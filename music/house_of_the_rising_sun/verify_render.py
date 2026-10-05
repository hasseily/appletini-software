#!/usr/bin/env python3
"""Measure the rendered SSI stem against the written score, not a human singer.

Pitch checks use sustained vowel interiors on the score's unchanged timeline.
Unvoiced consonants are excluded, but unvoiced output during an expected vowel
counts against coverage. These checks cannot establish lyric intelligibility.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "song_to_phasor"))
from phasor.audio import load_audio
from phasor.compare import acoustic_features
from phasor.hardware import ssi_pitch
from phasor.score import validate_score


def audio_levels(path: Path) -> dict:
    rate, raw = wavfile.read(path)
    if raw.dtype != np.int16 or raw.ndim != 2 or raw.shape[1] != 2:
        raise ValueError(f"Expected stereo 16-bit render: {path}")
    samples = raw.astype(np.float64) / 32768
    tail = samples[-max(1, rate // 5):]
    return {
        "sample_rate": rate, "samples": len(samples),
        "duration_seconds": len(samples) / rate,
        "peak": float(np.abs(samples).max()),
        "rms_left": float(np.sqrt(np.mean(samples[:, 0] ** 2))),
        "rms_right": float(np.sqrt(np.mean(samples[:, 1] ** 2))),
        "samples_at_rails": int(((raw == -32768) | (raw == 32767)).sum()),
        "last_200ms_peak": float(np.abs(tail).max()),
        "channels_identical": bool(np.array_equal(raw[:, 0], raw[:, 1])),
    }


def verify(score: dict, vocal_path: Path, mix_path: Path | None = None) -> dict:
    validate_score(score)
    if len(score["voices"]) != 1:
        raise ValueError("This arrangement check expects one centered singer")
    hz, duration = score["tick_hz"], score["duration_ticks"]
    if hz != 100:
        raise ValueError("This arrangement check uses the 100 Hz acoustic comparison grid")
    frames = score["voices"][0]["frames"]
    expected = np.zeros(duration)
    phones = np.zeros(duration, dtype=int)
    audible = np.zeros(duration, dtype=bool)
    onsets = []
    previous = None
    for index, frame in enumerate(frames):
        start = frame["tick"]
        end = frames[index + 1]["tick"] if index + 1 < len(frames) else duration
        expected[start:end] = frame["pitch_hz"]
        phones[start:end] = frame["phoneme"]
        audible[start:end] = frame["amplitude"] > 0
        if (previous is None or frame.get("retrigger", False)
                or frame["phoneme"] != previous["phoneme"]
                or bool(frame["amplitude"]) != bool(previous["amplitude"])
                or abs(1200 * np.log2(frame["pitch_hz"] / previous["pitch_hz"])) > 80):
            onsets.append(start)
        previous = frame
    vowel = audible & (phones >= 1) & (phones <= 28)
    # A 64ms pitch window needs room either side of a phone transition. Allow
    # a further 40ms after a restart for the firmware's tract to settle.
    for tick in onsets:
        vowel[max(0, tick - round(.04 * hz)):min(duration, tick + round(.08 * hz))] = False
    # Use the comparison module's normalized autocorrelation peak selection.
    # YIN's first acceptable minimum can mistake a strong formant harmonic for
    # F0 in these SSI vowels. Search remains unconstrained by the written note.
    measured = acoustic_features(load_audio(vocal_path)).f0
    observed = np.zeros(duration)
    length = min(duration, len(measured))
    observed[:length] = measured[:length]
    detected = observed > 0
    both = vowel & detected
    expected_quantized = np.array([ssi_pitch(value)[1] if value > 0 else 0 for value in expected])
    error = np.abs(1200 * np.log2(observed[both] / expected[both]))
    model_error = np.abs(1200 * np.log2(observed[both] / expected_quantized[both]))
    summary = lambda values: {
        "median_absolute_cents": float(np.median(values)) if len(values) else None,
        "p90_absolute_cents": float(np.percentile(values, 90)) if len(values) else None,
        "mean_absolute_cents": float(np.mean(values)) if len(values) else None,
    }
    count = int(vowel.sum())
    result = {
        "reference": "Written score; no reference singer or source recording",
        "alignment": "Absolute score timeline; no time shifting or warping",
        "expected_duration_seconds": duration / hz,
        "vowel_pitch": {
            "estimator": "Normalized autocorrelation; unconstrained 55..1100 Hz search",
            "eligible_seconds": count / hz,
            "detected_seconds": int(both.sum()) / hz,
            "detected_coverage": float(both.sum() / count) if count else None,
            "against_score": summary(error),
            "against_quantized_firmware_pitch": summary(model_error),
        },
        "vocal_audio": audio_levels(vocal_path),
        "limitations": [
            "Pitch and coverage are measured only on sustained vowel interiors.",
            "No comparison against a human singer; no measured lyric intelligibility.",
            "Firmware simulation is not a recording of a physical Phasor card.",
        ],
    }
    if mix_path:
        result["mix_audio"] = audio_levels(mix_path)
    result["checks"] = {
        "has_vowel_output": bool(both.any()),
        "vowel_coverage_at_least_95_percent": bool(count and both.sum() / count >= .95),
        "vowel_median_pitch_error_under_20_cents": bool(len(error) and np.median(error) < 20),
        "vowel_p90_pitch_error_under_50_cents": bool(len(error) and np.percentile(error, 90) < 50),
        "vocal_duration_matches": abs(result["vocal_audio"]["duration_seconds"] - duration / hz) < .001,
        "vocal_has_no_rail_samples": result["vocal_audio"]["samples_at_rails"] == 0,
        "vocal_tail_released": result["vocal_audio"]["last_200ms_peak"] < .001,
    }
    if mix_path:
        result["checks"].update({
            "mix_duration_matches": abs(result["mix_audio"]["duration_seconds"] - duration / hz) < .001,
            "mix_has_no_rail_samples": result["mix_audio"]["samples_at_rails"] == 0,
        })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score", type=Path)
    parser.add_argument("vocals", type=Path)
    parser.add_argument("--mix", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(json.loads(args.score.read_text()), args.vocals, args.mix)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if all(result["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
