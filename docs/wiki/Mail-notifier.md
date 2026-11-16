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
  - each account with its new and unread mail; click an account to open its inbox (and reset its count);
  - **Check now**, **Add an account**.
- **Move it with the mouse:** drag the envelope to another place of the toolbar, or past Thoron adblock's
  shield to change their order.
- **Settings** (the gear in the menu):
  - **Show it** next to the address bar, in the address bar, or in both; and where: right after the address bar,
    after the extensions or next to the menu; with the address bar's other icons, before them or at the far end;
  - **The icon counts** new mail since you looked, or all unread mail;
  - **Look every** 1 to 30 minutes;
  - **Play a sound for new mail** (on), **Show a notice for new mail** (off) and **List the messages in this
    menu** (off): as it comes, it only counts and makes a sound;
  - **Open mail in** the account's open Gmail tab, or a new tab;
  - **Accounts to watch**: one you untick is still listed but not counted, and you are not told of its mail.
- To turn it off entirely, set "Thoron M-Notifier" to **Disabled** on `chrome://flags/#thoron-mail-notifier`.

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
  password. **Proton Mail** needs its Bridge app, which Thoron does not use yet.
- To take a mailbox out again: **Remove**, next to it under "Accounts to watch".

## What is counted

Under **Counting**, "Of Gmail, count": the whole inbox, only the Primary tab, or the inbox and spam. Spam is
never counted unless you choose that.

## Coming from X-notifier

X-notifier can save its accounts to a file with a passphrase (its Export). Thoron M-Notifier reads that file:

1. Open Thoron M-Notifier's page (**Accounts and backup...** in its menu).
2. Under **Backup**, type the file's passphrase and choose **Read a file of X-notifier...**.
3. Your Google accounts appear under **Google accounts of your list**, each with its name and its password
   kept encrypted. One that Thoron is signed in to at Google says **Counted**. For the others, **Sign in**
   opens Google's page with the address filled in, and **Copy password** puts its password on the clipboard
   to paste there. You do this once for an account; Google keeps the sign-in.

Thoron M-Notifier does not sign in to Google by itself the way X-notifier does: that is what signs people
out. Up to 30 Google accounts are counted. Entries of X-notifier that are not mail are left out.

## Backup

On Thoron M-Notifier's page, under **Backup**:

- **Save a backup...** writes your mailboxes and settings to a file. With a passphrase the file is sealed and
  holds the passwords safely. Without one it holds no passwords, unless you tick that you want them in it as
  they are.
- **Read a backup...** brings them back, on this PC or another.
- The list of Google accounts (see above) is in the backup too.
- Save the file into your Google Drive folder, or any folder that is synced, and it is in the cloud.

## Coming

Outlook and Hotmail (with Microsoft's own sign-in) and Proton Mail are planned.
