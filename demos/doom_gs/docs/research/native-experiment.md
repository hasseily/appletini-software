# Native 65C02 against upstream's 65816: three routines measured

Date: 2026-09-30. Status: experiment done; nothing here is committed code.

The owner's direction is a full native 65C02 rewrite. Every estimate of that
rewrite needs one number first: how much larger and slower is hand-written
65C02 code than upstream's 65816 code for the same work? This note measures
it on three routines, on real inputs captured from the release.

Every claim is marked **measured** (I ran it), **read** (file:line) or
**assumed**. Upstream paths are under `build/upstream/src/iigs/`.

## Summary

| Routine | Bytes, 65816 | Bytes, 65C02 | Cycles a call, 65816 | Cycles a call, 65C02 | 65C02 / 65816 cycles | a2vm time, 65C02 (f121 = fastpath) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| (a) Seg column loop `v28`, one column | 213 | 194 | 252.7 still, 245.0 demo | 241.3 still, 233.9 demo | 0.95 | 4.04 µs still, 3.90 µs demo |
| (b) 16 x 16 to 32 unsigned product (`qmul`) | 102 (+512 KB tables) | 114 (+2 KB tables) | 86.4 | 211.8 | 2.45 | 3.82 µs |
| (b) the same product (`umul16`) | 106 | 114 | 98.4 | 208.0 | 2.11 | 3.68 µs |
| (c) `calcHeight` (P_CalcHeight) with all it calls | 1,037 | 1,205 | 1,625 still, 1,778 demo | 875 still, 2,116 demo | 0.54 still, 1.19 demo | 14.4 µs still, 35.8 µs demo |

All measured. The outputs of the native code were identical to upstream's
on every captured call: 6,496 products, 258 calls of `calcHeight`, and 828
seg loops (8,533 columns, 18,732 callee calls with their arguments).

In one line: **8-bit code costs the same or a little less on the 65C02; 16-
and 32-bit arithmetic costs 1.2 to 1.3 times more; the 16 x 16 multiply
costs 2.1 to 2.5 times more**, because the 65C02 cannot use upstream's 512 KB
of 16-bit quarter-square tables.

The cost model gives the same time in both firmware profiles for all three.
This is expected: the experiment keeps all code and data in fast memory, and
the two profiles differ only for RamWorks, bus cycles and SHR stores. A port
pays those costs separately (see "What they do not represent" below).

## How it was measured

All tools and derived code are in `build/native-experiment/` (ignored by
git; the native code is translated from GPL-2 code). `run_experiment.sh`
redoes everything in about 17 seconds.

| Step | Tool | What it does |
| --- | --- | --- |
| Call counts and heat | `capture.c` (links `tools/ref816` unmodified), `calls.py`, `heat.py` | Runs the release on ref816's IIgs under `coverage/newgame.script` (notes `still` to `still-10s`, 25 frames) and `coverage/title.script` (`demo` to `demo-25s`, 41 frames). Counts every JSR/JSL by target with inclusive cycles, and cycles and instructions per address, with the share run with a 16-bit accumulator. Interrupt cycles are excluded. |
| Inputs and outputs | `capture.c --capture ADDR` | For each call of a routine: registers in and out, every data byte it read before writing it, every byte it wrote, its 65816 cycles and instructions (from the first instruction through the RTS/RTL; the caller's JSL is not counted). Calls with an interrupt inside are dropped (5 of 6,759). |
| Seg loop | `capture.c --seg` | For each run of the `v28` loop: the whole loop page and both clip arrays at entry and at exit, the cycles and instructions spent in the loop's own code, and each callee call with the loop page at the call and what the callee changed. |
| Native code | `native/*.s`, ca65 and ld65 of cc65 2.18 | Hand-written 65C02 with 65C02 data layouts (below). Test drivers feed the captured inputs. |
| Exact 65C02 cycles | `run02.c` | a2vm's W65C02S core (`tools/a2vm/cpu65c02.c`, unmodified) on flat memory; the cycles of each call, from the first instruction through the RTS, as on the 65816 side. |
| Time on the target | `build/a2vm/a2vm --core w65c02s` with `--cost` f121 and fastpath | The same binaries; outputs compared again from the final snapshot; time from `--cost-phase`: the driver sets phase 1 around each call. |

The a2vm times of (b) and (c) include the caller's JSR (6 cycles, about 0.1
µs). For (a) the stub callees switch the phase back, which would count their
own RTS; so (a)'s time is its measured clocks per cycle (2.23 standing still,
2.22 in the demo, from a variant whose callees are a bare RTS) times the
loop's own cycles. **Measured.**

The 65816 cycles are those of ref816's ideal 65816 (no wait states,
`tools/ref816/README.md`); a real IIgs takes longer. **Read.**

