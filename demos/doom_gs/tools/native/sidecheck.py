#!/usr/bin/env python3
"""Check A3 of docs/RENDER.md 5.1: upstream's viewSide, with its
c14Bounds log-table test, against the native nr_side, which always takes
the two shiftMul products (RENDER.md 1.9).

Usage:  python3 tools/native/sidecheck.py [--maps 1,..,9] [--random N]
                                          [--edges N] [--seed S]

For each map, from its level source (tools/native/rendercap.py: all RAM
at an R_FillStamps of the tour run): upstream's viewSide runs on ref816's
machine (tools/native/mathref.c `batch`, the machine loaded with the map's
RAM once), from the registers and return address of a real call of
viewSide (rendercap.py logs the first one) with, per case, X = node * 4,
ND = the node's address (CORE_NODEADR[X], its bank that of `nodes`),
viewx and viewy, as bspNode leaves them (r_bsp65.s:162-167, :1247-1270);
the side is the carry of P at the return. The native nr_side runs on a2vm
(src/native/rdriver.s drv_bulk and rt_side) on the node's x, y, dx, dy and
the same view. Every case must give the same side.

The cases, per map (RENDER.md 5.1, check A3), on the nodes viewSide
decides (dx and dy not 0):

  random  N views in all (default 100,000), spread over the nodes: the
          view's map units uniform over the map's bounds with a margin,
          near the node's partition line, or any 16 bits; random
          fractions
  edges   for each node with |dx|, |dy| <= 255 (the only ones c14Bounds
          decides), views whose log difference (LOGTAB and SIGHTLOG read
          from the RAM as data, r_bsp65.s:1262-1291) lies within 5 units of
          +-417 on both sides of it, the integer offsets |x| and |y| of
          15, 16 and 17, and offsets that take the overflow branch; at
          most N a map (default 1,000,000, the corners included)

and for each view of either kind the four corners of the fraction byte
that shiftMul keeps: bits 8-15 of viewx and viewy at 0 and 255 (shiftMul
drops bits 0-7; for |dx|, |dy| <= 255 the products fit in 32 bits and L -
R is linear in the two bytes, so a side that agrees at the four corners
agrees at every fraction of that integer offset).

The report counts, per map, the cases that reached each branch of
c14Bounds (a host model of upstream's code decides the branch; the
sides come from the two machines), and fails when a branch that the
map's nodes allow is not reached, or when an eligible node that has
offsets at log differences 416 and 417 has no case at them.
"""

import argparse
import bisect
import json
import random
import struct
import subprocess
import sys
import tempfile
import zlib
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge import linkmap as blink  # noqa: E402
from native import levelconv, rendercap, render_check as RC, \
    rlayout as R  # noqa: E402
from ref816 import bounded  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
MATHREF = BUILD / 'native' / 'math' / 'mathref'
OUT = BUILD / 'native' / 'render' / 'sidecheck'
MM_LOGTAB = 0x1F0000
MM_B3F = 0x210000                   # CORE_NODEADR: node address, SIGHTLOG
SIZEOF_NODE = 28
AUX_BASE, AUX_LIMIT = 0x0800, 0xC0
FIRST_BANK, LAST_BANK = 1, 115      # below FSTEP's banks (rlayout.py)
MAX_RUN = 250_000                   # cases a native run
CYCLES_A_CASE = 4_000               # a native case's cycle bound (about
                                    #   1,000 used: the call and the copies)
MAX_BATCH = 400_000                 # cases a mathref run
RUN_TIMEOUT = 1200.0

AIM = 417                           # the edge cases' target: c14Bounds'
                                    #   threshold (r_bsp65.s:1292-1296);
                                    #   the check's own 416 and 417 are
                                    #   upstream's, not this
BRANCHES = ('sign', 'miss-dx', 'miss-dy', 'miss-x-32768', 'miss-y-32768',
            'miss-x<16', 'miss-y<16', 'greater', 'less', 'overflow-greater',
            'overflow-less', 'miss-threshold')


