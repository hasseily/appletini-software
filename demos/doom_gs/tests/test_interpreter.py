"""Tests of the interpreter's cost and of its first contact with the game
(docs/MILESTONES.md 3.2, items 2 and 3): the cost mode of
tools/a2vm/vm816.c, tools/a2vm/game816.c (contact, samples, pages) and
the report, tools/a2vm/interpreter_report.py, which writes
docs/INTERPRETER.md.

The report is tested on synthetic measurements whose results can be
worked out by hand, and, when build/a2vm/interp holds the measurements,
against docs/INTERPRETER.md itself. The first contact needs the release
image (tools/fetch_upstream.py) and the link map (imgmatch.py).
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support
from a2vm import costs, interpreter_report as report
from ref816 import make_image, title
from test_profile816 import LINKMAP as SYNTHETIC_LINKMAP
from test_ref816_machine import needs_linkmap
from test_vm import VECTOR_BIN, build, have_tools, mutant, needs_vectors

ORA_BUG = ('alu.s', 'op_ora: lda vA\n        ora dat',
           'op_ora: lda vA\n        and dat')
# INY increments X: crt0 runs it for every byte it clears.
INY_BUG = ('handlers.s', 'hC8:    sty vpcl                ; INY\n'
           '        ldx #vY', 'hC8:    sty vpcl                ; INY\n'
           '        ldx #vX')
# INY also writes the byte of main $1400: virtual $00:0900, the direct page.
INY_STRAY = ('handlers.s', 'hC8:    sty vpcl                ; INY\n',
             'hC8:    sty vpcl                ; INY\n'
             '        stz $1400\n')


def temporary():
    directory = Path(tempfile.mkdtemp(prefix='test-interp-',
                                      dir=str(support.BUILD)))
    return directory


def parameters(profile, directory):
    return costs.write(profile, directory / ('%s.txt' % profile))


def tool(name, vm, *arguments):
    out, _ = support.a2vm_build()
    return subprocess.run(
        [str(out / name), '--vm', str(vm)] + [str(a) for a in arguments],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True)


# ---- vm816 --cost ----

@have_tools
@needs_vectors
class VectorCost(unittest.TestCase):
    FILES = ('a9.n.bin', 'ea.n.bin', 'ea.e.bin', 'b1.n.bin', '54.n.bin')
    LIMIT = 40

    def setUp(self):
        support.BUILD.mkdir(exist_ok=True)
        self.directory = temporary()
        self.addCleanup(shutil.rmtree, str(self.directory))
        self.params = parameters('f121', self.directory)

    def measure(self, vm, name='out.cost'):
        path = self.directory / name
        result = tool('vm816', vm, '--limit', self.LIMIT, '--cost',
                      self.params, path,
                      *[VECTOR_BIN / f for f in self.FILES])
        return result, path

    def test_every_case_is_measured_and_checked(self):
        vm, _ = build()
        result, path = self.measure(vm)
        self.assertEqual(result.returncode, 0, result.stdout)
        cost = report.read_vector_cost(path)
        cases = self.LIMIT * len(self.FILES)
        self.assertEqual((cost.cases, cost.failures, cost.unmeasured),
                         (cases, 0, 0))
        self.assertEqual(sum(s.count for s in cost.buckets.values()), cases)
        self.assertEqual(sum(s.count for s in cost.modes.values()), cases)
        for (opcode, e), mode in cost.modes.items():
            widths = [s for (o, ee, _, _), s in cost.buckets.items()
                      if (o, ee) == (opcode, e)]
            self.assertEqual(mode.count, sum(s.count for s in widths))
            self.assertEqual(mode.cycles[3], sum(s.cycles[3] for s in widths))
        for stats in cost.buckets.values():
            for low, mid, high, total in (stats.cycles, stats.clocks):
                self.assertTrue(0 < low <= mid <= high, stats)
                self.assertTrue(low * stats.count <= total <=
                                high * stats.count)
        # A NOP reads no operand: the same cost in every case and mode,
        # but for a case that loads a code page, which is set apart.
        nops = [s for (o, _, _, _), s in cost.buckets.items() if o == 0xea]
        self.assertEqual(len({s.rest.cycles[0] for s in nops} |
                             {s.rest.cycles[2] for s in nops}), 1)
        for stats in list(cost.buckets.values()) + list(cost.modes.values()):
            self.assertEqual(stats.count, stats.apart + (
                stats.rest.count if stats.rest else 0))
        self.assertEqual(cost.apart, sum(s.apart
                                         for s in cost.buckets.values()))

    def test_sets_apart_a_case_that_loads_a_page(self):
        """A NOP at the first byte of a page: its fetch loads the page,
        cold, while it is measured. The case is set apart from the range,
        which is then that of every other NOP."""
        vm, _ = build()
        files = sorted(VECTOR_BIN.glob('ea.*.bin'))
        path = self.directory / 'nop.cost'
        result = tool('vm816', vm, '--cost', self.params, path, *files)
        self.assertEqual(result.returncode, 0, result.stdout)
        cost = report.read_vector_cost(path)
        self.assertGreater(cost.apart, 0)
        for stats in cost.modes.values():
            self.assertEqual(stats.rest.cycles[0], stats.rest.cycles[2])
        loaded = [s for s in cost.modes.values() if s.apart]
        self.assertTrue(loaded)
        for stats in loaded:
            # the maximum over every case has the copy of 256 bytes
            self.assertGreater(stats.cycles[2], stats.rest.cycles[2] + 1024)

    def test_is_deterministic(self):
        vm, _ = build()
        first = self.measure(vm, 'a.cost')[1].read_text()
        second = self.measure(vm, 'b.cost')[1].read_text()
        self.assertEqual(first, second)

    def test_still_checks_the_results(self):
        vm = mutant('ora', *ORA_BUG)
        path = self.directory / 'ora.cost'
        result = tool('vm816', vm, '--limit', 5, '--cost', self.params, path,
                      VECTOR_BIN / '09.n.bin')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('5 failures', result.stdout)


# ---- game816 samples and pages ----

def sample(pc, before, reads, writes, after, phase=2):
    """A sample of tools/ref816/trace.h: before and after are (A, X, Y, S,
    D, DBR, P, E) and the PC after; reads and writes (address, value,
    space)."""
    a, x, y, s, d, dbr, p, e = before
    lines = ['s %d %06X %04X %04X %04X %04X %04X %02X %02X %d' % (
        phase, pc, a, x, y, s, d, dbr, p, e), 'p 020000']
    lines += ['r %06X %02X %s' % r for r in reads]
    lines += ['w %06X %02X %s' % w for w in writes]
    a, x, y, s, d, dbr, p, e, next_pc = after
    lines.append('a %06X %04X %04X %04X %04X %04X %02X %02X %d 0' % (
        next_pc, a, x, y, s, d, dbr, p, e))
    return lines


NATIVE = (0, 0, 0, 0x3ff0, 0x0900, 0x02, 0x04, 0)
LDA_IMMEDIATE = sample(
    0x038000, NATIVE,
    [(0x038000, 0xa9, 'program'), (0x038001, 0x34, 'program'),
     (0x038002, 0x12, 'program')], [],
    (0x1234, 0, 0, 0x3ff0, 0x0900, 0x02, 0x04, 0, 0x038003))
STA_DIRECT = sample(
    0x038010, (0xabcd,) + NATIVE[1:],
    [(0x038010, 0x85, 'program'), (0x038011, 0x10, 'program')],
    [(0x000910, 0xcd, 'direct'), (0x000911, 0xab, 'direct')],
    (0xabcd, 0, 0, 0x3ff0, 0x0900, 0x02, 0x04, 0, 0x038012))
READS_IO = sample(
    0x038000, NATIVE,
    [(0x038000, 0xad, 'program'), (0x038001, 0x19, 'program'),
     (0x038002, 0xc0, 'program'), (0x00c019, 0x80, 'io')], [],
    (0x0080, 0, 0, 0x3ff0, 0x0900, 0x02, 0x04, 0, 0x038003))
READS_UNMAPPED = sample(
    0x038000, NATIVE,
    [(0x038000, 0xaf, 'program'), (0x038001, 0x00, 'program'),
     (0x038002, 0x00, 'program'), (0x038003, 0x7f, 'program'),
     (0x7f0000, 0x55, 'data'), (0x7f0001, 0x00, 'data')], [],
    (0x0055, 0, 0, 0x3ff0, 0x0900, 0x02, 0x04, 0, 0x038004))
TWO_PAGES = sample(
    0x0380fe, NATIVE,
    [(0x0380fe, 0xa9, 'program'), (0x0380ff, 0x34, 'program'),
     (0x038100, 0x12, 'program')], [],
    (0x1234, 0, 0, 0x3ff0, 0x0900, 0x02, 0x04, 0, 0x038101))
WRONG_AFTER = sample(
    0x038000, NATIVE,
    [(0x038000, 0xa9, 'program'), (0x038001, 0x34, 'program'),
     (0x038002, 0x12, 'program')], [],
    (0x1235, 0, 0, 0x3ff0, 0x0900, 0x02, 0x04, 0, 0x038003))


@have_tools
class Samples(unittest.TestCase):
    def setUp(self):
        support.BUILD.mkdir(exist_ok=True)
        self.directory = temporary()
        self.addCleanup(shutil.rmtree, str(self.directory))
        self.params = parameters('f121', self.directory)

    def run_samples(self, samples, vm=None):
        path = self.directory / 'test.samples'
        lines = ['ref816-samples 1']
        for s in samples:
            lines += s
        lines.append('end %d 0' % len(samples))
        path.write_text('\n'.join(lines) + '\n')
        result = tool('game816', vm or build()[0], '--cost', self.params,
                      'samples', path)
        return result, json.loads(result.stdout)

    def test_runs_and_checks_samples(self):
        result, data = self.run_samples(
            [LDA_IMMEDIATE, STA_DIRECT, READS_IO, READS_UNMAPPED, TWO_PAGES])
        self.assertEqual(result.returncode, 0, result.stdout)
        # LDA_IMMEDIATE starts a page, TWO_PAGES crosses one
        self.assertEqual((data['samples'], data['measured'],
                          data['failures'], data['warmed']), (5, 3, 0, 2))
        self.assertEqual(data['skipped'], {'io': 1, 'unmapped': 1,
                                           'aliased': 0, 'unstable': 0})
        self.assertEqual(data['unmapped'],
                         [['7F00', 'data', 0, 1, '038000']])
        buckets = report.json_buckets(data)
        self.assertEqual(buckets[(0xa9, 0, 0, 0)].count, 2)
        self.assertEqual(buckets[(0x85, 0, 0, 0)].count, 1)
        # The immediate load costs the same at the start of a page and
        # across two as anywhere: the pages are in the cache when it is
        # measured, and the lookups are set apart.
        self.assertEqual(buckets[(0xa9, 0, 0, 0)].cycles[0],
                         buckets[(0xa9, 0, 0, 0)].cycles[2])
        self.assertGreater(data['page_loads_set_apart'][0], 0)
        self.assertEqual(data['phases'], {'2': [
            3, sum(b.cycles[3] for b in buckets.values()),
            sum(b.clocks[3] for b in buckets.values())]})
        parts = sum(c for c, _ in data['parts'].values())
        self.assertEqual(parts, data['phases']['2'][1])
        self.assertEqual(data['parts']['code cache: a new page'], [0, 0])

    def test_sees_a_wrong_result(self):
        result, data = self.run_samples([LDA_IMMEDIATE, WRONG_AFTER])
        self.assertEqual(result.returncode, 1)
        self.assertEqual((data['measured'], data['failures']), (1, 1))
        self.assertIn('A is 1234', data['failures_shown'][0]['why'])

    def test_sees_a_stray_write(self):
        vm = mutant('iny-stray', *INY_STRAY)
        iny = sample(0x038000, NATIVE, [(0x038000, 0xc8, 'program')], [],
                     (0, 0, 1, 0x3ff0, 0x0900, 0x02, 0x04, 0, 0x038001))
        result, data = self.run_samples([iny], vm)
        self.assertEqual(result.returncode, 1)
        self.assertIn('$000900, the reference did not',
                      data['failures_shown'][0]['why'])


@have_tools
class Pages(unittest.TestCase):
    def test_a_change_of_page_costs_more_and_a_miss_most(self):
        directory = temporary()
        self.addCleanup(shutil.rmtree, str(directory))
        result = tool('game816', build()[0], '--cost',
                      parameters('fastpath', directory), 'pages')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        per = {key: data[key]['cycles'] / data[key]['instructions']
               for key in ('same_page', 'hit', 'miss')}
        self.assertLess(per['same_page'], per['hit'])
        # a miss copies 256 bytes: at least 4 cycles a byte more
        self.assertGreater(per['miss'], per['hit'] + 4 * 256)
        self.assertEqual(data['hit']['pages'], data['slots'])
        self.assertGreater(data['miss']['pages'], data['slots'])


# ---- the first contact ----

@have_tools
@needs_linkmap
@support.needs_release
class Contact(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        title.ensure_image()
        cls.image = make_image.OUT_DIR / 'memory.img'
        cls.result = tool('game816', build()[0], 'contact', cls.image)
        cls.data = json.loads(cls.result.stdout)

    def test_reaches_the_first_io_access(self):
        d = self.data
        self.assertEqual(self.result.returncode, 0, self.result.stderr)
        self.assertEqual(d['stop'], 'io')
        self.assertEqual(d['why'], '')
        self.assertGreater(d['identical'], 300000)
        self.assertEqual(d['reference_access']['kind'],
                         'the IIgs I/O space')
        self.assertEqual(d['interpreter_trap_address'],
                         d['reference_access']['address'])
        self.assertEqual(d['interpreter_status'],
                         2 if d['reference_access']['write'] else 1)
        # the one difference of memory: $01 shares $E1's memory
        self.assertEqual(d['memory_differences_at_stop'],
                         d['memory_differences_at_start'])
        self.assertEqual(set(d['memory_differences_at_stop_by_bank']),
                         {'01'})
        self.assertEqual(sum(b[4] for b in d['buckets']), d['identical'])

    def test_limit(self):
        result = tool('game816', build()[0], '--limit', 1000, 'contact',
                      self.image)
        data = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((data['stop'], data['identical']), ('limit', 1000))

    def test_is_deterministic_with_the_cost_model(self):
        directory = temporary()
        self.addCleanup(shutil.rmtree, str(directory))
        params = parameters('f121', directory)
        first = tool('game816', build()[0], '--cost', params, '--limit',
                     20000, 'contact', self.image).stdout
        second = tool('game816', build()[0], '--cost', params, '--limit',
                      20000, 'contact', self.image).stdout
        self.assertEqual(first, second)
        self.assertGreater(json.loads(first)['clocks_measured'], 0)

    def test_sees_a_wrong_operation(self):
        result = tool('game816', mutant('iny', *INY_BUG), 'contact',
                      self.image)
        data = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(data['stop'], 'difference')
        self.assertLess(data['identical'], self.data['identical'])

    def test_sees_a_stray_write(self):
        result = tool('game816', mutant('iny-stray', *INY_STRAY), 'contact',
                      self.image)
        data = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(data['stop'], 'difference')
        self.assertIn('the reference did not', data['why'])


# ---- the report ----

FABRIC = 100.0


def synthetic(directory):
    """Measurement files for the report whose results are known: every
    profile and scene the same; still and demo share the numbers."""
    phases = ['other', 'interrupt'] + [p.key for p in report.profile816
                                       .PHASES if p.key not in
                                       ('other', 'interrupt')]
    seg, replay = phases.index('seg'), phases.index('replay')
    trace = ['ref816-trace 1'] + ['phase %d %s' % (i, name)
                                  for i, name in enumerate(phases)]
    trace += ['split 1B6F', 'frame 0 0 0 0 5000 1000 1000',
              'cost %d 900 800' % seg, 'cost %d 100 200' % replay,
              'op %d A9 0 900' % seg, 'op %d EA 2 100' % replay,
              'code %d 45 9' % seg, 'code %d 5 1' % replay, 'unclosed 0',
              'smc-mixed 0', 'end 5000 1000 1000']
    # One LDA # case loaded a code page: set apart from the ranges.
    vectors = ['vm816-cost 2', 'fabric_mhz %.6f' % FABRIC,
               'cases 20 failures 0 known 0 unmeasured 0 apart 1',
               'bucket A9 0 0 0 10 90 100 5000 5890 180 200 9000 10890 '
               'apart 1 9 90 100 110 890 180 200 220 1890',
               'bucket EA 0 1 0 10 40 40 40 400 80 80 80 800 '
               'apart 0 10 40 40 40 400 80 80 80 800',
               'mode A9 0 10 90 100 5000 5890 180 200 9000 10890 '
               'apart 1 9 90 100 110 890 180 200 220 1890',
               'mode EA 0 10 40 40 40 400 80 80 80 800 '
               'apart 0 10 40 40 40 400 80 80 80 800']
    pages = {'format': 'game816-pages 1', 'cost_model': True,
             'fabric_mhz': FABRIC, 'slots': 16,
             'same_page': {'pages': 1, 'instructions': 100,
                           'cycles': 10000, 'clocks': 20000},
             'hit': {'pages': 16, 'instructions': 100, 'cycles': 30000,
                     'clocks': 60000},
             'miss': {'pages': 20, 'instructions': 100, 'cycles': 510000,
                      'clocks': 1020000}}
    samples = {'samples': 42, 'measured': 40, 'failures': 0,
               'warmed': 1,
               'skipped': {'io': 1, 'unmapped': 1, 'aliased': 0,
                           'unstable': 0},
               'unmapped': [['001B', 'stack', 1, 1, '032000']],
               'phases': {str(seg): [30, 6000, 12000],
                          str(replay): [10, 3000, 6000]},
               'fabric_mhz': FABRIC,
               'parts': {'dispatch loop': [900, 1800],
                         'far layer': [8100, 16200]},
               'classes': {'fast_clocks': 15000, 'ramworks_clocks': 1000,
                           'io_clocks': 1500, 'video_clocks': 500,
                           'bus_cycles': 20, 'io_accesses': 40},
               'buckets': [[0xa9, 0, 0, 0, 30, [200, 200, 200, 6000],
                            [400, 400, 400, 12000]],
                           [0xea, 0, 1, 0, 10, [300, 300, 300, 3000],
                            [600, 600, 600, 6000]]]}
    contact = {'identical': 1000, 'stop': 'io', 'why': '',
               'stop_opcode': 'AF', 'interpreter_status': 1,
               'interpreter_trap_address': 'E0C036',
               'reference_before': {'pc': '04:6002'},
               'reference_access': {'kind': 'the IIgs I/O space',
                                    'address': 'E0C036', 'write': False},
               'map_banks': 104, 'loaded_nonzero_bytes': 5,
               'aliased_bytes': 3, 'memory_differences_at_start': 3,
               'memory_differences_at_stop': 3,
               'memory_differences_at_start_by_bank': {'01': 3},
               'memory_differences_at_stop_by_bank': {'01': 3},
               'unloaded_nonzero_bytes': {'40': 100, '7F': 2, 'E0': 7},
               'fabric_mhz': FABRIC, 'cycles_measured': 250000,
               'clocks_measured': 500000,
               'buckets': [[0xc8, 0, 1, 0, 1000, [79, 80, 89, 80000],
                            [180, 190, 200, 190000]]]}
    directory.mkdir(parents=True, exist_ok=True)
    paths = report.paths(directory)
    for profile in report.PROFILES:
        paths['costs-' + profile].write_text('')
        paths['vectors-' + profile].write_text('\n'.join(vectors) + '\n')
        paths['pages-' + profile].write_text(json.dumps(pages))
        paths['contact-' + profile].write_text(json.dumps(contact))
        for scenario in report.SCENARIOS:
            paths['samples-%s-%s' % (scenario.key, profile)].write_text(
                json.dumps(samples))
    for scenario in report.SCENARIOS:
        paths['trace-' + scenario.key].write_text('\n'.join(trace) + '\n')
        paths['samples-' + scenario.key].write_text('')


class Report(unittest.TestCase):
    def setUp(self):
        support.BUILD.mkdir(exist_ok=True)
        self.directory = temporary()
        self.addCleanup(shutil.rmtree, str(self.directory))
        synthetic(self.directory)
        self.m = report.load(self.directory)

    def document(self):
        return report.document(self.m, report.TEMPLATE.read_text(),
                               SYNTHETIC_LINKMAP)

    def test_the_numbers(self):
        # Samples: 9,000 cycles and 18,000 clocks for 40 instructions.
        mean = report.sample_mean(self.m, 'still', 'f121')
        self.assertEqual((mean.count, mean.cycles, mean.us), (40, 225, 4.5))
        # The cache: 50 changes and 10 misses in 1,000 instructions; a
        # hit costs 200 cycles (4 us) more than none, a miss 5,000 (100).
        rate = report.code_rate(self.m.traces['still'])
        self.assertEqual((rate.changes, rate.misses), (0.05, 0.01))
        cycles, micro = report.cache_cost(self.m, 'still', 'f121')
        self.assertAlmostEqual(cycles, 0.05 * 200 + 0.01 * 4800)
        self.assertAlmostEqual(micro, 0.05 * 4 + 0.01 * 96)
        # Without the replay: 45 changes and 9 misses in 900.
        rate = report.code_rate(self.m.traces['still'], report.REPLAY)
        self.assertEqual((rate.changes, rate.misses), (0.05, 0.01))
        mean = report.sample_mean(self.m, 'still', 'f121', report.REPLAY)
        self.assertEqual((mean.cycles, mean.us), (200, 4.0))
        # The vector medians weighted by the mix: 900 x 100 + 100 x 40.
        weights = report.mix(self.m.traces['still'])
        self.assertEqual(report.weighted(
            weights, self.m.vectors['f121'].buckets, 'cycles', 1), 94)

    def test_the_document(self):
        text = self.document()
        self.assertEqual(text, self.document())
        # 225 + 58 cycles, 4.50 + 1.16 us, 5.66 / 3.2 = 1.77
        self.assertIn('| still | all instructions | 283 | 5.66 | 1.77 | '
                      '5.66 | 1.77 |', text)
        self.assertIn('| still, all instructions | vector medians | 94 |',
                      text)
        self.assertIn('| $00:1B00-1BFF | stack | write | '
                      '`r_seg65.s:R_RenderSegLoop` | 2 |', text)
        self.assertIn('(`LOGIC_SP` = $1B6F', text)
        self.assertNotIn('{', text.split('## 9.')[0])
        self.assertIn('| $EA | `NOP` | 40 | 0.80 | 0.80 | - | - | - |',
                      text)
        # The range leaves out the case set apart; the median counts it.
        self.assertIn('| $A9 | `LDA #` | 100 (90-110) | 2.00 | 2.00 |',
                      text)
        self.assertIn('The ranges leave out 1 of the 20 cases', text)
        self.assertIn('none of them by more than 0 cycles', text)

    def test_a_difference_is_reported(self):
        for profile in report.PROFILES:
            self.m.contact[profile].update(stop='difference',
                                           why='A is 0001')
        self.assertIn('It stopped at a DIFFERENCE: A is 0001.',
                      self.document())


@needs_linkmap
class TheDocument(unittest.TestCase):
    @unittest.skipUnless(
        all(p.exists() for p in report.paths(report.DATA).values()),
        '%s is incomplete: run python3 tools/a2vm/interpreter_report.py'
        % report.DATA.relative_to(support.ROOT))
    def test_docs_interpreter_md_is_current(self):
        with open(str(make_image.LINKMAP)) as handle:
            linkmap = json.load(handle)
        text = report.document(report.load(report.DATA),
                               report.TEMPLATE.read_text(), linkmap)
        self.assertEqual(text, report.OUTPUT.read_text())


if __name__ == '__main__':
    unittest.main()
