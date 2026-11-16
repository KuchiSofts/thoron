# Portable passphrase

**Not built yet.** Protecting the passwords and cookies of a portable copy with a passphrase is ROADMAP
P4.9. Nothing on this page works today except the advice in section 1.

## 1. Today

A portable copy protects saved passwords and cookies (your sign-ins) the way an installed browser does:
with a key that Windows keeps for **your Windows account** (DPAPI). So:

- On the PC and the Windows account where you saved them, they work.
- On another PC, or under another Windows account, they cannot be read and may be lost. Your bookmarks,
  history, settings and extensions still come along.
- Thoron does not use the browser's switch that would keep them unprotected instead, on purpose.

**What to do until the passphrase comes:**

1. **Do not keep passwords in a portable copy yet.** Keep them in an installed Thoron, or wherever you
   keep them now. When a portable copy offers to save a password, decline.
2. Do not import passwords into a portable copy ([Import](IMPORT.md#4-chromes-saved-passwords)).
3. Expect to sign in to your sites again when you use the copy on another PC or Windows account.
4. Remember that whoever holds the folder (for example a lost USB drive) can read everything in it that
   is not passwords or cookies: bookmarks, history, open tabs and the rest. A drive that must stay private
   as a whole needs an encrypted drive.

More about what a portable copy keeps and leaves: [PORTABLE.md](../release/PORTABLE.md#6-not-there-yet).

## 2. What it will do

As the [design](../design/2026-11-07-thoron-design.md#78-portable-encryption-owner-passphrase-encrypted)
describes it:

- **A passphrase you choose.** A random key encrypts the portable copy's saved passwords and cookies.
  That key is locked with your passphrase (stretched with Argon2id, a method made to slow down guessing).
- **On any PC.** The profile opens anywhere once you type the passphrase.
- **Remember this PC (optional).** A second copy of the key, locked by Windows (DPAPI), so a PC you trust
  does not ask every time.
- **Changing the passphrase** locks the same key again with the new passphrase. Your data is not
  encrypted again.
- **A forgotten passphrase cannot be undone.** The passwords and cookies cannot be recovered: that is the
  point of the protection. The setup says so plainly and offers a recovery key to print, a second way to
  unlock the same key. Keep it somewhere safe and apart from the drive.
- **Only passwords and cookies are encrypted.** History, bookmarks, open tabs, the cache, downloads and
  what sites keep in their own storage stay readable to whoever holds the folder, and some sites keep a
  sign-in there. For that, an encrypted drive is still needed.
- **A long passphrase.** A short or common one can be guessed, whatever the protection.
- **Older formats stay readable for good.** It ships behind a version check.

**Taking over an upstream Thorium portable folder**, which keeps passwords unprotected (ROADMAP P4.10):
Thoron copies the folder, checks the copy, encrypts the copy, checks that it opens, and only then uses it.
The original is left as it was, so it still holds your passwords unprotected: delete it yourself once you
are sure, and remember that deleted files on a USB drive can often be recovered.

## 3. Before it ships

It changes the part of the browser that encrypts passwords and cookies, where a mistake can lose data.
So it needs, before it is offered (ROADMAP P4.9):

- its own security review;
- fuzzing of the part that reads the key file;
- round-trip tests: encrypt, move to a "new PC" with an empty Windows key store, decrypt.

The threats it must answer are in the [threat model](../security/THREAT_MODEL.md#6-portable-encryption)
(ROADMAP S.2).
