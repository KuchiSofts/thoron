# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Phishing and malware test pages are blocked, and by what: the online check's decisions (ROADMAP S.14)."""
import unittest

from tools.qa import safe_browsing_check as sb

# what a tab showed in the measurement of 2026-11-16 (Thoron build 158.0.8127.3010)
WARNING = {"title": "Security error", "address": "chrome-error://chromewebdata/", "ready": "complete",
           "kind": "SAFEBROWSING", "error": "net::ERR_BLOCKED_BY_CLIENT"}
OPENED = {"title": "", "address": sb.TEST_SITE + "phishing.html", "ready": "complete", "kind": "", "error": ""}
ADBLOCK_PAGE = {"title": "Thoron blocked this page", "address": "chrome-error://chromewebdata/", "ready": "complete",
                "kind": "", "error": "net::ERR_BLOCKED_BY_CLIENT"}
NO_NETWORK = {"title": "testsafebrowsing.appspot.com", "address": "chrome-error://chromewebdata/",
              "ready": "complete", "kind": "", "error": "net::ERR_NAME_NOT_RESOLVED"}


def result(name: str, by: str, counted: bool = True, **more) -> dict:
    return {"name": name, "address": sb.TEST_SITE + name + ".html", "counted": counted, "by": by, "after": None,
            "detail": "", **more}


class BlockedByTests(unittest.TestCase):
    def test_safe_browsing_s_warning(self):
        self.assertEqual(sb.blocked_by(WARNING), sb.SAFE_BROWSING)
        # a page that sends on to a listed page: the warning comes without an error of the first address
        self.assertEqual(sb.blocked_by({**WARNING, "error": ""}), sb.SAFE_BROWSING)

    def test_thoron_adblock_s_page(self):
        self.assertEqual(sb.blocked_by(ADBLOCK_PAGE), sb.ADBLOCK)

    def test_a_page_that_opened(self):
        self.assertEqual(sb.blocked_by(OPENED), sb.OPEN)

    def test_a_page_that_did_not_load_is_not_called_blocked(self):
        self.assertEqual(sb.blocked_by(NO_NETWORK), sb.UNREACHABLE)
        self.assertEqual(sb.blocked_by({"address": "chrome-error://chromewebdata/"}), sb.UNREACHABLE)
        # another security page of the browser (a bad certificate) is not Safe Browsing's
        self.assertEqual(sb.blocked_by({**WARNING, "kind": "SSL", "error": "net::ERR_CERT_DATE_INVALID"}),
                         sb.UNREACHABLE)

    def test_only_the_two_warnings_count_as_blocked(self):
        self.assertTrue(sb.is_blocked(sb.SAFE_BROWSING))
        self.assertTrue(sb.is_blocked(sb.ADBLOCK))
        self.assertFalse(sb.is_blocked(sb.OPEN))
        self.assertFalse(sb.is_blocked(sb.UNREACHABLE))


class ProblemsTests(unittest.TestCase):
    def test_passes_when_phishing_and_malware_are_blocked_by_either(self):
        found = [result("phishing", sb.SAFE_BROWSING), result("malware", sb.ADBLOCK),
                 result("unwanted", sb.OPEN, counted=False)]
        self.assertEqual(sb.problems(found), [])

    def test_an_open_counted_page_fails(self):
        found = [result("phishing", sb.SAFE_BROWSING), result("malware", sb.OPEN)]
        self.assertEqual(sb.problems(found), ["malware: not blocked"])

    def test_a_page_that_did_not_load_fails_and_says_why(self):
        found = [result("phishing", sb.UNREACHABLE, detail="net::ERR_NAME_NOT_RESOLVED"),
                 result("malware", sb.SAFE_BROWSING)]
        self.assertEqual(len(sb.problems(found)), 1)
        self.assertIn("net::ERR_NAME_NOT_RESOLVED", sb.problems(found)[0])
        self.assertIn("online", sb.problems(found)[0])

    def test_nothing_counted_is_not_a_pass(self):
        self.assertTrue(sb.problems([]))
        self.assertTrue(sb.problems([result("unwanted", sb.SAFE_BROWSING, counted=False)]))


