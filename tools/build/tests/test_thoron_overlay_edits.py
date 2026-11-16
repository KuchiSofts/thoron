# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Edits to upstream overlay files, which the patch series cannot change (ROADMAP S.4, B.3)."""
import re
import unittest

from tools.build import thoron_identity as ti

FLAGS = "chrome/browser/thorium_flag_entries.h"
OFFSTORE = ('     "Allows downloaded CRX files to be installed when developer mode is enabled on the extensions page. '
            'CRX signatures, permission prompts, and extension policies still apply. Android also requires experimental '
            'extension support. Only enable this for sources you trust.",\n')
# Excerpt of upstream's overlay file (stored with Windows line endings).
FLAG_ENTRIES = (
    '    {"disable-web-security",\n     "Disable Web Security",\n'
    '     "Don\'t enforce the same-origin policy; meant for website testing only. See `https://web.dev/same-origin-policy/`",\n'
    '    {"allow-file-access-from-files",\n'
    '     "By default, file:// URIs cannot read other file:// URIs. This is an override for web developers who need this behavior for testing.",\n'
    '     "Disable encryption of cookies, passwords, and settings which normally uses a generated machine-specific encryption key. "\n'
    '     "This is used to enable portable user data directories. Enabled for Thorium Portable.",\n'
    '     "Disables use of a generated machine-specific ID to lock the user data directory to that machine. This is used to enable portable user data directories. Enabled for Thorium Portable.",\n'
    '     "Allows downloading files from mixed origin/cross origin schemes.",\n'
    '     "Choose the password store backend, instead of using the automatically detected one. "\n'
    '    {"allow-offstore-extension-downloads",\n     "Allow Third-Party Extension Downloads",\n' + OFFSTORE
    + '     kOsAll, SINGLE_VALUE_TYPE("allow-offstore-extension-downloads")},\n'
    '     "Enables Thorium to automatically change to Dark Mode according to the system GTK Theme.",\n'
    '     "Allows Thorium to use the detected GTK or Qt system theme on Linux instead of the default Thorium 2024 UI theme behavior.",\n'
    '    {"thorium-2024",\n     "Enable Experimental Thorium 2024 (Th24) UI",\n'
    '     kOsDesktop, FEATURE_VALUE_TYPE(features::kThorium2024)},\n'
    '     "Force disables tab outline strokes. Thorium enables them by default, improving accessiblity in dark mode, incognito mode, and low contrast themes.",\n'
    '    {"disable-thorium-icons",\n     "Disable Thorium Custom Icons",\n'
    '     "Uses Chromium\'s default icon designs and colors instead of "\n'
    '     "Thorium\'s custom icons throughout the browser UI.",\n'
    '    {"rectangular-tabs",\n     "Thorium Rectangular Tabs UI",\n'
    '    {"disable-thorium-dns-config",\n     "Disable Thorium Secure DNS Fallback",\n'
    '     "Disables Thorium\'s fallback that keeps explicitly configured Secure DNS-over-HTTPS available when the platform DNS configuration is unavailable. "\n'
    '     "Controls whether Thorium allows TLS Encrypted ClientHello. Enabled still requires server support and usable HTTPS/SVCB DNS records.",\n'
    '     "Enables high contrast mode for all Thorium instances.",\n'
    '     "When enabled, the traditional download shelf is used instead of the download bubble in the toolbar. Thorium flag",\n'
    '     "Retain All local browsing history. By default history older than 4 months is expired and purged. Thorium flag",\n'
    '     "Enabled by default, but may break some configurations. Thorium flag.",\n'
    '     "Requires `vdpau-va-driver` to be installed, and can be buggy. Thorium flag.",\n'
    '     "Inform Thorium\'s GPU process that a GPU context will not be lost in power saving mode, screen saving mode, etc. "\n'
    '     "Media router is a component responsible for pairing Thorium to devices and endpoints, "\n'
    '     "When moving a Thorium user profile from one drive to another (or one system to another), enable this flag before moving the profile directory. It should also be used "\n'
).replace("\n", "\r\n")


