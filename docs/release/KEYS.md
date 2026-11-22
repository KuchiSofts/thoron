# Thoron's release keys (ROADMAP P2.11)

Four keys sign what Thoron publishes. They are made once, on a system with no network, and kept in a backup
encrypted with a passphrase. They are on the release computer only while a release is signed. This page holds
no secret: only how the keys are made, kept, used and checked, and where their public halves go.

## 1. The keys

| Key | Signs | Its public half is in |
|---|---|---|
| `update-manifest.key` (Ed25519) | `update.json`, which the built-in updater trusts ([MANIFEST.md](../update/MANIFEST.md)) | every build: GN `thoron_update_public_key`; `release.py --manifest-public-key` |
| `adblock-resources.key` (Ed25519) | Thoron adblock's scriptlets and stand-ins | every build: `kResourcesPublicKey` in `components/thoron_adblock/list_store.cc` |
| `minisign.key` (minisign, Ed25519) | `SHA256SUMS` of each release (`SHA256SUMS.minisig`) | the README and the release notes, for people who check a download |
| `apt-gnupg/` (OpenPGP, Ed25519) | the APT repository's `InRelease` ([APT.md](APT.md)) | `thoron-archive-keyring.gpg` beside the repository; its fingerprint in the README |

The APT key has two parts: a root that only certifies, and a subkey that signs. Only the subkey is ever
unlocked for a release. If it is lost or leaks, the root revokes it and certifies a new one, and apt follows that.
The root's revocation certificate is in the backup (`openpgp-revocs.d`).

## 2. How they are kept

- The backup is one file, `thoron-keys-<date>.thoronkeys`. It holds all four keys and their public halves,
  encrypted with AES-256-GCM under a key derived from the passphrase with scrypt (N 2^18, r 8, p 1: 256 MiB and
  about a second for each guess). Its header is authenticated too, so a changed byte anywhere fails.
- It is kept in two places: two USB sticks, or one stick and a cloud folder (the file is encrypted).
- The passphrase is at least 20 characters (six or more random words are good). It is typed, never given
  on a command line or in a file. Write it on paper and keep the paper apart from the backup. Without the
  passphrase the keys are lost, and so is the built-in updater's trust (section 6).
- Unencrypted keys never go into a git repository or a folder a cloud service synchronises: `key_ceremony.py`
  refuses both. `release.py` refuses a key inside the repository, the build tree or the release folder.

## 3. The ceremony (owner, once)

On Windows, the ceremony runs in a Windows Sandbox with no network. The keys exist unencrypted only inside
the Sandbox, and Windows deletes it when it shuts down. The Sandbox can read the ceremony, this Python with
`cryptography`, and Git for Windows (its GnuPG); it can write only to the folder you name.

1. Turn on Windows Sandbox if it is off (Windows features), and plug in a USB stick.
2. Run, naming a new folder on the stick:

   ```powershell
   py -3 -I tools/release/key_ceremony_sandbox.py --out <stick>\thoron-keys
   ```

3. A console window opens in the Sandbox. Type the passphrase twice for the backup, then once more for the
   restore test, and press Enter at the end. The Sandbox shuts itself down.
