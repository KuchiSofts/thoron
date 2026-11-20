# User guides

Step-by-step guides for people who use Thoron. Each guide says what works today and what comes later,
with the stage of the [roadmap](../../ROADMAP.md) that brings it (an ID such as P3.20).

**There is no public release yet.** The first one is Thoron 0.1.1 for Windows x64.

| Guide | What it covers |
|---|---|
| [Install](INSTALL.md) | The portable package and the installer, which package fits your processor, moving a portable copy and USB drives, removing Thoron |
| [Install on Linux](INSTALL_LINUX.md) | The `.deb` package and the portable folder on Linux, which package fits your processor, the sandbox and AppArmor, removing Thoron |
| [Import](IMPORT.md) | Bringing your profile, open tabs and passwords over from Thorium and Chrome, today with small command-line tools |
| [Updates and rollback](UPDATES.md) | How Thoron looks for updates, what the About page says, the update modes, updating and rolling back a portable copy |
| [Portable passphrase](PORTABLE_PASSPHRASE.md) | Locking a portable copy's passwords and sign-ins with a passphrase, a recovery key and remembered PCs (built, not in a release yet) |

## How the guides are tested

The Windows steps of [Install](INSTALL.md) (the installer, the portable package, removing both) and the
update mode of [Updates](UPDATES.md) are followed on a clean Windows for each build, clicks included:
`tools/qa/sandbox_guides_check.py` runs them in Windows Sandbox and checks that each step shows what the
guide says. Sections 1 and 2 of [Import](IMPORT.md) (finding the browsers, bringing a whole Thorium profile
over, and each refusal: while Thorium runs, right after it closed, into a Thoron that has a profile) are
followed the same way by `tools/qa/sandbox_import_guide_check.py`, with a Thorium profile made in the
Sandbox. What they cannot follow yet: downloading from GitHub and the minisign check (there is no release
and no published key yet), installing Python from python.org (the Sandbox has no network: it gets the
interpreter and its standard library from the PC), the warning "Windows protected your PC" for a
downloaded file, and the sections of Import that need Chrome or Firefox installed.

The steps of [Install on Linux](INSTALL_LINUX.md) are followed on clean Ubuntu 24.04 and 26.04 test machines (`tools/qa/wsl_test_vm.py`): `tools/qa/linux_package_check.py` installs the `.deb` with apt, starts Thoron, installs upstream Thorium beside it (each keeps its own profile) and removes Thoron (the profile stays); `tools/qa/linux_portable_check.py` unpacks the portable package into a folder whose name has a space and accented and Cyrillic letters, starts it, moves it and starts it again with the same profile, and nothing is written to `~/.config/thoron`. What they cannot follow: the AppArmor steps (WSL has no AppArmor).

## How to read the guides

- Commands are typed in Windows PowerShell (Windows Terminal opens it).
- `$env:LOCALAPPDATA` in a command is your account's local application folder; PowerShell fills it in for
  you. In the text it is written `%LOCALAPPDATA%`, which also opens that folder when you type it into File
  Explorer's address bar.
- `<folder>` stands for a folder you chose, and `<version>` for a version number, such as
  `158.0.8127.3010`. Type your own in their place, without the `<` and `>`.

More about Thoron: the [wiki](https://github.com/KuchiSofts/thoron/wiki) and the [README](../../README.md).
