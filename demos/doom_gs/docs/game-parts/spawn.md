# Part `spawn` (wave 2)

The record of milestone 10's part `spawn` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 2; upstream 842 B, native budget 1100 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 2's `spawn` (built 2026-10-02, on a2vm against `ref816`; nothing committed).
- Files: `src/native/game/spawn/*.s`, `src/native/game/spawn/part.mk`, `src/native/game/spawn/args.json`, `tests/test_native_game_spawn.py`, this file; tools (if any) `tools/native/gparts/spawn*.py`; build output `build/native/game/spawn/` (`make -s -C src/native -f game.mk part P=spawn ROOT=$PWD`).
- Its scratch block: `SB_SPAWN` (32 B, `ggame.inc`), laid out in
  `src/native/game/spawn/sp.inc`.
- What it built: `spawn.s` (`P_SpawnPuff`, `P_SpawnBlood`, `zNoise`,
  `spawnXYZ`, `ticsNoise`, `P_IsAttackRangeMeleeRange`), `zmove.s`
  (`P_ZMovement`, `missileHit`, `shr3`, `p_mobj_isPlayer`), `sptest.s`
  (test builds only, the driver's area: `sp_bulk`, shr3's random check),
  `sp.inc`, `part.mk`, `args.json`; the harness
  `tools/native/gparts/spawn.py` (it imports wave 1's
  `gparts/mobjstate.py` for the generic parts: `stale_link_problems`,
  `allowed_main`/`allowed_aux`, the write log's clock, `native_checks`,
  `summarize`, `ref_call`); `tests/test_native_game_spawn.py`.

