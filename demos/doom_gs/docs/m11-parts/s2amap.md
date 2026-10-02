# Milestone 11, part `s2amap`: the automap, full mode

Part `s2amap` of wave 6 ([`docs/SCREENS.md`](../SCREENS.md) 7.3), written
from upstream's `src/iigs/am_map65.s`: `AM_Stop`, `AM_Responder`,
`AM_Start` and `AM_findMinMaxBoundaries`, the window, scale and follow
routines and `AM_Ticker`, the fixed-point helpers, `AM_Drawer`'s full
mode with its byte lists (`eraseOld`, `drawLines`, `showBytes`,
`clearStrip`, `clearView`, `plot`'s `pixFull`), `drawWalls`,
`drawPlayers`, the clip and `drawFL` with `rowColors` [R
`am_map65.s:224-1100`, `:1179-1306`, `:1337-1389`, `:1638-2861`].
2026-10-02. Follows SCREENS.md 1.5.4, 4.1, 6. Labels as in `NATIVE.md`:
[M] measured, [R file:line] read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `src/native/s2_am.s` | The image `AMAPW`'s own code (3,108 B): `am_frame` (the frame's tics through `am_ticker`, then `AM_Drawer`'s full mode in four bands of 42 rows), `am_responder` (`AM_Responder`, with `AM_Start`, `AM_Stop`, `AM_findMinMaxBoundaries`), `am_tick` (one `AM_Ticker`), `am_load`/`am_save` (the state block), the bands, the byte lists and their publish, the colours' nibble cache; it exports `am_seg`, `am_plot`, `am_rowcol` for `s2_amline.s` and the image's places for `s2_pub` (`s2_marks`, `s2_begin`, `s2_begun`) |
| `src/native/s2_amline.s` | The shared object (3,700 B), for `AMAPW` and part `s2ovl`'s `OVLW`: the window, scale and follow routines and `am_ticker`, the 32-bit helpers, `FTOM`/`MTOF`, the rotation, `am_walls` (`drawWalls`: the colour of each line from `LVG0`, `LNMAP`, `LVS` and the sectors), `am_players` (`drawPlayers`), the clip (`mapCode`, `toScreen`, the Cohen-Sutherland loop, `clipX`/`clipY`), `am_drawfl` (`drawFL`) |
| `src/native/s2_am.inc` | The automap's places, shared by both: the state block's fields (from `s2.inc`'s `A_*` and this part's), its zero page and W variables, with three bases another image can move (`AMZ`, `AMW`, `AMST`) |
| `src/native/s2_amt.s` | The test glue (not the game): `amt_case` copies a staged case into place (any main, card or bank range) and runs its events and its call in the cost phase 30; `amt_calls` runs many cases and keeps each one's results in a bank |
| `src/native/m11/s2amap.mk` | `make -C src/native -f m11.mk part P=s2amap`: `gen/s2amap.inc`, the image `amw` (`AMAPW` as the game links it: `s2_am`, `s2_amline`, `s2_pub` alone) and the test image `s2at` (with the glue) |
| `tools/native/s2amap.py` | The reference's capture (`--capture`), the native forms of the level and the state, a host model of upstream's drawing (`--model`), the checks (`--check`), the planted bugs (`--planted`), the timing (`--timing`), `--all` (`report.json`), the include (`--inc`) |
| `tests/wip_test_m11_s2amap.py` | 13 tests (2.1) |

Build output: `build/native/m11/s2amap/` (3.0 MB: the objects, the two
images, `gen/`, `cap/` the capture (1.6 MB), `report.json`). Every run's
directory and every planted bug's scratch copy is a `tempfile` directory
there, deleted after it.

### 1.1 The interface

**Entries** (for the frame driver and the second half; request
S2AMAP-6):

- `am_frame`, A = the tics the frame ran: `AM_Ticker` once a tic (the
  design's "at frame time, run once a tic of the frame", SCREENS.md
  1.5.4), then the full map (nothing unless `automapmode` is active without
  the overlay). After the tics, before `P2DW`. It loads its state block
  from `S2STATE`'s `SS_AMAPW` and writes it back.
- `am_responder`, A = the event's type (0 down, 1 up), X, Y = its key
  (low, high): `AM_Responder`; A = 1 when it took the event. Upstream's
  `D_PostEvent` calls it for every event a level's menu and cheats did not
  take [R `d_main65.s:690-704`], the map key starting the automap.
- `am_tick`: one `AM_Ticker` (the overlay's frames; `s2ovl` may link
  `s2_amline.s`'s `am_ticker` itself).

**The state block** is upstream's fields in the field map's places
(`s2layout`'s `A_*`, `$AC00-$AC61`, upstream's forms) and this part's
four (request S2AMAP-1): `A_MODE` (`AM_MODE`), `A_OLDTOP` (`AM_OLDTOP`),
`A_ON` (the old list's entries) and `A_OB` (its four bands' first
entries), `$AC62-$AC6D`. `am_load`/`am_save` move its first 110 bytes.

**What AMAPW reads** (milestones 7-10's places, read only, through the
generated `s2amap.inc`): the line count `LVCOUNT2`, `LNMAP` (`ML_MAPPED`),
`LVG0`'s lines (the ends, the sides, the special, the flags: 27 bytes of
each record), `LVS`'s `LNSECF`/`LNSECB` (each line's front and back
sector), the sectors' floor and ceiling (`LVMAP`) and oldspecial
(`LVG1`), the player's mobj handle and his RTHING (x, y, the angle's two
words), `powers[pw_allmap]`, `gamemap`, `menuactive`, the HUD's
`message_on` and `message_new` (the card's `HU_ON`, `HU_NEW`), the palette
state's `scb` and `viewpal` (`SS_PALST`) and the nibble tables (`S2NIB`).
**What it writes** besides its own places: `HU_NEW` (upstream's
`clearStrip` and redraw clear `message_new`), `player.message` (the follow
key: milestone 10's reference to `msgFollowOn`/`msgFollowOff`, tag 1),
the frame block's `AUTOMAP` (= `automapmode` after each entry: the
renderer reads it), `S2_MAIL` (below), the screen (aux 0 `$2000-$9CFF`).

**`S2_MAIL`** (request S2AMAP-3): AMAPW applies `MAIL_AMSTOP` (R6: an
`AM_Stop` in the tics) and a new `MAIL_AMVIEW` (a frame drew the view
without the overlay: upstream's `display` zeroes `am_valid` and `am_band`
then [R `d_main65.s:459-462`, `:497-503`]) at its next entry and clears
them; it sets `MAIL_AMSTRIP` (it published rows 0-9 black: `clearStrip` or
the redraw; `hu_drawer`'s A bit 1) and `MAIL_AMTITLE` (rows 160-167 black:
the redraw; A bit 2) for `P2DW`, which redraws the HUD's texts there as
upstream's `HU_Drawer` does after `iigs_textShown` is cleared.

**For part `s2ovl`** (no request: its notes take it): `s2_amline.s`
needs three routines of the linking image, `am_seg` (a clipped line on
the screen: `FL`, `COLI`), `am_plot` (a pixel: `PX`, `LNY`, `NIBH`,
`NIBL`) and `am_rowcol` (the colour's nibbles in row `LNY`), and the bases
`AMZ`, `AMW`, `AMST` (`.ifndef` in `s2_am.inc`: `OVLW` lives in milestone
8's W). It draws the rotation mode through the 32-bit path (`rotate`,
`wallRotation`); upstream's overlay takes its fast path (`fastSetup`,
`fastLine`, `fpoint`, `smul`, the vertex cache [R `am_map65.s:1893-2352`])
whenever `|s cos|` and `|s sin|` stay below 0.25, and its rounding is not
the 32-bit path's: that path is `s2ovl`'s to add.

### 1.2 How a frame is drawn

1. The tics (`am_ticker`), with the player's RTHING read once.
2. Upstream's choice [R `am_map65.s:1059-1087`]: all again (`am_valid` 0,
   the lines' top row changed, a menu) blacks rows 0-167 and draws; else a
   new message blacks the strip's rows 0-9 (`clearStrip`); else only the
   lines' bytes.
3. The rows' colours: each row's palette as upstream's `rowColors` sees it
   (display's `I_ViewPalette(AMAP_PAL)` applied first: `P2DW` does it for
   real after `AMAPW`; then `scb`, where the strip may hold `MSG_PAL`), the
   ten colours' nibbles of each palette (at most 4) from `S2NIB` into a
   160-byte cache.
4. The lines, once a frame: `drawWalls` and `drawPlayers` clip every line
   to the screen and keep it (8 bytes: x0, y0, x1, y1, the colour) in
   `S2STATE`'s `SS_AMSEG` (request S2AMAP-2), a page at a time.
5. Four bands of 42 rows (rows 0-167): each from zeros (the first band and
   after a full list: all 6,720 bytes; else only the bytes the band before
   listed), each kept line whose rows meet the band drawn by upstream's
   Bresenham with the band's rows plotted (the loop stops when the line has
   left them), each plotted byte into the new list (upstream's rule: once
   after the entry before; 2,048 entries, a full list as upstream's
   overflow). Then the band's bytes on the screen, CPU stores in one
   `RAMWRT` window: all its rows when all is drawn again, else the old
   list's entries of the band (from `SS_AMOLD`), the new list's, the strip's
   rows (`clearStrip`), and the lines' rows once the list is full.
