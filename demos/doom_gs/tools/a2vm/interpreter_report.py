#!/usr/bin/env python3
"""The cost of the 65816 interpreter of src/vm, and its first contact
with the game: docs/INTERPRETER.md.

Usage:  python3 tools/a2vm/interpreter_report.py [--run] [--data DIR]
                                                 [--output FILE]

Milestone 3.2 of docs/MILESTONES.md, items 2 and 3. The measurements are
files in DIR (default build/a2vm/interp), made when missing and again
with --run:

  costs-PROFILE.txt         the parameters of each cost profile of
                            tools/a2vm/costs/appletini.json (costs.py)
  vectors-PROFILE.cost      every SingleStepTests 65816 case run by the
                            interpreter on a2vm and measured
                            (tools/a2vm/vm816.c, --cost)
  pages-PROFILE.json        what a change of code page costs, when the
                            code cache has the page and when it has not
                            (game816.c, pages)
  contact-PROFILE.json      the first contact: the release image run from
                            its entry point in lockstep with ref816 up to
                            its first I/O access (tools/a2vm/game816.c,
                            contact)
  SCENARIO.trace            ref816's trace of each scenario of
  SCENARIO.samples          tools/ref816/profile816.py, with the opcode and
                            width of every instruction and one instruction
                            in 499 written whole (tools/ref816/trace.h)
  samples-SCENARIO-PROFILE.json
                            those instructions run again, one by one, by
                            the interpreter with the game's map, measured
                            and checked (game816.c, samples)

The report is a function of these files alone, so the same files give
the same report, byte for byte; a run of --run gives the same files, as
every machine involved is deterministic. It goes to docs/INTERPRETER.md
(or FILE) and to the standard output. Standard library only.
"""

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from a2vm import costs  # noqa: E402
from ref816 import (codemap, make_image, marks, profile816,  # noqa: E402
                    run_script, script, title, tracefile)
from ref816.profile816 import number, percent, table  # noqa: E402
from v816 import opcodes  # noqa: E402

ROOT = make_image.ROOT
BUILD = ROOT / 'build'
DATA = BUILD / 'a2vm' / 'interp'
OUTPUT = ROOT / 'docs' / 'INTERPRETER.md'
TEMPLATE = HERE / 'interpreter_template.md'
VM = BUILD / 'vm'
VM816 = BUILD / 'a2vm' / 'vm816'
GAME816 = BUILD / 'a2vm' / 'game816'
VECTORS = BUILD / 'vectors' / 'bin'

PROFILES = ('f121', 'fastpath')
SCENARIOS = profile816.SCENARIOS
SAMPLE_EVERY = 499
REPLAY = 'replay'           # the phase the port hand-writes
# ARCHITECTURE.md section 6, assumption P5, and the frame it implies.
P5_US, P5_LOW, P5_HIGH = 3.2, 3.0, 3.9
TIER0_FRAME_S = 1.9         # "Tier 0, all interpreted: about 1.9 s"
P1_HZ = 45e6                # "CPU rate in BRAM: 45 M cycles/s"
WIDTHS = {0: 'M16 X16', 1: 'M16 X8', 2: 'M8 X16', 3: 'M8 X8'}
TOP_OPCODES = 20


# ---- the names of the opcodes ----

def _names() -> Dict[int, str]:
    """Each opcode as `MNEMONIC mode` (tools/v816/opcodes.py): `JML` for
    the two opcodes JMP shares, no mode for the implied ones, `A` for the
    accumulator and `#` for an immediate."""
    names: Dict[int, str] = {}
    for mnemonic, modes in sorted(opcodes.OPCODES.items()):
        for mode, opcode in modes.items():
            if opcode in names and mnemonic != 'jml':
                continue
            if mode in ('imp', 'move'):
                names[opcode] = mnemonic.upper()
            else:
                names[opcode] = '%s %s' % (mnemonic.upper(), {
                    'acc': 'A', 'imm': '#'}.get(mode, mode))
    return names


NAMES = _names()


def instruction(opcode: int) -> str:
    return '`%s`' % NAMES[opcode]


# ---- the measurements ----

class Stats(NamedTuple):
    count: int
    cycles: Tuple[int, int, int, int]       # min, median, max, sum
    clocks: Tuple[int, int, int, int]
    # Vectors only: the cases whose fetch entered a new code page (and
    # copied it, cold, into the cache while measured), and the statistics
    # of the other cases (None when there are none).
    apart: int = 0
    rest: Optional['Stats'] = None


class VectorCost(NamedTuple):
    fabric_mhz: float
    cases: int
    failures: int
    known: int
    unmeasured: int
    apart: int                                       # cases set apart
    buckets: Dict[Tuple[int, int, int, int], Stats]  # opcode, e, m, x
    modes: Dict[Tuple[int, int], Stats]              # opcode, e


def vector_stats(words: Sequence[str]) -> Stats:
    """COUNT, 4 cycles, 4 clocks, 'apart', APART, REST_COUNT, then 4
    cycles and 4 clocks when REST_COUNT is not 0."""
    values = [int(w) for w in words[:9]]
    if len(words) < 12 or words[9] != 'apart':
        raise ValueError('bad statistics %r' % ' '.join(words))
    apart, rest_count = int(words[10]), int(words[11])
    rest = None
    if rest_count:
        more = [int(w) for w in words[12:20]]
        rest = Stats(rest_count, tuple(more[0:4]), tuple(more[4:8]))
    return Stats(values[0], tuple(values[1:5]), tuple(values[5:9]),
                 apart, rest)


