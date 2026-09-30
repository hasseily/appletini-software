"""Tests of tools/a2vm, milestone 6: the additions for routine tests.

  - --write-log RANGES: a line for every CPU write into the ranges, with
    the old value, so a store of the value already there is seen;
    storage ranges (main, aux banks, the card) and CPU ranges (I/O);
    with the zero-page pair, the bank a redirected write reaches;
  - --lowest-s and --lowest-s-in: the lowest S of the run and of the
    instructions inside PC ranges, in the state;
  - --snapshot-ranges: snapshots of chosen ranges only, as A2VMIMG1
    images that --image loads back;
  - input events at one PC: plain events all fire at the first visit, as
    before; pc ADDR@N fires at the Nth visit and pc ADDR@* at every one.

Each option is opt-in: without it the state has none of its fields (the
comparison with a2sim.py and every earlier test depend on that).
"""

import json
import struct
import subprocess
import unittest

import support
from test_a2vm_machine import Workspace, have_tools

W65 = ('--core', 'w65c02s', '--no-mouse')


def image_of(records):
    """An A2VMIMG1 image: (kind, bank, address, bytes) records."""
    out = bytearray(b'A2VMIMG1')
    for kind, bank, address, data in records:
        out += struct.pack('<BBHI', kind, bank, address, len(data)) + data
    return bytes(out)


def read_image(data):
    assert data[:8] == b'A2VMIMG1'
    records, at = [], 8
    while at < len(data):
        kind, bank, address, length = struct.unpack_from('<BBHI', data, at)
        at += 8
        records.append((kind, bank, address, data[at:at + length]))
        at += length
    return records


class Runs(Workspace):
    def run_program(self, code, *arguments, at=0x0800, events=None,
                    extra_code=(), records=()):
        """Run `code` at `at` (and each (address, bytes) of extra_code in
        main, and the image records `records`) on the exact core; the
        state and the process's output."""
        records = [(0, 0, at, bytes(code))] + \
            [(0, 0, a, bytes(c)) for a, c in extra_code] + list(records)
        image = self.directory / 'program.img'
        image.write_bytes(image_of(records))
        command = [str(self.out / 'a2vm'), '--rom', str(self.rom)] + \
            list(W65) + ['--image', str(image), '--reg', 'pc=%X' % at,
                         '--reg', 's=FF', '--cycles', '100000',
                         '--state', str(self.directory / 'state.json')]
        if events is not None:
            path = self.directory / 'events.txt'
            path.write_text('\n'.join(events) + '\n')
            command += ['--input', str(path)]
        result = support.run(command + [str(a) for a in arguments],
                             timeout=120, max_bytes=64 << 20,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             universal_newlines=True)
        state_path = self.directory / 'state.json'
        state = json.loads(state_path.read_text()) \
            if result.returncode != 2 else None
        return state, result


