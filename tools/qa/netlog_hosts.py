#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Which outside hosts a fresh profile contacts on its own, what asks for each and when (ROADMAP S.10, S.15).

Starts the browser headless on a throwaway profile with a local page (127.0.0.1) and Chromium's network
log turned on, waits, stops it, and reads the log. Nothing is typed or clicked, so every host listed is
contacted by the browser itself. This is an online measurement: the browser really reaches those hosts.
The log may be cut off when the browser is stopped; the parser does not need valid JSON. On Windows the
component updater hands its downloads to the system's background transfer service, which the browser's
log does not see; the tool has the browser make them itself, so that they are counted. It reports:

    hosts     every host other than the local machine that appears in the log, with how often
    requests  every request the browser made: the host, when (seconds after the browser was started),
              what asked (Chromium gives every caller of the network a "traffic annotation" and logs its
              number; the name is shown where it is known, and --annotations reads the whole table from
              a Chromium checkout), the path without its query, and the answer
    lookups   names the browser looked up without asking them anything
    ahead     connections the browser opened before any request for them (preconnects)
    arrived   the components the profile held at the end (what the downloads were)

    py -3 -I tools/qa/netlog_hosts.py --browser <out>\\thoron.exe --work C:\\thoron-build\\netlog --seconds 240
        --runs 3 --label "Thoron 158" --md <scratch>\\hosts.md --json <scratch>\\hosts.json
    py -3 -I tools/qa/netlog_hosts.py ... --switch=--disable-features=OptimizationHints
        --absent optimizationguide-pa.googleapis.com
    py -3 -I tools/qa/netlog_hosts.py ... --page chrome://newtab/
Exit status 1 when a host named with --absent is anywhere in a log (the test of ROADMAP S.15).

What it prints is made to be published: queries are dropped, extension and component ids are replaced by
<id> (an extension another program registered on the PC would name that program), and an address of the
local network is not shown. Read a report once before it is published all the same. A raw log
(--keep-log) holds the PC's addresses and paths: never commit one.
"""
import argparse
import ipaddress
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa.bench import PingServer, _launch, _stop  # noqa: E402

_URL = re.compile(r'"(?:url|original_url|location)"\s*:\s*"(?:https?|wss?)://([^/:"?#]+)')
_HOST = re.compile(r'"host"\s*:\s*"([^"]+)"')
_PAIR = re.compile(r'"host_port_pair"\s*:\s*"([^":]+)')
_LOCAL = {"127.0.0.1", "localhost", "::1", "[::1]"}
LOCAL_NETWORK = "(local network address)"
SINGLE_LABEL = "(single-label name)"

# The log's events are one a line and end with their source and type; only some are worth parsing.
_OTHER_EVENTS = ("HOST_RESOLVER_MANAGER_REQUEST", "HTTP_STREAM_JOB_CONTROLLER")
_TAIL = re.compile(r'"source":\{"id":\d+,"start_time":"\d+","type":(\d+)\},"time":"\d+","type":(\d+)\}$')
_REQUEST_URL = re.compile(r"^(?:https?|wss?)://([^/?#]*)([^?#]*)")
_ID = re.compile(r"(?i)(?<![a-z0-9])[a-p]{32}(?:_[0-9_]+)?(?![a-z0-9])")
_ITEM = re.compile(r'<item id="([^"]+)"[^>]*?(?:file_path="([^"]*)")?\s*/?>')

# The component updater's downloads stay in the browser, where the log sees them.
OWN_DOWNLOADS = "--component-updater=disable-background-downloads"

# Callers a fresh Thoron profile has or may have, by their traffic annotation (Chromium's names, then
# Thoron's own two); the log holds each one's number, which annotation_hash() works out from the name.
ANNOTATION_NAMES = (
    "aim_eligibility_fetch", "blink_resource_loader", "certificate_verifier_url_loader", "chrome_variations_service",
    "cws_fetch_item_snippet", "dns_over_https", "domain_reliability_report_upload", "extension_crx_fetcher",
    "extension_manifest_fetcher", "gaia_auth_list_accounts", "gcm_checkin", "gcm_registration",
    "hintsfetcher_gethintsrequest", "intranet_redirect_detector", "logo_service", "metrics_report_uma",
    "network_time_component", "ntp_custom_background", "omnibox_suggest", "omnibox_zerosuggest",
    "one_google_bar_service", "optimization_guide_model", "optimization_guide_model_download",
    "safe_browsing_v4_get_hash", "safe_browsing_v4_update", "translate_url_fetcher", "update_client",
    "thoron_adblock_lists", "thoron_mail_feed")


def annotation_hash(name: str) -> int:
    """The number Chromium's network log gives for a traffic annotation's name."""
    value = 0
    for byte in name.encode("utf-8"):
        value = (value * 31 + byte) % 138003713
    return value


ANNOTATIONS = {annotation_hash(name): name for name in ANNOTATION_NAMES}


def load_annotations(xml_text: str) -> dict[int, str]:
    """Every annotation of a Chromium checkout's tools/traffic_annotation/summary/annotations.xml, with the
    file that defines it."""
    return {annotation_hash(name): f"{name} ({path})" if path else name for name, path in _ITEM.findall(xml_text)}


def _clean(host: str) -> str:
    """ "https://host:443" and "host:443" are "host"; empty for the local machine."""
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", host.lower()).split("/")[0]
    if host.startswith("["):                                          # "[::1]:443"
        host = host[1:].split("]")[0]
    elif host.count(":") == 1:
        host = host.split(":")[0]
    host = host.strip(".")
    if not host or host in _LOCAL:
        return ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if address.is_loopback or address.is_unspecified:
        return ""
    return LOCAL_NETWORK if address.is_private or address.is_link_local else host


def hosts(log_text: str) -> dict[str, int]:
    found = Counter()
    for rx in (_URL, _HOST, _PAIR):
        for h in rx.findall(log_text):
            h = _clean(h)
            if "." in h or h == LOCAL_NETWORK:
                found[h] += 1
    return dict(found)


def path_shown(path: str) -> str:
    """A request's path as it can be published: ids gone, long opaque parts shortened."""
    parts = [_ID.sub("<id>", part) for part in path.split("/")]
    return "/".join(part if len(part) <= 48 else "<...>" for part in parts) or "/"


