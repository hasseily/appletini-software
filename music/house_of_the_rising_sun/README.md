# House of the Rising Sun — Phasor No. 1

A complete arrangement of the traditional song for the Phasor in Appletini One
F1.2.5 or later, or a real Phasor card: SSI-263 singing over AY bass, guitars,
lead and drums. This **blues-rock revision**
runs **1 minute 42 seconds** in C minor at 66 dotted-quarter beats per minute.
The two verses develop different grooves, the instrumental solo climbs to a
climax, and a quiet reprise rebuilds into a stop-time ending. Vocal phrases have
varied endings, small scoops, delayed vibrato and shaped dynamics.
[Arrangement, lyrics and sources](ARRANGEMENT.md).

## Play on Appletini

Mount `player/build/RISING.SUN.hdv` as a bootable **SmartPort hard disk** and
boot it. It targets native Phasor in slot 4 on an enhanced Apple II with a
65C02, running firmware F1.2.5 or later; it also plays on a real Phasor in
slot 4. PAL starts automatically; press **P** for PAL, **N** for NTSC, **R** to
replay, **Space** to stop, or **Q/Escape** to quit. The same player is on the
[Appletini demo disk](../../demos/appletini_demos/README.md).

The song (27,956 bytes PAL, 28,159 bytes NTSC) loads into RAM once. SmartPort
speed affects startup; playback has no disk reads. The disk contains both
regional streams. See the [player documentation](player/README.md) for memory
layout and checks.

## Speech registers and F1.2.5

The speech streams use the song framework's `physical-ssi263` profile, which
writes pitch and filter registers by the SSI-263 datasheet. F1.2.5's native
SSI-263 model follows the same datasheet, so Appletini and a real card get the
same stream. Earlier builds targeted F1.2.4's speech model and sound wrong on
F1.2.5: their filter bytes select a much lower filter clock there.
[Why, and how the score is translated](SSI263_MAPPING.md).

## Listen on a computer

This directory no longer builds a listening preview. Its old preview came from
the F1.2.4 speech RTL and does not match F1.2.5. appletini-one's
`scripts/render_ssi263_song.py` renders this song through the F1.2.5 native
SSI model, PAL by default (`--region ntsc` for NTSC); see that repository's
`docs/SSI263_SONG_PREVIEW.md`. It is a model of the chip, not the card's
analog output.

## Rebuild or edit

From this directory, with Python 3, GNU make 4.3+ and cc65 available:

```sh
make streams disk
python3 -m pip install py65
make check
```

`CA65` and `LD65` may select cc65 binaries outside PATH. Rebuilding the
score, register streams and disk takes seconds; no firmware checkout or
Verilator is needed.

Edit `arrangement.py` for the singer, `backing.py` for instrumental parts, or
`percussion.py` for the native AY kick, snare and hi-hat, then run `make`.
The generator also writes `cues.json`, timed `phonemes.json`, and
`vocal-reference.mid` for independent review. Generated `score.json` can be
edited directly and compiled with the framework; a later regeneration replaces
those edits. The two regional PHS1 streams have the same timing but different
AY tuning words and SSI register values, and must be played with their
matching regional timer.

## What is checked

The player checks execute the assembled 65C02 code through the whole song,
comparing every register write and timestamp, and verify the ProDOS image's
contents. See `player/build/validation.json` for measured results, or the
checked-in [validation summary](VALIDATION.md).

The SSI performance is an initial phonetic interpretation. Nothing here
establishes that every word is intelligible. Playback on F1.2.5 hardware and a
full ROM-level boot remain to be tested.