def read_vector_cost(path: Path) -> VectorCost:
    lines = path.read_text().splitlines()
    if not lines or lines[0] != 'vm816-cost 2':
        raise ValueError('%s is not a vm816 cost file (version 2)' % path)
    fabric = 0.0
    totals: Dict[str, int] = {}
    buckets = {}
    modes = {}
    for line in lines[1:]:
        words = line.split()
        if words[0] == 'fabric_mhz':
            fabric = float(words[1])
        elif words[0] == 'cases':
            totals = {words[i]: int(words[i + 1])
                      for i in range(0, len(words), 2)}
        elif words[0] == 'bucket':
            key = (int(words[1], 16), int(words[2]), int(words[3]),
                   int(words[4]))
            buckets[key] = vector_stats(words[5:])
        elif words[0] == 'mode':
            key = (int(words[1], 16), int(words[2]))
            modes[key] = vector_stats(words[3:])
        else:
            raise ValueError('%s: unknown line %r' % (path, line))
    return VectorCost(fabric, totals['cases'], totals['failures'],
                      totals['known'], totals['unmeasured'],
                      totals['apart'], buckets, modes)


def json_buckets(data: Dict) -> Dict[Tuple[int, int, int, int], Stats]:
    return {(b[0], b[1], b[2], b[3]): Stats(b[4], tuple(b[5]), tuple(b[6]))
            for b in data['buckets']}


class Measurements(NamedTuple):
    vectors: Dict[str, VectorCost]                  # by profile
    contact: Dict[str, Dict]                        # by profile
    pages: Dict[str, Dict]                          # by profile
    traces: Dict[str, tracefile.Trace]              # by scenario
    samples: Dict[Tuple[str, str], Dict]            # (scenario, profile)


def paths(data: Path) -> Dict[str, Path]:
    out = {}
    for profile in PROFILES:
        out['costs-' + profile] = data / ('costs-%s.txt' % profile)
        out['vectors-' + profile] = data / ('vectors-%s.cost' % profile)
        out['contact-' + profile] = data / ('contact-%s.json' % profile)
        out['pages-' + profile] = data / ('pages-%s.json' % profile)
        for scenario in SCENARIOS:
            out['samples-%s-%s' % (scenario.key, profile)] = \
                data / ('samples-%s-%s.json' % (scenario.key, profile))
    for scenario in SCENARIOS:
        out['trace-' + scenario.key] = data / (scenario.key + '.trace')
        out['samples-' + scenario.key] = data / (scenario.key + '.samples')
    return out


def load(data: Path) -> Measurements:
    p = paths(data)
    return Measurements(
        {pr: read_vector_cost(p['vectors-' + pr]) for pr in PROFILES},
        {pr: json.loads(p['contact-' + pr].read_text()) for pr in PROFILES},
        {pr: json.loads(p['pages-' + pr].read_text()) for pr in PROFILES},
        {s.key: tracefile.read(p['trace-' + s.key]) for s in SCENARIOS},
        {(s.key, pr): json.loads(p['samples-%s-%s' % (s.key, pr)]
                                 .read_text())
         for s in SCENARIOS for pr in PROFILES})


# ---- making the measurements ----

def check_call(command: Sequence[str], out: Optional[Path] = None,
               allowed: Sequence[int] = (0,)) -> None:
    print('running %s' % ' '.join(str(c) for c in command), file=sys.stderr)
    result = subprocess.run([str(c) for c in command],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True)
    if result.returncode not in allowed:
        raise RuntimeError('%s failed (%d):\n%s%s' % (
            command[0], result.returncode, result.stdout[-3000:],
            result.stderr[-3000:]))
    if out is not None:
        out.write_text(result.stdout)


def build_tools() -> None:
    check_call(['make', '-C', ROOT / 'src' / 'vm', 'OUT=%s' % VM])
    check_call(['make', '-C', HERE, 'all'])
    title.build_machine()
    title.ensure_image()


def trace_scenario(scenario, symbols: script.Symbols, data: Path) -> None:
    """The scenario on ref816, traced with samples."""
    path = run_script.script_path(scenario.script)
    program = script.compile_script(path.read_text(), symbols, path.name)
    run_dir = data / ('run-' + scenario.key)
    run = run_script.Run(run_dir, run_dir / 'shots')
    options = profile816.trace_options(
        symbols, scenario, data / (scenario.key + '.trace'))
    options += ['--trace-samples', str(data / (scenario.key + '.samples')),
                '--trace-sample-every', str(SAMPLE_EVERY)]
    print('tracing %s ...' % scenario.script, file=sys.stderr)
    state = run.execute(program, symbols, None,
                        run_script.DEFAULT_LIMIT_SECONDS, options)
    found = run_script.problems(state, marks.read(run.marks_path), symbols,
                                program)
    if found:
        raise RuntimeError('the traced run of %s: %s'
                           % (scenario.script, '; '.join(found)))


