# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of pe_check.py (ROADMAP P2b.1) on small PE files made here."""
import struct
import tempfile
import unittest
from pathlib import Path

from tools.release import pe_check as pc


def make_pe(machine: int, imports=(), delayed=()) -> bytes:
    """A minimal PE32+ file: one section holding the import and delay-import tables and the DLL names."""
    section_rva, section_raw, section_size = 0x1000, 0x200, 0x400
    imp_at = 0
    delay_at = imp_at + 20 * (len(imports) + 1)
    names_at = delay_at + 32 * (len(delayed) + 1)
    body = bytearray(section_size)
    cursor = names_at
    for i, name in enumerate(imports):
        struct.pack_into("<IIIII", body, imp_at + 20 * i, 1, 0, 0, section_rva + cursor, 1)
        body[cursor:cursor + len(name) + 1] = name.encode() + b"\0"
        cursor += len(name) + 1
    for i, name in enumerate(delayed):
        struct.pack_into("<IIIIIIII", body, delay_at + 32 * i, 1, section_rva + cursor, 1, 1, 1, 0, 0, 0)
        body[cursor:cursor + len(name) + 1] = name.encode() + b"\0"
        cursor += len(name) + 1
    dos = bytearray(0x40)
    dos[:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)
    coff = b"PE\0\0" + struct.pack("<HHIIIHH", machine, 1, 0, 0, 0, 240, 0x22)
    optional = bytearray(240)
    struct.pack_into("<H", optional, 0, 0x20B)
    struct.pack_into("<I", optional, 108, 16)
    if imports:
        struct.pack_into("<II", optional, 112 + 8 * 1, section_rva + imp_at, 20 * (len(imports) + 1))
    if delayed:
        struct.pack_into("<II", optional, 112 + 8 * 13, section_rva + delay_at, 32 * (len(delayed) + 1))
    section = b".idata\0\0" + struct.pack("<IIIIIIHHI", section_size, section_rva, section_size, section_raw,
                                          0, 0, 0, 0, 0xC0000040)
    head = bytes(dos) + coff + bytes(optional) + section
    return head + b"\0" * (section_raw - len(head)) + bytes(body)


class PeReaderTests(unittest.TestCase):
    def test_machine_and_both_import_tables(self):
        pe = pc.Pe(make_pe(0xAA64, ["KERNEL32.dll", "chrome_elf.dll"], ["bthprops.cpl"]))
        self.assertEqual(pe.machine, 0xAA64)
        self.assertEqual(pe.imports(), ["KERNEL32.dll", "chrome_elf.dll", "bthprops.cpl"])

    def test_what_is_no_pe_file(self):
        for data in (b"", b"MZ" + b"\0" * 10, make_pe(0x8664, ["a.dll"])[:0x150], b"ZM" + b"\0" * 300):
            with self.subTest(data=data[:4]), self.assertRaises((pc.PeError, struct.error)):
                pc.Pe(data).imports()

    def test_variants(self):
        self.assertEqual(pc.machine_of("win-arm64-armv8"), 0xAA64)
        self.assertEqual(pc.machine_of("win-x64-sse4"), 0x8664)
        with self.assertRaises(pc.PeError):
            pc.machine_of("linux-x64-avx2")


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name: str, data: bytes) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def test_a_good_arm64_package(self):
        self.put("thoron.exe", make_pe(0xAA64, ["chrome_elf.dll", "KERNEL32.dll", "api-ms-win-core-synch-l1-2-0.dll"]))
        self.put("158.0.8127.6500/chrome_elf.dll", make_pe(0xAA64, ["ntdll.dll"], ["bthprops.cpl"]))
        self.put("158.0.8127.6500/notes.txt", b"not a program")
        problems, count = pc.check_folder(self.root, "win-arm64-armv8", {"kernel32.dll", "ntdll.dll", "bthprops.cpl"})
        self.assertEqual((problems, count), ([], 2))

    def test_what_is_found(self):
        self.put("thoron.exe", make_pe(0x8664, ["KERNEL32.dll"]))
        self.put("158.0.8127.6500/chrome.dll", make_pe(0xAA64, ["MSVCP140.dll", "vcruntime140_1.dll", "nowhere.dll"]))
        self.put("158.0.8127.6500/broken.dll", b"MZ broken")
        problems, _ = pc.check_folder(self.root, "win-arm64-armv8", {"kernel32.dll", "msvcp140.dll"})
        self.assertIn("thoron.exe: built for x64, not arm64", problems)
        self.assertIn("158.0.8127.6500/chrome.dll: imports MSVCP140.dll, Visual Studio's runtime, which a clean PC "
                      "does not have", problems)
        self.assertIn("158.0.8127.6500/chrome.dll: imports vcruntime140_1.dll, Visual Studio's runtime, which a "
                      "clean PC does not have", problems)
        self.assertIn("158.0.8127.6500/chrome.dll: imports nowhere.dll, which is neither in the package nor part of "
                      "Windows", problems)
        self.assertTrue(any(p.startswith("158.0.8127.6500/broken.dll: not a PE file") for p in problems))
        self.assertEqual(len(problems), 5, problems)

    def test_a_runtime_the_package_carries_is_fine(self):
        self.put("thoron.exe", make_pe(0x8664, ["vcruntime140.dll"]))
        self.put("vcruntime140.dll", make_pe(0x8664))
        self.assertEqual(pc.check_folder(self.root, "win-x64-avx2", set())[0], [])


if __name__ == "__main__":
    unittest.main()
