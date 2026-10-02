# Milestone 11, part `s2ovl`: the automap's overlay records and `OVLW`

Part `s2ovl` of wave 7 ([`docs/SCREENS.md`](../SCREENS.md) 7.3), written
from upstream's `src/iigs/am_map65.s`: `AM_Drawer`'s overlay path,
`titleBand`, `drawLines`, `plot`'s overlay case `ovl` (`recOvl` of
`r_list65.s` inline) with `lists.inc`'s `FSCUTE`, `rowColors`, and the
rotation's fast path (`fastSetup`, `sq16`, `w16`, `fastLine`, `fpoint`,
`smul`) [R `am_map65.s:1033-1058`, `:1179-1219`, `:1337-1352`,
`:1461-1509`, `:1893-2352`, `:2843-2861`; `lists.inc:65-106`], and
display's overlay frame [R `d_main65.s:438-503`]. 2026-10-02. Follows
SCREENS.md 0.1 F9, 1.5.4, 4.1, 4.5; `design.md` R7. Labels as in
`NATIVE.md`: [M] measured, [R file:line] read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `src/native/s2_ovl.s` | The image `OVLW`'s own code (1,214 B with its 3-byte entry): `am_ovl` (A = the frame's tics: `AM_Ticker` once a tic, then `AM_Drawer`'s overlay, then OVLW's `nm_bkload`), `titleband`, `nibcache` and `am_rowcol` (`rowColors`), `am_seg` and `am_plot` (a line drawn at once; a pixel a `K_OVL` record through `mrec_room`, then `FSCUTE` on `FSTOP`/`FSBOT`), the fast path `am_fastsetup`, `am_fastline` (`fastSetup`, `fastLine`, `fpoint`, `smul`, `sq16`, `w16`) |
| `src/native/s2_ovd.s` | The test driver (not the game's): linked after milestone 8's `rdriver.s` in `render.cfg`'s `$E000` part; `ovd_frame` is `drv_fframe`'s whole frame with the overlay's step (below); `ovd_ltime` times `OVLW`'s load alone |
| `src/native/m11/s2ovl.mk` | `make -C src/native -f m11.mk part P=s2ovl`: milestone 8's objects of `ftest` and `fprof` (by `render.mk` itself, `OUT` in this part's directory), `gen/s2amap.inc` (part s2amap's generator), `gen/s2_amline-ovl.s` (request S2OVL-1's stand-in), the frame images `ovf` and `ovfp` (`render.cfg`), the image `OVLW` (`ovlw`, `ovlwp`: their own link, `ovlw.cfg` from the frame image's labels) and its size table `ovlw.sizes` (`s2layout.py --check-map OVLW`) |
| `tools/native/s2ovl.py` | The capture (`--capture`), the stand-ins (`--amline`; rcanon's `K_OVL`, in its process), `OVLW`'s link map (`--ovlw-cfg`), the checks (`--check`), the planted bugs (`--planted`), the timing (`--timing`), the sizes and the images' static checks (`--sizes`), `--all` (`report.json`) |
| `tests/wip_test_m11_s2ovl.py` | 12 tests (2.1) |

Build output: `build/native/m11/s2ovl/` (about 25 MB: milestone 8's
objects in `render/`, the images, `gen/`, `frames/` the capture (29
frames, 12 MB), `levels/` the level's conversion, `amcap/` part s2amap's
call capture made here, `report.json`). Every run's directory and every
planted bug's scratch copy is a `tempfile` directory there, deleted after
it.

### 1.1 How a frame runs

The test driver's `ovd_frame` is milestone 8's frame (`rdriver.s`'s
`drv_fframe`, RENDER-MASKED.md 3.2) with SCREENS.md 1.5.4's step: the
front end's window and `nr_frame`, the masked window and `nm_masked` (its
last batch staged); then, when the frame block's `AUTOMAP` has
`AM_ACTIVE | AM_OVERLAY`: `OVLW`'s room poisoned (the run's fill: `OVLW`
may not read what `MASKW` left in it), `far_pload` of `OVLW`'s page runs
from bank 93, `jsr OVLW_LO` with A = the frame's tics (the image's first
bytes are `jmp am_ovl`); `am_ovl` ends with `OVLW`'s `nm_bkload`. A frame
without the overlay runs `MASKW`'s `nm_bkload`. Then `nb_frame` (the
bucket pass and the replay). The cost phases: 1, 13, then 30 for `OVLW`'s
load and `am_ovl` (with its `nm_bkload`'s copy), 18 the bucket pass, 12
the replay.

`am_ovl`:

1. The state block (`SS_AMAPW`, `AMAPW`'s 110 bytes) into `AMST`
   (`$9B00`); `S2_MAIL`'s `MAIL_AMSTOP` (R6) and `MAIL_AMVIEW` (S2AMAP-3)
   as `AMAPW`'s `am_mail`; the player's `RTHING` (`am_getmo`).
2. `AM_Ticker` once a tic (`s2_amline`'s `am_ticker`, the player's last
   position: SCREENS.md 1.5.4's "at frame time", as `AMAPW`).
3. When the overlay is on: `AM_MODE` 1; the lines' rows `AWTOP`
   (10 when the HUD's `message_on`, else 0) .. 159; `titleBand`: when
   `am_band` is 0, `am_band` 1, rows 160-167 black on the screen (one
   `RAMWRT` window, 1,280 CPU stores) and `S2_MAIL`'s `MAIL_AMTITLE` for
   `P2DW`'s `hu_drawer` (R7 item 7's bit 2); the rows' colours
   (`nibcache`: display's `I_ViewPalette(0)` applied when `viewpal` was
   another, then `SS_PALST`'s `scb`; each palette's ten colours from
   `S2NIB`); `am_walls` and `am_players` (`drawLines`: `s2_amline`, with
   the fast path's hook); `am_valid` 0 (display's, after `R_DrawLists`
   [R `d_main65.s:503`]).
4. `AUTOMAP` from `automapmode`; the state block back; `mrec_flush` (the
   overlay's last batch); `jmp nm_bkload`.

A pixel (`am_plot`, rows `AWTOP` .. 159 only) is upstream's `ovl`: a
`K_OVL` record of 5 staged bytes (the kind, the column `x / 2`, the row,
the nibble to keep: `$0F` for an even `x`, `$F0` for an odd one, the
colour's nibble `NIBH` or `NIBL`), through `mrec_room` (the page model of
upstream's lists: `UPOFS`, `XPUSED`, a modelled flush), `sty MRB`; then
`FSCUTE` with the end `row + 1` and the first `row` on the column's
`FSBOT`, `FSTOP`.

**The fast path.** Upstream's `drawWalls` turns each line's ends with
four 16 x 16 products whenever `|s cos|` and `|s sin|` stay below 0.25
(`fastSetup`, `RF_MC` not `$FFFF`) and an end's distance from the origin
fits int16; its rounding is not the 32-bit path's (`s2_amline`'s
`slowline`): the planted bug 5 (3) shows every overlay frame of the script
differs without it. `am_fastsetup` runs after `wallrot` (request S2OVL-1:
`s2_amline.s` calls it, and `am_fastline` before `slowline` at each line,
when built with `-D AM_FASTLINE`); `smul` is `umul16` with the signs
(upstream's quarter squares are exact). Upstream's vertex cache
(`lvCheck`, `lvFrame`, `VS_TAB`) only skips the products of an end two
lines share, which give the same point: OVLW computes every end (open
problem 2).

### 1.2 The interface

- **`OVLW`**: bank 93 (`OVLW_BANK`), its stored bytes `$6800-$7FE2`
  (6,115 B: `jmp am_ovl`, `s2_ovl` 1,211, `s2_amline` 3,708, the masked
  copy of `rrec.s` 198, `bucket.s`'s `nm_bkload` 48, `BKFAR` 714 and
  `BKFAR2` 233 as data), loaded by `far_pload` of its page runs (`$68`,
  24 pages: 6,144 B); its run time `$9400-$9BFF` (the nibble pages 1 KB,
  `NCACHE`, `RBASE`, its variables, `s2_amline`'s `AMW` at `$9A00`, the
  state block `AMST` at `$9B00`). Entry: `jsr $6800` (`OVLW_LO`), A = the
  frame's tics. Request S2OVL-4 for the frame driver.
- **Reads**: the state block `SS_AMAPW` and the palette state `SS_PALST`
  (`scb`, `viewpal`) in `S2STATE`; `S2NIB` in `S2PAL`; the level's
  `LVG0`, `LVS`, `LVG1`, `LVMAP` (the sectors' heights), `LNMAP`,
  `LVCOUNT2`; the player's `G_PLAYER` (`mo`, `powers[pw_allmap]`) and his
  `RTHING` (x, y, the angle's both words); the card's `HU_ON` and
  `S2_MAIL`; the math (`MATHW`, `MATHLC`), the far layer.
- **Writes**: the records (`BATCH`, the staging and spill), `FSTOP`,
  `FSBOT`, `UPOFS` and the frame block's page model (`XPUSED`, `UPFLUSH`,
  `RECSEQ`, `STG_*`), `MRB`/`RSEQ`; `SS_AMAPW`; the frame block's
  `AUTOMAP`; `S2_MAIL`; aux 0 rows 160-167 (titleBand); `BKFAR`,
  `BKFAR2` into main (`nm_bkload`); W `$9400-$9BFF`; zero page `$80-$AE`,
  the math block, `FA_*`, `BK_P`/`BK_Q`; `PL_STATUS` on a stop
  (`PL_AMPALS`: more than 4 palettes in the lines' rows, impossible
  upstream). Checked on the write log of every run (2).
- **Zero page**: `s2_amline`'s `AMZ` `$80-$AE`: overlay 2 is dead after
  the masked phase, and the bucket pass sets its `$70-$AF` after `OVLW`
  (RENDER-MASKED.md 3.6).

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
df -h /System/Volumes/Data                      # 58 GB free
make -C src/native -f m11.mk part P=s2ovl       # no warning
python3 tools/native/s2ovl.py --capture         # 6 s, two ref816 runs
python3 tools/native/s2ovl.py --all --jobs 2    # report.json
python3 tools/testpar.py --jobs 2 tests/wip_test_m11_s2ovl.py
```

The truth is milestone 8's capture (`rendercap.py`'s run, its points P0
.. P5 and call logs) of `automap.script`, made into this part's directory
by `rendercap.run_one` with this part's choice of frames (the frames
whose `AM_Drawer` comes between `drawMasked` and `R_DrawLists`: display's
overlay call [R `d_main65.s:491-496`]; 4 usable frames without it on
each side): 21 overlay frames (all of the script's: part s2cap's cases
count 21 too) and 8 without, one level source, its conversion by
`levelconv.py` (`levels/`). The frame's start (the palette state before
display's `I_ViewPalette`) is part s2cap's `PD0` of the same frame
(`build/native/m11/cases/automap`, matched by cycles: the same
deterministic run; the automap's state at `PD0` and `P0` is checked
equal).

Results [M, 2026-10-02] (`report.json`, 2.2):

| Item | Result |
| --- | --- |
| Every frame, both fills (`$A5`, `$5A`) | 29 frames x 2: equal. Milestone 8's whole comparison (`frame8.compare`): the clip pass, the walk's outputs, the vissprites and the masked phase at the weapon, and at the staging's end every record of the frame by column in the order made (the view's, then the overlay's: 1,689 to 2,489 `K_OVL` records a frame, 2,782 to 3,871 records), the covered ranges and their records, the 8 span planes (`FSCUTE`), the page model (`UPOFS` against `COLW`, `XPNEXT`: 206 to 214, extra pages taken), the clips, the weapon skip, the clip log; the bucket pass's batches (2 or 3) against milestone 5's loader; the screen after the replay equal to P5 (aux 0 `$2000-$9FFF`, the model's count of SHR stores); the automap's state after `OVLW` equal to the reference's at `R_DrawLists` (and `am_valid` 0); `S2_MAIL` 0 |
| The variants (injected state with a reason) | `band0` (ovl-01, message_on 1; ovl-21, 0): `am_band` 0 in the injected state, as after a view frame without the overlay (no captured frame reaches `titleBand`: the full map leaves `am_band` 1): rows 160-167 black on the screen, `MAIL_AMTITLE`, 1,280 more SHR stores, everything else the frame's; `tics` (ovl-02 .. ovl-21): the automap's state as the overlay frame before left it at `R_DrawLists` (`am_valid` 0 as display leaves it), A = the 4 `AM_Ticker` calls in between (part s2amap's capture of the script, made into `amcap/`): the follow mode moved the window (`f_oldloc`, and `m_y`, `m_y2` in 11 of 20) and the frame is equal |
| Paths reached | the fast turn on every line of every overlay frame (`scale_mtof` 117,711: `|s cos|` below 0.25), the 32-bit path for the arrow; `I_ViewPalette(0)` (ovl-01: the frame starts with `viewpal` 11 after the full map); `AWTOP` 10 (ovl-01 .. 14, a message on) and 0 (ovl-15 .. 21); the computer map (every line, `pw_allmap`); extra pages and the page model's offsets in every overlay frame; no modelled flush (`UPFLUSH` 0) and no early flush upstream |
| Frames without the overlay | 8 x 2: equal (the same frame image: `OVLW` not loaded, `MASKW`'s `nm_bkload`) |
| No stray write | the write log by phase: milestone 8's front end, masked phase, bucket pass and replay sets; the poison (the driver); `OVLW`'s phase (215,761 to 234,934 writes a run), by the writing PC: `am_ovl` and `s2_amline` (zero page `$80-$AF`, the math block, `FA_*`, `MRB`, W `$9400-$9BFF`, `BATCH`, `FSTOP`-`FSBOT`, aux 0 rows 160-167, `S2_MAIL`, `AUTOMAP`, `PL_STATUS`), the masked copy of `rrec.s` (`FA_*`, overlay 1, the frame block, `UPOFS`, the staging and spill), `nm_bkload` (`rlayout.allowed_writes_bkload`), the far layer (W `$6800-$9BFF`, `$80-$AF`, `SS_AMAPW`), the math (its block, `mt_far`'s operands), the driver (its interrupt) |
| Milestone 8's W outside `OVLW`'s room | `$6000-$67FF`, `$9C00-$BFFF` but `BATCH` the same before and after `OVLW` in every overlay run |
| Stack | at most 59 B below the driver's in the overlay frames, 61 B in all (`--lowest-s-in`), of milestone 8's 112 |
| The images | `OVLW`'s `BKFAR` and `BKFAR2` are the frame image's (`MASKW`'s) byte for byte, at the same run addresses (both builds); its first bytes `jmp am_ovl`; the frame images `ovf` and `ovfp` are milestone 8's `ftest` and `fprof` (their objects `render.mk`'s, in its order; every file the same bytes, `rdriver.s`'s part of `.lce` but its operands naming its descriptor `DESC`, which this part's driver moves); the stand-in `s2_amline` assembles to `s2_amline.s`'s bytes for `AMAPW` |
| `tests/test_sound_*` | not touched |

### 2.1 The tests

`tests/wip_test_m11_s2ovl.py`, 12 tests: without a build, request
S2OVL-1's change applies once each (and fails on a changed source), each
planted edit is found once, `OVLW`'s link map and the planted one, the
places shared by `s2_ovl.s`, `s2ovl.mk` and the tool, `K_OVL`'s staged
size against `bucket.s`'s table, the frame image's objects against
`render.mk`'s `FTEST_OBJS`/`FPROF_OBJS`, the rcanon stand-in on a stream
with and without `K_OVL` (7 tests); with the build, the capture, the sizes
and the images, every frame and variant with both fills, the planted bugs,
the timing (5 tests).

`python3 tools/testpar.py --jobs 2 tests/wip_test_m11_s2ovl.py` [M]: 1
module, 12 tests, 0 failures, 0 errors, 0 skipped, 303.8 s. The 7 tests
without a build also pass on Python 3.9.6 with
`PYTHONWARNINGS=error::ResourceWarning`; `s2layout.py --check` passes
(the driver's phase marks 1, 13, 18 and 30 are read).

### 2.2 `--all`

`python3 tools/native/s2ovl.py --all --jobs 2` [M, 2026-10-02] (298 s,
two jobs): `report.json` ok. "102 runs (51 frames and variants), 0 with
problems; 180,896 `K_OVL` records compared in 86 overlay runs"; sizes
no problem (the images' checks above); the five planted bugs caught;
the timing below. `python3 tools/native/s2ovl.py --check --jobs 2` alone
(the 29 frames and 22 variants, both fills): the same 102 runs, about 3
minutes.

## 3. Planted bugs (each in a scratch copy) and the check that caught it

`python3 tools/native/s2ovl.py --planted --jobs 2`: each in a scratch copy
of its source (or of `OVLW`'s generated link map), built into a scratch
`M11` (milestone 8's objects taken from this part's build), run on
ovl-01, ovl-10, ovl-21 and plain-01 with fill `$A5`.

| Bug | Runs failing (of 8: the 4 frames and their variants; plain-01 has no overlay) | The first [M] |
| --- | ---: | --- |
| The kept nibble `$F0` for an even x (`am_plot`) | 7 | `ovl-01: records: 160 columns differ (first 0, record 5: native ('ovl', 88, 240, 208), reference ('ovl', 88, 15, 208))` |
| `FSCUTE`'s end row not `+ 1` | 7 | `ovl-01: spans: 25 differ (first 295: native 121, reference 122)` |
| The records before the view's last batch (the test driver runs the overlay's step after the walk, before the masked phase; main `$0C00-$0EFF`, `$0200-$02FF` kept in `RECW` around it) | 7 | `ovl-01: at the weapon: records: 160 columns differ (first 0, record 4: native ('ovl', 88, 240, 14), reference None)` |
| `nm_bkload` copying `BKFAR` from `MASKW`'s address instead of `OVLW`'s (`OVLW`'s link map with `__BKFAR_LOAD__` the frame image's) | 7 | `ovl-01: the frame stopped (BRK), status 0`; `ovl-10: the run ended with halt at $0F55` |
| (also) The fast turn never taken: every line by the 32-bit path | 7 | `ovl-01: records: 90 columns differ (first 1, record 5: native ('ovl', 34, 240, 14), reference ('ovl', 49, 15, 224))` |

## 4. Sizes against the budget

| Item | Size [M] | Budget |
| --- | ---: | ---: |
| `s2_ovl` (with its 3-byte entry) | 1,214 B | 4,500 B (7.3) |
| `s2_amline` (part s2amap's 3,700, with S2OVL-1's hook: +8 B) | 3,708 B | |
| `OVLW` own (s2layout's size table: `s2_ovl` and `s2_amline`) | 4,919 B | 5,500 B |
| `rrec.s` (`-D MREC`), `nm_bkload` | 198, 48 B | |
| `BKFAR`, `BKFAR2` (data) | 714, 233 B | |
| `OVLW` stored | 6,115 B (`$6800-$7FE2`) | 13,312 B (`$6800-$9BFF`) |
| `OVLW` run time | `$9400-$9BFF` (2,048 B) | in the room |
| Zero page | `$80-$AE` | overlay 2 |
| `S2STATE` | `SS_AMAPW`'s 110 B (`AMAPW`'s block) | |

## 5. Timing (SCREENS.md 6.4)

`python3 tools/native/s2ovl.py --timing`: the profiling builds (`ovfp`:
`fprof`'s objects, `ovlwp`: `bucket.s` and `rrec.s` with `-D RPROF`), the
29 frames (fill `$A5`), a2vm's cost model, `--cost-timed`; `OVLW`'s load
alone by `ovd_ltime` (the same each frame: its page runs).

`OVLW`'s load: 6,125 B (`ovlwp`, with the profiling build's `BKFAR`),
1.52 ms `f121`, 1.42 ms `fastpath` [M]. The title band's drain when
`titleBand` runs: 1,280 B, 1.27 ms [A on M: 0.991 µs a byte, `s2draw.md`
5] (no captured frame runs it).

ms, median / worst [M]:

| Phase | 21 overlay frames `f121` | 8 plain `f121` | overlay `fastpath` | plain `fastpath` |
| --- | --- | --- | --- | --- |
| The whole frame (phases 1-18, 30, 12) | 233.3 / 258.9 | 98.0 / 111.0 | 164.9 / 185.0 | 88.4 / 100.3 |
| 30: `OVLW`'s load and `am_ovl` (with its `nm_bkload`) | 56.5 / 61.2 | 0 | 51.0 / 55.6 | 0 |
| `am_ovl` (30 less the load) | 55.0 / 59.7 | | 49.6 / 54.2 | |
| 18: the bucket pass | 37.4 / 49.2 | 13.4 / 15.7 | 33.9 / 44.0 | 12.6 / 14.6 |
| 12: the replay (with the overlay's records) | 93.8 / 111.1 | 40.0 / 47.4 | 41.3 / 50.2 | 37.7 / 45.1 |
| 13: `MASKW`'s window | 2.53 | 2.53 | 2.37 | 2.37 |

The overlay frames draw the computer map (every line of E1M1: 1,689 to
2,489 `K_OVL` records); the replay's `f121` excess (about 54 ms) is its
`K_OVL` drawer's `RAMRD` window for each record, which waits for the
SHR bytes' drain (milestone 5's; lever L3).

## 6. Requests (for the integrator; the stand-ins are marked `STANDIN`)

### S2OVL-1. `src/native/s2_amline.s` (part s2amap's): the fast path's hook

**Evidence.** Upstream's `drawWalls` takes the fast turn for each line
whenever the rotation is on and `fastSetup` found `|s cos|`, `|s sin|`
below 0.25 [R `am_map65.s:1665-1670`, `:1771-1779`]; its rounding is not
the 32-bit path's: without it every overlay frame of `automap.script`
differs (planted bug 5: 90 to 160 columns' records). The hook must be
inside `am_walls`' loop (after `fetchline`, before `slowline`), which
`s2_amline.s` alone has; `toscreen` and `clipscr` are what the fast path
needs of it. `s2amap.md` 1.1 and open problem 2 leave the fast path to
this part. **Stand-in.** `build/native/m11/s2ovl/gen/s2_amline-ovl.s`,
written by `tools/native/s2ovl.py --amline` from `s2_amline.s` with
exactly this change (marked `STANDIN S2OVL-1`; the tool fails if a text
is not there once). Assembled for `AMAPW` (no `AM_FASTLINE`) it gives
`s2_amline.s`'s bytes (checked by `s2ovl.py --sizes` on every build).
**What.** In `src/native/s2_amline.s`, three insertions:

after `        .import am_seg, am_plot, am_rowcol`:

```
.ifdef AM_FASTLINE
        .import am_fastsetup, am_fastline   ; (OVLW's: request S2OVL-1)
        .export toscreen, clipscr
.endif
```

in `am_walls`, `        jsr wallrot` then `:       stz AMI` becomes:

```
        jsr wallrot
.ifdef AM_FASTLINE
        jsr am_fastsetup        ; fastSetup [R am_map65.s:1665-1670]
.endif
:       stz AMI
```

and `@draw:  sta COLI` then `        jsr slowline` becomes:

```
@draw:  sta COLI
.ifdef AM_FASTLINE
        jsr am_fastline         ; the rotation's fast turn: C = 1 drawn
        bcs @next               ;   [R am_map65.s:1771-1779]
.endif
        jsr slowline
```

The header's comment "the rotation's fast path (fastLine and its vertex
cache, the overlay's only) is part s2ovl's" may add "(s2_ovl.s:
am_fastsetup, am_fastline, through this hook)". Then `s2ovl.mk`'s rule
for `gen/s2_amline-ovl.s` and `AMLINE_CHANGES` in `s2ovl.py` go: the
makefile assembles `s2_amline.s` itself with `-D AM_FASTLINE` (and the
`HandMade` test of the stand-in becomes a check that the source has the
hook).

### S2OVL-2. `tools/native/rcanon.py` (milestone 8's): `K_OVL` in the record walks

**Evidence.** `walk_lists_all` raises on a `K_OVL` record ("a record of
kind 10") and `native_records_all` has no size for it, so milestone 8's
comparison (`frame8.compare`) cannot read a frame with the overlay; this
part's checkpoint is that comparison with the overlay's records.
**Stand-in.** `s2ovl.py`'s `standin_rcanon()` (marked `STANDIN
S2OVL-2`): in its own process, `rcanon.walk_lists_all` and
`rcanon.native_records_all` are replaced by copies with the `K_OVL`
branch, and `rcanon.NATIVE_SIZES` gains `K_OVL: 5`; streams without
`K_OVL` walk as before (a `HandMade` test). **What.** In `rcanon.py`:

- `NATIVE_SIZES = {K_TEX: 12, K_FILL: 6, K_TEXC: 8, K_FUZZ: 5}` becomes
  `{K_TEX: 12, K_FILL: 6, K_TEXC: 8, K_FUZZ: 5, K_OVL: 5}` (the automap
  overlay's pixel, milestone 11: the kind, the column, the row, keep, the
  colour; `bucket.s`'s `ssize`).
- In `walk_lists_all`, `if kind not in UP_SIZES or kind == K_OVL:`
  becomes `if kind not in UP_SIZES:`, and before its last `else:`
  (`recs.append(('fuzz', ...))`):

  ```
            elif kind == K_OVL:
                recs.append(('ovl', r[1], r[2], r[3]))
  ```

- In `native_records_all`, before its last `else:`:

  ```
        elif kind == K_OVL:
            lst.append(('ovl', r[2], r[3], r[4]))
  ```

Then `s2ovl.py`'s `standin_rcanon`, `_walk_lists_all`,
`_native_records_all` go (its calls become nothing).

### S2OVL-3. `tools/native/s2layout.py`: `OVLW`'s entry as built

**Evidence.** 1.2, 4. **What.** `Image('OVLW', ...)`'s runtime `()`
becomes `((0x9400, 0x9C00, 'the nibble pages, NCACHE, RBASE, the '
'variables, s2_amline\'s W variables (AMW $9A00), the state block (AMST '
'$9B00)'),)`; its `own_parts` text `'s2_ovl 4,300, rrec.s 198, nm_bkload
48, BKFAR/BKFAR2 962'` becomes `'s2_ovl 1,214 [M] and s2_amline 3,708 [M]
(part s2amap\'s, with S2OVL-1\'s hook): 4,919 [M]; rrec.s 198, nm_bkload
48, BKFAR/BKFAR2 947 [M] (not in the S2 segments): 6,115 of 13,312 B
stored'`; the budget 5,500 stays. Optionally `OVLW_AMW = 0x9A00`,
`OVLW_AMST = 0x9B00` in `s2.inc` (now `s2ovl.mk`'s `-D AMW=39424 -D
AMST=39680`, checked equal to `s2_ovl.s`'s places by a test), and
`OVLW_ENTRY = OVLW_LO` (the image's first bytes `jmp am_ovl`).

### S2OVL-4. `docs/m11-parts/design.md` R7 (the frame driver, the second half)

**What.** Item 2 becomes: "With the automap's overlay on (`AUTOMAP` has
`AM_ACTIVE` and `AM_OVERLAY`): after `nm_masked` (its last batch staged),
`far_pload` of `OVLW`'s page runs (`$68`, 24 pages, from bank 93,
`OVLW_BANK`) in `MASKW`'s place, then `jsr OVLW_LO` (`$6800`: `jmp
am_ovl`) with A = the frame's tics: `am_ovl` runs `AM_Ticker` once a tic,
the overlay's records, `titleBand` (rows 160-167 black on the screen when
`am_band` was 0, and `MAIL_AMTITLE`), `am_valid` 0, then `OVLW`'s own
`nm_bkload` (in place of `MASKW`'s); then `nb_frame`. `OVLW` reads the
HUD's `message_on` (`HU_ON`), so `hu_ticker` has run (the tic phase)."
Item 1 adds: "and `VIEWBOT` = 160 (`AM_TITLEY`) when the overlay is on,
else 168, as `display` [R `d_main65.s:475-482`]: the replay leaves the
title band's rows to `OVLW` and `P2DW`." Item 12's last sentence "In an
overlay frame the tics' `AM_Ticker` is `OVLW`'s (part `s2ovl`:
`s2_amline.s`'s `am_ticker` once a tic) or `AMAPW`'s `am_tick` once a
tic." becomes "In an overlay frame the tics' `AM_Ticker` is `OVLW`'s
(`am_ovl`'s A, item 2)." Item 13 is as built.

### S2OVL-5. `docs/SCREENS.md`: the overlay as built

**What.**
- 1.5.4's overlay row, the native column, becomes: "`OVLW` (`$6800-$9BFF`,
  `MASKW`'s code room; bank 93): `s2_ovl.s` (`am_ovl`, A = the frame's
  tics: `AM_Ticker` once a tic, `titleBand`, the rows' colours, the walls
  and the arrow by part s2amap's `s2_amline.s` with the rotation's fast
  turn of upstream (`fastSetup`, `fastLine`, `fpoint`: request S2OVL-1),
  each pixel a `K_OVL` record through `mrec_room` with `FSCUTE` on
  `FSTOP`/`FSBOT`), milestone 8's `rrec.s` (`-D MREC`) and `bucket.s`'s
  `nm_bkload` with `BKFAR`/`BKFAR2` as data (the frame image's bytes).
  The frame driver loads `OVLW` (`far_pload` of its page runs) after
  `nm_masked`'s last batch and calls `$6800`; `am_ovl` ends with its own
  `nm_bkload`, so `MASKW` is not loaded again. The replay draws the
  records (milestone 5's `K_OVL`). Part s2ovl, `docs/m11-parts/s2ovl.md`".
- 4.1's `OVLW` row: stored "`$6800-$7FE2` (6,115 B [M] of the 13,312 B
  room): `jmp am_ovl`, `s2_ovl.s`, `s2_amline.s`, `rrec.s`, `nm_bkload`
  and `BKFAR`/`BKFAR2` as data"; runtime "`$9400-$9BFF` (the nibble pages,
  `NCACHE`, `RBASE`, the variables, `AMW`, `AMST`); milestone 8's
  otherwise"; load "`far_pload` of its page runs from bank 93: 1.52 ms
  `f121` [M]". The paragraph after the size table: "`OVLW`: `s2_ovl`
  1,214 B and `s2_amline` 3,708 B [M], `rrec.s` 198 B, `nm_bkload` 48 B
  and `BKFAR`/`BKFAR2` 947 B [M]: 6,115 of 13,312 B (part s2ovl)."
- 4.3's `$80-$AF` row adds: "`OVLW`'s `s2_amline` places `$80-$AE`
  between the masked phase and the bucket pass (overlay 2 dead; part
  s2ovl)".
- 4.4's paragraph "`s2ovl`'s test runs milestone 8's whole frame with
  `rdriver.s` (card `$E000-$F8FF` [R `src/native/render.cfg`]) and needs
  none of this card state." becomes "`s2ovl`'s test runs milestone 8's
  whole frame with `rdriver.s` and its own driver `s2_ovd.s` after it in
  `render.cfg`'s `$E000` part (to `$E383`); `OVLW` reads `HU_ON` and
  writes `S2_MAIL` at the test build's places, free there." and the
  "This half's tests" row's "`s2ovl`'s uses milestone 8's `rdriver.s`,
  below" stays.
- 2.1's frame table, the render row: "`OVLW` after the masked phase when
  the overlay is on | far layer; `titleBand`'s `RAMWRT` window (1,280 B
  when `am_band` was 0) and the replay's: `RAMWRT` off waits for their
  drain".
- 8.3's lever L3 adds "(measured by part s2ovl: the replay of an overlay
  frame with the computer map, 1,689-2,489 `K_OVL` records, is 93.8 ms
  `f121` median against 40.0 ms without the overlay, 41.3 against 37.7
  `fastpath`: each record's `RAMRD` window waits for the drain)".
- 7.3's `s2ovl` paragraph: Files add `src/native/s2_ovd.s` (the test
  driver) and `tools/native/s2ovl.py`; the checkpoint's "after the native
  replay the view rows equal `PD1`'s" becomes "the screen after the
  replay equal to `R_DrawLists`' return (P5: `PD1`'s view rows, which
  part s2cap's cases do not keep, X1), the title band black when
  `titleBand` runs".

## 7. Decisions where the design left a choice

- **The truth is milestone 8's capture, not part s2cap's cases.** The
  checkpoint compares records by column, spans and the replay's screen:
  milestone 8's points P0 .. P5 (`rendercap.run_one`, this part's choice
  of frames, its own directories: `rendercap.py`, `levelconv.py` and
  their output directories are module attributes set in `s2ovl.py`'s
  process, the files untouched). s2cap's `PD1` does not keep the view's
  rows (X1); P5 is the screen at `R_DrawLists`' return, whose view rows
  nothing later in the frame writes. s2cap's `PD0` gives the frame's
  start (the palette state before display's `I_ViewPalette`).
- **`OVLW`'s own link.** `rrec.s` and `bucket.s` assemble their parts
  into `MASKW`, `BKFAR` and `BKFAR2` by segment name, so `OVLW` cannot be
  a second area of the frame image's link: it is linked alone
  (`ovlw.cfg`), the frame image's symbols given by value (`SYMBOLS`, from
  its labels: the far layer, the math, `nat_replay`) and `BKNEAR` placed
  where the frame image has it; `OVLW`'s `BKFAR`/`BKFAR2` are checked equal
  to the frame image's on every build.
- **The entry is the image's first byte** (`jmp am_ovl` at `$6800`): the
  frame driver needs no symbol of `OVLW`'s link.
- **The room is poisoned before the load** (the test driver): `OVLW`'s
  page runs do not cover all of `MASKW`'s pages (`MASKW`'s `BKFAR` data at
  `$8A6A` is above `OVLW`'s `$7FE2`), so without it `nm_bkload` copying
  from `MASKW`'s address (planted bug 4) would copy `MASKW`'s leftovers
  and pass.
- **The snapshot before `nm_bkload`.** `am_ovl` ends with `jmp
  nm_bkload` (the design), whose copy overwrites `FLOORCLIP`/`CEILCLIP`
  ($0C00-$0DFF) that milestone 8's comparison reads. A PC event inside
  `OVLW` could also be a `MASKW` instruction earlier in the frame, so the
  run snapshots before `OVLW` (`ovd_ovl`) and after `am_ovl` returns
  (`ovd_post`); the compared state is the latter with `nm_bkload`'s writes
  (`BKFAR`, `BKFAR2`, `BK_P`/`BK_Q`) as the former has them; the write log
  checks that only `nm_bkload` writes there in `OVLW`'s phase.
- **The rows' colours** as part s2amap's `nibcache` (4 slots of 40
  nibbles), with display's `I_ViewPalette(0)` instead of `AMAP_PAL`.
- **`titleBand` publishes its black rows itself** (as `AMAPW`'s redraw
  does), and `MAIL_AMTITLE` tells `P2DW` (R7 item 7's bit 2): the replay
  never draws rows 160-167 in an overlay frame (`VIEWBOT` 160).
- **No vertex cache**: same points; the cost is in 5.
- **`am_valid` 0 in `am_ovl`** (display's after `R_DrawLists` in a view
  frame), as `design.md` R7 item 13 says.
- **The 'tics' variant** starts from the state the frame before left at
  `R_DrawLists` (or after an `AM_Responder` call in between that changed
  the automap's fields: none in the script changes them, only `AM_EV`, a
  scratch) with the `AM_Ticker` calls in between as A.

## 8. Open problems

1. **The overlay's cost** with the computer map (every line, 1,689 to
   2,489 pixels a frame): `OVLW`'s work 55 ms (`f121`, median), the
   bucket pass 37 ms instead of 13, the replay 94 ms instead of 40 (its
   `K_OVL` drawer's `RAMRD` window a record: lever L3, SCREENS.md 8.3); the
   whole frame 233 ms against 98 without the overlay (5). Levers in
   `OVLW`: upstream's vertex cache (each line's ends are shared: about
   half of the `fpoint` products), a cheaper `am_plot` (the page model
   and the record per pixel are upstream's format). Without the computer
   map (the seen lines only) no frame is measured: `automap.script`
   turns it on before the overlay.
2. **Upstream's vertex cache is not ported** (1.1): no pixel changes; a
   cost lever (1).
3. **`titleBand` is reached by injection only** (`band0`: `am_band` 0):
   the script goes from the full map (which leaves `am_band` 1) to the
   overlay; a script that turns the overlay on from the view (the map key
   twice within a frame, or a view frame between) would capture it.
4. **No modelled or early flush and no stop** (`PL_AMPALS`) in the
   captured frames: `UPFLUSH` stays 0 (the extra pages go to 214 of 255);
   the half and two-thirds views (`halfOvl`, `AM_Clean`) are milestone
   13's.
5. **The arrow's lines** (the 32-bit path, rotated by `ANG90` without
   products) are compared in every overlay frame; a line of the walls
   with an end too far for int16 from the player (the fast path's
   fallback) is never met in E1M1.
6. The part took longer than its 1.5 hours.

## 9. The wave 7 integration (2026-10-02)

What the integrator did with each request (`docs/SCREENS.md` 8.11,
"Wave 7 as integrated"):

| Request | Outcome |
| --- | --- |
| S2OVL-1 | Applied as written: `src/native/s2_amline.s` has the hook (the `.ifdef AM_FASTLINE` import and export, `jsr am_fastsetup` after `wallrot`, `jsr am_fastline` / `bcs @next` before `slowline`) and the header's note. Without `AM_FASTLINE` it assembles to the same 3,700 B as before (checked by assembling the source with and without the hook's text). `s2ovl.mk` assembles `s2_amline.s` itself with `-D AM_FASTLINE` (`s2_amline-ovl.o`); the generated `gen/s2_amline-ovl.s`, `AMLINE_CHANGES`, `amline_standin`, `write_amline` and `--amline` went. `amline_problems()` (in `--sizes`) and the test `test_s2_amline_has_the_hook` now check that the source has each part of the hook once |
| S2OVL-2 | Applied as written to `tools/native/rcanon.py` (`NATIVE_SIZES[K_OVL]` 5; `walk_lists_all` and `native_records_all` read `K_OVL` as `('ovl', row, keep, colour)`); `standin_rcanon`, `_walk_lists_all`, `_native_records_all` and their calls went; the test `test_rcanon_reads_k_ovl` reads a stream with and without `K_OVL` through rcanon itself |
| S2OVL-3 | Applied **with one change**: `OVLW`'s runtime `((0x9400, 0x9C00, ...),)` and the `own_parts` text as asked; the budget 5,500 stays. As written, the run time range inside the room failed `s2layout.check()` (every image's run time ranges must be disjoint from its room). The check now requires `OVLW`'s run time ranges to be **inside** its room instead (every other image's stay disjoint), and `--check-map` limits an image's stored bytes to below a run time range inside its room, so `ovlw.sizes`' room row reads "4,922 of 11,264 B" (the S2 segments; the ld65 map's `OVW` area already stopped at `$9400`). `s2.inc` gains `OVLW_RT0`, `OVLW_RT0_END` from the range; the optional `OVLW_AMW`, `OVLW_AMST`, `OVLW_ENTRY` were not added (`s2_ovd.s` defines `OVLW_ENTRY` itself, and the makefile's `-D AMW`, `-D AMST` stay, checked by the test). `test_the_places_agree` also checks the range against `NBUF` and the room's end |
| S2OVL-4 | Applied: `design.md` R7 items 1, 2 and 12 as asked (and SCREENS.md 5's R7 row: `far_pload`, `jsr $6800`) |
| S2OVL-5 | Applied: SCREENS.md 1.5.4's overlay row, 2.1's render row, 4.1's `OVLW` row and the paragraph after the table, 4.3's `$80-$AF` row, 4.4's paragraph, 7.3's paragraph, 8.3's lever L3 |

Results after the integration [M]: `python3 tools/native/s2ovl.py
--capture` (3 s) and `--all --jobs 2` (242 s): `report.json` ok, the same
102 runs with 0 problems and 180,896 `K_OVL` records, the five planted
bugs caught (7 of 8 runs each), the sizes and the timing of sections 4
and 5; `tests/wip_test_m11_s2ovl.py` 12 tests OK (285 s, in the full
suite).
