#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Where a person can still read "Thorium" in a Thoron build, checked offline (ROADMAP B.3).

Reads an unpacked build (the folder that holds thoron.exe) and, when given, its mini installer. Nothing is
started. It looks at:
  - the version resource of every program file: what Windows shows as a file's properties;
  - the string tables of the installer and of the setup program packed in it (--sevenzip unpacks that one):
    the dialog texts, the name in Windows' list of apps and on the Start menu;
  - the text in the program files and in the resource packs (.pak): pages, menus, prompts and every
    translation. Entries packed with gzip are read; entries packed with brotli are read when --brotli names
    the brotli program of the build tree, and counted as unread otherwise.
Every "Thorium" found is sorted:
    seen      the product name where a person reads it: to fix
    unsorted  a kind of text this check does not know: look at it, then fix it or add it to a list below
    identity  names an installed copy is found by (registry keys): kept until a migration exists
    kept      credits, licence texts and the names of upstream's own work
    chromeos  texts about ChromeOS ("ThoriumOS"): packed with every language, shown on Windows or Linux at
              most in the permission list of an extension made for ChromeOS
    internal  names in code and files that no page shows (switches, resource and file names)
What only a running browser decides (a default, a switch) is not in the files: this check does not see it.

    py -3 -I tools/qa/identity_check.py --build <Chrome-bin> [--installer <mini installer>]
        [--sevenzip <7za.exe>] [--brotli <brotli.exe>] [--work <scratch dir>] [--json <file>]
