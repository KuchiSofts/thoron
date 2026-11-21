#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The update manifest, schema 1: build, check, sign and verify (ROADMAP P3.1, P3.2).

A release publishes two files: update.json, which names the newest release of a channel and where its
packages are, and update.json.sig, the Ed25519 signature of exactly those bytes. The updater in the
browser and the small installer hold only the public key. The format, the order of the checks and the
reason for each are in docs/update/MANIFEST.md; this file is the reference the C++ updater follows.

    example   [--out <file>]                 a valid manifest with made-up packages
    validate  <manifest>                     every problem of a manifest; no signature involved
    sign      <manifest> --key <private key file> --public-key <base64>
              (--previous <the manifest before it> | --first) [--out <file>]
                                             writes <manifest>.sig; signs nothing a copy would refuse
                                             today, nothing that goes back from the manifest before it,
                                             and nothing with a key other than the one copies hold
    renew     <manifest> --out <new manifest> [--valid-days 30]
                                             the same release in a new manifest: published now, a higher
                                             serial, a later expires; the release and its packages as they
                                             were (sign it then with --previous <manifest>), so a channel
                                             with no new release is not left with an expired manifest
    verify    <manifest> --public-key <base64> [--signature <file>] [--now <time>]
              [--installed <build version> --variant win-x64-avx2 --kind installed]
                                             the signature first, then the manifest, then its dates;
                                             with --installed, what that copy of Thoron does with it

Every command but example takes --host (repeatable): the hosts packages may be downloaded from (default
github.com). The private key is the release key (ROADMAP P2.11): 32 bytes in base64, in a file that never
enters the repository, the build tree or a log. This tool makes no keys and never overwrites a file.

    py -3 -I tools/update/manifest.py sign update.json --key <private key file> --public-key <base64>
        --previous <last update.json>
    py -3 -I tools/update/manifest.py verify update.json --public-key <base64>
"""
import argparse
import base64
import calendar
import datetime
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.release import version as ver  # noqa: E402

SCHEMA = 1
MANIFEST_NAME = "update.json"
SIGNATURE_NAME = MANIFEST_NAME + ".sig"
# What is signed is this prefix followed by the manifest's bytes. It names the purpose, so a signature the
# same key made for anything else (the ad blocker's resources, a checksum list, a later schema) is never
# the signature of a manifest.
SIGNATURE_PREFIX = b"thoron-update-manifest-v1\n"
# A key statement (ROADMAP P4.7): the new public key (32 bytes), then the signature (64 bytes) of a key the
# copy already trusts over this prefix and the new key. update.key of a release holds one.
KEY_STATEMENT_PREFIX = b"thoron-update-key-v1\n"
KEY_STATEMENT_BYTES = 96
MOST_KEY_STATEMENTS = 8
SIGNATURE_BYTES = 64
KEY_BYTES = 32

MAX_MANIFEST_BYTES = 256 * 1024
MAX_URL_CHARS = 1024
MAX_INT = 2**31 - 1                 # sizes and the serial: every JSON library reads these exactly
MAX_DELTAS = 8
MAX_VALID_SECONDS = 90 * 86400      # no manifest is good for longer than this
DEFAULT_VALID_DAYS = 30
CLOCK_SKEW_SECONDS = 86400          # how far a copy's clock may be off, either way
SIGNING_SLACK_SECONDS = 600         # how far `published` may be ahead of the clock of whoever signs
DEFAULT_HOSTS = ("github.com",)
NOTHING_INSTALLED = (0, 0, 0, 0)    # 0.0.0.0: the installed version of the installer; no release has it

# Public keys under which a signature proves nothing: all zero (a key that was never filled in) and the
# other points of small order, under which a made-up signature fits one message in eight or more. A key is
# compared with these after the top bit of its last byte is cleared.
WEAK_KEYS = frozenset(bytes.fromhex(text) for text in (
    "00" * 32,
    "01" + "00" * 31,
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "ec" + "ff" * 30 + "7f",
    "ed" + "ff" * 30 + "7f",
    "ee" + "ff" * 30 + "7f",
))

OSES = ("win", "linux")
# avx512 is opt-in (ROADMAP P5.11): in the schema from the start, because a reader refuses a variant it does
# not know, so one added after the first release would make every older updater refuse the manifest
CPUS = {"x64": ("avx2", "sse4", "avx512"), "arm64": ("armv8",)}
VARIANTS = tuple(f"{os_}-{arch}-{cpu}" for os_ in OSES for arch, cpus in CPUS.items() for cpu in cpus)
KINDS = ("installed", "portable")
TOP_KEYS = ("channel", "chromium_version", "critical", "expires", "min_updater_version", "packages",
            "published", "schema", "serial", "thoron_version", "version")
FILE_KEYS = ("sha256", "size", "url")

# What a copy of Thoron makes of a manifest (decide, check_update).
UPDATE = "update"                    # a newer version, with a package for this copy
UP_TO_DATE = "up_to_date"            # the current manifest names the installed version
BAD_SIGNATURE = "bad_signature"      # the signature does not hold: nothing was read
MALFORMED = "malformed"              # empty, too long, or signed and still not a manifest of this schema
WRONG_CHANNEL = "wrong_channel"      # a manifest of another channel
REPLAYED = "replayed"                # older than a manifest this copy has already accepted
NOT_YET_VALID = "not_yet_valid"      # dated after this computer's clock
EXPIRED = "expired"                  # too old to say what the newest release is
DOWNGRADE = "downgrade"              # names a version below the installed one
UPDATER_TOO_OLD = "updater_too_old"  # this updater may not apply the release
NO_PACKAGE = "no_package"            # a newer version, but nothing for this variant and kind
OUTCOMES = (UPDATE, UP_TO_DATE, BAD_SIGNATURE, MALFORMED, WRONG_CHANNEL, REPLAYED, NOT_YET_VALID, EXPIRED,
            DOWNGRADE, UPDATER_TOO_OLD, NO_PACKAGE)
# Outcomes after which the updater does not know whether this copy is current. None of them is "up to date".
CANNOT_VERIFY = frozenset({BAD_SIGNATURE, MALFORMED, WRONG_CHANNEL, REPLAYED, NOT_YET_VALID, EXPIRED, DOWNGRADE})

_CHANNEL = re.compile(r"[a-z][a-z0-9-]{0,31}")
_BUILD = re.compile(r"(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){3}")
_THORON = re.compile(r"(?:0|[1-9][0-9]{0,3})(?:\.(?:0|[1-9][0-9]{0,3})){2}")
_TIME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOST = re.compile(rf"{_LABEL}(?:\.{_LABEL})+")
_URL = re.compile(r"https://([a-z0-9.-]+)((?:/[A-Za-z0-9._~+-]+)+)")
_NOT_PLAIN = re.compile(rb"[^\n\x20-\x7e]")
_PLAIN_NAME = re.compile(r"[A-Za-z0-9._-]{1,40}")


class ManifestError(Exception):
    """The bytes or the data are not a manifest of this schema; `problems` lists every reason."""

    def __init__(self, *problems: str):
        super().__init__("; ".join(problems))
        self.problems = list(problems)


class SignatureError(Exception):
    """The signature is not this key's signature of these bytes."""


