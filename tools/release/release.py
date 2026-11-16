#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Release script (ROADMAP P2.12, P3.2): checks, packages, signs and publishes one Thoron build as a draft.

    prepare  checks the build before anything is packaged and stops on any problem:
             the release args (tools/build/release_args.py check), the version (set by
             tools/release/version.py and higher than the previous release) and the installer
             contents (tools/release/package_audit.py); then copies the installer and BUILDINFO into
             the release folder with Thoron names, writes SHA256SUMS and the release notes, and signs
             SHA256SUMS with minisign when a key is given.
             It also stops, with nothing packaged, when:
               - Thoron's own version is not the next one after the newest release tag of --repo
                 (v0.1.1; with no tag yet the first is 0.1.1; fetch the tags first) (P2.24);
               - BUILDINFO does not name the source tag, the commit under it, a tree with nothing
                 uncommitted and the Chromium tag, or the build tree has no whole text of the GPL (L.2);
               - the build's browser folder (--chrome-bin, default Chrome-bin in the out dir) cannot be
                 made into the portable package (tools/release/portable.py) (P2.8);
               - CREDITS.md and NOTICE of --repo are not current: the list of upstream contributors is
                 made again (asked from GitHub with gh, read only, or read from --contributors) and must
                 be the one in CREDITS.md, every origin of the patch licence inventory must be credited
                 there and every licence of it named in NOTICE. Nothing is rewritten (L.3);
               - CHANGELOG.md of --repo is not in its short form or lists no change for the release (D.10);
               - the wiki pages in docs/wiki fail the docs linter or do not name the version (D.9).
             The release folder then also holds the portable .zip and the licence bundle
             (thoron-<version>-licenses.zip: LICENSE.md, NOTICE, CREDITS.md, the patch licence inventory
             and the GPL text of the build tree), both listed in SHA256SUMS.
             The notes take Thoron's changes from CHANGELOG.md: the section of the version when there is
             one, else what waits under [Unreleased]. They name the source tag, its commit and the
             Chromium tag, and say where the licence texts are.
             --security and --highlights put the security fixes (security.json, as changelog.py reads
             it) and a hand-written opening into the notes.
             --manifest-key makes the update manifest (docs/update/MANIFEST.md): update.json names the
             packages just written, with their sizes and SHA-256, at the addresses the draft will give
             them, and update.json.sig is its Ed25519 signature. Without the key no manifest is made,
             and prepare says so.
             --adblock-key signs the build's scriptlets and stand-ins of Thoron adblock
             (tools/release/adblock_resources.py) as thoron_adblock_resources.signed. Without the key
             this step is left out.
    publish  creates the GitHub release, always as a draft, and only when SHA256SUMS is signed, the folder
             holds exactly the files SHA256SUMS lists, the build record names the draft's tag as its
             source tag, the licence bundle holds the GPL text, and the update manifest verifies with the
             public key and names those files at the draft's addresses. The draft's tag is put on the
             commit the build record names. A person reviews and publishes it (design: releases stay
             drafts). The wiki is never published from here: publish prints the commands that do it.

A private key is read from the file named on the command line and from nowhere else. It is never written,
printed or copied, and a key file inside the repository, the build tree or the release folder is refused.
The update manifest and thoron_adblock_resources.signed are not in SHA256SUMS: each carries its own
signature, and a manifest is signed again, with new dates, while its release is the newest one.

    py -3 -I tools/release/release.py prepare --src <chromium src> --out <out dir> --platform win
        --variant win-x64-avx2 --previous <last release> --buildinfo BUILDINFO.json --dist <folder>
        --repo . --since <last release tag> --chromium-old <version> [--sevenzip 7za.exe]
        [--chrome-bin <browser folder>] [--contributors <saved list>]
        [--minisign-key <key file>] [--security security.json] [--highlights highlights.md]
        [--manifest-key <key file> --manifest-public-key <base64> --gh-repo KuchiSofts/thoron
         (--previous-manifest <last update.json> | --first-manifest --min-updater-version <build version>)
         [--critical] [--channel stable] [--manifest-days 30]]
        [--adblock-key <key file> --adblock-public-key <base64> --adblock-serial <YYYYMMDDNN>
         [--adblock-resources <json>]]
    py -3 -I tools/release/release.py publish --dist <folder> --version <version> --gh-repo KuchiSofts/thoron
        --manifest-public-key <base64>

