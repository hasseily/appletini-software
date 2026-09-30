"""Tests of ref816's dump streams (--dump-at, --dump-stream; main.c,
tools/ref816/points.c) and of tools/ref816/dumps.py.

The machine runs a hand-made loop that calls a counting routine; dumps at
its entries, at frames and at cycle counts must equal the two-run method
(a run to the point that dumps all RAM with --dump-ram and stops). On the
release (skipped without build/), the six captures of
docs/research/native-verification.md section 3.1 are made both ways and
must be equal, the acceptance of milestone 6 (about 15 s).
"""

import io
import subprocess
import unittest

import support
from ref816 import dumps, make_image, marks
from test_ref816_call import Machine
from test_ref816_machine import have_tools, needs_linkmap

REGISTERS = make_image.Registers(pc=0x1000, pbr=3, dbr=0x7e, a=0, x=0, y=0,
                                 s=0x01ff, d=0, p=0x04, e=0)
SUB = 0x032000
# A loop that calls SUB for ever; SUB counts its calls in the word at
# $7E0000 and copies the word at $7E0010 to $7E0020.
CODE = {
    0x031000: [0xc2, 0x30,              # rep #$30
               0x20, 0x00, 0x20,        # 1002 jsr SUB
               0x80, 0xfb],             # bra 1002
    SUB: [0xee, 0x00, 0x00,             # inc $0000
          0xad, 0x10, 0x00,             # lda $0010
          0x8d, 0x20, 0x00,             # sta $0020
          0x60],                        # rts
}
ALL_RAM = (0x80 + 2) * 0x10000
# The bound of every stream of these tests (--dump-limit): four dumps of
# all RAM and change. A stream that would grow past it fails the run.
STREAM_LIMIT = 36 << 20


def loads():
    return [(address, bytes(data)) for address, data in CODE.items()]


