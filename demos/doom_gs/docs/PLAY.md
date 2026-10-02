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
| The hooks milestone 10's parts call (sounds, I_GetTime, AM_*, ST_*, HU_*, WI_*, F_*, D_PageTicker, D_AdvanceDemo) | `src/native/dl_hook.s` | The tic image's core and group `DLG_HOOK` (slot 1) |
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
| `K_LOAD` | 1, bank, runs..., 0 | `far_pload` of the bank's page runs into the same addresses of main |
| `K_CALL` | 2, address, A, X | `jsr` with A, X (Y 0); its A into `DL_RES` |
| `K_WLOAD` | 3 | `far_wload` (the front end's code and the level's W tables) |
| `K_MLOAD` | 4 | `far_mload` (the masked phase's image) |
| `K_TIC` | 5, code | the tic image's W and core (`GCODE0`) and the walk's planes (`MOBJP`) back, the slots empty, then `dl_brain` through `gcall.s`'s `fc_go` with `DL_CODE` = code |
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
82 of 128 B with the benchmark's `DL_BENCH`, `DL_BVIEW`, `DL_BRT`:
`python3 tools/native/playlayout.py --report`).

## 4. Memory

| Space | Range | Holds |
| --- | --- | --- |
| Main card | `$FF00-$FFBD`, `$FFD5-$FFF9` | the kernel (190 B; `$FFBE-$FFD4` free) and, since speed wave 1, `far_gcopy` at `KERN_GCOPY` (`glayout.py`): `gr_load`'s copy of a whole group in one `RAMRD` window (the 250 B before the vectors are all used: `dl_kern.s` pads to `KERN_GCOPY`) |
| Main card | `$FE80-$FEFF`, `$FE7B-$FE7F` | `DLBUF` (the step list), `KV_*` |
| Main | `$0880-$08FF`, `$0B94-$0BFF` | the kernel's menu loop (read-only code, copied by DLINIT's PRIVATE request with the static tables: MEMORY_MAP.md 3.2's free bytes, never `$0878-$087F`) |
| Main | `$1F00-$1F7F` | `DLM`: the brain's state (`DL_*`) |
| Main | `$0310-$036F`, `$0F00-$13FF`, `$18A0-$18AB`, `$1A80-$1B7F` | the renderer's frame block, spans, `WPREV`, `TEXTRANS`: set at the boot by `s_rinit` (section 9 item 5) |
| W | `$6000-$BFFF` | one image at a time (section 5) |
| RamWorks 1 (`DLBANK`) | `$0200` request, `$1000` sources, `$6600` DLINIT | the boot's PRIVATE request and what it copies |
| RamWorks 48 (`SPRT`) | `$5400-$54DB` | `SPRBOUND`, written at the disk's build (section 9 item 6) |
| RamWorks 72-73 (`GCODE0-1`) | `$0200-`, `$6000-$99FF` | the tic image: its W and core at W's addresses, its groups packed (GCODE0 then GCODE1) |
| RamWorks 91 (`DEMOB`) | | demo3 (DOOM1.WAD's `DEMO3`) for the title loop |
| RamWorks 104 (`S2STATE`) | `$0200-` | the 2D state's first values (the palette state, the automap's, the HUD's, the menu's save slots' text, the settings' defaults) |

