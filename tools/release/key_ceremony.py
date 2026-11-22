#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron's release keys (ROADMAP P2.11, docs/release/KEYS.md): made once on a computer with no network, kept
in a backup encrypted with a passphrase, and unlocked only for the time a release is signed.

    make          --out <new folder>           the four keys and, in <folder>/public, their public halves.
                                               Refused while the computer has a network route, unless
                                               --allow-network: such keys are marked as test keys
    backup        --keys <folder> --out <new file>
                                               checks the keys against their public halves, then writes the
                                               whole folder encrypted (scrypt, AES-256-GCM) and reads it back
    restore-test  --backup <file> --public <folder>
                                               decrypts into a temporary folder, signs with every key, checks
                                               each signature against the public halves as published, and
                                               deletes the temporary folder
    unlock        --backup <file> --out <new folder>
                                               the keys a release signs with; the APT key's root stays in the
                                               backup (only its signing subkey is unlocked)
    lock          --keys <folder>              deletes a made or unlocked folder, every file overwritten first
    show          --public <folder>            where each public half goes

The keys:
    update-manifest.key    Ed25519, 32 bytes in base64: signs update.json (docs/update/MANIFEST.md). Its public
                           half is built into Thoron (GN thoron_update_public_key) and is release.py's
                           --manifest-public-key
    adblock-resources.key  Ed25519, the same form: signs Thoron adblock's scriptlets and stand-ins
                           (kResourcesPublicKey in components/thoron_adblock/list_store.cc)
    minisign.key           minisign: signs SHA256SUMS (SHA256SUMS.minisig); public key minisign.pub, in the
                           README. Not encrypted by minisign itself: the backup is what protects it
    apt-gnupg/             a GnuPG home: an Ed25519 root that only certifies, and an Ed25519 subkey that signs
                           the APT repository's InRelease; public keyring thoron-archive-keyring.gpg; the root's
                           revocation certificate is in openpgp-revocs.d

Passphrases are typed, never given on a command line or read from a file, and no private key is printed. The
key folders are refused in a git repository or in a folder a cloud service synchronises; the encrypted backup
may be kept anywhere.

    py -3 -I tools/release/key_ceremony.py make --out <stick>\\thoron-keys
    py -3 -I tools/release/key_ceremony.py backup --keys <stick>\\thoron-keys
        --out <other stick>\\thoron-keys.thoronkeys
    py -3 -I tools/release/key_ceremony.py restore-test --backup <other stick>\\thoron-keys.thoronkeys
        --public <stick>\\thoron-keys\\public