# --- times and versions ------------------------------------------------------------------------------------

def parse_time(text) -> int:
    """Seconds since 1970 of a time written as 2026-12-01T12:00:00Z: UTC, to the second, nothing else."""
    m = _TIME.fullmatch(text) if type(text) is str else None
    if not m:
        raise ValueError("must be a UTC time written like 2026-12-01T12:00:00Z")
    parts = tuple(int(x) for x in m.groups())
    try:
        datetime.datetime(*parts)
    except ValueError:
        raise ValueError("is not a real date and time") from None
    if parts[0] < 1970:
        raise ValueError("must not be before 1970")
    return calendar.timegm(parts)


def format_time(seconds: int) -> str:
    try:
        t = datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=seconds)
    except OverflowError:
        raise ValueError(f"{seconds} seconds since 1970 is not a date") from None
    return f"{t.year:04d}-{t.month:02d}-{t.day:02d}T{t.hour:02d}:{t.minute:02d}:{t.second:02d}Z"


def _clock(seconds: int) -> str:
    """A clock reading for a message; a reading outside the calendar must not stop a check."""
    try:
        return format_time(seconds)
    except ValueError as exc:
        return str(exc)


def build_key(text) -> tuple[int, int, int, int]:
    """A build version as tools/release/version.py reads it, accepted only in its one written form
    (no leading zeros), so that two equal versions are always equal strings."""
    if type(text) is not str or not _BUILD.fullmatch(text):
        raise ver.VersionError("must be a build version of four numbers without leading zeros, "
                               "like 158.0.8127.3000")
    return ver.key(text)


def thoron_key(text) -> tuple[int, int, int]:
    if type(text) is not str or not _THORON.fullmatch(text):
        raise ver.VersionError("must be a Thoron version of three numbers without leading zeros, like 0.1.2")
    return ver.thoron_key(text)


# --- the schema --------------------------------------------------------------------------------------------

def _hosts(allowed_hosts) -> frozenset:
    try:
        hosts = None if isinstance(allowed_hosts, (str, bytes)) else frozenset(allowed_hosts)
    except TypeError:
        hosts = None
    if not hosts or not all(type(h) is str and _HOST.fullmatch(h) for h in hosts):
        raise ValueError("allowed_hosts is a list of at least one host name, each in lower case like github.com")
    return hosts


def _quoted(name) -> str:
    """A key of the manifest for a message: escaped, in ASCII, and cut short."""
    text = json.dumps(name) if type(name) is str else ascii(name)
    return text if len(text) <= 60 else text[:57] + "..."


def _shown(name) -> str:
    """A key as a step of a path in a message: as it is when it is a plain name, else quoted."""
    return name if type(name) is str and _PLAIN_NAME.fullmatch(name) else _quoted(name)


def _keys(out: list, where: str, obj: dict, required, allowed) -> None:
    at = f"{where}: " if where else ""
    out += [f"{at}unknown key {_quoted(k)}" for k in sorted(obj, key=str) if k not in allowed]
    out += [f"{at}missing key {_quoted(k)}" for k in required if k not in obj]


def url_problem(url, hosts) -> str | None:
    """Why a package may not be downloaded from `url`; None when it may."""
    if type(url) is not str:
        return "must be a string"
    if len(url) > MAX_URL_CHARS:
        return f"must be at most {MAX_URL_CHARS} characters"
    m = _URL.fullmatch(url)
    if not m:
        return "must be https://<host>/<path>, with no user name, port, query, fragment, escape or empty segment"
    if any(segment in (".", "..") for segment in m.group(2).split("/")):
        return 'must not have "." or ".." as a path segment'
    if m.group(1) not in hosts:
        return f"host {_shown(m.group(1))} is not on the allow-list ({', '.join(sorted(hosts))})"
    return None


