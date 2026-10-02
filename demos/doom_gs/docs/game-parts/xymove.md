# Part `xymove` (wave 5)

The record of milestone 10's part `xymove` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 5; upstream 2367 B, native budget 3100 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 5's `xymove` (2026-10-02, under the lean checks the owner asked for that day).
- Files: `src/native/game/xymove/*.s`, `src/native/game/xymove/part.mk`, `src/native/game/xymove/args.json`, `tests/test_native_game_xymove.py`, this file; tools (if any) `tools/native/gparts/xymove*.py`; build output `build/native/game/xymove/` (`make -s -C src/native -f game.mk part P=xymove ROOT=$PWD`).
- Its scratch block: `SB_XYMOVE` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_mobj65.s`: `P_XYMovement:1273` (the half steps of a big move, `P_TryMove`, the slide for the player, a missile into the sky or a wall, friction and the stop), `slideMove:67` (`P_SlideMove`: the three traces, `PTR_SlideTraverse:458`, `hitSlideLine:586`); helpers `clampMove`, `isBig`, `wholeMove`, `halfMove`, `skyHit`, `quarterOut`, `slow`, `frictionAP`, `frictionNear`, `friction`, `corners`, `slideTrace`, `bestMul`, `addCoord`, `bobClip`, `labs`

Its checkpoint (GAME.md 2.4): `P_XYMovement` (DEMO1 7,214: 600 by path, every slide)

Its planted bugs (each must fail the named check): friction in the air; the second trace from the other corner; a missile's sky test without the ceiling pic; the half steps' y before x

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_mobj65.s:P_XYMovement` | `P_XYMovement` | demo3 3248, demo1 7214, demo2 4015, newgame 287, tour 70 |
| `p_mobj65.s:slideMove` | `slideMove` | demo3 244, demo1 1383, demo2 1358, newgame 47, tour 0 |
| `p_mobj65.s:PTR_SlideTraverse` | `PTR_SlideTraverse` | demo3 474, demo1 2395, demo2 4043, newgame 49, tour 0 |
| `p_mobj65.s:hitSlideLine` | `hitSlideLine` | demo3 186, demo1 1153, demo2 1740, newgame 41, tour 0 |

Helpers: `p_mobj65.s:clampMove`, `p_mobj65.s:isBig`, `p_mobj65.s:wholeMove`, `p_mobj65.s:halfMove`, `p_mobj65.s:skyHit`, `p_mobj65.s:quarterOut`, `p_mobj65.s:slow`, `p_mobj65.s:frictionAP`, `p_mobj65.s:frictionNear`, `p_mobj65.s:friction`, `p_mobj65.s:corners`, `p_mobj65.s:slideTrace`, `p_mobj65.s:bestMul`, `p_mobj65.s:addCoord`, `p_mobj65.s:bobClip`, `p_mobj65.s:labs`.

### 1.1 What was built