def _url_parts(url) -> tuple[str, str]:
    """The host (empty for the local machine and for what is not a web address) and the path of an address."""
    found = _REQUEST_URL.match(str(url or ""))
    return (_clean(found.group(1).rsplit("@", 1)[-1]), found.group(2)) if found else ("", "")


def events(log_text: str):
    """The log's constants, then its events one by one. Events that are neither a request's, a name
    look-up nor the start of a connection are skipped unparsed (most of a log is QUIC packets); a line
    cut off mid-way is skipped."""
    start = log_text.find('"events"')
    constants = {}
    try:
        constants = json.loads(log_text[:max(start, 0)].rstrip().rstrip(",") + "}").get("constants", {})
    except ValueError:
        pass
    yield constants
    wanted_source = constants.get("logSourceType", {}).get("URL_REQUEST")
    wanted_types = {constants.get("logEventTypes", {}).get(name) for name in _OTHER_EVENTS}
    first = True
    for line in log_text[max(start, 0):].splitlines():
        line = line.strip().rstrip(",")
        if line.endswith("]"):
            line = line[:-1]
        if not line.startswith("{"):
            continue
        tail = _TAIL.search(line) if wanted_source is not None and not first else None
        if tail and int(tail.group(1)) != wanted_source and int(tail.group(2)) not in wanted_types:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and isinstance(event.get("source"), dict) and "type" in event:
            first = False
            yield event


