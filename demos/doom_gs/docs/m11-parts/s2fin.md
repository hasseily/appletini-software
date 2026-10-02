# Milestone 11, part `s2fin`: the finale, the pages, the loading screen, the busy sign

Part `s2fin` of wave 6 ([`docs/SCREENS.md`](../SCREENS.md) 7.3), written
from upstream's `src/iigs/f_finale65.s` (`F_Init`'s lumps,
`F_StartFinale`, `textSpeed`, `F_Ticker`, `F_Drawer`, `F_TextWrite`,
`F_LoadScreen` [R `f_finale65.s:60-284`]), `d_main65.s` (`D_PageDrawer`'s
`V_DrawRawFullScreen` [R `d_main65.s:417-422`] and display's finale and
page branches [R `:389-422`]) and `m_menu65.s` (`bmSignOn`, `bmSignOff`,
`bmSignBox`, `bmSignPatch` with `bmGlyph`, `bmGlyphCol`, `bmPut`,
`bmBlanks`, `bmMargin` [R `m_menu65.s:1759-2091`]). 2026-10-01. Follows
SCREENS.md 1.5.6, 1.5.7, 1.5.8, 4.1, 4.7, 6. Labels as in `NATIVE.md`: [M]
measured, [R file:line] read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `src/native/s2_fin.s` | The image `FINW`'s own code (2,213 B: code 1,553, tables 628, variables 32): `fin_init` (`F_Init`: `F_HELP2`, `F_BACKGROUND` as 2D store handles, no sign; written to `SS_FINW`), `fin_frame` (a finale or title-page frame: `pl_poll`, `fx_service`, `s2_palget`, the own block, `I_SetPalette(0)` when a level was left, `F_Drawer` or `D_PageDrawer`, `s2_finish`, `s2_palput`), `fin_load` (`F_LoadScreen`), `fin_signon`, `fin_signoff` (the busy sign). It exports the image's places for the shared objects (`s2_marks`, `s2_fbuf`, `s2_fbpages`, `s2_palst`, `s2_begun`, `s2_nbuf`) |
| `src/native/s2t_fin.s` | The tic side (175 B): `f_start` (`F_StartFinale`), `f_ticker` (`F_Ticker` after its `WI_checkForAccelerate`, which stays milestone 10's: request S2FIN-4) |
| `src/native/s2_fint.s` | The test glue (not the game): `fint_case` stages a case (WI_ACCEL, the card's `F_*`, GAMMA, `PALST`, FINW's own block, the SCBs and palettes or a whole screen) and runs its routine in the cost phase 30; `fint_tics` runs the tic records through `f_ticker` and `f_start` |
| `src/native/m11/s2fin.mk` | `make -C src/native -f m11.mk part P=s2fin`: `gen/lgame.inc` (milestone 10's, `llayout.py --game`), `gen/s2fin.inc`, `gen/s2pal.inc` (part s2pal's generator), the image `finw` (FINW as the game links it, under the test driver) and the test image `s2ft` (with the tic side and the glue) |
| `tools/native/s2fin.py` | The include (`--inc`: the release's lump numbers of `HELP2` and `TITLEPIC`, `CONST_GS_FINALE`, the end text's length, the font's places and widths), this part's capture (`--capture`), the cases, the a2vm runs and their judgement (`--check`), the planted bugs (`--planted`), the report (`--all`, `report.json`) |
| `tests/wip_test_m11_s2fin.py` | 13 tests (2.1) |

Build output: `build/native/m11/s2fin/` (about 2 MB: the objects, the two
images, `gen/`, `cap/` (this part's capture, 294 KB), `report.json`).
Every run's directory, and every planted bug's scratch copy, is a
`tempfile` directory there, deleted after it.

### 1.1 The interface

**The tic side** (`s2t_fin.s`, GAME.md 4.4's conventions: no zero page,
no scratch block, A, X, Y changed). The finale's state is the card's
`F_STAGE` (finalestage, a byte), `F_COUNT` (finalecount, upstream's
int32), `F_MID` (midstage, a byte) of the `S2T` block (SCREENS.md 4.4);
acceleratestage is milestone 10's `WI_ACCEL`; `G_GAMEACTION`,
`G_GAMESTATE` and the frame block's `AUTOMAP` through `lgame.inc` and
`rlayout.inc`.

- `f_start` is `F_StartFinale`: `G_GAMEACTION` 0, `G_GAMESTATE`
  `GS_FINALE`, bit 0 (`AM_ACTIVE`) of `AUTOMAP` cleared (the byte the
  renderer reads; R6's `AM_Stop` clears the same bit), `WI_ACCEL`, `F_MID`,
  `F_STAGE` and `F_COUNT` 0.
- `f_ticker` is `F_Ticker` without its first call: the hook calls
  milestone 10's `WI_checkForAccelerate` (flow's `gwi.s`), then
  `f_ticker` (request S2FIN-4), as `st_tick` passes `M_Random`'s value to
  `st_ticker`.
- Upstream's `F_Ticker` also writes display's `wipegamestate` (-1, a wipe)
  when the picture comes. Natively the wipe's black step comes from
  `s2_picpal`'s `picturenum` (a new picture), so nothing is written for it;
  `D_Wipe` and `I_FinishUpdate` are one routine upstream (0.1 F1).

**The frame and the events** (for the frame driver and the load protocol,
request S2FIN-5), each after `far_pload` of `FINW` (bank `S2CODE4`, 96):

| Entry | When | Arguments |
| --- | --- | --- |
| `fin_frame` | a finale frame (`G_GAMESTATE` `GS_FINALE`), a title-page frame that draws (display's page branch when not `staticUpToDate`) | A bit 0: display's `oldgamestate` was a level (`I_SetPalette(0)`); bit 1: the title page (`D_PageDrawer`) instead of `F_Drawer` |
| `fin_load` | `F_LoadScreen` (milestone 10's hook, `doWorldDone`) | none |
| `fin_signon` | `bmSignOn` (`bmLoad`, `bmSave`), `bmSignLoading`, `bmSignSaving`, `bmDiskAsk` | A: 0 "LOADING...", 1 "SAVING...", 2 "INSERT DISK n" with X the digit's character |
| `fin_signoff` | `bmSignOff` (`W_LevelDone`, `bmSaved`) | none |
| `fin_init` | once at the boot (`F_Init`) | none |

**How a screen is composed.** The pictures (`HELP2`, `TITLEPIC`) in five
bands of 40 rows: `s2_picpal` (their palette part, once), then `s2_rect`
of the picture's rows (every byte marked: `drawPicture`'s `markRows(0,
200)`), published. The finale's text and the loading screen in bands of 16
rows: the band's rows' nibble tables, `s2_back` (`V_DrawBackground` of
`FLOOR4_8`), the glyphs of `F_TextWrite` that cross the band (each by
`s2_vpatch`, clipped to the band), published. A band of 16 rows needs at
most 16 units of nibble tables (a palette and a parity, `s2_wi.s`'s
scheme), so the slots never overflow whatever the rows' palettes: the
finale's text sits on the level's rows (palette 0 and the status bar's
palettes 1-8), the loading screen on the intermission's (`WIMAP0`'s).

**The busy sign.** `bmSignPatch` builds a patch in RAM upstream; natively
the sign is drawn column by column into the band by the nibble rule (the
same pixels: the text in the font, each pixel doubled, `BUSY_H` 24 rows of
4 black, the glyph's rows 0-7 twice, 4 black, between 4 black columns, at
x = 160 - width / 2, y = 88; a glyph column's posts read as `bmGlyphCol`
reads them, rows past 7 dropped). The rows under the sign (88-111) are
saved the first time by one memory-API COPY of aux 0's 3,840 bytes to
`S2STATE`'s `SS_SIGN` (a source in aux 0 is allowed, SCREENS.md 0.1 F10;
`s2_mvid.s`'s transport), and the sign's state (upstream's `VW_SGON`) is
kept in FINW's own block (`F_SIGNON`, a marked stand-in: S2FIN-1), so the
sign survives the load that overwrites W. The band's background is the
saved rows (`s2_rect` from `SS_SIGN`), so the sign's edge nibbles come
from the screen as upstream's come from its back buffer. `fin_signon`
publishes the sign's bytes (markPatch's rectangle), or every row when the
sign was already on (a new text puts the rows back first); `fin_signoff`
publishes the 24 saved rows. Neither writes a colour or an SCB
(`I_ShowDirty`: `s2_begun` set around the publish).

**Zero page**: the drawers' `S2_*`, the far layer's `FA_*`, `s2_pal`'s
`S2P_*` and FINW's temporaries `FZ_*` at `$80-$A4` (the sign's over the
text's; request S2FIN-2). The test glue uses `$B0-$B8` (the math block's:
FINW calls no math).

### 1.2 This part's capture

Part s2cap's cases hold the frames and the `bmSignOn`, `F_LoadScreen`
events, but not what this part also needs, so `s2fin.py --capture` runs
the same three scripts (finale, signs, demo3) on ref816 again (8 s, 1.8 MB
of pipe traffic in all) with:

- the nibble tables (`NIBTAB`) and `TINTPAL` at part s2pal's points
  (`I_SetLevelPalette`'s, `drawPicture`'s and `I_MenuPaletteBack`'s
  returns): a case's tables are the last ones before it (its `S2NIB`);
- `bmSignOn`'s entry (`VW_SGON` and A, the text's address, matched to the
  event by its cycles: `txLoading` in all four), and the screen at
  `bmSignOff`'s entry with the sign on and at its return (`bmSignOff` is
  also reached by `JMP` [R `w_level65.s:519`], so s2cap has no event of
  it): 4 sign-offs, each run in the same a2vm run as its sign-on, from the
  native `SS_SIGN` and `F_SIGNON` that left;
- the call log of `F_Ticker` (`jumps=1`), `WI_checkForAccelerate` (its
  result is `f_ticker`'s input; the log's `parent` pairs it with its
  `F_Ticker`) and `F_StartFinale` (`jumps=1`: `W_StartFinale` jumps to
  it).

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
df -h /System/Volumes/Data                      # 60 GB free
make -C src/native -f m11.mk part P=s2fin       # no warning
python3 tools/native/s2fin.py --capture         # 8 s (3 runs, 2 at once)
python3 tools/native/s2fin.py --all --jobs 2    # the checks on f121 and
                                                #   fastpath, the planted
                                                #   bugs: report.json
python3 tools/testpar.py tests/wip_test_m11_s2fin.py
```

Results [M, 2026-10-01]: `report.json` `ok`, 0 problems.

| Item | Result |
| --- | --- |
| Every frame of `finale.script` that FINW draws | 63 finale frames: 35 of the text (from no letter to the whole text, the mid stage from frame 4,034), the `HELP2` wipe and 27 `HELP2` frames; each frame's whole screen (32,000 pixel bytes, the 200 SCBs, the 512 palette bytes; `$9DC8-$9DFF` kept) equal to the reference's after the frame |
| The title page | its one drawn frame in each of `finale.script`, `signs.script` and demo3 (frame 1,950: the boot's first page), equal; the page's other frames are display's `staticUpToDate` turns that draw nothing (26, 26 and 1,038 frames, counted, not run: the decision is the frame driver's) |
| `signs.script` | `F_LoadScreen` (the flat over the intermission's palettes), both busy signs and both sign-offs (the rows put back), equal; and demo3's and `finale.script`'s sign and sign-off |
| Injected, both fills | every case from its own state: fill `$A5` with the SCBs and palettes as captured, fill `$5A` with every byte the frame marked poisoned (the signs: the screen as captured in both, since the sign's edge nibbles are the screen's); the pixels are always poisoned before a frame or the load screen (all 32,000 must be drawn): 150 case runs in 24 a2vm runs, 0 problems |
| Chained | the 63 finale frames in order from the first one's state: `PALST`, FINW's own block and the nibble tables carried by the native code (across a2vm runs too: the last run's `SS_PALST`, `SS_FINW` and `S2NIB` start the next), the tic's state (`F_*`, `WI_ACCEL`) injected as the tics leave it: 3 runs, 0 problems |
| `F_MID`, `WI_ACCEL`, `PALST` | after every finale frame equal to the reference's at `I_FinishUpdate` (F_Drawer's `textSpeed` writes them); `PALST`'s `scb`, `palette` and `picturenum` too, after every frame and the load screen |
| The wipe (1.5.8) | the publish order on every frame's and the load screen's screen stores (`s2check.order`: the black step first on the 4 new pictures, no band store before the last SCB store, no colour store before the last band store); the `HELP2` wipe's step rebuilt from the write log (every screen store before `pictureColors`) equal to the reference's `PW`; the signs write no colour and no SCB |
| X3 | counted and named: 3 frames, the title page's first frame of each run (upstream's `titleWipe` over the boot's gray title: no black step, so no `PW`); the frame's final screen is compared as every other |
| `f_ticker`, `f_start` | every `F_Ticker` of `finale.script` (253) and its `F_StartFinale`: the card's `F_*`, `WI_ACCEL`, `G_GAMEACTION`, `G_GAMESTATE` and `AUTOMAP`'s `AM_ACTIVE` after it equal to the reference's, injected (each from the reference's state) and chained (the card carried from the first tic, `WI_ACCEL` taken from the record only where the reference's check changed it: 2 tics), 0 problems |
| No stray write | every writer judged (the driver, the loader, the far layer, the glue, `s2_fin`, `s2t_fin`, `s2_draw`, `s2_pub`, `s2_pal`, `s2_nib`, `fx_service`, `pl_poll`), 0 stray |
| Stack | 18 B (`--lowest-s-in`, the interrupt's included), of 64 + 24 |
| `FINW` within its room | 5,405 of 6,656 B (`finw.sizes`) |
| `tests/test_sound_*` | not touched |

### 2.1 The tests

`tests/wip_test_m11_s2fin.py` (13 tests, 80 s): without a build, the
region (the whole screen but rule 10's bytes), the stage and the tic
records against `s2_fint.s`'s constants, each planted edit found once in
the sources, the game's and the card's places taken by the includes'
names, the stand-ins marked (also OK on Python 3.9.6 with `-W
error::ResourceWarning`); with the build, the checkpoint (every case
injected and chained, every tic), the include, the end text equal to the
release's bytes, the sign-offs, the sizes, and the three planted bugs.
Without `build/` the first six run and the others skip naming what is
missing.

`python3 tools/testpar.py tests/wip_test_m11_s2fin.py` [M]: 1 module, 13
tests, 0 failures, 0 errors, 0 skipped.

## 3. Planted bugs (each in a scratch copy of the sources) and the check that caught it

| Bug | Caught by | The first failure [M] |
| --- | --- | --- |
| The text speed's mid stage ignored (`textSpeed`'s first test dropped in `s2_fin.s` and `s2t_fin.s`) | the text frames of the mid stage and the tics after the first request (31) | `finale/f004034 (fill A5): row 10 byte 86, $2696: $EE, ref $3F (5312 bytes differ)` |
| The new line 11 rows down off by one (12) | every text frame past the first line (30) | `finale/f004034 (fill A5): row 21 byte 6, $2D26: $FD, ref $F3 (7733 bytes differ)` |
| The sign's rows not put back (`fin_signoff` without its publish) | the four sign-offs, both fills (8) | `finale/soff0 (fill A5): row 88 byte 46, $572E: $00, ref $99 (1616 bytes differ)` |

## 4. Sizes against the budget

| Item | Size [M] | Budget |
| --- | ---: | ---: |
| `s2_fin`'s code | 1,553 B | 1,600 B (`s2fin`, 7.3) |
| `s2_fin`'s tables (the font's places and widths 252, the end text 298, the signs' texts 39, the COPY 30, constants 9) and variables (the units 32) | 628 + 32 B | 500 B (data, 4.1); over: request S2FIN-3 |
| `FINW` own (`s2_fin`) | 2,213 B | 2,100 B (`OVER BUDGET` in `finw.sizes`, which fails no build) |
| `s2_draw` + `s2_pub`, `s2_pal`, `s2_nib`, `fx_service`, `pl_poll` | 1,172, 680, 390, 396, 554 B | 1,200, 800, 400, 400, 600 B |
| `FINW` in its room | 5,405 B | 6,656 B (design total 5,500) |
| The tic side `s2t_fin` | 175 B | 250 B |
| Zero page | `FZ_*` `$80-$A4` (37 B) | request S2FIN-2 |

## 5. Timing (SCREENS.md 6.4)

`python3 tools/native/s2fin.py --all` [M]: each case's routine alone
(the glue's cost phase 30 around it, the clock from the write log's
`PHASE` stores, `--cost-timed`), every case injected at fill `$A5`; the
tic side a call:

| Case | n | `f121` median / p99 / worst ms | `fastpath` median / p99 / worst ms |
| --- | ---: | --- | --- |
| A text frame (from no letter to the whole text) | 35 | 67.87 / 174.02 / 174.02 | 62.27 / 143.70 / 143.70 |
| `HELP2`'s first frame (its 16 nibble tables, the black step) | 1 | 61.46 | 54.38 |
| A `HELP2` frame | 27 | 46.28 / 46.28 / 46.28 | 42.66 / 42.66 / 42.66 |
| The title page's first frame (the black step) | 3 | 62.01 | 54.90 |
| `F_LoadScreen` | 1 | 68.32 | 62.68 |
| `bmSignOn` (the COPY, the sign's 24 rows) | 4 | 17.11 / 18.71 / 18.71 | 14.05 / 15.26 / 15.26 |
| `bmSignOff` (24 rows published) | 4 | 5.49 / 5.50 / 5.50 | 5.08 / 5.08 / 5.08 |
| `f_ticker`, `f_start` (µs a call) | 254 | 2.36 / 2.38 / 2.95 µs | 2.34 / 2.36 / 2.93 µs |

Apart from these: `FINW`'s load, 5,405 B, about 1.33 ms [A on M: 0.246
µs a byte, `NATIVE.md` 4.3]; the publish's drain, 32,512 B a frame (the
pixels and the palettes), about 32.2 ms of the frames' times above, and
3,840 B (3.8 ms) of a sign's or a sign-off's [A on M: 0.991 µs a byte,
`s2draw.md` 5]. A text frame is the flat (the load screen's 68 ms, its
drain included) and about 0.4 ms a glyph: each glyph refills `s2_draw`'s
fetch buffer from its patch (open problem 4).

## 6. Requests (for the integrator; the stand-ins are marked `STANDIN`)

### S2FIN-1. `tools/native/s2layout.py`: the sign's state and its stop code

**Evidence.** The busy sign's state (upstream's `VW_SGON` [R
`viewwin.inc:69`]) must live from `bmSignOn` to `bmSignOff` across the
level load, which overwrites W, so it is in FINW's own block (`SS_FINW`),
after the field map's `F_HELP2`, `F_BACKGROUND`. A failed memory-API save
stops as the menu's does (`PL_MENUAMEM` `$C5`, S2MENU1-2). **Stand-in.**
`src/native/s2_fin.s`: `F_SIGNON = OWN + 2` and `FIN_AMEMSTOP = $C6`, both
marked. **What.** In `s2layout.py`:

```
-OWN_NATIVE = {'P2DW': P2DW_NATIVE, 'MENUW': MENUW_NATIVE}
+# FINW's own fields with no upstream counterpart (part s2fin, request
+# S2FIN-1): the busy sign is on (upstream's VW_SGON)
+FINW_NATIVE = [('F_SIGNON', 1)]
+OWN_NATIVE = {'P2DW': P2DW_NATIVE, 'MENUW': MENUW_NATIVE,
+              'FINW': FINW_NATIVE}
```

(`state_places('FINW')` then gives `F_SIGNON` `$BF02`, the stand-in's
address), and `PL`'s `'SIGNAMEM': 0xC6` (the sign's save failed; `s2.inc`
`PL_SIGNAMEM`). Then `s2_fin.s` drops both stand-ins and uses
`PL_SIGNAMEM`; `s2fin.py`'s `own[2]` becomes `S.state_places('FINW')
['F_SIGNON'] - 0xBF00`.

### S2FIN-2. SCREENS.md 4.3: FINW's temporaries at `$80-$A4`

**Evidence.** FINW's temporaries (`FZ_*`: the text's position and count,
the division, the units, the sign's columns) are 37 bytes; in `S2DATA`
they would cost code (absolute addressing) in an image already over its
own budget. `$80-$AF` is the menu's and the automap's (4.3) and WIW's
temporaries; none of those images runs while FINW does (a finale, page
or load frame draws no menu: display's `uiDisplay` replaces it; the sign
of a menu's save, `bmSave`, is drawn with FINW loaded in W in place of
MENUW, which the driver reloads after: S2FIN-5), and FINW keeps nothing
there between calls. **What.** 4.3's row `$80-$AF` adds: "FINW's
temporaries `$80-$A4` (`FZ_*`, part `s2fin`; nothing kept between
calls)".

### S2FIN-3. SCREENS.md 4.1, 7.3 and `s2layout.py`: FINW's own budget

**Evidence.** Section 4: the end text (298 B) and the font's table (252
B: a glyph's place and width, so the text's walk fetches nothing but the
glyphs it draws) are data upstream keeps in its own banks. **What.** 4.1's
size table, `FINW` own: "2,100 (`s2fin` 1,600, data 500)" becomes "2,300
(`s2fin` 1,600, data 700: 2,213 [M])"; the total "5,500 / 6,656" becomes
"5,700 / 6,656" (5,405 [M]). `s2layout.IMAGES`' `FINW`: `2100, 's2fin
1,600, data 500'` becomes `2300, 's2fin 1,600, data 700'`, and
`DESIGN_TOTALS['FINW']` 5500 becomes 5700.

### S2FIN-4. Milestone 10 (`design.md` R4): the finale's hooks

**What** (`design.md` R4, a new item): "`ghook.s`'s `W_StartFinale` (today
a stop, `GS_FINALE`) calls `f_start` (`src/native/s2t_fin.s`,
`F_StartFinale`'s state: `G_GAMEACTION` 0, `G_GAMESTATE` `GS_FINALE`,
`AUTOMAP`'s bit 0 cleared, `WI_ACCEL` and the card's `F_STAGE`, `F_COUNT`,
`F_MID` 0); `F_Ticker` (today a stop) does `FCALL WI_checkForAccelerate`
(flow's `gwi.s`), then `jsr f_ticker`. `s2t_fin.s` is 175 B [M], uses no
zero page and no scratch block, changes A, X, Y, and reads `WI_ACCEL`,
`G_GAMEACTION`, `G_GAMESTATE` by `lgame.inc`'s names; its tests link it in
this half's test image (`s2ft`)." **Why.** SCREENS.md 4.7: the finale's
ticker is tic-side; `WI_checkForAccelerate` is flow's [R GAME.md 2.4
`flow`], so the hook calls it first, as `st_tick` passes `M_Random`'s
value. The comparison takes the check's result from the reference's call
log (1.2).

