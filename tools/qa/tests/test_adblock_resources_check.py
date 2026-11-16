# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Signed updates of Thoron adblock's scriptlets: the offline check (ROADMAP P5.23)."""
import base64
import json
import tempfile
import unittest
from pathlib import Path

from tools.qa import adblock_resources_check as rc
from tools.release import adblock_resources as ar

SHIPPED = json.dumps([{"name": "noop.js", "aliases": [], "kind": {"mime": "application/javascript"},
                       "content": base64.b64encode(b"(function() {})();").decode("ascii")}])


class StepTests(unittest.TestCase):
    def test_the_marking_scriptlet_is_added(self):
        items = json.loads(rc.with_mark(SHIPPED, "A"))
        self.assertEqual([i["name"] for i in items], ["noop.js", "thoron-resources-mark.js"])
        self.assertIn(b"'A'", base64.b64decode(items[-1]["content"]))

    def test_a_forged_file_no_longer_verifies(self):
        private, public = ar.keygen()
        signed = ar.sign(rc.with_mark(SHIPPED, "A"), rc.NEW, private)
        self.assertEqual(ar.verify(signed, public), rc.NEW)
        self.assertIsNone(ar.verify(rc.forge(signed), public))

    def test_the_stored_serial(self):
        with tempfile.TemporaryDirectory() as d:
            profile = Path(d)
            self.assertIsNone(rc.stored_serial(profile))
            (profile / "Thoron Adblock").mkdir()
            (profile / "Thoron Adblock" / "resources.signed").write_text(
                "thoron-adblock-resources 1\nserial: 2026120200\nsignature: x\n\n[]", encoding="utf-8")
            self.assertEqual(rc.stored_serial(profile), "2026120200")

    def test_step_problems(self):
        self.assertEqual(rc.step_problems("s", "A", "A", "1", "1"), [])
        self.assertEqual(len(rc.step_problems("s", None, "A", None, "1")), 2)


if __name__ == "__main__":
    unittest.main()
