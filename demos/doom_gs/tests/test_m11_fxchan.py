"""Milestone 11, first half, part fxchan (docs/SCREENS.md 3, 4.4, 4.7,
7.3; tools/sound/README.md "The game side"; docs/m11-parts/fxchan.md):
the channel logic src/native/fx_chan.s, MENUW's position callback
src/native/fx_pcache.s, the host model tools/sound/fxchan.py, the cases
and checks tools/native/fxcap.py, the a2vm runs tools/native/fxcrun.py.

Without build/: the priority table as read from upstream's sfxPriority
skips with the rest (upstream's sources are in build/); the model's
mailbox rules and pickup rules on hand-made states need the math tables
too, so every test skips with a clear message without build/.

With cc65, build/a2vm/a2vm, the math tables, S2's player (make -C
src/sound), the release on ref816 (build/ref816) and the part's build
(make -f src/native/m11.mk part P=fxchan; the test makes it):

- comparison 1 and 2 (FXCH8): every captured S_StartSound, S_StartSound2,
  S_StopSound and S_UpdateSounds of demo3, DEMO1, DEMO2 and the tour (and
  the menu run's unpaused ones) equal to the reference (channel table,
  mailboxes, each adjust's audibility, SS_VOL, SS_SEP, FM) and to the
  model; the model equal to the reference;
- comparison 3: the eviction cases (ref816 --call of S_StartSound and
  S_StartSound2 from synthetic states) the same; every path of
  S_StartSound and getChannel taken by a compared call, getChannel's
  same-origin stop named unreachable with its reason;
- comparison 4: a start and the frame's sc_update with fxplay's
  fx_isplaying (FXCH8 and 3 channels);
- the 3-channel build equal to the model on every captured call stream
  and on 10,000 random call sequences;
- the MENUW linkage: the menu run's last unpaused S_UpdateSounds on the
  tic image's build, then its paused frames' on MENUW's object with
  fx_pcache after the volume changed, equal to the reference;
- the sizes within the budgets (since wave 4, FXCHAN-5) and MENUW's room;
- the planted bugs (fxcap.PLANTED), each in a scratch copy built apart.

By default (tests/README.md) comparisons 1 and 2 run every STEP-th
captured call of each run (the captures' counts still checked whole) and
the random check RANDOM_N sequences; DOOM_GS_FULL=1 runs every call and
10,000 sequences as before.

The captures (about 1 minute) are made when missing:
python3 tools/native/fxcap.py --capture.

Run by name: python3 tools/testpar.py tests/test_m11_fxchan.py
"""

import shutil
import unittest
from unittest import mock

import support

from native import fxcap as F, fxcrun as R  # noqa: E402
from sound import fxchan as FX  # noqa: E402

HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))


def ready() -> bool:
    from ref816 import title
    return HAVE_CC65 and R.A2VM.exists() and \
        (R.MATH_TABLES / 'tanto0.bin').exists() and \
        (R.MATH_TABLES / 'quartlo.bin').exists() and \
        (R.ROOT / 'build' / 'sound65' / 'player.o').exists() and \
        FX.SOUND_SRC.exists() and title.MACHINE.exists() and \
        title.MEMORY.exists()


READY = ready()
WHY = ('needs build/: cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm), '
       'the math tables (make -C src/native -f math.mk tables), S2\'s '
       'player (make -C src/sound), upstream\'s sources and the release '
       'on ref816 (MILESTONES.md "Setting up")')
needs_build = unittest.skipUnless(READY, WHY)

_BUILT = []


FULL = support.FULL
STEP = 5            # by default: every STEP-th captured call
RANDOM_N = 10000 if FULL else 1000


def built() -> None:
    if not _BUILT:
        _BUILT.append(R.make())
        missing = [r for r in F.RUNS if not (F.CAP / (r + '.json.z')).exists()]
        if missing:
            F.capture_all(missing, say=lambda *a: None)
        if not F.BASE.exists():
            F.capture_base()


