# Part `damage` (wave 2)

The record of milestone 10's part `damage` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 2; upstream 1363 B, native budget 1800 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 2's `damage` (2026-10-02).
- Files: `src/native/game/damage/*.s`, `src/native/game/damage/part.mk`, `src/native/game/damage/args.json`, `tests/test_native_game_damage.py`, this file; tools (if any) `tools/native/gparts/damage*.py`; build output `build/native/game/damage/` (`make -s -C src/native -f game.mk part P=damage ROOT=$PWD`).
- Its scratch block: `SB_DAMAGE` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_inter65.s`: `P_DamageMobj:541` (god mode, armour, the thrust with `P_Random`, `R_PointToAngle3` and the 32-bit divide, pain chance, threshold and target, the player's counts and attacker), `killMobj:994` (`P_KillMobj`: flags, counts, the death or extreme death state, the tics' `P_Random`, the drops through `P_SpawnMobj`); `p_pspr65.s`: `P_DropWeapon:547`, `lowerWeapon:551`, `wInfo:122`, `wInfoOf:123`; helpers `targetArg`, `setTarget`, `setState`, `lastEnemy`, `thrust`, `addThrust`, `playerDamage`

Its checkpoint (GAME.md 2.4): Every captured `P_DamageMobj` (demo3 132, DEMO1 186, DEMO2 52 [M: CALLS]); synthetic: a kill with a drop, the player's death, each armour type, god mode, a hit at 0 health

Its planted bugs (each must fail the named check): thrust divided before the multiply; pain chance tested before the thrust's `P_Random` (the index); the extreme death at `<=` instead of `<` (synthetic); the drop spawned before the death state (thinker order)

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_inter65.s:P_DamageMobj` | `P_DamageMobj` | demo3 132, demo1 186, demo2 52, newgame 0, tour 0 |
| `p_inter65.s:killMobj` | `killMobj` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_pspr65.s:P_DropWeapon` | `P_DropWeapon` | demo3 1, demo1 7, demo2 2, newgame 0, tour 0 |
| `p_pspr65.s:lowerWeapon` | `lowerWeapon` | demo3 2, demo1 9, demo2 3, newgame 0, tour 0 |
| `p_pspr65.s:wInfo` | `wInfo` | demo3 1224, demo1 3073, demo2 1559, newgame 57, tour 21 |
| `p_pspr65.s:wInfoOf` | `wInfoOf` | demo3 2, demo1 10, demo2 4, newgame 1, tour 9 |

Helpers: `p_inter65.s:targetArg`, `p_inter65.s:setTarget`, `p_inter65.s:setState`, `p_inter65.s:lastEnemy`, `p_inter65.s:thrust`, `p_inter65.s:addThrust`, `p_inter65.s:playerDamage`.

## What was built

| File | Content |
| --- | --- |
| `src/native/game/damage/dinter.s` | `P_DamageMobj`, `setState`, `lastEnemy`, `thrust` (with `addThrust` in place: `add_thrust`), `playerDamage`, `killMobj`; `setTarget` in place (`set_target`), `targetArg` in place (a `mo_get` of `DM_TGT` wherever upstream calls it) |
| `src/native/game/damage/dmath.inc` | **Stand-in** of request R1, included by `dinter.s` in `thrust`'s group: math.s's non-RENDER `pta3`, `pta_oct`, `finesine`, `finecosine` and `cosexc`, renamed `dm_*`, unchanged otherwise (656 B) |
| `src/native/game/damage/dweap.s` | `P_DropWeapon`, `lowerWeapon` (milestone 9's `gw_setpsprite`, its action through `ACTTAB`), `wInfo`, `wInfoOf` (math.s's `mul8`: upstream's `IIGS_MulLo16`), and upstream's `weaponinfo` table (108 B) in the core (request R2) |
| `src/native/game/damage/dtest.s` | The test routine `dm_t_bulk` (the thrust on many inputs for the random check), in the card's driver area; only in the part's own image (`part.mk`: `DM_TEST=1`) |
| `src/native/game/damage/damage.inc` | The part's places: the scratch block's bytes (`DM_*`, upstream's `DM_*` of `p_inter65.s`), the mobj line's groups, `WI_*` |
| `src/native/game/damage/part.mk`, `args.json` | The fragment; the entries' inputs and outputs |
| `tools/native/gparts/damage.py` | The part's harness (on part `mobjstate`'s: `Prepared`, `allowed_main`, the write log, `ref_call`): the image, the captures, routine mode on both fills and both profiles with the write log, the stop checks and their "action removed" variants, the synthetic groups, the random check of the thrust (`mathref batch`), the planted bugs, `report.json` |
| `tests/test_native_game_damage.py` | Build, Checkpoint (every 8th captured case, every synthetic group), Random (100,000 inputs), Plants |

### The interfaces (for the later waves' callers)

| Routine | In | Out | Notes |
| --- | --- | --- | --- |
| `P_DamageMobj` | `GA_0-1` the target, `GA_2-3` the inflictor, `GA_4-5` the source (handles; `$FFFF` none), `GA_6-7` the damage (signed) | nothing | upstream's `_Dp[0-3]`, `_Dp[4-7]`, `4,s` and C. Callers: `checkpos` (`PIT_CheckThing`), `look` (`PIT_RadiusAttack`), `attack` (`PTR_ShootTraverse`), `player` (`specialSector`), `teleport` (`stompThing`), `chase`'s attacks, `wfire`'s melee. Changes `GA_*`, `GT_*`, `GS_*` (a drop's spawn) and the math block; keeps nothing for its caller |
| `killMobj` | `DM_*` of the scratch block | | `P_DamageMobj`'s tail (upstream's `brl`); no other caller |
| `P_DropWeapon`, `lowerWeapon` | (the player) | | the weapon's psprite to its down state through `gw_setpsprite` (its action `A_Lower` through `ACTTAB`) |
| `wInfo` | (the ready weapon) | X = A = the offset of its record in `weaponinfo` | 12 × the weapon; changes Y and math.s's slot 0 (`mul8`). A caller reads `weaponinfo + WI_*, x` (`damage.inc`: `WI_AMMO` 0, `WI_UP` 2, `WI_DOWN` 4, `WI_READY` 6, `WI_ATK` 8, `WI_FLASH` 10), in the core in every group (R2) |
| `wInfoOf` | A = a weapon | X = A = its record's offset | the same |

Temporaries: `GT_0-GT_3` and the scratch block `SB_DAMAGE` (25 of 32 B:
`damage.inc`); no zero page of the part's own. `setState` keeps
`DM_TGT`, `DM_SRC` and `DM_TYPE` on the stack around `P_SetMobjState`,
and `P_DamageMobj` its justhit, as upstream does (a state's action may
damage again).

### Notes on upstream's code, reproduced

- The pain chance is a byte compare: `P_Random()` against the low byte of
  `mobjinfo.painchance` (`p_inter65.s:600-605`), so a pain chance of 256
  never hurts (the C: always). No E1 type has 256.
- The thrust's numerator is built as upstream builds it,
  `(12 d + (d >> 1)) << 16 + (d & 1) << 15` in 16-bit halves (`:795-812`,
  so 12 d wraps for |d| > 5,461), then divided by the mass's low word
  sign-extended (`:813-821`) with math.s's `sdiv32`.
- The armour's "used up" test is upstream's `cmp; beq; bmi` on the 16-bit
  difference saved - armorpoints (`:959-961`), the damage count's limit
  its `cmp ##101; bmi` (`:986-987`), the health's floor its `bpl`
  (`:973-977`): N flags of 16-bit differences, reproduced as such.
