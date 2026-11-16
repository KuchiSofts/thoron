# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thorium's name where a person still reads it outside the string files (ROADMAP B.3)."""
import unittest

from tools.build import thoron_identity as ti

MI = "chrome/installer/mini_installer/"
VERSION_H = MI + "mini_installer_version.h.template"
VERSION_RC = MI + "mini_installer_exe_version.rc.version"
FLAGS_PAGE = "components/webui/flags/resources/app.html.ts"
FLAG_TEXTS = "chrome/browser/flag_descriptions.h"
URLS_PAGE = "components/webui/chrome_urls/resources/app.html.ts"
DINO = "components/neterror/resources/dino_game/offline.ts"
MAIN = "chrome/browser/chrome_browser_main.cc"
FEATURES = "chrome/common/chrome_features.cc"
LICENSES = "tools/licenses/licenses.py"
CREDITS = "components/webui/about/resources/about_credits_reciprocal.tmpl"
BROWSER_LOG = "chrome/common/logging_chrome.cc"
INSTALLER_LOG = "chrome/installer/util/logging_installer.cc"

# Excerpts of the files as upstream's series leaves them.
SURFACE_FIXTURES = {
    VERSION_H: ('static constexpr wchar_t kVersionString[] = L"@MAJOR@.@MINOR@.@BUILD@.@PATCH@";\n'
                'static constexpr wchar_t kProductName[] = L"Thorium";\n'),
    VERSION_RC: ('            VALUE "ProductName", "@PRODUCT_INSTALLER_FULLNAME@"\n'
                 '            VALUE "Comments", "https://github.com/Alex313031/Thorium"\n'),
    FLAGS_PAGE: ('        <div class="logo">\n'
                 '          <img width="48" height="48" title="Hazard Icon" alt="hazard.svg" '
                 'src="chrome://resources/images/hazard.svg">\n        </div>\n'
                 '        <h1 class="section-header-title">$i18n{heading}</h1>\n'
                 '      <span title="Thorium Version" id="version" class="flex">$i18n{version}</span>\n'),
    FLAG_TEXTS: ('inline constexpr char kEnableFtpDescription[] =\n'
                 '    "by default defers handling of the URL to the underlying platform. This "\n'
                 '    "Thorium flag is enabled by default.";\n'),
    URLS_PAGE: "<h1>Thorium URLs</h1>\n<h2>List of Thorium chrome:// URLs</h2>\n<ul>\n",
    DINO: ("const ARCADE_MODE_URL: string = 'chrome://dino/';\n"
           "const ARCADE_MODE2_URL: string = 'Thorium Dino Game';\n"
           "      document.title = ARCADE_MODE2_URL;\n    favicon16.href = THORIUM_DINO_FAVICON_16;\n"),
    MAIN: ('  if (first_run::IsChromeFirstRun()) {\n'
           '    if (!base::CommandLine::ForCurrentProcess()->HasSwitch(switches::kApp) &&\n'
           '        !base::CommandLine::ForCurrentProcess()->HasSwitch(switches::kAppId)) {\n'
           '      // Open Welcome page on first run.\n'
           '      browser_creator_->AddFirstRunTabs({GURL("https://thorium.rocks/welcome/")});\n'
           '      browser_creator_->AddFirstRunTabs(master_prefs_->new_tabs);\n    }\n  }\n'),
    FEATURES: ('BASE_FEATURE(kTreatUnsafeDownloadsAsActive, base::FEATURE_ENABLED_BY_DEFAULT);\n\n'
               'BASE_FEATURE(kThoriumInternalUrlSchemeBranding,\n             base::FEATURE_ENABLED_BY_DEFAULT);\n'),
    LICENSES: ("      'thorium_project': 'Thorium',\n      'thorium_link': 'https://github.com/Alex313031/thorium',\n"
               "      'opensource_project': 'Chromium',\n"),
    CREDITS: ('<div class="open-sourced">\n'
              '    {{thorium_project}} is based on {{opensource_project}} and is made available as source code\n'
              '    <a href="{{thorium_link}}">here</a>. Chromium source code is available '
              '<a href="{{opensource_link}}">here</a>.\n</div>\n'),
    BROWSER_LOG: '  const base::FilePath log_filename(FILE_PATH_LITERAL("thorium_debug.log"));\n',
    INSTALLER_LOG: ('#if BUILDFLAG(GOOGLE_CHROME_BRANDING)\n      FILE_PATH_LITERAL("chrome_installer.log");\n'
                    '#else  // BUILDFLAG(CHROMIUM_BRANDING)\n      FILE_PATH_LITERAL("thorium_installer.log");\n#endif\n'),
}


def edited(rel: str) -> str:
    return ti.edit_surface(rel, SURFACE_FIXTURES[rel])


