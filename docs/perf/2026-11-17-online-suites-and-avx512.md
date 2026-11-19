# Online suites, and the AVX-512 build against AVX2 (2026-11-17)

ROADMAP **Q.1** (the online suites) and **P5.11** (an AVX-512 variant). `tools/qa/online_bench.py`:
Speedometer 3.0, JetStream 2.1 and MotionMark 1.3.1 from browserbench.org, 3 runs each, each run in a real
window with a throwaway profile, extensions off, a covered window kept rendering. `tools/qa/bench.py --profiles`
for the offline measures (5 runs after a warm-up). One Windows 11 x64 PC with AVX-512; **not idle**: other
programs on it used about 8 % of the processor the whole time, which is why the runs spread as they do.

| Build | Speedometer 3 | JetStream 2.1 | MotionMark 1.3.1 |
|---|---|---|---|
| Thoron 158 AVX2 | 28.6 (spread 20 %) | 298.7 (2 runs, 2 %) | 2790 (36 %) |
| Thoron 158 AVX-512 | 25.4 (28 %) | 293.1 (27 %) | 2796 (23 %) |
| Thorium 156 | 19.9 (17 %) | 326.4 (26 %) | 3069 (23 %) |
| Chrome 157 | 28.6 (17 %) | 357.9 (3 %) | 2870 (17 %) |

Medians; higher is better. One JetStream run of the AVX2 build gave no score in 20 minutes and is not counted.

| Offline (median) | Start-up | Memory, 1 tab | Memory, 20 tabs | Idle CPU | Start-up, 4 profiles |
|---|---|---|---|---|---|
| Thoron 158 AVX2 | 468 ms (14 %) | 311 MB | 677 MB | 0.1 % | 255 ms (14 %) |
| Thoron 158 AVX-512 | 500 ms (47 %) | 306 MB | 681 MB | 0.1 % | 235 ms (34 %) |

## The AVX-512 decision (P5.11)

No AVX-512 package for now. On this PC the AVX-512 build is not measurably faster than the AVX2 build in any
measure (every difference is well inside the runs' spread), and upstream's AVX-512 builds have a stability report
of their own (#1278, ROADMAP P5.5) that an extra variant would bring along, with one more build, package and test
run per release. The groundwork stays: the launcher and the update manifest know `win-x64-avx512`, so a package
can follow when a quiet, repeatable measurement shows a gain worth it.

## What else it shows

- JetStream 2.1 is lower in Thoron 158 than in Chrome 157 (about 299 against 358; Chrome's three runs within 3 %).
  It is not the built-in blocker: with it off the median was 316 (runs 425, 316, 297). To be measured again on a
  quiet PC and against Chrome 158 (same Chromium version) before it is called a regression.
- Speedometer 3: Thoron 158 matches Chrome 157 (28.6) and is above Thorium 156 (19.9).
- None of the suites is repeatable within the ±3 % Q.1 asks for on this PC; that needs a PC that does nothing else.
