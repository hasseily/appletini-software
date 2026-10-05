"""Verify the C++ SSI clock driver against the original timed SV test bench."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest

from phasor import fast_rtl, rtl
from phasor.hardware import pack_pitch, ssi_pitch
from tests.test_rtl import _startup


@unittest.skipUnless(os.environ.get("PHASOR_FIRMWARE_ROOT") and
                     (shutil.which("verilator") or shutil.which("verilator-cli")),
                     "Set PHASOR_FIRMWARE_ROOT and install Verilator for exact PCM checks")
class FastSSIEquivalenceTests(unittest.TestCase):
    def test_all_samples_and_stats_match_timed_driver_both_regions(self):
        """Exercise live pitch/FF/phone/CTL/amp changes, stereo and hard resets."""
        first = _startup(4, 160, 96) + _startup(5, 220, 160)
        inflection, rate = pack_pitch(ssi_pitch(283)[0])
        middle = [(80, 4, 1, inflection), (80, 4, 2, rate),
                  (90, 5, 4, 220), (105, 4, 0, 0xB2), (120, 5, 3, 0),
                  (140, 5, 3, 0x7F), (150, 4, 4, 255), (155, 4, 3, 0x80),
                  (160, 4, 0, 0xA1), (165, 4, 3, 0x5D)]
        restarted = [(200 + tick, target, register, value)
                     for tick, target, register, value in first]
        # AY writes are ignored; endpoint writes are outside the captured PCM.
        events = [(0, 0, 0, 77)] + first + middle + restarted + [(350, 5, 3, 0)]
        firmware = Path(os.environ["PHASOR_FIRMWARE_ROOT"])
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            cache = Path(os.environ.get("PHASOR_RTL_CACHE", str(folder / "cache")))
            for xck in (2_040_968, 2_031_250):
                with self.subTest(xck=xck):
                    reference, candidate = folder / "reference.wav", folder / "candidate.wav"
                    arguments = (events, 1000, 350, firmware)
                    a = rtl.render(*arguments, reference, cache, xck_hz=xck, reset_ticks=(200,))
                    b = fast_rtl.render(*arguments, candidate, cache, xck_hz=xck, reset_ticks=(200,))
                    self.assertEqual(reference.read_bytes(), candidate.read_bytes())
                    for field in ("frames", "writes", "starts", "dones", "xck_edges",
                                  "max_event_delay_cycles", "bank_resets", "pitch_period_histograms"):
                        self.assertEqual(a[field], b[field], field)
                    self.assertGreater(a["starts"][0], 1)
                    self.assertGreater(a["starts"][1], 1)


if __name__ == "__main__":
    unittest.main()
