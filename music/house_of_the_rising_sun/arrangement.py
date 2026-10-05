#!/usr/bin/env python3
"""Build the traditional song as an original AY / SSI-263 arrangement.

All musical times in the source are eighth notes. No audio, MIDI library or
network access is needed. See ARRANGEMENT.md for source and performance notes.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "song_to_phasor"))
from phasor.hardware import SSI_PHONEMES, fit_duration
from phasor.score import validate_score
from backing import accompaniment as build_backing, SONG_CHORDS
from percussion import percussion

TICK_HZ = 100
PULSE_BPM = 66  # dotted quarter: two pulses to each 6/8 bar
TRANSPOSE = 3   # Write in A minor; perform in C minor, with a brighter SSI range.
MUSIC_LEVEL_STEPS = 1  # Native AY volume lift relative to the unchanged singer.
TICKS_PER_EIGHTH = 60 * TICK_HZ / (PULSE_BPM * 3)
MUSIC_END = round(56 * 6 * TICKS_PER_EIGHTH)
DURATION = MUSIC_END + 50

# (syllable, eighth-note offset, [(MIDI, duration in eighths)], phone spelling)
# Parenthesized semivowels and closing consonants are intentionally short.
# The melody follows the traditional tune; phrase endings develop in verse two.
VERSE_ONE = [
    ("There", -2, [(40, 2)], "THV/EH/R"),
    ("is", 0, [(45, 4)], "/I/Z"),
    ("a", 4, [(47, 1), (45, 1)], "/UH/"),
    ("house", 6, [(48, 4)], "HF/AH>U/S"),
    ("in", 10, [(50, 1), (51, 1)], "/I/N"),
    ("New", 12, [(52, 4)], "N/IU/"),
    ("Or-", 16, [(48, 1), (47, 1)], "/AW/R"),
    ("-leans", 18, [(45, 4)], "L/E/N Z"),
    ("they", 22, [(52, 2)], "THV/A/"),
    ("call", 24, [(57, 4)], "K/AW/LF"),
    ("the", 28, [(52, 2)], "THV/UH/"),
    ("Ri-", 30, [(55, 4)], "R/AH>I/"),
    ("-sing", 34, [(52, 1), (50, 1)], "Z/I/NG"),
    ("Sun", 36, [(52, 5), (50, 1), (52, 2)], "S/UH1/N"),
    ("It's", 46, [(52, 2)], "/I/T S"),
    ("been", 48, [(57, 4)], "B/I/N"),
    ("the", 52, [(45, 2)], "THV/UH/"),
    ("ru-", 54, [(48, 2)], "R/U/"),
    ("-in", 56, [(48, 2)], "/I/N"),
    ("of", 58, [(50, 2)], "/UH/V"),
    ("ma-", 60, [(52, 1)], "M/AE/"),
    ("-ny", 61, [(52, 2)], "N/IE/"),
    ("a", 63, [(52, 1)], "/UH/"),
    ("poor", 64, [(48, 1), (47, 1)], "P/O/R"),
    ("girl", 66, [(45, 4)], "KV/ER/LF"),
    ("and", 70, [(52, 2)], "/AE/N D"),
    ("me", 72, [(57, 2)], "M/E/"),
    ("O", 74, [(55, 2)], "/OU/"),
    ("God", 76, [(52, 2)], "KV/AH/D"),
    ("for", 78, [(50, 4)], "F/AW/R"),
    ("one", 82, [(48, 1), (47, 1), (45, 10)], "W/UH1/N"),
]

VERSE_TWO = [
    ("Go", -2, [(40, 2)], "KV/OU/"),
    ("tell", 0, [(45, 4)], "T/EH/LF"),
    ("my", 4, [(47, 1), (45, 1)], "M/AH>I/"),
    ("ba-", 6, [(48, 4)], "B/A/"),
    ("-by", 10, [(50, 1), (51, 1)], "/IE/"),
    ("sis-", 12, [(52, 2.5), (55, .5), (52, 1)], "S/I/S"),
    ("-ter", 16, [(48, 1), (47, 1), (45, 4)], "T/ER/"),
    ("Ne-", 22, [(52, 2)], "N/EH/"),
    ("-ver", 24, [(57, 4)], "V/ER/"),
    ("do", 28, [(52, 2)], "D/U/"),
    ("like", 30, [(55, 4)], "L/AH>I/K"),
    ("I", 34, [(52, 1), (50, 1)], "/AH>I/"),
    ("have", 36, [(52, 3)], "HF/AE/V"),
    ("done", 39, [(52, 2), (55, 1), (52, 1), (50, 1)], "D/UH1/N"),
    ("To", 46, [(52, 2)], "T/U/"),
    ("shun", 48, [(57, 4)], "SCH/UH1/N"),
    ("that", 52, [(45, 2)], "THV/AE/T"),
    ("house", 54, [(48, 4)], "HF/AH>U/S"),
    ("in", 58, [(50, 2)], "/I/N"),
    ("New", 60, [(52, 3), (55, 1)], "N/IU/"),
    ("Or-", 64, [(48, 1), (47, 1)], "/AW/R"),
    ("-leans", 66, [(45, 4)], "L/E/N Z"),
    ("they", 70, [(52, 2)], "THV/A/"),
    ("call", 72, [(57, 3), (55, 1)], "K/AW/LF"),
    ("the", 76, [(52, 2)], "THV/UH/"),
    ("Ri-", 78, [(55, 2), (52, 2)], "R/AH>I/"),
    ("-sing", 82, [(48, 1), (47, 1)], "Z/I/NG"),
    ("Sun", 84, [(45, 10)], "S/UH1/N"),
]

SECTIONS = [
    ("intro", 0, 4), ("verse_1", 4, 20), ("verse_2", 20, 36),
    ("instrumental", 36, 44), ("reprise", 44, 52), ("coda", 52, 56),
]

def tick(eighths):
    return round(eighths * TICKS_PER_EIGHTH)


def hz(midi):
    return 440 * 2 ** ((midi - 69) / 12)


def consonant_ticks(label):
    return 7 if label in {"S", "Z", "SCH", "F", "TH", "THV", "HF"} else 5


def phone_intervals(start, end, spelling):
    """Allocate finite consonants and place the remaining duration in vowels."""
    onset, vowels, coda = spelling.split("/")
    heads, nuclei, tails = onset.split(), vowels.split(">"), coda.split()
    head_len = sum(consonant_ticks(p) for p in heads)
    tail_len = sum(consonant_ticks(p) for p in tails)
    if head_len + tail_len + 8 >= end - start:
        raise ValueError(f"Syllable is too short for {spelling}")
    cursor = start
    result = []
    for phone in heads:
        boundary = cursor + consonant_ticks(phone)
        result.append((cursor, boundary, phone, False))
        cursor = boundary
    vowel_end = end - tail_len
    if len(nuclei) == 1:
        result.append((cursor, vowel_end, nuclei[0], True))
    else:
        boundary = cursor + round((vowel_end - cursor) * .78)
        result.extend([(cursor, boundary, nuclei[0], True),
                       (boundary, vowel_end, nuclei[1], True)])
    cursor = vowel_end
    for phone in tails:
        boundary = cursor + consonant_ticks(phone)
        result.append((cursor, boundary, phone, False))
        cursor = boundary
    return result


def vocal_track():
    frames = {0: {"tick": 0, "phoneme": 0, "pitch_hz": hz(45 + TRANSPOSE), "amplitude": 0}}
    syllables, melody, phones = [], [], []
    stressed = {"house", "New", "call", "Ri-", "Sun", "been", "girl", "one",
                "tell", "sis-", "shun", "done", "God"}
    reprise = [(word, offset, list(notes), spelling) for word, offset, notes, spelling in VERSE_ONE[:14]]
    # The final statement answers the first one with a rising turn and a fall.
    reprise[-1] = ("Sun", 36, [(52, 3), (55, 1), (52, 2), (50, 1), (45, 1)], "S/UH1/N")
    for section, bar, words in [("verse_1", 4, VERSE_ONE),
                                ("verse_2", 20, VERSE_TWO),
                                ("reprise", 44, reprise)]:
        for word, offset, pitches, spelling in words:
            beginning = bar * 6 + offset
            start = tick(beginning)
            if word in {"call", "Sun", "girl", "done", "one"}:
                start += 2  # A small, deliberate behind-the-beat consonant.
            end = tick(beginning + sum(n[1] for n in pitches))
            # Leave a little breath at the end of long line-ending words.
            if word in {"Sun", "one", "done"}:
                end -= 8
            segments = []
            pos = beginning
            for midi, length in pitches:
                segments.append({"start_tick": max(start, tick(pos)),
                                 "end_tick": min(end, tick(pos + length)),
                                 "midi": midi + TRANSPOSE, "pitch_hz": round(hz(midi + TRANSPOSE), 6),
                                 "section": section, "syllable": word})
                pos += length
            melody.extend(segments)
            syllables.append({"text": word, "section": section,
                              "start_tick": start, "end_tick": end,
                              "start": start / TICK_HZ, "end": end / TICK_HZ,
                              "spelling": spelling, "notes": segments})
            for pstart, pend, phone, vowel in phone_intervals(start, end, spelling):
                dr, rate, _ = fit_duration((pend - pstart) / TICK_HZ)
                # Long vowels use a stable long interval; no artificial syllable
                # restarts are inserted when the melody or vibrato changes.
                sample_times = {pstart}
                sample_times.update(s["start_tick"] for s in segments
                                    if pstart < s["start_tick"] < pend)
                if vowel and pend - pstart > 35:
                    sample_times.update({pstart + 10, pend - 12})
                if vowel and pend - pstart > 50:
                    sample_times.update(range(pstart + 36, pend - 5, 8))
                for when in sorted(sample_times):
                    segment = next(s for s in segments
                                   if s["start_tick"] <= when < s["end_tick"])
                    pitch = segment["pitch_hz"]
                    # Shaped syllables, small onset scoops and delayed vibrato.
                    # Controls hold between these sparse updates; no vocal reset.
                    age, remaining = when - pstart, pend - when
                    cents = 0
                    if vowel and pend - pstart > 35 and age < 10:
                        cents = -22 * (1 - age / 10)
                    if vowel and age >= 36:
                        depth = 13 if section == "verse_1" else 20
                        cents += depth * math.sin(2 * math.pi * 4.7 * age / 100)
                    pitch *= 2 ** (cents / 1200)
                    peak = {"verse_1": 10, "verse_2": 11, "reprise": 12}[section]
                    peak = min(13, peak + int(word in stressed))
                    if section == "reprise" and offset < 10:
                        peak = 9  # A quiet return before the last build.
                    amp = peak if vowel else max(7, peak - 2)
                    if vowel and pend - pstart > 35 and age < 10:
                        amp = max(7, peak - 2)
                    if vowel and remaining <= 12:
                        amp = max(7, peak - 3)
                    tract = {"verse_1": 116, "verse_2": 122, "reprise": 126}[section]
                    if vowel and age < 10:
                        tract -= 4
                    frames[when] = {
                        "tick": when, "phoneme": SSI_PHONEMES[phone],
                        "pitch_hz": round(pitch, 6), "amplitude": amp,
                        "articulation": 5 if vowel else 7, "filter": tract,
                        "rate": rate, "duration": dr,
                        "retrigger": when == pstart,
                    }
                phones.append({"start_tick": pstart, "end_tick": pend,
                               "start": pstart / TICK_HZ, "end": pend / TICK_HZ,
                               "phoneme": SSI_PHONEMES[phone], "label": phone,
                               "vowel": vowel, "syllable": word,
                               "section": section})
            frames[end] = {"tick": end, "phoneme": 0,
                           "pitch_hz": segments[-1]["pitch_hz"], "amplitude": 0}
    frames[DURATION] = {"tick": DURATION, "phoneme": 0, "pitch_hz": hz(45 + TRANSPOSE),
                        "amplitude": 0}
    return {"chip": 0, "frames": [frames[t] for t in sorted(frames)]}, syllables, melody, phones


def accompaniment():
    return [dict(note, midi=note["midi"] + TRANSPOSE) for note in build_backing(tick)]


def varlen(value):
    data = [value & 0x7F]
    value >>= 7
    while value:
        data.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(data)


def write_changed(path, data):
    """Keep unchanged output timestamps so a rebuild need not rerender audio."""
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def write_midi(path, melody):
    # 100 pulses per quarter at 60 quarter notes/min: MIDI ticks equal score
    # ticks exactly. The musical dotted-quarter tempo is in cues.json.
    events = [(0, b"\xff\x51\x03\x0f\x42\x40")]
    for n in melody:
        events.extend([(n["start_tick"], bytes([0x90, n["midi"], 88])),
                       (n["end_tick"], bytes([0x80, n["midi"], 0]))])
    events.sort(key=lambda e: (e[0], e[1][0] != 0x80))
    track, previous = bytearray(), 0
    for when, data in events:
        track.extend(varlen(when - previous) + data)
        previous = when
    track.extend(varlen(DURATION - previous) + b"\xff\x2f\x00")
    write_changed(path, b"MThd" + struct.pack(">IHHH", 6, 0, 1, 100)
                  + b"MTrk" + struct.pack(">I", len(track)) + track)


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    voice, syllables, melody, phones = vocal_track()
    score = {"version": 1, "title": "House of the Rising Sun — Phasor No. 1, Blues-rock revision",
             "tick_hz": TICK_HZ, "duration_ticks": DURATION,
             "voices": [voice], "notes": accompaniment(), "percussion": percussion(tick)}
    for event in score["notes"] + score["percussion"]:
        if event["velocity"]:
            event["velocity"] = min(15, event["velocity"] + MUSIC_LEVEL_STEPS)
    validate_score(score)
    sections = [{"name": name, "start_bar": start, "end_bar": end,
                 "start_tick": tick(start * 6), "end_tick": tick(end * 6),
                 "start": tick(start * 6) / TICK_HZ,
                 "end": tick(end * 6) / TICK_HZ}
                for name, start, end in SECTIONS]
    cues = {"title": score["title"], "tick_hz": TICK_HZ,
            "duration_ticks": DURATION, "duration_seconds": DURATION / TICK_HZ,
            "key": "C minor", "meter": "6/8", "dotted_quarter_bpm": PULSE_BPM,
            "pickup_eighths": 2, "sections": sections,
            "lyrics": {
                "verse_1": ["There is a house in New Orleans,", "They call the Rising Sun.",
                            "It's been the ruin of many a poor girl,", "And me, O God, for one."],
                "verse_2": ["Go tell my baby sister,", "Never do like I have done.",
                            "To shun that house in New Orleans,", "They call the Rising Sun."],
                "reprise": ["There is a house in New Orleans,", "They call the Rising Sun."],
            }, "syllables": syllables, "melody": melody, "phones": phones,
            "chords": [{"bar": bar, "symbol": {"Am": "Cm", "Am/G": "Cm/Bb", "C": "Eb", "D": "F", "F": "Ab", "E7": "G7", "G": "Bb"}[chord], "start_tick": tick(bar * 6),
                        "end_tick": tick((bar + 1) * 6)} for bar, chord in enumerate(SONG_CHORDS)],
            "note": "The vocal pickup begins two eighth notes before each named vocal section; use syllable/phone timings for exact extraction."}
    for filename, data in [("score.json", score), ("cues.json", cues),
                           ("phonemes.json", [{k: p[k] for k in ("start", "end", "phoneme")} for p in phones])]:
        write_changed(output / filename, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    write_midi(output / "vocal-reference.mid", melody)
    print(f"{DURATION / TICK_HZ:.2f}s; {len(syllables)} syllables; {len(phones)} phones; "
          f"{len(voice['frames'])} vocal frames; {len(score['notes'])} AY note segments; "
          f"{len(score['percussion'])} drum hits")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE)
    build(parser.parse_args().out)
