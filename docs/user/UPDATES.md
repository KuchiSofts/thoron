# Updates and rollback

## 1. In short

- **Today no build of Thoron updates itself.** Updates are checked against Thoron's release key, and that
  key is made at the key ceremony, which has not happened yet (ROADMAP P2.11). A build without the key
  asks nothing: the About page shows no update line, and Thoron contacts nobody to look for updates.
- **Until then, update by hand:** a portable copy as in [section 5](#5-update-a-portable-copy-by-hand);
  an installed Thoron by closing it, copying `%LOCALAPPDATA%\Thoron\User Data` somewhere as a backup, and
  running the newer release's installer, which replaces the program and keeps your profile.
- **Never put an older version over a newer one.** A profile that a newer Chromium version has opened
  cannot be opened by an older one. To go back, see [section 6](#6-roll-back).
- An update only replaces the program. It never deletes, moves or changes your bookmarks, passwords,
  history, tabs or extensions.

## 2. How updates work once releases are signed

This is in the browser already and covered by its unit tests. It starts working with the first release
that is signed (ROADMAP P2.11). An update of an installed Thoron from start to end is still to be tried
on a test PC (ROADMAP P3.20). For an installed Thoron on Windows:

1. **When it looks.** 10 minutes after Thoron starts and then every 5 hours, in the update mode `auto`
   (section 4), and every time you open the About page (`chrome://settings/help`).
2. **What it fetches.** Three small public files of the newest release on GitHub, from
   `https://github.com/KuchiSofts/thoron/releases/latest/download/`: `update.json` (the manifest: which
   release is the newest, and the size and SHA-256 of each of its packages), `update.json.sig` (its
   signature) and, only when a release moves to a new signing key, `update.key`.
3. **What it checks.** The signature first, before a single byte of the manifest is read. It refuses a
   manifest that is unsigned or changed, one older than a manifest it has already accepted, one that has
   expired (a manifest is good for 30 days by default and never for more than 90), one dated
   in the future (your clock may be off by up to 24 hours), and one that names a version older than yours.
4. **The download.** When the manifest names a newer release, Thoron downloads its package (a smaller
   delta package first when the release has one, the full package otherwise or when the delta fails;
   delta packages come with ROADMAP P4.1). A download is used only when its length and SHA-256 are
   exactly the ones in the signed manifest.
5. **The install.** Chromium's own installer puts the new version in place while Thoron runs, and the
   About page offers to relaunch. The new version starts with the relaunch.

**What the requests carry.** They are plain HTTPS requests for public files through the browser's own
network: no profile, no cookies or other credentials, nothing stored in the cache, no identifier and no
usage data. A redirect away from HTTPS is refused. GitHub answers with a redirect to its file host
(`objects.githubusercontent.com` or `release-assets.githubusercontent.com`). The update never opens
`User Data`. What the updater keeps (the serial number of the newest manifest it accepted, and the
statements that introduce a new signing key) is in
the browser's `Local State`, outside every profile. Details:
[NETWORK.md, section 7.1](../security/NETWORK.md#71-the-updater-roadmap-p320) and
[MANIFEST.md](../update/MANIFEST.md).

Starting Thoron with `--disable-background-networking` stops the looks it makes on its own; the About page
still looks when you open it.

## 3. What the About page says

Open it with `chrome://settings/help`. Opening it counts as asking for an update. Every line below is
covered by a unit test; in a running browser only the first one has been seen so far, because the others
need a build with a key (ROADMAP P3.9).

| The page shows | What it means |
|---|---|
| No update line | This build has no release key, as every build until ROADMAP P2.11. It does not look for updates |
| Checking | It is fetching and checking the release's files |
| Updating, with a percentage | It is downloading; at 100 % the installer puts the new version in place |
| An offer to relaunch | The new version is installed. Relaunch to start it |
| Up to date | The signed manifest names the version you have. Only this answer means up to date |
| "Thoron `<version>` is out. This copy updates by hand: close Thoron and replace everything in its folder except User Data with the new package." | A portable copy found a newer release. See [section 5](#5-update-a-portable-copy-by-hand) |
| "Thoron `<version>` is out, but not yet for this kind of computer." | The newer release has no package for your processor variant yet |
| "Thoron `<version>` needs its own installer: download it from Thoron's releases page on GitHub." | This copy's updater is too old to apply that release by itself. Install it with the release's installer |
| "Thoron cannot verify updates (`<reason>`), so it installs nothing. If this computer's date and time are wrong, set them and try again." | Something about the release files did not check out. Nothing was installed |
| "Thoron could not update: `<what went wrong>`." | The look or the download failed. Nothing was installed |

`<version>` is the Thoron version followed by the build version in brackets.

The `<reason>` in "cannot verify" is one of:

| Reason | Meaning |
|---|---|
| `bad_signature` | The signature does not match the manifest |
| `malformed` | The manifest is empty, too long, or not in the form Thoron reads |
| `wrong_channel` | The manifest belongs to another channel |
| `replayed` | The manifest is older than one this copy already accepted |
| `not_yet_valid` | The manifest is dated after this computer's clock: check the date and time |
| `expired` | The manifest is too old to tell what the newest release is |
| `downgrade` | The manifest names a version older than yours |

What went wrong, in "could not update", is one of: "the update manifest could not be fetched" (with the
network error), "an update address led away from https", "a download led away from https", "the download
folder could not be made", "no download of the release verified", "the installer of the release failed".

## 4. The update modes

| Mode | What Thoron does on its own | When you open the About page |
|---|---|---|
| `auto` (the default) | Looks 10 minutes after the start and every 5 hours. An installed Thoron downloads and installs what it finds, and the new version starts with the next start. A portable copy only looks | Looks, and an installed Thoron installs what it finds |
| `notify` | Meant to tell you that a newer version is out, and install only when you ask. Today the browser looks on its own only in `auto`, so in `notify` it looks when you open the About page | The same |
| `off` | Nothing | The same |

A look that you ask for always shows its answer, in every mode.

**Setting the mode.** A switch in Settings comes later (ROADMAP P3.20). Today the mode is set with
Thoron's updater, `thoron_update.exe`, which only the portable package holds, in its version folder. The
mode is kept in the file `update-mode` in the `Application` folder; without that file it is `auto`. For a
portable copy:

```powershell
& "<folder>\ThoronPortable\Application\<version>\thoron_update.exe" --root "<folder>\ThoronPortable\Application" --mode notify
```

Put `auto`, `notify` or `off` at the end. `--mode` with nothing after it prints the mode in use. An
installed Thoron has no `thoron_update.exe`, so it stays in `auto` until the switch in Settings comes.

## 5. Update a portable copy by hand

A portable copy does not update itself yet: its browser does it once releases are signed (ROADMAP P2.11,
P3.20). Until then there are two ways.

### With Thoron's updater (keeps the version before)

1. Download the new `thoron-<version>-<variant>-portable.zip` for the **same variant** as your copy (the
   file `variant` in your folder names it) and **check it**
   ([Verifying downloads](../../README.md#verifying-downloads)). The updater takes the file as it is given:
   checking it is your part here, as checking the signed manifest is the browser's later.
2. Close Thoron: every window.
3. In a command prompt, run the updater of the version you have (the folder `current` names), with the
   new version's number:

       "<folder>\Application\<your version>\thoron_update.exe" --root "<folder>\Application" --apply-package "<download>\thoron-<version>-<variant>-portable.zip" --version <version>

   It unpacks only the new version beside yours, puts it in place and refreshes `Thoron.exe`. The last
   lines say `done` and `launcher: current`. Exit code 0 means it worked; anything else means nothing was
   switched.
4. Start `Thoron.exe`. The About page shows the new version, and section 6 can go back to the old one.

### By copying the files

1. **Back up first.** Close Thoron and copy the whole `ThoronPortable` folder, with `User Data`, to
   another place. This copy is your way back ([section 6](#6-roll-back)).
2. Download the new `thoron-<version>-<variant>-portable.zip` for the **same variant** as your copy (the
   file `variant` in your folder names it), check it
   ([Verifying downloads](../../README.md#verifying-downloads)), and unpack it somewhere else.
3. Make sure Thoron is closed: every window.
4. In your portable folder, delete `Thoron.exe`, `README.txt`, `variant` and the `Application` folder.
   **Keep `User Data`.**
5. Copy everything inside the new package's `ThoronPortable` folder into your portable folder.
6. Start `Thoron.exe`. The About page shows the new version.

The update mode is kept in `Application`, so after this it is `auto` again; set it once more if you had
changed it (section 4). Your folder now holds one version only, so the updater's rollback has nothing to
go back to: your backup from step 1 is the way back.

## 6. Roll back

### A portable copy: the version before

A portable copy's `Application` folder can hold two versions: the one that starts and the one before it.
The file `Application\current` names both. The version before is kept when Thoron's updater put the
update in place (section 5, with Thoron's updater); an update by copying the files keeps no version
before.

Close Thoron, then see what the folder holds. Use the `thoron_update.exe` of any version folder in
`Application`:

```powershell
& "<folder>\ThoronPortable\Application\<version>\thoron_update.exe" --root "<folder>\ThoronPortable\Application" --status
```

It prints three lines: `current:` the version that starts, `previous:` the version before it (or `none`),
and `mode:` the update mode. When there is a version before, roll back to it:

```powershell
& "<folder>\ThoronPortable\Application\<version>\thoron_update.exe" --root "<folder>\ThoronPortable\Application" --rollback
```

The first time it only says what it would do (exit code 16). Close Thoron, then run it again with
`--confirm` at the end. It prints `done`, and the next start of `Thoron.exe` runs the version before. It
deletes nothing: roll back again to go forward again. With `previous: none` it prints
`nothing_to_roll_back`.

To put the profile back as well, as it was before the update, add
`--restore-profile "<folder>\ThoronPortable\User Data" --snapshots "<folder>\ThoronPortable\Snapshots"`.
That works when the update took a snapshot (section 5: add
`--snapshot-profile "<folder>\ThoronPortable\User Data" --snapshots "<folder>\ThoronPortable\Snapshots"`
to the `--apply-package` command). What changed in the profile since the update is then lost, and the
command says so before it asks for `--confirm`. Every file of the snapshot is checked first: if one does
not verify, nothing is changed (exit code 17).

| Exit code | Meaning |
|---|---|
| 0 | Done |
| 1 | The command is not one the updater knows |
| 10 | `--status`: no version starts in that folder (check the `--root` path) |
| 14 | A rename or a write failed; the version that started before still does |
| 15 | `--rollback`: there is no version before the current one |
| 16 | `--rollback`: it said what it would do; run it again with `--confirm` |
| 17 | `--rollback`: there is no snapshot from before the update, or it does not verify; nothing changed |

PowerShell shows the exit code of the last command with `$LASTEXITCODE`.

A rollback changes the program only, never the profile. After an update to a new Chromium major
version, the older version may not open the profile any more: that is what the profile snapshot below is
for, and until it is used, what your own backup is for.

### A portable copy: your backup

1. Close Thoron.
2. Rename your portable folder (for example to `ThoronPortable new`). Do not delete it before the old
   copy works.
3. Put the copy you made before the update in its place.
4. Start `Thoron.exe`.

What you did after the backup (new bookmarks, saved passwords, open tabs) is only in the renamed folder.

### The profile snapshot

Before an update to a new major version, Thoron is meant to take a snapshot of what matters most in
every profile: `Local State` and, of each profile, the bookmarks, settings, saved passwords, history,
cookies, autofill, shortcuts, top sites and the open windows and tabs. Every file is copied and checked,
every database is checked by SQLite, the snapshot is kept next to `User Data` and never inside it, and the
last two are kept.

The code and its tests exist (ROADMAP P3.7). The browser does not take snapshots by itself yet (P3.20),
and a rollback that puts one back, with a clear warning that changes made since the update are lost and
your explicit confirmation, is ROADMAP P3.8. There is no command for either yet, so back up yourself
before an update.

### An installed Thoron

A rollback is not offered yet (ROADMAP P3.8). Before you install a newer version, close Thoron and copy
`%LOCALAPPDATA%\Thoron\User Data` somewhere.

## 7. Comes later

| What | Stage |
|---|---|
| Releases signed, so that copies can check and install them | P2.11, P3.2 |
| An installed Thoron updating itself end to end, with one relaunch | P3.20 |
| The update while Thoron runs, with a relaunch badge | P3.6 |
| A portable copy updating itself (the swap at its start) | P3.12, P3.20 |
| The update mode in Settings | P3.20 |
| Looking for updates without administrator rights while Thoron is closed | P3.10 |
| Delta packages | P4.1 |
| Downloads that resume, pause on metered connections, and work through a proxy | P4.3 |
| Rollback with the profile snapshot, a warning and your confirmation | P3.8 |
