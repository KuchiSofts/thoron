# Install Thoron on Windows

Thoron for Windows x64 comes in two forms:

- **Portable:** one folder that you unpack and start. Nothing is installed, and your profile stays inside
  the folder.
- **Installed:** an installer puts Thoron into your own Windows account.

**There is no public release yet.** The first one is Thoron 0.1.1 for Windows x64. Until then these
packages exist only for people who build Thoron themselves ([build guide](../build/WINDOWS.md)). Linux and
ARM64 follow later (ROADMAP P2.9, P2b.1).

## 1. Which package fits your processor

Every Windows package is made for one kind of processor, and its file name says which:

| In the file name | For |
|---|---|
| `win-x64-avx2` | x64 processors with AVX2. The faster build: try this one first |
| `win-x64-sse4` | Older x64 processors without AVX2 (they need SSE4.2 at least) |

The SSE4 build is part of ROADMAP P2.7, which is not finished, so the first packages may be AVX2 only.

**Not sure which processor you have?** Take the portable AVX2 package and start it (section 2). Its
launcher checks the processor first. When the package does not fit, it shows a message and starts nothing:

| The launcher says | What to do |
|---|---|
| "This copy of Thoron is made for processors with AVX2, which this computer's processor does not have. The SSE4 version of Thoron runs here: download it from the same page and put your "User Data" folder into it to keep your profile." | Take the `win-x64-sse4` package |
| "This computer's processor is too old for Thoron: it needs SSE4.2 at least." | Thoron does not run on this PC |
| "This copy of Thoron is made for a kind of processor this launcher does not know. Unpack the whole package again, or download the package for this computer." | The file `variant` is damaged or was changed: unpack the package again |

An **installed** AVX2 build does not check: on a processor without AVX2 it stops at once, without a
message. Only the portable launcher tells you.

## 2. The portable package

The file is called `thoron-<version>-<variant>-portable.zip`, for example
`thoron-158.0.8127.3010-win-x64-avx2-portable.zip`.

