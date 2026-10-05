"""Checks against the pitch counter and SSI mode/IRQ bus contract."""

import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phasor import hardware


class PitchTests(unittest.TestCase):
    def test_all_pitch_words_round_trip_with_independent_rate(self):
        for inflection in range(4096):
            for rate in (0, 7, 15):
                r1, r2 = hardware.pack_pitch(inflection, rate)
                self.assertEqual(((r2 & 8) << 8) | (r1 << 3) | (r2 & 7), inflection)
                self.assertEqual(r2 >> 4, rate)

    def test_nearest_rendered_pitch_in_cents(self):
        for hz in (31.25, 65.406, 110, 220, 261.626, 440, 880, 1760, 12000):
            inflection, actual = hardware.ssi_pitch(hz)
            period = max(1, ((4096 - inflection) * 5) // 32)
            self.assertEqual(actual, 20000 / period)
            best_error = min(abs(math.log2((20000 / p) / hz)) for p in range(1, 641))
            self.assertAlmostEqual(abs(math.log2(actual / hz)), best_error)

    def test_pitch_uses_firmware_counter_not_ideal_chip_formula(self):
        inflection, actual = hardware.ssi_pitch(440)
        ideal_chip_pitch = 1_000_000 / (8 * (4096 - inflection))
        self.assertLess(abs(actual - 440), abs(ideal_chip_pitch - 440))

    def test_out_of_range_pitch_clamps_and_reports_actual(self):
        self.assertEqual(hardware.ssi_pitch(1e-300), (0, 31.25))
        self.assertEqual(hardware.ssi_pitch(1e300)[1], 20000)
        self.assertEqual(hardware.ay_period(5e-324, 2_046_000)[0], 4095)
        self.assertEqual(hardware.ay_period(1e300, 2_046_000)[0], 1)

    def test_ay_pitch_uses_supplied_native_clock(self):
        period, actual = hardware.ay_period(440, 2_046_000)
        self.assertEqual(period, 291)
        self.assertEqual(actual, 2_046_000 / (16 * period))
        self.assertLessEqual(abs(math.log2(actual / 440)),
                             abs(math.log2((2_046_000 / (16 * 290)) / 440)))

    def test_invalid_controls_fail_before_packing(self):
        for value in (0, -1, float("nan"), float("inf"), True, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                hardware.ssi_pitch(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                hardware.ay_period(value, 2_046_000)
        for inflection, rate in ((-1, 0), (4096, 0), (3.5, 0), (0, 16), (0, -1)):
            with self.assertRaises(ValueError):
                hardware.pack_pitch(inflection, rate)

    def test_duration_fit_selects_nearest_native_interval(self):
        for seconds in (0.001, 0.04, 0.128, 0.9):
            duration, rate, actual = hardware.fit_duration(seconds)
            self.assertEqual(actual, 4096 * (4 - duration) * (16 - rate) / hardware.NTSC_CPU_HZ)
            nearest = min(abs(4096 * (4 - d) * (16 - r) / hardware.NTSC_CPU_HZ - seconds)
                          for d in range(4) for r in range(16))
            self.assertEqual(abs(actual - seconds), nearest)


class SSIInitializationTests(unittest.TestCase):
    def test_init_sets_mode_two_then_masks_irqs(self):
        # Model the wrapper's CTL edge semantics independently of the setup
        # sequence, starting from any retained function/interrupt state.
        for initial_mode in range(4):
            for chip in (0, 1):
                control, duration = 0x5F, 0xFF
                function, irq_enabled = initial_mode, True
                latched_modes = []
                for target, register, value in hardware.ssi_initialize(chip):
                    self.assertEqual(target, 4 + chip)
                    if register == 0:
                        self.assertTrue(control & 0x80)
                        duration = value
                    elif register == 3:
                        if control & 0x80 and not value & 0x80:
                            if duration >> 6:
                                function = duration >> 6
                                irq_enabled = True
                            else:
                                irq_enabled = False
                            latched_modes.append((function, irq_enabled))
                        control = value
                self.assertEqual(latched_modes, [(2, True), (2, False)])
                self.assertEqual((function, irq_enabled, control), (2, False, 0))

    def test_socket_ids_reject_out_of_bounds(self):
        for chip in (-1, 2, True):
            with self.assertRaises(ValueError):
                hardware.ssi_initialize(chip)

    def test_filter_starts_at_firmware_neutral_before_unmuting(self):
        writes = hardware.ssi_initialize(0)
        self.assertIn((4, 4, 128), writes)
        self.assertLess(writes.index((4, 4, 128)), writes.index((4, 3, 0)))


class FirmwareInspectionTests(unittest.TestCase):
    def test_version_label_alone_does_not_verify_firmware(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in hardware.FIRMWARE_SOURCE_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder\n")
            (root / hardware.FIRMWARE_SOURCE_FILES[0]).write_text(
                '#define APPLETINI_FIRMWARE_IMAGE_VERSION_SHORT "F1.2.4"\n')
            result = hardware.firmware_info(root)
            self.assertTrue(result["version_matches"])
            self.assertFalse(result["verified"])
            with patch.object(hardware, "TARGET_SOURCE_SHA256", result["sources"]):
                self.assertTrue(hardware.firmware_info(root)["verified"])
                (root / "hdl/apple/sc01a_digital_core.sv").write_text("changed\n")
                changed = hardware.firmware_info(root)
                self.assertFalse(changed["verified"])
                self.assertEqual(changed["mismatches"], ["hdl/apple/sc01a_digital_core.sv"])


if __name__ == "__main__":
    unittest.main()
