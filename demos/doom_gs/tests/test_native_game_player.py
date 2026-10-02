"""Milestone 10, wave 5: part player's checkpoint (docs/GAME.md 2.4, 3.5;
docs/game-parts/player.md; the harness is tools/native/gparts/player.py),
lean (the owner's rules of 2026-10-02: the default suite's share under
60 s, the rest with DOOM_GS_FULL=1).

  Build       the part's image builds with no warning; the part's code
              within 1.1 x its budget (2,800 B: over 10% is reported in
              docs/game-parts/player.md with its reasons); TRVTAB's two
              entries name the traversers; no far access of the part's
              own but the test routine's (every record through the object
              API)
  Checkpoint  routine mode on the part's image, fill $A5, f121: by
              default one captured call of each entry (P_PlayerThink,
              specialSector, angleToAttacker, P_UseLines) and the
              synthetic squat and E1M8 at health 10; with DOOM_GS_FULL=1
              every selected call (at most 40 a routine) and every
              synthetic case: the canonical state equal to ref816's, every
              declared output equal (onground, the angle), no stray write,
              the native-only globals consistent
  Random      thrustMul, fixedSquare, times64 and hurt32 against upstream's
              helpers on ref816 (mathref): 100,000 inputs each (about 7 s)
  Plants      (DOOM_GS_FULL=1) each planted bug, made in a scratch copy of
              the part's sources, fails its named check: the view height
              clamped before adding the delta (the squat), special 11
              exiting at health 11 (E1M8 at health 11), the bob's square
              without its last carry (fixedSquare's random check)

The full checkpoint is `python3 tools/native/gparts/player.py --check
--random --plants` (report.json).

Each class skips, naming the command that makes what it needs, when
build/ lacks it: the shared outputs (`make -s -C src/native -f game.mk
shared skel ROOT=$PWD`, the parallel runner's prebuild; never made here),
the survey (`python3 tools/native/gamecap.py --survey`), milestone 9's
level bases (`python3 tools/native/level_check.py --setup`), ref816, a2vm
and mathref (`make -C tools/ref816`, `make -C tools/a2vm`, `make -C
tools/native`), the part's captures (`python3
tools/native/gparts/player.py --capture`).
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
    import player as P
    return all(P.case_paths(key) for key in P.ENTRIES) and \
        bool(P.tour_cases())


def all_ok() -> bool:
    if not shared_ok():
        return False
    import player as P
    try:
        return P.missing() is None and captures_ok()
    except P.PartError:
        return False


needs_shared = unittest.skipUnless(
    shared_ok(), 'needs the shared outputs, newer than tools/native/'
    'glayout.py and llayout.py: ' + PREBUILD + ', and milestone 9\'s store '
    '(python3 tools/native/wadconv.py --store)')
needs_all = unittest.skipUnless(
    all_ok(),
    'needs the shared outputs (' + PREBUILD + '), ref816, a2vm and mathref '
    '(make -C tools/ref816; make -C tools/a2vm; make -C tools/native), the '
    'survey (python3 tools/native/gamecap.py --survey), milestone 9\'s '
    'level bases (python3 tools/native/level_check.py --setup) and the '
    'part\'s captures (python3 tools/native/gparts/player.py --capture)')
needs_full = unittest.skipUnless(
    FULL, 'the heavier checks run with DOOM_GS_FULL=1 (the owner\'s lean '
    'rules of 2026-10-02)')


def setUpModule():
    if shared_ok():
        import player as P
        import mobjstate as MS
        MS.use_cases(P.MYCASES)


@needs_shared
class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import player as P
        cls.b = P.load(P.build())
        cls.sizes = P.sizes(cls.b)

    def test_the_image_builds_within_its_budget(self):
        import player as P
        for m in P.MODULES + P.TEST_MODULES:
            self.assertGreater(self.sizes['modules'][m], 0, m)
        self.assertLessEqual(self.sizes['part_bytes'], P.BUDGET * 11 // 10)
        for name in ('P_PlayerThink', 'fixedSquare', 'specialSector',
                     'movePlayer', 'calcHeight', 'angleToAttacker',
                     'P_UseLines', 'PTR_UseTraverse', 'PTR_NoWayTraverse',
                     'onGround', 'thrustMul', 'hurt32', 'times64',
                     'pl_bulk'):
            self.assertIn(name, self.b.labels)

    def test_the_traversers_are_in_trvtab(self):
        """TRVTAB's entries of the part's traversers name them (gdisp.inc
        of the part's image counts the part built)."""
        text = (self.b.obj / 'gen' / 'gdisp.inc').read_text()
        for name in ('PTR_UseTraverse', 'PTR_NoWayTraverse'):
            self.assertIn('<%s, >%s' % (name, name), text)

    def test_no_far_access(self):
        """The part's sources call no g_get, g_put, far_get or far_put but
        the test routine's own banks (pltest.s: the random checks')."""
        from native import gameroutine as GR
        src = GR.SRC / 'game' / 'player'
        for p in sorted(src.glob('*.s')):
            if p.name == 'pltest.s':
                continue
            words = [GR._code(x) for x in p.read_text().splitlines()]
            far = [w for w in words if len(w) >= 2 and w[0] in ('jsr', 'jmp')
                   and w[1] in GR.FAR_CALLS]
            self.assertEqual(far, [], p.name)
        self.assertEqual(GR.grep_check(src, ('pltest.s',)), [])


@needs_all
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import player as P
        if FULL:
            cls.rep = P.check(jobs=2)
        else:
            cls.rep = P.check(jobs=2, sample=1 << 20,
                              synthetic_names=('squat', 'e1m8-10'))

    def test_no_failure_and_no_stray_write(self):
        bad = {k: e['first_failures'] for k, e in self.rep['entries'].items()
               if e['failures']}
        self.assertEqual(bad, {})
        self.assertEqual(self.rep['failures'], 0)
        self.assertEqual(self.rep['strays'], 0)

    def test_every_entry_ran(self):
        import player as P
        for key in P.ENTRIES:
            with self.subTest(key):
                e = self.rep['entries'].get(key)
                self.assertIsNotNone(e)
                self.assertGreater(e['runs'], 0)
                self.assertEqual(e.get('undecodable', 0), 0)

    @unittest.skipUnless(FULL, 'every class with DOOM_GS_FULL=1')
    def test_the_paths(self):
        """The captured calls take the death think with its attacker, the
        special floors, the use with its noway and its specials, and the
        synthetic cases the rest."""
        import player as P
        paths = ','.join(self.rep['entries'][P.THINK]['paths'])
        for what in ('atk', 'special', 'noway', 'lnVDoor',
                     'synthetic: dead-left', 'synthetic: dead-right',
                     'synthetic: squat'):
            self.assertIn(what, paths)
        paths = ','.join(self.rep['entries'][P.SPEC]['paths'])
        for name in ('nukage', 'nukage-16', 'nukage-suit', 'slime',
                     'slime-suit', 'e1m8-11', 'e1m8-11-god', 'e1m8-10',
                     'e1m8-10-god', 'e1m8-hurt'):
            self.assertIn('synthetic: ' + name, paths)
        self.assertIn('synthetic: locked-door',
                      self.rep['entries'][P.USE]['paths'])


@needs_all
class Random(unittest.TestCase):
    def test_the_helpers_against_upstream(self):
        import player as P
        n = 100_000
        r = P.random_check(n)
        for name in P.MODES:
            with self.subTest(name):
                self.assertEqual(r[name]['compared'], n)
                self.assertEqual(r[name]['different'], 0, r[name]['first'])
        self.assertGreater(r['hurt32_calls'], 0)


@needs_all
@needs_full
class Plants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        import player as P
        for name in P.PLANTS:
            with self.subTest(name):
                r = P.run_plant(name)
                self.assertGreater(r['runs'], 0)
                self.assertTrue(r['caught'], '%s was not caught by %s' % (
                    name, r['check']))


if __name__ == '__main__':
    unittest.main()
