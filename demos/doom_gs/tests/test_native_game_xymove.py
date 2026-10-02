"""Part xymove of milestone 10 (docs/GAME.md 2.4 row xymove, wave 5;
docs/game-parts/xymove.md): the horizontal move (P_XYMovement: the clamp,
the half steps of a big move, P_TryMove, the player's slide, a missile into
the sky or a wall, friction and the stop) and the wall slide (slideMove:
the three traces through P_PathTraverse and PTR_SlideTraverse, the move up
to the wall, hitSlideLine, the bobbing's clip, the stairstep), natively
(src/native/game/xymove/).

What it checks (tools/native/gparts/xymove.py does the work), within the
lean checks the owner asked for on 2026-10-02:

  * the part builds without a warning, within its budget (3,100 B, 10%
    more with a request), and makes no far access (no g_get, g_put,
    far_get or far_put in its game sources: gameroutine.grep_check);
  * the checkpoint (routine mode, GAME.md 3.5): every SAMPLE-th of the
    chosen captured calls (40 an entry: a cover of the candidates' paths)
    of P_XYMovement and slideMove, from the $A5 machine under f121, equal
    to ref816's with the routine exclusions only, no stray write;
  * the random checks of friction, bestMul and labs (GAME.md 2.4
    "Arithmetic"): RANDOM inputs each (the edges first) through upstream's
    helper (mathref) and the native one (xy_bulk), equal;
  * with DOOM_GS_FULL=1: every chosen call, the paths they take, 100,000
    random inputs a helper, and the planted bugs, each built from a scratch
    copy of the part's sources in a temporary directory and failing the
    checkpoint: friction in the air, the second trace from the other
    corner, a negative half step rounded down.

It skips with the reason when build/ lacks ref816, a2vm, the shared
outputs (`make -s -C src/native -f game.mk shared ROOT=$PWD`; the survey:
`python3 tools/native/gamecap.py --survey`), mathref (`make -C
tools/native`) or the part's own captures (`python3
tools/native/gparts/xymove.py --capture`). It never rebuilds a shared
output.
"""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

import xymove as X  # noqa: E402

FULL = os.environ.get('DOOM_GS_FULL') == '1'
SAMPLE = 4
RANDOM = 100_000


def setUpModule():
    """The part's own case directory (gamecap's CASES is one global, which
    another part's harness may change in the same process)."""
    X.GC.CASES = X.CASES


def why_skip():
    why = X.missing()
    if why:
        return why
    if not (X.GC.SURVEY / 'demo1.json.z').exists():
        return ('no survey (python3 tools/native/gamecap.py --survey)')
    import sight
    if not sight.MATHREF.exists():
        return 'no mathref (make -C tools/native)'
    for key in X.ENTRIES:
        if not X.captured(key):
            return ('no captures of %s (python3 tools/native/gparts/'
                    'xymove.py --capture)' % key)
    if not X.PATHS_FILE.exists():
        return ('the candidates\' paths are not decoded (python3 '
                'tools/native/gparts/xymove.py --capture)')
    return None


WHY = why_skip()


@unittest.skipIf(X.missing(), str(X.missing()))
class Build(unittest.TestCase):
    def test_builds_within_its_budget(self):
        X.build()
        sz = X.sizes()
        self.assertGreater(sz['bytes'], 0)
        self.assertLessEqual(sz['bytes'], sz['budget'] * 11 // 10, sz)
        for name in X.LABELS:
            self.assertIn(name, sz['groups'], name)

    def test_no_far_access(self):
        """No g_get, g_put, far_get or far_put in the game sources: every
        record through the object API (xytest.s, test-only code in the
        driver's area, reads its input banks)."""
        from native import gameroutine as GR
        srcs = ('xymove.s', 'slide.s')
        for f in srcs:
            words = [GR._code(x) for x in
                     (X.PART_SRC / f).read_text().splitlines()]
            far = [w for w in words if len(w) >= 2 and
                   w[0] in ('jsr', 'jmp') and w[1] in GR.FAR_CALLS]
            self.assertEqual(far, [], f)
        self.assertEqual(GR.grep_check(X.PART_SRC, srcs), [])


@unittest.skipIf(WHY, str(WHY))
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        X.build()
        cls.res = X.run_jobs(X.check_jobs(
            sample=1 if FULL else SAMPLE,
            profiles=X.PROFILES if FULL else X.PROFILES[:1]), 2)

    def test_every_run_equal(self):
        run = [r for r in self.res if not r.get('waiting') and
               not r.get('undecodable')]
        bad = [(r['case'], r.get('profile'), r.get('diff') or
                r.get('error') or r.get('ended')) for r in run
               if not r.get('ok')]
        self.assertEqual(bad, [])
        self.assertEqual(sum(r.get('stray') or 0 for r in run), 0)

    def test_both_entries_ran(self):
        for key in X.ENTRIES:
            with self.subTest(key):
                self.assertTrue([r for r in self.res if r['entry'] == key
                                 and r.get('ok')])

    @unittest.skipUnless(FULL, 'the paths of every chosen call: '
                         'DOOM_GS_FULL=1')
    def test_the_paths_taken(self):
        """The chosen calls move the player, things, corpses and missiles;
        take the half steps; slide with and without a hit; explode a
        missile; stop and apply friction; the slides turn, clip the bob
        and slide along angled lines."""
        paths = set()
        for r in self.res:
            if r.get('ok'):
                paths.update(r.get('path', []))
        for what in ('player', 'missile', 'thing', 'half', 'slide-hit',
                     'slide-nohit', 'exploded', 'stopped', 'friction',
                     'air', 'turns-1', 'turns-2', 'nothing-hit', 'slid',
                     'angled-line', 'axis-line'):
            self.assertIn(what, paths)


@unittest.skipIf(WHY, str(WHY))
class Random(unittest.TestCase):
    def test_helpers_equal_upstream(self):
        X.build()
        r = X.random_check(RANDOM)
        for name, x in r.items():
            with self.subTest(name):
                self.assertEqual(x['compared'], RANDOM)
                self.assertEqual(x['different'], 0, x['first'])


@unittest.skipIf(WHY, str(WHY))
@unittest.skipUnless(FULL, 'the planted bugs: DOOM_GS_FULL=1')
class Plants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        r = X.plants()
        for name in X.PLANT_NAMES:
            with self.subTest(name):
                self.assertGreater(r[name]['runs'], 0)
                self.assertTrue(r[name]['caught'], name)


if __name__ == '__main__':
    unittest.main()