@have_tools
class WriteLog(Runs):
    PROGRAM = [0xA9, 0x11,              # 0800 lda #$11
               0x8D, 0x00, 0x40,        # 0802 sta $4000
               0x8D, 0x00, 0x40,        # 0805 sta $4000 (the same value)
               0x8D, 0x05, 0xC0,        # 0808 sta $C005: RAMWRT on
               0x8D, 0x00, 0x40,        # 080B sta $4000: aux 0
               0x8D, 0x04, 0xC0,        # 080E sta $C004
               0x8D, 0x00, 0xD0,        # 0811 sta $D000: the card
               0x20, 0x20, 0x08,        # 0814 jsr $0820
               0x80, 0xFE]              # 0817 bra *
    RTS = (0x0820, [0x60])

    def log(self, ranges, *arguments, program=None):
        path = self.directory / 'writes.log'
        state, result = self.run_program(
            program or self.PROGRAM, '--write-log', ranges,
            '--write-log-file', path, '--stop-pc', '817',
            '--switch', 'lc_read=1', '--switch', 'lc_write=1',
            *arguments, extra_code=[self.RTS])
        self.assertEqual(result.returncode, 0, result.stdout)
        lines = path.read_text().splitlines()
        self.assertTrue(lines[0].startswith('# a2vm write-log 1'))
        return state, [line.split() for line in lines if line[0] != '#']

    def test_every_write_in_the_ranges(self):
        state, rows = self.log('main:4000-40FF,aux0:4000,main:0100-01FF,'
                               'cpu:C004-C005,lc')
        self.assertEqual([row[3:] for row in rows], [
            ['0802', '4000', 'main', '0', '4000', '00', '11'],
            ['0805', '4000', 'main', '0', '4000', '11', '11'],
            ['0808', 'C005', 'io', '-', '-', '-', '11'],
            ['080B', '4000', 'aux', '0', '4000', '00', '11'],
            ['080E', 'C004', 'io', '-', '-', '-', '11'],
            ['0811', 'D000', 'lc', '0', 'D000', '00', '11'],
            ['0814', '01FF', 'main', '0', '01FF', '00', '08'],
            ['0814', '01FE', 'main', '0', '01FE', '00', '16']])
        self.assertEqual(state['write_logged'], 8)
        clocks = [int(row[1]) for row in rows]
        self.assertEqual(clocks, sorted(clocks))
        self.assertEqual([int(row[1]) for row in rows],
                         [int(row[2]) for row in rows])     # no cost model
        self.assertTrue(all(row[0] == 'w' for row in rows))

    def test_the_log_limit_halts_the_run(self):
        """--write-log-limit N: N lines, then the write that would be
        line N + 1 halts the run (a log that fails rather than grows)."""
        path = self.directory / 'writes.log'
        state, result = self.run_program(
            self.PROGRAM, '--write-log', 'main:4000-40FF,cpu:C004-C005',
            '--write-log-file', path, '--write-log-limit', 2,
            '--stop-pc', '817', extra_code=[self.RTS])
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(state['end'], 'halt')
        self.assertIn('--write-log-limit', state['halt'])
        rows = [line for line in path.read_text().splitlines()
                if line[0] != '#']
        self.assertEqual(len(rows), 2)
        self.assertEqual(state['write_logged'], 2)
        # the third write in the ranges ($C005 at $0808) is where it halts
        self.assertEqual(state['pc'], 0x080B)

    def test_the_ranges_filter(self):
        _, rows = self.log('aux0')
        self.assertEqual([row[5:8] for row in rows], [['aux', '0', '4000']])
        _, rows = self.log('main:4001-40FF,aux1-127,lc1')
        self.assertEqual(rows, [])

    def test_a_redirected_write_names_its_bank(self):
        program = [0xA9, 0x06, 0x8D, 0x69, 0xC0,    # lda #6 / sta $C069
                   0xA9, 0x05, 0x85, 0x07,          # lda #5 / sta $07
                   0xA9, 0x22, 0x8D, 0x00, 0x40,    # lda #$22 / sta $4000
                   0x80, 0xFE]
        _, rows = self.log('aux1-127,main:0000-00FF', '--zpbank',
                           program=program + [0] * 9)
        self.assertEqual([row[3:] for row in rows], [
            ['0807', '0007', 'main', '0', '0007', '00', '05'],
            ['080B', '4000', 'aux', '5', '4000', '00', '22']])

    def test_off_by_default(self):
        state, result = self.run_program(self.PROGRAM, '--stop-pc', '817',
                                         extra_code=[self.RTS])
        self.assertEqual(result.returncode, 0, result.stdout)
        for key in ('write_logged', 'lowest_s', 'zpbank'):
            self.assertNotIn(key, state)

    def test_bad_ranges(self):
        for ranges, message in (('aux200', 'aux banks'),
                                ('lc:0000-0100', 'outside'),
                                ('main:4000-3000', 'empty'),
                                ('main:40G0', 'hex'), ('video', 'a range is'),
                                ('', 'no range')):
            _, result = self.run_program(self.PROGRAM, '--write-log', ranges,
                                         '--write-log-file',
                                         self.directory / 'w.log')
            self.assertEqual(result.returncode, 2, ranges)
            self.assertIn(message, result.stdout, ranges)
        # a snapshot holds storage, not the CPU's view
        _, result = self.run_program(self.PROGRAM, '--snapshot-ranges',
                                     'cpu:0000-FFFF', '--snapshot-dir',
                                     self.directory)
        self.assertEqual(result.returncode, 2)


