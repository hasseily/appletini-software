# Part `mobjstate` (wave 1)

The record of milestone 10's part `mobjstate` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 1; upstream 1397 B, native budget 1900 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 1's `mobjstate` (2026-10-01).
- Files: `src/native/game/mobjstate/*.s`, `src/native/game/mobjstate/part.mk`, `src/native/game/mobjstate/args.json`, `tests/test_native_game_mobjstate.py`, this file; tools (if any) `tools/native/gparts/mobjstate*.py`; build output `build/native/game/mobjstate/` (`make -s -C src/native -f game.mk part P=mobjstate ROOT=$PWD`).
- Its scratch block: `SB_MOBJSTATE` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_map65.s`: `P_UnsetThingPosition:717`, `P_DelSeclist:3033`, `P_DelSecnode:3058`; `p_think65.s`: `P_RemoveThinker:80`, `P_RemoveThing:84`, `P_RemoveThinkerDelayed:99`, `P_RemoveThingDelayed:102`, `P_NextThinker:153`; `p_spawn65.s`: `P_RemoveMobj:339`, `poolFree:1334` (and the zone's free list, whose free of a zone mobj that `CS_PREV` names sets that handle to `$FFFE` and raises `GT_ZPREV`, 1.8); `r_list65.s`: `linkRemove:933` (review 9); `p_tick65.s`: `P_SetMobjState:749` (the `ACTTAB` dispatch, `rocketCheat:863`), `P_MobjBrainlessThinker:706`; `p_mobj65.s`: `P_ExplodeMissile:734`, `explode:741`, `P_MobjIsPlayer:716`; helpers `unlist`, `link`, `mvSector`, `mvBlock`, `blockOf`, `snLink`, `unlink`, `rmArg`

Its checkpoint (GAME.md 2.4): `P_SetMobjState` (eligible calls: state chains whose actions are built), `P_RemoveMobj`, `P_UnsetThingPosition`, `P_DelSeclist`, `P_ExplodeMissile`; synthetic: a zone mobj removed and its slot taken again (the gate "no slot handed out twice"), a mobj with no function removed (`linkRemove`), a chain of 0-tic states, the rocket cheat flag

Its planted bugs (each must fail the named check): the action run before the tics are set; a mobj with no function freed at once instead of linked and deferred (`linkRemove`); a freed node put at the free list's tail (node order); the block list's back link left (lists); removal at once instead of deferred (the walk's next, 1.3); `poolFree` clearing the neighbour bit

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_map65.s:P_UnsetThingPosition` | `P_UnsetThingPosition` | demo3 254, demo1 362, demo2 134, newgame 3, tour 1 |
| `p_map65.s:P_DelSeclist` | `P_DelSeclist` | demo3 254, demo1 362, demo2 134, newgame 3, tour 1 |
| `p_map65.s:P_DelSecnode` | `P_DelSecnode` | demo3 605, demo1 714, demo2 264, newgame 15, tour 1 |
| `p_think65.s:P_RemoveThinker` | `P_RemoveThinker` | demo3 2, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_think65.s:P_RemoveThing` | `P_RemoveThing` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_think65.s:P_RemoveThinkerDelayed` | `P_RemoveThinkerDelayed` | demo3 13, demo1 8, demo2 8, newgame 0, tour 0 |
| `p_think65.s:P_RemoveThingDelayed` | `P_RemoveThingDelayed` | demo3 254, demo1 362, demo2 134, newgame 3, tour 1 |
| `p_think65.s:P_NextThinker` | `P_NextThinker` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_spawn65.s:P_RemoveMobj` | `P_RemoveMobj` | demo3 254, demo1 362, demo2 134, newgame 3, tour 1 |
| `p_spawn65.s:poolFree` | `poolFree` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `r_list65.s:linkRemove` | `linkRemove` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_tick65.s:P_SetMobjState` | `P_SetMobjState` | demo3 423, demo1 894, demo2 299, newgame 11, tour 10 |
| `p_tick65.s:rocketCheat` | `rocketCheat` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_tick65.s:P_MobjBrainlessThinker` | `P_MobjBrainlessThinker` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_mobj65.s:P_ExplodeMissile` | `P_ExplodeMissile` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_mobj65.s:explode` | `explode` | demo3 14, demo1 57, demo2 4, newgame 0, tour 0 |
| `p_mobj65.s:P_MobjIsPlayer` | `P_MobjIsPlayer` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |

Helpers: `p_map65.s:unlist`, `p_map65.s:link`, `p_map65.s:mvSector`, `p_map65.s:mvBlock`, `p_map65.s:blockOf`, `p_map65.s:snLink`, `p_think65.s:unlink`, `p_spawn65.s:rmArg`.

## What was built

| File | Content |
| --- | --- |
| `src/native/game/mobjstate/mslist.s` | `P_UnsetThingPosition`, `unlist`, `link`, `mvSector`, `mvBlock`, `p_map_blockOf`, `P_DelSeclist`, `P_DelSecnode` (upstream's `snLink` is its table of four link updates) |
| `src/native/game/mobjstate/msthink.s` | `P_RemoveThinker`, `P_RemoveThing`, `P_RemoveThinkerDelayed`, `P_RemoveThingDelayed` (the pool's free and the zone's free list, with the `CS_PREV` rule of GAME.md 1.8 item 3), `unlink`, `P_NextThinker`, `poolFree`, `linkRemove`, `P_RemoveMobj` (upstream's `rmArg` is its scratch copy of the mobj) |
| `src/native/game/mobjstate/msstate.s` | `P_SetMobjState` (the `ACTTAB` dispatch through `DCALL`, the rocket cheat through `FCALL A_CyberAttack`), `rocketCheat`, `P_MobjBrainlessThinker`, `P_ExplodeMissile`, `explode`, `P_MobjIsPlayer` |
| `src/native/game/mobjstate/msapi.s` | **Stand-ins** of request R2 (`ms_snget`, `ms_snput`, `ms_snw`, `ms_blget`, `ms_blput`, `ms_info`): the part's only `g_get`/`g_put`, each of a bank no cache holds (ZONE1, LVG1's `G_BLINKSAT` table, GTAB), in the core |
| `src/native/game/mobjstate/mstest.s` | The test routine `ms_t_seq` (the synthetic removal sequences); only in the part's own image (`part.mk`: `MS_TEST=1`) |
| `src/native/game/mobjstate/ms.inc` | The part's places: the scratch block's bytes, `MS_OBJ` (= `GA_0`, request R4) |
| `src/native/game/mobjstate/part.mk`, `args.json` | The fragment; the entries' inputs and outputs (`P_SetMobjState`, `P_RemoveMobj`, `P_UnsetThingPosition`, `P_DelSeclist`, `explode`, `P_ExplodeMissile`, `P_RemoveThingDelayed`) |
| `tools/native/gparts/mobjstate.py` | The part's harness: the image (with R1's stand-in), the captures, routine mode on both fills and both profiles with the write log, the stop check, the synthetic groups, the planted bugs, `report.json` |
| `tests/test_native_game_mobjstate.py` | Build, Checkpoint (every 8th captured case, every synthetic group), Plants |

### The interfaces (for the later waves' callers)

| Routine | In | Out | Notes |
| --- | --- | --- | --- |
| `P_SetMobjState` | `GA_0-1` (`MS_OBJ`) the mobj, A:X the state | A = 1 (Z clear) kept, 0 (Z set) removed by `S_NULL` | The action is called with the mobj in `GA_0-1`; the mobj is kept on the stack across it (an action may call `P_SetMobjState` again) |
| a mobj's `ACTTAB` action | `GA_0-1` the mobj | | (upstream's `_Dp`; a weapon action keeps `setPsprite`'s `GS_PSP`) |
| `THTAB`'s `P_RemoveThingDelayed`, `P_RemoveThinkerDelayed`, `P_MobjBrainlessThinker` | `GA_0-1` the thinker | | as secfind's thinkers (`docs/game-parts/secfind.md`); `P_RunThinkers` (part `tic`) reads the next thinker before the call |
| `P_RemoveMobj`, `P_UnsetThingPosition`, `explode`, `P_ExplodeMissile`, `linkRemove`, `P_RemoveThing`, `P_RemoveThinker` | A:X the mobj (thinker) | | |
| `P_DelSecnode` | A:X a node ($FFFF none) | A:X its next on the thing's thread | `gpos.s`'s `gp_secnodes` calls it |
| `P_DelSeclist` | | | `_s_sector_list` (`G_SECLIST`) |
| `P_NextThinker` | A:X a thinker ($FFFF: the first) | A:X the next, $FFFF after the last | (no caller in the tic) |
| `P_MobjIsPlayer` | A:X a mobj | A:X = `G_PLAYER` or 0 | (no caller in the tic) |
| `mvSector` | A:X the mobj, `GA_0` the new sector | | `P_TryMove`'s (part `trymove`); upstream's caller tests "already the first of that sector's list" itself |
| `mvBlock` | A:X the mobj, `GA_X`, `GA_Y` the new place (their high words are read) | | `P_TryMove`'s; the "already the first" test and the off-map case inside, as upstream |
| `p_map_blockOf` (`p_map65.s:blockOf`) | `GA_0-1` x, `GA_2-3` y (whole units) | C set off the map, else A:X the block's index | |
| `poolFree` | A:X a pool slot | | |

Temporaries: `GT_0-GT_6` and the scratch block `SB_MOBJSTATE` (32 B, all
used: `ms.inc`); no zero page of the part's own.

## 2. Requests

Each: what, why (with the evidence), what it changes for the other parts;
the integrator accepts or refuses it with its reason.

**R1. `gpos.s` (and `ghook.s`) import what they `FCALL`** (a build defect of
the skeleton). What: in `src/native/gpos.s`, after the line
`        .import fc_call, fc_unbuilt` of its `.ifndef LOADIMG` block, add

        .import P_DelSecnode

and in `src/native/ghook.s`, after `        .import g_stop, far_get, far_put, fc_call, fc_unbuilt`,
`        .import WI_Start` (part `flow`'s, the same defect). Better, in
`glayout.py`'s `MACROS`, `FCALL` could import a built target itself.
Why: once the part is built, `FCALL P_DelSecnode` expands to a `jsr`/`.word`
of a symbol `gpos.s` never imports, and ca65 has no auto-import:
`make -s -C src/native -f game.mk part P=mobjstate ROOT=$PWD` fails with
`gpos.s(607): Error: Symbol 'P_DelSecnode' is undefined`. An unused
`.import` is harmless (ca65 drops it; checked), so the line is safe in
every image, the load image included (it is in `.ifndef LOADIMG`). The
part's harness builds from a scratch copy whose `gpos.s` has the line
(`tools/native/gparts/mobjstate.py`, `GPOS_STANDIN`: the stand-in). Other
parts: every image with mobjstate built (waves 2-6, the game, the
release) needs it.

**R2. Object API calls for the three uncached records the part writes**
(`gobj.s`). What: `sn_get` (A:X a sector node: its `SN_SIZE` record into a
buffer, `LW_SN`), `sn_put` (A:X a node = the buffer), `sn_putw` (A:X a node,
Y a field: the word at `GO_T`), `bk_get`/`bk_put` (A:X a block's index: its
blocklink word, `G_BLINKSAT + 2 index` in LVG1), `mi_get` (A a type, Y a
field: the word of its mobjinfo record, GTAB `GT_MOBJINFO + 64 type`). Why:
the parts may not call `g_get`/`g_put`, and the API has no call for these
kinds; the core reaches them with `g_get`/`g_put` (`gpos.s` `sn_read`,
`node_prev`, `sn_thing`, `gp_setpos`'s blocklink; `gspawn.s`'s mobjinfo).
Until then the part's stand-ins (`msapi.s`, 192 B in the core, marked)
do it, of those banks only (the test's grep checks the banks). Other
parts: `checkpos`, `trymove`, `planes`, `teleport` (block lists, sector
nodes), `damage`, `spawn`, `missile`, `chase` (mobjinfo) need the same.

**R3. `grun.run` takes the entry's group from the placement, not its
address.** What: in `tools/native/grun.py` `run()`, replace

        grp = next(n for n, d in img.groups.items()
                   if _group_has(img.b, n, addr))

by the group `gen/gplace.inc` gives the routine (`GP_<name>_G`, 0 the core).
Why: two groups of one slot start at the same address, so the first group
whose range holds the address is often another routine's: with the
placement of `shared/placement.json`, `P_NextThinker` (group 8, `$A600`)
ran group 5's `P_RemoveThinker`, and `P_MobjBrainlessThinker` (group 25)
another group's code (the part's first synthetic runs, before the fix:
"crash GS 8", wrong states). The part's harness pokes `dg_entry` and
`dg_grp` itself (`entry_group()`). Other parts: every routine-mode run of
a routine in a group, through `gameroutine.run_case` too.

**R4. A name for the object of a dispatched call.** What: in `glayout.py`,
`GA_NAMES['GA_MO'] = 0` (two bytes, `GA_0-1`), and in
`src/native/game/README.md`'s "Calls: FCALL and DCALL": "a mobj's `ACTTAB`
action and a `THTAB` thinker function take their object (the mobj, the
thinker's handle) in `GA_MO` (`GA_0-1`), upstream's `_Dp`; a weapon action
takes its psprite in `GS_PSP`". Why: `DCALL` passes no register (`dc_call`
uses A, X, Y), and no convention was written; the part uses `GA_0-1`
(`ms.inc` `MS_OBJ`, the stand-in), as part `secfind` does for its thinkers.
Other parts: every action (`look`, `chase`, `pspr`, `wfire`) and thinker
(`tic`'s `P_RunThinkers` sets it, `secfind`, `planes`, `movers` read it).

**R5. `gameroutine.py`'s `args.json` conversions.** What: `"as"` for the
kinds `secnode` and `thinker` (a mobj, a special, or a special waiting for
its removal, kind `removed`: the port writer puts it after its home kind's
objects), in and out (a returned node compared by its sector and thing;
a thinker by its handle), and an output `player` (`G_PLAYER` against
`&_g_player`, 0 against NULL). Why: `P_DelSecnode`, `P_RemoveThinker`,
`P_RemoveThinkerDelayed`, `P_NextThinker` and `P_MobjIsPlayer` take or
give these; `run_case` converts only `mobj` and would pass a raw pointer.
Their specs are in the harness until then (`LOCAL_SPECS` and the synthetic
specs), its `_convert` and output code the proposed text. Other parts:
part `secfind` asked for the same (its request 6).

**R6. The survey's reached targets miss actions that are survey entries of
another pass.** What: in `gamecap.py`'s `passes()`, keep an entry with the
dispatch targets it reaches even when a target is itself an entry, or
attribute an entry's call to its caller across passes; then remake the
survey. Why: of demo3's 422 `P_SetMobjState` calls, 122 reach an unbuilt
action (52 `A_Chase`, 38 `A_FaceTarget`, 32 `A_Look`, from each state's
action in the reference's memory), but the survey attributes only the 38
`A_FaceTarget` ones (`gameroutine.py --eligible mobjstate`: 385
"eligible", of which 84 stop at `A_Chase` or `A_Look`). The part decides
eligibility from the reference's memory instead (`reaches()`: the state's
action, the rocket cheat; `explode`'s through its death state), exactly.
Other parts: every dispatcher's eligibility (`setPsprite`'s, `tic`'s,
`geom`'s, `path`'s, `lines`').

**R7. The bridge's coverage problem of a mobj taken off its lists.** What:
in `tools/bridge/upstream.py`, claim a mobj's `snext`, `sprev`, `bnext`,
`bprev` as `excl:dead link` when it is on no list of its kind (between
`P_UnsetThingPosition` and the new place or the end of `P_RemoveMobj`),
or accept the part's named rule (`stale_link_problems()`). Why:
upstream's `unlist` leaves the thing's own links as they were, so every
return of `P_UnsetThingPosition` and every entry and return of
`P_DelSeclist` (inside `P_RemoveMobj`) has a mobj whose 16 link bytes are
on no list: the reader reports "mobj N: its snext link is on no list"
(and the zone bytes "neither a field nor an exclusion": the same 16
bytes), though every canonical field is decoded. The part accepts exactly
these problems (each naming a link of a mobj named by a link problem) and
compares the whole canonical state; any other problem fails. The same
holds for a mobj `mvBlock` puts off the map (its block links NULL, not
`MF_NOBLOCKMAP`). Other parts: `trymove` (`P_TryMove` around `mvSector`,
`mvBlock`), `teleport`.

**R8. The placement of the part's routines.** What: one group (or the
core) for `unlist`, `link`, `blockOf`, `mvSector`, `mvBlock`,
`P_UnsetThingPosition`, `P_DelSeclist`, `P_DelSecnode`, `P_RemoveMobj`,
`linkRemove`, `P_RemoveThing`; one for `P_RemoveThingDelayed`,
`P_RemoveThinkerDelayed`, `unlink`, `poolFree`; `P_SetMobjState`,
`rocketCheat`, `explode` together (they are). Why: the initial placement
spreads the part over 10 groups (5, 8, 11, 14, 15, 18, 19, 21, 25 and the
core's stand-ins); `unlist` (group 14) and `blockOf`, `link` (group 15)
share slot 1, so every block-list `unlist` loads both groups again
(`FC_LOADS`: the report's `fc_loads` per entry). The routines' native
sizes are in the report (`sizes`). Other parts: none (the integrator's
`gplace.py`).

**R9. Over budget.** The part is 2,186 B (without `msapi.s`'s 192 B of
stand-ins, which belong to the API by R2, and the test routine), 15% over
1,900 B. Why: 8-bit code for upstream's 16-bit pointer moves (a link is
two loads and stores a byte a field, through `mo_get`/`sec_get` and a
dirty mark), the handles' head cases upstream does not have (a native
list's first has prev none, not `&head`: `unlist` finds the head by the
sector of its subsector or the block of its place, ~120 B), the cross-group
`FCALL`s (6 B each), and both list kinds of `unlist`/`link` served by
tables. Already table-driven: `unlist`, `link`, `P_DelSecnode` (saved 78
B). Other parts: the core's room (4.2).

**R10. Two helpers are inlined.** `p_spawn65.s:rmArg` (P_RemoveMobj keeps
its mobj in its scratch block) and `p_map65.s:snLink` (P_DelSecnode's
table loop) have no native label: please list them as inlined (as
`CORE_INLINES` does for the core) so the placement reserves nothing for
them.

**R11. `GAME.md` 2.2's `THTAB` row** names `tic` the owner of the brainless
thinker; `glayout.PARTS` gives `P_MobjBrainlessThinker` to this part, which
builds it (`THTAB` entry 2 is filled when the part is built). The text
could say `mobjstate (the brainless thinker, the two removals)`.

## 3. Results

The full checkpoint (2026-10-01): `python3 tools/native/gparts/mobjstate.py
--check --plants --jobs 2` (the image, every case, both fills `$A5` and
`$5A`, both profiles `f121` and `fastpath`: 4 runs a case), 1,926 s; its
report `build/native/game/mobjstate/report.json`. **8,816 runs, 0 failed,
0 stray writes**; 796 runs (199 cases) counted apart as undecodable (below).
The test module (`tests/test_native_game_mobjstate.py`: every 8th captured
case, every synthetic group, the seven plants) passes in 400 s.

| Entry | Cases (runs) | Call clock f121, median / worst | fastpath | Lowest S |
| --- | --- | --- | --- | ---: |
| `P_SetMobjState` | 300 captured (1,200): no action 218, `S_NULL` 82; 122 stop checks (488); 5 synthetic (20) | 39.0k / 420.4k (0.29 / 3.15 ms) | 28.5k / 315.0k | $D7 |
| `P_RemoveMobj` | 254 (1,016) | 242.1k / 484.1k (1.82 / 3.63 ms) | 180.9k / 362.9k | $D9 |
| `P_UnsetThingPosition` | 254 (1,016), every one with R7's rule | 69.7k / 136.7k | 50.0k / 99.5k | $DE |
| `P_DelSeclist` | 254 (1,016), every one with R7's rule | 48.4k / 93.9k | 36.0k / 66.7k | $E0 |
| `P_DelSecnode` | 101 captured (404) of 300 (199 undecodable); 259 of the skeleton's `P_CreateSecNodeList` cases that free a node (1,036) | 68.0k / 162.0k | 49.1k / 106.4k | $DF |
| `explode` | 75: demo3 14, demo1 57, demo2 4 (300) | 44.7k / 44.7k | 32.6k / 32.6k | $E2 |
| `P_ExplodeMissile` | 75 on explode's states, ref816 `--call` (300) | 58.6k / 58.6k | 43.2k / 43.2k | $DD |
| `P_RemoveThingDelayed` | 254 on the states after `P_RemoveMobj`'s calls, ref816 `--call` (1,016) | 46.7k / 49.8k | 33.6k / 35.8k | $E1 |
| `P_RemoveThinker`, `P_RemoveThinkerDelayed` | 2 captured + 1 synthetic; 2 (20) | 17.1k; 43.7k | 12.9k; 32.1k | $E1, $E4 |
| `P_RemoveThing`, `P_NextThinker`, `P_MobjIsPlayer`, `P_MobjBrainlessThinker` | 1; 4 (none, the first, the last, a special); 2; 3 (tics 5, 1, -1) (40) | 27.7k; 17.1k; 13.8k; 14.4k | 21.2k; 12.9k; 10.6k; 11.2k | $E1 |
| `mvSector`, `mvBlock` | 6 (2 sectors, 3 things); 24 (8 places: the same block, east, north, off each edge, the far corner) (120) | 137.9k; 123.5k / 175.2k | 100.4k; 90.8k | $DE |
| `ms_t_seq` (synthetic sequences) | 7: the zone gate, `CS_PREV`, no function pooled (4) and zone (28) | 413.9k / 535.5k | 311.7k / 400.0k | $D7 |

Clocks are the cost model's fabric clocks (133.33 MHz) from `call_entry`
to the call's return, paging loads included (`fc_loads` in the report:
`P_RemoveMobj` loads 8 groups at the median, 16 at worst: R8).

**Eligibility** (GAME.md 3.5 step 6), from the reference's memory
(`reaches()`, R6): of demo3's 422 `P_SetMobjState` calls (the survey's 423
counts one JML entry `--capture` does not, hit 240), 300 reach no action
or `S_NULL`; 122 reach an unbuilt action (`A_Chase` 52, `A_FaceTarget` 38,
`A_Look` 32) and are stop checks: the native stops at the action's
`DCALL` (`GS_UNBUILTD`, the action's number) with the mobj's state, tics,
sprite and frame equal to the reference's at the action's entry. Every
`explode` call is eligible (no death state of E1's missiles has an
action). The 300 calls are all of the eligible ones (the minimum is 300
spread evenly), with every path: `S_NULL`, a state with no action, the
stop at an action.

**Undecodable**: 199 of the 300 captured `P_DelSecnode` calls are inside
`P_DelSeclist`, whose `_s_sector_list` still names the nodes freed before
(upstream clears it at the end): the reference's state is no canonical
state. They are counted apart, never equal; `P_DelSecnode` is checked on
the 101 others, the 259 `P_CreateSecNodeList` cases and every
`P_DelSeclist` and `P_RemoveMobj` call.

**Synthetic cases** (GAME.md 2.4's row), each from demo3's states, the
reference run alone on ref816 (`--call`, one call after the other):
- the gate "no slot handed out twice": the pool filled (70 puffs at the
  player's place), a puff spawned (zone slot 337), removed
  (`P_RemoveMobj`), freed in its thinker's turn (`THTAB`'s entry of its
  kind, natively), spawned again: the native takes slot 337 again from the
  zone's free list, the states equal ref816's;
- a zone mobj `CS_PREV1` names freed: `CS_PREV1` `stale` on both sides
  (`$FFFE`), `GT_ZPREV` raised;
- a mobj with no function removed: 4 items of demo3 (pooled) and a clip
  spawned in a full pool (zone, then its slot taken again): linked by
  `linkRemove`, freed in its turn;
- a chain of 0-tic states (states 86-88 poked on both sides: the native
  GTAB and upstream's table);
- the rocket cheat (an imp, type 3): `CF_ENEMY_ROCKETS` with the first and
  the last state of [missilestate, painstate) with an action: the native
  calls `A_CyberAttack` (`FCALL`: the unbuilt stop of its routine, 526),
  state and tics as the reference's at its entry; `missilestate - 1` and
  the cheat off: the state's own action.

**Planted bugs** (`--plants`), each in a scratch copy of the part's
sources, its image in a temporary directory: all 7 caught by their named
check: the action before the tics (the stop check: tics 10, upstream 3),
a mobj with no function freed at once (the synthetic removal: its
function), a freed node at the free list's tail (`P_DelSeclist`: the
`SN_FREE` sequence), the block list's back link left (`P_UnsetThingPosition`:
the port reader's list check), removal at once (`P_RemoveMobj`: the
thinker list), `poolFree` clearing the neighbour bit (the removers: a
free bit), `CS_PREV` left naming a freed zone slot (the `CS_PREV`
synthetic: `stale` against a zone mobj).

**Arithmetic helpers**: none of GAME.md 2.4's list is this part's. Its one
computing helper, `blockOf`, is compared through `mvBlock`'s 24 places
(the map's four edges and the far corner) and every block-list head of
`P_UnsetThingPosition`.

**Sizes** (the image's map): `mslist.s` 978, `msthink.s` 665, `msstate.s`
543: **2,186 B against 1,900 (+15%, R9)**; the stand-ins `msapi.s` 192 B
(R2), the test routine `mstest.s` 155 B (the part's image only).

**Stack**: the lowest S of every run is $D7 (the driver starts at $EF:
24 bytes below, the sequences' spawn included); `P_SetMobjState` keeps
its mobj (2 B) on the stack across an action.

**build/**: `build/native/game/mobjstate/` 40 MB (the cases 29 MB, the
journal and the report, the image); every temporary directory deleted.

## 4. Open points

- The skeleton's `gpos.s` does not assemble with the part built (R1):
  until the integrator adds the import, `make -f game.mk part
  P=mobjstate` fails and only the part's harness (its scratch copy) builds
  the image.
- `gameroutine.run_case` (the integrator's rerun of every checkpoint) runs
  no profile and no write log, picks the entry's group by address (R3)
  and converts only mobjs (R5): the part's own harness does all three;
  the integrator can run `tools/native/gparts/mobjstate.py --check`.
- 122 `P_SetMobjState` calls wait for `look` (`A_Look`, wave 3) and
  `chase` (`A_Chase`, `A_FaceTarget`... wave 6): checked only up to the
  action now (the stop check).
- `mvSector` and `mvBlock` are checked on ref816's own calls with chosen
  places; their real calls come with `trymove` (wave 4), whose
  `P_TryMove` tests "already the first of the new sector" itself.
- The delayed removers' cases are ref816's own calls on the states right
  after `P_RemoveMobj`, not the walk's calls (`--capture` does not count
  their JML entry; part `secfind` captures at `callFn`).
- `P_RemoveThinkerDelayed` of a mobj is a stop (`GS_ERROR`): upstream
  never makes one (only specials call `P_RemoveThinker`).
- A special waiting for its removal is written by the port writer after
  the scroll kind's objects (`removed`'s home): natively its free goes to
  the scroll kind's free list in those cases (not canonical: the
  specials' identity is their rank).
- From the skeleton: the 259 `P_CreateSecNodeList` cases waiting for
  `P_DelSecnode` are equal now (above); the removal half of a mobj with
  no function is checked (the synthetic removals and the 12 captured
  pickups of `P_RemoveMobj`).

## 5. The integration of wave 1 (2026-10-01)

| Request | Decision |
| --- | --- |
| R1 the imports | **Accepted**, generally: `FCALL` makes a built target `.global` (glayout.py `MACROS`), so no source needs an `.import` of an `FCALL` target; the harness's `GPOS_STANDIN` is gone |
| R2 the API calls | **Accepted**: `gobj.s` `sn_get`, `sn_put`, `sn_putw` (`SN_BUF`, `API_W`), `bk_get`, `bk_put`, `mi_get` (`API_W`); `msapi.s` is deleted; `ms.inc`: `MS_W = API_W`, `DN_REC = SN_BUF`; the part's test now checks it has no far access at all |
| R3 `grun.run`'s group | **Accepted** (`grun.entry_group`) |
| R4 `GA_MO` | **Accepted**: `glayout.GA_NAMES['GA_MO'] = 0`; `MS_OBJ = GA_MO`; the README states the dispatch conventions |
| R5 `args.json` conversions | **Accepted in part** (as geom's R5): the part's harness keeps its specs; one harness is an open item |
| R6 the survey | **Accepted** (as geom's R10): `gamecap.passes` keeps a dispatcher and its target entries in different passes; the survey is remade |
| R7 the dead links | **Accepted as the part's named rule** (no bridge change: every existing manifest stays as it is): the 16 link bytes a mobj keeps after leaving its lists, and NULL block links off the map, are the only problems `stale_link_problems()` accepts, every canonical field still compared; parts `trymove` and `teleport` use the same rule (GAME.md 3.5, R7 added there) |
| R8 placement | **Accepted**: `gplace.AFFINITY`'s three units of this part |
| R9 over budget | Accepted: 2,186 B against 1,900 (+15%), reasons above; the placement uses the measured sizes |
| R10 inlined helpers | **Accepted**: `glayout.INLINED` (`snLink`, `rmArg`): no placement bytes |
| R11 GAME.md's `THTAB` row | **Accepted** |

**The plant "a freed node at the free list's tail" is not observable**
(found by the integration): the canonical model numbers the free sector
nodes in the free list's order (`tools/bridge/identity.py`: "the free
list" last), so a free list's order is no state and no check can see it;
with `msapi.s`'s stand-ins the plant failed only through its own
interplay with the stand-ins' temporaries (its diff showed node 0 not
freed), and with the object API its 254 `P_DelSeclist` cases all pass.
It is replaced by `node-not-freed` (the freed node left off the free
list: `SN_FREE` and the node's `free` differ), caught on the first
`P_DelSeclist` case. GAME.md 2.4's row says so.

Rerun at the integration (`mobjstate.py --check --plants --jobs 2`): 8,816 runs, 0 failed, 0 stray writes; 7 plants caught; `P_RemoveMobj` 0.79 ms at the median on `f121` (1.82 before: the placement's affinity units); the test module 8 tests OK. Size 2,167 B.

## 6. The integration of wave 3 (2026-10-02)

`waiting_for` counted every other part's action as unbuilt; it now uses `glayout.built_set` (the earlier and integrated waves, as `game.mk`'s part target), so `P_SetMobjState`'s calls of wave 3's actions (`A_Look`, `A_FaceTarget`, the screams, `A_Pain`, `A_Fall`, the weapon actions) run whole; the rocket cheat's synthetic calls whose own action is built are the reference's own call compared whole (`ref_case`), not a stop check. The shared stray rule (`allowed_main`) allows the scratch blocks of the other parts built in the image (a dispatched action writes its own part's block: look's `loadTarget`); an unbuilt part's block stays a stray.

## 7. The integration of wave 6 (2026-10-02)

Every `ACTTAB` action is now built, so no `P_SetMobjState` call can stop
at an unbuilt one.

- **The rocket cheat.** The cheat's synthetic calls that expected the
  unbuilt `A_CyberAttack` (part chase) are now the reference's own call,
  compared whole (`ref_case`), as calls of other built actions already
  were. Before this change they reported "no stop".
- **The test.** `test_the_stop_check` asserts at least one stop while any
  action is unbuilt. Once every action is built it asserts that no call
  stopped and that the cheat's calls ran.
- **The stray rule.** The shared rule now also allows `TEXTRANS`,
  `NUKAGE` and the driver's descriptor (`tic.md` R2).
