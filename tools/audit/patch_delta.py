#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""What changed INSIDE the patch files between two revisions.

Upstream is a patch series, so most of its commits change patch files. A refreshed patch differs in
every hunk header and index line although it makes the same change; a patch with one new line looks
no different in a diffstat. This tool compares what each patch does:

    same      the patch adds and removes the same lines in the same files; only context, offsets
              or index lines moved
    changed   lines the patch adds or removes were gained or lost (--show prints them)
    added, deleted

    py -3 -I tools/audit/patch_delta.py REPO BASE TARGET [PATH ...] [--show] [--json]

BASE and TARGET are commits or trees, so a folder of patches can be compared with upstream's:
    py -3 -I tools/audit/patch_delta.py . <upstream commit> HEAD:source/overlay other/<name>.patch --show

Like audit_diff.py it only reads: the file list comes from `git diff --raw -z`, contents are read by
blob id, and each hunk is consumed by the line counts its header declares, so a line that looks like a
header cannot hide a change. Lines outside the hunks (file names, modes, binary payloads, the text
above the first file) are compared as well; only `index` lines and hunk headers are left out.
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.audit.audit_diff import REGULAR_OR_LINK, _changes, _git, _read_blobs  # noqa: E402

PATCH_NAME_RE = re.compile(r"\.(patch|diff)$")
HUNK_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
INDEX_RE = re.compile(r"^index [0-9a-f]+\.\.[0-9a-f]+( \d+)?$")


def inner_lines(text: str) -> collections.Counter:
    """Counter of (inner file, line): the "+" and "-" lines of every hunk and the lines outside hunks."""
    lines = [line.rstrip("\r") for line in text.split("\n")]
    found, current, i = collections.Counter(), "", 0
    while i < len(lines):
        line = lines[i]
        i += 1
        match = HUNK_RE.match(line)
        if not match:
            if line.startswith("diff --git ") and " b/" in line:
                current = line.split(" b/", 1)[1]
            elif line.startswith(("--- ", "+++ ")) and line[4:].split("\t")[0] != "/dev/null":
                current = re.sub(r"^[ab]/", "", line[4:].split("\t")[0])   # a patch without `diff --git` lines
            if line and not INDEX_RE.match(line):
                found[(current, line)] += 1
            continue
        old_left = int(match.group(1)) if match.group(1) is not None else 1
        new_left = int(match.group(2)) if match.group(2) is not None else 1
        while (old_left > 0 or new_left > 0) and i < len(lines):
            body = lines[i]
            i += 1
            if body.startswith("\\"):
                continue
            if body.startswith("+"):
                new_left -= 1
                found[(current, body)] += 1
            elif body.startswith("-"):
                old_left -= 1
                found[(current, body)] += 1
            else:
                old_left -= 1
                new_left -= 1
    return found


def _tree(repo: str, rev: str) -> str:
    if rev.startswith("-"):
        raise ValueError(f"refusing option-like revision {rev!r}")
    sha = _git(repo, "rev-parse", "--verify", rev).decode("ascii").strip()
    return _git(repo, "rev-parse", "--verify", f"{sha}^{{tree}}").decode("ascii").strip()


def compare(repo: str, base: str, target: str, paths: list[str] | None = None) -> list[dict]:
    """One entry per patch file that differs between the two trees: path, state, gained, lost."""
    changes = [c for c in _changes(repo, _tree(repo, base), _tree(repo, target))
               if PATCH_NAME_RE.search(c[0]) and (not paths or c[0] in paths)]
    both = [c for c in changes if c[1] in ("M", "T") and c[2] in REGULAR_OR_LINK and c[3] in REGULAR_OR_LINK]
    blobs = _read_blobs(repo, sorted({sha for c in both for sha in c[4:6]}))
    entries = []
    for path, status, _old_mode, _new_mode, old_sha, new_sha in changes:
        entry = {"path": path, "state": {"A": "added", "D": "deleted"}.get(status, "changed"), "gained": [], "lost": []}
        if old_sha in blobs and new_sha in blobs:
            old, new = (inner_lines(blobs[sha].decode("utf-8", "replace")) for sha in (old_sha, new_sha))
            entry["gained"] = [list(key) for key in sorted((new - old).elements())]
            entry["lost"] = [list(key) for key in sorted((old - new).elements())]
            if not entry["gained"] and not entry["lost"]:
                entry["state"] = "same"
        entries.append(entry)
    return entries


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo")
    parser.add_argument("base")
    parser.add_argument("target")
    parser.add_argument("paths", nargs="*", help="only these patch files (paths as in the trees)")
    parser.add_argument("--show", action="store_true", help="print the lines a changed patch gained or lost")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    entries = compare(args.repo, args.base, args.target, args.paths)
    if args.json:
        print(json.dumps(entries, indent=1))
        return 0
    for entry in entries:
        detail = f"  ({len(entry['gained'])} gained, {len(entry['lost'])} lost)" if entry["state"] == "changed" else ""
        print(f"{entry['state']:<8} {entry['path']}{detail}")
        if args.show:
            for kind in ("lost", "gained"):
                for inner, line in entry[kind]:
                    print(f"    {kind:<6} [{inner}] {line}")
    count = collections.Counter(entry["state"] for entry in entries)
    print(f"{len(entries)} patch file(s): {count['same']} same, {count['changed']} changed, "
          f"{count['added']} added, {count['deleted']} deleted")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
