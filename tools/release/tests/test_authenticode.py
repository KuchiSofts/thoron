# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Authenticode signing of the Windows programs (ROADMAP S.8): the command lines and the reading of the check,
with stand-ins for signtool and PowerShell (the real signing is checked in Windows Sandbox)."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.release import authenticode as ac

THUMB = "0123456789abcdef0123456789abcdef01234567"
TS = "http://timestamp.example.com/rfc3161"


class Done:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def check_lines(entries) -> str:
    return "\n".join(json.dumps(e) for e in entries)


class FilesTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, True))
        (self.dir / "1.0" / "Locales").mkdir(parents=True)
        for name in ("thoron.exe", "1.0/chrome.dll", "1.0/Locales/en-US.pak", "1.0/notification_helper.exe"):
            (self.dir / name).write_bytes(b"MZ")

    def test_a_folder_gives_its_programs_and_libraries(self):
        names = sorted(p.relative_to(self.dir).as_posix() for p in ac.files_of([self.dir]))
        self.assertEqual(names, ["1.0/chrome.dll", "1.0/notification_helper.exe", "thoron.exe"])

    def test_what_is_not_a_program_or_not_there_is_refused(self):
        with self.assertRaises(ac.SigningError):
            ac.files_of([self.dir / "1.0" / "Locales" / "en-US.pak"])
        with self.assertRaises(ac.SigningError):
            ac.files_of([self.dir / "missing.exe"])


class CommandTests(unittest.TestCase):
    def test_sha256_digests_a_timestamp_and_the_store_certificate(self):
        commands = ac.sign_commands(Path("signtool.exe"), THUMB, TS, "Thoron", [Path("a.exe")])
        self.assertEqual(commands, [["signtool.exe", "sign", "/sha1", THUMB.upper(), "/fd", "sha256", "/tr", TS,
                                     "/td", "sha256", "/d", "Thoron", "a.exe"]])
        # never a key file or a password on the command line
        self.assertFalse({"/f", "/p", "/csp", "/kc"} & set(commands[0]))

    def test_many_files_go_in_batches(self):
        files = [Path(f"{n}.dll") for n in range(ac.BATCH + 3)]
        commands = ac.sign_commands(Path("signtool.exe"), THUMB, TS, "Thoron", files)
        self.assertEqual([len(c) - 12 for c in commands], [ac.BATCH, 3])

    def test_a_bad_thumbprint_or_timestamp_is_refused(self):
        with self.assertRaises(ac.SigningError):
            ac.sign_commands(Path("signtool.exe"), "not-a-thumbprint", TS, "Thoron", [Path("a.exe")])
        with self.assertRaises(ac.SigningError):
            ac.sign_commands(Path("signtool.exe"), THUMB, "timestamp.example.com", "Thoron", [Path("a.exe")])

    def test_the_newest_sdk_signtool_is_found(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, True))
        for version in ("10.0.22621.0", "10.0.28000.0", "10.0.9200.0"):
            (root / version / "x64").mkdir(parents=True)
            (root / version / "x64" / "signtool.exe").write_bytes(b"MZ")
        with mock.patch.object(ac, "SDK_BIN", root):
            self.assertEqual(ac.find_signtool(), root / "10.0.28000.0" / "x64" / "signtool.exe")


class CheckTests(unittest.TestCase):
    def test_every_file_must_be_trusted_and_timestamped(self):
        files = [Path(r"C:\r\good.exe"), Path(r"C:\r\untrusted.dll"), Path(r"C:\r\nostamp.dll"),
                 Path(r"C:\r\missing.exe")]
        out = check_lines([
            {"path": r"C:\r\good.exe", "status": "Valid", "timestamped": True, "signer": "CN=Thoron"},
            {"path": r"C:\r\untrusted.dll", "status": "UnknownError", "timestamped": True, "signer": "CN=x"},
            {"path": r"C:\r\nostamp.dll", "status": "Valid", "timestamped": False, "signer": "CN=Thoron"},
        ])
        problems = ac.check(files, run=lambda *a, **k: Done(stdout=out))
        self.assertEqual(sorted(p.name for p in problems), ["missing.exe", "nostamp.dll", "untrusted.dll"])
        self.assertIn("UnknownError", problems[files[1]])
        self.assertIn("without a timestamp", problems[files[2]])

    def test_paths_are_compared_as_windows_does(self):
        out = check_lines([{"path": r"c:\R\Good.EXE", "status": "Valid", "timestamped": True, "signer": "CN=T"}])
        self.assertEqual(ac.check([Path(r"C:\r\good.exe")], run=lambda *a, **k: Done(stdout=out)), {})


class SignTests(unittest.TestCase):
    def test_signing_then_checking(self):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            if command[0] == "powershell":
                return Done(stdout=check_lines([{"path": "a.exe", "status": "Valid", "timestamped": True,
                                                 "signer": "CN=Thoron"}]))
            return Done()
        ac.sign([Path("a.exe")], THUMB, TS, Path("signtool.exe"), run=run)
        self.assertEqual([c[0] for c in calls], ["signtool.exe", "powershell"])

    def test_a_signtool_failure_or_a_bad_result_stops_it(self):
        with self.assertRaises(ac.SigningError):
            ac.sign([Path("a.exe")], THUMB, TS, Path("signtool.exe"),
                    run=lambda command, **k: Done(returncode=1, stderr="SignTool Error: No certificates were found"))

        def run(command, **kwargs):
            if command[0] == "powershell":
                return Done(stdout=check_lines([{"path": "a.exe", "status": "NotSigned", "timestamped": False,
                                                 "signer": ""}]))
            return Done()
        with self.assertRaises(ac.SigningError):
            ac.sign([Path("a.exe")], THUMB, TS, Path("signtool.exe"), run=run)


if __name__ == "__main__":
    unittest.main()
