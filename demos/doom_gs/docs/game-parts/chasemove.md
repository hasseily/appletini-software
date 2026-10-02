# Part `chasemove` (wave 5)

The record of milestone 10's part `chasemove` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 5; upstream 2211 B, native budget 2900 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 5's `chasemove` (2026-10-02, under the lean checks the owner asked for that day).
- Files: `src/native/game/chasemove/*.s`, `src/native/game/chasemove/part.mk`, `src/native/game/chasemove/args.json`, `tests/test_native_game_chasemove.py`, this file; tools (if any) `tools/native/gparts/chasemove*.py`; build output `build/native/game/chasemove/` (`make -s -C src/native -f game.mk part P=chasemove ROOT=$PWD`).
- Its scratch block: `SB_CHASEMOVE` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_enemy65.s`: `pMove:100` (`P_Move`: the speeds table, the try, blocked doors through `P_UseSpecialLine`), `P_TryWalk:321`, `P_NewChaseDir:1118` (`doNewChaseDir:1201`: the directions with `P_Random`, the turnaround), `avoidDropoff:1402` with `PIT_AvoidDropoff:1529`, `speedStep:2278`; helpers `mulSpeed`, `umul16x`, `speedTab`, `speeds`, `tryWalk`, `newChaseDir`, `setDir`, `absGreater`, `absD`, `boxPlus`, `boxMinus`, `blockOf`, `boxAbove`, `boxBelow`, `sideFloor`, `signed`, `times32`

Its checkpoint (GAME.md 2.4): `P_NewChaseDir` and `pMove` as entries (inside `A_Chase`: 300 each by path)

Its planted bugs (each must fail the named check): `P_Random` before the direct test; the turnaround table; the diagonal tried after the straight ones

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_enemy65.s:pMove` | `pMove` | demo3 22494, demo1 12083, demo2 2656, newgame 224, tour 0 |
| `p_enemy65.s:P_TryWalk` | `P_TryWalk` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_enemy65.s:P_NewChaseDir` | `P_NewChaseDir` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_enemy65.s:doNewChaseDir` | `doNewChaseDir` | demo3 0, demo1 0, demo2 41, newgame 0, tour 0 |
| `p_enemy65.s:avoidDropoff` | `avoidDropoff` | demo3 0, demo1 0, demo2 41, newgame 0, tour 0 |
| `p_enemy65.s:PIT_AvoidDropoff` | `PIT_AvoidDropoff` | demo3 0, demo1 0, demo2 287, newgame 0, tour 0 |
| `p_enemy65.s:speedStep` | `speedStep` | demo3 43914, demo1 24020, demo2 5230, newgame 448, tour 0 |

Helpers: `p_enemy65.s:mulSpeed`, `p_enemy65.s:umul16x`, `p_enemy65.s:speedTab`, `p_enemy65.s:speeds`, `p_enemy65.s:tryWalk`, `p_enemy65.s:newChaseDir`, `p_enemy65.s:setDir`, `p_enemy65.s:absGreater`, `p_enemy65.s:absD`, `p_enemy65.s:boxPlus`, `p_enemy65.s:boxMinus`, `p_enemy65.s:blockOf`, `p_enemy65.s:boxAbove`, `p_enemy65.s:boxBelow`, `p_enemy65.s:sideFloor`, `p_enemy65.s:signed`, `p_enemy65.s:times32`, `p_enemy65.s:SPD47`.

### 1.1 What was built

