"""Milestone 10, wave 2: part damage's checkpoint (docs/GAME.md 2.4, 3.5;
docs/game-parts/damage.md; the harness is tools/native/gparts/damage.py).

  Build       the part's image builds with no warning; no far access of
              the part's own (every record through the object API); the
              native weaponinfo equals the release's table; the part's
              own bytes within 10% of its budget
  Checkpoint  routine mode on the part's image, both fills ($A5, $5A),
              both profiles (f121, fastpath): the three demos' captured
              calls of P_DamageMobj, P_DropWeapon, lowerWeapon, wInfoOf
              and wInfo, every SAMPLE-th; the calls that reach an unbuilt
              action (A_Lower, part pspr) as stop checks, and their
              variants with that action removed on both sides; the
              synthetic groups (kills with a drop, the rocket cheat, the
              extreme death's boundary, the player's death, each armour
              type, god mode, invulnerability, a hit at 0 health, baby,
              the exit sector, the turn-over, the chainsaw, no inflictor,
              the threshold): the canonical state equal to ref816's,
              wInfo's and wInfoOf's X and A, no stray write
  Random      the thrust on RANDOM_N inputs against upstream's thrust
              (mathref batch): the momentum, P_Random's index, the thrust
              and its angle equal; the division by zero (type 49's mass)
              the port's own result
  Plants      each planted bug of the part's row, made in a scratch copy of
              its sources, fails its named check (and the thrust divided
              first fails the random check too)

The full checkpoint (every case) is `python3 tools/native/gparts/
damage.py --check --random --plants` (report.json); this module runs every
SAMPLE-th captured case and every synthetic group.

By default (tests/README.md) it runs every SAMPLE_DEF-th captured case
instead (every entry still reached, both fills under both profiles),
every synthetic group from $A5 under f121 or $5A under fastpath in turn
(both fills and both profiles still among the groups), and the
thrust's random check on 20,000 inputs; DOOM_GS_FULL=1 runs all of what
it ran before (every SAMPLE-th case, 100,000 inputs).

Each class skips, naming the command that makes what it needs, when
build/ lacks it: the shared outputs (`make -s -C src/native -f game.mk
shared skel ROOT=$PWD`, the parallel runner's prebuild; never made here),
the survey (`python3 tools/native/gamecap.py --survey`), milestone 9's
level bases (`python3 tools/native/level_check.py --setup`), ref816 and
a2vm (`make -C tools/ref816`, `make -C tools/a2vm`), mathref (`make -C
tools/native`), the part's captures (`python3 tools/native/gparts/
damage.py --capture`).
"""

import os
import shutil
import struct
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
FULL = os.environ.get('DOOM_GS_FULL') == '1'
SAMPLE = 8
SAMPLE_DEF = 80                 # by default
RANDOM_N = 100_000 if FULL else 20_000


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


def machines_ok() -> bool:
    from native import grun as G
    from ref816 import title
    return Path(G.A2VM).exists() and Path(title.MACHINE).exists()


def survey_ok() -> bool:
    return (SHARED / 'survey' / 'demo3.json.z').exists()


def bases_ok() -> bool:
    from native import gameroutine as GR
    return GR.have_bases()


def captures_ok() -> bool:
    import damage as D
    return all(D.case_paths(run, key) for run, key, _ in D.CAPTURES)


def mathref_ok() -> bool:
    import damage as D
    return D.MATHREF.exists()


needs_shared = unittest.skipUnless(
    shared_ok(), 'needs the shared outputs, newer than tools/native/'
    'glayout.py and llayout.py: ' + PREBUILD + ', and milestone 9\'s store '
    '(python3 tools/native/wadconv.py --store)')
ALL_MSG = ('needs the shared outputs (' + PREBUILD + '), ref816 and a2vm '
           '(make -C tools/ref816; make -C tools/a2vm), the survey (python3 '
           'tools/native/gamecap.py --survey), milestone 9\'s level bases '
           '(python3 tools/native/level_check.py --setup) and the part\'s '
           'captures (python3 tools/native/gparts/damage.py --capture)')
