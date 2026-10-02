"""Milestone 10, part flow (docs/GAME.md 2.4 row flow, wave 1): the game
flow game-side against ref816 (tools/native/gparts/flowcheck.py).

  Build       the part's test image builds with no warning; its bytes
  Checkpoint  routine mode on the part's cases (a sample of each entry's,
              every synthetic one), from $A5 under f121 and $5A under
              fastpath: the canonical state after the call equal to
              ref816's (gcanon routine mode), the declared outputs, no
              stray write; the load-containing actions (doNewGame,
              doPlayDemo, loadLevel, doWorldDone) through the driver's
              routine-with-load mode, compared after the continuation
  Sweeps      every tic: readDemoTiccmd on the three demos, ST_Ticker and
              HU_Ticker on demo3, WI_Ticker on the tour's intermissions
  Random      the arithmetic helpers (times100, div1000, signLong) against
              upstream's (mathref batch): signLong on every input,
              the others on random inputs with the edges
  Plants      GAME.md 2.4's planted bugs, each in a scratch copy of the
              part's sources, each caught by its check
  Stops       victory stops with GS_FINALE (the finale is milestone 11's)

The full checkpoint (every case, both fills, both profiles), the random
checks on 100,000 inputs and report.json are the tool's (--checkpoint,
--random, --report); this module runs the same checks on fewer cases.

Each class skips, naming the command that makes what it needs, when
build/ lacks it: the shared outputs (make -s -C src/native -f game.mk
shared skel ROOT=$PWD), milestone 9's load image and level bases
(tools/native/level_check.py --setup), the tic references
(tools/native/ticcap.py), the part's call logs and cases
(tools/native/gparts/flowcheck.py --logs, --capture), mathref
(tools/native/mathcheck.py's build), a2vm and ref816.
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

ROOT = support.ROOT
BUILD = ROOT / 'build'
GAME = BUILD / 'native' / 'game'
SHARED = GAME / 'shared'
FLOW = GAME / 'flow'
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
PREBUILD = ('make -s -C src/native -f game.mk shared skel ROOT=$PWD (the '
            'parallel runner\'s prebuild)')
TOOL = 'python3 tools/native/gparts/flowcheck.py'

sys.path.insert(0, str(ROOT / 'tools' / 'native' / 'gparts'))


def _tool():
    import flowcheck
    return flowcheck


def missing() -> str:
    """What build/ lacks for the part's checks ('' when nothing)."""
    if not HAVE_CC65:
        return 'cc65 (ca65, ld65) is not installed'
    for p, how in (
            (SHARED / 'gen' / 'ggame.inc', PREBUILD),
            (SHARED / 'native-game-1.json', PREBUILD),
            (SHARED / 'placement.json', 'make -f game.mk place'),
            (BUILD / 'a2vm' / 'a2vm', 'make -C tools/a2vm all'),
            (BUILD / 'ref816' / 'ref816', 'make -C tools/ref816'),
            (BUILD / 'native' / 'levels' / 'store' / 'store.json',
             'python3 tools/native/lstore.py'),
            (BUILD / 'native' / 'levels' / 'obj' / 'ltest.lbl',
             'make -C src/native -f level.mk'),
            (BUILD / 'native' / 'levels' / 'setup' / 'tour-sk2-01.img',
             'python3 tools/native/level_check.py --setup'),
            (SHARED / 'tic' / 'demo3.json.z',
             'python3 tools/native/ticcap.py --runs demo3,demo1,demo2,'
             'newgame,tour'),
            (SHARED / 'survey' / 'tour.json.z',
             'python3 tools/native/gamecap.py --survey'),
            (FLOW / 'logs' / 'tour.json.z', TOOL + ' --logs'),
            (FLOW / 'cases' / 'tour' / 'base.ram.z', TOOL + ' --capture'),
            (FLOW / 'cases' / 'demo3' / 'HU_Ticker', TOOL + ' --capture')):
        if not p.exists():
            return '%s is missing: %s' % (p.relative_to(ROOT), how)
    return ''


_BUILT = []


def build():
    """The part's image, built once a process."""
    F = _tool()
    if not _BUILT:
        F.make_part()
        _BUILT.append(F.load_build())
    return _BUILT[0]


@unittest.skipIf(missing(), missing())
class Build(unittest.TestCase):
    def test_builds_and_sizes(self):
        F = _tool()
        b = build()
        sizes = F.part_sizes(b)
        self.assertGreater(sizes['gflow'], 0)
        self.assertGreater(sizes['gwi'], 0)
        # every entry of the part table is a label of the image
        names = json.loads(F.ARGS.read_text())['entries']
        for key, spec in names.items():
            self.assertIn(spec['native'], b.labels, key)


SAMPLE = 6                      # cases an entry (all synthetic ones too)
COMBOS = ((0xA5, 'f121'), (0x5A, 'fastpath'))