def _file(out: list, where: str, entry, hosts) -> None:
    if type(entry) is not dict:
        out.append(f"{where}: must be an object with url, size and sha256")
        return
    _keys(out, where, entry, FILE_KEYS, FILE_KEYS)
    if "url" in entry:
        problem = url_problem(entry["url"], hosts)
        if problem:
            out.append(f"{where}/url: {problem}")
    if "size" in entry and not (type(entry["size"]) is int and 0 < entry["size"] <= MAX_INT):
        out.append(f"{where}/size: must be a whole number of bytes from 1 to {MAX_INT}")
    if "sha256" in entry and not (type(entry["sha256"]) is str and _SHA256.fullmatch(entry["sha256"])):
        out.append(f"{where}/sha256: must be 64 lower-case hex digits")


def _deltas(out: list, where: str, deltas, version, hosts) -> None:
    if type(deltas) is not dict or not 1 <= len(deltas) <= MAX_DELTAS:
        out.append(f"{where}: must hold 1 to {MAX_DELTAS} deltas, each under the version it applies from "
                   "(leave the key out when there are none)")
        return
    for base, entry in deltas.items():
        at = f"{where}/{_shown(base)}"
        try:
            base_key = build_key(base)
        except ver.VersionError as exc:
            out.append(f"{at}: {exc}")
            continue
        if base_key == NOTHING_INSTALLED:
            out.append(f"{at}: a delta applies from a release; 0.0.0.0 stands for nothing installed")
        elif version and base_key >= version:
            out.append(f"{at}: a delta applies from a version lower than the manifest's version")
        _file(out, at, entry, hosts)


def _packages(out: list, packages, version, hosts) -> None:
    if type(packages) is not dict or not packages:
        out.append("packages: must be an object with at least one variant")
        return
    for variant, kinds in packages.items():
        where = f"packages/{_shown(variant)}"
        if variant not in VARIANTS:
            out.append(f"{where}: unknown variant (the names are in MANIFEST.md, section 4)")
            continue
        if type(kinds) is not dict or not kinds:
            out.append(f"{where}: must be an object with installed, portable or both")
            continue
        for kind, package in kinds.items():
            at = f"{where}/{_shown(kind)}"
            if kind not in KINDS:
                out.append(f"{at}: unknown package kind (known: {', '.join(KINDS)})")
            elif type(package) is not dict:
                out.append(f"{at}: must be an object with full and, when there are any, deltas")
            else:
                _keys(out, at, package, ("full",), ("deltas", "full"))
                if "full" in package:
                    _file(out, f"{at}/full", package["full"], hosts)
                if "deltas" in package:
                    _deltas(out, f"{at}/deltas", package["deltas"], version, hosts)


def _version(out: list, data: dict, name: str, read=build_key):
    if name not in data:
        return None
    try:
        return read(data[name])
    except ver.VersionError as exc:
        out.append(f"{name}: {exc}")
        return None


def _time(out: list, data: dict, name: str):
    if name not in data:
        return None
    try:
        return parse_time(data[name])
    except ValueError as exc:
        out.append(f"{name}: {exc}")
        return None


def problems(data, allowed_hosts) -> list[str]:
    """Every reason `data` (a manifest as parsed JSON) is not a schema 1 manifest; empty when it is one."""
    hosts = _hosts(allowed_hosts)
    if type(data) is not dict:
        return ["a manifest is one JSON object"]
    out: list[str] = []
    _keys(out, "", data, TOP_KEYS, TOP_KEYS)
    if "schema" in data and not (type(data["schema"]) is int and data["schema"] == SCHEMA):
        out.append(f"schema: must be {SCHEMA}")
    if "channel" in data and not (type(data["channel"]) is str and _CHANNEL.fullmatch(data["channel"])):
        out.append('channel: must be a lower-case name like "stable" (letters, digits, "-"; at most 32)')
    if "critical" in data and type(data["critical"]) is not bool:
        out.append("critical: must be true or false")
    version = _version(out, data, "version")
    chromium = _version(out, data, "chromium_version")
    minimum = _version(out, data, "min_updater_version")
    _version(out, data, "thoron_version", thoron_key)
    if version == NOTHING_INSTALLED:
        out.append("version: 0.0.0.0 stands for nothing installed and is no release")
    if version and chromium and ver.split(data["version"])[0] != data["chromium_version"]:
        out.append(f"chromium_version: build {data['version']} is Chromium {ver.split(data['version'])[0]}, "
                   f"not {data['chromium_version']}")
    if version and minimum and minimum > version:
        out.append("min_updater_version: must not be higher than version")
    published = _time(out, data, "published")
    expires = _time(out, data, "expires")
    if published is not None and expires is not None:
        if expires <= published:
            out.append("expires: must be later than published")
        elif expires - published > MAX_VALID_SECONDS:
            out.append(f"expires: must be at most {MAX_VALID_SECONDS // 86400} days after published")
    if "serial" in data:
        serial = data["serial"]
        if not (type(serial) is int and 0 < serial <= MAX_INT):
            out.append(f"serial: must be a whole number from 1 to {MAX_INT}")
        elif published is not None and serial // 100 != _day(data["published"]):
            out.append("serial: must be the UTC day of published and two more digits (YYYYMMDDNN)")
    if "packages" in data:
        _packages(out, data["packages"], version, hosts)
    return out


def _day(time_text: str) -> int:
    return int(time_text[0:4] + time_text[5:7] + time_text[8:10])


# --- bytes -------------------------------------------------------------------------------------------------

def canonical(data) -> bytes:
    """The one way a manifest is written: keys sorted, two spaces a level, LF, ASCII, one LF at the end."""
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def serialize(data, *, allowed_hosts) -> bytes:
    """The bytes of a manifest; ManifestError when `data` is not one."""
    found = problems(data, allowed_hosts)
    if found:
        raise ManifestError(*found)
    raw = canonical(data)
    _check_length(raw)
    return raw


