"""Milestone 11, first half, part s2menu1 (docs/SCREENS.md 1.5.3, 2.1, 3,
4.1, 6, 7.3; docs/m11-parts/s2menu1.md): the menu engine and the main
pages in MENUW (src/native/s2_menu.s, src/native/s2_mvid.s) against
upstream on ref816 (tools/native/s2menu1.py).

What runs here (the checkpoint, `python3 tools/native/s2menu1.py --all`,
also runs the timing on f121 and fastpath and writes report.json):
  - the reference's call log of menus.script (M_Responder, M_Ticker,
    G_SettingsChanged and the calls under them), captured into
    build/native/m11/s2menu1/cap/ when missing (about 3 s);
  - every menu frame of part s2cap's menus cases (the opens, the frames
    redrawn whole or by the skull) and every close, injected, twice (fill
    $A5 with the write log: no stray write, upstream's publish order; fill
    $5A with the reference's marked bytes poisoned, the opens as whole
    paused frames): the whole screen (pixels, SCBs, palettes) equal, the
    static screen's state equal to the next frame's;
  - every M_Responder call injected: its answer, the state after, the
    request, player.message, the volume, newpal and the sounds given to
    sc_start equal to the reference's S_StartSound calls;
  - every M_Ticker call, chained;
  - each menu session chained from its open's state alone to its close;
  - the sizes; the five planted bugs, each in a scratch copy.

Needs cc65, build/a2vm/a2vm, the math tables, ref816 with the release,
the link map, S2's objects (make -C src/sound), part s2data's store and
part s2cap's menus cases; skips naming what is missing.

Run by name: python3 tools/testpar.py tests/test_m11_s2menu1.py
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


class HandMade(unittest.TestCase):
    """The tool's rules on hand-made values (no build needed)."""

    def test_the_skulls_box_is_m_inits(self):
        """skullBox [R m_menu65.s:637-679]: the smallest -leftoffset and
        -topoffset, the largest right and bottom, then the size."""
        from native import s2menu1 as M
        ps = {'M_SKULL1': M.PatchInfo('M_SKULL1', 0, 0, 20, 19, 0, -1),
              'M_SKULL2': M.PatchInfo('M_SKULL2', 0, 0, 22, 17, 3, 2)}
        # left min(0, -3), top min(1, -2); right max(0 + 20, -3 + 22),
        # bottom max(1 + 19, -2 + 17), less them
        self.assertEqual(M.skull_box(ps), (-3, -2, 23, 22))

    def test_the_zero_page_and_the_native_fields_fit(self):
        from native import s2layout as S, s2menu1 as M
        zp = M.zero_page()
        self.assertGreaterEqual(min(zp.values()), S.ZP_S2M[0])
        self.assertLess(max(zp.values()), S.ZP_S2M[1])
        nat = M.native_fields()
        top = S.OWN_STATE['MENUW'][1] + S.SS_SIZE['SS_MENUW']
        for name, size in M.MENUW_NATIVE:
            self.assertLessEqual(nat[name] + size, top, name)
        # (S2MENU1-1, applied in wave 5: s2layout allocates them after
        # the field map's places, disjoint from them)
        fields = S._place_list('state', 'MENUW')
        used = S.state_places('MENUW')
        self.assertFalse(set(nat) & {n for n, _ in fields})
        end = max(used[n] + size for n, size in fields)
        self.assertGreaterEqual(min(nat.values()), end)
        self.assertEqual(nat, {n: used[n] for n, _ in M.MENUW_NATIVE})

    def test_the_places_are_menuws_runtime_and_the_asked_room(self):
        """S2MENU1-2: the room ends at $A500, PALST above it; the band,
        UI_GRAY, the marks, the slot and the fetch buffer in MENUW's
        runtime ranges."""
        from native import s2layout as S, s2menu1 as M
        im = S.IMAGE['MENUW']
        w = {n: a for n, a, _ in M.MENUW_PLACES}
        self.assertEqual(w['S2M_PALST'], M.ROOM_END)
        # (S2MENU1-2, applied in wave 5: the room ends at $A500 and PALST
        # is MENUW's first runtime range, just above it)
        self.assertEqual(im.stored[1], 0xA500)
        self.assertIn((w['S2M_PALST'], w['S2M_PALST'] + S.PALST_SIZE,
                       'PALST'), im.runtime)
        lo = min(r[0] for r in im.runtime)
        hi = max(r[1] for r in im.runtime)
        for n in ('S2M_BAND', 'S2M_GRAY', 'S2M_MARKS', 'S2M_SLOT',
                  'S2M_FBUF'):
            self.assertTrue(lo <= w[n] < hi, n)
        self.assertEqual(w['S2M_GRAY'] - w['S2M_BAND'], M.BAND_ROWS * 160)

    def test_the_requests_of_the_reference_calls(self):
        from native import s2menu1 as M
        req = dict(M.REQUESTS)
        mk = lambda n, a=0: {'name': n, 'in': {'a': a}}  # noqa: E731
        self.assertEqual(M.expected_request([]), (0, 0))
        self.assertEqual(M.expected_request([mk('G_DeferedInitNew', 2)]),
                         (req['REQ_NEWGAME'], 2))
        self.assertEqual(M.expected_request(
            [mk('I_MenuPaletteBack'), mk('G_CheckDemoStatus'),
             mk('D_StartTitle')]), (req['REQ_ENDGAME'], 1))
        self.assertEqual(M.expected_request([mk('G_LoadGame', 5)]),
                         (req['REQ_LOAD'], 5))

    def test_each_planted_text_is_in_its_source_once(self):
        from native import s2menu1 as M
        for p in M.PLANTS:
            text = (ROOT / 'src' / 'native' / p.source).read_text()
            self.assertEqual(text.count(p.old), 1, p.name)


