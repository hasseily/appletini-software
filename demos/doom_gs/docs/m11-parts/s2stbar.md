# Milestone 11, part `s2stbar`: the status bar and the face

Part `s2stbar` of wave 4 ([`docs/SCREENS.md`](../SCREENS.md) 7.3), written
from upstream's `src/iigs/st_stuff65.s` (`ST_Init`'s state, `ST_Start`
with `ST_initData` and `ST_createWidgets`, `ST_Ticker` but `M_Random`:
`readyNum`, the key boxes, `updateFace`, `painOffset`, `muchPain`,
`ouch`, `turnHead`, `st_oldhealth`; `ST_Drawer`: `refresh`, `diffDraw`,
`ST_diffNum`, `ST_diffIcon`, `restoreRect`, `STlib_updateMultIcon`,
`STlib_drawNum`, the percent signs, `stHide`) and `i_viigs65.s`
(`I_RestoreStatusRect`, `I_SaveStatusBackground`, `V_DrawRaw`'s status
bar). 2026-10-01. Labels as in `NATIVE.md`: [M] measured, [R file:line]
read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `src/native/s2_st.s` | P2DW's status bar (1,974 B, of which 114 B are a stand-in copy of `s2_draw`'s `markpatch`: S2STBAR-5): `st_drawer` (`ST_Drawer`: the menu's `stHide`, the whole bar, or the widgets that changed; the band published) and `s2_rows` (each band row's nibble table pages from its SCB, the palettes' tables fetched into P2DW's eight slots the first time a frame needs them; for `s2hud` too) |
| `src/native/s2t_st.s` | The tic side (886 B): `st_ticker` (A = `M_Random`'s value), `st_start`, `st_init` (`ST_Init`'s state, at boot) |
| `src/native/s2_stt.s` | Test glue (not the game): `stx_case`, a staged frame into its places, `st_drawer` in the cost phase 30, P2DW's own block fetched and written back as the frame does |
| `src/native/s2t_stt.s` | Test glue (not the game): `stt_run` (staged tics through `st_ticker`, `st_start` or `st_init`, results into RamWorks), the callback `s2t_pos` from a table, the scratch block `st_sb` |
| `src/native/m11/s2stbar.mk` | `gen/s2stbar.inc`, the images `s2sb` (P2DW's room: `s2_st.s`, part s2draw's `s2_draw.s` and `s2_pub.s`, `s2_beginstub.s`, the glue) and `s2st` (the tic side with the game's math, `math.s` without `RENDER`, for `pta3`) into `build/native/m11/s2stbar/` (`make -f m11.mk part P=s2stbar`) |
| `tools/native/s2stmodel.py` | The host model of upstream's rules (16-bit arithmetic and quirks): the ticker, `ST_Start`, the drawer on a back buffer with upstream's marks, its draws (the coverage table) |
| `tools/native/s2stbar.py` | The capture `pos` (turnHead's positions and `ST_Start`, a call log of its own), the model against ref816, the synthetic truth by ref816 `--call`, the native runs, the chain, the coverage table, the timing, the planted bugs, `--inc`, `--cfg-tic`, `--all` (the checkpoint, `report.json`) |
| `tests/wip_test_m11_s2stbar.py` | 13 tests (2.1) |

Build output: `build/native/m11/s2stbar/` (the images, `pos/` the capture,
`synth/` the `--call` truth, `report.json`). Every run's directory is a
`tempfile` directory there, deleted after it.

### 1.1 The design as built

**The bar's rows are kept as published (`STBUF`).** Upstream draws into a
back buffer that persists between frames; `ST_diffNum` and `ST_diffIcon`
restore a rectangle from `STCACHE` and draw over the back buffer's other
bytes, and `showDirty` publishes each row's marked range `[DRB, DRE)`,
which spans every byte between two widgets of the row. W is reloaded
every frame, so P2DW keeps upstream's back buffer's rows 168-199 in
S2STATE (`STBUF`, 5,120 B, request S2STBAR-2): it equals the screen's
rows whenever `ST_REFRESHED` is 1. A frame with changes runs the widgets
twice: a marking pass (each restore's and patch's rectangle, upstream's
marks, through `s2_mark` and a copy of `markpatch`), then each marked
row's bytes from `STBUF` with the rows' nibble tables, then the drawing
pass (the restores from `STCACHE` by `s2_rect`, the patches by
`s2_vpatch`, upstream's order and arithmetic), then the marked bytes back
into `STBUF` and the band published. A frame with nothing changed fetches
and publishes nothing. A refresh draws `STBAR` (`s2_raw`) and `STARMS`,
saves the band into `STCACHE`, draws every widget, puts the band into
`STBUF` and publishes it.

**The tic side writes the card.** `ST_FACEINDEX` .. `ST_REFRESHED` as
`s2layout.S2T` has them, and two bytes more (request S2STBAR-1):
`ST_READY`, `W_READY`'s value pointer as `readyNum` sets it at the tic (an
ammo index, `$FE` LARGEAMMO, `$FF` the frame rate), and `ST_RUNNING`
(`ST_Start`'s `ST_Stop`). `st_start` writes P2DW's state in S2STATE by
`far_put` (the widgets' old values, `st_palette`) and `newpal` 0 in
PALST (request S2PAL-9). `readyNum` reads `P_FPS` (the fps cheat) from
P2DW's state block in S2STATE, one byte by `far_get` a tic.

**The interface.**

| Entry | In | Out, writes |
| --- | --- | --- |
| `st_drawer` (P2DW, after `st_palette`, before the HUD) | PALST in W (`$BC00`, its SCBs), P2DW's own block in W (`$BF00`), the card, the player, `G_MENUACTIVE`; zero page `S2_*` | the band published (rows 168-199; with the menu's `stHide` also rows 0-9); `P_OLD*`, `P_TXTSHOWN`, `P_MHID`, `ST_REFRESHED`, `HU_ON`; `STCACHE`, `STBUF` |
| `s2_rows` | A, X: band rows `[A, X)`, `S2_Y0`, PALST's SCBs | `ROWL`, `ROWR`; slots fetched (`st_nibs` counts) |
| `st_ticker` (tic) | A = `M_Random`'s value; the player, the card | the card's status bar bytes; calls `s2t_pos`, `pta3`, `sdiv16`, `far_get` |
| `st_start` (tic) | the player, the card | the card; S2STATE: P2DW's `P_OLDREADY` .. `P_STPALETTE`, PALST's `PS_NEWPAL` (after the first) |
| `st_init` (boot) | | the card's status bar block |
| `s2t_pos` (milestone 10's callback) | A, X a mobj handle | `GT_POS`..+11: its x, y, angle (4 bytes each); may change `GT_*` |

`st_ticker`, `st_start` keep what they need across the callback in
`st_sb` (32 bytes, the module's scratch block); they use no zero page of
their own (FA_*, the math block, `GT_POS`).

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
df -h /System/Volumes/Data                          # 69 GB free
make -C src/native -f m11.mk part P=s2stbar ROOT=$PWD \
    -o $PWD/build/native/m11/shared/gen/s2.inc ...  # see open problem 1
python3 tools/native/s2stbar.py --capture --jobs 2  # 3 min, once
python3 tools/native/s2stbar.py --all --jobs 2      # the checkpoint
python3 tools/testpar.py tests/wip_test_m11_s2stbar.py
```

Results [M, 2026-10-01]: `report.json` `ok`, 0 problems (22 min with 2 jobs; `build/` +7.3 MB); the checkpoint's runs
are demo3, newgame, tour and `stbar.script` with part s2cap's five other
level runs (menus, palette, automap, finale, signs), and the synthetic
cases.

| Item | Result |
| --- | --- |
| The capture `pos` | the nine runs again on ref816 with a call log of `ST_Ticker` (as part s2cap logs it), `R_PointToAngle3` and `ST_Start`: 4,893 `ST_Ticker`, each paired with s2cap's by the SHA-256 of its entry memory (all equal), 89 `turnHead`s (demo3), 24 `ST_Start`s; 3 min with 2 jobs, 81 KB |
| The model, tics | every `ST_Ticker` of the nine runs (4,893: demo3 2,135, newgame 513, tour 428, stbar 827, menus 164, palette 394, automap 372, finale 23, signs 37): the state after it equal to the reference's, and turnHead's `R_PointToAngle3` equal to the reference's result; 3 calls where a script's poke landed inside the call take the player at its return (ST_Ticker writes none of it) |
| The model, frames | every level frame's `ST_Drawer` (1,224: 1,206 diffDraw, 18 refreshes): the screen's rows 168-199, `STCACHE`, the widgets' old values, `st_refreshed` and the marks of rows 168-199 equal to the reference's (in the 92 full-automap frames the status bar's marks inside the reference's, which also hold `AM_Drawer`'s); 36 frames of stbar.script whose poke landed inside display before ST_Drawer take the poked field from PDF (each such field must be what its widget shows after the frame) |
| Synthetic (ref816 `--call` on part s2draw's base state) | 77 frames (42 drawing every number widget's digits at each place, every face and restoring the one before, each key, each arm gray and yellow; 28 of the ready number; the edges: negative numbers, past 999, -1994, LARGEAMMO, the frame rate; a refresh from STCACHE and one from the raw bar; the menu's stHide with message_on and VW_MHID 0 and 1) and 96 tics (every path of updateFace at its edges, muchPain's overflow, the turned head at 16 directions and 3 angles, readyNum's sources, the key boxes, ST_Start with and without ST_Stop, a fist's NOAMMO pointer): the model equal on all |
| The native tic side (`s2st`) | 9,978 cases: the 4,893 tics and the 96 synthetic, both fills, 32 a2vm runs: every status bar byte of the card after `st_ticker` or `st_start` equal to the reference's, and `st_start`'s P2DW state and newpal in S2STATE; 0 stray writes; stack 19 B |
| The native drawer (`s2sb`) | 5,204 cases: the 1,224 level frames and the 77 synthetic, both fills, plain and with every byte of rows 168-199 the reference's status bar marked poisoned (rows 0-9 too for the stHide that clears them), 400 a2vm runs: the screen's rows 168-199 equal to the reference's (but X-ST1: the ready number of 37 frames of stbar.script), the bytes published equal to the reference's marks row by row, `STCACHE`, `STBUF` (the screen's rows), the old values and `ST_REFRESHED` equal; 0 stray writes; stack 21 B |
| Chained | demo3's 534 level frames from the first frame's injected state only (each later frame: the game's inputs and the tic side's card bytes from the reference; P2DW's state, STCACHE, STBUF, the screen's rows and ST_REFRESHED the native code's), 34 a2vm runs: every frame equal |
| The coverage table | 380 of 380: each number widget's digits 0-9 at places 1 and 2 and 1-9 at place 3 (11 widgets), the 42 faces, each key, each arm gray and yellow, both percent signs, STARMS, STBAR, drawn in compared frames (the model's draws); a combination never drawn fails |
| The menu's stHide | 4 synthetic frames (message_on, VW_MHID): rows 168-199 black and published, the strip's rows 0-9 cleared and published when either is set, message_on, iigs_textShown's first slot and VW_MHID as upstream's; no capture reaches it (a menu opened in a level makes display call uiDisplay instead [R `d_main65.s:513-514`]) |
| Nibble-table fetches a frame | of the 5,204 native cases: none 3,656 (nothing changed), 2 tables 212, 3 tables 32, 5 tables 364, all 8 940 (the face, the refreshes, the synthetic frames) |
| `tests/test_sound_*` | unchanged and green (this part touches no sound file) |


### 2.1 The tests

`tests/wip_test_m11_s2stbar.py` (13 tests, 115 s with 2 jobs; also OK on Python 3.9.6 with `-W error::ResourceWarning`, 147 s):
the model's rules on hand-made values (painOffset, muchPain with its
overflow, drawNum's digits, clamps and LARGEAMMO), the coverage
universe (no build needed); the include's places and stand-ins; the
model against every tic of demo3 and newgame and every frame of demo3,
newgame and stbar.script; the synthetic frames and tics; the coverage
table over every run; the native tic side on newgame and the synthetic
tics (both fills); the native drawer on newgame (`$A5` plain, `$5A`
poisoned) and a quarter of the synthetic frames with the edges, the
refreshes and stHide (both fills, poisoned); demo3's first 64 frames
chained; the sizes; the six planted bugs on the synthetic cases. Without
`build/` the three model-rule tests run and the others skip naming what
is missing.

## 3. Planted bugs (each in a scratch copy of the sources)

| Bug | Caught by | The first failure [M] |
| --- | --- | --- |
| painOffset's cache not refreshed (a health change keeps the old offset: `bra @done`) | the synthetic tics (73 of the full run) | `synth:attacked-50 (fill A5): ST_FACEINDEX 05, ref 15` |
| The evil grin on any weapon change (no bonus needed) | the synthetic tics (4) | `synth:grin-0-1 (fill A5): ST_FACEINDEX 06, ref 28` |
| The turned head's sides swapped | the synthetic tics (37) | `synth:attacked-80 (fill A5): ST_FACEINDEX 03, ref 04` |
| diffNum restoring the old number's width (its digits) instead of the widget's 3 | the synthetic and newgame frames (21): the bytes published | `synth ready-00 (fill A5): published [(74, 86), (15, 118), (15, 123)], the marks [(74, 86), (1, 118), (1, 123)]` |
| drawNum of LARGEAMMO (its digits drawn) | the synthetic frames (16) | `synth glyphs-00 (fill A5): the screen at $8AE3: $33, ref $99` |
| The ammo rows in ammoRows' wrong order (the first two swapped) | the synthetic and newgame frames (154) | `synth glyphs-00 (fill A5): the screen at $8CB7: $44, ref $EE` |

The checkpoint runs each on the synthetic cases and newgame's frames
(`--plants`, `--all`); the test on the synthetic tics and six synthetic
frames. The development found three more on its own way (each fixed,
each caught by these checks): the tic glue copying one byte of the
player (`ldx #147` .. `bpl`), the turned head's borrow lost between the
bytes of dx and dy (`cpx #8` inside the subtraction), and the
tantoangle planes missing from the test machine (pta3's angles wrong).

## 4. Sizes against the budget

| Item | Size [M] | Budget |
| --- | ---: | ---: |
| `s2_st` in P2DW (code 1,742, tables 192, data 40) | 1,974 B | 2,000 B |
| of which the stand-in `markp` (S2STBAR-5) | 114 B | |
| `s2t_st` (tic side) | 886 B | 900 B |
| P2DW's room with `s2_draw`, `s2_pub` and the test glue | 3,743 B | 7,424 B |
| card | 2 B more (S2STBAR-1): the S2T block 61 of 61 B | 61 B |
| S2STATE | 5,120 B (`STBUF`, S2STBAR-2) | bank 104's free 42,768 B |

## 5. Timing (SCREENS.md 6.4)

`python3 tools/native/s2stbar.py --timing` [M] (in `--all`): each frame
alone in its run, `st_drawer` in the cost phase 30 (its fetches of
STBUF, STCACHE and the nibble tables, the drawing, the publish with its
drain), six frames a kind of demo3 and the tour:

| Frame | Nibble tables | `f121` median / worst ms | `fastpath` median / worst ms |
| --- | ---: | --- | --- |
| Nothing changed | 0 | 0.06 / 0.06 | 0.06 / 0.06 |
| The face changed (alone) | 8 | 6.58 / 6.59 | 5.10 / 5.12 |
| Other widgets (numbers, with or without the face) | 5-8 | 8.04 / 11.32 | 6.11 / 8.79 |
| A full refresh | 8 | 44.43 / 44.43 | 35.41 / 35.41 |

The tic side (`--timing`'s `tic_timing`, the phase 30 around each call):
`st_ticker` 16.6 µs a call on `f121` (10.2 `fastpath`) over demo3's first
255 tics; 60.9 µs (48.1) for a tic with the turned head (two `s2t_pos`
calls of the stand-in, `pta3`).

Where a face change's 6.6 ms go [A on M: part s2draw's 4.17 µs a patch
pixel, s2pal's 0.25 ms a table]: the 8 nibble tables (the face spans the
bar's 32 rows: 8 palettes) about 2 ms, its 700-odd pixels about 3 ms,
the old face's restore, STBUF's 30 rows in and out and the publish the
rest. A refresh draws the raw bar through pairByte (10,240 bytes), every
widget (about 3,500 pixels) and publishes 5,120 bytes. Levers, for the
performance pass: L2 (pre-rendered glyphs) for the pixels; the refresh's
STCACHE fast path (upstream's `V_DrawRaw` copies STCACHE when it holds
the bar [R `i_viigs65.s:1316-1336`]: one state byte, about 15 ms a
refresh); the nibble tables kept in W across frames (P2DW's load would
then carry them, or a cache of the last frame's slots).

## 6. Requests (for the integrator; the stand-ins are marked `STANDIN` in the generated `s2stbar.inc`)

### S2STBAR-1. `tools/native/s2layout.py`: two card bytes, the ready number's source and `st_running`

**Evidence.** `readyNum` chooses `W_READY`'s value pointer at the tic
[R `st_stuff65.s:400-418`] (the fps cheat, LARGEAMMO for a weapon of no
ammo, else the ammo of the ready weapon), and `ST_createWidgets` sets it
without the NOAMMO check [R `:245-254`]: a fist after `ST_Start` shows
`ammo[5]`, which is `maxammo[1]`, until the next tic. The field map drops
the pointer ("the native widget names its field"), which loses both.
`ST_Start` calls `I_SetPalette(0)` only when `st_running` [R `:217-222`],
which the block lacks. **Stand-in.** `ST_READY = S2T_BASE + 59`,
`ST_RUNNING = S2T_BASE + 60` (the block's two free bytes). **What.** In
`S2T_FIELDS`, after `('LS_ANGLE', 4)`: `('ST_READY', 1), ('ST_RUNNING',
1)` (the block 61 of 61 B; no address moves). In `_stbar()`'s field map,
replace the dropped `W_READY+8` with `_f(s, st + 'W_READY+8', 2,
'readysrc', 'card', 'ST_READY')` and add `_f(s, st + 'st_running', 2,
'byte', 'card', 'ST_RUNNING')`; `s2state.encode` gains `readysrc`: the
near pointer `&ammo[k]` (`_g_player + OFS_PL_AMMO + 2k`, k 0-255) as k,
`&largeammo` as `$FE`, `&_g_fps_framerate` as `$FF` (`s2stbar.Ref.ready_of`
does it). SCREENS.md 4.4's row `$E443-$E47F`: "the status bar's (26 B)",
"61 of 61 B".

### S2STBAR-2. `tools/native/s2layout.py`: S2STATE's `SS_STBUF`

**Evidence.** 1.1 above: the published bytes of a row span other
widgets' bytes, which only upstream's persistent back buffer holds.
**Stand-in.** `SS_STBUF = $6120` (after `SS_SIGN`). **What.** Append
`('SS_STBUF', 5120)` to `S2STATE_FIELDS`; SCREENS.md 4.5's row 104:
"`STCACHE` (5,120 B), `STBUF` (the bar's rows as published, 5,120 B)",
and 1.5.1's `ST_Drawer` row: "`restoreRect` is a `far_get` of the
rectangle's rows from `STCACHE`; the frame's marked bytes from `STBUF`".

### S2STBAR-3. `tools/native/s2layout.py`: two places in P2DW's state block

**Evidence.** `stHide` reads and sets `VW_MHID` [R `st_stuff65.s:
1193-1199`; `viewwin.inc:43`], and the ready number shows
`_g_fps_framerate` when the fps cheat is on [R `:401-403`]; neither has a
native place. **Stand-in.** `P_MHID = $BFFC`, `P_FPSRATE = $BFFD` (2).
**What.** In `_stbar()`'s state fields (after `P_STPALETTE`, or at the
block's end): `('VW_MHID', 2, 'byte', 'state', 'P_MHID')` and
`('d_main65.s:_g_fps_framerate', 2, 'word', 'state', 'P_FPSRATE')`. The
frame rate is the second half's to compute (open problem 4).

### S2STBAR-4. Milestone 10 (request R4, made precise): the tic side's linkage

- `st_tick` returns `M_Random`'s value in A [R `src/native/game/flow/
  gwi.s:623-630`]; the `ST_Ticker` hook then calls `st_ticker` with it.
  The `ST_Start` hook calls `st_start`; the boot calls `st_init` once.
- `s2t_pos`: A, X a mobj handle; out: x, y, angle at `GT_0`-`GT_11` (4
  bytes each, little-endian; `GT_POS` in the stand-in is `GT_0`, `$5C`).
  It may change any `GT_*`, A, X, Y; `st_ticker` keeps what it needs in
  `st_sb`.
- `st_sb`: the module's 32-byte scratch block (`.import st_sb`; the
  integrator defines it as glayout's `SB_` of the module).
- `pta3` (`R_PointToAngle3`) and `sdiv16` in the tic image: `math.s`
  with `-D RENDER` (the tic image's `math-r.o` today) has no `pta3`; the
  game's own `R_PointToAngle3` calls (`P_DamageMobj`'s thrust, GAME.md
  2.4's `damage`) need it too. The test image links `math.s` without
  `RENDER`.
- The segments `S2TCODE` (code) and `S2TRODATA` (`st_wammo`, 11 B), in
  the core or a group; `far_get`, `far_put` (the far layer, card).

### S2STBAR-5. `src/native/s2_draw.s` (part s2draw): export `markpatch`

**Evidence.** The marking pass (1.1) needs `markPatch` of a patch without
drawing it; `s2_draw.s`'s `markpatch` is local. **Stand-in.** `markp` in
`s2_st.s`, a copy (114 B). **What.** In `s2_draw.s`: `.export s2_markp`
and the label `s2_markp = markpatch` with its contract in the header ("the
rectangle of S2_X, S2_Y (offsets applied), S2_W, S2_H clipped to the
screen and marked: markPatch"); then `s2_st.s` imports it and `markp`
goes (s2_st 1,860 B).

### S2STBAR-6. The frame driver (request R7) and part `s2hud`

- P2DW's own state block (256 B, `SS_P2DW` ↔ W `$BF00`) is fetched with
  PALST at the frame's start and written back at its end (`s2_palget`,
  `s2_palput` move PALST only): the test glue `s2_stt.s` does it as the
  frame should.
- The order in a level frame: `s2_palget`, `s2_viewpal`,
  `s2_stripearly`, `st_palette`, `st_drawer`, the HUD, `s2_finish`,
  `s2_palput`. `st_drawer` leaves `S2_BAND`, `S2_Y0`, `S2_Y1` at the bar's
  band and the marks clear; `s2hud` sets its own band and may call
  `s2_rows` (the slots of the frame are shared: `st_nslot`, `st_slotpal`).
- `st_init` at boot (SCREENS.md 1.5.1's table puts `st_init` in P2DW:
  it is the tic side's, since it writes the card only).

### S2STBAR-7. For part `s2cap`: `stbar.script`'s ready weapon 10

After its "health 0" poke the reference's player gets `readyweapon` 10
(`wp_nochange`) from its 679th `ST_Ticker` on [M: `pos/stbar`], so
`readyNum` reads `weaponinfo` past its 9 entries (the ammo index 133) and
the ready number shows a word of upstream's memory past the player. The
native tic side gives the same index (`st_wammo` keeps the release's two
bytes after the table), but the native drawer cannot show upstream's
word: 37 frames of the run have the ready number excluded (X-ST1,
counted). Poking `pendingweapon` with the health, or the health back
before the weapon lowers, would avoid the state.

## 7. Decisions where the design left a choice

- **STBUF, the bar's rows as published** (1.1), not a recomposition
  from STCACHE and the widgets: upstream's published range of a row spans
  every byte between its first and last mark, and a restore can wipe a
  neighbour's pixel that upstream does not draw again, so only upstream's
  back buffer's bytes are exact. Its cost is the marked bytes in and out
  (none in a frame with nothing changed). The injection puts the screen's
  rows before the frame into STBUF (the back buffer equals the screen
  whenever `st_refreshed` is 1); the chain carries it natively.
- **A marking pass before the drawing pass**: the marks a frame will make
  are known only by running its widgets; the marking pass runs the same
  code with the restores and patches marking only (`markp`, `s2_mark`).
- **The refresh always draws the raw bar and STARMS** (upstream copies
  STCACHE when `stcachenum` is the bar's): the same bytes (the raw bar
  and the idempotent STARMS over it), no state byte; 18 refreshes of the
  captures, cached and not, and two synthetic ones equal.
- **The refresh's widget order** is diffDraw's (health, its percent,
  armor, its percent) where upstream's refresh draws health, armor, then
  both percents [R `st_stuff65.s:765-781`]: the armor's patches and the
  health's percent sign share no byte, so the bytes are the same (one
  sequence table, 23 B less); the 20 refreshes equal.
- **The ready number's source at the tic** (ST_READY, S2STBAR-1), as
  upstream's pointer, with ST_createWidgets' missing NOAMMO check; the
  fps cheat's `P_FPS` read from S2STATE by the tic side.
- **st_wammo keeps 11 entries**: weaponinfo's 9 and the two words after
  it that readyNum reads for ready weapon 9 and 10 (the release's bytes),
  so the tic side equals upstream's for stbar.script's `wp_nochange`.
- **Pokes inside a call or a frame.** ref816's script pokes land at its
  own tic boundary, which can fall inside `ST_Ticker` (3 calls) or inside
  display before `ST_Drawer` (36 frames of stbar.script): the tic takes
  the player at its return (ST_Ticker writes none of it); the frame takes
  a field ST_Drawer reads from PDF only when its widget shows that value
  after the frame (both captured values; anything else fails).
- **The coverage table** counts the model's draws in compared frames; the
  model is checked against ref816 on every one of them, and the native
  against ref816 too, so a draw counted is a draw equal.
- **The synthetic truth** is ref816 `--call` of `ST_Drawer`, `ST_Ticker`
  and `ST_Start` on part s2draw's base state with the inputs poked (the
  attacker a fake mobj in the back buffer, which ST_Ticker never reads).
- **The full-automap frames' poison**: AM_Drawer marks rows 168-169 when
  it redraws a full list (part s2amap's); in those frames the poison is
  the status bar's own marks (the model's, checked inside the
  reference's): 1 frame of automap.script.

## 8. Open problems

1. **`s2layout.check()` fails on milestone 10's work in progress**:
   `src/native/game/flow/gflow.s:893` stores `2 * FL_PH_RESUME` (31) to
   `PHASE`, the platform's phase (and `:881` 30, this half's 2D phase),
   so every m11 build fails to regenerate `s2.inc` ("writes the phase 31,
   the platform's"). The includes it would write are unchanged (checked
   by `s2stbar.shared_old`), so this part builds with make's `-o` for the
   five shared includes. For the integrators (milestone 10's and this
   half's): SCREENS.md 4.8 gives 30 and 31 to this half.
2. **X-ST1**: 37 frames of stbar.script show the ready number of a ready
   weapon out of range (S2STBAR-7); the ready number's rectangle and old
   value are not compared there, counted in the report.
3. **`pta3` in the tic image** (S2STBAR-4): the tic image's math is the
   render build, without `R_PointToAngle3`.
4. **The frame rate** (`P_FPSRATE`, S2STBAR-3): nothing computes it yet
   (the fps cheat is the second half's); the synthetic frame with the
   cheat on poked it.
5. **Requests S2STBAR-1 to -5 are stand-ins** until the integrator
   applies them (`s2stbar.inc`'s `STANDIN` lines; `markp` in `s2_st.s`).
   `s2_st` is 1,974 of 2,000 B with the 114 B copy of `markpatch`.
6. **Refresh 44 ms on `f121`** (5 above): levers listed, not taken.
7. The part took much longer than its 1.5 hours.

## 9. The wave 4 integration (2026-10-01)

What the integrator did with each request (`docs/SCREENS.md` 8.8, "Wave
4 as integrated"):

| Request | Outcome |
| --- | --- |
| S2STBAR-1 | Applied as written: `S2T_FIELDS` ends with `ST_READY`, `ST_RUNNING` (61 of 61 B, the stand-ins' addresses); the field map's `W_READY+8` is `readysrc` → `ST_READY` and `st_running` a byte → `ST_RUNNING`; `s2state` has the encoding `readysrc` (`readysrc_code`, `readysrc_ptr`). `W_READY`'s pointer is NULL before the first `ST_Start` (in the frames before a level: 1,039 of demo3's, 29 to 123 in the other runs), which no code had: it is `$FD` (`s2state.READY_NONE`; ammo indexes stay below it), and `st_init` now writes `$FD` there instead of 0 (`s2t_st` 888 B); `Ref.ready_of`, `ready_code` know it. So every captured frame injects and reads back with no unfit value |
| S2STBAR-2 | Applied: `('SS_STBUF', 5120)` in `S2STATE_FIELDS` (at `$6120`, the stand-in's place); SCREENS.md 1.5.1, 4.5 |
| S2STBAR-3 | Applied: `VW_MHID` → `P_MHID` (a byte) and `_g_fps_framerate` → `P_FPSRATE` (a word) in `_stbar()`'s state fields; allocated with the field map at `$BF2C`, `$BF2D` (the stand-ins were `$BFFC`, `$BFFD`); `VW_MHID` is not in a unit's near data, so `s2cap` dumps it (`STATE_EXTRA`) and the cases were captured again; `frame_case` now reads the captured value (it was 0) |
| S2STBAR-4 | Recorded in `design.md` R4 items 1-4 for milestone 10 (`pta3` in the tic image's math is item 4). `GT_POS` stays a stand-in |
| S2STBAR-5 | Applied: `s2_draw.s` exports `s2_markp` (a label at `markpatch`, its contract in the header); `s2_st.s` imports it, `markp` is gone: `s2_st` 1,860 B |
| S2STBAR-6 | Recorded in `design.md` R7 item 7 |
| S2STBAR-7 | Not applied: X-ST1 stays named and counted. The script change would move `stbar.script`'s dead-face frames and part `s2cap`'s goals, for 37 frames whose ready number upstream draws from memory past the player; the owner's or a later `s2cap` change |

Also: `make_part()`'s `shared_old()` (`make -o` with `check()` bypassed)
is removed: the check passes again (S2HUD-4 as settled), and a failing
check now fails the build. `sizes()` no longer reports the stand-in.

## The final integration of the first half (2026-10-02)

`s2sb` links part s2pal's `s2_pal.o` in place of `s2_beginstub.s` (`s2_stt.s` exports `s2_palst`); its `s2_begin` never runs there (the frame's `s2_begun` is set), and the write log now gives `s2_pal` an empty allowed set: 0 stray writes over 5,204 cases and the 534 chained frames. `s2sb` is 4,088 of 7,424 B. The test is `tests/test_m11_s2stbar.py`. (`docs/SCREENS.md` 8.13.)
