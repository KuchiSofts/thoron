# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of sandbox_policy_netlog.py that do not need Windows Sandbox."""
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.qa import sandbox_policy_netlog as sp

WITHOUT = {"www.google.com": 2, "update.googleapis.com": 20, "edgedl.me.gvt1.com": 19,
           "safebrowsing.googleapis.com": 1, "clients2.google.com": 1}


class PolicyTests(unittest.TestCase):
    def test_policies_that_switch_their_hosts_off(self):
        self.assertEqual(sp.compare(WITHOUT, {"clients2.google.com": 1}), ([], []))
        self.assertEqual(sp.compare(WITHOUT, {"update.googleapis.com": 3}), ([], []))     # fewer is what it does

    def test_a_host_still_asked_or_never_asked(self):
        problems, _ = sp.compare(WITHOUT, {"update.googleapis.com": 20, "safebrowsing.googleapis.com": 1})
        self.assertEqual(problems, [
            "ComponentUpdatesEnabled: update.googleapis.com was asked as often with the policy (20 against 20)",
            "SafeBrowsingProtectionLevel: safebrowsing.googleapis.com was still asked with the policy (1 request(s))"])
        quiet = {k: v for k, v in WITHOUT.items() if k != "safebrowsing.googleapis.com"}
        problems, notes = sp.compare(quiet, {})
        self.assertEqual(problems, [])
        self.assertEqual(notes, ["SafeBrowsingProtectionLevel: safebrowsing.googleapis.com was not asked even "
                                 "without the policy; nothing to switch off here"])

    def test_the_report_lists_every_host_of_both_runs(self):
        text = sp.report({"a.example": 2}, {"b.example": 1}, 240)
        self.assertIn("| `a.example` | 2 | 0 |", text)
        self.assertIn("| `b.example` | 0 | 1 |", text)
        self.assertIn("`ComponentUpdatesEnabled` = 0", text)

    def test_the_sandbox_is_online_and_the_policies_go_where_thoron_reads_them(self):
        root = ET.fromstring(sp.wsb(Path(r"C:\work")))
        self.assertEqual(root.findtext("Networking"), "Default")
        self.assertIn(r"HKLM:\SOFTWARE\Policies\Chromium", sp.RUN)
        self.assertIn("--log-net-log=$log", sp.RUN)
        self.assertTrue(sp.RUN.rstrip().endswith("Stop-Computer -Force"))


if __name__ == "__main__":
    unittest.main()
