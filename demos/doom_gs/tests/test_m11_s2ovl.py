"""Milestone 11, first half, part s2ovl (docs/SCREENS.md 0.1 F9, 1.5.4,
4.1, 4.5, 7.3; docs/m11-parts/s2ovl.md): the automap's overlay, its K_OVL
records and the image OVLW (src/native/s2_ovl.s, with part s2amap's
s2_amline.s), in milestone 8's whole frame against upstream's frames of
coverage/m11/automap.script on ref816 (tools/native/s2ovl.py).

What runs here (the checkpoint, `python3 tools/native/s2ovl.py --all`,
also writes build/native/m11/s2ovl/report.json):
  - the sources and the harness without a build: s2_amline.s has request
    S2OVL-1's hook once each part, the planted edits are found once each, OVLW's link map (and the planted one), the places shared by
    s2_ovl.s, the makefile and the tool, K_OVL's staged size against
    bucket.s, the frame image's objects against render.mk's, rcanon's
    walks with K_OVL (request S2OVL-2);
  - with the build: OVLW within MASKW's code room, s2_ovl within its
    budget, OVLW's BKFAR and BKFAR2 the frame image's byte for byte, the
    frame image milestone 8's whole frame (ftest, fprof) but the driver;
  - every captured frame (21 with the overlay, 8 without) and the
    variants (titleBand with am_band 0 on two frames; every overlay frame
    after the first from the frame before's state with the AM_Ticker
    calls in between as am_ovl's A), each with both fills: milestone 8's
    whole comparison with the K_OVL records (by column, the view's then
    the overlay's), the spans, the batches, the screen after the replay
    (P5; the title band black when titleBand runs), the automap's state
    after OVLW, S2_MAIL, the write log by phase, W outside OVLW's room;
  - the five planted bugs, each in a scratch copy, caught;
  - the timing runs (f121, fastpath).

Needs cc65, build/a2vm/a2vm, ref816's machine and the release image, the
link map, milestone 8's tables (python3 tools/native/rtables.py) and part
s2cap's capture of automap.script (python3 tools/native/s2cap.py
--capture --runs automap); the frames are captured here when missing
(python3 tools/native/s2ovl.py --capture, 6 s); skips naming what is
missing.

Run by name: python3 tools/testpar.py tests/test_m11_s2ovl.py
"""

import re
import shutil
import unittest

import support

ROOT = support.ROOT
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))


def missing() -> str:
    from native import s2run
    from ref816 import make_image, title
    need = []
    if not HAVE_CC65:
        need.append('cc65 on PATH')
    if not s2run.A2VM.exists():
        need.append('build/a2vm/a2vm (make -C tools/a2vm)')
    if not (BUILD / 'native' / 'render' / 'tables' / 'tables.img').exists():
        need.append('milestone 8\'s tables (python3 tools/native/'
                    'rtables.py)')
    if not make_image.LINKMAP.exists():
        need.append('the link map (tools/v816/imgmatch.py)')
    for p in (title.MACHINE, title.MEMORY, title.DISK):
        if not p.exists():
            need.append('%s (MILESTONES.md "Setting up")' % p.name)
            break
    if not (BUILD / 'native' / 'm11' / 'cases' / 'automap' /
            'index.json').exists():
        need.append('part s2cap\'s capture of automap.script (python3 '
                    'tools/native/s2cap.py --capture --runs automap)')
    return ', '.join(need)


MISSING = missing()
needs_build = unittest.skipIf(MISSING, 'needs ' + MISSING)


