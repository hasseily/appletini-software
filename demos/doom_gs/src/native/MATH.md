# The native math

The 65C02 math of the port: [`math.s`](math.s), with
[`math.inc`](math.inc) (the zero page, the tables' places, the soft
switches) and [`mathgame.inc`](mathgame.inc) (the game's angle, sine
and distance routines). Every routine reproduces upstream's result bit
for bit, quirks included; the divides are the port's own, written from C
semantics. It is a GPL-2 derivative of upstream's `m_fixed65.s`,
`m_recip65.s`, `tables65.s`, `m_random65.s`, `r_iigs65.s`, `r_wall65.s`,
`p_mobj65.s` and `p_path65.s`. Nothing comes from upstream's
`cal_integer.s`: the divides were written from the call sites and C only.

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

- **`qmulh`** is upstream's `sq(a + b) − sq(|a − b|)` from the high words
  of the quarter squares only: the high word of a b, or 1 more. Natively
  that is the exact product plus the carry of lo(a b) + lo(sq(|a − b|)),
  with lo(sq(d)) = f(dl) + ((dh dl) mod 512) << 7 + (dh & 1) << 14. So
  the native `qmulh` costs more than the exact product, where upstream's
  costs less; an inexact form would change the frames.
- **`FixedMul3216` and `FixedMulAngle`** use only the low word of b: not
  `FixedMul`.
- **`FixedApproxDiv`** takes its small path for a b whose high word is 0
  *or negative* (a signed compare in the C), with b's low word only.
- **`R_PointToAngle16`** has two paths upstream: a fast one for deltas in
  −16384..16384 and `pointOld` otherwise, with signed 16-bit compares
  (so −(−32768) stays $8000, negative) and `slopeOld`. For num > den,
  `slopeOld` builds the dividend of `n << 11` with the high word
  **n >> 13** where it should be n >> 5 (`r_iigs65.s`, `slopeOld`, `80$`:
  `xba`, `and`, five `lsr`). The native `pta16` does the same.
- **`R_PointToAngle3`**: `SlopeDiv` is `(uint16_t)((num << 3) / (den >>
  8))`, the shift modulo 2^32 and the quotient's low word, at most
  2048; |x| of −2^31 stays −2^31, and the octant compare is signed.
- **`P_AproxDistance`**: labs in 32-bit two's complement, a signed
  compare, an arithmetic shift.
- **`finecosine`** is not the shifted sine on 12 entries (x = 6214,
  6258, 6599, 6773, 6775, 6915, 7007, 7211, 7277, 7403, 7417, 7971):
  `tools/native/mathtables.py` finds them in the reference's table
  (`cosexc.bin`) and the routine checks that list first.
- **`P_Random`**: upstream reads a 16-bit word at `rndtable + index` and
  masks the byte after the table off; the index is a byte natively.

### The divides: C semantics, and division by zero

Written from the call sites and C11 6.5.5 only: the quotient truncated
toward zero, the remainder with the dividend's sign,
`(a / b) * b + a % b == a`. What C leaves undefined, the port defines:

