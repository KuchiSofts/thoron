# Start-up with 4 profiles (2026-11-16)

ROADMAP **P5.10** (upstream #803: slow start-up with several profiles) and **Q.1**. A folder of profiles with four
profiles, each made by a start of its own and all open at the last exit. A start with several profiles shows the
profile picker first, so the time is from the start of the program until the picker has loaded (DevTools lists
it). Headless, offline, on one Windows 11 x64 PC in use; 12 runs each, the first dropped, timed with the fine
clock (`time.perf_counter`).

| Browser | Median | Spread |
|---|---|---|
| Thoron 158.0.8127.3010 | 242 ms | 22 % |
| Thorium 156.0.8078.28 | 243 ms | 31 % |
| Chrome 157.0.8103.78 | 237 ms | 10 % |

The three are within each other's spread: the slow start of #803 does not show here. Chrome 157 is one major
version behind Thoron's 158; P5.10 asks for the same version, so it is measured again then.

Not measured: a start that opens the four profiles' windows at once. A headless browser opens only the profile
that was used last, so that case needs a visible window. `tools/qa/bench.py --profiles` takes this measure
(`startup_4_profiles_ms`).
