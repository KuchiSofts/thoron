#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The patches whose authors publish no licence stay out of the published source (ROADMAP L.1).

Four records must agree, and `check` names every place where they do not:
    docs/legal/PATCH_LICENSES.md       the inventory: its rows marked NOT STATED are the patches without a licence
    tools/legal/patch_origins.tsv      the research: NOT STATED there and in the inventory for the same patches
    source/UPSTREAM.json, overlay/     each of them is withheld (recorded by hash only) and not in the overlay;
                                       nothing else is withheld except the files in OTHER_WITHHELD
    docs/legal/UNLICENSED_PATCHES.md   each of them has a section with the decision
A row marked UNKNOWN is a problem too. With `--tree` the patch series is read as well: every patch has a row
in the inventory, and a patch header says NOT STATED for exactly these patches. With `--release` a patch that
still has no licence is itself a problem, because a release may not carry it.
    py -3 -I tools/legal/unlicensed_patches.py check [--repo <repository>] [--tree <series tree>] [--release]
Exit status: 0 the records agree, 1 they do not.
"""
import argparse
import json
import sys
from pathlib import Path, PurePosixPath

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.legal import patch_headers as ph  # noqa: E402
from tools.legal import patch_licenses as pl  # noqa: E402

INVENTORY = "docs/legal/PATCH_LICENSES.md"
RESEARCH = "tools/legal/patch_origins.tsv"
UPSTREAM = "source/UPSTREAM.json"
OVERLAY = "source/overlay"
DECISIONS = "docs/legal/UNLICENSED_PATCHES.md"
# Withheld for another reason: it carries credentials that are not Thoron's (ROADMAP L.8).
OTHER_WITHHELD = frozenset({"other/thorium-default-api-keys.patch"})


def without_licence(inventory_md: str) -> list[str]:
    """The patches the inventory marks NOT STATED, by name."""
    return sorted(r["patch"] for r in pl.read_table(inventory_md) if r["license"] == pl.NOT_STATED)


def problems(inventory_md: str, research_tsv: str, upstream_json: str, overlay: set[str], decisions_md: str,
             release: bool = False) -> list[str]:
    """Why the records disagree. `overlay` holds the paths of the files in source/overlay."""
    rows = {r["patch"]: r["license"] for r in pl.read_table(inventory_md)}
    bare = set(without_licence(inventory_md))
    out = [f"{name}: the inventory says UNKNOWN; research it first"
           for name in sorted(rows) if rows[name] == "UNKNOWN"]
    research = pl.load_research(research_tsv)
    for name in sorted(bare):
        found = research.get(name, {}).get("license", "no row")
        if found != pl.NOT_STATED:
            out.append(f"{name}: NOT STATED in the inventory, {found} in the research")
    for name, row in sorted(research.items()):
        if row["license"] == pl.NOT_STATED and name in rows and name not in bare:
            out.append(f"{name}: NOT STATED in the research, {rows[name]} in the inventory")
    withheld = set(json.loads(upstream_json).get("withheld", {}))
    names = {PurePosixPath(path).name: path for path in withheld}
    out += [f"{name}: no licence, but not withheld in {UPSTREAM}" for name in sorted(bare - set(names))]
    out += [f"{path}: withheld in {UPSTREAM}, but it has a licence and is no known exception"
            for path in sorted(withheld - OTHER_WITHHELD) if PurePosixPath(path).name not in bare]
    out += [f"{path}: in {OVERLAY}, so it is published; it must only be recorded by hash"
            for path in sorted(overlay) if PurePosixPath(path).name in bare or path in OTHER_WITHHELD]
    headings = [line for line in decisions_md.splitlines() if line.startswith("#")]
    out += [f"{name}: no section in {DECISIONS}" for name in sorted(bare)
            if not any(f"`{name}`" in line for line in headings)]
    if release:
        out += [f"{name}: still without a licence; a release may not carry it" for name in sorted(bare)]
    return out


def tree_problems(tree: Path, inventory_md: str) -> list[str]:
    """Why a patch series and the inventory disagree about which patches there are and which have no licence."""
    rows = {r["patch"] for r in pl.read_table(inventory_md)}
    bare = set(without_licence(inventory_md))
    series = pl.series_patches(tree)
    names = {Path(rel).name for rel in series}
    out = [f"{name}: in the series, but the inventory has no row for it; run patch_licenses.py"
           for name in sorted(names - rows)]
    out += [f"{name}: a row in the inventory, but not in the series" for name in sorted(rows - names)]
    for rel in series:
        path, name = tree / rel, Path(rel).name
        if not path.is_file():
            continue
        said = ph.header_fields(path.read_text(encoding="utf-8", errors="replace")).get("license", "nothing")
        if (said == pl.NOT_STATED) != (name in bare):
            out.append(f"{name}: its header says {said}, the inventory says "
                       f"{pl.NOT_STATED if name in bare else 'it has a licence'}")
    return out


def check(repo: Path, tree: Path | None = None, release: bool = False) -> tuple[list[str], list[str]]:
    """The patches without a licence and the problems found in the repository (and the series, if given)."""
    texts = {}
    for rel in (INVENTORY, RESEARCH, UPSTREAM, DECISIONS):
        path = repo / rel
        if not path.is_file():
            return [], [f"{rel} is not in the repository"]
        texts[rel] = path.read_text(encoding="utf-8")
    root = repo / OVERLAY
    overlay = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} if root.is_dir() else set()
    try:
        found = problems(texts[INVENTORY], texts[RESEARCH], texts[UPSTREAM], overlay, texts[DECISIONS], release)
    except ValueError as exc:       # a research row or the JSON that cannot be read
        return [], [str(exc)]
    if tree is not None:
        found += tree_problems(tree, texts[INVENTORY])
    return without_licence(texts[INVENTORY]), found


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    c.add_argument("--tree", type=Path, help="the patch series' tree; its patches and headers are read too")
    c.add_argument("--release", action="store_true", help="a patch that still has no licence is a problem")
    a = parser.parse_args(argv)
    bare, found = check(a.repo, a.tree, a.release)
    for problem in found:
        print(f"unlicensed_patches: {problem}", file=sys.stderr)
    print(f"unlicensed patches: {len(bare)} without a licence, {len(found)} problem(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
