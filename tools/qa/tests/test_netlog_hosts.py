# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Hosts a fresh profile contacts, what asks for each and when (ROADMAP S.10, S.15)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.qa import netlog_hosts as nh

LOG = ('{"constants":{},"events":[\n'
       '{"params":{"url":"https://update.googleapis.com/service/update2/json?cup2key=1"},"type":2},\n'
       '{"params":{"host":"clients2.google.com","port":443},"type":3},\n'
       '{"params":{"url":"http://127.0.0.1:5555/page"},"type":2},\n'
       '{"params":{"host":"localhost"},"type":3},\n'
       '{"params":{"url":"chrome://newtab/"},"type":2},\n'
       '{"params":{"url":"https://update.googleapis.com/other"},"type":2},\n'
       '{"params":{"host_port_pair":"accounts.google.com:443"}')   # cut off: the browser was stopped

CONSTANTS = {"logEventTypes": {"REQUEST_ALIVE": 1, "URL_REQUEST_START_JOB": 2, "HTTP_TRANSACTION_SEND_REQUEST_HEADERS": 3,
                               "HTTP_TRANSACTION_READ_RESPONSE_HEADERS": 4, "HOST_RESOLVER_MANAGER_REQUEST": 5,
                               "QUIC_SESSION_PACKET_SENT": 6, "HTTP_TRANSACTION_HTTP2_SEND_REQUEST_HEADERS": 7,
                               "HTTP_STREAM_JOB_CONTROLLER": 8},
             "logSourceType": {"URL_REQUEST": 1, "QUIC_SESSION": 2, "HOST_RESOLVER_IMPL_JOB": 3,
                               "HTTP_STREAM_JOB_CONTROLLER": 4},
             "logEventPhase": {"PHASE_BEGIN": 1, "PHASE_END": 2, "PHASE_NONE": 0},
             "netError": {"ERR_NAME_NOT_RESOLVED": -105}, "timeTickOffset": 1000000}
BEGIN, END = 1, 2
EXTENSION = "abcdefghijklmnopabcdefghijklmnop"       # the shape of an extension's id


def event(kind: str, source: int, ticks: int, phase: int = 0, source_type: str = "URL_REQUEST", **params) -> str:
    """One line of a network log, written the way the browser writes it."""
    line = {"params": params} if params else {}
    line.update({"phase": phase, "source": {"id": source, "start_time": str(ticks),
                                            "type": CONSTANTS["logSourceType"][source_type]},
                 "time": str(ticks), "type": CONSTANTS["logEventTypes"][kind]})
    return json.dumps(line, separators=(",", ":"))


def log(*lines: str, cut: bool = False) -> str:
    text = '{"constants":' + json.dumps(CONSTANTS, separators=(",", ":")) + ',\n"events": [\n' + ",\n".join(lines)
    return text + (',\n{"params":{"url":"https://cut.example/pa' if cut else '],\n"polledData": {}}')


def lookup(host: str, ticks: int) -> str:
    return event("HOST_RESOLVER_MANAGER_REQUEST", 50, ticks, BEGIN, "HOST_RESOLVER_IMPL_JOB", host=host)


def connection(url: str, ticks: int, ahead: bool) -> str:
    return event("HTTP_STREAM_JOB_CONTROLLER", 60, ticks, BEGIN, "HTTP_STREAM_JOB_CONTROLLER", is_preconnect=ahead,
                 url=url)


