# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Chromium's Gemini plumbing is not loaded or shown: the offline check (ROADMAP S.16)."""
import unittest

from tools.qa import glic_check as gc

PDF = {"name": "Chromium PDF Viewer", "location": "COMPONENT"}
GEMINI = {"name": "Gemini in Chrome", "location": "COMPONENT"}


def menu(*ids, hidden=()):
    return [{"id": i, "href": "/" + i, "shown": i not in hidden} for i in ids]


FULL = menu("people", "autofill", "privacy", "performance", "appearance", "search", "thoronAdblockLink")


class StepTests(unittest.TestCase):
    def test_component(self):
        self.assertEqual(gc.component_problems([PDF]), [])
        self.assertEqual(len(gc.component_problems([GEMINI, PDF])), 1)
        self.assertEqual(len(gc.component_problems([{"name": "Glic helper"}])), 1)
        self.assertEqual(len(gc.component_problems([])), 1)

    def test_settings(self):
        self.assertEqual(gc.settings_problems(FULL), [])
        self.assertEqual(len(gc.settings_problems(FULL + menu("ai"))), 1)
        self.assertEqual(gc.settings_problems(FULL + menu("ai", hidden=("ai",))), [])
        self.assertEqual(len(gc.settings_problems([m for m in FULL if m["id"] != "thoronAdblockLink"])), 1)
        self.assertEqual(len(gc.settings_problems([])), 1)

    def test_an_entry_is_known_by_its_address_too(self):
        other = FULL + [{"id": "renamed", "href": "/ai", "shown": True}]
        self.assertEqual(len(gc.settings_problems(other)), 1)

    def test_switch(self):
        self.assertEqual(gc.switch_problems([GEMINI, PDF]), [])
        self.assertEqual(len(gc.switch_problems([PDF])), 1)


if __name__ == "__main__":
    unittest.main()