The draft's tag is v<version>. A manifest gives its packages the addresses of the tag v<Thoron version>
(v0.1.2), so a release with a manifest is published with --version <Thoron version>.
"""
import argparse
import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.build import release_args  # noqa: E402
from tools.credits import contributors  # noqa: E402
from tools.docs import check_docs  # noqa: E402
from tools.legal import patch_licenses  # noqa: E402
from tools.legal import unlicensed_patches  # noqa: E402
from tools.qa import perf_gate  # noqa: E402
from tools.release import adblock_resources, changelog, package_audit, portable, version as ver  # noqa: E402
from tools.update import manifest as mf  # noqa: E402

_VARIANT = re.compile(r"^(win|linux)-(x64|arm64)-[a-z0-9]+$")
INSTALLERS = {"win": "mini_installer.exe"}
_GH_REPO = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_SUM_LINE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9._+~-]+)$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")

CHROME_BIN = "Chrome-bin"                               # in the out dir: what the installer's chrome.7z holds
# The GPL text in the build tree: the file the browser's chrome://credits page is made from.
GPL_TEXT = "third_party/thoron_notices/LICENSE.GPL-3.0"
GPL_MARKS = ("GNU GENERAL PUBLIC LICENSE", "Version 3, 29 June 2007", "END OF TERMS AND CONDITIONS")
GPL_NAME = "GPL-3.0.txt"                                # its name in the licence bundle
PATCH_INVENTORY = "docs/legal/PATCH_LICENSES.md"
# The licence bundle of a release: these files of the repository beside the GPL text, in one folder.
LICENCE_FILES = {"LICENSE.md": "LICENSE.md", "NOTICE": "NOTICE", "CREDITS.md": "CREDITS.md",
                 "PATCH_LICENSES.md": PATCH_INVENTORY}
LICENCE_FOLDER = "licenses"
UPSTREAM_REPO = "Alex313031/thorium"                    # whose contributors CREDITS.md lists
WIKI_VERSIONS = "Versions.md"                           # the wiki page that names the newest version

MANIFEST_HOSTS = ("github.com",)                        # the packages of a release are its GitHub assets
ADBLOCK_RESOURCES = "thoron_adblock_resources.json"     # as the build writes it into the out dir
ADBLOCK_BUNDLE = "thoron_adblock_resources.signed"      # as copies of Thoron ask for it
ADBLOCK_TAG = "adblock-resources"                       # the release whose asset the bundle is
REQUIRED = (("SHA256SUMS", "checksums"), ("SHA256SUMS.minisig", "signature"), ("NOTES.md", "notes"))
# Not files of the draft: the notes are its text, and the bundle goes to its own release, by hand.
NOT_UPLOADED = ("NOTES.md", ADBLOCK_BUNDLE)
# What a release folder holds besides the files SHA256SUMS lists.
UNLISTED = ("SHA256SUMS", "SHA256SUMS.minisig", "NOTES.md", mf.MANIFEST_NAME, mf.SIGNATURE_NAME, ADBLOCK_BUNDLE)


class ReleaseError(Exception):
    pass


def read_version(src: Path) -> tuple[str, bool]:
    values = dict(l.split("=", 1) for l in (src / "chrome" / "VERSION").read_text(encoding="utf-8").splitlines()
                  if "=" in l)
    v = ".".join(values[k].strip() for k in ("MAJOR", "MINOR", "BUILD", "PATCH"))
    return v, "THORON_REBUILD" in values


def read_thoron_version(src: Path) -> str | None:
    """Thoron's own version (three numbers) from chrome/VERSION; None while it is not set."""
    for line in (src / "chrome" / "VERSION").read_text(encoding="utf-8").splitlines():
        if line.startswith("THORON_VERSION="):
            return line.split("=", 1)[1].strip()
    return None


def preflight(src: Path, out: Path, platform: str, previous: str, lister) -> tuple[str, list[str]]:
    problems = [f"release args: {p}" for p in release_args.check((out / "args.gn").read_text(encoding="utf-8"),
                                                                   platform)]
    version, converted = read_version(src)
    if not converted:
        problems.append("chrome/VERSION is not a Thoron version: run tools/release/version.py set first")
    problems += [f"version: {p}" for p in ver.check_new(version, previous)]
    if platform == "win":
        archive = out / "chrome.7z"
        if not archive.is_file():
            problems.append(f"missing {archive.name}")
        else:
            problems += [f"package: {p}" for p in package_audit.audit(lister(archive), platform)]
    return version, problems


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def installer_name(version: str, variant: str) -> str:
    return f"thoron-{version}-{variant}-installer.exe"


def portable_name(version: str, variant: str) -> str:
    return f"thoron-{version}-{variant}-portable.zip"       # as tools/release/portable.py names it


def licence_bundle_name(version: str) -> str:
    return f"thoron-{version}-licenses.zip"


# --- Thoron's own version (ROADMAP P2.24) ------------------------------------------------------------------

def thoron_version_problems(thoron: str | None, tags: list[str]) -> list[str]:
    """Why the build may not be released under its Thoron version: it has none, or it is not the next one
    after the newest release among `tags` (the tags of the repository; with none, the first is 0.1.1)."""
    if not thoron:
        return ["chrome/VERSION has no THORON_VERSION: run tools/release/version.py thoron first"]
    return ver.check_next_thoron(thoron, ver.latest_thoron(tags))


# --- the source and the licences (ROADMAP L.2) -------------------------------------------------------------

def read_buildinfo(path: Path) -> dict:
    """The build record, as tools/build/buildinfo.py writes it."""
    try:
        info = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise ReleaseError(f"{path.name} is not JSON: {exc}") from None
    if not isinstance(info, dict):
        raise ReleaseError(f"{path.name} is not a build record")
    return info


def source_problems(info: dict, thoron: str | None, chromium: str | None) -> list[str]:
    """Why a build record does not name the source of the build. The GPL asks for the exact source of what
    is handed out: the tag of this repository the build is released under, on a commit that holds all it
    was built from, and Chromium's tag. `thoron` and `chromium` are what the build tree says, when known."""
    out = []
    tag, chromium_tag, commit = (info.get(key) for key in ("source_tag", "chromium_tag", "thoron_commit"))
    if not isinstance(tag, str) or not tag:
        out.append("no source tag (source_tag): set Thoron's version and write the record again with "
                   "tools/build/buildinfo.py")
    elif thoron and tag != release_tag(thoron):
        out.append(f"the source tag is {tag}, and the build is Thoron {thoron} ({release_tag(thoron)})")
    if not isinstance(chromium_tag, str) or not chromium_tag:
        out.append("no Chromium tag (chromium_tag)")
    elif chromium and chromium_tag != chromium:
        out.append(f"the Chromium tag is {chromium_tag}, and the build is made of Chromium {chromium}")
    if not isinstance(commit, str) or not _COMMIT.match(commit):
        out.append("no commit (thoron_commit) for the source tag to stand on")
    if info.get("thoron_dirty") is not False:
        out.append("the build was not made from a tree with nothing uncommitted (thoron_dirty): the source tag "
                   "would not hold what was built")
    return out


def gpl_problems(text: str) -> list[str]:
    """Why a text is not the whole GNU General Public License version 3."""
    missing = [mark for mark in GPL_MARKS if mark not in text]
    return [f"not the whole GNU GPL version 3: it lacks {', '.join(repr(m) for m in missing)}"] if missing else []


def licence_texts(repo: Path, src: Path) -> tuple[dict[str, bytes], list[str]]:
    """What the licence bundle of a release holds, by the names inside it, and why it cannot be made.
    The GPL text is the build tree's own, the one the browser shows at chrome://credits, so the bundle
    and the packages carry the same text. Line ends are those of the repository, not of the checkout."""
    texts, problems = {}, []
    gpl = src / GPL_TEXT
    if gpl.is_file():
        texts[GPL_NAME] = gpl.read_bytes()
        problems += [f"{GPL_TEXT} is {p}" for p in gpl_problems(texts[GPL_NAME].decode("utf-8", "replace"))]
    else:
        problems.append(f"the build tree has no {GPL_TEXT}: the browser and the release would go out without "
                        "the text of the GPL")
    for name, rel in LICENCE_FILES.items():
        if (repo / rel).is_file():
            texts[name] = (repo / rel).read_bytes()
        else:
            problems.append(f"{rel} is not in the repository; the licence bundle holds it")
    return {name: data.replace(b"\r\n", b"\n") for name, data in texts.items()}, problems