1. Download the `.zip` for your processor from the
   [releases page](https://github.com/KuchiSofts/thoron/releases).
2. Check the download as the README shows in
   [Verifying downloads](../../README.md#verifying-downloads).
3. Right-click the `.zip`, choose **Extract All...** and pick a folder your account can write to: your
   Documents, the Desktop or a USB drive. Not `C:\Program Files`: the launcher must be able to make the
   profile folder there.
4. Open the unpacked `ThoronPortable` folder and start **`Thoron.exe`**.
5. Windows may show "Windows protected your PC", because Thoron's programs are not signed yet (ROADMAP
   S.8). If you checked the download in step 2, choose **More info**, then **Run anyway**.

### What the folder holds

```
ThoronPortable\
    Thoron.exe      the launcher: always start Thoron with this one
    README.txt      a short note
    variant         which processors this copy is made for
    Application\    the browser; the file "current" names the version that starts
    User Data\      your profile; made at the first start
```

Good to know:

- **Always start `Thoron.exe`.** The `thoron.exe` inside `Application`, started on its own, uses the PC's
  own profile and not the one in the folder.
- Nothing in the folder holds a full path, so the folder can be moved and renamed.
- No console window opens. The launcher starts the browser and ends.
- A portable copy still leaves a few traces on the PC: some registry values under `HKCU\Software\Thoron`
  (the browser engine writes them; an installed Thoron uses the same ones), sometimes a temporary folder,
  your downloads in the PC's Downloads folder, and what Windows itself records about programs that ran. The
  details are in [PORTABLE.md](../release/PORTABLE.md#4-what-stays-in-the-folder-and-what-a-portable-copy-leaves-on-the-pc).
- Saved passwords and sign-ins are locked to your Windows account: read
  [Portable passphrase](PORTABLE_PASSPHRASE.md) before you save any.
- A portable copy does not update itself yet: see [Updates](UPDATES.md#5-update-a-portable-copy-by-hand).
- The offers of the first start (import, default browser) are not made for portable copies yet (ROADMAP
  P3.21).

### Moving it, and USB drives

1. Close Thoron: every window.
2. Move or copy the whole `ThoronPortable` folder. You may rename it.
3. Start `Thoron.exe` in the new place. Your profile comes along.

On a USB drive:

- Thoron starts from any folder on the drive or from the drive's root. This was tested with a drive letter
  that Windows' `subst` makes, not yet on a real USB drive (its file system, its speed, pulling it out).
  That test is still open (ROADMAP P2.8, P3.12).
- Close Thoron before you remove the drive.
- On a write-protected drive the launcher says "Thoron cannot use the "User Data" folder beside it: the
  drive is write-protected, or a file has that name. Nothing was started, so that nothing is written to
  this computer instead."
- On another PC or another Windows account your bookmarks, history, settings and extensions come along,
  but saved passwords and sign-ins cannot be read there and may be lost
  ([why](PORTABLE_PASSPHRASE.md)).
- A drive formatted with FAT or exFAT has no file permissions: whoever holds the drive can change the
  program on it.

## 3. The installer

**What exists today:** the full installer of a build. A release will hold it as
`thoron-<version>-<variant>-installer.exe`, one for each processor variant (section 1).

1. Download the installer for your processor from the
   [releases page](https://github.com/KuchiSofts/thoron/releases).
2. Check the download ([Verifying downloads](../../README.md#verifying-downloads)).
3. Run it from a folder your account can write to, such as Downloads (it unpacks its files beside itself;
   from a read-only folder it stops and shows the code 109). Windows may warn about an unknown publisher, as in
   section 2, step 5.
4. It asks whether to install Thoron: choose **Install**. When it is done it says so: choose **OK**.
5. It installs Thoron for your Windows account only, into `%LOCALAPPDATA%\Thoron`: the program in
   `Application`, your profile in `User Data`. It needs no administrator rights.
6. Thoron is then in Windows' list of installed apps with its version. The program is
   `%LOCALAPPDATA%\Thoron\Application\thoron.exe`.

**For every user of the PC.** Someone with administrator rights can run the installer with
`--system-level`: Thoron then goes into `C:\Program Files\Thoron`, and each user still has a profile of
their own. Such a copy does not update itself, because the browser never asks for administrator rights: the
About page says when a newer release is out, and someone with administrator rights installs it the same
way. Installing it while Thoron runs closes Thoron after asking it to save its tabs.

Thoron installs next to Thorium and leaves it as it was: it has its own folder, program file, registry
key and file associations, and either one can be removed without affecting the other. To bring your
Thorium profile over, see [Import](IMPORT.md).

**Not released yet:**

| What | Stage |
|---|---|
| `ThoronSetup.exe`: one small installer that always installs the newest release | P3.19 |
| The import offer in the installer and in Settings | P3.13 |
| The first start's offers: import from your other browser, make Thoron the default browser | P3.21 |
| Updates by itself ([Updates](UPDATES.md)) | P3.20 |
| Signed checksums of a release | P2.11 |
| Signed programs, so Windows does not warn | S.8 |

## 4. Remove Thoron

**A portable copy:**

1. Close Thoron.
2. If you want to keep your profile, copy the `User Data` folder somewhere first.
3. Delete the `ThoronPortable` folder.

The registry values named in section 2 stay behind.

**An installed Thoron:**

1. Close Thoron.
2. To be safe, copy `%LOCALAPPDATA%\Thoron\User Data` somewhere first.
3. Open Windows **Settings**, then **Apps**, then **Installed apps**. Find Thoron, open its **...** menu and
   choose **Uninstall**.
4. Leave the box that also deletes your browsing data unticked: then your profile stays in
   `%LOCALAPPDATA%\Thoron\User Data`. Tick it only if you want your profile gone.

Keeping the profile by default is Thoron's rule, and it is checked on a clean Windows for every build
(install, first start, update and uninstall: [the installer page](../release/INSTALLER.md)). Step 2 is a
precaution all the same. Removing Thoron does not touch Thorium.
