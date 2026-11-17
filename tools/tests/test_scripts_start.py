# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Every tool runs as a script: `py -3 -I tools/<x>/<tool>.py --help` starts and shows its usage.

Unit tests import a tool as a package, so a tool that cannot find `tools` when it is started as a script (how
every command in the docs starts it) would pass them and still fail for a person. Only tools that use argparse
are started, with --help, which stops them before they do anything.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]


def scripts() -> list[Path]:
    out = []
    for path in sorted(TOOLS.rglob("*.py")):
        if "tests" in path.parts or path.name.startswith("__"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "argparse" in text and 'if __name__ == "__main__"' in text:
            out.append(path)
    return out


class ScriptsStartTests(unittest.TestCase):
    def test_every_tool_starts_as_a_script(self):
        found = scripts()
        self.assertGreater(len(found), 30)
        broken = []
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        for path in found:
            done = subprocess.run([sys.executable, "-I", str(path), "--help"], capture_output=True, text=True,
                                  timeout=60, cwd=TOOLS.parent, env=env)
            if done.returncode != 0 or "usage" not in (done.stdout + done.stderr).lower():
                last = (done.stderr.strip().splitlines() or ["no output"])[-1]
                broken.append(f"{path.relative_to(TOOLS.parent).as_posix()}: exit {done.returncode}: {last[:120]}")
        self.assertEqual(broken, [])


if __name__ == "__main__":
    unittest.main()
