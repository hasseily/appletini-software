# Part `player` (wave 5)

The record of milestone 10's part `player` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 5; upstream 2131 B, native budget 2800 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 5's `player` (2026-10-02, lean rules of the owner's 2026-10-02 request).
- Files: `src/native/game/player/*.s`, `src/native/game/player/player.inc`, `src/native/game/player/part.mk`, `src/native/game/player/args.json`, `tests/test_native_game_player.py`, this file; tools `tools/native/gparts/player.py`; build output `build/native/game/player/` (`make -s -C src/native -f game.mk part P=player ROOT=$PWD`; the checkpoint's image adds `PL_TEST=1`).
- Its scratch block: `SB_PLAYER` (32 B, `ggame.inc`): 31 B used (`player.inc`).

The routines (GAME.md 2.4's row):

`p_user65.s`: `P_PlayerThink:63` (noclip, the death think `fixedSquare:548`, weapons pending, powers' counts, `specialSector:717`: damage floors with `P_Random` and the leveltime mask, secrets, the exit), `movePlayer:250`, `calcHeight:378` (`P_CalcHeight`: bob, view height), `angleToAttacker:679`; `p_use65.s`: `P_UseLines:39`, `PTR_UseTraverse:162`, `PTR_NoWayTraverse:218`; helpers `countDown`, `blink`, `argMo`, `moSector`, `onGround`, `bobAndThrust`, `addMom`, `thrustMul`, `hurt32`, `times64`, `useRun`, `useArg`, `lineArg`

Its checkpoint (GAME.md 2.4): `P_PlayerThink` (every tic: 600 by path), `P_UseLines` (all 56 [M: CALLS]); synthetic: a dead player turning to the attacker, nukage with and without the suit, a use on a locked door, E1M8's sector special 11 at health 11 and 10 with and without god mode (the exit: no stream takes it, review 14). Lean (the owner's rules of 2026-10-02): at most 40 captured calls a routine, fill `$A5`, `f121`.

Its planted bugs (lean: three): the view height clamped before adding the delta; special 11 exiting at health 11; the bob's square overflowing differently (its last carry dropped). The two others of the task's list (the floor damage's mask `$0F`, the use range doubled) are not planted; the synthetic `nukage-16` (leveltime & 31 = 16: no damage) and the captured `P_UseLines` calls (the trace's line stamps) are the checks that would catch them.

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_user65.s:P_PlayerThink` | `P_PlayerThink` | demo3 2135, demo1 5027, demo2 3837, newgame 513, tour 428 |
| `p_user65.s:fixedSquare` | `fixedSquare` | demo3 4270, demo1 10054, demo2 7674, newgame 1026, tour 856 |
| `p_user65.s:specialSector` | `specialSector` | demo3 0, demo1 1180, demo2 152, newgame 0, tour 0 |
| `p_user65.s:movePlayer` | `movePlayer` | demo3 2079, demo1 4352, demo2 3503, newgame 513, tour 428 |
| `p_user65.s:calcHeight` | `calcHeight` | demo3 2135, demo1 5027, demo2 3837, newgame 513, tour 428 |
| `p_user65.s:angleToAttacker` | `angleToAttacker` | demo3 56, demo1 421, demo2 186, newgame 0, tour 0 |
| `p_use65.s:P_UseLines` | `P_UseLines` | demo3 10, demo1 25, demo2 21, newgame 1, tour 2 |
| `p_use65.s:PTR_UseTraverse` | `PTR_UseTraverse` | demo3 7, demo1 9, demo2 18, newgame 1, tour 0 |
| `p_use65.s:PTR_NoWayTraverse` | `PTR_NoWayTraverse` | demo3 0, demo1 4, demo2 1, newgame 0, tour 0 |

Helpers: `p_use65.s:times64`, `p_use65.s:useRun`, `p_use65.s:useArg`, `p_use65.s:lineArg`, `p_user65.s:countDown`, `p_user65.s:blink`, `p_user65.s:argMo`, `p_user65.s:moSector`, `p_user65.s:onGround`, `p_user65.s:bobAndThrust`, `p_user65.s:addMom`, `p_user65.s:thrustMul`, `p_user65.s:hurt32`.

## What was built

| File | Content |
| --- | --- |
| `src/native/game/player/puser.s` | `P_PlayerThink` (MF_NOCLIP from the cheat, the chainsaw's run forward, the reaction time, `movePlayer`, `calcHeight`, the sector's special, the weapon change, the use button, `P_MovePsprites`, the powers' counts, the damage and bonus counts, the colormap; the death think `pt_death`: the view height down to 6, `onGround`, `calcHeight`, the turn to the attacker by `ANG5` or at once, the damage flash, the reborn), `onGround`, `movePlayer` (the turn, the thrusts `pm_thrust`/`pm_addmom` with the CLEAN bit cleared, `S_PLAY_RUN1`), `thrustMul`, `calcHeight` (the bob, the view height and its delta, viewz, the ceiling), `fixedSquare`, `angleToAttacker` (`pta3`), `specialSector` (5, 7, 16 with the suit's `P_Random`, 9, 11 with the exit), `hurt32` |
| `src/native/game/player/puse.s` | `P_UseLines` (the 64-unit trace, `P_PathTraverse` with `PTR_UseTraverse`, then `PTR_NoWayTraverse`, the noway sound), `times64`, `PTR_UseTraverse`, `PTR_NoWayTraverse` (TRVTAB) |
| `src/native/game/player/pltest.s` | Test builds only, in the driver's area, only in the part's own image (`PL_TEST=1`): `pl_bulk`, the random checks' runner (`thrustMul`, `fixedSquare`, `times64`, `hurt32`) |
| `src/native/game/player/player.inc` | The scratch block's bytes (`PY_*`, 31 of 32), the mobj line's groups, upstream's constants of `p_user65.s:36-41` |
| `src/native/game/player/part.mk`, `args.json` | The fragment; the entries' inputs and outputs (`sb:PY_ONG` for upstream's `PU_ONGROUND`, `m_r` for a 32-bit result, `as`: `sectorptr`, `intercept`) |
| `tools/native/gparts/player.py` | The harness (on `mobjstate.py`'s machinery, as `pspr.py`): the image, the selection by class and the captures, routine mode with the write log, the synthetic cases, the random checks (`mathref batch` against `pl_bulk`), the plants, `report.json` |
| `tests/test_native_game_player.py` | Build (3 tests), Checkpoint (one captured call an entry and two synthetic cases by default; everything with `DOOM_GS_FULL=1`), Random (100,000 inputs a helper), Plants (`DOOM_GS_FULL=1`) |

### The interfaces (for the later waves' callers)

| Routine | In | Out | Notes |
| --- | --- | --- | --- |
| `P_PlayerThink` | (the player) | | part `tic`'s `P_Ticker`, every tic |
| `movePlayer`, `calcHeight` | (the player); `calcHeight` reads onground (`PY_ONG`, R1) | `movePlayer` sets onground | |
| `onGround` | (the player's mobj) | onground = z <= floorz | |
| `fixedSquare` | X = 0 (momx) or 4 (momy) of the player | `M_R` | upstream's FixedSquare with its wraps |
| `thrustMul` | `M_R` the trig value, `PY_T` m | `M_R` = FixedMulAngle(m, value) | |
| `angleToAttacker` | (the player's attacker) | `M_R` the angle | |
| `specialSector` | A = the player's sector | | may call `P_DamageMobj`, `G_ExitLevel` |
| `hurt32` | A:X = a damage | C set and `GA_0-7` = `P_DamageMobj`'s arguments (the player's mobj, `$FFFF`, `$FFFF`, the damage) when leveltime & 31 is 0, else C clear | **differs from upstream**: upstream's `hurt32` makes the call; natively the caller (`specialSector`) does `FCALL P_DamageMobj` when C is set, so that the helper's random check needs no damage run |
| `times64` | `M_R` | `M_R` = 64 `M_R` | |
| `P_UseLines` | (the player) | | |
| `PTR_UseTraverse`, `PTR_NoWayTraverse` (TRVTAB) | `GA_0` the intercept | C set and A = 1 go on, C clear and A = 0 stop | `TRVTAB_PTR_UseTraverse` 4, `TRVTAB_PTR_NoWayTraverse` 5 |

### Notes on upstream's code, reproduced

- **onground lives from tic to tic.** `PU_ONGROUND` is written by `movePlayer` and the death think and read by `calcHeight`; while the reaction time counts down (after a teleport) `movePlayer` is skipped, so `calcHeight` reads the last tic's value (`p_user65.s:90-97`, `:408`). It is upstream's scratch for the bridge, so routine mode takes it as an input and compares it as an output (`args.json`); natively it must persist: request R1.
- The weapon change reads `weaponowned[w]` for any `w` of the button's 4 bits (0-15), past `weaponowned[8]` into the ammo and the maxima, as upstream's layout (`p_user65.s:105-124`): the native player's layout keeps that order.
- Special 11's exit test is the N flag of `health - 11` (`bpl`, no overflow correction, `:774-776`), and god mode is cleared before the damage, so god mode never saves the player there.
- The use's trace: when the first traversal (`PTR_UseTraverse`) runs to its end, the second (`PTR_NoWayTraverse`) runs, and only its stop sounds noway (`p_use65.s:84-96`).
- The release's `line_t` keeps its two vertices in place (x, y in map units, 16 bits each, at `UO_LINE_V1`, `UO_LINE_V2`), not as pointers: the harness's locked-door case reads them so.

## 2. Requests

Each with what, why (the evidence), its effect on other parts, and the part's stand-in until it is applied.

**R1. A persistent onground `G_ONGROUND`.** What: (a) `glayout.TIC_MAIN_FIELDS` gains `('G_ONGROUND', 1)` (after `G_FPSSHOW`); (b) `gameroutine.tic_main_records` writes it from upstream's `p_user65.s:PU_ONGROUND` (its low byte), as `G_FPSSHOW` from `_g_fps_show`, so that a tic-level run starting at a `P_SetupLevel` entry takes the reference's value; (c) optionally the bridge's schema gains `p_user65.s:PU_ONGROUND` as a global (a byte, 0 or 1), so that the tic comparison sees it. Why: see "onground lives from tic to tic" above: `calcHeight` reads the previous tic's value when the reaction time is not 0 (`p_user65.s:90-97`, `:408`); the scratch block is W, which is not kept from one tic phase to the next (GAME.md 4.4; `README.md` "The load protocol"). Stand-in: `PY_ONG`, byte 0 of `SB_PLAYER` (`player.inc`); `args.json` maps `PU_ONGROUND` to `sb:PY_ONG`. When applied: `PY_ONG` becomes `G_ONGROUND` in `player.inc` (one line), `args.json`'s three `sb:PY_ONG` become `main:G_ONGROUND`, and `player.py`'s `SB_NAMES` loses it (its `Prep` and `outputs` then need the `main:` form, which `gameroutine.py` has). Effect: one byte of the globals block after `G_FPSSHOW`; none on other parts.

**R2. `INLINED` for the helpers done in place.** What: `glayout.INLINED['player'] = ('p_user65.s:argMo', 'p_user65.s:moSector', 'p_user65.s:countDown', 'p_user65.s:blink', 'p_user65.s:bobAndThrust', 'p_user65.s:addMom', 'p_use65.s:useRun', 'p_use65.s:useArg', 'p_use65.s:lineArg')`. Why: `argMo`, `useArg` (the player's mobj handle is read where upstream loads `_Dp`), `moSector` (in place in `P_PlayerThink`), `lineArg` (`pu_line`, `pn_line` in each traverser's group), `countDown`, `blink` (`pt_count`, `pt_blink`: local subroutines of `P_PlayerThink`), `bobAndThrust`, `addMom` (`pm_thrust`, `pm_addmom` of `movePlayer`) and `useRun` (`pu_run` of `P_UseLines`) have no label of their own; the placement gives them bytes today (groups 24, 26, 16). Effect: the placement's estimates only. `onGround`, `thrustMul`, `hurt32` and `times64` stay routines (two callers, or the random checks' `FCALL` from the driver).

**R3. Placement: the think in one group, the use in another.** What: `gplace.AFFINITY` gains three units, with the part's measured bytes (`grun.routine_sizes` on `build/native/game/player/ptest`): (a) the tic's: `p_user65.s:P_PlayerThink` 817, `movePlayer` 323, `calcHeight` 575, `fixedSquare` 101, `onGround` 59, `thrustMul` 17, `angleToAttacker` 65: 1,957 B; (b) the use: `p_use65.s:P_UseLines` 175, `PTR_UseTraverse` 165, `PTR_NoWayTraverse` 246, `times64` 14: 600 B; (c) `p_user65.s:specialSector` 172 with `hurt32` 35: 207 B (cold: only on a special floor; it does not fit beside (a)). Why: `P_PlayerThink` runs every tic and calls `movePlayer`, `calcHeight` (which calls `fixedSquare` twice and `onGround`), `thrustMul` twice a move; today they are in groups 24, 26, 4 and 2 of both slots, so a tic's think pays several group loads (routine mode, every slot empty at the call: 355,174 CPU cycles at the median). Effect: the placement's; wave 4's note that groups 24 and 26 (slot 1: `A_Chase` with `P_PlayerThink`) load each other more than once a tic changes with (a).

**R4. `OWN_STACK` for the local subroutines' returns.** What: `glayout.OWN_STACK` gains 2 for `p_user65.s:P_PlayerThink`, `p_user65.s:movePlayer`, `p_user65.s:calcHeight`, `p_user65.s:specialSector`, `p_use65.s:P_UseLines`, `p_use65.s:PTR_UseTraverse`, `p_use65.s:PTR_NoWayTraverse`. Why: each keeps the return of a local `jsr` on the stack under the callees it reaches (`pm_thrust` under `thrustMul`, `@hurt` under `hurt32` and `P_DamageMobj`, `pu_run` under `P_PathTraverse`, `pu_line`/`pn_line`/`pt_mo`/`ch_mo` under the object API), as trymove's R2. The runs' lowest S is `$BD` (189: `P_PlayerThink` with a use); `gcallgraph.py --stack --built` (waves 1-4 and `player`) 56 + 24 of 160 B without these. Effect: `--stack` counts 2 more on those chains.

**R5. The shared stray rule: the flood's stack and the sides.** What: `gparts/mobjstate.py`'s `allowed_main` gains part `pspr`'s work stack (`ps_stack`, 1,024 B, when the image has it) and `allowed_aux` the sides of `LVMAP` (`rlayout.SIDES`). Why: any caller of `P_MovePsprites` (a shot's noise alert: `recursiveSound`'s work stack in its group) or of `P_UseSpecialLine` (a switch: `P_ChangeSwitchTexture`'s `sd_put`) writes them; `pspr.py` and `evworld.py` each add them in their own rule, and so does `player.py` (`allowed_extra`, `allowed_aux_extra`): found by this part's first checkpoint run (3 cases: demo3 h177's flood, demo2 h4's and h660's switch; their canonical states were equal). Effect: the later parts' harnesses (`tic`, `wfire`) need no copy of the rule.

**R6. Documentation.** What: (a) `src/native/game/README.md` "The parts' interfaces": the rows of the table "The interfaces" above (`hurt32`'s convention in particular); (b) GAME.md 2.4's row `player`: the planted bugs as in section 1 (lean: three; the mask `$0F` and the doubled range named with the checks that would catch them). Effect: documentation.

## 3. Results

All on a2vm against `ref816`, 2026-10-02, at 2 jobs, lean (at most 40 captured calls a routine, one fill, no timing study); nothing committed. `build/native/game/player/report.json` has every number.

**Checkpoint** (`python3 tools/native/gparts/player.py --check --jobs 2`, 57 s): **134 runs, fill `$A5`, `f121`: 0 failed, 0 stray writes, 0 undecodable.**

| Entry | Cases | Failed | CPU cycles median / worst | Lowest S |
| --- | ---: | ---: | --- | ---: |
| `P_PlayerThink` | 43: 40 captured (31 classes, below), 3 synthetic | 0 | 355,174 / 1,645,631 | `$BD` |
| `specialSector` | 30: 20 captured (demo1 18, demo2 2: the damage floors), 10 synthetic | 0 | 88,787 / 260,402 | `$D3` |
| `angleToAttacker` | 20 captured (demo1 13, demo2 5, demo3 2) | 0 | 27,463 / 27,531 | `$E3` |
| `P_UseLines` | 41: 40 of the 59 calls (demo1 17, demo2 14, demo3 7, newgame 1, tour 1), 1 synthetic | 0 | 758,487 / 1,344,188 | `$C2` |

`movePlayer`, `calcHeight`, `fixedSquare`, `onGround`, `thrustMul` ran inside every `P_PlayerThink` call, `PTR_UseTraverse` and `PTR_NoWayTraverse` inside the `P_UseLines` calls and the `use` classes of `P_PlayerThink` (TRVTAB's: upstream enters them by `JML`, which `--capture` does not count). The `P_PlayerThink` classes (its tic's other calls in the survey: `still` no `movePlayer`, `atk` the death think's `angleToAttacker`, `special`, `use`, `noway`, and the dispatch targets it reached): plain, the psprites' actions (`A_WeaponReady`, `A_ReFire`, `A_Lower`, `A_Raise`, `A_Light0`, `A_Light2` and pairs), `atk+still+A_Lower` (the turn to the attacker), `still+A_Lower` (dead with no attacker), seven `special` classes, the uses with `PTR_UseTraverse` and `lnVDoor`, `lnDoor`, `lnPlat`, and two with `PTR_NoWayTraverse`. Eligible: 11,756 of the 11,940 calls (a call reaching `wfire`'s actions or `attack`'s traversers waits for the merge of waves 5-6).

The synthetic cases (each the reference's own call on a captured state with pokes, and a check that the call is the case it is named for): `dead-left`, `dead-right` (a dead player 90° off the attacker: a turn of `ANG5` each way), `squat` (viewheight 22, delta -2: under `VIEWHEIGHT / 2` after the delta); `nukage` (special 5, leveltime & 31 = 0: damage), `nukage-16` (& 31 = 16: none), `nukage-suit` (the suit: none), `slime` (16: damage), `slime-suit` (16 with the suit: `P_Random` called); `e1m8-11`, `e1m8-11-god` (no exit, god mode cleared), `e1m8-10`, `e1m8-10-god` (the exit), `e1m8-hurt` (health 30, leveltime & 31 = 0: 20 damage, then the exit), all on a tour state of E1M8; `locked-door` (`P_UseLines` 32 units in front of E1M2's line 527, a red door, facing it, no keys: the message).

Branches no case is known to reach (no path marks were run, lean): the noclip cheat's `MF_NOCLIP`, the chainsaw's `MF_JUSTATTACKED`, a reaction time (no survey run teleports), the powers' counts but the ones the demos give, the invisibility's end, the colormap's blink, special 7 and a secret (9), `MAXBOB`'s clamp, the view's ceiling clamp, `PTR_NoWayTraverse`'s too-high and too-low tests.

**Random checks** (`player.py --random`, 7 s): `thrustMul`, `fixedSquare`, `times64` on 100,000 inputs each (0, ±1, ±2, the extremes, `$FFFF`, `$8000`, `$10000` ..., then random 32-bit values) and `hurt32` on 100,000 (damage and leveltime, edges included; upstream's `P_DamageMobj` an RTL in mathref's RAM: whether it calls and with what: 3,150 calls) against upstream's helpers by `mathref batch`: **0 different** each.

**Planted bugs** (`player.py --plants`), each in a scratch copy, its image in a temporary directory:

| Plant | Check | Caught by |
| --- | --- | --- |
| the view height clamped before adding the delta | `squat` | `viewheight`, `deltaviewheight`, `viewz` |
| special 11 exiting at health 11 | `e1m8-11` | `_g_gameaction` 0 != 6 |
| the bob's square without its last carry | `fixedSquare`'s random check (20,000 inputs) | 6,748 different |

**Sizes** (the part's image's map): `puser.s` 2,164 B, `puse.s` 600 B: **2,764 of 2,800 B (-1.3%)**; test-only `pltest.s` 272 B in the driver's area. `glayout.py --check` ok; `gcallgraph.py --check --built` (waves 1-4 and `player`) 0 failures, `--stack` 56 + 24 = 80 of 160; the far-access grep on the part's sources clean.

**The test** (`tests/test_native_game_player.py`): 8 tests; by default 16 s (2 skipped); with `DOOM_GS_FULL=1` 78 s, all pass.

**build/**: `build/native/game/player` 44 MB (the cases 23 MB: five runs' bases and 138 cases); every temporary directory deleted.

## 4. Open points

- (Wave 2 as integrated) `R_PointToAngle3`, `finesine`, `finecosine` are resident (`jsr pta3` ...: the core's `math-g.o`).
- (Wave 2 as integrated) The player's message is a symbol's number: `ggame.inc`'s `SYM_*` (`pickup.md` P1).
- (Wave 3 as integrated) Part `pspr`'s `P_MovePsprites` is built (every tic); `bringUpWeapon` is an entry of `gweap.s` (the core: `pspr.md` R2).
- (Wave 4 as integrated) `P_PathTraverse` (part `path`): `GA_0-3` x1, `GA_4-7` y1, `GA_8-11` x2, `GA_12-15` y2, `GA_16` the flags, `GA_17` the traverser's `TRVTAB_<label>`; A = 1 and C set (true), 0 and C clear. A `TRVTAB` traverser takes the intercept's index in `GA_0` (`ICPT` + 6 × it: frac 4, what 2) and returns C set to go on, clear to stop (`path.md` R2, README `DCALL`); the walk's state is in `SB_PATH`, so a traverser's own state is its part's scratch block.
- R1's stand-in: until `G_ONGROUND` exists, onground is in W and does not survive a tic phase; routine mode is exact (the input is written), a tic-level run would not be after a teleport.
- The lean checkpoint ran one fill (`$A5`) and `f121` only; the other fill, `fastpath`, the rest of the captured calls and every `P_PlayerThink` call that reaches a `wfire` action or an `attack` traverser are the final integration's. The cycles are routine mode with every slot empty at the call (an upper bound), most of them group loads until R3 is applied.
- Two of the task's plants (the mask `$0F`, the use range doubled) were not planted (lean: three).

## 5. The integration of wave 5 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 5 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 a persistent `G_ONGROUND` | **Accepted** (a) and (b): `glayout.TIC_MAIN_FIELDS` gains `G_ONGROUND` (`$1EFB`, after `G_FPSSHOW`); `gameroutine.tic_main_records` writes it from `p_user65.s:PU_ONGROUND`'s low byte. `player.inc`'s `PY_ONG = G_ONGROUND` (the scratch block's byte 0 is free), `args.json`'s four `sb:PY_ONG` are `main:G_ONGROUND`, and `player.py` reads `main:` places from `glayout.TGM` (then `llayout.G`). **(c) refused for now**: a new global in the bridge's schema changes milestone 9's canonical state and its manifests, more than a lean merge reruns; the tic-level comparison (part `tic`, the final integration) can add it with its own acceptance runs. `MEMORY_MAP.md` has the row |
| R2 `INLINED['player']` | **Accepted** as written (9 helpers) |
| R3 the placement | **Accepted**: three units in `gplace.AFFINITY`. Measured placement: the think in group 10 (slot 2, 2,027 B), the use in group 15 (slot 1, with xymove's slide and geom's `P_LineOpening`), `specialSector` and `hurt32` in group 11 (slot 1, with `A_Chase` and the weapon's tic) |
| R4 `OWN_STACK` | **Accepted**: 2 for the seven routines. `gcallgraph.py --stack --built` (waves 1-5): 64 + 24 IRQ = 88 of 160 B |
| R5 the shared stray rule | **Accepted**: `mobjstate.allowed_main` allows part `pspr`'s `ps_stack` (1,024 B, when the image has it) and `allowed_aux` the sides of `LVMAP` (`rlayout.SIDES`); `player.py`'s, `pspr.py`'s and `evworld.py`'s own copies are left as they are (the same places) |
| R6 documentation | **Accepted**: (a) README "The parts' interfaces" (the player's rows, `hurt32`'s convention); (b) GAME.md 2.4's row `player`: the three planted bugs and the two named with the checks that would catch them |
