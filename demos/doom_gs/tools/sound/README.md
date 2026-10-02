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
| `mus2ay.py` | The converter: MUS to a song file |
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
  (VIA-A) 11, 5, 11; chips 2 and 3 (VIA-B) 5, 11, 5. The menu's scale is
  0-15 (`config_menu_phasor.c:333-336`); the gains
  (`mockingboard.sv:316-343`) keep the left at 16/16 for pans 0-8 and the
  right at 16/16 for pans 8-15, so **8 is the one centred pan**, both
  sides full (RETURN on a pan item in the menu sets it to 8,
  `config_menu_phasor.c:398-409`). The menu labels the chips by psg:
  chip 3 is "AY3 A/B/C", keys `phasor.pan.10`-`12` of
  `appletini_cfg.txt` (`:16-29`, `:234-243`, `:296-298`). The Doom
  profile sets chip 3's C to 8 (below, "Stereo by voice"); the music's
  chips keep the defaults.
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
to 165). All 13 songs are 135,903 bytes of stream (137,151 bytes
of song files), against 245,179 bytes of MUS.

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
<!-- report:end -->

### Against the design

native-sound.md's figures come from its prototype (`summary50.md`, 50 Hz
exactly). `tests/test_sound_mus2ay.py` checks every song against them on
the PAL machine the tables above use, with no exception: steals, drum
steals, writes a second and p99 writes of a burst, each at or below the
design's figure as `summary50.md` prints it (whole numbers), and the
stream bytes.

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

## What needs the owner's ear

The renders are the first time anyone hears this. To judge:

- **Heard on the card (2026-09-30,
  `docs/results/music-card-2026-09-30.md`).** "Music sounds great", the
  volume "a little low". A gain for each song that brought every song's
  loud notes to level 15 (commit 5aba2f60) was refused and reverted:
  "Drums now are too weak, and overall everything is flat." Keep this mix;
  any louder one must keep the drums' balance with the melody and must not
  clamp notes at full level.

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
| `E1M1.AY` ... `E1M9.AY`, `INTER.AY`, `INTRO.AY`, `VICTOR.AY`, `INTROA.AY` | BIN, `$1000` | 498 to 22,352 | The 13 song files, converted by `mus2ay.py` at build time, in upstream's song order (`mus.UPSTREAM_SONGS`): keys A to M |
| `PROFILE.TXT` | TXT | 4,030 | The Doom configuration profile: its keys (the window, chip 3's pans) and how to install it (below) |

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
`vtw.slowdown.cycles=32`; and since 2026-10-02 (`docs/SCREENS.md` 10,
row 6) chip 3's pans `phasor.pan.10=5`, `phasor.pan.11=11`,
`phasor.pan.12=8` (A left, B right, C centre: "Stereo by voice" below;
only C differs from the menu's default, 5). Read in appletini-one F1.2.1
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
   Mockingboard only option off. In the Phasor tab, AY3 C: RETURN (pan
   8, the centre).
2. Profiles tab: Save As, name `DOOM`. This writes
   `0:/profiles/DOOM/appletini_cfg.txt`.
3. On the SD volume (the card in a computer, or the menu's USB or FTP SD
   sharing), change that file's line `vtw.slowdown.cycles=512` to
   `vtw.slowdown.cycles=32`. Check `phasor.slot4.enabled=ON`,
   `phasor.mockingboard.only=OFF`, `slot2.card=MOUSE`,
   `vtw.turbo.enabled=ON`, `phasor.pan.10=5`, `phasor.pan.11=11`,
   `phasor.pan.12=8` while there.
4. Profiles tab: Choose profile, `DOOM`; the status line says `LOADED
   PROFILE DOOM`. Between steps 2 and 4, change no bezel or video ROM
   setting: the menu also writes those into the selected profile, with
   the window it holds, 512 (`config_menu.c:6745-6750`, `:7019-7021`).
5. Do not step the slowdown window in the menu afterwards.

A DOOM profile made before 2026-10-02 lacks the centre: Choose profile,
`DOOM`; Phasor tab, AY3 C, RETURN; Profiles tab, "Save to current
profile" (`config_menu_profiles.c:647-665`: every current setting, the
loaded window 32 with them). Or edit its line `phasor.pan.12=5` to
`phasor.pan.12=8` and choose `DOOM` again. A pan changed in the Phasor
tab alone is saved in `0:/appletini_cfg.txt` only
(`config_menu_phasor.c:338-341`, `config_menu.c:3913-3918`), so the next
"Choose profile" sets it back.

Undo: choose another profile, or set the lines back (512,
`phasor.pan.12=5`) and choose `DOOM` again. `PROFILE.TXT` on the disk and
`DOOM_PROFILE.TXT` beside it say the same (`musicdisk.py`, the pans from
`tables.FX_VOICES`). The keys are: `vtw.slowdown.cycles=32`,
`phasor.pan.10=5`, `phasor.pan.11=11`, `phasor.pan.12=8`. The playable
game's disk (`tools/native/playdisk.py`) carries no profile.

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
(`build/sound/MUSIC.hdv`, SHA-1 `500c6ea9`), 2026-09-30:

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

- **Nothing of S3 has run on the card.** The owner tests at milestone 12;
  the disk, the timing test and the profile are ready for it.
- The timing test's expected FW-S1 figure (8.4 us) is the design's; a2vm
  gives 9.1 us from its bus-cycle timing, which milestone 0 measures.
- The PAL/NTSC choice rests on VIA-A's timer 1 counting Apple bus cycles
  (`hdl/apple/via6522.v:334-352`, `mockingboard.sv:86`: `sss_en`); V
  switches by hand if the card's count differs.
- Quit restores ProDOS's language card from RamWorks bank 14 and calls
  ProDOS's QUIT; on a2vm the card's bytes come back exactly, but the MLI
  is a trap there, so ProDOS's own restart after the quit is untested.
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

## Effects (S4)

Status: design, 2026-10-01 (revised the same day after the review in
`docs/SCREENS.md` section 10), for milestone 11's first half
([`docs/SCREENS.md`](../../docs/SCREENS.md): section 3 places the
effects in the machine, section 7 gives the parts `fxconv`, `fxplay`,
`fxchan` and `fxdisk`). The converter is built (part `fxconv`, wave 1,
2026-10-01: [`docs/m11-parts/fxconv.md`](../../docs/m11-parts/fxconv.md)),
and so are the player (part `fxplay`, wave 3), the channel logic (part
`fxchan`, wave 4) and the test disk (part `fxdisk`, wave 7, 2026-10-02:
[`docs/m11-parts/fxdisk.md`](../../docs/m11-parts/fxdisk.md)), and the
first half's acceptance passes on a2vm (2026-10-02, `docs/SCREENS.md` 8.13
and the report 8.14: "Results" below); nothing has run on the card yet.
The music sections above
are unchanged, and so is what the music writes: with no effect playing,
the AY log stays S2's byte for byte (below, "The player").

