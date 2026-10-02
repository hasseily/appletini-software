# Milestone 11, part `s2wi`: the intermission

Part `s2wi` of wave 5 ([`docs/SCREENS.md`](../SCREENS.md) 7.3), written
from upstream's `src/iigs/wi_stuff65.s` (`WI_Init`'s lumps, `WI_Drawer`,
`drawStats`, `drawShowNextLoc`, `drawAtNode`, `slamBackground`,
`drawCenteredPatch`, `nextY`, `drawPercent`, `digitCount`, `drawNum`,
`drawTime` [R `wi_stuff65.s:96-200`, `:586-903`]) and display's
intermission branch [R `d_main65.s:389-399`]. 2026-10-01. Follows
SCREENS.md 1.5.5, 1.5.7, 4.1, 6. Labels as in `NATIVE.md`: [M] measured,
[R file:line] read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `src/native/s2_wi.s` | The image `WIW`'s own code (1,922 B: code 1,397, tables 103, variables 422): `wi_init` (`WI_Init`: the 33 lumps as 2D store handles into `W_LUMPS` and its place in `S2STATE`), `wi_frame` (an intermission frame: `pl_poll`, `fx_service`, `s2_palget`, `W_LUMPS` from `S2STATE`, `I_SetPalette(0)` when a level was left, `wi_drawer`, `s2_finish`, `s2_palput`), `wi_drawer` (`WI_Drawer` and everything under it). It exports the image's places for the shared objects (`s2_marks`, `s2_fbuf`, `s2_fbpages`, `s2_palst`, `s2_begun`, `s2_nbuf`) |
| `src/native/s2_wipl.s` | **STANDIN** `pl_poll` (an `rts` and 599 spare bytes: its 600 B budget), assembled as `pl_input-s2wi.o` so the size table counts it in `WIW`'s `pl_poll` row, until part `plinput`'s `pl_input.s` |
| `src/native/s2_wit.s` | The test glue (not the game): `wit_case` stages a case (the wi state at milestone 10's places, `PALST`, `WIW`'s own block, the SCBs and palettes), poisons the pixels, then runs `wi_frame` in the cost phase 30 |
| `src/native/m11/s2wi.mk` | `make -C src/native -f m11.mk part P=s2wi`: `gen/lgame.inc` (milestone 10's generated include, `llayout.py --game`), `gen/s2wi.inc`, `gen/s2pal.inc` (part s2pal's generator), the image `wiw` (WIW as the game links it, under the test driver) and the test image `s2wt` (with the glue) |
| `tools/native/s2wi.py` | The checks: the tour's intermission frames from part s2cap's capture, staged and run on a2vm, the snapshots and the write log judged; `--inc`, `--check`, `--planted`, `--units`, `--all` (`report.json`) |
| `tests/wip_test_m11_s2wi.py` | 9 tests (2.1) |

Build output: `build/native/m11/s2wi/` (1.6 MB: the objects, the two
images, `gen/`, `report.json`). Every run's directory, and every planted
bug's scratch copy, is a `tempfile` directory there, deleted after it.

### 1.1 The interface

**The wi state is milestone 10's**, read through its generated include
`lgame.inc` (`llayout.py --game`, the names `WI_STATE`, `WI_SNLPTR`,
`WI_CNTKILLS`, `WI_CNTITEMS`, `WI_CNTSECRET`, `WI_CNTTIME`, `WI_CNTTOTAL`,
`WI_CNTPAR`, `G_WMINFO` and `WM_DIDSECRET`, `WM_LAST`, `WM_NEXT`), so no
local stand-in was needed. **One write**: upstream's `WI_Drawer` sets
`snl_pointeron` to 1 in NoState [R `wi_stuff65.s:586-592`], and that value
carries into the next intermission's first ShowNextLoc frame (frame 5,524
of the tour starts with it 1); `wi_drawer` writes `WI_SNLPTR` the same
(request S2WI-4). `W_LUMPS` (WIW's own block, `$BF00`, 33 handles in
lumpNames' order) is `wi_init`'s, kept in `S2STATE`'s `SS_WIW`.

**The frame** (for the frame driver, request S2WI-5): `jsr wi_frame` with
A bit 0 set when display's `oldgamestate` was a level (display calls
`I_SetPalette(0)` then [R `d_main65.s:389-393`]), after `far_pload` of
`WIW`. It calls `pl_poll` and `fx_service` first (SCREENS.md 2.1), then
the palettes' `s2_palget`, the drawing and `s2_finish`/`s2_palput`.