"""
from __future__ import annotations

import argparse
import base64
import calendar
import functools
import getpass
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.update import manifest as mf  # noqa: E402

UPDATE_KEY, ADBLOCK_KEY, MINISIGN_KEY = "update-manifest.key", "adblock-resources.key", "minisign.key"
APT_HOME, PUBLIC = "apt-gnupg", "public"
PUBLIC_JSON, MINISIGN_PUB, KEYRING = "PUBLIC-KEYS.json", "minisign.pub", "thoron-archive-keyring.gpg"
TOP = (UPDATE_KEY, ADBLOCK_KEY, MINISIGN_KEY, APT_HOME, PUBLIC)
APT_NAME = "Thoron archive signing key"
MAGIC = b"THORON-KEYS\n"
SCRYPT = {"n": 2 ** 18, "r": 8, "p": 1}        # 256 MiB and about a second for each guess
MIN_PASSPHRASE = 20
MAX_BACKUP = 64 * 1024 * 1024
SYNCED = ("onedrive", "google drive", "googledrive", "my drive", "dropbox", "icloud", "box sync", "pcloud")
TEST_MESSAGE = b"Thoron key ceremony: a restored key signs, and its published public half verifies.\n"
# Connecting a UDP socket sends nothing; it only asks the system for a route. These are documentation addresses.
ROUTE_PROBES = ((socket.AF_INET, ("192.0.2.1", 9)), (socket.AF_INET6, ("2001:db8::1", 9)))


class CeremonyError(RuntimeError):
    pass


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# --- where keys may be -------------------------------------------------------------------------------------------

def network_route() -> bool:
    """True when the computer could send to the internet now (it has a route to an address outside it)."""
    for family, address in ROUTE_PROBES:
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as s:
                s.connect(address)
                return True
        except OSError:
            continue
    return False


def private_place_problem(folder: Path) -> str | None:
    """Why `folder` must not hold private keys: inside a git repository, or synchronised by a cloud service."""
    where = folder.resolve()
    if any(name in str(where).lower() for name in SYNCED):
        return f"{folder} looks like a folder a cloud service synchronises; private keys never go there"
    for parent in (where, *where.parents):
        if (parent / ".git").exists():
            return f"{folder} is inside a git repository ({parent}); private keys are kept out of every repository"
    return None


def new_folder(folder: Path) -> Path:
    problem = private_place_problem(folder)
    if problem:
        raise CeremonyError(problem)
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        raise CeremonyError(f"{folder} exists and is not an empty folder; keys are never written over anything")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def wipe(folder: Path) -> None:
    """Every file overwritten with zeros, then the folder deleted. On an SSD old blocks can stay readable, which is
    why keys are made and unlocked in a throwaway system or on an encrypted disk (docs/release/KEYS.md)."""
    for root, dirs, files in os.walk(folder, followlinks=False):
        for name in files:
            path = Path(root) / name
            if path.is_symlink() or not path.is_file():
                continue
            try:
                size = path.stat().st_size
                with open(path, "r+b") as f:
                    f.write(bytes(size))
                    f.flush()
                    os.fsync(f.fileno())
            except OSError:
                pass
    shutil.rmtree(folder, ignore_errors=True)


# --- Ed25519 and minisign ----------------------------------------------------------------------------------------

def _ed():
    from cryptography.hazmat.primitives.asymmetric import ed25519
    return ed25519


def ed25519_new() -> tuple[bytes, bytes]:
    """A new key pair: (private 32 bytes, public 32 bytes)."""
    from cryptography.hazmat.primitives import serialization as s
    key = _ed().Ed25519PrivateKey.generate()
    return (key.private_bytes(s.Encoding.Raw, s.PrivateFormat.Raw, s.NoEncryption()),
            key.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw))


def ed25519_signs(private: bytes, public: bytes) -> bool:
    """The private key signs TEST_MESSAGE and the public key verifies the signature."""
    from cryptography.exceptions import InvalidSignature
    try:
        signature = _ed().Ed25519PrivateKey.from_private_bytes(private).sign(TEST_MESSAGE)
        _ed().Ed25519PublicKey.from_public_bytes(public).verify(signature, TEST_MESSAGE)
    except (InvalidSignature, ValueError):
        return False
    return True


def _minisign_checksum(key_id: bytes, secret: bytes) -> bytes:
    return hashlib.blake2b(b"Ed" + key_id + secret, digest_size=32).digest()


def minisign_new() -> tuple[str, str]:
    """A minisign key pair as `minisign -G -W` writes it: (secret key file, public key file)."""
    seed, public = ed25519_new()
    key_id = os.urandom(8)
    secret = seed + public                      # libsodium's 64-byte secret key
    raw_secret = (b"Ed" + b"\0\0" + b"B2" + bytes(32 + 8 + 8) + key_id + secret
                  + _minisign_checksum(key_id, secret))
    shown = f"{int.from_bytes(key_id, 'little'):016X}"
    return (f"untrusted comment: minisign secret key {shown}\n{b64(raw_secret)}\n",
            f"untrusted comment: minisign public key {shown}\n{b64(b'Ed' + key_id + public)}\n")


def _minisign_secret(text: str) -> tuple[bytes, bytes]:
    """(key id, 32-byte seed) of a secret key file that minisign did not encrypt."""
    try:
        raw = base64.b64decode(text.splitlines()[1], validate=True)
    except (IndexError, ValueError):
        raise CeremonyError("minisign.key is not a minisign secret key") from None
    if len(raw) != 158 or raw[:2] != b"Ed" or raw[4:6] != b"B2":
        raise CeremonyError("minisign.key is not a minisign Ed25519 secret key")
    if raw[2:4] != b"\0\0":
        raise CeremonyError("minisign.key is encrypted by minisign; the ceremony's keys are protected by the backup")
    key_id, secret, checksum = raw[54:62], raw[62:126], raw[126:158]
    # minisign -G -W leaves the checksum zero (it checks one only when it decrypts); the ceremony writes it
    if checksum != bytes(32) and _minisign_checksum(key_id, secret) != checksum:
        raise CeremonyError("minisign.key fails its own checksum")
    return key_id, secret[:32]


def _minisign_public(text: str) -> tuple[bytes, bytes]:
    try:
        raw = base64.b64decode(text.splitlines()[1], validate=True)
    except (IndexError, ValueError):
        raise CeremonyError("minisign.pub is not a minisign public key") from None
    if len(raw) != 42 or raw[:2] != b"Ed":
        raise CeremonyError("minisign.pub is not a minisign Ed25519 public key")
    return raw[2:10], raw[10:]


def minisign_sign(secret_text: str, data: bytes, trusted_comment: str) -> str:
    """A .minisig of `data` as minisign -S writes it (prehashed, BLAKE2b-512)."""
    key_id, seed = _minisign_secret(secret_text)
    key = _ed().Ed25519PrivateKey.from_private_bytes(seed)
    signature = key.sign(hashlib.blake2b(data, digest_size=64).digest())
    global_signature = key.sign(signature + trusted_comment.encode("utf-8"))
    return (f"untrusted comment: signature from minisign secret key\n{b64(b'ED' + key_id + signature)}\n"
            f"trusted comment: {trusted_comment}\n{b64(global_signature)}\n")


def minisign_verifies(public_text: str, data: bytes, signature_text: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    key_id, public = _minisign_public(public_text)
    lines = signature_text.splitlines()
    try:
        raw = base64.b64decode(lines[1], validate=True)
        comment = lines[2].removeprefix("trusted comment: ")
        global_signature = base64.b64decode(lines[3], validate=True)
    except (IndexError, ValueError):
        return False
    if len(raw) != 74 or raw[2:10] != key_id or raw[:2] not in (b"ED", b"Ed") or not lines[2].startswith("trusted"):
        return False
    message = hashlib.blake2b(data, digest_size=64).digest() if raw[:2] == b"ED" else data
    key = _ed().Ed25519PublicKey.from_public_bytes(public)
    try:
        key.verify(raw[10:], message)
        key.verify(global_signature, raw[10:] + comment.encode("utf-8"))
    except InvalidSignature:
        return False
    return True


# --- the APT key (GnuPG) -----------------------------------------------------------------------------------------

@functools.cache
def _posix_gpg() -> bool:
    """True for the GnuPG of Git for Windows: a POSIX program, to which C:/x is a relative path."""
    found = shutil.which("gpg")
    return os.name == "nt" and found is not None and (Path(found).parent / "msys-2.0.dll").is_file()


def gnupg_path(path: Path) -> str:
    """A path as the gpg found takes it: /c/x for Git's GnuPG, the path itself for any other."""
    text = path.absolute().as_posix()
    if _posix_gpg() and len(text) > 2 and text[1] == ":":
        return "/" + text[0].lower() + text[2:]
    return text


