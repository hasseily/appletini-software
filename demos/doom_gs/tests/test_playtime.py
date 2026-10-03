"""tools/native/playtime.py, the play build's timing (docs/SPEED.md 1-2),
and the exact idle skip of playdisk.run.

Reading: frames cut at the kernel's K_END dispatches, their steps named
by the K_CALL's target and the K_LOAD's bank (the front end's and the
masked image's K_WLOAD and K_MLOAD), the group loads counted in K_TIC
only, the memory-API requests by kind, the cuts by gametic and by time
(synthetic PC logs, no build).
The idle: on the title loop, where the brain's frame wait does spin, the
exact skip gives the frames of a run with no skip at all (two bounded
a2vm runs of 12 s of model time; skipped when build/ lacks the play
build).
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from support import ROOT

sys.path.insert(0, str(ROOT / 'tools'))

from native import playdisk as P, playtime as T  # noqa: E402

HZ = 1000.0                     # a clock a ms, for the synthetic logs


def probe() -> T.Probe:
    names = {0x6593: ['nr_frame'], 0x6800: ['OVLW', 'nm_masked'],
             0x660B: ['s2_frame'], 0x6600: ['palw_level', 's2_poll']}
    return T.Probe({}, ['lc.FF9B', 'lc.FF9C', '1DC0', '1DC1', '1DC2',
                        '1DC3'], names, {0x6B: 'P2DW', 0x5D: 'OVLW',
                                         0x70: 'WCODE', 0x71: 'MCODE'}, HZ,
                   {5: 1000, 9: 512}, {5: 1, 9: 3},
                   {0x6B: (1, 7936), 0x70: (2, 18944), 0x71: (2, 10496)},
                   {'planes_out': (1, 40), 'dl_rsback': (2, 41)})


def ln(t, name, target=0, gametic=0, y=0, x=0, more=()) -> T.Line:
    return T.Line(t, name, 0, x, y, target, gametic, more)


def frame_lines(t, g, tics=4, loads=3, irqs=2):
    """One level frame from t (ms), gametic g at its K_END."""
    out = [ln(t, 'k_end', gametic=g),
           ln(t, 'k_tcore', gametic=g, more=(52, 2, 0, 0, 0, 0)),
           ln(t + 0.5, 'k_tplan', gametic=g, more=(52, 2, 0, 0, 0, 0))]
    for i in range(loads):
        out.append(ln(t + 1 + i, 'gr_load', gametic=g))
    out += [ln(t + 1, 'am_one', gametic=g, x=5),        # a W slot's
            ln(t + 1.25, 'gr_loaded', gametic=g),
            ln(t + 2, 'am_one', gametic=g, x=9),        # a frame slot's
            ln(t + 2.5, 'gr_loaded', gametic=g),
            ln(t + 3, 'planes_out', gametic=g, more=(52, 2, 0, 2, 7, 41)),
            ln(t + 4, 'planes_out', gametic=g, more=(52, 2, 0, 2, 40, 41)),
            ln(t + 4.5, 'fs_restore', gametic=g),
            ln(t + 5, 'dl_rsback', gametic=g, more=(52, 2, 0, 2, 40, 41)),
            ln(t + 10, 'k_load', gametic=g + tics),
            ln(t + 10, 'k_lrun', gametic=g + tics, y=0x70),
            ln(t + 12, 'k_call', gametic=g + tics),
            ln(t + 12, 'k_jsr', 0x6593, g + tics),
            ln(t + 20, 'k_load', gametic=g + tics),
            ln(t + 20, 'k_lrun', gametic=g + tics, y=0x71),
            ln(t + 21, 'gr_load', gametic=g + tics),   # not a tic's
            ln(t + 21, 'am_one', gametic=g + tics),    # not a tic's
            ln(t + 22, 'k_call', gametic=g + tics),
            ln(t + 22, 'k_jsr', 0x6800, g + tics),
            ln(t + 30, 'k_load', gametic=g + tics),
            ln(t + 30, 'k_lrun', gametic=g + tics, y=0x6B),
            ln(t + 32, 'k_call', gametic=g + tics),
            ln(t + 32, 'k_jsr', 0x660B, g + tics)]
    for i in range(irqs):
        out.append(ln(t + 5 + i, 'pl_vbl', gametic=g))
    return sorted(out, key=lambda x: x.t)


class Reading(unittest.TestCase):

    def lines(self):
        out = []
        for i in range(5):
            out += frame_lines(100 * i, 4 * i)
        out.append(ln(500, 'k_end', gametic=20))
        return out

    def test_frames_and_steps(self):
        frames = T.frames_of(self.lines(), probe())
        self.assertEqual(len(frames), 5)
        f = frames[1]
        self.assertEqual((f.start, f.end, f.gametic, f.tics),
                         (100, 200, 8, 4))
        self.assertEqual(f.steps, [('K_TIC', 10), ('K_WLOAD', 2),
                                   ('nr_frame', 8), ('K_MLOAD', 2),
                                   ('nm_masked', 8), ('K_LOAD P2DW', 2),
                                   ('s2_frame', 68)])
        self.assertEqual(f.loads, 3)        # K_TIC's only
        self.assertEqual(f.irqs, 2)
        # the requests: a kind each (planes_out's second line, its group
        # in slot 1, is the one), the kernel's loads by their lists
        self.assertEqual(f.amem['W slot'], [1, 1, 1000, 0.25])
        self.assertEqual(f.amem['frame slot'], [1, 1, 512, 0.5])
        self.assertEqual(f.amem['planes out'], [1, 4, 4 * 512, 0.5])
        self.assertEqual(f.amem['restore'], [1, 1, 512, 0.5])
        self.assertEqual(f.amem['K_TIC core'], [1, 1, 52 * 256, 0.5])
        self.assertEqual(f.amem['K_TIC planes'], [1, 4, 4 * 512, 0.5])
        self.assertEqual(f.amem['K_LOAD'], [3, 5, 18944 + 10496 + 7936, 6])
        r = T.report(frames, probe(), 'g', None, (4, 16))
        self.assertEqual(r['private']['all']['requests_frame'], 9.0)
        self.assertEqual(r['private']['W slot']['us_request'], 250.0)

    def test_report_by_gametic_and_by_time(self):
        frames = T.frames_of(self.lines(), probe())
        r = T.report(frames, probe(), 'g', None, (4, 16))
        self.assertEqual(r['frames'], 3)    # ends at gametics 8, 12, 16
        self.assertEqual(r['gametic'], [4, 16])
        self.assertEqual(r['ms_mean'], 100.0)
        self.assertEqual(r['fps'], 10.0)
        self.assertEqual(r['tics_frame'], 4.0)
        self.assertEqual(r['tics_second'], 40.0)
        self.assertEqual(r['loads_tic'], 0.75)
        self.assertEqual(list(r['steps_ms'])[:3],
                         ['K_TIC', 'K_WLOAD', 'nr_frame'])
        self.assertEqual(sum(r['steps_ms'].values()), 100.0)
        r = T.report(frames, probe(), 't', (0.1, 0.4), None)
        self.assertEqual(r['frames'], 3)    # 100-200, 200-300, 300-400
        with self.assertRaises(T.TimeError):
            T.report(frames, probe(), 'g', None, (100, 200))

    def test_call_names(self):
        pr = probe()
        self.assertEqual(T.call_name(pr, 0x6800, 'MCODE'), 'nm_masked')
        self.assertEqual(T.call_name(pr, 0x6800, 'OVLW'), 'OVLW')
        self.assertEqual(T.call_name(pr, 0x6800, None), 'OVLW|nm_masked')
        self.assertEqual(T.call_name(pr, 0x6600, 'PALW'), 'palw_level')
        self.assertEqual(T.call_name(pr, 0x1234, None), 'call $1234')

    def test_scripts(self):
        self.assertEqual(T.scene_script('demo3', HZ), '')
        walk = T.scene_script('walk', 1.0)
        self.assertIn('cycle 12 hold 0x0B', walk)
        self.assertEqual(walk.count('mouse 160 0'), 10)


GONE = P.missing()
needs_build = unittest.skipUnless(
    not GONE and (P.PLAY / 'tic').is_dir(),
    'build/ lacks the play build: %s' % '; '.join(GONE or ['native/play']))


@needs_build
class ExactIdle(unittest.TestCase):

    def test_title_loop_as_without_a_skip(self):
        """The title loop runs at 35 frames a second: the brain's frame
        wait spins, and the skip must give the frames of a run where it
        spins (docs/SPEED.md 1, "The measurement artifact")."""
        # one copy of the play link for both runs (a test elsewhere may
        # rebuild build/native/play meanwhile)
        tmp = Path(tempfile.mkdtemp(prefix='tmp-playtime-test-',
                                    dir=str(P.BUILD)))
        self.addCleanup(shutil.rmtree, str(tmp), True)
        play = tmp / 'play'
        shutil.copytree(str(P.PLAY), str(play))
        runs = {idle: T.measure('demo3', disk=None, play=play,
                                window=(2.0, 12.0), seconds=12.0, idle=idle,
                                timeout=600)
                for idle in ('exact', 'none')}
        exact, none = runs['exact'], runs['none']
        self.assertGreater(exact['idle_skipped_ms'], 1000)
        self.assertEqual(none['idle_skipped_ms'], 0)
        self.assertGreater(exact['frames'], 100)
        for key in ('frames', 'gametic', 'tics_frame', 'loads_frame'):
            self.assertEqual(exact[key], none[key], key)
        for key in ('ms_mean', 'ms_median', 'ms_max'):
            self.assertAlmostEqual(exact[key], none[key], delta=0.05,
                                   msg=key)


if __name__ == '__main__':
    unittest.main()
