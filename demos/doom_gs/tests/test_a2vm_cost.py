"""Tests of tools/a2vm, stage 3.1c: the cost model (tools/a2vm/cost.h).

  - the parameter file tools/a2vm/costs/appletini.json: every value has a
    source, both profiles are complete, and a2vm rejects a missing,
    unknown or malformed parameter;
  - the TURBO path against the firmware's own benchmark (README_TURBO.md:
    436 clocks a warm pass of a 16-byte copy, with the virtual Disk II
    inactive, the variant nod2; on the card as measured, f121, the Disk
    II's replay adds 2 clocks for each omitted dummy read: 532);
  - micro-cases through bus scripts, with the expected clocks derived
    from the RTL: the TURBO caches and their invalidation, the RamWorks
    line cache and the PSRAM admission, a $Cxxx bus cycle, the video
    mirror with its barrier, deferred bytes and exposure flushes, and the
    fast-path changes (quiet switches, the reconciler, lazy SHR bytes);
  - the memory API's costs, per chunk as memory_api_hw.c does them;
  - with the existing port's build: the model only observes (a run with
    it matches a run without, byte for byte), a timed run is
    deterministic, and the report of 20 frames of E1M1 standing still
    meets MILESTONES.md 3.1 item 4.
"""

import json
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

import support
from a2vm import costs, cost_report, doom
from test_a2vm_machine import (AUX, MAIN, Workspace, control, descriptor,
                               have_tools, needs_doom)

COPY, FILL, PRIVATE = 1, 2, 1
# The most cycles a frame of the existing port takes on a2vm (under 1e8
# with every profile; the report's --cycles bound, cost_report.py)
PORT_CYCLES = cost_report.FRAME_CYCLES


def parse_cost(line):
    fields = dict(item.split('=') for item in line.split()[1:])
    return {key: int(value) for key, value in fields.items()}


class CostWorkspace(Workspace):
    def setUp(self):
        super().setUp()
        self.files = {name: costs.write(name, self.directory /
                                        ('%s.txt' % name))
                      for name in costs.profiles()}

    def costs(self, lines, profile='f121', *arguments):
        """Run a bus script with the cost model; the `cost` lines."""
        output = self.bus(lines, '--no-mouse', '--cost',
                          str(self.files[profile]), *arguments)
        return [parse_cost(line) for line in output
                if line.startswith('cost ')]

    def deltas(self, lines, profile='f121', *arguments):
        """The clocks between consecutive `cost` lines."""
        points = self.costs(lines, profile, *arguments)
        return [b['t'] - a['t'] for a, b in zip(points, points[1:])], points


class ParameterFile(unittest.TestCase):
    def test_every_value_has_a_source(self):
        data = costs.load()
        entries = list(data['common'].items())
        for profile in data['profiles'].values():
            entries += list(profile['params'].items())
        for name, entry in entries:
            self.assertIn('value', entry, name)
            self.assertTrue(entry.get('source', '').strip(), name)
        self.assertEqual(costs.profiles(),
                         ['f121', 'f121zp', 'f122', 'fastpath', 'fastzp'])
        extra = data['common']['turbo_extra']
        self.assertTrue(extra['calibratable'])
        self.assertFalse(extra['calibrated'])
        self.assertEqual(len(data['profiles']['fastpath']['changes']), 7)

    def test_profiles_set_the_same_parameters(self):
        profiles = costs.load()['profiles']
        for name in profiles:
            self.assertEqual(set(profiles[name]['params']),
                             set(profiles['fastpath']['params']), name)
        f121, fast = costs.parameters('f121'), costs.parameters('fastpath')
        self.assertEqual(set(f121), set(fast))
        differ = {key for key in f121 if f121[key] != fast[key]}
        # fastpath changes every profile parameter but the pair's and
        # F1.2.2's (tests/test_a2vm_zpbank.py checks f121zp and fastzp)
        self.assertEqual(differ, set(profiles['fastpath']['params']) -
                         {'zp_pair', 'rmw_queue', 'amem_engine',
                          'ps_dispatch_us'})
        # f122 is f121 with F1.2.2's admission and copy engine, and the
        # one value fitted to the card
        f122 = costs.parameters('f122')
        self.assertEqual({key for key in f121 if f121[key] != f122[key]},
                         {'relaxed_admission', 'rmw_queue', 'amem_engine',
                          'ps_dispatch_us'})


