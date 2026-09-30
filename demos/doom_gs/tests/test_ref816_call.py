"""Tests of ref816's --call and --capture (tools/ref816/footprint.c) and of
the options that go with them in main.c: --load, --load-image, --reg,
--save, --call-reads, --call-writes. The machine runs small hand-made
routines; tests/test_ref816_capture.py runs the game's own replay.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support
from ref816 import make_image, refimage
from test_ref816_machine import have_tools

REGISTERS = make_image.Registers(pc=0, pbr=3, dbr=0, a=0, x=0, y=0,
                                 s=0x2345, d=0, p=0x04, e=0)
DATA = 0x7e0000
RETURN = 0x045677               # the caller's return address, less 1

# The routine at $03:1000: it reads DATA, calls a subroutine with JSR and
# another with JSL (each adds 1), stores the results and returns with RTL.
ROUTINE = {
    0x031000: [0xe2, 0x30,                  # sep #$30
               0xaf, 0x00, 0x00, 0x7e,      # lda $7E0000
               0x20, 0x00, 0x20,            # jsr $2000
               0x22, 0x00, 0x30, 0x03,      # jsl $03:3000
               0x8f, 0x02, 0x00, 0x7e,      # sta $7E0002
               0x6b],                       # rtl
    0x032000: [0x1a,                        # inc a
               0x8f, 0x01, 0x00, 0x7e,      # sta $7E0001
               0x60],                       # rts
    0x033000: [0x1a,                        # inc a
               0x6b],                       # rtl
}
ROUTINE_INSTRUCTIONS = 11
# sep, lda (the data byte), jsr, inc, sta, rts, jsl, inc, rtl, sta, rtl.


def records(code, extra=()):
    loads = [(address, bytes(data)) for address, data in code.items()]
    loads.append((DATA, bytes([0x41])))
    # The return address the final RTL pulls: above S.
    loads.append((REGISTERS.s + 1, bytes([RETURN & 0xff, RETURN >> 8 & 0xff,
                                          RETURN >> 16])))
    return loads + list(extra)


class Machine(unittest.TestCase):
    # The bounds of every run of the machine (support.run): these
    # programs run for milliseconds and write a few dumps at most.
    TIMEOUT = 120
    MAX_BYTES = 64 << 20

    def setUp(self):
        out, _ = support.ref816_build()
        self.machine = out / 'ref816'
        self.directory = Path(tempfile.mkdtemp(dir=str(out)))
        self.addCleanup(shutil.rmtree, str(self.directory))

    def image(self, loads, registers=REGISTERS, name='test.img'):
        path = self.directory / name
        path.write_bytes(make_image.image_bytes(registers, loads))
        return path

    def run_machine(self, image, *arguments):
        return support.run(
            [str(self.machine), str(image)] + [str(a) for a in arguments],
            timeout=self.TIMEOUT, max_bytes=self.MAX_BYTES,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)

    def state(self, image, *arguments):
        result = self.run_machine(image, *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)


@have_tools
class Call(Machine):
    def test_call_runs_to_its_return(self):
        reads, writes = self.directory / 'r.img', self.directory / 'w.img'
        state = self.state(self.image(records(ROUTINE)), '--call', '031000',
                           '--call-reads', reads, '--call-writes', writes,
                           '--peek', '7E0000:3')
        self.assertEqual(state['end']['reason'], 'return')
        self.assertEqual(state['peek']['7E0000'], '414243')
        cpu = state['cpu']
        self.assertEqual(cpu['pc'], RETURN + 1)
        self.assertEqual(cpu['s'], REGISTERS.s + 3)
        call = state['call']
        self.assertTrue(call['returned'])
        self.assertEqual(call['depth'], 0)
        self.assertEqual(call['instructions'], ROUTINE_INSTRUCTIONS)
        self.assertEqual(state['instructions'], ROUTINE_INSTRUCTIONS)
        self.assertEqual(call['cycles'], state['cycles'])
        self.assertEqual(call['interrupts']['count'], 0)
        self.assertEqual(call['start']['pc'], 0x031000)
        self.assertEqual(call['end']['pc'], RETURN + 1)

        # Writes: the two stores and the JSR and JSL pushes, $2343-$2345,
        # which the shadow register ($08: hi-res page 1 shadowed) also
        # copies to bank $E0.
        written = refimage.read(writes)
        pushes = bytes([0x0c, 0x10, 0x03])
        self.assertEqual(written.records, [(0x2343, pushes),
                                           (0x7e0001, bytes([0x42, 0x43])),
                                           (0xe02343, pushes)])
        self.assertEqual(written.registers.pc, (RETURN + 1) & 0xffff)
        self.assertEqual(call['bytes_written'], 8)
        self.assertEqual(call['written_then_changed'], 0)

        # Reads: every byte of code run, the data, and the return address
        # the last RTL pulls; not the stack bytes the call pushed first.
        memory = refimage.load(refimage.read(reads))
        code_bytes = sum(len(c) for c in ROUTINE.values())
        self.assertEqual(memory.count(), code_bytes + 1 + 3)
        self.assertEqual(call['bytes_read'], memory.count())
        self.assertEqual(memory.byte(DATA), 0x41)
        self.assertEqual(memory.get(REGISTERS.s + 1, 3),
                         bytes([0x77, 0x56, 0x04]))
        for address, code in ROUTINE.items():
            self.assertEqual(memory.get(address, len(code)), bytes(code))
        self.assertFalse(memory.is_known(REGISTERS.s))
        self.assertEqual(refimage.read(reads).registers.pc, 0x1000)

    def test_the_reads_alone_run_the_call_again(self):
        reads, writes = self.directory / 'r.img', self.directory / 'w.img'
        first = self.state(self.image(records(ROUTINE)), '--call', '031000',
                           '--call-reads', reads, '--call-writes', writes)
        again_writes = self.directory / 'w2.img'
        again = self.state(reads, '--call', '031000', '--call-writes',
                           again_writes)
        self.assertEqual(again['end']['reason'], 'return')
        self.assertEqual(again['call']['instructions'],
                         first['call']['instructions'])
        self.assertEqual(again['cpu'], first['cpu'])
        self.assertEqual(again_writes.read_bytes(), writes.read_bytes())

    def test_brk_and_its_rti_are_inside_the_call(self):
        # BRK goes through the native vector $00:FFE6, which the ROM
        # answers with 0 (shadow $08: I/O and ROM mapped in): an RTI at
        # $00:0000 comes back, and the call goes on to its own RTL.
        code = {0x031000: [0xe2, 0x30, 0x00, 0xea,   # sep; brk $EA
                           0xa9, 0x99,               # lda #$99
                           0x8f, 0x00, 0x00, 0x7e,   # sta $7E0000
                           0x6b],                    # rtl
                0x000000: [0x40]}                    # rti
        state = self.state(self.image(records(code)), '--call', '031000',
                           '--peek', '7E0000:1')
        self.assertEqual(state['end']['reason'], 'return')
        self.assertEqual(state['peek']['7E0000'], '99')
        self.assertEqual(state['call']['instructions'], 6)
        self.assertEqual(state['call']['rom_reads'], 2)
        self.assertEqual(state['cpu']['pc'], RETURN + 1)

    def test_a_call_that_does_not_return_stops_at_its_limit(self):
        code = {0x031000: [0x80, 0xfe]}              # bra *
        state = self.state(self.image(records(code)), '--call', '031000',
                           '--cycles', 1000)
        self.assertEqual(state['end']['reason'], 'cycles')
        self.assertFalse(state['call']['returned'])
        self.assertEqual(state['call']['end']['pc'], 0x031000)

    def test_load_reg_and_save(self):
        # rep #$30 / tax / txy / sta $7E0010 / tya / sta $7E0012 / rtl,
        # with A set by --reg and the code put in by --load and
        # --load-image.
        code = bytes([0xc2, 0x30, 0xaa, 0x9b, 0x8f, 0x10, 0x00, 0x7e,
                      0x98, 0x8f, 0x12, 0x00, 0x7e, 0x6b])
        part = self.directory / 'part.bin'
        part.write_bytes(code[:6])
        rest = self.image([(0x031006, code[6:])], name='rest.img')
        saved = self.directory / 'saved.bin'
        state = self.state(
            self.image(records({})), '--load', '031000:%s' % part,
            '--load-image', rest, '--reg', 'a=BEEF', '--reg', 'p=0',
            '--call', '031000', '--save', '7E0010:4:%s' % saved)
        self.assertEqual(state['end']['reason'], 'return')
        self.assertEqual(saved.read_bytes(), bytes([0xef, 0xbe, 0xef, 0xbe]))
        self.assertEqual(state['cpu']['a'], 0xbeef)

    def test_options_that_do_not_go_together(self):
        image = self.image(records(ROUTINE))
        for arguments in (
                ['--frames', 1, '--call-reads', self.directory / 'r.img'],
                ['--call', '031000', '--trace', self.directory / 't'],
                ['--frames', 1, '--capture', self.directory],
                ['--call', '031000', '--capture', self.directory,
                 '--capture-entry', '031000', '--capture-hit', 1],
                ['--call', '031000', '--reg', 'q=1'],
                ['--call', '031000', '--reg', 'e=2'],
                ['--frames', 1, '--load', 'nocolon']):
            result = self.run_machine(image, *arguments)
            self.assertEqual(result.returncode, 2, arguments)


# A loop that calls the routine at $03:1000 four times, then stops; the
# routine adds 1 to DATA.
LOOP = {
    0x030000: [0xe2, 0x30,                  # sep #$30
               0xa2, 0x04,                  # ldx #4
               0x22, 0x00, 0x10, 0x03,      # jsl $03:1000
               0xca,                        # dex
               0xd0, 0xf9,                  # bne (the jsl)
               0xdb],                       # stp
    0x031000: [0xaf, 0x00, 0x00, 0x7e,      # lda $7E0000
               0x1a,                        # inc a
               0x8f, 0x00, 0x00, 0x7e,      # sta $7E0000
               0x6b],                       # rtl
}


@have_tools
class Capture(Machine):
    def test_capture_the_chosen_calls(self):
        out = self.directory / 'captures'
        out.mkdir()
        image = self.image([(a, bytes(c)) for a, c in LOOP.items()] +
                           [(DATA, bytes([0x10]))])
        state = self.state(image, '--cycles', 100000, '--stop-on-fault',
                           '--capture', out, '--capture-entry', '031000',
                           '--capture-hit', 4, '--capture-hit', 2)
        self.assertEqual(state['end']['reason'], 'opcode')
        self.assertNotIn('call', state)
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ['hit-00000002', 'hit-00000004'])
        for hit, before in ((2, 0x11), (4, 0x13)):
            directory = out / ('hit-%08d' % hit)
            call = json.loads((directory / 'call.json').read_text())
            self.assertEqual(call['hit'], hit)
            self.assertEqual(call['entry'], 0x031000)
            self.assertTrue(call['call']['returned'])
            self.assertEqual(call['call']['instructions'], 4)
            entry = refimage.read(directory / 'entry.img')
            self.assertEqual((entry.registers.pbr, entry.registers.pc),
                             (3, 0x1000))
            memory = refimage.load(entry)
            self.assertEqual(memory.byte(DATA), before)
            reads = refimage.load(refimage.read(directory / 'reads.img'))
            self.assertEqual(reads.byte(DATA), before)
            writes = refimage.read(directory / 'writes.img')
            self.assertEqual(writes.records, [(DATA, bytes([before + 1]))])
            self.assertEqual(refimage.read(directory / 'exit.img').records,
                             writes.records)
            self.assertEqual(writes.registers.pc, 0x0008)

    def test_a_capture_that_never_comes_fails(self):
        out = self.directory / 'captures'
        out.mkdir()
        image = self.image([(a, bytes(c)) for a, c in LOOP.items()])
        result = self.run_machine(image, '--cycles', 100000,
                                  '--stop-on-fault', '--capture', out,
                                  '--capture-entry', '031000',
                                  '--capture-hit', 5)
        self.assertEqual(result.returncode, 2)
        self.assertIn('0 of the 1 calls to capture came', result.stderr)


if __name__ == '__main__':
    unittest.main()