- The drop's spawn calls `P_Random` (`P_SpawnMobj`'s "for compatibility",
  `p_spawn65.s:149`), after the death tics' one: the order is checked by
  the plant `drop-before-death`.

## 2. Requests

Each with what, why (the evidence), its effect on other parts, and the
part's stand-in until it is applied.

**R1. `R_PointToAngle3`, `finesine` and `finecosine` in the tic images.**
What: the tic images link `math.s` as `math-r.o` (`-D RENDER`, `game.mk`
`COMMON`), which has no `pta3`, `pta_oct`, `finesine`, `finecosine` or
`cosexc` (`math.s:44-50`, `:1115-1285`, `:1478-1544`). Link them into
the tic images: either math.s's own (a build of `math.s` that keeps
`MATHW`'s render subset and puts these five, 656 B with the table, in the
core or a group), or the aux card's `tantoangle` for `pta3` as GAME.md 4.1
plans (`auxlc.s`'s `ax_tanto` reads only bytes 2-3 of an entry: a 4-byte
read is needed). Why: the thrust calls `R_PointToAngle3`
(`p_inter65.s:792`), `finecosine` and `finesine` (`:874`, `:878`); with
`math-r.o` the part does not link. Stand-in: `dmath.inc`, math.s's
non-RENDER code with `dm_` names in `thrust`'s group (it reads the tables
bank `MT_TBANK` through math.s's `mt_far`, as math.s does; `grun.Image`
loads the bank). When applied: `dinter.s` drops the `.include` and calls
`pta3`, `finecosine`, `finesine` (three lines). Effect: every part whose
routines reach `R_PointToAngle2/3` or the sines needs it (`look`'s
`A_FaceTarget`, `chase`, `attack`, `missile`, `player`, `xymove`,
`teleport`, `wfire`); the part's bytes drop by 656.

