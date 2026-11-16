#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Which portable package the launcher starts on which processor (ROADMAP P4.4, P5.11), with the real program.

A small package is made around the launcher, with a stand-in for the browser (any program that ends by itself,
such as thoron_update.exe), and the file `variant` set to each case. The processor is assumed through the
launcher's test seam THORON_LAUNCHER_ASSUME_CPU (`avx2`: no AVX-512, `sse4`: no AVX2, `old`: no SSE4.2), or is
the real one; its message is read from a file instead of a window:

    no file, win-x64-avx2, win-x64-avx512 (on a processor with AVX-512) and win-x64-sse4   start (exit 0)
    win-x64-avx512 without AVX-512, win-x64-avx2 without AVX2, anything without SSE4.2       exit 3, said why
    any other text (a typo, an unknown name, a byte-order mark)                              exit 3, refused

The AVX-512 cases on the real processor run only where it has AVX-512. With --dumpbin the launcher's own code
is also checked for AVX instructions (portable_launcher_check.avx_found).
    py -3 -I tools/qa/launcher_variants_check.py --launcher <out>\\thoron_launcher.exe
        --stand-in <out>\\thoron_update.exe --work <scratch dir> [--dumpbin <dumpbin.exe>]
"""
import argparse
import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import portable_launcher_check as pl  # noqa: E402

VERSION = "158.0.8127.3010"
# variant file text (None: no file), assumed processor ("": the real one), exit wanted, words of the message
CASES = (
    (None, "", 0, None),
    ("win-x64-avx2\r\n", "", 0, None),
    ("win-x64-avx512\n", "", 0, None),
    ("win-x64-avx512\n", "avx2", 3, "AVX-512"),
    ("win-x64-avx512\n", "sse4", 3, "AVX-512"),
    ("win-x64-avx2\n", "avx2", 0, None),
    ("win-x64-avx2\n", "sse4", 3, "made for processors with AVX2"),
    ("win-x64-sse4\n", "sse4", 0, None),
    ("win-x64-sse4\n", "old", 3, "too old"),
    ("win-x64-avx2x\n", "", 3, "does not know"),
    ("win-x64-avx3\n", "", 3, "does not know"),
    ("﻿win-x64-avx2\n", "", 3, "does not know"),
)


def real_avx512() -> bool:
    return os.name == "nt" and bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(41))


def judge(code: int, said: str, want: int, words: str | None) -> bool:
    return code == want and (not said if words is None else words in said)


def run(launcher: Path, stand_in: Path, work: Path, dumpbin: Path | None) -> list[str]:
    if work.exists():
        shutil.rmtree(work)
    package = work / "ThoronPortable"
    (package / "Application" / VERSION).mkdir(parents=True)
    shutil.copy2(launcher, package / "Thoron.exe")
    shutil.copy2(stand_in, package / "Application" / VERSION / "thoron.exe")
    (package / "Application" / "current").write_text(VERSION + "\n", encoding="ascii")
    message = work / "message.txt"
    problems = []
    for text, cpu, want, words in CASES:
        if not cpu and text and "avx512" in text and not real_avx512():
            print(f"SKIP  {text!r} on the real processor: it has no AVX-512")
            continue
        (package / "variant").unlink(missing_ok=True)
        if text is not None:
            (package / "variant").write_bytes(text.encode("utf-8"))
        message.unlink(missing_ok=True)
        env = {k: v for k, v in os.environ.items() if k != "THORON_LAUNCHER_ASSUME_CPU"}
        env["THORON_LAUNCHER_MESSAGE_FILE"] = str(message)
        if cpu:
            env["THORON_LAUNCHER_ASSUME_CPU"] = cpu
        done = subprocess.run([str(package / "Thoron.exe")], env=env, timeout=60)
        said = message.read_text(encoding="utf-16-le") if message.exists() else ""
        ok = judge(done.returncode, said, want, words)
        print(f"{'PASS' if ok else 'FAIL'}  {text!r} on {cpu or 'the real processor'}: exit {done.returncode} "
              f"{said[:60]}")
        if not ok:
            problems.append(f"{text!r} on {cpu or 'the real processor'}: exit {done.returncode}, not {want}")
    if dumpbin:
        done = subprocess.run([str(dumpbin), "/nologo", "/disasm", str(launcher)], capture_output=True, text=True,
                              errors="replace")
        found = pl.avx_found(done.stdout)
        print(f"{'FAIL' if found else 'PASS'}  no-avx: {found or 'none in the launcher own code'}")
        problems += [f"no-avx: {f}" for f in found]
    shutil.rmtree(work, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--launcher", type=Path, required=True)
    p.add_argument("--stand-in", type=Path, required=True, help="a program that ends by itself, for the browser")
    p.add_argument("--work", type=Path, required=True, help="a scratch folder; `launcher-variants` is made in it")
    p.add_argument("--dumpbin", type=Path)
    a = p.parse_args(argv)
    if os.name != "nt":
        print("launcher variants: Windows only", file=sys.stderr)
        return 2
    problems = run(a.launcher, a.stand_in, a.work / "launcher-variants", a.dumpbin)
    print(f"LAUNCHER VARIANTS CHECK: {'PASSED' if not problems else f'FAILED ({len(problems)} problem(s))'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
