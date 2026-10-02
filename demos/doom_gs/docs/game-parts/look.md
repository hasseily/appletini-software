# Part `look` (wave 3)

The record of milestone 10's part `look` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 3; upstream 1729 B, native budget 2300 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 3's `look` (2026-10-02), lean checks (the owner's rules of 2026-10-02).
- Files: `src/native/game/look/*.s`, `src/native/game/look/part.mk`, `src/native/game/look/args.json`, `tests/test_native_game_look.py`, this file; tools (if any) `tools/native/gparts/look*.py`; build output `build/native/game/look/` (`make -s -C src/native -f game.mk part P=look ROOT=$PWD`).
- Its scratch block: `SB_LOOK` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_enemy65.s`: `A_Look:512`, `lookForPlayers:385`, `behindFast:2154` (its `bfTab`), `A_FaceTarget:1749`, `checkMeleeRange:1023`, `checkMissileRange:1056`, `P_CheckMeleeRange:1001`, `P_CheckMissileRange:1007`, `A_Scream:2017`, `A_XScream:2040`, `A_Pain:2046`, `A_Fall:2054`, `A_PlayerScream:2070`; `p_attack65.s`: `P_RadiusAttack:876`, `PIT_RadiusAttack:799`; helpers `angleToAT`, `distanceAT`, `faceTarget`, `loadTarget`, `randMod`, `startSound`, `blockPair`, `absDelta`

Its checkpoint (GAME.md 2.4): `A_Look` (demo3 5.3 a tic [M: VC]: 300 by path), the range checks; synthetic: `P_RadiusAttack` from a barrel (no demo calls it [M: CALLS]) with things around it, one behind a wall

Its planted bugs (each must fail the named check): `behindFast`'s 90° edge on the other side; the missile range not halved for its type; the shadow's `P_Random` shift; the radius damage's distance not clamped at 0

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_enemy65.s:A_Look` | `A_Look` | demo3 11410, demo1 42015, demo2 27064, newgame 267, tour 2705 |
| `p_enemy65.s:lookForPlayers` | `lookForPlayers` | demo3 11533, demo1 42084, demo2 27084, newgame 266, tour 2705 |
| `p_enemy65.s:behindFast` | `behindFast` | demo3 11013, demo1 35958, demo2 24757, newgame 265, tour 2705 |
| `p_enemy65.s:A_FaceTarget` | `A_FaceTarget` | demo3 56, demo1 256, demo2 14, newgame 1, tour 0 |
| `p_enemy65.s:checkMeleeRange` | `checkMeleeRange` | demo3 6857, demo1 4567, demo2 680, newgame 99, tour 0 |
| `p_enemy65.s:checkMissileRange` | `checkMissileRange` | demo3 1244, demo1 755, demo2 175, newgame 12, tour 0 |
| `p_enemy65.s:P_CheckMeleeRange` | `P_CheckMeleeRange` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_enemy65.s:P_CheckMissileRange` | `P_CheckMissileRange` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_enemy65.s:A_Scream` | `A_Scream` | demo3 20, demo1 13, demo2 11, newgame 0, tour 0 |
| `p_enemy65.s:A_XScream` | `A_XScream` | demo3 0, demo1 0, demo2 2, newgame 0, tour 0 |
| `p_enemy65.s:A_Pain` | `A_Pain` | demo3 22, demo1 98, demo2 11, newgame 0, tour 0 |
| `p_enemy65.s:A_Fall` | `A_Fall` | demo3 21, demo1 17, demo2 12, newgame 0, tour 0 |
| `p_enemy65.s:A_PlayerScream` | `A_PlayerScream` | demo3 1, demo1 7, demo2 2, newgame 0, tour 0 |
| `p_attack65.s:P_RadiusAttack` | `P_RadiusAttack` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_attack65.s:PIT_RadiusAttack` | `PIT_RadiusAttack` | demo3 0, demo1 5, demo2 21, newgame 0, tour 0 |

Helpers: `p_attack65.s:blockPair`, `p_attack65.s:absDelta`, `p_enemy65.s:angleToAT`, `p_enemy65.s:distanceAT`, `p_enemy65.s:faceTarget`, `p_enemy65.s:loadTarget`, `p_enemy65.s:randMod`, `p_enemy65.s:startSound`, `p_enemy65.s:bfD0`, `p_enemy65.s:bfD1`, `p_enemy65.s:bfD2`, `p_enemy65.s:bfD3`, `p_enemy65.s:bfD4`, `p_enemy65.s:bfD5`, `p_enemy65.s:bfD6`, `p_enemy65.s:bfD7`.

What was built (2026-10-02):

| File | Content |
| --- | --- |
| `src/native/game/look/look.s` | `A_Look`, `lookForPlayers`, `behindFast` (its `bfTab` a jump table inside it: `bfD0`-`bfD7` have no code of their own), `angleToAT`, `distanceAT`, `loadTarget`, `checkMeleeRange`, `checkMissileRange`, `P_CheckMeleeRange`, `P_CheckMissileRange`, `faceTarget`, `A_FaceTarget`, `p_enemy_randMod`, `p_enemy_startSound`, `A_Scream`, `A_XScream`, `A_Pain`, `A_Fall`, `A_PlayerScream` |
| `src/native/game/look/radius.s` | `P_RadiusAttack` (`blockPair` folded in), `PIT_RadiusAttack` (`absDelta` folded in) |
| `src/native/game/look/look.inc` | the scratch block's places (`LK_*`), the `DELTA`, `ABS16`, `GETMO` macros |
| `src/native/game/look/part.mk`, `args.json` | the fragment; the entries' inputs and outputs |
| `tools/native/gparts/look.py` | the part's harness: the callFn logs, the captures, the routine-mode runs, the synthetic cases, the plants, `report.json` |
| `tests/test_native_game_look.py` | sources, build and sizes, a sample of the checkpoint, the three plants (22 s; the whole checkpoint with `DOOM_GS_FULL=1`) |

The native interfaces (for `chase`, `chasemove`, and `A_Explode`'s caller):

| Routine | In | Out |
| --- | --- | --- |
| `A_Look`, `A_FaceTarget`, `A_Scream`, `A_XScream`, `A_Pain`, `A_Fall`, `A_PlayerScream` (`ACTTAB`) | `GA_MO` the actor | nothing |
| `lookForPlayers` | `GA_0-1` the actor, A = allaround (0, 1) | A = 1 seen (its target the player's mobj, threshold 60), 0 not |
| `behindFast` | `GA_0-1` the actor, `GA_2-3` the target | C set: A = 1 behind, 0 in front; C clear: it cannot tell (A = $FF) |
| `checkMeleeRange`, `P_CheckMeleeRange` | `GA_0-1` the actor | A = 1, 0 |
| `checkMissileRange`, `P_CheckMissileRange` | `GA_0-1` the actor (with a target, as upstream: no NULL test) | A = 1, 0 |
| `faceTarget` | `GA_0-1` the actor | A = 1 (a target: faced), 0 none |
| `loadTarget` | `GA_0-1` the actor | `LK_AP`, `LK_AT` set; A:X the target; C set when there is one |
| `p_enemy_randMod` | A = c | A = `P_Random()` % c (math.s `sdiv16`) |
| `p_enemy_startSound` | A = the sound, `GA_0-1` the origin | `S_StartSound` |
| `P_RadiusAttack` | `GA_0-1` the spot, `GA_2-3` the source ($FFFF none), `GA_4-5` the damage | nothing (A_Explode: `GA_2-3` = the barrel's target, `GA_4-5` = 128) |
| `PIT_RadiusAttack` (`ITTAB_PIT_RadiusAttack`) | `GA_0-1` the thing | C set (go on) |

Every routine changes `GA_*`, `GT_0-6`, the math block and the API's
temporaries; `angleToAT` and `distanceAT` (the part's own: `LK_AP`,
`LK_AT`) give `M_R`. `P_RadiusAttack` keeps its block loop (x, y, yh,
xl, xh: 10 B) on the stack as upstream does; bombspot, bombsource and
bombdamage are `LK_BSPOT`, `LK_BSRC`, `LK_BDMG` (upstream's `AT_B*`
globals, the same lifetime).

## 2. Requests

Each with what, why (the evidence), its effect on other parts, and the
part's stand-in until it is applied.

**1. `INLINED` for this part's helpers.** What: in `glayout.py`'s
`INLINED`, `'look': ('p_enemy65.s:bfD0', 'p_enemy65.s:bfD1',
'p_enemy65.s:bfD2', 'p_enemy65.s:bfD3', 'p_enemy65.s:bfD4',
'p_enemy65.s:bfD5', 'p_enemy65.s:bfD6', 'p_enemy65.s:bfD7',
'p_attack65.s:blockPair', 'p_attack65.s:absDelta')`. Why: `bfD0`-`bfD7`
are the cases of `behindFast`'s computed jump (`bf_d0`.. in `look.s`,
`jmp (bf_tab,x)`), `blockPair` is `radius.s`'s local `pair`/`shr7` of
`P_RadiusAttack`, `absDelta` its local `abs32` of `PIT_RadiusAttack`; the
placement gives them bytes and eight different groups today (`bfD0` in the
core, `bfD1` group 19, ...). Effect: none on other parts; the placement's
estimates.

**2. `P_AproxDistance` (`aproxdist`) in the tic images.** What: add
`aproxdist` (math.s:1016-1087, 136 B) to the game's math, `math.s -D
GAMEMATH` (`mathgame.inc`'s text, as wave 2 did for `pta3` and the sines:
damage R1), so that the tic images' core has it. Why: `distanceAT`
(`p_enemy65.s:484-506`) calls `P_AproxDistance`; the tic images link
`math-r.o` (`-D RENDER`: no `aproxdist`, `math.s:46-48`) and `math-g.o`
(pta3, pta_oct, finesine, finecosine, cosexc only): `ld65: Unresolved
external 'aproxdist'`. Stand-in: `look.s`'s `distanceAT` carries math.s's
code (`lk_standin` .. `lk_standin_end`, marked STAND-IN, 136 B); when
applied it becomes `jmp aproxdist` and the stand-in goes. Effect: every
part that reaches `P_AproxDistance` needs it resident: `xymove`
(`slideMove`, `p_mobj65.s:661`), `path` (`p_path65.s:284`), `missile`
(`destDelta`, `p_spawn65.s:573`); the core's room 136 B less.

**3. Placement units (`gplace.py` `AFFINITY`).** What: three units,
`('p_enemy65.s:A_Look', 'p_enemy65.s:lookForPlayers',
'p_enemy65.s:behindFast', 'p_enemy65.s:angleToAT',
'p_enemy65.s:distanceAT', 'p_enemy65.s:loadTarget',
'p_enemy65.s:checkMeleeRange', 'p_enemy65.s:checkMissileRange',
'p_enemy65.s:P_CheckMeleeRange', 'p_enemy65.s:P_CheckMissileRange',
'p_enemy65.s:faceTarget', 'p_enemy65.s:A_FaceTarget')` (1,821 B with the
stand-in, 1,685 B without), `('p_enemy65.s:A_Scream',
'p_enemy65.s:A_XScream', 'p_enemy65.s:A_Pain', 'p_enemy65.s:A_Fall',
'p_enemy65.s:A_PlayerScream', 'p_enemy65.s:randMod',
'p_enemy65.s:startSound')` (163 B) and `('p_attack65.s:P_RadiusAttack',
'p_attack65.s:PIT_RadiusAttack')` (629 B). Why: today's placement (from
estimates) spreads the part over eight groups (2, 5, 7, 11, 13, 15, 16,
21): `lookForPlayers` (group 15) calls `behindFast`, `angleToAT` and
`distanceAT` (group 21) and `A_Look` (16) calls `lookForPlayers` (15),
so a call pages two groups in and out: `behindFast` alone takes 41,040
CPU cycles at the median in routine mode (slots empty at the call), for
about 400 of its own; `A_Look` runs 5.3 times a tic in demo3 [M: VC] and
GAME.md 4.3 puts `A_Look`, `lookForPlayers` and `behindFast` in the core
(look is 5.7% of the game's instructions [M: HEAT]). Effect: the core's
room or a slot group of 1.7 KB; the placement's report decides.

**4. `OWN_STACK` for `P_RadiusAttack` and `A_Look`.** What: in
`glayout.py`'s `OWN_STACK`, `'p_attack65.s:P_RadiusAttack': 10` and
`'p_enemy65.s:A_Look': 1`. Why: `P_RadiusAttack` keeps its block loop's
five words on the stack across `P_BlockThingsIterator`
(`radius.s`, upstream's `p_attack65.s:893-930`); `A_Look` keeps the
type across `mi_get` and the sound (its calls there are the core's).
Measured lowest S: 184 in `P_RadiusAttack`'s runs (the driver starts at
$EF). Effect: `gcallgraph.py --stack` counts them.

**5. The parts' interfaces in `src/native/game/README.md`.** What: add
the table above ("The native interfaces") to README's "The parts'
interfaces" (rows for `lookForPlayers`, `behindFast`, `checkMeleeRange`,
`checkMissileRange`, `faceTarget`, `loadTarget`, `p_enemy_randMod`,
`p_enemy_startSound`, `P_RadiusAttack`, `PIT_RadiusAttack`). Why: `chase`
(wave 6: `A_Chase` calls `lookForPlayers` with allaround 0 and 1,
`checkMeleeRange`, `checkMissileRange`; the attacks call `faceTarget`,
`loadTarget`, `randMod`, `startSound`, `checkMeleeRange`
[R `p_enemy65.s:651-1999`]; `A_Explode` jumps to `P_RadiusAttack`) and
`chasemove` (`P_NewChaseDir`'s `loadTarget`, `p_enemy65.s:1176`) call them
by `FCALL`. Effect: documentation only.

**6. A note in README's "Testing a part" on capturing at a dispatch
stub.** What, the text: "ref816's `--capture` does not count a nested
call of the routine it is capturing: a capture at `p_tick65.s:callFn`
whose call enters `callFn` again before it returns (an `A_Look` that
sees: `P_SetMobjState` runs the see state's action through `callFn`)
makes every later requested hit of the same ref816 run one call late, so
a case may be another action's call. The call log's `hit` counts every
call. Put such a hit last in its capture run, and check each case (its
`FN_P` and gametic at the entry: `tools/native/gparts/look.py`
`nesting_hits`, `verify`)." Why: `look.py`'s first captures of
`A_Look` at `callFn` gave 27 cases of `A_Chase` or a thinker
(`FN_P` at the entry not the logged `A_Look`; hit 24955 of demo3 alone in
its run after the seeing hit 2469 entered `A_Chase`, hit 24956; alone it
was right). Effect: any part capturing a dispatch target at its stub
(`callFn`, `callLN`, `callLN2`, `callTrav`) where the target can re-enter
the stub (`tracel`'s `CAPTURE_AS` at `callLN` is safe only while
`PIT_AddLineIntercepts` never re-enters `callLN`).

## 3. Results

The lean checkpoint (the owner's rules of 2026-10-02: at most 40 calls
a routine chosen by branch, the `$A5` machine only, `f121` only):
`python3 tools/native/gparts/look.py --log --capture --check --plants
--jobs 2` (`report.json`): **305 runs, 0 failures, 0 stray writes**.

| Entry | Runs | Kinds | Branches (the reference's) | CPU cycles median / worst | Lowest S |
| --- | ---: | --- | --- | --- | ---: |
| `lookForPlayers` | 40 | captured | allaround 0 not seen 14, allaround 0 seen 13, allaround 1 not seen 13; the player dead 3 | 62,829 / 1,109,352 | 207 |
| `behindFast` | 56 | 40 captured, 16 synthetic | cannot tell 13, front 14, behind 13; each k: the edge (v = T, cannot tell) and one beyond (behind) | 41,040 / 41,120 | 227 |
| `checkMeleeRange` | 40 | captured | false 37, true 3 | 56,593 / 57,887 | 222 |
| `checkMissileRange` | 40 | captured | true 18, false 20, just hit 2 | 86,530 / 693,220 | 205 |
| `A_Look` | 60 | 20 captured that do not see, 20 that see: each stops at `A_Chase` (unbuilt, wave 6), and its variant with `A_Chase` removed runs whole | of the 40: a sound target 6, ambush with a sound target 9, ambush without 7, neither 18 | 86,578 / 1,166,846 | 202 |
| `A_FaceTarget` | 24 | 20 captured, 4 synthetic (a shadow target) | | 68,095 / 68,498 | 217 |
| `A_Scream`, `A_Pain`, `A_Fall` | 10 each | captured | | 24,359; 23,623; 12,920 | 225 |
| `A_PlayerScream`, `A_XScream` | 1, 2 | captured (demo3, demo2) | | 20,617 | 227 |
| `P_RadiusAttack` (`PIT_RadiusAttack` inside) | 12 | demo2's three barrels (`A_Explode` at `callFn`: the reference's `P_RadiusAttack` by `--call` with A_Explode's arguments); synthetic: a thing moved onto the spot (its distance clamped at 0), damage 400; 4 stop at `A_Lower` (the player's death: part `pspr`) with their 4 variants | in range and not damaged (P_CheckSight false: behind a wall): 1 of 5 at damage 128, 17 of 26 at damage 400 | 602,720 / 1,976,870 | 184 |

Cycles are routine mode with every slot empty at the call (each cross
group `FCALL` loads a group: request 3), an upper bound, `f121`.

Planted bugs (each in a scratch copy, built in a temporary directory,
deleted): behindFast's 90° edge on the other side (v = T tells): 9 of 56
runs fail (the 8 edge cases and one captured call at the edge); the
shadow's `P_Random` shift (<< 4): 4 of 24 (the shadow targets); the radius
damage's distance not clamped at 0: 2 of 11 (the things on the spot).
"The missile range not halved for its type" is not planted: upstream's
`checkMissileRange` has no halving (no type of episode 1 has it there:
`p_enemy65.s:1080-1112` takes 64, then 128 more with no melee state, and
clamps at 200).

Sizes (the part's image): 2,613 B, of which 136 B the `aproxdist`
stand-in (request 2): own 2,477 B of 2,300 (+7.7%; upstream 1,729 B);
`look.s` 1,984, `radius.s` 629. No build warning.

Test: `tests/test_native_game_look.py`, 7 tests, 22 s (default: one case
an entry, the synthetic cases the plants need, the three plants on them);
`DOOM_GS_FULL=1` runs the whole checkpoint and each plant on every case of
its entry.

`build/` growth: `build/native/game/look/` 29 MB (the cases 256, the
two runs' bases, the image); every temporary directory deleted.

## 4. Open points

- (Wave 2 as integrated) `R_PointToAngle3`, `finesine`, `finecosine` are resident (`jsr pta3` ...: the core's `math-g.o`, wave 2 as integrated; `damage.md` R1).
- Unreached by the sampled calls: `checkMissileRange`'s reaction-time
  return (no chosen call has a reaction time with the target seen and not
  just hit); `lookForPlayers` with allaround that sees (no such call in
  demo3); `checkMeleeRange` with no target; `P_CheckMeleeRange` and
  `P_CheckMissileRange` (no caller in the release: each is `FCALL` of the
  checked routine); `A_Look`'s see sounds are not told apart (posit,
  bgsit: only `P_Random`'s index is compared).
- The sounds: the routine harness compares no sound event (R6), so
  `A_Pain`, `A_XScream`, `A_PlayerScream` change no compared state and
  `A_Scream`, `A_Look` only `P_Random`'s index; the sound numbers wait for
  the reference's sound events in a case (`lines.md` request 5).
- `A_Look`'s seeing calls and the radius attack's deaths are checked only
  with `A_Chase` and `A_Lower` removed (stop checks and their variants)
  until `chase` (wave 6) and `pspr` (wave 3) fill `ACTTAB`.
- No release run calls `P_RadiusAttack` by `JSL`: its cases come from
  `A_Explode`'s jumps (demo2's three barrels) and their synthetic
  variants.

## 5. The integration of wave 3 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 3 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| 1 the helpers inlined | **Accepted**: `glayout.INLINED['look']` as written |
| 2 `aproxdist` in the tic images | **Accepted**: `aproxdist` moved from `math.s` into `mathgame.inc` (so `math-g.o` has it: 826 B in the core, 154 B more; the full build's `MATHW` the same size in another order); `distanceAT` is `jmp aproxdist` and the stand-in is gone; the test checks no stand-in is left. `MATH.md`; `xymove.md`, `path.md`, `missile.md` noted |
| 3 the placement units | **Accepted as units, not the core**: the look and ranges (group 14, slot 2), the sounds and the fall, the radius attack (`gplace.py` packs the small units). GAME.md 4.3's wish to put `A_Look`, `lookForPlayers` and `behindFast` in the core waits for the core's levers |
| 4 `OWN_STACK` | **Accepted**: `P_RadiusAttack` 10, `A_Look` 1 |
| 5 the interfaces | **Accepted**: README "The parts' interfaces"; `chase.md`, `chasemove.md` noted |
| 6 capturing at a dispatch stub | **Accepted**: README "Testing a part" |
