"""The menu benchmark on a2vm (docs/speed-parts/bench.md): OPTIONS,
BENCHMARK plays demo3 with timingdemo set at the normal tic rate, counts
the frames drawn, and at the demo's end shows the BENCHMARK page with
FPS = 35000 x frames / realtics as x.xxx (upstream's m_menu65.s bmStart,
bmDone); ESC while it runs stops it with no result (bmStop).

The disk is build/native/DOOM.hdv's with demo3 cut after DEMO_TICS tics
(its end marker there, its length to match: the CRCs are the build's), so
a run reaches the demo's end in seconds. a2vm's input events cannot poke
memory, so the demo is shortened in the disk rather than by moving the
demo pointer. Every run is bounded (playdisk.run) in a directory under
build/ deleted after it.
"""

import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from support import BUILD, ROOT

sys.path.insert(0, str(ROOT / 'tools'))

from native import playdisk as P  # noqa: E402

GONE = P.missing()
WHY = 'build/ lacks: %s' % '; '.join(GONE) if GONE else ''
needs_build = unittest.skipUnless(not GONE, WHY)

FABRIC_HZ = 133333333.33        # the f121 profile's cycles a second
KEY_RETURN, KEY_ESCAPE, KEY_SPACE = 13, 27, 32
DOWN = '0x0A'
DEMO_TICS = 120                 # demo3's tics kept (14 s at today's speed)
HEADER = 13                     # the demo's header bytes (gflow.s)
MARKER = 0x80                   # DEMOMARKER
MSG_BENCH = 16                  # s2_menu.s's messageKind of the page
M_BFPS_SIZE = 8


def at(seconds):
    return 'cycle %d' % int(seconds * FABRIC_HZ)