class OverlayEditTests(unittest.TestCase):
    def test_risky_flags_start_with_a_warning(self):
        out = ti.edit_overlay(FLAGS, FLAG_ENTRIES)
        self.assertEqual(out.count('"Warning: '), 6)
        self.assertIn("every website can read data from every other website", out)
        self.assertIn("stored unencrypted", out)
        self.assertNotIn("Thorium Portable", out)
        self.assertIn("Don't enforce the same-origin policy", out)          # the original text stays

    def test_extensions_from_other_sites_carry_a_warning(self):
        out = ti.edit_overlay(FLAGS, FLAG_ENTRIES)
        line = next(l for l in out.split("\r\n") if "Allows downloaded CRX files" in l)
        self.assertTrue(line.startswith('     "Warning: with this on and developer mode enabled, any website can offer'))
        self.assertIn("Only the permission prompt stands before the install", line)
        self.assertIn("signature does not show who made it", line)
        self.assertTrue(line.endswith('Only enable this for sources you trust.",'))
        self.assertNotIn("Android", line)                                    # does not apply to Thoron
        self.assertNotIn("still apply", line)                                # read as more than it is
        self.assertIn('"Allow Third-Party Extension Downloads",', out)       # the flag itself stays, off by default

    def test_a_reworded_extension_flag_raises(self):
        with self.assertRaisesRegex(ti.IdentityError, "Allows downloaded CRX files"):
            ti.edit_overlay(FLAGS, FLAG_ENTRIES.replace("Only enable this for sources you trust", "Be careful"))

    def test_flag_texts_name_thoron(self):
        out = ti.edit_overlay(FLAGS, FLAG_ENTRIES)
        self.assertEqual(out.count(". Thoron flag"), 4)
        self.assertIn('"Rectangular Tabs UI",', out)
        self.assertIn("Disables Thoron's fallback", out)
        self.assertIn("for pairing Thoron to devices", out)
        left = re.findall(r"Thorium[^\"]{0,20}", out)
        self.assertEqual(sorted(set(left)), ["Thorium 2024 (Th24) UI", "Thorium 2024 UI theme behav", "Thorium Custom Icons",
                                             "Thorium's custom icons thro", "Thorium2024)},\r\n     "])

    def test_a_new_flag_text_that_names_thorium_raises(self):
        with self.assertRaisesRegex(ti.IdentityError, "left over after the edit: 'Thorium'"):
            ti.edit_overlay(FLAGS, FLAG_ENTRIES + '     "Thorium Turbo Mode",\r\n')

    def test_idempotent_and_keeps_windows_line_endings(self):
        once = ti.edit_overlay(FLAGS, FLAG_ENTRIES)
        self.assertEqual(ti.edit_overlay(FLAGS, once), once)
        self.assertNotIn("\n", once.replace("\r\n", ""))

    def test_changed_upstream_text_raises(self):
        with self.assertRaisesRegex(ti.IdentityError, "thorium_flag_entries.h"):
            ti.edit_overlay(FLAGS, FLAG_ENTRIES.replace("Allows downloading files", "Allows downloads"))

    def test_apply_covers_the_overlay_file(self):
        self.assertIn(FLAGS, ti.OVERLAY_EDITS)


VERSION_HTML = "components/webui/version/resources/about_version.html"
VERSION_PAGE = (
    '        <picture title="Thorium Banner">\n'
    '          <img alt="$i18n{logo_alt_text}" src="chrome://theme/IDR_PRODUCT_LOGO">\n'
    '        <picture title="Thorium Banner">\n'
    '        <div id="company"><a target="_blank" rel="noopener" href="https://github.com/Alex313031/thorium">$i18n{company}</a></div>\n'
    '          <div id="thor_version"><a target="_self" rel="noopener" '
    'href="chrome://resources/text/thorium_version.txt">THORIUM_VERSION.txt</a></div>\n'
    '        <!-- Thorium Mascot. -->\n        <picture title="Thorium Mascot">\n'
    '          <img alt="Thorium Mascot" src="chrome://theme/IDR_PRODUCT_MASCOT">\n'
    '        <!-- Thorium Mascot. -->\n        <picture title="Thorium Mascot">\n'
    '          <img alt="Thorium Mascot" src="images/thorium_mascot.png">\n')


class VersionPageTests(unittest.TestCase):
    def test_build_variant_link_is_not_named_after_thorium(self):
        out = ti.edit_overlay(VERSION_HTML, VERSION_PAGE)
        self.assertIn(">BUILD_VARIANT.txt</a>", out)
        self.assertNotIn("THORIUM_VERSION", out)
        self.assertIn("chrome://resources/text/thorium_version.txt", out)    # the resource path stays
        self.assertEqual(ti.edit_overlay(VERSION_HTML, out), out)

    def test_tooltips_and_the_company_link_are_thorons(self):
        out = ti.edit_overlay(VERSION_HTML, VERSION_PAGE)
        self.assertNotIn("Thorium", out)
        self.assertEqual(out.count('title="Thoron"'), 2)
        self.assertEqual(out.count('alt="Thoron logo"'), 2)
        self.assertIn('href="https://github.com/KuchiSofts/thoron">$i18n{company}</a>', out)
        self.assertIn('src="images/thorium_mascot.png"', out)                # file names stay

    def test_a_changed_page_raises(self):
        with self.assertRaisesRegex(ti.IdentityError, "about_version.html"):
            ti.edit_overlay(VERSION_HTML, VERSION_PAGE.replace('title="Thorium Banner"', 'title="Thorium Wordmark"'))


OVERLAY_FIXTURES = {FLAGS: FLAG_ENTRIES, VERSION_HTML: VERSION_PAGE}


class CoverageTests(unittest.TestCase):
    def test_every_file_has_a_fixture(self):
        self.assertEqual(set(ti.OVERLAY_EDITS), set(OVERLAY_FIXTURES))


if __name__ == "__main__":
    unittest.main()