6. The new list (by band) into `SS_AMOLD`, its entries and bands into the
   state, `am_valid` 0 after a full list.

The screen after `AMAPW` is upstream's in the lines' rows; the bytes it
publishes are upstream's count (the old and the new lists, or all the
view's rows).

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
df -h /System/Volumes/Data                      # 59 GB free
make -C src/native -f m11.mk part P=s2amap      # no warning
python3 tools/native/s2amap.py --capture        # 3 s, two ref816 runs
python3 tools/native/s2amap.py --all --jobs 2   # 2 min 31 s: report.json
python3 tools/testpar.py --jobs 2 tests/wip_test_m11_s2amap.py
```

Results [M, 2026-10-02]: `report.json` `ok`, 0 problems.

| Item | Result |
| --- | --- |
| The capture | `automap.script` on ref816: 63 full-map frames (each with its start's palette state, `AM_Drawer`'s entry and return, the frame's end) and 415 calls (43 `AM_Responder`, 372 `AM_Ticker`), 11.5 MB of pipe, 0 problems; the level is one (E1M1, 475 lines, 273 sides, 85 sectors) and the fields the automap reads are the same in every frame |
| The host model (`--model`) | equals the reference on all 63 frames: the lines' rows and the new list in upstream's order (the reading of `am_map65.s` the native code follows) |
| Every full-map frame, injected | 63 frames x 2 fills (fill `$A5` with the screen as captured; fill `$5A` with every byte the frame changes poisoned: all view rows when it redraws, else the old and new lists' bytes and the strip): 0 problems. Checked: the lines' rows (`AM_WTOP` .. 159) equal to the reference's screen after the frame; every other screen byte its value before, or black where upstream blacks it (rows 0-167 redrawn, rows 0-9 `clearStrip`); the SCBs and palettes untouched; the state after equal to the reference's at `AM_Drawer`'s return (every field of the map and `AM_MODE`, `AM_OLDTOP`); the new list's set of bytes equal to the reference's; `message_new`, `S2_MAIL`'s bits and `AUTOMAP` as upstream's |
| Kinds of frames | 2 redraws (the first full-map frame, whose palette state still has the view's palette 0, and the one where the message strip turns on), 1 `clearStrip`, 60 of the lists only; up to 1,559 entries a list (the computer map) |
| Chained over the script | the 63 frames in order from the first one's state (8 runs, the state, the old list and the screen carried across runs too), the reference's 31 `AM_Responder` events and 4 tics a frame in between through `am_frame`'s A: 0 problems |
| `S2_MAIL` | a frame of lists with `MAIL_AMVIEW` redraws all (the reference's map, `am_valid` 1, both bits for `P2DW`); with `MAIL_AMSTOP` nothing is drawn, `automapmode` 0, `stopped` 1, `AUTOMAP` 0, the mail cleared |
| Every `AM_Responder` and `AM_Ticker` call | 415 calls x 2 fills from the reference's state at each entry: the state after, the answer and `player.message` equal; chained over all 415 from the first one's state (the fields `AM_Drawer` owns, `am_valid`, `am_band`, `AM_MODE`, `AM_OLDTOP`, left to the frames): 0 problems |
| Paths reached | the zoom (in and out, the minimum scale's clamp once; the maximum never), the pan (44 tics), the follow mode's move (115 tics), follow on and off with their messages, the map key starting the map and going to the overlay, the computer map (the unseen lines' colour), lines clipped at the top (59 ends over the frames), left (8) and right (32) edges (none at the bottom), the colours of walls, floor changes, ceiling changes, closed doors and the arrow [M: the host model's segments]; no keyed door, teleporter or secret sector's bound is drawn in these frames |
| No stray write | 7,136,233 writes judged (the zero page `$80-$D7` and `AMAPW`'s runtime W `$8E00-$BFFF` left out of the log: the snapshots judge them), 0 stray: the driver, the loader, the far layer, the math, the glue, `s2_am`, `s2_amline`, `s2_pub`, each in its allowed set |
| Stack | at most 21 B below the driver's (`--lowest-s-in`), of 64 + 24 |
| `AMAPW` | 6,953 of 10,240 B in its room; no `pl_poll`, no `fx_service` (its modules: `s2_am`, `s2_amline`, `s2_pub`) |
| `tests/test_sound_*` | not touched; green (7 modules, 152 tests) |

### 2.1 The tests

`tests/wip_test_m11_s2amap.py`, 13 tests: without a build, the glue's
constants against the tool, the stage banks against the banks the image
reads, a case's bytes and the directory, the native list's order by band,
the state block's places, each planted edit found once, `AMAPW` linking
the publish alone (7 tests, also OK on Python 3.9.6 with
`PYTHONWARNINGS=error::ResourceWarning`); with the build, the capture
(made when missing), the model, the frames, the calls, the sizes, and the
four planted bugs.

`python3 tools/testpar.py --jobs 2 tests/wip_test_m11_s2amap.py` [M]: 1
module, 13 tests, 0 failures, 0 errors, 0 skipped, 239 s.

## 3. Planted bugs (each in a scratch copy of the sources) and the check that caught it

`python3 tools/native/s2amap.py --planted --jobs 2` (1 min 28 s; fill
`$A5` only). The failures by check: frames injected / chained, calls
injected / chained.

| Bug | Failures | The first [M] |
| --- | --- | --- |
| The y-major loop's step on the wrong axis (its x step a y step) | 86 / 86 / 0 / 0 | `automap/f00 (fill A5): row 4 byte 93: $00, ref $01 (37 bytes differ)` |
| The clip's outcode bits swapped (top and bottom) | 85 / 43 / 0 / 0 | `automap/f00 (fill A5): row 0 byte 94: $00, ref $10 (155 bytes differ)` |
| The follow mode not recentring | 0 / 63 / 115 / 397 | `automap/f42 (fill A5, chained): row 10 byte 96: $00, ref $10 (454 bytes differ)`; the calls: every ticker call that follows a move |
| The zoom applied once a frame instead of once a tic (`am_frame` runs one tic) | 0 / 174 / 0 / 0 | `automap/f05 (fill A5, chained): row 0 byte 94: $10, ref $00 (393 bytes differ)` |

## 4. Sizes against the budget

| Item | Size [M] | Budget |
| --- | ---: | ---: |
| `s2_am` (code and tables 3,103, variables 5) | 3,108 B | |
| `s2_amline` | 3,700 B | |
| `AMAPW` own | 6,808 B | 7,000 B (`s2amap`, 4.1, 7.3) |
| `s2_pub` | 145 B | 200 B |
| `AMAPW` in its room | 6,953 B | 10,240 B (design total 7,200) |
| Zero page | `$80-$AE` (47 B) | `$80-$AF`, SCREENS.md 4.3's `S2A_*` |
| W variables | `$A840-$A8F8` (185 B) | `AMAPW`'s marks range `$A840-$ABFF` |
| W caches | the marks `$A900-$A97F`, the nibble cache `$A980-$AA1F`, the rows' bases `$AA20-$AAC7`, a page `$AB00-$ABFF` | the same range |
| `S2STATE` | `SS_AMAPW` 110 of 1,024 B; `SS_AMOLD` up to 4,096 B; `SS_AMSEG` up to 12,216 of 12,288 B | S2AMAP-2 |

The first build was 7,104 B own (`CP4` copies of 32-bit values expanded
inline); the indexed copies `ld_ma`, `ld_mb`, `st_mr`, `stw_mr`, `mr_ma`
took it to 6,808 B.

## 5. Timing (SCREENS.md 6.4)

`python3 tools/native/s2amap.py --timing` [M]: `am_frame` alone (the
glue's cost phase 30 around it, `--cost-timed`), the 63 frames injected
(fill `$A5`); the responder and the ticker on the script's first 240 calls.

| Frame | Frames | `f121` median / p99 / worst ms | `fastpath` median / p99 / worst ms | the drain in it [A] |
| --- | ---: | --- | --- | --- |
| Lists only | 60 | 13.23 / 62.65 / 62.65 | 11.76 / 56.72 / 56.72 | 0.58 median, 3.09 worst |
| `clearStrip` | 1 | 14.86 | 13.36 | 2.25 |
| Redraw (all again) | 2 | 38.67 | 37.24 | 26.64 |
| All | 63 | 13.25 / 62.65 / 62.65 | 11.76 / 56.72 / 56.72 | |

| Call | `f121` median / worst µs | `fastpath` median / worst µs |
| --- | --- | --- |
| `am_responder` (the worst: `AM_Start` with the level's box, 475 lines) | 109.6 / 8,943.5 | 72.1 / 7,421.2 |
| `am_tick` (load, a tic, save) | 128.2 / 210.9 | 86.1 / 165.9 |

The worst frames (56-63 ms) are the computer map's (every line, 1,557
list entries): the lines' transform and clip (four 32-bit products an
end) and the four bands' Bresenham loops. Apart from the times above:
`AMAPW`'s load, 8,380 B with `MATHW`, about 2.1 ms [A on M: 0.246 µs a
byte, `NATIVE.md` 4.3]; the drain [A on M: 0.991 µs a published byte,
`s2draw.md` 5], inside the times, is upstream's count of bytes.

## 6. Requests (for the integrator; the stand-ins are marked `STANDIN`)

### S2AMAP-1. `tools/native/s2layout.py`: `AMAPW`'s native fields

**Evidence.** `AM_MODE`, `AM_OLDTOP` and the old list's length are
upstream's state the full map reads at its next frame [R `am_map65.s:
119-130`, `:1059-1095`] and are not in the field map; the native list is
kept by band (1.2), so its bands' first entries go with it. **Stand-in.**
`tools/native/s2amap.py`'s `AMAPW_NATIVE` allocated after the field map's
places by the same `R.allocate` (`$AC62-$AC6D`), written into
`gen/s2amap.inc` (marked `STANDIN S2AMAP-1`). **What.** In `s2layout.py`,
after `MENUW_NATIVE`:

```
# AMAPW's own fields with no upstream counterpart (part s2amap, request
# S2AMAP-1): AM_MODE, AM_OLDTOP (bytes), the old byte list's entries
# (AM_ON as entries) and its four bands' first entries
AMAPW_NATIVE = [('A_MODE', 1), ('A_OLDTOP', 1), ('A_ON', 2), ('A_OB', 8)]
OWN_NATIVE = {'P2DW': P2DW_NATIVE, 'MENUW': MENUW_NATIVE,
              'AMAPW': AMAPW_NATIVE}