**How a frame is drawn.** As upstream, the whole picture and every patch
each frame (upstream's `drawPicture` marks rows 0-199 [R
`i_viigs65.s:1236-1240`], so it republishes 32,000 bytes a frame):

1. The patches' list: `drawStats` or `drawShowNextLoc` run once, each
   `drawLump`, `drawCenteredPatch` or `V_DrawPatchScaled` adding an entry
   (the patch's bank and address from `GFXDIR`, its top-left corner after
   its offsets, its height). Up to 47 entries (the stats' most: 2 titles,
   3 × (label, `%`, 5 digits), 3 × (label, 7 fields of a time)).
2. `WIMAP0`'s palette part: `s2_picpal` (A, X = its release lump number,
   upstream's `picturenum`, from `gen/s2wi.inc`): nothing when it is on the
   screen, else its rows, palettes and 16 nibble tables.
3. Five bands of 40 rows: the picture's rows (`s2_rect`, every byte
   marked), each listed patch crossing the band (`s2_patch`, clipped to
   it), then `s2_publish` (whose first band calls `s2_begin`: the black
   step and `newColors`).

**The nibble tables.** A pixel on row r uses the table of the row's
palette and parity: two pages (the left pixel's, the right pixel's) [R
`patch65.s:3-9`]. `WIMAP0` changes palette every few rows (13 palettes in
rows 0-39), so the splat at node 7 (rows 18-39) needs 10 palettes, more
than 8 slots of 1 KB. `WIW` uses its 8 KB of slots as **16 units of 2
pages** (a palette and a parity), fetched from `S2NIB` the first time a
frame needs them; a patch that needs more units than are free empties the
cache first. `python3 tools/native/s2wi.py --units` checks every row a
patch can be drawn at (103 positions): the most is 16, that splat [M].
More than 16 would be a `BRK`.

