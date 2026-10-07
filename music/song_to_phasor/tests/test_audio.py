"""Behavioral checks for the optional local DSP front end."""
import json
import math
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    from scipy.io import wavfile
    from phasor.audio import analyze_audio, load_audio, track_pitch
    HAS_AUDIO = True
except ImportError:
    HAS_AUDIO = False


@unittest.skipUnless(HAS_AUDIO, "optional audio analysis requires NumPy and SciPy")
class AudioTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def write_audio(self, name, samples, rate=16000):
        path = self.root / name
        wavfile.write(path, rate, np.asarray(samples, dtype=np.float32))
        return path

    @staticmethod
    def tone(frequency, seconds=1, rate=16000, amplitude=.45):
        return amplitude * np.sin(2 * np.pi * frequency * np.arange(round(seconds * rate)) / rate)

    @staticmethod
    def state_at(frames, tick):
        return max((frame for frame in frames if frame["tick"] <= tick), key=lambda frame: frame["tick"])

    def test_tracks_synthetic_fundamentals_and_transposition(self):
        for frequency in (65.406, 110.0, 220.0, 440.0, 880.0):
            with self.subTest(frequency=frequency):
                tracked = track_pitch(self.tone(frequency))
                pitch = float(np.median(tracked["pitch_hz"][10:-10]))
                self.assertLess(abs(1200 * math.log2(pitch / frequency)), 8)
                self.assertGreater(float(np.mean(tracked["confidence"][10:-10])), .95)
        path = self.write_audio("song.wav", self.tone(220))
        score = analyze_audio(path, transpose=12)
        frame = self.state_at(score["voices"][0]["frames"], 50)
        self.assertAlmostEqual(frame["pitch_hz"], 440, delta=3)
        self.assertTrue(any(note["midi"] == 69 for note in score["notes"]))
        self.assertIn("do not recognize words", score["analysis"]["quality_notes"][0])

    def test_harmonic_voice_uses_fundamental(self):
        samples = self.tone(160, amplitude=.20) + self.tone(320, amplitude=.45)
        samples += self.tone(480, amplitude=.20)
        tracked = track_pitch(samples)
        self.assertAlmostEqual(float(np.median(tracked["pitch_hz"][10:-10])), 160, delta=1)

    def test_silence_and_empty_audio_have_no_sound_or_nonfinite_values(self):
        for name, samples in (("silence.wav", np.zeros(8000)), ("empty.wav", np.zeros(0))):
            with self.subTest(name=name):
                score = analyze_audio(self.write_audio(name, samples))
                self.assertGreaterEqual(score["duration_ticks"], 1)
                self.assertEqual(score["notes"], [])
                self.assertTrue(all(frame["amplitude"] == 0 for frame in score["voices"][0]["frames"]))
                self.assertEqual(score["analysis"]["vocal"]["mean_voiced_confidence"], 0)
                json.dumps(score, allow_nan=False)

    def test_annotations_override_phone_and_silence_every_gap(self):
        song = self.write_audio("voice.wav", self.tone(220))
        annotations = self.root / "phones.json"
        annotations.write_text(json.dumps([
            {"start": .20, "end": .40, "phoneme": 0x01},
            {"start": .60, "end": .80, "phoneme": 0x13},
            {"start": .80, "end": .90, "phoneme": 0},
        ]))
        score = analyze_audio(song, annotations=annotations)
        frames = score["voices"][0]["frames"]
        for tick in range(100):
            frame = self.state_at(frames, tick)
            if 20 <= tick < 40:
                self.assertEqual(frame["phoneme"], 1)
                self.assertGreater(frame["amplitude"], 0)
            elif 60 <= tick < 80:
                self.assertEqual(frame["phoneme"], 0x13)
                self.assertGreater(frame["amplitude"], 0)
            else:
                self.assertEqual(frame["amplitude"], 0)
        self.assertEqual(frames[-1]["tick"], score["duration_ticks"])
        self.assertEqual(frames[-1]["amplitude"], 0)
        self.assertEqual(score["analysis"]["vocal"]["phoneme_source"], "annotations")

    def test_adjacent_same_phone_annotations_preserve_one_shot_retrigger(self):
        from phasor.compiler import compile_score

        song = self.write_audio("repeated.wav", self.tone(220))
        annotation = self.root / "repeated.json"
        annotation.write_text(json.dumps([
            {"start": .20, "end": .50, "phoneme": 0x28},
            {"start": .50, "end": .80, "phoneme": 0x28},
        ]))
        score = analyze_audio(song, annotations=annotation)
        frames = score["voices"][0]["frames"]
        triggers = [frame["tick"] for frame in frames if frame.get("retrigger")]
        self.assertEqual(triggers, [50])
        events, _ = compile_score(score)
        starts = [tick for tick, target, register, value in events
                  if target == 4 and register == 0 and (value & 63) == 0x28]
        self.assertEqual(starts, [20, 50])
        self.assertFalse(any(frame.get("retrigger") for frame in frames if frame["tick"] > 50))

    def test_invalid_annotation_times_phones_and_overlap_are_rejected(self):
        song = self.write_audio("voice.wav", self.tone(220, .1))
        invalid = [
            [{"start": -1, "end": 1, "phoneme": 1}],
            [{"start": 0, "end": 0, "phoneme": 1}],
            [{"start": 0, "end": float("nan"), "phoneme": 1}],
            [{"start": 0, "end": 1, "phoneme": 64}],
            [{"start": 0, "end": 1, "phoneme": True}],
            [{"start": 0, "end": 1, "phoneme": 1}, {"start": .5, "end": 2, "phoneme": 2}],
            {"start": 0, "end": 1, "phoneme": 1},
        ]
        for index, records in enumerate(invalid):
            with self.subTest(records=records):
                annotation = self.root / f"bad{index}.json"
                annotation.write_text(json.dumps(records))
                with self.assertRaises(ValueError):
                    analyze_audio(song, annotations=annotation)

    def test_accompaniment_tracks_chord_in_stable_nonoverlapping_slots(self):
        samples = self.tone(220, 2, amplitude=.3) + self.tone(329.6276, 2, amplitude=.2)
        accompaniment = self.write_audio("chord.wav", samples)
        silence = self.write_audio("silent-vocal.wav", np.zeros(32000))
        score = analyze_audio(accompaniment, vocals=silence, accompaniment=accompaniment)
        self.assertEqual({note["midi"] for note in score["notes"]}, {57.0, 64.0})
        self.assertEqual(len(score["notes"]), 2)
        for note in score["notes"]:
            self.assertEqual(note["start_tick"], 0)
            self.assertEqual(note["end_tick"], 200)
            self.assertIn(note["voice"], range(12))
            self.assertIn(note["velocity"], range(1, 16))
        self.assertEqual(len({note["voice"] for note in score["notes"]}), 2)
        self.assertTrue(all(frame["amplitude"] == 0 for frame in score["voices"][0]["frames"]))

    def test_accompaniment_suppresses_simple_harmonic_duplicates(self):
        samples = (self.tone(220, amplitude=.3) + self.tone(440, amplitude=.2)
                   + self.tone(660, amplitude=.1))
        score = analyze_audio(self.write_audio("harmonics.wav", samples))
        self.assertEqual({note["midi"] for note in score["notes"]}, {57.0})

    def test_repeated_note_changes_never_overlap_per_voice(self):
        samples = np.concatenate([self.tone(frequency, .25) for frequency in
                                  (220, 293.6648, 329.6276, 261.6256, 220)])
        score = analyze_audio(self.write_audio("changes.wav", samples))
        for voice in range(12):
            notes = sorted((note for note in score["notes"] if note["voice"] == voice),
                           key=lambda note: note["start_tick"])
            for previous, current in zip(notes, notes[1:]):
                self.assertLessEqual(previous["end_tick"], current["start_tick"])
        self.assertGreaterEqual(len(score["notes"]), 4)

    def test_decoder_downmixes_and_resamples(self):
        mono = self.tone(220, rate=48000)
        path = self.write_audio("stereo.wav", np.column_stack((mono, mono)), rate=48000)
        decoded = load_audio(path)
        self.assertEqual(decoded.shape, (16000,))
        self.assertAlmostEqual(float(np.sqrt(np.mean(decoded ** 2))), .45 / math.sqrt(2), delta=.01)
        tracked = track_pitch(decoded)
        self.assertAlmostEqual(float(np.median(tracked["pitch_hz"][10:-10])), 220, delta=1)
        self.assertEqual(len(load_audio(path, sample_rate=8000)), 8000)

    def test_analysis_is_deterministic_with_valid_bounds(self):
        path = self.write_audio("draft.wav", self.tone(220, .2))
        first = analyze_audio(path, tick_hz=60)
        second = analyze_audio(path, tick_hz=60)
        self.assertEqual(first, second)
        self.assertEqual(first["duration_ticks"], 12)
        frames = first["voices"][0]["frames"]
        self.assertEqual(sorted({frame["tick"] for frame in frames}), [frame["tick"] for frame in frames])
        for frame in frames:
            self.assertIn(frame["phoneme"], range(64))
            self.assertIn(frame["amplitude"], range(16))
            self.assertTrue(math.isfinite(frame["pitch_hz"]))
        for argument in ({"tick_hz": 0}, {"tick_hz": True}, {"transpose": 49}):
            with self.assertRaises(ValueError):
                analyze_audio(path, **argument)


if __name__ == "__main__":
    unittest.main()
