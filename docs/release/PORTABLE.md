# Thoron portable for Windows (ROADMAP P2.8)

A portable Thoron is one folder. It is unpacked anywhere, started with its launcher, and keeps its profile
inside itself. Nothing is installed. This page says what the package is, how it is made, what the launcher
does and why it is a `.cmd` for now, what a portable copy still leaves on the PC it runs on, and what is not
there yet.

Everything under "measured" was measured on 2026-11-16 with the Windows x64 build 158.0.8127.3010, by
`tools/qa/portable_check.py` and the tests of `tools/release/portable.py`. What was not measured is said so.

## 1. The package

```
ThoronPortable/
    Thoron.cmd      the launcher
    README.txt      a short note for the person who unpacks it
    Application/    the browser: thoron.exe and the version folder, as the build made them
    User Data/      the profile; not in the package, made at the first start
```

- The release file is `thoron-<version>-<variant>-portable.zip`, named like the installer beside it, for
  example `thoron-158.0.8127.3010-win-x64-avx2-portable.zip`. It holds the one folder `ThoronPortable`.
- `Application` and `User Data` are the names an installed Thoron uses under `%LOCALAPPDATA%\Thoron`. A
  portable folder is that folder, put somewhere else. The update steps of the design
  ([§7.3 and §7.4](../design/2026-11-07-thoron-design.md): a new version folder staged beside the old one,
  the profile never written by the updater) fit it as it is, which is why the browser is not spread out at
  the top of the package.
- The folder can be moved and renamed at any time. Nothing in the launcher or the readme holds a full path.
- To remove a portable Thoron, close it and delete the folder.

## 2. How it is made

```
py -3 -I tools/release/portable.py build --chrome-bin <out>\Chrome-bin --dist <folder> --variant win-x64-avx2
py -3 -I tools/release/portable.py audit --package <folder>\ThoronPortable
```

`build` reads the build's `Chrome-bin` folder (what the installer's `chrome.7z` holds) and never changes it.
It refuses, and writes nothing, when that folder:

- fails `tools/release/package_audit.py` (a Widevine module, a file named after Thorium, an upstream-only
  tool, no `thoron.exe`);
- has `thoron.exe` anywhere but at its top, or not exactly one version folder with `chrome.dll`;
- holds anything that looks like a profile or the leftovers of a browser that was installed and used
  (`User Data`, `Local State`, `Preferences`, `Login Data`, `Cookies`, a crash dump, a log, a pending update);
- holds a link, or two names that differ only in upper and lower case;

and when the output folder already holds a package: a package is never overwritten.

Every file is copied with a check (the SHA-256 of what was read against what was written). The launcher and
the readme are written by the tool, not taken from the build.

**The audit hook.** `portable.py audit` (the function `portable.audit`) is what a release must pass. It
covers `package_audit.py --dir <package>\Application --platform win`, and the package's own rules: only the
launcher, the readme and the browser folder at the top, the launcher byte for byte the one the tool writes,
and no profile. `build` runs it before it makes the `.zip`; the real check runs both audits again.

**The `.zip` is reproducible.** The same files give the same bytes:

- names in one fixed order (sorted), inside the one folder;
- one fixed time for every file, 1980-01-01 00:00:00 by default (`--epoch` sets another), written as it is
  and not taken from the clock or the time zone of the PC that builds;
- no detail of the building PC: the same creator mark, the same attributes, no extra fields, no comment.

Measured: two builds from the same folder gave the same bytes (about 229 MB, 264 files). The bytes depend on
the Python and zlib that compress; with another zlib the compressed bytes may differ while the files inside
are the same. The tool prints the SHA-256 of the `.zip`. Checksums and signatures of a release are the
release script's work (P2.12); it does not call this tool yet.

## 3. The launcher

```bat
@echo off
setlocal EnableExtensions DisableDelayedExpansion
call :locate
if not exist "%THORON_PORTABLE_DIR%Application\thoron.exe" goto missing
if not exist "%THORON_PORTABLE_DIR%User Data\" md "%THORON_PORTABLE_DIR%User Data"
if not exist "%THORON_PORTABLE_DIR%User Data\" goto unwritable
set "THORON_PORTABLE_DIR=" & start "" "%THORON_PORTABLE_DIR%Application\thoron.exe" --user-data-dir="%THORON_PORTABLE_DIR%User Data" --no-default-browser-check %*
exit /b %errorlevel%

:locate
set "THORON_PORTABLE_DIR=%~dp0"
exit /b 0
```

(The comments and the two messages, `:missing` and `:unwritable`, are left out here. The text is
`LAUNCHER_TEXT` in `tools/release/portable.py`.)

