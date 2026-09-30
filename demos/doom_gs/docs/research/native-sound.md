# Native sound on the Phasor: design

Status: design and first prototype, 2026-09-30. Nothing here runs on the card yet.
It follows the owner's direction of 2026-09-30: the MUS music of the WAD goes straight to the Phasor, and the Ensoniq DOC is not used as a base.

Every claim is marked:

- **M**: measured. I ran it; the script is named.
- **R**: read, with `file:line`.
- **A**: assumed or estimated.

Paths:

- `FW/` = the F1.2.1 firmware snapshot (`appletini-one-main`).
- `UP/` = upstream's clone in `build/upstream`.
- `ND/` = `build/native-design/sound/`, where the prototype lives.

## 0. Summary

- **Music.** A host converter turns each MUS lump into a compact stream of voice commands at 140 Hz ticks. A 65C02 player runs in the mouse card's VBL interrupt (50 Hz PAL, 60 Hz NTSC). Each interrupt it catches up 2 or 3 ticks and writes only the AY registers that changed, in one burst.
- **Voices.** In native mode there are 12 voices: 7 melodic and 2 drum voices on chips 0-2, and 3 effect voices on chip 3. The 6-voice fallback has 3 melodic, 1 drum and 2 effect voices.
  - With 7 melodic voices, 8 of the 13 songs need no note stealing. D_INTER steals 52 of 3,250 notes. **M**
- **Cost.** The largest cost is not the player's code. It is the firmware's slot-4 slowdown: every `$C4xx` access forces 1 MHz for the next 512 CPU cycles (**R**).
  - On F1.2.1 as it is, music costs 11.5 to 27.5 ms a second, 1.2% to 2.8% of wall time (**M**, model). Effects add at most about 10 ms a second (**A**).
  - Exempting VIA port writes from the slowdown (a small firmware change) brings music to 0.4 to 1.3 ms a second (**M**, model).
  - Setting the slowdown window to 32 cycles in the profile config needs no firmware change. It gives 2.5 to 7.1 ms a second (**A**, arithmetic on **M** counts).
- **Effects.** Recommended: an AY script for each effect, built on the host. The pitch comes from the DP* PC-speaker lump. The loudness and noisiness come from the DS* digital sample. The ten most frequent effects get hand-tuned overrides.
  - All 55 scripts total 14,837 bytes (**M**). A playing effect writes 1.6 registers a batch on average (**M**).
  - 4-bit sample playback is ruled out on F1.2.1: the CPU would stay at 1 MHz all the time (**R**, arithmetic).
- **Game side.** Keep upstream's channel choice, priorities and distance and angle logic (`s_sound65.s`). Drop everything that deals with DOC RAM, the song banks and the DOC player.
- **Tests.**
  - The Python player model is the reference for the 65C02 player's register stream, compared batch by batch in a2vm. This needs a per-write AY log in a2vm.
  - The a2vm cost model needs the slot-4 slowdown.
  - A WAV renderer of the AY stream exists (`ND/aywav.py`).

## 1. What the WAD and upstream hold

`ND/wad.py` reads the WAD directory of `UP/data/DOOM1.WAD`: IWAD, 1,264 lumps, 4,196,020 bytes (**M**).

| Lumps | Count | Bytes | What |
| --- | ---: | ---: | --- |
| `D_*` | 13 | 245,179 | MUS songs |
| `DP*` | 55 | 3,055 | PC-speaker effects: tone indexes at 140 Hz |
| `DS*` | 55 | 535,127 | digital effects, 8-bit, 11,025 Hz (ITMBK 22,050 Hz) |
| `GENMIDI` | 1 | 11,908 | DMX's OPL2 instrument bank: 128 programs and 47 percussion notes |

The songs (**M**, `ND/mus.py`; the output is in `ND/mus_stats.md`):

| Song | Bytes | Seconds | Events | Events/s | Notes | Max polyphony (all / no drums) | Melodic range | Drum range |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| D_E1M1 | 17,283 | 96.0 | 5,826 | 60.7 | 2,332 | 10 / 5 | 28-83 | 36-57 |
| D_E1M2 | 36,776 | 155.4 | 10,847 | 69.8 | 2,036 | 12 / 8 | 28-53 | 36-75 |
| D_E1M3 | 19,276 | 272.0 | 7,507 | 27.6 | 3,749 | 6 / 4 | 32-72 | 36-59 |
| D_E1M4 | 18,216 | 170.7 | 6,270 | 36.7 | 3,105 | 8 / 6 | 28-64 | 35-59 |
| D_E1M5 | 9,830 | 164.0 | 3,270 | 19.9 | 1,464 | 6 / 6 | 26-77 | 41 |
| D_E1M6 | 9,456 | 84.0 | 3,332 | 39.7 | 1,625 | 7 / 5 | 26-89 | 36-59 |
| D_E1M7 | 8,591 | 150.9 | 2,835 | 18.8 | 1,336 | 11 / 7 | 30-94 | 40-52 |
| D_E1M8 | 59,535 | 152.0 | 18,113 | 119.2 | 877 | 10 / 6 | 36-75 | 36-81 |
| D_E1M9 | 21,266 | 137.4 | 7,766 | 56.5 | 3,805 | 11 / 9 | 32-76 | 36-57 |
| D_INTER | 29,082 | 201.4 | 9,884 | 49.1 | 4,932 | 12 / 10 | 26-68 | 36-59 |
| D_INTRO | 1,485 | 6.9 | 498 | 72.6 | 110 | 15 / 11 | 8-53 | 35-57 |
| D_VICTOR | 13,752 | 192.0 | 4,532 | 23.6 | 2,254 | 10 / 8 | 31-82 | 36-81 |
| D_INTROA | 631 | 6.9 | 214 | 31.2 | 58 | 9 / 7 | 15-44 | 35-40 |