SIGN_IN = nh.annotation_hash("gaia_auth_list_accounts")
REQUESTS = (
    lookup("wpad:80", 4000),
    event("REQUEST_ALIVE", 1, 5000, BEGIN, traffic_annotation=SIGN_IN, url="https://accounts.google.com/ListAccounts"),
    event("URL_REQUEST_START_JOB", 1, 5000, BEGIN, method="POST", initiator="not an origin",
          url="https://accounts.google.com/ListAccounts?gpsia=1&source=ChromiumBrowser"),
    lookup("https://accounts.google.com:443", 5001),
    event("HTTP_TRANSACTION_HTTP2_SEND_REQUEST_HEADERS", 1, 5010, headers=[":method: POST"]),
    event("HTTP_TRANSACTION_READ_RESPONSE_HEADERS", 1, 5100, headers=["HTTP/1.1 200", "content-type: text/plain"]),
    event("REQUEST_ALIVE", 2, 5200, BEGIN, traffic_annotation=424242, url="http://first.example/a"),
    event("URL_REQUEST_START_JOB", 2, 5200, BEGIN, method="GET", url="http://first.example/a?x=1",
          initiator=f"chrome-extension://{EXTENSION}"),
    event("HTTP_TRANSACTION_SEND_REQUEST_HEADERS", 2, 5210, headers=["Host: first.example"]),
    event("HTTP_TRANSACTION_READ_RESPONSE_HEADERS", 2, 5300, headers=["HTTP/1.1 302 Found"]),
    event("URL_REQUEST_START_JOB", 2, 5310, BEGIN, method="GET",
          url=f"https://second.example:8443/v2/items/{EXTENSION}:fetchItemSnippet"),
    event("URL_REQUEST_START_JOB", 2, 5400, END, net_error=-105),
    # most of a real log: skipped without being parsed, so it may even be broken inside
    '{"params":{broken,"phase":0,"source":{"id":9,"start_time":"5450","type":2},"time":"5450","type":6}',
    event("REQUEST_ALIVE", 3, 5500, BEGIN, traffic_annotation=1, url="http://127.0.0.1:5555/page"),
    event("URL_REQUEST_START_JOB", 3, 5500, BEGIN, method="GET", url="http://127.0.0.1:5555/page"),
    lookup("http://127.0.0.1:5555", 5500),
    lookup("thispc", 5600),
    lookup("10.0.0.5:8009", 5700),
    connection("https://www.google.com/", 5800, ahead=True),
    lookup("https://www.google.com", 5800),
    connection("https://accounts.google.com/ListAccounts", 5000, ahead=False),     # a request's own connection
    connection("http://127.0.0.1:5555/", 5900, ahead=True),
    connection("https://www.google.com/", 65800, ahead=True),
)


class HostsTests(unittest.TestCase):
    def test_external_hosts_from_a_truncated_log(self):
        self.assertEqual(nh.hosts(LOG), {"update.googleapis.com": 2, "clients2.google.com": 1,
                                         "accounts.google.com": 1})

    def test_scheme_and_port_forms_are_one_host(self):
        log = ('{"params":{"host":"https://accounts.google.com"}},{"params":{"host":"accounts.google.com:443"}},'
               '{"params":{"host":"http://127.0.0.1:34519"}},{"params":{"host":"optimizationguide-pa.googleapis.com:443"}}')
        self.assertEqual(nh.hosts(log), {"accounts.google.com": 2, "optimizationguide-pa.googleapis.com": 1})

    def test_local_and_internal_are_ignored(self):
        found = nh.hosts(LOG)
        for local in ("127.0.0.1", "localhost", "newtab"):
            self.assertNotIn(local, found)

    def test_an_address_of_the_local_network_is_counted_but_not_shown(self):
        text = ('{"params":{"url":"http://10.0.0.5:8009/setup"}},{"params":{"host":"[fe80::1]:80"}},'
                '{"params":{"host":"[::1]:9222"}},{"params":{"host":"0.0.0.0"}},{"params":{"host":"93.184.216.34:443"}}')
        self.assertEqual(nh.hosts(text), {nh.LOCAL_NETWORK: 2, "93.184.216.34": 1})

    def test_markdown(self):
        md = nh.to_markdown({"update.googleapis.com": 2}, "Thoron 158", 120)
        self.assertIn("| update.googleapis.com | 2 |", md)
        self.assertIn("120 s", md)


class AnnotationTests(unittest.TestCase):
    def test_numbers_are_the_ones_the_browser_logs(self):
        # read from a Thoron 158 log: the request for /time/1/current and the filter list downloads
        self.assertEqual(nh.annotation_hash("network_time_component"), 46188932)
        self.assertEqual(nh.annotation_hash("thoron_adblock_lists"), 117366115)
        self.assertEqual(nh.ANNOTATIONS[46188932], "network_time_component")

    def test_table_of_a_chromium_checkout(self):
        xml = ('<annotations>\n <item id="update_client" added_in_milestone="120" content_hash_code="0123abcd"'
               ' os_list="linux,windows" file_path="components/update_client/net/network_impl.cc" />\n'
               ' <item id="old_one" added_in_milestone="62" type="partial" />\n</annotations>')
        names = nh.load_annotations(xml)
        self.assertEqual(names[nh.annotation_hash("update_client")],
                         "update_client (components/update_client/net/network_impl.cc)")
        self.assertEqual(names[nh.annotation_hash("old_one")], "old_one")


