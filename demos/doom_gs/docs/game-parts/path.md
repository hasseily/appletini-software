# Part `path` (wave 4)

The record of milestone 10's part `path` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 4; upstream 1239 B, native budget 1600 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 4's `path` (built 2026-10-02, on a2vm against ref816, under the owner's lean checks of 2026-10-02; nothing committed).
- Files: `src/native/game/path/*.s`, `src/native/game/path/part.mk`, `src/native/game/path/args.json`, `tests/test_native_game_path.py`, this file; tools (if any) `tools/native/gparts/path*.py`; build output `build/native/game/path/` (`make -s -C src/native -f game.mk part P=path ROOT=$PWD`; the checkpoint's image with `PT_TEST=1`).
- Its scratch block: `SB_PATH` (32 B, `ggame.inc`); the part needs 44 B (`path.inc`; request R1).

The routines (GAME.md 2.4's row):

`p_path65.s`: `P_PathTraverse:186`, `ptBody:226` (the block steps, `validcount++`, the early traversal with no guard and its limit `(M - 2) × K` [R `p_path65.s:594-645`]), `traverseTo:772` (`P_TraverseIntercepts`: the nearest first, ties by the list's order), `ptStuck:832` (the no-step case and its copies), `offLine:436`, `axisStep:474`, `early:594`, helpers `fromOrigin`, `a1Shr7`, `callTrav` (the `TRVTAB` dispatch)

Its checkpoint (GAME.md 2.4): Every captured call's endpoints and flags, from the captured state, with the recording traverser (3.5) in both machines, and with a traverser that stops at the k-th intercept (k from 1 to the count); **acceptance 6** (5.2): long dense traces of more than 64 intercepts

Its planted bugs (each must fail the named check): the early limit one block late (stamps, the k-stop runs); ties by the last; more than 64 intercepts handled as the C (none) instead of upstream (acceptance 6); the start not moved off a block line

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_path65.s:P_PathTraverse` | `P_PathTraverse` | demo3 1064, demo1 5380, demo2 5602, newgame 152, tour 4 |
| `p_path65.s:ptBody` | `ptBody` | demo3 272, demo1 591, demo2 242, newgame 10, tour 0 |
| `p_path65.s:traverseTo` | `traverseTo` | demo3 799, demo1 4856, demo2 5372, newgame 142, tour 4 |
| `p_path65.s:ptStuck` | `ptStuck` | demo3 9, demo1 35, demo2 10, newgame 0, tour 0 |
| `p_path65.s:offLine` | `offLine` | demo3 2128, demo1 10760, demo2 11204, newgame 304, tour 8 |
| `p_path65.s:axisStep` | `axisStep` | demo3 2128, demo1 10760, demo2 11204, newgame 304, tour 8 |
| `p_path65.s:early` | `early` | demo3 1573, demo1 4293, demo2 1427, newgame 52, tour 0 |

Helpers: `p_path65.s:fromOrigin`, `p_path65.s:a1Shr7`, `p_path65.s:callTrav`.

What the part built: `src/native/game/path/path.s` (every routine and
helper above but `callTrav`, each a `ROUTINE`; upstream's `traverse`
label, the final traversal, inside `ptBody`), `path.inc` (the walk's
state in the scratch block, the trace's names), `pttest.s` (test builds,
the driver's area, only with `PT_TEST=1`: `pt_bulk`, a1Shr7's random
check; `pt_rec_trv`, the recording traverser's stand-in of R2),
`part.mk`, `args.json`; `tools/native/gparts/path.py` (the selection,
whole-machine captures, the reference's variants with a recording
traverser, upstream's path points by `ref816 --mark`, acceptance 6's
search, the native runs, the random check, the planted builds,
`report.json`); `tests/test_native_game_path.py`.

### The native interfaces (what parts `attack`, `xymove`, `player` call)

| Routine | In | Out | Changes |
| --- | --- | --- | --- |
| `P_PathTraverse` | `GA_0-3` x1, `GA_4-7` y1, `GA_8-11` x2, `GA_12-15` y2 (fixed_t), `GA_16` the flags (`UC_PT_ADDLINES`, `UC_PT_ADDTHINGS`), `GA_17` the traverser (`TRVTAB_<label>`) | A = 1 and C set (true), A = 0 and C clear (false); `GM_TRACE` the trace (x1, y1 moved off a block line, dx, dy), `GM_TRLONG`, the intercepts (`ICPT`, `ICHAIN`, `GM_ICN`, `GM_ICLAST`; a delivered one's frac `$7FFFFFFF`), SIDE1's constants (`sideSetup`) | `GA_*`, `GT_*`, the math, `SB_PATH`, validcount + 1 and the lines' stamps |
| a `TRVTAB` traverser (wave 5's `PTR_*`) | `GA_0` the intercept's index: `ICPT` + 6 × it (frac 4, what 2: a line, or `$8000` + a mobj slot); `GM_TRACE` the trace | C set to go on, C clear to stop (upstream's A not 0 / 0) | anything (the walk's state is in `SB_PATH`, the trace in GW) |

Upstream keeps the caller's `_Dp[8-15]` around a shot's walk for its
traversers [R `p_path65.s:207-224`]: natively a traverser's own state is
its part's scratch block, so `P_PathTraverse` keeps nothing for it.
Upstream's dead guard (`guardL` and the rest) and its state (`G_IDT`,
`PT_OK`; GAME.md 3.5 R4) have no native code: `ptBody`'s `stz G_IDT`
[R `p_path65.s:271`] is not kept (only the guard reads it,
`tracet.md` "The dead guard"). Upstream's `ptPatch` (the flags'
branches `ptL1`-`ptL3` patched in place) is a test of `PT_FLAGS` at the
same three places (`tracet.md` R1, R5).

## 2. Requests

Each: what, why (the evidence), what it changes for other parts. All are
for the integrator; none is applied by the part.

**R1. The scratch block: 44 bytes.** Exact change in
`tools/native/glayout.py`, `SCRATCH_REQUESTS`:

```
SCRATCH_REQUESTS: Dict[str, int] = {        # part -> bytes (requests, 3.8)
    # P_CheckSight's state across its calls (docs/game-parts/sight.md R1)
    'sight': 106,
    # P_PathTraverse's walk across the block steps and the traverser's
    # calls (docs/game-parts/path.md R1)
    'path': 44}
```

Why: the walk's state lives across `traceLines`, `traceThings`,
`P_BlockLinesIterator` and the traverser's calls (any game logic), as
upstream's near scratch of `p_path65.s` does [R `p_path65.s:37-94`]: the
flags and the traverser (2), the ends' blocks (8), xstep, ystep (8),
xintercept, yintercept (8), mapx, mapy and their steps (8), the count,
K, the step's traverser flag, the things' first intercept (5),
`TI_LIM` and `TI_IN` (5): `path.inc`. x1 .. y2 are not kept (the trace
in `GM_TRACE` and the origins give them). Local stand-in: `PT =
SB_PATH` with 44 bytes, running 12 bytes into `SB_TRYMOVE` (part
`trymove`, wave 4, linked in no image of this part; `path.inc`'s
`.assert` allows it only until then). **Apply before wave 4's parts link
together.** Effect: every block after `path`'s moves 12 bytes (`trymove`
.. `chase`); the blocks then end at `$9DF6` of `$9E00`, no overlay
needed.

**R2. `TRVTAB`'s convention, and `gt_record_trv`.** Two defects of the
harness's recording traverser (`src/native/game/grec.s`), found by this
part's acceptance runs: (a) it takes the intercept in A, which `DCALL`
cannot give (`dc_call`'s A is the entry number on a paged target and 0
on a core target such as `gt_record_trv`: every call would record
intercept 0); (b) it makes `ICPT + 6 A` in X (8 bits), so from intercept
42 on it reads another entry's bytes (`6 × 42 = 252`: the `what` of
intercept 42 comes from `ICPT + 0`). Evidence: with a stand-in that took
GA_0 into A for it, 27 acceptance runs (the traces whose `ptStuck`
copies reach 56-64 intercepts) recorded `what` `$FFFF` at intercept 42
where the reference gave `$802D` (`e1m1-p112`); the stand-in below
passes all 150. Exact change in `grec.s`: the header line becomes
"`gt_record_trv   a traverser: GA_0 the intercept (its index in ICPT,
TRVTAB's convention); its 6 bytes (frac, what) appended; the same stop`",
and `gt_record_trv:` up to `; (Y = 6)` becomes:

```
gt_record_trv:
        lda GA_0                ; the intercept (TRVTAB's convention: GA_0;
        asl a                   ;   path.md R2): ICPT + 6 GA_0, 16 bits
        sta GO_I
        asl a
        clc
        adc GO_I
        ldx #>ICPT
        bcc :+
        inx
:       clc
        adc #<ICPT
        bcc :+
        inx
:       sta GO_P
        stx GO_P+1
        ldy #ICPT_SIZE - 1
:       lda (GO_P),y
        sta rec_v,y
        dey
        bpl :-
        ldy #ICPT_SIZE
```

and in `src/native/game/README.md`, the `DCALL` list, after the `ITTAB`
item: "* a `TRVTAB` traverser takes the intercept's index in `GA_0`
(`ICPT` + 6 × it) and returns C set to go on, clear to stop (part
`path`; `path.md` R2);". Local stand-in: `pttest.s`'s `pt_rec_trv` (the
code above, recording through grec's `rec_n`, `rec_stop`), which
`path.py` puts in `TRVTAB`'s harness entry of its image; with R2
`pt_rec_trv` can become `jmp gt_record_trv` and `path.py` keeps working.
Effect: wave 5's traversers (`attack`, `xymove`, `player`) take `GA_0`;
nothing built uses `TRVTAB` yet.

**R3. `callTrav` has no native code.** Exact change in
`tools/native/glayout.py`, `INLINED`, after `'look'`'s entry:

```
    # wave 4 (docs/game-parts/path.md R3): upstream's jml [PT_JMP] is
    # traverseTo's DCALL TRVTAB
    'path': ('p_path65.s:callTrav',),
```

Why: upstream's `callTrav` is `jml [PT_JMP]` [R `p_path65.s:816`];
natively the dispatch is `DCALL TRVTAB` in `traverseTo`. The wave 3
placement gives `callTrav` core bytes (`gplace.py`'s estimate) that no
code uses. Effect: placement only; `test_native_game_path` checks that
`callTrav` has no label.

**R4. The placement: the part as one unit.** Request, in
`tools/native/gplace.py` `AFFINITY`:

```
    # the walk of a trace (path.md R4): the block loop calls early, and
    # early traverseTo, at every block step
    ('p_path65.s:P_PathTraverse', 'p_path65.s:ptBody',
     'p_path65.s:early', 'p_path65.s:traverseTo', 'p_path65.s:offLine',
     'p_path65.s:axisStep', 'p_path65.s:fromOrigin', 'p_path65.s:a1Shr7',
     'p_path65.s:ptStuck'),
```

Why: the estimated placement spreads the part over four groups
(`P_PathTraverse` 18, `ptBody` 25 in slot 2, `early`, `axisStep`,
`offLine`, `fromOrigin`, `ptStuck` 15 and `traverseTo`, `a1Shr7` 20, both
in slot 1), so each block step's `early` (2,486 of the 2,550 block steps
of this part's reference runs call it) loads group 15, and its `traverseTo` group 20 in the same
slot: two loads a step and the restore. Measured sizes: 1,357 B in all
(`report.json`), fits a slot. tracet's block steps (group 24) and tracel's
crossed line are slot 1: slot 2 for this unit avoids loads between them
at every block. Effect: placement only (`gplace.py --measure`).

**R5. The parts' interfaces in `src/native/game/README.md`.** Exact rows
for "The parts' interfaces", after `longTrace`'s:

```
| `P_PathTraverse` (`path`) | `GA_0-3` x1, `GA_4-7` y1, `GA_8-11` x2, `GA_12-15` y2, `GA_16` the flags (`UC_PT_ADDLINES`, `UC_PT_ADDTHINGS`), `GA_17` the traverser (`TRVTAB_<label>`) | A = 1 and C set (true), A = 0 and C clear (false); `GM_TRACE` (x1, y1 moved off a block line), the intercepts (`ICPT`, `ICHAIN`, `GM_ICN`, `GM_ICLAST`) |
| a `TRVTAB` traverser (`attack`, `xymove`, `player`) | `GA_0` the intercept's index (`ICPT` + 6 × it); `GM_TRACE` | C set to go on, clear to stop |
```

Effect: documentation only.

**R6. GAME.md: acceptance 6 as found, and the variants' machines.**
Exact text appended to 5.2's row 6, in its "Checks" cell: " (wave 4,
`path.md` R6: E1's traces of more than 64 intercepts are rare: lines
along a whole map give at most about 50, and a long diagonal walk gets
stuck, its walk's steps being approximate [R `p_path65.s:516-534`],
before it collects more; so the traces are chosen by the reference's own
count, the host model only filtering the candidates: 2,692 candidates on
the nine maps' states, 17 of more than 64 intercepts on seven maps (none
found on E1M1, E1M4), most through `ptStuck`'s copies [R
`p_path65.s:832-883`]; the about 500 of this row stay a full run's
target)". And in `src/native/game/README.md` "Testing a part", a
paragraph: "A variant of a captured call (the reference's routine again
on the case's machine, with pokes: another traverser, a stop) can read
pages the captured call never read, which a case holds only from its
run's base, another moment's machine (wave 4: demo1's `LN36` of an
earlier life, so upstream stamped lines at stale addresses). Such
variants need the whole machine: `tools/native/gparts/path.py`'s
`capture_whole` keeps every page that differs from the base
(`path.md` R6)." Effect: documentation only.

## 3. Results

All on a2vm against ref816, 2026-10-02, at 2 processes; the part's image
links waves 1-3 (integrated) and this part. Under the owner's lean checks
of 2026-10-02: 40 captured calls of `P_PathTraverse`, from the `$A5`
machine only, under `f121` only. `build/native/game/path/report.json`
holds every number below.

**The routine checkpoint** (`path.py --run`): each case, the canonical
state after the call (gcanon's routine mode, exclusions R1-R7 only:
validcount and the lines' stamps among it), the return value (A and C),
the intercepts delivered to the traverser (frac, line or mobj, in order),
the intercepts left (their count, each frac and what, the chain from its
head, `IC_LAST`), the trace's state and SIDE1's constants, no stray write
(a2vm's write log): **372 runs, 0 failed, 0 undecodable, 0 stray
writes**; the lowest S `$CD`.

| Runs | Cases | Runs | Failed | Stray | Cycles median / worst (f121) | µs median / worst |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| as captured (the traverser never runs) | 9 | 9 | 0 | 0 | 744,584 / 980,811 | 15,018 / 19,802 |
| recording traverser, k-stops | 40 | 114 | 0 | 0 | 1,121,109 / 6,738,345 | 22,610 / 136,482 |
| the start on a block line (synthetic) | 3 | 6 | 0 | 0 | 4,976,204 / 5,369,786 | 100,494 / 108,488 |
| acceptance 6 | 25 traces | 150 | 0 | 0 | 6,617,139 / 12,840,322 | 133,606 / 258,673 |

- **The sample** (`path.py --select`): 12,197 calls in the survey, 4,333
  of them eligible as captured (their traverser never runs: every
  intercept is beyond the call's reach). 40 chosen: 8 from the tics of
  `ptStuck`'s calls, 6 from those of `traceLines` (the fast sides), 6
  eligible as captured, 2 of each traverser's kind, the rest spread
  (demo3 4, demo1 23, demo2 13; reached: `PTR_SlideTraverse` 13,
  `PTR_AimTraverse` 7, `PTR_ShootTraverse` 7, `PTR_UseTraverse` 2,
  `PTR_NoWayTraverse` 2).
- **The variants**: every chosen call again on the reference (`ref816
  --call` on its captured machine) with a recording traverser (65816 in
  bank `$7C`) in place of its own, never stopping, then stopping at the
  first, the middle and the last intercept it was given (114 runs); the
  native with `TRVTAB`'s harness entry stopping at the same k. The
  captures keep the whole machine (`capture_whole`, R6): with gamecap's
  pages a variant read demo1's `LN36` from the run's base and stamped
  lines at stale addresses (two undecodable runs), now none.
- **Synthetic**: a chosen shot's call with x1, y1 or both moved onto the
  nearest block line (offLine's `+ FRACUNIT`, which no sampled call and
  no acceptance trace takes: the 8 times the point is reached are these
  runs'), each never stopping and stopping at 1.
- **Acceptance 6** (`path.py --acceptance`): one state a map (the tour's
  `P_PlayerThink` calls, whole machines: E1M1-E1M9); candidates from
  things' places, 1,500-6,000 units long, the host model's count (lines
  crossed, things' diagonals crossed) at least 20, run on the reference
  never stopping; kept when the reference's run returns false (more
  than 64 intercepts: the list full, or `ptStuck`'s copies past it),
  3 a map at most, and a trace of each map whose run takes `ptStuck`'s
  copy: 2,692 candidates, **17 traces of more than 64 intercepts** (E1M2
  2, E1M3 3, E1M5 3, E1M6 1, E1M7 3, E1M8 3, E1M9 2; none found on E1M1
  and E1M4) and 8 of the copy; each with stops 0, 1, 8, 32, 64, 65 on
  both sides: 150 runs, 2,695 intercepts delivered, all equal. Two
  candidates (E1M8) never return on the reference: upstream's `fixedDiv`
  loops (`tracel.md` R4, GAME.md 3.6 T8), not compared. R6 says why the
  model alone finds none: the reference's count chooses.
- **The paths** (`ref816 --mark` at 31 points of `p_path65.s`, summed
  over every reference run; `report.json` `paths`): taken: a shot's kept
  `_Dp`, K, the lines by `traceLines` (lines only and with things) and by
  `P_BlockLinesIterator`, the things, the early traversal (with and
  without a limit, the traverser's false in it), the x and y steps, the
  three `axisStep` cases, `ptStuck` (the traverser ran; nothing to copy;
  the copy; too many: false), `offLine`, the final traversal, a
  delivery, `IC_LAST` back to the head, the traverser's false, the end
  beyond the limit. **Not reached**: the lines' list full (`lines-full`:
  more than 64 crossed lines in one walk, which E1 has not shown) and
  the early limit capped at `FRACUNIT` (`early-cap`: a walk past its last
  block far enough).
- **The inner routines** (`ptBody`, `traverseTo`, `ptStuck`, `offLine`,
  `axisStep`, `early`, `fromOrigin`, `a1Shr7`) were not replayed as
  entries of their own: their upstream interfaces are `p_path65.s`'s near
  scratch, the native ones `path.inc`'s, and every one runs inside the
  checked `P_PathTraverse` calls, whose path points above cover them.
- **The timings are upper bounds**: routine mode with every slot empty at
  the call, the part spread over four groups (R4). No timing study (lean).

**a1Shr7's random check** (`path.py --random`): 100,000 inputs (26 edges:
0, ±1, ±$80, the extremes, the shift's edges; random 32-bit values,
coordinates, powers of 2) through upstream's `a1Shr7` (`mathref batch`
on a captured call's machine, `AX_A` 0) and the native (`pt_bulk`): 0
different.

**The planted bugs** (each in a scratch copy, `path.py`'s `PLANTS`; the
lean rules: three, the likeliest):

| Plant | Check | Caught | The first difference |
| --- | --- | --- | --- |
| the early limit one block late (`(M - 1) K`) | the k-stop runs and acceptance 6 | 104 of 264 | `line[245].validcount` 4,159, upstream 4,157; 6 intercepts, upstream 7 |
| more than 64 intercepts handled as the C (no early traversal) | acceptance 6 | 109 of 150 | intercept 0 not delivered (frac `$00000144`, upstream `$7FFFFFFF`): delivered 0, upstream 7 |
| the start not moved off a block line (`offLine` never adds) | the synthetic starts on a block line | 6 of 6 | the trace's x1, then SIDE1's constants and the fracs |

Not planted (lean): ties taken by the last (the chain's order is
`icInsert`'s, part `tracel`'s, whose plant "an equal frac inserted before
the old one" covers it; `traverseTo` takes the chain's head).

The acceptance runs found two defects, both fixed before these numbers:
`ptStuck`'s `ICPT + 6 A` lost its carry at an end of 64 intercepts (9
runs: the copies' entries garbage), and grec's recording traverser (R2).

**Sizes** (`path.py`'s `sizes`, the map's module list; `make -f game.mk
sizes` was not run: it rebuilds the skeleton's shared image while the
other parts build): **1,357 B of 1,600** (upstream 1,239): `ptBody` 524,
`axisStep` 271, `ptStuck` 190, `early` 154, `traverseTo` 125, `offLine`
31, `fromOrigin` 31, `P_PathTraverse` 17, `a1Shr7` 14; test-only
`pttest.s` 241 B in the driver's area (`PT_TEST=1` only). The build: no
warnings; `gcallgraph.py --check` 0 failures.

**The test module** (`python3 -m unittest tests.test_native_game_path`):
9 tests; by default 24 s at 2 processes (the build's checks, 4 of the
chosen calls with their variants, the plain and synthetic cases, one
acceptance trace, the random check, two plants), with `DOOM_GS_FULL=1`
every case and the three plants.

**build/ growth**: 65 MB (`build/native/game/path/`: the whole-machine
captures 31 MB, the variants and acceptance runs 13 MB, the image and its
listings); every temporary directory deleted.

**Commands**:

    make -s -C src/native -f game.mk part P=path PT_TEST=1 ROOT=$PWD
    python3 tools/native/gparts/path.py --select --capture --variants --acceptance
    python3 tools/native/gparts/path.py --run --random --plants --report --jobs 2
    python3 -m unittest tests.test_native_game_path
    DOOM_GS_FULL=1 python3 -m unittest tests.test_native_game_path

## 4. Open points

- R1-R6 wait for the integrator; R1 before wave 4's parts link together
  (the stand-in overlaps `SB_TRYMOVE`).
- The lean checkpoint: one fill (`$A5`), one profile (`f121`), 40 calls,
  not "every captured call"; the k-stops at 1, the middle and the last,
  not every k; acceptance 6 with 25 traces (17 of more than 64
  intercepts, on seven maps), not about 500; the final integration
  decides what more is run.
- Not reached by any run: the lines' list full and the early limit's cap
  at `FRACUNIT` (above).
- Every captured call reaches a traverser of wave 5: no captured call
  runs whole with its own traverser until `attack`, `xymove` and
  `player` are built (4,333 of 12,197 run as captured: their traverser
  is never called).
- (Wave 2 as integrated) `P_PathTraverse` starts a trace in the shared tic scratch (`tracel.md` R1, wave 2 as integrated): `GM_ICN` 0, `ICHAIN + 64` = `$FF`, `GM_ICLAST` 64, the trace in `GM_TRACE` and `GM_TRLONG`. (Done.)
- (Wave 2 as integrated) `ptStuck`'s copies `FCALL icInsert` (upstream's `icInsertL` has no native code: `tracel.md` R3). (Done.)
- (Wave 2 as integrated) `FixedDiv`'s inputs that upstream never returns from count in `GT_DIV0` (`tracel.md` R4, GAME.md 3.6 T8). (Two acceptance candidates on E1M8 hit it: not compared.)
- (Wave 3 as integrated) `sideSetup` (part `tracet`) takes `P_PathTraverse`'s flags in A; upstream's `ptT1`, `ptT2`, `vsPatch`, `ptPatch` and the SIDE1 site patchers have no native code (`glayout.INLINED['tracet']`): `path` tests its flags itself at `ptL1`-`ptL3` (`tracet.md` R1). (Done.)
- (Wave 3 as integrated) Upstream's `VT_RR` is GW's `GM_RR`, SIDE1's constants `GM_SIDE1` (15), never overlaid, live across the early traversal's traverser calls (`tracet.md` R4). `traceLines` runs only when `GM_RR` is not 0; `traceLines`, `traceThings` take the block in `GA_0-3` (README "The parts' interfaces"). (Done.)
- (Wave 3 as integrated) The dead guard's state (GAME.md 3.5 R4): `ptBody` keeps its `stz G_IDT` only if the guard's state is kept natively, which nothing reads (`tracet.md` R3). (Not kept: no native `G_IDT`.)
- (Wave 3 as integrated) `P_AproxDistance` is the core's `aproxdist` (math-g.o, `look.md` request 2). (Done: `ptBody`'s K.)

## 5. The integration of wave 4 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 4 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 the scratch block, 44 B | **Accepted**: `glayout.SCRATCH_REQUESTS['path'] = 44` (`SB_PATH` `$9C2A`, `SB_TRYMOVE` after it at `$9C56`); `path.inc`'s stand-in `.assert` is now `SB_PATH_SIZE >= PT_NEED` |
| R2 `TRVTAB`'s convention, `gt_record_trv` | **Accepted** as written: `grec.s`'s `gt_record_trv` takes `GA_0` and makes `ICPT + 6 × GA_0` in 16 bits; `pttest.s`'s `pt_rec_trv` is `jmp gt_record_trv` (`path.py` unchanged); README's `DCALL` list has the traverser's convention |
| R3 `callTrav` inlined | **Accepted**: `glayout.INLINED['path']`; the core no longer gives it bytes |
| R4 the part as one unit | **Accepted**: `gplace.AFFINITY`; the measured placement puts the nine routines in group 18, slot 2 (1,726 B with `P_MobjThinker` and friction's helpers), tracet's block steps are group 22, slot 1, but tracel's crossed line is group 9, slot 2, the walk's slot: each `PIT_AddLineIntercepts` under `traceLines` loads group 9 over the walk's group and `fc_call` loads it back. `gplace.py`'s model counts only the calls between two groups of one slot, not a callee's callee in the caller's slot, so it does not see this cost: an open item for the timing report (GAME.md 5.4) and the next placement |
| R5 the interfaces | **Accepted**: README "The parts' interfaces" (both rows); `attack.md`, `xymove.md`, `player.md` noted |
| R6 acceptance 6 as found; whole-machine variants | **Accepted**: GAME.md 5.2 row 6's "Checks" and README "Testing a part" as written |

**Wave 5 as integrated (2026-10-02).** With `TRVTAB` built, 31 of the 40 chosen captured calls run as captured with their own traverser. `path.py`'s `TRV_CONTEXT` writes each traverser's context (what its caller set: attack's `AT_*` and `_g_linetarget`, player's `usething`, xymove's `SL_MO`, `SL_BEST`) from the reference's state at the call, and `geom_check.allowed_main` allows ghook's sound event buffer (`PTR_UseTraverse`'s noway or switch sounds). All 40 captured calls equal (`$A5`, `f121`); before the context, demo1 h2362 differed (GAME.md "Wave 5 as integrated").

## 6. The final integration (2026-10-02)

Acceptance 6 at the final integration (the owner's lean target: 200
traces of more than 64 intercepts) uses this part's method with two
entries the integrator added to `tools/native/gparts/path.py`:
`--acceptance-final` (`make_acceptance_final`: the candidates of
`acc_candidates` on the tour's state of each map that has such traces,
E1M2, E1M3, E1M5-E1M9, a new seed, 29 kept a map, each run on the
reference never stopping and stopping at k = 1, 8, 32, 64, 65, into
`cases/acc6-final/`) and `--run-final` (`check_final`: those cases on the
part's image, `acc6-final-run.json`). The part's own `acc6/` cases and
checks are unchanged. Results: docs/GAME.md "Acceptance".
