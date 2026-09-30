"""Tests of the memory ref816 writes into a run from outside
(tools/ref816/inject.c): --poke-file at points of the run, and --wad with
--lump, which place a lump in the game's WAD; and of tools/ref816/lumps.py.

The machine runs hand-made routines on a hand-made WAD. On the release
(skipped without build/), DEMO3 placed at $7E:0000 under its own entry
gives the run of the release mark for mark, and DEMO1 placed as DEMO3
starts E1M5 (its header's map).
"""

import json
import struct
import unittest

import support
from ref816 import dumps, lumps, make_image, marks, run_script, title
from test_ref816_call import Machine
from test_ref816_dump import CODE, REGISTERS, loads
from test_ref816_machine import have_tools, needs_linkmap

WAD = 0x100000


def wad_records(names=('ONE', 'DEMO3'), sizes=(4, 4)):
    """A WAD at $10:0000: a header, the directory at +12, the lumps from
    +0x40 (bytes 1, 2, ...)."""
    directory = b''
    data = b''
    for index, (name, size) in enumerate(zip(names, sizes)):
        directory += struct.pack('<II8s', 0x40 + len(data), size,
                                 name.encode())
        data += bytes([index + 1]) * size
    header = b'IWAD' + struct.pack('<II', len(names), 12)
    return [(WAD, header + directory), (WAD + 0x40, data)]


@have_tools
class Pokes(Machine):
    def run_pokes(self, text, *arguments, files=()):
        path = self.directory / 'pokes.txt'
        path.write_text(text)
        for name, data in files:
            (self.directory / name).write_bytes(data)
        stream = self.directory / 'dumps.stream'
        state = self.state(self.image(loads(), REGISTERS), '--poke-file',
                           path, '--dump-stream', stream, *arguments)
        return dumps.Stream(stream), state

    def test_pokes_at_points(self):
        # SUB copies $7E0010 to $7E0020 at each call.
        stream, state = self.run_pokes(
            '# point              address  data\n'
            'pc=032000,hits=3     7E0010   3412   # the third call\n'
            'frame=0              7E0030   @bytes.bin\n'
            'cycle=3000           7E0040   @sub/more.bin\n',
            '--cycles', 5000, '--peek', '7E0020:2', '--peek', '7E0030:3',
            '--peek', '7E0040:1',
            '--dump-at', 'pc=032000,hits=3,ranges=7E0010:2+7E0020:2',
            '--dump-at', 'pc=032000,hits=2,ranges=7E0010:2',
            files=(('bytes.bin', b'\xaa\xbb\xcc'),))
        third = [d for d in stream.dumps if d.header['point'] == 0][0]
        second = [d for d in stream.dumps if d.header['point'] == 1][0]
        # The poke comes before the dump of the same moment, and after
        # the second call.
        self.assertEqual(second.data, bytes(2))
        self.assertEqual(third.data, bytes([0x34, 0x12, 0, 0]))
        self.assertEqual(state['peek'], {'7E0020': '3412',
                                         '7E0030': 'aabbcc',
                                         '7E0040': '5a'})

    def test_every_hit_pokes_again(self):
        _, state = self.run_pokes('pc=032000 7E0000 0000\n', '--cycles',
                                  5000, '--dump-at', 'frame=0,ranges=00',
                                  '--peek', '7E0000:2')
        # SUB counts the call after the poke that cleared the count.
        self.assertEqual(state['peek']['7E0000'], '0100')

    def setUp(self):
        super().setUp()
        (self.directory / 'sub').mkdir()
        (self.directory / 'sub' / 'more.bin').write_bytes(b'\x5a')

    def test_errors(self):
        for text in ('pc=032000 7E0010\n',
                     'pc=032000 7E0010 123\n',
                     'pc=032000 7E0010 zz\n',
                     'pc=032000 900000 00\n',
                     'pc=032000,ranges=00 7E0010 00\n',
                     'nowhere 7E0010 00\n',
                     'frame=0 7E0010 @missing.bin\n',
                     'frame=0 7FFFFF 0000\n'):
            path = self.directory / 'bad.txt'
            path.write_text('# a comment\n\n' + text)
            result = self.run_machine(self.image(loads(), REGISTERS),
                                      '--cycles', 100, '--poke-file', path)
            self.assertEqual(result.returncode, 2, text)
            self.assertIn('bad.txt:3: ', result.stderr)

    def test_pokes_across_banks_within_ram(self):
        _, state = self.run_pokes('frame=0 7EFFFF 0102\n', '--cycles', 100,
                                  '--dump-at', 'frame=0,ranges=00',
                                  '--peek', '7EFFFF:2')
        self.assertEqual(state['peek']['7EFFFF'], '0102')


