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
first 60 s or the whole song and one second of release, 44,100 Hz) and
`SONG.native12.ay` (the song file). It renders 4 songs at a time
(`--jobs`, the ground rules' limit); run it under `nice -n 10`.

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
| `tables.py` | Machines, clocks, the voice layout, period, bend, level and volume tables, tempo |
| `mus2ay.py` | The converter: MUS to a song file, each song with its gain (`--gain`, `--percentile`, `--boost`, `--cap`; "The song gain") |
| `player.py` | The model of the 65C02 player: the specification and S2's oracle |
| `ayrender.py` | AY register writes to WAV, after the card's YM2149 core and mixer |
| `report.py` | All songs: the tables below, song files and WAVs |
| `tables65.py` | S2: the player's tables as ca65 source (`build/sound65/tables.inc`), from `tables.py` |
| `run65.py` | S2: the 65C02 player (`src/sound`) on a2vm against `player.py`, its sizes and its cost (`src/sound/README.md`) |
| `musicdisk.py` | S3: the music disk `build/sound/MUSIC.hdv` (MUSIC.SYSTEM from `src/sound/music.s`, `aytime.s`, `music.cfg` and the S2 player; the 13 songs; the Doom profile) and its checks on a2vm (below, "The music disk") |

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
  0 and 2 exist, so a card that cannot switch to native mode has no
  music (`src/sound/README.md`, "No music"). The tools use these chip
  numbers.

## Voice layout

There is one layout, native12, with the card in native mode. The 6-voice
fallback for Mockingboard mode (mb6 in native-sound.md) was removed on
2026-09-30 (NATIVE.md 15.1, row 11): no tool, song file or test uses it.

| Layout | Melodic voices (0-) | Drum voices | Left for effects |
| --- | --- | --- | --- |
| native12 (native mode) | chip 0 A, B, C; chip 1 A, B; chip 2 A, B (7) | chip 1 C, chip 2 C (2) | chip 3 A, B, C |

A drum voice owns its chip's noise period (R6) and envelope (R11-R13).
Voice numbers in the stream are the melodic voices, then the drums.

## The song file

All numbers little-endian.

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | format version, 1 |
| 1 | 1 | layout: 0 (native12); any other value is refused |
| 2 | 1 | NE, envelopes |
| 3 | 1 | ND, drum recipes |
| 4 | 2 | stream length |
| 6 | 2 | loop offset in the stream (0: the start) |
| 8 | 8 NE | envelopes: attack step (2), decay step (2), release step (2), sustain (1), flags (1: bit 0 = the level holds while the key is down) |
| | 6 ND | drum recipes: tone note (1, 0 none), noise period (1, 0 none), envelope period for a loud hit (2, at the PAL PSG clock of native mode), soft decay step (2) |
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
to 155). All 13 songs are 135,880 bytes of stream (137,128 bytes
of song files), against 245,179 bytes of MUS.

The attenuations in the stream include the song's gain (below, "The
song gain"): the player applies no gain of its own, and the format is
unchanged.

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

The first burst (`Player.reset`) writes R0-R12 of the four chips:
periods and levels 0, mixer `$38`. The 65C02 player must produce the same
writes in the same order after every interrupt; S2 compares them.

## Report

