#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron's GitHub social preview and release banner (ROADMAP B.4), built from the logo SVG so they never drift
from it, and rendered with the same headless browser as export_icons.py and wordmark.py.
    py -3 -I tools/branding/social.py --svg branding/thoron/thoron-logo.svg --out branding/thoron/social
writes thoron-social-preview.png (1280 x 640, what GitHub shows when the repository is linked; its own text
keeps 80 px from every edge, as GitHub asks) and thoron-release-banner.png (1280 x 320, the top of the release
notes), each with the SVG it was made from.
"""
import argparse
import re
import sys
from pathlib import Path

if __package__ in (None, ""):  # allow running as a script with `py -3 -I`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.branding.export_icons import find_browser  # noqa: E402
from tools.branding.wordmark import render  # noqa: E402

SOCIAL = (1280, 640)
BANNER = (1280, 320)
MARGIN = 80
NAME = "Thoron"
# the README's own line, in two
TAGLINE = ("A fast, secure and private browser", "for Windows, based on Thorium and Chromium")
FONT = "Segoe UI, Roboto, Arial, sans-serif"
_ROOT = re.compile(r"<svg\b[^>]*>(.*)</svg>\s*$", re.S)


def _inner(logo_svg: str) -> str:
    if 'viewBox="0 0 512 512"' not in logo_svg:
        raise ValueError("the logo SVG must have viewBox 0 0 512 512")
    m = _ROOT.search(logo_svg)
    if not m:
        raise ValueError("not an SVG document")
    return m.group(1)


def _background(width: int, height: int) -> str:
    # deep violet, from the logo's darkest blade to near black, with the logo's light violet as a soft glow
    return (f'  <defs>\n'
            f'    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">\n'
            f'      <stop offset="0" stop-color="#2B1258"/>\n'
            f'      <stop offset="1" stop-color="#120726"/>\n'
            f'    </linearGradient>\n'
            f'    <radialGradient id="glow" cx="0.26" cy="0.5" r="0.45">\n'
            f'      <stop offset="0" stop-color="#894EEF" stop-opacity="0.35"/>\n'
            f'      <stop offset="1" stop-color="#894EEF" stop-opacity="0"/>\n'
            f'    </radialGradient>\n'
            f'  </defs>\n'
            f'  <rect width="{width}" height="{height}" fill="url(#bg)"/>\n'
            f'  <rect width="{width}" height="{height}" fill="url(#glow)"/>\n')


def social_svg(logo_svg: str) -> str:
    width, height = SOCIAL
    logo, inner = 320, _inner(logo_svg)
    x0 = MARGIN + logo + 72
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">\n' + _background(width, height) +
            f'  <svg x="{MARGIN}" y="{(height - logo) // 2}" width="{logo}" height="{logo}" viewBox="0 0 512 512">'
            f'{inner}</svg>\n'
            f'  <text x="{x0}" y="300" font-family="{FONT}" font-size="132" font-weight="600" fill="#FFFFFF">'
            f'{NAME}</text>\n'
            f'  <text x="{x0 + 4}" y="372" font-family="{FONT}" font-size="34" fill="#D9CCFF">{TAGLINE[0]}</text>\n'
            f'  <text x="{x0 + 4}" y="418" font-family="{FONT}" font-size="34" fill="#D9CCFF">{TAGLINE[1]}</text>\n'
            f'</svg>\n')


def banner_svg(logo_svg: str) -> str:
    width, height = BANNER
    logo, inner = 192, _inner(logo_svg)
    x0 = MARGIN + logo + 56
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">\n' + _background(width, height) +
            f'  <svg x="{MARGIN}" y="{(height - logo) // 2}" width="{logo}" height="{logo}" viewBox="0 0 512 512">'
            f'{inner}</svg>\n'
            f'  <text x="{x0}" y="150" font-family="{FONT}" font-size="96" font-weight="600" fill="#FFFFFF">'
            f'{NAME}</text>\n'
            f'  <text x="{x0 + 3}" y="202" font-family="{FONT}" font-size="28" fill="#D9CCFF">{TAGLINE[0]}</text>\n'
            f'  <text x="{x0 + 3}" y="240" font-family="{FONT}" font-size="28" fill="#D9CCFF">{TAGLINE[1]}</text>\n'
            f'</svg>\n')


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--svg", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--browser", type=Path, help="a headless-capable Chromium-family browser")
    a = parser.parse_args(argv)
    browser = a.browser or find_browser()
    logo = a.svg.read_text(encoding="utf-8")
    a.out.mkdir(parents=True, exist_ok=True)
    for name, make, size in (("thoron-social-preview", social_svg, SOCIAL),
                             ("thoron-release-banner", banner_svg, BANNER)):
        text = make(logo)
        (a.out / f"{name}.svg").write_text(text, encoding="utf-8", newline="\n")
        render(text, a.out / f"{name}.png", browser, *size)
        print("wrote", a.out / f"{name}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
