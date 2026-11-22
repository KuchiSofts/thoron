#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron's signed APT repository with apt itself (ROADMAP P2.10). Run on Windows.

On a clean Ubuntu test machine of tools/qa/wsl_test_vm.py, as root, the release packages go into a flat repository
made by tools/release/apt_repo.py and signed with a throwaway key (the real one is the owner's, P2.11). A local
server answers as GitHub does: the release's download address redirects to a file host. With the key's keyring in
`Signed-By` and nothing else trusted:

    update      `apt-get update` reads the signed InRelease and lists thoron-browser (amd64, arm64) and
                thoron-browser-sse4
    install     `apt-get install thoron-browser-sse4` installs the SSE4.2 build from the repository
    upgrade     a newer version in the repository: `apt-get upgrade` brings the newer SSE4.2 build and never the
                AVX2 one (another package, which conflicts)
    tampered    a changed InRelease is refused (its signature is bad)
    other key   an index signed with another key is refused
    expired     an index past its Valid-Until is refused
    packages    a package list that is not the one InRelease names is refused (its hash)

    py -3 -I tools/qa/linux_apt_repo_check.py --deb avx2=<.deb> --deb sse4=<.deb> --deb arm64=<.deb>
        --root <test machines folder> --work <scratch> [--machine thoron-test-2604]
Exit status 0 only when every step passes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

if __package__ in (None, ""):  # running as a script: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO = Path(__file__).resolve().parents[2]
STEPS = ("update", "install", "upgrade", "tampered", "other key", "expired", "packages")
VARIANTS = {"avx2": "linux-x64-avx2", "sse4": "linux-x64-sse4", "arm64": "linux-arm64-armv8"}
PORT = 8098
BASE = f"http://127.0.0.1:{PORT}/KuchiSofts/thoron/releases/download/"

SCRIPT = r"""#!/bin/bash
# Other work may share this WSL machine: if memory runs out, the kernel ends this check's processes first.
echo 1000 > /proc/self/oom_score_adj 2>/dev/null
# As root inside a clean test machine: $1 work folder, $2 tools, $3.. the packages as variant=path
set -u
W="$1"; TOOLS="$2"; shift 2
out="$W/out"; rm -rf "$out"; mkdir -p "$out"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq > /dev/null 2>&1
apt-get install -y -qq gnupg gpgv > "$out/apt-tools.txt" 2>&1
python3 -I "$TOOLS/qa/linux_apt_repo_check.py" probe --tools "$TOOLS" --out "$out/probe.json" "$@" \
  > "$out/probe.txt" 2>&1
echo done > "$out/reached"
"""


# ----- inside the test machine -------------------------------------------------------------------------------

def _serve(root: Path, stop: threading.Event):
    """GitHub's way: /<owner>/<repo>/releases/download/apt/<file> answers 302 to /objects/<file>; a path with a
    "." or ".." part is refused, as a strict server would."""
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            prefix = "/KuchiSofts/thoron/releases/download/apt/"
            if "/./" in self.path or "/../" in self.path:
                self.send_response(400)
                self.end_headers()
                return
            if self.path.startswith(prefix):
                self.send_response(302)
                self.send_header("Location", "/objects/" + self.path[len(prefix):])
                self.end_headers()
                return
            path = root / self.path.removeprefix("/objects/")
            if not self.path.startswith("/objects/") or "/" in self.path[len("/objects/"):] or not path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _run(*cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, **kw)


def _key(home: Path, uid: str) -> str:
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    _run("gpg", "--homedir", str(home), "--batch", "--passphrase", "", "--quick-gen-key", uid, "ed25519", "sign",
         "1d")
    listed = _run("gpg", "--homedir", str(home), "--with-colons", "--list-keys").stdout
    return next(line.split(":")[9] for line in listed.splitlines() if line.startswith("fpr:"))


def _bumped(deb: Path, work: Path) -> Path:
    """The same package as a newer version (for the upgrade step)."""
    tree = work / "bump"
    shutil.rmtree(tree, ignore_errors=True)
    _run("dpkg-deb", "-R", str(deb), str(tree), check=True)
    control = tree / "DEBIAN" / "control"
    text = control.read_text()
    version = next(line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("Version:"))
    control.write_text(text.replace(f"Version: {version}", f"Version: {version}.1", 1))
    out = work / deb.name.replace(".deb", "-bumped.deb")
    _run("dpkg-deb", "-Zgzip", "-z1", "-b", str(tree), str(out), check=True)
    shutil.rmtree(tree, ignore_errors=True)
    return out


def probe(tools: Path, out: Path, debs: dict[str, Path]) -> int:
    sys.path.insert(0, str(tools.parent))
    from tools.release import apt_repo as ar
    work = Path("/var/tmp/apt-work")  # the machine's own disk: dpkg-deb refuses the Windows drive's permissions
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    found: dict = {step: [] for step in STEPS}
    notes: dict = {}
    serve_root = work / "serve"
    server = None
    try:
        home, other = work / "gnupg", work / "gnupg-other"
        key = _key(home, "Thoron APT test <apt-test@example.org>")
        other_key = _key(other, "Someone else <other@example.org>")
        pairs = [(debs[v], VARIANTS[v]) for v in ("avx2", "sse4", "arm64") if v in debs]

        def make(folder: Path, gnupg: Path, fpr: str, entries=pairs, **kw) -> Path:
            shutil.rmtree(folder, ignore_errors=True)
            ar.build(entries, folder, gnupg, fpr, **kw)
            return folder

        repos = {"good": make(work / "repo-good", home, key)}
        shutil.copytree(repos["good"], serve_root)
        server = _serve(serve_root, threading.Event())
        Path(ar.KEYRING_PATH).write_bytes((repos["good"] / ar.KEYRING).read_bytes())
        Path("/etc/apt/sources.list.d/thoron.sources").write_text(
            ar.sources_text("KuchiSofts/thoron").replace(
                "https://github.com/KuchiSofts/thoron/releases/download/", BASE))

        def update() -> subprocess.CompletedProcess:
            return _run("apt-get", "update", "-o", "Acquire::Retries=0")

        def serve(folder: Path) -> None:
            for f in serve_root.iterdir():
                f.unlink()
            for f in folder.iterdir():
                shutil.copy2(f, serve_root / f.name)

        # update
        done = update()
        policy = _run("apt-cache", "policy", "thoron-browser", "thoron-browser-sse4").stdout
        notes["update"] = policy.strip().replace("\n", " | ")[:300]
        if done.returncode != 0 or "W:" in done.stdout + done.stderr and "thoron" in (done.stdout + done.stderr):
            found["update"].append(f"apt-get update: {done.returncode} {(done.stdout + done.stderr)[-400:]}")
        if "thoron-browser-sse4:" not in policy or "Candidate: (none)" in policy:
            found["update"].append(f"the repository's packages are not listed: {policy[-300:]}")

        # install
        done = _run("apt-get", "install", "-y", "-q", "thoron-browser-sse4")
        status = _run("dpkg-query", "-W", "-f", "${Package} ${Version} ${Status}\\n", "thoron-browser-sse4",
                      "thoron-browser").stdout
        notes["install"] = status.strip().replace("\n", " | ")
        if done.returncode != 0 or "thoron-browser-sse4" not in status or "install ok installed" not in status:
            found["install"].append(f"not installed: {done.returncode} {(done.stdout + done.stderr)[-400:]}")

        # upgrade
        newer = [(_bumped(debs[v], work), VARIANTS[v]) for v in ("avx2", "sse4") if v in debs]
        serve(make(work / "repo-newer", home, key, entries=newer))
        update()
        done = _run("apt-get", "upgrade", "-y", "-q")
        status = _run("dpkg-query", "-W", "-f", "${Package} ${Version} ${db:Status-Abbrev}\\n",
                      "thoron-browser-sse4", "thoron-browser").stdout
        notes["upgrade"] = status.strip().replace("\n", " | ")
        lines = {line.split()[0]: line for line in status.splitlines() if line.strip()}
        if not lines.get("thoron-browser-sse4", "").split()[1:2] or \
                not lines["thoron-browser-sse4"].split()[1].endswith(".1") or "ii" not in lines["thoron-browser-sse4"]:
            found["upgrade"].append(f"the SSE4.2 build was not upgraded: {status} {done.stdout[-300:]}")
        if "ii" in lines.get("thoron-browser", ""):
            found["upgrade"].append("the AVX2 build came in on the upgrade")

        # tampered: one hash in InRelease changed
        good = work / "repo-newer"
        tampered = work / "repo-tampered"
        shutil.copytree(good, tampered)
        text = (tampered / "InRelease").read_text()
        digest = (tampered / "Packages").read_bytes()
        import hashlib
        h = hashlib.sha256(digest).hexdigest()
        (tampered / "InRelease").write_text(text.replace(h, h[:-1] + ("0" if h[-1] != "0" else "1"), 1))
        serve(tampered)
        done = update()
        notes["tampered"] = _first(done, ("BADSIG", "signatures were invalid", "not signed"))
        if done.returncode == 0 and "BADSIG" not in done.stdout + done.stderr:
            found["tampered"].append(f"a changed InRelease was taken: {(done.stdout + done.stderr)[-300:]}")

        # other key
        serve(make(work / "repo-other", other, other_key, entries=newer))
        done = update()
        notes["other key"] = _first(done, ("NO_PUBKEY", "not signed", "signatures couldn't be verified"))
        if done.returncode == 0 and "NO_PUBKEY" not in done.stdout + done.stderr:
            found["other key"].append(f"another key's index was taken: {(done.stdout + done.stderr)[-300:]}")

        # expired
        serve(make(work / "repo-expired", home, key, entries=newer, valid_days=1,
                   now=dt.datetime.now(dt.timezone.utc).replace(microsecond=0) - dt.timedelta(days=3)))
        done = update()
        notes["expired"] = _first(done, ("expired", "no longer valid", "Valid-Until"))
        text = done.stdout + done.stderr
        if not any(w in text for w in ("expired", "no longer valid", "Valid-Until")):
            found["expired"].append(f"an expired index was taken: {text[-300:]}")

        # packages: the list changed, InRelease as it was
        changed = work / "repo-packages"
        shutil.copytree(good, changed)
        (changed / "Packages").write_bytes((changed / "Packages").read_bytes().replace(b"Priority:", b"Priority: ", 1))
        (changed / "Packages.gz").unlink()
        serve(changed)
        _run("apt-get", "clean")
        shutil.rmtree("/var/lib/apt/lists", ignore_errors=True)
        Path("/var/lib/apt/lists/partial").mkdir(parents=True, exist_ok=True)
        done = update()
        notes["packages"] = _first(done, ("Hash Sum mismatch", "File has unexpected size", "mismatch"))
        if "mismatch" not in (done.stdout + done.stderr) and "unexpected size" not in (done.stdout + done.stderr):
            found["packages"].append(f"a changed package list was taken: {(done.stdout + done.stderr)[-300:]}")
    except Exception as exc:  # the reason goes into the results; the host reads it
        found.setdefault("error", []).append(f"{type(exc).__name__}: {exc}")
    finally:
        if server:
            server.shutdown()
    out.write_text(json.dumps({"problems": found, "notes": notes}), encoding="utf-8")
    return 0


def _first(done: subprocess.CompletedProcess, words) -> str:
    for line in (done.stdout + done.stderr).splitlines():
        if any(w in line for w in words):
            return line.strip()[:200]
    return f"exit {done.returncode}"


# ----- on Windows ----------------------------------------------------------------------------------------------

def run_machine(name: str, root: Path, work: Path, debs: dict[str, Path]) -> dict:
    from tools.qa import linux_package_check as lp
    from tools.qa import wsl_test_vm as vm
    vm.restore(root, name)
    folder = work / name
    if folder.exists():
        shutil.rmtree(folder, onexc=lambda func, path, _exc: (Path(path).chmod(0o700), func(path)))
    folder.mkdir(parents=True)
    (folder / "check.sh").write_bytes(SCRIPT.encode("utf-8"))
    tools = folder / "tools"
    shutil.copytree(REPO / "tools", tools, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    args = [f"--deb={v}={lp.wsl_path(p)}" for v, p in debs.items()]
    done = subprocess.run(["wsl.exe", "-d", vm.checked_name(name), "-u", "root", "--", "bash",
                           lp.wsl_path(folder / "check.sh"), lp.wsl_path(folder), lp.wsl_path(tools), *args],
                          capture_output=True, timeout=5400)
    (folder / "run-output.txt").write_bytes(done.stdout + done.stderr)
    try:
        return json.loads(lp.read(folder / "out", "probe.json") or "{}") or \
            {"problems": {"probe": [lp.read(folder / "out", "probe.txt")[-400:]]}}
    except ValueError:
        return {"problems": {"probe": ["the probe's results are not readable"]}}


def _deb_arg(text: str) -> tuple[str, Path]:
    variant, _, path = text.partition("=")
    if variant not in VARIANTS or not path:
        raise argparse.ArgumentTypeError("--deb is avx2=<path>, sse4=<path> or arm64=<path>")
    return variant, Path(path)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command")
    pr = sub.add_parser("probe", help="inside a test machine (used by the check itself)")
    pr.add_argument("--tools", type=Path, required=True)
    pr.add_argument("--out", type=Path, required=True)
    pr.add_argument("--deb", type=_deb_arg, action="append", required=True)
    p.add_argument("--deb", type=_deb_arg, action="append")
    p.add_argument("--root", type=Path)
    p.add_argument("--work", type=Path)
    p.add_argument("--machine", default="thoron-test-2604")
    a = p.parse_args(argv)
    if a.command == "probe":
        return probe(a.tools, a.out, dict(a.deb))
    if not (a.deb and a.root and a.work):
        p.error("--deb, --root and --work are needed")
    found = run_machine(a.machine, a.root, a.work.resolve(), {v: path.resolve() for v, path in a.deb})
    failed = 0
    notes = found.get("notes", {})
    for step, issues in found.get("problems", {}).items():
        print(f"{'PASS' if not issues else 'FAIL'}  {step}: {notes.get(step, '')[:150]}")
        for issue in issues:
            print(f"      {issue}")
        failed += len(issues)
    print(f"LINUX APT REPO CHECK: {'PASSED' if not failed else f'FAILED ({failed} problem(s))'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