Notes:

- **D_E1M8.** 14,934 of its 18,113 events are channel-volume changes (controller 3), and 1,079 are modulation (controller 2). **M**
- **D_E1M2.** It has 6,753 volume changes. **M**
- **D_E1M1.** It has 1,146 pitch bends, on channels 0 and 1 (the guitars). **M**
- **Drum notes used.** 23 distinct notes in all songs (**M**). The most common:

  | Note | Drum | Hits |
  | ---: | --- | ---: |
  | 36 | kick | 2,817 |
  | 40 | snare | 1,905 |
  | 42 | closed hi-hat | 1,891 |
  | 46 | open hi-hat | 718 |
  | 59 | ride | 320 |
  | 53 | ride bell | 280 |

- **Time above 7 voices.** Polyphony (drums included) exceeds 7 voices for at most 5% of the time in the level songs. It does so for 58% of D_INTRO's 6.9 s (**M**).

**Upstream's song list:**

- Songs are numbered 0-8 for E1M1-E1M9, then 9 INTER, 10 INTRO, 11 VICTOR, 12 INTROA (**R** `UP/src/iigs/s_sound65.s:1298-1300`, `UP/tools/musbank.py:70-71`).
- Doom's music numbers map to these through `musOfDoom` (**R** `s_sound65.s:1323-1328`).
- `UP/data/music/*.mus` are **not** MUS lumps. They are upstream's DOC song units, 57 to 94 KB each: a stream, pitch tables and SoundFont samples (**R** `UP/tools/music/README.md`, `MUSIC_FORMAT.md`). There are 12; INTROA has none.
- The owner said not to use them. This design reads only the WAD's `D_*`, `DP*`, `DS*` and `GENMIDI` lumps.

## 2. The Phasor as the Appletini implements it

### 2.1 Card, modes, registers

**Card.** It has two 6522 VIAs and four AY-3-8913-compatible PSGs (a YM2149 core), plus two SSI-263 speech chips.

- It resets into Mockingboard mode: 2 PSGs.
- Phasor native mode adds a second PSG behind each VIA (**R** `FW/hdl/apple/mockingboard.sv:1-11`).

**Mode switch.** The switch lives at `$C0C0-$C0CF` for slot 4 (nibble `{1, slot}`).

- An access with address bit 3 set selects Mockingboard mode.
- The low 3 bits are then ORed in. `$C0C8` then `$C0C5` gives native mode (**R** `mockingboard.sv:528-540`).
- A menu option, "Mockingboard only", ignores the switch (**R** `mockingboard.sv:39-41`).

**Decode.**

- In native mode, VIA-A answers when address bit 4 is set and VIA-B when bit 7 is set.
- In Mockingboard mode, VIA-A is `$C400-$C47F` and VIA-B is `$C480-$C4FF`.
- So `$C410` and `$C480` work in both modes (**R** `mockingboard.sv:73-80`).

**Chip select.** ORB bit 4 selects the first AY of a VIA and bit 3 the second, both active low. Bit 2 is the reset line, and bits 1-0 are BDIR/BC1 (**R** `mockingboard.sv:252-261`).

**Writing one register takes 6 VIA stores:**

1. ORA = register number
2. ORB = latch
3. ORB = idle
4. ORA = value
5. ORB = write
6. ORB = idle

This is the sequence of the Bilestoad, Bosconian and Pinball drivers (**R** `demos/bilestoad/src/sound.s:150-185`, `demos/appletini_bosconian/sound_io.s:101-134`).

- Data should go through ORA without handshake (`$Cn0F`). A plain ORA access clears the CA1 flag that the SSI-263 uses (**R** `sound_io.s:20-22`).
- In the HDL the PSG write is level-sensitive: the register follows DI on every clock while BDIR=1 and BC=0 (**R** `FW/hdl/apple/YM2149.sv:88-100`).
  - So a 5-store sequence is possible (latch, then write with the old ORA, then ORA = value). It leaves the register number in the register for about 1 µs.
  - a2vm writes on the ORB transition only (**R** `tools/a2vm/a2vm.c:262-281`), so it would not model that sequence.
  - I keep 6 stores.

### 2.2 Clock, pitch, levels

**PSG clock.** The clock enable is one pulse an Apple bus cycle, plus a second pulse in native mode (**R** `mockingboard.sv:262,541-549`: "doubles the PSG clock").

