# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock's words in Settings, translated: the offline check (ROADMAP P5.16)."""
import unittest

from tools.qa import adblock_strings_check as sc


class StepTests(unittest.TestCase):
    def test_the_languages(self):
        self.assertEqual(set(sc.WANT), {"es", "fr", "de", "pt-BR", "pt-PT", "ru"})

    def test_a_translated_page_passes(self):
        text = "Ajustes\nAnuncios y rastreadores\nLos anuncios y muchos rastreadores se bloquean antes de cargarse"
        self.assertEqual(sc.language_problems("es", text), [])

    def test_english_or_missing_text_fails(self):
        english = "Ads and trackers\nAds and many trackers are blocked before they load"
        self.assertEqual(len(sc.language_problems("es", english)), 4)
        self.assertEqual(len(sc.language_problems("ru", "Реклама и трекеры")), 1)


if __name__ == "__main__":
    unittest.main()