def _check_length(manifest: bytes) -> None:
    if not 0 < len(manifest) <= MAX_MANIFEST_BYTES:
        raise ManifestError(f"a manifest is 1 to {MAX_MANIFEST_BYTES} bytes, not {len(manifest)}")


def _exact_bytes(**values) -> None:
    """One immutable buffer is what gets checked and what gets read: nothing that only acts like bytes."""
    for name, value in values.items():
        if type(value) is not bytes:
            raise TypeError(f"{name} must be bytes, not {type(value).__name__}")


def _object(pairs) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise ManifestError(f"duplicate key {_quoted(key)}")
        out[key] = value
    return out


def _not_whole(_text):
    # The number itself is not repeated: the file may be something else, given by mistake.
    raise ManifestError("a number that is not a whole number written in digits")


def parse(manifest: bytes, *, allowed_hosts) -> dict:
    """The content of manifest bytes, or ManifestError. This reads the bytes as data, so an updater reaches
    it only through verify(); alone it serves the release tooling, before there is a signature."""
    _exact_bytes(manifest=manifest)
    hosts = _hosts(allowed_hosts)
    _check_length(manifest)
    bad = _NOT_PLAIN.search(manifest)
    if bad:     # the byte is named only when it is a usual slip; the file may be another one, given by mistake
        what = {0x0D: "a CR (line ends are LF alone)", 0x09: "a tab"}.get(bad.group()[0], "a byte that is no text")
        raise ManifestError(f"offset {bad.start()}: {what}; only printable ASCII and LF are allowed")
    try:
        data = json.loads(manifest.decode("ascii"), object_pairs_hook=_object, parse_float=_not_whole,
                          parse_constant=_not_whole)
    except (ValueError, RecursionError) as exc:
        raise ManifestError(f"not JSON: {exc}") from None
    found = problems(data, hosts)
    if found:
        raise ManifestError(*found)
    if canonical(data) != manifest:
        raise ManifestError("not in canonical form: keys sorted, two spaces a level, LF, one LF at the end")
    return data


# --- the signature -----------------------------------------------------------------------------------------

def _ed25519():
    from cryptography.hazmat.primitives.asymmetric import ed25519
    return ed25519


def signed_message(manifest: bytes) -> bytes:
    """What the signature is over: the purpose prefix, then the manifest exactly as published."""
    return SIGNATURE_PREFIX + manifest


def public_key_of(private_key: bytes) -> bytes:
    from cryptography.hazmat.primitives import serialization
    key = _ed25519().Ed25519PrivateKey.from_private_bytes(private_key)
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def usable_key(public_key: bytes) -> bool:
    """False for what is no key: not 32 bytes, all zero (never filled in), or a point of small order.
    Under such a key made-up signatures verify, so with it nothing does."""
    _exact_bytes(public_key=public_key)
    return len(public_key) == KEY_BYTES and public_key[:31] + bytes([public_key[31] & 0x7F]) not in WEAK_KEYS


def signature_holds(manifest: bytes, signature: bytes, public_key: bytes) -> bool:
    """True only when `signature` is this key's signature of exactly these manifest bytes."""
    _exact_bytes(manifest=manifest, signature=signature)
    if len(signature) != SIGNATURE_BYTES or not usable_key(public_key):
        return False
    from cryptography.exceptions import InvalidSignature
    ed25519 = _ed25519()
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(public_key).verify(signature, signed_message(manifest))
    except (InvalidSignature, ValueError):
        return False
    return True


def verify(manifest: bytes, signature: bytes, public_key: bytes, *, allowed_hosts) -> dict:
    """The content of a manifest whose signature holds. The signature is checked over the exact bytes
    before any of them is read as data: SignatureError when it does not hold, ManifestError when it holds
    and the bytes are still not a manifest (or when there are none, or too many to check)."""
    _exact_bytes(manifest=manifest, signature=signature, public_key=public_key)
    hosts = _hosts(allowed_hosts)
    _check_length(manifest)
    if not signature_holds(manifest, signature, public_key):
        raise SignatureError("the signature does not hold for these bytes")
    return parse(manifest, allowed_hosts=hosts)


def _raw_signature(private_key: bytes, message: bytes) -> bytes:
    return _ed25519().Ed25519PrivateKey.from_private_bytes(private_key).sign(message)


def sign(manifest: bytes, private_key: bytes, public_key: bytes, *, allowed_hosts, now: int) -> bytes:
    """The detached signature of a manifest: 64 bytes. `public_key` is the key that copies of Thoron hold
    and `now` the clock in seconds since 1970. Nothing is signed that a copy would refuse today: bytes that
    are not a valid manifest in its written form, a manifest dated ahead of the clock or already expired,
    or a private key that is not the one copies trust. A signature that does not verify is not handed out."""
    _exact_bytes(manifest=manifest, private_key=private_key, public_key=public_key)
    data = parse(manifest, allowed_hosts=allowed_hosts)
    _check_clock(now)
    if parse_time(data["published"]) > now + SIGNING_SLACK_SECONDS:
        raise ManifestError(f"published: {data['published']} is ahead of the clock ({_clock(now)}); a manifest "
                            "is dated when it is made, not later")
    if now >= parse_time(data["expires"]):
        raise ManifestError(f"expires: {data['expires']} has passed (the clock says {_clock(now)})")
    if len(private_key) != KEY_BYTES:
        raise ValueError(f"the private key is {KEY_BYTES} bytes")
    if not usable_key(public_key):
        raise ValueError(f"the public key is no usable key: it is {KEY_BYTES} bytes, not all zero and not of "
                         "small order")
    if public_key_of(private_key) != public_key:
        raise ValueError("the private key does not belong to the public key that copies of Thoron hold")
    signature = _raw_signature(private_key, signed_message(manifest))
    if not signature_holds(manifest, signature, public_key):
        raise SignatureError("the signature just made does not verify; it is not handed out")
    return signature


