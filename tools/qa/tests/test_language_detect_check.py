# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""A page's language is found without a download: the offline check (ROADMAP S.15)."""
import unittest

from tools.qa import language_detect_check as ld


def row(path, detected, adopted, by=ld.BUILT_IN, declared=""):
    return {"url": f"http://127.0.0.1:5000{path}", "declared": declared, "detected": detected, "by": by,
            "adopted": adopted}


GOOD = [row("/plain-fr", "fr - French", "fr - French"), row("/plain-en", "en - English", "en - English"),
        row("/declared-es", "es - Spanish", "es - Spanish", declared="es - Spanish")]


class PageTests(unittest.TestCase):
    def test_a_page_says_its_language_or_not(self):
        self.assertIn(b'<html lang="es">', ld.page("es", "hola"))
        self.assertIn(b"<html><head>", ld.page("", "hello"))
        self.assertIn("rivière".encode("utf-8"), ld.page("", ld.FRENCH))

    def test_the_pages(self):
        self.assertEqual({v[2] for v in ld.PAGES.values()}, {"fr", "en", "es"})
        self.assertEqual([p for p, v in ld.PAGES.items() if v[0]], ["/declared-es"])
        for _, text, _ in ld.PAGES.values():
            self.assertGreater(len(text), 300)

    def test_code(self):
        self.assertEqual(ld.code("fr - French"), "fr")
        self.assertEqual(ld.code("pt-BR - Portuguese"), "pt")
        self.assertEqual(ld.code(" EN "), "en")
        self.assertEqual(ld.code(""), "")


class StepTests(unittest.TestCase):
    def test_all_as_wanted(self):
        self.assertEqual(ld.plain_problems(GOOD), [])
        self.assertEqual(ld.declared_problems(GOOD), [])
        self.assertEqual(ld.built_in_problems(GOOD), [])

    def test_a_language_not_found(self):
        rows = [row("/plain-fr", "", "und - Unknown"), GOOD[1], GOOD[2]]
        found = ld.plain_problems(rows)
        self.assertEqual(len(found), 1)
        self.assertIn("/plain-fr", found[0])

    def test_a_page_not_listed(self):
        self.assertEqual(len(ld.plain_problems([GOOD[2]])), 2)
        self.assertEqual(len(ld.declared_problems(GOOD[:2])), 1)
        self.assertEqual(ld.built_in_problems([]), ["built-in: no detection was listed"])

    def test_the_declared_page(self):
        rows = GOOD[:2] + [row("/declared-es", "es - Spanish", "en - English", declared="es - Spanish")]
        self.assertEqual(len(ld.declared_problems(rows)), 1)

    def test_another_detector(self):
        rows = GOOD[:2] + [row("/declared-es", "es - Spanish", "es - Spanish", by="TFLite_v1")]
        found = ld.built_in_problems(rows)
        self.assertEqual(len(found), 1)
        self.assertIn("TFLite_v1", found[0])
        # a row of another page (the internals page lists every tab) is not counted
        other = {"url": "https://example.com/", "declared": "", "detected": "", "by": "", "adopted": ""}
        self.assertEqual(ld.built_in_problems(GOOD + [other]), [])

    def test_the_last_row_of_a_page_counts(self):
        rows = [row("/plain-fr", "", ""), row("/plain-fr", "fr - French", "fr - French")]
        self.assertEqual(ld.row_for(rows, "/plain-fr")["detected"], "fr - French")
        self.assertIsNone(ld.row_for(rows, "/plain-en"))


if __name__ == "__main__":
    unittest.main()
