#!/usr/bin/env python3
"""The tests of a2vm --via-timers: timer 1 of the Phasor's VIAs.

Usage:
  python3 tools/a2vm/viatest.py --a2vm BUILD/a2vm   (make viatest)

  - the registers: random sequences of accesses to VIA-B's timer-1
    registers (T1C-L/H, T1L-L/H, ACR, IFR, IER), in Mockingboard and in
    native mode, against a model that steps hdl/apple/via6522.v's timer-1
    logic a bus cycle at a time (each read's value, cycle for cycle);
  - the interrupt: a program whose handler acknowledges the VIA, on both
    cores, gets one interrupt every latch + 2 bus cycles, and none while
    IER is clear;
  - the idle skip ends at the timer's interrupt;
  - without --via-timers nothing changes: the registers a2sim.py does not
    model read $FF and no interrupt comes.
"""

import argparse
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

A2VM = None                         # set by main()
VIA_B = 0xC480
T1CL, T1CH, T1LL, T1LH, ACR, IFR, IER = 4, 5, 6, 7, 11, 13, 14


class Via6522:
    """Timer 1 of hdl/apple/via6522.v, a bus cycle at a time: in each
    cycle the timer steps first (slow_clock, sss_en), then the CPU's
    access (data_en) has its effect; a read of T1C returns the value before
    the cycle's step (timer1_bus_value)."""

    def __init__(self, native=False):
        self.native = native
        self.timer, self.undf = 0xFFFF, False
        self.latch = 0xFFFF
        self.one_shot = self.irq_t1 = False
        self.acr = self.ier = 0
        self.bus_value = 0xFFFF
        self.cycle = 0               # the last cycle run (the power-on)

    def tick(self):
        if self.undf:
            if self.one_shot or self.acr & 0x40:
                self.irq_t1 = True
            if not self.acr & 0x40:
                self.one_shot = False
            self.timer, self.undf = self.latch, False
        else:
            if self.timer == 0:
                self.undf = True
            self.timer = (self.timer - 1) & 0xFFFF

    def run_to(self, cycle):
        while self.cycle < cycle:
            self.cycle += 1
            self.bus_value = self.timer
            self.tick()

    def access(self, cycle, write, reg, value=0):
        self.run_to(cycle)
        if write:
            if reg in (T1CL, T1LL):
                self.latch = (self.latch & 0xFF00) | value
            elif reg == T1CH:
                self.latch = (self.latch & 0x00FF) | value << 8
                self.timer, self.undf = self.latch, False
                self.one_shot, self.irq_t1 = True, False
            elif reg == T1LH:
                self.latch = (self.latch & 0x00FF) | value << 8
                self.irq_t1 = False
            elif reg == ACR:
                self.acr = value
            elif reg == IFR and value & 0x40:
                self.irq_t1 = False
            elif reg == IER:
                if value & 0x80:
                    self.ier |= value & 0x7F
                else:
                    self.ier &= ~value & 0x7F
            return None
        if reg == T1CL:
            result = self.bus_value & 0xFF
            self.irq_t1 = False
            if self.native:          # the extra step (mockingboard.sv:97)
                self.tick()
            return result
        if reg == T1CH:
            return self.bus_value >> 8
        if reg == T1LL:
            return self.latch & 0xFF
        if reg == T1LH:
            return self.latch >> 8
        if reg == ACR:
            return self.acr
        if reg == IFR:
            flags = 0x40 if self.irq_t1 else 0
            return flags | (0x80 if flags & self.ier else 0)
        if reg == IER:
            return 0x80 | self.ier
        raise ValueError(reg)


def synthetic_rom(directory, irq=0x0400):
    """16 KB: the IRQ vector at $FFFE, BRK-free filler elsewhere."""
    rom = bytearray((i * 7 + 3) & 0xFF for i in range(0x4000))
    rom[0x3FFE], rom[0x3FFF] = irq & 0xFF, irq >> 8
    path = Path(directory) / 'rom.bin'
    path.write_bytes(bytes(rom))
    return path


class Workspace(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='viatest-'))
        self.addCleanup(shutil.rmtree, str(self.directory), True)
        self.rom = synthetic_rom(self.directory)

    def a2vm(self, arguments, timeout=120):
        result = subprocess.run(
            [str(A2VM), '--rom', str(self.rom)] + [str(a) for a in arguments],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, timeout=timeout)
        self.assertEqual(result.returncode, 0, result.stdout[-2000:])
        return result.stdout

    def bus(self, lines, *arguments):
        script = self.directory / 'bus.txt'
        script.write_text('\n'.join(lines) + '\n')
        out = self.a2vm(['--speed', 1] + list(arguments) +
                        ['--bus-script', script])
        return out.splitlines()

    @staticmethod
    def reads(lines):
        return [int(line.split()[2], 16) for line in lines
                if line.startswith('read ')]


