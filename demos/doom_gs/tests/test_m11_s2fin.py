"""Milestone 11, first half, part s2fin (docs/SCREENS.md 1.5.6-1.5.8, 4.1,
4.7, 6, 7.3; docs/m11-parts/s2fin.md): the image FINW (src/native/
s2_fin.s: the finale's drawer, the title page, F_LoadScreen, the busy sign)
and the tic side src/native/s2t_fin.s (f_ticker, f_start) against
upstream on ref816 (tools/native/s2fin.py).

What runs here (the checkpoint, `python3 tools/native/s2fin.py --all`,
also runs the timing on f121 and fastpath and writes report.json):
  - every finale frame of finale.script (the text, the mid stage, HELP2
    and its wipe), the title page's drawn frame of finale.script,
    signs.script and demo3 (X3 counted), F_LoadScreen, every bmSignOn and
    the bmSignOff that puts its rows back: the whole screen (pixels, SCBs,
    palettes) after it equal to the reference's, injected with both fills
    and the finale chained; F_MID, WI_ACCEL and PALST's scb, palette and
    picture equal to the reference's at I_FinishUpdate; the wipe's black
    step against PW; no stray write, upstream's publish order, the stack;
  - f_ticker on every F_Ticker of finale.script (injected and chained) and
    f_start on F_StartFinale;
  - FINW's sizes against its room, the part's code and the tic side's
    budgets;
  - the three planted bugs, each in a scratch copy.

Needs cc65, build/a2vm/a2vm, ref816, the math tables, the release image
and the link map, part s2cap's captures of finale, signs and demo3
(python3 tools/native/s2cap.py --capture), part s2data's store (make -C
src/native -f m11.mk part P=s2data) and S2's objects (make -C src/sound);
skips naming what is missing. This part's own capture (s2fin.py
--capture, 8 s) is made when it is missing.

Run by name: python3 tools/testpar.py tests/test_m11_s2fin.py
"""

import re
import shutil
import unittest
from unittest import mock

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
    if not title.MACHINE.exists():
        need.append('ref816 (MILESTONES.md "Setting up")')
    if not (s2run.TABLES / 'math' / 'squares.bin').exists():
        need.append('the math tables (python3 tools/native/rtables.py)')
    if not make_image.LINKMAP.exists():
        need.append('the link map (tools/v816/imgmatch.py)')
    if not (BUILD / 'upstream' / 'src' / 'iigs' / 'f_finale65.s').exists():
        need.append('upstream\'s sources and release (tools/'
                    'fetch_upstream.py)')
    m11 = BUILD / 'native' / 'm11'
    for run in ('finale', 'signs', 'demo3'):
        if not (m11 / 'cases' / run / 'index.json').exists():
            need.append('part s2cap\'s capture of %s (python3 tools/native/'
                        's2cap.py --capture)' % run)
    if not ((m11 / 's2data' / 's2data.inc').exists() and
            list((m11 / 's2data').glob('GFX.*'))):
        need.append('part s2data\'s store (make -C src/native -f m11.mk '
                    'part P=s2data)')
    if not (BUILD / 'sound65' / 'player.o').exists():
        need.append('S2\'s objects (make -C src/sound)')
    return ', '.join(need)


MISSING = missing()
needs_build = unittest.skipIf(MISSING, 'needs ' + MISSING)


def const(text: str, name: str) -> int:
    m = re.search(r'^%s\s*=\s*(\$?)([0-9A-Fa-f]+)\b' % name, text, re.M)
    if m is None:
        raise AssertionError('%s is not defined' % name)
    return int(m.group(2), 16 if m.group(1) else 10)


