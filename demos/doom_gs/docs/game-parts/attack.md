# Part `attack` (wave 5)

The record of milestone 10's part `attack` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 5; upstream 1877 B, native budget 2500 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 5's `attack` (built 2026-10-02, under the owner's lean checks of 2026-10-02).
- Files: `src/native/game/attack/*.s`, `src/native/game/attack/part.mk`, `src/native/game/attack/args.json`, `tests/test_native_game_attack.py`, this file; tools (if any) `tools/native/gparts/attack*.py`; build output `build/native/game/attack/` (`make -s -C src/native -f game.mk part P=attack ROOT=$PWD`).
- Its scratch block: `SB_ATTACK` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_attack65.s`: `P_AimLineAttack:639`, `PTR_AimTraverse:668`, `P_LineAttack:78`, `PTR_ShootTraverse:227` (lines: `shootSpecial:936` for gun specials, the sky, the puff's place `puffPos:1019`; things: blood or puff, `P_DamageMobj`); helpers `traceSetup`, `endPoint`, `traceRun`, `loadIntercept`, `opening`, `rangeDist`, `rangeMul`, `lineSectors`, `sideAddr`, `sideSectors`, `sectorsDiffer`, `shootable`, `rawSlope`, `thingHead`, `thingFoot`, `thingPtr`, `mul3`, `thingTop`, `thingTopRaw`, `ceilBelowZ`, `thingBottom`, `thingBottomRaw`, `slopeTo`, `slopeOf`, `traceAt`, `puffArgs`, `spawnPuff`

Its checkpoint (GAME.md 2.4): `P_LineAttack` (DEMO1 295), `P_AimLineAttack` (DEMO1 296) [M: CALLS]; synthetic: a shot into the sky, at a gun-activated line, along a wall

Its planted bugs (each must fail the named check): the aim's top and bottom slopes swapped; the puff 4 units early; a gun special on a line that is not one; damage before blood

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_attack65.s:P_AimLineAttack` | `P_AimLineAttack` | demo3 55, demo1 296, demo2 132, newgame 7, tour 0 |
| `p_attack65.s:PTR_AimTraverse` | `PTR_AimTraverse` | demo3 190, demo1 929, demo2 324, newgame 18, tour 0 |
| `p_attack65.s:P_LineAttack` | `P_LineAttack` | demo3 217, demo1 295, demo2 110, newgame 3, tour 0 |
| `p_attack65.s:PTR_ShootTraverse` | `PTR_ShootTraverse` | demo3 742, demo1 899, demo2 330, newgame 13, tour 0 |
| `p_attack65.s:shootSpecial` | `shootSpecial` | demo3 93, demo1 4, demo2 21, newgame 4, tour 0 |
| `p_attack65.s:puffPos` | `puffPos` | demo3 217, demo1 287, demo2 110, newgame 3, tour 0 |

Helpers: `p_attack65.s:traceSetup`, `p_attack65.s:endPoint`, `p_attack65.s:traceRun`, `p_attack65.s:loadIntercept`, `p_attack65.s:opening`, `p_attack65.s:rangeDist`, `p_attack65.s:rangeMul`, `p_attack65.s:lineSectors`, `p_attack65.s:sideAddr`, `p_attack65.s:sideSectors`, `p_attack65.s:sectorsDiffer`, `p_attack65.s:shootable`, `p_attack65.s:rawSlope`, `p_attack65.s:thingHead`, `p_attack65.s:thingFoot`, `p_attack65.s:thingPtr`, `p_attack65.s:mul3`, `p_attack65.s:thingTop`, `p_attack65.s:thingTopRaw`, `p_attack65.s:ceilBelowZ`, `p_attack65.s:thingBottom`, `p_attack65.s:thingBottomRaw`, `p_attack65.s:slopeTo`, `p_attack65.s:slopeOf`, `p_attack65.s:traceAt`, `p_attack65.s:puffArgs`, `p_attack65.s:spawnPuff`.

### 1.1 What was built

| File | What |
| --- | --- |
| `src/native/game/attack/attack.s` | The part's routines, a GPL-2 rewrite of upstream's `p_attack65.s` (no line of `cal_integer.s`: the products, the reciprocal and the divide are milestone 6's `mul32`, `fixmul`, `recip`, `approxdiv`, `finesine`, `finecosine`). Eight `ROUTINE`s: `P_LineAttack`, `P_AimLineAttack` (one group: their local `setup` = `traceSetup` + `endPoint`, `run` = `traceRun`), `PTR_AimTraverse`, `PTR_ShootTraverse`, `shootSpecial` (one group: their local helpers), `puffPos`, `mul3`, `rangeMul`. The routines that share a local helper assert that they are in one group (`.assert GP_..._G = GP_..._G`), as `planes.s` does |
| `src/native/game/attack/attack.inc` | The scratch block's places (`AK_*`, 29 of `SB_ATTACK`'s 32 B), `AK_RANGE` = `GM_ATRANGE`, `AK_TRACE` = `GM_TRACE`, the stand-ins of R1 and R2, the macros `SLT32` (upstream's signed 32-bit compare) and `AKCOPY` |
| `src/native/game/attack/aktest.s` | Test-only (`AK_TEST=1`, the part's own image, the driver's area): `ak_bulk`, `rangeMul` or `mul3` on many inputs for the random checks |
| `src/native/game/attack/part.mk`, `args.json` | The fragment; the entries' inputs and outputs (below) |
| `tools/native/gparts/attack.py` | The checkpoint (`--capture`, `--check`, `--random`, `--plants`, `--eligible`, `--report`), on part `checkpos`'s run machinery (`checkpos.Prep`, `run_one`, `outputs`: `secfind`'s and `mobjstate`'s checks) |
| `tests/test_native_game_attack.py` | The build within budget, no far access, `TRVTAB`'s entries; the checkpoint (every 4th chosen call and synthetic shot, `$A5`, `f121`); the random checks (100,000 inputs each); three planted bugs on the calls that take their paths; with `DOOM_GS_FULL=1` every chosen call on both profiles, the paths taken, and the four planted bugs on every chosen call. 8 tests, 29 s by default, 224 s with `DOOM_GS_FULL=1` |

Every upstream routine is mirrored with its quirks: the end point's
product is the low 32 bits of `(distance >> 16)` sign-extended times the
fine cosine or sine (`_Mul32`); shootz adds `height >> 1` (arithmetic) and
`8 × FRACUNIT`; the aim's thing slopes test `dist` for 0 (INT32_MAX) and the
shot's do not (`rawSlope`); the aim halves `top + bottom` toward 0 by
adding 1 to a negative 32-bit sum before the arithmetic shift; the shot
passes a two-sided line only where the floors (ceilings) differ and
`t` is not below `openbottom` (above `opentop`); the sky test reads the front
ceiling, then the back one only when the line has a side 1; blood or a
puff (`MF_NOBLOOD`) comes before `P_DamageMobj`, which runs only for a
damage other than 0; `shootSpecial` acts on special 46 only, with a tag
(`P_CheckTag`), as `EV_DoDoor(line, dopen)` then
`P_ChangeSwitchTexture(line, 1)`. `rangeMul`'s shift path (attackrange
`1 << 27` or `1 << 26`) gives `FixedMul`'s exact result, as upstream's.

### 1.2 The native interfaces (what parts `wfire` and `chase` call)

| Routine | In | Out |
| --- | --- | --- |
| `P_LineAttack` | `GA_0-1` t1 (a handle), `GA_2-5` the angle, `GA_6-9` the distance, `GA_10-13` the slope, `GA_14-15` the damage (upstream's `_Dp[0-3]`, X:C, `_Dp[4-7]`, the stack's slope and damage) | nothing; `GM_ATRANGE` = the distance; changes `GA_*`, `GT_*`, `GS_*`, the math block |
| `P_AimLineAttack` | `GA_0-1` t1, `GA_2-5` the angle, `GA_6-9` the distance | `GA_0-3` = aimslope when a target was found, else 0 (upstream's X:C); `AK_LTGT` the target (`$FFFF` none; `GM_LINETARGET` with R1); `GM_ATRANGE`; changes as `P_LineAttack` |
| `PTR_AimTraverse`, `PTR_ShootTraverse` (`TRVTAB` 1, 2) | `GA_0` the intercept's index (`path.md` R2) | C set (A = 1) to go on, C clear (A = 0) to stop |
| `shootSpecial` | `AK_LI` the line (the traverser's) | nothing |
| `puffPos` | A = 4 or 10, `GT_0-3` = the intercept's frac | `GA_X`, `GA_Y`, `GA_Z` = the puff's place (`P_SpawnPuff`'s, `P_SpawnBlood`'s arguments) |
| `mul3` | `M_B` = a frac; `AK_AIM`, `GM_ATRANGE` | `M_R` = `FixedMul3(aimslope, frac, attackrange)` |
| `rangeMul` | `M_B` = v; `GM_ATRANGE` | `M_R` = `FixedMul(attackrange, v)` |

The part keeps from its setup to its traversers' calls, in `SB_ATTACK`:
shootthing, shootz, la_damage, topslope, bottomslope, aimslope (upstream's
`AT_SHOOT`, `AT_Z`, `AT_DAMAGE`, `AT_TOP`, `AT_BOT`, `AT_AIM`), linetarget
(R1), the traverser's intercept and line or thing, and the shot's height
`t`. Its temporaries between calls that change no `GT_0-6` (the API, the
math, `rangeMul`, `mul3`, `fc_call`) are `GT_0-6` and the math block.

## 2. Requests

Each: what, why (with the evidence), what it changes for the other parts;
the integrator accepts or refuses it with its reason.

**R1. A shared `GM_LINETARGET` (2 B) in GW.** What: in
`tools/native/glayout.py`'s `TIC_GW_FIELDS`, after `('GM_ATRANGE', 4)`:

    # linetarget (p_map.c's _g_linetarget: P_AimLineAttack writes it,
    # parts wfire and chase read it after the call; a mobj handle,
    # $FFFF none; docs/game-parts/attack.md R1)
    ('GM_LINETARGET', 2),

Why: upstream's `_g_linetarget` [R `p_attack65.s:648-649`, `:775-778`] is
read after `P_AimLineAttack` by `bulletSlope`, `P_SpawnPlayerMissile`
(`wfire`) and `aimLine` (`chase`); a part's scratch block is its own, so
the result needs a shared place, as `GM_ATRANGE` did (`spawn.md` request
1). GW's tic fields end at `$B356` with 170 B free (wave 3 as integrated).
The stand-in: `AK_LTGT` (`SB_ATTACK` + 20, `attack.inc`, marked). With the
field: `attack.inc`'s `AK_LTGT = GM_LINETARGET`, `args.json`'s
`cp:AK_LTGT` becomes `gw:GM_LINETARGET` (two lines; `SB_ATTACK` then needs
27 B). Other parts: `wfire` and `chase` read `GM_LINETARGET`; README's
`GM_*` paragraph gains it.

**R2. A shared name for the sky's ceiling pic.** What: `ggame.inc` gets
`SKY_PIC = $FE` (from `levelconv.SKY_PIC`, written by `glayout.py`'s
`constants()`, never typed in a part). Why: upstream compares a sector's
`ceilingpic` with `skyflatnum`, the word `$FFFE` [R `r_data65.s:61-62`;
`p_attack65.s:290`, `:305`], which the native byte pics hold as `$FE`
(`levelconv.pic_byte`); part `xymove`'s missile into the sky [R
`p_mobj65.s:839`] needs the same value. The stand-in: `AK_SKYPIC = $FE`
(`attack.inc`, marked). Other parts: `xymove` uses the name.

**R3. `glayout.INLINED['attack']`**, the helpers with no code of their
own (their work is local code of the part's routines, some under the same
label, module-local):

    'attack': ('p_attack65.s:traceSetup', 'p_attack65.s:endPoint',
               'p_attack65.s:traceRun', 'p_attack65.s:loadIntercept',
               'p_attack65.s:opening', 'p_attack65.s:rangeDist',
               'p_attack65.s:lineSectors', 'p_attack65.s:sideAddr',
               'p_attack65.s:sideSectors', 'p_attack65.s:sectorsDiffer',
               'p_attack65.s:shootable', 'p_attack65.s:rawSlope',
               'p_attack65.s:thingHead', 'p_attack65.s:thingFoot',
               'p_attack65.s:thingPtr', 'p_attack65.s:thingTop',
               'p_attack65.s:thingTopRaw', 'p_attack65.s:ceilBelowZ',
               'p_attack65.s:thingBottom', 'p_attack65.s:thingBottomRaw',
               'p_attack65.s:slopeTo', 'p_attack65.s:slopeOf',
               'p_attack65.s:traceAt', 'p_attack65.s:puffArgs',
               'p_attack65.s:spawnPuff'),

Why: `traceSetup`, `endPoint`, `traceRun` are `P_LineAttack`'s and
`P_AimLineAttack`'s local `setup`, `endpt`, `run`; the others the
traversers' (and `puffPos`'s `traceAt`) local code; `sideAddr` and
`sideSectors` have none (the line's sectors come from `ln_get`: `LVS`'s
`LNSECF`, `LNSECB`), nor `puffArgs` and `spawnPuff` (the puff's place is
made in `GA_X`-`GA_Z`, then `FCALL P_SpawnPuff`). Twelve local labels
carry the helper's name (`opening`, `rangeDist`, `lineSectors`,
`sectorsDiffer`, `shootable`, `rawSlope`, `thingHead`, `thingFoot`,
`slopeTo`, `slopeOf`, `ceilBelowZ`, `traceAt`): listed here, `grun.routine_sizes`
leaves them out (wave 4 as integrated) instead of splitting their
routine's bytes. The routines (`ROUTINE`) are the six of the part table
and `mul3`, `rangeMul`. Other parts: none.

