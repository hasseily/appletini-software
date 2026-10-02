"""Milestone 11, first half, part s2stbar (docs/SCREENS.md 1.5.1, 1.6,
4.1, 4.4, 4.7, 6, 7.3; docs/m11-parts/s2stbar.md): the status bar's
drawer (src/native/s2_st.s, in P2DW) and its tic side (src/native/
s2t_st.s), against ref816 and the host model (tools/native/s2stmodel.py),
which is checked against ref816 first (tools/native/s2stbar.py).

What runs here (the checkpoint, `python3 tools/native/s2stbar.py --all`,
also runs every level frame of the nine runs from both fills, plain and
poisoned, the chain over all of demo3, every tic natively and the
timing):
  - the model's rules on hand-made values (no build needed);
  - the model against ref816: every ST_Ticker of demo3 and newgame (part
    s2cap's call logs, the turned head's positions from this part's
    capture), every level frame's ST_Drawer of demo3, newgame and
    stbar.script, the synthetic frames and tics by ref816 --call;
  - the native tic side: every tic of newgame and the synthetic tics
    (every path of updateFace, ST_Start), both fills;
  - the native drawer: newgame's level frames and the synthetic frames
    (every glyph at every place, the menu's stHide), from both fills,
    plain and with the bytes the reference marked poisoned; demo3's first
    64 frames chained;
  - the coverage table (every widget x glyph x place drawn);
  - the sizes: s2_st 2,000 B, s2t_st 900 B;
  - the six planted bugs, each in a scratch copy of the sources.

Needs cc65, build/a2vm/a2vm, the math tables, ref816 with the release,
the release image and DOOM1.WAD, part s2cap's cases, part s2data's store
(make -C src/native -f m11.mk part P=s2data), part s2draw's truth base
(python3 tools/native/s2drawcase.py) and this part's capture
(python3 tools/native/s2stbar.py --capture); skips naming what is
missing.

Run by name: python3 tools/testpar.py tests/test_m11_s2stbar.py
"""

import shutil
import unittest

import support

ROOT = support.ROOT
BUILD = ROOT / 'build'
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
RUNS = ('demo3', 'newgame', 'tour', 'stbar', 'menus', 'palette',
        'automap', 'finale', 'signs')


def missing() -> str:
    from native import s2cap, s2drawcase, s2run, s2stbar, umodel
    from ref816 import make_image, title
    need = []
    if not HAVE_CC65:
        need.append('cc65 on PATH')
    if not s2run.A2VM.exists():
        need.append('build/a2vm/a2vm (make -C tools/a2vm)')
    if not (s2run.TABLES / 'math' / 'squares.bin').exists():
        need.append('the math tables (python3 tools/native/rtables.py)')
    if not (title.MACHINE.exists() and title.MEMORY.exists() and
            title.DISK.exists()):
        need.append('ref816 and its memory image (make -C tools/ref816; '
                    'python3 tools/ref816/title.py)')
    if not (make_image.LINKMAP.exists() and umodel.RELEASE.exists()):
        need.append('the link map and the release image '
                    '(tools/fetch_upstream.py, tools/v816/imgmatch.py)')
    if not all((s2cap.CASES / r / 'index.json').exists() for r in RUNS):
        need.append('part s2cap\'s cases (python3 tools/native/s2cap.py '
                    '--capture)')
    if not (s2stbar.S2DATA / 's2data.json').exists():
        need.append('part s2data\'s store (make -C src/native -f m11.mk '
                    'part P=s2data)')
    if not s2drawcase.BASE.exists():
        need.append('part s2draw\'s base state (python3 tools/native/'
                    's2drawcase.py)')
    if not all((s2stbar.POS / ('%s.json.z' % r)).exists() for r in RUNS):
        need.append('this part\'s capture (python3 tools/native/'
                    's2stbar.py --capture)')
    return ', '.join(need)


MISSING = missing()
needs_build = unittest.skipIf(MISSING, 'needs ' + MISSING)


class ModelRules(unittest.TestCase):
    """The model on hand-made values (upstream's arithmetic)."""

    def test_pain_offset_and_much_pain(self):
        from native import s2stmodel as M
        tk = M.Ticker((5, 0, 1, 0, 2, 0, 2, 5, 1), (0,) * 2049)
        st = {'oldhealthPO': 0xFFFF, 'lastcalc': 0}
        p = M.Player(100, 0, (0,) * 8, 1, (1,) * 9, (0,) * 3, (0,) * 6, 0,
                     0, 0, 0, 1, 0)
        self.assertEqual(tk.pain_offset(st, p), 0)
        for h, want in ((0, 32), (19, 32), (20, 24), (21, 24), (40, 16),
                        (60, 8), (80, 0), (150, 0)):
            self.assertEqual(tk.pain_offset(st, p._replace(health=h)),
                             want, h)
        st = {'oldhealth': 100}
        self.assertTrue(M.Ticker.much_pain(st, p._replace(health=79)))
        self.assertFalse(M.Ticker.much_pain(st, p._replace(health=80)))
        # the add's overflow corrected: (20 - $8020) + $0010 = $7FF4 +
        # $0010 overflows to $8004, not much pain
        self.assertFalse(M.Ticker.much_pain({'oldhealth': 0x8020},
                                            p._replace(health=0x0010)))
        self.assertTrue(M.Ticker.much_pain({'oldhealth': 0x8010},
                                           p._replace(health=0x7FF0)))

    def test_draw_num_digits(self):
        """drawNum: at most 3 digits, a negative number at least -99
        (so -1994 draws 99), LARGEAMMO not drawn."""
        from native import s2stmodel as M

        class G:
            def width(self, name):
                return 14

            def __getitem__(self, name):
                return name

        drawn = []

        class Bar(M.Bar):
            def patch(self, widget, glyph, x, y, place=0):
                drawn.append((glyph, x, place))
        bar = Bar.__new__(Bar)
        bar.g, bar.old, bar.bugs = G(), {}, set()
        n = M.WIDGET['health']
        for v, want in ((0, [('STTNUM0', 76, 1)]),
                        (1234, [('STTNUM4', 76, 1), ('STTNUM3', 62, 2),
                                ('STTNUM2', 48, 3)]),
                        (0xFFFB, [('STTNUM5', 76, 1)]),
                        (0xFF00, [('STTNUM9', 76, 1), ('STTNUM9', 62, 2)]),
                        (1994, []),
                        (0x10000 - 1994, [('STTNUM9', 76, 1),
                                          ('STTNUM9', 62, 2)])):
            drawn.clear()
            bar.draw_num(n, v)
            self.assertEqual(drawn, want, v)
            self.assertEqual(bar.old['health'], v)

    def test_coverage_universe(self):
        from native import s2stbar as T
        uni = T.coverage_universe()
        self.assertEqual(len(uni), len(set(uni)))
        self.assertEqual(len(uni), 11 * 29 + 42 + 3 + 12 + 4)


