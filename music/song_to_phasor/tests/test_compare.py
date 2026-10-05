"""Measurements must expose the audible failures a fitter could otherwise hide."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

from phasor.compare import SAMPLE_RATE, acoustic_features, compare_audio, compare_samples, select_fit


def vocal(hz=220., seconds=1.2):
    t = np.arange(round(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    envelope = .25 + .12 * np.sin(2 * np.pi * 2.7 * t)
    return envelope * (np.sin(2 * np.pi * hz * t)
                       + .25 * np.sin(2 * np.pi * 2 * hz * t))


class ComparisonTests(unittest.TestCase):
    def test_identity_and_file_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voice.wav"
            wavfile.write(path, SAMPLE_RATE, vocal().astype(np.float32))
            result = compare_audio(path, path)
        self.assertEqual(result["pitch"]["mean_absolute_cents"], 0)
        self.assertEqual(result["voicing"]["recall"], 1)
        self.assertEqual(result["spectrum"]["envelope_rmse_db"], 0)
        self.assertEqual(result["timing"]["candidate_delay_seconds"], 0)
        json.dumps(result, allow_nan=False)

    def test_detuning_measures_cents_not_waveform_phase(self):
        result = compare_samples(vocal(), vocal(220 * 2 ** (50 / 1200)))
        self.assertAlmostEqual(result["pitch"]["median_signed_cents"], 50, delta=2)
        self.assertGreater(result["voicing"]["recall"], .95)

    def test_octave_errors_are_not_folded_away(self):
        result = compare_samples(vocal(), vocal(440))
        self.assertAlmostEqual(result["pitch"]["median_absolute_cents"], 1200, delta=3)

    def test_low_and_high_singing_pitches(self):
        for hz in (55, 65, 110, 880, 1100):
            with self.subTest(hz=hz):
                result = acoustic_features(vocal(hz))
                median = np.median(result.f0[result.voiced])
                self.assertLess(abs(1200 * np.log2(median / hz)), 5)
                self.assertGreater(result.voiced.mean(), .9)

    def test_mute_cannot_win_pitch_or_spectral_score(self):
        result = compare_samples(vocal(), np.zeros_like(vocal()))
        self.assertIsNone(result["pitch"]["mean_absolute_cents"])
        self.assertIsNone(result["spectrum"]["envelope_rmse_db"])
        self.assertEqual(result["voicing"]["recall"], 0)
        self.assertEqual(result["spectrum"]["reference_active_coverage"], 0)
        self.assertGreater(result["loudness"]["rmse_db"], 50)
        json.dumps(result, allow_nan=False)

    def test_missing_audio_counts_against_coverage(self):
        reference = vocal(seconds=2)
        result = compare_samples(reference, reference[:SAMPLE_RATE], max_lag_seconds=0)
        self.assertAlmostEqual(result["voicing"]["recall"], .5, delta=.02)
        self.assertLess(result["spectrum"]["reference_active_coverage"], .53)

    def test_extra_audio_counts_against_precision(self):
        result = compare_samples(vocal(seconds=1), vocal(seconds=2), max_lag_seconds=0)
        self.assertAlmostEqual(result["voicing"]["precision"], .5, delta=.02)

    def test_known_delay_and_alignment_bound(self):
        reference = vocal(seconds=2)
        late = np.pad(reference, (round(.13 * SAMPLE_RATE), 0))
        result = compare_samples(reference, late)
        self.assertAlmostEqual(result["timing"]["candidate_delay_seconds"], .13, delta=.011)
        self.assertLess(result["pitch"]["median_absolute_cents"], 1)
        bounded = compare_samples(reference, late, max_lag_seconds=.04)
        self.assertLessEqual(abs(bounded["timing"]["candidate_delay_seconds"]), .04)

    def test_gain_changes_loudness_but_not_spectral_shape(self):
        reference = vocal()
        result = compare_samples(reference, reference / 2)
        self.assertAlmostEqual(result["loudness"]["mean_signed_db"], -6.0206, places=3)
        self.assertGreater(result["loudness"]["envelope_correlation"], .999)
        self.assertLess(result["spectrum"]["envelope_rmse_db"], 1e-8)

    def test_noise_is_not_a_voiced_pitch_match(self):
        noise = np.random.default_rng(42).normal(0, .15, SAMPLE_RATE)
        result = compare_samples(vocal(seconds=1), noise)
        self.assertLess(result["voicing"]["recall"], .05)
        self.assertGreater(result["spectrum"]["envelope_rmse_db"], 5)

    def test_silence_and_invalid_input_are_explicit(self):
        result = compare_samples(np.zeros(1600), np.zeros(1600))
        self.assertIsNone(result["voicing"]["recall"])
        self.assertIsNone(result["loudness"]["envelope_correlation"])
        json.dumps(result, allow_nan=False)
        for invalid in (np.array([]), np.array([np.nan]), np.zeros((2, 2))):
            with self.assertRaises(ValueError):
                acoustic_features(invalid)


class FitSelectionTests(unittest.TestCase):
    def setUp(self):
        self.baseline = {
            "spectrum": {"envelope_rmse_db": 6.73099, "reference_active_coverage": .98},
            "voicing": {"recall": .9464},
            "pitch": {"mean_absolute_cents": 4.086},
            "timing": {"candidate_delay_seconds": .01},
        }
        self.candidate = copy.deepcopy(self.baseline)
        self.candidate["spectrum"]["envelope_rmse_db"] = 6.5

    def test_lower_proxy_cannot_override_worse_rendered_spectrum(self):
        self.baseline["dictionary_loss"] = .57125
        self.candidate["dictionary_loss"] = .56986
        self.candidate["spectrum"]["envelope_rmse_db"] = 6.73689
        self.candidate["pitch"]["mean_absolute_cents"] = 3.977
        selection = select_fit(self.baseline, self.candidate)
        self.assertEqual(selection["selected"], "baseline")
        self.assertAlmostEqual(selection["spectral_improvement_db"], -.0059)
        self.assertIn("below", selection["reasons"][0])

    def test_material_improvement_with_good_coverage_is_selected(self):
        original = copy.deepcopy(self.baseline)
        selection = select_fit(self.baseline, self.candidate)
        self.assertEqual(selection["selected"], "candidate")
        self.assertAlmostEqual(selection["spectral_improvement_db"], .23099)
        self.assertEqual(original, self.baseline)
        json.dumps(selection, allow_nan=False)

    def test_identical_or_tiny_improvement_keeps_baseline(self):
        for improvement in (0, .049):
            self.candidate["spectrum"]["envelope_rmse_db"] = 6.73099 - improvement
            self.assertEqual(select_fit(self.baseline, self.candidate)["selected"], "baseline")

    def test_guards_accept_exact_thresholds(self):
        self.candidate["spectrum"]["envelope_rmse_db"] = 6.73099 - .05
        self.candidate["spectrum"]["reference_active_coverage"] = .97
        self.candidate["voicing"]["recall"] = .9364
        self.candidate["pitch"]["mean_absolute_cents"] = 9.086
        self.candidate["timing"]["candidate_delay_seconds"] = -.03
        self.assertEqual(select_fit(self.baseline, self.candidate)["selected"], "candidate")

    def test_each_guard_rejects_regressions_even_when_spectrum_improves(self):
        changes = (
            ("voicing", "recall", .92, "Voicing"),
            ("spectrum", "reference_active_coverage", .96, "coverage"),
            ("pitch", "mean_absolute_cents", 9.1, "pitch"),
            ("timing", "candidate_delay_seconds", -.031, "delay"),
        )
        for section, metric, value, reason in changes:
            with self.subTest(metric=metric):
                candidate = copy.deepcopy(self.candidate)
                candidate[section][metric] = value
                result = select_fit(self.baseline, candidate)
                self.assertEqual(result["selected"], "baseline")
                self.assertTrue(any(reason in item for item in result["reasons"]))

    def test_missing_null_and_nonfinite_evidence_cannot_select_candidate(self):
        metrics = (("spectrum", "envelope_rmse_db"), ("spectrum", "reference_active_coverage"),
                   ("voicing", "recall"), ("pitch", "mean_absolute_cents"),
                   ("timing", "candidate_delay_seconds"))
        for section, metric in metrics:
            for invalid in (None, float("nan"), float("inf"), True, "0.1"):
                with self.subTest(metric=metric, invalid=invalid):
                    candidate = copy.deepcopy(self.candidate)
                    candidate[section][metric] = invalid
                    result = select_fit(self.baseline, candidate)
                    self.assertEqual(result["selected"], "baseline")
                    json.dumps(result, allow_nan=False)
            candidate = copy.deepcopy(self.candidate)
            del candidate[section][metric]
            self.assertEqual(select_fit(self.baseline, candidate)["selected"], "baseline")
        self.assertEqual(select_fit({}, self.candidate)["selected"], "baseline")

    def test_silent_or_muted_audio_retains_baseline(self):
        source = vocal(seconds=.2)
        silent = np.zeros_like(source)
        baseline = compare_samples(source, source)
        muted = compare_samples(source, silent)
        self.assertEqual(select_fit(baseline, muted)["selected"], "baseline")
        no_voice = compare_samples(silent, silent)
        self.assertEqual(select_fit(no_voice, no_voice)["selected"], "baseline")


if __name__ == "__main__":
    unittest.main()