# GnuPG's agent may put its sockets in the home folder, and a socket's path has at most 107 characters
LONGEST_SOCKET = "/S.gpg-agent.browser"


def gpg(home: Path, *args: str, data: bytes | None = None) -> subprocess.CompletedProcess:
    """gpg on `home` only, never the person's own keyring; keys there have no passphrase (the backup has one)."""
    if len(gnupg_path(home)) + len(LONGEST_SOCKET) > 107:
        raise CeremonyError(f"the path of {home} is too long for GnuPG's sockets; use a folder nearer the top of "
                            "its drive")
    done = subprocess.run(["gpg", "--homedir", gnupg_path(home), "--batch", "--no-tty", "--pinentry-mode",
                           "loopback", "--passphrase", "", *args], input=data, capture_output=True)
    if done.returncode != 0:
        raise CeremonyError(f"gpg {args[0]} stopped with {done.returncode}: "
                            f"{done.stderr.decode('utf-8', 'replace').strip()[-300:]}")
    return done


def stop_agent(home: Path) -> None:
    if home.is_dir() and shutil.which("gpgconf"):
        subprocess.run(["gpgconf", "--homedir", gnupg_path(home), "--kill", "all"], capture_output=True)


def _colons(home: Path, secret: bool) -> list[list[str]]:
    listed = gpg(home, "--with-colons", "--fingerprint", "--fingerprint",
                 "--list-secret-keys" if secret else "--list-keys")
    return [line.split(":") for line in listed.stdout.decode("utf-8", "replace").splitlines()]


