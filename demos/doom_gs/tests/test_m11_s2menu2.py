"""Milestone 11, first half, part s2menu2 (docs/SCREENS.md 1.5.3, 4.1,
6.2, 6.3, 7.3; docs/m11-parts/s2menu2.md): the settings pages' values,
the key setup page, the load and save pages' slots, the benchmark's
result (src/native/s2_menu2.s in MENUW, with part s2menu1's engine)
against upstream on ref816 (tools/native/s2menu2.py). (The busy sign's
font this part also built went at wave 6's integration: part s2fin's
FINW draws the sign, S2MENU2-4 with S2FIN-8.)

What runs here (the checkpoint, `python3 tools/native/s2menu2.py --all`,
also runs the timing on f121 and fastpath and writes report.json):
  - the reference's runs K1 (menus.script to the key setup, the //e names
    and table poked 1:1 into keyNames and keyTable), K2 (the whole
    script, the //e names poked) and B (the benchmark's result poked),
    captured into build/native/m11/s2menu2/cases/ when missing (about
    7 s), and part s2menu1's call log into build/native/m11/s2menu2/cap/;
  - every menu frame and close of part s2cap's menus cases (run A) and
    the key setup frames of K1 and K2 and the result's of B, injected,
    twice (fill $A5 with the write log: no stray write, upstream's
    publish order; fill $5A with the reference's marked bytes
    poisoned): the whole screen equal, X2's rows black natively;
  - each menu session of run A chained from its open's state;
  - part s2menu1's M_Responder and M_Ticker calls on this image (its
    t_num the release's, request S2MENU2-2);
  - the sizes; the four planted bugs, each in a scratch copy.

By default (tests/README.md) the frames run are an even sample (every
STEP-th of each run and the first of each page and kind), and part
s2menu1's calls the same sample as its module's; the capture's counts are
still checked whole. DOOM_GS_FULL=1 runs every one as before.

Needs cc65, build/a2vm/a2vm, the math tables, ref816 with the release,
the link map, S2's objects (make -C src/sound), part s2data's store,
and part s2cap's menus cases; skips naming what is missing.

Run by name: python3 tools/testpar.py tests/test_m11_s2menu2.py
"""

import shutil
import unittest

import support

ROOT = support.ROOT
BUILD = ROOT / 'build'
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))


def missing() -> str:
    from native import s2run
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
    if not make_image.LINKMAP.exists():
        need.append('the link map (tools/v816/imgmatch.py)')
    if not (BUILD / 'upstream' / 'src' / 'iigs' / 'm_menu65.s').exists():
        need.append('upstream\'s sources (tools/fetch_upstream.py)')
    if not (BUILD / 'sound65' / 'player.o').exists():
        need.append('S2\'s objects (make -C src/sound)')
    m11 = BUILD / 'native' / 'm11'
    if not ((m11 / 's2data' / 's2data.json').exists() and
            list((m11 / 's2data').glob('GFX.*'))):
        need.append('part s2data\'s store (make -C src/native -f m11.mk '
                    'part P=s2data)')
    if not (m11 / 'cases' / 'menus' / 'index.json').exists():
        need.append('part s2cap\'s menus cases (python3 tools/native/'
                    's2cap.py --capture)')
    return ', '.join(need)


MISSING = missing()
needs_build = unittest.skipIf(MISSING, 'needs ' + MISSING)
FULL = support.FULL
STEP = 6            # by default: every STEP-th frame of a run
# check_frames' runs: s2cap's menus cases (A) and this part's K1, K2, B
FRAME_RUNS = ('a', 'k1', 'k2', 'bench')


def frame_pick(M, setchg):
    """check_frames' pick by default (None: every job) and the jobs it
    picks: every STEP-th job of each run and the first of each (run,
    page, kind)."""
    if FULL:
        return None, None
    chosen, seen = set(), set()
    for run in FRAME_RUNS:
        js = [mj for mj in M.jobs_of(run, setchg) if not mj.job.excluded]
        for i, mj in enumerate(js):
            key = (run, mj.page, mj.job.kind)
            if i % STEP == 0 or key not in seen:
                seen.add(key)
                chosen.add((run, mj.job.name))
    return (lambda mj: (mj.run, mj.job.name) in chosen), chosen


