"""Part missile of milestone 10 (docs/GAME.md 2.4 row missile, wave 5;
docs/game-parts/missile.md): a monster's missile (P_SpawnMissile: the
angle, a shadow target's P_Random, the speed, momz by the distance with
math.s's sdiv32) and its spawn check (checkMissile: the tics noise, the
half step through halfMom, P_TryMove, the explosion), natively
(src/native/game/missile/).

What it checks (tools/native/gparts/missile.py does the work), within the
lean checks the owner asked for on 2026-10-02:

  * the part builds without a warning, within its budget (800 B, 10% more
    with a request), and makes no far access (no g_get, g_put, far_get or
    far_put: gameroutine.grep_check);
  * the checkpoint (routine mode, GAME.md 3.5): every SAMPLE-th of the
    chosen captured calls of P_SpawnMissile and checkMissile (40 each: a
    cover of the candidates' paths) and P_SpawnMissile's synthetic calls
    (a missile spawned inside a wall; one spawned into its target, whose
    P_DamageMobj is paged into checkMissile's slot: review 1's chain in the
    integrator's placement; the distance clamped at 1; a shadow target),
    from the $A5 machine under f121, equal to ref816's with the routine
    exclusions only, every declared output equal (the missile in A:X), no
    stray write;
  * halfMom's random check (GAME.md 2.4 "Arithmetic"): 100,000 inputs, the
    edge values among them, upstream's halfMom (mathref batch) against the
    native one;
  * with DOOM_GS_FULL=1: every chosen call under f121 and fastpath, the
    paths they take, and the planted bugs, each built from a scratch copy
    of the part's sources in a temporary directory and failing the
    checkpoint: momz rounded the other way (floored), the shadow P_Random
    taken for a visible target, the tics noise skipped.

It skips with the reason when build/ lacks ref816, a2vm, the shared
outputs (`make -s -C src/native -f game.mk shared ROOT=$PWD`; the survey:
`python3 tools/native/gamecap.py --survey`), the level bases (`python3
tools/native/level_check.py --setup`), mathref (`make -C tools/native`)
or the part's own captures (`python3
tools/native/gparts/missile.py --capture`). It never rebuilds a shared
output.
"""

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))

import missile as M  # noqa: E402

FULL = os.environ.get('DOOM_GS_FULL') == '1'
SAMPLE = 2


def setUpModule():
    """The part's own case directory (gamecap's CASES is one global, which
    another part's harness may change in the same process)."""
    M.GC.CASES = M.CASES


def why_skip():
    why = M.missing()
    if why:
        return why
    known = json.loads(M.PATHS_FILE.read_text()) \
        if M.PATHS_FILE.exists() else {}
    for key in M.ENTRIES:
        got = M.captured(key)
        if not got:
            return ('no captures of %s (python3 tools/native/gparts/'
                    'missile.py --capture)' % key)
        if any(str(p) not in known.get(key, {}) for _, _, p in got):
            return ('the paths of %s are not decoded (python3 tools/native/'
                    'gparts/missile.py --capture)' % key)
    return None


WHY = why_skip()
MATHREF_WHY = None if (M.BUILD / 'native' / 'math' / 'mathref').exists() \
    else 'no mathref (make -C tools/native)'


