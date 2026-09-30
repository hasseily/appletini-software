"""The native math of milestone 6: every routine's upstream form, native
form, host model and test inputs, in one table.

A routine has canonical operands (a tuple of Python ints) and a canonical
result (a tuple of ints). Each routine says how to put its operands into
upstream's registers and memory (for tools/native/mathref.c on ref816) and
into the native routine's zero page (for the driver of src/native on a2vm),
and how to read its result back from either. The host models are written
from C semantics and from upstream's own comments; they are a third
opinion, not the oracle: the oracle of every routine but the divides is
upstream's routine run on ref816 (docs/NATIVE.md 15.1). The divides are
the port's own (the owner's decision 5): their oracle is the C model here,
never the vendor routines.

Nothing here comes from upstream's cal_integer.s (the ground rules).
"""

import random
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
LINKMAP = BUILD / 'linkmap.json'
MATH = BUILD / 'native' / 'math'

M16 = 0xFFFF
M32 = 0xFFFFFFFF
INT32_MIN = -0x80000000
INT32_MAX = 0x7FFFFFFF
INT16_MIN = -0x8000
INT16_MAX = 0x7FFF

# upstream's tables of whole banks (memmap.inc: MM_SQL, MM_SQH, MM_RECIP,
# MM_SINE), for the "table" lines of the capture spec
SQ_RANGE = (0x130000, 0x1B0000)
RECIP_RANGE = (0x1E0000, 0x1F0000)
SINE_RANGE = (0x200000, 0x210000)
SLOPERANGE = 2048


def s16(v: int) -> int:
    v &= M16
    return v - 0x10000 if v & 0x8000 else v


def s32(v: int) -> int:
    v &= M32
    return v - 0x100000000 if v & 0x80000000 else v


def le(data: bytes, at: int, size: int) -> int:
    return int.from_bytes(data[at:at + size], 'little')


def b16(v: int) -> bytes:
    return (v & M16).to_bytes(2, 'little')


def b32(v: int) -> bytes:
    return (v & M32).to_bytes(4, 'little')


# ---------------------------------------------------------------------------
# Tables the models need (from the reference's RAM: see mathtables.py)
# ---------------------------------------------------------------------------

class Tables(NamedTuple):
    sine: List[int]         # finesine, 8192 entries, 32-bit patterns
    cosine: List[int]       # finecosine
    tanto: List[int]        # tantoangleTable, 2049 entries
    quarter: List[int]      # finesineTable_part_1, 2048 words
    rnd: bytes              # rndtable, 256 bytes
    recip: List[int]        # RECIP_TABLE, 32768 words


def recip_entry(i: int) -> int:
    """RECIP_TABLE entry i: floor((2^31 - 1) / (32768 + i)), the formula
    upstream's m_recip65.s documents (IIGS_InitRecip)."""
    return (2 ** 31 - 1) // (32768 + i)


# ---------------------------------------------------------------------------
# Host models
# ---------------------------------------------------------------------------

def m_umul16(a: int, b: int) -> int:
    return (a & M16) * (b & M16)


def m_fixmul(a: int, b: int) -> int:
    """FixedMul: floor(a * b / 65536) modulo 2^32, a and b signed."""
    return ((s32(a) * s32(b)) >> 16) & M32


def m_fixmul3216(a: int, bl: int) -> int:
    """FixedMul3216: floor(a * bl / 65536), a signed, bl unsigned 16."""
    return ((s32(a) * (bl & M16)) >> 16) & M32


def m_fixmulang(a: int, b: int) -> int:
    """FixedMulAngle: FixedMul3216(a, b & 0xFFFF), minus a when b < 0."""
    r = m_fixmul3216(a, b)
    if s32(b) < 0:
        r = (r - a) & M32
    return r


def m_mul32(a: int, b: int) -> int:
    return ((a & M32) * (b & M32)) & M32


def m_qmulh(a: int, b: int) -> int:
    """qmulh: sq(a + b) - sq(|a - b|) from the high words of the quarter
    squares sq(n) = floor(n^2 / 4) only (r_wall65.s): the high word of
    a * b, or 1 more."""
    a &= M16
    b &= M16
    s, d = a + b, abs(a - b)
    return (((s * s) >> 18) - ((d * d) >> 18)) & M16


def m_recip(v: int, recip: Sequence[int]) -> int:
    """recipCore of m_recip65.s: v shifted left by s until bit 31 is set,
    M its top 16 bits, RECIP_TABLE[M - 32768] shifted by s - 15."""
    v &= M32
    if v == 0:
        return M32
    s = 32 - v.bit_length()
    m = ((v << s) & M32) >> 16
    e = recip[m - 32768]
    if v >= 0x10000:
        return e >> (15 - s)
    return (e << (s - 15)) & M32


