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
| `probe.s` | `snd_probe`: 4 chips (a Phasor) or 2 (a Mockingboard, or the Phasor locked to Mockingboard mode), so that the boot code can pick the layout; boot code in main memory, not in the card |
| `driver.s` | The test driver: the main program `tools/sound/run65.py` runs on a2vm; not part of the game |
| `sound.inc` | Addresses, the model's constants, the song file's |
| `sound.cfg` | ld65's map for the tests: the player in the main language card, the driver and the probe at `$0800` |
| `Makefile` | Builds both layouts into `build/sound65/native12` and `build/sound65/mb6` |

`build/sound65/LAYOUT/tables.inc` is generated from
[`tools/sound/tables.py`](../../tools/sound/tables.py) by
[`tools/sound/tables65.py`](../../tools/sound/tables65.py): the voices of
the layout, the registers the music owns, the period tables of the card
mode for PAL and NTSC, the bend magnitudes and the level table. The player
and its oracle share one source for them; the tests read them back from
the assembled player.

## Commands

From `demos/doom_gs`, with cc65 2.18 and the song files of S1
(`python3 tools/sound/report.py`, which needs the WAD):

```
make -C src/sound                              # both layouts
make -C tools/a2vm                             # a2vm, with --ay-log
python3 tools/sound/run65.py                   # 13 songs x 2 layouts, 60 s, PAL
python3 tools/sound/run65.py --ntsc            # 20 s on NTSC
python3 tools/sound/run65.py --sizes --update-readme
python3 tools/sound/run65.py --cost --update-readme   # about 20 min
python3 -m unittest discover -s tests -p 'test_sound_player65.py'
```

## How it runs

| Entry | Where it runs | What it does |
| --- | --- | --- |
| `snd_probe` (`probe.s`) | once, at boot, before `snd_init` | Asks for native mode (`$C0C8`, `$C0C5`), resets VIA-A's chips, writes R0 of chip 0 ($55) then of chip 1 ($AA), reads chip 0's R0 back: $55 is 4 chips, A = 0 (native12); $AA is 2 chips, A = 1 (mb6), the second write having reached chip 0 on a card that ignores the mode switch and the chip selects (The Bilestoad's method). Leaves VIA-A's chips reset |
| `snd_init` | once, main loop | VIA interrupts off, ports as outputs, both AYs of each VIA reset (ORB 0, then idle), and for native12 the card's native mode (`$C0C8`, `$C0C5`). mb6 never switches the card (native-sound.md 5.2) |
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

**Layouts and machines.** The layout (native12 or mb6) is chosen when the
player is assembled, as the card mode is found once at boot by
`snd_probe`, which the boot code runs to pick the build to load; a song
file of the other layout is refused. PAL or NTSC is chosen at each
`snd_start`: two period tables of the layout's card mode, and the tempo
fraction (2 + 52,135/65,536 ticks an interrupt on PAL, 2 + 22,043/65,536
on NTSC).

## Sizes

Code and data of each build, from the linker's map
(`python3 tools/sound/run65.py --sizes --update-readme`):

<!-- sizes:begin -->
| Part | native12 | mb6 | Budget | Source of the budget |
| --- | ---: | ---: | ---: | --- |
| code (music, bursts, refill, the IRQ entry) (`SNDCODE`) | 2,104 | 2,022 | 2,000 | native-sound.md 4.3: about 2,000 with the effects; NATIVE.md 4.3: player and effects 3-5 KB |
| tables: periods PAL and NTSC, bend, levels, layout (`SNDRODATA`) | 973 | 922 | 800 | native-sound.md 4.3: about 800 |
| state: voices, shadows, song tables (`SNDBSS`) | 567 | 512 | 500 | native-sound.md 4.3: voices and shadows about 200, song tables <= 300 |
| write lists (in one page) (`SNDLIST`) | 128 | 128 | - | not in the design |
| the song ring (and its 3-byte mirror) (`SNDRING`) | 1,027 | 1,027 | 1,024 | native-sound.md 4.3: 1,024 |
| zero page (player and IRQ entry) (`SNDZP`) | 31 | 31 | - | the IRQ contract: the card or the zero page |
| alignment padding in the card (between `SNDRING`, `SNDLIST`, `SNDBSS`) | 0 | 0 | - | the ring is page aligned |
| **Data in the card** | 2,695 | 2,589 | 2,324 | native-sound.md 4.3 without the effect buffers (800 + 200 + 1,024 + 300); NATIVE.md 4.1 gives the player 4.2 KB with them |
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
  in bank 1) cover it. `snd_probe` (114 bytes) is boot code and not in
  the card.

