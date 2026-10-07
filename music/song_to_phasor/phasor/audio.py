"""Optional, local audio analysis for a *draft* Phasor score.

Requires NumPy and SciPy; non-WAV inputs additionally require ffmpeg. This is
an intentionally modest DSP baseline, not speech recognition or source
separation. Supply an isolated vocal stem and timed SSI phonemes for lyrics.
All expensive transforms run in bounded batches; no trained models/downloads
or firmware Python models are used.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
from scipy import fft, ndimage, signal
from scipy.io import wavfile

SAMPLE_RATE = 16_000
BATCH_SIZE = 128
VOICE_WINDOW = 1024
MUSIC_WINDOW = 4096
MIN_F0 = 55.0
MAX_F0 = 1100.0

# SSI-263 codes, not SC-01 codes. Names match the speech inventory documented
# in demos/appletini_bosconian/docs/DESIGN.md. These approximate human formant
# locations are analysis heuristics, not measurements of the firmware voices.
VOWEL_TARGETS = (
    (0x01, 270.0, 2290.0),  # E
    (0x07, 390.0, 1990.0),  # I
    (0x0A, 530.0, 1840.0),  # EH
    (0x0C, 660.0, 1720.0),  # AE
    (0x0E, 730.0, 1090.0),  # AH
    (0x10, 570.0, 840.0),   # AW
    (0x13, 300.0, 870.0),   # OO
    (0x18, 440.0, 1020.0),  # UH
    (0x1C, 490.0, 1350.0),  # ER
)


def _read_audio(path: Path) -> np.ndarray:
    """Read mono float32 audio at 16 kHz; keep all file access local."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Audio file does not exist: {path}")
    if path.suffix.lower() == ".wav":
        try:
            rate, samples = wavfile.read(path)
        except (ValueError, OSError) as exc:
            raise ValueError(f"Cannot read WAV {path}: {exc}") from exc
        if samples.dtype.kind == "u":
            midpoint = float(1 << (samples.dtype.itemsize * 8 - 1))
            samples = (samples.astype(np.float32) - midpoint) / midpoint
        elif samples.dtype.kind == "i":
            scale = float(1 << (samples.dtype.itemsize * 8 - 1))
            samples = samples.astype(np.float32) / scale
        elif samples.dtype.kind == "f":
            samples = samples.astype(np.float32)
        else:
            raise ValueError(f"Unsupported WAV sample encoding: {samples.dtype}")
        if samples.ndim == 2:
            samples = samples.mean(axis=1)
        if samples.ndim != 1 or rate <= 0:
            raise ValueError(f"Invalid WAV dimensions or sample rate: {path}")
        if not np.all(np.isfinite(samples)):
            raise ValueError(f"Audio contains nonfinite samples: {path}")
        if rate != SAMPLE_RATE and samples.size:
            divisor = math.gcd(rate, SAMPLE_RATE)
            samples = signal.resample_poly(
                samples, SAMPLE_RATE // divisor, rate // divisor
            ).astype(np.float32)
        return np.clip(samples, -1.0, 1.0)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ValueError("Reading non-WAV audio requires ffmpeg on PATH")
    result = subprocess.run(
        [ffmpeg, "-v", "error", "-nostdin", "-i", str(path.resolve()),
         "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"],
        check=False, capture_output=True,
    )
    if result.returncode:
        reason = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"ffmpeg could not decode {path}: {reason[-1000:]}")
    if len(result.stdout) % 4:
        raise ValueError(f"ffmpeg returned incomplete samples for {path}")
    samples = np.frombuffer(result.stdout, dtype="<f4")
    if not np.all(np.isfinite(samples)):
        raise ValueError(f"Audio contains nonfinite samples: {path}")
    return np.clip(samples, -1.0, 1.0)


