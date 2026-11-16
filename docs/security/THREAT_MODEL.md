# Threat model: updater, import and portable encryption (ROADMAP S.2)

What can go wrong in the three parts of Thoron that handle updates and people's data, who could make it
go wrong, and what stops them: the updater (ROADMAP **P3**, **P4**), the import from other browsers
(**P3.13** to **P3.18**, **P4.8**) and the passphrase encryption of portable profiles (**P4.9**,
**P4.10**).

Status: written 2026-11-16 from the design, before the code exists. Not reviewed yet (section 10). It
follows the [main design](../design/2026-11-07-thoron-design.md#7-smart-update-system-installed-and-portable)
(sections 7 and 11) and the [release program](../design/2026-11-12-release-program.md#9-security-review)
(section 9), and changes when they change.

How to read the tables:

- **Source** says where a mitigation comes from: *design* (the design commits to it, with its section)
  or *proposed* (the design is silent; this page proposes it, and the reviewer and the owner decide).
- **Stage and test** names the roadmap stage that builds the mitigation and the check in its "Done
  when" that proves it. "No test yet" marks a gap; the gaps are collected in section 8.

## 1. What is protected

| ID | Asset | What must hold |
|---|---|---|
| A1 | The profile, `User Data`: passwords, cookies, history, bookmarks, sessions, extensions | Never lost, never changed by an update or an import, readable only by its owner |
| A2 | The installed program (the application folder, or the portable folder) | Only code that Thoron signed runs |
| A3 | The release signing key (Ed25519), later the APT key and a code signing certificate | Never leaves its offline store; can be replaced when lost or stolen |
| A4 | The public key compiled into the browser, the updater and `ThoronSetup.exe` | It is the only thing an update is trusted by |
| A5 | The profile key of a portable profile and its wraps (passphrase, remembered PC, recovery key) | Secret without the passphrase; never lost by a bug |
| A6 | The other browser's profile during an import | Byte for byte as it was |
| A7 | Privacy towards the update channel | An update check identifies nobody |
| A8 | Rollback material: the N-1 program folder and the profile snapshots | As private as the profile; intact when needed |

## 2. Who attacks

| ID | Actor | Can | Cannot |
|---|---|---|---|
| N1 | Network attacker on the path (public Wi-Fi, a router, a proxy, a middlebox whose certificate the PC trusts) | Read, block, delay, replay and change traffic | Sign for Thoron |
| N2 | Whoever controls what GitHub serves: a taken-over account, a rogue collaborator, the host itself | Publish, replace or remove any file of a release | Sign for Thoron: the key is not on GitHub |
| N3 | Thief of the signing key | Sign anything | Deliver it, without also being N1 with broken TLS, or N2 |
| L1 | A program running as the same user (malware, an injected module) | Everything the user can: read and write the profile and the program | Nothing more through Thoron: Thoron never raises its rights |
| L2 | Another account on the same PC, or a sandboxed process | Read what is world-readable, write to shared folders | Write to the user's own folders |
| P1 | Someone who holds a portable drive (lost, stolen, or borrowed and returned), or a PC that "remembers" a profile | Read and change every file on it, guess the passphrase offline | Unlock without the passphrase, the recovery key or a remembered PC |
| P2 | A hostile PC a portable drive is plugged into | Record keys and memory while the profile is unlocked | - |
| F1 | The author of a crafted file: a profile folder, a session file, a key file, a CSV | Make Thoron's parsers read anything | - |
| U1 | The user by mistake: a forgotten passphrase, an import while the source runs, a rollback not understood | - | - |
| M1 | The maintainer side: a mistake in release tooling, a compromised build machine | Ship a bad release | - |

## 3. Trust boundaries

1. **Network to updater.** Everything fetched is untrusted until the manifest's signature holds, and
   every package until its size and SHA-256 match the signed manifest. HTTPS is transport, not proof.
2. **Updater to disk.** The updater writes to the application folder and the snapshot folder. It
   never writes inside `User Data`.
3. **User rights.** Installer, updater and import run as the user. Nothing asks for administrator
   rights, so there is no higher right to borrow.
4. **Foreign profile to import.** Another browser's files are input from outside: read only, copied,
   verified, then parsed by Thoron's own parsers.
5. **Portable drive at rest.** Every file on the drive, the key file and the program included, can be
   read and changed by whoever holds it. Only the passphrase, the recovery key and a remembered PC's
   OS store are outside the attacker's reach.
6. **Portable drive in use.** The PC it is plugged into is trusted while the profile is unlocked.
7. **Signing key to the rest.** The private key is outside the repository, GitHub and every log. Where
   it is while it signs is open question 2.

## 4. Updater

| ID | Threat (actor) | Mitigation | Source | Stage and test |
|---|---|---|---|---|
| U1 | A forged or altered update manifest (N1, N2) | Detached Ed25519 signature, checked with the compiled-in public key before a byte of the manifest is parsed; anything unsigned is refused, by the updater and by `ThoronSetup.exe` | design 7.2 | P3.2: flipping any byte fails verification. P3.3: unit tests reject bad signatures. P3.19: refuses a manifest that does not verify |
| U2 | A forged, altered, truncated or oversized package (N1, N2) | Size and SHA-256 come from the signed manifest; a file that does not match is never installed. A delta names the old and the new SHA-256 of every file and falls back to the full package on any mismatch | design 7.2, 7.3 | P3.4: corrupted and truncated downloads rejected. P4.1, P4.2: byte-identical result; a mismatch falls back. Stopping a download at the signed size: proposed, no test yet |
| U3 | Downgrade: an old, validly signed manifest is replayed to install a vulnerable version (N1, N2) | Only a higher build version installs; an older manifest is rejected. The only way back is the local rollback command (U11) | design 7.2 | P3.3: unit tests reject older manifests |
| U4 | Freeze: the current manifest is served for ever, or new ones are blocked, so the browser never learns of a fix (N1, N2) | The manifest carries `expires`. When the only manifest it can get has expired, the updater says "cannot verify updates", never "up to date" | design 7.2 | P3.3: "cannot verify" on an expired manifest. P4.5: a replayed old manifest triggers that state |
| U5 | The PC's clock is wrong or set back, so an expired manifest looks valid | Clock-skew tolerance. Proposed: the updater remembers the newest release date it has verified and refuses a manifest older than that | design 7.2, proposed | P4.5 for the tolerance. The remembered date: no test yet |
| U6 | The signing key is stolen (N3) | The key is offline, with encrypted backups whose restore is tested; a rotation counts only when the old key signed it; a second offline key can replace a lost or stolen one | design 7.2, release program 9 | P2.11: backup restore tested by sign and verify. P4.7: a rotation drill passes end to end. Residual 1, question 1 |
| U7 | The GitHub account or a release is taken over (N2) | It can publish files but not sign them. A release is a draft until the owner publishes it; `main` is protected | design 8, release program 9 | P2.12: publishing needs the owner and refuses an unsigned release. P2.26. Residual 2 |
| U8 | A checked file is swapped before it runs (L1, L2) | The download goes to a folder only the user can write, and the checked file stays open until it runs. Every staged file is verified in `<new>.staging`, then the folder is renamed in one step | release program 4, design 7.3 | P3.5: killing the updater at any step leaves a launchable browser. A swap between check and run: proposed test for P3.4, none yet |
| U9 | Hostile bytes reach a parser: manifest JSON, the delta container, Zucchini input, entries named with `..` or an absolute path (N1, N2, N3) | Nothing is parsed before its signature or hash holds. Proposed: every path in a package or delta must stay inside the staging folder, links are refused, and the manifest and delta parsers are fuzzed as the import parsers are | design 7.2, proposed | P3.3: malformed JSON rejected. Path checks and fuzzing: no test yet (P3.5, P4.1) |
| U10 | A file signed for another purpose is taken for a manifest: another channel or variant, `SHA256SUMS`, the ad-blocking resources of P5.23 | Channel and variant are inside the signed manifest and are checked. Proposed: every signed format begins with a line naming its kind, as the P5.23 file does, or each purpose has its own key | design 7.2, proposed | P3.1: the schema validator has invalid samples. A cross-format test: none yet |
| U11 | An update or a rollback loses data (U1, bugs) | The updater never writes inside `User Data`. Before a major-version jump the critical profile files are snapshotted and verified (hashes, SQLite integrity), the last 2 kept. Rollback restores N-1 and the snapshot only after a warning and a confirmation. Proposed: no field of a manifest can ever start a rollback or a downgrade | design 7.6, proposed | P3.6: profile byte-identical after an update. P3.7: snapshot verified on a copy of a real profile. P3.8: the round trip restores byte-identically. P3.20, Q.7: `tools/qa/profile_check.py` reports 1:1 |
| U12 | The update check is used to track people (N1, N2) | A static release-asset address, no identifier, no telemetry; updates can be switched off. Proposed: no cookies, no referrer, and the installed version is compared on the PC, not sent | design 3, release program 4 | S.10: `tools/qa/netlog_hosts.py` lists only the documented hosts. What the request carries: no test yet (P3.3) |
| U13 | The updater becomes a way to gain rights (L1, L2) | No administrator rights anywhere: a per-user task (Limited), a systemd user timer, no service, no UAC or sudo prompt. On `.deb` installs only apt changes program files, and root scripts never read a profile | design 7.5, 7.5a | P3.10: no prompt ever appears; portable leaves no registry or task traces |
| U14 | A broken updater release cuts everyone off from updates (M1) | The updater updates itself through the same signed manifest (`min_updater_version`); full installers and `ThoronSetup.exe` stay downloadable. Proposed: before a release is published, the previous release's updater installs it | design 7.4, G3, proposed | P4.6: an old updater upgrades itself first. P3.20: an installed release updates itself to the next; repeating it for every release: no test yet |
| U15 | The APT repository serves a changed package list (N1, N2) | A signed `InRelease`, with the key scoped by `signed-by` | design 7.5a | P2.10: a tampered `InRelease` is rejected |

Residual risks, stated plainly:

1. **A stolen key plus control of delivery.** A thief who also controls what GitHub serves, or who
   breaks TLS to it, can ship anything to every installed copy until a new key reaches it. The rule "a
   rotation counts only when the old key signed it" does not stop a thief, who holds the old key too;
   only the second offline key does. What stands in the way: the key is offline, its file is
   password-protected (minisign's default), and delivery over HTTPS is a second barrier.
2. **The first install has no trust anchor.** `ThoronSetup.exe` and a first full installer are
   protected by HTTPS and by the person checking `SHA256SUMS` by hand
   ([README, "Verifying downloads"](../../README.md#verifying-downloads)), with a public key published
   by the same account. Until binaries are code-signed (**S.8**), a taken-over account could replace
   them for new users. Installed copies are not affected (U1, U2).
3. **The freeze window.** Until `expires` passes, a blocked copy believes it is current. How long that
   is has not been decided (question 3).
4. **Same-user malware (L1)** can replace Thoron's files, its scheduled task and its profile. The
   updater does not defend against it, and adds nothing to it.
5. **A portable folder has no file permissions** on FAT or exFAT media: any program on the host, and
   anyone who holds the drive, can change the program. A folder can be compared byte for byte with the
   release ZIP: `tools/audit/compare_release.py`.
6. **Snapshots and the N-1 folder are second copies** of what the profile holds. Proposed: they get the
   profile's permissions, are deleted when they leave the last-2 window, and are deleted by an
   uninstall with "Also delete browsing data" ticked.
7. **A rollback reinstalls an older version** at the person's request. Proposed: the About page then
   says the version is outdated and keeps offering the newest.
8. **System-level installs are not covered.** A program in a user-writable folder that a task with
   higher rights runs would be a way to gain rights. The per-user model needs a new review before a
   system-level install gets an updater (**P2.19**).

## 5. Import

| ID | Threat (actor) | Mitigation | Source | Stage and test |
|---|---|---|---|---|
| I1 | The import changes or damages the other browser's data (bugs) | Copy, never move. The source is only read; every copied file is compared by SHA-256; SQLite integrity is checked on the copy, never by opening the source database (a database opened in place can be written to) | design 7.7, 7.7a; the "on the copy" rule is proposed wording | P3.14: every test source's hashes identical before and after. The command-line tool `tools/migrate/import_profile.py` already copies and compares hashes this way, with tests; it has no SQLite check |
| I2 | The copy is torn: the source browser is running or still writing | The source must be closed: Thoron asks and never force-closes; the running browser's lock file refuses the import; a browser started during it voids it. Proposed: a profile written a moment ago is refused too, the lesson of Q.7 | design 7.7a, proposed | P3.13: the prompt. `import_profile.py` tests cover the lock. The "written a moment ago" refusal exists in `tools/qa/profile_rehearsal.py`; in the engine: no test yet |
| I3 | A crafted profile attacks the parser: SNSS session files, `sessionstore.jsonlz4`, SQLite files, `Preferences` (F1) | Thoron's own parser, golden files from each browser, fuzzing. Proposed: the parsers run in a sandboxed utility process or in memory-safe code, never inside the installer, with limits on sizes and counts so a small compressed file cannot grow without bound | design 7.7a, proposed | P3.15: golden files restore exactly; 24 h of fuzzing finds no crash. 2026-11-16, the command-line version: the SNSS reader `tools/migrate/sessions.py` is memory-safe Python with limits on the file size (64 MB), the commands, windows, tabs, groups, pages of history and the work, and bad input gives only its own error (unit tests with cut, flipped and oversized files); the import leaves out of its copy every command the reader cannot use, since Chromium stops reading a session at the first one; golden files of Chrome 157, Thorium 156 and Thoron 158 come back in Thoron (`tools/qa/session_import_check.py`); `tools/migrate/fuzz_sessions.py` ran 20 minutes, 841,832 inputs, without a crash or a hang; open: the 24 h run, and the parser inside the browser (sandboxed or memory-safe). P4.8: the Firefox parser is fuzzed |
| I4 | A "profile folder" holds links or junctions that pull in files from elsewhere (F1) | Links and junctions are refused, nothing is followed, and only an empty destination is accepted | proposed; the command-line tool does it | `import_profile.py` and its tests. In the engine (P3.14): no test yet |
| I5 | The import carries over what an attacker planted in the old browser: a hostile or sideloaded extension, a changed search engine, start page or proxy (F1, L1) | A checkbox per data type, and a report of what came in. Proposed: outside the whole-profile copy from Thorium, extensions are installed again from their store by ID, unpacked ones are listed and skipped, and the report names the extensions and the search, start-page and proxy settings it brought | design 7.7a, proposed | P3.18: a report for every import. Extensions and settings: no test yet (P3.14); question 4 |
| I6 | Thoron is used to get around another browser's protection | Never. No bypass of app-bound encryption or anything like it; Chrome's passwords come only through Chrome's own export | design 7.7a | P3.17. Proposed test: Chrome 127+ passwords and cookies appear in the report as skipped, with the reason (P3.18) |
| I7 | The exported password CSV stays readable on disk | It is imported, then overwritten and deleted. Proposed: Thoron names a private local folder for the export, warns when the file lies in a cloud-synced folder, and imports and deletes in one step | design 7.7a, proposed | P3.17: the CSV is overwritten and deleted, covered by a test. Residual 1 |
| I8 | Secrets leak through side products: the report, logs, temporary copies | The report holds counts and reasons, no secrets; the log is local and holds no personal data. Proposed: temporary copies live inside the destination profile folder, with its permissions, and are deleted on success and on failure | design 7.7a, 7.5, proposed | P3.18: a test checks the report for secret values. Temporary files: no test yet |
| I9 | The import reaches another person's data on the PC | Proposed: detection looks only in the current user's own profile locations, plus a folder the person picks | proposed | No test yet (P3.13) |
| I10 | Imported passwords or cookies cannot be read afterwards | Windows: the DPAPI-wrapped key travels in the copied `Local State` (same Windows user). Linux: Thoron reads the same `Chromium Safe Storage` keyring entry | design 7.7 | P3.16: readable on GNOME and KDE test VMs. Q.7: `profile_check.py` reports 1:1 on real profiles |
| I11 | The first-run offer takes more than it shows | Import and default browser are offers; each does only what is shown; Windows' own page confirms the default | release program 6, 9 | P3.21: declining leaves the system as it was |

Residual risks:

1. **"Secure delete" of the CSV is best effort.** On an SSD, on a journaling or copy-on-write file
   system, with backups, shadow copies or a sync client, an overwritten file can survive. The UI should
   say "deleted", not promise more.
2. **Thoron's saved passwords are as protected as Chromium's, no better.** On Linux Thoron shares the
   `Chromium Safe Storage` key with Thorium and Chromium, so each can read the others' passwords. On
   Windows a per-user install protects them with DPAPI, as Chromium and Thorium do (the profile check
   of Q.7 watches that no app-bound key appears), so a program running as the user can read them.
   Accepted: it is what makes the import work.
3. **Two copies of one profile online at once** can sign each other out, and both sync as one device
   (`docs/build/WINDOWS.md`). The UI should say to keep the source browser closed as a backup.
4. **What is imported is trusted as the person's own.** Thoron cannot tell a bookmark or a cookie the
   person made from one that was planted.
5. **Session data Thoron does not understand** (Edge workspaces, Vivaldi stacks) is skipped and
   reported, never guessed.

## 6. Portable encryption

| ID | Threat (actor) | Mitigation | Source | Stage and test |
|---|---|---|---|---|
| E1 | A lost or stolen drive: the passphrase is guessed offline (P1) | A random profile key encrypts the secrets; it is wrapped by a key derived from the passphrase with Argon2id, with the parameters stored in the profile. Proposed: a floor below which stored parameters are refused (not weaker than RFC 9106's second recommended set: 64 MiB, 3 passes, 4 lanes), a higher setting calibrated on the PC that sets it up, and a minimum passphrase length | design 7.8, proposed | P4.9: security review; round-trip tests. Floor and calibration: no test yet |
| E2 | The key file is changed while the drive is out of sight: weaker parameters, or an "old format" or "not encrypted" marker, so that new secrets are written unprotected (P1) | Proposed: the wrap is authenticated encryption with the header (format version, parameters, salt) bound into it; a protected profile never carries on unprotected without a clear warning; a PC that remembers a profile also remembers that it is protected, and refuses a downgraded one | proposed | P4.9: the key-file parser is fuzzed. Downgrade tests: none yet |
| E3 | A bug makes passwords and cookies unreadable | Its own security review, fuzzing of the key-file parser, round-trip tests with a fresh OS key store, a version check, old formats readable for good. Proposed: the key file is replaced in one step with the previous one kept, and pulling the drive at any moment of setup or of a passphrase change leaves a profile that opens | design 7.8, proposed | P4.9: review signed off; round trip; fuzzing. The pulled-drive test: none yet |
| E4 | The passphrase is forgotten (U1) | Unrecoverable by design, and setup says so plainly; a printable recovery key is a second wrap of the profile key. Proposed: the recovery key is random (128 bits or more), carries a check against typing errors, is never derived from the passphrase, and setup asks to confirm it was written down | design 7.8, proposed | P4.9's round trip should include unlocking with the recovery key: not named yet |
| E5 | "Remember this PC" opens the profile to others on that PC (L1; P1 with the PC) | It is optional; the profile key is wrapped by the OS store (DPAPI, libsecret). Proposed: it is offered only where a real OS store exists, never with a plain-text fallback, and "forget this PC" removes the wrap | design 7.8, proposed | P4.9: a fresh OS key store falls back to the passphrase. The missing-store case: no test yet |
| E6 | Someone who once had the passphrase, a copy of the key file or a remembered PC keeps access after the passphrase is changed (P1) | None in the design: a passphrase change wraps the same profile key again. Proposed: a separate "new key" action that makes a new profile key, encrypts the data again and removes old wraps and snapshots | proposed | None yet; question 7 |
| E7 | The cryptography is put together wrongly, or its code is not what it claims (M1) | Proposed: values keep Chromium's existing `os_crypt` format, so only where the key comes from changes. Argon2id comes from one pinned, licence-checked and credited source (to confirm: the pinned Chromium tree seems to have none, so it must be added) and is checked against the RFC 9106 test vectors | proposed | P4.9: security review. Test vectors: no test yet |
| E8 | A web page imitates the unlock prompt | Proposed: the passphrase is asked for by the browser's own window before any page loads, never inside a tab | proposed | None yet |
| E9 | Key material is left behind: memory, the host's swap and hibernation files, crash dumps | Proposed: the passphrase is wiped once the key is derived. Crash dumps stay local and are treated as secrets ([crash triage](../qa/CRASH_TRIAGE.md)) | proposed | None yet; residual 5 |
| E10 | Adopting an upstream portable folder loses data | Copy, verify, encrypt the copy, verify that it decrypts, and only then use it; the original is untouched | design 7.8 | P4.10: the source folder is hash-identical afterwards; every password and cookie is readable. Residual 6 |

Residual risks:

1. **Only passwords and cookies are encrypted**, as the design says: what Chromium passes through
   `os_crypt`. History, bookmarks, open tabs, the cache, downloads and what sites keep in their own
   storage stay readable to whoever holds the drive, and some sites keep a login there. Setup and the
   user guide (**D.2**) must say so. A drive that must be private as a whole needs an encrypted volume.
2. **A hostile PC (P2).** Once a profile is unlocked on a PC that runs malware, everything in it is
   exposed, the passphrase included. Nothing in Thoron prevents that.
3. **A drive that was out of sight** can come back with a changed Thoron that records the passphrase:
   the folder carries its own program, and nothing on the drive can vouch for it. Compare it with the
   release ZIP (`tools/audit/compare_release.py`); code signing (**S.8**) will help on Windows.
4. **A weak passphrase** falls to offline guessing whatever the parameters are.
5. **The host's swap and hibernation files** may keep key material after the drive has left.
6. **The original of an adopted upstream folder** still holds every password unencrypted, often on the
   same drive. Thoron never deletes it (never remove user data), so the UI must tell the person to
   delete it, and that deleted files on flash media can often be recovered.
7. **"Remember this PC" on Linux** leaves an entry in that PC's keyring: an exception, chosen by the
   person, to "no trace outside its folder" (design 7.4). Question 5.

## 7. Out of scope here

| Topic | Where it is covered |
|---|---|
| Chromium's own security, the sandbox | `tools/build/smoke.py` proves the sandbox on every build; ROADMAP **S.5** |
| Code taken from upstream | The audit before every merge: [`tools/audit`](../../tools/audit/README.md), ROADMAP **S.1** |
| The repository and what it may hold | ROADMAP **P2.26**, **L.6** |
| Updates of ad-blocking lists and resources | [Native ad-blocking design](../design/2026-11-09-native-adblock-design.md), sections 8 and 12.69 (ROADMAP **P5.15**, **P5.23**) |
| Which hosts the browser contacts | [`NETWORK.md`](NETWORK.md), ROADMAP **S.10** |
| Getting a fix out quickly | [`SECURITY_RELEASES.md`](SECURITY_RELEASES.md), ROADMAP **S.9** |
| Crash dumps | [`docs/qa/CRASH_TRIAGE.md`](../qa/CRASH_TRIAGE.md), ROADMAP **Q.5** |

## 8. Mitigations without a test

S.2 is done when every mitigation is mapped to a test. These are not, today. Each one is either added
to the "Done when" of its stage in `ROADMAP.md`, or dropped with a reason, when this page is reviewed.

| Mitigation | Proposed home |
|---|---|
| U2: a download is stopped at the signed size | P3.4 (refusing a longer file is tested; stopping the download itself at that size comes with the downloader, P3.20, P4.3) |
| U5: the newest verified release date is remembered | Tested (2026-11-16): the serial of the newest accepted manifest is handed back to be stored, and an older one is `replayed` (`thoron_update_unittests`, RejectsOlderManifests); where it is stored is P3.20 |
| U8: a file swapped between check and run is refused | Partly tested (2026-11-16): a file is read with others kept from writing to it and checked again where it is used (NeverPlacesAnUnverifiedFile); between that and the start of the program, P3.20 |
| U9: paths stay inside the staging folder; manifest and delta parsers are fuzzed | Paths tested (2026-11-16, APathThatLeavesTheFolderIsRefused); fuzzing: P4.1 |
| U10: a file signed for another purpose is refused | Tested (2026-11-16): a signature over the bare bytes, without the purpose, is `bad_signature` (RejectsBadSignatures) |
| U11: no manifest field can start a rollback | Tested (2026-11-16): a manifest that names a version below the installed one is `downgrade` and hands out no package (RejectsOlderManifests); a rollback starts only from the command line or the person (`--rollback`, P3.8) |
| U12: the update request carries no cookie, referrer or version | P3.3 |
| U14: every release is installed by the previous release's updater before it is published | P3.20, release checklist |
| I2: a profile written a moment ago is refused | P3.14 |
| I3: parsers are sandboxed or memory-safe, with size limits | P3.15, P4.8 |
| I4: links and junctions are refused by the engine | P3.14 |
| I5: extensions come from their store; the report names extensions and changed settings | P3.14, P3.18 |
| I6: protected Chrome data is reported as skipped | P3.18 |
| I7: the export folder is private and not cloud-synced | P3.17 |
| I8: temporary copies stay inside the destination and are deleted | P3.14 |
| I9: only the current user's profiles are detected | P3.13 |
| E1: parameter floor, calibration, minimum passphrase length | P4.9 |
| E2: authenticated header; no silent downgrade | P4.9 |
| E3: the key file survives a pulled drive | P4.9 |
| E4: unlock with the recovery key; recovery key format | P4.9 |
| E5: no plain-text fallback for a remembered PC | P4.9 |
| E6: "new key" action | P4.9 or later |
| E7: RFC 9106 test vectors; vendored source pinned and credited | P4.9 |
| E8, E9: unlock prompt outside any tab; passphrase wiped | P4.9 |

## 9. Open questions for the owner

1. **One key scheme.** The design has two rules: a rotation counts only when the old key signed it
   (design 7.2), and a second offline key can replace a lost or stolen one (release program 9). Only
   the second helps against theft. Proposed: both public keys are compiled in from the first release;
   the first signs releases, the second is kept in another place and only ever signs a replacement of
   the first. To settle in **P2.11** and **P4.7**.
2. **Where signing happens.** `tools/release/release.py prepare` signs on the build machine
   (`--minisign-key`, `--manifest-key`, `--adblock-key`), so a key is on that machine while it signs.
   The script reads a key only from the file it is given and refuses a key file inside the repository,
   the build tree or the release folder. Either that is accepted (key on removable, encrypted media,
   present only for the signing), or `SHA256SUMS` and the manifest are carried to a machine that is
   never online, or a hardware token signs.
3. **How long a manifest is valid** (`expires`), and who signs it again when no release is due. A short
   time narrows the freeze window (residual 3 of the updater) but needs the offline key more often.
4. **Extensions in an import from another browser:** installed again from their store by ID
   (proposed), or copied as files.
5. **Portable profiles:** may "remember this PC" leave a keyring entry on a Linux host, and is one
   portable profile meant to open under both Windows and Linux?
6. **What portable encryption covers:** passwords and cookies as designed, said plainly in the UI
   (proposed), or more, which is a much larger change.
7. **The "new key" action (E6):** part of **P4.9**, or later.
8. **Who reviews.** This page needs a review to finish S.2, and **P4.9** needs "its own security
   review". Proposed: someone who did not write the code, for both.

A note for the builder, not a question: the manifest is `update-manifest.json` in the design (7.2) and
`update.json` in the release program (section 3), and the snapshot folder is still called
`Thorium Snapshots` in the design (7.6). **P3.1** and **P3.7** fix the names.

## 10. Review record

| Date | Reviewer (role) | Result |
|---|---|---|
| - | - | Not reviewed yet |
