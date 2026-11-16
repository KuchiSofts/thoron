#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Delta packages (ROADMAP P4.1): the files of a newer version made from those of an older one.

A delta turns the version folder of one release (the build's Chrome-bin folder, `Application\\<version>` of a
portable copy) into that of a newer one. For each file of the newer folder it holds one of:

    same    the file of the older folder at the same place (the folder named after the version is matched to
            the newer one's), byte for byte; nothing is stored
    patch   a Zucchini patch (Chromium's components/zucchini) from that older file; kept only when it is clearly
            smaller than the file (at most 80 %)
    whole   the file itself

The delta is a .zip, reproducible as the portable package is (sorted names, one fixed time):

    delta.json          {"format": 1, "from": <older version>, "to": <newer version>, "files": [...]}, each file
                        with its path, size and SHA-256 in the newer folder, how it is made, and for `same` and
                        `patch` the older file's path and SHA-256
    patch/<n>           the patches
    whole/<n>           the whole files

Before a delta is kept it is applied, with the Zucchini tool, to the older folder in a scratch folder, and every
file is compared with the newer one: a delta that does not give the newer files byte for byte is never written.
The updater applies a delta with the same Zucchini code (thoron_update --apply-delta) and checks every file
against its SHA-256 before the swap.

    py -3 -I tools/release/delta.py make --old <older version folder> --new <newer version folder>
        --zucchini <out>\\zucchini.exe --out <file.delta> [--work <scratch dir>]
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

FORMAT = 1
EPOCH = 315532800                   # 1980-01-01, as the portable package
MOST_PATCH_SHARE = 0.8              # a patch is kept when it is at most this share of the file
_VERSION = re.compile(r"^\d+(\.\d+){3}$")


class DeltaError(Exception):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def files(folder: Path) -> list[str]:
    """Every file below `folder`, as sorted paths with `/`. A link is refused."""
    out = []
    for base, dirs, names in os.walk(folder):
        for name in dirs + names:
            if os.path.islink(os.path.join(base, name)):
                raise DeltaError(f"{name} is a link")
        out += [Path(base, name).relative_to(folder).as_posix() for name in names]
    return sorted(out)


def version_of(names: list[str]) -> str:
    found = sorted({n.split("/", 1)[0] for n in names if "/" in n and _VERSION.match(n.split("/", 1)[0])})
    if len(found) != 1:
        raise DeltaError(f"one version folder is expected inside, found {found or 'none'}")
    return found[0]


def older_path(path: str, old_version: str, new_version: str) -> str:
    """Where a file of the newer folder was in the older one: the folder named after the version is matched."""
    head, _, rest = path.partition("/")
    return f"{old_version}/{rest}" if rest and head == new_version else path


def plan(old: Path, new: Path, gen, scratch: Path,
         keep_share: float = MOST_PATCH_SHARE) -> tuple[list[dict], dict[int, Path]]:
    """What the delta holds for each file of `new`, and the patch and whole files it stores by entry number
    (patches are made in `scratch`). `gen(old_file, new_file, patch_file)` makes a patch and answers whether it
    worked."""
    old_names, new_names = files(old), files(new)
    old_version, new_version = version_of(old_names), version_of(new_names)
    old_set = set(old_names)
    entries, stored = [], {}
    for n, name in enumerate(new_names):
        target = new / name
        entry = {"path": name, "size": target.stat().st_size, "sha256": sha256(target)}
        source = older_path(name, old_version, new_version)
        if source in old_set:
            source_sha = sha256(old / source)
            if source_sha == entry["sha256"]:
                entries.append(dict(entry, how="same", from_path=source, from_sha256=source_sha))
                continue
            patch = scratch / f"{n}.zuc"
            if entry["size"] > 0 and gen(old / source, target, patch) and patch.is_file() and \
                    patch.stat().st_size <= keep_share * entry["size"]:
                kept = scratch / f"patch-{n}"
                patch.replace(kept)
                stored[n] = kept
                entries.append(dict(entry, how="patch", from_path=source, from_sha256=source_sha))
                continue
            patch.unlink(missing_ok=True)
        stored[n] = target
        entries.append(dict(entry, how="whole"))
    return entries, stored


def manifest(entries: list[dict], old_version: str, new_version: str) -> bytes:
    return (json.dumps({"format": FORMAT, "from": old_version, "to": new_version, "files": entries},
                       indent=1, sort_keys=True) + "\n").encode("ascii")


def write(out: Path, entries: list[dict], stored: dict[int, Path], old_version: str, new_version: str,
          epoch: int = EPOCH) -> None:
    stamp = time.gmtime(epoch)[:6]
    with zipfile.ZipFile(out, "x", zipfile.ZIP_DEFLATED) as z:
        def put(name: str, data_path: Path | None = None, data: bytes | None = None) -> None:
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0x20
            if data is not None:
                z.writestr(info, data)
            else:
                with data_path.open("rb") as f, z.open(info, "w") as w:
                    shutil.copyfileobj(f, w, 1 << 20)
        put("delta.json", data=manifest(entries, old_version, new_version))
        for n, entry in enumerate(entries):
            if entry["how"] in ("patch", "whole"):
                put(f"{entry['how']}/{n}", data_path=stored[n])


def apply_with_tool(delta: Path, old: Path, into: Path, zucchini: Path) -> list[str]:
    """Applies `delta` to the older folder `old` into the empty folder `into` with the Zucchini tool, and gives
    the problems: each file whose result is not, byte for byte, the newer file the delta names."""
    problems = []
    with zipfile.ZipFile(delta) as z:
        data = json.loads(z.read("delta.json"))
        for n, entry in enumerate(data["files"]):
            target = into / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry["how"] == "same":
                shutil.copyfile(old / entry["from_path"], target)
            elif entry["how"] == "whole":
                with z.open(f"whole/{n}") as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
            else:
                patch = into.parent / f"patch-{n}.zuc"
                with z.open(f"patch/{n}") as src, patch.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                done = subprocess.run([str(zucchini), "-apply", str(old / entry["from_path"]), str(patch),
                                       str(target)], capture_output=True, text=True)
                patch.unlink(missing_ok=True)
                if done.returncode != 0:
                    problems.append(f"{entry['path']}: the patch does not apply ({done.returncode})")
                    continue
            if not target.is_file() or sha256(target) != entry["sha256"]:
                problems.append(f"{entry['path']}: not the newer file byte for byte")
    return problems


def make(old: Path, new: Path, zucchini: Path, out: Path, work: Path | None = None) -> dict:
    """Makes the delta from `old` to `new` at `out`, checks it by applying it, and reports its size."""
    if out.exists():
        raise DeltaError(f"{out.name} is already there; a delta is never overwritten")
    old_version, new_version = version_of(files(old)), version_of(files(new))
    if old_version == new_version:
        raise DeltaError("the two folders are the same version")

    def gen(a: Path, b: Path, patch: Path) -> bool:
        return subprocess.run([str(zucchini), "-gen", str(a), str(b), str(patch)], capture_output=True).returncode == 0

    scratch = Path(tempfile.mkdtemp(prefix="delta-", dir=work))
    try:
        entries, stored = plan(old, new, gen, scratch)
        write(out, entries, stored, old_version, new_version)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    check = Path(tempfile.mkdtemp(prefix="delta-check-", dir=work))
    try:
        problems = apply_with_tool(out, old, check / new_version, zucchini)
    finally:
        shutil.rmtree(check, ignore_errors=True)
    if problems:
        out.unlink(missing_ok=True)
        raise DeltaError("the delta does not give the newer files: " + "; ".join(problems[:5]))
    counts = {how: sum(1 for e in entries if e["how"] == how) for how in ("same", "patch", "whole")}
    return {"from": old_version, "to": new_version, "files": len(entries), **counts,
            "delta_bytes": out.stat().st_size, "new_bytes": sum(e["size"] for e in entries)}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--old", type=Path, required=True, help="the older release's version folder (or Chrome-bin)")
    m.add_argument("--new", type=Path, required=True, help="the newer release's version folder (or Chrome-bin)")
    m.add_argument("--zucchini", type=Path, required=True, help="Chromium's zucchini.exe")
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--work", type=Path, help="where the check applies the delta (default: the system's temp)")
    a = p.parse_args(argv)
    try:
        report = make(a.old, a.new, a.zucchini, a.out, a.work)
    except (DeltaError, OSError) as exc:
        print(f"delta: {exc}", file=sys.stderr)
        return 2
    share = 100 * report["delta_bytes"] / max(1, report["new_bytes"])
    print(f"delta: {report['from']} -> {report['to']}: {report['files']} files ({report['same']} same, "
          f"{report['patch']} patched, {report['whole']} whole); {report['delta_bytes']} bytes, "
          f"{share:.1f} % of the {report['new_bytes']} bytes of the newer files; applied and checked")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
