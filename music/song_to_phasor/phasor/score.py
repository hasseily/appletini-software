"""Validate the editable, tick-based interchange format before compilation."""

from __future__ import annotations

import math


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and in {low}..{high}")
    return value


def validate_score(score: dict) -> None:
    if not isinstance(score, dict) or score.get("version") != 1:
        raise ValueError("score must be an object with version 1")
    integer(score["version"], "version", 1, 1)
    integer(score.get("tick_hz"), "tick_hz", 25, 400)
    duration = integer(score.get("duration_ticks"), "duration_ticks", 1, 0xFFFFFFFF)
    voices = score.get("voices", [])
    notes = score.get("notes", [])
    percussion = score.get("percussion", [])
    if not all(isinstance(track, list) for track in (voices, notes, percussion)):
        raise ValueError("voices, notes and percussion must be arrays")
    chips = set()
    for voice in voices:
        if not isinstance(voice, dict):
            raise ValueError("each voice must be an object")
        chip = integer(voice.get("chip"), "voice.chip", 0, 1)
        if chip in chips:
            raise ValueError("each SSI chip may have only one voice track")
        chips.add(chip)
        frames = voice.get("frames")
        if not isinstance(frames, list):
            raise ValueError("voice.frames must be an array")
        previous = -1
        for frame in frames:
            if not isinstance(frame, dict):
                raise ValueError("each vocal frame must be an object")
            tick = integer(frame.get("tick"), "frame.tick", 0, duration)
            if tick <= previous:
                raise ValueError("vocal frame ticks must strictly increase")
            previous = tick
            integer(frame.get("phoneme"), "frame.phoneme", 0, 63)
            number(frame.get("pitch_hz"), "frame.pitch_hz", 0.001, 100000)
            integer(frame.get("amplitude"), "frame.amplitude", 0, 15)
            integer(frame.get("articulation", 5), "frame.articulation", 0, 7)
            integer(frame.get("filter", 128), "frame.filter", 0, 255)
            integer(frame.get("rate", 8), "frame.rate", 0, 15)
            integer(frame.get("duration", 0), "frame.duration", 0, 3)
            if "retrigger" in frame and type(frame["retrigger"]) is not bool:
                raise ValueError("frame.retrigger must be boolean")
            if tick == duration and frame["amplitude"] != 0:
                raise ValueError("a terminal vocal frame must be silent")
    ends = {}
    for note in notes:
        if not isinstance(note, dict):
            raise ValueError("each note must be an object")
        start = integer(note.get("start_tick"), "note.start_tick", 0, duration - 1)
        end = integer(note.get("end_tick"), "note.end_tick", start + 1, duration)
        voice = integer(note.get("voice"), "note.voice", 0, 11)
        if percussion and voice >= 9:
            raise ValueError("percussion reserves AY voices 9..11; tonal notes must use voices 0..8")
        number(note.get("midi"), "note.midi", 0, 127)
        integer(note.get("velocity"), "note.velocity", 0, 15)
    for note in sorted(notes, key=lambda note: note["start_tick"]):
        voice, start, end = note["voice"], note["start_tick"], note["end_tick"]
        if start < ends.get(voice, 0):
            raise ValueError(f"overlapping accompaniment notes on voice {voice}")
        ends[voice] = end
    drum_ends = {}
    for hit in percussion:
        if not isinstance(hit, dict):
            raise ValueError("each percussion hit must be an object")
        start = integer(hit.get("start_tick"), "percussion.start_tick", 0, duration - 1)
        integer(hit.get("end_tick"), "percussion.end_tick", start + 1, duration)
        if hit.get("kind") not in ("kick", "snare", "hat"):
            raise ValueError("percussion.kind must be kick, snare or hat")
        integer(hit.get("velocity"), "percussion.velocity", 0, 15)
    for hit in sorted(percussion, key=lambda hit: hit["start_tick"]):
        kind, start, end = hit["kind"], hit["start_tick"], hit["end_tick"]
        if start < drum_ends.get(kind, 0):
            raise ValueError(f"overlapping percussion hits on {kind}")
        drum_ends[kind] = end
