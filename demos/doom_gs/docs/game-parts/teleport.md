# Part `teleport` (wave 4)

The record of milestone 10's part `teleport` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 4; upstream 1130 B, native budget 1500 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 4's `teleport` (2026-10-02), under the owner's
  lean checks of 2026-10-02 (at most 40 calls a routine, one poisoned
  machine `$A5`, at most 3 planted bugs, the test under 60 s).
- Files: `src/native/game/teleport/*.s`, `src/native/game/teleport/part.mk`, `src/native/game/teleport/args.json`, `tests/test_native_game_teleport.py`, this file; tools (if any) `tools/native/gparts/teleport*.py`; build output `build/native/game/teleport/` (`make -s -C src/native -f game.mk part P=teleport ROOT=$PWD`).
- Its scratch block: `SB_TELEPORT` (32 B, `ggame.inc`; 30 used: `teleport.inc`).

The routines (GAME.md 2.4's row):

`p_telept65.s`: `EV_Teleport:51` (the destination by tag through the thinkers, the fogs, the angle, momentum and reaction time); `p_map65.s`: `P_TeleportMove:3420` (the stomp through `P_BlockThingsIterator` and `stompThing:3548`); helpers `fogSound`, `times20`, `thingArg`, `destArg`, `destination`, `tpThing`, `farFrom`

Its checkpoint (GAME.md 2.4): Synthetic mostly: every teleport line of the nine maps (special 97 [R `p_switch65.s:598`]) crossed by the player and by a monster, a thing at the destination; the captured ones of the generated streams

Its planted bugs (each must fail the named check): the destination found from the last thinker; the fog's z; the reaction time given to a monster; a stomp of a thing that is not shootable

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_telept65.s:EV_Teleport` | `EV_Teleport` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_map65.s:P_TeleportMove` | `P_TeleportMove` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_map65.s:stompThing` | `stompThing` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |

Helpers: `p_map65.s:tpThing`, `p_map65.s:farFrom`, `p_telept65.s:fogSound`, `p_telept65.s:times20`, `p_telept65.s:thingArg`, `p_telept65.s:destArg`, `p_telept65.s:destination`, `p_switch65.s:lnTele`.

`thingArg` resolved: `p_telept65.s`'s, as `glayout.PARTS` has it
(`p_map65.s` has none; the other `thingArg` is `p_floor65.s:441`, part
`planes`').

### 1.1 What was built

| File | What |
| --- | --- |
| `src/native/game/teleport/teleport.s` | The part's routines, a GPL-2 derivative of upstream's `p_telept65.s` (`EV_Teleport`, `fogSound`, `times20`, `destination`), `p_map65.s` (`P_TeleportMove`, `stompThing`, `farFrom`) and `p_switch65.s` (`lnTele`: `LSTAB`'s entry 8). `thingArg`, `destArg` and `tpThing` are done in place (the handles kept in the scratch block: `TP_THING`, `TP_DEST`, `TP_TPT`; request R1). `EV_Teleport`'s local `front` is upstream's `times20` call and add, `clean` its `CLEARCLEAN` (the kind plane's `KIND_CLEAN` bit through `pl_get`, `pl_put`) |
| `src/native/game/teleport/teleport.inc` | The scratch block's bytes (upstream's `TP_*`, `MP_TPX`, `MP_TPY`, `MP_TPT`, `MP_TELEFRAG`; the destination search's and the angle's bytes overlaid on `P_TeleportMove`'s, which are dead around them), the mobj line's groups |
| `src/native/game/teleport/tptest.s` | `tp_bulk`: `times20` on many inputs (the random check), in the driver's area, linked only into the part's own image (`part.mk`'s `TP_TEST=1`, as damage's `dtest.s`) |
| `src/native/game/teleport/part.mk`, `args.json` | The fragment; the entries' inputs and outputs (checkpos's forms: `gw:` places), and under `callers` `P_CrossSpecialLine` with lines' inputs and this part's outputs (the synthetic calls enter there) |
| `tools/native/gparts/teleport.py` | The lean checkpoint: the bases (`--capture`: the tour's `P_UpdateSpecials` every 20th call, as lines' and evworld's, then the three maps with teleport lines again with every page of RAM, below), the synthetic sequences on ref816 (`--synthetic`), the runs (`--check`), `times20`'s random check (`--random`), the planted bugs (`--plants`), `report.json`. It imports part `secfind`'s machinery (`Ref`, `Native`, `sounds`), part `lines`' (`Base`, `base_calls`), part `evworld`'s (`Base`, `ref_call`), part `checkpos`'s (`Prep` with `gw:` places, `outputs`, `check_writes`), part `mobjstate`'s native checks and part `sight`'s `mathref` |
| `tests/test_native_game_teleport.py` | The build within budget, `args.json` against the image, `LSTAB`'s `lnTele` and `ITTAB`'s `stompThing`, the far-access grep, a sample of the checkpoint (E1M5's first line: 11 calls), `times20` on 10,000 inputs, the three planted bugs (20 s); `DOOM_GS_FULL=1` adds every synthetic call on both profiles and 100,000 inputs (30 s more) |

**The whole-RAM bases.** A captured case keeps only the pages the bridge's
reader reads and the pages its own call touches; its other pages are the
run's first hit's (E1M1's). `P_UpdateSpecials`' case is enough for part
`lines`' and `evworld`'s calls, but a teleport spawns (`P_SpawnMobj`'s pool
bits, the zone) and moves things: run on the plain bases, ref816's
results decoded with bridge problems (a fog spawned into a live slot's
record: "thinker ... is not a declared thinker function"; block links
"on no list"). The three bases the calls use (E1M5 `h261`, E1M8 `h401`,
E1M9 `h141` of the tour's `P_UpdateSpecials`) are captured again with
every page of RAM (`teleport.py` `capture_full`, in gamecap's case format,
about 1 MB a case): every reference state then decodes with 0 problems.

### 1.2 The native interfaces

| Routine | In | Out |
| --- | --- | --- |
| `EV_Teleport` | `GA_0-1` the line, `GA_4-5` the thing (a mobj handle), `GA_6` the side (0 front, 1 back): upstream's `_Dp[0-3]`, `_Dp[4-7]`, C | A = 1 teleported, else 0 |
| `lnTele` (`LSTAB` 8) | `P_CrossSpecialLine`'s places (lines' request 3: the same as `EV_Teleport`'s) | A = `EV_Teleport`'s result |
| `P_TeleportMove` | `GA_0-1` the thing, `GA_2-5` x, `GA_6-9` y, `GA_10` boss (0, 1): upstream's `_Dp[0-3]`, X:C, `_Dp[4-7]`, the word at 4,s | A = 1 moved, 0 blocked; `GM_TMTHING`, `GM_TMX`, `GM_TMY`; `baseFloorL`'s `GM_TMFLOORZ`, `GM_TMCEILZ`, `GM_TMDROPZ`, `GM_NSPEC` 0, `validcount` + 1, `G_CEILLINE` none |
| `stompThing` (`ITTAB` 4) | `GA_0-1` the mobj (geom's convention) | C set go on, C clear blocked |
| `fogSound` | `GA_X`, `GA_Y`, `GA_Z` | a fog there (`P_SpawnMobj`, `MT_TFOG`), `S_StartSound(fog, sfx_telept)` |
| `times20` | `GA_0-3` | `GA_0-3` = 20 x it, the low 32 bits |
| `destination` | `TP_LINE` (the scratch block) | C set: `TP_DEST` the destination |
| `farFrom` | `GC_MP` the thing, Y = `TH_X` or `TH_Y`, X = 0 (`tmx`) or 4 (`tmy`), `GT_0-3` the block distance | C set when the distance is at least it (upstream's signed `SLT32`) |

Every routine changes `GA_*`, `GT_*` (`farFrom` `GT_4-7`), `GC_*`, `GS_*`
(the spawn's), the math block, the object API's lines and the hooks'
state. `P_TeleportMove` keeps its block loop (bx, by, XH, YL, YH) on the
stack across `P_BlockThingsIterator`, as upstream does (request R3).

**The destination's walk is inline.** Upstream walks the thinker list
once a tagged sector [R `p_telept65.s:276-348`]; natively the walk reads
the planes (`pl_get`: a mobj's next and kind) and a special's record
(`sp_get`: `SP_THNEXT`) itself, as mobjstate's `P_NextThinker` does,
instead of `FCALL P_NextThinker` once a thinker (mobjstate's group: two
group loads a thinker when it shares a slot with the caller). A mobj is a
destination when its kind (`KIND_CLEAN` masked, as upstream masks its
byte 11) is `FN_MOBJ`, its type `MT_TELEPORTMAN` and its subsector's
sector the tagged one.

## 2. Requests

Each: what, why (with the evidence), what it changes for the other parts;
the integrator accepts or refuses it with its reason.

**R1. `glayout.INLINED['teleport'] = ('p_telept65.s:thingArg', 'p_telept65.s:destArg', 'p_map65.s:tpThing')`.**
No code of their own: upstream's argument loaders (`_Dp` = `TP_THING`,
`TP_M`, `MP_TPT` [R `p_telept65.s:262-271`, `p_map65.s:3540-3544`]) are the
handles `TP_THING`, `TP_DEST`, `TP_TPT` of the scratch block, read in
place. Other parts: none (the placement gives them no bytes).

**R2. Placement: one group for the part.** The estimates put its routines
in three groups (`EV_Teleport`, `stompThing` 19; `lnTele`, `fogSound`,
`times20`, `destination`, `farFrom` 20; `P_TeleportMove` 25), and 19 and
20 share slot 1: every `FCALL` of a helper from `EV_Teleport` and of
`farFrom` from `stompThing` (twice a thing near the destination) reloads
the slot twice, and `lnTele` -> `EV_Teleport` once more. What:
`gplace.AFFINITY` +=

    ('p_switch65.s:lnTele', 'p_telept65.s:EV_Teleport',
     'p_telept65.s:fogSound', 'p_telept65.s:times20',
     'p_telept65.s:destination', 'p_map65.s:P_TeleportMove',
     'p_map65.s:stompThing', 'p_map65.s:farFrom'),

1,305 B measured (section 3; 1,221 when R4 is applied), within slot 2's
2,048. The teleport is cold (no survey run calls it), so not the core.
Other parts: none (placement only).

**R3. `glayout.OWN_STACK['p_map65.s:P_TeleportMove'] = 5`.** The block
loop's five bytes on the stack across `P_BlockThingsIterator`, as
upstream's own [R `p_map65.s:3449-3495`]: `stompThing`'s `P_DamageMobj`
runs game logic, and the scratch block has 2 bytes left. It is on GAME.md
4.5's deepest chain (`EV_Teleport` -> `P_TeleportMove` ->
`P_BlockThingsIterator` -> `stompThing` -> `P_DamageMobj` -> ...), so
`gcallgraph.py --stack` should count it. Measured: the lowest S of every
run is `$AE` (`P_CrossSpecialLine` with a telefrag; the driver starts at
`$EF`). Other parts: none.

**R4. `gpos.s` `gp_secnodes` (`P_CreateSecNodeList`) leaves `GM_TMX`,
`GM_TMY` = the thing's x, y, as upstream's does.** Upstream's
`P_CreateSecNodeList` sets `tmx, tmy = thing->x, y` and does not restore
them (it restores only `tmthing` [R `p_map65.s:2524-2531`, `:2610-2615`]);
`P_SetThingPosition` calls it for every thing without `MF_NOSECTOR` [R
`p_map65.s:784-804`]. A telefrag's kill of a zombieman or a shotgun guy
spawns its drop at the victim's x, y (`killMobj` [R
`p_inter65.s:1100-1140`]), so upstream's later stomps of the same
`P_TeleportMove` measure from the victim, not from the destination
(`stompThing` reads `tmx`, `tmy` [R `p_map65.s:3572-3579`]). Natively
`gp_secnodes` builds its own box and leaves `GM_TMX`, `GM_TMY`
(checkpos.md's open point). Evidence: the synthetic sequences "a monster
and a dropper 30 units on either side of the destination
(`P_TeleportMove` with boss set), then the player's crossing onto both":
in 5 of 6 the reference kills the dropper only (its drop is 60 units from
the other monster, beyond the 46 of the two radii), and with the part's
stand-in removed 5 of 6 runs fail (`_g_totallive` 90 against 89,
`prndindex` 17 against 18). **The stand-in** (`stompThing`, marked, 84
B): before the damage it keeps the victim's sector and the first thing of
that sector's list; after it, when that first thing changed (a thing was
set into the sector: the drop, which `P_SetThingPosition` links at the
head of the victim's sector and passes to `P_CreateSecNodeList`),
`GM_TMX`, `GM_TMY` = its x, y. Exact for `P_TeleportMove` (no other thing
is positioned during a stomp), but the shared fix belongs in the core.
What to add to `gp_secnodes` (about 16 B; the core had 86 B left at wave
3): copy the thing's `TH_X`..`TH_Y + 3` into `GM_TMX`..`GM_TMY + 3` where
it takes the thing's position for its box. Then the stand-in goes.
Other parts: any routine that reads `tmx`, `tmy` after a spawn or a
`P_SetThingPosition` gets upstream's value (part `trymove` after
`mvNodes`, `chasemove`'s `avoidDropoff`, if they read them there);
`checkpos` sets them itself before each walk.

**R5. README "The parts' interfaces"**: the rows of 1.2 above for
`EV_Teleport`, `lnTele`, `P_TeleportMove`, `stompThing`.

No layout field, scratch byte or exclusion is asked: the shared `GM_*`
(`GM_TMTHING`, `GM_TMX`, `GM_TMY`, `GM_TMBBOX`, `GM_TMFLOORZ` ..,
`GM_NSPEC`, `GM_BXL` .. `GM_BYH`) and the exclusions R1-R7 serve.

## 3. Results

**The checkpoint** (`python3 tools/native/gparts/teleport.py --capture`,
`--synthetic`, `--check --jobs 2`; 2026-10-02; the part's image links waves
1-3 and the part; `$A5` only, `f121` and `fastpath`): **122 runs, 0
failed, 0 waiting, 0 stray writes.** No survey run calls a routine of the
part (section 1), so every case is synthetic: ref816 `--call` of
upstream's routine on the in-play state of the tour's three maps with
teleport lines (E1M5: 10 lines, tag 5; E1M8: 8, tag 3; E1M9: 2, tag 7; the
other six maps have none), each call on the state the calls before it in
its sequence left. Every teleport line is crossed by the player; a
monster crosses the first line of each map and 2 more (the lean cut: 40
calls of `P_CrossSpecialLine`). Compared: the canonical state after the
call (gcanon's routine mode, R1-R7 only), the declared outputs (the
result; `tmthing`, `tmx`, `tmy`, `tmfloorz`, `tmceilingz`, `tmdropoffz`,
`numspechit` (which `P_TryMove`'s `spec` loop reads after the crossing),
`ceilingline`), the two `sfx_telept` events at the fogs (R6's events,
compared exactly, the old place's first), mobjstate's native list checks,
no stray write.

| Routine entered | Calls | Runs | Failed | Stray | Paths (calls) | Cycles median / worst, `f121`; `fastpath` | Lowest S |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `P_CrossSpecialLine` (`lnTele` -> `EV_Teleport`) | 40 | 80 | 0 | 0 | the player teleported 17, onto a monster (telefrag) 1, onto a dropper (telefrag, a drop) 7, onto two (both killed) 1; a monster teleported 5, past a thing not shootable 3, blocked by the player 3; the player from the back side 3 | 4,336,347 / 6,344,700 (32.5 / 47.6 ms); 3,110,355 / 4,631,732 (23.3 / 34.7 ms) | `$AE` |
| `EV_Teleport` alone | 9 | 18 | 0 | 0 | the player teleported 3; a missile 3; a tag with no destination 3 | 1,915,782 / 4,646,137 (14.4 / 34.8 ms); 1,296,083 / 3,355,165 (9.7 / 25.2 ms) | `$CC` |
| `P_TeleportMove` alone (boss set) | 12 | 24 | 0 | 0 | moved 12 (a monster beside the destination, then a dropper beside it) | 2,908,546 / 3,705,559 (21.8 / 27.8 ms); 2,157,591 / 2,791,156 (16.2 / 20.9 ms) | `$D1` |

`stompThing` (`ITTAB`) runs under every `P_TeleportMove`: shootable and
not, `tmthing` itself, near and far, telefrag and blocked, the drop's
`tmx` (R4). Cycles are fabric clocks at 133.3 MHz from the routine's
entry to its return, every slot empty at the call (upper bounds: the
paging of three groups, R2; the destination walk's `mo_get` of every mobj
thinker of each tagged sector).

**`times20`'s random check** (`teleport.py --random`): 100,000 inputs (21
edges: 0, +-1, +-2, the extremes, the words' edges, 2^32 / 20's
neighbours; then random 32-bit, finesine-sized and powers of two),
upstream's `times20` on ref816's machine (milestone 6's `mathref` batch,
`TP_T` out) against the native (`tp_bulk`): 0 different; upstream's equal
20 v mod 2^32 on all.

**The planted bugs** (`teleport.py --plants`, the lean three, each in a
scratch copy, built in a temporary directory, deleted):

| Plant | Check | Caught |
| --- | --- | --- |
| `fog-z`: the second fog at the old z, not the thing's after the move | the player's crossings (17) | 8 of 17 runs fail (`mobj[13].z`) |
| `react-monster`: every thing waits 18 tics | a monster's first crossing (3) | 3 of 3 (`mobj[66].reactiontime: 8 != 18`) |
| `stomp-not-shootable`: no shootable test in `stompThing` | a monster past a thing made not shootable (3) | 3 of 3 (blocked: no fogs, `prndindex` 17 != 15) |

GAME.md 2.4's fourth, "the destination found from the last thinker", is
not planted (the lean rule's three): no E1 tag has two destinations (one
`MT_TELEPORTMAN` a map), so first and last are the same thing and no
check could see it.

**The stand-in of R4 checked** (ad hoc, not one of the three): with its
code removed, 5 of the 6 sequences onto a dropper fail.

**Sizes** (`teleport.o` in the part's image, `teleport.py` `sizes`):
**1,305 of 1,500 B** (upstream 1,130): `EV_Teleport` 504 (with `front` and
`clean`), `P_TeleportMove` 279, `stompThing` 232 (84 of them R4's
stand-in), `destination` 141, `farFrom` 75, `times20` 51, `fogSound` 16,
`lnTele` 7; in groups 19, 20 and 25 (R2). `tptest.s` (the part's own image
only, in the driver's area): 148 B.

**Other checks.** `make -s -C src/native -f game.mk part P=teleport
ROOT=$PWD` (and with `TP_TEST=1`): no warnings. `gcallgraph.py --check
--built` waves 1-3 and `teleport`: 0 failures. `gameroutine.grep_check` on
`teleport.s`: clean. `python3 -m unittest tests.test_native_game_teleport`:
8 tests OK (1 skipped: `DOOM_GS_FULL`), 20 s; with `DOOM_GS_FULL=1` the
checkpoint and arithmetic classes in 30 s.

**`build/` growth**: 26 MB (`build/native/game/teleport`: the image and
its objects, the 22 bases with their run base, the three whole-RAM bases,
the synthetic calls, `report.json`); every temporary directory deleted.

## 4. Open points

- (Wave 2 as integrated) `lnTele` takes the thing in `GA_4-5` and the side in `GA_6` (0 front, 1 back: upstream's `SW_CSIDE`) besides the line (`lines.md` request 3). Done: `EV_Teleport` takes the same places.
- (Wave 3 as integrated) `tmthing`, `tmx`, `tmy` and setBox's box are GW's `GM_TMTHING`, `GM_TMX`, `GM_TMY`, `GM_TMBBOX` (`checkpos.md` R1); `setBoxL` has no native code: `P_TeleportMove` FCALLs `setBox` (`checkpos.md` R4). Done.
- The captured calls of the generated streams (GAME.md 2.4): none yet
  (G1, the only stream made, takes no teleporter; G6, E1M5 at medium, is
  aimed at them, 3.7). Until then every case is synthetic.
- Branches no call takes: `blockRange`'s "no block" (a destination's box
  off the map: none in E1); `P_TeleportMove` with boss set blocked (a
  boss always telefrags); `EV_Teleport`'s missile test through a crossing
  (`P_CrossSpecialLine` returns before it for E1's three missiles: the
  test runs only in the calls of `EV_Teleport` alone); a destination that
  is a zone mobj or found after the first tagged sector (one destination
  a map, in the first sector of its tag).
- R4: until the core's `gp_secnodes` leaves `tmx`, `tmy`, the stand-in in
  `stompThing` mirrors it for the teleport only.
- The sounds of a telefrag's death (`A_Scream` and the like, other parts'
  actions) are counted in each run (`other_sounds`), not compared: R6.
- The time of a teleport in routine mode (14-48 ms on `f121`) is mostly
  the destination's walk over the thinkers with a `mo_get` of each mobj
  (upstream's order) and the paging (R2); it is cold (no survey run
  teleports): a timing report item (GAME.md 5.4).

## 5. The integration of wave 4 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 4 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 the helpers inlined | **Accepted**: `glayout.INLINED['teleport']` as written |
| R2 one group | **Accepted**: `gplace.AFFINITY`; the eight routines are group 17, slot 1 (1,824 B with the missile spawn's routines) |
| R3 `OWN_STACK` 5 | **Accepted**: `glayout.OWN_STACK['p_map65.s:P_TeleportMove'] = 5`; `--stack` 80 of 160 B |
| R4 `gp_secnodes` leaves tmx, tmy | **Accepted**: `gpos.s` `gp_secnodes` copies the thing's `TH_X`..`TH_Y + 3` to `GM_TMX`..`GM_TMY + 3` at its start (11 B, the tic phase only: `.ifndef LOADIMG`); `stompThing`'s 84 B stand-in and `TP_SSEC`, `TP_SHEAD` are gone (the scratch block 27 of 32 B). The test module passes, and with `DOOM_GS_FULL=1` every synthetic call on both profiles (the dropper sequences included) is equal |
| R5 the interfaces | **Accepted**: README "The parts' interfaces" (`EV_Teleport`, `lnTele`, `P_TeleportMove`, `stompThing`, and the core's `P_CreateSecNodeList`) |
