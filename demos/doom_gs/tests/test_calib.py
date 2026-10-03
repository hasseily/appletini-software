"""tools/native/calibdisk.py and src/native/calib.s: CALIB.hdv, the
calibration disk (docs/results/calib.md, docs/SPEED.md 5).

Reading (no build): the two timers' arithmetic (calib.s t_elapsed, the
host's `elapsed`) over random start phases, VIA-B's wraps up to 16 s and
the read offsets a retaken read leaves; the screen's numbers; the
window's names.

The program (skipped without the play build, cc65 or a2vm), built with
zero predictions into a private directory and run on a2vm f121 (the
game's profile: the Phasor's window of 32, --via-timers, the exact core,
the model's clock): it ends on its screen and calibdisk.check finds
nothing (every line measured, the timers agreeing; each E the host's from
the timer reads and a2vm's clock between the reads; the PC log's unit
calls equal to the n and 2n the arithmetic used; the figures and the
screen the host's computation; the game's bytes in the card and page 1).
REG's and SPIN's cycle constants equal a2vm's core. One planted bug, the
second measurement running 4n units while the arithmetic assumes 2n, is
caught. The disk (skipped when build/native/CALIB.hdv is missing): its
CALIB.SYSTEM is this build's but for the predictions, boots on a2vm f121,
passes the same checks, and shows in its A2VM column the figures it
measures there. Every run is bounded; about 30 s in all.
"""

import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from support import ROOT

sys.path.insert(0, str(ROOT / 'tools'))

from native import calibdisk as C  # noqa: E402

PLANT_ANCHOR = '''        jsr measure
        ldy #R_TS2
'''
PLANT = '''        asl cnt                 ; (planted: 4n units, not 2n)
        rol cnt + 1
        jsr measure
        ldy #R_TS2
'''


def missing():
    out = []
    if not (C.PLAY / 'tic' / 'tic.core').exists():
        out.append('build/native/play (python3 tools/native/playdisk.py)')
    if not C.A2VM.exists():
        out.append('build/a2vm/a2vm (make -C tools/a2vm)')
    if shutil.which('ca65') is None or shutil.which('ld65') is None:
        out.append('cc65 (ca65, ld65)')
    return out


def reading(latch, start, t):
    """A 6522 timer 1 free-running with `latch`, at `start` (a counter
    value), after t bus cycles: N, N-1 ... 0, $FFFF, then the latch."""
    period = latch + 2
    pos = (start if start != 0xFFFF else latch + 1)
    pos = (pos - t) % period
    return 0xFFFF if pos == latch + 1 else pos


class Arithmetic(unittest.TestCase):

    def reads(self, b0, a0, e, lag_start=0, lag_end=0):
        ts = bytearray(8)
        for at, value in ((0, b0), (2, a0), (4, reading(0xFFFE, b0, e)),
                          (6, reading(0xFEFE, a0, e + lag_end - lag_start))):
            ts[at] = value & 0xFF
            ts[at + 1] = value >> 8
        return bytes(ts)

    def test_wraps_and_phases(self):
        rng = random.Random(1)
        for _ in range(4000):
            e = rng.choice([rng.randrange(1, 300),
                            rng.randrange(1, 70000),
                            rng.randrange(1, 254 * 65536 - 2000)])
            b0 = rng.randrange(0x10000)
            a0 = rng.choice([rng.randrange(0xFEFF), 0xFFFF])
            lag = rng.randrange(-16, 17)
            got, dlt, bad = C.elapsed(self.reads(b0, a0, e, 0, lag))
            self.assertEqual((got, dlt, bad), (e, lag, 0), (e, b0, a0, lag))

    def test_disagreement_is_bad(self):
        _, dlt, bad = C.elapsed(self.reads(0x1234, 0x4321, 50000, 0, 40))
        self.assertEqual((dlt, bad), (40, 1))

    def test_numbers(self):
        self.assertEqual(C.fix(47, 9), '    0.047')
        self.assertEqual(C.fix(510495, 9), '  510.495')
        self.assertEqual(C.fix(0, 7), '  0.000')
        self.assertEqual(C.fix(123456789, 9), '123456.789')
        self.assertEqual(C.integer(20280), '20280')
        self.assertEqual(C.integer(0), '0')
        self.assertEqual(C.window_text(325, 0), '32')
        self.assertEqual(C.window_text(5130, 0), '512')
        self.assertEqual(C.window_text(3, 0), 'NONE')
        self.assertEqual(C.window_text(1004, 0), '100')
        self.assertEqual(C.window_text(1005, 0), '101')
        self.assertEqual(C.window_text(0, 1), '?')