```

and the field map's `AM_LISTS` row (`_automap()`: `12000, 'bytes', 'bank',
'SS_AMOLD', 2 * 2048`, which no injection can apply: 6,000 words of two
lists into 2,048 entries) becomes deferred, named in `s2state.DEFERRED`:
"`am_map65.s:AM_LISTS`: the old list (the half not at `AM_LB`, `AM_ON`
bytes) as native entries by band, `A_ON` and `A_OB` from it
(`s2amap.native_list`, `encode_state`)". `s2amap.py` reads
`S.OWN_NATIVE['AMAPW']` once it exists and drops its stand-in; nothing
moves.

### S2AMAP-2. `tools/native/s2layout.py`, SCREENS.md 4.5: `SS_AMSEG` in `S2STATE`

**Evidence.** The frame's lines are clipped once and drawn into four bands
(1.2): up to 1,520 lines and the arrow's 7 at 8 bytes (12,216 B), more
than any W `AMAPW` has free. **Stand-in.** `s2amap.ss_amseg()`: the first
byte after `S2STATE_FIELDS` (`$8120`), 12,288 B, in `gen/s2amap.inc`
(`AM_SS_AMSEG`). **What.** `S2STATE_FIELDS` gains, last:

```
    # the full map's lines clipped on the screen, 8 bytes each (part
    # s2amap, request S2AMAP-2)
    ('SS_AMSEG', 0x3000),