def fps_text(frames, realtics):
    """bmDone's figure: 35000 x frames / realtics (32 bits, realtics 0 as
    1), at most 999.999, as x.xxx."""
    v = (35000 * frames) & 0xFFFFFFFF
    v = min(v // max(realtics, 1), 999999)
    return '%d.%03d' % (v // 1000, v % 1000)


def short_demob(original, tics):
    """playdisk.demob_segments with demo3 cut after `tics` tics."""
    def segments():
        (bank, at_dir, directory), (bank2, at_lump, data) = original()
        sym, off, index, _, addr = struct.unpack('<HHHHH', directory[1:])
        cut = data[:HEADER + 4 * tics] + bytes([MARKER])
        entry = struct.pack('<HHHHH', sym, off, index, len(cut), addr)
        return [(bank, at_dir, directory[:1] + entry), (bank2, at_lump, cut)]
    return segments


def to_benchmark(t):
    """ESC on the title page (the main menu), DOWN, RETURN (OPTIONS),
    DOWN x 3 (BENCHMARK): a script from t seconds; the snapshot 'menu'
    with BENCHMARK under the skull, then RETURN. Returns (script, the
    time of the RETURN)."""
    s = '%s key %d\n' % (at(t), KEY_ESCAPE)
    s += '%s key %s\n%s key %d\n' % (at(t + 0.5), DOWN, at(t + 1.0),
                                     KEY_RETURN)
    for k in range(3):
        s += '%s key %s\n' % (at(t + 1.5 + 0.5 * k), DOWN)
    s += '%s snapshot menu\n%s key %d\n' % (at(t + 3.2), at(t + 3.5),
                                            KEY_RETURN)
    return s, t + 3.5


@needs_build
class Benchmark(unittest.TestCase):
    """The disk with the short demo3, made once for the class."""

    @classmethod
    def setUpClass(cls):
        if GONE:
            raise unittest.SkipTest(WHY)
        play = P.make()
        cls.tmp = Path(tempfile.mkdtemp(prefix='tmp-bench-test-',
                                        dir=str(BUILD)))
        original = P.demob_segments
        P.demob_segments = short_demob(original, DEMO_TICS)
        try:
            cls.disk = P.build(play, cls.tmp / 'DOOM.hdv')
        finally:
            P.demob_segments = original
        cls.sym = P.symbols(play)
        cls.lab = P.labels(cls.disk)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def play(self, script, seconds):
        work = Path(tempfile.mkdtemp(prefix='run-', dir=str(self.tmp)))
        try:
            return P.run(self.disk, script, work, 'f121', seconds,
                         timeout=900)
        finally:
            shutil.rmtree(str(work), ignore_errors=True)

    def addr(self, name):
        """A symbol of the play build (play.inc: the benchmark's DLM bytes
        among them), else the tic image's label."""
        return self.sym[name] if name in self.sym else self.lab[name]

    def u8(self, mem, name):
        return mem[self.addr(name)]

    def u16(self, mem, name):
        return struct.unpack_from('<H', mem, self.addr(name))[0]

    def u32(self, mem, name):
        return struct.unpack_from('<I', mem, self.addr(name))[0]

    def text(self, mem):
        """M_BFPS (MENUW's state block, in W while the menu is up)."""
        raw = bytes(mem[self.sym['M_BFPS']:self.sym['M_BFPS'] +
                        M_BFPS_SIZE])
        self.assertIn(0, raw)
        return raw[:raw.index(0)].decode('ascii')

    def test_runs_demo3_to_its_result(self):
        """OPTIONS, BENCHMARK closes the menu and plays demo3 (E1M7) with
        timingdemo set; at its end the BENCHMARK page is up (MENUW's
        message MSG_BENCH) with FPS = 35000 x the frames drawn (the views
        since the menu: DL_VIEWS) / the realtics, x.xxx; a key closes it,
        the demo ends and the title loop goes on, timingdemo off."""
        script, go = to_benchmark(7)
        script += '%s snapshot run\n' % at(go + 3)
        script += '%s snapshot result\n' % at(go + 40)
        script += '%s key %d\n%s snapshot after\n' % (at(go + 41), KEY_SPACE,
                                                      at(go + 43))
        run = self.play(script, go + 43.5)
        self.assertEqual(run.state['end'], 'cycles', run.out)
        menu, mid = run.images['menu'][(0, 0)], run.images['run'][(0, 0)]
        res, after = run.images['result'][(0, 0)], run.images['after'][(0, 0)]
        # the menu path started demo3 as a timed demo, the menu closed
        self.assertEqual(self.u8(menu, 'G_MENUACTIVE'), 1)
        self.assertEqual(self.u8(mid, 'G_MENUACTIVE'), 0)
        self.assertEqual(self.u16(mid, 'G_TIMINGDEMO'), 1)
        self.assertEqual(self.u8(mid, 'DL_BENCH'), 1)
        self.assertNotEqual(self.u16(mid, 'G_DEMOPLAY'), 0)
        self.assertEqual(self.u8(mid, 'G_GAMEMAP'), 7)
        self.assertEqual(self.u8(mid, 'G_GAMESTATE'), self.sym['UC_GS_LEVEL'])
        # the result page
        self.assertEqual(self.u8(res, 'G_MENUACTIVE'), 1)
        self.assertEqual(self.u8(res, 'M_MSGPRINT'), 1)
        self.assertEqual(self.u8(res, 'M_MSGKIND'), MSG_BENCH)
        self.assertEqual(self.u16(res, 'G_TIMINGDEMO'), 0)
        self.assertEqual(self.u8(res, 'DL_BENCH'), 0)
        frames = self.u16(res, 'DL_VIEWS') - self.u16(menu, 'DL_VIEWS')
        realtics = self.u32(res, 'DL_BRT')
        self.assertGreater(frames, 5)
        self.assertEqual(self.u16(res, 'DL_BVIEW'), frames)
        # the demo's tics in the realtics (4 at most a frame: MAXTICS)
        self.assertGreaterEqual(realtics, DEMO_TICS // 4)
        self.assertEqual(self.text(res), fps_text(frames, realtics),
                         (frames, realtics))
        # the page closed: the demo ended (the title loop's next step)
        self.assertEqual(self.u8(after, 'G_MENUACTIVE'), 0)
        self.assertEqual(self.u16(after, 'G_TIMINGDEMO'), 0)
        self.assertEqual(self.u8(after, 'DL_BENCH'), 0)
        self.assertEqual(self.u8(after, 'DL_DEMOSEQ'), 1)
        print('\nbenchmark: %d frames, %d realtics, FPS %s'
              % (frames, realtics, self.text(res)))

    def test_escape_stops_it_with_no_result(self):
        """ESC while the benchmark runs: timingdemo off, the demo ended
        (G_CheckDemoStatus: advancedemo), the main menu opens with no
        message; ESC closes it and no result page comes."""
        script, go = to_benchmark(7)
        script += '%s snapshot run\n%s key %d\n%s snapshot esc\n' % (
            at(go + 2.8), at(go + 3), KEY_ESCAPE, at(go + 4))
        script += '%s key %d\n%s snapshot later\n' % (at(go + 5), KEY_ESCAPE,
                                                      at(go + 40))
        run = self.play(script, go + 40.5)
        self.assertEqual(run.state['end'], 'cycles', run.out)
        mid = run.images['run'][(0, 0)]
        esc, later = run.images['esc'][(0, 0)], run.images['later'][(0, 0)]
        self.assertEqual(self.u8(mid, 'DL_BENCH'), 1)
        self.assertNotEqual(self.u16(mid, 'G_DEMOPLAY'), 0)
        self.assertEqual(self.u8(esc, 'G_MENUACTIVE'), 1)
        self.assertEqual(self.u8(esc, 'M_MSGPRINT'), 0)
        self.assertEqual(self.u16(esc, 'G_TIMINGDEMO'), 0)
        self.assertEqual(self.u8(esc, 'DL_BENCH'), 0)
        self.assertEqual(self.u16(esc, 'G_DEMOPLAY'), 0)
        self.assertEqual(self.u8(esc, 'DL_ADVDEMO'), 1)
        self.assertEqual(self.u8(later, 'G_MENUACTIVE'), 0)
        self.assertEqual(self.u16(later, 'G_TIMINGDEMO'), 0)
        self.assertEqual(self.u8(later, 'DL_BENCH'), 0)
        self.assertEqual(self.u32(later, 'DL_BRT'), 0)


if __name__ == '__main__':
    unittest.main()