**R2. `weaponinfo` in the core.** What: upstream's table (`p_pspr65.s:1233-1250`,
108 B) is `dweap.s`'s, exported, in segment `GCORE` (the `wInfo`
callers read `weaponinfo + WI_*, x` after the call, in any group: a table
in a paged group would be another group's bytes when the caller's slot
holds it). Also: generate `U_WI_AMMO_w`, `U_WI_DOWN_w`, `U_WI_ATK_w`,
`U_WI_FLASH_w` in `lgame.inc` (`llayout.game_constants`, beside
`U_WI_UP_w` and `U_WI_READY_w`), so the table can be written from them
(`dweap.s` asserts its up and ready states against lgame's today, and the
test compares the table with the release's bytes). Why: `wInfo`'s callers
`pspr` (`p_pspr65.s:389`, `:536`, `:736`, `:745`, `:994`, `:1140`) and
`pickup`'s `giveWeapon`, which reads `weaponinfo + OFS_WI_AMMO` directly
(`p_inter65.s:459`): `pickup` (wave 2, built at the same time) should
import `weaponinfo` and index it with `wInfoOf`'s offset instead of a
table of its own. Effect: the core's room 108 B less; if the core is short
the integrator can move the table to `GTAB` with an API read (`wi_get`,
like `mi_get`), and `wInfo`'s interface becomes the record's fields in a
buffer.

**R3. `INLINED` for this part's helpers.** What: in `glayout.py`'s
`INLINED`, `'damage': ('p_inter65.s:targetArg', 'p_inter65.s:setTarget',
'p_inter65.s:addThrust')`. Why: `targetArg` is a `mo_get` of `DM_TGT`
where upstream calls it; `setTarget` is `set_target`, a local subroutine
of `P_DamageMobj`'s group (`dinter.s`); `addThrust` is `add_thrust`, a
local subroutine of `thrust`'s group. The placement gives them bytes and
groups today (`targetArg` and `setTarget` in group 22). Effect: none on
other parts; the placement's estimates.

**R4. `AM_Stop` and the automap's state.** What: upstream's `killMobj`
calls `AM_Stop` only when `automapmode & AM_ACTIVE`
(`p_inter65.s:1052-1056`); the native has no `automapmode` (review 7
left it out of the canonical model), so `killMobj` calls the hook
`AM_Stop` always (`dinter.s`, marked). `ghook.s`'s `AM_Stop` is empty now;
milestone 11's must test the automap's active flag itself (C's `AM_Stop`
does nothing visible when the automap is off, but its `ST_Responder`
message is the status bar's). Effect: none in milestone 10.

**R5. `gameroutine.py`: a NULL pointer `as: mobj`.** What: in
`run_case`'s inputs (and outputs), an upstream pointer 0 with `as: mobj`
becomes `$FFFF` (none), as part `mobjstate`'s `_convert` does. Why:
`P_DamageMobj`'s inflictor and source are often NULL (the damage floors
of `specialSector`: `player, no inflictor` in demo1's and demo2's
captures; `args.json` `dp:_Dp+4:4`, `s:4:4`); `gameroutine.run_case`
raises on them (`up.ref(0)`). `damage.py` runs through `mobjstate`'s
`Prepared` meanwhile. Effect: the integrator's one harness (wave 1's open
item).

