# Music of DOOM on the Phasor: host tools (milestone S1)

These tools turn the WAD's MUS songs into a compact stream of AY voice
commands for the Phasor, model the 65C02 player that will play it, and
render the result to WAV files to listen to before any 65C02 code
exists. They implement milestone S1 of [`docs/NATIVE.md`](../../docs/NATIVE.md)
section 13, from the design in
[`docs/research/native-sound.md`](../../docs/research/native-sound.md).

The source is the WAD's `D_*` MUS lumps and its `GENMIDI` bank, never
upstream's DOC song units or its SoundFont converter. All the code here is
original, written from the published MUS, MIDI, WAD and GENMIDI layouts and
from the Appletini's HDL of the Phasor. Standard library only, Python 3.9
to 3.14.

## Commands

From `demos/doom_gs`, after `python3 tools/fetch_upstream.py` (which puts
`DOOM1.WAD` in `build/upstream/data/`):

```
python3 tools/sound/mus.py                        # the songs of the WAD
python3 tools/sound/report.py --render            # tables, song files, WAVs
python3 tools/sound/report.py --update-readme     # the tables below
python3 -m unittest discover -s tests -p 'test_sound_*.py'
```

`report.py --render` writes, for each of the 13 songs, in `build/sound/`:
`SONG.wav` (native mode, PAL, stereo with the menu's default pans, the
first 60 s or the whole song and one second of release, 44,100 Hz),
`SONG.native12.ay` and `SONG.mb6.ay` (song files). It takes about 11 s on
8 cores.

One song at a time:

```
python3 tools/sound/mus2ay.py D_E1M1 --out build/sound          # song file
python3 tools/sound/player.py build/sound/D_E1M1.native12.ay \
        --seconds 60 --log build/sound/D_E1M1.log              # AY writes
python3 tools/sound/ayrender.py build/sound/D_E1M1.log \
        build/sound/D_E1M1.wav --seconds 60                     # WAV
python3 tools/sound/mus2mid.py D_E1M1 build/sound/D_E1M1.mid    # MIDI
```

| Module | What |
| --- | --- |
| `mus.py` | WAD directory, upstream's song list, the MUS parser (first decoder) |
| `mus2mid.py`, `midi.py` | The second decoder: MUS to a standard MIDI file, and a MIDI reader. It shares no MUS-reading code with `mus.py` |
| `genmidi.py` | GENMIDI: carrier envelope, level, note offset, fixed note |
| `tables.py` | Machines, clocks, voice layouts, period, bend, level and volume tables, tempo |
| `mus2ay.py` | The converter: MUS to a song file |
| `player.py` | The model of the 65C02 player: the specification and S2's oracle |
| `ayrender.py` | AY register writes to WAV, after the card's YM2149 core and mixer |
| `report.py` | All songs: the tables below, song files and WAVs |

## Facts checked in the HDL

`FW/` is the Appletini firmware snapshot (`appletini-one-main`).

- **PSG clock.** The YM2149 cores get one clock enable an Apple bus cycle
  (`data_en`), plus a second one in Phasor native mode:
  `FW/hdl/apple/mockingboard.sv:262` (`psg_clock = via_bus_clock ||
  psg_ce_extra_q`) and `:542-549` ("The Phasor native mode doubles the
  PSG clock"). So the PSG clock is 2 x the bus clock in native mode and
  the bus clock in Mockingboard mode. The bus clock is 1,015,625 Hz on a
  PAL //e and 1,020,484 Hz on an NTSC //e: native mode is 2,031,250 Hz
  (PAL) or 2,040,968 Hz (NTSC). The Bilestoad's 2 x 1,020,484 Hz
  (`demos/bilestoad/tools/make_music.py:22`) is the NTSC native figure;
  the owner's PAL machine is 0.5% (8 cents) lower, so the player picks a
  period table at boot.
- **Tone, noise, envelope.** A /8 prescaler (`FW/hdl/apple/YM2149.sv:139-162`);
  tone f = clock / (16 P) (`:203-226`), P = 0 holds the output at the
  mixer bit, which silences a channel whose tone is on (`:218-220`);
  noise steps every 16 x NP clocks (`:169-195`); the envelope steps every
  8 x EP clocks over 32 levels (`:230-342`).
- **The noise LFSR is not the AY's.** The core shifts in bit0 ^ bit2
  (`YM2149.sv:187`); that sequence repeats after 114,681 steps, where the
  AY-3-8910's bit0 ^ bit3 gives the maximal 131,071 (both measured by
  `ayrender.lfsr_period`). Noise still sounds like noise; the renderer
  models the card.
