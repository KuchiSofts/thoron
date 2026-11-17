#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The programs and libraries of a Windows package, checked for the processor they are built for and for what
they load (ROADMAP P2b.1).

Every .exe and .dll in the folder is read as a PE file (its own reader, nothing is run):

    machine   the processor it is built for must be the variant's: x64 (0x8664) for win-x64-*, ARM64 (0xAA64)
              for win-arm64-*; a file for another processor would not start, or would start emulated
    imports   every DLL it loads at start or on first use (its import and delay-import tables) must be in the
              package (beside it, or in the package's version folder) or be part of Windows; the C and C++
              runtime of Visual Studio (msvcp*, vcruntime*, the debug ones) is no part of Windows and must not
              be imported, so a clean PC can start the program

"Part of Windows" is an API set name (api-ms-win-*, ext-ms-*) or a DLL in the system folder of the Windows the
check runs on (--system32), the same names on x64 and ARM64 Windows.

    py -3 -I tools/release/pe_check.py --folder <Chrome-bin> --variant win-arm64-armv8 [--system32 C:\\Windows\\System32]
Exit status 0 when every file passes.
"""
from __future__ import annotations

import argparse
import os
import re
import struct
import sys
from pathlib import Path

MACHINES = {0x8664: "x64", 0xAA64: "arm64", 0x14C: "x86", 0xA641: "arm64ec", 0x1C4: "arm"}
VARIANT_MACHINE = {"x64": 0x8664, "arm64": 0xAA64}
RUNTIME = re.compile(r"(?i)^(msvcp\d+.*|vcruntime\d+.*|concrt\d+.*|vccorlib\d+.*|ucrtbased|msvcr\d+.*)\.dll$")
API_SET = re.compile(r"(?i)^(api|ext)-ms-[a-z0-9-]+\.dll$")
MOST_IMPORTS = 4096


class PeError(Exception):
    pass


class Pe:
    """The parts of a PE file this check needs: its machine and the DLLs it imports."""

    def __init__(self, data: bytes):
        self.data = data
        if len(data) < 64 or data[:2] != b"MZ":
            raise PeError("no MZ header")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if pe + 24 > len(data) or data[pe:pe + 4] != b"PE\0\0":
            raise PeError("no PE header")
        self.machine, sections, _, _, _, optional_size, _ = struct.unpack_from("<HHIIIHH", data, pe + 4)
        optional = pe + 24
        if optional + optional_size > len(data) or optional_size < 2:
            raise PeError("the optional header is cut off")
        magic = struct.unpack_from("<H", data, optional)[0]
        if magic == 0x20B:                                   # PE32+
            dirs_at, count_at = optional + 112, optional + 108
        elif magic == 0x10B:                                 # PE32
            dirs_at, count_at = optional + 96, optional + 92
        else:
            raise PeError(f"unknown optional header 0x{magic:x}")
        count = min(struct.unpack_from("<I", data, count_at)[0], 16)
        self.directories = [struct.unpack_from("<II", data, dirs_at + 8 * i) for i in range(count)
                            if dirs_at + 8 * i + 8 <= optional + optional_size]
        table = optional + optional_size
        self.sections = []
        for i in range(sections):
            at = table + 40 * i
            if at + 40 > len(data):
                raise PeError("the section table is cut off")
            vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", data, at + 8)
            self.sections.append((va, max(vsize, raw_size), raw_ptr, raw_size))

    def offset(self, rva: int) -> int | None:
        for va, size, raw_ptr, raw_size in self.sections:
            if va <= rva < va + size and rva - va < raw_size:
                return raw_ptr + rva - va
        return None

    def string(self, rva: int) -> str:
        at = self.offset(rva)
        if at is None:
            raise PeError("a name lies outside the file")
        end = self.data.find(b"\0", at, at + 260)
        if end < 0:
            raise PeError("a name has no end")
        return self.data[at:end].decode("ascii", "replace")

    def _directory(self, index: int) -> tuple[int, int]:
        return self.directories[index] if index < len(self.directories) else (0, 0)

    def imports(self) -> list[str]:
        """The DLLs of the import table, then those of the delay-import table."""
        names = []
        rva, size = self._directory(1)
        if rva:
            at = self.offset(rva)
            if at is None:
                raise PeError("the import table lies outside the file")
            for i in range(MOST_IMPORTS):
                if at + 20 * i + 20 > len(self.data):
                    raise PeError("the import table is cut off")
                entry = struct.unpack_from("<IIIII", self.data, at + 20 * i)
                if not any(entry):
                    break
                names.append(self.string(entry[3]))
        rva, size = self._directory(13)
        if rva:
            at = self.offset(rva)
            if at is None:
                raise PeError("the delay-import table lies outside the file")
            for i in range(MOST_IMPORTS):
                if at + 32 * i + 32 > len(self.data):
                    raise PeError("the delay-import table is cut off")
                entry = struct.unpack_from("<IIIIIIII", self.data, at + 32 * i)
                if not any(entry):
                    break
                names.append(self.string(entry[1]))
        return names


def file_machine(data: bytes) -> int:
    """The processor a PE file is built for (its COFF header's machine), read without the rest."""
    if len(data) < 64 or data[:2] != b"MZ":
        raise PeError("no MZ header")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if pe + 6 > len(data) or data[pe:pe + 4] != b"PE\0\0":
        raise PeError("no PE header")
    return struct.unpack_from("<H", data, pe + 4)[0]


def machine_of(variant: str) -> int:
    parts = variant.split("-")
    if len(parts) != 3 or parts[0] != "win" or parts[1] not in VARIANT_MACHINE:
        raise PeError(f"{variant} is not a Windows variant this check knows")
    return VARIANT_MACHINE[parts[1]]


def system_names(system32: Path | None) -> set[str]:
    if system32 is None or not system32.is_dir():
        return set()
    # a library may have another ending: bthprops.cpl (Bluetooth), winspool.drv
    return {p.name.lower() for p in system32.iterdir() if p.suffix.lower() in (".dll", ".drv", ".exe", ".cpl", ".ocx")}


def check_folder(folder: Path, variant: str, system: set[str]) -> tuple[list[str], int]:
    """The problems of every program and library in `folder`, and how many files were read."""
    want = machine_of(variant)
    files = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in (".exe", ".dll"))
    packaged = {p.name.lower() for p in files}
    problems = []
    for path in files:
        rel = path.relative_to(folder).as_posix()
        try:
            pe = Pe(path.read_bytes())
            imports = pe.imports()
        except (PeError, struct.error) as exc:
            problems.append(f"{rel}: not a PE file this check can read ({exc})")
            continue
        if pe.machine != want:
            problems.append(f"{rel}: built for {MACHINES.get(pe.machine, hex(pe.machine))}, not "
                            f"{MACHINES[want]}")
        for name in imports:
            low = name.lower()
            if RUNTIME.match(low) and low not in packaged:
                problems.append(f"{rel}: imports {name}, Visual Studio's runtime, which a clean PC does not have")
            elif not (low in packaged or API_SET.match(low) or low in system or RUNTIME.match(low)):
                problems.append(f"{rel}: imports {name}, which is neither in the package nor part of Windows")
    return problems, len(files)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--folder", type=Path, required=True, help="the package's browser folder (Chrome-bin)")
    p.add_argument("--variant", required=True, help="win-x64-avx2, win-x64-sse4 or win-arm64-armv8")
    p.add_argument("--system32", type=Path,
                   default=Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
    a = p.parse_args(argv)
    try:
        problems, count = check_folder(a.folder, a.variant, system_names(a.system32))
    except PeError as exc:
        print(f"pe check: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(f"pe check: {problem}", file=sys.stderr)
    print(f"pe check: {count} programs and libraries, {'OK' if not problems else f'{len(problems)} problem(s)'}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
