# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron's Linux package on clean Ubuntu machines (ROADMAP P2.4, P2.9, P2.21): the reading of a machine's
results."""
import tempfile
import unittest
from pathlib import Path

from tools.qa import linux_package_check as check

SANDBOX = """Sandbox Status
Layer 1 Sandbox  Namespace
PID namespaces  Yes
Network namespaces  Yes
Seccomp-BPF sandbox  Yes
Seccomp-BPF sandbox supports TSYNC  Yes
Ptrace Protection  Yes
You are adequately sandboxed."""


def write(folder: Path, files: dict) -> None:
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")


def good() -> dict:
    return {
        "reached": "done", "install_exit": "0", "upstream_exit": "0", "upgrade_exit": "0", "lintian_exit": "0",
        "files.txt": "/.\n/opt\n/opt/kuchisofts/thoron\n/opt/kuchisofts/thoron/thoron\n"
                     "/opt/kuchisofts/thoron/resources.pak\n/usr/share/applications/thoron.desktop\n"
                     "/usr/share/doc/thoron-browser/copyright\n",
        "upstream-files.txt": "/.\n/opt\n/opt/chromium.org/thorium/thorium\n"
                              "/usr/share/applications/thorium-browser.desktop\n",
        "regular-files.txt": "/opt/kuchisofts/thoron/thoron\n/opt/kuchisofts/thoron/resources.pak\n"
                             "/usr/share/applications/thoron.desktop\n",
        "upstream-regular-files.txt": "/opt/chromium.org/thorium/thorium\n"
                                      "/usr/share/applications/thorium-browser.desktop\n",
        "which-thoron.txt": "/usr/bin/thoron", "which-thorium.txt": "/usr/bin/thorium-browser",
        "desktop.txt": "thoron.desktop\nthorium-browser.desktop\n",
        "thoron-ran": "running", "thorium-ran": "running", "thoron-again-ran": "running",
        "config-dirs.txt": "thoron\nthorium\n", "sandbox.txt": SANDBOX, "lintian.txt": "W: a warning only\n",
        "version.txt": "158.0.8127.6504-1", "version-after.txt": "158.0.8127.6504-1+upgradetest1",
        "profile-kept": "same", "remove_exit": "0", "after-remove.txt": "profile",
    }


class ProblemsTests(unittest.TestCase):
    def found(self, changes: dict | None = None, online: bool = False) -> dict:
        with tempfile.TemporaryDirectory() as d:
            files = {**good(), **(changes or {})}
            write(Path(d), {k: v for k, v in files.items() if v is not None})
            return check.problems(Path(d), online)

    def test_a_good_machine_passes(self):
        self.assertEqual({k: v for k, v in self.found().items() if v}, {})

    def test_each_failure_is_named_in_its_step(self):
        cases = {
            "install": {"install_exit": "100"},
            "names": {"files.txt": good()["files.txt"] + "/opt/kuchisofts/thoron/thorium_shell\n"},
            "coexists": {"config-dirs.txt": "thoron\n"},
            "sandbox": {"sandbox.txt": SANDBOX.replace("You are adequately", "You are not adequately")},
            "lintian": {"lintian.txt": "E: thoron-browser: something wrong\n"},
            "upgrade": {"profile-kept": "changed"},
            "remove": {"after-remove.txt": "program\nprofile"},
        }
        for step, change in cases.items():
            with self.subTest(step):
                self.assertTrue(self.found(change)[step], step)

    def test_a_file_both_packages_own_is_found(self):
        shared = good()["upstream-regular-files.txt"] + "/usr/share/applications/thoron.desktop\n"
        self.assertTrue(self.found({"upstream-regular-files.txt": shared})["coexists"])

    def test_widevine_counts_only_online(self):
        self.assertNotIn("widevine", self.found())
        self.assertTrue(self.found({"widevine_exit": "1"}, online=True)["widevine"])
        self.assertFalse(self.found({"widevine_exit": "0"}, online=True)["widevine"])

    def test_a_stopped_run_says_where(self):
        self.assertIn("lintian", " ".join(self.found({"reached": "lintian"})["install"]))


class HelpersTests(unittest.TestCase):
    def test_paths_and_pages(self):
        self.assertEqual(check.wsl_path(Path(r"C:\thoron-build\qa work\x.deb")), "/mnt/c/thoron-build/qa work/x.deb")
        self.assertEqual(check.sandbox_on(SANDBOX), [])
        self.assertEqual(len(check.sandbox_on("")), 1)
        self.assertEqual(check.lintian_errors("W: x\nE: y\nI: z"), ["E: y"])
        self.assertEqual(check.owned_files("/opt/a/b.so\n/usr/bin/thoron\n"), {"/opt/a/b.so", "/usr/bin/thoron"})


if __name__ == "__main__":
    unittest.main()
