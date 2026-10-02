"""Milestone 10, wave 6: part tic's checkpoint (docs/GAME.md 2.4, 3.5;
docs/game-parts/tic.md; the harness is tools/native/gparts/tic.py), lean
(the owner's rules of 2026-10-02: the default suite's share under 60 s,
the rest with DOOM_GS_FULL=1).

  Build       the part's image builds with no warning; the part's code
              within 1.1 x its budget (1,500 B); THTAB's P_MobjThinker
              entry names it; the driver's entries g_ttick and g_tresume
              are in the card's driver area; no far access (every record
              through the object API)
  Checkpoint  routine mode on the part's image, fill $A5, f121: by
              default every 10th case of each entry (at least one:
              G_Ticker, P_Ticker, P_RunThinkers, P_MobjThinker, P_MapEnd)
              the paused tic and G_Ticker's four loads (the load
              protocol: GT_LOAD, G_LOADACT, the driver's load, g_tresume,
              the action loop again, WI_End, the new level's tic);
              with DOOM_GS_FULL=1 every selected case (at most 40 an
              entry): the canonical state equal to ref816's, every declared
              output equal (P_MapEnd's tmthing; onground), no stray write,
              the native-only globals consistent
  Plants      (DOOM_GS_FULL=1) each planted bug, made in a scratch copy of
              the part's sources, fails its named check: the walk reading
              a special's next after its turn (P_RunThinkers' removals of a
              special), leveltime raised before the specials (P_Ticker's 8
              consecutive tics), the ring's command copied while paused
              (the paused tic)

The full checkpoint is `python3 tools/native/gparts/tic.py --check
--plants` (report.json).

Each class skips, naming the command that makes what it needs, when
build/ lacks it: the shared outputs (`make -s -C src/native -f game.mk
shared skel ROOT=$PWD`, the parallel runner's prebuild; never made here),
the survey (`python3 tools/native/gamecap.py --survey`), milestone 9's
level bases (`python3 tools/native/level_check.py --setup`), ref816 and
a2vm (`make -C tools/ref816`, `make -C tools/a2vm`), the part's captures
and reference calls (`python3 tools/native/gparts/tic.py --capture
--synth`).
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
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
PREBUILD = ('make -s -C src/native -f game.mk shared skel ROOT=$PWD (the '
            'parallel runner\'s prebuild)')
FULL = os.environ.get('DOOM_GS_FULL') == '1'


def shared_ok() -> bool:
    """The shared outputs, and newer than the layouts that make them."""
    inc = SHARED / 'gen' / 'ggame.inc'
    if not (HAVE_CC65 and inc.exists() and
            (SHARED / 'native-game-1.json').exists() and
            (SHARED / 'gen' / 'gplace.inc').exists() and
            (BUILD / 'native' / 'levels' / 'store' / 'store.json').exists()):
        return False
    t = inc.stat().st_mtime
    return all(t >= (ROOT / 'tools' / 'native' / f).stat().st_mtime
               for f in ('glayout.py', 'llayout.py'))


def captures_ok() -> bool:
    import tic as T
    gt = [c for _, _, c in T.case_paths(T.GT)]
    return all(T.case_paths(key) for key in T.ENTRIES) and \
        'synthetic: paused' in gt and \
        len([c for c in gt if c.startswith('load: ')]) == len(T.LOAD_RUNS)


def all_ok() -> bool:
    if not shared_ok():
        return False
    import tic as T
    try:
        return T.missing() is None and captures_ok()
    except T.PartError:
        return False


needs_shared = unittest.skipUnless(
    shared_ok(), 'needs the shared outputs, newer than tools/native/'
    'glayout.py and llayout.py: ' + PREBUILD + ', and milestone 9\'s store '
    '(python3 tools/native/wadconv.py --store)')
needs_all = unittest.skipUnless(
    all_ok(),
    'needs the shared outputs (' + PREBUILD + '), ref816 and a2vm (make -C '
    'tools/ref816; make -C tools/a2vm), the survey (python3 tools/native/'
    'gamecap.py --survey), milestone 9\'s level bases (python3 tools/'
    'native/level_check.py --setup) and the part\'s captures and reference '
    'calls (python3 tools/native/gparts/tic.py --capture --synth)')
needs_full = unittest.skipUnless(
    FULL, 'the heavier checks run with DOOM_GS_FULL=1 (the owner\'s lean '
    'rules of 2026-10-02)')


def setUpModule():
    if shared_ok():
        import tic as T
        import mobjstate as MS
        MS.use_cases(T.MYCASES)


@needs_shared
class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tic as T
        cls.b = T.load(T.build())
        cls.sizes = T.sizes(cls.b)

    def test_the_image_builds_within_its_budget(self):
        import tic as T
        for m in T.MODULES:
            self.assertGreater(self.sizes['modules'][m], 0, m)
        self.assertLessEqual(self.sizes['part_bytes'], T.BUDGET * 11 // 10)
        for name in ('G_Ticker', 'P_MapEnd', 'P_Ticker', 'P_RunThinkers',
                     'P_MobjThinker', 'gt_loop', 'g_ttick', 'g_tresume'):
            self.assertIn(name, self.b.labels)

    def test_the_resumption_is_the_drivers(self):
        """g_ttick and g_tresume, which the lockstep driver calls with no
        paging (dg_ticker, dg_resume), are in the card's driver area."""
        lo, hi = self.b.segments['DRIVER']
        for name in ('g_ttick', 'g_tresume'):
            self.assertTrue(lo <= self.b.labels[name] <= hi, name)

    def test_p_mobjthinker_is_in_thtab(self):
        text = (self.b.obj / 'gen' / 'gdisp.inc').read_text()
        self.assertIn('<P_MobjThinker, >P_MobjThinker', text)

    def test_no_far_access(self):
        """The part's sources call no g_get, g_put, far_get or far_put."""
        from native import gameroutine as GR
        src = GR.SRC / 'game' / 'tic'
        for p in sorted(src.glob('*.s')):
            words = [GR._code(x) for x in p.read_text().splitlines()]
            far = [w for w in words if len(w) >= 2 and w[0] in ('jsr', 'jmp')
                   and w[1] in GR.FAR_CALLS]
            self.assertEqual(far, [], p.name)
        self.assertEqual(GR.grep_check(src, ()), [])


@needs_all
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tic as T
        T.build()
        cls.rep = T.check(jobs=2, sample=1 if FULL else 10)

    def test_no_failure_and_no_stray_write(self):
        bad = {k: e['first_failures'] for k, e in self.rep['entries'].items()
               if e['failures']}
        self.assertEqual(bad, {})
        self.assertEqual(self.rep['failures'], 0)
        self.assertEqual(self.rep['strays'], 0)

    def test_every_entry_ran(self):
        import tic as T
        for key in T.ENTRIES:
            with self.subTest(key):
                e = self.rep['entries'].get(key)
                self.assertIsNotNone(e)
                self.assertGreater(e['run'], 0)

    def test_the_paused_tic_and_the_loads_ran(self):
        import tic as T
        classes = self.rep['entries'][T.GT]['classes']
        for cls in ('synthetic: paused', 'load: doNewGame',
                    'load: doWorldDone', 'load: doPlayDemo'):
            self.assertIn(cls, classes)


@needs_all
@needs_full
class Plants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        import tic as T
        for name in T.PLANTS:
            with self.subTest(name):
                r = T.run_plant(name)
                self.assertGreater(r['runs'], 0)
                self.assertTrue(r['caught'], '%s was not caught by %s' % (
                    name, r['check']))


if __name__ == '__main__':
    unittest.main()