## (a) The seg column loop

**What.** `v28`: the loop of a single-sided wall with ceiling and floor
marks, one of the 14 loops made from `segvar.inc` (instantiated at
`r_seg65.s:3980`; its body `segvar.inc:27-246`). In the full view,
`c17Mode` (`r_seg65.s:5216`) patches its texture call to `texCol`. **Read.**
It is the most drawn single-sided kind: 159 columns a frame standing still
(3.5% of the frame's cycles), 111 in the demo (1.6%; the most of any loop
there). All the `vNN` loop bodies together are 12.3% standing still and 4.9%
in the demo. **Measured.**

**Scope.** The loop's own work per column: the clips, the three edge steps,
the row clamps, and the choice of which callee to call with what. The
callees (`ceilFill`, `floorFill`, `texCol` and the tier code it continues
into, `genColumn`) are not translated; on both sides their cycles are
excluded and the JSR to them is included. The native driver's stubs log the
column and eleven loop-page bytes at each call, and the check compares them
with upstream's loop page at the same call. Bytes a callee changed are
masked for the rest of that column (1,402 of 206,052 compared loop-page
bytes, demo only; the loop never reads them before rewriting them, and the
steps and clips at the end match). **Measured.**

**Native layout.** The loop page stays in zero page at upstream's offsets
(`wpage.inc`). The column in X is a byte, not twice the column, and the two
clip arrays are 160-byte arrays indexed by the column (upstream: 16-bit
entries with a zero high byte). **Assumed** to be what a native renderer
would use.

| Per column | 65816 | 65C02 |
| --- | ---: | ---: |
| Cycles, standing still (3,985 columns) | 252.7 | 241.3 |
| Cycles, demo (4,548 columns) | 245.0 | 233.9 |
| Instructions, standing still | 86.7 | 83.5 |
| Time | 88 µs on a 2.86 MHz IIgs (ideal) | 4.04 µs standing still, 3.90 µs demo, both profiles |
| Code bytes | 213 (plus 10 bytes of padding) | 194 |

**Why.** The loop is already 8-bit code (0.9% of the loop bodies'
instructions run with a 16-bit accumulator). Every instruction maps one to
one, and the 65C02 version saves about 11 cycles a column from: clip arrays by `abs,X` instead
of `long,X` (one byte and up to one cycle less each, four a column); an
8-bit index (one `INX` and an 8-bit compare instead of two `INX` and a 16-bit
compare); `STZ abs,X`; and no `REP` before the texture call. **Measured**
(counts) and **read** (the listing).

## (b) The 16 x 16 multiply

**Which.** No routine called `FixedMul` is hot: it runs 1 to 6 times a
frame. The most-called multiply is `qmul` (`r_wall65.s:1732`), the unsigned
16 x 16 to 32 product of the wall setup: 277.5 calls a frame standing still
(2.1% of the cycles), 212.5 in the demo. `umul16` (`m_fixed65.s:219`) is the
same product for the game logic and the other callers: 32 calls a frame
standing still, 144 in the demo. **Measured.** Both look up 16-bit quarter
squares in the tables `SQL` and `SQH`, 256 KB each (`m_fixed65.s:44-53`).
**Read.** Counting the table reads of all products, inlined ones included,
gives about 485 products a frame standing still and 530 in the demo.
**Measured.** No part of `cal_integer.s` was read; neither routine calls it.

**Native layout.** Quarter squares of bytes: four 512-byte tables (f(n)
and f(n - 255), low and high bytes), 2 KB in fast memory. A 16 x 16 product
is four 8 x 8 products through eight zero-page pointers whose high bytes
never change, then the carries. One native routine serves both captured
sets.

| Per call | 65816 `qmul` | 65816 `umul16` | 65C02 `umul16` |
| --- | ---: | ---: | ---: |
| Cycles, mean (range) | 86.4 (83-88) still, 85.6 (83-89) demo | 98.4 (97-101) still, 98.1 (96-102) demo | 211.8 to 212.3 (204-224) on `qmul`'s inputs, 208.0 to 208.9 (204-223) on `umul16`'s |
| Instructions | 27.6 | 29.5 | 59.7 |
| Time | 30 µs on a 2.86 MHz IIgs | 34 µs | 3.68 to 3.84 µs, both profiles |
| Code bytes | 102 | 106 | 114 |
| Tables | 512 KB (`SQL`, `SQH`) | same | 2 KB |

The cases: 1,734 and 2,000 `qmul` calls, 800 and 1,962 `umul16` calls
(standing still and demo), all identical. **Measured.**

