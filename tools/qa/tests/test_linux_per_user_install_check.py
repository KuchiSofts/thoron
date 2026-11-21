# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests for tools/qa/linux_per_user_install_check.py: what its results mean."""
import unittest

from tools.qa import linux_per_user_install_check as c

BEFORE = "./.bashrc\n./.profile\n"
GOOD = {
    "deps_exit": "0", "install_exit": "0", "dest.txt": "Application\nREADME.txt\ninstall-for-this-user\nper-user\n"
    "thoron\nvariant\n", "timer-enabled.txt": "enabled\n", "timers.txt": "... thoron-update.timer thoron-update.service",
    "service_exit": "0", "service_seconds": "1", "service-show.txt": "Result=success\nExecMainStatus=0\n",
    "profiles.txt": "/home/tester/.config/thoron-headless\n", "dest-after-start.txt": "Application\nthoron\n",
    "remove_exit": "0", "timers-after.txt": "0 timers listed.", "before.txt": BEFORE,
    "after.txt": BEFORE + "./.config\n./.config/thoron-headless\n./.config/thoron-headless/Default\n./.local\n"
                 "./.local/share\n./.local/share/pki\n./.local/share/pki/nssdb\n",
}


class ProblemsTest(unittest.TestCase):
    def found(self, **changes) -> dict:
        files = dict(GOOD, **changes)
        return c.problems(lambda name: files.get(name, ""))

    def test_a_good_run_has_none(self):
        self.assertEqual({k: v for k, v in self.found().items() if v}, {})

    def test_each_failure_lands_in_its_step(self):
        for step, change in (
                ("no admin", {"sudo-asked.txt": "sudo apparmor_parser -r x"}),
                ("install", {"timer-enabled.txt": "disabled"}),
                ("install", {"dest.txt": GOOD["dest.txt"] + "User Data\n"}),
                ("timer run", {"service-show.txt": "Result=exit-code\nExecMainStatus=127\n"}),
                ("profile", {"dest-after-start.txt": "Application\nUser Data\n"}),
                ("removed", {"after.txt": GOOD["after.txt"] + "./.local/share/thoron\n"})):
            got = self.found(**change)
            self.assertEqual([s for s, v in got.items() if v], [step], change)


if __name__ == "__main__":
    unittest.main()
