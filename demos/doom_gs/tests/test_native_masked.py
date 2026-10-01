"""Milestone 8, stage A (docs/RENDER-MASKED.md 5.1, 4.7): the sprite data
of the level converter, the sprite tables, the deferred projection and
the sort of the masked phase on a2vm against upstream on ref816, and the
bucket pass's prototype against milestone 5's loader.

A sample of checkpoint A: the builds without warnings and within their
budgets; the patch store, the sprite frames and patch headers of E1M7
(tools/native/levelconv.py) with every check, and the reach of the
records measured (--overrun); the scale records (tools/native/
rtables.py); the host model of upstream's projection (tools/native/
projmodel.py) equal to ref816 on a sample; the masked checkpoint
(tools/native/render_check.py --masked: the front end, then the masked
image loaded, the drawseg copy, the projection of the listed sectors and
the sort; the vissprites equal P3's, the order, FR_SKIP and W_WSK P3s's,
the listed sectors ref816's R_AddSprites calls, milestone 7's outputs at
the walk's end P3's, no stray write) on captured and synthetic frames,
both fills; the bucket prototype (tools/native/bucketcheck.py) equal to
the loader's batches, column starts, covered ranges and fuzz marks. Then
that the checks fail: bugs planted in scratch copies (RENDER-MASKED.md
4.7's stage A list, and the bucket prototype's, the converter's and the
tables' checks).

What it needs, and skips without: cc65 (ca65, ld65) on PATH;
build/a2vm/a2vm (make -C tools/a2vm); build/linkmap.json; the frames of
python3 tools/native/rendercap.py (with milestone 8's points and the demo3
set) and python3 tools/native/framesynth.py; the tables of python3
tools/native/rtables.py; the level sources.
"""

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

from native import bucketcheck as BC, framestate as FS, levelconv, \
    projmodel as PM, render_check as RC, rlayout as R, rtables  # noqa: E402
from bridge import linkmap as blink  # noqa: E402

ROOT = support.ROOT
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
FRAMES = RC.RENDER / 'frames'
MASKED = ('still-1', 'demo3-371', 'demo3-053', 'tour-10', 'synth-spectre',
          'synth-crowd', 'synth-close', 'synth-edge', 'synth-qmulh')
BUCKET = ('demo-09', 'title-05', 'synth-crowd')
PLANTS = ('newgame-40', 'demo3-049')    # (a thing just off the side)
E1M7 = levelconv.SOURCES / 'title-e1m7-t44.ram.z'

HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
READY = (HAVE_CC65 and RC.A2VM.exists() and
         (BUILD / 'linkmap.json').exists() and
         (RC.TABLES / 'tables.img').exists() and
         (RC.TABLES / 'sfirst.bin').exists() and E1M7.exists() and
         all((FRAMES / f / 'p3s.dump.z').exists()
             for f in MASKED + BUCKET + PLANTS))
WHY = ('needs cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm), '
       'build/linkmap.json, the frames of python3 tools/native/rendercap.py '
       '(milestone 8\'s points, the demo3 set) and python3 tools/native/'
       'framesynth.py, the tables of python3 tools/native/rtables.py')
needs_build = unittest.skipUnless(READY, WHY)

SOURCES = ('math.s', 'math.inc', 'rframe.s', 'rbsp.s', 'rlight.s',
           'auxlc.s', 'far.s', 'rdriver.s', 'rwall.s', 'rseg.s', 'rseg.inc',
           'rsky.s', 'rrec.s', 'render.cfg', 'render.mk', 'mmain.s',
           'mproj.s', 'mfar.s', 'msprite.s', 'mvis.s', 'mwall.s',
           'bucket.s', 'bdriver.s', 'bucket.cfg', 'wclip.s', 'wpsp.s', 'mpsp.s',
           'rrunner.s', 'replay.s')


def planted_obj(tmp: Path, bugs) -> Path:
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
    return tmp / 'obj'


def planted_module(tmp: Path, module, edits):
    """A scratch copy of a tool's module with the edits, imported."""
    path = tmp / (module.__name__.split('.')[-1] + '_planted.py')
    text = Path(module.__file__).read_text()
    for old, new in edits:
        if text.count(old) != 1:
            raise AssertionError('the bug no longer applies: %r' % old)
        text = text.replace(old, new)
    path.write_text(text)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@needs_build
