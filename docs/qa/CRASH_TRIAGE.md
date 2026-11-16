# Crash triage (ROADMAP Q.5)

How a crash of Thoron is looked into: where the dumps are, how to read one on Windows and on Linux, the
steps and labels of triage, what never leaves a PC, and the decision on publishing symbols.

Status: written 2026-11-16, before the first release. The debugger commands below name tools of the
Windows SDK and of the Chromium tree. They were not run on a Thoron dump for this page; the first real
triage confirms them (section 9).

## 1. Thoron sends no crash reports

Thoron has no telemetry (design, section 3). When a process crashes, Crashpad, Chromium's crash
handler, writes a dump file on the PC, and that is all.

Chromium uploads crash reports only in Google's own branded builds, and Thoron is not one
(`is_chrome_branded = false`, [`RELEASE_ARGS.md`](../build/RELEASE_ARGS.md)). That is the expectation.
Proposed check for every release build, not built yet: on a throwaway profile with Chromium's network
log on, open `chrome://crash` (it crashes the page's process on purpose); a dump must appear in the
folder of section 2 and the log must show no request that carries it.
[`NETWORK.md`](../security/NETWORK.md) lists hosts only, so it cannot show this by itself.

## 2. Where the dumps are

| Install | Folder |
|---|---|
| Windows, installed | `%LOCALAPPDATA%\Thoron\User Data\Crashpad\reports` |
| Windows, portable | `Crashpad\reports` in the profile folder inside the portable folder |
| Linux | `~/.config/thoron/Crash Reports` (new dumps in `pending`) |
| Any build started with `--user-data-dir=<folder>` | `<folder>\Crashpad\reports` on Windows, `<folder>/Crash Reports` on Linux |

- A dump is a `.dmp` file, a minidump: a part of the memory of the process that crashed.
- On Linux the launcher script removes pending dumps older than 30 days.
- The smoke test of every build ([`tools/build/smoke.py`](../../tools/build/smoke.py)) fails when its
  throwaway profile ends with any file in these folders, so a build that crashes at start does not
  become a release.
- To say how many dumps there are, count the files. Nobody needs to open or send them for that.

## 3. Reading a dump

First find the build. The version on `chrome://version` and the variant (AVX2, SSE4, ARM64) lead to
that release's `BUILDINFO` file, which names the commit and the build configuration.

### Windows

`cdb.exe` and WinDbg come with the Debugging Tools for Windows, which the build setup installs
([`WINDOWS.md`](../build/WINDOWS.md), section 1).

```powershell
cdb -z <dump>.dmp -y "<symbols folder>" -c ".ecxr; kn 40; lmv m chrome; q"
```

- `.ecxr` moves to the moment of the crash, `kn 40` prints 40 frames of the stack, `lmv m chrome`
  prints the version of `chrome.dll`. `!analyze -v` adds the debugger's own summary.
- Without Thoron's symbols a frame reads as a module and an offset (`chrome+0x...`). That already
  shows whose code crashed, and a maintainer with the symbols of that exact build can name the
  function from it.
- Frames in Windows' own modules get names from Microsoft's public symbol server when
  `srv*<cache folder>*https://msdl.microsoft.com/download/symbols` is added to the symbol path. That
  sends Microsoft the names and build numbers of the Windows modules in the dump, not the dump. Leave
  it out to stay offline.

### Linux

The tools are built in the Chromium tree the release was built in:

```bash
autoninja -C <out dir> minidump_stackwalk dump_syms
components/crash/content/tools/generate_breakpad_symbols.py --build-dir=<out dir> \
    --binary=<out dir>/thoron --symbols-dir=<symbols folder>
<out dir>/minidump_stackwalk <dump>.dmp <symbols folder> > stack.txt
```

Without the symbols folder, `minidump_stackwalk <dump>.dmp` still prints the reason of the crash and
the frames as module and offset.

### What to read out of it

1. **The reason:** the exception code on Windows, the signal on Linux.
2. **The process:** browser, renderer, GPU or utility. Crashpad stores it as an annotation of the
   dump.
3. **The top frames,** and above all their modules: Thoron's own (`chrome.dll`, `thoron.exe`, `thoron`
   on Linux), a graphics driver, or a module another program put into the browser.
4. **The version and the variant.**

