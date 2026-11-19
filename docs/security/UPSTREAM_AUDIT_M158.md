# Audit of upstream's changes for Chromium 158 (ROADMAP P2.2)

Every change upstream Thorium made between the last audited commit and the commit Thoron's Chromium 158
series is built on, checked with [`tools/audit`](../../tools/audit/README.md) and then read by a person
(ROADMAP **S.1**). The short form for the release notes is in [section 9](#9-for-the-release-notes).

Status: audited 2026-11-16. 13 findings: 11 fine, 1 fine with a note, 1 needs a change in Thoron (a
warning on one new flag, [section 5](#5-the-new-switch-for-extensions-from-other-sites)): the change is
made in the identity step and is in every build after 158.0.8127.3010. None needs the owner's decision.
Nothing is left to be reviewed.

How to read it:

- A statement without a mark was checked: read in the diff, in Thoron's tree, or in the output of a
  command shown here.
- **Inferred** marks what was concluded without a direct check.
- **Chromium 158** means Chromium's own source at tag 158.0.8127.30, read from the public Chromium
  repository where the diff alone does not show what the code does.
- Line numbers of a patch are those of upstream's file at the audited commit.

## 1. Range

| | |
|---|---|
| Upstream | https://github.com/gz83/thorium |
| Last audited commit | `de9a1bc6`, the M156.0.8078.28 state that ROADMAP **P1.3** reproduced |
| Audited up to | `efc0fffc256e7402ad4c3dc38ae1e5754221c03d`, the commit pinned in [`source/UPSTREAM.json`](../../source/UPSTREAM.json) |
| Commits | 18, dated 2026-10-26 to 2026-11-08, by Ho Cheung (16) and Alexander Frick (2); no merge commit |
| Files | 66 changed: 48 modified, 15 added, 3 deleted; 4,461 lines added, 653 removed |
| Kind of files | All 66 are text files with mode 100644: no binary file, no executable bit, no symbolic link, no submodule |
| By area | 42 patch files under `other/`, 6 files under `src/`, 6 under `infra/macos/`, 4 under `patch_scripts/`, 3 under `docs/`, 1 workflow under `.github/`, and `README.md`, `chromium_sync.py`, `trunk.py`, `version.py` |

## 2. What of it Thoron ships

Thoron's build tree is the pinned upstream commit with [`source/overlay/`](../../source/overlay) on top
and the files in [`source/REMOVED.txt`](../../source/REMOVED.txt) left out
([`tools/build/source_tree.py`](../../tools/build/source_tree.py)). The build then runs one upstream
script, `setup.py` ([`tools/build/pipeline.py`](../../tools/build/pipeline.py)). It copies upstream's
`src/` files into Chromium, merges the translation tables and applies the patch series. `setup.py`
did not change in this range, and it names neither `.github/`, `infra/macos/` nor the three scripts in
the last row below. A finding about a file Thoron does not carry is settled by that.

| Part of the range | In Thoron |
|---|---|
| 35 patch files | Applied from `source/overlay/other/`, each with Thoron's attribution header, ported to Chromium 158 where needed. 28 of the 42 patch files only moved with Chromium (section 3). For every patch whose change differs, Thoron's copy has each line the range added, with two exceptions: 14 lines of `developer-crx-installation.patch` that belong to an Android page, and the entry numbers in `open_in_same_tab.patch`, which Thoron renumbered for Chromium 158 |
| 5 patch files: `GPC.patch`, `android-extensions-opt-in-ui.patch`, `android-extensions-support.patch`, `enable-ctrl-tab-mru.patch`, `enable-extension-in-incognito.patch` | Not carried (`source/REMOVED.txt`); the reasons are in [`M158_REBASE.md`](../build/M158_REBASE.md) |
| `other/thorium-build-config-and-simd.patch` | Built, but withheld from the published source (ROADMAP **L.1**). It is the only one of the seven withheld files that changed in this range; the other six, among them `thorium-default-api-keys.patch`, are the same file at both ends |
| `other/v8-linux-woa-snapshot-toolchain.patch` | Deleted upstream; `v8-linux-snapshot-toolchain.patch` replaces it and Thoron carries that |
| 6 files under `src/` | Copied as they are. `thorium_flag_entries.h` then gets Thoron's edits in the identity step (`OVERLAY_EDITS` in [`tools/build/thoron_identity.py`](../../tools/build/thoron_identity.py)) |
| `patch_scripts/` | The series file is Thoron's own (`source/overlay/patch_scripts/series/series`). The translation tables are used as they are (**inferred** from `setup.py`, which runs `merge_thorium_xtb.py` on that folder) |
| `.github/`, `infra/macos/`, `chromium_sync.py`, `trunk.py`, `version.py`, upstream's `README.md` and `docs/` | Part of the upstream tree only. Thoron's build does not read them, and Thoron's repository does not hold them |

## 3. Method

Run from the repository root of a clone that has upstream's history:

```shell
py -3 -I tools/audit/audit_diff.py . de9a1bc6 efc0fffc256e7402ad4c3dc38ae1e5754221c03d --strict
py -3 -I tools/audit/audit_diff.py . de9a1bc6 efc0fffc256e7402ad4c3dc38ae1e5754221c03d --json
py -3 -I tools/audit/patch_delta.py . de9a1bc6 efc0fffc256e7402ad4c3dc38ae1e5754221c03d --show
py -3 -I tools/audit/patch_delta.py . efc0fffc256e7402ad4c3dc38ae1e5754221c03d HEAD:source/overlay --show other/developer-crx-installation.patch
git log --stat --no-renames de9a1bc6..efc0fffc256e7402ad4c3dc38ae1e5754221c03d
git show <commit>
```

1. **`audit_diff.py --strict`** exits 1. Its report: 0 binaries, 0 submodule changes, 1 CI workflow
   change, 3 network endpoints, 2 `security_disabled` hits, 7 `self_update` hits, 5 `flags_switches`
   hits, and 67 lines in 7 files under "security-feature changes". No hit in `remote_exec`,
   `dynamic_code`, `persistence`, `encoded_payload`, `credentials`, `mining_telemetry` or
   `adult_content`. When this audit began the tool showed only the endpoints and the 9 pattern hits;
   the workflow, the flags and the security-feature lines come from the checks added during it
   (section 7).
2. **`patch_delta.py`** compares what each patch does. Of the 42 patch files, 28 make the same change
   as before (only context, offsets or index lines moved), 9 changed, 4 are new and 1 was deleted. The
   new patches were read in full, the changed ones by the lines they gained and lost. Two were read
   less closely because Thoron does not carry them: of `android-extensions-opt-in-ui.patch` the list of
   files it touches and a search for switches, features and addresses; of
   `enable-extension-in-incognito.patch` the hunks outside the Android folders.
3. **The 24 other files.** Read in full: the workflow, `infra/macos/smoke_test.py`,
   `infra/macos/cdp.mjs`, `chromium_sync.py`, and the diffs of `trunk.py`, `version.py`,
   `thorium_flag_entries.h`, the series file, the ownership table and the docs. Of
   `infra/macos/browser_probe.mjs` (559 lines) the first 260 lines and every place that starts a
   process, opens an address, passes a switch or writes a file; of `infra/macos/README.md` the
   reported lines with their paragraphs. `probe.html` and `navigation.html` were searched for outside
   references (none). `xtb_additions.tsv` was checked by script: 243 new
   rows of 7 columns, 81 languages for each of 3 messages, no address and no markup other than the
   translation element. `signin_spin.json` was parsed: a Lottie animation, format 5.12.2, with no
   address, no embedded image and no expression. The two new SVG files have the blob IDs of the two
   deleted ones.
4. **What Thoron carries** was compared patch by patch with the second `patch_delta.py` form, and with
   `source/REMOVED.txt` and `source/UPSTREAM.json`. The withheld patch was compared on the build
   machine, in the local build branch whose tree hash is the `tree` value of `source/UPSTREAM.json`.
5. **Chromium 158** was read for finding 8: `chrome/browser/download/download_crx_util.cc`,
   `ShouldOpenDownload` in `chrome/browser/download/chrome_download_manager_delegate.cc`, `InstallCrx`,
   `AllowInstall` and `ConfirmInstall` in `extensions/browser/crx_installer.cc`,
   `extensions/common/verifier_formats.cc` and `StartWithCrx` in
   `extensions/browser/sandboxed_unpacker.cc`.

## 4. Findings

Every line of the tool's report is in one of these rows. "New check" marks what the tool reports only
since this audit.

| # | Report | Where | What it is | Verdict | Thoron |
|---|---|---|---|---|---|
| 1 | CI workflow change (new check) | `.github/workflows/macos-smoke-test.yml`, added | Upstream's test of its macOS packages on GitHub's macOS runners. It starts only by hand or from another workflow (`workflow_dispatch`, `workflow_call`). Its permissions are `actions: read` and `contents: read`. Its four actions are pinned to full commit hashes. Every input reaches the shell through an environment variable and is checked against a pattern first. It downloads a disk image from the same repository's release or run artifacts and runs `infra/macos/smoke_test.py` on it. The only token is the run's own `GITHUB_TOKEN` | Fine | Not carried. Thoron's repository has one workflow, `.github/workflows/checks.yml`, and GitHub runs only the workflows in a repository's own `.github/workflows/` folder (GitHub's documented behaviour, not tested here) |
| 2 | Endpoint `IP 2.06.02.16` | `src/ui/webui/resources/images/incognito_icon_thorium.svg` | A false alarm: the digits are part of the drawing's path data. The file is upstream's former `incognito_icon.svg` under a new name, with the same blob ID. It has no script, link or outside reference | Fine | Copied as it is |
| 3 | Endpoint `github.com/actions` | `infra/macos/README.md` | A link to GitHub's list of runner images | Fine | Not used |
| 4 | Endpoint `www.baidu.com` | `infra/macos/browser_probe.mjs` | The macOS test opens Baidu's home page in the tested browser and searches for "hello" to reproduce upstream's issue 1316. It also opens `https://www.google.com/` (not reported, Google is on the tool's list of known hosts) and a page the test serves itself on `127.0.0.1`. It drives the browser through `--remote-debugging-pipe`, without a network port, in a temporary profile | Fine | Not used. Nothing of it is in the browser |
| 5 | `security_disabled`, 2 hits: `--no-sandbox` | `infra/macos/smoke_test.py`, `infra/macos/README.md` | After a failed run the test repeats the failing probe three times, each with one added switch (`--disable-extensions`, `--disable-gpu`, `--no-sandbox`) and a fresh temporary profile, to narrow down a crash. A diagnostic pass never replaces the failed result. The README line describes this. Nothing in the browser or its packages gets the switch | Fine | Not used. Thoron's own test, `tools/build/smoke.py`, proves that the renderer sandbox is in force |
| 6 | `self_update`, 2 hits: `IsWebstoreUpdateUrl` | `other/developer-crx-installation.patch` | Two conditions of the new function of finding 8: a download whose first or final address is a Web Store update address never takes the new path. No update address is added or changed | Fine | Carried |
| 7 | `self_update`, 5 hits: `showFullDownloadUrls`; `flags_switches`, 1 hit: `downloads-show-full-url` | `other/downloads-page-enhancements.patch`, `thorium_flag_entries.h` | A match on the name only. The downloads page showed the full address of every download; that is now the feature `kThoriumDownloadsShowFullUrl`, on by default, and the flag turns it off. No network or update code | Fine | Carried unchanged |
| 8 | `flags_switches`, 2 hits, and security-feature lines: `allow-offstore-extension-downloads` | `other/developer-crx-installation.patch` (the function `OffStoreInstallAllowedByUser` and its three callers), `thorium_flag_entries.h` (2 lines), upstream's `README.md` (1 line) | A new switch, off by default, that lets a `.crx` file downloaded from any website be installed while developer mode is on. Section 5 | **Needs a change in Thoron** | Carried. The flag has a warning in Thoron's form since 2026-11-16 (section 8, point 1) |
| 9 | Security-feature lines: the rest of the 58 lines of the same patch | `other/developer-crx-installation.patch` | An "Install CRX file" button on the extensions page, shown in developer mode. It opens a file picker and installs through the same code as dropping a `.crx` file on that page, which Chromium allows in developer mode: off-store reason "from settings page", with the permission prompt. The patch adds checks to that code: the browser itself now refuses a dropped or picked file when developer mode is off, in Incognito and for supervised profiles; the picker needs a user gesture and accepts only a `.crx` name. The unpacker now names its working copy `extension.crx` instead of the file's own name; the copy is verified as before | Fine | Carried, without 14 lines for an Android page |
| 10 | `flags_switches`, 1 hit: `disable-thorium-icons` | `other/disable-thorium-icons.patch` | An existing switch gets one more use: the Incognito new-tab page shows Thorium's or Chromium's icon. Both drawings are compiled-in resources (4 new entries in `browser_resources.grd`) and reach the page as data addresses; no network address, no file read while running | Fine | Carried, ported to Chromium 158 |
| 11 | `flags_switches`, 1 hit: `instant-menu-show` | `other/views-menu-delay.patch`, `thorium_flag_entries.h` | Thorium had set the submenu delay to 1 ms for everyone and ignored the Windows setting. Chromium's values are back (400 ms, or the Windows setting), and the new feature `kThoriumInstantMenus`, off by default, brings the 1 ms back. Menu timing only | Fine | Carried unchanged |
| 12 | Security-feature lines, 3: `v8_control_flow_integrity` | `other/v8-linux-snapshot-toolchain.patch` | The patch keeps V8's control-flow integrity off in the program that writes V8's startup snapshot when a Linux x64 machine builds for ARM64 Windows. This range renames the patch and adds ARM64 macOS to the same condition. The patch's reason: those targets run with `arm_control_flow_integrity = "none"`, and a snapshot written with it on does not fit them. **Inferred** from the condition and its comment, not from a build: the browser that is shipped keeps the setting its target had before | Fine, with a note | Carried unchanged. No effect on today's builds: Windows x64 and Linux x64 are each built on their own system, and the condition needs a Linux machine building for ARM64 Windows or macOS. The note is in section 8 |
| 13 | Security-feature lines, 3: "quarantine" twice, `--use-mock-keychain` | `infra/macos/README.md`, `smoke_test.py`, `browser_probe.mjs` | The test copies the app out of the disk image with its signature and quarantine marks kept, requires `codesign --verify --deep --strict` to pass, and starts the browser with a mock keychain so that it never touches the runner's real one | Fine | Not used |

### The special-attention list

| Topic | Result | Evidence |
|---|---|---|
| Added or changed binaries | None | Tool: 0. `git diff --numstat` shows no binary file among the 66. The SVG files are renames, the JSON file was parsed (section 3) |
| Anything that downloads or executes | Only in upstream's test and sync scripts, which Thoron does not run | The workflow and the macOS test (findings 1, 4, 5) fetch a disk image and start the tested browser and macOS tools; `chromium_sync.py` runs `git` and `gclient`. The scripts start programs from argument lists, not through a shell; the workflow's shell steps take their inputs from checked environment variables |
| Default extensions and Web Store installs | The preinstalled extension and Web Store installs are untouched; one new opt-in path for other sites | `preinstall-ublock-origin.patch` is the same file at both ends. Finding 8 |
| API keys and credentials | None added | 0 `credentials` hits. `thorium-default-api-keys.patch` is the same file at both ends. The workflow names only the run's own token |
| Update addresses | None added or changed | Findings 6 and 7 are matches on names |
| Build flags that weaken security | None | `thorium-build-config-and-simd.patch` gains 18 lines that choose the optimization level (section 6, commit `e8fed38`). Finding 12. The build argument files under `other/AVX2/` are the same at both ends |
| Telemetry and new network contacts | None in browser code | The only hosts are in the macOS test (findings 3 and 4). `open_in_same_tab.patch` renumbers two entries of a histogram's label list for an existing menu item; it reports nothing new |
| Installer and registry | No change | No changed patch touches a file under `chrome/installer/`; `mini_installer.patch` is the same file at both ends; 0 `persistence` hits |

## 5. The new switch for extensions from other sites

Finding 8, upstream commit `312d9b5`, its fix for upstream's issue 1281.

**What the code does.** `OffStoreInstallAllowedByUser()` (lines 135 to 159 of the patch) is true only
when all of this holds: the switch `allow-offstore-extension-downloads` is on the command line;
extensions are not disabled; the profile is not Incognito and not a child's; developer mode is on
(`prefs::kExtensionsUIDeveloperMode`); the download has the CRX type or a `.crx` name; and the
download has no Web Store approval and neither its first nor its final address belongs to the Web
Store. For such a download `ShouldOpenDownload` sets the off-store reason
`OffStoreInstallAllowedBecausePref` (lines 61 to 80), the reason Chromium otherwise uses for sources
an administrator has allowed, and `OpenDownload` sends a later click on the saved file the same way
(lines 88 to 95). The switch is a `chrome://flags` entry, "Allow Third-Party Extension Downloads",
for all platforms, of the kind that is off until someone turns it on.

**What that changes, in Chromium 158.** Without the reason, `CrxInstaller::AllowInstall` refuses a
downloaded extension that is not from the Web Store (`OFFSTORE_INSTALL_DISALLOWED`). With it:

- the install goes ahead, and `ConfirmInstall` shows the usual prompt with the extension's
  permissions. An install started by a download never runs without that prompt: where there is
  none, the install is aborted;
- the file is checked as `VerifierFormat::CRX3` (`GetExternalVerifierFormat`) instead of the Web
  Store's format with publisher proof. It must be a well-formed CRX signed by the key its extension
  ID comes from. That shows the file is intact; it does not show who made it;
- the list of allowed install sources (`ExtensionInstallSources`) no longer limits where such a file
  may come from. The patch leaves every other policy check as it is.

So with the switch and developer mode on, any website can hand the browser an extension, and the
permission prompt is the one step left before it is installed. According to the patch's own comment
the installer is called when the download completes.

**Why it is not simply fine.** It stays opt-in, it needs two deliberate steps, it never installs
without the prompt, and the Web Store path keeps its stronger proof: there is no reason to take it out
of Thoron. But it lowers a protection Chromium has by default, and Thoron's rule is that such a flag
carries a warning (ROADMAP **S.4**; the wiki says "Flags that weaken security show a warning"). The
S.4 review found all 68 flags off by default, the number of entries the flag file has at the audited
commit, so this one was among them (**inferred** from the count); it gave five others a warning.
Upstream's text ends with "Only enable this for sources you trust", but it also says "CRX
signatures, permission prompts, and extension policies still apply", which reads as more than it is
(see the three points above), and it has a sentence about Android that does not apply to Thoron.

**The change.** In `OVERLAY_EDITS` of `tools/build/thoron_identity.py`, where the other five warnings
are, start this flag's description with a plain warning and drop the Android sentence, with a test
next to the existing ones. A wording:

> Warning: with this on and developer mode enabled, any website can offer you an extension that the
> Chrome Web Store has not checked. Only the permission prompt stands before the install, and the
> file's signature does not show who made it. Allows downloaded CRX files to be installed when
> developer mode is enabled on the extensions page.

Chromium's "unsupported command-line flag" bar could name the switch as well (`kBadFlags`, which
`other/ks-security-flag-warnings.patch` already edits). That is a second, optional step.

Decision taken in this audit: the feature stays, and the warning is added. The release notes name the
flag either way (section 9).

## 6. Commits the tool did not flag

When this audit began the tool flagged 5 of the 18 commits (`7308691`, `f6958a6`, `312d9b5`,
`4a31a6c`, `5bab49e`). These are the other 13, each read as described in section 3. With the checks
added in section 7 the tool now also flags the first three.

| Commit | What it changes | Result |
|---|---|---|
| `0a321d7` Fix macOS smoke tests | The workflow, the test and its guide | Test files only (findings 1, 4, 5). Not used by Thoron. Now flagged: workflow change |
| `04fec1d` Fix macOS V8 snapshots and smoke tests | Renames the V8 snapshot patch and extends it to ARM64 macOS; more test changes; adds `navigation.html` | Finding 12. Now flagged: workflow change and the three V8 lines |
| `8203bcc` Restore default menu delays and add instant-menu-show flag | `views-menu-delay.patch`, one flag entry; four patches moved with the code | Finding 11. Now flagged: the flag entry |
| `f739d84` Add Android extension opt-in guidance and disabled-state UI | New `android-extensions-opt-in-ui.patch` with its 162 translation rows and its lines in upstream's docs | Android only. Not carried |
| `a006c4e` Fix macOS Th24 tab strip gap above toolbar | `thorium-2024-ui-core.patch`: layout code for macOS (`immersive_mode_controller_mac.mm`, and a new helper for the tab strip's bounds whose only new step is under `BUILDFLAG(IS_MAC)`) | Layout only. Carried in ported form; on Windows and Linux the helper computes what the code it replaces computed |
| `2782b07` Fix Thorium first-run branding on desktop and Android | New `thorium-first-run-branding.patch`: CSS, and an SVG element that draws the product logo over the first-run picture, both from the page's own `images/` folder. `signin_spin.json`: an animation for Android's sign-in screen | No address, script or new permission. The patch is carried unchanged. The JSON file is copied but belongs to the Android build (**inferred** from its path, `android/java/res_chromium/raw`) |
| `ea5b348` Fix dependency rebase conflicts when switching Chromium revisions | New `chromium_sync.py`, called by `trunk.py` and `version.py`: before `gclient sync` it ends an unfinished `git rebase` or `git am` and detaches `HEAD` with `--force`, in the Chromium checkout and its dependencies | It discards local edits in a Chromium checkout, as its docstring says. Argument lists, no shell, no address of its own. Thoron's build does not run these three scripts |
| `81df936` Port Android incognito extension fixes and restore upstream behavior | Rewrites `enable-extension-in-incognito.patch` (386 lines gained, 105 lost) and edits the Android opt-in patch. Outside the Android folders it adds null checks to the extensions menu model and no longer overrides Chromium's `ShouldOpenInTab` choice in `extension_tab_util.cc` | Not carried |
| `d296202` Update to 156.0.8078.80 | 23 patches and the version string in `version.py`. 21 patches make the same change as before. `open_in_same_tab.patch` renumbers its menu and histogram entries; `android-extensions-support.patch` changes a build-flag condition in a unit test | A refresh. The two changed patches: carried with Thoron's own numbers for 158, and not carried |
| `41e3e83` Fix Android WebAPK build flag | `android-extensions-support.patch`: one build-flag condition in `components/webapps/browser/features.cc` | Android only. Not carried |
| `e8fed38` restore full optimizations in build/config/compiler:optimize config | `thorium-build-config-and-simd.patch`, 18 lines in `build/config/compiler/BUILD.gn`: when `is_full_optimization_build` is set (by default it follows `is_official_build`), the normal `optimize` config uses clang's `-O3` instead of `-O2`: on Windows for x86 and x64, and on Linux, macOS and Android, there with Rust's `-Copt-level=3` as well | Speed, not hardening: no sandbox, control-flow, stack or signature flag is touched. Thoron's withheld copy of the patch has all 18 lines |
| `d0f9f73` update SSE2 angle lockfree patch | `SSE2/angle-lockfree.patch`: a compile-time check (`static_assert`) that 64-bit atomics are lock-free replaces a check at run time | Stricter than before. Carried unchanged; it applies only to the SSE2 profile, which the x64 builds do not use |
| `efc0fff` Refresh patches | Two patches moved with the code | Same change as before |

## 7. What the tool missed, and what was changed

The audit's main finding, the new switch, reached the report only by chance: two of its lines contain
`UpdateUrl`. The section "security-feature changes" was empty.

| Blind spot | Evidence | Change, with tests |
|---|---|---|
| Changes to extension installs, sandbox policy, hardening build flags, data at rest, the quarantine mark, the installer and the registry were not security-feature changes | This range: 0 lines. Upstream's existing `disable-encryption.patch`, `thorium-sandbox-compat.patch` and `disable-download-quarantine.patch`, tried as if newly added: nothing reported | `audit_diff.py` knows these topics. This range now gives 67 lines in 7 files, 58 of them in the patch of findings 8 and 9. Test: one real upstream line per topic |
| A new switch or flag was not listed | The flag entry of finding 8 was in no category | New review category `flags_switches`: every `chrome://flags` entry and every switch named by a string |
| A new CI workflow was not listed | Finding 1 | CI workflow and action changes are listed, and `--strict` fails on them. It matters when upstream is merged rather than overlaid: a merged workflow runs with this repository's token |
| A patch file is read as text: a refreshed patch looks like hundreds of changed lines, and a line of context cannot be told from a line the patch adds | 42 changed patch files in this range, 28 of them unchanged in what they do | New tool [`patch_delta.py`](../../tools/audit/patch_delta.py). It reads each hunk by its declared line counts and also compares the lines outside the hunks, so a header-like line or a changed binary payload cannot pass as "same" |

Limits that remain, for the reviewer to cover by reading:

- A host named without `http://` or another scheme is not an endpoint for the tool.
- A script that starts programs from an argument list matches no pattern. New scripts must be read; in
  this range `chromium_sync.py`, `smoke_test.py` and `browser_probe.mjs`.
- A feature that is on by default but has no `chrome://flags` entry is not listed.
- The text report prints the first 12 hits of a category and the first 6 lines of a file. `--json` has
  all of them; in this range the patch of findings 8 and 9 has 58 lines.

## 8. Open points

1. **The warning of section 5** (ROADMAP **S.4**): done 2026-11-16 in `OVERLAY_EDITS` of
   `tools/build/thoron_identity.py`, with its tests in `tools/build/tests/test_thoron_overlay_edits.py`.
   The text is the wording of section 5 followed by upstream's "Only enable this for sources you
   trust."; the Android sentence and "CRX signatures, permission prompts, and extension policies still
   apply" are gone. Still to do: look at it in `chrome://flags` of the next build.
2. **ARM64** (finding 12). No ARM64 build exists yet
   ([`ARM_BETA_CHECKLIST.md`](../qa/ARM_BETA_CHECKLIST.md)). When the first one is made, record which
   system builds it and whether V8's control-flow integrity is on in the result: on a Linux machine
   that builds ARM64 Windows, the part of the patch that predates this range applies.
3. **Licences** (ROADMAP **L.1**). The 18 lines this range adds to the withheld
   `thorium-build-config-and-simd.patch` are upstream's commit `e8fed38` by Alexander Frick. The
   patch's licence question is older and not changed by them.
4. **The next audit** starts at `efc0fffc256e7402ad4c3dc38ae1e5754221c03d`: when the pin in
   `source/UPSTREAM.json` moves, run the commands of section 3 from that commit to the new one.

## 9. For the release notes

Six lines a user can read. They are not wired into the release tools yet.

- Built on Thorium's patch series as of 2026-11-08. Every change Thorium made since the version
  audited before (18 commits, 66 files) was checked by Thoron's audit tools and read by a person.
- Nothing hidden came in: no program files, no new update or tracking addresses, no keys or passwords.
- No protection was switched off. The sandbox, certificate checks and the checks on extensions from
  the Chrome Web Store are unchanged.
- New and off by default: an "Install CRX file" button on the extensions page in developer mode, and
  the flag "Allow Third-Party Extension Downloads". Leave that flag off unless you trust the site:
  with it on, any website can offer you an extension that the Web Store has not checked.
- Two more new flags: "Instant Menu Show" (off) and "Show Full Download URLs" (on, as before).
- Thorium's Android-only and macOS-only changes are not part of Thoron.
