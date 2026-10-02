# Part `planes` (wave 4)

The record of milestone 10's part `planes` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 4; upstream 1222 B, native budget 1600 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 4's `planes` (2026-10-02), under the owner's
  lean checks of 2026-10-02 (at most 40 calls a routine, one poisoned
  machine `$A5`, at most 3 planted bugs, the test under 60 s).
- Files: `src/native/game/planes/*.s`, `src/native/game/planes/part.mk`, `src/native/game/planes/args.json`, `tests/test_native_game_planes.py`, this file; tools (if any) `tools/native/gparts/planes*.py`; build output `build/native/game/planes/` (`make -s -C src/native -f game.mk part P=planes ROOT=$PWD`).
- Its scratch block: `SB_PLANES` (32 B, `ggame.inc`; 29 used).

The routines (GAME.md 2.4's row):

`p_floor65.s`: `T_MovePlaneFloor:90`, `T_MovePlaneCeiling:142` (crush, the restore on a block), `checkSector:330` and `changeSector:395` (`P_ChangeSector` over the sector's touching things with `visited`: `heightClip:450` = `P_ThingHeightClip` through `P_CheckPosition`, corpses to gibs, items removed, crush damage every 4 tics with `P_Random` blood), `T_MoveFloor:578`; helpers `restore`, `planeArgs`, `minusSpeed`, `plusSpeed`, `saveLast`, `setPlaneT`, `secArg`, `loadNode`, `nodeArg`, `thingArg`, `floorArg`, `floorSector`, `floorSpeed`, `sectorSound`

Its checkpoint (GAME.md 2.4): Every captured `T_MoveFloor` and plane move (the doors' through synthetic door states until `movers`); synthetic: a door closing on a monster, a crushing ceiling over a corpse and over an item

Its planted bugs (each must fail the named check): things visited by the sector list, not the node list; crush damage every tic; the move not undone when blocked; `visited` not reset

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_floor65.s:T_MovePlaneFloor` | `T_MovePlaneFloor` | demo3 526, demo1 161, demo2 204, newgame 0, tour 0 |
| `p_floor65.s:T_MovePlaneCeiling` | `T_MovePlaneCeiling` | demo3 346, demo1 539, demo2 195, newgame 35, tour 0 |
| `p_floor65.s:checkSector` | `checkSector` | demo3 872, demo1 700, demo2 399, newgame 35, tour 0 |
| `p_floor65.s:changeSector` | `changeSector` | demo3 590, demo1 48, demo2 280, newgame 0, tour 0 |
| `p_floor65.s:heightClip` | `heightClip` | demo3 590, demo1 48, demo2 280, newgame 0, tour 0 |
| `p_floor65.s:T_MoveFloor` | `T_MoveFloor` | demo3 242, demo1 0, demo2 0, newgame 0, tour 0 |

Helpers: `p_floor65.s:restore`, `p_floor65.s:planeArgs`, `p_floor65.s:minusSpeed`, `p_floor65.s:plusSpeed`, `p_floor65.s:saveLast`, `p_floor65.s:setPlaneT`, `p_floor65.s:secArg`, `p_floor65.s:loadNode`, `p_floor65.s:nodeArg`, `p_floor65.s:thingArg`, `p_floor65.s:floorArg`, `p_floor65.s:floorSector`, `p_floor65.s:floorSpeed`, `p_floor65.s:sectorSound`.

### 1.1 What was built

| File | What |
| --- | --- |
| `src/native/game/planes/planes.s` | The part's routines, a GPL-2 derivative of upstream's `p_floor65.s`: `T_MovePlaneFloor`, `T_MovePlaneCeiling` (upstream's `toDest`, `crushStep`, `okay` are their local `mp_todest`, `mp_crush`, `mp_step`/`mp_okay`), `checkSector` (`P_CheckSector`), `changeSector` (`PIT_ChangeSector`), `heightClip` (`P_ThingHeightClip`), `T_MoveFloor` (`THTAB`'s floor entry, 7). Every helper is done in place: `restore` is `mp_restore`; `planeArgs` `plane_args`; `minusSpeed`, `plusSpeed` `minus_speed`, `plus_speed`; `saveLast` and `setPlaneT` `mp_set` and `set_plane`; `loadNode`, `nodeArg` `cs_head`, `cs_next` (local subroutines of the routine that uses them); `secArg`, `floorSector`, `sectorSound` the macros `SECTOR`, `SECSOUND`; `thingArg`, `floorArg`, `floorSpeed` the handles kept in the scratch block (`SB_TH`, `SB_HT`, `SB_FL`) and read in place |
| `src/native/game/planes/part.mk`, `args.json` | The fragment; the entries' inputs and outputs (secfind's forms, and the part's own `sb:NAME`, a byte of the scratch block, for `changeSector`'s `NOFIT` in and out) |
| `tools/native/gparts/planes.py` | The lean checkpoint: `--log` (callFn's hits that enter `T_MoveFloor`, as secfind's thinker logs), `--capture` (a pool of 120 calls an entry, spread evenly over the survey's runs; `T_MoveFloor`'s at `callFn`, each case checked to enter it at the logged tic; then the choice: one call of each path the pool takes, then calls spread evenly, 40 an entry: `choice.json`), `--synthetic` (ref816 `--call` of chosen calls with pokes: 19 cases), `--check`, `--plants`, `report.json`. It imports part `secfind`'s machinery (`Ref`, `Prep`, `Native`, `sounds`) and part `mobjstate`'s stray rule and thinker-list checks |
| `tests/test_native_game_planes.py` | The build within budget, `args.json` against the image (the `sb:` names too), `THTAB`'s floor entry, the far-access grep, a sample of the checkpoint (the first chosen call of each entry, every third synthetic case, `$A5`, `f121`), the three planted bugs on every fourth case of their checks (20 s); `DOOM_GS_FULL=1` adds the whole checkpoint (about 2.5 min at 2 jobs) |

### 1.2 The native interfaces (what the later parts call)

| Routine | In | Out |
| --- | --- | --- |
| `T_MovePlaneFloor`, `T_MovePlaneCeiling` | `GA_0` the sector, `GA_2-5` speed, `GA_6-9` dest (fixed_t), `GA_10` the direction (`$FF` down, 1 up, else no move) (upstream's `_Dp[0-3]`, X:C, `_Dp[4-7]`, 4,s) | A = `UC_OK`, `UC_CRUSHED` or `UC_PASTDEST` |
| `checkSector` | A a sector (upstream's `MP_SEC`) | A = nofit (also `SB_NOFIT`) |
| `changeSector` | A:X a thing (a slot; upstream's `_Dp[0-3]`) | `SB_NOFIT` = 1 when it is shootable and does not fit, else unchanged (upstream's `NOFIT`) |
| `heightClip` | A:X a thing | A = 1 fits, 0 not |
| `T_MoveFloor` (`THTAB` 7) | `GA_0-1` the floor thinker's handle | |

Every routine changes `GA_*`, `GT_*`, `GC_*`, the object API's lines and
temporaries, and whatever `P_CheckPosition` (part `checkpos`),
`P_SetMobjState`, `P_RemoveMobj` and `P_RemoveThinker` (part `mobjstate`)
change. Nothing is kept on the stack across a call (no `OWN_STACK`).

For part `movers` (wave 6): `T_VerticalDoor` calls `T_MovePlaneCeiling`
and `T_PlatRaise` calls `T_MovePlaneFloor` with the special's sector byte
in `GA_0`, its speed in `GA_2-5`, the destination in `GA_6-9` and the
direction byte in `GA_10`; the result in A (upstream's `DR_RES`, `PL_RES`
[R `p_doors65.s:217-240`, `p_plats65.s:172-200`]). For part `evfloor`
(wave 4): `EV_DoFloor`, `EV_BuildStairs`, `EV_DoDonut` make the floor
thinkers that `T_MoveFloor` runs: function `FN_FLOOR`, `SPFL_TYPE` (2
bytes), `SPFL_DIRECTION` (1: `$FF` down, 1 up), `SPFL_TEXTURE` (2; its low
byte becomes the pool's floor pic at a donut's end), `SPFL_DEST`,
`SPFL_SPEED` (4 each), `SP_SECTOR`, and the sector's `SG_FLOORD` the handle
(`$FFFF` none, which `T_MoveFloor` writes at the destination).

**Differences in form, not in result.** Upstream's 16-bit sector special
and floor pic are native bytes (the donut's `floorpic = texture` stores the
texture's low byte; every E1 flat number is below 256); the sector is a
byte, the thing a slot, the floor thinker a handle. Upstream's
`CLEARCLEAN` (byte 11 of the mobj) is the kind plane's `KIND_CLEAN` bit,
cleared through `pl_get`/`pl_put` (R3: not compared). Arithmetic: none of
2.4's list (the movers add and subtract fixed_t only; upstream's
`IIGS_MulLo16` of a sector's address is the native number), so no random
check of a helper applies.

**Upstream has no crush damage.** GAME.md 2.4's row says "crush damage
every 4 tics with `P_Random` blood" and plants "crush damage every tic";
upstream's `PIT_ChangeSector` only gibs a corpse, removes a dropped item or
sets `nofit` [R `p_floor65.s:390-437`], with no `P_DamageMobj`, no
`P_Random` and no `leveltime` test (the file's only `leveltime` is
`T_MoveFloor`'s stone sound [R `p_floor65.s:598-602`]), and the movers take
no `crush` argument [R `p_floor65.s:80-86`]. The native follows upstream;
request 3 asks to correct the row, and that plant is not made (section 3).

## 2. Requests

Each with what, why (the evidence) and its effect on other parts. The part
needs no stand-in.

### Request 1: the helpers have no code of their own (`INLINED`)

**What.** In `tools/native/glayout.py`, `INLINED`, an entry for the part:

    'planes': ('p_floor65.s:restore', 'p_floor65.s:planeArgs',
               'p_floor65.s:minusSpeed', 'p_floor65.s:plusSpeed',
               'p_floor65.s:saveLast', 'p_floor65.s:setPlaneT',
               'p_floor65.s:secArg', 'p_floor65.s:loadNode',
               'p_floor65.s:nodeArg', 'p_floor65.s:thingArg',
               'p_floor65.s:floorArg', 'p_floor65.s:floorSector',
               'p_floor65.s:floorSpeed', 'p_floor65.s:sectorSound'),

**Why.** They are upstream's direct-page loaders and four-byte plane
copies [R `p_floor65.s:183-325`, `:375-391`, `:438-443`, `:648-690`]:
`planes.s` does each in place (1.1), as local code of the routine that
uses it, so no label of theirs is placed; today's placement gives them
bytes and groups (`gplace.inc`: `p_floor_secArg` group 10,
`p_floor_thingArg` group 20, ...).

**Effect on other parts.** None: no other part calls them (`evfloor` has
its own `secArg2`, `floorArgFL`, 2.4). The placement's estimates lose the
helpers' bytes.

### Request 2: the part's routines in one group (`AFFINITY`)

**What.** In `tools/native/gplace.py`, `AFFINITY`, after wave 3's entries:

    # the plane movers with the sector check and the floor thinker
    # (planes.md request 2): T_MovePlaneFloor and T_MovePlaneCeiling share
    # their local code (planes.s asserts one group)
    ('p_floor65.s:T_MoveFloor', 'p_floor65.s:T_MovePlaneFloor',
     'p_floor65.s:T_MovePlaneCeiling', 'p_floor65.s:checkSector',
     'p_floor65.s:changeSector', 'p_floor65.s:heightClip'),

**Why.** The test placement scatters them over five groups
(`T_MovePlaneFloor` and `T_MovePlaneCeiling` 10, `checkSector` 20,
`changeSector` 7, `heightClip` 3, `T_MoveFloor` 5), so a moving floor with
a thing on it pages up to five 2 KB groups in one call (`T_MoveFloor` →
`T_MovePlaneFloor` → `checkSector` → `changeSector` → `heightClip` →
`P_CheckPosition`, group 8). Measured (section 3, every slot empty at the
call): `T_MoveFloor` 995,936 fabric clocks at the median on `f121` (7.5
ms), `T_MovePlaneFloor` 858,852, `heightClip` 359,440; `checkSector` on an
empty sector, which pages nothing, 5,481. The six are 1,228 B (section 3),
which fits a group with room for `movers`' `T_VerticalDoor` and
`T_PlatRaise` (1,094 B upstream; GAME.md 4.3: "`planes` with `movers`").
The two movers share their local code (`mp_set`, `mp_restore`, ...):
`planes.s` asserts `GP_T_MovePlaneFloor_G = GP_T_MovePlaneCeiling_G`,
which holds in today's placement (both group 10) and which this entry
keeps. `checkSector` runs at every door, lift and floor step (2,006
calls in the survey's runs).

**Effect on other parts.** None on results. `movers` (wave 6) calls the
movers on every door and plat tic: joining this unit is its request.

### Request 3: GAME.md 2.4's row (no crush damage upstream)

**What.** In `docs/GAME.md` 2.4, row `planes`: replace "corpses to gibs,
items removed, crush damage every 4 tics with `P_Random` blood)" by
"corpses to gibs, dropped items removed, a shootable thing that does not
fit holds the plane; upstream has no crush damage:
`docs/game-parts/planes.md` 1.2)"; and in its planted bugs drop "crush
damage every tic".

**Why.** 1.2: upstream's `PIT_ChangeSector` [R `p_floor65.s:390-437`] has
no damage, no `P_Random` and no `leveltime`; a native crush damage would
break the comparison, and a plant of one cannot be made in code that has
none.

**Effect on other parts.** None (a document's text). `movers`' door
"closing on a thing and back" is `T_MovePlaneCeiling`'s `UC_CRUSHED`
(checked here by synthetic cases).

## 3. Results

The lean checkpoint (2026-10-02, the part's image: waves 1-3 integrated
and `planes`, the test placement; fill `$A5`, profiles `f121` and
`fastpath`, routine mode with R1-R6 only; the declared outputs, the
sector sound events (R6) and mobjstate's thinker-list checks compared;
mobjstate's stray rule with the parts' scratch blocks):

    python3 tools/native/gparts/planes.py --log          # demo3: 242 T_MoveFloor calls of 75,439 callFn calls, 8 s
    python3 tools/native/gparts/planes.py --capture      # 717 pooled cases, 11 min (most of it the paths' decoding)
    python3 tools/native/gparts/planes.py --synthetic    # 19 calls on ref816, 3 s
    python3 tools/native/gparts/planes.py --check --jobs 2   # 2.3 min
    python3 tools/native/gparts/planes.py --plants       # 26 s
    python3 -m unittest tests.test_native_game_planes    # 20 s (DOOM_GS_FULL=1: + about 2.5 min)

**518 runs, 0 failures, 0 stray writes, the lowest S `$B6` (182).**

| Entry | Calls in the survey (all eligible) | Cases run: captured + synthetic | Runs | Failed | f121 median / worst | fastpath median / worst | Lowest S |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: |
| `T_MovePlaneFloor` | 891 | 40 + 6 | 92 | 0 | 858,852 / 4,448,881 | 642,098 / 3,332,566 | 187 |
| `T_MovePlaneCeiling` | 1,115 | 40 + 6 | 92 | 0 | 127,611 / 2,118,493 | 96,872 / 1,595,522 | 187 |
| `checkSector` | 2,006 | 40 + 0 | 80 | 0 | 5,481 / 2,606,435 | 3,851 / 1,962,590 | 194 |
| `changeSector` | 918 | 40 + 3 | 86 | 0 | 652,588 / 1,853,691 | 484,530 / 1,395,995 | 199 |
| `heightClip` | 918 | 40 + 2 | 84 | 0 | 359,440 / 1,427,944 | 262,642 / 1,073,655 | 204 |
| `T_MoveFloor` | 242 | 40 + 2 | 84 | 0 | 995,936 / 4,719,886 | 745,818 / 3,549,746 | 182 |

The times are fabric clocks from the routine's entry to its return
(`report.json` gives µs: `T_MoveFloor` 7.5 / 35.4 ms on `f121`), in
routine mode with every slot empty at the call (the group loads of
request 2 included: an upper bound). No call of the survey reaches a
dispatch target, so every call is eligible.

The paths (planes.py's `path_of`, from the reference's states; the pool
is 120 calls an entry, the choice takes one of each path first):

- `T_MovePlaneFloor` captured: down a step with and without things in the
  sector, down to the destination (pastdest) with and without, up a step
  with and without. Synthetic: up a step on a too-tall monster (crushed,
  the move undone), corpse (gibs, the step kept), dropped item (removed);
  down to the destination on a too-tall monster (pastdest, the move
  undone); down a step on a too-tall monster (no restore on a step down);
  up with the destination above the ceiling (destheight = the ceiling,
  pastdest).
- `T_MovePlaneCeiling` captured: up a step with and without things, up to
  the destination with things, down a step with and without. Synthetic:
  down a step on a too-tall monster (crushed, undone: a door closing on a
  monster), corpse, dropped item; up to the destination on a too-tall
  monster (pastdest, undone); up a step on one (no restore); down with the
  destination below the floor (destheight = the floor).
- `checkSector` captured: no node, 1, 2, 3 or more nodes, things with
  `MF_NOBLOCKMAP` among them; every captured call fits (nofit 1 runs in
  the movers' synthetic cases).
- `changeSector` captured: fits; not fitting and not shootable (1).
  Synthetic: a too-tall monster (nofit), corpse (gibs: `S_GIBS`, not
  solid, no height, no radius), dropped item (`P_RemoveMobj`).
- `heightClip` captured: on the floor, fits, z moved with the floor or not;
  on the floor, not fitting. Synthetic: in the air (a unit above its
  floor), and its top above the ceiling (z = ceilingz - height).
- `T_MoveFloor` captured: down a step, down to the destination (the stop
  sound, floordata none, the thinker removed), up a step, with and without
  the stone sound. Synthetic: up to the destination, plain and as a
  donut's pool (`DONUTRAISE`: the floor pic and the special).
- **Not reached**: a mover called with a direction other than 1 and `$FF`
  (upstream's `okay` with no move: no caller passes one); `checkSector`'s
  restart from the head after a removal with unvisited nodes left after
  it (not checked on purpose: the synthetic removals do not choose their
  neighbours); `heightClip` not fitting in the air.

**Sizes** (`planes.o` in the part's image): **1,228 of 1,600 B** (upstream
1,222): `T_MovePlaneFloor` 64 and `T_MovePlaneCeiling` 369 (with the
movers' shared code), `checkSector` 187, `changeSector` 131, `heightClip`
289, `T_MoveFloor` 188. Scratch block 29 of 32 B.

**The planted bugs** (each in a scratch copy under `build/tmp-*`, deleted;
`planes.py --plants`; the test runs every fourth case of each check):

| Plant | Check | Caught |
| --- | --- | --- |
| `sector-list`: the things visited by the sector's thing list (`SEC_THINGS`, `TH_SNEXT`), not its touching-node list | `checkSector`'s captured calls with things | 17 of 17 runs fail (first differences: the line record and `ceilingline` of other position checks, the nodes' `visited`) |
| `not-undone`: `crushStep`'s move not undone when a thing does not fit | the movers' synthetic cases | 2 of 12 runs fail (the two crushed steps: the plane, `validcount`, the things) |
| `visited-kept`: `visited` not reset before the walk | `checkSector`'s captured calls with things | 13 of 17 runs fail (the things of an earlier check skipped) |

GAME.md 2.4's fourth plant, "crush damage every tic", cannot be made:
upstream has no crush damage (1.2, request 3). The lean rule keeps three.

**Sounds.** The sector sound events (`S_StartSound2`: `T_MoveFloor`'s
stone and stop sounds) are compared with upstream's model of them; the
mobj events of callees (`P_RemoveMobj`'s `S_StopSound` on a removed item,
2 events in the synthetic cases; a pickup's in `P_CheckPosition`, none
seen) are counted in `report.json` (`mobj_sound_events`), not compared.

**build/ growth**: 42 MB (`build/native/game/planes/`: the cases 25 MB
with the four runs' bases, the rest the image and its objects); every
temporary directory deleted. Nothing outside the part's directory
written.

## 4. Open points

- The paths not reached (section 3): a mover with direction 0, a
  `checkSector` restart after a removal with unvisited nodes after it,
  `heightClip` not fitting in the air.
- The mobj sound events of callees are not compared in routine mode (R6):
  the integration's tic-level runs compare every sound event.
- Request 2's single group: until then a moving floor with a thing on it
  pages up to five groups (section 3's times are routine mode with every
  slot empty).
- `T_MovePlaneFloor` and `T_MovePlaneCeiling` must stay in one group
  (`planes.s` asserts it at assembly): request 2 keeps them together; a
  placement that split them would stop the build, not misrun.

## 5. The integration of wave 4 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 4 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| 1 the helpers inlined | **Accepted**: `glayout.INLINED['planes']` as written |
| 2 one group | **Accepted**: `gplace.AFFINITY`; the six routines are group 23, slot 2 (2,012 B with other cold routines), so `planes.s`'s assertion holds; `movers.md` noted (joining the unit is its request) |
| 3 GAME.md 2.4's row | **Accepted**: the row says "dropped items removed, a shootable thing that does not fit holds the plane; upstream has no crush damage", and the planted bug "crush damage every tic" is gone |