class Converter(unittest.TestCase):
    """The sprite part of the level (RENDER-MASKED.md 1.3-1.4, 1.11)."""

    @classmethod
    def setUpClass(cls):
        cls.sym = blink.Symbols()
        cls.memory = levelconv.load_memory(E1M7)
        cls.level = levelconv.convert(cls.memory, cls.sym, E1M7.name)

    def test_patch_store_and_its_checks(self):
        info = self.level.info['sprites']
        self.assertEqual(levelconv.check_store(self.level, self.memory),
                         len(info['store']))
        self.assertGreater(len(info['store']), 300)
        self.assertEqual(info['not_frames'], [[1, 4]])  # SHTG's state E
        # every converted frame names a stored patch or the placeholder,
        # and the patch headers are the lumps' own
        for e in info['store'][:20]:
            ph = self.level.banks.get(R.SPRT, R.PHDRS.address(e['index']),
                                      R.PHDR_SIZE)
            self.assertEqual(ph[0:2], self.memory.read(e['address'], 2))
            self.assertEqual(ph[2:6], self.memory.read(e['address'] + 4, 4))
        # the tail: the 128 bytes after each lump, read across its bank
        e = max(info['store'], key=lambda e: (e['address'] + e['size']) &
                0xFFFF)
        got = self.level.banks.get(e['bank'], e['at'] + e['size'],
                                   levelconv.TAIL)
        self.assertEqual(got, self.memory.read(e['address'] + e['size'],
                                               levelconv.TAIL))
        # SFIRST: the converter's frames are rtables.py's
        sfirst = (RC.TABLES / 'sfirst.bin').read_bytes()
        at = 0
        for s, n in enumerate(info['frames_per_sprite']):
            self.assertEqual(sfirst[s] | sfirst[R.NUMSPRITES + s] << 8, at)
            at += n

    def test_a_wrong_store_is_caught(self):
        """A lump stored from one byte on: the store check fails."""
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            lc = planted_module(Path(t), levelconv, (
                ('        banks.put(bank, at, m.read(address, need))',
                 '        banks.put(bank, at, m.read(address + 1, need))'),))
            level = lc.convert(self.memory, self.sym, E1M7.name)
            with self.assertRaises(lc.ConvError) as caught:
                lc.check_store(level, self.memory)
            self.assertIn('differs from the reference', str(caught.exception))

    def test_a_frame_address_by_the_wrong_rule_is_caught(self):
        """The frames read at 19 f without upstream's $7FFF mask of the
        product are the same here (f < 1724); a stride of 18 is not: the
        headers read differ, and the frames of the states stop resolving
        (a garbage lump number)."""
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            lc = planted_module(Path(t), levelconv, (
                ('    low = (sf + ((19 * (f & 0x7FFF)) & 0x7FFF)) & 0xFFFF',
                 '    low = (sf + ((18 * (f & 0x7FFF)) & 0x7FFF)) & 0xFFFF'),))
            level = lc.convert(self.memory, self.sym, E1M7.name)
            self.assertNotEqual(level.info['sprites']['not_frames'],
                                self.level.info['sprites']['not_frames'])

    def test_overrun_reach(self):
        # a post of 8 texels at a step of 1.0 from texel 0: rows read 0-7
        self.assertEqual(levelconv.reach(0, 127, 0, 1, 8), 7)
        # magnified: 0.25 a row, 8 rows from texel 2
        self.assertEqual(levelconv.reach(0xC0, 1, 0x40, 0, 8), 4)
        # a first row just below texel 0 reads texel 127 (masked)
        self.assertEqual(levelconv.reach(0xF0, 127, 0x08, 0, 1), 127)
        summary = json.loads((levelconv.LEVELS / 'overrun.json').read_text()) \
            if (levelconv.LEVELS / 'overrun.json').exists() else None
        if summary is not None:
            self.assertLessEqual(summary['past_post'], 127)
            self.assertLess(summary['past_lump'], levelconv.TAIL)


