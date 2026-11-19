#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Release notes for a Thoron release (ROADMAP P2.13, D.4, D.10, design section 8).

Sections, in this order: highlights (optional, written by hand), the Chromium version change and its
security fixes, Thoron's changes, upstream Thorium commits credited by author, patches added, removed and
refreshed, fixed issues, downloads with SHA-256, the source and the licences (when given), credits.
Everything comes from git and local files; nothing is fetched. Author names are used, never emails.

Thoron's changes are the lines of the short changelog: with --changelog, the section of --thoron-version
when CHANGELOG.md has one, else what waits under [Unreleased]. A changelog that is not in its short form
(per version, one line per change under Added, Changed, Fixed, Removed and Security), or that lists no
change for the release, is refused. Without --changelog the commits since --since are grouped by their
prefix (CONTRIBUTING.md) instead.
    py -3 -I tools/release/changelog.py --version 158.0.8127.3000 --chromium-old 156.0.8078.80
        --chromium-new 158.0.8127.30 --repo . --since <last release tag>
        [--changelog CHANGELOG.md] [--thoron-version 0.1.2]
        [--upstream <upstream tree> --upstream-since <commit>] [--series-old <tree> --series-new <tree>]
        [--security security.json] [--sha256sums SHA256SUMS] [--highlights highlights.md] --out NOTES.md
security.json is a list of {"cve", "severity", "title"} taken from the Chrome Releases post.
"""
import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

PREFIXES = {"sec": "Security", "perf": "Performance", "fix": "Fixes", "ui": "User interface",
            "build": "Build", "docs": "Documentation"}
CATEGORIES = ["Security", "Performance", "Fixes", "User interface", "Build", "Documentation", "Other changes"]
SEVERITIES = ["Critical", "High", "Medium", "Low"]
_PREFIX = re.compile(r"^(\w+):\s*(.+)$")
_MERGE = re.compile(r"^Merge (pull request|branch|remote-tracking branch)\b")
_ISSUE = re.compile(r"(?i)\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+#(\d+)")
_LONG_DASH = re.compile("[" + chr(0x2013) + chr(0x2014) + "]")
CHROME_RELEASES = "https://chromereleases.googleblog.com/"
SECTIONS = ("Added", "Changed", "Fixed", "Removed", "Security")     # of the short changelog, in its order
UNRELEASED = "Unreleased"
_VERSION_HEADING = re.compile(r"^## \[([^\]]+)\]")
_ITEM = re.compile(r"^- \S")
_LIST_MARK = re.compile(r"^(?:[-*+]|\d+[.)])(?:\s|$)")
_LINK_DEFINITION = re.compile(r"^\[[^\]]+\]:\s+\S")


class NotesError(Exception):
    pass


def short_changelog(text: str) -> tuple[dict[str, dict[str, list[str]]], list[tuple[int, str]]]:
    """CHANGELOG.md read in its short form (ROADMAP D.10): per version, and for what waits under
    [Unreleased], one line per change under Added, Changed, Fixed, Removed and Security.

    Returns the changes by version and section, and every line that is not in that form, with its number.
    A change wrapped onto indented lines that follow it is still one change. What stands before the first
    version, and between a version's heading and its first section, is free text."""
    versions: dict[str, dict[str, list[str]]] = {}
    problems: list[tuple[int, str]] = []
    version = section = None        # where the line being read stands
    in_change = False               # the line before was a change, or a wrapped part of one
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        wrapped = in_change and line[:1] in (" ", "\t") and not _LIST_MARK.match(line.strip())
        in_change = False
        if not line:
            continue
        if line.startswith("## "):
            m = _VERSION_HEADING.match(line)
            name = m.group(1) if m else line[3:].strip()
            if not m:
                problems.append((number, "a version heading is `## [0.1.1] - YYYY-MM-DD` or `## [Unreleased]`"))
            elif name in versions:
                problems.append((number, f"[{name}] is there twice"))
            version, section = versions.setdefault(name, {}), None
        elif version is None:
            continue
        elif line.startswith("### "):
            name = line[4:].strip()
            if name not in SECTIONS:
                problems.append((number, f"`### {name}`: the sections are {', '.join(SECTIONS)}"))
                section = []                            # its lines are read and kept nowhere
            else:
                if name in version:
                    problems.append((number, f"`### {name}` is there twice under one version"))
                section = version.setdefault(name, [])
        elif _ITEM.match(line):
            if section is None:
                problems.append((number, f"a change outside {', '.join(SECTIONS)}"))
            else:
                section.append(line[2:].strip())
            in_change = True
        elif wrapped:
            if section:
                section[-1] += " " + line.strip()
            in_change = True
        elif section is not None and not _LINK_DEFINITION.match(line):
            problems.append((number, "not a change (`- text`, one line per change) and not a section heading"))
    return versions, problems


