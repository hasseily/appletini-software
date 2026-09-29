"""Tests of the trace of ref816 (tools/ref816/trace.c, --trace) and of its
reader (tools/ref816/tracefile.py).

The machine runs a small hand-assembled program whose every frame does
the same thing, so that the counts of a frame can be worked out by hand:
calls into nested phases, far, near, direct page and stack accesses, a
switch to a stack below the split, a direct and a shadowed screen write, a
store into code that runs after it, and a subroutine run at two widths.
A last test runs the game (with build/ contents) traced and untraced and
checks that the trace changes nothing and agrees with the log of marks.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support
from ref816 import (make_image, marks, measures, profile816, run_script,
                    script, title, tracefile)
from test_ref816_machine import have_tools, needs_linkmap

# Code at $03:0000, native mode, 16-bit A and index registers, S = $2345.
MAIN = [0x22, 0x00, 0x02, 0x03,     # 0000 jsl frame     (a frame starts)
        0x22, 0x00, 0x03, 0x03,     # 0004 jsl work
        0x80, 0xf6]                 # 0008 bra 0000
FRAME = [0x6b]                      # 0200 rtl
WORK = [0xe2, 0x20,                 # 0300 sep #$20
        0x20, 0x50, 0x03,           # 0302 jsr widths    (8-bit A)
        0xaf, 0x00, 0x00, 0x7f,     # 0305 lda $7F0000   far read
        0x8f, 0x00, 0x20, 0xe1,     # 0309 sta $E12000   screen, direct
        0x8f, 0x01, 0x20, 0x01,     # 030D sta $012001   screen, shadowed
        0x8f, 0x00, 0x00, 0x02,     # 0311 sta $020000   near write
        0xa9, 0xea,                 # 0315 lda #$EA
        0x8f, 0x40, 0x03, 0x03,     # 0317 sta $030340   into code
        0x85, 0x10,                 # 031B sta $10       direct page
        0xc2, 0x20,                 # 031D rep #$20
        0x20, 0x50, 0x03,           # 031F jsr widths    (16-bit A)
        0x20, 0x60, 0x03,           # 0322 jsr inner
        0x3b,                       # 0325 tsc
        0x85, 0x12,                 # 0326 sta $12
        0xa9, 0x00, 0x01,           # 0328 lda #$0100
        0x1b,                       # 032B tcs           (below the split)
        0x48,                       # 032C pha
        0x68,                       # 032D pla
        0xa5, 0x12,                 # 032E lda $12
        0x1b,                       # 0330 tcs
        0x80, 0x0d]                 # 0331 bra 0340
PATCHED = [0xea, 0x6b]              # 0340 nop (written by 0317) / rtl
WIDTHS = [0xea, 0x60]               # 0350 nop / rts
INNER = [0xaf, 0x01, 0x00, 0x7f,    # 0360 lda $7F0001   far read, 16 bits
         0x60]                      # 0364 rts
FAR_DATA = bytes([0x55, 0x66, 0x77])
PHASES = {'setup': 0x030200, 'work': 0x030300, 'inner': 0x030360}
# $C035 with the super hi-res shadow on (and the hi-res pages off).
SWITCHES = (0xc1, 0x00, 0x06, 0x80)

# An interrupt: the ADB mouse interrupt on, then frames in a loop; the
# handler reads the mouse report ($C024 twice), which clears it. The
# vectors are in RAM ($C035 bit 6).
IRQ_MAIN = [0xe2, 0x20,                 # 0000 sep #$20
            0xa9, 0x40,                 # 0002 lda #$40
            0x8f, 0x27, 0xc0, 0xe0,     # 0004 sta $E0C027
            0xc2, 0x20,                 # 0008 rep #$20
            0x58,                       # 000A cli
            0x22, 0x00, 0x02, 0x03,     # 000B jsl frame
            0x80, 0xfa]                 # 000F bra 000B
HANDLER = [0xe2, 0x20,                  # 3000 sep #$20
           0xaf, 0x24, 0xc0, 0xe0,      # 3002 lda $E0C024
           0xaf, 0x24, 0xc0, 0xe0,      # 3006 lda $E0C024
           0x40]                        # 300A rti
IRQ_SWITCHES = (0xc1, 0x00, 0x46, 0x80)


def program_image(loads=None, switches=SWITCHES):
    registers = make_image.Registers(pc=0, pbr=3, dbr=0, a=0, x=0, y=0,
                                     s=0x2345, d=0, p=0x04, e=0)
    if loads is None:
        loads = [(0x030000, bytes(MAIN)), (0x030200, bytes(FRAME)),
                 (0x030300, bytes(WORK)), (0x030340, bytes(PATCHED)),
                 (0x030350, bytes(WIDTHS)), (0x030360, bytes(INNER)),
                 (0x7f0000, FAR_DATA)]
    return make_image.image_bytes(registers, loads, switches)


def trace_options(path):
    options = ['--trace', str(path), '--trace-frame', '030200',
               '--trace-near', '02', '--trace-stack-split', '0200']
    for name, address in PHASES.items():
        options += ['--trace-phase', '%s=%06X' % (name, address)]
    return options


@have_tools
class TracedProgram(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out, _ = support.ref816_build()
        cls.machine = out / 'ref816'
        cls.directory = Path(tempfile.mkdtemp(dir=str(out)))
        cls.image = cls.directory / 'test.img'
        cls.image.write_bytes(program_image())
        cls.path = cls.directory / 'test.trace'
        cls.state = cls.run_machine(trace_options(cls.path) +
                                    ['--cycles', '5000'])
        cls.trace = tracefile.read(cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.directory))

    @classmethod
    def run_machine(cls, options):
        result = subprocess.run(
            [str(cls.machine), str(cls.image)] + [str(o) for o in options],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)

    def phase(self, name):
        return self.trace.phase(name)

    def test_header(self):
        t = self.trace
        self.assertEqual(t.phases, ['other', 'interrupt', 'setup', 'work',
                                    'inner'])
        self.assertEqual(t.entries, {0x030200: 2, 0x030300: 3,
                                     0x030360: 4})
        self.assertEqual(t.near, {0x02})
        self.assertEqual(t.split, 0x0200)
        self.assertEqual(t.end.cycles, self.state['cycles'])

    def test_frames_follow_each_other(self):
        frames = self.trace.frames
        self.assertGreater(len(frames), 10)
        self.assertEqual([f.index for f in frames], list(range(len(frames))))
        for a, b in zip(frames, frames[1:]):
            self.assertEqual(a.end, b.start)
        measures.check(self.trace)          # phases add up to the frame

    def test_instructions_by_phase(self):
        # work: 27 instructions of its own (the subroutine at 0350 is not
        # a phase), inner 2, setup the rtl, other jsl work, bra, jsl frame.
        expected = {self.phase('other'): 3, self.phase('setup'): 1,
                    self.phase('work'): 27, self.phase('inner'): 2}
        for frame in self.trace.frames:
            self.assertEqual({p: c[0] for p, c in frame.cost.items()},
                             expected)
            self.assertEqual(frame.instructions, 33)
            self.assertEqual(frame.unclosed, 0)
            self.assertEqual(frame.enters, {self.phase('setup'): 1,
                                            self.phase('work'): 1,
                                            self.phase('inner'): 1})
            self.assertEqual(frame.firmware, (0, 0))
        self.assertEqual(self.trace.jumps, {})

    def test_accesses(self):
        work, inner = self.phase('work'), self.phase('inner')
        for frame in self.trace.frames:
            a = frame.access
            self.assertEqual(a[(work, 'data', 0x7f)], (1, 0))
            self.assertEqual(a[(inner, 'data', 0x7f)], (2, 0))
            self.assertEqual(a[(work, 'data', 0xe1)], (0, 1))
            self.assertEqual(a[(work, 'data', 0x01)], (0, 1))
            self.assertEqual(a[(work, 'data', 0x02)], (0, 1))
            self.assertEqual(a[(work, 'data', 0x03)], (0, 1))
            # sta $10 (8 bits), sta $12 and lda $12 (16 bits)
            self.assertEqual(a[(work, 'direct', 0x00)], (2, 3))
            # two jsr and the pha, two rts and the pla; the rtl of work
            # itself pulls in work, its jsl pushes in other
            self.assertEqual(a[(work, 'stack', 0x00)], (9, 8))
            self.assertEqual(a[(inner, 'stack', 0x00)], (2, 0))
            # 7F -> E1 -> 01 -> 03 in work (02 is near), 03 -> 7F in inner
            self.assertEqual(frame.switches, {work: 3, inner: 1})
            # $7F0000 and $7F0001-2 are one 8-byte line
            self.assertEqual(frame.lines[0x7f], (1, 1, 1, 0, 0, 0))
            self.assertEqual(frame.lines[0x03], (1, 1, 1, 1, 1, 1))

    def test_stack(self):
        work, inner = self.phase('work'), self.phase('inner')
        for frame in self.trace.frames:
            self.assertEqual(frame.stack[work], (0x2340, 0x00fe))
            self.assertEqual(frame.stack[inner], (0x2340, None))

    def test_screen(self):
        work = self.phase('work')
        frames = self.trace.frames
        # $55 goes to $E1:2000 directly and to $E1:2001 through $01:2001:
        # both bytes change in the first frame only.
        self.assertEqual(frames[0].screen, {work: (1, 1, 2)})
        for frame in frames[1:]:
            self.assertEqual(frame.screen, {work: (1, 1, 0)})

    def test_writes_to_code(self):
        smc = {(s.frame, s.writer, s.target): s.count
               for s in self.trace.smc}
        self.assertEqual(smc, {(f.index, 0x030317, 0x030340): 1
                               for f in self.trace.frames})
        self.assertEqual(self.trace.smc_mixed, 0)

    def test_heat(self):
        work = self.phase('work')
        for frame in self.trace.frames:
            self.assertEqual(frame.heat[(work, 0x030350)], (2, 1))
            self.assertEqual(frame.heat[(work, 0x030305)], (1, 4))
            self.assertEqual(sum(c for c, _ in frame.heat.values()), 33)

    def test_widths(self):
        widths = self.trace.widths
        # M set (8-bit A) then clear; X clear throughout; D and DBR 0
        self.assertEqual(widths[0x030350], {'mx': {0b10, 0b00}, 'd': {0},
                                            'dbr': {0}})
        self.assertEqual(widths[0x030305]['mx'], {0b10})

    def test_tracing_changes_nothing(self):
        untraced = self.run_machine(['--cycles', '5000'])
        self.assertEqual(untraced['ram_fnv1a64'], self.state['ram_fnv1a64'])
        self.assertEqual(untraced['cycles'], self.state['cycles'])

    def test_window_between_notes(self):
        directory = self.directory / 'window'
        directory.mkdir()
        program = directory / 'input.txt'
        program.write_text('1 note start\n+1 note end\n+1 stop\n')
        path = directory / 'window.trace'
        self.run_machine(trace_options(path) + [
            '--input', program, '--frames', '10', '--trace-from', 'start',
            '--trace-to', 'end'])
        trace = tracefile.read(path)
        notes = dict(trace.notes)
        self.assertEqual(sorted(notes), ['end', 'start'])
        self.assertGreater(len(trace.frames), 100)
        self.assertGreaterEqual(trace.frames[0].start.clock,
                                notes['start'].clock)
        self.assertLessEqual(trace.frames[-1].end.clock, notes['end'].clock)
        # The frame the end note cut is dropped, and so are its writes.
        last = trace.frames[-1].index
        self.assertTrue(all(s.frame <= last for s in trace.smc))

    def test_option_errors(self):
        for options in (['--trace-frame', '030200'],
                        ['--trace', self.directory / 'x.trace',
                         '--trace-phase', 'work'],
                        ['--trace', self.directory / 'x.trace',
                         '--trace-phase', 'other=030300'],
                        ['--trace', self.directory / 'x.trace',
                         '--trace-near', '100']):
            result = subprocess.run(
                [str(self.machine), str(self.image), '--cycles', '10'] +
                [str(o) for o in options], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, universal_newlines=True)
            self.assertEqual(result.returncode, 2, options)


@have_tools
class TracedInterrupt(unittest.TestCase):
    def test_an_interrupt_is_a_phase(self):
        out, _ = support.ref816_build()
        directory = Path(tempfile.mkdtemp(dir=str(out)))
        self.addCleanup(shutil.rmtree, str(directory))
        image = directory / 'irq.img'
        image.write_bytes(program_image(
            [(0x030000, bytes(IRQ_MAIN)), (0x030200, bytes(FRAME)),
             (0x003000, bytes(HANDLER)), (0x00ffee, bytes([0x00, 0x30]))],
            IRQ_SWITCHES))
        program = directory / 'input.txt'
        program.write_text('0 mouse 3 4\n+3 stop\n')
        path = directory / 'irq.trace'
        result = subprocess.run(
            [str(out / 'ref816'), str(image), '--input', str(program),
             '--frames', '10'] + [str(o) for o in trace_options(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        interrupts = json.loads(result.stdout)['interrupts']
        self.assertEqual(interrupts, 1)
        trace = tracefile.read(path)
        irq = trace.phase('interrupt')
        taken = [f for f in trace.frames if irq in f.cost]
        self.assertEqual(len(taken), 1)
        frame, = taken
        # sep, lda, lda, rti; the two mouse reads; the entry pushes PBR,
        # PC, P and fetches the vector, the rti pulls them
        self.assertEqual(frame.cost[irq][0], 4)
        self.assertEqual(frame.enters[irq], 1)
        self.assertEqual(frame.access[(irq, 'io', 0xe0)], (2, 0))
        self.assertEqual(frame.access[(irq, 'stack', 0x00)], (4, 4))
        self.assertEqual(frame.access[(irq, 'vector', 0x00)], (2, 0))
        self.assertTrue(all(f.unclosed == 0 for f in trace.frames))
        measures.check(trace)


@have_tools
class TracedFirmware(unittest.TestCase):
    """A firmware trap charges its cycles with no instruction: they go to
    the frame's firmware record, never to the phase that made the call."""

    # Code in bank 0, where the slot firmware is: a frame, then a call of
    # "work", which calls the block driver (STATUS of unit $70).
    MAIN = [0x22, 0x00, 0x02, 0x03,     # 1000 jsl frame
            0x20, 0x00, 0x11,           # 1004 jsr work
            0x80, 0xf7]                 # 1007 bra 1000
    WORK = [0x20, 0x0a, 0xc7,           # 1100 jsr $C70A
            0x60]                       # 1103 rts

    def test_firmware_cycles_are_no_phase(self):
        out, _ = support.ref816_build()
        directory = Path(tempfile.mkdtemp(dir=str(out)))
        self.addCleanup(shutil.rmtree, str(directory))
        image = directory / 'firmware.img'
        registers = make_image.Registers(pc=0x1000, pbr=0, dbr=0, a=0, x=0,
                                         y=0, s=0x2345, d=0, p=0x04, e=0)
        image.write_bytes(make_image.image_bytes(
            registers, [(0x001000, bytes(self.MAIN)),
                        (0x001100, bytes(self.WORK)),
                        (0x030200, bytes(FRAME)),
                        (0x000042, bytes([0x00, 0x70]))], SWITCHES))
        path = directory / 'firmware.trace'
        options = ['--trace', str(path), '--trace-frame', '030200',
                   '--trace-phase', 'setup=030200',
                   '--trace-phase', 'work=001100']
        result = subprocess.run(
            [str(out / 'ref816'), str(image), '--cycles', '20000'] + options,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertGreater(state['firmware']['driver_calls'], 5)
        self.assertEqual(state['firmware']['errors'], 0)
        self.assertEqual(state['firmware']['cycles'],
                         2000 * state['firmware']['driver_calls'])
        trace = tracefile.read(path)
        measures.check(trace)       # phases and firmware add up
        other, work = trace.phase('other'), trace.phase('work')
        setup = trace.phase('setup')
        self.assertGreater(len(trace.frames), 5)
        for frame in trace.frames:
            # jsr $C70A and rts in work; jsr work, bra and jsl in other
            self.assertEqual(frame.cost[work], (2, 12))
            self.assertEqual(frame.cost[other], (3, 17))
            self.assertEqual(frame.cost[setup], (1, 6))
            self.assertEqual(frame.firmware, (1, 2000))
            self.assertEqual(frame.cycles, 12 + 17 + 6 + 2000)
            self.assertEqual(frame.enters, {setup: 1, work: 1})
        self.assertEqual(measures.firmware_cycles(trace),
                         [2000] * len(trace.frames))


class TraceFile(unittest.TestCase):
    TEXT = '\n'.join([
        'ref816-trace 1', 'phase 0 other', 'phase 1 interrupt',
        'phase 2 work', 'entry 030300 2', 'near 02', 'split 1B6F',
        'note a 10 20 30',
        'frame 0 100 200 300 110 235 310',
        'cost 0 4 10', 'cost 2 6 20', 'enters 2 3', 'firmware 1 5',
        'access 2 data 7F 3 1', 'lines 7F 1 1 1 0 0 0', 'switches 2 5',
        'stack 2 3FF0 -', 'screen 2 0 4 2', 'heat 2 030300 6 3',
        'unclosed 0',
        'smc 0 030317 030340 2', 'smc-mixed 1', 'jumps 2 4',
        'width 030300 mx 2', 'width 030300 d 900', 'width 030300 dbr 2',
        'end 120 240 320', ''])

    def test_parse(self):
        t = tracefile.parse(self.TEXT)
        self.assertEqual(t.phases, ['other', 'interrupt', 'work'])
        self.assertEqual(t.notes, [('a', tracefile.Counts(10, 20, 30))])
        frame, = t.frames
        self.assertEqual((frame.instructions, frame.cycles), (10, 35))
        self.assertEqual(frame.cost, {0: (4, 10), 2: (6, 20)})
        self.assertEqual(frame.enters, {2: 3})
        self.assertEqual(frame.firmware, (1, 5))
        measures.check(t)           # 10 + 20 cycles and 5 of firmware
        t.frames[0].firmware = (0, 0)
        with self.assertRaisesRegex(ValueError, 'frame 0'):
            measures.check(t)
        self.assertEqual(frame.access, {(2, 'data', 0x7f): (3, 1)})
        self.assertEqual(frame.stack, {2: (0x3ff0, None)})
        self.assertEqual(frame.screen, {2: (0, 4, 2)})
        self.assertEqual(frame.heat, {(2, 0x030300): (6, 3)})
        self.assertEqual(t.smc, [tracefile.Smc(0, 0x030317, 0x030340, 2)])
        self.assertEqual((t.smc_mixed, t.jumps), (1, {2: 4}))
        self.assertEqual(t.widths, {0x030300: {'mx': {2}, 'd': {0x900},
                                               'dbr': {2}}})
        self.assertEqual(t.end, tracefile.Counts(120, 240, 320))

    def test_errors(self):
        for text, message in (
                ('', 'not a ref816 trace'),
                ('ref816-trace 1\nphase 1 x\nend 1 2 3\n', 'line 2'),
                ('ref816-trace 1\ncost 0 1 2\nend 1 2 3\n', 'before any'),
                ('ref816-trace 1\nbogus\nend 1 2 3\n', 'unknown record'),
                ('ref816-trace 1\nwidth 000000 q 1\nend 1 2 3\n', 'kind'),
                ('ref816-trace 1\nphase 0 other\n', 'cut short')):
            with self.assertRaisesRegex(ValueError, message):
                tracefile.parse(text)


@have_tools
@needs_linkmap
@support.needs_release
class TracedGame(unittest.TestCase):
    """The game traced from the note "still" of newgame.script: the same
    run as untraced, and frames that agree with the log of marks."""

    def test_the_trace_agrees_with_the_marks(self):
        title.build_machine()
        title.ensure_image()
        with open(str(make_image.LINKMAP)) as handle:
            symbols = script.Symbols(json.load(handle))
        scenario = profile816.SCENARIOS[0]
        path = run_script.script_path(scenario.script)
        program = script.compile_script(path.read_text(), symbols,
                                        path.name)
        directory = Path(tempfile.mkdtemp(dir=str(make_image.OUT_DIR)))
        self.addCleanup(shutil.rmtree, str(directory))
        states = []
        for traced in (False, True):
            run = run_script.Run(directory / str(traced),
                                 directory / str(traced) / 'shots')
            extra = profile816.trace_options(
                symbols, scenario, directory / 'still.trace') \
                if traced else []
            states.append(run.execute(program, symbols, None, 900, extra))
        self.assertEqual(states[0]['ram_fnv1a64'], states[1]['ram_fnv1a64'])
        self.assertEqual(states[0]['cycles'], states[1]['cycles'])
        trace = tracefile.read(directory / 'still.trace')
        measures.check(trace)
        log = marks.read(run.marks_path)
        render = symbols.address(profile816.FRAME_ENTRY)
        start, end = [n for n in marks.notes(log)
                      if n.what in (scenario.start, scenario.end)]
        inside = [e for e in marks.at(log, render)
                  if start.clock <= e.clock <= end.clock]
        self.assertGreaterEqual(len(trace.frames), 20)
        self.assertEqual(
            [(f.start.cycles, f.end.cycles) for f in trace.frames],
            [(a.cycles, b.cycles) for a, b in zip(inside, inside[1:])])
        self.assertEqual([f.instructions for f in trace.frames],
                         [b.instructions - a.instructions
                          for a, b in zip(inside, inside[1:])])
        self.assertTrue(all(f.unclosed == 0 for f in trace.frames))


if __name__ == '__main__':
    unittest.main()