| File | What |
| --- | --- |
| `src/native/game/chasemove/pmove.s` | `pMove` (655 B, its tables 164 B of it) with `speedStep` (`cm_step`), `mulSpeed` (`cm_mulspeed`), `umul16x` (`cm_umul16x`), `speedTab`, `speeds`, `SPD47` in place; `tryWalk` (46 B); `P_TryWalk` (7 B, `FCALL tryWalk`) |
| `src/native/game/chasemove/chasedir.s` | `newChaseDir` (235 B: the drop-off test, the target's deltas); `doNewChaseDir` (517 B) with `setDir`, `absGreater`, `absD` in place; `P_NewChaseDir` (7 B, `FCALL newChaseDir`) |
| `src/native/game/chasemove/dropoff.s` | `avoidDropoff` (354 B) with `boxPlus`, `boxMinus`, `blockOf` in place; ITTAB's `PIT_AvoidDropoff` (468 B) with `boxAbove`, `boxBelow`, `sideFloor`, `signed`, `times32` in place |
| `src/native/game/chasemove/chasemove.inc` | the scratch block's bytes (27 of 32 B, overlaid where upstream's own uses do not meet: the file says which), the group offsets and dirty bits, the layout asserts |
| `src/native/game/chasemove/cmtest.s` | test builds of the part's own image only (`CM_TEST=1`): `cm_bulk`, the random checks' driver, in the driver's area (196 B) |
| `src/native/game/chasemove/part.mk`, `args.json` | the fragment (entries `pMove`, `tryWalk`, `P_TryWalk`, `newChaseDir`, `doNewChaseDir`, `P_NewChaseDir`, `avoidDropoff`, `PIT_AvoidDropoff`); the inputs and outputs (`pMove`, `newChaseDir`, `tryWalk`, `P_NewChaseDir`, `P_TryWalk`) |
| `tools/native/gparts/chasemove.py` | the part's own survey of `newChaseDir`, the candidates, captures and paths, the checkpoint on part `checkpos`'s run machinery (`checkpos.Prep`, `run_one`, `outputs`), the random checks, the planted bugs, sizes, `report.json` |
| `tests/test_native_game_chasemove.py` | the sources' checks (no far access; no routine jumps into another routine's local code), the build and budget, the sampled checkpoint (every 4th chosen call, `$A5`, `f121`), the random checks on 2,000 inputs: 9 tests, about 11 s; with `DOOM_GS_FULL=1` every chosen call on both profiles, the paths taken, 100,000 random inputs and the planted bugs (about 2 minutes) |

Total 2,289 B of the 2,900 B budget (upstream 2,211 B). No stand-in: every callee is built (`P_TryMove`: trymove; `P_UseSpecialLine`: lines; `P_BlockLinesIterator`, `P_BoxOnLineSide`: geom; `g_random`, `gv_inc`, the object API, `umul16`, `mul32`, `pta3`, `finesine`, `finecosine`, `g_stop`: the core and milestone 6).

### 1.2 The native interfaces