Exit status 0 only when nothing is "seen" or "unsorted".
"""
import argparse
import gzip
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

CLASSES = ("seen", "unsorted", "identity", "kept", "chromeos", "internal")
NAME = re.compile(r"(?i)thorium")
# The name as a word a person reads, also inflected or joined with a hyphen as translations do: not part of an
# identifier (ThoriumIcon), a path or an address.
SEEN = re.compile(r"(?<![/\\.@%_])Thorium(?![A-Z0-9_/\\]|\.\w)")
# Shown to a person although the text around it would be kept or internal.
SEEN_ANYWAY = [re.compile(p) for p in (
    r"thorium\.rocks/welcome",                               # the page opened on the first start
    r"Alex313031/thorium\">\$i18n\{company\}",               # the link on Thoron's own company line
)]
# Names an installed copy is found by: not renamed without a migration (docs/build/IDENTITY_LEFT.md).
IDENTITY = re.compile(r"(?i)software\\(?:microsoft\\windows\\currentversion\\uninstall\\)?thorium\b(?:\\NativeMessagingHosts)?")
# Credits, licences and the names of upstream's own work.
KEEP = [re.compile(p) for p in (
    r"Alex313031",                                           # a line that names the upstream author
    r"based on Thorium|Thorium by |the Thorium project",     # Thoron's own "based on" lines
    r"Thorium source code is available",                     # the credits page: where upstream's source is
    r"<span class=\"title\">Thorium</span>",                 # the credits page: upstream's entry
    r"Thorium Authors",                                      # the page that lists upstream's authors
    r"Thorium 2024|Th24",                                    # upstream's interface design, by its name
    r"Thorium Custom Icons|Thorium's custom icons",          # upstream's icon set, by its name
    r"Neither the name of|Redistribution and use|BSD 3-Clause|THE SOFTWARE IS PROVIDED",   # licence texts
)]
CHROMEOS = re.compile(r"Thorium(?:OS|Vox|bit\b|base\b|box\b)")
# Names no page shows. A match counts when it covers the found name.
INTERNAL = [re.compile(p) for p in (
    r"thorium[-_][\w.\-]*",                                  # thorium-2024, thorium_version.txt, thorium_debug.log
    r"[\w.\-/]*[-_]thorium\b[\w.\-]*",                       # disable-thorium-icons, images/hazard_thorium.svg
    r"\w*Thorium[A-Z0-9]\w*",                                # kStarThoriumIcon, Thorium2024, a feature's name
    r"thorium[A-Z0-9]\w*",                                   # thoriumInternalUrlSchemeBranding
    r"\w*THORIUM\w*",                                        # THORIUM_DEBUG, IDR_THORIUM_FOLDER_CLOSED
    r"thorium:(?://)?",                                      # the address alias, shown only when its flag is on
    r"\[thorium[\w\-]*\]|\{thorium\w*\}",                    # style and template names
)]
PROGRAM_SUFFIXES = (".exe", ".dll")
RT_STRING, RT_VERSION = "6", "16"
PAYLOAD_TYPES = ("B7", "BL", "BN")                           # what a mini installer carries packed
BROTLI_MAGIC = b"\x1e\x9b"
NOT_TEXT = chr(0xFFFD)                                       # what decoding puts in place of bytes that are no text
WINDOW = 120


def classify(text: str) -> str:
    """The class of a text: the most serious one of the names in it."""
    worst = len(CLASSES) - 1
    whole = text.strip()
    for m in NAME.finditer(text):
        near = text[max(0, m.start() - WINDOW):m.end() + WINDOW]
        if any(p.search(near) for p in SEEN_ANYWAY):
            found = "seen"
        elif any(i.start() <= m.start() and m.end() <= i.end() for i in IDENTITY.finditer(text)):
            found = "identity"
        elif any(p.search(near) for p in KEEP):
            found = "kept"
        elif CHROMEOS.match(text, m.start()):
            found = "chromeos"
        elif SEEN.match(text, m.start()):
            found = "seen"
        elif whole.lower() == "thorium" or any(i.start() <= m.start() and m.end() <= i.end()
                                               for p in INTERNAL for i in p.finditer(text)):
            found = "internal"
        else:
            found = "unsorted"
        worst = min(worst, CLASSES.index(found))
    return CLASSES[worst]


def pe_resources(data: bytes) -> list[tuple[str, str, int, int]]:
    """(type, name, file offset, size) of every resource of a program file; empty when it has none."""
    if data[:2] != b"MZ" or len(data) < 0x40:
        return []
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return []
    count, = struct.unpack_from("<H", data, pe + 6)
    opt_size, = struct.unpack_from("<H", data, pe + 20)
    opt = pe + 24
    magic, = struct.unpack_from("<H", data, opt)
    rva, _ = struct.unpack_from("<II", data, opt + (112 if magic == 0x20B else 96) + 16)
    if not rva:
        return []
    sections = [struct.unpack_from("<IIII", data, opt + opt_size + 40 * i + 8) for i in range(count)]

    def offset(address: int) -> int:
        for virtual_size, virtual, raw_size, raw in sections:
            if virtual <= address < virtual + max(virtual_size, raw_size):
                return address - virtual + raw
        raise ValueError("resource outside every section")

    base = offset(rva)

    def name_of(value: int) -> str:
        if value & 0x80000000:
            at = base + (value & 0x7FFFFFFF)
            length, = struct.unpack_from("<H", data, at)
            return data[at + 2:at + 2 + 2 * length].decode("utf-16-le", "replace")
        return str(value)

    out = []

    def walk(directory: int, path: list[str]) -> None:
        named, by_id = struct.unpack_from("<HH", data, base + directory + 12)
        for i in range(named + by_id):
            name, target = struct.unpack_from("<II", data, base + directory + 16 + 8 * i)
            here = path + [name_of(name)]
            if target & 0x80000000:
                if len(here) < 3:
                    walk(target & 0x7FFFFFFF, here)
            else:
                address, size = struct.unpack_from("<II", data, base + target)
                out.append((here[0], here[1] if len(here) > 1 else "", offset(address), size))

    walk(0, [])
    return out


def version_strings(blob: bytes) -> dict[str, str]:
    """The named texts of a version resource (ProductName, FileDescription, ...)."""
    out: dict[str, str] = {}

    def nodes(pos: int, end: int, depth: int) -> None:
        while pos + 6 <= end:
            length, value_length, kind = struct.unpack_from("<HHH", blob, pos)
            if length < 6:
                return
            stop = min(pos + length, end)
            key_end = pos + 6
            while key_end + 2 <= stop and blob[key_end:key_end + 2] != b"\0\0":
                key_end += 2
            key = blob[pos + 6:key_end].decode("utf-16-le", "replace")
            value = (key_end + 2 + 3) & ~3
            if depth == 3:
                size = 2 * value_length if kind == 1 else value_length
                out[key] = blob[value:min(value + size, stop)].decode("utf-16-le", "replace").split("\0")[0]
            elif depth == 0:
                nodes((value + value_length + 3) & ~3, stop, 1)
            elif depth == 2 or key == "StringFileInfo":
                nodes(value, stop, depth + 1)
            pos = (stop + 3) & ~3

    nodes(0, len(blob), 0)
    return out


def string_table(blob: bytes, block: int) -> dict[int, str]:
    """The texts of one block of a string table, by their number."""
    out, pos = {}, 0
    for i in range(16):
        if pos + 2 > len(blob):
            break
        length, = struct.unpack_from("<H", blob, pos)
        pos += 2
        if length:
            out[(block - 1) * 16 + i] = blob[pos:pos + 2 * length].decode("utf-16-le", "replace")
        pos += 2 * length
    return out


def pak_entries(data: bytes):
    """(number, bytes) of every entry of a resource pack (format 4 or 5)."""
    version, = struct.unpack_from("<I", data, 0)
    if version == 5:
        count, = struct.unpack_from("<H", data, 8)
        pos = 12
    elif version == 4:
        count, = struct.unpack_from("<I", data, 4)
        pos = 9
    else:
        raise ValueError(f"resource pack format {version} is not known")
    index = [struct.unpack_from("<HI", data, pos + 6 * i) for i in range(count + 1)]
    for (number, start), (_, end) in zip(index, index[1:]):
        yield number, data[start:end]


def texts_in(data: bytes, skip: list[tuple[int, int]] = ()) -> list[str]:
    """Each place where the name stands in raw bytes, as 8-bit or as UTF-16 text, with the text around it."""
    out = []
    for m in re.finditer(rb"(?i)t\0h\0o\0r\0i\0u\0m\0", data):
        if any(a <= m.start() < b for a, b in skip):
            continue
        start = m.start()
        while start - 2 >= max(0, m.start() - 2 * WINDOW) and _printable(data[start - 2] | data[start - 1] << 8):
            start -= 2
        end = m.end()
        while end + 2 <= min(len(data), m.end() + 2 * WINDOW) and _printable(data[end] | data[end + 1] << 8):
            end += 2
        out.append(data[start:end].decode("utf-16-le", "replace"))
    for m in re.finditer(rb"(?i)thorium", data):
        if any(a <= m.start() < b for a, b in skip):
            continue
        start = m.start()
        while start > max(0, m.start() - WINDOW) and data[start - 1] >= 32 and data[start - 1] != 127:
            start -= 1
        end = m.end()
        while end < min(len(data), m.end() + WINDOW) and data[end] >= 32 and data[end] != 127:
            end += 1
        # bytes that are not text end the text on that side
        before = data[start:m.start()].decode("utf-8", "replace").rpartition(NOT_TEXT)[2]
        after = data[m.end():end].decode("utf-8", "replace").partition(NOT_TEXT)[0]
        out.append(" ".join((before + m.group(0).decode("ascii") + after).split()))
    return out


def _printable(unit: int) -> bool:
    # Latin text only: UTF-16 text in a program's code is that, and anything wider would read 8-bit
    # neighbours as letters. Translated texts live in string tables and packs, which are read entry by entry.
    return 32 <= unit < 0x180 and unit != 127


def scan_program(name: str, data: bytes) -> tuple[list[dict], dict]:
    """Findings of one program file and its version texts."""
    found, skip, version = [], [], {}
    try:
        resources = pe_resources(data)
    except (ValueError, struct.error):
        resources = []
    for kind, res_name, start, size in resources:
        blob = data[start:start + size]
        if kind == RT_VERSION:
            version = version_strings(blob)
            skip.append((start, start + size))
            found += [{"file": name, "where": f"properties: {k}", "text": v} for k, v in version.items() if NAME.search(v)]
        elif kind == RT_STRING and res_name.isdigit():
            skip.append((start, start + size))
            found += [{"file": name, "where": f"string {n}", "text": t}
                      for n, t in string_table(blob, int(res_name)).items() if NAME.search(t)]
        elif kind in PAYLOAD_TYPES:
            skip.append((start, start + size))
    found += [{"file": name, "where": "text", "text": t} for t in texts_in(data, skip)]
    return found, version


def unbrotli(blobs: dict[str, bytes], program: str, work: Path) -> dict[str, bytes]:
    """Unpack brotli entries with the build tree's brotli program (each starts with grit's 8-byte header)."""
    work.mkdir(parents=True, exist_ok=True)
    out = {}
    names = list(blobs)
    for name in names:
        (work / f"{name}.br").write_bytes(blobs[name][8:])
    for i in range(0, len(names), 200):
        batch = [str(work / f"{n}.br") for n in names[i:i + 200]]
        subprocess.run([program, "-d", "-f", *batch], capture_output=True, check=False)
    for name in names:
        unpacked = work / name
        if unpacked.is_file():
            out[name] = unpacked.read_bytes()
    return out


def scan_pak(name: str, data: bytes, brotli: str | None, work: Path | None) -> tuple[list[dict], int]:
    """Findings of one resource pack and the number of entries that could not be read."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    found, packed = [], {}
    for number, blob in pak_entries(data):
        if blob[:2] == b"\x1f\x8b":
            try:
                blob = gzip.decompress(blob)
            except (OSError, EOFError):
                pass
        elif blob[:2] == BROTLI_MAGIC:
            packed[str(number)] = blob
            continue
        found += [{"file": name, "where": f"entry {number}", "text": t} for t in texts_in(blob)]
    unread = len(packed)
    if packed and brotli and work:
        unpacked = unbrotli(packed, brotli, work / re.sub(r"\W", "_", name))
        unread -= len(unpacked)
        for number, blob in unpacked.items():
            found += [{"file": name, "where": f"entry {number}", "text": t} for t in texts_in(blob)]
    return found, unread


