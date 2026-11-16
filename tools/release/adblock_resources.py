#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Signed updates of Thoron adblock's scriptlets and stand-ins between releases (ROADMAP P5.23).

The browser ships uBlock Origin's scriptlets and stand-ins (thoron_adblock_resources.json). A newer copy can
reach it between releases as one text file, signed with Thoron's Ed25519 key:

    thoron-adblock-resources 1
    serial: <YYYYMMDDNN, higher than the copy in use>
    signature: <base64 of the Ed25519 signature>
    <an empty line>
    <the resources, as the shipped file>

The signature is over the file without its signature line. The browser takes a copy in only when the
signature holds and the serial is higher than the one in use, and checks it again each time it reads it
(components/thoron_adblock/list_store.cc). The browser holds only the public key; the private key never
enters the repository, the build machine's tree or any log.

    keygen  --out <private key file>       a new key (the key ceremony, ROADMAP P2.11): the private key is
                                           written to the file (offline, kept as the release key is), the
                                           public key is printed, in base64 and as the C++ array for
                                           kResourcesPublicKey
    sign    --resources <json> --serial N --key <private key file> --out <file>
    verify  <file> --public-key <base64>   prints the serial when the signature holds

    py -3 -I tools/release/adblock_resources.py sign --resources thoron_adblock_resources.json \\
        --serial 2026120100 --key <private key file> --out thoron_adblock_resources.signed
"""
import argparse
import base64
import json
import re
import sys
from pathlib import Path

HEADER = "thoron-adblock-resources 1"
SERIAL = re.compile(r"^\d{10}$")


def _ed25519():
    from cryptography.hazmat.primitives.asymmetric import ed25519
    return ed25519


def message(serial: str, resources: str) -> bytes:
    """What the signature is over: the file without its signature line."""
    return f"{HEADER}\nserial: {serial}\n\n{resources}".encode("utf-8")


def check_resources(text: str) -> None:
    """Refuses what is not a resource list as the build writes it (the browser refuses it too)."""
    items = json.loads(text)
    if not isinstance(items, list) or not items:
        raise ValueError("not a list of resources")
    for item in items:
        if not isinstance(item, dict) or not item.get("name") or "content" not in item or "kind" not in item:
            raise ValueError(f"not a resource: {str(item)[:80]}")
        base64.b64decode(item["content"], validate=True)


def sign(resources: str, serial: str, private_key: bytes) -> str:
    if not SERIAL.match(serial):
        raise ValueError("the serial is ten digits: YYYYMMDDNN")
    check_resources(resources)
    key = _ed25519().Ed25519PrivateKey.from_private_bytes(private_key)
    signature = base64.b64encode(key.sign(message(serial, resources))).decode("ascii")
    return f"{HEADER}\nserial: {serial}\nsignature: {signature}\n\n{resources}"


def verify(text: str, public_key: bytes) -> str | None:
    """The serial of a signed file whose signature holds, else None (as the browser decides)."""
    lines = text.split("\n", 4)
    if len(lines) != 5 or lines[0] != HEADER or lines[3] != "":
        return None
    serial = lines[1].removeprefix("serial: ")
    signature = lines[2].removeprefix("signature: ")
    if not lines[1].startswith("serial: ") or not SERIAL.match(serial) or not lines[2].startswith("signature: "):
        return None
    try:
        raw = base64.b64decode(signature, validate=True)
        _ed25519().Ed25519PublicKey.from_public_bytes(public_key).verify(raw, message(serial, lines[4]))
    except Exception:  # noqa: BLE001 - any failure is a refusal
        return None
    return serial


def keygen() -> tuple[bytes, bytes]:
    """A new key: (private 32 bytes, public 32 bytes)."""
    from cryptography.hazmat.primitives import serialization
    key = _ed25519().Ed25519PrivateKey.generate()
    raw = serialization.Encoding.Raw
    private = key.private_bytes(raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = key.public_key().public_bytes(raw, serialization.PublicFormat.Raw)
    return private, public


def cpp_array(public: bytes) -> str:
    return "{" + ", ".join(f"0x{b:02x}" for b in public) + "}"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--out", required=True, type=Path)
    s = sub.add_parser("sign")
    s.add_argument("--resources", required=True, type=Path)
    s.add_argument("--serial", required=True)
    s.add_argument("--key", required=True, type=Path)
    s.add_argument("--out", required=True, type=Path)
    v = sub.add_parser("verify")
    v.add_argument("file", type=Path)
    v.add_argument("--public-key", required=True)
    a = p.parse_args(argv)
    if a.command == "keygen":
        if a.out.exists():
            print(f"{a.out} exists: a key is never overwritten")
            return 1
        private, public = keygen()
        a.out.write_bytes(base64.b64encode(private) + b"\n")
        print("public key (base64):", base64.b64encode(public).decode("ascii"))
        print("kResourcesPublicKey:", cpp_array(public))
        return 0
    if a.command == "sign":
        private = base64.b64decode(a.key.read_bytes().strip(), validate=True)
        a.out.write_bytes(sign(a.resources.read_text(encoding="utf-8"), a.serial, private).encode("utf-8"))
        print(f"signed {a.out} (serial {a.serial})")
        return 0
    serial = verify(a.file.read_text(encoding="utf-8"), base64.b64decode(a.public_key, validate=True))
    print(f"the signature holds, serial {serial}" if serial else "REFUSED: the signature does not hold")
    return 0 if serial else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
