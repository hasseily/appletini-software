# Part `chase` (wave 6)

The record of milestone 10's part `chase` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 6; upstream 1400 B, native budget 1800 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 6's `chase` (2026-10-02, lean rules).
- Files: `src/native/game/chase/*.s`, `src/native/game/chase/part.mk`, `src/native/game/chase/args.json`, `tests/test_native_game_chase.py`, this file; tools (if any) `tools/native/gparts/chase*.py`; build output `build/native/game/chase/` (`make -s -C src/native -f game.mk part P=chase ROOT=$PWD`).
- Its scratch block: `SB_CHASE` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_enemy65.s`: `A_Chase:621`, `A_PosAttack:1885`, `A_SPosAttack:1911`, `A_TroopAttack:1945`, `A_SargAttack:1968`, `A_CyberAttack:1982`, `A_BruisAttack:1992`, `A_Explode:2060`, `A_BossDeath:2079` (E1M8: the floor of tag 666); helpers `lineAttack`, `aimLine`, `spreadAngle`, `damageTarget`, `spawnMissile`

Its checkpoint (GAME.md 2.4): `A_Chase` (demo3 6.1 a tic [M: VC]: 600 by path), every attack; synthetic: `A_BossDeath` on E1M8 with the last baron

Its planted bugs (each must fail the named check): `movecount` decremented after the move; the attack's `P_Random` order; `A_BossDeath`'s floor type

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_enemy65.s:A_Chase` | `A_Chase` | demo3 12991, demo1 8846, demo2 1679, newgame 128, tour 0 |
| `p_enemy65.s:A_PosAttack` | `A_PosAttack` | demo3 8, demo1 16, demo2 2, newgame 1, tour 0 |
| `p_enemy65.s:A_SPosAttack` | `A_SPosAttack` | demo3 9, demo1 26, demo2 3, newgame 0, tour 0 |
| `p_enemy65.s:A_TroopAttack` | `A_TroopAttack` | demo3 14, demo1 79, demo2 4, newgame 0, tour 0 |
| `p_enemy65.s:A_SargAttack` | `A_SargAttack` | demo3 1, demo1 16, demo2 0, newgame 0, tour 0 |
| `p_enemy65.s:A_CyberAttack` | `A_CyberAttack` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_enemy65.s:A_BruisAttack` | `A_BruisAttack` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_enemy65.s:A_Explode` | `A_Explode` | demo3 0, demo1 1, demo2 3, newgame 0, tour 0 |
| `p_enemy65.s:A_BossDeath` | `A_BossDeath` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |

Helpers: `p_enemy65.s:lineAttack`, `p_enemy65.s:aimLine`, `p_enemy65.s:spreadAngle`, `p_enemy65.s:damageTarget`, `p_enemy65.s:spawnMissile`.

### 1.1 What was built

| File | What |
| --- | --- |
| `src/native/game/chase/chase.s` | The nine actions and the five helpers (14 `ROUTINE`s), and `bd_floors`, the stand-in of R1 |
| `src/native/game/chase/chase.inc` | The scratch block's places (`CH_*` for `A_Chase`, `AK_*` for the attacks, `BD_*` for `A_BossDeath`: apart, so that a chase action that a dispatched action reaches inside another cannot change the outer one's bytes), the macros |
| `src/native/game/chase/part.mk`, `args.json` | The fragment (wave 6); the nine entries, each an `ACTTAB` action: upstream's `_Dp[0-3]` to `GA_MO` as a mobj |
| `tools/native/gparts/chase.py` | The lean checkpoint: the call logs, the selection by branch, the captures at `callFn`, the synthetic cases, the runs (part mobjstate's `Prepared` and `run_one`, part look's stop handling), the plants, `report.json` |
| `tests/test_native_game_chase.py` | Sources, build and size, the checkpoint (default: 13 jobs; `DOOM_GS_FULL=1`: all), the three plants; 7 tests, 18 s |

### 1.2 How the native code follows upstream

