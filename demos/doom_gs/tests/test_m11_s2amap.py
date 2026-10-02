"""Milestone 11, first half, part s2amap (docs/SCREENS.md 1.5.4, 4.1, 6,
7.3; docs/m11-parts/s2amap.md): the automap's full mode, the image AMAPW
(src/native/s2_am.s, s2_amline.s), against upstream's frames and calls of
coverage/m11/automap.script on ref816 (tools/native/s2amap.py).

What runs here (the checkpoint, `python3 tools/native/s2amap.py --all`,
also runs the timing on f121 and fastpath and writes report.json):
  - the host model of upstream's drawing equals the reference on every
    full-map frame (the map's rows and the byte list, in its order);
  - every full-map frame of automap.script (63), injected from its own
    state with both fills (the second with every byte the frame changes
    poisoned) and chained over the script (the state, the old list and the
    screen carried by the native code, the reference's events and tics in
    between): the map's rows equal to the reference's screen after the
    frame, the other rows their value or black where upstream blacks them,
    the colours untouched, the state, the byte list's bytes, message_new,
    S2_MAIL's bits and the frame block's AUTOMAP as the reference's; no
    stray write; the stack; S2_MAIL's AM_Stop and view bits;
  - every AM_Responder and AM_Ticker call of the script (415), injected
    with both fills and chained: the state after (and the answer and
    player.message) equal;
  - AMAPW's sizes against its room and the part's budget, without pl_poll
    or fx_service;
  - the four planted bugs, each in a scratch copy.

Needs cc65, build/a2vm/a2vm, the math tables, ref816's machine and the
release image, the link map and upstream's sources; the capture is made
when missing (python3 tools/native/s2amap.py --capture, 3 s); skips naming
what is missing.

Run by name: python3 tools/testpar.py tests/test_m11_s2amap.py
"""

import re
import shutil
import struct
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
    if not (s2run.TABLES / 'math' / 'squares.bin').exists():
        need.append('the math tables (python3 tools/native/rtables.py)')
    if not make_image.LINKMAP.exists():
        need.append('the link map (tools/v816/imgmatch.py)')
    if not (BUILD / 'upstream' / 'src' / 'iigs' / 'am_map65.s').exists():
        need.append('upstream\'s sources and release (tools/'
                    'fetch_upstream.py)')
    for p in (title.MACHINE, title.MEMORY, title.DISK):
        if not p.exists():
            need.append('%s (MILESTONES.md "Setting up")' % p.name)
            break
    return ', '.join(need)


MISSING = missing()
needs_build = unittest.skipIf(MISSING, 'needs ' + MISSING)


def ensure_capture():
    from native import s2amap as A
    if not (A.CAP / 'index.json').exists():
        A.capture()


class HandMade(unittest.TestCase):
    """The harness's rules and the sources (no build needed)."""

    def test_the_glue_matches_the_tool(self):
        from native import s2amap as A
        text = (SRC / 's2_amt.s').read_text()
        for name, value in (('T_DIR', A.T_DIR), ('T_RES', A.T_RES),
                            ('RES_SIZE', 128)):
            m = re.search(r'^%s\s*=\s*(\d+)' % name, text, re.M)
            self.assertIsNotNone(m, name)
            self.assertEqual(int(m.group(1)), value, name)
        self.assertNotIn(A.T_DIR, A.STAGE_BANKS)
        self.assertNotIn(A.T_RES, A.STAGE_BANKS)

    def test_the_stage_banks_hold_nothing_the_image_reads(self):
        from native import llayout as LL, rlayout as R, s2amap as A, \
            s2layout as S
        read = {R.LVMAP, R.RTH, LL.LVG0, LL.LVG1, LL.LVS, S.S2STATE,
                S.S2PAL, S.image_banks()['AMAPW'], R.MT_TBANK, R.MT_RLO,
                R.MT_RHI}
        self.assertFalse(read & (set(A.STAGE_BANKS) | {A.T_DIR, A.T_RES}))

    def test_a_case_s_bytes(self):
        from native import s2amap as A
        c = A.Case(((A.K_MAIN, 0, 0x1234, b'\x01\x02'),
                    (A.K_AUX, 104, 0x0700, b'\x03' * 300)),
                   ((0, 0x66),), (A.CALL_FRAME, 4, 0, 0))
        blob = A.case_bytes(c)
        self.assertEqual(blob[0:6], bytes([2, 1, 0, 4, 0, 0]))
        self.assertEqual(blob[6:9], bytes([0, 0x66, 0]))
        kind, bank, addr, n, off = struct.unpack('<BBHHH', blob[0x40:0x48])
        self.assertEqual((kind, bank, addr, n, off),
                         (0, 0, 0x1234, 2, A.CASE_HEAD))
        kind, bank, addr, n, off = struct.unpack('<BBHHH', blob[0x48:0x50])
        self.assertEqual((kind, bank, n, off), (1, 104, 300,
                                                A.CASE_HEAD + 2))
        self.assertEqual(blob[off:off + n], b'\x03' * 300)
        recs = A.stage_records([c, c])
        direc = [r for r in recs if r[1] == A.T_DIR][0][3]
        self.assertEqual(direc[0], 2)
        self.assertEqual(list(direc[1:7]), [A.STAGE_BANKS[0], 0, 2,
                                             A.STAGE_BANKS[1], 0, 2])

    def test_the_native_list_is_by_band(self):
        from native import s2amap as A, s2layout as S
        row = lambda r, b: S.SHR + r * S.ROW_BYTES + b  # noqa: E731
        lst = [row(100, 3), row(5, 1), row(43, 7), row(5, 2), row(159, 0)]
        nat, ob = A.native_list(lst)
        self.assertEqual(nat, [row(5, 1), row(5, 2), row(43, 7), row(100, 3),
                               row(159, 0)])
        self.assertEqual(ob, [0, 2, 3, 4])
        with self.assertRaises(A.AmError):
            A.native_list([row(1, 1)] * (A.LIST_ENTRIES + 1))

    def test_the_state_block_s_places(self):
        """The field map's A_* then this part's own fields (S2AMAP-1), in
        the first page of AMAPW's block (am_load copies one)."""
        from native import s2amap as A, s2layout as S
        sp = A.state_places()
        base = S.OWN_STATE['AMAPW'][1]
        spans = sorted((v, v + n) for k, v in sp.items()
                       for name, n in A.AMAPW_NATIVE if name == k)
        self.assertEqual(spans[0][0], sp['A_AMBAND'] + 2)
        self.assertLessEqual(sp['A_OB'] + 8 - base, 256)

    def test_each_planted_edit_is_found_once(self):
        from native import s2amap as A
        for name, source, edits in A.PLANTED:
            text = (SRC / source).read_text()
            for old, _ in edits:
                self.assertEqual(text.count(old), 1, name)

    def test_amapw_links_the_publish_alone(self):
        mk = (SRC / 'm11' / 's2amap.mk').read_text()
        image = re.search(r'S2AM_IMAGE := (.*?)\n\S', mk, re.S).group(1)
        self.assertIn('s2_pub.o', image)
        for other in ('s2_draw', 'pl_input', 'fx.o', 's2_pal'):
            self.assertNotIn(other, image)


