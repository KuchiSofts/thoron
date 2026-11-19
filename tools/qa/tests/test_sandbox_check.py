# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Sandbox verification (ROADMAP S.5): the three witnesses and the negative control."""
import copy
import os
import unittest
from pathlib import Path
from unittest import mock

from tools.qa import sandbox_check as sc

LOCKED = ["strict handle checks", "win32k lockdown", "no extension points", "no child processes"]
NETWORK = "thoron.exe --type=utility --utility-sub-type=network.mojom.NetworkService --service-sandbox-type=none"
STORAGE = "thoron.exe --type=utility --utility-sub-type=storage.mojom.StorageService --service-sandbox-type=service"


def facts(integrity=0x0000, restricted=True, appcontainer=False, privileges=0, in_job=True, mitigations=LOCKED):
    return {"integrity": integrity, "restricted": restricted, "appcontainer": appcontainer,
            "privileges": privileges, "in_job": in_job, "mitigations": list(mitigations)}


def proc(pid, kind, cmd, **changes):
    return {"pid": pid, "type": kind, "cmd": cmd, "facts": facts(**changes)}


def free(pid, kind, cmd, in_job=False):
    """A process with the browser's own rights: what every child is without the sandbox."""
    return proc(pid, kind, cmd, integrity=0x2000, restricted=False, privileges=5, in_job=in_job, mitigations=[])


HEADER = ["Process", "Type", "Name", "Sandbox", "Lockdown", "Integrity", "Mitigations", "Component Filter",
          "Lowbox/AppContainer"]


def sandbox_on():
    procs = [free(10, "browser", "thoron.exe --headless=new about:blank"),
             free(11, "other", "thoron.exe --type=crashpad-handler"),
             proc(12, "gpu", "thoron.exe --type=gpu-process", integrity=0x1000, privileges=1,
                  mitigations=["no extension points"]),
             free(13, "utility", NETWORK, in_job=True),
             proc(14, "utility", STORAGE),
             proc(15, "renderer", "thoron.exe --type=renderer"),
             proc(16, "renderer", "thoron.exe --type=renderer --extension-process")]
    table = [HEADER,
             ["12", "GPU", "GPU", "GPU", "Limited", "S-1-16-4096 Low", "0111", "0001", ""],
             ["13", "Utility", "Network Service", "Not Sandboxed", "", "", "", "", ""],
             ["14", "Utility", "Storage Service", "Service", "Lockdown", "S-1-16-0 Untrusted", "0111", "0001", ""],
             ["15", "Renderer", "", "Renderer", "Lockdown", "S-1-16-0 Untrusted", "0111", "0001", ""],
             ["16", "Renderer", "", "Renderer", "Lockdown", "S-1-16-0 Untrusted", "0111", "0001", ""]]
    return {"procs": procs, "rows": sc.parse_rows(table), "gpu": True, "browser": "Thoron/1.2.3",
            "features": ["NetworkServiceSandbox: off"]}


def sandbox_off():
    switch = " --no-sandbox"
    procs = [free(10, "browser", "thoron.exe --headless=new --no-sandbox about:blank"),
             free(12, "gpu", "thoron.exe --type=gpu-process" + switch),
             free(13, "utility", NETWORK + switch, in_job=True),
             free(14, "utility", STORAGE + switch),
             free(15, "renderer", "thoron.exe --type=renderer" + switch)]
    table = [HEADER] + [[str(pid), kind, "", "Not Sandboxed", "", "", "", "", ""]
                        for pid, kind in ((12, "GPU"), (13, "Utility"), (14, "Utility"), (15, "Renderer"))]
    return {"procs": procs, "rows": sc.parse_rows(table), "gpu": False, "browser": "Thoron/1.2.3", "features": []}


def changed(pid, **changes):
    seen = sandbox_on()
    next(p for p in seen["procs"] if p["pid"] == pid)["facts"].update(changes)
    return seen