class HandMade(unittest.TestCase):
    """The sources and the harness (no build needed)."""

    def test_s2_amline_has_the_hook(self):
        """Request S2OVL-1 (applied in wave 7): s2_amline.s's fast path's
        hook, each part once, and the makefile assembles it with
        AM_FASTLINE; a source without a part of it is reported."""
        import tempfile
        from pathlib import Path
        from native import s2ovl as O
        self.assertEqual(O.amline_problems(), [])
        for hook in O.AMLINE_HOOKS:
            self.assertIn('.ifdef AM_FASTLINE', hook)
        mk = (SRC / 'm11' / 's2ovl.mk').read_text()
        self.assertRegex(mk, r'(?m)^\$\(S2OV_DIR\)/s2_amline-ovl\.o: '
                         r's2_amline\.s ')
        self.assertIn('-D AM_FASTLINE', mk)
        text = (SRC / 's2_amline.s').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 's2_amline.s').write_text(
                text.replace('        jsr am_fastline', '', 1))
            self.assertEqual(len(O.amline_problems(Path(tmp))), 1)

    def test_each_planted_edit_is_found_once(self):
        from native import s2ovl as O
        self.assertEqual(len(O.PLANTED), 5)
        for fname, edits, what in O.PLANTED:
            if fname == 'ovlw.cfg':
                continue
            text = (SRC / fname).read_text()
            for old, new in edits:
                self.assertEqual(text.count(old), 1, what)
                self.assertNotEqual(old, new)

    def test_ovlw_s_link_map(self):
        from native import rlayout as R, s2ovl as O
        labels = {n: 0x1000 + k for k, n in enumerate(O.OVLW_IMPORTS)}
        labels.update({'__BKNEAR_LOAD__': 0xFD8D, '__BKFAR_LOAD__': 0x8A6A,
                       '__BKFAR_RUN__': R.BKFAR_RUN,
                       '__BKFAR_SIZE__': 0x2CA})
        text = O.ovlw_cfg_text(labels)
        self.assertIn('OVW:   start = $6800, size = $2C00', text)
        self.assertIn('BKFAR:   load = OVW, run = BFAR, type = ro, '
                      'define = yes;', text)
        self.assertIn('RCX:   start = $FD8D', text)
        for n in O.OVLW_IMPORTS:
            self.assertIn('    %s: type = export, value = $%04X;'
                          % (n, labels[n]), text)
        self.assertNotIn('__BKFAR_LOAD__', text)
        planted = O.ovlw_cfg_text(labels, planted_bkfar=True)
        self.assertIn('__BKFAR_LOAD__: type = export, value = $8A6A;',
                      planted)
        self.assertNotIn('BKFAR:   load = OVW, run = BFAR, type = ro, '
                         'define', planted)

    def test_the_places_agree(self):
        """s2_ovl.s's run time places, the makefile's AMW and AMST and the
        tool's, in OVLW's room above its stored bytes."""
        from native import s2layout as S, s2ovl as O
        ovl = (SRC / 's2_ovl.s').read_text()
        nbuf = int(re.search(r'^NBUF\s*=\s*\$([0-9A-F]+)', ovl,
                             re.M).group(1), 16)
        self.assertEqual(nbuf, O.OVLW_RT)
        mk = (SRC / 'm11' / 's2ovl.mk').read_text()
        amw = int(re.search(r'-D AMW=(\d+)', mk).group(1))
        amst = int(re.search(r'-D AMST=(\d+)', mk).group(1))
        self.assertEqual((amw, amst), (0x9A00, 0x9B00))
        lo, hi = S.IMAGE['OVLW'].stored
        self.assertTrue(lo < O.OVLW_RT < amw < amst < hi)
        self.assertEqual(hi - amst, 256)
        # s2layout's run time range of OVLW (request S2OVL-3)
        self.assertEqual([r[:2] for r in S.IMAGE['OVLW'].runtime],
                         [(O.OVLW_RT, hi)])
        drv = (SRC / 's2_ovd.s').read_text()
        self.assertIn('OVLW_ENTRY = OVLW_LO', drv)

    def test_k_ovl_s_staged_size_is_bucket_s(self):
        from native import s2ovl as O
        text = (SRC / 'bucket.s').read_text()
        row = re.search(r'^ssize:\s*\.byte (.*)$', text, re.M).group(1)
        sizes = [x.strip() for x in row.split(',')]
        self.assertEqual(sizes[O.K_OVL], str(O.OVL_NATIVE))
        ovl = (SRC / 's2_ovl.s').read_text()
        self.assertIn('OVLREC_SIZE = %d' % O.OVL_NATIVE, ovl)
        self.assertIn('K_OVL     = %d' % O.K_OVL, ovl)

    def test_the_frame_image_s_objects_are_render_mk_s(self):
        from native import s2ovl as O
        self.assertEqual(O.mk_objects('S2OV_F8'), list(O.F8_OBJS))
        self.assertEqual(O.mk_objects('S2OV_F8P'), list(O.F8P_OBJS))
        self.assertEqual(O.render_mk_objects('FTEST_OBJS'), list(O.F8_OBJS))
        self.assertEqual(O.render_mk_objects('FPROF_OBJS'),
                         list(O.F8P_OBJS))

    def test_rcanon_reads_k_ovl(self):
        """Request S2OVL-2 (applied in wave 7): rcanon's native walk reads
        K_OVL's 5 staged bytes, and a stream without it as before."""
        from native import rcanon, s2ovl as O
        rec = bytes([2, 5, 10, 20, 0x11, 0x22])          # a K_FILL, col 5
        ovl = bytes([O.K_OVL, 7, 30, 0x0F, 0xE0])
        self.assertEqual(rcanon.K_OVL, O.K_OVL)
        self.assertEqual(rcanon.NATIVE_SIZES[O.K_OVL], O.OVL_NATIVE)
        got, seq = rcanon.native_records_all(rec, {}, [])
        self.assertEqual(got, {5: [('fill', 10, 20, 0x11, 0x22)]})
        got, seq = rcanon.native_records_all(rec + ovl, {}, [])
        self.assertEqual(got[7], [('ovl', 30, 0x0F, 0xE0)])
        self.assertEqual(seq, [(5, 0), (7, 0)])
        with self.assertRaises(rcanon.CanonError):
            rcanon.native_records_all(rec + ovl[:4], {}, [])


