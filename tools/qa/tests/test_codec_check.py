# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of codec_check.py that do not need a browser."""
import unittest

from tools.qa import codec_check as cc

GPU_TEXT = ("Sandboxed :trueGPU0                            :VENDOR= 0x10de, DEVICE=0x0001 [a card], SUBSYS=0x1, "
            "REV=161, LUID={0,176604174}, DRIVER_VENDOR=NVIDIA, DRIVER_VERSION=32 *ACTIVE*GPU1                    "
            "        :VENDOR= 0x1002, DEVICE=0x0002 [other], SUBSYS=0x2, REV=193, LUID={0,112457}, DRIVER_VERSION=32"
            "GPU2                            :VENDOR= 0x1414, DEVICE=0x008c [software], LUID={0,112334}, "
            "DRIVER_VERSION=10Optimus                         :false")


class CodecTests(unittest.TestCase):
    def test_the_adapters_chrome_gpu_lists(self):
        found = cc.adapters(GPU_TEXT)
        self.assertEqual([(a["vendor"], a["luid"], a["active"]) for a in found],
                         [("NVIDIA", "0,176604174", True), ("AMD", "0,112457", False),
                          ("Microsoft (software)", "0,112334", False)])
        self.assertNotIn("card", str(found))            # the model's name is never kept

    def test_the_decoder_from_the_media_domain(self):
        events = [{"method": "Media.playerPropertiesChanged", "params": {"properties": [
            {"name": "kVideoDecoderName", "value": "\"D3D11VideoDecoder\""},
            {"name": "kIsPlatformVideoDecoder", "value": "true"}]}},
            {"method": "Page.loadEventFired", "params": {}}]
        self.assertEqual(cc.decoder_of(events), {"decoder": "D3D11VideoDecoder", "hardware": True})
        self.assertEqual(cc.decoder_of([]), {})

    def test_what_a_clip_must_do(self):
        good = {"total": 301, "dropped": 2, "bright": 127, "error": ""}
        self.assertEqual(cc.clip_problems("x", good, 5, 1.0), [])
        self.assertIn("dropped", cc.clip_problems("x", {**good, "dropped": 30}, 5, 1.0)[0])
        self.assertIn("black", cc.clip_problems("x", {**good, "bright": 0.5}, 5, 1.0)[0])
        self.assertIn("frames in", cc.clip_problems("x", {**good, "total": 40}, 5, 1.0)[0])
        self.assertIn("failed", cc.clip_problems("x", {**good, "error": "4 unsupported"}, 5, 1.0)[0])
        self.assertIn("could not be read", cc.clip_problems("x", None, 5, 1.0)[0])

    def test_the_clips_cover_the_codecs_of_the_reports(self):
        names = {pattern.split("-")[0] for pattern, *_ in cc.MEDIA}
        self.assertEqual(names, {"h264", "hevc", "hevc10", "av1", "vp9"})
        self.assertEqual([size for size, _ in cc.SIZES], ["1920x1080", "3840x2160"])


if __name__ == "__main__":
    unittest.main()
