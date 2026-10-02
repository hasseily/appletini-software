"""Part attack of milestone 10 (docs/GAME.md 2.2 TRVTAB, 2.4 row attack,
wave 5; docs/game-parts/attack.md): the hitscan attacks (P_LineAttack,
P_AimLineAttack), their traversers (PTR_ShootTraverse, PTR_AimTraverse),
the gun special (shootSpecial), the puff's place (puffPos) and the
products mul3 and rangeMul, natively (src/native/game/attack/).

What it checks (tools/native/gparts/attack.py does the work), within the
lean checks the owner asked for on 2026-10-02:

  * the part builds without a warning, within its budget (2,500 B, 10%
    more with a request), and makes no far access (no g_get, g_put,
    far_get or far_put: gameroutine.grep_check);
  * the checkpoint (routine mode, GAME.md 3.5): every SAMPLE-th of the
    chosen captured calls of P_LineAttack and P_AimLineAttack (40 each: a
    cover of the candidates' paths) and of the synthetic shots (into the
    sky, at a gun-activated line, along a wall), from the $A5 machine
    under f121, equal to ref816's with the routine exclusions only, every
    declared output equal (aimslope, la_damage, attackrange, shootz,
    shootthing, the aim's slopes, linetarget and result), no stray write;
  * rangeMul's and mul3's random checks: 100,000 inputs each (0, +-1, the
    extremes, the two shift ranges, random values) against upstream's
    helpers on ref816 (mathref batch), no difference;
  * the planted bugs (the lean rules: three), each built from a scratch
    copy of the part's sources in a temporary directory, failing the
    checkpoint on a few calls that take its path: the aim's top and bottom
    slopes swapped, the puff 4 units early taken away, a gun special on a
    line that is not one;
  * with DOOM_GS_FULL=1: every chosen call under f121 and fastpath, the
    paths they take, and the planted bugs (with damage before blood) on
    every chosen call.

It skips with the reason when build/ lacks ref816, a2vm, the shared
outputs (`make -s -C src/native -f game.mk shared ROOT=$PWD`; the survey:
`python3 tools/native/gamecap.py --survey`), the level bases (`python3
tools/native/level_check.py --setup`), mathref (`make -C tools/native`) or
the part's own captures (`python3 tools/native/gparts/attack.py
--capture`). It never rebuilds a shared output.
"""

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

import attack as T  # noqa: E402

FULL = os.environ.get('DOOM_GS_FULL') == '1'
SAMPLE = 4


def setUpModule():
    """The part's own case directory (gamecap's CASES is one global, which
    another part's harness may change in the same process)."""
    T.GC.CASES = T.CASES


def why_skip():
    why = T.missing()
    if why:
        return why
    known = json.loads(T.PATHS_FILE.read_text()) \
        if T.PATHS_FILE.exists() else {}
    for key in T.ENTRIES:
        got = T.captured(key)
        if not got:
            return ('no captures of %s (python3 tools/native/gparts/'
                    'attack.py --capture)' % key)
        if any(str(p) not in known.get(key, {}) for _, _, p in got):
            return ('the paths of %s are not decoded (python3 tools/native/'
                    'gparts/attack.py --capture)' % key)
    return None


WHY = why_skip()
SG_MATHREF = ROOT / 'build' / 'native' / 'math' / 'mathref'