class HandMade(unittest.TestCase):
    """The harness's rules and the sources (no build needed)."""

    def test_the_store_is_never_seen_half_read(self):
        """store_records from two job threads at once: each sees the whole
        store (the wave 8 integration: the cache was published while it
        was being filled, and a thread that came second ran with part of
        the 2D store)."""
        import tempfile
        import threading
        import time
        from pathlib import Path
        from native import lstore, s2fin as M
        segs = [(109 + k, 0x0200 + 0x100 * j, bytes([k, j]) * 64)
                for k in range(3) for j in range(4)]
        read = lstore.read_bank_file

        def slow(data):
            time.sleep(0.02)
            return read(data)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 's2data').mkdir()
            for k in range(3):
                (Path(tmp) / 's2data' / ('GFX.%d' % (k + 1))).write_bytes(
                    lstore.bank_file(segs[4 * k:4 * k + 4]))
            saved = (M.M11, M._STORE)
            seen = []
            try:
                M.M11, M._STORE = Path(tmp), None
                lstore.read_bank_file = slow
                threads = [threading.Thread(
                    target=lambda: seen.append(list(M.store_records())))
                    for _ in range(3)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            finally:
                lstore.read_bank_file = read
                M.M11, M._STORE = saved
        want = [(1, b, a, d) for b, a, d in segs]
        self.assertEqual(seen, [want] * 3)

    def test_the_region_is_the_whole_screen_but_rule_10(self):
        from native import s2check as K, s2fin as F, s2layout as S
        got = set(K.offsets(F.screen_region()))
        self.assertEqual(len([a for a in got if a < S.SCB]), 32000)
        self.assertTrue(all(a in got for a in range(S.SCB, S.SCB + 200)))
        self.assertTrue(all(a in got for a in range(S.PALETTES,
                                                    S.SCREEN_END)))
        self.assertFalse(got & set(range(*S.RESERVED)))

    def test_the_stage_matches_the_glue(self):
        """s2fin.py's stage layout is the one src/native/s2_fint.s
        reads."""
        from native import s2fin as F
        text = (SRC / 's2_fint.s').read_text()
        self.assertEqual(const(text, 'T_STAGE'), F.T_STAGE)
        self.assertEqual(const(text, 'PER_BANK'), F.PER_BANK)
        self.assertEqual(const(text, 'REC_PAGES') * 256, F.REC)
        self.assertEqual(const(text, 'C_KIND'), F.REC_CTL)
        self.assertLessEqual(F.PER_BANK * F.REC, 0xC000 - 0x0200)
        self.assertLess(F.SCREEN_BANK0, F.T_STAGE)
        self.assertNotIn(F.TIC_IN, range(F.SCREEN_BANK0, F.T_STAGE + 2))
        recs = F.stage_records([F.Stage(bytes([k]) * F.REC, b'', None, b'',
                                        b'') for k in range(F.PER_BANK + 2)])
        self.assertEqual([r[1] for r in recs], [F.T_STAGE, F.T_STAGE + 1])
        self.assertEqual(recs[1][3][F.REC], F.PER_BANK + 1)
        # a whole screen goes to its own bank, named in the record
        recs = F.stage_records([F.Stage(bytes(F.REC), b'', bytes(32768),
                                        b'', b'')])
        self.assertEqual(recs[1][:3], (1, F.SCREEN_BANK0, 0x0200))
        self.assertEqual(recs[0][3][F.REC_CTL + 3], F.SCREEN_BANK0)

    def test_the_tic_records_match_the_glue(self):
        from native import s2fin as F
        text = (SRC / 's2_fint.s').read_text()
        t = F.Tic('t', 1, bytes([1, 2, 3, 4, 5, 6]), 0x0102, 0x0304,
                  0x0506, 7, False, {})
        r = F.tic_record(t, 5)
        self.assertEqual(len(r), F.TIC_REC)
        self.assertEqual(r[const(text, 'I_KIND')], 1)
        self.assertEqual(r[const(text, 'I_MODE')], 5)
        at = const(text, 'I_CARD')
        self.assertEqual(r[at:at + 6], bytes([1, 2, 3, 4, 5, 6]))
        for name, v in (('I_ACCEL', 0x0102), ('I_ACTION', 0x0304),
                        ('I_STATE', 0x0506)):
            at = const(text, name)
            self.assertEqual(r[at] | r[at + 1] << 8, v, name)
        self.assertEqual(r[const(text, 'I_AUTOMAP')], 7)

    def test_each_planted_edit_is_found_once(self):
        from native import s2fin as F
        for name, edits in F.PLANTED:
            for source, old, _ in edits:
                text = (SRC / source).read_text()
                self.assertEqual(text.count(old), 1, (name, source))

    def test_the_game_state_comes_from_the_includes(self):
        """The tic side and FINW take milestone 10's places by lgame.inc's
        names and the card's and FINW's by s2.inc's: none defined here."""
        for f in ('s2t_fin.s', 's2_fin.s'):
            text = (SRC / f).read_text()
            self.assertIn('.include "lgame.inc"', text)
            self.assertIn('.include "s2.inc"', text)
            for name in ('WI_ACCEL', 'G_GAMEACTION', 'G_GAMESTATE',
                         'F_STAGE', 'F_COUNT', 'F_MID', 'F_HELP2',
                         'F_BACKGROUND', 'AUTOMAP'):
                self.assertIsNone(re.search(r'^%s\s*=' % name, text, re.M),
                                  (f, name))
        mk = (SRC / 'm11' / 's2fin.mk').read_text()
        self.assertIn('llayout.py --game', mk)

    def test_the_shared_places_are_the_layout_s(self):
        """Request S2FIN-1 as applied (wave 6): the sign's state and its
        stop are s2.inc's (s2layout's FINW_NATIVE and PL), no local
        stand-in is left."""
        from native import s2layout as S
        text = (SRC / 's2_fin.s').read_text()
        self.assertNotIn('STANDIN', text)
        for name in ('F_SIGNON', 'FIN_AMEMSTOP'):
            self.assertIsNone(re.search(r'^%s\s*=' % name, text, re.M), name)
        self.assertIn('lda #PL_SIGNAMEM', text)
        self.assertEqual(S.state_places('FINW')['F_SIGNON'],
                         S.OWN_STATE['FINW'][1] + 2)
        self.assertEqual(S.PL['SIGNAMEM'], 0xC6)


@needs_build
class Checkpoint(unittest.TestCase):
    result = None

    @classmethod
    def setUpClass(cls):
        from native import s2fin as F
        if not all((F.CAP / (r + '.z')).exists() for r in F.RUNS):
            F.capture_all(2)
        F.make()
        cls.result = F.check(None, F.OUT, 2, ('injected', 'chained'))

    def test_every_case(self):
        r = self.result
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['excluded'], [])
        self.assertEqual(r['kinds'], {'page': 3, 'sign on': 4,
                                      'sign off': 4, 'text': 35,
                                      'picture (new)': 1, 'picture': 27,
                                      'load screen': 1})
        self.assertEqual(r['x3'], 3)            # X3: each title page
        self.assertEqual(len(r['x3_frames']), 3)
        self.assertEqual(r['stray'], 0)
        self.assertLessEqual(r['stack'], 64 + 24)
        injected = [x for x in r['runs'] if x['tag'].startswith('injected')]
        chained = [x for x in r['runs'] if x['tag'].startswith('chained')]
        self.assertEqual(sum(x['cases'] for x in injected), 2 * r['cases'])
        self.assertEqual(sum(x['cases'] for x in chained), 63)

    def test_every_tic(self):
        r = self.result
        self.assertEqual(r['tics'], 254)        # 253 F_Ticker, F_StartFinale
        self.assertEqual(sorted(x['mode'] for x in r['tic_runs']),
                         ['chained', 'injected'])
        for x in r['tic_runs']:
            self.assertEqual(x['problems'], [])
            self.assertEqual(x['starts'], 1)

    def test_the_include(self):
        from native import s2fin as F
        path = F.OUT / 'gen' / 's2fin.inc'
        vals = F.inc_values(path)
        rel = F.release()
        self.assertEqual(vals['FIN_HELP2NUM'], rel.index('HELP2'))
        self.assertEqual(vals['FIN_TITLENUM'], rel.index('TITLEPIC'))
        self.assertEqual(vals['FIN_E1LENGTH'], len(F.e1text()))
        own = set(re.findall(r'^(\w+)\s*=', path.read_text(), re.M))
        shared = set(re.findall(r'^(\w+)\s*=', (F.SHARED_GEN / 's2.inc')
                                .read_text(), re.M))
        self.assertFalse(own & shared)

    def test_the_text_is_upstreams(self):
        """s2_fin.s's e1text, assembled, is the release's bytes."""
        from native import s2fin as F
        lst = (F.OUT / 's2_fin.lst').read_text()
        self.assertIn('e1text:', lst)
        text = (SRC / 's2_fin.s').read_text()
        body = text.split('e1text:', 1)[1].split('e1end:', 1)[0]
        got = b''
        for line in body.splitlines():
            line = line.split(';')[0].strip()
            if not line.startswith('.byte'):
                continue
            for part in re.findall(r'"[^"]*"|\d+', line[5:]):
                got += part[1:-1].encode() if part.startswith('"') else \
                    bytes([int(part)])
        self.assertEqual(got, F.e1text())

    def test_the_signs_put_back(self):
        """Each sign-off case changes the screen (its rows come back)."""
        from native import s2fin as F
        cs, _, _ = F.all_cases()
        offs = [c for c in cs if c.kind == F.K_SIGNOFF]
        self.assertEqual(len(offs), 4)
        for c in offs:
            self.assertNotEqual(c.want, c.screen, c.name)

    def test_sizes(self):
        from native import s2fin as F
        s = F.sizes()
        self.assertLessEqual(s['code'], s['code_budget'])
        self.assertLessEqual(s['data'], s['data_budget'])
        self.assertLessEqual(s['tic'], s['tic_budget'])
        room = [line for line in s['table'] if ' room ' in line][0]
        used, size = map(int, re.findall(r'(\d+) of\s+(\d+)', room)[0])
        self.assertLessEqual(used, size)
        for line in s['table']:     # (FINW's own too since S2FIN-3)
            self.assertNotIn('OVER', line)


@needs_build
class Planted(unittest.TestCase):
    def test_each_planted_bug_is_caught(self):
        """Each bug on the injected checks, from both fills (by default
        from $A5 alone: tests/README.md; DOOM_GS_FULL=1 both)."""
        from native import s2fin as F
        if not all((F.CAP / (r + '.z')).exists() for r in F.RUNS):
            F.capture_all(2)
        F.make()
        fills = F.FILLS if support.FULL else F.FILLS[:1]
        for k in range(len(F.PLANTED)):
            with mock.patch.object(F, 'FILLS', fills):
                name, problems = F.plant(k, 2)
            self.assertTrue(problems, name)


if __name__ == '__main__':
    unittest.main()