- **Levels.** The Phasor's default is the AY-3-8913 volume table
  (`FW/ps_sources/frontend/config_menu_phasor.c:186`), `YM2149.sv:389-420`
  at entry 32 + 2n: 0, 3, 4, 6, 10, 15, 21, 34, 40, 65, 91, 114, 144, 181,
  215, 255.
- **Mix and pans.** Each channel is scaled by its menu pan (defaults 11
  and 5 alternating, `config_menu_phasor.c:9-14`; pan 11 is left 9/16,
  right 16/16, pan 5 left 16/16, right 10/16), the 12 channels are summed
  and a sum of 2048 or more saturates (`mockingboard.sv:316-378`, `:500-505`).
  The pan word runs psg0 (VIA-A first AY), psg1 (VIA-B first AY), psg2,
  psg3, so with the drivers' chip numbers the pans are: chips 0 and 1
  (VIA-A) 11, 5, 11; chips 2 and 3 (VIA-B) 5, 11, 5.
- **Addressing.** As the Bilestoad, Bosconian and Pinball drivers do
  (`demos/bilestoad/src/sound.s:1-17,150-185`,
  `demos/appletini_bosconian/sound_io.s:1-22,101-134`,
  `demos/pinball_construction_set/src/sound.s:58-68`): `$C0C8` then `$C0C5`
  for native mode; VIA-A at `$C41x`, VIA-B at `$C48x`; ORB `$0F/$17`
  latch, `$0E/$16` write, `$0C/$14` idle for the first/second AY of a VIA;
  data through ORA without handshake. Chips 0 and 1 are the first and
  second AY behind VIA-A, 2 and 3 behind VIA-B; in Mockingboard mode only
  0 and 2 exist. The tools use these chip numbers.

## Voice layouts

| Layout | Melodic voices (0-) | Drum voices | Left for effects |
| --- | --- | --- | --- |
| native12 (native mode) | chip 0 A, B, C; chip 1 A, B; chip 2 A, B (7) | chip 1 C, chip 2 C (2) | chip 3 A, B, C |
| mb6 (fallback, Mockingboard mode) | chip 0 A, B; chip 2 A (3) | chip 0 C (1) | chip 2 B, C |

A drum voice owns its chip's noise period (R6) and envelope (R11-R13).
Voice numbers in the stream are the melodic voices, then the drums.

## The song file

All numbers little-endian.

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | format version, 1 |
| 1 | 1 | layout: 0 native12, 1 mb6 |
| 2 | 1 | NE, envelopes |
| 3 | 1 | ND, drum recipes |
| 4 | 2 | stream length |
| 6 | 2 | loop offset in the stream (0: the start) |
| 8 | 8 NE | envelopes: attack step (2), decay step (2), release step (2), sustain (1), flags (1: bit 0 = the level holds while the key is down) |
| | 6 ND | drum recipes: tone note (1, 0 none), noise period (1, 0 none), envelope period for a loud hit (2, at the layout's PAL PSG clock), soft decay step (2) |
| | length | the stream |

Steps are in 1/256 of an attenuation unit a tick; an attenuation unit is
0.5 dB and 80 (40 dB) is silent. A tick is 1/140 s, the MUS unit.

### The stream

A command byte has the command in its high nibble and the voice in its low
nibble.

| Bytes | Command |
| --- | --- |
| `$0v nn` | note on, note nn; the voice keeps its attenuation and envelope |
| `$1v nn aa` | note on with attenuation aa (0-80) |
| `$2v nn aa ee` | note on with attenuation and envelope ee |
| `$3v` | note off: the release starts |
| `$4v aa` | attenuation of the voice |
| `$5v bb` | pitch bend of the voice, the MUS byte (128 none, +-2 semitones) |
| `$6v dd aa` | drum hit: recipe dd, attenuation aa |
| `$7v` | cut: the voice (melodic or drum) is silent at once, its envelope idle and a latched drum hit dropped |
| `$81`-`$FE` | wait 1-126 ticks |
| `$FF` | end: stop, or go to the loop offset |

`$80` is invalid. The converter sends a voice's bend with its first note,
since its state is unknown at the start and after a loop. A bend changes
the note's period P by (P x M[bb] + 1024) >> 11, where M[bb] =
|2^(-(bb - 128)/768) - 1| x 2048 rounded (a byte, at most 251): the
product is up to 20 bits, so the 65C02 needs 3 bytes for it, and the
added 1024 rounds to the nearest period. `$7v` is only sent for MUS
system event 10 (all sounds off), which the WAD's songs do not use.
The tables below give each song's size and bytes a second of music (44
to 165). All 13 songs are 135,903 bytes of stream (137,151 bytes
of song files) in native12 and 125,815 in mb6, against 245,179 bytes of
MUS.

