#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Native ad blocking, breakage on popular sites (ROADMAP P5.17; design section 9).

Two steps:

    list   picks the sites: the first N domains of a Tranco list (https://tranco-list.eu, a research
           ranking that combines several sources) whose home page is a real page on the same site (an HTML
           answer of at least 20 KB with a title), which leaves out CDNs, DNS, ad and API hosts and
           placeholder pages, and the few domains in EXCLUDED. Writes a plain text list with its source.
    run    loads every site of a list with uBlock Origin alone, with the native engine alone, and with
           both, each configuration in its own throwaway profile, a new tab per site. Online: these are
           the real sites. Nothing about the person using the PC is sent (throwaway profiles, sandbox on,
           no sign-in, background networking off), and the report keeps only domains, counts and, for
           first-party requests that were blocked, the address without its query.

For each site and configuration it records whether the page loaded, how many requests were blocked, which
first-party requests were blocked, how many script errors were thrown and how much text the page shows.
A site is flagged when the native configuration does worse than uBlock Origin alone: it did not load,
blocked a first-party request uBlock Origin allowed, threw clearly more script errors, or shows clearly
less text. Real sites change from one load to the next, so every flagged site is loaded again in both
configurations and a flag counts only when it repeats. Flags are leads for a person to check, not proof.
    py -3 -I tools/qa/adblock_breakage.py list --tranco top.csv --list-id Y895G --date 2026-11-10 --n 100
        --out tools/qa/sites/tranco-Y895G-top100.txt [--exclude a.example,b.example]
    inner  for every site of a list, one page beyond its home page: the most article-like link of the home
           page that stays on the site (not a sign-in, help, legal or shop page), found with no blocker,
           written as a list of addresses (without their queries) that `run` and `time` take as well.
           Keep that list and the JSON results of a run on it in a private folder: a site may send the
           browser to a page for the PC's own country or language. The Markdown reports name sites by
           domain only and first-party requests by host only.
    time   load times on the real network (P5.17): uBlock Origin alone and the native engine alone, each in
           its own throwaway profile, both open at once and taking turns page by page (which goes first
           changes every page and every round), so a network that gets slower or faster meets both alike.
           Per page the time to the load event (Navigation Timing); the report gives the median of each
           and of the per-page ratio, round by round (round 1 with empty caches).

    py -3 -I tools/qa/adblock_breakage.py run --browser <out>\\thoron.exe --extension <unpacked uBO>
        --sites tools/qa/sites/tranco-Y895G-top99.txt --work C:\\thoron-build\\breakage
        --out docs/perf/<name>.json --md docs/perf/<name>.md
    py -3 -I tools/qa/adblock_breakage.py inner --browser <out>\\thoron.exe --sites <list> --work <dir>
        --out tools/qa/sites/<name>-inner.txt
    py -3 -I tools/qa/adblock_breakage.py time --browser <out>\\thoron.exe --extension <unpacked uBO>
        --sites <list> --work <dir> --rounds 2 --out docs/perf/<name>.json --md docs/perf/<name>.md