# --- what a copy of Thoron does with a manifest ------------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    outcome: str                        # one of OUTCOMES
    detail: str                         # the reason, in words, for the log
    manifest: dict | None = None        # the content, only when the manifest is the channel's current one
    remember_serial: int | None = None  # to store as the highest serial accepted, when not None
    full: dict | None = None            # with UPDATE: the full package (url, size, sha256); with
                                        # UPDATER_TOO_OLD too, when the release has a package for this copy:
                                        # the old updater fetches it and hands the apply to the updater in it
    delta: dict | None = None           # with UPDATE only: the delta from the installed version, if there is
                                        # one; an updater that is too old never applies a delta

    @property
    def cannot_verify(self) -> bool:
        return self.outcome in CANNOT_VERIFY


def freshness(data: dict, *, channel: str, last_serial: int, now: int,
              skew: int = CLOCK_SKEW_SECONDS) -> tuple[str, str] | None:
    """Why a verified manifest is not its channel's current word (outcome, detail); None when it is."""
    _check_clock(now, skew, last_serial)
    if data["channel"] != channel:
        return WRONG_CHANNEL, f"the manifest is for channel {data['channel']}; this copy follows {_shown(channel)}"
    if data["serial"] < last_serial:
        return REPLAYED, f"serial {data['serial']} is below {last_serial}, which this copy has accepted before"
    if parse_time(data["published"]) > now + skew:
        return NOT_YET_VALID, (f"published {data['published']} is after this computer's clock "
                               f"({_clock(now)}): the clock is behind, or the manifest is wrong")
    if now > parse_time(data["expires"]) + skew:
        return EXPIRED, (f"expired {data['expires']} (the clock says {_clock(now)}): it no longer "
                         "shows what the newest release is")
    return None


def _check_clock(now, skew=0, last_serial=0) -> None:
    for name, value in (("now", now), ("skew", skew), ("last_serial", last_serial)):
        if type(value) is not int:
            raise TypeError(f"{name} must be a whole number, not {type(value).__name__}")
    if skew < 0 or last_serial < 0:
        raise ValueError("skew and last_serial are not below zero")


def _check_copy(channel, installed, updater, variant, kind) -> None:
    """What a copy says about itself has to make sense whatever the manifest is: an error, not an outcome."""
    if not (type(channel) is str and _CHANNEL.fullmatch(channel)):
        raise ValueError(f"not a channel: {channel!r}")
    build_key(installed)
    build_key(updater)
    if variant not in VARIANTS or kind not in KINDS:
        raise ValueError(f"not a variant and kind: {variant!r}, {kind!r}")


def decide(data: dict, *, channel: str, installed: str, updater: str, variant: str, kind: str, now: int,
           last_serial: int = 0, skew: int = CLOCK_SKEW_SECONDS) -> Decision:
    """What a copy of Thoron does with a manifest that verify() returned. `installed` is the installed build
    version ("0.0.0.0" for the installer, which has nothing installed yet) and `updater` the build version
    of the updater itself; `last_serial` is the highest serial this copy has accepted on the channel (0 for
    none) and `now` the clock in seconds since 1970."""
    _check_copy(channel, installed, updater, variant, kind)
    stale = freshness(data, channel=channel, last_serial=last_serial, now=now, skew=skew)
    if stale:
        return Decision(stale[0], stale[1])
    installed_key, updater_key = ver.key(installed), ver.key(updater)
    serial, version = data["serial"], data["version"]
    if ver.key(version) < installed_key:
        return Decision(DOWNGRADE, f"the manifest names {version}, below the installed {installed}: nothing "
                        "older is ever installed", data, serial)
    if ver.key(version) == installed_key:
        return Decision(UP_TO_DATE, f"{version} is installed and is the newest release", data, serial)
    package = data["packages"].get(variant, {}).get(kind)
    if updater_key < ver.key(data["min_updater_version"]):
        # P4.6: this updater may not apply the release, so it fetches the whole package and the updater in it
        # applies it (the old one never runs a delta or the swap)
        return Decision(UPDATER_TOO_OLD, f"{version} needs an updater of {data['min_updater_version']} or "
                        f"later; this one is {updater}", data, serial, package["full"] if package else None)
    if package is None:
        return Decision(NO_PACKAGE, f"{version} has no {kind} package for {variant}", data, serial)
    return Decision(UPDATE, f"{version} (Thoron {data['thoron_version']}) replaces {installed}", data, serial,
                    package["full"], package.get("deltas", {}).get(installed))


def check_update(manifest: bytes, signature: bytes, public_key: bytes, *, allowed_hosts, channel: str,
                 installed: str, updater: str, variant: str, kind: str, now: int, last_serial: int = 0,
                 skew: int = CLOCK_SKEW_SECONDS) -> Decision:
    """The whole check, from the two files as fetched to a decision: verify(), then decide(). Whatever the
    two files hold is an outcome and never raises. What the caller says about its own copy is checked
    first, before the files are looked at, and is an error when it makes no sense."""
    _check_copy(channel, installed, updater, variant, kind)
    _check_clock(now, skew, last_serial)
    try:
        data = verify(manifest, signature, public_key, allowed_hosts=allowed_hosts)
    except SignatureError as exc:
        return Decision(BAD_SIGNATURE, str(exc))
    except ManifestError as exc:
        return Decision(MALFORMED, str(exc))
    return decide(data, channel=channel, installed=installed, updater=updater, variant=variant, kind=kind,
                  now=now, last_serial=last_serial, skew=skew)


# --- making a manifest (the release tooling) ---------------------------------------------------------------

