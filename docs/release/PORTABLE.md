# Thoron portable for Windows (ROADMAP P2.8, P3.12)

A portable Thoron is one folder. It is unpacked anywhere, started with its launcher `Thoron.exe`, and keeps its
profile inside itself. Nothing is installed. This page says what the package is, how it is made, what the
launcher does, what the `.cmd` launcher before it could not do, what a portable copy still leaves on the PC it
runs on, and what is not there yet.

Everything under "measured" was measured on 2026-11-16 with the Windows x64 build 158.0.8127.3010 and the
launcher and updater built from the same source, by `tools/qa/portable_check.py`,
`tools/qa/portable_launcher_check.py` and the tests of `tools/release/portable.py`. What was not measured is
said so.

## 1. The package

```
ThoronPortable/
    Thoron.exe          the launcher
    README.txt          a short note for the person who unpacks it
    variant             win-x64-avx2 or win-x64-sse4: the processors the build is made for
    Application/
        current         the version that starts
        <version>/      the browser as the build made it (thoron.exe and its own version folder),
                        and the updater thoron_update.exe beside thoron.exe
    User Data/          the profile; not in the package, made by the launcher at the first start
```

- The release file is `thoron-<version>-<variant>-portable.zip`, named like the installer beside it, for
  example `thoron-158.0.8127.3010-win-x64-avx2-portable.zip`. It holds the one folder `ThoronPortable`.
- This is the layout of Thoron's own updater (`components/thoron_update/swap.h`, P3.5): every version in a
  folder of its own and the small file `current` naming the one that starts. An update is a new version
  folder put beside the old one and `current` replaced in one step; the version before is kept for a
  rollback; nothing is ever written into `User Data`.
- The updater lives in the version folder, so it changes with each version, and a running updater is never
  in a folder that is being removed.
- `Application` and `User Data` are the names an installed Thoron uses under `%LOCALAPPDATA%\Thoron`.
- `variant` and `current` are one line of ASCII each, ended by a line feed, as the launcher reads them.
- The folder can be moved and renamed at any time. Nothing in the package holds a full path.
- To remove a portable Thoron, close it and delete the folder.

## 2. How it is made

```
py -3 -I tools/release/portable.py build --chrome-bin <out>\Chrome-bin --launcher <out>\thoron_launcher.exe
    --updater <out>\thoron_update.exe --dist <folder> --variant win-x64-avx2
py -3 -I tools/release/portable.py audit --package <folder>\ThoronPortable
py -3 -I tools/release/portable.py audit --package <folder>\thoron-<version>-<variant>-portable.zip
```

`build` reads the build's `Chrome-bin` folder (what the installer's `chrome.7z` holds), the launcher and the
updater the build wrote into its out dir, and never changes them. It refuses, and writes nothing, when:

- the browser folder fails `tools/release/package_audit.py` (a Widevine module, a file named after Thorium,
  an upstream-only tool, no `thoron.exe`);
- it has `thoron.exe` anywhere but at its top, or not exactly one version folder with `chrome.dll`;
- it holds anything that looks like a profile or the leftovers of a browser that was installed and used
  (`User Data`, `Local State`, `Preferences`, `Login Data`, `Cookies`, a crash dump, a log, a pending update);
- it holds a link, two names that differ only in upper and lower case, or already an updater;
- the launcher or the updater is not a Windows program for x64 (an `MZ` and a `PE` header, machine `0x8664`,
  a program and not a library), or the launcher is not a window program (subsystem 2, so no console opens);
- the variant is not `win-x64-avx2` or `win-x64-sse4`, the two the launcher knows;
- the output folder already holds the package or its `.zip`: a package is never overwritten.

Every file is copied with a check (the SHA-256 of what was read against what was written). `Thoron.exe` is the
bytes of `thoron_launcher.exe`. The readme, `variant` and `current` are written by the tool.

`tools/release/release.py prepare` makes the package with the launcher and updater of its out dir
(`--launcher` and `--updater` name others, for example signed copies), and refuses before packaging anything
when they, the browser folder or the variant would be refused here, or when the variant is not the one the
build record names: the package's `variant` file tells the launcher which processors the build runs on.

