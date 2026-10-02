# Part `movers` (wave 6)

The record of milestone 10's part `movers` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 6; upstream 1094 B, native budget 1400 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 6's `movers` (2026-10-02), under the owner's
  lean checks of 2026-10-02 (at most 40 calls a routine, one poisoned
  machine `$A5`, at most 3 planted bugs, the test under 60 s).
- Files: `src/native/game/movers/*.s`, `src/native/game/movers/part.mk`, `src/native/game/movers/args.json`, `tests/test_native_game_movers.py`, this file; tools (if any) `tools/native/gparts/movers*.py`; build output `build/native/game/movers/` (`make -s -C src/native -f game.mk part P=movers ROOT=$PWD`).
- Its scratch block: `SB_MOVERS` (32 B, `ggame.inc`; 19 used).

The routines (GAME.md 2.4's row):

`p_doors65.s`: `T_VerticalDoor:55` (up, down, waiting, closing on a thing and back, the light tag `partLight:244`); `p_plats65.s`: `T_PlatRaise:39`; helpers `sectorArg`, `doorSound`, `moveCeiling`, `dlSec`, `mulExt`, `movePlat`, `stopWait`, `waitStatus`, `setStatus`

Its checkpoint (GAME.md 2.4): Every thinker call of the door and plat kinds (newgame's door, the demos'); synthetic: a door closing on a monster, a plat waiting with a thing on it

Its planted bugs (each must fail the named check): the door's wait not `VDOORWAIT`; the plat's status changed before the sound; the reversal without its sound

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_doors65.s:T_VerticalDoor` | `T_VerticalDoor` | demo3 796, demo1 1785, demo2 345, newgame 116, tour 0 |
| `p_doors65.s:partLight` | `partLight` | demo3 346, demo1 539, demo2 195, newgame 35, tour 0 |
| `p_plats65.s:T_PlatRaise` | `T_PlatRaise` | demo3 914, demo1 161, demo2 624, newgame 0, tour 0 |

Helpers: `p_plats65.s:movePlat`, `p_plats65.s:stopWait`, `p_plats65.s:waitStatus`, `p_plats65.s:setStatus`, `p_doors65.s:doorSound`, `p_doors65.s:moveCeiling`, `p_doors65.s:dlSec`, `p_doors65.s:mulExt`.

### 1.1 What was built

| File | What |
| --- | --- |
| `src/native/game/movers/movers.s` | The part's routines, a GPL-2 derivative of upstream's `p_doors65.s` and `p_plats65.s`: `T_VerticalDoor` (`THTAB` 6: waiting, down, up, done), `partLight` (with upstream's `lightPartway`, `EV_LightTurnOnPartway`, which is its tail: the level clamped to 0..`FRACUNIT`, each sector of the door line's tag through `P_FindSectorFromLineTag`, its neighbours through part `secfind`'s `nextSector`, the light by two `mulExt` products), `mulExt` (a routine of its own: the random check calls it), `T_PlatRaise` (`THTAB` 5: waiting, up, down, remove). The other helpers are done in place: `moveCeiling` and `movePlat` are the local `dr_move`, `pl_move`; `stopWait`, `waitStatus`, `setStatus` the local `pl_stop`, `pl_wait`, `pl_status`; `doorSound` (and evworld's `platSound`) the macro `SECSOUND`; `dlSec` and evworld's `doorArg`, `platArg`, `sectorArg`, `setDir` the macro `THINKER`, the handle `SB_TH`, `SB_SEC`, `SB_I` and the local `dr_setdir` |
| `src/native/game/movers/mvtest.s` | Test builds of the part's own image only (`MV_TEST=1`, as teleport's `tptest.s`): `mv_bulk`, `mulExt` on many inputs (driver area) |
| `src/native/game/movers/part.mk`, `args.json` | The fragment; the entries' inputs (the thinker's handle in `GA_0-1` from `_Dp[0-3]`; partLight's door in A:X from `DR_DOOR`); no outputs (none of the three returns a value) |
| `tools/native/gparts/movers.py` | The lean checkpoint: `--log` (one ref816 call log a run: `callFn`, the thinkers with `jumps=1`, `partLight` and what they call; each call's path from its callees and upstream's own sound events, no memory kept), `--capture` (40 calls an entry: one of each path the logs show, then spread evenly; the thinkers' at `callFn`, each case checked to enter its thinker at its tic: `choice.json`), `--synthetic` (13 ref816 `--call` cases with pokes), `--check`, `--random`, `--plants`, `report.json`. It uses part `secfind`'s machinery (`Ref`, `Prep`, `Native`, `sounds`), part `mobjstate`'s stray rule and thinker-list checks and part `sight`'s `mathref` batch, as part `planes` does |
| `tests/test_native_game_movers.py` | The build within budget, `args.json` against the image, `THTAB`'s two entries, the far-access grep, a sample of the checkpoint (one captured call of each path of each entry and every synthetic case, `$A5`, `f121`), `mulExt` on 10,000 inputs, the three planted bugs (37 s); `DOOM_GS_FULL=1` adds the whole checkpoint and 100,000 inputs |

### 1.2 The native interfaces

| Routine | In | Out |
| --- | --- | --- |
| `T_VerticalDoor` (`THTAB` 6), `T_PlatRaise` (`THTAB` 5) | `GA_0-1` the thinker's handle (upstream's `_Dp[0-3]`) | nothing |
| `partLight` | A:X the door's handle (upstream's `DR_DOOR`) | nothing |
| `mulExt` | `M_A` a 32-bit value, A:X a word (A low; sign extended) | `M_R` the product's low 32 bits (upstream's X:C = `_Dp[0-3]` × C); changes what `mul32` changes |

Every routine changes `GA_*`, `GT_*`, `GC_*`, the object API's lines and
temporaries, the math block, and whatever `T_MovePlaneCeiling`,
`T_MovePlaneFloor` (part `planes`), `P_RemoveThinker` (part `mobjstate`),
`P_FindSectorFromLineTag` and `nextSector` (part `secfind`) change. Two
bytes are on the stack under the plane movers' calls (the return of the
local `dr_move`, `pl_move`: request 3).

**Differences in form, not in result.** A door's direction is a byte (0,
1, `$FF`), as upstream's; the 16-bit type, status, count and countdown are
compared as words. A sector's light is its render byte: upstream's 16-bit
signed compares of two lights are unsigned byte compares, and the light
it stores, the high word of `level × bright + (FRACUNIT − level) × min`
with level in 0..`FRACUNIT` and both lights in 0..255, is at most 255.
`ceilingdata`, `floordata` are special handles (`$FFFF` none). The sounds
are the hook's `S_StartSound2` with X the sector and Y `$80`, in
upstream's order. Arithmetic: `mulExt` (GAME.md 2.4's list) is
`mul32` of the sign-extended word; `FixedApproxDiv` is milestone 6's
`approxdiv`.

## 2. Requests

Each with what, why (the evidence) and its effect on other parts. The part
needs no stand-in.

### Request 1: the helpers done in place (`INLINED`)

**What.** In `tools/native/glayout.py`, `INLINED`, an entry for the part:

    # wave 6 as integrated: the movers' plane-move loaders, status stores
    # and sector sounds are local code of the thinker that calls them
    # (movers.md request 1)
    'movers': ('p_plats65.s:movePlat', 'p_plats65.s:stopWait',
               'p_plats65.s:waitStatus', 'p_plats65.s:setStatus',
               'p_doors65.s:doorSound', 'p_doors65.s:moveCeiling',
               'p_doors65.s:dlSec'),

**Why.** They load upstream's direct page and store a field or two
[R `p_doors65.s:181-241`, `:423-428`; `p_plats65.s:174-234`]; `movers.s`
does each in place (1.1), so no label of theirs is placed; today's
placement gives them bytes and groups (`gplace.inc`: `movePlat`,
`moveCeiling`, `dlSec` group 1; `stopWait`, `waitStatus`, `setStatus`,
`doorSound` group 26). `mulExt` stays a routine (the random check calls
it).

**Effect on other parts.** None: no other part calls them. The
placement's estimates lose their bytes.

### Request 2: the movers in one group, apart from the planes' unit
(`AFFINITY`, `APART`)

**What.** In `tools/native/gplace.py`, `AFFINITY`, after wave 5's
entries:

    # the door and plat thinkers with the door's light (movers.md
    # request 2): partLight runs at every door move, mulExt in it
    ('p_doors65.s:T_VerticalDoor', 'p_doors65.s:partLight',
     'p_doors65.s:mulExt', 'p_plats65.s:T_PlatRaise'),

and in `APART`, the pair

    ('p_doors65.s:T_VerticalDoor', 'p_floor65.s:T_MovePlaneCeiling'),

**Why.** The test placement scatters the part over three groups
(`T_VerticalDoor` and `mulExt` group 1, slot 2; `partLight` group 6, slot
1; `T_PlatRaise` group 26, slot 2), so a moving door pages the door's
group, the planes' (group 25, slot 1) and then `partLight`'s (slot 1
again: the planes' group is restored after it), every tic it moves. The
four are 1,240 B (section 3), one group. GAME.md 4.3 puts `planes` with
`movers`, but the planes' unit is 1,228 B (`planes.md` 3), so the two do
not fit one 2,048 B group; in opposite slots each moving door or plat tic
loads at most the two groups, once each. Measured in routine mode with
every slot empty at the call (an upper bound): a moving door 1.8 ms at
the median on `f121`, a waiting one (no plane move) far less.

**Effect on other parts.** None on results. `planes`' unit keeps its
group; it gets a slot opposite the movers' group.

### Request 3: the stack under the plane movers (`OWN_STACK`)

**What.** In `tools/native/glayout.py`, `OWN_STACK`:

    # wave 6: the return address of a local jsr (dr_move, pl_move) under
    # the plane movers and partLight (movers.md request 3)
    'p_doors65.s:T_VerticalDoor': 2, 'p_plats65.s:T_PlatRaise': 2,

**Why.** `T_VerticalDoor` calls `T_MovePlaneCeiling` and `partLight`
through its local `dr_move`, `T_PlatRaise` `T_MovePlaneFloor` through
`pl_move` (as trymove's R2). The other local subroutines call only the
object API and the hooks, which keep their own bytes; `partLight` and
`mulExt` keep none.

**Effect on other parts.** `gcallgraph.py --stack` counts 2 B more on
chains through the thinkers (64 + 24 = 88 of 160 B today; the thinkers'
chains are not the deepest).

### Request 4: GAME.md 2.4's row and 4.3

**What.** In `docs/GAME.md` 2.4, row `movers`: after "the light tag
`partLight:244`" add "(no door of the demos has one: synthetic,
`docs/game-parts/movers.md` 3)"; in 4.3's table, slot 2's "`planes` with
`movers`" becomes "`planes`; `movers` (apart: `movers.md` request 2)".

**Why.** Section 3: every `partLight` call of the survey's runs has a
light tag of 0; the two units do not fit one group (request 2).

**Effect on other parts.** None (a document's text).

## 3. Results

The lean checkpoint (2026-10-02, the part's image: waves 1-5 integrated
and `movers`, the test placement; fill `$A5`, profiles `f121` and
`fastpath`, routine mode with R1-R6 only; the sector sound events (R6)
compared with upstream's own from the call log, and for the synthetic
cases with the model of `movers.expected_sounds`, which agrees with the
log on all 120 captured cases; part mobjstate's thinker-list checks and
stray rule with the parts' scratch blocks):

    python3 tools/native/gparts/movers.py --log          # 4 runs, 32 s
    python3 tools/native/gparts/movers.py --capture      # 120 cases, 1.8 min
    python3 tools/native/gparts/movers.py --synthetic    # 13 calls on ref816, 3 s
    python3 tools/native/gparts/movers.py --check --jobs 2   # 1.3 min
    python3 tools/native/gparts/movers.py --random       # 100,000 inputs, 2 s
    python3 tools/native/gparts/movers.py --plants       # 10 s
    python3 -m unittest tests.test_native_game_movers    # 37 s (DOOM_GS_FULL=1: + about 1.5 min)

**266 runs, 0 failures, 0 stray writes, the lowest S `$C5` (197).**

| Entry | Calls in the survey (all eligible) | Cases run: captured + synthetic | Runs | Failed | f121 median / worst (µs) | fastpath median / worst (µs) | Lowest S |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: |
| `T_VerticalDoor` | 3,042 | 40 + 3 | 86 | 0 | 1,787 / 11,670 | 1,354 / 8,775 | 197 |
| `partLight` | 1,115 | 40 + 3 | 86 | 0 | 26 / 17,389 | 18 / 12,504 | 223 |
| `T_PlatRaise` | 1,699 | 40 + 7 | 94 | 0 | 82 / 11,259 | 61 / 8,338 | 197 |

The times are from the routine's entry to its return in routine mode,
with every slot empty at the call (the group loads of request 2
included: an upper bound); `report.json` gives the fabric clocks. No
call of the survey reaches a dispatch target, so every call is eligible.
The call logs count every call of the survey (the log is checked against
the survey's counts, run by run).

**The paths** (the call logs' paths of every call; the choice takes the
first call of each, then calls spread evenly):

- `T_VerticalDoor`, captured, every path of the logs (12): waiting; the
  wait ending (normal: down, the close sound); down a step with and
  without things; down to the floor (normal: done, the thinker removed);
  **down onto a thing, crushed, up again with the open sound** (demo1,
  gametic 1,330: the door closing on a thing and back); up a step with
  and without things; up to the top (normal: waits `VDOORWAIT`) with and
  without things; up to the top and done (open-stay) with and without
  things. Synthetic: a door closing on a monster (a too-tall thing in its
  sector: crushed, up, the open sound); a `close30ThenOpen` door (no E1
  line makes one) at its wait's end (up, the open sound) and at its
  bottom (waits 1,050 tics).
- `partLight`, captured: every call of the survey's runs has a light tag
  of 0 (no door of the demos has one: 1 path). Synthetic: a light tag on
  a line with a sector's tag (demo3's E1M7: sector 23, light 176) at
  the level below 0 (128: the lowest), between (191) and above `FRACUNIT`
  (255: the brightest), each clamped and stored as upstream.
- `T_PlatRaise`, captured, every path of the logs (11): waiting; the wait
  ending (the start sound); down a step with and without things; down to
  the bottom (waits, the stop sound) with and without; up a step with and
  without things, and with the stone sound (a raise plat, demo1); up to
  the top (waits, the stop sound, done) with and without things.
  Synthetic: a plat waiting with a thing on it, its count ending (down),
  going on, and ending at its bottom (up); a plat rising onto a too-tall
  thing (crushed: down, the start sound); a raise plat reaching its top on
  the stone sound's tic (the stone sound, then the stop sound), off it,
  and crushed on it.
- **Not reached**: a door direction other than 0, 1, `$FF` and a plat
  status other than 0-2 (upstream returns: nothing makes them); a door
  type other than the three at its wait's end or bottom; a
  `close30ThenOpen` door reaching its top; `partLight` with a light tag and
  no height (top = floor: it returns); a raise plat going down to its
  bottom (raise plats only go up).

**mulExt's random check** (GAME.md 2.4 "Arithmetic"): 100,000 inputs (the
208 pairs of 16 32-bit and 13 16-bit edges, then uniform, partLight's
ranges and powers of two with offsets), upstream's `mulExt` on ref816
(`mathref` batch on a captured case's machine) against the native
(`mv_bulk`): **0 different**; upstream's equals the product's low 32 bits
on all of them.

**Sizes** (`movers.o` in the part's image): **1,240 of 1,400 B** (upstream
1,094): `T_VerticalDoor` 399 (with its local `dr_done`, `dr_setdir`,
`dr_move`) and `mulExt` 19 (group 1), `partLight` 393 (group 6),
`T_PlatRaise` 429 (group 26). Scratch block 19 of 32 B. `mvtest.s` 125 B
in the driver's area, the part's own image only.

**The planted bugs** (each in a scratch copy under `build/tmp-*`,
deleted; `movers.py --plants`):

| Plant | Check | Caught |
| --- | --- | --- |
| `door-wait`: the door's wait at its top 105 (the plat's 3 s), not `VDOORWAIT` | the captured normal doors reaching their top | 2 of 2 runs fail (`door.topcountdown` 150 against 105) |
| `status-first`: the plat's status changed (with its start or stop sound) before the stone sound | the synthetic raise plats on the stone sound's tic | 2 of 2 runs fail (the stop sound before the stone sound) |
| `reversal-silent`: the door's reversal on a thing without its open sound | demo1's door closing on a thing and the synthetic monster | 2 of 2 runs fail (no sound event, upstream's open sound expected) |

**build/ growth**: 42 MB (`build/native/game/movers/`: the cases and the
four runs' bases 41 MB, the logs' summaries, the image); every temporary
directory deleted. Nothing outside the part's directory written.

## 4. Open points

- The paths not reached (section 3).
- No door of the survey's runs has a light tag: `partLight`'s light work
  is checked on three synthetic cases only.
- The mobj sound events of callees (a thing removed by `changeSector`) are
  not compared in routine mode (R6); none was seen
  (`report.json` `mobj_sound_events` 0).
- Requests 1-3 are for the integrator; until request 2 a moving door pages
  up to three groups a tic (section 3's times are an upper bound).
- (Wave 3 as integrated) `p_doors65.s:sectorArg` and `p_plats65.s:sectorArg` have no native code (`glayout.INLINED['evworld']`, `evworld.md` request 1): `T_VerticalDoor` and `T_PlatRaise` take the special's `SP_SECTOR` byte in place.
- (Wave 4 as integrated) `T_MovePlaneFloor`, `T_MovePlaneCeiling` (part `planes`): `GA_0` the sector, `GA_2-5` speed, `GA_6-9` dest, `GA_10` the direction (`$FF` down, 1 up); A = `UC_OK`, `UC_CRUSHED`, `UC_PASTDEST` (`planes.md` 1.2). The six routines of `planes` are one `gplace.AFFINITY` unit (`planes.md` request 2: group 23, slot 2, 2,012 B with other routines); joining it is `movers`' request. Upstream has no crush damage (`planes.md` 1.2, request 3).

## 5. The integration of wave 6 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 6 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| 1 `INLINED['movers']` | **Accepted** as written |
| 2 the placement | **Accepted in part.** The unit in `gplace.AFFINITY` as written: group 9 (slot 1, 1,981 B in all). The `APART` pair (`T_VerticalDoor`, `T_MovePlaneCeiling`) as written: the planes' unit is group 26, slot 2. The integrator first tried, in its place, a rule that kept the thinkers' walk apart from every `THTAB` thinker. That rule cannot hold with this pair: `T_MoveFloor`, in the planes' unit, is a thinker too. It also raised the model's cost to 9.4 ms a tic, so the pair stays. Instead the walk's unit takes the light thinkers (`tic.md` R4 as integrated). In the final placement (with the plant margins, GAME.md "Wave 6 as integrated") the walk is group 21, slot 1, the movers' slot: a moving door loads its group, then the planes' (slot 2, if another group is there), then the walk's group again on return. That is three loads at most, the same count either way |
| 3 `OWN_STACK` | **Accepted** as written (`gcallgraph.py --stack`: 64 + 24 = 88 of 160 B, unchanged: the thinkers' chains are not the deepest) |
| 4 GAME.md 2.4 and 4.3 | **Accepted** as written |

Sizes in the wave image: `movers.o` 1,234 of 1,400 B. The test module
(default mode): 10 tests, 1 skipped (`DOOM_GS_FULL`), OK.
