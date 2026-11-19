#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Fuzzing of the session reader (ROADMAP P3.15): mutated golden files must never crash or hang it.

Each input is one of the golden session files (`tools/migrate/tests/data/sessions/*/`) or a small made-up one,
changed by one to four mutations: flipped bits, bytes set to edge values, cuts, splices from another file,
huge lengths written over a command's size or a pickle's length field, commands dropped, doubled or given
another id, random bytes put in. Every input is read as a `Session_` and as a `Tabs_` file, and its saved-group
links are taken out as the import does. Only `SessionError` may come out; anything else is a crash. Inputs that
read must give JSON, the unlinking must not change their reading, and copying a file command by command must
give the same bytes. An input slower than --slow seconds counts as a hang.

Input N of a run with seed S is made from the seed S + N, so a failure repeats: the seed is printed and the input
saved to --out (`crash-<seed>.bin`); `--repeat <seed>` runs that one input again and shows the error.
    py -3 -I tools/migrate/fuzz_sessions.py --minutes 20 [--seed 1] [--out <folder>]
    py -3 -I tools/migrate/fuzz_sessions.py --repeat 123456
For a long run in the background (PowerShell), with the output in a file:
    Start-Process py -ArgumentList '-3','-I','tools/migrate/fuzz_sessions.py','--minutes','1440','--out','<folder>'
        -RedirectStandardOutput <folder>\\fuzz.log -WindowStyle Hidden