@needs_build
class Checkpoint(unittest.TestCase):
    result = None

    @classmethod
    def setUpClass(cls):
        from native import s2amap as A
        A.make()
        ensure_capture()
        cls.result = A.check(None, A.OUT, 2)

    def test_the_capture(self):
        from native import s2amap as A
        cap = A.Capture()
        self.assertEqual(cap.index['problems'], [])
        self.assertEqual(len(cap.index['frames']), 63)
        self.assertEqual(len(cap.index['calls']), 415)
        self.assertEqual(len({A.static_key(A.level_of(f.E, cap.level, 0))
                              for f in A.frames(cap)}), 1)

    def test_the_model_equals_the_reference(self):
        from native import s2amap as A
        self.assertEqual(A.check_model(A.Capture()), [])

    def test_every_full_map_frame(self):
        r = self.result['frames']
        self.assertEqual(r['problems'], [])
        injected = sum(x['frames'] for x in r['jobs'])
        chained = sum(x['frames'] for x in r['chained'])
        self.assertEqual(injected, 2 * 63)
        self.assertEqual(chained, 63)
        kinds = [k for x in r['jobs'] for k in x['kinds']]
        self.assertEqual(kinds.count('redraw'), 2 * 2)
        self.assertEqual(kinds.count('strip'), 2 * 1)
        self.assertTrue(all(x['stray'] == 0 for x in r['jobs'] +
                            r['chained']))
        self.assertTrue(all(x['stack'] <= 64 + 24 for x in r['jobs'] +
                            r['chained']))
        self.assertEqual(r['mail']['problems'], [])

    def test_every_responder_and_ticker_call(self):
        r = self.result['calls']
        self.assertEqual(r['problems'], [])
        self.assertEqual(sum(x['calls'] for x in r['jobs']), 2 * 415)
        self.assertEqual(sum(x['calls'] for x in r['chained']), 415)

    def test_sizes(self):
        from native import s2amap as A
        s = A.sizes()
        self.assertLessEqual(s['own'], s['own_budget'])
        self.assertTrue(s['no_poll_or_service'])
        room = [line for line in s['table'] if ' room ' in line][0]
        used, size = map(int, re.findall(r'(\d+) of\s+(\d+)', room)[0])
        self.assertLessEqual(used, size)
        for line in s['table']:
            self.assertNotIn('OVER', line)


STEP = 3            # by default: the plants' every STEP-th injected frame


@needs_build
class Planted(unittest.TestCase):
    def test_each_planted_bug_is_caught(self):
        """Each bug on the checks (by default on every STEP-th injected
        frame and every second stretch of full-map frames chained, the
        calls whole: tests/README.md; DOOM_GS_FULL=1 every frame)."""
        from native import s2amap as A
        A.make()
        ensure_capture()
        frame_jobs, chain_jobs = A.frame_jobs, A.chain_jobs
        with mock.patch.object(A, 'frame_jobs', lambda fr: frame_jobs(
                support.every(fr, STEP))), \
                mock.patch.object(A, 'chain_jobs', lambda fr: support.every(
                    chain_jobs(fr), 2)):
            for k in range(len(A.PLANTED)):
                name, problems, _ = A.plant(k, 2)
                self.assertTrue(problems, name)


if __name__ == '__main__':
    unittest.main()