class InstallerTests(unittest.TestCase):
    def test_the_dialogs_name_thoron(self):
        out = edited(VERSION_H)
        self.assertIn('kProductName[] = L"Thoron";', out)
        self.assertIn("@MAJOR@.@MINOR@.@BUILD@.@PATCH@", out)                 # the version text is not touched

    def test_file_properties_link_to_thorons_repository(self):
        out = edited(VERSION_RC)
        self.assertIn('VALUE "Comments", "https://github.com/KuchiSofts/thoron"', out)
        self.assertNotIn("Alex313031", out)

    def test_no_registry_key_is_renamed(self):
        # what an installed copy is found by stays as it is until a migration exists (docs/build/IDENTITY_LEFT.md)
        for table in (ti.SURFACE_EDITS, ti.OVERLAY_EDITS):
            for rel, spec in table.items():
                for old, new, _ in spec.get("replace", []):
                    self.assertNotIn("Software\\", old + new, rel)
                    self.assertNotIn("Uninstall", old + new, rel)
        for rel in (MI + "mini_installer_constants.cc", "chrome/installer/launcher_support/chrome_launcher_support.cc"):
            for old, new, _ in ti.EXE_EDITS[rel]["replace"]:
                self.assertIn(".exe", old, rel)                              # only the program file name


class PageTests(unittest.TestCase):
    def test_flags_page_shows_thorons_logo_and_name(self):
        out = edited(FLAGS_PAGE)
        self.assertIn('<img width="48" height="48" alt="" src="chrome://theme/current-channel-logo@2x">', out)
        self.assertIn('title="Thoron version"', out)
        self.assertNotIn("hazard", out)
        self.assertNotIn("Thorium", out)

    def test_flag_text(self):
        self.assertIn('"Thoron flag is enabled by default.";', edited(FLAG_TEXTS))

    def test_urls_page(self):
        out = edited(URLS_PAGE)
        self.assertIn("<h1>Thoron URLs</h1>", out)
        self.assertIn("<h2>List of Thoron chrome:// URLs</h2>", out)

    def test_dino_page_title(self):
        out = edited(DINO)
        self.assertIn("ARCADE_MODE2_URL: string = 'Thoron Dino Game';", out)
        self.assertIn("THORIUM_DINO_FAVICON_16", out)                         # a name in code stays

    def test_credits_page_names_thoron_and_keeps_thorium(self):
        out = edited(CREDITS)
        self.assertIn("{{thorium_project}} is based on Thorium and {{opensource_project}} and is made available", out)
        self.assertIn('<a href="{{thorium_link}}">here</a>. Thorium source code is available '
                      '<a href="https://github.com/Alex313031/thorium">here</a>. Chromium source code is available', out)
        values = edited(LICENSES)
        self.assertIn("'thorium_project': 'Thoron',", values)
        self.assertIn("'thorium_link': 'https://github.com/KuchiSofts/thoron',", values)


class BehaviourTests(unittest.TestCase):
    def test_first_start_opens_no_page_of_another_project(self):
        out = edited(MAIN)
        self.assertNotIn("thorium.rocks", out)
        self.assertNotIn("Welcome", out)
        self.assertIn("      browser_creator_->AddFirstRunTabs(master_prefs_->new_tabs);\n", out)   # Chromium's own line
        self.assertEqual(out.count("\n"), SURFACE_FIXTURES[MAIN].count("\n") - 2)

    def test_first_start_with_windows_line_endings(self):
        out = ti.edit_surface(MAIN, SURFACE_FIXTURES[MAIN].replace("\n", "\r\n"))
        self.assertNotIn("thorium.rocks", out)
        self.assertNotIn("\n", out.replace("\r\n", ""))

    def test_another_hard_coded_first_start_page_raises(self):
        moved = SURFACE_FIXTURES[MAIN].replace("https://thorium.rocks/welcome/", "https://example.org/hello/")
        with self.assertRaisesRegex(ti.IdentityError, "chrome_browser_main.cc"):
            ti.edit_surface(MAIN, moved)

    def test_internal_pages_are_not_shown_as_thorium_addresses(self):
        out = edited(FEATURES)
        self.assertIn("BASE_FEATURE(kThoriumInternalUrlSchemeBranding,\n             base::FEATURE_DISABLED_BY_DEFAULT);", out)
        self.assertIn("BASE_FEATURE(kTreatUnsafeDownloadsAsActive, base::FEATURE_ENABLED_BY_DEFAULT);", out)

    def test_log_files(self):
        self.assertIn('FILE_PATH_LITERAL("thoron_debug.log")', edited(BROWSER_LOG))
        out = edited(INSTALLER_LOG)
        self.assertIn('FILE_PATH_LITERAL("thoron_installer.log")', out)
        self.assertIn('FILE_PATH_LITERAL("chrome_installer.log")', out)       # the other branding's line stays


class EveryFileTests(unittest.TestCase):
    def test_every_file_has_a_fixture(self):
        self.assertEqual(set(ti.SURFACE_EDITS), set(SURFACE_FIXTURES))

    def test_idempotent(self):
        for rel in SURFACE_FIXTURES:
            once = edited(rel)
            self.assertNotEqual(once, SURFACE_FIXTURES[rel], rel)
            self.assertEqual(ti.edit_surface(rel, once), once, rel)

    def test_changed_upstream_text_raises_and_names_the_file(self):
        for rel, text in SURFACE_FIXTURES.items():
            if rel == MAIN:
                continue                                                      # a removal: see BehaviourTests
            changed = text.replace("Thorium", "Thorium Browser").replace("thorium", "thorium2").replace(
                "FEATURE_ENABLED_BY_DEFAULT);\n", "FEATURE_ENABLED_BY_DEFAULT\n);\n")
            with self.assertRaisesRegex(ti.IdentityError, rel.rsplit("/", 1)[-1], msg=rel):
                ti.edit_surface(rel, changed)


if __name__ == "__main__":
    unittest.main()