class SideError(Exception):
    pass


def s16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class MapData:
    def __init__(self, source: Path, sym: blink.Symbols):
        self.source = source
        self.ram = zlib.decompress(source.read_bytes())
        if len(self.ram) != 130 * 0x10000:
            raise SideError('%s is not a whole RAM' % source)
        mem = levelconv.load_memory(source)
        up = levelconv.Upstream(mem, sym)
        self.nodes = up.ordered('node')
        self.gamemap = up.g('_g_gamemap')
        base = up.ptr('nodes')
        self.nodes_bank = base >> 16
        self.logtab = [self.u16(MM_LOGTAB + 2 * v) for v in range(32768)]
        self.node_addr = []
        self.k = []
        for n in range(len(self.nodes)):
            addr = self.u16(MM_B3F + 4 * n)
            if (self.nodes_bank << 16 | addr) != base + SIZEOF_NODE * n:
                raise SideError('CORE_NODEADR of node %d is not the node'
                                % n)
            self.node_addr.append(addr)
            self.k.append(self.u16(MM_B3F + 4 * n + 2))
        xs = [v for nd in self.nodes for v in nd['bbox'][2:4] +
              nd['bbox'][6:8]]
        ys = [v for nd in self.nodes for v in nd['bbox'][0:2] +
              nd['bbox'][4:6]]
        self.bounds = (min(xs), max(xs), min(ys), max(ys))

    def u16(self, address: int) -> int:
        return self.ram[address] | self.ram[address + 1] << 8


# ---------------------------------------------------------------------------
# upstream's branch, a host model of r_bsp65.s viewSide and c14Bounds
# ---------------------------------------------------------------------------

def branch(m: MapData, n: int, xhi: int, yhi: int) -> Tuple[str, int]:
    """The branch upstream's viewSide takes for node n and the view's map
    units (x, y relative to the node: xhi, yhi as 16-bit), and the log
    difference when c14Bounds computes one (else None)."""
    node = m.nodes[n]
    dx, dy = node['dx'] & 0xFFFF, node['dy'] & 0xFFFF
    xp, yp = xhi & 0xFFFF, yhi & 0xFFFF
    if (dy ^ dx ^ xp ^ yp) & 0x8000:
        return 'sign', None
    if not (-255 <= s16(dx) <= 255):
        return 'miss-dx', None
    if not (-255 <= s16(dy) <= 255):
        return 'miss-dy', None
    kk = m.k[n] & 0xFFF0
    i = (-s16(xp)) & 0xFFFF if xp & 0x8000 else xp
    if i & 0x8000:
        return 'miss-x-32768', None
    if i < 16:
        return 'miss-x<16', None
    j = (-s16(yp)) & 0xFFFF if yp & 0x8000 else yp
    if j & 0x8000:
        return 'miss-y-32768', None
    if j < 16:
        return 'miss-y<16', None
    t = (m.logtab[j] - m.logtab[i]) & 0xFFFF
    r = (t + kk) & 0xFFFF
    v = ((t ^ r) & (kk ^ r) & 0x8000) != 0
    d = s16(t) + s16(kk)
    if v:
        return ('overflow-greater' if r & 0x8000 else 'overflow-less'), d
    if r & 0x8000:
        return ('less' if r < 0x10000 - 416 else 'miss-threshold'), d
    return ('greater' if r >= 417 else 'miss-threshold'), d


# ---------------------------------------------------------------------------
# the cases: (node, viewx, viewy) with 32-bit views
# ---------------------------------------------------------------------------

def corners(n: int, xhi: int, yhi: int, rng: random.Random
            ) -> List[Tuple[int, int, int]]:
    out = []
    for bx in (0, 255):
        for by in (0, 255):
            vx = (xhi & 0xFFFF) << 16 | bx << 8 | rng.getrandbits(8)
            vy = (yhi & 0xFFFF) << 16 | by << 8 | rng.getrandbits(8)
            out.append((n, vx, vy))
    return out