```

(`$8120-$B11F`); SCREENS.md 4.5's row 104 adds "the automap's lines of a
frame (`SS_AMSEG`, 12,288 B)", and 104's free part becomes `$B120-$BFFF`
(part `s2data` packs nothing there today [M: `s2data.py --report`]).

### S2AMAP-3. `tools/native/s2layout.py`, SCREENS.md 4.4, `design.md` R6/R7: `S2_MAIL`'s bits

**Evidence.** Upstream's `AM_Drawer` clears `iigs_textShown` in its redraw
and `clearStrip` [R `am_map65.s:1074-1083`, `:1187-1201`] so that
`HU_Drawer` draws the message and the title again over the black rows;
`display` zeroes `am_valid` in every frame that draws the view and
`am_band` in those without the overlay [R `d_main65.s:459-462`, `:497-503`].
`AMAPW` runs only in full-map frames and `P2DW` after it. **Stand-in.**
`MAIL_AMSTRIP` `$04`, `MAIL_AMTITLE` `$08`, `MAIL_AMVIEW` `$10` in
`gen/s2amap.inc`. **What.** In `s2layout.py` beside `MAIL_AMSTOP`:

```
MAIL_AMSTRIP = 0x04             # S2_MAIL bit 2: AMAPW published rows 0-9
                                #   black (hu_drawer's A bit 1; S2AMAP-3)
