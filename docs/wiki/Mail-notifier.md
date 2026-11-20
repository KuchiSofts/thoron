# Thoron M-Notifier

Thoron M-Notifier is Thoron's own mail notifier: an envelope with the number of new messages of every Google
account you are signed in to in Thoron (Gmail and Google Workspace).

## How it works

- **No passwords.** It reads Gmail's own feed with the sign-in Thoron already has, the way Gmail's page itself
  is sent your mail. You never type a password into it, and it keeps none. To add an account, choose **Add an
  account** in its menu and sign in on Google's own page; the account is found from then on.
- **Every account.** Each Google account you are signed in to (the ones you switch between in Gmail) is found by
  itself.
- **Quiet without a sign-in.** While nobody is signed in to Google in the profile, Gmail is not asked at all;
  the first look comes as soon as you sign in. Mailboxes added by address and password are looked at either way.
- **New since you looked.** The count is the mail that came since you last opened that account's inbox from
  the M-Notifier. Click the account's address (or **Open inbox**) and its count starts again from 0; its unread
  mail is still listed. You can count all unread mail instead.
- **No spam.** Only the inbox is counted: spam, trash and archived mail never are.
- **Safe.** What Gmail sends is read in a sandboxed process, never in the browser itself. Only links to Gmail are
  opened from it.
- **In time.** It looks a moment after Thoron starts, then every 2 minutes (1 to 30, your choice), and each time
  you open its menu.

## Use it

- **The envelope:** in the browser's own colour, with the count in its corner while there is new mail (next to
  it in the address bar). Click it for the menu:
  - each account with its new and unread mail, by the name your list gives it (from X-notifier, say) or its
    address; click an account to open its inbox (and reset its count);
  - **Check now**, **Add an account**, and **Settings** (the gear), which opens Thoron M-Notifier's own page in a
    tab.
- **Move it with the mouse:** drag the envelope to another place of the toolbar, or past Thoron adblock's
  shield to change their order.
- To turn it off entirely, set "Thoron M-Notifier" to **Disabled** on `chrome://flags/#thoron-mail-notifier`.

## Its page

The page has five tabs, and keeps the one you chose in its address (a link to `#manage/alerts` opens Alerts):

- **Accounts:** every account in one list, each once: its name or address, what kind it is, its new and unread
  mail, and a switch to count it or not (one switched off is still listed, but not counted, and you are not told
  of its mail). Open an account (its name, or the arrow at its end) to give it its own sound, move it, edit it
  or remove it. With more than six accounts, **Find an account** narrows the list as you type.
- **Alerts and sounds:** the sound (see below), **Show a notice for new mail** and **List the messages in this
  menu**.
- **Counting:** **The icon counts** new mail since you looked, or all unread mail; **Look every** 1 to 30
  minutes; **Of Gmail, count** the whole inbox, only the Primary tab, or the inbox and spam.
- **Display:** **Show it** next to the address bar, in the address bar, or in both, and where; **Open mail in**
  the account's open Gmail tab, or a new tab.
- **Backup:** see below.

## Sounds

- **Sound:** Windows' own new-mail sound, or one of ten that Thoron makes itself: Chime, Bell, Marimba, Pop,
  Water drops, Bright, Soft, Knock, Ding and Double beep. **Play** lets you hear it first. Thoron's sounds have a
  **Volume** of their own; Windows' sound plays at the system's volume.
- **An account's own sound:** open the account under Accounts and choose **Its sound**: the sound for all
  accounts, another one, or **No sound** (its mail is still counted).
- **Stay quiet:** while a full-screen program, a game or a presentation runs (as Windows tells it); while that
  inbox is the tab in front of you (you are already looking at it); and in **Quiet hours** you set (from 22:00 to
  07:00, say), which hold the notices too.
- No recording is used: each of Thoron's sounds is made from tones when it plays, so none is anyone else's work.

## Mailboxes by address and password

You are not limited to the Google accounts Thoron is signed in to. In the menu choose **Add an account**, then
**Add by address and password...**: Thoron M-Notifier's own page opens.

- Type the address and the password, and **Add**. Thoron signs in over a secure connection, only reads, and
  keeps the password encrypted by Windows. A wrong password is told at once.
- Yahoo, AOL, iCloud, GMX, Mail.ru, Yandex, Zoho and Fastmail are known by name. For any other service, open
  **Server** and type its IMAP server.
- **Gmail** works this way too, but Google accepts only an *app password* here, not your normal password: you
  make one in your Google Account under Security, 2-Step Verification, App passwords.
- **Outlook, Hotmail and Live** cannot be added this way: Microsoft no longer lets mail programs sign in with a
  password.
