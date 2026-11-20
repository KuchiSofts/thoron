#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Every program and library of a Linux package is built for the processor of its variant (ROADMAP P2b.2, P2.7).

Reads a .deb (an `ar` archive with its files in data.tar.*) or a folder, finds every ELF file by its first bytes
and reads its header with its own reader (nothing is run): it must be 64-bit, little-endian, for the variant's
processor (x86-64 for linux-x64, AArch64 for linux-arm64), and a program that names a loader must name that
processor's (/lib64/ld-linux-x86-64.so.2, /lib/ld-linux-aarch64.so.1). A package with no ELF file at all, or
without the browser's program, fails as well.

    py -3 -I tools/release/elf_check.py --deb out/<dir>/thoron-browser_<version>_arm64.deb --variant linux-arm64
    py -3 -I tools/release/elf_check.py --dir <unpacked package> --variant linux-x64
Exit status 0 only when every ELF file matches.
"""
from __future__ import annotations

import argparse
import io
import lzma
import struct
import sys
import tarfile
from pathlib import Path

VARIANTS = {
    # variant: (e_machine, its name, the loader a program of it names)
    "linux-x64": (62, "x86-64", "/lib64/ld-linux-x86-64.so.2"),
    "linux-arm64": (183, "AArch64", "/lib/ld-linux-aarch64.so.1"),
}
MACHINES = {3: "i386", 40: "ARM (32-bit)", 62: "x86-64", 183: "AArch64", 243: "RISC-V"}
PROGRAM = "opt/kuchisofts/thoron/thoron"
PT_INTERP = 3


class ElfError(ValueError):
    pass


def read_elf(data: bytes) -> dict:
    """The header of an ELF file: its class, byte order, machine and the loader it names (or None)."""
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise ElfError("not an ELF file")
    bits = {1: 32, 2: 64}.get(data[4])
    order = {1: "<", 2: ">"}.get(data[5])
    if not bits or not order:
        raise ElfError("an ELF class or byte order that does not exist")
    info = {"bits": bits, "little": order == "<", "interpreter": None}
    if bits == 32:
        e_type, machine = struct.unpack_from(order + "HH", data, 16)
        info.update(type=e_type, machine=machine)
        return info                              # 32-bit files fail on their class; no need to read further
    e_type, machine = struct.unpack_from(order + "HH", data, 16)
    phoff, = struct.unpack_from(order + "Q", data, 32)
    phentsize, phnum = struct.unpack_from(order + "HH", data, 54)
    info.update(type=e_type, machine=machine)
    if phnum > 4096 or phentsize < 56 or phoff + phnum * phentsize > len(data):
        if phnum:
            raise ElfError("program headers outside the file")
        return info
    for i in range(phnum):
        at = phoff + i * phentsize
        p_type, = struct.unpack_from(order + "I", data, at)
        if p_type == PT_INTERP:
            offset, = struct.unpack_from(order + "Q", data, at + 8)
            size, = struct.unpack_from(order + "Q", data, at + 32)
            if offset + size > len(data) or size > 4096:
                raise ElfError("the loader's name is outside the file")
            info["interpreter"] = data[offset:offset + size].split(b"\0", 1)[0].decode("ascii", "replace")
    return info


def problems_of(name: str, data: bytes, variant: str) -> list[str]:
    machine, machine_name, loader = VARIANTS[variant]
    try:
        info = read_elf(data)
    except ElfError as exc:
        return [f"{name}: {exc}"]
    out = []
    if info["bits"] != 64 or not info["little"]:
        out.append(f"{name}: {info['bits']}-bit {'little' if info['little'] else 'big'}-endian, not 64-bit little-endian")
    if info["machine"] != machine:
        out.append(f"{name}: built for {MACHINES.get(info['machine'], info['machine'])}, not {machine_name}")
    if info["interpreter"] and info["interpreter"] != loader:
        out.append(f"{name}: names the loader {info['interpreter']}, not {loader}")
    return out


def _ar_members(data: bytes):
    """(name, bytes) of every member of an `ar` archive (a .deb)."""
    if not data.startswith(b"!<arch>\n"):
        raise ElfError("not a .deb (no ar archive)")
    at = 8
    while at + 60 <= len(data):
        header = data[at:at + 60]
        name = header[:16].decode("ascii", "replace").strip().rstrip("/")
        size = int(header[48:58].decode("ascii").strip() or 0)
        yield name, data[at + 60:at + 60 + size]
        at += 60 + size + (size % 2)


def deb_files(deb: Path):
    """(path, bytes) of every regular file in a .deb's data.tar.*."""
    for name, member in _ar_members(deb.read_bytes()):
        if name.startswith("data.tar"):
            raw = lzma.decompress(member) if name.endswith(".xz") else member
            mode = "r:gz" if name.endswith(".gz") else "r:"
            if name.endswith(".zst"):
                raise ElfError("data.tar.zst: unpack the package with dpkg-deb and use --dir")
            with tarfile.open(fileobj=io.BytesIO(raw), mode=mode) as tar:
                for item in tar:
                    if item.isfile():
                        yield item.name.lstrip("./"), tar.extractfile(item).read()
            return
    raise ElfError("the .deb has no data.tar")


def dir_files(folder: Path):
    for path in sorted(folder.rglob("*")):
        if path.is_file() and not path.is_symlink():
            yield path.relative_to(folder).as_posix(), path.read_bytes()


def check(files, variant: str) -> tuple[list[str], int]:
    problems, elves, program = [], 0, False
    for name, data in files:
        if data[:4] != b"\x7fELF":
            continue
        elves += 1
        program |= name.endswith(PROGRAM) or name == PROGRAM
        problems += problems_of(name, data, variant)
    if not elves:
        problems.append("no ELF file in the package")
    elif not program:
        problems.append(f"the program {PROGRAM} is not in the package")
    return problems, elves


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--deb", type=Path)
    src.add_argument("--dir", type=Path)
    p.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    a = p.parse_args(argv)
    try:
        problems, elves = check(deb_files(a.deb) if a.deb else dir_files(a.dir), a.variant)
    except (ElfError, OSError, tarfile.TarError, lzma.LZMAError) as exc:
        print(f"ELF CHECK: could not read the package: {exc}")
        return 1
    for problem in problems:
        print(f"  {problem}")
    print(f"ELF CHECK ({a.variant}): {elves} ELF file(s); "
          f"{'PASSED' if not problems else f'FAILED ({len(problems)} problem(s))'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