MAIL_AMTITLE = 0x08             # bit 3: rows 160-167 black (A bit 2)
MAIL_AMVIEW = 0x10              # bit 4: a frame drew the view without the
                                #   overlay since the automap last ran
```

in the `s2.inc` lines with `MAIL_AMSTOP`; SCREENS.md 4.4's `S2_MAIL`
"(1 B: bit 1 the automap stopped, request R6)" becomes "(1 B: bit 1 the
automap stopped, R6; bits 2 and 3 the strip's and the title's rows black,
for `P2DW`; bit 4 a view drawn, for the automap: S2AMAP-3)"; `design.md`
R7 item 7's "(a byte `AMAPW` leaves for `P2DW`, e.g. in `S2_MAIL`)" becomes
"(`S2_MAIL`'s `MAIL_AMSTRIP`, `MAIL_AMTITLE`, which `P2DW` clears)", and a
new item: "In every level frame that draws the view without the
automap's overlay, and when a paused frame puts the view back
(`I_RestoreView` [R `d_main65.s:459-462`]), set `S2_MAIL`'s `MAIL_AMVIEW`;
the automap (`AMAPW`, `OVLW`) zeroes `am_valid` and `am_band` at its next
entry. An overlay frame zeroes `am_valid` itself (part `s2ovl`)."

### S2AMAP-4. `tools/native/s2layout.py`: the full map's stops

**What.** In `PL` (the stop codes in `PL_STATUS`): `'AMPALS': 0xD1` (a
frame whose lines' rows use more than 4 palettes: impossible upstream,
whose full map has palettes 11 and the strip's 10) and `'AMSEGS': 0xD2`
(more clipped lines than `SS_AMSEG` holds: impossible with 1,520 lines).
Stand-in: `AMS_PALS`, `AMS_SEGS` in `s2_am.s` (marked).

### S2AMAP-5. SCREENS.md 1.5.4, 4.1, 4.3: the full mode as built

**What.** 1.5.4's full row, the native column, becomes:

```
`AMAPW` (`am_frame`, A = the frame's tics: `AM_Ticker` once a tic, then
the map): the frame's lines clipped once into `S2STATE`'s `SS_AMSEG`
(upstream's `drawWalls`, `drawPlayers`), then four bands of 42 rows, each
from zeros, each line that crosses it drawn with upstream's Bresenham and
only the band's rows plotted, each plotted byte into the new list (2,048
entries [A], a full list as upstream's overflow); published: all rows
when upstream redraws all, else the old list's and the new list's bytes
(both by band, the old in `SS_AMOLD`) and the strip's rows (`clearStrip`);
upstream's count of bytes. The screen after it is upstream's in the
lines' rows; the strip's and the title's rows it blacks are `P2DW`'s
(`S2_MAIL`, S2AMAP-3). Part s2amap, docs/m11-parts/s2amap.md
```

and a named difference after the paragraph "A full-automap frame draws":
"**D-AM1.** `AMAPW` publishes before `P2DW`'s `s2_begin`: in the frame
where the view's rows take the map's palette (`I_ViewPalette(AMAP_PAL)`,
the first full-map frame) or the strip turns on, the map's bytes reach the
screen before their SCBs (upstream's redraw shows the SCBs first; its
lists, `showBytes` inside `AM_Drawer`, the bytes first). The frame's final
screen is upstream's. `AMAPW` never calls `s2_begin` (its `s2_begun` is
1)." 4.1's size table, `AMAPW`'s own: "7,000 (`s2amap`)" becomes "7,000
(`s2amap`: 6,808 [M])"; its runtime text "`$A840-$AFFF` marks and state"
stays. 4.3's `$80-$AF` row adds "the automap's `$80-$AE` (part `s2amap`)".

### S2AMAP-6. `design.md` R7 (the frame driver, the second half): the automap's calls

**What.** A new item: "The automap (part `s2amap`): an event a level's
menu and cheats did not take goes to `AMAPW`'s `am_responder` (A the
type, X and Y the key) when `automapmode` is on, or when it is the map
key's key down (upstream's `AM_Responder` takes nothing else while the map
is off [R `am_map65.s:244-261`]), `far_pload` of `AMAPW` (bank 94) first;
the game's responder when A is 0 after it. In a full-map frame
(`AUTOMAP` active without the overlay), after the tics: `far_pload` of
`AMAPW`, `jsr am_frame` with A = the frame's tics, then `P2DW` (R7 item
3). In an overlay frame the tics' `AM_Ticker` is `OVLW`'s (part `s2ovl`:
`s2_amline.s`'s `am_ticker` once a tic) or `AMAPW`'s `am_tick` once a
tic." The first full-map frame's `AMAPW` load is 2.1 ms [A]; the
responder's load each event while the map is on is the driver's cost
(open problem 3).

## 7. Decisions where the design left a choice

- **The lines once, the bands four times.** Upstream draws each line once
  into a full back buffer; the bands need each line where it crosses
  them, so the transform and the clip run once a frame and the clipped
  lines wait in `S2STATE`; the Bresenham loop of a line runs in each band
  it crosses, from its start (its pixels are upstream's whatever the
  band), and stops when the line leaves the band for good.
- **The lists by band.** The old list is published band by band from the
  band's bytes (so a byte in both lists goes out once with its new value,
  as upstream's `copyList`s write the back buffer's final bytes); the new
  list is built band by band, and is the next frame's old list. An
  injected upstream list is sorted by band (`native_list`).
- **Clearing a band** costs its listed bytes after the first band
  (every nonzero byte is listed while the list is not full).
- **The rows' palettes.** `AMAPW` runs before `P2DW`'s `s2_viewpal`, so it
  applies upstream's `I_ViewPalette(AMAP_PAL)` itself for the nibbles
  (all 168 rows palette 11 when `viewpal` is not 11), without writing the
  palette state; the first frame of the script is such a frame.
- **The colours** are indexes (10 of them: `COLOR_SNGL` is `COLOR_CLSD`'s
  208); a palette's 40 nibbles (two parities, two sides) are fetched from
  `S2NIB` once a frame.
- **`AUTOMAP`** (the frame block's byte the renderer reads) is written from
  `automapmode` at the end of each entry; `A_AUTOMAPMODE` stays upstream's
  word.
- **The test's truth** is a capture of this part's own: part s2cap's cases
  hold no level (the zone), and `AM_Drawer`'s entry (after display's
  `I_ViewPalette`) and the frame's start (before it) are both needed.
- **The test's write log** leaves out the zero page `$80-$D7` (the math's
  and the automap's, thousands of writes a line) and `AMAPW`'s runtime W;
  the snapshots judge the screen, the state, the list and the card.

## 8. Open problems

1. **`AM_Ticker` at frame time** (the design's, SCREENS.md 1.5.4) runs
   every tic with the frame's last player position. Upstream's follows the
   position of each tic; the two agree whenever no tic's move and a zoom
   fall in the same frame (follow recentres from the position alone), which
   holds in `automap.script` (the player moves while the map is idle and
   the zoom happens standing). A move and a zoom in one frame can put the
   window a map unit off. Exact for every case would need the tics' last
   moved position and scale (a tic-side call, R4) or the ticker tic-side.
2. **The overlay's fast path** (`fastLine`) is part `s2ovl`'s; `s2_amline`
   gives it the 32-bit path, whose rounding differs.
3. **The responder's load**: `AMAPW` is 8.4 KB with `MATHW`; loading it for
   every automap key event (2.1 ms [A]) is the second half's cost to weigh
   (S2AMAP-6).
4. **Coverage**: one level (E1M1); no compared frame reaches the maximum
   scale's clamp, the overflow of the list (2,048 entries; the most a frame
   listed was 1,559), a clip at the bottom edge, or the colours of keyed
   doors, teleporters and secret sectors (their code is upstream's line
   for line, and the host model draws them the same way, but no frame
   compares them); a synthetic set (`ref816 --poke-file` of a line's
   special and a sector's oldspecial at a named tic) would close it. The
   half and two-thirds views (`halfOvl`, `AM_Clean`) are milestone 13's.
5. **D-AM1** (S2AMAP-5): the map's bytes before their SCBs in the first
   full-map frame, for the time between `AMAPW`'s and `P2DW`'s publishes.
6. The part took longer than its 1.5 hours.

## 9. The wave 6 integration (2026-10-02)

What the integrator did with each request (`docs/SCREENS.md` 8.10, "Wave
6 as integrated"):

| Request | Outcome |
| --- | --- |
| S2AMAP-1 | Applied as written: `s2layout.AMAPW_NATIVE` in `OWN_NATIVE` (`A_MODE`, `A_OLDTOP`, `A_ON`, `A_OB` at `$AC62-$AC6D`, the stand-in's places); `s2state.DEFERRED` names `AM_LISTS` with the request's text. `s2amap.py` takes the fields from `s2layout`; `gen/s2amap.inc` no longer defines them (they are `s2.inc`'s) |
| S2AMAP-2 | Applied: `SS_AMSEG` last in `S2STATE_FIELDS`, `$8120-$B11F`; `s2_am.s` uses `s2.inc`'s `SS_AMSEG` (`AM_SS_AMSEG` went); `s2layout.check()` now tests the last field against `$BFFF`; bank 104's free part `$B200-$BFFF` (the 2D store places nothing there: `s2data.py --check --report` unchanged) |
| S2AMAP-3 | Applied: `MAIL_AMSTRIP` `$04`, `MAIL_AMTITLE` `$08`, `MAIL_AMVIEW` `$10` in `s2layout` and `s2.inc`; SCREENS.md 4.4; `design.md` R7 item 7's text and a new item 13 |
| S2AMAP-4 | Applied: `PL['AMPALS']` `$D1`, `PL['AMSEGS']` `$D2` (`PL_AMPALS`, `PL_AMSEGS`); `s2_am.s`'s `AMS_*` went; SCREENS.md 4.2 |
| S2AMAP-5 | Applied: SCREENS.md 1.5.4's full row and D-AM1, 4.1's own row (6,808 [M]), 4.3 |
| S2AMAP-6 | Recorded in `design.md` R7 item 12 |

Part `s2fin`'s open problem 2 (`AMAPW`'s `automapmode` when a finale
starts) needs nothing here: upstream's `G_DoCompleted` stops the map
before any intermission or finale [R `g_game65.s:754-758`], whose hook
(R6) mails `MAIL_AMSTOP`, so `F_StartFinale`'s clear of `AM_ACTIVE` finds
it off, and the mail stops `AMAPW`'s state at its next entry.

Results after the integration [M]: `python3 tools/native/s2amap.py
--capture` (3 s: 63 frames, 415 calls, 0 problems) and `--all --jobs 2`
(151 s): `report.json` ok, 0 problems; the four planted bugs caught as in
section 3; `AMAPW` 6,953 of 10,240 B, own 6,808 of 7,000; the timing as in
section 5.

## 10. Wave 7 (2026-10-02)

Part s2ovl's request S2OVL-1 was applied to `s2_amline.s`: the rotation's
fast path's hook (open problem 2's fast path is `s2_ovl.s`'s
`am_fastsetup` and `am_fastline`), inside `.ifdef AM_FASTLINE`, which only
`OVLW`'s build defines. `AMAPW`'s `s2_amline` is the same 3,700 B
(`docs/m11-parts/s2ovl.md` 9); this part's checkpoint was rerun after it
(`docs/SCREENS.md` 8.11).
