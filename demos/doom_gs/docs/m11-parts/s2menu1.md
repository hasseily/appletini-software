# Milestone 11, part `s2menu1`: the menu engine and the main pages

Part `s2menu1` of wave 5 ([`docs/SCREENS.md`](../SCREENS.md) 7.3),
2026-10-01. GPL-2: rewritten from upstream's `src/iigs/m_menu65.s`
(`M_Init`, `M_StartControlPanel`, `M_DrawVersion`, `M_SkullVersion`,
`M_Ticker`, `M_Responder` and its handlers, `clearMenus`, `setupMenu`,
`startMessage`, the main, new game, skill and options pages, `M_Drawer`,
`M_DrawSkull`, `skullPlace`, `M_SkullRect`, `drawMessage`, `lineWidth`,
`writeLine`, and the settings pages' frame the options page draws
through), `i_viigs65.s` (`I_MenuPalette`, `uiGrayTables`, `grayMap`,
`uiDimAll`, `uiDimRect`, `uiFontNibbles`, `I_MenuPaletteBack`,
`I_RestoreBackRect`) and `d_main65.s` (`uiDisplay`, the static screen).
Follows SCREENS.md 1.2, 1.5.3, 2.1, 3, 4.1, 6. Labels as in `NATIVE.md`:
[M] measured, [R file:line] read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `src/native/s2_menu.s` | The engine and the pages (`MENUW`): `m_init`, `m_startcp` (with `uiMain`), `m_ticker`, `m_responder` (`responderEvent`, the 53 items' routines, `answer`, `vwKeys`), `m_savedone`, `m_display` (`uiDisplay`), `m_frame` (a paused frame in 2.1's order), `m_page` (`M_Drawer` into a band: the message, or the page, its items, `uiSettings`, the skull), `m_skullrect`, `m_drawskull`, the text (`drawMessage`, `lineWidth`, `writeLine`, `bmWrite`, `uiAlign`), `bmBox`, `m_load`/`m_save`; the pages' tables, strings and messages; exports `m_dpatch`, `m_wline`, `m_wstr`, `m_align` for part `s2menu2` |
| `src/native/s2_mvid.s` | The menu's video: `mv_open` (`I_MenuPalette`'s open: the save by one memory-API COPY, every SCB the menu palette, the palette state of a new picture), `mv_tables` (`uiGrayTables`/`grayMap`'s rule, palette 9's nibble table in `MENUW`'s slot from `GSOVL`'s pairs, `uiFontNibbles`), `mv_band`, `mv_dim` (`uiDimRect` into a band through a 256-byte gray map), `mv_restore` (`I_RestoreBackRect`), `mv_shade` (`bmFontShade`), `mv_full` (the bands of a whole frame), `mv_close` (`I_MenuPaletteBack`), `mv_static` (`staticUpToDate` with the skull's rectangles band by band), `mv_drawn` (`staticDrawn`), `mv_amem` (the FIFO transport); the image's places for the drawers |
| `src/native/s2_menut.s` | Test glue, not the game: the marked STANDINs of part `s2menu2` (`m2_page`, `m2_value`, `m2_bench`) and part `plinput` (`pl_poll`, `pl_bindkey`, `pl_defkeys`, `pl_mouseup`), the sound log, the checkpoint's entries `t_frame`, `t_close`, `t_resp`, `t_tick`, `t_save`, `t_tables`, `t_paused` (each between `m_load` and `m_save`, the routine alone in cost phase 30) |
| `src/native/m11/s2menu1.mk` | `make -C src/native -f m11.mk part P=s2menu1`: `gen/s2menu1.inc`, `gen/fxchan.inc`, `gen/s2pal.inc`; the `MENUW` image `s2m1` and the checkpoint's `s2m1t` (with the sound log), each with `s2_draw`, `s2_pub`, `s2_pal`, `fx_service`, `fx_chan -D FXC_NOSEP`, `fx_pcache -D FXC_MSCR`, `fx.s`'s card part, S2's player (read only), the test driver; `S2M1SRC`, `S2M1_DIR` for the planted bugs |
| `tools/native/s2menu1.py` | `--inc` (the generated include: the game's places, the message ids, the sounds, the native state and places as STANDINs, the patches and the font from the 2D store, the skulls' box); `--capture` (the reference's call log); `--check`, `--timing`, `--planted`, `--all` (section 2) |
| `tests/wip_test_m11_s2menu1.py` | 5 hand-made tests, 6 checkpoint tests, 1 planted-bugs test (5 subtests) |

Build output: `build/native/m11/s2menu1/` (the images, `gen/`, `cap/` the
call log 50 KB, `report.json`). Every run's directory is a `tmp-*`
directory there, deleted after it.

### 1.1 The design as built

**The open** (`mv_open`, upstream's `I_MenuPalette` with the palette off
[R `i_viigs65.s:2062-2126`]): the state the close restores (`M_PICTURE`,
`M_VIEWPAL`, `M_STRIPPAL`, `M_UIGAMMA`), then the screen saved by one
memory-API request through the raw FIFO (README_MEMORY_API.md section 7):
COPY of aux 0 `$2000` (`$8000` bytes: pixels, SCBs, palettes) to bank
`S2VIEW` (105) `$2000`, flags 0, interrupts masked; a failure stops with
`PL_STATUS` `$C5` then `BRK` (the close could not restore). Every row's
SCB becomes 9 (`MENU_PAL`); `mv_tables` builds `UI_GRAY` (W `$B700`, 16 ×
16 gray indexes, `grayMap`'s lightness 3 R + 6 G + B over 30, at most 4
[R `:877-912`]) from the **saved** palettes (bank 105 `$9E00`), palette
9's nibble table in `MENUW`'s slot (W `$B900`, `buildNibtab` of `GSOVL`'s
first record's pairs at `S2P_GSOVL + 448` [R `:705-736`, `:2099-2105`])
and the font's 16 reds (`uiFontNibbles` [R `:2326-2402`]: the record's
colour with the least `|R - red| + G + B`, the first best) into
`M_FONTBUF` and the slot's entries 176-191; palette 9 of `PALST` becomes
the record's 32 bytes; then the palette state of a new picture
(`palettecount`, `scbchanged`, no tint, no `levelcopy`) and the text
cache invalid (`uiInvalidate`). The frame then draws every band.

**A frame** (`m_display`, upstream's `uiDisplay` [R `:2047-2055`]): with
the menu's palette on, `mv_static` first (the static screen: nothing when
the versions match; a moved or blinked skull puts back its old and new
rectangles from the saved screen and draws the skull, band by band from
the lower first row, and publishes: `I_ShowDirty`); else `M_Drawer` in
eight 24-row bands and a 8-row one: each band's rows fetched from the
saved screen (`far_get`), each byte through the 256-byte gray map of its
row's **saved** palette (rebuilt when the palette changes:
`uiDimRect`'s rule [R `:2259-2322`]), the page drawn over it clipped to
the band (`m_page`: a patch whose rows miss the band is skipped before
`s2_vpatch`), the band published (`s2_publish`, its first call
`s2_begin`: the black palettes and the SCBs); then `staticDrawn` and
`s2_finish` (the palettes). Upstream redraws and copies all 32,000 bytes
on every such frame; so does the native.

**The close** (`mv_close`, `I_MenuPaletteBack` [R `:2138-2203`]): the
saved SCBs and palettes into `PALST`, the view's and strip's palettes
back, the palette state of a new picture, then every band fetched from
`S2VIEW` and published whole, and `s2_finish`; a gamma changed while the
menu was up calls `s2_reload`, and `M_RELOAD` = 1 when a level's tints
must be rebuilt (`PALW`: the second half's).

**Events** (`m_responder`, A = the type, X = data1): upstream's rules and
item routines; `S_StartSound(NULL, sfx)` is `sc_start` with `ORG_NONE`
(`fx_chan` linked into `MENUW`, FXCHAN-4); the game's actions are a
request in `M_REQ`, `M_REQARG` for the second half:

| `M_REQ` | Upstream | `M_REQARG` |
| ---: | --- | --- |
| 1 `REQ_NEWGAME` | `G_DeferedInitNew` (a skill, or nightmare after its message) | the skill |
| 2 `REQ_QUIT` | `I_Quit` | |
| 3 `REQ_ENDGAME` | `G_CheckDemoStatus` when a single demo plays, `D_StartTitle` | 1 with the demo's check |
| 4 `REQ_LOAD` | `G_LoadGame` (the menu closes) | the slot |
| 5 `REQ_SAVE` | `G_SaveGame`, `G_SaveSettings`; then `m_savedone` with C (the menu closes, or the failed save's message) | the slot |
| 6 `REQ_BENCH` | `bmStart` (the menu closes; demo3 timed) | |
| 7 `REQ_SAVESET` | `G_SaveSettings` (SAVE SETTINGS when `M_SETCHG`) | |

**The options page** is drawn by upstream's `uiSettings` [R
`m_menu65.s:2872-2999`] (the title, `bmBox`, each row's label and its
ON/OFF, SAVE SETTINGS dimmed by `bmFontShade` while the settings are
saved), which routes every page's skull, so this part builds it; the
values past ON/OFF (the view's size, the thermometers), the load and save
pages' slots, the key setup page and the benchmark's result are part
`s2menu2`'s through `m2_value`, `m2_page`, `m2_bench` (section 6,
S2MENU1-5).

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
df -h /System/Volumes/Data                      # 69 GB free
make -C src/native -f m11.mk part P=s2menu1     # no warning
python3 tools/native/s2menu1.py --all --jobs 2  # 2 min 35 s
python3 tools/testpar.py --jobs 2 tests/wip_test_m11_s2menu1.py
```

Results [M, 2026-10-01], `build/native/m11/s2menu1/report.json` `ok`:

| Checkpoint item | Result |
| --- | --- |
| The reference | `menus.script` on ref816 with a call log of `M_Responder` and `M_Ticker` (their state at the entry and the return: `m_menu65.s`'s znear and near data, `d_main65.s`'s static screen, the game's words, `menuNum`'s main row, the input layer's bind state, the volume, the automap's mode, `UI_PALON`, `newpal`, the event), `G_SettingsChanged`, and the entries of `S_StartSound`, the game's actions, `I_MenuPaletteBack` and the input layer's calls under them: 283 `M_Responder`, 863 `M_Ticker`, 22 `G_SettingsChanged`, 102 sounds, 3 s; and part `s2cap`'s `menus` cases (206 frames, 8 events) |
| Every frame of the main, new game, skill, options pages and messages, from the title and over the view: the whole screen (pixels, SCBs, palettes) equal | 157 jobs (7 opens, 18 frames redrawn whole, 125 skull frames, 7 closes), each twice: fill `$A5` with the write log (the opens as whole paused frames, `m_frame`: the poll, `sc_update`, `fx_service`, `snd_refill`, the display), fill `$5A` with every byte the reference's frame marked poisoned (an open's screen is its input, not poisoned); 10,271,568 bytes compared, 0 differ; `$9DC8-$9DFF` untouched; the static screen's state after each frame (`screenmenuversion`, `screenskullversion`, `skullshown`, `skx`..`skh`) equal to the next frame's |
| The close restores the screen byte for byte | the 7 closes, injected, equal to `I_MenuPaletteBack`'s return; and every session chained natively from its open's state alone to its close (below) |
| The writes | no stray write in the 157 write logs (each module's own W, bank, card and aux 0 ranges); upstream's publish order on each (the black step first at the opens and closes) |
| `M_Responder`, each call injected | 283 calls (102 eaten): the answer, the state after (the field map's `menus` fields and the native ones), the request, `player.message` (its symbol id), the volume, `newpal` and the sounds given to `sc_start` equal; 1 request (`G_DeferedInitNew`, skill 2); 0 problems |
| The menu's sounds | the 102 `sc_start` calls (the sound log of `s2m1t`) equal to the reference's 102 `S_StartSound` calls under `M_Responder`, all with a NULL origin |
| `M_Ticker` | 863 calls in 155 chains (a chain breaks where something else changed the state between two tics): the skull's counter, which skull (107 blinks), the versions and `bindRow` after every call equal; 1 key bound |
| Each session chained | the 7 sessions from their open's state alone: 159 frames, 268 events, 652 tics, 7 closes in the reference's order, chunks of 30 calls carried by the stop's snapshot; every frame and close's screen equal, but 71 frames over part `s2menu2`'s pages (X-M2); every event's answer and sounds equal |
| `MENUW` within its room | `s2m1` `$6600-$88F3` (8,948 of 16,896 B, and within the 16,128 B room S2MENU1-2 asks for); stack at most 21 B (64) |

**X-M2** (counted, named): the content of part `s2menu2`'s pages is not
this part's: 9 frames redrawn whole over the load, display and sound,
controls, key setup and save pages are not compared (their skull frames
are, 62 of the 125), and the chained runs leave 71 frames over those
pages uncompared (their screens differ where `s2menu2` draws: the slots,
the thermometers, the view's size, the key names).

### 2.1 The tests

`tests/wip_test_m11_s2menu1.py` (also on Python 3.9.6 with `-W
error::ResourceWarning` for the hand-made ones): the skulls' box rule,
the zero page and the native fields' places, `MENUW`'s places and the
asked room, the requests of the reference's calls, each planted text once
in its source (hand-made, no build); the reference's counts, every frame
and close, every responder call, every ticker call, each session
chained, the sizes; the planted bugs. Without `build/` only the hand-made
ones run; the others skip naming what is missing.

## 3. Planted bugs (each in a scratch copy of the sources)

`tools/native/s2menu1.py --planted`: each in a copy of `s2_menu.s` and
`s2_mvid.s` built into a scratch directory (`S2M1SRC`, `S2M1_DIR`), then
the check that must catch it [M]:

| Planted | Caught by | Message |
| --- | --- | --- |
| The gray of the right nibble from the left (`mv_map`'s low nibble from the high one) | the frames (`f000001`, `f000008`) | `open f000001 fill $A5: 7999 screen bytes differ (first $2001: $11 for $10)` |
| The skull's old rectangle not restored (`mv_static`) | the frames (`f000002`, `f000004`) | `skull f000002 fill $A5: 142 screen bytes differ (first $45A3: $1C for $13)` |
| The save request with a wrong length (`$7F00`) | the chained session from `f000001` to its close | `frame f000001: 14869 bytes differ` (9 problems, the close's included) |
| The menu palette's reds from the wrong colours (the green nibble for the red) | the frames (`f000008`, `f000043`) | `full f000008 fill $A5: 1029 screen bytes differ (first $5851: $10 for $1A)` |
| A menu sound not started (back to the parent menu) | every `M_Responder` call | `M_Responder call 288 (0, 9): the sounds [] for [18]` (10 calls) |

## 4. Sizes against the budget

| Item | Budget | As built [M] |
| --- | --- | --- |
| This part's code (`S2CODE` of `s2_menu`, `s2_mvid`) | 5,000 B (s2menu1's) | 3,720 B (2,295 and 1,425) |
| Its data (the pages' tables 305 B, strings and messages 515 B, the patch and font tables 582 B, the gray map 256 B and `mv_tables`' and the save's 77 B) | 2,500 B (`MENUW`'s names and strings, shared with `s2menu2`'s key names) | 1,747 B |
| Both | 5,000 + (names and strings) | 5,467 B: over the 5,000 B alone by 467 B (open problem 1) |
| `MENUW` (`s2m1`) | 16,896 B room; 16,000 B design total | 8,948 B (`s2_draw+s2_pub` 1,172, `s2_pal` 680, `fx_service` 396, `fx_chan` 970, own 5,730 with the test glue 178 B and `fx_pcache` 85 B, which the size table counts as own: S2MENU1-2) |
| The part | 1.5 hours | more (open problem 5) |

## 5. Timing (SCREENS.md 6.4)

`--timing`: each job of the checkpoint (fill `$A5`) under `--cost f121` and
`--cost fastpath` with `--cost-timed`, the routine alone in phase 30
(`m_display` of a frame, `m_close`), ms [M]:

| | `f121` median / p99 / worst | `fastpath` median / p99 / worst |
| --- | --- | --- |
| The open (save, tables, the whole gray screen and the page, published) | 136.6 / 137.3 / 137.3 | 117.6 / 118.1 / 118.1 |
| The 32 KB save alone (`mv_amem`: a2vm's model of the memory API) | 17.6 | 14.3 |
| The tables alone (`mv_tables`: `UI_GRAY`, the slot, the reds) | 1.2 | 1.1 |
| A frame redrawn whole (the gray conversion of 32,000 bytes, the page, the publish and its drain) | 93.5 / 136.9 / 136.9 | 82.7 / 115.2 / 115.2 |
| A skull frame (two rectangles and the skull) | 3.0 / 4.1 / 4.1 | 2.5 / 3.5 / 3.5 |
| The close (the restore: 32,000 bytes and the colours) | 46.9 (7 closes) | 43.5 |
| `MENUW`'s load (the driver's `far_pload`, phase 0) | 2.7 | 2.5 |

The save's time is a2vm's model of the memory API, not the card's
(README_MEMORY_API.md section 5: "Do not infer hardware acceleration from
the simulator's timing"). The worst full frame is the options page and
the messages (their text: a glyph is `s2_vpatch`'s, refetched every band).

## 6. Requests (for the integrator; the stand-ins are marked `STANDIN` in the generated `s2menu1.inc` and in `s2_menut.s`)

### S2MENU1-1. `tools/native/s2layout.py`: `MENUW`'s native state fields

**What.** After `P2DW_NATIVE`:

```
# MENUW's own fields with no upstream counterpart (part s2menu1,
# request S2MENU1-1): UI_PALON, UI_PICTURE, UI_VIEWPAL, UI_STRIPPAL,
# UI_GAMMA, menuNum's main row, bindRow and the input layer's bind
# state, G_SettingsChanged's answer (the second half's), the request to
# the second half and its argument, PALW due after the close, UI_FONTBUF
MENUW_NATIVE = [('M_PALON', 1), ('M_PICTURE', 2), ('M_VIEWPAL', 1),
                ('M_STRIPPAL', 1), ('M_UIGAMMA', 1), ('M_MAINN', 1),
                ('M_BINDROW', 1), ('M_BINDWAIT', 1), ('M_BINDCODE', 1),
                ('M_SETCHG', 1), ('M_REQ', 1), ('M_REQARG', 1),
                ('M_RELOAD', 1), ('M_FONTBUF', 16)]
OWN_NATIVE = {'P2DW': P2DW_NATIVE, 'MENUW': MENUW_NATIVE}
```

and the request codes in `constants()` (`REQ_NONE` 0 ... `REQ_SAVESET` 7,
`s2menu1.py`'s `REQUESTS`). **Why.** Upstream keeps them outside the
menu's znear (`viewwin.inc` `UI_*` [R `viewwin.inc:78-99`], `menuNum`
in code [R `m_menu65.s:3070`], `iigs_bindwait` and `iigs_bindcode` in
`i_iigs65.s`); natively they are the menu's, kept in its state block.
The stand-in allocates them from `$BF57` (the field map's end), the
same addresses this request gives. `tools/native/s2menu1.py`'s
`native_fields()` takes s2layout's places once they exist.

### S2MENU1-2. `tools/native/s2layout.py`: `MENUW`'s places

**What.** `IMAGES`' `MENUW`:

```
    Image('MENUW', (0x6600, 0xA500),
          ((0xA500, 0xA800, 'PALST'),
           (0xA800, 0xB700, 'a 24-row band'),
           (0xB700, 0xB800, 'UI_GRAY'),
           (0xB800, 0xB900, 'marks'),
           (0xB900, 0xBD00, 'the menu palette\'s nibble slot'),
           (0xBD00, 0xBF00, 'fetch buffer (fx_chan\'s scratch at $BEE0)'),
           (0xBF00, 0xC000, 'the state block')),
          (0xBF00, 0xC000), ...
```

`DRAW_PLACES['MENUW'] = (0xB800, 0xBD00, 2)`; MENUW's PALST at W `$A500`
(a `MENUW_PALST` beside `PALST_W`, which `P2DW`, `WIW`, `FINW` keep at
`$BC00`); `PL['MENUAMEM'] = 0xC5` (the save failed); `MODULE_ROW
['fx_pcache'] = 'fx_chan'` (its 85 B are counted as `MENUW`'s own
today). SCREENS.md 4.1's `MENUW` row the same: "`$6600-$A4FF` (16,128 B
room) | `$A500-$A7FF` PALST; `$A800-$B6FF` a 24-row band (3,840 B);
`$B700-$B7FF` `UI_GRAY`; `$B800-$B8FF` the drawers' marks; `$B900-$BCFF`
the menu palette's nibble slot; `$BD00-$BEFF` fetch buffer (`fx_chan`'s
scratch `$BEE0`, FXCHAN-4); `$BF00-$BFFF` state". **Why.** `MENUW`
links `s2_pal`, whose `s2_begin`/`s2_finish` need `PALST` in W (768 B;
wave 1's open problem 1, S2PAL-8), and `s2_draw` needs a marks page
(S2DRAW-1); its runtime ranges were full. The room keeps 16,128 B for
the design's 16,000 B total; `s2m1` uses 8,948 B. `UI_GRAY` is 256 B:
the font's reds (16 B) are `M_FONTBUF` in the state block, so the second
page holds the marks. **Stand-in:** these addresses in `s2menu1.inc`
(`S2M_*`); `tools/native/s2menu1.py` checks the image ends below `$A500`.

### S2MENU1-3. `docs/SCREENS.md`: 1.5.3, 4.3 and 7.3 as built

1. 1.5.3's table, row "Open": add "the gray tables from the **saved**
   palettes; palette 9's nibble table in `MENUW`'s slot only (S2NIB is
   never changed: `uiOriginalNibs` has nothing to put back, D-M2)"; row
   "Each frame": "the frame redrawn whole as upstream (every row from the
   saved screen through a 256-byte gray map of the row's saved palette,
   the page drawn over it band by band, all 32,000 bytes published), or
   the static screen with the skull's two rectangles"; row "Actions": the
   request table of section 1.1 here.
2. 4.3: "`$80-$AF` ... `S2M_*`: the menu's (`s2menu1.inc`)".
3. 7.3's `s2menu1` routines: add "the settings pages' frame
   (`uiSettings`, `uiAlign`, `uiCenter`, `bmWrite`, `bmBox`,
   `bmFontShade`), which every page's skull goes through"; `s2menu2`'s:
   "the values past ON/OFF (`thermo`, `onOff`, `uiViewIndex`, `uiVolume`
   for the drawing), `drawSlots`, `drawControls`, `keyName`, the
   benchmark's result, through `m2_page`, `m2_value`, `m2_bench`
   (S2MENU1-5)".

### S2MENU1-4. Part `plinput`: the menu's input

`MENUW` calls `pl_poll` once a frame (`m_frame`), `pl_bindkey` (A the Doom
key, X the //e key; `I_BindKey` [R `i_iigs65.s:868`]), `pl_defkeys`
(`I_DefaultKeys`), `pl_mouseup` (`IIGS_MouseUp`). The key setup's bind:
`m_responder` sets `M_BINDROW` and `M_BINDWAIT` = 1; the poll takes the
next key into `M_BINDCODE` (W `$BF60`) and clears `M_BINDWAIT` (`$BF5F`),
as upstream's `I_StartTic` does with `iigs_bindwait`; `m_ticker` then
binds unless the key is the //e's Esc (`$1B`, upstream's ADB `$35`, D-M6).

### S2MENU1-5. Part `s2menu2`: the hooks

`m2_page` (A = the page, `currentMenu / 2`: 2 load, 4 key setup, 5 save),
`m2_value` (X = the item: the kinds 20-40 of `uiKinds`), `m2_bench` (the
benchmark's result), all called inside `m_page` with the band set
(`S2_Y0`, `S2_Y1`; draw with `m_dpatch`, `m_wline`, `m_wstr`, `m_align`,
which skip what misses the band). Not to rebuild: `uiSettings`, `uiAlign`,
`bmWrite`, `bmBox`, `bmFontShade` (section 1.1). The settings item
routines (`changeGamma`, `sfxVolume`, `changeAlwaysRun`, `changeMouse`,
`changeMouseSpeed`, `changeMouseMove`, `bindAction`, `defaultKeys`) are
here, compared on every call; `viewSize` keeps the full view (D-M5).

### S2MENU1-6. The second half (design.md R7): the menu's frames

1. The paused frame: `far_pload` of `MENUW` when the menu opens (2.5 ms),
   `m_load`, `m_ticker` once a new tic, `m_responder` for each event,
   `m_frame`, `m_save`; when `G_MENUACTIVE` and `M_MSGPRINT` are both 0
   after it, the menu has closed: the game's frames resume.
2. An Escape with the menu closed: `MENUW` loaded and `m_responder` (its
   `vwKeys` opens the menu; upstream's `uiOpen` and `singletics`, which
   switch `displayCall`, are the driver's).
3. `M_REQ`/`M_REQARG` acted on (section 1.1) and cleared; `M_RELOAD`:
   `PALW` before the next level frame; `m_savedone` after a save
   (`REQ_SAVE`) with C set on failure; `M_SETCHG` kept as
   `G_SettingsChanged`'s answer (the settings against the saved file);
   `M_SAVESTR` from `G_UpdateSaveGameStrings`; `m_init` at the boot.

## 7. Decisions where the design left a choice, and named differences

- **The options page and `uiSettings`** are built here (section 1.1):
  every page's skull is drawn through `uiSettings`' tail and the options
  page is the checkpoint's.
- **Bands of 24 rows** (`MENUW`'s runtime), eight and an 8-row one; a
  patch whose rows miss the band is skipped before `s2_vpatch` (its
  columns would be walked for nothing).
- **The gray conversion** through a 256-byte map of the row's saved
  palette (both nibbles at once), rebuilt only when the palette changes:
  upstream's two `UI_GRAY` reads a byte give the same byte.
- **The skull's rectangles** are composed in bands from the lower of the
  two first rows; each band restores the old rectangle, the new one, then
  draws the skull, upstream's order; the bands publish only the marked
  bytes (`I_ShowDirty`).
- **The tables in a run that starts mid-menu**: `MENUW` stays in W while
  the menu is up, so `UI_GRAY` and the slot persist; the checkpoint's
  frames after an open call `mv_tables` first (phase 0), from the saved
  screen injected into `S2VIEW`.
- **D-M1** `grayMap` also writes `GRAYMAP` [R `i_viigs65.s:948`], which
  nothing reads (`GRAYMAP` appears in no other line of upstream's
  sources [M]): not written.
- **D-M2** `uiOriginalNibs` [R `:2207-2223`]: S2NIB is never changed, so
  nothing is put back.
- **D-M3** `sqmInit` after the close [R `:2196-2198`] (the renderer's
  `SQMID` over `MM_VIEWSAVE`): no counterpart.
- **D-M4** `uiOpen`, `displayCall`, `singletics` [R `:2038-2046`,
  `:2139-2142`]: the frame driver's (S2MENU1-6).
- **D-M5** `vwKeys`' zoom keys and `viewSize`: the full view only (no
  size change; the key eaten and its sound, as upstream with the view at
  its largest); view sizes are milestone 13's.
- **D-M6** the bind's Esc is the //e's `$1B`.
- **D-M7** `bmStop`/`bmRuns`: no benchmark runs while this part's menu
  takes keys natively; `REQ_BENCH` is the second half's.
- **D-M8** (corrected in wave 6's integration, request S2MENU2-2) the
  release's `MUSIC_MENU` is 1 (upstream's `Makefile:82`; its `menuNum` 6,
  5, 8, 5, 11, 8, 4, 2, 5 [M]): the display page has 4 rows and the sound
  page 2; `musicVolume` is `uiVolume` on `SS_SETTINGS+5`, drawn and saved,
  changing no AY write (the owner's mix stands). The first text said "no
  row with the release's `MUSIC_MENU` 0", which went unseen while the page
  was X-M2.
- **D-M9** the actions are requests (section 1.1); `saveDone` comes back
  through `m_savedone` after the second half's write.

## 8. Stand-ins (marked)

| Stand-in | Where | Until |
| --- | --- | --- |
| `MENUW`'s native fields `M_PALON`..`M_FONTBUF` from `$BF57` | `s2menu1.inc` (generated) | S2MENU1-1 |
| `MENUW`'s places (`S2M_PALST` `$A500`, the marks `$B800`, the room's end `$A500`), `S2M_AMEMSTOP` `$C5` | `s2menu1.inc` | S2MENU1-2 |
| `m2_page`, `m2_value`, `m2_bench` | `s2_menut.s` | part `s2menu2` (wave 6): gone at its integration, `s2_menu2.s` linked (S2MENU2-3) |
| `pl_poll`, `pl_bindkey`, `pl_defkeys`, `pl_mouseup` | `s2_menut.s` | part `plinput` (wave 5, building now) |
| `fxc_scr` at `$BEE0` | `fx_pcache.s -D FXC_MSCR` (part `fxchan`'s) | FXCHAN-4, S2MENU1-2 |

## 9. Open problems

1. **The size**: 5,467 B against s2menu1's 5,000 B; code 3,720 B, data
   1,747 B (section 4). The data are the pages' strings and messages
   (515 B), their tables (305 B), the patch and font tables (582 B) and
   the gray map (256 B), which this report counts against 4.1's 2,500 B
   of names and strings. Levers: the patches' places from the 2D store's handles table
   at run time (about 400 B), the messages fetched from `S2STATE` (risk
   12's remedy).
2. **The full frames' cost**: 93 ms (`f121`) for a page change, 137 ms
   with text, against upstream's same 32,000-byte redraw; the gray
   conversion and the publish dominate. Levers: redraw only the menu's
   rectangle over the gray screen kept in a bank (the screen beside it is
   unchanged), or a byte map a palette built once at the open.
3. **`M_SETCHG`** is the second half's input (S2MENU1-6); the
   checkpoint injects the reference's `G_SettingsChanged` per frame, and
   the chained runs restart a chunk where it changes.
4. **The memory API's time** is a2vm's model (section 5).
5. The part took longer than its 1.5 hours.

## 10. The wave 5 integration (2026-10-01)

What the integrator did with each request (`docs/SCREENS.md` 8.9, "Wave
5 as integrated"):

| Request | Outcome |
| --- | --- |
| S2MENU1-1 | Applied **without `M_BINDWAIT` and `M_BINDCODE`**: `s2layout.MENUW_NATIVE` (`M_PALON` .. `M_FONTBUF`, 30 B) in `OWN_NATIVE`, so `state_places('MENUW')` allocates them after the field map's; the requests `REQ_*` are `s2layout.MENU_REQUESTS`; both in `s2.inc`, no longer in `s2menu1.inc`. The input layer's bind state is part `plinput`'s `PL_BIND` (below), so the two fields went and `M_SETCHG` .. `M_FONTBUF` moved down 2 B |
| S2MENU1-2 | Applied: `MENUW`'s room `$6600-$A4FF`, its runtime ranges as asked (`PALST`, the band, `UI_GRAY`, `marks`, the slot, `fetch buffer`, the state), `DRAW_PLACES['MENUW']` (`$B800`, `$BD00`, 2 pages), `MENUW_PALST` `$A500`, `PL['MENUAMEM']` `$C5`, `MODULE_ROW['fx_pcache']` = `fx_chan` (1,055 of 1,100 B). With PLINPUT-5's `pl_keys` (300) the old total 16,000 would pass the new room, so `MENUW`'s own budget is 11,328 (names and strings 2,328) and the total 16,128 (4.1). `s2menu1.py` takes `MENUW_PLACES`, `AMEM_STOP`, `FBPAGES`, `ROOM_END` from `s2layout` |
| S2MENU1-3 | Applied to SCREENS.md 1.5.3 (open, each frame, the actions' table), 4.3, 7.3 |
| S2MENU1-4 | Applied through `PL_BIND` (main `$03ED`), not `M_BINDWAIT`/`M_BINDCODE`: the shared poll cannot write `MENUW`'s W state. `r_bind` writes `PLB_WAIT`; `m_ticker`, with `M_BINDROW` set and `PL_BIND` not `PLB_WAIT`, binds a code below `$80` but Esc (`$1B`) with `pl_bind` (A the Doom key, X the code) and writes `PLB_IDLE`; `m_init` leaves `PL_BIND` to `pl_init`; `r_defkeys` calls `pl_defaults`; `m_frame` passes `pl_poll` A = `G_MENUACTIVE`'s low byte. The checkpoint maps the reference's state to `PL_BIND` (`iigs_bindwait` → `$FF`; with `bindRow` waiting the code taken, ADB Esc `$35` as the //e's `$1B`, others 1:1 as 6.2's poke; else `$80`), injects it with the input block as `pl_init` leaves it and the default key table, and compares it after every `M_Responder` and `M_Ticker` call (the ticker's check is new) |
| S2MENU1-5 | Nothing to apply (part `s2menu2`'s hooks; SCREENS.md 7.3 names them) |
| S2MENU1-6 | Recorded in `design.md` R7 item 9 |

`MENUW` now links part `plinput`'s `pl_input.o`, `pl_keys.o` and `pl_irq.o`
(`pl_time`); the write log's owners add `plinput.image_owners()`. The
stand-ins left in `s2_menut.s`: `m2_page`, `m2_value`, `m2_bench` (part
`s2menu2`) and `pl_mouseup` (the menu's MOUSE option, which `pl_poll` has
no byte for: part `plinput`'s open problem 2).

**The size split** (open problem 1): confirmed as this part's code
(3,728 B [M]) against its 5,000 B and its data (1,747 B) against the
names and strings, now 2,328 B; with part `s2menu2`'s key names (`plk_names`
1,024 B) that row would be about 440 B over, but `MENUW`'s own row as a
whole (11,328 B) has room: `s2m1` uses 9,738 of 16,128 B. The levers of
open problem 1 stay for wave 6.

Results after the integration [M]: `python3 tools/native/s2menu1.py --all
--jobs 2` (3 min 22 s): ok, as in section 2 (157 frame jobs, 10,271,568
bytes compared; 283 responder calls with `PL_BIND` compared; 863 ticker
calls in 155 chains with `PL_BIND` compared after each; the 7 sessions
chained; 0 problems; stack 21 B); the five planted bugs caught with the
same first failures; own 5,475 B (`s2_menu` 3,717, `s2_mvid` 1,758);
timing as section 5. `wip_test_m11_s2menu1`: 12 tests OK after its two
hand-made checks of the stand-ins were rewritten for the applied
requests (also on Python 3.9.6).

## 11. The wave 6 integration (2026-10-02)

Part `s2menu2`'s requests changed this part's files (`docs/SCREENS.md`
8.10; `s2menu2.md` 10): `s2_menu.s`'s `t_num` is the release's (the
display page's 4 rows, the sound page's 2) and `r_musvol` is `uiVolume`
on `SS_SETTINGS+5` (S2MENU2-2; D-M8 corrected); `s2_menut.s` no longer
stands in for `m2_page`, `m2_value`, `m2_bench`, and `s2menu1.mk` links
part `s2menu2`'s `s2_menu2.o`, so `s2m1` is the one `MENUW` (S2MENU2-3:
`s2m1t` and `s2m2t` are the same image); the owners name `s2_menu2`;
`STATE_RANGES` logs `snd_MusicVolume`, the field map's new field, which
the call log's injection needs. X-M2 stays in this part's checkpoint:
part `s2menu2`'s run A compares those pages on the same image.

Results after the integration [M]: `python3 tools/native/s2menu1.py --all
--jobs 2` (2 min 48 s): ok; 157 frame jobs, 314 runs, 10,271,568 bytes
compared, 0 differ; 283 `M_Responder` and 863 `M_Ticker` calls (155
chains), 0 problems; the 7 sessions chained (71 frames X-M2); stack 21 B;
the five planted bugs caught; own 5,503 B (code 3,756, data 1,747); a
full frame 93.2 ms, a skull 3.2 ms, the open 137.0 ms, the close 46.9 ms
(`f121`).
