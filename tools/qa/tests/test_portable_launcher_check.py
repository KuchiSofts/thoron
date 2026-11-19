# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The portable launcher and its update: the offline check's judges (ROADMAP P3.12, P3.11, P4.4)."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.qa import portable_launcher_check as pl

# what dumpbin /disasm prints, in short
PLAIN = """wWinMain:
  0000000140001000: 48 89 5C 24 08     mov         qword ptr [rsp+8],rbx
  0000000140001005: 0F A2              cpuid
  000000014000100A: 0F 01 D0           xgetbv
  000000014000100D: 66 0F 6F 05 00 00  movdqa      xmm0,xmmword ptr [rip]
"""
RUNTIME = """memcpy_avx_ermsb_Intel:
  0000000140002000: C5 FE 6F 02        vmovdqu     ymm0,ymmword ptr [rdx]
memset:
  0000000140003000: C5 F8 77           vzeroupper
"""
OWN_AVX = """HasAvx2:
  0000000140001020: C5 FD 6F 05 00 00   vmovdqa     ymm0,ymmword ptr [rip]
  0000000140001028: C5 F8 77           vzeroupper
"""


class AvxTests(unittest.TestCase):
    def test_plain_code_has_none(self):
        self.assertEqual(pl.avx_found(PLAIN), [])

    def test_the_runtime_s_checked_routines_are_allowed(self):
        self.assertEqual(pl.avx_found(PLAIN + RUNTIME), [])
        self.assertEqual(sorted(pl.avx_by_function(RUNTIME)), ["memcpy_avx_ermsb_Intel", "memset"])

    def test_avx_in_the_launcher_s_own_code_is_found(self):
        found = pl.avx_found(PLAIN + RUNTIME + OWN_AVX)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("HasAvx2: "))
        self.assertIn("ymm0", found[0])
        self.assertIn("vzeroupper", found[0])

    def test_zmm_and_the_two_old_v_instructions(self):
        self.assertEqual(pl.avx_found("fn:\n  00000001: 0F 00 E0   verr  ax\n"), [])
        self.assertIn("zmm1", pl.avx_found("fn:\n  00000001: 62 F1 7C 48 28 C9   vmovaps zmm1,zmm1\n")[0])


class JudgeTests(unittest.TestCase):
    PACKAGE = Path("C:/x/a folder with spaces & more!/ThoronPortable")

    def found(self, version):
        return {"executable_path": str(self.PACKAGE / "Application" / version / "thoron.exe"),
                "profile_path": str(self.PACKAGE / "User Data" / "Default")}

    def test_the_named_version_with_the_package_profile(self):
        self.assertEqual(pl.started_problems("start", self.found(pl.OLDER), self.PACKAGE, pl.OLDER), [])

    def test_another_version_or_profile_is_named(self):
        self.assertEqual(len(pl.started_problems("update", self.found(pl.OLDER), self.PACKAGE, pl.NEWER)), 1)
        other = dict(self.found(pl.OLDER), profile_path="C:/somewhere/User Data/Default")
        self.assertEqual(len(pl.started_problems("start", other, self.PACKAGE, pl.OLDER)), 1)
        self.assertEqual(len(pl.started_problems("start", {}, self.PACKAGE, pl.OLDER)), 2)

    def test_a_drive_root(self):
        root = Path("C:\\")
        found = {"executable_path": "C:\\Application\\158.0.8127.3010\\thoron.exe",
                 "profile_path": "C:\\User Data\\Default"}
        self.assertEqual(pl.started_problems("update", found, root, pl.NEWER), [])

    def test_status(self):
        text = "current: 158.0.8127.3010\nprevious: 158.0.8127.3000\nmode: auto\n"
        self.assertEqual(pl.status_problems(text, pl.NEWER, pl.OLDER), [])
        self.assertEqual(len(pl.status_problems(text, pl.OLDER, pl.NEWER)), 1)


class FilesTests(unittest.TestCase):
    def test_the_list_the_updater_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "158.0.8127.3010").mkdir()
            (root / "thoron.exe").write_bytes(b"program")
            (root / "158.0.8127.3010" / "chrome.dll").write_bytes(b"library")
            listing = pl.files_list(root)
            self.assertEqual([f["path"] for f in listing], ["158.0.8127.3010/chrome.dll", "thoron.exe"])
            self.assertEqual(listing[1]["size"], 7)
            self.assertEqual(listing[1]["sha256"], hashlib.sha256(b"program").hexdigest())

    def test_links_are_the_same_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "a", Path(tmp) / "b"
            (source / "x").mkdir(parents=True)
            (source / "x" / "f").write_bytes(b"data")
            pl.link_tree(source, target)
            self.assertEqual((target / "x" / "f").read_bytes(), b"data")
            self.assertTrue((target / "x" / "f").samefile(source / "x" / "f"))


if __name__ == "__main__":
    unittest.main()
