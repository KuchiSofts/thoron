#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Memory-leak soak test (ROADMAP Q.4): hours of opening and closing tabs, and a pass/fail limit on memory growth.

The browser runs headless on a throwaway profile in --work, the sandbox stays on, and every page comes from a
local server on 127.0.0.1 (the resolver is told to find no other host), so nothing leaves the machine and no real
profile is touched. This tool makes three kinds of page: one heavy in DOM nodes, one in images and one in script.
In a loop, --tabs of them are opened, left to finish their work, and closed again.

What is measured: the private memory (commit; on Linux anonymous memory plus swap) of the browser's own process
tree, read from the system for the browser process, the GPU process, the renderers and the utility processes.
Two kinds of sample go to the CSV:

    churn    taken in every round while the tabs are open: the picture of the load, not judged
    settled  taken every --interval with every test tab closed, after a forced garbage collection and a
             memory-pressure notification, once the number of the browser's processes has stood still for
             --settle: the browser is in the same state every time, so these samples can be compared

How a run is judged: only the settled samples of the second half count (the first half is warm-up: caches
fill, code is compiled). A trend line is fitted to them as the median of the slopes between every two samples
(Theil-Sen), which a few outliers do not move. The run fails when all three hold:

    1. the trend is steeper than --threshold, in MB per hour,
    2. the growth along the trend over that half is more than the noise: three times the scatter of the
       settled samples (measured around the line and from the jumps between one sample and the next; the
       larger counts), and never less than 5 MB, and
    3. the final quarter of the run still climbs at more than half the threshold: memory that rose and then
       stays flat (a step up, or growth that stopped) is a cache that filled, not a leak.

It also fails when the browser exits or writes a crash dump, when pages did not finish loading (no churn, no
test), and when there are fewer than 20 settled samples. The shorter the run, the less it can see: over minutes
only a gross leak rises above the noise, and the limit in MB per hour is what decides over hours.

    py -3 -I tools/qa/soak.py --browser <out>\\thoron.exe --work <scratch dir> [--duration 8h] [--interval 5m]
        [--threshold 10] [--tabs 6] [--settle 10s] [--csv <file>] [--report <file>]
Exit status 0 only when the run passes. Run nothing heavy beside it. The run is headless, like the other checks:
a leak that needs a visible window is outside it.
"""
import argparse
import csv
import functools
import http.server
import json
import os
import random
import re
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zlib
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.build import smoke  # noqa: E402
from tools.qa.adblock_site_switch_check import _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

KINDS = ("dom", "images", "script")
TYPES = ("browser", "gpu", "renderer", "utility", "other")
CSV_HEADER = ["elapsed_s", "phase", "tabs", "total_mb", *(f"{t}_mb" for t in TYPES), "processes", "renderers"]
THRESHOLD_MB_PER_HOUR = 10.0
NOISE_TIMES = 3.0           # growth must be more than this many times the scatter around the trend line
NOISE_FLOOR_MB = 5.0        # and never less than this
MIN_SETTLED = 20            # fewer settled samples than this cannot be judged
LOADED_SHARE = 0.95         # at least this share of the opened pages must have finished their work
IMAGE_SIDE = 400
LOAD_TIMEOUT_S = 45.0


class SoakError(Exception):
    pass


# --- the decision: pure functions -------------------------------------------------------------------------------

def seconds(text: str) -> float:
    """A length of time: '8h', '5m', '90s', or a plain number of seconds."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([hms]?)\s*", text.lower())
    if not m or float(m.group(1)) <= 0:
        raise ValueError(f"not a length of time: {text!r}")
    return float(m.group(1)) * {"h": 3600, "m": 60, "s": 1, "": 1}[m.group(2)]


def theil_sen(points: list[tuple[float, float]]) -> float:
    """Slope of the trend line through (x, y) points: the median of the slopes between every two of them."""
    slopes = [(y2 - y1) / (x2 - x1) for i, (x1, y1) in enumerate(points) for x2, y2 in points[i + 1:] if x2 != x1]
    return statistics.median(slopes) if slopes else 0.0


