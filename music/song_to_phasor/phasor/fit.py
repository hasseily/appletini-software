"""Fit SSI phonemes and tract filter settings against the actual firmware audio.

The small cached reference bank is an acoustic dictionary, not a recognizer.
It cannot infer lyrics or guarantee intelligibility. Supplied phoneme timings
can be locked while the acoustic filter is fitted. Pitch, energy, notes, and
other score annotations are preserved.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np

from .audio import load_audio
from .compare import ANALYSIS_VERSION, HOP, SAMPLE_RATE, acoustic_features
from .hardware import firmware_info, pack_pitch, ssi_initialize, ssi_pitch
from .score import validate_score


BANK_VERSION = 2
SEGMENT_TICKS = 22
BANK_TICK_HZ = 100
MAX_SEARCH_FRAMES = 6000
_CONTROLS = ("phoneme", "pitch_hz", "amplitude", "articulation", "filter", "rate", "duration")
_DEFAULTS = {"articulation": 5, "filter": 128, "rate": 8, "duration": 0}


def _expand_frames(frames: list[dict], duration: int, tick_hz: int) -> list[dict]:
    """Sample held audible controls; do not turn annotations into retriggers."""
    expanded = []
    stride = max(1, round(tick_hz / 100))
    for index, frame in enumerate(frames):
        expanded.append(frame)
        end = frames[index + 1]["tick"] if index + 1 < len(frames) else duration
        if frame["amplitude"] and frame["phoneme"]:
            controls = {key: frame[key] for key in _CONTROLS if key in frame}
            expanded.extend({"tick": tick, **controls}
                            for tick in range(frame["tick"] + stride, end, stride))
    return expanded


def _sparsify_frames(frames: list[dict], original_ticks: set[int]) -> list[dict]:
    """Remove redundant inserted controls while preserving all user events."""
    result, previous = [], None
    for frame in frames:
        state = tuple(frame.get(key, _DEFAULTS.get(key)) for key in _CONTROLS)
        if frame["tick"] in original_ticks or state != previous or frame.get("retrigger"):
            result.append(frame)
        previous = state
    return result


def _viterbi(cost: np.ndarray, switch_penalty: np.ndarray | float = .25) -> np.ndarray:
    """O(frames * candidates) uniform-switch Viterbi, with small backpointers.

    A varying penalty permits quick changes at acoustic attacks. Unlike a
    minimum-duration rule, this does not prohibit short consonants.
    """
    cost = np.asarray(cost, dtype=np.float64)
    if cost.ndim != 2 or not cost.shape[1] or np.isnan(cost).any():
        raise ValueError("Viterbi needs a frame by candidate cost matrix")
    if not len(cost):
        return np.zeros(0, dtype=np.int32)
    if np.any(~np.isfinite(cost).any(axis=1)):
        raise ValueError("Every frame needs at least one finite candidate")
    penalties = np.broadcast_to(switch_penalty, (len(cost),))
    if not np.isfinite(penalties).all() or np.any(penalties < 0):
        raise ValueError("Transition penalties must be finite and nonnegative")
    pointer = np.empty(cost.shape, dtype=np.int32)
    previous = cost[0].copy()
    states = np.arange(cost.shape[1])
    for frame in range(1, len(cost)):
        best = int(np.argmin(previous))
        jump = previous[best] + penalties[frame]
        stay = previous <= jump
        pointer[frame] = np.where(stay, states, best)
        previous = cost[frame] + np.minimum(previous, jump)
        # Renormalizing does not change the solution, and avoids drift on
        # long songs with many frames and large squared spectral errors.
        previous -= np.min(previous)
    path = np.empty(len(cost), dtype=np.int32)
    path[-1] = np.argmin(previous)
    for frame in range(len(cost) - 1, 0, -1):
        path[frame - 1] = pointer[frame, path[frame]]
    return path


def _bank_events(pitch_hz: float, filters: tuple[int, ...]):
    inflection, actual_pitch = ssi_pitch(pitch_hz)
    r1, r2 = pack_pitch(inflection, 8)
    events, labels = [], []
    for tract_filter in filters:
        for phone in range(1, 64):
            tick = len(labels) * SEGMENT_TICKS
            # Restore mode/IRQ state and trigger a fresh phone attack. The
            # renderer additionally asserts global reset at segment boundaries;
            # CTL alone cannot clear every interpolation or phase register.
            events.extend((tick, target, reg, value)
                          for target, reg, value in ssi_initialize(0))
            events.extend((tick, 4, reg, value) for reg, value in (
                (1, r1), (2, r2), (4, tract_filter), (0, phone), (3, 0x5F)))
            labels.append((phone, tract_filter))
    duration = len(labels) * SEGMENT_TICKS
    events.append((duration, 4, 3, 0x80))
    return events, np.asarray(labels, dtype=np.int16), duration, actual_pitch


def _load_bank(firmware_root: Path, cache_dir: Path, pitch_hz: float,
               filters: tuple[int, ...]) -> tuple[dict, dict]:
    from . import rtl

    fingerprint = rtl.source_fingerprint(firmware_root)
    config = {
        "version": BANK_VERSION, "analysis_version": ANALYSIS_VERSION,
        "firmware": fingerprint, "pitch_hz": pitch_hz, "filters": filters,
        "segment_ticks": SEGMENT_TICKS, "tick_hz": BANK_TICK_HZ,
        "reset_each_segment": True,
    }
    key = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:24]
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    bank_path = cache_dir / f"ssi-bank-{key}.npz"
    if bank_path.exists():
        try:
            with np.load(bank_path, allow_pickle=False) as saved:
                bank = {name: saved[name].copy() for name in ("labels", "spectra", "voiced")}
            if (bank["labels"].shape != (len(bank["labels"]), 2)
                    or bank["spectra"].shape != (len(bank["labels"]), 2, 24)
                    or bank["voiced"].shape != (len(bank["labels"]), 2)
                    or not len(bank["labels"])
                    or not np.issubdtype(bank["labels"].dtype, np.integer)
                    or not np.isfinite(bank["spectra"]).all()
                    or not np.isfinite(bank["voiced"]).all()):
                raise ValueError("Malformed cached bank")
            return bank, {"cache_hit": True, "key": key, **config}
        except (ValueError, OSError, KeyError):
            # Interrupted or stale cache data can always be rebuilt locally.
            bank_path.unlink(missing_ok=True)
    events, labels, duration, actual_pitch = _bank_events(pitch_hz, filters)
    wave_path = cache_dir / f"ssi-bank-{key}.wav"
    render_info = rtl.render(events, BANK_TICK_HZ, duration, firmware_root,
                             wave_path, cache_dir,
                             reset_ticks=range(0, duration, SEGMENT_TICKS))
    samples = load_audio(wave_path, sample_rate=SAMPLE_RATE)
    spectra, voicing, kept_labels = [], [], []
    for row, label in enumerate(labels):
        first = row * SEGMENT_TICKS * HOP
        segment = samples[first:first + SEGMENT_TICKS * HOP]
        if not len(segment):
            raise RuntimeError("The SSI bank render ended before all templates were produced")
        # Analyze each reset segment separately: centered windows must not
        # mix the preceding phone into an attack or set a shared noise floor
        # that hides weak fricatives beneath a much louder vowel.
        features = acoustic_features(segment)
        # Keep separate attack and body descriptors. Averaging everything
        # would lose stop consonants and favor sustained vowels everywhere.
        phases = (np.arange(1, 8), np.arange(8, 19))
        active_phases = [indices[(indices < len(features.rms)) &
                                  features.active[np.clip(indices, 0, len(features.rms) - 1)]]
                         for indices in phases]
        if not any(len(indices) for indices in active_phases):
            continue  # Reserved/silent phones are never a useful voiced match.
        usable = next(indices for indices in active_phases if len(indices))
        active_phases = [indices if len(indices) else usable for indices in active_phases]
        spectra.append([np.mean(features.spectrum_db[indices], axis=0) for indices in active_phases])
        voicing.append([np.mean(features.voiced[indices]) for indices in active_phases])
        kept_labels.append(label)
    if not kept_labels:
        raise RuntimeError("The firmware rendered a silent SSI bank; inspect renderer output and firmware compatibility")
    bank = {"labels": np.asarray(kept_labels, dtype=np.int16),
            "spectra": np.asarray(spectra), "voiced": np.asarray(voicing)}
    with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".npz", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        np.savez_compressed(temporary_path, **bank)
        temporary_path.replace(bank_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return bank, {"cache_hit": False, "key": key, **config,
                  "actual_bank_pitch_hz": actual_pitch, "render": render_info}


def _emissions(spectra: np.ndarray, voiced: np.ndarray, bank: dict) -> np.ndarray:
    """Minimum attack/body distance with modest voiced/unvoiced mismatch cost."""
    result = np.empty((len(spectra), len(bank["labels"])), dtype=np.float32)
    for offset in range(0, len(spectra), 128):
        count = min(128, len(spectra) - offset)
        difference = spectra[offset:offset + count, None, None, :] - bank["spectra"][None]
        cost = np.mean(difference ** 2, axis=-1) / 100
        cost += .75 * (voiced[offset:offset + count, None, None] - bank["voiced"][None]) ** 2
        result[offset:offset + count] = cost.min(axis=2)
    return result


def fit_score(score: dict, vocals: Path, firmware_root: Path, cache_dir: Path,
              *, locked_phonemes: bool = False, filters: tuple[int, ...] = (96, 128, 160),
              bank_pitch_hz: float | None = None) -> tuple[dict, dict]:
    """Select phone/filter sequences by matching a cached real-RTL dictionary.

    A first default bank contains 189 phone/filter combinations (~42 s of
    simulated audio). Later songs reuse it when their rounded median pitch
    matches. Pass ``filters=(128,)`` for a smaller neutral-tract search.
    Final quality must be measured with compare_audio on the full rendered
    vocal; dictionary loss is only the search proxy.
    """
    validate_score(score)
    profile = firmware_info(Path(firmware_root))
    if not profile["verified"]:
        raise ValueError("Acoustic fitting requires the pinned F1.2.4 firmware sources; cached banks do not bypass verification")
    populated_voices = [voice for voice in score.get("voices", [])
                        if any(frame["amplitude"] > 0 for frame in voice["frames"])]
    if len(populated_voices) > 1:
        raise ValueError("One vocal stem cannot fit two independent SSI voices; fit each voice against its own stem")
    filters = tuple(dict.fromkeys(filters))
    if not filters or any(type(value) is not int or not 0 <= value <= 255 for value in filters):
        raise ValueError("filters must contain SSI filter integers in 0..255")
    if len(filters) > 8:
        raise ValueError("At most eight filter settings may be searched in one bank")
    if not isinstance(locked_phonemes, bool):
        raise ValueError("locked_phonemes must be boolean")
    samples = load_audio(vocals, sample_rate=SAMPLE_RATE)
    features = acoustic_features(samples)
    score_duration = score["duration_ticks"] / score["tick_hz"]
    if len(samples) / SAMPLE_RATE + .05 < score_duration:
        raise ValueError("Vocal stem is shorter than the score; preserve the original song timeline")
    if bank_pitch_hz is None:
        pitches = features.f0[features.voiced]
        bank_pitch_hz = float(np.clip(round(float(np.median(pitches)) / 20) * 20, 60, 1000)) if len(pitches) else 140.
    if not np.isfinite(bank_pitch_hz) or not 31.25 <= bank_pitch_hz <= 20000:
        raise ValueError("bank_pitch_hz must be finite and in 31.25..20000")
    fitted = copy.deepcopy(score)
    audible_count = sum(frame["amplitude"] > 0 and frame["phoneme"] != 0
                         for voice in fitted.get("voices", []) for frame in voice["frames"])
    if not audible_count:
        return fitted, {"changed_frames": 0, "fitted_frames": 0,
                        "method": "cached RTL acoustic dictionary", "reason": "No audible vocal frames"}
    bank, bank_info = _load_bank(Path(firmware_root), Path(cache_dir), float(bank_pitch_hz), filters)
    labels = bank["labels"]
    changed = fitted_count = unavailable = 0
    before_costs, after_costs = [], []
    for voice in fitted.get("voices", []):
        original_ticks = {frame["tick"] for frame in voice["frames"]}
        frames = _expand_frames(voice["frames"], score["duration_ticks"], score["tick_hz"])
        # Keep silence unchanged and break smoothing at rests. Source consonants
        # need not have a stable F0 to be eligible for a spectral match.
        runs, run = [], []
        for index, frame in enumerate(frames):
            feature_index = round(frame["tick"] / score["tick_hz"] * SAMPLE_RATE / HOP)
            eligible = (frame["amplitude"] > 0 and frame["phoneme"] != 0
                        and feature_index < len(features.rms) and features.active[feature_index])
            if locked_phonemes and not np.any(labels[:, 0] == frame["phoneme"]):
                eligible = False
                unavailable += int(frame["amplitude"] > 0)
            if eligible:
                if run and (len(run) >= MAX_SEARCH_FRAMES
                            or frame["tick"] - frames[run[-1][0]]["tick"] > max(1, score["tick_hz"] * .08)):
                    runs.append(run)
                    run = []
                run.append((index, feature_index))
            elif run:
                runs.append(run)
                run = []
        if run:
            runs.append(run)
        for run in runs:
            frame_indices, source_indices = np.asarray(run).T
            spectra = features.spectrum_db[source_indices]
            cost = _emissions(spectra, features.voiced[source_indices].astype(float), bank)
            for row, frame_index in enumerate(frame_indices):
                original = frames[frame_index]
                old = (labels[:, 0] == original["phoneme"]) & (labels[:, 1] == original.get("filter", 128))
                if old.any():
                    before_costs.append(float(cost[row, np.flatnonzero(old)[0]]))
                if locked_phonemes:
                    cost[row, labels[:, 0] != original["phoneme"]] = np.inf
            flux = np.concatenate(([0.], np.sqrt(np.mean(np.diff(spectra, axis=0) ** 2, axis=1))))
            # Low regularization stops flutter without requiring long segments;
            # an attack gets almost no change penalty and can retain a 10 ms stop.
            penalty = .2 * np.exp(-flux / 3)
            path = _viterbi(cost, penalty)
            for row, frame_index in enumerate(frame_indices):
                frame = frames[frame_index]
                phone, tract_filter = map(int, labels[path[row]])
                changed += int(frame["phoneme"] != phone or frame.get("filter", 128) != tract_filter)
                frame["phoneme"], frame["filter"] = phone, tract_filter
                fitted_count += 1
                after_costs.append(float(cost[row, path[row]]))
        voice["frames"] = _sparsify_frames(frames, original_ticks)
    report = {
        "method": "cached RTL acoustic dictionary with attack/body spectra and Viterbi smoothing",
        "bank": bank_info, "firmware": profile, "templates": len(labels), "locked_phonemes": locked_phonemes,
        "fitted_frames": fitted_count, "changed_frames": changed,
        "locked_frames_without_template": unavailable,
        "maximum_search_frames_per_chunk": MAX_SEARCH_FRAMES,
        "dictionary_loss_before": float(np.mean(before_costs)) if before_costs else None,
        "dictionary_loss_after": float(np.mean(after_costs)) if after_costs else None,
        "dictionary_loss_before_frames": len(before_costs),
        "limitations": [
            "Dictionary loss is a search proxy, not a perceptual quality or intelligibility score.",
            "One source-median pitch bank approximates tract shape; final rendering uses the full original pitch contour.",
            "Attack history and phone transitions differ from isolated templates; compare the complete rendered vocal.",
            "Automatic phones approximate sound, not lyrics; lock aligned phonemes to preserve known words.",
        ],
    }
    fitted.setdefault("analysis", {})["acoustic_fit"] = {
        "bank_key": bank_info["key"], "changed_frames": changed,
        "locked_phonemes": locked_phonemes,
    }
    validate_score(fitted)
    return fitted, report
