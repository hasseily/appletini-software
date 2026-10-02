# Milestone 11, part `s2lay`: the layouts, the makefile, the test driver, the runner, the checker

Part `s2lay` of wave 1 ([`docs/SCREENS.md`](../SCREENS.md) 7.3), the
shared infrastructure of every later part. 2026-10-01. Labels as in
`NATIVE.md`: [M] measured, [R file:line] read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `tools/native/s2layout.py` | Every place of SCREENS.md 4: the seven W images (rooms, runtime ranges, state blocks, the shared objects they link), the size table and its check against an image's ld65 map (`--check-map`), the packing of the stored pages into the code banks (`pack`, `image_banks`), main's input block and `PL_STATUS` with the stop codes `S2S_*` and `PL_*`, the zero page, the card blocks with their per-build addresses (`BUILDS`: `test`, `release`, `m11`, `fxch8`: `S2T_BASE`, `SC_BASE`, `NUM_CHANNELS`), the voice, channel and mailbox formats, the banks of 4.5 and the layout of `S2STATE`, the cost phases 30 and 31, the screen regions and the frame kinds, the field map of 6.2 for every screen of 1.6 (`field_map`, `state_places`, `palst_places`), `check()`; the generated `s2.inc` (`--inc --build B`), an image's ld65 map (`--cfg IMAGE`), `--report` |
| `src/native/m11.mk` | The shared rules: the includes in `build/native/m11/shared/gen` (written atomically and only when they change), the macros `M11_COMMON DIR` (far layer, math, `auxlc`, the driver, `s2_drv-pl.o` with `-D PL_VBL`, any `DIR/%.o`) and `M11_IMAGE DIR,NAME,IMAGE,OBJECTS` (link with the generated map, then the size table; an image over its room fails); targets `part P=NAME`, `images`, `sizes`, `check`, `gen`, `clean-part P=NAME`; with `P` only `m11/s2lay.mk` and `m11/NAME.mk` are read, so another part's half-built fragment cannot break a build |
| `src/native/m11/s2lay.mk` | This part's builds: the test image `s2lt` |
| `src/native/s2_drv.s` | The test driver at card `$F900-$FEFF`: the IRQ vector (`pl_vbl` with `-D PL_VBL`, else a stub that acknowledges the mouse card's VBL and counts it in `s2d_vbls`, in the card, under the IRQ contract), the VBL on, each load (a bank and its page runs by `far_pload`, phase 0), each call (a routine with A, X, Y; phase 30 around it; the snapshot point `s2d_called` after it), the stop `S2S_DONE` at `PL_STATUS` then `BRK`; any `BRK` ends at `s2d_stop` through `s2d_brk`, which writes nothing outside the IRQ contract (a `BRK` inside a `RAMWRT` window stops cleanly; a `BRK` that wrote no code leaves `S2S_RUN`) |
| `src/native/s2_lt.s` | The test image in `P2DW`'s room: `s2t_nop`, `s2t_echo` (A, X, Y into `$BFFD-$BFFF`), `s2t_stop` (a routine's stop), `s2t_wait` (until the stub counted A VBLs) |
| `tools/native/s2run.py` | a2vm runs, built on `lrun.py` (imported: labels, segments, image bytes): the poisoned machines `$A5`/`$5A`, the persistent globals 0, the card, the image in its code bank, the descriptors; the write log (`Write` with the old and new values) and `stray` by owners (the driver's set, the phase loader's, each part's `Owner`); range snapshots after each call and at the stop, or the whole machine at the stop with `changed_outside`; `--cost PROFILE --cost-timed --cost-phase $0300` and `phase_ms`; the AY log (`ay_events`, `irq_lengths`), `--irq-bounds 00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF` by default, `--phasor-mb-only`; the stack depth by `--lowest-s-in` (`stack_depth`) |
| `tools/native/s2check.py` | `offsets(region)` (its own code, checked equal to `s2layout.Region.offsets`), `compare` (the region equal to `PD1`, every other byte its injected value or poison, X1-X3 counted by name, X2 black), `order` (the publish order of 1.3 and 1.5.8 on a frame's aux-0 stores, rule 10), `report` (the exclusions X1-X4 by name and count) |
| `tests/wip_test_m11_s2lay.py` | 25 tests: layouts, checker, planted bugs, the driver on a2vm |

Build output: `build/native/m11/s2lay/` (428 KB) and
`build/native/m11/shared/gen/` (`s2.inc`, `s2-release.inc`, `s2-m11.inc`,
`s2-fxch8.inc`, `rlayout.inc`; 48 KB). Every run's directory is a
`tempfile` directory under `build/` that the caller deletes.

**For the later parts.** A fragment `src/native/m11/<part>.mk` sets its
directory, `$(eval $(call M11_COMMON,$(DIR)))`, then one
`$(eval $(call M11_IMAGE,$(DIR),NAME,IMAGE,$(OBJS)))` an image, and a
target `<part>_all` (or one named the part: `fxconv`'s); its sources put
code and data in the segments `S2CODE`, `S2RODATA`, `S2DATA` (the room),
S2's segments where they link the player, `FXCODE` (`$F505-$F8FF`) for
the effects' card code. In Python: `SR.make(part)`,
`SR.load_build(dir, name, IMAGE)`, `SR.run(build, [SR.Call('label', a,
x, y), ...], fill, work, loads=..., extra_records=..., snap_ranges=...,
whole=..., profile=..., ay_log=...)`, then `stray(run.writes(),
[driver_owner, loader_owner, your Owner])`, `run.calls()`, `run.status()`,
`phase_ms`. The places are `s2layout`'s names in `s2.inc`.

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
python3 tools/native/s2layout.py --check
make -C src/native -f m11.mk part P=s2lay      # no warning
make -C src/native -f m11.mk sizes
python3 -m unittest discover -s tests -p wip_test_m11_s2lay.py
python3 tools/native/s2run.py --profile f121   # (and fastpath)
```

(`python3 tools/testpar.py tests/wip_test_m11_s2lay.py`, the command of
SCREENS.md 7.1, refuses the name: request S2LAY-4.)

Results [M, 2026-10-01]: 25 tests, all pass (2.4 s with the build up to
date).

| Item | Result |
| --- | --- |
| `check()` against `rlayout.py`, `llayout.py`, `glayout.py` (imported) | passes, after request S2LAY-3: `GS_ARG` is a word (`$03B1-$03B2`), so the input block starts at `$03B3` |
| Phase constants | `s2layout.PHASE_2D` 30, `PHASE_PLATFORM` 31 (and `PHASES`); `rlayout`, `llayout`, `glayout` have no named phase constant. The 65C02 sources (all of `src/`, 66 stores to `PHASE` read, none unread) write 0-18; `s2_drv.s` writes 0 and 30; nothing writes 31 |
| Empty call list, `$A5` and `$5A` | stops at `s2d_stop` with `S2S_DONE`; 1,833 logged writes, 0 outside the driver's and the phase loader's sets; the whole machine at the stop: 0 bytes changed outside them (the stack page aside); the image in W equal to its file |
| Calls | three calls' snapshots show the registers each passed; a routine's stop (`$7E`) reaches `PL_STATUS`; the image's 7 writes are strays without its owner's set and none with it |
| The VBL stub | `s2t_wait 5` under `--irq-bounds 00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF`: 5 interrupts, the bounds held, every `irq` with its `rti` in the AY log; stack 5 B below the driver's S with an interrupt's entry |
| `s2check` | the hand-made case (status bar region, injected rows 0-99, poison elsewhere, both fills) equal; one region byte wrong and one byte outside each caught; X1 (viewtop `$FFFF`: 26,880 B; 9: 25,280 B), X2 (black) counted by name |
| Two write logs | upstream's order: no problem; one band store before the last black palette store: "store 300 ($8900, a band store of $00) before the last black palette store"; a picture colour before the last band, an SCB after the first band, a black step short of a byte, a non-zero store to `$9DFC` each fail |
| Size check | for each of the six packed images a synthetic map filling its room passes and one byte over fails ("... is over its room ... by 1 B") |

## 3. Planted bugs (each in a scratch copy) and the check that caught it

| Bug | Caught by | The failure |
| --- | --- | --- |
| Two regions overlapping (`stbar` from row 167) | `check()`'s frame kinds | "level, strip on: the regions view and stbar overlap at aux 0 $8860" |
| A stored page run of two images overlapping in one bank (`pack` ignoring the overlap) | `check()`'s independent check of the packing's result | "bank 107: the stored pages of AMAPW and FINW overlap" |
| `s2check`'s region off by one row (`range(r0, r1)`) | the hand-made case | 54 bytes outside the region changed, first "$9C60 outside the region: native $FB, it held $A5" (row 199) |
| The driver writing one byte of aux 0 (`RAMWRT` on, `sta $2000`, off, before the VBL) | the empty run's write log and the whole-machine snapshot | `stray`: "pc $F9.. (driver) wrote aux 0 $2000" (and the two switch writes); `changed_outside`: 1 byte, aux 0 `$2000` |
| The input block starting at `$03B0` | `check()` with `glayout` imported | "the input block $03B0-$03EA overlaps glayout the stop codes ($03B0-$03B2)" |
| A phase constant 32 (`PHASE_2D = 32`) | `check()`'s phases | "the phase constant s2layout.PHASE_2D is 32, outside 0-31", the same for `PHASES[32]`, and "src/native/s2_drv.s:93 writes the phase 32 (counted in 31)" |
| A write log with one band store before the last black palette store passing (the black step skipping what is not a black palette store) | the test's judgement of the hand-made bad log | the planted judge returns no problem, the real one "store 300 ... before the last black palette store" |

## 4. Sizes against the budget

| Item | Size | Budget |
| --- | ---: | ---: |
| `s2_drv.s` code (`DRIVER`, `$F900-$F99F`) [M] | 160 B | 600 B |
| its descriptors (`DESC`, `$FA00-$FBAE`: the runs page, 4 loads, 32 calls) [M] | 431 B | in `$F900-$FEFF` (1,536 B) |
| `s2lt` in `P2DW`'s room [M] | 24 B | 7,424 B |
| The tic-side block (`S2T_BASE`) | 59 B | 61 B |
| The channels and mailboxes (3 channels; `FXCH8` 8) | 48 B; 128 B | 64 B; 128 B |
| `S2STATE` as allocated | `$0200-$611F` (24,352 B) | 48,640 B |

Timing (6.4): this part has no frame-side entry. The driver's load of
`s2lt`'s 7 pages (1,792 B, `MATHW` and `AUXW` and the image) in phase 0:
0.460 ms on `f121`, 0.426 ms on `fastpath` [M: `s2run.py --profile`],
0.26 and 0.24 µs a byte, as `NATIVE.md` 4.3's 0.246 [M].

## 5. Requests (for the integrator; the stand-ins are marked `STANDIN` in `s2layout.py`)

### S2LAY-1. `docs/SCREENS.md` 4.1 (row *Packing*) and 4.5: the code banks

**Evidence.** `far_pload` copies a bank's pages to the same addresses of
main [R `src/native/far.s:330-343`], and every packed image's stored
pages start at `$6600` (4.1's rooms). So two images can never share a
bank: the design's banks 107, 108 and 94 hold three of the six images
(`s2layout.pack(budget_extents(), DESIGN_CODE_BANKS)` fails: "WIW
($6600-$7A4F) has no bank"; `wip_test_m11_s2lay` asserts it).

**Stand-in.** `STANDIN_CODE_BANKS = (95, 96, 97)` (GAME.md 1.10's spare):
P2DW 107, MENUW 108, AMAPW 94, WIW 95, FINW 96, PALW 97.

**What** (either, the owner's or the integrator's choice):

- (a) keep the rooms; in 4.5 add the rows "95, 96, 97 | `S2CODE3`-`S2CODE5`
  | `WIW`'s, `FINW`'s, `PALW`'s page runs (each image's pages start at
  `$6600`, so one image a bank)" and in 4.1's *Packing* row replace
  "packs the stored page runs into banks 107, 108 and, if they do not
  fit, 94 (`MATHW` once a bank, runs disjoint within a bank)" with "puts
  each image's stored page runs in a bank of its own among 107, 108, 94,
  95, 96, 97 (`far_pload` copies to the same addresses and every image is
  stored from `$6600`)"; risk 3's next bank for the store becomes 125;
- (b) no bank more: link `WIW`, `FINW` and `PALW` at the top of W (code
  `$A600-$BFFF`, runtime `$6600-$A5FF`), so that each shares a bank with
  one bottom image (`P2DW` and `WIW` in 107: `$6600-$82FF` and
  `$A600-$BFFF`; `AMAPW` and `PALW` in 94; `MENUW`'s room would have to
  end at `$A600` for `FINW` in 108, or `FINW` takes 95). `s2layout.py`
  then holds those rooms and runtime ranges; the parts take them from
  `s2.inc`.

### S2LAY-2. `docs/SCREENS.md` 4.6: how a state block is loaded and saved

**Evidence.** `P2DW`'s, `WIW`'s and `FINW`'s state blocks are all W
`$BC00-$BFFF` and `MENUW`'s `$BF00-$BFFF` (4.1), so `far_pload` (same
addresses) cannot load them from one bank `S2STATE`; `far_put` copies at
most 256 bytes [R `far.s:63-79`], not 1 KB "with one `far_put`".

**What.** Replace "loaded with the image (a second `far_pload`, from
`S2STATE`) and written back with one `far_put` at the image's end (0.25
ms [A])" with "fetched with `far_get` and written back with `far_put`,
256 bytes a call, between its W block and its place in `S2STATE`
(`s2layout`'s `SS_*`: the palette state `SS_PALST`, 768 B, shared by
every image that publishes, then each image's own part; 0.25 ms a KB
[A])". `s2layout.py` holds that layout: P2DW, WIW, FINW keep `PALST` at
W `$BC00-$BEFF` and their own 256 B at `$BF00-$BFFF`; MENUW its own at
`$BF00`; AMAPW its 1 KB at `$AC00-$AFFF` (inside 4.1's "marks and state",
the marks `$A840-$ABFF`).

### S2LAY-3. The input block: `docs/SCREENS.md` 2.4 and 4.2, `docs/m11-parts/design.md` R3 (for `MEMORY_MAP.md` 3.1)

**Evidence.** `GS_ARG` is a word: `glayout.regions()` gives the stop
codes `$03B0-$03B2` [R `tools/native/glayout.py:778`], `gcall.s` stores
`GS_ARG` and `GS_ARG+1` [R `src/native/gcall.s:136-139`]. The design's
block `$03B2-$03ED` meets `GS_ARG+1`.

**What.** Everywhere the block is named, `$03B2-$03ED` (60 B) becomes
`$03B3-$03ED` (59 B: 58 used, 1 spare), and "`$03B0-$03B1` are milestone
10's `GS_STATUS` and `GS_ARG`" becomes "`$03B0-$03B2` are milestone 10's
`GS_STATUS` (a byte) and `GS_ARG` (a word)". 4.2's table, as built:
`PL_QUEUE` `$03B3-$03DF` (15 × 3 B), `PL_QHEAD` `$03E0`, `PL_QTAIL`
`$03E1`, `PL_HELD` `$03E2`, `PL_BUTTONS` `$03E3`, `PL_MDX` `$03E4-$03E5`,
`PL_MSEQ` `$03E6`, `PL_MX` `$03E7`, `PL_REPKEY` `$03E8`, `PL_REPCH`
`$03E9`, `PL_REPTIC` `$03EA-$03EB`, `PL_DEFER` `$03EC`, spare `$03ED`.

### S2LAY-4. `tools/testpar.py` (and `tests/README.md`): run a wip test by name

**Evidence.** SCREENS.md 7.1 runs each part's test with `python3
tools/testpar.py tests/wip_test_m11_<part>.py`; `discover()` accepts only
names among `tests/test*.py` and exits "testpar: no such test module:
wip_test_m11_s2lay" [R `tools/testpar.py:638-649`].

**What.** In `discover`, after `found = ...`:

```python
    if not names:
        return found
    wanted = [Path(n).name for n in names]     # tests/test_x.py too
    wanted = [n[:-3] if n.endswith('.py') else n for n in wanted]
    # a work-in-progress module (tests/wip_test_*.py) runs when named
    found += sorted(n for n in wanted if n.startswith('wip_test_') and
                    (tests / (n + '.py')).is_file() and n not in found)
```

(the module is then loaded with the pattern `<module>.py`, as any).
Meanwhile: `python3 -m unittest discover -s tests -p
wip_test_m11_<part>.py`.

### S2LAY-5. `docs/MEMORY_MAP.md` section 18 (design.md R2 item 4), as built

With S2LAY-1 to -3 applied, the section's tables are `python3
tools/native/s2layout.py --report` and `s2.inc`; the rows that differ
from SCREENS.md 4: the input block (`$03B3`), the code banks (S2LAY-1),
`S2STATE`'s layout (S2LAY-2), the card's tic-side block (59 of 61 B:
`ST_*` 24 B, `HU_*` 8 B with a spare, `F_*` 6 B, `S2_MAIL`, `FM_X/Y` 8 B,
`LS_X/Y/ANGLE` 12 B), the channel record (12 B: `CH_SFX`, `CH_PICKUP`,
`CH_KIND`, `CH_HANDLE` 2, `CH_X` 3, `CH_Y` 3, spare 1; mailbox `MX_FLAGS`,
`MX_SOUND`, `MX_VOL`, `MX_SEP`).

## 6. Decisions where the design left a choice

- **Phase 0 is the driver and the loads**; a2vm's phase is `PHASE / 2`
  [R `tools/a2vm/cost.c:888-889`, `:941`], so `s2.inc` gives the values
  `PHV_2D` 60, `PHV_PLATFORM` 62, `PHV_DRIVER` 0. The platform's code
  marks 31 itself (restoring 30 when it returns).
- **The phase check reads the sources** too: every `stz PHASE`, `lda #E`
  then `sta PHASE` (or `jsr mark` where the file's `mark:` stores
  `PHASE`, `rwall.s`'s), and `MARK n` macros; a store it cannot read
  fails the check, naming the line. 31 only from `src/native/pl_*.s`,
  `fx_*.s` and `src/sound/fx*.s`.
- **Frame kinds** (`s2layout.FRAME_KINDS`): the regions each kind of
  frame shows must be disjoint but for named overlays (the map's title
  over the map or the view, the message over the map), as upstream draws
  them; the title's rows are `HU_TITLEY` 160-166 [R
  `hu_stuff65.s:20-22`].
- **The publish order** is judged on one frame's stores; the black step
  is exactly the 512 palette bytes, each once, all 0, first.
- **The field map** places every 1.6 field: the game's by
  `llayout.G`, the frame block, the render inputs, `player.F` (through
  `llayout.player_layout`, `s2cap`'s); the card's by `S2T_*`; the 2D
  state's in the image's block or `S2STATE` with encodings `word`,
  `byte`, `sxbyte`, `long`, `bytes` (a widget's value pointer `dropped`).
  Its upstream names are checked against `build/linkmap.json` (0
  problems). The menu's settings (`_g_alwaysRun`, `detailLevel`, the
  mouse's) are in `SS_SETTINGS`; the second half's `G_BuildTiccmd` reads
  `_g_alwaysRun` there.

## 7. Open problems

1. **`MENUW` has no room for the palette state** (`PALST`, 768 B: `scb`,
   `palette`, the flags of 1.3): its runtime map gives the state 256 B
   at `$BF00`, but it links `s2_pal` and builds `UI_GRAY` from the
   palettes on the screen. For `s2pal` and `s2menu1`: `PALST` read from
   `S2STATE` into the band while the menu opens, or `MENUW`'s fetch
   buffer moved.
2. The channel record's `CH_X`, `CH_Y` are 3 bytes (bits 8-31 of the
   fixed value) [A] to keep 12 B: `fxchan` decides.
3. A build linking `pl_vbl` ends a `BRK` at `pl_vbl`'s crash stop: `s2run`
   stops at a label `pl_crash` when the build has one (part `plclock`
   names it so, or routes the test build's `BRK` to `s2d_brk`).
4. Seen while reading the phases, not this part's: milestone 8's bucket
   pass marks phase 18 (`rdriver.s:163`, `bdriver.s:24`), which GAME.md
   5.4 gives to milestone 10's tic phase entry; milestone 10's profile
   build and a whole-frame profile would count both in 18.
5. S2LAY-1, -2, -3 are stand-ins until the integrator applies or
   changes them; the tests assert the design's packing failure so the
   finding stays visible.

## 8. The wave 1 integration (2026-10-01)

What the integrator did with each request (`docs/SCREENS.md` 8.5, "Wave
1 as integrated"):

| Request | Outcome |
| --- | --- |
| S2LAY-1 | Applied, option (a): banks 95, 96, 97 are `S2CODE3`-`S2CODE5` (`WIW`, `FINW`, `PALW`), one image a bank; SCREENS.md 4.1 *Packing*, 4.5 and risk 3 (the store's next bank is 125) changed. `s2layout.py`: `STANDIN_CODE_BANKS` is now `S2CODE3_5`, `DESIGN_CODE_BANKS` `FIRST_CODE_BANKS` (the test still shows the first design's three banks cannot hold the six). Option (b) was not taken: it changes three rooms and their runtime ranges, and `FINW` would need a bank of its own anyway |
| S2LAY-2 | Applied: SCREENS.md 4.6 says `far_get`/`far_put`, 256 bytes a call, between the W block and `S2STATE`'s `SS_*` |
| S2LAY-3 | Applied: SCREENS.md 2.4, 4.2 (the table as built), 5 (R3), 7.3 (`s2lay`, `plinput`) and `design.md` R3 say `$03B3-$03ED`, `GS_ARG` a word. `MEMORY_MAP.md` 3.1 is left to the final integrator (SCREENS.md 8.4) |
| S2LAY-4 | Applied with R-FX3: `tools/testpar.py` runs a named `tests/wip_test_*.py`; `test_testpar.py` checks it (not discovered, runs by name); `tests/README.md` says so |
| S2LAY-5 | Recorded in `design.md` R2 item 4 for the final integrator (SCREENS.md 8.4: `MEMORY_MAP.md` is milestone 10's or the final integrator's) |

The `STANDIN` markers are gone from `s2layout.py`; section 7's open
problems 1-4 stay open (1 for `s2pal`/`s2menu1`, 2 for `fxchan`, 3 for
`plclock`, 4 for milestone 10's integrator).