class HandMade(unittest.TestCase):
    """The tool's rules on hand-made values (no build needed)."""

    def test_the_titles_are_centred_as_centerpatch(self):
        """centerPatch: 160 - width / 2, the width halved first."""
        from native import s2menu2 as M
        self.assertEqual(M.title_x(92), 114)
        self.assertEqual(M.title_x(125), 98)     # 160 - 62

    def test_the_applied_places(self):
        """S2MENU2-1 and -2 as applied (wave 6): M_BFPS, 8 bytes, then
        (the play build's phase rows, docs/PLAY.md 15) M_BROWS, 96 bytes,
        the last of s2layout's MENUW fields, inside the state block; the
        music's volume the field map's SS_SETTINGS+5, s2_menu.s's
        SET_MUSVOL."""
        import re
        from native import s2layout as S, s2menu2 as M
        used = S.state_places('MENUW')
        at = M.native_places()['M_BFPS']
        self.assertEqual(S.MENUW_NATIVE[-2:], [('M_BFPS', 8),
                                               ('M_BROWS', 96)])
        self.assertEqual(at, used['M_BFPS'])
        self.assertEqual(M.native_places()['M_BROWS'], at + 8)
        self.assertLessEqual(at + 8 + 96, S.OWN_STATE['MENUW'][1] +
                             S.SS_SIZE['SS_MENUW'])
        self.assertEqual(M.settings_places()[M.MUSIC_FIELD], M.SET_MUSVOL)
        self.assertLess(M.SET_MUSVOL, S.SS_SIZE['SS_SETTINGS'])
        menu = (ROOT / 'src' / 'native' / 's2_menu.s').read_text()
        self.assertEqual(int(re.search(r'^SET_MUSVOL\s*=\s*(\d+)', menu,
                                       re.M).group(1)), M.SET_MUSVOL)

    def test_the_release_s_menunum(self):
        """S2MENU2-2: s2_menu.s's t_num is the release's menuNum (the
        display page's 4 rows, the sound page's 2: MUSIC_MENU 1)."""
        from native import s2menu2 as M
        tree = (ROOT / 'src' / 'native' / 's2_menu.s').read_text()
        self.assertEqual(tree.count(M.MENU1_NUM), 1)

    def test_one_menu_glue(self):
        """S2MENU2-3: both parts' images link s2_menu2.s and the one test
        glue s2_menut.s, which no longer stands in for the hooks."""
        src = ROOT / 'src' / 'native'
        self.assertFalse((src / 's2_menu2t.s').exists())
        glue = (src / 's2_menut.s').read_text()
        self.assertNotIn('m2_page:', glue)
        for mk in ('s2menu1.mk', 's2menu2.mk'):
            text = (src / 'm11' / mk).read_text()
            self.assertIn('s2_menu2.o', text, mk)
            self.assertIn('s2_menut.o', text, mk)

    def test_x2_is_ubenchmarks_last_three_rows(self):
        """uiBenchmark's rows at y 60 + 16 i [R m_menu65.s:3015-3058]; a
        glyph's rows y .. y + 7; X2 the rows of i = 2, 3, 4, whole."""
        from native import s2layout as S, s2menu2 as M
        self.assertEqual(M.X2_ROWS, tuple((60 + 16 * i, 60 + 16 * i + 7)
                                          for i in (2, 3, 4)))
        self.assertEqual(len(M.x2_offsets()), 3 * 8 * S.ROW_BYTES)

    def test_each_planted_text_is_in_its_source_once(self):
        from native import s2menu2 as M
        for p in M.PLANTS:
            if p.source.startswith('gen/'):
                continue                # (in the scratch build's include)
            text = (ROOT / 'src' / 'native' / p.source).read_text()
            self.assertEqual(text.count(p.old), 1, p.name)


