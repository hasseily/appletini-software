# Part `missile` (wave 5)

The record of milestone 10's part `missile` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 5; upstream 593 B, native budget 800 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 5's `missile` (2026-10-02, under the lean checks the owner asked for that day).
- Files: `src/native/game/missile/*.s`, `src/native/game/missile/part.mk`, `src/native/game/missile/args.json`, `tests/test_native_game_missile.py`, this file; tools (if any) `tools/native/gparts/missile*.py`; build output `build/native/game/missile/` (`make -s -C src/native -f game.mk part P=missile ROOT=$PWD`).
- Its scratch block: `SB_MISSILE` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_spawn65.s`: `P_SpawnMissile:533` (the angle, a shadow target's `P_Random`, `momz` by the distance with the 32-bit divide, `checkMissile:850`: tics noise, a half step, `P_TryMove`, the explosion); helpers `srcArg`, `srcAbove`, `seeTarget`, `thSpeed`, `destDelta`, `angleMom`, `speedMom`, `halfMom`

Its checkpoint (GAME.md 2.4): Every captured monster missile (imps in all demos); synthetic: a missile spawned inside a wall

Its planted bugs (each must fail the named check): `momz` rounded the other way; the shadow `P_Random` taken for a visible target; the tics noise skipped

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_spawn65.s:P_SpawnMissile` | `P_SpawnMissile` | demo3 14, demo1 58, demo2 4, newgame 0, tour 0 |
| `p_spawn65.s:checkMissile` | `checkMissile` | demo3 14, demo1 58, demo2 4, newgame 0, tour 0 |

Helpers: `p_spawn65.s:srcArg`, `p_spawn65.s:srcAbove`, `p_spawn65.s:seeTarget`, `p_spawn65.s:thSpeed`, `p_spawn65.s:destDelta`, `p_spawn65.s:angleMom`, `p_spawn65.s:speedMom`, `p_spawn65.s:halfMom`.

### 1.1 What was built

| File | What |
| --- | --- |
| `src/native/game/missile/missile.s` | `P_SpawnMissile` (381 B, with `destDelta` as its local `delta` and `sub4`), `checkMissile` (106 B), `halfMom` (45 B); and the helpers that part `wfire`'s `P_SpawnPlayerMissile` shares, each a routine: `srcAbove` (25 B), `seeTarget` (76 B), `thSpeed` (28 B), `angleMom` (159 B, with `speedMom` as its local `speed_mom`) |
| `src/native/game/missile/missile.inc` | the scratch block's bytes (`MSL_SRC`, `MSL_DEST`, `MSL_TH`, `MSL_AN`, `MSL_T`, `MSL_HT`, `MSL_HS`, `MSL_HA`, `MSL_SPD`, `MSL_CK`: 28 of 32 B), the group offsets and dirty bits, the layout asserts |
| `src/native/game/missile/mstest.s` | `ms_bulk`: `halfMom` on many inputs (the random check), in the driver's area; linked only into the part's own image (`MS_TEST=1`), as damage's `dtest.s` |
| `src/native/game/missile/part.mk`, `args.json` | the fragment (entries `P_SpawnMissile`, `checkMissile`, `halfMom`, `srcAbove`, `seeTarget`, `thSpeed`, `angleMom`); the inputs and outputs |
| `tools/native/gparts/missile.py` | the captures, the paths, the synthetic calls, the checkpoint on part `checkpos`'s run machinery (`checkpos.Prep`, `check_writes`, `outputs`, with the A:X result added), `halfMom`'s random check, the planted bugs, sizes, the placement of review 1's chain, `report.json` |
| `tests/test_native_game_missile.py` | the build and budget, the far-access check, review 1's placement, the sampled checkpoint (every 2nd chosen call and the synthetic calls, `$A5`, `f121`), the random check; with `DOOM_GS_FULL=1` every chosen call on both profiles, the paths taken, the planted bugs. About 25 s by default, 170 s with `DOOM_GS_FULL=1` |

No local stand-in: every callee is built (`spawnXYZ`, `ticsNoise`: spawn; `P_TryMove`: trymove; `P_ExplodeMissile`: mobjstate; `P_DamageMobj` under `P_TryMove`: damage; `mo_get`, `mi_get`, `g_random`, `S_StartSound`: the core; `pta3`, `aproxdist`, `finesine`, `finecosine`: `math-g.o`; `fixmulang`, `sdiv32`: `math-r.o`).

