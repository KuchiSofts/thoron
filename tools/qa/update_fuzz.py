#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Coverage-guided fuzzing of the updater's readers (ROADMAP S.2, U9): seeds and a timed run.

Two libFuzzer targets of components/thoron_update, built with a fuzzing engine (use_libfuzzer = true; on
Windows also is_asan = true, a release and static build, where the build's own protoc stops on
AddressSanitizer reports of its own before the targets are built, so they are run on the Linux build):

    thoron_update_manifest_fuzzer     the signed manifest past its signature: the first byte of an input
                                      picks the copy, the rest is the manifest; the target signs it with the
                                      published test key and runs the whole check
    thoron_update_delta_list_fuzzer   a delta's file list (delta.json), from 158.0.8127.3010 to .6500

`seeds` writes valid inputs for both, made with the reference tools (tools/update/manifest.py, the
format of tools/release/delta.py), so the run starts from inputs that get all the way through.
`run` runs a target for a time with its corpus and dictionary, keeps what it finds in the corpus, and
reports the number of inputs, the coverage it reached and every crash (libFuzzer writes the input that
crashed as crash-<hash> in the artifact folder).

    py -3 -I tools/qa/update_fuzz.py seeds --out <corpus root>
    py -3 -I tools/qa/update_fuzz.py run --fuzzer <out>\\thoron_update_manifest_fuzzer.exe
        --corpus <corpus root>\\manifest --dict <src>\\components\\thoron_update\\manifest_fuzzer.dict
        --seconds 3600 --artifacts <folder> [--md <report.md>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.update import manifest as mf  # noqa: E402

URL = "https://github.com/KuchiSofts/thoron/releases/download/v0.1.2/"
FROM, TO = "158.0.8127.3010", "158.0.8127.6500"
PUBLISHED = 1795000000 - 3600          # an hour before the clock of the manifest fuzzer


def _entry(name: str, size: int) -> dict:
    return {"url": URL + name, "size": size, "sha256": hashlib.sha256(name.encode("ascii")).hexdigest()}


def manifests() -> list[bytes]:
    """Valid manifests of several shapes: full packages, deltas, both kinds, several builds, critical."""
    out = [mf.example()]
    shapes = [
        {"win-x64-avx2": {"installed": {"full": _entry("i.exe", 104857600)}}},
        {"win-x64-avx2": {"installed": {"full": _entry("i.exe", 104857600),
                                        "deltas": {FROM: _entry("d.delta", 9437184)}},
                          "portable": {"full": _entry("p.zip", 157286400),
                                       "deltas": {FROM: _entry("pd.delta", 8388608)}}}},
        {"win-x64-sse4": {"portable": {"full": _entry("s.zip", 150000000)}},
         "win-arm64-armv8": {"installed": {"full": _entry("a.exe", 99000000)}},
         "linux-x64-avx2": {"portable": {"full": _entry("l.tar.xz", 120000000)}}},
    ]
    for i, packages in enumerate(shapes):
        for channel in ("stable", "beta"):
            out.append(mf.build(channel=channel, version=TO, thoron_version="0.1.2", critical=bool(i % 2),
                                min_updater_version="158.0.8127.3000", packages=packages, published=PUBLISHED,
                                allowed_hosts=("github.com",)))
    return out


def delta_lists() -> list[bytes]:
    sha = "0123456789abcdef" * 4
    files = [{"path": "thoron.dll", "size": 200000000, "sha256": sha, "how": "patch",
              "from_path": "thoron.dll", "from_sha256": sha},
             {"path": "Locales/de.pak", "size": 400000, "sha256": sha, "how": "same",
              "from_path": "Locales/de.pak", "from_sha256": sha},
             {"path": "Installer/setup.exe", "size": 3000000, "sha256": sha, "how": "whole"}]
    return [json.dumps({"format": 1, "from": FROM, "to": TO, "files": files[:n]}, indent=1).encode("utf-8")
            for n in (1, 2, 3)]


def write_seeds(out: Path) -> dict[str, int]:
    (out / "manifest").mkdir(parents=True, exist_ok=True)
    (out / "delta_list").mkdir(parents=True, exist_ok=True)
    count = {"manifest": 0, "delta_list": 0}
    for data in manifests():
        for pick in (0x00, 0x01, 0x03, 0x05, 0x11, 0x21, 0x41):   # copies of several kinds, builds and channels
            seed = bytes([pick]) + data
            (out / "manifest" / f"seed-{hashlib.sha1(seed).hexdigest()}").write_bytes(seed)
            count["manifest"] += 1
    for data in delta_lists():
        (out / "delta_list" / f"seed-{hashlib.sha1(data).hexdigest()}").write_bytes(data)
        count["delta_list"] += 1
    return count


_DONE = re.compile(r"Done (\d+) runs in (\d+) second")
_COV = re.compile(r"\bcov: (\d+) ft: (\d+)")


def summary(log: str, artifacts: Path) -> dict:
    """What a libFuzzer run says of itself: inputs run, coverage reached, crashes written."""
    done = _DONE.findall(log)
    cov = _COV.findall(log)
    crashes = sorted(p.name for p in artifacts.glob("crash-*")) + sorted(p.name for p in artifacts.glob("leak-*")) \
        + sorted(p.name for p in artifacts.glob("timeout-*")) + sorted(p.name for p in artifacts.glob("oom-*"))
    return {"runs": int(done[-1][0]) if done else None, "seconds": int(done[-1][1]) if done else None,
            "coverage": int(cov[-1][0]) if cov else None, "features": int(cov[-1][1]) if cov else None,
            "findings": crashes, "error": "ERROR: AddressSanitizer" in log or "==ERROR" in log}


def report(name: str, found: dict) -> str:
    verdict = ("NOT RUN" if not found["runs"] else
               "CLEAN" if not found["findings"] and not found["error"] else "FOUND")
    lines = [f"{name}: {verdict}", f"- inputs run: {found['runs']} in {found['seconds']} s",
             f"- coverage: {found['coverage']} edges, {found['features']} features"]
    lines += [f"- finding: {f}" for f in found["findings"]]
    return "\n".join(lines) + "\n"


def run(fuzzer: Path, corpus: Path, dictionary: Path | None, seconds: int, artifacts: Path) -> tuple[dict, str]:
    artifacts.mkdir(parents=True, exist_ok=True)
    command = [str(fuzzer), str(corpus), f"-max_total_time={seconds}", f"-artifact_prefix={artifacts}\\",
               "-print_final_stats=1", "-timeout=10", "-rss_limit_mb=2048", "-max_len=65536"]
    if dictionary:
        command.append(f"-dict={dictionary}")
    started = time.monotonic()
    done = subprocess.run(command, capture_output=True, text=True, errors="replace",
                          timeout=seconds + 600)
    log = done.stdout + done.stderr
    found = summary(log, artifacts)
    found["exit"] = done.returncode
    found["wall_seconds"] = round(time.monotonic() - started)
    return found, log


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("seeds")
    s.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--fuzzer", type=Path, required=True)
    r.add_argument("--corpus", type=Path, required=True)
    r.add_argument("--dict", type=Path)
    r.add_argument("--seconds", type=int, default=3600)
    r.add_argument("--artifacts", type=Path, required=True)
    r.add_argument("--log", type=Path)
    r.add_argument("--md", type=Path)
    a = p.parse_args(argv)
    if a.command == "seeds":
        print(json.dumps(write_seeds(a.out)))
        return 0
    found, log = run(a.fuzzer, a.corpus, a.dict, a.seconds, a.artifacts)
    if a.log:
        a.log.write_text(log, encoding="utf-8")
    text = report(a.fuzzer.stem, found)
    print(text)
    if a.md:
        a.md.write_text(text, encoding="utf-8", newline="\n")
    return 0 if text.split(": ", 1)[1].startswith("CLEAN") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