| Routine | In | Out |
| --- | --- | --- |
| `pMove` | `GA_0-1` the actor | A = 1 (C set) moved, or a special line opened; A = 0 (C clear) not, or `DI_NODIR`; after a refused move with special lines met: movedir `DI_NODIR`, `GM_NSPEC` = `$FF` (upstream's -1); changes `GA_*`, `GT_*`, `GS_*`, the math block |
| `tryWalk`, `P_TryWalk` | `GA_0-1` the actor | A = 1 (C set): moved, movecount = `P_Random() & 15`; A = 0 (C clear) not |
| `newChaseDir`, `P_NewChaseDir` | `GA_0-1` the actor (with a target: none stops with `GS_ERROR`, C Doom's `I_Error`) | nothing (movedir, movecount) |
| `doNewChaseDir` | the scratch block's `CM_AP` (the actor), `CM_D` (deltax, deltay) | nothing |
| `avoidDropoff` | `CM_AP` | A = 1 (C set) when the drop-off deltas are not both 0; `CM_DDX`, `CM_DDY`; `GM_TMBBOX` the actor's box |
| `PIT_AvoidDropoff` (ITTAB) | `GA_0-1` the line | C set (always) |

A_Chase (part `chase`, wave 6) calls `pMove` and `newChaseDir` (upstream's `jsr .kbank pMove`, `jsr .kbank newChaseDir` [R `p_enemy65.s:790`, `:948`, `:951`]) with `FCALL` and the actor in `GA_0-1`. `pMove` keeps upstream's TICSTEP 1 code only (the release's [R `tics.inc`]).

### 1.3 How the native code follows upstream

- **`pMove`** [R `p_enemy65.s:100-305`]: the speed's high word decides the 32-bit products (`pMoveMul32`, `mulSpeed`: `mul32` of the speed and the direction's value, as upstream's `_Mul32`); else each coordinate steps by its class (`speedStep` [R `:2278-2368`]): an axis adds or takes the speed from the whole part, a diagonal `SPD47[speed]` below 32, else `umul16` (upstream's `umul16x`). `speeds` is one table of 5 class values natively (`cm_value`): each direction's value is its class's [R `:308-311`]. Then `P_TryMove`; moved: z = floorz (P_TryMove's move already took `CLEAN` off); refused with special lines: movedir `DI_NODIR` and `P_UseSpecialLine` on each, the last first, `GM_NSPEC` decremented and re-read each turn.
- **`newChaseDir`** [R `:1130-1197`]: the drop-off test's three signed tests in upstream's order, `avoidDropoff`, then `doNewChaseDir` on the deltas and movecount 1; else the target's x, y less the actor's.
- **`doNewChaseDir`** [R `:1201-1396`]: as upstream, including `setDir` before the turnaround test (a diagonal equal to the turnaround is set and not walked), `P_Random` taken before `absGreater` (which runs only for 200 or less), the xdir and ydir turned to `DI_NODIR` when equal to the turnaround, the two search orders by `P_Random() & 1`, and the turnaround set even when it is `DI_NODIR`.
- **`avoidDropoff`, `PIT_AvoidDropoff`** [R `:1402-1724`]: the box in `GM_TMBBOX` (upstream's `_g_tmbbox`), the blocks `(box - bmaporg) >> 23` from the difference's high word, floorz = the actor's z (upstream's, not its floorz), `validcount` + 1, the blocks' loop in signed words; the callback's four box tests (signed 32 bits against the line's box words << 16), `P_BoxOnLineSide` = -1, the front and back floors from the line cache's two sectors (LVS's `LNSECF`, `LNSECB`, side 0's and side 1's: the line is two-sided), the angle by `pta3` of (±dx, ±dy) << 16 with 16-bit negations, `finesine`, `finecosine` of angle >> 19, `times32`.

## 2. Requests

Each is a change to a shared file, for the wave's integrator. No stand-in waits on them: the part builds and passes as it is.

**R1. The helpers done in place (`glayout.INLINED`).** What: add to `INLINED` in `tools/native/glayout.py`:

    # wave 5 as integrated: pMove's speed steps, products and tables,
    # doNewChaseDir's setDir, absGreater and absD, avoidDropoff's box and
    # block helpers, PIT_AvoidDropoff's box tests, side floors, negation
    # and shift are local code of the routine that calls them
    # (chasemove.md R1)
    'chasemove': ('p_enemy65.s:speedStep', 'p_enemy65.s:mulSpeed',
                  'p_enemy65.s:umul16x', 'p_enemy65.s:speedTab',
                  'p_enemy65.s:speeds', 'p_enemy65.s:SPD47',
                  'p_enemy65.s:setDir', 'p_enemy65.s:absGreater',
                  'p_enemy65.s:absD', 'p_enemy65.s:boxPlus',
                  'p_enemy65.s:boxMinus', 'p_enemy65.s:blockOf',
                  'p_enemy65.s:boxAbove', 'p_enemy65.s:boxBelow',
                  'p_enemy65.s:sideFloor', 'p_enemy65.s:signed',
                  'p_enemy65.s:times32'),

Why: each is called only by the routine that holds it natively [R `p_enemy65.s:140`, `:148` (`speedStep` from `pMove` only), `:250`, `:255` (`mulSpeed` from `pMoveMul32`), `:2346` (`umul16x` from `speedStep`), `:1263-1351` (`setDir`), `:1274` (`absGreater`), `:1364`, `:1368` (`absD`), `:1411-1434` (`boxPlus`, `boxMinus`, `blockOf` from `avoidDropoff`), `:1542-1649` (`boxAbove`, `boxBelow`, `sideFloor`, `signed`, `times32` from `PIT_AvoidDropoff`)]; natively they are local labels (`cm_*`) in those routines' segments, called with `jsr`. Today's `gplace.inc` gives them groups 2, 4, 5, 7, 9, 13, 14, 21 and 25, none of them used. `speedStep` is in the row's routines and upstream far code only for room [R `:2271-2277`]. Other parts: none (no other part calls them; `setDir` and `blockOf` are keyed `p_enemy65.s:`, not part evworld's or mobjstate's).

**R2. Placement (`gplace.py`).** What:

1. `CORE_FIRST`: replace `'p_enemy65.s:P_NewChaseDir'` and `'p_enemy65.s:P_TryWalk'` by `'p_enemy65.s:newChaseDir'`, `'p_enemy65.s:doNewChaseDir'` and `'p_enemy65.s:tryWalk'` (keep `pMove`). Natively `P_NewChaseDir` and `P_TryWalk` are 7 B wrappers that the release never calls (survey: 0 calls in every run); A_Chase calls `newChaseDir` and `pMove` [R `p_enemy65.s:790`, `:948`, `:951`].
2. `AFFINITY`: one unit `('p_enemy65.s:pMove', 'p_enemy65.s:tryWalk', 'p_enemy65.s:newChaseDir', 'p_enemy65.s:doNewChaseDir', 'p_enemy65.s:P_NewChaseDir', 'p_enemy65.s:P_TryWalk')` (1,467 B) and one `('p_enemy65.s:avoidDropoff', 'p_enemy65.s:PIT_AvoidDropoff')` (822 B, cold: DEMO2's 41 calls only).

Why: `doNewChaseDir` calls `tryWalk` up to 12 times a call, `tryWalk` calls `pMove`, so apart they reload a slot on most returns. In this part's image (the wave-4 placement) `pMove` is group 7, `newChaseDir` 15 and `doNewChaseDir` 13, all three slot 2, `tryWalk` 21 (slot 1): a `newChaseDir` costs 3.0 M cycles at the median on `f121` in routine mode (every slot empty at the call), almost all group loads, against `pMove`'s 1.1 M. GAME.md 4.3's rule stays: the unit not in `A_Chase`'s slot, and preferably not in the slot of part `checkpos`'s position check (group 10 today, slot 2), which `P_TryMove` calls under every `pMove`. `avoidDropoff` calls `P_BlockLinesIterator`, which calls back `PIT_AvoidDropoff` through ITTAB: apart in one slot they would reload on every line. Other parts: placement only.

**R3. `OWN_STACK`.** What: `glayout.OWN_STACK['p_enemy65.s:doNewChaseDir'] = 2`. Why: `doNewChaseDir` reaches `tryWalk` through its local `jsr cm_try`, so 2 B are under `tryWalk` and its callees, which the graph cannot see once R1 inlines the helpers. No other routine of the part keeps a byte on the stack across an `FCALL` (`pMove` and `cm_setdir` push only around object API calls). Measured: the lowest S of every run is `$B7` (183) for `newChaseDir` and `$C9` (201) for `pMove`. Other parts: `gcallgraph.py --stack`'s bound grows by at most 2 B on chains through `doNewChaseDir`.

**R4. The interfaces (README "The parts' interfaces").** What: these rows:

    | `pMove` (`chasemove`) | `GA_0-1` the actor | A = 1 (C set) moved or a special line opened, 0 (C clear) not; after a refused move with special lines met movedir `DI_NODIR` and `GM_NSPEC` `$FF`; changes `GA_*`, `GT_*`, `GS_*`, the math block |
    | `tryWalk`, `P_TryWalk` (`chasemove`) | `GA_0-1` the actor | A = 1 (C set): moved, movecount = `P_Random() & 15`; 0 (C clear) not |
    | `newChaseDir`, `P_NewChaseDir` (`chasemove`) | `GA_0-1` the actor, which has a target (none: `GS_ERROR`) | nothing |
    | `PIT_AvoidDropoff` (`chasemove`, `ITTAB`) | `GA_0-1` the line | C set (go on) |

Why: part `chase` (wave 6) calls `pMove` and `newChaseDir` from `A_Chase`. Other parts: `chase` uses these conventions.

## 3. Results

Lean checks (the owner's request of 2026-10-02): the `$A5` machine only, at most 40 calls an entry chosen to cover the candidates' paths, under `f121` and `fastpath`; 3 planted bugs.

**The part's survey.** `newChaseDir` is a helper, so the shared survey does not log it (`P_NewChaseDir`, the public routine of the row, has 0 calls in every run). `python3 tools/native/gparts/chasemove.py --survey` logs it in one ref816 pass a run, with the gametic and the dispatch targets it reaches, into `build/native/game/chasemove/survey/`: demo3 3,378 calls, DEMO1 1,717, DEMO2 341 (30 s in all). Every call comes from `A_Chase`; DEMO2's 41 drop-offs reach `PIT_AvoidDropoff`; the doors reached are `lnVDoor` and `lnPlat`. Every call of both entries is eligible (`pMove` 37,233 and `newChaseDir` 5,436 over the three demos; none waits).

**The candidates.** `--capture` made 303 cases (4 minutes): for each entry 60, 40 and 20 spread evenly over demo3, DEMO1 and DEMO2, and up to 12 of each run's calls that reached each dispatch target. Their paths, from the reference alone (`path_of`):

| `pMove` path | Candidates | | `newChaseDir` path | Candidates |
| --- | ---: | --- | --- | ---: |
| axis | 80 | | took the diagonal | 38 |
| diagonal | 66 | | took xdir or ydir | 39 |
| moved | 77 | | took the old direction | 9 |
| crossed special lines | 5 | | took the search | 19 |
| blocked | 39 | | ended at `DI_NODIR` (a door opened, or stuck) | 51 |
| blocked with special lines | 30 | | the drop-off test | 15 |
| a door opened (`lnVDoor`) | 26 | | moved away from a drop-off (`PIT_AvoidDropoff`) | 15 |
| none opened | 4 | | the diagonal is the turnaround | 7 |
| `lnPlat` reached | 3 | | xdir none | 16 |
| `DI_NODIR` | 1 | | olddir none | 55 |

**The checkpoint** (`python3 tools/native/gparts/chasemove.py --check --jobs 2`, 36 s): 40 chosen cases an entry, every candidate's path covered.

| Entry | Cases | Runs | Failed | Stray writes | Lowest S | Cycles, median / worst (`f121`; `fastpath`) |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `pMove` | 40 | 80 | 0 | 0 | 201 | 1,147,534 / 3,261,952; 862,426 / 2,377,694 |
| `newChaseDir` | 40 | 80 | 0 | 0 | 183 | 3,032,457 / 11,649,824; 2,282,564 / 8,832,162 |

Every run's canonical state equals ref816's with R1-R6 only (the moves, the sector, block and node lists, the line stamps and `validcount`, the line record, movedir, movecount, `P_Random`'s index), and the declared outputs (`pMove`'s A and `numspechit`) are equal. The cycles are routine mode with every slot empty at the call (an upper bound, mostly group loads: R2).

**The random checks** (`--random`, 7 s): `umul16x`, `mulSpeed` and `times32`, 100,000 inputs each (the edges 0, ±1, the extremes, the speed and class edges, then random; `mulSpeed` over the 16 directions' values and speeds of 16 and 32 bits), upstream's helper by `mathref batch` on a captured `pMove` call's machine against `cm_bulk`: 0 different; upstream equals the model (a × b; coordinate + speed × speeds[k]; v << 5, modulo 2^32) on every input.

**The planted bugs** (`--plants`, 57 s; each built from a scratch copy in a deleted temporary directory, run on `newChaseDir`'s 40 chosen calls, `$A5`, `f121`): `P_Random` taken before the direct test: caught (13 of 40 runs fail); the turnaround table (`olddir ^ 2`): caught (9 of 40); the diagonal tried after the straight ones (before the old direction): caught (26 of 40).

**Found by the checkpoint** (fixed before the numbers above): `ldx #dir` between a signed compare and its `bmi` (the 65C02's `ldx` sets N), which chose the wrong xdir and ydir; and `doNewChaseDir` calling `newChaseDir`'s local `cm_get`, which sits in another group of the same slot (group 15 against 13: the call ran another group's bytes). The test file now checks that no routine jumps into another routine's local code.

**Sizes** (the part's image's map; the driver's `cmtest.s` not counted): 2,289 of 2,900 B. `pMove` 655 (group 7), `tryWalk` 46 (21), `P_TryWalk` 7 (core), `newChaseDir` 235 (15), `doNewChaseDir` 517 (13), `P_NewChaseDir` 7 (core), `avoidDropoff` 354 (4), `PIT_AvoidDropoff` 468 (25); `grun.routine_sizes` gives the same. The core 13,266 of 13,312 B; the driver's area 3,385 of 3,584 B with `cmtest.s`. `gcallgraph.py --check --built` (waves 1-4 and this part): 0 failures; `--stack` 80 of 160 B.

**Commands.**

    python3 tools/native/gparts/chasemove.py --survey
    python3 tools/native/gparts/chasemove.py --capture --jobs 2
    python3 tools/native/gparts/chasemove.py --check --jobs 2
    python3 tools/native/gparts/chasemove.py --random
    python3 tools/native/gparts/chasemove.py --plants --jobs 2
    python3 -m unittest tests.test_native_game_chasemove    # 11 s; DOOM_GS_FULL=1: 2 minutes

`build/` grew by 38.8 MB (`build/native/game/chasemove`: the cases 16 MB, the image's objects 17 MB, the survey 20 KB); every temporary directory was deleted.

## 4. Open points

- Branches no chosen call takes (no candidate takes them): `doNewChaseDir`'s turnaround walk (`took-turnaround`) and a call with ydir `DI_NODIR`; `pMove`'s speed steps of 32 or more (`umul16x`) and of 65536 or more (`mulSpeed`): no E1 monster is that fast, so they are checked by the random checks only; `newChaseDir`'s stop on a missing target (A_Chase never calls it so); which of `PIT_AvoidDropoff`'s two sides (back at floorz, or front) the 15 drop-off cases take was not decoded.
- R2's placement: until the integrator places the unit, each `newChaseDir` loads up to three groups (R2's numbers).
- The sounds are not compared in routine mode (R6); `pMove` makes none itself (a door's sound comes from part `evworld`).
- (Wave 3 as integrated) `_g_tmbbox` and `_g_spechit` are GW's `GM_TMBBOX` and `GM_SPECHIT` (`checkpos.md` R1): used. `loadTarget` (part `look`) is not called: `newChaseDir` reads its target through the object API itself, as `loadTarget` would (its `LK_AP`, `LK_AT` stay look's).
- (Wave 4 as integrated) `P_TryMove` (part `trymove`): `GA_0-1` the thing, `GA_2-5` x, `GA_6-9` y; A = 1 and C set moved, 0 and C clear not; a refused move leaves `GM_NSPEC`, `GM_SPECHIT` as `checkPos` left them (`trymove.md` R4): used by `pMove`. The core's `P_CreateSecNodeList` leaves `GM_TMX`, `GM_TMY` = its thing's x, y (`teleport.md` R4); `P_TryMove` shares a group with `P_XYMovement` (`gplace.AFFINITY`, `trymove.md` R3).

## 5. The integration of wave 5 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 5 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 `INLINED['chasemove']` | **Accepted** as written (17 helpers) |
| R2 the placement | **Accepted**: `CORE_FIRST` names `newChaseDir`, `doNewChaseDir`, `tryWalk` (with `pMove`) in place of the 7 B wrappers; the two units in `gplace.AFFINITY`. Measured placement: only `tryWalk` (46 B) fits in the core (3,362 of 3,367 B); `pMove`, `newChaseDir`, `doNewChaseDir` and the wrappers are group 18 (slot 2, 1,713 B with `P_ChangeSwitchTexture`), not `A_Chase`'s slot (group 11, slot 1): the rule holds. The drop-off unit is group 5 (slot 2). The preference "not the position check's slot" is **not met**: `checkPos` is group 9, slot 2, so each `pMove` reaches `P_TryMove` (group 2, slot 1) and then `checkPos` over the chase's group, which reloads on return (the model's blind spot of a callee's callee, wave 4's open item) |
| R3 `OWN_STACK` | **Accepted** as written |
| R4 the interfaces | **Accepted**: README "The parts' interfaces" (the four rows); `chase.md` noted |
