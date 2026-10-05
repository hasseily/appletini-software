"""Vocal contour, mode-side-effect and chronological write regressions."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phasor.cli import compile_files
from phasor.compiler import compile_score
from phasor.hardware import ssi_initialize
from phasor.score import validate_score


def frame(tick, **changes):
    result = {"tick": tick, "phoneme": 14, "pitch_hz": 220.0, "amplitude": 12}
    result.update(changes)
    return result


def score(frames=None, notes=None, duration=100):
    result = {"version": 1, "tick_hz": 100, "duration_ticks": duration,
              "voices": [], "notes": [] if notes is None else notes}
    if frames is not None:
        result["voices"] = [{"chip": 0, "frames": frames}]
    return result


def note(start, end, midi=60, voice=0, velocity=10):
    return {"start_tick": start, "end_tick": end, "midi": midi,
            "voice": voice, "velocity": velocity}


def drum(start, end, kind="snare", velocity=12):
    return {"start_tick": start, "end_tick": end, "kind": kind, "velocity": velocity}


class CompilerTests(unittest.TestCase):
    def test_initialization_preserves_every_ctl_edge(self):
        events, _ = compile_score(score([frame(0)]))
        for target in (4, 5):
            writes = [(chip, register, value) for _, chip, register, value in events
                      if chip == target]
            expected = ssi_initialize(target - 4)
            self.assertEqual(writes[:len(expected)], expected)

    def test_sustained_singing_changes_pitch_and_filter_without_phone_restart(self):
        events, _ = compile_score(score([
            frame(0), frame(10, pitch_hz=233.082),
            frame(20, pitch_hz=246.942, filter=160),
            frame(30, pitch_hz=220, amplitude=10),
        ]))
        for target in (4, 5):
            live = [event for event in events if event[1] == target and 0 < event[0] < 100]
            self.assertFalse(any(event[2] == 0 for event in live))
            self.assertTrue(any(event[2] == 1 for event in live))
            self.assertIn((20, target, 4, 160), live)
            self.assertIn((30, target, 3, 0x5A), live)

    def test_same_phone_can_retrigger_on_a_new_syllable(self):
        events, _ = compile_score(score([frame(0), frame(10, retrigger=True), frame(20)]))
        self.assertEqual([event for event in events if event[0] == 10 and event[2] == 0],
                         [(10, 4, 0, 14), (10, 5, 0, 14)])
        self.assertFalse(any(event[0] == 20 and event[2] == 0 for event in events))

    def test_resume_after_silence_restarts_phone_with_new_pitch_first(self):
        events, _ = compile_score(score([
            frame(0), frame(10, amplitude=0), frame(20, pitch_hz=440)
        ]), center_voice=False)
        resumed = [event for event in events if event[0] == 20 and event[1] == 4]
        registers = [event[2] for event in resumed]
        self.assertIn(0, registers)
        self.assertLess(registers.index(1), registers.index(0))
        self.assertLess(registers.index(0), registers.index(3))

    def test_two_tracks_never_mirror_over_each_other(self):
        source = score([frame(0)])
        source["voices"].append({"chip": 1, "frames": [frame(10, phoneme=1)]})
        events, report = compile_score(source)
        self.assertFalse(report["centered_voice"])
        self.assertTrue(any(event == (10, 5, 0, 1) for event in events))
        self.assertFalse(any(event[0] == 10 and event[1] == 4 for event in events))

    def test_note_shadows_follow_time_even_if_input_notes_are_unsorted(self):
        events, _ = compile_score(score(notes=[note(20, 30, 62), note(0, 10, 60)]))
        amplitudes = [event for event in events if event[1:3] == (0, 8)]
        self.assertEqual(amplitudes, [(0, 0, 8, 0), (0, 0, 8, 10),
                                      (10, 0, 8, 0), (20, 0, 8, 10), (30, 0, 8, 0)])

    def test_adjacent_notes_release_before_attack_on_same_tick(self):
        events, _ = compile_score(score(notes=[note(0, 10), note(10, 20)]))
        amplitudes = [event[3] for event in events if event[:3] == (10, 0, 8)]
        self.assertEqual(amplitudes, [0, 10])

    def test_terminal_state_powers_down_both_ssis_and_silences_every_ay(self):
        source = score([frame(0)], [note(0, 100, voice=voice) for voice in range(12)])
        events, report = compile_score(source)
        shadow = {(target, register): value for _, target, register, value in events}
        for target in range(4):
            self.assertEqual([shadow[target, register] for register in (8, 9, 10)], [0, 0, 0])
        self.assertEqual([shadow[target, 3] for target in (4, 5)], [0x80, 0x80])
        self.assertLessEqual(report["peak_writes_per_tick"], 255)
        self.assertEqual(events, sorted(events, key=lambda event: event[0]))

    def test_firmware_mismatch_writes_no_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "result"
            with patch("phasor.cli.checked_firmware", side_effect=ValueError("mismatch")):
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    compile_files(score([frame(0)]), out, "ntsc", firmware=Path("unused"))
            self.assertFalse(out.exists())

    def test_percussion_uses_shared_fixed_noise_and_separate_volume_gates(self):
        source = score()
        source["percussion"] = [drum(10, 40), drum(15, 20, "hat"), drum(10, 30, "kick")]
        events, report = compile_score(source)
        self.assertEqual(report["percussion_hits"], 3)
        self.assertIn((0, 3, 6, 8), events)
        self.assertIn((0, 3, 7, 0x0E), events)
        # Hat attacks/releases neither retune the shared source nor silence B.
        hat_edges = [event for event in events if event[0] in (15, 20) and event[1] == 3]
        self.assertTrue(any(event[2] == 10 for event in hat_edges))
        self.assertFalse(any(event[2] in (6, 7, 9) for event in hat_edges))
        final = {(chip, register): value for _, chip, register, value in events}
        self.assertEqual([final[3, register] for register in (8, 9, 10)], [0, 0, 0])
        self.assertEqual(final[3, 7], 0x38)

    def test_drum_shadows_follow_time_and_adjacent_hits_release_first(self):
        source = score(notes=[note(12, 26)])
        source["percussion"] = [drum(20, 30), drum(0, 20)]
        events, _ = compile_score(source)
        self.assertEqual(events, sorted(events, key=lambda event: event[0]))
        self.assertEqual([event[3] for event in events if event[:3] == (20, 3, 9)], [0, 12])
        self.assertIn((30, 3, 9, 0), events)
        self.assertIn((12, 0, 8, 10), events)

    def test_one_tick_kick_has_attack_and_silence_without_late_stages(self):
        source = score()
        source["percussion"] = [drum(10, 11, "kick")]
        events, _ = compile_score(source)
        live = [event for event in events if event[1:3] == (3, 8) and event[0] > 0]
        self.assertEqual(live, [(10, 3, 8, 12), (11, 3, 8, 0)])

    def test_kick_pitch_falls_using_regional_clock(self):
        source = score()
        source["percussion"] = [drum(10, 40, "kick")]
        events, _ = compile_score(source)
        low, high, periods = 0, 0, []
        for tick, chip, register, value in events:
            if chip == 3 and 10 <= tick < 40:
                if register == 0:
                    low = value
                elif register == 1:
                    high = value
                elif register == 8:
                    periods.append(low | high << 8)
        self.assertEqual(len(periods), 3)
        self.assertEqual(periods, sorted(periods))
        self.assertGreater(periods[-1], periods[0])
        pal, _ = compile_score(source, clock="pal")
        self.assertNotEqual([e for e in events if e[1] == 3 and e[2] < 2],
                            [e for e in pal if e[1] == 3 and e[2] < 2])


class ScoreValidationTests(unittest.TestCase):
    def test_note_overlap_rejected_per_voice_but_chords_allowed(self):
        validate_score(score(notes=[note(0, 20, voice=0), note(0, 20, voice=1)]))
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_score(score(notes=[note(0, 20), note(10, 30)]))

    def test_malformed_notes_fail_validation_before_sorting(self):
        for value in ("10", None, float("nan"), False):
            malformed = note(10, 20)
            malformed["start_tick"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_score(score(notes=[note(0, 5), malformed]))

    def test_nonfinite_pitch_midi_and_invalid_control_values_rejected(self):
        for bad in (float("inf"), float("nan"), -float("inf"), True):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                validate_score(score([frame(0, pitch_hz=bad)]))
            with self.subTest(value=bad), self.assertRaises(ValueError):
                validate_score(score(notes=[note(0, 10, midi=bad)]))
        for name, value in (("filter", 256), ("rate", 16), ("duration", 4),
                            ("phoneme", 64), ("amplitude", -1), ("retrigger", 1)):
            with self.subTest(control=name), self.assertRaises(ValueError):
                validate_score(score([frame(0, **{name: value})]))

    def test_terminal_vocal_frame_must_be_silent(self):
        validate_score(score([frame(100, amplitude=0)]))
        with self.assertRaisesRegex(ValueError, "terminal"):
            validate_score(score([frame(100)]))

    def test_percussion_rejects_invalid_fields_and_reserved_voice_conflicts(self):
        for field, value in (("kind", "cymbal"), ("kind", []), ("start_tick", -1),
                             ("end_tick", 101), ("end_tick", 10), ("velocity", 16)):
            source = score()
            source["percussion"] = [drum(10, 20)]
            source["percussion"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_score(source)
        for voice in (9, 10, 11):
            source = score(notes=[note(0, 10, voice=voice)])
            source["percussion"] = [drum(20, 30)]
            with self.subTest(voice=voice), self.assertRaisesRegex(ValueError, "reserves AY"):
                validate_score(source)

    def test_percussion_overlap_rejected_per_kind_but_different_drums_can_overlap(self):
        source = score()
        source["percussion"] = [drum(0, 20), drum(10, 30, "hat")]
        validate_score(source)
        source["percussion"][1]["kind"] = "snare"
        with self.assertRaisesRegex(ValueError, "overlapping percussion"):
            validate_score(source)


if __name__ == "__main__":
    unittest.main()
