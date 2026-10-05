"""An original, section-shaped 6/8 groove for the second Phasor arrangement.

``percussion(tick)`` accepts the arrangement's eighth-note-to-tick function.
The resulting score events use the compiler's dedicated AY3 kit: a falling
tone kick and two independently gated channels of shared AY noise. These are
synthesized drums, not samples. Tone parts must leave voices 9..11 free.
"""


def percussion(tick):
    hits = []

    def hit(bar, beat, kind, velocity, length=None):
        if length is None:
            length = {"kick": .42, "snare": .48, "hat": .14}[kind]
        start = tick(bar * 6 + beat)
        end = max(start + 1, tick(bar * 6 + beat + length))
        hits.append({"start_tick": start, "end_tick": end,
                     "kind": kind, "velocity": velocity})

    for bar in range(56):
        # Let the introduction and first vocal pickup breathe.
        if bar < 2:
            continue
        if bar < 4:
            for beat in (0, 3):
                hit(bar, beat, "hat", 8)
            if bar == 3:
                hit(bar, 3, "kick", 9)
            continue

        # Pull right back for the vocal return; the earlier solo's density
        # makes this space part of the arrangement's dynamic arc.
        if bar in (44, 45):
            hit(bar, 0, "kick", 10)
            hit(bar, 3, "hat", 8)
            continue

        # Two stop-time hits, then silence before the final tonic.
        if bar == 54:
            for beat in (0, 3):
                hit(bar, beat, "kick", 12)
                hit(bar, beat, "snare", 11, .35)
                hit(bar, beat, "hat", 10, .35)
            continue
        if bar == 55:
            hit(bar, 0, "kick", 12)
            hit(bar, 0, "hat", 12, 1.2)
            continue

        quiet = bar < 20
        building = bar in (46, 47)
        solo = 36 <= bar < 44
        reprise = 48 <= bar < 52
        full = solo or reprise
        # Eighth-note accents group as 3+3. The sparser verse pattern leaves
        # real holes instead of playing the same loop beneath every phrase.
        hats = (0, 2, 3, 5) if not full else (0, 1, 2, 3, 4, 5)
        if quiet and bar % 4 == 2:
            hats = (0, 3, 5)
        for beat in hats:
            accent = 1 if beat in (0, 3) else 0
            hit(bar, beat, "hat", (8 if quiet or building else 9) + accent)
        hit(bar, 0, "kick", 10 if quiet else 12)
        # A small pickup changes the bass-drum pattern every other bar.
        if not quiet and bar % 2 == 1 and bar != 53:
            hit(bar, 4.5, "kick", 10)
        elif quiet and bar % 4 == 3:
            hit(bar, 5, "kick", 9)
        hit(bar, 3, "snare", 9 if quiet else 12)

        # Short fills answer four-bar phrases, with a bigger lift into the
        # instrumental. The final 16th-like strokes stay below the sung lead.
        if bar in (11, 19, 27, 35, 43, 47, 51, 53):
            fill = [(4.5, 9), (5.25, 10)]
            if bar in (35, 43, 51):
                fill = [(4, 9), (4.75, 10), (5.5, 12)]
            for beat, velocity in fill:
                hit(bar, beat, "snare", velocity, .30)

    return sorted(hits, key=lambda event: (event["start_tick"], event["kind"]))
