#!/usr/bin/env python3
"""Check the native math against upstream, and measure it.

Usage:  python3 tools/native/mathcheck.py [--full] [--random N]
            [--routines NAME,...] [--no-costs] [--jobs N] [--report FILE]

For each routine of tools/native/mathdefs.py:

1. The cases: every input of a small domain (the sines and cosines: all
   8,192 entries; the random indexes; the byte products; the reciprocal of
   every 16-bit value); else N random inputs (--random, 2,000 by default,
   1,000,000 with --full) and the edge inputs; and every distinct input of
   the calls logged in the coverage runs (build/native/math/captures, by
   tools/native/mathcap.py).
2. The truth: upstream's routine run on ref816 on every case
   (build/native/math/mathref batch, which runs it from its entry to its
   return as ref816's --call does, with the registers and the return
   address of a real call). The divides have no upstream oracle (the
   owner's decision 5: the port's own divides, never tested directly
   against the vendor's; upstream's angle routines call _UDivMod32 inside,
   so pta3, pta16 and pta16p meet it indirectly, src/native/MATH.md):
   their truth is C semantics (mathdefs.m_udiv, m_sdiv), and the
   byte product's is x * y. The host models are checked against the truth
   too, and the logged calls against the batch runs (the batch harness
   reproduces what the game's own calls returned).
3. The native routine on a2vm on every case (tools/native/mathrun.py,
   bulk runs): its results must equal the truth, all of them.
4. The costs (unless --no-costs), on up to 1,024 of the logged inputs (or
   random ones): 65C02 cycles a call on a2vm, its time on a2vm's f121 and
   fastpath profiles, upstream's 65816 cycles on ref816 (on the same
   inputs, and over every logged call), the native bytes; the writes the
   native routine makes (a2vm's write log: only the math block, the
   stack, mt_far's operands, the random indexes, $C002, $C003, $C073) and
   its lowest S.

Writes build/native/math/report.json (--report) and prints a summary.
Exit status 1 when a result differs, a native routine writes where it may
not, or a logged call disagrees with its batch run.

At most 2 processes at a time (--jobs), under nice.
"""

import argparse
import json
import random
import statistics
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import mathdefs, mathrun, mathtables  # noqa: E402
from native.mathdefs import Routine  # noqa: E402

MATH = mathdefs.MATH
MATHREF = MATH / 'mathref'
CAPTURES = MATH / 'captures'
REPORT = MATH / 'report.json'
SAMPLE_RANDOM = 2000
FULL_RANDOM = 1_000_000
TIMING_CASES = 1024
EXAMPLES = 5


def capture_dirs() -> List[Path]:
    if not CAPTURES.exists():
        return []
    return sorted(d for d in CAPTURES.iterdir()
                  if (d / 'base.ram').exists() and (d / 'spec.txt').exists())


def logged_calls(r: Routine) -> List[Tuple[str, mathdefs.Call]]:
    """Every logged call of r's upstream routine (and, for sdiv16, of
    _Mod16), with its script."""
    names = [(r.name, r.up_in, r.up_out)]
    for name, _, up_in, native in mathdefs.EXTRA_CAPTURES:
        if native == r.name:
            names.append((name, up_in, ()))
    out = []
    for d in capture_dirs():
        for name, up_in, up_out in names:
            path = d / (name + '.bin')
            if path.exists():
                inonly = name in mathdefs.VENDOR or name != r.name
                for c in mathdefs.read_log(path, up_in, up_out, inonly):
                    out.append((d.name, c))
    return out


def ops_of_call(r: Routine, call: mathdefs.Call):
    return tuple(r.ops_from_up(call.inputs))


def cases_for(r: Routine, n_random: int) -> Tuple[List[tuple], List[tuple],
                                                   List[tuple]]:
    """(domain or random plus edges, captured distinct, all distinct in
    order)."""
    if r.exhaustive:
        base = [tuple(o) for o in r.exhaustive()]
    else:
        # the edges, then n_random distinct random inputs besides them
        rng = random.Random('mathcheck:' + r.name)
        base = list(dict.fromkeys(tuple(o) for o in r.edges()))
        known = set(base)
        randoms = 0
        while randoms < n_random:
            o = tuple(r.gen(rng))
            if o not in known:
                known.add(o)
                base.append(o)
                randoms += 1
    captured = []
    seen = set()
    if r.ops_from_up:
        for _, call in logged_calls(r):
            if call.flags & 4:
                continue
            o = ops_of_call(r, call)
            if o not in seen:
                seen.add(o)
                captured.append(o)
    allc = []
    seen = set()
    for o in base + captured:
        if o not in seen:
            seen.add(o)
            allc.append(o)
    return base, captured, allc