4. `<stick>\thoron-keys` now holds `thoron-keys-<date>.thoronkeys` and `public\`. Copy the backup file to a second
   place.
5. Hand over `public\`: it holds only public keys. They go into the build and the README (section 1).

Without Windows Sandbox, the same steps run on a computer with no network (cable out, Wi-Fi off). `make`
refuses to run while the computer has a network route:

```
py -3 -I tools/release/key_ceremony.py make --out <folder on an encrypted disk or a stick>
py -3 -I tools/release/key_ceremony.py backup --keys <folder> --out <stick>\thoron-keys.thoronkeys
py -3 -I tools/release/key_ceremony.py restore-test --backup <stick>\thoron-keys.thoronkeys --public <folder>\public
py -3 -I tools/release/key_ceremony.py lock --keys <folder>
```

`lock` overwrites every file and deletes the folder. On an SSD old blocks can stay readable, which is why the
keys are made in a throwaway system or on an encrypted disk.

## 4. Signing a release

```
py -3 -I tools/release/key_ceremony.py unlock --backup <stick>\thoron-keys.thoronkeys --out <folder>
```

`unlock` writes the two Ed25519 keys, `minisign.key`, and a GnuPG home holding only the APT signing subkey (the
root stays in the backup). It prints the options to use: `release.py prepare --minisign-key --manifest-key
--adblock-key`, and `apt_repo.py --gnupg-home --key`. When the release is signed:

```
py -3 -I tools/release/key_ceremony.py lock --keys <folder>
```

`py -3 -I tools/release/key_ceremony.py show --public <folder>\public` prints where each public half goes,
including the C++ array for `kResourcesPublicKey`.

## 5. Checking the backup

`restore-test` decrypts the backup into a temporary folder and signs a test message with every key. Each
signature must verify under the public halves as published, the APT one under a GnuPG home that holds only the
published keyring, and made by the subkey. The test also checks that the root's secret and its revocation
certificate are there, then deletes the folder. Run it after every copy to a new medium, and once a year.

What was tested on 2026-11-22, with throwaway keys deleted afterwards:

- In a Windows Sandbox with no network, the whole ceremony ran and marked the keys as made offline. Only the backup, the
  public halves and the result came out, and the backup then restored and passed the restore test outside the
  Sandbox.
- On Linux, in a network namespace with no interface, every command ran. The real minisign 0.11 signed with the
  ceremony's key without asking anything and verified with the published key, and the ceremony's code read a
  key minisign made itself. `apt_repo.py` signed with the unlocked subkey and `gpgv` verified `Release.gpg` and
  `InRelease` under the published keyring. The published key's times are midnight UTC, and it names no e-mail.
  A wrong passphrase was refused. With a network, `make` refused to run.
- In the unit tests (`tools/release/tests/test_key_ceremony.py`, `test_key_ceremony_sandbox.py`), a changed byte,
  a wrong passphrase, a changed header and a path out of the folder are refused, and nothing is written over a
  file. `lock` deletes nothing but a key folder.

## 6. Why it is made this way

- The update key is the root itself, unlocked only for a release. A separate online key introduced by a key
  statement (P4.7) would not help: a copy of Thoron keeps every key it has learned, and there is no revocation,
  so a leaked online key would stay trusted.
- Nothing expires. An expiry date that passes would cut every installed copy off from its updates, and a
  renewed key could not reach them. A leaked APT subkey is revoked by the root instead.
- minisign's own passphrase is not used. One passphrase protects everything, so there is one thing to
  remember; the backup is what protects the key.
- The APT key's creation time is midnight UTC of the ceremony day, so the published key tells no hour.
  The Ed25519 and minisign keys hold no time.
- The offline check sends nothing. It asks the system for a route to a documentation address (192.0.2.1,
  2001:db8::1) over a UDP socket, which sends no packet.

## 7. Loss and compromise

- If the backup or its passphrase is lost, no new key can be introduced, because only the old key can sign a key
  statement. Installed copies would never verify an update again, and people would have to install Thoron anew.
  This is why there are two copies, and a restore test every year.
- If the update key leaks, someone could sign an update that copies trust. Rotation (P4.7) adds a new key but
  does not remove the old one. A leak is announced at once, and copies are moved to a new key with the
  affected releases named in the notes. A second update key kept in another place, compiled in beside the first,
  would answer loss and theft better; that is open question 1 of the
  [threat model](../security/THREAT_MODEL.md) and needs the updater to trust two built-in keys.
- If the APT subkey leaks, the root revokes it and certifies a new subkey; the new keyring is published beside
  the repository.
- If the minisign key leaks, a new key is made and published in the README and the release notes, and the old
  one is named there as no longer used.