class AxiDependency(unittest.TestCase):
    """The report says that axi_us is fitted to the hardware measurement,
    so the frame total is not an independent check."""

    def report(self, fitted_ms, runs=None):
        report = {'profiles': {'f121': {'mean_ms': fitted_ms}}}
        if runs is not None:
            base = costs.parameters('f121')['axi_us']
            report['sensitivity'] = {
                'axi_us_matching_copy': 0.138,
                'runs': [{'axi_us': base, 'mean_ms': fitted_ms}] + [
                    {'axi_us': value, 'mean_ms': ms} for value, ms in
                    zip(cost_report.REVIEW_AXI_US, runs)]}
        return cost_report.axi_dependency(report)

    def test_the_source_says_fitted(self):
        entry = costs.load()['common']['axi_us']
        self.assertIn('Fitted, not measured', entry['source'])
        self.assertIn('%.1f ms' % cost_report.HARDWARE_MS, entry['source'])
        low, high = cost_report.REVIEW_AXI_US
        self.assertIn('%.3f to %.2f us' % (low, high), entry['source'])
        self.assertLess(entry['value'], low)
        self.assertEqual(costs.parameters('f121')['axi_write_us'],
                         entry['value'])

    def test_says_the_total_is_not_independent(self):
        text = self.report(248.3, [289.8, 456.8])
        self.assertIn('axi_us is fitted to this capture, not measured', text)
        self.assertIn('frame total is not an independent check', text)
        self.assertIn('248.3 ms (+0.1%)', text)
        self.assertIn('The copy phases alone give 0.138 us', text)
        self.assertIn('289.8 ms (+16.9%) at 0.305 us', text)
        self.assertIn('456.8 ms (+84.2%) at 0.980 us.', text)

    def test_without_the_sensitivity_runs(self):
        text = self.report(250.0)
        self.assertIn('frame total is not an independent check', text)
        self.assertIn('without --no-sensitivity', text)


@have_tools
class Loading(CostWorkspace):
    def run_with(self, text):
        path = self.directory / 'bad.txt'
        path.write_text(text)
        script = self.directory / 'bus.txt'
        script.write_text('cost\n')
        return support.run(
            [str(self.out / 'a2vm'), '--rom', str(self.rom), '--cost',
             str(path), '--bus-script', str(script)], timeout=120,
            max_bytes=16 << 20, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, universal_newlines=True)

    def test_rejects_bad_files(self):
        good = self.files['f121'].read_text()
        self.assertEqual(self.run_with(good).returncode, 0)
        missing = '\n'.join(line for line in good.splitlines()
                            if not line.startswith('turbo_hit '))
        result = self.run_with(missing)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no value for turbo_hit', result.stdout)
        result = self.run_with(good + 'no_such_parameter 1\n')
        self.assertIn('unknown parameter', result.stdout)
        result = self.run_with(good.replace('turbo_hit 2', 'turbo_hit 2.5'))
        self.assertIn('bad value', result.stdout)
        result = self.run_with(good.replace('rw_lines 1', 'rw_lines 0'))
        self.assertIn('out of range', result.stdout)