It follows the owner's decision (`NATIVE.md` 15.1, row 11): effects
generated automatically, the 10 most frequent hand-tuned, stereo by
picking a left- or right-panned voice (since 2026-10-02 also a centred
one: "Stereo by voice"); and `docs/research/native-sound.md`
4.5, whose prototype (`build/native-design/sound/sfx.py`) this replaces
with tools of our own. Labels as in `NATIVE.md`: [M] measured, [R
file:line] read, [A] assumed.

### Sources

| Lumps | What | Facts |
| --- | --- | --- |
| `DS*` | Digital effects: DMX format, a format word (3), the sample rate, the sample count, then 8-bit unsigned samples | 55 in `DOOM1.WAD`, 52 of them the game's sounds (`CONST_SFX_PISTOL` .. `GETPOW` [R `build/upstream/src/iigs/offsets.inc:448-499`]); `DSBDOPN`, `DSBDCLS`, `DSITMBK` are not; 515,136 samples for the 52, the longest 1.69 s [M: this design]; 11,025 Hz but `DSITMBK` 22,050 [M: sound 4.5] |
| `DP*` | PC-speaker effects: a zero word, a count, then one tone index a 140 Hz tick (0 silent) | 55, all 52 game sounds present [M: this design]; `DPPISTOL` 27 ticks |

Upstream's sound bank and DOC plans [R `s_sound65.s:1-13`] are not used.

### The converter (`tools/sound/fxconv.py`)

For each of the 52 game sounds, in upstream's order (`sfxPriority`'s [R
`s_sound65.s:1274-1285`]), one script:

| Per 140 Hz tick (78.75 samples at 11,025 Hz) | Rule |
| --- | --- |
| Tone | The `DP` tick's tone index, through the PC speaker's divisor table (Chocolate Doom's published table, `divisors[]` of `src/i_pcsound.c`, PIT clock 1,193,181 Hz; native-sound 4.5's quarter-tone reconstruction is within 7.4 cents of it [M: `docs/m11-parts/fxconv.md` 4]), to an AY period at the PAL native PSG clock, 2,031,250 Hz (this README, "Facts checked in the HDL"); a byte of 0 or 128 and up: no tone. NTSC plays the same periods, 8 cents sharp [A: inaudible on effects] |
| Level | The `DS` tick's RMS in dB, to the music's attenuation unit (0.5 dB, 80 silent), so the effects use the music's `LEVEL` table; 0 dB is a full-scale sine; the DS's first and last 16 samples are DMX's padding and skipped |
| Noise | On when the `DS` tick's zero crossings pass 2,500 a second, or when the tick has no tone after the quantization (the DS's sound past the DP's tones, a shot's or an explosion's decay, is heard as noise); its period from the crossing rate, 1-31 (31 with no crossing) |
| Length | The longer of the two lumps; the tail after the last tick within 40 attenuation units (20 dB) of the effect's loudest trimmed; a tick at 80 or with neither tone nor noise is silent (0, 80, 0), and silent ticks at the end dropped |

Then **quantized for the ring**: a change of level under one AY step, or
a tone change held for one tick only, is dropped until the ring's budget
holds: **every 42 ticks (300 ms) of any script take at most 128 bytes**
(one ring, refilled once a frame: `docs/SCREENS.md` 3). The rules go in
11 stages (L, H, N): an attenuation change under L half-dB units dropped
unless from or to 80, a tone held at least H ticks, a noise period
change under N dropped unless it turns the noise on or off; each script
takes the first stage that holds the budget (`tools/sound/fxconv.py`,
`STAGES`). The converter fails, naming the effect, if one cannot. The
prototype's format took up to about 580 B a second (`BGACT`: 527 B over
127 ticks [M: sound, `sfx_table.md`]); this one averages 283 B a second
over the 52 effects, 128 B in the worst 300 ms [M:
`docs/m11-parts/fxconv.md` 3].

**The script format** (version 1; little endian):

| Bytes | Meaning |
| --- | --- |
| header, 4 | version 1; flags (bit 0 tuned, bit 1 uses noise); the length of the steps |
| `$00`-`$3F` | wait 1-64 ticks |
| `$40`-`$4F` and fields | set: bit 0 the tone period follows (2 bytes, 0 = tone off), bit 1 the attenuation (1 byte, 0-80), bit 2 the noise period (1 byte, 0 = noise off), bit 3: one wait follows the fields and the script ends when it expires |
| `$FF` | end: the voice falls silent |

A voice starts at (tone 0, attenuation 80, noise 0); the header's last two
bytes are the length of the steps after it.

The scripts go into one bank file, `SFX.1` (bank `SFX`, 103), with a
directory of 52 entries (bank address, length), the volume table (below)
and nothing else. `SFX.1` is 11,385 B [M: `docs/m11-parts/fxconv.md`]:
the directory (52 × 4 B, u16 address and u16 length) at `$0200`, `VATT`
at `$02D0`, the scripts from `$0350`.