def measure(data: Path, again: bool) -> None:
    """Make the measurement files that are missing (all with `again`)."""
    p = paths(data)
    missing = [key for key, path in p.items() if again or not path.exists()]
    if not missing:
        return
    for path in (make_image.RELEASE_IMAGE, make_image.LINKMAP):
        if not path.exists():
            raise RuntimeError('%s is missing: run python3 '
                               'tools/fetch_upstream.py and python3 '
                               'tools/v816/imgmatch.py first' % path)
    vectors = sorted(VECTORS.glob('*.bin'))
    if len(vectors) != 512:
        raise RuntimeError('the 65816 vectors are missing: run python3 '
                           'tools/ref816/fetch_vectors.py first')
    data.mkdir(parents=True, exist_ok=True)
    build_tools()
    for profile in PROFILES:
        costs.write(profile, p['costs-' + profile])
    with open(str(make_image.LINKMAP)) as handle:
        symbols = script.Symbols(json.load(handle))
    for scenario in SCENARIOS:
        if 'trace-' + scenario.key in missing or \
                'samples-' + scenario.key in missing:
            trace_scenario(scenario, symbols, data)
    # The two vector runs take minutes each: side by side.
    running = []
    for profile in PROFILES:
        if 'vectors-' + profile in missing:
            command = [VM816, '--vm', VM, '--cost', p['costs-' + profile],
                       p['vectors-' + profile]] + vectors
            print('running vm816 --cost %s on %d files ...'
                  % (profile, len(vectors)), file=sys.stderr)
            running.append((profile, subprocess.Popen(
                [str(c) for c in command], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, universal_newlines=True)))
    for profile in PROFILES:
        check_call([GAME816, '--vm', VM, '--cost', p['costs-' + profile],
                    'pages'], p['pages-' + profile])
        check_call([GAME816, '--vm', VM, '--cost', p['costs-' + profile],
                    'contact', make_image.OUT_DIR / 'memory.img'],
                   p['contact-' + profile], allowed=(0, 1))
        for scenario in SCENARIOS:
            check_call([GAME816, '--vm', VM, '--cost', p['costs-' + profile],
                        'samples', p['samples-' + scenario.key]],
                       p['samples-%s-%s' % (scenario.key, profile)],
                       allowed=(0, 1))
    for profile, process in running:
        output, _ = process.communicate()
        if process.returncode:
            raise RuntimeError('vm816 --cost %s failed:\n%s'
                               % (profile, output[-3000:]))


# ---- the numbers ----

def us(clocks: float, fabric_mhz: float) -> float:
    return clocks / fabric_mhz


def fmt_us(value: float) -> str:
    return '%.2f' % value


def fmt_cycles(value: float) -> str:
    return number(value)


def mix(trace: tracefile.Trace, skip_phase: Optional[str] = None
        ) -> Counter:
    """(opcode, e, m, x): instructions over the recorded frames."""
    skip = trace.phase(skip_phase) if skip_phase else -1
    out: Counter = Counter()
    for frame in trace.frames:
        for (phase, opcode, mx), count in frame.ops.items():
            if phase != skip:
                out[(opcode, mx >> 2 & 1, mx >> 1 & 1, mx & 1)] += count
    return out


def weighted(weights: Counter, buckets: Dict, field: str,
             which: int) -> float:
    """The mean over the mix of statistic `which` (0 minimum, 1 median)
    of the buckets' `field` (cycles or clocks)."""
    total = sum(weights.values())
    missing = [key for key in weights if key not in buckets]
    if missing:
        raise ValueError('no vector cases for %s' % missing[:5])
    return sum(count * getattr(buckets[key], field)[which]
               for key, count in weights.items()) / total


class Mean(NamedTuple):
    count: int
    cycles: float           # 65C02 cycles an instruction
    us: float               # microseconds an instruction


def sample_mean(m: 'Measurements', scenario: str, profile: str,
                skip_phase: Optional[str] = None) -> Mean:
    """The mean cost of the measured samples (all phases, or without
    `skip_phase`)."""
    data = m.samples[(scenario, profile)]
    phases = m.traces[scenario].phases
    count = cycles = clocks = 0
    for phase, (n, c, k) in data['phases'].items():
        if skip_phase and phases[int(phase)] == skip_phase:
            continue
        count += n
        cycles += c
        clocks += k
    return Mean(count, cycles / count, us(clocks / count, data['fabric_mhz']))


class PageCost(NamedTuple):
    hit_cycles: float       # a change of page the cache has, more than none
    hit_us: float
    miss_cycles: float      # one it has not
    miss_us: float
    same_cycles: float      # JMP within a page
    same_us: float


def page_cost(m: 'Measurements', profile: str) -> PageCost:
    data = m.pages[profile]
    fabric = data['fabric_mhz']

    def per(key: str) -> Tuple[float, float]:
        d = data[key]
        return (d['cycles'] / d['instructions'],
                us(d['clocks'] / d['instructions'], fabric))

    same, hit, miss = per('same_page'), per('hit'), per('miss')
    return PageCost(hit[0] - same[0], hit[1] - same[1], miss[0] - same[0],
                    miss[1] - same[1], same[0], same[1])


class CodeRate(NamedTuple):
    changes: float          # changes of code page an instruction
    misses: float           # of those, misses of the 16 slots