"""
import argparse
import concurrent.futures
import html
import http.client
import http.server
import json
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_proof import _settle  # noqa: E402
from tools.qa.adblock_site_switch_check import _devtools_port, _open, settings_call  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

MODES = ("ubo", "native", "native+ubo")
REFERENCE = "ubo"
LOAD_TIMEOUT_S = 30
QUIET_AFTER_LOAD_S = 3
MORE_ERRORS = 2          # script errors beyond uBlock Origin's before a site is flagged
LESS_TEXT = 0.7          # flagged below this share of uBlock Origin's text
MIN_TEXT = 200           # pages with less text than this are not compared on text
# The second-level parts under which a registrable name has three labels (a small, common subset of the
# public suffix list; enough to tell first-party from third-party requests on these sites).
TWO_PART_SUFFIXES = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.jp", "ne.jp",
                     "or.jp", "com.br", "com.cn", "com.tr", "co.in", "co.kr", "com.mx", "co.za", "com.tw",
                     "com.hk", "com.sg", "co.nz", "com.ar", "com.ua", "co.il", "com.vn", "com.my", "co.id"}
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/158.0.0.0 Safari/537.36")
MIN_PAGE_BYTES = 20000
# Domains that pass the page rule but are not sites people visit, each with its reason.
EXCLUDED = {
    "astrumu.io": "its page names no product or company; ranked by traffic from software, not visits",
}
UBO_READY_TIMEOUT_S = 180
# The readiness page for uBlock Origin: one ad script and one tracker image on real hosts.
PROBE = (b'<!doctype html><title>probe</title>'
         b'<script src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"></script>'
         b'<img src="https://www.google-analytics.com/collect?v=1" alt="">')
TEXT_LENGTH_JS = "document.body ? document.body.innerText.length : 0"
# the time from the start of the navigation to the end of the load event, in ms; 0 when there is none
LOAD_MS_JS = ("(() => { const n = performance.getEntriesByType('navigation')[0];"
              " return n && n.loadEventEnd > 0 ? Math.round(n.loadEventEnd - n.startTime) : 0; })()")
# The most article-like link of a page that stays on its site: visible, on https, not the page itself, not
# a sign-in, help, legal, shop or download page; deeper paths with words in them first. Without its query.
INNER_LINK_JS = r"""(() => {
  const host = location.hostname.replace(/^www\./, '');
  const bad = /(log-?in|sign-?in|sign-?up|register|account|privacy|terms|cookie|legal|help|support|contact|about|career|jobs|download|store|cart|checkout|subscribe|policy|search|password|settings)/i;
  const found = [];
  for (const a of document.querySelectorAll('a[href]')) {
    let u;
    try { u = new URL(a.href, location.href); } catch (e) { continue; }
    const h = u.hostname.replace(/^www\./, '');
    if (u.protocol !== 'https:' || (h !== host && !h.endsWith('.' + host))) continue;
    const p = u.pathname;
    if (p.length < 8 || p === location.pathname || bad.test(p) || /\.(pdf|zip|exe|dmg|apk|jpe?g|png|gif|svg)$/i.test(p)) continue;
    const r = a.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const parts = p.split('/').filter(Boolean).length;
    found.push([parts * 10 + (/[-_]/.test(p) ? 20 : 0) + (/\d/.test(p) ? 5 : 0) + Math.min(p.length, 60) / 6,
                u.origin + p]);
  }
  found.sort((x, y) => y[0] - x[0]);
  return found.length ? found[0][1] : '';
})()"""


def site_of(host: str) -> str:
    host = host.lower().rstrip(".")
    if re.fullmatch(r"[\d.]+|\[[0-9a-f:]+\]", host):
        return host
    labels = host.split(".")
    n = 3 if len(labels) >= 3 and ".".join(labels[-2:]) in TWO_PART_SUFFIXES else 2
    return ".".join(labels[-n:])


def read_tranco(text: str) -> list[str]:
    rows = []
    for line in text.splitlines():
        if "," in line:
            rank, domain = line.split(",", 1)
            if rank.strip().isdigit():
                rows.append((int(rank), domain.strip().lower()))
    return [d for _, d in sorted(rows)]


def page_title(body: bytes) -> str:
    m = re.search(rb"<title[^>]*>([^<]*)", body, re.I)
    return html.unescape(m.group(1).decode("utf-8", "replace")).strip() if m else ""


def probe(domain: str, timeout: float = 15) -> tuple[str, int, str, int, str] | None:
    """(final URL, status, content type, size, title) of the site's home page; None when unreachable."""
    for url in (f"https://{domain}/", f"https://www.{domain}/"):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(2_000_000)
                return r.geturl(), r.status, r.headers.get("Content-Type", ""), len(body), page_title(body)
        except urllib.error.HTTPError as e:
            return e.geturl() or url, e.code, e.headers.get("Content-Type", "") if e.headers else "", 0, ""
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
            continue
    return None