@have_tools
class LowestS(Runs):
    PROGRAM = [0x20, 0x10, 0x08,        # 0800 jsr $0810
               0x80, 0xFE]              # 0803 bra *
    SUB = (0x0810, [0x48,               # 0810 pha
                    0x20, 0x20, 0x08,   # 0811 jsr $0820
                    0x68,               # 0814 pla
                    0x60])              # 0815 rts
    INNER = (0x0820, [0x48, 0x48, 0x68, 0x68, 0x60])

    def test_overall_and_in_ranges(self):
        state, result = self.run_program(
            self.PROGRAM, '--lowest-s-in', '0810-0815,0820-0824,0900-09FF',
            '--stop-pc', '803', extra_code=[self.SUB, self.INNER])
        self.assertEqual(result.returncode, 0, result.stdout)
        low = state['lowest_s']
        self.assertEqual((low['s'], low['pc']), (0xf8, 0x0821))
        self.assertEqual(low['steps'], 10)
        ranges = [(r['low'], r['high'], r['s'], r['steps'])
                  for r in low['ranges']]
        self.assertEqual(ranges, [(0x0810, 0x0815, 0xfa, 4),
                                  (0x0820, 0x0824, 0xf8, 5),
                                  (0x0900, 0x09ff, None, 0)])

    def test_the_whole_run_only(self):
        state, _ = self.run_program(self.PROGRAM, '--lowest-s', '--stop-pc',
                                    '803', extra_code=[self.SUB, self.INNER])
        self.assertEqual(state['lowest_s']['s'], 0xf8)
        self.assertEqual(state['lowest_s']['ranges'], [])

    def test_an_interrupt_counts_where_it_lands(self):
        """The entry's pushes count for the range of the interrupted PC:
        BRK at $0810, its vector in the card to an RTI at $0900."""
        state, result = self.run_program(
            self.PROGRAM, '--lowest-s-in', '0810-0811', '--stop-pc', '803',
            '--switch', 'lc_read=1',
            extra_code=[(0x0810, [0x00, 0x00, 0x60]), (0x0900, [0x40])],
            records=[(2, 0, 0xfffe, bytes([0x00, 0x09]))])
        self.assertEqual(result.returncode, 0, result.stdout)
        # JSR: $FD; BRK pushes three more: $FA
        self.assertEqual(state['lowest_s']['ranges'][0]['s'], 0xfa)
        self.assertEqual(state['lowest_s']['s'], 0xfa)
        self.assertEqual(state['pc'], 0x0803)


@have_tools
class RangeSnapshots(Runs):
    PROGRAM = [0xA9, 0x42, 0x8D, 0x00, 0x40,    # lda #$42 / sta $4000
               0x8D, 0x05, 0xC0,                # sta $C005
               0x8D, 0x00, 0x20,                # sta $2000 (aux 0)
               0x80, 0xFE]

    def test_ranges_only_and_loadable(self):
        ranges = ('main:4000-4003,aux0:2000-2001,aux3-4:1000,lc:FFFE-FFFF,'
                  'lc1:D000')
        state, result = self.run_program(
            self.PROGRAM, '--snapshot-dir', self.directory,
            '--final-snapshot', '--snapshot-ranges', ranges, '--stop-pc',
            '80B')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse((self.directory / 'final.ram').exists())
        final = json.loads((self.directory / 'final.json').read_text())
        self.assertEqual(final['pc'], 0x080b)
        records = read_image((self.directory / 'final.img').read_bytes())
        self.assertEqual(records, [
            (0, 0, 0x4000, bytes([0x42, 0, 0, 0])),
            (1, 0, 0x2000, bytes([0x42, 0])),
            (1, 3, 0x1000, bytes([0])), (1, 4, 0x1000, bytes([0])),
            (2, 0, 0xfffe, bytes([0, 0])), (3, 0, 0xd000, bytes([0]))])
        # --image takes it back
        script = self.directory / 'bus.txt'
        script.write_text('peek main 0 4000\npeek aux 0 2000\n')
        output = support.run(
            [str(self.out / 'a2vm'), '--rom', str(self.rom), '--image',
             str(self.directory / 'final.img'), '--bus-script', str(script)],
            timeout=120, max_bytes=64 << 20,
            stdout=subprocess.PIPE, universal_newlines=True).stdout
        self.assertEqual(self.peeks(output.splitlines()), [0x42, 0x42])

    def test_event_snapshots_too(self):
        _, result = self.run_program(
            self.PROGRAM, '--snapshot-dir', self.directory,
            '--snapshot-ranges', 'main:0800-080F', '--stop-pc', '80B',
            events=['pc 805 snapshot early'])
        self.assertEqual(result.returncode, 0, result.stdout)
        records = read_image((self.directory / 'early.img').read_bytes())
        self.assertEqual(records, [(0, 0, 0x0800,
                                    bytes(self.PROGRAM) + bytes(3))])
        self.assertFalse((self.directory / 'early.ram').exists())