| What the dump shows | Usual meaning | Next step |
|---|---|---|
| Illegal instruction (`0xC000001D`, `SIGILL`), often right at start | The build variant does not fit the CPU, for example the AVX2 build on a CPU without AVX2 (ROADMAP **P2.7**, **P4.4**) | Ask for the CPU's class; try the SSE4 build |
| Breakpoint (`0x80000003`) or trap inside Thoron's module | Chromium stopped itself on a failed check; upstream #1230 is one (ROADMAP **P5.4**) | The stack names the check |
| Access violation (`0xC0000005`, `SIGSEGV`) | A memory bug; upstream #1288 is one (ROADMAP **P5.6**) | Section 4, step 2, before anything else |
| Top frames in a graphics driver, GPU process | Driver or hardware acceleration | Ask for `chrome://gpu`'s feature list; try with acceleration off |
| Top frames in a module that is neither Thoron's nor the system's | Security or overlay software injected into the browser | Name the module; try without that program |
| Frames in Thoron adblock or its Rust engine | Thoron's own code | `origin-thoron`, first in line |

## 4. Triage steps

1. **Take the report in.** A crash comes in as a bug report, labelled `crash`. Needed: Thoron version
   and variant, OS, what was being done, whether it happens on a new profile
   (`--user-data-dir=<empty folder>`), whether it happens in Chromium or Thorium of the same version,
   and how many dumps there are. If the reporter can read the dump (section 3), the reason and the top
   frames as text. Never the dump itself (section 6).
2. **Look for a security problem first.** Signs: an access violation while writing or executing, a
   damaged heap, a crash a web page can cause on demand. Then no details go into the public issue: the
   reporter is asked to use private reporting ([`SECURITY.md`](../../SECURITY.md)), and a bug that
   Chromium of the same version shares goes to the Chromium project.
3. **Reproduce** on a throwaway profile, never on a real one. For a crash at start, `smoke.py` is the
   shortest way. Try the same steps in Chromium and in upstream Thorium of the same version.
4. **Find whose code it is** and set one `origin-` label: Thoron's own code or patches, an upstream
   Thorium patch, Chromium, or something outside the browser.
5. **Decide:** fix it in Thoron with a test that fails before the fix; report it to Thorium or
   Chromium and link the report; or record it as a known issue of the next release, with the reason.
