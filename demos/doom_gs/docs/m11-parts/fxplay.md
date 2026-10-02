# Milestone 11, part `fxplay`: the effect player

Part `fxplay` of wave 3 ([`docs/SCREENS.md`](../SCREENS.md) 0.1 F12, 2.3,
3, 4.4, 6.4, 7.3; [`tools/sound/README.md`](../../tools/sound/README.md)
"Effects (S4)": "The player", "No native mode", "Stereo by voice",
"Volume", "Memory", "Cost"), 2026-10-01. Labels as in `NATIVE.md`: [M]
measured, [R file:line] read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `src/sound/fx.s` | The effect player, two objects from one file. The card part (`FXCODE`, `$F505-$F8FF` with `pl_vbl`): `fx_step` (the interrupt's tempo, each active voice's ticks from its ring, chip 3 composed, the write list; no I/O), `fx_burst` (the list to VIA-B's second AY, S2's 41-cycle loop), `fx_song`, `fx_init`, `fx_stopall`, `fx_isplaying`, `fx_copy` and `fx_volume` (the main loop's two RAMRD windows on bank `SFX`, which must run outside `$0200-$BFFF`), chip 3's `want`, `shadow` and write list. The frame side (`-D FX_SERVICE`, segment `S2CODE`, the size table's module `fx`): `fx_service` |
| `src/sound/fxdrv.s` | Test only: the driver of the test machine (S2's `driver.s` as the model): boot (`pl_clkset`, `snd_probe` optional, `snd_init`, `fx_init`), a calibration of its delay loop, actions at given VBLs (song start through `fx_song`, song stop, the mailboxes' start, stop and volume as the channel logic writes them, the gates, `fx_stopall`, `fx_isplaying` queries, the frame length, an extra `fx_service`), a frame every N VBLs (`fx_service`, then `snd_refill`), `drv_mark` for the write log's timeline, a counting loop for the cost |
| `tools/sound/fxplay.py` | The specification and the oracle (its docstring is the player's rules): `FxPlayer` (`init`, the mailbox writer `mail_start`/`mail_stop`/`mail_volume`, `service`, `stopall`, `isplaying`, `song_begin`/`song_end`, `step`/`interrupt`), `Voice.tick`, the bank reader |
| `tools/sound/fxrun65.py` | The test machine's ld65 map (`--cfg`), the builds (`make`, a scratch copy through `FXSRC`), the a2vm runs (AY log, write log, `--irq-bounds`, `--lowest-s-in`, final snapshot), the timeline oracle, the comparisons, the scenarios, `--checkpoint [--quick]`, `--cost`, `--timing`, `--planted` |
| `src/native/m11/fxplay.mk` | `make -f m11.mk part P=fxplay`: `fx-card.o`, `fx.o`, `fxdrv.o`, the test machine `fxt.*` (S2's `player.o` and `probe.o` from `build/sound65`, read only; `pl_irq.o`), and `fxpt.*`: the card part and `fx_service` linked in `P2DW`'s room under `s2_drv` (the size table's `fx_service` row, `FXC`'s room checked by ld65) |
| `tests/wip_test_m11_fxplay.py` | 15 tests: 11 of the model on a hand-made bank (no `build/` needed), the map; with `build/`: the checkpoint, the sizes, the planted bugs, the noise case's discrimination |

Build output: `build/native/m11/fxplay/` (856 KB). Every run's
directory is a `tempfile` directory `build/tmp-fxplay-*` deleted after
the run; nothing else is written.

## 2. The player as built (decisions where the design left a choice)

Each is in `fxplay.py`'s docstring, which the 65C02 code follows.

1. **Two objects from `fx.s`.** The design names one file with card and
   frame-side routines; ca65 assembles it twice (`fx-card.o`, and
   `fx.o` with `-D FX_SERVICE`), so a frame image links only
   `fx_service` and the card image only the card part.
2. **The windows run in the card.** A RAMRD window hides main
   `$0200-$BFFF`, `fx_service`'s own code in W included, so the copies
   from bank `SFX` are `fx_copy` (A bytes, self-modified operands
   `fxc_ld+1`, `fxc_st+1`) and `fx_volume` (one byte of `VATT`), in the
   card, as S2's `snd_refill` is. Each window writes `$C073` then 0 [R
   `far.s:12-14`].
3. **`VATT` stays in bank `SFX`** (`SFX.1`'s `$02D0`, part `fxconv`):
   `fx_volume` reads the byte through a window at a start or a volume,
   and stores the attenuation in the voice (`V_ATT`); the interrupt never
   reads `VATT`. The card's 128 B of `VATT` are not needed (FXPLAY-2).
4. **The header goes into the ring**: a start copies the script's first
   up to 128 bytes from its directory address (the 4-byte header
   included), then sets `rpos` 4. `fxconv`'s budget counts the header at
   tick 0 [R `docs/m11-parts/fxconv.md` 2 item 9], so the first 42 ticks
   still fit; it saves the header arithmetic in `fx_service`.
5. **Refill**: twice, a piece of min(free, to the ring's end, left)
   bytes, each published (`V_WPOS +=`) after its bytes. `V_WPOS` (the
   main loop's) and `V_RPOS` (the interrupt's) count bytes mod 256, so
   each side writes only its own byte and 128 unread bytes are told from
   0.
6. **A tick** (`Voice.tick`): a wait `$00-$3F` of n + 1 ticks counts
   this tick as its first; a set is read only when all its bytes are in
   the ring; a set's bit 3 makes the voice end when its wait expires; a
   byte `$50-$FE` ends the voice as `$FF` does. A tick without its bytes
   marks the voice `STARVED` and holds it for the rest of the interrupt
   (it tries again at the next).
7. **Compose**: an active voice that is not starved gives its period,
   `LEVEL[min(80, att + VATT)]` (S2's `level_of_att`) and its tone and
   noise bits; every other voice level 0 and both bits off, its period
   kept; an ending one becomes idle (the README's "level 0 once"). R6:
   the loudest voice with noise, the lowest min(80, att + VATT), the
   first voice of a tie; unchanged when no voice has noise. R7's bits
   6-7 are 0.
8. **The write list is built in `fx_step`** (R10 first), so `fx_burst`
   is S2's loop alone right after the music's burst, with no
   computation between (the shared slowdown tail). Nothing while
   `FX_HOLD`; with `FX_INVAL` all of R0-R10 (also when the only voice
   left is an ending one), then the shadow is valid.
9. **The tempo** (the music's fraction, PAL or NTSC from `CLK_STD`'s
   bit 7 at each interrupt, so `fx_init` may precede `pl_detect`) runs
   only in an interrupt where a voice is active or ending.
10. **`fx_service` with more channels than voices** (`FXCH8`): a start
    that finds no free voice is dropped.
11. **Interfaces.** `fx_init`: A = `snd_probe`'s answer. `fx_song`:
    S2's `snd_start`'s arguments; returns its carry and A; X changed.
    `fx_isplaying`: X = a channel; carry set and A = 1 when playing, else
    carry clear and A = 0; X kept, Y changed. `fx_stopall`: every active
    voice ending, every mailbox emptied. Sounds 1-52 (`MX_SOUND`), volume
    0-127 (bit 7 ignored), separation 0-255.
12. **The places.** The interrupt's zero page is `ZP_FXRING` (`$F7-$FC`):
    the current voice's ring pointer and four temporaries (compose
    reuses them), not three ring pointers; `fx_service`'s four
    temporaries are `FX_SPARE` (`$E73C-$E73F`, main loop only); the
    consumed count `V_RPOS` is `V_SIDE`'s byte (the side is the voice's).
    Local names marked `STANDIN` in `fx.s` until FXPLAY-1.

## 3. Checkpoint

Commands, from `demos/doom_gs` (`df -h /System/Volumes/Data`: 74 GB free):

```
make -C src/native -f m11.mk part P=fxplay                # no warning
python3 tools/native/s2layout.py --check                  # passes
python3 tools/sound/fxrun65.py --checkpoint --jobs 2      # 25 s
python3 tools/sound/fxrun65.py --planted --jobs 2         # 5 s
python3 tools/sound/fxrun65.py --cost --jobs 2            # 2 min (no idle skip)
python3 tools/sound/fxrun65.py --timing --jobs 2          # 1 s
python3 tools/testpar.py --jobs 2 tests/wip_test_m11_fxplay.py   # 15 tests, 30 s
python3 tools/testpar.py --jobs 2 test_sound_ayrender test_sound_decoders \
    test_sound_disk test_sound_mus test_sound_mus2ay test_sound_player \
    test_sound_player65 tests/wip_test_m11_s2lay.py tests/wip_test_m11_plclock.py
```

Every run: the Doom profile `f121+phasor+window32` unless named,
`--cost-timed`, `--irq-bounds 00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF`,
the AY log, the write log (the voices, `FX_ON`-`FX_SPARE`, the rings,
`snd_playing`, `drv_mark`), the final snapshot. The oracle takes the
interrupts (AY log) and the main loop's events (`drv_mark`; `fx_song`'s
`FX_HOLD` and `snd_playing` stores) in time order: an interrupt is S2's
music model (`run65.RingPlayer`) then `fxplay.FxPlayer.step()`, and must
equal the machine's write for write (chips 0-2, then chip 3); the main
loop's writes between interrupts, the chips at the end, `drv_qlog` (the
`fx_isplaying` answers) and the write log's publish order are checked
too. An interrupt that lands inside a main-loop event other than a song
start fails the run (the model would not know where it fell).

Results [M, 2026-10-01], all 0 problems:

| Item | Result |
| --- | --- |
| Every effect alone: PAL and NTSC × volumes 127, 63, 6 × voices A, B, C | 18 runs, the 52 effects each, one after the other: every interrupt equal to the model (PAL 2,290 interrupts, NTSC 2,722 a run; 2,008-3,143 chip-3 writes). Voice C is reached by a start on A and one on C in the same gap, A stopped before any interrupt |
| Each effect over each of the 13 songs, 20 s | 132 starts a song at demo3's measured times (its 430 `S_StartSound`/`S_StartSound2` gametics, `build/native/m11/cases/demo3/calls.z`, at 34.955 a second from VBL 10), each of the 52 effects in every song, channels 0-2 in turn, volumes 127, 90, 63, 30, 6 and separations 128, 127, 129, 64, 200, 1, 255: every interrupt equal to the model, and chips 0-2 equal S2's own build's (`build/sound65`, `snd_vbl`) log of the song alone, interrupt for interrupt (3,045-3,711 chip-3 writes a run) |
| No effect: 13 songs, 20 s | the whole AY log equal to S2's own build's, group for group (before the first interrupt, each interrupt, the main loop after each), and the chips at the end (no run ended inside an interrupt) |
| Ring underrun | `DORCLS` (460 B) with `fx_service` gated off 40 VBLs, then `SAWFUL` gated 25: the ring runs dry, the voice is silent (level 0) and holds, then goes on; equal to the model |
| The IRQ bounds | held in every run (a2vm stops the run on any access outside them) |
| Held across `fx_song` | 40 song starts while effects play, each after a delay a step longer (the driver's calibrated loop, 2.5 × a VBL over the 40): 5 VBLs landed with `FX_HOLD` set (interrupts 344, 356, 368, 380, 392); none wrote chip 3; the next burst of chip 3 wrote all of R0-R10; the whole run equal to the model (old song, held interrupt, new song) |
| A tone effect before any song | `PISTOL` (its first state has a tone) at VBL 3 with no song: chip 3 holds the reset's values (R7 0); the first burst writes R0-R10, all 11 |
| `--phasor-mb-only` | `snd_probe` answers no music; effects started, queried, a song action: no AY write past the probe's, `FX_ON` 0, `fx_isplaying` 0 after the frame |
| The stereo rule | separation 127 A, 128 A, 129 B; A busy: 128 C; A and C busy: 128 B; B busy: 129 A; B and A busy: 129 C; a channel's own voice freed first (A again) |
| The mailboxes | a start then a stop in one frame: no voice (`fx_isplaying` 1 between them, 0 after); a stop then a start: the new sound (on B, separation 200); a start then a volume: the new volume; equal to the model |
| The noise of the loudest | two noisy effects, the louder first then the louder last: 57 interrupts where "the loudest" and "the last" differ [M: the model] |
| Three effects started in one VBL over music | D_E1M1 and D_INTRO, window 32 and 512, the first three on the song's first chord: worst interrupt 2,047.9 µs (window 32), 2,050.8 µs (512), both D_INTRO's first chord with chip 3 written whole (music alone 1,548.9 and 1,567.4 µs); D_E1M1 1,516.2 / 1,519.1 µs (alone 1,017.2 / 1,035.7); median 248-271 µs; stack 16 B (limit 24) |
| `tests/test_sound_*` | unchanged (no file of S2 or S3 edited), green: 7 modules |
| Python 3.9.6 | `wip_test_m11_fxplay` OK with `-W error::ResourceWarning` (15 tests, 39 s) |

## 4. Planted bugs (each in a scratch copy) and the check that caught it

Each is a text replacement in a copy of `fx.s` (`fxrun65.PLANTED`),
built apart into a `tempfile` directory (`make ... M11=<tmp>/m11
FXSRC=<tmp>/src`) and run through the named scenarios.

| Bug | Caught by | The failure |
| --- | --- | --- |
| Chip 3's burst before the music's (`fx_step` ends with `jmp fx_burst`; `pl_vbl` is `plclock`'s file) | 13 songs' order check | "interrupt 11: a write of chip 0-2 after chip 3's" |
| The noise period of the last voice instead of the loudest | stereo run, the noise cases | "interrupt 105 (chip 3): write 2 is (3, 6, 17), expected (3, 6, 16)" |
| A ring refill published before its bytes | the write log's publish order (underrun run) | "voice 0: byte 0 of the ring published at clock 4305058 before it was written (pc $0B67)" |
| The side choice inverted | stereo run | "interrupt 3 (chip 3): write 0 is (3, 0, 0), expected (3, 0, 68)" |
| The distance attenuation added twice | every effect alone, volume 63 | "interrupt 3 (chip 3): write 8 is (3, 8, 5), expected (3, 8, 9)" |
| `FX_INVAL` ignored (the shadow kept across a song start) | the hold run | "interrupt 8 (chip 3): write 23 is (3, 6, 16), expected (3, 1, 0)" |
| Separation 128 to voice B | stereo run | "interrupt 36 (chip 3): write 0 is (3, 2, 108), expected (3, 0, 108)" |
| `fx_isplaying` ignoring a pending start | stereo run's queries | "fx_isplaying: [0, 0, 0, 1, 1, 3, 0], the model [1, 0, 0, 1, 1, 3, 0]" |

## 5. Sizes against the budget

| Item | Size [M] | Budget |
| --- | ---: | ---: |
| The card part (`fx-card.o`, `FXCODE`) | 739 B: 694 code, 45 chip-3 state (`want`, `shadow` 11 each, the list 22, its length) | 620 B and `VATT`'s 128 B: 748 B (`VATT` stays in bank `SFX`, 2 item 3) |
| `FXCODE` in all, with `pl_vbl` (244 B) | 983 of 1,019 B (`$F505-$F8DB`), 36 B left | `$F505-$F8FF` |
| `fx_service` (`fx.o`, `S2CODE`) | 396 B (`fxpt.sizes`: `P2DW fx_service 396 of 400 B`) | 400 B |
| Card state | voices `$E413-$E442`, `FX_ON`-`FX_TEMPO` `$E737-$E73B`, `fx_service`'s temporaries `$E73C-$E73F`, rings `$E740-$E8BF` | SCREENS.md 4.4 |
| Zero page | `$F7-$FC` (the interrupt's) | `ZP_FXRING` |
| The interrupt's stack | 16 B | 24 B |

## 6. Timing (SCREENS.md 6.4) and cost

`fx_service` a frame, three effects playing (each of the 52 in turn,
back to back) over D_E1M1, between `drv_mark`'s stores (an interrupt
inside left out):

| Profile | Frames a second | `fx_service` median / p99 / worst |
| --- | ---: | --- |
| `f121` (Doom profile) | 50.1 | 19.0 / 89.7 / 130.2 µs |
| `f121` | 6.3 | 58.2 / 189.7 / 191.1 µs |
| `fastpath` | 50.1 | 13.1 / 59.2 / 87.2 µs |
| `fastpath` | 6.3 | 42.8 / 125.6 / 129.0 µs |

The cost a second (`drv_count` against the same run without effects; 1
or 3 channels each playing the 52 effects in turn; no music):

| Setting | Effects | From the main loop | In the interrupt | Tail | Chip-3 writes/s | Bursts/s | Tail a burst |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| window 512 | 1 | 18.69 ms/s | 3.66 | 15.02 | 55 | 31.6 | 475 µs |
| window 512 | 3 | 33.18 ms/s | 9.60 | 23.58 | 173 | 48.6 | 485 µs |
| window 32 | 1 | 4.00 ms/s | 3.66 | 0.34 | 55 | 31.6 | 11 µs |
| window 32 | 3 | 10.64 ms/s | 9.60 | 1.04 | 173 | 48.6 | 21 µs |
| FW-S1 | 1 | 1.66 ms/s | 1.31 | 0.34 | 55 | 31.6 | 11 µs |
| FW-S1 | 3 | 4.27 ms/s | 3.23 | 1.04 | 173 | 48.6 | 21 µs |

Over D_E1M1 with three effects (the song alone the base): window 512
17.73 → 39.84 ms/s (the effects 9.21 ms/s in the interrupt, 12.90 of
tail); window 32 5.99 → 16.62 (9.60, 1.04); FW-S1 3.17 → 7.44 (3.23,
1.03). Of the interrupts where chip 3 writes, 24.2 a second share the
music's burst and pay no tail of their own; 24.4 a second write alone
and pay an **extra tail of 529 µs (window 512), 42 µs (window 32, the
Doom profile) or 42 µs (FW-S1)** each. The design's estimates [A]: 3.2
ms/s for one effect, 10 for three, a tail of about 505 µs at window 512
and 32 µs at window 32 (`tools/sound/README.md` "Cost").

## 7. Requests (for the integrator; stand-ins marked `STANDIN` in `fx.s`)

### FXPLAY-1. `tools/native/s2layout.py`: the effects' names

**Evidence.** Section 2 items 5 and 12: the interrupt reads a ring
through one pointer at a time (the voices are indexed by X = 16 v, so
three pointers would need a copy anyway) and needs four temporaries;
`fx_service` needs four temporaries outside the interrupt's zero page;
the consumed count is a voice byte, the side a function of the voice.

**Stand-in.** In `fx.s`: `V_RPOS = V_SIDE`, `FXZ_RING = FX_RP0`,
`FXZ_N = FXZ_MIX = FX_RP1`, `FXZ_T = FXZ_BEST = FX_RP1 + 1`,
`FXZ_AV = FXZ_A = FX_RP2`, `FXZ_OP = FXZ_V = FX_RP2 + 1`,
`FXS_C`, `FXS_V`, `FXS_N`, `FXS_P` = `FX_SPARE` + 0-3.

**What.**

- `VOICE_FIELDS`: `('V_SIDE', 1)` becomes `('V_RPOS', 1)`, and the
  comment above it "(fxplay finalizes the fields; offsets)" becomes
  "(part fxplay, src/sound/fx.s: V_WPOS the main loop's bytes put in the
  ring and V_RPOS the interrupt's taken from it, both mod 256; V_LEVEL
  the step's attenuation; V_ATT the volume's, VATT[volume])".
- `FX_FIELDS`: `('FX_SPARE', 4)` becomes `('FX_SVC', 4)` with the comment
  "fx_service's temporaries, main loop only (FXS_C, FXS_V, FXS_N,
  FXS_P)".
- `ZP_FXRING = (0xF7, 0xFD)` keeps its range; its comment becomes "the
  effect player's interrupt: the ring of the voice it runs and four
  temporaries"; `FX_RP` becomes `FX_ZP = {'FXZ_RING': 0xF7, 'FXZ_N':
  0xF9, 'FXZ_T': 0xFA, 'FXZ_AV': 0xFB, 'FXZ_OP': 0xFC}` (`zeropage()`
  writes it); `check()`'s line `if sorted(FX_RP.values()) !=
  list(range(ZP_FXRING[0], ZP_FXRING[1], 2))` becomes `if FX_ZP !=
  {'FXZ_RING': ZP_FXRING[0], 'FXZ_N': ZP_FXRING[0] + 2, 'FXZ_T':
  ZP_FXRING[0] + 3, 'FXZ_AV': ZP_FXRING[0] + 4, 'FXZ_OP': ZP_FXRING[0] +
  5}`, and its message "the ring pointers" stays.
- `FX_CODE`'s comment becomes "pl_vbl, the clock (244 B, part plclock);
  fx.s's card part (739 B, part fxplay); 983 of 1,019 B".

Then in `fx.s`: drop the `STANDIN` lines; `FXZ_MIX`, `FXZ_BEST`,
`FXZ_A`, `FXZ_V` become `FXZ_N`, `FXZ_T`, `FXZ_AV`, `FXZ_OP` (aliases
kept in `fx.s`); `FXS_*` = `FX_SVC` + 0-3. The addresses do not move:
the images are unchanged. **Effect on others:** none (no other part uses
these names).

### FXPLAY-2. `docs/SCREENS.md` 2.3, 3, 4.3, 4.4 and `tools/sound/README.md` "Effects (S4)": the player as built

- SCREENS.md 4.4, row `$F505-$F8FF`: "`fx_step`, `fx_burst`, `fx_song`
  (about 620 B [A]), `VATT` (128 B)" becomes "`fx.s`'s card part: `fx_step`,
  `fx_burst`, `fx_song`, `fx_init`, `fx_stopall`, `fx_isplaying`,
  `fx_copy`, `fx_volume` and chip 3's state, 739 B [M: part `fxplay`];
  983 of 1,019 B in all. `VATT` stays in `SFX.1` (bank `SFX`, `$02D0`),
  read through a window by `fx_volume`". Row `$E737-$E73F`: "`FX_ON`,
  `FX_HOLD`, `FX_INVAL`, the effects' tempo fraction (2), `fx_service`'s
  4 temporaries (main loop)".
- SCREENS.md 4.3, row `$F7-$FC`: "the effect player's interrupt: the ring
  of the voice it runs, four temporaries (part `fxplay`)".
- SCREENS.md 3, the table's `fx_step`, `fx_burst` row, "Where it lives":
  "the card `$F505-$F8FF`, state `$E413-$E442` and `$E737-$E73F`, rings
  `$E740-$E8BF`; `VATT` in bank `SFX`".
- README "The player": `fx_step` row, after "Its own tempo fraction":
  "(it runs in an interrupt where a voice is active or ending; PAL or
  NTSC from `CLK_STD`)"; after "each active voice runs its ticks from its
  ring": "(a tick without all its bytes holds the voice, silent, for the
  rest of the interrupt)"; "R6 the noise period of the loudest voice
  with noise on" gains "(the lowest min(80, step + `VATT`), the first of
  a tie; unchanged when none)"; "No I/O" gains "; the write list is
  built here, so `fx_burst` follows the music's burst with no
  computation between". `fx_burst` row: "with the shadow invalid
  (`FX_INVAL`) and a voice active" becomes "... active or ending".
  `fx_service` row: "copies the script's first 128 bytes into its ring"
  becomes "copies the script's first 128 bytes (its 4-byte header with
  them, taken at once) into its ring"; add "The copies run in the card
  (`fx_copy`, `fx_volume`): a RAMRD window hides W". `fx_init` row: "A
  = `snd_probe`'s answer". `fx_song` row: "returns `snd_start`'s carry
  and A".
- README "Memory": replace "`fx_step`, `fx_burst`, `fx_song` and `VATT` in
  `$F505-$F8FF` after S2's code (about 750 B of the 1,019 left, with
  `pl_vbl`), ring pointers in zero page `$F7-$FC`" with "`fx.s`'s card
  part (739 B: the routines and chip 3's `want`, `shadow` and write list)
  in `$F505-$F8FF` after S2's code, with `pl_vbl`: 983 of 1,019 B
  [M: `docs/m11-parts/fxplay.md`]; `VATT` read from `SFX.1` through a
  window; the interrupt's ring pointer and temporaries in zero page
  `$F7-$FC`, `fx_service`'s in `$E73C-$E73F`". "`fx_service` (about 400
  B)" becomes "`fx_service` (396 B [M])".
- README "Cost": add after its paragraph "Measured (part `fxplay`,
  `docs/m11-parts/fxplay.md` 6): one effect 3.66 ms/s in the interrupt,
  three 9.60; from the main loop 18.69 and 33.18 ms/s at window 512,
  4.00 and 10.64 at window 32, 1.66 and 4.27 with FW-S1; over D_E1M1 a
  burst the effects write alone pays a tail of 529 µs (window 512) or 42
  µs (window 32), one that shares the music's pays none; the worst
  interrupt, three effects starting on D_INTRO's first chord, 2,048 µs
  in the Doom profile (the music alone 1,549 µs)."
- README "Tests", row `fxplay`: add "the publish order on the write log;
  `fx_isplaying`'s answers; the cost and the tail (`tools/sound/
  fxrun65.py --cost`)".

**Evidence:** sections 2, 3, 5 and 6. **Effect on others:** none.

### FXPLAY-3. The builds that link the player (integration, `plboot`, `fxdisk`)

- The card image (and every test build with `pl_vbl` that wants
  effects) links `fx-card.o` in place of `plclock`'s `pl_fxstub.o`, with
  S2's `player.o` (`snd_start`, `level_of_att`). `fx-card.o` uses
  `SC_MAIL` and `NUM_CHANNELS` (`fx_init`, `fx_stopall`, `fx_isplaying`,
  `fx_volume`), so it is assembled with the build's `s2.inc`
  (`s2-release.inc` in the release, `s2-m11.inc` in milestone 10's `M11`
  build, whose channel block is at `$EE40`). `fxplay.mk`'s rules show
  the flags (`-I build/sound65` for `tables.inc`).
- Every frame image (`P2DW`, `MENUW`, `WIW`, `FINW`) links `fx.o` (the
  size table's `fx_service` row) and resolves `fx_copy`, `fxc_ld`,
  `fxc_st`, `fx_volume` from the card: link `fx-card.o` and `player.o`
  into its `FXC`/`SND` files as `fxpt` does (those files are not
  stored), or an import list of the card's addresses.
- `fx_burst`'s lists must not cross a page (`fx.s` asserts it at link
  time, `lderror`): if a release link moves them across, align `FXCODE`
  or move `fx_wreg`/`fx_wval`.
- Boot order (for `plboot` and `SOUNDS.SYSTEM`): `snd_probe`,
  `snd_init`, `fx_init` with the answer in A, then the VBL, `CLI`,
  `pl_detect` (the tempo reads `CLK_STD` at each interrupt). Bank `SFX`
  must hold `SFX.1` before the first `fx_service`.
- Optional: `plclock`'s `plct`, `music/` and `bridge/` images may link
  `fx-card.o` in place of the stand-ins (with `FX_ON` 0 it writes
  nothing, so their checks hold); then `pl_fxstub.s` can go.

### FXPLAY-4. For part `fxchan` (no change asked)

The mailboxes are written as `fxdrv.s`'s `act_start`, `act_stop`,
`act_volume` write them (`fxplay.FxPlayer.mail_*`): a start ORs
`MX_START` and sets the sound (1-52, the pickup bit removed), the volume
(0-127) and the separation; a stop sets `MX_STOP` and clears `MX_START`
and `MX_VOLUME`; a volume ORs `MX_VOLUME` and sets the volume.
`fx_isplaying`: X = the channel; carry and A as in section 2 item 11; it
lives in the card, so the tic image and `MENUW` both call it. In `FXCH8`
(8 channels, 3 voices) a start that finds no free voice plays nothing.

## 8. Open problems

1. Nothing has been heard: the effects' loudness against the music and
   the left lean of centred sounds are the owner's at milestone 12.
2. The hold test lands VBLs inside `fx_song` by a swept delay; on the
   card the window is wherever a song starts. The model is exact for
   any landing the write log shows, and the test fails if none lands.
3. A refill can be interrupted (as S2's): the publish order makes that
   safe, checked on the write log; the AY comparison itself needs every
   frame's `fx_service` to finish between two interrupts, and fails a
   run where one does not.
4. `fx_burst`'s 41 cycles a register hold only while its lists stay in
   one page (FXPLAY-3).
5. FXPLAY-1's names are stand-ins until the integrator applies it.
6. The card keeps 36 B free in `$F505-$F8FF`; PLCLOCK-2 (a boot segment
   for `pl_clkset`, `pl_detect`) would free 128 B more, and `fx_init`
   (52 B) could join it.

## 9. The wave 3 integration (2026-10-01)

What the integrator did with each request (`docs/SCREENS.md` 8.7, "Wave
3 as integrated"):

| Request | Outcome |
| --- | --- |
| FXPLAY-1 | Applied as written: `s2layout.py` `VOICE_FIELDS` has `V_RPOS` in `V_SIDE`'s place, `FX_FIELDS` `FX_SVC` in `FX_SPARE`'s, `FX_ZP` (`FXZ_RING` `$F7`, `FXZ_N` `$F9`, `FXZ_T` `$FA`, `FXZ_AV` `$FB`, `FXZ_OP` `$FC`) in place of `FX_RP`, written into `s2.inc`'s zero page and checked by `check()`; `FX_CODE`'s comment. In `fx.s` the `STANDIN` lines are gone: `FXZ_MIX`, `FXZ_BEST`, `FXZ_A`, `FXZ_V` are aliases of `FXZ_N`, `FXZ_T`, `FXZ_AV`, `FXZ_OP`, and `FXS_*` are `FX_SVC` + 0-3. The addresses did not move: the sizes and every result below are the part's |
| FXPLAY-2 | Applied: SCREENS.md 3 (the `fx_step` row), 4.3 (`$F7-$FC`), 4.4 (`$E413-$E442`, `$E737-$E73F`, `$F505-$F8FF`); `tools/sound/README.md` "The player" (the `fx_step`, `fx_burst`, `fx_service`, `fx_song`, `fx_init` rows), "Memory", "Cost" (the measured paragraph), "Tests"; `design.md` R2 item 1 (rows `$E900-$F8FF`, `$E737-$E73F`) for the final integrator |
| FXPLAY-3 | Nothing to apply yet: no release card image exists before `plboot`, and the frame images are built by waves 4-6 (each links `fx.o` and resolves the card's names from `fx-card.o` as `fxpt` does). The page assertion stays in `fx.s`. `plclock`'s test images keep `pl_fxstub.o` (optional; their checks are unchanged), so `pl_fxstub.s` stays until `plboot` or the final integration |
| FXPLAY-4 | Nothing to apply; kept for `fxchan` (wave 4) |

## The final integration of the first half (2026-10-02)

FXPLAY-3's optional item applied: `plclock`'s and `plinput`'s images link `fx-card.o`, and `pl_fxstub.s` is deleted. `fxrun65.py --cost` gained the report's rows (SCREENS.md 8.3): D_E1M1 with the effects at demo3's measured start times and with three started together, and each run's worst interrupt (SCREENS.md 8.14). The test is `tests/test_m11_fxplay.py`. (`docs/SCREENS.md` 8.13.)
