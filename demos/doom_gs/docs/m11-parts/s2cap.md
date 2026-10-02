# Milestone 11, part `s2cap`: captures, scripts, injection

Part `s2cap` of wave 2 ([`docs/SCREENS.md`](../SCREENS.md) 7.3), 2026-10-01.
It follows SCREENS.md 1.6, 6.1, 6.2 and appendix A. Labels as in
`NATIVE.md`: [M] measured, [R file:line] read, [A] assumed. Nothing here
ports upstream code: everything is ref816 captures of upstream.

## 1. What was built

| File | What |
| --- | --- |
| `tools/native/s2cap.py` | The captures: the points and the call log of 6.1 resolved from `build/linkmap.json` and the release's code (`places`, `points`, `routines`); a ref816 run with the dump stream on a pipe and the call log on a named pipe, both read as they come and never stored (`machine`, `Distiller`, `CallSink`); the cases (`RunCases`, `Case`); the checks (`check_frames`, `check_sounds`, `check_injection`, `a2vm_injection`, `two_run`, `same_capture`, `goals_check`, `check_run`, `check_all`). `--points`, `--capture`, `--check [--twice] [--two-run N]` |
| `tools/native/s2state.py` | The injection of 6.2: a case's fields for one screen of 1.6 by `s2layout.field_map()` into their native places (the game's, the card's `S2T_*`, the image's state block at its `S2STATE` place, `SS_PALST`, `S2STATE`'s `SS_*`, the player through `llayout.player_layout`), the screen into aux 0, both fills, the poisoned screen; `read_back` and `poison_problems`; the //e key names and table as a ref816 `--poke-file` (`keys_poke`, with `apple2e_keys` a marked stand-in) |
| `coverage/m11/menus.script`, `automap.script`, `palette.script`, `finale.script`, `signs.script`, `stbar.script` | The six scripts of 6.1 |
| `src/native/m11/s2cap.mk` | `part P=s2cap` (the points resolve), `s2cap-capture`, `s2cap-check`, `s2cap-clean`; not in `all` |
| `tests/wip_test_m11_s2cap.py` | 16 tests (below) |

Build output: `build/native/m11/cases/RUN/` (`index.json`, `cases.pack`,
`blobs.pack`, `calls.z`: 22.9 MB for the eleven runs) and
`build/native/m11/s2cap/` (`report.json`, the logs of the last runs).
Every run's temporary directory is a `tempfile` directory there, deleted
after the run.

### 1.1 The points as built (differences from 6.1's table: request S2CAP-2)

Upstream's frame has more shapes than 6.1's table assumed, found by
running it:

- **While a menu is up `display` is never called.** `uiOpen` points
  `displayCall`'s JSR at `menuDisplayNear`, which jumps to `uiDisplay`
  [R `i_viigs65.s:2038-2055`, `d_main65.s:513-514`]. Its static turns,
  which draw nothing, come about 2,000 a second [M: 200,000 in one run
  of menus.script before this was handled]. So a frame starts where it may
  first write: `PD0:display` at `displayCall` when its operand is
  `display`, `PD0:menu` at `uiDisplay`'s `jsl M_Drawer`, `PD0:skull` at
  `staticUpToDate`'s skull path. A static menu turn dumps nothing.
- **The frame's end.** `PD1` is at `displayCall + 3` when the operand is
  `display`. A menu's frame ends where the next thing begins. A display
  frame in which a menu opened has no `PD1` (`uiOpen` changed the operand
  before it), and ends at the next frame's start; the menu pauses the
  tics, so nothing comes between (`lazy_ends`: 4 in menus, 8 in palette).
