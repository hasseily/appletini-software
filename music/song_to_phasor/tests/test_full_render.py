"""Neutral mixer arithmetic and opt-in tests of all six actual firmware chips."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest
import wave

import numpy as np

from phasor.full_render import DEFAULT_PAN, mix_ay, render_ay, render_full
from phasor.hardware import AY_NATIVE_CLOCK_HZ, ay_period, pack_pitch, ssi_pitch
from phasor.rtl import FABRIC_HZ, SAMPLE_RATE, render as render_ssi


def _read(path):
    with wave.open(str(path), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (2, 2, SAMPLE_RATE)
        return np.frombuffer(wav.readframes(wav.getnframes()), "<i2").reshape(-1, 2).astype(np.int32)


def _ay_tone(chip, hz, tick=0, amp=15):
    period, _ = ay_period(hz, AY_NATIVE_CLOCK_HZ)
    return [(tick, chip, reg, value) for reg, value in
            ((7, 0x3E), (0, period & 255), (1, period >> 8), (8, amp))]


class MixerTests(unittest.TestCase):
    def test_firmware_shift_rounding_and_default_pan(self):
        channels = np.zeros((1, 12), dtype=np.uint8)
        channels[0, 0] = 255
        # Default channel 0 pan 11 => gain L9/R16. Each term shifts separately.
        self.assertEqual(DEFAULT_PAN, (11, 5) * 6)
        self.assertEqual(mix_ay(channels).tolist(), [[(127 + 15) * 16, 255 * 16]])
        self.assertEqual(mix_ay(channels, (0,) * 12).tolist(), [[4080, 0]])
        self.assertEqual(mix_ay(channels, (15,) * 12).tolist(), [[0, 4080]])

    def test_neutral_ay_mixer_saturates_and_preserves_zero(self):
        self.assertTrue(np.all(mix_ay(np.zeros((2, 12), np.uint8)) == 0))
        self.assertEqual(mix_ay(np.full((1, 12), 255, np.uint8), (8,) * 12).tolist(),
                         [[32767, 32767]])

    def test_rejects_bad_pan_and_path_aliases_before_firmware_access(self):
        for pan in ((0,) * 11, (16,) * 12, (True,) * 12):
            with self.subTest(pan=pan), self.assertRaises(ValueError):
                mix_ay(np.zeros((1, 12), np.uint8), pan)
        with self.assertRaises(ValueError):
            render_full([], 100, 10, Path("absent"), Path("same.wav"), Path("cache"),
                        vocal_output=Path("same.wav"))


@unittest.skipUnless(os.environ.get("PHASOR_FIRMWARE_ROOT") and
                     (shutil.which("verilator") or shutil.which("verilator-cli")),
                     "Set PHASOR_FIRMWARE_ROOT and install Verilator for real RTL audio tests")
class FullFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="phasor-full-tests-")
        cls.folder = Path(cls.temporary.name)
        cls.firmware = Path(os.environ["PHASOR_FIRMWARE_ROOT"])
        cls.cache = Path(os.environ.get("PHASOR_RTL_CACHE", str(cls.folder / "cache")))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_four_real_ay_targets_pitch_pan_clock_and_silence(self):
        # Each chip plays alone for 0.1 s, then all volumes go to zero.
        events = []
        for chip in range(4):
            events += _ay_tone(chip, 400, tick=chip * 100)
            events += [((chip + 1) * 100, chip, 8, 0)]
        pan = (0, 0, 0, 15, 15, 15, 0, 0, 0, 15, 15, 15)
        path = self.folder / "four.wav"
        metadata = render_ay(events, 1000, 450, self.firmware, path, self.cache, pan=pan)
        audio = _read(path)
        self.assertLess(abs(metadata["ce_edges"] - .45 * AY_NATIVE_CLOCK_HZ), 3)
        for chip in range(4):
            segment = audio[(chip * 4800 + 480):(chip + 1) * 4800 - 480]
            active, quiet = chip % 2, 1 - chip % 2
            self.assertGreater(np.max(segment[:, active]), 1000)
            self.assertTrue(np.all(segment[:, quiet] == 0))
            spectrum = abs(np.fft.rfft(segment[:, active] - np.mean(segment[:, active])))
            frequency = np.argmax(spectrum) * SAMPLE_RATE / len(segment)
            self.assertAlmostEqual(frequency, 400, delta=15)
        self.assertTrue(np.all(audio[400 * 48 + 48:] == 0))

    def test_skipped_idle_cycles_match_dense_fabric_for_noise_envelope_and_writes(self):
        # Register writes coincide with other chips' active tones, change the
        # LFSR period, and retrigger a saw envelope. Compare every output bit.
        events = sorted(_ay_tone(0, 333) + _ay_tone(1, 700) + _ay_tone(3, 123) +
                        [(0, 2, 7, 0), (0, 2, 6, 3), (0, 2, 8, 16),
                         (0, 2, 11, 12), (0, 2, 13, 10),
                         (11, 2, 6, 7), (13, 2, 13, 14), (17, 0, 8, 10)], key=lambda event: event[0])
        paths = [self.folder / "sparse.wav", self.folder / "dense.wav"]
        fast = render_ay(events, 1000, 35, self.firmware, paths[0], self.cache)
        dense = render_ay(events, 1000, 35, self.firmware, paths[1], self.cache, _dense=True)
        np.testing.assert_array_equal(_read(paths[0]), _read(paths[1]))
        self.assertEqual(dense["evaluated_cycles"], 35 * FABRIC_HZ // 1000)
        self.assertLess(fast["evaluated_cycles"], dense["evaluated_cycles"] / 3)

    def test_full_mix_preserves_isolated_ssi_and_exact_stem_sum(self):
        word, _ = ssi_pitch(160)
        r1, r2 = pack_pitch(word)
        events = _ay_tone(0, 440, amp=12) + [
            (0, 5, reg, value) for reg, value in
            ((3, 128), (0, 129), (1, r1), (2, r2), (4, 128), (3, 127))]
        events += [(180, 0, 8, 0), (180, 5, 3, 0)]
        mixed, vocal, backing, reference = [self.folder / (name + ".wav")
                                            for name in ("mix", "vocal", "backing", "reference")]
        metadata = render_full(events, 1000, 250, self.firmware, mixed, self.cache,
                               pan=(0,) * 12, vocal_output=vocal, backing_output=backing)
        render_ssi(events, 1000, 250, self.firmware, reference, self.cache)
        np.testing.assert_array_equal(_read(vocal), _read(reference))
        np.testing.assert_array_equal(_read(mixed), np.clip(_read(vocal) + _read(backing), -32768, 32767))
        self.assertTrue(np.all(_read(vocal)[:, 0] == 0))
        self.assertTrue(np.all(_read(backing)[:, 1] == 0))
        self.assertGreater(np.max(np.abs(_read(vocal)[:, 1])), 100)
        # The actual SSI filter settles to a two-LSB fixed-point residual;
        # preserve it rather than silently adding a software DC blocker.
        self.assertLessEqual(np.max(np.abs(_read(mixed)[220 * 48:])), 2)
        self.assertEqual(metadata["normalization"], "none; native card gain, no DC removal")


if __name__ == "__main__":
    unittest.main()
