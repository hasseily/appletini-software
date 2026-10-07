"""Physical SSI equations, profile isolation and the published stream contract."""

import contextlib
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phasor.cli import compile_files, main
from phasor.compiler import compile_score
from phasor.hardware import physical_ssi_filter, physical_ssi_pitch, ssi_initialize
from phasor.stream import encode


def reference_score():
    return {
        "version": 1, "tick_hz": 100, "duration_ticks": 100,
        "voices": [{"chip": 0, "frames": [
            {"tick": 0, "phoneme": 14, "pitch_hz": 220., "amplitude": 12},
            {"tick": 10, "phoneme": 14, "pitch_hz": 233.082, "amplitude": 11, "filter": 160},
            {"tick": 25, "phoneme": 1, "pitch_hz": 261.626, "amplitude": 10,
             "duration": 2, "rate": 7, "articulation": 3},
            {"tick": 50, "phoneme": 1, "pitch_hz": 261.626, "amplitude": 0},
        ]}],
        "notes": [
            {"start_tick": 0, "end_tick": 40, "midi": 60, "voice": 0, "velocity": 10},
            {"start_tick": 40, "end_tick": 100, "midi": 62, "voice": 0, "velocity": 12},
        ],
        "percussion": [
            {"start_tick": 10, "end_tick": 30, "kind": "snare", "velocity": 12},
            {"start_tick": 10, "end_tick": 30, "kind": "kick", "velocity": 13},
        ],
    }


class PhysicalEquationTests(unittest.TestCase):
    def test_known_pal_pitch_register_and_clock_dependence(self):
        inflection, actual = physical_ssi_pitch(128.88642131979697, 1_015_625)
        self.assertEqual(inflection, 0xC27)
        self.assertAlmostEqual(actual, 128.88642131979697)
        self.assertEqual(physical_ssi_pitch(2 * actual, 2_031_250)[0], inflection)
        self.assertAlmostEqual(physical_ssi_pitch(2 * actual, 2_031_250)[1], 2 * actual)

    def test_physical_pitch_is_nearest_in_cents_and_clamps(self):
        clock = 1_015_625
        for hz in (30., 65.406, 110, 220, 261.626, 440, 880, 1760, 12000, 200000):
            inflection, actual = physical_ssi_pitch(hz, clock)
            self.assertEqual(actual, clock / (8 * (4096 - inflection)))
            nearest = min(abs(math.log2(clock / (8 * period)) - math.log2(hz))
                          for period in range(1, 4097))
            self.assertAlmostEqual(abs(math.log2(actual) - math.log2(hz)), nearest)
        self.assertEqual(physical_ssi_pitch(5e-324, clock), (0, clock / 32768))
        self.assertEqual(physical_ssi_pitch(1e300, clock), (4095, clock / 8))

    def test_physical_filter_maps_authored_neutral_to_twenty_kilohertz(self):
        # FF=128, used by the Appletini stream, is only 3967 Hz on real PAL
        # hardware. Neutral must choose FF=231 (20312.5 Hz), over 230 (19531.25).
        self.assertEqual(1_015_625 / (2 * (256 - 128)), 3967.28515625)
        self.assertEqual(1_015_625 / (2 * (256 - 230)), 19531.25)
        self.assertEqual(physical_ssi_filter(128, 1_015_625), (231, 20312.5))
        for authored in (0, 96, 116, 122, 128, 160, 255):
            ff, actual = physical_ssi_filter(authored, 1_015_625)
            desired = 20_000 * (128 + authored) / 256
            self.assertEqual(actual, 1_015_625 / (2 * (256 - ff)))
            nearest = min(abs(1_015_625 / (2 * period) - desired) for period in range(1, 257))
            self.assertEqual(abs(actual - desired), nearest)

    def test_invalid_effective_clock_rejected(self):
        for clock in (0, -1, True, float("nan"), float("inf"), None):
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                physical_ssi_pitch(220, clock)
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                physical_ssi_filter(128, clock)