def code_rate(trace: tracefile.Trace,
              skip_phase: Optional[str] = None) -> CodeRate:
    skip = trace.phase(skip_phase) if skip_phase else -1
    changes = misses = instructions = 0
    for frame in trace.frames:
        for phase, (c, k) in frame.code.items():
            if phase != skip:
                changes += c
                misses += k
        for phase, (n, _) in frame.cost.items():
            if phase != skip:
                instructions += n
    return CodeRate(changes / instructions, misses / instructions)


def cache_cost(m: 'Measurements', scenario: str, profile: str,
               skip_phase: Optional[str] = None) -> Tuple[float, float]:
    """Cycles and microseconds an instruction for the code page cache:
    each change of page costs a hit, each miss the difference too."""
    rate = code_rate(m.traces[scenario], skip_phase)
    cost = page_cost(m, profile)
    cycles = rate.changes * cost.hit_cycles + rate.misses * (
        cost.miss_cycles - cost.hit_cycles)
    micro = rate.changes * cost.hit_us + rate.misses * (
        cost.miss_us - cost.hit_us)
    return cycles, micro


def total_cost(m: 'Measurements', scenario: str, profile: str,
               skip_phase: Optional[str] = None) -> Tuple[float, float]:
    """The interpreter with its code page cache: the game's own
    instructions plus the cache's share."""
    mean = sample_mean(m, scenario, profile, skip_phase)
    cycles, micro = cache_cost(m, scenario, profile, skip_phase)
    return mean.cycles + cycles, mean.us + micro


def frame_instructions(trace: tracefile.Trace) -> float:
    from statistics import median
    return median(f.instructions for f in trace.frames)


# ---- the tables ----

LABELS = (('all instructions', None),
          ('without the record replay', REPLAY))


def headline_table(m: 'Measurements', values: Dict[str, str]) -> str:
    rows = []
    for scenario in SCENARIOS:
        for label, skip in LABELS:
            row = [scenario.key, label]
            cycles = total_cost(m, scenario.key, 'f121', skip)[0]
            row.append(fmt_cycles(cycles))
            for pr in PROFILES:
                micro = total_cost(m, scenario.key, pr, skip)[1]
                row.append(fmt_us(micro))
                row.append('%.2f' % (micro / P5_US))
                if skip is None:
                    values['total_%s_%s' % (scenario.key, pr)] = \
                        fmt_us(micro)
                    values['ratio_%s_%s' % (scenario.key, pr)] = \
                        '%.1f' % (micro / P5_US)
            if skip is None:
                values['total_cycles_%s' % scenario.key] = \
                    fmt_cycles(cycles)
                values['p1_us_%s' % scenario.key] = fmt_us(
                    cycles / P1_HZ * 1e6)
            rows.append(row)
    every = sorted((values['ratio_%s_%s' % (sc.key, pr)] for sc in SCENARIOS
                    for pr in PROFILES), key=float)
    values['ratio_min'], values['ratio_max'] = every[0], every[-1]
    for pr in PROFILES:
        ratios = sorted({values['ratio_%s_%s' % (sc.key, pr)]
                         for sc in SCENARIOS}, key=float)
        values['ratios_' + pr] = ' to '.join([ratios[0], ratios[-1]]) \
            if len(ratios) > 1 else ratios[0]
    return table(['Scene', 'Instructions', '65C02 cycles', 'µs, f121',
                  'f121 / P5', 'µs, fastpath', 'fastpath / P5'], rows, 2)


def methods_table(m: 'Measurements', values: Dict[str, str]) -> str:
    rows = []
    fabric = {pr: m.vectors[pr].fabric_mhz for pr in PROFILES}
    for scenario in SCENARIOS:
        trace = m.traces[scenario.key]
        for label, skip in LABELS:
            weights = mix(trace, skip)
            for name, which in (('vector medians', 1),
                                ('vector minimums', 0)):
                row = ['%s, %s' % (scenario.key, label), name,
                       fmt_cycles(weighted(weights,
                                           m.vectors['f121'].buckets,
                                           'cycles', which))]
                for pr in PROFILES:
                    row.append(fmt_us(us(weighted(
                        weights, m.vectors[pr].buckets, 'clocks', which),
                        fabric[pr])))
                rows.append(row)
                if skip is None and which == 1:
                    values['vector_%s_f121' % scenario.key] = row[3]
                    values['vector_%s_cycles' % scenario.key] = row[2]
            means = [sample_mean(m, scenario.key, pr, skip)
                     for pr in PROFILES]
            rows.append(['%s, %s' % (scenario.key, label),
                         "the game's own instructions",
                         fmt_cycles(means[0].cycles)] +
                        [fmt_us(x.us) for x in means])
            if skip is None:
                values['sample_%s_cycles' % scenario.key] = \
                    fmt_cycles(means[0].cycles)
                for pr, x in zip(PROFILES, means):
                    values['sample_%s_%s' % (scenario.key, pr)] = \
                        fmt_us(x.us)
    return table(['Code', 'Cost of each (opcode, widths) taken from',
                  '65C02 cycles', 'µs, f121', 'µs, fastpath'], rows, 2)


