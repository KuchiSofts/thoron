# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Where a person can still read "Thorium" in a build: the offline check (ROADMAP B.3)."""
import contextlib
import gzip
import io
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from tools.qa import identity_check as ic


def make_version(strings: dict[str, str]) -> bytes:
    """A version resource with the given named texts."""
    def node(key: str, value: bytes = b"", children: bytes = b"", text: bool = False) -> bytes:
        head = 6 + 2 * (len(key) + 1)
        body = value + b"\0" * (-len(value) % 4) + children if children else value
        size = len(value) // 2 if text else len(value)
        out = struct.pack("<HHH", head + (-head % 4) + len(body), size, int(text)) + (key + "\0").encode("utf-16-le")
        return out + b"\0" * (-head % 4) + body

    entries = b""
    for key, value in strings.items():
        entry = node(key, (value + "\0").encode("utf-16-le"), text=True)
        entries += entry + b"\0" * (-len(entry) % 4)
    info = node("StringFileInfo", children=node("040904b0", children=entries))
    return node("VS_VERSION_INFO", value=b"\0" * 52, children=info)


def make_strings(first_number: int, texts: list[str]) -> tuple[int, bytes]:
    """One block of a string table: (block number, bytes)."""
    slots = [""] * (first_number % 16) + texts
    slots += [""] * (16 - len(slots))
    return first_number // 16 + 1, b"".join(struct.pack("<H", len(t)) + t.encode("utf-16-le") for t in slots)