@have_tools
class DumpAt(Machine):
    def setUp(self):
        super().setUp()
        self.loop = self.image(loads(), REGISTERS)

    def stream(self, *arguments, image=None):
        path = self.directory / 'dumps.stream'
        state = self.state(image or self.loop, '--dump-stream', path,
                           '--dump-limit', STREAM_LIMIT, *arguments)
        self.assertLessEqual(path.stat().st_size, STREAM_LIMIT)
        return dumps.Stream(path), state

    def two_run(self, *arguments):
        """RAM and the final state of a run that stops at the point."""
        path = self.directory / 'ram.bin'
        state = self.state(self.loop, '--dump-ram', path, *arguments)
        return path.read_bytes(), state

    def test_hits_and_ranges(self):
        stream, state = self.stream(
            '--cycles', 20000, '--dump-at',
            'pc=032000,hits=2-6/2,ranges=7E0000:2+7E0020:0x2',
            '--peek', '7E0000:2')
        self.assertEqual(stream.info, {'format': 'ref816-dump-stream 1',
                                       'points': [
            'pc=032000,hits=2-6/2,ranges=7E0000:2+7E0020:0x2']})
        self.assertEqual(stream.end, {'end': 'cycles', 'dumps': 3})
        self.assertEqual([d.header['dump'] for d in stream.dumps], [1, 2, 3])
        self.assertEqual([d.header['hit'] for d in stream.dumps], [2, 4, 6])
        for dump in stream.dumps:
            header = dump.header
            self.assertEqual(header['point'], 0)
            self.assertEqual(header['cpu']['pc'], SUB)
            self.assertEqual(header['ranges'], [[0x7e0000, 2],
                                                [0x7e0020, 2]])
            self.assertEqual(header['bytes'], 4)
            # Before the instruction at SUB: the calls before this one.
            count = header['hit'] - 1
            self.assertEqual(dump.get(0x7e0000, 2), bytes([count, 0]))
            self.assertEqual(header['peek'], {'7E0000': '%02x00' % count})
            self.assertIn('shadow', header['switches'])
        cycles = [d.header['cycles'] for d in stream.dumps]
        self.assertEqual(cycles, sorted(cycles))
        self.assertLess(cycles[-1], state['cycles'])

    def test_a_hit_equals_the_two_run_method(self):
        log = self.directory / 'marks.txt'
        self.state(self.loop, '--cycles', 20000, '--mark', '032000',
                   '--marks', log)
        third = [e for e in marks.read(log) if e.kind == 'mark'][2]
        ram, state = self.two_run('--cycles', third.cycles)
        stream, _ = self.stream('--cycles', 20000, '--dump-at',
                                'pc=032000,hits=3')
        dump = stream.dumps[0]
        self.assertEqual(len(dump.data), ALL_RAM)
        self.assertEqual(dump.data, ram)
        self.assertEqual(dump.header['cycles'], state['cycles'])
        self.assertEqual(dump.header['instructions'], state['instructions'])
        self.assertEqual(dump.header['cpu'], {k: v for k, v in
                                              state['cpu'].items()
                                              if k != 'state'})
        self.assertEqual(dump.header['ranges'],
                         [[0, 0x800000], [0xe00000, 0x20000]])

    def test_frames_and_cycles_equal_the_two_run_method(self):
        stream, _ = self.stream('--frames', 7, '--dump-at', 'frame=2-6/2',
                                '--dump-at', 'cycle=50000,ranges=7E-7E')
        frames = [d for d in stream.dumps if d.header['point'] == 0]
        self.assertEqual([d.header['hit'] for d in frames], [2, 4, 6])
        self.assertEqual([d.header['frame'] for d in frames], [2, 4, 6])
        ram, state = self.two_run('--frames', 4)
        self.assertEqual(frames[1].data, ram)
        self.assertEqual(frames[1].header['cycles'], state['cycles'])
        cycle = [d for d in stream.dumps if d.header['point'] == 1]
        self.assertEqual(len(cycle), 1)
        ram, state = self.two_run('--cycles', 50000)
        self.assertEqual(cycle[0].header['hit'], 50000)
        self.assertEqual(cycle[0].header['cycles'], state['cycles'])
        self.assertEqual(cycle[0].data, ram[0x7e0000:0x7f0000])

    def test_dumps_of_one_moment_in_the_order_of_the_options(self):
        stream, _ = self.stream('--cycles', 5000,
                                '--dump-at', 'pc=032000,hits=2,ranges=00',
                                '--dump-at', 'pc=032000,hits=2,ranges=7E')
        self.assertEqual([d.header['point'] for d in stream.dumps], [0, 1])
        self.assertEqual(stream.dumps[0].header['cycles'],
                         stream.dumps[1].header['cycles'])

    def test_frame_zero_is_before_any_instruction(self):
        stream, _ = self.stream('--cycles', 1000, '--dump-at',
                                'frame=0,ranges=7E0000:2')
        self.assertEqual(stream.dumps[0].header['cycles'], 0)
        self.assertEqual(stream.dumps[0].header['cpu']['pc'], 0x031000)

    def test_after_a_note_and_if(self):
        program = self.directory / 'input.txt'
        program.write_text('3 note cap\n')
        log = self.directory / 'marks.txt'
        self.state(self.loop, '--frames', 5, '--input', program,
                   '--mark', '032000', '--marks', log)
        entries = marks.read(log)
        cap = [e for e in entries if e.kind == 'note'][0]
        first = [e for e in entries if e.kind == 'mark' and
                 e.cycles > cap.cycles][0]
        stream, _ = self.stream('--frames', 5, '--input', program,
                                '--dump-at',
                                'pc=032000,after=cap,hits=1',
                                '--dump-at',
                                'pc=032000,if=7E0000:2:ge:10,hits=1,'
                                'ranges=7E0000:2')
        after = [d for d in stream.dumps if d.header['point'] == 0][0]
        ram, _ = self.two_run('--frames', 5, '--input', program, '--cycles',
                              first.cycles)
        self.assertEqual(after.data, ram)
        self.assertEqual(after.header['cycles'], first.cycles)
        self.assertEqual(after.header['note'], 'cap')
        test = [d for d in stream.dumps if d.header['point'] == 1][0]
        self.assertEqual(test.data, bytes([10, 0]))
        self.assertEqual(test.header['hit'], 1)

    def test_stream_on_stdout(self):
        result = support.run(
            [str(self.machine), str(self.loop), '--cycles', '5000',
             '--state', str(self.directory / 'state.json'),
             '--dump-stream', '-', '--dump-at',
             'pc=032000,hits=1,ranges=7E0000:2'], timeout=self.TIMEOUT,
            max_bytes=self.MAX_BYTES, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)
        stream = dumps.Stream(io.BytesIO(result.stdout))
        self.assertEqual(len(stream.dumps), 1)
        self.assertEqual(stream.dumps[0].data, bytes(2))

    def test_the_dumps_change_nothing(self):
        """Dumps at every fifth call (181 of them), one of all RAM, and
        at every frame: the run is the run without them. The stream stays
        small: 64 bytes a call."""
        plain = self.state(self.loop, '--cycles', 30000)
        stream, dumped = self.stream('--cycles', 30000, '--dump-at',
                                     'pc=032000,hits=5-/5,ranges=7E0000:0x40',
                                     '--dump-at', 'pc=032000,hits=5',
                                     '--dump-at', 'frame=all,ranges=00')
        self.assertEqual(plain, dumped)
        self.assertEqual(stream.end, {'end': 'cycles', 'dumps': 183})
        whole = [d for d in stream.dumps if d.header['point'] == 1]
        self.assertEqual([len(d.data) for d in whole], [ALL_RAM])
        self.assertLess((self.directory / 'dumps.stream').stat().st_size,
                        ALL_RAM + (1 << 20))

    def test_dump_max_ends_the_stream(self):
        """--dump-max: the dump past it is not written; the stream ends
        with "dump-max" and the run fails."""
        path = self.directory / 'dumps.stream'
        result = self.run_machine(self.loop, '--cycles', 30000,
                                  '--dump-stream', path, '--dump-at',
                                  'pc=032000,ranges=7E0000:2',
                                  '--dump-max', 3)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('would pass --dump-max 3', result.stderr)
        stream = dumps.Stream(path)
        self.assertEqual(len(stream.dumps), 3)
        self.assertEqual(stream.end, {'end': 'dump-max', 'dumps': 3})

    def test_dump_limit_bounds_the_stream(self):
        """--dump-limit: a dump at every instruction stops at the limit,
        a byte-exact bound on the file, with the stream's last line."""
        path = self.directory / 'dumps.stream'
        result = self.run_machine(self.loop, '--cycles', 1000000,
                                  '--dump-stream', path, '--dump-at',
                                  'cycle=all,ranges=7E0000:1',
                                  '--dump-limit', 20000)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('past --dump-limit 20000 bytes', result.stderr)
        self.assertLessEqual(path.stat().st_size, 20000)
        stream = dumps.Stream(path)
        self.assertEqual(stream.end['end'], 'dump-limit')
        self.assertEqual(stream.end['dumps'], len(stream.dumps))
        self.assertGreater(len(stream.dumps), 10)
        # all RAM does not fit in a limit of 8 MB: no dump at all
        result = self.run_machine(self.loop, '--cycles', 1000,
                                  '--dump-stream', path,
                                  '--dump-at', 'frame=0',
                                  '--dump-limit', 8 << 20)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(dumps.Stream(path).end,
                         {'end': 'dump-limit', 'dumps': 0})

    def test_errors(self):
        for arguments in (
                ['--dump-at', 'pc=032000'],
                ['--dump-stream', 'x'],
                ['--dump-at', 'pc=zz', '--dump-stream', 'x'],
                ['--dump-at', 'pc=032000,ranges=90', '--dump-stream', 'x'],
                ['--dump-at', 'pc=032000,ranges=7E0000:0',
                 '--dump-stream', 'x'],
                ['--dump-at', 'frame=2,hits=1', '--dump-stream', 'x'],
                ['--dump-at', 'frame=5-2', '--dump-stream', 'x'],
                ['--dump-at', 'hits=1', '--dump-stream', 'x'],
                ['--dump-at', 'pc=032000,if=7E0000:3:eq:1',
                 '--dump-stream', 'x'],
                ['--dump-at', 'pc=032000,if=7E0000:1:eq:256',
                 '--dump-stream', 'x'],
                ['--dump-at', 'pc=032000', '--dump-stream', '-'],
                ['--dump-at', 'pc=032000', '--dump-stream',
                 self.directory / 'x', '--dump-limit', '10']):
            result = self.run_machine(self.loop, '--cycles', 100, *arguments)
            self.assertEqual(result.returncode, 2, arguments)
            self.assertIn('ref816: ', result.stderr)


