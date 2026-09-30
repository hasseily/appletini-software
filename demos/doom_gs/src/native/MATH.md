# The native math (milestone 6)

The 65C02 math of the port: [`math.s`](math.s), with
[`math.inc`](math.inc). Milestone 6 of
[`docs/NATIVE.md`](../../docs/NATIVE.md) section 13, item 3; the
arithmetic rules are its section 3. Every routine is bit-exact with
upstream's, checked on a2vm against upstream's routine run on ref816 on a
million random inputs, the edges, and every input the coverage runs gave
it; the divides are the port's own (the owner's decision 5, `NATIVE.md`
15.1) and are checked against C semantics. It is a GPL-2 derivative of
upstream's `m_fixed65.s`, `m_recip65.s`, `tables65.s`, `m_random65.s`,
`r_iigs65.s`, `r_wall65.s`, `p_mobj65.s` and `p_path65.s`. Nothing comes
from upstream's `cal_integer.s`: the divides were written from the call
sites and C only, pass the C model on their own, and the vendor divides
are never compared directly (their calls are logged for their inputs
only). One indirect comparison remains: upstream's `R_PointToAngle3`
(`r_iigs65.s:1134`) and `slopeOld` (`r_iigs65.s:410`, under
`R_PointToAngle16` and `pointAngle`) call `_UDivMod32`, and the native
`pta3`, `pta16` and `pta16p`, which call `udiv32`, are compared bit-exact
with them. So `udiv32`'s quotient meets the vendor divide's inside those
routines, on the inputs they give it and clamped at 2048 (see
Verification and the owner's question there).

## The routines

Operands in `M_A` and `M_B`, results in `M_R` (and the remainder in
`M_T`), little-endian, in the math block of zero page (below). Each
routine's comment in `math.s` lists what else it changes.

| Native | Upstream | Does | In | Out |
| --- | --- | --- | --- | --- |
| `umul16` | `umul16`, `_Mul16`, `qmul` | unsigned 16 × 16 → 32 | `M_A`, `M_B` (16) | `M_R` (32) |
| `umul16lo` | `umul16lo`, `IIGS_MulLo16` | the low word of the same | `M_A`, `M_B` (16) | `M_R` (16) |
| `mul8` | the byte products of `mul.inc` (a macro upstream) | 8 × 8 → 16 | A, Y | `M_R` (16) |
| `mulw` | | the word in the slots × X:Y (the core of the others) | slots, X, Y | `M_R` (32) |
| `qmulh` | `qmulh` (`r_wall65.s`) | the high word of a product, **or 1 more**, exactly as upstream (below) | `M_A`, `M_B` (16) | `M_R` (16) |
| `mul32` | `_Mul32` | 32 × 32 → the low 32 bits | `M_A`, `M_B` | `M_R` |
| `fixmul` | `FixedMul`, `FixedMul3232` | floor(a b / 65536) mod 2^32, exact | `M_A`, `M_B` | `M_R` |
| `fixmul3216` | `FixedMul3216` | the same with b the unsigned low word | `M_A`, `M_B` (16) | `M_R` |
| `fixmulang` | `FixedMulAngle` (`p_mobj65.s`) | `FixedMul3216(a, b & $FFFF)`, minus a when b < 0 | `M_A`, `M_B` | `M_R` |
| `udiv16`, `udiv32` | for `_UDivMod16`, `_UDivMod32` | unsigned quotient and remainder | `M_A`, `M_B` | `M_R`, `M_T` |
| `sdiv16`, `sdiv32` | for `_Div16`, `_Mod16`, `_Div32` | signed, C semantics | `M_A`, `M_B` | `M_R`, `M_T` |
| `recip` | `FixedReciprocal` | 0xFFFFFFFF / v with 16 significant bits (`RECIP_TABLE`) | `M_A` | `M_R` |
| `recipsmall` | `FixedReciprocalSmall` | the same of a 16-bit v | `M_A` (16) | `M_R` |
| `recipbig` | `FixedReciprocalBig` | the same for v ≥ $10000 (16-bit result) | `M_A` | `M_R` |
| `approxdiv` | `FixedApproxDiv` | a × the reciprocal of b, upstream's two paths | `M_A`, `M_B` | `M_R` |
| `aproxdist` | `P_AproxDistance` | dx + dy − min/2 with its rounding | `M_A`, `M_B` | `M_R` |
| `pta3` | `R_PointToAngle3` (the game's `R_PointToAngle2`) | the angle of (x, y), `SlopeDiv` and `tantoangle` | `M_A`, `M_B` | `M_R` |
| `pta16` | `R_PointToAngle16`, `pointAngle` | the renderer's 16-bit angle of (x, y) from (viewx, viewy) | `M_A` (x, y), `M_B` (viewx, viewy), 16 bits each | `M_R` (16) |
| `finesine`, `finecosine` | `finesine`, `finecosine` | Doom8088's tables, all 8,192 entries | `M_A` (0-8191) | `M_R` |
| `sineapprox`, `cosineapprox` | `finesineapprox`, `finecosineapprox` | the quarter table, mirrored and negated | `M_A` (16) | `M_R` |
| `prandom`, `mrandom`, `mclearrandom` | `P_Random`, `M_Random`, `M_ClearRandom` | `rndtable[++index]`, a byte index each | | A |
| `mt_init` | | the square pointers' high bytes: once, before any product | | |
| `mt_far`, `mt_recipe` | | the RamWorks table reads (RAMRD windows) | | |

### What is exact, and upstream's quirks kept

All of it reproduces upstream, quirks included (`NATIVE.md` 3.2 and 3.3;
the owner's decision 3 keeps the renderer's arithmetic exact):

- **`qmulh`** is upstream's `sq(a + b) − sq(|a − b|)` from the high words
  of the quarter squares only: the high word of a b, or 1 more. Natively
  that is the exact product plus the carry of lo(a b) + lo(sq(|a − b|)),
  with lo(sq(d)) = f(dl) + ((dh dl) mod 512) << 7 + (dh & 1) << 14. So
  the native `qmulh` costs more than the exact product, where upstream's
  costs less (two table reads for four); a faster inexact form would
  change frames, and is a later option under a waiver (`NATIVE.md` 3.3).
- **`FixedMul3216` and `FixedMulAngle`** use only the low word of b
  (`NATIVE.md` 3.2): not `FixedMul`.
- **`FixedApproxDiv`** takes its small path for a b whose high word is 0
  *or negative* (a signed compare in the C), with b's low word only.
- **`R_PointToAngle16`** has two paths upstream: a fast one for deltas in
  −16384..16384 and `pointOld` otherwise, with signed 16-bit compares
  (so −(−32768) stays $8000, negative) and `slopeOld`. For num > den,
  `slopeOld` builds the dividend of `n << 11` with the high word
  **n >> 13** where it should be n >> 5 (`r_iigs65.s`, `slopeOld`, `80$`:
  `xba`, `and`, five `lsr`). The native `pta16` does the same; the
  checks found it (the first host model did the C's shift and disagreed
  with upstream on 91 of 3,962 inputs, all with a delta of −32768).
- **`R_PointToAngle3`**: `SlopeDiv` is `(uint16_t)((num << 3) / (den >>
  8))`, the shift modulo 2^32 and the quotient's low word, at most
  2048; |x| of −2^31 stays −2^31, and the octant compare is signed.
- **`P_AproxDistance`**: labs in 32-bit two's complement, a signed
  compare, an arithmetic shift.
- **`finecosine`** is not the shifted sine on 12 entries (x = 6214,
  6258, 6599, 6773, 6775, 6915, 7007, 7211, 7277, 7403, 7417, 7971):
  `mathtables.py` finds them in the reference's table and the routine
  checks that list first.
- **`P_Random`**: upstream reads a 16-bit word at `rndtable + index` and
  masks the byte after the table off; the index is a byte natively.

### The divides: C semantics, and division by zero

Written from the 46 call sites (`research/native-modules.md` 4.2) and C11
6.5.5 only: the quotient truncated toward zero, the remainder with the
dividend's sign, `(a / b) * b + a % b == a`. What C leaves undefined, the
port defines:

| Case | Unsigned | Signed |
| --- | --- | --- |
| x / 0 | quotient all ones ($FFFF, $FFFFFFFF), remainder x | quotient the largest value of x's sign: $7FFF / $7FFFFFFF for x ≥ 0, $8000 / $80000000 for x < 0; remainder x |
| INT_MIN / −1 | | quotient INT_MIN (the two's complement wrap), remainder 0 |

The coverage runs never divide by zero: 0 of the 17,842 calls of the
vendor divides logged in `newgame`, `title`, `tour` and `viewsize` (28
call sites) have a zero divisor, nor does any angle routine reach its
own `den` of 0 except through its defined `SlopeDiv` rule. So the port's
definition never changes a coverage run (`NATIVE.md` 15.1, row 5).

## Where it lives

The map of [`docs/MEMORY_MAP.md`](../../docs/MEMORY_MAP.md), and what
this build adds to it (**new** rows are proposals for the map's owner):

| What | Where | Bytes |
| --- | --- | ---: |
| Quarter squares f(n) and f(n − 255), low and high bytes, 512 each | main card bank 1 `$D000-$D7FF` (MEMORY_MAP 4.2) | 2,048 |
| The products (`MATHLC`): `mt_init`, `umul16`, `mulw`, `umul16lo`, `mul8`, `qmulh`, `fixmul`, `fixmul3216`, `fixmulang`, `mul32` | bank 1 `$D800-$DBFF` (MEMORY_MAP 4.2: "16 × 16 multiply, FixedMul family, divides") | see Results |
| The table reads (`MATHFAR`): `mt_far`, `mt_recipe`. They run with RAMRD on, so they must be in the card; they are "the RamWorks table lookup" of the far layer's `$DC00-$DFFF` | bank 1 `$DC00-` | see Results |
| The rest (`MATHW`): the divides, reciprocals, `FixedApproxDiv`, `P_AproxDistance`, the angles, sines, random numbers, the cosine's exceptions | a code window of main memory (W), loaded with the phase that calls them: the tic window, the render window | see Results |
| `rndtable` (`MATHRND`) | W, page aligned | 256 |
| **new** The math block: the square pointers (8 × 2 bytes; their high bytes are set once by `mt_init`), `M_A`, `M_B`, `M_R`, 12 temporaries (`MT`, `M_T`, `MT_E`, `MT_P`) | zero page `$B0-$D7`, the top 40 bytes of overlay 2 (MEMORY_MAP 2). Every phase that calls the math keeps it for the math; the replay (`$48-$6F`) and the IRQ (`$D8-$FF`) do not touch it | 40 |
| **new** `P_Random`'s and `M_Random`'s indexes | main `$03EE`, `$03EF` (the persistent globals, MEMORY_MAP 3.1) | 2 |
| **new** The math tables bank (`MT_TBANK`, 120): sine magnitude planes `$2000`, `$4000` (8,192 each); `tantoangleTable`, 2,049 entries, 4 byte planes at `$6000` + 9 pages each; `finesineTable_part_1`, 2,048 words, planes `$8400`, `$8C00` | RamWorks (MEMORY_MAP 7: "tables bank ... sine 16 KB, finesine part 1") | 30,724 |
| **new** `RECIP_TABLE` low and high planes, 32,768 each | RamWorks banks 121 (`MT_RLO`) and 122 (`MT_RHI`), `$2000-$9FFF` | 65,536 |

- **The sine** is 16 KB of magnitude planes, the sign bit 12 of x: the
  scheme of `NATIVE.md` 3.1, checked by `mathtables.py` on all 8,192
  entries (the largest magnitude 65,535).
- **Not the aux card.** MEMORY_MAP 4.3 puts `tantoangle` in the aux card
  for the F1.2.1 renderer, read in `ALTZP` windows from main memory. This
  build reads it from the tables bank like the sine, with one RAMRD
  window a lookup (one `mt_far` back end, F1.2.1's). The aux-card back
  end, and the pair's (`zp_rd`), are for milestones 7 and 13; the routines
  call the table read through `mt_far`, so only it changes.
- **`$C073`** is set to the table's bank inside each window and back to 0
  after (the far layer, not written yet, will keep a shadow of it).
- **`mt_far`** patches two operand bytes of its own code in the card (its
  count and stride); the card is RAM in every phase (MEMORY_MAP rule 1).
- The a2vm test build (`math.cfg`) links these areas at these addresses,
  so an overflow of `$D800-$DBFF` fails the link; its test driver lives in
  the card's `$E000` part, which the game gives the sound and IRQ code.

## Not in this module

| Upstream | Why not | Where it goes |
| --- | --- | --- |
| `fixedDiv` of `p_trace65.s` (the C's `FixedDiv` of `P_InterceptVector`) | Part of the trace code: its operands in `TC_A`, `TC_B`, D used as data, the guards in `ivTest` | Milestone 10, with `P_PathTraverse`, on `udiv32`/`sdiv32`-style steps; `NATIVE.md` 3.2 lists it |
| `shiftMul`, `SIDEPROD`, `ivProd`, the inlined `QPROD` of `r_thing65.s` | Products inlined in their callers, with their own operand forms | Milestones 7 and 10, from `mulw`, `mul8`, `umul16` |
| `R_ScaleFromGlobalAngle`, `scaleFast`, `FSTEP`, the sprite scale tables | Renderer approximations (`NATIVE.md` 3.3) | Milestone 7 |
| `IIGS_SMul16` | Not in the release: absent from the link map | |
| The quarter-square tables `SQL`, `SQH` (512 KB) | The 65C02 cannot use them (`research/native-experiment.md` (b)) | Replaced by 2 KB of byte squares |

## Verification

From `demos/doom_gs`, with ref816's image (`python3
tools/ref816/make_image.py`), a2vm (`make -C tools/a2vm`), cc65 and the
link map. Every a2vm run of `mathrun.py` uses a2vm's `--snapshot-ranges`,
and the cost and stray-write runs its `--write-log`, `--write-log-file`
and `--lowest-s-in`, which are not in a2vm's last commit (`30811a08`)
but in its uncommitted changes of this milestone:
this module is committed with them or after them, never before.

```
make -C src/native -f math.mk tables       # capture newgame, the tables
python3 tools/native/mathcap.py            # all four coverage scripts
make -C src/native -f math.mk              # the build
make -C src/native -f math.mk sizes        # bytes by area and routine
make -C src/native -f math.mk check        # tests/test_native_math.py
make -C src/native -f math.mk check-full   # a million a routine
```

The tools, in [`tools/native`](../../tools/native):

| Tool | What it does |
| --- | --- |
| `mathref.c` (`make -C tools/native`) | Upstream's routines on ref816's machine, used as a library and not modified. `capture` runs a coverage script and logs every call of the routines of a spec: the declared inputs at the entry, the outputs at the return, the cycles, and flags (an interrupt inside; a read of data that is neither a declared input, nor a declared table, nor written first by the call). `batch` runs one routine from a logged call's state (registers, soft switches, return address) on many inputs in one process, as `--call` does |
| `mathcap.py` | Compiles the coverage scripts as `run_script.py` does and runs `mathref capture` on each into `build/native/math/captures/SCRIPT/` |
| `mathtables.py` | The native tables from the reference's RAM and our formulas, with the checks above |
| `mathdefs.py` | Every routine: upstream's label, inputs and outputs; the native entry, inputs and outputs; the host model; the random and edge inputs |
| `mathrun.py` | The native math on a2vm: the image, the driver's descriptor, bulk runs (cases and results in RamWorks banks 1-119) and cost runs (cases in main memory) |
| `mathcheck.py` | The checks and the costs; `build/native/math/report.json` and `.md` |

**The truth.** Upstream's routine on ref816, run by `mathref batch`:
from the entry of a logged call (so the direct page, the data bank, the
switches and the return address are a real call's) to the RTS or RTL that
pops that return address, with a fresh machine whose DOC and ADB are
quiet. Three checks keep that harness honest:

- every logged call without an interrupt inside returns, in the batch,
  what it returned in the game (the declared inputs are the whole input);
- the capture flags any undeclared read (none is left: two 16-bit loads
  whose extra byte upstream masks off are declared);
- a few cases of each routine also go through ref816's own `--call`
  (`mathcheck.py --call-cases`), which must give the same outputs and
  cycles.

The divides have no upstream oracle (decision 5): C semantics
(`mathdefs.m_udiv`, `m_sdiv`), including the port's division by zero. The
byte product's is x × y. The host models are compared with the truth too.

**An indirect comparison with a vendor divide.** The angle routines'
oracle is upstream's routine on ref816, and upstream's `R_PointToAngle3`
and `slopeOld` call `_UDivMod32` inside (`r_iigs65.s:1134`, `:410`). The
native `pta3`, `pta16` and `pta16p` call `udiv32` at the same point, so
their bit-exact comparison on about a million inputs each also compares
`udiv32`'s quotient, clamped at 2048 and only on the dividends and
divisors those routines produce, with the vendor divide's. Nothing is
derived from it: `udiv32` passes the C model independently on its own
million cases, and no vendor divide's output is logged (`mathref.c`
records only their inputs, `mathdefs.VENDOR`). This is unavoidable for
the angle routines, and the tic comparisons of later milestones compare
whole tics that contain vendor divides the same way. **Open question for
the owner:** are such indirect comparisons acceptable under decision 5
("no black-box testing of the vendor routines")?

**The cases.** For each routine: every input of a small domain (every
entry of the sine and cosine, 8,192 each; every 16-bit input of the
approximate sine and cosine and of `FixedReciprocalSmall`; every byte
pair of `mul8`; every random index); otherwise 1,000,000 random inputs
(a mix of uniform bits, small magnitudes of both signs, powers of two
with small offsets, random widths) and the edge inputs; and every
distinct input logged in the four coverage runs.

**The native side.** a2vm's exact W65C02S core runs the build with the
driver of `mathdrv.s`: a descriptor says where each input byte goes and
each output byte comes from; the cases and results sit in RamWorks banks
1-119, copied through RAMRD and RAMWRT windows between the calls. The
tables are where `math.inc` puts them.

**Costs.** On up to 1,024 of the logged inputs (evenly spaced over
them; `mul8`, which no call logs, on random ones), in main memory with no
window between the calls:

- 65C02 cycles a call: the cycles of a run less those of the same run
  calling a bare `RTS`, over the calls, plus the `RTS`'s 6: from the
  routine's first instruction through its return, as ref816 counts
  upstream's;
- time a call on a2vm's cost model, `f121` (F1.2.1) and `fastpath` (the
  firmware design): the phase-1 clocks the driver marks around the call,
  less the bare `RTS` run's, over the calls. The model's costs are
  derived from the RTL, not measured on the card (milestone 0);
- upstream's 65816 cycles on ref816 on the same inputs (and over every
  logged call, in `report.json`): an ideal 65816 with no wait states;
- the lowest S inside the math's code (a2vm `--lowest-s-in`), and
  a2vm's write log: the math's code may write only the math block, the
  stack, `mt_far`'s two operands, the random indexes and `$C002`,
  `$C003`, `$C073`.

`tests/test_native_math.py` runs a sample (200 random inputs a routine,
plus the domains and the logged inputs), the `--call` cross-check, the
costs of three routines, and plants five bugs in a scratch copy of the
sources to show the checks fail: `qmulh` without its carry, a division by
zero giving 0, the cosine without its exceptions, a remainder with the
wrong sign, and a store into `$1A80` (caught by the write log only).

## Results

`python3 tools/native/mathcheck.py --full --call-cases 8` (the `check-full`
target), 2026-09-30, 3 minutes on the owner's Mac with 2 jobs; the
numbers below are the ones it printed (`build/native/math/report.md`;
`make -C src/native -f math.mk check-full` gave the same report, byte for
byte, on a second run the same day). Captures: `newgame`, `title`, `tour`, `viewsize`.

**Correctness: 0 differing results in every routine.** "Cases" are the
distinct inputs run: the whole domain, or 1,000,000 distinct random
inputs plus the edges; plus the logged inputs ("of them logged": every
distinct input the coverage runs gave upstream's routine, all of them in
the cases). For every routine with an upstream oracle, also: 0 of the
logged calls (without an interrupt inside) returned in the game other
than in the batch; 8 cases gave the same outputs and cycles by ref816's
own `--call`; the host model agreed with ref816 on every case. The native
code made 0 stray writes on the cost runs.

| Routine | Upstream | Oracle | Cases | Of them logged | Differ |
| --- | --- | --- | ---: | ---: | ---: |
| `umul16` | `umul16` | ref816 | 1,007,736 | 8,070 | 0 |
| `umul16lo` | `umul16lo` | ref816 | 1,000,792 | 690 | 0 |
| `qmul` | `qmul` | ref816 | 1,018,930 | 19,324 | 0 |
| `mul16` | `_Mul16` | ref816 | 1,000,569 | 46 | 0 |
| `mullo16` | `IIGS_MulLo16` | ref816 | 1,002,663 | 2,480 | 0 |
| `mul8` | `(none)` | x * y | 65,536 | 0 | 0 |
| `qmulh` | `qmulh` | ref816 | 1,007,326 | 6,829 | 0 |
| `mul32` | `_Mul32` | ref816 | 1,002,967 | 1,696 | 0 |
| `fixmul` | `FixedMul` | ref816 | 1,001,800 | 431 | 0 |
| `fixmul3216` | `FixedMul3216` | ref816 | 1,001,926 | 1,140 | 0 |
| `fixmulang` | `FixedMulAngle` | ref816 | 1,003,063 | 1,706 | 0 |
| `udiv16` | `_UDivMod16` | C semantics | 1,000,628 | 149 | 0 |
| `sdiv16` | `_Div16` | C semantics | 1,000,775 | 534 | 0 |
| `udiv32` | `_UDivMod32` | C semantics | 1,001,410 | 47 | 0 |
| `sdiv32` | `_Div32` | C semantics | 1,004,001 | 2,655 | 0 |
| `recip` | `FixedReciprocal` | ref816 | 1,000,317 | 1,281 | 0 |
| `recipsmall` | `FixedReciprocalSmall` | ref816 | 65,536 | 536 | 0 |
| `recipbig` | `FixedReciprocalBig` | ref816 | 1,000,078 | 54 | 0 |
| `approxdiv` | `FixedApproxDiv` | ref816 | 1,001,428 | 59 | 0 |
| `aproxdist` | `P_AproxDistance` | ref816 | 1,002,311 | 942 | 0 |
| `pta3` | `R_PointToAngle3` | ref816 | 1,001,556 | 187 | 0 |
| `pta16` | `R_PointToAngle16` | ref816 | 1,001,962 | 234 | 0 |
| `pta16p` | `pointAngle` | ref816 | 1,006,455 | 4,727 | 0 |
| `finesine` | `finesine` | ref816 | 8,192 | 608 | 0 |
| `finecosine` | `finecosine` | ref816 | 8,192 | 161 | 0 |
| `sineapprox` | `finesineapprox` | ref816 | 65,536 | 96 | 0 |
| `cosineapprox` | `finecosineapprox` | ref816 | 65,536 | 35 | 0 |
| `prandom` | `P_Random` | ref816 | 256 | 256 | 0 |
| `mrandom` | `M_Random` | ref816 | 256 | 256 | 0 |

| Routine | Native | Bytes | With callees | 65C02 cycles | f121 us | fastpath us | Upstream cycles | Ratio | Stack |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `umul16` | `umul16` | 28 | 126 | 189.23 | 3.255 | 3.255 | 98.36 (96-102) | 1.92 | 2 |
| `umul16lo` | `umul16lo` | 60 | 60 | 113.44 | 2.001 | 2.001 | 67.23 (66-71) | 1.69 | 2 |
| `qmul` | `umul16` | 28 | 126 | 202.07 | 3.46 | 3.46 | 86.04 (83-89) | 2.35 | 2 |
| `mul16` | `umul16` | 28 | 126 | 195.35 | 3.329 | 3.329 | 129.78 (126-131) | 1.51 | 2 |
| `mullo16` | `umul16lo` | 60 | 60 | 114.27 | 2.007 | 2.007 | 82.03 (79-83) | 1.39 | 2 |
| `mul8` | `mul8` | 24 | 24 | 49.5 | 0.803 | 0.803 | - | - | 2 |
| `qmulh` | `qmulh` | 115 | 241 | 392.04 | 6.609 | 6.609 | 63.9 (61-67) | 6.14 | 4 |
| `mul32` | `mul32` | 134 | 232 | 419.74 | 6.97 | 6.97 | 213.42 (164-286) | 1.97 | 4 |
| `fixmul` | `fixmul` | 313 | 411 | 625.07 | 10.628 | 10.628 | 299.64 (230-505) | 2.09 | 4 |
| `fixmul3216` | `fixmul3216` | 4 | 415 | 391.36 | 6.741 | 6.741 | 221.93 (215-227) | 1.76 | 4 |
| `fixmulang` | `fixmulang` | 59 | 474 | 435.57 | 7.266 | 7.266 | 250.38 (228-281) | 1.74 | 11 |
| `udiv16` | `udiv16` | 88 | 88 | 566.77 | 7.276 | 7.276 | - | - | 2 |
| `sdiv16` | `sdiv16` | 111 | 199 | 568.53 | 7.529 | 7.529 | - | - | 4 |
| `udiv32` | `udiv32` | 172 | 172 | 1724.98 | 22.745 | 22.745 | - | - | 2 |
| `sdiv32` | `sdiv32` | 175 | 347 | 2290.37 | 30.231 | 30.231 | - | - | 4 |
| `recip` | `recip` | 168 | 196 | 378.63 | 13.018 | 6.133 | 142.87 (124-151) | 2.65 | 4 |
| `recipsmall` | `recipsmall` | 4 | 200 | 394.21 | 13.323 | 6.334 | 142.46 (122-183) | 2.77 | 4 |
| `recipbig` | `recipbig` | 168 | 196 | 385.59 | 12.987 | 5.958 | 148 (132-165) | 2.61 | 4 |
| `approxdiv` | `approxdiv` | 103 | 714 | 999.19 | 23.193 | 16.206 | 461.8 (441-483) | 2.16 | 10 |
| `aproxdist` | `aproxdist` | 154 | 154 | 131.29 | 2.174 | 2.174 | 87.86 (67-122) | 1.49 | 2 |
| `pta3` | `pta3` | 357 | 691 | 1528.9 | 30.833 | 24.228 | 861.15 (715-1010) | 1.78 | 5 |
| `pta16` | `pta16` | 344 | 571 | 884.7 | 19.482 | 13.635 | 295.46 (265-311) | 2.99 | 5 |
| `pta16p` | `pta16` | 344 | 571 | 878.52 | 19.326 | 13.566 | 276.56 (111-296) | 3.18 | 5 |
| `finesine` | `finesine` | 63 | 102 | 148.92 | 8.095 | 2.894 | 33 (33-33) | 4.51 | 4 |
| `finecosine` | `finecosine` | 48 | 247 | 335.28 | 11.104 | 5.423 | 33 (33-33) | 10.16 | 4 |
| `sineapprox` | `sineapprox` | 88 | 127 | 171.71 | 8.647 | 3.196 | 47.69 (42-55) | 3.60 | 6 |
| `cosineapprox` | `cosineapprox` | 9 | 136 | 183.46 | 8.862 | 3.426 | 54.91 (50-63) | 3.34 | 6 |
| `prandom` | `prandom` | 11 | 267 | 20.0 | 0.271 | 0.271 | 32 (32-32) | 0.62 | 2 |
| `mrandom` | `mrandom` | 11 | 267 | 20.0 | 0.271 | 0.271 | 32 (32-32) | 0.62 | 2 |


Sizes (`make -f math.mk sizes`): `MATHLC` 860 of 1,024 bytes at `$D800`,
`MATHFAR` 67 bytes at `$DC00`, `MATHW` 2,133 bytes, `MATHRND` 256. "Bytes"
is a routine's own code (to the next exported label, its local helpers
and data included); "with callees" adds what it calls. "Upstream cycles"
is the mean (minimum-maximum) on the same inputs; "Stack" the bytes below
the caller's S, the call's return address included.

What the numbers say:

- **Products: 1.4 to 2.4 times upstream's cycles**, as the experiment
  measured (`research/native-experiment.md` (b): 2.1-2.5 for the 16 x 16
  product). `umul16` takes 189 cycles on its logged inputs and 202 on
  `qmul`'s (the renderer's, 81,051 calls in the four runs); a 16 x 16
  product is 3.3-3.5 us on the model, the same in both profiles (fast
  memory only).
- **`qmulh` is 6.1 times upstream's**: upstream's is two lookups in its
  512 KB tables, the native one the exact product plus the correction
  term (above). Its callers are `scaleFast` (21,880 calls, 2 a wall). A
  faster inexact form would need the owner's waiver.
  - Measured on those 21,880 logged calls (2026-09-30): upstream's result
    is the exact high word plus 1 in 49-52% of them, never anything else.
    The value feeds a wall's scale, where one unit is about 0.002 of a
    pixel for a 128-pixel wall, so the exact product (`umul16`, about
    3.3 us) would move a wall edge by one pixel only rarely; but frames
    would no longer equal upstream's byte for byte.
  - At about 500 calls a frame, the exact `qmulh` costs about 3.3 ms a
    frame and the exact product about 1.6 ms. The owner decided on
    2026-09-30 to keep `qmulh` exact for now.
- **Tables in RamWorks cost their window**: `finesine` is 149 cycles but
  8.1 us on F1.2.1, 2.9 us on fastpath: 4 soft-switch writes a lookup
  ($C073 twice, RAMRD twice). Upstream's 33 cycles are 11.5 us on a 2.86
  MHz IIgs. The reciprocals and the angle routines pay the same, once.
- **Angles**: `pointAngle` (the BSP's `vtxAngle`, 4,687 calls in the
  runs) is 879 cycles, 19.3 us on F1.2.1, 3.2 times upstream: its 11
  division steps and one table window. `R_PointToAngle3` is 1.8 times
  upstream.
- **Divides**: 567-2,290 cycles, 7-30 us. They are cold: level loads
  (`R_InitData`'s `divD`, 10,240 of the 10,353 32-bit signed calls; the
  lump name hash), the intermission, sound set-up, and `(leveltime >> 3)
  % 3` once a tic.
- **`P_Random`**: 20 cycles, 0.27 us, against upstream's 32.