@needs_build
class Checkpoint(unittest.TestCase):
    result = None

    @classmethod
    def setUpClass(cls):
        from native import s2ovl as O
        O.make()
        if not (O.OUT / 'capture.json').exists():
            O.capture()
        cls.result = O.run_checks(None, O.FILLS, 2, verbose=False)

    def test_the_capture(self):
        from native import s2ovl as O
        names = [d.name for d in O.frame_dirs()]
        self.assertEqual(len([n for n in names if n.startswith('ovl-')]),
                         21)
        self.assertEqual(len([n for n in names if n.startswith('plain-')]),
                         8)

    def test_the_sizes_and_the_images(self):
        from native import s2ovl as O
        s = O.sizes()
        self.assertEqual(s['problems'], [])
        self.assertLessEqual(s['s2_ovl'], O.BUDGET_OWN)
        self.assertLessEqual(s['stored'], O.OVLW_RT - 0x6800)

    def test_every_frame_and_variant(self):
        res = self.result
        problems = ['%s %s: %s' % (r['frame'], r.get('fill'), q)
                    for r in res for q in r['problems']]
        self.assertEqual(problems, [])
        self.assertEqual(len(res), 2 * (29 + 2 + 20))
        self.assertFalse([r for r in res if r.get('known')])
        ovl = [r for r in res if r.get('overlay')]
        self.assertTrue(all(r['k_ovl'] > 1000 for r in ovl))
        band = [r for r in res if r['frame'].endswith('+band0')]
        self.assertEqual(len(band), 4)
        self.assertTrue(all(r['titleband'] for r in band))
        tics = [r for r in res if r['frame'].endswith('+tics')]
        self.assertEqual(len(tics), 40)
        self.assertTrue(any(r['tics'] > 0 for r in tics))
        self.assertTrue(all(r['stack_bytes'] <= 112 for r in res))


@needs_build
class Planted(unittest.TestCase):
    def test_each_planted_bug_is_caught(self):
        from native import s2ovl as O
        O.make()
        if not (O.OUT / 'capture.json').exists():
            O.capture()
        for r in O.planted(2):
            self.assertTrue(r['caught'], r)


@needs_build
class Timing(unittest.TestCase):
    def test_the_timing_runs(self):
        from native import s2ovl as O
        O.make()
        if not (O.OUT / 'capture.json').exists():
            O.capture()
        t = O.timing(2)
        for p in O.PROFILES:
            self.assertGreater(t['load_ms'][p], 0)
            ov = t['summary'][p]['overlay']
            self.assertEqual(ov['total_ms']['n'], 21)
            self.assertGreater(ov['ovlw_work']['median'], 0)
            self.assertEqual(t['summary'][p]['plain']['ovlw']['worst'], 0)


if __name__ == '__main__':
    unittest.main()
