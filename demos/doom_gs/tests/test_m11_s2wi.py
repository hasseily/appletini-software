"""Milestone 11, first half, part s2wi (docs/SCREENS.md 1.5.5, 1.5.7, 4.1,
6, 7.3; docs/m11-parts/s2wi.md): the intermission's image WIW
(src/native/s2_wi.s: wi_init, wi_frame, wi_drawer) against upstream's
frames of the tour (tools/native/s2wi.py).

What runs here (the checkpoint, `python3 tools/native/s2wi.py --all`,
also runs the timing on f121 and fastpath and writes report.json):
  - every intermission frame of the tour (eight intermissions, the stats
    and the next location with its blinking pointer), injected from its
    own state with both fills (the second with every byte the frame marked
    poisoned) and chained through each intermission: the whole screen
    (pixels, SCBs, palettes) after the frame equal to the reference's,
    WI_SNLPTR and PALST's scb, palette and picture equal to the
    reference's at I_FinishUpdate, W_LUMPS from wi_init (chained), no
    stray write, upstream's publish order, the stack;
  - the nibble tables' units every patch position needs (at most 16);
  - WIW's sizes against its room and the part's budget;
  - the four planted bugs, each in a scratch copy.

By default (tests/README.md) the frames run are an even sample: every
STEP-th intermission frame and each new picture's injected from both
fills, every CHAIN_STEP-th intermission chained whole, the planted bugs
on every STEP-th frame from the $A5 machine; the capture's counts (214
frames, eight intermissions, eight new pictures) are still checked
whole. DOOM_GS_FULL=1 runs every frame as before.

Needs cc65, build/a2vm/a2vm, the math tables, the release image and the
link map, part s2cap's capture of the tour (python3 tools/native/s2cap.py
--capture), part s2data's store (make -C src/native -f m11.mk part
P=s2data) and S2's objects (make -C src/sound); skips naming what is
missing.

Run by name: python3 tools/testpar.py tests/test_m11_s2wi.py
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
    from ref816 import make_image
    need = []
    if not HAVE_CC65:
        need.append('cc65 on PATH')
    if not s2run.A2VM.exists():
        need.append('build/a2vm/a2vm (make -C tools/a2vm)')
    if not (s2run.TABLES / 'math' / 'squares.bin').exists():
        need.append('the math tables (python3 tools/native/rtables.py)')
    if not make_image.LINKMAP.exists():
        need.append('the link map (tools/v816/imgmatch.py)')
    if not (BUILD / 'upstream' / 'src' / 'iigs' / 'wi_stuff65.s').exists():
        need.append('upstream\'s sources and release (tools/'
                    'fetch_upstream.py)')
    m11 = BUILD / 'native' / 'm11'
    if not (m11 / 'cases' / 'tour' / 'index.json').exists():
        need.append('part s2cap\'s capture of the tour (python3 tools/'
                    'native/s2cap.py --capture)')
    if not ((m11 / 's2data' / 's2data.inc').exists() and
            list((m11 / 's2data').glob('GFX.*'))):
        need.append('part s2data\'s store (make -C src/native -f m11.mk '
                    'part P=s2data)')
    if not (BUILD / 'sound65' / 'player.o').exists():
        need.append('S2\'s objects (make -C src/sound)')
    return ', '.join(need)


MISSING = missing()
needs_build = unittest.skipIf(MISSING, 'needs ' + MISSING)
FULL = support.FULL
STEP = 4            # by default: every STEP-th frame (and each new picture)
CHAIN_STEP = 4      # by default: every CHAIN_STEP-th intermission chained


def sampled(W, cs, excluded):
    """W.cases on the default sample of the frames."""
    pick = support.every(cs, STEP, keep=lambda c: c.black)
    return mock.patch.object(W, 'cases', lambda run=W.RUN: (pick, excluded))


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
        from native import lstore, s2wi as M
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
        from native import s2check as K, s2layout as S, s2wi as W
        got = set(K.offsets(W.screen_region()))
        self.assertEqual(len([a for a in got if a < S.SCB]), 32000)
        self.assertTrue(all(a in got for a in range(S.SCB, S.SCB + 200)))
        self.assertTrue(all(a in got for a in range(S.PALETTES,
                                                    S.SCREEN_END)))
        self.assertFalse(got & set(range(*S.RESERVED)))

    def test_the_stage_matches_the_glue(self):
        """s2wi.py's stage layout is the one src/native/s2_wit.s reads."""
        from native import s2wi as W
        text = (SRC / 's2_wit.s').read_text()

        def const(name):
            m = re.search(r'^%s\s*=\s*\$?([0-9A-F]+)' % name, text, re.M)
            self.assertIsNotNone(m, name)
            return int(m.group(1), 16 if '$' in m.group(0) else 10)
        self.assertEqual(const('T_STAGE'), W.T_STAGE)
        self.assertEqual(const('PER_BANK'), W.PER_BANK)
        self.assertEqual(const('REC_PAGES') * 256, W.REC)
        self.assertEqual(const('C_FLAGS'), W.REC_CTL)
        self.assertLessEqual(W.PER_BANK * W.REC, 0xC000 - 0x0200)
        recs = W.stage_records([W.Stage(bytes([k]) * W.REC, b'', b'')
                                for k in range(W.PER_BANK + 2)])
        self.assertEqual([r[1] for r in recs], [W.T_STAGE, W.T_STAGE + 1])
        self.assertEqual(recs[1][3][W.REC], W.PER_BANK + 1)

    def test_each_planted_edit_is_found_once(self):
        from native import s2wi as W
        for name, source, edits in W.PLANTED:
            text = (SRC / source).read_text()
            for old, _ in edits:
                self.assertEqual(text.count(old), 1, name)

    def test_the_wi_state_comes_from_milestone_10s_include(self):
        """s2_wi.s takes the wi state by lgame.inc's names and defines no
        place of its own for them (SCREENS.md 1.5.5)."""
        text = (SRC / 's2_wi.s').read_text()
        self.assertIn('.include "lgame.inc"', text)
        for name in ('WI_STATE', 'WI_SNLPTR', 'WI_CNTKILLS', 'WI_CNTTIME',
                     'WI_CNTTOTAL', 'WI_CNTPAR', 'G_WMINFO', 'WM_LAST',
                     'WM_NEXT', 'WM_DIDSECRET'):
            self.assertIsNone(re.search(r'^%s\s*=' % name, text, re.M), name)
            self.assertIn(name, text)
        mk = (SRC / 'm11' / 's2wi.mk').read_text()
        self.assertIn('llayout.py --game', mk)


