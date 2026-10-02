# Part `sight` (wave 1)

The record of milestone 10's part `sight` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 1; upstream 2738 B, native budget 3600 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 1's `sight` (built 2026-10-01, on a2vm against ref816; nothing committed).
- Files: `src/native/game/sight/*.s`, `src/native/game/sight/part.mk`, `src/native/game/sight/args.json`, `tests/test_native_game_sight.py`, this file; tools (if any) `tools/native/gparts/sight*.py`; build output `build/native/game/sight/` (`make -s -C src/native -f game.mk part P=sight ROOT=$PWD`).
- Its scratch block: `SB_SIGHT` (32 B in `ggame.inc`; the part needs 106 B: request R1).

The routines (GAME.md 2.4's row):

`p_sight65.s`: `P_CheckSight:138` (`CS_PREV`, REJECT through `RJROW`, the same subsector, the walk of `P_CrossBSPNode` with its waiting children, the hint as a one-seg subsector, the seg and line tests with `validcount`), `zSetup:1061`, `sightSlope:1407`, `interceptFrac:1150`, `opening:985`; helpers `hintOf`, `half`, `qbd`, `nodeDone`, `lineDone`, `pick`, `sameHeight`, `st32`, `shr8V`, `smul48`, `bitTab`

Its checkpoint (GAME.md 2.4): 2,000 calls over the three demos and the coverage runs, by path: REJECT, same subsector, the same pair (`CS_PREV`, with the hit log of 1.8 compared), the hint hit, blocked by a one-sided line, by a two-sided opening, seen; each case also run with an empty hint plane, the answer required equal (fact 3); synthetic: a sight line along a node line (the side test's "on" case), a call whose `CS_PREV` is `$FFFE` with a pair of the same slots as before it (no hit)

Its planted bugs (each must fail the named check): `CS_PREV` not kept (`validcount`); `$FFFE` matching a slot (the hit log); the far child walked first (stamps); the side test on 32-bit differences, not the 16-bit whole parts with their wrap [R `p_sight65.s:620-650`] (synthetic); `sightSlope`'s reciprocal of the 32-bit distance; REJECT's bit order

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_sight65.s:P_CheckSight` | `P_CheckSight` | demo3 10287, demo1 31587, demo2 22261, newgame 288, tour 2059 |
| `p_sight65.s:zSetup` | `zSetup` | demo3 1084, demo1 1007, demo2 822, newgame 21, tour 148 |
| `p_sight65.s:sightSlope` | `sightSlope` | demo3 3031, demo1 2329, demo2 1946, newgame 105, tour 369 |
| `p_sight65.s:interceptFrac` | `interceptFrac` | demo3 1930, demo1 1607, demo2 1313, newgame 81, tour 281 |
| `p_sight65.s:opening` | `p_sight_opening` | demo3 3135, demo1 5061, demo2 5460, newgame 105, tour 461 |

Helpers: `p_sight65.s:hintOf`, `p_sight65.s:half`, `p_sight65.s:qbd`, `p_sight65.s:nodeDone`, `p_sight65.s:lineDone`, `p_sight65.s:pick`, `p_sight65.s:sameHeight`, `p_sight65.s:st32`, `p_sight65.s:shr8V`, `p_sight65.s:smul48`, `p_sight65.s:bitTab`, `p_sight65.s:straceDone`.


What the part built: `src/native/game/sight/sight.s` (`P_CheckSight`
with the walk, the side tests and the stand-ins of R2; in test builds
`sg_timed` and `sg_bulk`, the harness's entries), `sfrac.s` (`zSetup`,
`sightSlope`, `interceptFrac`, `p_sight_opening`, `smul48`), `sight.inc`
(the scratch block's fields), `part.mk`, `args.json`;
`tools/native/gparts/sight.py` (the path logs, the selection, the
captures, the synthetic cases, the routine runs, the random checks, the
paging measure, the report); `tests/test_native_game_sight.py`. The
native interfaces: `P_CheckSight` takes t1 in `GA_0-1` and t2 in `GA_2-3`
(mobj slots) and answers in A (1 seen, 0 not; Z from A); the four inner
entries take and leave their values in the scratch block (`sight.inc`),
`sightSlope` its height in `GA_0-3` and its result in `M_R`; they are
called by `P_CheckSight` only, as upstream's.

The helpers `half`, `qbd`, `hintOf`, `nodeDone`, `lineDone`, `straceDone`,
`pick`, `sameHeight`, `st32`, `shr8V` and `bitTab` have no native label of
their own: they are folded into the routines that use them (the walk's
side passes are its control flow, `half` and `qbd` the magnitudes of
`sg_side`, `hintOf` the slot itself, `pick` and `sameHeight` the opening's
and the walk's compares, `bitTab` a table inside `P_CheckSight`'s code).

## 2. Requests

**R1. The scratch block: 106 bytes** (`glayout.SCRATCH_REQUESTS['sight'] =
106`). Why: `P_CheckSight` keeps upstream's near state of `p_sight65.s`
across its calls (the object API, the math, its own routines in other
groups): t1, t2, `los` (strace 16, t2x/t2y 8, sightzstart and the two
slopes 12), the box of the line of sight (8), the opening (8), the
fraction, sightblocker, TWOBLOCKER, the seg, its line, the segs left,
`CS_Z`, the seg's sectors and their cache lines, S before the walk, the
divline's pointer (`sight.inc`: 78 B), and a 28-byte union for the side
test's operands and products, `zSetup`'s CS_T, `sightSlope`'s whole part
and `interceptFrac`'s work. Local stand-in: `SG = SB_SIGHT` with 106 bytes
(`sight.inc`), which runs past the 32 bytes into the default blocks of
`tracel` and `damage` (wave 2, linked in no wave-1 image). **This must be
applied before wave 2 links**: `PTR_ShootTraverse` (`tracel`'s traversal)
→ `P_DamageMobj` (`damage`) → a barrel's `A_Explode` → `P_RadiusAttack` →
`P_CheckSight` can run with both those parts' blocks live. Effect: with
every other part at 32 B the blocks take 1,002 of 1,024 bytes, no overlay
needed; every block after `sight`'s moves 74 bytes (no source names an
address).

**R2. Three reads and a write of the object API** (`gobj.s`): `hn_get` /
`hn_put` (A:X a mobj slot: its hint, `MOBJP` `HINTL`/`HINTH`), `rj_row` (A
a sector: its `RJROW` word, `LVS`), `rj_byte` (A:X an offset: the byte of
REJECT at `G_REJECTAT` + it, `LVG2`). Why: `P_CheckSight` needs them
(docs/GAME.md 1.6, 1.8) and the API has none; parts may not call
`far_get`/`far_put`. Local stand-in: `sg_hint_get`, `sg_hint_put`,
`sg_rjrow`, `sg_rjbyte` in `sight.s` (section "LOCAL STAND-INS"), by
`far_get`/`far_put` of those three banks, none a cached kind's (the grep
check's rule holds). Effect: about 90 B in `gobj.s`; no other part
changes; the stand-ins then go.

**R3. `grun.Image` loads the math's RamWorks tables** (banks `MT_TBANK`
120: sines, tantoangle, the quarter sine; `MT_RLO` 121, `MT_RHI` 122: the
reciprocals), as `render_check.image_records` does. Why, with the case:
`build/native/game/sight/cases/demo3/P_CheckSight/h00000469.case.z` (a
call that sees, through two-sided lines) answered 0 from the $A5 machine
and 1 from the $5A machine (ref816: 1): `sightSlope`'s `recipsmall` read
the poison of bank 121/122. Local stand-in: `sight.py` `math_tables()`
appends the tables to every image it runs. Effect: every part whose
routines reach `recip`, `recipsmall`, `approxdiv`, `finesine`,
`finecosine`, `pta3` or the quarter sine (`look`, `chase`, `attack`,
`xymove`, `player`, `missile`, `wfire`, `teleport` ...) gets fill-dependent
answers without it; the skeleton's S2 routines never reach them.

**R4. `gameroutine.py`**: the `args.json` additions this part uses (a
destination or output `sb:FIELD`, a field of the part's scratch block,
resolved from the part's include; `zp:M_R`, `M_A`, `M_B`; the conversions
`as: line` and `as: sector`, an upstream pointer to its object's number),
the stray-write check (a2vm's write log on the complement of the allowed
places: `sight.py` `write_ranges()`), the timing of the call alone (the
cost phase around it: `sg_timed`), the math tables of R3, and a case
directory per part (`gamecap.CASES` is a module global the part's tool
points at its own directory, so that two parts never write one run's
`base.ram.z`). Local stand-in: all of it in `tools/native/gparts/sight.py`.
Effect: the integrator's rerun of every checkpoint can use one harness.

**R5. The placement: `P_CheckSight`, `zSetup`, `sightSlope`,
`interceptFrac`, `opening` and `smul48` in one image, the core.** Why:
sight is 40.4% of the game's instructions [GAME.md 0.3 fact 7]; today
`P_CheckSight` is in group 13 (slot 1), `opening`, `interceptFrac` in group
20 and `zSetup`, `sightSlope` in group 22 (both slot 2), `smul48` in the
core. Every crossed two-sided line pages slot 2 up to six times
(`fc_call`'s restore). Measured on every 10th case (`paging.json`): a call
that sees makes 5 group loads at the median, 21 at most; 203,071 cycles at
the median against 52,473 for those with no load; a hint hit 0 loads at
the median, 7 at most. And group 13 cannot hold it: `P_CheckSight` alone
is 2,137 B in the release (2,422 in test builds), and group 13 also
holds thirteen routines of other parts (2,042 B estimated for the group in
all): it passes slot 1's 2,560 B when they are built. The part's release bytes are 3,361 (sizes below). Effect: core
room 3,361 B (the core had 4,489 B free after the skeleton). The folded
helpers' placement entries (`half`, `qbd`, ... `bitTab`, `straceDone`)
name no native code and can go.

**R6. The stack**: the walk keeps its waiting children on the stack, 2
bytes a level over a 2-byte marker: E1's trees are at most 19 nodes deep
(E1M5, E1M7, E1M8), so up to 40 bytes inside `P_CheckSight` beyond its
calls (`zSetup` etc. via `fc_call`, 5 B each, then `mo_get`, `umul16`).
`gcallgraph.py --stack` should count `P_CheckSight`'s own 40 bytes. The
lowest S measured over all runs: $C9 (201), from the driver's $EF (38
bytes below the driver's frame, `sg_timed` and the walk included).

No new exclusion is asked: routine mode needed R1-R6 only.

## 3. Results

All on a2vm against ref816, 2026-10-01 (`build/native/game/sight/
report.json`; `check.json` and `results/` the runs; `random.json`,
`paging.json`).

**Selection and captures** (GAME.md 2.4 minimums; the path logs
`paths/RUN.json.z` of the five survey runs, 66,482 calls of
`P_CheckSight`): 2,000 calls of `P_CheckSight` over demo3, DEMO1, DEMO2,
newgame and the tour, by path from the call logs: the same pair 377,
REJECT 377, the same subsector 114 (all there are), blocked 377 + 377
(one- and two-sided), seen 377; on the captured cases the exact classes:
the same pair 377, REJECT 377, the same subsector 114, the hint hit 702,
blocked by a one-sided line 34, by a two-sided opening 19, seen 377 (the
hint hit is a blocked call whose blocker is t1's hint). `zSetup` 300,
`sightSlope` 301 (the one call with fraction 0 added), `interceptFrac`
301 (num 0, the wide divisor and the negative quotient added), `opening`
300 (both orders of the ceilings and of the floors). Every call is
eligible (the part reaches no dispatch target).

**Synthetic cases** (36, run on ref816 by `--call` from captured calls):
`on-node` (4: t1 and t2 on the root's partition line, the side test's
"on"), `stale1`/`stale2` (4 each: a same-pair call with `CS_PREV1`, or
both, pointing at no object, `$FFFE` natively: no hit), `wrap` (16: no
hint, t1 and t2 at +-32,000 on one axis: the whole parts' 16-bit wrap),
`frac-den0`, `frac-big` (4 each: `interceptFrac`'s den >> 12 = 0 and its
quotient of $10000 or more, which no run takes).

**The checkpoint** (both machines: $A5 under `f121`, $5A under
`fastpath`; canonical state with R1-R6 only, the declared outputs, the hit
log, `GT_HINT`, the write log):

| Entry | Cases | Runs | Failed | Stray writes | f121 median / worst | fastpath median / worst |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `P_CheckSight` | 2,028 (28 synthetic) | 4,056 | 0 | 0 | 12,489 cyc, 294 us / 3,718,048 cyc, 83.4 ms | 203 us / 61.7 ms |
| `zSetup` | 300 | 600 | 0 | 0 | 16,167 cyc, 348 us / 16,231 | 248 us / 248 us |
| `sightSlope` | 301 | 602 | 0 | 0 | 11,200 cyc, 229 us / 11,523 | 173 us / 177 us |
| `interceptFrac` | 309 (8 synthetic) | 618 | 0 | 0 | 21,486 cyc, 421 us / 22,017 | 331 us / 340 us |
| `opening` | 300 | 600 | 0 | 0 | 18,791 cyc, 385 us / 18,845 | 287 us / 287 us |

The hint-free answer (fact 3): every `P_CheckSight` case run once more
with the hint planes empty and t1's sightline 0: 2,028 runs, every answer
equal. The hit log: every same-pair case logs (tic, t1, t2) once, no other
case logs. The worst `P_CheckSight` times are the synthetic `wrap` cases
(walks of the whole map); over the captured calls alone: f121 median 294
us, p99 15.5 ms, worst 30.8 ms; fastpath 203 us, 11.3 ms, 22.7 ms. The
inner entries' times include one group load each (`sg_timed` calls them
through `FCALL`). The paging (R5) is most of the walks' time: see R5.

**Random checks** (`--random`: upstream's helper on ref816 by
`build/native/math/mathref batch`, the native one on a2vm by `sg_bulk`):
`smul48` 100,000 inputs (the edges included), 0 different (and every
upstream result the exact 48-bit product); the magnitude (upstream's
`half` of 2 |v|, the operand of its products, against `sg_mag`) every
nonzero 16-bit v (65,535; 0 never reaches `half`: the signs answer
first), 0 different; the side test (upstream's `sideTest`, its log fast
path then the products, against the exact signed products of `sg_side`)
100,000 inputs (the edges, random 16-bit values, small ones, pairs whose
products are within a few units; node and line-of-sight divlines; 6,249
with an operand of -32768), 0 different.

**The decision on the log fast path** (GAME.md 1.6): the exact signed
product gives upstream's answer on every captured call (the checkpoint:
2,000 calls and the 36 synthetic ones, stamps and answers equal) and on
all 100,000 random inputs, those with |Q| = 32768 included, since
`LOGTAB`'s entry 0 (the index of 32768 after the shift) holds 30,720 =
log2(32768) x 2048. The bound argues the same: the four log entries are
each within 1/2 and K at most 15 low, so a decision at |M| >= 18 is never
wrong. The native never reads `LOGTAB`: **banks 123-124 can be freed**
(the integrator's change to `llayout.LOGTAB` and `MEMORY_MAP.md`).

**Sizes** (the part's modules in its test image, `grun.module_sizes`):
`sight.s` 2,422 B, `sfrac.s` 1,224 B, of which 285 B test-only
(`sg_timed`, `sg_bulk`): **3,361 B in the release against the budget of
3,600** (upstream 2,738). Groups in the part's image: 13 (slot 1) 2,422
B, 20 (slot 2) 755 B, 22 (slot 2) 306 B, the core 163 B (`smul48`).

**Planted bugs** (the test file, each in a scratch copy of the part's
sources in a deleted temporary directory, on 10-16 cases the tree's image
passes): `CS_PREV` not kept (caught by the canonical `CS_PREV1/2` on the
walking cases; the next call of the pair would walk and raise
validcount); `$FFFE` matching a slot (the hit log: the stale cases hit);
the far child walked first (the lines' stamps: 10 of 10 calls blocked by
a line of the tree); the side test on the 32-bit differences' sign, not
the 16-bit whole parts with their wrap (the `wrap` cases: 14 of 16);
`sightSlope` with the 32-bit distance (its result on the sightSlope
cases); REJECT's bit order reversed (the REJECT cases).

**Runs and commands**:

    make -s -C src/native -f game.mk part P=sight ROOT=$PWD
    python3 tools/native/gparts/sight.py --paths          # 5 runs, ~40 s
    python3 tools/native/gparts/sight.py --capture        # ~30 min at 2 jobs
    python3 tools/native/gparts/sight.py --synthetic
    python3 tools/native/gparts/sight.py --check          # ~40 min at 2 jobs, resumable
    python3 tools/native/gparts/sight.py --random         # ~10 s
    python3 tools/native/gparts/sight.py --paging --report
    python3 -m unittest tests.test_native_game_sight      # 17 tests, ~4 min

The test file runs every 20th `P_CheckSight` case and every 15th of the
others, every synthetic case, the random checks in full and the six
planted bugs: 17 tests OK (220 s at 2 jobs).

`build/` growth: `build/native/game/sight/` 117 MB (the cases 94 MB, the
results 13 MB, the check's JSON 2.3 MB, the synthetic cases 0.8 MB, the
image 1 MB); every temporary directory deleted.

## 4. Open points

- `hl_add` (ghook.s) logs each same-pair hit for the tic comparison; the
  reference's same-pair hits a tic are in `shared/tic/RUN.json.z`. The
  part calls it on every hit in test builds (checked in routine mode).
- R1 must be applied before wave 2 links (above).
- The time of a walk is the paging's and the far fetches': R5 is the
  lever; the far fetches (a seg and its line a seg, a node a node: the
  misses, 30-680 a call) are the object API's (GAME.md 6, risk 1).
- `GT_HINT` is raised by a walk whose t1 is a zone mobj (the hint and the
  sightline are read and written then); no captured call has a zone t1
  (the demos' pools are not full), so it is checked as 0 on every case
  only: the generated stream G1 (zone mobjs from the first shot) will
  show it at the tic level.
- `mobj.sightline` of a one-sided blocker is taken as upstream takes it,
  unchecked against the map's line count (upstream does the same: a
  spawn clears it).

## 5. The integration of wave 1 (2026-10-01)

| Request | Decision |
| --- | --- |
| R1 106 bytes | **Accepted**: `glayout.SCRATCH_REQUESTS['sight'] = 106`; the blocks take 1,002 of 1,024 B; `sight.inc` asserts `SB_SIGHT_SIZE >= SG_NEED` |
| R2 the API calls | **Accepted**: `gobj.s` `hn_get`, `hn_put` (`API_W`), `rj_row`, `rj_byte` (an offset into REJECT: the API adds `G_REJECTAT`); the stand-ins and the part's far accesses are gone (but the test-only `sg_bulk`'s) |
| R3 the math tables | **Accepted**: `grun.Image` loads them (`grun.math_table_records`); `sight.py`'s `math_tables()` adds none |
| R4 the harness | **Accepted in part** (as geom's R5) |
| R5 sight in the core | **Accepted**: `gplace.PINNED`: `P_CheckSight`, `zSetup`, `sightSlope`, `interceptFrac`, `opening`, `smul48` first in the core (3,195 B). To make the room, every part's test-only code moved to the card's driver area (segment `DRIVER`, `FC_HERE .set 0`): `sg_timed` and `sg_bulk` there (`sg_bulk` asserts `P_CheckSight` in the core: it calls `sg_mag`, `sg_side`) |
| R6 the stack | **Accepted**: `glayout.OWN_STACK` (`P_CheckSight` 40 B) counted by `gcallgraph.py --stack` |
| LOGTAB | Not freed yet: the native never reads it, but freeing banks 123-124 changes milestone 9's store and disk; left for the milestone's bank report (GAME.md 5.5) |

Rerun at the integration (`sight.py --check --jobs 2`, `--random`, `--paging --report`): 6,476 runs, 0 failed, 0 stray writes, the hint-free answer on all 2,028 `P_CheckSight` cases; random checks 0 different; with sight in the core a call that sees takes 134,459 cycles at the median (203,071 before) and no group load; the test module 17 tests OK. Size 3,180 B.