**R6. The stray-write rule: math.s's `mt_far` operands.** What: the
harness's write log allows the two bytes `mt_far` patches in its own code
in the card's bank 1 (`mt_far_count + 1`, `mt_far_stride + 1`, written by
`MATHFAR`'s code). Why: any call that reaches `pta3`, the sines,
`recip`, `recipsmall` or `approxdiv` writes them (`math.s` "mt_far");
`mobjstate.stray()` flags them (its log has `lc1` and no rule for it).
`damage.py`'s `stray()` adds exactly these two bytes. Effect: the
integrator's one harness; `look`, `chase`, `attack`, `missile`, `player`,
`xymove`, `teleport` reach `mt_far`.

**R7. The placement: one group for the damage.** What: `gplace.py`'s
`AFFINITY` (or `PINNED`): `P_DamageMobj`, `thrust`, `playerDamage`,
`setState`, `lastEnemy`, `killMobj` together (2,427 B with R1's
stand-in, slot 1's room only; 1,771 B without, either slot), and `wInfo`, `wInfoOf` in the core (19 B; `wInfo` is
called by `pspr`'s per-tic routines: 1,224 times in demo3). Why: the
measured paging (results: the calls' `fc_loads`); the initial placement
spreads them over groups 6, 13, 16, 17, 22 and 25, both slots. Effect: the
placement's (the integrator's).

**R8. The interfaces in `src/native/game/README.md`.** What: the table
"The interfaces" above, for the later waves' callers of `P_DamageMobj`,
`wInfo`, `wInfoOf`, `P_DropWeapon`. Effect: documentation.

## 3. Results

All on a2vm against `ref816`, 2026-10-02, at 2 jobs; nothing committed.
`report.json` (`build/native/game/damage/report.json`) has every number.

**Checkpoint** (`python3 tools/native/gparts/damage.py --check --jobs 2`):
3,596 runs, both fills (`$A5`, `$5A`), both profiles (`f121`,
`fastpath`): **0 failed, 0 stray writes**; 572 s.

| Entry | Cases | Runs | Failed | CPU cycles, median / worst | Clock `f121`, `fastpath` (median) | Lowest S | Group loads (median / worst) |
| --- | --- | ---: | ---: | --- | --- | ---: | --- |
| `P_DamageMobj` | 429: 360 captured, 10 captured stop checks (`A_Lower`), 41 synthetic, 4 synthetic stop checks (3 `A_Lower`, 1 `A_Chase`), 14 variants with the action removed | 1,716 | 0 | 115,791 / 236,612 | 312,502, 235,853 | `$D1` | 6 / 12 |
| `killMobj` | 77: `P_DamageMobj`'s deaths (46 captured, 18 synthetic, 13 variants) | 308 | 0 | 166,029 / 236,612 | 457,411, 339,313 | `$D1` | 8 / 12 |
| `P_DropWeapon` | 20: 10 captured stop checks (`A_Lower`), 10 variants | 80 | 0 | 31,626 | 85,663, 64,658 | `$D9` | 4 |
| `lowerWeapon` | 28: 14 captured stop checks (`A_Lower`), 14 variants | 112 | 0 | 11,610 | 31,857, 23,789 | `$DE` | 2 |
| `wInfo` | 387: 378 captured (100 of each demo spread evenly, all of the newgame's 57 and the tour's 21), 9 synthetic (each weapon) | 1,548 | 0 | 10,382 | 27,836, 21,286 | `$E3` | 2 |
| `wInfoOf` | 35: 26 captured (all), 9 synthetic (each weapon) | 140 | 0 | 5,201 | 13,941, 10,685 | `$E8` | 1 |

Eligibility (the survey): `P_DamageMobj` demo3 131 of 132, DEMO1 179 of
186, DEMO2 50 of 52; the others wait for `A_Lower` (part `pspr`, wave 3);
the native stops at exactly those calls (10), every one a passing stop
check whose variant without `A_Lower` is equal. Every call is routine
mode with both slots empty at the call: the cycles are mostly paging
(`fc_call`'s group loads, R7); `$D1` is 30 B below the driver's `$EF`.

The paths of `P_DamageMobj`'s captured calls (`report.json`
`entries.paths`): monsters thrust, in pain, given a new target, dying
(46, 2 extreme, 23 with a drop), the player with and without inflictor,
green armour, dying; the synthetic groups add the rest of the row:
kills with a drop (zombieman, shotgun guy, four `P_Random` indexes each),
the rocket cheat (in and out of its range), the extreme death's boundary
(`health - damage` = `-spawnhealth`: death; one below: extreme), the
player's death (200 and 1,000), each armour type (green, blue, used up,
equal, a negative damage), god mode and invulnerability below and at
1,000, a hit at 0 and at -5 health, not shootable, baby (odd and negative
damage), the exit sector (special 11, above and below the health), the
turn-over (four indexes, and `dz` exactly 64), the chainsaw, the pistol,
`MF_NOCLIP`, no inflictor, the threshold (0 from the spawn state: the
see state, `A_Chase`; and 5).

