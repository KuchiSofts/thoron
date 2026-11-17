#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Video plays, with a picture and without dropped frames, on each graphics adapter (ROADMAP P5.7: upstream #1271,
HEVC and AV1 that play black, and #1285, frames dropped on NVIDIA graphics with hardware acceleration).

Plays every clip of --media in a real window on a throwaway profile, hardware acceleration on as by default, from
a local server on 127.0.0.1, and counts --seconds of each from its second second on (not its start, not the jump
back of the loop). For each clip it records:

    frames    how many frames were shown and how many dropped (the page's getVideoPlaybackQuality)
    picture   the mean brightness of the frame, drawn into a small canvas: a black picture is #1271
    decoder   the decoder the browser chose, from DevTools' Media domain (kVideoDecoderName; a platform decoder
              is the graphics adapter's own, in hardware)

A clip passes when it plays without an error, about as many frames as its rate are shown, its picture is not
black, and at most --drops percent of its frames are dropped. With --adapter all it runs once on every graphics
adapter chrome://gpu lists (--use-adapter-luid), so a PC with integrated and discrete graphics tests both.

The clips are made with ffmpeg from its moving test pattern (--make-media writes them: H.264, HEVC 8 and 10 bit,
AV1 and VP9, at 1080p and 2160p, 60 frames a second); nothing comes from the network.
    py -3 -I tools/qa/codec_check.py --browser <out>\\thoron.exe --work <scratch dir> --media <clip folder>
        [--make-media [--ffmpeg ffmpeg]] [--adapter all|default] [--seconds 5] [--drops 1] [--json <file>]
"""
import argparse
import functools
import http.server
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402
from tools.qa.online_bench import KEEP_RENDERING  # noqa: E402

FPS = 60
WARMUP = 2.0         # seconds of each clip before frames are counted
VENDORS = {"10de": "NVIDIA", "1002": "AMD", "8086": "Intel", "1414": "Microsoft (software)"}
# (file, ffmpeg's hardware encoder, its software one, what else ffmpeg is told)
MEDIA = [
    ("h264-{h}p60.mp4", "h264_nvenc", "libx264", ["-profile:v", "high", "-pix_fmt", "yuv420p"]),
    ("hevc-{h}p60.mp4", "hevc_nvenc", "libx265", ["-profile:v", "main", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]),
    ("hevc10-{h}p60.mp4", "hevc_nvenc", "libx265", ["-profile:v", "main10", "-pix_fmt", "p010le", "-tag:v", "hvc1"]),
    ("av1-{h}p60.mp4", "av1_nvenc", "libaom-av1", ["-pix_fmt", "yuv420p"]),
    ("vp9-{h}p60.webm", "libvpx-vp9", "libvpx-vp9", ["-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1"]),
]
SIZES = (("1920x1080", "12M"), ("3840x2160", "40M"))
PAGE = """<!doctype html><meta charset="utf-8"><title>codec check</title>
<body style="margin:0;background:#000">
<video id="v" muted loop autoplay playsinline style="width:960px" src="/media/%s"></video>
<canvas id="c" width="64" height="36" hidden></canvas>
<script>
window.result = () => {
  const v = document.getElementById('v');
  const q = v.getVideoPlaybackQuality();
  let bright = -1;
  try {
    const c = document.getElementById('c').getContext('2d', {willReadFrequently: true});
    c.drawImage(v, 0, 0, 64, 36);
    const d = c.getImageData(0, 0, 64, 36).data;
    let sum = 0;
    for (let i = 0; i < d.length; i += 4) sum += d[i] + d[i + 1] + d[i + 2];
    bright = sum / (d.length / 4) / 3;
  } catch (e) {}
  return JSON.stringify({total: q.totalVideoFrames, dropped: q.droppedVideoFrames, bright,
                         width: v.videoWidth, height: v.videoHeight,
                         error: v.error ? v.error.code + ' ' + (v.error.message || '') : ''});
};
</script>"""
# chrome://gpu's text of one adapter: "GPU0 :VENDOR= 0x10de, DEVICE=0x...., ..., LUID={0,1234}, ... *ACTIVE*",
# one after the other with nothing between them
ADAPTER = re.compile(r"GPU(\d+)\s*:\s*VENDOR\s*=\s*0x([0-9a-f]{4}),\s*DEVICE\s*=\s*0x([0-9a-f]{4}).*?"
                     r"LUID\s*=\s*\{(-?\d+),\s*(\d+)\}(.*?)(?=GPU\d+\s*:\s*VENDOR|$)", re.I | re.S)


class Recording(WebSocket):
    """A DevTools connection that keeps the events it reads while it waits for an answer."""

    def __init__(self, url: str):
        super().__init__(url)
        self.events: list[dict] = []

    def call(self, method: str, **params) -> dict:
        self.next_id += 1
        self.send(json.dumps({"id": self.next_id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.recv())
            if msg.get("id") == self.next_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)


def decoder_of(events: list[dict]) -> dict:
    """The video decoder the Media domain's events name, and whether it is the platform's (hardware) one."""
    found: dict = {}
    for e in events:
        if e.get("method") != "Media.playerPropertiesChanged":
            continue
        for prop in e.get("params", {}).get("properties", []):
            if prop.get("name") == "kVideoDecoderName":
                found["decoder"] = str(prop.get("value")).strip('"')
            elif prop.get("name") == "kIsPlatformVideoDecoder":
                found["hardware"] = str(prop.get("value")).strip('"').lower() == "true"
    return found


def clip_problems(name: str, got: dict | None, seconds: float, drops_pct: float) -> list[str]:
    if not got:
        return [f"{name}: the page could not be read"]
    if got.get("error"):
        return [f"{name}: the video failed ({got['error']})"]
    out = []
    total, dropped = got.get("total", 0), got.get("dropped", 0)
    if total < FPS * seconds * 0.8:
        out.append(f"{name}: {total} frames in {seconds:g} s, not about {FPS * seconds:g}")
    if total and dropped * 100 / total > drops_pct:
        out.append(f"{name}: {dropped} of {total} frames dropped ({dropped * 100 / total:.1f} %)")
    if got.get("bright", -1) < 8:
        out.append(f"{name}: the picture is black (brightness {got.get('bright', -1):.1f})")
    return out


def adapters(gpu_text: str) -> list[dict]:
    """The graphics adapters chrome://gpu lists: vendor, device, LUID (for --use-adapter-luid), in use or not."""
    out = []
    for m in ADAPTER.finditer(gpu_text):
        vendor = m.group(2).lower()
        out.append({"gpu": int(m.group(1)), "vendor": VENDORS.get(vendor, f"0x{vendor}"), "device": m.group(3),
                    "luid": f"{m.group(4)},{m.group(5)}", "active": "ACTIVE" in m.group(6).upper()})
    return out


def make_media(folder: Path, ffmpeg: str) -> list[Path]:
    """Writes the clips with ffmpeg's test pattern; a hardware encoder when ffmpeg has it, else the software one."""
    folder.mkdir(parents=True, exist_ok=True)
    listed = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    made = []
    for size, rate in SIZES:
        height = size.split("x")[1]
        for pattern, hardware, software, extra in MEDIA:
            target = folder / pattern.format(h=height)
            encoder = hardware if re.search(rf"\s{re.escape(hardware)}\s", listed) else software
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            f"testsrc2=size={size}:rate={FPS}:duration=8", "-c:v", encoder, "-b:v", rate, *extra,
                            *(["-movflags", "+faststart"] if target.suffix == ".mp4" else []), str(target)],
                           check=True)
            made.append(target)
    return made