needs_all = unittest.skipUnless(
    shared_ok() and machines_ok() and survey_ok() and bases_ok() and
    captures_ok(), ALL_MSG)
needs_mathref = unittest.skipUnless(
    shared_ok() and machines_ok() and bases_ok() and captures_ok() and
    mathref_ok(), ALL_MSG + ', and mathref (make -C tools/native: '
    'build/native/math/mathref)')


@needs_shared
class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import damage as D
        cls.b = D.load(D.build())

    def test_the_image_builds(self):
        import damage as D
        sz = D.sizes(self.b)
        for m in D.MODULES + D.TEST_MODULES:
            self.assertGreater(sz['modules'][m], 0, m)
        for name in ('P_DamageMobj', 'killMobj', 'P_DropWeapon',
                     'lowerWeapon', 'wInfo', 'wInfoOf', 'thrust',
                     'playerDamage', 'setState', 'lastEnemy', 'weaponinfo',
                     'dm_t_bulk'):
            self.assertIn(name, self.b.labels)

    def test_within_ten_percent_of_the_budget(self):
        """The part's own bytes (the weapon table included, the math
        stand-in of request R1 not) within 10% of GAME.md 2.4's 1,800."""
        import damage as D
        sz = D.sizes(self.b)
        self.assertLessEqual(sz['own_bytes'], int(1.1 * D.BUDGET), sz)

    def test_no_far_access(self):
        """The part's sources call no g_get, g_put, far_get or far_put but
        the test routine's own bulk buffers (dtest.s, banks 93 and 94)."""
        from native import gameroutine as GR
        src = GR.SRC / 'game' / 'damage'
        for p in sorted(src.glob('*.s')) + sorted(src.glob('*.inc')):
            if p.name == 'dtest.s':
                continue
            words = [GR._code(x) for x in p.read_text().splitlines()]
            far = [w for w in words if len(w) >= 2 and w[0] in ('jsr', 'jmp')
                   and w[1] in GR.FAR_CALLS]
            self.assertEqual(far, [], p.name)

    def test_weaponinfo_is_the_releases(self):
        """The native table (in the core) equals the release's
        p_pspr65.s:weaponinfo, byte for byte."""
        from native import umodel as U
        rel = U.Release().table('p_pspr65.s:weaponinfo', 12 * 9)
        b = self.b
        a = b.labels['weaponinfo']
        lo, hi = b.segments['GCORE']
        core = (b.obj / (b.name + '.core')).read_bytes()
        from native import glayout as GL
        at = a - GL.WR['CORE'][0]
        self.assertTrue(lo <= a and a + 108 <= hi + 1)
        self.assertEqual(core[at:at + 108], rel)
        self.assertEqual(struct.unpack_from('<6H', rel, 12)[2],
                         struct.unpack_from('<6H', core, at + 12)[2])


