# Portable passphrase

A portable copy of Thoron can lock its saved passwords and cookies (your sign-ins) with a passphrase, so
they open on any PC once you type it and stay locked for anyone else who holds the drive (ROADMAP P4.9).
On Windows and on Linux; Linux works a little differently (section 5).

**Status:** built and tested on test copies, and on a second PC (a copy locked on one PC opened on a clean
Windows with its passphrase, its sign-ins and settings intact), and on Linux end to end on a clean Ubuntu with
GNOME's keyring (lock, unlock, recovery key, remember, change, removal); it is not in a release yet, and its own
security review by someone other than its author is still to come. Until a release has it, follow
section 4.

## 1. Without a passphrase

A portable copy protects saved passwords and cookies the way an installed browser does: with a key that
Windows keeps for **your Windows account** (DPAPI). So:

- On the PC and the Windows account where you saved them, they work.
- On another PC, or under another Windows account, they cannot be read and may be lost. Your bookmarks,
  history, settings and extensions still come along.
- Thoron does not use the browser's switch that would keep them unprotected instead, on purpose.

## 2. Lock a copy with a passphrase

1. In the portable copy, open `chrome://thoron-portable`.
2. Type a passphrase twice: at least 12 characters. A few unrelated words are long and easy to type.
3. Leave **Make a recovery key** ticked, and tick **Remember this PC** if you want this PC (for this
   Windows account) to open the copy without asking. Choose **Next**.
4. Write down the recovery key shown (eight groups of four characters) and keep it apart from the drive.
   Type its last group to confirm, and choose **Lock this copy**.

The copy keeps working at once; nothing else changes. From now on:

- **On another PC**, Thoron shows its own small window before it opens anything: type the passphrase and
  choose **Unlock**. **Quit** closes Thoron without opening anything.
- **Remember this PC** in that window saves you typing it there next time. It is kept in the copy's folder,
  locked by Windows for that PC and that Windows account only, so the drive alone does not open with it.
- **Forgot the passphrase?** In the window choose **Use the recovery key** and type the key you wrote down,
  with or without its dashes.

## 3. Change it, forget a PC, or remove the lock

All on `chrome://thoron-portable` in the unlocked copy:

- **Change the passphrase**: type the current one and the new one twice. Your data is not encrypted again;
  only the lock changes. The old passphrase no longer opens the copy.
- **Make a new recovery key**: needs the passphrase; the old recovery key stops working.
- **Remember this PC** or **Forget this PC**: for the PC and Windows account you are on.
- **Remove the lock**: needs the passphrase. The passwords and sign-ins then open only on this PC and this
  Windows account again, as in section 1.

## 4. What it covers, and what it does not

- **Only passwords and cookies are locked.** History, bookmarks, open tabs, the cache, downloads and what sites
  keep in their own storage stay readable to whoever holds the folder, and some sites keep a sign-in there. For
  those, an encrypted drive is still needed.
- **A forgotten passphrase without the recovery key cannot be undone.** Nobody, Thoron included, can open the
  passwords and sign-ins then. That is the point of the lock.
- **A long passphrase.** A short or common one can be guessed, whatever the protection. Thoron makes each guess
  slow on purpose (Argon2id, at least 64 MiB of memory per try).
- **The key file.** The lock lives in the file `Thoron Portable Key` in the copy's `User Data` folder. Keep it
  with the copy and in your backups of it. If it is missing or damaged, Thoron says so at start and does not
  carry on as if nothing happened; if it was changed by someone who could not open it, Thoron refuses it.
- **Taking over an upstream Thorium portable folder**, which keeps passwords unprotected (ROADMAP P4.10):
  with Thoron's portable copy closed and its `User Data` empty, run
  `py -3 -I tools/migrate/adopt_portable.py --from <the Thorium portable folder> --into <ThoronPortable>`. It
  copies the folder and checks every file, leaves the original as it was, protects the key at once and checks
  that every saved password and cookie still opens. Then start the Thoron copy and lock it here. The original
  still holds them unprotected: delete it yourself once you are sure (deleted files on a USB drive can often be
  recovered).
