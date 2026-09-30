"""Milestone 7, stage A: the native renderer's front end on a2vm against
upstream on ref816 (docs/RENDER.md 4.5, 5.1).

A sample of checkpoint A: the build without warnings and within its
areas; the frame check of tools/native/render_check.py (the wall calls,
the stamps, the vertex angles computed, the clears and derived values at
the walk's entry, no stray write, interrupts taken) on four captured
frames, one of them with a fixed colormap and a gamma other than 0; check
A3 (tools/native/sidecheck.py: upstream's viewSide with c14Bounds against
nr_side) on a sample of E1M1's and E1M6's cases; the aux card's reads
against the tables; the frame injection's cross-check with the bridge's
Reader. Then that the checks fail: bugs planted in a scratch copy of the
sources (RENDER.md 4.5's list for stage A, and a stray store).

What it needs, and skips without: cc65 (ca65, ld65) on PATH;
build/a2vm/a2vm (make -C tools/a2vm); build/native/math/mathref (make -C
tools/native); build/linkmap.json; the frames and level sources of python3
tools/native/rendercap.py and the tables of python3 tools/native/
rtables.py.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

from native import framestate as FS, levelconv, render_check as RC, \
    rlayout as R, sidecheck  # noqa: E402
from bridge import linkmap as blink  # noqa: E402

ROOT = support.ROOT
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
FRAMES = RC.RENDER / 'frames'
SAMPLE = ('still-1', 'demo-10', 'tour-30', 'lights-08')

HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
READY = (HAVE_CC65 and RC.A2VM.exists() and sidecheck.MATHREF.exists() and
         (BUILD / 'linkmap.json').exists() and
         (RC.TABLES / 'tables.img').exists() and
         all((FRAMES / f / 'frame.json').exists() for f in SAMPLE))
WHY = ('needs cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm), '
       'build/native/math/mathref (make -C tools/native), '
       'build/linkmap.json, the captures of python3 tools/native/'
       'rendercap.py and the tables of python3 tools/native/rtables.py')
needs_build = unittest.skipUnless(READY, WHY)

SOURCES = ('math.s', 'math.inc', 'rframe.s', 'rbsp.s', 'rlight.s',
           'auxlc.s', 'far.s', 'rdriver.s', 'rwall.s', 'rseg.s', 'rseg.inc',
           'rsky.s', 'rrec.s', 'render.cfg', 'render.mk')


def planted_build(tmp: Path, bugs) -> RC.Build:
    """The sources copied to tmp/src with each (file, old, new) applied
    once, built into tmp/obj."""
    src = tmp / 'src'
    src.mkdir()
    for f in SOURCES:
        shutil.copy(str(SRC / f), str(src / f))
    for name, old, new in bugs:
        text = (src / name).read_text()
        if text.count(old) != 1:
            raise AssertionError('the bug no longer applies: %r' % old)
        (src / name).write_text(text.replace(old, new))
    RC.make(tmp / 'obj', src)
    return RC.load_build(tmp / 'obj')


@needs_build
class FrontEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RC.make()
        cls.b = RC.load_build()
        cls.sym = blink.Symbols()
        cls.cases = {f: RC.prepare(FRAMES / f, cls.sym) for f in SAMPLE}

    def check(self, frame, b=None, fill=0xA5):
        b = b or self.b
        return RC.check_frame(self.cases[frame], b, fill,
                              RC.base_records(b, fill))

    def test_build_fits_its_areas(self):
        s = self.b.segments
        self.assertLessEqual(s['MATHW'][1], R.WCODE_END - 1)
        self.assertLessEqual(s['RFAR'][1], R.FAR_CARD_END - 1)
        self.assertEqual(s['RFAR'][0], R.FAR_CARD)
        self.assertLessEqual(s['MATHLC'][1], 0xDBFF)
        mods = RC.module_sizes()
        for key, (seg, budget) in RC.BUDGETS.items():
            used = sum(mods.get(m, {}).get(seg, 0) for m in key.split('+'))
            self.assertLessEqual(used, budget, key)

    def test_checkpoint_a_on_a_sample(self):
        for frame in SAMPLE:
            for fill in RC.FILLS:
                with self.subTest(frame=frame, fill=fill):
                    r = self.check(frame, fill=fill)
                    self.assertEqual(r['problems'], [])
                    self.assertGreater(r['walls'], 0)
                    self.assertGreater(r['irqs'], 0)
                    self.assertLessEqual(r['stack_bytes'] + R.IRQ_STACK,
                                         R.RENDER_STACK)

    def test_the_sample_reaches_its_paths(self):
        c = self.cases
        self.assertGreater(c['demo-10'].truth['vtxangle'], 0)
        self.assertEqual(c['still-1'].truth['vtxangle'], 0)
        self.assertNotEqual(c['lights-08'].truth['bsp_entry']['lt_fixed'],
                            0xFFFF)
        self.assertEqual(c['still-1'].truth['bsp_entry']['lt_fixed'],
                         0xFFFF)

    def test_the_injection_is_checked_by_the_reader(self):
        f = FS.Frame(FRAMES / 'newgame-01')
        level = json.loads((FS.level_of(f, self.sym) / 'level.json')
                           .read_text())
        inputs = FS.read_inputs(f, self.sym, level)
        self.assertIn('the Reader agrees', FS.cross_check(f, inputs,
                                                          self.sym))
        inputs['sectors'][0]['floorpic'] = 300
        with self.assertRaises(levelconv.ConvError):
            FS.records(f, inputs, level)

    def test_side_check_sample(self):
        for g in (1, 6):
            with self.subTest(map=g):
                r = sidecheck.check_map(g, self.sym, self.b, 3000, 40000, 7)
                self.assertEqual(r['problems'], [])
                self.assertEqual(r['differ'], 0)
                self.assertGreater(r['branches']['greater'], 0)
                self.assertGreater(r['branches']['less'], 0)

    def test_walllight_equals_upstream(self):
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            r = sidecheck.walllight_check(self.b, self.sym, Path(t))
        self.assertEqual(r['differ'], 0, r['first'])
        self.assertGreater(r['cases'], 50000)

    def test_anglea_stays_in_the_sine_table(self):
        """rsga's anglea = ANG90 + xtoviewangle[x] (high words) lies in
        $0000-$7FFF for every column, so its sine index is never negative
        and sinelow needs no rule for it (RENDER.md 3.9)."""
        img = {(k, b, a): d for k, b, a, d in levelconv.Image.parse(
            (RC.TABLES / 'tables.img').read_bytes())}
        lo, hi = img[(0, 0, R.XTVLO)], img[(0, 0, R.XTVHI)]
        anglea = [(lo[x] | hi[x] << 8) + 0x4000 & 0xFFFF
                  for x in range(R.VIEWWIDTH)]
        self.assertLess(max(anglea), 0x8000)

    def test_aux_card_reads(self):
        tables = RC.TABLES
        img = {(k, b, a): d for k, b, a, d in levelconv.Image.parse(
            (tables / 'tables.img').read_bytes())}
        vtox = img[(1, 0, R.AX_VTOX - 0x1000)]
        tan3 = (img[(1, 0, R.AX_TAN3 - 0x1000)],
                img[(1, 0, R.AX_TAN3 - 0x1000 + 0x400)])
        tan4 = [img[(1, 0, R.AX_TAN4 + 0x400 * k)] for k in range(4)]
        tanto = [img[(1, 0, R.AX_TANTO + 0x800 * k)] for k in range(4)]
        lab = self.b.labels
        oa, oy = lab['DRV_OA'], lab['DRV_OY']
        ia, ix = lab['DRV_IA'], lab['DRV_IX']
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            work = Path(t)
            idx = list(range(0, 2042, 7)) + [2040, 2041]
            res = sidecheck.bulk(self.b, 'ax_vtox', [ia, ix],
                                 [oa], [bytes([i >> 8, i & 0xFF])
                                        for i in idx], work)
            self.assertEqual([r[0] for r in res], [vtox[i] for i in idx])
            idx = list(range(0, 2048, 13)) + [2047]
            res = sidecheck.bulk(self.b, 'ax_tanto', [ia, ix], [oa, oy],
                                 [bytes([i >> 8, i & 0xFF]) for i in idx],
                                 work)
            self.assertEqual([(r[0], r[1]) for r in res],
                             [(tanto[2][i], tanto[3][i]) for i in idx])
            idx = list(range(0, 1024, 11)) + [1023]
            res = sidecheck.bulk(self.b, 'ax_tan3', [ia, ix], [oa, oy],
                                 [bytes([i >> 8, i & 0xFF]) for i in idx],
                                 work)
            self.assertEqual([(r[0], r[1]) for r in res],
                             [(tan3[0][i], tan3[1][i]) for i in idx])
            out = lab['ax_out']
            res = sidecheck.bulk(self.b, 'ax_tan4', [ia, ix],
                                 [out, out + 1, out + 2, out + 3],
                                 [bytes([i >> 8, i & 0xFF]) for i in idx],
                                 work)
            self.assertEqual([tuple(r) for r in res],
                             [tuple(tan4[k][i] for k in range(4))
                              for i in idx])


# bugs planted in a scratch copy (RENDER.md 4.5, stage A): the name, the
# edits, the frame that shows it, and what must catch it
BUGS = (
    ('viewSide\'s side flipped for dy < 0 (dx 0)', (
        ('rbsp.s', '        bmi @s0\n        dey\n',
         '        bmi @dx0lt\n        dey\n'),), 'still-1', 'call'),
    ('the plane colours with extralight', (
        ('rlight.s', '        adc LT_BASE\n        sec\n        sbc '
         'EXTRALIGHT\n', '        adc LT_BASE\n'),), 'title-22', 'call'),
    ('a sector not stamped', (
        ('rbsp.s', '        lda #2\n        sta FA_N\n        jsr far_put\n',
         '        lda #2\n        sta FA_N\n'),), 'still-1',
     'sector_valid'),
    ('the vertex stamp advanced every frame', (
        ('rbsp.s', '        lda VA_STAMP\n        bne @keep\n',
         '        lda VA_STAMP\n        bra @new\n'),), 'still-2',
     'vertex angles'),
    ('the fixed colormap ignored by the planes', (
        ('rlight.s', '        lda LT_FIXED+1          ; the fixed '
         'colormap: LT_FIXED >> 3\n        bmi @light\n',
         '        lda LT_FIXED+1          ; the fixed colormap: LT_FIXED '
         '>> 3\n        bra @light\n'),), 'lights-08', 'call'),
    ('a store into the hot game globals', (
        ('rbsp.s', 'nr_side:\n        ldy #ND_DX\n',
         'nr_side:\n        stz $1A80\n        ldy #ND_DX\n'),), 'still-1',
     'stray'),
)


@needs_build
class PlantedBugs(unittest.TestCase):
    """The checks fail on a wrong front end."""

    @classmethod
    def setUpClass(cls):
        cls.sym = blink.Symbols()

    def test_bugs_are_caught(self):
        for name, edits, frame, caught in BUGS:
            with self.subTest(bug=name):
                with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
                    b = planted_build(Path(t), edits)
                    case = RC.prepare(FRAMES / frame, self.sym)
                    r = RC.check_frame(case, b, 0xA5,
                                       RC.base_records(b, 0xA5))
                    self.assertTrue(r['problems'], name)
                    self.assertTrue(any(caught in p for p in r['problems']),
                                    r['problems'])

    def test_a_wrong_fake_contrast_is_caught(self):
        """R_WallLight's contrast the other way: + 1 along x."""
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            b = planted_build(Path(t), (
                ('rlight.s', '        lda LT_I                ; along x: - 1\n'
                 '        bne :+\n        dec LT_I+1\n:       dec LT_I\n',
                 '        inc LT_I                ; along x: + 1 (bug)\n'
                 '        bne @done\n        inc LT_I+1\n'),))
            with tempfile.TemporaryDirectory(dir=str(BUILD)) as w:
                r = sidecheck.walllight_check(b, self.sym, Path(w))
            self.assertGreater(r['differ'], 0)

    def test_a_flipped_side_is_caught_by_a3(self):
        """viewSide's products compared the wrong way: check A3."""
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            b = planted_build(Path(t), (
                ('rbsp.s', ':       eor #$80\n        asl a\n        rts\n\n'
                 '; shiftmul', ':       asl a\n        rts\n\n; shiftmul'),))
            r = sidecheck.check_map(1, self.sym, b, 500, 5000, 3)
            self.assertGreater(r['differ'], 0)

    def test_a3_edges_aimed_wrong_are_caught(self):
        """The edge generator aiming at +-317 instead of +-417: the
        coverage check (log differences 416 and 417 not reached)."""
        import importlib.util
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            copy = Path(t) / 'sidecheck_bug.py'
            text = (ROOT / 'tools' / 'native' / 'sidecheck.py').read_text()
            old = 'AIM = 417 '
            new = 'AIM = 317 '
            self.assertEqual(text.count(old), 1, 'the bug no longer applies')
            copy.write_text(text.replace(old, new))
            spec = importlib.util.spec_from_file_location('sidecheck_bug',
                                                          copy)
            bug = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bug)
            r = bug.check_map(1, self.sym, RC.load_build(), 500, 20000, 3)
            self.assertTrue(any('log difference' in p
                                for p in r['problems']), r['problems'])


if __name__ == '__main__':
    unittest.main()
