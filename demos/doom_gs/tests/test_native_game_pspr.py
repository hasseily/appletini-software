"""Milestone 10, wave 3: part pspr's checkpoint (docs/GAME.md 2.4, 3.5;
docs/game-parts/pspr.md; the harness is tools/native/gparts/pspr.py),
lean (the owner's rules of 2026-10-02: the default suite's share under
60 s, the rest with DOOM_GS_FULL=1).

  Build       the part's image builds with no warning; the part's code
              (the flood's work stack apart) within 1.4 x its budget
              (1,200 B: over 10% is reported in docs/game-parts/pspr.md
              with its reasons); the work stack and the flood's code fit
              one group (2,048 B); no far access of the part's own but the
              test routine's (every record through the object API: the
              flood lists' stand-in reads them through lt_get)
  Checkpoint  routine mode on the part's image, fill $A5, f121: by
              default one captured call of each entry (P_MovePsprites,
              tickPsprite, fireWeapon, checkAmmo, P_CheckAmmo,
              recursiveSound) and the synthetic E1M2 flood (93 levels,
              every line open); with DOOM_GS_FULL=1 every selected call
              (at most 40 a routine) and every synthetic case: the
              canonical state equal to ref816's, every declared output
              equal, no stray write, the native-only globals consistent
  Random      signExt4 and signExt0 on 100,000 inputs
              each against upstream's helpers on ref816 (mathref)
  Plants      (DOOM_GS_FULL=1) each planted bug, made in a scratch copy of
              the part's sources, fails its named check: a work stack of
              80 (the E1M2 flood stops), the bob's x from the sine (the
              captured P_MovePsprites calls), a closed opening let through
              (the captured floods)

The full checkpoint is `python3 tools/native/gparts/pspr.py --check
--random --plants` (report.json).

Each class skips, naming the command that makes what it needs, when
build/ lacks it: the shared outputs (`make -s -C src/native -f game.mk
shared skel ROOT=$PWD`, the parallel runner's prebuild; never made here),
the survey (`python3 tools/native/gamecap.py --survey`), milestone 9's
level bases (`python3 tools/native/level_check.py --setup`), ref816 and
a2vm (`make -C tools/ref816`, `make -C tools/a2vm`), the part's captures
(`python3 tools/native/gparts/pspr.py --capture`).
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
    import pspr as P
    return all(P.case_paths(key) for key in P.ENTRIES)


def all_ok() -> bool:
    if not shared_ok():
        return False
    import pspr as P
    return P.missing() is None and captures_ok()


needs_shared = unittest.skipUnless(
    shared_ok(), 'needs the shared outputs, newer than tools/native/'
    'glayout.py and llayout.py: ' + PREBUILD + ', and milestone 9\'s store '
    '(python3 tools/native/wadconv.py --store)')
needs_all = unittest.skipUnless(
    all_ok(),
    'needs the shared outputs (' + PREBUILD + '), ref816 and a2vm (make -C '
    'tools/ref816; make -C tools/a2vm), the survey (python3 tools/native/'
    'gamecap.py --survey), milestone 9\'s level bases (python3 tools/native/'
    'level_check.py --setup) and the part\'s captures (python3 tools/native/'
    'gparts/pspr.py --capture)')
needs_full = unittest.skipUnless(
    FULL, 'the heavier checks run with DOOM_GS_FULL=1 (the owner\'s lean '
    'rules of 2026-10-02)')


def setUpModule():
    if shared_ok():
        import pspr as P
        import mobjstate as MS
        MS.use_cases(P.MYCASES)


@needs_shared
class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pspr as P
        cls.b = P.load(P.build())
        cls.sizes = P.sizes(cls.b)

    def test_the_image_builds_within_its_room(self):
        import pspr as P
        for m in P.MODULES + P.TEST_MODULES:
            self.assertGreater(self.sizes['modules'][m], 0, m)
        self.assertLessEqual(self.sizes['part_bytes'], P.BUDGET * 14 // 10)
        self.assertLessEqual(self.sizes['flood_group_bytes'], 2048)
        for name in ('P_MovePsprites', 'tickPsprite', 'A_WeaponReady',
                     'A_ReFire', 'A_Lower', 'A_GunFlash', 'A_Light0',
                     'A_Light1', 'A_Light2', 'fireWeapon', 'checkAmmo',
                     'recursiveSound', 'P_CheckAmmo', 'p_pspr_startSound',
                     'setMoState', 'signExt4', 'signExt0', 'fireSomething',
                     'ps_stack', 'ps_bulk'):
            self.assertIn(name, self.b.labels)

    def test_the_actions_are_in_acttab(self):
        """ACTTAB's entries of the part's actions name them (gdisp.inc of
        the part's image counts the part built)."""
        text = (self.b.obj / 'gen' / 'gdisp.inc').read_text()
        for name in ('A_WeaponReady', 'A_ReFire', 'A_Lower', 'A_GunFlash',
                     'A_Light0', 'A_Light1', 'A_Light2'):
            self.assertIn('<%s, >%s' % (name, name), text)

    def test_no_far_access(self):
        """The part's sources call no g_get, g_put, far_get or far_put but
        the test routine's own banks (pstest.s: the random check's)."""
        from native import gameroutine as GR
        src = GR.SRC / 'game' / 'pspr'
        for p in sorted(src.glob('*.s')):
            if p.name == 'pstest.s':
                continue
            words = [GR._code(x) for x in p.read_text().splitlines()]
            far = [w for w in words if len(w) >= 2 and w[0] in ('jsr', 'jmp')
                   and w[1] in GR.FAR_CALLS]
            self.assertEqual(far, [], p.name)
        self.assertEqual(GR.grep_check(src, ('pstest.s',)), [])


@needs_all
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pspr as P
        if FULL:
            cls.rep = P.check(jobs=2)
        else:
            cls.rep = P.check(jobs=2, sample=1 << 20,
                              synthetic_names=('flood-e1m2',))

    def test_no_failure_and_no_stray_write(self):
        bad = {k: e['first_failures'] for k, e in self.rep['entries'].items()
               if e['failures']}
        self.assertEqual(bad, {})
        self.assertEqual(self.rep['failures'], 0)
        self.assertEqual(self.rep['strays'], 0)

    def test_every_entry_ran(self):
        import pspr as P
        for key in P.ENTRIES:
            with self.subTest(key):
                e = self.rep['entries'].get(key)
                self.assertIsNotNone(e)
                self.assertGreater(e['runs'], 0)

    def test_the_deep_flood(self):
        """The E1M2 flood from its deepest start with every line open: run
        and equal (its 93 levels need 92 entries of the work stack)."""
        paths = self.rep['entries']['p_pspr65.s:recursiveSound']['paths']
        self.assertIn('synthetic: flood-e1m2', paths)

    @unittest.skipUnless(FULL, 'every class with DOOM_GS_FULL=1')
    def test_the_classes_of_the_calls(self):
        """The captured P_MovePsprites calls take every built action
        (A_WeaponReady with and without a shot, A_ReFire, A_Lower, A_Raise,
        A_Light0, A_Light2) and the synthetic cases the rest (A_GunFlash
        with A_Light1, the empty weapon, the chainsaw's idle, the rocket
        launcher held)."""
        import pspr as P
        paths = ','.join(self.rep['entries'][P.MOVE]['paths'])
        for what in ('A_WeaponReady+fire', 'A_ReFire', 'A_Lower',
                     'A_Raise', 'A_Light0', 'A_Light2', 'synthetic: gunflash',
                     'synthetic: empty-weapon', 'synthetic: saw-idle',
                     'synthetic: missile-held'):
            self.assertIn(what, paths)
        self.assertIn('synthetic: flood-e1m3', self.rep['entries'][
            P.FLOOD]['paths'])


@needs_all
class Random(unittest.TestCase):
    def test_the_sign_extensions_on_100000_inputs(self):
        import pspr as P
        r = P.random_check(100_000)
        for name in ('signExt4', 'signExt0'):
            with self.subTest(name):
                self.assertEqual(r[name]['compared'], 100_000)
                self.assertEqual(r[name]['different'], 0, r[name]['first'])
                self.assertEqual(r[name]['upstream_is_the_sign_extension'],
                                 100_000)


@needs_all
@needs_full
class Plants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        import pspr as P
        for name in P.PLANTS:
            with self.subTest(name):
                r = P.run_plant(name)
                self.assertGreater(r['runs'], 0)
                self.assertTrue(r['caught'], '%s was not caught by %s' % (
                    name, r['check']))


if __name__ == '__main__':
    unittest.main()