@needs_build
class Checkpoint(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from native import s2stbar as T
        T.make_part()

    def test_include(self):
        """The include's player offsets are llayout's, every stand-in is
        marked STANDIN and named by a request."""
        from native import llayout as LL, s2stbar as T
        text = T.inc_text()
        at = {tuple(p): a for p, e, a in LL.player_layout()}
        self.assertIn('PO_HEALTH       = $%04X' % at[('health',)], text)
        self.assertIn('PO_ATTACKER     = $%04X' % at[('attacker',)], text)
        for name, expr, why in T.STANDINS:
            self.assertRegex(text, r'%s\s+= %s\s*; STANDIN S2STBAR-\d'
                             % (name, expr.replace('+', r'\+')
                                .replace('$', r'\$')))

    def test_model_tics(self):
        from native import s2stbar as T
        res = T.tic_model(('demo3', 'newgame'))
        self.assertEqual(res['problems'], [])
        self.assertEqual(res['runs'], {'demo3': 2135, 'newgame': 513})
        self.assertGreater(res['paths'].get('attacked-turn', 0), 80)

    def test_model_frames(self):
        from native import s2stbar as T
        res = T.frame_model(('demo3', 'newgame', 'stbar'))
        self.assertEqual(res['problems'], [])
        self.assertEqual(res['runs'], {'demo3': 534, 'newgame': 128,
                                       'stbar': 206})

    def test_model_synthetic(self):
        from native import s2stbar as T
        self.assertEqual(T.synth_tic_model()['problems'], [])
        res = T.synth_model()
        self.assertEqual(res['problems'], [])
        self.assertEqual(res['kinds'].get('hide'), 4)

    def test_coverage(self):
        from native import s2stbar as T
        frames = [fc for r in RUNS for fc in T.frame_cases(r)] + \
            T.synth_frames()
        res = T.coverage(frames)
        self.assertEqual(res['missing'], [])

    def test_native_tics(self):
        from native import s2stbar as T
        res = T.native_tics(('newgame', 'synth'), jobs=2)
        self.assertEqual(res['problems'], [])
        self.assertEqual(res['stray'], 0)
        self.assertEqual(res['cases'], 2 * (513 + 96))

    def test_native_frames(self):
        """newgame's frames from the $A5 machine plain and the $5A one
        poisoned; the synthetic frames of every 4th glyph frame, the
        edges, the refreshes and the menu's stHide, both fills."""
        from native import s2stbar as T
        res = T.native_frames(('newgame',), jobs=2, fills=(0xA5,),
                              poisons=(False,))
        res2 = T.native_frames(('newgame',), jobs=2, fills=(0x5A,),
                               poisons=(True,))
        names = [si.name for si in T.synth_inputs()
                 if not si.name.startswith(('glyphs', 'ready')) or
                 int(si.name[-2:]) % 4 == 0]
        res3 = T.native_frames(('synth',), jobs=2, poisons=(True,),
                               names=names)
        for r in (res, res2, res3):
            self.assertEqual(r['problems'], [])
            self.assertEqual(r['stray'], 0)
        self.assertEqual(res['cases'] + res2['cases'], 2 * 128)
        self.assertEqual(res3['cases'], 2 * len(names))

    def test_native_chain(self):
        from native import s2stbar as T
        frames = T.frame_cases('demo3')[:64]
        orig = T.frame_cases
        try:
            T.frame_cases = lambda run: frames
            res = T.native_chain('demo3')
        finally:
            T.frame_cases = orig
        self.assertEqual(res['problems'], [])
        self.assertEqual(res['frames'], 64)

    def test_sizes(self):
        from native import s2stbar as T
        sizes = T.sizes()
        self.assertLessEqual(sizes['s2_st'], T.DRAW_BUDGET)
        self.assertLessEqual(sizes['s2t_st'], T.TIC_BUDGET)

    def test_planted_bugs(self):
        from native import s2stbar as T
        for pl in T.PLANTS:
            res = T.plant_run(pl, jobs=2, quick=True)
            self.assertTrue(res['caught'], pl.name)


if __name__ == '__main__':
    unittest.main()