class Site:
    def __init__(self, media: Path):
        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path.startswith("/play/"):
                    body = (PAGE % self.path[len("/play/"):]).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path.startswith("/media/"):
                    self.path = self.path[len("/media"):]
                    return super().do_GET()
                self.send_error(404)

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                                      functools.partial(Handler, directory=str(media)))
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]

    def __enter__(self):
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


def _launch(browser: Path, profile: Path, luid: str | None) -> subprocess.Popen:
    return subprocess.Popen([str(browser), f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                             "--disable-extensions", "--autoplay-policy=no-user-gesture-required", "--mute-audio",
                             *KEEP_RENDERING, *([f"--use-adapter-luid={luid}"] if luid else []),
                             "--window-position=40,40", "--window-size=1100,700", "--remote-debugging-port=0",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _value(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    return reply.get("result", {}).get("value")


def gpu_page(port: int) -> str:
    ws = WebSocket(_open(port, "chrome://gpu")["webSocketDebuggerUrl"])
    try:
        text = ""
        for _ in range(20):
            time.sleep(1)
            # the page's text is inside its <info-view>'s shadow tree
            text = _value(ws, "(document.querySelector('info-view') || {}).shadowRoot ? "
                              "document.querySelector('info-view').shadowRoot.textContent : ''") or ""
            if "VENDOR" in text:
                break
        return text
    finally:
        ws.close()


def run_adapter(browser: Path, work: Path, site: Site, clips: list[str], seconds: float, drops: float,
                luid: str | None) -> dict:
    profile = Path(tempfile.mkdtemp(prefix="codec-", dir=work))
    proc = _launch(browser, profile, luid)
    port = None
    result: dict = {"luid": luid, "clips": {}, "problems": []}
    try:
        port = _devtools_port(profile)
        listed = adapters(gpu_page(port))
        result["adapters"] = listed
        result["active"] = next((a for a in listed if a["active"]), None)
        for clip in clips:
            ws = Recording(_open(port, "about:blank")["webSocketDebuggerUrl"])
            try:
                ws.call("Media.enable")
                ws.call("Page.navigate", url=f"http://127.0.0.1:{site.port}/play/{clip}")
                # counted from WARMUP s on, so that neither the start nor the jump back of the loop (the clips
                # are 8 s) is in it: what is measured is steady playback
                time.sleep(WARMUP)
                raw = _value(ws, "window.result ? window.result() : ''")
                first = json.loads(raw) if raw else None
                time.sleep(seconds)
                raw = _value(ws, "window.result ? window.result() : ''")
                got = json.loads(raw) if raw else None
                if got is not None and first is not None:
                    got["total"] -= first.get("total", 0)
                    got["dropped"] -= first.get("dropped", 0)
                if got is not None:
                    got.update(decoder_of(ws.events))
            except (OSError, RuntimeError, ValueError) as exc:
                got = {"error": f"the page failed ({exc})"}
            finally:
                ws.close()
            found = clip_problems(clip, got, seconds, drops)
            result["clips"][clip] = got
            result["problems"] += found
            print(f"  {'PASS' if not found else 'FAIL'}  {clip}: {(got or {}).get('decoder', '?')}"
                  f"{' (hardware)' if (got or {}).get('hardware') else ''}, "
                  f"{(got or {}).get('dropped', '?')} of {(got or {}).get('total', '?')} frames dropped, "
                  f"brightness {(got or {}).get('bright', -1):.0f}")
            for f in found:
                print(f"        {f}")
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        result["problems"].append(f"the run failed: {exc}")
    finally:
        if port is not None:
            _close_browser(port, proc)
        else:
            bench._stop(proc, profile)
        shutil.rmtree(profile, ignore_errors=True)
    return result


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path)
    p.add_argument("--media", required=True, type=Path, help="the folder of the clips")
    p.add_argument("--make-media", action="store_true", help="write the clips with ffmpeg first")
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument("--adapter", choices=("all", "default"), default="all")
    p.add_argument("--seconds", type=float, default=5, help="seconds counted, after the first 2")
    p.add_argument("--drops", type=float, default=1.0, help="percent of the frames that may be dropped")
    p.add_argument("--json", type=Path)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    a.work.mkdir(parents=True, exist_ok=True)
    if a.make_media:
        make_media(a.media, a.ffmpeg)
    clips = sorted(f.name for f in a.media.iterdir() if f.suffix in (".mp4", ".webm"))
    if not clips:
        print("CODEC CHECK: FAILED (no clips in --media; --make-media writes them)")
        return 1
    runs = []
    with Site(a.media) as site:
        print("adapter: the browser's own choice")
        first = run_adapter(a.browser, a.work, site, clips, a.seconds, a.drops, None)
        runs.append(first)
        if a.adapter == "all":
            for adapter in first.get("adapters", []):
                if first.get("active") and adapter["luid"] == first["active"]["luid"]:
                    continue
                if adapter["vendor"].startswith("Microsoft"):
                    continue
                print(f"adapter: {adapter['vendor']} (LUID {adapter['luid']})")
                runs.append(run_adapter(a.browser, a.work, site, clips, a.seconds, a.drops, adapter["luid"]))
    if a.json:
        a.json.write_text(json.dumps(runs, indent=1), encoding="utf-8")
    problems = [f"{(r.get('active') or {}).get('vendor', r['luid'])}: {p_}" for r in runs for p_ in r["problems"]]
    print(f"CODEC CHECK: {'PASSED' if not problems else f'FAILED ({len(problems)} problem(s))'}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
