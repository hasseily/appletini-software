"""The native math (src/native/math.s) on the host: the reference's tables
(mathtables.py reads them into Tables), RECIP_TABLE's formula and the
model of recipCore (rtables.py's check of the sprite scales).

Nothing here comes from upstream's cal_integer.s (the ground rules).
"""

from pathlib import Path
from typing import List, NamedTuple, Sequence

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
LINKMAP = BUILD / 'linkmap.json'

M32 = 0xFFFFFFFF


def s32(v: int) -> int:
    v &= M32
    return v - 0x100000000 if v & 0x80000000 else v


def le(data: bytes, at: int, size: int) -> int:
    return int.from_bytes(data[at:at + size], 'little')


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


def symbols():
    import json
    import sys
    sys.path.insert(0, str(ROOT / 'tools'))
    from ref816 import script
    return script.Symbols(json.loads(LINKMAP.read_text()))
