# Part `checkpos` (wave 3)

The record of milestone 10's part `checkpos` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 3; upstream 2019 B, native budget 2600 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 3's `checkpos` (built 2026-10-02, under the owner's lean checks of that day).
- Files: `src/native/game/checkpos/*.s` (`checkpos.s`, and its places `checkpos.inc`), `src/native/game/checkpos/part.mk`, `src/native/game/checkpos/args.json`, `tests/test_native_game_checkpos.py`, this file; tools (if any) `tools/native/gparts/checkpos*.py`; build output `build/native/game/checkpos/` (`make -s -C src/native -f game.mk part P=checkpos ROOT=$PWD`).
- Its scratch block: `SB_CHECKPOS` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_map65.s`: `P_CheckPosition:1198`, `checkPos:1383` (the box through `setBox:1253`, `setBoxL:1251`, `above:1335` (review 9), the point's floor and ceiling, the things' walk with `checkThing:2879` = `PIT_CheckThing`: missiles' damage with `P_Random`, pickups, solid things; the lines' walk `lineBlocks:1706` with `PIT_CheckLine`: the blocking flags, openings, `spechit` in order, the line record `LR_OK`, `LR_N`, `LR_LINES` for `mvNodes` in `lCross:1899` and the walk's end [R `:1850-1856`]), `walkRange:1045`, `loadRad:1209`, `cpCopy:1230`, `ps32:2040`

Its checkpoint (GAME.md 2.4): `P_CheckPosition` (demo3 590) and `checkPos` as an entry inside `P_TryMove` (300 by path); synthetic: things and lines at block corners where the order shows (as milestone 9's `secorder.py`), three special lines crossed in one box, a box crossing more than 24 lines (`LR_N` `$FF`); outputs `tmfloorz`, `tmceilingz`, `tmdropoffz`, `spechit` and the line record compared (2.4 "Inputs and outputs")

Its planted bugs (each must fail the named check): the block walk with y outer (the corner cases: milestone 9's gate "the block walk's order on every move"); things before lines; `spechit` in reverse; a missile's damage `P_Random` order; the line record not kept

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_map65.s:P_CheckPosition` | `P_CheckPosition` | demo3 590, demo1 48, demo2 280, newgame 0, tour 0 |
| `p_map65.s:checkPos` | `checkPos` | demo3 26245, demo1 21665, demo2 9102, newgame 592, tour 70 |
| `p_map65.s:setBox` | `setBox` | demo3 28630, demo1 25661, demo2 10889, newgame 766, tour 2015 |
| `p_map65.s:setBoxL` | `setBoxL` | demo3 2385, demo1 3996, demo2 1787, newgame 174, tour 1945 |
| `p_map65.s:above` | `above` | demo3 0, demo1 0, demo2 82, newgame 0, tour 0 |
| `p_map65.s:checkThing` | `checkThing` | demo3 101, demo1 269, demo2 283, newgame 0, tour 1 |
| `p_map65.s:lineBlocks` | `lineBlocks` | demo3 25261, demo1 23492, demo2 10768, newgame 766, tour 2015 |
| `p_map65.s:lCross` | `lCross` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_map65.s:walkRange` | `walkRange` | demo3 49718, demo1 43452, demo2 19343, newgame 1279, tour 2085 |
| `p_map65.s:loadRad` | `loadRad` | demo3 101, demo1 269, demo2 283, newgame 0, tour 1 |
| `p_map65.s:cpCopy` | `cpCopy` | demo3 26245, demo1 21665, demo2 9102, newgame 592, tour 70 |
| `p_map65.s:ps32` | `ps32` | demo3 4451, demo1 2108, demo2 950, newgame 141, tour 0 |

Helpers: none.

## 2. Requests

**R1. Shared names for `p_map65.s`'s near scratch that `checkpos` writes and later parts read.** `tmthing`, `tmx`, `tmy` (cpCopy's; read by `trymove` after `checkPos` and when `MP_CLOB` is set [R `p_map65.s:340-352`, `:504-505`, `:590-601`]; written and read by `teleport` [R `p_map65.s:3420-3436`, stompThing]), `_g_tmbbox` (setBox's; `chasemove`'s `avoidDropoff` builds its own box there [R `p_enemy65.s:1482-1514`]), `_g_spechit` (PIT_CheckLine's; `trymove`'s `spec` [R `p_map65.s:921-937`] and `chasemove`'s `pMove` [R `p_enemy65.s:184-203`] read it, with `numspechit`, geom's `GM_NSPEC`), `MP_TRY` (P_TryMove sets it before `checkPos` [R `p_map65.s:334-336`]). What: add to `glayout.TIC_GW_FIELDS`, after `GM_ATRANGE` (35 of GW's 221 free bytes):

    ('GM_TMTHING', 2), ('GM_TMX', 4), ('GM_TMY', 4), ('GM_TMBBOX', 16),
    ('GM_SPECHIT', 8), ('GM_MPTRY', 1)

(`GM_TMBBOX` top, bottom, left, right in upstream's `UC_BOX*` order, fixed_t each; `GM_SPECHIT` 4 line numbers.) The part's stand-ins (`checkpos.inc`, marked) are the same fields at `CPG` = `$B3D0` in GW; the change is `CP_TMTHING = GM_TMTHING` ... in `checkpos.inc` (and `args.json`'s `cp:` places become `gw:`). Other parts: `trymove`, `teleport`, `chasemove` use the names.

**R2. Placement: one group (or the core) for the part.** The estimates put its seven routines in four groups (`P_CheckPosition`, `setBox` 8; `checkPos`, `cpCopy` 17; `walkRange`, `lineBlocks`, `checkThing` 4), so a check pages three groups (routine mode: 365k cycles at the median on `f121`, 912k at worst). What: `gplace.AFFINITY` += `('p_map65.s:P_CheckPosition', 'p_map65.s:checkPos', 'p_map65.s:cpCopy', 'p_map65.s:setBox', 'p_map65.s:walkRange', 'p_map65.s:lineBlocks', 'p_map65.s:checkThing')`: 2,206 B, over slot 2's 2,048, so either the core (`checkpos` is 8.8% of the hot set, GAME.md 0.3 fact 7; `P_TryMove` 11 calls a tic) or two groups: `checkThing` (365 B, cold: 101 calls in demo3) apart and the other six (1,841 B) together. Other parts: none (placement only).

**R3. `OWN_STACK['p_map65.s:checkPos'] = 12`.** The things' walk keeps its state (11 B: the blocks, the block's index, the row, the thing) and PIT_CheckThing's result (1 B) on the stack across `checkThing`, which can run any game logic (upstream keeps its walk frame there too [R `p_map65.s:1414-1424`, `:1574-1630`]). Measured lowest S 196 (`$01C4`) in the checkpoint.

**R4. `glayout.INLINED['checkpos'] = ('p_map65.s:setBoxL', 'p_map65.s:above', 'p_map65.s:lCross', 'p_map65.s:ps32', 'p_map65.s:loadRad')`.** No code of their own: `setBoxL` is upstream's JSL wrapper (its callers, `teleport`'s `P_TeleportMove` [R `p_map65.s:3447`], FCALL `setBox`; `P_CreateSecNodeList`'s box is gpos.s's own); `above` is only `boxOnLineSide`'s, which geom's `P_BoxOnLineSide` has inline (`@above`); `lCross` and `ps32` are `lineBlocks`'s code; `loadRad` is done in place after `checkThing`.

**R5. The interfaces (for README "The parts' interfaces").**

| Routine | In | Out |
| --- | --- | --- |
| `P_CheckPosition` | `GA_0-1` the thing, `GA_2-5` x, `GA_6-9` y | A = 1 fits, 0 not; tmfloorz, tmceilingz, tmdropoffz (`GM_TM*`), numspechit and spechit, ceilingline, the line record |
| `cpCopy` | the same | tmthing, tmx, tmy |
| `checkPos` | tmthing, tmx, tmy, `MP_TRY` (1 from `P_TryMove`: the point's floor after the things) | C set and A = 1 fits; as `P_CheckPosition`; `G_MPCLOB` 1 when PIT_CheckThing ran |
| `setBox` | `GA_0-1` the thing, tmx, tmy | the box, `MP_TMF`, `MP_RAD` (`SB_CHECKPOS`) |
| `walkRange` | A = d (whole units), the box | `CP_BX` (xl), `CP_XH`, `CP_YL`, `CP_YH`; C set none |
| `lineBlocks` | the box, `CP_MISS`, `CP_PLAY` (checkPos sets them) | C clear when a line blocks; the record |
| `checkThing` | `GA_0-1` the thing, tmthing | C set and A = 1: no block |

For `trymove`: natively `P_TryMove` keeps tmthing, tmx, tmy itself (its frame, e.g. on the stack) from its `cpCopy`, and takes them back when `G_MPCLOB` is set after `checkPos`: upstream copies them into P_TryMove's frame at the first game logic of the walk (`TC_TRY` [R `p_map65.s:1587-1600`]), and nothing changes them before that, so the values are the same. Every routine changes `GA_*`, `GT_*`, the math block and the API's temporaries.

Accepted or refused: (for the integrator)

## 3. Results

Lean checks (the owner's request of 2026-10-02): the `$A5` machine only, `f121` and `fastpath`, at most 40 captured calls an entry chosen as a cover of the candidates' paths, 3 planted bugs. Commands:

    make -s -C src/native -f game.mk part P=checkpos ROOT=$PWD
    python3 tools/native/gparts/checkpos.py --capture     # 201 candidates, paths.json
    python3 tools/native/gparts/checkpos.py --check --jobs 2
    python3 tools/native/gparts/checkpos.py --plants --jobs 2
    python3 -m unittest tests.test_native_game_checkpos   # 7 s; DOOM_GS_FULL=1: 194 s

| Entry | Cases | Runs | Failed | Stray | Cycles median / worst, `f121` | `fastpath` | Lowest S |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: |
| `P_CheckPosition` | 40 captured (demo3, demo2: `P_ThingHeightClip`'s) + 20 synthetic | 120 | 0 | 0 | 497,029 / 1,820,619 | 363,107 / 1,377,081 | 203 |
| `checkPos` (`P_TryMove`'s) | 40 captured (demo3, DEMO1, DEMO2) | 80 | 0 | 0 | 364,551 / 912,391 | 265,153 / 682,357 | 196 |

Compared: the canonical state (gcanon routine mode, R1-R7: line stamps, `validcount`, ceilingline, `MP_CLOB`, the line record, `P_Random`'s index, every mobj and node a pickup changes) and the declared outputs (the result; tmfloorz, tmceilingz, tmdropoffz; numspechit and the spechit lines it counts; ceilingline; `LR_OK`, `LR_N`, `LR_LINES`); no stray write (secfind's rule, with the globals block's native-only state checked by `mobjstate.native_checks` and mobjstate's shared rule for the records' banks). No case waits for an unbuilt routine.

Paths taken: fits; blocked by a thing and by a line; `MP_TRY` 0 and 1; PIT_CheckThing run (pickups, missiles passing over, under or their shooter); tmthing a missile, a pickup; 1, 2, 3 lines recorded; 1 and 2 special lines (spechit); ceilingline; boxes over 2 x 2 blocks. The synthetic calls: `P_CheckPosition` of a thing of radius 48 moved just past 10 block corners of E1M7 (demo3) and of DEMO2's map whose two off-diagonal blocks list lines (the walk's order, as milestone 9's `secorder.py`): 20 cases, 40 runs, equal.

Planted (each in a scratch copy, deleted; `$A5`, `f121`, the 100 cases): the lines' block walk with y outer: caught (2 of 100 runs fail, both corner cases: a line's stamp); the line record not kept (LR_OK never set): caught (72 of 100); the lines walked before the things: caught (25 of 100: line stamps).

Sizes (`checkpos.o` in the part's image): 2,206 of 2,600 B (upstream 2,019): `P_CheckPosition` 19, `cpCopy` 26, `setBox` 138, `walkRange` 171, `checkPos` 698, `lineBlocks` 789 (with its window `lb_word`), `checkThing` 365.

`build/`: `build/native/game/checkpos/` 28 MB (the image, 201 cases and 3 runs' bases, paths.json, synthetic.json, report.json); every temporary directory deleted.

## 4. Open points

- (Wave 2 as integrated) `PIT_CheckThing` calls `P_DamageMobj` (`GA_0-1` target, `GA_2-3` inflictor, `GA_4-5` source, `GA_6-7` damage: `damage.md`) and `P_TouchSpecialThing` (`GA_0-1` the special, `GA_2-3` the toucher: `pickup.md`).
- Not covered by this checkpoint (lean): PIT_CheckThing's damage path (`P_Random` x the missile's damage, `P_DamageMobj`), a missile exploding on its shooter's species, a missile at a thing that is not shootable: no candidate call takes them (demo3's and DEMO1's missile hits are imps' fireballs on the player, whose pain state's `A_Pain` is `look`'s, wave 3); MF_NOCLIP; more than 24 lines in one box (`LR_N` `$FF`); three special lines in one box (spechit reaches 2); the walk's end with no block (`walkRange` none). The planted bug "a missile's damage `P_Random` order" and "spechit in reverse" are not made (3 plants at most). For the integration's checks once `look` is in.
- `P_CreateSecNodeList` (gpos.s `gp_secnodes`) builds its box itself, so it does not leave tmx, tmy (the thing's x, y), the box, `MP_TMF` and `MP_RAD` as upstream's `setBoxL` call there does [R `p_map65.s:2515-2531`, `:2562`]. All are upstream's scratch: a check's walk reads them only after its own `setBox`, but a spawn inside PIT_CheckThing's game logic (a kill's drop) changes them upstream under a walk that then ends at once (the missile's `false`); `P_TryMove` takes tmthing, tmx, tmy back from its frame. No difference is expected; the tic level would show one.
- A radius of 255 (none in E1) would meet the walk's "no radius yet" (`CP_PR` `$FF`), as upstream's `WK_PR` after a `checkThing` ([R `p_map65.s:1615-1616`]: a byte store over a radius word).


## 5. The integration of wave 3 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 3 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 the near scratch in GW | **Accepted**: `TIC_GW_FIELDS` `GM_TMTHING`, `GM_TMX`, `GM_TMY`, `GM_TMBBOX`, `GM_SPECHIT`, `GM_MPTRY` (`$B333-$B355`); `checkpos.inc`'s `CP_TM*` are those names (the `CPG` stand-ins at `$B3D0` gone), `args.json`'s places `gw:`; `checkpos.py`'s unused `STAND_INS` gone |
| R2 one group | **Accepted, as two**: `gplace.AFFINITY` keeps `P_CheckPosition`, `checkPos`, `cpCopy`, `setBox`, `walkRange`, `lineBlocks` together (group 8, slot 1); `checkThing` (cold) is apart (group 18, slot 1). The core has no room (finding 1 of wave 2; `aproxdist` took 154 B more this wave) |
| R3 `OWN_STACK` 12 | **Accepted**: `glayout.OWN_STACK['p_map65.s:checkPos'] = 12` |
| R4 the helpers inlined | **Accepted**: `glayout.INLINED['checkpos']` as written |
| R5 the interfaces | **Accepted**: README "The parts' interfaces" (with the shared `GM_*` names); `trymove.md`, `teleport.md`, `chasemove.md` noted |