class LineTests(unittest.TestCase):
    def test_names_the_page_who_stopped_it_and_when(self):
        text = sb.line(result("phishing", sb.SAFE_BROWSING, after=219))
        self.assertTrue(text.startswith("BLOCKED"))
        self.assertIn("phishing: safe-browsing, 219 s after the start", text)
        self.assertIn(sb.TEST_SITE + "phishing.html", text)
        self.assertNotIn("not counted", text)

    def test_open_unknown_and_not_counted(self):
        self.assertTrue(sb.line(result("malware", sb.OPEN)).startswith("OPEN"))
        text = sb.line(result("x", sb.UNREACHABLE, counted=False, detail="net::ERR_FAILED"))
        self.assertTrue(text.startswith("UNKNOWN"))
        self.assertIn("(net::ERR_FAILED)", text)
        self.assertIn("[not counted]", text)


class EnvironmentTests(unittest.TestCase):
    BASE = {"PATH": "x", "Google_Api_Key": "from the shell", "GOOGLE_DEFAULT_CLIENT_ID": "id"}

    def test_the_build_s_own_keys_are_measured_unless_asked(self):
        env = sb.child_environment(self.BASE, no_google_keys=False)
        self.assertEqual(env, {"PATH": "x"})

    def test_the_placeholder_takes_the_place_of_every_key(self):
        env = sb.child_environment(self.BASE, no_google_keys=True)
        self.assertEqual({env[name] for name in sb.KEY_VARIABLES}, {sb.PLACEHOLDER})
        self.assertEqual(env["PATH"], "x")
        self.assertNotIn("Google_Api_Key", env)
        self.assertEqual(self.BASE["Google_Api_Key"], "from the shell")  # the caller's own is untouched


class DownloadTests(unittest.TestCase):
    def test_a_saved_file_was_not_stopped(self):
        self.assertEqual(sb.download_outcome(True, {"state": 2, "danger": 0})[0], sb.OPEN)

    def test_a_verdict_of_download_protection(self):
        self.assertEqual(sb.download_outcome(False, {"state": 4, "danger": 6}), (sb.SAFE_BROWSING, "dangerous host"))
        self.assertEqual(sb.download_outcome(False, {"state": 4, "danger": 5}), (sb.SAFE_BROWSING, "uncommon file"))
        self.assertEqual(sb.download_outcome(False, {"state": 4, "danger": 7}), (sb.SAFE_BROWSING, "unwanted app"))

    def test_the_file_type_question_is_not_safe_browsing(self):
        by, detail = sb.download_outcome(False, {"state": 4, "danger": sb.DANGER_FILE_TYPE})
        self.assertEqual(by, sb.OPEN)
        self.assertIn("file type", detail)

    def test_no_download_teaches_nothing(self):
        self.assertEqual(sb.download_outcome(False, None)[0], sb.UNREACHABLE)
        self.assertEqual(sb.download_outcome(False, {"state": 5, "danger": 0})[0], sb.UNREACHABLE)


class PagesTests(unittest.TestCase):
    def test_phishing_and_malware_count_and_nothing_else(self):
        self.assertEqual([name for name, _, counted in sb.PAGES if counted], ["phishing", "malware"])
        self.assertTrue(sb.PAGES[0][2])  # the page that is opened until a list arrived is a counted one

    def test_every_address_is_on_google_s_test_site(self):
        addresses = [address for _, address, _ in sb.PAGES] + [address for _, address in sb.DOWNLOADS]
        self.assertTrue(all(a.startswith("https://testsafebrowsing.appspot.com/s/") for a in addresses))
        self.assertEqual(len(set(addresses)), len(addresses))

    def test_it_says_that_it_is_online(self):
        self.assertIn("ONLINE", sb.__doc__)


if __name__ == "__main__":
    unittest.main()