def is_page(domain: str, answer) -> bool:
    if not answer or domain in EXCLUDED:
        return False
    final, status, ctype, size, title = answer
    host = urllib.parse.urlsplit(final).hostname or ""
    return (status == 200 and "text/html" in ctype.lower() and site_of(host) == site_of(domain)
            and size >= MIN_PAGE_BYTES and bool(title))


def pick_sites(domains: list[str], probe_fn, n: int, workers: int = 16, exclude=frozenset()) -> list[str]:
    """The first n domains, in rank order, whose home page is a real page (probed in parallel).
    Domains in `exclude` are skipped (--exclude: a name the repository may not hold, for example)."""
    domains = [d for d in domains if d not in exclude]
    picked, start = [], 0
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        while len(picked) < n and start < len(domains):
            batch = domains[start:start + workers * 2]
            start += len(batch)
            for d, answer in zip(batch, pool.map(probe_fn, batch)):
                if len(picked) < n and is_page(d, answer):
                    picked.append(d)
    return picked


def site_list_text(sites: list[str], list_id: str, date: str, left_out: int = 0) -> str:
    head = [f"# The first {len(sites)} domains of the Tranco list {list_id} ({date}, https://tranco-list.eu/list/{list_id})",
            f"# whose home page is a real page on the same site (HTML, at least {MIN_PAGE_BYTES // 1000} KB, with a title),",
            "# leaving out: " + "; ".join(f"{d} ({why})" for d, why in EXCLUDED.items()) + ".",
            *([f"# {left_out} more left out on request (--exclude), not named here."] if left_out else []),
            "# Tranco: Le Pochat et al., NDSS 2019.",
            "# Picked by tools/qa/adblock_breakage.py list."]
    return "\n".join(head + sites) + "\n"


