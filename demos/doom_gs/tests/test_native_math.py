"""Milestone 6: the native math (src/native/math.s, tools/native/math*).

A sample of what `make -C src/native -f math.mk check-full` checks on a
million inputs a routine: every native routine on a2vm against upstream's
routine on ref816 (or, for the port's own divides, C semantics) on random
and edge inputs and on every input the coverage runs logged; the batch
harness (mathref batch) against ref816's own --call; the host models
against both; the logged calls against their batch runs; the costs and the
write log (no stray writes). Then that these checks fail: bugs planted in
a scratch copy of the sources. The host models' definitions (the divides'
result for a division by zero) are checked without any build.

What the checks need, and skip without: cc65 (ca65, ld65) on PATH;
build/a2vm/a2vm (make -C tools/a2vm); build/ref816/ref816 (make -C
tools/ref816), whose --call the batch harness is checked against;
build/linkmap.json (tools/v816/imgmatch.py); the captures and tables
(make -C src/native -f math.mk tables, which runs tools/native/mathcap.py
on build/ref816/memory.img and disk.hdv, then mathtables.py). The tests
build the math and build/native/math/mathref themselves.
"""

import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

from native import mathcheck, mathdefs, mathrun, mathtables  # noqa: E402
from native.mathdefs import M16, M32  # noqa: E402

ROOT = support.ROOT
SRC = ROOT / 'src' / 'native'
MATH = mathdefs.MATH
SAMPLE = 200

HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
CAPTURED = (MATH / 'captures' / 'newgame' / 'base.ram').exists() and \
    (MATH / 'tables' / 'rndtable.bin').exists()
READY = (HAVE_CC65 and mathrun.A2VM.exists() and CAPTURED and
         mathdefs.LINKMAP.exists() and mathcheck.REF816.exists())
WHY = ('needs cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm), '
       'build/ref816/ref816 (make -C tools/ref816: ref816\'s own --call), '
       'build/linkmap.json and the captures and tables of the native math '
       '(make -C src/native -f math.mk tables)')
needs_build = unittest.skipUnless(READY, WHY)


def make(out: Path, src: Path = SRC) -> str:
    result = subprocess.run(
        ['make', '-C', str(src), '-f', 'math.mk', 'ROOT=%s' % ROOT,
         'OUT=%s' % out, 'TABLES=%s' % (MATH / 'tables')],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True)
    if result.returncode:
        raise AssertionError('make failed:\n' + result.stdout)
    return result.stdout


