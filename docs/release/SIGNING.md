# Code signing of the Windows programs (ROADMAP S.8)

Every program and library a Windows release of Thoron holds is signed with Authenticode once Thoron has a code
signing certificate: Windows then names the publisher in its security questions, and SmartScreen can learn the
publisher's reputation. The tools are ready; the certificate is the owner's to get.

## 1. What is signed, and where

| What | Signed by |
|---|---|
| The programs and libraries inside the installer (`thoron.exe`, `chrome.dll`, the helpers, `ThoronSetup.exe`), and `setup.exe` | the installer's archive step, in its own staging folder, when the build has `thoron_authenticode_command_file` |
| The installer itself, `ThoronSetup.exe` in the release folder, the portable package's launcher and updater, the `setup.exe` an installed copy's delta carries | `tools/release/release.py prepare --authenticode-command`, on the copies it puts into the release |

The build's own files are never signed in place: the build links a program again when its file has changed
(checked on 2026-11-22: one changed program in an up-to-date build, and the next build linked it again), so a
signature put there would be gone at the next build. Signing the copies the installer packs avoids that.

Each signature uses SHA-256 and carries an RFC 3161 timestamp from the certificate issuer's timestamp server,
so it stays valid after the certificate expires. The certificate is picked from the Windows certificate store
by its SHA-1 thumbprint: its private key stays in the store or on the hardware token the issuer requires, never
in a file or on a command line.

## 2. Signing a release

1. **The certificate (owner).** A code signing certificate from a certificate authority (an EV certificate
   builds SmartScreen reputation at once). Install it as the issuer says, so it is in the Windows certificate
   store of the account that makes the release, and note its SHA-1 thumbprint and the issuer's timestamp
   server.
2. **The signing command.** A file outside the repository, for example `C:\thoron-signing\sign.json`, holding
   the command as a JSON list; the files to sign are appended to it:

   ```json
   ["py", "-3", "-I", "C:/thoron/tools/release/authenticode.py", "sign",
    "--thumbprint", "<the certificate's SHA-1 thumbprint>", "--timestamp", "<the issuer's RFC 3161 URL>"]
   ```

   `authenticode.py sign` finds `signtool.exe` in the Windows SDK (or takes `--signtool`), signs, and checks
   every file it signed: signed, trusted by Windows, timestamped.
3. **The build.** In the release build's `args.gn`:

   ```gn
   thoron_authenticode_command_file = "/C:/thoron-signing/sign.json"
   ```

   then build `mini_installer` as in [docs/build/WINDOWS.md](../build/WINDOWS.md). Only the archive step and
   the installer's own link run again when this changes.
4. **The release.** Give the same file to `release.py prepare --authenticode-command C:\thoron-signing\sign.json`.
   It refuses the release when a program inside the installer (its `Chrome-bin`) is not signed, signs the copies
   of section 1, and checks every program of the release folder before it writes `SHA256SUMS`. Without the
   option it says that the programs are not signed.
5. **A check at any time:** `py -3 -I tools/release/authenticode.py check <folder or files>`.

## 3. What is tested, and what is not yet

- `authenticode.py` in Windows Sandbox with a throwaway certificate trusted in the Sandbox only: three of the
  build's programs signed with SHA-256 and a timestamp from a public timestamp server (which receives only a
  hash), checked, then one byte of one changed: the check refuses it (hash mismatch).
- The installer's archive step with a stand-in signer: it was given the 14 programs and libraries of the staged
  `Chrome-bin` and the staged `setup.exe`, nothing of the build's own, which stayed byte for byte; the installer
  builds with and without the setting.
- `release.py`: unit tests of the signer, the copies, the checksums of the signed bytes and the refusal of an
  unsigned program.
- Not yet: a release signed with Thoron's own certificate, which waits for the certificate (S.8).