**Random check** (`damage.py --random`): the thrust on 100,000 inputs
(every damage edge with every type, then random damages, positions far,
close, on an axis, on a diagonal, equal and at the 32-bit extremes,
heights around the turn-over's 64 units, healths around the damage)
against upstream's `thrust` by `mathref batch`: momentum, `P_Random`'s
index, the thrust and its angle **0 different**; 11,104 inputs turned
over (their `P_Random`). Type 49's mass is 0 (not shootable: no game call
reaches its thrust): its 500 inputs are a division by zero, checked
against the port's own quotient (MATH.md), 0 different, never against
the vendor's.

**Planted bugs** (`damage.py --plants`), each caught by its check:

| Plant | Check | Caught by |
| --- | --- | --- |
| the thrust divided before the multiply | the captured hits; the random check | demo3 hit 1: `momx 11810 != 0`; 1,855 of 2,000 random inputs |
| the pain chance's `P_Random` before the thrust's | the turn-over, god mode, the drops | turned over 0: `prndindex`, `momx`, `momy`, `tics` |
| the extreme death at `<=` | `xdeath-equal` | the state 125 against 130 |
| the drop spawned before the death state | the drops | drop-possessed 0: `tics 3 != 4` (the spawn's `P_Random` taken before the tics') |

**Sizes** (the part's image's map): `dinter.s` 2,427 B (656 of them
R1's stand-in), `dweap.s` 155 B (the table 108); **own bytes 1,926 of
1,800 (+7.0%)**, code alone 1,818 (+1.0%); by routine `P_DamageMobj`
399, `setState` 68, `lastEnemy` 95, `thrust` 519 (+ 656 stand-in),
`playerDamage` 301, `killMobj` 389, `P_DropWeapon` 7, `lowerWeapon` 21,
`wInfo` 10, `wInfoOf` 9. Test-only `dtest.s` 333 B in the driver's area
(`$E000-$EA9F`, 2,720 of 3,584 with wave 1's). The core with the table:
`$6600-$96C4`, 12,485 of 12,800 B. `glayout.py --check` ok;
`gcallgraph.py --check --built geom,mobjstate,secfind,flow,sight,damage`
0 failures, `--stack` 80 of 160; `gameroutine.grep_check` on the part's
sources: clean.

**The test** (`tests/test_native_game_damage.py`): Build (4), Checkpoint
(every 8th captured case, every synthetic group: 5), Random (100,000
inputs), Plants (the four and the random one).

**build/**: `build/native/game/damage` 47 MB (the cases 44 MB: three
demos' bases and 798 cases); every temporary directory deleted.

## 4. Open points

- The 10 captured player deaths reach `A_Lower` (part `pspr`, wave 3),
  as do every `P_DropWeapon` and `lowerWeapon` call: today they are stop
  checks, and their variants without `A_Lower` are compared whole. They
  become eligible when `pspr` is integrated (the integrator's rerun).
- The see state (a monster hit in its spawn state, threshold 0, by
  another mobj) reaches `A_Chase` (part `chase`, wave 6): no captured
  call takes it; the synthetic `threshold` case is a stop check and a
  variant.
- `killMobj` has no captured call of its own (upstream enters it by
  `brl`): its runs are `P_DamageMobj`'s deaths.
- The plant "the drop spawned before the death state (thinker order)":
  the dropped items' spawn states have tics -1, so `P_SpawnMobj` gives
  them no thinker (`addIfFunc`); the order shows through `P_Random`
  (the spawn's against the death tics'), which the drops' check catches.
- R1's stand-in costs 656 B in `thrust`'s group until the math is linked;
  R4 (the automap) is milestone 11's.
- The module's time: 12 tests in 157 s (`python3 -m unittest discover
  -s tests -p test_native_game_damage.py`, 2 processes), under
  `tools/testpar.py`'s 1,200 s: no `MODULE_TIMEOUTS` entry needed.

## 5. The integration of wave 2 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 2 as integrated").

| Request | Decision |
| --- | --- |
| R1 the game's math in the tic images | **Accepted**: `math.s -D GAMEMATH` (`math-g.o`, in every tic image: `game.mk` `COMMON`) assembles only `pta3`, `pta_oct`, `finesine`, `finecosine` and `cosexc` (one text, `src/native/mathgame.inc`, which the whole module includes too; the render build is unchanged byte for byte) into the core, on `math-r.o`'s `mt_far`, `udiv32` and `pta_tab`: 672 B. The core could not hold them at 12,800 B (sight's pinned 3,172 B left 3,599 for routines), so **W's map changed**: the core is `$6600-$99FF` (13,312 B), the scratch blocks `$9A00-$9DFF`, slot 1 `$9E00-$A5FF` (2,048 B: `gplace.py` cut every group at 2,048 already). `dmath.inc` is gone; `dinter.s` calls `pta3`, `finecosine`, `finesine` |
| R2 `weaponinfo` in the core | **Accepted**: `dweap.s`'s table stays in `GCORE`, now written from `lgame.inc`'s `U_WI_AMMO_w` .. `U_WI_FLASH_w` (`llayout.game_constants`: the release's table) and checked against `UO_WI_*`; part `pickup` reads it (`weaponinfo + UO_WI_AMMO` at 12 × the weapon) instead of a table of its own |
| R3 `INLINED` | **Accepted**: `targetArg`, `setTarget`, `addThrust` |
| R4 `AM_Stop` | **Accepted** as milestone 11's: `ghook.s`'s header says its `AM_Stop` must test the automap's state |
| R5 a NULL pointer `as: mobj` | **Accepted**: `gameroutine.run_case` gives a NULL pointer `as: mobj` the handle `$FFFF` (inputs) and requires `$FFFF` for a NULL (outputs); `damage.py` keeps `mobjstate`'s `Prepared` until the five harnesses are one (GAME.md "Wave 1 as integrated", open) |
| R6 `mt_far`'s operands | **Accepted**: `mobjstate.stray` (the rule `spawn`, `damage` and the later parts share) allows the two bytes, `mobjstate.mt_far_operands` |
| R7 the placement | **Accepted**: `gplace.AFFINITY` (`P_DamageMobj`, `thrust`, `playerDamage`, `setState`, `lastEnemy`, `killMobj`: one group, 19, slot 1) and `CORE_FIRST` (`wInfo`, `wInfoOf`: in the core) |
| R8 the interfaces | **Accepted**: README "The parts' interfaces" |

## 6. The integration of wave 3 (2026-10-02)

`A_Lower` (part `pspr`) is built: the player's deaths and `lowerWeapon`'s calls that stopped at its DCALL run it whole, equal to the reference; `test_native_game_damage`'s stop test became `test_a_lower_runs_whole` (no case waits for `A_Lower`, a player's death is in the sample) and the stop test checks the variants of whatever still waits (`A_Chase`). The damage image's driver area overflowed by 67 B once every part image linked `pspr`'s `pstest.s`: `pstest.s` is now linked only into pspr's own image (`PS_TEST=1`, as `DM_TEST`).
