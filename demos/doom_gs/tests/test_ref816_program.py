"""Tests of the input program of ref816 (tools/ref816/program.c) and of
the options of main.c that the script runs use: the log of marks and
notes, several stop addresses, --stop-on-fault and --cpu-hz.

The machine runs small hand-made images: a counter loop that stores a
growing word at $7F0000, so that waits have something to watch.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support
from ref816 import marks
from test_ref816_machine import have_tools, tiny_image

# rep #$30 / lda ##0 / loop: inc a / sta $7F0000 / bra loop
COUNTER = [0xc2, 0x30, 0xa9, 0x00, 0x00, 0x1a, 0x8f, 0x00, 0x00, 0x7f,
           0x80, 0xf9]
LOOP = 0x030005


@have_tools
class Program(unittest.TestCase):
    def setUp(self):
        out, _ = support.ref816_build()
        self.machine = out / 'ref816'
        self.directory = Path(tempfile.mkdtemp(dir=str(out)))
        self.addCleanup(shutil.rmtree, str(self.directory))

    def run_machine(self, program, *arguments, code=COUNTER):
        image = self.directory / 'test.img'
        image.write_bytes(tiny_image(code))
        command = [str(self.machine), str(image), '--shot-dir',
                   str(self.directory)]
        if program is not None:
            path = self.directory / 'input.txt'
            path.write_text(program)
            command += ['--input', str(path)]
        return subprocess.run(command + [str(a) for a in arguments],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)

    def state(self, program, *arguments, **keywords):
        result = self.run_machine(program, *arguments, **keywords)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_steps_in_order(self):
        log = self.directory / 'marks.txt'
        state = self.state(
            '# the counter has run by frame 1\n'
            '0 wait 0x7F0000 2 ge 1000 100\n'
            '+0 note counted\n'
            '+2 poke 0x7E0000 2 0x1234\n'
            '+0 shot after-poke\n'
            '+3 stop\n',
            '--frames', 100, '--marks', log, '--peek', '7E0000:2')
        self.assertEqual(state['end'], {'reason': 'stop', 'pc': 0,
                                        'line': 6})
        self.assertEqual(state['frames'], 1 + 2 + 3)
        self.assertEqual(state['peek']['7E0000'], '3412')
        self.assertTrue((self.directory / 'after-poke.shr').exists())
        entries = marks.read(log)
        self.assertEqual([(e.kind, e.what) for e in entries],
                         [('note', 'counted'), ('end', '-')])
        frame = 912 * 262
        self.assertGreaterEqual(entries[0].clock, frame)
        self.assertLess(entries[0].clock, frame + 100)

    def test_gain_counts_from_the_start_of_its_wait(self):
        # The counter goes up by one every 11 cycles, 4344 a frame, and
        # wraps at 64 K: each wait takes 14 frames from its start.
        log = self.directory / 'marks.txt'
        state = self.state('0 wait 0x7F0000 2 gain 60000 50\n'
                           '+0 note first\n'
                           '+0 wait 0x7F0000 2 gain 60000 50\n'
                           '+0 note second\n'
                           '+0 stop\n', '--frames', 100, '--marks', log)
        self.assertEqual(state['end']['reason'], 'stop')
        first, second = marks.notes(marks.read(log))
        frame = 912 * 262
        self.assertEqual(first.clock // frame, 14)
        self.assertEqual(second.clock // frame, 28)

    def test_timeout(self):
        state = self.state('2 wait 0x7E0000 1 eq 5 3\n', '--frames', 100)
        self.assertEqual(state['end'], {'reason': 'timeout', 'pc': 0,
                                        'line': 1})
        self.assertEqual(state['frames'], 2 + 3)

    def test_late(self):
        state = self.state('10 key 1 down\n5 key 1 up\n', '--frames', 100)
        self.assertEqual(state['end']['reason'], 'late')
        self.assertEqual(state['end']['line'], 2)

    def test_the_run_goes_on_after_the_last_step(self):
        state = self.state('1 key 53 down\n', '--frames', 5)
        self.assertEqual(state['end']['reason'], 'frames')
        self.assertEqual(state['frames'], 5)

    def test_marks(self):
        log = self.directory / 'marks.txt'
        state = self.state(None, '--cycles', 1000, '--mark', '%06X' % LOOP,
                           '--marks', log)
        entries = marks.read(log)
        loops = marks.at(entries, LOOP)
        # the loop: inc a (2), sta long (6), bra (3)
        self.assertEqual([b.cycles - a.cycles
                          for a, b in zip(loops, loops[1:])],
                         [11] * (len(loops) - 1))
        self.assertEqual([b.instructions - a.instructions
                          for a, b in zip(loops, loops[1:])],
                         [3] * (len(loops) - 1))
        self.assertEqual(entries[-1].kind, 'end')
        self.assertEqual(entries[-1].cycles, state['cycles'])
        self.assertEqual(entries[-1].instructions, state['instructions'])

    def test_marks_do_not_change_the_run(self):
        program = ('1 wait 0x7F0000 2 ge 30000 10\n+1 poke 0x7E0000 2 7\n'
                   '+1 stop\n')
        plain = self.state(program, '--frames', 50)
        marked = self.state(program, '--frames', 50, '--mark',
                            '%06X' % LOOP, '--marks',
                            self.directory / 'marks.txt')
        self.assertEqual(plain, marked)

    def test_stop_addresses(self):
        state = self.state(None, '--cycles', 1000, '--stop-pc', '123456',
                           '--stop-pc', '%06X' % LOOP)
        self.assertEqual(state['end']['reason'], 'stop-pc')
        self.assertEqual(state['end']['pc'], LOOP)
        self.assertTrue(state['stopped_at_pc'])

    def test_faults(self):
        spin = self.state(None, '--cycles', 1000, '--stop-on-fault',
                          code=[0xea, 0x80, 0xfe])
        self.assertEqual(spin['end'], {'reason': 'spin', 'pc': 0x030001,
                                       'line': 0})
        wdm = self.state(None, '--cycles', 1000, '--stop-on-fault',
                         code=[0xea, 0x42, 0x00, 0xea])
        self.assertEqual(wdm['end']['reason'], 'opcode')
        self.assertEqual(wdm['end']['pc'], 0x030001)
        self.assertEqual(wdm['opcodes']['wdm'], 1)
        # Without the option both run on.
        self.assertEqual(self.state(None, '--cycles', 1000,
                                    code=[0x80, 0xfe])['end']['reason'],
                         'cycles')

    def test_cpu_rate(self):
        state = self.state(None, '--cycles', 12000000, '--cpu-hz', 12000000)
        self.assertEqual(state['cpu_hz'], 12000000)
        # 12 MHz: 715909 master clocks every 600000 cycles.
        self.assertEqual(state['master_clocks'],
                         state['cycles'] * 715909 // 600000)
        self.assertEqual(state['frames'], 59)
        own = self.state(None, '--cycles', 1000)
        self.assertEqual(own['cpu_hz'], 2863636)
        self.assertEqual(own['master_clocks'], 5 * own['cycles'])

    def test_errors(self):
        for text, message in [
                ('1 key 200 down', 'an ADB key code is 0-127'),
                ('1 key 1 sideways', 'expected down or up'),
                ('1 jump 1 2', 'unknown input jump'),
                ('1 key 1', 'expected WHEN key CODE down|up'),
                ('x key 1 up', 'not a number'),
                ('-1 key 1 up', 'not a number'),
                ('1 mouse 1 99999', 'not a number from -32768 to 32767'),
                ('1 button 2 down', 'the mouse has buttons 0 and 1'),
                ('1 shot ../x', 'a name is up to 63 letters'),
                ('1 poke 0x800000 1 0', '$800000 is not in RAM'),
                ('1 poke 0x7F0000 3 0', 'a size is 1, 2 or 4 bytes'),
                ('1 poke 0x7F0000 1 256', '256 does not fit in 1 bytes'),
                ('1 wait 0x7F0000 2 gt 1 10', 'a wait tests eq, ne, ge'),
                ('1 wait 0x7F0000 2 eq 1', 'expected WHEN wait'),
                ('1 stop now', 'expected WHEN stop'),
                ('stop', 'expected WHEN ACTION')]:
            result = self.run_machine('# a comment\n\n' + text + '\n',
                                      '--frames', 1)
            self.assertEqual(result.returncode, 2, text)
            self.assertIn('input.txt:3: ' + message, result.stderr, text)
        # The last line without its newline is read like the others.
        result = self.run_machine('1 stop\n1 jump', '--frames', 1)
        self.assertIn('input.txt:2: unknown input jump', result.stderr)
        result = self.run_machine('1 key 1 up ' + 'x ' * 8 + '\n',
                                  '--frames', 1)
        self.assertIn('input.txt:1: too many words', result.stderr)
        result = self.run_machine('1 stop #' + 'x' * 300 + '\n',
                                  '--frames', 1)
        self.assertIn('input.txt:1: a line is longer', result.stderr)
        result = self.run_machine(None, '--frames', 1, '--mark', '030000')
        self.assertIn('--mark needs --marks', result.stderr)
        result = self.run_machine(None, '--frames', 1, '--cpu-hz', '5')
        self.assertIn('--cpu-hz takes', result.stderr)


if __name__ == '__main__':
    unittest.main()
