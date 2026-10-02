"""a2vm's options of the speed plan (tools/a2vm/README.md, 2026-10-02):
the idle conditions byte=A,V and eq= on the main language card (lc.), the
PC log (--pclog) and --stop-word, on a small counting program.

Each run is bounded (support.run) in a directory of its own under build/,
deleted after the test; a2vm is built for these tests alone.
"""

import atexit
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

import support

have_tools = unittest.skipUnless(
    shutil.which('cc') and shutil.which('make'), 'cc or make is missing')

# $0800: STZ $3000; STZ $3001; then the loop at $0806: a 16-bit count in
# $3000-$3001 (INC $3000; BNE +3; INC $3001; JMP $0806)
LOOP = 0x0806
PROGRAM = bytes([0x9C, 0x00, 0x30, 0x9C, 0x01, 0x30,
                 0xEE, 0x00, 0x30, 0xD0, 0x03, 0xEE, 0x01, 0x30,
                 0x4C, 0x06, 0x08])
FRAME = 1250000                 # a2vm's turbo frame, in cycles

_built = []


def machine() -> Path:
    """build/…/a2vm, made once from tools/a2vm for these tests."""
    if not _built:
        support.BUILD.mkdir(exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix='test-a2vm-pclog-',
                                    dir=str(support.BUILD)))
        atexit.register(shutil.rmtree, str(out), True)
        result = support.run(
            ['make', '-s', '-C', str(support.ROOT / 'tools' / 'a2vm'),
             'OUT=%s' % out, str(out / 'a2vm')], timeout=300,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)
        _built.extend([out / 'a2vm', result])
    path, result = _built
    if result.returncode:
        raise AssertionError('make failed:\n' + result.stdout)
    return path


def image(records) -> bytes:
    """An A2VMIMG1 image of (kind, address, bytes) records, bank 0."""
    out = b'A2VMIMG1'
    for kind, address, data in records:
        out += struct.pack('<BBHI', kind, 0, address, len(data)) + data
    return out