@unittest.skipIf(T.missing(), str(T.missing()))
class Build(unittest.TestCase):
    def test_builds_within_its_budget(self):
        T.build()
        sz = T.sizes()
        self.assertGreater(sz['bytes'], 0)
        self.assertLessEqual(sz['bytes'], sz['budget'] * 11 // 10, sz)
        for name in T.LABELS:
            self.assertIn(name, sz['routines'], name)

    def test_no_far_access(self):
        """No g_get, g_put, far_get or far_put in the game code: every
        record through the object API (aktest.s, test-only in the
        driver's area, moves its bulk records with far_get and far_put)."""
        from native import gameroutine as GR
        srcs = ('attack.s',)
        for f in srcs:
            words = [GR._code(x) for x in
                     (T.PART_SRC / f).read_text().splitlines()]
            far = [w for w in words if len(w) >= 2 and
                   w[0] in ('jsr', 'jmp') and w[1] in GR.FAR_CALLS]
            self.assertEqual(far, [], f)
        self.assertEqual(GR.grep_check(T.PART_SRC, srcs), [])

    def test_traversers_in_trvtab(self):
        """TRVTAB's entries 1 and 2 are the part's traversers, and the
        image's table names them (the part's image counts it built)."""
        T.build()
        b = T.G.load_build(T.OUT, T.IMAGE)
        consts = dict(T.GL.constants())
        self.assertEqual(consts['TRVTAB_PTR_AimTraverse'], 1)
        self.assertEqual(consts['TRVTAB_PTR_ShootTraverse'], 2)
        table = (T.OUT / 'gen' / 'gdisp.inc').read_text()
        table = table.split('TRVTAB:', 1)[1].splitlines()
        for k, name in ((0, 'PTR_AimTraverse'), (1, 'PTR_ShootTraverse')):
            self.assertIn('<%s, >%s' % (name, name), table[k + 1])
            self.assertIn(name, b.labels)


@unittest.skipIf(WHY, str(WHY))
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T.build()
        cls.res = T.run_jobs(T.check_jobs(sample=1 if FULL else SAMPLE,
                                          profiles=T.PROFILES if FULL else
                                          T.PROFILES[:1]), 2)

    def test_every_run_equal(self):
        run = [r for r in self.res if not r.get('waiting')]
        bad = [(r['case'], r.get('profile'), r.get('diff') or
                r.get('error') or r.get('ended')) for r in run
               if not r.get('ok')]
        self.assertEqual(bad, [])
        self.assertEqual(sum(r.get('stray') or 0 for r in run), 0)
        self.assertEqual([r['case'] for r in self.res if r.get('waiting')],
                         [])

    def test_both_entries_and_the_synthetic_shots_ran(self):
        for key in T.ENTRIES:
            with self.subTest(key):
                self.assertTrue([r for r in self.res if r['entry'] == key
                                 and r.get('ok')])
        synth = {r['case'].split()[0] for r in self.res
                 if r['case'].startswith('synthetic') and r.get('ok')}
        for kind in ('synthetic:sky', 'synthetic:gun-line',
                     'synthetic:along-wall'):
            self.assertIn(kind, synth)

    @unittest.skipUnless(FULL, 'the paths of every chosen call: '
                         'DOOM_GS_FULL=1')
    def test_the_paths_taken(self):
        """The shots of the player and of monsters make puffs and blood,
        none (into the sky), damage and kill (one a thing with no blood),
        cross special lines and start a door at a gun line; the aims find a
        target and none, narrow the window's top and bottom, aim up and
        down."""
        paths = set()
        for r in self.res:
            if r.get('ok'):
                paths.update(r.get('path', []))
        for what in ('player', 'monster', 'puff', 'blood', 'no-spawn',
                     'damage', 'kill', 'noblood-damage', 'special-tic',
                     'started-door', 'sky', 'gun-line', 'along-wall',
                     'target', 'no-target', 'top-narrowed',
                     'bottom-narrowed', 'slope-up', 'slope-down'):
            self.assertIn(what, paths)


@unittest.skipIf(WHY, str(WHY))
class Random(unittest.TestCase):
    @unittest.skipUnless(SG_MATHREF.exists(),
                         'no mathref (make -C tools/native)')
    def test_range_mul_and_mul3(self):
        T.build()
        r = T.random_check(100_000)
        for name in ('rangeMul', 'mul3'):
            with self.subTest(name):
                self.assertEqual(r[name]['compared'], 100_000)
                self.assertEqual(r[name]['different'], 0, r[name]['first'])


@unittest.skipIf(WHY, str(WHY))
class Plants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        names = T.PLANT_NAMES if FULL else T.DEFAULT_PLANTS
        r = T.plants(names, targeted=not FULL)
        for name in names:
            with self.subTest(name):
                self.assertGreater(r[name]['runs'], 0)
                self.assertTrue(r[name]['caught'], name)


if __name__ == '__main__':
    unittest.main()
