"""Milestone 11, first half, part s2draw (docs/SCREENS.md 1.2-1.4, 6.3,
7.3; docs/m11-parts/s2draw.md): the drawers into a band
(src/native/s2_draw.s), the publish (s2_pub.s), the stand-in s2_begin
(s2_beginstub.s), the host model of the nibble rule
(tools/native/s2draw.py), against upstream's own routines on ref816
(tools/native/s2drawcase.py).

The checkpoint:
  - the truth: ref816 --call of IIGS_DrawPatch, V_DrawPatchNotScaled,
    V_DrawRaw, V_DrawBackground and I_RestoreStatusRect on a state of the
    release with the patch, the position and the tables poked (every
    status bar, menu, intermission and font patch of DOOM1.WAD at four
    positions with both x parities and clipped at each edge, a third of
    them recording CAPVAL and CAPMSK), and the tour's captured calls
    (--capture), the HUD's two texts with their records among them;
  - the host model equals the truth on every case;
  - every case's bytes and marks, drawn natively in bands cut at varying
    rows, equal the truth, and the texts' CAPVAL and CAPMSK;
  - the publish of random marks equals a host copy, from both poisoned
    machines, with 0 stray writes and s2_begin (the stand-in) once, before
    the first band store; a drawing run's write log has 0 stray writes;
  - the sizes: s2_draw and s2_pub 1,200 B, s2_pub alone 200 B;
  - the planted bugs, each in a scratch copy of the sources: the odd
    pixel's mask $0F, the post's row table a row off (parity), the clip at
    x = 320 not taken, pairByte's right table at + $100, the publish
    ending a byte early, the publish not calling s2_begin.

Needs cc65, build/a2vm/a2vm, the math tables (python3 tools/native/
rtables.py), ref816 with the release's memory image (make -C tools/ref816,
python3 tools/ref816/title.py) and DOOM1.WAD (tools/fetch_upstream.py);
skips naming what is missing. The first run captures the base state and
the truth into build/native/m11/s2draw/ (about 2 minutes); later runs
take them from there.

Run by name: python3 tools/testpar.py tests/test_m11_s2draw.py
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import support

ROOT = support.ROOT
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))


def missing() -> str:
    from native import s2run
    from ref816 import lumps, make_image, title
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
    if not (make_image.LINKMAP.exists() and lumps.WAD.exists()):
        need.append('the link map and DOOM1.WAD (tools/fetch_upstream.py, '
                    'tools/v816/imgmatch.py)')
    return ', '.join(need)


MISSING = missing()
needs_build = unittest.skipIf(MISSING, 'needs ' + MISSING)

# (file, old, new): each planted bug, applied once in a scratch copy
PLANTED = {
    'odd_mask': ('s2_draw.s', 'lda #$F0                ; the right pixel',
                 'lda #$0F                ; the right pixel'),
    'row_page_parity': ('s2_draw.s',
                        '        clc                     ;   index '
                        '(upstream\'s NTP)',
                        '        sec                     ;   index '
                        '(upstream\'s NTP)'),
    'clip_320': ('s2_draw.s', '        cmp #$40\n        bcs nextcol',
                 '        cmp #$80\n        bcs nextcol'),
    'pair_right_table': ('s2_draw.s', '        lda ROWR,x\n        sta pr+2',
                         '        lda ROWL,x\n        inc a\n'
                         '        sta pr+2'),
    'publish_byte_early': ('s2_pub.s', '        sty S2_CNT\n',
                           '        dey\n        sty S2_CNT\n'),
    'publish_no_begin': ('s2_pub.s', '        jsr s2_begin\n',
                         '        nop\n        nop\n        nop\n'),
}
# the cases the planted builds run: these patches' eight places, and every
# raw, background and rectangle case
PLANTED_PATCHES = ('STCFN065', 'STTNUM5', 'STFST01', 'M_DOOM', 'WIF')


@needs_build
class Draw(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from native import s2drawcase as C
        cls.C = C
        cls.b = C.build()
        cls.cases, cls.states, cls.set_of = C.synthetic()
        cls.cc, cls.cs, cls.co = C.captured()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='tmp-m11-s2draw-test-',
                                         dir=str(BUILD)))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def test_sizes(self):
        from native import s2layout as S
        C = self.C
        rows, problems = S.check_map('P2DW', (C.OUT / 's2dt.map').read_text())
        self.assertEqual(problems, [])
        ms = S.read_map((C.OUT / 's2dt.map').read_text())
        both = ms.modules['s2_draw'] + ms.modules['s2_pub']
        self.assertLessEqual(both, S.SHARED_BUDGETS['s2_draw+s2_pub'])
        self.assertLessEqual(ms.modules['s2_pub'], S.SHARED_BUDGETS['s2_pub'])
        alone = S.read_map((C.OUT / 's2pt.map').read_text())
        self.assertEqual(alone.modules['s2_pub'], ms.modules['s2_pub'])
        rows, problems = S.check_map('AMAPW',
                                     (C.OUT / 's2pt.map').read_text())
        self.assertEqual(problems, [])
        # AMAPW's size table counts s2_pub.o in its own row (S2DRAW-2)
        row = [r.split() for r in rows if r.split()[1] == 's2_pub']
        self.assertEqual(len(row), 1)
        self.assertEqual(int(row[0][2]), ms.modules['s2_pub'])

    def test_the_column_contract(self):
        D = self.C.D
        over = [n for b, n in D.longest_columns(D.wad_patches())
                if b > D.COLUMN_LIMIT]
        self.assertEqual(over, ['WIMAP0'])     # a picture in the release

    def test_cases_cover_the_patches_and_kinds(self):
        D = self.C.D
        names = {c.name.split('-')[0] for c in self.cases
                 if c.kind in ('patch', 'vpatch')}
        self.assertEqual(names, set(D.wad_patches()) - {'WIMAP0'})
        kinds = {c.kind for c in self.cases}
        self.assertEqual(kinds, {'patch', 'vpatch', 'raw', 'back', 'rect'})
        self.assertGreater(sum(c.cap for c in self.cases), 300)
        self.assertEqual({c.kind for c in self.cc},
                         {'patch', 'vpatch', 'raw', 'back', 'rect'})
        texts = [c for c in self.cc if c.cap]
        self.assertEqual(len(texts), 34)       # the tour's two HUD texts

    def test_the_model_equals_ref816(self):
        C = self.C
        probs = [x for i, c in enumerate(self.cases)
                 for x in C.model_problems(c, self.states[self.set_of[i]])]
        probs += [x for i, c in enumerate(self.cc)
                  for x in C.model_problems(c, self.cs[i])]
        self.assertEqual(probs, [])

    def test_synthetic_native_equals_ref816(self):
        probs, _ = self.C.run_all(self.b, self.cases, self.states,
                                  self.set_of)
        self.assertEqual(probs, [])

    def test_captured_native_equals_ref816(self):
        C = self.C
        probs, _ = C.run_all(self.b, self.cc, self.cs, self.co,
                             C.CAPTURED_A_RUN)
        self.assertEqual(probs, [])
        # the texts' records after their last characters
        last = [c for c in self.cc if c.cap][-1]
        self.assertTrue(any(last.truth['capmsk']))

    def test_a_drawing_run_writes_nothing_stray(self):
        # (6 cases: the log is bounded at 64 MB)
        probs, ms = self.C.run_all(self.b, self.cases[:6], self.states,
                                   self.set_of[:6], write_log=True)
        self.assertEqual(probs, [])
        self.assertGreater(ms[0]['writes'], 10000)

    def test_publish(self):
        C = self.C
        for fill in (0xA5, 0x5A):
            work = self.tmp / ('%02x' % fill)
            probs, m = C.publish_run(self.b, C.publish_cases(fill), fill,
                                     work)
            self.assertEqual(probs, [])
            self.assertGreater(m['bytes'], 1000)
            self.assertEqual(m['stores'], m['bytes'])
            shutil.rmtree(str(work))
        work = self.tmp / 'begun'
        probs, _ = C.publish_run(self.b, C.publish_cases(7), 0xA5, work,
                                 begun=True)
        self.assertEqual(probs, [])

    # -- the planted bugs ---------------------------------------------------

    def planted(self, name: str):
        """The problems of the planted build `name` on the planted cases."""
        C = self.C
        SR = C.SR
        file, old, new = PLANTED[name]
        src = self.tmp / 'src'
        (src / 'm11').mkdir(parents=True)
        shutil.copy(str(SRC / 'm11.mk'), str(src / 'm11.mk'))
        for f in ('s2lay.mk', 's2draw.mk'):
            shutil.copy(str(SRC / 'm11' / f), str(src / 'm11' / f))
        text = (SRC / file).read_text()
        self.assertEqual(text.count(old), 1, name)
        (src / file).write_text(text.replace(old, new))
        m11 = self.tmp / 'm11'
        SR.make('s2draw', m11=m11, source=src)
        b = SR.load_build(m11 / 's2draw', 's2dt', 'P2DW')
        if file == 's2_pub.s':
            return C.publish_run(b, C.publish_cases(0xA5), 0xA5,
                                 self.tmp / 'pub')[0]
        sel = [i for i, c in enumerate(self.cases)
               if c.name.split('-')[0] in PLANTED_PATCHES or
               c.kind in ('raw', 'back', 'rect')]
        probs, _ = C.run_all(b, [self.cases[i] for i in sel], self.states,
                             [self.set_of[i] for i in sel])
        return probs

    def check_caught(self, name: str, *words):
        probs = self.planted(name)
        self.assertTrue(probs, name + ' was not caught')
        print('\nplanted %s: %d problems, first: %s' % (name, len(probs),
                                                       probs[0]))
        for w in words:
            self.assertTrue(any(w in p for p in probs), (name, w, probs[:3]))

    def test_planted_odd_mask(self):
        self.check_caught('odd_mask', 'in-odd', 'the byte')

    def test_planted_row_page_parity(self):
        self.check_caught('row_page_parity', 'the byte')

    def test_planted_clip_320(self):
        self.check_caught('clip_320', '-right')

    def test_planted_pair_right_table(self):
        self.check_caught('pair_right_table', 'STBAR-raw', '-back')

    def test_planted_publish_byte_early(self):
        self.check_caught('publish_byte_early', 'the host copy')

    def test_planted_publish_no_begin(self):
        self.check_caught('publish_no_begin', 's2_begin wrote 0 SCBs')


if __name__ == '__main__':
    unittest.main()