| Machine | Bus clock | PSG clock, native | PSG clock, Mockingboard mode |
| --- | ---: | ---: | ---: |
| PAL //e (owner's) | 1,015,625 Hz | 2,031,250 Hz | 1,015,625 Hz |
| NTSC //e | 1,020,484 Hz | 2,040,968 Hz | 1,020,484 Hz |

The bus clocks are **R** from `tools/a2vm/README.md` (131.28 fabric clocks a cycle, PAL). The NTSC figure is **A** (the standard figure).

**Tone.** A /8 prescaler (**R** `YM2149.sv:153`), and the output toggles every P prescaled ticks (**R** `:210-214`). So:

f = clock / (16 × P), with P from 1 to 4095.

In native mode on PAL (**M**, `ND/ayconv.py`):

- The lowest note is 31.0 Hz: MIDI 23 is out of range, and MIDI 24 has P = 3,882.
- The pitch error is at most 6.4 cents for notes 24-84 and 9.8 cents at note 96.
- NTSC runs 8.3 cents sharp with a PAL table. Ship two period tables of 73 notes: 292 bytes (**A**).
- Mockingboard mode halves every period. The error reaches 20.8 cents at note 91 (**M**).

**Noise.** The LFSR steps every 16 × NP clocks, NP from 1 to 31 (**R** `YM2149.sv:140-190`).

**Envelope.** One step every 8 × EP clocks, 32 steps (**R** `YM2149.sv:226-240`). A full one-shot decay takes 256 × EP / clock: EP = 1,190 gives 150 ms (**A**, arithmetic).

**Output levels.** The default volume table is the AY-3-8913 one (**R** `FW/ps_sources/frontend/config_menu_phasor.c:186`; table `YM2149.sv:389-425`, entries 32 + 2n).

| Level | 15 | 14 | 13 | 12 | 11 | 10 | 9 | 8 | 7 | 6 | 5 | 4 | 3 | 2 | 1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dB | 0 | -1.5 | -3.0 | -5.0 | -7.0 | -8.9 | -11.9 | -16.1 | -17.5 | -21.7 | -24.6 | -28.1 | -32.6 | -36.1 | -38.6 |

The dB values are **M**, computed from the table.

**Stereo.** Each of the 12 channels has a pan (0-15) set in the firmware menu, not by software. The defaults alternate 11 and 5 (**R** `config_menu_phasor.c:9-14`).

### 2.3 What a `$C4xx` access costs in TURBO

1. **The bus cycle.** Every `$Cxxx` access is a real bus cycle synced to PHI0: 122 to 253 fabric clocks, 0.9 to 1.9 µs (**R** `tools/a2vm/README.md:440`).
2. **The mirror drain.** While Super Hi-Res mirror bytes are pending, the next `$Cxxx` access waits for them to drain (**R** `docs/research/appletini-hardware.md:66-73`).
   - Any interrupt handler already pays this at its first I/O access, the mouse ACK. Sound adds no second wait (**A**).
   - The lazy-mirror design removes the wait for SHR bytes (**R** `docs/firmware/lazy-mirror-review.md:41`).
3. **The slot-4 slowdown. This is the cost that matters.**
   - When the virtual Phasor is enabled, the firmware always adds slot 4 to the slowdown regions, "regardless of the per-slot config" (**R** `FW/ps_sources/frontend/config_menu.c:4660-4692`).
   - The window is `vtw_slowdown_cycles`: 512 by default. The menu presets are 256 to 65,535 (**R** `config_menu.c:75-86`).
   - A hit is any access to `$C400-$C4FF` or `$C0C0-$C0CF` (**R** `FW/hdl/apple/vtw_core_top.sv:1119-1144`).
   - A hit reloads a counter that drops by one each completed CPU cycle (**R** `:1884-1898`). While it is not zero, the effective mode is 1 MHz and TURBO is off (**R** `:1153-1171`).
   - **Consequences** (**A**, arithmetic from the RTL):
     - All code between two slot-4 accesses runs at 1 MHz.
     - After the last access, the next 512 CPU cycles run at 1 MHz: 504 µs on PAL. The same 512 cycles would take about 8 µs in TURBO, so about 496 µs is lost per burst.
   - **A workaround that needs no firmware change.** The profile config key `vtw.slowdown.cycles` accepts any value from 1 to 65,535 (**R** `config_menu.c:3550-3552`), and it is applied as is (**R** `:4677-4687`).
     - A hand-edited `vtw.slowdown.cycles=32` shortens the tail to 32 cycles.
     - Cycle-counted Mockingboard detection reads the timers 8 cycles apart (**R** `vtw_core_top.sv:1119-1124`, comment). 32 cycles still covers it.
     - Only slot 4 is in the mask by default (**R** `config_menu.c:75`).

Cost of one AY register write and one burst (**A**, from the RTL and the write loop of 4.2):

| Firmware setting | One register write | Tail per burst |
| --- | ---: | ---: |
| F1.2.1, window 512 (default) | 41 CPU cycles at 1 MHz, 40.4 µs | 504 µs |
| F1.2.1, window 32 (config edit) | 40.4 µs | 31.5 µs |
| Proposed FW-S1: VIA port writes do not trigger the window | 6 bus accesses, about 8.4 µs | 0 |

