# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Every program and library of a Linux package is built for its variant's processor (ROADMAP P2b.2)."""
import io
import lzma
import struct
import tarfile
import tempfile
import unittest
from pathlib import Path

from tools.release import elf_check as check


def elf(machine: int, interpreter: str | None = None, bits: int = 64, order: int = 1) -> bytes:
    """A minimal ELF file: the header, one program header (the loader's name, when given)."""
    if bits == 32:
        return b"\x7fELF" + bytes([1, order, 1]) + bytes(9) + struct.pack("<HH", 2, machine) + bytes(44)
    body = (interpreter.encode() + b"\0") if interpreter else b""
    phoff, phnum = 64, 1 if interpreter else 0
    header = (b"\x7fELF" + bytes([2, order, 1]) + bytes(9) + struct.pack("<HHIQQQIHHHHHH", 2, machine, 1, 0, phoff, 0,
                                                                         0, 64, 56, phnum, 64, 0, 0))
    ph = struct.pack("<IIQQQQQQ", check.PT_INTERP, 4, 64 + 56, 0, 0, len(body), len(body), 1) if interpreter else b""
    return header + ph + body


def deb(files: dict, xz: bool = True) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo("./" + name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    data = lzma.compress(raw.getvalue()) if xz else raw.getvalue()
    name = "data.tar.xz" if xz else "data.tar"

    def member(n: str, content: bytes) -> bytes:
        head = f"{n + '/':<16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(content):<10}`\n".encode()
        return head + content + (b"\n" if len(content) % 2 else b"")
    return b"!<arch>\n" + member("debian-binary", b"2.0\n") + member("control.tar.xz", lzma.compress(b"")) + \
        member(name, data)


class ReadTests(unittest.TestCase):
    def test_the_header_and_the_loader_are_read(self):
        info = check.read_elf(elf(183, "/lib/ld-linux-aarch64.so.1"))
        self.assertEqual((info["bits"], info["little"], info["machine"], info["interpreter"]),
                         (64, True, 183, "/lib/ld-linux-aarch64.so.1"))
        self.assertIsNone(check.read_elf(elf(62))["interpreter"])

    def test_damaged_files_are_refused_with_a_reason(self):
        for data in (b"", b"\x7fELF", b"MZ" + bytes(100), b"\x7fELF" + bytes([9, 1]) + bytes(80)):
            with self.subTest(data=data[:6]):
                with self.assertRaises(check.ElfError):
                    check.read_elf(data)
        cut = bytearray(elf(183, "/lib/ld-linux-aarch64.so.1"))
        struct.pack_into("<Q", cut, 64 + 8, 10 ** 6)          # the loader's name far past the end
        with self.assertRaises(check.ElfError):
            check.read_elf(bytes(cut))


class CheckTests(unittest.TestCase):
    def package(self, machine: int, loader: str) -> dict:
        return {check.PROGRAM: elf(machine, loader), "opt/kuchisofts/thoron/libEGL.so": elf(machine),
                "opt/kuchisofts/thoron/resources.pak": b"PAK", "usr/share/doc/thoron-browser/copyright": b"text"}

    def test_a_package_for_its_processor_passes(self):
        problems, elves = check.check(self.package(183, "/lib/ld-linux-aarch64.so.1").items(), "linux-arm64")
        self.assertEqual((problems, elves), ([], 2))
        problems, _ = check.check(self.package(62, "/lib64/ld-linux-x86-64.so.2").items(), "linux-x64")
        self.assertEqual(problems, [])

    def test_a_file_for_another_processor_or_loader_fails(self):
        files = self.package(183, "/lib/ld-linux-aarch64.so.1")
        files["opt/kuchisofts/thoron/libvk_swiftshader.so"] = elf(62)
        files["opt/kuchisofts/thoron/chrome_crashpad_handler"] = elf(183, "/lib64/ld-linux-x86-64.so.2")
        files["opt/kuchisofts/thoron/old.so"] = elf(40, bits=32)
        problems, _ = check.check(files.items(), "linux-arm64")
        self.assertEqual(len(problems), 4)              # x86-64; the x86-64 loader; 32-bit; and ARM 32-bit
        self.assertTrue(any("x86-64, not AArch64" in p for p in problems))

    def test_a_package_without_elf_files_or_the_program_fails(self):
        self.assertEqual(check.check({"a.txt": b"x"}.items(), "linux-x64")[0], ["no ELF file in the package"])
        self.assertIn("is not in the package", check.check({"opt/x.so": elf(62)}.items(), "linux-x64")[0][0])

    def test_a_deb_is_read_without_unpacking_it(self):
        with tempfile.TemporaryDirectory() as d:
            for xz in (True, False):
                path = Path(d) / f"thoron-{xz}.deb"
                path.write_bytes(deb(self.package(183, "/lib/ld-linux-aarch64.so.1"), xz))
                problems, elves = check.check(check.deb_files(path), "linux-arm64")
                self.assertEqual((problems, elves), ([], 2))
                self.assertEqual(check.main(["--deb", str(path), "--variant", "linux-x64"]), 1)
            bad = Path(d) / "bad.deb"
            bad.write_bytes(b"not a deb")
            self.assertEqual(check.main(["--deb", str(bad), "--variant", "linux-arm64"]), 1)


if __name__ == "__main__":
    unittest.main()