@have_tools
class Events(Runs):
    # X counts 0, 1, 2, 3 at the four visits of $0802
    LOOP = [0xA2, 0x00,             # 0800 ldx #0
            0xE8,                   # 0802 inx
            0xE0, 0x04,             # 0803 cpx #4
            0xD0, 0xFB,             # 0805 bne $0802
            0x80, 0xFE]             # 0807 bra *

    def snapshot_x(self, name):
        return json.loads((self.directory / (name + '.json')).read_text())['x']

    def test_visits(self):
        _, result = self.run_program(
            self.LOOP, '--snapshot-dir', self.directory, '--snapshot-ranges',
            'main:0000-00FF', events=[
                'pc 802 snapshot first', 'pc 802 snapshot also-first',
                'pc 802@3 snapshot third', 'pc 802@* snapshot every',
                'pc 802@9 snapshot never', 'pc 807 stop'])
        self.assertEqual(result.returncode, 0, result.stdout)
        # two plain events at one PC both fire at its first visit, as
        # before; @N at the Nth; @* at each, named NAME-VISIT
        self.assertEqual(self.snapshot_x('first'), 0)
        self.assertEqual(self.snapshot_x('also-first'), 0)
        self.assertEqual(self.snapshot_x('third'), 2)
        self.assertEqual([self.snapshot_x('every-%04d' % n)
                          for n in range(1, 5)], [0, 1, 2, 3])
        self.assertFalse((self.directory / 'every-0005.json').exists())
        self.assertFalse((self.directory / 'never.json').exists())
        state = json.loads((self.directory / 'state.json').read_text())
        self.assertEqual((state['end'], state['pc']), ('stop', 0x0807))

    def test_main_only_visits(self):
        _, result = self.run_program(
            self.LOOP, '--snapshot-dir', self.directory, '--snapshot-ranges',
            'main:0000-00FF', events=['pc 802:main@2 snapshot second',
                                      'pc 807 stop'])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.snapshot_x('second'), 1)

    def test_every_limit_bounds_the_snapshots(self):
        """--every-limit N: an @* event takes at most N snapshots; the
        visit after them ends the run with an error."""
        _, result = self.run_program(
            self.LOOP, '--snapshot-dir', self.directory, '--snapshot-ranges',
            'main:0000-00FF', '--every-limit', 2,
            events=['pc 802@* snapshot every', 'pc 807 stop'])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('past --every-limit 2', result.stdout)
        self.assertEqual([self.snapshot_x('every-%04d' % n)
                          for n in (1, 2)], [0, 1])
        self.assertFalse((self.directory / 'every-0003.json').exists())
        # an @* event of another action is not counted
        _, result = self.run_program(
            self.LOOP, '--every-limit', 1,
            events=['pc 802@* oa 1', 'pc 807 stop'])
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_cycles_none(self):
        """--cycles none: no limit (without --cycles a2vm stops at 2e10
        cycles, end "cycle-cap", status 3; too long a run for a test)."""
        state, result = self.run_program(
            self.LOOP, '--cycles', 'none', events=['pc 807 stop'])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(state['end'], 'stop')

    def test_visit_zero_is_refused(self):
        _, result = self.run_program(self.LOOP, events=['pc 802@0 stop'])
        self.assertEqual(result.returncode, 2)
        self.assertIn('counts visits from 1', result.stdout)


if __name__ == '__main__':
    unittest.main()
