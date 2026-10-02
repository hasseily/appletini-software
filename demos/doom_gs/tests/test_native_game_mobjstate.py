"""Milestone 10, wave 1: part mobjstate's checkpoint (docs/GAME.md 2.4, 3.5;
docs/game-parts/mobjstate.md; the harness is
tools/native/gparts/mobjstate.py).

  Build       the part's image builds with no warning; no far access of
              the part's own (every record through the object API)
  Checkpoint  routine mode on the part's image, both fills ($A5, $5A),
              both profiles (f121, fastpath): demo3's captured calls of
              P_SetMobjState, P_RemoveMobj, P_UnsetThingPosition,
              P_DelSeclist, P_DelSecnode, P_RemoveThinker and explode
              (demo1's and demo2's too), every SAMPLE-th; the delayed
              removers on the states after P_RemoveMobj and
              P_RemoveThinker; P_ExplodeMissile on explode's states; the
              skeleton's P_CreateSecNodeList calls that free a node;
              P_SetMobjState's calls of an unbuilt action at its DCALL (the
              stop check); the synthetic groups (a zone mobj removed and its
              slot taken again, a zone mobj CS_PREV names freed, a mobj
              with no function removed, pooled and zone, a chain of 0-tic
              states, the rocket cheat, the brainless thinker,
              P_NextThinker, P_MobjIsPlayer, P_RemoveThing): the canonical
              state equal to ref816's, every declared output equal, no
              stray write, the native-only globals consistent
  Plants      each planted bug of the part's row, made in a scratch copy of
              its sources, fails its named check

The full checkpoint (every case) is `python3 tools/native/gparts/
mobjstate.py --check --plants` (report.json); this module runs every
SAMPLE-th captured case and every synthetic group.

By default (tests/README.md) it runs every SAMPLE_DEF-th captured case
(both fills, both profiles), and each synthetic group once, from $A5
under f121 or $5A under fastpath in turn (both fills and both profiles
still among the groups); the plants run two at a time. DOOM_GS_FULL=1
runs all of what it ran before: every SAMPLE-th captured case, every
group from both fills under both profiles.

Each class skips, naming the command that makes what it needs, when
build/ lacks it: the shared outputs (`make -s -C src/native -f game.mk
shared skel ROOT=$PWD`, the parallel runner's prebuild; never made here),
the survey (`python3 tools/native/gamecap.py --survey`), milestone 9's
level bases (`python3 tools/native/level_check.py --setup`), ref816 and
a2vm (`make -C tools/ref816`, `make -C tools/a2vm`), the part's captures
(`python3 tools/native/gparts/mobjstate.py --capture`).
"""

import os
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
FULL = os.environ.get('DOOM_GS_FULL') == '1'
SAMPLE = 8
SAMPLE_DEF = 240                # by default


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
    import mobjstate as M
    return all(M.case_paths(run, key) for run, key, _ in M.CAPTURES)


needs_shared = unittest.skipUnless(
    shared_ok(), 'needs the shared outputs, newer than tools/native/'
    'glayout.py and llayout.py: ' + PREBUILD + ', and milestone 9\'s store '
    '(python3 tools/native/wadconv.py --store)')
needs_all = unittest.skipUnless(
    shared_ok() and machines_ok() and survey_ok() and bases_ok() and
    captures_ok(),
    'needs the shared outputs (' + PREBUILD + '), ref816 and a2vm (make -C '
    'tools/ref816; make -C tools/a2vm), the survey (python3 tools/native/'
    'gamecap.py --survey), milestone 9\'s level bases (python3 tools/native/'
    'level_check.py --setup) and the part\'s captures (python3 tools/native/'
    'gparts/mobjstate.py --capture)')


@needs_shared
class Build(unittest.TestCase):
    def test_the_image_builds(self):
        import mobjstate as M
        b = M.load(M.build())
        sz = M.sizes(b)
        for m in M.MODULES:
            self.assertGreater(sz['modules'][m], 0, m)
        for name in ('P_SetMobjState', 'P_RemoveMobj', 'P_DelSecnode',
                     'P_RemoveThingDelayed', 'mvBlock', 'ms_t_seq'):
            self.assertIn(name, b.labels)

    def test_no_far_access(self):
        """The part's sources call no g_get, g_put, far_get or far_put: the
        sector nodes, the blocklinks and mobjinfo go through the object
        API (sn_get, sn_put, sn_putw, bk_get, bk_put, mi_get: request R2,
        applied at wave 1's integration; msapi.s's stand-ins are gone)."""
        from native import gameroutine as GR
        src = GR.SRC / 'game' / 'mobjstate'
        self.assertFalse((src / 'msapi.s').exists())
        for p in sorted(src.glob('*.s')):
            words = [GR._code(x) for x in p.read_text().splitlines()]
            far = [w for w in words if len(w) >= 2 and w[0] in ('jsr', 'jmp')
                   and w[1] in GR.FAR_CALLS]
            self.assertEqual(far, [], p.name)


