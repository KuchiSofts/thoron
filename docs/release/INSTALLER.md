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

Found on the way:

- The installer run straight from the read-only shared folder stopped with code 109 (section 1). The check
  copies it to the Sandbox's disk first.
- Chromium writes the entry of a system-wide install in the 32-bit view of the registry
  (`HKLM\SOFTWARE\WOW6432Node\...\Uninstall`); the check looks in both views.

## 4. Open

- An update over an older installed version while it runs (`--update`): written, waiting for a second build
  to install over the first.
- A system-wide copy updated while it runs: Chromium hands the swap of `new_thoron.exe` to Google Update,
  which Thoron does not have, so the swap may never happen. To be checked with `--update --system-level`.
- The message for code 109 could say what to do (run it from Downloads). It is Chromium's message.