def m_recipsmall(v: int, recip: Sequence[int]) -> int:
    return m_recip(v & M16, recip)


def m_approxdiv(a: int, b: int, recip: Sequence[int]) -> int:
    """FixedApproxDiv (r_iigs65.s approxDiv): a signed compare, so a
    negative b takes the small path with its low word."""
    if (b & M32) >> 16 == 0 or s32(b) < 0:
        return m_fixmul(a, m_recipsmall(b, recip))
    return m_fixmul3216(a, m_recip(b, recip))


def m_aproxdist(dx: int, dy: int) -> int:
    """P_AproxDistance: dx + dy - min(dx, dy) / 2 with labs and the
    rounding m - (m >> 1), 32-bit two's complement throughout."""
    dx = (-s32(dx) if s32(dx) < 0 else dx) & M32
    dy = (-s32(dy) if s32(dy) < 0 else dy) & M32
    if s32(dx) < s32(dy):
        return (dy + (s32(dx) >> 1) + (dx & 1)) & M32
    return (dx + (s32(dy) >> 1) + (dy & 1)) & M32


def m_pta3(x: int, y: int, tanto: Sequence[int]) -> int:
    """R_PointToAngle3 (r_iigs65.s), the C of r_draw.c with SlopeDiv(num,
    den) = (uint16_t)((num << 3) / (den >> 8)), at most SLOPERANGE."""
    x &= M32
    y &= M32
    if x == 0 and y == 0:
        return 0
    xn = s32(x) < 0
    yn = s32(y) < 0
    if xn:
        x = (-x) & M32
    if yn:
        y = (-y) & M32
    if s32(y) < s32(x):
        le_ = 0
        num, den = y, x
    else:
        le_ = 1
        num, den = x, y
    d = den >> 8
    if d == 0:
        q = SLOPERANGE
    else:
        q = (((num << 3) & M32) // d) & M16
        q = min(q, SLOPERANGE)
    t = tanto[q]
    k = 4 * xn + 2 * yn + le_
    if k == 0:
        r = t
    elif k == 1:
        r = 0x3FFFFFFF - t
    elif k == 2:
        r = -t
    elif k == 3:
        r = 0xC0000000 + t
    elif k == 4:
        r = 0x7FFFFFFF - t
    elif k == 5:
        r = 0x40000000 + t
    elif k == 6:
        r = 0x80000000 + t
    else:
        r = 0xBFFFFFFF - t
    return r & M32


def _slope16(n: int, d: int) -> int:
    """SlopeDiv16 as slopeOld (r_iigs65.s): n and d unsigned 16-bit. For
    n > d upstream builds its 32-bit dividend with a high word of n >> 13
    where n << 11 has n >> 5 (r_iigs65.s slopeOld, 80$: xba, and, five
    lsr); the port does the same."""
    if d == 0 or n == d:
        return SLOPERANGE
    if n < d:
        return (n * 2048) // d
    dividend = (n >> 13) << 16 | ((n << 11) & M16)
    return min((dividend // d) & M16, SLOPERANGE)


def m_pta16(x: int, y: int, vx: int, vy: int,
            tanto: Sequence[int]) -> int:
    """R_PointToAngle16 and pointAngle (r_iigs65.s): the angle of (x, y)
    from (viewx, viewy), whole units, 16-bit; the high words of
    tantoangleTable. Both deltas in -16384..16384: the fast path (0 for
    the view's own point); else pointOld, with its signed 16-bit compares
    and slopeOld."""
    dx = (x - vx) & M16
    dy = (y - vy) & M16
    fast = ((dx + 0x4000) & M16) < 0x8001 and ((dy + 0x4000) & M16) < 0x8001
    if fast and dx == 0 and dy == 0:
        return 0
    tt = lambda q: tanto[q] >> 16  # noqa: E731
    if s16(dx) >= 0:
        if s16(dy) >= 0:
            if s16(dy) < s16(dx):
                return tt(_slope16(dy, dx))
            return (0x3FFF - tt(_slope16(dx, dy))) & M16
        ny = (-dy) & M16
        if s16(ny) < s16(dx):
            return (-tt(_slope16(ny, dx))) & M16
        return (0xC000 + tt(_slope16(dx, ny))) & M16
    nx = (-dx) & M16
    if s16(dy) >= 0:
        if s16(dy) < s16(nx):
            return (0x7FFF - tt(_slope16(dy, nx))) & M16
        return (0x4000 + tt(_slope16(nx, dy))) & M16
    ny = (-dy) & M16
    if s16(ny) < s16(nx):
        return (0x8000 + tt(_slope16(ny, nx))) & M16
    return (0xBFFF - tt(_slope16(nx, ny))) & M16


def m_sineapprox(x: int, quarter: Sequence[int]) -> int:
    """finesineapprox (tables65.s): the quarter table, mirrored and
    negated; x unsigned 16-bit."""
    x &= M16

    def q(c):
        return quarter[c if c < 2048 else 4095 - c]
    if x < 4096:
        return q(x)
    return (-q(x & 4095)) & M32


def m_cosineapprox(x: int, quarter: Sequence[int]) -> int:
    return m_sineapprox((x + 2048) & 8191, quarter)


# The divides: the port's own, from C semantics (C11 6.5.5: the quotient
# truncated toward zero, (a / b) * b + a % b == a). Division by zero, which
# C leaves undefined, is defined by the port: the quotient saturates to the
# largest value of the dividend's sign (all ones unsigned; INT_MAX for a
# dividend >= 0, INT_MIN below) and the remainder is the dividend. The one
# signed overflow, INT_MIN / -1, wraps: INT_MIN, remainder 0.

def m_udiv(a: int, b: int, bits: int) -> Tuple[int, int]:
    mask = (1 << bits) - 1
    a &= mask
    b &= mask
    if b == 0:
        return mask, a
    return a // b, a % b


def m_sdiv(a: int, b: int, bits: int) -> Tuple[int, int]:
    mask = (1 << bits) - 1
    half = 1 << (bits - 1)
    sa = (a & mask) - ((a & half) << 1)
    sb = (b & mask) - ((b & half) << 1)
    if sb == 0:
        return (half if sa < 0 else half - 1), sa & mask
    q = abs(sa) // abs(sb)
    if (sa < 0) != (sb < 0):
        q = -q
    r = sa - q * sb
    return q & mask, r & mask


# ---------------------------------------------------------------------------
# Random and edge inputs
# ---------------------------------------------------------------------------

EDGE32 = sorted({0, 1, 2, 3, 0x7F, 0x80, 0xFF, 0x100, 0x7FFF, 0x8000,
                 0xFFFF, 0x10000, 0x10001, 0x1FFFF, 0x7FFFFF, 0x800000,
                 0xFFFFFF, 0x1000000, 0x3FFFFFFF, 0x40000000, 0x7FFFFFFE,
                 0x7FFFFFFF, 0x80000000, 0x80000001, 0xFFFF0000, 0xFFFF0001,
                 0xFFFF8000, 0xFFFF7FFF, 0xFFFFFF00, 0xFFFFFF80, 0xFFFFFFFE,
                 0xFFFFFFFF, 0xC0000000, 0x00010000 * 64, 0x00008000 * 3,
                 12345678, (-12345678) & M32})
EDGE16 = sorted({0, 1, 2, 3, 0x7F, 0x80, 0xFF, 0x100, 0x101, 0x3FFF,
                 0x4000, 0x4001, 0x7FFE, 0x7FFF, 0x8000, 0x8001, 0xBFFF,
                 0xC000, 0xFF00, 0xFFFE, 0xFFFF, 1000, 0xFFFF - 999})


def rand32(rng: random.Random) -> int:
    """A 32-bit value from a mix: uniform bits, small magnitudes of
    either sign, a power of two with a small offset, and a random bit
    width (so every byte length is common)."""
    kind = rng.randrange(8)
    if kind < 3:
        return rng.getrandbits(32)
    if kind < 5:
        v = rng.getrandbits(rng.randrange(1, 33))
        return (-v) & M32 if rng.getrandbits(1) else v
    if kind == 5:
        v = (1 << rng.randrange(32)) + rng.randrange(-3, 4)
        return (-v if rng.getrandbits(1) else v) & M32
    if kind == 6:
        return rng.choice(EDGE32)
    return rng.getrandbits(rng.randrange(1, 33))


def rand16(rng: random.Random) -> int:
    kind = rng.randrange(6)
    if kind < 3:
        return rng.getrandbits(16)
    if kind == 3:
        v = rng.getrandbits(rng.randrange(1, 17))
        return (-v) & M16 if rng.getrandbits(1) else v
    if kind == 4:
        return rng.choice(EDGE16)
    return rng.getrandbits(rng.randrange(1, 17))


# ---------------------------------------------------------------------------
# The routines
# ---------------------------------------------------------------------------

class Routine(NamedTuple):
    """One routine of the native math.

    name        the native routine (and the test's name)
    upstream    upstream's label ("unit:label"), or None when upstream has
                no routine to call (the byte product, a macro; the
                divides, the vendor's, never called as an oracle)
    up_in, up_out
                the capture spec's items: 'a', 'x', 'y', or (SYMBOL, LEN)
    up_tables   ranges upstream's routine may read besides its inputs:
                (start, end) or (SYMBOL, LEN)
    ops_from_up the operands from upstream's input bytes
    up_bytes    upstream's input bytes from the operands
    res_from_up the result from upstream's output bytes
    native      the native entry label
    nat_in      the native inputs: a list of (SYMBOL, LEN) or ('A'|'X'|'Y')
    nat_out     the native outputs, the same
    nat_bytes   the native input bytes from the operands
    res_from_nat
    model       the host model: operands -> result (tables as keyword t)
    gen         (rng) -> operands, the random inputs
    edges       the edge operands, all tested
    exhaustive  every operand tuple of the domain, when it is small
    """
    name: str
    upstream: Optional[str]
    up_in: Tuple
    up_out: Tuple
    up_tables: Tuple
    ops_from_up: Optional[Callable]
    up_bytes: Optional[Callable]
    res_from_up: Optional[Callable]
    native: str
    nat_in: Tuple
    nat_out: Tuple
    nat_bytes: Callable
    res_from_nat: Callable
    model: Callable
    gen: Optional[Callable]
    edges: Callable
    exhaustive: Optional[Callable] = None
    doc: str = ''


def _pairs(values: Sequence[int]) -> List[Tuple[int, int]]:
    return [(a, b) for a in values for b in values]


def _ax(b: bytes, at: int = 0) -> int:
    """X:C (A the low word, X the high word) from two register items."""
    return le(b, at, 2) | le(b, at + 2, 2) << 16


def _gen2x32(rng):
    return (rand32(rng), rand32(rng))


def _gen2x16(rng):
    return (rand16(rng), rand16(rng))


def _edges2x32():
    return _pairs(EDGE32)


def _edges2x16():
    return _pairs(EDGE16)


SQ = (SQ_RANGE,)
SQ_REC = (SQ_RANGE, RECIP_RANGE, ('m_recip65.s:rcShl1', 3 * 32 + 2 * 34))
SINE = (SINE_RANGE,)
TANTO = (('tantoangleTable', 2049 * 4),)
# R_PointToAngle3 reads _Dp[4] with lda (_Dp+3), and masks it off
TANTO3 = TANTO + (('r_iigs65.s:octJump3', 16), ('_Dp+4', 1))
QUARTER = (('finesineTable_part_1', 4096),)


def _nat32x2(ops):
    return b32(ops[0]) + b32(ops[1])


def _routines() -> List[Routine]:
    r = []

    # -- the multiply family --------------------------------------------
    r.append(Routine(
        'umul16', 'm_fixed65.s:umul16', (('MA', 2), ('MB', 2)),
        (('MR', 4),), SQ,
        lambda b: (le(b, 0, 2), le(b, 2, 2)),
        lambda o: b16(o[0]) + b16(o[1]),
        lambda b: (le(b, 0, 4),),
        'umul16', (('M_A', 2), ('M_B', 2)), (('M_R', 4),),
        lambda o: b16(o[0]) + b16(o[1]),
        lambda b: (le(b, 0, 4),),
        lambda o, t: (m_umul16(*o),),
        _gen2x16, _edges2x16,
        doc='unsigned 16 x 16 -> 32 (umul16, _Mul16, qmul)'))
    r.append(Routine(
        'umul16lo', 'm_fixed65.s:umul16lo', (('MA', 2), ('MB', 2)),
        ('a',), SQ,
        lambda b: (le(b, 0, 2), le(b, 2, 2)),
        lambda o: b16(o[0]) + b16(o[1]),
        lambda b: (le(b, 0, 2),),
        'umul16lo', (('M_A', 2), ('M_B', 2)), (('M_R', 2),),
        lambda o: b16(o[0]) + b16(o[1]),
        lambda b: (le(b, 0, 2),),
        lambda o, t: (m_umul16(*o) & M16,),
        _gen2x16, _edges2x16,
        doc='the low word of a 16 x 16 product (umul16lo, IIGS_MulLo16)'))
    # upstream's other entries of the same two products
    r.append(Routine(
        'qmul', 'r_wall65.s:qmul', (('MA', 2), 'a'), ('y', 'a'), SQ,
        lambda b: (le(b, 0, 2), le(b, 2, 2)),
        lambda o: b16(o[0]) + b16(o[1]),
        lambda b: (le(b, 0, 2) | le(b, 2, 2) << 16,),
        'umul16', (('M_A', 2), ('M_B', 2)), (('M_R', 4),),
        lambda o: b16(o[0]) + b16(o[1]),
        lambda b: (le(b, 0, 4),),
        lambda o, t: (m_umul16(*o),),
        _gen2x16, _edges2x16,
        doc='qmul of the wall setup: the same product as umul16'))
    r.append(Routine(
        'mul16', 'm_fixed65.s:_Mul16', ('a', 'x'), ('a', 'x'), SQ,
        lambda b: (le(b, 0, 2), le(b, 2, 2)),
        lambda o: b16(o[0]) + b16(o[1]),
        lambda b: (_ax(b),),
        'umul16', (('M_A', 2), ('M_B', 2)), (('M_R', 4),),
        lambda o: b16(o[0]) + b16(o[1]),
        lambda b: (le(b, 0, 4),),
        lambda o, t: (m_umul16(*o),),
        _gen2x16, _edges2x16,
        doc='_Mul16: the same product as umul16'))
    r.append(Routine(
        'mullo16', 'm_fixed65.s:IIGS_MulLo16', ('a', 'x'), ('a',), SQ,
        lambda b: (le(b, 0, 2), le(b, 2, 2)),
        lambda o: b16(o[0]) + b16(o[1]),
        lambda b: (le(b, 0, 2),),
        'umul16lo', (('M_A', 2), ('M_B', 2)), (('M_R', 2),),
        lambda o: b16(o[0]) + b16(o[1]),
        lambda b: (le(b, 0, 2),),
        lambda o, t: (m_umul16(*o) & M16,),
        _gen2x16, _edges2x16,
        doc='IIGS_MulLo16: the same product as umul16lo'))
    r.append(Routine(
        'mul8', None, (), (), (), None, None, None,
        'mul8', ('A', 'Y'), (('M_R', 2),),
        lambda o: bytes([o[0], o[1]]),
        lambda b: (le(b, 0, 2),),
        lambda o, t: (o[0] * o[1],),
        None, lambda: [],
        exhaustive=lambda: [(a, b) for a in range(256) for b in range(256)],
        doc='8 x 8 -> 16 (the byte products of mul.inc, a macro upstream)'))
    r.append(Routine(
        'qmulh', 'r_wall65.s:qmulh', (('MA', 2), 'a'), ('a',), SQ,
        lambda b: (le(b, 0, 2), le(b, 2, 2)),
        lambda o: b16(o[0]) + b16(o[1]),
        lambda b: (le(b, 0, 2),),
        'qmulh', (('M_A', 2), ('M_B', 2)), (('M_R', 2),),
        lambda o: b16(o[0]) + b16(o[1]),
        lambda b: (le(b, 0, 2),),
        lambda o, t: (m_qmulh(*o),),
        _gen2x16, _edges2x16,
        doc='the high word of a 16 x 16 product, or 1 more (qmulh)'))
    r.append(Routine(
        'mul32', 'm_fixed65.s:_Mul32', (('_Dp', 8),), ('a', 'x'), SQ,
        lambda b: (le(b, 0, 4), le(b, 4, 4)),
        lambda o: b32(o[0]) + b32(o[1]),
        lambda b: (_ax(b),),
        'mul32', (('M_A', 4), ('M_B', 4)), (('M_R', 4),),
        _nat32x2, lambda b: (le(b, 0, 4),),
        lambda o, t: (m_mul32(*o),),
        _gen2x32, _edges2x32,
        doc='32 x 32 -> the low 32 bits (_Mul32)'))
    r.append(Routine(
        'fixmul', 'm_fixed65.s:FixedMul', ('a', 'x', ('_Dp', 4)),
        ('a', 'x'), SQ,
        lambda b: (_ax(b), le(b, 4, 4)),
        lambda o: b32(o[0]) + b32(o[1]),
        lambda b: (_ax(b),),
        'fixmul', (('M_A', 4), ('M_B', 4)), (('M_R', 4),),
        _nat32x2, lambda b: (le(b, 0, 4),),
        lambda o, t: (m_fixmul(*o),),
        _gen2x32, _edges2x32,
        doc='FixedMul, FixedMul3232: floor(a * b / 65536), exact'))
    r.append(Routine(
        'fixmul3216', 'm_fixed65.s:FixedMul3216', ('a', 'x', ('_Dp', 2)),
        ('a', 'x'), SQ,
        lambda b: (_ax(b), le(b, 4, 2)),
        lambda o: b32(o[0]) + b16(o[1]),
        lambda b: (_ax(b),),
        'fixmul3216', (('M_A', 4), ('M_B', 2)), (('M_R', 4),),
        lambda o: b32(o[0]) + b16(o[1]), lambda b: (le(b, 0, 4),),
        lambda o, t: (m_fixmul3216(*o),),
        lambda rng: (rand32(rng), rand16(rng)),
        lambda: [(a, b) for a in EDGE32 for b in EDGE16],
        doc='FixedMul3216: floor(a * bl / 65536), bl unsigned 16'))
    r.append(Routine(
        'fixmulang', 'p_mobj65.s:FixedMulAngle', ('a', 'x', ('_Dp', 4)),
        ('a', 'x'), SQ,
        lambda b: (_ax(b), le(b, 4, 4)),
        lambda o: b32(o[0]) + b32(o[1]),
        lambda b: (_ax(b),),
        'fixmulang', (('M_A', 4), ('M_B', 4)), (('M_R', 4),),
        _nat32x2, lambda b: (le(b, 0, 4),),
        lambda o, t: (m_fixmulang(*o),),
        _gen2x32, _edges2x32,
        doc='FixedMulAngle: FixedMul3216(a, b & 0xFFFF) - (b < 0 ? a : 0)'))

    # -- the divides (the port's own; no upstream oracle) ----------------
    def div(name, bits, signed, vendor, up_in, ops_from_up, doc):
        size = bits // 8
        mask = (1 << bits) - 1
        model = (lambda o, t: m_sdiv(o[0], o[1], bits)) if signed else \
            (lambda o, t: m_udiv(o[0], o[1], bits))
        gen = _gen2x32 if bits == 32 else _gen2x16
        edges = _edges2x32 if bits == 32 else _edges2x16
        return Routine(
            name, vendor, up_in, (), (), ops_from_up, None, None,
            name, (('M_A', size), ('M_B', size)),
            (('M_R', size), ('M_T', size)),
            lambda o: (o[0] & mask).to_bytes(size, 'little') +
            (o[1] & mask).to_bytes(size, 'little'),
            lambda b: (le(b, 0, size), le(b, size, size)),
            model, gen, edges, doc=doc)
    r.append(div('udiv16', 16, False, 'cal_integer.s:_UDivMod16',
                 ('a', 'x'), lambda b: (le(b, 0, 2), le(b, 2, 2)),
                 'unsigned 16-bit quotient and remainder (for _UDivMod16)'))
    r.append(div('sdiv16', 16, True, 'cal_integer.s:_Div16',
                 ('a', 'x'), lambda b: (le(b, 0, 2), le(b, 2, 2)),
                 'signed 16-bit quotient and remainder (for _Div16, _Mod16)'))
    r.append(div('udiv32', 32, False, 'cal_integer.s:_UDivMod32',
                 ('a', 'x', ('_Dp', 8)), lambda b: (le(b, 4, 4), le(b, 8, 4)),
                 'unsigned 32-bit quotient and remainder (for _UDivMod32)'))
    r.append(div('sdiv32', 32, True, 'cal_integer.s:_Div32',
                 ('a', 'x', ('_Dp', 8)), lambda b: (le(b, 4, 4), le(b, 8, 4)),
                 'signed 32-bit quotient and remainder (for _Div32)'))

    # -- reciprocals -----------------------------------------------------
    r.append(Routine(
        'recip', 'm_recip65.s:FixedReciprocal', ('a', 'x'), ('a', 'x'),
        SQ_REC,
        lambda b: (_ax(b),), lambda o: b32(o[0]), lambda b: (_ax(b),),
        'recip', (('M_A', 4),), (('M_R', 4),),
        lambda o: b32(o[0]), lambda b: (le(b, 0, 4),),
        lambda o, t: (m_recip(o[0], t.recip),),
        lambda rng: (rand32(rng),), lambda: [(v,) for v in EDGE32],
        doc='FixedReciprocal: 0xFFFFFFFF / v, 16 significant bits'))
    r.append(Routine(
        'recipsmall', 'm_recip65.s:FixedReciprocalSmall', ('a',),
        ('a', 'x'), SQ_REC,
        lambda b: (le(b, 0, 2),), lambda o: b16(o[0]), lambda b: (_ax(b),),
        'recipsmall', (('M_A', 2),), (('M_R', 4),),
        lambda o: b16(o[0]), lambda b: (le(b, 0, 4),),
        lambda o, t: (m_recipsmall(o[0], t.recip),),
        None, lambda: [],
        exhaustive=lambda: [(v,) for v in range(65536)],
        doc='FixedReciprocalSmall: v unsigned 16'))
    r.append(Routine(
        'recipbig', 'm_recip65.s:FixedReciprocalBig', ('a', 'x'),
        ('a', 'x'), SQ_REC,
        lambda b: (_ax(b),), lambda o: b32(o[0]), lambda b: (_ax(b),),
        'recipbig', (('M_A', 4),), (('M_R', 4),),
        lambda o: b32(o[0]), lambda b: (le(b, 0, 4),),
        lambda o, t: (m_recip(o[0], t.recip),),
        lambda rng: ((rand32(rng) | 0x10000) if rng.getrandbits(1)
                     else max(rand32(rng), 0x10000),),
        lambda: [(v,) for v in EDGE32 if v >= 0x10000],
        doc='FixedReciprocalBig: v >= 0x10000 (its callers\' domain)'))
    r.append(Routine(
        'approxdiv', 'r_iigs65.s:FixedApproxDiv', ('a', 'x', ('_Dp', 4)),
        ('a', 'x'), SQ_REC,
        lambda b: (_ax(b), le(b, 4, 4)),
        lambda o: b32(o[0]) + b32(o[1]),
        lambda b: (_ax(b),),
        'approxdiv', (('M_A', 4), ('M_B', 4)), (('M_R', 4),),
        _nat32x2, lambda b: (le(b, 0, 4),),
        lambda o, t: (m_approxdiv(o[0], o[1], t.recip),),
        _gen2x32, _edges2x32,
        doc='FixedApproxDiv: a times the reciprocal of b'))

    # -- distance and angles ----------------------------------------------
    r.append(Routine(
        'aproxdist', 'p_path65.s:P_AproxDistance', ('a', 'x', ('_Dp', 4)),
        ('a', 'x'), (),
        lambda b: (_ax(b), le(b, 4, 4)),
        lambda o: b32(o[0]) + b32(o[1]),
        lambda b: (_ax(b),),
        'aproxdist', (('M_A', 4), ('M_B', 4)), (('M_R', 4),),
        _nat32x2, lambda b: (le(b, 0, 4),),
        lambda o, t: (m_aproxdist(*o),),
        _gen2x32, _edges2x32,
        doc='P_AproxDistance'))
    r.append(Routine(
        'pta3', 'r_iigs65.s:R_PointToAngle3', ('a', 'x', ('_Dp', 4)),
        ('a', 'x'), TANTO3,
        lambda b: (_ax(b), le(b, 4, 4)),
        lambda o: b32(o[0]) + b32(o[1]),
        lambda b: (_ax(b),),
        'pta3', (('M_A', 4), ('M_B', 4)), (('M_R', 4),),
        _nat32x2, lambda b: (le(b, 0, 4),),
        lambda o, t: (m_pta3(o[0], o[1], t.tanto),),
        _gen2x32, _edges2x32,
        doc='R_PointToAngle3, the game\'s R_PointToAngle2'))
    for name, label, up_in, frm in (
            ('pta16', 'r_iigs65.s:R_PointToAngle16',
             ('a', ('_Dp', 2), ('viewx+2', 2), ('viewy+2', 2)),
             lambda b: (le(b, 0, 2), le(b, 2, 2), le(b, 4, 2), le(b, 6, 2))),
            ('pta16p', 'r_iigs65.s:pointAngle',
             ('a', 'y', ('viewx+2', 2), ('viewy+2', 2)),
             lambda b: (le(b, 0, 2), le(b, 2, 2), le(b, 4, 2), le(b, 6, 2)))):
        r.append(Routine(
            name, label, up_in, ('a',), TANTO, frm,
            lambda o: b''.join(b16(v) for v in o),
            lambda b: (le(b, 0, 2),),
            'pta16', (('M_A', 4), ('M_B', 4)), (('M_R', 2),),
            lambda o: b''.join(b16(v) for v in o),
            lambda b: (le(b, 0, 2),),
            lambda o, t: (m_pta16(o[0], o[1], o[2], o[3], t.tanto),),
            lambda rng: (rand16(rng), rand16(rng), rand16(rng),
                         rand16(rng)),
            lambda: [(a, b, c, d) for a in EDGE16[::2] for b in EDGE16[::2]
                     for c in (0, 0x4000, 0x8000, 0xC001)
                     for d in (0, 0x3FFF, 0xC000)],
            doc='R_PointToAngle16 (and pointAngle, its entry from the BSP)'))

    # -- sine and cosine -------------------------------------------------
    for name, label, tab in (('finesine', 'tables65.s:finesine', 'sine'),
                             ('finecosine', 'tables65.s:finecosine',
                              'cosine')):
        r.append(Routine(
            name, label, ('a',), ('a', 'x'), SINE,
            lambda b: (le(b, 0, 2),), lambda o: b16(o[0]),
            lambda b: (_ax(b),),
            name, (('M_A', 2),), (('M_R', 4),),
            lambda o: b16(o[0]), lambda b: (le(b, 0, 4),),
            (lambda tab: lambda o, t: (getattr(t, tab)[o[0]],))(tab),
            None, lambda: [],
            exhaustive=lambda: [(x,) for x in range(8192)],
            doc='%s: all 8,192 entries' % label.split(':')[1]))
    for name, label, model in (
            ('sineapprox', 'tables65.s:finesineapprox', m_sineapprox),
            ('cosineapprox', 'tables65.s:finecosineapprox', m_cosineapprox)):
        r.append(Routine(
            name, label, ('a',), ('a', 'x'), QUARTER,
            lambda b: (le(b, 0, 2),), lambda o: b16(o[0]),
            lambda b: (_ax(b),),
            name, (('M_A', 2),), (('M_R', 4),),
            lambda o: b16(o[0]), lambda b: (le(b, 0, 4),),
            (lambda model: lambda o, t: (model(o[0], t.quarter),))(model),
            None, lambda: [],
            exhaustive=lambda: [(x,) for x in range(65536)],
            doc='%s: every 16-bit input' % label.split(':')[1]))

    # -- random ----------------------------------------------------------
    for name, label, index, nat in (
            ('prandom', 'm_random65.s:P_Random', 'm_random65.s:prndindex',
             'MT_PRND'),
            ('mrandom', 'm_random65.s:M_Random', 'm_random65.s:rndindex',
             'MT_MRND')):
        r.append(Routine(
            name, label, ((index, 2),), ('a', (index, 2)),
            # a 16-bit load at index 255 reads the byte after the table,
            # and masks it off
            (('rndtable', 257),),
            lambda b: (le(b, 0, 2),), lambda o: b16(o[0]),
            lambda b: (le(b, 0, 2), le(b, 2, 2)),
            name, ((nat, 1),), ('A', (nat, 1)),
            lambda o: bytes([o[0] & 0xFF]),
            lambda b: (b[0], b[1]),
            lambda o, t: (t.rnd[(o[0] + 1) & 0xFF], (o[0] + 1) & 0xFF),
            None, lambda: [],
            exhaustive=lambda: [(i,) for i in range(256)],
            doc='%s: every index' % label.split(':')[1]))
    return r


ROUTINES = _routines()
BY_NAME = {r.name: r for r in ROUTINES}

# upstream routines that are logged for their inputs only: the vendor
# divides (never compared directly: the owner's decision 5; only inside
# upstream's angle routines, which call _UDivMod32, src/native/MATH.md)
VENDOR = ('udiv16', 'sdiv16', 'udiv32', 'sdiv32')
# a vendor divide logged under another native routine: _Mod16 feeds sdiv16
EXTRA_CAPTURES = (('mod16', 'cal_integer.s:_Mod16', ('a', 'x'), 'sdiv16'),)


def upstream_result(r: Routine, up_out: bytes) -> Tuple:
    """The canonical result from upstream's output bytes, reduced to what
    the native routine returns (P_Random's index is a byte natively)."""
    res = r.res_from_up(up_out)
    if r.name in ('prandom', 'mrandom'):
        return (res[0] & 0xFF, res[1] & 0xFF)
    return res


# ---------------------------------------------------------------------------
# The capture spec (tools/native/mathref.c)
# ---------------------------------------------------------------------------

def symbols():
    import json
    import sys
    sys.path.insert(0, str(ROOT / 'tools'))
    from ref816 import script
    return script.Symbols(json.loads(LINKMAP.read_text()))


def _item(sym, it) -> str:
    if isinstance(it, str):
        return it
    name, length = it
    return '%06X %d' % (sym.address(name), length)


def capture_spec() -> str:
    """The spec of every upstream routine, for `mathref capture`."""
    sym = symbols()
    lines = ['# written by tools/native/mathdefs.py']
    entries = []
    for r in ROUTINES:
        if r.upstream:
            entries.append((r.name, r.upstream, r.up_in, r.up_out,
                            r.up_tables, r.name in VENDOR))
    for name, label, up_in, _ in EXTRA_CAPTURES:
        entries.append((name, label, up_in, (), (), True))
    for name, label, up_in, up_out, tables, inonly in entries:
        lines.append('routine %s %06X%s' % (name, sym.address(label),
                                            ' inonly' if inonly else ''))
        for it in up_in:
            lines.append('in ' + _item(sym, it))
        if not inonly:
            for it in up_out:
                lines.append('out ' + _item(sym, it))
        for t in tables:
            if isinstance(t[0], int):
                lines.append('tablerange %06X %06X' % t)
            else:
                lines.append('table %06X %d' % (sym.address(t[0]), t[1]))
    return '\n'.join(lines) + '\n'


def item_bytes(items) -> int:
    return sum(2 if isinstance(it, str) else it[1] for it in items)


HEADER_BYTES = 12


class Call(NamedTuple):
    site: int
    d: int
    dbr: int
    p: int
    flags: int
    cycles: int
    inputs: bytes
    outputs: bytes


def read_log(path: Path, up_in, up_out, inputs_only: bool) -> List[Call]:
    """The records of a mathref capture log."""
    n_in = item_bytes(up_in)
    n_out = 0 if inputs_only else item_bytes(up_out)
    size = HEADER_BYTES + n_in + n_out
    data = Path(path).read_bytes()
    if len(data) % size:
        raise ValueError('%s: not whole records' % path)
    out = []
    for at in range(0, len(data), size):
        rec = data[at:at + size]
        out.append(Call(le(rec, 0, 3), le(rec, 3, 2), rec[5], rec[6],
                        rec[7], le(rec, 8, 4),
                        rec[HEADER_BYTES:HEADER_BYTES + n_in],
                        rec[HEADER_BYTES + n_in:]))
    return out