class ReadingTests(unittest.TestCase):
    def test_table_of_the_sandbox_page(self):
        rows = sandbox_on()["rows"]
        self.assertEqual([r["pid"] for r in rows], [12, 13, 14, 15, 16])
        self.assertEqual(rows[0], {"pid": 12, "type": "GPU", "name": "GPU", "sandbox": "GPU", "lockdown": "Limited",
                                   "integrity": "S-1-16-4096 Low", "rid": 0x1000})
        self.assertEqual((rows[1]["sandbox"], rows[1]["rid"]), ("Not Sandboxed", None))
        self.assertEqual(rows[3]["rid"], 0)

    def test_table_with_other_columns_or_nothing(self):
        moved = [["Integrity", "Sandbox", "Process"], ["S-1-16-0 Untrusted", "Renderer", "7"], ["", "", "total"]]
        self.assertEqual(sc.parse_rows(moved), [{"pid": 7, "type": "", "name": "", "sandbox": "Renderer",
                                                 "lockdown": "", "integrity": "S-1-16-0 Untrusted", "rid": 0}])
        self.assertEqual(sc.parse_rows([]), [])
        self.assertEqual(sc.parse_rows([HEADER]), [])
        self.assertEqual(sc.parse_rows([HEADER, ["15"]])[0]["sandbox"], "")

    def test_features(self):
        raw = ('features: [\n  {"enabled": false, "name": "NetworkServiceSandbox"},\n'
               '  {"enabled": true, "name": "WinSboxZeroAppShim"}\n]\npolicies: [{"processId": 1}]')
        self.assertEqual(sc.parse_features(raw), ["NetworkServiceSandbox: off", "WinSboxZeroAppShim: on"])
        self.assertEqual(sc.parse_features("features: [oops]\npolicies: []"), [])
        self.assertEqual(sc.parse_features(""), [])

    def test_gpu_page(self):
        # the page's text has the name, the colon and the value on lines of their own
        self.assertIs(sc.gpu_sandboxed("\n".join(["Driver Information", "Sandboxed", ":", "true", "GPU0"])), True)
        self.assertIs(sc.gpu_sandboxed("Sandboxed: false"), False)
        self.assertIsNone(sc.gpu_sandboxed("unable to reset the D3D device in the GPU process sandbox"))

    def test_mitigations(self):
        self.assertEqual(sc.mitigation_names({4: 0x5, 6: 0x1, 10: 0x3, 13: 0x0}),
                         ["win32k lockdown", "no extension points", "no remote images", "no low-integrity images"])
        self.assertEqual(sc.mitigation_names({4: 0x4}), [])         # another bit of that policy
        self.assertEqual(sc.mitigation_names({}), [])
        self.assertIn(sc.RENDERER_MUST_HAVE[0], [n for bits in sc.MITIGATIONS.values() for n in bits.values()])

    def test_what_a_command_line_says(self):
        self.assertEqual([sc.declared(cmd) for cmd in (NETWORK, STORAGE, "thoron.exe")], ["none", "service", ""])
        self.assertTrue(sc.by_design({"type": "utility", "cmd": NETWORK}))
        self.assertTrue(sc.by_design({"type": "utility", "cmd": "x --service-sandbox-type=none_and_elevated"}))
        self.assertFalse(sc.by_design({"type": "utility", "cmd": STORAGE}))
        self.assertFalse(sc.by_design({"type": "renderer", "cmd": "x --type=renderer --service-sandbox-type=none"}))
        self.assertEqual(sc.who({"pid": 13, "type": "utility", "cmd": NETWORK}),
                         "utility 13 (network.mojom.NetworkService)")
        self.assertEqual(sc.who({"pid": 15, "type": "renderer", "cmd": "x"}), "renderer 15")

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_reads_this_process_from_windows(self):
        mine = sc._windows_facts(os.getpid())
        self.assertIn(mine["integrity"], (0x2000, 0x3000, 0x4000))  # an ordinary process is not sandboxed
        self.assertFalse(mine["appcontainer"])
        self.assertGreater(mine["privileges"], 0)
        self.assertNotIn("win32k lockdown", mine["mitigations"])
        self.assertEqual(sc.windows_problems([{"pid": 1, "type": "renderer", "cmd": "", "facts": mine}])[0],
                         f"renderer 1 runs at {sc.level(mine['integrity'])} integrity (not sandboxed)")