@unittest.skipIf(M.missing(), str(M.missing()))
class Build(unittest.TestCase):
    def test_builds_within_its_budget(self):
        M.build()
        sz = M.sizes()
        self.assertGreater(sz['bytes'], 0)
        self.assertLessEqual(sz['bytes'], sz['budget'] * 11 // 10, sz)
        for name in M.LABELS:
            self.assertIn(name, sz['routines'], name)

    def test_no_far_access(self):
        """No g_get, g_put, far_get or far_put in the game code: every
        record through the object API (mstest.s, the driver area's test
        routine, moves its bulk data with far_get and far_put)."""
        from native import gameroutine as GR
        srcs = ('missile.s',)
        for f in srcs:
            words = [GR._code(x) for x in
                     (M.PART_SRC / f).read_text().splitlines()]
            far = [w for w in words if len(w) >= 2 and
                   w[0] in ('jsr', 'jmp') and w[1] in GR.FAR_CALLS]
            self.assertEqual(far, [], f)
        self.assertEqual(GR.grep_check(M.PART_SRC, srcs), [])

    def test_review_1_placement(self):
        """The image's placement (the integrator's, shared/placement.json)
        pages P_DamageMobj into checkMissile's slot, the chain the damage
        synthetic call takes (review 1). A later placement that keeps them
        apart is no fault of the code, so it is reported as a skip: the
        damage call still runs, on whatever chain the placement makes."""
        M.build()
        p = M.placement_note()
        if not p['damage_pages_into_checkMissiles_slot']:
            self.skipTest('the placement no longer pages P_DamageMobj into '
                          'checkMissile\'s slot: %s' % p)


@unittest.skipIf(WHY, str(WHY))
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        M.build()
        cls.res = M.run_jobs(M.check_jobs(sample=1 if FULL else SAMPLE,
                                          profiles=M.PROFILES if FULL else
                                          M.PROFILES[:1]), 2)

    def test_every_run_equal(self):
        run = [r for r in self.res if not r.get('waiting') and
               not r.get('undecodable')]
        bad = [(r['case'], r.get('profile'), r.get('diff') or
                r.get('error') or r.get('ended')) for r in run
               if not r.get('ok')]
        self.assertEqual(bad, [])
        self.assertEqual(sum(r.get('stray') or 0 for r in run), 0)
        self.assertEqual([r['case'] for r in self.res
                          if r.get('waiting') or r.get('undecodable')], [])

    def test_both_entries_ran(self):
        for key in M.ENTRIES:
            with self.subTest(key):
                self.assertTrue([r for r in self.res if r['entry'] == key
                                 and r.get('ok')])

    def test_the_synthetic_paths(self):
        """The wall explodes the missile; the damage call damages the
        target and explodes it; the close one clamps the distance; the
        shadow one takes the angle's noise."""
        paths = {}
        for r in self.res:
            if r.get('ok') and r['case'].startswith('synthetic'):
                kind = r['case'].split()[1]
                paths.setdefault(kind, set()).update(r.get('path', []))
        self.assertIn('exploded', paths.get('wall', ()))
        self.assertTrue({'damage', 'exploded', 'momz-neg-inexact'} <=
                        paths.get('damage', set()), paths.get('damage'))
        self.assertIn('dist-clamped', paths.get('close', ()))
        self.assertIn('shadow', paths.get('shadow', ()))

    @unittest.skipUnless(FULL, 'the paths of every chosen call: '
                         'DOOM_GS_FULL=1')
    def test_the_paths_taken(self):
        """The chosen captured calls take every sign of momz, the negative
        inexact divide, a shadow target and the move."""
        paths = set()
        for r in self.res:
            if r.get('ok') and not r['case'].startswith('synthetic'):
                paths.update(r.get('path', []))
        for what in ('momz-zero', 'momz-pos', 'momz-neg', 'momz-neg-inexact',
                     'momz-inexact', 'shadow', 'visible', 'moved',
                     'see-sound'):
            self.assertIn(what, paths)


@unittest.skipIf(WHY or MATHREF_WHY, str(WHY or MATHREF_WHY))
class Random(unittest.TestCase):
    def test_halfmom(self):
        M.build()
        r = M.random_check(100_000)
        self.assertEqual(r['compared'], 100_000)
        self.assertEqual(r['different'], 0, r['first'])
        self.assertEqual(r['upstream_is_the_model'], 100_000)


@unittest.skipIf(WHY, str(WHY))
@unittest.skipUnless(FULL, 'the planted bugs: DOOM_GS_FULL=1')
class Plants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        r = M.plants()
        for name in M.PLANT_NAMES:
            with self.subTest(name):
                self.assertGreater(r[name]['runs'], 0)
                self.assertTrue(r[name]['caught'], name)


if __name__ == '__main__':
    unittest.main()
