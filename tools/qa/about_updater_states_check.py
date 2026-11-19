#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Every state of the About page's update line, in a running Thoron (ROADMAP P3.9). Windows only.

It needs a build that trusts the published TEST key (`thoron_update_public_key` set to the test key of
components/thoron_update/make_test_vectors.py, whose private half is in the repository; nothing shipped trusts
it). That build runs as a portable copy (`tools/release/portable.py build`), so an update goes into the copy's
own folder and never into this PC's own Thoron. github.com, where the updater looks, is mapped to a local HTTPS
server (`--host-resolver-rules`) with a certificate made for this run and trusted by this browser only
(`--ignore-certificate-errors-spki-list`); every other name is unresolvable. The manifests are signed with the
test key, as `release.py` signs a release's.

Each case starts from a fresh copy of the portable folder, opens chrome://settings/help (which asks the
updater to look and to install what it finds) and reads the update line every 0.3 s. A line that names
Chromium instead of Thoron is a problem too (the first run found "Chromium is up to date": a tree where
upstream's string step had not run):

    up to date        the manifest names this build's version                     "... is up to date"
    error             there is no manifest (404)                                   "could not update: ..."
    cannot verify     the manifest is signed with another key                      "cannot verify updates"
    no package        a newer version, only for SSE4 computers                     "... not yet for this kind"
    needs installer   a newer version whose updater must be newer than this one,
                      with an installer only (no portable package)                 "... needs its own installer"
    update            a newer version (this build under the newer version's folder name); the manifest
                      comes after 3 s and the package slowly: "checking", then "updating" with its
                      percentage, then "relaunch"; the copy's `current` then names the newer version

    py -3 -I tools/qa/about_updater_states_check.py --chrome-bin <test key build's Chrome-bin>
        --launcher <out>\\thoron_launcher.exe --updater <out>\\thoron_update.exe --work <scratch dir>
Exit status 0 only when every case shows its state.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import http.server
import json
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa.about_updater_check import READ_STATUS  # noqa: E402
from tools.qa.adblock_site_switch_check import _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402
from tools.update import manifest as mf  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
# The published test keys (make_test_vectors.py): the private half is the SHA-256 of a phrase, no secret.
TEST_KEY = hashlib.sha256(b"thoron-update test vectors: a key for tests only, never a release key").digest()
OTHER_KEY = hashlib.sha256(b"thoron-update test vectors: another key for tests only").digest()
GH_REPO = "KuchiSofts/thoron"
MANIFEST_PATH = f"/{GH_REPO}/releases/latest/download/update.json"
VARIANT = "win-x64-avx2"
THORON_VERSION = "0.1.1"

CASES = {
    "up to date": re.compile(r"up to date", re.I),
    "error": re.compile(r"could not update: the update manifest could not be fetched", re.I),
    "cannot verify": re.compile(r"cannot verify updates", re.I),
    "no package": re.compile(r"is out, but not yet for this kind of computer", re.I),
    "needs installer": re.compile(r"needs its own installer", re.I),
}
CHECKING = re.compile(r"checking", re.I)
UPDATING = re.compile(r"(\d{1,3})\s*%")
RELAUNCH = re.compile(r"relaunch", re.I)


def bump(version: str, by: int) -> str:
    parts = version.split(".")
    return ".".join(parts[:3] + [str(int(parts[3]) + by)])


# --- the server ----------------------------------------------------------------------------------------------

def certificate(folder: Path) -> tuple[Path, Path, str]:
    """A key and a self-signed certificate for github.com, made now; and its SPKI hash (base64 of SHA-256)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "github.com")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("github.com")]), critical=False)
            .sign(key, hashes.SHA256()))
    key_file, cert_file = folder / "server.key", folder / "server.crt"
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    spki = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return key_file, cert_file, base64.b64encode(hashlib.sha256(spki).digest()).decode()


class Server:
    """github.com on 127.0.0.1: the manifest and its signature of the case, and the packages by name."""

    def __init__(self, key_file: Path, cert_file: Path):
        self.files: dict[str, bytes | Path] = {}
        self.manifest_delay = 0.0
        self.package_rate = 0                     # bytes a second; 0 is as fast as it goes
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                name = self.path.rsplit("/", 1)[-1]
                body = outer.files.get(name) if self.path.startswith(f"/{GH_REPO}/releases/") else None
                if body is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if name == "update.json" and outer.manifest_delay:
                    time.sleep(outer.manifest_delay)
                size = body.stat().st_size if isinstance(body, Path) else len(body)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    if isinstance(body, Path):
                        with body.open("rb") as f:
                            for block in iter(lambda: f.read(1 << 20), b""):
                                self.wfile.write(block)
                                if outer.package_rate:
                                    time.sleep(len(block) / outer.package_rate)
                    else:
                        self.wfile.write(body)
                except (ConnectionError, OSError):
                    pass

        class Https(http.server.ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass

        self.httpd = Https(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_file, key_file)
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


# --- the manifests ---------------------------------------------------------------------------------------------

def signed(version: str, packages: dict, *, min_updater: str | None = None, key: bytes = TEST_KEY,
           thoron_version: str = THORON_VERSION) -> tuple[bytes, bytes]:
    """A manifest and its signature. `min_updater` is the oldest updater that may apply it (the version itself
    when not given: then an older copy needs its own installer)."""
    now = int(time.time())
    raw = mf.build(channel="stable", version=version, thoron_version=thoron_version, critical=False,
                   min_updater_version=min_updater or version, packages=packages, published=now - 60,
                   allowed_hosts=mf.DEFAULT_HOSTS)
    return raw, mf.sign(raw, key, mf.public_key_of(key), allowed_hosts=mf.DEFAULT_HOSTS, now=now)


def entry(path: Path, tag: str) -> dict:
    return mf.file_entry(path, f"https://github.com/{GH_REPO}/releases/download/{tag}/{path.name}")


def renamed_package(source: Path, version: str, newer: str, target: Path) -> Path:
    """The portable package of `source` with its version folder named `newer` (stored, not compressed)."""
    old, new = f"ThoronPortable/Application/{version}/", f"ThoronPortable/Application/{newer}/"
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as zout:
        for info in zin.infolist():
            data = zin.read(info)
            info.filename = new + info.filename[len(old):] if info.filename.startswith(old) else info.filename
            info.compress_type = zipfile.ZIP_STORED
            zout.writestr(info, data)
    return target


# --- one case -------------------------------------------------------------------------------------------------

def copy_portable(base: Path, folder: Path) -> Path:
    shutil.copytree(base, folder, ignore=shutil.ignore_patterns("User Data"))
    return folder


def browsers_in(folder: Path) -> list[int]:
    """The ids of the processes running a program inside `folder`."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like "
                          f"'{folder}\\*' }} | ForEach-Object {{ $_.ProcessId }}"],
                         capture_output=True, text=True).stdout
    return [int(x) for x in out.split() if x.isdigit()]


