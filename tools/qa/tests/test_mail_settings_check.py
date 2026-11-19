# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of mail_settings_check.py's verdicts (ROADMAP P5.82); the browser itself is driven only by the check."""
import json
import unittest

from tools.qa import mail_settings_check as ms

A, B, LISTED, MADE, TABS = ms.A, ms.B, ms.LISTED, ms.MADE, ms.TABS


def sound(**more):
    return {"names": MADE, "name": "bell", "volume": 40, "held": 0, "last": "", "lastQuiet": "", **more}


class TabsTests(unittest.TestCase):
    GOOD = {"tabs": TABS, **{name: [f"tab-{name}"] for name in TABS}, "address": "#manage/backup",
            "reloaded": ["tab-alerts"]}

    def test_five_tabs_each_with_its_part(self):
        self.assertEqual(ms.tabs_problems(self.GOOD), [])

    def test_what_is_wrong(self):
        self.assertTrue(ms.tabs_problems(dict(self.GOOD, counting=["tab-counting", "tab-display"])))
        self.assertTrue(ms.tabs_problems(dict(self.GOOD, address="#manage")))
        self.assertTrue(ms.tabs_problems(dict(self.GOOD, reloaded=["tab-accounts"])))
        self.assertTrue(ms.tabs_problems(dict(self.GOOD, tabs=TABS[:4])))


class SettingsAndListTests(unittest.TestCase):
    def test_the_settings_button_opens_the_page(self):
        menu = "chrome://mail-notifier.top-chrome/"
        self.assertEqual(ms.settings_problems([menu], [menu, menu + "#manage"]), [])
        self.assertTrue(ms.settings_problems([menu], [menu]))

    def test_each_address_once(self):
        self.assertEqual(ms.list_problems([A, B, LISTED], f"{A}\n{B}\n{LISTED}"), [])
        self.assertTrue(ms.list_problems([A, B, LISTED, A], f"{A}\n{B}\n{LISTED}"))
        self.assertTrue(ms.list_problems([A, B, LISTED], f"{A}\n{B}\n{LISTED}\n{A}"))   # shown twice


class SoundTests(unittest.TestCase):
    def test_every_sound_plays_and_the_choice_is_kept(self):
        heard = {name: name for name in ["system", *MADE]}
        self.assertEqual(ms.sounds_problems({"sound": sound()}, heard, sound()), [])
        self.assertTrue(ms.sounds_problems({"sound": sound(names=MADE[:9])}, heard, sound()))
        self.assertTrue(ms.sounds_problems({"sound": sound()}, dict(heard, pop="system"), sound()))
        self.assertTrue(ms.sounds_problems({"sound": sound()}, heard, sound(volume=70)))

    def test_an_account_with_no_sound_stays_quiet(self):
        before = {"sounds": 3, "sound": sound(held=1)}
        after = {"sounds": 4, "sound": sound(held=2, last="pop", lastQuiet="account", accounts={A: "off", B: "pop"})}
        self.assertEqual(ms.own_problems(before, after), [])
        self.assertTrue(ms.own_problems(before, dict(after, sounds=5)))
        self.assertTrue(ms.own_problems(before, {"sounds": 4, "sound": sound(held=1, last="pop",
                                                                              accounts={A: "off", B: "pop"})}))

    def test_quiet_hours(self):
        before = {"sounds": 4, "notices": 2, "sound": sound(held=2)}
        during = {"sounds": 4, "notices": 2, "sound": sound(held=4, lastQuiet="hours")}
        after = {"sounds": 6, "notices": 4, "sound": sound(held=4)}
        self.assertEqual(ms.quiet_problems(before, during, after), [])
        self.assertTrue(ms.quiet_problems(before, dict(during, sounds=5), after))
        self.assertTrue(ms.quiet_problems(before, dict(during, notices=3), after))
        self.assertTrue(ms.quiet_problems(before, during, dict(after, sounds=4)))

    def test_the_backup_holds_the_sound(self):
        good = {"settings": {"sound": {"name": "bell", "volume": 40, "accounts": {A: "off", B: "pop"},
                                       "quietFullscreen": True, "quietInFront": True, "quietFrom": -1,
                                       "quietTo": -1}}}
        self.assertEqual(ms.backup_problems(json.dumps(good)), [])
        partial = json.loads(json.dumps(good))
        del partial["settings"]["sound"]["quietTo"]
        self.assertTrue(ms.backup_problems(json.dumps(partial)))
        self.assertTrue(ms.backup_problems("not json"))


if __name__ == "__main__":
    unittest.main()
