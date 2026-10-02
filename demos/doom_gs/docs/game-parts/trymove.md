# Part `trymove` (wave 4)

The record of milestone 10's part `trymove` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 4; upstream 1164 B, native budget 1500 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 4's `trymove` (2026-10-02, under the lean checks the owner asked for that day).
- Files: `src/native/game/trymove/*.s`, `src/native/game/trymove/part.mk`, `src/native/game/trymove/args.json`, `tests/test_native_game_trymove.py`, this file; tools (if any) `tools/native/gparts/trymove*.py`; build output `build/native/game/trymove/` (`make -s -C src/native -f game.mk part P=trymove ROOT=$PWD`).
- Its scratch block: `SB_TRYMOVE` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_map65.s`: `P_TryMove:326` (the floor, ceiling, step and drop-off rules, the move: `overStep:440`, `mvNodes:860` with its shortcut, `spec:926` the crossed special lines through `P_CrossSpecialLine`), `lessHeight:421`, `specLine:1011`; `p_spawn65.s`: `P_NightmareRespawn:1126` (back at the place of its death, not its spawn point [R `p_spawn65.s:1121-1124`]), helpers `nmArg`, `nmXY`, `subFloor`, `fog`

Its checkpoint (GAME.md 2.4): `P_TryMove` (demo3 25,655 [M: CALLS]: 600 by path, the shortcut's both branches, and `mvNodes`' `LR_USE` branch, whose `P_CreateSecNodeList` takes the record without stamping lines (fact 4)); synthetic: a drop-off, a 24-unit step, two special lines crossed at once, a nightmare respawn (the generated nightmare stream)

Its planted bugs (each must fail the named check): the shortcut without `validcount++`; `LR_USE` not set (line stamps); `spechit` walked from the first; `MF_DROPOFF` ignored; floorz set before the step test

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_map65.s:P_TryMove` | `P_TryMove` | demo3 25655, demo1 21617, demo2 8822, newgame 592, tour 70 |
| `p_map65.s:overStep` | `overStep` | demo3 28861, demo1 26374, demo2 8423, newgame 736, tour 70 |
| `p_map65.s:mvNodes` | `mvNodes` | demo3 15663, demo1 16071, demo2 5978, newgame 439, tour 70 |
| `p_map65.s:spec` | `spec` | demo3 505, demo1 262, demo2 51, newgame 8, tour 0 |
| `p_map65.s:lessHeight` | `lessHeight` | demo3 33692, demo1 33373, demo2 12794, newgame 1052, tour 140 |
| `p_map65.s:specLine` | `specLine` | demo3 1128, demo1 646, demo2 113, newgame 24, tour 0 |
| `p_spawn65.s:P_NightmareRespawn` | `P_NightmareRespawn` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |

Helpers: `p_spawn65.s:nmArg`, `p_spawn65.s:nmXY`, `p_spawn65.s:subFloor`, `p_spawn65.s:fog`.

### 1.1 What was built