def file_entry(path: Path, url: str) -> dict:
    """The entry of a package on disk: its size, its SHA-256, and where it will be downloaded from."""
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    return {"url": url, "size": size, "sha256": digest.hexdigest()}


def next_serial(published: int, previous_serial: int = 0) -> int:
    """The serial of a manifest published at `published`: its UTC day, then a two-digit count that puts
    it above the manifest before it."""
    first = _day(format_time(published)) * 100
    if previous_serial < first:
        return first
    if previous_serial >= first + 99:
        raise ManifestError(f"serial: the manifest before this one has {previous_serial}; no serial of "
                            f"{format_time(published)[:10]} is above it")
    return previous_serial + 1


def succession_problems(new: dict, previous: dict) -> list[str]:
    """Why manifest `new` may not be published after `previous` (both valid); empty when it may."""
    out = []
    if new["channel"] != previous["channel"]:
        out.append(f"channel: {new['channel']} cannot follow a manifest of channel {previous['channel']}")
    if new["serial"] <= previous["serial"]:
        out.append(f"serial: {new['serial']} is not higher than the previous manifest's {previous['serial']}")
    if parse_time(new["published"]) < parse_time(previous["published"]):
        out.append(f"published: {new['published']} is before the previous manifest's {previous['published']}")
    build, old_build = ver.key(new["version"]), ver.key(previous["version"])
    thoron, old_thoron = ver.thoron_key(new["thoron_version"]), ver.thoron_key(previous["thoron_version"])
    if build < old_build:
        out.append(f"version: {new['version']} is lower than the previous manifest's {previous['version']}")
    elif build == old_build and thoron != old_thoron:
        out.append(f"thoron_version: build {new['version']} is Thoron {previous['thoron_version']} in the "
                   f"previous manifest, not {new['thoron_version']}")
    elif build > old_build and thoron <= old_thoron:
        out.append(f"thoron_version: {new['thoron_version']} is not higher than the previous release "
                   f"{previous['thoron_version']}")
    return out


def build(*, channel: str, version: str, thoron_version: str, critical: bool, min_updater_version: str,
          packages: dict, published: int, allowed_hosts, valid_days: int = DEFAULT_VALID_DAYS,
          previous: dict | None = None) -> bytes:
    """The bytes of a new manifest, ready to sign. `published` is the clock in seconds since 1970;
    `previous` is the content of the manifest it replaces on the channel, when there is one."""
    if type(published) is not int or type(valid_days) is not int:
        raise ManifestError("published is the clock in whole seconds and valid_days a whole number of days")
    if previous is not None:
        found = problems(previous, allowed_hosts)
        if found:
            raise ManifestError(*(f"the manifest before this one: {problem}" for problem in found))
    try:
        build_key(version)
        chromium = ver.split(version)[0]
        published_text, expires_text = format_time(published), format_time(published + valid_days * 86400)
    except ver.VersionError as exc:
        raise ManifestError(f"version: {exc}") from None
    except ValueError as exc:
        raise ManifestError(f"published: {exc}") from None
    data = {
        "schema": SCHEMA, "channel": channel,
        "serial": next_serial(published, previous["serial"] if previous is not None else 0),
        "published": published_text, "expires": expires_text,
        "version": version, "thoron_version": thoron_version, "chromium_version": chromium,
        "critical": critical, "min_updater_version": min_updater_version, "packages": packages,
    }
    raw = serialize(data, allowed_hosts=allowed_hosts)
    found = succession_problems(data, previous) if previous is not None else []
    if found:
        raise ManifestError(*found)
    return raw


def renew(previous_raw: bytes, *, published: int, allowed_hosts, valid_days: int = DEFAULT_VALID_DAYS) -> bytes:
    """The same release in a new manifest, ready to sign: published at `published`, a higher serial, expiring
    `valid_days` later; channel, versions, critical, minimum updater and packages as the manifest before it
    has them. Copies take it as the channel's current manifest (it may follow the one before it); without it a
    channel that has no new release before the old manifest expires leaves its copies unable to check."""
    previous = parse(previous_raw, allowed_hosts=allowed_hosts)
    return build(channel=previous["channel"], version=previous["version"],
                 thoron_version=previous["thoron_version"], critical=previous["critical"],
                 min_updater_version=previous["min_updater_version"], packages=previous["packages"],
                 published=published, allowed_hosts=allowed_hosts, valid_days=valid_days, previous=previous)


def example() -> bytes:
    """A valid manifest with made-up packages: the example of docs/update/MANIFEST.md."""
    new, old = "158.0.8127.4500", "158.0.8127.3000"

    def entry(name: str, size: int) -> dict:
        return {"url": f"https://github.com/KuchiSofts/thoron/releases/download/v0.1.2/{name}", "size": size,
                "sha256": hashlib.sha256(name.encode("ascii")).hexdigest()}

    packages = {
        "win-x64-avx2": {
            "installed": {"full": entry(f"thoron-{new}-win-x64-avx2-installer.exe", 104857600),
                          "deltas": {old: entry(f"thoron-{old}-to-{new}-win-x64-avx2-installed.delta", 9437184)}},
            "portable": {"full": entry(f"thoron-{new}-win-x64-avx2-portable.zip", 157286400)},
        },
        "win-x64-sse4": {
            "installed": {"full": entry(f"thoron-{new}-win-x64-sse4-installer.exe", 103809024)},
        },
    }
    return build(channel="stable", version=new, thoron_version="0.1.2", critical=True, min_updater_version=old,
                 packages=packages, published=parse_time("2026-12-01T12:00:00Z"), allowed_hosts=DEFAULT_HOSTS)


# --- command line ------------------------------------------------------------------------------------------