@have_tools
class TurboPath(CostWorkspace):
    def benchmark(self, core, profile='f121'):
        """README_TURBO.md's program (hdl/sim/tb_vtw_turbo.sv:717-747) at
        $F000 in the language card: the clocks, the accesses and the
        omitted dummy reads of each pass."""
        if profile not in self.files:
            self.files[profile] = costs.write(
                profile, self.directory / ('%s.txt' % profile))
        program = bytes([0xA2, 0x00, 0xBD, 0x00, 0x90, 0x9D, 0x00, 0xA0,
                         0xE8, 0xE0, 0x10, 0xD0, 0xF5, 0xEE, 0x00, 0xA1,
                         0x4C, 0x00, 0xF0])
        image = self.directory / 'bench.img'
        image.write_bytes(b'A2VMIMG1' + struct.pack('<BBHI', 2, 0, 0xF000,
                                                    len(program)) + program)
        report = self.directory / 'bench.jsonl'
        # bounded: ten passes take about 2,500 cycles
        support.run(
            [str(self.out / 'a2vm'), '--rom', str(self.rom), '--core', core,
             '--no-mouse', '--image', str(image), '--switch', 'lc_read=1',
             '--switch', 'lc_write=1', '--reg', 'pc=F000', '--cost',
             str(self.files[profile]), '--cost-report', str(report),
             '--boundary', 'F000', '--boundaries', '10', '--cycles',
             '1000000', '--state', str(self.directory / 'state.json')],
            timeout=120, max_bytes=16 << 20, check=True,
            stdout=subprocess.DEVNULL)
        state = json.loads((self.directory / 'state.json').read_text())
        self.assertEqual((state['end'], state['boundaries']),
                         ('boundaries', 10))
        rows = [json.loads(line) for line in report.read_text().splitlines()
                if line.startswith('{"boundary')]
        return ([row['clocks'] for row in rows],
                [row['accesses'] for row in rows],
                [row['dropped'] for row in rows])

    def test_warm_pass_takes_436_clocks(self):
        # the RTL simulation's setup: no virtual Disk II (the variant nod2)
        clocks, accesses, dropped = self.benchmark('w65c02s', 'f121+nod2')
        # 218 accesses a pass with TURBO's dummy cycles omitted
        self.assertEqual(accesses[1:], [218] * 9)
        self.assertEqual(clocks[1:], [436] * 9)
        # the cold pass misses 5 code words, 4 source words and the
        # marker's word (2 more clocks each) and 2 write pages (3 more);
        # README_TURBO.md measures 474 from the core's start, with its
        # reset sequence, where this starts at the program
        self.assertEqual(clocks[0], 436 + 2 * (5 + 4 + 1) + 3 * 2)
        # the card as measured (f121: the virtual Disk II replays each
        # step's cycles, docs/results/calib.md): the 48 omitted dummy
        # reads a pass (sta abs,x, inx and the taken bne 16 times but the
        # last bne, inc's modify), each alone in its step, take 2 clocks
        # each (436 before 2026-10-03, when f121 took them as free)
        clocks, accesses, dropped = self.benchmark('w65c02s')
        self.assertEqual(accesses[1:], [218] * 9)
        self.assertEqual(dropped[1:], [48] * 9)
        self.assertEqual(clocks[1:], [436 + 2 * 48] * 9)

    def test_the_compatibility_core_makes_no_dummy_reads(self):
        clocks, accesses, _ = self.benchmark('py65')
        # py65 does not read the offset of a branch not taken
        self.assertEqual(accesses[1:], [217] * 9)
        self.assertEqual(clocks[1:], [434] * 9)

    def test_caches_and_invalidation(self):
        lines = ['cost', 'read 1000', 'cost', 'read 1001', 'cost',
                 'read 1004', 'cost', 'write 1000 AA', 'cost',
                 'write 1001 BB', 'cost', 'write C003 00', 'write C002 00',
                 'cost', 'read 1000', 'cost']
        d, points = self.deltas(lines)
        # read miss 4, hit 2, other word 4, write miss 5, write hit 2
        self.assertEqual(d[:5], [4, 2, 4, 5, 2])
        # two bus cycles, each 122-253 clocks
        self.assertTrue(2 * 122 <= d[5] <= 2 * 254, d[5])
        self.assertEqual(points[6]['invalidations'], 2)
        self.assertEqual(d[6], 4)           # the cache was cleared
        # the fast path: quiet switches (3 clocks), caches kept
        d, points = self.deltas(lines, 'fastpath')
        self.assertEqual(d[:5], [4, 2, 4, 5, 2])
        self.assertEqual(d[5], 6)
        self.assertEqual(points[6]['invalidations'], 0)
        self.assertEqual(d[6], 2)

    def test_bus_cycle_phase(self):
        """A $C073 write costs CAPTURE and ROUTE, the wait for drive_en,
        drive_en to data_en and two clocks: 122 to 253 clocks."""
        seen = set()
        for pad in range(0, 140, 7):
            lines = ['read 1000'] + ['read 1001'] * pad + \
                ['cost', 'write C073 00', 'cost']
            d, _ = self.deltas(lines)
            self.assertTrue(122 <= d[0] <= 253, d[0])
            seen.add(d[0])
        self.assertGreater(max(seen) - min(seen), 100)


