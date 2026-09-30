"""Tests of tools/a2vm, milestone 6: the zero-page bank pair.

The pair is the firmware design's (docs/firmware/zpbank-spec.md as
corrected by zpbank-review.md; NATIVE.md 4.5 and 15.1: main zero page
only). a2vm arms it with --zpbank or the cost profiles f121zp and fastzp.

  - the $C069 enable, the watch of main zero-page writes, the values
    that select a bank and those that follow the switches, the scope of
    the redirect ($0200-$BFFF, data accesses only) and its priority over
    RAMRD, RAMWRT, 80STORE and PAGE2, the reset rules;
  - the review's cases: an aux zero-page write does not load the pair,
    $FF disables it, 127 (and 128-255) follow the switches;
  - programs on the exact core: the detection probe of the spec, every
    opcode's accesses against the core's data_ea table (the table of
    tools/a2vm/selftest.c, read from that file), the same-page STA a,X
    false read, JMP (a) and BRK with the pair set, a read-modify-write
    with zp_rd and zp_wr apart;
  - the cost: a redirected access is a RamWorks line access, no TURBO
    cache is invalidated or used, the $C069 write is one bus cycle, and
    F1.2.1's one line thrashes on a two-bank copy where fastzp's 16 do
    not;
  - with the pair off, nothing changes (tests/test_a2vm_cost.py runs the
    existing port under every profile, the pair's included).
"""

import json
import re
import subprocess
import unittest

import support
from a2vm import costs
from test_a2vm_cost import CostWorkspace, parse_cost
from test_a2vm_machine import Workspace, have_tools

W65 = ('--core', 'w65c02s', '--no-mouse')
PAIR = W65 + ('--zpbank',)


def zpbank(line):
    """The fields of a `zpbank` line of a bus script."""
    fields = dict(item.split('=') for item in line.split()[1:])
    return {key: int(value, 16) if key in ('address', 'rd', 'wr')
            else int(value) for key, value in fields.items()}


def pokes(address, code, storage='main', bank=0):
    return ['poke %s %d %04X %02X' % (storage, bank, address + i, b)
            for i, b in enumerate(code)]


def selftest_tables():
    """ea_class and ea_mode of tools/a2vm/selftest.c: the core's data_ea
    classification of every opcode (taken from w65c02_core.sv)."""
    text = (support.ROOT / 'tools' / 'a2vm' / 'selftest.c').read_text()
    tables = {}
    for name in ('ea_class', 'ea_mode'):
        body = re.search(r'static const char %s\[\] =(.*?);' % name, text,
                         re.S).group(1)
        tables[name] = ''.join(re.findall(r'"([^"]*)"', body))
        assert len(tables[name]) == 256
    return tables['ea_class'], tables['ea_mode']


