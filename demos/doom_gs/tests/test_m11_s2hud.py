"""Milestone 11, first half, part s2hud (docs/SCREENS.md 0.1 F8, 1.4,
1.5.2, 4.4, 4.7, 6.3 X1, 7.3; docs/m11-parts/s2hud.md): the HUD's tic side
(src/native/s2t_hu.s: hu_ticker, hu_start), its cached drawer in P2DW
(src/native/s2_hu.s: hu_drawer) and the texts (tools/native/s2msgs.py),
against upstream on ref816 (tools/native/s2hud.py).

What runs here (the checkpoint, `python3 tools/native/s2hud.py --all`,
also runs the timing on fastpath and writes report.json):
  - the call logs of demo3, newgame, menus.script and automap.script
    (captured into build/native/m11/s2hud/cases/ when missing, about 15 s);
  - every HU_Ticker and HU_Start of the four runs, chained and injected:
    the counter, message_on, message_new, the line, player.message and
    G_MSGKEEP after each equal; in every level frame message_on after the
    frame's tics equal to point PV's and request R7's VIEWTOP equal to
    upstream's viewtop;
  - every HU_Drawer of the four runs, chained: the screen's rows 0-9
    (the strip on) and 160-167 (the map's title) after the frame equal to
    display's return, rows 0-9 never written with the strip off, the text
    cache after each frame equal; the same frames drawn afresh give the
    same screens;
  - synthetic HU_Ticker calls and lines against ref816 --call;
  - the sizes; the seven planted bugs, each in a scratch copy.

Needs cc65, build/a2vm/a2vm, the math tables, ref816 with the release,
the link map, DOOM1.WAD, part s2data's store (make -C src/native -f
m11.mk part P=s2data) and part s2draw's truth base (python3
tools/native/s2drawcase.py); skips naming what is missing.

Run by name: python3 tools/testpar.py tests/test_m11_s2hud.py
"""

import re
import shutil
import unittest

import support

ROOT = support.ROOT
BUILD = ROOT / 'build'
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))


def missing() -> str:
    from native import s2drawcase, s2run
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
    if not (BUILD / 'upstream' / 'src' / 'iigs' / 'hu_stuff65.s').exists():
        need.append('upstream\'s sources (tools/fetch_upstream.py)')
    m11 = BUILD / 'native' / 'm11'
    if not ((m11 / 's2data' / 's2data.json').exists() and
            list((m11 / 's2data').glob('GFX.*'))):
        need.append('part s2data\'s store (make -C src/native -f m11.mk '
                    'part P=s2data)')
    if not s2drawcase.BASE.exists():
        need.append('part s2draw\'s base state (python3 tools/native/'
                    's2drawcase.py)')
    return ', '.join(need)


MISSING = missing()
needs_build = unittest.skipIf(MISSING, 'needs ' + MISSING)


class HandMade(unittest.TestCase):
    """The generator's rules on hand-made text (no build needed)."""

    def test_the_store_rule_takes_sta_and_stx_not_stz(self):
        from native import s2msgs as MS
        self.assertTrue(MS.STORE_RE.search(
            '2$:           sta     .near (PL+OFS_PL_MESSAGE)\n'))
        self.assertTrue(MS.STORE_RE.search(
            '              stx     .near (_g_player+OFS_PL_MESSAGE+2)\n'))
        self.assertFalse(MS.STORE_RE.search(
            '              stz     .near (PL+OFS_PL_MESSAGE)\n'))
        self.assertEqual(MS.WORD0_RE.findall(
            'lda ##.word0 msgOn\n.word .word0 msgA, .word2 msgA'),
            ['msgOn', 'msgA'])

    def test_keys_of_the_bank_table(self):
        from native import s2msgs as MS
        self.assertEqual(MS.key_of(0x0090), 0x90)
        self.assertEqual(MS.key_of(MS.TITLE_ID + 1), MS.KEY_TITLE + 1)
        self.assertEqual(MS.key_of(MS.TITLE_ID + 9), 0xF9)
        self.assertLess(MS.TEST_ID + len(MS.test_texts()), MS.KEY_TITLE)

    def test_the_line_ends_as_upstream(self):
        """drawTextLine's end [R hu_stuff65.s:177-205]: a glyph that ends
        at 320 is drawn, one that would end at 321 is not; a space that
        reaches 320 ends the line."""
        from native import s2hud as H
        widths = {c: 8 for c in range(0x21, 0x60)}
        self.assertEqual(H.line_end(b'A' * 40, widths), (320, 40))
        self.assertEqual(H.line_end(b'A' * 41, widths), (320, 40))
        self.assertEqual(H.line_end(b'a' * 39 + b'b', widths), (320, 40))
        self.assertEqual(H.line_end(b'A' * 38 + b' ', widths), (308, 39))
        self.assertEqual(H.line_end(b'A' * 39 + b'  ', widths), (320, 40))
        self.assertEqual(H.line_end(b'`{', widths), (8, 2))