def apt_fingerprint(home: Path) -> str:
    rows = _colons(home, secret=False)
    primaries = [i for i, row in enumerate(rows) if row[0] == "pub"]
    if len(primaries) != 1:
        raise CeremonyError(f"the APT GnuPG home holds {len(primaries)} keys, not one")
    return next(row[9] for row in rows[primaries[0]:] if row[0] == "fpr")


def make_apt(home: Path, public: Path, when: int) -> str:
    """The APT key in a new GnuPG home: an Ed25519 root that only certifies and an Ed25519 signing subkey, neither
    expiring (a date that passes would cut every copy off from its updates; a lost subkey is revoked by the
    root). `when` is the creation time written into the key: midnight UTC of the day, so the key tells no hour."""
    home.mkdir(mode=0o700)
    clock = ("--faked-system-time", f"{when}!")
    gpg(home, *clock, "--quick-gen-key", APT_NAME, "ed25519", "cert", "never")
    fingerprint = apt_fingerprint(home)
    gpg(home, *clock, "--quick-add-key", fingerprint, "ed25519", "sign", "never")
    (public / KEYRING).write_bytes(gpg(home, "--export", fingerprint).stdout)
    stop_agent(home)
    return fingerprint


def check_apt(home: Path, keyring: Path, fingerprint: str, root_needed: bool) -> str:
    """The APT key signs and a GnuPG home holding only the published keyring verifies the signature as made by a
    subkey of `fingerprint`; with `root_needed` the root's secret and its revocation certificate are there too."""
    with tempfile.TemporaryDirectory(prefix="tv-") as tmp:   # short: GnuPG's sockets go in it
        work = Path(tmp)
        (work / "message").write_bytes(TEST_MESSAGE)
        gpg(home, "--local-user", fingerprint, "--digest-algo", "SHA512", "--detach-sign", "--output",
            gnupg_path(work / "message.sig"), gnupg_path(work / "message"))
        verifier = work / "v"
        verifier.mkdir(mode=0o700)
        try:
            gpg(verifier, "--import", gnupg_path(keyring))
            status = gpg(verifier, "--status-fd", "1", "--verify", gnupg_path(work / "message.sig"),
                         gnupg_path(work / "message"))
        finally:
            stop_agent(verifier)
    valid = [line.split() for line in status.stdout.decode("utf-8", "replace").splitlines()
             if line.startswith("[GNUPG:] VALIDSIG ")]
    if not valid or valid[0][-1] != fingerprint:
        raise CeremonyError("the APT key's signature does not verify under the published keyring")
    if valid[0][2] == fingerprint:
        raise CeremonyError("the APT signature was made by the root; the signing subkey must make it")
    if root_needed:
        primary = next(row for row in _colons(home, secret=True) if row[0] == "sec")
        if len(primary) > 14 and primary[14] == "#":
            raise CeremonyError("the backup holds no secret APT root (only its stub)")
        if not (home / "openpgp-revocs.d" / f"{fingerprint}.rev").is_file():
            raise CeremonyError("the APT root's revocation certificate is missing")
    return f"APT key {fingerprint}: its signing subkey signs, the published keyring verifies"


