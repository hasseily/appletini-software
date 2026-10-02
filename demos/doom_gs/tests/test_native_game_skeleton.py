"""Milestone 10's skeleton: checkpoint S (docs/GAME.md 3.9).

  S1  milestone 9's acceptance on the final layouts: every setup equal to
      ref816's from both fills (no stray write), checkpoint B, the disk
      check, frame8.py on the loaded levels with validcount joined
  S2  the routine harness on milestone 9's routines in play (demo3's
      captures, both fills): P_SpawnMobj (every z mode), P_SetThingPosition,
      P_CreateSecNodeList (both branches of LR_USE); a mobj with no
      function spawned; the grep check
  S3  the tic level's reference side: the fixed runs decoded with no bridge
      problem, the schedule, the setups' re-key records, the T3 windows
      and the wraps in them, the same-pair hits, the I_GetTime values, the
      menu's actions; a generated stream played; the native machinery
      (ticrun.py --selftest)
  S4  LNSECF, LNSECB, RJROW against LNSEC, SS_ROW on every setup dump, and
      the re-keying a round trip
  S5  the runtime on hand-made data (gselftest.py), both fills
  S6  glayout's check, gcallgraph's check and stack bound, the bridge's
      additions and the snapshot stream (their test classes, run here too)
  S7  the planted bugs, each caught: a missed write-back and gp_secnodes
      walking with LR_USE set (S2); FCALL not reloading the caller's
      group, FCALL restoring only a same-slot caller's, gspawn's g_put
      past the cache, GA_PLAYDEMO without demoplayback (S5); RJROW of the
      wrong sector (S4)

Each class skips, naming the command that makes what it needs, when
build/ lacks it: the shared outputs and the skeleton's image come from
`make -s -C src/native -f game.mk shared skel ROOT=$PWD` (the runner's
prebuild), the captures from tools/native/gamecap.py, the tic references
from tools/native/ticcap.py, the generated stream from
tools/native/ticgen.py.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

# S6: the bridge's additions and the snapshot stream, run here too
from test_bridge_game import CompareModes, ManifestFeatures, \
    TicDecoding  # noqa: E402,F401
from test_a2vm_harness import SnapshotStream  # noqa: E402,F401

ROOT = support.ROOT
BUILD = ROOT / 'build'
GAME = BUILD / 'native' / 'game'
SHARED = GAME / 'shared'
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
PREBUILD = ('make -s -C src/native -f game.mk shared skel ROOT=$PWD (the '
            'parallel runner\'s prebuild)')


def have_skeleton() -> bool:
    return HAVE_CC65 and (GAME / 'skel' / 'skel.lbl').exists() and \
        (SHARED / 'native-game-1.json').exists() and \
        (BUILD / 'native' / 'levels' / 'store' / 'store.json').exists()


def have_bases() -> bool:
    from native import gameroutine as GR
    return all(GR.base_path(m).exists() for m in range(1, 10))


def have_setups() -> bool:
    return (BUILD / 'native' / 'levels' / 'setups' / 'demo3-01' /
            'r.ram.z').exists()


def have_cases() -> bool:
    from native import gamecap as GC
    return all(list(GC.case_dir('demo3', k).glob('h*.case.z'))
               for k in ('p_spawn65.s:P_SpawnMobj',
                         'p_map65.s:P_SetThingPosition',
                         'p_map65.s:P_CreateSecNodeList'))


# The frame check on loaded levels runs an even sample by default;
# DOOM_GS_FULL=1 runs all 729 frames (about 18 minutes alone), as the
# acceptance runs of milestones 9 and 10 do (tests/README.md).
FULL = os.environ.get('DOOM_GS_FULL') == '1'

needs_skeleton = unittest.skipUnless(
    have_skeleton(), 'needs the skeleton\'s image and the shared outputs: ' +
    PREBUILD + ', and milestone 9\'s store (python3 tools/native/wadconv.py '
    '--store)')
needs_bases = unittest.skipUnless(
    have_skeleton() and have_setups() and have_bases(),
    'needs milestone 9\'s setup dumps and kept setup machines: python3 '
    'tools/native/setupcap.py, then python3 tools/native/level_check.py '
    '--setup')
needs_cases = unittest.skipUnless(
    have_skeleton() and have_bases() and have_cases(),
    'needs demo3\'s captures of the three routines: python3 tools/native/'
    'gamecap.py --survey, then --capture FILE:LABEL --run demo3 --all for '
    'p_spawn65.s:P_SpawnMobj, p_map65.s:P_SetThingPosition and '
    'p_map65.s:P_CreateSecNodeList')


# ---------------------------------------------------------------------------
# S6 (with the classes imported above)
# ---------------------------------------------------------------------------

class S6Layouts(unittest.TestCase):
    def test_glayout_check(self):
        from native import glayout as GL
        GL.check()
        self.assertEqual(len(GL.PARTS), 29)
        self.assertLessEqual(GL.RT_USED, 256)

    def test_scratch_blocks_fit(self):
        from native import glayout as GL
        sb = GL.scratch_blocks()
        self.assertEqual(len(sb), 29)
        lo, hi = GL.WR['SCRATCH']
        for a, n in sb.values():
            self.assertTrue(lo <= a and a + n <= hi)

    @unittest.skipUnless((ROOT / 'build' / 'linkmap.json').exists(),
                         'needs build/linkmap.json')
    def test_callgraph_check_and_stack(self):
        from native import gcallgraph as CG
        g = CG.load(write=False)
        self.assertEqual(CG.check(g), [])
        depth = CG.stack_depth(g)
        self.assertTrue(depth['ok'], depth)
        self.assertGreater(len(depth['chain']), 2)
        self.assertLessEqual(depth['total'], depth['budget'])


# ---------------------------------------------------------------------------
# S5 and its planted bugs (S7)
# ---------------------------------------------------------------------------

@needs_bases
class S5Runtime(unittest.TestCase):
    def test_both_fills(self):
        from native import gselftest as ST
        for fill in (0xA5, 0x5A):
            with self.subTest(fill='%02x' % fill):
                res = ST.run_all(fill)
                self.assertEqual({k: v for k, v in res.items() if v}, {})


@needs_bases
class S7RuntimePlants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        from native import gselftest as ST
        for name in ST.PLANTS:
            with self.subTest(name):
                self.assertNotEqual(ST.run_plant(name), [],
                                    '%s was not caught' % name)


# ---------------------------------------------------------------------------
# S4 and its planted bug (S7)
# ---------------------------------------------------------------------------

@needs_bases
class S4Tables(unittest.TestCase):
    def test_all_setup_dumps(self):
        from native import ticcap as TC
        rep = TC.check_tables(say=lambda *a: None)
        self.assertGreaterEqual(len(rep['setups']), 57)
        self.assertEqual(rep['failures'], [])

    def test_rjrow_of_the_wrong_sector_is_caught(self):
        from native import ticcap as TC
        rep = TC.planted_tables()
        self.assertTrue(rep['failures'])
        self.assertTrue(any('RJROW' in f for f in rep['failures']))


# ---------------------------------------------------------------------------
# S2 and its planted bugs (S7)
# ---------------------------------------------------------------------------

@needs_cases
class S2Routines(unittest.TestCase):
    SAMPLE = 10         # every 10th case of each routine, both fills
                        # (gameroutine.py --s2 runs them all)

    @classmethod
    def setUpClass(cls):
        from native import gameroutine as GR
        cls.rep = GR.s2(sample=cls.SAMPLE, jobs=4, say=lambda *a: None)

    def test_no_failure(self):
        self.assertEqual(self.rep['failures'], [])

    def test_each_routine_equal(self):
        for key, r in self.rep['routines'].items():
            with self.subTest(key):
                self.assertGreater(r['classes'].get('equal', 0), 0)
                self.assertNotIn('failed', r['classes'])

    def test_every_z_mode(self):
        by = self.rep['routines']['p_spawn65.s:P_SpawnMobj']['by']['z']
        for mode in ('floor', 'given'):
            for fill in ('a5', '5a'):
                self.assertGreater(by.get('%s=equal/%s' % (mode, fill), 0), 0)
        ceil = self.rep['ceiling_synthetic']
        self.assertEqual((ceil['equal'], ceil['runs'] > 0), (ceil['runs'],
                                                             True))

    def test_both_branches_of_lr_use(self):
        by = self.rep['routines']['p_map65.s:P_CreateSecNodeList']['by'][
            'lr_use']
        for lr in (0, 1):
            self.assertGreater(by.get('%d=equal/a5' % lr, 0), 0)
            self.assertGreater(by.get('%d=equal/5a' % lr, 0), 0)

    def test_the_grep_check(self):
        self.assertEqual(self.rep['grep'], [])


@needs_cases
class S2NoFunction(unittest.TestCase):
    def test_a_mobj_with_no_function(self):
        """A spawn whose state never ends gets no thinker (addIfFunc): the
        in-play drops of demo3 (P_SpawnMobj of types whose spawn state
        has tics -1), both fills."""
        from native import gamecap as GC, gameroutine as GR, grun as G
        b = G.load_build(G.GAME / 'skel', 'skel')
        spec = GR.all_args()['p_spawn65.s:P_SpawnMobj']
        cm = GC.CallerMap()
        ran = 0
        for p in GR.case_paths('demo3', 'p_spawn65.s:P_SpawnMobj'):
            c = GC.load_case(p)
            if GR.caller_of(c, cm) != 'p_inter65.s:playerDamage':
                continue
            for fill in (0xA5, 0x5A):
                r = GR.run_case(c, spec, b, fill)
                self.assertTrue(r.ok, r.get('diff') or r.get('error'))
                ran += 1
        self.assertGreater(ran, 0)


@needs_cases
class S7RoutinePlants(unittest.TestCase):
    def test_each_plant_is_caught(self):
        from native import gameroutine as GR
        for name in GR.S2_PLANTS:
            with self.subTest(name):
                r = GR.run_s2_plant(name, n=8)
                self.assertGreater(r['cases'], 0)
                self.assertGreater(r['failed'], 0, '%s was not caught' %
                                   name)

    def test_the_grep_check_sees_a_g_put_past_the_cache(self):
        from native import gameroutine as GR, gselftest as ST
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-grep-', dir=str(BUILD)))
        try:
            src = GR.SRC / 'gthink.s'
            (tmp / 'gthink.s').write_text(src.read_text())
            for name, old, new in ST.PLANTS['mosave-past-cache'][1]:
                p = tmp / name
                p.write_text(p.read_text().replace(old, new, 1))
            self.assertTrue(GR.grep_check(tmp, ('gthink.s',)))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------

def tic_ref(run):
    from native import ticcap as TC
    return TC.load(run)


@unittest.skipUnless(
    (SHARED / 'tic' / 'demo3.json.z').exists(),
    'needs the tic references: python3 tools/native/ticcap.py --runs '
    'demo3,demo1,demo2,newgame,tour')
class S3Reference(unittest.TestCase):
    def test_demo3(self):
        r = tic_ref('demo3')
        self.assertEqual(r['tics_decoded'], 2134)
        self.assertEqual(r['tics_with_problems'], 0)
        self.assertEqual(r['run_problems'], [])
        self.assertEqual(r['tics_a_frame']['median'], 4)
        self.assertEqual(len(r['setups']), 1)
        self.assertTrue(all('rekey' in s for s in r['setups']))

    def test_the_fixed_runs(self):
        from native import gamecap as GC, glayout as GL
        for run in GC.RUNS:
            r = tic_ref(run)
            if r is None:
                self.skipTest('no tic reference of %s: python3 tools/native/'
                              'ticcap.py --runs %s' % (run, run))
            with self.subTest(run):
                self.assertEqual(r['tics_with_problems'], 0,
                                 r['first_problems'])
                self.assertEqual(r['run_problems'], [])
                for s in r['setups']:
                    self.assertEqual(len(bytes.fromhex(s['rekey'])),
                                     GL.REKEY_RECORD)
                # a wrap inside a T3 window goes to the owner before the
                # acceptance: never passed silently
                self.assertEqual(r['wraps_in_windows'], 0,
                                 '%s: validcount wraps inside a T3 window: '
                                 '%s' % (run, r['wraps']))
                for key in ('windows', 'same_pair_hits', 'times',
                            'menu_actions', 'cheats', 'pokes'):
                    self.assertIn(key, r)
                stream = SHARED / 'tic' / (run + '.stream')
                self.assertEqual(stream.read_bytes()[:4], b'GSTR')

    def test_newgame_and_tour_streams_have_their_events(self):
        for run in ('newgame', 'tour'):
            r = tic_ref(run)
            if r is None:
                self.skipTest('no tic reference of %s' % run)
            with self.subTest(run):
                self.assertTrue(r['menu_actions'] or r['cheats'] or
                                r['pokes'] or r['times'])
        tour = tic_ref('tour')
        if tour is not None:
            self.assertTrue(tour['pokes'])          # _g_wminfo + 4
            self.assertTrue(tour['cheats'])         # idclev, iddqd


@unittest.skipUnless(
    list((SHARED / 'streams').glob('G*.json')) if (SHARED /
                                                    'streams').exists()
    else False,
    'needs a generated stream: python3 tools/native/ticgen.py --stream G1')
class S3Generated(unittest.TestCase):
    def test_a_stream_played_to_its_end(self):
        p = sorted((SHARED / 'streams').glob('G*.json'))[0]
        r = json.loads(p.read_text())
        self.assertEqual(r['rejected'], [])
        self.assertEqual(r['problems'], [])
        self.assertGreater(r['tics'], 1000)
        self.assertTrue(p.with_suffix('.lmp').exists())


@needs_bases
class S3Native(unittest.TestCase):
    def test_the_lockstep_machinery(self):
        from native import ticrun
        r = ticrun.selftest()
        self.assertEqual(r['problems'], [])
        self.assertGreater(r['tics'], 3)


# ---------------------------------------------------------------------------
# S1
# ---------------------------------------------------------------------------

def _setups_of_run(run):
    """Milestone 9's acceptance 1 on one capture run, both fills (in a
    worker process)."""
    from native import setupcheck as SC
    rep = SC.check_setups(names=(run,))
    return {'setups': rep['setups'], 'failures': rep['failures']}


@needs_bases
class S1Milestone9(unittest.TestCase):
    def test_every_setup_both_fills(self):
        from concurrent.futures import ProcessPoolExecutor
        from native import setupcheck as SC
        runs = sorted({json.loads((g[0] / 'setup.json').read_text())['run']
                       for g in SC.groups()})
        setups, failures = 0, []
        with ProcessPoolExecutor(max_workers=4) as pool:
            for rep in pool.map(_setups_of_run, runs):
                setups += len(rep['setups'])
                failures += rep['failures']
                self.assertTrue(all(all(f['ok'] for f in s['fills'].values())
                                    for s in rep['setups'].values()))
        self.assertEqual(failures, [])
        self.assertGreaterEqual(setups, 57)

    def test_checkpoint_b_and_frame8_on_loaded_levels(self):
        from native import frame8 as F8, level_check as K, lrun
        from native import framestate as FS
        from native import render_check as RC
        if not (RC.OBJ / 'ftest.lbl').exists():
            self.skipTest('needs the render build (render.mk)')
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-s1-', dir=str(BUILD)))
        saved = (lrun.LOADED, FS.LEVEL_HOOK)
        try:
            lrun.LOADED = tmp / 'loaded'
            K.LOADED = lrun.LOADED
            rep = K.check_load()
            self.assertEqual(rep['failures'], [])
            out = tmp / 'frames.json'
            if FULL:
                pick = ['--sets', 'm7,demo3']
            else:
                # An even sample: every 20th frame of the 734 in order,
                # every set represented (DOOM_GS_FULL=1 runs all of them).
                dirs = RC.frame_dirs(None, 'm7,demo3')
                names = [d.name for i, d in enumerate(dirs) if i % 20 == 0]
                pick = ['--frames', ','.join(names)]
            code = F8.main(['--levels', 'loaded'] + pick +
                           ['--jobs', '6', '--json', str(out), '--no-build'])
            res = json.loads(out.read_text())
            self.assertEqual(code, 0)
            if FULL:
                # 729 frames from both fills (milestone 9: 1,458 runs)
                self.assertEqual(len(res), 1458)
            else:
                self.assertGreaterEqual(len(res), 60)
                self.assertGreater(len({r['frame'].rsplit('-', 1)[0]
                                        for r in res}), 4)
            self.assertEqual([r['frame'] for r in res if r['problems']], [])
        finally:
            lrun.LOADED, FS.LEVEL_HOOK = saved
            K.LOADED = lrun.LOADED
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_the_disk(self):
        from native import ldisk, lrun
        try:
            bd = ldisk.disk_writer()
        except Exception as e:      # pragma: no cover (the writer's tree)
            self.skipTest('the disk writer: %s' % e)
        if not bd.DEFAULT_MASTER.is_file():
            self.skipTest('needs appletini-one\'s ProDOS (%s)'
                          % bd.DEFAULT_MASTER)
        disk = ldisk.build(lrun.OBJ)
        work = Path(tempfile.mkdtemp(prefix='tmp-m10-disk-', dir=str(BUILD)))
        try:
            r = ldisk.check(disk, work, 'fastpath')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        self.assertEqual(r['problems'], [])
        self.assertTrue(all(x['canonical'] == 'equal' for x in r['loads']))


if __name__ == '__main__':
    unittest.main()
