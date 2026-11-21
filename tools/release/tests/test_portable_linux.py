# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Linux portable package (ROADMAP P2.9, P3.12): made from the .deb, its layout, its launcher, its audit."""
import io
import lzma
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from tools.release import portable_linux as pl
from tools.release.tests.test_elf_check import elf

VERSION = "158.0.8127.6504"


def deb(files: dict, version: str = VERSION, links: dict | None = None, modes: dict | None = None) -> bytes:
    def tar_of(entries: dict, link_entries: dict | None = None) -> bytes:
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w") as tar:
            for name, data in entries.items():
                info = tarfile.TarInfo("./" + name)
                info.size, info.mode = len(data), (modes or {}).get(name, 0o755 if name.endswith("thoron") else 0o644)
                tar.addfile(info, io.BytesIO(data))
            for name, target in (link_entries or {}).items():
                info = tarfile.TarInfo("./" + name)
                info.type, info.linkname = tarfile.SYMTYPE, target
                tar.addfile(info)
        return raw.getvalue()

    def member(n: str, content: bytes) -> bytes:
        head = f"{n + '/':<16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(content):<10}`\n".encode()
        return head + content + (b"\n" if len(content) % 2 else b"")
    control = tar_of({"control": f"Package: thoron-browser\nVersion: {version}-1\nArchitecture: amd64\n".encode()})
    data = tar_of(files, links)
    return (b"!<arch>\n" + member("debian-binary", b"2.0\n") + member("control.tar.xz", lzma.compress(control))
            + member("data.tar.xz", lzma.compress(data)))


def the_deb() -> dict:
    return {"opt/kuchisofts/thoron/thoron": elf(62, "/lib64/ld-linux-x86-64.so.2"),
            "opt/kuchisofts/thoron/libEGL.so": elf(62), "opt/kuchisofts/thoron/resources.pak": b"PAK",
            "opt/kuchisofts/thoron/locales/en-US.pak": b"PAK", "usr/bin/thoron": b"#!/bin/sh\n",
            "usr/share/applications/thoron.desktop": b"[Desktop Entry]\n"}


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def make(self, files=None, variant="linux-x64-avx2", **kw) -> Path:
        path = self.dir / "thoron.deb"
        path.write_bytes(deb(files or the_deb(), **kw))
        return pl.build(path, self.dir / "dist", variant)

    def test_the_layout_comes_from_the_deb(self):
        archive = self.make()
        self.assertEqual(archive.name, f"thoron-{VERSION}-linux-x64-avx2-portable.tar.xz")
        with tarfile.open(archive) as tar:
            names = tar.getnames()
            self.assertIn("ThoronPortable/thoron", names)
            self.assertIn(f"ThoronPortable/Application/{VERSION}/thoron", names)
            self.assertIn(f"ThoronPortable/Application/{VERSION}/locales/en-US.pak", names)
            self.assertNotIn(f"ThoronPortable/Application/{VERSION}/usr", " ".join(names))  # only /opt/kuchisofts/thoron
            self.assertEqual(tar.extractfile("ThoronPortable/Application/current").read(), f"{VERSION}\n".encode())
            self.assertEqual(tar.extractfile("ThoronPortable/variant").read(), b"linux-x64-avx2\n")
            self.assertTrue(tar.getmember("ThoronPortable/thoron").mode & 0o100)
            self.assertTrue({m.mtime for m in tar.getmembers()} == {pl.EPOCH})
        self.assertEqual(pl.audit(archive, "linux-x64-avx2"), [])

    def test_the_updater_goes_beside_the_program(self):
        updater = self.dir / "thoron_update"
        updater.write_bytes(elf(62, "/lib64/ld-linux-x86-64.so.2"))
        path = self.dir / "thoron.deb"
        path.write_bytes(deb(the_deb()))
        archive = pl.build(path, self.dir / "dist", "linux-x64-avx2", updater=updater)
        with tarfile.open(archive) as tar:
            item = tar.getmember(f"ThoronPortable/Application/{VERSION}/thoron_update")
            self.assertTrue(item.mode & 0o100)
        with self.assertRaises(pl.PackageError):
            pl.build(path, self.dir / "dist", "linux-x64-avx2", updater=self.dir / "missing")

    def test_the_same_deb_gives_the_same_bytes(self):
        first = self.make().read_bytes()
        self.assertEqual(self.make().read_bytes(), first)

    def test_a_set_user_id_helper_loses_its_bit(self):
        files = {**the_deb(), "opt/kuchisofts/thoron/chrome-sandbox": elf(62)}
        archive = self.make(files, modes={"opt/kuchisofts/thoron/chrome-sandbox": 0o4755})
        with tarfile.open(archive) as tar:
            self.assertEqual(tar.getmember(f"ThoronPortable/Application/{VERSION}/chrome-sandbox").mode & 0o6000, 0)

    def test_what_cannot_be_a_portable_package_is_refused(self):
        with self.assertRaises(pl.PackageError):
            self.make({"usr/bin/thoron": b"x"})
        with self.assertRaises(pl.PackageError):          # an x64 build in the ARM64 package
            self.make(variant="linux-arm64-armv8")
        with self.assertRaises(pl.PackageError):
            self.make(links={"opt/kuchisofts/thoron/escape": "../../../etc/passwd"})
        with self.assertRaises(pl.PackageError):
            self.make(version="158.0")

    def test_the_audit_finds_a_profile_in_the_package(self):
        archive = self.make()
        with tarfile.open(archive) as tar:
            members = [(m, tar.extractfile(m).read() if m.isfile() else None) for m in tar.getmembers()]
        bad = self.dir / "bad.tar.xz"
        with lzma.open(bad, "wb") as xz, tarfile.open(fileobj=xz, mode="w") as tar:
            for m, data in members:
                tar.addfile(m, io.BytesIO(data) if data is not None else None)
            info = tarfile.TarInfo("ThoronPortable/User Data/Default/Login Data")
            tar.addfile(info, io.BytesIO(b""))
        problems = pl.audit(bad)
        self.assertTrue(any("profile" in p for p in problems), problems)


