#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The portable package's launcher and its update, checked end to end and offline (ROADMAP P3.12, P3.11, P4.4).

A portable folder in the layout of Thoron's own updater is made from a build (hard links, so it costs no space):

    ThoronPortable/
        Thoron.exe          the launcher (components/thoron_update/launcher)
        Application/current names the version that starts, and the one before it
        Application/<version>/ the build's browser folder
        User Data/          the profile, made by the launcher

The same build is put in twice, as an older and a newer version, so which one a start runs is told by the
folder `chrome://version` names. Then, from a folder with spaces and `& !`, from one with accented, Cyrillic and
Chinese letters, and as the root of a drive letter that `subst` makes:

    start     Thoron.exe starts the version `current` names, with the profile beside it; a setting is changed
    update    `thoron_update --apply` puts the newer version in place; the next start runs it, the setting kept
    rollback  `thoron_update --rollback`; the next start runs the older version again, the setting kept
    status    `thoron_update --status` names both

And once, in the first folder:

    processor on a processor without AVX2 the launcher of an AVX2 package says so and starts nothing (exit 3);
              the package of the SSE4 build starts there
    no-avx    the launcher's own code holds no AVX instruction (dumpbin), so it runs where the build does not;
              the C runtime's memcpy, memset and string routines have AVX paths that they take only after
              checking the processor, and are allowed

Nothing leaves the PC: the browser runs headless with every outside name unresolvable.
    py -3 -I tools/qa/portable_launcher_check.py --chrome-bin <Chrome-bin> --launcher <out>\\thoron_launcher.exe
        --cli <out>\\thoron_update.exe --work <scratch dir> [--dumpbin <dumpbin.exe>]
Exit status 0 only when every step passes.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import portable_check as pc  # noqa: E402
from tools.qa.adblock_site_switch_check import _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

OLDER, NEWER = "158.0.8127.3000", "158.0.8127.3010"
PLACES = {"spaces": "a folder with spaces & more!", "letters": "Ünïcødé Пример 例"}
START_ARGS = ["--headless=new", "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
              "--disable-component-update", f"--host-resolver-rules={pc.OFFLINE}", "--remote-debugging-port=0",
              "about:blank"]
AVX = re.compile(r"\b((?:ymm|zmm)\d+)\b|^\s*[0-9A-F]+:\s+(?:[0-9A-F]{2} )+\s*(v(?!err\b|erw\b)[a-z0-9]+)\b", re.M)


