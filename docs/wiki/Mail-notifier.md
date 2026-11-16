# Thoron M-Notifier

Thoron M-Notifier is Thoron's own mail notifier: an envelope with the number of new messages of every Google
account you are signed in to in Thoron (Gmail and Google Workspace).

## How it works

- **No passwords.** It reads Gmail's own feed with the sign-in Thoron already has, the way Gmail's page itself
  is sent your mail. You never type a password into it, and it keeps none. To add an account, choose **Add an
  account** in its menu and sign in on Google's own page; the account is found from then on.
- **Every account.** Each Google account you are signed in to (the ones you switch between in Gmail) is found by
  itself.
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

## Coming

Outlook and Hotmail, Yahoo and Proton Mail are planned next.