def random_sequence(rng, length=80):
    """(cycle, write, reg, value) accesses, a cycle apart at least."""
    out, cycle = [(1, True, ACR, rng.choice((0x00, 0x40)))], 1
    cycle += rng.randrange(1, 4)
    out.append((cycle, True, T1CL, rng.randrange(256)))
    cycle += rng.randrange(1, 4)
    out.append((cycle, True, T1CH, rng.randrange(2)))
    for _ in range(length):
        cycle += rng.choice((1, 1, 2, 3, rng.randrange(1, 40),
                             rng.randrange(1, 700)))
        kind = rng.randrange(20)
        if kind < 9:
            out.append((cycle, False, rng.choice(
                (T1CL, T1CH, IFR, IFR, IFR, T1LL, T1LH, ACR, IER)), 0))
        elif kind < 11:
            out.append((cycle, True, rng.choice((T1CL, T1LL)),
                        rng.randrange(256)))
        elif kind < 12:
            out.append((cycle, True, rng.choice((T1CH, T1LH)),
                        rng.randrange(3)))
        elif kind < 14:
            out.append((cycle, True, ACR, rng.choice((0x00, 0x40))))
        elif kind < 16:
            out.append((cycle, True, IFR, rng.choice((0x40, 0x7F, 0x3F))))
        else:
            out.append((cycle, True, IER, rng.choice((0xC0, 0x40, 0x7F,
                                                      0x82))))
    return out


class Registers(Workspace):
    def check(self, seed, native):
        rng = random.Random(seed)
        sequence = random_sequence(rng)
        model = Via6522(native)
        expected = []
        lines = ['write C0C8 00', 'write C0C5 00'] if native else []
        for cycle, write, reg, value in sequence:
            lines.append('clock %d' % cycle)
            if write:
                lines.append('write %04X %02X' % (VIA_B + reg, value))
                model.access(cycle, True, reg, value)
            else:
                lines.append('read %04X' % (VIA_B + reg))
                expected.append(model.access(cycle, False, reg))
        got = self.reads(self.bus(lines, '--via-timers'))
        if got != expected:
            reads = [s for s in sequence if not s[1]]
            for (cycle, _, reg, _), g, e in zip(reads, got, expected):
                if g != e:
                    self.fail('seed %d native %d: cycle %d register %d: '
                              'a2vm $%02X, via6522.v $%02X'
                              % (seed, native, cycle, reg, g, e))
            self.fail('seed %d: %d reads, %d expected'
                      % (seed, len(got), len(expected)))

    def test_mockingboard_mode(self):
        for seed in range(40):
            with self.subTest(seed=seed):
                self.check(seed, False)

    def test_native_mode(self):
        for seed in range(40, 80):
            with self.subTest(seed=seed):
                self.check(seed, True)

    def test_free_run_by_hand(self):
        # latch 10: the flag every 12 cycles, from the T1C-H write
        lines = ['clock 100', 'write C48B 40', 'write C484 0A',
                 'write C485 00']
        for cycle in (101, 110, 111, 112, 113, 124, 136):
            lines += ['clock %d' % cycle, 'read C48D', 'read C485']
        lines += ['write C48D 40', 'read C48D', 'write C48E C0',
                  'read C48E', 'clock 148', 'read C48D']
        got = self.reads(self.bus(lines, '--via-timers'))
        self.assertEqual(got[0:14:2], [0, 0, 0, 0x40, 0x40, 0x40, 0x40])
        self.assertEqual(got[14:], [0x00, 0xC0, 0xC0])


PROGRAM = 0x0300
HANDLER = 0x0400


def program_bytes(latch, ier=0xC0):
    """$0300: VIA-B timer 1 free-running with `latch`, IER = `ier`, CLI,
    then a loop serving each interrupt ($10-$11 counts them, $12-$13 the
    ones served, $14 counts services). $0400: the handler, IFR bit 6
    checked and acknowledged."""
    code = [0xA9, 0x40, 0x8D, 0x8B, 0xC4,           # LDA #$40; STA ACR
            0xA9, latch & 0xFF, 0x8D, 0x84, 0xC4,   # T1C-L
            0xA9, latch >> 8, 0x8D, 0x85, 0xC4,     # T1C-H: start
            0xA9, ier, 0x8D, 0x8E, 0xC4,            # IER
            0x58]                                   # CLI
    loop = PROGRAM + len(code)
    code += [0xA5, 0x10, 0xC5, 0x12,                # LDA $10; CMP $12
             0xF0, 0xFA,                            # BEQ loop
             0x85, 0x12, 0xE6, 0x14,                # STA $12; INC $14
             0x4C, loop & 0xFF, loop >> 8]
    handler = [0x48,                                # PHA
               0xAD, 0x8D, 0xC4,                    # LDA IFR
               0x29, 0x40, 0xF0, 0x09,              # AND #$40; BEQ done
               0x8D, 0x8D, 0xC4,                    # STA IFR: acknowledge
               0xE6, 0x10, 0xD0, 0x02, 0xE6, 0x11,  # INC $10 (16 bits)
               0x68, 0x40]                          # done: PLA; RTI
    image = bytearray(HANDLER - PROGRAM + len(handler))
    image[0:len(code)] = bytes(code)
    image[HANDLER - PROGRAM:] = bytes(handler)
    return bytes(image), loop


