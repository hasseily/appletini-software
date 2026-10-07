"""Acoustic measurements for a vocal stem and its rendered SSI approximation.

These measurements describe pitch, timing, energy, and spectral shape. They do
not measure lyric intelligibility or singer identity. Pitch error is always
reported together with voicing coverage so silence cannot earn a good score.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from pathlib import Path

import numpy as np
from scipy.fft import rfft, irfft
from scipy.signal import find_peaks


SAMPLE_RATE = 16000
HOP = 160
WINDOW = 640
ANALYSIS_VERSION = 1


@dataclass
class Features:
    rms: np.ndarray
    spectrum_db: np.ndarray
    f0: np.ndarray
    voiced: np.ndarray
    periodicity: np.ndarray
    active: np.ndarray


def _band_weights() -> np.ndarray:
    """Broad perceptual bands suppress individual harmonics, retaining formants."""
    mel = lambda hz: 2595 * np.log10(1 + hz / 700)
    hz = lambda value: 700 * (10 ** (value / 2595) - 1)
    edges = hz(np.linspace(mel(100), mel(7500), 26))
    frequencies = np.fft.rfftfreq(1024, 1 / SAMPLE_RATE)
    weights = np.maximum(0, np.minimum(
        (frequencies[None, :] - edges[:-2, None]) / np.diff(edges)[:-1, None],
        (edges[2:, None] - frequencies[None, :]) / np.diff(edges)[1:, None],
    ))
    return weights / np.maximum(weights.sum(axis=1, keepdims=True), 1e-12)


_BANDS = _band_weights()


def acoustic_features(samples: np.ndarray) -> Features:
    """Measure 16 kHz mono audio on a 10 ms grid, bounded to small FFT batches."""
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all():
        raise ValueError("Audio must be a nonempty, finite mono signal")
    count = (len(samples) + HOP - 1) // HOP
    padded = np.pad(samples, (WINDOW // 2, WINDOW // 2 + HOP))
    views = np.lib.stride_tricks.sliding_window_view(padded, WINDOW)[::HOP][:count]
    rms = np.empty(count)
    bands = np.empty((count, 24))
    f0 = np.zeros(count)
    periodicity = np.zeros(count)
    taper = np.hanning(WINDOW)
    # The mean-subtracted autocorrelation uses its own rectangular window;
    # overlap-energy normalization avoids a bias towards short pitch periods.
    low_lag, high_lag = int(SAMPLE_RATE / 1100) - 1, int(np.ceil(SAMPLE_RATE / 55)) + 1
    for offset in range(0, count, 256):
        frames = views[offset:offset + 256].copy()
        frames -= frames.mean(axis=1, keepdims=True)
        rms[offset:offset + len(frames)] = np.sqrt(np.mean(frames ** 2, axis=1))
        power = np.abs(rfft(frames * taper, n=1024, axis=1)) ** 2
        # Limit dynamic range relative to each frame. This avoids numerical
        # floors and recording gain dominating a spectral-shape comparison.
        band_power = power @ _BANDS.T
        floor = np.maximum(band_power.max(axis=1, keepdims=True) * 1e-6, 1e-20)
        spectrum = 10 * np.log10(np.maximum(band_power, floor))
        bands[offset:offset + len(frames)] = spectrum - spectrum.mean(axis=1, keepdims=True)
        acf = irfft(np.abs(rfft(frames, n=2048, axis=1)) ** 2, n=2048, axis=1)
        energy = np.concatenate((np.zeros((len(frames), 1)),
                                 np.cumsum(frames ** 2, axis=1)), axis=1)
        lags = np.arange(high_lag + 2)
        denominator = np.sqrt(np.maximum(
            energy[:, WINDOW - lags] * (energy[:, -1, None] - energy[:, lags]), 1e-30))
        corr = acf[:, :high_lag + 2] / denominator
        for j, row in enumerate(corr):
            peaks, _ = find_peaks(row[low_lag:high_lag + 1])
            peaks = peaks + low_lag
            if not len(peaks):
                continue
            best = row[peaks].max()
            # Earliest nearly-equivalent maximum avoids octave-down errors
            # from harmonics of a clean periodic waveform.
            lag = int(peaks[np.flatnonzero(row[peaks] >= max(.55, best * .92))[0]]) if best >= .55 else int(peaks[np.argmax(row[peaks])])
            quality = float(np.clip(row[lag], 0, 1))
            curvature = row[lag - 1] - 2 * row[lag] + row[lag + 1]
            shift = .5 * (row[lag - 1] - row[lag + 1]) / curvature if abs(curvature) > 1e-12 else 0
            f0[offset + j] = SAMPLE_RATE / (lag + np.clip(shift, -.5, .5))
            periodicity[offset + j] = quality
    active = rms > max(1e-5, float(rms.max()) * .01)
    voiced = active & (periodicity >= .65) & (f0 > 0)
    f0[~voiced] = 0
    return Features(rms, bands, f0, voiced, periodicity, active)


def _correlation(a: np.ndarray, b: np.ndarray) -> float | None:
    if len(a) < 3:
        return None
    a = a - np.mean(a)
    b = b - np.mean(b)
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    if denominator <= 1e-12:
        return None
    return float(np.clip(np.dot(a, b) / denominator, -1, 1))


def _align(reference: np.ndarray, candidate: np.ndarray, bound: int) -> tuple[int, float | None]:
    """Positive lag means the candidate is late; never warp or stretch time."""
    # Use changes in the energy envelope to find attacks, with a weaker energy
    # term that disambiguates repeated note attacks and long silences.
    def onset(x):
        return np.maximum(0, np.diff(np.log1p(x * 100), prepend=0))

    ref_onset, cand_onset = onset(reference), onset(candidate)
    best = (float("-inf"), 0, None)
    min_overlap = max(3, int(min(len(reference), len(candidate)) * .75))
    for lag in range(-bound, bound + 1):
        r0, c0 = max(0, -lag), max(0, lag)
        length = min(len(reference) - r0, len(candidate) - c0)
        if length < min_overlap:
            continue
        # A centered RMS window leaks an attack into the preceding two frames.
        # The start/end of the cropped overlap must not masquerade as attacks.
        edge = 2 if length > 8 else 0
        a = _correlation(ref_onset[r0 + edge:r0 + length - edge],
                         cand_onset[c0 + edge:c0 + length - edge])
        b = _correlation(reference[r0:r0 + length], candidate[c0:c0 + length])
        if a is None and b is None:
            continue
        quality = .7 * (a if a is not None else b) + .3 * (b if b is not None else a)
        # Prefer no correction when evidence is tied (e.g. a steady tone).
        objective = quality - abs(lag) * 1e-5
        if objective > best[0]:
            best = (objective, lag, quality)
    if best[2] is None or best[2] < .1:
        return 0, None
    return best[1], float(best[2])


def compare_samples(reference: np.ndarray, candidate: np.ndarray,
                    *, max_lag_seconds: float = .5) -> dict:
    """Compare finite 16 kHz signals; undefined measurements are JSON null."""
    if not np.isfinite(max_lag_seconds) or not 0 <= max_lag_seconds <= 5:
        raise ValueError("max_lag_seconds must be in 0..5")
    ref, cand = acoustic_features(reference), acoustic_features(candidate)
    bound = round(max_lag_seconds * SAMPLE_RATE / HOP)
    lag, alignment_confidence = _align(ref.rms, cand.rms, bound)
    # Map into the full reference timeline. Missing candidate audio stays
    # silent and therefore counts against coverage and the energy comparison.
    indices = np.arange(len(ref.rms)) + lag
    valid = (indices >= 0) & (indices < len(cand.rms))
    mapped = np.clip(indices, 0, len(cand.rms) - 1)
    candidate_rms = np.where(valid, cand.rms[mapped], 0)
    candidate_voiced = valid & cand.voiced[mapped]
    both_voiced = ref.voiced & candidate_voiced
    both_active = ref.active & valid & cand.active[mapped]
    cents = 1200 * np.log2(cand.f0[mapped[both_voiced]] / ref.f0[both_voiced])
    absolute_cents = np.abs(cents)
    ref_voiced_count, cand_voiced_count = int(ref.voiced.sum()), int(cand.voiced.sum())
    matched_voiced_count = int(both_voiced.sum())
    errors = (ref.spectrum_db[both_active] - cand.spectrum_db[mapped[both_active]])
    union_active = ref.active | (valid & cand.active[mapped])
    level_errors = (20 * np.log10(np.maximum(candidate_rms[union_active], 1e-4))
                    - 20 * np.log10(np.maximum(ref.rms[union_active], 1e-4)))
    mean_or_none = lambda values: float(np.mean(values)) if len(values) else None
    return {
        "analysis_version": ANALYSIS_VERSION,
        "reference_seconds": len(reference) / SAMPLE_RATE,
        "candidate_seconds": len(candidate) / SAMPLE_RATE,
        "timing": {
            "candidate_delay_seconds": lag * HOP / SAMPLE_RATE,
            "max_alignment_seconds": max_lag_seconds,
            "at_search_boundary": bool(bound and abs(lag) == bound),
            "alignment_correlation": alignment_confidence,
        },
        "pitch": {
            "mean_absolute_cents": mean_or_none(absolute_cents),
            "median_absolute_cents": float(np.median(absolute_cents)) if len(cents) else None,
            "p90_absolute_cents": float(np.percentile(absolute_cents, 90)) if len(cents) else None,
            "median_signed_cents": float(np.median(cents)) if len(cents) else None,
            "jointly_voiced_seconds": matched_voiced_count * HOP / SAMPLE_RATE,
        },
        "voicing": {
            "reference_voiced_seconds": ref_voiced_count * HOP / SAMPLE_RATE,
            "candidate_voiced_seconds": cand_voiced_count * HOP / SAMPLE_RATE,
            "recall": matched_voiced_count / ref_voiced_count if ref_voiced_count else None,
            "precision": matched_voiced_count / cand_voiced_count if cand_voiced_count else None,
        },
        "loudness": {
            "envelope_correlation": _correlation(ref.rms, candidate_rms),
            "mean_signed_db": mean_or_none(level_errors),
            "rmse_db": float(np.sqrt(np.mean(level_errors ** 2))) if len(level_errors) else None,
        },
        "spectrum": {
            "envelope_rmse_db": float(np.sqrt(np.mean(errors ** 2))) if len(errors) else None,
            "jointly_active_seconds": int(both_active.sum()) * HOP / SAMPLE_RATE,
            "reference_active_coverage": float(both_active.sum() / ref.active.sum()) if ref.active.any() else None,
        },
        "limitations": [
            "Acoustic diagnostics do not establish lyric intelligibility or singer identity.",
            "Pitch assumes one singer; use an isolated vocal stem, not the full music mix.",
            "Conditional pitch and spectrum errors must be read with coverage and timing.",
        ],
    }


def compare_audio(reference: Path, candidate: Path, *, max_lag_seconds: float = .5) -> dict:
    """Decode two recordings, align at most 0.5 seconds, and measure differences."""
    from .audio import load_audio

    return compare_samples(load_audio(reference, sample_rate=SAMPLE_RATE),
                           load_audio(candidate, sample_rate=SAMPLE_RATE),
                           max_lag_seconds=max_lag_seconds)


def select_fit(baseline: dict, candidate: dict) -> dict:
    """Conservatively select between complete rendered-vocal measurements.

    Both reports must compare the same source vocal with the same measurement
    settings. The dictionary's optimization loss is deliberately not an input.
    These thresholds are acoustic guardrails, not proof of intelligibility,
    naturalness, or perceptual preference. Missing evidence keeps the baseline.
    """
    thresholds = {
        "minimum_spectral_improvement_db": .05,
        "maximum_voicing_recall_loss": .01,
        "maximum_active_coverage_loss": .01,
        "maximum_pitch_mae_regression_cents": 5.,
        "maximum_absolute_delay_increase_seconds": .02,
    }
    specifications = (
        ("spectrum", "envelope_rmse_db", 0., None),
        ("voicing", "recall", 0., 1.),
        ("spectrum", "reference_active_coverage", 0., 1.),
        ("pitch", "mean_absolute_cents", 0., None),
        ("timing", "candidate_delay_seconds", None, None),
    )
    values, reasons = {}, []
    for name, report in (("baseline", baseline), ("candidate", candidate)):
        values[name] = {}
        for section, key, minimum, maximum in specifications:
            group = report.get(section) if isinstance(report, dict) else None
            value = group.get(key) if isinstance(group, dict) else None
            if (isinstance(value, bool) or not isinstance(value, Real)
                    or not math.isfinite(value)
                    or (minimum is not None and value < minimum)
                    or (maximum is not None and value > maximum)):
                reasons.append(f"Missing or invalid {name} measurement: {section}.{key}.")
            else:
                values[name][key] = float(value)
    improvement = None
    if "envelope_rmse_db" in values["baseline"] and "envelope_rmse_db" in values["candidate"]:
        improvement = values["baseline"]["envelope_rmse_db"] - values["candidate"]["envelope_rmse_db"]
    if not reasons:
        before, after = values["baseline"], values["candidate"]
        # Tiny arithmetic noise must not reject a value exactly at a boundary.
        tolerance = 1e-12
        if improvement < thresholds["minimum_spectral_improvement_db"] - tolerance:
            reasons.append(f"Spectral envelope improvement {improvement:.6f} dB is below the required 0.05 dB.")
        if before["recall"] - after["recall"] > thresholds["maximum_voicing_recall_loss"] + tolerance:
            reasons.append("Voicing recall falls by more than 0.01.")
        if (before["reference_active_coverage"] - after["reference_active_coverage"]
                > thresholds["maximum_active_coverage_loss"] + tolerance):
            reasons.append("Active spectral coverage falls by more than 0.01.")
        if (after["mean_absolute_cents"] - before["mean_absolute_cents"]
                > thresholds["maximum_pitch_mae_regression_cents"] + tolerance):
            reasons.append("Mean absolute pitch error increases by more than 5 cents.")
        if (abs(after["candidate_delay_seconds"]) - abs(before["candidate_delay_seconds"])
                > thresholds["maximum_absolute_delay_increase_seconds"] + tolerance):
            reasons.append("Absolute alignment delay increases by more than 0.02 seconds.")
    selected = "baseline" if reasons else "candidate"
    if not reasons:
        reasons.append(f"Full-render spectral envelope improves by {improvement:.6f} dB and all acoustic guardrails pass.")
    return {
        "selected": selected,
        "reasons": reasons,
        "spectral_improvement_db": improvement,
        "thresholds": thresholds,
        "interpretation": "Conservative acoustic selection; not a perceptual preference or intelligibility guarantee.",
    }
