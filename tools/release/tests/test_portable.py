# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Windows portable package and its launcher (ROADMAP P2.8, P3.12).

The package and its audit are tried with stand-ins for the programs: the first bytes of a Windows program are
all the audit reads. The launcher itself, Thoron.exe, is started for real on Windows when THORON_TEST_LAUNCHER
names a built thoron_launcher.exe (it is not in the repository): a small stand-in program then takes the
browser's place and writes down the command line, the working directory and the environment it was started with.
"""
import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools.release import package_audit, portable as po

VERSION = "158.0.8127.3010"
OLDER = "158.0.8127.3000"
BROWSER = {"thoron.exe": b"program", "chrome_proxy.exe": b"proxy", f"{VERSION}/chrome.dll": b"dll" * 5000,
           f"{VERSION}/{VERSION}.manifest": b"<assembly/>", f"{VERSION}/resources.pak": b"pak",
           f"{VERSION}/Locales/en-US.pak": b"en", f"{VERSION}/Locales/de.pak": b"de"}
ARGUMENTS = '--flag "two words" "https://example.com/?a=1&b=2%20c"'
PASSED = ["--flag", "two words", "https://example.com/?a=1&b=2%20c"]
# Folder names built from code points, so this file stays ASCII.
LATIN = "Caf\u00e9 \u00dcbung"
CYRILLIC = "\u041f\u0440\u0438\u043c\u0435\u0440 \u043f\u0430\u043f\u043a\u0438"
CJK = "\u4f8b\u3048 \u30c6\u30b9\u30c8 \ud55c\uae00"
BEYOND = "x\U00020bb7\U0001f600y"      # outside the 16-bit range: two code units each for Windows


def program(subsystem: int = 2, machine: int = 0x8664, magic: int = 0x20B, flags: int = 0x22,
            tail: bytes = b"") -> bytes:
    """The headers of a Windows program, as much as the audit reads, and nothing that runs."""
    at = 0x80
    head = bytearray(at + 24 + 240)
    head[:2] = b"MZ"
    head[0x3C:0x40] = at.to_bytes(4, "little")
    head[at:at + 4] = b"PE\0\0"
    head[at + 4:at + 6] = machine.to_bytes(2, "little")
    head[at + 22:at + 24] = flags.to_bytes(2, "little")
    head[at + 24:at + 26] = magic.to_bytes(2, "little")
    head[at + 24 + 68:at + 24 + 70] = subsystem.to_bytes(2, "little")
    return bytes(head) + tail


LAUNCHER = program(2, tail=b"launcher")     # a window program
UPDATER = program(3, tail=b"updater")       # a console program


def browser(root: Path, files: dict = BROWSER, order=sorted) -> Path:
    for name in order(files):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(files[name])
    return root


def parts(root: Path, launcher: bytes = LAUNCHER, updater: bytes = UPDATER) -> tuple[Path, Path]:
    """The launcher and the updater as the build writes them into its out dir."""
    root.mkdir(parents=True, exist_ok=True)
    (root / po.BUILT_LAUNCHER).write_bytes(launcher)
    (root / po.UPDATER).write_bytes(updater)
    return root / po.BUILT_LAUNCHER, root / po.UPDATER


class ProgramTests(unittest.TestCase):
    def test_a_window_program_and_a_console_program(self):
        self.assertEqual(po.program_problems(LAUNCHER, "Thoron.exe", window=True), [])
        self.assertEqual(po.program_problems(UPDATER, "thoron_update.exe"), [])
        self.assertEqual(po.program_problems(UPDATER, "Thoron.exe", window=True),
                         ["Thoron.exe must be a window program (subsystem 2, no console window), not subsystem 3"])

    def test_what_is_not_an_x64_program(self):
        moved = bytearray(LAUNCHER)
        moved[0x3C:0x40] = (len(LAUNCHER) + 10).to_bytes(4, "little")
        no_signature = bytearray(LAUNCHER)
        no_signature[0x80:0x84] = b"NE\0\0"
        cases = {
            "x is missing": None,
            "no MZ header": b"#!/bin/sh\n" * 10,
            "no MZ header ": b"MZ" + b"\0" * 10,                  # cut short
            "no PE header": bytes(moved),
            "no PE header ": bytes(no_signature),
            "not a program for x64 (machine 0x014c)": program(machine=0x14C),      # 32-bit x86
            "not a program for x64 (machine 0xaa64)": program(machine=0xAA64),     # ARM64
            "not a program for x64 (machine 0x8664)": program(magic=0x10B),        # a PE32 header
            "a library": program(flags=0x2022),
            "cannot be run": program(flags=0x0020),
        }
        for want, head in cases.items():
            with self.subTest(want):
                self.assertTrue([p for p in po.program_problems(head, "x") if want.strip() in p],
                                po.program_problems(head, "x"))

    def test_the_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher, updater = parts(Path(tmp))
            self.assertEqual(po.parts_problems(launcher, updater), [])
            self.assertEqual(po.parts_problems(updater, launcher),
                             ["the launcher thoron_update.exe must be a window program (subsystem 2, no console "
                              "window), not subsystem 3"])
            self.assertEqual(po.parts_problems(Path(tmp) / "nowhere.exe", updater),
                             ["the launcher nowhere.exe is missing"])


class ReadmeTests(unittest.TestCase):
    def test_the_readme(self):
        for variant in po.VARIANTS:
            with self.subTest(variant):
                text = po.readme_text(VERSION, variant)
                self.assertTrue(text.isascii())
                self.assertEqual(text.count("\n"), text.count("\r\n"))
                for part in ("Start Thoron.exe.", "Application", "User Data", VERSION, variant, "no console window",
                             "passwords", "does not update itself yet", "except User Data", "delete",
                             "write-protected"):
                    self.assertIn(part, text.replace("\r\n  ", " ").replace("\r\n", " "))
                self.assertNotIn(".cmd", text)
                self.assertLess(max(len(line) for line in text.split("\r\n")), 79)
        self.assertIn("AVX2", po.readme_text(VERSION, "win-x64-avx2"))
        self.assertIn("older processors", po.readme_text(VERSION, "win-x64-sse4"))


class PackageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.src = browser(self.tmp / "Chrome-bin")
        self.launcher, self.updater = parts(self.tmp / "out")
        self.dist = self.tmp / "dist"

    def build(self, variant: str = "win-x64-avx2", src: Path | None = None, dist: Path | None = None,
              launcher: Path | None = None, updater: Path | None = None, **kw) -> dict:
        return po.build(src or self.src, dist or self.dist, variant, launcher or self.launcher,
                        updater or self.updater, **kw)

    def test_the_package(self):
        made = self.build()
        package = self.dist / "ThoronPortable"
        self.assertEqual(made["package"], package)
        self.assertEqual(made["version"], VERSION)
        self.assertEqual(sorted(p.name for p in package.iterdir()), ["Application", "README.txt", "Thoron.exe",
                                                                     "variant"])
        self.assertEqual(sorted(p.name for p in (package / "Application").iterdir()), [VERSION, "current"])
        self.assertEqual((package / "Thoron.exe").read_bytes(), LAUNCHER)
        self.assertEqual((package / "Application" / VERSION / "thoron_update.exe").read_bytes(), UPDATER)
        self.assertEqual((package / "Application" / "current").read_bytes(), f"{VERSION}\n".encode("ascii"))
        self.assertEqual((package / "variant").read_bytes(), b"win-x64-avx2\n")
        self.assertEqual((package / "README.txt").read_bytes(),
                         po.readme_text(VERSION, "win-x64-avx2").encode("ascii"))
        for name, data in BROWSER.items():
            self.assertEqual((package / "Application" / VERSION / name).read_bytes(), data)
        self.assertEqual(made["files"], len(BROWSER) + 5)
        self.assertEqual(made["files"], len(po.files(package)))
        self.assertEqual(made["zip"], self.dist / f"thoron-{VERSION}-win-x64-avx2-portable.zip")
        self.assertEqual({int(p.stat().st_mtime) for p in package.rglob("*") if p.is_file()}, {po.EPOCH})
        self.assertFalse((package / "User Data").exists())
        self.assertEqual(sorted(p.name for p in self.src.iterdir()), [VERSION, "chrome_proxy.exe", "thoron.exe"])

    def test_the_sse4_package(self):
        made = self.build("win-x64-sse4")
        self.assertEqual((made["package"] / "variant").read_bytes(), b"win-x64-sse4\n")
        self.assertEqual(made["zip"].name, f"thoron-{VERSION}-win-x64-sse4-portable.zip")
        self.assertEqual(po.audit(made["zip"]), [])

    def test_the_package_passes_the_audits(self):
        made = self.build()
        package = made["package"]
        self.assertEqual(po.audit(package), [])
        self.assertEqual(po.audit(package, "win-x64-avx2"), [])
        self.assertEqual(po.audit(made["zip"]), [])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(package_audit.main(["--dir", str(package / "Application" / VERSION),
                                                 "--platform", "win"]), 0)
            self.assertEqual(po.main(["audit", "--package", str(package)]), 0)
            self.assertEqual(po.main(["audit", "--package", str(made["zip"])]), 0)
        self.assertIn("package audit: OK", out.getvalue())
        self.assertEqual(out.getvalue().count("portable audit: OK"), 2)

    def test_the_zip_holds_the_package_in_one_folder_in_a_stable_order(self):
        made = self.build()
        with zipfile.ZipFile(made["zip"]) as z:
            infos = z.infolist()
            self.assertIsNone(z.testzip())
            self.assertEqual(z.read(f"ThoronPortable/Application/{VERSION}/{VERSION}/chrome.dll"),
                             BROWSER[f"{VERSION}/chrome.dll"])
            self.assertEqual(z.read("ThoronPortable/Thoron.exe"), LAUNCHER)
        names = [i.filename for i in infos]
        self.assertEqual(names, sorted(names))
        self.assertEqual(names, [f"ThoronPortable/{n}" for n in po.files(made["package"])])
        self.assertEqual(names[-4:], ["ThoronPortable/Application/current", "ThoronPortable/README.txt",
                                      "ThoronPortable/Thoron.exe", "ThoronPortable/variant"])
        self.assertEqual({i.date_time for i in infos}, {(1980, 1, 1, 0, 0, 0)})
        self.assertEqual({(i.create_system, i.external_attr, i.comment, i.extra) for i in infos}, {(0, 0x20, b"", b"")})
        self.assertFalse([n for n in names if n.endswith("/") or "User Data" in n])

    def test_the_same_files_give_the_same_zip(self):
        first = self.build()["zip"]
        again = browser(self.tmp / "later" / "Chrome-bin", order=lambda f: sorted(f, reverse=True))
        launcher, updater = parts(self.tmp / "later" / "out")
        for path in [*again.rglob("*"), launcher, updater]:
            os.utime(path, (1_900_000_000, 1_900_000_000))      # built at another time, written in another order
        second = self.build(src=again, dist=self.tmp / "dist2", launcher=launcher, updater=updater)["zip"]
        self.assertEqual(first.read_bytes(), second.read_bytes())
        for name, (src, launcher, updater) in {
                "browser": (browser(self.tmp / "b" / "Chrome-bin", dict(BROWSER, **{"thoron.exe": b"x"})), None, None),
                "launcher": (None, *parts(self.tmp / "l", launcher=program(2, tail=b"other"))),
                "updater": (None, *parts(self.tmp / "u", updater=program(3, tail=b"other")))}.items():
            with self.subTest(name):
                other = self.build(src=src, dist=self.tmp / f"dist-{name}", launcher=launcher, updater=updater)
                self.assertNotEqual(po.sha256(first), po.sha256(other["zip"]))

    def test_the_time_can_be_set_and_not_before_1980(self):
        made = self.build(epoch=1_767_225_600)       # 2026-01-01 00:00:00 UTC
        with zipfile.ZipFile(made["zip"]) as z:
            self.assertEqual({i.date_time for i in z.infolist()}, {(2026, 1, 1, 0, 0, 0)})
        with self.assertRaises(po.PortableError):
            self.build(dist=self.tmp / "dist2", epoch=0)

    def refused(self, want: str, files: dict | None = None, variant: str = "win-x64-avx2",
                launcher: bytes = LAUNCHER, updater: bytes = UPDATER):
        bad = self.tmp / "bad"
        shutil.rmtree(bad, ignore_errors=True)
        src = browser(bad / "Chrome-bin", files) if files is not None else self.src
        made = parts(bad / "out", launcher, updater)
        with self.assertRaises(po.PortableError) as raised:
            self.build(variant, src, launcher=made[0], updater=made[1])
        self.assertIn(want, str(raised.exception))
        self.assertFalse(self.dist.exists() and any(self.dist.iterdir()), "nothing may be written")

    def test_a_folder_that_fails_the_package_audit_is_refused(self):
        self.refused("Widevine", dict(BROWSER, **{f"{VERSION}/WidevineCdm/widevinecdm.dll": b"x"}))

    def test_a_name_after_thorium_is_refused(self):
        self.refused("Thorium", dict(BROWSER, **{f"{VERSION}/thorium.ico": b"x"}))

    def test_the_program_must_be_at_the_top(self):
        files = {("bin/" + n if n == "thoron.exe" else n): d for n, d in BROWSER.items()}
        self.refused("not at the top", files)

    def test_one_version_folder(self):
        self.refused("one version folder", dict(BROWSER, **{"157.0.1.2/chrome.dll": b"x"}))
        self.refused("one version folder", {"thoron.exe": b"x"})
        self.refused("chrome.dll is missing", {"thoron.exe": b"x", f"{VERSION}/resources.pak": b"x"})

    def test_profile_data_and_leftovers_are_refused(self):
        for name in ("User Data/Default/Preferences", "User Data/Local State", f"{VERSION}/debug.log",
                     "new_thoron.exe", f"{VERSION}/Crashpad/reports/a.dmp", "Login Data", "lockfile"):
            with self.subTest(name):
                self.refused("profile data or a leftover", dict(BROWSER, **{name: b"x"}))

    def test_a_browser_folder_that_already_holds_an_updater_is_refused(self):
        self.refused("already holds thoron_update.exe", dict(BROWSER, **{"thoron_update.exe": UPDATER}))

    def test_a_link_is_refused(self):
        try:
            os.symlink(self.src / "thoron.exe", self.src / "link.exe")
        except OSError:
            self.skipTest("links cannot be made here")
        self.refused("is a link")

    def test_only_the_two_variants_the_launcher_knows(self):
        for variant in ("win-x64-avx512", "win-arm64-neon", "linux-x64-avx2", "WIN-X64-AVX2", "win-x64-avx2 "):
            with self.subTest(variant):
                self.refused("variant must be win-x64-avx2 or win-x64-sse4", variant=variant)

    def test_the_launcher_and_the_updater_must_be_x64_programs(self):
        for want, launcher, updater in (
                ("the launcher thoron_launcher.exe must be a window program", UPDATER, UPDATER),
                ("the launcher thoron_launcher.exe is not a program for x64", program(machine=0x14C), UPDATER),
                ("the launcher thoron_launcher.exe is not a Windows program: no MZ header", b"@echo off\r\n", UPDATER),
                ("the updater thoron_update.exe is not a program for x64", LAUNCHER, program(3, machine=0xAA64)),
                ("the updater thoron_update.exe is a library", LAUNCHER, program(3, flags=0x2022)),
                ("the updater thoron_update.exe is not a Windows program", LAUNCHER, b"")):
            with self.subTest(want):
                self.refused(want, launcher=launcher, updater=updater)
        (self.tmp / "out" / "thoron_launcher.exe").unlink()
        with self.assertRaises(po.PortableError) as raised:
            self.build()
        self.assertIn("the launcher thoron_launcher.exe is missing", str(raised.exception))
        self.assertFalse(self.dist.exists())

    def test_a_package_is_never_overwritten(self):
        self.build()
        before = po.sha256(self.dist / f"thoron-{VERSION}-win-x64-avx2-portable.zip")
        with self.assertRaises(po.PortableError) as raised:
            self.build()
        self.assertIn("never overwritten", str(raised.exception))
        self.assertEqual(po.sha256(self.dist / f"thoron-{VERSION}-win-x64-avx2-portable.zip"), before)
        self.assertEqual(po.audit(self.dist / "ThoronPortable"), [])
        shutil.rmtree(self.dist / "ThoronPortable")         # the .zip alone is in the way too
        with self.assertRaises(po.PortableError):
            self.build()

    def test_a_package_or_a_zip_that_fails_its_audit_is_not_kept(self):
        for planted in ("package_problems", "zip_problems"):
            with self.subTest(planted), mock.patch.object(po, planted, return_value=["planted"]), \
                    self.assertRaises(po.PortableError) as raised:
                self.build()
            self.assertIn("planted", str(raised.exception))
            self.assertEqual(list(self.dist.iterdir()), [])

    def test_the_audit_hook(self):
        good = self.build(zipped=False)["package"]
        app = f"Application/{VERSION}"
        made = []

        def problems(change) -> list[str]:
            package = self.tmp / f"case{len(made)}" / "ThoronPortable"
            made.append(package)
            shutil.copytree(good, package)
            change(package)
            return po.audit(package)

        def put(name: str, data: bytes):
            def change(package: Path):
                (package / name).parent.mkdir(parents=True, exist_ok=True)
                (package / name).write_bytes(data)
            return change

        def remove(name: str):
            return lambda package: (package / name).unlink()

        def rename(old: str, new: str):
            return lambda package: (package / old).rename(package / new)

        cases = {
            "a package never carries a profile": put("User Data/Default/Preferences", b"{}"),
            "Thoron.exe must be a window program": put("Thoron.exe", UPDATER),
            "Thoron.exe is not a Windows program": put("Thoron.exe", b"@echo off\r\n"),
            "Thoron.exe is missing": remove("Thoron.exe"),
            "README.txt is missing": remove("README.txt"),
            "variant is missing": remove("variant"),
            "variant must be one of": put("variant", b"win-x64-avx2"),
            "variant must be one of ": put("variant", b"win-x64-avx512\n"),
            "variant must be one of  ": put("variant", "win-x64-avx2\n".encode("utf-16")),
            "Application/current is missing": remove("Application/current"),
            "Application/current must name the version folder": put("Application/current", f"{OLDER}\n".encode()),
            "Application/current must name the version folder ": put("Application/current",
                                                                     f"{VERSION}\n{OLDER}\n".encode()),
            "not part of a package: Application/thoron.exe": put("Application/thoron.exe", b"the old layout"),
            "one version folder is expected in Application": put(f"Application/{OLDER}/thoron.exe", b"x"),
            "one version folder is expected in Application ": rename(app, "Application/latest"),
            f"{app}: thoron_update.exe is not beside thoron.exe": remove(f"{app}/thoron_update.exe"),
            f"{app}/thoron_update.exe is not a Windows program": put(f"{app}/thoron_update.exe", b"x"),
            f"{app}: thoron.exe is not at the top": remove(f"{app}/thoron.exe"),
            f"{app}: profile data or a leftover of a used browser: Local State": put(f"{app}/Local State", b"{}"),
            f"{app}: package audit: Widevine": put(f"{app}/{VERSION}/WidevineCdm/manifest.json", b"{}"),
        }
        for want, change in cases.items():
            with self.subTest(want):
                found = problems(change)
                self.assertTrue([p for p in found if want.strip() in p], found)
        self.assertEqual(problems(put("notes.txt", b"x")), ["not part of a package: notes.txt"])
        renamed = problems(lambda p: (rename(app, "Application/158.0.8127.3999")(p),
                                      put("Application/current", b"158.0.8127.3999\n")(p)))
        self.assertEqual(renamed, [f"the version folder 158.0.8127.3999 holds the browser {VERSION}"])
        self.assertEqual(po.audit(good, "win-x64-sse4"),
                         ["variant says win-x64-avx2, and the package is named for win-x64-sse4"])
        # two names that differ in case only cannot both be made on Windows: the names are judged as they come
        twice = po.package_problems(po.files(good) + [f"{app}/THORON_UPDATE.EXE"], lambda n: (good / n).read_bytes())
        self.assertIn("two names in the package differ only in upper and lower case", twice)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(po.main(["audit", "--package", str(made[-1])]), 1)
            self.assertEqual(po.main(["audit", "--package", str(good / "nowhere")]), 1)
        self.assertIn("portable: the version folder 158.0.8127.3999 holds the browser", err.getvalue())
        self.assertIn("portable: the package is not there", err.getvalue())

    def test_the_zip_audit(self):
        made = self.build()
        name = made["zip"].name

        def as_named(new: str) -> list[str]:
            target = self.tmp / "named" / new
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(made["zip"], target)
            return po.audit(target)

        self.assertEqual(as_named("thoron-portable.zip"), ["thoron-portable.zip is not named "
                                                           "thoron-<version>-<variant>-portable.zip"])
        self.assertEqual(as_named(name.replace("avx2", "sse4")),
                         ["variant says win-x64-avx2, and the package is named for win-x64-sse4"])
        self.assertEqual(as_named(name.replace(VERSION, "158.0.8127.3999")),
                         [f"the version folder is {VERSION}, and the package is named for 158.0.8127.3999"])

        def remade(extra: dict, stored: bool = False) -> Path:
            target = self.tmp / "remade" / name
            shutil.rmtree(target.parent, ignore_errors=True)
            target.parent.mkdir()
            with zipfile.ZipFile(made["zip"]) as z, zipfile.ZipFile(
                    target, "w", zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED) as out:
                for info in z.infolist():
                    out.writestr(info.filename, z.read(info))
                for entry, data in extra.items():
                    out.writestr(entry, data)
            return target

        self.assertEqual(po.audit(remade({})), [])
        self.assertEqual(po.audit(remade({"other/notes.txt": b"x"})),
                         ["the .zip holds other/notes.txt, outside the one folder ThoronPortable"])
        self.assertEqual(po.audit(remade({"ThoronPortable/../evil.txt": b"x"})),
                         ["the .zip holds ThoronPortable/../evil.txt, outside the one folder ThoronPortable"])
        self.assertEqual(po.audit(remade({"ThoronPortable/User Data/": b""})),
                         ["the .zip holds a folder entry ThoronPortable/User Data/; a package's .zip holds files only"])
        stored = remade({}, stored=True)
        raw = stored.read_bytes()
        at = raw.index(b"dll" * 100)
        stored.write_bytes(raw[:at] + b"DLL" + raw[at + 3:])        # one changed byte inside chrome.dll
        self.assertEqual(po.audit(stored), [f"ThoronPortable/Application/{VERSION}/{VERSION}/chrome.dll in the .zip "
                                            "does not match its checksum"])
        stored.write_bytes(b"not a zip")
        self.assertTrue(po.audit(stored)[0].startswith("the .zip cannot be read"))

    def test_the_command_line(self):
        out, err = io.StringIO(), io.StringIO()
        common = ["--chrome-bin", str(self.src), "--launcher", str(self.launcher), "--updater", str(self.updater),
                  "--variant", "win-x64-avx2"]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(po.main(["build", *common, "--dist", str(self.dist)]), 0)
            self.assertEqual(po.main(["build", *common, "--dist", str(self.dist)]), 2)
            self.assertEqual(po.main(["build", *common, "--dist", str(self.tmp / "d2"), "--no-zip"]), 0)
            with self.assertRaises(SystemExit):
                po.main(["build", *common[:-1], "win-x64-avx512", "--dist", str(self.tmp / "d3")])
            with self.assertRaises(SystemExit):     # the launcher and the updater are needed
                po.main(["build", "--chrome-bin", str(self.src), "--dist", str(self.tmp / "d4"),
                         "--variant", "win-x64-avx2"])
        self.assertIn(f"ThoronPortable ({len(BROWSER) + 5} files, Thoron {VERSION}, win-x64-avx2)", out.getvalue())
        self.assertIn(f"thoron-{VERSION}-win-x64-avx2-portable.zip", out.getvalue())
        self.assertIn("sha256", out.getvalue())
        self.assertIn("never overwritten", err.getvalue())
        self.assertNotIn(str(self.tmp), out.getvalue())
        self.assertEqual([p.name for p in (self.tmp / "d2").iterdir()], ["ThoronPortable"])
        self.assertFalse((self.tmp / "d3").exists() or (self.tmp / "d4").exists())


STAND_IN = """
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Threading;

