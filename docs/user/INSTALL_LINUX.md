# Install Thoron on Linux

Thoron for Linux x64 (Ubuntu 24.04 and newer, and other Debian-based systems) comes in two forms:

- **The `.deb` package:** installed for the whole computer, with a menu entry and the command
  `thoron-browser`. Installing it needs administrator rights (`sudo`).
- **Portable:** one folder that you unpack and start. Nothing is installed, and your profile stays inside
  the folder.

**There is no public release yet.** Until the first one, these packages exist only for people who build
Thoron themselves ([build guide](../build/LINUX.md)). ARM64 follows later (ROADMAP P2b.2).

## 1. Which package fits your processor

Each package is made for one kind of processor, named in its file name:

| Name | Runs on |
|---|---|
| `AVX2` (`linux-x64-avx2`) | Most x64 processors from 2013 on |
| `SSE4` (`linux-x64-sse4`) | Older x64 processors |

To see whether yours has AVX2, run `grep -m1 -o avx2 /proc/cpuinfo`: it prints `avx2` when it has. The
portable launcher checks this too and starts nothing on a processor its package cannot run.

## 2. The `.deb` package

```bash
sudo apt install ./thoron-browser_<version>_AVX2.deb
```

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

**A newer version:** install the newer `.deb` the same way. Updates through apt from Thoron's own signed
repository come later (ROADMAP P2.10).

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

**A newer version:** a Linux portable copy does not update itself from inside Thoron yet (ROADMAP P3.23).
Unpack the newer package and move your old folder's `User Data` into it (with Thoron closed).

## 4. Bring your data over

Thoron's Settings import reads other browsers in `~/.config` (Thorium, Chrome, Edge, Brave, Vivaldi,
Opera, Chromium): see [Import](IMPORT.md).