**R4. Placement: the part in two units, the traversers' in slot 1.** What:
`tools/native/gplace.py` `AFFINITY` +=

    ('p_attack65.s:PTR_AimTraverse', 'p_attack65.s:PTR_ShootTraverse',
     'p_attack65.s:shootSpecial', 'p_attack65.s:puffPos',
     'p_attack65.s:mul3', 'p_attack65.s:rangeMul'),
    ('p_attack65.s:P_LineAttack', 'p_attack65.s:P_AimLineAttack'),

1,806 B and 358 B measured (section 3), and the first unit in the slot
other than path's walk (group 18, slot 2 at wave 4): path's
`traverseTo` calls a traverser for every intercept. Why: the estimates
scatter the part over four groups: the traversers and `shootSpecial` in 21
(slot 1), `rangeMul` in 12 (slot 1), `puffPos` and `mul3` in 1 (slot 2),
the entries in 5 (slot 2). Each `rangeDist` (every thing an aim or a shot
meets) loads group 12 over the traverser's group and reloads it on return;
each puff or blood loads group 1 over path's walk. Measured with that
placement (routine mode, every slot empty at the call): `P_LineAttack`
6,490,688 cycles at the median on `f121` (13,793,909 worst),
`P_AimLineAttack` 5,219,166 (10,686,539), against path's own 1,121,109 at
the median with the recording traverser (`path.md` 3). The asserts in
`attack.s` keep the two units' routines together whatever the placement
(the build fails otherwise). Other parts: none (placement only).