@needs_build
class Checkpoint(unittest.TestCase):
    result = None

    @classmethod
    def setUpClass(cls):
        from native import s2wi as W
        W.make()
        cs, excluded = W.cases()
        cls.capture = (len(cs), len({c.inter for c in cs}),
                       sum(1 for c in cs if c.black))
        if FULL:
            cls.result = W.check(None, W.OUT, 2, ('injected', 'chained'))
            cls.injected = cls.chained = len(cs)
            return
        # the injected frames' sample, then the chained intermissions
        with sampled(W, cs, excluded):
            r = W.check(None, W.OUT, 2, ('injected',))
        cls.injected = r['cases']
        inters = sorted({c.inter for c in cs})[::CHAIN_STEP]
        chain = [c for c in cs if c.inter in inters]
        cls.chained = len(chain)
        with mock.patch.object(W, 'cases',
                               lambda run=W.RUN: (chain, excluded)):
            c = W.check(None, W.OUT, 2, ('chained',))
        for k in ('problems', 'runs'):
            r[k] += c[k]
        r['stray'] += c['stray']
        r['stack'] = max(r['stack'], c['stack'])
        cls.result = r

    def test_every_intermission_frame(self):
        r = self.result
        self.assertEqual(self.capture, (214, 8, 8))
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['excluded'], [])
        self.assertEqual(r['intermissions'], 8)
        self.assertEqual(r['kinds']['new picture'], 8)
        self.assertGreater(r['kinds']['stats'], 0)
        self.assertGreater(r['kinds']['next location'], 0)
        self.assertGreater(r['pointer frames'], 0)
        self.assertEqual(r['stray'], 0)
        self.assertLessEqual(r['stack'], 64 + 24)
        injected = [x for x in r['runs'] if x['tag'].startswith('injected')]
        chained = [x for x in r['runs'] if x['tag'].startswith('chained')]
        self.assertEqual(sum(x['cases'] for x in injected),
                         2 * self.injected)
        self.assertEqual(sum(x['cases'] for x in chained), self.chained)

    def test_the_include(self):
        from native import s2wi as W
        vals = W.inc_values(W.OUT / 'gen' / 's2wi.inc')
        self.assertEqual(vals['WI_PICNUM'], W.picnum())
        own = set(re.findall(r'^(\w+)\s*=', (W.OUT / 'gen' / 's2wi.inc')
                             .read_text(), re.M))
        shared = set(re.findall(r'^(\w+)\s*=', (W.SHARED_GEN / 's2.inc')
                                .read_text(), re.M))
        self.assertFalse(own & shared)

    def test_the_units(self):
        from native import s2wi as W
        u = W.unit_needs()
        self.assertLessEqual(u['most'], u['slots'])

    def test_sizes(self):
        from native import s2wi as W
        s = W.sizes()
        self.assertLessEqual(s['code'], s['code_budget'])
        room = [line for line in s['table'] if ' room ' in line][0]
        used, size = map(int, re.findall(r'(\d+) of\s+(\d+)', room)[0])
        self.assertLessEqual(used, size)
        for line in s['table']:
            if ' own ' not in line:
                self.assertNotIn('OVER', line)


@needs_build
class Planted(unittest.TestCase):
    def test_each_planted_bug_is_caught(self):
        """Each bug from both fills on every frame (by default from $A5
        on the sample)."""
        from native import s2wi as W
        W.make()
        cs, excluded = W.cases()
        for k in range(len(W.PLANTED)):
            if FULL:
                name, problems = W.plant(k, 2)
            else:
                with sampled(W, cs, excluded), \
                        mock.patch.object(W, 'FILLS', W.FILLS[:1]):
                    name, problems = W.plant(k, 2)
            self.assertTrue(problems, name)


if __name__ == '__main__':
    unittest.main()