class Points(unittest.TestCase):
    def test_resolve(self):
        class Symbols:
            def address(self, text):
                return {'G_Ticker': 0x03ceb7, '_g_gametic': 0x02c6af,
                        '_g_player': 0x02c614}[text.partition('+')[0]] + \
                    int(text.partition('+')[2] or '0', 0)
        self.assertEqual(
            dumps.resolve('pc=G_Ticker,after=cap,if=_g_gametic:4:ge:100,'
                          'ranges=02+_g_player:155+1D-1E+_g_player+2:4',
                          Symbols()),
            'pc=03CEB7,after=cap,if=02C6AF:4:ge:100,'
            'ranges=02+02C614:155+1D-1E+02C616:4')
        self.assertEqual(dumps.resolve('frame=5-/10', Symbols()),
                         'frame=5-/10')


@have_tools
@needs_linkmap
@support.needs_release
class Release(unittest.TestCase):
    def test_the_six_captures_equal_the_two_run_method(self):
        dumps.title.build_machine()
        dumps.title.ensure_image()
        out = make_image.OUT_DIR / 'test-dumps'
        results = []
        for name in sorted(dumps.SCRIPTS):
            results += dumps.verify(name, out)
        self.assertEqual(len(results), 6)
        for capture in results:
            self.assertTrue(capture.at_entry, capture)
            self.assertTrue(capture.equal, capture)
            self.assertTrue(capture.registers_equal, capture)
        # The cycle counts of native-verification.md section 3.1.
        self.assertEqual({c.name: c.cycles for c in results}, {
            'e1m1-G_Ticker': 172980261, 'e1m1-R_DrawLists': 172583162,
            'e1m3-G_Ticker': 404818326, 'e1m3-R_DrawLists': 405384889,
            'demo-G_Ticker': 261613133, 'demo-R_DrawLists': 262188510})


if __name__ == '__main__':
    unittest.main()