@have_tools
class ExtendedMemory(CostWorkspace):
    LINES = ['write C073 05', 'write C003 00', 'cost', 'read 4000', 'cost',
             'read 4001', 'cost', 'read 4008', 'cost', 'write C005 00',
             'write 4008 11', 'cost', 'read 4010', 'cost']

    def test_f121_single_line(self):
        d, points = self.deltas(self.LINES)
        # a clean miss: 4 clocks to the request, the admission window, 31
        self.assertTrue(35 <= d[0] <= 35 + 132, d[0])
        self.assertEqual(d[1], 5)           # a line hit
        # the next line waits for the next cycle's admission
        self.assertTrue(35 + 40 <= d[2] <= 35 + 2 * 132, d[2])
        # a dirty victim: the write, then the fill in a later cycle
        self.assertGreater(d[4], 4 + 24 + 31)
        self.assertEqual(points[-1]['rw_dirty'], 1)
        self.assertEqual(points[-1]['rw_misses'], 3)

    def test_fastpath_relaxed_and_sixteen_lines(self):
        d, points = self.deltas(self.LINES, 'fastpath')
        self.assertEqual(d[0], 35)          # no window: 4 + 31
        self.assertEqual(d[1], 5)
        self.assertEqual(d[2], 35)
        self.assertEqual(points[-1]['rw_dirty'], 0)   # 16 lines
        # sixteen dirty lines, then a seventeenth evicts one: 4 + 24 + 31
        lines = ['write C073 05', 'write C005 00'] + \
            ['write %04X 01' % (0x5000 + 8 * i) for i in range(16)] + \
            ['cost', 'write 6000 02', 'cost']
        d, points = self.deltas(lines, 'fastpath')
        self.assertEqual(d[0], 4 + 24 + 31)
        self.assertEqual(points[-1]['rw_dirty'], 1)