What it does:

1. It finds its own folder, when it runs, from where the file is.
2. It starts `Application\thoron.exe` from that folder with `--user-data-dir` set to `User Data` in that
   folder, and passes every argument on as it got it.
3. It adds one switch of its own, `--no-default-browser-check`: a portable copy does not ask to become the
   default browser of a PC it is a guest on, because that writes its path into the registry. The person can
   still choose it in the settings.
4. It makes `User Data` itself before the start, and starts nothing when it cannot. Chromium's start-up
   code uses the PC's own profile folder when it cannot make the folder it was given, so on a
   write-protected drive the browser would quietly work in `%LOCALAPPDATA%\Thoron\User Data`. (This is read
   in Chromium's source. It was not tried with the real browser, because trying it would open the real
   profile of the test PC.)
5. It writes nothing else, does not change the working directory, and leaves the browser's environment as
   it got it.

### Why a `.cmd` for now

- P2.8 asks for a launcher now. P3.12 replaces it with a program that also puts a downloaded update in
  place at the start. That program is built in the Chromium tree, signed with the rest (S.8) and reviewed
  as code that runs before the browser. None of that is needed to start the browser with one switch.
- A `.cmd` is text. Anyone can read what it does, it is the same bytes in every build, and it needs no
  compiler.
- Not chosen: a `.vbs` file (VBScript is being retired from Windows, and script files are often blocked),
  a `.ps1` file (a double click does not run it), a shortcut (it stores a full path).
- The price is a console window that shows for a moment, and the limits in section 3.2.

### 3.1 What a `.cmd` gets wrong, and the proof for each

The tests are in `tools/release/tests/test_portable.py`. `LauncherRunTests` runs the launcher with `cmd.exe`
for real: a small stand-in program takes the browser's place and writes down the command line, the working
directory and the environment it was started with. The real check then does the same with the real browser.

| Pitfall | What goes wrong | What the launcher does | Proved by |
|---|---|---|---|
| Code pages | A file saved in one code page reads wrong in another; a name that passes through a pipe or `for /f` loses its letters | The file is ASCII; the folder's name never leaves `cmd.exe`'s own text | `test_code_pages` (437, 850, 932, 936, 1251, 1252, 65001), `test_the_launcher_keeps_its_own_rules` |
| Names outside ASCII | The same | The same | `test_folder_names` (accented Latin, Cyrillic, CJK, characters beyond 16 bits); the check's "scripts" folder |
| `%` in the folder's name | Read as a variable when a line is read twice | A value is put into a line once; `call` is never given a path or the arguments | `test_folder_names` (percent, percent pair), `test_arguments_pass_as_they_are` |
| `!` in the folder's name | Lost when delayed expansion is on, which a PC can have on by default | Delayed expansion is switched off in the launcher | `test_delayed_expansion_switched_on_for_every_prompt` |
| `&` `^` `(` `)` `;` `,` `=` | Cut the command in two, or close a block | Every path is quoted; there is no block in brackets | `test_folder_names`; the check's "signs" folder |
| Quoting | `start` takes its first quoted word as a window title; a folder alone in quotes ends in `\"`, which escapes the quote | `start ""`; the folder is never alone in quotes | `test_every_rule_catches_its_mistake`, `test_folder_names` (spaces); the check's "spaces" folder and its drive root |
| The console window | `cmd.exe` waits for a program with windows, so the console stays open for the whole session | `start` does not wait: the launcher ends at once (0.1 s measured) | `test_the_launcher_does_not_wait_for_the_browser`; every start of the check |
| The working directory | A launcher that changes it breaks file names given as arguments; one that relies on it puts the profile wherever it was started from | It neither changes nor uses it | `test_the_working_directory_is_left_alone_and_nothing_is_written`; the check starts from another folder |
| A start by the bare name | `%~dp0` is wrong when a quoted bare name is found through the search path | The folder is read inside a called label, where it is right | `test_a_start_by_the_bare_name_through_the_search_path` |
| The environment | A helper variable reaches the browser and every program the browser starts | The variable is cleared on the line that starts the browser | `test_the_environment_is_passed_on_unchanged` |
| The caller | `exit` closes the prompt or the batch file that called; an old error level is passed back | `exit /b`, and its own result | `test_called_from_another_batch_file` |
| Extensions switched off | `%~dp0` and `exit /b` need the command extensions | The launcher switches them on for itself | `test_command_extensions_switched_off` |
| No browser beside it | A start from inside the `.zip` viewer shows a Windows error box | A plain message, and nothing starts | `test_without_the_browser_it_says_so_and_starts_nothing` |
| A profile folder that cannot be made | The browser works in the PC's own profile folder | The folder is made first, or nothing starts | `test_a_profile_folder_that_cannot_be_made_starts_nothing` |
| A moved folder | A stored path points to the old place | Nothing is stored | `test_a_moved_and_renamed_folder`; "moved" in the check |

