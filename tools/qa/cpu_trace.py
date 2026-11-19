#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Processor use of a running browser, process by process (ROADMAP P5.3: upstream #1313, background processes
that climb in CPU until the browser fails).

Watches the processes started from one browser folder (--browser-dir; nothing else is looked at) for a while,
without starting or touching any of them, and reads each one's processor time every --interval. It reports,
for each kind of process (browser, GPU, renderer, utility, crash handler), the share of one processor core it
used (median, 95th percentile, most), how many processes there were, and every process that stayed above
--limit percent of a core for longer than --sustain: that is a runaway, and the trace fails. A browser at work
uses the processor in bursts; a process that does not come down again is what the report describes.

Windows only (it reads the processes through CIM).
    py -3 -I tools/qa/cpu_trace.py --browser-dir <folder of thoron.exe> --minutes 60 [--interval 5]
        [--limit 50] [--sustain 120] [--csv <file>]
"""
import argparse
import csv
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

# Every process whose program lies in THORON_DIR: its id, kind (from --type=), processor time in 100 ns and
# working set, one JSON line per sample.
SAMPLE = r"""
$dir = $env:THORON_DIR.TrimEnd('\') + '\'
while ($true) {
  $now = [DateTime]::UtcNow.Ticks
  $rows = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($dir, [StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object {
      $kind = 'browser'
      if ($_.CommandLine -match '--type=([a-z-]+)') { $kind = $Matches[1] }
      @{ pid = [int]$_.ProcessId; kind = $kind; cpu = [int64]$_.KernelModeTime + [int64]$_.UserModeTime;
         ws = [int64]$_.WorkingSetSize } })
  [Console]::Out.WriteLine((ConvertTo-Json -Compress -Depth 3 -InputObject @{ t = $now; rows = $rows }))
  [Console]::Out.Flush()
  Start-Sleep -Seconds ([int]$env:THORON_INTERVAL)
}
"""
KINDS = {"gpu-process": "gpu", "renderer": "renderer", "utility": "utility", "crashpad-handler": "crashpad",
         "browser": "browser"}


def kind_of(raw: str) -> str:
    return KINDS.get(raw, "other")


def usage(samples: list[dict]) -> list[dict]:
    """Per process and interval: the share of one core it used (100 = one core busy all the time). A process
    seen first in a sample counts from the next one on."""
    out = []
    for before, after in zip(samples, samples[1:]):
        seconds = (after["t"] - before["t"]) / 1e7
        if seconds <= 0:
            continue
        earlier = {r["pid"]: r for r in before["rows"]}
        for row in after["rows"]:
            old = earlier.get(row["pid"])
            if old is None or row["cpu"] < old["cpu"]:
                continue
            out.append({"at": (after["t"] - samples[0]["t"]) / 1e7, "pid": row["pid"], "kind": kind_of(row["kind"]),
                        "pct": (row["cpu"] - old["cpu"]) / 1e7 / seconds * 100, "seconds": seconds})
    return out


def runaways(points: list[dict], limit: float, sustain: float) -> list[dict]:
    """Every process that stayed above `limit` percent of a core for longer than `sustain` seconds without a
    break: its id, kind, how long and its median share meanwhile."""
    longest: dict[int, dict] = {}
    streak: dict[int, dict] = {}
    for p in sorted(points, key=lambda p: (p["pid"], p["at"])):
        now = streak.setdefault(p["pid"], {"pid": p["pid"], "kind": p["kind"], "seconds": 0.0, "pcts": []})
        if p["pct"] > limit:
            now["seconds"] += p["seconds"]
            now["pcts"].append(p["pct"])
            if now["seconds"] > sustain and now["seconds"] > longest.get(p["pid"], {}).get("seconds", 0):
                longest[p["pid"]] = {**now, "pcts": list(now["pcts"])}
        else:
            streak[p["pid"]] = {"pid": p["pid"], "kind": p["kind"], "seconds": 0.0, "pcts": []}
    return [{"pid": r["pid"], "kind": r["kind"], "seconds": round(r["seconds"]),
             "median_pct": round(statistics.median(r["pcts"]), 1)} for r in longest.values()]


def summary(samples: list[dict], points: list[dict]) -> dict:
    by_kind: dict[str, dict] = {}
    for kind in sorted({p["kind"] for p in points}):
        # the kind's share in each interval: its processes together
        per_interval: dict[float, float] = {}
        for p in points:
            if p["kind"] == kind:
                per_interval[p["at"]] = per_interval.get(p["at"], 0.0) + p["pct"]
        values = sorted(per_interval.values())
        by_kind[kind] = {"median_pct": round(statistics.median(values), 1),
                         "p95_pct": round(values[min(len(values) - 1, int(len(values) * 0.95))], 1),
                         "most_pct": round(values[-1], 1)}
    counts = [len(s["rows"]) for s in samples]
    return {"minutes": round((samples[-1]["t"] - samples[0]["t"]) / 6e8, 1) if len(samples) > 1 else 0,
            "samples": len(samples), "processes": {"fewest": min(counts), "most": max(counts)} if counts else {},
            "kinds": by_kind}


def trace(browser_dir: Path, minutes: float, interval: int) -> list[dict]:
    import os
    proc = subprocess.Popen(["powershell.exe", "-NoProfile", "-Command", SAMPLE], stdout=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace",
                            env=dict(os.environ, THORON_DIR=str(browser_dir), THORON_INTERVAL=str(interval)))
    samples, end = [], time.monotonic() + minutes * 60
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            sample = json.loads(line)
            rows = sample.get("rows") or []
            sample["rows"] = rows if isinstance(rows, list) else [rows]
            samples.append(sample)
            if time.monotonic() >= end:
                break
    finally:
        proc.kill()
    return samples


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser-dir", required=True, type=Path, help="the folder the browser's programs are in")
    p.add_argument("--minutes", type=float, default=60)
    p.add_argument("--interval", type=int, default=5, help="seconds between samples")
    p.add_argument("--limit", type=float, default=50, help="percent of one core a process may use for long")
    p.add_argument("--sustain", type=float, default=120, help="seconds above --limit that make a runaway")
    p.add_argument("--csv", type=Path)
    a = p.parse_args(argv)
    samples = trace(a.browser_dir.resolve(), a.minutes, a.interval)
    if len(samples) < 2:
        print("CPU TRACE: FAILED (no process of that folder ran)")
        return 1
    points = usage(samples)
    if a.csv:
        with a.csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["at", "pid", "kind", "pct", "seconds"])
            w.writeheader()
            w.writerows({**p_, "at": round(p_["at"], 1), "pct": round(p_["pct"], 2)} for p_ in points)
    result = summary(samples, points)
    result["runaways"] = runaways(points, a.limit, a.sustain)
    print(json.dumps(result, indent=1))
    print(f"CPU TRACE: {'PASSED' if not result['runaways'] else 'FAILED'} ({len(result['runaways'])} runaway(s) "
          f"above {a.limit:g} % of a core for over {a.sustain:g} s)")
    return 1 if result["runaways"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