@have_tools
class VideoMirror(CostWorkspace):
    def lines(self, count):
        out = ['write C029 C1', 'write C005 00', 'cost']
        out += ['write %04X %02X' % (0x2000 + i, i & 0xff)
                for i in range(count)]
        out += ['cost', 'read C000', 'cost', 'write C004 00',
                'write 2100 11', 'cost', 'read C000', 'cost',
                'write C000 00', 'cost', 'write C029 01', 'cost']
        return out

    def test_f121_barrier_and_flush(self):
        period = 133.333333 * 64 / 65
        d, points = self.deltas(self.lines(200))
        self.assertEqual(d[0], 200 * 6)     # a video write takes 6 clocks
        # the $C000 read waits until the 200th byte is out (the
        # coalescer counts a byte when it queues it for the bus)
        self.assertEqual(points[2]['posted'], 200)
        self.assertGreater(d[0] + d[1], 200 * period)
        self.assertLess(d[0] + d[1], 200 * period + 400)
        # a main HGR byte with TEXT on is deferred: the next $C000 read
        # does not flush it, an exposure write ($C000) does
        self.assertEqual(points[4]['posted'], 200)
        self.assertEqual(points[5]['posted'], 201)
        self.assertEqual(points[5]['flushes'], 1)

    def test_coalescing(self):
        lines = ['write C005 00'] + ['write 2000 %02X' % i
                                     for i in range(20)] + \
            ['read C000', 'cost']
        points = self.costs(lines)
        # the writes that come before the scanner reaches the byte are
        # coalesced, those after it into one more
        self.assertIn(points[0]['posted'], (1, 2))

    def test_sparse_column_drains_by_the_page(self):
        # one byte a screen row (160 bytes apart): about 1.6 dirty bytes a
        # page, each page scanned whole, 2 clocks a byte
        # (vtw_video_coalescer.sv:119-149); the Verilator run of the RTL
        # took 41,854 clocks for 168 rows after the writes, 54,745 with
        # them (docs/results/fuzz-timing-2026-09-30.md section 3)
        column = ['write %04X 01' % (0x2000 + 160 * r) for r in range(168)]
        dense = ['write %04X 01' % (0x2000 + i) for i in range(168)]
        period = 133.333333 * 64 / 65
        for lines, low, high in ((column, 105 * 512, 105 * 512 + 2000),
                                 (dense, 168 * period,
                                  168 * period + 1200)):
            d, points = self.deltas(['write C005 00', 'cost'] + lines +
                                    ['read C000', 'cost'])
            self.assertTrue(low <= d[0] <= high, (d[0], low, high))
            self.assertEqual(points[1]['posted'], 168)
        # coalescer 0: the write-ordered model, one byte an Apple cycle
        # whatever the page
        self.files['nocz'] = self.directory / 'nocz.txt'
        self.files['nocz'].write_text(costs.text('f121').replace(
            '\ncoalescer 1\n', '\ncoalescer 0\n'))
        self.assertIn('\ncoalescer 0\n', self.files['nocz'].read_text())
        d, points = self.deltas(['write C005 00', 'cost'] + column +
                                ['read C000', 'cost'], 'nocz')
        self.assertLess(d[0], 168 * period + 1200)
        self.assertEqual(points[1]['posted'], 168)

    def test_fastpath_lazy_shr(self):
        d, points = self.deltas(self.lines(200), 'fastpath')
        self.assertEqual(points[1]['posted'], 0)
        self.assertLess(d[1], 400)          # no barrier
        self.assertEqual(points[5]['posted'], 1)      # only the main byte
        # leaving SHR flushes the 200 lazy bytes
        self.assertEqual(points[6]['posted'], 201)
        self.assertGreater(d[5], 200 * 131)

    def test_fastpath_reconciler(self):
        lines = ['write C073 05', 'cost', 'read C000', 'cost']
        d, points = self.deltas(lines, 'fastpath')
        # the quiet bank write is replayed before the next bus cycle
        self.assertEqual(points[1]['reconcile_cycles'], 1)
        self.assertEqual(points[1]['bus_cycles'] - points[0]['bus_cycles'], 2)
        # and a pending SHR frame is flushed first (rule O4)
        lines = ['write C029 C1', 'write C005 00'] + \
            ['write %04X 01' % (0x2000 + i) for i in range(50)] + \
            ['write C004 00', 'write C073 05', 'cost', 'read C000', 'cost']
        _, points = self.deltas(lines, 'fastpath')
        self.assertEqual(points[1]['lazy_flushes'], 1)
        self.assertEqual(points[1]['posted'], 50)


def memory_api_lines(request):
    lines = ['read CFFF', 'read C700']
    lines += ['write CFF0 %02X' % b for b in request]
    return lines + ['cost', 'write CFF1 02', 'cost', 'read CFF1',
                    'read CFF0', 'write CFF2 00']