- `A_Chase` is upstream's with `TICSTEP` 1 (the release's [R `tics.inc:9-11`]): `p_enemy65.s:641-646` (reactiontime), `:647-676` (threshold), `:730-756` (the turn: after the mask only the angle's high byte is not 0, so the 16-bit difference's sign is that byte's bit 7 and the step `ANG90 / 2` is `$20` on it; the four bytes are written whenever movedir < 8, as upstream writes both words), `:760-791`, `:794-820` (melee), `:823-849` (missile), `:852-901` (pursuit), `:904-951` (the move), `:954-976` (the active sound: `P_Random` only when the type has one).
- The attacks are upstream's in its order of calls (`:1885-2015`); `spreadAngle` [R `:1837-1854`]: the first `P_Random` less the second, 16 bits, `<< 4` added to the angle's high word; `randMod` is part look's `p_enemy_randMod` (math.s's `sdiv16`); the damages are byte products (at most 80).
- `loadTarget` and `startSound` (part look's) are done in place: the target read from the actor's cache line, `S_StartSound` (the core's hook) called with `jsr`.
- `A_BossDeath` [R `:2079-2142`]: the map a word (8), the type, the player's health (> 0, signed 16 bits), then the thinker list from `G_THFIRST` as part teleport walks it (`teleport.s` `destination`): a special's next from its record, a mobj's from the planes; `P_MobjThinker` whether `CLEAN` or not (upstream masks its kind cache, `and ##0x00ff` [R `:2109`]); another baron with health > 0 ends it.
- `A_Explode` [R `:2060-2068`]: `P_RadiusAttack(it, its target, 128)` (part look).

### 1.3 The native interfaces

| Routine | In | Out |
| --- | --- | --- |
| `A_Chase`, `A_PosAttack`, `A_SPosAttack`, `A_TroopAttack`, `A_SargAttack`, `A_CyberAttack`, `A_BruisAttack`, `A_Explode`, `A_BossDeath` (`ACTTAB`) | `GA_MO` the actor | nothing; change `GA_*`, `GT_*`, `GS_*`, the math block |
| `aimLine` | `AK_AP` the actor, `AK_ANG` the angle | `AK_SLOPE` = `P_AimLineAttack(actor, angle, MISSILERANGE)` |
| `lineAttack` | A the damage; `AK_AP`, `AK_ANG`, `AK_SLOPE` | `P_LineAttack(actor, angle, MISSILERANGE, slope, damage)` |
| `spreadAngle` | `AK_BASE` | `AK_ANG` = base + ((`P_Random()` - `P_Random()`) << 20) |
| `damageTarget` | A the damage; `AK_AP` | `P_DamageMobj(actor->target, actor, actor, damage)` |
| `spawnMissile` | A the type; `AK_AP` | `P_SpawnMissile(actor, actor->target, type)` |

No part outside `chase` calls the helpers (upstream's are local to `p_enemy65.s`'s attacks).

## 2. Requests

Each is a change to a shared file, for the wave's integrator. The part builds and passes as it is (R1's stand-in is in its own source, marked).

**R1. `A_BossDeath`'s floors: `EV_DoFloor` by a tag (parts `evfloor`, `secfind`), or the stand-in accepted.** What, either:

(a) part evfloor exports `EV_DoFloorTag` (A:X the tag, a word; Y the floor type): the body of `EV_DoFloor` after its line's tag is read, with part secfind's tag search from a tag (`P_FindSectorFromTag`: A:X the tag, Y the start: the loop of `P_FindSectorFromLineTag` after its `ln_get`); `EV_DoFloor` and `P_FindSectorFromLineTag` read the line's tag and fall into them. Then `bd_floors` (130 B) becomes

        lda #<666
        ldx #>666
        ldy #UC_LOWERFLOORTOLOWEST
        FCALL EV_DoFloorTag

(b) or the stand-in `bd_floors` stays (`chase.s`, marked "STAND-IN of request 1").

Why: upstream's `A_BossDeath` calls `EV_DoFloor` with a junk line of tag 666 in its near scratch (`AC_JUNK` with `OFS_LINE_TAG` = 666 [R `p_enemy65.s:75`, `:2134-2141`]). A native line's tag is a byte (`LN_TAG`, sign-extended by `P_FindSectorFromLineTag` [R `src/native/game/secfind/secfind.s:403-413`]; no E1 line has a tag above 127), so no line handle can carry 666. The stand-in does `EV_DoFloor`'s `lowerFloorToLowest` for the tag itself, in `EV_DoFloor`'s order (the sectors from 0, a sector with a moving floor skipped): part evfloor's `newFloor` (A the sector, Y the type), then the fields its `floorUp` (down) and `setDest` write, through llayout's `SPFL_DIRECTION`, `SP_SECTOR`, `SPFL_SPEED`, `SPFL_DEST` and the API (`sp_get`, `sp_dirty`), and part secfind's `P_FindLowestFloorSurrounding` for the destination. Checked: the synthetic "last baron" case on the tour's E1M8 makes one floor, equal to the reference's, and the plant `boss-floor-type` fails it. (a) keeps the making of a floor in one part (a change to evfloor's floors would not need the stand-in followed); (b) costs 130 B of cold code (`A_BossDeath`'s group) and nothing else.
Other parts: (a) evfloor and secfind gain an entry each (a few bytes: the tag in A:X instead of read from the line), their checks unchanged; (b) none.

**R2. Placement (`gplace.py` `AFFINITY`).** What: one unit for the attacks and their helpers:

    # the monsters' attacks and their helpers (chase.md R2)
    ('p_enemy65.s:A_PosAttack', 'p_enemy65.s:A_SPosAttack',
     'p_enemy65.s:A_TroopAttack', 'p_enemy65.s:A_SargAttack',
     'p_enemy65.s:A_CyberAttack', 'p_enemy65.s:A_BruisAttack',
     'p_enemy65.s:lineAttack', 'p_enemy65.s:aimLine',
     'p_enemy65.s:spreadAngle', 'p_enemy65.s:damageTarget',
     'p_enemy65.s:spawnMissile'),

Why: today's placement (from estimates) puts the attacks in groups 4 and 6 (slot 1), `lineAttack`, `aimLine`, `spreadAngle` in group 17 (slot 2, with look's screams), `damageTarget` in group 6 and `spawnMissile` alone in group 22 (slot 1): `A_TroopAttack` (group 4) loads group 22 over itself for `spawnMissile`, which loads `P_SpawnMissile`'s group 8 over that, and each return loads them back; `A_SPosAttack`'s three pellets call `spreadAngle` and `lineAttack` in slot 2 six times. Measured bytes (the part's image): `A_PosAttack` 122, `A_SPosAttack` 145, `A_TroopAttack` 90, `A_SargAttack` 69, `A_CyberAttack` 51, `A_BruisAttack` 89, `lineAttack` 48, `aimLine` 49, `spreadAngle` 62, `damageTarget` 45, `spawnMissile` 41: the unit is 811 B. `A_Chase` (730 B) stays a unit of its own (GAME.md 4.3's rule: never in the slot of `pMove` and `newChaseDir`); `A_Explode` (31 B) and `A_BossDeath` (280 B with the stand-in) are cold (no demo calls `A_BossDeath`; `A_Explode` 4 calls in the three demos). Other parts: placement only.

