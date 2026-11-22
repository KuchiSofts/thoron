# Security releases (ROADMAP S.9)

The runbook for getting a security fix to Thoron's users quickly, written so that one maintainer can
follow it from the first notice to the draft release. The targets are those of the
[release policy](../../ROADMAP.md#release-policy) (G2):

- **7 days** from a Chrome release that fixes a bug exploited in the wild to the Thoron release;
- **14 days** from a new Chrome major version.

Status: written 2026-11-16; first drill 2026-11-17 (section 8). There is no public release yet, so
the release step still lacks its keys (ROADMAP **P2.11**); the steps that depend on them say so. What a
fix must not break is in the [threat model](THREAT_MODEL.md).

## 1. What to watch

| Source | What it tells | How often |
|---|---|---|
| Chrome Releases, the "Stable Channel Update for Desktop" posts (https://chromereleases.googleblog.com/) | The new version, the security fixes with CVE and severity, and whether an exploit exists in the wild | Daily |
| Chromium's release tags (`git ls-remote --tags https://chromium.googlesource.com/chromium/src "refs/tags/<major>.*"`) | The exact version to build | When a post appears |
| Upstream Thorium (https://github.com/Alex313031/thorium, https://github.com/gz83/thorium) | A refreshed patch series for a new Chromium | Weekly, and at every Chrome major version |
| Thoron's private vulnerability reports (the repository's Security tab) | Problems in Thoron's own code; [`SECURITY.md`](../../SECURITY.md) promises an answer within 72 hours | Daily |
| A catalogue of vulnerabilities known to be exploited, such as the one CISA keeps | A second signal that a CVE is exploited in the wild | During triage |
| Advisories for what Thoron adds: the Rust crates of Thoron adblock (pinned in `Cargo.lock`, vendored by `tools/build/rust_crates.py`) and the pinned uBlock Origin package its scriptlets come from (https://github.com/gorhill/uBlock) | A fix Thoron has to pick up itself | Weekly |

The watch is a person looking, every day. Nothing automatic exists yet. Proposed: a scheduled check
that compares the current stable Chromium version with the one in `source/UPSTREAM.json` and opens an
issue when they differ; it needs no secret. The feed addresses and the catalogue's address are confirmed when the
watch is set up; this page was written without network access.

## 2. Triage

Decide on the day the notice arrives, and write the decision down.

| Class | What it is | Target | Path |
|---|---|---|---|
| A | A Chrome stable update that fixes a bug exploited in the wild, in code Thoron ships | Released within 7 days of the Chrome post (G2) | Fast track, section 3 |
| B | A new Chrome major version | Released within 14 days (G2) | The method of [`M158_REBASE.md`](../build/M158_REBASE.md), then section 3 from step 6 |
| C | A Chrome stable update with Critical or High fixes, none known to be exploited | Proposed: the next release, 14 days at most | Section 3, with nothing deferred |
| D | A Chrome stable update with Medium or Low fixes only | The next regular release | The normal release |
| E | A vulnerability in Thoron's own code: updater, import, Thoron adblock, Thoron M-Notifier, packaging, Thoron's patches | An answer within 72 hours, a fix within 90 days at the latest (`SECURITY.md`). Proposed: the speed of class A when a web page or the network can trigger it | A private advisory until the release is out; section 3 |
| F | A vulnerability in something Thoron takes from others: a Thorium patch, a vendored crate, the pinned uBlock Origin package | By severity, as A, C or D | Coordinate with its authors (`SECURITY.md`, "What goes where"), then section 3 |

Questions that decide the class:

1. **Is the fixed code in Thoron's build?** A fix only for Android, iOS, ChromeOS or macOS, or for a
   part the release configuration leaves out ([`RELEASE_ARGS.md`](../build/RELEASE_ARGS.md)), does not
   apply. In doubt, it applies.
2. **Does the post say an exploit exists in the wild?** Then it is class A, whatever the severity.
3. **Will the patch series still apply?** Step 4 answers this in minutes, before any time is planned.

Record: one issue per security release ("Security release: Chromium `<new version>`") with the class,
the CVEs, the date of the Chrome post (day 0) and the decision. Class E and F stay inside the private
advisory until the release is published.

## 3. Fast track

Day 0 is the date of the Chrome post. Proposed budget: source and build done by day 3, checks by day
4, the draft with the owner by day 5, two days left for review and trouble. On the reference machine a
build takes about 2.5 hours per variant ([`BUILD_BUDGET.md`](../build/BUILD_BUDGET.md)), so the time
goes to patches that no longer apply, not to compiling.

A fast-track release carries the Chromium update and nothing that has not been verified. When `main`
holds unreleased work that has not passed every check of section 4, build from the last release plus
the update (proposed).

Commands are run from the repository root in the build window of
[`docs/build/WINDOWS.md`](../build/WINDOWS.md); `<...>` are placeholders.

**Start**

1. Note day 0, the new Chromium version and the list of fixes. Write `security.json` and, when a fix
   is exploited in the wild, `highlights.md` (section 5). Chrome lists the CVEs in the post of a full
   stable release; a beta or early-stable post lists none. An update taken before the full stable post
   (as the drill of 2026-11-17 did) goes without `security.json`, and the notes say that Chrome names
   the fixes when the version reaches stable.
2. Open the tracking issue. Check the machine:
   `py -3 -I tools\build\pipeline.py preflight --root <build root> --need-gb 250`.

**Source**

3. Fetch Chromium at the new tag into a fresh checkout folder (`WINDOWS.md`, section 5, with the new
   tag in `.gclient`; about 10 minutes and 27 GB on the reference machine). `chrome\VERSION` must read
   the new version.
4. See how Thoron's series fits, without changing the checkout:

   ```powershell
   py -3 -I tools\build\rebase_report.py --tree <build tree> --src <chromium src> `
       --chromium <new version> --out <scratch>\fit.md
   ```

   The build tree is the work tree `source/` was exported from, or the output of
   `tools\build\source_tree.py materialize`. Exit status 1 means a patch is rejected or missing.
5. Refresh what does not apply, in the work tree. A refreshed patch keeps its `Origin:`, `Author:`
   and `License:` lines:

   ```powershell
   py -3 -I tools\legal\patch_headers.py lint --tree <build tree> --research tools\legal\patch_origins.tsv
   ```

   Proposed: a patch that cannot be refreshed in time, and that neither security nor people's data
   depends on, is left out of this release and named under "Known issues".
6. Take nothing else from upstream in a fast track. If a Thorium change must come in, audit it first
   and have a person review every finding (ROADMAP **S.1**):

   ```powershell
   py -3 -I tools\audit\audit_diff.py <upstream clone> <old commit> <new commit> --section all --strict
   ```
7. Apply to the new checkout, as in `WINDOWS.md`, sections 6 and 7:

   ```powershell
   py -3 -I tools\build\pipeline.py apply --tree <build tree> --src <chromium src> --profile avx2 --log <log file>
   py -3 -I tools\build\thoron_identity.py --src <chromium src>
   py -3 -I tools\build\rust_crates.py --src <chromium src>
   ```

   `apply` must end with `0 rejects`. It applies with Git's `core.autocrlf` off whatever the PC says
   (Git for Windows turns it on, and then `git apply` writes CRLF ends and can damage a binary file a
   patch adds). Anything applied by hand gets `git -c core.autocrlf=false apply`. To start over, reset
   the main checkout **and** the nested repositories the series patches (`third_party/ffmpeg`, `v8`,
   `third_party/search_engines_data/resources`, `third_party/zstd/src`); a reset of `src` alone leaves
   their half-applied state behind. When Thoron's own patches no longer fit (`ks-native-adblock-*`),
   apply them once with less context (`-C2`), then make them again from the new tree. Upstream's `setup.py`
   stops at the first patch that does not apply, before its last two steps: upstream's string step (the
   product's name and Thorium's translations in the string files) and the copies of the processor
   profile. After patches fixed by hand, run them from `setup.py` itself
   (`setup.apply_grd_rebase(<tree>, <src>)` and `setup.execute_profile_plan(setup.profile_copy_plan("avx2",
   <tree>, <src>))`), then Thoron's identity step (`tools/build/thoron_identity.py`), which refuses a tree
   where upstream's string step has not run. To make the patches:
   `THORON_SRC=<new chromium src> py -3 -I <build root>\logs\make_ks_adblock_hook.py --write`.
8. Set the versions. A new Chromium starts at rebuild 0; a Thoron-only fix on the same Chromium is the
   next rebuild. Thoron's own version is the next one after the newest release tag; `next` prints it
   (fetch the tags first):

   ```powershell
   py -3 -I tools\release\version.py next --repo .
   py -3 -I tools\release\version.py set --src <chromium src> --rebuild 0
   py -3 -I tools\release\version.py rebuild --src <chromium src> --to <n>
   py -3 -I tools\release\version.py thoron --src <chromium src> --to <next 0.MINOR.PATCH>
   ```

9. Put the source the release is built from into `main` (ROADMAP **P2.25**), with the `Security` line
   in `CHANGELOG.md` (section 5) in the same change:

   ```powershell
   py -3 -I tools\build\source_tree.py export --tree <work tree> --base <upstream commit> --out source `
       --chromium <new version> --repository <upstream repository>
   py -3 -I tools\build\source_tree.py verify --upstream <upstream clone> --source source
   ```

   The checks of `.github/workflows/checks.yml` must pass on that change.

**Build**

10. Compose and check the release configuration, then build Windows x64 AVX2 first (`WINDOWS.md`,
    section 8). The other variants follow in the order of `BUILD_BUDGET.md`.

    ```powershell
    py -3 -I tools\build\release_args.py compose --platform win --upstream <upstream args file> `
        --source "<upstream> <commit> <args file>" --out <out dir>\args.gn
    py -3 -I tools\build\release_args.py check --platform win --args <out dir>\args.gn
    gn gen <out dir>
    autoninja -j 12 -C <out dir> chrome mini_installer
    ```

11. Write the build record: `py -3 -I tools\build\pipeline.py buildinfo ...` (`WINDOWS.md`, section 9).
    It names the source of the build: the source tag (`v<Thoron version>`), the commit under it and the
    Chromium tag. Build from a tree with nothing uncommitted, or step 13 refuses the record.

**Check**

12. Run every check of section 4.1.

**Release**

13. Package, write the notes and sign, in one command. `prepare` stops on a release configuration, a
    version or installer contents that fail, and never overwrites a release folder. It also stops when
    Thoron's version is not the next one after the newest release tag, when the build record does not
    name its source (step 11) or the build tree has no whole text of the GPL, when the build's browser
    folder cannot become the portable package, when `CREDITS.md` or `NOTICE` are not current, when
    `CHANGELOG.md` is not in its short form or lists no change for the release, and when the wiki pages
    fail the linter or do not name the version. `--security` and
    `--highlights` put the fixes and the hand-written opening into `NOTES.md` (section 5).
    `--manifest-key` makes the signed update manifest ([`MANIFEST.md`](../update/MANIFEST.md), section
    10); `--critical` goes with class A and E.

    ```powershell
    py -3 -I tools\release\release.py prepare --src <chromium src> --out <out dir> --platform win `
        --variant win-x64-avx2 --previous <last build version> --buildinfo <out dir>\BUILDINFO.json `
        --dist <release folder> --repo . --since <last release tag> --chromium-old <old version> `
        --security security.json --highlights highlights.md --minisign-key <key file> `
        --sandbox-evidence <sandbox_check.py's evidence file> `
        --manifest-key <key file> --manifest-public-key <public key> --gh-repo KuchiSofts/thoron `
        --previous-manifest <the last update.json> --critical
    ```

    - **Several variants** (AVX2 and SSE4, later ARM64): `prepare` each into a folder of its own, from
      the same commit and with the same options, then make the release from them:
      `py -3 -I tools\release\release.py combine --from <avx2 folder> --from <sse4 folder> --dist <release folder>
      --manifest-key <key file> --manifest-public-key <public key> --minisign-key <key file>`. It refuses
      folders of different builds or commits, of the same variant, with notes or manifests that differ
      beyond their files, or with a file that is not what their `SHA256SUMS` lists; it makes one
      `SHA256SUMS`, one set of notes listing every file, and one update manifest naming every variant,
      signed, and `publish` then takes that folder.
    - Leave `--highlights` out when there is nothing to say by hand, and `--critical` out for class C
      and D. A `security.json` that is not a list of fixes stops `prepare` before anything is packaged.
    - `--previous-manifest` is the `update.json` of the newest release. The very first manifest is made
      with `--first-manifest --min-updater-version <build version>` instead.
    - The release folder also gets the portable `.zip` (made from `<out dir>\Chrome-bin`, or the folder
      `--chrome-bin` names) and the licence bundle `thoron-<build version>-licenses.zip` with the GPL
      text; both are in `SHA256SUMS`, and the manifest names the portable package beside the installer.
    - The notes' "Thoron changes" are the lines of `CHANGELOG.md`: the section of the version when there
      is one, else what waits under `[Unreleased]`.
    - `prepare` asks GitHub (read only, with `gh`) for upstream's contributors and compares them with
      the list in `CREDITS.md`; `--contributors <saved list>` gives it a saved list instead. When the
      list is out of date, run `tools\credits\contributors.py`, commit, and run `prepare` again. It
      never rewrites `CREDITS.md` or `NOTICE` itself.
    - Key files stay outside the repository, the build tree and the release folder; `prepare` refuses
      one that is inside. Without `--manifest-key` it makes no manifest and says so, and step 14 then
      refuses the release.
    - Read `<release folder>\NOTES.md` before going on.

14. Create the draft. It refuses a release without a signed `SHA256SUMS`, with a file that
    `SHA256SUMS` does not list, with a build record whose source tag is not the draft's tag, without
    the licence bundle and its GPL text, or with an update manifest that is missing, unsigned, does not
    verify with the public key, or names other files than the folder's. The draft's tag is put on the
    commit the build record names, so that commit must be on GitHub.

    ```powershell
    py -3 -I tools\release\release.py publish --dist <release folder> --version <Thoron version> `
        --gh-repo KuchiSofts/thoron --manifest-public-key <public key>
    ```

    `<Thoron version>` is the `0.MINOR.PATCH` of step 8, as `prepare` printed it: the draft's tag is
    `v<Thoron version>`, the tag in the manifest's download addresses.
15. **The owner reads the draft and publishes it.** Nothing else publishes a release.
16. Afterwards: publish the wiki (`py -3 -I tools\docs\publish_wiki.py --repo KuchiSofts/thoron`; step 14
    prints the command and never runs it, and `--dry-run` shows what would change),
    publish the advisory (class E and F), close the issue, and fill in a row of section 8.

## 4. Checks

### 4.1 Never skipped

| Check | Tool | Passes when |
|---|---|---|
| Unit tests, docs and privacy linter, binary policy | `py -3 -m unittest discover -s tools -t .`, `tools/docs/check_docs.py --private`, `tools/audit/binary_policy.py` | All three report no problem, locally and in the checks workflow |
| The release is built from what `main` holds | `tools/build/source_tree.py verify` | The tree hash matches the one on record |
| Every patch names its origin, author and licence | `tools/legal/patch_headers.py lint` | Nothing is reported |
| Anything taken from upstream is audited | `tools/audit/audit_diff.py --strict` | A person has reviewed every finding |
| Release configuration | `tools/build/release_args.py check` (also run by `release.py prepare`) | No difference from Thoron's choices, no Google API keys in `args.gn` |
| Version | `tools/release/version.py check` (also run by `release.py prepare`) | Higher than the last release |
| Sandbox (ROADMAP S.5) | `tools/qa/sandbox_check.py --evidence <file>`, given to `release.py prepare --sandbox-evidence` | Every renderer, the GPU process and each utility process that declares a sandbox run sandboxed as Windows itself reports it, `chrome://sandbox` and `chrome://gpu` agree, and the control run with `--no-sandbox` is caught; the evidence is of this build. It stays with the build's records and is not published |
| Network contacts (ROADMAP S.10) | `tools/qa/netlog_hosts.py --seconds 240 --json <file>` on the build, given to `release.py prepare --network-report` | Every host a fresh profile of this build contacts is named in `docs/security/NETWORK.md`; the report is of this build and measured as a person starts it. A new host means the page is brought up to date (what asks, why, how to switch it off) before the release |
| Sandbox on Linux (ROADMAP S.5) | `tools/qa/linux_apparmor_vm_check.py --evidence <file>`, given to `release.py prepare --sandbox-evidence` for a Linux release | On Ubuntu's own kernel with AppArmor (its cloud image in a VM): the `.deb`'s `chrome://sandbox` reads "You are adequately sandboxed", the portable copy without a profile refuses to run without its sandbox, and with the README's profile it is sandboxed; the evidence is of this build. It stays with the build's records |
| The product's name, no build for tests | `release.py prepare` | The English strings name Thoron and none of the About page's lines name Chromium; the browser does not trust the updater's test key |
| Thoron version | `release.py prepare` (the next one: `tools/release/version.py next`) | The next version after the newest release tag; `0.1.1` when there is none |
| Source and licences (ROADMAP **L.2**) | `release.py prepare` and `publish` | The build record names the source tag, its commit and the Chromium tag; the licence bundle holds the GPL text |
| Credits (ROADMAP **L.3**) | `release.py prepare` | The contributor list in `CREDITS.md` is the one made now; every origin and licence of the patch inventory is in `CREDITS.md` and `NOTICE` |
| Changelog and wiki (ROADMAP **D.10**, **D.9**) | `release.py prepare` | `CHANGELOG.md` is in its short form and lists the release's changes; the wiki pages pass the linter and name the version |
| The build starts, the sandbox is in force, nothing crashes | `tools/build/smoke.py` | `SMOKE: PASSED` |
| The last release's updater installs this one (THREAT_MODEL U14) | `tools/qa/portable_update_check.py --previous <the last release's portable .zip> --report <file>`, given to `release.py prepare --update-check` | `PORTABLE UPDATE CHECK: PASSED`, from the last release to this build; `prepare` refuses a release after the first without it |
| Package contents | `tools/release/package_audit.py` (also run by `release.py prepare`, for the installer and the portable package) | The Thoron program is there; no Widevine, no Thorium-named file; no profile data in the portable package |
| A real profile survives the update (ROADMAP **Q.7**) | `tools/qa/profile_rehearsal.py` on a copy of a real profile | The last line says the new build kept everything |
| Signature | `release.py prepare --minisign-key`, then `minisign -Vm SHA256SUMS -P <public key>` | The signature verifies; `publish` refuses a release without one |
| Update manifest | `release.py prepare --manifest-key`, then `tools/update/manifest.py verify update.json --public-key <public key>` | The signature holds; `publish` refuses a release whose manifest is missing, unsigned, does not verify or names other files |
| A person publishes | The draft on GitHub | The owner has read the notes and the file list |

A check that fails stops the release. A fix exploited in the wild does not change that: an update that
damages a profile or ships without its sandbox is worse than a late one.

### 4.2 May wait until after a class A release

- The online benchmark suites and the soak test (ROADMAP **Q.1**, **Q.4**). The offline run of
  `tools/qa/bench.py` takes minutes and is still compared with the last release.
- The long verification of features the update did not touch. What it finds becomes a known issue or
  the next release.
- The SSE4, Linux and ARM64 variants: they follow the first variant as they pass the same checks.
- Wiki pages other than the version.

Each thing left out is named in the tracking issue and done within 14 days.

## 5. How the release notes name the fixes

- **`security.json`** is given to `release.py prepare --security` (and read the same way by
  `tools/release/changelog.py`): a list of
  `{"cve": "CVE-YYYY-NNNNN", "severity": "High", "title": "..."}`, one entry per fix, copied from the
  Chrome Releases post. The severity is Chrome's own word: `Critical`, `High`, `Medium` or `Low`. The
  tool sorts by severity, then by CVE, and refuses a file that is not such a list: no fix at all, a
  missing `cve`, `severity` or `title`, another severity, or a value of more than one line.
- **The notes** then read "Chromium `<old>` to `<new>`", a link to Chrome Releases, and under
  "Security fixes" one line per fix: `CVE-YYYY-NNNNN (High): <title as in the post>`.
- **"Exploited in the wild"** has no field in `security.json`. It is said in the first sentence of
  `highlights.md`, the hand-written opening given to `prepare --highlights`, with the CVE: "Security
  release. Chromium `<new>` fixes CVE-YYYY-NNNNN, which is being exploited in the wild." Proposed: an
  optional `"exploited": true` that the tool turns into a mark on the line.
- **`CHANGELOG.md`** gets one line under `### Security`: the Chromium version, the number of fixes
  and the CVE that made it urgent.
- **Titles and numbers are never reworded**, and nothing in the notes explains how a bug is
  exploited. Fixes the post lists without a CVE are counted, not described.
- **Names of the people who found a bug** are in the Chrome Releases post; the notes link to it and
  do not copy them.
- **A vulnerability in Thoron's own code** is named by its advisory ID, and by its CVE when it has
  one, with the severity of the advisory. The reporter is credited unless they prefer not to be
  (`SECURITY.md`). The advisory is published with the release; technical detail follows when people
  have had time to update.
- **The versions:** the Thoron version is the next `0.MINOR.PATCH`; the build version follows Chromium
  (`tools/release/version.py`).

## 6. When the target cannot be met

Say so in the tracking issue as soon as it is clear: which fix is outstanding, why, and the new date.
Proposed: when day 7 of a class A fix passes without a release, the notice is also pinned in the
repository's issues until the release is out. A missed target is recorded in section 8 with its cause,
and the cause becomes a roadmap task.

## 7. Checklist

```text
[ ] Day 0 noted; class decided and written in the tracking issue (or the private advisory)
[ ] security.json written from the Chrome Releases post
[ ] Chromium fetched at the new tag; chrome/VERSION reads the new version
[ ] rebase_report.py: no patch rejected or missing (or each one refreshed, headers kept)
[ ] Nothing else merged from upstream (or audit_diff.py --strict, every finding reviewed)
[ ] pipeline.py apply: 0 rejects; thoron_identity.py and rust_crates.py run
[ ] version.py: build version and Thoron version set
[ ] source/ exported and verified; CHANGELOG has its Security line; the checks workflow passed
[ ] release_args.py check passed; build finished; BUILDINFO written
[ ] smoke.py: SMOKE: PASSED
[ ] profile_rehearsal.py on a copy of a real profile: everything kept
[ ] bench.py (offline) compared with the last release
[ ] portable_update_check.py --previous <last release's portable .zip> --report: PASSED
[ ] release.py prepare with --security and --highlights: no problem; NOTES.md names the fixes, in-the-wild ones first
[ ] The release folder holds the installer, the portable .zip, BUILDINFO and the licence bundle
[ ] The keys unlocked from the backup for this release (key_ceremony.py unlock), locked after (lock)
[ ] SHA256SUMS signed and the signature verified
[ ] update.json signed (critical for class A and E) and verified with manifest.py verify
[ ] netlog_hosts.py --json of this build given to prepare --network-report: every host in NETWORK.md
[ ] Windows, once Thoron has a certificate: the installer built with thoron_authenticode_command_file and
    prepare given --authenticode-command: every program signed and timestamped (docs/release/SIGNING.md)
[ ] Linux: linux_package_check.py PASSED; linux_apparmor_vm_check.py --evidence PASSED, given to prepare --sandbox-evidence
[ ] Linux: apt_repo.py build from the release's .deb files; its files ready for the release `apt` (docs/release/APT.md)
[ ] release.py publish --version <Thoron version>: draft created
[ ] The owner has read and published the draft
[ ] Wiki published; advisory published (class E, F); issue closed
[ ] Deferred checks listed, with a date; section 8 filled in
```

## 8. Drills and real runs

S.9 is done when a drill meets the 7-day target. A drill takes a past Chrome stable update as if it
had just appeared, follows sections 2 to 4 to a draft that is deleted and never published, and records
the days.

| Date | Drill or real | Chromium from, to | Class | Day the draft was ready | Day published | What slowed it |
|---|---|---|---|---|---|---|
| 2026-11-17 | Drill | 158.0.8127.30 to 158.0.8127.65 | A (taken as A for the clock; the early-stable post named no fixes) | Not made: it needs the release keys (P2.11) and the licence of one patch (L.1), both the owner's; every step before it was done on day 0 | Never (a drill) | Refreshing the patch series (two patches no longer applied, Git for Windows' line ends, a newer `gnrt`) and the build itself (4 h 17 min in a new checkout) |

### The drill of 2026-11-17

Chromium 158.0.8127.65 was taken as a Chrome update that had just appeared (day 0), with Thoron on
158.0.8127.30. What each step took, from the start of day 0:

| Step | Took | What happened |
|---|---|---|
| Patch series refreshed, applied, source exported (steps 5 to 7) | 49 min | 151 patches, `0 rejects` after two were refreshed: the HEVC patch had picked up links to nested repositories, and Chromium had changed `rpm/build.py` under the Linux packaging patch. Thoron's own patches were made again from the new tree. `source/` exported and verified |
| Release build, AVX2 (step 9) | 4 h 17 min | A clean build in a new checkout, beside other work on the PC |
| Checks (section 4) | about 1 h | The updater's 113 unit tests passed; the smoke test passed (JavaScript, WebGL, H.264, HEVC, AV1, JPEG XL, the sandbox on); the profile rehearsal on a copy of a real profile kept everything; in a clean Windows (`tools/qa/sandbox_install_check.py`) the build installed, started and uninstalled, and installed over a running 158.0.8127.3010 (status 30, the restart ran 158.0.8127.6500, the profile kept) |
| `release.py prepare` (step 10) | minutes | Refused, for three reasons the drill expected: one patch without a licence (L.1), no 8-hour soak report of this build, and no benchmark of it (15 minutes; not run, because a timing run beside the 48-hour soak of the previous build would be wrong) |

What the drill showed:

- The work before the draft fits in one day. The 7-day target is held by the owner's keys and by the
  soak: the draft can follow the 8-hour soak, on day 1.
- Line ends and nested repositories are now handled by the tools and described in step 7.
- Chrome's early-stable post names no fixes (step 1).
- `prepare` asks for the soak before the draft, where section 4.2 lets a class A release go first
  (open item 7).
- **The drill's build called itself Chromium** in most of its menus and pages. `setup.py` had stopped at the
  two patches fixed by hand, so its string step never ran, and Thoron's identity step, which renames
  Thorium, found almost nothing to rename. None of the checks of that day looked at the product's name;
  the About page's update states, checked the same evening (ROADMAP P3.9), showed "Chromium is up to
  date". Fixed the same day: the two steps run on the tree, the identity step run again, the browser
  built again (13 minutes); the identity step now refuses such a tree, and `release.py prepare` refuses a
  browser whose English strings do not name Thoron, or that trusts the updater's test key.
- An install for every user of the PC (`--system-level`), updated while it ran, seemed to hang in the
  clean Windows. The hang was the check's own registry read; the update itself took 16 s and works as
  Thorium's installer patch intends: it ends the running Thoron and updates in place
  ([INSTALLER.md](../release/INSTALLER.md), section 1).

S.9 stays open until a drill makes the draft.

## 9. Open items for the owner

1. **Class C target.** 14 days for Critical and High fixes that are not known to be exploited is a
   proposal; the release policy names only classes A and B.
2. **Fast track from the last release, not from `main`,** when `main` holds unverified work (section
   3). It needs a branch or tag policy for releases.
3. **Leaving a patch out of a class A release** when it cannot be refreshed in time (step 5).
4. **A public notice when a target is missed** (section 6).
5. **The watch:** by hand every day, or the scheduled check proposed in section 1.
6. **Where the signing key is while it signs** is question 2 of the
   [threat model](THREAT_MODEL.md#9-open-questions-for-the-owner).
7. **The soak test of a class A release.** Section 4.2 lets it follow the release, but
   `release.py prepare` refuses a release without an 8-hour soak report of the same build (found by
   the drill of 2026-11-17). Either the runbook asks for the soak before every release, or `prepare`
   learns to accept a class A release (`--critical`) with the soak named as owed within 14 days.
