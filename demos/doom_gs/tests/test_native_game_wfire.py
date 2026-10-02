"""Milestone 10, wave 6: part wfire's checkpoint (docs/GAME.md 2.2 ACTTAB,
2.4 row wfire, 3.5; docs/game-parts/wfire.md; the harness is
tools/native/gparts/wfire.py), lean (the owner's rules of 2026-10-02: the
default suite's share under 60 s, the rest with DOOM_GS_FULL=1).

  Build       the part's image builds with no warning; the part's code
              within 1.1 x its budget (1,300 B); the actions are ACTTAB's
              entries; no far access (every record through the object API)
  Checkpoint  routine mode on the part's image, fill $A5: the weapon
              actions reached through part pspr's P_MovePsprites (ACTTAB).
              By default one captured call of each captured action
              (A_FirePistol, A_FireShotgun) under f121, and the synthetic
              chainsaw beside a target; with DOOM_GS_FULL=1 every selected
              call (at most 40 an action) and every synthetic case (the
              berserk punch, the chainsaw's four turns and its miss, the
              rocket's aim retries, the chaingun's second shot and its
              empty clip) under f121 and fastpath: the canonical state
              equal to ref816's, no stray write, the native-only globals
              consistent
  Plants      each planted bug, made in a scratch copy of the part's
              sources, fails its named check: by default the spread taken
              on the first shot (one captured accurate pistol shot); with
              DOOM_GS_FULL=1 also the shotgun's pellets in another order
              (the captured shotgun calls) and the aim retries' order (the
              captured calls of both actions)

The full checkpoint is `python3 tools/native/gparts/wfire.py --check
--plants` (report.json).

Each class skips, naming the command that makes what it needs, when
build/ lacks it: the shared outputs (`make -s -C src/native -f game.mk
shared skel ROOT=$PWD`, the parallel runner's prebuild; never made here),
the survey (`python3 tools/native/gamecap.py --survey`), milestone 9's
level bases (`python3 tools/native/level_check.py --setup`), ref816 and
a2vm (`make -C tools/ref816`, `make -C tools/a2vm`), the part's captures
(`python3 tools/native/gparts/wfire.py --capture`).
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
    import wfire as W
    return all(W.case_paths(a) for a in W.CAPTURED)


def all_ok() -> bool:
    if not shared_ok():
        return False
    import wfire as W
    return W.missing() is None and captures_ok()


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
    'gparts/wfire.py --capture)')

_IMAGE = []


def image():
    """The part's image, built once a run of the module."""
    import wfire as W
    if not _IMAGE:
        _IMAGE.append(W.build())
    return _IMAGE[0]


def setUpModule():
    if shared_ok():
        import wfire as W
        W.use_cases()


@needs_shared
class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wfire as W
        cls.b = W.load(image())
        cls.sizes = W.sizes(cls.b)

    def test_the_image_builds_within_its_budget(self):
        import wfire as W
        self.assertGreater(self.sizes['part_bytes'], 0)
        self.assertLessEqual(self.sizes['part_bytes'], W.BUDGET * 11 // 10)
        for name in W.LABELS:
            self.assertIn(name, self.b.labels)

    def test_the_actions_are_in_acttab(self):
        """ACTTAB's entries of the part's actions name them (gdisp.inc of
        the part's image counts the part built)."""
        text = (self.b.obj / 'gen' / 'gdisp.inc').read_text()
        for name in ('A_FirePistol', 'A_FireShotgun', 'A_FireCGun',
                     'A_FireMissile', 'A_Punch', 'A_Saw'):
            self.assertIn('<%s, >%s' % (name, name), text)

    def test_no_far_access(self):
        """The part's sources call no g_get, g_put, far_get or far_put."""
        from native import gameroutine as GR
        src = GR.SRC / 'game' / 'wfire'
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
        import wfire as W
        image()
        if FULL:
            cls.rep = W.check(jobs=2, rebuild=False)
        else:
            cls.rep = W.check(jobs=2, sample=1 << 20,
                              synthetic_names=('saw-left',),
                              profiles=('f121',), rebuild=False)

    def test_no_failure_and_no_stray_write(self):
        bad = {k: e['first_failures'] for k, e in self.rep['entries'].items()
               if e['failures']}
        self.assertEqual(bad, {})
        self.assertEqual(self.rep['failures'], 0)
        self.assertEqual(self.rep['strays'], 0)

    def test_the_actions_ran(self):
        import wfire as W
        acts = W.ACTIONS if FULL else W.CAPTURED + (W.SAW,)
        for key in acts:
            with self.subTest(key):
                e = self.rep['entries'].get(key)
                self.assertIsNotNone(e)
                self.assertGreater(e['runs'], 0)

    def test_the_chainsaw_beside_a_target(self):
        """The synthetic chainsaw beside a target (GAME.md 2.4): the
        reference hit it and turned the player (took()), and the native
        run is equal."""
        import wfire as W
        paths = self.rep['entries'][W.SAW]['paths']
        self.assertIn('synthetic: saw-left', paths)

    @unittest.skipUnless(FULL, 'every synthetic case with DOOM_GS_FULL=1')
    def test_every_synthetic_case(self):
        import wfire as W
        got = set()
        for e in self.rep['entries'].values():
            got |= set(e['paths'])
        for name in W.SYNTHETIC:
            self.assertIn('synthetic: ' + name, got)


@needs_all
class Plants(unittest.TestCase):
    def test_the_spread_on_the_first_shot_is_caught(self):
        import wfire as W
        r = W.run_plant('spread-first-shot', sample=1 << 20)
        self.assertGreater(r['runs'], 0)
        self.assertTrue(r['caught'], 'spread-first-shot was not caught')

    @unittest.skipUnless(FULL, 'the other plants with DOOM_GS_FULL=1')
    def test_each_plant_is_caught(self):
        import wfire as W
        for name in W.PLANTS:
            with self.subTest(name):
                r = W.run_plant(name)
                self.assertGreater(r['runs'], 0)
                self.assertTrue(r['caught'], '%s was not caught by %s' % (
                    name, r['check']))


if __name__ == '__main__':
    unittest.main()
