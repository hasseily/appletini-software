#!/usr/bin/env python3
"""Run the native math on a2vm, many cases a run.

The build is src/native/math.mk's (build/native/math/obj/mathtest.*): the
math at its places (the products in the main card's bank 1 at $D800, the
table reads at $DC00, the rest in W at $6000, the quarter squares at
$D000) and the test driver of src/native/mathdrv.s in the card at $E000.
The tables go into RamWorks banks MT_TBANK, MT_RLO and MT_RHI as math.inc
places them (from build/native/math/tables, tools/native/mathtables.py).

A run puts the cases of one routine in memory, lets the driver call the
routine once a case, and reads the results from the final snapshot:

    bulk  cases and results in RamWorks banks 1-119 (RAMRD and RAMWRT
          windows between the calls), as many as fit; for correctness
    main  up to 8 KB of cases at $8000 and of results at $A000, no
          window between the calls; for the costs: the 65C02 cycles of a
          call (a run of the routine less a run of a bare RTS, plus the
          RTS's 6) and, with a2vm's cost model (tools/a2vm/README.md,
          "The cost model"), its time on F1.2.1 (f121) and with the
          firmware design (fastpath), the driver marking the call as
          phase 1

a2vm is used as it is, through its command line: nothing in tools/a2vm is
changed.

    python3 tools/native/mathrun.py --sizes     the bytes of each area and
                                                routine
"""

import argparse
import json
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from a2vm import costs  # noqa: E402
from native import mathdefs  # noqa: E402

ROOT = mathdefs.ROOT
MATH = mathdefs.MATH
OBJ = MATH / 'obj'
TABLES = MATH / 'tables'
SOURCE = ROOT / 'src' / 'native'
A2VM = ROOT / 'build' / 'a2vm' / 'a2vm'

AUX_BASE = 0x0800           # cases and results in a bank: $0800-$BFFF
AUX_LIMIT = 0xC0
AUX_BYTES = (AUX_LIMIT << 8) - AUX_BASE
FIRST_BANK = 1
LAST_BANK = 119             # below the tables banks (math.inc)
MAIN_IN, MAIN_OUT, MAIN_BYTES = 0x8000, 0xA000, 0x2000
PAD = 0xF2                  # a byte of the driver's zero page, for padding
RTS_CYCLES = 6
CYCLE_LIMIT = 40_000_000_000

# the snapshot's RAM (tools/a2vm/main.c)
LC = 0x10000
LC1 = 0x14000
AUX = 0x15000


def aux_offset(bank: int, address: int) -> int:
    return AUX + bank * 0x10000 + address


def use_build(obj: Path, source: Path = SOURCE) -> None:
    """Use another build (the tests' scratch copies with planted bugs)."""
    global OBJ, SOURCE
    OBJ, SOURCE = Path(obj), Path(source)


def labels(path: Optional[Path] = None) -> Dict[str, int]:
    out = {}
    path = path or OBJ / 'mathtest.lbl'
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == 'al':
            out[parts[2].lstrip('.')] = int(parts[1], 16)
    return out


def constants(path: Optional[Path] = None) -> Dict[str, int]:
    """The literal constants of math.inc (NAME = $hex or decimal)."""
    out = {}
    path = path or SOURCE / 'math.inc'
    for line in Path(path).read_text().splitlines():
        m = re.match(r'^(\w+)\s*=\s*(\$[0-9A-Fa-f]+|\d+)\s*(;.*)?$', line)
        if m:
            v = m.group(2)
            out[m.group(1)] = int(v[1:], 16) if v[0] == '$' else int(v)
    return out


def segments(path: Optional[Path] = None) -> Dict[str, Tuple[int, int]]:
    """Segment -> (start, end inclusive) from ld65's map."""
    out = {}
    text = Path(path or OBJ / 'mathtest.map').read_text()
    for m in re.finditer(r'^(\w+)\s+([0-9A-F]{6})\s+([0-9A-F]{6})\s+'
                         r'([0-9A-F]{6})', text, re.M):
        out[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16))
    return out