def eligible(m: MapData) -> List[int]:
    return [n for n, nd in enumerate(m.nodes) if nd['dx'] and nd['dy']]


def random_cases(m: MapData, count: int, rng: random.Random
                 ) -> List[Tuple[int, int, int]]:
    nodes = eligible(m)
    x0, x1, y0, y1 = m.bounds
    out = []
    for _ in range(count):
        n = rng.choice(nodes)
        nd = m.nodes[n]
        kind = rng.random()
        if kind < 0.5:              # anywhere in the map, a margin round it
            x = rng.randint(x0 - 1024, x1 + 1024)
            y = rng.randint(y0 - 1024, y1 + 1024)
        elif kind < 0.9:            # near the partition line
            t = rng.uniform(-2.0, 3.0)
            x = int(nd['x'] + t * nd['dx']) + rng.randint(-40, 40)
            y = int(nd['y'] + t * nd['dy']) + rng.randint(-40, 40)
        else:                       # any map unit
            x = rng.getrandbits(16)
            y = rng.getrandbits(16)
        out += corners(n, x, y, rng)
    return out


def offsets_at(m: MapData, n: int, d: int) -> Optional[Tuple[int, int]]:
    """Integer offsets (|x|, |y|), 16-32767, at log difference d for node
    n (LOGTAB[y] - LOGTAB[x] + K = d), or None."""
    if not hasattr(m, 'firstat'):
        m.firstat = {}
        for i in range(16, 32768):
            m.firstat.setdefault(m.logtab[i], i)
        m.logdesc = sorted(m.firstat, reverse=True)
    c = d - s16(m.k[n] & 0xFFF0)
    for v in m.logdesc:
        i = m.firstat.get(v - c)
        if i is not None:
            return i, m.firstat[v]
    return None


def reachable_416(m: MapData, n: int) -> set:
    """The log differences +-416 and +-417 that some integer offsets of
    node n reach (LOGTAB[j] - LOGTAB[i] + K for i, j 16-32767), from the
    tables alone: the cases must include each (the check does not trust
    the generator)."""
    if not hasattr(m, 'logset'):
        m.logset = set(m.logtab[16:])
        m.logdesc = sorted(m.logset, reverse=True)
    kk = s16(m.k[n] & 0xFFF0)
    out = set()
    for d in (416, 417, -416, -417):
        c = d - kk
        if any(v - c in m.logset for v in m.logdesc):
            out.add(d)
    return out


def js_for(m: MapData, target: int) -> List[int]:
    """j (16-32767) with LOGTAB[j] == target: the first and last."""
    lo = bisect.bisect_left(m.logtab, target, 16)
    hi = bisect.bisect_right(m.logtab, target, 16) - 1
    if lo > hi or lo >= 32768 or m.logtab[lo] != target:
        return []
    return sorted({lo, hi})