def sample(paths, k=SAMPLE):
    synth = [p for p in paths if p.name.startswith('s-')]
    real = [p for p in paths if not p.name.startswith('s-')]
    step = max(1, len(real) // k)
    return real[::step][:k] + synth


@unittest.skipIf(missing(), missing())
class Checkpoint(unittest.TestCase):
    def check(self, key, k=SAMPLE):
        F = _tool()
        build()
        paths = sample([p for _, p in F.all_cases(key)], k)
        self.assertTrue(paths, 'no case of %s: %s --capture' % (key, TOOL))
        res = F.run_entry(key, paths=paths, combos=COMBOS, jobs=2)
        bad = [r for r in res if not r.get('ok')]
        self.assertEqual(bad, [], '%s: %s' % (key, json.dumps(bad[:2])[
            :1500]))
        self.assertEqual(sum(r.get('strays', 0) for r in res), 0)

    def test_readDemoTiccmd(self):
        self.check('g_game65.s:readDemoTiccmd')

    def test_G_CheckDemoStatus(self):
        self.check('g_game65.s:G_CheckDemoStatus')

    def test_doCompleted(self):
        self.check('g_game65.s:doCompleted', 8)

    def test_WI_Ticker(self):
        self.check('wi_stuff65.s:WI_Ticker')

    def test_WI_small(self):
        for key in ('wi_stuff65.s:WI_End',
                    'wi_stuff65.s:WI_checkForAccelerate'):
            with self.subTest(key=key):
                self.check(key, 3)

    def test_st_hu_tick(self):
        for key in ('st_stuff65.s:ST_Ticker', 'hu_stuff65.s:HU_Ticker'):
            with self.subTest(key=key):
                self.check(key)

    def test_small_entries(self):
        for key in ('g_game65.s:G_DeferedInitNew',
                    'g_game65.s:G_DeferedPlayDemo',
                    'g_game65.s:G_ExitLevel',
                    'g_game65.s:G_SecretExitLevel',
                    'g_game65.s:G_WorldDone',
                    'g_game65.s:G_ReloadDefaults',
                    'g_game65.s:checkOverrun'):
            with self.subTest(key=key):
                self.check(key, 3)

    def test_load_actions(self):
        for key in ('g_game65.s:doNewGame', 'g_game65.s:doPlayDemo',
                    'g_game65.s:loadLevel'):
            with self.subTest(key=key):
                self.check(key, 1)

    def test_world_done_loads(self):
        # every world-done load of the tour; the first (E1M1 to E1M2) and
        # the fourth (E1M9 to E1M4) differ in texturetranslation after the
        # load until the load resets it as upstream's does
        # (docs/game-parts/flow.md, request 6: r_data65.s:458)
        self.check('g_game65.s:doWorldDone', 8)


@unittest.skipIf(missing(), missing())
class Sweeps(unittest.TestCase):
    combos = ((0xA5, 'f121'),)

    def check(self, got):
        self.assertEqual(got['failed'], 0, got['first'])
        self.assertEqual(got['strays'], 0)
        self.assertGreater(got['calls'], 0)

    def test_readDemoTiccmd_every_tic(self):
        F = _tool()
        b = build()
        for run in ('demo3', 'demo1', 'demo2'):
            with self.subTest(run=run):
                self.check(F.sweep_demo(run, b, self.combos))

    def test_st_hu_every_tic(self):
        F = _tool()
        b = build()
        self.check(F.sweep_st('demo3', b, self.combos))
        self.check(F.sweep_hu('demo3', b, self.combos))

    def test_WI_Ticker_every_intermission_tic(self):
        F = _tool()
        b = build()
        self.check(F.sweep_wi('tour', b, self.combos))


@unittest.skipIf(missing() or not (BUILD / 'native' / 'math' / 'mathref')
                 .exists(), missing() or 'build/native/math/mathref is '
                 'missing: make -C tools/native')
class Random(unittest.TestCase):
    def test_helpers(self):
        F = _tool()
        b = build()
        for name in F.HELPERS:
            with self.subTest(helper=name):
                r = F.compare_helper(name, 3000, b)
                self.assertEqual(r['failed'], 0, r['first'])
                self.assertGreaterEqual(r['inputs'], 3000)

    def test_planted_helper_caught(self):
        F = _tool()
        r = F.random_plant(300)
        self.assertGreater(r['failed'], 0, 'times100 without its * 64 term '
                           'passed the random check')


@unittest.skipIf(missing(), missing())
class Plants(unittest.TestCase):
    def test_each_caught(self):
        F = _tool()
        build()
        for name in F.PLANTS:
            with self.subTest(plant=name):
                r = F.run_plant(name)
                self.assertTrue(r['cases'] > 0, name)
                self.assertTrue(r['caught'], '%s not caught (%d cases)' % (
                    name, r['cases']))


@unittest.skipIf(missing(), missing())
class Stops(unittest.TestCase):
    def test_victory_is_the_finale_stop(self):
        F = _tool()
        b = build()
        self.assertEqual(F.stop_of(b, 'victory'),
                         F.GL.GS['FINALE'])


if __name__ == '__main__':
    unittest.main()