def read_private_key(path: Path) -> bytes:
    """The release key from its file: 32 bytes in base64, as the key ceremony writes it."""
    try:
        key = base64.b64decode(path.read_bytes().strip(), validate=True)
    except ValueError:
        raise ValueError("the key file does not hold base64") from None
    if len(key) != KEY_BYTES:
        raise ValueError(f"the key file does not hold a {KEY_BYTES}-byte key")
    return key


def _summary(data: dict) -> str:
    return (f"Thoron {data['thoron_version']} (build {data['version']}), channel {data['channel']}, "
            f"serial {data['serial']}, good until {data['expires']}")


def _refused(error: ManifestError) -> int:
    for problem in error.problems:
        print(f"manifest: {problem}", file=sys.stderr)
    print(f"manifest: refused, {len(error.problems)} problem(s)")
    return 1


def _public_key(text: str) -> bytes:
    key = base64.b64decode(text, validate=True)
    if not usable_key(key):
        raise ValueError(f"--public-key is {KEY_BYTES} bytes in base64, not all zero and not of small order")
    return key


def _write_new(path: Path, content: bytes) -> bool:
    try:
        with path.open("xb") as f:
            f.write(content)
    except FileExistsError:
        print(f"manifest: {path} exists; a file is never overwritten")
        return False
    return True


def _run(a) -> int:
    if a.command == "key-statement":
        statement = sign_key_statement(read_private_key(a.old_key), _public_key(a.new_public_key))
        if not _write_new(a.out, statement):
            return 1
        print(f"key statement: {a.out.name} introduces {base64.b64encode(statement[:KEY_BYTES]).decode()}")
        return 0
    if a.command == "check-key-statement":
        key = key_from_statement(a.statement.read_bytes(), [_public_key(a.public_key)])
        if key is None:
            print("key statement: not signed by that key, or no statement")
            return 1
        print(f"key statement: introduces {base64.b64encode(key).decode()}")
        return 0
    if a.command == "example":
        raw = example()
        if a.out:
            return 0 if _write_new(a.out, raw) else 1
        if hasattr(sys.stdout, "buffer"):
            # The bytes as they are. A shell that re-encodes what it redirects (PowerShell's ">") still
            # changes them: --out is the way to get the file.
            sys.stdout.buffer.write(raw)
        else:
            sys.stdout.write(raw.decode("ascii"))
        return 0
    hosts = a.host or DEFAULT_HOSTS
    if a.command == "verify":
        if a.last_serial < 0:
            raise ValueError("--last-serial is not below zero")
        if not a.installed and (a.variant or a.kind or a.updater):
            raise ValueError("--variant, --kind and --updater go with --installed")
        if a.installed and not (a.variant and a.kind):
            raise ValueError("--installed goes with --variant and --kind")
    raw = a.manifest.read_bytes()
    if a.command == "renew":
        try:
            made = renew(raw, published=int(time.time()), allowed_hosts=hosts, valid_days=a.valid_days)
        except ManifestError as exc:
            return _refused(exc)
        if not _write_new(a.out, made):
            return 1
        print(f"manifest: renewed, {_summary(parse(made, allowed_hosts=hosts))}; sign it with --previous "
              f"{a.manifest.name}")
        return 0
    if a.command == "validate":
        print(f"manifest: OK, {_summary(parse(raw, allowed_hosts=hosts))}")
        return 0
    if a.command == "sign":
        public_key = _public_key(a.public_key)
        data = parse(raw, allowed_hosts=hosts)
        if a.previous:
            found = succession_problems(data, parse(a.previous.read_bytes(), allowed_hosts=hosts))
            if found:
                return _refused(ManifestError(*found))
        out = a.out or a.manifest.with_name(a.manifest.name + ".sig")
        if out.exists():
            print(f"manifest: {out} exists; a file is never overwritten")
            return 1
        signature = sign(raw, read_private_key(a.key), public_key, allowed_hosts=hosts, now=int(time.time()))
        if not _write_new(out, signature):
            return 1
        print(f"manifest: signed, {_summary(data)}")
        return 0
    signature = (a.signature or a.manifest.with_name(a.manifest.name + ".sig")).read_bytes()
    try:
        data = verify(raw, signature, _public_key(a.public_key), allowed_hosts=hosts)
    except SignatureError as exc:
        print(f"manifest: REFUSED ({BAD_SIGNATURE}): {exc}")
        return 1
    now = parse_time(a.now) if a.now is not None else int(time.time())
    channel = a.channel or data["channel"]
    if a.installed:
        decision = decide(data, channel=channel, installed=a.installed, updater=a.updater or a.installed,
                          variant=a.variant, kind=a.kind, now=now, last_serial=a.last_serial)
        print(f"manifest: {decision.outcome}: {decision.detail}")
        for name, package in (("full", decision.full), ("delta", decision.delta)):
            if package:
                print(f"manifest: {name} package {package['url']} ({package['size']} bytes)")
        return 0 if decision.outcome in (UPDATE, UP_TO_DATE) else 1
    stale = freshness(data, channel=channel, last_serial=a.last_serial, now=now)
    if stale:
        print(f"manifest: REFUSED ({stale[0]}): {stale[1]}")
        return 1
    print(f"manifest: the signature holds, {_summary(data)}")
    return 0


# --- key rotation (ROADMAP P4.7) -------------------------------------------------------------------------
#
# A copy trusts the key it was built with. A release that moves to a new key publishes, beside the manifest,
# a key statement: the new public key and the signature of the old key over the purpose prefix and the new
# key. A copy that trusts the old key then trusts the new one too, and keeps it; a chain of statements is
# followed from key to key. A manifest is checked under each trusted key in turn (MANIFEST.md, section 11:
# an updater that trusts two keys tries both). A statement no trusted key signed is ignored.