def p5_table(m: 'Measurements') -> str:
    rows = []
    for scenario in SCENARIOS:
        cycles = total_cost(m, scenario.key, 'f121')[0]
        rows.append([scenario.key, fmt_cycles(cycles),
                     '%.0f' % (P5_US * P1_HZ / 1e6),
                     '%.1f' % (cycles / (P5_US * P1_HZ / 1e6)),
                     fmt_us(cycles / P1_HZ * 1e6)])
    return table(['Scene', '65C02 cycles measured', '65C02 cycles P5 '
                  'allows at P1', 'Ratio', 'µs at P1 (45 M cycles/s)'],
                 rows, 1)


def frame_table(m: 'Measurements') -> str:
    rows = []
    for scenario in SCENARIOS:
        trace = m.traces[scenario.key]
        instructions = frame_instructions(trace)
        for pr in PROFILES:
            micro = total_cost(m, scenario.key, pr)[1]
            seconds = instructions * micro / 1e6
            rows.append([scenario.key, pr, number(instructions),
                         '%.2f s' % seconds, '%.2f' % (1 / seconds)])
    return table(['Scene', 'Profile', 'Instructions a frame (median, '
                  'PROFILE.md)', 'Frame, all interpreted',
                  'Frames a second'], rows, 2)


def coverage_table(m: 'Measurements') -> str:
    rows = []
    for scenario in SCENARIOS:
        data = m.samples[(scenario.key, 'f121')]
        skipped = data['skipped']
        rows.append([scenario.key, number(data['samples']),
                     number(data['measured']), number(data['failures']),
                     number(data['warmed']),
                     number(skipped['io']), number(skipped['unmapped']),
                     number(skipped['aliased'] + skipped['unstable'])])
    return table(['Scene', 'Samples', 'Measured', 'Differences',
                  'Run twice', 'Skipped: I/O', 'Skipped: unmapped',
                  'Skipped: other'], rows, 1)


def phase_table(m: 'Measurements', scenario) -> str:
    phases = m.traces[scenario.key].phases
    by_profile = {pr: m.samples[(scenario.key, pr)] for pr in PROFILES}
    total = sum(v[0] for v in by_profile['f121']['phases'].values())
    rows = []
    for phase in profile816.PHASES:
        if phase.key not in phases:
            continue
        index = str(phases.index(phase.key))
        if index not in by_profile['f121']['phases']:
            continue
        n, c, _ = by_profile['f121']['phases'][index]
        row = [phase.title, number(n), percent(n, total), fmt_cycles(c / n)]
        for pr in PROFILES:
            n2, _, k = by_profile[pr]['phases'][index]
            row.append(fmt_us(us(k / n2, by_profile[pr]['fabric_mhz'])))
        rows.append(row)
    return table(['Phase', 'Samples', 'Share', '65C02 cycles', 'µs, f121',
                  'µs, fastpath'], rows, 1)


def parts_sums(m: 'Measurements') -> Dict[str, Dict[str, List[int]]]:
    sums: Dict[str, Dict[str, List[int]]] = {
        pr: defaultdict(lambda: [0, 0]) for pr in PROFILES}
    for scenario in SCENARIOS:
        for pr in PROFILES:
            for name, (c, k) in m.samples[(scenario.key, pr)]['parts'] \
                    .items():
                sums[pr][name][0] += c
                sums[pr][name][1] += k
    return sums


def parts_table(m: 'Measurements', values: Dict[str, str]) -> str:
    rows = []
    sums = parts_sums(m)
    names = list(m.samples[(SCENARIOS[0].key, 'f121')]['parts'])
    totals = {pr: (sum(v[0] for v in sums[pr].values()),
                   sum(v[1] for v in sums[pr].values())) for pr in PROFILES}
    for name in names:
        if not sums['f121'][name][0]:
            continue
        rows.append([name, percent(sums['f121'][name][0], totals['f121'][0]),
                     percent(sums['f121'][name][1], totals['f121'][1]),
                     percent(sums['fastpath'][name][1],
                             totals['fastpath'][1])])
    values['far_share'] = percent(sums['f121']['far layer'][0],
                                  totals['f121'][0], 0)
    return table(['Part of the interpreter', 'Share of the 65C02 cycles',
                  'Share of the time, f121', 'Share of the time, fastpath'],
                 rows, 1)


CLASS_TITLES = (
    ('fast_clocks', 'Fast memory: main RAM, language card, base aux'),
    ('ramworks_clocks', 'Extended memory: RamWorks banks (PSRAM)'),
    ('io_clocks', '$C0xx: the soft switches RAMRD, RAMWRT and $C073'),
    ('video_clocks', 'Video mirror'))


def classes_table(m: 'Measurements', values: Dict[str, str]) -> str:
    rows = []
    for pr in PROFILES:
        sums: Counter = Counter()
        measured = 0
        for scenario in SCENARIOS:
            data = m.samples[(scenario.key, pr)]
            sums.update(data['classes'])
            measured += data['measured']
        total = sum(sums[key] for key, _ in CLASS_TITLES)
        for key, title_text in CLASS_TITLES:
            rows.append([pr, title_text, percent(sums[key], total),
                         fmt_us(us(sums[key] / measured,
                                   m.vectors[pr].fabric_mhz))])
            values['class_%s_%s' % (key, pr)] = percent(sums[key], total,
                                                        0)
        values['bus_%s' % pr] = '%.2f' % (sums['bus_cycles'] / measured)
        values['switches_%s' % pr] = '%.2f' % (sums['io_accesses'] /
                                               measured)
    return table(['Profile', 'Accesses', 'Share of the time',
                  'µs an instruction'], rows, 2)


