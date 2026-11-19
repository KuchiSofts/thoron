#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The performance gate of a release (ROADMAP Q.3): a regression blocks the release until it is explained.

A release's benchmark (`tools/qa/bench.py --out`) is compared with the baseline in `docs/perf/baseline.json`, a
result of the same tool. Every measure is lower-is-better (start-up time, memory, idle CPU). A measure has
regressed when its median rose by more than its limit, both as a share and as an amount, and by more than twice
the larger spread of the two runs, so that noise is not called a regression:

    startup_ms          10 % and 30 ms
    memory_1_tab_mb     10 % and 20 MB
    memory_20_tabs_mb   10 % and 50 MB
    idle_cpu_pct        50 % and 0.5 points

A regression is explained by a line of `docs/perf/EXPLAINED.md` that names the Thoron version and the measure:

    - 0.1.2 memory_20_tabs_mb: the new tab strip keeps its previews; 30 MB more, accepted.

    py -3 -I tools/qa/perf_gate.py --baseline docs/perf/baseline.json --results <bench.json> --version 0.1.2
        [--explained docs/perf/EXPLAINED.md]
Exit status 0 when nothing regressed or every regression is explained.
"""
import argparse
import json
import re
import sys
from pathlib import Path

# measure -> (share in percent, smallest amount)
LIMITS = {"startup_ms": (10.0, 30.0), "memory_1_tab_mb": (10.0, 20.0), "memory_20_tabs_mb": (10.0, 50.0),
          "idle_cpu_pct": (50.0, 0.5)}
EXPLAINED = "docs/perf/EXPLAINED.md"
LINE = re.compile(r"^- (\d+\.\d+\.\d+) ([a-z0-9_]+): (\S.*)$")


def regressions(baseline: dict, results: dict) -> list[dict]:
    """The measures that regressed: name, the two medians and the rise. A measure missing from the results of a
    release is a problem too: what is not measured cannot be shown not to have regressed."""
    out = []
    for name, (share, amount) in LIMITS.items():
        base, now = baseline.get(name), results.get(name)
        if not isinstance(base, dict) or "median" not in base:
            continue
        if not isinstance(now, dict) or "median" not in now:
            out.append({"measure": name, "missing": True})
            continue
        before, after = float(base["median"]), float(now["median"])
        rise = after - before
        noise = 2 * max(float(base.get("spread_pct", 0)), float(now.get("spread_pct", 0))) / 100 * before
        if before > 0 and rise > amount and rise / before * 100 > share and rise > noise:
            out.append({"measure": name, "before": before, "after": after,
                        "rise_pct": round(rise / before * 100, 1)})
    return out


def explanations(markdown: str) -> set[tuple[str, str]]:
    """(version, measure) of every explanation line."""
    found = set()
    for line in markdown.splitlines():
        m = LINE.match(line.strip())
        if m and len(m.group(3).strip()) >= 10:
            found.add((m.group(1), m.group(2)))
    return found


def problems(baseline: dict, results: dict, version: str, explained_md: str) -> list[str]:
    known = explanations(explained_md)
    out = []
    for r in regressions(baseline, results):
        if r.get("missing"):
            out.append(f"{r['measure']} was not measured for this release")
        elif (version, r["measure"]) not in known:
            out.append(f"{r['measure']} rose {r['rise_pct']} % ({r['before']} to {r['after']}) and is not explained "
                       f"in {EXPLAINED} for {version}")
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--version", required=True, help="the Thoron version of the release, such as 0.1.2")
    p.add_argument("--explained", type=Path, default=Path(EXPLAINED))
    a = p.parse_args(argv)
    try:
        baseline = json.loads(a.baseline.read_text(encoding="utf-8"))
        results = json.loads(a.results.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"perf_gate: {exc}", file=sys.stderr)
        return 1
    explained = a.explained.read_text(encoding="utf-8") if a.explained.is_file() else ""
    found = problems(baseline, results, a.version, explained)
    for problem in found:
        print(f"perf_gate: {problem}")
    print(f"perf gate: {len(regressions(baseline, results))} regression(s), {len(found)} unexplained")
    return 0 if not found else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
