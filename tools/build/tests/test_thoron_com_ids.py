# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron's own COM interface IDs (ROADMAP P2.19): the IDL placeholders and MIDL's dynamic GUIDs."""
import unittest

from tools.build import thoron_identity as ti

_MIDL = """midl("{name}") {{
  sources = [ "{name}.idl" ]

  writes_tlb = true
}}
"""
COM_FIXTURES = {
    "chrome/elevation_service/elevation_service_idl.idl":
        "[\n  object,\n  uuid(BB19A0E5-00C6-4966-94B2-5AFEC6FED93A),\n]\ninterface IElevator2Chromium : IElevator2\n",
    "chrome/elevation_service/BUILD.gn": _MIDL.format(name="elevation_service_idl"),
    "chrome/windows_services/elevated_tracing_service/tracing_service_idl.idl":
        "[\n  uuid(E0B03E2D-7682-4D83-B9FF-4574AF720500),\n]\ninterface ISystemTraceSessionChromium\n",
    "chrome/windows_services/elevated_tracing_service/BUILD.gn": _MIDL.format(name="tracing_service_idl"),
}
for _idl in ("chrome/elevation_service/elevation_service_idl",
             "chrome/windows_services/elevated_tracing_service/tracing_service_idl"):
    for _arch in ("x64", "x86", "arm64"):
        for _suffix in (".h", "_i.c", "_p.c"):
            _name = _idl.rsplit("/", 1)[1]
            COM_FIXTURES[f"third_party/win_build_output/midl/{_idl.rsplit('/', 1)[0]}/{_arch}/{_name}{_suffix}"] = (
                f"/* Compiler settings for ../../{_idl}.idl:\r\n    Oicf, W1, Zp8 */\r\n")


class ComIdTests(unittest.TestCase):
    def test_the_fixtures_are_every_file_edited(self):
        self.assertEqual(set(ti.COM_EDITS), set(COM_FIXTURES))

    def test_placeholders_and_dynamic_guids_with_thorons_ids(self):
        idl = ti.edit_com_ids("chrome/elevation_service/elevation_service_idl.idl",
                              COM_FIXTURES["chrome/elevation_service/elevation_service_idl.idl"])
        self.assertIn("uuid(PLACEHOLDER-GUID-BB19A0E5-00C6-4966-94B2-5AFEC6FED93A)", idl)
        gn = ti.edit_com_ids("chrome/elevation_service/BUILD.gn", COM_FIXTURES["chrome/elevation_service/BUILD.gn"])
        self.assertIn(f'dynamic_guids = "ignore_proxy_stub,PLACEHOLDER-GUID-BB19A0E5-00C6-4966-94B2-5AFEC6FED93A='
                      f'{ti.THORON_IDS["elevator_iid"]}"', gn)
        rel = "chrome/windows_services/elevated_tracing_service/BUILD.gn"
        tracing = ti.edit_com_ids(rel, COM_FIXTURES[rel])
        self.assertIn(f'PLACEHOLDER-GUID-E0B03E2D-7682-4D83-B9FF-4574AF720500={ti.THORON_IDS["tracing_service_iid"]}',
                      tracing)
        # a second run changes nothing
        self.assertEqual(ti.edit_com_ids(rel, tracing), tracing)
        self.assertEqual(ti.edit_com_ids("chrome/elevation_service/elevation_service_idl.idl", idl), idl)

    def test_the_install_mode_registers_thorons_ids(self):
        from tools.build.tests.test_thoron_identity import INSTALL_MODES
        out = ti.edit_install_modes(INSTALL_MODES)
        self.assertIn(ti.guid_struct(ti.THORON_IDS["elevator_iid"]), out)
        self.assertIn(ti.guid_struct(ti.THORON_IDS["tracing_service_iid"]), out)
        self.assertNotIn("0xbb19a0e5", out.lower())
        self.assertNotIn("0xe0b03e2d", out.lower())

    def test_the_checked_in_midl_output_names_the_generated_idl(self):
        rel = "third_party/win_build_output/midl/chrome/elevation_service/arm64/elevation_service_idl_p.c"
        out = ti.edit_com_ids(rel, COM_FIXTURES[rel])
        self.assertIn("Compiler settings for gen/chrome/elevation_service/elevation_service_idl.idl:", out)
        self.assertEqual(ti.edit_com_ids(rel, out), out)
        self.assertEqual(len([r for r in ti.COM_EDITS if r.startswith("third_party/win_build_output/")]), 18)

    def test_the_ids_are_new_and_distinct(self):
        ids = {ti.THORON_IDS["elevator_iid"], ti.THORON_IDS["tracing_service_iid"], ti.ELEVATOR_OLD,
               ti.TRACING_OLD, ti.THORON_IDS["elevator_clsid"], ti.THORON_IDS["tracing_service_clsid"]}
        self.assertEqual(len(ids), 6)


if __name__ == "__main__":
    unittest.main()