@needs_build
class Tables(unittest.TestCase):
    """The sprite scale records (RENDER-MASKED.md 1.6)."""

    def test_scale_records_and_their_checks(self):
        sym = blink.Symbols()
        ram = rtables.made_source(rtables.ram_of(E1M7), sym)
        tab = rtables.sprite_tables(ram)
        recip = rtables.words(rtables.rd(ram, rtables.MM_RECIP, 65536))
        rtables.check_sprite_tables(tab, recip)
        recs = rtables.scale_records(tab)
        self.assertEqual(len(recs), R.SCALE_SIZE * (R.MAXZ + 1))
        d = 100
        rec = recs[R.SCALE_SIZE * d:R.SCALE_SIZE * (d + 1)]
        self.assertEqual(int.from_bytes(rec[0:4], 'little'), (80 << 16) // d)
        self.assertEqual(int.from_bytes(rec[4:8], 'little'),
                         (160 << 16) // d)
        self.assertEqual((int.from_bytes(rec[12:14], 'little'), rec[14]),
                         divmod(16 * d, 5))
        # a wrong SPRISCALE entry is caught
        bad = dict(tab, **{'is': list(tab['is'])})
        bad['is'][700] ^= 1
        with self.assertRaises(rtables.TableError):
            rtables.check_sprite_tables(bad, recip)
        cmop = (RC.TABLES / 'cmop.bin').read_bytes()
        self.assertEqual(len(cmop), 85)
        self.assertEqual((cmop[0], cmop[24], cmop[55], cmop[84]),
                         (0x46, 0x46, 0x65, 0x65))


@needs_build
class Model(unittest.TestCase):
    """The host model of upstream's projection and sort on a sample."""

    def test_model_equals_ref816(self):
        sym = blink.Symbols()
        for f in MASKED:
            with self.subTest(frame=f):
                self.assertEqual(PM.check_frame(FRAMES / f, sym), [])


@needs_build
class Masked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RC.make()
        cls.sym = blink.Symbols()
        cls.b = RC.load_build(RC.OBJ, 'mtest')
        cls.cases = {f: RC.prepare_masked(FRAMES / f, cls.sym)
                     for f in MASKED}
        cls.bases = {f: RC.base_records(cls.b, f, window=True)
                     for f in RC.FILLS}

    def test_builds_fit_their_budgets(self):
        s = self.b.segments
        self.assertEqual(s['MASKW'][0], R.MCODE)
        self.assertLess(s['MASKW'][1], R.MCODE_END)
        self.assertLessEqual(s['AUXW'][1], R.MCODE - 1)
        self.assertLessEqual(RC.w_end(self.b), R.WCODE_END - 1)
        self.assertLessEqual(s['MFAR'][1], R.FAR_CARD_END - 1)
        self.assertLessEqual(R.frame_block_used(), R.FRAME_BLOCK_SIZE)
        self.assertLessEqual(sum(n for _, n in R.RENDER_INPUTS),
                             R.RIN_END - R.RIN)
        seg = BC.segments()
        # stage C: BKCARD's routines went into BKFAR and BKFAR2 (main
        # $0200-$02FF), both copied from the masked image
        near = seg['BKNEAR'][1] + 1 - seg['BKNEAR'][0]
        self.assertLessEqual(near, 371)         # the card's $F900 part left
        self.assertLessEqual(seg['BKFAR'][1], 0x0EFF)
        self.assertGreaterEqual(seg['BKFAR2'][0], R.BKFAR2_RUN)
        self.assertLessEqual(seg['BKFAR2'][1], R.BKFAR2_END - 1)

    def test_masked_checkpoint_on_a_sample(self):
        for frame in MASKED:
            for fill in RC.FILLS:
                with self.subTest(frame=frame, fill=fill):
                    r = RC.check_masked(self.cases[frame], self.b, fill,
                                        self.bases[fill])
                    self.assertEqual(r['problems'], [])
                    self.assertNotIn('known', r)
                    self.assertGreater(r['vissprites'], 0)
                    self.assertGreater(r['irqs'], 0)
                    self.assertLessEqual(r['stack_bytes'] + R.IRQ_STACK,
                                         R.RENDER_STACK)

    def test_the_sample_reaches_its_paths(self):
        """Each synthetic frame takes the path it stands for."""
        c = self.cases
        crowd = c['synth-crowd'].vis
        self.assertEqual(len(crowd['vis']), R.MAXVIS)   # the cut
        scales = [v['scale'] for v in crowd['vis']]
        self.assertLess(len(set(scales)), len(scales))  # the sort's ties
        spectre = c['synth-spectre']
        self.assertIn(0, [v['page'] for v in spectre.vis['vis']])
        self.assertEqual(spectre.vis['fr_skip'], 0)     # sortSkip cleared
        p3 = FS.Frame(FRAMES / 'synth-spectre').dump('p3')
        self.assertEqual(p3.u(self.sym.address('FR_SKIP'), 2), 1)
        cov = PM.coverage([FRAMES / 'synth-close', FRAMES / 'synth-edge'],
                          self.sym)['synth']
        for path in ('wHi', 'x1neg', 'reject:labsTZ', 'gGZ', 'fixmulx:xl',
                     'fixmulx:xr'):
            self.assertIn('frames:' + path, cov, path)

    def test_timing_by_phase(self):
        prof = RC.load_build(RC.OBJ, 'mprof')
        t = RC.timing_masked(self.cases['demo3-371'], prof,
                             RC.base_records(prof, 0xA5, window=True))
        for profile in ('f121', 'fastpath'):
            for phase in ('mwindow', 'dscopy', 'project', 'sort', 'walk'):
                self.assertGreater(t[profile][phase]['ms'], 0, phase)
        self.assertEqual(t['f121']['project']['cycles'],
                         t['fastpath']['project']['cycles'])


@needs_build
class Bucket(unittest.TestCase):
    """The bucket pass's prototype against milestone 5's loader."""

    @classmethod
    def setUpClass(cls):
        RC.make()
        cls.sym = blink.Symbols()
        cls.streams = {f: BC.stream_of(FS.Frame(FRAMES / f),
                                       BC.front_staging(FRAMES / f, cls.sym),
                                       cls.sym) for f in BUCKET}

    def test_prototype_equals_the_loader(self):
        for f in BUCKET:
            for fill in RC.FILLS:
                with self.subTest(frame=f, fill=fill):
                    r = BC.check(self.streams[f], fill)
                    self.assertEqual(r['problems'], [])
        self.assertGreater(BC.check(self.streams['title-05'], 0xA5)['marks'],
                           0)
        self.assertEqual(BC.check(self.streams['synth-crowd'],
                                  0xA5)['batches'], 3)

    def test_bucket_bugs_are_caught(self):
        for name, edits, frames, caught in BUCKET_BUGS:
            with self.subTest(bug=name):
                with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
                    obj = planted_obj(Path(t), edits)
                    problems = []
                    for f in frames:
                        try:
                            problems += BC.check(self.streams[f], 0xA5,
                                                 obj=obj)['problems']
                        except BC.BucketError as e:
                            problems.append(str(e))
                    self.assertTrue(problems, name)
                    self.assertTrue(any(any(w in p for w in caught)
                                        for p in problems), problems)


# bugs planted in a scratch copy (RENDER-MASKED.md 4.7, stage A): the name,
# the edits, the frames that show it, and the words of the problems that
# must catch it
BUGS = (
    ('a fractional thing\'s G parts exact, not upstream\'s qmulh', (
        ('mproj.s', '        ldy #YCOS\n        sec\n        jsr gpart\n'
         '        ldx #MP_GZ\n        jsr put32\n',
         '        ldy #YCOS\n        clc\n        jsr gpart\n'
         '        ldx #MP_GZ\n        jsr put32\n'),
        ('mproj.s', '        ldy #YSIN\n        sec\n        jsr gpart\n'
         '        ldx #MP_GX\n        jsr put32\n',
         '        ldy #YSIN\n        clc\n        jsr gpart\n'
         '        ldx #MP_GX\n        jsr put32\n'),
        ('mproj.s', '        ldy #YSIN\n        sec\n        jsr gpart\n'
         '        ldx #MP_GZ\n        jsr add32\n',
         '        ldy #YSIN\n        clc\n        jsr gpart\n'
         '        ldx #MP_GZ\n        jsr add32\n'),
        ('mproj.s', '        ldy #YCOS\n        sec\n        jsr gpart\n'
         '        ldx #MP_GX\n        jsr sub32\n',
         '        ldy #YCOS\n        clc\n        jsr gpart\n'
         '        ldx #MP_GX\n        jsr sub32\n')),
     ('synth-qmulh',), ('vissprite',)),
    ('the rotation\'s + $9000 as + $8000', (
        ('mproj.s', '        adc #$90\n', '        adc #$80\n'),),
     ('demo3-371',), ('vissprite',)),
    ('a flip ignored', (
        ('mproj.s', '        and SFR+SF_FLIP\n', '        and #0\n'),),
     ('demo3-371',), ('vissprite',)),
    ('the early rejection reading E / 2 + 2 for E', (
        ('mproj.s', '        adc SPRB,x\n        sta MP_T4\n        lda '
         'SPRB+1,x\n', '        adc SPRB+2,x\n        sta MP_T4\n        lda '
         'SPRB+3,x\n'),),
     ('newgame-40', 'demo3-049'), ('vissprite',)),
    ('the sort\'s ties swapped', (
        ('mproj.s', '        ldy #VR_SCALE           ; s[j - 1]\'s scale < '
         'temp\'s, signed\n        lda (MP_VP),y\n        cmp MP_FT\n'
         '        iny\n        lda (MP_VP),y\n        sbc MP_FT+1\n'
         '        iny\n        lda (MP_VP),y\n        sbc MP_FT+2\n'
         '        iny\n        lda (MP_VP),y\n        sbc MP_FT+3\n'
         '        bvc :+\n        eor #$80\n:       bpl @put\n',
         '        ldy #VR_SCALE           ; (temp < s[j - 1]: stop)\n'
         '        lda MP_FT\n        cmp (MP_VP),y\n        iny\n'
         '        lda MP_FT+1\n        sbc (MP_VP),y\n        iny\n'
         '        lda MP_FT+2\n        sbc (MP_VP),y\n        iny\n'
         '        lda MP_FT+3\n        sbc (MP_VP),y\n        bvc :+\n'
         '        eor #$80\n:       bmi @put\n'),),
     ('synth-crowd',), ('order',)),
    ('MAXVISSPRITES 79', (
        ('mproj.s', '        cmp #MAXVIS\n        bcc :+\n        rts\n',
         '        cmp #MAXVIS - 1\n        bcc :+\n        rts\n'),),
     ('synth-crowd',), ('vissprites: native 79',)),
    ('CMOP one page off', (
        ('mproj.s', '        lda cmop,x\n', '        lda cmop+1,x\n'),),
     ('demo3-371',), ('vissprite',)),
    ('sortSkip blind to shadows', (
        ('mproj.s', '        lda (MP_VP),y\n        beq @shadow\n',
         '        lda (MP_VP),y\n        nop\n        nop\n'),),
     ('synth-spectre',), ('fr_skip', 'w_wsk')),
    ('a sector listed twice in SPRSEC', (
        ('rbsp.s', '        sta SPRSEC,x\n        sta RAMWRTOFF\n        inc '
         'SPRN\n', '        sta SPRSEC,x\n        sta SPRSEC+1,x\n        '
         'sta RAMWRTOFF\n        inc SPRN\n        inc SPRN\n'),),
     ('still-1',), ('listed sectors', 'vissprites: native')),
    ('a store into the masked image\'s code', (
        ('mmain.s', 'nm_masked:\n        MARK 14 ',
         'nm_masked:\n        stz nm_masked\n        MARK 14 '),),
     ('still-1',), ('stray',)),
)

BUCKET_BUGS = (
    ('the K_FUZZNOW marks missing', (
        ('bucket.s', '        lda #K_FUZZNOW\n        sta (BK_P)\n',
         '        nop\n        nop\n        nop\n        nop\n'),),
     ('title-05',), ('the loader',)),
    ('the record cut by a chunk\'s end dropped', (
        ('bucket.s', 'chunk:  ldx #0\n        ldy BK_AT\n',
         'chunk:  ldx #0\n        ldy BK_LEN\n'),),
     ('demo-09',), ('the loader', 'ended', 'batches')),
    ('a covered range\'s W address one record off', (
        ('bucket.s', '        lda BK_SEQ\n        cmp CVRECLO,x\n',
         '        lda BK_SEQ\n        dec a\n        cmp CVRECLO,x\n'),),
     ('title-05',), ('covering record',)),
)


@needs_build
class PlantedBugs(unittest.TestCase):
    """The checks fail on a wrong masked phase."""

    @classmethod
    def setUpClass(cls):
        cls.sym = blink.Symbols()
        cls.cases = {}

    def case(self, frame):
        if frame not in self.cases:
            self.cases[frame] = RC.prepare_masked(FRAMES / frame, self.sym)
        return self.cases[frame]

    def test_bugs_are_caught(self):
        for name, edits, frames, caught in BUGS:
            with self.subTest(bug=name):
                with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
                    obj = planted_obj(Path(t), edits)
                    b = RC.load_build(obj, 'mtest')
                    base = RC.base_records(b, 0xA5, window=True)
                    problems = []
                    for frame in frames:
                        r = RC.check_masked(self.case(frame), b, 0xA5, base)
                        problems += r['problems']
                    self.assertTrue(problems, name)
                    self.assertTrue(any(any(w in p for w in caught)
                                        for p in problems), problems)


if __name__ == '__main__':
    unittest.main()