| Case | Unsigned | Signed |
| --- | --- | --- |
| x / 0 | quotient all ones ($FFFF, $FFFFFFFF), remainder x | quotient the largest value of x's sign: $7FFF / $7FFFFFFF for x ≥ 0, $8000 / $80000000 for x < 0; remainder x |
| INT_MIN / −1 | | quotient INT_MIN (the two's complement wrap), remainder 0 |

The angle routines `pta3` and `pta16` call `udiv32` where upstream's
call its vendor divide `_UDivMod32`; on the inputs those routines give
it (quotients clamped at 2048) the two agree, so the angles stay
upstream's.

## Where it lives

[`docs/MEMORY_MAP.md`](../../docs/MEMORY_MAP.md) sections 2, 4, 5
and 8.

| What | Where | Bytes |
| --- | --- | ---: |
| Quarter squares f(n) and f(n − 255), low and high bytes, 512 each (`SQL`, `SQH`, `NSL`, `NSH`) | main card bank 1 `$D000-$D7FF` | 2,048 |
| The products (segment `MATHLC`): `mt_init`, `umul16`, `mulw`, `umul16lo`, `mul8`, `qmulh`, `fixmul`, `fixmul3216`, `fixmulang`, `mul32` | main card bank 1 `$D800-$DBFF` | ≤ 1,024 |
| The table reads (`MATHFAR`): `mt_far`, `mt_recipe`. They run with RAMRD on, so they must be in the card | bank 1 from `$DC00`, before the far layer (`far.s`) | |
| The rest (`MATHW`): the divides, reciprocals, `approxdiv`, the angles, the approximate sines | W `$6000-$65FF` with `AUXW` after it, the same bytes in every W image that calls the math (render, load, 2D, tic) | |
| The math block: the square pointers (8 × 2 bytes; their high bytes set once by `mt_init`), `M_A`, `M_B`, `M_R`, 12 temporaries (`MT`, `M_T`, `MT_E`, `MT_P`) | zero page `$B0-$D7`. Every phase that calls the math keeps it; the replay (`$48-$6F`) and the IRQ (`$D8-$FF`) never touch it | 40 |
| The tables bank (`MT_TBANK`, 120): sine magnitude planes `$2000`, `$4000` (8,192 each); `tantoangleTable`, 2,049 entries, 4 byte planes at `$6000` + 9 pages each; `finesineTable_part_1`, 2,048 words, planes `$8400`, `$8C00` | RamWorks | 30,724 |
| `RECIP_TABLE` low and high planes, 32,768 each | RamWorks banks 121 (`MT_RLO`) and 122 (`MT_RHI`), `$2000-$9FFF` | 65,536 |

- **The sine** is 16 KB of magnitude planes, the sign bit 12 of x
  (checked by `mathtables.py` on all 8,192 entries).
- **A table read** is one RAMRD window: `$C073` set to the table's bank,
  the read, `$C073` 0 and RAMRD off. `mt_far` patches two operand bytes
  of its own code in the card (its count and stride); the card is RAM
  in every phase. On F1.2.1 each window costs its four soft-switch
  writes, so `finesine` and the reciprocals cost far more than their
  instruction cycles.
- **`mt_init`** runs once before any product: `lsetup.s` calls it at a
  level's setup.

## The builds of `math.s`

| Build | Flag | Object | What it holds | Linked into |
| --- | --- | --- | --- | --- |
| render | `-D RENDER` | `math-r.o` | `MATHLC`, `MATHFAR`, and the subset of `MATHW` without `pta3`, `aproxdist`, `finesine`, `finecosine` and the random numbers; `pta16` reads `tantoangle` from the aux card (`auxlc.s` `ax_tanto`, MEMORY_MAP 6) instead of the tables bank | `render.mk`, `level.mk`, `m11.mk`, `play.mk` (the tic image) |
| game | `-D GAMEMATH` | `math-g.o` | only `mathgame.inc`: `pta3`, `pta_oct`, `finesine`, `finecosine`, `cosexc`, `aproxdist`, in the tic image's core (segment `GCORE`), on the render build's `mt_far`, `udiv32` and octant table (`pta_tab`) | `play.mk` (the tic image) |

`mathgame.inc` is one text for both: without either flag `math.s`
includes it in `MATHW`. That whole-module build (with `prandom`,
`mrandom`, `mclearrandom` and `rndtable` in segment `MATHRND`) is not
linked by any makefile now; the game's random numbers are `gthink.s`'s
`g_random` and `g_mrandom`, with their own copy of the table.

## The tables

`tools/native/rtables.py` calls `mathtables.build`, which reads
upstream's tables from the reference machine's RAM (the release run by
`tools/native/rendercap.py`), checks them, and writes the native layouts
into `build/native/render/tables/math` (they are Doom's and upstream's
data, so they stay in `build/`):

| File | What |
| --- | --- |
| `squares.bin` | the quarter squares of `$D000-$D7FF`: f(n) = floor(n × n / 4), n = 0-511, low then high bytes; then f(n − 255) the same |
| `sinelo.bin`, `sinehi.bin` | \|finesine[x]\|, x = 0-8191, low and high bytes |
| `cosexc.bin` | the entries where `finecosine` is not the shifted sine: their count, then their x and values as byte planes (16 slots) |
| `tanto0-3.bin` | `tantoangleTable`, 2,049 entries, one byte plane each |
| `quartlo.bin`, `quarthi.bin` | `finesineTable_part_1`, 2,048 words |
| `reciplo.bin`, `reciphi.bin` | `RECIP_TABLE`, 32,768 words: floor((2^31 − 1) / (32768 + i)), our formula, checked against the reference's table |
| `rndtable.bin` | `P_Random`'s 256 bytes |
| `tables.json` | the counts and checks |

`tools/native/mathdefs.py` holds the table record, `RECIP_TABLE`'s
formula and a host model of the reciprocal (`m_recip`), which
`rtables.py` uses to check the sprite scales. The disk builder puts
`squares.bin` into the main card image and the RamWorks planes into
banks 120-122.
