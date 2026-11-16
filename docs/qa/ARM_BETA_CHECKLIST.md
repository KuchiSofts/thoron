# ARM beta checklist (ROADMAP P2b.4)

What a community tester runs on a Windows-on-ARM PC or an ARM64 Linux device, and what to report.
Thoron's ARM64 builds are cross-compiled on an x64 machine and only run under emulation before they are
published (ROADMAP **P2b.1** to **P2b.3**), so they carry the label "beta" until reports from real
devices are in.

Status: written 2026-11-16. There is no ARM64 build to test yet; this is ready for the first one.

Report with the **ARM64 beta report** form:
https://github.com/KuchiSofts/thoron/issues/new?template=arm-beta-report.yml
(its source is [`arm-beta-report.yml`](../../.github/ISSUE_TEMPLATE/arm-beta-report.yml)).

## Before you start

- **Use the new profile Thoron creates.** Do not import your own browser data for this test and do not
  sign in to accounts that matter to you. The required steps take about 45 minutes.
- **Never start Thoron with `--no-sandbox`.** If it only starts that way, that is the finding: report
  it and stop.
- **A security problem is not reported here.** Use private reporting
  ([`SECURITY.md`](../../SECURITY.md)).

## What a report must not contain

- Your name, account names, e-mail addresses, the PC's name or serial number, your IP address or where
  you are.
- A file from a profile, a crash dump (`.dmp`) or a log. A dump is a piece of memory and can hold
  passwords ([crash triage](CRASH_TRIAGE.md), section 6).
- A screenshot that shows your tabs, bookmarks or accounts. On a new profile there are none.
- Your user name inside a pasted path: replace it with `<name>`.

The device is described by its class only, for example "Snapdragon X laptop, 16 GB" or "Raspberry Pi
5, 8 GB".

## Required steps, both platforms

| Step | Do | Passes when |
|---|---|---|
| A1 | Check the download: both steps of [README, "Verifying downloads"](../../README.md#verifying-downloads) | The signature of `SHA256SUMS` and the file's checksum both verify |
| A2 | Install or unpack, and start Thoron | A window opens |
| A3 | Check that it is the ARM64 build running natively. Windows: Task Manager, Details, add the column "Architecture". Linux: `uname -m`, and `file <install folder>/thoron` | Windows: every `thoron.exe` says ARM64. Linux: `aarch64` both times |
| A4 | Open `chrome://version` | Note the Thoron version and the Chromium version |
| A5 | Open `chrome://sandbox` | Linux: the page ends with "You are adequately sandboxed." Windows: copy the page's text into the report; the renderer rows must show a sandbox |
| B1 | Open the file `tools/build/smoke_page.html` from a copy of this repository in Thoron. It runs on the PC only and contacts nothing | `js`, `webgl`, `h264`, `hevc` and `av1` are `true`. `jxl` is `false` when the page is opened by hand; that is expected. Paste the line; it names the OS and the Chromium version, nothing else |
| B2 | Open `chrome://gpu` and copy only the first list, "Graphics Feature Status" | Paste it; hardware acceleration is not all "disabled" or "software only" |
| B3 | Play a video for 5 minutes, in a window and full screen, with sound | No stutter, no wrong colours, no crash |
| B4 | Open a news page that carries ads; click the Thoron adblock shield; open `chrome://adblock` | The shield counts blocked requests, the menu and the page open |
| B5 | In `chrome://password-manager`, add a made-up entry (site `example.com`, user `test`, any password); close Thoron completely; start it; look at the entry | The entry is there and its password can be shown (Windows may first ask you to confirm it is you) |
| B6 | Install one extension from the Chrome Web Store and use it | It installs and works |
| B7 | Download a file, open a PDF, and print a page to PDF | All three work |
| C1 | Browse for 30 minutes with 10 or more tabs | No crash, no "this page crashed" tab |
| C2 | Put the device to sleep with Thoron open, and wake it | The windows redraw and the pages still work |
| C3 | Leave one empty tab open for 5 minutes and look at Thoron's CPU use in Task Manager or `top` | Close to zero |
| C4 | Count the files in the crash folder ([crash triage](CRASH_TRIAGE.md), section 2) | Report the number. Never attach the files |

## Windows on ARM only

| Step | Do | Passes when |
|---|---|---|
| W1 | Watch the installer | It asks for no administrator rights and installs into `%LOCALAPPDATA%\Thoron` |
| W2 | Look in Windows' list of installed apps | Thoron is listed with its version |
| W3 | Play video for 15 minutes on battery | The device stays usable and does not get unusually hot |
| W4 | At the very end, if you want to: uninstall, leaving "Also delete browsing data" unticked | The program is gone and the profile folder is still there |

## ARM64 Linux only

| Step | Do | Passes when |
|---|---|---|
| L1 | Install the `.deb` with `sudo apt install ./<file>.deb`, or unpack the portable `.tar.xz` | No error; the `.deb` adds Thoron to the applications menu |
| L2 | Note the distribution and version, and `echo $XDG_SESSION_TYPE` | Report them (Wayland or X11) |
| L3 | Run `getconf PAGESIZE` | Report the number. ARM64 kernels differ here (4096, 16384, 65536) and the emulated tests run with one |
| L4 | Repeat A5 after a restart of the device | Still "You are adequately sandboxed.", without any extra switch |

Ubuntu 24.04 and 26.04 are the supported systems. A report from another distribution is welcome and is
counted as best effort.

## Optional

- **Protected video (DRM).** Open a site with protected video. Report "plays" or "does not play". A "no"
  is information, not a failure: Thoron does not bundle Google's Widevine module (ROADMAP **P2.6**),
  and whether it is offered for the device is part of what the beta finds out.
- **The smoke test,** with Python 3 and a copy of this repository. It starts Thoron on a throwaway
  profile and proves the sandbox from the processes themselves. It has not run on ARM64 hardware yet,
  so a failure of the tool itself is worth reporting too. Without a JPEG XL sample, given as
  `--jxl-sample <any small .jxl file>`, it reports `jxl` as failed; that is expected. Paste what it
  prints.

  ```powershell
  py -3 -I tools\build\smoke.py --browser "$env:LOCALAPPDATA\Thoron\Application\thoron.exe" --work <empty folder>
  ```

  ```bash
  python3 -I tools/build/smoke.py --browser <install folder>/thoron --work <empty folder>
  ```

- **Benchmarks.** Speedometer 3, JetStream 2 and MotionMark: on mains power, other programs closed,
  three runs each, report the middle value. The same on another browser of the device makes the
  numbers comparable. `tools/qa/bench.py` measures start-up time, memory and idle CPU offline.

## What counts

ROADMAP **P2b.4** is done when 3 independent reports per platform are in.

- **Platforms:** Windows on ARM, and ARM64 Linux.
- **Independent:** from different people on different devices.
- **Complete:** every required step, and the steps of the platform, answered with pass, fail or not
  run. A report with failures counts: finding them is the point.
- **One report per device and Thoron version.**

| Platform | Complete reports | Issues |
|---|---|---|
| Windows on ARM | 0 of 3 | - |
| ARM64 Linux | 0 of 3 | - |

A failure becomes a bug with the label `arm64`; a crash goes through [crash triage](CRASH_TRIAGE.md).
The label "beta" comes off only after the validation on real devices of ROADMAP **P2b.5**.

## For maintainers

1. Read a new report for personal data first, and remove any before answering.
2. Keep the label `arm64`; open a bug for every failure and link it.
3. Add a complete report to the table above, by its issue number.