def files_list(folder: Path) -> list[dict]:
    """The version's files as the updater checks them: path with '/', size, SHA-256."""
    out = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        out.append({"path": path.relative_to(folder).as_posix(), "size": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return out


def link_tree(source: Path, target: Path) -> None:
    """`target` as a copy of `source` made of hard links (same drive)."""
    for path in source.rglob("*"):
        to = target / path.relative_to(source)
        if path.is_dir():
            to.mkdir(parents=True, exist_ok=True)
        else:
            to.parent.mkdir(parents=True, exist_ok=True)
            os.link(path, to)


# The C runtime's string and memory routines hold AVX paths that they take only after checking the processor at
# run time (the runtime reads its features at start); they run on every x64 processor.
RUNTIME_DISPATCHED = re.compile(r"^(memcpy|memmove|memset|memchr|memcmp|strlen|strnlen|wcslen|wcsnlen|strchr|"
                                r"wcschr)(_[A-Za-z0-9_]+)?$")
LABEL = re.compile(r"^([A-Za-z_?@$][^\s]*):\s*$")


def avx_by_function(disassembly: str) -> dict[str, list[str]]:
    """The AVX instructions of a disassembly (dumpbin /disasm), by the function they are in."""
    out: dict[str, set] = {}
    function = "?"
    for line in disassembly.splitlines():
        label = LABEL.match(line)
        if label:
            function = label.group(1)
            continue
        for m in AVX.finditer(line):
            out.setdefault(function, set()).add(m.group(1) or m.group(2))
    return {name: sorted(found) for name, found in out.items()}


def avx_found(disassembly: str) -> list[str]:
    """The AVX instructions outside the runtime's routines that check the processor first, as "function: name"."""
    return sorted(f"{name}: {', '.join(found)}" for name, found in avx_by_function(disassembly).items()
                  if not RUNTIME_DISPATCHED.match(name))


def started_problems(step: str, found: dict, package: Path, version: str) -> list[str]:
    program = (found.get("executable_path") or "").lower()
    profile = (found.get("profile_path") or "").lower()
    want = str(package / "Application" / version).lower()
    out = []
    if not program.startswith(want + "\\"):
        out.append(f"{step}: the browser started from {found.get('executable_path')!r}, not version {version}")
    if not profile.startswith(str(package / "User Data").lower()):
        out.append(f"{step}: the profile is {found.get('profile_path')!r}, not the package's User Data")
    return out


def status_problems(text: str, current: str, previous: str) -> list[str]:
    want = f"current: {current}\nprevious: {previous}\n"
    return [] if text.startswith(want) else [f"status: {text!r} does not start with {want!r}"]


def _start(package: Path, extra_env: dict | None = None) -> tuple[subprocess.CompletedProcess, Path]:
    env = dict(os.environ, **(extra_env or {}))
    # the port file of the start before names a port that is closed now
    (package / "User Data" / "DevToolsActivePort").unlink(missing_ok=True)
    done = subprocess.run([str(package / "Thoron.exe"), *START_ARGS], env=env, capture_output=True, timeout=60)
    return done, package / "User Data"


def _one_start(package: Path, change: int | None) -> dict:
    """Starts the package, reads chrome://version and the setting, changes it when asked, and closes it."""
    done, profile = _start(package)
    if done.returncode != 0:
        return {"exit": done.returncode}
    port = pc.devtools_port(profile)
    ws = WebSocket(_open(port, "chrome://version/")["webSocketDebuggerUrl"])
    try:
        found = pc.wait_for(ws, pc.VERSION_JS, lambda v: all(json.loads(v or "{}").get(k) for k in pc.NEEDED))
        found = json.loads(found or "{}")
        ws.call("Page.navigate", url="chrome://settings/")
        pc.wait_for(ws, pc.READY_JS, bool)
        found["setting"] = pc.evaluate(ws, pc.GET_JS)
        if change is not None:
            pc.evaluate(ws, pc.SET_JS % change)
            time.sleep(1.5)
    finally:
        ws.close()
    _close(port)
    # the browser was started by the launcher, not by this script: wait until no program of the package runs
    for _ in range(60):
        if not pc.own_processes(lambda path: str(path).lower().startswith(str(package).lower())):
            break
        time.sleep(0.5)
    found["exit"] = 0
    return found


def _close(port: int) -> None:
    """A normal exit through DevTools, so the profile is saved as when a person closes the browser."""
    version = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=10).read())
    ws = WebSocket(version["webSocketDebuggerUrl"])
    try:
        ws.call("Browser.close")
    except (ConnectionError, OSError):
        pass
    finally:
        ws.close()


def _cli(cli: Path, *args: str) -> tuple[int, str]:
    done = subprocess.run([str(cli), *args], capture_output=True, text=True, encoding="utf-8", timeout=600)
    return done.returncode, done.stdout


