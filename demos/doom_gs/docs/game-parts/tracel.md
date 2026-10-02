# Part `tracel` (wave 2)

The record of milestone 10's part `tracel` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 2; upstream 2136 B, native budget 2800 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 2's `tracel` (built 2026-10-02, on a2vm against ref816; nothing committed).
- Files: `src/native/game/tracel/*.s`, `src/native/game/tracel/part.mk`, `src/native/game/tracel/args.json`, `tests/test_native_game_tracel.py`, this file; tools (if any) `tools/native/gparts/tracel*.py`; build output `build/native/game/tracel/` (`make -s -C src/native -f game.mk part P=tracel ROOT=$PWD`).
- Its scratch block: `SB_TRACEL` (32 B, `ggame.inc`), all 32 bytes used (`tracel.inc`; 29 of them the stand-in of request R1).

The routines (GAME.md 2.4's row):

`p_trace65.s`: `PIT_AddLineIntercepts:985`, `interceptVector3:242` (`P_InterceptVector3` with its `FixedDiv` and guards [R `NATIVE.md` 3.2]), `divlineSide:152`, `addIntercept:744`, `icInsert:778` (the by-frac list), `ivSetup:1875`; helpers `ivTest`, `ivProd`, `ivAxis`, `lineCross`, `lineCrossL`, `vtxSlow`, `vtxSlowL`, `vtxSlowR`, `icInsertL`, `gOf`, `smul`, `vsC`

Its checkpoint (GAME.md 2.4): `PIT_AddLineIntercepts` through `P_BlockLinesIterator` on every captured `P_PathTraverse` block step; `interceptVector3` and `divlineSide` on 1,000,000 random inputs by `--call` plus every captured input; synthetic: two intercepts of equal frac (the list's order)

Its planted bugs (each must fail the named check): the `FixedDiv` guard one off (random inputs); an equal frac inserted before the old one (synthetic); the fast product path deciding where upstream's does not (random)

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_trace65.s:PIT_AddLineIntercepts` | `PIT_AddLineIntercepts` | demo3 2678, demo1 15329, demo2 18585, newgame 252, tour 0 |
| `p_trace65.s:interceptVector3` | `interceptVector3` | demo3 1069, demo1 4180, demo2 5556, newgame 88, tour 0 |
| `p_trace65.s:divlineSide` | `divlineSide` | demo3 145, demo1 313, demo2 113, newgame 0, tour 0 |
| `p_trace65.s:addIntercept` | `addIntercept` | demo3 2407, demo1 5958, demo2 6245, newgame 105, tour 0 |
| `p_trace65.s:icInsert` | `icInsert` | demo3 2465, demo1 5958, demo2 6245, newgame 105, tour 0 |
| `p_trace65.s:ivSetup` | `ivSetup` | demo3 272, demo1 591, demo2 242, newgame 10, tour 0 |

Helpers: `p_trace65.s:ivTest`, `p_trace65.s:ivProd`, `p_trace65.s:ivAxis`, `p_trace65.s:lineCross`, `p_trace65.s:lineCrossL`, `p_trace65.s:vtxSlow`, `p_trace65.s:vtxSlowL`, `p_trace65.s:vtxSlowR`, `p_trace65.s:icInsertL`, `p_trace65.s:gOf`, `p_trace65.s:smul`, `p_trace65.s:vsC`.

What the part built: `src/native/game/tracel/tracel.s` (every routine and
helper above, each a `ROUTINE`; upstream's `fixedDiv` and `fdLoop` inside
`ivTest`, `ivB` inside `interceptVector3`, `ivSlow` inside `ivProd`;
`SIDEPROD` a macro on `mul32`), `tracel.inc` (the places, the zero page,
the macros `SIDEPROD`, `ICPTR`, `FRACLT`), `tracelt.s` (the random
checks' driver: segment `DRIVER`, `TESTBUILD` only), `part.mk`,
`args.json`; `tools/native/gparts/tracel.py` (the selection, the
captures, the synthetic cases, the routine runs with the trace's state,
the call logs, the random checks, a step model of upstream's routines,
the planted builds, `report.json`); `tests/test_native_game_tracel.py`.

### The native interfaces (what later parts call)

Every routine is `FCALL`ed by its name. The trace's state (`TL_TRACE`,
`TL_TRLONG`, `TL_ICN`, `TL_ICLAST`, `TL_IVON`, `TL_IVM`, `TL_INVB`,
exported by `tracel.s`; request R1 moves them to `GM_*`) and the
intercepts (`ICPT`: frac 4, what 2 = a line, or `$8000` + a mobj slot;
`ICHAIN`: the next entry's index after each, `$FF` none, the head at
`ICHAIN + 64`) are as GAME.md 1.9 and `tracel.inc` say. `P_PathTraverse`
(part `path`) starts a trace with `TL_ICN` 0, `ICHAIN + 64` = `$FF`,
`TL_ICLAST` 64, the trace and `TL_TRLONG`; `sideSetup` (part `tracet`)
sets `TL_IVON` from `ivSetup`'s A, and `TL_INVB`.

| Routine | In | Out | Changes |
| --- | --- | --- | --- |
| `PIT_AddLineIntercepts` | `GA_0-1` the line (ITTAB's convention) | C set: go on; clear: the intercepts are full | `GA_*`, `GT_0-GT_18`, the math |
| `divlineSide` | `GA_0-3` x, `GA_4-7` y (fixed_t) | A = 0, 1 | `GA_0-7`, `GT_0-3`, the math |
| `interceptVector3` | dl in `GA_0-15` (x1, y1, dx, dy) | `GA_16-19` the frac | `GT_0-GT_15`, the math |
| `ivTest` | num `GT_0-3`, den `GT_4-7` | `GA_16-19` | `GT_0-GT_15`; `GT_DIV0` + 1 where upstream never returns (R4) |
| `ivProd` | X the axis (0, 4), dl in `GA_0-15` | `M_R` | `GT_12-13`, the math |
| `ivAxis` | dl in `GA_0-15` | C set and `GA_16-19`, or C clear | as `ivTest` |
| `lineCross`, `lineCrossL` | A:X a line | A = 0 and C clear: full; else A = 1, C set | `GA_*`, `GT_*`, `TL_LD` |
| `vtxSlow`, `vtxSlowL` | A:X a line, Y `LN_V1X` or `LN_V2X` | A = 0, 1 | as `divlineSide` |
| `vtxSlowR` | the same | A = `$80` side ^ `TL_INVB` (upstream's `$8000 (side ^ inv)`) | the same |
| `addIntercept` | A:X what, `GA_16-19` the frac | C clear when full | `GT_0-5` |
| `icInsert`, `icInsertL` | A an entry | the chain, `TL_ICLAST` | `GT_0-5` |
| `ivSetup` | the trace | A = 1, 0; `TL_IVM` | |
| `gOf` | A:X f | A:X | |
| `smul` | `M_A`, `M_B` (16 bits, signed) | `M_R` | the math |
| `vsC` | `GA_0-1` SQ, `GA_2` the axis (0, 4), `GA_4-5` g of y, `GA_8-9` g of x | `GA_16-17` VT_CV, `GA_18-19` VT_CT | the math |

## 2. Requests

Each: what, why (the evidence), what it changes for other parts. All are
for the integrator; none is applied by the part.

**R1. The trace's state as shared tic scratch in GW.** `_g_trace`,
`TR_LONG`, the intercepts' count (`intercept_p`), `IC_LAST`, `IV_ON`,
`IV_ML`/`IV_MH`, `VT_INVB` are upstream's scratch of `p_trace65.s` and
`p_path65.s` [R `p_trace65.s:29-47`, `:1913-1919`; `p_path65.s:226-271`],
written by `path` (`P_PathTraverse`) and `tracet` (`sideSetup`), read by
this part, `tracet`, `path` and the traversers (`attack`: the trace's point
at a frac). GAME.md 1.9 names them but no shared place holds them (only
`ICPT` and `ICHAIN` are in `llayout.GW_FIELDS`); a scratch block can be
overlaid (4.4) and is one part's, so they belong in GW, never overlaid,
as geom's `GM_*` (geom R3). Exact change in `tools/native/glayout.py`,
`TIC_GW_FIELDS`, after `('API_W', 2)`:

```
                 ('GM_TRACE', 16), ('GM_TRLONG', 1), ('GM_ICN', 1),
                 ('GM_ICLAST', 1), ('GM_IVON', 1), ('GM_IVM', 8),
                 ('GM_INVB', 1),
```

(29 of GW's 254 free bytes after `API_W`), with the comment "the trace's
state (docs/game-parts/tracel.md R1): `_g_trace`, `TR_LONG`, the
intercepts' count and the last one in, `IV_ON`, `IV_ML`/`IV_MH`,
`VT_INVB`'s bit 15". Local stand-in: `tracel.inc` puts them in
`SB_TRACEL` + 0 .. + 28, each marked "(stand-in R1)". With R1 the seven
lines of `tracel.inc` become `TL_TRACE = GM_TRACE`, `TL_TRLONG =
GM_TRLONG`, `TL_ICN = GM_ICN`, `TL_ICLAST = GM_ICLAST`, `TL_IVON =
GM_IVON`, `TL_IVM = GM_IVM`, `TL_INVB = GM_INVB` (no code changes;
`tracel.py` finds the places by their labels), and `SB_TRACEL` keeps
`TL_LD`, `TL_S1` (3 bytes: `TL_LD = TL + 0`, `TL_S1 = TL + 2`). Effect:
`tracet`, `path`, `attack`, `xymove` (the slide's traces) and `player`
(the use traces) name `GM_*`; nothing else moves.

**R2. The placement: the part's hot path in one group.** The shared
placement (from estimates) spreads the part over nine groups:
`PIT_AddLineIntercepts` 18, `lineCross` 24, `ivAxis` and `divlineSide`
26, `interceptVector3` and `addIntercept` 23, `ivTest` and `ivProd` 12,
`icInsert` 20, `ivSetup`, `gOf` and `vsC` 7, `smul` 2
(`build/native/game/tracel/gen/gplace.inc`), so one crossed line pays up
to five slot loads (`PIT_AddLineIntercepts` → `lineCross` → `ivAxis` →
`ivTest`, `addIntercept` → `icInsert`); the timings of section 3 are
routine mode with every slot empty at the call, an upper bound. Request,
in `tools/native/gplace.py` `AFFINITY`:

```
    ('p_trace65.s:PIT_AddLineIntercepts', 'p_trace65.s:lineCross',
     'p_trace65.s:ivAxis', 'p_trace65.s:interceptVector3',
     'p_trace65.s:ivTest', 'p_trace65.s:ivProd', 'p_trace65.s:addIntercept',
     'p_trace65.s:icInsert', 'p_trace65.s:vtxSlow',
     'p_trace65.s:divlineSide', 'p_trace65.s:vtxSlowR',
     'p_trace65.s:lineCrossL', 'p_trace65.s:icInsertL',
     'p_trace65.s:vtxSlowL'),
    ('p_trace65.s:ivSetup', 'p_trace65.s:gOf', 'p_trace65.s:smul',
     'p_trace65.s:vsC'),
```

The first is 2,110 B measured (2,089 with R3): slot 1 or the core, not
slot 2 (2,048); the second, 300 B, belongs with `tracet`'s `sideSetup`,
its only caller. `P_PointOnLineSide` (geom; group 18 today, with
`PIT_AddLineIntercepts`) is called twice for each line of a short trace.
Effect: placement only, no source changes.

**R3. The long-call wrappers inlined.** `vtxSlowL`, `lineCrossL`,
`icInsertL` are upstream's `jsl` entries of `vtxSlow`, `lineCross`,
`icInsert` [R `p_trace65.s:810`, `:1276`, `:1320`]; natively each is an
`FCALL` of its routine and `rts` (7 B, a call level, and with today's
placement a slot load). Request: `glayout.INLINED['tracel'] =
('p_trace65.s:vtxSlowL', 'p_trace65.s:lineCrossL',
'p_trace65.s:icInsertL')` with the native names `vtxSlow`, `lineCross`,
`icInsert` for them (`glayout.native_names`), so that `tracet`'s and
`path`'s `FCALL icInsertL` (`ptStuck`'s copies [R `p_path65.s:871`]) reach
`icInsert`; the part then deletes its three wrappers. Effect: `tracet`
and `path` may `FCALL` either name.

**R4. FixedDiv's inputs that upstream never returns from: a known
divergence counted in `GT_DIV0`.** Upstream's `fixedDiv` shifts b left
while b < a, signed [R `p_trace65.s:430-438`]; when b reaches 0 below a
it loops forever: FixedDiv(`$7FFFFFFF`, 1), FixedDiv(`$7FFFFFFF`,
`$40000000`), FixedDiv(-1, `$80000000`) (a num near 2^31 whose den's
doubling passes 2^31 first, or a den of -2^31). `tracel.py`'s model names
every such input; mathref ran the random checks' first ones 100,000,000
cycles each without a return (section 3). No game call met one: every
logged call of `interceptVector3` in the four runs returned. Natively the
result is `$7FFFFFFF` (C's `FixedDiv` for an overflow of one sign) and
`GT_DIV0` + 1, the port's rule for its own divides (`NATIVE.md` 15.1 row
5), so a tic-level run ends its comparison there (GAME.md 3.6 T8). Exact
change in `docs/GAME.md` 3.6, row T8's first cell: "A tic in which the
native divides by zero or meets the inputs `fixedDiv` of `p_trace65.s`
never returns from (docs/game-parts/tracel.md R4) (`GT_DIV0` counts)".
Effect: none on other parts; `ticgen.py`'s seed check (no division by
zero) covers it through `GT_DIV0`.

**R5. GAME.md 2.4 row `tracel` and risk 6: "built on milestone 6's
32-bit divide".** Upstream's `fixedDiv` is `p_trace65.s`'s own long
division (no runtime divide: `cal_integer.s` is not involved), with
signed 32-bit compares and shifts and a 16-bit `ibit`: for operands of
2^30 and more its shifts wrap and its results are not floor(a 2^16 / b)
(`$5F27B566` / `$3F76C68A` gives 0; the quotient is `$17FD5`), which no
`udiv32`-based divide gives. The part mirrors upstream's steps (the guard
"b < 2^30 and a < b" with the unsigned fast loop, else the signed loops),
the arithmetic rule of 2.4 for upstream's own helpers. Exact change in
the row: "(`P_InterceptVector3` with its `FixedDiv` and guards [R
`NATIVE.md` 3.2]: upstream's own long division of
`p_trace65.s:405-541`, mirrored; tracel.md R4, R5)", and in risk 6:
"`tracel`'s `FixedDiv` [R `p_trace65.s:237`, `:398-404`] is upstream's own
long division, mirrored step by step". Also `src/native/MATH.md` "Not in
this module", the row of `fixedDiv`: "on `udiv32`/`sdiv32`-style steps"
becomes "mirrored from `p_trace65.s` (part `tracel`)".

**R6. `gamecap.capture` of a routine entered by `JML`.** ref816's
`--capture` counts JSR, JSL and JSR (a,x) only, so
`PIT_AddLineIntercepts` (entered by `callLN`'s `JML [LN]` [R
`p_map65.s:2786`]) cannot be captured (ref816: "0 of the 22 calls to
capture came"). The part captures it at `callLN` (`tracel.py`
`CAPTURE_AS`): the same state and return, in the runs where every
`P_BlockLinesIterator` call is `ptBody`'s (demo3, demo1, newgame; demo2's
`avoidDropoff` calls interleave `PIT_AvoidDropoff`), so that callLN's
k-th call is `PIT_AddLineIntercepts`' k-th. Request: a note in
`src/native/game/README.md`, "Testing a part": "A routine entered by a
JML (`ITTAB`'s callbacks through `callLN`, `callLN2`; the `THTAB`,
`ACTTAB`, `TRVTAB` targets) is captured at the JSL'd stub that jumps to
it, in runs where the stub serves only that routine (part tracel's
`CAPTURE_AS`)". Effect: `chasemove`, `look`, `teleport` (the other
`ITTAB` callbacks) meet the same; `gamecap.capture` is unchanged.

**R7. The driver's area.** `tracelt.s` (the random checks' driver) is
687 B of the card's `DRIVER` area, which held 2,387 of 3,584 B with wave
1's: 3,074 with this part. If wave 2's drivers do not fit together, its
descriptor lists (194 B) can move to a spare bank, or the part trims
them on request. Effect: the integrated wave's driver area.

## 3. Results

All on a2vm against ref816, 2026-10-02, at 2 processes; the part's image
links wave 1's five parts (integrated) and this part.
`build/native/game/tracel/report.json` holds every number below.

**The routine checkpoint** (`tracel.py --run`): every chosen case from
both poisoned machines (`$A5`, `$5A`) under `f121` and `fastpath`, the
canonical state after the call (gcanon's routine mode, R1-R6 only), every
declared output (the intercepts: their count, each one's frac and line or
mobj, the chain walked from its head, `IC_LAST`; the trace's state; the
frac, the side, C), no stray write (a2vm's write log); 11,300 runs,
about 70 minutes.

| Entry | Survey calls | Cases (synthetic) | Runs | Failed | Stray | Cycles median / worst | f121 µs median / worst | fastpath µs | Lowest S |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---: |
| `PIT_AddLineIntercepts` | 18,256 (demo3, demo1, newgame: R6) | 316 (11) | 1,264 | 0 | 0 | 12,096 / 253,991 | 251 / 5,098 | 186 / 3,890 | `$D9` |
| `interceptVector3` | 10,889 | 300 | 1,200 | 0 | 0 | 37,933 / 40,727 | 751 / 797 | 581 / 627 | `$E3` |
| `divlineSide` | 568 | 300 | 1,200 | 0 | 0 | 21,400 / 21,911 | 426 / 434 | 329 / 337 | `$E6` |
| `addIntercept` | 14,711 | 304 (4) | 1,216 | 0 | 0 | 30,204 / 30,936 | 609 / 620 | 463 / 474 | `$E3` |
| `icInsert` | 14,769 | 302 (2) | 1,208 | 0 | 0 | 15,048 / 16,179 | 304 / 323 | 231 / 250 | `$E8` |
| `ivSetup` | 1,111 | 300 | 1,200 | 0 | 0 | 10,418 / 10,419 | 208 / 208 | 159 / 159 | `$E8` |
| block steps: `P_BlockLinesIterator` with `PIT_AddLineIntercepts` | 11,233 | 1,003 (3) | 4,012 | 0 | 0 | 252,776 / 940,535 | 5,089 / 18,887 | 3,867 / 14,405 | `$D1` |

- **The selection.** 300 spread evenly over each entry's calls (the
  block steps: 1,000 over all four runs, demo2's included), the last call
  of a run left out; every call eligible (no dispatch from the part's
  entries; the block steps' only target is `PIT_AddLineIntercepts`).
  Paths no chosen call takes: `PIT_AddLineIntercepts`' "behind" (a
  crossed line behind the trace's start) from its call log (`tracel.py
  --paths`: 5 calls added); its "long" (`divlineSide` on the vertices) and
  "axis" (`ivAxis` deciding in a shot) never occur in the runs (shots and
  long traces go through `tracet`'s `traceLines`): synthetic, 5 long
  traces and 4 shots; the full list (64): synthetic for
  `PIT_AddLineIntercepts`, `addIntercept` and the block steps (the
  callback stops the walk: A 0); the block steps off the map: synthetic,
  2. Every declared path of every entry is taken but `interceptVector3`'s
  "dl 0" and "FixedDiv never returns", and `divlineSide`'s "dx 0" and
  "dy 0", which no game call takes (every logged call, below) and the
  random checks take 63,341, 7,145, 80,221 and 79,491 times.
- **Synthetic: two intercepts of equal frac** (`addIntercept`: equal to
  `IC_LAST`'s, the search from it; equal to the chain's first, the search
  from the head; equal to two chained ones; `icInsert`: equal to
  `IC_LAST`'s and to the first): each case's entry state with the frac
  poked, run on ref816 alone (`--call`), the new one after the old ones,
  all equal natively.
- **The timings are upper bounds**: routine mode with every slot empty at
  the call, and the shared placement spreads the part over nine groups
  (R2): `ivSetup`'s 10,418 cycles are almost all its group's load. The
  block steps' worst is a block of many crossed lines in one call.

**Every captured input** (`tracel.py --logs`): every call of
`interceptVector3` (10,893: demo3 1,069, demo1 4,180, demo2 5,556,
newgame 88) and `divlineSide` (571) in ref816's call log of the four runs,
inputs and result, run natively: 0 failed; the model 0 different. No call
of the runs reaches FixedDiv's non-return (R4).

**The random checks** (`tracel.py --rand`, mathref's batch of upstream's
routine against the native one through `tracelt.s`, the edges first; the
model checked against both; 1 min 52 s):

| Routine | Inputs | Failed | The model different | Upstream never returns (the model's; confirmed on mathref) | Paths |
| --- | ---: | ---: | ---: | --- | --- |
| `interceptVector3` | 1,000,000 | 0 | 0 | 7,145 (6 of 6 confirmed; natively `$7FFFFFFF`, `GT_DIV0` 1: all) | both 669,905, dx 0 132,970, dy 0 133,784, dl 0 63,341; ivProd fast 144,921, slow 803,589; FixedDiv fast 179,090, slow 271,673; guards 0 21,148, signs 457,603 |
| `divlineSide` | 1,000,000 | 0 | 0 | 0 | products 498,733, signs 341,555, dx 0 80,221, dy 0 79,491 |
| `ivTest` (FixedDiv and its guards) | 300,000 (144 edge pairs; b around 2^30, a around b, a around b 2^k) | 0 | 0 | 2,515 (6 confirmed; native all right) | fast 74,523, slow 194,768, 0 11,264, signs 16,930 |
| `ivAxis` | 100,000 | 0 | 0 | 0 | decided 26,360 |
| `ivProd` (arithmetic helper) | 100,000 | 0 | 0 | 0 | fast 15,009 (n's edges -4097..4097), slow 84,991 |
| `smul` (arithmetic helper) | 100,000 (25 edge pairs) | 0 | 0 | 0 | |
| `ivSetup` | 100,000 | 0 | 0 | 0 | |
| `gOf` | all 65,536 | 0 | 0 | 0 | |
| `vsC` | 100,000 | 0 | 0 | 0 | |

**The planted bugs** (each in a scratch copy, `tracel.py`'s `PLANTS`;
`tests/test_native_game_tracel.py`'s `TestPlants`):

| Plant | The check | Caught |
| --- | --- | --- |
| FixedDiv's guard one off (`cmp #$41` for "b < 2^30") | random `ivTest` | 5,081 of 300,000 (FixedDiv(`$40000000`, `$40000001`): upstream 0, the plant `$FFFF`) |
| the fast product path deciding where upstream's does not (n up to 4,351 taken as -4096..4095) | random `ivProd` | 213 of 100,000 |
| an equal frac inserted before the old one | synthetic, equal fracs | 3 of 6 (the chain `[3, 0, 1, 2]`, upstream `[0, 3, 1, 2]`) |

**Sizes** (`tracel.py`'s `sizes`, the map's module list): 2,410 B of 2,800
(upstream 2,136): `PIT_AddLineIntercepts` 131, `interceptVector3` 283,
`divlineSide` 315, `addIntercept` 70, `icInsert` 177, `ivSetup` 93,
`ivTest` 387 (with `fixedDiv`), `ivProd` 150, `ivAxis` 416, `lineCross`
107, `vtxSlow` 39, `vtxSlowR` 14, `vtxSlowL`, `lineCrossL`, `icInsertL` 7
each, `gOf` 26, `smul` 38, `vsC` 143. The test driver `tracelt.s`: 687 B in
the card's driver area (R7). The build: no warnings.

**The test module** (`python3 -m unittest tests.test_native_game_tracel`):
9 tests, 496 s at 2 processes (every 5th case, `TRACEL_SAMPLE`; the random
checks in full; every logged call; the three plants).

**build/ growth**: 107 MB (`build/native/game/tracel/`: the cases 88 MB,
the upstream results' cache of the random checks 4.4 MB, `run.json` 4.4
MB, the image 6 MB); every temporary directory deleted.

**Commands**:

    make -s -C src/native -f game.mk part P=tracel ROOT=$PWD
    python3 tools/native/gparts/tracel.py --select --paths --capture --synth
    python3 tools/native/gparts/tracel.py --run --logs --rand --report --jobs 2
    python3 -m unittest tests.test_native_game_tracel

## 4. Open points

- R1-R7 wait for the integrator; until R1 the trace's state is in
  `SB_TRACEL`, so `tracet` and `path` (waves 3, 4) import `TL_*` from this
  part or wait for `GM_*`.
- `PIT_AddLineIntercepts` is captured only in demo3, demo1 and newgame
  (R6); demo2's calls run inside the 480 demo2 block steps.
- No run reaches `PIT_AddLineIntercepts`' long-trace and shot paths, the
  full list, or FixedDiv's non-return: they are checked by synthetic
  cases and the random checks only; the generated streams (GAME.md 3.7)
  may reach them.
- The timings are with the estimated placement (R2); the integrator's
  `gplace.py --measure` gives the real ones.

## 5. The integration of wave 2 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 2 as integrated").

| Request | Decision |
| --- | --- |
| R1 the trace's state in GW | **Accepted**: `glayout.TIC_GW_FIELDS` `GM_TRACE` (16), `GM_TRLONG`, `GM_ICN`, `GM_ICLAST`, `GM_IVON`, `GM_IVM` (8), `GM_INVB` after `API_W` (`$B302-$B31E`); `tracel.inc`'s `TL_*` are those names; `SB_TRACEL` keeps `TL_LD` (+0) and `TL_S1` (+2) |
| R2 the placement | **Accepted in part**: `gplace.AFFINITY` keeps the crossed line's path (`PIT_AddLineIntercepts`, `lineCross`, `ivAxis`, `interceptVector3`, `ivTest`, `ivProd`, `addIntercept`, `icInsert`: 1,721 B) in one group, with `P_PointOnLineSide` (group 9, slot 1); the long trace's vertex sides (`vtxSlow`, `divlineSide`, `vtxSlowR`, 368 B) are a unit of their own: the whole 2,089 B passes slot 2's 2,048, at which `gplace.py` cuts every group, and slot 1 is 2,048 B too since this integration (the core took 512 B of it for the game's math, `damage.md` R1). `ivSetup`, `gOf`, `smul`, `vsC` are a unit (300 B), for `tracet`'s `sideSetup` to join |
| R3 the wrappers inlined | **Accepted, without aliases**: `glayout.INLINED['tracel']` = `vtxSlowL`, `lineCrossL`, `icInsertL`; the three wrappers are gone from `tracel.s`. Native-name aliases (two keys, one label) would give `gplace.inc` two definitions of one `GP_` name, so a caller `FCALL`s `vtxSlow`, `lineCross`, `icInsert` itself (README, `tracet.md`, `path.md`); `tests/test_native_game_tracel.py`'s export check skips the inlined |
| R4 `fixedDiv`'s non-returns in `GT_DIV0` | **Accepted**: GAME.md 3.6 T8 names them |
| R5 the texts of `fixedDiv` | **Accepted**: GAME.md 2.4's row and risk 6, `MATH.md` "Not in this module" |
| R6 capturing a JML-entered routine | **Accepted**: README "Testing a part" |
| R7 the driver's area | No change needed: wave 2's image holds 3,186 + 61 of 3,584 B (`tracelt.s` 687, `sptest.s` 112; `dtest.s` only in damage's own image) |

The far-access grep (`gameroutine.grep_check`) flags `tracelt.s`'s
`far_get`/`far_put` of `t_bank` (its own record banks 93-97, test-only
code in the driver's area, not a game kind's): outside the rule, as the
README now says; `tracel.s` is clean.

## 6. The final integration (2026-10-02)

The integrator changed this part's fragment: `part.mk` links
`tracelt.s` (the random checks' test driver, 687 B in the driver's area)
only with `TL_TEST=1`, which `tools/native/gparts/tracel.py`'s `build()`
passes, as spawn's `sptest.s` at wave 6. Why: the lockstep driver's
tic-level additions (the stream, the frames, `TICLEVEL`) left the game
image's area 38 B short with every part's test code linked. The part's
own image, its checks and its plants are unchanged (`make -f game.mk
part P=tracel TL_TEST=1` links it as before: `$E000-$EC77`).