**The tic image** (glayout's game layout, linked by `play.mk` with
`playlink.py --tic-cfg`): W `$6000-$65FF`, core `$6600-$98CE` (13,007 of
13,312 B with speed wave 1's placement), slot 1 `$9E00-$A5FF`, slot 2
`$A600-$ADFF`, the planes `$B400-$BFFF`. The glue's groups follow
milestone 10's, 43 since speed wave 1: `DLG_B` 1,049, `DLG_C` 1,081,
`DLG_D` 1,242, `DLG_H` 1,902, `DLG_S` 1,270 B (of 2,048: `make -f
play.mk sizes`). `gcall.s`'s slot cache tags (`SLOT_GRP`) and, since
speed wave 1, the lazy restore's `SLOT_NEED` are reset at each `K_TIC`
because every other image overwrites the slots.

**Zero page.** Each image uses its own (MEMORY_MAP.md 13, SCREENS.md 4.3).
The glue in the tic image uses the game's temporaries `GT_0-6`
(`$5C-$62`) and `GA_0-10` (`$48-$52`), `FA_*` for `far_get`, `FC_*` for
`fc_call`, `GC_MP` for `mo_get`; none is live across a step. The kernel
uses none.

## 5. The images and their loads

| Image | Bank, pages | Load, measured or from the rate |
| --- | --- | --- |
| Tic image (W + core + planes) | 72 and 74: 57 + 12 pages | 4.4 ms (from the rate) |
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
(P2DW's 31 pages in 1.96 ms). The level load itself is milestone 9's: E1M1
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
`GFX.1`, `HUDTXT.1`. 4,027,904 bytes (speed wave 1).

`DOOM.SYSTEM` probes the card, loads every bank file into RamWorks and the
card images into the card, checks the CRCs, starts the mouse card's clock
and jumps to `pl_ready`: the kernel. Its first `K_TIC E_BOOT` runs
`b_boot` (ST_Init's state, `G_ReloadDefaults`, the renderer's statics, the
title's start) and the boot list: `DLINIT` (the PRIVATE copy of the
static tables and the menu loop; black palettes), `MENUW`'s `m_init`,
`WIW`'s `wi_init`, `FINW`'s `fin_init`, then the first frame. On a2vm the
title page shows about 6 s after the start of `DOOM.SYSTEM`.

## 8. Frame rate (a2vm, f121, measured)

**After speed wave 1 (2026-10-02; section 14, `docs/SPEED.md` 5).**
`python3 tools/native/playtime.py --scene still|demo3 [--profile
fastpath]` on `build/native/DOOM.hdv`, card-equivalent (the exact idle),
and the menu's BENCHMARK played whole from the menu:

| Scene | f121 before | f121 after | fastpath after | `K_TIC` after (f121) | Render after (`nr_frame` + `nm_masked` + `nm_bkload` + `nb_frame`, f121) |
| --- | ---: | ---: | ---: | ---: | ---: |
| E1M1's start, standing still (15-25 s) | 180.7 ms, **5.53 FPS**, 21.9 tics/s | 87.9 ms, **11.37 FPS**, 34.9 tics/s | 84.3 ms, 11.86 FPS | 24.4 ms (11.5 group loads a tic) | 52.2 ms |
| demo3 on E1M7, gametics 1052-1796 (186 frames of 4 tics) | 873.3 ms mean, **1.15 FPS**, max 1,656 | 271.6 ms mean, **3.68 FPS**, max 635 | 243.8 ms, 4.10 FPS | 188.4 ms (63.5 loads a tic) | 70.1 ms |
| OPTIONS, BENCHMARK: the whole of demo3, 534 frames | FPS **0.912** | FPS **3.318** (5,632 realtics) | FPS 3.842 | | |

"Before" is the owner's build (`SPEED.md` 2), but the benchmark's: it
did not exist then, so its "before" is that build plus part bench alone
(a2vm f121 with the exact idle: 534 frames in 20,480 realtics; part bench read 0.900 with the old idle). Standing still now runs at real time (35 tics a
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
    python3 -m unittest test_play_glue test_play_runs test_play_bench   # from tests/
    python3 tools/native/playtime.py --scene still|walk|demo3 [--profile fastpath]

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
   `vtw.turbo.enabled=ON`) loaded.
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
  f121: 534 frames in 5,632 tics, FPS 3.318).

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
  | The menu's BENCHMARK (all of demo3) | 0.912 | **3.318** |
  | (fastpath, for reference: still / demo3 / BENCHMARK) | 6.48 / 1.46 / 1.177 | 11.86 / 4.10 / 3.842 |

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