@needs_all
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import damage as D
        if FULL:
            cls.rep = cls.captured = D.check(jobs=2, sample=SAMPLE,
                                             say=lambda *a: None)
            return
        # damage.check() on the default sample: the captured cases from
        # both fills under both profiles, each synthetic group on one of
        # the two diagonal combinations
        D.build()
        js, _ = D.plan(D.OUT, D.FILLS, D.PROFILES, SAMPLE_DEF)
        diag = (((0xA5,), ('f121',)), ((0x5A,), ('fastpath',)))
        synth = [j[:4] + diag[i % 2] for i, j in
                 enumerate(j for j in js if j[0] == 'synthetic')]
        res_c = D.run_jobs([j for j in js if j[0] != 'synthetic'], 2)
        res = res_c + D.run_jobs(synth, 2)
        cls.rep = {'entries': D.summarize(res),
                   'strays': sum(r.get('strays') or 0 for r in res)}
        cls.captured = {'entries': D.summarize(res_c)}

    def test_no_failure_and_no_stray_write(self):
        bad = {k: e['first_failures'] for k, e in self.rep['entries'].items()
               if e['failures']}
        self.assertEqual(bad, {})
        self.assertEqual(self.rep['strays'], 0)

    def test_every_entry_ran(self):
        import damage as D
        for key in (D.DAMAGE, D.KILL, D.DROP, D.LOWER, D.WINFO, D.WINFOOF):
            with self.subTest(key):
                e = self.rep['entries'].get(key)
                self.assertIsNotNone(e)
                self.assertGreater(e['runs'], 0)

    def test_both_fills_and_profiles(self):
        """Every case from both fills under both profiles (by default the
        captured ones: the synthetic groups run one combination each)."""
        import damage as D
        e = self.rep['entries'][D.DAMAGE]
        for prof in ('f121', 'fastpath'):
            self.assertIsNotNone(e['cpu_cycles'][prof]['median'])
        self.assertEqual(self.captured['entries'][D.DAMAGE]['runs'] % 4, 0)
        self.assertGreater(self.captured['entries'][D.DAMAGE]['runs'], 0)

    def test_a_lower_runs_whole(self):
        """The player's deaths and lowerWeapon reach A_Lower (part pspr):
        until wave 3 each stopped at its DCALL and its variant without the
        action was compared; since wave 3's integration A_Lower is built,
        so they run it whole, equal to the reference (no failure above),
        and no case waits for it."""
        import damage as D
        for key in (D.DAMAGE, D.LOWER):
            with self.subTest(key):
                e = self.rep['entries'][key]
                self.assertGreater(e['runs'], 0)
                self.assertEqual(e['waiting'].get('p_pspr65.s:A_Lower', 0),
                                 0)
        e = self.rep['entries'][D.DAMAGE]
        self.assertTrue(any(p.startswith('player') and 'dies' in p
                            for p in e['paths']), sorted(e['paths']))

    def test_the_stops_and_their_variants(self):
        """A case that reaches a still unbuilt action (A_Chase, wave 6)
        stops at its DCALL, and its variant without the action is
        evaluated."""
        import damage as D
        for key, e in self.rep['entries'].items():
            if e['waiting']:
                with self.subTest(key):
                    self.assertGreater(e['kinds'].get('action removed', 0),
                                       0)

    def test_the_synthetic_groups(self):
        import damage as D
        paths = ' | '.join(p for e in self.rep['entries'].values()
                           for p in e['paths'])
        for what in D.SYNTHETIC:
            self.assertIn(what + ':', paths)
        for what in ('drop-possessed: monster, thrust, dies, drop',
                     'xdeath-below: monster, thrust, dies, extreme',
                     'god: player, thrust, no damage',
                     'health-0: monster, dead', 'armour-blue: player',
                     'no-inflictor: monster, no inflictor'):
            self.assertIn(what, paths)


@needs_mathref
class Random(unittest.TestCase):
    def test_the_thrust(self):
        import damage as D
        D.build()
        r = D.random_check(RANDOM_N)
        self.assertEqual(r['compared'], RANDOM_N)
        self.assertEqual(r['different'], 0, r['first'])
        self.assertGreater(r['turn_over_random'], 0)
        self.assertEqual(r['division_by_zero']['different'], 0)


@needs_all
class Plants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        import damage as D
        for name in D.PLANTS:
            with self.subTest(name):
                r = D.run_plant(name)
                self.assertGreater(r['runs'], 0)
                self.assertTrue(r['caught'], '%s was not caught by %s' % (
                    name, r['check']))

    @unittest.skipUnless(mathref_ok(), 'needs mathref (make -C tools/native)')
    def test_the_divided_thrust_fails_the_random_check(self):
        import damage as D
        self.assertTrue(D.run_plant_random()['caught'])


if __name__ == '__main__':
    unittest.main()
