# Thoron and Chrome 158 (2026-11-20)

ROADMAP **P5.10** (upstream #803: slow start-up with several profiles) and **Q.1**. Thoron 158.0.8127.6503 (AVX2)
against Chrome for Testing 158.0.8127.36, Google's build of Chrome for automated tests (unpacked, not installed; same
major version and branch as Thoron's Chromium 158.0.8127.65). One Windows 11 x64 PC in use: other programs used about
a fifth of the processor the whole time, so the runs spread as they do; both browsers ran in the same hour.

## Offline measures

`tools/qa/bench.py --profiles`, 7 runs after a warm-up, headless, offline, a fresh profile each run.

| Measure (median) | Thoron 158 | Chrome 158 |
|---|---|---|
| Start-up, until a local page has loaded | 531 ms (spread 18 %) | 750 ms (12 %) |
| Memory with 1 tab | 285 MB (12 %) | 332 MB (7 %) |
| Memory with 20 tabs | 670 MB (3 %) | 735 MB (4 %) |
| Idle CPU | 0.1 % | 0.0 % |
| Start-up with 4 profiles, until the profile picker has loaded | 221 ms (23 %) | 242 ms (30 %) |

## Online suites

`tools/qa/online_bench.py`, 3 runs each, each run in a real window with a throwaway profile (browserbench.org).

| Suite (median, higher is better) | Thoron 158 | Chrome 158 |
|---|---|---|
| JetStream 2.1 | 313.7 (spread 19 %) | 291.8 (10 %) |
| Speedometer 3 | 23.6 (11 %) | 20.0 (17 %) |

Against Chrome 157 (2026-11-17) Thoron's JetStream was lower (299 against 358); against Chrome of its own major version
it is not.

## Four profiles opening their windows at once

The case #803 is about: four profiles that were open at the last exit, the profile picker off, so the start opens
all four windows. A headless browser opens one profile only, so these starts have real windows (minimized). Each
profile is set, on its own Settings page, to open a page at start (Chromium does not open a further profile's window
that would only show a New Tab page). `tools/qa/bench.py --profile-windows`: the time until the four windows' pages
are there. 15 runs after a warm-up, four rounds in the order Thoron, Chrome, Chrome, Thoron, so a change of the PC's
load weighs on both alike.

| | Runs | Median | Fastest | Slowest |
|---|---|---|---|---|
| Thoron 158 | 30 | 605 ms | 519 ms | 754 ms |
| Chrome 158 | 30 | 647 ms | 454 ms | 802 ms |

## Result

Start-up with four profiles is not slower than Chrome of the same major version, with the profile picker (221 ms
against 242 ms) and with the four windows at once (605 ms against 647 ms): P5.10 is done. The differences are within
the runs' spread on this PC, so the measure says "not slower", not "faster". The slow start of #803 does not show.

Two faults in the measuring tool were found and fixed on the way: a cycle of process ids that Windows had reused
stopped a memory run for good (the walk of a browser's processes now takes each process once), and the setting that
turns the profile picker off is `profile.show_picker_on_startup`.

Chrome for Testing needs its folder readable by Chromium's sandbox (`icacls <folder> /grant *S-1-15-2-1:(OI)(CI)(RX)
*S-1-15-2-2:(OI)(CI)(RX) /T`) when it is unpacked outside the user's own folders; without that its network service
cannot start and no page loads.