def load_audio(path: Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Public decoder for analysis and render comparison (mono floats)."""
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")
    samples = _read_audio(Path(path))
    if sample_rate != SAMPLE_RATE and samples.size:
        divisor = math.gcd(sample_rate, SAMPLE_RATE)
        samples = signal.resample_poly(samples, sample_rate // divisor,
                                       SAMPLE_RATE // divisor).astype(np.float32)
    return samples


def _batches(samples: np.ndarray, ticks: np.ndarray, tick_hz: int, size: int):
    """Centered windows with exact integer tick locations and zero padding."""
    # Keep the view virtual; only materialize up to BATCH_SIZE windows at once.
    padded = np.pad(samples, (size // 2, size // 2))
    windows = np.lib.stride_tricks.sliding_window_view(padded, size)
    for offset in range(0, len(ticks), BATCH_SIZE):
        tick_batch = ticks[offset:offset + BATCH_SIZE]
        centers = (tick_batch.astype(np.int64) * SAMPLE_RATE) // tick_hz
        frames = np.zeros((len(centers), size), dtype=np.float64)
        valid = centers < len(samples)
        frames[valid] = windows[centers[valid]]
        yield offset, frames


def _yin_batch(frames: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """FFT YIN difference function; return F0 and periodicity confidence.

    Difference sums use the actual overlapping energies at each lag instead
    of a circular autocorrelation. First good local minimum avoids selecting
    a longer multiple of the fundamental period in a harmonic-rich voice.
    """
    frames = frames - frames.mean(axis=1, keepdims=True)
    count, size = frames.shape
    first = max(2, int(SAMPLE_RATE / MAX_F0))
    last = min(size // 2, int(math.ceil(SAMPLE_RATE / MIN_F0)))
    spectrum = fft.rfft(frames, n=2 * size, axis=1)
    autocorrelation = fft.irfft(spectrum * spectrum.conj(), n=2 * size, axis=1)
    energy = np.concatenate((np.zeros((count, 1)),
                             np.cumsum(frames * frames, axis=1)), axis=1)
    lags = np.arange(1, last + 1)
    differences = np.maximum(
        energy[:, size - lags] + energy[:, -1, None] - energy[:, lags]
        - 2.0 * autocorrelation[:, lags], 0.0,
    )
    cumulative = np.cumsum(differences, axis=1)
    cmnd = np.ones((count, last + 1))
    np.divide(differences * lags, cumulative, out=cmnd[:, 1:], where=cumulative > 1e-14)
    pitches = np.zeros(count)
    confidence = np.zeros(count)
    for index, curve in enumerate(cmnd):
        candidates = np.flatnonzero(curve[first:last] < 0.16) + first
        if len(candidates):
            lag = int(candidates[0])
            while lag < last and curve[lag + 1] < curve[lag]:
                lag += 1
        else:
            lag = first + int(np.argmin(curve[first:last + 1]))
        quality = float(np.clip(1.0 - curve[lag], 0.0, 1.0))
        confidence[index] = quality
        if quality < 0.70:
            continue
        fractional = float(lag)
        if 1 <= lag < last:
            left, center, right = curve[lag - 1:lag + 2]
            denominator = left - 2.0 * center + right
            if abs(denominator) > 1e-12:
                fractional += float(np.clip(0.5 * (left - right) / denominator, -0.5, 0.5))
        pitch = SAMPLE_RATE / fractional
        if MIN_F0 <= pitch <= MAX_F0:
            pitches[index] = pitch
    return pitches, confidence


def track_pitch(samples: np.ndarray, tick_hz: int = 100) -> dict[str, np.ndarray]:
    """Return per-tick F0, periodicity confidence, and RMS for 16 kHz mono.

    A zero F0 means unvoiced or silent. Confidence is periodicity, not ASR
    certainty. Returned arrays are NumPy arrays, suitable for metric work.
    """
    if isinstance(tick_hz, bool) or not isinstance(tick_hz, int) or not 1 <= tick_hz <= 1000:
        raise ValueError("tick_hz must be an integer in 1..1000")
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim != 1 or not np.all(np.isfinite(samples)):
        raise ValueError("Pitch analysis requires finite, mono samples at 16 kHz")
    count = max(1, math.ceil(len(samples) * tick_hz / SAMPLE_RATE))
    ticks = np.arange(count)
    pitches, confidence, rms = (np.zeros(count) for _ in range(3))
    for offset, frames in _batches(samples, ticks, tick_hz, VOICE_WINDOW):
        finish = offset + len(frames)
        pitches[offset:finish], confidence[offset:finish] = _yin_batch(frames)
        rms[offset:finish] = np.sqrt(np.mean(frames * frames, axis=1))
    threshold = max(1e-5, float(rms.max(initial=0.0)) * 10 ** (-42 / 20))
    pitches[rms < threshold] = 0
    confidence[rms < threshold] = 0
    return {"tick": ticks, "pitch_hz": pitches, "confidence": confidence, "rms": rms}


def _guess_phones(spectra: np.ndarray, pitches: np.ndarray) -> np.ndarray:
    """Broad vowel colors and noisy consonants only; never a transcription."""
    frequencies = fft.rfftfreq(VOICE_WINDOW, 1.0 / SAMPLE_RATE)
    envelope = ndimage.gaussian_filter1d(spectra, sigma=5.0, axis=1)
    low = (frequencies >= 230) & (frequencies <= 1000)
    high = (frequencies >= 800) & (frequencies <= 3000)
    low_indices = np.flatnonzero(low)
    high_indices = np.flatnonzero(high)
    phones = np.full(len(pitches), 0x0E, dtype=np.int16)
    total = spectra.sum(axis=1) + 1e-12
    high_fraction = spectra[:, frequencies >= 2500].sum(axis=1) / total
    targets = np.array([(f1, f2) for _, f1, f2 in VOWEL_TARGETS])
    for index, pitch in enumerate(pitches):
        if pitch == 0:
            phones[index] = 0x30 if high_fraction[index] > 0.45 else 0x34  # S / F
            continue
        # A nearly sinusoidal source has no useful vowel envelope. /AH/ is
        # a neutral audible draft, rather than pretending to infer a lyric.
        if spectra[index, frequencies > max(900, pitch * 2)].sum() < 0.025 * total[index]:
            continue
        f1 = frequencies[low_indices[np.argmax(envelope[index, low])]]
        f2 = frequencies[high_indices[np.argmax(envelope[index, high])]]
        distances = (np.log(targets[:, 0] / f1) ** 2
                     + np.log(targets[:, 1] / f2) ** 2)
        phones[index] = VOWEL_TARGETS[int(np.argmin(distances))][0]
    return phones


def _annotations(path: Path | None) -> list[tuple[float, float, int]] | None:
    if path is None:
        return None
    try:
        records = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read phoneme annotations {path}: {exc}") from exc
    if not isinstance(records, list):
        raise ValueError("Phoneme annotations must be a JSON list")
    result = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"Annotation {index} must be an object")
        start, end, phoneme = (record.get(key) for key in ("start", "end", "phoneme"))
        if (isinstance(start, bool) or not isinstance(start, (int, float))
                or isinstance(end, bool) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start):
            raise ValueError(f"Annotation {index} needs finite times 0 <= start < end")
        if isinstance(phoneme, bool) or not isinstance(phoneme, int) or not 0 <= phoneme <= 63:
            raise ValueError(f"Annotation {index} phoneme must be an SSI-263 code 0..63")
        result.append((float(start), float(end), phoneme))
    result.sort(key=lambda record: record[0])
    for previous, current in zip(result, result[1:]):
        if current[0] < previous[1]:
            raise ValueError("Phoneme annotations must not overlap")
    return result


def _voice_analysis(samples: np.ndarray, tick_hz: int, duration_ticks: int,
                    transpose: int, annotations: list | None) -> tuple[list[dict], dict]:
    ticks = np.arange(duration_ticks)
    pitches, rms, confidence = (np.zeros(duration_ticks) for _ in range(3))
    phones = np.zeros(duration_ticks, dtype=np.int16)
    window = signal.windows.hann(VOICE_WINDOW, sym=False)
    for offset, frames in _batches(samples, ticks, tick_hz, VOICE_WINDOW):
        finish = offset + len(frames)
        batch_pitch, batch_confidence = _yin_batch(frames)
        pitches[offset:finish] = batch_pitch
        confidence[offset:finish] = batch_confidence
        rms[offset:finish] = np.sqrt(np.mean(frames * frames, axis=1))
        spectra = abs(fft.rfft(frames * window, axis=1))
        phones[offset:finish] = _guess_phones(spectra, batch_pitch)
    reference = float(np.percentile(rms, 95)) if len(rms) else 0.0
    # The maximum fallback preserves sparse, short phrases in long silence.
    reference = max(reference, float(rms.max(initial=0.0)) * 0.25, 1e-8)
    audible = rms >= max(1e-5, reference * 10 ** (-42 / 20))
    amplitudes = np.clip(np.rint(15 * np.sqrt(rms / reference)), 1, 15).astype(np.int16)
    amplitudes[~audible] = 0
    confidence[~audible] = 0
    pitches[~audible] = 0
    phones[~audible] = 0
    # Three-frame median suppresses single-hop pitch outliers without moving
    # voiced/unvoiced boundaries or fabricating F0 for consonants.
    smoothed = ndimage.median_filter(pitches, size=3, mode="nearest")
    replace = (pitches > 0) & (smoothed > 0)
    pitches[replace] = smoothed[replace]
    retrigger_ticks = set()
    if annotations is not None:
        annotated = np.full(duration_ticks, -1, dtype=np.int16)
        times = ticks / tick_hz
        previous_interval = None
        for start, end, phoneme in annotations:
            first = int(np.searchsorted(times, start, side="left"))
            stop = int(np.searchsorted(times, end, side="left"))
            annotated[first:stop] = phoneme
            # Separate annotations denote distinct phones even when their
            # numeric codes agree. Preserve an onset when no silent tick
            # separates them; ordinary contour updates must remain legato.
            if (first < stop and phoneme > 0 and previous_interval is not None
                    and previous_interval[0] == phoneme
                    and previous_interval[1] >= first):
                retrigger_ticks.add(first)
            previous_interval = (phoneme, stop)
        gaps = annotated <= 0
        phones = np.maximum(annotated, 0)
        amplitudes[gaps] = 0
    else:
        # Use a majority filter, not a numeric median of unrelated phone IDs.
        original = phones.copy()
        for index in range(1, duration_ticks - 1):
            if (original[index - 1] == original[index + 1]
                    and original[index - 1] > 0 and amplitudes[index] > 0):
                phones[index] = original[index - 1]
    frames_out = []
    previous = None
    last_pitch = 120.0 * 2 ** (transpose / 12)
    for tick in range(duration_ticks):
        amplitude = int(amplitudes[tick])
        if pitches[tick] > 0 and amplitude > 0:
            # 1/32 semitone (~3 cents) keeps expressive contours while
            # eliminating pointless jitter in a steady held vowel.
            midi = round((69 + 12 * math.log2(pitches[tick] / 440)) * 32) / 32
            last_pitch = round(440 * 2 ** ((midi + transpose - 69) / 12), 3)
        phone = int(phones[tick]) if amplitude else 0
        state = (phone, last_pitch, amplitude)
        retrigger = tick in retrigger_ticks and amplitude > 0
        if state != previous or retrigger:
            frame = {"tick": tick, "phoneme": phone,
                     "pitch_hz": last_pitch, "amplitude": amplitude}
            if retrigger:
                frame["retrigger"] = True
            frames_out.append(frame)
            previous = state
    frames_out.append({"tick": duration_ticks, "phoneme": 0,
                       "pitch_hz": last_pitch, "amplitude": 0})
    voiced = (pitches > 0) & audible
    summary = {
        "method": "FFT YIN F0, RMS dynamics, broad spectral vowel/noise heuristic",
        "phoneme_source": "annotations" if annotations is not None else "spectral heuristic",
        "voiced_fraction": round(float(np.mean(voiced)), 4),
        "mean_voiced_confidence": round(float(np.mean(confidence[voiced])), 4) if np.any(voiced) else 0.0,
        "mean_rms": round(float(np.mean(rms)), 6),
        "pitch_range_hz": [round(float(pitches[voiced].min()), 3),
                           round(float(pitches[voiced].max()), 3)] if np.any(voiced) else [],
        "analysis_pitch_limits_hz": [MIN_F0, MAX_F0],
        "pitch_track": [{"tick": int(tick), "f0_hz": round(float(pitches[tick]), 3),
                         "confidence": round(float(confidence[tick]), 4),
                         "rms": round(float(rms[tick]), 6)} for tick in ticks],
    }
    return frames_out, summary


def _music_candidates(spectrum: np.ndarray, transpose: int) -> dict[int, float]:
    """Rough polyphony: spectral peaks minus likely upper harmonics.

    This intentionally sacrifices some octave chord tones to reduce harmonic
    duplicates. It does not infer instrument identities, drums, or note bends.
    """
    frequencies = fft.rfftfreq(MUSIC_WINDOW, 1.0 / SAMPLE_RATE)
    eligible = (frequencies >= 55) & (frequencies <= 2100)
    maximum = float(spectrum[eligible].max(initial=0.0))
    if maximum < 1e-4:
        return {}
    peaks, _ = signal.find_peaks(spectrum, height=maximum * 0.12,
                                 prominence=maximum * 0.06, distance=2)
    peaks = [int(index) for index in peaks if eligible[index]]
    peaks = sorted(peaks, key=lambda index: float(spectrum[index]), reverse=True)[:48]
    candidates = []
    for index in sorted(peaks):
        # Parabolic interpolation of log magnitude improves low note accuracy.
        left, center, right = np.log(np.maximum(spectrum[index - 1:index + 2], 1e-12))
        denominator = left - 2 * center + right
        shift = float(np.clip(0.5 * (left - right) / denominator, -0.5, 0.5)) if abs(denominator) > 1e-12 else 0.0
        frequency = (index + shift) * SAMPLE_RATE / MUSIC_WINDOW
        harmonic = False
        for fundamental, _ in candidates:
            ratio = frequency / fundamental
            nearest = round(ratio)
            if 2 <= nearest <= 8 and abs(1200 * math.log2(ratio / nearest)) < 25:
                harmonic = True
                break
        if not harmonic:
            candidates.append((frequency, float(spectrum[index])))
    result = {}
    for frequency, strength in sorted(candidates, key=lambda item: item[1], reverse=True)[:12]:
        midi = round(69 + 12 * math.log2(frequency / 440)) + transpose
        if 0 <= midi <= 127:
            result[midi] = max(result.get(midi, 0.0), strength)
    return result


def _accompaniment(samples: np.ndarray, tick_hz: int, duration_ticks: int,
                   transpose: int) -> list[dict]:
    step = max(1, round(tick_hz / 20))
    ticks = np.arange(0, duration_ticks, step)
    window = signal.windows.hann(MUSIC_WINDOW, sym=False)
    active: dict[int, dict] = {}
    pending: dict[int, tuple[int, int, int]] = {}
    notes = []
    slot_ends = [0] * 12
    reference = max(float(np.max(abs(samples), initial=0.0)) * MUSIC_WINDOW / 4, 1e-8)

    def finish(midi: int):
        note = active.pop(midi)
        end = min(duration_ticks, note.pop("last_tick") + step)
        if end > note["start_tick"]:
            note["end_tick"] = end
            notes.append(note)
            slot_ends[note["voice"]] = end

    for offset, frames in _batches(samples, ticks, tick_hz, MUSIC_WINDOW):
        spectra = abs(fft.rfft(frames * window, axis=1))
        for relative, spectrum in enumerate(spectra):
            tick = int(ticks[offset + relative])
            found = _music_candidates(spectrum, transpose)
            for midi in list(active):
                if midi not in found and tick - active[midi]["last_tick"] >= 2 * step:
                    finish(midi)
            for midi in list(pending):
                if midi not in found:
                    del pending[midi]
            for midi, strength in sorted(found.items()):
                velocity = int(np.clip(round(15 * math.sqrt(strength / reference)), 1, 15))
                if midi in active:
                    active[midi]["last_tick"] = tick
                    active[midi]["velocity"] = max(active[midi]["velocity"], velocity)
                    continue
                start, count, last = pending.get(midi, (tick, 0, tick - step))
                if last != tick - step:
                    start, count = tick, 0
                pending[midi] = (start, count + 1, tick)
                if count + 1 < 2:
                    continue
                used = {note["voice"] for note in active.values()}
                available = [voice for voice in range(12) if voice not in used]
                if available:
                    voice = available[0]
                    # A newly confirmed onset can precede the release of the
                    # slot used for it. Trim to that slot's last emitted end.
                    occupied_until = slot_ends[voice]
                    active[midi] = {"start_tick": max(start, occupied_until),
                                    "last_tick": tick, "midi": float(midi),
                                    "velocity": velocity, "voice": voice}
                    del pending[midi]
    for midi in list(active):
        finish(midi)
    return sorted(notes, key=lambda note: (note["start_tick"], note["voice"]))


def analyze_audio(song: Path, *, vocals: Path | None = None,
                  accompaniment: Path | None = None, annotations: Path | None = None,
                  tick_hz: int = 100, transpose: int = 0) -> dict:
    """Convert local audio into an editable score; quality notes are explicit.

    ``annotations`` is a JSON list of ``{start, end, phoneme}`` intervals in
    seconds using SSI codes 0..63. Intervals must not overlap. Annotated gaps
    are silent; time ranges use start-inclusive/end-exclusive semantics.
    Stems must be aligned at song time zero (no automatic stem alignment).
    Transposition affects voice and accompaniment together, in semitones.
    """
    if isinstance(tick_hz, bool) or not isinstance(tick_hz, int) or not 25 <= tick_hz <= 400:
        raise ValueError("tick_hz must be an integer in 25..400")
    if isinstance(transpose, bool) or not isinstance(transpose, int) or not -48 <= transpose <= 48:
        raise ValueError("transpose must be an integer in -48..48 semitones")
    timed_phones = _annotations(annotations)
    decoded: dict[Path, np.ndarray] = {}

    def read(path):
        path = Path(path).resolve()
        if path not in decoded:
            decoded[path] = _read_audio(path)
        return decoded[path]

    original = read(song)
    vocal_audio = read(vocals) if vocals is not None else original
    music_audio = read(accompaniment) if accompaniment is not None else original
    duration_ticks = max(1, math.ceil(max(len(original), len(vocal_audio), len(music_audio))
                                      * tick_hz / SAMPLE_RATE))
    voice_frames, vocal_report = _voice_analysis(vocal_audio, tick_hz, duration_ticks,
                                                 transpose, timed_phones)
    notes = _accompaniment(music_audio, tick_hz, duration_ticks, transpose)
    quality_notes = [
        "Local DSP draft: spectral phone colors do not recognize words or transcribe lyrics.",
        "Supply aligned SSI phoneme intervals to preserve lyrics; review vowel and consonant timing by ear.",
        "Accompaniment is a rough spectral reduction; harmonic suppression can remove octave chord tones.",
        "No drum transcription, instrument separation, or singer identity reconstruction is performed.",
        "F0 confidence describes periodicity, not confidence in the words or singer identity.",
    ]
    if vocals is None:
        quality_notes.append("No isolated vocal stem supplied: instruments in the mix can be mistaken for the singer.")
    if accompaniment is None:
        quality_notes.append("No accompaniment stem supplied: the mix is also reduced to AY notes and may duplicate the vocal melody.")
    if timed_phones is not None:
        quality_notes.append("Phoneme annotations override heuristic phones; annotated gaps are explicitly silent.")
    return {
        "version": 1,
        "title": Path(song).stem,
        "tick_hz": tick_hz,
        "duration_ticks": duration_ticks,
        "voices": [{"chip": 0, "frames": voice_frames}],
        "notes": notes,
        "analysis": {
            "sample_rate": SAMPLE_RATE,
            "transpose_semitones": transpose,
            "vocal_source": str(vocals if vocals is not None else song),
            "accompaniment_source": str(accompaniment if accompaniment is not None else song),
            "vocal": vocal_report,
            "quality_notes": quality_notes,
        },
    }
