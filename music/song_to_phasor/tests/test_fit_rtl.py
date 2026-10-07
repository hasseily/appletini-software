"""Optional synthesis/inversion check: recover known tract tone from real RTL audio.

Set PHASOR_FIT_RTL=1 and PHASOR_FIRMWARE_ROOT to run. A fresh reference bank
takes minutes; PHASOR_RTL_CACHE allows reuse with the CLI's 200 Hz bank.
"""

import copy
import os
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(os.environ.get("PHASOR_FIT_RTL") == "1" and os.environ.get("PHASOR_FIRMWARE_ROOT"),
                     "Set PHASOR_FIT_RTL=1 and PHASOR_FIRMWARE_ROOT for the full model-fitting check")
class FirmwareFitTests(unittest.TestCase):
    def test_recovers_tract_shape_and_reduces_rendered_spectral_error(self):
        from phasor.compiler import compile_score
        from phasor.compare import compare_audio
        from phasor.fit import fit_score
        from phasor.rtl import render

        root = Path(os.environ["PHASOR_FIRMWARE_ROOT"])
        cache = Path(os.environ.get("PHASOR_RTL_CACHE", ".cache"))
        source = {"version": 1, "title": "Known RTL vowel", "tick_hz": 100,
                  "duration_ticks": 80, "voices": [{"chip": 0, "frames": [
                      {"tick": 0, "phoneme": 14, "pitch_hz": 200.0, "amplitude": 15, "filter": 96},
                      {"tick": 70, "phoneme": 0, "pitch_hz": 200.0, "amplitude": 0}
                  ]}], "notes": []}
        draft = copy.deepcopy(source)
        draft["voices"][0]["frames"][0]["filter"] = 128
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            reference = directory / "reference.wav"
            baseline = directory / "baseline.wav"
            candidate = directory / "candidate.wav"
            render(compile_score(source)[0], 100, 80, root, reference, cache)
            render(compile_score(draft)[0], 100, 80, root, baseline, cache)
            fitted, report = fit_score(draft, reference, root, cache,
                                      locked_phonemes=True, bank_pitch_hz=200.0)
            render(compile_score(fitted)[0], 100, 80, root, candidate, cache)
            before = compare_audio(reference, baseline)
            after = compare_audio(reference, candidate)
            self.assertGreater(report["changed_frames"], 0)
            self.assertTrue(any(frame.get("filter") == 96 for frame in fitted["voices"][0]["frames"]))
            self.assertLess(after["spectrum"]["envelope_rmse_db"], before["spectrum"]["envelope_rmse_db"] * .75)
            self.assertGreater(after["voicing"]["recall"], .9)
            self.assertLess(after["pitch"]["mean_absolute_cents"], 10)
            print("RTL fit spectral error (dB):", before["spectrum"]["envelope_rmse_db"],
                  "->", after["spectrum"]["envelope_rmse_db"])


if __name__ == "__main__":
    unittest.main()
