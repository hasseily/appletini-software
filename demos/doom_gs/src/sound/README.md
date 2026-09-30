# src/sound: the 65C02 music player for the Phasor (milestone S2)

The music player of the native rewrite, in 65C02 assembly for ca65 (cc65
2.18): milestone S2 of [`docs/NATIVE.md`](../../docs/NATIVE.md) section
13, from the design of
[`docs/research/native-sound.md`](../../docs/research/native-sound.md)
sections 3 and 4. It is a translation of
[`tools/sound/player.py`](../../tools/sound/player.py), the specification
milestone S1 wrote: the same state, the same steps in the same order, the
same integer arithmetic, so it writes the same AY registers in the same
order after every interrupt. All the code is original; no upstream source
was used.

| File | What it is |
| --- | --- |
| `player.s` | The player: the interrupt's work (`snd_tick`), the stream interpreter, the envelopes, the levels, the register shadows and the burst to the chips, song start and stop, the ring and its refill |
| `irq.s` | The VBL interrupt entry and the card's vectors, as far as the music needs the platform's handler |
| `probe.s` | `snd_probe`: music (the card switched to native mode: 4 chips) or no music (a Mockingboard, or the Phasor locked to Mockingboard mode: 2 chips); boot code in main memory, not in the card |
| `driver.s` | The test driver: the main program `tools/sound/run65.py` runs on a2vm; not part of the game |
| `sound.inc` | Addresses, the model's constants, the song file's |
| `sound.cfg` | ld65's map for the tests: the player in the main language card, the driver and the probe at `$0800` |
| `Makefile` | Builds the player into `build/sound65` |
| `music.s` | MUSIC.SYSTEM of the music disk (milestone S3): boot (mouse card, RamWorks, `snd_probe`, the 13 songs into RamWorks, ProDOS's card saved), the text screen, the keys, the song clock, the quit (the chips reset, ProDOS's card back, the Phasor back in Mockingboard mode, ProDOS's QUIT); not part of the game |
| `aytime.s` | The AY timing test of S3 (key T): a register write and the slow-window tail measured by VBL counts, with the expected values beside them |
| `music.cfg` | ld65's map for MUSIC.SYSTEM: the program at `$2000-$3FFF`, the player's card image at `$4000-$56FF` for `$E900-$FFFF`, where `docs/MEMORY_MAP.md` 4.2 puts it in the game |

The last three files are milestone S3's; `tools/sound/musicdisk.py`
builds them into the disk `build/sound/MUSIC.hdv` and checks it on a2vm
(`tools/sound/README.md`, "The music disk").

There is one voice layout, native12: 7 melodic and 2 drum voices on the 4
AY chips of the card in native mode, 3 voices left for the effects
(`tools/sound/README.md`, "Voice layout"). The 6-voice fallback for a card
in Mockingboard mode was removed on 2026-09-30 (NATIVE.md 15.1, row 11);
such a card gets no music (below, "No music").

`build/sound65/tables.inc` is generated from
[`tools/sound/tables.py`](../../tools/sound/tables.py) by
[`tools/sound/tables65.py`](../../tools/sound/tables65.py): the voices of
the layout, the registers the music owns, the period tables of native
mode for PAL and NTSC, the bend magnitudes and the level table. The player
and its oracle share one source for them; the tests read them back from
the assembled player.

## Commands

From `demos/doom_gs`, with cc65 2.18 and the song files of S1
(`python3 tools/sound/report.py`, which needs the WAD):

```
make -C src/sound                              # the player
make -C tools/a2vm                             # a2vm, with --ay-log
nice -n 10 python3 tools/sound/run65.py        # 13 songs, 60 s, PAL
nice -n 10 python3 tools/sound/run65.py --ntsc # 20 s on NTSC
python3 tools/sound/run65.py --sizes --update-readme
nice -n 10 python3 tools/sound/run65.py --cost --update-readme   # about 10 min
python3 -m unittest discover -s tests -p 'test_sound_player65.py'
```

## How it runs

| Entry | Where it runs | What it does |
| --- | --- | --- |
| `snd_probe` (`probe.s`) | once, at boot, before `snd_init` | Asks for native mode (`$C0C8`, `$C0C5`), resets VIA-A's chips, writes R0 of chip 0 ($55) then of chip 1 ($AA), reads chip 0's R0 back: $55 is 4 chips, carry clear and A = `SND_MUSIC` (0); $AA is 2 chips, carry set and A = `SND_NO_MUSIC` (1), the second write having reached chip 0 on a card that ignores the mode switch and the chip selects (The Bilestoad's method). Leaves VIA-A's chips reset |
| `snd_init` | once, main loop, after `snd_probe`, whatever it answered | The card's native mode (`$C0C8`, `$C0C5`), VIA interrupts off, ports as outputs, both AYs of each VIA reset (ORB 0, then idle), the player stopped (so `snd_tick` returns at once until a `snd_start`) |
| `snd_start` | main loop | Plays the song file at `snd_song_bank:snd_song_addr` (a RamWorks bank, `$0200-$BFFF`) with `snd_song_flags` (bit 0 loop, bit 7 NTSC) and `snd_song_matt` (music attenuation, 0.5 dB steps). Reads the header through a read window, refuses a file of another version or layout, too many envelopes (20) or drums (23), or a loop offset outside the stream (carry set, `snd_error` 1-4); copies the envelope and drum tables into the card; selects the PAL or NTSC period table and tempo; resets the voices (`Player.__init__`); fills the ring; writes the first burst (`Player.reset`: R0-R12 of every chip of the layout). The interrupt ignores the player until it is done |
| `snd_tick` | the VBL interrupt, after the acknowledge | `Player.interrupt`: the pending releases, the ticks due (the 16-bit tempo fraction), each tick's commands and envelopes, then the levels (`compose`), the registers that changed (`flush`) and one burst |
| `snd_refill` | main loop, as often as it likes | When half the ring or more is free, copies the stream into it, 512 bytes at a time |
| `snd_stop` | main loop | The next interrupt silences every music voice, writes that burst, and the player stops |
| `snd_vbl` (`irq.s`) | the IRQ vector at `$FFFE` | Reads the mouse card's status (`$C0A0`), acknowledges it (`$C0AF`), and on a VBL counts it (`vbl_count`) and calls `snd_tick`; a BRK stops at `snd_crash` |

**Player.py step by step.** `snd_tick` is `Player.interrupt`,
`commands` is `Player.commands`, `note_on`, `set_tone`, `drum_start`,
`envelopes`, `compose` and `flush` have the model's names, and
`bend_period` is `tables.bent_period`: a 12 x 8 bit shift-and-add multiply
into 3 bytes, 1024 added, a shift by 11. `burst` writes each chip's list
with the loop of native-sound.md 4.2 (41 cycles a register: ORA without
handshake, latch, idle, value, write, idle). `flush` walks the owned
registers of the chips in descending order into per-chip lists that the
burst walks backwards, so the chips, and each chip's registers, go out in
ascending order, the order player.py defines. R13 goes out again after a
drum's retrigger even when equal, as in the model.

**The IRQ contract** (native-sound.md 4.3, NATIVE.md 10). The interrupt
reads and writes only the zero page (31 bytes at `$80` in this map), the
stack, the main language card and I/O: the player's code, tables, state,
ring and write lists are all in the card, its vector at `$FFFE` in the
card. It makes no mapping switch and no RamWorks access, so RAMRD,
RAMWRT and `$C073` may be anything when it comes, including in the middle
of a refill's read window. It assumes ALTZP off: with ALTZP on the aux
card would need its own vectors and a bridge (NATIVE.md 4.3 and 10), a
milestone 11 matter. The decimal flag is cleared by the interrupt entry.
Every run of the tests checks the contract as the machine runs: a2vm's
`--irq-bounds` halts the run at the first access of an interrupt handler
outside `$0000-$01FF`, `$C0A0-$C0AF` (the mouse card), `$C400-$C4FF` (the
Phasor) and `$D000-$FFFF`, wherever the interrupt lands, so a table moved
out of the card or a mapping switch in the handler fails the tests
(`PlantedBugs`).

**The ring** (native-sound.md 4.3). 1,024 bytes in the card, page
aligned, and a 3-byte mirror of its first bytes after its end, so that a
command that wraps reads its operands with one `(rp),y`. The main loop
fills it a page at a time: a page is published by incrementing one byte
(`wpos_hi`) once all its bytes are in, so the interrupt never sees half
of a page, and the main loop reads the interrupt's 16-bit position with
interrupts masked for three instructions. It copies through a read window
(`$C073` = the song's bank, RAMRD on), with the copy loop in the card,
since RAMRD moves the main-memory code it would otherwise run. At the end
of a looping song the refill goes on with the loop's bytes, so the
interrupt reads straight on after the `$FF`; player.py jumps back in
memory, and the two agree (the tests). A song that does not loop stops
the refills at its end.

**A stream that breaks a rule.** An envelope index at or past the song's
envelope count (header byte 2) or a drum recipe at or past its drum
count (byte 3), a voice outside the layout, a wait of 0, or a looping
stream without a wait: the player stops reading at that command, with
`snd_error` = 5 (`ERR_STREAM`) and its position on the command; the
voices keep what they had. player.py raises in the same interrupt (an
IndexError for the indexes, when it uses them). The converter never
writes such a stream; `InvalidStreams` tests the indexes.

**Underrun** (native-sound.md 4.3: "silences all music voices and holds
position"). When the bytes of the next command are not all in the ring,
the player silences every music voice (idle, silent, flags and latched
hits cleared, as a `$7v` cut does) and returns; the next tick tries the
same command again. player.py has no ring, so `tools/sound/run65.py`'s
`RingPlayer` is player.Player reading through the ring with these rules,
and the ring's tests compare with it. With the ring refilled after each
interrupt, RingPlayer equals player.Player exactly on the tests' random
streams and on the looping song that goes round the ring.

**No music.** The music needs the card's native mode (native12, the only
layout). `snd_probe`'s answer is the flag the game acts on, defined in
`sound.inc`:

| A (carry) | Name | The card | What the game does |
| --- | --- | --- | --- |
| `$00` (clear) | `SND_MUSIC` | Switched to native mode: 4 AY chips (the Appletini's Phasor) | `snd_init`, then `snd_start`, `snd_refill`, `snd_stop` as it likes |
| `$01` (set) | `SND_NO_MUSIC` | Cannot switch: 2 AY chips (a Mockingboard, or the Phasor with "Mockingboard only" set, its `audio_control` bit 26) | `snd_init` once, then nothing else of the player: it says it has no music (NATIVE.md 15.1, row 11) and never calls `snd_start`. The VBL interrupt still runs: `snd_vbl` counts the VBLs and `snd_tick` returns at once |

The test driver does the same: `drv_found` keeps the answer (`$FF` when
it ran no probe), its "no music" report, and with `SND_NO_MUSIC` it
skips its START and STOP actions and never calls `snd_refill`. `Probe`
tests it on a2vm with `--phasor-mb-only`, the player's RAM starting as
garbage and the run ending at any call to `snd_start`, `snd_stop` or
`snd_refill`. A song file of another layout
(header byte 1 not 0) is refused by `snd_start` with `ERR_LAYOUT`.

**Machines.** PAL or NTSC is chosen at each `snd_start`: two period
tables of native mode, and the tempo fraction (2 + 52,135/65,536 ticks an
interrupt on PAL, 2 + 22,043/65,536 on NTSC).

## Sizes

Code and data of the player, from the linker's map
(`python3 tools/sound/run65.py --sizes --update-readme`):

<!-- sizes:begin -->
| Part | Bytes | Budget | Source of the budget |
| --- | ---: | ---: | --- |
| code (music, bursts, refill, the IRQ entry) (`SNDCODE`) | 2,104 | 2,000 | native-sound.md 4.3: about 2,000 with the effects; NATIVE.md 4.3: player and effects 3-5 KB |
| tables: periods PAL and NTSC, bend, levels, layout (`SNDRODATA`) | 973 | 800 | native-sound.md 4.3: about 800 |
| state: voices, shadows, song tables (`SNDBSS`) | 567 | 500 | native-sound.md 4.3: voices and shadows about 200, song tables <= 300 |
| write lists (in one page) (`SNDLIST`) | 128 | - | not in the design |
| the song ring (and its 3-byte mirror) (`SNDRING`) | 1,027 | 1,024 | native-sound.md 4.3: 1,024 |
| zero page (player and IRQ entry) (`SNDZP`) | 31 | - | the IRQ contract: the card or the zero page |
| alignment padding in the card (between `SNDRING`, `SNDLIST`, `SNDBSS`) | 0 | - | the ring is page aligned |
| **Data in the card** | 2,695 | 2,324 | native-sound.md 4.3 without the effect buffers (800 + 200 + 1,024 + 300); NATIVE.md 4.1 gives the player 4.2 KB with them |
<!-- sizes:end -->

- **Code: 2,104 bytes (native12), over the design's "about 2,000"**,
  which was to include the effects player too (native-sound.md 4.3;
  NATIVE.md 4.3 gives the player and the effects 3-5 KB of code, 1-2 KB
  hot). By routine (native12): the start with its header checks, table
  copies and first burst 441 bytes, the envelopes 201, the refill 218,
  the drum start 165, the burst loops 153, the commands and their
  handlers 338 (with the index checks), the bend's multiply 125, the
  interrupt's own steps 110, the IRQ entry 40. What the interrupt runs is about 1,365 bytes; the
  start, `snd_init` and the refill (about 740) run in the main loop and
  could live in the card's second `$D000` bank (NATIVE.md 4.1), a choice
  for milestone 5's map.
- **Tables: 973 bytes against about 800.** The period tables cover all
  128 notes the stream format allows, as `tables.period_table` does
  (2 x 256 bytes), where the design counted 73 notes (292 bytes); notes
  below 24 repeat an octave higher, so folding them would save 96 bytes.
- **Write lists: 128 bytes the design did not count**, the price of the
  41-cycle burst loop: the burst's `lda wreg+c*16-1,x` must not cross a
  page, so `wreg-1` to `wval+63` stay in one page. They follow the ring
  (which ends 3 bytes into a page) with no padding; `player.s` has the
  linker check it. The first version aligned them to a page, which left
  253 bytes unused after the ring that the table did not show; the
  table now counts any padding between the card's data segments.
- **State: 567 bytes against about 500**: the song tables take their
  maximum (20 envelopes, 23 drum recipes: 298 bytes; the WAD's songs use
  at most 9 and 17), and the voice arrays are 11 x 9 bytes.
- **The card as a whole**: data 2,695 bytes (`$D000-$D6B9`, no padding)
  against 2,324 for the music part of the design. With the 1,920 bytes
  of effect buffers S4 will add, 4,615 bytes against NATIVE.md 4.1's
  4.2 KB: **about 0.4 KB over**, in a card already oversubscribed (about
  19.7 KB wanted of 16 KB, NATIVE.md 4.1). Milestone 5's byte map
  decides; the savings above (the period fold, a smaller ring, cold code
  in bank 1) cover it. `snd_probe` (117 bytes) is boot code and not in
  the card.

## Verification

`tests/test_sound_player65.py` (it builds the player and a2vm from
scratch; the song tests skip without the WAD, the player's without cc65):

| Test | What it checks |
| --- | --- |
| `Build` | The player builds with no warning from ca65 or ld65 (`run65.build()` fails on one, so every test that builds does too); a planted warning (the `.import vbl_count` of the first version) fails the build |
| `Tables` | Every table in the assembled player equals `tables.py` (both period tables, bend, levels, owned registers in flush order); the IRQ contract's placement: code, data, ring, lists in the card, the vector at `$FFFE`, the zero page under `$100`; the ring page aligned, the write lists in one page |
| `Songs` | The 13 songs of the WAD, converted by `mus2ay.py` at test time, looping: 60 s on a PAL //e (3,005 interrupts each) and 20 s on NTSC (1,198); every interrupt's writes equal `player.Player`'s, and the start's first burst equals `Player.reset()`. And D_INTROA not looping, past its end |
| Every run | The chips are reset only by `snd_init` (the AY log's `reset` lines, before everything else); at the end the chips' 16 registers (a2vm's state) equal the model's shadow, the registers it does not hold 0, the card in native mode; no interrupt reads or writes outside its bounds (above) |
| `RandomStreams` | 16 random song files (seeded) that use every command on every voice with the edges of the arithmetic: 16-bit envelope sums that carry, attacks of 65,535, attenuations past 80 (to 255), bends 0, 127, 129 and 255, loud and quiet drums, notes 0 and 127, a loop offset inside the stream; PAL and NTSC; and the music attenuation (0, 6, 30, 80) |
| `Ring` | A song of 2-3 KB looping through the ring for 30 s (the stream goes round more than 3 times, the ring's position counted by the 65C02 equals the model's); an underrun: no refills for 6 s, every music voice quiet, only level registers written (to 0), then the song goes on; start, stop, a stop's burst then silence, a song started while another plays, NTSC and a music attenuation per start, a song that ends; refused starts (version 2, layout 1, 21 envelopes; `player.py` refuses the first two too); `RingPlayer` equals `player.Player` on 8 random songs when refilled after each interrupt |
| `PlantedBugs` | Eight bugs planted in copies of `player.s`, each caught by the comparison: the bend rounding down, R13 not rewritten after a retrigger, the release adding the decay step, chip 2 written before chip 0, the ring mirror never written, an off after an on in the same interrupt releasing at once, the tempo dropping the fraction's carry, the burst pulsing its VIA's reset after each write (every write as player.py's, the chips cleared). The tables the interrupt reads moved to main memory: the run halts on the interrupt bounds. The end-of-run register check fails on a changed register, a wrong card mode, and a wrong write in an interrupt the run cut. An unchanged copy passes |
| `Probe` | On the Phasor the probe answers `SND_MUSIC`, and 20 s of a random song and of D_E1M1 after it equal player.py, the card in native mode at the end. On a card locked to Mockingboard mode (a2vm `--phasor-mb-only`) it answers `SND_NO_MUSIC` (its $AA reached chip 0): `drv_found` is `SND_NO_MUSIC`, and in 5 s with a start, a stop and a second start the driver never calls `snd_start`, `snd_stop` or `snd_refill` (the run stops at any of them), no chip is written after `snd_init`'s resets, `snd_playing` is 0 after `snd_init` though the player's RAM at `$D000` starts as garbage (no byte 0, as a real machine's at power-on; a2vm starts it at zero), the VBL interrupt runs and counts every VBL (`vbl_count` equals the interrupts), and the card is still in Mockingboard mode at the end, all its registers 0; the same actions on the Phasor play |
| `InvalidStreams` | Envelope indexes 2, 20, 255 of a song with 2 envelopes, drum indexes 2, 23, 255 of one with 2 recipes: the writes equal player.py's until the interrupt where it fails, then the player stops with `ERR_STREAM` on that command |
| `AyLog`, `Slowdown` | a2vm's additions (`tools/a2vm/README.md`, "The AY log", "Interrupt bounds" and "The slot-4 slowdown"); `--irq-bounds` passes a handler that stays inside and halts one that reads main memory, writes it, or writes `$C003` |

What the planted bugs showed: each makes the comparison fail at a named
interrupt and write, for instance "interrupt 8: write 8 is (1, 0, 135),
expected (1, 0, 134)" for the bend's rounding. A first version of the
list had a bug that stopped a quiet drum's software decay one step early;
it was not caught, and it cannot be: a quiet drum has a note attenuation
above 12, so its level is 0 before that step either way, and only a note
that starts on the same voice in that very tick would show it. It was
replaced by the release bug.

## Cost

The player's time a second in the cost model (`tools/a2vm`, profile f121
on the model's clock, PAL, the virtual Phasor enabled): each song played
once to its end plus one second, as `tools/sound/report.py` and the
design's `summary50.md` count it. Its time is what it takes from the main
loop: the driver counts its loop's iterations, and the cost is 1 - count /
(the count of a run with no song over the same time), so it includes the
interrupts' work, the bursts at 1 MHz, the slow window's tail after each
burst, and the refills' copies through the read window. "In the IRQ" is
the part between the interrupts' entries and RTIs, from the AY log's
clocks. "Formula" is native-sound.md 2.3's arithmetic on this run's
counts (40.4 us a write, a 504 us or 31.5 us tail a burst; 8.4 us a
write with FW-S1), and "4.2" the design's table, where it has the song.

    python3 tools/sound/run65.py --cost --update-readme

<!-- cost:begin -->
| Song | Seconds | Bursts/s | Writes/s | F1.2.1, window 512: ms/s (in the IRQ) | formula | 4.2 | window 32: ms/s (in the IRQ) | formula | 4.2 | FW-S1: ms/s (in the IRQ) | formula | 4.2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| D_E1M1 | 97.0 | 36.5 | 121.5 | 25.78 (8.88) | 23.30 | 23.90 | 8.79 (8.65) | 6.06 | 6.60 | 4.03 (3.91) | 1.02 | 1.12 |
| D_E1M2 | 156.4 | 36.6 | 86.5 | 24.06 (7.18) | 21.93 | - | 7.03 (6.94) | 4.65 | - | 3.43 (3.35) | 0.73 | - |
| D_E1M3 | 273.0 | 40.7 | 92.1 | 26.49 (7.74) | 24.26 | 25.60 | 7.52 (7.45) | 5.00 | 5.30 | 3.62 (3.55) | 0.77 | 0.81 |
| D_E1M4 | 171.7 | 38.4 | 110.9 | 25.89 (8.20) | 23.82 | - | 8.03 (7.94) | 5.69 | - | 3.59 (3.51) | 0.93 | - |
| D_E1M5 | 165.0 | 21.6 | 46.5 | 15.01 (5.06) | 12.77 | 12.90 | 4.95 (4.87) | 2.56 | 2.60 | 2.97 (2.91) | 0.39 | 0.39 |
| D_E1M6 | 85.0 | 42.5 | 138.1 | 29.58 (9.89) | 27.02 | 27.50 | 9.76 (9.66) | 6.92 | 7.10 | 4.34 (4.25) | 1.16 | 1.20 |
| D_E1M7 | 151.9 | 27.3 | 48.8 | 17.91 (5.39) | 15.73 | - | 5.20 (5.12) | 2.83 | - | 3.05 (2.99) | 0.41 | - |
| D_E1M8 | 153.0 | 18.5 | 41.1 | 12.98 (4.43) | 10.96 | 11.50 | 4.39 (4.31) | 2.24 | 2.50 | 2.67 (2.60) | 0.35 | 0.40 |
| D_E1M9 | 138.4 | 33.9 | 120.3 | 24.35 (8.71) | 21.97 | - | 8.54 (8.43) | 5.93 | - | 3.94 (3.84) | 1.01 | - |
| D_INTER | 202.4 | 38.0 | 117.8 | 26.01 (8.52) | 23.89 | 24.70 | 8.33 (8.23) | 5.95 | 6.50 | 3.72 (3.63) | 0.99 | 1.11 |
| D_INTRO | 7.8 | 26.0 | 56.6 | 18.12 (5.72) | 15.39 | - | 5.90 (5.56) | 3.10 | - | 3.34 (3.16) | 0.48 | - |
| D_INTROA | 7.8 | 24.8 | 55.8 | 17.34 (5.45) | 14.78 | - | 5.66 (5.33) | 3.04 | - | 3.16 (2.99) | 0.47 | - |
| D_VICTOR | 193.0 | 33.1 | 74.6 | 22.09 (6.84) | 19.71 | - | 6.66 (6.58) | 4.06 | - | 3.53 (3.47) | 0.63 | - |
<!-- cost:end -->

The run of 2026-09-30, after the 6-voice layout was removed, took 14
minutes at 4 jobs under `nice -n 10` on an Apple M3 Pro (39 runs of a2vm
with the counting loop, and 3 without a song). The player in the card is
byte for byte the build measured before; the figures moved by at most
0.03 ms a second, from the test driver's own loop (its "no music" check
before each refill).

**Against native-sound.md 4.2.** With the default window (512) the
player costs 13.0 to 29.6 ms a second (1.3% to 3.0% of the machine).
The design's six songs: D_E1M1 +7.9%,
D_E1M3 +3.5%, D_E1M6 +7.6%, D_INTER +5.3% against its table, within the
10% its section 5.2 asks for; **D_E1M5 +16% and D_E1M8 +13% are not**.
The formula column shows why: on this player's own counts, the design's
arithmetic (bursts x 504 us + writes x 40.4 us) gives 2.0 to 2.7 ms a
second less than measured in every song. That is the player's computing, which
the design estimated (about 2,500 cycles an interrupt, 2 ms a second,
native-sound.md 4.2) but left out of its table; it weighs most in the
quiet songs. Measured on the AY log's cycle counts (60 s of D_E1M1,
D_E1M8 and D_INTER): 3,000
to 3,700 cycles an interrupt on average without the writes, 4,700 to
11,500 at the 99th percentile, 14,200 at most (D_E1M1, whose guitars bend
a lot: each bend is a 125-byte multiply). The burst and tail parts agree
with the design: the formula is 1% to 5% below its table, because S1's
player writes a little less than the design's prototype.

With **window 32** the cost is 4.4 to 9.8 ms a second, against
2.5 to 7.1 in the design: the tail has gone, so the computing (about 2.1
to 2.9 ms a second at 50 Hz) is now a third to a half of it. With
**FW-S1**, 2.7 to 4.3 ms a second against 0.39 to 1.20: nearly all of it
is computing and the interrupt itself. The design's FW-S1 column counts
only the writes. So after FW-S1 the next saving is in the player's own
code (the envelope pass over every voice each tick, the 42-register flush
compare), not in the bus.

"In the IRQ" is 29% to 35% of the F1.2.1 cost and nearly all of the
FW-S1 cost: with the default window most of the time is the 504 us tail
that the main loop runs at 1 MHz after each burst.

## Departures from the design

- **The ring's refill granularity.** The design copies 512 bytes when
  half the ring is free; this player copies two pages then, but publishes
  each page on its own, and reads a command only when all its bytes are
  in. A 3-byte mirror after the ring lets a wrapping command read its
  operands in place.
- **Underrun and stop** are specified here (above), since player.py has
  neither; `RingPlayer` holds the rules.
- **One layout, no fallback.** The design kept a 6-voice layout for a
  card in Mockingboard mode (native-sound.md 3.1); the owner dropped it
  (NATIVE.md 15.1, row 11), so there is one build and `snd_probe` answers
  music or no music. PAL or NTSC is chosen at start. The design shipped
  "two period tables of 73 notes"; these are 128 notes, as the model's.
- **snd_init resets the chips** with an ORB 0 pulse (as the Bosconian
  driver does) before the first burst writes R0-R12; the pulse is not a
  register write, so the AY log shows it as `reset` lines, and player.py's
  first burst is unchanged.
- **The data byte goes through ORA without handshake** (`$C41F`,
  `$C48F`), as native-sound.md 2.1 says. a2vm, following `a2sim.py`,
  ignored that register; `--via-ora-nh` makes it follow the card's 6522
  (`via6522.v:149`), and the harness uses it.

## Open problems

- The card's language-card map (milestone 5) will place the player; this
  build's addresses are the tests'.
- The boot code that runs `snd_probe`, and the game's message when it
  answers `SND_NO_MUSIC`, are milestone 11's; the driver here only keeps
  the answer.
- ALTZP on (the tic window of the design + pair variant) needs the aux
  card's copy of the vector and a bridge (NATIVE.md 10); not written.
- Effects (S4): chip 3 is the effect voices'; the flush here owns the
  music's registers only.
- Nothing has run on the card (S3).
