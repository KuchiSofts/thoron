#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The online benchmark suites (ROADMAP Q.1): Speedometer 3.0, JetStream 2.1 and MotionMark 1.3.1, as published on
browserbench.org, in a real window on the screen (they measure frames as a person sees them), each with a
throwaway profile of its own.

    speedometer3   ?startAutomatically=true; the score is #result-number (runs per minute, higher is better)
    jetstream2     JetStream.start() once its Start button is there; the score is the one in #result-summary
                   (higher is better); never ?report=true, which posts the results to the site
    motionmark     benchmarkController.startBenchmark(); the score is #results-score (higher is better)

This is an online measurement: the pages come from browserbench.org; nothing is sent but the requests for them.
Run nothing else on the PC meanwhile (the numbers are only comparable between quiet runs).
    py -3 -I tools/qa/online_bench.py --browser <out>\\thoron.exe --label "Thoron 158" --work <scratch dir>
        [--runs 3] [--suite speedometer3 --suite jetstream2 --suite motionmark] [--json <file>]
"""
import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

# A window that another window covers, or that is not in front, is slowed down by Chromium (fewer frames,
# slower timers): the suites, which count frames, would then measure the desktop. These keep every run the same.
KEEP_RENDERING = ("--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                  "--disable-background-timer-throttling", "--disable-features=CalculateNativeWinOcclusion")

SUITES = {
    "speedometer3": {
        "url": "https://browserbench.org/Speedometer3.0/?startAutomatically=true",
        "start": None,
        "done": "(() => { const s = document.getElementById('summary'); const n = document.getElementById("
                "'result-number'); return s && n && getComputedStyle(s).display !== 'none' && n.textContent.trim() "
                "? n.textContent.trim() : ''; })()",
        "minutes": 12,
    },
    "jetstream2": {
        "url": "https://browserbench.org/JetStream2.1/",
        # started only once its own "Start Test" button is there (its resources are loaded); never with
        # ?report=true, which would post the results to the site
        "start": "document.querySelector('#status a.button') && typeof JetStream !== 'undefined' ? "
                 "(JetStream.start(), 'started') : ''",
        "done": "(() => { const r = document.querySelector('#result-summary .score'); return r && r.textContent."
                "trim() ? r.textContent.trim() : ''; })()",
        "minutes": 20,
    },
    "motionmark": {
        "url": "https://browserbench.org/MotionMark1.3.1/",
        "start": "typeof benchmarkController !== 'undefined' ? (benchmarkController.startBenchmark(), 'started') : ''",
        "done": "(() => { const r = document.getElementById('results-score'); return r && r.textContent.trim() && "
                "/[0-9]/.test(r.textContent) ? r.textContent.trim() : ''; })()",
        "minutes": 20,
    },
}


def score_of(text: str) -> float | None:
    """The score in what a suite shows: the first number (a "± ..." after it is left out)."""
    m = re.search(r"\d+(?:\.\d+)?", (text or "").replace(",", ""))     # a comma groups thousands
    return float(m.group(0)) if m else None


def _page(port: int) -> WebSocket:
    listing = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10).read())
    return WebSocket(next(t for t in listing if t.get("type") == "page")["webSocketDebuggerUrl"])


def run_suite(browser: Path, name: str, work: Path, extra: tuple[str, ...] = ()) -> float:
    suite = SUITES[name]
    profile = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=work))
    proc = subprocess.Popen(
        [str(browser), f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-component-update", "--disable-extensions",
         *KEEP_RENDERING, *extra, "--window-position=40,40", "--window-size=1280,900", "--remote-debugging-port=0",
         suite["url"]],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = None
    try:
        port = _devtools_port(profile)
        ws = _page(port)
        try:
            end = time.monotonic() + 60
            if suite["start"]:
                while time.monotonic() < end:                 # the page loads, then the suite is started
                    got = ws.call("Runtime.evaluate", expression=suite["start"], returnByValue=True)
                    if got.get("result", {}).get("value") == "started":
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError(f"{name} could not be started")
            end = time.monotonic() + suite["minutes"] * 60
            while time.monotonic() < end:
                time.sleep(5)
                got = ws.call("Runtime.evaluate", expression=suite["done"], returnByValue=True)
                value = score_of(got.get("result", {}).get("value") or "")
                if value is not None:
                    return value
            raise RuntimeError(f"{name} gave no score within {suite['minutes']} minutes")
        finally:
            ws.close()
    finally:
        if port is not None:
            _close_browser(port, proc)
        else:
            bench._stop(proc, profile)
        shutil.rmtree(profile, ignore_errors=True)


def summarise(values: list[float]) -> dict:
    middle = statistics.median(values)
    spread = 100 * (max(values) - min(values)) / middle if middle else 0.0
    return {"median": round(middle, 2), "spread_pct": round(spread, 1), "runs": len(values),
            "values": [round(v, 2) for v in values]}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", type=Path, required=True)
    p.add_argument("--label", default="browser")
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--suite", action="append", choices=sorted(SUITES), help="default: all three")
    p.add_argument("--json", type=Path)
    p.add_argument("--switch", action="append", default=[], metavar="SWITCH",
                   help="one more browser switch, written --switch=--name=value; may be repeated")
    a = p.parse_args(argv)
    a.work.mkdir(parents=True, exist_ok=True)
    out = {"browser": a.label}
    for name in a.suite or list(SUITES):
        values = []
        for n in range(a.runs):
            try:
                values.append(run_suite(a.browser, name, a.work, tuple(a.switch)))
                print(f"{name} run {n + 1}: {values[-1]:g}", flush=True)
            except RuntimeError as exc:
                print(f"{name} run {n + 1}: {exc}", file=sys.stderr, flush=True)
        if values:
            out[name] = summarise(values)
    if a.json:
        a.json.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0 if all(name in out for name in (a.suite or list(SUITES))) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