`launcher_problems` in `portable.py` holds these rules as code. A launcher that breaks one is not packaged.

### 3.2 Known limits

- **A folder named after an environment variable.** A folder whose name holds the name of an existing
  variable between two `%`, such as `%TEMP%`, cannot start any `.cmd`: `cmd.exe` puts the variable's value
  into the path before the launcher runs. A single `%`, or a name that is not a variable, is fine.
  `test_known_limit_a_folder_named_after_an_environment_variable` shows it. Only a program avoids it (P3.12).
- **An argument with `&`, `|`, `<`, `>` or `^` must be quoted**, as for any command typed at a prompt:
  `Thoron.cmd "https://example.com/?a=1&b=2"`.
- **The console window shows for a moment.**
- **A program that reads the launcher's output through a pipe waits until the browser ends**, because the
  browser gets the same pipe. Give the launcher a file, or nothing, to write to.
- **`Application\thoron.exe` started on its own uses the PC's profile**, not the one in the folder. Only
  the launcher sets the profile's place.
- **Full paths longer than about 250 characters** are not tried. `cmd.exe` and Chromium both have Windows'
  260-character limit.
- **A network share.** The launcher finds itself on a `\\server\share` path (tried once by hand with the
  stand-in program, through a share of the test PC itself). The browser on a share is not tried.

## 4. What stays in the folder, and what a portable copy leaves on the PC

### 4.1 Measured

`tools/qa/portable_check.py` built the package, unpacked its `.zip` into three folders (one with spaces, one
named in accented Latin, Cyrillic and CJK, one with `& % ! ^ ( )`), started the browser through the launcher
three times in each (first, again, moved and renamed) and once as the root of a drive letter. Ten starts,
all headless, from a working directory that was not the package's.