**Zero page**: the drawers' `S2_*`, the far layer's `FA_*`, and `WIW`'s
temporaries `S2W_*` at `$80-$AD` (request S2WI-1). The test glue uses
`$B0-$B4` (the math block's; `WIW` calls no math).

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
df -h /System/Volumes/Data                      # 69 GB free
make -C src/native -f m11.mk part P=s2wi        # no warning
python3 tools/native/s2wi.py --all --jobs 2     # 4 min: f121, fastpath,
                                                #   planted, report.json
python3 tools/testpar.py tests/wip_test_m11_s2wi.py
```

Results [M, 2026-10-01]: `report.json` `ok`, 0 problems.

| Item | Result |
| --- | --- |
| Every intermission frame of the tour | 214 frames, 8 intermissions, none excluded: 88 stats frames, 118 next-location frames (80 with the pointer on), 8 new-picture (wipe) frames; each frame's whole screen (32,000 pixel bytes, the 200 SCBs, the 512 palette bytes; `$9DC8-$9DFF` kept) equal to the reference's after the frame |
| Injected, both fills | every frame from its own state: fill `$A5` with the SCBs and palettes as captured, fill `$5A` with every byte the frame marked poisoned; the pixels are always poisoned before the frame (all 32,000 must be drawn): 428 frame runs in 36 a2vm runs, 0 problems |
| Chained | each intermission from its first frame (the wipe): `wi_init`, then every frame with `PALST`, `W_LUMPS` and the nibble tables carried by the native code (across a2vm runs too: the last run's `S2STATE` and `S2NIB` start the next), the wi state injected each frame as milestone 10 makes it: 214 frames in 10 runs, 0 problems; `W_LUMPS` equal to upstream's lumps as handles |
| `WI_SNLPTR`, `PALST` | after every frame equal to the reference's at `I_FinishUpdate` (NoState's write included); `PALST`'s `scb`, `palette` and `picturenum` too |
| No stray write | 20,048,733 writes judged on `f121` (13,492,530 on `fastpath`), 0 stray: the driver, the loader, the far layer, the glue, `s2_wi`, `s2_draw`, `s2_pub`, `s2_pal`, `s2_nib`, `fx_service`, the `pl_poll` stand-in, each in its allowed set |
| The publish order (SCREENS.md 1.3) | `s2check.order` on every frame's screen stores: the black step first on the 8 wipe frames, no band store before the last SCB store, no colour store before the last band store |
| Stack | 24 B (`--lowest-s-in`, the interrupt's included), of 64 + 24 |
| `WIW` within its room | 5,160 of 6,656 B (`wiw.sizes`, with the 600 B `pl_poll` stand-in) |
| `tests/test_sound_*` | not touched; green (7 modules, 152 tests) |

### 2.1 The tests

`tests/wip_test_m11_s2wi.py` (9 tests, 198 s): without a build, the
region (the whole screen but rule 10's bytes), the stage layout against
`s2_wit.s`'s constants, each planted edit found once in the sources, the
wi state taken by `lgame.inc`'s names (also OK on Python 3.9.6 with `-W
error::ResourceWarning`); with the build, the checkpoint (injected and
chained), the include, the units, the sizes, and the four planted bugs.
Without `build/` the first four run and the others skip naming what is
missing.

`python3 tools/testpar.py tests/wip_test_m11_s2wi.py` [M]: 1 module, 9
tests, 0 failures, 0 errors, 0 skipped.

## 3. Planted bugs (each in a scratch copy of the sources) and the check that caught it

| Bug | Caught by | The first failure [M] |
| --- | --- | --- |
| `drawTime` without the first colon | every stats frame (140) | `tour/f003444 (fill A5): row 160 byte 58, $843A: $46, ref $DD (246 bytes differ)` |
| The splats drawn to `last` instead of `next - 1` after the secret level | the next-location frames after E1M9 (74) | `tour/f010500 (fill A5): row 18 byte 68, $2B84: $E3, ref $83 (793 bytes differ)` |
| The "you are here" node not lowered to 45 | the pointer at nodes 8 and 7 (20) | `tour/f008851 (fill A5): row 9 byte 41, $25C9: $2B, ref $44 (390 bytes differ)` |
| The percent sign of a negative count | the stats frames whose counts are still -1 (52) | `tour/f005524 (fill A5): row 50 byte 135, $3FC7: $8A, ref $87 (177 bytes differ)` |

## 4. Sizes against the budget

| Item | Size [M] | Budget |
| --- | ---: | ---: |
| `s2_wi`'s code | 1,397 B | 1,400 B (`s2wi`, 7.3) |
| `s2_wi`'s tables (handles, nodes, rows) and variables (the list 376, the units 32, the picture's and the name's places 14) | 103 + 422 B | 400 B (data, 4.1); over: request S2WI-2 |
| `WIW` own (`s2_wi`) | 1,922 B | 1,800 B |
| `s2_draw` + `s2_pub`, `s2_pal`, `s2_nib`, `fx_service`, `pl_poll` (stand-in) | 1,172, 680, 390, 396, 600 B | 1,200, 800, 400, 400, 600 B |
| `WIW` in its room | 5,160 B | 6,656 B (design total 5,200) |
| Zero page | `S2W_*` `$80-$AD` (46 B) | request S2WI-1 |

The first build, with the temporaries in `S2DATA`, was 2,173 B own.

## 5. Timing (SCREENS.md 6.4)

`python3 tools/native/s2wi.py --all` [M]: each frame's `wi_frame` alone
(the glue's cost phase 30 around it, the clock from the write log's
`PHASE` stores, `--cost-timed`), the 214 frames injected:

| Frame | Frames | `f121` median / p99 / worst ms | `fastpath` median / p99 / worst ms |
| --- | ---: | --- | --- |
| Stats | 88 | 85.97 / 88.99 / 88.99 | 73.61 / 76.03 / 76.03 |
| Next location | 118 | 76.01 / 95.91 / 95.92 | 65.74 / 80.95 / 80.95 |
| A new picture (the 16 nibble tables built, the black step) | 8 | 101.66 / 104.14 / 104.14 | 85.72 / 87.71 / 87.71 |
| All | 214 | 81.09 / 102.86 / 104.14 | 69.65 / 86.70 / 87.71 |

Apart from these: `WIW`'s load, 5,160 B, about 1.3 ms [A on M: 0.246 µs
a byte, `NATIVE.md` 4.3]; the publish's drain, 32,512 B a frame (the
pixels and the palettes), about 32.2 ms of the times above [A on M: 0.991
µs a byte, `s2draw.md` 5].

## 6. Requests (for the integrator; the stand-ins are marked `STANDIN`)

### S2WI-1. SCREENS.md 4.3 (and `s2layout.py` if it lists zero page by image): `WIW`'s temporaries at `$80-$AD`

**Evidence.** With its 46 B of temporaries in `S2DATA` the image's own
part was 2,173 B, its code 1,594 B (over the 1,400 B budget) [M: the first
build]; in zero page the code is 1,397 B. `$80-$AF` is the menu's and the
automap's (4.3); neither runs while `WIW` does (the menu pauses the game
and `uiDisplay` replaces display, so no intermission frame is drawn under
it [R `d_main65.s:513-514`]; `AMAPW` draws level frames only), and `WIW`
keeps nothing there between frames. **What.** 4.3's row `$80-$AF`
becomes: "`S2M_*` / `S2A_*` / `S2W_*`: the menu's and the automap's own
state; `WIW`'s temporaries `$80-$AD` (part `s2wi`; nothing kept between
frames)".

### S2WI-2. SCREENS.md 4.1, 7.3: `WIW`'s own budget

**Evidence.** Section 4. The variables are runtime only, but `S2DATA` is
stored with the image (0.1 ms of load). **What.** 4.1's size table, `WIW`
own: "1,800 (`s2wi` 1,400, data 400)" becomes "1,950 (`s2wi` 1,400, data
550: 1,922 [M])"; the total "5,200 / 6,656" becomes "5,350 / 6,656" (5,160
[M] with the `pl_poll` stand-in at its budget). `s2layout.IMAGES`' `WIW`:
`1800, 's2wi 1,400, data 400'` becomes `1950, 's2wi 1,400, data 550'`,
and `DESIGN_TOTALS['WIW']` 5200 becomes 5350.

### S2WI-3. `pl_poll` (part `plinput`)

**Stand-in.** `src/native/s2_wipl.s` (marked `STANDIN`), assembled as
`pl_input-s2wi.o`. **What.** When `src/native/pl_input.s` exists,
`s2wi.mk`'s `S2WI_SHARED` takes `$(S2WI_DIR)/pl_input.o` instead of
`pl_input-s2wi.o` and `s2_wipl.s` is deleted; `tools/native/s2wi.py`'s
owner "pl_poll (stand-in)" becomes `pl_input`'s with its allowed set
(`$03B3-$03ED`, its I/O), and its `card_records`/stage give the input
block its boot state.

### S2WI-4. The wi state is not read-only from the frame side (SCREENS.md 1.5.5, 5; milestone 10)

**Evidence.** Upstream's `WI_Drawer` writes `snl_pointeron = 1` in NoState
[R `wi_stuff65.s:586-592`]; the value survives `G_WorldDone` and is the
one the next intermission's first ShowNextLoc frame shows (the tour's
frame 5,524 starts with 1 from frame 3,801); every frame's `WI_SNLPTR` is
checked against the reference's at `I_FinishUpdate`. **What.**
SCREENS.md 1.5.5, "read-only through the generated include" becomes
"through the generated include, read only but `WI_SNLPTR`, which
`WI_Drawer` sets to 1 in NoState as upstream"; 5's "Read only, from
milestone 10" adds "(but `WI_SNLPTR`: S2WI-4)". For milestone 10
(`docs/m11-parts/design.md` R4/R7): a run of tics without frames
(`flowcheck`) leaves `WI_SNLPTR` as the tickers leave it; where it
compares `WI_SNLPTR` after a NoState tic, the reference's value includes
display's write.

### S2WI-5. The frame driver (R7): the intermission's frame

**What** (`design.md` R7, a new item): "In an intermission frame
(`G_GAMESTATE` 1), after the tics: `far_pload` of `WIW` (bank `S2CODE3`),
then `jsr wi_frame` with A = 1 when display's `oldgamestate` was a level
(the frame that leaves it: `I_SetPalette(0)`), else 0. A menu over the
intermission (`_g_menuactive`) runs `MENUW`'s frame instead, as display's
`uiDisplay` does. `wi_init` runs once at the boot with `WIW` loaded (it
writes `SS_WIW`), like upstream's `WI_Init` in `D_DoomMain`."

### S2WI-6. SCREENS.md 4.1, `WIW`'s runtime ranges: the slots as units

**What.** `WIW`'s "`$9A00-$B9FF` eight nibble slots" becomes "`$9A00-$B9FF`
the nibble tables: 16 units of 2 pages (a palette and a parity; part
`s2wi`: a 22-row patch on `WIMAP0` can need 10 palettes)". `s2layout.py`'s
`WIW` runtime text the same (`'eight nibble slots'` → `'16 nibble units of
2 pages'`). No address changes.

### S2WI-7. Part `s2cap`'s `s2state.py`: the native fields at a frame's start (for the later parts)

**Evidence.** `PS_BEGUN` has no upstream counterpart, so an injected
`PALST` leaves it the fill, and `s2_publish` then skips `s2_begin` (the
first run of this part lost the black step and the SCBs of the 8 wipe
frames). `S2NIB` (upstream's `NIBTAB`) is not injected either: a frame
whose picture is already up draws its patches through it. **Stand-in.**
`s2wi.stage()` sets `PS_BEGUN` 0 (`s2_finish` leaves it 0 at every frame's
end) and `run_job` puts `WIMAP0`'s 16 tables (part s2pal's
`s2palmodel.build_nibtab`, checked against ref816's `NIBTAB`) into `S2NIB`
for the runs without a new picture (the wipe frames build their own).
**What.** `s2state.inject(..., 'palettes', ...)` writes `PS_BEGUN` 0;
`s2state.DEFERRED` names `NIBTAB` ("built from the picture on the screen,
or the level's records: part s2pal's model").

## 7. Decisions where the design left a choice

- **Upstream's whole redraw.** Every frame draws the picture and every
  patch and publishes 32,000 bytes, as upstream does (its `drawPicture`
  marks all rows). Lever L-WI (not taken): the picture changes only on its
  first frame, so publishing only the patches' rectangles (and the
  pointer's background when it blinks off) would give the same screens
  with about a tenth of the bytes and the drain.
- **The list.** The patches' places and positions are computed once a
  frame (the divisions of the counts and times once), then each band draws
  the entries that cross it, in upstream's order (so overlaps are
  upstream's).
- **`PS_PICTURE` holds upstream's lump number** (`WI_PICNUM`, 322 [M]), as
  part s2pal's `s2_picpal` and the injected `picturenum` do; the patches go
  by the 2D store's handles.
- **The units of 2 pages** (1.1) instead of 1 KB slots.
- **Arithmetic as upstream's**: `drawCenteredPatch`'s signed halving,
  `nextY`'s 16-bit `5 * h / 4`, `digitCount` on the unsigned count, the
  node's lowering by an unsigned compare, the splats' signed loop to `last`
  (or `next - 1`), `drawTime`'s fields (two digits for the seconds, the
  minutes two only with hours, the first colon always, "sucks" at 86,400 s
  or more, nothing for a negative time), `par` sign-extended.
- **The test's write log** leaves out the stack page, `$00-$05`,
  `$48-$7F`, the image's code (s2_draw patches its operands), `WIW`'s
  runtime W and the pixel rows 1-198 (the whole screen is compared on the
  snapshots; rows 0 and 199, the first and last band stores, stay for the
  order).

## 8. Open problems

1. **The tour reaches few values.** Its counts are -1 or 0 (`0%`), its
   times 1-8 s and its par 30-180 s, so 2-5 digit counts, hours, "sucks"
   and a negative par are drawn by no compared frame. A synthetic set by
   `ref816 --call` of `WI_Drawer` with poked counts (as part s2hud's
   synthetic lines) would close it; not built.
2. **`pl_poll` is a stand-in** (S2WI-3) and `fx_service` runs with empty
   mailboxes only (the test's card state); neither is exercised here.
3. **A frame takes 70-100 ms** (section 5), about 32 ms of it the drain of
   32 KB that upstream's model republishes every frame (lever L-WI).
4. **`W_LUMPS` is not loaded at the boot** until `plboot` and the frame
   driver call `wi_init` (S2WI-5).
5. The requests S2WI-1 (zero page), -2 (budget) and -6 (the slots' text)
   change no address; until they are applied, `WIW`'s own row prints
   `OVER BUDGET` (1,922 of 1,800 B), which fails no build.
6. The part took longer than its 1.5 hours.

## 9. The wave 5 integration (2026-10-01)

What the integrator did with each request (`docs/SCREENS.md` 8.9, "Wave
5 as integrated"):

| Request | Outcome |
| --- | --- |
| S2WI-1 | Applied to SCREENS.md 4.3 and `s2layout.ZP_S2M`'s comment (`s2layout` lists no zero page by image) |
| S2WI-2 | Applied: `WIW`'s own budget 1,950 (`s2wi` 1,400, data 550), `DESIGN_TOTALS['WIW']` 5,350; SCREENS.md 4.1. `wiw`'s own row is 1,924 of 1,950 B (2 B more: `wi_frame` now loads A = 0 for `pl_poll`); the test image `s2wt` counts its 268 B glue as own and prints `OVER BUDGET`, which fails no build |
| S2WI-3 | Applied: `s2wi.mk` links `pl_input.o` (and `pl_irq.o` for `pl_time`); `s2_wipl.s` deleted; `s2wi.py`'s owners take `plinput.image_owners()` and its runs start with `plinput.boot_records()` (the input block as `pl_init` leaves it, the default key table) |
| S2WI-4 | Applied to SCREENS.md 1.5.5 and 5; for milestone 10 in `design.md` R7 item 8 |
| S2WI-5 | Recorded in `design.md` R7 item 8 |
| S2WI-6 | Applied: SCREENS.md 4.1, `s2layout`'s `WIW` runtime text |
| S2WI-7 | Applied: `s2state.inject(..., 'palettes', ...)` adds a record `PS_BEGUN` 0; `s2state.DEFERRED` names `i_viigs65.s:NIBTAB` (no field of the map today). `s2wi.stage()` keeps its own `PS_BEGUN` 0 and `run_job` its `S2NIB` |

**Fixed between the parts.** `wi_frame` called `pl_poll` with A = its
own flags byte (bit 0, a level was left), which the real poll reads as
"a menu is up" (its menu repeat): it now passes 0.

Results after the integration [M]: `python3 tools/native/s2wi.py --all
--jobs 2` (4 min 40 s): `report.json` ok, 0 problems (the 214 frames
injected with both fills and chained, every screen equal, 0 stray writes
with `pl_poll`'s judged), the four planted bugs caught with the same
first failures; `WIW` 5,116 of 6,656 B (`pl_poll` 554, own 1,924 of
1,950). `wip_test_m11_s2wi`: 9 tests OK, also on Python 3.9.6.

## The wave 8 integration (2026-10-02)

`tools/native/s2wi.py`'s `store_records` published its cache as an empty
list and then filled it, so a job thread that came second ran with part
of the 2D store (a crash stop with status `$80`, or a run away: wave 6's
unexplained `s2wi` batch failure, and `s2fin`'s in wave 8). The list is
built whole and published in one assignment now; the part's test
`test_the_store_is_never_seen_half_read` fails on the old code
(`docs/SCREENS.md` 8.12).
