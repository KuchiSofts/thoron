# Thoron's installer for Windows (ROADMAP P2.8)

Thoron's installer is Chromium's `mini_installer` with Thoron's name, icons and a small dialog. It installs
for the person who runs it, in `%LOCALAPPDATA%\Thoron\Application`, with no administrator rights. This page
says how it is checked on a clean Windows, what the check found, and what is still open. The portable
package has its own page, [PORTABLE.md](PORTABLE.md).

## 1. What the installer does

- Run by a person, it asks first (Install or Cancel; Cancel is the default button), installs, and shows the
  result with an OK button. Run with `--silent`, it asks nothing and shows nothing.
- It unpacks into a new folder next to itself and removes that folder at the end. The folder it is run from
  must be one it may write to: from a read-only folder (a read-only share or drive) it stops with code 109
  and a message to download Thoron again. Downloading it again does not help there; running it from
  Downloads does.
- The program goes to `Application\thoron.exe` and `Application\<version>\`, and the uninstaller to
  `Application\<version>\Installer\setup.exe`. Thoron is listed among the installed programs as "Thoron"
  with Thoron's own version.
- `--thoron-chrome-bin=<folder>` (Thoron's, for its updater): setup installs from a folder with the
  layout of the archive's `Chrome-bin` instead of an archive. Chromium 158's setup has no differential
  installer left, so an installed copy's delta is made into such a folder by the updater, and the newer
  version's own `setup.exe`, which the delta also makes, installs it (ROADMAP P4.1).
- Uninstalling removes the program and its entry and **keeps the profile** (`User Data`) unless the person
  ticks the box that deletes it (`--delete-profile`).
- For one user (ROADMAP P3.10), every install and update registers the daily update task in Task
  Scheduler, through Task Scheduler's own interface (`chrome/installer/setup/thoron_update_task.cc`):
  `ThoronUpdateTaskUser<the user's SID>` runs `Application\<version>\ThoronSetup.exe --scheduled
  --variant=<this build>` with the user's own rights (an interactive token, so no password is stored;
  the least privilege), once a day at 12:00 plus up to an hour at random, as soon as the PC is on again
  when it was off then, only with a network, for at most an hour. A task the person switched off stays
  off when it is registered again. The uninstall removes it. An install for every user registers none.
  `ThoronSetup.exe` is in each version folder for this (`chrome.release`).
- Installed over a running Thoron, it does one of two things. For one user (the default) it leaves Thoron
  running: the new program waits as `new_thoron.exe` beside `thoron.exe` and replaces it when Thoron is
  closed or next started (Chromium's in-use update). For every user of the PC it closes the running Thoron
  and updates in place: such an install has no Google Update to finish the swap later (Thorium's installer
  patch). Thoron first asks the running browser to end its session, the way Windows asks it when the
  person signs out, so it saves the tabs of every window and its data and exits by itself; only what still
  runs 15 seconds later is ended. Thoron then starts on the new version with its tabs and profile.

## 2. The check: `tools/qa/sandbox_install_check.py`

The check never installs anything on the PC it runs on. It starts Windows Sandbox, a clean Windows that is
new at every start and gone when it closes, with networking off, the clipboard and printers not shared, the
installer in a folder the Sandbox may only read, and an empty folder it writes its findings to. A script
inside it:

| Step | What it does | It passes when |
|---|---|---|
| install | copies the installer to the Sandbox's own disk, runs it with `--silent --do-not-launch-chrome` | exit 0 (or another success code), `thoron.exe` there, one version folder, the entry among the installed programs |
| start | starts Thoron with its window, waits 25 s, closes the window the way a person does | Thoron runs, has a window, ends by itself within 30 s of the close, and has made `User Data\Local State` |
| task | reads the update task (`schtasks /Query /XML`), starts it (`/Run`), runs its program directly, then switches it off with another program in it (Task Scheduler's PowerShell commands) and installs again | for one user: the task runs the installed version's `ThoronSetup.exe --scheduled --variant=win-...` with an interactive token and the least privilege, `StartWhenAvailable` on; started without a network (the Sandbox has none) its run waits in the queue; ThoronSetup run directly ends with 4 (it got as far as the network); after installing again it is Thoron's task again and still off. For every user: no task |
| uninstall | puts a file into the profile, runs `setup.exe --uninstall --force-uninstall` | exit 19 (uninstalled), `thoron.exe` and the entry gone, the profile and the file in it kept; for one user the task is gone |

Then the Sandbox shuts itself down; the check closes it if it is still there a minute after the results.

```
py -3 -I tools/qa/sandbox_install_check.py --installer <out>\thoron_AVX2_mini_installer.exe --work <scratch folder>
    [--update <newer build>\thoron_AVX2_mini_installer.exe] [--system-level]