| Place | What was found |
|---|---|
| The package's folder | The profile is in `User Data`: the browser names it as its profile, Windows names the program in the folder as the running one, and the DevTools port file, `Local State` and `Default\Preferences` are there. A setting changed in one start is read back in the next, and after the move. Nothing else appears in the folder. |
| `Application` | The same files before and after. The browser does not write into its own folder. |
| Beside the package, and the working directory | Nothing. |
| `%LOCALAPPDATA%\Thoron` and its `User Data` (an installed Thoron's own place) | No new name. Only the names before and after were compared; nothing was opened. |
| The temporary folder | Nothing was left after a normal exit. (For this the browser's temporary folder was pointed at a scratch folder.) |
| The registry, `HKCU\Software\Thoron` | **Written.** During the starts these keys were written: the key itself, `BLBeacon`, `PreferenceMACs\Default`, `PreferenceMACs\Default\extensions.settings`, `StabilityMetrics`, `ThirdParty`. No new key appeared. |

About the registry:

- The browser engine keeps these values per product, not per profile folder, so `--user-data-dir` does not
  move them. No launcher can stop it; it needs a change in the browser.
- What they are, from their names (no value was read): `BLBeacon` is a start-up mark of the browser's
  check of loaded libraries; `PreferenceMACs\<profile folder name>` holds a checksum for each protected
  setting, under the setting's name (such as `homepage` or `pinned_tabs`), not the setting itself;
  `StabilityMetrics` is the mark of a clean exit; `ThirdParty` is the state of the check of other
  programs' libraries.
- The keys were there before the run: an installed Thoron makes the same ones, and the check cannot tell
  its writes from those of an installed Thoron in use at the same time. On a PC that never had Thoron the
  key would be made; that was not measured.
- A portable copy and an installed Thoron on one PC write the same values (both profiles are called
  `Default`). It is a trace, and it is shared. Whether the two can disturb each other was not looked into.

Inside the profile, after the move: two settings still held the old place after one start in the new one,
`extensions.settings.<id>.path` of two built-in extensions in `Secure Preferences`. The browser started and
kept the setting. Whether anything reads those two paths was not checked.

The profile's key for passwords and cookies is kept by the Windows account (DPAPI); see "Not there yet".

### 4.2 Not measured

- **A real USB drive.** A program cannot test one. A drive letter put on the package's own folder with
  `subst` was tested (the launcher and the browser both ran from `<letter>:\`), which proves the path
  handling at a drive root and nothing about a real drive: its file system (FAT, exFAT), its speed, pulling
  it out, or write protection. The launcher's answer to a folder it cannot write is tested with the
  stand-in program only.
- **A start with windows.** Only headless starts were measured. With windows the browser also keeps a
  list for the taskbar's jump list, which Windows stores in the user's own folder, and a person can leave
  more: downloads in the PC's Downloads folder, a web app's shortcut on the desktop (it holds a full path),
  the default browser choice.
- **What Windows itself records** about any program that ran (the list of started programs, the virus
  scanner's history and the like). No launcher changes that.
- **A PC that never had Thoron**, and a second PC or a second Windows account.

## 5. The real check

```
py -3 -I tools/qa/portable_check.py --chrome-bin <out>\Chrome-bin --work <scratch dir> [--drive-root]
```

It needs no network and no real profile, closes only processes whose program file is inside the scratch
folder, and removes everything it made. It ran in full twice on 2026-11-16, with the same result; a run takes
between one and four minutes. The last one:

```
PASS  package: 264 files, Thoron 158.0.8127.3010, a .zip of 229 MB; the portable audit and package_audit.py pass
PASS  spaces/first: the launcher ended after 0.1 s; program and profile in the folder; a new profile, setting 16 -> 17; its key is kept by the Windows account (DPAPI)
PASS  spaces/again: the setting read back: 17
PASS  spaces/moved: the same profile in the new place, setting 17; settings that still name the old place: [2 settings]
PASS  spaces/folder: the package holds ['Application', 'README.txt', 'Thoron.cmd', 'User Data'], nothing beside it or in the working directory
PASS  scripts/first: the launcher ended after 0.1 s; program and profile in the folder; a new profile, setting 16 -> 19; its key is kept by the Windows account (DPAPI)
PASS  scripts/again: the setting read back: 19
PASS  scripts/moved: the same profile in the new place, setting 19; settings that still name the old place: [2 settings]
PASS  scripts/folder: the package holds ['Application', 'README.txt', 'Thoron.cmd', 'User Data'], nothing beside it or in the working directory
PASS  signs/first: the launcher ended after 0.1 s; program and profile in the folder; a new profile, setting 16 -> 21; its key is kept by the Windows account (DPAPI)
PASS  signs/again: the setting read back: 21
PASS  signs/moved: the same profile in the new place, setting 21; settings that still name the old place: [2 settings]
PASS  signs/folder: the package holds ['Application', 'README.txt', 'Thoron.cmd', 'User Data'], nothing beside it or in the working directory
PASS  root: started as <letter>:\Thoron.cmd, the launcher ended after 0.1 s; profile at <letter>:\User Data, setting 16 -> 23; the letter is removed again
PASS  host: 2 folders of the PC's own Thoron hold <N> names, none new; registry key Software\Thoron: new keys: none; written during the runs: [the six keys of section 4.1]; left in the temporary folder: nothing
PORTABLE CHECK: PASSED
```

(Shortened here: the two settings and the six keys, which section 4.1 names, and the count of names.)

## 6. Not there yet

| What | Until then | Stage |
|---|---|---|
| Updates | A portable copy does not update itself. By hand: get the new package, close Thoron, replace `Application`, keep `User Data` | P3.6, P3.12 |
| A launcher that is a program | No console window, no limit on `%NAME%` folders, the update put in place at the start | P3.12 |
| A profile that opens on any PC | Saved passwords and sign-ins are locked to the Windows account they were saved with (measured: the profile's key is kept by DPAPI). On another PC or account they cannot be read and may be lost (known from how Chromium protects them; not measured). The browser's flag that stores them unprotected is deliberately not used | P4.9 |
| Taking over an upstream Thorium portable folder | Not offered | P4.10 |
| A warning when the copy is moved to a PC whose processor cannot run its variant | Nothing checks the processor before the start | P4.4 |
| A portable copy that leaves no registry values | See section 4.1; it needs a change in the browser | no stage yet; upstream's report "Portable is not fully portable" (#592) is kept under P3.12 and P4.9 |
| The browser started without the launcher from a portable folder | It uses the PC's profile | no stage yet; it belongs with the program launcher |
| The first run's offers (import, default browser, P3.21) in a portable copy | The launcher only keeps the default browser question away | P3.21 |
| The release script making and signing the `.zip` | `portable.py` is run by hand | P2.12 |
| Signed program files | Windows may warn about an unknown publisher | S.8 |
| A test on a real USB drive, by a person | Section 4.2 | P2.8 |
| The installer half of P2.8 | Not part of this work | P2.8 |
| Linux portable `.tar.xz` | Not part of this work | P2.9 |