@unittest.skipIf(missing(), 'calib: build/ lacks %s' % '; '.join(missing()))
class Program(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='tmp-calib-test-',
                                        dir=str(C.BUILD)))
        try:
            cls.parts = C.play_parts()
            cls.gen = cls.tmp / 'gen'
            C.write_gen(cls.parts, gen=cls.gen)
            cls.prog = C.make(cls.tmp / 'obj', cls.gen)
            cls.run_ = C.run(cls.prog, 'f121', cls.tmp / 'f121')
        except BaseException:       # (tearDownClass does not run then)
            shutil.rmtree(str(cls.tmp), ignore_errors=True)
            raise

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_every_line_runs_and_checks(self):
        self.assertEqual(C.check(self.prog, self.run_, self.parts), [])
        res = C.results(self.prog, self.run_)
        self.assertEqual(len(res.recs), C.NOPS)
        self.assertTrue(all(r.err == 0 and r.v > 0 for r in res.recs))
        self.assertEqual(C.window_text(res.w10, res.wbad), '32')
        screen = C.screen_of(self.run_)
        self.assertTrue(screen[0].startswith('CALIB PAL 20280  WIN 32  '),
                        screen[0])
        # each E(n) about 55,000 bus cycles on f121, the reads' window
        # (512 cycles at most) under 1% of it
        for op, rec in zip(res.ops, res.recs):
            self.assertGreater(rec.e1, 51200, op.name)
            self.assertLess(rec.e2, 254 * 65536, op.name)

    def test_cycle_constants(self):
        got = C.core_cycles(self.prog, self.tmp / 'core')
        self.assertEqual(got, {'REG': C.UC_REG, 'SPIN': C.UC_SPIN})
        text = (C.SOURCE / 'calib.s').read_text()
        self.assertIn('UC_REG      = %d' % C.UC_REG, text)
        self.assertIn('UC_SPIN     = %d' % C.UC_SPIN, text)

    def test_planted_count_is_caught(self):
        text = (C.SOURCE / 'calib.s').read_text()
        self.assertEqual(text.count(PLANT_ANCHOR), 1)
        src = self.tmp / 'plant' / 'calib.s'
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(text.replace(PLANT_ANCHOR, PLANT))
        prog = C.make(self.tmp / 'plant' / 'obj', self.gen, src)
        r = C.run(prog, 'f121', self.tmp / 'plant' / 'run')
        bad = C.check(prog, r, self.parts)
        self.assertTrue(any('the arithmetic assumed' in b for b in bad), bad)
        # and the figures it shows are three times the right ones
        good = C.results(self.prog, self.run_).recs[C.OP_REG].v
        self.assertAlmostEqual(C.results(prog, r).recs[C.OP_REG].v / good,
                               3.0, delta=0.05)

    @unittest.skipUnless(C.OUT.exists(), 'build/native/CALIB.hdv is '
                         'missing: python3 tools/native/calibdisk.py')
    def test_the_disk(self):
        system = C.disk_system(C.OUT)
        lab = self.prog.labels
        at = lab['pred_v'] - 0x2000
        size = 4 * C.NOPS
        mine = self.prog.system
        self.assertEqual(len(system), len(mine))
        self.assertEqual(system[:at] + system[at + size:],
                         mine[:at] + mine[at + size:],
                         'CALIB.hdv is stale: python3 tools/native/'
                         'calibdisk.py')
        prog = C.Program(self.prog.obj, system, lab)
        pred = [C.u32(system, at + 4 * i) for i in range(C.NOPS)]
        r = C.run(prog, 'f121', self.tmp / 'disk')
        self.assertEqual(C.check(prog, r, self.parts, pred), [])
        self.assertEqual([x.v for x in C.results(prog, r).recs], pred)


if __name__ == '__main__':
    unittest.main()
