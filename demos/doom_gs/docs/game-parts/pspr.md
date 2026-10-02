# Part `pspr` (wave 3)

The record of milestone 10's part `pspr` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 3; upstream 894 B, native budget 1200 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 3's `pspr` (2026-10-02, lean rules of the owner's 2026-10-02 request).
- Files: `src/native/game/pspr/*.s`, `src/native/game/pspr/part.mk`, `src/native/game/pspr/args.json`, `tests/test_native_game_pspr.py`, this file; tools (if any) `tools/native/gparts/pspr*.py`; build output `build/native/game/pspr/` (`make -s -C src/native -f game.mk part P=pspr ROOT=$PWD`).
- Its scratch block: `SB_PSPR` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_pspr65.s`: `P_MovePsprites:1200`, `tickPsprite:1215`, `A_WeaponReady:561` (the bob, the attack, the saw's idle sound), `A_ReFire:675`, `A_Lower:694`, `A_GunFlash:756`, `A_Light0:1171`, `A_Light1:1173`, `A_Light2:1176`, `fireWeapon:530`, `checkAmmo:379` (the weapon order when out of ammo, and `P_NoiseAlert` with `recursiveSound:451` made iterative with the 512-entry work stack [R `LEVELS.md` 5.5]), `P_CheckAmmo:376`; helpers `startSound`, `argMo`, `setMoState`, `signExt4`, `signExt0`, `fireSomething`

Its checkpoint (GAME.md 2.4): `P_MovePsprites` (every tic), `P_NoiseAlert` (each shot), `checkAmmo`; synthetic: the deepest floods of E1M2 and E1M3 (93 [M: M9]) with every two-sided line open, an empty weapon

Its planted bugs (each must fail the named check): the flood taking the `ML_SOUNDBLOCK` entries first (sector stamps); a work stack of 80 (E1M2's flood stops, as milestone 9 planted); the bob's x from the cosine; the shotgun preferred over the chaingun

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_pspr65.s:P_MovePsprites` | `P_MovePsprites` | demo3 2135, demo1 5026, demo2 3837, newgame 513, tour 428 |
| `p_pspr65.s:tickPsprite` | `tickPsprite` | demo3 4270, demo1 10052, demo2 7674, newgame 1026, tour 856 |
| `p_pspr65.s:A_WeaponReady` | `A_WeaponReady` | demo3 1004, demo1 2159, demo2 2394, newgame 466, tour 293 |
| `p_pspr65.s:A_ReFire` | `A_ReFire` | demo3 25, demo1 102, demo2 50, newgame 2, tour 0 |
| `p_pspr65.s:A_Lower` | `A_Lower` | demo3 73, demo1 715, demo2 353, newgame 0, tour 0 |
| `p_pspr65.s:A_GunFlash` | `A_GunFlash` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_pspr65.s:A_Light0` | `A_Light0` | demo3 26, demo1 105, demo2 51, newgame 2, tour 0 |
| `p_pspr65.s:A_Light1` | `A_Light1` | demo3 26, demo1 105, demo2 51, newgame 2, tour 0 |
| `p_pspr65.s:A_Light2` | `A_Light2` | demo3 26, demo1 16, demo2 8, newgame 0, tour 0 |
| `p_pspr65.s:fireWeapon` | `fireWeapon` | demo3 26, demo1 139, demo2 51, newgame 2, tour 0 |
| `p_pspr65.s:checkAmmo` | `checkAmmo` | demo3 1142, demo1 2739, demo2 1399, newgame 50, tour 12 |
| `p_pspr65.s:recursiveSound` | `recursiveSound` | demo3 1095, demo1 3421, demo2 443, newgame 167, tour 0 |
| `p_pspr65.s:P_CheckAmmo` | `P_CheckAmmo` | demo3 1116, demo1 2600, demo2 1348, newgame 48, tour 12 |

Helpers: `p_pspr65.s:startSound`, `p_pspr65.s:argMo`, `p_pspr65.s:setMoState`, `p_pspr65.s:signExt4`, `p_pspr65.s:signExt0`, `p_pspr65.s:fireSomething`.

## What was built

| File | Content |
| --- | --- |
| `src/native/game/pspr/pspr.s` | `P_MovePsprites`, `tickPsprite`, `A_WeaponReady` (the attack states left, the chainsaw's idle sound, the lower, the attack with the rocket launcher's and the BFG's held button, the bob: `finecosine`, two `mul32`, `finesine`, `fixmulang`), `signExt4`, `signExt0`, `A_ReFire`, `A_Lower` with `bringUp` (**stand-in** of R2), `A_GunFlash`, `fireSomething`, `A_Light0-2`, `fireWeapon` with the noise alert (`gv_inc`, the target, the player's sector through `mo_get` and `ss_get`), `checkAmmo`, `P_CheckAmmo`, `p_pspr_startSound`, `setMoState` |
| `src/native/game/pspr/pflood.s` | `recursiveSound`, iterative, its work stack `ps_stack` (512 entries, 1,024 B) in its group after its code; the flood lists read through `lt_get` (**stand-in** of R3), the opening computed in place (**stand-in** of R5) |
| `src/native/game/pspr/pstest.s` | Test builds only, in the driver's area: `ps_bulk` (the sign extensions on many inputs, the random check) |
| `src/native/game/pspr/pspr.inc` | The scratch block's bytes (`PS_*`, 25 of 32), the work stack's geometry, the stop code (R4's stand-in), the player's psprite places |
| `src/native/game/pspr/part.mk`, `args.json` | The fragment; the entries' inputs and outputs (`as`: `psp`, `sector`, `mobj`; `sb:PS_TGT`) |
| `tools/native/gparts/pspr.py` | The harness (on `mobjstate.py`'s machinery, as `spawn.py`): the image, the selection and captures, routine mode with the write log, the synthetic cases, the random check (`mathref batch` against `ps_bulk`), the plants, `report.json` |
| `tests/test_native_game_pspr.py` | Build (3 tests), Checkpoint (one captured call an entry and the E1M2 flood by default; everything with `DOOM_GS_FULL=1`), Random (100,000 inputs each), Plants (`DOOM_GS_FULL=1`) |

### The interfaces (for the later waves' callers)

| Routine | In | Out | Notes |
| --- | --- | --- | --- |
| `P_MovePsprites` | (the player) | | `player`'s `P_PlayerThink` and the death think, every tic |
| `tickPsprite` | A = the psprite (0 weapon, 1 flash) | | |
| `A_*` (ACTTAB) | `GS_PSP` the psprite (gw_setpsprite's convention) | | `A_WeaponReady` keeps its psprite on the stack (an action it runs may set `GS_PSP` again) |
| `fireSomething` | A = k | | the flash psprite to the ready weapon's flash state + k: part `wfire`'s `A_FirePistol` ... call it |
| `fireWeapon` | | | checkAmmo, the attack state, the noise alert |
| `checkAmmo`, `P_CheckAmmo` | | A = 1 enough or none needed, 0 not | upstream's checkAmmo switches no weapon (R7) |
| `recursiveSound` | A = a sector, Y = the blocks (0, 1), `PS_TGT` the target | | `validcount` raised by the caller (the noise alert); a flood deeper than 512 levels stops (`GS_FLOOD`, R4) |
| `p_pspr_startSound` | A = a sound | | `S_StartSound(player->mo, A)` |
| `setMoState` | A:X = a state | A as `P_SetMobjState` | the player's mobj |
| `signExt4`, `signExt0` | A:X a word | `M_B`, `M_A` = it sign extended | `_Mul32`'s operands (math.s `mul32`) |

Temporaries: `GT_0-GT_6`, `GS_ST`, `GS_PSP`, the math block, the scratch block `SB_PSPR`. No zero page of the part's own.

### Notes on upstream's code, reproduced

- The bob's x is upstream's sum of two 32-bit low products' high words plus 1 (`p_pspr65.s:608-637`: `hi16(bob x bhw) + hi16(sext(ahw) x blw) + 1`, `finecosine` of `(leveltime & 63) << 7`), not `FixedMul`; its y `WEAPONTOP + FixedMulAngle(bob, finesine(angle & 4095))` (`:638-651`).
- `A_Lower`'s bottom test is the N flag of the 16-bit `cmp WEAPONBOTTOM`, no overflow correction (`:699-700`); `checkAmmo`'s the corrected signed one (`:396-400`).
- The flood keeps upstream's order of stamps exactly: a level's entries without `ML_SOUNDBLOCK` in the list's order, the callee entered at once (depth first), then, after `v = 0`, the entries with it with `v = 1` (`:451-523`); the in-loop test before the opening (`:488-495`) and the callee's own test (`:453-463`) are both made. The work stack holds 2 bytes an entry (the entry and its part and `v`), not LEVELS.md 5.5's 3: a level's sector is the flood entry of the level below it, or the first sector (`PS_ST`), so 512 entries take 1,024 B and the code fits the group with them.
- `A_WeaponReady` compares the mobj's state and the psprite's with whole state numbers; upstream compares the pointers' low words in one bank: the same.

## 2. Requests

Each with what, why (the evidence), its effect on other parts, and the part's stand-in until it is applied.

**R1. `INLINED` for `argMo`.** What: in `glayout.py`'s `INLINED`, `'pspr': ('p_pspr65.s:argMo',)`. Why: upstream's `argMo` (`p_pspr65.s:137-142`) puts `player->mo` in `_Dp`; natively the routines read `G_PLAYER + PL_MO` where upstream calls it (`setMoState`, `p_pspr_startSound`, `A_WeaponReady`, the noise alert): it has no code (the placement gives it bytes in group 3 today). Effect: the placement's estimates only.

**R2. A `bringUpWeapon` entry in `gweap.s`.** What: in `src/native/gweap.s`, `.export bringUpWeapon` and the label `bringUpWeapon:` on the line `lda PLR + PL_PENDINGWEAPON       ; WP_NOCHANGE: the ready one` (gw_setup's own bringUpWeapon, after "pending = ready"), so that it is upstream's `bringUpWeapon` (`p_pspr65.s:155-176`: the pending weapon, or the ready one when none, comes up from `WEAPONBOTTOM + 2`; the chainsaw's `sfx_sawup`). Why: `A_Lower` calls it (`p_pspr65.s:715-717`) after setting the ready weapon to the pending one; milestone 9 has it only inside `gw_setup`. Stand-in: `bringUp` in `pspr.s` after `A_Lower` (75 B, the same steps through `wInfoOf` and `weaponinfo`). When applied: `A_Lower`'s tail becomes `FCALL bringUpWeapon` (the core: a `jsr`), `bringUp` goes (-75 B). Effect: none on other parts (`gw_setup` unchanged; `glayout` already lists `p_pspr65.s:bringUpWeapon` in the core).

**R3. The flood lists in the object API.** What: in `src/native/gobj.s` (tic images, `.ifndef LOADIMG`), `fl_idx` (A = a sector, Y = 0-3: A:X = word Y of its flood index, LVG1 `G_FLIDXAT + 8 s + 2 Y`: the first entry, the end of the entries without `ML_SOUNDBLOCK`, the first with it, the end) and `fl_ent` (A:X = an entry: A = its sector, the byte at LVG1 `G_FLENTAT + e`). Why: the flood reads them (`p_pspr65.s:475-477`, `:486`, `:515-517`) and no API call reaches them; the parts may not call `g_get`/`far_get`. Stand-in: `pflood.s` reads them through `lt_get`, whose entry i is the word at `G_LTABAT + 2 i` of LVG1: the index and the entries follow the line tables at even distances (`llayout.py` "LVG1"), so `PS_FLI`, `PS_FLE` = (place - `G_LTABAT`) / 2 and a byte entry is one half of a word (about 85 B and an extra far word read an entry). When applied: `pflood.s`'s `fl_idx`, `fl_ent` and the places' loop go (-85 B), `PS_FLI`, `PS_FLE` are freed. Effect: none on other parts.

**R4. A stop code `GS_FLOOD`.** What: `glayout.GS['GS_FLOOD'] = 0x10` (`ggame.inc`): the flood is deeper than its work stack (512 levels), `GS_ARG` the sector. Why: a native limit must stop, never cut silently (GAME.md 3.4 "Stops"); the bound of every E1 map is 500 (LEVELS.md 5.5), so no E1 flood reaches it. Stand-in: `pspr.inc` defines `PS_GS_FLOOD` = `GS_FLOOD` when it exists, else `$10` (no code of `glayout.GS` uses it: they end at `$0F`). Effect: none.

**R5. `P_LineOpeningXY` with the flood (placement).** What: `gplace.AFFINITY`'s geom pair joined by the flood: `('p_map65.s:P_LineOpening', 'p_map65.s:P_LineOpeningXY', 'p_pspr65.s:recursiveSound')` (or `P_LineOpeningXY` in the core). Why: the flood's work stack is in its group (GAME.md 4.1: slot 2's group keeps its data); an `FCALL P_LineOpeningXY` (`p_pspr65.s:496-500`) to a group of the same slot reloads the slot and, on the return, reloads the flood's group from `GCODE`, the stack lost. In this part's image both are in slot 1 (groups 1 and 27), so the stack would be lost at the first opening. Stand-in: `opening` in `pflood.s` computes `P_LineOpeningXY`'s `openrange` of the two sectors in place (the lower ceiling less the higher floor, 32 bits, the compares signed with the overflow corrected as `openXY`, `p_map65.s:2412-2450`), about 100 B. When applied: `opening` becomes `FCALL P_LineOpeningXY` (A = `PS_OTH`, X = `PS_SEC`, a `jsr` in the group) and the test of `GM_OPENRANGE` (> 0), -90 B. Size: the flood's group is 1,636 B now (612 code, 1,024 stack); with geom's pair (its measured bytes) and without the stand-ins it stays under 2,048. Effect: `P_LineOpening`'s other callers (`checkpos`, `attack`, `xymove`, `chasemove`, sight's?) load a group of about 1.9 KB instead of geom's own when it is not resident (0.25 µs a byte: about 0.3 ms more a load); the alternative is the core, if it has 150 B. The group must not take other routines that the flood does not call (its room is the stack's).

**R6. The weapon's routines in one group (placement).** What: `gplace.AFFINITY` `('p_pspr65.s:P_MovePsprites', 'p_pspr65.s:tickPsprite', 'p_pspr65.s:A_WeaponReady', 'p_pspr65.s:signExt4', 'p_pspr65.s:signExt0', 'p_pspr65.s:setMoState', 'p_pspr65.s:startSound', 'p_pspr65.s:A_ReFire', 'p_pspr65.s:A_Lower', 'p_pspr65.s:A_GunFlash', 'p_pspr65.s:fireSomething', 'p_pspr65.s:A_Light0', 'p_pspr65.s:A_Light1', 'p_pspr65.s:A_Light2', 'p_pspr65.s:fireWeapon', 'p_pspr65.s:checkAmmo', 'p_pspr65.s:P_CheckAmmo')`: `pspr.s`, 971 B (896 without R2's stand-in), one group. Why: `P_MovePsprites` runs every tic and calls `tickPsprite` twice; `A_WeaponReady` (most tics) calls `signExt4`, `signExt0` and, on a shot, `setMoState`, `fireWeapon`, `checkAmmo`; the placement spreads them over groups 7, 3, 20, 16, 2, 25, 15, 18, 19, 5 in both slots: a `P_MovePsprites` call with the bob costs 62,014 CPU cycles at the median in routine mode (every slot empty at the call), most of it group loads; P_MovePsprites with a shot up to 858,805. Effect: the placement's (the integrator's); `wfire`'s actions call `fireSomething`.

**R7. GAME.md 2.4's row (documentation).** What: in the row `pspr`, (a) "`checkAmmo:379` (the weapon order when out of ammo, ..." becomes "`checkAmmo:379` (the ammunition of a shot; upstream switches no weapon there: `P_SwitchWeapon:183`, the preferences `prefs:60`, is `G_BuildTiccmd`'s, `g_game65.s:298-302`, milestone 11's), ..."; (b) the planted bugs "the flood taking the `ML_SOUNDBLOCK` entries first (sector stamps)" and "the shotgun preferred over the chaingun" are replaced by "a closed opening (openrange 0) let through (the captured floods)" and moved to milestone 11 (`P_SwitchWeapon`'s order) respectively; (c) "the bob's x from the cosine" reads "the bob's x from the sine". Why: (a) `p_pspr65.s:379-406`; (b) the flood's final stamps do not depend on the order of the lists (upstream's own note, `p_pspr65.s:445-449`: "The order of the lines and a line more to the same sector do not change the result": soundtraversed is the least number of blocks + 1 over the paths), so no state check can catch that plant; `P_SwitchWeapon` is in no part's routines; (c) the bob's x is the cosine's (`:613`). Also LEVELS.md 5.5 and MEMORY_MAP.md 3.5: the work stack is 512 entries of 2 bytes, 1,024 B (the sector is not kept). Effect: documentation.

**R8. The interfaces in `src/native/game/README.md`.** What: the table "The interfaces" above in "The parts' interfaces". Effect: documentation.

## 3. Results

All on a2vm against `ref816`, 2026-10-02, at 2 jobs, lean (the owner's rules of 2026-10-02: at most 40 captured calls a routine, one fill, no timing study); nothing committed. `build/native/game/pspr/report.json` has every number.

**Checkpoint** (`python3 tools/native/gparts/pspr.py --check --jobs 2`, 57 s): **166 runs, fill `$A5`, `f121`: 0 failed, 0 stray writes**.

| Entry | Cases | Failed | CPU cycles median / worst | Lowest S |
| --- | ---: | ---: | --- | ---: |
| `P_MovePsprites` | 44: 40 captured (13 classes of call, below), 4 synthetic | 0 | 62,014 / 858,805 | `$C3` |
| `tickPsprite` | 20 captured (both psprites) | 0 | 15,026 / 173,692 | `$D0` |
| `fireWeapon` | 20 captured (each with its noise alert) | 0 | 374,096 / 577,567 | `$D9` |
| `checkAmmo` | 20 captured | 0 | 5,302 | `$E4` |
| `P_CheckAmmo` | 20 captured | 0 | 20,308 | `$DF` |
| `recursiveSound` | 42: 40 captured (demo1 27, demo3 9, demo2 3, newgame 1; top-level floods and inner levels), 2 synthetic | 0 | 48,097 / 1,511,426 | `$E2` |

The captured `P_MovePsprites` calls, by class (the ACTTAB actions the call reached in the survey, `+fire` a shot in its tic), 3 each (`A_Raise` 4): none (tics counting down), `A_WeaponReady` (the bob), `A_WeaponReady+fire`, `A_ReFire`, `A_ReFire+fire`, `A_Lower`, `A_Lower+A_Raise`, `A_Lower+A_WeaponReady`, `A_Raise`, `A_Raise+A_WeaponReady`, `A_Raise+A_WeaponReady+fire`, `A_Light0`, `A_Light2`. Eligible only: a call reaching a `wfire` action (`A_FirePistol`, `A_FireShotgun` and their `A_Light1`) waits for wave 6.

The synthetic cases (each with the reference's own call and a check that the call is the case it is named for): `flood-e1m2`, `flood-e1m3` (`recursiveSound` from sector 34 of E1M2 and 29 of E1M3, `level_check.py --flood`'s deepest starts, 93 levels, every sector's floor 0 and ceiling 128, a new validcount: at least half the sectors stamped), `empty-weapon` (the pistol ready, the attack, no clip: no shot, no noise), `gunflash` (the rocket launcher: `A_GunFlash`, the flash's `A_Light1`, the noise alert), `saw-idle` (the chainsaw's idle sound), `missile-held` (the rocket launcher with `attackdown` set: no shot, the bob).

Branches that no case is known to reach (no path marks were run, lean): `checkAmmo`'s BFG (40 cells) and super shotgun (2) counts (no such weapon in E1: their `cmp` only); `A_Lower`'s "no health" (the weapon's psprite to `S_NULL`: a dying player is `PST_DEAD` first); `bringUp`'s chainsaw sound (no chainsaw raised in the runs; `saw-idle` covers `A_WeaponReady`'s); a flood entry past `$3FFF` and the work stack's overflow (the plant `stack-80` takes the stop).

**Random check** (`pspr.py --random`): `signExt4` and `signExt0` on 100,000 inputs each (17 edges: 0, ±1, ±2, `$7FFF`, `$8000`, `$FF`, `$100`, `±$80` ..., then random words) against upstream's helpers by `mathref batch` (its `_Dp+4` and `_Dp` after the call): **0 different**, every one the sign extension.

**Planted bugs** (`pspr.py --plants`), each in a scratch copy, its image in a temporary directory:

| Plant | Check | Caught by |
| --- | --- | --- |
| a work stack of 80 | `flood-e1m2` | the stop `GS_FLOOD` (code `$10`, sector 181) |
| the bob's x from the sine | the captured `P_MovePsprites` calls | 4 of 40 (the moving player's: `sx 1 != 3`) |
| a closed opening (openrange 0) let through | the captured floods | 19 of 40 (sector stamps: `soundtraversed`, `validcount`, `soundtarget`) |

**Sizes** (the part's image's map): `pspr.s` 971 B, `pflood.s` 1,636 B of which the work stack 1,024: **code 1,583 of 1,200 B (+31.9%)**. The reasons: the three stand-ins (R2 `bringUp` 75 B, R3 the flood lists' reads 85 B, R5 the opening 100 B: 260 B; without them 1,323 B, +10%), the bob's two 32-bit products and two table reads in 8-bit steps, and the iterative flood's own stack handling (upstream's recursion is free). The flood's group 1,636 of 2,048 B (with `lnExit` of part `lines` in this image's group 1: 1,724). Test-only `pstest.s` 132 B in the driver's area. `glayout.py --check` ok; `gcallgraph.py --check --built` (waves 1-2 and `pspr`): 0 failures, `--stack` 80 of 160; `gameroutine.grep_check` on the part's sources: clean.

**The test** (`tests/test_native_game_pspr.py`): 9 tests; by default 10 s (Build, one case an entry and the E1M2 flood, Random; 2 skipped), with `DOOM_GS_FULL=1` 95 s (every selected case, every synthetic case, the plants).

**build/**: `build/native/game/pspr` 40 MB (the cases 37 MB: five runs' bases and 188 cases); every temporary directory deleted.

## 4. Open points

- (Wave 2 as integrated) `wInfo` and `wInfoOf` are in the core (`gplace.CORE_FIRST`): X = A = the record's offset in `weaponinfo` (core, part `damage`), fields at `UO_WI_*` (`damage.md` R2, R7).
- (Wave 2 as integrated) The bob's `finesine`, `finecosine` are resident (`jsr`: the core's `math-g.o`, wave 2 as integrated).
- The survey counts more `recursiveSound` calls than ref816's `--capture` (demo1 3,421 against 3,368): the selection takes the first 90% of each run's calls, all of which the capture reaches; any call of `recursiveSound` is a whole flood from its sector, so the capture's numbering is all a case needs.
- The lean checkpoint ran one fill (`$A5`) and `f121` only; the other fill, `fastpath` and every captured call are the final integration's. The cycles are routine mode with every slot empty at the call (an upper bound), most of them group loads until R5 and R6 are applied.
- A captured call whose tic reaches a `wfire` action (`A_FirePistol`, `A_FireShotgun`, with their `A_Light1`) waits for wave 6; `A_Light1` is checked here only through `gunflash`.
- Part `damage`'s waiting cases (its 10 captured player deaths and every `P_DropWeapon`, `lowerWeapon` call reach `A_Lower`) become eligible with this part: the integrator's rerun.
- The stand-ins of R2, R3 and R5 are marked in `pspr.s` and `pflood.s`; R4's `$10` is used only while `GS_FLOOD` is undefined.

## 5. The integration of wave 3 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 3 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 `argMo` inlined | **Accepted**: `glayout.INLINED['pspr']` |
| R2 `bringUpWeapon` in `gweap.s` | **Accepted**: `gweap.s` exports `bringUpWeapon` at gw_setup's bringUpWeapon; `A_Lower` ends with `jmp bringUpWeapon` (the core, as `gw_setpsprite`), and the stand-in `bringUp` is gone (`pspr.s` 75 B less) |
| R3 `fl_idx`, `fl_ent` in the object API | **Refused**: the API is in the core, which is full (wave 2's finding 1; this wave's `aproxdist` took its last bytes); the flood is cold (a shot's noise alert) and its reads through `lt_get` are the API's, so the 85 B stay in the flood's group, which has room (1,024 B of stack + the code). `pflood.s`'s comments now say so. To revisit with the core's levers (the timing report) |
| R4 `GS_FLOOD` | **Accepted**: `glayout.GS['FLOOD'] = 16`; `pspr.inc`'s `PS_GS_FLOOD` is `GS_FLOOD` |
| R5 `P_LineOpeningXY` with the flood | **Refused**: `P_LineOpening` runs for every line of a position check and of the traversers (`checkpos`, `attack`, `xymove`, `chasemove`); with the flood it would load a 1.9 KB group with 1 KB of dead stack at each of those calls, to save 90 B in a cold routine; the core has no room. The flood's own `opening` stays, and it calls only the core, so the stack cannot be lost |
| R6 the weapon's routines in one group | **Accepted**: `gplace.AFFINITY` with the 17 routines (group 26, slot 2) |
| R7 the texts | **Accepted**: GAME.md 2.4's `pspr` row (a), (b), (c); `LEVELS.md` 5.5 and `MEMORY_MAP.md` 3.5 the 1,024 B work stack of 2-byte entries |
| R8 the interfaces | **Accepted**: README "The parts' interfaces"; `wfire.md` and `player.md` noted |

Also changed by the integration: `pstest.s` (test-only, in the driver's
area) is linked only into the part's own image (`part.mk`: `PS_TEST=1`,
which `pspr.py`'s `build` passes, as damage's `DM_TEST`): linked into
every part's image it overflowed damage's driver area by 67 B.