def installer_payloads(data: bytes) -> dict[str, bytes]:
    """What a mini installer carries packed, by resource name (the browser archive and the setup program)."""
    return {name: data[start:start + size] for kind, name, start, size in pe_resources(data) if kind in PAYLOAD_TYPES}


def unpack_setup(payloads: dict[str, bytes], sevenzip: str, work: Path) -> Path | None:
    """The setup program out of a mini installer's payload, unpacked with 7-Zip into the scratch folder."""
    for name, blob in payloads.items():
        if not name.upper().startswith("SETUP"):
            continue
        work.mkdir(parents=True, exist_ok=True)
        packed = work / name.lower()
        packed.write_bytes(blob)
        if blob[:2] == b"MZ":
            return packed
        subprocess.run([sevenzip, "x", "-y", f"-o{work}", str(packed)], capture_output=True, check=False)
        for candidate in work.rglob("setup.exe"):
            return candidate
    return None


def scan(build: Path | None, installer: Path | None = None, sevenzip: str | None = None, brotli: str | None = None,
         work: Path | None = None) -> dict:
    """Everything found, each with its class, the version texts of the program files and what was not read."""
    found, properties, notes, unread = [], {}, [], 0
    if build:
        for path in sorted(p for p in build.rglob("*") if p.is_file()):
            name = path.relative_to(build).as_posix()
            data = path.read_bytes()
            if path.suffix.lower() == ".pak":
                part, missed = scan_pak(name, data, brotli, work / "pak" if work else None)
                unread += missed
            elif path.suffix.lower() in PROGRAM_SUFFIXES:
                part, version = scan_program(name, data)
                if version:
                    properties[name] = version
            else:
                part = [{"file": name, "where": "text", "text": t} for t in texts_in(data)]
            found += part
    if installer:
        data = installer.read_bytes()
        part, version = scan_program(installer.name, data)
        found += part
        properties[installer.name] = version
        setup = unpack_setup(installer_payloads(data), sevenzip, work / "setup") if sevenzip and work else None
        if setup:
            part, version = scan_program(f"{installer.name}: setup.exe", setup.read_bytes())
            found += part
            properties[f"{installer.name}: setup.exe"] = version
        else:
            notes.append("the setup program inside the installer was not read (give --sevenzip)")
    if unread:
        notes.append(f"{unread} packed page(s) and script(s) were not read (give --brotli)")
    for item in found:
        # a file's properties describe the product itself: credits there never name Thorium, so any hit is shown
        item["class"] = "seen" if item["where"].startswith("properties:") else classify(item["text"])
    return {"found": found, "properties": properties, "notes": notes}