The figures come from `python3 tools/sound/report.py --update-readme`,
run on 2026-09-30. Each song is played once to its end (no loop) plus one
second. "Writes/interrupt" is over all interrupts; "p99 of bursts" over the
interrupts that write something (the design report's measure). Costs use
native-sound.md 2.3: on F1.2.1, 504 us a burst and 40.4 us a write; with
the proposed FW-S1, 8.4 us a write. The songs are as shipped, each with
its song gain. The loudness table compares gain 0 and as shipped: "Loud
notes at" is the attenuation of the song's loud notes at gain 0, the
statistic the gain rests on; "Clamped" the share of the melodic held
note time whose attenuation is below the gain, so that it plays at
attenuation 0 (level 15) and loses its dynamics; then, over the first
60 s, the loudest level of a melodic voice, the mean AY level of the
melodic voices that sound and of all the music voices that sound (a
drum on the chip's envelope counts the envelope's level, 15 down to 0
over its recipe's decay: the player leaves such a voice at `$10` until
its next hit), and "Interrupts at 15", of the interrupts with a melodic
voice sounding, those whose loudest melodic voice is at 15. The two drum
columns are over the whole song: the share of hits on the chip's
envelope, and "Drums against melody", the mean change of a drum hit's
peak less the mean change of a melodic note's, in dB at the AY's levels
(`report.peak_changes`; 0 would keep the balance of gain 0).

<!-- report:begin (python3 tools/sound/report.py --update-readme) -->
Native mode, 12 voices (7 melodic, 2 drums, 3 effects left free), PAL //e: interrupts at 50.080 Hz, 2 or 3 MUS ticks each.

| Song | MUS bytes | Seconds | Events | Notes | Drum hits | Voices used (most held) | Steals | Drum steals | Release cuts | Stream bytes | Stream B/s | File bytes | Writes/s | Writes/interrupt mean | p99 | p99 of bursts | Max | F1.2.1 ms/s | FW-S1 ms/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| D_E1M1 | 17283 | 96.0 | 5826 | 1630 | 702 | 7 (5) | 0 | 133 | 40 | 14912 | 155 | 15016 | 117 | 2.33 | 16 | 17 | 25 | 22.5 | 0.98 |
| D_E1M2 | 36776 | 155.4 | 10847 | 804 | 1232 | 7 (7) | 8 | 276 | 670 | 13508 | 87 | 13586 | 79 | 1.58 | 14 | 15 | 27 | 19.3 | 0.66 |
| D_E1M3 | 19276 | 272.0 | 7507 | 2341 | 1408 | 7 (4) | 0 | 5 | 2259 | 13976 | 51 | 14030 | 104 | 2.08 | 10 | 11 | 20 | 25.2 | 0.87 |
| D_E1M4 | 18216 | 170.7 | 6270 | 1895 | 1210 | 7 (6) | 0 | 92 | 279 | 12629 | 74 | 12753 | 118 | 2.36 | 19 | 19 | 28 | 24.6 | 0.99 |
| D_E1M5 | 9830 | 164.0 | 3270 | 1460 | 4 | 7 (6) | 0 | 0 | 1447 | 7305 | 45 | 7343 | 55 | 1.10 | 9 | 10 | 16 | 15.0 | 0.46 |
| D_E1M6 | 9456 | 84.0 | 3332 | 1071 | 554 | 7 (5) | 0 | 32 | 1018 | 7104 | 85 | 7252 | 125 | 2.50 | 16 | 17 | 25 | 25.3 | 1.05 |
| D_E1M7 | 8591 | 150.9 | 2835 | 1110 | 226 | 7 (7) | 0 | 4 | 1093 | 6677 | 44 | 6773 | 50 | 0.99 | 7 | 7 | 23 | 15.6 | 0.42 |
| D_E1M8 | 59535 | 152.0 | 18113 | 355 | 522 | 7 (6) | 0 | 43 | 151 | 11252 | 74 | 11334 | 46 | 0.93 | 8 | 11 | 19 | 11.8 | 0.39 |
| D_E1M9 | 21266 | 137.4 | 7766 | 2620 | 1185 | 7 (7) | 2 | 272 | 1678 | 15470 | 113 | 15592 | 129 | 2.57 | 21 | 22 | 29 | 23.3 | 1.08 |
| D_INTER | 29082 | 201.4 | 9884 | 3250 | 1682 | 7 (7) | 52 | 212 | 1312 | 21416 | 106 | 21558 | 113 | 2.26 | 18 | 19 | 27 | 23.1 | 0.95 |
| D_INTRO | 1485 | 6.9 | 498 | 60 | 50 | 7 (7) | 7 | 4 | 46 | 642 | 94 | 746 | 57 | 1.13 | 11 | 12 | 33 | 15.3 | 0.48 |
| D_VICTOR | 13752 | 192.0 | 4532 | 1506 | 748 | 7 (7) | 3 | 60 | 1482 | 10551 | 55 | 10647 | 76 | 1.51 | 13 | 15 | 23 | 19.6 | 0.64 |
| D_INTROA | 631 | 6.9 | 214 | 10 | 48 | 7 (7) | 0 | 0 | 0 | 438 | 64 | 498 | 54 | 1.07 | 5 | 5 | 35 | 15.6 | 0.45 |
| All | 245179 | | | | | | | | | 135880 | | 137128 | | | | | | | |

NTSC //e (59.923 Hz), native mode: writes/s and p99 of bursts per song: D_E1M1 118/17, D_E1M2 80/15, D_E1M3 105/10, D_E1M4 121/19, D_E1M5 57/10, D_E1M6 130/16, D_E1M7 52/7, D_E1M8 48/11, D_E1M9 134/21, D_INTER 119/18, D_INTRO 59/12, D_VICTOR 79/15, D_INTROA 57/4.

Loudness: the song gain (percentile 0.99 of the melodic note time, boost +3.0 dB, cap +12.0 dB); the AY levels of the first 60 s (PAL) and the drums over the whole song, at gain 0 and as shipped.

| Song | Loud notes at | Gain | Clamped | Loudest level | Mean level, melodic | Mean level, all | Interrupts at 15 | Hits on the envelope | Drums against melody |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| D_E1M1 | -5.5 dB | +8.5 dB | 87% | 12 to 15 | 9.3 to 12.0 | 8.8 to 11.2 | 0% to 88% | 56% to 95% | -2.2 dB |
| D_E1M2 | -4.0 dB | +7.0 dB | 55% | 12 to 15 | 8.1 to 10.1 | 7.8 to 9.9 | 0% to 85% | 0% to 85% | +2.8 dB |
| D_E1M3 | -7.5 dB | +10.5 dB | 68% | 11 to 15 | 6.1 to 8.3 | 6.2 to 8.3 | 0% to 10% | 51% to 92% | -5.2 dB |
| D_E1M4 | -5.5 dB | +8.5 dB | 25% | 12 to 15 | 8.2 to 10.9 | 8.1 to 10.3 | 0% to 55% | 79% to 99% | -6.4 dB |
| D_E1M5 | -4.5 dB | +7.5 dB | 32% | 12 to 15 | 6.4 to 6.9 | 6.4 to 6.9 | 0% to 78% | 100% to 100% | -7.4 dB |
| D_E1M6 | -6.0 dB | +9.0 dB | 25% | 11 to 15 | 6.4 to 7.6 | 6.3 to 7.7 | 0% to 57% | 8% to 84% | +0.1 dB |
| D_E1M7 | -4.0 dB | +7.0 dB | 48% | 13 to 15 | 8.4 to 10.7 | 8.3 to 10.6 | 0% to 66% | 16% to 76% | +0.8 dB |
| D_E1M8 | -7.5 dB | +10.5 dB | 35% | 11 to 15 | 7.8 to 11.2 | 7.7 to 11.2 | 0% to 73% | 57% to 81% | -4.1 dB |
| D_E1M9 | -4.0 dB | +7.0 dB | 21% | 13 to 15 | 9.1 to 11.8 | 9.2 to 11.2 | 0% to 84% | 94% to 99% | -6.1 dB |
| D_INTER | -4.0 dB | +7.0 dB | 61% | 12 to 15 | 10.0 to 12.7 | 9.5 to 11.4 | 0% to 52% | 72% to 98% | -4.0 dB |
| D_INTRO | 0.0 dB | +3.0 dB | 10% | 15 to 15 | 8.5 to 9.6 | 8.2 to 9.2 | 0% to 0% | 14% to 26% | +0.2 dB |
| D_VICTOR | -3.0 dB | +6.0 dB | 3% | 13 to 15 | 6.5 to 8.2 | 6.5 to 8.2 | 0% to 3% | 12% to 36% | -0.4 dB |
| D_INTROA | -4.0 dB | +7.0 dB | 68% | 12 to 15 | 9.3 to 11.4 | 8.9 to 10.9 | 0% to 78% | 12% to 38% | +1.0 dB |
<!-- report:end -->

### Against the design

native-sound.md's figures come from its prototype (`summary50.md`, 50 Hz
exactly), which had no song gain. `tests/test_sound_mus2ay.py` checks
every song against them on the PAL machine: steals, drum steals, writes
a second and p99 writes of a burst, each at or below the design's figure
as `summary50.md` prints it (whole numbers), and the stream bytes. It
checks the songs as shipped (`AllSongs.test_against_the_design`), with
no exception but the 7 figures the song gain raised (`DESIGN_WITH_GAIN`;
"The song gain" below), and at gain 0
(`test_against_the_design_at_gain_0`, the songs as they were before the
gain, byte for byte). The figures of this section are at gain 0, where
every song passes.