**R3. `OWN_STACK`.** What: `glayout.OWN_STACK['p_enemy65.s:A_Chase'] = 1`. Why: `A_Chase` keeps one byte on the stack over a call of the object API (`php` over `mo_dirty` after `movecount - 1`; `pha` over `mo_get` in its `ch_flag`); every `FCALL` of `A_Chase` is made with its own pushes popped. The lowest S of the runs (`report.json`): `$A8` (`A_TroopAttack`'s paging case: `P_DamageMobj` under `checkMissile`, `P_TryMove`, `checkThing`), `$B9` for `A_Chase`. Other parts: `gcallgraph.py --stack` grows by at most 1 B.

**R4. The interfaces (`src/native/game/README.md` "The parts' interfaces").** What: the row

    | `A_Chase`, `A_PosAttack`, `A_SPosAttack`, `A_TroopAttack`, `A_SargAttack`, `A_CyberAttack`, `A_BruisAttack`, `A_Explode`, `A_BossDeath` (`chase`, `ACTTAB`) | `GA_MO` the actor | nothing; change `GA_*`, `GT_*`, `GS_*`, the math block |

Why: part `tic` (wave 6) reaches them through `P_SetMobjState`'s `ACTTAB` (a state's end in the walk). Other parts: none.

**Budget.** 1,852 B in the image's map, 1,722 B without the stand-in (`bd_floors`, 130 B) against 1,800 (4% under; with it 2.9% over, under the 10% that needs a request): `A_Chase` is 730 B, its 13 `FCALL`s through `fc_call` 6 B each.

**Exclusions.** None new: R1-R7 of GAME.md 3.5 only.

**Arithmetic helpers (GAME.md 2.4).** None of the list is this part's. `spreadAngle`'s shift and the damages' products take `P_Random`'s values, no input a random check could give; every attack case compares their result (the angle a shot takes, the damage).

## 3. Results