def top_table(m: 'Measurements') -> str:
    """The opcodes and widths that take the most time in the samples of
    both scenes, with their vector medians."""
    time: Counter = Counter()
    counts: Counter = Counter()
    cycles: Counter = Counter()
    fastpath: Counter = Counter()
    for scenario in SCENARIOS:
        for key, stats in json_buckets(
                m.samples[(scenario.key, 'f121')]).items():
            time[key] += stats.clocks[3]
            counts[key] += stats.count
            cycles[key] += stats.cycles[3]
        for key, stats in json_buckets(
                m.samples[(scenario.key, 'fastpath')]).items():
            fastpath[key] += stats.clocks[3]
    total_time = sum(time.values())
    total_count = sum(counts.values())
    fabric = m.vectors['f121'].fabric_mhz
    rows = []
    ranked = sorted(time, key=lambda k: (-time[k], k))
    for key in ranked[:TOP_OPCODES]:
        opcode, e, mm, x = key
        vector = m.vectors['f121'].buckets.get(key)
        rows.append(['$%02X' % opcode, instruction(opcode),
                     WIDTHS[mm << 1 | x] if not e else 'emulation',
                     percent(counts[key], total_count),
                     percent(time[key], total_time),
                     fmt_cycles(cycles[key] / counts[key]),
                     fmt_cycles(vector.cycles[1]) if vector else '-',
                     fmt_us(us(time[key] / counts[key], fabric)),
                     fmt_us(us(fastpath[key] / counts[key], fabric))])
    shown = ranked[:TOP_OPCODES]
    rows.append(['', '%d others' % (len(ranked) - len(shown)), '',
                 percent(total_count - sum(counts[k] for k in shown),
                         total_count),
                 percent(total_time - sum(time[k] for k in shown),
                         total_time), '', '', '', ''])
    return table(['Opcode', 'Instruction', 'Widths', 'Share of the '
                  'instructions', 'Share of the time, f121', 'Cycles, '
                  'mean in the game', 'Cycles, vector median', 'µs, f121',
                  'µs, fastpath'], rows, 3)


def page_table(m: 'Measurements', values: Dict[str, str]) -> str:
    rows = []
    for pr in PROFILES:
        cost = page_cost(m, pr)
        rows.append([pr, fmt_cycles(cost.same_cycles), fmt_us(cost.same_us),
                     fmt_cycles(cost.hit_cycles), fmt_us(cost.hit_us),
                     fmt_cycles(cost.miss_cycles), fmt_us(cost.miss_us)])
        values['hit_cycles'] = fmt_cycles(cost.hit_cycles)
        values['miss_cycles'] = fmt_cycles(cost.miss_cycles)
    values['slots'] = str(m.pages['f121']['slots'])
    return table(['Profile', 'JMP in its page: cycles', 'µs',
                  'A change of page, cached: more cycles', 'µs',
                  'A change of page, not cached: more cycles', 'µs'],
                 rows, 1)


def code_table(m: 'Measurements') -> str:
    rows = []
    for scenario in SCENARIOS:
        for label, skip in LABELS:
            rate = code_rate(m.traces[scenario.key], skip)
            row = [scenario.key, label, '%.3f' % rate.changes,
                   percent(rate.misses, rate.changes),
                   '%.4f' % rate.misses]
            for pr in PROFILES:
                row.append(fmt_us(cache_cost(m, scenario.key, pr, skip)[1]))
            rows.append(row)
    return table(['Scene', 'Instructions', 'Changes of page an '
                  'instruction', 'Missed', 'Misses an instruction',
                  'µs an instruction, f121', 'µs, fastpath'], rows, 2)


def cell(stats: Optional[Stats], fabric: float, field: str) -> str:
    """The median of every case; the range of vector cases leaves out
    those set apart (stats.rest)."""
    if stats is None:
        return '-'
    if field == 'cycles':
        mid = stats.cycles[1]
        if stats.apart:
            if stats.rest is None:
                return '%s (every case set apart)' % number(mid)
            low, _, high, _ = stats.rest.cycles
        else:
            low, _, high, _ = stats.cycles
        if low == high == mid:
            return number(mid)
        return '%s (%s-%s)' % (number(mid), number(low), number(high))
    return fmt_us(us(stats.clocks[1], fabric))


def median_shift(m: 'Measurements') -> int:
    """The most the 65C02 cycle median of an opcode and mode of the
    vectors moves when the cases set apart are left out."""
    return max((abs(s.cycles[1] - s.rest.cycles[1])
                for v in m.vectors.values() for s in v.modes.values()
                if s.rest is not None), default=0)


def opcode_table(m: 'Measurements') -> str:
    rows = []
    f121, fast = m.vectors['f121'], m.vectors['fastpath']
    for opcode in range(256):
        row = ['$%02X' % opcode, instruction(opcode)]
        for e in (0, 1):
            row.append(cell(f121.modes.get((opcode, e)), f121.fabric_mhz,
                            'cycles'))
            row.append(cell(f121.modes.get((opcode, e)), f121.fabric_mhz,
                            'us'))
            row.append(cell(fast.modes.get((opcode, e)), fast.fabric_mhz,
                            'us'))
        rows.append(row)
    return table(['Opcode', 'Instruction', 'Native: cycles, median '
                  '(range)', 'µs, f121', 'µs, fastpath', 'Emulation: '
                  'cycles, median (range)', 'µs, f121', 'µs, fastpath'],
                 rows, 2)


