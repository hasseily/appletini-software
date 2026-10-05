"""Search correctness, consonant preservation, and score invariants."""

import copy
import itertools
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from phasor.compare import SAMPLE_RATE, acoustic_features
from phasor.fit import _bank_events, _expand_frames, _load_bank, _sparsify_frames, _viterbi, fit_score


class SearchTests(unittest.TestCase):
    def test_viterbi_matches_exhaustive_search(self):
        generator = np.random.default_rng(7)
        for _ in range(20):
            costs = generator.uniform(0, 2, (5, 3))
            penalties = generator.uniform(0, .8, 5)
            path = _viterbi(costs, penalties)

            def objective(sequence):
                return (sum(costs[t, value] for t, value in enumerate(sequence))
                        + sum(penalties[t] * (sequence[t] != sequence[t - 1])
                              for t in range(1, len(sequence))))

            exhaustive = min(objective(sequence) for sequence in itertools.product(range(3), repeat=5))
            self.assertAlmostEqual(objective(path), exhaustive)

    def test_one_frame_consonant_survives_large_acoustic_evidence(self):
        cost = np.array([[0, 2], [0, 2], [3, 0], [0, 2], [0, 2]])
        self.assertEqual(_viterbi(cost, .2).tolist(), [0, 0, 1, 0, 0])

    def test_locked_state_changes_remain_possible(self):
        self.assertEqual(_viterbi(np.array([[0, np.inf], [np.inf, 0]]), .2).tolist(), [0, 1])
        with self.assertRaises(ValueError):
            _viterbi(np.array([[np.inf, np.inf]]))

    def test_held_states_are_sampled_without_repeating_retrigger_or_lyrics(self):
        frames = [{"tick": 0, "phoneme": 7, "pitch_hz": 160., "amplitude": 12,
                   "retrigger": True, "lyric": "held"},
                  {"tick": 20, "phoneme": 0, "pitch_hz": 160., "amplitude": 0}]
        expanded = _expand_frames(copy.deepcopy(frames), 40, 100)
        self.assertEqual([frame["tick"] for frame in expanded], list(range(21)))
        self.assertNotIn("retrigger", expanded[1])
        self.assertNotIn("lyric", expanded[1])
        self.assertEqual(_sparsify_frames(expanded, {0, 20}), frames)

    def test_bank_has_fresh_phone_attacks_and_final_mute(self):
        events, labels, duration, _ = _bank_events(160, (96, 128))
        self.assertEqual(len(labels), 126)
        self.assertEqual(set(labels[:, 0]), set(range(1, 64)))
        for index, (phone, tract_filter) in enumerate(labels):
            segment = [event for event in events if event[0] == index * 22]
            self.assertEqual(segment[0][1:], (4, 3, 0x80))
            self.assertIn((index * 22, 4, 4, tract_filter), segment)
            self.assertIn((index * 22, 4, 0, phone), segment)
            self.assertEqual(segment[-1][1:], (4, 3, 0x5F))
        self.assertEqual(events[-1], (duration, 4, 3, 0x80))

    def test_bank_is_cached_by_firmware_and_resets_each_template(self):
        t = np.arange(63 * 22 * (SAMPLE_RATE // 100)) / SAMPLE_RATE
        samples = .15 * np.sin(2 * np.pi * 160 * t)
        with tempfile.TemporaryDirectory() as directory, \
                patch("phasor.rtl.source_fingerprint", return_value="firmware-a") as fingerprint, \
                patch("phasor.rtl.render", return_value={"test_fixture": True}) as render, \
                patch("phasor.fit.load_audio", return_value=samples):
            bank, first = _load_bank(Path("firmware"), Path(directory), 160., (128,))
            reused, second = _load_bank(Path("firmware"), Path(directory), 160., (128,))
            self.assertFalse(first["cache_hit"])
            self.assertTrue(second["cache_hit"])
            self.assertEqual(render.call_count, 1)
            np.testing.assert_array_equal(bank["spectra"], reused["spectra"])
            self.assertEqual(list(render.call_args.kwargs["reset_ticks"]), list(range(0, 63 * 22, 22)))
            fingerprint.return_value = "firmware-b"
            _, changed = _load_bank(Path("firmware"), Path(directory), 160., (128,))
            self.assertNotEqual(first["key"], changed["key"])
            self.assertEqual(render.call_count, 2)


class ScoreFitTests(unittest.TestCase):
    def setUp(self):
        t = np.arange(SAMPLE_RATE // 2) / SAMPLE_RATE
        self.samples = .2 * np.sin(2 * np.pi * 160 * t)
        features = acoustic_features(self.samples)
        descriptor = features.spectrum_db[10]
        self.bank = {
            "labels": np.array([[7, 128], [7, 96], [9, 128]]),
            "spectra": np.array([[descriptor + 20] * 2,
                                 [descriptor + 5] * 2,
                                 [descriptor] * 2]),
            "voiced": np.ones((3, 2)),
        }
        self.score = {
            "version": 1, "title": "fixture", "tick_hz": 100, "duration_ticks": 50,
            "voices": [{"chip": 0, "frames": [
                {"tick": 10, "phoneme": 7, "pitch_hz": 160., "amplitude": 12,
                 "filter": 128, "articulation": 6, "lyric": "hello"},
                {"tick": 11, "phoneme": 7, "pitch_hz": 162., "amplitude": 10,
                 "filter": 128, "articulation": 4},
                {"tick": 20, "phoneme": 0, "pitch_hz": 162., "amplitude": 0},
            ]}],
            "notes": [{"start_tick": 0, "end_tick": 25, "midi": 60, "velocity": 8, "voice": 0}],
            "analysis": {"annotations": "provided"},
        }

    def run_fit(self, **kwargs):
        with tempfile.TemporaryDirectory() as cache, \
                patch("phasor.fit.firmware_info", return_value={"verified": True}), \
                patch("phasor.fit.load_audio", return_value=self.samples), \
                patch("phasor.fit._load_bank", return_value=(self.bank, {"key": "fixture"})):
            return fit_score(self.score, Path("vocals.wav"), Path("firmware"), Path(cache), **kwargs)

    def test_fit_changes_phones_preserves_contours_notes_and_annotations(self):
        original = copy.deepcopy(self.score)
        result, report = self.run_fit()
        self.assertEqual(self.score, original)
        self.assertEqual(result["notes"], original["notes"])
        self.assertEqual(result["analysis"]["annotations"], "provided")
        self.assertEqual(report["changed_frames"], 10)
        result_frames = {frame["tick"]: frame for frame in result["voices"][0]["frames"]}
        for before in original["voices"][0]["frames"]:
            after = result_frames[before["tick"]]
            for key in before.keys() - {"phoneme", "filter"}:
                self.assertEqual(before[key], after[key])
        self.assertEqual(result["voices"][0]["frames"][0]["phoneme"], 9)
        self.assertEqual(result["voices"][0]["frames"][-1], original["voices"][0]["frames"][-1])
        self.assertLess(report["dictionary_loss_after"], report["dictionary_loss_before"])

    def test_locked_phone_retains_words_while_filter_can_change(self):
        result, report = self.run_fit(locked_phonemes=True)
        self.assertTrue(report["locked_phonemes"])
        frame = result["voices"][0]["frames"][0]
        self.assertEqual(frame["phoneme"], 7)
        self.assertEqual(frame["filter"], 96)

    def test_held_vowel_body_can_change_without_a_preexisting_control_event(self):
        t = np.arange(SAMPLE_RATE // 2) / SAMPLE_RATE
        body = (.05 * np.sin(2 * np.pi * 160 * t)
                + .15 * np.sin(2 * np.pi * 480 * t)
                + .10 * np.sin(2 * np.pi * 800 * t))
        self.samples[int(.2 * SAMPLE_RATE):] = body[int(.2 * SAMPLE_RATE):]
        features = acoustic_features(self.samples)
        self.bank = {
            "labels": np.array([[7, 128], [9, 128]]),
            "spectra": np.array([[features.spectrum_db[10]] * 2,
                                 [features.spectrum_db[30]] * 2]),
            "voiced": np.ones((2, 2)),
        }
        self.score["voices"][0]["frames"] = [
            {"tick": 0, "phoneme": 7, "pitch_hz": 160., "amplitude": 12},
            {"tick": 50, "phoneme": 0, "pitch_hz": 160., "amplitude": 0},
        ]
        result, report = self.run_fit()
        frames = result["voices"][0]["frames"]
        at = lambda tick: next(frame for frame in reversed(frames) if frame["tick"] <= tick)
        self.assertEqual(at(10)["phoneme"], 7)
        self.assertEqual(at(30)["phoneme"], 9)
        self.assertGreater(report["fitted_frames"], 40)
        self.assertTrue(any(0 < frame["tick"] < 50 for frame in frames))

    def test_missing_locked_template_is_preserved_and_reported(self):
        self.score["voices"][0]["frames"][0]["phoneme"] = 63
        result, report = self.run_fit(locked_phonemes=True)
        self.assertEqual(result["voices"][0]["frames"][0]["phoneme"], 63)
        self.assertEqual(report["locked_frames_without_template"], 1)

    def test_short_stem_is_rejected_instead_of_shifting_annotations(self):
        self.samples = self.samples[:SAMPLE_RATE // 4]
        with self.assertRaisesRegex(ValueError, "shorter"):
            self.run_fit()

    def test_empty_voice_needs_no_model_bank(self):
        self.score["voices"] = []
        result, report = self.run_fit()
        self.assertEqual(report["fitted_frames"], 0)
        self.assertEqual(result, self.score)

    def test_two_voices_are_not_fitted_to_the_same_stem(self):
        second = copy.deepcopy(self.score["voices"][0])
        second["chip"] = 1
        self.score["voices"].append(second)
        with self.assertRaisesRegex(ValueError, "two independent"):
            self.run_fit()

    def test_cache_cannot_bypass_firmware_verification(self):
        with patch("phasor.fit.firmware_info", return_value={"verified": False}), \
                patch("phasor.fit._load_bank") as bank:
            with self.assertRaisesRegex(ValueError, "pinned F1.2.4"):
                fit_score(self.score, Path("vocals.wav"), Path("firmware"), Path("cache"))
            bank.assert_not_called()


if __name__ == "__main__":
    unittest.main()
