# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of sandbox_portable_traces.py that do not need Windows Sandbox."""
import unittest

from tools.qa import sandbox_portable_traces as pt

BEFORE = """Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer]
"Seen"=dword:00000001

[HKEY_CURRENT_USER\\Software\\Other]
"kept"="same"
"""
AFTER = BEFORE.replace('"Seen"=dword:00000001', '"Seen"=dword:00000002') + """
[HKEY_CURRENT_USER\\Software\\Thoron]
"usagestats"=dword:00000000
"long"=hex:01,02,\\
  03,04

[HKEY_CURRENT_USER\\Software\\Thoron\\BLBeacon]
"state"=dword:00000000
"""


class TraceTests(unittest.TestCase):
    def test_a_registry_export_is_read_with_its_long_values(self):
        entries = pt.reg_entries(AFTER)
        self.assertEqual(entries["HKEY_CURRENT_USER\\Software\\Thoron"],
                         {'"usagestats"': "dword:00000000", '"long"': "hex:01,02,03,04"})
        self.assertEqual(entries["HKEY_CURRENT_USER\\Software\\Other"], {'"kept"': '"same"'})

    def test_new_and_changed_keys_and_values(self):
        changes = pt.reg_changes(pt.reg_entries(BEFORE), pt.reg_entries(AFTER))
        self.assertEqual(changes, [
            'changed value HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer "Seen"',
            "new key HKEY_CURRENT_USER\\Software\\Thoron (2 value(s))",
            "new key HKEY_CURRENT_USER\\Software\\Thoron\\BLBeacon (1 value(s))"])
        thorons = [c for c in changes if not pt.WINDOWS_OWN.search(c)]
        self.assertEqual(len(thorons), 2)                       # Explorer's record is Windows' own

    def test_tasks_are_compared_by_name(self):
        before = '"\\Microsoft\\A","18/11/2026 03:05:48","Ready"\n'
        after = '"\\Microsoft\\A","19/11/2026 01:00:00","Ready"\n"\\Thoron\\Update","N/A","Ready"\n'
        self.assertEqual(pt.task_changes(before, after), ["\\Thoron\\Update"])

    def test_the_report(self):
        text = pt.report({"registry": ["new key X"], "registry_windows_own": ["a", "b"], "tasks": [], "folders": []})
        self.assertIn("Registry under HKEY_CURRENT_USER: \n- new key X", text)
        self.assertIn("Scheduled tasks: none", text)
        self.assertIn("2 registry change(s)", text)


if __name__ == "__main__":
    unittest.main()
