# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of tools/release/delta.py. The Zucchini tool is not needed: patches are made by a stand-in that copies
the newer file (as a patch it is "too big" or "small" as each test wants), and the real tool's round trip runs
only when THORON_TEST_ZUCCHINI names a zucchini.exe."""
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.release import delta as dl

OLD, NEW = "158.0.8127.3000", "158.0.8127.3010"


class DeltaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def folder(self, name: str, version: str, contents: dict[str, bytes]) -> Path:
        root = self.tmp / name
        for path, data in contents.items():
            target = root / path.replace("<v>", version)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return root

    def test_the_version_folder_is_matched_to_the_newer_one(self):
        self.assertEqual(dl.older_path(f"{NEW}/chrome.dll", OLD, NEW), f"{OLD}/chrome.dll")
        self.assertEqual(dl.older_path("thoron.exe", OLD, NEW), "thoron.exe")
        self.assertEqual(dl.older_path(f"{NEW}x/a", OLD, NEW), f"{NEW}x/a")

    def test_each_file_is_same_patched_or_whole(self):
        old = self.folder("old", OLD, {"thoron.exe": b"launcher", "<v>/chrome.dll": b"a" * 1000,
                                       "<v>/gone.dat": b"gone"})
        new = self.folder("new", NEW, {"thoron.exe": b"launcher", "<v>/chrome.dll": b"b" * 1000,
                                       "<v>/new.dat": b"new", "<v>/big.dat": b"c" * 100})
        (old / OLD / "big.dat").write_bytes(b"d" * 100)

        def gen(a, b, patch):          # a small patch for chrome.dll, a big one for the rest
            patch.write_bytes(b"p" * (10 if b.name == "chrome.dll" else 99))
            return True

        entries, stored = dl.plan(old, new, gen, self.tmp)
        how = {e["path"]: e["how"] for e in entries}
        self.assertEqual(how, {"thoron.exe": "same", f"{NEW}/chrome.dll": "patch", f"{NEW}/new.dat": "whole",
                               f"{NEW}/big.dat": "whole"})
        same = next(e for e in entries if e["how"] == "same")
        self.assertEqual(same["from_path"], "thoron.exe")
        patch = next(e for e in entries if e["how"] == "patch")
        self.assertEqual(patch["from_path"], f"{OLD}/chrome.dll")
        self.assertEqual(patch["from_sha256"], dl.sha256(old / OLD / "chrome.dll"))
        self.assertEqual(patch["sha256"], dl.sha256(new / NEW / "chrome.dll"))

    def test_the_delta_is_reproducible_and_holds_what_its_list_says(self):
        old = self.folder("old", OLD, {"thoron.exe": b"launcher", "<v>/chrome.dll": b"a" * 1000})
        new = self.folder("new", NEW, {"thoron.exe": b"launcher", "<v>/chrome.dll": b"b" * 1000,
                                       "<v>/new.dat": b"new"})

        def gen(a, b, patch):
            patch.write_bytes(b"p" * 10)
            return True

        outs = []
        for n in range(2):
            entries, stored = dl.plan(old, new, gen, self.tmp)
            out = self.tmp / f"d{n}.delta"
            dl.write(out, entries, stored, OLD, NEW)
            outs.append(out.read_bytes())
        self.assertEqual(outs[0], outs[1])
        with zipfile.ZipFile(self.tmp / "d0.delta") as z:
            data = json.loads(z.read("delta.json"))
            self.assertEqual((data["format"], data["from"], data["to"]), (1, OLD, NEW))
            names = sorted(z.namelist())
        self.assertEqual(names, ["delta.json", "patch/0", "whole/1"])

    def test_two_folders_of_one_version_are_refused(self):
        a = self.folder("a", NEW, {"<v>/x": b"1"})
        b = self.folder("b", NEW, {"<v>/x": b"2"})
        with self.assertRaises(dl.DeltaError):
            dl.make(a, b, Path("zucchini.exe"), self.tmp / "x.delta")

    @unittest.skipUnless(os.environ.get("THORON_TEST_ZUCCHINI"), "THORON_TEST_ZUCCHINI names no zucchini.exe")
    def test_a_real_round_trip_gives_the_newer_files(self):
        old = self.folder("old", OLD, {"thoron.exe": bytes(range(256)) * 64, "<v>/x.bin": bytes(4096)})
        new = self.folder("new", NEW, {"thoron.exe": bytes(range(256)) * 63 + bytes(256),
                                       "<v>/x.bin": bytes(4096), "<v>/y.bin": b"new"})
        report = dl.make(old, new, Path(os.environ["THORON_TEST_ZUCCHINI"]), self.tmp / "r.delta", self.tmp)
        self.assertEqual(report["files"], 3)
        self.assertEqual(report["same"], 1)


if __name__ == "__main__":
    unittest.main()