def unlock_apt(source: Path, target: Path, fingerprint: str) -> None:
    """Only the signing subkey (and the root's public part) into a new GnuPG home: the root stays offline."""
    subkeys = gpg(source, "--export-secret-subkeys", fingerprint).stdout
    target.mkdir(mode=0o700)
    gpg(target, "--import", data=subkeys)
    primary = next(row for row in _colons(target, secret=True) if row[0] == "sec")
    if len(primary) <= 14 or primary[14] != "#":
        raise CeremonyError("the unlocked APT home would hold the root's secret; nothing was unlocked")
    stop_agent(target)


# --- making and checking the keys --------------------------------------------------------------------------------

def midnight_utc(now: float | None = None) -> int:
    day = time.gmtime(now if now is not None else time.time())
    return calendar.timegm((day.tm_year, day.tm_mon, day.tm_mday, 0, 0, 0))


def make(out: Path, offline: bool, now: float | None = None) -> dict:
    """Every key into `out` (new or empty), the public halves into out/public; returns PUBLIC-KEYS.json."""
    new_folder(out)
    public = out / PUBLIC
    public.mkdir()
    try:
        update_private, update_public = ed25519_new()
        adblock_private, adblock_public = ed25519_new()
        (out / UPDATE_KEY).write_text(b64(update_private) + "\n", encoding="ascii")
        (out / ADBLOCK_KEY).write_text(b64(adblock_private) + "\n", encoding="ascii")
        secret, minisign_public = minisign_new()
        (out / MINISIGN_KEY).write_text(secret, encoding="ascii", newline="\n")
        (public / MINISIGN_PUB).write_text(minisign_public, encoding="ascii", newline="\n")
        when = midnight_utc(now)
        fingerprint = make_apt(out / APT_HOME, public, when)
        info = {
            "format": 1,
            "made": time.strftime("%Y-%m-%d", time.gmtime(when)),
            "made_offline": offline,
            "update_manifest": b64(update_public),
            "adblock_resources": b64(adblock_public),
            "minisign": minisign_public.splitlines()[1],
            "apt_fingerprint": fingerprint,
            "apt_keyring_sha256": hashlib.sha256((public / KEYRING).read_bytes()).hexdigest(),
        }
        (public / PUBLIC_JSON).write_text(json.dumps(info, indent=2) + "\n", encoding="ascii", newline="\n")
        check_keys(out, public, root_needed=True)
    except BaseException:
        stop_agent(out / APT_HOME)
        wipe(out)
        raise
    return info