- **Steals.** Equal in all 13 songs (0 in 8; D_INTER 52 of 3,250
  notes, D_INTRO 7). Drum steals equal or lower (D_E1M6 32 against 33,
  D_INTER 212 against 216).
- **Writes a second.** At or below the design in all 13 songs
  (D_E1M1 122 against 134, D_INTER 118 against 132; 158,353 writes for
  the 13 songs). Main reasons: an idle voice that already holds the note's
  pitch is preferred (no tone write), an idle drum voice that last played
  the same recipe is preferred (no tone, noise, mixer or envelope period
  writes), and a drum voice's hits in one interrupt are latched so that
  only the last one writes registers.
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
  is still at or below the design.
- **Largest burst.** One more than the design in D_E1M2 (20), D_E1M5
  (17) and D_E1M8 (19). The largest burst depends on where the interrupts
  fall: at an exact 50 Hz D_E1M8's is 16. The largest of all is 33 writes
  (D_INTRO and D_INTROA, their first chord), as in the design.

### The song gain

The owner's first run of the music disk on the card (2026-09-30,
`docs/results/music-card-2026-09-30.md`): "Volume is a little low but
music sounds great". At gain 0 the songs' loudest melodic notes reach
level 11 to 13 of the AY's 15 (D_INTRO 15), and in the first 60 s no
song but D_INTRO has a melodic voice at 15 in any interrupt: the songs
seldom play at velocity, volume and expression 127, the only full level
of the General MIDI law.

`mus2ay.convert` gives each song a gain, in attenuation units of 0.5 dB,
taken off every note's and every drum hit's attenuation:

- **The statistic** (`loud_attenuation`). A first pass of the converter
  at gain 0 counts the melodic notes' held time (note on to note off, a
  steal, a cut or the end; split at each volume or expression change; a
  note held less than a tick counts one tick) by attenuation. The loud
  notes' attenuation is the smallest a such that the notes at a or
  louder are held for at least 1% of that time (`PERCENTILE`, 0.99), so
  that one stray loud note does not set it.
- **The gain** (`song_gain`): that attenuation, which brings the loud
  notes to 0 (level 15), plus `BOOST` (6 units, +3 dB), at most `CAP` (24
  units, +12 dB).