class WitnessTests(unittest.TestCase):
    def test_the_sandbox_on_passes_every_witness(self):
        self.assertEqual(sc.judge(sandbox_on()), {"switch": [], "system": [], "pages": []})
        self.assertEqual(tuple(sc.judge(sandbox_on())), sc.WITNESSES)
        self.assertEqual(sc.judge(sandbox_on(), lambda procs: ["said by another system's rules"])["system"],
                         ["said by another system's rules"])
        self.assertEqual(sc.SYSTEMS["nt"], (sc._windows_facts, sc.windows_problems))

    def test_switch(self):
        seen = sandbox_on()
        seen["procs"][5]["cmd"] += " --no-sandbox --lang=en"
        self.assertEqual(sc.judge(seen)["switch"], ["renderer 15 runs with --no-sandbox"])
        seen["procs"][5]["cmd"] = "thoron.exe --type=renderer --no-sandbox-zygote"
        self.assertEqual(sc.judge(seen)["switch"], [])

    def test_windows_on_a_renderer(self):
        for change, said in (({"integrity": 0x2000}, "renderer 15 runs at Medium integrity (not sandboxed)"),
                             ({"integrity": None}, "renderer 15 runs at unknown integrity (not sandboxed)"),
                             ({"restricted": False}, "renderer 15: its token is not restricted"),
                             ({"privileges": 5}, "renderer 15 holds 5 privileges, no fewer than the browser itself"),
                             ({"in_job": False}, "renderer 15 is in no job object"),
                             ({"mitigations": ["no extension points"]}, "renderer 15: win32k lockdown is off")):
            with self.subTest(change=change):
                found = sc.judge(changed(15, **change))
                self.assertEqual(found["system"], [said])
                self.assertEqual(found["switch"], [])

    def test_windows_on_the_other_processes(self):
        self.assertEqual(sc.judge(changed(12, integrity=0x2000))["system"],
                         ["gpu 12 runs at Medium integrity (not sandboxed)"])
        self.assertEqual(sc.judge(changed(14, restricted=False))["system"],
                         ["utility 14 (storage.mojom.StorageService): its token is not restricted"])
        # only a renderer must be in a job, hold fewer privileges and have win32k shut off
        self.assertEqual(sc.judge(changed(12, in_job=False, privileges=9, mitigations=[]))["system"], [])
        # an AppContainer does the work of a restricted token
        self.assertEqual(sc.judge(changed(14, restricted=False, appcontainer=True, integrity=0x1000))["system"], [])
        # the network service declares that it has no sandbox: named in the notes, not a problem
        self.assertEqual(sc.judge(changed(13, integrity=0x3000))["system"], [])

    def test_windows_could_not_look(self):
        seen = sandbox_on()
        seen["procs"][5]["facts"] = None
        self.assertEqual(sc.judge(seen)["system"], ["renderer 15: its security token could not be read"])
        seen["procs"] = seen["procs"][:5]
        self.assertEqual(sc.judge(seen)["system"], ["no renderer process found, so the sandbox could not be checked"])

    def test_pages(self):
        seen = sandbox_on()
        seen["rows"][3].update(sandbox="Not Sandboxed", rid=None)
        self.assertEqual(sc.judge(seen)["pages"], ["chrome://sandbox: renderer 15 is not sandboxed"])
        seen = sandbox_on()
        seen["rows"][2].update(sandbox="Not Sandboxed", rid=None)
        self.assertEqual(sc.judge(seen)["pages"],
                         ["chrome://sandbox: utility 14 (storage.mojom.StorageService) is not sandboxed"])
        self.assertEqual(sc.judge(dict(sandbox_on(), gpu=False))["pages"],
                         ["chrome://gpu says the GPU process is not sandboxed"])
        self.assertEqual(sc.judge(dict(sandbox_on(), gpu=None))["pages"],
                         ["chrome://gpu does not say whether the GPU process is sandboxed"])
        self.assertEqual(sc.judge(dict(sandbox_on(), rows=[]))["pages"], ["chrome://sandbox lists no process"])

    def test_pages_and_windows_must_agree(self):
        found = sc.judge(changed(15, integrity=0x1000))
        self.assertEqual(found["system"], [])                     # Low is below Medium
        self.assertEqual(found["pages"], ["renderer 15: chrome://sandbox says S-1-16-0 Untrusted, Windows says Low "
                                          "integrity"])
        seen = sandbox_on()
        seen["rows"] = seen["rows"][:3]                             # the page lists none of the renderers
        self.assertEqual(sc.judge(seen)["pages"],
                         ["no renderer is both in chrome://sandbox and in the process tree: nothing was compared"])
        late = sandbox_on()
        late["rows"] = late["rows"][:4]                             # one renderer started after the page was read
        self.assertEqual(sc.judge(late)["pages"], [])

    def test_negative_control(self):
        control = sandbox_off()
        caught = sc.judge(control)
        self.assertEqual([len(caught[name]) for name in sc.WITNESSES], [5, 9, 4])
        self.assertEqual(sc.control_problems(control, caught), [])
        self.assertIn("renderer 15 runs at Medium integrity (not sandboxed)", caught["system"])
        self.assertIn("chrome://gpu says the GPU process is not sandboxed", caught["pages"])
        for name in sc.WITNESSES:
            with self.subTest(silent=name):
                self.assertEqual(sc.control_problems(control, dict(caught, **{name: []})),
                                 [f"negative control: the {name} witness did not notice a browser started with "
                                  "--no-sandbox"])
        self.assertEqual(len(sc.control_problems(sandbox_on(), sc.judge(sandbox_on()))), 3)

    def test_negative_control_must_be_caught_for_the_right_reason(self):
        missed = "negative control: the {} witness did not notice a browser started with --no-sandbox".format
        # a control browser that showed no renderer: "no renderer found" is a report, not the control caught
        empty = sandbox_off()
        empty["procs"] = empty["procs"][:4]
        found = sc.judge(empty)
        self.assertTrue(found["system"] and found["pages"])
        self.assertEqual(sc.control_problems(empty, found), [missed("system"), missed("pages")])
        # reports about the GPU process alone do not show that an unsandboxed renderer is seen
        control = sandbox_off()
        found = sc.judge(control)
        gpu_only = dict(found, system=[r for r in found["system"] if r.startswith("gpu")],
                        pages=[r for r in found["pages"] if "renderer" not in r])
        self.assertEqual(sc.control_problems(control, gpu_only), [missed("system"), missed("pages")])
        # the system must name every renderer; the pages may have been read before the last one started
        two = sandbox_off()
        two["procs"].append(free(150, "renderer", "thoron.exe --type=renderer --no-sandbox"))
        found = sc.judge(two)
        self.assertEqual(sc.control_problems(two, found), [])
        about_15 = [r for r in found["system"] if not r.startswith("renderer 150")]
        self.assertEqual(sc.control_problems(two, dict(found, system=about_15)), [missed("system")])

    def test_evidence_text(self):
        seen = sandbox_on()
        seen["procs"][0]["facts"]["integrity"] = 0x3000
        self.assertEqual(sc.notes(seen), [
            "utility 13 (network.mojom.NetworkService) is not sandboxed by design (--service-sandbox-type=none)",
            "the browser itself runs at High integrity: it was started from an elevated shell"])
        self.assertEqual(len(sc.notes(sandbox_on())), 1)
        text = sc.describe("Sandbox on", seen)
        self.assertTrue(text.startswith("Sandbox on (Thoron/1.2.3)\n"))
        self.assertIn("    renderer 15: Untrusted integrity, token restricted, 0 privileges, in a job; sandbox "
                      "mitigations: strict handle checks, win32k lockdown, no extension points, no child processes",
                      text)
        self.assertIn("    browser 10: High integrity, token not restricted, 5 privileges, in no job; sandbox "
                      "mitigations: none", text)
        self.assertIn("    13 Utility Network Service: Not Sandboxed\n", text)
        self.assertIn("    15 Renderer: Renderer, Lockdown, S-1-16-0 Untrusted\n", text)
        self.assertIn("    features: NetworkServiceSandbox: off\n", text)
        self.assertIn("  chrome://gpu shows: Sandboxed: true\n", text)
        self.assertIn("  note: the browser itself runs", text)
        unread = copy.deepcopy(seen)
        unread["procs"][5]["facts"] = None
        self.assertIn("    renderer 15: token could not be read", sc.describe("x", dict(unread, rows=[], gpu=None)))
        self.assertIn("  chrome://sandbox shows:\n    nothing\n  chrome://gpu shows: Sandboxed: not said",
                      sc.describe("x", dict(unread, rows=[], gpu=None, features=[])))


