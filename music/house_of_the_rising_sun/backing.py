"""Original 6/8 blues-rock arrangement for nine native AY tone channels.

All source times are eighth notes; ``tick`` is supplied by arrangement.py.
The musical development is deliberately written as phrases, not randomized
ornaments: the small rising intro cell becomes a higher, syncopated solo,
then the band drops out before the last vocal statement and final cadence.
The other three channels (9..11) belong exclusively to the drum part.
"""

from __future__ import annotations


CHORDS = {
    "Am": (33, [57, 60, 64]),
    "Am/G": (31, [57, 60, 64]),
    "C": (36, [55, 60, 64]),
    "D": (38, [57, 62, 66]),
    "F": (29, [57, 60, 65]),
    "E7": (28, [56, 59, 62]),
}
HARMONY = [
    "Am", "C", "D", "F", "Am", "C", "E7", "E7",
    "Am", "C", "D", "F", "Am", "E7", "Am", "E7",
]
SONG_CHORDS = (
    ["Am", "Am/G", "F", "E7"] + HARMONY + HARMONY
    + HARMONY[:8] + HARMONY[:8] + ["Am", "F", "E7", "Am"]
)

# Position, length, pitch: an original answer to the traditional vocal tune.
# The opening E -> A -> C leap is restated higher and extended in the solo.
INTRO_LEAD = {
    0: [(0, .7, 76), (1, 1.3, 69), (2.5, .4, 71),
        (3, 1.3, 72), (4.5, .45, 74), (5, .8, 76)],
    1: [(.5, 1.2, 79), (2, .7, 76), (3, .7, 74),
        (4, .7, 72), (5, .6, 69)],
    2: [(0, 1.4, 77), (1.5, .4, 76), (2, .7, 72),
        (3.5, .7, 69), (4.5, .4, 72), (5, .7, 71)],
    3: [(0, .6, 68), (1, .6, 71), (2, .7, 74), (3, .65, 76)],
}
SOLO_LEAD = {
    36: [(0, .7, 76), (1, 1.25, 69), (2.5, .35, 72),
         (3, .8, 74), (4, .35, 75), (4.5, 1.25, 76)],
    37: [(.5, .7, 79), (1.5, .7, 76), (2.5, .4, 74),
         (3, 1.35, 72), (4.5, .4, 74), (5, .75, 76)],
    38: [(0, 1.25, 78), (1.5, .4, 76), (2, .7, 74),
         (3, .7, 78), (4, .7, 81), (5, .7, 78)],
    39: [(0, 1.7, 77), (2, .7, 76), (3, .7, 74),
         (4, .45, 72), (4.5, .45, 71), (5, .75, 69)],
    40: [(.5, .65, 76), (1.5, 1.8, 81), (3.5, .4, 79),
         (4, .7, 76), (5, .35, 74), (5.5, .35, 72)],
    41: [(0, .7, 76), (1, .4, 79), (1.5, 1.25, 81),
         (3, .4, 79), (3.5, .4, 76), (4, .7, 74), (5, .75, 72)],
    42: [(.5, .4, 74), (1, .75, 76), (2, 1.2, 80),
         (3.5, .4, 78), (4, .4, 76), (4.5, .4, 74), (5, .75, 71)],
    43: [(0, .65, 76), (.75, .45, 74), (1.5, .45, 71),
         (2.25, .45, 68), (3, .65, 64)],
}


