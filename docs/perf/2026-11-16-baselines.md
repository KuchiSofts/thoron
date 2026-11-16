# Performance baselines (2026-11-16)

ROADMAP **Q.2**. Measured with [`tools/qa/bench.py`](../../tools/qa/bench.py) on one Windows 11 x64 PC, one browser
after the other, 5 runs each after 1 warm-up run that is dropped, every run on a throwaway profile, headless,
against a local page (127.0.0.1); nothing was loaded from the network. Lower is better for every measure.

| Measure | Thoron 158.0.8127.3010 | Thorium 156.0.8078.28 | Chrome 157.0.8103.78 |
|---|---|---|---|
| Start-up (ms) | 484.0 (spread 16.1 %) | 719.0 (spread 15.3 %) | 516.0 (spread 9.1 %) |
| Memory, 1 tab (MB) | 313.2 (spread 2.6 %) | 389.9 (spread 18.9 %) | 366.8 (spread 2.5 %) |
| Memory, 20 tabs (MB) | 678.3 (spread 1.8 %) | 794.1 (spread 3.1 %) | 724.2 (spread 1.7 %) |
| Idle CPU (%) | 0.1 (spread 43.9 %) | 0.6 (spread 24.1 %) | 0.0 (spread 283.3 %) |

The median of the runs, and in brackets their spread ((max - min) / median). Within 3 % counts as repeatable;
repeatable here: Thoron 158.0.8127.3010: memory_1_tab_mb, memory_20_tabs_mb; Thorium 156.0.8078.28: none; Chrome 157.0.8103.78: memory_1_tab_mb, memory_20_tabs_mb.

What to keep in mind:

- **Not an idle PC.** The PC was in use while it ran (other programs and browsers open), so the spreads are
  wider than ROADMAP **Q.1** asks for. The release gate (`tools/qa/perf_gate.py`, ROADMAP **Q.3**) does not
  call a rise a regression unless it is larger than twice the spread of the two runs it compares.
- **Chrome 157, not 158.** Q.2 asks for Chrome of the same major version; the Chrome on this PC was 157. The
  comparison with Chrome is therefore one version apart.
- **Headless.** The start-up time is the time until the local page answers, without a window; memory is the
  private memory of the browser's own processes; idle CPU is measured with one page open after it settled.
- **What each browser does at start differs:** Thoron loads its ad blocker's lists, Thorium 156 its bundled
  uBlock Origin, Chrome neither.

The results are in `2026-11-16-baseline-thoron.json`, `2026-11-16-baseline-thorium.json` and `2026-11-16-baseline-chrome.json`.
`baseline.json` is Thoron's, the one the release gate compares a release with; it is replaced only on purpose,
with this page updated.
