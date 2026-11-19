# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the social preview and release banner (ROADMAP B.4) without a browser."""
import re
import unittest
from pathlib import Path

from tools.branding import social
from tools.branding.ico import png_size
from tools.release import release as rel

REPO = Path(__file__).resolve().parents[3]
LOGO = (REPO / "branding/thoron/thoron-logo.svg").read_text(encoding="utf-8")


class SocialTests(unittest.TestCase):
    def test_sizes_logo_name_and_the_readme_s_line(self):
        for make, (width, height) in ((social.social_svg, social.SOCIAL), (social.banner_svg, social.BANNER)):
            svg = make(LOGO)
            self.assertIn(f'width="{width}" height="{height}"', svg)
            self.assertIn('viewBox="0 0 512 512"', svg)          # the logo itself, inside
            self.assertIn(">Thoron</text>", svg)
            readme = (REPO / "README.md").read_text(encoding="utf-8")
            self.assertIn(" ".join(social.TAGLINE), readme)
            self.assertNotIn(chr(0x2014), svg)

    def test_the_social_preview_keeps_github_s_margin(self):
        svg = social.social_svg(LOGO)
        for x in re.findall(r'<(?:svg|text) x="(\d+)"', svg):
            self.assertGreaterEqual(int(x), social.MARGIN)

    def test_refuses_a_logo_without_a_512_viewbox(self):
        with self.assertRaises(ValueError):
            social.social_svg('<svg viewBox="0 0 10 10"></svg>')

    def test_the_committed_images_have_their_sizes(self):
        folder = REPO / "branding/thoron/social"
        self.assertEqual(png_size((folder / "thoron-social-preview.png").read_bytes()), social.SOCIAL)
        self.assertEqual(png_size((folder / "thoron-release-banner.png").read_bytes()), social.BANNER)
        self.assertTrue((REPO / rel.RELEASE_BANNER).is_file())
        self.assertEqual(rel.release_banner_url("example/thoron", "v0.1.1"),
                         "https://raw.githubusercontent.com/example/thoron/v0.1.1/" + rel.RELEASE_BANNER)


if __name__ == "__main__":
    unittest.main()
