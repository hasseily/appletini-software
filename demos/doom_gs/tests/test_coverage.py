"""The coverage scripts (coverage/*.script) on the release image: each
runs to its stop, twice the same, with nothing that would make the run
meaningless (tools/ref816/run_script.py), and its shots show what the
script says they show.

The scripts run at the IIgs's own CPU rate, and newgame.script also at
12 MHz, the rate of the accelerator the game wants. They need
build/release/doom-hd.hdv and build/linkmap.json, and skip without them;
they take about 30 seconds of host time.
"""

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

import support
from ref816 import make_image, run_script, shot, title
from test_ref816_machine import have_tools, needs_linkmap

SCRIPTS = ('title', 'newgame', 'viewsize', 'tour')
E1M1_VIEWS = ('still-00s', 'still-05s', 'still-10s', 'walk', 'turned',
              'fire', 'door-opening', 'door-open', 'through')
# The window of the view at each size (left, top, width, height, as
# tools/ref816/shot.py view_stats finds it): that fraction of the 320x168
# of the full view, as the game rounds it (the 2/3 view is 214 wide, the
# 1/3 view 108), about centred above the status bar.
SIZES = {'full': (0, 0, 320, 168), '3-4': (40, 21, 240, 126),
         '2-3': (52, 28, 214, 112), '1-2': (80, 42, 160, 84),
         '1-3': (106, 56, 108, 56), '1-4': (120, 63, 80, 42)}
TOUR = (1, 2, 3, 9, 4, 5, 6, 7, 8)


@have_tools
@support.needs_release
@needs_linkmap
class Coverage(unittest.TestCase):
    reports = {}

    @classmethod
    def setUpClass(cls):
        title.build_machine()
        with contextlib.redirect_stdout(io.StringIO()):
            if make_image.main([]):
                raise AssertionError('make_image.py failed')
        cls.out = Path(tempfile.mkdtemp(dir=str(title.OUT)))
        runs, shots = cls.out / 'runs', cls.out / 'shots'
        for name in SCRIPTS:
            cls.reports[name] = run_script.run(
                run_script.script_path(name), twice=True, runs=runs,
                shots=shots)
        cls.reports['newgame-12mhz'] = run_script.run(
            run_script.script_path('newgame'), cpu_hz=12000000, twice=True,
            runs=cls.out / 'runs-12mhz', shots=cls.out / 'shots-12mhz')
        cls.dumps = {name: runs / name / 'dumps' for name in SCRIPTS}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.out))

    def view(self, script, name):
        return self.reports[script]['shots'][name]

    def test_every_script_runs_to_its_stop_twice_the_same(self):
        for name, report in self.reports.items():
            self.assertEqual(report['problems'], [], name)
            self.assertEqual(report['end']['reason'], 'stop', name)
            self.assertTrue(report['deterministic'], name)

    def test_the_title_demo_plays_twenty_seconds(self):
        report = self.reports['title']
        (demo,) = report['intervals']
        self.assertGreaterEqual(demo['seconds'], 20)
        self.assertGreaterEqual(demo['frames_measured'], 20)
        for name in ('demo-05s', 'demo-10s', 'demo-15s', 'demo-20s',
                     'demo-25s'):
            self.assertTrue(self.view('title', name)['full_3d_view'], name)
        self.assertEqual(len(report['shots']), 7)

    def test_e1m1_shows_a_3d_view(self):
        for script in ('newgame', 'newgame-12mhz'):
            for name in E1M1_VIEWS:
                self.assertTrue(self.view(script, name)['full_3d_view'],
                                (script, name))
            for name in ('menu', 'skill'):
                self.assertFalse(self.view(script, name)['full_3d_view'],
                                 (script, name))
            (still,) = self.reports[script]['intervals']
            self.assertGreaterEqual(still['frames_measured'], 20)

    def test_the_view_changes_through_the_door(self):
        dumps = self.dumps['newgame']
        before = shot.render((dumps / 'turned.shr').read_bytes())
        after = shot.render((dumps / 'through.shr').read_bytes())
        changed = sum(1 for a, b in zip(before.rows[:shot.STATUS_ROW],
                                        after.rows[:shot.STATUS_ROW])
                      for x, y in zip(a, b) if x != y)
        self.assertGreater(changed, 320 * shot.STATUS_ROW // 2)

    def test_every_view_size(self):
        for size, window in SIZES.items():
            names = ['size-' + size]
            names += [] if size == '1-4' else ['size-%s-again' % size]
            for name in names:
                view = self.view('viewsize', name)['view']
                self.assertEqual(tuple(view['window']), window, name)
                self.assertTrue(view['status_palettes_apart'], name)
        self.assertTrue(self.view('viewsize', 'size-full')['full_3d_view'])
        self.assertFalse(self.view('viewsize', 'menu-1-3')['full_3d_view'])

    def test_the_tour_sees_nine_maps(self):
        pictures = set()
        for level in TOUR:
            name = 'e1m%d' % level
            self.assertTrue(self.view('tour', name)['full_3d_view'], name)
            pictures.add((self.dumps['tour'] / (name + '.shr')).read_bytes())
        self.assertEqual(len(pictures), len(TOUR))
        for level in TOUR[:-1]:
            self.assertFalse(
                self.view('tour', 'after-e1m%d' % level)['full_3d_view'])


if __name__ == '__main__':
    unittest.main()
