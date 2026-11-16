# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""chrome://credits lists what Thoron is built from: the offline check (ROADMAP P2.5)."""
import unittest

from tools.qa import credits_check as cc


def page():
    products = []
    for name in cc.ENTRIES:
        text = " ".join(cc.TEXTS.get(name, ("Mozilla Public License",))) + " " + "x" * 100
        products.append({"name": name, "text": text})
    return products


class StepTests(unittest.TestCase):
    def test_a_complete_page_passes(self):
        self.assertEqual(cc.listed_problems(page()), [])
        self.assertEqual(cc.texts_problems(page()), [])

    def test_a_missing_entry_or_an_empty_text_fails(self):
        self.assertEqual(len(cc.listed_problems(page()[1:])), 1)
        short = page()
        short[0]["text"] = "BSD"
        self.assertEqual(len(cc.listed_problems(short)), 1)

    def test_a_text_without_what_it_must_hold_fails(self):
        wrong = page()
        wrong[1]["text"] = "x" * 200
        self.assertEqual(len(cc.texts_problems(wrong)), 2)


if __name__ == "__main__":
    unittest.main()