def scatter(points: list[tuple[float, float]], slope: float) -> float:
    """How far the points lie from a line of that slope, as a robust standard deviation (1.4826 x MAD)."""
    off = [y - slope * x for x, y in points]
    middle = statistics.median(off)
    return 1.4826 * statistics.median(abs(o - middle) for o in off)


def jump_scatter(points: list[tuple[float, float]]) -> float:
    """The noise of one sample, from the jumps between each sample and the next, which a slow trend does not
    show in: 1.4826 x MAD of the jumps, over the square root of two."""
    jumps = [b[1] - a[1] for a, b in zip(points, points[1:])]
    if not jumps:
        return 0.0
    middle = statistics.median(jumps)
    return 1.4826 * statistics.median(abs(j - middle) for j in jumps) / 2 ** 0.5


def analyse(samples: list[tuple[float, float]], threshold: float = THRESHOLD_MB_PER_HOUR) -> dict:
    """Judge settled samples (seconds since the start, MB), in time order. `leak` is the verdict; `judged` is
    False when there are too few samples for one."""
    if len(samples) < MIN_SETTLED:
        return {"judged": False, "leak": False, "samples": len(samples)}
    half = samples[len(samples) // 2:]
    quarter = half[len(half) // 2:]
    per_second = theil_sen(half)
    slope = per_second * 3600
    hours = (half[-1][0] - half[0][0]) / 3600
    growth = slope * hours
    # two estimates of the noise, the larger counts: around the trend line of the judged half (few samples in a
    # short run, so it can come out too small by chance), and from the jumps over the whole run
    noise = max(scatter(half, per_second), jump_scatter(samples))
    floor = max(NOISE_TIMES * noise, NOISE_FLOOR_MB)
    tail = theil_sen(quarter) * 3600
    return {"judged": True, "leak": slope > threshold and growth > floor and tail > threshold / 2,
            "samples": len(samples), "judged_samples": len(half), "hours": hours, "slope": slope, "growth": growth,
            "noise": noise, "floor": floor, "tail_slope": tail, "threshold": threshold,
            "first": samples[0][1], "level": statistics.median(y for _, y in half)}


def wait_quiet(count, quiet: float, limit: float, sleep=time.sleep, clock=time.monotonic) -> bool:
    """Wait until count() has stood still for `quiet` seconds. False when `limit` seconds pass first."""
    start = since = clock()
    last = count()
    while clock() - since < quiet:
        if clock() - start >= limit:
            return False
        sleep(min(1.0, quiet))
        now = count()
        if now != last:
            last, since = now, clock()
    return True


def process_type(cmd: str) -> str:
    """The type of a child process of the browser, from its command line."""
    m = re.search(r"--type=([\w-]+)", cmd)
    return {"renderer": "renderer", "gpu-process": "gpu", "utility": "utility"}.get(m.group(1) if m else "", "other")


def family(procs: list[dict], root: int) -> list[dict]:
    """The process `root` and its descendants, from pid, ppid and born (start time). A process counts as a child
    only when it started no earlier than its parent: process numbers are used again, so a process whose parent
    has gone can carry the number of a newer process that has nothing to do with it."""
    by_pid = {p["pid"]: p for p in procs}
    if root not in by_pid:
        raise SoakError(f"process {root} is not running")
    out, todo, seen = [], [root], {root}
    while todo:
        parent = by_pid[todo.pop()]
        out.append(parent)
        for p in procs:
            if p["ppid"] == parent["pid"] and p["pid"] not in seen and p["born"] >= parent["born"]:
                seen.add(p["pid"])
                todo.append(p["pid"])
    return out


def by_type(tree: list[dict], root: int) -> dict:
    """Private memory of a process tree in MB: in all and for each process type, and the process counts."""
    out = {t: 0.0 for t in TYPES}
    kinds = ["browser" if p["pid"] == root else process_type(p["cmd"]) for p in tree]
    for p, kind in zip(tree, kinds):
        out[kind] += p["private"] / 2**20
    out["total"] = sum(out[t] for t in TYPES)
    out["processes"], out["renderers"] = len(tree), kinds.count("renderer")
    return out


def linux_private(status: str) -> int:
    """Private memory in bytes from the text of /proc/<pid>/status: anonymous memory in RAM plus swap."""
    found = dict(re.findall(r"^(RssAnon|VmSwap):\s*(\d+) kB", status, re.M))
    return (int(found.get("RssAnon", 0)) + int(found.get("VmSwap", 0))) * 1024


def csv_row(elapsed: float, phase: str, tabs: int, memory: dict) -> list:
    return [round(elapsed, 1), phase, tabs, round(memory["total"], 1), *(round(memory[t], 1) for t in TYPES),
            memory["processes"], memory["renderers"]]


def problems(result: dict) -> list[str]:
    """Why a run fails (empty list: it passes)."""
    out = list(result.get("errors", []))
    opened, loaded = result.get("opened", 0), result.get("loaded", 0)
    if not opened or loaded < LOADED_SHARE * opened:
        out.append(f"only {loaded} of {opened} pages finished their work: the tabs were not really churned")
    if result.get("crash_dumps"):
        out.append(f"crash dump(s) written: {', '.join(result['crash_dumps'])}")
    verdict = result["verdict"]
    unforced = result.get("unforced", [])
    if unforced and len(unforced) >= verdict["samples"]:     # a miss now and then is a note in the report
        out.append(f"no settled sample is comparable: every time, {unforced[-1]}")
    if not verdict["judged"]:
        out.append(f"only {verdict['samples']} settled sample(s), {MIN_SETTLED} are needed: run longer, or with a "
                   "shorter --interval")
    elif verdict["leak"]:
        out.append(f"memory keeps growing: {verdict['slope']:+.1f} MB per hour over the second half of the run "
                   f"({verdict['growth']:+.1f} MB in {verdict['hours']:.2f} h, noise floor {verdict['floor']:.1f} MB), "
                   f"and still {verdict['tail_slope']:+.1f} MB per hour in the final quarter; the limit is "
                   f"{verdict['threshold']:g} MB per hour")
    return out


def build_of(browser: Path) -> str:
    """The build version of a browser folder (Chrome-bin): the one folder beside the program named like
    158.0.8127.3010; empty when there is not exactly one."""
    found = [p.name for p in browser.parent.iterdir()
             if p.is_dir() and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", p.name)] if browser.parent.is_dir() else []
    return found[0] if len(found) == 1 else ""


def report(result: dict) -> str:
    """The short report of a run."""
    v = result["verdict"]
    lines = [f"Soak: {result['seconds'] / 3600:.2f} h, {result['rounds']} rounds of {result['tabs']} tabs, "
             f"{result['opened']} pages opened, {result['loaded']} finished their work, "
             f"{v['samples']} settled samples",
             f"Build: {result.get('build') or 'unknown'}",
             "Private memory of the browser's process tree, in MB:",
             f"  with the tabs open: at most {result['peak']:.1f}"]
    if result.get("unforced"):
        lines.insert(1, f"Note: before {len(result['unforced'])} settled sample(s), {result['unforced'][-1]}")
    if v["judged"]:
        lines += [f"  settled: first sample {v['first']:.1f}, median of the second half {v['level']:.1f}",
                  f"  trend over the second half ({v['hours']:.2f} h, {v['judged_samples']} samples): "
                  f"{v['slope']:+.2f} MB per hour, {v['growth']:+.1f} MB in all",
                  f"  scatter of the settled samples {v['noise']:.2f}, noise floor {v['floor']:.1f}",
                  f"  trend over the final quarter: {v['tail_slope']:+.2f} MB per hour",
                  "  trend by process type, MB per hour: "
                  + ", ".join(f"{t} {result['slopes'][t]:+.2f}" for t in TYPES),
                  f"Limit: {v['threshold']:g} MB per hour, above the noise floor, still climbing in the final "
                  "quarter"]
    found = problems(result)
    return "\n".join(lines + found + ["SOAK: PASSED" if not found else f"SOAK: FAILED ({len(found)} problem(s))"])


# --- the test pages, made here and served on 127.0.0.1 -------------------------------------------------------

def png(width: int, height: int, seed: int) -> bytes:
    """A PNG of noise (it does not compress, so the browser has real work decoding it)."""
    rnd = random.Random(seed)
    raw = b"".join(b"\0" + rnd.randbytes(width * 3) for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


def _page(kind: str, body: str, script: str) -> str:
    return ("<!doctype html><html><head><meta charset='utf-8'><title>soak " + kind + "</title><style>"
            "td{border:1px solid #999;padding:2px}.on{background:#def}img{width:150px;height:150px}"
            "</style></head><body>" + body + "<script>const done = () => fetch('/done/" + kind
            + "').catch(() => {});\n" + script + "</script></body></html>")


def dom_page(rows: int = 1500) -> str:
    """Some twenty thousand elements, and a timer that keeps adding, removing and restyling nodes."""
    cells = "".join(f"<td><span class='c{c}'>cell {c}</span></td>" for c in range(6))
    table = "".join(f"<tr id='r{r}'>{cells}</tr>" for r in range(rows))
    return _page("dom", f"<table>{table}</table><ul id='list'></ul>", """
let round = 0;
const list = document.getElementById('list');
const rows = document.querySelectorAll('tr');
setInterval(() => {
  for (let i = 0; i < 300; i++) {
    const li = document.createElement('li');
    li.textContent = 'item ' + round + '.' + i;
    list.appendChild(li);
  }
  while (list.children.length > 900) list.removeChild(list.firstChild);
  for (let i = round % 7; i < rows.length; i += 7) rows[i].classList.toggle('on');
  if (++round === 3) done();
}, 250);""")


def images_page(count: int = 12) -> str:
    """A dozen separately loaded pictures, drawn to a canvas as well. Reading a pixel back makes the browser
    decode and draw them at once, in a background tab too (img.decode() waits there for a frame that never
    comes)."""
    pictures = "".join(f"<img src='/image/{i}.png' alt=''>" for i in range(count))
    return _page("images", pictures, """
addEventListener('load', () => {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 800;
  const paint = canvas.getContext('2d');
  [...document.images].forEach((picture, n) => {
    try { paint.drawImage(picture, (n % 4) * 200, Math.floor(n / 4) * 200, 200, 200); } catch (e) {}
  });
  paint.getImageData(0, 0, 1, 1);
  document.body.appendChild(canvas);
  done();
});""")


def script_page() -> str:
    """Maps, arrays, strings and typed arrays made, sorted, turned to JSON and back, and partly let go."""
    return _page("script", "<p>script</p>", """
const keep = [];
let round = 0;
function work() {
  const map = new Map();
  for (let i = 0; i < 40000; i++) map.set('k' + i + '_' + round, {i, text: 'v'.repeat(16) + i, list: [i, i + 1]});
  const numbers = Array.from({length: 150000}, (_, i) => (i * 2654435761) % 1000003);
  numbers.sort((a, b) => a - b);
  const text = JSON.stringify([...map.values()].slice(0, 15000));
  keep.push(map, JSON.parse(text), new Float64Array(200000), numbers);
  if (keep.length > 12) keep.splice(0, 4);
  if (++round === 3) done();
}
setInterval(work, 300);""")


class _Quiet(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass    # a tab closed while its page was still loading


class Pages:
    """The test pages on 127.0.0.1: /dom, /images, /script, the pictures of /images, and /done/<kind>, which
    every page asks for once its work is done."""

    def __init__(self):
        self.loaded = 0
        self._changed = threading.Condition()
        pages = {"/dom": dom_page().encode(), "/images": images_page().encode(), "/script": script_page().encode()}
        pictures = [png(IMAGE_SIDE, IMAGE_SIDE, seed) for seed in range(4)]
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                kind, body = "text/html; charset=utf-8", pages.get(path)
                if path.startswith("/image/"):
                    number = path[len("/image/"):].split(".")[0]
                    kind, body = "image/png", pictures[int(number) % len(pictures)] if number.isdigit() else None
                elif path.startswith("/done/"):
                    with outer._changed:
                        outer.loaded += 1
                        outer._changed.notify_all()
                    kind, body = "text/plain", b"ok"
                self.send_response(200 if body is not None else 404)
                body = body if body is not None else b"no"
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        self._httpd = _Quiet(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def url(self, kind: str) -> str:
        return f"{self.base}/{kind}"

    def wait(self, count: int, timeout: float) -> bool:
        """Wait until `count` pages in all have said that their work is done."""
        with self._changed:
            return self._changed.wait_for(lambda: self.loaded >= count, timeout)

    def __enter__(self):
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


# --- the browser's process tree, read from the system ----------------------------------------------------------

@functools.cache
def _windows():
    """The Windows calls used here: (list of (pid, ppid), details of one pid or None)."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):          # PROCESSENTRY32W
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("ppid", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                    ("exe", wintypes.WCHAR * 260)]

    class Memory(ctypes.Structure):         # PROCESS_MEMORY_COUNTERS_EX
        _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in (
            "peak_working_set", "working_set", "peak_paged_pool", "paged_pool", "peak_nonpaged_pool",
            "nonpaged_pool", "pagefile", "peak_pagefile", "private")]

    class Text(ctypes.Structure):           # UNICODE_STRING
        _fields_ = [("length", wintypes.USHORT), ("room", wintypes.USHORT), ("at", ctypes.c_void_p)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long
    ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
                                                ctypes.POINTER(wintypes.ULONG)]

    def snapshot() -> list[tuple[int, int]]:
        handle = k32.CreateToolhelp32Snapshot(0x2, 0)                  # TH32CS_SNAPPROCESS
        if handle in (None, ctypes.c_void_p(-1).value):
            raise SoakError("the list of processes could not be read")
        try:
            entry, out = Entry(size=ctypes.sizeof(Entry)), []
            more = k32.Process32FirstW(handle, ctypes.byref(entry))
            while more:
                out.append((entry.pid, entry.ppid))
                more = k32.Process32NextW(handle, ctypes.byref(entry))
            return out
        finally:
            k32.CloseHandle(handle)

    def details(pid: int) -> dict | None:
        handle = k32.OpenProcess(0x1000, False, pid)                   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            memory = Memory(size=ctypes.sizeof(Memory))
            if not k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)) or \
                    not k32.K32GetProcessMemoryInfo(handle, ctypes.byref(memory), ctypes.sizeof(memory)):
                return None
            cmd, need = "", wintypes.ULONG(0)
            ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(need))   # the command line
            if need.value >= ctypes.sizeof(Text):
                room = ctypes.create_string_buffer(need.value)
                if ntdll.NtQueryInformationProcess(handle, 60, room, need, ctypes.byref(need)) == 0:
                    text = Text.from_buffer(room)
                    cmd = ctypes.wstring_at(text.at, text.length // 2) if text.at else ""
            return {"born": (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime, "cmd": cmd,
                    "private": int(memory.private)}
        finally:
            k32.CloseHandle(handle)

    return snapshot, details


def process_tree(root: int) -> list[dict]:
    """The browser process `root` and its descendants: pid, ppid, born, cmd and private memory in bytes."""
    if os.name == "nt":
        snapshot, details = _windows()
        # everything below the root by parent number alone; the start times then weed out reused numbers
        below = family([{"pid": pid, "ppid": ppid, "born": 0} for pid, ppid in snapshot()], root)
        known = [dict(p, **d) for p in below if (d := details(p["pid"]))]
        return family(known, root)
    procs = []
    for d in Path("/proc").iterdir():
        if d.name.isdigit():
            try:
                f = (d / "stat").read_text().rsplit(")", 1)[1].split()
                procs.append({"pid": int(d.name), "ppid": int(f[1]), "born": int(f[19])})
            except (OSError, IndexError, ValueError):
                continue
    out = []
    for p in family(procs, root):
        try:
            cmd = Path(f"/proc/{p['pid']}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            out.append(dict(p, cmd=cmd, private=linux_private(Path(f"/proc/{p['pid']}/status").read_text())))
        except OSError:
            continue
    return out


# --- the browser ---------------------------------------------------------------------------------------------

def launch(browser: Path, profile: Path, extra: tuple[str, ...] = ()) -> subprocess.Popen:
    """The browser headless on a throwaway profile, offline but for 127.0.0.1, DevTools on 127.0.0.1 only."""
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-default-apps", "--disable-background-networking",
            "--disable-component-update", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", *extra, "about:blank"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=os.name != "nt")


def stop(proc: subprocess.Popen, port: int | None, profile: Path) -> None:
    """Close the browser this run started, and remove its profile. The browser is asked to exit; if it does not,
    that one process is ended through the handle this run holds, never by name and never by walking process
    numbers (they are used again). Its child processes leave when the browser does."""
    if port is not None and proc.poll() is None:
        try:
            ws = WebSocket(_get(port, "version")["webSocketDebuggerUrl"])
            try:
                ws.call("Browser.close")
            except (ConnectionError, OSError, RuntimeError):
                pass
            finally:
                ws.close()
            proc.wait(timeout=30)
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            pass
    if proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pass
    for _ in range(10):         # the child processes let go of the profile's files a moment later
        time.sleep(1)
        shutil.rmtree(profile, ignore_errors=True)
        if not profile.exists():
            break


def _get(port: int, what: str):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/{what}", timeout=20).read())


def _open_tab(port: int, url: str) -> str:
    for _ in range(2):          # a busy browser may miss one request; it must not end a run of hours
        try:
            return _open(port, url)["id"]
        except OSError:
            time.sleep(2)
    return _open(port, url)["id"]


def _close_tab(port: int, target: str) -> None:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{target}", timeout=20).read()
    except OSError:
        pass                    # it is closed again before the next settled sample


def _settle(port: int, base: str) -> str:
    """Bring the browser to its resting state: every tab but the first closed, garbage collected in that tab,
    a memory-pressure notification. Returns what could not be forced, if anything."""
    for target in _get(port, "list"):
        if target.get("type") == "page" and target.get("id") != base:
            _close_tab(port, target["id"])
    missed = ""
    try:
        ws = WebSocket(next(t for t in _get(port, "list") if t.get("id") == base)["webSocketDebuggerUrl"])
        try:
            ws.call("HeapProfiler.collectGarbage")
            ws.call("Memory.simulatePressureNotification", level="critical")
        finally:
            ws.close()
    except (OSError, RuntimeError, StopIteration, KeyError, ValueError) as e:
        missed = f"garbage collection could not be forced: {e}"
    return missed


def run(browser: Path, work: Path, duration: float, interval: float, threshold: float, tabs: int, csv_path: Path,
        dwell: float = 2.0, settle: float = 10.0, say=print) -> dict:
    """One soak run. Returns what `report` and `problems` take."""
    profile = Path(tempfile.mkdtemp(prefix="soak-", dir=work))
    settled: list[tuple[float, dict]] = []
    result = {"seconds": 0.0, "rounds": 0, "tabs": tabs, "opened": 0, "loaded": 0, "peak": 0.0, "errors": [],
              "unforced": [], "crash_dumps": [], "build": build_of(browser)}
    with Pages() as pages, open(csv_path, "w", newline="", encoding="utf-8") as out:
        rows = csv.writer(out)
        rows.writerow(CSV_HEADER)
        proc, port = launch(browser, profile), None
        try:
            port = _devtools_port(profile)
            base = next(t["id"] for t in _get(port, "list") if t.get("type") == "page")
            start = time.monotonic()

            def sample(phase: str, open_tabs: int) -> dict:
                memory = by_type(process_tree(proc.pid), proc.pid)
                elapsed = time.monotonic() - start
                rows.writerow(csv_row(elapsed, phase, open_tabs, memory))
                out.flush()
                if phase == "settled":
                    settled.append((elapsed, memory))
                    say(f"settled {elapsed / 3600:6.2f} h  {memory['total']:8.1f} MB  ("
                        + ", ".join(f"{t} {memory[t]:.1f}" for t in TYPES)
                        + f"; {memory['processes']} processes)  rounds {result['rounds']}")
                return memory

            def rest() -> None:
                missed = _settle(port, base)
                if missed:
                    result["unforced"].append(missed)
                # the processes of the closed tabs take a moment to leave, longer on a busy machine
                wait_quiet(lambda: len(process_tree(proc.pid)), settle, 6 * settle)
                sample("settled", 0)

            rest()
            due, rested = interval, True
            while time.monotonic() - start < duration:
                if proc.poll() is not None:
                    raise SoakError(f"the browser exited after {(time.monotonic() - start) / 3600:.2f} h")
                before = pages.loaded
                # the last tab opened is the one in front: the kinds take turns at it
                opened = [_open_tab(port, pages.url(KINDS[(result["rounds"] + i) % len(KINDS)]))
                          for i in range(tabs)]
                result["opened"] += tabs
                pages.wait(before + tabs, LOAD_TIMEOUT_S)
                time.sleep(dwell)
                result["peak"] = max(result["peak"], sample("churn", tabs)["total"])
                for target in opened:
                    _close_tab(port, target)
                result["rounds"] += 1
                rested = False
                time.sleep(0.5)
                if time.monotonic() - start >= due:
                    rest()
                    rested = True
                    while due <= time.monotonic() - start:     # on a slow machine, missed turns are skipped
                        due += interval
            if not rested:
                rest()
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, IndexError, StopIteration, SoakError) as e:
            result["errors"].append(f"the run stopped early: {e}")
        finally:
            result["seconds"] = settled[-1][0] if settled else 0.0
            result["loaded"] = pages.loaded
            result["crash_dumps"] = smoke._crash_dumps(profile)
            stop(proc, port, profile)
    result["verdict"] = analyse([(t, m["total"]) for t, m in settled], threshold)
    half = settled[len(settled) // 2:]
    result["slopes"] = {kind: theil_sen([(t, m[kind]) for t, m in half]) * 3600 for kind in TYPES}
    return result


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profile")
    p.add_argument("--duration", type=seconds, default=seconds("8h"), help="how long to churn: 8h, 30m, 600s")
    p.add_argument("--interval", type=seconds, default=seconds("5m"), help="time between settled samples")
    p.add_argument("--threshold", type=float, default=THRESHOLD_MB_PER_HOUR,
                   help="growth of the settled memory that fails the run, in MB per hour")
    p.add_argument("--tabs", type=int, default=6, help="tabs opened and closed in every round")
    p.add_argument("--settle", type=seconds, default=seconds("10s"),
                   help="how long the number of the browser's processes must stand still before a settled "
                        "sample (it waits at most six times as long)")
    p.add_argument("--csv", type=Path, help="every sample (default: soak.csv in --work)")
    p.add_argument("--report", type=Path, help="the short report (default: soak.txt in --work)")
    a = p.parse_args(argv)
    if a.tabs < 1 or a.threshold <= 0:
        p.error("--tabs and --threshold must be positive")
    a.work.mkdir(parents=True, exist_ok=True)
    result = run(a.browser.resolve(), a.work, a.duration, a.interval, a.threshold, a.tabs,
                 a.csv or a.work / "soak.csv", settle=a.settle)
    text = report(result)
    (a.report or a.work / "soak.txt").write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not problems(result) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="backslashreplace", line_buffering=True)   # progress shows in a log file too
    sys.exit(main(sys.argv[1:]))
