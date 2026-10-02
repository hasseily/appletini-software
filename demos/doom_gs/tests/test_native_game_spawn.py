"""Milestone 10, wave 2: part spawn's checkpoint (docs/GAME.md 2.4, 3.5;
docs/game-parts/spawn.md; the harness is tools/native/gparts/spawn.py).

  Build       the part's image builds with no warning, within its budget
              (1,100 B, 10% more allowed with a request); no far access of
              the part's own (every record through the object API)
  Paths       the path points of P_ZMovement, missileHit, isPlayer and
              P_IsAttackRangeMeleeRange (found in upstream's source and
              placed by our assembler) start instructions of the release,
              each of the expected kind
  Checkpoint  routine mode on the part's image, both fills ($A5, $5A),
              both profiles (f121, fastpath): every SAMPLE-th captured call
              of the seven entries (P_SpawnPuff, P_SpawnBlood,
              P_IsAttackRangeMeleeRange, P_ZMovement, missileHit, shr3,
              isPlayer) and every synthetic case (a mobj at the ceiling,
              rising into it and stuck through it; a missile into the
              ceiling and into the floor; the player's hard landing, alive
              and dead, and his squat; a fall from rest; a punch's puff;
              blood at damage 8, 9, 12, 13; the melee range): the canonical
              state equal to ref816's, every declared output equal, no
              stray write, the native-only globals consistent
  Random      shr3 on 100,000 inputs (0, +-1, the extremes, the shift's
              edges, random 32-bit values) against upstream's shr3 on
              ref816 (mathref)
  Plants      each planted bug of the part's row, made in a scratch copy of
              its sources, fails its named check: gravity after the floor
              clamp (P_ZMovement), the puff's z P_Random after the tics'
              (P_SpawnPuff), blood's thresholds one off (P_SpawnBlood), the
              squat's deltaviewheight shift (P_ZMovement's squat path)

The full checkpoint (every case) is `python3 tools/native/gparts/spawn.py
--check --random --plants` (report.json); this module runs every
SAMPLE-th captured case, every synthetic case, the random check and the
plants.

Each class skips, naming the command that makes what it needs, when
build/ lacks it: the shared outputs (`make -s -C src/native -f game.mk
shared skel ROOT=$PWD`, the parallel runner's prebuild; never made here),
the survey (`python3 tools/native/gamecap.py --survey`), milestone 9's
level bases (`python3 tools/native/level_check.py --setup`), ref816 and
a2vm (`make -C tools/ref816`, `make -C tools/a2vm`), the part's path logs
and captures (`python3 tools/native/gparts/spawn.py --paths --capture`).
"""

import shutil
import sys
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

ROOT = support.ROOT
BUILD = ROOT / 'build'
GAME = BUILD / 'native' / 'game'
SHARED = GAME / 'shared'
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
PREBUILD = ('make -s -C src/native -f game.mk shared skel ROOT=$PWD (the '
            'parallel runner\'s prebuild)')
SAMPLE = 8


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
    import spawn as S
    return all(S.load_paths(run) is not None for run in
               ('demo3', 'demo1', 'demo2', 'newgame', 'tour')) and \
        all(S.case_paths(key) for key in S.ENTRIES)


def all_ok() -> bool:
    if not shared_ok():
        return False
    import spawn as S
    return S.missing() is None and captures_ok()


needs_shared = unittest.skipUnless(
    shared_ok(), 'needs the shared outputs, newer than tools/native/'
    'glayout.py and llayout.py: ' + PREBUILD + ', and milestone 9\'s store '
    '(python3 tools/native/wadconv.py --store)')
needs_all = unittest.skipUnless(
    all_ok(),
    'needs the shared outputs (' + PREBUILD + '), ref816 and a2vm (make -C '
    'tools/ref816; make -C tools/a2vm), the survey (python3 tools/native/'
    'gamecap.py --survey), milestone 9\'s level bases (python3 tools/native/'
    'level_check.py --setup) and the part\'s path logs and captures '
    '(python3 tools/native/gparts/spawn.py --paths --capture)')