def release_changes(text: str, version: str | None = None) -> tuple[str, dict[str, list[str]]]:
    """The changes of one release from the short changelog: the section of `version` (Thoron's own, such as
    0.1.2) when the file has one, else what waits under [Unreleased]. Returns the section taken and its
    changes; NotesError when the file is not in its short form or that section lists no change."""
    versions, problems = short_changelog(text)
    if problems:
        shown = "; ".join(f"line {number}: {what}" for number, what in problems[:5])
        raise NotesError("the changelog is not in its short form: " + shown
                         + (f"; and {len(problems) - 5} more" if len(problems) > 5 else ""))
    name = version if version in versions else UNRELEASED
    if name not in versions:
        raise NotesError(f"the changelog has no [{UNRELEASED}] section")
    if not any(versions[name].values()):
        raise NotesError(f"the changelog lists no change under [{name}]: the notes of a release are its lines there")
    return name, versions[name]


def _clean(text: str) -> str:
    return _LONG_DASH.sub("-", text).strip()


def group_commits(subjects: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {c: [] for c in CATEGORIES}
    for s in subjects:
        s = s.strip()
        if not s or _MERGE.match(s):
            continue
        m = _PREFIX.match(s)
        if m and m.group(1).lower() in PREFIXES:
            groups[PREFIXES[m.group(1).lower()]].append(_clean(m.group(2)))
        else:
            groups["Other changes"].append(_clean(s))
    return groups


def issues(messages: list[str]) -> list[int]:
    return sorted({int(n) for m in messages for n in _ISSUE.findall(m)})


def series_changes(old: dict[str, str], new: dict[str, str]) -> dict[str, list[str]]:
    name = lambda p: Path(p).name
    return {"added": sorted(name(p) for p in new if p not in old),
            "removed": sorted(name(p) for p in old if p not in new),
            "refreshed": sorted(name(p) for p in new if p in old and old[p] != new[p])}


def sort_security(fixes: list[dict]) -> list[dict]:
    for f in fixes:
        if f.get("severity") not in SEVERITIES:
            raise NotesError(f"unknown severity {f.get('severity')!r} for {f.get('cve')}")
    return sorted(fixes, key=lambda f: (SEVERITIES.index(f["severity"]), f["cve"]))


def security_problems(fixes) -> list[str]:
    """Why `fixes` is not a security list (the content of security.json); empty when it is one."""
    if not isinstance(fixes, list) or not fixes:
        return ["a security list is a JSON list of at least one fix (leave it out when there is none)"]
    out = []
    for number, fix in enumerate(fixes, 1):
        if not isinstance(fix, dict):
            out.append(f"fix {number}: must be an object with cve, severity and title")
            continue
        for key in ("cve", "severity", "title"):
            value = fix.get(key)
            if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
                out.append(f"fix {number}: {key} must be one line of text")
            elif key == "severity" and value not in SEVERITIES:
                out.append(f"fix {number}: severity must be one of {', '.join(SEVERITIES)}")
    return out


def read_security(path: Path) -> list[dict]:
    """The security list of a file (security.json), or NotesError naming everything wrong with it."""
    try:
        fixes = json.loads(path.read_text(encoding="utf-8-sig"))      # a byte order mark is not content
    except ValueError as exc:
        raise NotesError(f"{path.name} is not JSON: {exc}") from None
    found = security_problems(fixes)
    if found:
        raise NotesError(f"{path.name}: " + "; ".join(found))
    return fixes


def _log(repo: Path, since: str) -> list[dict]:
    out = subprocess.run(["git", "-C", str(repo), "log", "--no-merges", "--reverse",
                          "--format=%an%x1f%s%x1f%b%x1e", f"{since}..HEAD"],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    entries = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        author, subject, body = (rec.split("\x1f") + ["", ""])[:3]
        entries.append({"author": author.strip(), "subject": subject.strip(), "body": body.strip()})
    return entries


AUDIT_GLOB = "docs/security/UPSTREAM_AUDIT_*.md"
AUDIT_SECTION = re.compile(r"(?ms)^## \d+\. For the release notes\n(.*?)(?=^## |\Z)")


def audit_lines(repo: Path) -> tuple[str | None, list[str]]:
    """The newest upstream audit (ROADMAP P2.2) and its lines for the release notes: the list items of its
    section "For the release notes", each joined onto one line. (None, []) when there is none."""
    docs = sorted(repo.glob(AUDIT_GLOB), key=lambda p: (len(p.stem), p.stem))
    if not docs:
        return None, []
    newest = docs[-1]
    m = AUDIT_SECTION.search(newest.read_text(encoding="utf-8").replace("\r\n", "\n"))
    if not m:
        return newest.name, []
    items, current = [], None
    for line in m.group(1).splitlines():
        if line.startswith("- "):
            current = line[2:].strip()
            items.append(current)
        elif line.startswith("  ") and current is not None and line.strip():
            items[-1] = items[-1] + " " + line.strip()
        elif not line.strip():
            current = None
    return newest.name, items


def series_files(tree: Path) -> dict[str, str]:
    from tools.legal.patch_licenses import series_patches
    return {rel: (tree / rel).read_text(encoding="utf-8", errors="replace") for rel in series_patches(tree)
            if (tree / rel).is_file()}


def render(version: str, chromium_old: str, chromium_new: str, repo: Path, since: str,
           upstream: Path | None = None, upstream_since: str | None = None,
           series: dict | None = None, security: list | None = None, artifacts: list | None = None,
           highlights: str | None = None, changes: dict | None = None, thoron_version: str | None = None,
           source: dict | None = None, audit: tuple[str, list[str]] | None = None) -> str:
    """`changes` are the release's lines of the short changelog (release_changes); without them the commits
    are grouped by prefix. `thoron_version` is the version people see; `version` stays the build number.
    `source` names the tag, the commit, the Chromium tag and the licence bundle of the release (L.2)."""
    built = f"Thoron {thoron_version} (build {version})" if thoron_version else f"Thoron {version}"
    # ROADMAP B.4: the release banner, from the release's own tag (branding/thoron/social/)
    out = [f"![Thoron]({source['banner']})", ""] if source and source.get("banner") else []
    out += [f"# Thoron {thoron_version or version}", "",
           f"{built} is based on Chromium {chromium_new} and the Thorium patch series.", ""]
    if highlights:
        out += ["## Highlights", "", _clean(highlights), ""]
    out += ["## Chromium", ""]
    if chromium_old == chromium_new:
        out.append(f"Chromium {chromium_new}, unchanged since the last release.")
    else:
        out.append(f"Chromium {chromium_old} to {chromium_new}. Details: [Chrome Releases]({CHROME_RELEASES}).")
    if security:
        out += ["", "### Security fixes", ""]
        out += [f"- {f['cve']} ({f['severity']}): {_clean(f['title'])}" for f in sort_security(security)]
    entries = _log(repo, since)
    groups = group_commits([e["subject"] for e in entries])
    out += ["", "## Thoron changes"]
    if changes is not None:
        listed = [(name, changes.get(name) or []) for name in SECTIONS]
    else:
        listed = [(cat, groups[cat]) for cat in CATEGORIES]
    for title, lines in listed:
        if lines:
            out += ["", f"### {title}", ""] + [f"- {_clean(s)}" for s in lines]
    if not any(lines for _, lines in listed):
        out += ["", "No changes of our own."]
    out += ["", "## Upstream Thorium", ""]
    if upstream and upstream_since:
        up = [e for e in _log(upstream, upstream_since) if not _MERGE.match(e["subject"])]
        if up:
            out += [f"- {_clean(e['subject'])} ({e['author']})" for e in up]
            counts = Counter(e["author"] for e in up)
            thanks = ", ".join(f"{a} ({n} commit{'s' if n != 1 else ''})" for a, n in counts.most_common())
            out += ["", f"Thanks to: {thanks}."]
        else:
            out.append("No new upstream commits.")
    else:
        out.append("No new upstream commits.")
    if audit and audit[1]:
        out += ["", "## Upstream audit", "",
                f"Every change taken from upstream was audited before this release (`docs/security/{audit[0]}`):",
                ""] + [f"- {_clean(line)}" for line in audit[1]]
    out += ["", "## Patches", ""]
    series = series or {"added": [], "removed": [], "refreshed": []}
    for key, title in (("added", "Added"), ("removed", "Removed"), ("refreshed", "Refreshed")):
        names = series.get(key) or []
        out.append(f"- {title}: " + (", ".join(f"`{n}`" for n in names) if names else "none"))
    fixed = issues([e["subject"] + "\n" + e["body"] for e in entries])
    out += ["", "## Fixed issues", "", ", ".join(f"#{n}" for n in fixed) if fixed else "None reported."]
    out += ["", "## Downloads", ""]
    lines = [l.split(None, 1) for l in (artifacts or []) if l.strip()]
    if lines:
        out += ["| File | SHA-256 |", "|---|---|"] + [f"| `{n.strip().lstrip('*')}` | `{h}` |" for h, n in lines]
        out += ["", "Check the files against `SHA256SUMS` and its signature, as described in the README"
                    " (Verifying downloads)."]
    else:
        out.append("The files are attached to this release with `SHA256SUMS` and its signature.")
    if source:
        out += ["", "## Source and licences", "",
                f"The source of this release is the tag `{source['tag']}` of this repository (commit"
                f" `{source['commit']}`), applied to Chromium at its tag `{source['chromium_tag']}`. Parts of"
                " Thoron are under the GNU General Public License version 3; `NOTICE` says which. Its text and"
                f" the other licence texts are in `{source['licences']}`, and in the browser at"
                " `chrome://credits`."]
    out += ["", "## Credits", "",
            "Thoron is based on [Thorium](https://github.com/Alex313031/thorium) by Alex313031 and gz83, and on"
            " Chromium by The Chromium Authors. Every contributor and patch source is credited in"
            " [CREDITS.md](CREDITS.md).", ""]
    text = "\n".join(out)
    if _LONG_DASH.search(text):
        raise NotesError("long dash left in the notes")
    return text


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", required=True)
    p.add_argument("--chromium-old", required=True)
    p.add_argument("--chromium-new", required=True)
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--since", required=True)
    p.add_argument("--upstream", type=Path)
    p.add_argument("--upstream-since")
    p.add_argument("--series-old", type=Path)
    p.add_argument("--series-new", type=Path)
    p.add_argument("--security", type=Path)
    p.add_argument("--sha256sums", type=Path)
    p.add_argument("--highlights", type=Path)
    p.add_argument("--changelog", type=Path, help="CHANGELOG.md in its short form: Thoron's changes come from it")
    p.add_argument("--thoron-version", help="Thoron's own version, such as 0.1.2: the notes' title, and the "
                   "changelog section taken when there is one")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        series = (series_changes(series_files(a.series_old), series_files(a.series_new))
                  if a.series_old and a.series_new else None)
        changes = (release_changes(a.changelog.read_text(encoding="utf-8-sig"), a.thoron_version)[1]
                   if a.changelog else None)
        text = render(a.version, a.chromium_old, a.chromium_new, a.repo, a.since, a.upstream, a.upstream_since,
                      series,
                      read_security(a.security) if a.security else None,
                      a.sha256sums.read_text(encoding="utf-8").splitlines() if a.sha256sums else None,
                      a.highlights.read_text(encoding="utf-8") if a.highlights else None,
                      changes, a.thoron_version)
    except (NotesError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"changelog: {exc}", file=sys.stderr)
        return 2
    a.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