**The second model (`tools/sound/fxmodel.py`)** reads `DOOM1.WAD`, the
`DS` and `DP` lumps, with its own readers (no code shared with
`fxconv.py` or `mus.py`), computes each tick's wanted tone, level and
noise by the rules above, applies the quantization rules by its own code,
and gives the per-tick state. The test decodes each script with a third,
small decoder and requires the per-tick state to equal the model's
exactly for every automatic script (as S1's two MUS decoders, above).

### The ten tuned effects

The 10 most frequent starts in demo3, DEMO1, DEMO2 and the tour (1,304
starts, 36 distinct effects [M: this design, `docs/SCREENS.md`
appendix A]):

| Effect | Starts | Priority [R `s_sound65.s:1278-1285`] |
| --- | ---: | ---: |
| `BGACT` (imp, active) | 169 | 120 |
| `PISTOL` | 162 | 64 |
| `POSACT` (zombie, active) | 161 | 120 |
| `SHOTGN` | 88 | 64 |
| `PLPAIN` | 77 | 96 |
| `FIRSHT` (imp fireball) | 76 | 70 |
| `FIRXPL` (fireball hit) | 75 | 70 |
| `STNMOV` (moving floor) | 51 | 119 |
| `POPAIN` (zombie pain) | 41 | 96 |
| `BGSIT2` (imp sight) | 36 | 98 |

`tools/sound/fxtune.txt` holds a tuned script for each, in a text form
one step a line: ticks, then any of `tone=HZ` or `period=N`, `att=DB`
(0-40 dB), `noise=N` (1-31, 0 off), e.g.

    PISTOL
    2  noise=4 att=0
    3  att=6
    4  noise=9 att=12
    6  att=24
    end

`fxconv.py` takes the tuned script in place of the automatic one when the
file has the effect (flag bit 0), and the test disk keeps both. The
first tuned versions are written in part `fxconv` from the WAV renders
(`build/sound/fx/*.wav`, by `ayrender.py` from the model's AY log); they
are a starting point for the owner's ear.

**How the owner tunes them (milestone 12).** Boot `SOUNDS.hdv` (below)
with the Doom profile; choose an effect; `T` switches between its tuned
and its automatic version; play each, near and far, left and right, with
and without music. Edit `tools/sound/fxtune.txt` on the host (each
effect's steps, as above), run `python3 tools/sound/fxdisk.py`, copy
`build/sound/SOUNDS.hdv` to the card, boot again. The disk's screen shows
each effect's version (a checksum of its script), so a photo of the
screen records what was heard. Notes go into
`docs/results/sfx-tuning-<date>.md`.

### The player (`src/sound/fx.s`, model `tools/sound/fxplay.py`)

| Part | Where | Does |
| --- | --- | --- |
| `fx_step` | The VBL interrupt (`pl_vbl`, `docs/SCREENS.md` 2.3), before `snd_tick` | Its own tempo fraction (the music's: 2 + 52,135/65,536 ticks an interrupt on PAL, 2 + 22,043/65,536 on NTSC; this README, "The player") (it runs in an interrupt where a voice is active or ending; PAL or NTSC from `CLK_STD`); each active voice runs its ticks from its ring (a tick without all its bytes holds the voice, silent, for the rest of the interrupt); then compose chip 3 into its own register list: R0-R5 the three periods, R6 the noise period of the loudest voice with noise on (the lowest min(80, step + `VATT`), the first of a tie; unchanged when none), R7 the mixer (tone and noise bits of the three voices), R8-R10 `LEVEL[min(80, step attenuation + VATT[volume])]`. No I/O; the write list is built here, so `fx_burst` follows the music's burst with no computation between; with no voice active it returns at once. A voice that ends or is stopped gets level 0 once and goes idle |
| `fx_burst` | The same interrupt, right after `snd_tick`'s burst | The registers of the list that differ from its shadow, ascending, to the second AY of VIA-B (`$C48x`, ORB `$17` latch, `$16` write, `$14` idle; this README, "Addressing"), with S2's 41-cycle loop; with the shadow invalid (`FX_INVAL`) and a voice active or ending, all of R0-R10, then the shadow is valid; nothing while `FX_HOLD` is set or `FX_ON` is 0 |
| `fx_service` | The main loop, once a frame, in every frame image (`docs/SCREENS.md` 2.1) | The channels' mailboxes (below, "The game side"), each in order: a stop silences the channel's voice; a start frees the channel's voice, chooses one, copies the script's first 128 bytes (its 4-byte header with them, taken at once) into its ring and sets the voice active last; a volume sets the voice's attenuation; the mailbox is then empty. Every frame each active ring is refilled through a read window, a page of the ring published at a time, as S2's `snd_refill`. With `FX_ON` 0 it empties the mailboxes and starts nothing. The copies run in the card (`fx_copy`, `fx_volume`): a RAMRD window hides W |
| `fx_song` | Wherever the game starts a song (main loop) | `FX_HOLD` set; S2's `snd_start`; `FX_INVAL` set; `FX_HOLD` cleared; returns `snd_start`'s carry and A. `snd_start` ends with `reset_chips`, a burst of R0-R12 of all four chips from the main loop with interrupts on (`src/sound/player.s:1008`, `:1056-1101`): an effect burst inside it would tear VIA-B's latch sequence, and after it chip 3 no longer holds what the effect player's shadow says |
| `fx_init` | Boot, after `snd_probe` and `snd_init`; A = `snd_probe`'s answer | `FX_ON` 1 when `snd_probe` answered `SND_MUSIC` (native mode), else 0; the shadow invalid (before any song the chips hold the reset's values, R7 0 with every noise on, not the `$38` of S2's first burst); no voice active |

**No effect, no write.** `fx_burst` writes nothing while no voice is
active (an invalid shadow stays invalid until a voice starts), `fx_step`
does no I/O, and `snd_tick` (S2's player) is unchanged, so a run without
effects gives S2's AY log byte for byte. With effects, chips 0-2 still
get exactly the music's writes in each interrupt; chip 3's follow them
in the same interrupt.

**No native mode.** With `SND_NO_MUSIC` the card keeps one AY behind
each VIA and ORB `$17` reaches VIA-B's only AY, the music's chip 2
(`snd_probe` detects the mode that way, `src/sound/probe.s:71`): the
effects are off (`FX_ON` 0), as the music is. Effects on a plain
Mockingboard would be the owner's call; not built.

**Stereo by voice** (revised 2026-10-02, the owner's answer to
`docs/SCREENS.md` 10, row 6). One table, `tables.FX_VOICES`, gives chip
3's voices their sides and their pans in the Doom profile: **A left (pan
5: left 16/16, right 10/16), B right (pan 11: left 9/16, right 16/16), C
centre (pan 8: both 16/16)**. The model (`fxplay.py`), the 65C02 player
(`fx.s`, through `tables65.py`'s `FX_VOICE_*` and `FX_SEP_*` equates in
`build/sound65/tables.inc`), the test disk's voice names (`fxdisk.py`)
and the effects' renders (`ayrender.DOOM_PANS`; the music's chips keep
the menu's defaults) read it. The menu's own default for chip 3's C is 5,
so the owner sets it to 8 in the Phasor menu or the profile (above, "The
Doom configuration profile").

The voice is chosen at the start (`tables.fx_voice_order`): a separation
below 96 tries the left voice first, 96 to 160 the centre, above 160 the
right; a busy voice falls back to the nearest free voice in pan: a side
to the centre, then the other side; the centre to the side the
separation leans to, 128 exactly to the left. So the orders are A, C, B
(below 96); C, A, B (96-128); C, B, A (129-160); B, C, A (above 160). The
channel's own voice is freed first, so with 3 channels and 3 voices there
is always one. Below 128 is the left (upstream's pan law: left = vol ×
(254 - sep) / 127, right = vol × sep / 127, `s_sound65.s:698-712`; sep =
128 - swing × sin(angle), swing 96, `:552-564`, so a source within about
20° of straight ahead or behind is in the centre band). Exactly 128 is
every sound without an origin and every sound of the player
(`s_sound65.s:221-235`: `PISTOL`, `SHOTGN`, `PLPAIN`, pickups, the menu,
the intermission), the most frequent: they now take C, the centre, one
voice for the whole sound. In `fx.s` three comparisons make the band 0,
1, 3 or 7, the offset of its order in one overlapping 11-byte string
(`fx_order`; `fx_service` 398 of its 400 B). The side is chosen at the
start only; `S_UpdateSounds`' new separation changes nothing, its volume
does.

**How many centred voices.** One. On the four captured runs (demo1-3 and
the tour: 1,076 starts, the reference's 8-channel stream played on 3
voices by length, an estimate), 51% of the starts are in the centre band
and 28% are exactly 128. With A left, B right, C centre, 65% of the
starts get the voice of their band, 22% a neighbour (a side for a centred
sound or the centre for a side's), 5% the opposite side (both nearer
voices busy) and 8% none (more than three at once in the reference; the
game's 3 channels evict by priority instead); with the menu's default
pans (C left) 34%, 49%, 9%. Two centred voices (A and C centred, B
right) give 61%, 29%, 2%, but no voice on the left at all: every left
sound plays in the middle. Three centred is mono.

**Volume.** `VATT[v]`, v 0-127 (upstream's volume: `snd_SfxVolume` × 8,
less with distance [R `s_sound65.s:565-618`]), is 40 log10(127 / v) in
the music's half-dB units, 80 at v = 0: the music's law (this README,
"What needs the owner's ear", "Loudness").

**Memory** (`docs/MEMORY_MAP.md` 4.2): voices `$E413-$E442` (16 B each),
`FX_ON`, `FX_HOLD`, `FX_INVAL` and the tempo fraction in `$E737-$E73B`,
rings `$E740-$E8BF` (3 × 128 B), `fx.s`'s card part (739 B: the
routines and chip 3's `want`, `shadow` and write list) in `$F505-$F8FF`
after S2's code, with `pl_vbl`: 983 of 1,019 B [M:
`docs/m11-parts/fxplay.md`]; `VATT` read from `SFX.1` through a window;
the interrupt's ring pointer and temporaries in zero page `$F7-$FC`,
`fx_service`'s in `$E73C-$E73F`; the channel table and the mailboxes
(3 × 4 B) in `$E8C0-$E8EF` (`docs/SCREENS.md` 4.4). `fx_service` (398 B
[M]) is a shared object of every frame image.

**Cost** [A on M]: an active voice writes about 1.6 registers an
interrupt [M: sound 4.5], so one effect adds about 80 writes a second at
50 Hz, 3.2 ms a second at 40.4 µs a write on F1.2.1; three voices about
10 ms a second; with FW-S1 about a fifth. `fx_burst` follows the music's
burst with no computation between, so the two share one slot-4 slowdown
tail when both write; an interrupt where only the effects write pays a
tail of its own (about 32 µs at the Doom profile's window 32, about 505
µs at the default 512; this README, "The Doom configuration profile").
`fxplay`'s checkpoint measures all of it.

Measured (part `fxplay`, `docs/m11-parts/fxplay.md` 6): one effect 3.66
ms/s in the interrupt, three 9.60; from the main loop 18.69 and 33.18
ms/s at window 512, 4.00 and 10.64 at window 32, 1.66 and 4.27 with
FW-S1; over D_E1M1 a burst the effects write alone pays a tail of 529 µs
(window 512) or 42 µs (window 32), one that shares the music's pays
none; the worst interrupt, three effects starting on D_INTRO's first
chord, 2,048 µs in the Doom profile (the music alone 1,549 µs).

### Results (the first half's acceptance, 2026-10-02)

On a2vm (`docs/SCREENS.md` 8.13, 8.14), all with 0 problems:

| Check | Result [M] |
| --- | --- |
| `fxconv` (`make -C src/native -f m11.mk fxconv`) | 52 scripts, `SFX.1` 11,385 B, every automatic script equal to `fxmodel.py` tick by tick; the five planted bugs caught |
| `fxplay` (`fxrun65.py --checkpoint`, `--planted`) | every effect alone and over each of the 13 songs equal to the models; no effect: S2's AY log byte for byte; the hold across `fx_song` (5 VBLs landed in it); a tone effect before any song; `--phasor-mb-only` no chip-3 write; the eight planted bugs caught |
| The music through the release's interrupt (`plclock.py --checkpoint`, since the final integration with `fx.s` linked, the effects on and none playing) | the 13 songs' AY logs equal to S2's; the worst interrupt 1,547.9 µs (S2 alone 1,543.8) |
| `fxchan` (`fxcap.py --check`, `--planted`) | demo3 1,218, DEMO1 2,290, DEMO2 1,273, the tour 137 and the menu's 709 calls equal (`S_UpdateSounds` included); 134 eviction cases, every path; 10,000 random sequences; the seven planted bugs caught |
| `fxdisk` (`fxdisk.py --check`, `--planted`) | `build/sound/SOUNDS.hdv` (143,360 B, SHA-1 `225f7d59`): places, left, right, tuned, music, NTSC, quit, no native mode; the four planted bugs caught |

**Cost on D_E1M1** (`fxrun65.py --cost`, ms a second taken from the main
loop; the Doom profile's window 32, then window 512 and FW-S1): the music
alone 5.99 (17.73, 3.17); with the effects at demo3's measured start times
(132 starts in 20 s) 16.24 (38.56, 7.49); with three effects started
together every 45 VBLs 14.80 (35.91, 6.80). The worst interrupt at
demo3's rate 1,111.5 µs (1,114.5, 339.0).

**Sizes:** `fx.s`'s card part 739 B, with `pl_vbl` 983 of `$F505-$F8FF`'s
1,019 B; `fx_service` 396 of 400 B in every frame image; `fx_chan` 1,085
of 1,100 B (tic image), 970 in `MENUW` with `fx_pcache` 85; the card
state as "Memory" above; `SOUNDS.SYSTEM` code 2,422 B, data 1,056 B.

**The centre (2026-10-02).** Chip 3's voices became A left, B right, C
centre ("Stereo by voice"): `fxrun65.py --checkpoint --jobs 2` 0 problems
(every scenario as above; the stereo scenario now each band and its
bounds, the four fallbacks and the channel's own voice; no effect: S2's
AY log byte for byte for the 13 songs; worst interrupt 2,047.9 µs);
`--planted --jobs 2` all nine caught (three new on the choice: the sides
inverted, 128 falling back to the right, 96 to the left voice);
`fxdisk.py --check --jobs 2` and `--planted --jobs 2` 0 problems
(`SOUNDS.hdv` SHA-1 `05c7cac4`; the left check now also reads the voice
on the screen after RETURN, A and C: `C CENTRE`, `A LEFT`, `C CENTRE`);
`fx_service` 398 of 400 B; S2's `sound.lc` and `sound.main` byte for byte
the same after `tables.inc` gained the equates.

**For the owner's ear (milestone 12).** Copy `build/sound/SOUNDS.hdv` to
the card and boot it with the Doom profile (`vtw.slowdown.cycles=32`,
`PROFILE.TXT` on the disk); the keys are in "The test disk" below. The
ten tuned effects are tuned as "The ten tuned effects" says: `T` toggles
an effect between its tuned and automatic scripts, `R` repeats it every
second, `1`-`3` the distance, `A`/`B` the side, `M` the music under it;
edit `tools/sound/fxtune.txt`, run `python3 tools/sound/fxdisk.py`, boot
again, and note what was heard (with the screen's `SUM`) in
`docs/results/sfx-tuning-<date>.md`.

### The game side (`src/native/fx_chan.s`, model `tools/sound/fxchan.py`)

Upstream's channel logic [R `s_sound65.s:177-670`]: `S_StartSound`,
`S_StartSound2` (the one fake mobj `FM` [R `:181-198`]), the pickup
flag, the kill of the origin's earlier sound of the same kind,
`getChannel`'s free channel, same origin, then priority [R `:284-334`],
`S_StopSound`, `S_UpdateSounds` [R `:377-423`], and
`S_AdjustSoundParams` (distance 160 to 1,200 map units, map 8's floor of
15, the separation from the angle with the swing 96 [R `:425-618`]) on
milestone 6's math. `NUM_CHANNELS` is 3 in the game and 8 in the
comparison build `FXCH8` (upstream's [R `:30`]). Nothing of the DOC is
kept [R native-sound 4.5 "Drop"]. The routines read their arguments in
`GA_*` and ask `s2t_pos` for every position, the listener as the handle
$FFFE; `MENUW` links them with `-D FXC_NOSEP` and `fx_pcache`
(`docs/m11-parts/fxchan.md` 2). The channel record (12 B: the sound, the
origin's kind with the pickup flag in bit 7, its handle, its last x and
y) and `LS_ON`, `SND_SFXVOL` after the mailboxes are `s2layout.py`'s
(`docs/SCREENS.md` 4.4; wave 4, FXCHAN-1 and -2).

**One mailbox a channel** (4 B: flags, sound, volume, separation), so a
frame's decisions are bounded by `NUM_CHANNELS` and none is dropped:
`stopChannel`, whatever its cause, sets *stop* and clears *start* and
*volume*; a start sets *start* with its sound, volume and separation (it
implies stopping the channel's voice); `I_UpdateSoundParams` sets
*volume* (its separation is not used: the side is chosen at the start).
`fx_service` empties them once a frame (above).

**`isPlaying`** is the channel's voice active **or** a start in its
mailbox: `S_UpdateSounds` runs after the frame's tics and before
`fx_service`, so without the second half it would stop every sound the
frame's tics started.

It runs in the tic phase from milestone 10's hooks, `sc_update` once a
frame after the tics (`docs/SCREENS.md` 3, 4.7); the same object is
linked into the menu's image, whose sounds start from `M_Responder` and
whose paused frames run `sc_update` from the channel table's last
positions.

### The test disk `SOUNDS.hdv` (`tools/sound/fxdisk.py`)

`SOUNDS.SYSTEM` (`src/sound/sounds.s`, `sounds.cfg`; with S2's player,
`pl_vbl` and `fx.s` at the game's places), like `MUSIC.SYSTEM` above:
the mouse card, RamWorks banks 1-103, the probe, `SFX.1` into bank
`SFX` at `$0200` and the ten tuned effects' automatic scripts from
`SFXAUTO.1` after it (`$2E79-$374A`), `E1M1.AY` into bank 100 at
`$1000`, ProDOS's card saved in bank 1, `snd_init`, `fx_init`, PAL or
NTSC (`pl_detect`). The disk (143,360 B): `SOUNDS.SYSTEM`, `PRODOS`,
`SFX.1`, `SFXAUTO.1`, `E1M1.AY`, `PROFILE.TXT`.

```
DOOM GS: THE EFFECTS ON THE PHASOR
PAL //E  PHASOR NATIVE  CHIP 3 MUSIC REP
  PISTOL T     PLPAIN T     PDIEHI
  ...  (52 effects, 3 columns of 18; > the chosen; T tuned, A a tuned
        effect set to its automatic script)
POSACT AUTO  SUM 63AB MID  B RIGHT
ARROWS CHOOSE  RETURN PLAY  A B C VOICE
1 NEAR 2 MID 3 FAR  T TUNED  R REPEAT
M MUSIC  S STOP  V PAL/NTSC  Q QUIT
```

Row 20: the chosen effect, its version, `SUM` (a checksum of the script
the bank's directory gives: for each byte the 16-bit sum rotated left
one bit, then the byte added), the distance, and after a play the voice
it got. A play stops every effect, then starts the chosen one by the
game's mailbox (channel 0), one effect at a time.

| Key | What |
| --- | --- |
| Up, down | The previous or next effect; left, right a column |
| RETURN | Play it as a source ahead (separation 128): the game's rule gives voice C, the centre |
| A, B | Play it on A (separation 64, left) or B (200, right) |
| C | Play it on C (the centre) by the fallback: channel 0 takes A and channel 1 the effect at separation 64 in one service (A busy: C), then channel 0 is stopped, interrupts masked: A never sounds |
| 1, 2, 3 | Distance: volume 127, 63 (about 680 units), 6 (1,150); the playing effect's volume follows |
| T | Its tuned or automatic script (the ten tuned only): its directory entry in the bank is rewritten |
| R | Repeat the last play every second (50 or 60 VBLs), to compare by ear |
| M | `D_E1M1` under the effects (`fx_song`), or silence (`snd_stop`) |
| S | Stop every effect, and the repeat |
| V | PAL or NTSC: the effects' tempo (`pl_clkset`) and the song again on the other tables |
| Q, ESC | Quit as `MUSIC.SYSTEM` (the chips reset, ProDOS's card back, the Phasor in Mockingboard mode) |

On a card without native mode the second line says `NO EFFECTS: NO
NATIVE MODE`, the song is not loaded, and no key writes an AY register.

`fxdisk.py --check` runs it on a2vm (MLI trap, `--irq-bounds`, the AY
log, a write log of the effects' state and the program's step marker):
the program's steps equal a model of the keys, each in its visit, and
every interrupt's writes equal the models' (`fxplay.py`'s for chip 3,
S2's for the music): every effect on the centre and left voices
(RETURN, A, C) and on the right one at the three distances, the voice
named on the screen after the first plays, the ten tuned tuned and automatic, every effect
over `D_E1M1` with V and M, NTSC with the volume, the repeat, S and
ESC, q, and `--phasor-mb-only` (no AY write past the probe's and
`snd_init`'s); the screen's rows; the quit as `MUSIC.SYSTEM`'s; four
planted bugs caught (`docs/m11-parts/fxdisk.md`).

### Tests

| Test (`tests/test_m11_fx*.py`; `wip_test_m11_fx*.py` while built) | What it checks |
| --- | --- |
| `fxconv` | Every script against `fxmodel.py`, tick by tick; the ring budget; the tuned scripts against `fxtune.txt`; planted bugs |
| `fxplay` | Every effect alone (PAL, NTSC, three volumes, each voice) and over each of the 13 songs: every interrupt's AY writes equal the models' (S2's `player.py` for chips 0-2, `fxplay.py` for chip 3); no effect: S2's log byte for byte; the IRQ bounds; underrun; an effect held across `fx_song`; a tone effect before any song; `--phasor-mb-only`; the voice choice (each band and its bounds, the fallbacks, the channel's own voice; on the model also every separation with every set of busy voices against the nearest voice in pan); the mailboxes' rules; the publish order on the write log; `fx_isplaying`'s answers; the cost and the tail (`tools/sound/fxrun65.py --cost`) |
| `fxpan` | Chip 3's table (A left 5, B right 11, C centre 8) against the HDL's pan law (8 the only centred pan), the bands, the generated equates, the renders' mix (`DOOM_PANS`: chip 3's C centred, the music's chips the menu's), the profile's keys |
| `fxchan` | Every captured call of demo3, DEMO1, DEMO2 and the tour (`FXCH8`, the reference's channel table and `isPlaying` answers injected) equal; every `S_UpdateSounds` (captured with `jumps=1`) equal; `ref816 --call` eviction cases with every path of `S_StartSound` and `getChannel` covered; a start and the same frame's `sc_update`; the 3-channel build equal to `fxchan.py` on the captured streams and 10,000 random sequences; the menu's paused frame |
| `fxdisk` | The disk on a2vm: the keys' steps against a model of the keys, every effect left and right at three distances, the ten tuned both ways, over the music with V and M, NTSC, the repeat, the quit, `--phasor-mb-only`; the screen; the planted bugs |

`tests/test_sound_*` stay as they are and green.

### Open problems

- The PC speaker's divisor table is read from Chocolate Doom's
  `src/i_pcsound.c` over the network; no copy is kept offline.
- One noise generator for three voices: the loudest voice's period wins,
  a choice to judge by ear.
- The centre needs the owner's setting: with the menu's default pans
  (chip 3's C at 5) the centre voice leans left as before (16/16,
  10/16). The profile (`PROFILE.TXT`) says how to set `phasor.pan.12=8`;
  the program cannot read or set the pans.
- Two centred sounds at once: the second takes a side voice (128 the
  left), a choice to judge by ear; the estimate in "Stereo by voice"
  puts 22% of the starts on a neighbouring voice.
- The renders (`build/sound/fx/*.wav`) are on voice A, pan 5, as
  before; they do not show the centre.
- No effects on a card without native mode.
- An effect starts at the frame after its tic, about 60-165 ms later on
  f121 (`docs/SCREENS.md` 3).
- Nothing has been heard yet; the owner tunes at milestone 12.
