#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Fuzzing of the Firefox session reader (ROADMAP P4.8): mutated session files must never crash or hang it.

Each input starts from the golden Firefox session (`tools/migrate/tests/data/sessions/firefox/`) or a small
made-up one, and is changed at one of three depths:
    file       the mozLz4 bytes themselves: flipped bits, edge bytes, cuts, a wrong size in the header, a huge
               literal or copy length, an offset that reaches before the start;
    text       the JSON text inside, packed again: flipped bits and edge bytes, cuts, splices, deep nesting,
               long strings, lone surrogates;
    values     the parsed JSON: a value replaced by one of another type or an edge value (huge numbers,
               negative indexes, empty and very long strings, other schemes, deep lists), an item dropped or
               doubled.
Only `FirefoxSessionError` may come out. An input that reads must give JSON, and the Thoron session file made
from it (`to_snss`) must read back, with Chromium's rules (`sessions.read_session`), as the same windows, tabs,
pages and groups. An input slower than --slow seconds counts as a hang.

Input N of a run with seed S is made from the seed S + N, so a failure repeats: the seed is printed and the input
saved to --out (`crash-<seed>.bin`); `--repeat <seed>` runs that one input again and shows the error.
    py -3 -I tools/migrate/fuzz_firefox_sessions.py --minutes 20 [--seed 1] [--out <folder>]
    py -3 -I tools/migrate/fuzz_firefox_sessions.py --repeat 123456
Exit status 0 when nothing crashed or hung.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import struct
import sys
import time
import traceback
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.migrate import firefox_sessions as fs  # noqa: E402
from tools.migrate import sessions as s  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "tests" / "data" / "sessions" / "firefox" / "sessionstore.jsonlz4"
EDGE_BYTES = (0x00, 0x01, 0x0F, 0x10, 0x7F, 0x80, 0xF0, 0xFE, 0xFF)
EDGE_VALUES = (None, True, False, 0, -1, 1, 2 ** 31, -2 ** 31 - 1, 2 ** 63, 1e308, -0.5, "", "x" * 70000,
               "about:newtab", "javascript:alert(1)", "data:text/html,x", "https://example.com/" + "a" * 20000,
               "\ud800", [], {}, [[[[[]]]]], {"entries": None}, "gray", "unknown-colour")


def made_up() -> list[dict]:
    """Small sessions that reach the corners the golden file does not."""
    page = lambda n: {"url": f"https://example.com/{n}", "title": f"Page {n}"}
    return [
        {"windows": [{"tabs": [{"entries": [page(i) for i in range(120)], "index": 60}], "selected": 1}]},
        {"windows": [{"tabs": [{"entries": [page(1)], "pinned": True, "groupId": "g"},
                               {"entries": [page(2)], "groupId": "g"}, {"entries": [page(3)]},
                               {"entries": [page(4)], "groupId": "g"}],
                      "groups": [{"id": "g", "name": "G", "color": "purple", "collapsed": True}], "selected": 9}],
         "selectedWindow": 7},
        {"windows": [{"tabs": [{"entries": [{"url": "about:home"}]}]},
                     {"tabs": [{"entries": [{"url": "file:///C:/x.html", "title": "\ud83d\ude00"}],
                                "index": 0}]}]},
    ]


def corpus() -> list[dict]:
    return [json.loads(fs.decode_mozlz4(GOLDEN.read_bytes()))] + made_up()


