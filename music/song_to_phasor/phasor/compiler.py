"""Compile all analysis on the host; leave only timed register writes to the IIe."""

from __future__ import annotations

from collections import Counter
import math

from .hardware import (_positive_finite, ay_period, pack_pitch, physical_ssi_filter,
                       physical_ssi_pitch, ssi_initialize, ssi_pitch)
from .score import validate_score

AY_CLOCKS = {"ntsc": 2_040_968, "pal": 2_031_250}
# physical-ssi263 follows the SSI-263 datasheet: a real Phasor and Appletini
# F1.2.5 and later. appletini-f1.2.4 matches the obsolete F1.2.4 speech model
# and its pinned RTL, which the fit, listen and render tools still simulate.
PROFILES = ("physical-ssi263", "appletini-f1.2.4")
DEFAULT_PROFILE = "physical-ssi263"
# (absolute tick, logical target: AY 0..3 / SSI 4..5, register, value)
Event = tuple[int, int, int, int]


def percussion_writes(hits: list[dict], clock_hz: int) -> list[tuple[int, int, int, int]]:
    """AY3 only: tone-swept kick A, noise snare B and noise hat C.

    The B/C noise source is shared at one fixed period. It is never retuned by
    a hit, so a simultaneous hat cannot change the snare's timbre. Software
    amplitude envelopes leave the AY's shared hardware envelope unused.
    Tuples are (tick, order, register, value), with releases before attacks.
    """
    writes = []
    for hit in hits:
        start, end, level = hit["start_tick"], hit["end_tick"], hit["velocity"]
        channel = {"kick": 0, "snare": 1, "hat": 2}[hit["kind"]]
        # Fractions give short hits a valid envelope at every supported tick
        # rate; deduplicate quantized stages without erasing the initial attack.
        stages = ((0, 0), (.28, 2), (.62, 5)) if channel < 2 else ((0, 0), (.40, 3))
        used = set()
        for fraction, decay in stages:
            when = start + int((end - start) * fraction)
            if when in used:
                continue
            used.add(when)
            if channel == 0:
                hz = (155, 90, 58)[len(used) - 1]
                period, _ = ay_period(hz, clock_hz)
                writes.extend([(when, 1, 0, period & 255),
                               (when, 1, 1, period >> 8)])
            writes.append((when, 1, 8 + channel, max(0, level - decay)))
        writes.append((end, 0, 8 + channel, 0))
    return writes