- **The screen, `STCACHE`, `TINTPAL` and `AM_LISTS` are carried.**
  Dumping 32 KB at every frame's start and end took the menus run past
  200 MB of pipe traffic. Each is dumped where a write of it is complete
  (`PC:*`): the screen at `I_FinishUpdate`'s two `RTL`s, `I_ShowDirty`'s,
  `titleWipe`'s own return to `D_Wipe`'s caller [R `w_level65.s:1430-1447`]
  and the returns of `bmSignBox` (the busy sign's rows put back by MVN;
  `bmSignOff` is also reached by `JMP` [R `m_menu65.s:1798`,
  `w_level65.s:519`]); `STCACHE` after `I_SaveStatusBackground` and
  `V_DrawRaw`, which falls into it [R `i_viigs65.s:1355-1367`]; `TINTPAL`
  after `buildTints`; `AM_LISTS` after `AM_Drawer` with the map on. A
  frame's carried values at its start are `CB`, those it changed `CA`.
  **Every 8th frame start** (`PDX:*`) dumps them all and checks the
  carried value equal: 1,525 checks over the runs, 0 differences. Two
  writers were found that way and added: `titleWipe` (the two-run check
  caught it on the first title page, 1,078 bytes of rows 191-199) and
  `bmSignBox` (a `PDX` in the tour, 1,632 bytes).
- **Level frames leave the renderer's rows out.** In a frame with `PV`,
  not paused and with no menu, the rows of X1 (0-167, or 10-167 when
  `viewtop` is 9; the title's rows 160-167 kept with the overlay, 160-166
  until wave 4's S2HUD-5) are zero
  in `CB`, `CA`, `PW` and `PC:SCREEN`, listed in the case's `blank`; the
  injection gives them the fill, so they are poison, as 6.2 says of every
  byte a case does not define.
- **More points.** `PV` is a dump point (and also logged with its
  caller); `PM` dumps the screen at `I_MenuPalette`'s entry when the menu's
  palette is not on (the view the menu grays, which no frame start holds);
  `PDF` dumps the marks and the whole 2D state at `I_FinishUpdate`'s entry
  (the state after the drawers); `PU0`/`PU1` at each JSL site of the
  events (`bmSignOn`, `bmSignOff`, `bmSignLoading`, `bmSignSaving`,
  `bmDiskAsk`, `F_LoadScreen`, `I_MenuPaletteBack`) and its return, so an
  update outside a frame (the sign, the load screen, the menu's close)
  has a case of its own.
- **`HU_Ticker` and `F_Ticker` are reached by `JMP`** from `G_Ticker`
  [R `g_game65.s:615-623`], like `S_UpdateSounds` from `musFrame`: all
  three are logged with `jumps=1` (without it `HU_Ticker` and `F_Ticker`
  logged 0 calls [M]).
- **`S_UpdateSounds` while a menu is up.** `musFrame` calls it in every
  turn, so about 2,000 times a second while a menu is up; it and its
  per-turn callees (`isPlaying`, `docVolume`, `adjustParams`) are logged
  while `_g_menuactive` is 0. The check of 6.1 is on those turns (every
  turn of `display` without a menu). A menu's own sounds (`S_StartSound`
  and its callees) are all logged.
- **DEMO1 and DEMO2** are the sound calls of 6.1, captured without
  screens.

### 1.2 The cases

A run's `index.json` lists each frame and event (its place in
`cases.pack`, SHA-256, cycles, points, blank rows), the blob keys and the
run's counts and problems. A case is zlib of a JSON header line and its
inline bytes; a range of 1 KB or more is in `blobs.pack` by its SHA-256,
once a run (identical screens and caches are stored once); a shorter range
`PD0` also has is XOR'ed with it. `s2cap.RunCases(path)` gives the frames
and events as `Case` objects: `before` (the state at the start), `after`
(`PD1`, or `PU1`), `carried(name, after=False)`, `screen_before`,
`screen_after`, `blank_offsets()`, `all(point)`; `calls()` the call log.

For the later parts: `s2state.inject(case, screen, fill, poison)` gives
the records for `s2run.run(..., extra_records=...)`; `read_back` and
`poison_problems` check them; `s2state.marked(case)` is the set of screen
bytes the reference's frame wrote.

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
df -h /System/Volumes/Data                             # 77 GB free
python3 tools/native/s2cap.py --capture --jobs 2       # 25-38 s
python3 tools/native/s2cap.py --check --twice --two-run 3 --jobs 2
                                                       # 2 min 30 s