**The audit hook.** `portable.py audit` (the function `portable.audit`) is what a release must pass. It takes
the folder or its `.zip`. It covers `package_audit.py --dir <package>\Application\<version> --platform win`,
and the package's own rules:

- only `Thoron.exe`, `README.txt`, `variant` and `Application` at the top, and no profile;
- `Thoron.exe` a window program for x64, `thoron_update.exe` beside `thoron.exe` a program for x64;
- `variant` one of the two, as the launcher reads it;
- `Application` holding `current` and exactly one version folder, and `current` naming exactly that one;
- the version folder holding the browser of that version;
- for the `.zip`: one folder and files only (no folder entries, nothing outside, no name twice), every
  checksum right, and its name saying the same variant and version as the files inside.

`build` audits the folder before it makes the `.zip`, and the `.zip` after; the real check audits both again.

**The `.zip` is reproducible.** The same files give the same bytes:

- names in one fixed order (sorted), inside the one folder;
- one fixed time for every file, 1980-01-01 00:00:00 by default (`--epoch` sets another), written as it is
  and not taken from the clock or the time zone of the PC that builds;
- no detail of the building PC: the same creator mark, the same attributes, no extra fields, no comment.

Measured: two builds from the same inputs gave the same bytes (about 231 MB, 267 files). The bytes depend on
the Python and zlib that compress; with another zlib the compressed bytes may differ while the files inside
are the same. The tool prints the SHA-256 of the `.zip`. Checksums and signatures of a release are the
release script's work (P2.12): `release.py prepare` keeps only the `.zip` in the release folder, lists it in
`SHA256SUMS` and names it in the update manifest as the `portable` package of its variant.

## 3. The launcher

`Thoron.exe` is built from `components/thoron_update/launcher/thoron_launcher_win.cc` in the Chromium tree. It
uses nothing of the browser's code and is built without the processor flags of the builds, so it runs on
every x64 processor (P4.4). What it does, in this order:

1. It finds the package's folder from its own file, every time it starts. No path is stored anywhere.
2. It reads `variant`. On a processor without what that variant needs (AVX2 for `win-x64-avx2`, SSE4.2 for
   `win-x64-sse4`) it says so and starts nothing. Without the file it takes the AVX2 build.
3. It reads the first line of `Application\current` and starts `Application\<that version>\thoron.exe`. A
   package made before versions side by side had `Application\thoron.exe`, which it starts when the version
   is not there; `portable.py` never makes one.
4. It makes `User Data` before the start, and starts nothing when it cannot. Chromium's start-up code uses
   the PC's own profile folder when it cannot make the folder it was given, so on a write-protected drive the
   browser would quietly work in `%LOCALAPPDATA%\Thoron\User Data`. (This is read in Chromium's source. It
   was not tried with the real browser, because trying it would open the real profile of the test PC.)
5. It starts the browser with `--user-data-dir="<package>\User Data"` and the rest of its own command line,
   exactly as it got it, and ends at once. It adds no other switch. The `--no-default-browser-check` that
   the `.cmd` added is not needed: Thoron's build removes the default browser prompt and the check behind
   it (`source/overlay/other/disable-default-browser-prompt.patch`, from upstream).
6. It is a window program, so no console window opens, and it hands no handle of its own to the browser.

| Exit status | Meaning |
|---|---|
| 0 | the browser was started |
| 2 | no browser in the package |
| 3 | this processor cannot run the package's variant |
| 4 | the profile folder cannot be made, or the start failed |

Its messages are shown in a small window. The checks set `THORON_LAUNCHER_MESSAGE_FILE` to read them from a
file instead, and `THORON_LAUNCHER_ASSUME_CPU` (`sse4` or `old`) to try other processors.

### 3.1 What the `.cmd` launcher could not do, and the proof

Until this change the launcher was `Thoron.cmd`, a batch file: readable text, no compiler needed. It had to
keep a dozen rules against `cmd.exe` (`LAUNCHER_TEXT` and `launcher_problems` in `portable.py`), and some
things no batch file can do. All of that is gone with it: no command interpreter reads the folder's name or
the arguments any more.

The tests are in `tools/release/tests/test_portable.py`. `LauncherRunTests` starts the real `Thoron.exe` (set
`THORON_TEST_LAUNCHER` to a built `thoron_launcher.exe`; the tests are skipped without it and away from
Windows). A small stand-in program takes the browser's place and writes down the command line, the working
directory and the environment it was started with. The real check then does the same with the real browser.

