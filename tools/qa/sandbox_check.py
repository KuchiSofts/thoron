#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Sandbox verification for a release (ROADMAP S.5): is the sandbox of the running browser really on? Windows.

The browser is started headless on a throwaway profile in --work, offline but for 127.0.0.1, with a local web
page, chrome://gpu and chrome://sandbox open. Three witnesses are then heard, and they must agree:

    switch   no process of the browser's tree carries --no-sandbox on its command line
    system   what Windows itself says about each child process, read with the Windows API and not from the
             browser: every renderer runs below Medium integrity (the build smoke test's proof,
             tools/build/smoke.py) on a restricted token, with fewer privileges than the browser, inside a
             job object and with win32k system calls shut off; the GPU process and every utility process that
             declares a sandbox run below Medium integrity on a restricted token (or in an AppContainer)
    pages    what the browser says: chrome://sandbox lists the renderers and the GPU process as sandboxed, the
             integrity level it shows for a process is the one Windows reports, and chrome://gpu says
             "Sandboxed: true"

A utility process that the browser starts without a sandbox on purpose (--service-sandbox-type=none, today the
network service) is not a failure; it is named in the output, so that a release sees the list.

Negative control: the same browser is then started with --no-sandbox, and each of the three witnesses must
report it: the system for every renderer, the pages for at least one. A witness that stays silent there could
not have caught a real failure, so the check fails.

The evidence file holds what chrome://sandbox showed and what Windows reported, for the release checklist.

    py -3 -I tools/qa/sandbox_check.py --browser <out>\\thoron.exe --work <scratch dir> [--evidence <file>]
        [--switch=--disable-gpu-sandbox]
Exit status 0 only when the sandbox is on and the negative control is caught; 2 on a system that is not
checked yet. --switch starts the checked browser with one more switch, to watch the check fail on a browser
weakened in one place.