def vector_totals(m: 'Measurements') -> str:
    rows = []
    for pr in PROFILES:
        v = m.vectors[pr]
        rows.append([pr, number(v.cases), number(v.cases - v.unmeasured),
                     number(v.failures), number(v.known)])
    return table(['Profile', 'Cases', 'Measured', 'Differences',
                  'Known issues of the set'], rows, 1)


def unmapped_table(m: 'Measurements', code: codemap.CodeMap) -> str:
    """The accesses that made samples skip as unmapped, both scenes:
    bank $00 by page, the other banks together by instruction."""
    groups: Dict[Tuple, List] = {}
    for scenario in SCENARIOS:
        for page_text, space, write, count, pc_text in \
                m.samples[(scenario.key, 'f121')]['unmapped']:
            page, pc = int(page_text, 16), int(pc_text, 16)
            bank = page >> 8
            where = code.place(pc).function
            key = (0, page, space, write, where) if bank == 0 else \
                (1, 0, space, write, where)
            entry = groups.setdefault(key, [bank, bank, 0])
            entry[0] = min(entry[0], bank)
            entry[1] = max(entry[1], bank)
            entry[2] += count
    rows = []
    for key in sorted(groups, key=lambda k: (-groups[k][2], k)):
        far, page, space, write, where = key
        low, high, count = groups[key]
        if not far:
            place = '$00:%02X00-%02XFF' % (page & 0xff, page & 0xff)
        elif low == high:
            place = 'bank $%02X' % low
        else:
            place = 'banks $%02X-$%02X' % (low, high)
        rows.append([place, space, 'write' if write else 'read',
                     '`%s`' % where, number(count)])
    return table(['Address', 'Kind', 'Access', 'First seen in',
                  'Samples'], rows, 4)


def contact_values(m: 'Measurements') -> Dict[str, str]:
    c = m.contact['f121']
    fast = m.contact['fastpath']
    for key in ('identical', 'stop', 'why', 'stop_opcode',
                'interpreter_status', 'interpreter_trap_address',
                'memory_differences_at_stop', 'reference_before'):
        if c[key] != fast[key]:
            raise ValueError('the two contact runs differ in %s' % key)
    before = c['reference_before']
    access = c.get('reference_access', {})
    address = access.get('address', '------')
    values = {
        'contact_identical': number(c['identical']),
        'contact_stop': {
            'io': 'at the first access to the IIgs I/O space',
            'limit': 'at the instruction limit',
            'difference': 'at a difference'}.get(c['stop'], c['stop']),
        'contact_why': c['why'] or 'none',
        'contact_pc': '$' + before['pc'],
        'contact_opcode': '$%s' % c['stop_opcode'],
        'contact_instruction': instruction(int(c['stop_opcode'], 16)),
        'contact_access': '$%s:%s' % (address[:2], address[2:]),
        'contact_access_kind': access.get('kind', 'none'),
        'contact_access_rw': 'write' if access.get('write') else 'read',
        'contact_trap': '$%s:%s' % (c['interpreter_trap_address'][:2],
                                    c['interpreter_trap_address'][2:]),
        'contact_status': str(c['interpreter_status']),
        'contact_banks': str(c['map_banks']),
        'contact_loaded': number(c['loaded_nonzero_bytes']),
        'contact_aliased': number(c['aliased_bytes']),
        'contact_mem_start': number(c['memory_differences_at_start']),
        'contact_mem_stop': number(c['memory_differences_at_stop']),
        'contact_mem_banks': ', '.join(
            '$%s' % b for b in sorted(
                c['memory_differences_at_stop_by_bank'])) or 'none',
        'contact_unloaded': contact_unloaded(c),
        'contact_result': contact_result(c),
        'contact_alias_text': (
            'They differ the same way at the stop: no instruction of the '
            'run wrote them, and one that read them would have shown in '
            'its registers.'
            if c['memory_differences_at_stop'] ==
            c['memory_differences_at_start'] and
            c['memory_differences_at_stop_by_bank'] ==
            c['memory_differences_at_start_by_bank']
            else 'At the stop the differences are not those of the start: '
            'see the table.'),
    }
    rows = []
    buckets = {pr: json_buckets(m.contact[pr]) for pr in PROFILES}
    for key in sorted(buckets['f121'],
                      key=lambda k: (-buckets['f121'][k].count, k)):
        s = buckets['f121'][key]
        if s.count < 100:
            continue
        rows.append(['$%02X' % key[0], instruction(key[0]),
                     WIDTHS[key[2] << 1 | key[3]], number(s.count),
                     cell(s, 0, 'cycles'),
                     fmt_us(us(s.clocks[1], c['fabric_mhz'])),
                     fmt_us(us(buckets['fastpath'][key].clocks[1],
                               fast['fabric_mhz']))])
    small = [s for s in buckets['f121'].values() if s.count < 100]
    rows.append(['', '%d other opcodes and widths' % len(small), '',
                 number(sum(s.count for s in small)), '', '', ''])
    values['contact_table'] = table(
        ['Opcode', 'Instruction', 'Widths', 'Count', 'Cycles, median '
         '(range)', 'µs, f121', 'µs, fastpath'], rows, 3)
    values['contact_us_f121'] = fmt_us(us(
        c['clocks_measured'] / c['identical'], c['fabric_mhz']))
    values['contact_us_fastpath'] = fmt_us(us(
        fast['clocks_measured'] / fast['identical'], fast['fabric_mhz']))
    values['contact_cycles'] = fmt_cycles(c['cycles_measured'] /
                                          c['identical'])
    return values


