#!/usr/bin/env python3
"""Hardware-clock debug rates and SHR bounds, executing the banked 65C02 code.

The readout uses injected VBL/tic/frame counter snapshots. This verifies its
arithmetic and write traffic independently of any emulator speed assumption.
Far writes use the standalone harness's transport trap; the complete kernel
bridge and live clock are covered by the platform integration suite.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/host"))
import bankedsim  # noqa: E402

BUILD = ROOT / "build/host/debug-readout"
READY = (ROOT / "build/data/manifest.json").is_file()
SHR_START = 0x2000
ROW_BYTES = 320
READOUT_START = SHR_START + ROW_BYTES * 84
READOUT_END = SHR_START + ROW_BYTES * 100


class ReadoutGame(bankedsim.BankedGame):
    def __init__(self):
        self.writes = []
        super().__init__(BUILD)

    def _far_write(self):
        destination = self.zp("far_dst", 3)
        length = self.zp("far_len", 2)
        self.writes.append((destination >> 16, destination & 0xFFFF, length))
        return super()._far_write()

    def sample(self, vbl, tics, frames):
        for name, value in (("_debug_vbl", vbl), ("_debug_tics", tics),
                            ("_debug_frames", frames)):
            address = self.L[name]
            self.mem[address:address + 2] = (value & 0xFFFF).to_bytes(2, "little")
        self.call("_debug_readout", limit=2_000_000)
        return self.word("_debug_fps10"), self.word("_debug_tps10")


@unittest.skipUnless(READY, "requires converted game data")
class DebugReadoutTest(unittest.TestCase):
    def test_two_second_window_and_no_early_refresh(self):
        game = ReadoutGame()
        self.assertEqual(game.sample(1000, 2000, 3000), (0, 0))
        self.assertEqual(game.word("_debug_updates"), 0)
        placeholder = bytes(game.bank(0)[READOUT_START:READOUT_END])
        self.assertGreater(len(set(placeholder)), 1, "the initial placeholder is blank")
        initial_writes = list(game.writes)

        self.assertEqual(game.sample(1119, 2069, 3011), (0, 0))
        self.assertEqual(game.writes, initial_writes, "an incomplete window must not redraw")
        self.assertEqual(game.word("_debug_updates"), 0)

        self.assertEqual(game.sample(1120, 2070, 3012), (60, 350))
        self.assertEqual(game.word("_debug_updates"), 1)
        self.assertNotEqual(bytes(game.bank(0)[READOUT_START:READOUT_END]), placeholder)
        refreshed_writes = list(game.writes)
        self.assertEqual(game.sample(1120, 2070, 3012), (60, 350))
        self.assertEqual(game.writes, refreshed_writes, "a repeated snapshot must not redraw")

    def test_uses_actual_elapsed_time_and_restarts_each_window(self):
        game = ReadoutGame()
        game.sample(500, 800, 900)
        # A slow frame can overshoot two seconds. Divide by the observed
        # three seconds, with truncation at one decimal place.
        self.assertEqual(game.sample(680, 905, 937), (123, 350))
        self.assertEqual(game.word("_debug_updates"), 1)
        # The next sample is relative to that refresh, not the first call.
        self.assertEqual(game.sample(800, 975, 946), (45, 350))
        self.assertEqual(game.word("_debug_updates"), 2)

    def test_pal_calibration_toggle_is_edge_triggered_and_resets_window(self):
        game = ReadoutGame()
        game.sample(0, 0, 0)
        self.assertEqual(game.byte("_debug_hz"), 60)
        game.sample(120, 70, 20)
        updates = game.word("_debug_updates")
        keyboard = game.L["_kin"] + 4

        game.mem[keyboard] = ord("V")
        self.assertEqual(game.sample(150, 77, 23), (0, 0))
        self.assertEqual(game.byte("_debug_hz"), 50)
        self.assertEqual(game.word("_debug_updates"), updates)
        placeholder = bytes(game.bank(0)[READOUT_START:READOUT_END])
        write_count = len(game.writes)
        # Holding V must neither toggle back nor restart the PAL window.
        game.sample(249, 146, 32)
        self.assertEqual(game.byte("_debug_hz"), 50)
        self.assertEqual(len(game.writes), write_count)
        self.assertEqual(game.word("_debug_updates"), updates)
        self.assertEqual(game.sample(250, 147, 33), (50, 350))
        self.assertEqual(game.byte("_debug_hz"), 50)
        self.assertEqual(game.word("_debug_updates"), updates + 1)
        self.assertNotEqual(bytes(game.bank(0)[READOUT_START:READOUT_END]), placeholder)

        game.mem[keyboard] = 0
        game.sample(251, 147, 33)
        game.mem[keyboard] = ord("V")
        self.assertEqual(game.sample(300, 177, 40), (0, 0))
        self.assertEqual(game.byte("_debug_hz"), 60)
        self.assertEqual(game.word("_debug_updates"), updates + 1)
        write_count = len(game.writes)
        game.sample(419, 246, 51)
        self.assertEqual(game.byte("_debug_hz"), 60)
        self.assertEqual(len(game.writes), write_count)
        # The resumed 60 Hz measurement uses the new baseline at VBL 300.
        self.assertEqual(game.sample(420, 247, 52), (60, 350))
        self.assertEqual(game.word("_debug_updates"), updates + 2)

    def test_all_three_counters_wrap_independently(self):
        for base in ((65500, 4000, 5000), (1000, 65520, 4000),
                     (1000, 4000, 65530), (65500, 65520, 65530)):
            with self.subTest(baseline=base):
                game = ReadoutGame()
                game.sample(*base)
                self.assertEqual(game.sample(base[0] + 120, base[1] + 70, base[2] + 13),
                                 (65, 350))
                self.assertEqual(game.word("_debug_updates"), 1)
                self.assertEqual(game.sample(base[0] + 240, base[1] + 80, base[2] + 15),
                                 (10, 50))

    def test_wide_multiply_long_interval_zero_rate_and_saturation(self):
        cases = (
            # delta * 600 exceeds 16 bits, but the displayed result fits.
            (120, 300, 200, (1000, 1500)),
            # Long windows exercise a divisor with its high bit set.
            (60000, 65535, 65535, (655, 655)),
            (120, 0, 0, (0, 0)),
            # The display's four digits include the fractional digit.
            (120, 65535, 65535, (9999, 9999)),
        )
        for elapsed, tics, frames, expected in cases:
            with self.subTest(elapsed=elapsed, tics=tics, frames=frames):
                game = ReadoutGame()
                game.sample(0, 0, 0)
                self.assertEqual(game.sample(elapsed, tics, frames), expected)

    def test_draws_only_text_rows_in_bottom_strip(self):
        game = ReadoutGame()
        pixels = game.bank(0)
        # Nonzero, nonuniform canaries catch both unexpected clear operations
        # and stray writes before or after the intended SHR region.
        pixels[:] = bytes((address * 17 + (address >> 8)) & 255 for address in range(65536))
        before = bytes(pixels)
        text_start, text_end = SHR_START + ROW_BYTES * 88, SHR_START + ROW_BYTES * 95
        game.sample(100, 100, 100)
        self.assertTrue(game.writes)
        for bank, address, length in game.writes:
            self.assertEqual(bank, 0)
            self.assertGreaterEqual(address, text_start)
            self.assertLessEqual(address + length, text_end)
        self.assertEqual(bytes(pixels[:text_start]), before[:text_start])
        self.assertEqual(bytes(pixels[text_end:]), before[text_end:])

        after_initial = bytes(pixels)
        game.writes.clear()
        game.sample(220, 170, 112)
        self.assertTrue(game.writes)
        for bank, address, length in game.writes:
            self.assertEqual(bank, 0)
            self.assertGreaterEqual(address, text_start)
            self.assertLessEqual(address + length, text_end)
        self.assertEqual(bytes(pixels[:text_start]), after_initial[:text_start])
        self.assertEqual(bytes(pixels[text_end:]), after_initial[text_end:])


if __name__ == "__main__":
    unittest.main()
