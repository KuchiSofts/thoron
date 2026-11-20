#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Take over an upstream Thorium portable folder into a Thoron portable copy (ROADMAP P4.10, design 7.8). Windows.

Upstream Thorium's portable package starts its browser with `--disable-encryption`, which keeps the key of the
saved passwords and cookies in its `USER_DATA\\Local State` unprotected: anyone who holds the drive can read
them. Thoron never does that. This tool, with the original left exactly as it was:

    1. copies the folder into the Thoron copy's empty `User Data` (import_profile.py: every file checked by
       SHA-256, the source read only and found unchanged afterwards);
    2. protects the copy's key at once, the way an unlocked Thoron copy keeps it (Windows' DPAPI for the account
       running the tool), so the copy never holds it in the clear;
    3. checks that every saved password and cookie of every profile in the copy decrypts with the key the copy
       now holds;
    4. only then gives the folder its name, `User Data`.

The person then starts the Thoron copy and locks it with a passphrase on chrome://thoron-portable, which writes
the key file and opens it again before it counts (P4.9). The tool asks for no passphrase and writes no key file:
the passphrase is typed into Thoron only. The report holds counts only, never a value.

    py -3 -I tools/migrate/adopt_portable.py --from <Thorium portable folder, or its USER_DATA> --into <ThoronPortable>
Exit status: 0 taken over, 1 refused or failed (nothing of the original was changed).
"""
import argparse
import base64
import ctypes
import json
import shutil
import sqlite3
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.migrate import import_profile  # noqa: E402

DPAPI_PREFIX = b"DPAPI"
KEY_BYTES = 32
ADOPTING = "User Data.adopting"
# (what, the database in a profile, the table, the column of encrypted values)
SECRETS = (("saved passwords", "Login Data", "logins", "password_value"),
           ("cookies", "Network/Cookies", "cookies", "encrypted_value"))


class AdoptRefused(RuntimeError):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, protect: bool) -> bytes | None:
    """CryptProtectData or CryptUnprotectData for the current Windows account, no extra entropy (as Chromium's
    os_crypt does); None when it fails."""
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buffer = ctypes.create_string_buffer(data, len(data))
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    out = _Blob()
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ui_forbidden = 0x1
    if not call(ctypes.byref(source), None, None, None, None, ui_forbidden, ctypes.byref(out)):
        return None
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)
        ctypes.memset(buffer, 0, len(data))


def read_key(local_state: dict) -> tuple[bytes, str]:
    """The profile key of an upstream portable `Local State`, and how it was kept: "unprotected" (Thorium's
    --disable-encryption: "DPAPI" and the 32 bytes themselves) or "this account" (a real DPAPI blob this Windows
    account opens). Refused otherwise: another account's key, or Chrome's app-bound key."""
    crypt = local_state.get("os_crypt") if isinstance(local_state, dict) else None
    if not isinstance(crypt, dict) or not isinstance(crypt.get("encrypted_key"), str):
        raise AdoptRefused("its Local State holds no key for passwords and cookies")
    if crypt.get("app_bound_encrypted_key"):
        raise AdoptRefused("its passwords and cookies are locked to the browser that made them (app-bound)")
    try:
        stored = base64.b64decode(crypt["encrypted_key"], validate=True)
    except ValueError as exc:
        raise AdoptRefused("its Local State's key is not readable") from exc
    if not stored.startswith(DPAPI_PREFIX):
        raise AdoptRefused("its Local State's key is in a form Thoron does not know")
    body = stored[len(DPAPI_PREFIX):]
    if len(body) == KEY_BYTES:
        return body, "unprotected"
    key = _dpapi(body, protect=False)
    if key is None or len(key) != KEY_BYTES:
        raise AdoptRefused("its key is protected for another Windows account or PC; start it there with Thorium "
                           "and export the passwords instead")
    return key, "this account"


def protected_key(key: bytes) -> str:
    """`key` as an unlocked Thoron copy keeps it in Local State."""
    blob = _dpapi(key, protect=True)
    if not blob:
        raise AdoptRefused("Windows did not protect the key for this account")
    return base64.b64encode(DPAPI_PREFIX + blob).decode("ascii")


def decrypts(value: bytes, key: bytes) -> bool:
    """A value Chromium encrypted on Windows ("v10", AES-256-GCM: a 12-byte nonce, then the text and its tag)."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not value.startswith(b"v10") or len(value) < 3 + 12 + 16:
        return False
    try:
        AESGCM(key).decrypt(value[3:15], value[15:], None)
        return True
    except InvalidTag:
        return False