### The player

`player.py` is the specification; its docstring lists the state. Each
mouse-card VBL interrupt:

1. A note that started and ended in the last interrupt starts its release
   now (every note is heard for at least one interrupt); the voice flags
   are cleared.
2. Tempo: add TEMPO_FRAC to a 16-bit fraction; run TEMPO_INT ticks plus
   the carry. PAL: 2 + 52,135/65,536 ticks an interrupt (2.795520, the
   exact 140 Hz x 20,280 cycles / 1,015,625 Hz); NTSC: 2 + 22,043/65,536.
3. Each tick: the stream commands due, then every envelope one step
   (attack down to 0, decay up to the sustain level, then hold or, for a
   percussive program, release; release up to silence). An attack starts
   from the voice's current level, as an OPL key-on does. A drum hit is
   latched: the last hit of a drum voice in an interrupt is the one that
   sounds.
4. Compose: latched drum hits start (tone, noise, mixer; a hit of
   attenuation 12 or less, with the music volume, uses the chip's
   envelope, shape `\___`; a quieter one decays in software from full);
   each voice's level is LEVEL[min(80, note attenuation + envelope + music
   attenuation)].
5. Burst: for chips in ascending order and their owned registers in
   ascending order, write each register that differs from the shadow, and
   R13 when a hit restarted the envelope.

The first burst (`Player.reset`) writes R0-R12 of every chip of the layout:
periods and levels 0, mixer `$38`. The 65C02 player must produce the same
writes in the same order after every interrupt; S2 compares them.

## Report

