# Install Thoron on Linux

Thoron for Linux x64 (Ubuntu 24.04 and newer, and other Debian-based systems) comes in two forms:

- **The `.deb` package:** installed for the whole computer, with a menu entry and the command
  `thoron-browser`. Installing it needs administrator rights (`sudo`).
- **Portable:** one folder that you unpack and start. Nothing is installed, and your profile stays inside
  the folder.

**There is no public release yet.** Until the first one, these packages exist only for people who build
Thoron themselves ([build guide](../build/LINUX.md)).

## 1. Which package fits your processor

Each package is made for one kind of processor, named in its file name:

| Name | Runs on |
|---|---|
| `AVX2` (`linux-x64-avx2`) | Most x64 processors from 2013 on |
| `SSE4` (`linux-x64-sse4`) | Older x64 processors |
| `arm64` (`linux-arm64-armv8`) | 64-bit ARM (checked under emulation so far, not yet on an ARM64 PC) |

To see whether yours has AVX2, run `grep -m1 -o avx2 /proc/cpuinfo`: it prints `avx2` when it has. The
portable launcher checks this too and starts nothing on a processor its package cannot run.

## 2. The `.deb` package

```bash
sudo apt install ./thoron-<version>-linux-x64-avx2.deb
```

The SSE4 build is the package `thoron-browser-sse4` (the AVX2 build and the ARM64 one are `thoron-browser`).
The two x64 packages exclude each other, so an update never swaps one for the other.

- The program goes to `/opt/kuchisofts/thoron`; start it from the menu (**Thoron**) or with
  `thoron-browser`.
- Your profile is `~/.config/thoron`. It stays when you install a newer version and when you remove
  Thoron.
- It installs beside upstream Thorium (`thorium-browser`), which keeps its own profile in
  `~/.config/thorium`; neither touches the other's.
- Ubuntu 23.10 and later let only programs named in an AppArmor profile use the user namespaces the
  browser's sandbox needs. The package brings its own profile (`/etc/apparmor.d/thoron-browser`), so the
  sandbox works without anything else to do.
- Saved passwords use your desktop's keyring (GNOME's, under the name `Chromium Safe Storage`, the same as
  Thorium's), so a profile brought over from Thorium keeps its passwords readable.

**A newer version:** install the newer `.deb` the same way, or let apt bring it from Thoron's signed
repository (section 2a).

### 2a. Updates through apt

Thoron's APT repository is signed with Thoron's own key, and apt trusts that key for this repository only
([how it is made](../release/APT.md)). **It goes live with the first release**, once the owner's signing key
exists (ROADMAP P2.10, P2.11); until then these steps have nothing to fetch.

```bash
curl -fsSLo /tmp/thoron-archive-keyring.gpg https://github.com/KuchiSofts/thoron/releases/download/apt/thoron-archive-keyring.gpg
gpg --show-keys /tmp/thoron-archive-keyring.gpg   # its fingerprint must be the one in Thoron's README
sudo install -m 0644 /tmp/thoron-archive-keyring.gpg /usr/share/keyrings/thoron-archive-keyring.gpg
sudo tee /etc/apt/sources.list.d/thoron.sources > /dev/null <<'EOF'
Types: deb
URIs: https://github.com/KuchiSofts/thoron/releases/download/
Suites: apt/
Signed-By: /usr/share/keyrings/thoron-archive-keyring.gpg
EOF
sudo apt update
sudo apt install thoron-browser        # or thoron-browser-sse4 on an x64 processor without AVX2
```

apt then refuses an index that is not signed by that key, one that was changed, and one past its expiry
date, so an old index cannot be served again to hold back an update.

**Remove it:** `sudo apt remove thoron-browser`. Your profile stays in `~/.config/thoron`; delete that
folder yourself only if you want your bookmarks, passwords and history gone for good.

## 3. The portable package

```bash
tar -xf thoron-<version>-linux-x64-avx2-portable.tar.xz
./ThoronPortable/thoron
```

- The profile is the folder's own `User Data`, and crash reports stay in it too: nothing is written to
  `~/.config/thoron`.
- You can rename or move the folder; Thoron starts from it with the same profile. The folder's name may
  hold spaces and letters of any language.
- On Ubuntu 23.10 and later the launcher may say that this Linux lets only programs with an AppArmor
  profile use the sandbox. A portable copy has none, and Thoron never runs without its sandbox. An
  administrator can add a profile for the folder's program (the folder's `README.txt`, "The sandbox",
  says how), or install the `.deb`, which brings its own.
- `chrome://thoron-portable` locks the copy's saved passwords and cookies with a passphrase; from then on the
  `thoron` file asks for it at each start ([Portable passphrase](PORTABLE_PASSPHRASE.md#5-on-linux)).

**A newer version:** a Linux portable copy looks for updates from inside Thoron, but there is no signed
release for it to find yet (ROADMAP P2.11, P3.23). Until then, unpack the newer package and move your old
folder's `User Data` into it (with Thoron closed).

## 4. For this user only

The portable folder can also install Thoron for you alone, without administrator rights:

```bash
./ThoronPortable/install-for-this-user
```

- The program goes to `~/.local/share/thoron`, with a menu entry (**Thoron**). Its profile is
  `~/.config/thoron`, as the `.deb`'s, never in the program's folder.
- A systemd user timer (`thoron-update.timer`) starts Thoron once a day, with no window and a profile folder
  of its own, to look for an update while Thoron is closed; the look ends by itself. Without a published
  release key (there is none yet) it finds nothing to install.
- On Ubuntu 23.10 and later, as for the portable copy, an administrator must allow the sandbox once with an
  AppArmor profile (the folder's `README.txt`, "The sandbox"); Thoron itself never asks for `sudo`.

**Remove it:** `~/.local/share/thoron/install-for-this-user --remove` takes away the program, the menu
entry and the timer. Your profile stays in `~/.config/thoron`.

## 5. Bring your data over

Thoron's Settings import reads other browsers in `~/.config` (Thorium, Chrome, Edge, Brave, Vivaldi,
Opera, Chromium): see [Import](IMPORT.md).