def read_site_list(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def page_url(entry: str) -> str:
    """A list holds domains (their home page) or, from `inner`, full https addresses."""
    return entry if "://" in entry else f"https://{entry}/"


def entry_host(entry: str) -> str:
    return urllib.parse.urlsplit(page_url(entry)).hostname or entry


def inner_list_text(pages: dict[str, str], source: str) -> str:
    """The list `inner` writes: for each site, the page it found (sites without one are named)."""
    head = [f"# One page beyond the home page of each site of {source}: the most article-like link of the home",
            "# page that stays on the site, found with no blocker; the address without its query.",
            "# Picked by tools/qa/adblock_breakage.py inner."]
    missing = sorted(site for site, url in pages.items() if not url)
    if missing:
        head.append(f"# No such link on: {', '.join(missing)}.")
    return "\n".join(head + [url for url in pages.values() if url]) + "\n"


def median(values: list[float]) -> float | None:
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def timing_summary(times: dict[str, dict[str, list]], rounds: int) -> list[dict]:
    """Per round: pages where both loaded, the median load time of each, the median of the per-page ratio
    native / uBlock Origin, and how many pages the native engine loaded faster."""
    out = []
    pages = sorted(set(times.get("ubo", {})) & set(times.get("native", {})))
    for r in range(rounds):
        pairs = []
        for page in pages:
            a, b = times["ubo"][page], times["native"][page]
            if r < len(a) and r < len(b) and a[r] and b[r]:
                pairs.append((a[r], b[r]))
        ratio = median([n / u for u, n in pairs])
        out.append({"round": r + 1, "pages": len(pairs), "ubo_ms": median([u for u, _ in pairs]),
                    "native_ms": median([n for _, n in pairs]), "ratio": ratio,
                    "native_faster": sum(1 for u, n in pairs if n < u)})
    return out


def timing_markdown(summary: list[dict], source: str, version: str) -> str:
    lines = [f"# Native ad blocking: load times on the real network ({version or 'unknown version'})", "",
             f"Generated by `tools/qa/adblock_breakage.py time` on {source}: uBlock Origin alone and the native",
             "engine alone, each in its own throwaway profile, both open at once and taking turns page by page",
             "(which goes first changes every page and every round). The time is from the start of the",
             "navigation to the end of the load event; round 1 starts with empty caches. A ratio below 1 means",
             "the native engine was faster.", "",
             "| Round | Pages | uBlock Origin, median ms | Native, median ms | Median ratio | Native faster on |",
             "|---|---|---|---|---|---|"]
    for row in summary:
        ratio = f"{row['ratio']:.3f}" if row["ratio"] is not None else "-"
        lines.append(f"| {row['round']} | {row['pages']} | {row['ubo_ms']} | {row['native_ms']} | {ratio} | "
                     f"{row['native_faster']} of {row['pages']} |")
    return "\n".join(lines) + "\n"


def id_free(path: str) -> str:
    """The path with ids and hashes (long digit or hex runs) replaced by *, so loads compare."""
    return re.sub(r"[0-9a-f]{12,}|[0-9]{6,}", "*", path, flags=re.I)


def summarise(site: str, events: list[dict], text_length: int) -> dict:
    urls, blocked, first_party = {}, 0, []
    exceptions, loaded = 0, False
    for e in events:
        m, p = e.get("method"), e.get("params", {})
        if m == "Network.requestWillBeSent":
            urls[p.get("requestId")] = p.get("request", {}).get("url", "")
        elif m == "Network.loadingFailed" and p.get("errorText") == "net::ERR_BLOCKED_BY_CLIENT":
            blocked += 1
            u = urllib.parse.urlsplit(urls.get(p.get("requestId"), ""))
            if u.hostname and site_of(u.hostname) == site_of(site):
                first_party.append(f"{u.hostname}{id_free(u.path)}")
        elif m == "Runtime.exceptionThrown":
            exceptions += 1
        elif m == "Page.loadEventFired":
            loaded = True
    return {"loaded": loaded, "blocked": blocked, "first_party_blocked": sorted(set(first_party)),
            "exceptions": exceptions, "text": text_length, "error": None}


def blocker_acted(events: list[dict]) -> bool:
    """True when a request was blocked or sent to an extension's stand-in."""
    for e in events:
        p = e.get("params", {})
        if e.get("method") == "Network.loadingFailed" and p.get("errorText") == "net::ERR_BLOCKED_BY_CLIENT":
            return True
        if e.get("method") == "Network.requestWillBeSent" and p.get("request", {}).get("url", "").startswith(
                "chrome-extension://"):
            return True
    return False


def compare(candidate: dict, reference: dict) -> list[str] | None:
    """Breakage flags of `candidate` against uBlock Origin alone; None when the reference itself failed."""
    if reference.get("error") or not reference.get("loaded"):
        return None
    c, r = candidate, reference
    if c.get("error") or not c.get("loaded"):
        return [f"did not load ({c.get('error') or 'no load event'})"]
    flags = []
    new_fp = sorted(set(c["first_party_blocked"]) - set(r["first_party_blocked"]))
    if new_fp:
        flags.append(f"first-party requests blocked: {', '.join(new_fp[:5])}")
    if c["exceptions"] > r["exceptions"] + MORE_ERRORS:
        flags.append(f"more script errors ({c['exceptions']} vs {r['exceptions']})")
    if r["text"] >= MIN_TEXT and c["text"] < r["text"] * LESS_TEXT:
        flags.append(f"less text ({c['text']} vs {r['text']})")
    return flags


def confirmed(first: list[str], second: list[str]) -> list[str]:
    """Flags of the first run whose kind shows again in the second run."""
    kind = lambda f: f.split(" (")[0].split(":")[0]
    again = {kind(f) for f in second}
    return [f for f in first if kind(f) in again]


class Tab:
    """One browser tab over DevTools, with a reader thread so events are kept while waiting."""

    def __init__(self, port: int):
        self.target = _open(port, "about:blank")
        self.port = port
        self.ws = WebSocket(self.target["webSocketDebuggerUrl"])
        self.ws.sock.settimeout(None)
        self.inbox: queue.Queue = queue.Queue()
        self.events: list[dict] = []
        self.replies: dict[int, dict] = {}
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                self.inbox.put(json.loads(self.ws.recv()))
        except (OSError, ConnectionError, ValueError):
            self.inbox.put(None)

    def pump(self, seconds: float) -> bool:
        """Collect messages for up to `seconds`; False when the connection closed."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            try:
                msg = self.inbox.get(timeout=left)
            except queue.Empty:
                return True
            if msg is None:
                return False
            if "id" in msg:
                self.replies[msg["id"]] = msg
            else:
                self.events.append(msg)
        return True

    def call(self, method: str, timeout: float = 15, **params) -> dict:
        self.ws.next_id += 1
        mid = self.ws.next_id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        end = time.monotonic() + timeout
        while mid not in self.replies:
            if time.monotonic() > end or not self.pump(0.2):
                raise RuntimeError(f"{method}: no answer")
        msg = self.replies.pop(mid)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    def close(self):
        try:
            self.ws.close()
        finally:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/close/{self.target['id']}", timeout=10).read()
            except OSError:
                pass


def load_site(port: int, site: str) -> dict:
    """`site`: a domain (its home page) or a full https address."""
    tab = Tab(port)
    try:
        for domain in ("Network", "Runtime", "Page"):
            tab.call(f"{domain}.enable")
        # per tab, not --user-agent: that switch also changes what extensions see, and uBlock Origin then
        # blocks nothing (checked on 158)
        tab.call("Network.setUserAgentOverride", userAgent=USER_AGENT)
        tab.call("Page.navigate", url=page_url(site))
        end = time.monotonic() + LOAD_TIMEOUT_S
        while time.monotonic() < end and not any(e["method"] == "Page.loadEventFired" for e in tab.events):
            if not tab.pump(0.5):
                break
        error = None if any(e["method"] == "Page.loadEventFired" for e in tab.events) else f"no load in {LOAD_TIMEOUT_S} s"
        tab.pump(QUIET_AFTER_LOAD_S)
        try:
            text = int(tab.call("Runtime.evaluate", expression=TEXT_LENGTH_JS, returnByValue=True)
                       .get("result", {}).get("value") or 0)
        except (RuntimeError, ValueError, TypeError):
            text = 0
        try:
            load_ms = int(tab.call("Runtime.evaluate", expression=LOAD_MS_JS, returnByValue=True)
                          .get("result", {}).get("value") or 0)
        except (RuntimeError, ValueError, TypeError):
            load_ms = 0
        out = summarise(entry_host(site), tab.events, text)
        out["error"] = error
        out["load_ms"] = load_ms
        return out
    except (OSError, RuntimeError, ConnectionError, ValueError) as e:
        return {"loaded": False, "blocked": 0, "first_party_blocked": [], "exceptions": 0, "text": 0,
                "error": str(e)[:200]}
    finally:
        tab.close()


def _launch(browser: Path, profile: Path, mode: str, extension: Path | None) -> subprocess.Popen:
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-default-apps", "--disable-background-networking",
            "--disable-component-update", "--disable-sync",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0"]
    # the browser reads only the last --disable-features: one switch for all; the native engine is on by
    # default (P5.24), so a configuration without it turns it off
    disable = []
    if "ubo" in mode:
        args.append(f"--load-extension={extension}")
        disable.append("DisableLoadExtensionCommandLineSwitch")
    if "native" in mode:
        args.append("--enable-features=ThoronNativeAdblock")
    else:
        disable.append("ThoronNativeAdblock")
    if disable:
        args.append(f"--disable-features={','.join(disable)}")
    return subprocess.Popen(args + ["about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class ProbeServer:
    """Serves the readiness page on 127.0.0.1."""

    def __init__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(PROBE)))
                self.end_headers()
                self.wfile.write(PROBE)

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]

    def __enter__(self):
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


def _wait_ubo(port: int, mode: str) -> float:
    """Wait until uBlock Origin blocks the probe page's ad requests; the seconds it took."""
    start = time.monotonic()
    if "native" in mode:
        # the native engine would block the probe first: allow ads on 127.0.0.1 (not a tested site)
        tab = Tab(port)
        try:
            tab.call("Page.enable")
            tab.call("Page.navigate", url="chrome://settings/content/ads")
            tab.pump(3)
            tab.call("Runtime.evaluate", expression=settings_call("site"))
            tab.pump(1)
        finally:
            tab.close()
    with ProbeServer() as server:
        n = 0
        while time.monotonic() - start < UBO_READY_TIMEOUT_S:
            tab = Tab(port)
            try:
                tab.call("Network.enable")
                tab.call("Page.enable")
                tab.call("Page.navigate", url=f"http://127.0.0.1:{server.port}/?{n}")
                tab.pump(3)
                if blocker_acted(tab.events):
                    return time.monotonic() - start
            finally:
                tab.close()
            n += 1
    raise bench.BenchError(f"{mode}: uBlock Origin did not start blocking within {UBO_READY_TIMEOUT_S} s")


def run_mode(browser: Path, work: Path, mode: str, extension: Path | None, sites: list[str],
             progress=lambda line: print(line, flush=True)) -> dict:
    profile = Path(tempfile.mkdtemp(prefix="breakage-", dir=work))
    proc = _launch(browser, profile, mode, extension)
    out = {}
    try:
        port = _devtools_port(profile)
        if "ubo" in mode:
            progress(f"{mode}: uBlock Origin blocking after {_wait_ubo(port, mode):.0f} s")
        _settle(proc)                      # a new profile, uBlock Origin building its filters
        load_site(port, "wikipedia.org")   # warm-up, not counted
        for i, site in enumerate(sites, 1):
            out[site] = load_site(port, site)
            progress(f"{mode} {i}/{len(sites)} {site}: {json.dumps(out[site])[:160]}")
    finally:
        bench._stop(proc, profile)
    return out


def public_flag(flag: str) -> str:
    """A flag as the public report shows it: first-party requests by host only. A site may send the browser
    to a page for the PC's own country or language, and its paths could tell where that PC is."""
    head = "first-party requests blocked: "
    if not flag.startswith(head):
        return flag
    hosts = sorted({item.strip().split("/")[0] for item in flag[len(head):].split(",") if item.strip()})
    return head + ", ".join(hosts)


def public_name(entry: str) -> str:
    """A site of the report: its domain, never the address of an inner page (see public_flag)."""
    return entry_host(entry) + (" (a page beyond the home page)" if "://" in entry else "")


def to_markdown(results: dict) -> str:
    lines = [f"# Native ad blocking: breakage on popular sites ({results.get('browser_version') or 'unknown version'})", "",
             f"Generated by `tools/qa/adblock_breakage.py` on the {results['sites']} sites of {results['list']}, each loaded",
             "in a new tab of a throwaway profile per configuration. A site is flagged when a configuration does worse",
             "than uBlock Origin alone, and only when a second load repeats it. Flags are leads to check by hand.", ""]
    for mode, flags in results["flags"].items():
        judged = results["judged"].get(mode, 0)
        lines += [f"## {mode} against uBlock Origin alone", "",
                  f"{len(flags)} of {judged} sites flagged (sites where uBlock Origin itself failed to load are not judged).", ""]
        if flags:
            lines += ["| Site | Flags | Blocked (uBlock Origin / this) |", "|---|---|---|"]
            for site, fl in sorted(flags.items()):
                ps = results["per_site"][site]
                lines.append(f"| {public_name(site)} | {'; '.join(public_flag(f) for f in fl)} | "
                             f"{ps[REFERENCE]['blocked']} / {ps[mode]['blocked']} |")
            lines.append("")
    blocked = {m: sum(ps[m]["blocked"] for ps in results["per_site"].values() if m in ps) for m in results["modes"]}
    lines += ["## Requests blocked in all", "", "| Configuration | Blocked |", "|---|---|"]
    lines += [f"| {m} | {n} |" for m, n in blocked.items()]
    return "\n".join(lines) + "\n"


def cmd_list(a) -> int:
    domains = read_tranco(Path(a.tranco).read_text(encoding="utf-8"))
    exclude = {d.strip().lower() for d in a.exclude.split(",") if d.strip()}
    sites = pick_sites(domains, probe, a.n, exclude=exclude)
    left_out = len(exclude & set(domains))
    Path(a.out).write_text(site_list_text(sites, a.list_id, a.date, left_out), encoding="utf-8", newline="\n")
    print(f"{len(sites)} sites -> {a.out}")
    return 0 if len(sites) == a.n else 1


def find_inner(port: int, site: str) -> str:
    tab = Tab(port)
    try:
        for domain in ("Runtime", "Page"):
            tab.call(f"{domain}.enable")
        tab.call("Network.setUserAgentOverride", userAgent=USER_AGENT)
        tab.call("Page.navigate", url=page_url(site))
        end = time.monotonic() + LOAD_TIMEOUT_S
        while time.monotonic() < end and not any(e["method"] == "Page.loadEventFired" for e in tab.events):
            if not tab.pump(0.5):
                break
        tab.pump(QUIET_AFTER_LOAD_S)
        return str(tab.call("Runtime.evaluate", expression=INNER_LINK_JS, returnByValue=True)
                   .get("result", {}).get("value") or "")
    except (OSError, RuntimeError, ConnectionError, ValueError):
        return ""
    finally:
        tab.close()


def cmd_inner(a) -> int:
    sites = read_site_list(Path(a.sites).read_text(encoding="utf-8"))[:a.limit or None]
    a.work.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="inner-", dir=a.work))
    proc = _launch(a.browser, profile, "none", None)
    pages = {}
    try:
        port = _devtools_port(profile)
        for i, site in enumerate(sites, 1):
            pages[site] = find_inner(port, site)
            print(f"inner {i}/{len(sites)} {site}: {pages[site] or '(none)'}", flush=True)
    finally:
        bench._stop(proc, profile)
    Path(a.out).write_text(inner_list_text(pages, a.sites.name), encoding="utf-8", newline="\n")
    found = sum(1 for url in pages.values() if url)
    print(f"{found} of {len(sites)} sites have an inner page -> {a.out}")
    return 0 if found else 1