class ProfileCompilationTests(unittest.TestCase):
    def test_f1_2_4_stream_bytes_remain_unchanged(self):
        # Digests captured from main da00433 before adding physical profiles,
        # when the F1.2.4 model was the only profile.
        digests = {"ntsc": "32031d3cbb738f5caf6bc74ab16a4a2664539bd31b296b52684336467ad22bb3",
                   "pal": "b5b19eb68767caae02e4965bd13c4de411ff8d708185d7af0cd136fe67d8008f"}
        score = reference_score()
        for clock, digest in digests.items():
            with self.subTest(clock=clock):
                events, _ = compile_score(score, clock, profile="appletini-f1.2.4")
                self.assertEqual(hashlib.sha256(encode(events, 100, 100)).hexdigest(), digest)

    def test_default_profile_is_physical(self):
        score = reference_score()
        for clock in ("ntsc", "pal"):
            with self.subTest(clock=clock):
                events, report = compile_score(score, clock)
                self.assertEqual(report["profile"], "physical-ssi263")
                self.assertEqual(compile_score(score, clock, profile="physical-ssi263")[0], events)

    def test_physical_changes_only_pitch_and_filter_registers(self):
        source = reference_score()
        model, _ = compile_score(source, "pal", profile="appletini-f1.2.4")
        physical, report = compile_score(source, "pal", profile="physical-ssi263")
        unchanged = lambda events: [event for event in events if event[1] < 4 or event[2] in (0, 3)]
        self.assertEqual(unchanged(physical), unchanged(model))
        self.assertEqual(report["ssi_effective_clock_hz"], 1_015_625)
        self.assertNotIn("target_firmware", report)
        self.assertNotIn("shortened_excitation_frames", report)
        self.assertFalse(report["physical_hardware_calibrated"])
        self.assertLess(report["max_pitch_error_cents"], 2)
        self.assertEqual(report["ssi_filter_register_range"][0], 231)
        for chip in (0, 1):
            writes = [(target, reg, value) for _, target, reg, value in physical if target == 4 + chip]
            initial = ssi_initialize(chip, filter_byte=231)
            self.assertEqual(writes[:len(initial)], initial)

    def test_override_only_changes_ssi_and_is_reported(self):
        source = reference_score()
        default, _ = compile_score(source, "pal", profile="physical-ssi263")
        overridden, report = compile_score(source, "pal", profile="physical-ssi263", ssi_effective_clock_hz=2_031_250)
        self.assertEqual([e for e in default if e[1] < 4], [e for e in overridden if e[1] < 4])
        self.assertNotEqual(default, overridden)
        self.assertEqual(report["ssi_effective_clock_hz"], 2_031_250)
        self.assertEqual(report["ssi_filter_register_range"][0], 205)
        with self.assertRaisesRegex(ValueError, "requires profile"):
            compile_score(source, profile="appletini-f1.2.4", ssi_effective_clock_hz=1_000_000)
        with self.assertRaisesRegex(ValueError, "profile must"):
            compile_score(source, profile="unknown")

    def test_physical_file_report_contains_no_firmware_verification(self):
        with tempfile.TemporaryDirectory() as temporary, patch("phasor.cli.checked_firmware") as checked:
            _, report = compile_files(reference_score(), temporary, "pal", firmware=Path("unused"),
                                      profile="physical-ssi263")
            checked.assert_not_called()
            self.assertNotIn("firmware", report)
            self.assertEqual(json.loads((Path(temporary) / "report.json").read_text()), report)


class ProfileCLITests(unittest.TestCase):
    def test_compile_cli_accepts_profile_and_effective_clock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, out = root / "input.json", root / "output"
            source.write_text(json.dumps(reference_score()))
            with contextlib.redirect_stdout(io.StringIO()):
                main(["compile", str(source), "--out", str(out), "--clock", "pal",
                      "--profile", "physical-ssi263", "--ssi-effective-clock-hz", "1000000"])
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(report["profile"], "physical-ssi263")
            self.assertEqual(report["ssi_effective_clock_hz"], 1_000_000)

    def test_convert_and_fit_reject_physical_rtl_before_work(self):
        commands = [
            ["fit", "missing.json", "missing.wav"],
            ["convert", "missing.wav", "--fit"],
            ["convert", "missing.wav", "--listen"],
        ]
        # physical-ssi263 is also the default, so omitting --profile must fail too.
        for command in commands:
            for profile in (["--profile", "physical-ssi263"], []):
                with (self.subTest(command=command, profile=profile),
                      tempfile.TemporaryDirectory() as temporary):
                    out = Path(temporary) / "output"
                    error = io.StringIO()
                    with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                        main(command + profile + ["--out", str(out)])
                    self.assertEqual(raised.exception.code, 2)
                    self.assertIn("F1.2.4 speech model", error.getvalue())
                    self.assertIn("--profile appletini-f1.2.4", error.getvalue())
                    self.assertFalse(out.exists())

    def test_convert_physical_passes_profile_without_firmware_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "output"
            with (patch("phasor.audio.analyze_audio", return_value=reference_score()),
                  patch("phasor.cli.checked_firmware") as checked,
                  contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
                main(["convert", "input.wav", "--out", str(out), "--clock", "pal",
                      "--profile", "physical-ssi263"])
            checked.assert_not_called()
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(report["profile"], "physical-ssi263")
            self.assertEqual(report["ssi_effective_clock_hz"], 1_015_625)
            self.assertNotIn("firmware", report)

    def test_render_rejects_physical_report_without_running_rtl(self):
        for extra in ([], ["--full"]):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                compile_files(reference_score(), root, "pal", profile="physical-ssi263")
                output = root / "mix.wav"
                error = io.StringIO()
                with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                    main(["render", str(root / "song.phs"), str(output)] + extra)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("Cannot render physical-ssi263", error.getvalue())
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