@needs_shared
class Build(unittest.TestCase):
    def test_the_image_builds_within_its_budget(self):
        import spawn as S
        b = S.load(S.build())
        sz = S.sizes(b)
        for m in S.MODULES + S.TEST_MODULES:
            self.assertGreater(sz['modules'][m], 0, m)
        self.assertLessEqual(sz['part_bytes'], S.BUDGET * 11 // 10)
        for name in ('P_SpawnPuff', 'P_SpawnBlood', 'P_ZMovement',
                     'missileHit', 'shr3', 'p_mobj_isPlayer', 'zNoise',
                     'spawnXYZ', 'ticsNoise', 'P_IsAttackRangeMeleeRange',
                     'sp_bulk'):
            self.assertIn(name, b.labels)

    def test_no_far_access(self):
        """The part's sources call no g_get, g_put, far_get or far_put but
        the test routine's own banks (sptest.s: the random check's)."""
        from native import gameroutine as GR
        src = GR.SRC / 'game' / 'spawn'
        for p in sorted(src.glob('*.s')):
            if p.name == 'sptest.s':
                continue
            words = [GR._code(x) for x in p.read_text().splitlines()]
            far = [w for w in words if len(w) >= 2 and w[0] in ('jsr', 'jmp')
                   and w[1] in GR.FAR_CALLS]
            self.assertEqual(far, [], p.name)
        self.assertEqual(GR.grep_check(src, ('sptest.s',)), [])


@needs_all
class Paths(unittest.TestCase):
    def test_the_points_start_instructions(self):
        """Each path point is the first byte of an instruction of the
        expected kind in the release (the run's base memory): the opcodes
        of P_ZMovement's points, missileHit's jsr explode, the two lda #1
        of the comparisons."""
        import spawn as S
        from native import gamecap as GC
        S.MS.use_cases(S.MYCASES)
        mem = GC.load_base('demo1')
        pcs = S.path_pcs()
        want = {('p_mobj65.s:P_ZMovement', 'entry'): 0xD4,   # pei (ENTER)
                ('p_mobj65.s:P_ZMovement', 'floor'): 0xA0,   # ldy ##
                ('p_mobj65.s:P_ZMovement', 'hard'): 0xAA,    # tax
                ('p_mobj65.s:P_ZMovement', 'end'): 0xA9,     # lda ##0
                ('p_mobj65.s:missileHit', 'explode'): 0x20,  # jsr
                ('p_mobj65.s:isPlayer', 'player'): 0xA9,
                ('p_attack65.s:P_IsAttackRangeMeleeRange', 'melee'): 0xA9}
        for (key, name), op in want.items():
            with self.subTest(key=key, point=name):
                self.assertEqual(mem.read(pcs[key][name], 1)[0], op)

    def test_every_call_has_its_path(self):
        import spawn as S
        for run in ('demo3', 'demo1', 'demo2', 'newgame', 'tour'):
            d = S.load_paths(run)
            for key, calls in d['routines'].items():
                with self.subTest(run=run, key=key):
                    self.assertNotIn('?', calls)


@needs_all
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import spawn as S
        cls.rep = S.check(jobs=2, sample=SAMPLE, quiet=True)

    def test_no_failure_and_no_stray_write(self):
        bad = {k: e['first_failures'] for k, e in self.rep['entries'].items()
               if e['failures']}
        self.assertEqual(bad, {})
        self.assertEqual(self.rep['failures'], 0)
        self.assertEqual(self.rep['strays'], 0)

    def test_every_entry_ran_on_both_fills_and_profiles(self):
        import spawn as S
        for key in S.ENTRIES:
            with self.subTest(key):
                e = self.rep['entries'].get(key)
                self.assertIsNotNone(e)
                self.assertGreater(e['runs'], 0)
                self.assertEqual(e['runs'] % 4, 0)
                for prof in ('f121', 'fastpath'):
                    self.assertIsNotNone(e['cpu_cycles'][prof]['median'])

    def test_every_synthetic_case(self):
        import spawn as S
        paths = {p for e in self.rep['entries'].values() for p in e['paths']}
        for name in S.SYNTHETIC:
            with self.subTest(name):
                self.assertIn('synthetic: ' + name, paths)

    def test_the_paths_of_the_floor_and_the_ceiling(self):
        """The captured P_ZMovement calls take the floor, the fall, the air
        with gravity and the ceiling; with the synthetic cases a missile
        explodes at both."""
        paths = ','.join(self.rep['entries']['p_mobj65.s:P_ZMovement'][
            'paths'])
        for what in ('floor', 'fall', 'air', 'gravity'):
            self.assertIn(what, paths)
        for what in ('zm-ceiling-missile', 'zm-floor-missile', 'zm-squat',
                     'zm-hard-landing'):
            self.assertIn(what, paths)


@needs_all
class Random(unittest.TestCase):
    def test_shr3_on_100000_inputs(self):
        import spawn as S
        r = S.random_check(100_000)
        self.assertEqual(r['inputs'], 100_000)
        self.assertEqual(r['compared'], 100_000)
        self.assertEqual(r['different'], 0, r['first'])
        self.assertEqual(r['upstream_is_the_arithmetic_shift'], 100_000)


@needs_all
class Plants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        import spawn as S
        for name in S.PLANTS:
            with self.subTest(name):
                r = S.run_plant(name)
                self.assertGreater(r['runs'], 0)
                self.assertTrue(r['caught'], '%s was not caught by %s' % (
                    name, r['check']))


if __name__ == '__main__':
    unittest.main()