**Interrupts.**

- The VIA IRQs are wired to the Apple IRQ line (**R** `mockingboard.sv:1068`).
- The Appletini mouse card raises an IRQ at the start of every vertical blank, mode bit 3 (**R** `FW/hdl/apple/mouse_card.sv:57,449`). Writing 3 to `$C0AF` acknowledges it.
  - The existing Doom port uses this as its 50/60 Hz clock (**R** `demos/doom/docs/DESIGN.md:90-95,1020-1024`).
  - Slot 2 is not slowed by default (**R** `config_menu.c:75`).

### 2.4 How a2vm and a2sim model it

- **a2sim.py.** `Phasor` models the two VIAs, the four AY register files, the mode switch and the chip-select rules. It logs each AY write as `(chip, reg, value)` (**R** `demos/doom/tools/a2sim.py:250-397`).
- **a2vm.** It follows a2sim (**R** `tools/a2vm/a2vm.c:198-352`):
  - Writes on ORB function 6, latches on function 7.
  - T1 is a free-running counter, and the SSI-263 is a phoneme timer.
  - It counts `ay_writes` and dumps the final register files in its JSON state (**R** `tools/a2vm/main.c:681-701`).
  - It has no sound, no VIA interrupts, and no slot-4 slowdown. The README says the slowdown is off "as in the measured setup" (**R** `tools/a2vm/README.md:224,595-596`).

### 2.5 The existing drivers

| Port | Time base | What it teaches |
| --- | --- | --- |
| Bilestoad (`src/sound.s`) | Reads VIA-A T1 once a frame and runs one 60 Hz tick per 1/60 s elapsed, up to 4. No IRQ. | Voice = chip × 3 + channel. Probe: read back chip 0 after writing chip 1. |
| Bosconian (`sound_io.s`, `sound.c`) | One burst a frame, after rendering | All `$C4xx` accesses in one burst "because any access to that slot slows the vTW to 1 MHz". ORA without handshake. |
| Pinball (`src/sound.s`) | One step a frame | Register shadows: "a quiet frame costs 0 accesses". Init costs 312 accesses. |

All three: **R**. Bilestoad `sound.s:1-17`; Bosconian `README.md:85-97`, `docs/DESIGN.md:66-68`; Pinball `sound.s:42-52`.

None of them plays music at a steady rate while the game runs slowly. Doom renders at 5 to 10 frames a second, so the time base must be an interrupt (section 4.1).

## 3. The host converter (MUS → AY stream)

Prototype: `ND/ayconv.py`. It uses `ND/mus.py` and `ND/genmidi.py`, written from the published MUS and GENMIDI layouts, not from upstream's `dmxmus.py`. It is original code with no upstream derivation. It can move to `tools/` when adopted.

### 3.1 Voice layouts