Exit status 0 when nothing crashed or hung.
"""
from __future__ import annotations

import argparse
import json
import random
import struct
import sys
import time
import traceback
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.migrate import sessions as s  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "tests" / "data" / "sessions"
EDGE_BYTES = (0x00, 0x01, 0x7F, 0x80, 0xFE, 0xFF)
HUGE = (0xFFFF, 0xFFFE, 0x8000, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0x40000000)


def made_up() -> list[bytes]:
    """Small files that reach the commands the golden files do not hold."""
    nav = s.navigation_pickle
    session = s.snss([
        s.command(s.S_WINDOW_TYPE, struct.pack("<ii", 1, 0)),
        s.command(s.S_WINDOW_BOUNDS2, struct.pack("<iiiii?3x", 1, 0, 0, 640, 480, True)),
        s.command(s.S_TAB_WINDOW, struct.pack("<ii", 1, 2)),
        s.command(s.S_NAVIGATION, nav(2, 0, "http://127.0.0.1/a", "a")),
        s.command(s.S_NAVIGATION, nav(2, 1, "http://127.0.0.1/b", "b")),
        s.command(s.S_NAVIGATION, nav(2, 2, "http://127.0.0.1/c", "c")),
        s.command(s.S_PRUNED, struct.pack("<iii", 2, 0, 1)),
        s.command(s.S_PRUNED_BACK, struct.pack("<ii", 2, 1)),
        s.command(s.S_PRUNED_FRONT, struct.pack("<ii", 2, 1)),
        s.command(s.S_TAB_DATA, s.PickleWriter().int(2).int(2).string("k").string("v").string("k2").string("v2")
                  .done()),
        s.command(s.S_USER_AGENT2, s.PickleWriter().int(2).string("ua").bool(True).string("meta").done()),
        s.command(s.S_SPLIT_DATA, s.PickleWriter().u64(1).u64(2).double(0.5).string("Vertical").done()),
        s.command(s.S_TAB_EXTRA, s.PickleWriter().int(2).string("k").string("v").done()),
        s.command(s.S_PLATFORM_ID, s.PickleWriter().string("id").done()),
        s.command(s.S_TAB_CLOSED, struct.pack("<i4xq", 9, 0)),
        s.command(s.S_WINDOW_CLOSED, struct.pack("<i4xq", 9, 0)),
    ])
    closed = s.snss([
        s.command(s.T_WINDOW_OLD, struct.pack("<iii4xq", 5, 0, 1, 0)),
        s.command(s.T_SELECTED_NAVIGATION, struct.pack("<ii", 6, 0)),
        s.command(s.T_NAVIGATION, nav(6, 0, "http://127.0.0.1/w", "w")),
        s.command(s.T_CREATE_GROUP, s.PickleWriter().u64(3).u64(4).int(7).int(1).int(5).string16("g").u32(4)
                  .bool(True).string("0e4c1a34-5f7c-4b1e-9d2a-6f3b8c2d1e0f").i64(0).done()),
        s.command(s.T_SELECTED_NAVIGATION, struct.pack("<iiq", 8, 0, 0)),
        s.command(s.T_NAVIGATION, nav(8, 0, "http://127.0.0.1/g", "g")),
        s.command(s.T_GROUP_DATA, s.PickleWriter().u64(3).u64(4).string16("g").u32(4).bool(True)
                  .string("0e4c1a34-5f7c-4b1e-9d2a-6f3b8c2d1e0f").bool(True).done()),
        s.command(s.T_CREATE_SPLIT, s.PickleWriter().u64(1).u64(2).int(9).i64(0).double(0.5).int(0).done()),
        s.command(s.T_RESTORED, struct.pack("<i", 9)),
    ])
    return [session, closed]


def corpus(folder: Path = GOLDEN) -> list[bytes]:
    files = sorted(p for p in folder.glob("*/*") if p.name.startswith(("Session_", "Tabs_")))
    return [p.read_bytes() for p in files] + made_up()


def _command_starts(data: bytes) -> list[int]:
    starts, pos = [], 8
    while len(data) - pos >= 2:
        size = data[pos] | (data[pos + 1] << 8)
        if size < 1 or size > len(data) - pos - 2:
            break
        starts.append(pos)
        pos += 2 + size
    return starts


def mutate(rng: random.Random, inputs: list[bytes]) -> bytes:
    data = bytearray(rng.choice(inputs))
    for _ in range(rng.randint(1, 4)):
        kind = rng.randrange(10)
        if not data:
            data = bytearray(rng.choice(inputs))
        if kind == 0:                                           # flip a few bits
            for _ in range(rng.randint(1, 8)):
                i = rng.randrange(len(data))
                data[i] ^= 1 << rng.randrange(8)
        elif kind == 1:                                         # a byte set to an edge value
            data[rng.randrange(len(data))] = rng.choice(EDGE_BYTES)
        elif kind == 2:                                         # a cut
            del data[rng.randrange(len(data)):]
        elif kind == 3:                                         # a splice from another input
            other = rng.choice(inputs)
            a = rng.randrange(len(other))
            piece = other[a:a + rng.randint(1, 512)]
            at = rng.randrange(len(data) + 1)
            data[at:at + (len(piece) if rng.random() < 0.5 else 0)] = piece
        elif kind in (4, 5):                                    # a huge length over a size or a pickle field
            starts = _command_starts(bytes(data))
            if starts and kind == 4:
                at = rng.choice(starts)
                data[at:at + 2] = struct.pack("<H", rng.choice(HUGE) & 0xFFFF)
            elif starts:
                at = rng.choice(starts) + 3 + 4 * rng.randrange(0, 8)
                if at + 4 <= len(data):
                    data[at:at + 4] = struct.pack("<I", rng.choice(HUGE))
        elif kind == 6:                                         # a command dropped
            starts = _command_starts(bytes(data))
            if len(starts) > 1:
                i = rng.randrange(len(starts) - 1)
                del data[starts[i]:starts[i + 1]]
        elif kind == 7:                                         # a run of commands doubled
            starts = _command_starts(bytes(data))
            if len(starts) > 2:
                i = rng.randrange(len(starts) - 1)
                j = rng.randrange(i + 1, len(starts))
                data[starts[j]:starts[j]] = data[starts[i]:starts[j]]
        elif kind == 8:                                         # a command given another id
            starts = _command_starts(bytes(data))
            if starts:
                data[rng.choice(starts) + 2] = rng.randrange(256) if rng.random() < 0.3 else rng.randrange(40)
        else:                                                   # random bytes put in
            at = rng.randrange(len(data) + 1)
            data[at:at] = rng.randbytes(rng.randint(1, 64))
    return bytes(data)


def check(data: bytes) -> None:
    """Read `data` every way the import does; raise AssertionError (or anything else) on a broken promise."""
    for reader, prefix in ((s.read_session, "Session"), (s.read_closed, "Tabs")):
        try:
            reading = reader(data)
        except s.SessionError:
            continue
        json.dumps(reading, ensure_ascii=False)
        unlinked, _ = s.unlink_saved_groups(data, prefix)
        assert reader(unlinked) == reading, f"unlinking saved groups changed the {prefix} reading"
        copy, _ = s.prepare_copy(data, prefix)
        copied = reader(copy)
        assert s.essence(copied) == s.essence(reading), f"the import's copy reads unlike the {prefix} source"
        assert not copied["skipped"]["unknown"] and not copied["skipped"]["malformed"], \
            f"the import's copy of the {prefix} file still holds what Thoron would stop at"
    try:
        same = s.rewrite(data, lambda cid, payload: payload)
    except s.SessionError:
        return
    assert same == data, "copying the file command by command changed its bytes"


def run(minutes: float, seed: int, out: Path | None, slow: float, report_every: float = 60) -> dict:
    inputs = corpus()
    end = time.monotonic() + minutes * 60
    next_report = time.monotonic() + report_every
    count, crashes, hangs, slowest, slowest_seed = 0, [], [], 0.0, None
    print(f"fuzz: seed {seed}, {len(inputs)} inputs to start from, {minutes:g} minute(s)", flush=True)
    while time.monotonic() < end:
        input_seed = seed + count
        data = mutate(random.Random(input_seed), inputs)
        # The reader's own processor time: on a busy PC the wall clock also counts the time this process
        # waited for a processor, which says nothing about the input (a loop that never ends still counts).
        started = time.process_time()
        try:
            check(data)
        except Exception as exc:                                 # anything at all is a finding
            crashes.append(input_seed)
            print(f"fuzz: CRASH at seed {input_seed}: {type(exc).__name__}: {exc}", flush=True)
            if out is not None:
                out.mkdir(parents=True, exist_ok=True)
                (out / f"crash-{input_seed}.bin").write_bytes(data)
        took = time.process_time() - started
        if took > slowest:
            slowest, slowest_seed = took, input_seed
            if took > 1.0:
                print(f"fuzz: slowest so far: seed {input_seed}, {took * 1000:.0f} ms of processor time",
                      flush=True)
        if took > slow:
            hangs.append(input_seed)
            print(f"fuzz: HANG at seed {input_seed}: {took:.1f} s", flush=True)
            if out is not None:
                out.mkdir(parents=True, exist_ok=True)
                (out / f"slow-{input_seed}.bin").write_bytes(data)
        count += 1
        if time.monotonic() >= next_report:
            print(f"fuzz: {count} inputs, {len(crashes)} crash(es), {len(hangs)} hang(s), slowest "
                  f"{slowest * 1000:.0f} ms (seed {slowest_seed})", flush=True)
            next_report += report_every
    return {"seed": seed, "inputs": count, "crashes": crashes, "hangs": hangs, "slowest_ms": round(slowest * 1000),
            "slowest_seed": slowest_seed}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--minutes", type=float, default=1.0, help="how long to run")
    p.add_argument("--seed", type=int, help="the first seed (default: from the clock, printed)")
    p.add_argument("--out", type=Path, help="folder for the inputs that crash or hang")
    p.add_argument("--slow", type=float, default=10.0, help="seconds after which an input counts as a hang")
    p.add_argument("--repeat", type=int, help="run the input of this one seed again and show what happens")
    a = p.parse_args(argv)
    if a.repeat is not None:
        data = mutate(random.Random(a.repeat), corpus())
        print(f"fuzz: seed {a.repeat}, {len(data)} bytes")
        try:
            check(data)
        except Exception:
            traceback.print_exc()
            return 1
        print("fuzz: no crash")
        return 0
    seed = a.seed if a.seed is not None else int(time.time())
    result = run(a.minutes, seed, a.out, a.slow)
    print(f"fuzz: done, {result['inputs']} inputs from seed {result['seed']}, {len(result['crashes'])} crash(es), "
          f"{len(result['hangs'])} hang(s), slowest {result['slowest_ms']} ms of processor time (seed "
          f"{result['slowest_seed']})", flush=True)
    for found in result["crashes"] + result["hangs"]:
        print(f"fuzz: repeat with --repeat {found}")
    return 0 if not result["crashes"] and not result["hangs"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