def check_secrets(user_data: Path, key: bytes) -> dict:
    """For every profile of `user_data`, how many saved passwords and cookies there are and how many decrypt with
    `key`. Empty values are not secrets and are not counted. Copies of the databases are read, inside
    `user_data` (THREAT_MODEL I8), and removed."""
    counts = {what: {"found": 0, "readable": 0} for what, _, _, _ in SECRETS}
    scratch = Path(tempfile.mkdtemp(prefix=".thoron-adopt-", dir=user_data))
    try:
        for profile in sorted(p for p in user_data.iterdir() if p.is_dir() and (p / "Preferences").is_file()):
            for what, name, table, column in SECRETS:
                database = profile / name
                if not database.is_file():
                    continue
                copy = scratch / f"{profile.name}-{database.name}"
                shutil.copyfile(database, copy)
                con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
                try:
                    rows = con.execute(f"SELECT {column} FROM {table}").fetchall()
                finally:
                    con.close()
                for (value,) in rows:
                    value = bytes(value or b"")
                    if not value:
                        continue
                    counts[what]["found"] += 1
                    counts[what]["readable"] += decrypts(value, key)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return counts


def source_user_data(given: Path) -> Path:
    """`given` itself when it is a User Data folder, else its USER_DATA (upstream's portable layout)."""
    for candidate in (given, given / "USER_DATA"):
        if (candidate / "Local State").is_file():
            return candidate
    raise AdoptRefused(f"{given} is not an upstream portable folder: no USER_DATA\\Local State")


def adopt(source: Path, into: Path) -> dict:
    source = source_user_data(source.resolve())
    into = into.resolve()
    if not (into / "Thoron.exe").is_file() or not (into / "Application").is_dir():
        raise AdoptRefused(f"{into} is not a Thoron portable copy (no Thoron.exe and Application folder)")
    final = into / "User Data"
    if final.exists() and any(final.iterdir()):
        raise AdoptRefused(f"the Thoron copy already has a profile in {final}; nothing was changed")
    local_state = json.loads((source / "Local State").read_text(encoding="utf-8"))
    key, kept = read_key(local_state)
    work = into / ADOPTING
    if work.exists():
        shutil.rmtree(work)
    try:
        copied = import_profile.import_profile(source, work)
        state_path = work / "Local State"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.setdefault("os_crypt", {})["encrypted_key"] = protected_key(key)
        state.setdefault("thoron_portable", {})["locked"] = False
        state_path.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
        # the copy opens with what it now holds, on this PC and account
        again, how = read_key(json.loads(state_path.read_text(encoding="utf-8")))
        if again != key or how != "this account":
            raise import_profile.VerificationFailed("the copy's protected key does not open again")
        secrets = check_secrets(work, again)
        unreadable = {what: c["found"] - c["readable"] for what, c in secrets.items() if c["found"] != c["readable"]}
        if unreadable:
            raise import_profile.VerificationFailed(f"some values do not decrypt in the copy: {unreadable}")
        if final.exists():
            final.rmdir()  # empty, checked above
        work.rename(final)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return {"files": copied["files"], "bytes": copied["bytes"], "source_unchanged": copied["source_unchanged"],
            "key_was": kept, "secrets": secrets}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from", dest="source", required=True, type=Path)
    p.add_argument("--into", required=True, type=Path)
    a = p.parse_args(argv)
    try:
        report = adopt(a.source, a.into)
    except (AdoptRefused, import_profile.ImportRefused, import_profile.VerificationFailed, OSError,
            ValueError, sqlite3.Error) as exc:
        print(f"not taken over: {exc}")
        return 1
    print(json.dumps(report, indent=2))
    print("Taken over. Start the Thoron copy and lock it with a passphrase on chrome://thoron-portable.")
    if report["key_was"] == "unprotected":
        print("The original folder still keeps its passwords and cookies unprotected: delete it yourself once you "
              "are sure, and remember that deleted files on a USB drive can often be recovered.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
