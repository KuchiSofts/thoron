# Portable passphrase

A portable copy of Thoron can lock its saved passwords and cookies (your sign-ins) with a passphrase, so
they open on any PC once you type it and stay locked for anyone else who holds the drive (ROADMAP P4.9).
Windows only for now.

**Status:** built and tested on test copies, and on a second PC (a copy locked on one PC opened on a clean
Windows with its passphrase, its sign-ins and settings intact); it is not in a release yet, and its own
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

Until a release has the lock:

1. **Do not keep passwords in a portable copy.** Keep them in an installed Thoron, or wherever you keep them
   now. When a portable copy offers to save a password, decline.
2. Do not import passwords into a portable copy ([Import](IMPORT.md#4-chromes-saved-passwords)).
3. Expect to sign in to your sites again when you use the copy on another PC or Windows account.

More about what a portable copy keeps and leaves: [PORTABLE.md](../release/PORTABLE.md#6-not-there-yet). How
it works and the threats it answers: the
[design](../design/2026-11-07-thoron-design.md#78-portable-encryption-owner-passphrase-encrypted) and the
[threat model](../security/THREAT_MODEL.md#6-portable-encryption) (ROADMAP S.2).