- **Crash reports:** a locked copy writes none on Windows, because they would be on its drive and may hold its key. Unlocked, it keeps them in its own folder as before ([crash reports](../qa/CRASH_TRIAGE.md)).

Until a release has the lock:

1. **Do not keep passwords in a portable copy.** Keep them in an installed Thoron, or wherever you keep them
   now. When a portable copy offers to save a password, decline.
2. Do not import passwords into a portable copy ([Import](IMPORT.md#4-chromes-saved-passwords)).
3. Expect to sign in to your sites again when you use the copy on another PC or Windows account.

## 5. On Linux

The Linux portable package (`ThoronPortable`, [Install on Linux](INSTALL_LINUX.md#3-the-portable-package))
locks the same way, on `chrome://thoron-portable`, with these differences:

- **The question comes from the `thoron` file you start the copy with**, before Thoron itself starts: a small
  desktop dialog (zenity or kdialog, whichever the desktop has), or the terminal. Type the passphrase or the
  recovery key in the same field. What you type goes to Thoron on its input, never on its command line, so other
  programs on the PC do not see it in the list of processes. Start the copy with that file, not with the program
  inside `Application`, which only says it is locked.
- **The first start after the lock encrypts the saved passwords, cookies and cards again** (and sign-in tokens
  and Autofill's other saved values). Linux keeps no key of its own for a portable copy, so the lock gives the
  copy a new key. At that start Thoron first makes a copy of each database, checks that the copy is the same,
  encrypts every value again, reads each one back, and only then wipes the copy (it overwrites it before deleting
  it). If anything fails, the database is put back from its copy and Thoron tries again at its next start. A value
  the old keys cannot read (with the desktop's keyring locked, or one saved on another PC's keyring) is left as it
  is and waited for at later starts, and Thoron says so in the terminal; it is never encrypted again as something
  it is not.
- **Remember this PC** keeps a key in the desktop's keyring for your user (GNOME's keyring, KDE's KWallet, or
  another Secret Service such as KeePassXC). Tick it when you lock, or choose **Remember this PC** on the page
  later. A start then asks nothing while that keyring is unlocked (it is, once you have signed in to the
  desktop). **Forget this PC** on the page takes it out of the copy and deletes its entry in the keyring
  ("Thoron portable copy: this PC") too. With the keyring locked it cannot, and the page says so.
- **Removing the lock** takes one more start: on the page, type the passphrase and choose **Remove the lock**,
  then close Thoron and start it again with the passphrase once more. At that start Thoron puts every saved
  password, cookie and card back under Chromium's own key for Linux, which anyone can use, as an unlocked copy
  has them, the same careful way (a checked copy first, each value read back), and only then removes the key
  file. If anything fails, the lock stays and the next start tries again. The copy keeps its former key in its
  `Local State` file, only to read anything else still under it; if you lock the copy again later, it takes that
  key again. Only the page can ask for the removal: a `Local State` changed by someone else does not remove the
  lock.
- **Without its key file** (lost, or taken away), a locked copy does not start as if it had never been locked,
  also when someone changed its `Local State` to say so: the `thoron` file asks whether to start without its saved
  passwords and sign-ins. If you choose to, Thoron sets the databases that hold them aside, next to the new ones
  (`Login Data.thoron-without-key` and so on), and does not delete them: put the key file back and those files in
  place to have them again.
- **Crash reports** of a locked copy stay off the drive: they go into your user's runtime folder on the PC (kept
  in memory, gone when you sign out), because they may hold the copy's key.
- **What was saved before the lock** was protected only by the desktop's keyring or by Chromium's fixed key
  (when there is no keyring), which anyone can use. Thoron overwrites what it can, but a flash drive may keep
  older blocks of its own. Lock a new copy before you save passwords in it, or change those passwords after
  the lock.

More about what a portable copy keeps and leaves: [PORTABLE.md](../release/PORTABLE.md#6-not-there-yet). How
it works and the threats it answers: the
[design](../design/2026-11-07-thoron-design.md#78-portable-encryption-owner-passphrase-encrypted) and the
[threat model](../security/THREAT_MODEL.md#6-portable-encryption) (ROADMAP S.2).