class Models(unittest.TestCase):
    """The host models' definitions, without any build."""

    def test_divides_follow_c(self):
        rng = random.Random(6)
        for bits in (16, 32):
            mask = (1 << bits) - 1
            for _ in range(2000):
                a = rng.getrandbits(bits)
                b = rng.getrandbits(rng.randrange(1, bits + 1))
                if not b:
                    continue
                sa = a - ((a >> (bits - 1)) << bits)
                sb = b - ((b >> (bits - 1)) << bits)
                q, r = mathdefs.m_sdiv(a, b, bits)
                sq = q - ((q >> (bits - 1)) << bits)
                sr = r - ((r >> (bits - 1)) << bits)
                if sa == -(1 << (bits - 1)) and sb == -1:
                    self.assertEqual((sq, sr), (sa, 0))
                    continue
                self.assertEqual(sq * sb + sr, sa)          # C11 6.5.5
                self.assertLess(abs(sr), abs(sb))
                self.assertTrue(sr == 0 or (sr < 0) == (sa < 0))
                self.assertEqual(abs(sq), abs(sa) // abs(sb))
                self.assertEqual(mathdefs.m_udiv(a, b, bits),
                                 (a // b, a % b))
                self.assertEqual(q & ~mask, 0)

    def test_division_by_zero_is_defined(self):
        self.assertEqual(mathdefs.m_udiv(1234, 0, 16), (0xFFFF, 1234))
        self.assertEqual(mathdefs.m_udiv(0, 0, 32), (M32, 0))
        self.assertEqual(mathdefs.m_sdiv(5, 0, 16), (0x7FFF, 5))
        self.assertEqual(mathdefs.m_sdiv(0, 0, 16), (0x7FFF, 0))
        self.assertEqual(mathdefs.m_sdiv(-5 & M16, 0, 16),
                         (0x8000, -5 & M16))
        self.assertEqual(mathdefs.m_sdiv(-7 & M32, 0, 32),
                         (0x80000000, -7 & M32))
        self.assertEqual(mathdefs.m_sdiv(0x80000000, M32, 32),
                         (0x80000000, 0))

    def test_products(self):
        unit = 0x10000
        for v in (0, 1, 12345, (-12345) & M32, 0x7FFFFFFF, 0x80000000):
            self.assertEqual(mathdefs.m_fixmul(v, unit), v)
            self.assertEqual(mathdefs.m_fixmul(unit, v), v)
        self.assertEqual(mathdefs.m_fixmul((-1) & M32, 1), M32)  # floor
        self.assertEqual(mathdefs.m_fixmul3216(3 << 16, 0x8000), 0x18000)
        self.assertEqual(mathdefs.m_fixmulang(unit, (-1) & M32),
                         (0xFFFF - unit) & M32)
        for a, b in ((0, 0), (0xFFFF, 0xFFFF), (1234, 5678)):
            h = mathdefs.m_qmulh(a, b)
            self.assertIn(h - (a * b >> 16), (0, 1))

    def test_recip_formula(self):
        self.assertEqual(mathdefs.recip_entry(0), 65535)
        self.assertEqual(mathdefs.recip_entry(32767), 32768)
        table = [mathdefs.recip_entry(i) for i in range(32768)]
        self.assertEqual(mathdefs.m_recip(0, table), M32)
        self.assertEqual(mathdefs.m_recip(0x10000, table), 0xFFFF)
        self.assertEqual(mathdefs.m_recip(1, table), 0xFFFF0000)

    def test_every_routine_has_a_native_entry_and_cases(self):
        for r in mathdefs.ROUTINES:
            self.assertTrue(r.native)
            self.assertTrue(r.exhaustive or r.gen, r.name)
            if r.upstream and r.name not in mathdefs.VENDOR:
                self.assertTrue(r.ops_from_up and r.up_bytes and
                                r.res_from_up, r.name)


@needs_build
class Native(unittest.TestCase):
    """The build against upstream on a sample."""

    @classmethod
    def setUpClass(cls):
        make(mathrun.OBJ)
        tool = subprocess.run(['make', '-C', str(ROOT / 'tools' / 'native')],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,
                              universal_newlines=True)
        if tool.returncode:
            raise AssertionError('make -C tools/native failed:\n' +
                                 tool.stdout)
        cls.tables = mathtables.load(mathcheck.capture_dirs()[0] /
                                     'base.ram')

    def setUp(self):
        mathrun.use_build(MATH / 'obj', SRC)

    def test_build_has_no_warnings(self):
        """A clean build of both, into scratch directories (the build
        directories may be up to date, and make then compiles nothing)."""
        with tempfile.TemporaryDirectory() as t:
            out = make(Path(t) / 'obj')
            for tool in ('ca65', 'ld65'):
                self.assertIn(tool, out)            # it did assemble
            self.assertNotIn('warning', out.lower())
            tool = subprocess.run(
                ['make', '-C', str(ROOT / 'tools' / 'native'),
                 'OUT=%s' % (Path(t) / 'ref')],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True)
            self.assertEqual(tool.returncode, 0, tool.stdout)
            self.assertIn('mathref.c', tool.stdout)  # it did compile
            self.assertTrue((Path(t) / 'ref' / 'mathref').exists())
            self.assertNotIn('warning', tool.stdout.lower())

    def test_areas_fit_the_map(self):
        seg = mathrun.segments()
        self.assertEqual(seg['MATHLC'][0], 0xD800)
        self.assertLessEqual(seg['MATHLC'][1], 0xDBFF)
        self.assertEqual(seg['MATHFAR'][0], 0xDC00)
        self.assertEqual(seg['MATHRND'][0] & 0xFF, 0)
        lab = mathrun.labels()
        self.assertEqual(lab['MZ'], 0xB0)
        self.assertEqual(lab['SQL'], 0xD000)

    def test_tables(self):
        with tempfile.TemporaryDirectory(dir=str(MATH)) as t:
            report = mathtables.build(self.tables, Path(t))
        self.assertEqual(len(report['cosine_exceptions']), 12)
        self.assertTrue(report['recip_equals_formula'])
        self.assertEqual(report['sine_magnitude_max'], 0xFFFF)

    def test_every_routine_on_a_sample(self):
        with tempfile.TemporaryDirectory(dir=str(MATH)) as tmp:
            for r in mathdefs.ROUTINES:
                with self.subTest(routine=r.name):
                    d = Path(tmp) / r.name
                    d.mkdir()
                    rep = mathcheck.check_routine(r, SAMPLE, False,
                                                  self.tables, d)
                    self.assertEqual(rep['mismatches'], 0,
                                     rep['mismatch_examples'])
                    self.assertFalse(rep.get('model_mismatches'))
                    self.assertFalse(rep.get('logged_vs_batch_mismatches'))
                    if r.exhaustive:
                        self.assertGreaterEqual(rep['domain_or_random'],
                                                256)
                    if r.name in ('finesine', 'finecosine'):
                        self.assertEqual(rep['domain_or_random'], 8192)

    def test_batch_is_refs_call(self):
        with tempfile.TemporaryDirectory(dir=str(MATH)) as tmp:
            for name in ('fixmul', 'qmul', 'pta3', 'finecosine'):
                d = Path(tmp) / name
                d.mkdir()
                rep = mathcheck.check_routine(mathdefs.BY_NAME[name], 20,
                                              False, self.tables, d,
                                              call_cases=3)
                self.assertEqual(rep['call_checked'], 3)
                self.assertEqual(rep['call_mismatches'], 0)

    def test_costs_and_writes(self):
        for name in ('umul16', 'finesine', 'udiv32'):
            r = mathdefs.BY_NAME[name]
            rng = random.Random(name)
            ops = [tuple(r.exhaustive()[i]) for i in range(0, 8192, 97)] \
                if r.exhaustive else [tuple(r.gen(rng)) for _ in range(60)]
            c = mathcheck.costs(r, ops)
            self.assertEqual(c['stray_writes'], 0, c['stray_examples'])
            self.assertGreater(c['cycles'], 20)
            self.assertGreater(c['f121_us'], 0)
            self.assertGreaterEqual(c['f121_us'], c['fastpath_us'])
            self.assertLessEqual(c['stack_bytes'], 8)


# bugs planted in a scratch copy: (name, file, old text, new text, routine)
BUGS = (
    ('qmulh without its carry', 'math.s',
     '        lda M_R+2\n        adc #0\n        sta M_R\n',
     '        lda M_R+2\n        adc #1\n        sta M_R\n', 'qmulh'),
    ('a division by zero giving 0', 'math.s',
     '        bne ud16go\n        lda #$FF\n',
     '        bne ud16go\n        lda #$00\n', 'udiv16'),
    ('the cosine without its exceptions', 'mathgame.inc',
     'finecosine:\n        ldx cosexc',
     'finecosine:\n        bra @none\n        ldx cosexc', 'finecosine'),
    ('a remainder without the dividend\'s sign', 'math.s',
     ':       bit MT+4\n        bpl :+\n        NEG16 M_T\n',
     ':       bit MT+4\n        bra :+\n        NEG16 M_T\n', 'sdiv16'),
)
STRAY = ('a store into the hot game globals', 'math.s',
         'umul16:\n        lda M_A\n',
         'umul16:\n        stz $1A80\n        lda M_A\n', 'umul16')


@needs_build
class PlantedBugs(unittest.TestCase):
    """The checks fail on a wrong routine."""

    @classmethod
    def setUpClass(cls):
        cls.tables = mathtables.load(mathcheck.capture_dirs()[0] /
                                     'base.ram')

    def tearDown(self):
        mathrun.use_build(MATH / 'obj', SRC)

    def planted(self, tmp: Path, bug):
        _, name, old, new, _ = bug
        src = tmp / 'src'
        src.mkdir()
        for f in ('math.s', 'mathgame.inc', 'math.inc', 'mathdrv.s', 'math.cfg',
                  'math.mk'):
            shutil.copy(str(SRC / f), str(src / f))
        text = (src / name).read_text()
        self.assertEqual(text.count(old), 1, 'the bug no longer applies')
        (src / name).write_text(text.replace(old, new))
        make(tmp / 'obj', src)
        mathrun.use_build(tmp / 'obj', src)

    def test_wrong_results_are_caught(self):
        for bug in BUGS:
            with self.subTest(bug=bug[0]):
                with tempfile.TemporaryDirectory(dir=str(MATH)) as t:
                    tmp = Path(t)
                    self.planted(tmp, bug)
                    (tmp / 'work').mkdir()
                    rep = mathcheck.check_routine(
                        mathdefs.BY_NAME[bug[4]], SAMPLE, False,
                        self.tables, tmp / 'work')
                    self.assertGreater(rep['mismatches'], 0)

    def test_a_stray_write_is_caught(self):
        with tempfile.TemporaryDirectory(dir=str(MATH)) as t:
            tmp = Path(t)
            self.planted(tmp, STRAY)
            r = mathdefs.BY_NAME['umul16']
            c = mathcheck.costs(r, [(3, 5), (1000, 2000)])
            self.assertEqual(c['stray_writes'], 2)
            self.assertIn(' 1A80 main ', c['stray_examples'][0])


if __name__ == '__main__':
    unittest.main()