**R5. README: the part's interfaces.** What: `src/native/game/README.md`'s
table "The parts' interfaces" gains, before `P_PathTraverse`'s row:

    | `P_LineAttack` (`attack`) | `GA_0-1` t1, `GA_2-5` the angle, `GA_6-9` the distance, `GA_10-13` the slope, `GA_14-15` the damage | nothing; `GM_ATRANGE` the distance; changes `GA_*`, `GT_*`, `GS_*`, the math block |
    | `P_AimLineAttack` (`attack`) | `GA_0-1` t1, `GA_2-5` the angle, `GA_6-9` the distance | `GA_0-3` the slope when a target was found, else 0; `GM_LINETARGET` the target (`$FFFF` none, R1); `GM_ATRANGE` |
    | `PTR_AimTraverse`, `PTR_ShootTraverse` (`attack`, `TRVTAB` 1, 2) | `GA_0` the intercept | C set go on, clear stop |
    | `puffPos`, `mul3`, `rangeMul` (`attack`) | `attack.md` 1.2 | |

Other parts: `wfire` and `chase` call the two entries.

No new exclusion: R1-R7 of GAME.md 3.5 suffice (the sounds of the
damage's actions are R6's, as for every part).

## 3. Results

**The checkpoint** (`python3 tools/native/gparts/attack.py --capture`,
then `--check --jobs 2`; lean: the `$A5` machine only, `f121` and
`fastpath`): the canonical state after each call equal to `ref816`'s with
R1-R7 only, every declared output of `args.json` equal (aimslope,
la_damage, attackrange, shootz, shootthing; for the aim also topslope,
bottomslope, linetarget and the result), no stray write:

