# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock, chrome://adblock's regional lists and finding things there: the offline check (ROADMAP P5.73)."""
import unittest

from tools.qa import adblock_catalog_check as cc

DE = {"flags": [{"name": "Deutschland", "shapes": 4, "letters": ""}], "text": "EasyList Germany Deutschland https://x"}
AT = {"flags": [{"name": "Österreich", "shapes": 4, "letters": ""}], "text": "Liste AT Österreich https://y"}


def catalog(regional, suggested=None, none=False):
    seen = [{"group": cc.REGIONS, "lists": regional}]
    if suggested is not None:
        seen.insert(0, {"group": cc.SUGGESTED, "lists": suggested})
    return seen + [{"none": none}]


class StepTests(unittest.TestCase):
    def test_flags(self):
        self.assertEqual(cc.flags_problems(catalog([DE, AT] * 20)), [])
        self.assertIn("not all", cc.flags_problems(catalog([DE]))[0])
        bare = dict(DE, flags=[])
        self.assertTrue(any("without a flag" in p for p in cc.flags_problems(catalog([bare] * 31))))
        letters = dict(DE, flags=[{"name": "XX", "shapes": 1, "letters": "XX"}])
        self.assertTrue(any("by their letters" in p for p in cc.flags_problems(catalog([letters] * 31))))
        emoji = dict(DE, text="\U0001F1E9\U0001F1EA EasyList Germany")
        self.assertTrue(any("emoji" in p for p in cc.flags_problems(catalog([emoji] * 31))))

    def test_suggest(self):
        self.assertEqual(cc.suggest_problems(catalog([DE, AT], [DE]), "Deutschland"), [])
        self.assertIn("no lists", cc.suggest_problems(catalog([DE, AT]), "Deutschland")[0])
        self.assertIn("not one for", cc.suggest_problems(catalog([DE, AT], [DE, AT]), "Deutschland")[0])

    def test_find(self):
        empty = [{"none": True}]
        self.assertEqual(cc.find_problems(catalog([AT]), empty, "Österreich"), [])
        self.assertIn("found no list", cc.find_problems(catalog([], none=True), empty, "Österreich")[0])
        self.assertIn("do not name it", cc.find_problems(catalog([AT, DE]), empty, "Österreich")[0])
        self.assertIn("nonsense", cc.find_problems(catalog([AT]), catalog([DE]), "Österreich")[0])

    def test_setting(self):
        everything = {"shown": ["a", "b Menü", "c"], "headings": ["A", "B"], "none": False}
        found = {"shown": ["b Menü"], "headings": ["B"], "none": False}
        nothing = {"shown": [], "headings": [], "none": True}
        self.assertEqual(cc.setting_problems(found, everything, nothing, "Menü"), [])
        self.assertTrue(cc.setting_problems(everything, everything, nothing, "Menü"))
        self.assertIn("nonsense", cc.setting_problems(found, everything, found, "Menü")[0])

    def test_preview(self):
        self.assertEqual(cc.preview_problems({"menu": "bbb[iii]bbbSM", "extensions": "bbb[iSii]bSbbM"}), [])
        self.assertIn("next to the menu", cc.preview_problems({"menu": "bbb[iii]Sbbbm",
                                                               "extensions": "bbb[iSii]bSbbM"})[0])
        self.assertIn("default", cc.preview_problems({"menu": "bbb[iii]bbbSM", "extensions": "bbb[iii]bSbbM"})[0])


if __name__ == "__main__":
    unittest.main()
