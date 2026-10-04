# The playable game: the main loop, the glue and the boot disk

Status: **assembled 2026-10-02 and played on a2vm** (f121, scripted
input; not yet run on the card: the owner's test). `build/native/DOOM.hdv`
links every part of milestone 10 (all 29, `G_Ticker` and `P_Ticker`
included), milestone 9's load and setup, milestones 7-8's renderer,
milestone 11's screens, platform and effects, and the music player, with
this main loop; no stub is left. It boots to the title page with its
music, runs the title loop with demo3, the menus, a new game, E1M1 played
to its exit, the intermission and E1M2. Section 12 is the owner's guide
(the card, the keys, what is missing, the known problems); section 13 the
scripted runs and what they showed; section 8 the frame rates.

It sits on [`GAME.md`](GAME.md) (milestone 10: the tic image, the groups,
the load protocol, the hooks), [`SCREENS.md`](SCREENS.md) (milestone 11:
the 2D images, the platform, `DOOM.SYSTEM`), [`RENDER.md`](RENDER.md) and
[`RENDER-MASKED.md`](RENDER-MASKED.md) (the renderer's phases),
[`LEVELS.md`](LEVELS.md) (the store and the load) and
[`MEMORY_MAP.md`](MEMORY_MAP.md). Their files are read only here; what
this work needs changed in them is asked in
[`play-requests.md`](play-requests.md).

## 1. The pieces

| Piece | Files | Where it runs |
| --- | --- | --- |
| The kernel: a resident loop that runs step lists | `src/native/dl_kern.s` | Main card `$FF00-$FFBD` (pl_ready's place), its menu loop in main `$0880-$08FF` and `$0B94-$0BFF` |
| The brain: D_DoomLoop's logic, tryRunTics, the events, the menu's requests | `src/native/dl_brain.s` | The tic image's group `DLG_BRAIN` (slot 2) |
| G_BuildTiccmd, buildNewTiccmds, P_SwitchWeapon, the weapon cycle | `src/native/dl_cmd.s` | Group `DLG_CMD` (slot 1) |
| D_Display: which images draw the frame, the step lists | `src/native/dl_disp.s` | Group `DLG_DISP` (slot 1) |
| The hooks milestone 10's parts call (sounds, I_GetTime, AM_*, ST_*, HU_*, WI_*, F_*, D_PageTicker, D_AdvanceDemo) | `src/native/dl_hook.s` | The tic image's core and group `DLG_HOOK` (slot 1); the HUD's ticker `s2t_hu.s` and `fxc_scr` in the core since speed wave 2 (`play.mk`'s `PLAY_TIC`) |
| The songs, the title loop's D_DoAdvanceDemo, the renderer's boot and level state | `src/native/dl_snd.s` | Group `DLG_SND` (slot 1), with `s2t_st.s` |
| P2DW's frame glue (poll, palettes, status bar, HUD) | `src/native/dl_p2d.s` | The `P2DW` image |
| DLINIT: the boot's PRIVATE copies, the quit's last screen | `src/native/dl_init.s` | W `$6600`, loaded from `DLBANK` |
| Layout, links, disk | `tools/native/playlayout.py`, `playlink.py`, `playdisk.py`, `src/native/play.mk`, `src/native/dl.inc` | host |

The game's own parts (milestone 10's integrated waves, milestone 11's
images, milestones 7-9's renderer and load) are linked as they are built:
`play.mk` takes their objects and generated layouts, never their sources'
copies.

## 2. A frame

Upstream's `D_DoomLoop` (`d_main65.s`) runs, each frame: the input, the
tics the clock gives (tryRunTics: `buildNewTiccmds`, then `G_Ticker` once
per tic), the sounds (`musFrame`), and `display`. Natively W
(`$6000-$BFFF`) holds one image at a time, so the frame is a sequence of
phases, each with its image in W:

| Phase | What | Image in W | Code |
| --- | --- | --- | --- |
| Input | `pl_poll` (keys, Apple keys, mouse) into the event queue `PL_QUEUE`; the effects' service and the music's ring | `P2DW` (`s2_poll`; also each `s2_frame`) | milestone 11's `pl_input.s` |
| Events | `D_PostEvent`'s routing: ESC to the menu (`MENUW`), the cheats (`C_Responder`), the automap's keys (`AMAPW`'s `am_responder`), `G_Responder` (title: any key opens the menu; in a level `gamekeydown`) | the tic image; `AMAPW` or `MENUW` for their responders | `dl_brain.s` (`b_events`) |
| Tics by the clock | `buildNewTiccmds` (a command per new tic of `pl_time`, at most `MAXTICS` ahead), then `G_Ticker` per command (`runtics = maketic - gametic`), the load protocol when a tic loads a level (`GT_LOAD`: section 3) | the tic image (W, core, two group slots) | `dl_brain.s`, `dl_cmd.s`; `G_Ticker` is part tic's |
| Sound | `S_UpdateSounds` (`sc_update`: the positional effects), the songs by `fx_song` | the tic image; the player in the card | `dl_hook.s`, `dl_snd.s` |
| Render: front end | BSP walk, walls, planes, records (`nr_frame`) | `WCODE` (bank 112) + the level's W tables | milestone 7 |
| Render: masked | sprites, masked walls, the weapon (`nm_masked`, `nm_bkload`) | `MCODE` (bank 113) | milestone 8 |
| Replay | the records onto the screen (`nb_frame`; the automap overlay `OVLW` first when on) | card and main `$0C00` (W free) | milestone 8 |
| Full automap, intermission, finale, title page | `am_frame`, `wi_frame`, `fin_frame` | `AMAPW`, `WIW`, `FINW` | milestone 11 |
| Palettes | the level's tints at its first frame, gamma | `PALW` | milestone 11 |
| Status bar, HUD, wipe, palette show | `s2_frame`: `st_palette`, `st_drawer`, `hu_drawer`, the black-first wipe (SCREENS.md F1) | `P2DW` | milestone 11 + `dl_p2d.s` |
| Menu | while a menu is up: only `M_Ticker` per new tic and `m_frame` (upstream's paused `uiDisplay`) | `MENUW` | the kernel's menu loop |

The order of a level frame, as built: K_TIC (the tic image back, the
brain: events, commands, tics, sounds, the list) → `K_WLOAD` →
`nr_frame` → `K_MLOAD` → `nm_masked` → `nm_bkload` → `nb_frame` →
`P2DW` → `s2_frame` → `K_END` (the next frame).

## 3. The kernel and its step lists

The brain cannot stay in W while the frame's images run, so at every
frame it writes a step list into `DLBUF` (card `$FE80-$FEFF`) and returns
to the kernel, which runs it:

| Step | Bytes | Does |
| --- | --- | --- |
| `K_END` | 0 | the list's end: `K_TIC E_FRAME` |
| `K_LOAD` | 1, bank, runs..., 0 | `far_pload` of the bank's page runs into the same addresses of main; since the copy engine (section 18) one memory-API PRIVATE request, a descriptor a run (`gcall.s`'s `am_runs` in the card), and the front end's window and the masked image come this way too (the brain's `img_wload`, `img_mload`: `far_wloadt`'s and `far_mload`'s runs) |
| `K_CALL` | 2, address, A, X | `jsr` with A, X (Y 0); its A into `DL_RES` |
| `K_WLOAD` | 3 | `far_wloadt` (the front end's code from page `$65` and the level's W tables; since speed wave 2: the tic image left the same `MATHW` bytes in `$6000-$64FF`, `playdisk.shared_w_problems` asserts it); since the copy engine a stop (the brain writes a `K_LOAD`, section 18) |
| `K_MLOAD` | 4 | `far_mload` (the masked phase's image); since the copy engine a stop, as `K_WLOAD` |
| `K_TIC` | 5, code | the tic image's core (and its W unless the list ended with P2DW, which left the same bytes in `$6000-$65FF`: then from page `$66`) from `GCODE0` and each plane's pages below `G_MOHWM` from `MOBJP` (speed wave 2), the slots empty, then `dl_brain` through `gcall.s`'s `fc_go` with `DL_CODE` = code; `planes_out` writes the planes back in one `RAMWRT` window and sets the next `K_TIC`'s two load lists (`k_core`, `k_planes` at `KLISTS`) |
| `K_MENU` | 6 | the menu's paused frames with `MENUW` in W, until the menu closes or asks something (`M_REQ`) |
| `K_HALT` | 7 | the quit's end |

The brain's entries (`DL_CODE`): `E_BOOT` (the boot's inits, the title),
`E_FRAME` (a frame), `E_RESUME` (after a load: `g_resume`, the level's
frame-block fields, `S_Start`, `G_Ticker` again), `E_EVENT` (the
automap's answer for the queue's head), `E_MENU` (the menu's request: new
game, end game, quit, save, the benchmark).

**The load protocol** (GAME.md 3.4): a tic whose action loads a level
returns `GT_LOAD`; the brain writes the load list (`fin_load` when
`F_LoadScreen` asked for it, the loading sign, `LCODE`'s `nl_setup` of
`G_GAMEMAP`, the sign off, `K_TIC E_RESUME`); at `E_RESUME` the brain
calls `g_resume`, clears the keys, sets the level's frame-block fields
and `S_Start`, then `G_Ticker` again at its action loop (part tic's
`gt_loop`, through `dl.inc`'s `GTRESUME`), as part tic's own driver's
`g_tresume` does and upstream goes on after the action returns.

The kernel keeps nothing in zero page between steps: its state is `KV_*`
(card `$FE7B-$FE7F`) and the brain's `DL_*` (main `DLM`, `$1F00-$1F7F`,
122 of 128 B with the benchmark's `DL_BENCH`, `DL_BVIEW`, `DL_BRT` and
its phase timing's `BT_*` (section 15):
`python3 tools/native/playlayout.py --report`).

## 4. Memory

| Space | Range | Holds |
| --- | --- | --- |
| Main card | `$FF00-$FFB6`, `$FFB8-$FFC3`, `$FFC4-$FFD4`, `$FFD5-$FFF7` | the kernel's code (`$FFB7` padding), its two load lists `k_core` and `k_planes` at `KLISTS` (speed wave 2: `dl_disp.s` in the tic image rewrites them each frame), the benchmark timing's `bt_replay` at `BT_REPLAY` (17 B, section 15) and, since speed wave 1, `far_gcopy` at `KERN_GCOPY` (`glayout.py`): `gr_load`'s copy of a group in one `RAMRD` window, since wave 2 its length only (from byte 256 − its tail of the page before it). 248 of the 250 B before the vectors. Since the copy engine (section 18) the code is 16 B shorter (`k_wload`, `k_mload` gone: `dl_halt` at `$FFA4`, `$FFA7-$FFB7` padding) and `far_gcopy` is called by no game code (`CALIB.hdv` times it) |
| Main card bank 1 | `$DB5C-$DBFF` | since the copy engine (section 18): the memory API's transport `AMEMLC` (`gcall.s`, 164 B), from the tic image's link |
| Main card | `$FE80-$FEFF`, `$FE7B-$FE7F` | `DLBUF` (the step list), `KV_*` |
| Main | `$0880-$08FF`, `$0B94-$0BFF` | the kernel's menu loop and the benchmark timing's `bt_mark` at `BT_MARK` (`$08CA`) and `BT_MARK2` (`$0BE1`) (read-only code, copied by DLINIT's PRIVATE request with the static tables: MEMORY_MAP.md 3.2's free bytes, never `$0878-$087F`; `$08F3-$08FF` free) |
| Main | `$0844-$0867` | `bt_mark`'s middle part `bt_ext`, which the brain's `bt_start` writes there at each benchmark's start (section 15) |
| Main | `$1F00-$1F7F` | `DLM`: the brain's state (`DL_*`) |
| Main | `$0310-$036F`, `$0F00-$13FF`, `$18A0-$18AB`, `$1A80-$1B7F` | the renderer's frame block, spans, `WPREV`, `TEXTRANS`: set at the boot by `s_rinit` (section 9 item 5) |
| W | `$6000-$BFFF` | one image at a time (section 5) |
| RamWorks 1 (`DLBANK`) | `$0200` request, `$1000` sources, `$6600` DLINIT | the boot's PRIVATE request and what it copies |
| RamWorks 48 (`SPRT`) | `$5400-$54DB` | `SPRBOUND`, written at the disk's build (section 9 item 6) |
| RamWorks 72-73 (`GCODE0-1`) | `$0200-`, `$6000-$99FF` | the tic image: its W and core at W's addresses, its groups packed (GCODE0 then GCODE1) |
| Main | `$2000-$5FFF` | since the frame slots (section 17): during the tic phase the pinned groups, over colormaps A and B, which the brain's last step puts back |
| RamWorks 91 (`DEMOB`) | | demo3 (DOOM1.WAD's `DEMO3`) for the title loop |
| RamWorks 104 (`S2STATE`) | `$0200-` | the 2D state's first values (the palette state, the automap's, the HUD's, the menu's save slots' text, the settings' defaults) |

**The tic image** (glayout's game layout, linked by `play.mk` with
`playlink.py --tic-cfg`): W `$6000-$65FF`, core `$6600-$993D` (13,118 of
13,312 B with speed wave 2's placement; 13,007 with wave 1's), slot 1 `$9E00-$A5FF`, slot 2
`$A600-$ADFF`, the planes `$B400-$BFFF`. The glue's groups follow
milestone 10's, 43 since speed wave 1: `DLG_B` 1,097, `DLG_C` 1,603,
`DLG_D` 1,937, `DLG_H` 1,775 (7 pages since wave 2: the HUD's ticker left it), `DLG_S` 1,270 B (of 2,048: `make -f
play.mk sizes`). Since wave 2 the group directory holds each group's whole pages and the bytes of its last page (`grp_tail`), and `gr_load` copies only the group's length. `gcall.s`'s slot cache tags (`SLOT_GRP`) and, since
speed wave 1, the lazy restore's `SLOT_NEED` are reset at each `K_TIC`
because every other image overwrites the slots.

Since the frame slots (2026-10-03, section 17; `docs/SPEED.md` 9) 12
groups are pinned to places of their own in main `$2000-$5FFF` (64 pages),
loaded by one memory-API PRIVATE request at their first call in a frame,
their colormap bytes put back by the brain's last step (`fs_restore`);
`SLOT_GRP` holds 19 slots, `SLOT_NEED` 18, then `FS_DIRTY`, all reset at
`K_TIC`. The core `$6600-$9939` (13,114 B) no longer holds `gspec.s` or
`g_resume` (`DLG_B` 1,263 B holds `g_resume` now).

**Zero page.** Each image uses its own (MEMORY_MAP.md 13, SCREENS.md 4.3).
The glue in the tic image uses the game's temporaries `GT_0-6`
(`$5C-$62`) and `GA_0-10` (`$48-$52`), `FA_*` for `far_get`, `FC_*` for
`fc_call`, `GC_MP` for `mo_get`; none is live across a step. The kernel
uses none.

## 5. The images and their loads

| Image | Bank, pages | Load, measured or from the rate |
| --- | --- | --- |
| Tic image (W + core + planes) | 72 and 74: 58 + 12 pages; since speed wave 2 52 + 4-12 (the core from `$66` after P2DW, the planes below `G_MOHWM`) | 4.4 ms (from the rate); less since wave 2; since the copy engine (section 18, a2vm `f122-nod2`) 0.57 + 0.15 ms, two requests |
| A group (slot) | 72-73: up to 8 pages | 0.5 ms each switch (from the rate) |
| `WCODE` + the level's W tables | 112 | 5.0 ms (measured) |
| `MCODE` | 113 | 2.5 ms (measured) |
| `P2DW` | 107: 31 pages from `$6000` | 2.0 ms (measured) |
| `MENUW` | 108: 52 pages | 3.3 ms |
| `AMAPW` | 94: 34 pages | 2.1 ms |
| `WIW` | 95: 26 pages | 1.6 ms |
| `FINW` | 96: 28 pages | 1.8 ms |
| `PALW` | 97: 10 pages | 0.6 ms |
| `OVLW` | 93: 24 pages from `$6800` | 1.5 ms |
| `LCODE` (the load) | 98: 48 pages | 3.0 ms |
| `DLINIT` | 1: 2 pages from `$6600` | 0.1 ms (boot and quit only) |

"From the rate": `far_pload` copies 63 µs a page on a2vm's f121 profile
(P2DW's 31 pages in 1.96 ms). Since the copy engine (section 18) every one
is one memory-API request, about 46 µs and 9.8 µs a page on F1.2.2
(a2vm `f122-nod2`): `WCODE` 0.79 ms, `MCODE` 0.47, `P2DW` 0.36. The level load itself is milestone 9's: E1M1
216 ms on f121 (LEVELS.md, `--setup-timing`).

## 6. No stubs

Every routine the game calls is built: the play link's `gplace.inc` has no
routine with `_B = 0`; `dl.inc`'s `GTICKER` and `GTRESUME` call part
tic's `G_Ticker` (and refuse to assemble if it were not built); the
preparation's test builds (`STUB=stop`, `STUB=skip`, `dl_gstub.s`,
`DOOM-stop.hdv`, `DOOM-skip.hdv`) are gone. What still stops a run
loudly are upstream's own error paths and the guards: `I_Error`
(`GS_ERROR`), the `Z_*` zone calls (`GS_ZONE`: the native pools are
gthink.s's), the saved games' actions (`GS_SAVEGAME`: the menu never asks
for them, section 11), an action past `ga_worlddone` (`GS_ACTION`) and
`FCALL`'s `GS_UNBUILT` (none reachable). Each is a `BRK` that stops at
`pl_crash`.

## 7. The boot: one disk

`playdisk.py` writes a ProDOS volume `DOOM` (pldisk.py's writer):
`DOOM.SYSTEM` (milestone 11's `pl_boot.s`, unchanged but for the kernel in
`pl_ready`'s place), `CATALOG`, `CRCLIST`, `LC.BIN` (the card images: the
player, the effects' card part, `pl_vbl`, the kernel; milestone 8's math,
far layer, phase loader, replay), and the bank files: the level store
(`TEXELS.1`, `PATCHES.1`, `MAPS.1`, `TABLES.1`), `CODE.1` (`LCODE`, the
render images, the 2D images, `OVLW`), `CODE.2` (the tic image, its group
directory written into the core), `PLAY.1` (`DLBANK`, `DEMOB`,
`S2STATE`'s first values, `SPRBOUND`), `RTABLES.1`, `SONGS.1`, `SFX.1`,
`GFX.1`, `HUDTXT.1`. 4,029,952 bytes (speed wave 2).

`DOOM.SYSTEM` probes the card, loads every bank file into RamWorks and the
card images into the card, checks the CRCs, starts the mouse card's clock
and jumps to `pl_ready`: the kernel. Its first `K_TIC E_BOOT` runs
`b_boot` (ST_Init's state, `G_ReloadDefaults`, the renderer's statics, the
title's start) and the boot list: `DLINIT` (the PRIVATE copy of the
static tables and the menu loop; black palettes), `MENUW`'s `m_init`,
`WIW`'s `wi_init`, `FINW`'s `fin_init`, then the first frame. On a2vm the
title page shows about 6 s after the start of `DOOM.SYSTEM`.

## 8. Frame rate (a2vm, f121, measured)

**After speed wave 2 (2026-10-03; section 16, `docs/SPEED.md` 5).** Same
commands, card-equivalent; "before" is wave 1's disk with the benchmark's
timing (SHA-1 `90635ac1…`), rebuilt and measured again with the same a2vm:

| Scene | f121 before | f121 after | fastpath before | fastpath after | `K_TIC` after (f121) |
| --- | ---: | ---: | ---: | ---: | ---: |
| E1M1's start, standing still (15-25 s) | 88.4 ms, **11.32 FPS** | 80.3 ms, **12.45 FPS** | 84.7 ms, 11.81 FPS | 78.6 ms, 12.72 FPS | 19.0 ms (24.8 before) |
| demo3 on E1M7, gametics 1052-1796 | 272.1 ms, **3.67 FPS** | 247.2 ms, **4.04 FPS** | 244.6 ms, 4.09 FPS | 226.9 ms, 4.41 FPS | 168.4 ms (188.9 before) |
| OPTIONS, BENCHMARK (all of demo3) | FPS **3.294** | FPS **3.631** | FPS 3.717 | FPS 4.026 | |

The page's rows on a2vm f121: `TIC 201.1  3D 22.9` / `MASK 14.2  DRAW 31.9` / `REST 5.6  N 534` (before: 225.2, 23.2, 14.2, 35.7, 5.6).

**After speed wave 1 (2026-10-02; section 14, `docs/SPEED.md` 5).**
`python3 tools/native/playtime.py --scene still|demo3 [--profile
fastpath]` on `build/native/DOOM.hdv`, card-equivalent (the exact idle),
and the menu's BENCHMARK played whole from the menu:

| Scene | f121 before | f121 after | fastpath after | `K_TIC` after (f121) | Render after (`nr_frame` + `nm_masked` + `nm_bkload` + `nb_frame`, f121) |
| --- | ---: | ---: | ---: | ---: | ---: |
| E1M1's start, standing still (15-25 s) | 180.7 ms, **5.53 FPS**, 21.9 tics/s | 87.9 ms, **11.37 FPS**, 34.9 tics/s | 84.3 ms, 11.86 FPS | 24.4 ms (11.5 group loads a tic) | 52.2 ms |
| demo3 on E1M7, gametics 1052-1796 (186 frames of 4 tics) | 873.3 ms mean, **1.15 FPS**, max 1,656 | 271.6 ms mean, **3.68 FPS**, max 635 | 243.8 ms, 4.10 FPS | 188.4 ms (63.5 loads a tic) | 70.1 ms |
| OPTIONS, BENCHMARK: the whole of demo3, 534 frames | FPS **0.912** (*) | FPS **3.302** (5,659 realtics; 3.318 was read wrong, (*)) | FPS 3.732 (5,008 realtics) | | |

"Before" is the owner's build (`SPEED.md` 2), but the benchmark's: it
did not exist then, so its "before" is that build plus part bench alone
(a2vm f121 with the exact idle: 534 frames in 20,480 realtics; part bench read 0.900 with the old idle). (*) The benchmark's figures of the
integration (0.912, 3.318, fastpath 1.177 and 3.842) were read with
a2vm stopped as soon as `G_TimeDemoEnd` began writing `DL_BRT`; it writes
the high bytes first, so the low byte was still 0 (20,480 = `$5000`,
5,632 = `$1600`, 4,864 = `$1300`) and the FPS too high. The page's own
figures, read with the page up (`playtime.py --scene bench`, section 15),
are 3.302 on f121 and 3.732 on fastpath for that build; the "before"
column was not measured again (its realtics are 20,480 to 20,735: FPS
0.901 to 0.912). Standing still now runs at real time (35 tics a
second, 3.1 tics a frame); demo3 still runs 4 tics a frame, the same
frames as before.

**Before speed wave 1** (the rest of this section, kept as measured then;
the still row's 5.3 FPS and 190 ms were a2vm's idle artifact, `SPEED.md`
1: the exact figure is 5.53 FPS, 180.7 ms, with `K_TIC` 112.1 ms, the
render 57.1 ms, loads and `s2_frame` 11.5 ms).

Measured from runs with a snapshot of the step list at every kernel step
dispatch (`dl_kern.s`'s `run`, by PC), the cycles between dispatches
(133.33 MHz), and `P_Ticker`'s call and return in `G_Ticker` (G_Ticker +
`$109`, + `$10F`, with G_Ticker's group in its slot). The game's speed
follows upstream's rule: at most `MAXTICS` (4) tics a frame, so a frame
longer than 114 ms slows the game below 35 tics a second.

| Scene | Frames a second | Tics a second | Frame | `K_TIC` (tic image back, the brain, the tics) | of which `P_Ticker` | Render (`nr_frame`, `nm_masked`, `nb_frame`) | Loads (`WCODE`, `MCODE`, `P2DW`) and `s2_frame` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| E1M1's start, standing still (15-25 s) | **5.3** | 21.3 | 190 ms | 122.0 ms | 82.1 ms (20.2 ms a tic) | 56.8 ms | 11.8 ms |
| E1M1, the computer room's fight with two zombiemen (44-52 s of section 13's route) | **2.7** | 11.3 | 370 ms | 260.8 ms | 221.4 ms (53.4 ms a tic) | 95.7 ms | 13.7 ms |
| The title loop's demo3 on E1M7, with its fights (60-199 s) | **1.0** | 4.1 | about 1 s | | | | |
| (the preparation's, `P_Ticker` skipped, E1M1 still) | 10.0 | 35.0 | 96-103 ms | 33.6-40.6 ms | 0 | 51.9 ms | 10.6 ms |

**Where the tic time goes: code paging.** `gcall.s`'s `gr_load` (a group
into its slot, about 0.5 ms for 2 KB) runs **39 times a tic standing
still** and **79 times a tic in the fight**. The most loaded groups are 21
(`P_RunThinkers`, `P_MobjThinker`) and 19 (`P_SetMobjState`, the thing
links), which share a slot and evict each other for every thinker whose
state changes; then 10 (the psprites), 24 (`G_Ticker`), 11 and 29 (the
brain). So nearly all of the 20.2 ms a tic standing still is paging, not
game logic. This is milestone 10's placement (`tools/native/gplace.py`:
its groups, `AFFINITY`, `CORE_FIRST`), not the play glue's; the cure is a
placement that keeps the thinker loop's callees out of its slot (or
`P_SetMobjState` in the core), then measuring again. Not done today: the
owner asked for the rate measured, not optimised.

To measure again: `python3 tools/native/playtime.py --scene
still|walk|demo3 [--profile fastpath]` (part measure: every PC from the
play link's labels; the walk is not like for like across builds, its
input runs on model time).

## 9. The final assembly (2026-10-02)

What was done to the preparation's tree:

1. **Linked with part tic**: `make -f play.mk` builds `build/native/play`
   with all 29 parts of milestone 10's integrated waves; the stubs and
   their test builds are removed (section 6). `E_RESUME` re-enters
   `G_Ticker` at its action loop (`gt_loop`), as part tic's `g_tresume`.
2. **A renderer bug found in play and fixed** (`tools/native/playdisk.py`
   `static_sources`): DLINIT's PRIVATE copies of main `$0900-$0B93` took
   their bytes from the render link's `rcard.m08` only, but
   `xtoviewangle` (`XTVLO` `$09A9`, `XTVHI` `$0AF3`, 161 B each) is
   `rtables.py`'s, in `tables.img`, which milestone 8's runs load over the
   link's. On the game disk both were zero, so every column of a wall took
   the same texture column (horizontal stripes, no texture across a wall).
   The copies now overlay every main and aux 0 record of `tables.img`
   below the card, and refuse one outside the copied ranges. Test:
   `test_play_glue.StaticTables` (fails without the fix). After it, the
   first frame of a new game equals the reference's but for a few pixels
   of an animated sprite (`test_play_runs.Level`).
3. **Milestone 11's R4 and R5 applied in part flow** (request P1, done):
   `src/native/game/flow/gwi.s`'s `st_tick` calls `g_mrandom`, then jumps
   to `ST_TickerHook` with its value; `hu_tick` calls `HU_TickerHook`
   first. `src/native/ghook.s` (the lockstep and test builds) exports both
   as a plain `rts`, so those builds do what they did. In play the status
   bar's face animates and HUD messages time out after 140 tics
   (`test_play_runs.Level.test_pickup_and_message_timeout`).
4. **Tests renamed and rewritten** for the real build: `test_play_glue.py`
   (was `wip_`), `test_play_runs.py` (replaces `wip_test_play_runs.py`).
5. Left as the preparation built them (named, unchanged): `SPRBOUND` from
   the whole WAD (larger than upstream's for sprites a level set does not
   hold: less early rejection, never a missing sprite); the render images
   are milestone 8's test builds with `VCWRAP_UPSTREAM` (request P5:
   `validcount` wraps as upstream's after 65,535 increments; a frame and
   every trace each add one, so after a few hours of play a stale stamp
   can make a line or sector skipped for one walk, as on the IIgs); no
   `idrate`.

Requests still open for their owners (`play-requests.md`): P5, P6 (P2,
gplace's core budget counting `dl_hook.o`, was done by speed wave 1), and the new P7 (milestone 10's profiling build's
`PH_LOAD` phase breaks milestone 11's layout check, so a play build that
must regenerate `s2.inc` fails until it is settled).

## 10. Tests and commands

    python3 tools/native/playdisk.py                 # make -f play.mk, then DOOM.hdv
    python3 tools/native/playdisk.py --no-build --run SCRIPT --seconds S \
        [--keep build/tmp-play-x]                    # a2vm, bounded
    python3 -m unittest test_play_glue test_play_runs test_play_bench test_play_cardprof
                                                     # from tests/
    python3 tools/native/playtime.py --scene still|walk|demo3|bench [--profile fastpath]

A run's script is a2vm's input events (`tools/a2vm/README.md`) with
`@label` for the play link's labels (`pc @dl_halt shot halt`). A
one-character key is that character, so codes are written in hex: `0x09`
TAB, `0x08` left arrow, `0x0B` up arrow, `0x0A` down arrow.

| Test | Checks |
| --- | --- |
| `test_play_glue.Layout` | `playlayout.check()`; the groups' slots |
| `test_play_glue.Hooks` | `dl_hook.s` exports every `ghook.s` entry; every glue source says GPL-2 |
| `test_play_glue.StaticTables` | DLINIT's copies hold every main and aux 0 table milestone 8's runs load below the card (the `xtoviewangle` bug) |
| `test_play_glue.SprBound` | `SPRBOUND` by upstream's rule equals the reference's for the sprites its level sets hold |
| `test_play_runs.Boot` | the boot to the title page with its song; the title loop's demo3 on E1M7, played (tics, views, the player moving); ESC opens and closes the menu; QUIT GAME, Y ends at the halt on the text screen |
| `test_play_bench` | OPTIONS, BENCHMARK on a disk whose demo3 is cut after 120 tics: demo3 starts on E1M7 with timingdemo set, the result page shows FPS = 35000 × frames / realtics as the host computes it, a key closes it and the title loop goes on; ESC while it runs stops it with no result |
| `test_play_cardprof` | the benchmark's phase rows (section 15) on the same disk: the five sums against the same span's kernel steps in a2vm's PC log, each within the reads' cost; their total against the realtics; the rows' text as the host formats the sums, drawn on the page; ESC stops the timing and puts nat_replay's entry back |
| `test_playtime` | `playtime.py`'s reading of the PC log (synthetic logs); the exact idle against no idle on the title loop (the same frames) |
| `test_a2vm_pclog` | a2vm's idle conditions `byte=` and `eq=lc.`, `--pclog`, `--stop-word` |
| `test_play_runs.Level` | a new game: E1M1 at skill 2, the first frame's view equal to ref816's `calls-newgame/still-00s.png`; the up arrow, the left arrow and A give forwardmove 25, angleturn 640, sidemove -24 and move, turn and strafe the player; the health bonus picked up (health 101) with its HUD message on, then off after 140 tics; TAB opens the automap, TAB again the overlay |

The 14 tests take about 90 s of host time; each a2vm run is bounded
(`bounded.run`) in a directory under `build/` deleted after it.

The whole suite after the assembly (`python3 tools/testpar.py --jobs 4`,
2026-10-02): 122 modules, 2,052 tests, 0 failures, 0 errors, 26 skipped
(milestone 10's parts' own skips). After speed wave 1's integration (`python3
tools/testpar.py`, 9 jobs, 48 minutes): 127 modules, 2,088 tests, 3
failures, each a check that assumed the old speed or layout (`SPEED.md`
5, "Integration"); after the fixes those three modules pass alone.

## 11. Differences from upstream (named)

- Save and load: the slots say "NOT IN / THIS / VERSION"; saving answers
  through `m_savedone` with C set (`k_sdfail`).
- `SPRBOUND` from the whole WAD (section 9 item 5).
- No idrate.
- The quit ends on a text screen ("DOOM HAS ENDED. TURN THE COMPUTER OFF.")
  after the sounds stop.
- No gray boot title (`titleWipe`): SCREENS.md X3.
- `validcount` wraps as upstream's (section 9 item 5).
- `idclev` is upstream's IIgs version: it ends the level (`G_ExitLevel`,
  `m_cheat65.s:246-247`) and takes no map number.

## 12. For the owner: playing DOOM.hdv on the card

### 12.1 The disk and the machine

1. Build it (or take the one built on 2026-10-02):
   `python3 tools/native/playdisk.py` writes `build/native/DOOM.hdv`,
   4,027,904 bytes (speed wave 1), a ProDOS volume `DOOM` whose first file is
   `DOOM.SYSTEM`.
2. Copy `DOOM.hdv` to the Appletini's SD volume, as for `MUSIC.hdv` and
   the replay disks (the card in a computer, or the menu's USB or FTP SD
   sharing).
3. The machine: the //e (PAL or NTSC) with 8 MB of RamWorks, the
   Appletini in TURBO mode, the mouse card in slot 2, the Phasor in slot 4
   in native mode (not "Mockingboard only"), and the Doom profile of
   `tools/sound/README.md` ("The Doom configuration profile":
   `vtw.slowdown.cycles=32`, `phasor.slot4.enabled=ON`,
   `phasor.mockingboard.only=OFF`, `slot2.card=MOUSE`,
   `vtw.turbo.enabled=ON`) loaded. For speed, add
   `vtw.disk2.acceleration.disabled=on` (only `on` reads as true; the
   menu shows "DISK II ACCELERATION DISABLED"): with the virtual Disk II
   active, every TURBO cycle is replayed to it and the CPU runs at about
   67 MHz instead of 110 (`docs/SPEED.md` 5, `docs/results/calib.md`).
   The card's figures since 2026-10-03 are firmware F1.2.2 with this key.

   **The memory API is optional** (since 2026-10-03, section 19). With it
   (the Appletini's slot 7, F1.1.4 or later; F1.2.2 for its copy engine)
   every bulk copy goes by the API, exactly as before. Without it
   `DOOM.SYSTEM` says `NO MEMORY API: COPIES BY THE CPU $FF` on the
   loading screen's fourth row and goes on: the CPU makes the same copies,
   byte for byte, at the same points, and the game plays the same, only
   slower (section 19 has the figures). **The mouse card is optional
   too** (since 2026-10-03, section 20), and since 2026-10-04 (section
   21) **a standard AppleMouse II in slot 2 is enough for the clock and
   the mouse**: its VBL interrupt is the game's clock and its X and
   button turn and fire, through its own firmware; with no mouse card at
   all the clock is the Phasor's timer and the game is played from the
   keyboard. So the game runs on an emulator, which needs:

   - an enhanced //e (65C02) with 8 MB of RamWorks: 127 banks of 64 KB,
     bank 0 the base aux 64 KB and banks 1-126 at `$C073` (the boot
     writes each bank's number at its `$0200` and reads them back; a
     missing bank stops it, "8 MB OF RAMWORKS NEEDED"), and the //e's
     language card;
   - Super Hi-Res on the //e: `NEWVIDEO` (`$C029`) bit 7 shows aux bank
     0's `$2000-$9FFF` (the pixels, the SCBs at `$9D00`, the 16 palettes
     at `$9E00`) as a IIgs shows bank `$E1` (a VidHD-style card), always
     bank 0's whatever `$C073` selects (the game pages other banks in
     while the picture shows);
   - a Phasor in slot 4, in native mode, for the music and the effects
     (without native mode, or with a Mockingboard, the game says so and
     plays silent; with nothing in slot 4 too). Its two 6522s must be
     real ones at the //e's bus clock: register 15 (ORA without
     handshake) writes port A as register 1 does (every AY write goes
     through it); timer 1 of the first VIA (`$C414-$C417`) counts the bus
     cycles, which tells PAL from NTSC with an AppleMouse; and timer 1 of
     the second VIA (`$C484-$C487`, ACR `$C48B`, IFR `$C48D`, IER `$C48E`)
     counts them in free-run mode and interrupts at each time-out: with
     no mouse card at all it is the game's clock;
   - slot 2: the Appletini's mouse card, a standard AppleMouse II (as
     GSSquared's "mouse" card and AppleWin emulate it, with Apple's ROM
     342-0270), or nothing. `DOOM.SYSTEM` reads the AppleMouse ID bytes
     (`$C205` `$38`, `$C207` `$18`, `$C20B` `$01`, `$C20C` `$20`) and then
     the Appletini's own (`$C200-$C201` `LDX #2`, `$C20D-$C20F` `STA
     $C0AC`). With all of them it uses your card as before. With the ID
     bytes alone it is an AppleMouse II: the boot calls its firmware
     (INITMOUSE, POSMOUSE, then SETMOUSE `$09`: the mouse on, its VBL
     interrupt on), says `APPLEMOUSE VBL CLOCK, PAL` (or `NTSC`) on the
     loading screen's sixth row, and from then on each VBL interrupt
     calls SERVEMOUSE, READMOUSE and POSMOUSE: the clock, the turn (the
     mouse's X) and the fire (its button), as on your card. PAL or NTSC
     comes from one VBL counted by the first VIA's timer 1 when slot 4
     has a 6522 (a Phasor or a Mockingboard); with none it is NTSC with
     a `?` after it (on a PAL machine the game then runs 17% slow).
     With no mouse card the boot says `NO APPLETINI MOUSE: PHASOR CLOCK,
     PAL` (or `NTSC`) instead, reads no mouse (the keyboard and the
     Apple keys only), and takes its clock from VIA-B's timer 1 at a
     frame's period (20,280 bus cycles PAL, 17,030 NTSC, as
     `MUSIC.SYSTEM` in `music/doom` does). With no mouse card and no
     VIA-B timer it stops: `NO CLOCK: NO MOUSE CARD OR PHASOR`;
   - the vertical blanking at the real video rate: the AppleMouse's VBL
     interrupt (50 or 60 a second), or with no mouse card `$C019`
     (RDVBLBAR, bit 7 low in the blanking), whose two frames the boot
     times against VIA-B's timer to choose PAL or NTSC (both within 512
     cycles of 20,280 or of 17,030 and within 256 of each other); a
     machine where it never changes, or changes at another rate, gets
     NTSC and a `?` after it on that row. The timers and the blanking
     must run at the real machine's rate (about 1.02 MHz and 50 or 60
     Hz) even when the emulator runs the CPU faster: the game's tics (35
     a second) and the music's tempo come from them;
   - a ProDOS block device that boots `DOOM.hdv` (4 MB);
   - nothing in slot 7, or any card: the probe writes nothing there
     unless the slot's ROM and its FIFO read as the Appletini's (a card
     that reads so but does not answer holds the boot about half a
     second);
   - speed: the game runs its tics at 35 a second whatever the CPU (at
     most four tics a frame, upstream's rule), and the benchmark's frame
     takes the card about 154 ms with the API and 209 ms without it at
     its TURBO speed of about 110 MHz, some 17 and 23 million cycles: a
     1 MHz //e would show a frame every 20 s, so the emulator must run
     the CPU about a hundred times faster than a //e for the card's frame
     rate (with the bus's timer and video at their real rate, above).
4. Boot `DOOM.hdv` from the menu's file browser as the boot volume.
   `DOOM.SYSTEM` loads the 4 MB into RamWorks and the card, checks every
   CRC (milestone 11's boot, SCREENS.md), and starts
   the title loop: the title page with the intro music about 6 s after
   the start on a2vm, then after 30 s the demo (demo3, on E1M7), then the
   title again. Without native mode on the Phasor the game says it has no
   music and plays silent.

### 12.2 Playing

- **A new game**: any key on the title page opens the menu (or ESC);
  NEW GAME, the episode (Knee-Deep in the Dead), the skill; RETURN, RETURN
  takes "Hurt me plenty" on E1M1.
- **Run**: OPTIONS, CONTROLS, ALWAYS RUN (the //e cannot see Shift alone).
  MOUSE (on), MOUSE SPEED and KEY SETUP are on the same page; DISPLAY &
  SOUND has the gamma, the effects' and the music's volumes.
- **The automap**: TAB opens the full map, TAB again lays it over the
  view, TAB again closes it; `-` and `=` zoom.
- **Dying**: the view drops; USE restarts the level with a new player
  (pistol, 50 bullets), as upstream's single player.
- **Cheats** are upstream's IIgs set: `iddqd`, `idkfa`, `idfa`,
  `idspispopd`, `idchoppers`, `idbehold` + v, s, i, r, a, l, `idrocket`;
  `idclev` ends the level; `idend` goes to the episode's end.
- **Benchmark**: OPTIONS, BENCHMARK plays demo3 at the normal tic rate and
  shows FPS = 35000 × frames drawn / realtics; ESC stops it with no
  result. The whole demo takes about 3 minutes after wave 1 (on a2vm
  f121: 534 frames in 5,659 tics, FPS 3.302; 5,673 tics and 3.294 with
  the phase timing of section 15). Under the FPS, three rows show where
  each frame's time goes (section 15).

| Key | Does |
| --- | --- |
| Up, down arrows, `W` `S` | forward, back |
| Left, right arrows | turn |
| `A` `D`, `,` `.` | strafe |
| Open Apple, the mouse button | fire |
| `E`, `SPACE`, `RETURN`, Solid Apple | use: doors, switches, lifts (`RETURN` also selects in the menus) |
| the mouse, left and right | turn |
| `1`-`7` | weapons (`1` the fist, or the chainsaw) |
| `TAB`, `-`, `=` | the automap, zoom |
| `ESC` | the menu |

### 12.3 What is missing

- **Saving and loading**: the menu's LOAD GAME and SAVE GAME slots say
  "NOT IN / THIS / VERSION"; nothing is written.
- `idrate` (the frame counter) is not built.
- The episode is DOOM1.WAD's only one (the shareware); E1M2 is the last
  map these runs reached (section 13); the later maps load by milestone
  9's checks but have not been played here, nor the episode's end and its
  finale.

### 12.4 Known problems

1. **It is slow, less so since speed wave 1.** 11.4 frames a second
   standing at E1M1's start (was 5.5) and 3.7 in E1M7's demo (was 1.15),
   on a2vm f121 (sections 8 and 14). Because a frame runs at most 4 tics
   (upstream's rule), the game itself slows down when a frame takes
   longer than 114 ms: standing still now runs at real time (35 tics a
   second), the fights still below it (about 15 tics a second in demo3).
   Waves 2 and 3 of `docs/SPEED.md` come next.
2. **Never run on the card.** Everything here is from a2vm under the
   `f121` profile with scripted input. The card's first run may show
   timing or hardware differences a2vm does not model.
3. Turning with the mouse takes effect a frame or two later (the mouse is
   read once a frame), which feels laggy at these frame rates.
4. After hours of play `validcount` wraps as upstream's does (section 9
   item 5): a wall or sector may be skipped for one frame.
5. The four-tic cap and the slow frames make the demo on the title loop
   play at about a third of its speed (it stays in step: it is played by
   tics).

## 13. The scripted runs of 2026-10-02 (a2vm, f121)

Every run boots `DOOM.hdv` from the start of `DOOM.SYSTEM` with a2vm's MLI
trap, the memory API, the mouse card's VBL clock and the interrupt bounds,
and plays a script of a2vm input events (keys, held keys, the Apple keys,
mouse motion) at fixed model times. The machine is deterministic: the same
script gives the same game, tic for tic, so a route was driven step by
step (a scratch autopilot replayed the script from the boot, read the
player's place at the end of each step, and appended the next turn and
walk) and the finished script then replayed whole on the final disk: same
tics, places and health at every checkpoint. The scripts and logs stayed
in the session's scratch space; the runs' build directories were deleted.

| Run | Model time | What it showed |
| --- | ---: | --- |
| Boot and title | 0-8 s | `DOOM.SYSTEM` loads, every CRC; the title page about 6 s in; the intro song on chips 0-2 |
| Title loop | 0-200 s | the title page 30 s, then demo3 on E1M7: the demo's player moves, fights, kills 7 monsters, loses health (the run ends inside the demo) |
| Menus | 7-16 s | ESC opens the main menu; the arrows move the skull over NEW GAME, OPTIONS, LOAD GAME, SAVE GAME, QUIT GAME; OPTIONS (MESSAGES, DISPLAY & SOUND, CONTROLS, BENCHMARK, SAVE SETTINGS), CONTROLS (ALWAYS RUN, MOUSE, MOUSE SPEED, MOUSE MOVE, KEY SETUP), DISPLAY & SOUND (VIEW, GAMMA, SFX VOLUME, MUSIC VOLUME); ESC goes back |
| New game | 8-20 s | RETURN, RETURN: E1M1 at "Hurt me plenty"; the first frame equal to ref816's; the up arrow walks (forwardmove 25), the left arrow turns (640), `A` and `D` strafe (sidemove ∓24), the mouse turns exactly (546 counts, 90°) |
| Run | 12-30 s | CONTROLS, ALWAYS RUN on in a level ("IN A HURRY, MARINE?"); the down arrow then gives forwardmove -50 |
| Automap | 12-17 s | TAB: the full map (the lines seen so far, "E1M1: HANGAR"); TAB: the overlay; `-` zooms out |
| Pickup and HUD | 11-25 s | the health bonus north-east of the start: health 101, "PICKED UP A HEALTH BONUS." on the HUD, gone 140 tics later |
| E1M1 to the exit | 0-169 s | the start room, the corridor, **the door** (USE against it: line 151 opens; USE from 1.6 units past the 64-unit reach rightly does not), the computer room: **two zombiemen fight back** (health 100 → 76), one killed with the pistol; the zigzag room's zombieman killed; over line 195 (E1M1's walk-over lift trigger); **the nukage** (health down 5 at a time), shells picked up, the door at y -4016, the exit hall's imp killed (health 57 → 36), the door at y -4632, **the exit switch** (line 330: the level ends) |
| Intermission, E1M2 | 169-186 s | the tally (kills 83%, items 8%, secret 0%, time 0:57, par 0:30); USE twice: E1M2 loads, the player's health 36, armor 2, 34 bullets and 4 shells carried over |
| Death and reborn | 46-174 s | standing in E1M1's computer room under fire: health to 0, the view drops; USE: E1M1 again from its start with 100 health and the pistol |
| E1M2's lift and the shotgun | 0-83 s | `idclev` (upstream's IIgs: ends the level), the intermission, E1M2; up the steps, over line 289 (lift 109 lowers from 192 to 64, waits, rises), onto it, **the ride** (the player's z from 105 to 233 as it rises), onto the platform: **the shotgun** ("YOU GOT THE SHOTGUN!", 8 shells, the weapon raised); `2` the pistol, `3` the shotgun |
| Sound effects | 8-19 s | the pistol's shots: chip 3's writes (none before, 12-26 a second while firing), E1M1's song on chips 0-2 throughout |
| Quit | 7-12 s | QUIT GAME, Y: "DOOM HAS ENDED. TURN THE COMPUTER OFF." on the text screen, the run ends at the kernel's halt |
| Long run 1 | 0-650 s | E1M1's route, then 460 s of scripted play on E1M2 (walking, turning, firing, using, strafing, weapon keys, the automap's three states, the menu): two deaths and reborns, the green armor picked up, the fist, no stop (`GS_STATUS` 0 throughout, the run ending on its cycle bound); 6,545 tics (3 min 7 s of game time) |
| **Long run 2** | 0-2,760 s | E1M1's route, then 2,560 s of scripted play on E1M2 as in run 1: **24,435 tics, 11 min 38 s of game time**, 46 minutes of machine time, at least 6 deaths and reborns, armor and ammo picked up, kills; no stop (`GS_STATUS` 0 at all 46 snapshots, the run ending on its cycle bound); 1.0-3.5 frames a second and 4-14 tics a second by minute on E1M2 |

## 14. What changed in speed wave 1 (2026-10-02)

For the owner, after "the benchmark … is indeed too slow and needs a
speed optimization". Nothing the game shows or does changed: the frames
and the demo's sync stay bit-exact against ref816 (checked below). Only
the time changed. `docs/SPEED.md` has the plan and the measurements;
`docs/speed-parts/*.md` each part's details.

**What you will notice**

- **BENCHMARK works.** OPTIONS, BENCHMARK closes the menu, plays demo3
  at the normal tic rate and, at the demo's end (about 3 minutes now),
  shows the BENCHMARK page with the view size and FPS = 35000 × frames /
  realtics, as upstream's does. ESC while it runs stops it with no
  result. Read this figure on the card after each wave.
- **About twice as fast standing still and three times as fast in
  fights** (a2vm f121, card-equivalent):

  | | Before | After |
  | --- | ---: | ---: |
  | E1M1's start, standing still | 5.53 FPS (180.7 ms) | **11.37 FPS** (87.9 ms), real-time tics |
  | demo3 on E1M7, gametics 1052-1796 | 1.15 FPS (873 ms) | **3.68 FPS** (272 ms) |
  | The menu's BENCHMARK (all of demo3) | 0.912 (*) | **3.302** (3.318 as first read, (*)) |
  | (fastpath, for reference: still / demo3 / BENCHMARK) | 6.48 / 1.46 / 1.177 (*) | 11.86 / 4.10 / 3.732 (3.842 as first read) |

  (*) Read with the realtics' low byte not yet written (section 8).

**What was changed**

1. **The tic code is placed by the machine's real cost** (part place).
   `gplace.py` now charges what a group load costs (its pages × 63.8 µs,
   plus 5 µs a cross-group call), trained on recorded calls of still,
   walk and demo3. Group loads a tic: 38.8 → 11.5 standing still, 241 →
   63.5 in demo3.
2. **A group loads in one window** (part paging): `gr_load` copies a
   whole group through the kernel's new `far_gcopy` (card `$FFD5`) in one
   `RAMRD` window, 64 µs a page instead of 100. And the **lazy restore**:
   on return a group is reloaded only when an active caller needs it.
3. **The bucket pass and the record flush are faster** (part bucket):
   each column's byte count comes from the record producers (walk 1
   gone), the chunk copy is a patched zero-page loop, walk 2 and the
   flush are tighter loops. Render −4.8 ms standing still, −13 ms in the
   heaviest frame.
4. **Exact timing on a2vm** (part measure): the emulator now skips the
   two tic waits only when the card would really wait there (the old
   skip made still read 190.6 ms instead of 180.7), and
   `tools/native/playtime.py` measures any build.
5. **The benchmark** (part bench): `REQ_BENCH`, the timed demo and its
   result page.

**How it was checked** (the owner's rule: only what changed): lockstep
demo3 against ref816 (2,134 tics, 0 failures; the game code, its
placement and the paging), `frame8.py` on 23 frames from one fill (the
ten heaviest, every 50th of demo3, still and the median: all equal; the
renderer), the benchmark's scripted runs (`test_play_bench`, and the
whole benchmark from the menu above), then the fast full suite once
(`python3 tools/testpar.py`: 127 modules, 2,088 tests, 3 failures on the first run (each a check that assumed the old speed or layout; fixed, and the three modules then passed alone: `SPEED.md` 5, "Integration")).

**The disk**: `build/native/DOOM.hdv`, 4,027,904 bytes, SHA-1 `5fa5a03f80a15c98214129a46f19e4ea3f867632`.

## 15. The benchmark's phase rows (2026-10-02)

For the owner, after "Benchmark is actually the exact same at 2.897.
That's what it was before, not 2.93. And I'm on a PAL machine at 50Hz".
The card shows 2.897; a2vm f121 shows 3.302 for the same build (section
8: the 3.318 written before was misread), so a2vm runs this benchmark 14%
faster than the card. To find in which part of the frame, the BENCHMARK
page now times the frame's phases on the machine itself and shows them in
the three rows under FPS, upstream's CPU, CACHE and ROM rows, which
milestone 11 left black (SCREENS.md X2). On a2vm f121, this disk:

    BENCHMARK: DEMO3
    VIEW                     FULL
    FPS:                    3.294
    TIC 225.2  3D 23.2
    MASK 14.2  DRAW 35.7
    REST 5.6  N 534

**How to read the rows.** Each figure is one phase's mean time a frame,
in ms with one decimal, over the whole benchmark; N is the frames drawn
(the FPS's frames). The five phases are the whole frame: their sum is
about 1000 / FPS (on a2vm 304.0 ms against 1000 / 3.294 = 303.6: the rows
start at the end of demo3's load, the realtics a few ms later).

| Row | The phase | What runs in it (section 2's steps) | a2vm f121, ms |
| --- | --- | --- | ---: |
| TIC | the tic phase | `K_TIC`: the tic image and its planes back into W, the brain, the frame's 4 tics (the game code, its group loads, the object API's far windows), the next step list, the caches written back | 225.2 |
| 3D | the front end | `K_WLOAD` (the front end's image and the level's W tables) and `nr_frame` (the BSP walk, walls, planes, the records) | 23.2 |
| MASK | the masked phase and the bucket pass | `K_MLOAD`, `nm_masked` (sprites, masked walls, the weapon), `nm_bkload`, and `nb_frame` but its replays (the bucket pass: the batches, the scatter, the fuzz marks) | 14.2 |
| DRAW | the replay | `nb_frame`'s calls of `nat_replay`: each batch drawn onto the screen, its SHR drain included | 35.7 |
| REST | the rest | `PALW` at the level's first frame, the `P2DW` load, `s2_frame` (palettes, status bar, HUD, the input poll) | 5.6 |

`OVF n` after N would mean the timing lost n turns of its timer that it
could not place in a phase; the rows would then be wrong. a2vm never
shows it.

**Comparing with a2vm.** The card's frame is 1000 / 2.897 = 345 ms
against a2vm's 303 to 304: about 41 ms more. Each row of the card's page
against the same row on a2vm (above, and `docs/SPEED.md` 5, "The
benchmark's rows") shows where those 41 ms are. TIC is mostly RamWorks
copies (the group loads: 64 µs a page on a2vm), `RAMRD` windows and
`$C073` writes; 3D and MASK mostly the CPU in W and the card; DRAW is
held by the SHR drain (a byte an Apple cycle); REST is small.

**How it is measured.** The timer is the Phasor's VIA-A timer 1: the
boot's PAL or NTSC detection (`pl_detect`, `pl_irq.s`) loads it with
`$FFFF`, and nothing uses it after (the music and the effects write only
the VIAs' ports, their directions and the interrupt enables). It counts
the Apple bus cycles down, free-running: 1,015,625 a second on PAL,
1,020,484 on NTSC, and the rows are converted with the rate of the
standard the boot detected. It is read low byte then high byte, both again
when the low byte was within 8 of its borrow, at each boundary:

- three steps the frame's list adds while the benchmark runs: `K_CALL`s
  of the kernel's `bt_mark` before `K_MLOAD`, after `nb_frame` and before
  `K_END`;
- around each batch's replay: the brain's `bt_start` writes `jmp
  bt_replay` over `nat_replay`'s first instruction (`sta gcol`, kept in
  DLM with a `jmp` back), and `bt_stop` puts it back;
- at the brain's end (`bt_close`, `dl_disp.s`): the end of the tic phase.

A short phase's interval is the difference of two readings (mod 65,536).
The timer turns every 65,536 cycles (64.5 ms) and the tic phase is
longer, so `bt_close` counts its turns from the VBL count kept with each
reading (20,280 cycles a VBL on PAL; exact while a phase lasts under 256
VBLs, 5.1 s), and checks the short phases' sums over the same span: the
turns an interval of 3 VBLs or more lost go back to its phase (the first
frame's REST, 85 ms with `PALW`, is one). The sums are 32-bit counts of
bus cycles in DLM (`BT_S`). The timing starts at the end of demo3's load
(`E_RESUME`) and stops in `G_TimeDemoEnd` (or at Escape); `bt_rows`
(`dl_cmd.s`) writes the rows into MENUW's state block (`M_BROWS`), and
MENUW's `m2_bench` draws them over the black rows.

**What it costs.** Each reading is 2 to 4 reads of slot 4, and each
slot-4 access holds the card at 1 MHz for the Doom profile's window
(`vtw.slowdown.cycles=32`): about 40 µs a boundary on a2vm f121, which
models that window, and 6 to 8 boundaries a frame (3 in the list, 2 a
replay batch, the brain's): about 0.25 ms a frame. The timing's code also
makes two glue groups longer by 3 and 2 pages (`DLG_DISP`, `DLG_CMD`,
each loaded about once a frame: about 0.3 ms). In all the frame is 0.8 ms
longer on a2vm f121 (0.26%): FPS 3.302 without the timing, 3.294 with it
(5,659 and 5,673 realtics). A reading's own time falls in the phases on
either side of it; the rows agree with the kernel steps of the same run
(`playtime.py --scene bench`) within 0.3 ms a frame:

| a2vm f121, ms a frame | TIC | 3D | MASK | DRAW | REST |
| --- | ---: | ---: | ---: | ---: | ---: |
| The page (the machine's timer, 534 frames) | 225.2 | 23.2 | 14.2 | 35.7 | 5.6 |
| `playtime.py`'s kernel steps, same run (533 whole frames) | 225.5 | 23.1 | 14.2 | 35.8 | 5.4 (+ 0.12 of the list's reads) |
| `playtime.py`, the build without the timing | 224.9 | 23.2 | 14.2 | 35.7 | 5.4 |

(The page's TIC also counts the tic phase that follows the load and the
last one, to `G_TimeDemoEnd`; `playtime.py` whole frames only.)

**Where the code is.** `bt_mark` in the kernel's menu-loop bytes of main
(`BT_MARK` `$08CA`, `BT_MARK2` `$0BE1`), its middle part `bt_ext` (36 B)
at `$0844`, in MEMORY_MAP.md 3.2's free bytes, which `bt_start` writes at
each benchmark's start; `bt_replay` in the kernel at `$FFC4` (its last
17 free bytes); `bt_start`, `bt_stop`, `bt_close` in `DLG_DISP`,
`bt_rows` in `DLG_CMD` (not the brain's group, which is loaded again
after each tic); `BT_*` in DLM (40 B: DLM 122 of 128 B). It is the play
build's only: the lockstep and test images of `game.mk` are byte for byte
as before (293 files compared), and MENUW draws the rows only when
`M_BROWS` is not empty (milestone 11's checks inject it empty: X2's rows
stay black there).

**Checked** (the owner's rule: the benchmark's scripted runs, then the
modules the change touches): `tests/test_play_cardprof.py` (about 30 s):
one run of the menu's benchmark on `test_play_bench`'s disk (demo3 cut
after 120 tics, 30 frames) with a2vm's PC log; each of the five sums
against the same span's kernel steps within the reads' cost (5.9 ms on
that run: 90 list marks and 30 replays, 39 µs a mark): TIC 3,368.9 /
3,369.3 ms, 3D 501.4 / 499.9, MASK 281.8 / 279.4, DRAW 899.0 / 900.2,
REST 247.7 / 246.6; their total against the realtics (within two tics);
the rows' text as the host formats the sums, the rows drawn on the page;
the FPS row as `test_play_bench` computes it; no overflow; `nat_replay`'s
entry back after the stop; Escape: the timing stopped, the entry back, no
rows. A planted bug, the MASK boundary after `K_MLOAD` instead of before
it, fails the test (3D 580.1 against 500.2 ms). `test_play_bench` passes
as before; `test_m11_s2menu2`'s frames and sizes on the new MENUW (X2
black with `M_BROWS` empty); `test_playtime` (playtime.py's replay split
and bench scene).

**Commands**: `python3 tools/native/playtime.py --scene bench [--profile
fastpath]`: the whole benchmark on a2vm with the PC log (about 2 minutes
of host time), with playtime's steps and phases, the page's FPS and rows
and the machine's sums.

**The disk**: `build/native/DOOM.hdv`, 4,029,440 bytes, SHA-1
`90635ac146d2fa2432cf73eb665dab263517109d`.

**Not done**: the card has not run it (the owner's test); NTSC is
converted by its rate but was not run on a2vm (it runs PAL).

## 16. What changed in speed wave 2 (2026-10-03)

For the owner, after the card's benchmark rows (`TIC 260  3D 26.1` /
`MASK 16.4  DRAW 37.7` / `REST 6.2  N 534  OVF 1`): the tic phase is three
quarters of the card's frame, so this wave works mostly there. Nothing the
game shows or does changed: the game's state and demo3's sync stay exact
against ref816, and every frame the renderer draws is byte for byte the
same (checked below). Only the time changed. `docs/SPEED.md` 4-5 has the
plan and the figures, `docs/speed-parts/*.md` each part's details.

**What you will notice** (a2vm f121, card-equivalent; `playtime.py`):

| | Before (wave 1, your disk `90635ac1`) | After wave 2 |
| --- | ---: | ---: |
| E1M1's start, standing still | 11.32 FPS (88.4 ms) | **12.45 FPS** (80.3 ms) |
| demo3 on E1M7, gametics 1052-1796 | 3.67 FPS (272 ms) | **4.04 FPS** (247 ms) |
| The menu's BENCHMARK | 3.294 | **3.631** |
| Its rows | TIC 225.2, 3D 23.2, MASK 14.2, DRAW 35.7, REST 5.6 | TIC 201.1, 3D 22.9, MASK 14.2, DRAW 31.9, REST 5.6 |
| (fastpath: still / demo3 / BENCHMARK) | 11.81 / 4.09 / 3.717 | 12.72 / 4.41 / 4.026 |

On your card, with the factors your rows showed (TIC and MASK about 1.155,
3D 1.125, DRAW 1.056), the benchmark should read about **3.18 FPS** (about
314 ms a frame: TIC about 232, DRAW about 34) against 2.897. That is an
estimate: your card's page gives the figure.

**What was changed**

1. **The object API's misses copy in one window** (part objapi): a mobj's
   four record groups, a line with its sectors, a sector's two records and
   a block list each come over in one `RAMRD` window (a small copy routine
   in page 1), not two to four; lookups start from the line last used. The
   caches keep their sizes (bigger ones would gain about 1.5 ms in memory
   that does not exist). demo3 −13.4 ms a frame.
2. **Smaller tic loads** (part ticloads): a group load copies only the
   group's bytes, not its last page's padding, in one window; the walk's
   planes come and go only below the highest mobj slot used, written back
   in one window; after the status bar's image the tic image's first six
   pages are already in place and are not loaded again. demo3 −6 ms,
   still −3.5 ms.
3. **The HUD's ticker stays resident** (part glue): it runs from the tic
   core instead of loading its 8-page group every tic. −1.3 to −1.7 ms.
4. **The replay copies fewer texels** (part replay): a texture span that
   wraps past texel 127 copies its two used runs, not all 128. DRAW −3.8 ms
   in the benchmark; the heaviest frames −8 to −26 ms.
5. **The front end** (part frontend): its image loads from page `$65`
   (the tic image left the first five pages identical), the BSP walk
   remembers each node's box corner angles while the view stands still,
   and the weapon's clip pass is reused while the weapon is off screen.
   −2.4 ms standing still.

**How it was checked** (the owner's rule: only what changed, once each):
the lockstep demo3 run against ref816 (`ticrun.py --run demo3 --frames
front --fills a5`: 2,134 tics, 0 failures; the game code, the placement
and the paging), `frame8.py` on 23 frames from one fill (demo3-036, the
ten heaviest, every 50th demo3 frame, still-1 and still-2: all 23 equal,
24,381 records; the renderer), the benchmark played whole from the menu on
f121 and fastpath (the kernel), then the fast full suite
(`python3 tools/testpar.py`; its first run found four harness checks that
did not know a part's change and one defect of the integration in the
test driver, each fixed: `docs/SPEED.md` 5, "Integration of wave 2").

**The disk**: `build/native/DOOM.hdv`, 4,029,952 bytes, SHA-1
`f92c81aeaf03fd9436e33fec5c6aa125ea105893`.

**Not done** (each part's note says why and what it would take): the
status bar's ticker in the core (no room), the brain's tic loop in the
core, the object API's 2-byte blockmap reads and stamp-only line
write-backs (outside that part's files), the replay's stage plan in the
bucket pass (no spare record byte), the patched copy loops (no gain on
F1.2.1), the planes' dirty flag (measured slower).

## 17. What changed: the frame slots (2026-10-03)

For the owner, after the card's wave-2 benchmark (`TIC 250.4  3D 25.8` /
`MASK 16.3  DRAW 33.2` / `REST 6.3`, 3.015 FPS): the tic phase spent about
half its time copying code into W's two 2 KB slots, because W has no room
for the code a fight runs. Main `$2000-$5FFF` holds the colormaps, which
only the drawing (the replay) reads; now, while the tics run, 12 groups of
game code live there, each in a place of its own, copied in by the memory
API the first time a frame needs them, and the colormaps are copied back
before anything draws. Nothing the game shows or does changed: demo3's sync
stays exact against ref816 and every replay finds its colormaps (checked
below). `docs/SPEED.md` 9 has the details.

**What you will notice** (a2vm f121, the model corrected by your card's
CALIB figures, which matched your wave-2 benchmark within 0.4%):

| | Before (wave 2, your disk `f92c81ae`) | After the frame slots |
| --- | ---: | ---: |
| E1M1's start, standing still | 10.40 FPS (96.2 ms) | **11.02 FPS** (90.8 ms) |
| demo3 on E1M7, gametics 1052-1796 | 3.37 FPS (297.0 ms) | **4.91 FPS** (203.7 ms) |
| The menu's BENCHMARK | 3.004 (your card: 3.015) | **4.641** |
| Its rows | TIC 251.7, 3D 25.8, MASK 16.3, DRAW 33.2, REST 6.2 | TIC 134.0, 3D 25.8, MASK 16.3, DRAW 33.4, REST 6.2 |

Your card should show about **4.6 FPS** with `TIC` about 134, if the memory
API's copies into main cost on the card what a2vm models (83 µs a 256-byte
page; the benchmark makes about 15 such copies a frame, 89 pages, 7.4 ms).
That cost has not been measured on the card yet: if it is slower, `TIC`
shows it.

**What was changed**

1. **Frame slots**: the placement pins 12 groups (P_RunThinkers and
   P_SetMobjState with G_Ticker and the sector thinkers, the position check
   with its block walk, A_Chase with its moves, A_Look and the attacks'
   range checks, the line opening and the puffs, the unlinking, the
   thrust and friction of P_XYMovement, and more) to their own places in
   main `$2000-$5FFF` (64 pages). The first call in a frame copies one in
   (one PRIVATE request, at most 2 KB); the brain's last step copies the
   colormap bytes back from the level's copy in RamWorks.
2. **The core made room for it**: the level's specials (`gspec.s`, only
   the load runs them) left the tic image, and the load's continuation
   (`g_resume`) moved to the brain's group.
3. **The placement** was searched again with the frame slots and the
   card's copy cost (80 µs a page into W, 85 µs a page by PRIVATE).

**How it was checked** (the owner's rule: only what changed, once each):
the lockstep demo3 run against ref816 (`ticrun.py --run demo3 --frames
front --fills a5`: 2,134 tics, 0 failures; the game code, the placement
and the paging); the menu's BENCHMARK played from the menu
(`test_play_bench`), now with a snapshot at every replay that must find
the colormaps exactly as the level loaded them (43 replays, all equal; a
planted bug that skips the copy-back once is caught); the disk builder's
new check that no tic code stores into `$2000-$5FFF`; then the fast full
suite (`python3 tools/testpar.py`).

**The disk**: `build/native/DOOM.hdv`, 4,029,952 bytes, SHA-1
`2b0fa3a6df5526364f7d27a9d039852e84bb8a26`.

## 18. What changed: the copy engine (2026-10-03)

For the owner, after the frame slots' benchmark on your card (5.648 FPS,
`TIC 105.4`, F1.2.2, the Disk II's acceleration off): F1.2.2 copies with
the memory API on the FPGA's copy engine, about 46 µs a request and 0.038
µs a byte, six times faster a byte than the CPU's copy. Every big copy of
a frame now goes that way: each group of game code loaded into W's two
slots (about 40 a frame in the benchmark), the tic image's core and the
walk's planes, the planes back, and the images of the 3D view, the
sprites and the status bar. Nothing the game shows or does changed (the
checks below). `docs/SPEED.md` 10 has the details.

**What you will notice** (a2vm `f122-nod2`, which matched your card's
frame-slot benchmark within 0.03 FPS):

| | Before (your disk `2b0fa3a6`) | After |
| --- | ---: | ---: |
| The menu's BENCHMARK | 5.677 (your card: 5.648) | **6.519** |
| Its rows | TIC 104.5, 3D 21.8, MASK 13.8, DRAW 31.4, REST 4.9 | TIC 89.4, 3D 18.0, MASK 11.6, DRAW 31.3, REST 3.3 |
| E1M1's start, standing still | 13.75 FPS (72.7 ms) | **16.97 FPS** (58.9 ms) |
| demo3 on E1M7, gametics 1052-1796 | 6.01 FPS (166.5 ms) | **6.96 FPS** (143.7 ms) |

Your card should show about **6.5 FPS** with `TIC` about 89.

**What was changed**

1. **The transport moved to the card**: the code that sends a request to
   the memory API and waits for it (`gcall.s`'s `AMEMLC`, 164 B in the
   main card's bank 1 after the multiply tables) now serves every
   request, because a load that replaces the whole of W would overwrite
   code waiting in W.
2. **Group loads**: `gr_load` loads a group into a W slot by one request,
   as it already did for a frame slot; the frame slots' colormap bytes go
   back in one request a frame instead of one a slot.
3. **The kernel's loads**: `K_TIC`'s core and planes and every `K_LOAD`
   are one request each, a descriptor a run; the 3D view's and the
   sprites' images are `K_LOAD`s now (the steps `K_WLOAD` and `K_MLOAD`
   left the kernel); the planes go back to RamWorks by one request.
4. **The placement** was searched again with these prices (a2vm's F1.2.2
   model): `tools/native/gplace-f122.json`, 11 frame slots.
5. Kept as they were: the copies that draw the screen (they must be
   seen), the masked phase's two small copies (0.3 ms a frame, in the
   renderer's build), and the many copies under 256 B.

**How it was checked** (the owner's rule: only what changed, once each):
the lockstep demo3 run against ref816 (2,134 tics, 0 failures: the group
loads and the placement); the menu's BENCHMARK (`test_play_bench`), with
a new check that at every call of the 3D view, the sprites and the status
bar W holds their image exactly as its RamWorks bank does (129 loads) and
the colormaps right at every replay (43); a planted bug in each (a load a
page short, a group without its last bytes), both caught; then the fast
full suite (`python3 tools/testpar.py --jobs 5`).

**The disk**: `build/native/DOOM.hdv`, 4,029,952 bytes, SHA-1
`fd3ce9fd7e44c4e642dcd76101870609d2f01382`.

## 19. What changed: the memory API optional (2026-10-03)

For the owner, who asked "Can you make the memory API optional? so that
emulators can run the game?": the game no longer needs the Appletini's
memory API. With it nothing changed: your card runs the same code, makes
the same requests at the same points, and the benchmark reads the same
(a2vm `f122-nod2`: 6.519 FPS, 551 frames, 2,958 realtics, `TIC 89.4`,
as before; the boot reaches its ready state at the same cycle). Without
it (an emulator, or a card whose firmware has none) `DOOM.SYSTEM` puts
`NO MEMORY API: COPIES BY THE CPU $FF` on the loading screen's fourth row
and goes on, and the CPU makes every copy the API made, byte for byte, at
the same point: the game plays exactly the same, only slower. Section
12.1 lists what an emulator needs.

**What you will notice** (a2vm `f122-nod2`, your card's setting;
`playtime.py --scene bench`, with `--no-amem` for the second column):

| | With the API | Without the API |
| --- | ---: | ---: |
| The menu's BENCHMARK | **6.519 FPS** (551 frames, 2,958 realtics) | **4.794 FPS** (534 frames, 3,898 realtics) |
| Its rows | TIC 89.4, 3D 18.0, MASK 11.6, DRAW 31.3, REST 3.3 | TIC 136.8, 3D 22.0, MASK 13.8, DRAW 31.4, REST 5.0 |
| ms a frame (mean) | 153.6 | 208.9 |
| The copies, ms a frame | 7.65 (the copy engine) | 59.75 (the CPU) |

Without the API the CPU's copies cost 52 ms more a frame: the groups into
W's slots 17.3 ms (3.9 with the API), the frame slots' loads and restores
29.4 ms (1.3: in main `$2000-$5FFF` every CPU store is a video write, about
1 µs a byte on the card, `MEMORY_MAP.md` rule 3), `K_TIC`'s core and
planes 3.6 ms, the images of the 3D view, the sprites and the status bar
8.8 ms. On the card without an API the game would show about 4.8 FPS; an
emulator's speed depends on how fast it runs the 65C02.

**What was changed**

1. **The probe** (`pl_boot.s` `probe_amem`, at its old place in
   `DOOM.SYSTEM` and in its old room of 215 bytes, so that every other
   routine of the boot keeps its address; the message and the patcher in
   a new segment `PLAMEM` after the boot's): it writes nothing into slot
   7 until the slot reads as the Appletini's, twice over (an empty slot
   reads the floating bus):
   the SmartPort ID bytes `$C701`, `$C703`, `$C705`, `$C707` (`$20`,
   `$00`, `$03`, `$00`; a Disk II's `$C707` is `$3C`), the ProDOS entry's
   offset `$C7FF` (`$0A`, the SmartPort entry `$C70D` of
   `README_MEMORY_API.md`; appletini-one's slot ROM image
   `smartport_a2retronet_style_c700.mem` has both), then its FIFO's
   control register `$CFF1` (bits 0-5 `$20`, the vTW bit and no reply
   pending). Only then does the STATUS request go into the FIFO, as
   before; its reply is waited for 4 × 64 K turns (about 0.5 s; the old
   probe waited 256 × 64 K, some 33 s, which a card whose ROM reads as
   the Appletini's but which does not answer would hold the boot for:
   four times the wait `am_fin` gives every CONTROL in the game). A
   refusal, an error, no reply, a capability or the available
   bit missing: the CPU's copies (the answer after the message: `$FF` not
   an Appletini ROM, `$FE` a capability missing or unavailable, `$6F` no
   reply, else the API's error). The boot no longer stops for it
   (`PL_NOAMEM` is no longer used).
2. **The CPU's version, written at the boot when there is no API**
   (`am_patch`, after the install, from `bt_init`, which then goes on to
   `pl_init`; the table `bt_patch`, 640 B in
   `DOOM.SYSTEM`, 462 used, built by `tools/native/amcpu.py` and written
   by `playdisk.py`), so that the API's path has no test to make:
   - over the card's transport (`gcall.s` segment `AMEMCPU` over
     `AMEMLC`, whose entries it keeps): `am_begin` returns, `am_push` does
     the template's descriptor (`cx_exec`, with interrupts enabled as the
     far layer's copies before the copy engine; `am_fin` puts the
     caller's flags back), `am_runs` is the far layer's `far_pload`. So
     `gr_load`, `fs_restore`, `planes_out` and the kernel's `K_TIC` and
     `K_LOAD` are unchanged. `cx_exec` sets RAMRD for the source's
     space, RAMWRT for the destination's and `$C073` to their bank, and
     copies or fills a part page at a time; from one RamWorks bank to
     another it switches `$C073` at each byte, as RAMRD and RAMWRT share
     it. Its pages loop and its inner loops (`AMEMCPUD`, `AMEMCPUF`) go
     into two ranges of the card that no link uses (`$DFE6-$DFFF`,
     `$FE45-$FE7A`), which `playdisk.py` checks at every build;
   - over each W image's own transport, which no code reaches without the
     API: a 53-byte walker of its request through `cx_exec` (the load
     image's `am_send`, DLINIT's static tables, the menu's screen save,
     the busy sign's save).
3. **The checks' tools**: `ticrun.py --no-amem` runs the lockstep build on
   a2vm without the API, its image patched as `DOOM.SYSTEM` patches the
   disk (`grun.Image.cpu_copies`); `playdisk.py --run` and `playtime.py`
   take `--no-amem`; `pldisk.py`'s boot checks `noamem` and the new
   `amemoff` (the Appletini ROM with the API unavailable) expect the
   ready state and the message instead of the stop.

**How it was checked** (the owner's rule: what changed, once each):

- the lockstep demo3 run against ref816, with the API (`python3
  tools/native/ticrun.py --run demo3 --frames front --fills a5 --jobs 2`)
  and without it (the same with `--no-amem`: the groups into W's and the
  frame slots, the restores and the level load by the CPU): 2,134 tics
  compared, 0 failures, same-pair hits 1,009 = 1,009, in both;
- the BENCHMARK with the API (`python3 -m unittest test_play_bench`): the
  colormaps right at 43 replays, the images right at 129 loads, FPS
  6.458 on the short demo, as before;
- without the API, the new `tests/test_play_noamem.py`: one bounded run
  from the boot through the title, a new game (E1M1's load, the menu) and
  the BENCHMARK (E1M7's load) to its result page: the message, the card's
  CPU version, DLINIT's static tables equal to their sources, the
  colormaps right at 109 replays, W right at 327 K_CALLs, the core and
  the planes right at 146 K_TICs; FPS 5.675 on the short demo;
- `tests/test_amcpu.py`: the walker's bytes against ca65's, the table's
  format, and one request of sixteen descriptors of every kind (COPY
  between main, RamWorks banks, aux 0's screen; FILL; one byte to 8 KB,
  odd addresses, page crossings, each reading an earlier one's result)
  done by the CPU's version on a2vm: main and the banks byte for byte as
  the API's model leaves them, nothing else written, the far layer's
  zero page kept. A planted bug (the per-byte loop writing to the read
  bank) is caught by it and by the play run (the boot crashes in DLINIT);
- then the fast full suite (`python3 tools/testpar.py --jobs 6`).

**After the review** (three findings fixed, the checks above rerun once
each with the results given there and in the table):

- the boot with the API was 179.7 ms (9 VBLs) later than before: moving
  `probe_amem` out of `PLBOOT` had moved the CRC loop (`crc_page`
  `$253D` to `$2471`) into TURBO read-cache sets shared with its zero
  page variables, so `check_files` ran 4.5% slower in the model, the
  benchmark's scripted keys landed 6 gametics later and its page read
  6.522 instead of 6.519. `probe_amem` is back at its place in its old
  room (215 B, padded), its data at theirs, `am_patch`'s call moved into
  `bt_init` (the same `jsr` that called `pl_init`) and `s_noamem`'s 26
  bytes kept as room: `DOOM.SYSTEM` differs from `fd3ce9fd`'s only in the
  probe's room, that `jsr`'s target and the 26 bytes, and the boot with
  the API reaches `pl_ready` at 741,792,217 fabric clocks as before
  (765,753,813 in the reviewed build);
- a card whose ROM shows the six bytes but does not answer held the
  boot 33 s (a2vm, a ROM made for it: the title at 38.6 s); the wait is
  now 4 × 64 K turns (6.06 s against 5.56 s with slot 7 empty). Such a
  card still gets the one STATUS request: no read of a ROM tells a ROM
  made to match from the Appletini's;
- the per-byte switching of `$C073` also slows the menu's and the busy
  sign's saves (the open problems below say how much);
- the fast full suite (`python3 tools/testpar.py --jobs 6`): 133
  modules, 2,120 tests, 27 skipped, one failure, `test_m11_plboot`'s
  planted bug "fx_init called before snd_probe's answer", whose anchor
  line the fix had left one space short; the space put back (the same
  bytes), the module passes.

**The disk**: `build/native/DOOM.hdv`, 4,029,952 bytes, SHA-1
`9d2c23d6dd68c47114cfaf90f29b51d94878b7ed`. Every image in RamWorks and
LC.BIN are byte for byte as in `fd3ce9fd`; only `DOOM.SYSTEM` differs.

**Open problems**

- On an Appletini without the API, the CPU's stores reach main
  `$4078-$407F` (the frame slot at page `$40`, colormap B's level 0),
  where the firmware looks for `A2Li` (`MEMORY_MAP.md` rule 8):
  `playdisk.py` checks the pinned groups, not the level palettes'
  colormap bytes there.
- From one AUX bank to another (aux 0 counts as bank 0) the CPU switches
  `$C073` twice a byte (`cx_tog`): 3.9 µs a byte on a2vm `f122-nod2`
  against 0.8 µs within one bank (about 6 µs on the card at CALIB's
  2.95 µs a switch). The level load makes such copies (a second or so
  more there), and so do two copies of the 2D layer: the menu's screen
  save (`mv_amem`, aux 0 `$2000-$9FFF` to `S2VIEW`, 32 KB: 0.13 s on
  a2vm, about 0.2 s on the card, at every opening of the menu) and the
  busy sign's save (`sgsave`, aux 0 to `S2STATE`, 3,840 B: 15 ms, at a
  level's load). A bounce through a main page would cut them.
- The test disks (`LEVELS.hdv`, `RENDER.hdv`, `REPLAY.hdv`, `CALIB.hdv`)
  keep their own probes and still need the API.

## 20. What changed: the mouse card optional (2026-10-03)

For the owner, so that `DOOM.hdv` runs on an emulator with an enhanced
//e, 8 MB of RamWorks, a Phasor in slot 4 and Super Hi-Res, with a plain
AppleMouse II in slot 2 or none. Until now the game took its 50 or 60 Hz
interrupt (the tic clock, the music, the effects, the waits) from the
Appletini mouse card's registers: an AppleMouse II passed the ID check
and then never interrupted (the boot hung at `DOOM: LOADING`), and with
no card the boot stopped. **With your card nothing changed**: the same
card bytes, the same images in RamWorks, the same clock; the benchmark
reads 6.519 FPS (551 frames, 2,958 realtics, `TIC 89.4`) on a2vm
`f122-nod2`, as before. Section 12.1 lists what an emulator needs.

**What was changed**

1. **The probe** (`pl_boot.s` `probe_mouse`, in its old room of 44 B so
   that the rest of the boot keeps its addresses): the four AppleMouse
   ID bytes as before, then `mo_check` reads five bytes only the
   Appletini's slot ROM has: `$C200-$C201` (`LDX #2`, its slot helper)
   and `$C20D-$C20F` (`STA $C0AC`, its command stub, a register an
   AppleMouse II does not have); appletini-one's
   `scripts/build_mouse_rom.py` pins both. Reads only: nothing is written
   to slot 2 unless all nine match. Otherwise (`mo_none`) the boot checks
   that VIA-B's timer 1 is there (its latch holds `$55AA` then `$AA55`,
   `MUSIC.SYSTEM`'s `timer_check`) or stops with `NO CLOCK: NO APPLETINI
   MOUSE OR PHASOR` (`PL_NOMOUSE`, the old stop's code).
2. **The clock without the card** (`bt_detect`, after `snd_init`, whose
   IER `$7F` turned both VIAs' interrupts off): with interrupts masked,
   two frames between starts of a blanking at `$C019` are each counted by
   VIA-B's timer 1, restarted from `$FFFF` at every start (`vb_edge`; a
   time-out ends the wait, so no count is taken across one: no blanking
   for 65,536 counts, 64 ms at the bus clock, or a frame too long for the
   timer). Then:
   - two frames within 512 counts of the same standard and 256 of each
     other choose it, and the timer runs with the latch 20,278 (PAL) or
     17,028 (NTSC), a time-out every 20,280 or 17,030 bus cycles, the
     rate of the VBL;
   - two frames within 256 of each other and at least 16,384 counts but
     near no standard (an emulator's VIA counting faster than the bus)
     set the latch to the frame measured (plus the 13 counts from the
     reading to the restart, less 2), so that the timer still times out
     once a frame whatever its clock; the tic step is NTSC's, or PAL's
     when half the frame is near PAL's (a VIA at twice the bus clock),
     shown with a `?` (the review of 2026-10-03: before, any count
     outside the windows gave NTSC's latch, and a VIA at twice the bus
     clock ran the game at twice its speed, 2.4 times on a PAL machine);
   - otherwise (no blanking, a frame of 65,536 counts or more, two
     frames that differ) NTSC with its latch, and a `?`.
   The timer free-runs with its interrupt on (IER `$C0`), as
   `music/doom`'s `timer_on`, then `pl_clkset` with the standard. The
   tic step a period is the VBL's (45,743 or 38,229 / 65,536), so the
   clock is 34.955 tics a second either way.
3. **The handler without the card** (`bt_init`, after the install, from
   `pl_boot.s`'s own records `mo_recs`, `am_patch`'s form): the first 13
   bytes of `pl_vbody` become `LDA $C48D`, `AND #$40`, `BEQ pl_vnone`,
   `STA $C48D` (the flag cleared by writing it back, as `music/doom`'s
   `snd_irq`: a read of T1C-L in native mode would step the counter once
   more), three NOPs; the rest of the handler (the clock, `fx_step`,
   `snd_tick`, `fx_burst`) is unchanged, and the effects' and the
   music's port writes are untouched (the timer is VIA-B's own register
   set, `$C484-$C48E`). `pl_crash` turns VIA-B's interrupt off instead of
   the mouse card's mode. The IRQ contract is unchanged (`$C400-$C4FF`
   was in it).
4. **No mouse read without the card**: `pl_init`'s window and centring
   writes are branched over; in each frame image that links the poll
   (P2DW, MENUW, WIW, FINW) the buttons' read of `$C0A5` becomes `LDA #0`
   (a floating bus would press them) and `pl_mouse` an `RTS`. These
   eight records are `tools/native/nomouse.py`'s, written by
   `playdisk.py` into `DOOM.SYSTEM`'s `bt_mpatch` (52 B, 49 used), which
   also checks that the bytes `mo_recs` replaces are still the card's.
   The keyboard, the arrows and the Apple keys (Open Apple fires, Solid
   Apple uses) play the game.
5. **With the card, the PAL/NTSC choice checked**: `bt_detect` calls
   `pl_detect` as before and checks its count with the same windows; a
   count near neither standard (a VIA counting another clock) gives
   NTSC. Your card's count is in the window, so the result is the same.
   This lives in `DOOM.SYSTEM` (`std_of`), not in the card.
6. **Room**: the new code is in `DOOM.SYSTEM`'s `PLAMEM` segment; the
   memory API's patch table `bt_patch` went from 640 B to 512 B (462
   used) to make room (`amcpu.PATCH_SIZE`), 9 B free before `$3000`.
   `PLBOOT` keeps its size and
   every label's address; its bytes change at `probe_mouse`, at
   `bt_installed` (a `BRA` over the old ACK and mode, which `bt_init`
   now writes, in the same order), at the `jsr` to `bt_detect`, and in
   the strings' room.
7. **The tools**: a2vm `--mouse-plain` (slot 2's ROM with the AppleMouse
   ID bytes and an AppleMouse II's first instruction, no registers);
   `playdisk.py --mouse appletini|none|plain` (the last two add a2vm's
   `--via-timers`), and the profile `f122-nod2-ntsc`; `pldisk.py`'s
   `nomouse` check (no mouse card and a2vm without `--via-timers`, so no
   VIA-B timer) expects the new stop message.

**How it was checked** (once each, as the owner asked; he will validate
on an emulator):

- `tests/test_m11_plboot.py` without its planted bugs (`Pure`, the disk's
  files and sizes, the images against the card, the checkpoint's eight
  boots): 11 tests, OK;
- with the Appletini mouse card, `python3 tools/native/playtime.py
  --scene bench --profile f122-nod2`: the title with its music (230 AY
  writes before the menu at 7 s), the BENCHMARK 6.519 FPS, 551 frames,
  2,958 realtics, rows `TIC 89.4 3D 18.0 MASK 11.6 DRAW 31.3 REST 3.3`,
  as before;
- no mouse card, PAL (`playdisk.run`, `mouse='none'`, `f122-nod2`, 46 s):
  row 5 `NO APPLETINI MOUSE: PHASOR CLOCK, PAL`, PL_STATUS ready, the
  title, then the title demo; over 15-45 s 1,502 VIA-B interrupts, 50.080
  a second, and `CLK_TICS` 328 to 1,376: 34.966 tics a second (0.10%
  under 35);
  after the review's fix of the measured latch (`vb_edge` restarting the
  timer at each blanking, the latch from the frame near no standard),
  this run again: row 5 `NO APPLETINI MOUSE: PHASOR CLOCK, PAL` (no `?`),
  `CLK_STD` PAL, 1,502 VIA-B interrupts over 15-45 s (50.067 a second)
  and `CLK_TICS` 328 to 1,377, 34.967 tics a second; the NTSC and plain
  ROM runs below were not rerun, and a2vm's VIA counts the bus clock, so
  the new path for a VIA near no standard has not run;
- the same NTSC (`f122-nod2-ntsc`): `NTSC`, 59.923 interrupts a second,
  34.966 tics a second;
- slot 2 a plain AppleMouse ROM (`--mouse-plain`, PAL, 46 s): no hang; the
  same row 5, the same 50.080 interrupts and 34.966 tics a second, 1,160
  AY writes in 15-45 s (the music and the effects), and at 46 s the demo
  playing on E1M7 (`G_DEMOPLAY` 1, gametic 1,307).

**The disk**: `build/native/DOOM.hdv`, 4,029,952 bytes, SHA-1
`0b9470bac765ea4d6032b9727c013d7e0924fea8` (after the review's fix of
the measured latch; before it `7c479a808bd7d6346d0a41d2cf3c774886273081`).

**Open problems**

- Without the Appletini's card there is no mouse at all: an AppleMouse
  II's own protocol (its firmware's READMOUSE, or its interrupts) is not
  used.
- A VIA counting 3.85 times the bus clock or more (3.2 on a PAL
  machine) has frames of 65,536 counts or more, which timer 1's 16 bits
  cannot hold: the boot falls back to NTSC's latch and the game runs that
  many times too fast (with a `?` on row 5). One interrupt a frame there
  would need the handler to count several time-outs a tic, a change on
  the card. Between 1 and 3.85 times, the latch follows the frame, but
  the tic step is NTSC's unless the VIA is at twice the bus clock on a
  PAL machine, so a PAL machine at another rate runs 17% slow.
- Not run here: a real emulator, a Mockingboard instead of a Phasor (its
  second VIA would be the clock, the game silent), and the default path
  (no blanking at `$C019`: NTSC with a `?`).


## 21. What changed: the standard AppleMouse II (2026-10-04)

For the owner, who saw `NO CLOCK: NO APPLETINI MOUSE OR PHASOR` in his
GSSquared fork and said "it needs the Phasor. I can give it the standard
mousecard in slot 2": a standard AppleMouse II in slot 2 is now enough
for the clock and the mouse. **With your card nothing changed**: the
same card bytes, the same images in RamWorks, the same path through the
boot; the benchmark reads 6.519 FPS (551 frames, 2,958 realtics,
`TIC 89.4 3D 18.0 MASK 11.6 DRAW 31.3 REST 3.3`) on a2vm `f122-nod2`, as
before.

**Why the fork said NO CLOCK.** That stop means two things failed: slot
2 was not the Appletini's mouse card (the fork has no model of its
registers, and an AppleMouse II was not used then), and VIA-B's timer 1
latch at `$C486-$C487` did not hold `$55AA`, then `$AA55`. The fork's
Mockingboard (`src/devices/mockingboard/mb2.cpp`, `W6522.hpp`) would
have passed that test: `$C486` and `$C487` reach the 6522 at `$C480`
(`n6522[0]`), registers 6 and 7, whose writes set the latch's bytes and
whose reads return them; its timer counts video cycles, so the clock
would have run at 35 tics a second, silent (its AY has no Phasor native
mode). DOOM's test is right; the machine had no 6522 in slot 4 (the
`IIe_Appletini.gs2` configuration has only the `appletini` card in slot
7).

**In GSSquared** (`platform = "apple2e_enhanced"`, the `appletini` card
in slot 7 for the 8 MB of RamWorks and SHR): add `card = "mouse"` in
slot 2 (Apple's ROM and its 6805, the AppleMouse III model). The loading
screen's sixth row then says `APPLEMOUSE VBL CLOCK, NTSC?` with slot 4
empty (the `?`: no VIA to count a frame; right for the fork's `clock =
"ntsc"`), or `APPLEMOUSE VBL CLOCK, NTSC` with a `mockingboard` in slot
4 (still silent: no native mode). The memory API is still optional
(section 19): without it row 4 says so and the CPU copies.

**What was changed**

1. **The probe** (`pl_boot.s`, a new segment `PLMOUSE` after `PLAMEM`, so
   that `PLBOOT` and `PLAMEM` keep every address and the Appletini's
   path runs the same bytes; `DOOM.SYSTEM` grew from 4 KB to 5 KB,
   `$2000-$33FF`): the AppleMouse ID bytes without the Appletini's own
   are an AppleMouse II (`mo_none`'s first instruction now jumps to
   `mo_apple`), provided its entry table (`$C212-$C219`) has the five
   entries DOOM uses (a ROM with the ID bytes and no firmware is taken
   as no mouse card: a2vm's `--mouse-plain` still boots on VIA-B's
   timer). `mo_apple`, with the ROM visible and interrupts masked:
   INITMOUSE (on a //e its firmware reads `$FBB3` and times `$C019`),
   POSMOUSE to X 512, and the entries of SERVEMOUSE, READMOUSE and
   POSMOUSE written into the handler's three `JSR`s. Nothing can stop
   the boot there.
2. **The handler** (`ap_irq`, written into the card by `bt_init` after
   the install over `pl_detect` and `pl_wait`, which only the boot
   calls, and only with your card; `MEMORY_MAP.md` 21): `pl_vbody`'s
   first 13 bytes become `JSR ap_irq`, `BCS pl_vnone`, a `BRA` to the
   clock. At each interrupt `ap_irq` reads `$C018`, `$C013`, `$C014`
   and turns 80STORE, RAMRD and RAMWRT off (main memory for the
   firmware; PAGE2 maps nothing then and is left alone; ALTZP is never
   on in a handler, `MEMORY_MAP.md` rule 7; INTCXROM is never on after
   the boot); exchanges slot 2's eight screen holes (main `$047A`,
   `$04FA`, ... `$07FA`: colormaps A and B of levels 32 and 33 at `$7A`
   and `$FA`) with eight bytes in the card that keep the firmware's own;
   calls SERVEMOUSE (C set: not the mouse's interrupt, nothing counts),
   READMOUSE (X less 512 added to a 16-bit X in zero page `$FD-$FE`,
   button 0 into `$FF` with a count of updates) and POSMOUSE back to
   512; exchanges the holes again; puts the switches back as they were.
   The clock, `fx_step`, `snd_tick` and `fx_burst` follow unchanged.
   `MEMORY_MAP.md` rule 2 is amended for it: the switches, the firmware
   at `$C200-$C2FF`, zero page `$06` (SERVEMOUSE puts an RTS there and
   gives the byte back) and the holes, exchanged and put back.
3. **The mouse read**: in each frame image's poll (P2DW, MENUW, WIW,
   FINW) the reads of the card's buttons, sequence and X read those
   zero-page bytes instead (the same instructions, absolute operands
   `$00FD-$00FF`), and `pl_centre` writes them; the poll's arithmetic,
   its re-centring at `$8000`, the turn speed and the menus' MOUSE
   options are your card's. Its 41 records a frame image are
   `tools/native/nomouse.py`'s `apple_patches`, written by `playdisk.py`
   into `DOOM.SYSTEM`'s `ap_mpatch` (176 B, 164 used).
4. **The clock's standard** (`ap_clock`, from `bt_detect`, interrupts
   on): row 5 first (a mouse that never interrupted held the boot
   there; since the fix below it falls back to VIA-B's timer); then,
   when VIA-A's timer 1 latch
   holds what is written, one of the mouse's VBLs counted by it as
   `pl_detect` does: within 512 cycles of 20,280 PAL, of 17,030 NTSC;
   else NTSC with a `?`. Clock priority: your card, then an AppleMouse
   II's VBL, then the Phasor's VIA-B timer, else the stop, whose
   message is now `NO CLOCK: NO MOUSE CARD OR PHASOR`.
5. **The tools**: a2vm `--mouse-apple` (an AppleMouse II in slot 2: its
   ID bytes and entry table, each firmware call serviced by a2vm at its
   entry with the screen-hole protocol and zero page `$06` as the
   firmware uses them, through the bus so that the //e's switches and
   the interrupt bounds apply; its VBL interrupt in mode `$08`; the
   final state's `applemouse` counts the calls) and `--no-phasor` (slot
   4 empty); `--irq-bounds` takes 24 ranges; `playdisk.py --mouse
   apple` (with `--via-timers` and the handler's wider bounds);
   `playdisk.apple_card_problems` checks the two card ranges at every
   build.

**How it was checked** (once each; you will validate on GSSquared):

| Run (a2vm, `f122-nod2`, 47 s unless said) | Row 5 | `CLK_TICS`, 15-45 s | The title demo at 46.8 s | AY writes |
| --- | --- | --- | --- | ---: |
| AppleMouse, no Phasor, no memory API, NTSC (`f122-nod2-ntsc`) | `APPLEMOUSE VBL CLOCK, NTSC?` | 331 to 1,379: 34.93 a second (0.19% under 35) | demo3 on E1M7, gametic 1,270 | 0 |
| AppleMouse, no Phasor, no memory API, PAL | `APPLEMOUSE VBL CLOCK, NTSC?` | 276 to 1,152: 29.20 a second (NTSC's step at 50 Hz, as documented) | demo3 on E1M7, gametic 1,161 | 0 |
| AppleMouse and the Phasor, the API, PAL | `APPLEMOUSE VBL CLOCK, PAL` | 329 to 1,377: 34.93 | demo3 on E1M7, gametic 1,327 | 1,946 |
| AppleMouse and the Phasor, the API, NTSC | `APPLEMOUSE VBL CLOCK, NTSC` | 330 to 1,378: 34.93 | demo3 on E1M7, gametic 1,329 | 2,096 |
| Slot 2 a ROM with the ID bytes and no firmware (`--mouse-plain`), 20 s | `NO APPLETINI MOUSE: PHASOR CLOCK, PAL` | | | 498 |

In every AppleMouse run each interrupt was the mouse's (SERVEMOUSE,
READMOUSE and POSMOUSE once each per interrupt: 2,485 at 60 Hz), and
the handler stayed within its bounds (a2vm's `--irq-bounds`: zero page
`$06` and `$D8-$1FF`, the eight holes, `$C000-$C01F`, `$C0A0-$C0AF`,
`$C200-$C2FF`, `$C400-$C4FF`, `$E000-$FFFF`). A new game (RETURN at 8 s
and 9 s), the mouse moved 300 to the right at 11.6 s: the view from 90
to 40.56 degrees; 200 to the left at 13 s: back to 73.52 (two thirds of
the first turn, as the counts); its button held 14.2-15.0 s: the
command's BT_ATTACK and the pistol's clip from 50 to 48. Then
`tests/test_m11_plboot.py` without its planted bugs (11 tests, OK, the
`nomouse` check with the new stop message) and the BENCHMARK with your
card (`playtime.py --scene bench --profile f122-nod2`): 6.519 FPS, 551
frames, 2,958 realtics, as before.

**The disk**: `build/native/DOOM.hdv`, 4,030,976 bytes (1 KB more:
`DOOM.SYSTEM`), SHA-1 `adea421abac32f229ed7cbbaf4f290006ffcae48`.

**Open problems**

- Not run on a real emulator: a2vm's AppleMouse II is a model of the
  firmware's calls (their holes and zero page `$06`), not Apple's ROM
  and its 6805. The firmware's own stack use (about 6 bytes) and its
  time per call are from its listing, not measured; three calls a VBL
  may cost a real 6805 several hundred microseconds.
- With no 6522 in slot 4 the standard is a guess (NTSC, `?`): a PAL
  machine runs 17% slow. Counting a frame's display and blanking lines
  against each other at `$C019` would tell PAL (120 blank lines of 312)
  from NTSC (70 of 262) at any CPU speed; not done.
- Only button 0 is read (the AppleMouse has one); MOUSE 2 (strafe) has
  no source.
- If a memory-API copy into main `$0400-$07FF` ran while the interrupt
  exchanges the holes (an emulator whose API runs a request in the
  background), the copy's bytes at those eight places could be undone;
  with the CPU's copies (no API) an interrupt in the middle of a copy
  puts back exactly what it found.
- The fork's Mockingboard gives the PAL/NTSC count and no music: the
  Phasor's native mode (your branch `codex/phasor-dual-ssi263`, commit
  `c786a6d1`) is needed for the sound.

### The freeze on GSSquared (2026-10-04)

The owner: "If I run DOOM_Appletini.gs2, it starts loading and says
`APPLEMOUSE VBL CLOCK,` and freezes" (GSSquared's `feature/appletini-doom`,
slot 2 `mouse`, slot 4 `phasor`, slot 7 `appletini`; `DOOM.hdv` SHA-1
`515ec351`).

**The cause is GSSquared's, not DOOM's or Apple's ROM's.** Read in its
source (not run: the GUI is never launched here):

- `src/util/EventTimer.cpp` (`scheduleEvent`, lines 23-25) drops any event
  whose time is below `clock->get_cycles()`, the CPU's cycle count, and
  prints `scheduleEvent: Event in the past, skipping`. The card's VBL
  is scheduled on `computer->event_timer`, whose times are 14M ticks
  (`gs2.cpp` processes it against `clock->get_c14m()`).
- The `appletini` card sets 33.3 MHz when it starts (`pdblock3.cpp`
  1282). In that mode `NClockII::slow_incr_cycles` adds a CPU cycle at
  every cycle but a 14M tick on about 43% of them (238,944 / 556,272 a
  frame), so the CPU count runs ahead of the 14M count from the start
  and is over a frame ahead after about 20 ms.
- `applemouseiii.cpp` (lines 37-50) schedules each VBL at the frame's
  start + a frame + 192 lines, in 14M ticks: below the CPU count, so it
  is dropped; `vbl_timer_armed` is still set, so SETMOUSE `$09`'s
  `applemouseiii_schedule_vbl` returns at once. The card's VBL never
  comes again. INITMOUSE, POSMOUSE and SETMOUSE are synchronous in its
  model, so the boot gets to row 5, and `ap_wait` then waited for a
  VBL that never came. Ludicrous speed (F9) has the same wrong-clock
  check, and its probe frames also leave `get_frame_start_cycle()`
  behind ("AppleMouse III vbl cycle is before current cycle").
- The fix there: compare each timer's events with its own clock (14M
  for `event_timer`, video cycles for `vid_event_timer`, CPU cycles for
  `cpu_event_timer`), or drop the check, since `processEvents` already
  fires late events; and in `applemouseiii.cpp` set `vbl_timer_armed`
  only when the event was taken, and schedule the next VBL from the
  last one + a frame.

Apple's firmware itself works with DOOM: a2vm's new `--mouse-rom FILE`
runs Apple's ROM 342-0270-C (read from GSSquared's assets at run time,
never copied here) on a port of GSSquared's PIA and 6805 model, and
DOOM boots and plays on it (below). Its SERVEMOUSE runs an RTS at zero
page `$06`, whose dummy read on the 65C02 is `$07`: `playdisk.py`'s
AppleMouse interrupt bounds now include `$07` (`MEMORY_MAP.md` rule 2).

**What was changed in DOOM** (`pl_boot.s` `PLMOUSE` only: `PLBOOT` and
`PLAMEM` keep every byte, and the Appletini's card runs the same
bytes; `DOOM.SYSTEM`'s `PLMOUSE` is `$2FFF-$330B`, 244 B left before
`$3400`): `ap_wait`, which `ap_clock` and `ap_count` use, gives up after
20 changes of `$C019`'s bit 7 (10 frames, at any CPU speed). Then
`ap_novbl`, masked: SETMOUSE `$01` (on, no interrupt) and a SERVEMOUSE
(an interrupt that came late cleared); `pl_vbody`'s head on VIA-B's
timer 1 as without a mouse card, but calling `ap_irq` with its
SERVEMOUSE a `CLC`, so that each tick reads the mouse (READMOUSE,
POSMOUSE: `MEMORY_MAP.md` 21); the timer checked (`mo_via`: else the
stop) and `bd_via`'s standard, with row 5 saying
`APPLEMOUSE NO VBL: PHASOR CLOCK, ` and the standard. On GSSquared
until its timer is fixed the game should then run on the Phasor's timer
with the mouse read once a frame (not run there). a2vm has
`--mouse-no-vbl` for this: the ROM card's controller never sees a VBL.

**How it was checked** (once each, a2vm `f122-nod2` (PAL), the Phasor
and the memory API; `--rom` GSSquared's `apple2e_enh/main.rom`, whose
`$FBB3` is `$06`, for the ROM card):

| Run | Row 5 | `CLK_TICS` | Mouse firmware | The rest |
| --- | --- | --- | --- | --- |
| `--mouse-rom`, 47 s | `APPLEMOUSE VBL CLOCK, PAL` | 328 to 1,376 over 15-45 s: 34.93 a second (0.19% under 35) | mode `$09`; 2,076 interrupts, raised and released 2,076 times; SET 1, SERVE 2,076, READ 2,076, POS 2,077, INIT 2 | 1,900 AY writes; demo3 on E1M7, gametic 1,270 at 45 s, 1,310 at 46.8 s, views 62 to 72 |
| `--mouse-rom`, a new game, 16 s | `APPLEMOUSE VBL CLOCK, PAL` | | 523 interrupts, each served | the mouse 300 right at 11.6 s: the view 90 to 40.56 degrees; 200 left at 13 s: 73.52; button 0 held 14.2-15.0 s: BT_ATTACK in the command, the clip 50, 49, 48 |
| `--mouse-rom --mouse-no-vbl`, a new game, 20 s | `APPLEMOUSE NO VBL: PHASOR CLOCK, PAL` | 76 to 478 over 8-19.5 s: 34.96 a second | mode `$01`, no interrupt raised; SET 2, SERVE 1, READ 710, POS 711 (one a VIA-B tick) | 973 AY writes; the same turns (40.56, 73.52) and the same shots |
| `--mouse-apple`, 47 s | `APPLEMOUSE VBL CLOCK, PAL` | 328 to 1,377: 34.97 a second | calls SET 1, SERVE 2,077, READ 2,077, POS 2,078, INIT 1 | 1,946 AY writes; demo3 on E1M7, gametic 1,282 to 1,326 |

Then `tests/test_m11_plboot.py` without its planted bugs (11 tests, OK)
and the BENCHMARK with your card (`playtime.py --scene bench --profile
f122-nod2`): 6.519 FPS, 551 frames, 2,958 realtics, as before. All four
runs ended at their cycle limit within their interrupt bounds.

**The disk**: `build/native/DOOM.hdv`, 4,030,976 bytes, SHA-1
`2a4d0dad452afd1f0d670665438af2762b3dd8fe`; only `DOOM.SYSTEM` differs
from `515ec351`'s, from `$3038` (in `PLMOUSE`) on.

**Open problems**

- Not run on GSSquared. With its timer as it is, the boot should say
  `APPLEMOUSE NO VBL: PHASOR CLOCK,` and play on the Phasor's timer; with
  its timer fixed, `APPLEMOUSE VBL CLOCK,` as on a2vm.
- A mouse whose VBL stops after the boot (GSSquared's Ludicrous speed
  pressed during the game) still stops the game's clock: the fallback is
  decided once, at the boot.
- `ap_wait` trusts `$C019` to change: a machine whose blanking flag
  never moves and whose mouse never interrupts would still wait.