| File | What |
| --- | --- |
| `src/native/game/trymove/trymove.s` | `P_TryMove` (716 B) with `lessHeight`, `overStep`, the move, `mvNodes`, `spec` and `specLine` done in place (local `jsr`s inside the routine's own segment) |
| `src/native/game/trymove/nightmare.s` | `P_NightmareRespawn` (281 B) with `nmArg`, `nmXY`, `subFloor`, `fog` done in place |
| `src/native/game/trymove/trymove.inc` | the scratch block's bytes (`TM_SAVE`, `TM_OX`, `TM_OY`, `TM_OS`, `TM_LN`, `TM_TH`, `NR_MO`, `NR_NEW`: 27 of 32 B), the group offsets and dirty bits, the layout asserts |
| `src/native/game/trymove/part.mk`, `args.json` | the fragment (entries `P_TryMove`, `P_NightmareRespawn`); the inputs and outputs |
| `tools/native/gparts/trymove.py` | the candidates, captures and paths; `P_NightmareRespawn`'s synthetic calls; the checkpoint on part `checkpos`'s run machinery (`checkpos.Prep`, `run_one`, `outputs`); the planted bugs; sizes; `report.json` |
| `tests/test_native_game_trymove.py` | the build and budget, the far-access check, the sampled checkpoint (every 2nd chosen call, `$A5`, `f121`: 13-15 s); with `DOOM_GS_FULL=1` every chosen call on both profiles, the paths taken, the planted bugs |

No local stand-in is left: every callee is built (`cpCopy`, `checkPos`, `P_CheckPosition`: checkpos; `pointSector`, `P_PointOnLineSide`: geom; `mvSector`, `mvBlock`, `P_RemoveMobj`: mobjstate; `P_CrossSpecialLine`: lines; `spawnXYZ`: spawn; `P_CreateSecNodeList`, `gp_pointsub`, `gv_inc`, the object API, `S_StartSound`: the core).

### 1.2 How the native code follows upstream

- **The frame.** Upstream keeps tmthing, tmx, tmy (its `TT`), oldx, oldy and the old side on the stack [R `p_map65.s:318-325`]; natively they are the scratch block (`TM_SAVE`, `TM_OX`, `TM_OY`, `TM_OS`). `P_TryMove` copies `GM_TMTHING`..`GM_TMY` after `cpCopy` and takes them back, with `pointSector(tmx, tmy)`, when `G_MPCLOB` is set after `checkPos` (checkpos.md R5). The thing is the handle `TM_TH`, upstream's `TP`, which upstream takes back from the frame after each `P_CrossSpecialLine` [R `p_map65.s:996-1002`].
- **The tests.** `lessHeight` and `overStep` are the signed 32-bit compares that upstream's word pairs make (`d < height`; `d > 24.0`) [R `p_map65.s:421-452`]. They run in upstream's order: `tmceilingz - tmfloorz`, `tmceilingz - z`, `tmfloorz - z` (the step), then, unless `MF_DROPOFF`, `tmfloorz - tmdropoffz` [R `:369-407`]. `MF_NOCLIP` skips them [R `:360-364`].
- **The move**, in upstream's order [R `:458-536`]:
  - oldx and oldy, when `numspechit` is not 0;
  - unless `MF_NOSECTOR`, the sector list (`mvSector`). The list stays when the thing is already first in the new sector's list. Natively that is: its sprev is none and `GM_SEC`'s list head names it, the native form of upstream's `sprev == &MV_SEC->thinglist`;
  - unless `MF_NOBLOCKMAP`, the block list (`mvBlock`, with `GA_X`, `GA_Y` = tmx, tmy);
  - the kind plane's `CLEAN` off (upstream's byte 11);
  - floorz, ceilingz, dropoffz, x, y and the subsector (`GM_SS`);
  - unless `MF_NOSECTOR`, `mvNodes`;
  - unless `MF_NOCLIP`, and when `numspechit` is not 0, `spec`.