def check_place(package: Path, build: Path, launcher: Path, cli: Path, report) -> None:
    app = package / "Application"
    app.mkdir(parents=True)
    shutil.copy2(launcher, package / "Thoron.exe")
    link_tree(build, app / OLDER)
    (app / "current").write_text(OLDER + "\n", encoding="ascii")

    found = _one_start(package, change=21)
    report("start", started_problems("start", found, package, OLDER) or
           ([] if found.get("setting") == pc.DEFAULT else [f"start: the setting is {found.get('setting')}"]),
           found.get("executable_path"))

    staged = app / (NEWER + ".staging")
    link_tree(build, staged)
    listing = package.parent / f"{package.name}.files.json"
    listing.write_text(json.dumps(files_list(staged)), encoding="utf-8")
    code, text = _cli(cli, f"--root={app}", f"--apply={staged}", f"--version={NEWER}", f"--files={listing}")
    found = _one_start(package, change=None)
    problems = [] if code == 0 else [f"update: thoron_update --apply gave {code}: {text.strip()}"]
    problems += started_problems("update", found, package, NEWER)
    problems += [] if found.get("setting") == 21 else [f"update: the setting is {found.get('setting')}, not 21"]
    report("update", problems, found.get("executable_path"))

    code, text = _cli(cli, f"--root={app}", "--status")
    report("status", status_problems(text, NEWER, OLDER) if code == 0 else [f"status gave {code}"], text.strip())

    code, text = _cli(cli, f"--root={app}", "--rollback")
    found = _one_start(package, change=None)
    problems = [] if code == 0 else [f"rollback: thoron_update --rollback gave {code}: {text.strip()}"]
    problems += started_problems("rollback", found, package, OLDER)
    problems += [] if found.get("setting") == 21 else [f"rollback: the setting is {found.get('setting')}, not 21"]
    report("rollback", problems, found.get("executable_path"))


def check_processor(package: Path, report) -> None:
    message = package.parent / "launcher-message.txt"
    env = {"THORON_LAUNCHER_ASSUME_CPU": "sse4", "THORON_LAUNCHER_MESSAGE_FILE": str(message)}
    done, _ = _start(package, env)
    said = message.read_text(encoding="utf-16-le") if message.exists() else ""
    problems = []
    if done.returncode != 3 or "AVX2" not in said:
        problems.append(f"processor: an AVX2 package on a processor without AVX2 gave {done.returncode}, {said!r}")
    (package / "variant").write_text("win-x64-sse4\n", encoding="ascii")
    message.unlink(missing_ok=True)
    found = _one_start(package, change=None) if not problems else {}
    if not problems and found.get("exit") != 0:
        problems.append(f"processor: the SSE4 package did not start on that processor ({found.get('exit')})")
    (package / "variant").unlink(missing_ok=True)
    report("processor", problems, f"exit {done.returncode}")


def run(chrome_bin: Path, launcher: Path, cli: Path, work: Path, dumpbin: Path | None) -> list[str]:
    problems: list[str] = []

    def report(step: str, found: list[str], detail) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {step}: {str(detail)[:150]}")
        problems.extend(found)

    if dumpbin:
        text = subprocess.run([str(dumpbin), "/disasm", str(launcher)], capture_output=True, text=True,
                              errors="replace").stdout
        found = avx_found(text)
        report("no-avx", [f"no-avx: the launcher holds {found}"] if found else [], f"{len(text)} characters read")
    base = work / "launcher-check"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    letter = None
    try:
        for key, name in PLACES.items():
            print(f"== {key}")
            check_place(base / name / "ThoronPortable", chrome_bin, launcher, cli, report)
        check_processor(base / PLACES["spaces"] / "ThoronPortable", report)
        letter = pc.free_letter()
        if letter:
            drive_folder = base / "drive"
            drive_folder.mkdir()
            subprocess.run(["subst", f"{letter}:", str(drive_folder)], check=True, capture_output=True)
            print(f"== drive root ({letter}:)")
            check_place(Path(f"{letter}:\\"), chrome_bin, launcher, cli, report)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as e:
        problems.append(f"the run failed: {e}")
    finally:
        if letter:
            subprocess.run(["subst", f"{letter}:", "/d"], capture_output=True)
        pc.stop_own(lambda path: str(path).lower().startswith(str(base).lower()), base)
        shutil.rmtree(base, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--chrome-bin", required=True, type=Path)
    p.add_argument("--launcher", required=True, type=Path)
    p.add_argument("--cli", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path)
    p.add_argument("--dumpbin", type=Path)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if os.name != "nt":
        print("PORTABLE LAUNCHER CHECK: Windows only")
        return 1
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.chrome_bin.resolve(), a.launcher.resolve(), a.cli.resolve(), a.work.resolve(), a.dumpbin)
    for problem in problems:
        print(problem)
    print("PORTABLE LAUNCHER CHECK: PASSED" if not problems
          else f"PORTABLE LAUNCHER CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
