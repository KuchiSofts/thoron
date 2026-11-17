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
- Uninstalling removes the program and its entry and **keeps the profile** (`User Data`) unless the person
  ticks the box that deletes it (`--delete-profile`).
- Installed over a running Thoron, it does one of two things. For one user (the default) it leaves Thoron
  running: the new program waits as `new_thoron.exe` beside `thoron.exe` and replaces it when Thoron is
  closed or next started (Chromium's in-use update). For every user of the PC it **ends the running Thoron
  at once** and updates in place. Thorium's installer patch does this because such an install has no
  Google Update to finish the swap later; Thoron then starts on the new version with the profile kept, but
  it is closed without the usual shutdown.

## 2. The check: `tools/qa/sandbox_install_check.py`

The check never installs anything on the PC it runs on. It starts Windows Sandbox, a clean Windows that is
new at every start and gone when it closes, with networking off, the clipboard and printers not shared, the
installer in a folder the Sandbox may only read, and an empty folder it writes its findings to. A script
inside it:

| Step | What it does | It passes when |
|---|---|---|
| install | copies the installer to the Sandbox's own disk, runs it with `--silent --do-not-launch-chrome` | exit 0 (or another success code), `thoron.exe` there, one version folder, the entry among the installed programs |
| start | starts Thoron with its window, waits 25 s, closes the window the way a person does | Thoron runs, has a window, ends by itself within 30 s of the close, and has made `User Data\Local State` |
| uninstall | puts a file into the profile, runs `setup.exe --uninstall --force-uninstall` | exit 19 (uninstalled), `thoron.exe` and the entry gone, the profile and the file in it kept |

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
| For every user | exit 0, status 2; the installer ended the running 3010 (six processes before, none after) and updated in place; the next start ran 6500; the profile kept | pass, as designed (section 1) |

Found on the way:

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

- For every user of the PC, an update ends a running Thoron without its normal shutdown. Asking it to close
  first (and waiting a little) would let it save its session the usual way. Not done yet; ROADMAP P3.6.
- The message for code 109 could say what to do (run it from Downloads). It is Chromium's message.
