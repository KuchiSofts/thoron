# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Windows portable package and its launcher (ROADMAP P2.8).

The launcher is run for real where cmd.exe is: a small stand-in program takes the browser's place and writes
down the command line, the working directory and the environment it was started with.
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
BROWSER = {"thoron.exe": b"program", "chrome_proxy.exe": b"proxy", f"{VERSION}/chrome.dll": b"dll" * 5000,
           f"{VERSION}/{VERSION}.manifest": b"<assembly/>", f"{VERSION}/resources.pak": b"pak",
           f"{VERSION}/Locales/en-US.pak": b"en", f"{VERSION}/Locales/de.pak": b"de"}
# Folder names built from code points, so this file stays ASCII.
LATIN = "Caf\u00e9 \u00dcbung"
CYRILLIC = "\u041f\u0440\u0438\u043c\u0435\u0440 \u043f\u0430\u043f\u043a\u0438"
CJK = "\u4f8b\u3048 \u30c6\u30b9\u30c8 \ud55c\uae00"
BEYOND = "x\U00020bb7\U0001f600y"      # outside the 16-bit range: two code units each for Windows


def browser(root: Path, files: dict = BROWSER, order=sorted) -> Path:
    for name in order(files):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(files[name])
    return root


class LauncherTextTests(unittest.TestCase):
    def test_the_launcher_keeps_its_own_rules(self):
        self.assertEqual(po.launcher_problems(po.LAUNCHER_TEXT), [])
        raw = po.LAUNCHER_TEXT.encode("ascii")      # ASCII: the same in every code page
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))

    def test_it_starts_the_browser_beside_itself_with_the_profile_beside_itself(self):
        self.assertIn(f'start "" "{po.HERE}Application\\thoron.exe" --user-data-dir="{po.HERE}User Data" '
                      "--no-default-browser-check %*", po.LAUNCHER_TEXT)
        self.assertIn('set "THORON_PORTABLE_DIR=%~dp0"', po.LAUNCHER_TEXT)
        lines = po.LAUNCHER_TEXT.split("\r\n")      # the profile folder is made, and checked, before the start
        self.assertLess(lines.index(po.MAKE), lines.index(f'if not exist "{po.HERE}User Data\\" goto unwritable'))
        self.assertLess(lines.index(f'if not exist "{po.HERE}User Data\\" goto unwritable'), lines.index(po.START))

    def test_every_rule_catches_its_mistake(self):
        good = po.LAUNCHER_TEXT
        mistakes = {
            "not ASCII": good.replace("launcher.", "launcher \u00e9."),
            "CR LF": good.replace("\r\n", "\n"),
            "first line": "rem first\r\n" + good,
            "delayed expansion must": good.replace("DisableDelayedExpansion", "EnableDelayedExpansion"),
            "would be lost": good.replace("pause", "echo Stop!"),
            "comment": good.replace("rem Thoron portable launcher.", "rem Thoron & portable launcher."),
            "no pipe, redirection": good.replace("pause", "pause >nul"),
            "or other change": good.replace("call :locate", f'call :locate\r\ndel /q "{po.HERE}User Data\\lockfile"'),
            "its own profile folder": good.replace(po.MAKE, f'md "{po.HERE}User Data"'),
            "working directory": good.replace("call :locate", 'call :locate\r\ncd /d "%~dp0."'),
            "reads its line twice": good.replace(po.START, "call " + po.START),
            "close the prompt": good.replace("exit /b 1", "exit 1"),
            "exactly one start line": good.replace('start ""', "start"),
            "a variable other": good.replace("pause", 'if exist "%LOCALAPPDATA%\\x" pause'),
            "absolute path": good.replace("pause", 'if exist "C:\\x" pause'),
            "escapes it": good.replace(f'"{po.HERE}User Data"', f'"{po.HERE}"'),
            "odd number of quotes": good.replace("pause", 'echo "'),
        }
        for want, text in mistakes.items():
            with self.subTest(want):
                self.assertTrue([p for p in po.launcher_problems(text) if want in p], po.launcher_problems(text))

    def test_the_arguments_come_last_and_nothing_follows_them(self):
        self.assertTrue(po.START.endswith(" %*"))
        self.assertTrue([p for p in po.launcher_problems(po.LAUNCHER_TEXT.replace(" %*", " %* --last"))
                         if "exactly one start line" in p])

    def test_the_readme(self):
        text = po.readme_text(VERSION)
        self.assertTrue(text.isascii())
        self.assertEqual(text.count("\n"), text.count("\r\n"))
        for part in (po.LAUNCHER, po.BROWSER_DIR, po.PROFILE_DIR, VERSION, "passwords", "update", "delete"):
            self.assertIn(part, text)
        self.assertLess(max(len(line) for line in text.split("\r\n")), 79)


class PackageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.src = browser(self.tmp / "Chrome-bin")
        self.dist = self.tmp / "dist"

    def test_the_package(self):
        made = po.build(self.src, self.dist, "win-x64-avx2")
        package = self.dist / "ThoronPortable"
        self.assertEqual(made["package"], package)
        self.assertEqual(made["version"], VERSION)
        self.assertEqual(sorted(p.name for p in package.iterdir()), ["Application", "README.txt", "Thoron.cmd"])
        self.assertEqual((package / "Thoron.cmd").read_bytes(), po.LAUNCHER_TEXT.encode("ascii"))
        self.assertEqual((package / "README.txt").read_bytes(), po.readme_text(VERSION).encode("ascii"))
        for name, data in BROWSER.items():
            self.assertEqual((package / "Application" / name).read_bytes(), data)
        self.assertEqual(made["files"], len(BROWSER) + 2)
        self.assertEqual(made["zip"], self.dist / f"thoron-{VERSION}-win-x64-avx2-portable.zip")
        self.assertEqual({int(p.stat().st_mtime) for p in package.rglob("*") if p.is_file()}, {po.EPOCH})

    def test_the_package_passes_the_audits(self):
        package = po.build(self.src, self.dist, "win-x64-avx2", zipped=False)["package"]
        self.assertEqual(po.audit(package), [])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(package_audit.main(["--dir", str(package / "Application"), "--platform", "win"]), 0)
            self.assertEqual(po.main(["audit", "--package", str(package)]), 0)
        self.assertIn("package audit: OK", out.getvalue())
        self.assertIn("portable audit: OK", out.getvalue())

    def test_the_zip_holds_the_package_in_one_folder_in_a_stable_order(self):
        made = po.build(self.src, self.dist, "win-x64-avx2")
        with zipfile.ZipFile(made["zip"]) as z:
            infos = z.infolist()
            self.assertIsNone(z.testzip())
            self.assertEqual(z.read(f"ThoronPortable/Application/{VERSION}/chrome.dll"), BROWSER[f"{VERSION}/chrome.dll"])
        names = [i.filename for i in infos]
        self.assertEqual(names, sorted(names))
        self.assertEqual(names, [f"ThoronPortable/{n}" for n in po.files(made["package"])])
        self.assertEqual({i.date_time for i in infos}, {(1980, 1, 1, 0, 0, 0)})
        self.assertEqual({(i.create_system, i.external_attr, i.comment, i.extra) for i in infos}, {(0, 0x20, b"", b"")})
        self.assertFalse([n for n in names if n.endswith("/") or "User Data" in n])

    def test_the_same_files_give_the_same_zip(self):
        first = po.build(self.src, self.dist, "win-x64-avx2")["zip"]
        again = browser(self.tmp / "later" / "Chrome-bin", order=lambda f: sorted(f, reverse=True))
        for path in again.rglob("*"):
            os.utime(path, (1_900_000_000, 1_900_000_000))      # built at another time, written in another order
        second = po.build(again, self.tmp / "dist2", "win-x64-avx2")["zip"]
        self.assertEqual(first.read_bytes(), second.read_bytes())
        changed = browser(self.tmp / "changed" / "Chrome-bin", dict(BROWSER, **{"thoron.exe": b"another"}))
        third = po.build(changed, self.tmp / "dist3", "win-x64-avx2")["zip"]
        self.assertNotEqual(po.sha256(first), po.sha256(third))

    def test_the_time_can_be_set_and_not_before_1980(self):
        made = po.build(self.src, self.dist, "win-x64-avx2", epoch=1_767_225_600)       # 2026-01-01 00:00:00 UTC
        with zipfile.ZipFile(made["zip"]) as z:
            self.assertEqual({i.date_time for i in z.infolist()}, {(2026, 1, 1, 0, 0, 0)})
        with self.assertRaises(po.PortableError):
            po.build(self.src, self.tmp / "dist2", "win-x64-avx2", epoch=0)

    def refused(self, want: str, files: dict | None = None, variant: str = "win-x64-avx2"):
        src = browser(self.tmp / "bad" / "Chrome-bin", files) if files is not None else self.src
        with self.assertRaises(po.PortableError) as raised:
            po.build(src, self.dist, variant)
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
        shutil.rmtree(self.tmp / "bad")
        self.refused("one version folder", {"thoron.exe": b"x"})
        shutil.rmtree(self.tmp / "bad")
        self.refused("chrome.dll is missing", {"thoron.exe": b"x", f"{VERSION}/resources.pak": b"x"})

    def test_profile_data_and_leftovers_are_refused(self):
        for name in ("User Data/Default/Preferences", "User Data/Local State", f"{VERSION}/debug.log",
                     "new_thoron.exe", f"{VERSION}/Crashpad/reports/a.dmp", "Login Data", "lockfile"):
            with self.subTest(name):
                self.refused("profile data or a leftover", dict(BROWSER, **{name: b"x"}))
                shutil.rmtree(self.tmp / "bad")

    def test_a_link_is_refused(self):
        try:
            os.symlink(self.src / "thoron.exe", self.src / "link.exe")
        except OSError:
            self.skipTest("links cannot be made here")
        self.refused("is a link")

    def test_other_refusals(self):
        self.refused("variant must look like", variant="linux-x64-avx2")
        with self.assertRaises(po.PortableError):
            po.build(self.tmp / "nowhere", self.dist, "win-x64-avx2")
        self.assertTrue([p for p in po.source_problems(list(BROWSER) + ["THORON.EXE"]) if "upper and lower" in p])

    def test_a_package_is_never_overwritten(self):
        po.build(self.src, self.dist, "win-x64-avx2")
        before = po.sha256(self.dist / f"thoron-{VERSION}-win-x64-avx2-portable.zip")
        with self.assertRaises(po.PortableError) as raised:
            po.build(self.src, self.dist, "win-x64-avx2")
        self.assertIn("never overwritten", str(raised.exception))
        self.assertEqual(po.sha256(self.dist / f"thoron-{VERSION}-win-x64-avx2-portable.zip"), before)
        self.assertEqual(po.audit(self.dist / "ThoronPortable"), [])

    def test_a_launcher_that_breaks_a_rule_is_not_packaged(self):
        bad = po.LAUNCHER_TEXT.replace("DisableDelayedExpansion", "EnableDelayedExpansion")
        with mock.patch.object(po, "LAUNCHER_TEXT", bad), self.assertRaises(po.PortableError):
            po.build(self.src, self.dist, "win-x64-avx2")
        self.assertEqual(list(self.dist.iterdir()), [])

    def test_the_audit_hook(self):
        package = po.build(self.src, self.dist, "win-x64-avx2", zipped=False)["package"]
        (package / "User Data" / "Default").mkdir(parents=True)
        (package / "User Data" / "Default" / "Preferences").write_text("{}")
        self.assertTrue([p for p in po.audit(package) if "never carries a profile" in p])
        shutil.rmtree(package / "User Data")
        (package / "notes.txt").write_text("x")
        self.assertEqual(po.audit(package), ["not part of a package: notes.txt"])
        (package / "notes.txt").unlink()
        (package / "Thoron.cmd").write_bytes(po.LAUNCHER_TEXT.replace("\r\n", "\n").encode("ascii"))
        self.assertTrue([p for p in po.audit(package) if "not the launcher this tool writes" in p])
        (package / "Thoron.cmd").unlink()
        (package / "README.txt").unlink()
        self.assertEqual(po.audit(package), ["Thoron.cmd is missing", "README.txt is missing"])
        (package / "Application" / "thoron.exe").unlink()
        self.assertTrue([p for p in po.audit(package) if "thoron.exe is missing" in p])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(po.main(["audit", "--package", str(package)]), 1)
            self.assertEqual(po.main(["audit", "--package", str(package / "nowhere")]), 1)

    def test_the_command_line(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(po.main(["build", "--chrome-bin", str(self.src), "--dist", str(self.dist),
                                      "--variant", "win-x64-avx2"]), 0)
            self.assertEqual(po.main(["build", "--chrome-bin", str(self.src), "--dist", str(self.dist),
                                      "--variant", "win-x64-avx2"]), 2)
            self.assertEqual(po.main(["build", "--chrome-bin", str(self.src), "--dist", str(self.tmp / "d2"),
                                      "--variant", "win-x64-avx2", "--no-zip"]), 0)
        self.assertIn(f"ThoronPortable ({len(BROWSER) + 2} files, Thoron {VERSION})", out.getvalue())
        self.assertIn(f"thoron-{VERSION}-win-x64-avx2-portable.zip", out.getvalue())
        self.assertIn("sha256", out.getvalue())
        self.assertIn("never overwritten", err.getvalue())
        self.assertNotIn(str(self.tmp), out.getvalue())
        self.assertEqual([p.name for p in (self.tmp / "d2").iterdir()], ["ThoronPortable"])


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


def _arguments(line: str) -> list[str]:
    """A command line split as Windows splits it for a program (the browser uses the same call)."""
    import ctypes
    shell32, kernel32 = ctypes.windll.shell32, ctypes.windll.kernel32
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    count = ctypes.c_int()
    parts = shell32.CommandLineToArgvW(line, ctypes.byref(count))
    try:
        return [parts[i] for i in range(count.value)]
    finally:
        kernel32.LocalFree(parts)


@unittest.skipUnless(_compiler(), "needs cmd.exe and the C# compiler of Windows")
class LauncherRunTests(unittest.TestCase):
    """The launcher run by cmd.exe, as a double click runs it, from folders with every kind of name."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.tmp = Path(cls._tmp.name)
        (cls.tmp / "stand_in.cs").write_text(STAND_IN, encoding="utf-8")
        cls.stand_in = cls.tmp / "stand_in.exe"
        made = subprocess.run([str(_compiler()), "/nologo", "/target:winexe", f"/out:{cls.stand_in}",
                               str(cls.tmp / "stand_in.cs")], capture_output=True, text=True,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        if made.returncode != 0 or not cls.stand_in.is_file():
            raise unittest.SkipTest(f"the stand-in program could not be made: {made.stdout.strip()[:200]}")
        cls.count = 0

    def package(self, name: str) -> Path:
        type(self).count += 1
        package = self.tmp / f"case{self.count}" / name
        (package / "Application").mkdir(parents=True)
        shutil.copyfile(self.stand_in, package / "Application" / "thoron.exe")
        (package / "Thoron.cmd").write_bytes(po.LAUNCHER_TEXT.encode("ascii"))
        return package

    def launch(self, line: str, cwd: Path | None = None, extra: dict | None = None, wait: bool = True) -> dict:
        """Run a command line; what the launcher answered and what the stand-in program wrote down."""
        type(self).count += 1
        record = self.tmp / f"record{self.count}.txt"
        env = dict(os.environ, PORTABLE_TEST_RECORD=str(record), **(extra or {}))
        env.pop("THORON_PORTABLE_DIR", None)
        log = self.tmp / f"log{self.count}.txt"
        with log.open("wb") as out:     # a file, not a pipe: the started program would keep a pipe open
            code = subprocess.run(line, cwd=cwd or self.tmp, env=env, stdin=subprocess.DEVNULL, stdout=out,
                                  stderr=subprocess.STDOUT, timeout=60,
                                  creationflags=subprocess.CREATE_NO_WINDOW).returncode
        for _ in range(400 if wait else 20):        # patient where a start is expected: a new program is scanned
            if record.is_file():
                break
            time.sleep(0.05)
        found = {"code": code, "said": log.read_bytes().decode("ascii", "replace"), "record": record, "env": env,
                 "started": record.is_file()}
        if found["started"]:
            lines = record.read_text(encoding="utf-8").split("\n")
            found.update(argv=_arguments(lines[0]), cwd=lines[1], names=sorted(n for n in lines[2:] if n))
        return found

    def assert_started(self, found: dict, package: Path, arguments: list[str]):
        self.assertTrue(found["started"], found["said"])
        self.assertEqual(found["code"], 0)
        self.assertEqual(found["argv"], [str(package / "Application" / "thoron.exe"),
                                         f"--user-data-dir={package / 'User Data'}",
                                         "--no-default-browser-check", *arguments])

    def test_folder_names(self):
        names = {"plain": "plain", "spaces": "with two  spaces", "accented Latin": LATIN, "Cyrillic": CYRILLIC,
                 "CJK": CJK, "beyond 16 bits": BEYOND, "ampersand": "R&D", "percent": "100% sure",
                 "percent pair": "50%off%now", "exclamation": "wow! really!", "caret": "a^b^^c",
                 "parentheses": "x (1) y)", "list signs": "a;b,c=d", "quote sign": "it's `this`",
                 "all at once": f"R&D 100% (new)! ^ ;,= {LATIN} {CYRILLIC} {CJK} {BEYOND}"}
        for what, name in names.items():
            with self.subTest(what):
                package = self.package(name)
                found = self.launch(f'"{package / "Thoron.cmd"}" --flag "two words" "https://example.com/?a=1&b=2%20c"')
                self.assert_started(found, package, ["--flag", "two words", "https://example.com/?a=1&b=2%20c"])
                self.assertTrue((package / "User Data").is_dir())

    def test_delayed_expansion_switched_on_for_every_prompt(self):
        package = self.package(f"wow! really! {CJK}")
        found = self.launch(f'cmd.exe /d /v:on /s /c ""{package / "Thoron.cmd"}" "a!b" last!"')
        self.assert_started(found, package, ["a!b", "last!"])

    def test_command_extensions_switched_off(self):
        package = self.package(f"R&D 100% (new)! {CYRILLIC}")
        found = self.launch(f'cmd.exe /d /e:off /s /c ""{package / "Thoron.cmd"}" one"')
        self.assert_started(found, package, ["one"])
        self.assertEqual(found["said"], "")

    def test_code_pages(self):
        package = self.package(f"{LATIN} {CYRILLIC} {CJK} {BEYOND}")
        for page in (437, 850, 932, 936, 1251, 1252, 65001):
            with self.subTest(page):
                found = self.launch(f'cmd.exe /d /s /c "chcp {page}>nul&"{package / "Thoron.cmd"}" one"')
                self.assert_started(found, package, ["one"])

    def test_the_working_directory_is_left_alone_and_nothing_is_written(self):
        package = self.package(f"R&D 100% (new)! {LATIN}")
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        found = self.launch(f'"{package / "Thoron.cmd"}" page.html', cwd=elsewhere)
        self.assert_started(found, package, ["page.html"])
        self.assertEqual(Path(found["cwd"]), elsewhere)
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertEqual(sorted(p.name for p in package.iterdir()), ["Application", "Thoron.cmd", "User Data"])
        self.assertEqual(list((package / "User Data").iterdir()), [])     # made by the launcher, and left empty
        self.assertEqual(sorted(p.name for p in package.parent.iterdir()), [package.name])
        found = self.launch('cmd.exe /d /s /c ".\\Thoron.cmd one"', cwd=package)
        self.assert_started(found, package, ["one"])

    def test_a_start_by_the_bare_name_through_the_search_path(self):
        package = self.package(f"on the path {CYRILLIC}")
        path = {"PATH": f"{package}{os.pathsep}{os.environ['PATH']}"}
        for line in ('cmd.exe /d /s /c ""Thoron.cmd" one"', 'cmd.exe /d /s /c ""Thoron" one"',
                     'cmd.exe /d /s /c "Thoron.cmd one"', 'cmd.exe /d /s /c "Thoron one"'):
            with self.subTest(line):
                self.assert_started(self.launch(line, extra=path), package, ["one"])

    def test_called_from_another_batch_file(self):
        package = self.package(f"called {CJK}")
        elsewhere = self.tmp / "from here"
        elsewhere.mkdir()
        caller = self.tmp / "caller.cmd"
        caller.write_bytes(b'@echo off\r\nsetlocal EnableDelayedExpansion\r\ncd /d "%~1"\r\ncmd /c exit 7\r\n'
                           b'call "%~2" one\r\necho level=!errorlevel!\r\n')
        found = self.launch(f'cmd.exe /d /s /c ""{caller}" "{elsewhere}" "{package / "Thoron.cmd"}""')
        self.assert_started(found, package, ["one"])
        self.assertEqual(found["said"].strip(), "level=0")      # not the caller's stale 7, and the caller goes on
        self.assertEqual(Path(found["cwd"]), elsewhere)

    def test_arguments_pass_as_they_are(self):
        package = self.package(f"R&D 100% (new)! {CJK}")
        cases = (("", []), ('""', [""]), ("a b  c", ["a", "b", "c"]), ('"100%" a%20b 5%', ["100%", "a%20b", "5%"]),
                 ("^%OS^% ^%nosuch^%", ["%OS%", "%nosuch%"]),        # the launcher puts no variable into them
                 ("wow! !x! a!b", ["wow!", "!x!", "a!b"]), ('"a^b" "x&y" "p|q" "<r>"', ["a^b", "x&y", "p|q", "<r>"]),
                 ('"C:\\folder with space\\\\"', ["C:\\folder with space\\"]),
                 ('--a=b --c="d e" a;b a,b (x) y)', ["--a=b", "--c=d e", "a;b", "a,b", "(x)", "y)"]),
                 ('--user-data-dir="C:\\other one"', ["--user-data-dir=C:\\other one"]),
                 (f'"{CYRILLIC}" {CJK}', [CYRILLIC, *CJK.split()]))
        for text, want in cases:
            with self.subTest(text):
                self.assert_started(self.launch(f'"{package / "Thoron.cmd"}" {text}'), package, want)

    def test_the_environment_is_passed_on_unchanged(self):
        package = self.package(f"environment {LATIN}")
        found = self.launch(f'"{package / "Thoron.cmd"}"')
        self.assert_started(found, package, [])
        self.assertEqual(sorted(n.upper() for n in found["names"]), sorted(n.upper() for n in found["env"]))

    def test_the_launcher_does_not_wait_for_the_browser(self):
        package = self.package(f"no wait {CJK}")
        hold = self.tmp / "hold"
        try:
            found = self.launch(f'"{package / "Thoron.cmd"}"', extra={"PORTABLE_TEST_HOLD": str(hold)})
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

    def test_a_moved_and_renamed_folder(self):
        package = self.package("first place")
        self.assert_started(self.launch(f'"{package / "Thoron.cmd"}"'), package, [])
        moved = self.tmp / f"moved {CYRILLIC}" / f"second place & {LATIN}"
        moved.parent.mkdir()
        for _ in range(100):        # the stand-in program may still be ending
            try:
                package.rename(moved)
                break
            except OSError:
                time.sleep(0.05)
        self.assert_started(self.launch(f'"{moved / "Thoron.cmd"}"'), moved, [])

    def test_without_the_browser_it_says_so_and_starts_nothing(self):
        package = self.package(f"R&D 100% (new)! {CJK}")
        (package / "Application" / "thoron.exe").unlink()
        found = self.launch(f'"{package / "Thoron.cmd"}" one', wait=False)
        self.assertFalse(found["started"])
        self.assertEqual(found["code"], 1)
        self.assertIn("Thoron cannot start", found["said"])
        self.assertIn("Extract the whole package", found["said"])
        self.assertEqual(sorted(p.name for p in package.iterdir()), ["Application", "Thoron.cmd"])

    def test_a_profile_folder_that_cannot_be_made_starts_nothing(self):
        # the browser would fall back to the profile folder of the PC: the launcher must not let it
        package = self.package(f"R&D 100% (new)! {CYRILLIC}")
        (package / "User Data").write_bytes(b"in the way")
        found = self.launch(f'"{package / "Thoron.cmd"}" one', wait=False)
        self.assertFalse(found["started"])
        self.assertEqual(found["code"], 1)
        self.assertIn("User Data cannot be made", found["said"])
        self.assertEqual((package / "User Data").read_bytes(), b"in the way")

    def test_known_limit_a_folder_named_after_an_environment_variable(self):
        # cmd.exe puts the variable's value into the path before any .cmd runs: only a program avoids it (P3.12)
        package = self.package("a%OS%b")
        found = self.launch(f'"{package / "Thoron.cmd"}" one', wait=False)
        self.assertFalse(found["started"])
        self.assertNotEqual(found["code"], 0)
        self.assertEqual(sorted(p.name for p in package.iterdir()), ["Application", "Thoron.cmd"])


if __name__ == "__main__":
    unittest.main()