class Image:
    """A2VMIMG1 records (tools/a2vm/main.c load_image)."""

    def __init__(self):
        self.data = bytearray(b'A2VMIMG1')

    def add(self, kind: int, bank: int, address: int, data: bytes) -> None:
        for at in range(0, len(data), 0x8000):
            chunk = data[at:at + 0x8000]
            self.data += struct.pack('<BBHI', kind, bank, address + at,
                                     len(chunk))
            self.data += chunk


def check_build() -> Optional[str]:
    for name in ('mathtest.lc1', 'mathtest.far', 'mathtest.w',
                 'mathtest.lce', 'mathtest.lbl', 'mathtest.map'):
        if not (OBJ / name).exists():
            return '%s is missing: make -C src/native -f math.mk' % (
                OBJ / name)
    for name in ('squares.bin', 'sinelo.bin', 'reciplo.bin'):
        if not (TABLES / name).exists():
            return '%s is missing: make -C src/native -f math.mk tables' % (
                TABLES / name)
    if not A2VM.exists():
        return '%s is missing: make -C tools/a2vm' % A2VM
    return None


def base_image() -> Image:
    """The code, the quarter squares and the RamWorks tables."""
    c = constants()
    img = Image()
    img.add(3, 0, c['SQL'], (TABLES / 'squares.bin').read_bytes())
    img.add(3, 0, 0xD800, (OBJ / 'mathtest.lc1').read_bytes())
    img.add(3, 0, 0xDC00, (OBJ / 'mathtest.far').read_bytes())
    img.add(0, 0, 0x6000, (OBJ / 'mathtest.w').read_bytes())
    img.add(2, 0, 0xE000, (OBJ / 'mathtest.lce').read_bytes())
    t = c['MT_TBANK']
    img.add(1, t, c['SINELO'], (TABLES / 'sinelo.bin').read_bytes())
    img.add(1, t, c['SINEHI'], (TABLES / 'sinehi.bin').read_bytes())
    for k in range(4):
        img.add(1, t, c['TANTO0'] + 256 * c['TANTO_STRIDE'] * k,
                (TABLES / ('tanto%d.bin' % k)).read_bytes())
    img.add(1, t, c['QUARTLO'], (TABLES / 'quartlo.bin').read_bytes())
    img.add(1, t, c['QUARTHI'], (TABLES / 'quarthi.bin').read_bytes())
    img.add(1, c['MT_RLO'], c['RECIPT'],
            (TABLES / 'reciplo.bin').read_bytes())
    img.add(1, c['MT_RHI'], c['RECIPT'],
            (TABLES / 'reciphi.bin').read_bytes())
    return img


def power_of_two(n: int) -> int:
    p = 1
    while p < n:
        p *= 2
    return p


class Layout(NamedTuple):
    """Where the driver moves each byte of a case and of a result."""
    entry: int
    nin: int
    nout: int
    in_places: List[int]
    out_places: List[int]


REGS_IN = {'A': 'DRV_IA', 'X': 'DRV_IX', 'Y': 'DRV_IY'}
REGS_OUT = {'A': 'DRV_OA', 'X': 'DRV_OX', 'Y': 'DRV_OY'}


def layout(r: mathdefs.Routine, lab: Dict[str, int],
           stub: bool = False) -> Layout:
    def places(items, regs):
        out = []
        for it in items:
            if isinstance(it, str):
                out.append(lab[regs[it]])
            else:
                name, length = it
                out += [lab[name] + k for k in range(length)]
        return out
    ins = places(r.nat_in, REGS_IN)
    outs = places(r.nat_out, REGS_OUT)
    nin, nout = power_of_two(len(ins)), power_of_two(len(outs))
    if nin > 16 or nout > 16:
        raise ValueError('%s: too many bytes' % r.name)
    entry = lab['drv_stub'] if stub else lab[r.native]
    return Layout(entry, nin, nout, ins + [PAD] * (nin - len(ins)),
                  outs + [PAD] * (nout - len(outs)))


def descriptor(lay: Layout, count: int, inbank: int, outbank: int,
               inbase: int, outbase: int, limit: int) -> bytes:
    d = bytearray(80)
    struct.pack_into('<HBB', d, 0, lay.entry, lay.nin, lay.nout)
    d[4:7] = count.to_bytes(3, 'little')
    d[7], d[8] = inbank, outbank
    struct.pack_into('<HHB', d, 9, inbase, outbase, limit)
    for i, a in enumerate(lay.in_places):
        d[16 + i], d[32 + i] = a & 0xFF, a >> 8
    for i, a in enumerate(lay.out_places):
        d[48 + i], d[64 + i] = a & 0xFF, a >> 8
    return bytes(d)


