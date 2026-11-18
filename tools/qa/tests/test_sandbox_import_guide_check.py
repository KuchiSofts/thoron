# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of sandbox_import_guide_check.py that do not need Windows Sandbox."""
import sys
import tempfile
import unittest
from pathlib import Path

from tools.qa import sandbox_import_guide_check as ig

GOOD = {
    "installed": True, "thorium_window": True,
    "detect_running": {"exit": 0, "text": "Thorium (C:\\x\\User Data) (running: close it before an import)\n  Default"},
    "import_running": {"exit": 1, "text": "refused: the source browser is running; close it completely first"},
    "import_too_soon": {"exit": 1, "text": "refused: the source was written a moment ago (x), so its browser may "
                                           "still be closing; wait half a minute and import again"},
    "detect": {"exit": 0, "text": "Thorium (C:\\x\\User Data)\n  Default: Person 1"},
    "import": {"exit": 0, "text": "Imported 1 profile"}, "report": True, "marker_copied": True,
    "thoron_window": True, "marker_kept": True,
    "import_again": {"exit": 1, "text": "refused: C:\\y already holds a profile; nothing was changed"},
    "marker_after_again": True, "done": True}


class ProblemsTests(unittest.TestCase):
    def test_a_run_that_followed_the_guide(self):
        found = ig.problems(GOOD)
        self.assertEqual(sum(len(v) for v in found.values()), 0, found)

    def test_each_step_that_differs_from_the_guide(self):
        cases = [
            ({"detect_running": {"exit": 0, "text": "Thorium\n  Default"}}, "detect, running"),
            ({"import_running": {"exit": 0, "text": ""}}, "import, running"),
            ({"import_too_soon": {"exit": 0, "text": "Imported"}}, "import, too soon"),
            ({"detect": {"exit": 0, "text": "Thorium (running: close it before an import)\n  Default"}}, "detect"),
            ({"import": {"exit": 1, "text": "refused"}}, "import"),
            ({"report": False}, "import"),
            ({"marker_copied": False}, "import"),
            ({"marker_kept": False}, "first start"),
            ({"import_again": {"exit": 0, "text": "Imported"}}, "import, again"),
            ({"marker_after_again": False}, "import, again"),
            ({"installed": False}, "setup"),
        ]
        for change, step in cases:
            with self.subTest(change=change):
                found = ig.problems({**GOOD, **change})
                self.assertEqual(len(found[step]), 1, found)
                self.assertEqual(sum(len(v) for v in found.values()), 1, found)


class PythonCopyTests(unittest.TestCase):
    def test_only_the_interpreter_and_its_standard_library_go_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "python"
            ig.copy_python(dest)
            self.assertTrue((dest / "python.exe").is_file() if sys.platform == "win32" else True)
            self.assertTrue((dest / "Lib" / "sqlite3").is_dir())
            self.assertFalse((dest / "Lib" / "site-packages").exists())
            self.assertFalse(any(dest.rglob("__pycache__")))

    def test_the_tools_are_run_as_the_guide_runs_them(self):
        for command in ("tools\\migrate\\detect.py", "tools\\migrate\\import_profile.py"):
            self.assertIn(command, ig.RUN)
        self.assertIn("(@('-I') + $arguments)", ig.RUN)              # isolated, as `py -3 -I`


if __name__ == "__main__":
    unittest.main()
