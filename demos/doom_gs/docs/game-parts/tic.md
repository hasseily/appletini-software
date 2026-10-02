# Part `tic` (wave 6)

The record of milestone 10's part `tic` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 6; upstream 1155 B, native budget 1500 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 6's `tic` (2026-10-02, lean rules of the owner's 2026-10-02 request).
- Files: `src/native/game/tic/gtick.s`, `src/native/game/tic/ptick.s`, `src/native/game/tic/tic.inc`, `src/native/game/tic/part.mk`, `src/native/game/tic/args.json`, `tests/test_native_game_tic.py`, this file; tools `tools/native/gparts/tic.py`; build output `build/native/game/tic/` (`make -s -C src/native -f game.mk part P=tic ROOT=$PWD`).
- Its scratch block: `SB_TIC` (32 B, `ggame.inc`): 4 B used (`tic.inc`: `TK_MO`, `TK_ACT`, `TK_KIND`). The walk's thinker and its next are the runtime's `RT_TH`, `RT_NEXT` (main `$19EF`, GAME.md 4.4).

The routines (GAME.md 2.4's row):

`g_game65.s`: `G_Ticker:563` (reborn, `P_MapEnd`, the actions with the load protocol (3.4), the command, demo playback, pause, `WI_End`, the state tickers); `p_map65.s`: `P_MapEnd:3296` (review 9); `p_think65.s`: `P_Ticker:185`; `p_tick65.s`: `P_RunThinkers:134` (the walk over the planes, kinds, `CLEAN`, deferred removal, the state end's action), `P_MobjThinker:540`, helpers `mobjArg`, `stillMobjThinker`

Its checkpoint (GAME.md 2.4): `P_MobjThinker` (every call), `P_RunThinkers` and `G_Ticker` (one a tic), each from both fills; then the first 140 tics of demo3 at tic level (3.6's harness). Lean (the owner's rules of 2026-10-02): at most 40 calls a routine, fill `$A5`, `f121`, no demo or tic-stream run.

Its planted bugs (each must fail the named check): next read after the call (a removed thinker's next); `CLEAN` kept after a momentum change; leveltime raised before the specials; the command copied while paused. Lean: three planted (3); the two others are open points (4).

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `g_game65.s:G_Ticker` | `G_Ticker` | demo3 3188, demo1 6078, demo2 4888, newgame 548, tour 1343 |
| `p_map65.s:P_MapEnd` | `P_MapEnd` | demo3 5323, demo1 11104, demo2 8724, newgame 1061, tour 1771 |
| `p_think65.s:P_Ticker` | `P_Ticker` | demo3 2135, demo1 5027, demo2 3837, newgame 513, tour 428 |
| `p_tick65.s:P_RunThinkers` | `P_RunThinkers` | demo3 2135, demo1 5026, demo2 3837, newgame 513, tour 428 |
| `p_tick65.s:P_MobjThinker` | `P_MobjThinker` | demo3 5968, demo1 11708, demo2 5507, newgame 333, tour 70 |

Helpers: `p_tick65.s:mobjArg`, `p_tick65.s:stillMobjThinker`, `g_game65.s:actions`.

## What was built

| File | Content |
| --- | --- |
| `src/native/game/tic/gtick.s` | `G_Ticker` (316 B), `P_MapEnd` (9 B, the core), and in the card's driver area (segment `DRIVER`, 17 B) the lockstep driver's two entries `g_ttick` (`dg_ticker`: `FCALL G_Ticker`) and `g_tresume` (`dg_resume`: flow's `g_resume`, then `G_Ticker`'s action loop `gt_loop` through `fc_call`) |
| `src/native/game/tic/ptick.s` | `P_Ticker` (82 B), `P_RunThinkers` (323 B), `P_MobjThinker` (278 B, with its local subroutines `mt_mo` = upstream's `mobjArg` and `mt_still` = `stillMobjThinker`) |
| `src/native/game/tic/tic.inc` | the scratch block's bytes, the line's group offsets, the ring's size (`TK_CMDS` 8, asserted against `G_CMDS`'s 64 B), the asserts on the layouts the code relies on |
| `src/native/game/tic/part.mk`, `args.json` | the fragment; the five entries (none takes an argument but `P_MobjThinker`, `GA_MO`; `P_MapEnd`'s `tmthing` a declared output, `gw:GM_TMTHING` as a mobj or none) |
| `tools/native/gparts/tic.py` | the selection by class from the survey, the captures, the reference's own calls (`P_MobjThinker`, the paused tic), the runs on part `mobjstate`'s machinery with the demo bank and the tic phase's globals, `G_Ticker`'s load runs (the driver's routine-with-load mode), the planted bugs, `report.json` |
| `tests/test_native_game_tic.py` | the build and budget, THTAB's entry, the driver's entries in the card, the far-access check; every 10th case of each entry with the paused tic, the intermission tics and the five loads (24 s); with `DOOM_GS_FULL=1` every case and the three plants (85 s) |

### The interfaces (for the integrator and the driver)

| Routine | In | Out |
| --- | --- | --- |
| `G_Ticker` | (the globals: gameaction, the player, the ring `G_CMDS`, demoplayback, menuactive, gamestate, prevgamestate) | A = 0; or A = `GT_LOAD` with `G_LOADACT` = the action that reached the load (the load protocol: the driver loads, then calls `g_tresume`); a saved game's action stops (`GS_SAVEGAME`), an action past `ga_worlddone` stops (`GS_ACTION`: upstream loops for ever there) |
| `gt_loop` | | `G_Ticker` from its action loop's test of gameaction (for `g_tresume` only) |
| `g_ttick`, `g_tresume` (card, `DRIVER`) | | the lockstep driver's `dg_ticker` and `dg_resume`: the driver jumps to them with no paging; A as `G_Ticker`'s |
| `P_MapEnd` | | `GM_TMTHING` = `$FFFF` (upstream's `tmthing = NULL`) |
| `P_Ticker` | | one level tic (nothing while paused by the menu out of a demo, but viewz 1) |
| `P_RunThinkers` | | the walk; `RT_TH`, `RT_NEXT` |
| `P_MobjThinker` (`THTAB` 1) | `GA_MO` the mobj | nothing |

### Notes on upstream's code, reproduced

- **The walk** (TICSTEP 1, `p_tick65.s:120-330`). A thinker's next is read before its turn (`RT_NEXT`): a removed mobj's or special's own link is its free list's after the removal (`gt_spfree`, the zone mobjs' `G_ZMFREE`), and a thinker appended during the last one's turn is not visited in this walk (upstream's stack-saved next). A mobj's kind plane holds upstream's byte 11: `P_MobjThinker` with no momentum on its floor gets `CLEAN` and from then on only its tics, as `P_MobjBrainlessThinker`'s mobjs (upstream's kinds 1 and 2, done in the walk); a mobj of `P_MobjThinker` that is not clean calls it and keeps its kind without `CLEAN` (upstream's byte 11 = 0 stays). Tics -1 stay (but a `CLEAN` `MF_COUNTKILL` mobj with respawnmonsters calls `P_MobjThinker`: `forever`); at 0 the state ends through `P_SetMobjState(mobj, state->nextstate)`, which is what upstream's inline state change (`state`, `stNext`, `stAct`) does: its sprite, frame, tics, the action, and again while the tics are 0. No function: nothing (kind 3). Any other function: `THTAB` (`DCALL`, the thinker in `GA_MO`). The walk only sets `CLEAN`: clearing it on a change of momentum, z or floorz is the movers' (upstream's `CLEARCLEAN`: parts `xymove`, `trymove`, `player`, `damage`, `planes`, `teleport`).
- **P_Ticker** (`p_think65.s:185-213`): paused when menuactive and not demoplayback and viewz is not 1 (upstream's "after a tic": the setup's viewz 1); `P_PlayerThink` when gamestate is `GS_LEVEL`; leveltime + 1 after `P_UpdateSpecials` and `P_MapEnd`. Upstream's own stack (`LOGIC_SP`) has no native counterpart.
- **G_Ticker** (`g_game65.s:563-632`): the ring's slot of gametic (`& (CMDS - 1)`, 8 bytes a slot) copied as upstream's 5 bytes; paused: basetic + 1 (32 bits) and no command; `WI_End` when prevgamestate was `GS_INTERMISSION` and gamestate changed; the tickers by gamestate (16-bit compares as upstream's).

## 2. Requests

Each a change to a shared file, with its evidence and its effect on other parts. The part goes on with a local stand-in where one is needed (marked in its source or harness).

**R1. `glayout.INLINED` for the helpers with no label.** What: `glayout.INLINED['tic'] = ('p_tick65.s:mobjArg', 'p_tick65.s:stillMobjThinker', 'g_game65.s:actions')`. Why: `mobjArg` and `stillMobjThinker` are `P_MobjThinker`'s local subroutines `mt_mo`, `mt_still` (`ptick.s`); `actions` (upstream's table `jsr (actions-2,x)`) is `G_Ticker`'s chain of compares (`gtick.s`); the placement gives them estimated bytes today (groups 16 and 12). Effect: the placement's estimates only.

**R2. The shared stray rule (`tools/native/gparts/mobjstate.py`).** What: in `allowed_main`, after the `ps_stack` lines:

    # the two places P_UpdateSpecials (part secfind) writes every tic, which
    # any caller of P_Ticker reaches: TEXTRANS (texturetranslation,
    # basepic .. basepic + 2) and the frame block's NUKAGE
    # (P_UpdateAnimatedFlat); both compared as canonical state (wave 6 as
    # integrated: docs/game-parts/tic.md R2)
    out.append((R.TEXTRANS, R.TEXTRANS + 256))
    out.append((R.FRAME['NUKAGE'], R.FRAME['NUKAGE'] + 1))

and in `stray()`, the driver's descriptor whoever writes it (a load run's driver reads the re-key record into it with `far_get`, the far layer's code; part flow's `allowed_places` allows it so): `elif w.storage == 'lc' and desc[0] <= w.offset <= desc[1]: continue`. Why: every `P_Ticker` and `G_Ticker` case wrote `$1ABD-$1ABF` (TEXTRANS 61-63) and `$0338` (NUKAGE) from `P_UpdateSpecials`' groups (48 "strays" in 24 cases before the stand-in), and every load run the descriptor (`pc $DC4F`, `RFAR`, writing `$ECA1-`). Stand-in: `tic.py`'s `stray()` (`TIC_ALLOWED`, the descriptor), which wraps `MS.stray` for its runs only. Effect: no part's result changes (the places are written by design and compared canonically); the integration's routine runs of `G_Ticker` and `P_Ticker` need it.

**R3. `glayout.OWN_STACK['p_tick65.s:P_MobjThinker'] = 2`.** Why: `mt_still` keeps its return on the stack under `pl_get` (the object API). Effect: `gcallgraph.py --stack` counts 2 more on that chain (64 + 24 of 160 B today, `--built` waves 1-5 and `tic`).

**R4. Placement: the walk with `P_MobjThinker`.** What: a `gplace.AFFINITY` unit `('p_tick65.s:P_RunThinkers', 'p_tick65.s:P_MobjThinker')` (323 + 278 = 601 B, measured: `grun.routine_sizes` on `build/native/game/tic/ptest`); the measured sizes of the others: `G_Ticker` 316, `P_Ticker` 82, `P_MapEnd` 9 (the core today). Why: the walk calls `P_MobjThinker` for every mobj that is not clean (demo3: 5,968 calls in 2,135 tics); today they are groups 5 and 3, both slot 2, so each call loads 2 KB and reloads the walk's group on its return. The survey's call counts cannot see it: upstream calls it by the walk's `JML [FN_P]` (`callFn`), as `TRVTAB`'s traversers (wave 5's `APART` note). Group 3 is at 2,047 of 2,048 B in the part's image with `P_MobjThinker` in it. Effect: the placement's.

**R5. The lockstep runner's wiring (`tools/native/ticrun.py`, wave 1's open item; `tools/native/ticcap.py`).** What: `dg_ticker` = `g_ttick` and `dg_resume` = `g_tresume` (labels of the image, both in the card's `DRIVER` area: `gdriver.s` jumps to them with `jmp (FC_T)`, no paging, and `G_Ticker` itself is in a group); with the items already listed in 4: `DEMOB` by `DEMOB_LAYOUT` (part flow's `demob_records`), `gameroutine.tic_main_records` (`G_WSET`, `G_FPSSHOW`, `G_ONGROUND`) at a run's start. And the setups' re-key records: `ticcap.py`'s records of every setup of the five fixed runs have no hints and no `CS_PREV` (`TC.load(run)['setups']`: all 22 empty, flow's open point); `tic.py`'s `setup_rekey()` makes a setup's record from the reference's memory: the state after the setup (here `G_Ticker`'s return) with upstream's `SIGHTHINT` table and `CS_PREV1/2/R` from before the load (nothing but `P_CheckSight` writes them, and the setup calls none), decoded with the new level's pool. Why: demo1's reborn load (`G_Ticker` h2477) differed in two line stamps with the record of the state after the call (the new level's first tic had changed the hints) and in the hints themselves with ticcap's empty record; with `setup_rekey` it is equal. Effect: `ticrun.py` and `ticcap.py`, which only the integrator changes.

**R6. Documents.** What: (a) `GAME.md` 2.4's row `tic`, planted bugs: add "Lean (wave 6, `tic.md` 1): three planted (the next read after the call, leveltime before the specials, the command copied while paused); `CLEAN` kept after a momentum change is the movers' clear (the walk only sets `CLEAN`), and the load returned without `G_LOADACT` cannot be seen (flow's `doLoadLevel` sets it too)". (b) `src/native/game/README.md` "The parts' interfaces", rows:

    | `G_Ticker` (`tic`) | (the globals) | A = 0, or `GT_LOAD` with `G_LOADACT` the action (the load protocol); `GS_SAVEGAME` for a saved game's action, `GS_ACTION` past `ga_worlddone` (upstream loops for ever) |
    | `g_ttick`, `g_tresume` (`tic`, the card's `DRIVER`) | | the lockstep driver's `dg_ticker`, `dg_resume`: `G_Ticker`; flow's `g_resume`, then `G_Ticker`'s action loop (`gt_loop`) |
    | `P_Ticker`, `P_RunThinkers`, `P_MapEnd` (`tic`) | | the level's tic; the walk (`RT_TH`, `RT_NEXT`); `GM_TMTHING` = `$FFFF` |
    | `P_MobjThinker` (`tic`, `THTAB` 1) | `GA_MO` the mobj | nothing |

(c) `src/native/lsetup.s`'s comment "P_MapEnd: no tmthing natively" is out of date (`GM_TMTHING` exists since wave 3; the load leaves it as it is, which nothing reads before `checkpos` writes it).

## 3. Results

Lean checkpoint (2026-10-02; `python3 tools/native/gparts/tic.py --capture --synth`, then `--build --check --plants --jobs 2`; `$A5`, `f121`; `build/native/game/tic/report.json`): every comparison exact against `ref816` (gcanon's routine mode, R1-R7 only), every declared output equal (`tmthing`; `G_ONGROUND` against `PU_ONGROUND` after every call), the native-only globals consistent, no stray write (with R2's places).

| Entry | Cases eligible / run | Failures | Waiting | Stray writes | CPU cycles median / worst (f121) | Lowest S | What the cases are |
| --- | ---: | ---: | --- | ---: | --- | ---: | --- |
| `G_Ticker` | 20 / 20 | 0 | 0 | 0 | 4,381,560 / 10,289,562 | `$A7` | 12 level tics (6 demo: `readDemoTiccmd`; 6 ring: the command copy) by class; 2 intermission tics (tour: `WI_Ticker`); 5 loads (routine-with-load mode: tour's `doNewGame` and first `doWorldDone` (with `WI_End`), newgame's `doNewGame`, demo3's `doPlayDemo` (title to demo), demo1's reborn `loadLevel` (`PST_REBORN`)), each through `GT_LOAD`, `G_LOADACT`, the driver's load, `g_tresume` and the new level's tic; the paused tic (synthetic) |
| `P_Ticker` | 12 / 12 | 0 | 0 | 0 | 7,334,090 / 8,839,453 | `$B8` | 8 consecutive tics of demo2 (leveltime crosses a multiple of 8: the animated textures and `NUKAGE`), 4 by class (demo, ring) |
| `P_RunThinkers` | 30 / 30 | 0 | 0 | 0 | 5,897,718 / 9,060,035 | `$B3` | by class of reached targets: every eligible removal of a special (`P_RemoveThinkerDelayed`, 5), mobj removals, the states' actions (`A_Look`, `A_Pain`, `A_Fall`, `A_Scream`, `A_PlayerScream`, `A_FaceTarget`), the slides, the lights and scrollers |
| `P_MobjThinker` | 40 / 40 | 0 | 0 | 0 | 83,910 / 3,563,855 | `$B8` | the reference's own calls on 10 captured `P_RunThinkers` states, by class: momentum in x or y (8), z or momz (8), tics 1 (8, the next state's action built), tics -1 (8), other tics (8) |
| `P_MapEnd` | 6 / 6 | 0 | 0 | 0 | 61 / 61 | `$EB` | level tics of every run; `tmthing` (`GM_TMTHING`) none |

The cycles are routine mode with every slot empty at the call (group loads included: an upper bound); the load runs' are not counted.

Planted bugs (each in a scratch copy, built in a temporary directory, deleted), all caught:

| Plant | Check | Runs | Failed |
| --- | --- | ---: | ---: |
| `next-after-call`: a special's next read after its turn | `P_RunThinkers`' cases with `P_RemoveThinkerDelayed` | 5 | 1 (demo1 h757: the walk followed the free list and stopped; a mobj's z, momz, tics) |
| `leveltime-first`: leveltime + 1 before `P_UpdateSpecials` | every `P_Ticker` case | 12 | 2 (`nukage`, `texturetranslation` at the multiple of 8) |
| `paused-copy`: the ring's command copied while paused (and no basetic + 1) | the paused tic | 1 | 1 (basetic, `player.cmd`) |

Sizes (the part's image map): 1,008 B of 1,500 (`gtick` 325, `ptick` 683; upstream 1,155), plus 17 B in the card's driver area (`g_ttick`, `g_tresume`). `G_Ticker` and `P_RunThinkers` are in group 5 (slot 2, 1,651 B), `P_MobjThinker` in group 3 (slot 2, 2,047 of 2,048 B), `P_Ticker` in group 11 (slot 1), `P_MapEnd` in the core. The driver's area 3,203 of 3,584 B in the part's image.

Checks: `gcallgraph.py --check --built` (waves 1-5 and `tic`) 0 failures (935 heads, 589 reachable); `--stack` 64 + 24 IRQ = 88 of 160 B; `glayout.py --check` ok; the far-access grep on the part's sources clean; the build has no warning. Test module: `python3 -m unittest discover -s tests -p test_native_game_tic.py` 8 tests OK (1 skipped: `DOOM_GS_FULL`), 24 s; with `DOOM_GS_FULL=1` 8 OK, 85 s.

`build/` growth: 54 MB (`build/native/game/tic`: the cases 22 MB with the runs' bases, the image and its objects); every temporary directory of the part's runs deleted.

## 4. Open points

- **Not covered by the lean checkpoint**: fill `$5A` and `fastpath`; the nightmare respawn (no run has respawnmonsters: `P_MobjThinker`'s `mt_nm` body past its first tests and the walk's `rt_ever` call are not taken); a removal by `P_XYMovement` or `P_ZMovement` before the tics (the exits after `mt_still`) not shown taken; a mobj of no function on the list (`linkRemove`'s, between its add and its removal) not shown taken; `G_Ticker`'s `doCompleted` and `victory` actions, the saved games' stop, `GS_ACTION`, the finale's and the title's tickers (`F_Ticker`, `D_PageTicker`: states with no level, not decodable), basetic's carry; `P_Ticker`'s menu pause with viewz 1.
- **Waiting for the wave's other parts**: every call reaching `A_Chase`, the monsters' attacks (`chase`), `T_VerticalDoor`, `T_PlatRaise` (`movers`) or the weapons' fire (`wfire`) is not eligible in the part's image (waves 1-5 and `tic`): of the survey's calls, `P_RunThinkers` demo3 90 of 2,135 eligible, demo1 1,063 of 5,026, demo2 2,787 of 3,837, newgame 337 of 513, tour all 428.
- **The 140 tics of demo3 at tic level** were not run (lean: no demo or tic-stream runs) and need R5's wiring. The survey says which tics would wait: of demo3's first 140 level tics (gametic 1051-1190), 74 reach only built targets; `T_VerticalDoor` (part `movers`) from gametic 1123 (35 tics), `A_Chase` (part `chase`) from gametic 1127 (56 tics): a lockstep run of the part's image would stop at gametic 1123.
- **Two of the row's planted bugs are not planted**: `CLEAN` kept after a momentum change (the walk only sets `CLEAN`; the clears are the movers' parts' code); the load returned without `G_LOADACT` (part flow's `doLoadLevel` also sets `G_LOADACT` from gameaction, so `G_Ticker`'s own store cannot be seen: the five load cases check the protocol).
- R2's stand-in (the part's stray rule) and R5's `setup_rekey` live in `tic.py` until the integrator applies them.
- (Wave 2 as integrated) The tic stream's cheat events (kind 1): `lda #number`, `FCALL C_Responder` (part `pickup`) where upstream's `D_ProcessEvents` calls it, before `G_Ticker` (`pickup.md` P6): the driver's, not `G_Ticker`'s (upstream calls it outside `G_Ticker`).
- (Wave 2 as integrated) `ticrun.py` writes `G_FPSSHOW` from the reference's `_g_fps_show` at a run's start, as `G_WSET` (`pickup.md` P4): R5.
- (Wave 4 as integrated) `P_NightmareRespawn` (part `trymove`): A:X the dead monster; nothing back (`trymove.md` R4): `P_MobjThinker` calls it so. `T_MoveFloor` is `THTAB`'s floor entry (part `planes`): the walk dispatches it.
- (Wave 5 as integrated) `gameroutine.tic_main_records` gives `G_ONGROUND`: the part's runs write it (and compare it with `PU_ONGROUND` after every call); `ticrun.py`'s start is R5.

## 5. The integration of wave 6 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 6 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 `INLINED['tic']` | **Accepted** as written |
| R2 the shared stray rule | **Accepted**. `mobjstate.allowed_main` allows `TEXTRANS` and `NUKAGE`, and `mobjstate.stray` allows the driver's descriptor whoever writes it. `tic.py`'s stand-in (`TIC_ALLOWED`, the wrapper and its swap in `run_one`) is removed: its `stray` is the shared rule |
| R3 `OWN_STACK` | **Accepted** as written |
| R4 the placement | **Accepted, and widened by the integrator.** The walk's unit also takes the thinkers that the walk reaches by `callFn` every tic: `T_Glow`, `T_LightFlash`, `T_StrobeFlash`, `T_Scroll` and `P_MobjBrainlessThinker` (1,019 B in all). Placed in any other group of the walk's slot, each of them would load its own group and then the walk's again, every tic. In the final placement (with the plant margins) the unit is group 21 (slot 1, 1,458 B). `P_SetMobjState` is group 19 in the same slot: `P_MobjThinker`'s call at a state's end is native code where upstream's is inline, so the survey does not count it. An `APART` pair for it raised the model's cost by about what it would save, so it was not added (GAME.md "Wave 6 as integrated") |
| R5 the lockstep runner's wiring | **Deferred to the final integration**: it is checked only by the tic-level runs (demo3's first 140 tics), which a lean merge does not make. `tic.py` keeps `setup_rekey` and its loads' wiring |
| R6 the documents | **Accepted**: GAME.md 2.4's row, README's rows, `lsetup.s`'s comment |

**Found by this integration.** The integrated image failed the load case
`load: doWorldDone` (tour h151). The run hit its cycle limit at `$4C4E`,
with stray writes from slot 2. After the load, `g_tresume`'s `fc_call`
found `SLOT_GRP` still naming `G_Ticker`'s group (then 26, slot 2), so it ran
the load image's bytes. The load image had overwritten the slots, and the
test driver never forgot what they held. In the part's own image a callee
of `g_resume` happened to page slot 2 first. Fix: `gdriver.s`'s
`core_in` sets every `SLOT_GRP` to `$FF`, as milestone 11's kernel does at
its tic (`dl_kern.s`); it runs after every load and every frame. After it
the case passes.

The selection changed with the wave built: `G_Ticker`, `P_Ticker` and
`P_RunThinkers` calls that reach the movers', weapons' and chase's
routines are now eligible. `tic.py --capture` was run once more for the
new selection (20 s). The test module then runs the integrated wave's
routines inside the walk.

Sizes in the wave image: `gtick.o` 328 B, `ptick.o` 683 B (1,011 of
1,500 B; `g_ttick` and `g_tresume` in the driver's area). The test module
(default mode): 8 tests, 1 skipped (`DOOM_GS_FULL`), OK.

## 6. The final integration (2026-10-02)

R5, deferred at wave 6, is **applied** by the integrator in
`tools/native/ticrun.py` (docs/GAME.md "Acceptance"): `dg_ticker` =
`g_ttick`, `dg_resume` = `g_tresume`; the demo bank by part flow's
`demob_records`; `gameroutine.tic_main_records` (`G_WSET`, `G_FPSSHOW`,
`G_ONGROUND`) at a run's start; every setup's re-key record from
`ticcap.py`, made again at the final integration (the records of the
later setups hold their hints now: `setup_rekey` stays the part's, for
its routine-with-load cases). The lockstep runs pass with them: demo3,
DEMO1 (seven reborn loads), DEMO2, newgame, the tour (eight world-done
loads) and three generated streams, every tic equal.

Found by the tic-level runs, in the skeleton's driver, not in this part:
`gdriver.s`'s lockstep loop never raised gametic after a tic (upstream's
`runTic`, `d_main65.s:248-251`); the skeleton's stub ticker raised it
itself, so the selftest hid it. The driver raises it now and the stub
(`game/gtest.s`) no longer does.