def ref_batch(r: Routine, ops: Sequence[tuple], directory: Path,
              capture: Path) -> Tuple[List[bytes], List[int]]:
    """Upstream's r on ref816 for each operand tuple: (output bytes,
    cycles)."""
    n_out = mathdefs.item_bytes(r.up_out)
    cases = directory / ('%s.cases' % r.name)
    out = directory / ('%s.out' % r.name)
    cases.write_bytes(b''.join(r.up_bytes(o) for o in ops))
    command = ['nice', '-n', '10', str(MATHREF), 'batch',
               str(capture / 'base.ram'), str(capture / (r.name + '.entry')),
               str(capture / 'spec.txt'), r.name, str(cases), str(out)]
    result = subprocess.run(command, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True)
    if result.returncode:
        raise RuntimeError('mathref batch %s: %s' % (r.name, result.stderr))
    data = out.read_bytes()
    size = n_out + 4
    outs, cycles = [], []
    for at in range(0, len(data), size):
        outs.append(data[at:at + n_out])
        cycles.append(mathdefs.le(data, at + n_out, 4))
    cases.unlink()
    out.unlink()
    return outs, cycles


def read_entry(path: Path) -> Dict:
    """A NAME.entry of mathref capture."""
    out = {}
    for line in path.read_text().splitlines():
        key, _, rest = line.partition(' ')
        values = rest.split()
        if key in ('stack', 'switches'):
            out[key] = [int(v, 16) for v in values]
        elif key == 'ret':
            out[key] = int(values[0])
        else:
            out[key] = int(values[0], 16)
    return out


REF816 = mathdefs.BUILD / 'ref816' / 'ref816'


def ref_call(r: Routine, ops: Sequence[tuple], capture: Path,
             workdir: Path) -> List[Tuple[bytes, int]]:
    """Upstream's r run by ref816's own --call, one process a case: the
    image is the capture's RAM with the return address of the logged
    call on the stack and the inputs in place. Returns (output bytes,
    cycles) per case, to check that mathref batch does what --call does."""
    from ref816 import make_image
    entry = read_entry(capture / (r.name + '.entry'))
    base = bytearray((capture / 'base.ram').read_bytes())
    out = []
    for k, o in enumerate(ops):
        ram = bytearray(base)
        s = entry['s']
        for i, v in enumerate(entry['stack']):
            ram[(s + 1 + i) & 0xFFFF] = v
        regs = {'a': entry['a'], 'x': entry['x'], 'y': entry['y']}
        data = r.up_bytes(o)
        at = 0
        sym = mathdefs.symbols()
        for it in r.up_in:
            if isinstance(it, str):
                regs[it] = mathdefs.le(data, at, 2)
                at += 2
            else:
                address = sym.address(it[0])
                ram[address:address + it[1]] = data[at:at + it[1]]
                at += it[1]
        registers = make_image.Registers(
            pc=entry['pc'] & 0xFFFF, pbr=entry['pc'] >> 16,
            dbr=entry['dbr'], a=regs['a'], x=regs['x'], y=regs['y'],
            s=s, d=entry['d'], p=entry['p'], e=entry['e'])
        records = [(0, bytes(ram[:0x800000])),
                   (0xE00000, bytes(ram[0x800000:]))]
        image = workdir / ('call%d.img' % k)
        image.write_bytes(make_image.image_bytes(
            registers, records, tuple(entry['switches'])))
        state = workdir / ('call%d.json' % k)
        command = [str(REF816), str(image), '--call', '%06X' % entry['pc'],
                   '--cycles', '100000000', '--state', str(state)]
        saves = []
        for i, it in enumerate(r.up_out):
            if not isinstance(it, str):
                path = workdir / ('save%d-%d.bin' % (k, i))
                command += ['--save', '%06X:%d:%s' % (
                    sym.address(it[0]), it[1], path)]
                saves.append(path)
        result = subprocess.run(['nice', '-n', '10'] + command,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                universal_newlines=True)
        if result.returncode:
            raise RuntimeError('ref816 --call: %s' % result.stderr)
        call = json.loads(state.read_text())['call']
        if not call['returned'] or call['interrupts']['count']:
            raise RuntimeError('ref816 --call of %s did not return cleanly'
                               % r.name)
        end = call['end']
        b = b''
        si = 0
        for it in r.up_out:
            if isinstance(it, str):
                b += (end[it] & 0xFFFF).to_bytes(2, 'little')
            else:
                b += saves[si].read_bytes()
                si += 1
        out.append((b, call['cycles']))
        for path in [image, state] + saves:
            path.unlink()
    return out