def write_licence_bundle(path: Path, texts: dict[str, bytes]) -> Path:
    """The licence bundle as a .zip that must not exist yet. The same texts give the same bytes, as for
    the portable package: sorted names, one fixed time, no host details."""
    stamp = time.gmtime(portable.EPOCH)[:6]
    with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(texts):
            info = zipfile.ZipInfo(f"{LICENCE_FOLDER}/{name}", date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0x20
            z.writestr(info, texts[name])
    return path


def licence_bundle_problems(dist: Path) -> list[str]:
    """Why a release folder does not carry the text of the GPL in a licence bundle."""
    bundles = sorted(dist.glob(licence_bundle_name("*")))
    if not bundles:
        return [f"no licence bundle ({licence_bundle_name('<version>')}) in the folder; prepare writes it"]
    out = []
    for path in bundles:
        try:
            with zipfile.ZipFile(path) as z:
                text = z.read(f"{LICENCE_FOLDER}/{GPL_NAME}").decode("utf-8", "replace")
        except (KeyError, zipfile.BadZipFile, OSError):
            out.append(f"{path.name} holds no {LICENCE_FOLDER}/{GPL_NAME}")
            continue
        out += [f"{GPL_NAME} in {path.name} is {p}" for p in gpl_problems(text)]
    return out


def source_tag_problems(dist: Path, tag: str) -> list[str]:
    """Why the draft's tag would not be the source tag of what a release folder holds."""
    records = sorted(dist.glob("BUILDINFO-*.json"))
    if not records:
        return ["no build record (BUILDINFO-*.json) in the folder names the source of the release"]
    out, commits = [], set()
    for path in records:
        try:
            info = read_buildinfo(path)
        except (ReleaseError, OSError) as exc:
            out.append(str(exc))
            continue
        if info.get("source_tag") != tag:
            out.append(f"{path.name} names the source tag {info.get('source_tag')}, and the draft would be "
                       f"tagged {tag}")
        commit = info.get("thoron_commit")
        if isinstance(commit, str) and _COMMIT.match(commit):
            commits.add(commit)
        else:
            out.append(f"{path.name} names no commit (thoron_commit) for the tag to stand on")
    if len(commits) > 1:
        out.append("the build records name different commits; one tag cannot be the source of them all")
    return out


def release_commit(dist: Path) -> str:
    """The commit the draft's tag is put on: the one the build records of the folder name."""
    commits = {read_buildinfo(path).get("thoron_commit") for path in sorted(dist.glob("BUILDINFO-*.json"))}
    commit = commits.pop() if len(commits) == 1 else None
    if not isinstance(commit, str) or not _COMMIT.match(commit):
        raise ReleaseError(f"the build record in {dist} names no one commit for the tag to stand on; nothing is "
                           "published without it")
    return commit


# --- the portable package (ROADMAP P2.8) -------------------------------------------------------------------

def portable_problems(chrome_bin: Path, version: str) -> list[str]:
    """Why the build's browser folder cannot become the portable package of this release, as
    tools/release/portable.py judges it; empty when it can. Found before anything is packaged."""
    if not chrome_bin.is_dir():
        return [f"the browser folder {chrome_bin.name} is not there (--chrome-bin names it)"]
    try:
        names = portable.files(chrome_bin)
        out = portable.source_problems(names)
        if not out and portable.browser_version(names) != version:
            out.append(f"the browser folder holds version {portable.browser_version(names)}, and the build is "
                       f"{version}")
    except portable.PortableError as exc:
        return [str(exc)]
    return out


def add_portable(chrome_bin: Path, dist: Path, version: str, variant: str) -> Path:
    """The portable .zip of the release, made by tools/release/portable.py in the release folder. The
    folder it is zipped from, which that call has just made, is taken away again: a release folder holds
    files only."""
    try:
        made = portable.build(chrome_bin, dist, variant)
    except portable.PortableError as exc:
        raise ReleaseError(f"portable package: {exc}") from None
    shutil.rmtree(made["package"])
    if made["zip"].name != portable_name(version, variant):
        raise ReleaseError(f"portable package: {made['zip'].name} is not the package of build {version}")
    return made["zip"]


# --- credits (ROADMAP L.3) ---------------------------------------------------------------------------------

def read_contributors(path: Path) -> list[dict]:
    """A saved list of upstream's contributors, as GitHub gives it (contributors.py --from-json)."""
    try:
        people = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise ReleaseError(f"{path.name} is not JSON: {exc}") from None
    if not isinstance(people, list) or not people or not all(isinstance(p, dict) for p in people):
        raise ReleaseError(f"{path.name} is not a list of contributors")
    return people


def upstream_contributors(saved: Path | None) -> list[dict]:
    """The contributors of upstream Thorium as GitHub lists them: from a saved list, or asked now with gh.
    Asking only reads; nothing is written there."""
    if saved is not None:
        return read_contributors(saved)
    try:
        return contributors.fetch(UPSTREAM_REPO)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise ReleaseError(f"the contributors of {UPSTREAM_REPO} could not be read from GitHub with gh "
                           f"({type(exc).__name__}); --contributors takes a saved list instead") from None


def _repo_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.is_file() else None


def credits_problems(repo: Path, people: list[dict]) -> list[str]:
    """Why CREDITS.md and NOTICE of the tree are not current; nothing is rewritten here. The list of
    upstream's contributors is made again from `people` and must be the one in CREDITS.md. Every origin the
    patch licence inventory names must be credited in CREDITS.md, and every licence it lists named in NOTICE."""
    credits_md, notice, inventory = (_repo_text(repo / name) for name in ("CREDITS.md", "NOTICE", PATCH_INVENTORY))
    out = [f"{name} is not in the repository" for name, text in
           (("CREDITS.md", credits_md), ("NOTICE", notice), (PATCH_INVENTORY, inventory)) if text is None]
    rows = patch_licenses.read_table(inventory or "")
    if inventory is not None and not rows:
        out.append(f"{PATCH_INVENTORY} lists no patch")
    if credits_md is not None:
        try:
            if contributors.replace_section(credits_md, contributors.render_contributors(people)) != credits_md:
                out.append("CREDITS.md: the list of upstream contributors is out of date: run "
                           "tools/credits/contributors.py and commit the result")
        except ValueError as exc:
            out.append(f"CREDITS.md: {exc}")
        origins = sorted({name for row in rows for name in patch_licenses.origin_names(row["origin"])})
        out += [f"CREDITS.md does not credit {name}, an origin in {PATCH_INVENTORY}"
                for name in origins if name.lower() not in credits_md.lower()]
    if notice is not None:
        licences = sorted({part.strip() for row in rows for part in row["license"].split(" AND ")})
        out += [f"NOTICE does not name the licence {licence}, which {PATCH_INVENTORY} lists"
                for licence in licences if licence not in notice]
    return out


def licence_record_problems(repo: Path) -> list[str]:
    """Why the patch licence records forbid a release (ROADMAP L.1): they disagree, or a patch whose author
    publishes no licence is still in the series."""
    try:
        _, found = unlicensed_patches.check(repo, release=True)
    except (OSError, ValueError, KeyError) as exc:
        return [f"the licence records could not be read ({type(exc).__name__})"]
    return found


PERF_BASELINE = "docs/perf/baseline.json"


def performance_problems(repo: Path, bench: Path | None, thoron: str) -> list[str]:
    """Why the release's benchmark forbids it (ROADMAP Q.3): it is missing, or a measure regressed against
    the baseline and docs/perf/EXPLAINED.md does not explain it for this version."""
    if bench is None:
        return ["no benchmark of this build: run tools/qa/bench.py on it and give --bench"]
    try:
        baseline = json.loads((repo / PERF_BASELINE).read_text(encoding="utf-8"))
        results = json.loads(bench.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"the benchmark or {PERF_BASELINE} could not be read ({type(exc).__name__})"]
    explained = _repo_text(repo / perf_gate.EXPLAINED) or ""
    return perf_gate.problems(baseline, results, thoron, explained)


# --- the wiki (ROADMAP D.9) --------------------------------------------------------------------------------

def wiki_problems(repo: Path, thoron: str | None) -> list[str]:
    """Why the wiki pages of the tree may not go out with this release: they fail the docs linter (links
    between pages, long dashes, private data), or the page about versions does not name the version being
    released. Publishing them stays a step a person takes; `publish` prints its command."""
    folder = repo / check_docs.WIKI_DIR
    if not folder.is_dir():
        return [f"{check_docs.WIKI_DIR} is not in the repository"]
    pages = sorted(p for p in folder.glob("*.md") if p.is_file())
    out = (check_docs.check_wiki(repo) + check_docs.check_dashes(repo, pages)
           + check_docs.check_private(repo, pages, check_docs.private_strings_file()))
    versions = folder / WIKI_VERSIONS
    named = thoron and versions.is_file() and re.search(rf"(?<![\d.]){re.escape(thoron)}(?!\.?\d)",
                                                         versions.read_text(encoding="utf-8"))
    if thoron and not named:
        out.append(f"{check_docs.WIKI_DIR}/{WIKI_VERSIONS} does not name Thoron {thoron}: the wiki is updated "
                   "with every release")
    return out


def wiki_commands(gh_repo: str) -> list[str]:
    """The commands that publish the wiki, the one that only looks first. They are printed, never run."""
    tool = f"py -3 -I tools/docs/publish_wiki.py --repo {gh_repo}"
    return [f"{tool} --dry-run", tool]


def assemble(out: Path, dist: Path, version: str, variant: str, buildinfo: Path, chrome_bin: Path | None = None,
             licences: dict[str, bytes] | None = None) -> list[Path]:
    """Fills the release folder. With `chrome_bin` the portable package of a Windows build is made beside
    the installer, and with `licences` the licence bundle; SHA256SUMS lists every file."""
    if not _VARIANT.match(variant):
        raise ReleaseError(f"variant must look like win-x64-avx2, got {variant!r}")
    if dist.exists() and any(dist.iterdir()):
        raise ReleaseError(f"{dist} is not empty; a release folder is never overwritten")
    dist.mkdir(parents=True, exist_ok=True)
    platform = variant.split("-")[0]
    files = []
    installer = INSTALLERS.get(platform)
    if installer:
        target = dist / installer_name(version, variant)
        shutil.copy2(out / installer, target)
        files.append(target)
    if chrome_bin is not None and platform == "win":
        files.append(add_portable(chrome_bin, dist, version, variant))
    info = dist / f"BUILDINFO-{version}-{variant}.json"
    shutil.copy2(buildinfo, info)
    files.append(info)
    if licences is not None:
        files.append(write_licence_bundle(dist / licence_bundle_name(version), licences))
    sums = dist / "SHA256SUMS"
    sums.write_text("".join(f"{_sha256(p)}  {p.name}\n" for p in sorted(files)), encoding="utf-8", newline="\n")
    return files + [sums]


def sign(dist: Path, key: Path, run=subprocess.run) -> Path:
    sig = dist / "SHA256SUMS.minisig"
    run(["minisign", "-S", "-s", str(key), "-m", str(dist / "SHA256SUMS"), "-x", str(sig)], check=True)
    return sig


# --- the notes -------------------------------------------------------------------------------------------

def read_highlights(path: Path) -> str:
    """The hand-written opening of the notes; a file with nothing in it is a mistake, not an opening."""
    text = path.read_text(encoding="utf-8-sig").strip()        # a byte order mark is not content
    if not text:
        raise ReleaseError(f"{path.name} is empty: leave --highlights out when there is nothing to say")
    return text


# --- keys ------------------------------------------------------------------------------------------------

def read_signing_key(path: Path, option: str, keep_out_of) -> bytes:
    """A private key from the file named on the command line: 32 bytes in base64, as the key ceremony
    writes it. A file inside one of the folders of `keep_out_of` (the repository, the build tree, the
    release folder) is refused unread: from there a key is one command away from being committed, packaged
    or uploaded."""
    where = path.resolve()
    for folder in keep_out_of:
        if where.is_relative_to(folder.resolve()):
            raise ReleaseError(f"{option}: the key file is inside {folder}; a key is kept outside the "
                               "repository, the build tree and the release folder")
    try:
        return mf.read_private_key(path)
    except ValueError as exc:
        raise ReleaseError(f"{option}: {exc}") from None


def public_key_from(text: str, option: str) -> bytes:
    """A public key as given on the command line: 32 bytes in base64 that are a usable key."""
    try:
        key = base64.b64decode(text, validate=True)
    except ValueError:
        raise ReleaseError(f"{option} is not base64") from None
    if not mf.usable_key(key):
        raise ReleaseError(f"{option} is {mf.KEY_BYTES} bytes in base64, not all zero and not of small order")
    return key


# --- the update manifest (ROADMAP P3.2) --------------------------------------------------------------------

def release_tag(version: str) -> str:
    return f"v{version}"


def download_url(gh_repo: str, tag: str, name: str) -> str:
    """Where GitHub serves the asset `name` of the release tagged `tag`."""
    return f"https://github.com/{gh_repo}/releases/download/{tag}/{name}"


@dataclass(frozen=True)
class ManifestPlan:
    """What the update manifest of a release says besides its packages. No key is kept here."""
    channel: str
    thoron_version: str
    critical: bool
    min_updater_version: str
    previous: dict | None       # the content of the manifest this one replaces on the channel
    gh_repo: str
    published: int              # the clock, in seconds since 1970
    valid_days: int

    @property
    def tag(self) -> str:
        return release_tag(self.thoron_version)


def _read_at_most(path: Path, limit: int) -> bytes:
    with path.open("rb") as f:
        return f.read(limit)


def manifest_plan(src: Path, *, channel: str, critical: bool, min_updater_version: str | None,
                  previous_manifest: Path | None, gh_repo: str, published: int, valid_days: int) -> ManifestPlan:
    """The plan of a release's manifest, from the build tree and the manifest before it. The oldest
    updater allowed is kept from the manifest before; only --min-updater-version changes it."""
    thoron = read_thoron_version(src)
    if not thoron:
        raise ReleaseError("chrome/VERSION has no THORON_VERSION, which the update manifest names: run "
                           "tools/release/version.py thoron first")
    if not _GH_REPO.match(gh_repo):
        raise ReleaseError(f"--gh-repo must look like KuchiSofts/thoron, got {gh_repo!r}")
    previous = None
    if previous_manifest is not None:
        try:
            previous = mf.parse(_read_at_most(previous_manifest, mf.MAX_MANIFEST_BYTES + 1),
                                allowed_hosts=MANIFEST_HOSTS)
        except mf.ManifestError as exc:
            raise ReleaseError(f"--previous-manifest is not a manifest: {exc}") from None
    if min_updater_version is None:
        if previous is None:
            raise ReleaseError("the first manifest of a channel needs --min-updater-version: the build version "
                               "of the oldest updater that may apply this release")
        min_updater_version = previous["min_updater_version"]
    return ManifestPlan(channel, thoron, critical, min_updater_version, previous, gh_repo, published, valid_days)


def package_names(version: str, variant: str) -> dict[str, str]:
    """The packages a release of `variant` is made of, by the kind of package a manifest knows."""
    return {"installed": installer_name(version, variant), "portable": portable_name(version, variant)}


def package_files(dist: Path, version: str, variant: str) -> dict[str, Path]:
    """The packages of the release folder an update can be made of, by kind of package."""
    return {kind: dist / name for kind, name in package_names(version, variant).items() if (dist / name).is_file()}


def manifest_packages(dist: Path, version: str, variant: str, gh_repo: str, tag: str) -> dict:
    """The `packages` of a manifest: the size and SHA-256 of each package as it lies in the release
    folder, and the address the draft will serve it from."""
    kinds = {kind: {"full": mf.file_entry(path, download_url(gh_repo, tag, path.name))}
             for kind, path in package_files(dist, version, variant).items()}
    return {variant: kinds} if kinds else {}


def build_manifest(plan: ManifestPlan, version: str, packages: dict) -> bytes:
    return mf.build(channel=plan.channel, version=version, thoron_version=plan.thoron_version,
                    critical=plan.critical, min_updater_version=plan.min_updater_version, packages=packages,
                    published=plan.published, allowed_hosts=MANIFEST_HOSTS, valid_days=plan.valid_days,
                    previous=plan.previous)


def manifest_problems(plan: ManifestPlan, version: str, variant: str, private_key: bytes,
                      public_key: bytes) -> list[str]:
    """Why no manifest could be signed for this release. Found before anything is packaged: the manifest
    is built once with a stand-in for each package, so that only the packages themselves are still missing."""
    out = []
    if mf.public_key_of(private_key) != public_key:
        out.append("--manifest-key does not belong to the public key that copies of Thoron hold "
                   "(--manifest-public-key)")
    if variant not in mf.VARIANTS:
        return out + [f"{variant} is not a variant a manifest can name (known: {', '.join(mf.VARIANTS)})"]
    if variant.split("-")[0] not in INSTALLERS:
        return out + [f"no package is made for {variant} yet, so a manifest has nothing to name"]
    stand_ins = {kind: {"full": {"url": download_url(plan.gh_repo, plan.tag, name), "size": 1, "sha256": "0" * 64}}
                 for kind, name in package_names(version, variant).items()}
    try:
        build_manifest(plan, version, {variant: stand_ins})
    except mf.ManifestError as exc:
        out += exc.problems
    return out


def _write_new(path: Path, content: bytes) -> Path:
    """A file that must not exist yet, byte for byte."""
    with path.open("xb") as f:
        f.write(content)
    return path


def write_manifest(dist: Path, plan: ManifestPlan, version: str, variant: str, private_key: bytes,
                   public_key: bytes, now: int) -> list[Path]:
    """Builds the manifest from the packages in the release folder, signs it and writes update.json and
    update.json.sig. The signature is made, and verified, before either file is written; what was written
    is read back and verified with the public key. A manifest never stays in the folder without a
    signature that holds: when anything fails, what this call wrote is taken away again."""
    packages = manifest_packages(dist, version, variant, plan.gh_repo, plan.tag)
    if not packages:
        raise ReleaseError(f"no package of {variant} in {dist}; a manifest has nothing to name")
    raw = build_manifest(plan, version, packages)
    signature = mf.sign(raw, private_key, public_key, allowed_hosts=MANIFEST_HOSTS, now=now)
    written = []
    try:
        written.append(_write_new(dist / mf.MANIFEST_NAME, raw))
        written.append(_write_new(dist / mf.SIGNATURE_NAME, signature))
        mf.verify(written[0].read_bytes(), written[1].read_bytes(), public_key, allowed_hosts=MANIFEST_HOSTS)
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return written


def manifest_entries(data: dict):
    """Every file a manifest names, with where it stands in the manifest."""
    for variant, kinds in data["packages"].items():
        for kind, package in kinds.items():
            yield f"{variant}/{kind}/full", package["full"]
            for base, entry in package.get("deltas", {}).items():
                yield f"{variant}/{kind}/deltas/{base}", entry


def manifest_file_problems(data: dict, dist: Path, gh_repo: str, tag: str) -> list[str]:
    """Why a verified manifest does not describe the files of this folder as the draft will serve them."""
    out, base = [], download_url(gh_repo, tag, "")
    for where, entry in manifest_entries(data):
        name = entry["url"][len(base):] if entry["url"].startswith(base) else ""
        if not name or "/" in name:
            out.append(f"{where} is at {entry['url']}, which is no file of release {tag} of {gh_repo}")
        elif not (dist / name).is_file():
            out.append(f"{where} names {name}, which is not in the folder")
        elif mf.file_entry(dist / name, entry["url"]) != entry:
            out.append(f"{where}: the size and SHA-256 are not those of {name} in the folder")
    return out


def signed_manifest_problems(dist: Path, gh_repo: str, tag: str, public_key: bytes, now: int) -> list[str]:
    """Why the manifest of a release folder may not be published: it is missing, unsigned, does not verify
    with the public key, would be refused by a copy of Thoron today, or names other files than the
    folder's."""
    manifest, signature = dist / mf.MANIFEST_NAME, dist / mf.SIGNATURE_NAME
    if not manifest.is_file():
        return [f"there is none ({manifest.name}); prepare makes it when it is given --manifest-key"]
    if not signature.is_file():
        return [f"{manifest.name} is not signed (no {signature.name})"]
    try:
        data = mf.verify(_read_at_most(manifest, mf.MAX_MANIFEST_BYTES + 1),
                         _read_at_most(signature, mf.SIGNATURE_BYTES + 1), public_key, allowed_hosts=MANIFEST_HOSTS)
    except mf.SignatureError:
        return [f"the signature does not hold with the public key given: {manifest.name} or {signature.name} "
                "was changed after signing, or another key signed it"]
    except mf.ManifestError as exc:
        return exc.problems
    stale = mf.freshness(data, channel=data["channel"], last_serial=0, now=now)
    return ([stale[1]] if stale else []) + manifest_file_problems(data, dist, gh_repo, tag)


# --- Thoron adblock's scriptlets and stand-ins (ROADMAP P5.23) ---------------------------------------------

def sign_adblock_bundle(resources: str, serial: str, private_key: bytes, public_key: bytes) -> str:
    """The signed copy of Thoron adblock's scriptlets and stand-ins, as copies of Thoron take it in
    between releases. Nothing is handed out that does not verify with the key those copies hold."""
    if mf.public_key_of(private_key) != public_key:
        raise ReleaseError("--adblock-key does not belong to the public key that copies of Thoron hold "
                           "(--adblock-public-key)")
    try:
        text = adblock_resources.sign(resources, serial, private_key)
    except ValueError as exc:
        raise ReleaseError(f"Thoron adblock's resources: {exc}") from None
    if adblock_resources.verify(text, public_key) != serial:
        raise ReleaseError("Thoron adblock's signed resources do not verify; nothing is written")
    return text


# --- publishing ------------------------------------------------------------------------------------------

def checksum_problems(dist: Path) -> list[str]:
    """Why the folder is not what SHA256SUMS lists: a file that is missing, changed, or was put there
    later. Every file of the folder is uploaded, so nothing else belongs in it."""
    out, listed = [], {}
    for line in (dist / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        m = _SUM_LINE.match(line)
        if m:
            listed[m.group(2)] = m.group(1)
        else:
            out.append("SHA256SUMS has a line that is not `<sha256>  <file name>`")
    for name, digest in listed.items():
        if not (dist / name).is_file():
            out.append(f"{name} is in SHA256SUMS and not in the folder")
        elif _sha256(dist / name) != digest:
            out.append(f"{name} does not have the SHA-256 that SHA256SUMS lists")
    for path in sorted(dist.iterdir()):
        if path.is_dir():
            out.append(f"{path.name} is a folder; a release folder holds files only")
        elif path.name not in listed and path.name not in UNLISTED:
            out.append(f"{path.name} is not in SHA256SUMS; only what prepare wrote belongs in the folder")
    return out


def publish_problems(dist: Path, version: str, gh_repo: str, public_key: bytes, now: int) -> list[str]:
    """Every reason the release folder may not become a draft; empty when it may. This is all `publish`
    checks before it asks GitHub for anything, and none of it leaves this computer."""
    out = [f"no {why} ({need}) in {dist}; nothing is published without it"
           for need, why in REQUIRED if not (dist / need).is_file()]
    if (dist / "SHA256SUMS").is_file():
        out += checksum_problems(dist)
    out += [f"source: {p}" for p in source_tag_problems(dist, release_tag(version))]
    out += [f"licences: {p}" for p in licence_bundle_problems(dist)]
    return out + [f"update manifest: {p}"
                  for p in signed_manifest_problems(dist, gh_repo, release_tag(version), public_key, now)]


def publish(dist: Path, version: str, gh_repo: str, run=None) -> None:
    """Creates the draft from a release folder. The `publish` command runs publish_problems() first.
    The tag a person makes by publishing the draft is put on the commit the build was made from, so that
    the source tag the build record names is the source of what is handed out."""
    for need, why in REQUIRED:
        if not (dist / need).is_file():
            raise ReleaseError(f"no {why} ({need}) in {dist}; nothing is published without it")
    files = [str(p) for p in sorted(dist.iterdir()) if p.name not in NOT_UPLOADED]
    cmd = ["gh", "release", "create", release_tag(version), "--draft", "--repo", gh_repo,
           "--target", release_commit(dist),
           "--title", f"Thoron {version}", "--notes-file", str(dist / "NOTES.md"), *files]
    if run is None:
        subprocess.run(cmd, check=True)
    else:
        run(cmd)


# --- command line ----------------------------------------------------------------------------------------

def check_prepare_options(a) -> None:
    """The options of one step are given together, and none is given that would be ignored."""
    manifest = {"--manifest-public-key": a.manifest_public_key, "--gh-repo": a.gh_repo,
                "--previous-manifest": a.previous_manifest, "--first-manifest": a.first_manifest or None,
                "--min-updater-version": a.min_updater_version, "--critical": a.critical or None,
                "--channel": a.channel, "--manifest-days": a.manifest_days}
    adblock = {"--adblock-public-key": a.adblock_public_key, "--adblock-serial": a.adblock_serial,
               "--adblock-resources": a.adblock_resources}
    for key, key_option, options, needed in (
            (a.manifest_key, "--manifest-key", manifest, ("--manifest-public-key", "--gh-repo")),
            (a.adblock_key, "--adblock-key", adblock, ("--adblock-public-key", "--adblock-serial"))):
        given = [name for name, value in options.items() if value is not None]
        if key is None and given:
            raise ReleaseError(f"{', '.join(given)}: only with {key_option}")
        missing = [name for name in needed if options[name] is None]
        if key is not None and missing:
            raise ReleaseError(f"{key_option} needs {', '.join(missing)}")
    if a.manifest_key is not None and a.previous_manifest is None and not a.first_manifest:
        raise ReleaseError("--manifest-key needs --previous-manifest <the last update.json>, or --first-manifest "
                           "when the channel has no manifest yet")


def _prepare(a) -> int:
    check_prepare_options(a)
    now = int(time.time())
    keep_out_of = (a.repo, a.src, a.out, a.dist)
    security = changelog.read_security(a.security) if a.security else None
    highlights = read_highlights(a.highlights) if a.highlights else None
    info = read_buildinfo(a.buildinfo)
    bundle = None
    if a.adblock_key:       # signed in memory before anything is packaged; written with the rest
        resources = (a.adblock_resources or a.out / ADBLOCK_RESOURCES).read_text(encoding="utf-8")
        bundle = sign_adblock_bundle(resources, a.adblock_serial,
                                     read_signing_key(a.adblock_key, "--adblock-key", keep_out_of),
                                     public_key_from(a.adblock_public_key, "--adblock-public-key"))
    version, problems = preflight(a.src, a.out, a.platform, a.previous,
                                  lambda archive: package_audit.list_archive(archive, a.sevenzip))
    thoron = read_thoron_version(a.src)
    chromium_new = ver.split(version)[0] if read_version(a.src)[1] else None
    chrome_bin = (a.chrome_bin or a.out / CHROME_BIN) if a.platform == "win" else None
    problems += [f"Thoron version: {p}" for p in thoron_version_problems(thoron, ver.release_tags(a.repo))]
    problems += [f"BUILDINFO: {p}" for p in source_problems(info, thoron, chromium_new)]
    licences, found = licence_texts(a.repo, a.src)
    problems += [f"licences: {p}" for p in found]
    if chrome_bin is not None:
        problems += [f"portable package: {p}" for p in portable_problems(chrome_bin, version)]
    problems += [f"credits: {p}" for p in credits_problems(a.repo, upstream_contributors(a.contributors))]
    problems += [f"patch licences: {p}" for p in licence_record_problems(a.repo)]
    problems += [f"performance: {p}" for p in performance_problems(a.repo, a.bench, thoron)]
    audit_doc, audit_lines = changelog.audit_lines(a.repo)
    if not audit_lines:
        problems.append("upstream audit: no docs/security/UPSTREAM_AUDIT_*.md with lines \"For the release notes\" "
                        "(ROADMAP P2.2)" if audit_doc is None else
                        f"upstream audit: {audit_doc} has no lines \"For the release notes\" (ROADMAP P2.2)")
    problems += [f"wiki: {p}" for p in wiki_problems(a.repo, thoron)]
    changes = None
    try:
        if not (a.repo / "CHANGELOG.md").is_file():
            raise changelog.NotesError("CHANGELOG.md is not in the repository")
        section, changes = changelog.release_changes((a.repo / "CHANGELOG.md").read_text(encoding="utf-8-sig"),
                                                     thoron)
    except changelog.NotesError as exc:
        problems.append(f"changelog: {exc}")
    plan = private_key = public_key = None
    if a.manifest_key:
        private_key = read_signing_key(a.manifest_key, "--manifest-key", keep_out_of)
        public_key = public_key_from(a.manifest_public_key, "--manifest-public-key")
        plan = manifest_plan(a.src, channel=a.channel or "stable", critical=a.critical,
                             min_updater_version=a.min_updater_version, previous_manifest=a.previous_manifest,
                             gh_repo=a.gh_repo, published=now,
                             valid_days=mf.DEFAULT_VALID_DAYS if a.manifest_days is None else a.manifest_days)
        problems += [f"update manifest: {p}"
                     for p in manifest_problems(plan, version, a.variant, private_key, public_key)]
    if problems:
        for prob in problems:
            print(f"release: {prob}", file=sys.stderr)
        print(f"release: {len(problems)} problem(s); nothing was packaged")
        return 1
    if a.dist.exists() and any(a.dist.iterdir()):
        raise ReleaseError(f"{a.dist} is not empty; a release folder is never overwritten")
    try:
        files = assemble(a.out, a.dist, version, a.variant, a.buildinfo, chrome_bin, licences)
        source = {"tag": info["source_tag"], "commit": info["thoron_commit"], "chromium_tag": info["chromium_tag"],
                  "licences": licence_bundle_name(version)}
        notes = changelog.render(version, a.chromium_old, chromium_new, a.repo, a.since,
                                 artifacts=(a.dist / "SHA256SUMS").read_text(encoding="utf-8").splitlines(),
                                 security=security, highlights=highlights, changes=changes, thoron_version=thoron,
                                 source=source, audit=changelog.audit_lines(a.repo))
        (a.dist / "NOTES.md").write_text(notes, encoding="utf-8", newline="\n")
        print(f"release: the notes list the changes under [{section}] of CHANGELOG.md")
        if a.minisign_key:
            files.append(sign(a.dist, a.minisign_key))
        else:
            print("release: SHA256SUMS is not signed (no --minisign-key); publish will refuse it")
        if plan:
            files += write_manifest(a.dist, plan, version, a.variant, private_key, public_key, now)
            print(f"release: {mf.MANIFEST_NAME} is signed: Thoron {plan.thoron_version} (build {version}), "
                  f"channel {plan.channel}, good for {plan.valid_days} days; publish it with --version "
                  f"{plan.thoron_version}")
        else:
            print("release: no update manifest was made (no --manifest-key); publish will refuse this release")
        if bundle:
            files.append(_write_new(a.dist / ADBLOCK_BUNDLE, bundle.encode("utf-8")))
            print(f"release: {ADBLOCK_BUNDLE} is signed (serial {a.adblock_serial}); it is no part of the "
                  f"draft: the owner uploads it to the release tagged {ADBLOCK_TAG}")
    except BaseException:
        if a.dist.exists():
            print(f"release: {a.dist} is incomplete; remove it before running prepare again", file=sys.stderr)
        raise
    print(f"release {version}: {len(files)} file(s) in {a.dist}")
    return 0


def _publish(a, run) -> int:
    public_key = public_key_from(a.manifest_public_key, "--manifest-public-key")
    problems = publish_problems(a.dist, a.version, a.gh_repo, public_key, int(time.time()))
    if problems:
        for prob in problems:
            print(f"release: {prob}", file=sys.stderr)
        print(f"release: {len(problems)} problem(s); nothing was published")
        return 1
    publish(a.dist, a.version, a.gh_repo, run)
    print(f"draft release v{a.version} created; review it on GitHub and publish it by hand")
    if (a.dist / ADBLOCK_BUNDLE).is_file():
        print(f"release: {ADBLOCK_BUNDLE} is not in the draft; the owner uploads it to the release tagged "
              f"{ADBLOCK_TAG}")
    print(f"release: the wiki is not published from here. Once the draft is published, see what would change "
          f"in the wiki and then publish the pages of {check_docs.WIKI_DIR}:")
    for command in wiki_commands(a.gh_repo):
        print(f"    {command}")
    return 0


def main(argv: list[str], run=None) -> int:
    """`run`, when given, takes the `gh` command of publish instead of running it (the tests' seam)."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a_ = sub.add_parser("prepare")
    for name in ("--src", "--out", "--buildinfo", "--dist", "--repo"):
        a_.add_argument(name, type=Path, required=True)
    for name in ("--platform", "--variant", "--previous", "--since", "--chromium-old"):
        a_.add_argument(name, required=True)
    a_.add_argument("--sevenzip", default="7z")
    a_.add_argument("--chrome-bin", type=Path, help=f"the build's browser folder, which becomes the portable "
                    f"package; default: {CHROME_BIN} in the out dir")
    a_.add_argument("--contributors", type=Path, help="a saved list of upstream's contributors, as "
                    "tools/credits/contributors.py --from-json reads it; default: ask GitHub (read only)")
    a_.add_argument("--minisign-key", type=Path)
    a_.add_argument("--security", type=Path, help="security.json: the fixes the notes name")
    a_.add_argument("--highlights", type=Path, help="a hand-written opening of the notes")
    a_.add_argument("--bench", type=Path, help="tools/qa/bench.py's result for this build; it is compared "
                    "with docs/perf/baseline.json (ROADMAP Q.3)")
    a_.add_argument("--manifest-key", type=Path, help="the private key file that signs the update manifest")
    a_.add_argument("--manifest-public-key", help="the public key copies of Thoron hold, base64 of 32 bytes")
    a_.add_argument("--gh-repo", help="the repository the draft is made in: its release serves the packages")
    before = a_.add_mutually_exclusive_group()
    before.add_argument("--previous-manifest", type=Path, help="the manifest this one replaces on the channel")
    before.add_argument("--first-manifest", action="store_true", help="the channel has no manifest yet")
    a_.add_argument("--min-updater-version", help="the oldest updater (build version) that may apply the "
                    "release; default: as in the manifest before")
    a_.add_argument("--critical", action="store_true", help="a security release that should not wait")
    a_.add_argument("--channel", help="default: stable")
    a_.add_argument("--manifest-days", type=int, help=f"how long the manifest is good for; default: "
                    f"{mf.DEFAULT_VALID_DAYS}")
    a_.add_argument("--adblock-key", type=Path, help="the private key file that signs Thoron adblock's resources")
    a_.add_argument("--adblock-public-key", help="the public key copies of Thoron hold for them, in base64")
    a_.add_argument("--adblock-serial", help="YYYYMMDDNN, higher than the copy in use")
    a_.add_argument("--adblock-resources", type=Path, help=f"default: {ADBLOCK_RESOURCES} in the out dir")
    b_ = sub.add_parser("publish")
    b_.add_argument("--dist", type=Path, required=True)
    b_.add_argument("--version", required=True)
    b_.add_argument("--gh-repo", required=True)
    b_.add_argument("--manifest-public-key", required=True,
                    help="the public key copies of Thoron hold, base64 of 32 bytes")
    a = p.parse_args(argv)
    try:
        return _publish(a, run) if a.cmd == "publish" else _prepare(a)
    except (ReleaseError, ver.VersionError, changelog.NotesError, mf.ManifestError, mf.SignatureError, OSError,
            ValueError, subprocess.CalledProcessError) as exc:
        print(f"release: {exc}", file=sys.stderr)
        return 2
    except ImportError as exc:
        if not (exc.name or "").startswith("cryptography"):
            raise
        print("release: signing, and checking a signature, need the Python package cryptography", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
