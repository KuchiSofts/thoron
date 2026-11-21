# Import from another browser

Bookmarks, history, saved passwords, search engines, form entries and cookies (you stay signed in to
your sites) come over from Thoron's Settings (section 1a); Thoron's welcome page at its first start leads there. Whole profiles, open tabs and Chrome's
passwords come over with small command-line tools from Thoron's repository. An import screen in the
installer comes later (ROADMAP P3.13).

Every tool **copies and never moves**: the other browser's files are only read and stay exactly as they
were, so that browser keeps working and stays your backup.

## What can be imported today

| From | What comes over | Section |
|---|---|---|
| Thorium, Chrome, Edge, Brave, Vivaldi, Opera, Opera GX, Chromium | Bookmarks, history, saved passwords and cookies (not those Chrome locks to itself), search engines, form entries, the home page and startup pages, extensions from the Chrome Web Store (installed again from the store), and the open windows, tabs and tab groups (they open in new windows), in Thoron's Settings | [1a](#1a-in-thorons-settings) |
| Thorium, same Windows account | Everything: bookmarks, history, saved passwords, cookies (you stay signed in), extensions, settings, open tabs and tab groups | [2](#2-thorium-the-whole-profile) |
| Chrome, Thorium, Thoron | Open windows, tabs and tab groups (names, colours, collapsed or not), pinned tabs, each tab's back and forward history | [3](#3-open-tabs-and-tab-groups) |
| Firefox | The same: open windows, tabs and tab groups, pinned tabs, each tab's history | [3](#from-firefox) |
| Firefox | Bookmarks, history and saved passwords, with Chromium's own importer in Thoron's Settings | [3](#from-firefox) |
| Chrome | Saved passwords, through Chrome's own export | [4](#4-chromes-saved-passwords) |
| uBlock Origin, from its backup file | Your own filters, lists, trusted sites, rules, switches and the settings you changed, into Thoron adblock | [5](#5-ublock-origins-settings-into-thoron-adblock) |

**Chrome's cookies cannot come over.** Chrome locks its saved passwords and cookies to itself
(app-bound encryption), so no other program can read them. Thoron does not try to get around that:
the tricks that do are what password-stealing programs use. Passwords come over through Chrome's own
export (section 4). For cookies there is no such way, so sign in to your sites again in Thoron.

## 1a. In Thoron's Settings

1. Close the browser you import from, completely.
2. In Thoron open **Settings**, then **Import bookmarks and settings** (or type
   `chrome://settings/importData` into the address bar). At the first start, the welcome page's
   **Import...** opens the same dialog.
3. Pick the browser in the list. It names each one found in your own account (on Windows in your
   `AppData`, on Linux in `~/.config`), with the profile's name when it has several, such as
   "Brave (Work)". Thoron never lists itself.
4. Leave ticked what you want, and choose **Import**.

If that browser still runs, Thoron asks you to close it, and imports nothing until you have; it never
closes it for you. Close it and choose **Try again**.

What it does: it copies the files it needs (`Bookmarks`, `History`, `Login Data`, `Web Data` and the
browser's `Local State`, and a database's `-wal` file when the browser did not close cleanly) into a temporary
folder, checks each database copy with SQLite and leaves out one that is damaged, reads the copies and
deletes them at the end. The other browser's files are only read.
The bookmarks go into a folder of their own, "Imported from" and the browser's name (while Thoron's bookmarks
bar is still empty they go straight onto it, as Chromium does). Saved passwords and
cookies (**Cookies and site sign-ins**) come over when they belong to your Windows account; those that
Chrome locks to itself (app-bound encryption) are left out and never forced. Cookies that end when the
other browser closes, and expired ones, are left out; a cookie Thoron already has for the same site, name
and path is replaced by the imported one. **Home page and startup pages** brings the home page (and
whether the home button shows) and what the browser opens at its start: its last session, the New Tab
page, or pages of its own, which then become Thoron's startup pages. Only web pages come over, never a
script or a browser's internal page, and a setting that your organization's policy decides stays as the
policy says. Check them afterwards in Thoron's Settings, **On startup** and **Appearance**: they are set
exactly as the other browser had them. **Extensions (installed again from the Chrome Web Store)**
is off until you tick it: Thoron reads which extensions you installed from the Chrome Web Store (only
their IDs) and downloads each one again from the store, as a fresh install would, never a copy of the
other browser's extension files. They arrive within a few minutes, with the access they ask for not
granted: one that wants to read your sites, tabs or similar stays off, and Thoron's menu offers to turn
it on, showing what it asks for; one that asks for none of that is on at once. Extensions that came
with the browser, that a policy or another program put there, or that were loaded unpacked are left out
(the unpacked and other-program ones are counted in the report; add those yourself if you trust them).
The extensions' own settings and data stay
behind. **Open tabs and tab groups (they open now, in new windows)** is off until you tick it too: Thoron
reads the other browser's last session (the one it would open itself at its next start) and opens its
windows, tabs and tab groups, with the groups' names, colours and whether they were collapsed, in new
Thoron windows straight away. Each tab keeps its back and forward history (up to 50 pages). Only web
pages come over: a browser's own pages (its settings, its start page) and scripts do not, a tab that had
only such pages is left out, and so are app and pop-up windows. Pages load fresh from their addresses, so
what you had typed into a form, where you had scrolled to and a page that came from sending a form stay
behind. At most 500 tabs in 50 windows come over. For Thorium's whole profile, or with the browsers
closed, sections 2 and 3 bring the tabs too.

**On Linux** the same import works with the browsers in `~/.config` (Thorium, Chrome, Edge, Brave, Vivaldi, Opera, Chromium). Saved passwords and cookies there are encrypted either with Chromium's fixed key (a browser without a desktop keyring, or started with `--password-store=basic`) or with a key the browser keeps in your desktop's keyring (GNOME's keyring and others that offer the Secret Service): Thoron reads that key from the keyring, as the browser itself does, while your keyring is unlocked. It only reads it: it never adds, changes or unlocks anything there, and a locked keyring is left alone (those passwords are then counted as not readable in the report). KDE's KWallet is not read yet. A browser still runs while its `SingletonLock` names a running process on this computer.

**The report.** Each import writes `Thoron import report.json` into the Thoron profile's folder (for an
installed Thoron, `%LOCALAPPDATA%\Thoron\User Data\Default`), replacing the one before: when, from which
browser, how many bookmarks, history entries, saved passwords, cookies, search engines and form entries came over,
whether a home page did and how many startup pages, how many extensions are to be installed from the store, how many open tabs,
and how many were left out and why (passwords and cookies locked by Chrome, in no format Thoron knows, or
that did not decrypt; extensions not from the store; a damaged database). It holds counts and the browser's name only, never an address, a name, a
password or any other value.

## 1. Before you start

1. Install **Python 3.11 or newer** for Windows (from python.org). It brings the `py` command the guides use.
2. Get Thoron's repository: on [its GitHub page](https://github.com/KuchiSofts/thoron) choose **Code**,
   then **Download ZIP**, and unpack it.
3. Open the unpacked folder (the one that holds `tools` and `README.md`) in File Explorer, right-click an
   empty place in it and choose **Open in Terminal**. Type every command below there.
4. Close the browser you import from and Thoron, **completely**. The tools refuse while either one runs,
   and they never close a browser for you. They also wait until the browser you closed has finished
   writing its profile: within the first half minute after closing it they ask you to try again.

To see which browsers and profiles the tools find:

```powershell
py -3 -I tools\migrate\detect.py
```

It looks only in your own Windows account, never in another user's, and finds Thorium, Chrome, Edge,
Brave, Vivaldi, Opera, Opera GX and Chromium. For each it lists the profiles: the folder name first (such
as `Default` or `Profile 1`, which the commands below need), then the name you gave the profile. A browser
that runs is marked `(running: close it before an import)`.

## 2. Thorium: the whole profile

This copies Thorium's whole `User Data` folder into Thoron. It works only into an **empty** Thoron
profile, so do it before Thoron's first start.

Into an installed Thoron:

```powershell
py -3 -I tools\migrate\import_profile.py --from "$env:LOCALAPPDATA\Thorium\User Data" --to "$env:LOCALAPPDATA\Thoron\User Data"
```

Into a portable copy, before its first start:

```powershell
py -3 -I tools\migrate\import_profile.py --from "$env:LOCALAPPDATA\Thorium\User Data" --to "<folder>\ThoronPortable\User Data"
```

In a portable copy the saved passwords and sign-ins then work only on this PC and this Windows account
([why](PORTABLE_PASSPHRASE.md)); Thorium keeps the originals.

What it does:

- It copies every file and compares each copy with the original (SHA-256).
- It checks that Thorium's files were the same before and after; if something wrote to them meanwhile,
  it says so.
- It checks every database of the copy with SQLite, on a copy of the copy.
- Saved passwords and cookies keep working, because the key that unlocks them comes along. That key
  belongs to your Windows account, so this works only for the same account.

It refuses, and changes nothing, when: the source is not a browser's `User Data` folder; Thorium or Thoron
is running; one folder is inside the other; the source holds a link or junction; or **Thoron's folder
already holds a profile**. If Thoron has started once already, close it, rename its `User Data` folder
(for example to `User Data before import`, so nothing is lost) and run the command again.

**The report.** At the end the tool prints a short report and writes it as `Thoron import report.json`
beside the destination folder (for an installed Thoron, `%LOCALAPPDATA%\Thoron\Thoron import report.json`).
For every profile it gives the number of bookmarks, history entries, saved passwords, cookies, autofill
entries and extensions that came over (counted in the copy), what could not be counted and why, a
database that SQLite found damaged, and what was not brought over. It holds counts and names of profiles
and files only: never a password, a user name, an address, a cookie or any other value.

**Afterwards** use Thoron and keep Thorium closed, as your backup. Two copies of one profile online at the
same time can make sites sign one of them out, and both sync as the same device.

## 3. Open tabs and tab groups

This brings the open windows of another profile into a Thoron profile: the tab order, pinned tabs, tab
groups with their names, colours and collapsed state, each tab's history, and the recently closed tabs.
It was tested with Chrome 157, Edge 157, Brave 1.97, Vivaldi 8.3, Opera, Thorium 156 and Thoron 158. From Thorium
you do not need it after section 2: the whole profile brings the tabs. With Thoron running, Settings' import does
the same for the Chromium family without these steps (**Open tabs and tab groups**, section 1a), opening the
windows at once.

1. Start Thoron once and close it again: the Thoron profile must have started before.
2. Close the other browser.
3. See what would come over. This only reads; the titles and addresses it prints are your own, so keep
   them on your PC:

   ```powershell
   py -3 -I tools\migrate\sessions.py read --profile "$env:LOCALAPPDATA\Google\Chrome\User Data\Default"
   ```

4. Import:

   ```powershell
   py -3 -I tools\migrate\sessions.py import --from "$env:LOCALAPPDATA\Google\Chrome\User Data\Default" --to "$env:LOCALAPPDATA\Thoron\User Data\Default" --set-aside --restore-on-next-start
   ```

5. Start Thoron: the imported windows open.

Change the paths for your case: another Chrome profile is `Profile 1` and so on in place of `Default`
(see `detect.py`); a portable copy is `--to "<folder>\ThoronPortable\User Data\Default"`.

- `--set-aside` keeps Thoron's own last session in a folder inside `Sessions` (its name starts with
  `Thoron before import`). Without it the import refuses when Thoron has a session of its own.
- `--restore-on-next-start` makes the next start of Thoron open the imported windows once, without
  changing your start-up setting.

The tool says what it copied: `tabs: copied <files>, every file verified;` and then the number of
windows, tabs, groups, pinned tabs and recently closed entries. Two things differ from the other browser,
on purpose:

- Tab groups come over as Thoron's own. Their link to the other browser's saved groups is left out,
  because Thoron would otherwise take them for groups deleted elsewhere and close them with their tabs.
- Parts of the session that Thoron cannot use (another browser's own additions, or damaged parts) are
  left out, because the browser stops reading a session at the first one and would lose the rest.

A minimized window opens as a normal one, as Thoron does with its own session.

### From Firefox

Firefox keeps its open tabs in `sessionstore.jsonlz4` in its profile folder (a packed file of its own),
not in the files Chromium browsers use. `firefox_sessions.py` reads it and writes the same windows into
Thoron as a session file of Thoron's own, then reads that file back to check it holds the same windows,
tabs, pages and groups. It was tested with a session Firefox 160 wrote.

1. Start Thoron once and close it again.
2. Close Firefox completely. Firefox writes `sessionstore.jsonlz4` when it quits; while it runs the tool
   refuses.
3. Find your Firefox profile folder: in Firefox, `about:profiles` names it ("Root Directory"), usually
   `%APPDATA%\Mozilla\Firefox\Profiles\<letters>.default-release`.
4. See what would come over (this only reads):

   ```powershell
   py -3 -I tools\migrate\firefox_sessions.py read --file "<Firefox profile folder>\sessionstore.jsonlz4"
   ```

5. Import, then start Thoron:

   ```powershell
   py -3 -I tools\migrate\firefox_sessions.py import --from "<Firefox profile folder>" --to "$env:LOCALAPPDATA\Thoron\User Data\Default" --set-aside --restore-on-next-start
   ```

`--set-aside` and `--restore-on-next-start` work as above. What differs from Firefox, on purpose:

- Only web pages come over (addresses that start with `http`, `https`, `ftp` or `file`). Firefox's own
  pages (`about:` pages, extension pages) mean nothing in Thoron; a tab that had only such pages is left
  out. The tool counts what it left out (`dropped`).
- At most 50 pages of each tab's history come over, around the page it was on, as Chromium keeps them.
- Pinned tabs come first in their window and are in no group, as Thoron needs them. Firefox's colour
  "gray" is Thoron's "grey".
- Firefox's recently closed tabs and windows do not come over.

Bookmarks, history and saved passwords come with Chromium's own importer, which Thoron keeps: in Thoron,
open `chrome://settings/importData`, choose Mozilla Firefox and what to bring, and close Firefox first. It
reads the passwords with Firefox's own security library, so a Firefox primary password is asked for if
you set one. Thoron's tests do not cover that importer yet: it reads only your own Firefox profile.

## 4. Chrome's saved passwords

**Do not import passwords into a portable copy yet** ([why](PORTABLE_PASSPHRASE.md)). Use an installed
Thoron.

The tool guides Chrome's own export and Thoron's own import, and then removes the exported file. That
file holds every password in plain text while it exists.

1. Start the guide (with Chrome installed in its usual place; if Chrome is installed for your account only,
   its program is `$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe`):

   ```powershell
   py -3 -I tools\migrate\chrome_passwords.py --chrome "C:\Program Files\Google\Chrome\Application\chrome.exe" --thoron "$env:LOCALAPPDATA\Thoron\Application\thoron.exe"
   ```

2. Chrome opens its password settings. Choose **Export passwords** and save the file in your **Downloads**
   folder, never in a folder that OneDrive, Google Drive, Dropbox, iCloud or Box copies, and never
   outside your own folders (a second drive or the Public folder), where other accounts of the PC may read
   it: the tool refuses such a file.
3. Drag the saved file into the terminal window (or type its path) and press Enter. Pressing Enter on an
   empty line stops, and nothing is imported.
4. The tool checks the file: Chrome's columns, at least one password, and not in a synced folder. It says
   how many passwords the file holds.
5. Thoron opens its password settings. Choose **Import passwords** and pick the same file.
6. Back in the terminal, press Enter when Thoron has imported them (or when you want to stop). The tool
   overwrites the file with random bytes and deletes it, and does the same with a copy beside it such as
   `... (1).csv`.

The tool reads only the file's first line and counts its lines. It never shows, logs or keeps a password.

Deleting is all it can promise: a copy that a backup, a snapshot, a synced folder or the drive itself
made on its own is not reached. If the file was ever in such a place, check there. If the guide was
stopped before step 6, remove the file with:

```powershell
py -3 -I tools\migrate\chrome_passwords.py --wipe "<the file>"
```

## 5. uBlock Origin's settings into Thoron adblock

Thoron has its own ad blocker, Thoron adblock, so uBlock Origin is not needed beside it. What you set up
in uBlock Origin comes over in two steps, and uBlock Origin itself is not changed:

1. In uBlock Origin: its **Dashboard**, the **Settings** tab, **Back up to file**. It saves a file named
   like `my-ublock-backup_2026-11-17_10.00.00.txt`.
2. In Thoron: open `chrome://adblock`, the **Backup** tab, **Restore from file**, and pick that file.

| Comes over | Note |
|---|---|
| Your own filters ("My filters") | as they are |
| The filter lists you had on | uBlock Origin's own lists by their names; optional lists that Thoron adblock's list of lists has; lists you added by their address |
| Trusted sites | the sites; uBlock Origin's own entries for browser pages are left out, they mean nothing here |
| Your rules and the switches of sites | "My rules", the per-site switches (pop-ups, large media, fonts, JavaScript, cosmetic filtering) |
| The settings you changed | the badge, pre-fetching, hyperlink auditing, WebRTC, the default behaviour, the theme and the accent colour; the others keep Thoron adblock's own defaults |

The page names what has no place in Thoron adblock: a list it does not know (add it from the list of lists,
if it is there) and uBlock Origin's advanced settings. Like any restore, it replaces Thoron adblock's
lists, own filters, trusted sites and switches with the file's. Thoron's own phishing list stays as it is.

## 6. Comes later

| What | Stage |
|---|---|
| Open tabs and tab groups in Settings' own import | P3.22 |
| Linux: passwords imported from Thorium readable | P3.16 |
