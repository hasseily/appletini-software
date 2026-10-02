# Milestone 11, part `s2menu2`: the settings pages, the key setup, the slots, the signs' font

Part `s2menu2` of wave 6 ([`docs/SCREENS.md`](../SCREENS.md) 7.3),
2026-10-01. GPL-2: rewritten from upstream's `src/iigs/m_menu65.s`
(`thermo`, `drawControls`, `keyName`, `text`, `drawSlots`, `drawLoad`,
`drawSave`, the values of `uiSettings` past ON and OFF with `uiViewIndex`
for the full view only, `uiGammaPos`, `uiMousePos`, `uiBenchmark`'s rows,
and the busy sign's font `bmGlyph`, `bmGlyphCol`, `bmPut`, `bmMargin`,
`bmBlanks`). Follows SCREENS.md 1.5.3, 4.1, 6.2, 6.3. Labels as in
`NATIVE.md`: [M] measured, [R file:line] read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `src/native/s2_menu2.s` | In `MENUW`, the hooks part `s2menu1`'s `m_page` calls (S2MENU1-5): `m2_page` (A = the page: `drawLoad` and `drawSave` with their 8 slots, `drawControls` with `keyName` over part `plinput`'s `pl_action` and `plk_names`), `m2_value` (the VIEW row's "FULL"; the thermometers of gamma, the effects' and the music's volume and the mouse speed), `m2_bench` (the result's title, VIEW and FPS rows; the CPU, CACHE and ROM rows black, X2). With `-D M2_SIGNFONT`, a separate object for `FINW`: `sg_glyph`, `sg_col`, `sg_put`, `sg_blanks` (the busy sign built as a patch in W) and the font's places |
| `src/native/s2_menu2t.s` | Test glue, not the game: part `s2menu1`'s `s2_menut.s` without its STANDINs of this part's hooks (the two cannot link together: request S2MENU2-3), with its `pl_mouseup` STANDIN and its entries; with `-D M2_SIGNFONT`, `t_sign` (the sign's patch in `bmSignPatch`'s order, so the font is compared alone) |
| `src/native/m11/s2menu2.mk` | `make -C src/native -f m11.mk part P=s2menu2`: `gen/s2menu2.inc`, `gen/s2_menu.s` (the STANDIN copy of part `s2menu1`'s source, S2MENU2-2), the other parts' generated includes (`s2menu1.inc`, `fxchan.inc`, `s2pal.inc`, `plkeys.inc`); `MENUW` with both menu parts as `s2m2` and with the sound log as `s2m2t` (the checkpoint's); `s2_sgfont.o` and its test image `s2sgt` in `FINW`'s room. `S2M2SRC`, `S2M2PLSRC`, `S2M2_DIR` for the planted bugs |
| `tools/native/s2menu2.py` | `--inc`, `--menu1` (the generated files); `--capture` (the reference runs K1, K2, B through part `s2cap`'s capture, and part `s2menu1`'s call log into this part's directory); `--check`, `--timing`, `--planted`, `--all` (section 2); it imports `s2menu1.py` for the jobs, the injection, the comparison and the chains |
| `tests/wip_test_m11_s2menu2.py` | 6 hand-made tests, 6 checkpoint tests, 1 planted-bugs test (5 subtests) |

Build output: `build/native/m11/s2menu2/` (the images, `gen/`, `cases/`
the three runs, 6 MB, `cap/` the call log, `report.json`; 7 MB in all).
Every run's directory is a `tmp-*` directory there, deleted after it.

### 1.1 The design as built

**The pages.** `m_page` calls `m2_page` before the items' patches, as
`M_Drawer` calls a page's routine [R `m_menu65.s:1086-1128`]; each band
walks the whole page and `m_dpatch`, `m_wline`, `m_align` skip what
misses it. The load and save pages: the title centred at y 8 (its x
from the patch's width at build time: `M2_LOADG_X`, `M2_SAVEG_X`), then
eight slots at y 34 + 13 i: `M_LSLEFT` at 104, twelve `M_LSCNTR` from 112,
`M_LSRGHT` at 208, the slot's string (`M_SAVESTR` + 8 i) at (112, y - 7)
by `writeLine`, which stops at a 0 or a line break as upstream's does.
The key setup: "KEY SETUP" centred at y 4, each action's name at (48, 24
+ 16 i), at 176 "KEY / ESC CANCEL" on `M_BINDROW`'s row, else
`pl_action`'s first two codes (upstream's range order, part `plinput`'s)
by name, "---" for none, ", " between two; DEFAULT KEYS alone.

**The values** (`m2_value`, inside `settings`' loop, which keeps
`S2M_ITEM`, `S2M_LEFT`, `S2M_UIY`, `S2M_KIND`): VIEW's value is "FULL" at
the right edge 284 (`uiViewIndex` with the full view only, D-M5); the
thermometer at (204, y - 3): the left end, 16 middles from 212, the right
end at 276, the dot at 212 + 4 v [R `:1268-1300`], v = `uiGammaPos[GAMMA]`,
`uiMousePos[SS_SETTINGS+3]`, `SND_SFXVOL` or the music's volume
(`SS_SETTINGS+5`, a STANDIN: S2MENU2-2).

**The benchmark's result** (`m2_bench`): "BENCHMARK: DEMO3" centred at y
24, "VIEW" and "FPS:" at x 36, y 60 and 76 (`bmWrite`), their values at
the right edge 284: "FULL" and the FPS text `M_BFPS` (STANDIN: S2MENU2-1;
the second half's benchmark writes it as `bmDone` does `VW_BTXT`'s second
line). The rows of CPU, CACHE and ROM (y 92, 108, 124 and the 7 rows
under each: the font's tops are 0 or below, its heights at most 8) are
black, whole rows, as `s2check.x2` defines X2, and marked.

**The busy sign's font** (`-D M2_SIGNFONT`): `sg_glyph` fetches a glyph
whole (at most 160 B [M]) into a 256-byte W buffer; `sg_col` parses a
column's posts into `SG_COL` (rows past 7 dropped); `sg_put` appends a
column to the patch in W (its offset, then one post: row 0, 24 pixels: 4
black, each of the 8 twice, 4 black); `sg_blanks` X black columns. Zero
page: the drawers' temporaries `$5A-$6D` (the sign is built before it is
drawn). Part `s2fin` drew the sign by columns into its band instead, with
its own 289 B of helpers; S2MENU2-4 with S2FIN-8.

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
df -h /System/Volumes/Data                      # 60 GB free
make -C src/native -f m11.mk part P=s2menu2     # no warning
python3 tools/native/s2menu2.py --all --jobs 2  # 3 min 2 s
python3 tools/testpar.py --jobs 2 tests/wip_test_m11_s2menu2.py   # 170 s, 13 OK
```

The reference runs (all on ref816 through `s2cap.capture`, 7 s together
[M]):

| Run | What | Frames compared |
| --- | --- | --- |
| A | part `s2cap`'s `menus` cases (upstream's ADB key names and table) | 162 jobs: every open, frame and close of both menu parts, but the key setup's 4 frames redrawn whole (X-K) |
| K1 | `menus.script` to the key setup page, the //e names and table of `plkeys.inc` poked 1:1 into `keyNames` and `keyTable` at `uiDisplay`'s entry the first time `currentMenu` is 8 (SCREENS.md 6.2; at `uiDisplay` rather than `M_Drawer`, whose entry comes after the case's `PD0` dump) | the key setup's 9 frames (1 whole, 8 skull) |
| K2 | the whole `menus.script` with the //e names poked into `keyNames` at the main loop's first display; `keyTable` stays upstream's, so the script's keys work: the binding to Q and the defaults back are drawn; each frame's `keyTable` Doom keys injected 1:1 into `PL_KEYTAB` | the key setup's 24 frames (4 whole) |
| B | the menu opened over the title with the result poked at `uiDisplay`'s entry (`messageToPrint` 1, `messageKind` 16, `menuversion`, `VW_BTXT` "FULL\n12.345\nZIPGS 8.00 MHZ\n16 KB\n3") | the result's open and its 8 static frames |

Results [M, 2026-10-01], `build/native/m11/s2menu2/report.json` `ok`:

| Checkpoint item | Result |
| --- | --- |
| Every page and cursor of `menus.script`, both fills (fill `$A5` with the write log, the opens as whole paused frames; fill `$5A` with the reference's marked bytes poisoned): the whole screen (pixels, SCBs, palettes) equal | 204 jobs, 408 runs, 13,346,496 bytes compared, 0 differ: the load and save pages (1 whole frame and 15 skull frames each), display and sound (1, 4), controls (2, 8), key setup (5 whole, 48 skull, in A, K1, K2), the benchmark's result (1 open, 8 static), and again part `s2menu1`'s pages, messages, opens and closes on this image; 0 stray writes, upstream's publish order, stack at most 23 B; the //e names (K1, K2) and table (K1) checked in each reference frame |
| X2 | 3 × 8 rows black natively in each of the 9 result frames (34,560 bytes; 22,248 of them not black in the reference) |
| Each session chained (run A, from each open's state alone) | 7 sessions: 159 frames, 268 events, 652 tics, 7 closes, every screen and answer equal; 24 frames over the key setup page not compared (X-K; part `s2menu1` left 71 out, X-M2) |
| Part `s2menu1`'s calls on this image (its `t_num` as S2MENU2-2 asks) | 283 `M_Responder` (102 sounds, 1 request), 863 `M_Ticker` in 155 chains: 0 problems |
| The busy sign's font | 8 texts ("LOADING...", "SAVING...", "INSERT DISK 1", "INSERT DISK 9", "Insert disk 2 {~}\|`", the whole font in three): each patch equal to upstream's `bmSignPatch` (`ref816 --call` on part `s2draw`'s base image), 57,682 bytes; 0 stray writes |
| `MENUW` with both menu parts within its room | `s2m2` `$6600-$9345`: 11,590 of 16,128 B; own 7,505 of 11,328 B |

**X-K** (counted, named): in run A the key setup page shows upstream's
ADB names, which no native table holds; its 4 whole frames are compared
in K1 and K2 instead, and its skull frames are compared in all three (a
skull's rectangles never reach the names).

## 3. Planted bugs (each in a scratch copy)

`tools/native/s2menu2.py --planted`: each in a copy of `s2_menu2.s`,
`pl_keys.s` or the scratch build's generated `plkeys.inc`, built into a
scratch directory (an image equal to the tree's is an error, so a plant
that did not reach the image cannot pass), then the frames of its runs
and pages [M]:

| Planted | Caught by | Message |
| --- | --- | --- |
| A thermometer's dot one step off (`TH_X0 + 12`) | run A, display and sound, controls | `a full f000059 (display & sound) fill $A5: 140 screen bytes differ (first $512B: $49 for $CC)` |
| The key setup's second key from the wrong range order (`pl_keys.s`: `$00-$1F` before `$20-$2F`) | K1, K2 | `k1 full f000076 (key setup) fill $A5: 264 screen bytes differ (first $3958: $AA for $0A)` |
| The view size not limited to full (VIEW's value "3/4 SIZE") | run A display and sound, B | `a full f000059 (display & sound) fill $A5: 147 screen bytes differ (first $4374: $AA for $12)` |
| A key name written without its 0 (`plkeys.inc`'s pads `$20`) | K1 ("MOUSE 1" runs on into "O-APPLE") | `k1 full f000076 (key setup) fill $A5: 545 screen bytes differ (first $2F73: $0A for $00)` |
| The sign's glyph rows not doubled (extra) | the sign's 8 texts | `'LOADING...': the patch differs (4496 B for 4496; first at +574)` |

## 4. Sizes against the budget

| Item | Budget | As built [M] |
| --- | ---: | ---: |
| `s2_menu2` in `MENUW`: code | | 605 B |
| its data: the strings and tables 223 B, `plk_names` 1,024 B | | 1,247 B |
| `s2_sgfont` (for `FINW`): code 272 B, the font's places 252 B | | 524 B |
| The part | 4,000 B | 2,376 B |
| `MENUW` (`s2m2`): own (both menu parts, the glue 178 B) | 11,328 B | 7,505 B |
| `MENUW` room | 16,128 B | 11,590 B (`$6600-$9345`) |
| Time | 1.5 hours | more (open problem 4) |

4.1's split: `s2menu1` 5,475 B against its 5,000 B, this part 1,852 B in
`MENUW` against its 4,000 B; the names and strings' 2,328 B hold
`s2menu1`'s 1,747 B of data and this part's 1,247 B only together with
some of this part's unused 2,148 B (the own row as a whole has 3,823 B
left).

## 5. Timing (SCREENS.md 6.4)

`--timing`: each frame of this part's pages (runs A, K2, B; fill `$A5`)
under `--cost f121` and `--cost fastpath` with `--cost-timed`,
`m_display` alone in phase 30, ms [M]:

| Frame | n | `f121` median / p99 / worst | `fastpath` median / p99 / worst |
| --- | --: | --- | --- |
| load page, redrawn whole | 1 | 163.2 | 137.3 |
| save page, redrawn whole | 1 | 160.6 | 134.6 |
| key setup, redrawn whole | 4 | 124.8 / 127.4 / 127.4 | 108.2 / 110.2 / 110.2 |
| display and sound, redrawn whole | 1 | 112.0 | 97.9 |
| controls, redrawn whole | 2 | 106.8 | 93.0 |
| the benchmark's result (the open: save, tables, gray screen, page) | 1 | 95.3 | 85.6 |
| a skull frame (load, save, key setup, display, controls) | 82 | 2.1-3.7 / up to 4.1 | 1.7-3.1 / up to 3.5 |
| the result's static frames | 8 | 0.005 | 0.005 |
| the busy sign's patch ("LOADING...", "INSERT DISK 9") | | 2.2, 2.9 | 2.0, 2.6 |

A whole redraw is `s2menu1`'s 32,000-byte gray conversion and publish
(93.5 ms on `f121`, `s2menu1.md` 5) plus the page: the load and save
pages' 113 patches (the slots' borders) walked in each of the nine bands
and drawn in the bands they cross, about 70 ms.

## 6. Requests (for the integrator; the stand-ins are marked `STANDIN`)

### S2MENU2-1. `tools/native/s2layout.py`: `MENUW`'s `M_BFPS`

**What.** `MENUW_NATIVE` gains `('M_BFPS', 8)` after `('M_FONTBUF', 16)`,
with this line added to its comment: "the benchmark's FPS text,
0-terminated, at most 7 characters (`bmDone`'s second line of
`VW_BTXT`, x.xxx; the second half writes it; part s2menu2, request
S2MENU2-1)". **Why.** `uiBenchmark` draws `VW_BTXT`'s lines [R
`m_menu65.s:3015-3058`], which `bmDone` writes [R `:2457-2533`]; natively
the VIEW line is the constant "FULL" (the full view only) and the three
accelerator lines are dropped (X2), so only the FPS text needs a place;
`MENUW`'s state block has 141 B free after `M_FONTBUF` [M]. **Stand-in:**
`M_BFPS` = `$BF73` in `gen/s2menu2.inc`, the address this request gives
(`s2menu2.native_places()` takes s2layout's once it is there). For
`design.md` R7 (the second half): `REQ_BENCH`'s end writes `M_BFPS` as
`bmDone` does and starts the message `MSG_BENCH` [R `:2516-2526`].

### S2MENU2-2. The release's `MUSIC_MENU` is 1: the display page's fourth row

**Evidence.** upstream's `Makefile:82` `MUSIC_MENU ?= 1` and `:84` pass
it to `m_menu65.s`; the release's `menuNum` [M: the release image at
`m_menu65.s:menuNum` `$4DDE6`] is 6, 5, 8, 5, 11, 8, **4, 2**, 5, so the
display and sound page has 4 rows (VIEW, GAMMA, SFX VOLUME, MUSIC
VOLUME) and the old sound page 2. `s2menu1.md` 7's D-M8 ("no row with
the release's `MUSIC_MENU` 0") is not so; it went unseen because that
page was X-M2. With `s2_menu.s`'s `t_num` the native draws 3 rows:
`menus` frame `f000059` differs from the reference in 677 bytes, rows
125-137 (the fourth row at y 128) [M].

**What.**

1. `src/native/s2_menu.s` (part `s2menu1`'s), the table:
   `t_num:   .byte 6, 5, 8, 5, 11, 8, 3, 1, 5` becomes
   `t_num:   .byte 6, 5, 8, 5, 11, 8, 4, 2, 5`; `r_musvol` becomes
   `uiVolume` on the music's byte (natively it changes no AY write: the
   owner's mix stands):

   ```
   r_musvol:
           sta S2M_K               ; uiVolume: the music's 0-15 in
           ldx #SET_MUSVOL         ;   SS_SETTINGS (S_SetMusicVolume: the
           jsr getset              ;   owner's mix stays as it is)
           ldx S2M_K
           bne @up
           cmp #0
           beq @done
           dec a
           bra @put
   @up:    cmp #15
           bcs @done
           inc a
   @put:   ldx #SET_MUSVOL
           jmp putset
   @done:  rts
   ```

   with `SET_MUSVOL  = 5` beside `SET_MMOVE`, and its comments "(no music
   volume row: MUSIC_MENU 0)" and D-M8 in `s2menu1.md` 7 corrected.
2. `tools/native/s2layout.py` `_menus()`: after the `iigs_mousemove` line,
   `_f(s, 's_sound65.s:snd_MusicVolume', 2, 'byte', 'bank',
   'SS_SETTINGS+5')`, so the injection and part `s2menu1`'s state
   comparisons carry it; `s2menu2.settings_places()` then finds it and
   `extra_records` writes the same byte.
3. `SCREENS.md` 1.5.3, row "Sounds": "the music's volume is upstream's
   setting (`SS_SETTINGS+5`), drawn and saved; it changes no AY write".

**Stand-in:** `gen/s2_menu.s`, `s2_menu.s` with `t_num`'s change only
(`s2menu2.py --menu1`; once the tree's file has the new `t_num`, the copy
is the file unchanged), and `SET_MUSVOL` = 5 in `gen/s2menu2.inc`. Part
`s2menu1`'s 283 `M_Responder` and 863 `M_Ticker` calls pass on this image
(section 2); the script never changes the music's volume.

### S2MENU2-3. One `MENUW`: part `s2menu1`'s images with this part linked

**What.** `src/native/s2_menut.s`: its `m2_page`, `m2_value`, `m2_bench`
STANDINs and their export go (this part's `s2_menu2.s` exports them);
`src/native/m11/s2menu1.mk`: `S2M1_SHARED` adds `$(S2M1_DIR)/s2_menu2.o`,
built as `s2menu2.mk` builds it (with `gen/plkeys.inc` and
`gen/s2menu2.inc`, or the two parts' fragments merged); then
`src/native/s2_menu2t.s` goes (its `-D M2_SIGNFONT` half moves with
S2MENU2-4), and `tools/native/s2menu1.py`'s X-M2 (`PAGES_M2`, `on_m2`,
the `why` of `menu_jobs`) becomes this part's X-K: only the key setup's
frames redrawn whole in run A, compared in K1 and K2. **Why.** The two
glues cannot link together (each exports `t_frame` .. `t_tables`); one
`MENUW` holds both parts (SCREENS.md 4.1).

### S2MENU2-4. The busy sign's font: with S2FIN-8

`s2fin.md` S2FIN-8 asks the integrator to keep `s2_fin.s`'s own column
drawer (a) or link this part's `s2_sgfont.o` and build the sign as a
patch in W (b). This part's font is compared with upstream's
`bmSignPatch` on 8 texts (section 2) and is ready for (b) (`FINW` would
need the patch's W room, about 6 KB for "INSERT DISK n", and a glyph
buffer of 256 B). With (a): `s2_menu2.s`'s `-D M2_SIGNFONT` half,
`s2_menu2t.s`'s, `s2sgt` and its rules in `s2menu2.mk`, and
`check_signs` with the `sign-double` plant in `s2menu2.py` go (524 B of
this part's budget unused).

### S2MENU2-5. `docs/SCREENS.md`: as built

1. 1.5.3, row "Gone": "The benchmark itself stays, with its two rows
   (view, FPS); the CPU, CACHE and ROM rows (y 92, 108, 124, 8 rows each)
   black, whole rows (X2, `s2check.x2`)".
2. 6.2, the key poke: "at `uiDisplay`'s entry the first time
   `currentMenu` is the key setup (8) (`M_Drawer`'s entry comes after the
   case's `PD0` dump); and a second run with the names alone, the
   bindings upstream's, each frame's `keyTable` injected 1:1 into
   `PL_KEYTAB` (part `s2menu2`, runs K1 and K2)".
3. 4.1's size table, `MENUW`'s own row: "(`s2menu1` 5,000, `s2menu2`
   4,000: 1,852 B [M] in `MENUW`, with the names 1,024, and 524 B of the
   sign's font for `FINW`, S2MENU2-4; names and strings 2,328)".
4. 7.3, `s2menu2`: the routines as section 1 here; Files: add
   `src/native/s2_menu2t.s` (test glue), `tools/native/s2menu2.py`.

`MEMORY_MAP.md`, `NATIVE.md`: nothing.

## 7. Decisions where the design left a choice, and named differences

- **The comparison's key tables** (runs K1, K2, X-K): section 2. 6.2's
  1:1 poke of both tables stops the script on the key setup page
  (S2CAP-4), so K1 covers the page as it opens with the //e defaults and
  K2 the binding and the defaults back; both draw the //e names.
- **The view is the full view only** (D-M5, part `s2menu1`'s): VIEW's
  value and the result's VIEW line are the constant "FULL"; the reference
  runs show the full view (run A's display page, frame `f000059`, equal
  with "FULL" [M]).
- **X2 as whole rows** black (`s2check.x2`'s definition) rather than the
  text's width; the result's rows 92-99, 108-115, 124-131.
- **The music's volume** is drawn from `SS_SETTINGS+5`; natively it
  changes nothing audible (the owner approved S2's mix as it is).
- **No benchmark run natively** yet (`REQ_BENCH` is the second half's):
  the result's frame is compared on the reference's poked state.
- **The sign as a patch in W** (`bmSignPatch`'s model), not drawn by
  columns into the band (part `s2fin`'s choice): S2MENU2-4.

## 8. Stand-ins (marked)

| Stand-in | Where | Until |
| --- | --- | --- |
| `M_BFPS` at `$BF73` | `gen/s2menu2.inc` | S2MENU2-1 |
| `SET_MUSVOL` = 5 (`SS_SETTINGS+5`) | `gen/s2menu2.inc`; `s2menu2.SET_MUSVOL` | S2MENU2-2 |
| `s2_menu.s` with the release's `t_num` | `gen/s2_menu.s` (`s2menu2.py --menu1`) | S2MENU2-2 |
| The test glue without `s2_menut.s`'s hooks; `pl_mouseup` | `src/native/s2_menu2t.s` | S2MENU2-3; part `plinput`'s open problem 2 |

## 9. Open problems

1. **The music row** needs S2MENU2-2 in part `s2menu1`'s source; until
   then the tree's `MENUW` draws 3 rows on the display page (the
   reference 4).
2. **The whole frames' cost**: 107-163 ms on `f121` for this part's pages,
   most of it `s2menu1`'s 32 KB gray conversion and publish (its open
   problem 2); the slots' 113 border patches add about 70 ms on the load
   and save pages. Lever: the borders as one pre-rendered row of bytes a
   slot (the same 8 rows each time), or the levers of `s2menu1.md` 9.
3. **The key setup with the //e table** is compared only as the page
   opens (K1); the binding to a //e key and the defaults back are compared
   with upstream's table (K2), since the script's keys go through
   `keyTable` (S2CAP-4). The binding itself (`pl_bind`) is part
   `plinput`'s, compared by its model.
4. The part took longer than its 1.5 hours.

## 10. The wave 6 integration (2026-10-02)

What the integrator did with each request (`docs/SCREENS.md` 8.10, "Wave
6 as integrated"):

| Request | Outcome |
| --- | --- |
| S2MENU2-1 | Applied: `('M_BFPS', 8)` last in `s2layout.MENUW_NATIVE`, at `$BF73` as the stand-in was; `M_BFPS` is `s2.inc`'s and `gen/s2menu2.inc` no longer defines it; `design.md` R7 item 9 has the benchmark's write |
| S2MENU2-2 | Applied: `s2_menu.s`'s `t_num` is the release's (6, 5, 8, 5, 11, 8, 4, 2, 5), `r_musvol` is `uiVolume` on `SET_MUSVOL` = 5 (`s2_menu.s` defines it beside `SET_MMOVE`; `gen/s2menu2.inc` takes it from the field map), the field map has `s_sound65.s:snd_MusicVolume` at `SS_SETTINGS+5`, SCREENS.md 1.5.3's "Sounds" row and `s2menu1.md`'s D-M8 are corrected. `gen/s2_menu.s` and `--menu1` went. **Fixed:** part `s2menu1`'s call log did not dump `snd_MusicVolume` (`$0275F6`), so the injection of the new field stopped `check_responders` (`KeyError: '$0275F6+2 is not in PD0'`); `STATE_RANGES` now logs it and both parts' call logs were captured again |
| S2MENU2-3 | Applied with one change: `s2_menut.s` lost the hooks' stand-ins and is the one menu glue; `s2menu1.mk` links `s2_menu2.o` (with `gen/s2menu2.inc` and `gen/plkeys.inc` generated into its `gen/`); `s2menu2.mk` links `s2_menut.o` and the tree's `s2_menu.s`; `s2_menu2t.s` is deleted; `s2m1t` and `s2m2t` are the same image byte for byte. `s2menu1.py`'s owners name `s2_menu2`; `s2menu2.owners` is `s2menu1.owners`. **Not done:** `s2menu1.py`'s X-M2 stays in that part's own checkpoint (its injection lacks this part's key table, effects' volume and FPS records); the comparison of every page of the one `MENUW` is this part's run A (all of `s2menu1`'s jobs and this part's pages, X-K the key setup's 4 whole frames), so nothing is left uncompared |
| S2MENU2-4 | Option (a) of S2FIN-8: `FINW` keeps `s2_fin.s`'s own column drawer (no patch in W beside the band and the units, about 6 KB for "INSERT DISK n"; the image 726 B smaller than (b) would make it; and the drawer compared against the release's signs). The `-D M2_SIGNFONT` half of `s2_menu2.s`, `s2_menu2t.s`'s, `s2sgt` and its rules, `check_signs`, `ref_signs` and the `sign-double` plant went; the test's sign checks went with them (524 B of this part's budget unused) |
| S2MENU2-5 | Applied: SCREENS.md 1.5.3 "Gone", 6.1, 6.2's key poke, 4.1's own row, 7.3 |

Results after the integration [M]: `python3 tools/native/s2menu2.py --all
--jobs 2` (2 min 53 s): ok; the three runs captured again (K1 85 frames,
K2 203, B 10); 204 frame jobs, 408 runs, 13,346,496 bytes compared, 0
differ; the 7 sessions chained (159 frames, 268 events, 652 tics, 24
frames X-K); 283 `M_Responder` and 863 `M_Ticker` calls, 0 problems;
stack 23 B; the four planted bugs caught as in section 3; `s2_menu2`
1,852 B (code 605, data 1,247 with the names' 1,024) of 4,000;
`MENUW` `$6600-$9361`, 11,618 of 16,128 B, own 7,533 of 11,328 B.
