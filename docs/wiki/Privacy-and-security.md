# Privacy and security

Security and the safety of your data come first in Thoron.

## Privacy

- No telemetry and no usage statistics.
- The update check sends no identifier.
- A profile nobody signed in to Google with asks Google nothing on its own account: no sign-in check, no
  optimization guide, no time request, no connection ahead of a search. What belongs to a Google sign-in (the
  New Tab page's Google bar and doodle, the mail counter's look at Gmail) works once you are signed in to
  Google.
- Every host a fresh profile contacts by itself is listed, with the reason, in
  [NETWORK.md](https://github.com/KuchiSofts/thoron/blob/main/docs/security/NETWORK.md).

## Security

- Updates are signed, and the signature is checked before anything else.
- Security fixes from Chromium are the first priority of every release.
- Every change taken from upstream passes an automatic audit and a human review.
- Flags that weaken security show a warning.

## Report a vulnerability

Please report it privately through
[GitHub's private reporting](https://github.com/KuchiSofts/thoron/security/advisories/new), never in a public
issue. Details are in [SECURITY.md](https://github.com/KuchiSofts/thoron/blob/main/SECURITY.md).