static class StandIn
{
    static int Main()
    {
        string record = Environment.GetEnvironmentVariable("PORTABLE_TEST_RECORD");
        if (string.IsNullOrEmpty(record)) return 2;
        string hold = Environment.GetEnvironmentVariable("PORTABLE_TEST_HOLD");
        var names = new List<string>();
        foreach (DictionaryEntry e in Environment.GetEnvironmentVariables()) names.Add((string)e.Key);
        File.WriteAllText(record + ".part", Environment.CommandLine + "\\n" + Environment.CurrentDirectory + "\\n"
                          + string.Join("\\n", names.ToArray()) + "\\n", new UTF8Encoding(false));
        File.Move(record + ".part", record);
        if (!string.IsNullOrEmpty(hold))
        {
            for (int i = 0; i < 1200 && !File.Exists(hold); i++) Thread.Sleep(50);
            File.WriteAllText(record + ".ended", "");
        }
        return 0;
    }
}
"""


def _compiler() -> Path | None:
    """The C# compiler every Windows carries: it makes the stand-in program."""
    found = sorted((Path(os.environ.get("WINDIR", "")) / "Microsoft.NET").glob("Framework*/v4*/csc.exe"))
    return found[-1] if os.name == "nt" and found else None


def _launcher() -> Path | None:
    """A built launcher (thoron_launcher.exe), named by THORON_TEST_LAUNCHER: it is not in the repository."""
    named = os.environ.get("THORON_TEST_LAUNCHER")
    return Path(named) if os.name == "nt" and named and Path(named).is_file() else None


