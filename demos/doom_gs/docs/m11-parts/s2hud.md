# Milestone 11, part `s2hud`: the HUD, its ticker and its cached drawer

Part `s2hud` of wave 4 ([`docs/SCREENS.md`](../SCREENS.md) 7.3), written
from upstream's `src/iigs/hu_stuff65.s` (`HU_Init`'s rows, `HU_Start`,
`HU_Drawer`, `drawTextLine`, `HU_Ticker` but its clears) and
`src/iigs/i_viigs65.s` (`I_DrawCachedText`, `I_EndTextCapture`,
`textInvalidate`, `I_MessageStrip`'s clear). 2026-10-01. Follows
SCREENS.md 0.1 F8, 1.4, 1.5.2, 1.6, 4.4, 4.7, 6.3 X1 and `design.md` R5,
R7. Labels as in `NATIVE.md`: [M] measured, [R file:line] read, [A]
assumed.

## 1. What was built

| File | What |
| --- | --- |
| `src/native/s2t_hu.s` | The tic-side module (100 B): `hu_ticker` (`HU_Ticker` but the clears [R `hu_stuff65.s:244-276`]: the counter's decrement and `message_on` 0 at its end, then, with `G_SHOWMSG` or `G_MSGKEEP` and `player.message` set, the line's message id, `message_on`, `message_new`, the counter 140) and `hu_start` (`HU_Start`'s state [R `:94-118`]: `message_on` 0, the line empty, the title's map). Their state is the card's `HU_*` (`s2layout` `S2T_FIELDS`) |
| `src/native/s2_hu.s` | The drawer in `P2DW` (1,411 B: code 1,125, the font table 252, its tables 6, variables 28): `hu_drawer`, the map's title (slot 1, rows 160-167) then the message (slot 0, rows 0-9), each composed in `P2DW`'s band and published; the text cache with a record (CAPVAL, CAPMSK) of each slot's line in `S2STATE` instead of upstream's generated code; `textInvalidate` from `PALST`'s `PS_TXTINV`; `I_MessageStrip`'s clear |
| `src/native/s2_hut.s` | The test glue (not the game): `hut_tics` (the tic calls, chained or injected, with a **STANDIN** of milestone 10's `hu_tick` after `hu_ticker`, request R5's order) and `hut_frames` (the frames' inputs, then `hu_drawer` alone in the cost phase 30) |
| `tools/native/s2msgs.py` | The generator: the message ids' texts (milestone 10's numbering, `llayout.symbol_list()`), the maps' titles, the font table; the bank file `HUDTXT.1` (the texts' table `SS_HUDMSG` in `S2STATE`), `gen/s2msgs.inc` (the font), `gen/s2hud.inc` (the game's places, the stand-ins) |
| `tools/native/s2hud.py` | The checks: the captures (ref816 call logs of `display`, `HU_Drawer`, `HU_Ticker`, `HU_Start`, `R_RenderPlayerView` and what a frame does to the HUD's rows), the cases, the native runs on a2vm and their write logs, the synthetic ref816 `--call` truth, the planted bugs, the timing, `report.json` |
| `src/native/m11/s2hud.mk` | `make -C src/native -f m11.mk part P=s2hud`: the includes, `HUDTXT.1` and `HUDTXT-test.1`, the test image `s2ht` in `P2DW`'s room |
| `tests/wip_test_m11_s2hud.py` | 11 tests (2.1) |

Build output: `build/native/m11/s2hud/` (the image, `gen/`, the bank
files, `cases/` the four call logs, 1.4 MB, `synth/` the `--call` truth,
`report.json`). Every run's directory is a `tempfile` directory there,
deleted after the run.

### 1.1 The interface

**Tic side** (GAME.md's conventions; no zero page, X and Y kept):
`hu_ticker` and `hu_start` read `player.message` (`G_PLAYER` + 111: the
tag, 0 for NULL, then the id), `G_SHOWMSG`, `G_MSGKEEP`, `G_GAMEMAP`, and
write only `HU_ON`, `HU_NEW`, `HU_COUNTER`, `HU_MSGID`, `HU_TITLEMAP`.
Request R5's order: `flow`'s `hu_tick` calls `hu_ticker` first, then
clears `player.message` and `G_MSGKEEP`; the `HU_Start` hook calls
`hu_start`, then clears `G_MSGKEEP`. `hu_start` sets `HU_MSGID` to
`$FFFF` (upstream's `strcpy` of an empty line).

**The message ids.** Natively `player.message` is a reference to a
symbol whose id is its index in `llayout.symbol_list()` (every rodata
label, sorted: the bridge's numbering), so the HUD's table and milestone
10 agree by construction. `s2msgs.py` takes the **message symbols**: the
labels referenced as `.word0 NAME` in the units that store a value into
`player.message` (`sta`/`stx` of `OFS_PL_MESSAGE`: `am_map65.s`,
`m_cheat65.s`, `m_menu65.s`, `p_doors65.s`, `p_inter65.s`) whose bytes
start with a string of 1-34 printable characters: 51 labels, 1,022 B [M].
Five are never messages (`keyNames`, whose first name is "A", and
`txComma`, `txControls`, `txNone`, `txPress`): harmless. Every message of
the four runs is in the table (the cases fail otherwise).

**The frame side.** `hu_drawer` with A = the frame's flags (request
S2HUD-2): bit 0, the strip is cleared (`s2_stripearly`'s C: rows 0-9
black and marked, the message off the screen); bit 1, the message's text
is off the screen (the view drew rows 0-9, `VIEWTOP` `$FF`; the full map's
`clearStrip` or `clearView`); bit 2, the title's text is off the screen
(a view frame without the overlay; the map's `titleBand` with `am_band`
0, `clearView`, `AM_Clean`). It reads `HU_ON`, `HU_MSGID`, `HU_TITLEMAP`,
`AUTOMAP` bit 0, `PALST`'s `PS_SCB` (the rows' palettes) and
`PS_TXTINV`, and `P2DW`'s own state: `P_TITLE`, `P_MESSAGE` (upstream's
lines), `P_TXTVALID`, `P_TXTLEN`, `P_TXTY`, `P_TXTSHOWN` (upstream's words)
and the stand-ins `P_TXTTEXT`, `P_MSGFILL`, `P_MAPFILL` (request S2HUD-1).
It runs after the status bar is published (it reuses the band and takes
nibble slots from the last one down).

**The texts** are in RamWorks, not in `P2DW` (request S2HUD-3, SCREENS.md
risk 12's first remedy): `SS_HUDMSG` in `S2STATE`, an index of 256 words
(a key's entry, 0 for none) then 36-byte entries (the text padded to 35,
its length), 2,672 B [M]. A message's key is its id (below `$E6`), a
title's `$F0` + map. A line's text is fetched (`far_get` of 2 and 36
bytes) only when its id changes (`P_MSGFILL`, `P_MAPFILL`). `P2DW` keeps
the font: each glyph's bank, address and width (`STCFN033`-`STCFN095`,
part `s2data`'s places, DOOM1.WAD's widths).

**The band and the record.** A line is composed from black: the strip is
black under a message (`I_MessageStrip` clears it when it turns on and
for each new message; the full map's `clearStrip`, `clearView`), the
title's rows are black under the title (`titleBand`, `clearView`), so a
line drawn again over its own pixels gives upstream's bytes. All 794
frames of the four runs check this (2). The band's rows 0-9 (the title's
0-7) hold the line, 10-19 CAPVAL, 20-29 CAPMSK (`s2_draw`'s capture);
the record (13 pages) goes to `SS_HUDTXT` + slot × `$1000` after a fresh
draw and comes back for a replay: `byte & ~CAPMSK | CAPVAL` over the
line's rows, which are marked whole (upstream's `markRows(y, y +
TEXT_H)`, clipped to the band).

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
df -h /System/Volumes/Data                          # 69 GB free
make -C src/native -f m11.mk part P=s2hud           # no warning (but see S2HUD-4)
python3 tools/native/s2hud.py --all                 # captures, f121 and fastpath, planted
python3 tools/testpar.py tests/wip_test_m11_s2hud.py
```

Results [M, 2026-10-01]: `report.json` `ok`, 0 problems, on `f121` and on
`fastpath` (the same runs twice: the checks do not depend on the
profile). The captures take 13 s with 2 jobs (demo3's pipe 35 MB, the
four call logs 1.4 MB zlib'd); the whole `--all` about 4 minutes.

| Run | `HU_Ticker`, `HU_Start` | PV | `HU_Drawer` frames | Lines: on the screen / replayed / drawn afresh | Excluded | Problems |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| demo3 | 2,136 | 534 | 534 | 376 / 6 / 17 | | 0 |
| newgame | 514 | 129 | 128 | 0 / 0 / 0 (no message) | | 0 |
| menus.script | 165 | 41 | 40 | 33 / 0 / 2 | 3 frames: the menu over the screen (`s2menu1`'s region) | 0 |
| automap.script | 373 | 30 | 92 | 131 / 1 / 6 (the title: 80 / 1 / 3) | | 0 |
| synthetic | 64 `HU_Ticker` calls | | 12 lines | 0 / 0 / 12 | | 0 |

| Checkpoint item | Result |
| --- | --- |
| Strip rows and title rows equal | every frame of the four runs: the screen's rows 0-9 (strip on) and 160-167 (map up) after the native frame (display's entry rows, the map's blacks of S2HUD-2, then the bytes `s2_publish` stored, from the write log) equal display's return; 3 frames excluded and named (a menu opened over them) |
| The cache replay equal to a fresh draw on every cached frame | the 794 frames again with `PS_TXTINV` every frame (every line drawn afresh): the same screens on every frame, the 7 replays and the 764 frames with nothing to draw included |
| The text cache | after every frame `textValid`, `textLen`, `textY`, `iigs_textShown` and each valid slot's text equal `HU_Drawer`'s return; the lines' texts and lengths equal upstream's; 24 frames draw a line afresh, as upstream's |
| `hu_ticker` on every tic | 3,188 calls of `HU_Ticker` and `HU_Start` (4 `HU_Start`), chained (the native state carried; `message_new` from the reference, the frame side's) and injected (each from the reference's entry): the counter, `message_on`, `message_new`, the line's text, `player.message` and `G_MSGKEEP` after each equal; for `HU_Start` the title too |
| `message_on` at PV and R7's `VIEWTOP` | 734 level frames: `message_on` after the frame's tics (the chained native state) equal PV's, and 9 when it is set and `DD_PAUSED` 0, else `$FFFF`, equal upstream's `viewtop` |
| Rows 0-9 never written when the strip is off | no store of `s2_publish` in rows 0-9 with the strip off (nor in 160-167 with the map off), on every frame of the write logs |
| The synthetic cases (ref816 `--call` on part `s2draw`'s base state) | `HU_Ticker` at the counter's edges (0, 1, 2, 139, 140, 255, 256, 257) × a message or none × `showMessages` and the keep: 64 calls equal; `HU_Drawer` of every font character, lower case, the characters outside the font (`` ` ``, `{`-`~`, `$7F`, control and high bytes), spaces, and titles whose last glyph ends at x = 319, 320 (drawn) or 321 (cut) and whose spaces reach 320 (titles of 41-44 bytes running on through their own length into `w_message`, as upstream's loop reads them): 12 lines, the back buffer's rows and the cache equal |
| D2 (the title's replay) | the one title replay: rows 168-169 of upstream's back buffer equal the screen's |
| Every message is in the table | every `player.message` of the four runs resolves to a message symbol, every line's text to a table entry |
| No stray write | 0 on every run's write log (the driver, the loader, the far layer, the glue, `s2_hu`, `s2t_hu`, `s2_draw`, `s2_pub`, the stand-in `s2_begin` never runs) |
| Stack | 15-17 B in the HUD's code (`--lowest-s-in`), of the 64 B of SCREENS.md 4.3 |
| `tests/test_sound_*` | not touched; green (7 modules, 152 tests, with this part's module in one `testpar` run) |

### 2.1 The tests

`tests/wip_test_m11_s2hud.py` (11 tests): the generator's rules on
hand-made text (the store rule, the keys, the line's end), which need no
build; then the message table, the bank table read back, the include
(no name of `s2.inc` defined again), every tic and PV, every frame, the
synthetic cases, the sizes, and the seven planted bugs. It captures the
call logs when they are missing. Without `build/` the first three run
and the others skip naming what is missing.

`python3 tools/testpar.py --jobs 2 tests/wip_test_m11_s2hud.py
tests/test_sound_*.py` [M]: 8 modules, 163 tests, 0 failures, 0 errors,
0 skipped (this module 11 tests in 101 s, the planted bugs included). The
three hand-made tests also pass on Python 3.9.6 with `-W
error::ResourceWarning`, and both tools compile there.

## 3. Planted bugs (each in a scratch copy of the sources) and the check that caught it

| Bug | Caught by | The first failure [M] |
| --- | --- | --- |
| The replay not marking its rows (`replay` ends without `s2_mark`) | the title's replay of automap.script (2 problems) | `call 255: the title row 160 byte 1: $00, ref $BB` |
| Lower case not mapped | every line with lower case (523) | `call 1089: the strip row 0 byte 4: $00, ref $BB` |
| The space width 3 | every line with a space (528) | `call 1089: the strip row 0 byte 23: $0B, ref $00` |
| The line cut at 319 (`x + w > 319`) | the synthetic title whose last glyph ends at 320 (1) | `synthetic 9 (title): the title row 160 byte 156: $00, ref $3F` |
| `message_on` cleared a tic late | demo3's chained tics (24) | `demo3 chained call 1499: message_on 1, ref 0` |
| The counter tested after the take (the end's test before the take, its clear of `message_on` after it: a new message dies at once when the old counter reaches 1) | the synthetic tic with the counter at 1 and a message (3) | `synthetic tic 13 [1, 1, 1, 0]: message_on 0, ref 1` |
| `hu_ticker` reading `player.message` after `hu_tick`'s clear (the glue's order swapped) | every take of the runs (7,523) | `demo3 chained call 1084: message_on 0, ref 1` |

The first three are drawing bugs the captures catch; the cut and the
counter's edge happen in no run (no line of upstream reaches 320 pixels,
no message arrives on the counter's last tic), so the synthetic `--call`
cases are what catch them.

## 4. Sizes against the budget

| Item | Size [M] | Budget |
| --- | ---: | ---: |
| `s2_hu` in `P2DW` (code 1,125, the font 252, its tables 6, variables 28) | 1,411 B | 1,700 B (`s2hud` 700, texts 1,000) |
| of which the code | 1,125 B | 700 B [A] (over: open problem 2) |
| `s2t_hu` (tic side) | 100 B | 150 B |
| The texts' table `SS_HUDMSG` in `S2STATE` (51 messages, 9 titles) | 2,672 B | its stand-in room 3,072 B (S2HUD-3) |
| The records `SS_HUDTXT` | 2 × 3,328 B | 2 × 4,096 B |
| `P2DW`'s state block (the stand-ins of S2HUD-1) | 83 B | its free 118 B after `$BF8A` |
| Zero page | `S2_*` (the drawers'), `S2P_A` (a pointer, never live across a call) | `$48-$7F` |
| The test image `s2ht` in `P2DW`'s room (with the glue 921 B) | 3,626 B | 7,424 B |

The first build, with the texts in `P2DW`, was 2,835 B (S2HUD-3).

## 5. Timing (SCREENS.md 6.4)

`python3 tools/native/s2hud.py --all` [M]: each frame's `hu_drawer` alone
(the glue's cost phase 30 around the call; the frame's clock from the
write log's `PHASE` stores, `--cost-timed`), 794 frames of the four runs;
each tic call the same way.

| Frame | Frames | `f121` median / p99 / worst ms | `fastpath` median / p99 / worst ms |
| --- | ---: | --- | --- |
| Nothing to draw (the lines on the screen, or none) | 764 | 0.023 / 0.037 / 0.037 | 0.023 / 0.037 / 0.037 |
| A replay (the record fetched, 1,600 B replayed, published) | 6 | 3.836 / 3.842 / 3.842 | 3.512 / 3.519 / 3.519 |
| A line drawn afresh (its nibble table, the glyphs, the record saved) | 24 | 15.17 / 22.02 / 22.02 | 12.08 / 17.41 / 17.41 |
| All | 794 | 0.023 / 17.75 / 22.02 | 0.023 / 14.13 / 17.41 |
| `hu_ticker`, `hu_start` (a call) | 3,188 | 1 / 1 / 3 µs | 1 / 1 / 2 µs |

The drain of the published bytes is in these times (a fresh strip with
its clear publishes 1,600 B: about 1.6 ms of drain at 0.991 µs a byte
[M: `s2draw.md` 5]). `P2DW`'s load and its state's write-back are the
frame's, not the HUD's (SCREENS.md 6.4: reported apart by the images'
parts).

## 6. Requests (for the integrator; the stand-ins are marked `STANDIN`)

### S2HUD-1. `tools/native/s2layout.py`, the field map: the text cache's texts and the lines' ids in `P2DW`'s block

**Evidence.** `textText` (80 B) is `'bank'` `SS_HUDTXT` in `_hud()`, so the
cache's key (the slot's text) would need a `far_get` every frame a line
is up (upstream compares the text every frame [R `i_viigs65.s:1796-1818`]);
`P2DW`'s own block has room (its fields end at `$BF8A`). The drawer also
keeps, for each line, the id its text was fetched for. **Stand-in.**
`s2msgs.hud_inc_text()`: `P_TXTTEXT` `$BFB0` (80), `P_MSGFILL` `$BFAC` (2),
`P_MAPFILL` `$BFAE` (1), marked `STANDIN` in the generated `s2hud.inc`
(the generator fails if the block's fields reach `$BFAC`). **What.** In
`_hud()`:

```python
-        _f(s, 'i_viigs65.s:textText', 80, 'bytes', 'bank', 'SS_HUDTXT'),
+        _f(s, 'i_viigs65.s:textText', 80, 'bytes', 'state', 'P_TXTTEXT'),
```

and, as `PALST_NATIVE` does for `PALST`, the block's native fields after
the field map's (`state_places('P2DW')` allocates them next):

```python
# P2DW's own fields with no upstream counterpart (part s2hud, request
# S2HUD-1): the message id P_MESSAGE's text was fetched for, the map
# P_TITLE's was
P2DW_NATIVE = [('P_MSGFILL', 2), ('P_MAPFILL', 1)]
```

Then `s2msgs.hud_inc_text()` drops its three stand-ins (they come from
`s2.inc`) and `s2hud.state_block()` takes them from `state_places`.

### S2HUD-2. The frame driver (R7), `AMAPW` (`s2amap`) and `OVLW` (`s2ovl`): `hu_drawer`'s flags

**Evidence.** Upstream's display clears `iigs_textShown` in places that
are not the HUD's: `I_MessageStrip`'s clear [R `i_viigs65.s:526-552`],
after `R_DrawLists` when the view drew rows 0-9 (`VW_STRIPV` [R
`d_main65.s:503-506`]), in a view frame without the overlay [R
`d_main65.s:497`], and in the map's `clearStrip`, `clearView` (`redraw`),
`titleBand`, `AM_Clean` [R `am_map65.s:1074-1081`, `:1173`, `:1188-1215`].
Natively those are other images. **What** (no stand-in needed: the
interface is `hu_drawer`'s A): `P2DW`'s frame calls `jsr hu_drawer` after
the status bar is published with A =

| Bit | Set when | By |
| --: | --- | --- |
| 0 | `s2_stripearly` returned C = 1 (the strip turns on, or a new message) | `P2DW`'s frame (`s2pal`'s `s2_stripearly`) |
| 1 | a view frame with `VIEWTOP` `$FF` (the view drew rows 0-9); a full-map frame whose `AMAPW` ran `clearStrip` or `clearView` | the frame driver; `AMAPW` (a byte it leaves for `P2DW`, e.g. in `S2_MAIL`) |
| 2 | a view frame without the overlay; a frame whose map ran `clearView`, `titleBand` with `am_band` 0, or `AM_Clean` | the frame driver; `AMAPW`, `OVLW` |

and those images publish their own black rows (rows 0-9, 160-167). The
checkpoint derives the flags from the reference's calls of these
routines in each frame (`s2hud.frame_cases`) and checks the screen and
the cache on all 794 frames, so these rules are the ones to implement.

### S2HUD-3. `S2STATE`: the texts' table `SS_HUDMSG`, and its bank file

**Evidence.** With the 51 messages' and 9 titles' texts in `P2DW` the
drawer was 2,835 B, 1,135 over its 1,700 B (`s2hud` 700, texts 1,000;
SCREENS.md 4.1) [M: the first build]. SCREENS.md risk 12's first remedy
is "`P2DW`'s ... texts to its state block's bank"; a line's text is
needed only when its id changes. **Stand-in.** `s2msgs.SS_HUDMSG` `$6200`,
size `$0C00`, after `s2layout`'s `SS_*` (which end at `$6120`), marked
`STANDIN`; the bank file `build/native/m11/s2hud/HUDTXT.1` (one segment:
bank 104 at `SS_HUDMSG`, 2,672 B). **What.**

1. `s2layout.S2STATE_FIELDS`: after `('SS_SIGN', 4096)` add
   `('SS_HUDMSG', 0x0C00),   # the HUD's texts (part s2hud: HUDTXT.1)`
   (it lands at `$6120`; the code needs no alignment); then
   `s2msgs.SS_HUDMSG` reads `S.SS['SS_HUDMSG']` and the stand-in goes.
2. The boot (`plboot`, SCREENS.md 2.5 step 2) loads `HUDTXT.1` with the
   other bank files (or part `s2data` makes the table a lump of `GFX.n`
   at that place: `s2msgs.bank_table()` gives its bytes).
3. SCREENS.md 1.5.2, last sentence: "The id's text comes from a string
   table in `P2DW`'s data, generated ..." becomes "The id's text comes
   from a table in `S2STATE` (`SS_HUDMSG`, the bank file `HUDTXT.1`),
   fetched when the line's id changes, generated from upstream's message
   symbols by the list milestone 10 numbers them with (`s2msgs.py`; risk
   12's first remedy); `P2DW` keeps the font's places and widths". 4.1's
   size table: `P2DW`'s own "s2hud 700, texts 1,000" becomes "s2hud
   1,411 (the font 252) [M]". 4.5, row 104: add "the HUD's texts
   (`SS_HUDMSG`, 2,672 B [M: part s2hud])".

### S2HUD-4. `s2layout.check()` against milestone 10's `gflow.s` (for the integrator and milestone 10)

**Evidence.** Milestone 10's work in progress `src/native/game/flow/gflow.s`
now stores `lda #2 * FL_PH_RESUME` (62: phase 31) [R `gflow.s:892-893`],
following wave 3's note; `check()` refuses any phase-31 writer but the
platform's, so `make -f m11.mk` cannot regenerate `s2.inc` once a layout
file is newer than it: "ValueError: src/native/game/flow/gflow.s:893
writes the phase 31, the platform's" [M]. The current includes are what
`s2layout` writes (checked with `check()` bypassed in a scratch process:
all four equal) [M]. **Stand-in.** `s2hud.make()` retries with `make -o`
on the four shared includes and `rlayout.inc` when the build fails that
way, and says so. **What** (the integrator's choice with milestone 10):
milestone 10 uses phases of its own (GAME.md 5.4: 18-29), or
`PLATFORM_SOURCES` admits the flow's resume as the driver's.

### S2HUD-5. `tools/native/s2layout.py`: the title's region, `resolve_game`

1. **The title has 8 rows.** `STCFN036` (`$`), `STCFN064` (`@`) and
   `STCFN081` (`Q`) are 8 high [M: DOOM1.WAD], so a title at y = 160 can
   draw row 167: `REGIONS['title']` becomes `rows('title', 's2hud',
   TITLE_Y, TITLE_Y + 7)` (rows 160-167; the map and the overlay keep
   those rows black under it [R `am_map65.s:1045-1047`, `:1188-1215`]),
   and SCREENS.md 6.1 / 6.3's "the title's rows 160-166" become 160-167.
2. **`resolve_game` adds `FB` twice**: `R.FRAME` is absolute already
   [R `rlayout.py:767`], so `('main', R.FB + R.FRAME[place])` gives `$064A`
   for `AUTOMAP` (`$033A`). It should return `('main',
   R.FRAME[place])`. No field reaches it today (`frame.AUTOMAP` is
   deferred in `s2state`).

### S2HUD-6. Part `s2cap`'s `s2state.py`: the HUD's deferred fields

`player.message` and `textText` are deferred there. **What.** With
S2HUD-1 applied, `textText` is a `state` field (80 bytes, no encoding
change). The card's `HU_MSGID` is the *line's* id (upstream's
`w_message`'s text), not `player.message`: in `_hud()` the row
`_f(s, 'player.message', 4, 'word', 'card', 'HU_MSGID')` becomes
`_f(s, hu + 'w_message', 39, 'msgid', 'card', 'HU_MSGID', 2)` with an
encoding `msgid` (the id of the line's text, `s2msgs`'s table: `$FFFF`
for an empty line; a text the table lacks is unfit), and
`player.message` is the player's field (milestone 10's reference: tag 1,
the symbol's index in `llayout.symbol_list()`, offset 0; tag 0 for NULL).
`tools/native/s2hud.py` does both for its own cases (`Texts`,
`state_block`).

### S2HUD-7. For milestone 10 (R5's details)

1. `hu_tick` calls `FCALL hu_ticker` before its clears; the `HU_Start`
   hook calls `FCALL hu_start` and then clears `G_MSGKEEP`. The test
   glue's `hutick` is a stand-in of `gwi.s:638-653` with that order; the
   planted bug "`hu_ticker` reading `player.message` after `hu_tick`'s
   clear" (7,523 failures) shows what the order decides.
2. The message ids are `llayout.symbol_list()`'s indexes (51 of 228
   labels today, the largest `$A2`); the bank table keys messages below
   `$E6`, and `s2msgs.py` fails if a message's id reaches it.
3. Every message the four runs take is a symbol at offset 0 (the cases
   resolve every `player.message` pointer to a label); `hu_ticker` copies
   the id and ignores the reference's offset.

## 7. Decisions where the design left a choice

- **The texts in `S2STATE`** (S2HUD-3) rather than `P2DW`'s data: a
  line's text is fetched (2 + 36 bytes) only when its id changes.
- **The line starts black.** No 2D drawer reads the screen (SCREENS.md
  1.2); upstream's back buffer under a line is black whenever a line is
  drawn (the strip is cleared when it turns on and for every new message,
  the map's clears and `titleBand` blacken its rows), which all 794
  frames confirm, including two title redraws over the same title in
  another palette (the same glyphs: the same bytes).
- **The record is dense**: CAPVAL and CAPMSK of the line's rows as band
  rows (`s2_draw`'s capture, the band's rows 10-29), 13 pages to
  `SS_HUDTXT`; the replay walks the line's 1,600 (1,280) bytes.
- **The replay marks the line's rows whole**, upstream's `markRows(y, y +
  TEXT_H)` clipped to the band: rows 0-9, and 160-167 for the title. A
  named difference **D2**: upstream's title replay also re-publishes rows
  168-169 from its back buffer; the checkpoint checks, on every title
  replay, that those rows of the back buffer are the screen's already.
- **The cache's key is the text**, as upstream's (not the id); the
  native fill keys on the id.
- **The rows' nibble tables** come from `PS_SCB` (`palette`'s number) and
  are fetched into `P2DW`'s slots from the last one down, only for a line
  drawn afresh (the strip's palette 10 or 11, the title's 0 or 11 in the
  runs).
- **Upstream's NULL test** of `player.message` is a 32-bit pointer;
  natively the reference's tag (0 for NULL) [R `gwi.s:644`].
- **The test's write log** leaves out what a few hundred afresh frames
  would make too large: the far layer's arguments (`$00-$05`), the 2D
  zero page `$48-$7F`, the image's code (its loops patch their operands),
  `P2DW`'s runtime W `$8300-$BBFF` and the bulk copies into banks 104 and
  106; every other CPU write is judged by its writer.

## 8. Open problems

1. **A line drawn afresh is slow**: 15-22 ms on `f121` (section 5),
   against 0.02 ms for a frame whose lines are on the screen and 3.8 ms
   for a replay. Most of it is `s2_draw`'s fetch buffer: each glyph is a
   patch of its own (60-100 B), and the drawer refills the buffer with
   `s2_fbpages` pages (`P2DW`: 4, 1 KB) at a patch's first column, about
   0.25 ms a glyph [A on M: `NATIVE.md` 4.3's 0.246 µs a byte], 5 ms for
   a line of 20 [A]. A lever for part `s2draw`: refill only the patch's
   remaining bytes (`GFXDIR`'s sizes) when they are fewer. Fresh draws are
   rare (24 of 794 frames: a new message, a title after the map opens).
2. **The drawer's code is 1,125 B**, over the 700 B estimate (upstream ×
   1.3); the module with the font is within its 1,700 B with the texts in
   `S2STATE` (S2HUD-3). Without S2HUD-3 applied (or the stand-in kept) the
   texts would have to come back into `P2DW` (2,835 B).
3. **The flags of S2HUD-2 are injected from the reference** in the
   checkpoint (from the calls of `I_MessageStrip`, `R_RenderPlayerView`,
   `clearStrip`, `clearView`, `titleBand`, `AM_Clean` in each frame):
   the frame driver, `AMAPW` and `OVLW` must set them so; nothing native
   computes them yet.
4. **`hu_tick` is a stand-in** in the test glue (`s2_hut.s`'s `hutick`,
   marked) until milestone 10's `M11` build links `s2t_hu.s` (R4, R5).
5. **The shared includes are kept with `make -o`** while `s2layout.check()`
   refuses milestone 10's phase-31 write (S2HUD-4); a plain `make -f
   m11.mk` of any part fails until then.
6. Requests S2HUD-1 and -3 are stand-ins (`P_TXTTEXT`, `P_MSGFILL`,
   `P_MAPFILL`, `SS_HUDMSG`) until the integrator applies them; nothing
   loads `HUDTXT.1` before `plboot`.
7. Newgame shows no message (its 128 frames draw nothing); the strip's
   lines come from demo3 (17 fresh, 6 replays), menus.script and
   automap.script (the title: 1 replay); the cut at 320 and the counter's
   edges only from the synthetic cases.
8. Once, in the first `--all`, an a2vm run of a planted copy ended
   without its state file and without output; three full reruns of the
   seven planted bugs did not show it again. `plant()` now reports such a
   failure as the bug's result ("the run failed: ...") instead of
   stopping.
9. The part took longer than its 1.5 hours.

## 9. The wave 4 integration (2026-10-01)

What the integrator did with each request (`docs/SCREENS.md` 8.8, "Wave
4 as integrated"):

| Request | Outcome |
| --- | --- |
| S2HUD-1 | Applied: `textText` is a `state` field (`P_TXTTEXT`, 80 B) and `s2layout.P2DW_NATIVE` (`P_MSGFILL` 2, `P_MAPFILL` 1) is allocated after the field map's fields (`state_places`). With S2STBAR-3's two fields before them the places moved from the stand-ins: `P_TXTTEXT` `$BF89`, `P_MSGFILL` `$BFDD`, `P_MAPFILL` `$BFDF` (the block ends at `$BFE0`). `s2msgs.hud_inc_text()` no longer writes them; `s2hud.state_block()` and `fstate()` take them from `state_places` (`fstate` read the text at the stand-in's `$BFB0`) |
| S2HUD-2 | Recorded in `design.md` R7 item 7 for the frame driver, `s2amap` and `s2ovl` |
| S2HUD-3 | Applied: `('SS_HUDMSG', 0x0C00)` in `S2STATE_FIELDS`, after S2STBAR-2's `SS_STBUF`, so at `$7520` (the stand-in's `$6200` would have met `STBUF` at `$6120-$751F`); `s2msgs.SS_HUDMSG` reads `s2layout`. SCREENS.md 1.5.2, 4.1 (P2DW's own row), 4.5 (row 104). Item 2 (the boot loads `HUDTXT.1`) is `plboot`'s |
| S2HUD-4 | Settled: `s2layout`'s phase scanner reads `.ifdef TESTBUILD` branches as milestone 10's test-build harness, checked in 0-31 and readable only (SCREENS.md 4.8; `design.md` R8 for milestone 10). `s2hud.make()`'s fallback to `make -o` is removed: a failing check fails the build |
| S2HUD-5 | Applied: `REGIONS['title']` is rows 160-167; `resolve_game` returns `R.FRAME[place]`; `s2cap`'s `TITLE_ROWS` (160, 167) and `x1_rows` (an empty range dropped), so the cases were captured again |
| S2HUD-6 | Applied: `_hud()`'s `HU_MSGID` comes from `hu_stuff65.s:w_message` with the encoding `msgid` (`s2state.msgid_of`: the line's text in `s2msgs`'s table, `$FFFF` for an empty line, unfit when the table lacks it); `player.message` is a `player` field, deferred (milestone 10's reference); `textText` no longer deferred |
| S2HUD-7 | Recorded in `design.md` R5 |

Results after the integration [M]: `python3 tools/native/s2hud.py --all
--jobs 2` (1 min 31 s) `report.json` ok, as in section 2 on `f121` and
`fastpath` (demo3 2,136 tics, 534 frames, 17 fresh, 6 replays; menus 3
frames excluded; automap 92 frames; 64 synthetic tics, 12 lines; the
seven planted bugs caught with the same first failures); timing as
section 5; `s2_hu` 1,411 B, `s2t_hu` 100 B, the texts 2,672 of 3,072 B.

## The final integration of the first half (2026-10-02)

`s2ht` links part s2pal's `s2_pal.o` in place of `s2_beginstub.s` (never run: the glue sets `s2_begun`; its allowed set stays empty). The checkpoint and the seven planted bugs pass again. `P2DW` linked whole with the status bar (`build/native/m11/s2int/p2dwl`) is 6,093 of 7,424 B. The test is `tests/test_m11_s2hud.py`. (`docs/SCREENS.md` 8.13.)