def close(devtools: int | None, folder: Path) -> None:
    if devtools is not None:
        try:
            import urllib.request
            version = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{devtools}/json/version", timeout=10).read())
            ws = WebSocket(version["webSocketDebuggerUrl"])
            try:
                ws.call("Browser.close")
            except (ConnectionError, OSError):
                pass
            finally:
                ws.close()
        except (OSError, ValueError, KeyError):
            pass
    end = time.monotonic() + 30
    while time.monotonic() < end and browsers_in(folder):
        time.sleep(0.5)
    for pid in browsers_in(folder):
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)


def watch(copy: Path, port: int, spki: str, seconds: float, done) -> list[tuple[float, str]]:
    """Start the copy, open the About page, and read its update line until `done(text)` or `seconds`."""
    args = [str(copy / "Thoron.exe"), "--headless=new", "--no-first-run", "--no-default-browser-check",
            "--disable-background-networking",
            f"--host-resolver-rules=MAP github.com 127.0.0.1:{port}, MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            f"--ignore-certificate-errors-spki-list={spki}", "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0", "about:blank"]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    seen: list[tuple[float, str]] = []
    devtools = None
    try:
        devtools = _devtools_port(copy / "User Data")
        ws = WebSocket(_open(devtools, "about:blank")["webSocketDebuggerUrl"])
        try:
            started = time.monotonic()
            ws.call("Page.navigate", url="chrome://settings/help")
            while time.monotonic() - started < seconds:
                status = json.loads(ws.call("Runtime.evaluate", expression=READ_STATUS, returnByValue=True)
                                    ["result"].get("value") or "{}")
                text = status.get("text", "") if status.get("shown") else ""
                if text and (not seen or seen[-1][1] != text):
                    seen.append((round(time.monotonic() - started, 1), text))
                if text and done(text):
                    break
                time.sleep(0.3)
        finally:
            ws.close()
    finally:
        close(devtools, copy)
    return seen


def run(chrome_bin: Path, launcher: Path, updater: Path, work: Path) -> list[str]:
    work.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="about-states-", dir=work))
    version = next(p.name for p in chrome_bin.iterdir() if p.is_dir() and re.fullmatch(r"\d+(\.\d+){3}", p.name))
    newer, newest = bump(version, 1), bump(version, 2)
    dist = root / "dist"
    made = subprocess.run([sys.executable, "-I", str(REPO / "tools/release/portable.py"), "build", "--chrome-bin",
                           str(chrome_bin), "--launcher", str(launcher), "--updater", str(updater), "--dist", str(dist),
                           "--variant", VARIANT], capture_output=True, text=True)
    if made.returncode:
        return [f"the portable package could not be made: {made.stdout[-300:]} {made.stderr[-300:]}"]
    base = dist / "ThoronPortable"
    package = next(dist.glob("*-portable.zip"))
    newer_package = renamed_package(package, version, newer, root / f"thoron-{newer}-{VARIANT}-portable.zip")
    key_file, cert_file, spki = certificate(root)
    problems: list[str] = []
    with Server(key_file, cert_file) as server:
        def case(name: str, manifest: tuple[bytes, bytes] | None, pattern, seconds: float = 40):
            server.files = {} if manifest is None else {"update.json": manifest[0], "update.json.sig": manifest[1]}
            copy = copy_portable(base, root / name.replace(" ", "-"))
            seen = watch(copy, server.port, spki, seconds, lambda text: bool(pattern.search(text)))
            print(f"{name}: {seen}")
            if not seen or not pattern.search(seen[-1][1]):
                problems.append(f"{name}: the line never said {pattern.pattern!r} (it said {seen})")
            problems.extend(f"{name}: the line names Chromium: {t!r}" for _, t in seen if "Chromium" in t)
            return copy, seen

        avx2 = {VARIANT: {"portable": {"full": entry(package, f"v{THORON_VERSION}")}}}
        case("up to date", signed(version, avx2), CASES["up to date"])
        case("error", None, CASES["error"])
        case("cannot verify", signed(version, avx2, key=OTHER_KEY), CASES["cannot verify"])
        sse4 = {"win-x64-sse4": {"portable": {"full": entry(newer_package, "v0.1.2")}}}
        case("no package", signed(newer, sse4, min_updater=version, thoron_version="0.1.2"), CASES["no package"])
        installer_only = {VARIANT: {"installed": {"full": entry(newer_package, "v0.1.3")}}}
        case("needs installer", signed(newest, installer_only, min_updater=newer, thoron_version="0.1.3"),
             CASES["needs installer"])
        # the update: the manifest after 3 s ("checking"), the package at about 40 MB a second ("updating")
        server.manifest_delay, server.package_rate = 3.0, 40 * 1024 * 1024
        newer_entry = {VARIANT: {"portable": {"full": entry(newer_package, "v0.1.2")}}}
        manifest = signed(newer, newer_entry, min_updater=version, thoron_version="0.1.2")
        server.files = {"update.json": manifest[0], "update.json.sig": manifest[1], newer_package.name: newer_package}
        copy = copy_portable(base, root / "update")
        seen = watch(copy, server.port, spki, 180, lambda text: bool(RELAUNCH.search(text)))
        print(f"update: {seen}")
        texts = [t for _, t in seen]
        percents = [int(m.group(1)) for t in texts for m in [UPDATING.search(t)] if m]
        if not any(CHECKING.search(t) for t in texts):
            problems.append(f"update: the line never said 'checking' ({texts})")
        if not percents or max(percents) == 0:
            problems.append(f"update: the line never showed the download's percentage ({texts})")
        if not texts or not RELAUNCH.search(texts[-1]):
            problems.append(f"update: the line never asked for a relaunch ({texts})")
        named = sorted({t for t in texts if "Chromium" in t})
        if named:
            problems.append(f"update: {len(named)} line(s) name Chromium, the first {named[0]!r}")
        # `current` names the version that starts, then the one before it (for going back)
        current = (copy / "Application" / "current").read_text(encoding="utf-8").split("\n")[0].strip() \
            if (copy / "Application" / "current").is_file() else ""
        if current != newer or not (copy / "Application" / newer).is_dir():
            problems.append(f"update: the copy's current version is {current!r}, not {newer}")
        print(f"update: percentages shown {percents}; the copy's current version: {current}")
    if not problems:
        shutil.rmtree(root, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--chrome-bin", type=Path, required=True, help="the test key build's Chrome-bin folder")
    p.add_argument("--launcher", type=Path, required=True)
    p.add_argument("--updater", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    a = p.parse_args(argv)
    if sys.platform != "win32":
        print("ABOUT UPDATER STATES CHECK: not on Windows, nothing to check")
        return 0
    problems = run(a.chrome_bin.resolve(), a.launcher.resolve(), a.updater.resolve(), a.work.resolve())
    for problem in problems:
        print(f"FAIL  {problem}")
    print(f"ABOUT UPDATER STATES CHECK: {'PASSED' if not problems else f'FAILED ({len(problems)} problem(s))'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
