"""Milestone 10's tic level (docs/GAME.md 3.6, 5.2-5.4, "Acceptance"): the
lockstep build against ref816 tic by tic (tools/native/ticrun.py), lean
(the default suite's share about a minute; DOOM_GS_FULL=1 runs demo3 to
its end both ways).

  Lockstep    newgame on the ring of commands (the stream: every tic's
              command, the menu's new game) every tic equal; demo3's first
              100 level tics with FRONT frames equal, the same-pair hits
              equal; with DOOM_GS_FULL=1 all of demo3's 2,134
  Full        demo3's first 60 tics with FULL frames: the tics, and the
              records and view of every 10th frame, equal to milestone 8's
              captures; with DOOM_GS_FULL=1 the whole demo
  Plant       part tic's leveltime raised before the specials, built into
              a scratch game image: demo3's run fails
  Timing      newgame on the gprof build under the cost model: a line a
              tic, the tic's time in the subsystems' phases of the PC map
              (a2vm --cost-pcmap), the group loads in the paging's

Each class skips, naming the command that makes what it needs, when
build/ lacks it: the shared outputs (the parallel runner's prebuild), the
tic references with their frame views (`python3 tools/native/ticcap.py
--runs demo3,newgame`), milestone 8's render build and frame captures,
milestone 9's level bases, ref816 and a2vm.
"""

import os
import shutil
import sys
import unittest

import support  # noqa: F401  (puts tools/ on the path)

ROOT = support.ROOT
BUILD = ROOT / 'build'
GAME = BUILD / 'native' / 'game'
SHARED = GAME / 'shared'
RENDER = BUILD / 'native' / 'render'
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
FULL = os.environ.get('DOOM_GS_FULL') == '1'


def missing():
    if not HAVE_CC65:
        return 'cc65 (ca65, ld65) is not installed'
    if not (SHARED / 'gen' / 'ggame.inc').exists():
        return ('the shared outputs: make -s -C src/native -f game.mk shared '
                'skel ROOT=$PWD (the parallel runner\'s prebuild)')
    if not (BUILD / 'a2vm' / 'a2vm').exists():
        return 'a2vm: make -C tools/a2vm'
    if not (RENDER / 'obj' / 'rcard.lbl').exists():
        return 'milestone 8\'s render build (make -f render.mk, rcard)'
    if not (BUILD / 'native' / 'levels' / 'setup').exists():
        return ('milestone 9\'s level bases: python3 tools/native/'
                'level_check.py --setup')
    from native import ticcap as TC
    for run in ('demo3', 'newgame'):
        r = TC.load(run)
        if r is None or 'frame_view' not in r or \
                'digest_front' not in r['tics'][0]:
            return ('the tic reference of %s with its frame views: python3 '
                    'tools/native/ticcap.py --runs %s' % (run, run))
    return None


WHY = missing()


@unittest.skipIf(WHY, WHY or '')
class Lockstep(unittest.TestCase):
    def test_newgame_every_tic(self):
        from native import ticrun
        r = ticrun.run('newgame', (0xA5,), frames='front', jobs=2,
                       say=lambda *a: None)
        f = r['fills']['a5']
        self.assertEqual(f['failures'], 0, f.get('first_failures'))
        self.assertEqual(f['tics_compared'], 512)
        self.assertEqual(f['same_pair_hits']['tics_differing'], [])
        self.assertTrue(r['ok'], f)

    def test_demo3_front(self):
        from native import ticrun
        r = ticrun.run('demo3', (0xA5,), tics=None if FULL else 100,
                       frames='front', jobs=2, say=lambda *a: None)
        f = r['fills']['a5']
        self.assertEqual(f['failures'], 0, f.get('first_failures'))
        self.assertEqual(f['tics_compared'], 2134 if FULL else 100)
        self.assertTrue(r['ok'], f)


@unittest.skipIf(WHY, WHY or '')
class Full(unittest.TestCase):
    def test_demo3_full_frames(self):
        from native import ticrun
        r = ticrun.run('demo3', (0xA5,), tics=None if FULL else 60,
                       frames='full', jobs=2, say=lambda *a: None)
        f = r['fills']['a5']
        self.assertEqual(f['failures'], 0, f.get('first_failures'))
        full = f['full']
        self.assertGreaterEqual(full['frames_compared'], 54 if FULL else 2)
        self.assertEqual(full['frames_compared'], full['frames_scheduled'])
        self.assertEqual(full['failures'], 0, full['first_failures'])
        self.assertTrue(r['ok'], f)


@unittest.skipIf(WHY, WHY or '')
class Plant(unittest.TestCase):
    def test_leveltime_first_is_caught(self):
        from native import ticrun
        r = ticrun.run_plant('demo3-leveltime-first', jobs=2,
                             say=lambda *a: None)
        self.assertTrue(r['caught'], r)
        self.assertGreater(r['failures'], 0)


@unittest.skipIf(WHY, WHY or '')
class Timing(unittest.TestCase):
    def test_newgame_by_subsystem(self):
        from native import ticrun
        t = ticrun.timing('newgame', 'f121', say=lambda *a: None)
        self.assertEqual(t['ended'], 'halt')
        s = ticrun.timing_summary(t)
        self.assertEqual(s['tics'], 512)
        # the PC map gives the tic's time to its subsystems: the walk runs
        # every tic, and every tic's time is in the phases 19-30
        self.assertGreater(s['walk']['median'], 0)
        self.assertGreater(s['object API']['median'], 0)
        self.assertGreater(s['paging']['median'], 0)
        for x in t['tics'][1:50]:
            self.assertAlmostEqual(sum(x['us'][19:31]), x['tic_us'])


if __name__ == '__main__':
    unittest.main()