def read_public(public: Path) -> dict:
    try:
        info = json.loads((public / PUBLIC_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CeremonyError(f"{public / PUBLIC_JSON}: {exc}") from None
    for name in ("update_manifest", "adblock_resources", "minisign", "apt_fingerprint", "apt_keyring_sha256"):
        if not isinstance(info.get(name), str):
            raise CeremonyError(f"{PUBLIC_JSON} has no {name}")
    keyring = public / KEYRING
    if not keyring.is_file() or hashlib.sha256(keyring.read_bytes()).hexdigest() != info["apt_keyring_sha256"]:
        raise CeremonyError(f"{KEYRING} is missing or is not the one {PUBLIC_JSON} names")
    try:
        minisign_public = (public / MINISIGN_PUB).read_text(encoding="ascii")
    except OSError:
        raise CeremonyError(f"{MINISIGN_PUB} is missing") from None
    if minisign_public.splitlines()[1:2] != [info["minisign"]]:
        raise CeremonyError(f"{MINISIGN_PUB} is not the key {PUBLIC_JSON} names")
    return info


def _ed25519_key(path: Path) -> bytes:
    try:
        return mf.read_private_key(path)
    except (OSError, ValueError) as exc:
        raise CeremonyError(f"{path.name}: {exc}") from None


def check_keys(keys: Path, public: Path, root_needed: bool) -> list[str]:
    """Each key in `keys` signs, and the public halves in `public` verify; a CeremonyError names the first that
    does not."""
    info = read_public(public)
    found = []
    for name, field in ((UPDATE_KEY, "update_manifest"), (ADBLOCK_KEY, "adblock_resources")):
        published = base64.b64decode(info[field], validate=True)
        if not mf.usable_key(published):
            raise CeremonyError(f"the published {field} key is no usable key")
        if not ed25519_signs(_ed25519_key(keys / name), published):
            raise CeremonyError(f"{name} does not belong to the published {field} key")
        found.append(f"{name}: signs, the published key verifies")
    try:
        secret = (keys / MINISIGN_KEY).read_text(encoding="ascii")
    except OSError:
        raise CeremonyError(f"{MINISIGN_KEY} is missing") from None
    minisign_public = (public / MINISIGN_PUB).read_text(encoding="ascii")
    signature = minisign_sign(secret, TEST_MESSAGE, "thoron key ceremony")
    if not minisign_verifies(minisign_public, TEST_MESSAGE, signature):
        raise CeremonyError(f"{MINISIGN_KEY} does not belong to the published minisign key")
    if shutil.which("minisign"):
        with tempfile.TemporaryDirectory(prefix="thoron-minisign-check-") as tmp:
            for name, content in (("m", TEST_MESSAGE), ("m.minisig", signature.encode("ascii")),
                                  ("k.pub", minisign_public.encode("ascii"))):
                (Path(tmp) / name).write_bytes(content)
            done = subprocess.run(["minisign", "-V", "-q", "-p", str(Path(tmp) / "k.pub"), "-m",
                                   str(Path(tmp) / "m")], capture_output=True)
        if done.returncode != 0:
            raise CeremonyError("minisign itself does not verify the minisign key's signature")
        found.append(f"{MINISIGN_KEY}: signs, the published key verifies (minisign itself too)")
    else:
        found.append(f"{MINISIGN_KEY}: signs, the published key verifies")
    found.append(check_apt(keys / APT_HOME, public / KEYRING, info["apt_fingerprint"], root_needed))
    return found


# --- the encrypted backup ----------------------------------------------------------------------------------------

def _key(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    secret = unicodedata.normalize("NFC", passphrase).encode("utf-8")
    return hashlib.scrypt(secret, salt=salt, n=n, r=r, p=p, dklen=32, maxmem=2 ** 30)


def folder_files(keys: Path) -> dict[str, bytes]:
    """The files of a key folder by their paths in it; GnuPG's sockets and lock files (which name the computer)
    are left out."""
    found = {}
    for root, dirs, files in os.walk(keys, followlinks=False):
        dirs.sort()
        for name in sorted(files):
            path = Path(root) / name
            if path.is_symlink() or not path.is_file() or name.startswith(("S.", ".#lk")) or name.endswith(".lock"):
                continue
            found[path.relative_to(keys).as_posix()] = path.read_bytes()
    return found


def _packed(files: dict[str, bytes]) -> bytes:
    """A zip in a fixed order with fixed times."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as z:
        for name, content in files.items():
            z.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), content)
    return buffer.getvalue()


def seal(files: dict[str, bytes], passphrase: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = os.urandom(16), os.urandom(12)
    header = dict(SCRYPT, format=1, kdf="scrypt", cipher="AES-256-GCM", salt=b64(salt), nonce=b64(nonce))
    head = MAGIC + json.dumps(header, sort_keys=True).encode("ascii") + b"\n"
    key = _key(passphrase, salt, SCRYPT["n"], SCRYPT["r"], SCRYPT["p"])
    return head + AESGCM(key).encrypt(nonce, _packed(files), head)


def opened(sealed: bytes, passphrase: str) -> dict[str, bytes]:
    """The files of a backup, by their paths in the folder."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not sealed.startswith(MAGIC) or b"\n" not in sealed[len(MAGIC):len(MAGIC) + 1024]:
        raise CeremonyError("not a Thoron key backup")
    end = sealed.index(b"\n", len(MAGIC)) + 1
    try:
        header = json.loads(sealed[len(MAGIC):end])
        salt, nonce = base64.b64decode(header["salt"]), base64.b64decode(header["nonce"])
        n, r, p = int(header["n"]), int(header["r"]), int(header["p"])
    except (ValueError, KeyError, TypeError):
        raise CeremonyError("the backup's header is damaged") from None
    if header.get("format") != 1 or header.get("kdf") != "scrypt" or header.get("cipher") != "AES-256-GCM" \
            or n not in (2 ** 14, 2 ** 15, 2 ** 16, 2 ** 17, 2 ** 18, 2 ** 19, 2 ** 20) or (r, p) != (8, 1) \
            or len(salt) != 16 or len(nonce) != 12:
        raise CeremonyError("the backup's header names settings this tool does not use")
    try:
        packed = AESGCM(_key(passphrase, salt, n, r, p)).decrypt(nonce, sealed[end:], sealed[:end])
    except InvalidTag:
        raise CeremonyError("the passphrase is wrong, or the backup was changed or damaged") from None
    files = {}
    with zipfile.ZipFile(io.BytesIO(packed)) as z:
        for info in z.infolist():
            parts = info.filename.split("/")
            if info.is_dir() or info.filename.startswith("/") or "\\" in info.filename or ".." in parts \
                    or parts[0] not in TOP or ":" in info.filename:
                raise CeremonyError(f"the backup holds an unexpected path: {info.filename!r}")
            files[info.filename] = z.read(info)
    return files


def write_files(files: dict[str, bytes], keys: Path) -> None:
    for name, content in files.items():
        path = keys.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(content)


def backup(keys: Path, out: Path, passphrase: str) -> list[str]:
    """Checks the keys, writes the encrypted backup (never over a file) and reads it back."""
    stop_agent(keys / APT_HOME)
    found = check_keys(keys, keys / PUBLIC, root_needed=True)
    stop_agent(keys / APT_HOME)
    files = folder_files(keys)
    sealed = seal(files, passphrase)
    try:
        with open(out, "xb") as f:
            f.write(sealed)
            f.flush()
            os.fsync(f.fileno())
    except FileExistsError:
        raise CeremonyError(f"{out} exists; a backup is never written over a file") from None
    if opened(out.read_bytes(), passphrase) != files:
        raise CeremonyError(f"{out} does not read back as written")
    return found


def _read_backup(path: Path) -> bytes:
    try:
        if path.stat().st_size > MAX_BACKUP:
            raise CeremonyError(f"{path} is too large to be a key backup")
        return path.read_bytes()
    except OSError as exc:
        raise CeremonyError(f"{path}: {exc}") from None


def restore_test(backup_file: Path, public: Path, passphrase: str) -> list[str]:
    """The backup decrypts, and every key in it signs what the published public halves verify."""
    files = opened(_read_backup(backup_file), passphrase)
    work = Path(tempfile.mkdtemp(prefix="tk-"))       # short: GnuPG's sockets go in it
    try:
        write_files(files, work)
        return check_keys(work, public, root_needed=True)
    finally:
        stop_agent(work / APT_HOME)
        wipe(work)


def unlock(backup_file: Path, out: Path, passphrase: str) -> dict:
    """The keys a release signs with into `out`: the two Ed25519 keys, minisign's, and a GnuPG home with only
    the APT signing subkey. Checked before it is handed over."""
    files = opened(_read_backup(backup_file), passphrase)
    new_folder(out)
    work = Path(tempfile.mkdtemp(prefix="tk-"))       # short: GnuPG's sockets go in it
    try:
        write_files(files, work)
        info = read_public(work / PUBLIC)
        for name in (UPDATE_KEY, ADBLOCK_KEY, MINISIGN_KEY):
            shutil.copyfile(work / name, out / name)
        shutil.copytree(work / PUBLIC, out / PUBLIC)
        unlock_apt(work / APT_HOME, out / APT_HOME, info["apt_fingerprint"])
        check_keys(out, out / PUBLIC, root_needed=False)
    except BaseException:
        stop_agent(out / APT_HOME)
        wipe(out)
        raise
    finally:
        stop_agent(work / APT_HOME)
        wipe(work)
    return info


def lock(keys: Path) -> None:
    """Deletes a folder `make` or `unlock` wrote, and nothing else."""
    if not keys.is_dir():
        raise CeremonyError(f"{keys} is not a folder")
    names = {p.name for p in keys.iterdir()}
    if not names or not names <= set(TOP) or not names & {UPDATE_KEY, MINISIGN_KEY, APT_HOME}:
        raise CeremonyError(f"{keys} is not a key folder this tool wrote; nothing was deleted")
    stop_agent(keys / APT_HOME)
    wipe(keys)


def where_they_go(info: dict) -> list[str]:
    adblock = base64.b64decode(info["adblock_resources"])
    lines = [
        f"update manifest key (base64): {info['update_manifest']}",
        f"    GN: thoron_update_public_key = \"{info['update_manifest']}\" and release.py --manifest-public-key",
        f"Thoron adblock resources key (base64): {info['adblock_resources']}",
        "    components/thoron_adblock/list_store.cc kResourcesPublicKey = "
        "{" + ", ".join(f"0x{b:02x}" for b in adblock) + "}",
        f"minisign public key: {info['minisign']}   (README, release notes: minisign -Vm SHA256SUMS -P <key>)",
        f"APT key fingerprint: {info['apt_fingerprint']}   (README; {KEYRING} beside the APT repository)",
    ]
    if not info.get("made_offline"):
        lines.insert(0, "TEST KEYS: made on a computer with a network; never build them into a release")
    return lines


# --- the command line --------------------------------------------------------------------------------------------

def ask_new_passphrase() -> str:
    print("The backup's passphrase: at least 20 characters; six or more random words are good. Write it on paper"
          " and keep the paper apart from the backup: without it the keys are lost for good.")
    first = getpass.getpass("passphrase: ")
    if len(first) < MIN_PASSPHRASE:
        raise CeremonyError(f"the passphrase is shorter than {MIN_PASSPHRASE} characters")
    if getpass.getpass("the same passphrase again: ") != first:
        raise CeremonyError("the two passphrases differ")
    return first


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    m = sub.add_parser("make")
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--allow-network", action="store_true", help="make test keys on a computer with a network")
    b = sub.add_parser("backup")
    b.add_argument("--keys", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("restore-test")
    r.add_argument("--backup", type=Path, required=True)
    r.add_argument("--public", type=Path, required=True)
    u = sub.add_parser("unlock")
    u.add_argument("--backup", type=Path, required=True)
    u.add_argument("--out", type=Path, required=True)
    lk = sub.add_parser("lock")
    lk.add_argument("--keys", type=Path, required=True)
    s = sub.add_parser("show")
    s.add_argument("--public", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        if a.command == "make":
            online = network_route()
            if online and not a.allow_network:
                raise CeremonyError("this computer has a network route: the keys are made with no network (unplug "
                                    "the cable, turn Wi-Fi off, or use the offline Windows Sandbox of KEYS.md)")
            info = make(a.out, offline=not online)
            print(f"key ceremony: four keys made in {a.out}; the public halves are in {a.out / PUBLIC}")
            print("\n".join(where_they_go(info)))
            print("next: backup, then restore-test, then lock")
        elif a.command == "backup":
            found = backup(a.keys, a.out, ask_new_passphrase())
            print("\n".join(found))
            print(f"key ceremony: {a.out} written and read back; copy it to a second place, then run restore-test")
        elif a.command == "restore-test":
            found = restore_test(a.backup, a.public, getpass.getpass("passphrase: "))
            print("\n".join(found))
            print("key ceremony: the backup restores, and every key signs what the published keys verify")
        elif a.command == "unlock":
            info = unlock(a.backup, a.out, getpass.getpass("passphrase: "))
            print(f"key ceremony: the release keys are in {a.out} (the APT root stayed in the backup):")
            print(f"    release.py --minisign-key {a.out / MINISIGN_KEY} --manifest-key {a.out / UPDATE_KEY} "
                  f"--adblock-key {a.out / ADBLOCK_KEY}")
            print(f"    apt_repo.py --gnupg-home {a.out / APT_HOME} --key {info['apt_fingerprint']}")
            print(f"when the release is signed: key_ceremony.py lock --keys {a.out}")
        elif a.command == "lock":
            lock(a.keys)
            print(f"key ceremony: {a.keys} deleted")
        else:
            print("\n".join(where_they_go(read_public(a.public))))
    except CeremonyError as exc:
        print(f"key ceremony: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