**Why.** Upstream's product is two lookups of 16-bit squares plus 16-bit
subtractions. The 65C02 needs four byte products (16 byte lookups) and a
carry chain: 2.2 times the instructions, 2.1 to 2.5 times the cycles. The
65C02 cannot use upstream's method: 512 KB does not fit in fast memory
(about 90 KB), and each lookup in RamWorks would be a PSRAM line miss
(131 clocks today, about 35 with the firmware design;
`tools/a2vm/README.md:439`), which
is more than the whole native product (about 510 clocks). **Measured** (the
ratio) and **assumed** (that no better 65C02 method exists; published 6502
16 x 16 quarter-square routines are of the same order, about 190 to 200
cycles, not measured here).

## (c) A game-logic routine every tic: P_CalcHeight

**What.** `calcHeight` (`p_user65.s:378`, falling into `viewCeiling` at
`:526`) runs once a tic for the player: the bob from the squared momentum
(`fixedSquare`, `:548`, through `umul16` and `_Mul32`), the view bob
through `finesine` and `FixedMulAngle` (`p_mobj65.s:1213`, then
`FixedMul3216`), the view height and its delta, and the ceiling clamp.
**Read.** It runs 4 times a frame (0.57% of the cycles standing still,
0.40% in the demo). **Measured.** It is short but typical of the game code:
32-bit fixed-point adds, signed compares, products and a table.

**Native layout.** The player is one record at a fixed address with 32-bit
little-endian fields; playerstate and onground are bytes; the mobj is
reached through a zero-page pointer. The sine is two 8 KB magnitude planes
(low and high bytes, 16 KB); its sign is bit
12 of the angle (corrected after review: the cosine's sign is bit 12 of
x + 2048, not of x, and the cosine equals the shifted sine except on 12
entries, so cosine = shifted sine plus a 12-entry exception list), because the table is at least 0 in its first half and at
most 0 in its second (**measured** on the table in the game's RAM; the table
is not symmetric within a half, so a quarter table would not be exact).
Products use the 2 KB tables of (b), with a squaring routine of three byte
products, an 8 x 16 routine for the small high words, and skips when a
factor is zero. The angle `(leveltime * 409) & 8191` takes two constant
byte products (409 = 256 + 153).

| Per call | 65816 | 65C02 |
| --- | ---: | ---: |
| Cycles, standing still (100 calls, all on the ground, not moving) | 1,625 (1,601-1,649) | 875 (875-877) |
| Cycles, demo (158 calls, all on the ground and moving) | 1,778 (1,647-1,887) | 2,116 (1,341-2,514) |
| Instructions, standing still / demo | 434 / 482 | 269 / 632 |
| Time | 567 µs / 621 µs on a 2.86 MHz IIgs | 14.4 µs / 35.8 µs, both profiles |
| Code bytes, the routine's own | 486 (`calcHeight`, `viewCeiling`, `fixedSquare`) | 956 |
| Code bytes, with everything it calls | 1,037 | 1,205 |
| Tables | 40 KB of sine; 512 KB of squares | 16 KB of sine; 2 KB of squares |

The outputs compared: the player's bob, viewz, viewheight and
deltaviewheight. **Measured.**

**Why.** When the player moves, the native code is 1.19 times slower and
runs 1.31 times the instructions: every 32-bit add, compare or copy is four
byte operations instead of two word operations, and each 16 x 16 product
costs 2 to 2.5 times more. Standing still, it is 1.9 times faster, because it
skips the products of zero, which upstream computes. Its own code is twice
upstream's, since it inlines the 32-bit work that upstream shares with other
routines; with the callees counted, 1.16 times. **Measured.**

## How representative the three are

The share of the frame's 65816 cycles, and of its instructions run with a
16-bit accumulator, by kind of code (**measured**, from the heat of the two
scenarios):

| Code | Cycles, still | Cycles, demo | 16-bit A, still | 16-bit A, demo | Nearest routine here |
| --- | ---: | ---: | ---: | ---: | --- |
| Record replay (`r_list65.s`, `drawcol.s`) | 34.1% | 41.8% | 4.1% | 1.7% | (a) in kind; its real cost is far reads and SHR stores |
| Seg loop bodies (`vNN` of `segvar.inc`) | 12.3% | 4.9% | 0.9% | 1.2% | (a) |
| Rest of `r_seg65.s` (texture columns, records, fills, sprite posts) | 22.2% | 10.4% | 61.7% | 62.4% | (c) in kind, with inlined products of (b) |
| `r_wall65.s` (wall setup) | 10.6% | 4.5% | 95.7% | 96.5% | (b), (c) |
| `r_bsp65.s` (BSP walk) | 6.5% | 2.6% | 100% | 100% | (c) in kind, plus pointer chasing in far data |
| Game logic (`p_*.s`, `g_*.s`) | 3.9% | 19.7% | 62.5% | 81.5% | (c) |
| `m_fixed65.s` | 0.7% | 1.5% | 100% | 100% | (b) |
| Everything else | 9.7% | 14.7% | 58.2% | 61.8% | none |
| **All** | | | 39.4% | 40.0% | |

