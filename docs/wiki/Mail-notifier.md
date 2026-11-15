# Mail notifier

Thoron shows your unread mail in the toolbar: an envelope with the number of unread messages of every Google
account you are signed in to in Thoron (Gmail and Google Workspace).

## How it works

- **No passwords.** It reads Gmail's own feed of unread mail with the sign-in Thoron already has, the way Gmail's
  page itself is sent your mail. You never type a password into it, and it keeps none.
- **Every account.** Each Google account you are signed in to (the ones you switch between in Gmail) is found by
  itself. To add one, choose **Add an account** in its menu and sign in to Google as usual.
- **Safe.** What Gmail sends is read in a sandboxed process, never in the browser itself. Only links to Gmail are
  opened from it.
- **In time.** It looks a moment after Thoron starts, then every 2 minutes (1 to 30, your choice), and each time
  you open its menu.

## Use it

- **The envelope:** teal with a red count while there is unread mail. Click it for the menu:
  - each account with its number of unread messages and its newest ones (sender, subject, when);
  - click a message to open it in Gmail, or **Open inbox**; a Gmail tab of that account that is already open is
    used, so you do not get a new tab each time;
  - **Check now**, **Add an account**;
  - **Tell me of new mail**: a notice for each new message (one notice that counts them when many come at once);
  - **Look every**: how often it looks.
- To turn it off entirely, set "Thoron mail notifier" to **Disabled** on `chrome://flags/#thoron-mail-notifier`.

## Coming

Outlook and Hotmail, Yahoo and Proton Mail are planned next.
