#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""A delta package applied by the updater itself, with real builds (ROADMAP P4.1).

A program folder is made with the older build as its current version (hard links: nothing is copied, and the
older files are only read). Then the older version's own updater runs

    thoron_update --root <folder> --apply-delta <file.delta> --version <newer>

The version folder it makes must be, file for file and byte for byte, the newer build; `current` must name the
newer version and the older one before it, and the older folder must be untouched. A delta for other versions, a
damaged delta and an older file that was changed are refused and switch nothing.
    py -3 -I tools/qa/delta_apply_check.py --old <older version folder> --new <newer version folder>
        --delta <file.delta> --updater <thoron_update.exe> --work <scratch dir>
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def tree_hashes(folder: Path) -> dict[str, str]:
    out = {}
    for f in sorted(folder.rglob("*")):
        if f.is_file():
            h = hashlib.sha256()
            with f.open("rb") as r:
                for block in iter(lambda: r.read(1 << 20), b""):
                    h.update(block)
            out[f.relative_to(folder).as_posix()] = h.hexdigest()
    return out


def link_tree(source: Path, target: Path) -> None:
    for base, _, names in os.walk(source):
        out = target / Path(base).relative_to(source)
        out.mkdir(parents=True, exist_ok=True)
        for name in names:
            os.link(Path(base) / name, out / name)


def run_tool(updater: Path, *args: str) -> tuple[int, str]:
    done = subprocess.run([str(updater), *args], capture_output=True, text=True, timeout=1800)
    return done.returncode, done.stdout


def damaged(delta: Path, out: Path, change) -> Path:
    with zipfile.ZipFile(delta) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info, change(info.filename, src.read(info)))
    return out


def run(old: Path, new: Path, delta: Path, updater: Path, work: Path) -> list[str]:
    if work.exists():
        shutil.rmtree(work)
    with zipfile.ZipFile(delta) as z:
        listing = json.loads(z.read("delta.json"))
    older, newer = listing["from"], listing["to"]
    app = work / "Application"
    link_tree(old, app / older)
    tool = work / "thoron_update.exe"
    shutil.copy2(updater, tool)
    (app / "current").write_text(older + "\n", encoding="ascii")
    old_before = tree_hashes(app / older)
    problems = []

    def report(step: str, found: list[str], detail: str) -> None:
        problems.extend(found)
        print(f"{'PASS' if not found else 'FAIL'}  {step}: {detail}")
        for f in found:
            print(f"      {f}")

    # Refused first, so that the folder is still at the older version.
    code, text = run_tool(tool, f"--root={app}", f"--apply-delta={delta}", "--version=158.0.8127.3999")
    found = [] if code == 13 and "wrong_version" in text else [f"another version gave {code} {text.strip()!r}"]
    bad = damaged(delta, work / "damaged.delta",
                  lambda name, data: data[:-200] + bytes(200) if name.startswith("patch/") else data)
    code2, text2 = run_tool(tool, f"--root={app}", f"--apply-delta={bad}", f"--version={newer}")
    if code2 != 12:
        found.append(f"a damaged delta gave {code2} {text2.strip()!r}")
    code3, text3 = run_tool(tool, f"--root={app}", "--status")
    if f"current: {older}\n" not in text3 or any(p.name.endswith(".staging") for p in app.iterdir()):
        found.append("refused: something was switched or left")
    report("refused", found, f"{text.strip()} / {text2.strip()}")

    code, text = run_tool(tool, f"--root={app}", f"--apply-delta={delta}", f"--version={newer}")
    found = [] if code == 0 and "done" in text else [f"--apply-delta gave {code}: {text.strip()[:200]}"]
    report("apply", found, text.strip().replace("\n", " | "))

    want, made = tree_hashes(new), tree_hashes(app / newer) if (app / newer).is_dir() else {}
    found = [f"{name}: not the newer build's file" for name in sorted(want) if made.get(name) != want[name]]
    found += [f"{name}: not in the newer build" for name in sorted(set(made) - set(want))]
    report("byte for byte", found[:10], f"{len(made)} files made, {len(want)} in the newer build")

    code, text = run_tool(tool, f"--root={app}", "--status")
    found = [] if f"current: {newer}\nprevious: {older}\n" in text else [f"status: {text.strip()!r}"]
    if tree_hashes(app / older) != old_before:
        found.append("the older version's folder changed")
    report("status", found, text.strip().replace("\n", " | "))
    shutil.rmtree(work, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--old", type=Path, required=True)
    p.add_argument("--new", type=Path, required=True)
    p.add_argument("--delta", type=Path, required=True)
    p.add_argument("--updater", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True, help="a scratch folder; `delta-apply` is made in it")
    a = p.parse_args(argv)
    problems = run(a.old, a.new, a.delta, a.updater, a.work / "delta-apply")
    print(f"DELTA APPLY CHECK: {'PASSED' if not problems else f'FAILED ({len(problems)} problem(s))'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