| What the `.cmd` could not do, or had to work around | Now | Proved by |
|---|---|---|
| Start from a folder whose name holds an existing variable between two `%`, such as `%TEMP%`: `cmd.exe` put the value into the path first | Starts; the profile is made under that very name | `test_a_folder_named_after_an_environment_variable`, `test_a_package_portable_py_built` (unpacked into a `%TEMP%` folder); the check's "signs" folder |
| Avoid the console window: it showed for a moment at every start | No console: the launcher is a window program, which the audit checks | `test_the_launcher_and_the_updater_must_be_x64_programs`, the audit hook |
| Pass an unquoted `&`, `\|`, `<`, `>` or `^` | Passed as it is when the launcher is started directly (a shortcut, Run, another program). Typed at a prompt, the prompt's own rules still apply | `test_arguments_pass_as_they_are` |
| A program reading the launcher's output waited until the browser ended: the browser got the same pipe | The browser gets no handle of the launcher's | `test_a_caller_that_reads_the_output_does_not_wait_for_the_browser` |
| Code pages, `!` with delayed expansion, `%` read twice, `^ ( ) ; , =`, a folder alone in quotes, a start by the bare name, `exit` closing the caller | Nothing reads them: the folder comes from Windows as the program's own file name | `test_folder_names` (spaces, accented Latin, Cyrillic, CJK, characters beyond 16 bits, `& % ! ^ ( ) ; , =`), `test_a_start_by_the_bare_name_through_the_search_path` |
| Tell the processor | Says so before the start (exit 3) | `test_the_processor`; `portable_launcher_check.py` |
| Start the version `current` names | Does | `test_the_version_current_names_starts` |

And what both do, proved again for the program: arguments reach the browser intact
(`--flag "two words" "https://example.com/?a=1&b=2%20c"`, `test_arguments_reach_the_browser_intact`, started
as a command line, as a list and as typed at a prompt); a start from another working directory and by a
relative path (`test_started_from_another_working_directory`); the environment passed on unchanged; the
launcher not waiting for the browser; a moved and renamed folder; no browser in the folder (exit 2, nothing
made); a folder in which `User Data` cannot be made (exit 4, nothing started; the test denies making folders
there, and is skipped when the account running it passes over such a rule).

### 3.2 Known limits

- Fixed 2026-11-16, found by these tests: **a file named `User Data`** in the package's folder was taken for
  the profile folder (Windows answers "already there" for a file as for a folder), and the browser then fell
  back to the PC's own profile. The launcher now asks whether it is a folder and otherwise starts nothing
  and says why (`test_a_file_in_the_place_of_the_profile_folder_starts_nothing`). A junction there is a
  folder and is used, as the person made it.
- Fixed 2026-11-16, found by these tests: **the browser ran in the package's folder** instead of the
  caller's, so a file named by a relative path (`Thoron.exe page.html` at a prompt elsewhere) was looked for
  in the package. The launcher now leaves the working directory as it is
  (`test_started_from_another_working_directory`); a relative path with the real browser was not tried.
- **`Application\<version>\thoron.exe` started on its own uses the PC's profile**, not the one in the
  folder. Only the launcher sets the profile's place.
- **Full paths longer than about 250 characters** are not tried.
- **A network share** is not tried.

## 4. What stays in the folder, and what a portable copy leaves on the PC

### 4.1 Measured

`tools/qa/portable_check.py` built the package, unpacked its `.zip` into three folders (one with spaces, one
named in accented Latin, Cyrillic and CJK, one with `& % ! ^ ( )` and `%TEMP%`), started the browser through
`Thoron.exe` three times in each (first, again, moved and renamed, the last into a folder named with `%OS%`)
and once as the root of a drive letter. Ten starts, all headless, from a working directory that was not the
package's.

