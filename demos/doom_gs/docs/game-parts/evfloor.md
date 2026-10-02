# Part `evfloor` (wave 4)

The record of milestone 10's part `evfloor` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 4; upstream 1159 B, native budget 1500 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 4's `evfloor` (2026-10-02), under the owner's
  lean checks of 2026-10-02 (at most 40 calls a routine, one poisoned
  machine `$A5`, at most 3 planted bugs, the test under 60 s).
- Files: `src/native/game/evfloor/*.s`, `src/native/game/evfloor/part.mk`, `src/native/game/evfloor/args.json`, `tests/test_native_game_evfloor.py`, this file; tools (if any) `tools/native/gparts/evfloor*.py`; build output `build/native/game/evfloor/` (`make -s -C src/native -f game.mk part P=evfloor ROOT=$PWD`).
- Its scratch block: `SB_EVFLOOR` (32 B, `ggame.inc`; 23 used).

The routines (GAME.md 2.4's row):

`p_floor65.s`: `EV_DoFloor:815` (each type E1's lines use), `EV_BuildStairs:1057` (the steps by texture and tag), `EV_DoDonut:1233`, `newFloor:922`; helpers `lineStart`, `nextTagged`, `secOf`, `secArg2`, `floorField`, `floorDown`, `floorUp`, `floorArgFL`, `setDest`, `sameAsFloor`, `underCeiling`, `stairStep`, `nextStep`, `lineSector`, `sectorNum`, `s2Arg`, `s3Arg`, `s3Floor`, `halfSpeed`

Its checkpoint (GAME.md 2.4): The few captured calls; synthetic: every floor, stairs and donut special on every line of the nine maps that has it, by `--call`

Its planted bugs (each must fail the named check): stairs following the other side; the donut's outer floor height; the turbo speed; the destination from the next highest instead of the lowest

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_floor65.s:EV_DoFloor` | `EV_DoFloor` | demo3 3, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_floor65.s:EV_BuildStairs` | `EV_BuildStairs` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_floor65.s:EV_DoDonut` | `EV_DoDonut` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_floor65.s:newFloor` | `newFloor` | demo3 2, demo1 0, demo2 0, newgame 0, tour 0 |

Helpers: `p_floor65.s:lineStart`, `p_floor65.s:nextTagged`, `p_floor65.s:secOf`, `p_floor65.s:secArg2`, `p_floor65.s:floorField`, `p_floor65.s:floorDown`, `p_floor65.s:floorUp`, `p_floor65.s:floorArgFL`, `p_floor65.s:setDest`, `p_floor65.s:sameAsFloor`, `p_floor65.s:underCeiling`, `p_floor65.s:stairStep`, `p_floor65.s:nextStep`, `p_floor65.s:lineSector`, `p_floor65.s:sectorNum`, `p_floor65.s:s2Arg`, `p_floor65.s:s3Arg`, `p_floor65.s:s3Floor`, `p_floor65.s:halfSpeed`, `p_switch65.s:lnFloor`, `p_switch65.s:lnStairs`, `p_switch65.s:lnDonut`.

### 1.1 What was built

| File | What |
| --- | --- |
| `src/native/game/evfloor/evfloor.s` | The part's routines, a GPL-2 derivative of upstream's `p_floor65.s` (`EV_DoFloor`, `newFloor`, `EV_BuildStairs`, `EV_DoDonut`) and `p_switch65.s` (`lnFloor`, `lnStairs`, `lnDonut`: `LSTAB`'s entries 4-6). Five helpers are routines of their own (the placement's units): `floorUp` (upstream's `floorUp` and `floorDown`, the direction in A), `setDest`, `halfSpeed`, `stairStep`, `nextStep`. The others are done in place: `lineStart` and `nextTagged` (the macro `NEXTTAGGED`), `floorArgFL` (`FLOOR`), `s3Floor` (`S3FLOOR`), `floorField`, `secArg2`, `s2Arg`, `s3Arg`, `sameAsFloor` and `underCeiling` (`EV_DoFloor`'s turbo and raise branches); `secOf`, `lineSector` and `sectorNum` are a sector's number and a line's front and back sector bytes (no arithmetic) |
| `src/native/game/evfloor/part.mk`, `args.json` | The fragment; the entries' inputs and outputs (secfind's forms; `newFloor` takes `FL_SEC` "as" a sector and C, and gives `FL_FLOOR` "as" a floor; the synthetic calls through `P_UseSpecialLine` and `P_CrossSpecialLine` use lines' declarations) |
| `tools/native/gparts/evfloor.py` | The lean checkpoint: the captures (`--capture`: every survey call, 5, and the tour's in-play bases), the synthetic calls on the nine maps (`--synthetic`), the runs (`--check`), the planted bugs (`--plants`), `report.json`. It imports part `secfind`'s machinery (`Ref`, `Prep`, `Native`, `sounds`), part `lines`' (`outputs`, `path_of`, `find_special`, `switch_place`), part `mobjstate`'s thinker-list checks and part `evworld`'s stray rule (with the sides), bases and `ref_call` |
| `tests/test_native_game_evfloor.py` | The build within budget, `args.json` against the image, `LSTAB`'s three entries, the far-access grep, the whole checkpoint under `f121`, the three planted bugs (25 s); `DOOM_GS_FULL=1` adds `fastpath` |

### 1.2 The native interfaces (what the later parts call)

| Routine | In | Out |
| --- | --- | --- |
| `EV_DoFloor` | A:X the line, Y the floor type (`UC_LOWERFLOOR` .. `UC_RAISEFLOORTONEAREST`; upstream's `_Dp[0-3]` and C) | A = 1 when a floor started, else 0 |
| `EV_BuildStairs`, `EV_DoDonut` | A:X the line | A = 1 when a stair, a donut started, else 0 |
| `newFloor` | A the sector, Y the type (upstream's `FL_SEC` and C) | A:X the floor's handle (upstream's `FL_FLOOR`) |
| `floorUp` | A the direction (1, `$FF`); `SB_FL` the floor, `SB_SEC` its sector | |
| `setDest`, `halfSpeed` | `GA_0-3` the height; `SB_FL` | |
| `stairStep`, `nextStep` | `SB_SEC`, `SB_H`, `SB_TX` | nextStep: A = 1 a step made (`SB_SEC` it), 0 none |
| `lnFloor` (`LSTAB` 4) | README's convention: `GA_0-1` the line, `GA_2` spectab's argument (the type) | A = `EV_DoFloor`'s result |
| `lnStairs`, `lnDonut` (`LSTAB` 5, 6) | `GA_0-1` the line | A = the routine's result |

Every routine changes `GA_*`, `GT_*`, `GC_*` (the core's temporaries:
`gt_spectake`, `gt_add`, `sp_store`), the object API's lines and the
scratch block `SB_EVFLOOR`.

**The floor as made** (llayout's `SP_KIND['floor']`, `ZONE0`), for part
`planes` (`T_MoveFloor`, wave 4) and the bridge: function `FN_FLOOR`, the
thinker links, the type (high byte 0); then `floorUp` (upstream's
`floorUp`, `floorDown`): its sector, the direction (1 or `$FF`), speed
`FRACUNIT`; turboLower speed `4 × FRACUNIT`, a step `FRACUNIT / 4`, both
halves of a donut `FRACUNIT / 2`; the destination; the donut's rising pool
the model's floorpic as its texture (high byte 0). The rest 0 (upstream's
`Z_CallocLevSpec`). A type past the table (no E1 line has one) gets only
the function, the links, the type and the sector's `floordata`: its sector
stays none (`$FF`, upstream's NULL), as upstream's. After `newFloor` and
before `floorUp` the sector is none too, which the captured `newFloor`
calls compare.

**Differences in form, not in result.** Upstream's 16-bit fields are
native bytes: a line's tag and special, its flags' low byte
(`ML_TWOSIDED`), a sector's number and floorpic. Upstream's `minssec` in
`EV_BuildStairs` stays -1, so its test never holds and has no code; the
outer tag index (upstream's `FL_SECNUM`, pushed around a stair) is `SB_SN`,
which `nextStep` leaves alone (its step is `SB_SEC`, a sector's number).
Arithmetic: none of 2.4's "Arithmetic" list (`IIGS_MulLo16` of a sector's
or side's address, `_Div16` in `sectorNum`: the native number). The
turboLower `+ 8 × FRACUNIT` and the stairs' `+ 8` are 16-bit adds on the
high word, as upstream's.

## 2. Requests

Each with what, why (the evidence) and its effect on other parts. The part
goes on with its own code meanwhile; none needs a stand-in.

### Request 1: the helpers with no code of their own (`INLINED`)

**What.** In `tools/native/glayout.py`, `INLINED`, after the `'evworld'`
entry:

    'evfloor': ('p_floor65.s:lineStart', 'p_floor65.s:nextTagged',
                'p_floor65.s:secOf', 'p_floor65.s:secArg2',
                'p_floor65.s:floorField', 'p_floor65.s:floorDown',
                'p_floor65.s:floorArgFL', 'p_floor65.s:sameAsFloor',
                'p_floor65.s:underCeiling', 'p_floor65.s:lineSector',
                'p_floor65.s:sectorNum', 'p_floor65.s:s2Arg',
                'p_floor65.s:s3Arg', 'p_floor65.s:s3Floor'),

**Why.** They are argument loaders, field stores and compares of
upstream's direct page [R `p_floor65.s:875-920`, `:949-1050`, `:1194-1231`,
`:1349-1368`]: `evfloor.s` does each in place (1.1), and `floorDown` is
`floorUp` with A = `$FF`, so no label of theirs exists while the
placement gives them bytes and groups today (`gplace.inc`:
`GP_floorDown_G = 5`, ...).

**Effect on other parts.** None: no other part calls them (they are the
helpers of this part's routines; `planes` has its own, `floorArg`,
`floorSector`, `secArg`).

### Request 2: the part's routines in one group (`AFFINITY`)

**What.** In `tools/native/gplace.py`, `AFFINITY`, after the wave 3
entries:

    # the floors, stairs and donut a line starts (evfloor.md request 2):
    # each handler with its routine, the helper routines with them
    ('p_switch65.s:lnFloor', 'p_floor65.s:EV_DoFloor',
     'p_floor65.s:newFloor', 'p_floor65.s:floorUp', 'p_floor65.s:setDest',
     'p_floor65.s:halfSpeed', 'p_switch65.s:lnStairs',
     'p_floor65.s:EV_BuildStairs', 'p_floor65.s:stairStep',
     'p_floor65.s:nextStep', 'p_switch65.s:lnDonut',
     'p_floor65.s:EV_DoDonut'),

**Why.** The test placement puts the three `EV_` routines in group 4 and
`newFloor`, the helper routines and the handlers in group 5, so every
floor made crosses groups (`fc_call` from group 4 to 5: `newFloor`,
`floorUp`, `setDest` for each floor of `EV_DoFloor`, ten for a donut,
`stairStep` and each `nextStep` of a stair: 16 for the 14-step one). The twelve are 1,180 B (section 3), which fits a
group; GAME.md 4.3 already names `evfloor` as one slot 2 group.

**Effect on other parts.** None on results. The neighbours are `lines`'
group (the dispatch) and secfind's finders' group
(`P_FindSectorFromLineTag`, `P_Find*`), which the `EV_` routines call once
a tagged sector; `gplace.py`'s rule 3 picks the slots.

### Request 3: lines' sound events of the floor handlers (lines' request 5)

**What.** `tools/native/gparts/lines.py`, `expected_sounds`: after the
evworld branch (`if row[1] in ('p_switch65.s:lnVDoor', ...)`), before the
`raise PartError(...)`:

        if row[1] in ('p_switch65.s:lnFloor', 'p_switch65.s:lnStairs',
                      'p_switch65.s:lnDonut'):
            # part evfloor's handlers (evfloor.md request 3): the floors
            # make no sound; the switch's after a started handler
            import evfloor
            GC.CASES = CASES    # (evfloor's first import points it at its own)
            return evfloor.expected_sounds(prep)

**Why.** `lines.md` request 5: the calls of `P_UseSpecialLine` and
`P_CrossSpecialLine` that reach `lnFloor`, `lnStairs`, `lnDonut` become
eligible with this part. Upstream's `EV_DoFloor`, `EV_BuildStairs` and
`EV_DoDonut` start no sound (the floors' sounds are `T_MoveFloor`'s
[R `p_floor65.s:578-645`]); `P_UseSpecialLine`'s switch (mode 1) or button
(mode 2) sounds after a handler that started (lines' rule). The model
(`evfloor.py` `expected_sounds`: a handler started when it made a floor)
agrees with the native events on all 62 runs through the lines of
section 3.

**Effect on other parts.** `lines`' checkpoint can run its waiting cases
of these three handlers. A capture that logs upstream's own
`S_StartSound*` (lines' request 5 as written) stays the better answer.

### Request 4: the README's interfaces table

**What.** In `src/native/game/README.md`, "The parts' interfaces", after
the `evworld` row:

    | `EV_DoFloor`, `EV_BuildStairs`, `EV_DoDonut`, `newFloor` (`evfloor`) and `LSTAB`'s `lnFloor`, `lnStairs`, `lnDonut` | `evfloor.md` 1.2 "The native interfaces" (the floor as made: for `planes`' `T_MoveFloor`) | |

**Why.** The later parts' builders (`planes`, `movers`) read the table.

**Effect on other parts.** None.

## 3. Results

The lean checkpoint (2026-10-02, the part's image: waves 1-3 integrated
and `evfloor`, the test placement; fill `$A5`, profiles `f121` and
`fastpath`, routine mode with R1-R6 only; the declared outputs, the sound
events and mobjstate's thinker-list checks compared; evworld's stray rule:
mobjstate's places, the parts' scratch blocks, the sides a switch
changes):

    python3 tools/native/gparts/evfloor.py --capture     # 27 cases, 28 s
    python3 tools/native/gparts/evfloor.py --synthetic   # 35 calls on ref816, 5 s
    python3 tools/native/gparts/evfloor.py --check --jobs 2      # 19 s
    python3 tools/native/gparts/evfloor.py --plants              # 9 s
    python3 -m unittest tests.test_native_game_evfloor   # 25 s (DOOM_GS_FULL=1: + fastpath)

**80 runs, 0 failures, 0 stray writes, the lowest S `$CF` (207).**

| Entry | Calls in the survey (all eligible) | Cases run: captured + synthetic | Runs | Failed | f121 median / worst | fastpath median / worst | Lowest S |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: |
| `EV_DoFloor` | 3 | 3 + 4 | 14 | 0 | 895,163 / 1,405,982 | 608,300 / 979,728 | 221 |
| `EV_BuildStairs` | 0 | (through the lines) | | | | | |
| `EV_DoDonut` | 0 | (through the lines) | | | | | |
| `newFloor` | 2 | 2 + 0 | 4 | 0 | 11,016 / 11,016 | 8,477 / 8,477 | 226 |
| `P_UseSpecialLine` (to `lnFloor`, `lnStairs`, `lnDonut`) | (synthetic) | 0 + 13 | 26 | 0 | 1,418,875 / 2,877,944 | 1,013,000 / 2,101,722 | 207 |
| `P_CrossSpecialLine` (to `lnFloor`, `lnStairs`) | (synthetic) | 0 + 18 | 36 | 0 | 1,286,782 / 2,676,797 | 916,116 / 1,918,671 | 207 |
| of which `lnFloor` | | 25 | 50 | 0 | 1,286,782 / 2,051,500 | 916,116 / 1,485,141 | 211 |
| of which `lnStairs` | | 4 | 8 | 0 | 2,676,797 / 2,877,944 | 1,918,671 / 2,101,722 | 207 |
| of which `lnDonut` | | 2 | 4 | 0 | 2,273,915 | 1,635,145 | 211 |

The times are fabric clocks from the routine's entry to its return
(`report.json` gives µs too: `EV_DoFloor` 6.7 / 10.5 ms on `f121`), in
routine mode with every slot empty at the call (group loads included: an
upper bound). The cost is the tag scan (`P_FindSectorFromLineTag`, a
`sec_get` a sector) and the finders' paging; a use of the 14-step stair
takes 21.6 ms (`f121`). Request 2 and the placement are the levers.

The branches taken (fill `$A5`, `f121`):

- `EV_DoFloor` captured (demo3): turboLower one floor, raiseFloor one
  floor, raiseFloor with its sector busy (none made). Synthetic, by
  `--call` of `EV_DoFloor` itself: lowerFloor (type 0, which no E1 line
  uses), a type past the table (7: the bare floor, its sector none),
  turboLower on a sector whose highest floor next to it is its own (no
  `+ 8`), raiseFloor on one whose lowest ceiling next to it is above its
  own (the dest clamped to the ceiling); `newFloor`: both captured calls.
- Through `P_UseSpecialLine` and `P_CrossSpecialLine` (`usetab`,
  `crosstab`), the player, one line of each (map, special, tag) on the nine
  maps (20 lines): floors 5, 91 (raiseFloor), 18 (raiseFloorToNearest), 23
  and 82 (lowerFloorToLowest), 36, 70 and 98 (turboLower, with the `+ 8`),
  one to three floors a line; the stairs 8 (E1M3: 10 steps) and 7 (E1M8:
  14 steps); the donut 9 (E1M2: the pool and the pillar); the first line
  of each special used again on the state the first use left, its special
  put back (every handler with its tagged floors busy: none made, no
  switch sound).
- **Not reached**: `EV_DoDonut`'s pool none (the pillar's first line
  one-sided), its pool busy, and a pool with no model line (every back
  side of the pool the pillar); `EV_BuildStairs`' next step whose floor
  moves already (the second stairs use stops at the first step's busy
  floor); a monster at a floor line (lines' `monster-not-a-door`: no
  handler call). The lean cut leaves out the fill `$5A` and the other
  lines of each (map, special, tag), which have the same effect (a handler
  reads only the line's tag); no line was cut by the 40-call limit.

Planted bugs (`evfloor.py --plants`, each from a scratch copy in a deleted
temporary directory, fill `$A5`, `f121`):

| Bug | Check | Caught |
| --- | --- | --- |
| the stairs following the other side (`nextStep`: the step is the line's back sector, the next its front) | stairs: the two stair lines' first uses | 2 of 2 runs fail (`floor: identities [1, ..., 8] only in a, [] only in b`) |
| the donut's outer floor height (`S3FLOOR` from the pool `SB_S2`, not the model) | donut: the donut line's first use | 1 of 1 run fails (`floor[0].dest: 8388608 != 6815744`) |
| the turbo speed (`FLOORSPEED`, not 4 ×) | turbo: the turboLower lines' first uses (36, 70, 98) | 8 of 8 runs fail (`floor[0].speed: 262144 != 65536`) |

GAME.md 2.4's fourth, "the destination from the next highest instead of
the lowest", is not planted (the lean rules: at most 3); the captured and
synthetic calls of lowerFloorToLowest (23, 82) and raiseFloorToNearest
(18) compare every floor's destination.

Sizes (`evfloor.py`'s `sizes()`, the part's image): **1,180 B of 1,500**
(upstream 1,159): `EV_DoFloor` 304, `EV_BuildStairs` 112, `EV_DoDonut` 334
(group 4); `newFloor` 108, `floorUp` 31, `setDest` 26, `halfSpeed` 23,
`stairStep` 56, `nextStep` 151, `lnFloor` 13, `lnStairs` 11, `lnDonut` 11
(group 5). `make -f game.mk sizes` was not run (its `skel` prerequisite
rebuilds the skeleton's shared image).

Other checks: the build has no warning; `gcallgraph.py --check --built`
(waves 1-3 and `evfloor`) 935 heads, 0 failures; `--stack` 56 + 24 = 80 of
160 B; `gameroutine.grep_check` on `evfloor.s`: clean.

`build/` growth: `build/native/game/evfloor/` 26.4 MB (27 cases with the
tour's bases, the 35 synthetic calls, the image); every temporary
directory deleted.

## 4. Open points

- (Wave 2 as integrated) An `LSTAB` handler takes the line in `GA_0-1` and spectab's argument in `GA_2-3` (`lines.md` request 3: the thing in `GA_4-5`, unused here). Done: `lnFloor` reads `GA_0-2`, `lnStairs` and `lnDonut` `GA_0-1`.
- `floorUp` and `EV_DoDonut` keep one byte on the stack across `sp_get` (an object API call, a leaf: `pha` ... `pla`), as evworld's `EV_DoPlat` does; no `OWN_STACK` entry is asked for.
- The lean cut (section 3): the fill `$5A`, the other lines of each (map, special, tag) and the fourth planted bug are left to the final integration if it wants them.
- The sound model (request 3) is from the reference's states, not from upstream's events; a capture that logs `S_StartSound*` (lines' request 5) would replace it.
- `EV_DoFloor`'s, `EV_BuildStairs`' and `EV_DoDonut`'s cost is the tag scan and the finders' paging (section 3): for the timing report (5.4).

## 5. The integration of wave 4 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 4 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| 1 the helpers inlined | **Accepted**: `glayout.INLINED['evfloor']` as written |
| 2 one group | **Accepted**: `gplace.AFFINITY`; the twelve routines are group 11, slot 1 (2,030 B with other routines) |
| 3 lines' sound events of the floor handlers | **Accepted**: `lines.py` `expected_sounds` calls `evfloor.expected_sounds` for `lnFloor`, `lnStairs`, `lnDonut` |
| 4 the README's interfaces | **Accepted**: the row as written |
