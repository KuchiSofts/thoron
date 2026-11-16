# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock, lines that only name a host: the offline check (ROADMAP S.14)."""
import unittest

from tools.qa import adblock_hosts_check as hc

OPEN = {"title": "a page", "text": "a page"}


def blocked(host):
    return {"title": hc.BLOCKED_TITLE, "text": f"Thoron blocked this page\n{host}"}


AFTER = {"plain": blocked(hc.PLAIN), "plain-www": blocked(hc.PLAIN), "hosts-file": blocked(hc.HOSTS_FILE),
         "mention": OPEN, "other": OPEN}


class StepTests(unittest.TestCase):
    def test_the_lines_and_the_pages(self):
        self.assertEqual(hc.LINES.splitlines()[0], hc.PLAIN)
        self.assertTrue(hc.LINES.splitlines()[1].endswith(" " + hc.HOSTS_FILE))
        self.assertEqual(sorted(n for n, (_, stopped) in hc.PAGES.items() if stopped), ["hosts-file", "plain", "plain-www"])
        self.assertIn(hc.PLAIN, hc.PAGES["mention"][0])
        for address, _ in hc.PAGES.values():
            self.assertTrue(address.split("/")[2].endswith(".test"))

    def test_before(self):
        self.assertEqual(hc.before_problems({name: OPEN for name in hc.PAGES}), [])
        self.assertEqual(len(hc.before_problems(AFTER)), 3)

    def test_stopped(self):
        self.assertEqual(hc.stopped_problems(AFTER, [hc.OTHER]), [])
        self.assertEqual(len(hc.stopped_problems({name: OPEN for name in hc.PAGES}, [])), 3)
        self.assertEqual(len(hc.stopped_problems(AFTER, [hc.PLAIN])), 1)
        unnamed = dict(AFTER, plain={"title": hc.BLOCKED_TITLE, "text": "Thoron blocked this page"})
        self.assertEqual(len(hc.stopped_problems(unnamed, [])), 1)

    def test_others(self):
        self.assertEqual(hc.others_problems(AFTER), [])
        self.assertEqual(len(hc.others_problems(dict(AFTER, mention=blocked(hc.OTHER)))), 1)
        self.assertEqual(len(hc.others_problems(dict(AFTER, other={"title": "", "text": ""}))), 1)


if __name__ == "__main__":
    unittest.main()