def digest(log_text: str, names: dict[int, str] | None = None, launched: float | None = None) -> dict:
    """The requests of a log, the names it only looked up and the connections it opened ahead of a
    request. `launched` is when the browser was started (seconds since 1970); without it, times count
    from the log's first event."""
    names = {**ANNOTATIONS, **(names or {})}
    stream = events(log_text)
    constants = next(stream)
    type_name = {v: k for k, v in constants.get("logEventTypes", {}).items()}
    source_name = {v: k for k, v in constants.get("logSourceType", {}).items()}
    error_name = {v: k for k, v in constants.get("netError", {}).items()}
    begin = constants.get("logEventPhase", {}).get("PHASE_BEGIN", 1)
    zero, state, requests, looked, ahead = None, {}, [], Counter(), []
    for event in stream:
        try:
            ticks = int(event.get("time", 0))
        except (TypeError, ValueError):
            continue
        if zero is None:
            zero = ticks
            try:
                if launched is not None:
                    zero = launched * 1000 - float(constants["timeTickOffset"])
            except (KeyError, TypeError, ValueError):
                pass
        kind = type_name.get(event["type"], "")
        params = event.get("params") if isinstance(event.get("params"), dict) else {}
        if kind == "HOST_RESOLVER_MANAGER_REQUEST":
            if event.get("phase") == begin and isinstance(params.get("host"), str):
                host = _clean(params["host"])
                if host:
                    looked[host if "." in host or host in ("wpad", LOCAL_NETWORK) else SINGLE_LABEL] += 1
            continue
        if kind == "HTTP_STREAM_JOB_CONTROLLER":
            if event.get("phase") == begin and params.get("is_preconnect") is True:
                host = _url_parts(params.get("url"))[0]
                if host:
                    ahead.append({"host": host, "at": round((ticks - zero) / 1000, 1)})
            continue
        if source_name.get(event["source"].get("type")) != "URL_REQUEST":
            continue
        mine = state.setdefault(event["source"].get("id"), {"annotation": None, "request": None})
        if kind == "REQUEST_ALIVE" and event.get("phase") == begin:
            mine["annotation"] = params.get("traffic_annotation")
        elif kind == "URL_REQUEST_START_JOB" and event.get("phase") == begin:
            mine["request"] = None                                     # a redirect starts the next job
            host, path = _url_parts(params.get("url"))
            if host:
                number = mine["annotation"]
                mine["request"] = {"host": host, "at": round((ticks - zero) / 1000, 1),
                                   "asked_by": names.get(number, f"annotation {number}"),
                                   "method": str(params.get("method", "")), "path": path_shown(path),
                                   "initiator": _ID.sub("<id>", str(params.get("initiator", ""))), "sent": False,
                                   "answer": ""}
                requests.append(mine["request"])
        elif mine["request"] is not None:
            request = mine["request"]
            if kind.endswith("SEND_REQUEST_HEADERS"):
                request["sent"] = True
            elif kind == "HTTP_TRANSACTION_READ_RESPONSE_HEADERS" and params.get("headers"):
                status = str(params["headers"][0]).split(" ")
                request["answer"] = status[1] if len(status) > 1 else status[0]
            elif params.get("net_error") and not request["answer"]:
                request["answer"] = error_name.get(params["net_error"], str(params["net_error"]))
    asked = {r["host"] for r in requests}
    return {"requests": requests, "lookups": {h: n for h, n in looked.items() if h not in asked},
            "preconnects": ahead}


