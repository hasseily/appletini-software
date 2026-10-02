"""Part trymove of milestone 10 (docs/GAME.md 2.4 row trymove, wave 4;
docs/game-parts/trymove.md): the move (P_TryMove: the floor, ceiling, step
and drop-off rules, the sector, block and node lists with mvNodes'
shortcut and its LR_USE branch, the crossed special lines) and the
nightmare respawn (P_NightmareRespawn), natively
(src/native/game/trymove/).

What it checks (tools/native/gparts/trymove.py does the work), within the
lean checks the owner asked for on 2026-10-02:

  * the part builds without a warning, within its budget (1,500 B, 10%
    more with a request), and makes no far access (no g_get, g_put,
    far_get or far_put: gameroutine.grep_check);
  * the checkpoint (routine mode, GAME.md 3.5): every SAMPLE-th of the
    chosen captured calls of P_TryMove (40: a cover of the candidates'
    paths) and of P_NightmareRespawn's synthetic calls, from the $A5
    machine under f121, equal to ref816's with the routine exclusions
    only (the line stamps, validcount, the line record, the lists), every
    declared output equal, no stray write;
  * with DOOM_GS_FULL=1: every chosen call under f121 and fastpath, the
    paths they take, and the planted bugs, each built from a scratch copy
    of the part's sources in a temporary directory and failing the
    checkpoint: mvNodes' shortcut without validcount + 1, LR_USE not set
    (the walk stamps the lines), floorz set before the step test.

It skips with the reason when build/ lacks ref816, a2vm, the shared
outputs (`make -s -C src/native -f game.mk shared ROOT=$PWD`; the survey:
`python3 tools/native/gamecap.py --survey`), the level bases (`python3
tools/native/level_check.py --setup`) or the part's own captures
(`python3 tools/native/gparts/trymove.py --capture`). It never rebuilds a
shared output.
"""

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

import trymove as T  # noqa: E402

FULL = os.environ.get('DOOM_GS_FULL') == '1'
SAMPLE = 2


def setUpModule():
    """The part's own case directory (gamecap's CASES is one global, which
    another part's harness may change in the same process)."""
    T.GC.CASES = T.CASES


def why_skip():
    why = T.missing()
    if why:
        return why
    got = T.captured()
    if not got:
        return ('no captures of %s (python3 tools/native/gparts/'
                'trymove.py --capture)' % T.TRYMOVE)
    known = json.loads(T.PATHS_FILE.read_text()).get(T.TRYMOVE, {}) \
        if T.PATHS_FILE.exists() else {}
    if any(str(p) not in known for _, _, p in got):
        return ('the paths of %s are not decoded (python3 tools/native/'
                'gparts/trymove.py --capture)' % T.TRYMOVE)
    return None


WHY = why_skip()


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
        """No g_get, g_put, far_get or far_put at all: every record through
        the object API."""
        from native import gameroutine as GR
        srcs = ('trymove.s', 'nightmare.s')
        for f in srcs:
            words = [GR._code(x) for x in
                     (T.PART_SRC / f).read_text().splitlines()]
            far = [w for w in words if len(w) >= 2 and
                   w[0] in ('jsr', 'jmp') and w[1] in GR.FAR_CALLS]
            self.assertEqual(far, [], f)
        self.assertEqual(GR.grep_check(T.PART_SRC, srcs), [])


@unittest.skipIf(WHY, str(WHY))
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T.build()
        cls.res = T.run_jobs(T.check_jobs(sample=1 if FULL else SAMPLE,
                                          profiles=T.PROFILES if FULL else
                                          T.PROFILES[:1]), 2)

    def test_every_run_equal(self):
        run = [r for r in self.res if not r.get('waiting') and
               not r.get('undecodable')]
        bad = [(r['case'], r.get('profile'), r.get('diff') or
                r.get('error') or r.get('ended')) for r in run
               if not r.get('ok')]
        self.assertEqual(bad, [])
        self.assertEqual(sum(r.get('stray') or 0 for r in run), 0)

    def test_both_entries_ran(self):
        for key in T.ENTRIES:
            with self.subTest(key):
                self.assertTrue([r for r in self.res if r['entry'] == key
                                 and r.get('ok')])

    @unittest.skipUnless(FULL, 'the paths of every chosen call: '
                         'DOOM_GS_FULL=1')
    def test_the_paths_taken(self):
        """The chosen calls move and are refused (by the check, by the
        step), take mvNodes' shortcut, its LR_USE branch and the walk, walk
        the crossed special lines and reach a line's handler, keep and move
        the sector list; the respawns find room and none."""
        paths = set()
        for r in self.res:
            if r.get('ok'):
                paths.update(r.get('path', []))
        for what in ('moved', 'refused', 'nodes-shortcut', 'nodes-lruse',
                     'nodes-walk', 'spec', 'sector-stays', 'sector-moves',
                     'refused-check', 'refused-step', 'reached-lnPlat',
                     'respawned', 'no-room', 'zero-xy'):
            self.assertIn(what, paths)


@unittest.skipIf(WHY, str(WHY))
@unittest.skipUnless(FULL, 'the planted bugs: DOOM_GS_FULL=1')
class Plants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        r = T.plants()
        for name in T.PLANT_NAMES:
            with self.subTest(name):
                self.assertGreater(r[name]['runs'], 0)
                self.assertTrue(r[name]['caught'], name)


if __name__ == '__main__':
    unittest.main()