Linux is not checked yet (there is no Linux package to check). Its half is a second entry in SYSTEMS, in this
same shape (facts from the system, the browser's pages, the negative control). It needs: from /proc/<pid>/status
of every renderer "Seccomp: 2" and "NoNewPrivs: 1"; its user, PID and network namespaces differing from the
browser's (tools/build/smoke.py already reads the first and the PID namespace); the AppArmor label of the
processes of the installed package (/proc/<pid>/attr/current) and the profile the package installs, because
where unprivileged user namespaces are restricted the sandbox depends on that profile or on a setuid helper; and
the status list of chrome://sandbox on Linux, which differs from the table read here.
"""
import argparse
import functools
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.build import smoke  # noqa: E402
from tools.qa import bench, soak  # noqa: E402
from tools.qa.adblock_site_switch_check import _devtools_port, _open  # noqa: E402
from tools.qa.cdp import TEXT_JS, WebSocket  # noqa: E402

NOT_SANDBOXED = "Not Sandboxed"
# GetProcessMitigationPolicy: policy number -> {bit: what it means when set}
MITIGATIONS = {2: {0: "no dynamic code"}, 3: {0: "strict handle checks"}, 4: {0: "win32k lockdown"},
               6: {0: "no extension points"}, 8: {0: "Microsoft-signed images only"}, 9: {0: "system fonts only"},
               10: {0: "no remote images", 1: "no low-integrity images"}, 13: {0: "no child processes"}}
RENDERER_MUST_HAVE = ("win32k lockdown",)
WITNESSES = ("switch", "system", "pages")
ROWS_JS = ("JSON.stringify([...document.querySelectorAll('#sandbox-status tr')].map((tr) => "
           "[...tr.cells].map((td) => (td.querySelector('.mitigations') || td).textContent.trim())))")
RAW_JS = "(document.getElementById('raw-info') || {textContent: ''}).textContent"


# --- the decision: pure functions -------------------------------------------------------------------------------

def level(rid: int | None) -> str:
    return "unknown" if rid is None else smoke._LEVELS.get(rid, hex(rid))


def declared(cmd: str) -> str:
    """The sandbox a utility process says it was started with ("" when its command line does not say)."""
    m = re.search(r"--service-sandbox-type=([\w-]+)", cmd)
    return m.group(1) if m else ""


def by_design(proc: dict) -> bool:
    """A utility process the browser starts without a sandbox on purpose."""
    return proc["type"] == "utility" and declared(proc["cmd"]).startswith("none")


def who(proc: dict) -> str:
    service = re.search(r"--utility-sub-type=([\w.]+)", proc["cmd"])
    return f"{proc['type']} {proc['pid']}" + (f" ({service.group(1)})" if service else "")


def privileges(count: int) -> str:
    return f"{count} privilege" + ("" if count == 1 else "s")


def mitigation_names(flags: dict[int, int]) -> list[str]:
    """The mitigations that are on, from the flag words Windows returned for each policy."""
    return [name for policy, bits in MITIGATIONS.items() for bit, name in bits.items()
            if flags.get(policy, 0) >> bit & 1]


def switch_problems(procs: list[dict]) -> list[str]:
    return [f"{who(p)} runs with --no-sandbox" for p in procs if re.search(r"--no-sandbox(?![\w-])", p["cmd"])]


def windows_problems(procs: list[dict]) -> list[str]:
    """What Windows reports against the sandbox. Each process: pid, type, cmd, and facts (None when its token
    could not be read): integrity, restricted, appcontainer, privileges, in_job, mitigations."""
    out = []
    if not any(p["type"] == "renderer" for p in procs):
        out.append("no renderer process found, so the sandbox could not be checked")
    browser = next((p["facts"] for p in procs if p["type"] == "browser" and p["facts"]), None)
    for p in procs:
        if p["type"] not in ("renderer", "gpu", "utility") or by_design(p):
            continue
        facts = p["facts"]
        if facts is None:
            out.append(f"{who(p)}: its security token could not be read")
            continue
        if facts["integrity"] is None or facts["integrity"] >= smoke.MEDIUM_INTEGRITY:
            out.append(f"{who(p)} runs at {level(facts['integrity'])} integrity (not sandboxed)")
        if not (facts["restricted"] or facts["appcontainer"]):
            out.append(f"{who(p)}: its token is not restricted")
        if p["type"] != "renderer":
            continue
        if browser and facts["privileges"] >= browser["privileges"]:
            out.append(f"{who(p)} holds {privileges(facts['privileges'])}, no fewer than the browser itself")
        if not facts["in_job"]:
            out.append(f"{who(p)} is in no job object")
        out += [f"{who(p)}: {must} is off" for must in RENDERER_MUST_HAVE if must not in facts["mitigations"]]
    return out


def parse_rows(table: list[list[str]]) -> list[dict]:
    """The table of chrome://sandbox (first row: the column names) as pid, type, sandbox, integrity and rid."""
    if not table:
        return []
    names = {name: i for i, name in enumerate(table[0])}
    out = []
    for cells in table[1:]:
        def cell(name: str) -> str:
            return cells[names[name]] if name in names and names[name] < len(cells) else ""
        if not cell("Process").isdigit():
            continue
        rid = re.search(r"S-1-16-(\d+)", cell("Integrity"))
        out.append({"pid": int(cell("Process")), "type": cell("Type"), "name": cell("Name"),
                    "sandbox": cell("Sandbox"), "lockdown": cell("Lockdown"), "integrity": cell("Integrity"),
                    "rid": int(rid.group(1)) if rid else None})
    return out


def parse_features(raw: str) -> list[str]:
    """The sandbox features of chrome://sandbox's raw information, as "name: on" or "name: off"."""
    m = re.search(r"features:\s*(\[.*?\])\s*(?:policies:|$)", raw, re.S)
    try:
        return [f"{f['name']}: {'on' if f['enabled'] else 'off'}" for f in json.loads(m.group(1))] if m else []
    except (ValueError, KeyError, TypeError):
        return []


def gpu_sandboxed(text: str) -> bool | None:
    """What chrome://gpu says of the GPU process's sandbox (None: it does not say)."""
    m = re.search(r"\bSandboxed\s*:?\s*(true|false)\b", text)
    return None if not m else m.group(1) == "true"


def page_problems(procs: list[dict], rows: list[dict], gpu: bool | None) -> list[str]:
    """What the browser's own pages report against the sandbox, and where they differ from Windows."""
    out = []
    listed = {r["pid"]: r for r in rows}
    if not listed:
        out.append("chrome://sandbox lists no process")
    renderers = 0
    for p in procs:
        row = listed.get(p["pid"])
        if row is None or p["type"] not in ("renderer", "gpu", "utility"):
            continue
        renderers += p["type"] == "renderer"
        if row["sandbox"] == NOT_SANDBOXED:
            if not by_design(p):
                out.append(f"chrome://sandbox: {who(p)} is not sandboxed")
            continue
        seen = (p["facts"] or {}).get("integrity")
        if row["rid"] is not None and seen is not None and row["rid"] != seen:
            out.append(f"{who(p)}: chrome://sandbox says {row['integrity']}, Windows says {level(seen)} integrity")
    if listed and not renderers:
        out.append("no renderer is both in chrome://sandbox and in the process tree: nothing was compared")
    if gpu is not True:
        out.append("chrome://gpu " + ("says the GPU process is not sandboxed" if gpu is False else
                                      "does not say whether the GPU process is sandboxed"))
    return out


def judge(seen: dict, system_problems=windows_problems) -> dict:
    """The problems each witness reports for one observed browser (all empty: the sandbox is on)."""
    return {"switch": switch_problems(seen["procs"]), "system": system_problems(seen["procs"]),
            "pages": page_problems(seen["procs"], seen["rows"], seen["gpu"])}


def control_problems(seen: dict, found: dict) -> list[str]:
    """The negative control: every witness must have reported the browser started with --no-sandbox, and for
    the right reason: the system must name every renderer it saw, and the pages at least one of them (a
    renderer may have started after chrome://sandbox was read). Any other report, such as a browser that did
    not start, is not the control being caught."""
    renderers = [who(p) for p in seen["procs"] if p["type"] == "renderer"]

    def named(reports: list[str]) -> list[str]:
        return [r for r in renderers if any(re.search(rf"\b{re.escape(r)}\b", report) for report in reports)]

    noticed = {"switch": bool(found["switch"]),
               "system": bool(renderers) and named(found["system"]) == renderers,
               "pages": bool(named(found["pages"]))}
    return [f"negative control: the {name} witness did not notice a browser started with --no-sandbox"
            for name in WITNESSES if not noticed[name]]


def notes(seen: dict) -> list[str]:
    out = [f"{who(p)} is not sandboxed by design (--service-sandbox-type={declared(p['cmd'])})"
           for p in seen["procs"] if by_design(p)]
    browser = next((p["facts"] for p in seen["procs"] if p["type"] == "browser" and p["facts"]), None)
    if browser and browser["integrity"] is not None and browser["integrity"] > smoke.MEDIUM_INTEGRITY:
        out.append(f"the browser itself runs at {level(browser['integrity'])} integrity: it was started from an "
                   "elevated shell")
    return out


def describe(title: str, seen: dict) -> str:
    """One observed browser as text: what Windows reported for each process and what the pages showed."""
    lines = [f"{title} ({seen['browser'] or 'version unknown'})", "  Windows reports:"]
    for p in seen["procs"]:
        f = p["facts"]
        said = "token could not be read" if f is None else (
            f"{level(f['integrity'])} integrity, token {'restricted' if f['restricted'] else 'not restricted'}"
            + (", AppContainer" if f["appcontainer"] else "") + f", {privileges(f['privileges'])}, "
            + ("in a job" if f["in_job"] else "in no job") + "; sandbox mitigations: "
            + (", ".join(f["mitigations"]) or "none"))
        lines.append(f"    {who(p)}: {said}")
    lines.append("  chrome://sandbox shows:")
    lines += [f"    {' '.join(x for x in (str(r['pid']), r['type'], r['name']) if x)}: {r['sandbox']}"
              + (f", {r['lockdown']}, {r['integrity']}" if r["sandbox"] != NOT_SANDBOXED else "")
              for r in seen["rows"]] or ["    nothing"]
    if seen["features"]:
        lines.append("    features: " + ", ".join(seen["features"]))
    lines.append(f"  chrome://gpu shows: Sandboxed: {'not said' if seen['gpu'] is None else str(seen['gpu']).lower()}")
    return "\n".join(lines + [f"  note: {n}" for n in notes(seen)])


# --- what Windows says about one process -------------------------------------------------------------------------

@functools.cache
def _windows():
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    a32 = ctypes.WinDLL("advapi32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    k32.GetProcessMitigationPolicy.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
    a32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    a32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
    a32.IsTokenRestricted.argtypes = [wintypes.HANDLE]
    return ctypes, wintypes, k32, a32


def _windows_facts(pid: int) -> dict | None:
    """Integrity level, token restrictions, job and mitigation policies of a process, or None."""
    ctypes, wintypes, k32, a32 = _windows()
    process = k32.OpenProcess(0x0400, False, pid)                       # PROCESS_QUERY_INFORMATION
    if not process:
        return None
    try:
        token = wintypes.HANDLE()
        if not a32.OpenProcessToken(process, 0x0008, ctypes.byref(token)):   # TOKEN_QUERY
            return None
        try:
            word, size = wintypes.DWORD(), wintypes.DWORD()
            if not a32.GetTokenInformation(token, 29, ctypes.byref(word), 4, ctypes.byref(size)):
                return None                                             # TokenIsAppContainer
            appcontainer = bool(word.value)
            a32.GetTokenInformation(token, 3, None, 0, ctypes.byref(size))   # TokenPrivileges: count first
            room = ctypes.create_string_buffer(max(size.value, 4))
            if not a32.GetTokenInformation(token, 3, room, size, ctypes.byref(size)):
                return None
            held = int.from_bytes(room.raw[:4], "little")
            restricted = bool(a32.IsTokenRestricted(token))
        finally:
            k32.CloseHandle(token)
        in_job, flags = wintypes.BOOL(), {}
        if not k32.IsProcessInJob(process, None, ctypes.byref(in_job)):
            return None
        for policy in MITIGATIONS:
            word = wintypes.DWORD()
            if k32.GetProcessMitigationPolicy(process, policy, ctypes.byref(word), 4):
                flags[policy] = word.value
    finally:
        k32.CloseHandle(process)
    return {"integrity": smoke._integrity_rid(pid), "restricted": restricted, "appcontainer": appcontainer,
            "privileges": held, "in_job": bool(in_job.value), "mitigations": mitigation_names(flags)}


# The systems that are checked, by os.name: how the facts of one process are read, and the rules they must meet.
SYSTEMS = {"nt": (_windows_facts, windows_problems)}


# --- one observed browser ----------------------------------------------------------------------------------------

def _read(port: int, url: str, expression: str, ready, wait: float = 30) -> str:
    """Open a page in a new tab and return what `expression` gives once `ready` accepts it."""
    ws = WebSocket(_open(port, url)["webSocketDebuggerUrl"])
    try:
        deadline, value = time.monotonic() + wait, ""
        while True:
            time.sleep(1)
            value = ws.call("Runtime.evaluate", expression=expression, returnByValue=True)["result"].get("value", "")
            if ready(value) or time.monotonic() > deadline:
                return value
    finally:
        ws.close()


def observe(browser: Path, work: Path, facts, extra: tuple[str, ...] = ()) -> dict:
    """Start the browser, open a local page and the two pages, and collect what the system and the pages say."""
    profile = Path(tempfile.mkdtemp(prefix="sandbox-", dir=work))
    with bench.PingServer() as server:
        proc, port = soak.launch(browser, profile, extra), None
        try:
            port = _devtools_port(profile)
            _open(port, server.url("page"))
            if not server.wait(60):
                raise RuntimeError("the local test page did not load")
            gpu = gpu_sandboxed(_read(port, "chrome://gpu", TEXT_JS, lambda text: gpu_sandboxed(text) is not None))
            ws = WebSocket(_open(port, "chrome://sandbox")["webSocketDebuggerUrl"])
            try:
                deadline, table = time.monotonic() + 30, []
                while len(table) < 2 and time.monotonic() < deadline:
                    time.sleep(1)
                    table = json.loads(ws.call("Runtime.evaluate", expression=ROWS_JS,
                                               returnByValue=True)["result"].get("value") or "[]")
                raw = ws.call("Runtime.evaluate", expression=RAW_JS, returnByValue=True)["result"].get("value", "")
            finally:
                ws.close()
            procs = [{"pid": p["pid"], "cmd": p["cmd"], "facts": facts(p["pid"]),
                      "type": "browser" if p["pid"] == proc.pid else soak.process_type(p["cmd"])}
                     for p in soak.process_tree(proc.pid)]
            return {"procs": procs, "rows": parse_rows(table), "features": parse_features(raw), "gpu": gpu,
                    "browser": soak._get(port, "version").get("Browser", "")}
        finally:
            soak.stop(proc, port, profile)


def run(browser: Path, work: Path, switches: tuple[str, ...] = (), say=print) -> tuple[list[str], str]:
    """The check: the browser as it starts (plus `switches`, to try the check on a weakened browser), then the
    negative control. Returns (problems, evidence text)."""
    facts, rules = SYSTEMS[os.name]
    seen = observe(browser, work, facts, switches)
    found = judge(seen, rules)
    problems = [p for name in WITNESSES for p in found[name]]
    text = [describe("Started with " + " ".join(switches) if switches else "Sandbox on", seen)]
    say(text[0])
    say(f"{'PASS' if not problems else 'FAIL'}  the browser's sandbox: "
        + ("no witness reports a problem" if not problems else f"{len(problems)} problem(s)"))
    control = observe(browser, work, facts, ("--no-sandbox",))
    caught = judge(control, rules)
    missed = control_problems(control, caught)
    text.append(describe("Negative control, started with --no-sandbox", control))
    say(text[1])
    say(f"{'PASS' if not missed else 'FAIL'}  negative control: "
        + ", ".join(f"{name} {len(caught[name])} report(s)" for name in WITNESSES))
    problems += missed
    text.append("\n".join(problems) if problems else "No witness reports a problem with the sandbox on, and every "
                "witness reported the browser started with --no-sandbox.")
    return problems, "\n\n".join(text)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profiles")
    p.add_argument("--evidence", type=Path, help="where the evidence is written (default: sandbox.txt in --work)")
    p.add_argument("--switch", action="append", default=[], metavar="SWITCH",
                   help="an extra switch for the checked browser, to see the check fail on a weakened one, for "
                        "example --switch=--disable-gpu-sandbox (may be given more than once)")
    a = p.parse_args(argv)
    if os.name not in SYSTEMS:
        print("SANDBOX CHECK: NOT RUN (only Windows is checked so far; see the top of this file for Linux)")
        return 2
    a.work.mkdir(parents=True, exist_ok=True)
    try:
        problems, text = run(a.browser.resolve(), a.work, tuple(a.switch))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, IndexError, soak.SoakError) as e:
        problems, text = [f"the run failed: {e}"], ""
    verdict = "SANDBOX CHECK: PASSED" if not problems else f"SANDBOX CHECK: FAILED ({len(problems)} problem(s))"
    (a.evidence or a.work / "sandbox.txt").write_text(f"{text}\n\n{verdict}\n", encoding="utf-8", newline="\n")
    for problem in problems:
        print(problem)
    print(verdict)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="backslashreplace", line_buffering=True)
    sys.exit(main(sys.argv[1:]))