| Place | What was found |
|---|---|
| The package's folder | The profile is in `User Data`: the browser names it as its profile, Windows names the program in the version folder as the running one, and the DevTools port file, `Local State` and `Default\Preferences` are there. A setting changed in one start is read back in the next, and after the move. Nothing else appears in the folder. |
| `Application` | The same files before and after. Neither the launcher nor the browser writes into it. |
| Beside the package, and the working directory | Nothing. |
| `%LOCALAPPDATA%\Thoron` and its `User Data` (an installed Thoron's own place) | No new name. Only the names before and after were compared; nothing was opened. |
| The temporary folder | One or two `scoped_dir` folders of the browser were left after the normal exits (two in the first run, one in the second; the last run with the `.cmd` left none). Why, and what they held, was not looked into. (For this the browser's temporary folder was pointed at a scratch folder.) |
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

Inside the profile, after the move: one setting still held the old place after one start in the new one,
`extensions.settings.<id>.path` of a built-in extension in `Secure Preferences` (the run with the `.cmd`
found two). The browser started and kept the setting. Whether anything reads that path was not checked.

The profile's key for passwords and cookies is kept by the Windows account (DPAPI); see "Not there yet".

### 4.2 Not measured

- **A real USB drive.** A program cannot test one. A drive letter put on the package's own folder with
  `subst` was tested (the launcher and the browser both ran from `<letter>:\`), which proves the path
  handling at a drive root and nothing about a real drive: its file system (FAT, exFAT), its speed, pulling
  it out, or write protection. The launcher's answer to a folder it cannot write is tested with the
  stand-in program only.
- **A start with windows.** Only headless starts were measured. With windows the browser also keeps a
  list for the taskbar's jump list, which Windows stores in the user's own folder, and a person can leave
  more: downloads in the PC's Downloads folder, a web app's shortcut on the desktop (it holds a full path).
- **What Windows itself records** about any program that ran (the list of started programs, the virus
  scanner's history and the like). No launcher changes that.
- **A PC that never had Thoron**, and a second PC or a second Windows account.

## 5. The real checks

```
py -3 -I tools/qa/portable_check.py --chrome-bin <out>\Chrome-bin --launcher <out>\thoron_launcher.exe
    --updater <out>\thoron_update.exe --work <scratch dir> [--drive-root]
```

It needs no network and no real profile, closes only processes whose program file is inside the scratch
folder, and removes everything it made. It ran in full twice on 2026-11-16, with the same result apart from
the count of `scoped_dir` folders; a run took about 75 seconds. The first one:

```
PASS  package: 267 files, Thoron 158.0.8127.3010 (win-x64-avx2), a .zip of 231 MB; the portable audit of the folder and of the .zip and package_audit.py pass
PASS  spaces/first: the launcher ended after 0.0 s; program and profile in the folder; a new profile, setting 16 -> 17; its key is kept by the Windows account (DPAPI)
PASS  spaces/again: the setting read back: 17
PASS  spaces/moved: the same profile in the new place, setting 17; settings that still name the old place: [1 setting]
PASS  spaces/folder: the package holds ['Application', 'README.txt', 'Thoron.exe', 'User Data', 'variant'], nothing beside it or in the working directory
PASS  scripts/first: the launcher ended after 0.0 s; program and profile in the folder; a new profile, setting 16 -> 19; its key is kept by the Windows account (DPAPI)
PASS  scripts/again: the setting read back: 19
PASS  scripts/moved: the same profile in the new place, setting 19; settings that still name the old place: [1 setting]
PASS  scripts/folder: the package holds ['Application', 'README.txt', 'Thoron.exe', 'User Data', 'variant'], nothing beside it or in the working directory
PASS  signs/first: the launcher ended after 0.0 s; program and profile in the folder; a new profile, setting 16 -> 21; its key is kept by the Windows account (DPAPI)
PASS  signs/again: the setting read back: 21
PASS  signs/moved: the same profile in the new place, setting 21; settings that still name the old place: [1 setting]
PASS  signs/folder: the package holds ['Application', 'README.txt', 'Thoron.exe', 'User Data', 'variant'], nothing beside it or in the working directory
PASS  root: started as <letter>:\Thoron.exe, the launcher ended after 0.0 s; profile at <letter>:\User Data, setting 16 -> 23; the letter is removed again
PASS  host: 2 folders of the PC's own Thoron hold <N> names, none new; registry key Software\Thoron: new keys: none; written during the runs: [the six keys of section 4.1]; left in the temporary folder: {'scoped_dir#_#': 2}
PORTABLE CHECK: PASSED
```

(Shortened here: the setting and the six keys, which section 4.1 names, and the count of names.)

`tools/qa/portable_launcher_check.py` checks the launcher and an update and rollback in the updater's layout.
It takes the parts, not a finished package, and lays out its own folder with the same build in twice, as an
older and a newer version. It was run with the parts taken out of a package `portable.py` built: its
`Application\<version>` folder as the browser, its `Thoron.exe` and its `thoron_update.exe`:

```
py -3 -I tools/qa/portable_launcher_check.py --chrome-bin <package>\Application\158.0.8127.3010
    --launcher <package>\Thoron.exe --cli <package>\Application\158.0.8127.3010\thoron_update.exe --work <work>
```

```
== spaces
PASS  start: <work>\launcher-check\a folder with spaces & more!\ThoronPortable\Application\158.0.8127.3000\thoron.exe
PASS  update: <work>\launcher-check\a folder with spaces & more!\ThoronPortable\Application\158.0.8127.3010\thoron.exe
PASS  status: current: 158.0.8127.3010 / previous: 158.0.8127.3000 / mode: auto
PASS  rollback: <work>\launcher-check\a folder with spaces & more!\ThoronPortable\Application\158.0.8127.3000\thoron.exe
== letters
PASS  start: <work>\launcher-check\Ünïcødé Пример 例\ThoronPortable\Application\158.0.8127.3000\thoron.exe
PASS  update: <work>\launcher-check\Ünïcødé Пример 例\ThoronPortable\Application\158.0.8127.3010\thoron.exe
PASS  status: current: 158.0.8127.3010 / previous: 158.0.8127.3000 / mode: auto
PASS  rollback: <work>\launcher-check\Ünïcødé Пример 例\ThoronPortable\Application\158.0.8127.3000\thoron.exe
PASS  processor: exit 3
== drive root (<letter>:)
PASS  start: <letter>:\Application\158.0.8127.3000\thoron.exe
PASS  update: <letter>:\Application\158.0.8127.3010\thoron.exe
PASS  status: current: 158.0.8127.3010 / previous: 158.0.8127.3000 / mode: auto
PASS  rollback: <letter>:\Application\158.0.8127.3000\thoron.exe
PORTABLE LAUNCHER CHECK: PASSED
```

(The status lines are joined with `/` here.) The packaged updater also reads the `current` that `portable.py`
writes: `thoron_update.exe --root <package>\Application --status` answered `current: 158.0.8127.3010`,
`previous: none`, `mode: auto`.

## 6. Not there yet

| What | Until then | Stage |
|---|---|---|
| Updates | The browser of a portable copy updates it from the release's package once releases are signed (P2.11): its own updater unpacks the new version beside the old one, puts it in place and refreshes the launcher, and the relaunch runs it (`tools/qa/portable_update_check.py` does the update with the real programs and a real package, offline). Until releases are signed, by hand: close Thoron and replace everything in the folder except `User Data` | P2.11, P3.20 |
| A profile that opens on any PC | Saved passwords and sign-ins are locked to the Windows account they were saved with (measured: the profile's key is kept by DPAPI). On another PC or account they cannot be read and may be lost (known from how Chromium protects them; not measured). The browser's flag that stores them unprotected is deliberately not used | P4.9 |
| Taking over an upstream Thorium portable folder | Not offered | P4.10 |
| A portable copy that leaves no registry values | See section 4.1; it needs a change in the browser | no stage yet; upstream's report "Portable is not fully portable" (#592) is kept under P3.12 and P4.9 |
| The browser started without the launcher from a portable folder | It uses the PC's profile | no stage yet; it belongs with the launcher |
| The first run's offers (import, P3.21) in a portable copy | Not adapted to a portable copy | P3.21 |
| A signed `.zip` of a real release | `release.py prepare` makes it and lists it in `SHA256SUMS`; the release keys are not made yet | P2.11 |
| Signed program files, the launcher among them | Windows may warn about an unknown publisher | S.8 |
| An ARM64 portable package | The launcher knows the two x64 variants only, so `portable.py` refuses others | P2.7, P3.12 |
| A test on a real USB drive, by a person | Section 4.2 | P2.8, P3.12 |
| The installer half of P2.8 | Not part of this work | P2.8 |
| Linux portable `.tar.xz` and its shell launcher | Not part of this work | P2.9, P3.12 |