python3 tools/testpar.py tests/wip_test_m11_s2cap.py   # 16 tests, 11.7 s
make -C src/native -f m11.mk part P=s2cap
```

Results [M, 2026-10-01]: `report.json` `ok: true`, 0 problems.

| Run | Frames | Events | Level frames = PV | Turns | `S_UpdateSounds` | `isPlaying` | `docVolume` | `stopChannel` | Injections | Two-run | Goals | Pipes MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| demo3 | 1,573 | 1 | 534 | 1,573 | 534 | 2,233 | 646 | 302 | 44,072 | 3 | | 66.7 |
| newgame | 170 | 2 | 128 | 156 | 129 | 60 | 18 | 17 | 4,816 | 3 | | 11.8 |
| tour | 355 | 18 | 112 | 354 | 113 | 152 | 22 | 86 | 10,444 | 3 | | 24.9 |
| demo1 | (sounds) | | | 2,296 | 1,257 | 4,589 | 1,387 | 684 | | | | 37.4 |
| demo2 | (sounds) | | | 1,998 | 959 | 1,316 | 366 | 219 | | | | 24.4 |
| menus | 206 | 8 | 40 | 48 | 41 | 24 | 7 | 109 | 5,992 | 3 | 17 | 13.6 |
| automap | 121 | 2 | 29 | 120 | 93 | 2 | 1 | 10 | 3,444 | 3 | 8 | 9.5 |
| palette | 206 | 10 | 98 | 125 | 98 | 36 | 9 | 90 | 6,048 | 3 | 4 | 14.9 |
| finale | 97 | 2 | 5 | 96 | 69 | 2 | 1 | 10 | 2,772 | 3 | 4 | 5.5 |
| signs | 50 | 4 | 9 | 49 | 10 | 20 | 3 | 19 | 1,512 | 3 | 3 | 3.2 |
| stbar | 235 | 2 | 206 | 233 | 206 | 2 | 1 | 10 | 6,636 | 3 | 36 | 16.9 |

| Checkpoint item | Result |
| --- | --- |
| Every run of 6.1 captured twice with the same cases | all eleven: `index.json`, `cases.pack`, `blobs.pack`, `calls.z` byte for byte |
| 0 decode problems | 0 (every case's SHA-256, every range, every carried range at start and end, blank rows zero) |
| `PV` in every level frame | every level frame (display's frame, gametic != basetic, at `I_FinishUpdate` `GS_LEVEL`, `DD_VIEW` 1, `DD_PAUSED` 0) has exactly one, none elsewhere but paused frames; and `viewtop` is 9 exactly when `message_on` (display's rule [R `d_main65.s:467-474`]) |
| `S_UpdateSounds` once a frame with a mobj (`jumps=1`) | once in every turn without a menu where the player has a mobj, none in the others; `isPlaying` under it exactly once a channel with a sound, every call; `docVolume`, `stopChannel` logged |
| Each case injected and read back equal | every frame and event, 7 screens, both fills, plain and poisoned: 85,736 injections on the host, 0 differences; 2 frames a screen run on a2vm, both fills, the records of all 7 screens at once (s2lay's `s2lt`, empty call list, the whole machine at the stop): 36 runs, 0 differences |
| A sample of `PD1` screens equal to the two-run method's | 3 display frames a screen run (the first, and the two marking the most bytes): a run to the cycle where that `display` returned (the call log's) with `--save E12000:32768`; equal outside the undefined rows; each run's sample changes the screen |
| The scripts reach what they name | 72 goals, all reached (menus: every page and row, the four messages, a binding changed and the defaults back, the gray view, messages off and on; automap: full, overlay, follow off and on, zoom, pan, the computer map, a view rendered with the overlay; palette: gamma 0-4 with the view up, the red, bonus and radiation tints; finale: the text, the mid stage, the picture; signs: the busy sign drawn, the world-done load; stbar: the 3 keys, the 9 arms, ready weapons 0-5, ammo and maxammo at each of 0, 9, 10, 99, 100, 200, 400, health 0/100/200, armour 0/200, god mode, the backpack, pain, the evil grin) |
| `df -h` before the first capture | printed by `--capture` (77 GB free) |
| All cases under 60 MB | 22.9 MB |
| `tests/test_sound_*` | not touched |

Also: the demo3 sound starts, 366 `S_StartSound`, 64 `S_StartSound2`, 254
`S_StopSound`, are appendix A's counts [M]; demo3 has 534 level frames
(6.1's estimate said 533) among 1,573 frames.

### 2.1 The tests

`tests/wip_test_m11_s2cap.py` (16 tests; also OK on Python 3.9.6 with
`-W error::ResourceWarning`): the //e table stand-in; the case codec on a
hand-made case; the points where the sources put them; signs.script
captured twice (the same files), its frames, sounds, injection on the host
and on a2vm, two-run, goals; the //e names and table poked into ref816 and
found in the state `I_FinishUpdate` sees on the key setup page (the run
stops on that page: the menu's own keys go through `keyTable`, and the
page takes 1.4 s of machine time to draw [M]); the planted bugs; the
captured cases (size, every index clean). Without `build/` only the first
two run; the others skip naming what is missing.

### 2.2 Planted bugs (each in a scratch copy of the tool)

| Planted | Caught by | Message [M] |
| --- | --- | --- |
| `PD1` (the screen at the frame's end) at `I_FinishUpdate`'s entry instead of its return: the screen's writer points at the entries of `I_FinishUpdate` and `I_ShowDirty` | the two-run check | `f000036: 32476 bytes differ from the run to cycle 158619173 (first $2000)` |
| A word field injected as a byte | the read back | 25 fields, e.g. `m_menu65.s:_g_menuactive: $A500 read back for $0 (word at main 00:1E6B)` |
| The poison not covering a marked byte (the first one skipped) | `poison_problems` (the marks computed from the case) | `1 marked or undefined bytes are not the fill (first $2000)` |
| `S_UpdateSounds` logged without `jumps=1` | the per-turn count | 0 logged, `the turn at cycle 140897853: 0 S_UpdateSounds with mo $065B78` (11 turns) |

The first planted bug first passed, with the two-run sample taken at the
first, middle and last frames, whose updates rewrote identical bytes; the
sample now takes the frames that mark the most bytes (from `PDF`'s marks,
which do not depend on the screen points).

## 3. Sizes against the budget

| Item | Budget | As built [M] |
| --- | --- | --- |
| A capture run's wall time | 25 minutes | the eleven in 25-38 s with 2 jobs; the longest, demo1 (735 s of machine time, 31,907 calls), 13-16 s |
| A run's pipe traffic | 200 MB | at most 66.7 MB (demo3); bounded by `PIPE_LIMIT` as it is read |
| Runs at once | at most 4 (the task: 2) | 2 |
| All cases | 60 MB | 22.9 MB |
| The part | 1.5 hours | more: the frame shapes of 1.1 took most of it |

## 4. Requests (for the integrator)

### S2CAP-1. `tools/native/s2layout.py`, the field map: `st_palette` is a signed byte

`ST_initData` sets `st_palette` to `$FFFF` [R `st_stuff65.s:226-228`]
until `ST_doPaletteStuff` first runs, and every level's first frames hold
it [M: every screen run, `report.json` before the stand-in]; the map's
`byte` cannot hold it. In `_stbar()`:

```
-    out += [_f(s, st + 'st_palette', 2, 'byte', 'state', 'P_STPALETTE'),
+    out += [_f(s, st + 'st_palette', 2, 'sxbyte', 'state', 'P_STPALETTE'),
```

Stand-in meanwhile: `s2state.ENC_STANDIN`, marked; remove it when this is
applied.

### S2CAP-2. `docs/SCREENS.md` 6.1, the points as built

Replace the table's rows `PD0`, `PD1`, and add after the table, with 1.1
above as the evidence:

```
| `PD0` | `pc=displayCall` when its operand is `display`; while a menu is up (`uiDisplay`, which never enters `display` [R `i_viigs65.s:2038-2055`]) at `uiDisplay`'s `jsl M_Drawer` and `staticUpToDate`'s skull path, where the frame may first write; a static menu turn dumps nothing | the 2D state of 1.6 by symbol (the near and znear data of the units below), `_g_player`, `keyTable`, `keyNames` |
| `PD1` | `pc=displayCall+3` when its operand is `display`; a menu's frame ends where the next begins | the gametic |
| `PC` | where a write of the screen, `STCACHE`, `TINTPAL` or `AM_LISTS` is complete (`I_FinishUpdate`'s and `I_ShowDirty`'s `RTL`s, `titleWipe`'s return, `bmSignBox`'s, `I_SaveStatusBackground`'s and `V_DrawRaw`'s, `buildTints`', `AM_Drawer`'s with the map on); every 8th frame start dumps all four and checks them | the range written |
| `PM` | `I_MenuPalette`'s entry when the menu's palette is off | the screen the menu grays |
| `PU0`, `PU1` | each JSL site of `bmSignOn`, `bmSignOff`, `bmSignLoading`, `bmSignSaving`, `bmDiskAsk`, `F_LoadScreen`, `I_MenuPaletteBack` and its return | the 2D state and the screen: an update outside a frame |

The frames' screen rows of X1 are not kept (undefined, poisoned when
injected). `HU_Ticker` and `F_Ticker` are reached by `JMP` from `G_Ticker`
[R `g_game65.s:615-623`] and logged with `jumps=1` too. `S_UpdateSounds`
runs in every turn of the main loop, about 2,000 a second while a menu is
up: it and its per-turn callees are logged while no menu is up, and the
check is on those turns.
```

and in "Budget": `demo3's 533 frames about 5 MB, all runs under 60 MB
[A]` becomes `demo3's 1,573 frames (534 level frames) 7.1 MB, the eleven
runs 22.9 MB [M: part s2cap]`.

### S2CAP-3. `docs/SCREENS.md` 6.1, `automap.script`'s row: no `iddt`

Upstream has no `iddt` cheat; its map of every line is the computer map
power [R `m_cheat65.s:116-247`, `am_map65.s:1720`]:

```
-... the map key (off); the `iddt` cheat's map |
+... the map key (off); the computer map (`idbehold a`, `powers[pw_allmap]`: upstream has no `iddt`) |
```

### S2CAP-4. `docs/SCREENS.md` 6.2, where the //e key table is poked

```
-The key setup's names and bindings for the //e are poked into
-ref816's `keyNames` and `keyTable` by `--poke-file` before the page is
-drawn, so upstream's drawer stays the truth (1.5.3).
+The key setup's names and bindings for the //e are poked into
+ref816's `keyNames` and `keyTable` by `--poke-file` at `M_Drawer`'s
+entry the first time `currentMenu` is the key setup (8), so upstream's
+drawer stays the truth (1.5.3); the menu's own keys go through
+`keyTable` too, so such a run stops on that page.
```

### S2CAP-5. For part `fxchan`: the sound positions are not in the cases (open problem 1)

## 5. Stand-ins (marked in the code)

| Stand-in | Where | Until |
| --- | --- | --- |
| `st_palette` injected as a signed byte | `s2state.ENC_STANDIN` | S2CAP-1 |
| The //e key names and table | `s2state.apple2e_keys` (from SCREENS.md 1.5.3 and 2.4: the fold to upper case, `CTRL-A`..., `LEFT`, `ESC`, the pseudo-keys `$70`-`$73`, 2.4's default bindings) | part `plinput`'s table; `keys_poke` takes any |
| The player's `mo` and `attacker` | injected as handle 0 (the player's mobj), 1 (another) or `$FFFF` (null) | milestone 10's mobj table in a case |

## 6. Decisions where the design left a choice

- **A frame's start and end** follow the code that may write (1.1), not
  `display`'s entry alone.
- **Carried ranges** with a sampled check instead of a dump at every frame
  start: the samples (every 8th frame) check the whole window since the
  last writer's dump, and the two-run check covers the frames in between.
- **Static frames**: a frame of `display` that writes nothing is still a
  case (the title page's 1,000 frames in demo3); identical consecutive
  ones would be one case with a repeat count, which no run produced (the
  gametic changes between them).
- **The level frame** of the `PV` check is decided on the reference's own
  state at `I_FinishUpdate` (`DD_VIEW`, `DD_PAUSED`, `gamestate`), not on
  `PV`.
- **Unfit values** (an upstream value the field map's encoding cannot
  hold) are reported by field; `st_palette` was the only one (S2CAP-1).
- **Deferred fields**, whose native form a later part decides, are listed
  and never guessed: `GSVIEWn`, `LVG0`, `LNMAP` (the level's), `AM_LISTS`'s
  2,048-entry form (`s2amap`), `frame.AUTOMAP` (the frame driver's),
  `TINTPAL`'s place in `S2PAL` (`s2pal`), `textText`'s records (`s2hud`),
  `player.message` as an id (`s2hud`, R5), `GTAB`.

## 7. Open problems

1. **The sound positions.** 6.1 asks for the player and the zone banks at
   each `S_StartSound` and `S_UpdateSounds` entry. The zone is banks
   `$06-$09` [R `memmap.inc`]: 256 KB a dump, thousands of calls a demo,
   far past 200 MB. What is captured: `adjustParams`' entry with
   `_Dp[0-7]` (the listener's and the source's addresses) and the channel
   block, its return with `SS_VOL`, `SS_SEP` and the carry (audible).
   The x and y of the two mobjs are not. Part `fxchan` can capture them
   with dump points whose ranges are those mobjs (one point an address,
   from this log), or ref816 could take a range relative to a pointer in
   memory (a change to ref816, not this part's).
2. **`S_UpdateSounds` with a menu up** (`MENUW`'s `sc_update`, 0.1 F11)
   has no logged calls: a sampled log (`hits=`) of them is for
   `s2menu1`/`fxchan`.
3. **Event cases are the JSL sites'**: `bmSignOff` reached by `JMP` has no
   event case of its own (its write is carried, through `bmSignBox`).
4. **The view rows of level frames are not kept** (X1); a part that needs
   the view under its drawing in a level frame (none in 1.5 does: the
   map's title over the view is kept) needs a capture of its own.
5. The part took longer than its 1.5 hours.

## 8. The wave 2 integration (2026-10-01)

What the integrator did with each request (`docs/SCREENS.md` 8.6, "Wave
2 as integrated"):

| Request | Outcome |
| --- | --- |
| S2CAP-1 | Applied: `st_palette` is `sxbyte` in `s2layout.py`'s field map; `s2state.ENC_STANDIN` removed |
| S2CAP-2 | Applied to SCREENS.md 6.1 as written (the rows `PD0`, `PD1`, `PC`, `PM`, `PU0`/`PU1`, the paragraph after the table, with a sentence on the sound positions; the budget as measured) |
| S2CAP-3 | Applied: 6.1, `automap.script`'s row |
| S2CAP-4 | Applied: 6.2 |
| S2CAP-5 | Nothing to apply; in SCREENS.md 8.6's open items for `fxchan` |

After it: `s2cap.py --check --twice --two-run 3 --jobs 2` `report.json`
`ok`, 0 problems, no unfit value (2 min 31 s); `wip_test_m11_s2cap` 16
tests OK (also on Python 3.9.6). The deferred fields and the open problems
of section 7 stay. Also new in `s2.inc` since this part: `PS_BEGUN` at
`PALST` `$02D1` (S2DRAW-5), which no case defines, so an injection leaves
it poisoned; the part that first links `s2_pal` sets it 0 at a frame's
start.