| Entry | Eligible | Captured | Chosen | Synthetic | Runs | Failed | Stray | Lowest S | Cycles median / worst, `f121` | `fastpath` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `P_LineAttack` | 625 | 100 | 40 | 13 | 106 | 0 | 0 | `$BF` | 6,490,688 / 13,793,909 | 4,910,014 / 10,444,614 |
| `P_AimLineAttack` | 490 | 77 | 40 | 0 | 80 | 0 | 0 | `$CB` | 5,219,166 / 10,686,539 | 3,966,362 / 8,097,223 |

- Every call of the survey is eligible (no dispatch target waits: the
  traversers are the part's, `P_DamageMobj`'s actions are built).
- **The candidates** (100 and 77 captured): evenly over demo3, DEMO1,
  DEMO2 and newgame, and `P_LineAttack`'s calls in the first tics where
  `shootSpecial` ran (34 of the 100 are in such tics). 40 of each chosen by a greedy cover of their
  paths (`path_of`, from the reference alone), then spread.
- **The paths taken**: `P_LineAttack`: the player and monsters, a puff,
  blood, no puff (the sky), damage, a kill, a puff with damage
  (`MF_NOBLOOD`), the slope 0 and not, a tic where `shootSpecial` ran, a
  door started (the gun line); `P_AimLineAttack`: a target and none, the
  window's top and bottom narrowed, the slope up and down.