class DigestTests(unittest.TestCase):
    def test_requests_with_who_asked_when_and_the_answer(self):
        found = nh.digest(log(*REQUESTS))["requests"]
        self.assertEqual([r["host"] for r in found], ["accounts.google.com", "first.example", "second.example"])
        first, redirect, target = found
        self.assertEqual(first, {"host": "accounts.google.com", "at": 1.0, "asked_by": "gaia_auth_list_accounts",
                                 "method": "POST", "path": "/ListAccounts", "initiator": "not an origin",
                                 "sent": True, "answer": "200"})
        self.assertEqual((redirect["asked_by"], redirect["path"], redirect["answer"], redirect["sent"]),
                         ("annotation 424242", "/a", "302", True))
        self.assertEqual(redirect["initiator"], "chrome-extension://<id>")
        self.assertEqual((target["path"], target["answer"], target["sent"], target["at"]),
                         ("/v2/items/<id>:fetchItemSnippet", "ERR_NAME_NOT_RESOLVED", False, 1.3))

    def test_times_count_from_the_launch_when_it_is_known(self):
        launched = (CONSTANTS["timeTickOffset"] + 3000) / 1000          # one second before the first event
        self.assertEqual(nh.digest(log(*REQUESTS), launched=launched)["requests"][0]["at"], 2.0)

    def test_names_only_looked_up(self):
        self.assertEqual(nh.digest(log(*REQUESTS))["lookups"],
                         {"wpad": 1, nh.SINGLE_LABEL: 1, nh.LOCAL_NETWORK: 1, "www.google.com": 1})

    def test_connections_opened_before_any_request(self):
        self.assertEqual(nh.digest(log(*REQUESTS))["preconnects"],
                         [{"host": "www.google.com", "at": 1.8}, {"host": "www.google.com", "at": 61.8}])

    def test_a_log_cut_off_loses_only_its_last_line(self):
        self.assertEqual(len(nh.digest(log(*REQUESTS, cut=True))["requests"]), 3)

    def test_more_names_can_be_given(self):
        found = nh.digest(log(*REQUESTS), names={424242: "some_caller (a/file.cc)"})["requests"]
        self.assertEqual(found[1]["asked_by"], "some_caller (a/file.cc)")

    def test_a_log_without_constants_has_no_requests(self):
        self.assertEqual(nh.digest(LOG), {"requests": [], "lookups": {}, "preconnects": []})
        self.assertEqual(nh.digest(""), {"requests": [], "lookups": {}, "preconnects": []})


class PublishableTests(unittest.TestCase):
    def test_ids_and_opaque_parts_leave_a_path(self):
        self.assertEqual(nh.path_shown(f"/crx/blobs/{'A1b2' * 20}/{EXTENSION.upper()}_6_42_1_0.crx"),
                         "/crx/blobs/<...>/<id>.crx")
        self.assertEqual(nh.path_shown(f"/edgedl/diffgen-puffin/{EXTENSION}/1f2e"), "/edgedl/diffgen-puffin/<id>/1f2e")
        self.assertEqual(nh.path_shown("/mail/u/0/feed/atom"), "/mail/u/0/feed/atom")
        self.assertEqual(nh.path_shown(""), "/")

    def test_nothing_of_the_log_that_names_the_pc_is_in_the_report(self):
        run = {"hosts": nh.hosts(log(*REQUESTS)), **nh.digest(log(*REQUESTS)), "arrived": {}}
        text = json.dumps(run) + nh.detail_markdown([run])
        for private in (EXTENSION, "10.0.0.5", "thispc", "gpsia", "x=1"):
            self.assertNotIn(private, text)