| Layout | Melodic | Drums (own the chip's noise and envelope) | Effects |
| --- | --- | --- | --- |
| native12 | chip 0 A, B, C; chip 1 A, B; chip 2 A, B (7) | chip 1 C, chip 2 C (2) | chip 3 A, B, C (3) |
| mb6 (fallback) | chip 0 A, B; chip 2 A (3) | chip 0 C (1) | chip 2 B, C (2) |

- Chips 0 and 1 sit behind VIA-A, and chips 2 and 3 behind VIA-B.
- In Mockingboard mode only chips 0 and 2 exist.
- The effect chip in native12 has its own noise generator, mixer and envelope, so effects never disturb music registers.

### 3.2 Pitch

- **Period table.** The player looks up the note number in a period table built for the clock of 2.2.
- **Low notes.** Notes below 24 are raised by octaves. Only D_INTRO and D_INTROA have them.
- **Pitch bend.** The MUS bend byte (128 = centre) goes into the stream as is: 2 bytes. The player computes period × 2^(-(bend - 128)/768) with a 256-entry multiplier table and one 16×8 multiply. The range is assumed to be ±2 semitones, as DMX (**A**).
- **Tempo.** MUS time is 140 Hz ticks, fixed. The player catches up ticks per interrupt: 14/5 on PAL (2 or 3 ticks), 7/3 on NTSC.
  - A note starts at most one interrupt late: 20 ms on PAL, 16.7 ms on NTSC (**A**, arithmetic).
  - 27 notes in all songs are shorter than 3 ticks (**M**). With an instant release (Distortion Guitar, for example) a note that starts and ends inside one batch would never reach the chip.
  - Rule for the player: a note-on always shows for at least one batch. A note-off that arrives in the same batch waits for the next batch.

### 3.3 Voice allocation (host side, so the player does no search)

For a note-on:

1. The same channel and note still sounding: reuse that voice.
2. A voice whose release has ended.
3. The voice whose release ends first.
4. Steal: keep the lowest sounding note (the bass), and take the oldest note of the channel that has the most voices.

Drums take a free drum voice, else the oldest drum hit.

Results (**M**, `ND/summary.py` → `ND/summary50.md`):

| Layout | Songs with no melodic steal | Worst song |
| --- | --- | --- |
| native12 | 8 of 13 | D_INTER: 52 of 3,250 notes; D_INTRO: 7 of 60 |
| mb6 | 0 of 13 | D_E1M9: 1,426 of 2,620 notes |

- native12 drum steals: 0 to 276 a song. A steal only cuts a decaying tail.
- mb6 is a fallback, not a target. Expect chords to thin out.

### 3.4 Volume

- **Attenuation.** The player works in attenuation steps of 0.5 dB, 0-80 (80 = silent).
- **Law.** Velocity, channel volume (controller 3) and expression (controller 5) each follow the General MIDI law, 40 × log10(v/127). The GENMIDI carrier level adds 0.75 dB a step.
- **Level lookup.** An 81-byte table maps attenuation to the nearest AY level in dB (**M**, table in `ayconv.LEVEL_OF_ATT`).
- **Filtering volume changes.** A channel-volume change is emitted only when a sounding note's AY level changes.
  - D_E1M8: 12,210 of its 14,934 volume events are dropped, and 2,706 attenuation commands remain (**M**).
- **Assumptions (A).**
  - The initial channel volume is 127.
  - The master music volume becomes one more attenuation term, in place of upstream's `musAtt` (**R** `s_sound65.s:1308-1310`).

### 3.5 Instruments

- **Software envelope.** Each program gets an envelope from its GENMIDI carrier, voice 0:
  - Attack rate, decay rate, sustain level (3 dB steps), release rate.
  - The EG-type flag: a non-sustained carrier keeps decaying while held.
  - OPL rates are converted to times with the YM3812 table (**A**).
- **Stored parameters.** Per used program: attack step, decay step and release step (16-bit each, in 1/256 attenuation steps a tick), sustain (byte), flags: 8 bytes.
- **Song tables.** A song uses 3 to 21 programs (**M**).
- **Examples** (**M**, from the WAD):

  | Program | Envelope |
  | --- | --- |
  | 30, Distortion Guitar (the E1M1 riff) | instant attack, no decay, instant release |
  | 34, Electric Bass (pick) | decays to -39 dB over 16 s, 614 ms release |
  | 48, String Ensemble | 177 ms attack, 2.5 s release |

- **Not modelled yet (A).**
  - GENMIDI's second voice (double-voice instruments), fine tune, and per-instrument note offset.
  - Modulation (controller 2): D_E1M8 has 1,079 events of it. A vibrato would cost 2 writes a batch a voice.
  - Pan (controller 4): the Phasor pans are set in the menu.
  - Sustain pedal (controller 8).
- **Optional, to try by ear: envelope "buzz" bass.** Set the chip's envelope to a repeating sawtooth at the note frequency: EP = clock / (256 f).
  - Pitch error is under 1% (17 cents) only below about 150 Hz (**A**, arithmetic). So it fits bass and the low E1M1 guitar riff, on the one chip without a drum voice (chip 0).
  - Cost: 2 envelope-period writes a note.

### 3.6 Percussion

Each GM drum note maps to a recipe: tone note or none, noise period or none, decay time. The table is hand-made, a first guess to tune by ear (`ayconv.DRUMS`):

| Drum | Recipe |
| --- | --- |
| Kick | tone, note 33 |
| Snare | noise 6 plus tone, note 50 |
| Hi-hats | noise 1; 50, 70 or 350 ms |
| Toms | a pitched tone with a little noise |
| Cymbals | noise 1-2, 0.5-1.2 s |

- **Hardware envelope** (shape `\___`, retriggered by writing R13) when the hit is louder than -6 dB. Quieter hits decay in software, because the hardware envelope ignores velocity.
  - Measured hits below -12 dB: 308 of 702 in D_E1M1, and all 1,232 in D_E1M2 (**M**).
- **The hybrid choice.** D_E1M1 costs 134 writes/s this way, against 117 with velocity ignored and 156 with software decay only (**M**).

### 3.7 Stream format and sizes

| Bytes | Command |
| --- | --- |
| `$0v nn` | note on, voice v, note nn; the voice keeps its last attenuation and envelope |
| `$1v nn aa` | note on with attenuation aa |
| `$2v nn aa ee` | note on with attenuation and envelope (song table index) |
| `$3v` | note off (release) |
| `$4v aa` | attenuation of a sounding note |
| `$5v bb` | pitch bend of the sounding note |
| `$6v dd aa` | drum hit: recipe dd, attenuation aa |
| `$80+n` | wait n ticks, 1-126 |
| `$FF` | end of song: loop or stop |

Sizes (**M**):

| Layout | All 13 songs | Largest song | Rate |
| --- | ---: | --- | --- |
| native12 | 141,293 bytes | D_INTER, 23,335 bytes | 44 to 173 bytes/s |
| mb6 | 126,506 bytes | | |

- The stream is about as large as the MUS lumps (245,179 bytes in all).
- A song file also holds its envelope table (8 bytes an entry) and its drum-recipe list.
- Both layouts are stored, because the allocation differs. That is about 268 KB of RamWorks (**A**).

## 4. The 65C02 player

### 4.1 What drives it

| Driver | Updates/s | Slot-4 accesses when nothing changes | Slow-window tail per second, F1.2.1 | Note timing |
| --- | ---: | --- | ---: | --- |
| **Mouse VBL IRQ (recommended)** | 50 / 60 | 0 (the ACK is slot 2) | ≤ 25.2 ms (PAL) | ≤ 20 / 16.7 ms late |
| VIA T1 IRQ at 140 Hz | 140 | ≥ 1 each tick (acknowledging the IRQ is a `$C4xx` access) | 70.6 ms | exact |
| Main-loop poll of T1 (Bilestoad) | 5-10 (frame rate) | 2 reads a frame | small | 100-200 ms: unusable for music |
| VBL IRQ, every second VBL | 25 / 30 | 0 | ≤ 12.6 ms | ≤ 40 ms late |

The tail figures are **A**, arithmetic from 2.3.

### 4.2 Structure of one interrupt

The player is called by the port's single VBL handler, after the tic counter and after `$C0AF` is acknowledged. The drain wait is paid there.

1. **Compute (TURBO speed, no I/O).**
   - Add 14 (PAL) or 7 (NTSC) to a fraction accumulator.
   - For each whole tick: run the stream commands due, then advance every active software envelope.
   - Run the effect scripts the same way.
   - Compose the wanted registers and compare them with the shadow. Build a write list grouped by chip.
2. **Burst (1 MHz).** For each chip with writes, run a generated loop with constant latch and write values:

```
        ldx n_chip0            ; writes queued for chip 0 (VIA-A, first AY)
        ldy #$0C               ; idle, chip 0 selected
loop:   lda wreg-1,x   ; 4
        sta $C41F      ; 4   ORA, no handshake
        lda #$0F       ; 2   latch
        sta $C410      ; 4   ORB
        sty $C410      ; 4   idle
        lda wval-1,x   ; 4
        sta $C41F      ; 4
        lda #$0E       ; 2   write
        sta $C410      ; 4
        sty $C410      ; 4   idle
        dex            ; 2
        bne loop       ; 3   = 41 cycles a register
```

The sketch is original. Its cycle counts come from the 65C02 datasheet (**A**).

Compute cost per interrupt (**A**, estimate to be measured in a2vm):

| Part | 65C02 cycles |
| --- | ---: |
| 2.8 ticks × (stream about 60 cycles + 10 envelopes × about 35) | about 1,300 |
| Compose and compare for 12 voices and 4 chips | about 1,200 |
| **Total** | **about 2,500** |

That is about 40 µs in fast memory, and about 2 ms a second at 50 Hz (0.2%). It is small next to the burst.

Burst cost (**M** counts from the player model at 50 Hz; times use the per-write costs of 2.3, **A**):

| Song (native12) | Bursts/s | Writes/s | p99 writes a burst | F1.2.1 (window 512) ms/s | Window 32 ms/s | FW-S1 ms/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| D_E1M1 | 36.7 | 134 | 18 | 23.9 | 6.6 | 1.12 |
| D_E1M3 | 43.0 | 97 | 11 | 25.6 | 5.3 | 0.81 |
| D_E1M5 | 21.9 | 47 | 10 | 12.9 | 2.6 | 0.39 |
| D_E1M6 | 43.0 | 143 | 15 | 27.5 | 7.1 | 1.20 |
| D_E1M8 | 19.0 | 47 | 11 | 11.5 | 2.5 | 0.40 |
| D_INTER | 38.4 | 132 | 22 | 24.7 | 6.5 | 1.11 |

- The other songs fall inside these ranges; see `ND/summary50.md`, and `ND/summary60.md` for NTSC.
- At 60 Hz the F1.2.1 cost is 12.1 to 30.9 ms a second (**M** counts).
- Updating at 25 Hz lowers F1.2.1 to 8.3 to 16.4 ms a second, at 40 ms of timing jitter (**M** counts).
- The largest single burst is 33 writes, at the first chord of D_INTRO (**M**): 1.3 ms plus the tail.

### 4.3 State and memory

Everything the interrupt reads or writes is in the language card or zero page (corrected after review: main `$0200-$BFFF` is unsafe, since a far window may leave RAMRD on with `$C073` = N and the replay leaves RAMWRT on). A handler never switches RAMRD or `$C073` (the RamWorks bank), because a mapping change clears the TURBO caches (**R** `docs/research/appletini-hardware.md:60`). The "main" rows below mean the card.

| Item | Bytes | Where |
| --- | ---: | --- |
| Player code (music, effects, burst loops) | about 2,000 (**A**) | main |
| Period tables PAL and NTSC, bend multipliers, level table | about 800 | main |
| Voice state (12 voices × about 12) and register shadows (4 × 14) | about 200 | main |
| Song ring buffer | 1,024 | main |
| Song envelope and drum tables | ≤ 300 | main |
| Effect script buffers (3 voices × 640) | 1,920 | main |
| All song streams (both layouts), all effect scripts | about 283,000 | RamWorks |

- **Ring refill.** The main loop refills the ring from the song's RamWorks copy by CPU copy through a read window when half of it is free (about 0.13 ms for 512 B, **A**); the memory API cannot write the card (**R** `README_MEMORY_API.md:161`). At ≤ 173 bytes/s, 1 KB lasts 5.9 s (**M** rate).
- **Underrun** (during disk access or level load): the player silences all music voices and holds position. This replaces upstream's `musPause`/`musResume` (**R** `s_sound65.s:2363-2365`).
- **Starting an effect.** Game code posts an effect start to a small request queue. The main loop picks the voice (4.5 below), copies the script into that voice's buffer, and sets the voice's active byte last. The interrupt reads only voices whose active byte is set.
- **IRQ contract.** The vector, zero-page use and the zero-page bank pair belong to the platform's handler design (**R** `docs/firmware/zpbank-spec.md:331-344`). The player adds no mapping switch and no RamWorks access.

### 4.4 Firmware requests (for the owner; not in `docs/firmware/`)

- **FW-S1.** Do not trigger the slot-4 slowdown on writes to VIA ORB, ORA, ORA-without-handshake, DDRA, DDRB, IFR and IER.
  - Keep it on every read, and on writes to the timer, ACR, PCR and SSI registers.
  - Detection loops time timer reads, so they keep working (**R** `vtw_core_top.sv:1119-1124`).
  - The cost looks like a few LUTs in `sd_hit` (**A**).
  - Gain: music drops from about 2.5% to about 0.1% of wall time.
- **FW-S2.** Add 16, 32 and 64 to the window presets. Until then, `vtw.slowdown.cycles=32` in a Doom profile gives most of the gain.

### 4.5 Sound effects

| Option | Data | Bus cost | Quality | Verdict |
| --- | --- | --- | --- | --- |
| a. DP* tones on one AY tone channel | 3,055 bytes in all (**M**) | about 1-2 writes a batch | the PC-speaker Doom; weak shots and explosions (no noise, no loudness shape); sampled at 50 Hz, it loses 64% of the 140 Hz steps | fallback |
| **b. DP pitch + DS loudness and noise (prototype)** | 14,837 bytes of scripts (**M**) | 1.6 writes a batch a playing effect (**M**) | noise for shots and explosions, the real sounds' loudness contour; distance attenuation is added to the script's attenuation | **recommended**, with c for the top 10 |
| c. Hand-made AY patches (as Bilestoad and Pinball) | small | as b | best control | for the 10 most frequent effects |
| d. 4-bit PCM through an AY volume register | 535,127 bytes of DS (**M**) | an interrupt per sample; 11,025 Hz × ≥ 2 slot-4 accesses | 4-bit log levels, noisy | **ruled out on F1.2.1**: the 504 µs window never ends, so the CPU would run at 1 MHz all the time. With FW-S1 it would still cost about 2.5-5% for one channel, plus a drain wait for every sample while SHR bytes are pending (**A**) |

How the option b scripts are built (`ND/sfx.py`):

- One step per 140 Hz tick.
- Tone from the DP lump. Its PIT divisor table is reconstructed as quarter tones from 175 Hz (**A**: check it against a reference table before use).
- Level from the DS RMS in that tick.
- Noise on when the DS zero-crossing rate is above 2,500/s. The noise period comes from the crossing rate.
- Run-length coded.

Effects last 0.87 s on average (**M**). Renders to listen to are `ND/sfx_{PISTOL,SHOTGN,BAREXP,DOROPN}.wav`.

**Sharing voices with music.**

- native12: chip 3 is for effects only. Music never takes it, and effects never take music voices.
- mb6: 2 effect voices share chip 2 with one melodic voice. Chip 2's noise generator belongs to the effects.
- Optional: music borrows idle effect voices. I do not recommend it: 7 melodic voices already avoid steals in 8 of 13 songs.
- **Worst case with effects:** 3 effects playing all the time means a burst every VBL, so a 25.2 ms tail per second. That plus about 240 more writes a second makes about 34 ms/s on F1.2.1: 3.4% of wall time (**A**).

What to keep from upstream's `s_sound65.s`:

| Keep (translate to 65C02) | Lines (R) | Change |
| --- | --- | --- |
| `S_Init`, `S_SetSfxVolume` | 121-156 | |
| `S_Start`: stop channels, start the map's song | 157-176 | calls the new player |
| `S_StartSound`, `S_StartSound2`, `sameOrigin`, `getChannel`, `priority`, `stopChannel` | 177-354 | `NUM_CHANNELS` = 3 (native) or 2 (mb6) |
| `S_StopSound` | 355-376 | |
| `S_UpdateSounds` (each frame; upstream calls it from `musFrame`) | 377-424, 1911-1923 | |
| `adjustParams`: distance 160 to 1,200, map 8 at least 15, separation from the angle, swing 96 | 425-670 | volume becomes attenuation; separation optionally picks a left- or right-panned voice |
| `sfxPriority` table, `snd_SfxVolume` 15, `snd_MusicVolume` 12 | 1274-1295 | |
| `musOfDoom`, `S_SetMusicVolume` | 1323-1328, 1535-1567 | volume becomes an attenuation offset |
| The rules of `musNewMap` (a new map stops the song; the same map again keeps it) and `musLevel` | 1632-1658, 1719-1727 | |
| `S_ChangeMusic`, `S_StartMusic` (once or looping) | 1728-1776 | the song start becomes "select stream, reset ring" |
| `musTitle`/`musInter`/`musFinale` hooks, `musGo` (the title starts its song when its colours come on) | 1880-1910, 2048-2067 | |
| `musShutdown`, `musPause`/`musResume` (their effect: silence, song kept) | 2346-2380 | |

Drop:

- The DOC channel code: `isPlaying`, `docStop`, `docVolume`, `startSound`, `cacheSound`, `placeSound`, `loadPlan`, `evictSound`, `PAGEOWNER`, the pool and `I_InitSound` decoding (671-1272 and 1396-1490).
- All DOC music loading and control: `I_InitSound2`, `musRevol`, `setVolume`, `musWillPlay`, `planSwap` (1491-1534, 1568-1631, 1659-1718); `musPlay`, `musSource` (1777-1879); `musStep`, `musPart`, `musLoad` (1924-2047); `musStart`, `musDesc`, `musUpload`, `musEvict`, `musAlarm`, `musStop`, `musSet` (2068-2345).
- The DOC player in `irq65.s`.

## 5. Tests

1. **Host unit tests** (future `tests/test_sound_*.py`, standard library only; they skip without `build/`):
   - All 13 songs parse to their end marker, with the event counts of section 1.
   - The stream decodes to its end.
   - Voice numbers are within the layout.
   - Every note-on is either on a free voice or counted as a steal.
   - The steal and writes-per-batch figures stay at or below those of `ND/summary50.md`.
   - Period, level and bend tables match their formulas.
2. **Register-stream check in a2vm.**
   - Assemble the 65C02 player, load a converted song, and run N VBL interrupts. The a2vm cost-timed mode delivers the mouse card's VBL (**R** `tools/a2vm/README.md:223,446-447`).
   - After every interrupt, compare the ordered AY writes with the Python player model (`ayconv.Player`, the reference). The writes must match exactly; the model is deterministic.
   - Needed in a2vm (for the a2vm owners):
     - an `--ay-log FILE` option writing (bus clock, chip, register, value) per write. a2sim's `Phasor.log` already has the tuple.
     - a slot-4 slowdown in the cost model (window length, FW-S1 on or off). Acceptance: music alone on F1.2.1 within 10% of the table in 4.2.
   - Mockingboard-mode run: never switch to native. The probe must find 2 chips and select mb6.
3. **WAV renderer** (`ND/aywav.py`, done): renders any register log with the YM2149.sv rules (tone, 17-bit noise, 32-step envelope, AY levels, mixer). It will read a2vm's `--ay-log` output unchanged.
   - Renders: `e1m1_native12_50hz.wav`, `e1m1_native12_140hz.wav` (to hear the 50 Hz batching), `e1m1_mb6_50hz.wav`, `e1m8_native12_50hz.wav`, 45 s each. They do not clip: peak 26,051 of 32,767 (**M**).
4. **On the card** (milestone 0 style):
   - A loop of N AY writes timed by VBL counts, with window 512 and window 32. This checks the 40.4 µs a write and the 504 µs tail.
   - Then one level with music and effects, reading the frame rate with sound on and off.

## 6. Prototype files

All are in `build/native-design/sound/`. They are ignored by git and use no upstream code.

| File | What |
| --- | --- |
| `wad.py` | WAD directory, sound-lump listing |
| `mus.py` | MUS parser and song statistics (`mus_stats.md`) |
| `genmidi.py` | GENMIDI reader: carrier envelope, fixed notes |
| `ayconv.py` | converter, stream encoder, player model, register log (`--log`), `--soft-drums` |
| `summary.py` | all songs, both layouts, cost table (`summary50.md`, `summary60.md`) |
| `sfx.py` | effect scripts from DP and DS (`sfx_table.md`, `--log NAME`) |
| `aywav.py` | register log → WAV |

What the prototype does not validate:

- the sound itself (nobody has listened yet);
- the 65C02 cycle estimates;
- the OPL-to-time conversion;
- the reconstructed PC-speaker table.

## 7. Open questions for the owner

1. Accept about 1.2-2.8% of wall time for music on F1.2.1, or pursue FW-S1, or ship a Doom profile with `vtw.slowdown.cycles=32`?
2. VBL at 50/60 Hz (≤ 20 ms late), or every second VBL to halve the cost?
3. Is the 6-voice fallback worth keeping? It only matters with "Mockingboard only" set, or a real Mockingboard.
4. Effects: automatic DP+DS scripts with hand overrides for the top 10 effects, or all hand-made?
5. Should the effect voice follow Doom's stereo separation by picking a left- or right-panned voice, given the menu's default pans of 11 and 5?
6. Try the envelope buzz bass on the E1M1 riff?
7. The start rate of effects is not measured. The ref816 traces could count `S_StartSound` calls in the demos, to size the effect queue and the script-copy cost.
