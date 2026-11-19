# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of launcher_variants_check.py that do not need the launcher."""
import unittest

from tools.qa import launcher_variants_check as lv


class JudgeTests(unittest.TestCase):
    def test_a_start_says_nothing_and_a_refusal_says_why(self):
        self.assertTrue(lv.judge(0, "", 0, None))
        self.assertFalse(lv.judge(0, "a message", 0, None))
        self.assertTrue(lv.judge(3, "made for processors with AVX-512", 3, "AVX-512"))
        self.assertFalse(lv.judge(3, "", 3, "AVX-512"))
        self.assertFalse(lv.judge(0, "", 3, "AVX-512"))

    def test_every_known_variant_and_every_refusal_is_a_case(self):
        texts = {text for text, *_ in lv.CASES}
        for name in ("win-x64-avx2\n", "win-x64-sse4\n", "win-x64-avx512\n", None):
            self.assertIn(name, texts)
        self.assertTrue(any(want == 3 and words == "does not know" for *_, want, words in lv.CASES))
        self.assertTrue(any(want == 3 and words == "too old" for *_, want, words in lv.CASES))


if __name__ == "__main__":
    unittest.main()