The figures come from `python3 tools/sound/report.py --update-readme`,
run on 2026-09-30. Each song is played once to its end (no loop) plus one
second. "Writes/interrupt" is over all interrupts; "p99 of bursts" over the
interrupts that write something (the design report's measure). Costs use
native-sound.md 2.3: on F1.2.1, 504 us a burst and 40.4 us a write; with
the proposed FW-S1, 8.4 us a write.

<!-- report:begin (python3 tools/sound/report.py --update-readme) -->
Native mode, 12 voices (7 melodic, 2 drums, 3 effects left free), PAL //e: interrupts at 50.080 Hz, 2 or 3 MUS ticks each.

| Song | MUS bytes | Seconds | Events | Notes | Drum hits | Voices used (most held) | Steals | Drum steals | Release cuts | Stream bytes | Stream B/s | File bytes | Writes/s | Writes/interrupt mean | p99 | p99 of bursts | Max | F1.2.1 ms/s | FW-S1 ms/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| D_E1M1 | 17283 | 96.0 | 5826 | 1630 | 702 | 7 (5) | 0 | 133 | 40 | 15868 | 165 | 15972 | 122 | 2.43 | 15 | 16 | 25 | 23.3 | 1.02 |
| D_E1M2 | 36776 | 155.4 | 10847 | 804 | 1232 | 7 (7) | 8 | 276 | 670 | 12790 | 82 | 12868 | 87 | 1.73 | 11 | 12 | 20 | 21.9 | 0.73 |
| D_E1M3 | 19276 | 272.0 | 7507 | 2341 | 1408 | 7 (4) | 0 | 5 | 2259 | 13976 | 51 | 14030 | 92 | 1.84 | 9 | 9 | 19 | 24.3 | 0.77 |
| D_E1M4 | 18216 | 170.7 | 6270 | 1895 | 1210 | 7 (6) | 0 | 92 | 279 | 12976 | 76 | 13100 | 111 | 2.21 | 18 | 19 | 23 | 23.8 | 0.93 |
| D_E1M5 | 9830 | 164.0 | 3270 | 1460 | 4 | 7 (6) | 0 | 0 | 1447 | 7224 | 44 | 7262 | 47 | 0.93 | 9 | 10 | 17 | 12.8 | 0.39 |
| D_E1M6 | 9456 | 84.0 | 3332 | 1071 | 554 | 7 (5) | 0 | 32 | 1018 | 7132 | 85 | 7280 | 138 | 2.76 | 14 | 15 | 20 | 27.0 | 1.16 |
| D_E1M7 | 8591 | 150.9 | 2835 | 1110 | 226 | 7 (7) | 0 | 4 | 1093 | 6742 | 45 | 6838 | 49 | 0.97 | 7 | 7 | 23 | 15.7 | 0.41 |
| D_E1M8 | 59535 | 152.0 | 18113 | 355 | 522 | 7 (6) | 0 | 43 | 151 | 9560 | 63 | 9642 | 41 | 0.82 | 8 | 11 | 19 | 11.0 | 0.35 |
| D_E1M9 | 21266 | 137.4 | 7766 | 2620 | 1185 | 7 (7) | 2 | 272 | 1678 | 15798 | 115 | 15920 | 120 | 2.40 | 20 | 21 | 27 | 22.0 | 1.01 |
| D_INTER | 29082 | 201.4 | 9884 | 3250 | 1682 | 7 (7) | 52 | 212 | 1312 | 22210 | 110 | 22352 | 118 | 2.35 | 18 | 19 | 26 | 23.9 | 0.99 |
| D_INTRO | 1485 | 6.9 | 498 | 60 | 50 | 7 (7) | 7 | 4 | 46 | 636 | 93 | 740 | 57 | 1.13 | 9 | 12 | 33 | 15.4 | 0.48 |
| D_VICTOR | 13752 | 192.0 | 4532 | 1506 | 748 | 7 (7) | 3 | 60 | 1482 | 10553 | 55 | 10649 | 75 | 1.49 | 11 | 13 | 20 | 19.7 | 0.63 |
| D_INTROA | 631 | 6.9 | 214 | 10 | 48 | 7 (7) | 0 | 0 | 0 | 438 | 64 | 498 | 56 | 1.11 | 5 | 6 | 33 | 14.8 | 0.47 |
| All | 245179 | | | | | | | | | 135903 | | 137151 | | | | | | | |

NTSC //e (59.923 Hz), native mode: writes/s and p99 of bursts per song: D_E1M1 124/16, D_E1M2 91/11, D_E1M3 94/9, D_E1M4 112/18, D_E1M5 48/10, D_E1M6 146/15, D_E1M7 51/7, D_E1M8 42/11, D_E1M9 125/21, D_INTER 123/18, D_INTRO 60/12, D_VICTOR 77/12, D_INTROA 60/6.

Fallback, Mockingboard mode, 6 voices (3 melodic, 1 drum, 2 effects left free), PAL //e:

| Song | Steals | Drum steals | Release cuts | Stream bytes | Writes/s | Writes/interrupt mean | p99 | p99 of bursts | Max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| D_E1M1 | 290 | 447 | 671 | 14523 | 79 | 1.57 | 11 | 12 | 14 |
| D_E1M2 | 76 | 699 | 723 | 10373 | 35 | 0.70 | 6 | 8 | 14 |
| D_E1M3 | 33 | 324 | 2305 | 13535 | 38 | 0.76 | 7 | 7 | 13 |
| D_E1M4 | 326 | 598 | 925 | 14231 | 72 | 1.45 | 13 | 13 | 15 |
| D_E1M5 | 494 | 0 | 963 | 6333 | 21 | 0.42 | 5 | 6 | 9 |
| D_E1M6 | 389 | 296 | 633 | 7065 | 91 | 1.82 | 11 | 12 | 14 |
| D_E1M7 | 422 | 6 | 681 | 6453 | 34 | 0.68 | 6 | 6 | 12 |
| D_E1M8 | 148 | 203 | 81 | 5221 | 23 | 0.46 | 5 | 7 | 10 |
| D_E1M9 | 1426 | 756 | 931 | 14534 | 58 | 1.16 | 12 | 13 | 15 |
| D_INTER | 899 | 887 | 1454 | 22483 | 86 | 1.72 | 14 | 14 | 16 |
| D_INTRO | 13 | 27 | 44 | 471 | 27 | 0.53 | 5 | 8 | 16 |
| D_VICTOR | 795 | 299 | 707 | 10166 | 46 | 0.92 | 8 | 10 | 15 |
| D_INTROA | 4 | 24 | 1 | 427 | 32 | 0.64 | 3 | 5 | 17 |
| All | | | | 125815 | | | | | |
<!-- report:end -->

### Against the design

native-sound.md's figures come from its prototype (`summary50.md`, 50 Hz
exactly). `tests/test_sound_mus2ay.py` checks every song and both layouts
against them on the PAL machine the tables above use, with no exception:
steals, drum steals, writes a second and p99 writes of a burst, each at
or below the design's figure as `summary50.md` prints it (whole numbers),
and the stream bytes of each layout.

