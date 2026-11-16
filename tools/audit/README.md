# Audit toolkit

Security checks that run **before every upstream merge and before every release**. These tools only
read; they never execute anything from the code or archives they inspect. They use the Python standard
library only.

| Tool | Answers | Example |
|---|---|---|
| `audit_diff.py` | What does upstream **add**? It reports binaries (including executables disguised as images), submodule and `.gitmodules` changes, CI workflow changes, network endpoints, suspicious code patterns, new flags and switches, and changes to security features. | `py -3 -I tools/audit/audit_diff.py . "$(git merge-base HEAD gz83/M158)" gz83/M158 --strict` |
| `patch_delta.py` | What changed **inside** upstream's patches? For every patch file that differs it says whether the patch still makes the same change (only context, offsets or index lines moved) or which lines it gained and lost. | `py -3 -I tools/audit/patch_delta.py . <old commit> <new commit> --show` |
| `crx_id.py` | Is a bundled extension genuine? It verifies the CRX3 **RSA signature** and checks that the signing key matches the expected extension ID. | `py -3 -I tools/audit/crx_id.py uBlock0_1.75.0.chromium.crx --expect fkgkibajhfbepljeaefdnfnegdcjomkh` |
| `binary_policy.py` | Does the repository carry only what it may? It fails on any prebuilt executable, library, package or archive (found by content, so renamed files are caught) that has no allowlist entry with its SHA-256, licence and source, and always on proprietary blobs such as the Widevine CDM. | `py -3 -I tools/audit/binary_policy.py` |
| `compare_release.py` | Is an installed or extracted copy byte-identical to the published release ZIP? It warns about any extra executable, which could be DLL side-loading. | `py -3 -I tools/audit/compare_release.py Thorium_AVX2_x.zip "%LOCALAPPDATA%\Thorium\Application" --strict` |

## `audit_diff.py`

### Built for hostile input

`audit_diff.py` is designed so a crafted change cannot hide from it:
- **File list:** taken from `git diff --raw -z`.
- **File contents:** read by blob ID. They never go through file names, and never through the
  user's diff or `textconv` settings.
- **Added lines in modified files:** taken from a blob-to-blob diff, parsed by the line counts each
  hunk header declares.
- **Line splitting:** text is split on `\n` only, so form feeds and Unicode line separators cannot
  hide code.
- **Translation files:** `.xtb` files are skipped as non-executable noise.

### Categories

| Category | Looks for | `--strict` fails on it |
|---|---|---|
| `remote_exec` | download-and-run: `curl … \| sh` (also with `sudo`), `bash <(curl …)`, `iex`/`irm`/`iwr`, `.DownloadString(`, `certutil -urlcache`, `bitsadmin`, `mshta` | yes |
| `dynamic_code` | `eval(`, `new Function(`, `shell=True`, `os.system(`, `powershell -EncodedCommand …` | yes |
| `persistence` | Run/RunOnce keys, scheduled tasks, cron, `systemctl [--user] enable`, shell rc files, autostart, sudoers | yes |
| `security_disabled` | `--no-sandbox`, `disable-web-security`, certificate bypasses, remote debugging | yes |
| `mining_telemetry` | crypto-miners and third-party analytics endpoints | yes |
| `adult_content` | adult or NSFW terms and sites in added text **and in file names** (term list stored ROT13-encoded) | yes |
| `encoded_payload` | base64 decoding and very long encoded strings | no (review) |
| `credentials` | API keys, private keys, hard-coded passwords and tokens | no (review) |
| `self_update` | update and download URLs, Omaha | no (review) |
| `flags_switches` | every `chrome://flags` entry and every command-line switch named by a string (`HasSwitch("...")`, `AppendSwitch...("...")`): each is a behaviour someone can turn on | no (review) |

`--strict` also fails on:
- any added, modified or type-changed **non-image binary**;
- any **submodule** change;
- any **`.gitmodules`** change;
- any added or changed **CI workflow or action** under `.github/workflows/` or `.github/actions/`: once
  merged it runs with this repository's token.

### Security-feature changes

The last section of the report lists every added line that touches one of these topics, whatever the
direction of the change:
- the browser's security features: Safe Browsing, site isolation, HTTPS upgrades, mixed content,
  certificate checks, the sandbox switches, CSP, CORS, cookies, download protection;
- **extension installs and their proof**: off-store installs, the CRX installer and unpacker, the
  verifier format, install policies, external and preinstalled extensions;
- **sandbox policy and hardening build flags**: files under `sandbox/`, seccomp and syscall lists,
  control-flow integrity, stack protection;
- **data at rest and downloaded files**: OS-level encryption of saved data, the password store, the
  quarantine mark on downloads;
- **installer and registry**: files under `chrome/installer/`, registry keys.

The topics in bold were added after the audit of the upstream changes for Chromium 158
([`docs/security/UPSTREAM_AUDIT_M158.md`](../../docs/security/UPSTREAM_AUDIT_M158.md)): a new opt-in
switch for off-store extension installs and a change to V8's control-flow integrity setting had
produced no line in this section.

### Network endpoints

Endpoints on hosts where anyone can publish files are reported together with the owner or bucket:
- `raw.githubusercontent.com/<owner>`, `github.com/<owner>`;
- `storage.googleapis.com/<bucket>`;
- Google Docs, Drive and Sites.

Known upstream owners are not reported.

A `--strict` failure is not automatically malicious. For example, upstream updates Google's
Widevine binaries, which `binary_policy.py` keeps out of this repository entirely. It means **a human must review each finding** before the merge or release
proceeds. Record the outcome in the pull request or release notes.

## `patch_delta.py`

Upstream is a patch series, so most of its commits change patch files, and `audit_diff.py` sees a
patch file as text: it cannot tell a line the patch adds from a line of context. A refreshed patch
differs in every hunk header although it makes the same change. `patch_delta.py` compares what each
patch does:

| State | Meaning |
|---|---|
| `same` | The patch adds and removes the same lines in the same files. Only context, offsets or index lines moved. |
| `changed` | Lines the patch adds or removes were gained or lost. `--show` prints them with the file they belong to. |
| `added`, `deleted` | The patch file is new or gone. Read a new patch in full. |

```shell
py -3 -I tools/audit/patch_delta.py . <old commit> <new commit>
py -3 -I tools/audit/patch_delta.py . <old commit> <new commit> --show other/<name>.patch
```

Both revisions may be trees, so Thoron's own copy of a patch can be compared with upstream's (the
difference then includes the attribution header Thoron adds to every patch):

```shell
py -3 -I tools/audit/patch_delta.py . <pinned upstream commit> HEAD:source/overlay --show other/<name>.patch
```

It reads the same way as `audit_diff.py`: the file list from `git diff --raw -z`, contents by blob
ID, and every hunk by the line counts its header declares, so a line that looks like a header cannot
hide a change. Lines outside the hunks (file names, modes, binary payloads, the text above the first
file) are compared too; only `index` lines and hunk headers are left out.

## Tests

```shell
py -3 -I -m unittest discover -s tools -t . -p "test_*.py" -v
```

The tests include regression cases for every evasion found in review: header-like content lines,
quoted file names, Unicode line separators, `diff.noprefix`, submodules, symlink-to-binary type
changes, disguised images, and forged CRX signatures.
