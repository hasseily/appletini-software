# Part `tracet` (wave 3)

The record of milestone 10's part `tracet` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 3; upstream 2189 B, native budget 2800 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 3's `tracet` (built 2026-10-02, on a2vm against ref816, under the owner's lean checks of 2026-10-02; nothing committed).
- Files: `src/native/game/tracet/*.s`, `src/native/game/tracet/part.mk`, `src/native/game/tracet/args.json`, `tests/test_native_game_tracet.py`, this file; tools (if any) `tools/native/gparts/tracet*.py`; build output `build/native/game/tracet/` (`make -s -C src/native -f game.mk part P=tracet ROOT=$PWD`).
- Its scratch block: `SB_TRACET` (32 B, `ggame.inc`), 29 bytes used (`tracet.inc`; 16 of them the stand-in of request R4).

The routines (GAME.md 2.4's row):

`p_trace65.s`: `traceLines:1142` (each block's lines with `validcount`, the fast vertex sides), `traceThings:1407` (a thing's diagonal), `sideSetup:860`, `longTrace:817`, the patched templates `tlP1`, `tlP2`, `thP`, `gtP1`, `gtP2`, `ptT1:1681`, `ptT2:1762`, `vsPatch:1806`, `ptPatch:1842` (natively data, not patched code); helpers `thFast`, `thFastL`, `thSide`

Its checkpoint (GAME.md 2.4): `traceLines` and `traceThings` on every captured block step of `P_PathTraverse` (DEMO2 5,602 traverses); synthetic: a trace through a vertex, along a line

Its planted bugs (each must fail the named check): a thing's diagonal chosen by the wrong quadrant; the stamp written after the box test; a line shared by two blocks met twice

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_trace65.s:traceLines` | `traceLines` | demo3 1594, demo1 4364, demo2 1473, newgame 54, tour 4 |
| `p_trace65.s:traceThings` | `traceThings` | demo3 1573, demo1 4293, demo2 1427, newgame 52, tour 0 |
| `p_trace65.s:sideSetup` | `sideSetup` | demo3 1064, demo1 5380, demo2 5602, newgame 152, tour 4 |
| `p_trace65.s:longTrace` | `longTrace` | demo3 1064, demo1 5380, demo2 5602, newgame 152, tour 4 |
| `p_trace65.s:ptT1` | `ptT1` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_trace65.s:ptT2` | `ptT2` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_trace65.s:vsPatch` | `vsPatch` | demo3 287, demo1 637, demo2 268, newgame 11, tour 4 |
| `p_trace65.s:ptPatch` | `ptPatch` | demo3 49, demo1 176, demo2 79, newgame 4, tour 1 |

Helpers: `p_trace65.s:thFast`, `p_trace65.s:thFastL`, `p_trace65.s:thSide`, `p_trace65.s:tlP1`, `p_trace65.s:tlP2`, `p_trace65.s:thP`, `p_trace65.s:gtP1`, `p_trace65.s:gtP2`.

What the part built: `src/native/game/tracet/tracet.s` (`traceLines`,
`traceThings`, `thFast`, `thSide`, `sideSetup`, `longTrace`, each a
`ROUTINE`; upstream's `VSIDE` and `tlSlow1`/`tlSlow2` inside
`traceLines`), `tracet.inc` (the places, the zero page, the macros
`TT_INRANGE` and `SIDE1`), `part.mk`, `args.json`;
`tools/native/gparts/tracet.py` (the selection, the captures, the
synthetic cases, the routine runs with the trace's state, a model of
upstream's branches for the coverage, the dead guard's evidence, the
planted builds, `report.json`); `tests/test_native_game_tracet.py`.

### The native interfaces (what part `path` calls)

Every routine is `FCALL`ed by its name. SIDE1's constants (upstream's
`VT_*` of bank `$21`) are `TT_*` (`tracet.inc`, exported by `tracet.s`;
request R4 moves them to GW).

| Routine | In | Out | Changes |
| --- | --- | --- | --- |
| `traceLines` | `GA_0-1` the block's x, `GA_2-3` its y (signed words); called only when `TT_RR` is not 0, as upstream's `ptL2` site does [R `p_path65.s:335-336`] | A = 1 and C set (every line done, or off the map); A = 0 and C clear: the intercepts are full | `GA_*`, `GT_*`, the math, the lines' `LN_VALID` (stamped with `G_VALID` before their sides), the intercepts |
| `traceThings` | the same | the same | the same (no stamps) |
| `sideSetup` | A = `P_PathTraverse`'s flags (`UC_PT_ADDLINES`, `UC_PT_ADDTHINGS`); `GM_TRACE`, `GM_TRLONG` | `GM_IVON` (`ivSetup`'s answer for a shot, else 0), `GM_IVM`; when the trace is long, not on an axis, `|DX| + |DY| <= 2900` and its start below `$7FFF.0001`: `TT_*`, `GM_INVB` and `TT_RR` = 1; else `TT_RR` = 0 (`GM_INVB` and the rest as they were, as upstream leaves them) | `GA_*`, `GT_*`, the math |
| `longTrace` | `GM_TRACE` | C set and A = 1 when `dx`, `dy` > 16 units or < -16 units, else C clear and A = 0 (`path` stores it in `GM_TRLONG`) | |
| `thFast` | `TT_MO` (a mobj) | A = 0 not crossed, 1 crossed, 2 cannot tell | `GT_0-GT_11`, `TT_X2`, `TT_Y2`, `TT_S1`, `TT_SEL` |
| `thSide` | `GT_0-1` X', `GT_2-3` Y', `TT_SEL` (0 a vertex, 2 a thing's corner) | C clear and A = `$80` (side ^ inv); C set: this way cannot tell | `GT_4-GT_11`, the math |

Upstream's `ptPatch` patched the flag tests of `P_PathTraverse`'s block
loop (`ptL1`-`ptL3`), of the guard (`ptG1`, `ptG2`) and of `gBlockT`
(`ptT1`, `ptT2`) when the flags changed (`PT_FLP`, a "code patch" the
bridge excludes); `vsPatch` wrote SIDE1's register pair for the main axis
into `tlP1`, `tlP2`, `gtP1`, `gtP2`, `thP`. Natively both are data:
`path` tests its flags itself at those three sites, and SIDE1 reads the
axis from `TT_AX`. `thFastL` (a long-call wrapper) has one caller,
`gBlockT`, the dead guard's. None of these has native code (R1).

### The dead guard (GAME.md 3.5 R4)

`traceLines` has no native code for upstream's count of the guard with the
sides (`G_IDT`, `GSTAMP` [R `p_trace65.s:1199-1213`]): `ptBody` clears
`G_IDT` (= `G_OFS`) before every walk [R `p_path65.s:271`], and only the
guard sets it [R `p_path65.s:896`], which the release never calls
(`early`'s `bra 4$` over it [R `p_path65.s:612-614`]). The captures show
it: `tracet.py --guard` reads every one of the 160 sampled calls of the
four entries: none writes `GSTAMP` (`line.gstamp`), `GW_TAB`, `G_ID`,
`GW_TAG`, `G_N`, `G_OFS`, `G_MX`, `G_MY`, `G_XI`, `G_YI`, `G_COUNT`,
`G_PREV` or `PT_OK`, and `G_IDT` is 0 at each of the 40 calls of
`traceLines` (`guard.json`). The release's writers of the guard's state
are elsewhere, and only the guard reads them: `P_SetupLevel`'s `stz G_ID`
[R `p_setup65.s:137`], `P_InitFlood`'s `GW_TAG` and `GW_TAB` at a load
[R `p_pspr65.s:1306-1318`], `ptBody`'s `stz G_IDT` [R `p_path65.s:271`]
(part `path`'s).

## 2. Requests

Each: what, why (the evidence), what it changes for other parts. All are
for the integrator; none is applied by the part.

**R1. No native code for the templates, their patchers and `thFastL`.**
Upstream's patched templates and their patchers are data natively (the
row says so: "natively data, not patched code"), and `thFastL` is a
long-call wrapper whose one caller is the dead `gBlockT`
[R `p_trace65.s:1783`]. Exact change in `tools/native/glayout.py`,
`INLINED`, after `'spawn'`'s entry:

```
    # wave 3 (docs/game-parts/tracet.md R1): upstream's patched templates
    # and their patchers are data natively (TT_AX; part path tests its
    # flags itself), thFastL a long-call wrapper of the dead guard's
    'tracet': ('p_trace65.s:ptT1', 'p_trace65.s:ptT2',
               'p_trace65.s:vsPatch', 'p_trace65.s:ptPatch',
               'p_trace65.s:thFastL', 'p_trace65.s:tlP1',
               'p_trace65.s:tlP2', 'p_trace65.s:thP', 'p_trace65.s:gtP1',
               'p_trace65.s:gtP2'),
```

Effect: the placement gives them no bytes (today `vsPatch`, `ptPatch` are
in group 2, `ptT1` in 22, `thFastL`, `thP` in 16); `path` reads the
flags itself at `ptL1`-`ptL3` (its record should say so); nothing else.
`tests/test_native_game_tracet.py` already checks that they have no
label.

**R2. The placement: the measured sizes, and two units.** The estimated
placement put `traceLines`, `sideSetup`, `longTrace` in group 24 (slot 2,
estimated 1,966 B with geom's iterators, flow's `doCompleted`,
`signLong` and path's `ptStuck`, `offLine`, `fromOrigin`). With SIDE1
expanded in `traceLines` (as upstream's `VSIDE` macro is) the part's
build overflowed group 24 by 90 B, so SIDE1 is one copy in `thSide`
(group 16, slot 1), which `traceLines` calls twice a line through
`fc_call`. The built part of group 24 is now 1,888 of 2,048 B (flow 349,
geom 616, tracet 923) before path's three routines are built. Measured
sizes (`report.json`): `traceLines` 367, `traceThings` 410, `thFast`
278, `thSide` 272, `sideSetup` 444, `longTrace` 112 (1,883 B). Request,
in `tools/native/gplace.py` `AFFINITY`:

```
    ('p_trace65.s:traceLines', 'p_trace65.s:traceThings',
     'p_trace65.s:thFast', 'p_trace65.s:thSide'),
```

(1,327 B: the block steps' every line and thing; `thSide` twice a line
and a thing), and `sideSetup`, `longTrace` into the unit of tracel's
`ivSetup`, `gOf`, `smul`, `vsC` (856 B; GAME.md "Wave 2 as integrated",
not done: "`tracet`'s `sideSetup` joins the unit"). Effect: placement
only; `gplace.py --measure` on the wave-3 image gives the real sizes.
Path's `P_PathTraverse` loop calls `traceLines` and `traceThings` once a
block: the first unit beside path's loop and tracel's crossed line
(1,721 B) is the integrator's choice.

**R3. GAME.md 3.5 R4: the evidence.** Exact change in the R4 row's
second cell, after "or names the writes (they cannot change a result:
only the guard reads them)": " (wave 3: part `tracet`'s 160 sampled calls
of `traceLines`, `traceThings`, `sideSetup` and `longTrace` write none
of them, and `G_IDT` is 0 at each of its 40 `traceLines` calls; the
release writes them only in `P_SetupLevel`'s `stz G_ID` [R
`p_setup65.s:137`], `P_InitFlood`'s `GW_TAG` and `GW_TAB` at a load [R
`p_pspr65.s:1306-1318`] and `ptBody`'s `stz G_IDT` (`G_OFS`) before each
walk [R `p_path65.s:271`]: `docs/game-parts/tracet.md` "The dead
guard")". Effect: none on other parts; `ptBody` (part `path`) keeps its
`stz G_IDT` only if the guard's state is kept natively, which nothing
reads.

**R4. SIDE1's constants as shared tic scratch in GW.** `VT_RR`, `VT_P1`,
`VT_P2`, `VT_CV`, `VT_CT`, `VT_OXC`, `VT_OYC`, `VT_SGN`, `VT_DYF` and the
pair of `vsPatch` [R `p_trace65.s:25-37`, `:860-974`] live from
`sideSetup` to a trace's last block step, across the early traversal's
calls of the traverser (`early` → `traverseTo` → `callTrav` [R
`p_path65.s:381`, `:802`, `:816`]: parts `attack`, `xymove`, `player`, and
through them most of the game), and part `path` reads `VT_RR` [R
`p_path65.s:335`] (and its dead guard at `:888`, `:1050`, `:1254`). A scratch block is one part's and can
be overlaid (GAME.md 4.4), so they belong in GW, never overlaid, as
tracel's trace state (tracel.md R1). Exact change in
`tools/native/glayout.py`, `TIC_GW_FIELDS`, after `('GM_ATRANGE', ...)`:

```
                 ('GM_RR', 1), ('GM_SIDE1', 15),
```

with the comment "SIDE1's constants of the trace (docs/game-parts/
tracet.md R4): VT_RR (not 0: the fast vertex sides), then the axis,
VT_P1, VT_P2, VT_CV, VT_CT, VT_OXC, VT_OYC, VT_SGN's and VT_DYF's high
bytes". Local stand-in: `tracet.inc` puts them in `SB_TRACET` + 0 .. + 15,
each marked "(stand-in R4)". With R4 the ten lines of `tracet.inc` become
`TT_RR = GM_RR`, `TT_AX = GM_SIDE1 + 0`, `TT_P1 = GM_SIDE1 + 1`, `TT_P2
= + 3`, `TT_CV = + 5`, `TT_CT = + 7`, `TT_OXC = + 9`, `TT_OYC = + 11`,
`TT_SGN = + 13`, `TT_DYF = + 14` (no code changes: `tracet.py` finds them
by their labels; `thSide`'s `TT_CV,y` with Y = 0, 2 needs `TT_CT` 2 bytes
after `TT_CV`, which this order keeps), and `SB_TRACET` keeps the walks'
13 bytes. Effect: `path` reads `GM_RR` where upstream reads `VT_RR`;
nothing else moves.

**R5. The parts' interfaces in `src/native/game/README.md`.** Exact rows
for "The parts' interfaces" table, after `tracel`'s:

```
| `traceLines`, `traceThings` (`tracet`) | `GA_0-1` the block's x, `GA_2-3` its y (signed words); `traceLines` only when `TT_RR` (R4: `GM_RR`) is not 0 | A = 1 and C set, A = 0 and C clear when the intercepts are full |
| `sideSetup` (`tracet`) | A = the flags (`UC_PT_ADDTHINGS`); `GM_TRACE`, `GM_TRLONG` | `GM_IVON`, SIDE1's constants, `GM_INVB`, `TT_RR` |
| `longTrace` (`tracet`) | `GM_TRACE` | C set (A = 1): a long trace |
```

and in the README's paragraph on the trace's state: "`sideSetup` (part
`tracet`) takes `P_PathTraverse`'s flags in A; upstream's `ptPatch` and
`vsPatch` have no native code: `path` tests its flags itself". Effect:
documentation only.

## 3. Results

All on a2vm against ref816, 2026-10-02, at 2 processes; the part's image
links waves 1 and 2 (integrated) and this part. Under the owner's lean
checks of 2026-10-02: at most 40 captured calls an entry, from the `$A5`
machine only, under `f121` only. `build/native/game/tracet/report.json`
holds every number below.

**The routine checkpoint** (`tracet.py --run`): every sampled and
synthetic case, the canonical state after the call (gcanon's routine
mode, exclusions R1-R7 only: the lines' `validcount` stamps among it),
every declared output (the return value in A and C; the intercepts:
their count, each one's frac and line or mobj, the chain walked from its
head, `IC_LAST`; the trace's state `GM_*`; SIDE1's constants), no stray
write (a2vm's write log): 174 runs, 0 failed, 0 stray writes.

| Entry | Survey calls | Sampled (synthetic) | Runs | Failed | Stray | Cycles median / worst (f121) | µs median / worst | Lowest S |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| `traceLines` | 7,484 | 40 (4) | 44 | 0 | 0 | 123,919 / 311,387 | 2,488 / 6,251 | `$DD` |
| `traceThings` | 7,341 | 40 (2) | 42 | 0 | 0 | 75,156 / 325,008 | 1,525 / 6,540 | `$DE` |
| `sideSetup` | 12,197 | 40 (7) | 47 | 0 | 0 | 50,159 / 52,368 | 1,011 / 1,045 | `$E1` |
| `longTrace` | 12,197 | 40 (1) | 41 | 0 | 0 | 39,629 / 39,657 | 801 / 802 | `$E8` |

- **The sample.** `traceLines`, `traceThings`: 40 spread evenly over the
  survey's calls (demo3 9, demo1 23, demo2 8). `sideSetup`, `longTrace`
  (one call each a trace): 20 from the tics in which `traceLines` runs
  (the long traces with the fast sides, which only those calls set up),
  20 spread over all (demo3 6, demo1 20, demo2 14). No entry dispatches:
  every call is eligible. Each case is a separate a2vm run (the routine
  harness gives each call its own pre-state).
- **Synthetic** (`tracet.py --synth`: a sampled case's state with pokes,
  the calls run alone on ref816 by `--call`, a new trace through
  upstream's own `sideSetup` first): `traceLines` on a trace through a
  line's vertex (x axis, and y axis with `dx < 0`: SIDE1 cannot tell at
  the vertex, `vtxSlowR` decides), on a trace along a slanted line (both
  vertices on the trace: `vtxSlowR` twice), and with the list full (64:
  A = 0); `traceThings` with `VT_RR` 0 (every thing by `divlineSide` on
  its diagonal) and with the list full; `sideSetup` with `dx` 0, `dy` 0,
  `|DX|` 2,901, `|DX| + |DY|` 2,901, x at `$7FFF.8000`, y at
  `$7FFF.0001`, a start in whole units; `longTrace` with `dx` -17 units.
- **The branches** (`tracet.py`'s model of upstream's routines on each
  case's inputs; `report.json` `paths`): taken by the sampled and
  synthetic calls: `traceLines` off the map, a line stamped already,
  SIDE1's sign test, its product deciding, its limit (cannot tell:
  `vtxSlowR`), crossed, not crossed, the list's end, full;
  `traceThings` off the map, an empty block, `thFast` crossed and not
  crossed, `VT_RR` 0 (the slow sides) crossed, both quadrants, full;
  `sideSetup` every branch (lines, things, short, `dx` 0, `dy` 0, `|DX|`
  and the sum too large, both overflows, axis x and y, SQ of both signs,
  a start with and without fraction); `longTrace` `dx` above, below, `dy`
  above, short. **Not reached**: `traceLines`' SIDE1 out of range (`|X'|`
  or `|Y'|` > 2,040) and its vertex overflow (`vtxSlowR` for both);
  `traceThings`' radius with a fraction, its overflow, SIDE1 unable to
  tell at a corner, a thing not crossed by the slow sides; `longTrace`'s
  `dy` below -16 units (its test is the mirror of `dx`'s, which is taken).
- **The timings are upper bounds**: routine mode with every slot empty at
  the call, and the estimated placement spreads the part over three
  groups (R2): `longTrace`'s 39,629 cycles are almost all its group's
  load. No timing study was made (lean checks).

**The dead guard** (`tracet.py --guard`): 160 sampled calls, no write of
the guard's state, `G_IDT` 0 at all 40 `traceLines` calls ("The dead
guard" above; R3).

**The planted bugs** (each in a scratch copy, `tracet.py`'s `PLANTS`,
run on the sampled and synthetic cases of its entry;
`tests/test_native_game_tracet.py`'s `TestPlants`):

| Plant | Entry | Caught | The first difference |
| --- | --- | --- | --- |
| a thing's diagonal chosen by the wrong quadrant (`dx ^ dy < 0` taken as `> 0`) | `traceThings` | 7 of 42 | intercept 3: frac `$2107`, upstream `$206D` |
| the stamp written after the side test (only a crossed line stamped; GAME.md's "box test" is the side test here: `traceLines` has no box) | `traceLines` | 33 of 44 | `line[946].validcount`: 3,232, upstream 3,231 |
| a line shared by two blocks met twice (the stamp not tested) | `traceLines` | 6 of 44 | 6 intercepts, upstream 5 |

**Sizes** (`tracet.py`'s `sizes`, the map's module list; `make -f
game.mk sizes` was not run: it rebuilds the skeleton's shared image while
the other parts build): 1,883 B of 2,800 (upstream 2,189): `traceLines`
367, `traceThings` 410, `thFast` 278, `thSide` 272, `sideSetup` 444,
`longTrace` 112. No test driver. The build: no warnings; `gcallgraph.py
--check` 0 failures.

**The test module** (`python3 -m unittest tests.test_native_game_tracet`):
8 tests; by default 22 s at 2 processes (the build's checks, 4 sampled
calls an entry with every synthetic case, the guard, the stamp plant on 4
calls and the synthetic ones), with `DOOM_GS_FULL=1` 180 s (every sampled
call, the three plants).

**build/ growth**: 35 MB (`build/native/game/tracet/`: the cases 19 MB,
the image and its listings 16 MB); every temporary directory deleted.

**Commands**:

    make -s -C src/native -f game.mk part P=tracet ROOT=$PWD
    python3 tools/native/gparts/tracet.py --select --capture --synth
    python3 tools/native/gparts/tracet.py --run --guard --plants --report --jobs 2
    python3 -m unittest tests.test_native_game_tracet
    DOOM_GS_FULL=1 python3 -m unittest tests.test_native_game_tracet

## 4. Open points

- R1-R5 wait for the integrator; until R4 SIDE1's constants are in
  `SB_TRACET`, so `path` (wave 4) imports `TT_RR` from this part or waits
  for `GM_RR`.
- The lean checkpoint: one fill (`$A5`), one profile (`f121`), 40 calls
  an entry, not "every captured block step of `P_PathTraverse`"; the
  branches listed as not reached above are unchecked; the final
  integration decides what more is run.
- `traceLines` calls `thSide` through `fc_call` twice a line (R2: one
  group, or SIDE1 expanded back in `traceLines` when the group has room).
- Group 24 holds path's `ptStuck`, `offLine`, `fromOrigin` too: with them
  built it passes 2,048 B (R2).
- (Wave 2 as integrated) The trace's state is shared tic scratch since wave 2's integration (`tracel.md` R1): `sideSetup` writes `GM_IVON` (`ivSetup`'s A) and `GM_INVB`, and reads `GM_TRACE`, `GM_TRLONG` (`ggame.inc`); the intercepts are `ICPT`/`ICHAIN` as `tracel.md` says. (Done.)
- (Wave 2 as integrated) `vtxSlowL`, `lineCrossL`, `icInsertL` have no native code (`glayout.INLINED`): `FCALL vtxSlow`, `lineCross`, `icInsert` (`tracel.md` R3). (Done: `traceLines` calls `vtxSlowR` and `lineCross`, `traceThings` `divlineSide`, `ivAxis`, `interceptVector3`, `addIntercept`.)
- (Wave 2 as integrated) `gplace.AFFINITY` keeps tracel's `ivSetup`, `gOf`, `smul`, `vsC` together (300 B); `sideSetup` is their only caller: ask for it in that unit (`tracel.md` R2). (Asked: R2.)

## 5. The integration of wave 3 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 3 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| R1 the templates and patchers inlined | **Accepted**: `glayout.INLINED['tracet']` as written |
| R2 the placement | **Accepted**: `gplace.AFFINITY` `traceLines`, `traceThings`, `thFast`, `thSide` (group 24, slot 1, 1,434 B with spawn's `checkMissile`); `sideSetup`, `longTrace` joined tracel's `ivSetup`, `gOf`, `smul`, `vsC` (group 15, slot 1, with path's estimated `ptStuck`, `offLine`, `axisStep`, `early`, `fromOrigin` and geom's `P_BlockThingsIterator`). `gplace.py --measure build/native/game/wave3/wtest --write` |
| R3 GAME.md 3.5 R4's evidence | **Accepted**: the row's text as written |
| R4 SIDE1's constants in GW | **Accepted**: `TIC_GW_FIELDS` `GM_RR` (`$B323`), `GM_SIDE1` (15, `$B324`); `tracet.inc`'s `TT_RR` .. `TT_DYF` are those names; `SB_TRACET` keeps the walks' 13 bytes (`TT_S1` .. `TT_SEL` moved down by 16, `TT_NEED` 13) |
| R5 the interfaces | **Accepted**: README "The parts' interfaces" and the trace's paragraph |
