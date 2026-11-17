# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock's import of uBlock Origin's own backup (ROADMAP P5.1): the judgement of the browser check, and
the page script's table of uBlock Origin's list names, read from the published source."""
import copy
import re
import unittest
from pathlib import Path

from tools.qa import adblock_backup_check as bc

PATCH = Path(__file__).resolve().parents[3] / "source/overlay/other/ks-native-adblock-engine.patch"


def page_script() -> str:
    """settings_page.js as the published patch adds it."""
    text = PATCH.read_text(encoding="utf-8")
    start = text.index("+++ b/components/thoron_adblock/settings_page.js")
    end = text.find("\ndiff --git ", start)
    body = text[start:end if end != -1 else len(text)].splitlines()[1:]
    return "\n".join(line[1:] for line in body if line.startswith("+"))


def brought_over() -> dict:
    backup = bc.UBO_BACKUP
    return {"settings": {"prefetch": True, "default-fonts": True, "badge": False, "media-kb": 80, "theme": "dark"},
            "myFilters": backup["userFilters"], "disabled": ["easyprivacy"], "allowed": [bc.UBO_TRUSTED],
            "switches": {bc.UBO_POPUPS: ["popups"]}}


MESSAGE = ("The backup of uBlock Origin was brought over. Not brought over: the list XYZ-0 (add it from the list "
           "of lists, if it is there); 1 advanced setting(s) of uBlock Origin.")


class JudgementTests(unittest.TestCase):
    def test_what_came_over(self):
        self.assertEqual(bc.ublock_problems(brought_over(), MESSAGE), [])

    def test_each_part_that_differs_is_named(self):
        got = brought_over()
        got["disabled"] = ["easyprivacy", "phishing-1"]
        self.assertIn("phishing", bc.ublock_problems(got, MESSAGE)[0])
        got = brought_over()
        got["allowed"] = [bc.UBO_TRUSTED, "chrome-extension-scheme"]
        self.assertIn("own entries", bc.ublock_problems(got, MESSAGE)[0])
        got = copy.deepcopy(brought_over())
        got["settings"]["media-kb"] = 50
        self.assertIn("media-kb", bc.ublock_problems(got, MESSAGE)[0])
        self.assertIn("not named", bc.ublock_problems(brought_over(), "The backup of uBlock Origin was brought "
                                                                      "over.")[0])
        self.assertIn("said", bc.ublock_problems(brought_over(), "This file is not a backup")[0])

    def test_the_backup_has_the_fields_ublock_origin_writes(self):
        for field in ("timeStamp", "version", "userSettings", "selectedFilterLists", "hiddenSettings", "whitelist",
                      "dynamicFilteringString", "urlFilteringString", "hostnameSwitchesString", "userFilters"):
            self.assertIn(field, bc.UBO_BACKUP)


@unittest.skipUnless(PATCH.is_file(), "the published source is not here")
class ListNameTests(unittest.TestCase):
    def test_every_optional_list_name_finds_its_list_in_the_catalog(self):
        script = page_script()
        table = script[script.index("const UBO_OPTIONAL = {"):]
        table = table[:table.index("};")]
        titles = re.findall(r"""^\s*'[a-z0-9_-]+': (?:'([^']+)'|"([^"]+)"),$""", table, re.M)
        self.assertGreater(len(titles), 15)
        catalog = set(re.findall(r'"title": "([^"]+)"', script))
        for single, double in titles:
            self.assertIn(single or double, catalog)

    def test_the_built_in_lists_are_the_ones_the_browser_has(self):
        script = page_script()
        built_in = re.search(r"const UBO_BUILT_IN = \[([^\]]+)\]", script).group(1)
        self.assertEqual(sorted(re.findall(r"'([a-z0-9-]+)'", built_in)),
                         sorted(["easylist", "easyprivacy", "ublock-filters", "ublock-privacy", "ublock-badware",
                                 "ublock-quick-fixes", "ublock-unbreak", "urlhaus-1"]))
        self.assertIn("const THORON_ONLY = new Set(['phishing-1']);", script)


if __name__ == "__main__":
    unittest.main()