@unittest.skipUnless(shutil.which("sh") and os.name != "nt", "the launcher runs on Linux")
class LauncherTests(unittest.TestCase):
    def test_it_starts_the_current_version_with_the_profile_in_the_folder(self):
        with tempfile.TemporaryDirectory(prefix="Thoron portable é ") as d:
            root = Path(d) / "ThoronPortable"
            program = root / "Application" / VERSION / "thoron"
            program.parent.mkdir(parents=True)
            program.write_text('#!/bin/sh\nfor a in "$@"; do echo "[$a]"; done\n')
            program.chmod(0o755)
            (root / "Application" / "current").write_text(VERSION + "\n")
            (root / "variant").write_text("linux-x64-sse4\n")
            (root / "thoron").write_text(pl.LAUNCHER_TEXT)
            (root / "thoron").chmod(0o755)
            out = subprocess.run([str(root / "thoron"), "a b", "c'd"], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn(f"[--user-data-dir={root}/User Data]", out.stdout)
            self.assertIn("[a b]", out.stdout)
            self.assertIn("[c'd]", out.stdout)
            self.assertTrue((root / "User Data").is_dir())
            (root / "Application" / "current").write_text("../evil\n")
            self.assertEqual(subprocess.run([str(root / "thoron")], capture_output=True).returncode, 4)


@unittest.skipUnless(shutil.which("sh") and os.name != "nt", "the installer runs on Linux")
class PerUserInstallTests(unittest.TestCase):
    """install-for-this-user (P3.10): the program into ~/.local/share/thoron, a menu entry and a systemd user timer,
    no administrator rights; --remove takes them away and keeps the profile."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="per user é "))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.home = self.dir / "home"
        self.root = self.dir / "ThoronPortable"
        program = self.root / "Application" / VERSION / "thoron"
        program.parent.mkdir(parents=True)
        program.write_text('#!/bin/sh\nfor a in "$@"; do echo "[$a]"; done\n')
        program.chmod(0o755)
        (self.root / "Application" / "current").write_text(VERSION + "\n")
        (self.root / "variant").write_text("linux-x64-sse4\n")
        (self.root / "README.txt").write_text("readme\n")
        (self.root / "User Data").mkdir()
        (self.root / "User Data" / "Local State").write_text("{}")
        for name, text in (("thoron", pl.LAUNCHER_TEXT), (pl.INSTALLER, pl.INSTALLER_TEXT)):
            (self.root / name).write_text(text)
            (self.root / name).chmod(0o755)
        # a systemctl that writes down what it is asked
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        (self.bin / "systemctl").write_text('#!/bin/sh\necho "$@" >> "$SYSTEMCTL_LOG"\n')
        (self.bin / "systemctl").chmod(0o755)
        self.log = self.dir / "systemctl.log"

    def run_it(self, script: Path, *args: str):
        env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin", "SYSTEMCTL_LOG": str(self.log)}
        return subprocess.run([str(script), *args], capture_output=True, text=True, env=env)

    def test_it_installs_for_this_user_and_removes_again(self):
        out = self.run_it(self.root / pl.INSTALLER)
        self.assertEqual(out.returncode, 0, out.stderr)
        dest = self.home / ".local/share/thoron"
        self.assertTrue((dest / "Application" / VERSION / "thoron").is_file())
        self.assertTrue((dest / pl.PER_USER).is_file())
        self.assertFalse((dest / "User Data").exists())             # never a profile
        units = self.home / ".config/systemd/user"
        service = (units / "thoron-update.service").read_text()
        self.assertIn(f'ExecStart="{dest}/thoron" --headless=new', service)
        self.assertIn("--thoron-scheduled-update", service)
        self.assertIn("OnCalendar=daily", (units / "thoron-update.timer").read_text())
        self.assertIn(f'Exec="{dest}/thoron" %U',
                      (self.home / ".local/share/applications/thoron-user.desktop").read_text())
        self.assertIn("--user enable --now thoron-update.timer", self.log.read_text())
        # the installed copy's launcher: the usual profile, no profile folder of its own
        started = self.run_it(dest / "thoron", "x")
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertNotIn("--user-data-dir", started.stdout)
        self.assertIn("[x]", started.stdout)
        self.assertFalse((dest / "User Data").exists())
        # the profile stays when Thoron goes
        profile = self.home / ".config/thoron"
        profile.mkdir(parents=True)
        removed = self.run_it(dest / pl.INSTALLER, "--remove")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertFalse(dest.exists())
        self.assertFalse((units / "thoron-update.timer").exists())
        self.assertTrue(profile.is_dir())
        self.assertIn("--user disable --now thoron-update.timer", self.log.read_text())

    def test_the_installed_copy_does_not_install_itself(self):
        self.assertEqual(self.run_it(self.root / pl.INSTALLER).returncode, 0)
        again = self.run_it(self.home / ".local/share/thoron" / pl.INSTALLER)
        self.assertEqual(again.returncode, 2)


class LauncherTextTests(unittest.TestCase):
    def test_it_never_turns_the_sandbox_off_and_passes_arguments_as_they_are(self):
        self.assertNotIn("--no-sandbox", pl.LAUNCHER_TEXT)
        self.assertIn('exec "$program" --user-data-dir="$here/User Data" "$@"', pl.LAUNCHER_TEXT)
        self.assertNotIn("eval", pl.LAUNCHER_TEXT)


if __name__ == "__main__":
    unittest.main()