@needs_build
class Checkpoint(unittest.TestCase):
    data = None
    setchg = None
    b = None

    @classmethod
    def setUpClass(cls):
        from native import s2menu1 as M, s2run as SR
        SR.make('s2menu1')
        if not M.CALLS_FILE.exists():
            M.capture()
        cls.data = M.load_calls()
        cls.setchg = M.settings_by_frame(cls.data)
        cls.b = SR.load_build(M.OUT, 's2m1t', 'MENUW')

    def test_the_reference_calls(self):
        from collections import Counter
        from native import s2menu1 as M
        n = Counter(c['name'] for c in self.data['calls'])
        self.assertEqual(n[M.RESPONDER], 283)
        self.assertEqual(n[M.TICKER], 863)
        self.assertEqual(n['S_StartSound'], 102)
        self.assertGreater(sum(self.setchg.values()), 0)
        self.assertIn(0, self.setchg.values())

    def test_every_frame_and_close(self):
        from native import s2menu1 as M
        r = M.check_frames(self.b, self.setchg)
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['kinds'], {'open': 7, 'skull': 125, 'full': 18,
                                      'close': 7})
        self.assertEqual(sum(r['excluded'].values()), 9)
        self.assertTrue(all(k.startswith('X-M2') for k in r['excluded']))
        self.assertLessEqual(r['stack'], 64)

    def test_every_responder_call(self):
        from native import s2menu1 as M
        r = M.check_responders(self.b, self.data)
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['calls'], 283)
        self.assertEqual(r['sounds'], 102)

    def test_every_ticker_call(self):
        from native import s2menu1 as M
        r = M.check_tickers(self.b, self.data)
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['calls'], 863)
        self.assertGreater(r['blinks'], 100)

    def test_each_session_chained(self):
        from native import s2menu1 as M
        r = M.check_chains(self.b, self.setchg, self.data)
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['sessions'], 7)
        self.assertEqual(r['steps']['close'], 7)

    def test_sizes(self):
        """MENUW within its room and the room S2MENU1-2 asks for; this
        part's code within its 5,000 B, its data within the names and
        strings' 2,500 B (SCREENS.md 4.1's split)."""
        from native import s2menu1 as M
        s = M.sizes()
        self.assertEqual(s['problems'], [])
        self.assertLessEqual(s['code'], M.BUDGET)
        self.assertLessEqual(s['data'], M.DATA_BUDGET)


@needs_build
class Planted(unittest.TestCase):
    def test_each_planted_bug_is_caught(self):
        from native import s2menu1 as M
        data = M.load_calls() if M.CALLS_FILE.exists() else M.capture()
        r = M.planted(M.settings_by_frame(data), data)
        self.assertEqual(sorted(r), sorted(p.name for p in M.PLANTS))
        for name, v in r.items():
            with self.subTest(name):
                self.assertTrue(v['caught'], v)


if __name__ == '__main__':
    unittest.main()
