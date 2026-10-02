# Milestone 11, part `s2pal`: palettes, tints, gamma, SCBs, the finish, the wipe, PALW

Part `s2pal` of wave 3 ([`docs/SCREENS.md`](../SCREENS.md) 7.3), written
from upstream's `src/iigs/i_viigs65.s` (`I_SetPalette`,
`I_ReloadPalette`, `I_FinishUpdate`/`D_Wipe` without `showDirty`,
`I_ApplyColors`, `newColors`, `pictureColors`, `I_ViewPalette`,
`I_MessageStrip`, `gammaColor`, `buildTints`, `levelPalettes`,
`tintRecords`, `tintColors`, `buildNibtab`, `setRows`, `rowPalette`,
`enterLevelMode`, `drawPicture`'s palette part), `st_stuff65.s`
(`ST_doPaletteStuff`) and `d_main65.s` (`stripEarly`'s palette).
2026-10-01. Labels as in `NATIVE.md`: [M] measured, [R file:line] read,
[A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `src/native/s2_pal.s` | The shared object `s2_pal` (680 B): `s2_palget`/`s2_palput` (PALST between W and `S2STATE`'s `SS_PALST`), `s2_begin` (the black step when a picture is new, then `newColors`: a new tint, the SCBs, the level's TINTPAL row), `s2_finish` (`s2_begin` if no band came, `pictureColors`, `s2_begun` cleared), `s2_setpal` (`I_SetPalette`), `s2_reload` (`I_ReloadPalette`: C = 1 when a level's tints must be rebuilt by PALW), `s2_viewpal` (`I_ViewPalette`), `s2_strip` (`I_MessageStrip`'s palette; C = 1 when the strip's rows must be cleared), `s2_stripearly` (`stripEarly`: A = `DD_PAUSED`, `message_new` from the card's `HU_NEW`), `s2_setrows` (`setRows` and `rowPalette`'s SCB), `st_palette` (`ST_doPaletteStuff`, upstream's 16-bit arithmetic, into `P_STPALETTE` and `newpal`) |
| `src/native/s2_nib.s` | The shared object `s2_nib` (390 B): `s2_nibtab` (`buildNibtab` into `S2NIB`), `s2_gamma` (`gammaColor`), `s2_picpal` (`drawPicture`'s palette part: the rows, the 16 palettes with gamma, `palettecount`, the 16 nibble tables; nothing when the picture is on the screen) |
| `src/native/s2_palw.s` | The image `PALW` (443 B own): `palw_level` (`buildTints` into `S2PAL`'s TINTPAL, the nibble tables of palettes 0-11, the view's and the status bar's rows, no picture, the colours due), `palw_gamma` (a level's `I_ReloadPalette`: the tints again, the colours due); `palw_getst`/`palw_putst` (PALST, for the test around `s2_picpal`) |
| `src/native/s2_palt.s` | The test glue (not the game), assembled twice: `s2pp` in `P2DW`'s room (`s2_pal`, `s2_pub`), `s2pf` in `WIW`'s (`s2_pal`, `s2_nib`, `s2_pub`): `s2y_case` (a staged case into its places, then `s2_palget`, the frame's calls, a band of rows 100-101 published), `s2y_end` (`s2_finish`, `s2_palput`) |
| `src/native/m11/s2pal.mk` | `gen/s2pal.inc`, `palw`, `s2pp`, `s2pf` into `build/native/m11/s2pal/` (`make -f m11.mk part P=s2pal`) |
| `tools/native/s2palmodel.py` | The host model of upstream's rules: the palette state, the screen's `$9D00-$9FFF`, TINTPAL, NIBTAB, every routine above, every screen store in order, each branch taken |
| `tools/native/s2pal.py` | The checks: the model against `s2cap`'s cases (display's palette calls emulated from the frame's start, [R `d_main65.s:377-558`]); `nibcap` (ref816 dumps of NIBTAB, TINTPAL and the palette state after each `I_SetLevelPalette`, `drawPicture` and `I_MenuPaletteBack`); the native frames, PALW and `s2_picpal` on a2vm; `ST_doPaletteStuff` by ref816 `--call`; the timing; the planted bugs; `--inc` (the generated include); `--all` (the checkpoint, `report.json`) |
| `tests/wip_test_m11_s2pal.py` | 14 tests (below) |

Build output: `build/native/m11/s2pal/` (1.7 MB: the images, `nib/` the
nibble dumps of nine runs, 0.5 MB, `synth/` the `--call` truth,
`report.json`). Every run's directory is a `tempfile` directory there,
deleted after it.

### 1.1 The interface

**PALST** (upstream's palette state, SCREENS.md 1.3) is at `s2_palst` in
W, which each image exports (`P2DW`, `WIW`, `FINW`, `PALW`: `PALST_W`
`$BC00`), and `s2_begun = s2_palst + PS_BEGUN` (S2DRAW-5). `PS_PALCOUNT`
is natively a flag (upstream's `palettecount` is 0 or 256 words [R
`i_viigs65.s:1275`, `:2124`, `:2187`]: request S2PAL-5); `newpal`'s "no
change" is upstream's 100 [R `:66`]. `PS_TXTINV` (after `PS_BEGUN`,
request S2PAL-2) is upstream's `textInvalidate` [R `:1891-1897`]:
`setRows`, `buildNibtab` and `drawPicture` set it; `s2hud` clears its
text slots and it.

**The frame's calls**, in display's order [R `d_main65.s:377-558`], for
the frame driver (R7) and the images' glue:

| Frame | Calls |
| --- | --- |
| Every frame image | `s2_palget` first, `s2_finish` then `s2_palput` last; `s2_publish` calls `s2_begin` before its first band |
| A level frame, not paused | `s2_viewpal` (0, or `AMAP_PAL` 11 in a full-automap frame); when the view is drawn, `s2_stripearly` (A = `DD_PAUSED`; C = 1: `s2hud` clears rows 0-9 of its strip band and marks them, `iigs_textShown`'s first slot 0); `st_palette` (in `P2DW`) |
| A level left (gamestate not a level, `oldgamestate` a level) | `s2_setpal` with A = 0 |
| A picture drawn (pages, intermission, finale) | `s2_picpal` (A, X = the lump, `S2_PBANK:S2_PADDR` = its bytes from offset 32,000) before its bands, in `WIW`/`FINW` |
| A level's first frame | `PALW`'s `palw_level` (after milestone 9's load: `GSVIEWn` in `LVC`; `GSSTAT`, `GSOVL` at `S2PAL`'s places) |
| The gamma changed | `s2_reload`; C = 1: `PALW`'s `palw_gamma` |

`I_ApplyColors` has no native call: its colours go out with `s2_begin`
(named difference D1, SCREENS.md 1.3).

**Places**: TINTPAL, the 16 nibble tables `S2NIB`, `GSSTAT`, `GSOVL` and
`GRAYMAP` in bank `S2PAL` (106), zero page `$78-$7F`, page 1
`$0100-$017F` (requests S2PAL-1, -3, -4; stand-ins in the generated
`s2pal.inc`).

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
df -h /System/Volumes/Data                           # 74 GB free
make -C src/native -f m11.mk part P=s2pal            # no warning
python3 tools/native/s2layout.py --check
python3 tools/native/s2pal.py --all --jobs 2         # 4 min 20 s
python3 tools/testpar.py tests/wip_test_m11_s2pal.py # 14 tests, 84 s
```

Results [M, 2026-10-01]: `report.json` `ok`, 0 problems. The runs are
the checkpoint's four (demo3, newgame, tour, palette.script) and `s2cap`'s
other five screen runs (automap, menus, stbar, finale, signs).

| Item | Result |
| --- | --- |
| The model against ref816, every frame | 9 runs, 3,062 frames and events (3,013 and 49): 1,652 with an `I_FinishUpdate`, whose palette state at its entry, `st_palette`, and SCBs and palettes after it equal ref816's; 1,410 without one (nothing published), their SCBs and palettes unchanged; 0 problems. 127 of the 1,652 are another part's palette work (96 menu frames, 22 closes of the menu, 9 loading screens: `s2menu1`'s and `s2fin`'s `I_MenuPalette`, `I_MenuPaletteBack`, `F_LoadScreen`): the finish alone from the state at `I_FinishUpdate`'s entry. 4 frames of palette.script and stbar.script read the player's fields at `ST_doPaletteStuff` after a script's poke that lands inside display's frame (the inputs are the reference's at the call) |
| The wipe's two steps | 63 new pictures (menus' open and close, pages, intermissions, the finale): the screen after the black step and `newColors` equal to `PW`, after the colours to `PD1`; 9 `titleWipe` frames (X3: the first title page of each run) compared after the colours |
| TINTPAL | every distinct TINTPAL of a level (31) is `buildTints` of its record and gamma; the 8 gamma changes of palette.script (`I_ReloadPalette` after the menu's close) equal ref816's |
| The nibble tables (`nibcap`) | after 27 level loads (palettes 0-11 from the records, 12-15 unchanged), 19 new pictures (all 16) and 22 menu closes (unchanged): the model equal to ref816's NIBTAB, TINTPAL and state |
| The native frames (`s2pp`, `s2pf`) | all 1,652 cases from both fills, plain and with every SCB and palette byte the frame writes poisoned (6,608 runs of a case in 472 a2vm runs): the SCBs and palettes after `s2_finish` equal ref816's, the wipe's step equal to `PW` (every wipe frame publishes a band, the others alternate), PALST after `s2_palput` equal to the model's, `st_palette`, `message_new`, the strip's clear, the 19 pictures' 16 tables; the publish order of 1.3 (`s2check.order`) on every case's write log; 0 stray writes of 49,277,480; stack 11 B |
| PALW and `s2_picpal` | 54 cases from both fills against the dumps: 27 `palw_level` (TINTPAL, the 12 tables, 12-15 kept, the rows and flags), 8 `palw_gamma`, 19 `s2_picpal`; 0 problems, 0 stray writes |
| `ST_doPaletteStuff`'s paths | 164 synthetic inputs (every path and edge: each red step and the cap, the menu's half, the berserk's fade and its 16-bit compare, each gold step and the cap, the suit above 128 and its blink on bit 3, none, st_palette unchanged) by ref816 `--call` on a state in play: the model equal on all; 155 of them natively (9 give a tint past TINTPAL's 14 or a `st_palette` a signed byte cannot hold: model only, counted) and 13 hand-made states for the branches the frames take rarely (`stripEarly` paused and in a menu, the strip kept, cleared again and restored, the automap's rows, `I_ReloadPalette`'s two branches, a level left, the same picture again): 0 problems |
| Coverage | each of the model's 22 branches taken by compared cases (`report.json` `coverage`); none taken fails the checkpoint |
| `tests/test_sound_*` | unchanged and green (7 modules, 152 tests) |

### 2.1 The tests

`tests/wip_test_m11_s2pal.py` (14 tests, 84 s; also OK on Python 3.9.6
with `-W error::ResourceWarning`, 118 s): the model's rules on hand-made
values, PALST's round trip, the include's places, `s2layout.check()`
(no build needed); the model against ref816 on palette.script and newgame
and on all nine runs' nibble dumps; the native frames of palette.script
and newgame (both fills, plain and poisoned); PALW on palette.script;
the `ST_doPaletteStuff` paths; the sizes; the seven planted bugs. Without
`build/` the first seven run and the others skip naming what is missing.

## 3. Planted bugs (each in a scratch copy of the sources) and the check that caught it

| Bug | Caught by | The first failure [M] |
| --- | --- | --- |
| Gamma applied twice (`s2_gamma`'s blue looked up again) | PALW against the dumps (14 failures) | `palette/PG:040CA0#4 (gamma, fill A5): TINTPAL byte 8 97, ref 96` |
| The tint row of `newpal - 1` | the native frames (49) | `palette/f000029 (fill A5): after s2_finish $9E00 A5, ref 00` |
| The black step skipped | the wipe's step and the order (37) | `palette/f000027 (fill A5): the wipe's step (PW) $9E02 7F, ref 00` |
| The black palettes after the first band (`s2_publish` calls `s2_begin` after its band's stores) | the order alone: both snapshots pass (19) | `palette/f000027 (fill A5): order: store 0 ($5E80, a band store of $5A) before the last black palette store` |
| A radiation suit blink on bit 3 of the wrong byte | the synthetic paths (84) | `synth/stpal-132 (fill A5): after s2_finish $9E00 00, ref 8D` |
| The strip's palette not restored | demo3's frames (20) | `demo3/f001091 (fill A5): after s2_finish $9D00 0A, ref 00` |
| `TINT_ROW` 512 instead of 384 | the native frames (32) | `palette/f000029 (fill A5): after s2_finish $9F81 02, ref 00` |

The radiation suit's blink is never reached in the captures
(palette.script pokes `powers[pw_ironfeet]` 200, then 0 sixty tics later,
so it stays above 128): the synthetic inputs by ref816 `--call` are what
catch that bug.

## 4. Sizes against the budget

| Item | Size [M] | Budget |
| --- | ---: | ---: |
| `s2_pal` (in `P2DW`, `WIW`) | 680 B | 800 B |
| `s2_nib` (in `WIW`, `PALW`) | 390 B | 400 B |
| `PALW`'s own (`s2_palw`) | 443 B | 1,500 B |
| `PALW` in its room (with `s2_nib`) | 833 B | 6,656 B (design 1,900) |
| zero page | `$78-$7F` | `S2_*` `$48-$7F` |
| page 1 | `$0100-$017F` | below `$01B4` (4.2) |

## 5. Timing (SCREENS.md 6.4)

`python3 tools/native/s2pal.py --all` [M]: each case alone, the cost
phase 30 around the code under test only (`s2_palget`, the frame's
palette calls, `s2_begin` and `s2_finish` without a band, `s2_palput`),
1,652 frames:

| Frame | Frames | `f121` median / p99 / worst ms | `fastpath` median / p99 / worst ms |
| --- | ---: | --- | --- |
| Nothing to write | 1,458 | 0.71 / 0.71 / 0.71 | 0.49 / 0.50 / 0.50 |
| The SCBs | 8 | 0.92 / 0.95 / 0.95 | 0.70 / 0.73 / 0.73 |
| A TINTPAL row (a new tint or a level's first frame) | 123 | 1.27 / 1.48 / 1.48 | 1.02 / 1.22 / 1.22 |
| A wipe (the black step, the colours) | 63 | 1.93 / 16.43 / 16.43 | 1.71 / 12.71 / 12.71 |
| All | 1,652 | 0.71 / 15.88 / 16.43 | 0.49 / 12.20 / 12.71 |

The 0.71 ms floor is PALST's fetch and write-back (1,536 bytes through
the far layer, the state block of SCREENS.md 4.6). The wipe's worst are
the frames of a new picture, whose `s2_picpal` builds 16 nibble tables
and 256 colours with gamma (about 14 ms). `PALW` (one case alone, the
driver's phase 30 around the call): `palw_level` 22.2 ms `f121` (18.0
`fastpath`) at worst over the 27 loads, `palw_gamma` 12.4 (10.7),
`s2_picpal` with PALST's get and put 14.7 (11.0); `PALW`'s load is its
833 bytes plus `MATHW`.

## 6. Requests (for the integrator; the stand-ins are marked `STANDIN` in `tools/native/s2pal.py` and the generated `s2pal.inc`)

### S2PAL-1. `tools/native/s2layout.py` (and `s2.inc`): `S2PAL`'s places

**Evidence.** SCREENS.md 4.5 gives bank `S2PAL` "TINTPAL, the 16 nibble
tables `S2NIB`, `GRAYMAP`, `GSSTAT`, `GSOVL`" but no addresses;
`newColors`, `PALW` and `s2_nib` need them, and part `s2data` puts
`GSSTAT` and `GSOVL` in the bank. **Stand-in.** `s2pal.S2PAL_PLACES`,
written into `build/native/m11/s2pal/gen/s2pal.inc`. **What.** In
`s2layout.py`, after `S2STATE`'s layout:

```python
# S2PAL (bank 106, SCREENS.md 4.5): part s2pal's places (request
# S2PAL-1); each in the bank's $0200-$BFFF (a RAMRD window reaches nothing
# else), S2P_NIB page aligned (a palette's table at S2P_NIB + p * $400)
S2PAL_PLACES = [('S2P_TINTPAL', 0x0200, 14 * 384),
                ('S2P_NIB', 0x1800, 16 * 0x400),
                ('S2P_GSSTAT', 0x5800, 5664),
                ('S2P_GSOVL', 0x6E20, 2112),
                ('S2P_GRAYMAP', 0x7700, 256)]
```

written into `s2.inc` as `NAME = addr` and `NAME_SIZE = size`, and checked
by `check()` (inside `$0200-$BFFF`, disjoint, `S2P_NIB & $FF == 0`).
Then `s2pal.S2PAL_PLACES` imports it and `s2pal.inc` drops these lines.
Part `s2data` (or the boot) puts `GSSTAT` and `GSOVL` at these places.

### S2PAL-2. `tools/native/s2layout.py`: `PS_TXTINV` in `PALST_NATIVE`

**Evidence.** Upstream's `setRows`, `buildNibtab` and `drawPicture` call
`textInvalidate` [R `i_viigs65.s:705`, `:744`, `:1245`], which
clears the HUD's `textValid` and `iigs_textShown` [R `:1891-1897`];
natively those are `P2DW`'s state (`P_TXTVALID`, `P_TXTSHOWN`), which
`WIW`, `FINW` and `PALW` cannot reach. **Stand-in.** `PS_TXTINV =
PS_BEGUN + 1` in `s2pal.inc`. **What.** `PALST_NATIVE = [('PS_BEGUN', 1),
('PS_TXTINV', 1)]` with the comment "PS_TXTINV: the HUD's text cache is
invalid (upstream's textInvalidate: s2_setrows, s2_nibtab and s2_picpal
set it; s2hud clears both slots' textValid and iigs_textShown, then it)".
For part `s2hud`: do so at `HU_Drawer`'s start.

### S2PAL-3. `tools/native/s2layout.py` (`S2_ZP`) and SCREENS.md 4.3: `$78-$7F`

**Stand-in.** `s2pal.S2P_ZP`. **What.** Add to `S2_ZP` `('S2P_A', 0x78,
2), ('S2P_B', 0x7A, 2), ('S2P_C', 0x7C, 1), ('S2P_D', 0x7D, 1),
('S2P_E', 0x7E, 1), ('S2P_F', 0x7F, 1)` (in the form `S2_ZP` takes); in
SCREENS.md 4.3's row `$48-$7F` replace "`$78-$7F` free" with "`$78-$7F`
`s2_pal`'s and `s2_nib`'s temporaries (`S2P_*`, part `s2pal`)". They are
never live across a drawer's call: `s2_publish` calls `s2_begin`, which
keeps `S2_BAND`..`S2_DRY1`.

### S2PAL-4. SCREENS.md 4.2: page 1 for `newColors`

Add the row "`$0100-$017F` | `newColors`' bounce: TINTPAL's row from
`S2PAL` to aux 0, 128 bytes at a time (`s2_begin`, part `s2pal`) | no |
the stack stays at or above `$01C0`".

### S2PAL-5. The field map and `s2state.py`: `palettecount` is a flag natively

**Evidence.** Upstream writes `palettecount` 0 or 256 only [R
`i_viigs65.s:404`, `:1274-1275`, `:2124`, `:2187`]; the field map's `byte`
cannot hold 256 (no case had it at a frame's start, so `s2cap` saw no
unfit value; an event's or a menu's would). **What.** In
`s2layout._palettes()`: `('palettecount', 2, 'byte', 'PS_PALCOUNT')` →
`('palettecount', 2, 'flag', 'PS_PALCOUNT')`, with `'flag': 1` in the
native sizes [R `s2layout.py:573`] and `check()`'s encodings [R `:1376`];
in `s2state.encode`: `if enc == 'flag': return bytes([1 if value else 0]),
value in (0, 256)`, and `decode`: `if enc == 'flag': return 256 if data[0]
else 0`. (`s2pal.palst_native` does this for its own cases.)

### S2PAL-6. `tools/native/s2state.py`: `NO_PALETTE_CHANGE` is 100

**Evidence.** `NO_PALETTE_CHANGE .equ 100` [R `i_viigs65.s:66`];
`s2state.py:58` has `0xFFFF`, so `marked()` takes every frame for one
with a new tint and poisons palettes 0-11 of every frame's screen
(`newpal` is a byte, never `$FFFF`): a part that poisons with `marked()`
would expect palette bytes no frame wrote. **What.** `NO_PALETTE_CHANGE =
100` with the citation `[R i_viigs65.s:66]`. (This part poisons from its
model's own stores.)

### S2PAL-7. SCREENS.md 7.3 (`s2pal`), 4.1's size table: where `setRows` is

**Evidence.** `P2DW` needs `setRows` (`I_ViewPalette`, `I_MessageStrip`)
but does not link `s2_nib` (4.1's size table). **What.** In 7.3's
`s2pal` entry, `s2_nib.s` "(nibble tables from a picture's pairs,
`setRows`, `rowPalette`)" becomes "(the nibble tables, `gammaColor`, a
picture's palettes)", and `s2_pal.s` adds "`setRows` and `rowPalette`'s
SCB". A row's nibble pages (upstream's `iigs_rowpageL/R`) are natively
each drawing image's (its slots), from the row's SCB: open problem 1.

### S2PAL-8. S2DRAW-5's rest: `AMAPW`'s `s2_begin`, `MENUW`'s PALST

**Evidence.** In a full-automap frame upstream's order is
`I_ViewPalette(AMAP_PAL)` (the rows' SCBs), the map's bytes, then the
status bar's [R `d_main65.s:445-450`, `:526-536`]; natively `AMAPW`
publishes first, and its `s2_publish` needs `s2_begin` with the rows
already set. `AMAPW` has no `s2_pal` and no room for PALST (its runtime
ranges `$8E00-$BFFF` are all taken); `MENUW` the same (wave 1, open
problem 1). **What** (the integrator's or `s2amap`'s and `s2menu1`'s
choice): `AMAPW` links `s2_pal` (680 B; its room holds 7,200 of 10,240 B
budgeted) and keeps PALST at W `$8B00-$8DFF` with its room ending at
`$8B00` (s2layout's `AMAPW` image), runs `s2_palget`, `s2_viewpal` with
`AMAP_PAL` before its first band, and `s2_palput` after (`P2DW` then
runs `st_palette` and `s2_finish`, its `s2_begun` already set); `MENUW`
the same with its PALST where `s2menu1` finds room (its fetch buffer
`$BD00-$BEFF` and state `$BF00` hold 768 B only together with the
state).

### S2PAL-9. For `s2stbar` and `s2menu1`: `I_SetPalette` from the tic and the menu

`ST_Start` calls `I_SetPalette(0)` [R `st_stuff65.s:221-225`] from the
tic, where PALST is in `S2STATE`, not in W: `st_start` (tic-side) writes
`newpal` 0 there by a one-byte `far_put` to `SS_PALST + PS_NEWPAL`; the
menu's `I_SetPalette` [R `m_menu65.s:1078`] is `s2_setpal` in `MENUW`.

## 7. Decisions where the design left a choice

- **The colours once a frame.** `I_ApplyColors` before the view and
  `I_FinishUpdate`'s `newColors` after it [R `d_main65.s:499-502`,
  `:552-557`] are one `s2_begin` natively; the final screen is the same
  (every byte `I_ApplyColors` writes is written again or is equal), so the
  poisoned runs, which poison every byte either wrote, pass. 40 frames of
  the nine runs had `I_ApplyColors` stores (D1).
- **The black step always.** `titleWipe`'s first title page without black
  [R `w_level65.s:1418-1447`] has no native counterpart (X3, 9 frames: one
  a run); natively the black step comes and the colours after it equal.
- **PALW rebuilds the tints at every level start** instead of upstream's
  cache of the record and gamma (`VL_TINTS`, `VL_TGAMMA` [R
  `i_viigs65.s:1189-1196`]): the same bytes, 22 ms at worst once a level.
- **ST_doPaletteStuff's inputs** are the reference's at the call: the
  player's four fields at `I_FinishUpdate`'s entry (display changes none
  of them; a script's poke can land inside the frame).
- **The test image's places**: `WIW`'s room for the frames with a picture
  (`s2_nib` linked), `P2DW`'s for the others; the case's state staged in
  bank 61, its TINTPAL in 63, its picture in 62, copied into place by the
  glue in phase 0.

## 8. Open problems

1. **A row's nibble pages.** Upstream's `rowPalette` also writes
   `iigs_rowpageL/R` [R `i_viigs65.s:766-787`]; natively each band's
   `ROWL`/`ROWR` (part `s2draw`'s interface) come from the rows' SCBs and
   the image's nibble slots, and nothing shared builds them yet (the
   slots' fetches from `S2NIB` and their eviction): for `s2stbar` (8
   slots, palettes 1-8, then the strip's palette 10) and the others, or a
   helper in `s2_pal` (about 120 B left in its budget).
2. **PALST's write-back every frame** (0.71 ms of the 0.71 ms a frame
   with nothing to write costs on `f121`): `s2_palput` could be skipped
   when nothing changed but `PS_BEGUN`, if `s2_finish` left it to the
   next frame's `s2_palget` (a lever for the performance pass).
3. **`PS_PALCOUNT`, `newpal` and `st_palette`** keep upstream's values
   only where they fit: a tint past TINTPAL's 14 or a `st_palette`
   outside -128..127 (both from damage or bonus counts past 32,000) are
   compared on the model only (9 synthetic inputs).
4. Requests S2PAL-1 to -5 are stand-ins until the integrator applies them;
   S2PAL-6 is a defect of `s2state.py` (part `s2cap`'s), not of this part.
5. The part took longer than its 1.5 hours.

## 9. The wave 3 integration (2026-10-01)

What the integrator did with each request (`docs/SCREENS.md` 8.7, "Wave
3 as integrated"):

| Request | Outcome |
| --- | --- |
| S2PAL-1 | Applied as written: `s2layout.py` `S2PAL_PLACES` (also `S2PAL_AT`, `S2PAL_SIZE`), written into `s2.inc` as `NAME` and `NAME_SIZE` and checked by `check()` (inside `$0200-$BFFF`, disjoint, `S2P_NIB` page aligned); `s2pal.py` imports them and `s2pal.inc` no longer defines them (`wip_test_m11_s2pal`'s `test_include` now also checks that `s2pal.inc` defines none of `s2.inc`'s names). With S2DATA-3: `GSSTAT` and `GSOVL` stay at these places, and part `s2data`'s `GFX.1` writes them there |
| S2PAL-2 | Applied: `PALST_NATIVE` = `PS_BEGUN`, `PS_TXTINV` (offset `$02D2`); `s2pal.py`'s `palst_native` and `palst_decode` read the offset from `palst_places()` |
| S2PAL-3 | Applied: `S2P_A`-`S2P_F` in `S2_ZP` (`$78-$7F`); SCREENS.md 4.3 |
| S2PAL-4 | Applied: SCREENS.md 4.2's row `$0100-$017F`; `MEMORY_MAP.md` section 2 recorded in `design.md` R2 item 5 for the final integrator |
| S2PAL-5 | Applied: the field map's `palettecount` is `flag` (a native byte); `s2state.encode` and `decode` take `flag` (0 or 256 as 0 or 1; anything else unfit); `check()` accepts it |
| S2PAL-6 | Applied: `s2state.NO_PALETTE_CHANGE` is 100 [R `i_viigs65.s:66`]; `marked()` now poisons palettes 0-11 only in a frame with a new tint or a level copy (rerun: `s2cap`'s checkpoint, below) |
| S2PAL-7 | Applied: SCREENS.md 7.3's `s2pal` entry |
| S2PAL-8 | Not applied: left to `s2amap` (wave 6) and `s2menu1` (wave 5), who build those images; the part's option (`AMAPW` links `s2_pal` with PALST at W `$8B00-$8DFF` and its room ending at `$8B00`) is recorded in SCREENS.md 8.7's open problems |
| S2PAL-9 | Nothing to apply; kept for `s2stbar` and `s2menu1` |