- **Steals.** native12: equal in all 13 songs (0 in 8; D_INTER 52 of 3,250
  notes, D_INTRO 7). Drum steals equal or lower (D_E1M6 32 against 33,
  D_INTER 212 against 216). mb6: equal in all 13 songs, with the design's
  idle-voice rule (below).
- **Writes a second.** native12: at or below the design in all 13 songs
  (D_E1M1 122 against 134, D_INTER 118 against 132; 158,353 writes for
  the 13 songs). Main reasons: an idle voice that already holds the note's
  pitch is preferred (no tone write), an idle drum voice that last played
  the same recipe is preferred (no tone, noise, mixer or envelope period
  writes), and a drum voice's hits in one interrupt are latched so that
  only the last one writes registers. mb6: at or below in all 13 songs;
  D_E1M4 is 72.47 against the prototype's 71.77 before rounding (72 both
  rounded). The difference is an attack the prototype skips: when a steal
  gives a voice two notes in one tick and the first has an instant attack,
  the prototype starts the second from full level, where this player
  starts its attack from the level the voice had (the first note never
  sounded), so Synth Brass 2 ramps up over a few interrupts.
- **p99 writes of a burst.** At or below the design in all 13 songs.
  D_E1M8 is 11: 23 of its 2,823 bursts have 12 writes or more, and the
  99th percentile allows 29. It was 12 before the drum-voice preference,
  whose bursts at bar starts restarted a drum on the voice that had
  played the other drum (tone, noise, mixer and envelope period: 7 writes
  where 1 or 2 do).
- **The interrupt rate matters at the margin.** The prototype run at the
  //e's real PAL rate (50.080 Hz) instead of 50 Hz gives D_E1M8 a p99 of
  12 and D_E1M9 126 writes a second, both one above its own
  `summary50.md`. Many figures here equal the design's (the rules are
  the same), and a figure at its limit can cross it with the rate or a
  tie-break. Run at an exact 50 Hz, as `summary50.md` was, every figure
  of both layouts is still at or below the design except mb6 D_E1M4's
  writes a second, 72.54, which rounds to 73.
- **Largest burst.** One more than the design in D_E1M2 (20), D_E1M5
  (17) and D_E1M8 (19). The largest burst depends on where the interrupts
  fall: at an exact 50 Hz D_E1M8's is 16. The largest of all is 33 writes
  (D_INTRO and D_INTROA, their first chord), as in the design.

### Departures from native-sound.md

- **Tempo.** The design's 14/5 and 7/3 ticks an interrupt assume 50 and
  60 Hz; the video frames are 50.080 Hz (PAL, 312 lines of 65 cycles) and
  59.923 Hz (NTSC, 262 lines). A 16-bit fraction of the exact ratio keeps
  the tempo within 0.002%, where 14/5 would run 0.16% slow.
