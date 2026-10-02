# Milestone 11, part `plclock`: the IRQ entry, the clock, the bridge

Part `plclock` of wave 2 ([`docs/SCREENS.md`](../SCREENS.md) 2.2, 2.3,
4.4, 6.5, 7.3), 2026-10-01. Labels as in `NATIVE.md`: [M] measured, [R
file:line] read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `src/native/pl_irq.s` | `pl_vbl`, the main card's IRQ vector, with SCREENS.md 2.3's seven steps: A, X, Y saved and a BRK (the pushed P's B bit) to the crash stop; the mouse card's status read, then acknowledged, and only the VBL cause counts; the clock; `fx_step`; `snd_tick` (S2's player, unchanged); `fx_burst`; restore and `RTI`. Steps 2-6 are the subroutine `pl_vbody`, which the bridge calls. `pl_crash` (interrupts masked, the VBL off, a loop; it writes nothing outside the IRQ contract). `pl_time` (`I_GetTime`: the 32-bit tics read with interrupts masked, A, X, Y bits 0-23 and bits 24-31 copied to `CLK_TIME3`, P's I bit kept). `pl_clkset` (A = the standard: its fraction, the clock and the VBL count from 0). `pl_detect` (PAL or NTSC as `MUSIC.SYSTEM`: VIA-A's timer 1 over one VBL, the cut 18,655, then `pl_clkset`; returns A = the standard and the count in X:Y). The main card's vectors. All code in `FXCODE` (`$F505-$F8FF`); the VBL count `vbl_count` in `SNDZP` |
| `src/native/pl_fxstub.s` | **STANDIN**, test images only: `fx_step` and `fx_burst`, one `RTS`, until `fxplay`'s `src/sound/fx.s` |
| `src/native/pl_bridge.s` | The aux card's bridge at `$FF00` (`PLBRIDGE`) and the aux card's vectors (`AUXVEC`): A, X, Y on the aux stack, a BRK to `pl_crash` with `ALTZP` off, else `ALTZP` off, `jsr pl_vbody` on the main stack, `ALTZP` on, A, X, Y back, `RTI` from the aux stack. The same bytes sit at `$FF00` in both cards, so the fetch continues across each `ALTZP` store (MEMORY_MAP.md 4.4) |
| `src/native/pl_ct.s` | Test only: `plt_mode`, `plt_clock` (snd_init, the standard detected or given, then the clock logged after each of N VBLs: 4 bytes a VBL in W from `$7000`, the VBL count checked to be k at the k-th) under the test driver `s2_drv` |
| `src/native/pl_bt.s` | Test only: the bridge machine's main program (markers on the main stack, `ALTZP` on, a loop on the aux zero page and stack that checks its registers and pushed values; an optional BRK with `ALTZP` on) |
| `tools/native/plclock.py` | The host model (the fraction from the rates, `clock_at(n)`, the rates, the detection's cut, a self-check of the step form against the closed form over 70,000 VBLs); the two ld65 maps (`--cfg music`, `--cfg bridge`, from `s2layout.py`'s places); the a2vm runs (`clock_run`, `music_run`, `s2_music_run` through `tools/sound/run65.py`, `bridge_run`) and their checks; `--model`, `--checkpoint` |
| `src/native/m11/plclock.mk` | `make -f m11.mk part P=plclock`: `plct` (the clock's test image, P2DW's room, `s2_drv` with `-D PL_VBL`, S2's `player.o` in the card), `music/sound.*` (S2's `driver.o`, `player.o`, `probe.o` from `build/sound65`, read only, with `pl_irq.o` and the stand-ins, at the game's places), `bridge/plbr.*` |
| `tests/wip_test_m11_plclock.py` | 19 tests: the model, the maps, the clock (60 s PAL and NTSC), the second entry, the sizes, the music (13 songs and an NTSC song), the bounds, the bridge, the five planted bugs |

Build output: `build/native/m11/plclock/` (about 0.6 MB). Every run's
directory is a `tempfile` directory under `build/` (`tmp-m11-plclock-*`)
that the caller deletes.

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
make -C src/native -f m11.mk part P=plclock          # no warning
python3 tools/native/s2layout.py --check              # passes with the new sources
python3 tools/native/plclock.py --model
python3 tools/native/plclock.py --checkpoint --jobs 2 # every run below, 7 s
python3 tools/testpar.py --jobs 2 tests/wip_test_m11_plclock.py   # 19 tests, 22 s
python3 tools/testpar.py --jobs 2 test_sound_ayrender test_sound_decoders \
    test_sound_disk test_sound_mus test_sound_mus2ay test_sound_player \
    test_sound_player65
```

Results [M, 2026-10-01]:

| Item | Result |
| --- | --- |
| The model | PAL 50.0801 Hz × 45,743 / 65,536 = 34.9551 tics a second; NTSC 59.9227 Hz × 38,229 / 65,536 = 34.9546; both fractions equal round(34.955 × 65,536 / the VBL's rate) |
| Clock, PAL (`--cost f121 --cost-timed`, 60 s) | `pl_detect` counted 20,280 bus cycles: PAL; 3,004 VBLs logged, the fraction and the tics equal to the model at **every** VBL; 2,096 tics at the end (the model 2,096); 34.954 tics a second and 50.0801 VBLs a second on the machine's clock (the AY log's interrupt times) |
| Clock, NTSC (`f121+ntsc`, 60 s) | counted 17,030: NTSC; 3,595 VBLs, every one equal to the model; 2,097 tics (the model 2,097); 34.963 tics a second (±0.017 is one tic over the 60 s the measure spans), 59.9228 VBLs a second |
| A second entry (no VBL pending) | with the mouse card's button interrupt on beside the VBL's, 20 interrupts with no VBL pending among 170: the same log, the same VBL count and tics, the stop at the same VBL as the run without them |
| IRQ with music alone (`f121+phasor+window32`, the Doom profile), `--irq-bounds 00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF` | 13 songs × 20 s, 1,001 interrupts each: the bounds held, and the AY log **equal to S2's own build's** (`build/sound65`, `snd_vbl`) group for group, write for write, and the chips at the end; an NTSC song (10 s) too |
| The interrupt's stack | 16 B (≤ 24): the CPU's 3, A, X, Y, `jsr pl_vbody`, `jsr snd_tick` and its own; `--lowest-s-in` of `FXCODE` and `SNDCODE` against the idle loop's (whose lowest S is an interrupt's entry) |
| The worst length | **1,546.9 µs** (`D_INTRO`; S2's own 1,543.8 µs), about 206,000 fabric clocks; 1,558.5 µs with window 512. It is the music's burst under the slot-4 slowdown; `pl_vbl` adds 1-3 µs an interrupt. Per song: worst 254-1,547 µs, median 42-120 µs, 0.31-0.74 % of the machine's time |
| The bridge (`--speed 1`, no cost model, bounds plus `C008-C009`) | 100 interrupts in 100 VBLs, all through the bridge to `pl_vbody`: the VBL count 100, the tics the model's; the loop's count in the aux zero page, nothing in main's; the main stack's 8 markers above the loop's S intact; the aux zero page's `$D8-$FF` untouched; the aux card unchanged (only the bridge's 30 B and its vectors in it, the same bytes as the main card's `$FF00`); a BRK with `ALTZP` on ends at `pl_crash` with `ALTZP` off |
| `tests/test_sound_*` | unchanged (no file of S2 or S3 edited) and green: 7 modules, 152 tests |
| `wip_test_m11_s2lay` | still green (its phase scan reads the new sources) |
| Python 3.9.6 | `wip_test_m11_plclock` OK with `-W error::ResourceWarning` |

## 3. Planted bugs (each in a scratch copy) and the check that caught it

Each is built from a copy of `m11.mk`, `m11/s2lay.mk`, `m11/plclock.mk`
and the part's sources with one change, into its own directory
(`wip_test_m11_plclock.Planted`).

| Bug | Caught by | The failure |
| --- | --- | --- |
| The PAL fraction 45,742 (`TIC_FRAC_PAL`) | the model at every VBL | "VBL 1: tics 0, fraction 45742; the model 0, 45743" (the rate alone, 34.98 over 200 VBLs, would not see it) |
| The NTSC fraction for PAL | the model at every VBL and the rate | "VBL 1: tics 0, fraction 38229; the model 0, 45743"; 29.19 tics a second |
| A tic lost at the fraction's carry (`clc` before the high byte's `adc`: the low byte's carry dropped) | the model at every VBL | "VBL 2: tics 1, fraction 25694; the model 1, 25950" (a tic comes late from then on) |
| The VBL cause not checked (`beq @none` dropped: a second entry counts) | the second-entry runs | "the pressed run stopped 20.00 frames early" (each button interrupt counted as a VBL) |
| The handler reading main `$0300` (`lda $0300` in `pl_vbody`) | `--irq-bounds` | "halt at $F51A: irq-bounds: read $0300 in an interrupt, pc $F51A" |

## 4. Sizes against the budget

| Item | Size [M] | Budget |
| --- | ---: | ---: |
| `pl_vbl`, `pl_vbody`, `pl_crash`, `pl_time` (the card, `$F505-$F578`) | 116 B | 150 B |
| `pl_clkset`, `pl_detect`, `pl_wait` (boot-time, in the card too) | 128 B | (PLCLOCK-2) |
| The stand-ins `fx_step`, `fx_burst` | 1 B | test only |
| `FXCODE` in all, of `$F505-$F8FF` | 245 of 1,019 B | with `fxplay`'s 620 B and `VATT`'s 128 B: 993 B, 26 B left |
| The bridge (`$FF00-$FF1D`) | 30 B | `$FF00-$FFF9` (250 B) |
| The aux card's vectors | 6 B | `$FFFA-$FFFF` |
| The clock's state, card `$E403-$E412` | `CLK_STEP` 2, `CLK_FRAC` 2, `CLK_TICS` 4, `CLK_STD` 1, `CLK_TIME3` 1 (10 of 16 B) | 16 B |
| The VBL count, zero page | `vbl_count` 2 B, inside S2's 31 B at `$D8` | `$D8-$F6` |

## 5. Timing (SCREENS.md 6.4)

The part has no frame-side entry; its cost is the interrupt's.

| Run | Interrupt length [M] |
| --- | --- |
| Music idle (`snd_tick` with no song), `f121` | median 5.28 µs, worst 5.52 µs a VBL (0.03 % of the time) |
| Music idle, `f121+ntsc` | median 5.38 µs, worst 5.93 µs |
| Music idle, `fastpath` | 5.39 µs |
| Music alone, the Doom profile | median 42-120 µs, worst 1,546.9 µs; 0.31-0.74 % of the time; S2's `snd_vbl` 1-3 µs less an interrupt |

## 6. Requests (for the integrator; stand-ins marked `STANDIN`)

### PLCLOCK-1. `tools/native/s2layout.py` `CLOCK_FIELDS`, `docs/SCREENS.md` 2.2 and 4.4: the clock's bytes

**Evidence.** S2's test driver, `MUSIC.SYSTEM` and the timing test import
the VBL count as a zero-page word, `vbl_count` [R `src/sound/driver.s:38`,
`src/sound/music.s:48`, `src/sound/aytime.s:48`], and the checkpoint links
S2's `driver.o` unchanged with `pl_vbl`; S2's 31 zero-page bytes at `$D8`
already hold it [R `src/sound/irq.s:19-20`; `s2layout.ZP_MUSIC`]. So the
VBL count stays `vbl_count` (`pl_irq.s` exports it in `SNDZP`, in place
of `irq.s`), and `CLK_VBL`'s two card bytes are free. The clock needs the
fraction a VBL (2 B, read by every interrupt rather than branching on the
standard) and `pl_time`'s fourth byte (1 B: `I_GetTime` returns 32 bits
[R `src/native/ghook.s:17-19`: GA_0-3, the low word in A:X]).

**Stand-in.** In `pl_irq.s`: `CLK_STEP = CLK_VBL`, `CLK_TIME3 =
CLK_SPARE` (marked `STANDIN`).

**What.**

- `s2layout.py`: `CLOCK_FIELDS = [('CLK_STEP', 2), ('CLK_FRAC', 2),
  ('CLK_TICS', 4), ('CLK_STD', 1), ('CLK_TIME3', 1), ('CLK_SPARE', 6)]`,
  with the comment "the VBL count is S2's `vbl_count` in the IRQ's zero
  page (part plclock, request PLCLOCK-1); `CLK_STEP` the fraction a VBL
  (45,743 PAL, 38,229 NTSC), `CLK_STD` 0 PAL or `$80` NTSC (S2's
  `SONG_NTSC`), `CLK_TIME3` `pl_time`'s bits 24-31". Then remove the two
  `STANDIN` lines of `pl_irq.s`.
- SCREENS.md 2.2, row "State": "Card `$E403-$E412` (`MEMORY_MAP.md` 4.2's
  IRQ state): VBL count (2), fraction (2), tics (4), the standard (1), 7
  spare" becomes "Card `$E403-$E412` (`MEMORY_MAP.md` 4.2's IRQ state):
  the fraction a VBL `CLK_STEP` (2), the fraction (2), the tics (4), the
  standard (1: 0 PAL, `$80` NTSC, S2's `SONG_NTSC`), `pl_time`'s fourth
  byte (1), 6 spare; the VBL count is S2's `vbl_count` in the IRQ's zero
  page (part `plclock`, request PLCLOCK-1)".
- SCREENS.md 2.2, row "`I_GetTime`": add "A, X, Y bits 0-23, bits 24-31
  in `CLK_TIME3`, P's I bit kept".
- SCREENS.md 4.4, row `$E403-$E412`: "the clock: VBL count, fraction,
  tics, PAL or NTSC" becomes "the clock: the fraction a VBL, the
  fraction, the tics, PAL or NTSC, `pl_time`'s fourth byte (the VBL count
  is `vbl_count`, zero page)".
- `docs/m11-parts/design.md` R2 item 1 (for `MEMORY_MAP.md` 4.2): add "Row
  `$E403-$E412`: 'IRQ state: VBL count, tic accumulator, tic counter'
  becomes 'IRQ state (milestone 11, `pl_irq.s`): the fraction a VBL, the
  fraction, the tic counter, PAL or NTSC, `pl_time`'s fourth byte (10 of
  16 B); the VBL count is `vbl_count` in the player's zero page'"; and in
  the same item, "`pl_vbl` and the clock (about 100 B)" becomes "`pl_vbl`,
  the clock and `pl_time` (116 B), `pl_clkset` and `pl_detect` (128 B,
  boot-time; PLCLOCK-2)"; row `$FF00-$FFF9`: "IRQ bridge landing (pair
  build)" becomes "the aux card's IRQ bridge, the same 30 B in both cards
  (`pl_bridge.s`; pair build only)".

**Effect on others.** None on milestone 10. `fxplay` and `plboot` read
the names from `s2.inc`.

### PLCLOCK-2 (optional). A boot segment for `pl_clkset` and `pl_detect`

**Evidence.** They run once, at boot, but sit in the card's `FXCODE`
(128 B): with `fxplay`'s 620 B and `VATT`'s 128 B the room keeps 26 B
(section 4).

**What.** If `fxplay` needs the room: `s2layout.py --cfg` maps a segment
`PLBOOT` (optional) to the boot's main memory in `plboot`'s image and to
the room in the test images, and `pl_irq.s` puts `pl_clkset`, `pl_detect`
and `pl_wait` in it. Not done here: no image of this wave has a boot.

### PLCLOCK-3. Notes for `plboot` (no change asked)

- The boot's order: the card image installed, the vector `pl_vbl`, the
  mouse card's VBL on (mode `$09`, as `MUSIC.SYSTEM` and the kernel [R
  `demos/doom/src/kernel/input.s:63`]; the test driver `s2_drv` writes
  `$08`, which a2vm takes too), `CLI`, then `pl_detect` (it waits on
  `vbl_count`, so it needs the interrupt running, as `MUSIC.SYSTEM`'s
  `detect_video`), then `snd_start` with `CLK_STD` or'ed into the song's
  flags (`$80` is `SONG_NTSC`).
- A build links `pl_irq.o` or S2's `irq.o`, never both (both define
  `vbl_count` and `VECTORS`).

## 7. Decisions where the design left a choice

- **The VBL count in zero page** (PLCLOCK-1): S2's interface kept.
- **`pl_vbody` as a subroutine**: one body for `pl_vbl` and the bridge,
  at 12 cycles and 2 stack bytes an interrupt.
- **The clock's step in the card** (`CLK_STEP`) instead of a branch on
  the standard: one absolute operand an interrupt; `pl_clkset` sets it.
- **`pl_clkset` restarts the VBL count**, so the clock is a function of
  `vbl_count` alone: tics = `vbl_count` × F >> 16 until the count wraps
  (65,536 VBLs, 21.8 minutes on PAL; the tics go on, 32 bits).
- **The crash stop shows nothing**: `pl_crash` masks interrupts, stops
  the VBL and loops, writing nothing outside the IRQ contract; the stop's
  code is what the stopping code wrote to `PL_STATUS` (as `ldriver.s` and
  `s2_drv.s`). `kstart.s` shows "DOOM CRASH $cc" on the text screen
  [R `kstart.s:215-246`]; that needs stores outside the contract and is
  the second half's choice.
- **The second entry is tested with a real interrupt**: a2vm does not
  model the TURBO echo `kstart.s` describes [R `kstart.s:267-270`], so
  the test turns on the mouse card's button interrupt beside the VBL's
  and presses the button 10 times (20 interrupts with no VBL pending).
  Those runs leave out the idle skip, or a press due during a skip would
  come with the VBL's interrupt.
- **The music's comparison** is against S2's own build run the same way
  (`run65.run`), not only against `player.py`: the two a2vm AY logs equal
  group for group (before the first interrupt, each burst, the main loop
  after each), and the chips at the end.

## 8. Open problems

1. `fx_step` and `fx_burst` are the stand-ins: the IRQ row "music and three
   effects", `FX_HOLD` and `--phasor-mb-only` are `fxplay`'s (wave 3).
2. The worst interrupt with music alone, 1.55 ms in the Doom profile, is
   S2's burst under the slot-4 slowdown, not `pl_vbl`'s; it delays the
   main loop, not the clock.
3. The bridge is tested on a2vm at `--speed 1` without the cost model; no
   build links it before milestone 13. It relies on the program switching
   `ALTZP` on with its main S and keeping S at or below it (the comment
   of `pl_bridge.s`).
4. `pl_detect` reads timer 1's low byte, then its high byte (as
   `MUSIC.SYSTEM`); a borrow between the reads errs by at most 256 cycles
   against a margin of 1,625.
5. `vbl_count`'s address follows the link order inside S2's 31 B (`$F5`
   after the player's 29 B, or `$D8` before them); both are inside
   `ZP_MUSIC`.
6. PLCLOCK-1's stand-in names stay until the integrator applies it.

## 9. The wave 2 integration (2026-10-01)

What the integrator did with each request (`docs/SCREENS.md` 8.6, "Wave
2 as integrated"):

| Request | Outcome |
| --- | --- |
| PLCLOCK-1 | Applied as written: `s2layout.py` `CLOCK_FIELDS` (`CLK_STEP`, `CLK_FRAC`, `CLK_TICS`, `CLK_STD`, `CLK_TIME3`, `CLK_SPARE` 6), SCREENS.md 2.2 and 4.4 (also 4.4's `$F505-$F8FF` row with the measured 116 B and 128 B), `design.md` R2 item 1; the two `STANDIN` lines of `pl_irq.s` removed (the addresses are the stand-ins', `$E403` and `$E40C`); `plclock.py` places the step by `S.CLOCK['CLK_STEP']` |
| PLCLOCK-2 | Not applied (optional, no boot yet); open for `fxplay` if `FXCODE`'s 26 B are not enough |
| PLCLOCK-3 | Nothing to apply; for `plboot` |

After it: `plclock.py --checkpoint --jobs 2` 0 problems (the figures of
section 2 unchanged), `wip_test_m11_plclock` 19 tests OK (also on Python
3.9.6). The other wave 2 change that touches this part: `s2_drv.s` masks
the interrupt for one instruction over its snapshot point (S2DRAW-3); the
clock's runs under `s2_drv` are unchanged by it.

## The final integration of the first half (2026-10-02)

`pl_fxstub.s` is gone: `plct`, `music/` and `bridge/` link part fxplay's `fx-card.o` before `pl_irq.o` (FXPLAY-3's optional item, PLBOOT-4's order); `pl_ct.s` and `pl_bt.s` call `fx_init` with the native answer and `plclock.py`'s music run starts with the effects on and none playing. The checkpoint passes again: PAL 34.9544, NTSC 34.9633 tics a second; the 13 songs' AY logs equal S2's, the worst interrupt 1,547.9 µs (3-4 µs above S2's in each song: the effect steps' early returns); `sizes()` reports `fx.s`'s card part (739 B) in place of the stand-ins; the planted bugs caught. The test is `tests/test_m11_plclock.py`. (`docs/SCREENS.md` 8.13.)
