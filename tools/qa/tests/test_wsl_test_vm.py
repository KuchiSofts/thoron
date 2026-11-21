# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of wsl_test_vm.py that need no WSL: only test machines are ever named."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.qa import wsl_test_vm as vm


class NamesTest(unittest.TestCase):
    def test_only_test_machines(self):
        for name in vm.MACHINES:
            self.assertEqual(vm.checked_name(name), name)
        for name in ("Ubuntu", "Ubuntu-24.04", "docker-desktop", "thoron-test-", "thoron-test-24 04",
                     "thoron-test-../x", "THORON-TEST-2404", "xthoron-test-2404"):
            with self.assertRaises(vm.VmError, msg=name):
                vm.checked_name(name)

    def test_restore_refuses_a_person_distribution_before_any_call(self):
        with mock.patch.object(vm, "_wsl") as wsl, tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(vm.VmError):
                vm.restore(Path(tmp), "Ubuntu")
            wsl.assert_not_called()

    def test_restore_needs_its_snapshot(self):
        with mock.patch.object(vm, "_wsl") as wsl, tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(vm.VmError):
                vm.restore(Path(tmp), "thoron-test-2404")
            wsl.assert_not_called()

    def test_text(self):
        self.assertEqual(vm._text("abc".encode("utf-16-le")), "abc")
        self.assertEqual(vm._text(b"tester\n"), "tester\n")


if __name__ == "__main__":
    unittest.main()