So the three span the two kinds of code the frame is made of: about 46% of
the cycles are 8-bit loops like (a), about half is 16-bit code like (c), and
products are 4% or less (485 to 530 a frame at about 86 cycles).

What they do not represent:

- **Far data.** Upstream reads far data with long addresses for one extra
  cycle; the target pays a bank switch or a RamWorks line miss. All three
  kept their data in fast memory. The BSP walk, the wall setup and the replay
  are where this matters (29,949 far accesses a frame outside the replay
  standing still, 47,345 in the demo; `PROFILE.md:737`).
- **SHR stores.** Only the replay writes the screen; its drain (131.3
  fabric clocks, about 0.98 µs, a byte; `tools/a2vm/README.md:441`) is not
  in these numbers.
- **The seg loop's callees** (22.2% standing still): `texCol` and the record
  making are 16-bit code with inlined products. By their instruction mix
  they should behave like (c), not (a). **Assumed.**
- **Self-modifying overlays.** Upstream patches its loops by view size and
  per seg (`c17Setup`, `r_seg65.s:5178`); the native loop has none, as it
  runs in the full view only. A native renderer needs its own versions for
  the other view sizes (**assumed**).
- One loop of 14, one multiply form of several (`MULLO16` needs only three
  byte products, so its ratio should be lower; **assumed**), one game-logic
  routine.

## What this means for estimates

Factors to use, 65C02 cycles for 65816 cycles (**measured** on these
routines; applying them to whole classes is **assumed**):

| Kind of code | Cycles | Code bytes |
| --- | ---: | ---: |
| 8-bit loops (replay, seg loops, drawers) | 0.95 | 0.9 |
| 16/32-bit arithmetic and control (game logic, BSP, wall setup, texture columns) | 1.2 to 1.3 (0.5 when zero operands can be skipped) | 1.2 with shared helpers, 2 inlined |
| 16 x 16 products | 2.1 to 2.5 | 1.1, tables 1/256 |

A rough frame, standing still (**assumed**, from the table above: 46% at
0.95, 4% at 2.45, 50% at 1.19 to 1.31): the native frame is about 1.1 to 1.2
times upstream's 1,123,634 cycles, about 1.3 million 65C02 cycles. At the
2.2 to 2.3 fabric clocks a cycle measured here in fast memory, that is about
21 to 23 ms of CPU time a frame, before far accesses and SHR drains. The demo
gives the same factor on 1.6 million cycles: about 30 ms.

Against the interpreter of `src/vm` (5.3 to 5.7 µs a 65816 instruction today,
4.4 to 4.6 µs with the firmware design; `MILESTONES.md:353-356`), the native
code is
38 to 41 times faster on the product (27.6 instructions against 3.8 µs), 71
to 77 times on `calcHeight` moving, and 114 to 122 times on a seg column,
with today's interpreter figures. **Derived** from the measured instruction
counts and native times.

## Limits

- The native code was written for this experiment in a few hours: correct
  on every case, reasonably tuned, not exhaustively. The ratios are upper
  bounds for competent code, not lower bounds.
- (a) excludes the callees. Its time on a2vm is its measured clocks per
  cycle times its cycles; the other two include the caller's JSR.
- The a2vm binary is `build/a2vm/a2vm` as built at 00:37 on 2026-09-30,
  with the parameter profiles of `tools/a2vm/costs/appletini.json`; its
  costs are derived from the RTL, not measured on the card (milestone 0).
- Standing still, `calcHeight` sees only zero momentum; the demo's 158 calls
  are all on the ground and moving. Neither scenario covers a jump or death.
- 65816 figures are ref816's ideal cycles, not a real IIgs's.

## Files

In `build/native-experiment/` (not in git):

| File | What |
| --- | --- |
| `run_experiment.sh` | Redoes everything |
| `capture.c`, `Makefile` | The capture harness on ref816's machine |
| `run02.c` | Exact 65C02 cycles per call on a2vm's core |
| `mkinput.py`, `calls.py`, `heat.py`, `sizes.py`, `capfile.py` | Inputs, call counts, heat, upstream sizes, capture reader |
| `mulcases.py`, `mulrun.py`, `calcrun.py`, `segrun.py`, `nativerun.py` | Cases, runs on run02 and a2vm, comparisons |
| `native/mul.s`, `native/calc.s`, `native/v28.s` | The native routines |
| `native/*_test.s`, `native/code.cfg`, `native/gen_tables.py` | Drivers, link config, square tables |
| `results-*.json` | The numbers of this note |
