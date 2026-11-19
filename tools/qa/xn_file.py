#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""X-notifier's file of accounts ("chrome.xn"), written and read, for the checks (ROADMAP P5.80).

Thoron M-Notifier reads the file X-notifier exports. The checks need such a file with made-up accounts, so this
writes one in the same form, and reads one back:

    [---<info>---]              a line: the file's token (digits), encrypted
    [---<preferences>---]       lines of name, kind (0 text, 1 number, 2 yes or no) and value, tab-separated;
                                "accounts.[<kind>#<user>].<name>" is a setting of one account
    [---<accounts>---]          a line for each account: kind, user, password and the token, tab-separated,
                                encrypted
    [------]

An encrypted line is base64 of 8 bytes (where the counter starts) and the text in AES counter mode. The key is
the passphrase's first 32 bytes (UTF-8, filled up with zeros) encrypted once with themselves as the key, and
those 16 bytes twice. AES itself is written out here (FIPS 197) so the tool needs nothing installed; it is for
test files, not for speed.
"""
import base64
import re

_SBOX = [0] * 256


def _make_sbox() -> None:
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q
        for turn in (1, 2, 3, 4):
            x ^= ((q << turn) | (q >> (8 - turn))) & 0xFF
        _SBOX[p] = x ^ 0x63
        if p == 1:
            break
    _SBOX[0] = 0x63


_make_sbox()


def _double(a: int) -> int:
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _expand(key: bytes) -> list[list[int]]:
    words = len(key) // 4
    rounds = words + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(words)]
    constant = 1
    for i in range(words, 4 * (rounds + 1)):
        t = list(w[i - 1])
        if i % words == 0:
            t = [_SBOX[b] for b in t[1:] + t[:1]]
            t[0] ^= constant
            constant = _double(constant)
        elif words > 6 and i % words == 4:
            t = [_SBOX[b] for b in t]
        w.append([a ^ b for a, b in zip(w[i - words], t)])
    return w


def aes_block(block: bytes, key: bytes) -> bytes:
    """One 16-byte block encrypted with AES (a key of 16, 24 or 32 bytes)."""
    w = _expand(key)
    rounds = len(w) // 4 - 1
    s = [block[i] ^ w[i // 4][i % 4] for i in range(16)]
    for r in range(1, rounds + 1):
        s = [_SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]  # the rows shifted (the state is column by column)
        if r != rounds:
            mixed = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                t = a[0] ^ a[1] ^ a[2] ^ a[3]
                mixed += [a[i] ^ t ^ _double(a[i] ^ a[(i + 1) % 4]) for i in range(4)]
            s = mixed
        s = [s[i] ^ w[4 * r + i // 4][i % 4] for i in range(16)]
    return bytes(s)


def key_of(passphrase: str) -> bytes:
    typed = passphrase.encode("utf-8")[:32].ljust(32, b"\0")
    half = aes_block(typed[:16], typed)
    return half + half


def _counter_mode(data: bytes, start: bytes, key: bytes) -> bytes:
    out = bytearray()
    for at in range(0, len(data), 16):
        stream = aes_block(start + (at // 16).to_bytes(8, "big"), key)
        out += bytes(x ^ y for x, y in zip(data[at:at + 16], stream))
    return bytes(out)


def encrypt(text: str, passphrase: str, start: bytes = bytes(8)) -> str:
    """`text` as a line of the file. `start`: the 8 bytes the counter starts with (X-notifier takes the time)."""
    assert len(start) == 8
    return base64.b64encode(start + _counter_mode(text.encode("utf-8"), start, key_of(passphrase))).decode()


def decrypt(line: str, passphrase: str) -> str:
    raw = base64.b64decode(line.strip())
    return _counter_mode(raw[8:], raw[:8], key_of(passphrase)).decode("utf-8", errors="replace")


def write(accounts: list[tuple[str, str, str]], passphrase: str, token: str = "20261116",
          preferences: list[tuple[str, int, str]] = ()) -> str:
    """The file's text for `accounts` (kind, user, password) and `preferences` (name, kind, value)."""
    lines = ["[---<info>---]", encrypt(token, passphrase), "[---<preferences>---]"]
    lines += [f"{name}\t{kind}\t{value}" for name, kind, value in preferences] or ["soundUrl\t0\t"]
    lines.append("[---<accounts>---]")
    lines += [encrypt("\t".join((kind, user, password, token)), passphrase, bytes([i + 1] * 8))
              for i, (kind, user, password) in enumerate(accounts)]
    return "\r\n".join(lines + ["[------]"])


def read(text: str, passphrase: str) -> dict | None:
    """What a file holds, or None when the passphrase does not open it (or it is not such a file)."""
    sections = dict(re.findall(r"\[---(.+?)---\]\n([\s\S]+?)\n(?=\[--)", text.replace("\r\n", "\n")))
    if "<info>" not in sections or "<accounts>" not in sections:
        return None
    token = decrypt(sections["<info>"], passphrase)
    if not re.fullmatch(r"\d+", token):
        return None
    accounts = []
    for line in sections["<accounts>"].split("\n"):
        parts = decrypt(line, passphrase).split("\t")
        if len(parts) >= 4 and parts[3] == token:
            accounts.append((parts[0], parts[1], parts[2]))
    preferences = [tuple(line.split("\t")) for line in sections.get("<preferences>", "").split("\n") if line]
    return {"token": token, "accounts": accounts, "preferences": preferences}
