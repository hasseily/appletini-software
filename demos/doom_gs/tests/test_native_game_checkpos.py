"""Part checkpos of milestone 10 (docs/GAME.md 2.4 row checkpos, wave 3;
docs/game-parts/checkpos.md): whether a thing fits at a place
(P_CheckPosition, checkPos: the box, the point's floor and ceiling, the
things' walk with PIT_CheckThing, the lines' walk with PIT_CheckLine,
spechit and the line record), natively (src/native/game/checkpos/).

What it checks (tools/native/gparts/checkpos.py does the work), within
the lean checks the owner asked for on 2026-10-02:

  * the part builds without a warning, within its budget (2,600 B, 10%
    more with a request), and makes no far access of a cached kind's bank
    (gameroutine.grep_check);
  * the checkpoint (routine mode, GAME.md 3.5): every SAMPLE-th of the
    chosen captured calls of each entry (40 an entry: a cover of the
    candidates' paths), from the $A5 machine under f121, equal to
    ref816's with the routine exclusions only, every declared output
    equal (the result; tmfloorz, tmceilingz, tmdropoffz; numspechit and
    spechit; ceilingline; the line record), no stray write;
  * with DOOM_GS_FULL=1: every chosen call under f121 and fastpath, and
    the planted bugs, each built from a scratch copy of the part's
    sources in a temporary directory and failing the checkpoint: the
    lines' block walk with y outer, the line record not kept (LR_OK), the
    lines walked before the things.

It skips with the reason when build/ lacks ref816, a2vm, the shared
outputs (`make -s -C src/native -f game.mk shared ROOT=$PWD`; the survey:
`python3 tools/native/gamecap.py --survey`), the level bases (`python3
tools/native/level_check.py --setup`) or the part's own captures
(`python3 tools/native/gparts/checkpos.py --capture`). It never rebuilds a
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

import checkpos as C  # noqa: E402

FULL = os.environ.get('DOOM_GS_FULL') == '1'
SAMPLE = 10


def setUpModule():
    """The part's own case directory (gamecap's CASES is one global, which
    another part's harness may change in the same process)."""
    C.GC.CASES = C.CASES


def why_skip():
    why = C.missing()
    if why:
        return why
    known = json.loads(C.PATHS_FILE.read_text()) \
        if C.PATHS_FILE.exists() else {}
    for key in C.ENTRIES:
        got = C.captured(key)
        if not got:
            return ('no captures of %s (python3 tools/native/gparts/'
                    'checkpos.py --capture)' % key)
        if any(str(p) not in known.get(key, {}) for _, _, p in got):
            return ('the paths of %s are not decoded (python3 tools/native/'
                    'gparts/checkpos.py --capture)' % key)
    return None


WHY = why_skip()


@unittest.skipIf(C.missing(), str(C.missing()))
class Build(unittest.TestCase):
    def test_builds_within_its_budget(self):
        C.build()
        sz = C.sizes()
        self.assertGreater(sz['bytes'], 0)
        self.assertLessEqual(sz['bytes'], sz['budget'] * 11 // 10, sz)
        for name in C.LABELS:
            self.assertIn(name, sz['routines'], name)

    def test_no_far_access(self):
        """No g_get, g_put, far_get or far_put at all: every record through
        the object API."""
        from native import gameroutine as GR
        words = [GR._code(x) for x in
                 (C.PART_SRC / 'checkpos.s').read_text().splitlines()]
        far = [w for w in words if len(w) >= 2 and w[0] in ('jsr', 'jmp')
               and w[1] in GR.FAR_CALLS]
        self.assertEqual(far, [])
        self.assertEqual(GR.grep_check(C.PART_SRC, ('checkpos.s',)), [])


@unittest.skipIf(WHY, str(WHY))
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        C.build()
        cls.res = C.run_jobs(C.check_jobs(sample=1 if FULL else SAMPLE,
                                          profiles=C.PROFILES if FULL else
                                          C.PROFILES[:1]), 2)

    def test_every_run_equal(self):
        run = [r for r in self.res if not r.get('waiting')]
        bad = [(r['case'], r.get('profile'), r.get('diff') or
                r.get('error') or r.get('ended')) for r in run
               if not r.get('ok')]
        self.assertEqual(bad, [])
        self.assertEqual(sum(r.get('stray') or 0 for r in run), 0)

    def test_both_entries_ran(self):
        for key in C.ENTRIES:
            with self.subTest(key):
                self.assertTrue([r for r in self.res if r['entry'] == key
                                 and r.get('ok')])

    @unittest.skipUnless(FULL, 'the paths of every chosen call: '
                         'DOOM_GS_FULL=1')
    def test_the_paths_taken(self):
        """The chosen calls fit and are blocked by a thing and by a line,
        cross special lines, keep a record and walk more than one column
        and row of blocks."""
        paths = set()
        for r in self.res:
            if r.get('ok'):
                paths.update(r.get('path', []))
        for what in ('fits', 'blocked', 'thing-block', 'line-block', 'try',
                     'notry', 'spechit-1', 'lr-1', 'blocks-2x2',
                     'checkthing', 'ceilingline'):
            self.assertIn(what, paths)


@unittest.skipIf(WHY, str(WHY))
@unittest.skipUnless(FULL, 'the planted bugs: DOOM_GS_FULL=1')
class Plants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        r = C.plants()
        for name in C.PLANT_NAMES:
            with self.subTest(name):
                self.assertGreater(r[name]['runs'], 0)
                self.assertTrue(r[name]['caught'], name)


if __name__ == '__main__':
    unittest.main()