@have_tools
class Enable(Workspace):
    def pair(self, lines, *arguments):
        output = self.bus(lines + ['zpbank'], *(arguments or PAIR))
        return [zpbank(line) for line in output if line.startswith('zpbank')]

    def test_c069_values(self):
        states = self.pair([
            'zpbank', 'write C069 06', 'zpbank', 'write 0006 05',
            'write 0007 09', 'zpbank',
            # every $C069 write clears both registers
            'write C069 06', 'zpbank', 'write 0006 05', 'write C069 20',
            'zpbank',
            # $00 and $FF turn the pair off (review finding 9)
            'write C069 00', 'zpbank', 'write C069 FF', 'zpbank',
            'write 00FF 05', 'write 0000 05', 'zpbank',
            'write C069 FE', 'write 00FE 07', 'write 00FF 08'])
        self.assertEqual([(s['address'], s['rd'], s['wr']) for s in states],
                         [(0, 0, 0), (6, 0, 0), (6, 5, 9), (6, 0, 0),
                          (0x20, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
                          (0xfe, 7, 8)])
        self.assertEqual(states[-1]['enables'], 6)

    def test_c069_reads_are_unchanged(self):
        lines = ['write C069 06', 'read C069', 'write 0006 05', 'read C069']
        armed = self.reads(self.bus(lines, *PAIR))
        plain = self.reads(self.bus(lines, *W65))
        self.assertEqual(armed, plain)

    def test_disarmed_is_f121(self):
        states = self.pair(['write C069 06', 'write 0006 05'], *W65)
        self.assertEqual((states[0]['armed'], states[0]['address'],
                          states[0]['rd']), (0, 0, 0))
        # nor does a disarmed machine redirect
        output = self.bus(['write C069 06', 'write 0006 05',
                           'poke aux 5 4000 AA', 'poke main 0 4000 11',
                           'read-ea 4000'], *W65)
        self.assertEqual(self.reads(output), [0x11])

    def test_values_that_select_and_follow(self):
        states = self.pair(['write C069 06'] + sum(
            (['write 0006 %02X' % v, 'zpbank'] for v in
             (1, 0x42, 126, 127, 128, 0xc5, 255, 0)), []))
        self.assertEqual([s['rd'] for s in states[:-1]],
                         [1, 0x42, 126, 0, 0, 0, 0, 0])

    def test_only_main_zero_page_loads_it(self):
        """Review finding 2 (D4 corrected): a write to aux zero page, ALTZP
        on, whatever the RamWorks bank, does not load the pair."""
        states = self.pair([
            'write C069 06', 'write 0006 05', 'zpbank',
            'write C009 00', 'write 0006 09', 'write 0007 09', 'zpbank',
            'write C073 03', 'write 0006 0A', 'zpbank',
            'write C073 00', 'write C008 00', 'write 0007 0B', 'zpbank',
            # a poke is not a CPU write
            'poke main 0 0006 0C', 'zpbank'])
        self.assertEqual([(s['rd'], s['wr']) for s in states[:-1]],
                         [(5, 0), (5, 0), (5, 0), (5, 11), (5, 11)])

    def test_c073_leaves_the_pair_alone(self):
        states = self.pair(['write C069 06', 'write 0006 05', 'write C073 09',
                            'write C071 22', 'zpbank'])
        self.assertEqual((states[0]['address'], states[0]['rd']), (6, 5))

    def test_reset_and_disarm(self):
        states = self.pair(['write C069 06', 'write 0006 05', 'reset',
                            'zpbank', 'write C069 06', 'write 0007 05',
                            'zpbank-arm 0', 'zpbank', 'zpbank-arm 1',
                            'write 0007 05'])
        self.assertEqual([(s['armed'], s['address'], s['wr'])
                          for s in states],
                         [(1, 0, 0), (0, 0, 0), (1, 0, 0)])

    def test_arming_needs_the_exact_core_and_8_mb(self):
        script = self.directory / 'nothing.txt'
        script.write_text('zpbank\n')
        for arguments, message in (
                ((), 'needs the exact core'),
                (('--core', 'w65c02s', '--banks', '64'), 'RamWorks banks')):
            result = support.run(
                [str(self.out / 'a2vm'), '--rom', str(self.rom), '--zpbank',
                 '--bus-script', str(script)] + list(arguments),
                timeout=120, max_bytes=64 << 20, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, universal_newlines=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn(message, result.stdout)


@have_tools
class Redirect(Workspace):
    def test_reads_and_writes_by_direction(self):
        lines = ['write C069 06', 'poke main 0 4000 11', 'poke aux 5 4000 55',
                 'poke aux 9 4000 99', 'write 0006 05', 'read-ea 4000',
                 'write-ea 4001 A1', 'peek main 0 4001', 'write 0007 09',
                 'read-ea 4000', 'write-ea 4001 A2', 'peek aux 9 4001',
                 'peek main 0 4001', 'peek aux 5 4001',
                 # the plain bus verbs are not effective-address accesses
                 'read 4000', 'write 4002 A3', 'peek main 0 4002',
                 'peek aux 9 4002', 'zpbank']
        output = self.bus(lines, *PAIR)
        self.assertEqual(self.reads(output), [0x55, 0x55, 0x11])
        self.assertEqual(self.peeks(output), [0xa1, 0xa2, 0xa1, 0, 0xa3, 0])
        state = zpbank(output[-1])
        self.assertEqual((state['reads'], state['writes'], state['loads']),
                         (2, 1, 2))

    def test_scope(self):
        """$0200-$BFFF only: never zero page, the stack, I/O or the card."""
        lines = ['write C069 06', 'write 0006 05', 'write 0007 05',
                 'poke aux 5 0200 22', 'poke aux 5 BFFF 33',
                 'poke aux 5 01FF 44', 'poke main 0 01FF 45',
                 'poke aux 5 0080 46', 'poke main 0 0080 47',
                 'read C083', 'read C083', 'poke lc 0 D000 48',
                 'poke aux 5 D000 49',
                 'read-ea 0200', 'read-ea BFFF', 'read-ea 01FF',
                 'read-ea 0080', 'read-ea D000',
                 'write-ea 01FE 50', 'write-ea C000 00', 'write-ea D001 51',
                 'peek main 0 01FE', 'peek lc 0 D001', 'peek aux 5 01FE',
                 'peek aux 5 D001']
        output = self.bus(lines, *PAIR)
        self.assertEqual(self.reads(output)[-5:], [0x22, 0x33, 0x45, 0x47,
                                                   0x48])
        self.assertEqual(self.peeks(output), [0x50, 0x51, 0, 0])

    def test_beats_ramrd_ramwrt_80store_and_page2(self):
        lines = ['write C069 06', 'write C073 03', 'write C003 00',
                 'write C005 00', 'write C001 00', 'write C055 00',
                 'write C057 00',
                 'poke aux 3 0400 03', 'poke aux 7 0400 07',
                 'poke aux 3 2000 13', 'poke aux 7 2000 17',
                 'poke aux 3 4000 23', 'poke aux 7 4000 27',
                 'read-ea 0400', 'read-ea 2000', 'read-ea 4000',
                 'write 0006 07', 'write 0007 07',
                 'read-ea 0400', 'read-ea 2000', 'read-ea 4000',
                 'write-ea 0401 A0', 'write-ea 2001 A1', 'write-ea 4001 A2',
                 'peek aux 7 0401', 'peek aux 7 2001', 'peek aux 7 4001',
                 'peek aux 3 0401', 'peek aux 3 2001', 'peek aux 3 4001',
                 # a zero direction follows the switches again
                 'write 0006 00', 'read-ea 0400']
        output = self.bus(lines, *PAIR)
        self.assertEqual(self.reads(output),
                         [3, 0x13, 0x23, 7, 0x17, 0x27, 3])
        self.assertEqual(self.peeks(output), [0xa0, 0xa1, 0xa2, 0, 0, 0])

    def test_redirected_writes_are_not_video_writes(self):
        """A redirected write to $2000 under RAMWRT reaches a PSRAM bank:
        not posted, not counted (spec 3.1, core_top:565-569)."""
        lines = ['write C069 06', 'write C005 00', 'write-ea 2000 01',
                 'counts', 'write 0007 05', 'write-ea 2001 02', 'counts',
                 'peek aux 5 2001', 'peek aux 0 2001']
        output = self.bus(lines, *PAIR)
        counts = [[int(x) for x in line.split()[2:4]] for line in output
                  if line.startswith('counts')]      # video, SHR writes
        self.assertEqual(counts, [[1, 1], [1, 1]])
        self.assertEqual(self.peeks(output), [2, 0])


def cpu_lines(code, at=0x0800, registers='', steps=1):
    """Poke `code` at `at` and run `steps` instructions from it."""
    return pokes(at, code) + ['reg pc=%X' % at] + \
        ['reg %s' % r for r in registers.split()] + ['run %d' % steps]


@have_tools
class Programs(Workspace):
    """Programs on the exact core with the pair armed."""

    def test_detection_probe(self):
        """zpbank-spec.md section 7, run as written (PROBE = $4000); the
        result goes to $80: 1 present, 0 absent."""
        probe = [0x78,                          # sei
                 0xA9, 0x06, 0x8D, 0x69, 0xC0,  # lda #6 / sta $C069
                 0x64, 0x06, 0x64, 0x07,        # stz $06 / stz $07
                 0xA9, 0xA5, 0x8D, 0x00, 0x40,  # lda #$A5 / sta PROBE
                 0xA9, 0x01, 0x85, 0x07,        # lda #1 / sta $07
                 0xA9, 0x5A, 0x8D, 0x00, 0x40,  # lda #$5A / sta PROBE
                 0x64, 0x07,                    # stz $07
                 0xA9, 0x01, 0x85, 0x06,        # lda #1 / sta $06
                 0xAE, 0x00, 0x40,              # ldx PROBE
                 0x64, 0x06,                    # stz $06
                 0xAD, 0x00, 0x40,              # lda PROBE
                 0x64, 0x80,                    # stz $80
                 0xC9, 0xA5, 0xD0, 0x08,        # cmp #$A5 / bne absent
                 0xE0, 0x5A, 0xD0, 0x04,        # cpx #$5A / bne absent
                 0xA9, 0x01, 0x85, 0x80,        # lda #1 / sta $80
                 0xA9, 0x00, 0x8D, 0x69, 0xC0,  # absent: lda #0 / sta $C069
                 0x80, 0xFE]                    # bra *
        lines = cpu_lines(probe, steps=40) + ['peek main 0 0080',
                                              'peek aux 1 4000']
        present = self.peeks(self.bus(lines, *PAIR))
        absent = self.peeks(self.bus(lines, *W65))
        self.assertEqual(present, [1, 0x5a])
        self.assertEqual(absent, [0, 0])

    def test_every_opcode(self):
        """Each opcode that addresses memory in $0200-$BFFF, once with the
        pair at rd = 5 and wr = 9: its data_ea reads come from bank 5, its
        writes go to bank 9, main is never touched, and nothing else is
        redirected (the pair's counters)."""
        self.every_opcode(decimal=False)

    def test_every_opcode_in_decimal_mode(self):
        """The same with D set: ADC and SBC on memory make their decimal
        cycle (ST_DECIMAL_EXTRA), a second EA read at the effective
        address, redirected too; every other opcode is as in binary
        mode."""
        self.every_opcode(decimal=True)

    def test_decimal_immediate_extra_cycle_is_not_redirected(self):
        """Decimal ADC # and SBC # read $007F and $0000 in their extra
        cycle, EA cycles in zero page, which the pair never redirects."""
        for op in (0x69, 0xE9):
            output = self.bus(['write C069 06', 'write 0006 05',
                               'write 0007 09'] +
                              cpu_lines([op, 0x10], registers='a=10 p=38') +
                              ['zpbank', 'state'], *PAIR)
            state = zpbank([line for line in output
                            if line.startswith('zpbank')][0])
            self.assertEqual((state['reads'], state['writes']), (0, 0),
                             hex(op))
            # the add was decimal: $10 + $10 = $20 (SBC: $10 - $10 - 1)
            self.assertEqual(self.state(output)['a'],
                             0x20 if op == 0x69 else 0x99, hex(op))

    def every_opcode(self, decimal):
        ea_class, ea_mode = selftest_tables()
        # X = 1, Y = 2; operand $10 $40; ($10) = $4130, ($11) = $5041
        ea_of = {'a': 0x4010, 'X': 0x4011, 'Y': 0x4012, 'i': 0x5041,
                 'j': 0x4132, 'p': 0x4130}
        cases = [op for op in range(256) if ea_mode[op] in ea_of]
        self.assertEqual(len(cases), 74)
        lines = ['write C069 06', 'write 0006 05', 'write 0007 09',
                 'poke main 0 0010 30', 'poke main 0 0011 41',
                 'poke main 0 0012 50']
        for op in cases:
            ea = ea_of[ea_mode[op]]
            lines += ['poke main 0 %04X 11' % ea, 'poke aux 5 %04X 55' % ea,
                      'poke aux 9 %04X 99' % ea]
            lines += cpu_lines([op, 0x10, 0x40], registers='x=1 y=2 a=C3 p=%s'
                               % ('38' if decimal else '30'))
            lines += ['zpbank', 'peek main 0 %04X' % ea,
                      'peek aux 5 %04X' % ea, 'peek aux 9 %04X' % ea,
                      'poke main 0 %04X 00' % ea, 'poke aux 5 %04X 00' % ea,
                      'poke aux 9 %04X 00' % ea]
        output = self.bus(lines, *PAIR)
        states = [zpbank(line) for line in output if line.startswith('zpbank')]
        peeks = self.peeks(output)
        reads = writes = 0
        for n, op in enumerate(cases):
            c = ea_class[op]
            reads += {'R': 1, 'A': 2 if decimal else 1, 'M': 2, 'W': 0}[c]
            writes += c in 'WM'
            name = 'opcode %02X (%s)%s' % (op, c, ' D=1' if decimal else '')
            self.assertEqual((states[n]['reads'], states[n]['writes']),
                             (reads, writes), name)
            main, bank5, bank9 = peeks[3 * n:3 * n + 3]
            self.assertEqual((main, bank5), (0x11, 0x55), name)
            if c == 'R' or c == 'A':
                self.assertEqual(bank9, 0x99, name)
            elif c == 'W':
                # STA, STX, STY store $C3, 1, 2; STZ zero
                self.assertIn(bank9, (0xc3, 0x01, 0x02, 0x00), name)
            else:
                self.assertNotEqual(bank9, 0x99, name)

    def test_loads_read_the_bank(self):
        for op, register in ((0xAD, 'a'), (0xAE, 'x'), (0xAC, 'y'),
                             (0xB2, 'a')):
            output = self.bus(
                ['write C069 06', 'write 0006 05', 'poke aux 5 4010 5A',
                 'poke main 0 4010 11', 'poke main 0 0010 10',
                 'poke main 0 0011 40'] +
                cpu_lines([op, 0x10, 0x40]) + ['state'], *PAIR)
            self.assertEqual(self.state(output)[register], 0x5a, hex(op))

    def test_read_modify_write_across_banks(self):
        output = self.bus(['write C069 06', 'write 0006 05', 'write 0007 09',
                           'poke aux 5 4000 41', 'poke aux 9 4000 00',
                           'poke main 0 4000 77'] +
                          cpu_lines([0xEE, 0x00, 0x40]) +     # inc $4000
                          ['peek aux 9 4000', 'peek aux 5 4000',
                           'peek main 0 4000'], *PAIR)
        self.assertEqual(self.peeks(output), [0x42, 0x41, 0x77])

    def test_same_page_sta_false_read_is_not_redirected(self):
        """STA a,X on the same page reads its target first (ST_INDEX_DUMMY),
        a cycle review finding 8 leaves on the switches' mapping."""
        output = self.bus(['write C069 06', 'write 0006 05', 'write 0007 05'] +
                          cpu_lines([0x9D, 0x00, 0x40], registers='x=1 a=33') +
                          ['zpbank', 'peek aux 5 4001'], *PAIR)
        state = zpbank(output[-2])
        self.assertEqual((state['reads'], state['writes']), (0, 1))
        self.assertEqual(self.peeks(output), [0x33])

    def test_jmp_indirect_pointer_is_code_space(self):
        """D1: JMP (a) and JMP (a,X) take their pointer from main."""
        for code, registers in (([0x6C, 0x00, 0x40], ''),
                                ([0x7C, 0xFF, 0x3F], 'x=1')):
            output = self.bus(['write C069 06', 'write 0006 05',
                               'poke main 0 4000 34', 'poke main 0 4001 12',
                               'poke aux 5 4000 78', 'poke aux 5 4001 56'] +
                              cpu_lines(code, registers=registers) +
                              ['state', 'zpbank'], *PAIR)
            self.assertEqual(self.state(output[:-1])['pc'], 0x1234)
            self.assertEqual(zpbank(output[-1])['reads'], 0)

    def test_brk_with_the_pair_set(self):
        """The stack and the vector are never redirected; the handler's
        code runs from main (here the card) and its data reads are."""
        handler = [0xAD, 0x00, 0x40]            # lda $4000
        lines = ['read C083', 'read C083'] + \
            pokes(0xfffe, [0x00, 0xE0], 'lc') + pokes(0xE000, handler, 'lc') + \
            ['write C069 06', 'write 0006 05', 'write 0007 05',
             'poke aux 5 4000 5A', 'poke aux 5 01FF 99',
             'poke aux 5 FFFE 00', 'poke aux 5 FFFF 90'] + \
            cpu_lines([0x00, 0x00], registers='s=FF', steps=2) + \
            ['peek main 0 01FF', 'peek main 0 01FE', 'state']
        output = self.bus(lines, '--switch', 'lc_read=1', '--switch',
                          'lc_write=1', *PAIR)
        state = self.state(output)
        self.assertEqual((state['pc'], state['a']), (0xE003, 0x5a))
        self.assertEqual(self.peeks(output), [0x08, 0x02])


@have_tools
class PairCost(CostWorkspace):
    def pair_costs(self, lines, profile='f121zp'):
        return self.deltas(lines, profile, '--core', 'w65c02s')

    def test_the_profiles(self):
        for name in ('f121zp', 'fastzp'):
            p = costs.parameters(name)
            self.assertEqual((p['zp_pair'], p['read_bank']), (1, 0), name)
        base = {'f121zp': 'f121', 'fastzp': 'fastpath'}
        for name, other in base.items():
            p, q = costs.parameters(name), costs.parameters(other)
            differ = sorted(k for k in p if p[k] != q[k])
            self.assertEqual(differ, ['read_bank', 'zp_pair']
                             if other == 'fastpath' else ['zp_pair'], name)

    def test_a_profile_without_the_pair_refuses_zpbank(self):
        script = self.directory / 'nothing.txt'
        script.write_text('zpbank\n')
        result = support.run(
            [str(self.out / 'a2vm'), '--rom', str(self.rom), '--core',
             'w65c02s', '--zpbank', '--cost', str(self.files['f121']),
             '--bus-script', str(script)], timeout=120, max_bytes=64 << 20,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('no zero-page pair', result.stdout)
        # the pair profiles arm it themselves
        output = self.bus(['zpbank'], '--core', 'w65c02s', '--cost',
                          str(self.files['fastzp']))
        self.assertEqual(zpbank(output[0])['armed'], 1)

    def test_a_redirected_access_is_a_ramworks_line_access(self):
        lines = ['write C069 06', 'write 0006 05', 'write 0007 05', 'cost',
                 'read-ea 4000', 'cost', 'read-ea 4001', 'cost',
                 'write-ea 4002 01', 'cost', 'read 1000', 'cost']
        for profile in ('f121zp', 'fastzp'):
            d, points = self.pair_costs(lines, profile)
            self.assertEqual(points[1]['rw_misses'] - points[0]['rw_misses'],
                             1, profile)
            self.assertEqual(d[1], 5, profile)      # a line hit: 5 clocks
            self.assertEqual(d[2], 5, profile)
            self.assertEqual(points[3]['rw_hits'] - points[0]['rw_hits'], 2)
            self.assertEqual(points[3]['read_hits'], 0)

    def test_no_invalidation_and_main_entries_are_not_used(self):
        """Warm main $4000 (a read word and a write page), then redirect:
        the redirected accesses are RamWorks accesses and main keeps its
        entries (spec section 6: the veto; no invalidation)."""
        # (main $6000: not a video page, so its writes take page entries)
        lines = ['read 6000', 'write 6000 11', 'read 6000', 'cost',
                 'write C069 06', 'write 0006 05', 'write 0007 05', 'cost',
                 'read-ea 6000', 'write-ea 6000 22', 'cost',
                 'write 0006 00', 'write 0007 00', 'cost',
                 'read-ea 6000', 'cost', 'write-ea 6000 33', 'cost',
                 'peek main 0 6000', 'peek aux 5 6000']
        for profile in ('f121zp', 'fastzp'):
            output = self.bus(lines, '--no-mouse', '--core', 'w65c02s',
                              '--cost', str(self.files[profile]))
            points = [parse_cost(line) for line in output
                      if line.startswith('cost ')]
            self.assertEqual(points[-1]['invalidations'],
                             points[0]['invalidations'], profile)
            self.assertEqual(points[2]['rw_hits'] + points[2]['rw_misses'] -
                             points[1]['rw_hits'] - points[1]['rw_misses'], 2)
            # main's word and page entries survived: 2-clock hits
            self.assertEqual(points[4]['t'] - points[3]['t'], 2, profile)
            self.assertEqual(points[5]['t'] - points[4]['t'], 2, profile)
            self.assertEqual(self.peeks(output), [0x33, 0x22])

    def test_c069_is_a_bus_cycle(self):
        for profile, bus in (('f121zp', 1), ('fastzp', 1), ('fastpath', 0)):
            core = ('--core', 'w65c02s')
            d, points = self.deltas(['cost', 'write C069 06', 'cost'],
                                    profile, *core)
            self.assertEqual(points[1]['bus_cycles'] - points[0]['bus_cycles'],
                             bus, profile)
            if bus:
                self.assertTrue(122 <= d[0] <= 253, (profile, d[0]))
            self.assertEqual(points[1]['invalidations'], 0, profile)

    def test_two_bank_copy_thrashes_one_line_not_sixteen(self):
        lines = ['write C069 06', 'write 0006 05', 'write 0007 06']
        for i in range(8):
            lines += ['read-ea %04X' % (0x4000 + i),
                      'write-ea %04X 01' % (0x5000 + i)]
        lines += ['cost']
        f121 = self.costs(lines, 'f121zp', '--core', 'w65c02s')[-1]
        fast = self.costs(lines, 'fastzp', '--core', 'w65c02s')[-1]
        self.assertEqual(f121['rw_misses'], 16)     # every access
        self.assertEqual(f121['rw_dirty'], 7)
        self.assertEqual(fast['rw_misses'], 2)      # one line each
        self.assertEqual(fast['rw_dirty'], 0)

    def test_redirected_writes_are_not_posted(self):
        lines = ['write C029 C1', 'write C005 00', 'write C069 06',
                 'write 0007 05', 'cost'] + \
            ['write-ea %04X 01' % (0x2000 + i) for i in range(10)] + \
            ['cost', 'write 0007 00', 'write-ea 2000 01', 'cost']
        for profile in ('f121zp', 'fastzp'):
            points = self.costs(lines, profile, '--core', 'w65c02s')
            self.assertEqual(points[1]['posted'], points[0]['posted'])
            ramworks = [p['rw_hits'] + p['rw_misses'] for p in points]
            self.assertEqual(ramworks[1] - ramworks[0], 10)
            # the same write with the pair at 0 goes to the screen
            self.assertEqual(ramworks[2], ramworks[1])

    def test_the_report_counts_the_pair(self):
        program = [0xA9, 0x06, 0x8D, 0x69, 0xC0,    # lda #6 / sta $C069
                   0xA9, 0x05, 0x85, 0x06,          # lda #5 / sta $06
                   0xAD, 0x00, 0x40,                # lda $4000
                   0x8D, 0x00, 0x40,                # sta $4000
                   0x80, 0xFE]                      # bra *
        image = self.directory / 'p.img'
        image.write_bytes(b'A2VMIMG1' + bytes([0, 0, 0x00, 0x08,
                                               len(program), 0, 0, 0]) +
                          bytes(program))
        for profile in ('f121', 'f121zp'):
            report = self.directory / ('%s.jsonl' % profile)
            # bounded: the program reaches its second boundary in 95
            # cycles; a bug of the pair that sends it elsewhere ends at
            # --cycles (then the check fails), not never
            support.run(
                [str(self.out / 'a2vm'), '--rom', str(self.rom), '--core',
                 'w65c02s', '--no-mouse', '--image', str(image),
                 '--reg', 'pc=800', '--boundary', '80F', '--boundaries', '2',
                 '--cycles', '100000',
                 '--cost', str(self.files[profile]), '--cost-report',
                 str(report), '--state', str(self.directory / 's.json')],
                timeout=120, max_bytes=16 << 20, check=True,
                stdout=subprocess.DEVNULL)
            rows = [json.loads(line) for line in
                    report.read_text().splitlines()
                    if line.startswith('{"boundary')]
            state = json.loads((self.directory / 's.json').read_text())
            self.assertEqual((state['end'], state['boundaries']),
                             ('boundaries', 2), profile)
            if profile == 'f121':
                self.assertNotIn('zpb_reads', rows[0])
                self.assertNotIn('zpbank', state)
                continue
            self.assertEqual((rows[0]['zpb_enables'], rows[0]['zpb_loads'],
                              rows[0]['zpb_reads'], rows[0]['zpb_writes']),
                             (1, 1, 1, 0))
            self.assertEqual(rows[1]['zpb_reads'], 0)       # a delta
            self.assertEqual(state['zpbank']['address'], 6)
            self.assertEqual(state['zpbank']['rd'], 5)


if __name__ == '__main__':
    unittest.main()