def cmd_time(a) -> int:
    pages = read_site_list(Path(a.sites).read_text(encoding="utf-8"))[:a.limit or None]
    a.work.mkdir(parents=True, exist_ok=True)
    modes = ("ubo", "native")
    procs, ports, profiles = {}, {}, {}
    times: dict[str, dict[str, list]] = {m: {p: [] for p in pages} for m in modes}
    try:
        for m in modes:
            profiles[m] = Path(tempfile.mkdtemp(prefix=f"time-{m}-", dir=a.work))
            procs[m] = _launch(a.browser, profiles[m], m, a.extension)
            ports[m] = _devtools_port(profiles[m])
        print(f"ubo: uBlock Origin blocking after {_wait_ubo(ports['ubo'], 'ubo'):.0f} s", flush=True)
        for m in modes:
            _settle(procs[m])
            load_site(ports[m], "wikipedia.org")   # warm-up, not counted
        for r in range(a.rounds):
            for i, page in enumerate(pages):
                order = modes if (i + r) % 2 == 0 else tuple(reversed(modes))
                for m in order:
                    got = load_site(ports[m], page)
                    times[m][page].append(got["load_ms"] if got.get("loaded") and not got.get("error") else None)
                print(f"time round {r + 1} {i + 1}/{len(pages)} {entry_host(page)}: "
                      f"ubo {times['ubo'][page][-1]} native {times['native'][page][-1]}", flush=True)
    finally:
        for m in procs:
            bench._stop(procs[m], profiles[m])
    summary = timing_summary(times, a.rounds)
    version = ""
    try:
        version = subprocess.run([str(a.browser), "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    results = {"list": a.sites.name, "browser_version": version, "rounds": a.rounds,
               "pages": {p: {m: times[m][p] for m in modes} for p in pages}, "summary": summary}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8", newline="\n")
    if a.md:
        a.md.write_text(timing_markdown(summary, f"the {len(pages)} pages of {a.sites.name}", version),
                        encoding="utf-8", newline="\n")
    print("TIME:", json.dumps(summary))
    return 0


def cmd_run(a) -> int:
    sites = read_site_list(Path(a.sites).read_text(encoding="utf-8"))[:a.limit or None]
    a.work.mkdir(parents=True, exist_ok=True)
    modes = [m for m in MODES if m in a.modes.split(",")]
    if REFERENCE not in modes:
        raise SystemExit("the uBlock Origin run is the reference and must be included")
    per_mode = {m: run_mode(a.browser, a.work, m, a.extension, sites) for m in modes}
    per_site = {s: {m: per_mode[m][s] for m in modes} for s in sites}
    flags, judged = {}, {}
    for m in modes:
        if m == REFERENCE:
            continue
        first = {s: f for s in sites if (f := compare(per_site[s][m], per_site[s][REFERENCE]))}
        judged[m] = sum(1 for s in sites if compare(per_site[s][m], per_site[s][REFERENCE]) is not None)
        if first:   # load the flagged sites again in both configurations
            again_ref = run_mode(a.browser, a.work, REFERENCE, a.extension, list(first))
            again = run_mode(a.browser, a.work, m, a.extension, list(first))
            first = {s: c for s, f in first.items()
                     if (c := confirmed(f, compare(again[s], again_ref[s]) or []))}
        flags[m] = first
    version = ""
    try:
        version = subprocess.run([str(a.browser), "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    list_line = next((l for l in Path(a.sites).read_text(encoding="utf-8").splitlines() if "Tranco list" in l), "")
    m = re.search(r"Tranco list (\S+)", list_line)
    results = {"list": f"Tranco list {m.group(1)}" if m else str(a.sites), "browser_version": version,
               "sites": len(sites), "modes": modes, "per_site": per_site, "flags": flags, "judged": judged}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8", newline="\n")
    if a.md:
        a.md.write_text(to_markdown(results), encoding="utf-8", newline="\n")
    print("BREAKAGE:", {k: len(v) for k, v in flags.items()}, "flagged")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--tranco", required=True)
    p.add_argument("--list-id", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--exclude", default="", help="domains to leave out, comma-separated (not written to the list)")
    p.add_argument("--out", required=True)
    p = sub.add_parser("run")
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--extension", required=True, type=Path, help="unpacked uBlock Origin")
    p.add_argument("--sites", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path)
    p.add_argument("--modes", default=",".join(MODES))
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--md", type=Path)
    p = sub.add_parser("inner")
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--sites", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("time")
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--extension", required=True, type=Path, help="unpacked uBlock Origin")
    p.add_argument("--sites", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path)
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--md", type=Path)
    a = parser.parse_args(argv)
    return {"list": cmd_list, "run": cmd_run, "inner": cmd_inner, "time": cmd_time}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