The lean checkpoint (2026-10-02, the part's image: waves 1-5 integrated and `chase`, with the integrator's placement of wave 5, `shared/placement.json`; fill `$A5`, profile `f121`, routine mode with R1-R7; mobjstate's shared stray rule):

    python3 tools/native/gparts/chase.py --build                  # 1 s
    python3 tools/native/gparts/chase.py --log --jobs 2           # 19 s (demo3, demo1, demo2, tour)
    python3 tools/native/gparts/chase.py --capture --jobs 2       # 161 cases, 80 s
    python3 tools/native/gparts/chase.py --check --jobs 2         # 169 jobs, 120 s
    python3 tools/native/gparts/chase.py --plants --jobs 2        # 55 s
    python3 -m unittest discover -s tests -p test_native_game_chase.py   # 7 tests, 18 s

**169 runs, 0 failures, 0 stray writes, the lowest S `$A8` (168).**

| Entry | Calls in the three demos | Run: captured + synthetic | Failed | Cycles median / worst (`f121`) | Lowest S |
| --- | ---: | ---: | ---: | --- | ---: |
| `A_Chase` | 23,514 | 40 + 0 | 0 | 935,111 / 2,872,791 | 185 |
| `A_PosAttack` | 26 | 24 + 0 | 0 | 5,529,456 / 9,817,285 | 181 |
| `A_SPosAttack` | 38 | 35 + 0 | 0 | 9,771,180 / 16,050,885 | 181 |
| `A_TroopAttack` | 97 | 40 + 1 (paging) | 0 | 778,706 / 946,214 | 168 |
| `A_SargAttack` | 17 | 17 + 0 | 0 | 89,427 / 512,106 | 206 |
| `A_CyberAttack` | 0 | 0 + 2 | 0 | 991,323 | 182 |
| `A_BruisAttack` | 0 | 0 + 2 | 0 | 808,619 | 185 |
| `A_Explode` | 4 | 4 + 0 | 0 | 1,422,174 / 1,700,547 | 179 |
| `A_BossDeath` | 0 | 0 + 4 | 0 | 120,845 / 485,232 | 221 |

The cycles are the W65C02S's from the routine's entry to its return, in routine mode with every slot empty at the call (group loads included: an upper bound); `report.json` has the fabric clocks too.

**The selection.** A call log of each run (`callfn-RUN.json`: callFn's hits by action, the gametic, the routines the action called directly with the results of `lookForPlayers`, `checkMeleeRange`, `checkMissileRange`, `P_CheckSight`, `pMove`, `faceTarget`, and whether it entered `callFn` again before its return) gives each call a signature, its branch; at most 40 calls a routine by signature, the smallest classes first: `A_Chase` 30 of demo3's (23 classes) and 10 of demo1's (`lookForPlayers` = 1 is demo1's only), every attack call of demo3 and demo1 (`A_TroopAttack` 14 + 26 of 79 by class), `A_Explode` demo2's 3 and demo1's 1. Each case is checked to enter its logged action at its logged tic (`verify()`). `A_Chase`'s 26 signatures run: a target that cannot be shot (`lookForPlayers` 0 then the spawn state; 1), just attacked (`newChaseDir` alone), melee (a sergeant: its melee state, `MF_JUSTHIT`), the missile state (with and without the melee check before it), the pursuit (`P_CheckSight` 0 and 1, `lookForPlayers` after), the move (`pMove` 1; 0 then `newChaseDir`; movecount run out). Of the 40 cases 6 have a reactiontime, 6 a threshold (1 with a dead target), 14 turn, 17 a movecount of 0.

**The synthetic cases** (the reference's own `callFn` by `ref816 --call` on a case's state with pokes; each checked to take its path on the reference's side):

- `A_CyberAttack`, `A_BruisAttack`: a melee and a missile `A_TroopAttack` of demo1 with `FN_P` the action (no run calls them; the cyberdemon's is reached through the rocket cheat).
- **The paging case** (GAME.md 3.4, review 1): demo3's `A_TroopAttack` h72104 (a shot) with the shootable monster nearest the imp (a barrel 32 units away, in a block the shot's check walks) moved 10 units in front of it at its z: the troopshot's `checkMissile` → `P_TryMove` → `checkThing` → `P_DamageMobj` hits it (the reference's barrel 20 → 11 health), across the integrator's placement: `A_TroopAttack` group 4, `spawnMissile` 22, `P_SpawnMissile` and `checkThing` 8, `P_TryMove` 2 (slot 1); `checkMissile` and `checkPos` 9, `P_DamageMobj` 16 (slot 2). 20 group loads; the state after equal to the reference's, so each return landed in its group.
- `A_BossDeath` on E1M8: the tour's `A_Look` call at tic 1304 (the tour run's first capture, so that its base is that machine: every page exact), the actor one of E1M8's two barons: "last baron" (both barons' health 0: one floor of tag 666 made, equal), "another alive" (nothing), "player dead" (nothing), "not a baron" (`A_Look`'s own actor: nothing).

**Planted bugs** (each in a scratch copy, built in a temporary directory that is deleted; `--plants`, every case of its entry):

| Plant | Fails |
| --- | --- |
| `movecount-after`: `pMove` first, then `--movecount` and its test | 13 of 40 `A_Chase` runs (`validcount`, a mobj's x: a move made or missed) |
| `random-order`: `A_PosAttack`'s damage `P_Random` before the spread's two | 24 of 24 (the shot's line stamps, the puff's place) |
| `boss-floor-type`: `lowerFloor` for `lowerFloorToLowest` | 1 of 4 (the "last baron" case: `floor[0].type`) |

The test file's default mode (13 jobs: the first captured call of each entry, three of `A_Chase`, the two synthetic attacks, the paging case, the last baron) catches the three too.

**Sizes** (the part's image): 1,852 B (`A_Chase` 730, `A_BossDeath` 280 with `bd_floors` 130, the six attacks 566, the five helpers 245, `A_Explode` 31); 1,722 B without the stand-in, of 1,800.

**build/**: `build/native/game/chase/` 47 MB (the 161 cases with the four runs' bases, the call logs, the image); every temporary directory of the part deleted.

## 4. Open points

- **R1** (the stand-in `bd_floors`) waits for the integrator's choice.
- **Not reached by the sample** (lean: 40 calls a routine, `$A5`, `f121`): `A_Chase` at nightmare (its two skill tests: no run plays skill 4), an actor with no target at all (the 40 have one; the no-target branch ran with targets that cannot be shot), a threshold with no target, whether the active sound's `P_Random` < 3 was taken (the sound is R6's; `P_Random`'s index is compared in every case); `A_BossDeath` with a tag-666 sector whose floor already moves; `A_CyberAttack` and `A_BruisAttack` only synthetic. The `$5A` fill and `fastpath` were not run.
- The paging case is one synthetic call (no captured shot hits a monster at once).

- (Wave 2 as integrated) `R_PointToAngle3`, `finesine`, `finecosine` are resident (`jsr pta3` ...: the core's `math-g.o`, wave 2 as integrated).
- (Wave 3 as integrated) Part `look`'s `lookForPlayers` (A = allaround), `checkMeleeRange`, `checkMissileRange`, `faceTarget`, `loadTarget`, `p_enemy_randMod`, `p_enemy_startSound` and `P_RadiusAttack` (for `A_Explode`) are built; their interfaces are in README "The parts' interfaces"; `P_AproxDistance` is the core's `aproxdist`.
- (Wave 5 as integrated) Part `chasemove`'s `pMove`, `newChaseDir` (and `tryWalk`), part `attack`'s `P_LineAttack`, `P_AimLineAttack` (the target in GW's `GM_LINETARGET`) and part `missile`'s `P_SpawnMissile` are built; README "The parts' interfaces".

## 5. The integration of wave 6 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 6 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 `A_BossDeath`'s floors | **(b) accepted**: the stand-in `bd_floors` stays, now marked as accepted in `chase.s`. (a) would change two parts already verified (`evfloor`'s `EV_DoFloor` and `secfind`'s tag search), and a lean merge does not rerun their checkpoints. The final integration may still choose (a) |
| R2 the placement | **Accepted**: the attacks' unit in `gplace.AFFINITY`, group 5 (slot 2, 1,897 B in all). `spawnMissile` reaches `P_SpawnMissile` in group 14 (slot 1). `A_Chase` is in group 10 (slot 2, with `P_Ticker` and the psprites). `pMove` and `newChaseDir` are in group 13 (slot 1): A_Chase's rule kept |
| R3 `OWN_STACK` | **Accepted** as written |
| R4 the interfaces | **Accepted**: README "The parts' interfaces" (wave 6's row) |

Sizes in the wave image: `chase.o` 1,813 B with the stand-in, against
1,800 (0.7% over). The test module (default mode): 7 tests OK.