def compile_score(score: dict, clock: str = "ntsc", center_voice: bool = True, *,
                  profile: str = DEFAULT_PROFILE,
                  ssi_effective_clock_hz: float | None = None) -> tuple[list[Event], dict]:
    validate_score(score)
    if clock not in AY_CLOCKS:
        raise ValueError("clock must be ntsc or pal")
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {', '.join(PROFILES)}")
    physical = profile == "physical-ssi263"
    if ssi_effective_clock_hz is not None and not physical:
        raise ValueError("ssi_effective_clock_hz requires profile physical-ssi263")
    effective_clock = _positive_finite(
        AY_CLOCKS[clock] / 2 if ssi_effective_clock_hz is None else ssi_effective_clock_hz,
        "effective SSI clock")
    neutral_filter = physical_ssi_filter(128, effective_clock)[0] if physical else 128
    filter_registers = {neutral_filter}
    requested_pitches = []
    achieved_pitches = []
    events = []
    shadow = {}
    suppressed = 0

    def write(tick, target, reg, value, force=False):
        nonlocal suppressed
        key = target, reg
        if not force and shadow.get(key) == value:
            suppressed += 1
            return
        events.append((tick, target, reg, value))
        shadow[key] = value

    # Required on every stream: don't inherit live registers from a prior song.
    for chip in range(4):
        for reg in range(14):
            write(0, chip, reg, 0x38 if reg == 7 else 0, force=True)
    for chip in range(2):
        for target, reg, value in ssi_initialize(chip, filter_byte=neutral_filter):
            write(0, target, reg, value, force=True)

    pitch_errors = []
    clipped = 0
    shortened_pulse = 0
    last_phone = {}
    was_audible = {}
    # One voice is centred by writing both hard-panned SSI sockets. Two voice
    # tracks own the sockets independently; they are never mirrored over each other.
    mirror = center_voice and len(score.get("voices", [])) == 1
    vocal_frames = []
    for voice in score.get("voices", []):
        targets = (4, 5) if mirror else (4 + voice["chip"],)
        for frame in voice["frames"]:
            vocal_frames.append((frame["tick"], targets, frame))
    for tick, targets, frame in sorted(vocal_frames, key=lambda item: item[0]):
        infl, actual = (physical_ssi_pitch(frame["pitch_hz"], effective_clock)
                        if physical else ssi_pitch(frame["pitch_hz"]))
        r1, r2 = pack_pitch(infl, frame.get("rate", 8))
        amp = frame["amplitude"]
        if amp:
            pitch_errors.append(abs(1200 * math.log2(actual / frame["pitch_hz"])))
            if physical:
                clipped += int(not effective_clock / 32768 <= frame["pitch_hz"] <= effective_clock / 8)
                requested_pitches.append(frame["pitch_hz"])
                achieved_pitches.append(actual)
            else:
                clipped += int(frame["pitch_hz"] < 31.25 or frame["pitch_hz"] > 20000)
                shortened_pulse += int(actual > 20000 / 72)
        for target in targets:
            if not amp:
                write(tick, target, 3, frame.get("articulation", 5) << 4)
                was_audible[target] = False
                continue
            # Live pitch and tract changes preserve the running phoneme and
            # glottal phase. R0 is an edge-triggering write, never just a shadow.
            write(tick, target, 1, r1)
            write(tick, target, 2, r2)
            filter_byte = (physical_ssi_filter(frame.get("filter", 128), effective_clock)[0]
                           if physical else frame.get("filter", 128))
            filter_registers.add(filter_byte)
            write(tick, target, 4, filter_byte)
            phone = (frame.get("duration", 0) << 6) | frame["phoneme"]
            if phone != last_phone.get(target) or not was_audible.get(target) or frame.get("retrigger", False):
                write(tick, target, 0, phone, force=True)
                last_phone[target] = phone
            write(tick, target, 3, (frame.get("articulation", 5) << 4) | amp)
            was_audible[target] = True

    percussion = score.get("percussion", [])
    if percussion:
        # A: tone only; B/C: noise only. Amplitude zero gates each channel.
        write(0, 3, 6, 8)
        write(0, 3, 7, 0x0E)
    ay_writes = []
    for note in score.get("notes", []):
        # Release before the next attack when notes meet on the same tick.
        chip, channel = divmod(note["voice"], 3)
        hz = 440.0 * 2 ** ((note["midi"] - 69) / 12)
        period, _ = ay_period(hz, AY_CLOCKS[clock])
        ay_writes.extend([
            (note["start_tick"], 1, chip, channel * 2, period & 255),
            (note["start_tick"], 1, chip, channel * 2 + 1, period >> 8),
            (note["start_tick"], 1, chip, 8 + channel, note["velocity"]),
            (note["end_tick"], 0, chip, 8 + channel, 0),
        ])
    ay_writes.extend((tick, order, 3, reg, value)
                     for tick, order, reg, value in percussion_writes(percussion, AY_CLOCKS[clock]))
    for tick, _, chip, reg, value in sorted(ay_writes, key=lambda item: item[:2]):
        write(tick, chip, reg, value)

    duration = score["duration_ticks"]
    for target in range(4):
        for reg in (8, 9, 10):
            write(duration, target, reg, 0)
    if percussion:
        write(duration, 3, 7, 0x38)
    for target in (4, 5):
        write(duration, target, 3, 0x80, force=True)
    # Stable order keeps the CTL/mode handshake and simultaneous note releases.
    events.sort(key=lambda event: event[0])
    counts = Counter(event[0] for event in events)
    warnings = []
    if clipped:
        pitch_range = "physical SSI pitch register" if physical else "modeled SSI pitch"
        warnings.append(f"{clipped} audible frames exceeded the {pitch_range} range")
    if shortened_pulse:
        warnings.append(f"{shortened_pulse} audible frames shorten the SSI excitation pulse above 278 Hz; audition or transpose these notes")
    if max(counts.values(), default=0) > 96:
        warnings.append("Large register burst: benchmark the player and the configured slot slowdown on hardware")
    report = {
        "profile": profile, "clock": clock, "ay_clock_hz": AY_CLOCKS[clock],
        "tick_hz": score["tick_hz"], "duration_ticks": duration,
        "centered_voice": mirror, "register_writes": len(events),
        "suppressed_writes": suppressed, "peak_writes_per_tick": max(counts.values(), default=0),
        "mean_pitch_error_cents": sum(pitch_errors) / len(pitch_errors) if pitch_errors else None,
        "max_pitch_error_cents": max(pitch_errors) if pitch_errors else None,
        "clipped_vocal_frames": clipped, "warnings": warnings,
        "percussion_hits": len(percussion),
    }
    if physical:
        report.update({
            "ssi_effective_clock_hz": effective_clock,
            "ssi_pitch_model": "XCK / (8 * (4096 - I))",
            "pitch_error_basis": "datasheet equation; excludes physical clock and analog tolerances",
            "requested_vocal_pitch_hz_range": [min(requested_pitches), max(requested_pitches)] if requested_pitches else None,
            "achieved_vocal_pitch_hz_range": [min(achieved_pitches), max(achieved_pitches)] if achieved_pitches else None,
            "ssi_filter_register_range": [min(filter_registers), max(filter_registers)],
            "ssi_filter_clock_hz_range": [effective_clock / (2 * (256 - value))
                                           for value in (min(filter_registers), max(filter_registers))],
            "ssi_filter_mapping": "20,000 * (128 + authored_filter) / 256 Hz; nearest XCK / (2 * (256 - FF)); not a calibrated spectral match",
            "physical_hardware_calibrated": False,
        })
    else:
        report.update({"target_firmware": "F1.2.4", "shortened_excitation_frames": shortened_pulse})
    return events, report