@needs_build
class ModelTest(unittest.TestCase):
    def test_priority_table_is_upstreams(self):
        prio = FX.priority_table()
        self.assertEqual(len(prio), FX.constants()['CONST_NUMSFX'])
        self.assertEqual(prio[0], 0)
        self.assertTrue(all(0 <= p < 128 for p in prio))

    def test_mailbox_rules(self):
        m = FX.new_model(3)
        m.pos = lambda h: (0, 0, 0) if h == FX.LISTENER else None
        m.start(1, FX.NONE, FX.NO_HANDLE, 0, 0)
        self.assertEqual(m.mail[0].flags, FX.MX_START)
        m.start(1, FX.NONE, FX.NO_HANDLE, 0, 0)     # kills the first
        self.assertEqual(m.mail[0].flags, FX.MX_STOP | FX.MX_START)
        m.stop(FX.NONE, FX.NO_HANDLE)
        self.assertEqual(m.mail[0].flags, FX.MX_STOP)
        self.assertEqual(m.chans[0].sfx, 0)

    def test_pickup_keeps_both(self):
        m = FX.new_model(3)
        m.start(1, FX.NONE, FX.NO_HANDLE, 0, 0)
        m.start(1 | FX.PICKUP_SOUND, FX.NONE, FX.NO_HANDLE, 0, 0)
        self.assertEqual([c.sfx for c in m.chans], [1, 1, 0])


@needs_build
class CheckpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        built()

    def test_captured_calls_equal_the_reference(self):
        # the captures' calls (check_captured's), counted whole
        def compared(refs):
            return [x for x in refs
                    if not (x.op == 'update' and x.world['menu'])]
        every = {run: F.refs_of(F.load_capture(run)) for run in F.RUNS}
        whole = {run: compared(v) for run, v in every.items()}
        self.assertGreater(sum(len(v) for v in whole.values()), 5000)
        game = [x for k, v in whole.items() if k != 'menu' for x in v]
        # SCREENS.md 3: 1,304 starts, 751 stops
        self.assertEqual(sum(1 for x in game if x.op in ('start',
                                                         'start2')), 1304)
        self.assertEqual(sum(1 for x in game if x.op == 'stop'), 751)
        refs_of = F.refs_of
        with mock.patch.object(F, 'refs_of', lambda cap: support.every(
                refs_of(cap), STEP)):
            r = F.check_captured()
        self.assertEqual(r['problems'], [])
        calls = sum(x['calls'] for x in r['runs'].values())
        self.assertEqual(calls, sum(len(compared(support.every(v, STEP)))
                                    for v in every.values()))
        type(self).paths = r['paths']

    def test_evictions_and_path_coverage(self):
        r = F.check_evict()
        self.assertEqual(r['problems'], [])
        self.assertGreaterEqual(r['x4'], 2)
        cap = F.check_captured(runs=('demo3',))
        cov = F.coverage(r['paths'], cap['paths'])
        self.assertEqual(cov['problems'], [])
        self.assertEqual(set(cov['unreachable']), {'gc:same-origin'})

    def test_two_tic_case(self):
        for b in ('fxc8r', 'fxc3'):
            r = F.two_tic(b)
            self.assertEqual(r['problems'], [], b)

    def test_menu_linkage(self):
        r = F.menu_chain()
        self.assertEqual(r['problems'], [])
        self.assertGreaterEqual(r['volumes'], 1)
        self.assertGreaterEqual(r['paused'], 2)

    def test_three_channels_on_the_captured_streams(self):
        for run in ('demo3', 'demo1', 'demo2', 'tour'):
            r = F.replay3(run)
            self.assertEqual(r['failed'], 0, (run, r['problems'][:3]))
            self.assertGreater(r['calls'], 100)

    def test_three_channels_on_random_sequences(self):
        r = F.check_random(RANDOM_N)
        self.assertEqual(r['failed'], 0, r['problems'][:3])
        self.assertEqual(r['sequences'], RANDOM_N)

    def test_sizes(self):
        s = F.sizes()
        rows = '\n'.join(s['menuw_sizes'])
        self.assertIn('fx_chan', rows)
        self.assertGreater(s['fx_chan (the tic image)'], 0)
        self.assertGreater(s['fx_pcache'], 0)
        # the budgets as raised in wave 4 (FXCHAN-5) now hold
        for key in ('fx_chan (the tic image)', 'fx_chan (MENUW, -D '
                    'FXC_NOSEP)'):
            self.assertLessEqual(s[key], s['budget']['fx_chan'], key)
        self.assertLessEqual(s['fx_pcache'], s['budget']['fx_pcache'])


@needs_build
class PlantedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        built()

    def test_each_planted_bug_is_caught(self):
        for plant in F.PLANTED:
            with self.subTest(plant.name):
                self.assertNotEqual(F.run_planted(plant), [], plant.name)


if __name__ == '__main__':
    unittest.main()