| File | What |
| --- | --- |
| `src/native/game/xymove/xymove.s` | `P_XYMovement` (750 B) with `isBig`, `wholeMove`, `halfMove` done in place (local `jsr`s: `big`, `whole`, `half`); the routines `clampMove`, `skyHit`, `quarterOut` (227 B together), `slow`, `frictionAP`, `frictionNear` (134 B), `friction` (84 B) |
| `src/native/game/xymove/slide.s` | `slideMove` (580 B, with the stairstep and `addCoord` in place); `slideTrace` with `corners` in place and `bobClip` (304 B); `bestMul` (27 B), `labs` (30 B); `PTR_SlideTraverse` (`TRVTAB` 3, with `blocking` in place) and `hitSlideLine` (652 B together) |
| `src/native/game/xymove/xymove.inc` | the scratch block's bytes (`XY_MO`, `XY_PL`, `XY_XM`, `XY_HIT`, `XY_BEST`, `XY_LINE`, `XY_TM`, with `XY_FRAC`, `XY_LI` over `XY_TM`: 26 of 32 B), the group offsets and dirty bits, the sky's pic stand-in (R3), the layout asserts |
| `src/native/game/xymove/xytest.s` | test only (`XY_TEST=1`, the driver's area, 189 B): `xy_bulk`, the helpers' random checks |
| `src/native/game/xymove/part.mk`, `args.json` | the fragment; the inputs of `P_XYMovement` and `slideMove` (the mobj in A:X; no outputs: upstream's `MV_*`, `SL_*`, `HS_*` are its near scratch, R2) |
| `tools/native/gparts/xymove.py` | the candidates, captures and paths; the synthetic big moves; the checkpoint on part `checkpos`'s run machinery (`checkpos.Prep`, `run_one`); the random checks (`sight.mathref` against `xy_bulk`); the planted bugs; sizes; `report.json` |
| `tests/test_native_game_xymove.py` | the build and budget, the far-access check, the sampled checkpoint (every 4th chosen call, `$A5`, `f121`), the random checks (100,000 inputs a helper): 18 s; with `DOOM_GS_FULL=1` every chosen call on both profiles, the paths taken, the planted bugs: 130 s |

No local stand-in calls a routine: every callee is built (`P_TryMove`: trymove; `P_PathTraverse`: path; `P_PointOnLineSide`, `P_LineOpening`: geom; `P_RemoveMobj`, `explode`, `P_SetMobjState`: mobjstate; the object API, `I_Error`, milestone 6's `umul16`, `fixmul`, `fixmulang`, `pta3`, `aproxdist`, `finesine`, `finecosine`: the core). The one stand-in is a constant, `XY_SKYPIC` (R3).

### 1.2 How the native code follows upstream

- **The routines and their helpers.** Each upstream helper that the placement gives a group of its own (`gplace.inc`: `clampMove`, `skyHit`, `quarterOut` group 3; `slow`, `frictionAP`, `frictionNear`, `labs` 18; `friction` 27; `slideTrace`, `bobClip`, `bestMul` 7) is a `ROUTINE` of that name, reached by `FCALL`, so the part links with the shared placement: with them in place, group 8 (`P_TryMove`, `P_XYMovement`, `slideMove`) overflowed by 533 B. `isBig`, `wholeMove`, `halfMove` (P_XYMovement's), `corners` (slideTrace's) and `addCoord` (slideMove's) are done in place under other names (R2). Each routine has its own local helpers (`xm_mo`, `ld4`, `slt` and so on), since the placement may put them apart.
- **The scratch.** Upstream's near scratch becomes the scratch block (26 B). The corners (`SL_LEAD`, `SL_TRAIL`) are not kept: each trace makes its start from the mobj (x, y, radius and the momentum's signs), which no trace changes. `PTR_SlideTraverse`'s frac and line (`SL_FRAC`, `SL_LI`) share bytes with `tmxmove`, `tmymove`, which no trace sees live. `hitSlideLine`'s angles and lengths are `GT_0-11` (only milestone 6's math runs between them, which keeps to the math block); the side is on the stack across `R_PointToAngle3`, as upstream's.
- **P_XYMovement** [R `p_mobj65.s:1273-1529`], in upstream's order: no momentum, nothing (upstream's early `rtl`). The kind plane's `CLEAN` off (GAME.md 1.2: the momentum changes; upstream's own code needs no `CLEARCLEAN` here, since a mobj with momentum is never clean, so this only keeps the native rule). `XY_PL`, the clamp (`clampMove`: above `$001E0000` 30.0, below `$FFE20000` -30.0), `xmove`, `ymove`. The loop: the half steps when either move is above `$000F0000` or below `$FFF10000` (`isBig`), with `halfMove`'s C rounding (a negative move + 1, then `>> 1`) for the try and the move's arithmetic `>>= 1`; else the whole move. `P_TryMove(mo, ptryx, ptryy)` (`GA_0-1`, `GA_2-5`, `GA_6-9`). Refused: the player slides; a missile goes into the sky (`skyHit`: `G_CEILLINE` not none, its `LN_SIDE1` not none, its back sector (LVS's `LNSECB`) with the sky's ceiling pic and its ceiling below the missile's z, signed) through `P_RemoveMobj` and the end, else `explode`; anything else stops (`momx = momy = 0`), the loop going on with `xmove`, `ymove` as upstream's. Then: a missile ends; a mobj in the air (`floorz < z`, signed) ends; a corpse with a momentum beyond `FRACUNIT / 4` (`quarterOut`) on a floor that is not its subsector's sector's floor ends; a momentum below `STOPSPEED` both ways (`slow`) stops, for the player only with no `forwardmove` nor `sidemove`, its state set to `S_PLAY` when it is one of `S_PLAY_RUN1`..`+3` (the state number, upstream's pointer difference) and its own momentum 0; else friction on `momx`, `momy` and the player's.
- **friction** [R `p_mobj65.s:1180-1206`]: `((lo × $E800) >> 16) + hi × $E800` with `hi × $E800` from `umul16` less `$E800 << 16` for a negative hi, upstream's two products.
- **slideMove** [R `:67-260`]: the hitcount 3, bestslidefrac `$00010001`, the three traces in upstream's order (lead x and y; trail x, lead y; lead x, trail y), the stairstep when nothing hit, the move up to the wall when `bestslidefrac - $800 > 0` (`FixedMul` by `bestMul`), the rest `$F800 - it` clamped to `FRACUNIT`, `tmxmove`, `tmymove`, `hitSlideLine`, `momx`, `momy` = them, `bobClip` for the player (a signed compare of the two `labs`), `P_TryMove(x + tmxmove, y + tmymove)`, refused: again. The mobj's fields are read again where upstream reads them (a `P_TryMove` may change them).
- **PTR_SlideTraverse** [R `:458-580`]: `TRVTAB`'s convention (`GA_0` the intercept's index; C set to go on). A thing is `I_Error` (upstream's "not a line?"). One-sided: blocks unless `P_PointOnLineSide` says 1; two-sided: `P_LineOpening`, then `openrange < height`, `opentop - z < height`, `24.0 < openbottom - z` (signed), as upstream. A blocking line nearer than the best (signed) becomes the best; then stop.
- **hitSlideLine** [R `:586-709`]: dy 0 or dx 0 first, then the side, `pta3(dx << 16, dy << 16)` (+ ANG180 on side 1), `pta3(tm)` + 10 - lineangle, `aproxdist(tm)`, the flip above ANG180 (unsigned), and the three `FixedMulAngle` (`fixmulang`) with `finecosine`, `finecosine`, `finesine` of the angle's high word `>> 3`.

## 2. Requests

**R1** (`tools/native/gplace.py` `AFFINITY`; the placement). What: three units, so that a move pages at most one group besides its own:

    # part xymove (xymove.md R1): the move's helpers, one group of the
    # slot P_XYMovement's group is not in (each move with momentum on a
    # floor calls slow, frictionAP and friction; clampMove every move)
    ('p_mobj65.s:clampMove', 'p_mobj65.s:slow', 'p_mobj65.s:frictionAP',
     'p_mobj65.s:frictionNear', 'p_mobj65.s:friction',
     'p_mobj65.s:quarterOut', 'p_mobj65.s:skyHit'),
    # the player's slide: its traces and clip with their traverser
    ('p_mobj65.s:slideTrace', 'p_mobj65.s:bobClip', 'p_mobj65.s:bestMul',
     'p_mobj65.s:labs', 'p_mobj65.s:PTR_SlideTraverse',
     'p_mobj65.s:hitSlideLine'),

and `slideMove` with `P_XYMovement` and `P_TryMove` as now (the existing unit `('p_mobj65.s:P_XYMovement', 'p_map65.s:P_TryMove')` plus `'p_mobj65.s:slideMove'`). Why: the wave-4 placement, made from estimates, spreads the helpers over groups 3, 7, 18 and 27 (all slot 2): each moving mobj on its floor takes `clampMove` (3), `slow` and `frictionAP` (18) and `friction` (27), three loads of slot 2 a call (measured sizes: the move's helper unit 445 B, the slide unit 1,023 B; `P_XYMovement` 750 B, `slideMove` 580 B). What it changes for others: group 8 is 2,046 of 2,048 B in this part's image (`P_TryMove` 716, `P_XYMovement` 750, `slideMove` 580), and the placement also puts part `attack`'s `p_attack65.s:opening` there, so group 8 overflows once `attack` is merged: the wave-5 placement must be remade with the measured sizes in any case. `PTR_SlideTraverse` and `hitSlideLine` then leave group 16 (geom's `P_LineOpening` group), which `PTR_SlideTraverse` FCALLs once a crossed two-sided line.

**R2** (`tools/native/glayout.py` `INLINED`). What: `'xymove': ('p_mobj65.s:isBig', 'p_mobj65.s:wholeMove', 'p_mobj65.s:halfMove', 'p_mobj65.s:corners', 'p_mobj65.s:addCoord')`. Why: done in place (local helpers named `big`, `whole`, `half`, `corner`, `sm_add`), so they have no code under their names. Others: none.

**R3** (a shared name for the sky's ceiling pic). What: a constant in a generated include (e.g. `lgame.inc` `SKY_PIC = $FE` from `tools/native/levelconv.py`'s `SKY_PIC`). Why: `skyHit` compares the back sector's `SEC_CPIC` with upstream's `skyflatnum` (-2, the converted byte `$FE`: `levelconv.pic_byte`); the frame block's `SKYFLAT` is a render input, not set in the tic phase. Stand-in: `XY_SKYPIC = $FE` in `xymove.inc`. Others: part `attack` (a shot into the sky, `p_attack65.s`) compares the same pic.

**R4** (`tools/native/glayout.py` `OWN_STACK`). What: `'p_mobj65.s:slideMove': 2` (the return address of the local `sm_try` under its `FCALL P_TryMove`), `'p_mobj65.s:frictionAP': 1`, `'p_mobj65.s:frictionNear': 1`, `'p_mobj65.s:bobClip': 1` (the offset or axis pushed across `FCALL friction` or `FCALL labs`), `'p_mobj65.s:hitSlideLine': 1` (the side across `pta3`). Why: `gcallgraph.py --stack`'s count. The lowest S measured in the checkpoint: 186 (`P_XYMovement`), 197 (`slideMove`).

No exclusion beyond R1-R7 is needed.

## 3. Results

Lean checks (2026-10-02). Commands:

- `make -s -C src/native -f game.mk part P=xymove ROOT=$PWD XY_TEST=1` (no warnings; the image links the twenty parts of waves 1-4 and this one)
- `python3 tools/native/gparts/xymove.py --capture --jobs 2` (376 cases, 23 MB: P_XYMovement 301 candidates over demo3, DEMO1, DEMO2, newgame; slideMove 75)
- `python3 tools/native/gparts/xymove.py --check --jobs 2 --profiles f121,fastpath`
- `python3 tools/native/gparts/xymove.py --random --count 100000`
- `python3 tools/native/gparts/xymove.py --plants --jobs 2`
- `python3 -m unittest tests.test_native_game_xymove` (7 tests, 2 skipped, 18 s); with `DOOM_GS_FULL=1` 7 tests OK, 130 s

**Checkpoint** (routine mode, `$A5`, both profiles; every call eligible: no dispatch target waits):

| Entry | Eligible | Run | Runs | Failures | Strays | f121 median / worst | fastpath median / worst | Lowest S |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `P_XYMovement` | 14,834 | 40 captured + 11 synthetic | 102 | 0 | 0 | 3,253,667 / 36,183,538 | 2,459,275 / 27,416,773 | 186 |
| `slideMove` | 3,032 | 40 | 80 | 0 | 0 | 7,593,570 / 16,115,481 | 5,764,407 / 12,258,630 | 197 |

(Cycles: fabric clocks from the entry to the return, every slot empty at the call, as the other parts' reports.) Paths run: P_XYMovement the player, things, corpses and missiles; slides with and without a hit (PTR_SlideTraverse, PIT_AddLineIntercepts reached), a crossed line's handler (`lnPlat`, `lnFloor`), `A_Lower`; a missile exploded; stopped; friction; in the air; not moved. Synthetic (no candidate moves faster than MAXMOVE / 2): the half steps (odd negative moves) and the clamp of the player's mobj on three bases and the half steps of two missiles in flight, upstream's routine run alone on the poked memory (`gamecap.call_case`). slideMove: one and two turns, nothing hit (the stairstep), slid along axis and angled lines, moved and not, the bob clipped on x and on y.

**Random checks** (100,000 inputs each, the edges first; upstream's helper by mathref on a slideMove case's machine against `xy_bulk`): `friction` 0 different, `bestMul` 0, `labs` 0; upstream equals the Python model of each on all inputs.

**Planted bugs** (lean: 3), each caught by the checkpoint: friction in the air (1 of 51 runs fails: momx, momy); the second trace from the other corner, trail x with trail y (5 of 40: `LR_LINES`, validcount); a negative half step rounded down instead of toward 0 (6 of 51: the synthetic runs' y). GAME.md's "the half steps' y before x" cannot fail natively: each axis's half step is computed apart into its own `GA_*` before the one `P_TryMove`, as upstream's, so their order changes nothing; the rounding is the plant of that code instead. "A missile's sky test without the ceiling pic" was not planted (lean: three; no captured missile meets a ceiling line whose back ceiling is below it).

**Sizes** (`xymove.py` `sizes()` from the part's map): 2,761 of 3,100 B (upstream 2,367): `P_XYMovement` 750, `slideMove` 580, `PTR_SlideTraverse` + `hitSlideLine` 652, `slideTrace` + `bobClip` 304, `clampMove` + `skyHit` + `quarterOut` 227, `slow` + `frictionAP` + `frictionNear` 134, `friction` 84, `labs` 30, `bestMul` 27; test-only `xy_bulk` 189 B in the driver's area. Group 8 2,046 of 2,048 B (R1).

**build/ growth**: `build/native/game/xymove/` 45 MB (the cases 23 MB, the image and its listings); no temporary directory left.

## 4. Open points

- (Wave 2 as integrated) `p_mobj_isPlayer` (part `spawn`): A:X a mobj, A 1 / 0. The slide's traces use the shared trace state `GM_*` (`tracel.md` R1); `R_PointToAngle3` and the sines are resident (`math-g.o`).
- (Wave 3 as integrated) `P_AproxDistance` is the core's `aproxdist` (math-g.o, `look.md` request 2).
- (Wave 4 as integrated) `P_PathTraverse` (part `path`): `GA_0-3` x1, `GA_4-7` y1, `GA_8-11` x2, `GA_12-15` y2, `GA_16` the flags, `GA_17` the traverser's `TRVTAB_<label>`; A = 1 and C set (true), 0 and C clear. A `TRVTAB` traverser takes the intercept's index in `GA_0` (`ICPT` + 6 × it: frac 4, what 2) and returns C set to go on, clear to stop (`path.md` R2, README `DCALL`); the walk's state is in `SB_PATH`, so a traverser's own state is its part's scratch block.
- (Wave 4 as integrated) `P_TryMove` (part `trymove`): `GA_0-1` the thing, `GA_2-5` x, `GA_6-9` y; A = 1 and C set moved, 0 and C clear not; a refused move leaves `GM_NSPEC`, `GM_SPECHIT` as `checkPos` left them (`trymove.md` R4). The core's `P_CreateSecNodeList` (`gp_secnodes`) now leaves `GM_TMX`, `GM_TMY` = its thing's x, y, as upstream's (`teleport.md` R4). `P_TryMove` shares a group with `P_XYMovement` (`gplace.AFFINITY`, `trymove.md` R3).
- (xymove, 2026-10-02) Branches no checked call reaches: a missile into the sky (`skyHit` true, `P_RemoveMobj`: no candidate; the planted test of the ceiling pic not run), the player's stop back to `S_PLAY` (no candidate stops in a walking frame with no command), a corpse that goes on (`quarterOut` true with floorz above its sector's floor), `PTR_SlideTraverse`'s thing (`I_Error`), the clamp and the half steps only in synthetic calls. `PTR_SlideTraverse`'s and `hitSlideLine`'s own branches were not counted apart: they ran inside the 40 slides and the 84 + 12 sliding P_XYMovement candidates, but which of their branches (one- or two-sided lines, the back side, each opening test) ran was not recorded.
- (xymove) Only `$A5` (the lean checks); the sounds of a missile's explosion are not compared in routine mode (R6).
- (xymove) Group 8 is full (R1): the wave-5 integration must remake the placement with the measured sizes.

## 5. The integration of wave 5 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 5 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 the placement | **Accepted**: the helpers' and the slide's units, `slideMove` with `P_XYMovement` and `P_TryMove`. Measured placement: `P_XYMovement`, `P_TryMove`, `slideMove` group 2 (slot 1, 2,046 B), the helpers group 3 (slot 2, with path's walk and `P_MobjThinker`), the slide group 15 (slot 1, with player's use and `P_LineOpening`): **the slide is in the move's slot**, so a slide reloads group 2 on each of its returns (the model's cost of `slideMove` to `hitSlideLine` 0.21 ms a tic at the mean; with the other slot the whole placement cost more) |
| R2 `INLINED['xymove']` | **Accepted** as written |
| R3 `SKY_PIC` | **Accepted** (as `attack.md` R2): `xymove.inc`'s `XY_SKYPIC = SKY_PIC` |
| R4 `OWN_STACK` | **Accepted** as written |