def edge_cases(m: MapData, limit: int, rng: random.Random
               ) -> Tuple[List[Tuple[int, int, int]], Dict[int, set], set]:
    """The dense edges (module docstring); also, per node, the log
    differences in {+-416, +-417} that some offset reaches (the check
    requires a case at each)."""
    nodes = [n for n in eligible(m)
             if abs(m.nodes[n]['dx']) <= 255 and abs(m.nodes[n]['dy']) <= 255]
    targets = list(range(AIM - 5, AIM + 6)) + \
        list(range(-AIM - 5, -AIM + 6))
    base_is = [16, 17, 18, 19, 20, 24, 32, 48, 64, 96, 128, 192, 256, 384,
               512, 1024, 2048, 4096, 8192, 16384, 32767]
    out: List[Tuple[int, int, int]] = []
    reachable: Dict[int, set] = {}
    overflow: set = set()
    chosen: List[Tuple[int, List, List]] = []
    for n in nodes:
        nd = m.nodes[n]
        kk = s16(m.k[n] & 0xFFF0)
        dxs, dys = nd['dx'] < 0, nd['dy'] < 0
        signs = [(sx, sy) for sx in (1, -1) for sy in (1, -1)
                 if ((sx < 0) ^ (sy < 0)) == (dxs ^ dys)]
        views = []
        must = []
        reach = set()
        for i in sorted(set(base_is + [rng.randint(16, 32767)
                                       for _ in range(6)])):
            li = m.logtab[i]
            for d in targets:
                for j in js_for(m, d - kk + li):
                    sx, sy = rng.choice(signs)
                    v = (nd['x'] + sx * i, nd['y'] + sy * j)
                    if abs(d) in (AIM - 1, AIM):
                        reach.add(d)
                        must.append(v)
                    else:
                        views.append(v)
        # every log difference of +-416 and +-417 the node's K allows
        for d in (AIM - 1, AIM, 1 - AIM, -AIM):
            pair = offsets_at(m, n, d)
            if pair:
                sx, sy = rng.choice(signs)
                must.append((nd['x'] + sx * pair[0], nd['y'] + sy * pair[1]))
        # |x| and |y| of 15, 16, 17, and offsets of -32768
        for i in (15, 16, 17):
            for j in (15, 16, 17, 100, 1000):
                for sx, sy in signs:
                    must.append((nd['x'] + sx * i, nd['y'] + sy * j))
                    must.append((nd['x'] + sx * j, nd['y'] + sy * i))
        for sy in (1, -1):
            must.append((nd['x'] + 0x8000, nd['y'] + sy * 100))
            must.append((nd['x'] + sy * 100, nd['y'] + 0x8000))
        # the overflow branch: a small |x|, a large |y|, or the reverse
        for i in (16, 17, 20, 32):
            for j in (32767, 30000, 20000, 16000, 12000):
                for sx, sy in signs:
                    for a, bb in ((i, j), (j, i)):
                        x, y = nd['x'] + sx * a, nd['y'] + sy * bb
                        br, _ = branch(m, n, x - nd['x'], y - nd['y'])
                        if br.startswith('overflow'):
                            must.append((x, y))
                            overflow.add(br)
        reachable[n] = reach
        rng.shuffle(views)
        chosen.append((n, must, views))
    # every node's must cases, then its share of the rest of the budget
    room = limit // 4 - sum(len(mu) for _, mu, _ in chosen)
    share = max(0, room // max(1, len(chosen)))
    for n, must, views in chosen:
        for x, y in must + views[:share]:
            out += corners(n, x, y, rng)
    return out, reachable, overflow


# ---------------------------------------------------------------------------
# ref816: mathref batch
# ---------------------------------------------------------------------------

def entry_text(sym: blink.Symbols, viewside: Dict, switches: Dict) -> str:
    r = viewside['in']
    ret = bytes.fromhex(r['mem'][0])
    return ('pc %06X\ndbr %02X\nd %04X\np %02X\ne %d\ns %04X\na %04X\n'
            'x %04X\ny %04X\nret 2\nstack %02X %02X\n'
            'switches %02X %02X %02X %02X\n' % (
                sym.address('r_bsp65.s:viewSide'), r['dbr'], r['d'],
                r['p'], r['e'], r['s'], r['a'], r['x'], r['y'], ret[0],
                ret[1], switches['newvideo'], switches['border'],
                switches['shadow'], switches['speed']))


def nd_address(sym: blink.Symbols, d: int) -> int:
    """ND (_Dp + 12) as the direct page of the call places it."""
    ztiny = sym.sections['ztiny']['first']
    return (d + sym.address('_Dp') + 12 - ztiny) & 0xFFFF


def spec_text(sym: blink.Symbols, nd: int) -> str:
    return ('routine viewside %06X\nin x\nin %06X 3\nin %06X 4\nin %06X 4\n'
            'out p\n' % (sym.address('r_bsp65.s:viewSide'), nd,
                         sym.address('viewx'), sym.address('viewy')))


def reference_sides(m: MapData, cases, sym: blink.Symbols,
                    viewside: Dict, switches: Dict, work: Path) -> bytes:
    if not MATHREF.exists():
        raise SideError('%s is missing: make -C tools/native' % MATHREF)
    (work / 'base.ram').write_bytes(m.ram)
    (work / 'viewside.entry').write_text(entry_text(sym, viewside,
                                                    switches))
    nd = nd_address(sym, viewside['in']['d'])
    (work / 'spec.txt').write_text(spec_text(sym, nd))
    out = bytearray()
    for at in range(0, len(cases), MAX_BATCH):
        raw = bytearray()
        for n, vx, vy in cases[at:at + MAX_BATCH]:
            raw += struct.pack('<HHBII', 4 * n, m.node_addr[n],
                               m.nodes_bank, vx, vy)
        (work / 'cases.bin').write_bytes(raw)
        result = bounded.run(
            ['nice', '-n', '10', str(MATHREF), 'batch',
             str(work / 'base.ram'), str(work / 'viewside.entry'),
             str(work / 'spec.txt'), 'viewside', str(work / 'cases.bin'),
             str(work / 'out.bin')], timeout=RUN_TIMEOUT,
            max_bytes=64 << 20, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, universal_newlines=True)
        if result.returncode:
            raise SideError('mathref batch failed: %s' % result.stdout)
        data = (work / 'out.bin').read_bytes()
        out += bytes(data[k] & 1 for k in range(0, len(data), 6))
    return bytes(out)


# ---------------------------------------------------------------------------
# a2vm: drv_bulk on rt_side
# ---------------------------------------------------------------------------

def descriptor(entry: int, nin: int, nout: int, count: int, inbank: int,
               outbank: int, in_places: Sequence[int],
               out_places: Sequence[int]) -> bytes:
    d = bytearray(80)
    struct.pack_into('<HBB', d, 0, entry, nin, nout)
    d[4:7] = count.to_bytes(3, 'little')
    d[7], d[8] = inbank, outbank
    struct.pack_into('<HHB', d, 9, AUX_BASE, AUX_BASE, AUX_LIMIT)
    for i, a in enumerate(in_places):
        d[16 + i], d[32 + i] = a & 0xFF, a >> 8
    for i, a in enumerate(out_places):
        d[48 + i], d[64 + i] = a & 0xFF, a >> 8
    return bytes(d)


def bulk(b: RC.Build, entry: str, in_places: Sequence[int],
         out_places: Sequence[int], cases: Sequence[bytes],
         work: Path) -> List[bytes]:
    """drv_bulk of the render test build: each case's bytes to the
    places, the routine called, the output places' bytes back."""
    nin, nout = len(in_places), len(out_places)
    assert nin in (1, 2, 4, 8, 16) and nout in (1, 2, 4, 8, 16)
    per_in = (0xC000 - AUX_BASE) // nin
    per_out = (0xC000 - AUX_BASE) // nout
    out: List[bytes] = []
    base = RC.base_records(b, 0)
    for at in range(0, len(cases), MAX_RUN):
        chunk = cases[at:at + MAX_RUN]
        recs = list(base)
        raw = b''.join(chunk)
        bank = FIRST_BANK
        for k in range(0, len(raw), per_in * nin):
            recs.append((1, bank, AUX_BASE, raw[k:k + per_in * nin]))
            bank += 1
        outbank = bank
        last = outbank + -(-len(chunk) // per_out) - 1
        if last > LAST_BANK:
            raise SideError('too many cases for one run')
        recs.append((2, 0, b.labels['drv_desc'], descriptor(
            b.labels[entry], nin, nout, len(chunk), FIRST_BANK, outbank,
            in_places, out_places)))
        state = RC.a2vm_run(b, recs, work, [], [
            '--snapshot-ranges', 'aux%d-%d:%X-%X' % (
                outbank, last, AUX_BASE, (AUX_LIMIT << 8) - 1),
            '--final-snapshot'], start='drv_bulk',
            cycles=CYCLES_A_CASE * len(chunk) + 10_000_000,
            timeout=RUN_TIMEOUT)
        if state.get('pc') != b.labels['drv_halt']:
            raise SideError('the bulk run ended at $%04X' % state.get('pc',
                                                                     -1))
        shot = [p for p in work.glob('*.img') if p.name != 'image.bin']
        if len(shot) != 1:
            raise SideError('no final snapshot')
        mem: Dict[int, bytearray] = {}
        for kind, bnk, address, data in levelconv.Image.parse(
                shot[0].read_bytes()):
            m = mem.setdefault(bnk, bytearray(0x10000))
            m[address:address + len(data)] = data
        shot[0].unlink()
        for i in range(len(chunk)):
            bnk = outbank + i // per_out
            a = AUX_BASE + (i % per_out) * nout
            out.append(bytes(mem[bnk][a:a + nout]))
    return out


def native_sides(b: RC.Build, m: MapData, cases, work: Path) -> bytes:
    F = R.FRAME
    places = [R.NODEF + k for k in range(8)] + \
        [F['VIEWX'] + k for k in range(4)] + [F['VIEWY'] + k
                                             for k in range(4)]
    raw = []
    for n, vx, vy in cases:
        nd = m.nodes[n]
        raw.append(struct.pack('<hhhhII', nd['x'], nd['y'], nd['dx'],
                               nd['dy'], vx, vy))
    res = bulk(b, 'rt_side', places, [b.labels['DRV_OA']], raw, work)
    return bytes(r[0] for r in res)


# ---------------------------------------------------------------------------
# R_WallLight against nr_walllight (for stage B, checked here)
# ---------------------------------------------------------------------------

def walllight_cases() -> List[Tuple[int, int, int, int]]:
    """(light, normal angle, LT_BASE, LT_FIXED): every light level, the
    angles that take each path, extralight 0-2 and gamma 0-4, no fixed
    colormap and the fixed ones upstream makes (n * 256)."""
    angles = (0, 0x4000, 0x8000, 0xC000, 1, 0x4001, 0x3FFF, 0xFFFF, 0x2468,
              0xC001)
    fixed = (0xFFFF, 0, 0x0100, 0x2000, 0x2100)
    return [(light, angle, 16 + extra + gamma, f)
            for light in range(256) for angle in angles
            for extra in range(3) for gamma in range(5)
            for f in fixed][::3]


def walllight_check(b: RC.Build, sym: blink.Symbols, work: Path) -> Dict:
    """Upstream's R_WallLight (mathref batch, from a JSL entry with
    the C code's direct page and the near bank) against nr_walllight
    (drv_bulk): the offset returned and LT_I."""
    source = sorted(rendercap.LEVEL_SOURCES.glob('tour-e1m1-*.ram.z'))[0]
    ram = zlib.decompress(source.read_bytes())
    (work / 'base.ram').write_bytes(ram)
    viewside = json.loads((rendercap.LEVEL_SOURCES / 'tour-viewside.json')
                          .read_text())['in']
    info = json.loads(source.with_suffix('').with_suffix('.json')
                      .read_text())
    sw = info['switches']
    (work / 'wl.entry').write_text(
        'pc %06X\ndbr %02X\nd %04X\np 00\ne 0\ns %04X\na 0000\n'
        'x 0000\ny 0000\nret 3\nstack 00 00 00\n'
        'switches %02X %02X %02X %02X\n' % (
            sym.address('R_WallLight'), viewside['dbr'], viewside['d'],
            viewside['s'], sw['newvideo'], sw['border'], sw['shadow'],
            sw['speed']))
    (work / 'wl.spec').write_text(
        'routine walllight %06X\nin a\nin y\nin %06X 2\nin %06X 2\n'
        'out a\nout %06X 2\n' % (
            sym.address('R_WallLight'), sym.address('LT_BASE'),
            sym.address('LT_FIXED'), sym.address('LT_I')))
    cases = walllight_cases()
    raw = b''.join(struct.pack('<HHHH', li, an, lb, lf)
                   for li, an, lb, lf in cases)
    (work / 'wl.cases').write_bytes(raw)
    result = bounded.run(
        ['nice', '-n', '10', str(MATHREF), 'batch', str(work / 'base.ram'),
         str(work / 'wl.entry'), str(work / 'wl.spec'), 'walllight',
         str(work / 'wl.cases'), str(work / 'wl.out')],
        timeout=RUN_TIMEOUT, max_bytes=64 << 20, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, universal_newlines=True)
    if result.returncode:
        raise SideError('mathref batch failed: %s' % result.stdout)
    out = (work / 'wl.out').read_bytes()
    ref = [struct.unpack_from('<HH', out, 8 * k) for k in range(len(cases))]
    lab = b.labels
    F = R.FRAME
    places = [lab['DRV_IA'], lab['DRV_IX'], lab['DRV_IY'], F['LT_BASE'],
              F['LT_BASE'] + 1, F['LT_FIXED'], F['LT_FIXED'] + 1,
              F['LT_BASE']]
    nat_in = [bytes([li, an & 0xFF, an >> 8, lb & 0xFF, lb >> 8,
                     lf & 0xFF, lf >> 8, lb & 0xFF])
              for li, an, lb, lf in cases]
    res = bulk(b, 'nr_walllight', places,
               [lab['DRV_OA'], lab['DRV_OX'], F['LT_I'], F['LT_I'] + 1],
               nat_in, work)
    nat = [(r[0] | r[1] << 8, r[2] | r[3] << 8) for r in res]
    diffs = [k for k in range(len(cases)) if ref[k] != nat[k]]
    return {'cases': len(cases), 'differ': len(diffs),
            'first': None if not diffs else {
                'case': cases[diffs[0]], 'upstream': ref[diffs[0]],
                'native': nat[diffs[0]]}}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def check_map(gamemap: int, sym: blink.Symbols, b: RC.Build,
              n_random: int, n_edges: int, seed: int) -> Dict:
    sources = sorted(rendercap.LEVEL_SOURCES.glob('tour-e1m%d-*.ram.z'
                                                  % gamemap))
    if not sources:
        raise SideError('no level source of E1M%d' % gamemap)
    source = sources[0]
    m = MapData(source, sym)
    info = json.loads(source.with_suffix('').with_suffix('.json')
                      .read_text())
    viewside = json.loads((rendercap.LEVEL_SOURCES / 'tour-viewside.json')
                          .read_text())
    rng = random.Random(seed * 100 + gamemap)
    cases = random_cases(m, n_random, rng)
    edges, reachable, overflow = edge_cases(m, n_edges, rng)
    all_cases = cases + edges
    work = Path(tempfile.mkdtemp(prefix='tmp-render-side-',
                                 dir=str(BUILD)))
    try:
        ref = reference_sides(m, all_cases, sym, viewside,
                              info['switches'], work)
        nat = native_sides(b, m, all_cases, work)
    finally:
        import shutil
        shutil.rmtree(str(work), ignore_errors=True)
    diffs = [k for k in range(len(all_cases)) if ref[k] != nat[k]]
    counts: Counter = Counter()
    got_d: Dict[int, set] = {}
    for n, vx, vy in all_cases:
        nd = m.nodes[n]
        br, d = branch(m, n, (vx >> 16) - nd['x'], (vy >> 16) - nd['y'])
        counts[br] += 1
        if d is not None and abs(d) in (416, 417):
            got_d.setdefault(n, set()).add(d)
    problems = []
    small = [n for n in eligible(m) if abs(m.nodes[n]['dx']) <= 255 and
             abs(m.nodes[n]['dy']) <= 255]
    large = [n for n in eligible(m) if n not in small]
    need = ['sign', 'greater', 'less', 'miss-threshold', 'miss-x<16',
            'miss-y<16', 'miss-x-32768', 'miss-y-32768'] if small else []
    if any(abs(m.nodes[n]['dx']) > 255 for n in large):
        need.append('miss-dx')
    if any(abs(m.nodes[n]['dx']) <= 255 and abs(m.nodes[n]['dy']) > 255
           for n in large):
        need.append('miss-dy')
    # the overflow branch: t + K overflows 16 bits only when |K| reaches
    # 32768 - (LOGTAB[32767] - LOGTAB[16]) (t = LOGTAB[j] - LOGTAB[i],
    # i, j 16-32767); required when a node's K allows it
    tmax = m.logtab[32767] - m.logtab[16]
    ks = [s16(m.k[n] & 0xFFF0) for n in small]
    if any(k >= 32768 - tmax for k in ks):
        need.append('overflow-greater')
    if any(k <= -32768 + tmax for k in ks):
        need.append('overflow-less')
    need += sorted(overflow - set(need))
    for k in need:
        if not counts[k]:
            problems.append('branch %s not reached' % k)
    for n in small:
        want = reachable_416(m, n)
        missing = want - got_d.get(n, set())
        if missing:
            problems.append('node %d: no case at log difference %s'
                            % (n, sorted(missing)))
    if diffs:
        n, vx, vy = all_cases[diffs[0]]
        problems.append('%d sides differ; the first: node %d view '
                        '(%08X, %08X): upstream %d, native %d' % (
                            len(diffs), n, vx, vy, ref[diffs[0]],
                            nat[diffs[0]]))
    return {'map': 'E1M%d' % gamemap, 'source': source.name,
            'nodes': len(m.nodes), 'eligible': len(eligible(m)),
            'c14_nodes': len(small), 'random_cases': len(cases),
            'edge_cases': len(edges), 'differ': len(diffs),
            'branches': {k: counts[k] for k in BRANCHES},
            'nodes_at_416_417': sum(1 for n in small if got_d.get(n)),
            'overflow_bound': {'K_range': [min(ks), max(ks)] if ks else None,
                               'needs_abs_K': 32768 - tmax},
            'required': need,
            'problems': problems}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--maps', default='1,2,3,4,5,6,7,8,9')
    parser.add_argument('--random', type=int, default=100_000)
    parser.add_argument('--edges', type=int, default=1_000_000)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--obj', type=Path, default=RC.OBJ)
    parser.add_argument('--source', type=Path, default=RC.SOURCE)
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--walllight', action='store_true',
                        help='check nr_walllight against R_WallLight too')
    args = parser.parse_args(argv)
    if not args.no_build:
        RC.make(args.obj, args.source)
    sym = blink.Symbols()
    b = RC.load_build(args.obj)
    results = []
    failed = False
    if args.walllight:
        work = Path(tempfile.mkdtemp(prefix='tmp-render-wl-',
                                     dir=str(BUILD)))
        try:
            r = walllight_check(b, sym, work)
        finally:
            import shutil
            shutil.rmtree(str(work), ignore_errors=True)
        print('R_WallLight: %d cases, %d differ%s' % (
            r['cases'], r['differ'], '' if not r['first'] else
            '; the first %r' % r['first']))
        failed = failed or bool(r['differ'])
    for g in (int(x) for x in args.maps.split(',') if x):
        try:
            r = check_map(g, sym, b, args.random, args.edges, args.seed)
        except SideError as e:
            r = {'map': 'E1M%d' % g, 'problems': [str(e)]}
        results.append(r)
        failed = failed or bool(r['problems'])
        if 'differ' in r:
            print('%s: %d nodes (%d decided by viewSide, %d by c14Bounds), '
                  '%d random + %d edge cases, %d differ; branches %s'
                  % (r['map'], r['nodes'], r['eligible'], r['c14_nodes'],
                     r['random_cases'], r['edge_cases'], r['differ'],
                     json.dumps(r['branches'])), flush=True)
        for p in r['problems'][:8]:
            print('    ' + p)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=1) + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