@needs_build
class Checkpoint(unittest.TestCase):
    data = None
    setchg = None
    b = None

    @classmethod
    def setUpClass(cls):
        from native import s2menu1 as M1, s2menu2 as M, s2run as SR
        SR.make('s2menu2')
        if not all((M.run_root(r) / 'index.json').exists()
                   for r in M.RUNS) or not M1.CALLS_FILE.exists():
            M.capture()
        cls.data = M1.load_calls()
        cls.setchg = M1.settings_by_frame(cls.data)
        cls.b = SR.load_build(M.OUT, 's2m2t', 'MENUW')

    def test_the_poked_runs(self):
        """K1 and K2 reach the key setup with the //e names (and K1 the
        //e table: key_problems on every frame); B the result's frame."""
        from native import s2menu2 as M
        runs = {r: M.jobs_of(r, self.setchg) for r in M.RUNS}
        self.assertTrue(any(j.job.kind == 'full' for j in runs['k1']))
        self.assertGreaterEqual(sum(j.job.kind == 'full'
                                    for j in runs['k2']), 4)
        self.assertEqual([j.job.kind for j in runs['bench']][0], 'open')
        for r in ('k1', 'k2'):
            for j in runs[r]:
                self.assertEqual(M.key_problems(j), [], j.job.name)

    def test_every_frame_and_close(self):
        from native import s2menu2 as M
        from collections import Counter
        pick, chosen = frame_pick(M, self.setchg)
        r = M.check_frames(self.b, self.setchg, pick=pick)
        self.assertEqual(r['problems'], [])
        every = Counter(run for run in FRAME_RUNS
                        for mj in M.jobs_of(run, self.setchg)
                        if not mj.job.excluded)
        self.assertEqual(dict(every), {'a': 162, 'k1': 9, 'k2': 24,
                                       'bench': 9})
        self.assertEqual(r['by_run'], dict(every) if FULL else
                         dict(Counter(run for run, _ in chosen)))
        for page in ('load full', 'save full', 'display & sound full',
                     'controls full', 'key setup full', 'benchmark open'):
            self.assertIn(page, r['pages'])
        self.assertEqual(list(r['excluded']), [M.X_K])
        self.assertEqual(r['excluded'][M.X_K], 4)
        self.assertGreater(r['x2']['drawn_by_reference'], 0)
        self.assertLessEqual(r['stack'], 64)

    def test_each_session_chained(self):
        from native import s2menu2 as M
        r = M.check_chains(self.b, self.setchg, self.data)
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['sessions'], 7)
        self.assertEqual(r['steps']['close'], 7)
        self.assertEqual(r['steps']['excluded'], 24)    # the key setup's

    def test_s2menu1s_calls_on_this_image(self):
        """Part s2menu1's calls (by default its module's sample)."""
        from native import s2menu1 as M1, s2menu2 as M
        from test_m11_s2menu1 import responder_calls, ticker_chains
        only, n, _ = responder_calls(M1, self.data)
        r = M1.check_responders(self.b, self.data, 0xA5, 2, M.OUT, only)
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['calls'], 283 if FULL else n)
        patch, n = ticker_chains(M1, self.data)
        with patch:
            r = M1.check_tickers(self.b, self.data, 0xA5, 2, M.OUT)
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['calls'], 863 if FULL else n)

    def test_sizes(self):
        """MENUW with both menu parts within its room; this part's code
        and data (the names included) within its 4,000 B."""
        from native import s2menu2 as M
        s = M.sizes()
        self.assertEqual(s['problems'], [])
        self.assertLessEqual(s['total'], M.BUDGET)


@needs_build
class Planted(unittest.TestCase):
    def test_each_planted_bug_is_caught(self):
        from native import s2menu1 as M1, s2menu2 as M
        if not M1.CALLS_FILE.exists():
            M.capture()
        r = M.planted(M1.settings_by_frame(M1.load_calls()))
        self.assertEqual(sorted(r), sorted(p.name for p in M.PLANTS))
        for name, v in r.items():
            with self.subTest(name):
                self.assertTrue(v['caught'], v)


if __name__ == '__main__':
    unittest.main()