## Verification

`tests/test_sound_player65.py` (it builds the player and a2vm from
scratch; the song tests skip without the WAD, the player's without cc65):

| Test | What it checks |
| --- | --- |
| `Build` | Both layouts build with no warning from ca65 or ld65 (`run65.build()` fails on one, so every test that builds does too); a planted warning (the `.import vbl_count` of the first version) fails the build |
| `Tables` | Every table in the assembled player equals `tables.py` (both period tables of both layouts, bend, levels, owned registers in flush order); the IRQ contract's placement: code, data, ring, lists in the card, the vector at `$FFFE`, the zero page under `$100`; the ring page aligned, the write lists in one page |
| `Songs` | The 13 songs of the WAD, converted by `mus2ay.py` at test time, in both layouts, looping: 60 s on a PAL //e (3,005 interrupts each) and 20 s on NTSC (1,198); every interrupt's writes equal `player.Player`'s, and the start's first burst equals `Player.reset()`. And D_INTROA not looping, past its end |
| Every run | The chips are reset only by `snd_init` (the AY log's `reset` lines, before everything else); at the end the chips' 16 registers (a2vm's state) equal the model's shadow, the chips outside the layout 0, the card in its layout's mode (native for native12, Mockingboard for mb6); no interrupt reads or writes outside its bounds (above) |
| `RandomStreams` | 16 random song files (seeded) that use every command on every voice with the edges of the arithmetic: 16-bit envelope sums that carry, attacks of 65,535, attenuations past 80 (to 255), bends 0, 127, 129 and 255, loud and quiet drums, notes 0 and 127, a loop offset inside the stream; PAL and NTSC; and the music attenuation (0, 6, 30, 80) |
| `Ring` | A song of 2-3 KB looping through the ring for 30 s (the stream goes round more than 3 times, the ring's position counted by the 65C02 equals the model's); an underrun: no refills for 6 s, every music voice quiet, only level registers written (to 0), then the song goes on; start, stop, a stop's burst then silence, a song started while another plays, NTSC and a music attenuation per start, a song that ends; refused starts (version, layout, tables, an mb6 file on native12) |
| `PlantedBugs` | Eight bugs planted in copies of `player.s`, each caught by the comparison: the bend rounding down, R13 not rewritten after a retrigger, the release adding the decay step, chip 2 written before chip 0, the ring mirror never written, an off after an on in the same interrupt releasing at once, the tempo dropping the fraction's carry, the burst pulsing its VIA's reset after each write (every write as player.py's, the chips cleared). The tables the interrupt reads moved to main memory: the run halts on the interrupt bounds. The end-of-run register check fails on a changed register, a wrong card mode, and a wrong write in an interrupt the run cut. An unchanged copy passes |
| `Probe` | On the Phasor the probe finds 4 chips and on a card locked to Mockingboard mode (a2vm `--phasor-mb-only`) 2; each build runs only on its card (the other stops with A = $10 + the layout found). The mb6 player on the locked card, after the probe: 20 s of a random song and of D_E1M1 equal player.py, and the card is still in Mockingboard mode at the end (native-sound.md 5, item 2) |
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
| Song | Layout | Seconds | Bursts/s | Writes/s | F1.2.1, window 512: ms/s (in the IRQ) | formula | 4.2 | window 32: ms/s (in the IRQ) | formula | 4.2 | FW-S1: ms/s (in the IRQ) | formula | 4.2 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| D_E1M1 | native12 | 97.0 | 36.5 | 121.5 | 25.76 (8.88) | 23.30 | 23.90 | 8.79 (8.65) | 6.06 | 6.60 | 4.03 (3.91) | 1.02 | 1.12 |
| D_E1M2 | native12 | 156.4 | 36.6 | 86.5 | 24.04 (7.18) | 21.93 | - | 7.03 (6.94) | 4.65 | - | 3.43 (3.35) | 0.73 | - |
| D_E1M3 | native12 | 273.0 | 40.7 | 92.1 | 26.47 (7.74) | 24.26 | 25.60 | 7.52 (7.45) | 5.00 | 5.30 | 3.62 (3.55) | 0.77 | 0.81 |
| D_E1M4 | native12 | 171.7 | 38.4 | 110.9 | 25.87 (8.20) | 23.82 | - | 8.03 (7.94) | 5.69 | - | 3.59 (3.51) | 0.93 | - |
| D_E1M5 | native12 | 165.0 | 21.6 | 46.5 | 15.00 (5.06) | 12.77 | 12.90 | 4.95 (4.87) | 2.56 | 2.60 | 2.97 (2.91) | 0.39 | 0.39 |
| D_E1M6 | native12 | 85.0 | 42.5 | 138.1 | 29.55 (9.89) | 27.02 | 27.50 | 9.76 (9.66) | 6.92 | 7.10 | 4.34 (4.25) | 1.16 | 1.20 |
| D_E1M7 | native12 | 151.9 | 27.3 | 48.8 | 17.90 (5.39) | 15.73 | - | 5.20 (5.12) | 2.83 | - | 3.05 (2.99) | 0.41 | - |
| D_E1M8 | native12 | 153.0 | 18.5 | 41.1 | 12.98 (4.43) | 10.96 | 11.50 | 4.39 (4.31) | 2.24 | 2.50 | 2.67 (2.60) | 0.35 | 0.40 |
| D_E1M9 | native12 | 138.4 | 33.9 | 120.3 | 24.33 (8.71) | 21.97 | - | 8.54 (8.43) | 5.93 | - | 3.94 (3.84) | 1.01 | - |
| D_INTER | native12 | 202.4 | 38.0 | 117.8 | 25.99 (8.52) | 23.89 | 24.70 | 8.33 (8.23) | 5.95 | 6.50 | 3.72 (3.63) | 0.99 | 1.11 |
| D_INTRO | native12 | 7.8 | 26.0 | 56.6 | 18.10 (5.72) | 15.39 | - | 5.90 (5.56) | 3.10 | - | 3.33 (3.16) | 0.48 | - |
| D_INTROA | native12 | 7.8 | 24.8 | 55.8 | 17.33 (5.45) | 14.78 | - | 5.66 (5.33) | 3.04 | - | 3.16 (2.99) | 0.47 | - |
| D_VICTOR | native12 | 193.0 | 33.1 | 74.6 | 22.07 (6.84) | 19.71 | - | 6.66 (6.58) | 4.06 | - | 3.54 (3.47) | 0.63 | - |
| D_E1M1 | mb6 | 97.0 | 29.4 | 78.7 | 19.28 (5.47) | 18.01 | - | 5.59 (5.42) | 4.11 | - | 2.49 (2.38) | 0.66 | - |
| D_E1M2 | mb6 | 156.4 | 21.5 | 34.9 | 13.27 (3.22) | 12.23 | - | 3.28 (3.18) | 2.09 | - | 1.74 (1.67) | 0.29 | - |
| D_E1M3 | mb6 | 273.0 | 24.2 | 38.0 | 14.79 (3.52) | 13.73 | - | 3.54 (3.46) | 2.30 | - | 1.87 (1.80) | 0.32 | - |
| D_E1M4 | mb6 | 171.7 | 29.2 | 72.5 | 18.67 (5.01) | 17.66 | - | 5.07 (4.95) | 3.85 | - | 2.18 (2.10) | 0.61 | - |
| D_E1M5 | mb6 | 165.0 | 12.0 | 21.0 | 7.97 (2.33) | 6.88 | - | 2.41 (2.32) | 1.23 | - | 1.50 (1.43) | 0.18 | - |
| D_E1M6 | mb6 | 85.0 | 37.2 | 91.2 | 23.45 (6.08) | 22.43 | - | 6.15 (6.01) | 4.86 | - | 2.50 (2.41) | 0.77 | - |
| D_E1M7 | mb6 | 151.9 | 20.2 | 33.9 | 12.57 (3.11) | 11.55 | - | 3.17 (3.08) | 2.01 | - | 1.69 (1.63) | 0.28 | - |
| D_E1M8 | mb6 | 153.0 | 14.9 | 22.9 | 9.45 (2.44) | 8.44 | - | 2.52 (2.42) | 1.40 | - | 1.49 (1.43) | 0.19 | - |
| D_E1M9 | mb6 | 138.4 | 15.4 | 58.2 | 11.40 (4.16) | 10.09 | - | 4.26 (4.14) | 2.83 | - | 2.10 (2.01) | 0.49 | - |
| D_INTER | mb6 | 202.4 | 27.2 | 86.1 | 18.28 (5.54) | 17.20 | - | 5.63 (5.49) | 4.34 | - | 2.35 (2.26) | 0.72 | - |
| D_INTRO | mb6 | 7.8 | 18.9 | 26.6 | 11.91 (2.87) | 10.58 | - | 3.03 (2.82) | 1.67 | - | 1.70 (1.63) | 0.22 | - |
| D_INTROA | mb6 | 7.8 | 21.9 | 32.2 | 13.60 (3.16) | 12.35 | - | 3.30 (3.10) | 1.99 | - | 1.75 (1.67) | 0.27 | - |
| D_VICTOR | mb6 | 193.0 | 23.0 | 46.1 | 14.52 (3.79) | 13.43 | - | 3.85 (3.74) | 2.58 | - | 1.93 (1.86) | 0.39 | - |
<!-- cost:end -->

The run of 2026-09-30 took 16 minutes on 7 of 8 cores of an Apple M3
Pro (78 runs of a2vm with the counting loop, and 6 without a song).

**Against native-sound.md 4.2.** With the default window (512) the
player costs 13.0 to 29.6 ms a second in native12 (1.3% to 3.0% of the
machine), 8.0 to 23.4 in mb6. The design's six songs: D_E1M1 +7.8%,
D_E1M3 +3.4%, D_E1M6 +7.5%, D_INTER +5.2% against its table, within the
10% its section 5.2 asks for; **D_E1M5 +16% and D_E1M8 +13% are not**.
The formula column shows why: on this player's own counts, the design's
arithmetic (bursts x 504 us + writes x 40.4 us) gives 2.0 to 2.7 ms a
second less than measured in every native12 song (1.0 to 1.3 in mb6). That is the player's computing, which
the design estimated (about 2,500 cycles an interrupt, 2 ms a second,
native-sound.md 4.2) but left out of its table; it weighs most in the
quiet songs. Measured on the AY log's cycle counts (60 s of D_E1M1,
D_E1M8 and D_INTER, native12): 3,000
to 3,700 cycles an interrupt on average without the writes, 4,700 to
11,500 at the 99th percentile, 14,200 at most (D_E1M1, whose guitars bend
a lot: each bend is a 125-byte multiply). The burst and tail parts agree
with the design: the formula is 1% to 5% below its table, because S1's
player writes a little less than the design's prototype.

With **window 32** the cost is 4.4 to 9.8 ms a second (native12), against
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
- **The layout is fixed at assembly**, PAL or NTSC at start. The design
  shipped "two period tables of 73 notes"; these are 128 notes, as the
  model's. `snd_probe` finds the card's layout at boot; loading the
  matching build is the boot code's (milestone 11).
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
- The boot code that runs `snd_probe` and loads the matching build is
  milestone 11's. On a Phasor the probe leaves the card in native mode, so
  the mb6 build is only for cards that cannot switch (a Mockingboard, or
  the Phasor locked to Mockingboard mode); an owner who wants mb6 on a
  Phasor would need a setting, not in the design.
- ALTZP on (the tic window of the design + pair variant) needs the aux
  card's copy of the vector and a bridge (NATIVE.md 10); not written.
- Effects (S4): chip 3 in native12 and chip 2's mixer in mb6 are shared
  with the effect voices; the flush here owns the music's registers only.
- Nothing has run on the card (S3).