### S2FIN-5. The frame driver and the load protocol (`design.md` R7)

**What** (`design.md` R7, a new item 11): "Finale frames (`G_GAMESTATE`
`GS_FINALE`) and the title page's drawing frames: `far_pload` of `FINW`
(bank `S2CODE4`, 96), then `jsr fin_frame` with A bit 0 when display's
`oldgamestate` was a level, bit 1 for the title page (`D_PageDrawer`);
the page's static turns (display's `staticUpToDate`, then `onlyTics`) do
not call it. A menu over either runs `MENUW`'s frame, as display's
`uiDisplay` does. `F_LoadScreen` (milestone 10's hook in `doWorldDone`):
`FINW` loaded, `jsr fin_load`. The busy sign (`bmLoad` around the level
load, `bmSave`/`bmSaved` around a save, `bmDiskAsk`): `FINW` loaded, `jsr
fin_signon` with A = 0 "LOADING...", 1 "SAVING...", 2 "INSERT DISK n" (X
the digit's character) before the disk work, `FINW` loaded again, `jsr
fin_signoff` after it; a menu's save reloads `MENUW` after. `fin_init`
once at the boot with `FINW` loaded (it writes `SS_FINW`: `F_HELP2`,
`F_BACKGROUND`, no sign), like upstream's `F_Init` in `D_DoomMain`."

### S2FIN-6. `s2layout.py`'s FINW runtime text

**What.** `IMAGES`' `FINW` runtime `(0x9A00, 0xBA00, 'eight nibble
slots')` becomes `(0x9A00, 0xBA00, '16 nibble units of 2 pages (bands of
16 rows)')`; SCREENS.md 4.1's `FINW` row "as `WIW`" stays true. No address
changes.

### S2FIN-7. SCREENS.md 1.5.6, 1.5.8, 6.1 as built

**What.** 1.5.6's busy sign row: "`FINW`; the rows under the sign kept in
`S2STATE` and put back" becomes "`FINW`: the sign drawn by columns into a
band over the rows under it, which the first `bmSignOn` saves by one
memory-API COPY of aux 0's rows 88-111 to `SS_SIGN` (a source in aux 0, F10)
and `bmSignOff` publishes back; the sign's state `F_SIGNON` in FINW's own
block (S2FIN-1)". 1.5.6's finale row adds "`F_Ticker` after milestone 10's
`WI_checkForAccelerate` (S2FIN-4)". 6.1's paragraph after the table adds:
"`bmSignOff`'s screen (it is also reached by `JMP`) and the nibble tables
of the finale's and the signs' cases come from part `s2fin`'s own capture
(`s2fin.py --capture`)".

### S2FIN-8. The busy sign's font: this part's and part s2menu2's

**Evidence.** SCREENS.md 7.3 gives the sign's font (`bmGlyph`, `bmPut`)
to part `s2menu2` and the sign (`bmSignOn` .. `bmSignPatch`) to this part;
both were built at once in wave 6. Part s2menu2's
`src/native/m11/s2menu2.mk` builds `s2_sgfont.o` (`s2_menu2.s -D
M2_SIGNFONT`: `sg_glyph`, `sg_col`, `sg_put`, `sg_blanks`, building the
sign as a patch in W, 726 B in its FINW-room test image `s2sgt`). This
part's `s2_fin.s` draws the sign by columns straight into the band (no
patch in W, so no W buffer for it beside the band and the slots): its
font helpers `sgchar`, `blanks`, `gcol`, `put` are 289 B of `s2_fin`'s
code, compared against ref816 on every captured sign (section 2).
**What** (for the integrator, one of): (a) keep `s2_fin.s`'s, and part
s2menu2's `s2_sgfont.o` and `s2sgt` are not linked into `FINW`; or (b)
link `s2_sgfont.o` into `FINW`, build the patch in W (about 6 KB for
"INSERT DISK n": the slots' 8 KB are then shared with the units) and draw
it with `s2_vpatch`, removing `sgchar` .. `put` from `s2_fin.s` (its own
code 289 B less, the image 726 B more). (a) is smaller and is the one
checked here.

## 7. Decisions where the design left a choice

- **Upstream's whole redraw.** Every finale and page frame draws the
  whole screen and publishes 32,000 bytes, as upstream does (its
  `V_DrawBackground` and `drawPicture` mark rows 0-199). Lever L-FIN1 (not
  taken): the `HELP2` frames after the wipe change nothing, and a text
  frame changes at most the letters added since the last.
- **Bands of 16 rows for the flat and the text** (the slots can never
  overflow: 16 rows need at most 16 units) and of 40 rows for the
  pictures (no nibble table).
- **The text's walk per band.** Each band walks the text from its start
  (x and y move by the font's widths, a table of 63 bytes) and draws only
  the glyphs whose rows (y .. y + 7: the font's tops are 0 or below and
  no glyph is taller than 8 rows less its top, which `s2fin.py --inc`
  checks) cross the band; `s2_vpatch` clips them exactly.
- **The count.** `(finalecount - 10) * 100 / speed` is computed as
  upstream (int32, the product by shifts, a signed division by 300 for
  the slow speed, below 0 none), saturated at 65,535 letters: the walk
  stops at the text's end (297 letters), so a larger count draws the
  same.
- **The sign drawn by columns**, not built as a patch: the same pixels
  (bmGlyphCol's posts, rows past 7 dropped, each pixel doubled), drawn by
  the nibble rule of `s2_draw.s` into the band.
- **The tic side's `textSpeed`** is in both `s2t_fin.s` and `s2_fin.s`
  (17 B each): the tic image and FINW are separate images.
- **`F_StartFinale`'s automap**: upstream clears `AM_ACTIVE` in
  `automapmode`; natively bit 0 of the frame block's `AUTOMAP` (the
  renderer's), as R6's `AM_Stop` does. `AMAPW`'s own `automapmode` (part
  s2amap, wave 6) is not touched: open problem 2.

## 8. Open problems

1. **Untested paths of the sign.** Every captured sign is "LOADING..."
   with the sign off before it: a new text over a sign that is on (the
   rows put back first, every row published), "SAVING...", "INSERT DISK
   n" (`bmDiskAsk`, the only text of odd width, so the only sign whose
   edges are half bytes) and the failed save's stop run in no compared
   case. A synthetic set (`ref816 --call` of `bmSignOn`, `bmDiskAsk`,
   `bmSignOff` from a captured state) would close it; not built.
2. **`AMAPW`'s `automapmode` at the finale.** `f_start` clears the
   renderer's `AUTOMAP` bit only; if the finale can start with the automap
   active, `AMAPW` (part s2amap) must clear its own `AM_ACTIVE` when it
   next runs (for example from `AUTOMAP`'s bit 0, or a mail bit). No
   compared run starts the finale with the automap on (`F_StartFinale`'s
   one case has `automapmode` 0).
3. **The tic side's state written by the drawer.** `F_Drawer`'s
   `textSpeed` writes `F_MID` (the card) and `WI_ACCEL` (milestone 10's)
   from FINW, as upstream's drawer does; in every compared frame it found
   nothing to change (the ticker takes every request in the same tic).
4. **A text frame takes up to 174 ms on `f121`** (section 5): 32 ms the
   drain of the whole screen, about 36 ms the flat, the rest the glyphs,
   each of which refills `s2_draw`'s fetch buffer (512 bytes) from its
   patch (the same cost as part s2hud's HUD line). Levers: L-FIN1 (section
   7), and a font cache in W for the text stage.
5. **`WI_checkForAccelerate`'s result is the reference's** in the tic
   cases (the hook's order, S2FIN-4): milestone 10 compares that routine
   itself.
6. The part took longer than its 1.5 hours.

## 9. The wave 6 integration (2026-10-02)

What the integrator did with each request (`docs/SCREENS.md` 8.10, "Wave
6 as integrated"):

| Request | Outcome |
| --- | --- |
| S2FIN-1 | Applied as written: `s2layout.FINW_NATIVE` (`F_SIGNON` at `$BF02`) and `PL['SIGNAMEM']` `$C6` (`PL_SIGNAMEM`); `s2_fin.s`'s two stand-ins went (an `.assert` keeps `F_SIGNON` = `OWN` + 2, the three bytes `ownget` moves); `s2fin.py` places the sign's byte by `state_places('FINW')`; the test's stand-in check became a check of the applied places |
| S2FIN-2 | Applied: SCREENS.md 4.3, `s2layout`'s zero-page comment |
| S2FIN-3 | Applied: `FINW`'s own budget 2,300 (`s2fin` 1,600, data 700), `DESIGN_TOTALS['FINW']` 5,700, SCREENS.md 4.1; `finw.sizes` no longer prints `OVER BUDGET`; `s2fin.py`'s data budget is 700 and the test now requires every row of the table, own included, within budget |
| S2FIN-4 | Recorded in `design.md` R4 item 1 (milestone 10's integrator) |
| S2FIN-5 | Recorded in `design.md` R7 item 11 |
| S2FIN-6 | Applied: `FINW`'s runtime text "16 nibble units of 2 pages (bands of 16 rows)"; SCREENS.md 4.1 |
| S2FIN-7 | Applied: SCREENS.md 1.5.6, 6.1 |
| S2FIN-8 | Option (a): `s2_fin.s`'s own column drawer stays; part `s2menu2`'s sign font (`-D M2_SIGNFONT`, `s2sgt`) went (S2MENU2-4) |

Open problem 2 is answered by reading: upstream's `G_DoCompleted` stops
the map before any intermission or finale [R `g_game65.s:754-758`] (R6's
hook mails `MAIL_AMSTOP`), so `F_StartFinale` finds it off and `AMAPW`'s
state is stopped by the mail at its next entry (`s2amap.md` 9).

Results after the integration [M]: `python3 tools/native/s2fin.py
--capture` (9 s) and `--all --jobs 2` (99 s): `report.json` ok, 0
problems; 75 cases, 254 tics, X3 3 frames; the three planted bugs caught
as in section 3; `FINW` 5,405 of 6,656 B, own 2,213 of 2,300.

## The wave 8 integration (2026-10-02)

`tools/native/s2fin.py`'s `store_records` published its cache as an empty
list and then filled it, so a job thread that came second ran with part
of the 2D store (a crash stop with status `$80`, or a run away: wave 6's
unexplained `s2wi` batch failure, and `s2fin`'s in wave 8). The list is
built whole and published in one assignment now; the part's test
`test_the_store_is_never_seen_half_read` fails on the old code
(`docs/SCREENS.md` 8.12).