def contact_result(c: Dict) -> str:
    """One sentence: how the first contact ended."""
    if c['stop'] == 'io':
        same = c['interpreter_trap_address'] == \
            c.get('reference_access', {}).get('address')
        return ('It stopped where it should: the reference\'s next '
                'instruction accesses the IIgs I/O space, and the '
                'interpreter trapped on that same access%s.' %
                ('' if same else ' (NOT at the same address: see the '
                 'values below)'))
    if c['stop'] == 'limit':
        return 'It stopped at the instruction limit, with no difference.'
    return ('It stopped at a DIFFERENCE: %s.' % c['why'])


def contact_unloaded(c: Dict) -> str:
    by_bank = c['unloaded_nonzero_bytes']
    groups = []
    store = sum(v for b, v in by_bank.items() if 0x40 <= int(b, 16) < 0x5c
                and v > 2)
    probes = sorted(b for b, v in by_bank.items() if v == 2)
    if store:
        groups.append('%s bytes of the level store in banks $40-$5B' %
                      number(store))
    if probes:
        groups.append('the two bytes of the loader\'s memory probe in each '
                      'of %d banks the map leaves out' % len(probes))
    if 'E0' in by_bank:
        groups.append('%s bytes of bank $E0 (the copies the shadow '
                      'register made of the text and hi-res pages of bank '
                      '$00)' % number(by_bank['E0']))
    known = set(probes) | {'E0'} | {b for b in by_bank
                                    if 0x40 <= int(b, 16) < 0x5c}
    for bank in sorted(set(by_bank) - known):
        groups.append('%s bytes of bank $%s' % (number(by_bank[bank]), bank))
    return '; '.join(groups) if groups else 'none'


# ---- the document ----

def document(m: 'Measurements', template: str, linkmap: Dict) -> str:
    values: Dict[str, str] = {}
    code = codemap.CodeMap(linkmap)
    values['unmapped'] = unmapped_table(m, code)
    values['logic_sp'] = '$%04X' % script.Symbols(linkmap).address(
        profile816.TIC_STACK)
    values['headline'] = headline_table(m, values)
    values['methods'] = methods_table(m, values)
    values['p5'] = p5_table(m)
    values['frames'] = frame_table(m)
    values['coverage'] = coverage_table(m)
    for scenario in SCENARIOS:
        values['phases_' + scenario.key] = phase_table(m, scenario)
    values['parts'] = parts_table(m, values)
    values['classes'] = classes_table(m, values)
    values['top'] = top_table(m)
    values['top_count'] = str(TOP_OPCODES)
    values['pages'] = page_table(m, values)
    values['code'] = code_table(m)
    values['opcodes'] = opcode_table(m)
    values['vector_totals'] = vector_totals(m)
    apart = {m.vectors[pr].apart for pr in PROFILES}
    if len(apart) != 1:
        raise ValueError('the profiles set apart different cases: %s'
                         % sorted(apart))
    values['vector_apart'] = number(apart.pop())
    values['vector_cases'] = number(m.vectors['f121'].cases)
    values['median_shift'] = number(median_shift(m))
    values.update(contact_values(m))
    values['sample_every'] = str(SAMPLE_EVERY)
    values['p5_us'] = '%.1f' % P5_US
    values['p5_range'] = '%.1f to %.1f' % (P5_LOW, P5_HIGH)
    values['p5_cycles'] = '%.0f' % (P5_US * P1_HZ / 1e6)
    values['tier0_frame'] = '%.1f' % TIER0_FRAME_S
    values['fabric_mhz'] = '%.3f' % m.vectors['f121'].fabric_mhz
    measured = sum(m.samples[(s.key, 'f121')]['measured'] for s in SCENARIOS)
    failures = sum(m.samples[(s.key, pr)]['failures'] for s in SCENARIOS
                   for pr in PROFILES)
    samples = sum(m.samples[(s.key, 'f121')]['samples'] for s in SCENARIOS)
    values['skipped_share'] = percent(samples - measured, samples)
    values['samples_measured'] = number(measured)
    values['samples_failures'] = number(failures)
    values['vector_failures'] = number(sum(m.vectors[pr].failures
                                           for pr in PROFILES))
    return template.format(**values)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--run', action='store_true',
                        help='make the measurements again')
    parser.add_argument('--data', type=Path, default=DATA)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    arguments = parser.parse_args(argv)
    try:
        measure(arguments.data, arguments.run)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    with open(str(make_image.LINKMAP)) as handle:
        linkmap = json.load(handle)
    text = document(load(arguments.data), TEMPLATE.read_text(), linkmap)
    arguments.output.write_text(text)
    print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