@have_tools
class Lumps(Machine):
    def place(self, *arguments, records=None):
        lump = self.directory / 'lump.bin'
        lump.write_bytes(b'LUMP-BYTES')
        image = self.image(loads() + (records or wad_records()), REGISTERS)
        return self.run_machine(image, '--cycles', 10, '--wad', '100000',
                                *[str(a).replace('LUMP', str(lump))
                                  for a in arguments])

    def test_placement(self):
        directory = self.directory / 'directory.bin'
        data = self.directory / 'data.bin'
        # (the loop of the image counts in $7E0000)
        result = self.place('--lump', 'DEMO3:7D0000:LUMP',
                            '--save', '10000C:32:%s' % directory,
                            '--save', '7D0000:12:%s' % data)
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = directory.read_bytes()
        self.assertEqual(entries[:16], struct.pack('<II8s', 0x40, 4, b'ONE'))
        self.assertEqual(entries[16:],
                         struct.pack('<II8s', 0x7d0000 - WAD, 10, b'DEMO3'))
        self.assertEqual(data.read_bytes(), b'LUMP-BYTES\0\0')

    def test_refusals(self):
        for arguments, records, message in (
                (['--lump', 'DEMO9:7E0000:LUMP'], None, '0 entries'),
                (['--lump', 'DEMO3:7E0000:LUMP'],
                 wad_records(('DEMO3', 'DEMO3')), '2 entries'),
                (['--lump', 'DEMO3:7EFFF8:LUMP'], None, 'within one bank'),
                (['--lump', 'DEMO3:900000:LUMP'], None, 'within one bank'),
                (['--lump', 'DEMO3:031000:LUMP'], None, 'not free'),
                (['--lump', 'DEMO3:7E0000:LUMP'],
                 [(WAD, b'JUNK')], 'no IWAD'),
                (['--lump', 'TOOLONGNAME:7E0000:LUMP'], None, 'NAME:DEST'),
                (['--lump', 'DEMO3:7E0000'], None, 'NAME:DEST:FILE')):
            result = self.place(*arguments, records=records)
            self.assertEqual(result.returncode, 2, arguments)
            self.assertIn(message, result.stderr, arguments)

    def test_lump_needs_wad(self):
        result = self.run_machine(self.image(loads(), REGISTERS),
                                  '--cycles', 10, '--lump', 'A:7E0000:x')
        self.assertEqual(result.returncode, 2)
        self.assertIn('--lump needs --wad', result.stderr)


class WadReader(unittest.TestCase):
    def test_demo_info(self):
        lump = bytes([109, 2, 1, 5]) + bytes(9) + bytes(4 * 7) + b'\x80'
        self.assertEqual(lumps.demo_info(lump), {
            'version': 109, 'skill': 2, 'episode': 1, 'map': 5, 'tics': 7})
        with self.assertRaises(ValueError):
            lumps.demo_info(lump[:-1])

    def test_demo_script_compiles(self):
        class Symbols:
            def address(self, text):
                return 0x1234
        program = run_script.script.compile_script(
            lumps.demo_script(5), Symbols(), 'demo')
        self.assertIn('note demo', program)
        self.assertIn('note demo-end', program)
        self.assertTrue(program.rstrip().splitlines()[-1].split('#')[0]
                        .strip().endswith('stop'))


@have_tools
@needs_linkmap
@support.needs_release
@unittest.skipUnless(lumps.WAD.exists(), '%s is missing: run python3 '
                     'tools/fetch_upstream.py first' % lumps.WAD)
class Release(unittest.TestCase):
    def setUp(self):
        title.build_machine()
        title.ensure_image()
        self.symbols = dumps.symbols()

    def test_demo3_moved_plays_as_the_release(self):
        plain = run_script.run(run_script.script_path('title'),
                               name='test-lump-plain')
        moved = run_script.run(
            run_script.script_path('title'), name='test-lump-moved',
            extra=lumps.options('DEMO3', self.symbols,
                                out=make_image.OUT_DIR / 'test-lumps'))
        self.assertEqual(plain['problems'], [])
        self.assertEqual(moved['problems'], [])
        runs = run_script.RUNS
        self.assertEqual(
            marks.read(runs / 'test-lump-plain' / 'marks.txt'),
            marks.read(runs / 'test-lump-moved' / 'marks.txt'))
        self.assertEqual(sorted(plain['shots']), sorted(moved['shots']))
        for dump in (runs / 'test-lump-plain' / 'dumps').glob('*.shr'):
            self.assertEqual(dump.read_bytes(),
                             (runs / 'test-lump-moved' / 'dumps' /
                              dump.name).read_bytes())
        self.assertNotEqual(plain['ram_fnv1a64'], moved['ram_fnv1a64'])

    def test_demo1_starts_e1m5(self):
        info = lumps.demo_info(lumps.read_wad()['DEMO1'])
        self.assertEqual((info['map'], info['tics']), (5, 5026))
        script = make_image.OUT_DIR / 'test-lumps' / 'demo1-start.script'
        script.parent.mkdir(parents=True, exist_ok=True)
        text = lumps.demo_script(info['map']).replace(
            'wait _g_demoplayback == 0', 'at +35t note one-second\n'
            'wait _g_demoplayback == 1 within 1s\n#')
        script.write_text(text)
        report = run_script.run(
            script, name='test-lump-demo1',
            extra=lumps.options('DEMO1', self.symbols,
                                out=make_image.OUT_DIR / 'test-lumps'))
        self.assertEqual(report['problems'], [])
        self.assertEqual(report['end']['reason'], 'stop')


if __name__ == '__main__':
    unittest.main()