def report(result: dict, examples: int = 3) -> list[str]:
    """The result as lines: every text to fix, the rest counted by kind."""
    lines = []
    by_class = {c: [f for f in result["found"] if f["class"] == c] for c in CLASSES}
    for name in ("seen", "unsorted"):
        items = by_class[name]
        lines.append(f"{name}: {len(items)}")
        per_file: dict[str, Counter] = {}
        for f in items:
            per_file.setdefault(f["file"], Counter())[f"[{f['where'].split(' ')[0]}] {f['text'][:150]}"] += 1
        for file, texts in sorted(per_file.items()):
            shown = texts.most_common() if len(texts) <= 40 else texts.most_common(examples)
            lines.append(f"  {file}: {sum(texts.values())} in {len(texts)} text(s)")
            lines += [f"    {text}" for text, _ in shown]
            if len(shown) < len(texts):
                lines.append(f"    ... and {len(texts) - len(shown)} more text(s)")
    for name in ("identity", "kept", "chromeos", "internal"):
        items = by_class[name]
        lines.append(f"{name}: {len(items)} in {len({f['file'] for f in items})} file(s)")
        if name == "identity":
            lines += [f"  {text} ({n})" for text, n in Counter(f["text"][:100] for f in items).most_common()]
    lines += [f"note: {n}" for n in result["notes"]]
    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build", type=Path, help="the unpacked build: the folder that holds thoron.exe")
    parser.add_argument("--installer", type=Path, help="the mini installer of the same build")
    parser.add_argument("--sevenzip", help="7-Zip program, to read the setup program inside the installer")
    parser.add_argument("--brotli", help="brotli program of the build tree, to read the pages packed with it")
    parser.add_argument("--work", type=Path, help="scratch folder (a temporary one when not given)")
    parser.add_argument("--json", type=Path, help="write everything found to this file")
    a = parser.parse_args(argv)
    if not a.build and not a.installer:
        parser.error("give --build, --installer or both")
    work = a.work or Path(tempfile.mkdtemp(prefix="identity-check-"))
    try:
        result = scan(a.build, a.installer, a.sevenzip, a.brotli, work)
    finally:
        if not a.work:
            shutil.rmtree(work, ignore_errors=True)
    if a.json:
        a.json.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for line in report(result):
        print(line)
    for file, version in sorted(result["properties"].items()):
        if file.endswith(("thoron.exe", "setup.exe")) or file == (a.installer.name if a.installer else ""):
            print(f"properties of {file}: " + "; ".join(f"{k}={version.get(k, '')}" for k in (
                "ProductName", "FileDescription", "CompanyName", "LegalCopyright", "Comments") if k in version))
    counts = Counter(f["class"] for f in result["found"])
    bad = counts["seen"] + counts["unsorted"]
    print(f"identity check: {'OK' if not bad else f'{bad} to fix or sort'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