def _paths(value, path=()):
    """Every place in a JSON value, as a path of keys and indexes."""
    yield path
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _paths(v, path + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _paths(v, path + (i,))


def _mutate_values(rng: random.Random, state) -> object:
    state = copy.deepcopy(state)
    for _ in range(rng.randint(1, 4)):
        places = list(_paths(state))
        place = rng.choice(places)
        if not place:
            state = rng.choice(EDGE_VALUES)
            continue
        parent = state
        try:
            for key in place[:-1]:
                parent = parent[key]
        except (KeyError, IndexError, TypeError):
            continue
        key = place[-1]
        choice = rng.random()
        if choice < 0.6:
            parent[key] = copy.deepcopy(rng.choice(EDGE_VALUES))
        elif choice < 0.8 and isinstance(parent, list):
            del parent[key]
        elif isinstance(parent, list):
            parent.insert(key, copy.deepcopy(parent[key]))
        elif isinstance(parent, dict):
            del parent[key]
    return state


def _mutate_bytes(rng: random.Random, data: bytearray, other: bytes) -> bytearray:
    for _ in range(rng.randint(1, 4)):
        if not data:
            data += bytes(rng.randrange(256) for _ in range(rng.randint(1, 16)))
            continue
        kind = rng.randrange(5)
        at = rng.randrange(len(data))
        if kind == 0:
            data[at] ^= 1 << rng.randrange(8)
        elif kind == 1:
            data[at] = rng.choice(EDGE_BYTES)
        elif kind == 2:
            del data[at:at + rng.randint(1, 64)]
        elif kind == 3 and other:
            start = rng.randrange(len(other))
            data[at:at] = other[start:start + rng.randint(1, 256)]
        else:
            data[at:at] = bytes(rng.randrange(256) for _ in range(rng.randint(1, 16)))
    return data


def mutate(rng: random.Random, states: list) -> bytes:
    state = rng.choice(states)
    depth = rng.randrange(3)
    if depth == 2:
        return fs.encode_mozlz4(json.dumps(_mutate_values(rng, state), ensure_ascii=rng.random() < 0.5)
                                .encode("utf-8", "surrogatepass"))
    text = json.dumps(state, ensure_ascii=False).encode("utf-8", "surrogatepass")
    if depth == 1:
        if rng.random() < 0.1:
            text = b"[" * rng.choice((100, 1000, 100000)) + text
        other = json.dumps(rng.choice(states)).encode("utf-8", "surrogatepass")
        return fs.encode_mozlz4(bytes(_mutate_bytes(rng, bytearray(text), other)))
    packed = bytearray(GOLDEN.read_bytes() if rng.random() < 0.7 else fs.encode_mozlz4(text))
    if rng.random() < 0.2:          # a wrong size in the header
        struct.pack_into("<I", packed, 8, rng.choice((0, 1, len(text) - 1, len(text) + 1, 0xFFFFFFFF, 2 ** 28)))
    return bytes(_mutate_bytes(rng, packed, b""))


def check(data: bytes) -> None:
    """Read `data` as the import does; raise AssertionError (or anything else) on a broken promise."""
    try:
        reading = fs.read_firefox_session(data)
    except fs.FirefoxSessionError:
        return
    json.dumps(reading, ensure_ascii=False)
    if not reading["windows"]:
        return
    written = fs.to_snss(reading)
    back = s.read_session(written)
    assert not back["skipped"]["unknown"] and not back["skipped"]["malformed"], "the Thoron file has bad commands"
    problems = fs.same_session(reading, back)
    assert not problems, f"the Thoron file reads differently: {problems}"


def run(minutes: float, seed: int, out: Path | None, slow: float, report_every: float = 60) -> dict:
    states = corpus()
    end = time.monotonic() + minutes * 60
    next_report = time.monotonic() + report_every
    count, crashes, hangs, slowest, slowest_seed = 0, [], [], 0.0, None
    print(f"fuzz: seed {seed}, {len(states)} sessions to start from, {minutes:g} minute(s)", flush=True)
    while time.monotonic() < end:
        input_seed = seed + count
        data = mutate(random.Random(input_seed), states)
        started = time.process_time()
        try:
            check(data)
        except Exception as exc:                                 # anything at all is a finding
            crashes.append(input_seed)
            print(f"fuzz: CRASH at seed {input_seed}: {type(exc).__name__}: {exc}"[:500], flush=True)
            if out is not None:
                out.mkdir(parents=True, exist_ok=True)
                (out / f"crash-{input_seed}.bin").write_bytes(data)
        took = time.process_time() - started
        if took > slowest:
            slowest, slowest_seed = took, input_seed
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