class Interrupts(Workspace):
    def run_program(self, latch, cycles, core, ier=0xC0, extra=()):
        image, loop = program_bytes(latch, ier)
        (self.directory / 'prog.bin').write_bytes(image)
        log = self.directory / 'ay.log'
        state = self.directory / 'state.json'
        self.a2vm(['--speed', 1, '--core', core, '--via-timers',
                   '--load', '300:%s' % (self.directory / 'prog.bin'),
                   '--reg', 'pc=300', '--reg', 's=FF', '--reg', 'p=34',
                   '--cycles', cycles, '--ay-log', log, '--state', state,
                   '--no-mouse'] + list(extra))
        entries = [int(line.split()[3]) for line in log.read_text().split(
            '\n') if line.startswith('irq ')]
        return json.loads(state.read_text()), entries, loop

    def check_rate(self, latch, core, extra=()):
        cycles = 60 * (latch + 2) + 500
        state, entries, _ = self.run_program(latch, cycles, core,
                                             extra=extra)
        period = latch + 2
        # the T1C-H write is the program's 15th byte: the first time-out
        # latch + 2 cycles after it, then one every latch + 2
        self.assertGreaterEqual(len(entries), 59)
        for a, b in zip(entries, entries[1:]):
            self.assertLessEqual(abs(b - a - period), 8, (a, b))
        span = entries[-1] - entries[0]
        self.assertLessEqual(abs(span - (len(entries) - 1) * period), 8)
        self.assertEqual(state['irqs'], len(entries))
        return state, entries

    def test_rate_exact_core(self):
        for latch in (998, 17028, 20278):
            with self.subTest(latch=latch):
                self.check_rate(latch, 'w65c02s')

    def test_rate_compatibility_core(self):
        self.check_rate(998, 'py65')

    def test_acknowledged(self):
        state, entries, _ = self.run_program(1998, 30000, 'w65c02s')
        via = state['via_timers'][1]
        self.assertEqual(via['ier'], 0x40)
        self.assertEqual(via['acr'], 0x40)
        self.assertEqual(via['latch'], 1998)
        self.assertEqual(len(entries), state['irqs'])

    def test_no_interrupt_without_ier(self):
        state, entries, _ = self.run_program(998, 20000, 'w65c02s', ier=0x40)
        self.assertEqual(entries, [])
        self.assertEqual(state['via_timers'][1]['ifr'], 0x40)

    def test_idle_skip_stops_at_the_timer(self):
        # the loop waits for $10-$11 to leave $12-$13: an idle loop of the
        # VBL kind would skip to the next VBL, past ~17 interrupts
        _, loop = program_bytes(998)
        state, entries = self.check_rate(
            998, 'w65c02s',
            extra=['--idle', '%X:vbl:eq=10,12' % loop])
        self.assertGreater(state['idle_cycles'], 0)


class Default(Workspace):
    def test_unchanged_without_the_option(self):
        lines = ['clock 10', 'write C48B 40', 'write C484 0A',
                 'write C485 00', 'write C48E C0', 'clock 200',
                 'read C48D', 'read C48E', 'read C48B', 'read C486',
                 'read C485', 'read C484']
        got = self.reads(self.bus(lines))
        # a2sim.Phasor: unmodelled registers read $FF, timer 1 a
        # free-running count from $FFFF since the T1C-H write
        self.assertEqual(got, [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF - 190])

    def test_no_interrupt_without_the_option(self):
        image, _ = program_bytes(998)
        (self.directory / 'prog.bin').write_bytes(image)
        state = self.directory / 'state.json'
        self.a2vm(['--speed', 1, '--core', 'w65c02s', '--load',
                   '300:%s' % (self.directory / 'prog.bin'),
                   '--reg', 'pc=300', '--reg', 'p=34', '--cycles', 50000,
                   '--state', state, '--no-mouse'])
        result = json.loads(state.read_text())
        self.assertEqual(result['irqs'], 0)
        self.assertNotIn('via_timers', result)


def main():
    global A2VM
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--a2vm', required=True, help='the a2vm binary')
    arguments, rest = parser.parse_known_args()
    A2VM = Path(arguments.a2vm).resolve()
    unittest.main(argv=[sys.argv[0]] + rest)


if __name__ == '__main__':
    main()