- **Applied** (`attenuation`): the sum of the law's terms (velocity,
  volume, expression, carrier level) less the gain, 0 to 80. A note is
  silent (80) only when one term is silent by itself, a value of 12 or
  less (volume 0 included), so that a channel at volume 0 stays mute (the
  WAD's songs have such notes). A sum of 40 dB or more whose terms all
  sound is gained like any other: a volume fade keeps fading below the
  level it reached at gain 0 instead of cutting to silence (67 notes of
  D_E1M8, D_E1M2, D_E1M6 and D_INTRO sound now that were silent at gain 0,
  and the volume fades of held notes go on below the level at which they
  used to cut; six song files changed with this rule).
- **The clamp.** With the boost, the loud notes and every note up to 3
  dB quieter play at attenuation 0 (level 15): that note time loses its
  dynamics. The loudness table's "Clamped" gives its share of each song's
  melodic held note time: 3% (D_VICTOR) to 87% (D_E1M1), and more than
  half in D_E1M1, D_E1M3, D_INTROA, D_INTER and D_E1M2. `--boost 0`
  clamps only the loud notes' 1% (and the gains fall by 3 dB); the owner
  chooses.
- **Drums** take the same gain in attenuation, but not in balance with
  the melody. A hit of attenuation 12 or less (`tables.HW_DRUM_ATT`)
  plays on the chip's envelope from full level, so a hit already there
  cannot get louder, and a soft hit that the gain brings to 12 or less
  jumps to full level. At gain 0 most hits of D_E1M4, D_E1M5 (4 hits in
  all), D_E1M9 and D_INTER are already on the envelope (72% to 100%), so
  their drums fall back 4.0 to 7.4 dB against the melody; D_E1M2's hits were all soft and
  its drums gain 2.8 dB on the melody ("Drums against melody", -7.4 to
  +2.8 dB by song). Whether that sounds right is for the owner's ear; a
  separate drum gain is the alternative.
- The stream carries the gained attenuations; the player and the song
  file's format do not change. The counts report `gain`. `mus2ay.py
  --gain N` fixes one gain for every song (0: the songs as before), and
  `--percentile`, `--boost` and `--cap` change the rule.

The gains run from +3.0 dB (D_INTRO, whose loud notes are already at
full level) to +10.5 dB (D_E1M3 and D_E1M8); no song reaches the cap. The
loudness table above gives each song's gain and levels. In the renders
(the first 60 s, or the whole song and one second, PAL; the card's mix before the DC blocker; the RMS is
of both channels about their mean, in dB below the sum that saturates):

| Song | Gain | RMS, gain 0 | RMS, shipped | Change | Mix peak, of saturation |
| --- | ---: | ---: | ---: | ---: | ---: |
| D_E1M1 | +8.5 dB | -25.5 dB | -19.3 dB | +6.2 dB | 41% to 71% |
| D_E1M2 | +7.0 dB | -27.9 dB | -21.7 dB | +6.2 dB | 25% to 58% |
| D_E1M3 | +10.5 dB | -31.5 dB | -24.8 dB | +6.7 dB | 26% to 48% |
| D_E1M4 | +8.5 dB | -26.4 dB | -20.1 dB | +6.3 dB | 35% to 66% |
| D_E1M5 | +7.5 dB | -30.4 dB | -25.0 dB | +5.4 dB | 16% to 32% |
| D_E1M6 | +9.0 dB | -29.8 dB | -22.1 dB | +7.7 dB | 29% to 59% |
| D_E1M7 | +7.0 dB | -25.0 dB | -19.4 dB | +5.6 dB | 42% to 66% |
| D_E1M8 | +10.5 dB | -28.1 dB | -19.4 dB | +8.7 dB | 33% to 72% |
| D_E1M9 | +7.0 dB | -24.8 dB | -19.9 dB | +4.9 dB | 43% to 68% |
| D_INTER | +7.0 dB | -24.0 dB | -19.3 dB | +4.7 dB | 46% to 69% |
| D_INTRO | +3.0 dB | -23.7 dB | -20.6 dB | +3.1 dB | 42% to 54% |
| D_VICTOR | +6.0 dB | -31.7 dB | -25.9 dB | +5.8 dB | 23% to 41% |
| D_INTROA | +7.0 dB | -23.3 dB | -18.3 dB | +5.0 dB | 44% to 83% |

- **The mix never saturates**, before or after: 0 saturated samples in
  the 13 renders. D_INTROA comes closest, 83% of the sum
  that saturates (2,048).
- **The RMS rises less than the gain** where the loudest notes are
  clamped at level 15, and the AY's levels are coarse at the top (15 to
  14 is 1.5 dB, 14 to 13 is 1.5 dB, 13 to 12 is 2.0 dB). The mean level
  of the voices that sound rises less still (D_E1M5 6.4 to 6.9): release
  tails that were below level 1 now sound at levels 1 to 3 and count. The
  RMS is the measure of loudness; the mean levels are not (a level is a
  step of 1.5 to 3 dB, and a drum's level follows its envelope).
- **The WAVs are now at the card's scale** (`ayrender.LISTENING_GAIN` 1,
  was 2): at +6 dB the 16-bit output of D_E1M1, D_E1M9, D_INTER and
  D_INTROA clipped (10 to 72 samples each). So the new WAVs sound 6 dB
  less than the gain says against the old ones; the card has no such
  factor.

**What the gain moves in the design's figures** (PAL, gain 0 to shipped,
the design's `summary50.md` figure in brackets; F1.2.1 is the burst cost
of native-sound.md 2.3):

| Song | Writes/s | p99 of bursts | Largest burst | F1.2.1 ms/s | Soft drum hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| D_E1M1 | 122 to 117 [134] | 16 to 17 [18] | 25 to 25 | 23.3 to 22.5 | 308 to 36 |
| D_E1M2 | 87 to 79 [91] | 12 to **15** [12] | 20 to 27 | 21.9 to 19.3 | 1,232 to 185 |
| D_E1M3 | 92 to **104** [97] | 9 to 11 [11] | 19 to 20 | 24.3 to 25.2 | 684 to 106 |
| D_E1M4 | 111 to 118 [124] | 19 to 19 [20] | 23 to 28 | 23.8 to 24.6 | 250 to 12 |
| D_E1M5 | 47 to **55** [47] | 10 to 10 [10] | 17 to 16 | 12.8 to 15.0 | 0 to 0 |
| D_E1M6 | 138 to 125 [143] | 15 to **17** [15] | 20 to 25 | 27.0 to 25.3 | 510 to 87 |
| D_E1M7 | 49 to **50** [49] | 7 to 7 [7] | 23 to 23 | 15.7 to 15.6 | 190 to 54 |
| D_E1M8 | 41 to 46 [47] | 11 to 11 [11] | 19 to 19 | 11.0 to 11.8 | 225 to 98 |
| D_E1M9 | 120 to **129** [125] | 21 to 22 [22] | 27 to 29 | 22.0 to 23.3 | 77 to 6 |
| D_INTER | 118 to 113 [132] | 19 to 19 [22] | 26 to 27 | 23.9 to 23.1 | 463 to 31 |
| D_INTRO | 57 to 57 [64] | 12 to 12 [12] | 33 to 33 | 15.4 to 15.3 | 43 to 37 |
| D_VICTOR | 75 to 76 [77] | 13 to **15** [13] | 20 to 23 | 19.7 to 19.6 | 659 to 475 |
| D_INTROA | 56 to 54 [59] | 6 to 5 [6] | 33 to **35** | 14.8 to 15.6 | 42 to 30 |

In bold, what is now above the design: writes a second in D_E1M3,
D_E1M5, D_E1M7 and D_E1M9; the p99 of bursts in D_E1M2, D_E1M6 and
D_VICTOR; the largest burst of all, 35 in D_INTROA against 33. Steals,
drum steals, release cuts and the voices are the same at every gain
(the allocation does not look at loudness; the tests check it). The
stream is about the same size (135,880 bytes against 135,903): more notes
share an attenuation of 0, so more note ons take the short form, but
D_E1M8 grows (9,560 to 11,252 bytes) and D_E1M2 too (12,790 to 13,508),
their volume fades now sending levels below the gain-0 silence. Two
causes of the writes:

- **Levels.** A voice writes its level register each interrupt its
  level changes. A louder note crosses more of the AY's 16 levels on its
  way down (decay, release), so it writes more. D_E1M5, with 4 drum hits
  in the song, moves by this alone: 47 to 55 writes a second, its level
  writes 5,509 to 6,962 in the song.
- **Drums on the envelope generator.** A hit of attenuation 12 or less
  (-6 dB) uses the chip's envelope generator (`tables.HW_DRUM_ATT`); the
  gain moves most hits there (soft hits 4,683 to 1,157 in the 13 songs).
  Such a hit writes the envelope period (R11, R12) when it differs, R13
  always, and the level `$10` once, then nothing while it decays; a soft
  hit writes its level at each interrupt of its decay. So a song with
  many hits can write less a second (D_E1M2 87 to 79, D_E1M6 138 to 125),
  while the interrupt of a hit writes more: the bursts at hits grow. In
  the bursts at or above the p99, the envelope registers went from 0 to
  5.2 writes a burst in D_E1M2, 0.2 to 3.9 in D_E1M6 and 1.3 to 3.1 in
  D_VICTOR, the other registers about the same.

**How the tests bound it.** The design's figures stay the test of the
songs that ship (`AllSongs.test_against_the_design`), with the 7 figures
in bold above accepted in `DESIGN_WITH_GAIN` in
`tests/test_sound_mus2ay.py`, one entry a song and figure with its
reason (accepted 2026-09-30 for the owner's "Volume is a little low";
the owner can refuse them, which means a smaller gain). Why they are
accepted: those figures exist to bound the player's cost, and the gain
leaves that inside the design's range: at most 12 more writes and 3.6 more bursts a
second, 2.2 ms a second more on F1.2.1 (D_E1M5, 12.8 to 15.0; a burst
costs its 504 us tail), and every song's F1.2.1 burst cost at most 27.5
ms a second and FW-S1 at most 1.20, the top of native-sound.md 4.2's
range (11.8 to 25.3 and 0.39 to 1.08). The converter's rules are also
checked at gain 0 against the design, where every song passes
(`test_against_the_design_at_gain_0`). `AllSongs.test_the_song_gain`
checks each song's gain (pinned: `SONG_GAINS`), that it is the
statistic's plus the boost, that every note and drum hit carries its
gain-0 attenuation less the gain (a silent sum of audible terms may
sound, at 80 less the gain or above), that the voices are the same, and
the bus cost above. `test_sound_decoders.py` checks every attenuation of
the shipped songs against its terms, from the second decoder.

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
- **Voice choice.** Among idle voices, the converter takes one with the
  same pitch, then the same envelope, then the longest idle (158,353
  writes for the 13 songs against 162,548 with the design's longest idle
  alone). The rest is
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
- **Drum envelope periods** are stored for the PAL clock; on NTSC a loud
  drum decays 0.5% faster.
- **No 6-voice fallback.** The design's mb6 layout for a card in
  Mockingboard mode is gone (NATIVE.md 15.1, row 11).
- **Song gain.** The design had none; each song is now scaled so that its
  loud notes reach level 15 ("The song gain"). Seven figures of the
  shipped songs are above the design's, accepted in `DESIGN_WITH_GAIN`
  because the bus cost stays inside the design's range.

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
- **Drums against the melody after the song gain.** The gain moves the
  drums' balance by song, -7.4 dB (D_E1M5) to +2.8 dB (D_E1M2) ("The
  song gain", "Drums"): in D_E1M3, D_E1M4, D_E1M5, D_E1M8, D_E1M9 and
  D_INTER the drums fall back 4 dB or more, in D_E1M2 they come forward. Whether the
  drums now sit right, and whether a separate drum gain is wanted, is
  for the owner to say.
- **Loudness.** Velocity, volume and expression follow 40 log10(v/127);
  DMX's own curve is not known here. Each song has a gain of +3 to +10.5
  dB so that its loud notes reach level 15 ("The song gain"); on the
  card the owner found the songs a little quiet before it. The boost (+3
  dB over the loud notes) clamps 3% to 87% of a song's melodic note time
  at level 15, where it loses its dynamics ("Clamped"); `--boost 0` keeps
  more dynamics for 3 dB less. The owner chooses the boost. The mix never
  saturates (0 saturated samples in the 13 renders, at most 83% of the
  saturating sum); the WAVs are at the card's scale.
- **Pitch bend range** is taken as +-2 semitones (D_E1M1's guitars).
- **Timing.** Notes move to the next interrupt (at most 20 ms late on
  PAL); a note shorter than an interrupt still sounds for one.
- **Not modelled in the renders:** the Phasor's bass, mid, treble and
  warmth stages (`mockingboard.sv:422-480`; warmth defaults to 8), and
  any analog filtering after the card.

## The music disk (milestone S3)

The card run of the music: `build/sound/MUSIC.hdv`, a bootable ProDOS
volume, for the owner to boot on the Appletini (NATIVE.md 13, S3: "a timed
loop of AY writes confirms 40.4 us a write and the 504 us tail (window 512
and 32); a disk plays every song; the owner listens").

```
python3 tools/sound/musicdisk.py                        # the disk
nice -n 10 python3 tools/sound/musicdisk.py --check     # and the a2vm checks
python3 -m unittest discover -s tests -p 'test_sound_disk.py'
```

It needs `DOOM1.WAD` (`tools/fetch_upstream.py`), cc65 2.18 and the
existing port's disk writer (`demos/doom/tools/build_disk.py`, with
appletini-one's `software/ProDOS_2_4_3.po`; `APPLETINI_ROOT` if
appletini-one is not next to appletini-software). The checks run at most 2
a2vm runs at a time (`--jobs`), each bounded in time and file size
(`tools/ref816/bounded.py`), in a `build/tmp-musicdisk-*` directory
removed at the end (`--keep DIR` keeps them). All of `--check` takes
about 4 s; the tests about 10 s.

### What is on the disk

Volume `MUSIC`, 219,136 bytes (428 blocks):

| File | Type | Bytes | What |
| --- | --- | ---: | --- |
| `MUSIC.SYSTEM` | SYS, `$2000` | 14,080 | The program (below): `$2000-$3FFF` its code, `$4000-$56FF` the card image `$E900-$FFFF` |
| `PRODOS` | SYS | 17,128 | ProDOS 2.4.3, with its boot blocks, from `ProDOS_2_4_3.po` |
| `E1M1.AY` ... `E1M9.AY`, `INTER.AY`, `INTRO.AY`, `VICTOR.AY`, `INTROA.AY` | BIN, `$1000` | 498 to 21,558 | The 13 song files, converted by `mus2ay.py` at build time, in upstream's song order (`mus.UPSTREAM_SONGS`): keys A to M |
| `PROFILE.TXT` | TXT | 2,504 | The Doom configuration profile: the key and how to install it (below) |

`DOOM_PROFILE.TXT`, written beside the disk image (`build/sound/` by
default; `--out` moves both), is the same text, to copy beside
`MUSIC.hdv` on the SD card, where the Appletini menu's file browser opens
text files.

### MUSIC.SYSTEM

Sources: `src/sound/music.s` (boot, screen, keys, quit), `aytime.s` (the
timing test), `music.cfg` (the map), with the S2 player unchanged
(`player.s`, `irq.s`, `probe.s`). The player sits where
`docs/MEMORY_MAP.md` 4.2 puts it in the game, so the card run tests the
game's placement and IRQ contract: zero page `$D8-$F6`, ring
`$E000-$E402`, write lists `$E480-$E4FF`, state `$E500-$E736`, code and
tables `$E900-$F504` (3,077 of the map's 4,096 bytes), the IRQ vector at
`$FFFE` (`snd_vbl`); `$D000` bank 1 selected, and the interrupt never
reads `$D000-$DFFF`. The program's own data is in main `$1000-$1FFF` and
its zero page at `$18`, outside the video pages, so the timing test's
stores leave nothing in the card's mirror; no CPU store reaches
`$0878-$087F` or `$4078-$407F` (rule 8; the tool checks the file's bytes
at `$4078`).

The boot, under ProDOS with interrupts masked: the text screen (40
columns, SHR off); the mouse card in slot 2 (its ID bytes; none: "NO MOUSE
CARD IN SLOT 2", a key, ProDOS's QUIT); RamWorks banks 1-14 distinct
(else "THE SONGS NEED RAMWORKS BANKS 1-14"); `snd_probe`; with music, the
13 songs into banks 1-13 at `$1000` (each file's length checked against
the tool's); ProDOS's language card (both `$D000` banks and `$E000-$FFFF`)
saved in bank 14; the card image installed; `snd_init`; the mouse card's
VBL interrupt on; then **PAL or NTSC**: VIA-A's timer 1 counts Apple bus
cycles, 20,280 over one VBL on a PAL //e (312 lines of 65 cycles) and
17,030 on NTSC, and the program takes the nearer (the count is on the
screen; V switches by hand). With music the first song starts, looping.

The screen:

```
DOOM GS: THE MUSIC ON THE PHASOR
PAL //E: TIMER 1 COUNTS 20280 A VBL
PHASOR IN NATIVE MODE, 4 AY CHIPS

 A D_E1M1   1:36     H D_E1M8   2:32
 B D_E1M2   2:35     I D_E1M9   2:17
 C D_E1M3   4:32     J D_INTER  3:21
 D D_E1M4   2:51     K D_INTRO  0:07
 E D_E1M5   2:44     L D_VICTOR 3:12
 F D_E1M6   1:24     M D_INTROA 0:07
 G D_E1M7   2:31

PLAYING D_E1M2   0:01   OF 2:35   LOOP

A-M PLAY  N NEXT  P PREVIOUS  SPACE STOP
R LOOP OR ALL  V PAL OR NTSC  Q QUIT
T AY TIMING TEST
```

(the a2vm run's screen; the playing song's letter is in inverse). Each
song's length is its MUS length. The clock counts 50 or 60 VBLs a second,
so on PAL (50.08 Hz) it gains 0.16%.

| Key | What |
| --- | --- |
| A to M | Play that song from its start (lower case too) |
| SPACE | Stop: the next interrupt silences the voices |
| N or right arrow, P or left arrow | The next or previous song |
| R | Loop (each song loops, the default) or ALL (each song once; 50 VBLs after its end, the next) |
| V | PAL or NTSC tables and tempo; the playing song starts again on them |
| T | The AY timing test (below); it stops the music |
| Q or ESC | Quit: the chips reset, ProDOS's card put back from bank 14, the Phasor back in Mockingboard mode (its power-on mode, for the next program), ProDOS's QUIT |

**No music.** When `snd_probe` answers `SND_NO_MUSIC` (a Mockingboard, or
the Phasor with its Mockingboard only option on), no song is loaded and
the screen says:

```
NO MUSIC. THE CARD IN SLOT 4 DID NOT
SWITCH TO THE PHASOR'S NATIVE MODE: IT
HAS 2 AY CHIPS, AND THE MUSIC NEEDS 4.
IT IS A MOCKINGBOARD, OR THE PHASOR
WITH ITS MOCKINGBOARD ONLY OPTION ON.
IN THE APPLETINI MENU: PHASOR IN SLOT 4
ON, MOCKINGBOARD ONLY OFF; THEN REBOOT.

T AY TIMING TEST  V PAL OR NTSC  Q QUIT
```

The timing test still runs (on the first AY of VIA-A).

### The AY timing test (key T)

native-sound.md 2.3 expects an AY register write of the burst loop (41
cycles) to take 40.4 us, and the slow window after a burst's last write to
run 512 cycles at 1 MHz (504 us) by default, 32 (31.5 us) with the Doom
profile, none with FW-S1 (8.4 us a write). The test measures both by VBL
counts, in about 2 seconds: three phases of 32 frames; in each frame,
right after the VBL, a burst of K writes (R8 of chip 0 = 0, silent) with
the player's own 41-cycle loop, then a loop of 13 cycles that counts its
turns until the next VBL. K is 0 (the reference, all TURBO), 16 and 208.
The turns a burst costs give its time in bus cycles, D = (cF - c) / cF x
the frame; a write is (D2 - D1) / 192; what is left of D1 after its 16
writes is the window at 1 MHz less what TURBO would have run in it, from
which the window in cycles follows (`aytime.s` gives the arithmetic). It
prints, with the expected values beside:

```
AY TIMING, PAL (1,015,625 HZ)
A WRITE 40.4 US, EXPECTED 40.4
TAIL 513.1 CYCLES = 505.2 US
EXPECTED 512 = 504.1 US: DEFAULT
      OR  32 = 31.5 US: DOOM PROFILE
SO THE WINDOW IS 512: THE DEFAULT
(FW-S1: A WRITE ABOUT 8.4 US, NO TAIL)
```

The verdict line reads 512 for 504-520 cycles, 32 for 28-36, "PORT WRITES
ARE NOT SLOWED: FW-S1" when a write takes under 20 bus cycles, and
"ANOTHER WINDOW THAN 512 OR 32" otherwise. On NTSC the expected values are
40.2 us, 501.7 us and 31.4 us (a bus cycle of 979.9 ns, 984.6 ns on PAL).

**For the owner:** boot the disk and press T once with the default setup
(expect about 40.4 us and 504 us), then install the Doom profile (below),
boot again, press T (expect 40.4 us and about 31.5 us). The measured tail
is the window plus the rest of the instruction it ends in and the first
write's bus cycle: on a2vm up to 1.3 cycles over the setting (below).

### The Doom configuration profile

The owner's decision (NATIVE.md 15.1, row 2): ship a Doom profile with
`vtw.slowdown.cycles=32`. Read in appletini-one F1.2.1
(`ps_sources/frontend`):

- A profile is a folder `0:/profiles/NAME/` on the card's SD volume
  holding `appletini_cfg.txt` (`profile_manager.h:9-10`,
  `profile_manager.c:165-168`), in the same `key=value` format as the
  main `0:/appletini_cfg.txt` (`config_menu.c:939-975`, `:3796-3812`).
- Loading one (Profiles tab, "Choose profile", `config_menu_profiles.c:259`)
  runs `config_menu_load_profile_settings` (`config_menu.c:4377-4410`):
  **every setting is reset to its default first** (`:4307-4309`,
  `config_menu_reset_settings_only` `:4179-4272`), then the file's keys
  apply; TURBO is off unless the file says `vtw.turbo.enabled=ON`
  (`:4311-4312`); the result is saved as `0:/appletini_cfg.txt`
  (`:4401`), so it holds after a reboot. The video standard and the
  ONE//e state are global and never taken from a profile (`:4323-4327`).
- `vtw.slowdown.cycles` takes 1-65,535 as written (`:3550-3552`); the
  menu's presets are 256-65,535 (`:84-86`) and a step of the window in
  the menu replaces a value that is not a preset with the next preset
  (`:4694-4717`). With the Phasor on, slot 4 is always in the slowdown
  mask and a window of 0 becomes 512 (`:4669-4692`).
- "Save As" (Profiles tab) creates the folder and writes every current
  setting into its `appletini_cfg.txt` (`config_menu_profiles.c:437-457`,
  `config_menu.c:4353-4367`).

So a file with the one key would turn off the Phasor, the mouse card,
RamWorks and TURBO. The profile is made from the working setup and
edited:

1. Boot into the Appletini menu with the setup DOOM needs: TURBO on,
   RamWorks on, the mouse card in slot 2, the Phasor in slot 4 on and its
   Mockingboard only option off.
2. Profiles tab: Save As, name `DOOM`. This writes
   `0:/profiles/DOOM/appletini_cfg.txt`.
3. On the SD volume (the card in a computer, or the menu's USB or FTP SD
   sharing), change that file's line `vtw.slowdown.cycles=512` to
   `vtw.slowdown.cycles=32`. Check `phasor.slot4.enabled=ON`,
   `phasor.mockingboard.only=OFF`, `slot2.card=MOUSE`,
   `vtw.turbo.enabled=ON` while there.
4. Profiles tab: Choose profile, `DOOM`; the status line says `LOADED
   PROFILE DOOM`. Between steps 2 and 4, change no bezel or video ROM
   setting: the menu also writes those into the selected profile, with
   the window it holds, 512 (`config_menu.c:6745-6750`, `:7019-7021`).
5. Do not step the slowdown window in the menu afterwards.

Undo: choose another profile, or set the line back to 512 and choose
`DOOM` again. `PROFILE.TXT` on the disk and `DOOM_PROFILE.TXT` beside it
say the same. The key is: `vtw.slowdown.cycles=32`.

### Checks on a2vm

`musicdisk.py --check` (and `tests/test_sound_disk.py`) runs the disk's
own MUSIC.SYSTEM on a2vm: the MLI trap serves the disk's files (as
`tools/native/disk.py --check`), the exact W65C02S core, the cost model on
the model's clock with the Phasor's slowdown (`f121+phasor`), and every
interrupt held to the game's contract (`--irq-bounds
00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF`, MEMORY_MAP rule 2). Keys are
a2vm input events at the Nth visit of `mus_service`, the main loop's
once-a-VBL service. Results of 2026-09-30:

| Check | Result |
| --- | --- |
| songs | The probe says music; the 13 files in banks 1-13 byte for byte; timer 1 counts 20,280 cycles a VBL (PAL); A from the boot, then B to M by key, 20.0 s each: 13,043 interrupts, every interrupt's AY writes and every start's first burst equal `player.py`'s (run65's comparison, `RingPlayer` for the ring), each start at the VBL of its key, the chips' registers at the end equal the model's shadow; 990 VBLs into D_INTROA the status row reads exactly `PLAYING D_INTROA 0:19   OF 0:07   LOOP` (the clock at 50 VBLs a second) |
| keys | `b` (lower case), SPACE, N, P, M, right arrow (M to A), left arrow (A to M), V (NTSC tables), R (play all), K: starts at interrupts 2, 51, 251, 351, 401, 421, 441, 451, 561 and 1022 (D_E1M1, D_E1M2, D_E1M3, D_E1M2, D_INTROA, D_E1M1, D_INTROA, D_INTROA on NTSC tables, D_INTRO, then D_VICTOR by itself 49 interrupts after D_INTRO's end); the stop's silence; all equal the model. T 100 VBLs into D_VICTOR: the music stops at that VBL (interrupt 1122), the test's 7,168 writes and nothing else, the status row `STOPPED D_VICTOR 0:01   OF 3:12   ALL` (the NTSC clock, 60 VBLs a second); then ESC quits as Q does |
| quit | `q` while A plays: `snd_init`'s resets the last AY events, the chips at 0, the card's former contents (a random pattern loaded before the boot) back byte for byte, the Phasor back in Mockingboard mode, ProDOS's QUIT (ESC in `keys` is checked the same way) |
| nomusic | `--phasor-mb-only`: the no-music screen, one MLI call (the QUIT: no song file opened), a song key changes nothing on the screen (no message on the last row), no AY event but the probe's and the two `snd_init`s' resets, the card still in Mockingboard mode |
| aytime | Below |

The timing test on a2vm, against the model (the variants of
`costs/appletini.json`); "AY log" is the mean spacing of the 208-write
bursts in a2vm's own log, an independent check of the program's
arithmetic. The check also requires rows 17-23 of the test's screen to
read exactly what the measured values give (`aytime_rows`: the write's
and the tail's microseconds, the expected 40.4 or 40.2 us, 504.1 or 501.7
us and 31.5 or 31.4 us, the verdict). Results of the shipped build
(`build/sound/MUSIC.hdv`, SHA-1 `500c6ea9`), 2026-09-30; the build
with the song gain (SHA-1 `0adc5554`, the same program, other song
files) gave the same four rows, and so does the build after the review
of the gain (SHA-1 `1344e6cf`, six song files changed by the attenuation
rule, "The song gain"), 2026-09-30:

| Variant | A write, cycles (AY log) | us | Tail, cycles | us | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| `f121+phasor` (window 512), PAL | 41.013 (41.000) | 40.4 | 513.0 | 505.1 | 512 |
| `+window32`, PAL | 41.012 (41.000) | 40.4 | 33.0 | 32.5 | 32 |
| `+fws1`, PAL | 9.230 (9.246) | 9.1 | none | - | FW-S1 |
| `f121+phasor+ntsc` (window 512) | 41.014 (41.000) | 40.2 | 513.2 | 502.9 | 512 |

The build before the quit's `bit PHASOR_MB` (3 bytes more in `music.s`,
which moves `aytime.s`'s loops) gave 513.1, 31.9, 513.3 cycles of tail and
an FW-S1 write of 9.256 (AY log 9.268): the figures move with where the
code falls against the bus clock.

- **A write** is the design's 41 cycles within 0.05%.
- **The tail** is the window from 0.1 cycles under to 1.3 over, by the
  build. What moves it, from the model (`tools/a2vm/README.md`, "The
  slot-4 slowdown"): an instruction that began at 1 MHz keeps its cycles
  when the window closes inside it (up to 2 more cycles of the spin
  loop), and the burst's first write is one bus cycle of 0.93 to 1.93
  where the arithmetic counts 1; the program's formula leaves both out.
  The check accepts the setting from 0.5 cycles under to 3 over.
- **FW-S1**: a write takes 9 or 10 bus cycles by its alignment to the
  bus (6 bus accesses; 9.25 to 9.27 on average in long bursts, by the
  build), 9.1 us against the design's "about 8.4 us"; a burst costs 4 to
  5 us more than its writes by that alignment (3.8 and 4.6 us in the two
  builds), not a window.
- The comparisons can fail (`PlantedBugs`): copies of `music.s` whose
  keys start the wrong song, whose PAL clock counts 60 VBLs a second,
  whose song keys run without music (the player refuses the song and the
  last row says so), or whose quit leaves the Phasor in native mode, and
  copies of `aytime.s` whose burst loop takes 43 cycles or whose
  microseconds are divided by 99,000,000 in place of 100,000,000, are
  caught; an unchanged copy passes. By hand, `EXPECTED` computed from
  43,000 mc and the tail's microseconds taken from the write time were
  caught too (rows 18 and 19).
- A run that passes its time limit is reported as a failure, and the
  builds (`make`, `ca65`, `ld65`) run under `bounded.run` with a time
  limit.

## Open problems

- **The disk has run on the card once** (2026-09-30,
  `docs/results/music-card-2026-09-30.md`): PAL found, a write 40.4 us,
  the tail 32.2 cycles under the Doom profile, the music "a little low
  but sounds great", the quit to ProDOS fine. The song gain answers the
  volume; the disk with it (`1344e6cf`) has not run on the card.
- **The shipped songs exceed the design** in 7 figures, accepted in
  `DESIGN_WITH_GAIN` ("The song gain", "How the tests bound it"): writes
  a second in D_E1M3, D_E1M5, D_E1M7 and D_E1M9, the p99 of bursts in
  D_E1M2, D_E1M6 and D_VICTOR. If the owner refuses them, the gain
  changes.
- The timing test's expected FW-S1 figure (8.4 us) is the design's; a2vm
  gives 9.1 us from its bus-cycle timing, which milestone 0 measures.
- The PAL/NTSC choice rests on VIA-A's timer 1 counting Apple bus cycles
  (`hdl/apple/via6522.v:334-352`, `mockingboard.sv:86`: `sss_en`); V
  switches by hand if the card's count differs.
- Quit restores ProDOS's language card from RamWorks bank 14 and calls
  ProDOS's QUIT; on a2vm the card's bytes come back exactly (the MLI is a
  trap there), and on the card the owner found the exit to ProDOS fine.
- The song gain is chosen by a statistic, not by ear: D_E1M3, D_INTRO and
  D_VICTOR have few interrupts at level 15 (9.5%, 0.3%, 3.1%) because
  their loudest 1% is well above the rest. `--percentile` and `--boost`
  change it for all songs; the boost's clamp and the drums' balance
  ("The song gain") wait for the owner's ear.
- S2 used a2vm's per-write AY log (`--ay-log`) and the slot-4 slowdown in
  its cost model (native-sound.md 5.2); both exist now
  (`tools/a2vm/README.md`).
- MUS has no loop point: the songs loop from their start (loop offset 0).
- The model reads the whole stream from memory; the ring buffer, its
  refill and the underrun rule (silence, hold position) of native-sound.md
  4.3 are modelled by `run65.RingPlayer` (S2), which the 65C02 player is
  tested against, not by `player.py` itself.
- Effects (S4) are not here; they get chip 3.
- Upstream's `tools/dmxmus.py` was not used as an extra oracle; the second
  decoder is `mus2mid.py` with `midi.py`.