def sign_key_statement(old_private_key: bytes, new_public_key: bytes) -> bytes:
    """The key statement that introduces `new_public_key` under the old key: 96 bytes."""
    _exact_bytes(old_private_key=old_private_key, new_public_key=new_public_key)
    if not usable_key(new_public_key):
        raise ManifestError("the new key is no key: all zero or a point of small order")
    if len(old_private_key) != KEY_BYTES:
        raise ManifestError("the old private key is 32 bytes")
    return new_public_key + _raw_signature(old_private_key, KEY_STATEMENT_PREFIX + new_public_key)


def key_from_statement(statement: bytes, trusted: list[bytes]) -> bytes | None:
    """The key `statement` introduces, when it is a statement and one of `trusted` signed it."""
    _exact_bytes(statement=statement)
    if len(statement) != KEY_STATEMENT_BYTES:
        return None
    new_key, signature = statement[:KEY_BYTES], statement[KEY_BYTES:]
    if not usable_key(new_key):
        return None
    from cryptography.exceptions import InvalidSignature
    ed25519 = _ed25519()
    for key in trusted:
        if not usable_key(key):
            continue
        try:
            ed25519.Ed25519PublicKey.from_public_bytes(key).verify(signature, KEY_STATEMENT_PREFIX + new_key)
        except (InvalidSignature, ValueError):
            continue
        return new_key
    return None


def trusted_keys(built_in: bytes, statements: list[bytes]) -> list[bytes]:
    """The keys a copy trusts: its own, and every key a chain of `statements` leads to from it, in the order
    they were reached. At most MOST_KEY_STATEMENTS statements are read."""
    keys = [built_in]
    pending = list(statements[:MOST_KEY_STATEMENTS])
    found = True
    while found:
        found = False
        for statement in list(pending):
            key = key_from_statement(statement, keys)
            if key is not None:
                pending.remove(statement)
                if key not in keys:
                    keys.append(key)
                found = True
    return keys


def check_update_with_keys(manifest: bytes, signature: bytes, keys: list[bytes], **copy) -> "Decision":
    """check_update() under each key in turn: the first answer that is not bad_signature, else that one."""
    answer = None
    for key in keys:
        answer = check_update(manifest, signature, key, **copy)
        if answer.outcome != BAD_SIGNATURE:
            return answer
    return answer if answer is not None else check_update(manifest, signature, bytes(KEY_BYTES), **copy)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    e = sub.add_parser("example", help="print a valid manifest with made-up packages")
    e.add_argument("--out", type=Path, help="write it to a new file, byte for byte")
    v = sub.add_parser("validate", help="list every problem of a manifest")
    s = sub.add_parser("sign", help="write the detached signature of a valid manifest")
    s.add_argument("--key", required=True, type=Path, help="the private key file (base64 of 32 bytes)")
    s.add_argument("--public-key", required=True, help="the public key copies of Thoron hold, base64 of 32 "
                   "bytes: the private key must be its other half")
    before = s.add_mutually_exclusive_group(required=True)
    before.add_argument("--previous", type=Path, help="the manifest this one replaces: it must not go back")
    before.add_argument("--first", action="store_true", help="the channel has no manifest yet")
    s.add_argument("--out", type=Path, help="the signature file (default: <manifest>.sig)")
    r = sub.add_parser("renew", help="the same release in a new manifest with later dates, ready to sign")
    r.add_argument("--out", type=Path, required=True, help="the new manifest (never overwritten)")
    r.add_argument("--valid-days", type=int, default=DEFAULT_VALID_DAYS, help="days until it expires")
    k = sub.add_parser("key-statement", help="write a key statement: the old key signs the new public key (P4.7)")
    k.add_argument("--old-key", type=Path, required=True, help="the old private key file (base64 of 32 bytes)")
    k.add_argument("--new-public-key", required=True, help="the new public key, base64 of 32 bytes")
    k.add_argument("--out", type=Path, required=True, help="the statement to write: update.key of a release")
    t = sub.add_parser("check-key-statement", help="say which key a statement introduces under a trusted key")
    t.add_argument("statement", type=Path)
    t.add_argument("--public-key", required=True, help="the trusted public key, base64 of 32 bytes")
    c = sub.add_parser("verify", help="check the signature, the manifest and its dates")
    c.add_argument("--public-key", required=True, help="the public key, base64 of 32 bytes")
    c.add_argument("--signature", type=Path, help="the signature file (default: <manifest>.sig)")
    c.add_argument("--now", help="the clock to check the dates against, like 2026-12-02T00:00:00Z")
    c.add_argument("--channel", help="the channel the copy follows (default: the manifest's own)")
    c.add_argument("--last-serial", type=int, default=0, help="the highest serial the copy has accepted")
    c.add_argument("--installed", help="the installed build version: show what that copy would do")
    c.add_argument("--updater", help="the updater's build version (default: the installed version)")
    c.add_argument("--variant", choices=VARIANTS)
    c.add_argument("--kind", choices=KINDS)
    for command in (v, s, c, r):
        command.add_argument("manifest", type=Path)
        command.add_argument("--host", action="append", help="a host packages may come from (default: github.com)")
    a = p.parse_args(argv)
    try:
        return _run(a)
    except ManifestError as exc:
        return _refused(exc)
    except (ver.VersionError, ValueError, OSError) as exc:
        print(f"manifest: {exc}", file=sys.stderr)
        return 2
    except ImportError:
        print("manifest: sign and verify need the Python package cryptography", file=sys.stderr)
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")    # a path the console cannot show must not stop the tool
    sys.exit(main(sys.argv[1:]))
