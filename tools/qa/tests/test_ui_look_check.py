# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of ui_look_check.py that do not need a browser."""
import unittest

from tools.qa import ui_look_check as ui


class ConfigTests(unittest.TestCase):
    def test_every_ported_option_has_a_picture(self):
        names = [name for name, _ in ui.CONFIGS]
        self.assertEqual(names, ["default", "combo-left", "thorium-2024", "classic-omnibox", "rectangular-tabs",
                                 "tab-width-120", "link-menu"])
        switches = {name: extra for name, extra in ui.CONFIGS}
        self.assertIn("--enable-features=ThoriumLeftAlignedTabStripComboButton", switches["combo-left"])
        self.assertIn("--enable-features=Thorium2024", switches["thorium-2024"])
        self.assertIn("--custom-tab-width=120", switches["tab-width-120"])

    def test_only_the_browsers_own_windows_are_captured(self):
        # the screen is never grabbed: nothing else open on the PC may end up in a picture
        import inspect
        source = inspect.getsource(ui)
        self.assertNotIn("ImageGrab", source)
        self.assertIn("PrintWindow", source)


if __name__ == "__main__":
    unittest.main()
