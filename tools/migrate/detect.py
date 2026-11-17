#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Which browsers of the Chromium family this Windows user has, and their profiles (ROADMAP P3.13, I9).

What an import offers is found here: Thorium, Chrome, Edge, Brave, Vivaldi, Opera, Opera GX and Chromium, each in
the folders of the current user only (never another user's, never a system-wide one), with the profiles its
`Local State` lists. A browser counts as running while its `lockfile` exists, so an import can ask for it to be
closed first (it never closes it). Nothing is read beyond `Local State` and the profile folders' names.

    py -3 -I tools/migrate/detect.py            prints what it finds (profile names are the person's own)
    py -3 -I tools/migrate/detect.py --json
"""
import argparse
import json
import os
import sys
from pathlib import Path

# browser -> (where its folder of profiles is, under %LOCALAPPDATA% or %APPDATA%), whether that folder is one
# profile itself (Opera keeps its only profile in the folder that holds Local State)
BROWSERS = (
    ("Thorium", "LOCALAPPDATA", "Thorium/User Data", False),
    ("Chrome", "LOCALAPPDATA", "Google/Chrome/User Data", False),
    ("Edge", "LOCALAPPDATA", "Microsoft/Edge/User Data", False),
    ("Brave", "LOCALAPPDATA", "BraveSoftware/Brave-Browser/User Data", False),
    ("Vivaldi", "LOCALAPPDATA", "Vivaldi/User Data", False),
    ("Opera", "APPDATA", "Opera Software/Opera Stable", True),
    ("Opera GX", "APPDATA", "Opera Software/Opera GX Stable", True),
    ("Chromium", "LOCALAPPDATA", "Chromium/User Data", False),
)
MOST_LOCAL_STATE_BYTES = 8 * 1024 * 1024


def profiles_of(user_data: Path, single: bool) -> list[dict]:
    """The profiles `Local State` lists that have their folder: folder name and the name the person gave it."""
    if single:
        return [{"folder": ".", "name": "Default"}] if (user_data / "Preferences").is_file() else []
    state_file = user_data / "Local State"
    try:
        if state_file.stat().st_size > MOST_LOCAL_STATE_BYTES:
            return []
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return []
    # another browser's file: any part of it may have another shape than the browser writes
    profile = state.get("profile") if isinstance(state, dict) else None
    cache = (profile.get("info_cache") if isinstance(profile, dict) else None) or {}
    if not isinstance(cache, dict):
        return []
    out = []
    for folder, info in sorted(cache.items()):
        if not isinstance(info, dict) or "/" in folder or "\\" in folder or folder in (".", ".."):
            continue
        if (user_data / folder / "Preferences").is_file():
            out.append({"folder": folder, "name": str(info.get("name") or folder)[:100]})
    return out


def detect(environ: dict | None = None) -> list[dict]:
    """The browsers found for the current user, each with its folder, whether it runs, and its profiles."""
    env = os.environ if environ is None else environ
    found = []
    for name, base, rel, single in BROWSERS:
        root = env.get(base)
        if not root:
            continue
        folder = Path(root) / rel
        if not (folder / "Local State").is_file():
            continue
        found.append({"browser": name, "folder": str(folder), "running": (folder / "lockfile").exists(),
                      "profiles": profiles_of(folder, single)})
    return found


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    found = detect()
    if a.json:
        print(json.dumps(found, indent=2, ensure_ascii=False))
        return 0
    for browser in found:
        state = " (running: close it before an import)" if browser["running"] else ""
        print(f"{browser['browser']}{state}: {len(browser['profiles'])} profile(s)")
        for profile in browser["profiles"]:
            print(f"  {profile['folder']}: {profile['name']}")
    if not found:
        print("no browser of the Chromium family was found for this user")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