class RunTests(unittest.TestCase):
    def run_with(self, *seen, switches=()):
        said = []
        with mock.patch.object(sc, "SYSTEMS", {os.name: (None, sc.windows_problems)}), \
                mock.patch.object(sc, "observe", side_effect=list(seen)) as observe:
            problems, text = sc.run(Path("thoron.exe"), Path("work"), switches, say=said.append)
        return problems, text, said, [call.args[3] for call in observe.call_args_list]

    def test_sandbox_on_and_control_caught(self):
        problems, text, said, started = self.run_with(sandbox_on(), sandbox_off())
        self.assertEqual(problems, [])
        self.assertEqual(started, [(), ("--no-sandbox",)])
        self.assertEqual([line for line in said if line.startswith(("PASS", "FAIL"))],
                         ["PASS  the browser's sandbox: no witness reports a problem",
                          "PASS  negative control: switch 5 report(s), system 9 report(s), pages 4 report(s)"])
        self.assertTrue(text.startswith("Sandbox on (Thoron/1.2.3)\n"))
        self.assertIn("\n\nNegative control, started with --no-sandbox (Thoron/1.2.3)\n", text)
        self.assertTrue(text.endswith("every witness reported the browser started with --no-sandbox."))

    def test_a_browser_without_its_sandbox_fails(self):
        problems, text, said, _ = self.run_with(sandbox_off(), sandbox_off())
        self.assertEqual(len(problems), 18)
        self.assertIn("FAIL  the browser's sandbox: 18 problem(s)", said)
        self.assertTrue(text.endswith("\n".join(problems)))

    def test_a_control_that_is_not_caught_fails(self):
        problems, _, said, _ = self.run_with(sandbox_on(), sandbox_on())
        self.assertEqual(problems, [f"negative control: the {name} witness did not notice a browser started with "
                                    "--no-sandbox" for name in sc.WITNESSES])
        self.assertIn("FAIL  negative control: switch 0 report(s), system 0 report(s), pages 0 report(s)", said)

    def test_a_system_that_is_not_checked_yet_is_not_a_pass(self):
        with mock.patch.object(sc, "SYSTEMS", {}), mock.patch("builtins.print") as said:
            self.assertEqual(sc.main(["--browser", "thoron.exe", "--work", "never-made"]), 2)
        self.assertIn("SANDBOX CHECK: NOT RUN", said.call_args.args[0])
        self.assertFalse(Path("never-made").exists())

    def test_a_weakened_browser_is_named(self):
        weak = changed(12, integrity=0x2000, restricted=False)
        problems, text, _, started = self.run_with(weak, sandbox_off(), switches=("--disable-gpu-sandbox",))
        self.assertEqual(started[0], ("--disable-gpu-sandbox",))
        self.assertTrue(text.startswith("Started with --disable-gpu-sandbox (Thoron/1.2.3)\n"))
        self.assertEqual(problems[:2], ["gpu 12 runs at Medium integrity (not sandboxed)",
                                        "gpu 12: its token is not restricted"])


if __name__ == "__main__":
    unittest.main()