@needs_all
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import mobjstate as M
        if FULL:
            cls.rep = M.check(jobs=2, sample=SAMPLE, say=lambda *a: None)
            return
        # mobjstate.check() on the default sample: the synthetic groups
        # each on one of the two diagonal combinations
        M.build()
        js, _ = M.plan(M.OUT, M.FILLS, M.PROFILES, SAMPLE_DEF)
        diag = (((0xA5,), ('f121',)), ((0x5A,), ('fastpath',)))
        n = 0
        for i, j in enumerate(js):
            if j[0] == 'synthetic':
                js[i] = j[:5] + diag[n % 2]
                n += 1
        res = M.run_jobs(js, 2)
        cls.rep = {'entries': M.summarize(res),
                   'strays': sum(r.get('strays') or 0 for r in res)}

    def test_no_failure_and_no_stray_write(self):
        bad = {k: e['first_failures'] for k, e in self.rep['entries'].items()
               if e['failures']}
        self.assertEqual(bad, {})
        self.assertEqual(self.rep['strays'], 0)

    def test_every_entry_ran(self):
        for key in ('p_tick65.s:P_SetMobjState', 'p_spawn65.s:P_RemoveMobj',
                    'p_map65.s:P_UnsetThingPosition',
                    'p_map65.s:P_DelSeclist', 'p_map65.s:P_DelSecnode',
                    'p_mobj65.s:explode', 'p_mobj65.s:P_ExplodeMissile',
                    'p_think65.s:P_RemoveThingDelayed',
                    'p_think65.s:P_RemoveThinkerDelayed',
                    'p_think65.s:P_RemoveThinker',
                    'p_think65.s:P_RemoveThing', 'p_think65.s:P_NextThinker',
                    'p_tick65.s:P_MobjBrainlessThinker',
                    'p_mobj65.s:P_MobjIsPlayer', 'ms_t_seq'):
            with self.subTest(key):
                e = self.rep['entries'].get(key)
                self.assertIsNotNone(e)
                self.assertGreater(e['runs'], 0)

    def test_both_fills_and_profiles(self):
        e = self.rep['entries']['p_spawn65.s:P_RemoveMobj']
        for prof in ('f121', 'fastpath'):
            self.assertIsNotNone(e['clock'][prof]['median'])
        self.assertEqual(e['runs'] % 4, 0)

    def test_the_synthetic_groups(self):
        paths = {p for k in ('ms_t_seq', 'p_tick65.s:P_SetMobjState')
                 for p in self.rep['entries'][k]['paths']}
        for what in ('zone-gate (type 11)', 'zone-prev (type 11)',
                     'no-function-zone (type 29)'):
            self.assertIn(what, paths)
        self.assertTrue(any(p.startswith('no function') for p in paths))
        self.assertTrue(any(p.startswith('chain of 0-tic states')
                            for p in paths))
        self.assertTrue(any(p.startswith('cheat, missilestate range')
                            for p in paths))

    def test_the_stop_check(self):
        import mobjstate as M
        from native import gcallgraph as CG, glayout as GL
        e = self.rep['entries']['p_tick65.s:P_SetMobjState']
        acts = GL.dispatch_entries(CG.load(write=False))['ACTTAB']
        if M.waiting_for(acts):
            self.assertGreater(e['kinds'].get('stop', 0), 0)
        else:
            # every action built (wave 6 as integrated): no call can stop
            # at an unbuilt one, and the rocket cheat's calls (A_CyberAttack)
            # run whole against the reference's own call
            self.assertEqual(e['kinds'].get('stop', 0), 0)
            self.assertTrue(any(p.startswith('cheat, missilestate range')
                                for p in e['paths']))


def _plant(name):
    import mobjstate as M
    return M.run_plant(name)


@needs_all
class Plants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        import mobjstate as M
        from concurrent.futures import ProcessPoolExecutor
        names = list(M.PLANTS)
        with ProcessPoolExecutor(max_workers=1 if FULL else 2) as pool:
            got = dict(zip(names, pool.map(_plant, names)))
        for name in names:
            with self.subTest(name):
                r = got[name]
                self.assertGreater(r['runs'], 0)
                self.assertTrue(r['caught'], '%s was not caught by %s' % (
                    name, r['check']))


if __name__ == '__main__':
    unittest.main()
