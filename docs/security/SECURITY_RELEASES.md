# Security releases (ROADMAP S.9)

The runbook for getting a security fix to Thoron's users quickly, written so that one maintainer can
follow it from the first notice to the draft release. The targets are those of the
[release policy](../../ROADMAP.md#release-policy) (G2):

- **7 days** from a Chrome release that fixes a bug exploited in the wild to the Thoron release;
- **14 days** from a new Chrome major version.

Status: written 2026-11-16. No drill has been run yet (section 8). There is no public release yet, so
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
   is exploited in the wild, `highlights.md` (section 5).
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

   `apply` must end with `0 rejects`.
8. Set the versions. A new Chromium starts at rebuild 0; a Thoron-only fix on the same Chromium is the
   next rebuild:

   ```powershell
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

**Check**

12. Run every check of section 4.1.

**Release**

13. Package, write the notes and sign, in one command. `prepare` stops on a release configuration, a
    version or installer contents that fail, and never overwrites a release folder. `--security` and
    `--highlights` put the fixes and the hand-written opening into `NOTES.md` (section 5).
    `--manifest-key` makes the signed update manifest ([`MANIFEST.md`](../update/MANIFEST.md), section
    10); `--critical` goes with class A and E.

    ```powershell
    py -3 -I tools\release\release.py prepare --src <chromium src> --out <out dir> --platform win `
        --variant win-x64-avx2 --previous <last build version> --buildinfo <out dir>\BUILDINFO.json `
        --dist <release folder> --repo . --since <last release tag> --chromium-old <old version> `
        --security security.json --highlights highlights.md --minisign-key <key file> `
        --manifest-key <key file> --manifest-public-key <public key> --gh-repo KuchiSofts/thoron `
        --previous-manifest <the last update.json> --critical
    ```

    - Leave `--highlights` out when there is nothing to say by hand, and `--critical` out for class C
      and D. A `security.json` that is not a list of fixes stops `prepare` before anything is packaged.
    - `--previous-manifest` is the `update.json` of the newest release. The very first manifest is made
      with `--first-manifest --min-updater-version <build version>` instead.
    - Key files stay outside the repository, the build tree and the release folder; `prepare` refuses
      one that is inside. Without `--manifest-key` it makes no manifest and says so, and step 14 then
      refuses the release.
    - Read `<release folder>\NOTES.md` before going on.

14. Create the draft. It refuses a release without a signed `SHA256SUMS`, with a file that
    `SHA256SUMS` does not list, or with an update manifest that is missing, unsigned, does not verify
    with the public key, or names other files than the folder's.

    ```powershell
    py -3 -I tools\release\release.py publish --dist <release folder> --version <Thoron version> `
        --gh-repo KuchiSofts/thoron --manifest-public-key <public key>
    ```

    `<Thoron version>` is the `0.MINOR.PATCH` of step 8, as `prepare` printed it: the draft's tag is
    `v<Thoron version>`, the tag in the manifest's download addresses.
15. **The owner reads the draft and publishes it.** Nothing else publishes a release.
16. Afterwards: publish the wiki (`py -3 -I tools\docs\publish_wiki.py --repo KuchiSofts/thoron`),
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
| The build starts, the sandbox is in force, nothing crashes | `tools/build/smoke.py` | `SMOKE: PASSED` |
| Package contents | `tools/release/package_audit.py` (also run by `release.py prepare`) | The Thoron program is there; no Widevine, no Thorium-named file |
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
[ ] release.py prepare with --security and --highlights: no problem; NOTES.md names the fixes, in-the-wild ones first
[ ] SHA256SUMS signed and the signature verified
[ ] update.json signed (critical for class A and E) and verified with manifest.py verify
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
| - | - | - | - | - | - | No drill run yet |

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
