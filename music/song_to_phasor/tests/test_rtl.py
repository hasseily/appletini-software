"""Pure input checks plus opt-in tests of actual F1.2.4 synthesized audio.

Run the integration checks with PHASOR_FIRMWARE_ROOT pointing to the pinned
firmware checkout. They compile Verilator once and reuse the binary throughout.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest
import wave

import numpy as np

from phasor.hardware import pack_pitch, ssi_pitch
from phasor.rtl import FABRIC_HZ, SAMPLE_RATE, XCK_HZ, _prepare_events, render, source_fingerprint, SOURCES


class EventValidationTests(unittest.TestCase):
    def test_preserves_equal_tick_order_and_filters_ay(self):
        events = [(0, 0, 13, 8), (1, 4, 3, 128), (1, 4, 0, 129), (2, 5, 7, 99)]
        self.assertEqual(_prepare_events(events, 1000, 10), [
            (FABRIC_HZ // 1000, 4, 3, 128),
            (FABRIC_HZ // 1000, 4, 0, 129),
            (2 * FABRIC_HZ // 1000, 5, 7, 99),
        ])

    def test_terminal_silence_is_valid_but_outside_pcm(self):
        self.assertEqual(_prepare_events([(10, 4, 3, 0)], 1000, 10), [])

    def test_rejects_invalid_and_unsorted_streams_before_build(self):
        cases = [([(2, 4, 0, 0), (1, 4, 0, 0)], 1000, 10),
                 ([(11, 4, 0, 0)], 1000, 10),
                 ([(0, 6, 0, 0)], 1000, 10),
                 ([(0, 4, 8, 0)], 1000, 10),
                 ([(0, 4, 0, 256)], 1000, 10),
                 ([(0, 4, 0, True)], 1000, 10),
                 ([], 0, 10), ([], 1000, -1)]
        for events, tick_hz, duration in cases:
            with self.subTest(events=events, tick_hz=tick_hz, duration=duration):
                with self.assertRaises(ValueError):
                    _prepare_events(events, tick_hz, duration)

    def test_fingerprint_changes_with_firmware_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in SOURCES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            before = source_fingerprint(root)
            self.assertEqual(before, source_fingerprint(root))
            (root / SOURCES[-1]).write_text("new firmware")
            self.assertNotEqual(before, source_fingerprint(root))

    def test_template_resets_validate_before_accessing_firmware(self):
        for resets in ((True,), (-1,), (14,), (1,)):
            with self.subTest(resets=resets), self.assertRaises(ValueError):
                render([], 7, 14, Path("missing-firmware"), Path("unused.wav"),
                       Path("unused-cache"), reset_ticks=resets)


def _startup(target: int, hz: float, ff: int = 128) -> list[tuple[int, int, int, int]]:
    word, _ = ssi_pitch(hz)
    inflection, rate = pack_pitch(word, rate=0)
    # Mode 2 latches on CTL falling; E is voiced, and all later pitch writes
    # must keep this single start alive without another DURPHON write.
    return [(0, target, reg, value) for reg, value in (
        (3, 0x80), (0, 0x81), (1, inflection), (2, rate), (4, ff), (3, 0x7F))]


def _read_audio(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (2, 2, SAMPLE_RATE)
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, 2).astype(float)


def _periodic_pitch(samples: np.ndarray, expected: float) -> float:
    """Find the actual waveform repetition near one expected glottal period."""
    signal = samples - np.mean(samples)
    low = int(SAMPLE_RATE / (expected * 1.10))
    high = int(SAMPLE_RATE / (expected * 0.90))
    correlations = [np.dot(signal[:-lag], signal[lag:]) /
                    max(1.0, np.linalg.norm(signal[:-lag]) * np.linalg.norm(signal[lag:]))
                    for lag in range(low, high + 1)]
    return SAMPLE_RATE / (low + int(np.argmax(correlations)))


@unittest.skipUnless(os.environ.get("PHASOR_FIRMWARE_ROOT") and
                     (shutil.which("verilator") or shutil.which("verilator-cli")),
                     "Set PHASOR_FIRMWARE_ROOT and install Verilator for real RTL audio tests")
class FirmwareAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="phasor-rtl-tests-")
        cls.folder = Path(cls.temporary.name)
        cls.firmware = Path(os.environ["PHASOR_FIRMWARE_ROOT"])
        cls.cache = Path(os.environ.get("PHASOR_RTL_CACHE", str(cls.folder / "cache")))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_audio(self, name, events, duration=600):
        output = self.folder / (name + ".wav")
        metadata = render(events, 1000, duration, self.firmware, output, self.cache)
        return _read_audio(output), metadata

    def test_ctl_startup_stereo_routing_and_rational_xck(self):
        audio, metadata = self.run_audio("left", _startup(4, 160), 400)
        self.assertGreater(np.max(np.abs(audio[:, 0])), 100)
        self.assertTrue(np.all(audio[:, 1] == 0))
        self.assertEqual(metadata["starts"], [1, 0])
        self.assertEqual(metadata["xck_edges"], metadata["frames"] * XCK_HZ // SAMPLE_RATE)
        no_ctl = [event for event in _startup(5, 160) if event[2] != 3 or event[3] == 128]
        muted, muted_meta = self.run_audio("no-start", no_ctl, 100)
        self.assertTrue(np.all(muted == 0))
        self.assertEqual(muted_meta["starts"], [0, 0])

    def test_live_inflection_changes_sung_pitch_without_phone_restart(self):
        word, achieved = ssi_pitch(220)
        inflection, rate = pack_pitch(word)
        events = _startup(4, 160) + [(300, 4, 1, inflection), (300, 4, 2, rate)]
        audio, metadata = self.run_audio("hot-pitch", events)
        self.assertEqual(metadata["starts"], [1, 0])
        self.assertIn(str(round(20000 / 160)), metadata["pitch_period_histograms"][0])
        self.assertIn(str(round(20000 / achieved)), metadata["pitch_period_histograms"][0])
        before = _periodic_pitch(audio[7200:13200, 0], 160)
        after = _periodic_pitch(audio[21600:27600, 0], achieved)
        self.assertAlmostEqual(before, 160, delta=3)
        self.assertAlmostEqual(after, achieved, delta=4)
        self.assertGreater(after / before, 1.3)

    def test_live_ff_changes_spectrum_preserving_source_pitch(self):
        events = _startup(4, 160) + _startup(5, 160)
        # Only the left tract changes. Both wrappers retain identical pitch.
        events += [(300, 4, 4, 255)]
        audio, metadata = self.run_audio("hot-ff", events)
        self.assertEqual(metadata["starts"], [1, 1])
        self.assertEqual(metadata["pitch_period_histograms"][0],
                         metadata["pitch_period_histograms"][1])
        left, right = audio[21600:27600].T
        self.assertGreater(np.mean((left - right) ** 2), 100)
        self.assertAlmostEqual(_periodic_pitch(left, 160),
                               _periodic_pitch(right, 160), delta=2)
        # Gain-normalized magnitude distributions detect timbre rather than
        # merely a louder output after the filter-frequency write.
        spectra = np.abs(np.fft.rfft(np.stack([left, right]) * np.hanning(len(left))))
        spectra /= np.maximum(spectra.sum(axis=1, keepdims=True), 1)
        self.assertGreater(np.abs(spectra[0] - spectra[1]).sum(), 0.05)

    def test_bank_resets_make_repeated_templates_pcm_identical(self):
        segment_ticks = 137  # Avoid an integer number of glottal periods.
        first = _startup(4, 160, 96) + _startup(5, 220, 160)
        middle = _startup(4, 183, 255) + _startup(5, 95, 0)
        # Include a different phoneme between the two identical templates.
        middle = [(tick, target, reg, 0xB2 if reg == 0 else value)
                  for tick, target, reg, value in middle]
        events = [(offset * segment_ticks + tick, target, reg, value)
                  for offset, sequence in enumerate((first, middle, first))
                  for tick, target, reg, value in sequence]
        output = self.folder / "isolated-templates.wav"
        metadata = render(events, 1000, segment_ticks * 3, self.firmware,
                          output, self.cache,
                          reset_ticks=(segment_ticks, 2 * segment_ticks))
        audio = _read_audio(output)
        count = segment_ticks * SAMPLE_RATE // 1000
        self.assertEqual(len(audio), 3 * count)
        self.assertGreater(np.max(np.abs(audio[:count])), 100)
        np.testing.assert_array_equal(audio[:count], audio[2 * count:])
        self.assertEqual(metadata["bank_resets"], 2)
        self.assertEqual(metadata["starts"], [3, 3])


if __name__ == "__main__":
    unittest.main()