def make_pe(resources: list[tuple]) -> bytes:
    """A minimal 64-bit program file with resources: (type, name, bytes), type and name a number or a text."""
    def order(keys):
        return sorted(keys, key=lambda k: (isinstance(k, int), k))

    by_type: dict = {}
    for kind, name, blob in resources:
        by_type.setdefault(kind, {})[name] = blob
    kinds = order(by_type)
    leaves = [(kind, name, by_type[kind][name]) for kind in kinds for name in order(by_type[kind])]
    type_at, pos = [], 16 + 8 * len(kinds)
    for kind in kinds:
        type_at.append(pos)
        pos += 16 + 8 * len(by_type[kind])
    leaf_at, entry_at = pos, pos + 24 * len(leaves)
    text_at = entry_at + 16 * len(leaves)
    texts, text_pos = bytearray(), {}
    for key in [k for k in kinds if isinstance(k, str)] + [n for _, n, _ in leaves if isinstance(n, str)]:
        if key not in text_pos:
            text_pos[key] = text_at + len(texts)
            texts += struct.pack("<H", len(key)) + key.encode("utf-16-le")
    data_at = (text_at + len(texts) + 3) & ~3
    rva, raw = 0x1000, 0x200

    def directory(entries) -> bytes:
        named = sum(1 for key, _ in entries if isinstance(key, str))
        out = struct.pack("<IIHHHH", 0, 0, 0, 0, named, len(entries) - named)
        return out + b"".join(struct.pack("<II", 0x80000000 | text_pos[key] if isinstance(key, str) else key, target)
                              for key, target in entries)

    section = bytearray(directory([(kind, 0x80000000 | type_at[i]) for i, kind in enumerate(kinds)]))
    index = 0
    for kind in kinds:
        entries = []
        for name in order(by_type[kind]):
            entries.append((name, 0x80000000 | (leaf_at + 24 * index)))
            index += 1
        section += directory(entries)
    for i in range(len(leaves)):
        section += directory([(1033, entry_at + 16 * i)])
    blobs = bytearray()
    for _, _, blob in leaves:
        section += struct.pack("<IIII", rva + data_at + len(blobs), len(blob), 0, 0)
        blobs += blob + b"\0" * (-len(blob) % 4)
    section += texts
    section += b"\0" * (data_at - len(section)) + blobs
    head = bytearray(raw)
    head[:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 0x80)
    head[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", head, 0x84, 0x8664, 1, 0, 0, 0, 240, 0x22)
    struct.pack_into("<H", head, 0x98, 0x20B)
    struct.pack_into("<II", head, 0x98 + 112 + 16, rva, len(section))
    struct.pack_into("<8sIIII", head, 0x98 + 240, b".rsrc", len(section), rva, len(section), raw)
    return bytes(head) + bytes(section)


def make_pak(entries: dict[int, bytes]) -> bytes:
    """A resource pack (format 5) with the given entries."""
    numbers = sorted(entries)
    start = 12 + 6 * (len(numbers) + 1)
    index, body = b"", b""
    for number in numbers:
        index += struct.pack("<HI", number, start + len(body))
        body += entries[number]
    index += struct.pack("<HI", 0, start + len(body))
    return struct.pack("<IB3xHH", 5, 1, len(numbers), 0) + index + body


class ClassifyTests(unittest.TestCase):
    CASES = {
        "seen": ["About Thorium", "Do you want to install Thorium?", "<h1>Thorium URLs</h1>", "Thorium Rectangular Tabs UI",
                 "Thoriumin asetukset", "Thorium-Profil", "ku-Thorium.", "从Thorium中移除",
                 "This Thorium flag is enabled by default.", "https://thorium.rocks/welcome/",
                 'href="https://github.com/Alex313031/thorium">$i18n{company}</a>',
                 "ThoriumOS could not save Thorium data"],
        "unsorted": ["https://thorium.rocks/optimizations", "Thorium/Thorium"],
        "identity": ["Software\\Thorium", "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Thorium",
                     "SOFTWARE\\Thorium\\NativeMessagingHosts"],
        "kept": ["Thoron is an independent browser by KuchiSofts, based on Thorium by Alex313031 and Chromium by The "
                 "Chromium Authors. It is not affiliated with or endorsed by the Thorium project or Google.",
                 "<title>Thorium Authors</title>", "Enable Experimental Thorium 2024 (Th24) UI",
                 "Disable Thorium Custom Icons", "instead of Thorium's custom icons throughout the browser UI.",
                 '<span class="title">Thorium</span>', 'here</a>. Thorium source code is available <a href="x">here</a>',
                 "https://github.com/Alex313031/Thorium"],
        "chromeos": ["Restart ThoriumOS", "ThoriumVox", "ThoriumOS-Einstellungen"],
        "internal": ["thorium", "thorium-2024", "kStarThoriumIcon", "Thorium2024", "images/hazard_thorium.svg",
                     "text/thorium_version.txt", "THORIUM_DEBUG", "IDR_THORIUM_FOLDER_CLOSED", "disable-thorium-icons",
                     "Use thorium:// for internal URLs", ":host-context([thorium-2024]){border-radius:4px}",
                     "$i18n{thorium2024} $i18n{webuiRefresh2026}", 'getBoolean("thoriumInternalUrlSchemeBranding")',
                     "no name in here"],
    }

    def test_each_kind_of_text(self):
        for expected, texts in self.CASES.items():
            for text in texts:
                self.assertEqual(ic.classify(text), expected, text)

    def test_the_most_serious_name_in_a_text_counts(self):
        self.assertEqual(ic.classify("thorium-2024 and kThoriumIcon, then: Open Thorium"), "seen")
        self.assertEqual(ic.classify("Software\\Thorium and thorium-2024"), "identity")

    def test_a_credit_far_from_the_name_does_not_cover_it(self):
        self.assertEqual(ic.classify("by Alex313031" + " x" * 100 + " Open Thorium now"), "seen")


class FormatTests(unittest.TestCase):
    def test_version_texts(self):
        blob = make_version({"ProductName": "Thoron", "FileDescription": "Thoron Installer", "Comments": "a b"})
        self.assertEqual(ic.version_strings(blob), {"ProductName": "Thoron", "FileDescription": "Thoron Installer",
                                                    "Comments": "a b"})
        self.assertEqual(ic.version_strings(b"\0" * 40), {})

    def test_string_table(self):
        block, blob = make_strings(1602, ["Do you want to install $1?", "", "Thorium-apps"])
        self.assertEqual(ic.string_table(blob, block), {1602: "Do you want to install $1?", 1604: "Thorium-apps"})

    def test_program_resources_by_number_and_by_name(self):
        data = make_pe([(16, 1, b"VERSION!"), ("B7", "CHROME.PACKED.7Z", b"7z-data"), (6, 101, b"table")])
        found = {(kind, name): data[start:start + size] for kind, name, start, size in ic.pe_resources(data)}
        self.assertEqual(found, {("16", "1"): b"VERSION!", ("B7", "CHROME.PACKED.7Z"): b"7z-data", ("6", "101"): b"table"})
        self.assertEqual(ic.pe_resources(b"not a program"), [])
        self.assertEqual(ic.installer_payloads(data), {"CHROME.PACKED.7Z": b"7z-data"})

    def test_pack_entries(self):
        self.assertEqual(dict(ic.pak_entries(make_pak({7: b"seven", 9: b"", 300: b"three hundred"}))),
                         {7: b"seven", 9: b"", 300: b"three hundred"})
        with self.assertRaises(ValueError):
            list(ic.pak_entries(struct.pack("<I", 3) + b"\0" * 20))

    def test_text_in_bytes_as_8_bit_and_utf16(self):
        data = (b"\x00\x01\xff\xfeOpen Thorium now\x00\x02" + "Software\\Thorium".encode("utf-16-le") + b"\x00\x00\x07\x00"
                + "Kirjaudu Thoriumiin".encode("utf-8") + b"\x00")
        self.assertEqual(sorted(ic.texts_in(data)), ["Kirjaudu Thoriumiin", "Open Thorium now", "Software\\Thorium"])
        self.assertEqual(ic.texts_in(data, skip=[(0, len(data))]), [])


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="identity-check-test-"))
        self.build = self.tmp / "Chrome-bin"
        (self.build / "1.2.3.4" / "Locales").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_build(self, product: str, strings: dict[int, bytes]) -> None:
        program = make_pe([(16, 1, make_version({"ProductName": product, "CompanyName": "KuchiSofts"}))])
        (self.build / "thoron.exe").write_bytes(program + b"\0kStarThoriumIcon\0")
        (self.build / "1.2.3.4" / "Locales" / "en-US.pak").write_bytes(make_pak(strings))

    def classes(self, result: dict) -> dict:
        return {(f["file"].rsplit("/", 1)[-1], f["text"]): f["class"] for f in result["found"]}

    def test_a_build_that_still_names_thorium(self):
        self.write_build("Thorium", {100: b"About Thorium", 101: b"based on Thorium by Alex313031",
                                     102: gzip.compress(b"<h1>Thorium URLs</h1>"), 103: ic.BROTLI_MAGIC + b"\0" * 20})
        result = ic.scan(self.build)
        self.assertEqual(self.classes(result), {
            ("thoron.exe", "Thorium"): "seen", ("thoron.exe", "kStarThoriumIcon"): "internal",
            ("en-US.pak", "About Thorium"): "seen", ("en-US.pak", "based on Thorium by Alex313031"): "kept",
            ("en-US.pak", "<h1>Thorium URLs</h1>"): "seen"})
        self.assertEqual(result["properties"]["thoron.exe"]["ProductName"], "Thorium")
        self.assertEqual(result["notes"], ["1 packed page(s) and script(s) were not read (give --brotli)"])
        where = {f["text"]: f["where"] for f in result["found"]}
        self.assertEqual((where["Thorium"], where["About Thorium"]), ("properties: ProductName", "entry 100"))

    def test_an_installer_with_its_setup_program(self):
        block, table = make_strings(1600, ["Thorium-apps", "Thoron"])
        setup = make_pe([(16, 1, make_version({"ProductName": "Thorium Installer"}))])
        installer = self.tmp / "thoron_mini_installer.exe"
        installer.write_bytes(make_pe([(6, block, table), (16, 1, make_version({"Comments": "https://github.com/Alex313031/Thorium"})),
                                       ("BN", "SETUP.EXE", setup), ("B7", "CHROME.PACKED.7Z", b"7z" + b"Thorium" * 3)])
                              + "Software\\Thorium".encode("utf-16-le"))
        result = ic.scan(None, installer, sevenzip="not-needed-for-an-unpacked-setup", work=self.tmp / "work")
        self.assertEqual(self.classes(result), {
            ("thoron_mini_installer.exe", "Thorium-apps"): "seen",
            ("thoron_mini_installer.exe", "https://github.com/Alex313031/Thorium"): "seen",   # a file property
            ("thoron_mini_installer.exe", "Software\\Thorium"): "identity",
            ("thoron_mini_installer.exe: setup.exe", "Thorium Installer"): "seen"})   # nothing from the packed archive
        self.assertEqual(result["notes"], [])
        without = ic.scan(None, installer)
        self.assertEqual(without["notes"], ["the setup program inside the installer was not read (give --sevenzip)"])

    def test_exit_status_and_report(self):
        self.write_build("Thorium", {100: b"About Thorium", 101: b"Restart ThoriumOS"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = ic.main(["--build", str(self.build), "--json", str(self.tmp / "found.json")])
        text = out.getvalue()
        self.assertEqual(status, 1)
        self.assertIn("seen: 2", text)
        self.assertIn("    [entry] About Thorium", text)
        self.assertIn("chromeos: 1 in 1 file(s)", text)
        self.assertIn("properties of thoron.exe: ProductName=Thorium; CompanyName=KuchiSofts", text)
        self.assertTrue(text.rstrip().endswith("identity check: 2 to fix or sort"))
        self.assertTrue((self.tmp / "found.json").is_file())

    def test_a_clean_build_passes(self):
        self.write_build("Thoron", {100: b"About Thoron", 101: b"based on Thorium by Alex313031", 102: b"Restart ThoriumOS"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = ic.main(["--build", str(self.build)])
        self.assertEqual(status, 0)
        self.assertTrue(out.getvalue().rstrip().endswith("identity check: OK"))


if __name__ == "__main__":
    unittest.main()