- **`mvNodes`** [R `:860-905`]: with `G_MPCLOB` 0 and `LR_OK` set, `LR_N` 0 and a touching list of one node (`m_tnext` none) of `GM_SEC`, it takes the shortcut: `gv_inc`, `_s_sector_list` none, the list kept. Otherwise it sets `LR_USE` to 1. Then `P_SetSeclist` in place (`G_SECLIST` = the touching list, the touching list none) and `P_CreateSecNodeList` (the core's `gp_secnodesmo`, which takes `LR_USE` and clears it).
- **`spec`** [R `:926-1022`]: `numspechit` (`GM_NSPEC`) is decremented and re-read in memory each turn, because game logic under `P_CrossSpecialLine` may change it. The line comes from `GM_SPECHIT[numspechit]`, the last one first. The count ends at `$FF` (upstream's word `$FFFF`).
- **`P_NightmareRespawn`** [R `p_spawn65.s:1126-1236`]: takes the dead monster in A:X (its caller is part `tic`'s `P_MobjThinker`). The first fog's z comes from the floor of its subsector's sector, the second's from the floor of `gp_pointsub(x, y)`'s sector. `spawnXYZ` makes the new mobj (`GA_X`..`GA_Z`), which gets the dead one's angle (`TH_ANG`, `TH_ANGLO`) and reaction time 18. Then `P_RemoveMobj`.

## 2. Requests

Each is a change to a shared file, for the wave's integrator. No stand-in waits on them: the part builds and passes as it is.

**R1. The helpers done in place (`glayout.INLINED`).** What: add to `INLINED` in `tools/native/glayout.py`:

    # wave 4 as integrated: P_TryMove's tests, mvNodes, spec and specLine,
    # and P_NightmareRespawn's argument loaders, subFloor and fog, are
    # local code of the routine that calls them (trymove.md R1)
    'trymove': ('p_map65.s:overStep', 'p_map65.s:lessHeight',
                'p_map65.s:mvNodes', 'p_map65.s:spec',
                'p_map65.s:specLine', 'p_spawn65.s:nmArg',
                'p_spawn65.s:nmXY', 'p_spawn65.s:subFloor',
                'p_spawn65.s:fog'),

Why: only `P_TryMove` calls `lessHeight`, `overStep`, `mvNodes` and `spec`, and only `spec` calls `specLine` [R `p_map65.s:374`, `:384`, `:394`, `:406`, `:522`, `:530`, `:939`, `:960`, `:983`]. Only `P_NightmareRespawn` calls `nmArg`, `nmXY`, `subFloor` and `fog` [R `p_spawn65.s:1144-1201`]. Natively they are local labels in `P_TryMove`'s and `P_NightmareRespawn`'s segments, called with `jsr` (no `ROUTINE`, no `FCALL`). So the placement must give them no bytes and no group of their own; today's `gplace.inc` gives `mvNodes` group 11, `lessHeight` 8, `spec` 17 and the helpers 20, none of them used. Other parts: none, since no other part calls them.

**R2. `OWN_STACK`.** What: `glayout.OWN_STACK['p_map65.s:P_TryMove'] = 2` and `glayout.OWN_STACK['p_spawn65.s:P_NightmareRespawn'] = 2`. Why: `mvNodes` and `spec` are reached by a local `jsr`, and they `FCALL` `P_CreateSecNodeList`, `P_PointOnLineSide` and `P_CrossSpecialLine`. Likewise `nr_fog` `FCALL`s `spawnXYZ`. That puts 2 B under those callees, which the graph cannot see once R1 inlines the helpers. Measured: the lowest S of every run is `$BC` for `P_TryMove` (with its callees and the driver's frame) and `$CC` for `P_NightmareRespawn`. Upstream's 21 B frame [R `p_map65.s:318-325`] is in the scratch block instead. Other parts: `gcallgraph.py --stack`'s bound grows by at most 2 B on the chains through these routines (the deepest chain of GAME.md 4.5 runs through `spec`).

**R3. Placement (`gplace.py`).** What: put `P_TryMove` (716 B) in the core if a later measure finds room; GAME.md 4.3 lists `trymove` in the core, and demo3 calls it 11 times a tic at the median [M: CALLS]. Otherwise put it in one group with part `xymove`'s `P_XYMovement` (its caller, 2.9 times a tic at the median: wave 3's finding), in the slot that does not hold part `checkpos`'s position check (group 8, slot 1). Then `P_TryMove` -> `checkPos` loads no group over its caller. `P_NightmareRespawn` (281 B, cold: skill 5 only) can go anywhere; placed with part `spawn`'s `spawnXYZ`, it would save a group load for each fog. Why: in routine mode (every slot empty at the call) a `P_TryMove` costs 909,317 cycles at the median on `f121`. Almost all of that is group loads: its own group 22, checkpos's 8, geom's 17, mobjstate's lists, and lines'. Other parts: placement only.

**R4. The interfaces (README "The parts' interfaces").** What: two rows:

    | `P_TryMove` (`trymove`) | `GA_0-1` the thing, `GA_2-5` x, `GA_6-9` y | A = 1 and C set: moved; A = 0 and C clear: not; `GM_TMFLOORZ`, `GM_TMCEILZ`, `GM_TMDROPZ`, `G_CEILLINE`, `GM_NSPEC`, `GM_SPECHIT` and the line record as `checkPos` leaves them, but `GM_NSPEC` is `$FF` when the crossed lines were walked (upstream's -1); changes `GA_*`, `GT_*`, `GS_*`, the math block |
    | `P_NightmareRespawn` (`trymove`) | A:X the dead monster | nothing |

Why: parts `xymove`, `missile` and `chasemove` (wave 5) call `P_TryMove`, and part `tic` (wave 6) calls `P_NightmareRespawn`. `chasemove`'s `pMove` reads `numspechit` and `spechit` after a refused move [R `p_enemy65.s:184-203`]; `spec` runs only after a move, so a refused move leaves the check's count. Other parts: those callers use these conventions.

## 3. Results

Lean checks (the owner's request of 2026-10-02): the `$A5` machine only, at most 40 calls an entry chosen to cover the candidates' paths, under `f121` and `fastpath`; 3 planted bugs.

**The candidates.** `python3 tools/native/gparts/trymove.py --capture` made 299 `P_TryMove` cases in `build/native/game/trymove/cases/`, in about 3 minutes:
- 140 spread evenly over demo3 (80), DEMO1 (40) and DEMO2 (20);
- every call (up to 12 a tic) of 14 tics where `spec` ran and of 6 tics where `P_TouchSpecialThing` ran;
- every eligible call that reached a dispatch target (11 `lnPlat`, 2 `A_Lower`).

Eligibility: every call of the survey's runs is eligible except 3 of demo3's, which wait for `lnFloor` (part `evfloor`, wave 4).

Their paths, from the reference alone (`path_of`):

| Path | Candidates |
| --- | ---: |
| moved | 218 |
| refused | 81 |
| refused by the check | 60 |
| refused by the height | 11 |
| refused by the step | 7 |
| refused by the ceiling | 2 |
| refused by the drop-off | 1 |
| refused with tmfloorz unlike the thing's floorz | 10 |
| `mvNodes`' shortcut | 164 |
| `LR_USE` branch, with lines | 41 |
| `LR_USE` branch, with none | 3 |
| the walk | 10 |
| `MP_CLOB` | 13 |
| sector list kept | 86 |
| sector list moved | 132 |
| crossed lines walked | 31 |
| crossed lines reaching `lnPlat` | 11 |
| missiles | 12 |
| a step up | 2 |

**The checkpoint** (`python3 tools/native/gparts/trymove.py --check --jobs 2`; `build/native/game/trymove/report.json`):

| Entry | Cases run | Runs | Failed | Stray writes | Cycles `f121` median / worst | `fastpath` median / worst | Lowest S | Bytes |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- | ---: |
| `P_TryMove` | 40 captured | 80 | 0 | 0 | 909,317 / 2,888,376 | 675,393 / 2,092,573 | `$BC` | 716 |
| `P_NightmareRespawn` | 8 synthetic (+2 without a reference) | 16 | 0 | 0 | 2,056,638 / 3,836,035 | 1,549,069 / 2,646,942 | `$CC` | 281 |

What is compared:
- the canonical state after the call (gcanon's routine mode, R1-R7): the mobjs with their sector, block and node lists, the sector nodes and their free list, the line stamps, `validcount`, the line record (`LR_OK`, `LR_USE`, `LR_N`, `LR_LINES`), `_s_sector_list`, the planes, `P_Random`'s index, and every mobj that a pickup, a damage or a respawn changes;
- the declared outputs: the result; tmfloorz, tmceilingz and tmdropoffz; `numspechit`; ceilingline; the line record;
- no stray write (checkpos's rule).

The 40 chosen calls take every path the candidates take:
- moved;
- refused by the check, the height, the ceiling, the step and the drop-off, including refusals with tmfloorz unlike floorz;
- `mvNodes`' shortcut, its `LR_USE` branch (with lines and with none), and the walk after game logic (`MP_CLOB`);
- the sector list kept and moved;
- the crossed lines walked, with `lnPlat` reached through `P_CrossSpecialLine`;
- an `A_Lower` reached through a missile's damage;
- missiles and a step up.

`P_NightmareRespawn`'s calls are synthetic, because no run plays skill 5. Upstream's routine runs alone by `ref816 --call` on the memory of 8 captured `P_TryMove` calls of monsters (their `_Dp[0-3]` is the thing):
- 6 respawns with room;
- 1 with none: its x, y poked to the player's mobj, which is solid, so `P_CheckPosition` refuses;
- 1 at x = y = 0.

Two more bases have no usable reference and are counted apart, never equal. In one, upstream's call does not return. In the other, the bridge reads three live sector nodes on no sector list after the call. Both come from the method: the spawns' `Z_Malloc` walks zone pages outside the base case's footprint, and those pages hold the run's base RAM, not that tic's memory.

**The planted bugs** (`python3 tools/native/gparts/trymove.py --plants`; each in a scratch copy in a deleted `build/tmp-m10-trymove-plant-*`, run on the 40 chosen calls, `$A5`, `f121`):

| Plant | Caught |
| --- | --- |
| `shortcut-no-validcount`: `mvNodes`' shortcut without `validcount + 1` | 16 of 40 runs fail (`validcount` one short) |
| `lruse-not-set`: `LR_USE` not set (the walk stamps the record's lines) | 4 of 40 runs fail (the lines' stamps) |
| `floorz-before-step`: floorz, ceilingz, dropoffz written before the height and step tests | 2 of 40 runs fail (a refused thing's floorz) |

**Sizes**: 997 of 1,500 B (upstream 1,164): `trymove.o` 716 (group 22), `nightmare.o` 281 (group 7). The build has no warnings. The scratch block: 27 of 32 B.

**The test** (`python3 -m unittest tests.test_native_game_trymove`): 6 tests, 13-15 s, 2 skipped without `DOOM_GS_FULL=1` (the paths and the plants).

**`build/` growth**: `build/native/game/trymove/` is 34,940 KB (the cases 16,456 KB, plus the part image and the logs); every temporary directory was deleted.

## 4. Open points

- (Wave 2 as integrated) `spawnXYZ` (part `spawn`, for `P_NightmareRespawn`'s fogs): A a type, `GA_X`..`GA_Z`, the slot back in A:X. Used so.
- (Wave 3 as integrated) `tmthing`, `tmx`, `tmy`, `_g_tmbbox`, `_g_spechit`, `MP_TRY` are GW's `GM_TMTHING`, `GM_TMX`, `GM_TMY`, `GM_TMBBOX`, `GM_SPECHIT`, `GM_MPTRY` (`checkpos.md` R1); `checkPos` takes them (README "The parts' interfaces"); `P_TryMove` keeps tmthing, tmx, tmy itself from its `cpCopy` and takes them back when `G_MPCLOB` is set after `checkPos` (`checkpos.md` R5). Done so.
- **Not covered by the sample** (the lean checks; left for the generated streams and the final integration). No candidate takes any of these, and no synthetic cases were made for them:
  - a thing with `MF_DROPOFF` stepping off a ledge of more than 24 units;
  - a step of exactly 24 units (the 2 step-up candidates are smaller);
  - `MF_NOCLIP`;
  - two special lines crossed in one move. 31 candidates walk `spechit` and 11 cross a line with a handler, but how many lines each one crossed is not in the reference's memory after the call.
- **`P_NightmareRespawn`** is checked on synthetic calls only; the real check is the generated nightmare stream (GAME.md 3.7) at the tic level. Its sounds (`sfx_telept` twice) are hook events and are not compared in routine mode (R6).
- **Planted bugs not made** (at most 3 under the lean rule):
  - `spechit` walked from the first: catching it needs two crossed special lines in one call (see above);
  - `MF_DROPOFF` ignored: the sample has no drop-off that `MF_DROPOFF` allows, and its 1 refused drop-off is a thing without the flag, which the plant would not change.
- The checkpoint ran from the `$A5` machine only; the `$5A` machine is left to the final integration.
- `gcallgraph.py --stack` was not run here (the integrator runs it on the merged wave); R2 gives it the 2 B.

## 5. The integration of wave 4 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 4 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 the helpers inlined | **Accepted**: `glayout.INLINED['trymove']` as written. `grun.routine_sizes` now leaves inlined names out, so `overStep`'s local label no longer splits `P_TryMove`'s bytes (716 B as one routine) |
| R2 `OWN_STACK` | **Accepted**: `P_TryMove` 2, `P_NightmareRespawn` 2; `gcallgraph.py --stack` 80 of 160 B (unchanged: not on the deepest chain) |
| R3 the placement | **Accepted, the second form**: the core has no room (3,367 of 3,367 B), so `gplace.AFFINITY` keeps `P_TryMove` with `P_XYMovement` (group 8, slot 1, with `slideMove`, `opening`), the slot apart from the position check (group 10, slot 2); part `xymove`'s wave may revise it with its measured sizes. `P_NightmareRespawn` with `spawnXYZ`: **refused** (cold, skill 5 only; its 281 B would be loaded with every puff and spawn of the hot spawn unit); the placement puts it in group 14 (slot 2) |
| R4 the interfaces | **Accepted**: README "The parts' interfaces"; `xymove.md`, `missile.md`, `chasemove.md`, `tic.md` noted |
| (teleport's R4) | The core's `gp_secnodes` now leaves `GM_TMX`, `GM_TMY` = its thing's x, y, as upstream's; after `mvNodes` they are the moved thing's x, y = tmx, tmy, the values `P_TryMove` had: no change to this part's results (its test module passes) |