def entry_capture(r: Routine) -> Optional[Path]:
    for d in capture_dirs():
        if (d / (r.name + '.entry')).exists():
            return d
    return None


def stats(values: Sequence[float]) -> Optional[Dict]:
    if not values:
        return None
    return {'n': len(values), 'mean': round(statistics.mean(values), 2),
            'min': min(values), 'max': max(values)}


def timing_set(captured: List[tuple], base: List[tuple]) -> List[tuple]:
    source = captured if captured else base
    if len(source) <= TIMING_CASES:
        return list(source)
    step = len(source) / TIMING_CASES
    return [source[int(i * step)] for i in range(TIMING_CASES)]


def stray_writes(r: Routine, log: str) -> List[str]:
    """Writes by the math's code outside what it may write."""
    lab = mathrun.labels()
    seg = mathrun.segments()
    code = [seg[s] for s in ('MATHLC', 'MATHFAR', 'MATHW', 'MATHRND')
            if s in seg]
    mz = lab['MZ']
    allowed_main = [(mz, mz + 39), (0x0100, 0x01FF),
                    (lab['MT_PRND'], lab['MT_PRND']),
                    (lab['MT_MRND'], lab['MT_MRND'])]
    allowed_lc1 = [(lab['mt_far_count'] + 1, lab['mt_far_count'] + 1),
                   (lab['mt_far_stride'] + 1, lab['mt_far_stride'] + 1)]
    allowed_io = {0xC002, 0xC003, 0xC073}
    bad = []
    for line in log.splitlines():
        if not line.startswith('w '):
            continue
        parts = line.split()
        pc = int(parts[3], 16)
        if not any(lo <= pc <= hi for lo, hi in code):
            continue
        address, storage = int(parts[4], 16), parts[5]
        ok = False
        if storage == 'main':
            ok = any(lo <= address <= hi for lo, hi in allowed_main)
        elif storage == 'lc1':
            ok = any(lo <= address <= hi for lo, hi in allowed_lc1)
        elif storage == 'io':
            ok = address in allowed_io
        if not ok and len(bad) < EXAMPLES:
            bad.append(line)
        elif not ok:
            bad.append('')
    return bad


def costs(r: Routine, ops: List[tuple]) -> Dict:
    cases = [r.nat_bytes(o) for o in ops]
    out = {'cases': len(cases)}
    plain = mathrun.run(r, cases, mode='main', write_log=True,
                        lowest_s=True)
    stub = mathrun.run(r, cases, mode='main', stub=True)
    diff = plain.state['cycles'] - stub.state['cycles']
    out['cycles'] = round(diff / len(cases) + mathrun.RTS_CYCLES, 2)
    stray = stray_writes(r, plain.write_log or '')
    out['stray_writes'] = len(stray)
    out['stray_examples'] = [s for s in stray if s][:EXAMPLES]
    low = plain.state.get('lowest_s', {})
    ranges = [x for x in low.get('ranges', []) if x.get('steps')]
    if ranges:
        # the driver's S before a call is $FF: bytes below it, the
        # return address of the call included
        out['stack_bytes'] = 0xFF - min(x['s'] for x in ranges)
    for profile in ('f121', 'fastpath'):
        timed = mathrun.run(r, cases, mode='main', profile=profile)
        base = mathrun.run(r, cases, mode='main', profile=profile,
                           stub=True)
        mhz = timed.cost['fabric_mhz']
        clocks = timed.cost['phases'][1] - base.cost['phases'][1]
        out[profile + '_us'] = round(clocks / len(cases) / mhz, 3)
    return out