- **Proton Mail** is read through **Proton Mail Bridge**, Proton's own app (see below).
- To change a mailbox (a new password, another address or server): open it under Accounts and choose **Edit**.
  Leave the password empty to keep the one it has. A new password, address or server is signed in to first and
  kept only when that works, so a typo changes nothing. Only its mail page is kept at once.
- To take a mailbox out again: open it and choose **Remove** (twice: the first press asks).

## Your order

Under Accounts, drag an account to where you want it, or open it and use **Move up** and **Move down** (with the
keyboard, Alt and an arrow key). The menu lists the accounts in that order, it stays after a restart, and it is in
the backup.

## What is counted

On the Counting tab, "Of Gmail, count": the whole inbox, only the Primary tab, or the inbox and spam. Spam is
never counted unless you choose that.

## Coming from X-notifier

X-notifier can save its accounts to a file with a passphrase (its Export). Thoron M-Notifier reads that file:

1. Open Thoron M-Notifier's page (**Settings**, the gear in its menu).
2. On the Backup tab, type the file's passphrase and choose **Read a file of X-notifier...**.
3. Your Google accounts appear under Accounts, each with its name and its password kept encrypted. One
   that Thoron is signed in to at Google shows its mail. For the others, **Sign in**
   opens Google's page with the address filled in, and **Copy password** puts its password on the clipboard
   to paste there. You do this once for an account; Google keeps the sign-in.
4. Open an account and choose **Edit**: it changes its address, its name or its password (left empty, the password stays).
   An *app password* typed there also lets Thoron read the account's mail as a mailbox.

Thoron M-Notifier does not sign in to Google by itself the way X-notifier does: that is what signs people
out. Up to 30 Google accounts are counted. Entries of X-notifier that are not mail are left out.

## Backup

On Thoron M-Notifier's page, on the Backup tab:

- **Save a backup...** writes your mailboxes, your list, your order and your settings to a file you choose in
  Windows' own Save dialog (named with the day, so older backups stay beside it; the next one starts in the same
  folder). With a passphrase the file is sealed and holds the passwords safely. Without one it holds no
  passwords, unless you tick that you want them in it as they are. Thoron reads the file back after writing it:
  when a folder does not take the whole file, you are told so and asked to choose another, and no empty file is
  left behind.
- **Read a backup...** brings them back, on this PC or another.
- The list of Google accounts (see above) is in the backup too.
- Save the file into your Google Drive folder, or any folder that is synced, and it is in the cloud.

### By itself

Turn on **Save a backup by itself after each change** and choose a folder (your Google Drive folder, for one).
Every two minutes Thoron looks whether anything a backup holds has changed (an account, a password, your order,
a setting), and then writes a new backup into that folder, named with the date and time
(`thoron-m-notifier-auto-...`). Nothing is written while nothing changes.

- **Backups kept:** only its own newest files stay (5 unless you choose 3, 10 or 20). Your other files in the
  folder, and the backups you saved yourself, are never touched.
- **Passphrase:** type one (8 characters or more) and choose **Keep**: the backups are then sealed with it and
  hold the passwords. Thoron keeps the passphrase encrypted by Windows, so it is not asked for again on this
  PC; on another PC you type it to read a backup. Without a passphrase the backups hold everything except the
  passwords.
- **Save one now** writes one at once. If the folder is gone or cannot be written, the Backup tab says so.

## Proton Mail

Proton keeps your mail encrypted, so no mail program reads it directly. Proton's own app, **Proton Mail
Bridge**, runs on your computer and serves your mailbox to mail programs. Thoron M-Notifier reads it there:

1. Install Proton Mail Bridge from Proton, sign in to it, and keep it running.
2. In Bridge, open your address's mailbox details and copy the **password Bridge shows** (it is not your Proton
   password).
3. In Thoron M-Notifier, **Add by address and password...**, type your Proton address (the server
   `127.0.0.1` and port `1143` are filled in), paste Bridge's password, and **Add**.

Bridge makes its own certificate for the encrypted connection, which no authority signs. Thoron trusts the one
Bridge shows when you add the mailbox, and only that one: Thoron connects only to your own computer for it,
never through a proxy, and sends the password only after the encrypted connection is up. If Bridge is installed
again and makes a new certificate, the mailbox shows **Certificate changed**: open it, choose **Edit**, type
Bridge's password again and save, and the new certificate is trusted instead. Bridge's "STARTTLS" (its default)
and "SSL" settings both work.

## Coming

Outlook and Hotmail, with Microsoft's own sign-in, are planned.
