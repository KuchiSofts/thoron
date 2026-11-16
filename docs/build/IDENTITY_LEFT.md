# What still carries Thorium's name (ROADMAP B.3)

The identity step ([`tools/build/thoron_identity.py`](../../tools/build/thoron_identity.py)) renames
Thorium to Thoron wherever a person reads the product's name. Three kinds of "Thorium" are left in a
Thoron build on purpose. This page lists them, says why, and proposes how the first kind can change.
[`tools/qa/identity_check.py`](../../tools/qa/identity_check.py) reads a build and its installer and
reports every "Thorium" that is on none of these lists.

Checked against the patched Chromium 158 tree and the installer of build 158.0.8127.3010 on 2026-11-16.
Nothing here was read from a registry: the values come from the source and from the installer's files.

## 1. Names an installed copy is found by

Not renamed by the identity step. A wrong rename here loses an install, a profile or a setting.

Thoron's own names are already Thoron's and stay as they are: the folder `%LOCALAPPDATA%\Thoron`
(program and profile), the registry key `Software\Thoron`, the entry
`Software\Microsoft\Windows\CurrentVersion\Uninstall\Thoron` in Windows' list of apps, the app GUID, the
app ID `Thoron`, the ProgIDs `ThoronHTM` and `ThoronPDF` and the COM class IDs (`THORON_IDS` and
`chromium_install_modes.h`). The setup program writes all of them.

Still Thorium's:

| Name | Where | What reads it | Effect today |
|---|---|---|---|
| `Software\Microsoft\Windows\CurrentVersion\Uninstall\Thorium` | `mini_installer_constants.cc` (`kUninstallRegistryKey`), from upstream's `mini_installer.patch` | The mini installer reads `InstallLocation` there to tell a first install from an update, and to start the browser after a first install | It never finds Thoron, whose entry is `...\Uninstall\Thoron`. Every run with the dialog counts as a first install: the setup program is told not to start the browser, and the mini installer's own start after the result page finds no folder. So the dialog starts no browser after an install or an update (read from the code, not tried). With Thorium installed too, the run counts as an update and the setup program decides by itself. Read only |
| `Software\Thorium` | The same file: `kCleanupRegistryKey`, `kClientsKeyBase`, `kClientStateKeyBase` | The first: the value `ChromeInstallerCleanup`, a developer's switch that keeps the unpacked files. The other two are used only in a Google Chrome build | None for a user. Read only |
| `SOFTWARE\Thorium\NativeMessagingHosts` | `launch_context_win.cc`, from upstream's `thorium-common-branding-paths.patch` | The browser looks there for the helper programs of extensions (native messaging hosts), then under Chrome's key | A helper registered for Thorium is found by Thoron too. Most helpers register under Chrome's key |
| `Software\Thorium` | `chrome_launcher_support.cc` (`kInstallationRegKey`), from `thorium-install-static-branding.patch` | Two helper libraries Thoron does not ship | In no shipped file |
| `Thorium/External Extensions`, `/Library/Application Support/Thorium/NativeMessagingHosts` | `chrome_paths.cc` | macOS only | Thoron has no macOS build |

### Proposal

1. **The mini installer's keys: align them, no migration needed.** Thoron stores nothing under
   Thorium's names, so nothing has to move: the setup program already writes `Software\Thoron` and
   `...\Uninstall\Thoron`, and the mini installer should read the same. Two more lines for the file's
   entry in `EXE_EDITS`:

   ```python
   ('L"Software\\\\Thorium"', 'L"Software\\\\Thoron"', 3),
   ('Uninstall\\\\Thorium"', 'Uninstall\\\\Thoron"', 1),
   ```

   It is not done yet because it changes what the installer does, not only what it shows: after a
   first install the browser starts when the result page is closed with OK, and an update no longer
   counts as a first install. That needs an install test first: a first install, an update, and both
   again next to an installed Thorium, whose keys must stay untouched. It fits the one installer of
   ROADMAP **P3.19**.
