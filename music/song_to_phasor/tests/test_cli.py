"""A measured selection must select the same score, bytes and audible output."""

import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phasor.cli import main
from phasor.compiler import compile_score
from phasor.stream import decode, encode


def metrics(spectrum):
    return {"spectrum": {"envelope_rmse_db": spectrum, "reference_active_coverage": .98},
            "pitch": {"mean_absolute_cents": 4.0}, "voicing": {"recall": .96},
            "timing": {"candidate_delay_seconds": 0.0}}


class SelectionIntegrationTests(unittest.TestCase):
    def test_full_render_uses_regional_clocks_and_requested_stems(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stream = root / "song.phs"
            stream.write_bytes(encode([], 100, 20))
            output, vocals, backing = (root / name for name in ("mix.wav", "vocal.wav", "ay.wav"))
            with (patch("phasor.full_render.render_full", return_value={"model": "full"}) as render,
                  contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
                self.assertEqual(main(["render", str(stream), str(output), "--full", "--clock", "pal",
                                       "--vocal-output", str(vocals), "--backing-output", str(backing)]), 0)
            self.assertEqual(render.call_args.kwargs["xck_hz"], 2_031_250)
            self.assertEqual(render.call_args.kwargs["ay_clock_hz"], 2_031_250)
            self.assertEqual(render.call_args.kwargs["vocal_output"], vocals)
            self.assertEqual(render.call_args.kwargs["backing_output"], backing)
            self.assertEqual(json.loads(output.with_suffix(".render.json").read_text()), {"model": "full"})

    def test_selected_score_stream_and_wave_agree_for_acceptance_and_rejection(self):
        original = {"version": 1, "tick_hz": 100, "duration_ticks": 20, "notes": [],
                    "voices": [{"chip": 0, "frames": [
                        {"tick": 0, "phoneme": 14, "pitch_hz": 200.0, "amplitude": 12}
                    ]}]}
        candidate = copy.deepcopy(original)
        candidate["voices"][0]["frames"][0]["filter"] = 160

        def fake_render(events, tick_hz, duration_ticks, firmware_root, output, cache, **kwargs):
            fitted = any(target == 4 and register == 4 and value == 160
                         for _, target, register, value in events)
            Path(output).write_bytes(b"candidate" if fitted else b"baseline")
            return {"output": str(output)}

        for candidate_distance, selected in ((6.74, "baseline"), (5.0, "candidate")):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as temporary:
                out = Path(temporary) / "result"
                with (patch("phasor.audio.analyze_audio", return_value=original),
                      patch("phasor.fit.fit_score", return_value=(candidate, {})),
                      patch("phasor.cli.checked_firmware", return_value={"verified": True}),
                      patch("phasor.rtl.render", side_effect=fake_render),
                      patch("phasor.compare.compare_audio", side_effect=[metrics(candidate_distance), metrics(6.73)]),
                      contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
                    self.assertEqual(main(["convert", "song.wav", "--vocals", "vocals.wav", "--fit", "--listen",
                                           "--out", str(out), "--firmware-root", temporary,
                                           "--profile", "appletini-f1.2.4"]), 0)
                expected = candidate if selected == "candidate" else original
                self.assertEqual(json.loads((out / "score.json").read_text()), expected)
                self.assertEqual(json.loads((out / "candidate.score.json").read_text()), candidate)
                self.assertEqual(decode((out / "song.phs").read_bytes())[0], compile_score(expected, profile="appletini-f1.2.4")[0])
                self.assertEqual((out / "vocals.rtl.wav").read_bytes(), selected.encode())
                report = json.loads((out / "report.json").read_text())
                self.assertEqual(report["fit_selection"]["selected"], selected)


if __name__ == "__main__":
    unittest.main()