def chunk_clocks(profile, source_bram, target_bram, n=504):
    """One 504-byte chunk, aligned, from memory_api_hw.c's AXI counts."""
    p = costs.parameters(profile)
    mhz, axi = p['fabric_mhz'], p['axi_us']
    period = mhz * p['line_us'] / 65

    def clocks(reads, writes):
        return round((reads * axi + writes * p['axi_write_us']) * mhz)

    def dma(write):
        each = (p['psram_write'] if write else p['psram_read'] + 1) \
            if p['relaxed_admission'] else period
        return clocks(p['amem_dma_axi'], 3) + round(n / 8 * each) + \
            clocks(p['amem_dma_poll_axi'], 0)
    words = n // 4
    read = clocks(p['amem_read_setup_axi'] +
                  words * (p['amem_read_word_axi'] - 1), 1 + words) \
        if source_bram else dma(False)
    write = clocks(p['amem_write_setup_axi'] +
                   words * (p['amem_write_word_axi'] - 1), 2 + words) \
        if target_bram else dma(True)
    return read + write


@have_tools
class MemoryApiCost(CostWorkspace):
    def request_clocks(self, source, destination, count, profile='f121'):
        request = control([descriptor(COPY, PRIVATE, source, destination,
                                      count)])
        points = self.costs(memory_api_lines(request), profile, '--amem')
        self.assertEqual(points[1]['amem_requests'], 1)
        self.assertEqual(points[1]['amem_bytes'], count)
        return points[1]['amem_clocks']

    def test_per_chunk(self):
        for profile in ('f121', 'fastpath'):
            for source, destination, bram in (
                    ((MAIN, 0, 0x1000), (AUX, 5, 0x1000), (True, False)),
                    ((AUX, 5, 0x1000), (MAIN, 0, 0x1000), (False, True))):
                one = self.request_clocks(source, destination, 504, profile)
                two = self.request_clocks(source, destination, 1008, profile)
                expected = chunk_clocks(profile, *bram)
                self.assertLess(abs((two - one) - expected), 4,
                                (profile, bram, two - one, expected))

    def test_saving_main_costs_more_than_loading_it(self):
        save = self.request_clocks((MAIN, 0, 0x1000), (AUX, 5, 0x1000), 4032)
        load = self.request_clocks((AUX, 5, 0x1000), (MAIN, 0, 0x1000), 4032)
        self.assertGreater(save, load)      # 12 AXI accesses a word, not 6

    def test_the_hold_flushes_the_mirror(self):
        def fill(destination):
            return control([descriptor(FILL, PRIVATE, (0, 0, 0),
                                       destination, 8)])
        # deferred main bytes: 'read CFFF' is an exposure access and
        # flushes them before the request
        points = self.costs(['write 2100 01', 'write 2101 02'] +
                            memory_api_lines(fill((MAIN, 0, 0x1000))),
                            'f121', '--amem')
        self.assertEqual(points[0]['flushes'], 1)
        self.assertEqual(points[0]['posted'], 2)
        # fast path: lazy SHR bytes stay through a hold whose destination
        # is outside the SHR range (KEEP_LAZY), and go before one inside
        shr = ['write C029 C1', 'write C005 00'] + \
            ['write %04X 01' % (0x2000 + i) for i in range(100)] + \
            ['write C004 00']
        kept = self.costs(shr + memory_api_lines(fill((MAIN, 0, 0x1000))),
                          'fastpath', '--amem')
        flushed = self.costs(shr + memory_api_lines(fill((AUX, 0, 0x3000))),
                             'fastpath', '--amem')
        self.assertEqual(kept[1]['posted'], 0)
        self.assertEqual(flushed[1]['posted'], 100)
        self.assertGreater(flushed[1]['amem_clocks'] - kept[1]['amem_clocks'],
                           100 * 131)


def doom_command(build, directory, core='py65', amem=True, a2vm=None):
    """The command that runs the existing port on `a2vm` (default
    doom.A2VM, build/a2vm/a2vm; the tests pass the one they built)."""
    image = Path(directory) / 'fast.img'
    image.write_bytes(build.image())
    command = [str(a2vm or doom.A2VM), '--rom', str(doom.DEFAULT_ROM),
               '--speed', 'turbo', '--core', core] + \
        (['--amem'] if amem else [])
    return command + build.fast_arguments(image) + build.hook_arguments()