@needs_build
class Checkpoint(unittest.TestCase):
    result = None
    note = ''

    @classmethod
    def setUpClass(cls):
        from native import s2hud as H
        cls.note = H.make()
        rs = None
        for run in H.RUNS:
            if not (H.CASES / (run + '.json.z')).exists():
                rs = rs or H.routines()
                H.capture(run, rs)
        cls.result = H.check_all(H.RUNS, 'f121')

    def test_the_message_table(self):
        from native import s2msgs as MS
        ms = {e.name: e for e in MS.message_symbols()}
        for name in ('p_inter65.s:msgClip', 'am_map65.s:msgFollowOn',
                     'g_game65.s:strGameSaved', 'm_menu65.s:msgRunOn',
                     'm_cheat65.s:msgDqdOn', 'p_doors65.s:msgYellow'):
            self.assertIn(name, ms)
        self.assertEqual(ms['g_game65.s:strGameSaved'].text, b'game saved.')
        ids = MS.symbol_ids()
        for e in ms.values():
            self.assertEqual(ids[e.name], e.id)
            self.assertLess(e.id, MS.TEST_ID)
        titles = MS.titles()
        self.assertEqual([t.text for t in titles][:2],
                         [b'E1M1: Hangar', b'E1M2: Nuclear Plant'])
        self.assertLessEqual(len(MS.bank_table(True)), MS.SS_HUDMSG_SIZE)

    def test_the_bank_table_reads_back(self):
        from native import s2msgs as MS
        table = MS.bank_table(True)
        for e in MS.entries(True):
            k = MS.key_of(e.id)
            at = table[2 * k] | table[2 * k + 1] << 8
            self.assertNotEqual(at, 0, e.name)
            entry = table[at - MS.SS_HUDMSG:at - MS.SS_HUDMSG + MS.ENTRY]
            self.assertEqual(entry[MS.ENTRY - 1], len(e.text))
            self.assertEqual(entry[:len(e.text)], e.text)

    def test_the_include_defines_nothing_of_s2_inc(self):
        from native import s2hud as H
        own = (H.OUT / 'gen' / 's2hud.inc').read_text()
        shared = (H.M11 / 'shared' / 'gen' / 's2.inc').read_text()
        names = lambda text: set(re.findall(r'^(\w+)\s*=', text, re.M))  # noqa
        self.assertFalse(names(own) & names(shared))

    def test_every_tic_and_pv(self):
        r = self.result
        by = {x['run']: x for x in r['runs']}
        self.assertEqual(by['demo3']['tics'], 2136)
        self.assertEqual(by['demo3']['pv'], 534)
        for x in r['runs']:
            self.assertEqual([p for p in x['problems'] if ' call ' in p and
                              ('chained' in p or 'injected' in p or
                               'PV' in p)], [], x['run'])

    def test_every_frame(self):
        r = self.result
        self.assertEqual(sum(x['frames'] for x in r['runs']), 794)
        self.assertEqual(r['problems'], [])
        kinds = {}
        for x in r['runs']:
            for k, v in x['kinds'].items():
                kinds[k] = kinds.get(k, 0) + v
        self.assertGreater(kinds['replay'], 0)
        self.assertGreater(kinds['fresh'], 0)

    def test_the_synthetic_cases(self):
        syn = self.result['synthetic']
        self.assertEqual(syn['tics'], 64)
        self.assertGreaterEqual(syn['frames'], 12)
        self.assertEqual(syn['problems'], [])

    def test_sizes(self):
        from native import s2hud as H
        s = H.sizes()
        self.assertLessEqual(s['p2dw'], s['p2dw_budget'])
        self.assertLessEqual(s['tic'], s['tic_budget'])
        self.assertLessEqual(s['texts_bank'], s['texts_bank_room'])


@needs_build
class Planted(unittest.TestCase):
    def test_each_planted_bug_is_caught(self):
        from native import s2hud as H
        H.make()
        for k in range(len(H.PLANTED)):
            name, problems = H.plant(k, H.RUNS)
            self.assertTrue(problems, name)


if __name__ == '__main__':
    unittest.main()