- **The synthetic shots** (GAME.md 2.4; captured calls with pokes,
  upstream's `P_LineAttack` alone on `ref816` with `--reg`): into the sky
  (every ceiling the sky, the slope 2, 1/2 and 0: no puff in all three), at
  a gun-activated line (every tagged line made special 46, on six shots:
  one starts a door and changes the switch, five start none), along a wall (the shooter put a quarter of the way along a
  one-sided vertical or horizontal line, the angle along it: four shots,
  each a puff).
- **The random checks** (`--random`): `rangeMul` and `mul3` on 100,000
  inputs each (every edge v with eleven ranges: the two shift ranges, their
  neighbours, 0, 1, INT32_MAX; then random values, the aims 0, +-1, the
  extremes, the view's slopes), upstream's helpers by `mathref` batch on a
  captured call's machine against `ak_bulk`: **0 different**; upstream
  equals the Python model (`FixedMul`, `FixedMul3`) on all 100,000.
- **The planted bugs** (`--plants`, each in a scratch copy, on all 93
  chosen calls, `$A5`, `f121`): the aim's slopes swapped: 40 runs fail
  (validcount, the line stamps, linetarget, the result); the puff 4 units
  early taken away (`puffPos` with 0): 27 fail (the puff's x, y); a gun
  special on a line that is not one: 11 fail (doors started, a run that
  never returns); damage before blood: 20 fail (the blood's z: `P_Random`'s
  order). The test plants the first three (the lean rules)
  on four calls each that take their path (`attack.py`'s `PLANT_PATHS`):
  4, 4 and 2 of 4 fail.

**Sizes** (the part's image's map; `aktest.s` is test-only, in the
driver's area: 152 B): **2,164 B of 2,500** (upstream 1,877): `P_LineAttack`
with `P_AimLineAttack` and their local helpers 358 B (group 5), the
traversers, `shootSpecial` and their local helpers 1,479 (group 21),
`puffPos` with `traceAt` 185 and `mul3` 68 (group 1), `rangeMul` 74
(group 12). `SB_ATTACK` 29 of 32 B. The part image links with no warning
(`make -B -s -C src/native -f game.mk part P=attack [AK_TEST=1]
ROOT=$PWD`); its far-access grep is clean.

**Timing**: the cycles above are routine mode with every slot empty at the
call, under the estimates' placement, which scatters the part over four
groups (R4); no timing study was made (lean rules).

**Commands**:

    make -s -C src/native -f game.mk part P=attack AK_TEST=1 ROOT=$PWD
    python3 tools/native/gparts/attack.py --capture
    python3 tools/native/gparts/attack.py --check --jobs 2
    python3 tools/native/gparts/attack.py --random --count 100000
    python3 tools/native/gparts/attack.py --plants --jobs 2
    python3 -m unittest discover -s tests -p test_native_game_attack.py
    DOOM_GS_FULL=1 python3 -m unittest discover -s tests -p test_native_game_attack.py

`build/native/game/attack/` holds 42 MB (the cases 18 MB with their
runs' bases, the image, `paths.json`, `report.json`); every temporary
directory was deleted.

## 4. Open points

- **Not covered by a chosen call** (the reference does not show them, or
  no run takes them): the aim's and the shot's `dist` 0 (a thing or a line
  at the trace's start: `slopeOf`'s INT32_MAX, `rawSlope`'s divide by 0);
  which of the aim's three stops at a line ends it (one-sided, the
  opening closed, the window closed: all are "no target"); the sky's back
  ceiling branch apart from the front one (the synthetic sky shots end
  with no puff, not told apart); special 46 on a line with no tag
  (`P_CheckTag` false); la_damage 0 (no caller gives it). E1's one line
  of special 46 (E1M2) is never shot in the runs.
- A line with `ML_TWOSIDED` and no side 1 would make `sectorsDiffer` read
  sector `$FF` (upstream reads through a NULL sector): no E1 map has one
  (`DOOM1.WAD`'s LINEDEFS: 0 in E1M1-E1M9).
- The `$5A` machine is not run (lean rules); the sound events of
  `P_DamageMobj`'s actions are not compared (R6).
- The timing waits for the placement (R4) and the timing report (5.4).

- (Wave 2 as integrated) `P_LineAttack` and `P_AimLineAttack` write `attackrange` to `GM_ATRANGE` (4 B, `ggame.inc`; `spawn.md` request 1), which `spawn`'s `P_IsAttackRangeMeleeRange` reads.
- (Wave 2 as integrated) The trace's point at a frac reads `GM_TRACE` (`tracel.md` R1).
- (Wave 2 as integrated) `shootSpecial` calls `P_ChangeSwitchTexture` with Y = 1 (useAgain: `lines.md` 1.2).
- (Wave 2 as integrated) `P_DamageMobj`: `GA_0-1` the target, `GA_2-3` the inflictor, `GA_4-5` the source, `GA_6-7` the damage (`damage.md`); `R_PointToAngle3`, `finesine`, `finecosine` are resident (`jsr pta3` ...: the core's `math-g.o`, wave 2 as integrated).
- (Wave 4 as integrated) `P_PathTraverse` (part `path`): `GA_0-3` x1, `GA_4-7` y1, `GA_8-11` x2, `GA_12-15` y2, `GA_16` the flags, `GA_17` the traverser's `TRVTAB_<label>`; A = 1 and C set (true), 0 and C clear. A `TRVTAB` traverser takes the intercept's index in `GA_0` (`ICPT` + 6 × it: frac 4, what 2) and returns C set to go on, clear to stop (`path.md` R2, README `DCALL`); the walk's state is in `SB_PATH`, so a traverser's own state is its part's scratch block.

## 5. The integration of wave 5 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 5 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 `GM_LINETARGET` | **Accepted**, placed last in `glayout.TIC_GW_FIELDS` rather than after `GM_ATRANGE`, so that the fields after it keep their places (`$B356`, GW's tic fields end at `$B358`); `attack.inc`'s `AK_LTGT = GM_LINETARGET` (the scratch block's places after it moved down 2 B: `AK_NEED` 27), `args.json`'s output `gw:GM_LINETARGET` |
| R2 `SKY_PIC` | **Accepted**: `glayout.constants()` writes `SKY_PIC` (`levelconv.SKY_PIC`, `$FE`) into `ggame.inc`; `attack.inc`'s `AK_SKYPIC = SKY_PIC` (and `xymove.inc`'s `XY_SKYPIC`) |
| R3 `INLINED['attack']` | **Accepted** as written (25 helpers); `grun.routine_sizes` leaves the twelve local labels named as helpers out |
| R4 the placement | **Accepted**: the two units in `gplace.AFFINITY`; "the traversers not in path's walk's slot" needed a rule the placement did not have: `gplace.APART`, the pairs (`traverseTo`, each `TRVTAB` traverser) whose groups never share a slot, kept as A_Chase's rule is (the search now two-colours these rules and tries every slot of the moves, `gplace.EXHAUSTIVE`). Measured placement: the traversers' unit in group 13 (slot 1, 1,879 B with `lnExit`), path's walk group 3 (slot 2), the entries group 6 (slot 1, 2,038 B with the radius attack). `P_SpawnPuff`/`P_SpawnBlood` (group 8, slot 1) are in the traversers' slot: each puff or blood reloads the traverser's group on return |
| R5 the interfaces | **Accepted**: README "The parts' interfaces" (the four rows); `wfire.md`, `chase.md` noted |