```

`--update` adds a step before the uninstall: Thoron is started again, and while it runs the newer build is
installed over it (Chromium's in-use update, exit 30, `new_thoron.exe` left beside `thoron.exe`); after the
window is closed and Thoron started again, it must run from the newer version folder, with
`new_thoron.exe` gone and the profile kept. `--system-level` runs every step for all users of the PC.

Windows Sandbox must be turned on (Windows 11 Pro or Enterprise, "Windows Sandbox" in Windows features). It
opens a window for a few minutes; nothing in it needs a click.

## 3. Measured

On 2026-11-17, with the Windows x64 AVX2 build 158.0.8127.3010 (the installer is 144 MB):

| Step | Result |
|---|---|
| install | exit 0; version folder `158.0.8127.3010`; listed as "Thoron", version 0.1.1 |
| start | window shown; closed by itself after the window was closed; `Local State` made |
| uninstall | exit 19; program and entry gone; `User Data` and the file put into it kept |

The same build installed for every user of the PC (`--system-level`: the program in Program Files, the
entry in the PC's list of programs) passed the same three steps; the profile stays each user's own.

The update from 158.0.8127.3010 to 158.0.8127.6500 (the drill build of the
[security runbook](../security/SECURITY_RELEASES.md#8-drills-and-real-runs)) while 3010 ran:

| Install | What happened | Result |
|---|---|---|
| For one user | exit 0, status 30 (updated while in use); `new_thoron.exe` waited while 3010 ran; on close it was swapped in; the next start ran 6500; the 3010 folder was removed; the profile kept | pass |
| For every user | exit 0, status 2; the installer closed the running 3010 and updated in place; the next start ran 6500; the profile kept. With Thorium's installer alone the browser was ended from outside (it recorded its exit as "Crashed"); with Thoron's change it was asked to end its session first (3 windows of 9 processes; it saved and exited within a tenth of a second, recording "SessionEnded") | pass |

An installed copy updated from a delta (`--installed-delta`, P4.1): the installed 158.0.8127.3010 and the
delta to .6500 (31.2 MB) made by `tools/release/delta.py`; `thoron_update.exe --apply-installed-delta` made
the new files and the new setup installed them in 18 s (exit 0); Thoron then started on .6500 with the
profile kept, nothing was left in `Update`, and the new setup uninstalled it (exit 19). Pass.

The daily update task (P3.10), on 2026-11-18 with the build 158.0.8127.6500 that has it: for one user the
install registered `ThoronUpdateTaskUser<SID>` running the installed version's `ThoronSetup.exe --scheduled
--variant=win-x64-avx2` with an interactive token and the least privilege (Task Scheduler leaves the
default `RunLevel` out of its export) and `StartWhenAvailable` on. Started, its run stayed in the queue: the
task runs only with a network and the Sandbox has none. ThoronSetup run directly the same way ended with 4
(it found no network). Switched off by hand with another program in it and installed again, it was
Thoron's task again and still off. The uninstall removed it. Installed for every user: no task. Pass.

Found on the way:

- A task's on-demand run with "only with a network" waits in the queue without one, and Task Scheduler
  then shows its last result as 0; the check reads the state (`Queued`) and runs ThoronSetup directly
  for its exit code.
- The installer run straight from the read-only shared folder stopped with code 109 (section 1). The check
  copies it to the Sandbox's disk first.
- Chromium writes the entry of a system-wide install in the 32-bit view of the registry
  (`HKLM\SOFTWARE\WOW6432Node\...\Uninstall`); the check looks in both views.
- Setup exits with 0 for every successful install, an update while Thoron runs included
  (`InstallUtil::GetInstallReturnCode`); the status itself (30 for an in-use update) is kept in the
  registry as `InstallerError`, where the check reads it.
- After the update of an install for every user, PowerShell's own registry reader hung on
  `HKLM\Software\Thoron` inside the Sandbox; the check reads the registry with `reg.exe` and a time
  limit instead, and saves its findings before each step so a hang says where it is.

## 4. Open

- The message for code 109 could say what to do (run it from Downloads). It is Chromium's message.
