"""The native math's tables, from the reference's RAM and from formulas.

build(load(RAM), OUT) (rtables.py: OUT is build/native/render/tables/
math) reads upstream's tables from a RAM of the running game (banks
$00-$7F), checks them, and writes the native layouts (the tables are
Doom's and upstream's data, so they stay in build/, like the WAD):

    squares.bin    the quarter squares of $D000-$D7FF (main card, bank 1):
                   f(n) = floor(n * n / 4), n = 0-511, low then high
                   bytes; then f(n - 255) the same (our formula)
    sinelo.bin, sinehi.bin
                   |finesine[x]|, x = 0-8191, low and high bytes: the
                   sign is bit 12 of x (checked on all 8,192 entries)
    cosexc.bin     the entries where finecosine[x] is not the shifted
                   sine (the magnitude at x + 2048 with the sign of bit 12
                   of x + 2048), as math.s scans them: their count, then
                   16 low bytes of x, 16 high bytes, and 16 of each byte
                   of the value (at most 16 entries; unused slots $FF)
    tanto0-3.bin   tantoangleTable, 2,049 entries, one byte plane each
    quartlo.bin, quarthi.bin
                   finesineTable_part_1, 2,048 words, low and high planes
    reciplo.bin, reciphi.bin
                   RECIP_TABLE, 32,768 words: floor((2^31 - 1) / (32768 +
                   i)), our formula, checked against the reference's table
    rndtable.bin   P_Random's 256 bytes
    tables.json    the counts and checks
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import mathdefs  # noqa: E402
from native.mathdefs import M32, Tables, le  # noqa: E402

SINE = 0x200000
COSINE = SINE + 0x8000
RECIP = 0x1E0000
COSEXC_SLOTS = 16


def peek(ram: bytes, address: int, length: int) -> bytes:
    if address + length > 0x800000:
        raise ValueError('outside banks $00-$7F')
    return ram[address:address + length]


def load(ram_path: Path) -> Tables:
    ram = Path(ram_path).read_bytes()
    sym = mathdefs.symbols()
    words = lambda at, n, size: [le(ram, at + size * i, size)  # noqa: E731
                                 for i in range(n)]
    return Tables(
        sine=words(SINE, 8192, 4), cosine=words(COSINE, 8192, 4),
        tanto=words(sym.address('tantoangleTable'), 2049, 4),
        quarter=words(sym.address('finesineTable_part_1'), 2048, 2),
        rnd=peek(ram, sym.address('rndtable'), 256),
        recip=words(RECIP, 32768, 2))


def sign_magnitude(v: int):
    s = mathdefs.s32(v)
    return s < 0, abs(s)


def build(tables: Tables, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    report = {}

    f = lambda n: n * n // 4  # noqa: E731
    squares = (bytes(f(n) & 0xFF for n in range(512)) +
               bytes(f(n) >> 8 for n in range(512)) +
               bytes(f(n - 255) & 0xFF for n in range(512)) +
               bytes(f(n - 255) >> 8 for n in range(512)))
    (out / 'squares.bin').write_bytes(squares)

    lo, hi = bytearray(), bytearray()
    for x, v in enumerate(tables.sine):
        negative, magnitude = sign_magnitude(v)
        if magnitude > 0xFFFF:
            raise ValueError('finesine[%d] = %d: more than 16 bits' % (x, v))
        if magnitude and negative != bool(x & 0x1000):
            raise ValueError('finesine[%d]: the sign is not bit 12' % x)
        lo.append(magnitude & 0xFF)
        hi.append(magnitude >> 8)
    (out / 'sinelo.bin').write_bytes(bytes(lo))
    (out / 'sinehi.bin').write_bytes(bytes(hi))

    def shifted(x):
        x2 = (x + 2048) & 8191
        m = lo[x2] | hi[x2] << 8
        return (-m) & M32 if x2 & 0x1000 else m
    exceptions = [(x, v) for x, v in enumerate(tables.cosine)
                  if shifted(x) != v]
    if len(exceptions) > COSEXC_SLOTS:
        raise ValueError('%d cosine exceptions: math.s has room for %d'
                         % (len(exceptions), COSEXC_SLOTS))
    pad = [(0xFFFF, 0xFFFFFFFF)] * (COSEXC_SLOTS - len(exceptions))
    slots = exceptions + pad
    exc = bytearray([len(exceptions)])
    exc += bytes(x & 0xFF for x, _ in slots)
    exc += bytes(x >> 8 for x, _ in slots)
    for k in range(4):
        exc += bytes((v >> (8 * k)) & 0xFF for _, v in slots)
    (out / 'cosexc.bin').write_bytes(bytes(exc))
    report['cosine_exceptions'] = [[x, v] for x, v in exceptions]

    for k in range(4):
        (out / ('tanto%d.bin' % k)).write_bytes(
            bytes((v >> (8 * k)) & 0xFF for v in tables.tanto))
    if tables.tanto[2048] != 0x20000000:
        raise ValueError('tantoangleTable[2048] is not ANG45')
    (out / 'quartlo.bin').write_bytes(bytes(v & 0xFF
                                            for v in tables.quarter))
    (out / 'quarthi.bin').write_bytes(bytes(v >> 8 for v in tables.quarter))

    formula = [mathdefs.recip_entry(i) for i in range(32768)]
    differ = sum(a != b for a, b in zip(formula, tables.recip))
    if differ:
        raise ValueError('RECIP_TABLE: %d entries differ from the formula'
                         % differ)
    report['recip_equals_formula'] = True
    (out / 'reciplo.bin').write_bytes(bytes(v & 0xFF for v in formula))
    (out / 'reciphi.bin').write_bytes(bytes(v >> 8 for v in formula))
    (out / 'rndtable.bin').write_bytes(tables.rnd)
    report['sine_sign_is_bit_12'] = True
    report['sine_magnitude_max'] = max(lo[i] | hi[i] << 8
                                       for i in range(8192))
    (out / 'tables.json').write_text(json.dumps(report, indent=1) + '\n')
    return report