def arrived(user_data: Path) -> dict[str, str]:
    """The components a profile holds: each folder of the user data directory with a versioned manifest."""
    found = {}
    for manifest in sorted(user_data.glob("*/*/manifest.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("version"):
            found[manifest.parent.parent.name] = str(data["version"])
    return found


def seed_prefs(profile: Path, prefs: dict) -> None:
    """Preferences a profile starts with ("a.b.c" names a value inside dictionaries), as a changed default
    would give them: written before the browser first runs."""
    tree = {}
    for name, value in prefs.items():
        node = tree
        *parents, last = name.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[last] = value
    (profile / "Default").mkdir(parents=True, exist_ok=True)
    (profile / "Default" / "Preferences").write_text(json.dumps(tree), encoding="utf-8")


def start_args(profile: Path, visible: bool) -> list[str]:
    """How the browser is started: headless and past the first run (the default), or (visible) as a person's
    first start, in a real window with the first-run page."""
    if visible:
        return [f"--user-data-dir={profile}", "--window-position=40,40", "--window-size=1100,750"]
    return ["--headless=new", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check"]


def _one(browser: Path, profile: Path, log: Path, seconds: float, extra: list[str], visible: bool,
         names: dict[int, str] | None, keep_log: bool) -> dict:
    held = {}
    launched = time.time()
    args = [f"--log-net-log={log}", "--net-log-capture-mode=Default", OWN_DOWNLOADS, *extra]
    if visible:
        proc = subprocess.Popen([str(browser), *start_args(profile, True), *args], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=os.name != "nt")
    else:
        proc = _launch(browser, profile, args)
    try:
        time.sleep(seconds)
        held = arrived(profile)
    finally:
        _stop(proc, profile)
        time.sleep(2)
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    if keep_log:
        print(f"netlog_hosts: raw log kept (never commit it): {log}", file=sys.stderr)
    else:
        log.unlink(missing_ok=True)
    if not text:
        raise RuntimeError("the browser wrote no network log")
    return {"hosts": hosts(text), **digest(text, names, launched), "arrived": held}


def capture(browser: Path, work: Path, seconds: float, switches: tuple[str, ...] = (), prefs: dict | None = None,
            names: dict[int, str] | None = None, keep_log: bool = False, page: str | None = None,
            visible: bool = False, again: bool = False) -> dict:
    """One fresh profile; with `again` also a later start of the same profile, under "again"."""
    work.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="netlog-", dir=work))
    if prefs:
        seed_prefs(profile, prefs)
    try:
        with PingServer() as server:
            extra = [*switches, page or server.url("page")]
            result = _one(browser, profile, profile.parent / f"{profile.name}.json", seconds, extra, visible, names,
                          keep_log)
            if again:
                result["again"] = _one(browser, profile, profile.parent / f"{profile.name}-again.json", seconds,
                                       extra, visible, names, keep_log)
    finally:
        for _ in range(10):                    # a file still held a moment after the stop: try again
            shutil.rmtree(profile, ignore_errors=True)
            if not profile.exists():
                break
            time.sleep(1)
    return result


def by_host(runs: list[dict]) -> dict[str, dict]:
    """Per host over all runs: in how many runs, requests per run, when first, who asked, for what, answers."""
    out = {}
    for index, run in enumerate(runs):
        for r in run["requests"]:
            h = out.setdefault(r["host"], {"runs": set(), "requests": Counter(), "first": {}, "asked_by": Counter(),
                                           "paths": Counter(), "answers": Counter()})
            h["runs"].add(index)
            h["requests"][index] += 1
            h["first"][index] = min(h["first"].get(index, r["at"]), r["at"])
            h["asked_by"][r["asked_by"]] += 1
            h["paths"][f"{r['method']} {r['path']}"] += 1
            h["answers"][r["answer"] or ("no answer" if r["sent"] else "not sent")] += 1
    return {host: {"runs": len(h["runs"]), "requests": [h["requests"][i] for i in sorted(h["runs"])],
                   "first": [h["first"][i] for i in sorted(h["runs"])], "asked_by": dict(h["asked_by"]),
                   "paths": dict(h["paths"]), "answers": dict(h["answers"])} for host, h in out.items()}


def _span(values: list) -> str:
    low, high = min(values), max(values)
    return f"{low:g}" if low == high else f"{low:g} to {high:g}"


def _top(counted: dict, most: int = 3) -> str:
    ranked = sorted(counted.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = [f"`{name}` ({n})" for name, n in ranked[:most]]
    return ", ".join(shown) + (f", {len(ranked) - most} more" if len(ranked) > most else "")


def to_markdown(found: dict[str, int], label: str, seconds: float, page: str = "one local page") -> str:
    out = [f"# Hosts contacted by a fresh {label} profile", "",
           f"Measured with `tools/qa/netlog_hosts.py`: headless, throwaway profile, {page}, {seconds:g} s,"
           " no user action.", "", "| Host | Log entries |", "|---|---|"]
    out += [f"| {h} | {n} |" for h, n in sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))]
    if not found:
        out.append("| (none) | 0 |")
    return "\n".join(out) + "\n"


def detail_markdown(runs: list[dict]) -> str:
    """The requests of all runs by host, the names only looked up, the connections opened ahead, and
    what arrived in the profile."""
    count = len(runs)
    out = ["## Requests", "", "Times are seconds after the browser was started; counts are requests in a run.", "",
           f"| Host | In runs (of {count}) | Requests | First at | Asked by | Asked for | Answers |",
           "|---|---|---|---|---|---|---|"]
    table = by_host(runs)
    for host, h in sorted(table.items(), key=lambda kv: (statistics.median(kv[1]["first"]), kv[0])):
        out.append(f"| {host} | {h['runs']} | {_span(h['requests'])} | {_span(h['first'])} | {_top(h['asked_by'])} | "
                   f"{_top(h['paths'])} | {_top(h['answers'])} |")
    if not table:
        out.append("| (none) | 0 | 0 | | | | |")
    looked = Counter()
    for run in runs:
        looked.update(run.get("lookups", {}).keys())
    if looked:
        out += ["", "Looked up without a request: " + ", ".join(f"`{h}` (in {n} of {count})"
                                                                for h, n in sorted(looked.items()))]
    ahead = {}
    for index, run in enumerate(runs):
        for opened in run.get("preconnects", []):
            ahead.setdefault(opened["host"], {}).setdefault(index, []).append(opened["at"])
    if ahead:
        out += ["", "Connected to before any request (preconnect): " + ", ".join(
            f"`{host}` (in {len(per)} of {count}, {_span([len(t) for t in per.values()])} a run, first at "
            f"{_span([min(t) for t in per.values()])})" for host, per in sorted(ahead.items()))]
    held = Counter()
    for run in runs:
        held.update(run.get("arrived", {}).keys())
    if held:
        out += ["", "Components in the profile at the end: " + ", ".join(f"{name} (in {n} of {count})"
                                                                         for name, n in sorted(held.items()))]
    return "\n".join(out) + "\n"


