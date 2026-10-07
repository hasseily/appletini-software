# Music and sound effects of DOOM on the Phasor: host tools

These tools turn the WAD's MUS songs into compact streams of AY voice
commands for the Phasor, and its sound effects into AY scripts for the
fourth chip. The 65C02 side is [`src/sound`](../../src/sound/README.md)
(the music player and the effects player) and `src/native/fx_chan.s`
(the game's channel logic).

The source is the WAD's `D_*` MUS lumps, its `GENMIDI` bank and its
`DS*`/`DP*` effect lumps, never upstream's DOC song units or its SoundFont
converter. All the code here is original, written from the published MUS,
MIDI, WAD, GENMIDI and DMX layouts and from the Appletini's HDL of the
Phasor. Standard library only.

## Modules

| Module | What |
| --- | --- |
| `mus.py` | The WAD directory, upstream's song list (`UPSTREAM_SONGS`), the MUS parser |
| `genmidi.py` | GENMIDI: carrier envelope, level, note offset, fixed note |
| `tables.py` | Machines, clocks, the voice layout, period, bend, level and volume tables, tempo, chip 3's effect voices (`FX_VOICES`, `FX_SEP_*`) |
| `mus2ay.py` | The converter: MUS to a song file |
| `player.py` | The song file (`SongFile`): header, envelope and drum tables, stream |
| `songs.py` | The 13 songs, converted from the WAD at build time, for the game disk's `SONGS.1` (`tools/native/pldisk.py`) |
| `tables65.py` | The player's tables as a ca65 include (`build/sound65/tables.inc`), from `tables.py` |
| `fxconv.py` | The effects converter: `SFX.1` (bank 103) and its listing |
| `fxtune.txt` | The ten hand-tuned effect scripts |
| `fxchan.py` | The channel logic's generated include (`fxchan.inc`), read from upstream's sources at build time |

They run as part of the game's build (`build.sh`); `DOOM1.WAD` comes from
`python3 tools/fetch_upstream.py`. Run by hand, from `demos/doom_gs`:

```
make -C src/sound                                # tables.inc, player.o, probe.o
make -C src/native -f m11.mk part P=fxconv       # SFX.1 and SFX.lst
python3 tools/sound/fxconv.py [--wad FILE] [--tune FILE] [--out DIR]
python3 tools/sound/fxchan.py --inc OUT
python3 tools/sound/tables65.py OUT.inc
```

## Facts checked in the HDL

`FW/` is the Appletini firmware snapshot (`appletini-one-main`).

- **PSG clock.** The YM2149 cores get one clock enable an Apple bus cycle
  (`data_en`), plus a second one in Phasor native mode:
  `FW/hdl/apple/mockingboard.sv:262` (`psg_clock = via_bus_clock ||
  psg_ce_extra_q`) and `:542-549` ("The Phasor native mode doubles the
  PSG clock"). So the PSG clock is 2 x the bus clock in native mode and
  the bus clock in Mockingboard mode. The bus clock is 1,015,625 Hz on a
  PAL //e and 1,020,484 Hz on an NTSC //e: native mode is 2,031,250 Hz
  (PAL) or 2,040,968 Hz (NTSC). The PAL machine is 0.5% (8 cents) lower,
  so the player picks a period table at start.
- **Tone, noise, envelope.** A /8 prescaler (`FW/hdl/apple/YM2149.sv:139-162`);
  tone f = clock / (16 P) (`:203-226`), P = 0 holds the output at the
  mixer bit, which silences a channel whose tone is on (`:218-220`);
  noise steps every 16 x NP clocks (`:169-195`); the envelope steps every
  8 x EP clocks over 32 levels (`:230-342`).
- **The noise LFSR is not the AY's.** The core shifts in bit0 ^ bit2
  (`YM2149.sv:187`); that sequence repeats after 114,681 steps, where the
  AY-3-8910's bit0 ^ bit3 gives the maximal 131,071. Noise still sounds
  like noise.
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
  music and no effects (`src/sound/README.md`, "No music"). The tools use
  these chip numbers.

## Voice layout

There is one layout, native12, with the card in native mode:

| Layout | Melodic voices (0-) | Drum voices | Effects |
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
0.5 dB and 80 (40 dB) is silent. A tick is 1/140 s, the MUS unit. MUS
has no loop point: the songs loop from their start (loop offset 0).

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

### The converter

`mus2ay.py`'s docstring gives its rules: voice allocation (same channel
and note; else an idle voice, preferring one that holds the note's pitch,
then one with its envelope, then the longest idle; else the release that
ends first; else a steal that keeps the bass and takes the oldest note of
the busiest channel), pitch (GENMIDI's note offset and fixed notes
applied, as DMX does), loudness (40 log10(v / 127) for velocity, volume
and expression, plus the carrier level), the instruments' software
envelopes, the drum recipes (`mus2ay.DRUMS`) and MUS's edge cases.
Volume and bend changes reach the voices holding a note of the channel;
notes in their release keep their level and pitch.

### The player

`src/sound/player.s` plays the song files. Each VBL interrupt:

1. A note that started and ended in the last interrupt starts its release
   now (every note is heard for at least one interrupt); the voice flags
   are cleared.
2. Tempo: add TEMPO_FRAC to a 16-bit fraction; run TEMPO_INT ticks plus
   the carry. PAL: 2 + 52,135/65,536 ticks an interrupt (2.795520, the
   exact 140 Hz x 20,280 cycles / 1,015,625 Hz); NTSC: 2 + 22,043/65,536.
   The video frames are 50.080 Hz (PAL, 312 lines of 65 cycles) and
   59.923 Hz (NTSC, 262 lines).
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

The first burst, at `snd_start`, writes R0-R12 of the four chips:
periods and levels 0, mixer `$38` (tones on, noises off, so a tone-only
drum needs no mixer write). Drum envelope periods are stored for the PAL
clock; on NTSC a loud drum decays 0.5% faster.

## What needs the owner's ear

- **The mix.** Heard on the card: "Music sounds great", the volume "a
  little low". A gain for each song that brought every song's loud notes
  to level 15 was refused: "Drums now are too weak, and overall
  everything is flat." Keep this mix; any louder one must keep the drums'
  balance with the melody and must not clamp notes at full level.
- **Instrument mapping.** Every program is a square wave with a software
  envelope from its GENMIDI carrier (attack, decay, sustain, release).
  The modulator, feedback, the second voice of double-voice programs and
  the fine tune are not used, so timbres differ only by envelope and
  loudness. The OPL rates are converted with the YM3812 manual's table
  (an assumption, not measured).
- **Programs that are effects**: D_E1M5 uses Reverse Cymbal (119) and
  Guitar Fret Noise (120) as tones; noise might suit them better.
- **Drums** (`mus2ay.DRUMS`): a hand-made guess per GM note (tone note,
  noise period, decay). The kick is a fixed 55 Hz tone with no pitch
  sweep. Hits of -6 dB and louder use the envelope generator.
- **Loudness.** Velocity, volume and expression follow 40 log10(v/127);
  DMX's own curve is not known here.
- **Pitch bend range** is taken as +-2 semitones (D_E1M1's guitars).
- **Timing.** Notes move to the next interrupt (at most 20 ms late on
  PAL); a note shorter than an interrupt still sounds for one.

## The Doom configuration profile

The game wants a profile with `vtw.slowdown.cycles=32` (the slot-4
slowdown window after each AY burst: 32 cycles, 31.5 us, in place of the
default 512, 504 us) and chip 3's pans `phasor.pan.10=5`,
`phasor.pan.11=11`, `phasor.pan.12=8` (A left, B right, C centre: "Stereo
by voice" below; only C differs from the menu's default, 5). The game disk
carries no profile; the owner makes it once. Read in appletini-one F1.2.1
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

A DOOM profile without the centre: Choose profile, `DOOM`; Phasor tab, AY3
C, RETURN; Profiles tab, "Save to current profile"
(`config_menu_profiles.c:647-665`: every current setting, the loaded
window 32 with them). Or edit its line `phasor.pan.12=5` to
`phasor.pan.12=8` and choose `DOOM` again. A pan changed in the Phasor
tab alone is saved in `0:/appletini_cfg.txt` only
(`config_menu_phasor.c:338-341`, `config_menu.c:3913-3918`), so the next
"Choose profile" sets it back.

Undo: choose another profile, or set the lines back (512,
`phasor.pan.12=5`) and choose `DOOM` again.

## Effects (S4)

The effects are generated from the WAD automatically, the 10 most
frequent hand-tuned, and play on chip 3, one voice left, one right and
one centred ("Stereo by voice"). With no effect playing, chips 0-2 get
exactly the music's writes and chip 3 none.

### Sources

| Lumps | What | Facts |
| --- | --- | --- |
| `DS*` | Digital effects: DMX format, a format word (3), the sample rate, the sample count, then 8-bit unsigned samples | 55 in `DOOM1.WAD`, 52 of them the game's sounds (`CONST_SFX_PISTOL` .. `GETPOW`, upstream's `offsets.inc`); `DSBDOPN`, `DSBDCLS`, `DSITMBK` are not; 11,025 Hz but `DSITMBK` 22,050 |
| `DP*` | PC-speaker effects: a zero word, a count, then one tone index a 140 Hz tick (0 silent) | all 52 game sounds present; `DPPISTOL` 27 ticks |

### The converter (`tools/sound/fxconv.py`)

For each of the 52 game sounds, in upstream's order (`sfxenum_t`), one
script:

| Per 140 Hz tick (78.75 samples at 11,025 Hz) | Rule |
| --- | --- |
| Tone | The `DP` tick's tone index, through the PC speaker's divisor table (Chocolate Doom's published table, `divisors[]` of `src/i_pcsound.c`, PIT clock 1,193,181 Hz), to an AY period at the PAL native PSG clock, 2,031,250 Hz; a byte of 0 or 128 and up: no tone. NTSC plays the same periods, 8 cents sharp |
| Level | The `DS` tick's RMS in dB, to the music's attenuation unit (0.5 dB, 80 silent), so the effects use the music's `LEVEL` table; 0 dB is a full-scale sine; the DS's first and last 16 samples are DMX's padding and skipped |
| Noise | On when the `DS` tick's zero crossings pass 2,500 a second, or when the tick has no tone after the quantization (the DS's sound past the DP's tones, a shot's or an explosion's decay, is heard as noise); its period from the crossing rate, 1-31 (31 with no crossing) |
| Length | The longer of the two lumps; the tail after the last tick within 40 attenuation units (20 dB) of the effect's loudest trimmed; a tick at 80 or with neither tone nor noise is silent (0, 80, 0), and silent ticks at the end dropped |

Then **quantized for the ring**: **every 42 ticks (300 ms) of any script
take at most 128 bytes** (one ring, refilled once a frame). The rules go
in stages (L, H, N), `fxconv.STAGES`: an attenuation change under L
half-dB units dropped unless from or to 80, a tone held at least H ticks,
a noise period change under N dropped unless it turns the noise on or
off; each script takes the first stage that holds the budget. The
converter fails, naming the effect, if one cannot. The scripts average
about 283 B a second.

**The script format** (version 1; little endian):

| Bytes | Meaning |
| --- | --- |
| header, 4 | version 1; flags (bit 0 tuned, bit 1 uses noise); the length of the steps (u16) |
| `$00`-`$3F` | wait 1-64 ticks |
| `$40`-`$4F` and fields | set: bit 0 the tone period follows (2 bytes, 0 = tone off), bit 1 the attenuation (1 byte, 0-80), bit 2 the noise period (1 byte, 0 = noise off), bit 3: one wait follows the fields and the script ends when it expires |
| `$FF` | end: the voice falls silent |

A voice starts at (tone 0, attenuation 80, noise 0).

**`SFX.1`**, the bank file of bank 103 (`SFX`), loaded at `$0200`: the
directory (52 × 4 B, u16 bank address and u16 length of the script with
its header) at `$0200`, `VATT` (128 B, below) at `$02D0`, the scripts from
`$0350`. `SFX.lst` lists each effect's lengths, quantization stage,
bytes and worst 42-tick window.

### The ten tuned effects

The 10 most frequent starts in demo3, DEMO1, DEMO2 and a tour (1,304
starts, 36 distinct effects):

| Effect | Starts | Priority |
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

`tools/sound/fxtune.txt` holds a tuned script for each, one step a line:
ticks, then any of `tone=HZ` or `period=N`, `att=DB` (0-40 dB), `noise=N`
(1-31, 0 off); a field not given keeps its value; `end` closes it, e.g.

    PISTOL
    2  period=324 noise=8 att=0
    2  period=364 att=4
    ...
    end

`fxconv.py` takes the tuned script in place of the automatic one (flag
bit 0). To change one: edit `fxtune.txt`, rebuild `SFX.1` (`make -C
src/native -f m11.mk part P=fxconv`) and the game disk
(`python3 tools/native/playdisk.py`, or `build.sh`).

### The player (`src/sound/fx.s`)

| Part | Where | Does |
| --- | --- | --- |
| `fx_step` | The VBL interrupt (`pl_vbl`, `src/native/pl_irq.s`), before `snd_tick` | Its own tempo fraction (the music's: 2 + 52,135/65,536 ticks an interrupt on PAL, 2 + 22,043/65,536 on NTSC; PAL or NTSC from `CLK_STD`); each active voice runs its ticks from its ring (a tick without all its bytes holds the voice, silent, for the rest of the interrupt); then compose chip 3 into its own register list: R0-R5 the three periods, R6 the noise period of the loudest voice with noise on (the lowest min(80, step + `VATT`), the first of a tie; unchanged when none), R7 the mixer, R8-R10 `LEVEL[min(80, step attenuation + VATT[volume])]`. No I/O; with no voice active it returns at once. A voice that ends or is stopped gets level 0 once and goes idle |
| `fx_burst` | The same interrupt, right after `snd_tick`'s burst | The registers of the list that differ from its shadow, ascending, to the second AY of VIA-B, with the music's 41-cycle loop; with the shadow invalid (`FX_INVAL`) and a voice active or ending, all of R0-R10; nothing while `FX_HOLD` is set or `FX_ON` is 0 |
| `fx_service` | The main loop, once a frame, in every frame image | The channels' mailboxes ("The game side"), each in order: a stop silences the channel's voice; a start frees the channel's voice, chooses one, copies the script's first 128 bytes (its 4-byte header taken at once) into its ring and sets the voice active last; a volume sets the voice's attenuation; the mailbox is then empty. Every frame each active ring is refilled through a read window, a page of the ring published at a time. With `FX_ON` 0 it empties the mailboxes and starts nothing |
| `fx_song` | Wherever the game starts a song (main loop) | `FX_HOLD` set; `snd_start`; `FX_INVAL` set; `FX_HOLD` cleared; returns `snd_start`'s carry and A. `snd_start` ends with a burst of R0-R12 of all four chips from the main loop with interrupts on: an effect burst inside it would tear VIA-B's latch sequence, and after it chip 3 no longer holds what the shadow says |
| `fx_init` | Boot, after `snd_probe` and `snd_init`; A = `snd_probe`'s answer | `FX_ON` 1 when `snd_probe` answered `SND_MUSIC`, else 0; the shadow invalid; no voice active |
| `fx_stopall`, `fx_isplaying`, `fx_copy`, `fx_volume` | Main loop | Every voice stopped; the channel logic's `isPlaying`; the copies through a RAMRD window, run from the card |

`fx.s`'s header lists the voice record and the entry conditions.

**No native mode.** With `SND_NO_MUSIC` the card keeps one AY behind
each VIA and ORB `$17` reaches VIA-B's only AY, the music's chip 2: the
effects are off (`FX_ON` 0), as the music is.

**Stereo by voice.** One table, `tables.FX_VOICES`, gives chip 3's voices
their sides and their pans in the Doom profile: **A left (pan 5: left
16/16, right 10/16), B right (pan 11: left 9/16, right 16/16), C centre
(pan 8: both 16/16)**. `fx.s` reads it through `tables65.py`'s
`FX_VOICE_*` and `FX_SEP_*` equates. The menu's own default for chip 3's
C is 5, so the owner sets it to 8 in the Phasor menu or the profile
(above, "The Doom configuration profile"); without it the centre voice
leans left. The program cannot read or set the pans.

The voice is chosen at the start: a separation below 96 tries the left
voice first, 96 to 160 the centre, above 160 the right; a busy voice
falls back to the nearest free voice in pan: a side to the centre, then
the other side; the centre to the side the separation leans to, 128
exactly to the left. So the orders are A, C, B (below 96); C, A, B
(96-128); C, B, A (129-160); B, C, A (above 160). The channel's own voice
is freed first, so with 3 channels and 3 voices there is always one.
Below 128 is the left (upstream's pan law: left = vol × (254 - sep) /
127, right = vol × sep / 127; sep = 128 - swing × sin(angle), swing 96,
so a source within about 20° of straight ahead or behind is in the
centre band). Exactly 128 is every sound without an origin and every
sound of the player (`PISTOL`, `SHOTGN`, `PLPAIN`, pickups, the menu, the
intermission), the most frequent: they take C. In `fx.s` three
comparisons pick the offset of the band's order in one overlapping
11-byte string (`fx_order`). The side is chosen at the start only;
`S_UpdateSounds`' new separation changes nothing, its volume does.

On captured runs (demo1-3 and a tour, 1,076 starts) 51% of the starts
are in the centre band and 28% exactly 128; with A left, B right, C
centre, 65% get the voice of their band, 22% a neighbour, 5% the
opposite side and 8% none. One noise generator serves three voices: the
loudest voice's period wins.

**Volume.** `VATT[v]`, v 0-127 (upstream's volume: `snd_SfxVolume` × 8,
less with distance), is 40 log10(127 / v) in the music's half-dB units,
80 at v = 0: the music's law.

**Memory** (`docs/MEMORY_MAP.md` 5): voices `$E413-$E442` (16 B each),
`FX_ON`, `FX_HOLD`, `FX_INVAL` and the tempo fraction in `$E737-$E73B`,
rings `$E740-$E8BF` (3 × 128 B), `fx.s`'s card part (the routines and
chip 3's `want`, `shadow` and write list) from `$F505` with `pl_vbl`;
`VATT` read from `SFX.1` through a window; the interrupt's ring pointer
and temporaries in zero page `$F7-$FC`, `fx_service`'s in `$E73C-$E73F`;
the channel table and the mailboxes (3 × 4 B) in `$E8C0-$E8EF`.
`fx_service` is a shared object of every frame image.

**Cost.** An active voice writes about 1.6 registers an interrupt.
`fx_burst` follows the music's burst with no computation between, so the
two share one slot-4 slowdown tail when both write; an interrupt where
only the effects write pays a tail of its own (about 32 µs at the Doom
profile's window 32, about 505 µs at the default 512). Measured on a2vm
over D_E1M1 with demo3's effect starts, ms a second taken from the main
loop: 16.2 at window 32 (the music alone 6.0), 38.6 at window 512.

### The game side (`src/native/fx_chan.s`, generated `fxchan.inc`)

Upstream's channel logic (`s_sound65.s`): `S_StartSound`,
`S_StartSound2`, the pickup flag, the kill of the origin's earlier sound
of the same kind, `getChannel`'s free channel, same origin, then
priority, `S_StopSound`, `S_UpdateSounds`, and `S_AdjustSoundParams`
(distance 160 to 1,200 map units, map 8's floor of 15, the separation
from the angle with the swing 96). The priority table and constants come
from upstream's files through `fxchan.py` at build time. `NUM_CHANNELS`
is 3. The routines ask `s2t_pos` for every position; the menu's image
links them with `-D FXC_NOSEP`.

**One mailbox a channel** (4 B: flags, sound, volume, separation), so a
frame's decisions are bounded by the channel count and none is dropped:
`stopChannel`, whatever its cause, sets *stop* and clears *start* and
*volume*; a start sets *start* with its sound, volume and separation (it
implies stopping the channel's voice); `I_UpdateSoundParams` sets
*volume* (its separation is not used: the side is chosen at the start).
`fx_service` empties them once a frame.

**`isPlaying`** is the channel's voice active **or** a start in its
mailbox: `S_UpdateSounds` runs after the frame's tics and before
`fx_service`, so without the second half it would stop every sound the
frame's tics started. An effect starts at the frame after its tic.