2. **Native messaging hosts: read Thoron's key first, keep the others.** A patch, not a text edit: look
   under `SOFTWARE\Thoron\NativeMessagingHosts`, then under Thorium's key, then under Chrome's. Nothing
   stops working, and a helper can register for Thoron alone. Thorium's key can go in a later release,
   with a line in the release notes.
3. **If one of Thoron's own names ever has to change** (folder, registry key, entry in the list of apps):
   do it in the setup program at update time, in one run and in this order: read the old place, write
   the new one, re-make the shortcuts and the default-browser registration, remove the old entry; keep
   reading the old place as a fallback for some releases; never move a profile folder while the browser
   runs. Do not change the app ID: Windows ties taskbar pins and notifications to it.

## 2. Credits and the names of upstream's own work

Kept, and meant to stay:

- the About page's line "Thoron is an independent browser by KuchiSofts, based on Thorium by Alex313031
  ...", and the copyright lines "The Chromium Authors, Alex313031 and KuchiSofts";
- `chrome://credits`: Thorium's entry with its licence and links. Its first line now reads "Thoron is
  based on Thorium and Chromium and is made available as source code here. Thorium source code is
  available here", each with its own link;
- `chrome://authors`, titled "Thorium Authors": upstream's list of authors;
- the flags "Enable Experimental Thorium 2024 (Th24) UI" and "Disable Thorium Custom Icons" and the
  texts that name "Thorium 2024" or "Thorium's custom icons": upstream's interface design and icon set,
  by their names;
- the names of upstream's patches and files in the source, and every licence header.

## 3. Names no page shows

- the internal names of flags and switches (`thorium-2024`, `disable-thorium-icons`,
  `disable-thorium-dns-config`, `thorium-internal-url-scheme`) and of features (`Thorium2024`):
  renaming one drops the choice a person saved for it;
- resource and file names inside the program (`thorium_version.txt`, `*_thorium.svg`, `IDR_THORIUM_*`),
  the style name `thorium-2024` and the environment variable `THORIUM_DEBUG`;
- the address alias `thorium://`: a typed `thorium://flags` still opens the page. Internal pages are
  shown as `chrome://` again, as in Chromium; the flag "Use thorium:// for internal URLs" turns upstream's
  display back on;
- texts about ChromeOS ("ThoriumOS", "ThoriumVox", upstream's name for its ChromeOS build): packed with
  every language. Thoron has no ChromeOS build; on Windows or Linux they show at most in the permission
  list of an extension made for ChromeOS. There is no "ThoronOS" to rename them to.

## 4. Open choices

- **`thoron://` as the alias.** Possible as a patch on upstream's two alias patches (the scheme's name
  in `content/public/common/url_constants.h` and the few places that spell it out), with `thorium://`
  still accepted. It is new behaviour, not a text, so it was not done in the identity step.
- **The version in the installer's dialog title.** It shows the build version ("Thoron 158.0.8127.x").
  The template can also use `@THORON_VERSION@` from `chrome/VERSION` ("Thoron 0.1.1").

## Checking a build

```powershell
py -3 -I tools\qa\identity_check.py --build <Chrome-bin> --installer <mini installer> `
    --sevenzip <7za.exe> --brotli <brotli.exe> --work <scratch dir>
```

`7za.exe` is in the Chromium tree (`third_party\lzma_sdk\bin\win64`), `brotli.exe` in the build's
output folder. Without them the setup program inside the installer and the pages packed with brotli are
not read, and the report says so. The check sorts every "Thorium" it finds into `seen` (to fix),
`unsorted` (to look at), `identity` (section 1), `kept` (section 2), `chromeos` and `internal`
(section 3), and passes when the first two are empty. It reads files only: what a default or a switch
decides in the running browser, like the address alias, it cannot see.