class ProfileTests(unittest.TestCase):
    def test_components_that_arrived(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder, text in (("CertificateRevocation/10300", '{"name": "crl-set", "version": "10300"}'),
                                 ("Broken/1", "{not json"), ("NoVersion/1", '{"name": "x"}')):
                (root / folder).mkdir(parents=True)
                (root / folder / "manifest.json").write_text(text, encoding="utf-8")
            (root / "Default").mkdir()
            (root / "Default" / "Preferences").write_text("{}", encoding="utf-8")
            self.assertEqual(nh.arrived(root), {"CertificateRevocation": "10300"})

    def test_preferences_a_profile_starts_with(self):
        with tempfile.TemporaryDirectory() as tmp:
            nh.seed_prefs(Path(tmp), {"signin.allowed_on_next_startup": False, "signin.allowed": False, "plain": 2})
            data = json.loads((Path(tmp) / "Default" / "Preferences").read_text(encoding="utf-8"))
        self.assertEqual(data, {"signin": {"allowed_on_next_startup": False, "allowed": False}, "plain": 2})

    def test_preference_arguments(self):
        self.assertEqual(nh._pref("signin.allowed=false"), ("signin.allowed", False))
        self.assertEqual(nh._pref("a.b=text"), ("a.b", "text"))
        with self.assertRaises(nh.argparse.ArgumentTypeError):
            nh._pref("no-value")


class CaptureTests(unittest.TestCase):
    def _capture(self, work: Path, **more) -> tuple[dict, dict]:
        seen = {}

        def launch(browser, profile, args):
            seen["args"] = args
            seen["prefs"] = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
            written = Path(next(a for a in args if a.startswith("--log-net-log=")).split("=", 1)[1])
            written.write_text(log(*REQUESTS), encoding="utf-8")
            (profile / "OriginTrials" / "1.0").mkdir(parents=True)
            (profile / "OriginTrials" / "1.0" / "manifest.json").write_text('{"version": "1.0"}', encoding="utf-8")
            return mock.Mock(pid=4242)

        def stop(proc, profile):       # as when a file is still held: the folder is not gone yet
            seen["stopped"] = proc.pid

        with mock.patch.object(nh, "_launch", side_effect=launch), mock.patch.object(nh, "_stop", side_effect=stop), \
                mock.patch.object(nh.time, "sleep"), contextlib.redirect_stderr(io.StringIO()):
            run = nh.capture(Path("thoron.exe"), work, 5, ("--disable-features=X",), {"a.b": 1}, **more)
        return run, seen

    def test_a_run_reads_the_log_and_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, seen = self._capture(Path(tmp) / "work")
            self.assertEqual(list((Path(tmp) / "work").iterdir()), [])        # no profile, no raw log
        self.assertEqual(seen["stopped"], 4242)
        self.assertEqual(seen["prefs"], {"a": {"b": 1}})
        self.assertIn("--disable-features=X", seen["args"])
        self.assertLess(seen["args"].index(nh.OWN_DOWNLOADS), seen["args"].index("--disable-features=X"))
        self.assertTrue(seen["args"][-1].startswith("http://127.0.0.1:"))
        self.assertEqual(run["arrived"], {"OriginTrials": "1.0"})
        self.assertEqual(len(run["requests"]), 3)
        self.assertEqual(len(run["preconnects"]), 2)
        self.assertEqual(run["hosts"]["accounts.google.com"], 4)          # every mention in the log

    def test_the_raw_log_is_kept_only_when_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._capture(Path(tmp) / "work", keep_log=True)
            self.assertEqual([p.suffix for p in (Path(tmp) / "work").iterdir()], [".json"])

    def test_another_page_can_be_opened_instead_of_the_local_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, seen = self._capture(Path(tmp) / "work", page="chrome://newtab/")
        self.assertEqual(seen["args"][-1], "chrome://newtab/")
        self.assertFalse(any(arg.startswith("http://127.0.0.1") for arg in seen["args"]))

    def test_no_log_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(nh, "_launch", return_value=mock.Mock(pid=1)), \
                mock.patch.object(nh, "_stop"), mock.patch.object(nh.time, "sleep"):
            with self.assertRaises(RuntimeError):
                nh.capture(Path("thoron.exe"), Path(tmp) / "work", 5)


def run_of(*requests: tuple, lookups: dict | None = None, arrived: dict | None = None, ahead: tuple = ()) -> dict:
    found = [{"host": host, "at": at, "asked_by": by, "method": "GET", "path": path, "initiator": "",
              "sent": True, "answer": answer} for host, at, by, path, answer in requests]
    return {"hosts": {r["host"]: 3 for r in found}, "requests": found, "lookups": lookups or {},
            "preconnects": [{"host": "www.google.com", "at": at} for at in ahead], "arrived": arrived or {}}


RUNS = [run_of(("mail.google.com", 15.2, "thoron_mail_feed", "/mail/u/0/feed/atom", "401"),
               ("mail.google.com", 135.2, "thoron_mail_feed", "/mail/u/0/feed/atom", "401"),
               ("www.google.com", 0.4, "aim_eligibility_fetch", "/async/folae", "200"),
               lookups={"wpad": 7}, arrived={"OriginTrials": "1.0"}, ahead=(0.4, 0.6, 60.5)),
        run_of(("mail.google.com", 15.6, "thoron_mail_feed", "/mail/u/0/feed/atom", ""),
               arrived={"OriginTrials": "1.0", "Crowd Deny": "2"})]


class ReportTests(unittest.TestCase):
    def test_by_host_over_several_runs(self):
        table = nh.by_host(RUNS)
        self.assertEqual(table["mail.google.com"], {"runs": 2, "requests": [2, 1], "first": [15.2, 15.6],
                                                    "asked_by": {"thoron_mail_feed": 3},
                                                    "paths": {"GET /mail/u/0/feed/atom": 3},
                                                    "answers": {"401": 2, "no answer": 1}})
        self.assertEqual((table["www.google.com"]["runs"], table["www.google.com"]["requests"]), (1, [1]))

    def test_markdown_of_the_requests(self):
        md = nh.detail_markdown(RUNS)
        self.assertIn("| www.google.com | 1 | 1 | 0.4 | `aim_eligibility_fetch` (1) | `GET /async/folae` (1) | `200` (1) |",
                      md)
        self.assertIn("| mail.google.com | 2 | 1 to 2 | 15.2 to 15.6 | `thoron_mail_feed` (3) |", md)
        self.assertLess(md.index("www.google.com"), md.index("mail.google.com"))      # in the order they are asked
        self.assertIn("Looked up without a request: `wpad` (in 1 of 2)", md)
        self.assertIn("Connected to before any request (preconnect): `www.google.com` (in 1 of 2, 3 a run, "
                      "first at 0.4)", md)
        self.assertIn("Crowd Deny (in 1 of 2), OriginTrials (in 2 of 2)", md)
        self.assertIn("| (none) | 0 |", nh.detail_markdown([run_of()]))

    def test_hosts_that_had_to_stay_away(self):
        self.assertEqual(nh.contacted(RUNS, ["WWW.google.com", "accounts.google.com"]), ["www.google.com"])
        self.assertEqual(nh.contacted(RUNS, []), [])


class MainTests(unittest.TestCase):
    ARGS = ["--browser", "thoron.exe", "--work", "work", "--seconds", "5", "--runs", "2",
            "--switch=--disable-features=AimServerEligibilityEnabled", "--pref", "signin.allowed=false"]

    def _main(self, extra: list[str]) -> tuple[int, str, mock.Mock]:
        out = io.StringIO()
        with mock.patch.object(nh, "capture", side_effect=RUNS) as capture, contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            status = nh.main(self.ARGS + extra)
        return status, out.getvalue(), capture

    def test_runs_switches_and_preferences_reach_the_browser(self):
        status, text, capture = self._main([])
        self.assertEqual(status, 0)
        self.assertEqual(capture.call_count, 2)
        self.assertEqual(capture.call_args.args[2:5], (5.0, ("--disable-features=AimServerEligibilityEnabled",),
                                                       {"signin.allowed": False}))
        self.assertIn("| mail.google.com | 6 |", text)                   # log entries of both runs
        self.assertIn("## Requests", text)
        self.assertIn("one local page", text)

    def test_the_report_names_the_page_that_was_opened(self):
        status, text, capture = self._main(["--page", "chrome://newtab/"])
        self.assertEqual((status, capture.call_args.args[7]), (0, "chrome://newtab/"))
        self.assertIn("the page `chrome://newtab/`, 5 s", text)

    def test_a_host_that_must_be_absent_fails_the_run(self):
        self.assertEqual(self._main(["--absent", "www.google.com"])[0], 1)
        self.assertEqual(self._main(["--absent", "optimizationguide-pa.googleapis.com"])[0], 0)

    def test_the_measurement_is_written_run_by_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved_to, report = Path(tmp) / "out" / "hosts.json", Path(tmp) / "hosts.md"
            status, _, _ = self._main(["--json", str(saved_to), "--md", str(report)])
            saved = json.loads(saved_to.read_text(encoding="utf-8"))
            self.assertTrue(report.read_text(encoding="utf-8").startswith("# Hosts contacted"))
        self.assertEqual(status, 0)
        self.assertEqual((len(saved["runs"]), saved["seconds"], saved["prefs"]), (2, 5.0, {"signin.allowed": False}))

    def test_a_browser_that_wrote_no_log_is_an_error(self):
        with mock.patch.object(nh, "capture", side_effect=RuntimeError("the browser wrote no network log")), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(nh.main(self.ARGS), 1)
        self.assertIn("no network log", err.getvalue())


if __name__ == "__main__":
    unittest.main()