class Run(NamedTuple):
    results: List[bytes]        # the output bytes of each case
    state: Dict
    cost: Optional[Dict]
    write_log: Optional[str]


def capacity(nin: int, nout: int) -> int:
    """Cases a bulk run holds."""
    per_bank_in = AUX_BYTES // nin
    per_bank_out = AUX_BYTES // nout
    banks = LAST_BANK - FIRST_BANK + 1
    lo, hi = 0, banks * max(per_bank_in, per_bank_out)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        need = -(-mid // per_bank_in) + -(-mid // per_bank_out)
        if need <= banks:
            lo = mid
        else:
            hi = mid - 1
    return lo


def run(r: mathdefs.Routine, cases: Sequence[bytes], mode: str = 'bulk',
        profile: Optional[str] = None, stub: bool = False,
        write_log: bool = False, lowest_s: bool = False,
        workdir: Optional[Path] = None) -> Run:
    """One a2vm run of routine r (or of the driver's bare RTS, stub) on the
    cases (each the native input bytes, unpadded)."""
    lab = labels()
    lay = layout(r, lab, stub)
    count = len(cases)
    img = base_image()
    raw = b''.join(c + bytes(lay.nin - len(c)) for c in cases)
    if mode == 'main':
        if count * lay.nin > MAIN_BYTES or count * lay.nout > MAIN_BYTES:
            raise ValueError('too many cases for main memory')
        img.add(0, 0, MAIN_IN, raw)
        desc = descriptor(lay, count, 0, 0, MAIN_IN, MAIN_OUT, 0xFF)
        outbank0 = 0
    else:
        if count > capacity(lay.nin, lay.nout):
            raise ValueError('too many cases for one run')
        bank = FIRST_BANK
        per_bank = AUX_BYTES // lay.nin * lay.nin
        for at in range(0, len(raw), per_bank):
            img.add(1, bank, AUX_BASE, raw[at:at + per_bank])
            bank += 1
        outbank0 = bank
        desc = descriptor(lay, count, FIRST_BANK, outbank0, AUX_BASE,
                          AUX_BASE, AUX_LIMIT)
    img.add(2, 0, lab['drv_desc'], desc)

    temp = None
    if workdir is None:
        temp = tempfile.TemporaryDirectory(prefix='mathrun-',
                                           dir=str(MATH))
        workdir = Path(temp.name)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        (workdir / 'image.bin').write_bytes(bytes(img.data))
        rom = workdir / 'rom.bin'
        rom.write_bytes(bytes(0x4000))
        args = [str(A2VM), '--rom', str(rom), '--core', 'w65c02s',
                '--io-cycles', '0',
                '--image', str(workdir / 'image.bin'),
                '--switch', 'lc_read=1', '--switch', 'lc_write=1',
                '--switch', 'lc_bank2=0',
                '--reg', 'pc=%X' % lab['drv_start'], '--reg', 'p=34',
                '--stop-pc', '%X' % lab['drv_halt'],
                '--cycles', str(CYCLE_LIMIT),
                '--state', str(workdir / 'state.json'),
                '--snapshot-dir', str(workdir), '--final-snapshot']
        if mode == 'main':
            args += ['--snapshot-ranges', 'main:%X-%X' % (
                MAIN_OUT, MAIN_OUT + count * lay.nout - 1)]
        else:
            last = outbank0 + -(-count * lay.nout // AUX_BYTES) - 1
            args += ['--snapshot-ranges', 'aux%d-%d:%X-%X' % (
                outbank0, last, AUX_BASE, (AUX_LIMIT << 8) - 1)]
        if write_log:
            args += ['--write-log', 'main,lc,lc1,aux0-127,cpu:C000-C0FF',
                     '--write-log-file', str(workdir / 'writes.log')]
        if lowest_s:
            seg = segments()
            ranges = ','.join('%X-%X' % seg[s] for s in
                              ('MATHLC', 'MATHFAR', 'MATHW') if s in seg)
            args += ['--lowest-s-in', ranges]
        report = workdir / 'cost.json'
        if profile:
            (workdir / 'cost.txt').write_text(costs.text(profile))
            args += ['--cost', str(workdir / 'cost.txt'), '--cost-timed',
                     '--cost-phase', '%X' % lab['PHASE'],
                     '--cost-report', str(report)]
        result = subprocess.run(['nice', '-n', '10'] + args,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                universal_newlines=True)
        state_path = workdir / 'state.json'
        if not state_path.exists():
            raise RuntimeError('a2vm failed: %s' % result.stdout)
        state = json.loads(state_path.read_text())
        if state.get('pc') != lab['drv_halt']:
            raise RuntimeError('a2vm stopped at $%04X, not the driver\'s '
                               'halt: %s' % (state.get('pc', -1),
                                             json.dumps(state)[:400]))
        results = read_results(workdir, lay, count, mode, outbank0)
        cost = None
        if profile and report.exists():
            text = report.read_text()
            cost = json.loads(text[text.rfind('{"final"'):])['cost']
            cost['fabric_mhz'] = costs.parameters(profile)['fabric_mhz']
        log = (workdir / 'writes.log').read_text() if write_log else None
        return Run(results, state, cost, log)
    finally:
        if temp is not None:
            temp.cleanup()


def read_image_records(path: Path) -> Dict[Tuple[int, int], bytes]:
    """(kind, bank) -> {address: bytes} records of an A2VMIMG1 snapshot."""
    data = path.read_bytes()
    if data[:8] != b'A2VMIMG1':
        raise ValueError('%s is not an A2VMIMG1 image' % path)
    out = {}
    at = 8
    while at < len(data):
        kind, bank, address, length = struct.unpack_from('<BBHI', data, at)
        at += 8
        out.setdefault((kind, bank), []).append((address,
                                                 data[at:at + length]))
        at += length
    return out


def read_results(workdir: Path, lay: Layout, count: int, mode: str,
                 outbank0: int) -> List[bytes]:
    shot = next(iter(sorted(workdir.glob('*.img'))), None)
    if shot is None or shot.name == 'image.bin':
        shots = [p for p in workdir.glob('*.img') if p.name != 'image.bin']
        if not shots:
            raise RuntimeError('no snapshot in %s' % workdir)
        shot = shots[0]
    records = read_image_records(shot)

    def memory(kind, bank):
        mem = bytearray(0x10000)
        for address, data in records.get((kind, bank), []):
            mem[address:address + len(data)] = data
        return mem
    out = []
    if mode == 'main':
        mem = memory(0, 0)
        for i in range(count):
            at = MAIN_OUT + i * lay.nout
            out.append(bytes(mem[at:at + lay.nout]))
        return out
    per_bank = AUX_BYTES // lay.nout
    cache = {}
    for i in range(count):
        bank = outbank0 + i // per_bank
        if bank not in cache:
            cache.clear()
            cache[bank] = memory(1, bank)
        at = AUX_BASE + (i % per_bank) * lay.nout
        out.append(bytes(cache[bank][at:at + lay.nout]))
    return out


def run_all(r: mathdefs.Routine, cases: Sequence[bytes],
            jobs: int = 1) -> List[bytes]:
    """Bulk runs of as many cases as needed."""
    lab = labels()
    lay = layout(r, lab)
    per = capacity(lay.nin, lay.nout)
    chunks = [cases[i:i + per] for i in range(0, len(cases), per)]
    if jobs <= 1 or len(chunks) == 1:
        out = []
        for chunk in chunks:
            out += run(r, chunk).results
        return out
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(jobs, 2)) as pool:
        parts = list(pool.map(lambda c: run(r, c).results, chunks))
    return [x for part in parts for x in part]


# ---------------------------------------------------------------------------
# Sizes
# ---------------------------------------------------------------------------

# the code each routine runs besides its own, for "with what it calls"
CALLEES = {
    'umul16': ['mulw'], 'qmulh': ['umul16', 'mulw'],
    'fixmul': ['mulw'], 'fixmul3216': ['fixmul', 'mulw'],
    'fixmulang': ['fixmul3216', 'fixmul', 'mulw'], 'mul32': ['mulw'],
    'sdiv16': ['udiv16'], 'sdiv32': ['udiv32'],
    'recip': ['mt_recipe'], 'recipsmall': ['recip', 'mt_recipe'],
    'recipbig': ['mt_recipe'],
    'approxdiv': ['recip', 'mt_recipe', 'fixmul3216', 'fixmul', 'mulw'],
    'pta3': ['pta_oct', 'pta_tab', 'udiv32', 'mt_far'],
    'pta16': ['pta_tab', 'udiv32', 'mt_far'],
    'finesine': ['mt_far'], 'finecosine': ['finesine', 'cosexc', 'mt_far'],
    'sineapprox': ['mt_far'], 'cosineapprox': ['sineapprox', 'mt_far'],
    'prandom': ['rndtable'], 'mrandom': ['rndtable'],
}
# entries that fall into the routine after them (their code is that one's)
FALLS_INTO = {'fixmul3216': 'fixmul', 'recipsmall': 'recip',
              'cosineapprox': 'sineapprox', 'finecosine': 'finesine'}


def exports(path: Optional[Path] = None) -> List[str]:
    """The names math.s exports (.export lines)."""
    out = []
    for line in Path(path or SOURCE / 'math.s').read_text().splitlines():
        m = re.match(r'\s*\.export(zp)?\s+(.*?)\s*(;.*)?$', line)
        if m:
            out += [n.strip() for n in m.group(2).split(',') if n.strip()]
    return out


# exported labels inside the code that are not routines
NOT_ROUTINES = ('SQL', 'MT_PRND', 'MT_MRND', 'mt_far_count',
                'mt_far_stride')


def routine_sizes() -> Dict[str, int]:
    """Each exported code label's bytes: to the next exported code label
    of its segment (so a routine includes its local helpers and data)."""
    lab = labels()
    seg = segments()
    names = set(exports()) - set(NOT_ROUTINES)
    code = sorted((a, n) for n, a in lab.items()
                  if n in names and
                  any(s[0] <= a <= s[1] for k, s in seg.items()
                      if k.startswith('MATH')))
    out = {}
    for i, (a, n) in enumerate(code):
        end = next((s[1] + 1 for s in seg.values() if s[0] <= a <= s[1]))
        if i + 1 < len(code) and code[i + 1][0] <= end - 1:
            nxt = code[i + 1][0]
        else:
            nxt = end
        out[n] = nxt - a
    # aliases at one address: the same code
    by_addr = {}
    for a, n in code:
        by_addr.setdefault(a, []).append(n)
    for names in by_addr.values():
        size = max(out[n] for n in names)
        for n in names:
            out[n] = size
    return out


def size_with_callees(name: str, sizes: Dict[str, int]) -> int:
    seen = {name}
    total = sizes.get(name, 0)
    for callee in CALLEES.get(name, []):
        if callee not in seen:
            seen.add(callee)
            total += sizes.get(callee, 0)
    # an entry that falls into the next routine includes it
    nxt = FALLS_INTO.get(name)
    if nxt and nxt not in seen:
        total += sizes.get(nxt, 0)
    return total


def print_sizes() -> int:
    problem = check_build()
    if problem:
        print(problem, file=sys.stderr)
        return 1
    seg = segments()
    budgets = {'MATHLC': 0x400, 'MATHFAR': 0x400, 'MATHW': None,
               'MATHRND': 0x100}
    print('%-10s %-13s %6s %8s' % ('segment', 'range', 'bytes', 'budget'))
    for name in ('MATHLC', 'MATHFAR', 'MATHW', 'MATHRND'):
        lo, hi = seg[name]
        b = budgets[name]
        print('%-10s $%04X-$%04X %6d %8s' % (name, lo, hi, hi - lo + 1,
                                             b if b else '(W)'))
    sizes = routine_sizes()
    print()
    for n in sorted(sizes, key=lambda n: labels()[n]):
        print('%-14s $%04X %5d  with callees %5d' % (
            n, labels()[n], sizes[n], size_with_callees(n, sizes)))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--sizes', action='store_true')
    args = parser.parse_args(argv)
    if args.sizes:
        return print_sizes()
    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