def check_routine(r: Routine, n_random: int, want_costs: bool,
                  tables: mathdefs.Tables, workdir: Path,
                  call_cases: int = 0) -> Dict:
    base, captured, allc = cases_for(r, n_random)
    rep = {'routine': r.name, 'native': r.native, 'upstream': r.upstream,
           'doc': r.doc, 'cases': len(allc), 'domain_or_random': len(base),
           'exhaustive': bool(r.exhaustive),
           'random_inputs': 0 if r.exhaustive else n_random,
           'captured_distinct': len(captured)}
    oracle_upstream = bool(r.upstream) and r.name not in mathdefs.VENDOR
    logged = logged_calls(r) if r.ops_from_up else []
    rep['logged_calls'] = len(logged)
    rep['logged_by_script'] = {}
    for script, _ in logged:
        rep['logged_by_script'][script] = \
            rep['logged_by_script'].get(script, 0) + 1

    # the truth
    up_cycles = {}
    if oracle_upstream:
        capture = entry_capture(r)
        if capture is None:
            raise RuntimeError('%s: no logged call to run it from '
                               '(run tools/native/mathcap.py)' % r.name)
        outs, cyc = ref_batch(r, allc, workdir, capture)
        truth = [tuple(mathdefs.upstream_result(r, b)) for b in outs]
        up_cycles = dict(zip(allc, cyc))
        cyc_of = up_cycles
        rep['oracle'] = 'upstream on ref816 (mathref batch)'
        model_bad = [(o, t) for o, t in zip(allc, truth)
                     if tuple(r.model(o, tables)) != t]
        rep['model_mismatches'] = len(model_bad)
        # the logged calls against their batch runs
        truth_of = dict(zip(allc, truth))
        disagree = 0
        for _, call in logged:
            if call.flags & 5:
                continue
            o = ops_of_call(r, call)
            if tuple(mathdefs.upstream_result(r, call.outputs)) != \
                    truth_of[o]:
                disagree += 1
        rep['logged_vs_batch_mismatches'] = disagree
        # a few cases through ref816's own --call: the same results and
        # cycles as the batch
        if call_cases:
            pick = allc[:: max(1, len(allc) // call_cases)][:call_cases]
            got = ref_call(r, pick, capture, workdir)
            index = {o: i for i, o in enumerate(allc)}
            same = sum(1 for o, (b, cyc) in zip(pick, got)
                       if b == outs[index[o]] and cyc == cyc_of[o])
            rep['call_checked'] = len(pick)
            rep['call_mismatches'] = len(pick) - same
    else:
        truth = [tuple(r.model(o, tables)) for o in allc]
        rep['oracle'] = ('C semantics (the port\'s own divide)'
                         if r.name in mathdefs.VENDOR else 'x * y')
        if r.name in mathdefs.VENDOR:
            zero = sum(1 for _, c in logged
                       if r.ops_from_up(c.inputs)[1] == 0)
            rep['logged_divisions_by_zero'] = zero

    # the native routine
    results = mathrun.run_all(r, [r.nat_bytes(o) for o in allc])
    bad = []
    for o, b, t in zip(allc, results, truth):
        got = tuple(r.res_from_nat(b))
        if got != t:
            bad.append({'operands': ['0x%X' % v for v in o],
                        'native': ['0x%X' % v for v in got],
                        'truth': ['0x%X' % v for v in t]})
    rep['mismatches'] = len(bad)
    rep['mismatch_examples'] = bad[:EXAMPLES]

    # the costs
    if want_costs:
        timing = timing_set(captured, base)
        rep['costs'] = costs(r, timing)
        rep['costs']['timing_inputs'] = 'captured' if captured else 'random'
        if up_cycles:
            rep['costs']['upstream_cycles_same_inputs'] = stats(
                [up_cycles[o] for o in timing])
        real = [c.cycles for _, c in logged if not c.flags & 5]
        if real and oracle_upstream:
            rep['costs']['upstream_cycles_logged'] = stats(real)
    return rep


def summary(reports: List[Dict]) -> str:
    sizes = mathrun.routine_sizes()
    lines = ['%-12s %9s %9s %6s %7s %6s %9s %8s %8s %8s %6s' % (
        'routine', 'cases', 'captured', 'bad', 'bytes', '+calls',
        'cycles', 'f121 us', 'fast us', 'up cyc', 'ratio')]
    for rep in reports:
        c = rep.get('costs', {})
        up = c.get('upstream_cycles_same_inputs') or {}
        cyc = c.get('cycles')
        ratio = (cyc / up['mean']) if cyc and up.get('mean') else None
        lines.append('%-12s %9d %9d %6d %7d %6d %9s %8s %8s %8s %6s' % (
            rep['routine'], rep['cases'], rep['captured_distinct'],
            rep['mismatches'], sizes.get(rep['native'], 0),
            mathrun.size_with_callees(rep['native'], sizes),
            cyc if cyc is not None else '-',
            c.get('f121_us', '-'), c.get('fastpath_us', '-'),
            up.get('mean', '-'), '%.2f' % ratio if ratio else '-'))
    return '\n'.join(lines)


def markdown(doc: Dict) -> str:
    """The report as MATH.md's tables (the numbers as printed)."""
    sizes = doc['sizes']
    reports = doc['routines']
    out = ['| Routine | Upstream | Oracle | Cases | Of them logged | '
           'Differ |',
           '| --- | --- | --- | ---: | ---: | ---: |']
    for rep in reports:
        up = rep['upstream'] or '(none)'
        oracle = {'upstream on ref816 (mathref batch)': 'ref816',
                  'x * y': 'x * y'}.get(rep['oracle'], 'C semantics')
        out.append('| `%s` | `%s` | %s | %s | %s | %d |' % (
            rep['routine'], up.split(':')[-1], oracle,
            '{:,}'.format(rep['cases']),
            '{:,}'.format(rep['captured_distinct']), rep['mismatches']))
    out += ['', '| Routine | Native | Bytes | With callees | 65C02 cycles | '
            'f121 us | fastpath us | Upstream cycles | Ratio | Stack |',
            '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: '
            '| ---: |']
    for rep in reports:
        c = rep.get('costs', {})
        up = c.get('upstream_cycles_same_inputs') or {}
        cyc = c.get('cycles')
        ratio = '%.2f' % (cyc / up['mean']) if cyc and up.get('mean') \
            else '-'
        out.append('| `%s` | `%s` | %d | %d | %s | %s | %s | %s | %s | %s |'
                   % (rep['routine'], rep['native'],
                      sizes.get(rep['native'], 0),
                      mathrun.size_with_callees(rep['native'], sizes),
                      cyc if cyc is not None else '-',
                      c.get('f121_us', '-'), c.get('fastpath_us', '-'),
                      ('%s (%d-%d)' % (up['mean'], up['min'], up['max']))
                      if up else '-', ratio, c.get('stack_bytes', '-')))
    return '\n'.join(out) + '\n'


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--full', action='store_true',
                        help='1,000,000 random inputs a routine')
    parser.add_argument('--random', type=int)
    parser.add_argument('--routines')
    parser.add_argument('--no-costs', action='store_true')
    parser.add_argument('--call-cases', type=int, default=4,
                        help='cases a routine also run by ref816 --call')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--report', type=Path, default=REPORT)
    parser.add_argument('--markdown', type=Path,
                        help='print the tables of an existing report')
    args = parser.parse_args(argv)
    if args.markdown:
        print(markdown(json.loads(args.markdown.read_text())))
        return 0
    problem = mathrun.check_build()
    if problem:
        print(problem, file=sys.stderr)
        return 1
    if not MATHREF.exists() or not capture_dirs():
        print('no captures: run python3 tools/native/mathcap.py',
              file=sys.stderr)
        return 1
    n_random = args.random if args.random is not None else (
        FULL_RANDOM if args.full else SAMPLE_RANDOM)
    routines = mathdefs.ROUTINES
    if args.routines:
        wanted = args.routines.split(',')
        routines = [mathdefs.BY_NAME[n] for n in wanted]
    tables = mathtables.load(capture_dirs()[0] / 'base.ram')
    with tempfile.TemporaryDirectory(prefix='mathcheck-',
                                     dir=str(MATH)) as tmp:
        work = Path(tmp)

        def one(r):
            d = work / r.name
            d.mkdir()
            return check_routine(r, n_random, not args.no_costs, tables, d,
                                 args.call_cases)
        with ThreadPoolExecutor(max_workers=max(1, min(args.jobs, 2))) as p:
            reports = list(p.map(one, routines))
    failed = [rep['routine'] for rep in reports
              if rep['mismatches'] or rep.get('logged_vs_batch_mismatches')
              or rep.get('model_mismatches') or rep.get('call_mismatches')
              or rep.get('costs', {}).get('stray_writes')]
    doc = {'random_inputs': n_random, 'captures':
           [d.name for d in capture_dirs()], 'routines': reports,
           'sizes': mathrun.routine_sizes(),
           'segments': {k: [v[0], v[1]] for k, v in
                        mathrun.segments().items()},
           'failed': failed}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(doc, indent=1) + '\n')
    args.report.with_suffix('.md').write_text(markdown(doc))
    print(summary(reports))
    print('report: %s' % args.report)
    if failed:
        print('FAILED: %s' % ', '.join(failed))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