def contacted(runs: list[dict], names: list[str]) -> list[str]:
    """Which of the named hosts a run contacted or mentioned in its log."""
    seen = set()
    for run in runs:
        seen.update(run["hosts"])
        seen.update(r["host"] for r in run["requests"])
    return sorted(seen.intersection(n.lower() for n in names))


def _pref(text: str) -> tuple[str, object]:
    name, sep, value = text.partition("=")
    if not sep or not name:
        raise argparse.ArgumentTypeError(f"{text!r} is not NAME=VALUE")
    try:
        return name, json.loads(value)
    except ValueError:
        return name, value


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--seconds", type=float, default=120)
    p.add_argument("--runs", type=int, default=1, help="how many fresh profiles to measure, one after another")
    p.add_argument("--label", default="browser")
    p.add_argument("--switch", action="append", default=[], metavar="SWITCH",
                   help="one more browser switch, written --switch=--name=value; may be repeated")
    p.add_argument("--pref", action="append", default=[], type=_pref, metavar="NAME=VALUE",
                   help="a preference the profile starts with (VALUE as JSON); may be repeated")
    p.add_argument("--annotations", type=Path, help="a Chromium checkout's annotations.xml, to name every caller")
    p.add_argument("--page", help="the page to open instead of the local one, for example chrome://newtab/")
    p.add_argument("--absent", action="append", default=[], metavar="HOST",
                   help="a host that must not be contacted; may be repeated")
    p.add_argument("--keep-log", action="store_true", help="keep the raw logs in --work (never commit them)")
    p.add_argument("--visible", action="store_true",
                   help="a person's first start: a real window with the first-run page (not headless)")
    p.add_argument("--again", action="store_true",
                   help="also a later start of the same profile, measured on its own")
    p.add_argument("--md", type=Path)
    p.add_argument("--json", type=Path, help="what was measured, run by run")
    a = p.parse_args(argv)
    try:
        names = None
        if a.annotations:
            names = load_annotations(a.annotations.read_text(encoding="utf-8", errors="replace"))
        runs = [capture(a.browser, a.work, a.seconds, tuple(a.switch), dict(a.pref), names, a.keep_log, a.page,
                        a.visible, a.again)
                for _ in range(max(a.runs, 1))]
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"netlog_hosts: {exc}", file=sys.stderr)
        return 1
    found = Counter()
    for run in runs:
        found.update(run["hosts"])
    opened = f"the page `{a.page}`" if a.page else "one local page"
    if a.visible:
        opened += ", in a real window as a person's first start (the first-run page)"
    md = to_markdown(dict(found), a.label, a.seconds, opened) + "\n" + detail_markdown(runs)
    later = [run["again"] for run in runs if "again" in run]
    if later:
        found_later = Counter()
        for run in later:
            found_later.update(run["hosts"])
        md += ("\n## A later start of the same profile\n\n"
               + to_markdown(dict(found_later), a.label + " (later start)", a.seconds, opened) + "\n"
               + detail_markdown(later))
    if a.md:
        a.md.parent.mkdir(parents=True, exist_ok=True)
        a.md.write_text(md, encoding="utf-8", newline="\n")
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps({"label": a.label, "seconds": a.seconds, "switches": a.switch,
                                      "prefs": dict(a.pref), "page": a.page, "runs": runs}, indent=1) + "\n",
                            encoding="utf-8")
    print(md)
    still = contacted(runs, a.absent)
    if still:
        print(f"netlog_hosts: contacted although --absent: {', '.join(still)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