- **Drum hits are latched** to the interrupt (the last hit of a voice
  sounds) and start at the compose step, so a quiet hit is heard at full
  level for one interrupt before its decay.
- **GENMIDI's note offset and fixed notes are applied** (the design left
  the note offset out): Rock Organ, Cello, Tremolo Strings, Kalimba,
  Melodic Tom and Reverse Cymbal play an octave lower, as DMX plays them.
- **Voice choice.** Among idle voices, native12 takes one with the same
  pitch, then the same envelope, then the longest idle (158,353 writes
  for the 13 songs against 162,548 with the design's longest idle alone);
  mb6 takes the longest idle, the design's rule (with the same-pitch
  preference D_E1M2 had 83 steals against the design's 76). The rest is
  the design's: the same channel and note reuse their voice; else the
  release that ends first; else steal, keeping the bass (of two equal
  lowest notes, the one on the lower voice, as the prototype does) and
  taking the oldest note of the busiest channel. Drums: an idle drum
  voice, the one that last played the same recipe first, else the oldest
  hit.
- **MUS edge cases** the WAD's songs do not use (checked on hand-made
  songs, `tests/test_sound_mus2ay.py` and `test_sound_decoders.py`): a
  note of volume 0 is a note off, as a MIDI note on of velocity 0 is (the
  second decoder reads it so); system event 10 (all sounds off) cuts the
  channel's held and releasing notes at once with `$7v`, and on channel
  15 the drums still decaying; 11 (all notes off) releases the channel's
  held notes; 14 (reset all controllers) sets expression to 127, sends
  the held notes their new level, and centres the bend (the channel
  volume stays, as in MIDI).
- **Volume and bend changes** reach the voices holding a note of the
  channel; notes in their release keep their level and pitch.
- **Player start.** The mixer starts at `$38` (tones on, noises off), as
  the Bilestoad driver does, so a tone-only drum needs no mixer write.
- **The first note of each voice sends its bend** (2 bytes a voice a song).
- **Drum envelope periods** are stored for the layout's PAL clock; on
  NTSC a loud drum decays 0.5% faster.

## What needs the owner's ear

The renders are the first time anyone hears this. To judge:

- **Instrument mapping.** Every program is a square wave with a software
  envelope from its GENMIDI carrier (attack, decay, sustain, release).
  The modulator, feedback, the second voice of double-voice programs and
  the fine tune are not used, so timbres differ only by envelope and
  loudness. The OPL rates are converted with the YM3812 manual's table
  (an assumption, not measured).
- **Programs that are effects**: D_E1M5 uses Reverse Cymbal (119) and
  Guitar Fret Noise (120) as tones; noise might suit them better.
- **Drums** (`mus2ay.DRUMS`): a hand-made first guess per GM note (tone
  note, noise period, decay). The kick is a fixed 55 Hz tone with no
  pitch sweep. Hits of -6 dB and louder use the envelope generator.
- **Loudness.** Velocity, volume and expression follow 40 log10(v/127);
  DMX's own curve is not known here. The mix never saturates (0 saturated
  samples in the 13 renders); the WAVs are 6 dB above the card's scale.
- **Pitch bend range** is taken as +-2 semitones (D_E1M1's guitars).
- **Timing.** Notes move to the next interrupt (at most 20 ms late on
  PAL); a note shorter than an interrupt still sounds for one.
- **Not modelled in the renders:** the Phasor's bass, mid, treble and
  warmth stages (`mockingboard.sv:422-480`; warmth defaults to 8), and
  any analog filtering after the card.

## Open problems

- S2 needs a2vm's per-write AY log (`--ay-log`) and the slot-4 slowdown in
  its cost model (native-sound.md 5.2); neither exists yet.
- MUS has no loop point: the songs loop from their start (loop offset 0).
- The model reads the whole stream from memory; the ring buffer, its
  refill and the underrun rule (silence, hold position) of native-sound.md
  4.3 are not modelled yet.
- Effects (S4) are not here. In mb6, chip 2's mixer (R7) is shared with
  the effect voices and will have to be composed from both.
- Upstream's `tools/dmxmus.py` was not used as an extra oracle; the second
  decoder is `mus2mid.py` with `midi.py`.
