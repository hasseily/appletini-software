# House of the Rising Sun — Phasor No. 1

A complete arrangement of the traditional song for Appletini One F1.2.4:
SSI-263 singing over AY bass, guitars, lead and drums. This **blues-rock revision**
runs **1 minute 42 seconds** in C minor at 66 dotted-quarter beats per minute.
The two verses develop different grooves, the instrumental solo climbs to a
climax, and a quiet reprise rebuilds into a stop-time ending. Vocal phrases have
varied endings, small scoops, delayed vibrato and shaped dynamics.
[Arrangement, lyrics and sources](ARRANGEMENT.md).

## Play on Appletini

Mount `player/build/RISING.SUN.hdv` as a bootable **SmartPort hard disk** and
boot it. It targets native Phasor in slot 4 on an enhanced Apple II with a
65C02, running firmware F1.2.4. NTSC starts automatically; press **P** for PAL,
**N** for NTSC, **R** to replay, **Space** to stop, or **Q/Escape** to quit.

The 28,333-byte song loads into RAM once. SmartPort speed affects
startup; playback has no disk reads. The disk contains both regional streams.
See the [player documentation](player/README.md) for memory layout and checks.

## Listen on a computer

For a **physical Phasor**, use the separate
[physical SSI-263 test disk](PHYSICAL_PHASOR.md). It corrects the filter-register
and pitch mapping exposed by the first hardware recording. Build it with
`make -C player physical check-physical`; `player/build/physical/RISING.SUN.hdv`
starts in PAL and also includes NTSC. Its corrected sound still needs a hardware
audition; the Appletini preview below does not simulate the real analog chip.

`build/house-of-the-rising-sun.mp3` is the listening preview.
`build/house-of-the-rising-sun.wav` preserves the unnormalized firmware-model
mix; `build/vocals.wav` and `build/backing.wav` hold the separate stems.
These are generated artifacts, supplied in the release bundle or rebuilt below.

The preview runs the actual pinned SSI and AY RTL, with the firmware's default
AY pan and AY8913 volume mode. It uses neutral tone controls, including
**warmth 0**; the board's default warmth +8 sounds different. It excludes the
final DAC path and tiny mixer-pipeline delays. No recording of a human singer
or other instrument is mixed into it.

## Rebuild or edit

From this directory, install the sibling framework's audio dependencies and
have Verilator, a C++ compiler, GNU make 4.3+, ffmpeg and cc65 available:

```sh
python3 -m pip install -e '../song_to_phasor[audio]'
make streams disk
make preview
python3 -m pip install py65
make check
```

`APPLETINI_ROOT` selects the firmware checkout; `CACHE` selects the shared
Verilator cache. `CA65` and `LD65` may select cc65 binaries outside PATH.
The full RTL render takes several minutes; later unchanged builds reuse the
WAV. Rebuilding only the score, register streams and disk takes seconds.

Edit `arrangement.py` for the singer, `backing.py` for instrumental parts, or
`percussion.py` for the native AY kick, snare and hi-hat, then run `make`.
The generator also writes `cues.json`, timed `phonemes.json`, and
`vocal-reference.mid` for independent review. Generated `score.json` can be
edited directly and compiled with the framework; a later regeneration replaces
those edits. The two regional PHS1 streams have the same timing but different
AY tuning words and must be played with their matching regional timer.

## What is checked

The player checks execute the assembled 65C02 code through the whole song,
comparing every register write and timestamp, and verify the ProDOS image's
contents. `verify_render.py` measures sustained vocal pitch against the score,
reports voiced coverage, duration and sample peaks, and checks that the vocal
releases at the end. It does not shift the audio to hide timing errors.

The SSI performance is an initial phonetic interpretation. Acoustic checks
cannot establish that every word is intelligible. Physical Appletini playback
and a full ROM-level boot remain to be tested; the preview is firmware
simulation. See `build/audio-validation.json` and `player/build/validation.json`
for measured results, or the checked-in [validation summary](VALIDATION.md).