@have_tools
@needs_doom
class ExistingPort(unittest.TestCase):
    def setUp(self):
        self.out, _ = support.a2vm_build()
        self.directory = Path(tempfile.mkdtemp(dir=str(self.out)))
        self.addCleanup(shutil.rmtree, str(self.directory), True)
        self.build = doom.Build()

    def finish(self, name, extra=(), core='py65'):
        directory = self.directory / name
        directory.mkdir()
        # the a2vm built from the source (not build/a2vm/a2vm), bounded:
        # three frames take at most 3e8 cycles and a second
        command = doom_command(self.build, directory, core,
                               a2vm=self.out / 'a2vm') + list(extra) + [
            '--boundaries', '3', '--cycles', str(PORT_CYCLES * 3),
            '--snapshot-dir', str(directory), '--final-snapshot',
            '--state', str(directory / 'state.json')]
        support.run(command, timeout=600, max_bytes=64 << 20, check=True,
                    stdout=subprocess.DEVNULL)
        state = json.loads((directory / 'state.json').read_text())
        self.assertEqual((state['end'], state['boundaries']),
                         ('boundaries', 3), name)
        state.pop('host_seconds')
        return state, (directory / 'final.ram').read_bytes()

    def test_observing_changes_nothing(self):
        plain = self.finish('plain')
        for profile in costs.profiles():
            if costs.parameters(profile)['zp_pair']:
                continue            # the next test (the exact core)
            observed = self.finish(profile, self.build.cost_arguments(
                profile, self.directory))
            self.assertEqual(plain[0], observed[0], profile)
            self.assertTrue(plain[1] == observed[1], profile)

    def test_the_pair_profiles_change_nothing_here(self):
        """f121zp and fastzp arm the zero-page pair (the exact core only).
        The existing port never writes $C069, so a run is the plain run of
        the exact core, plus the pair's state, which stays all zero."""
        plain = self.finish('plain-w65', core='w65c02s')
        self.assertNotIn('zpbank', plain[0])
        idle = {'address': 0, 'rd': 0, 'wr': 0, 'enables': 0, 'loads': 0,
                'reads': 0, 'writes': 0, 'firmware': 0, 'amem': 0}
        for profile in costs.profiles():
            if not costs.parameters(profile)['zp_pair']:
                continue
            observed = self.finish(profile, self.build.cost_arguments(
                profile, self.directory), core='w65c02s')
            self.assertEqual(observed[0].pop('zpbank'), idle, profile)
            self.assertEqual(plain[0], observed[0], profile)
            self.assertTrue(plain[1] == observed[1], profile)

    def test_report(self):
        rows = {}
        for profile in costs.profiles():
            rows[profile], state = cost_report.run(
                self.build, profile, self.directory / profile, 20,
                a2vm=self.out / 'a2vm')
            again, _ = cost_report.run(self.build, profile,
                                       self.directory / (profile + '-2'), 20,
                                       a2vm=self.out / 'a2vm')
            self.assertEqual(rows[profile], again, 'not deterministic')
            self.assertEqual(state['end'], 'boundaries')
            for row in rows[profile]:
                self.assertEqual(sum(row['phases']), row['clocks'])
        f121 = cost_report.summary(rows['f121'], 133.333333)
        fast = cost_report.summary(rows['fastpath'], 133.333333)
        # MILESTONES.md 3.1 item 4: within 25% of 248 ms a frame
        self.assertLess(abs(f121['mean_ms'] / 248.0 - 1), 0.25,
                        f121['mean_ms'])
        self.assertLess(fast['mean_ms'], f121['mean_ms'])
        # the event counts against the card's own counters
        hardware = cost_report.hardware_per_frame()
        for name in ('steps', 'read_hits', 'misses', 'invalidations',
                     'video_wait', 'bus_cycles', 'posted'):
            model = f121['counters'][cost_report.MODEL_COUNTER.get(name, name)]
            self.assertLess(abs(model / hardware[name] - 1), 0.10, name)


if __name__ == '__main__':
    unittest.main()