6. **Close:** a `Fixed` line in [`CHANGELOG.md`](../../CHANGELOG.md), the row of the
   [upstream issue map](../../ROADMAP.md#upstream-issue-map) when it was one of those, and the issue
   closed with the version that carries the fix.

A crash blocks the next release (`release-blocker`) when it happens at start or in the browser process
on a new profile, when it loses or damages profile data, when the smoke test or the profile rehearsal
(ROADMAP **Q.7**) shows it, or when it is new since the last release on a path most people use.

The crashes already on the roadmap go through these steps first: ROADMAP **P5.3** to **P5.6**. The soak
test (**Q.4**) feeds its dumps into the same steps.

## 5. Labels

`bug` and `arm64` exist. The others are proposed and do not exist in the repository yet.

| Label | Meaning |
|---|---|
| `crash` | A crash, a "this page crashed" tab, or a hang that ends in a dump |
| `needs-info` | Version, variant, OS or steps are missing |
| `needs-stack` | There is no readable stack yet |
| `cannot-reproduce` | Not reproduced on a new profile after a real try |
| `origin-thoron` | Thoron's own code or patches |
| `origin-thorium` | An upstream Thorium patch |
| `origin-chromium` | Chromium of the same version does it too |
| `origin-third-party` | A driver, a module another program injects, or an extension |
| `regression` | It did not happen in the previous Thoron release |
| `release-blocker` | To be fixed or explained before the next release |
| `arm64` | Only on ARM64 ([ARM beta checklist](ARM_BETA_CHECKLIST.md)) |

There is no public label for a security problem: such a report leaves the public issues (step 2).

## 6. What never leaves the PC

A dump is memory. It can hold the addresses of open pages, text from pages and forms, cookies,
passwords, the user's and the PC's name, environment variables, the path of the profile, and the list
of loaded modules, which shows what security software is installed.

1. **Thoron uploads nothing** (section 1).
2. **A dump is never attached** to an issue, a pull request or a discussion. A maintainer who sees one
   removes it at once and tells the reporter. Whether a removed attachment's address stops working is
   to be checked with GitHub; it was not verified for this page.
3. **A dump is never uploaded** to an online analyser, a paste site or a shared or cloud-synced
   folder, and never committed ([`CONTRIBUTING.md`](../../CONTRIBUTING.md), privacy rules).
4. **Maintainers never ask for a dump in public.** They ask for text: the reason, the process, the top
   frames. Before pasting, the user name is taken out of any path (`C:\Users\<name>\...` on Windows,
   the home folder on Linux).
5. **Nor for anything from `User Data`,** and not for `chrome_debug.log`, which names the pages that
   were open.
6. **A maintainer's own dumps** from test runs stay in a private local folder that is not cloud-synced
   and are deleted when the triage is done, as profile copies are (`WINDOWS.md`, "Upgrading").
7. **When only the dump could answer the question,** the answer is to reproduce the crash. Thoron has
   no private channel for a dump that is not a security report, and proposes not to add one
   (section 9).

## 7. Symbols

A dump is read with the symbols of exactly the build that wrote it: on Windows the `.pdb` files the
build writes next to its programs (`chrome.dll.pdb`, `thoron.exe.pdb`), on Linux the program before it
is stripped. Symbols from another build of the same source fit only if that build is byte-identical,
which the design calls a stretch goal (design 6.1). So they are kept when the release is built, or
they do not exist.

Whether a release build writes symbols at all depends on `symbol_level` in the release configuration,
which comes from upstream's args file. This repository does not record it yet:
`gn args <out dir> --list=symbol_level` answers it, and the answer belongs in `RELEASE_ARGS.md`.
Without symbols, triage has the module and offset of each frame, and reproduction.

## 8. Decision: publishing symbols

**Recommended on 2026-11-16. Awaiting the owner's confirmation; nothing is published before it.**

Recommendation:

1. Every release build writes symbols that are enough for a stack trace: function names and line
   numbers (`symbol_level = 1`). They stay out of the installer and the portable package.
2. The symbols of every published release are kept next to its `BUILDINFO`, for as long as that
   release can still be in use.
3. They are published as one more file of the release per variant, listed in the signed `SHA256SUMS`.
   No symbol server.

Reasons:

- **Privacy.** With public symbols a person turns their own dump into a readable stack on their own PC
  and shares only that text. Without them, the only way to a readable stack is to send the dump, with
  the person's memory in it, to a maintainer, which section 6 rules out.
- **Nothing in them is secret.** Thoron is open source. Symbols name functions and source lines that
  are in `main` already, and hold nothing of anyone's profile.
- **Traceable builds (G1).** Symbols tie a crash, and a binary, to the published source.
- **No server.** A file on the release fits "everything is served from GitHub as static files"
  (design, section 3). A symbol server would be a service to run, and it would see who debugs which
  build.
- **One maintainer.** A readable stack in a report replaces hours of trying to reproduce.

Conditions, each to be met before the first publication:

- **Cost measured.** What `symbol_level` is today, and what a build with symbols costs in time, memory
  and disk, is measured and recorded in [`BUILD_BUDGET.md`](../build/BUILD_BUDGET.md) and
  `RELEASE_ARGS.md`. It must not endanger the 7-day target of
  [security releases](../security/SECURITY_RELEASES.md).
- **The same program.** The benchmarks (ROADMAP **Q.1**) show no difference between a build with
  symbols and one without.
- **No private paths.** Symbol files can carry source paths of the build machine. Before publication
  they are scanned for the build root and for user names, as `tools/build/buildinfo.py` and the
  privacy linter do for their files, and a hit stops the release. Proposed; not built yet.
- **No withheld source.** While files are withheld from `source/` (ROADMAP **L.1**, **L.8**), symbols
  would name what is in them. Both lists must be empty before the first release anyway.
- **Size.** The file must fit what GitHub allows for a release file (to confirm). If it does not, it
  is split by module.

Alternatives considered:

| Alternative | Why not |
|---|---|
| Release builds without symbols | No readable stack for any crash of a release; triage can only reproduce |
| Symbols kept private | Maintainers could read a dump only by receiving it, which draws people's memory dumps towards the project |
| A symbol server | A service to run and a record of who debugs what; against the "no servers" non-goal |

If the owner decides against publishing, the symbols are kept private, dumps are still never asked
for, and triage works from reproduction and from module and offset.

| Date | Step | By |
|---|---|---|
| 2026-11-16 | Recommended: publish stack-trace symbols with every release, under the conditions above | QA engineer, security researcher |
| - | Confirmed or changed | Owner (pending) |

## 9. Open items

1. **The owner's confirmation** of section 8.
2. **`symbol_level` of the release configuration:** record it, and measure a build with symbols.
3. **No private channel for dumps** (section 6, rule 7): proposed as the rule; the owner may decide
   otherwise for security reports.
4. **The labels of section 5** need someone with rights on the repository to create them.
5. **`*.dmp` in `.gitignore`:** proposed, so a dump cannot be committed by accident.
6. **The no-upload check of section 1:** proposed as an addition to `tools/qa/netlog_hosts.py` or
   `tools/build/smoke.py`.
7. **First real triage:** confirm the commands of section 3 on a Thoron dump, on Windows and on Linux,
   and correct this page.
