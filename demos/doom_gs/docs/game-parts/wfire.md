# Part `wfire` (wave 6)

The record of milestone 10's part `wfire` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 6; upstream 964 B, native budget 1300 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 6's `wfire` (2026-10-02, lean rules).
- Files: `src/native/game/wfire/*.s`, `src/native/game/wfire/part.mk`, `src/native/game/wfire/args.json`, `tests/test_native_game_wfire.py`, this file; tools (if any) `tools/native/gparts/wfire*.py`; build output `build/native/game/wfire/` (`make -s -C src/native -f game.mk part P=wfire ROOT=$PWD`).
- Its scratch block: `SB_WFIRE` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_spawn65.s`: `P_SpawnPlayerMissile:640` (the aim retries); `p_pspr65.s`: `A_FirePistol:1108`, `A_FireShotgun:1121`, `A_FireCGun:1139`, `A_FireMissile:1005`, `A_Punch:767`, `A_Saw:802`, `gunShot:1055`, `bulletSlope:1015`; helpers `aim`, `meleeAngle`, `spread`, `meleeAttack`, `angleToTarget`, `randMod`, `useAmmo`, `aimAt`, `notRefire`

Its checkpoint (GAME.md 2.4): Every captured weapon action (through `ACTTAB` entries); synthetic: the chainsaw beside a target, berserk punch, a rocket if E1's things give one

Its planted bugs (each must fail the named check): the shotgun's pellets in another order; the spread taken on the first shot; the aim retries' order

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_spawn65.s:P_SpawnPlayerMissile` | `P_SpawnPlayerMissile` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_pspr65.s:A_FirePistol` | `A_FirePistol` | demo3 0, demo1 89, demo2 43, newgame 2, tour 0 |
| `p_pspr65.s:A_FireShotgun` | `A_FireShotgun` | demo3 26, demo1 16, demo2 8, newgame 0, tour 0 |
| `p_pspr65.s:A_FireCGun` | `A_FireCGun` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_pspr65.s:A_FireMissile` | `A_FireMissile` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_pspr65.s:A_Punch` | `A_Punch` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_pspr65.s:A_Saw` | `A_Saw` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_pspr65.s:gunShot` | `gunShot` | demo3 182, demo1 201, demo2 99, newgame 2, tour 0 |
| `p_pspr65.s:bulletSlope` | `bulletSlope` | demo3 26, demo1 105, demo2 51, newgame 2, tour 0 |

Helpers: `p_pspr65.s:meleeAngle`, `p_pspr65.s:spread`, `p_pspr65.s:meleeAttack`, `p_pspr65.s:angleToTarget`, `p_pspr65.s:randMod`, `p_pspr65.s:useAmmo`, `p_pspr65.s:aimAt`, `p_pspr65.s:notRefire`, `p_spawn65.s:aim`.

### 1.1 What was built

| File | What |
| --- | --- |
| `src/native/game/wfire/wfire.s` | The six weapon actions (`ACTTAB`), `P_SpawnPlayerMissile` with its aim retries, `bulletSlope`, `gunShot`, and the helpers `meleeAngle`, `spread`, `meleeAttack`, `angleToTarget`, `p_pspr_randMod` (`p_pspr65.s:randMod`), `useAmmo`, each a `ROUTINE` (the placement may part them); every call through `FCALL`, every record through the object API |
| `src/native/game/wfire/wfire.inc` | The scratch block's places (`WF_*`: 31 of `SB_WFIRE`'s 32 B), the player's places, A_Saw's angle constants |
| `src/native/game/wfire/part.mk`, `args.json` | The fragment; each entry's inputs and outputs (the actions are checked through part `pspr`'s `P_MovePsprites`, which `args.json`'s "about" says) |
| `tools/native/gparts/wfire.py` | The checkpoint: the selection and captures, the synthetic cases, the runs (part `pspr`'s `Prep` and `run_one` on `P_MovePsprites`), the planted bugs, `report.json` |
| `tests/test_native_game_wfire.py` | Build, checkpoint, plants: 8 s by default, the rest with `DOOM_GS_FULL=1` |

### 1.2 The native interfaces

| Routine | In | Out |
| --- | --- | --- |
| `A_FirePistol`, `A_FireShotgun`, `A_FireCGun`, `A_FireMissile`, `A_Punch`, `A_Saw` (`ACTTAB`) | `GS_PSP` the psprite (only `A_FireCGun` reads it: the flash + its state - `S_CHAIN1`) | nothing |
| `P_SpawnPlayerMissile` | `GA_0-1` the source (upstream's `_Dp[0-3]`) | nothing |
| `bulletSlope` | (the player's mobj) | `WF_SLOPE` (`SB_WFIRE` + 0, 4 B): upstream's `WP_SLOPE` |
| `gunShot` | A = accurate (0 not), `WF_SLOPE` | nothing |
| `meleeAngle`, `spread` | ; `WF_ANGLE` (`SB_WFIRE` + 4) | `WF_ANGLE` = the player's angle with the spread; its high word += (t - P_Random()) << 2 |
| `meleeAttack` | A = 0 or 1 (MELEERANGE + A), `WF_ANGLE`, `WF_DMG` | nothing |
| `angleToTarget` | `GM_LINETARGET` | `M_R` = R_PointToAngle2(the player's mobj, linetarget) |
| `p_pspr_randMod` | A = c (1-255) | A = P_Random() % c |
| `useAmmo` | (the ready weapon) | ammo[its ammo] - 1 (a word) |

Every routine changes A, X, Y, `GA_*`, `GT_*`, `GS_*` and the math block
(its callees `P_AimLineAttack`, `P_LineAttack`, `P_SpawnMobj` do). No
routine of the part can be entered again while it is active (the actions'
own calls reach no weapon action: `S_PLAY_ATK2` has none, the flash's are
`A_Light*`), so what a routine keeps across a call is in `SB_WFIRE`, never
on the stack.

## 2. Requests

**R1. `glayout.INLINED['wfire']`** = `('p_pspr65.s:aimAt',
'p_pspr65.s:notRefire', 'p_spawn65.s:aim')`. *Why*: they have no native
code: the three aims of `bulletSlope` and of `P_SpawnPlayerMissile` are a
loop in their routine (the angle's high byte stepped by `$04`, then
`$F8`), and `!refire` is two loads and a branch in `A_FirePistol` and
`A_FireCGun` (`wfire.s`). `grun.routine_sizes` and the placement give them
no bytes (as wave 4's `overStep` showed, a helper left out of `INLINED`
splits its caller's bytes). *Effect on others*: none.

**R2. `gplace.AFFINITY`: the weapon units.** Today's placement (from the
estimates) scatters the part over six groups in both slots (the part's
image: `A_FirePistol`, `A_FireShotgun`, `A_FireCGun` group 12; `bulletSlope`,
`gunShot`, `A_Punch`, `A_Saw`, `meleeAttack` group 17; `meleeAngle`,
`spread`, `angleToTarget`, `p_pspr_randMod` group 1; `useAmmo` group 6;
`A_FireMissile` group 22; `P_SpawnPlayerMissile` group 8), so a pistol shot
pages `A_FirePistol` → `useAmmo` → `bulletSlope` → `gunShot` →
`p_pspr_randMod` → `spread` through four groups, and a shotgun shot does
`gunShot` → `p_pspr_randMod`, `spread` seven times. Asked: one unit
`('p_pspr65.s:A_FirePistol', 'p_pspr65.s:A_FireShotgun',
'p_pspr65.s:A_FireCGun', 'p_pspr65.s:bulletSlope', 'p_pspr65.s:gunShot',
'p_pspr65.s:spread', 'p_pspr65.s:randMod', 'p_pspr65.s:useAmmo',
'p_pspr65.s:A_Punch', 'p_pspr65.s:A_Saw', 'p_pspr65.s:meleeAngle',
'p_pspr65.s:meleeAttack', 'p_pspr65.s:angleToTarget')` (1,096 B measured:
204 + 118 + 125 + 49 + 14 + 20 + 106 + 292 + 39 + 77 + 52), and
`p_pspr65.s:A_FireMissile` (31 B) with `P_SpawnPlayerMissile` in missile's
unit (missile.md R2), which holds it already. If the integrator's measure
puts the unit in the slot of part `attack`'s entries (wave 5: group 6, slot
1), every `P_AimLineAttack` and `P_LineAttack` call (2-4 a pistol shot, 8-10
a shotgun shot) loads attack's group and reloads the weapon's on return:
the weapon unit is better in the other slot (an `APART` pair with
`p_attack65.s:P_LineAttack`), the integrator's call from the timing model.
*Effect on others*: the groups' fill; no code changes.

**R3. `src/native/game/README.md` "The parts' interfaces"**: the rows of
1.2 above (wave 6 as integrated), for part `chase` and the integrator.
*Effect*: documentation.

**R4 (to the integrator's record, no file change).** Part `player`'s
`P_PlayerThink` calls that reach a `wfire` action (184 of 11,940, wave 5 as
integrated) become eligible with this part; part `pspr`'s `P_MovePsprites`
classes "no wfire action" (its `move_class`, `eligible`) now include the
fire calls: its selection may take them after the merge (they are the
calls this part's checkpoint runs, equal).

No exclusion is asked: the checkpoint compares with R1-R7 only. No size
request: the part's code is 1,392 B against 1,300 (7.1% over, under the
10% that needs one): A_Saw's turn (292 B: four 32-bit compares and its four
results as addends) and the player's angle loaded in place by four routines
the placement may part.

## 3. Results

The lean checkpoint (the owner's rules of 2026-10-02), on the part's image
(`make -s -C src/native -f game.mk part P=wfire ROOT=$PWD`: waves 1-5's
parts and `wfire`; no warning), fill `$A5`, `f121` and `fastpath`, routine
mode through part `pspr`'s `P_MovePsprites` (`ACTTAB`): the canonical state
equal to `ref816`'s (gcanon's routine mode, R1-R7), no stray write (part
mobjstate's shared rule with every built part's scratch block), the
native-only globals consistent.

    python3 tools/native/gparts/wfire.py --capture --jobs 2
    python3 tools/native/gparts/wfire.py --check --jobs 2
    python3 tools/native/gparts/wfire.py --plants --jobs 2

| Action | Cases | Runs | Failures | Paths (runs) | CPU cycles median / worst | Clock f121 / fastpath median | Lowest S |
| --- | ---: | ---: | ---: | --- | --- | --- | ---: |
| `A_FirePistol` | 40 captured (demo1 26, demo2 13, newgame 1, of 134 eligible) | 80 | 0 | accurate (refire 0) with a target and a hit 4, without a target 42; spread with a target and a hit 12, a target missed 4, no target 18 | 7,657,023 / 15,972,859 | 20,567,819 / 15,622,095 | 173 |
| `A_FireShotgun` | 40 captured (demo3 21, demo1 13, demo2 6, of 50) | 80 | 0 | a target hit 28, a target missed 26, no target 26 | 24,877,460 / 38,202,205 | 67,175,311 / 50,870,169 | 173 |
| `A_Punch` | 2 synthetic: punch-berserk (the x 10, a hit, the turn), punch-miss | 4 | 0 | both | 2,309,589 | 6,211,391 / 4,716,083 | 180 |
| `A_Saw` | 5 synthetic: saw-left, saw-right (the far turns, angle -/+ ANG90/21), saw-near-left, saw-near-right (mo->angle +/- ANG90/20), saw-miss | 10 | 0 | all four turns, the miss | 2,344,301 / 2,349,821 | 6,306,701 / 4,787,619 | 180 |
| `A_FireMissile` (`P_SpawnPlayerMissile`) | 4 synthetic: rocket-straight (the first aim), rocket-left (the second), rocket-right (the third), rocket-none (level, slope 0) | 8 | 0 | every retry | 8,277,090 / 10,310,951 | 22,225,700 / 16,883,769 | 181 |
| `A_FireCGun` | 2 synthetic: cgun-second (S_CHAIN2: the flash + 1), cgun-empty (no clip: no shot) | 4 | 0 | both | 5,193,200 | 13,981,136 / 10,606,870 | 175 |
| all | 93 | 186 | **0** | | | | 173 |

Stray writes 0. The cycles and clocks are the whole `P_MovePsprites`
call's, every slot empty at the call (the paging loads included: an upper
bound; the timing report is the integrator's). `bulletSlope` and `gunShot`
run in every pistol and shotgun case (one `bulletSlope` and one or seven
`gunShot` a case), `useAmmo` in each but the empty chaingun, `spread` in
every pellet, spread pistol shot and melee, `angleToTarget` in each melee
hit, `p_pspr_randMod` in each shot and melee.

Each synthetic case is a captured fire call whose aim found a live target
(the reference's `_g_linetarget` after it), its weapon's psprite put on the
state before the action's with 1 tic left (`S_PUNCH1`, `S_SAW1`,
`S_MISSILE1`, `S_CHAIN1`), the weapon ready, berserk or not, the ammunition
set, the player 8 units from the target's edge facing it at the case's
offset (melee) or at its own place turned (the rocket), the reference's own
`P_MovePsprites` run by `ref816 --call`; `wfire.took()` checks that the
reference took the case's path (the target hit or not, the turn's size, the
rocket's angle against the player's and that it did not explode, a round
used or not) before the case counts. Every case took its path on its first
base (`synthetic.json`: demo1 h86, rocket-right demo1 h4214).

**Planted bugs** (each in a scratch copy, deleted; `$A5`, `f121`):

| Bug | Check | Caught |
| --- | --- | --- |
| `pellet-order`: a pellet's spread taken before its damage (the shotgun's pellets in another order) | the 40 shotgun calls | 40 of 40 runs fail (line stamps, P_Random's index, the puffs) |
| `spread-first-shot`: the spread taken on the pistol's first (accurate) shot | the 40 pistol calls | 23 of 40 fail: every accurate shot |
| `aim-order`: the aim retries right before left | the 80 pistol and shotgun calls | 22 of 80 fail (line stamps of the second and third aims) |

**The test** (`tests/test_native_game_wfire.py`): by default 9 tests in 8 s
(2 skipped: `DOOM_GS_FULL`): the build, `ACTTAB`'s entries, no far access,
one captured call of each captured action and the synthetic saw-left under
`f121`, the `spread-first-shot` plant on the first pistol call; with
`DOOM_GS_FULL=1` every selected call and synthetic case on both profiles
and the three plants. Run once each way: default 9 tests OK (2 skipped) in 8 s;
`DOOM_GS_FULL=1` 9 tests OK in 559 s.

**Arithmetic** (GAME.md 2.4): its list names no helper of this part. The
part's helpers with arithmetic are `p_pspr_randMod` (P_Random() % c, c 3
or 10: a subtraction loop, not `math.s`'s divide) and `spread`; both run in
every case above (the P_Random index and every angle compared through the
canonical state), so no random check by `--call` was made (lean).

**Sizes** (the part's image's map, `wfire.o`): 1,392 B against 1,300
(+7.1%): group 17 718 B (`bulletSlope` 118, `gunShot` 125, `A_Punch` 106,
`A_Saw` 292, `meleeAttack` 77), group 8 265 (`P_SpawnPlayerMissile`),
group 12 204 (`A_FirePistol` 57, `A_FireShotgun` 57, `A_FireCGun` 90),
group 1 154 (`meleeAngle` 39, `spread` 49, `angleToTarget` 52,
`p_pspr_randMod` 14), group 22 31 (`A_FireMissile`), group 6 20
(`useAmmo`). Scratch block 31 of 32 B.

**build/** growth: 45 MB (`build/native/game/wfire/`: the cases 17 MB, the
image and objects); every temporary directory deleted.

## 4. Open points

- (Wave 2 as integrated) `R_PointToAngle3` and the sines are resident (`math-g.o`, wave 2 as integrated); `spawnXYZ` as `missile.md` notes.
- (Wave 3 as integrated) Part `pspr`'s `fireSomething` (A = k) and `p_pspr_startSound`, `setMoState` are built (README "The parts' interfaces").
- (Wave 5 as integrated) Part `attack`'s `P_LineAttack`, `P_AimLineAttack` (the target in GW's `GM_LINETARGET`, `$FFFF` none) and part `missile`'s `srcAbove`, `seeTarget`, `thSpeed`, `angleMom`, `checkMissile` are built; README "The parts' interfaces". `P_SpawnPlayerMissile` is in `gplace.AFFINITY`'s missile unit (`missile.md` R2).
- (wfire) The paths no case takes: which of `bulletSlope`'s three aims
  found the target in a captured call is not classified (the "no target"
  cases run all three; the rocket's synthetic cases take each of
  `P_SpawnPlayerMissile`'s, the same loop); `A_FireCGun`'s first shot
  (`S_CHAIN1`: the flash + 0) and its non-zero refire; a punch without
  berserk that hits; a rocket that explodes at its spawn (`checkMissile`'s
  refused move: its `S_EXPLODE1` runs `A_Explode`, part `chase`'s, not
  built in this image, so a run would stop "waiting"); `useAmmo`'s borrow
  (ammunition 0: `checkAmmo` refuses such a shot first); a captured kill
  by the linetarget. The final integration can add the rocket into a wall
  once `chase` is built.
- (wfire) The lean rules: one fill (`$A5`); at most 40 captured calls an
  action; the other fill and the timing report are the final
  integration's.
- (wfire) The sounds are R6 (not compared in routine mode): the pistol's,
  shotgun's, launcher's, punch's and saw's sounds are made through part
  pspr's `p_pspr_startSound` in upstream's order.

## 5. The integration of wave 6 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 6 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 `INLINED['wfire']` | **Accepted** as written |
| R2 the placement | **Accepted**: the weapons' unit in `gplace.AFFINITY` (group 20, slot 2, 1,862 B in all), and `A_FireMissile` added to missile's unit with `P_SpawnPlayerMissile` (group 14, slot 1). No `APART` pair with `P_LineAttack` was needed: the slot search put attack's entries in group 18, slot 1, opposite the weapons. The survey counts those calls, so the model already prices them |
| R3 the interfaces | **Accepted**: README "The parts' interfaces" (wave 6's rows) |
| R4 the record | **Noted** in GAME.md "Wave 6 as integrated": `player`'s and `pspr`'s calls that reach a weapon action are now eligible. Their selections were not captured again (the lean rule) |

Sizes in the wave image: `wfire.o` 1,338 of 1,300 B (2.9% over, under
the 10% that needs a request). The test module (default mode): 9 tests,
2 skipped (`DOOM_GS_FULL`), OK.