def _arguments(line: str) -> list[str]:
    """A command line split as Windows splits it for a program (the browser uses the same call)."""
    import ctypes
    shell32, kernel32 = ctypes.windll.shell32, ctypes.windll.kernel32
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    count = ctypes.c_int()
    parts_ = shell32.CommandLineToArgvW(line, ctypes.byref(count))
    try:
        return [parts_[i] for i in range(count.value)]
    finally:
        kernel32.LocalFree(parts_)


@unittest.skipUnless(_compiler() and _launcher(), "needs Windows, its C# compiler, and THORON_TEST_LAUNCHER naming "
                                                  "a built thoron_launcher.exe")
class LauncherRunTests(unittest.TestCase):
    """Thoron.exe started for real, as a double click or a prompt starts it, from folders with every kind of name."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.tmp = Path(cls._tmp.name)
        cls.launcher = _launcher()
        if po.program_problems(cls.launcher.read_bytes()[:po.HEAD], "the launcher", window=True):
            raise AssertionError(f"{cls.launcher} is not a window program for x64")
        (cls.tmp / "stand_in.cs").write_text(STAND_IN, encoding="utf-8")
        cls.stand_in = cls.tmp / "stand_in.exe"
        made = subprocess.run([str(_compiler()), "/nologo", "/target:winexe", f"/out:{cls.stand_in}",
                               str(cls.tmp / "stand_in.cs")], capture_output=True, text=True,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        if made.returncode != 0 or not cls.stand_in.is_file():
            raise unittest.SkipTest(f"the stand-in program could not be made: {made.stdout.strip()[:200]}")
        cls.count = 0

    def package(self, name: str, variant: str | None = "win-x64-avx2", versions: tuple = (VERSION,)) -> Path:
        """A package in the layout portable.py makes, with the stand-in in the browser's place."""
        type(self).count += 1
        package = self.tmp / f"case{self.count}" / name
        for version in versions:
            (package / "Application" / version).mkdir(parents=True)
            shutil.copyfile(self.stand_in, package / "Application" / version / "thoron.exe")
        (package / "Application" / "current").write_bytes(po.current_text(versions[-1]))
        shutil.copyfile(self.launcher, package / "Thoron.exe")
        if variant:
            (package / "variant").write_bytes(po.variant_text(variant))
        return package

    def launch(self, line, cwd: Path | None = None, extra: dict | None = None, wait: bool = True) -> dict:
        """Run a command line (or a list); what the launcher said and what the stand-in program wrote down."""
        type(self).count += 1
        record = self.tmp / f"record{self.count}.txt"
        message = self.tmp / f"message{self.count}.txt"     # the launcher writes its message here, not in a window
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("THORON_LAUNCHER_")}
        env.update(PORTABLE_TEST_RECORD=str(record), THORON_LAUNCHER_MESSAGE_FILE=str(message), **(extra or {}))
        code = subprocess.run(line, cwd=cwd or self.tmp, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
                              creationflags=subprocess.CREATE_NO_WINDOW).returncode
        for _ in range(400 if wait else 20):        # patient where a start is expected: a new program is scanned
            if record.is_file():
                break
            time.sleep(0.05)
        found = {"code": code, "said": message.read_text(encoding="utf-16-le") if message.is_file() else "",
                 "record": record, "env": env, "started": record.is_file()}
        if found["started"]:
            lines = record.read_text(encoding="utf-8").split("\n")
            found.update(argv=_arguments(lines[0]), cwd=lines[1], names=sorted(n for n in lines[2:] if n))
        return found

    def assert_started(self, found: dict, package: Path, arguments: list[str], version: str = VERSION):
        self.assertTrue(found["started"], found["said"])
        self.assertEqual(found["code"], 0)
        self.assertEqual(found["said"], "")
        self.assertEqual(found["argv"], [str(package / "Application" / version / "thoron.exe"),
                                         f"--user-data-dir={package / 'User Data'}", *arguments])

    def test_arguments_reach_the_browser_intact(self):
        package = self.package("plain")
        self.assert_started(self.launch(f'"{package / "Thoron.exe"}" {ARGUMENTS}'), package, PASSED)
        self.assertTrue((package / "User Data").is_dir())
        self.assert_started(self.launch([str(package / "Thoron.exe"), *PASSED]), package, PASSED)
        typed = f'cmd.exe /d /s /c ""{package / "Thoron.exe"}" {ARGUMENTS}"'       # as typed at a prompt
        self.assert_started(self.launch(typed), package, PASSED)

    def test_folder_names(self):
        names = {"spaces": "with two  spaces", "accented Latin": LATIN, "Cyrillic": CYRILLIC, "CJK": CJK,
                 "beyond 16 bits": BEYOND, "ampersand": "R&D", "percent": "100% sure", "percent pair": "50%off%now",
                 "exclamation": "wow! really!", "caret": "a^b^^c", "parentheses": "x (1) y)",
                 "list signs": "a;b,c=d", "quote sign": "it's `this`",
                 "all at once": f"R&D 100% (new)! ^ ;,= {LATIN} {CYRILLIC} {CJK} {BEYOND}"}
        for what, name in names.items():
            with self.subTest(what):
                package = self.package(name)
                self.assert_started(self.launch(f'"{package / "Thoron.exe"}" {ARGUMENTS}'), package, PASSED)
                self.assertTrue((package / "User Data").is_dir())

    def test_a_folder_named_after_an_environment_variable(self):
        # a .cmd could not start from here: cmd.exe put the variable's value into the path before it ran
        for name in ("a%TEMP%b", f"x %TEMP% & %OS% {CJK}"):
            with self.subTest(name):
                package = self.package(name)
                self.assert_started(self.launch(f'"{package / "Thoron.exe"}" {ARGUMENTS}'), package, PASSED)
                self.assertTrue((package / "User Data").is_dir())      # under that very name
                self.assertEqual(sorted(p.name for p in package.parent.iterdir()), [name])

    def test_arguments_pass_as_they_are(self):
        package = self.package(f"R&D 100% (new)! {CJK}")
        cases = (("", []), ('""', [""]), ("a b  c", ["a", "b", "c"]), ('"100%" a%20b 5%', ["100%", "a%20b", "5%"]),
                 ("%OS% %nosuch% %TEMP%", ["%OS%", "%nosuch%", "%TEMP%"]),     # no variable is put into them
                 ("wow! !x! a!b", ["wow!", "!x!", "a!b"]), ('"a^b" "x&y" "p|q" "<r>"', ["a^b", "x&y", "p|q", "<r>"]),
                 ("a&b c|d ^e", ["a&b", "c|d", "^e"]),         # not quoted: no command interpreter reads them
                 ('"C:\\folder with space\\\\"', ["C:\\folder with space\\"]),
                 ('--a=b --c="d e" a;b a,b (x) y)', ["--a=b", "--c=d e", "a;b", "a,b", "(x)", "y)"]),
                 ('--user-data-dir="C:\\other one"', ["--user-data-dir=C:\\other one"]),
                 (f'"{CYRILLIC}" {CJK} {BEYOND}', [CYRILLIC, *CJK.split(), BEYOND]))
        for text, want in cases:
            with self.subTest(text):
                self.assert_started(self.launch(f'"{package / "Thoron.exe"}" {text}'), package, want)

    def test_started_from_another_working_directory(self):
        package = self.package(f"R&D 100% (new)! {LATIN}")
        elsewhere = self.tmp / f"elsewhere {CYRILLIC}"
        elsewhere.mkdir()
        found = self.launch(f'"{package / "Thoron.exe"}" {ARGUMENTS}', cwd=elsewhere)
        self.assert_started(found, package, PASSED)
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertEqual(sorted(p.name for p in package.iterdir()), ["Application", "Thoron.exe", "User Data",
                                                                     "variant"])
        self.assertEqual(list((package / "User Data").iterdir()), [])     # made by the launcher, and left empty
        self.assertEqual(sorted(p.name for p in package.parent.iterdir()), [package.name])
        # the browser starts in the caller's working directory, so a relative file on the command line is theirs
        self.assertEqual(Path(found["cwd"]), elsewhere)
        found = self.launch('cmd.exe /d /s /c ".\\Thoron.exe one"', cwd=package)
        self.assert_started(found, package, ["one"])
        found = self.launch(f'cmd.exe /d /s /c ""{package.name}\\Thoron.exe" one"', cwd=package.parent)  # relative
        self.assert_started(found, package, ["one"])

    def test_a_start_by_the_bare_name_through_the_search_path(self):
        package = self.package(f"on the path {CYRILLIC}")
        path = {"PATH": f"{package}{os.pathsep}{os.environ['PATH']}"}
        for line in ('cmd.exe /d /s /c ""Thoron.exe" one"', 'cmd.exe /d /s /c "Thoron one"'):
            with self.subTest(line):
                self.assert_started(self.launch(line, extra=path), package, ["one"])

    def test_the_environment_is_passed_on_unchanged(self):
        package = self.package(f"environment {LATIN}")
        found = self.launch(f'"{package / "Thoron.exe"}"')
        self.assert_started(found, package, [])
        self.assertEqual(sorted(n.upper() for n in found["names"]), sorted(n.upper() for n in found["env"]))

    def test_the_launcher_does_not_wait_for_the_browser(self):
        package = self.package(f"no wait {CJK}")
        hold = self.tmp / "hold"
        try:
            found = self.launch(f'"{package / "Thoron.exe"}"', extra={"PORTABLE_TEST_HOLD": str(hold)})
            self.assert_started(found, package, [])     # the launcher has ended (launch waits for it)
            ended = Path(f"{found['record']}.ended")
            self.assertFalse(ended.exists(), "the program was still running when the launcher ended")
        finally:
            hold.write_text("")
        for _ in range(200):
            if ended.exists():
                break
            time.sleep(0.05)
        self.assertTrue(ended.exists())

    def test_a_caller_that_reads_the_output_does_not_wait_for_the_browser(self):
        # the .cmd handed its pipe on to the browser, so a program reading it waited for the whole session
        package = self.package(f"pipe {CJK}")
        hold, record = self.tmp / "hold-pipe", self.tmp / "record-pipe.txt"
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("THORON_LAUNCHER_")}
        env.update(PORTABLE_TEST_RECORD=str(record), PORTABLE_TEST_HOLD=str(hold),
                   THORON_LAUNCHER_MESSAGE_FILE=str(self.tmp / "message-pipe.txt"))
        try:
            done = subprocess.run([str(package / "Thoron.exe"), "one"], env=env, capture_output=True, timeout=30,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b"", b""))
            for _ in range(400):
                if record.is_file():
                    break
                time.sleep(0.05)
            self.assertTrue(record.is_file())
            self.assertFalse(Path(f"{record}.ended").exists(), "the browser had ended before the pipe was read")
        finally:
            hold.write_text("")
        for _ in range(200):
            if Path(f"{record}.ended").exists():
                break
            time.sleep(0.05)

    def test_a_moved_and_renamed_folder(self):
        package = self.package("first place")
        self.assert_started(self.launch(f'"{package / "Thoron.exe"}"'), package, [])
        moved = self.tmp / f"moved {CYRILLIC}" / f"second place & %TEMP% {LATIN}"
        moved.parent.mkdir()
        for _ in range(100):        # the stand-in program may still be ending
            try:
                package.rename(moved)
                break
            except OSError:
                time.sleep(0.05)
        self.assert_started(self.launch(f'"{moved / "Thoron.exe"}"'), moved, [])

    def test_the_version_current_names_starts(self):
        package = self.package(f"two versions {CJK}", versions=(OLDER, VERSION))
        self.assert_started(self.launch(f'"{package / "Thoron.exe"}" one'), package, ["one"], VERSION)
        (package / "Application" / "current").write_bytes(f"{OLDER}\n{VERSION}\n".encode("ascii"))
        self.assert_started(self.launch(f'"{package / "Thoron.exe"}" one'), package, ["one"], OLDER)

    def test_without_the_browser_it_says_so_and_starts_nothing(self):
        package = self.package(f"R&D 100% (new)! {CJK}")
        (package / "Application" / VERSION / "thoron.exe").unlink()
        for current in (f"{VERSION}\n", f"{OLDER}\n", "garbage\n"):     # nothing to fall back to in this layout
            with self.subTest(current):
                (package / "Application" / "current").write_text(current, encoding="ascii")
                found = self.launch(f'"{package / "Thoron.exe"}" one', wait=False)
                self.assertFalse(found["started"])
                self.assertEqual(found["code"], 2)
                self.assertIn("program files are not in this folder", found["said"])
                self.assertEqual(sorted(p.name for p in package.iterdir()), ["Application", "Thoron.exe", "variant"])

    def test_a_profile_folder_that_cannot_be_made_starts_nothing(self):
        # the browser would fall back to the profile folder of the PC: the launcher must not let it. A folder
        # in which no folder may be made stands for a write-protected drive.
        package = self.package(f"R&D 100% (new)! {CYRILLIC}")
        everyone = "*S-1-1-0"
        denied = subprocess.run(["icacls", str(package), "/deny", f"{everyone}:(AD)"], capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if denied.returncode != 0:
            self.skipTest("the folder's rights cannot be changed here")
        self.addCleanup(subprocess.run, ["icacls", str(package), "/remove:d", everyone], capture_output=True,
                        creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            (package / "probe").mkdir()
            self.skipTest("this process passes over the folder's rights (a backup or restore privilege is on)")
        except PermissionError:
            pass
        found = self.launch(f'"{package / "Thoron.exe"}" one', wait=False)
        self.assertFalse(found["started"])
        self.assertEqual(found["code"], 4)
        self.assertIn("write-protected", found["said"])
        self.assertFalse((package / "User Data").exists())

    def test_a_file_in_the_place_of_the_profile_folder_starts_nothing(self):
        # CreateDirectoryW answers ERROR_ALREADY_EXISTS for a file as well, and the browser, given a profile
        # folder it cannot use, would fall back to the PC's own: the launcher asks whether it is a folder
        package = self.package(f"R&D 100% (new)! {CYRILLIC}")
        (package / "User Data").write_bytes(b"in the way")
        found = self.launch(f'"{package / "Thoron.exe"}" one')     # patient: a late start must be seen
        self.assertEqual((package / "User Data").read_bytes(), b"in the way")
        self.assertFalse(found["started"])
        self.assertEqual(found["code"], 4)
        self.assertIn("a file has that name", found["said"])

    def test_the_processor(self):
        package = self.package(f"processor {LATIN}")
        sse4, old = {"THORON_LAUNCHER_ASSUME_CPU": "sse4"}, {"THORON_LAUNCHER_ASSUME_CPU": "old"}
        found = self.launch(f'"{package / "Thoron.exe"}" one', extra=sse4, wait=False)
        self.assertEqual((found["code"], found["started"]), (3, False))
        self.assertIn("AVX2", found["said"])
        self.assertFalse((package / "User Data").exists())
        (package / "variant").unlink()                  # no file: the AVX2 build, the one made first
        self.assertEqual(self.launch(f'"{package / "Thoron.exe"}"', extra=sse4, wait=False)["code"], 3)
        (package / "variant").write_bytes(po.variant_text("win-x64-sse4"))
        self.assert_started(self.launch(f'"{package / "Thoron.exe"}" one', extra=sse4), package, ["one"])
        found = self.launch(f'"{package / "Thoron.exe"}" one', extra=old, wait=False)
        self.assertEqual((found["code"], found["started"]), (3, False))
        self.assertIn("too old", found["said"])

    def test_a_package_portable_py_built(self):
        src = browser(self.tmp / "built" / "Chrome-bin", {"thoron.exe": self.stand_in.read_bytes(),
                                                          f"{VERSION}/chrome.dll": b"dll"})
        _, updater = parts(self.tmp / "built" / "out")
        made = po.build(src, self.tmp / "built" / "dist", "win-x64-avx2", self.launcher, updater)
        place = self.tmp / f"unpacked %TEMP% & 100%! {CJK}"
        with zipfile.ZipFile(made["zip"]) as z:
            z.extractall(place)
        package = place / "ThoronPortable"
        self.assertEqual(po.audit(package), [])
        self.assert_started(self.launch(f'"{package / "Thoron.exe"}" {ARGUMENTS}', cwd=self.tmp / "built"),
                            package, PASSED)
        self.assertTrue((package / "User Data").is_dir())


if __name__ == "__main__":
    unittest.main()