def accompaniment(tick, song_chords=None):
    """Return nonoverlapping score notes, shaped for AY logarithmic volumes.

    Bass has one attack plus a lower sustain. Plucked chord strings decay in
    two steps; lead phrases use three, occasionally approaching a long note
    from below. These are real register-level pitch/volume articulations.
    """
    chords = SONG_CHORDS if song_chords is None else song_chords
    if len(chords) != 56:
        raise ValueError("the arrangement requires its 56-bar form")
    notes = []

    def emit(start, end, midi, velocity, voice):
        if end > start:
            notes.append({"start_tick": start, "end_tick": end,
                          "midi": midi, "velocity": velocity, "voice": voice})

    def shaped(pos, length, midi, volume, voice, kind="pluck", bend=False):
        start, end = tick(pos), tick(pos + length)
        if end <= start:
            return
        if kind == "lead":
            # A short pickup scoop is used only on sustained phrase accents.
            attack = min(end, start + 5)
            release = max(attack, start + round((end - start) * .73))
            emit(start, attack, midi - .38 if bend else midi, volume, voice)
            emit(attack, release, midi, volume - 1, voice)
            emit(release, end, midi, volume - 3, voice)
        elif kind == "bass":
            attack = min(end, start + 7)
            emit(start, attack, midi, volume, voice)
            emit(attack, end, midi, volume - 1, voice)
        else:
            attack = min(end, start + 5)
            emit(start, attack, midi, volume, voice)
            emit(attack, end, midi, max(1, volume - 3), voice)

    def chord_stroke(bar, beat, triad, volume, duration=.7):
        # Slightly spread attacks make a strum instead of a static organ pad.
        for voice, midi, delay in [(2, triad[0], 0), (5, triad[1], .07),
                                   (8, triad[2], .13)]:
            shaped(bar * 6 + beat + delay, duration - delay,
                   midi, volume, voice)

    def lead_phrase(bar, phrase, volume, voice=6):
        for beat, length, midi in phrase:
            shaped(bar * 6 + beat, length, midi, volume, voice, "lead",
                   bend=length >= 1.2)

    for bar, chord in enumerate(chords):
        root, triad = CHORDS[chord]
        nxt = CHORDS[chords[min(bar + 1, 55)]][0]
        intro = bar < 4
        verse_one = 4 <= bar < 20
        verse_two = 20 <= bar < 36
        solo = 36 <= bar < 44
        breakdown = bar in (44, 45)
        final_vocal = 46 <= bar < 52

        if bar == 55:
            # Final major-scale tension resolves to an unambiguous minor triad.
            # Long stepped releases are audible on the card; no DSP fade needed.
            for voice, midi, level in [(0, 33, 13), (1, 57, 11), (4, 64, 11),
                                       (2, 60, 10), (5, 69, 10), (6, 76, 12)]:
                for a, b, drop in [(0, .3, 0), (.3, 1.6, 2),
                                   (1.6, 3.2, 4), (3.2, 5, 7)]:
                    emit(tick(bar * 6 + a), tick(bar * 6 + b),
                         midi, level - drop, voice)
            continue

        bass_level = 11 if intro or verse_one or breakdown else 12
        if bar == 54:
            bass_pattern = [(0, root, 1.25), (3, root + 12, .75)]
        elif breakdown:
            bass_pattern = [(0, root, 2.25)]
        elif intro and bar < 2:
            bass_pattern = [(0, root, 2.3), (3, root + 12, 1.9)]
        elif verse_one and bar < 12:
            bass_pattern = [(0, root, 2.3), (3, root + 7, 1.5),
                            (5, nxt - 1, .72)]
        else:
            # A root, octave/fifth answer and chromatic approach form a moving
            # bass line. Every fourth bar breaks into a short turnaround.
            fifth = root + 7 if chord != "Am/G" else 40
            if bar % 4 == 3 and bar not in (3, 43, 51):
                bass_pattern = [(0, root, 1.6), (2, fifth, .7),
                                (3, root + 12, .9), (4.5, nxt + 1, .35),
                                (5, nxt - 1, .65)]
            else:
                bass_pattern = [(0, root, 2), (2.5, root + 12, .35),
                                (3, fifth, 1.4), (5, nxt - 1, .65)]
        for beat, midi, length in bass_pattern:
            shaped(bar * 6 + beat, length, midi, bass_level, 0, "bass")

        if breakdown:
            # Keep the returning first lyric almost naked; do not run the same
            # arpeggio through every section of the performance.
            pattern = [(0, 0, 1, 1.4), (3.5, 2, 4, 1.2)]
        elif bar == 54:
            pattern = []
        elif verse_two:
            # A loping syncopated answer, with an audible gap around beat 3.
            pattern = [(.15, 0, 1, .8), (1.5, 2, 4, .65),
                       (2.5, 1, 1, .4), (4, 2, 4, .65),
                       (5.15, 1, 1, .5)]
        elif solo:
            # The lead needs space; harmony strokes replace busy high figures.
            pattern = [(0, 0, 1, 1), (1.5, 2, 4, .7),
                       (3, 1, 1, .7), (4.5, 2, 4, .7)]
        elif final_vocal or bar >= 52:
            pattern = [(0, 0, 1, .6), (1, 2, 4, .6), (2, 1, 1, .65),
                       (3, 0, 4, .65), (4, 1, 1, .6), (5, 2, 4, .6)]
        else:
            # Two different contours exchange between the strings each bar.
            pattern = ([(0, 0, 1, .8), (1, 2, 4, .7), (2, 1, 1, .75),
                        (3, 2, 4, .8), (4, 1, 1, .65), (5, 0, 4, .65)]
                       if bar % 2 == 0 else
                       [(0, 0, 1, .8), (1, 1, 4, .75), (2, 2, 1, .75),
                        (3, 1, 4, .8), (4.25, 2, 1, .6), (5, 1, 4, .65)])
        arp_level = 10 if intro or verse_one or breakdown else 11
        for beat, tone, voice, length in pattern:
            # Alternate position keeps harmony audible without doubling the
            # singer's melody in lockstep for the full song.
            midi = triad[tone] + (12 if voice == 4 else 0)
            shaped(bar * 6 + beat, length, midi, arp_level, voice)

        if bar == 54:
            chord_stroke(bar, 0, triad, 12, 1.3)
            chord_stroke(bar, 3, triad, 12, .8)
        elif verse_two:
            chord_stroke(bar, 3.15, triad, 9, .65)
        elif solo or bar in (48, 49, 50, 51, 52, 53):
            chord_stroke(bar, .05, triad, 9, .8)
            chord_stroke(bar, 3.1, triad, 10, .7)
        elif bar in (14, 16, 18, 46, 47):
            chord_stroke(bar, 3.15, triad, 9, .8)

    for bar, phrase in INTRO_LEAD.items():
        lead_phrase(bar, phrase, 12)
    for bar, phrase in SOLO_LEAD.items():
        lead_phrase(bar, phrase, 13)

    # Brief answers occupy actual breath gaps (after "Sun" / "done") rather
    # than competing with the singer. The second response changes direction.
    lead_phrase(11, [(2.15, .42, 71), (2.7, .42, 74), (3.25, .4, 76)], 11)
    lead_phrase(27, [(2.15, .42, 76), (2.7, .42, 74), (3.25, .4, 71)], 12)
    lead_phrase(51, [(2.15, .42, 76), (2.7, .42, 74), (3.25, .4, 71),
                    (4, .7, 68), (5, .65, 64)], 12)

    # Two short harmony answers mark the solo's peak; no continuous pad.
    lead_phrase(39, [(0, 1.7, 72), (2, .7, 69)], 10, 7)
    lead_phrase(40, [(1.5, 1.8, 76)], 11, 7)
    lead_phrase(41, [(1.5, 1.25, 76)], 11, 7)

    # Coda expands the intro cell, descends, stops, and lands on the last Am.
    lead_phrase(52, [(0, .7, 76), (1, .7, 79), (2, 1.3, 81),
                    (3.5, .4, 79), (4, .7, 76), (5, .7, 72)], 13)
    lead_phrase(53, [(0, 1.2, 77), (1.5, .4, 76), (2, .7, 74),
                    (3, .7, 72), (4, .7, 69), (5, .6, 65)], 13)
    lead_phrase(54, [(0, 1.2, 68), (3, .75, 71)], 13)

    notes.sort(key=lambda note: (note["start_tick"], note["voice"]))
    ends = {}
    for note in notes:
        voice = note["voice"]
        if note["start_tick"] < ends.get(voice, 0):
            raise ValueError(f"overlapping backing phrase on voice {voice}")
        ends[voice] = note["end_tick"]
    return notes