@have_tools
class Options(unittest.TestCase):

    def setUp(self):
        self.a2vm = machine()
        self.dir = Path(tempfile.mkdtemp(dir=str(self.a2vm.parent)))
        self.addCleanup(shutil.rmtree, str(self.dir), True)
        (self.dir / 'rom.bin').write_bytes(bytes(0x4000))
        (self.dir / 'prog.bin').write_bytes(PROGRAM)

    def run_a2vm(self, *options, records=(), core='w65c02s',
                 cycles=4 * FRAME, start=0x0800, status=0):
        """The state of a run of the program; options are a2vm's."""
        img = self.dir / 'mem.img'
        img.write_bytes(image(records))
        state = self.dir / 'state.json'
        if state.exists():
            state.unlink()
        args = [str(self.a2vm), '--rom', str(self.dir / 'rom.bin'),
                '--core', core, '--image', str(img),
                '--load', '0800:%s' % (self.dir / 'prog.bin'),
                '--reg', 'pc=%X' % start, '--cycles', str(cycles),
                '--state', str(state)] + [str(o) for o in options]
        result = support.run(args, timeout=120, max_bytes=16 << 20,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             universal_newlines=True)
        self.assertEqual(result.returncode, status, result.stdout)
        return json.loads(state.read_text()) if status != 2 else \
            result.stdout

    def fails(self, *options):
        out = self.run_a2vm(*options, status=2)
        self.assertIn('a2vm:', out)

    # ---- the idle conditions -------------------------------------------

    def skipped(self, spec, records=(), *options):
        st = self.run_a2vm('--idle', spec, *options, records=records)
        return st['idle_cycles']

    def test_byte_condition(self):
        mark = [(0, 0x3100, b'\x5A')]
        self.assertGreater(self.skipped('806:vbl:byte=3100,5A', mark),
                           2 * FRAME)
        self.assertEqual(self.skipped('806:vbl:byte=3100,5B', mark), 0)
        both = [(0, 0x3100, b'\x5A\x07')]
        self.assertGreater(self.skipped(
            '806:vbl:byte=3100,5A:byte=3101,7', both), 0)
        self.assertEqual(self.skipped(
            '806:vbl:byte=3100,5A:byte=3101,8', both), 0)

    def test_eq_on_the_language_card(self):
        same = [(2, 0xE407, b'\x34\x12'), (0, 0x1F01, b'\x34\x12')]
        high = [(2, 0xE407, b'\x34\x13'), (0, 0x1F01, b'\x34\x12')]
        low = [(2, 0xE407, b'\x35\x12'), (0, 0x1F01, b'\x34\x12')]
        spec = '806:vbl:eq=lc.E407,1F01'
        self.assertGreater(self.skipped(spec, same), 0)
        self.assertEqual(self.skipped(spec, high), 0)
        self.assertEqual(self.skipped(spec, low), 0)
        # main memory's $E407 is not the card's
        self.assertEqual(self.skipped('806:vbl:eq=E407,1F01', same), 0)
        # the main words, as before
        self.assertGreater(self.skipped('806:vbl:eq=1F01,1F01', same), 0)

    def test_conditions_together(self):
        recs = [(2, 0xE407, b'\x34\x12'), (0, 0x1F01, b'\x34\x12'),
                (0, 0x19EE, b'\x1D')]
        spec = '806:vbl:main:byte=19EE,1D:eq=lc.E407,1F01'
        self.assertGreater(self.skipped(spec, recs), 0)
        self.assertEqual(self.skipped(spec, recs, '--switch', 'altzp=1'), 0)
        self.assertEqual(self.skipped(
            '806:vbl:main:byte=19EE,1C:eq=lc.E407,1F01', recs), 0)

    def test_bad_idle_specs(self):
        self.fails('--idle', '806:vbl:byte=3100')
        self.fails('--idle', '806:vbl:byte=3100,100')
        self.fails('--idle', '806:vbl:eq=lc.1000,1F01')
        self.fails('--idle', '806:vbl:eq=lc.FFFF,1F01')
        self.fails('--idle', '806:vbl:byte=1,1:byte=2,2:byte=3,3:byte=4,4:'
                   'byte=5,5')

    # ---- the PC log ----------------------------------------------------

    def log(self, *options, core='w65c02s', cycles=2000, status=0):
        path = self.dir / 'pc.log'
        st = self.run_a2vm('--pclog', path, *options, core=core,
                           cycles=cycles, status=status,
                           records=[(2, 0xE407, b'\x77')])
        lines = path.read_text().splitlines()
        head = [x for x in lines if x.startswith('#')]
        return st, head, [x.split() for x in lines if not x.startswith('#')]

    def test_pclog_lines(self):
        for core in ('w65c02s', 'py65'):
            st, head, rows = self.log('--pclog-pcs', '80E,800',
                                      '--pclog-bytes', '3000,lc.E407',
                                      core=core)
            self.assertIn('# CLOCK PC A X Y S ALTZP BYTE...', head)
            self.assertGreater(len(rows), 50, core)
            self.assertEqual(rows[0][1], '0800')
            loops = [r for r in rows if r[1] == '080E']
            self.assertEqual(len(loops) + 1, len(rows))
            # the count after each INC, the card's byte, ALTZP off
            self.assertEqual([int(r[7], 16) for r in loops[:5]],
                             [1, 2, 3, 4, 5])
            self.assertTrue(all(len(r) == 9 and r[8] == '77' and r[6] == '0'
                                for r in rows))
            clocks = [int(r[0]) for r in rows]
            self.assertEqual(clocks, sorted(clocks))
            self.assertEqual(st['end'], 'cycles')

    def test_pclog_only_observes(self):
        plain = self.run_a2vm(cycles=50000)
        logged = self.run_a2vm('--pclog', self.dir / 'p.log', '--pclog-pcs',
                               '806,80E', cycles=50000)
        for key in ('host_seconds',):
            plain.pop(key, None)
            logged.pop(key, None)
        self.assertEqual(plain, logged)

    def test_pclog_from_and_limit(self):
        st, _, rows = self.log('--pclog-pcs', '80E', '--pclog-from', '1000')
        self.assertTrue(rows and all(int(r[0]) >= 1000 for r in rows))
        st, _, rows = self.log('--pclog-pcs', '80E', '--pclog-limit', '5',
                               status=1)
        self.assertEqual(len(rows), 5)
        self.assertEqual(st['end'], 'halt')
        self.assertIn('pclog', st['halt'])

    def test_pclog_skipped_idle(self):
        # the log's line comes after the skip: its clock is the VBL's
        st, _, rows = self.log('--pclog-pcs', '806',
                               '--idle', '806:vbl', cycles=3 * FRAME)
        self.assertGreaterEqual(len(rows), 3)
        for r in rows[1:]:
            self.assertEqual(int(r[0]) % FRAME,
                             int(rows[1][0]) % FRAME)

    def test_bad_pclog_options(self):
        self.fails('--pclog-pcs', '800')
        self.fails('--pclog', self.dir / 'x.log')
        self.fails('--pclog', self.dir / 'x.log', '--pclog-pcs', '800',
                   '--pclog-limit', '0')
        self.fails('--pclog', self.dir / 'x.log', '--pclog-pcs', '800',
                   '--pclog-bytes', 'lc.1000')

    # ---- --stop-word ---------------------------------------------------

    def test_stop_word(self):
        # the count starts at $0200 (above 256): the program zeroes it,
        # then counts up to 256
        start = [(0, 0x3000, b'\x00\x02\x00\x00')]
        st = self.run_a2vm('--stop-word', '3000:256', '--pclog',
                           self.dir / 's.log', '--pclog-pcs', '806',
                           '--pclog-bytes', '3000,3001', records=start)
        self.assertEqual(st['end'], 'stop-word')
        last = (self.dir / 's.log').read_text().splitlines()[-1].split()
        self.assertEqual(last[7:], ['FF', '00'])     # the visit before
        # never below: the run goes on to its cycles
        st = self.run_a2vm('--stop-word', '3000:256', records=start,
                           start=LOOP, cycles=20000)
        self.assertEqual(st['end'], 'cycles')
        self.fails('--stop-word', '3000')
        self.fails('--stop-word', 'FFFE:1')


if __name__ == '__main__':
    unittest.main()