The routines (GAME.md 2.4's row):

`p_spawn65.s`: `P_SpawnPuff:375`, `P_SpawnBlood:401`, helpers `moArg`, `saveXYZ`, `zNoise`, `spawnXYZ`, `ticsNoise`, `thArg`; `p_attack65.s`: `P_IsAttackRangeMeleeRange:622`; `p_mobj65.s`: `P_ZMovement:949` (gravity, the floor and ceiling hits, a missile's explosion, the player's squat), `missileHit:880`, `shr3:895`, `isPlayer:1230`

Its checkpoint (GAME.md 2.4): Every captured `P_ZMovement` (DEMO1 5,864: 300 by path), every puff and blood; synthetic: a mobj at the ceiling, a missile into the floor

Its planted bugs (each must fail the named check): gravity after the floor clamp; the puff's z `P_Random` taken after the tics' (the index); blood's state thresholds one off; the squat's `deltaviewheight` shift

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_spawn65.s:P_SpawnPuff` | `P_SpawnPuff` | demo3 92, demo1 191, demo2 77, newgame 3, tour 0 |
| `p_spawn65.s:P_SpawnBlood` | `P_SpawnBlood` | demo3 125, demo1 96, demo2 33, newgame 0, tour 0 |
| `p_attack65.s:P_IsAttackRangeMeleeRange` | `P_IsAttackRangeMeleeRange` | demo3 92, demo1 191, demo2 77, newgame 3, tour 0 |
| `p_mobj65.s:P_ZMovement` | `P_ZMovement` | demo3 3088, demo1 5864, demo2 1635, newgame 53, tour 0 |
| `p_mobj65.s:missileHit` | `missileHit` | demo3 123, demo1 116, demo2 57, newgame 2, tour 0 |
| `p_mobj65.s:shr3` | `shr3` | demo3 21, demo1 18, demo2 22, newgame 1, tour 0 |
| `p_mobj65.s:isPlayer` | `p_mobj_isPlayer` | demo3 6522, demo1 14231, demo2 7390, newgame 381, tour 70 |

Helpers: `p_spawn65.s:moArg`, `p_spawn65.s:saveXYZ`, `p_spawn65.s:zNoise`, `p_spawn65.s:spawnXYZ`, `p_spawn65.s:ticsNoise`, `p_spawn65.s:thArg`.

### The native conventions (for the parts that call these)

| Routine | In | Out | Notes |
| --- | --- | --- | --- |
| `P_SpawnPuff` | `GA_X`, `GA_Y`, `GA_Z` (x, y, z) | | `zNoise`, `spawnXYZ` (`MT_PUFF`), momz `FRACUNIT`, `ticsNoise`, `S_PUFF3` when `P_IsAttackRangeMeleeRange` |
| `P_SpawnBlood` | `GA_X`, `GA_Y`, `GA_Z`, damage in `GA_12-13` (`GA_DMG`) | | the damage is read first (`GA_TYPE` is the same byte); `S_BLOOD3` below 9, `S_BLOOD2` to 12 (signed) |
| `zNoise` | `GA_Z` | `GA_Z` += (`P_Random()` - `P_Random()`) << 10 | the first call's value less the second's |
| `spawnXYZ` | A a type, `GA_X`, `GA_Y`, `GA_Z` | A:X the slot (and `SP_TH`) | upstream's takes `SP_X..SP_Z`; natively the caller's `GA_*`, so `missile`, `wfire` and `trymove` call it with their own coordinates and keep the slot themselves (`SP_TH` is this part's scratch) |
| `ticsNoise` | A:X a mobj | | tics -= `P_Random() & 3`, at least 1 (the tics plane's byte) |
| `P_IsAttackRangeMeleeRange` | attackrange (request 1) | A 1 / 0 (Z clear / set) | |
| `P_ZMovement` | A:X a mobj | | TICSTEP 1, the release's |
| `missileHit` | A:X a mobj | C set (A 1) when it exploded | FCALLs `mobjstate`'s `explode` |
| `shr3` | `GA_0-3` | `GA_0-3` >> 3, arithmetic | upstream's C:X (C the high word) |
| `p_mobj_isPlayer` | A:X a mobj | A 1 / 0 (Z clear / set) | the slot against `G_PLAYER + PL_MO`; part `xymove` calls it |

`moArg`, `thArg` and `saveXYZ` have no native code (request 3): they copy
between upstream's registers, its `_Dp` and its near scratch; natively the
coordinates stay in `GA_X..GA_Z` and the slot is A:X.

## 2. Requests

1. **`GM_ATRANGE` (4 B) in the tic scratch.** In
   `tools/native/glayout.py` `TIC_GW_FIELDS`, after `('GM_BYH', 1),`:
   `('GM_ATRANGE', 4),` (and a line in `src/native/game/README.md`'s
   `GM_*` paragraph: "`GM_ATRANGE` (`attackrange`: part `attack` writes
   it, part `spawn` reads it)"). Why: upstream's `attackrange` is
   `p_attack65.s:27` `AT_RANGE`, written by `P_LineAttack` and
   `P_AimLineAttack` [R `p_attack65.s:107-109`] (part `attack`, wave 5) and
   read by `P_IsAttackRangeMeleeRange` [R `p_attack65.s:623-626`] (this
   part) inside `P_SpawnPuff` [R `p_spawn65.s:387`], which
   `PTR_ShootTraverse` calls [R `p_attack65.s:1101`]: two parts share it,
   so it cannot be either's scratch block. Effect: `attack` writes it
   there; this part needs no edit (`sp.inc`: `.ifdef GM_ATRANGE`;
   `spawn.py`'s `place('AT_RANGE')` follows `glayout.TGW`); GW grows by 4
   B. Until then the **local stand-in** is `SB_SPAWN + 28..31` (marked in
   `sp.inc`), into which the harness writes upstream's `AT_RANGE`.
2. **Placement affinity** (`tools/native/gplace.py` `AFFINITY`, two
   groups): `('p_mobj65.s:P_ZMovement', 'p_mobj65.s:missileHit',
   'p_mobj65.s:shr3', 'p_mobj65.s:isPlayer')` and
   `('p_spawn65.s:P_SpawnPuff', 'p_spawn65.s:P_SpawnBlood',
   'p_spawn65.s:zNoise', 'p_spawn65.s:spawnXYZ',
   'p_spawn65.s:ticsNoise', 'p_attack65.s:P_IsAttackRangeMeleeRange')`;
   GAME.md 4.3 puts `P_ZMovement` in the core, and with its three callees
   it is 590 B. Why: the shared placement puts `P_ZMovement` in group 16,
   `missileHit` and `shr3` in 14, `p_mobj_isPlayer` in 21 (all slot 2),
   `P_SpawnPuff` in 13, `P_SpawnBlood` in 16, `ticsNoise` in 3,
   `P_IsAttackRangeMeleeRange` in 6. Every `P_ZMovement` call pages
   `p_mobj_isPlayer`'s group at its start and its own group back: in
   routine mode (every slot empty at the call) `P_ZMovement`'s median is
   23,821 CPU cycles with 2 group loads, `p_mobj_isPlayer`'s 5,147 for a
   routine of about 20 cycles, a puff 59,723 with 4 loads, blood 75,707
   with 6. Effect: none on any source (placement is data); the integrator
   weighs it against the core's room.
3. **`glayout.INLINED['spawn']`**: `('p_spawn65.s:moArg',
   'p_spawn65.s:saveXYZ', 'p_spawn65.s:thArg')`, the helpers with no code
   of their own (section 1). `moArg` is `P_SpawnMobj`'s helper (milestone
   9's core has its own); `thArg` is "the slot of the last spawn", which
   callers keep from `spawnXYZ`'s A:X. Effect: `gplace.py` gives them no
   bytes; no `FCALL` names them.

## 3. Results

All on the part's image (`make -s -C src/native -f game.mk part P=spawn
ROOT=$PWD`: the runtime, milestone 9's core, wave 1's five parts and
this part), a2vm against `ref816`, 2026-10-02.

**The paths** (`spawn.py --paths`): the five runs on `ref816` with the
call log of `P_ZMovement`, `missileHit`, `isPlayer` and
`P_IsAttackRangeMeleeRange` and `--mark` at 18 path points, found in
upstream's source by text and placed by our own assembler's spans
(`tools/v816`), each checked to start an instruction of the release (the
test); every call count equals the survey's. `P_ZMovement`'s 10,640 calls
take 12 paths: in the air with no gravity 7,913 (puffs, blood, missiles),
with gravity 2,429 (from rest 293), the floor hit after a fall 204 (the
player's 35), the floor with no fall 13, the player's squat 59, the hard
landing with "oof" 3, a missile exploding on the floor 4, the ceiling (a
rise ended) 15;
`isPlayer` 13,941 the player's of 28,594; `P_IsAttackRangeMeleeRange` never
melee (no punch in any run); `missileHit` 4 explosions of 298.

**The checkpoint** (`spawn.py --check --jobs 2`; every case from both
fills under both profiles, 4 runs each; 1,502 s):

| Entry | Cases (eligible = captured) | Runs | Failed | CPU cycles median / worst | Lowest S |
| --- | --- | ---: | ---: | --- | ---: |
| `P_SpawnPuff` | 363 (every call) + 1 synthetic | 1,456 | 0 | 59,723 / 208,540 | $D4 |
| `P_SpawnBlood` | 254 (every call: 71 `S_BLOOD1`, 95 `S_BLOOD2`, 88 `S_BLOOD3`) + 4 synthetic | 1,032 | 0 | 75,707 / 167,440 | $D1 |
| `P_IsAttackRangeMeleeRange` | 300 of 363 spread + 2 synthetic | 1,208 | 0 | 5,159 / 5,164 | $E8 |
| `P_ZMovement` | 306 (300 of DEMO1's spread, 6 more for the paths none took) + 8 synthetic | 1,256 | 0 | 23,821 / 52,595 | $D8 |
| `missileHit` | 298 (every call) | 1,192 | 0 | 7,973 / 25,979 | $DD |
| `shr3` | 62 (every call) | 248 | 0 | 5,229 / 5,229 | $E8 |
| `isPlayer` | 300 of 28,594 spread | 1,200 | 0 | 5,147 / 5,152 | $E8 |

7,592 runs, 0 failed, 0 stray writes; every captured call eligible (no
call reached a dispatch target: the death states of the missiles that
explode have no action, nor do `S_PUFF3`, `S_BLOOD2`, `S_BLOOD3`). Cycles
are the W65C02S's from the call to its return with every slot empty (the
group loads of `FCALL` included: an upper bound), the same on both
profiles; the fabric clocks per profile (`f121`, `fastpath`) are in
`report.json`. Lowest S from `$EF`: 30 B at most.

The synthetic cases (the reference's own call on a captured state with
fields poked; each also checked to take its path on `ref816`): a mobj
rising into the ceiling (momz to 0, z = ceilingz - height), one stuck
through the ceiling, an imp's fireball into the ceiling and one into the
floor (both explode), the player's hard landing alive ("oof") and dead,
the player's squat, a fall from rest (momz -2 `FRACUNIT`), a punch's puff
(`S_PUFF3`), blood at damage 8, 9, 12 and 13, `P_IsAttackRangeMeleeRange`
at `MELEERANGE` and at a range whose low word only matches: 15 cases, 60
runs, all equal.

**shr3's random check** (`spawn.py --random`): 100,000 inputs (32 edges:
0, ±1, ±7..±16, the extremes, the low word's edges; then random values)
through upstream's `shr3` (milestone 6's `mathref`, batch mode, on a
captured `shr3` call's machine) and the native (`sp_bulk`): 0 different;
upstream equals the arithmetic shift on all 100,000. A logical shift
planted in a scratch copy gives 3,054 differences in 20,000.

**The planted bugs** (`spawn.py --plants`; each in a scratch copy, its
image in a deleted temporary directory, one fill):

| Plant | Check | Failed runs |
| --- | --- | --- |
| gravity after the floor clamp | `P_ZMovement`'s floor-path cases | 7 of 10 (the others: an explosion, `MF_NOGRAVITY`) |
| the puff's z `P_Random` after the tics' | `P_SpawnPuff`'s cases | 41 of 41 |
| blood's thresholds one off (< 10, < 14) | `P_SpawnBlood`'s cases and the damage cases | 7 of 44 (damage 9 and 12) |
| the squat's `deltaviewheight` shift (>> 2) | `P_ZMovement`'s squat-path cases | 2 of 2 |

**Sizes** (the image's map): `spawn.s` 359 B, `zmove.s` 590 B: 949 of
1,100 B (upstream 842 B); `sptest.s` 112 B in the driver's area (test
builds only).

**The test** (`tests/test_native_game_spawn.py`, 10 tests, 220 s alone):
the build and budget, no far access, the path points, every 8th captured
case and every synthetic case on both fills and profiles, the random
check, the four plants.

**build/**: `build/native/game/spawn/` 62 MB (cases 45 MB with their 4
run bases, the image and its objects 7 MB, the checkpoint's journal 3
MB, the paths 20 KB); every temporary directory deleted.

## 4. Open points

- `isPlayer`'s "low word equal, bank different" path (upstream compares a
  24-bit pointer in two words) has no native counterpart (the native
  compares slots) and no capture: no two mobjs of a run differ only in
  their bank.
- `P_IsAttackRangeMeleeRange`'s melee answer and a missile exploding at
  the ceiling are synthetic only (no punch and no such explosion in any
  run); the generated streams may add them.
- A missile whose death state has an action (the rocket's `A_Explode`,
  part `chase`) would make `missileHit` and `P_ZMovement` cases wait; none
  of the survey's runs has one.
- The timing above pays the paging of request 2.

## 5. The integration of wave 2 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 2 as integrated").

| Request | Decision |
| --- | --- |
| 1 `GM_ATRANGE` | **Accepted**: `glayout.TIC_GW_FIELDS` (4 B, `$B31F`); `sp.inc`'s stand-in branch is gone; `attack.md` notes it |
| 2 the placement | **Accepted**: the height move (`P_ZMovement`, `missileHit`, `shr3`, `isPlayer`: group 23, slot 2) and the puffs (`P_SpawnPuff`, `P_SpawnBlood`, `zNoise`, `spawnXYZ`, `ticsNoise`, `P_IsAttackRangeMeleeRange`: group 6, slot 2) each in one group; not in the core, which sight's pinned routines fill (the gprof build's heat decides later, GAME.md 5.4) |
| 3 `INLINED` | **Accepted** |

## The integration of wave 6 (2026-10-02)

`sptest.s` (`sp_bulk`, the random check's test routine, 112 B in the
card's driver area) is now linked only with `SP_TEST=1`, which
`spawn.py`'s `build()` passes. Linked in every image, it left no room in
the driver's area for part damage's `dtest.s` once every part was built:
damage's image overflowed `LCE` by 24 B (docs/GAME.md "Wave 6 as
integrated"). The placement's new margins (`gplace.GROUP_MARGIN`) give
this part's plants room again: `puff-z-random-after-tics` had passed its
group by 47 B, and `squat-shift` by 2 B.