### 1.2 How the native code follows upstream

- **`P_SpawnMissile`** [R `p_spawn65.s:533-633`], in upstream's order: `srcAbove` (the source's x, y and z + 32.0 into `GA_X`..`GA_Z`), `spawnXYZ` (the type in A), `seeTarget`, the angle `pta3(dest - source)`, the shadow noise, `angleMom`, then `dist = aproxdist(dest - source) / speed` by `sdiv32` (upstream's `_Div32`: C's truncation), at least 1 (a quotient whose high word is negative or a zero quotient becomes 1 [R `:578-586`]), then `momz = (dest->z - source->z) / dist` by `sdiv32` [R `:587-614`]. The missile stays on the stack over `checkMissile` and is the result (A:X), as upstream keeps it there [R `:621-633`].
- **The shadow noise** [R `:556-570`]: `t = P_Random()`, then `t - P_Random()` as a 16-bit value, shifted left 4 and added to the angle's high word (upstream's `<< 20`), only when the destination's flags have `MF_SHADOW` (group B, byte 2).
- **`angleMom`** [R `:812-845`]: the angle into `TH_ANGLO`, `TH_ANG`; the index is the high word `>> 3`; `momx = fixmulang(speed, finecosine[i])`, `momy = fixmulang(speed, finesine[i])` (upstream's `FixedMulAngle(X:C = speed, _Dp = the sine)`: `M_A` the speed, `M_B` the sine). Upstream's `speedMom` reads the speed again for each; natively `angleMom` reads it once (`thSpeed`), the same value.
- **`checkMissile`** [R `:850-890`]: `ticsNoise` first (its `P_Random`), then `halfMom` for x, y, z, then for a missile (`MF_MISSILE`, group B byte 2) `P_TryMove(th, x, y)` with th on the stack, and `P_ExplodeMissile` when the move is refused. It takes the missile in A:X (upstream's `SP_TH`), so part `wfire` calls it the same way.
- **`halfMom`** [R `:893-912`]: `x += mom >> 1` with an arithmetic shift of the 32-bit momentum and a 32-bit sum, on the mobj's cache line (`GC_MP`); X and Y are the line offsets of the coordinate and the momentum, as upstream's X and Y are the record's.

### 1.3 The native interfaces (for the callers: parts `chase` and `wfire`, wave 6)

| Routine | In | Out |
| --- | --- | --- |
| `P_SpawnMissile` | `GA_0-1` the source, `GA_2-3` the destination (handles), A the type | A:X the missile; changes `GA_*`, `GT_*`, `GS_*`, the math block |
| `checkMissile` | A:X the missile | nothing |
| `srcAbove` | A:X a mobj | `GA_X`, `GA_Y`, `GA_Z` = its x, y, z + 32 * FRACUNIT (`spawnXYZ`'s place) |
| `seeTarget` | A:X the missile, `GA_0-1` the source | its see sound (`S_StartSound`); its target = the source |
| `thSpeed` | A:X a mobj | `M_A` = `mobjinfo[its type].speed` (4 bytes): `wfire`'s `momz = FixedMul(speed, slope)` is `M_B` = the slope, `jsr fixmul` |
| `angleMom` | A:X the missile, `GA_0-3` the angle | its angle; momx, momy by the angle at its type's speed |
| `halfMom` | `GC_MP` a mobj's line (`mo_get`), X the coordinate's line offset, Y the momentum's | the coordinate += momentum >> 1; the caller marks the line dirty |

## 2. Requests

Each is a change to a shared file, for the wave's integrator. No stand-in waits on them: the part builds and passes as it is.

**R1. The helpers with no code of their own (`glayout.INLINED`).** What: add to `INLINED` in `tools/native/glayout.py`:

    # wave 5 as integrated: P_SpawnMissile's argument loader srcArg has no
    # code, and destDelta and speedMom are local code of their only
    # callers, P_SpawnMissile and angleMom (missile.md R1)
    'missile': ('p_spawn65.s:srcArg', 'p_spawn65.s:destDelta',
                'p_spawn65.s:speedMom'),

Why: `srcArg` copies `SP_SRC` to `_Dp` [R `p_spawn65.s:714-718`]: natively the source is a handle in the scratch block, so it has no code. Only `P_SpawnMissile` calls `destDelta` [R `:551`, `:572`], and only `angleMom` calls `speedMom` [R `:834`, falling into it at `:837`]. Natively they are local labels (`delta`, `speed_mom`). Today's `gplace.inc` gives `srcArg` and `destDelta` group 17 and `speedMom` group 5, none of them used. Other parts: none. `srcAbove`, `seeTarget`, `thSpeed` and `angleMom` stay routines, because `wfire`'s `P_SpawnPlayerMissile` calls them [R `:676-688`]; `halfMom` stays a routine for its random check (and `checkMissile` reaches it from both spawners).

**R2. Placement (`gplace.py` `AFFINITY`).** What: one unit for the spawners and their helpers:

    # the missiles' spawners and the helpers they share (missile.md R2)
    ('p_spawn65.s:P_SpawnMissile', 'p_spawn65.s:srcAbove',
     'p_spawn65.s:seeTarget', 'p_spawn65.s:thSpeed',
     'p_spawn65.s:angleMom', 'p_spawn65.s:halfMom',
     'p_spawn65.s:P_SpawnPlayerMissile'),

Why: today's placement puts `P_SpawnMissile` and `halfMom` in group 20 (slot 1) and `srcAbove`, `seeTarget`, `thSpeed`, `angleMom` in group 17, also slot 1. Each of `P_SpawnMissile`'s four calls of them loads group 17 over its own group, and `fc_call` loads group 20 back on the return. Measured in routine mode on `f121`: `P_SpawnMissile` takes 1,766,119 cycles at the median with the helpers in group 17, and took 963,727 when they were local code in group 20 (the part's first build, before they became routines for `wfire`). The bytes are measured, not the estimates: `P_SpawnMissile` 381 B (estimate 294), `halfMom` 45 B (48), `srcAbove` 25 B (44), `seeTarget` 76 B (52), `thSpeed` 28 B (40), `angleMom` 159 B (52). The unit is 714 B without `P_SpawnPlayerMissile` (wfire). `checkMissile` (106 B, estimate 113) can stay in group 10 with `checkPos`; its three `halfMom` calls find group 20 resident when `P_SpawnMissile` (or `P_SpawnPlayerMissile`) is the caller. Other parts: placement only. Group 20's other members (`checkThing`, the puffs, `P_ExplodeMissile`, ...) may have to move if the unit does not fit beside them (`gplace.py --measure`).

**R3. `OWN_STACK`.** What: `glayout.OWN_STACK['p_spawn65.s:P_SpawnMissile'] = 2` and `glayout.OWN_STACK['p_spawn65.s:checkMissile'] = 2`. Why: `P_SpawnMissile` keeps the missile (2 B) on the stack over `checkMissile`, and `checkMissile` keeps it over `P_TryMove`, as upstream does [R `p_spawn65.s:624-629`, `:870-881`], because `P_TryMove` runs game logic. Measured: the lowest S of every run is `$B2` for `P_SpawnMissile` (the damage call: `P_TryMove`, `checkPos`, `checkThing`, `P_DamageMobj` under it, with the driver's frame) and `$C7` for `checkMissile`. Other parts: `gcallgraph.py --stack`'s bound grows by at most 4 B on the chains through `A_TroopAttack` and the other monster attacks.

**R4. The interfaces (`src/native/game/README.md` "The parts' interfaces").** What: the rows of 1.3 above:

    | `P_SpawnMissile` (`missile`) | `GA_0-1` the source, `GA_2-3` the destination, A the type | A:X the missile; changes `GA_*`, `GT_*`, `GS_*`, the math block |
    | `checkMissile` (`missile`) | A:X the missile | nothing |
    | `srcAbove`, `seeTarget`, `thSpeed`, `angleMom` (`missile`) | A:X a mobj; `seeTarget` also `GA_0-1` the source, `angleMom` `GA_0-3` the angle | `GA_X`..`GA_Z` = its x, y, z + 32.0; its see sound and target; `M_A` = its type's speed; its angle, momx, momy |
    | `halfMom` (`missile`) | `GC_MP` the mobj's line, X the coordinate's offset, Y the momentum's | the coordinate += momentum >> 1 (the caller marks the line dirty) |

Why: part `chase` (wave 6) calls `P_SpawnMissile` from its `spawnMissile` [R `p_enemy65.s:1877-1883`], and part `wfire` (wave 6) builds `P_SpawnPlayerMissile` from `srcAbove`, `spawnXYZ`, `seeTarget`, `angleMom`, `thSpeed` and `checkMissile` [R `p_spawn65.s:676-697`]. Other parts: those callers use these conventions.

**Budget.** 820 B against 800 (2.5% over, under the 10% that needs a request): the four shared helpers are routines of their own (their `rts`, their arguments and `FCALL`s), where upstream's `jsr .kbank` helpers share `_Dp` and the near scratch.

**Exclusions.** None new: R1-R7 of GAME.md 3.5 only.

**Arithmetic helpers (GAME.md 2.4).** `halfMom` is arithmetic (upstream's own 32-bit arithmetic shift and sum): it has its random check (3). `speedMom` is not: it is milestone 6's `FixedMulAngle` (`fixmulang`, whose random check is milestone 6's) on the speed and a sine, with no arithmetic of its own.

## 3. Results

Lean checks (the owner's request of 2026-10-02): the `$A5` machine only, at most 40 calls an entry chosen to cover the candidates' paths, under `f121` and `fastpath`; 3 planted bugs.

**The candidates.** `python3 tools/native/gparts/missile.py --capture` made every call of both entries in demo3, DEMO1 and DEMO2 into a case (76 each, every one eligible: no call reaches a dispatch target), in about 2 minutes. newgame and the tour fire no monster missile. Their paths, from the reference alone (`path_of`, whose model of `dist` and `momz` equals upstream's `momz` on all 76):

| Path | Candidates |
| --- | ---: |
| type 9 (`MT_TROOPSHOT`), with its see sound | 76 |
| a shadow destination | 1 |
| `momz` 0 | 51 |
| `momz` negative / of them inexact (where the rounding shows) | 20 / 19 |
| `momz` positive, inexact | 5 |
| moved | 76 |

The chosen calls: 40 of each entry (a greedy cover of these paths, then spread evenly).

**The synthetic calls** (`P_SpawnMissile`, upstream's routine run by `ref816 --call` on demo3's first call's memory with pokes; DEMO1's for a second shadow call):

| Call | Pokes | Paths |
| --- | --- | --- |
| wall | the source onto the middle of the one-sided line nearest it | the missile spawned inside the wall, the move refused, exploded |
| damage | the source 20 units east of the destination and 13 units + 1/65536 above it | `momz` negative and inexact, the missile into the player: `PIT_CheckThing` calls `P_DamageMobj`, exploded |
| close | the source 6 units north of the destination | `dist` clamped at 1, damage, exploded |
| shadow (2) | the destination's flags + `MF_SHADOW` | the angle's noise |

**Review 1's chain** (GAME.md 3.4): the part's image takes the integrator's placement (`shared/placement.json`): `P_SpawnMissile` group 20 in slot 1, `checkMissile` group 10 in slot 2, `P_TryMove` group 8 in slot 1, `checkPos` group 10, `checkThing` group 20 in slot 1, `P_DamageMobj` group 1 in slot 2. The damage and close calls run that chain: `P_DamageMobj` is paged into `checkMissile`'s slot, and each slot is restored on the way back. Both are equal to the reference (and the test checks the placement still gives that chain).

**The checkpoint** (`python3 tools/native/gparts/missile.py --check --jobs 2`, 39 s):

| Entry | Cases | Runs | Failures | Stray writes | Lowest S | Cycles median / worst, `f121` | `fastpath` |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `P_SpawnMissile` | 40 + 5 synthetic | 90 | 0 | 0 | `$B2` | 1,766,119 / 2,854,972 | 1,330,256 / 2,167,576 |
| `checkMissile` | 40 | 80 | 0 | 0 | `$C7` | 866,856 / 1,945,864 | 650,492 / 1,474,290 |

Every run's canonical state equals `ref816`'s with R1-R7 only, the declared output (the missile in A:X, as a mobj) equals upstream's X:C, and no call waits or is undecodable. The cycles are routine mode's: every slot empty at the call, so most of them are group loads (R2).

**Branches no chosen call takes:** `checkMissile`'s "not a missile" exit (both spawners make missiles); `seeTarget`'s "no see sound" (every missile type has one); the quotient `aproxdist / speed` negative (impossible: both are positive); missile types other than `MT_TROOPSHOT` (the baron's is E1M8's, which no demo reaches). `checkMissile` as an entry is only ever moved in the demos; its explosion and the damage are run through `P_SpawnMissile`'s synthetic calls.

**`halfMom`'s random check** (`--random`): 100,000 inputs (all 400 pairs of 20 edge values: 0, ±1, ±2, ±3, the extremes, the word and half-word boundaries, ±10.0; then random words, momentum-like values and small ones), upstream's `halfMom` by `mathref batch` on a captured `checkMissile` call's machine against the native one (`ms_bulk`): 0 different, and upstream equals the model `x + (mom >> 1)` on all of them.

**The planted bugs** (`--plants`, each in a scratch copy, on the chosen and synthetic calls, `$A5`, `f121`):

| Bug | Caught by |
| --- | --- |
| `momz` rounded the other way (floored) | 12 of 85 runs fail: `mobj.momz` -73,400 against -73,401 (the negative inexact calls) |
| the shadow `P_Random` taken for a visible target | 42 of 85: `prndindex` and the missile's angle |
| the tics noise skipped | 85 of 85: `prndindex` and the missile's tics |

**Sizes**: 820 B of 800 (`GGRP20` 426, `GGRP17` 288, `GGRP10` 106; `mstest.s`, 122 B, is the part image's driver area only).

**`build/` growth**: 36 MB (`build/native/game/missile/`: 15 MB of cases, the image, the reports). Every temporary directory was deleted.

## 4. Open points

- (Wave 2 as integrated) `spawnXYZ` (part `spawn`) takes the type in A and the place in `GA_X`..`GA_Z`, and returns the slot in A:X; `ticsNoise` takes A:X a mobj (`spawn.md`). `R_PointToAngle3` and the sines are resident (`math-g.o`).
- (Wave 3 as integrated) `P_AproxDistance` is the core's `aproxdist` (math-g.o, `look.md` request 2).
- (Wave 4 as integrated) `P_TryMove` (part `trymove`): `GA_0-1` the thing, `GA_2-5` x, `GA_6-9` y; A = 1 and C set moved, 0 and C clear not; a refused move leaves `GM_NSPEC`, `GM_SPECHIT` as `checkPos` left them (`trymove.md` R4). The core's `P_CreateSecNodeList` (`gp_secnodes`) now leaves `GM_TMX`, `GM_TMY` = its thing's x, y, as upstream's (`teleport.md` R4). `P_TryMove` shares a group with `P_XYMovement` (`gplace.AFFINITY`, `trymove.md` R3).
- (missile) Group 10 (`checkPos`'s) had 3 B to spare in the wave-4 placement; `checkMissile` came out at 106 B against its 113 B estimate, so it fits. The first build (117 B) overflowed it by 1 B.
- (missile) No run fires a baron's missile, a rocket (`P_SpawnPlayerMissile`: part `wfire`) or a missile at a spectre; the one natural shadow destination in DEMO1 and the two synthetic ones cover the shadow branch.
- (missile, for `wfire`) `P_SpawnPlayerMissile` takes `srcAbove`, `seeTarget`, `angleMom`, `thSpeed` and `checkMissile` as 1.3 gives them. `seeTarget` and `angleMom` use the scratch block's `MSL_HT`, `MSL_HS`, `MSL_HA`, `MSL_SPD`, which no caller needs to keep.

## 5. The integration of wave 5 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 5 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 `INLINED['missile']` | **Accepted** as written |
| R2 the placement | **Accepted**: the unit in `gplace.AFFINITY` (with wfire's `P_SpawnPlayerMissile` at its estimate). Measured placement: group 8 (slot 1, 1,958 B, with `checkThing`, `P_ExplodeMissile`, the puffs and spawns); `checkMissile` group 9 (slot 2, `checkPos`'s); `P_DamageMobj` group 16, also slot 2, so the test's review-1 case still pages it into `checkMissile`'s slot |
| R3 `OWN_STACK` | **Accepted** as written |
| R4 the interfaces | **Accepted**: README "The parts' interfaces" (the four rows); `wfire.md`, `chase.md` noted |
