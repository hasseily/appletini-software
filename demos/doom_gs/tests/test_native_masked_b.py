"""Milestone 8, stage B (docs/RENDER-MASKED.md 5.2, 4.7): the masked phase
of the native renderer (the sprites clipped against the drawsegs, their
records, the shadows with the fuzz position, the magnified runs, the
masked mid textures, the page model of upstream's lists, the covered
ranges and spans) on a2vm against upstream on ref816.

A sample of checkpoint B: the host model of upstream's masked phase
(tools/native/maskmodel.py) equal to ref816 at playerSkip (P3w) on
captured and synthetic frames, and reaching every path the checkpoint
names on them; the native masked phase (tools/native/render_check.py
--masked, the build mtest with the clip log) equal to P3w on the same
frames, both fills: every record of the frame by column, the covered
ranges and their records, the spans, UPOFS and XPUSED against COLW and
XPNEXT, the modelled flushes, FZ_POS, rw_scalestep, the clips, the
masked columns' marks, the clip log against the call log, no stray
write; the native fallbacks no capture reaches (a drawseg past DSW, a
column of more posts than the card's buffer) with scratch builds that
take them. Then that the checks fail: the bugs of RENDER-MASKED.md 4.7's
stage B list planted in scratch copies.

What it needs, and skips without: cc65 (ca65, ld65) on PATH;
build/a2vm/a2vm (make -C tools/a2vm); build/linkmap.json; the frames of
python3 tools/native/rendercap.py (milestone 8's points, the demo3 set)
and python3 tools/native/framesynth.py (synth-mwlong, synth-pagefull,
synth-mwclose); the tables of python3 tools/native/rtables.py; the levels
of python3 tools/native/levelconv.py --all; the level sources.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

from native import framestate as FS, maskcap as MC, maskmodel as MM, \
    maskroutine as MR, render_check as RC, rlayout as R  # noqa: E402
from bridge import linkmap as blink  # noqa: E402

ROOT = support.ROOT
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
FRAMES = RC.RENDER / 'frames'
# the sample and the paths each stands for (maskmodel's names)
SAMPLE = {
    'still-1': ('ds clips (scales)', 'bottom silhouette'),
    'title-05': ('shadow', 'top silhouette'),
    'title-47': (),
    'demo3-114': ('magnified run', 'extra page'),
    'demo3-048': ('a column past x2',),
    'demo3-344': ('side test back', 'side test front'),
    'demo3-433': ('dsVisible: exact',),
    'demo3-508': ('unit scale',),
    'demo3-372': ('wclipSprite',),
    'tour-31': ('masked range from a sprite', 'masked: column drawn already',
                'K_TEXC', 'masked: peg bottom'),
    'tour-46': ('masked: two lights',),
    'synth-mwlong': ('K_TEXC refused (the page\'s end)',),
    'synth-pagefull': ('flush',),
    'synth-mwclose': ('masked: recip step', 'masked: lower ceiling'),
    'synth-mwlight': ('masked: two lights',),
    'title-50': (),
    'demo-01': (),
}

HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
READY = (HAVE_CC65 and RC.A2VM.exists() and
         (BUILD / 'linkmap.json').exists() and
         (RC.TABLES / 'tables.img').exists() and
         (RC.TABLES / 'pgt.bin').exists() and
         all((FRAMES / f / 'p3w.dump.z').exists() for f in SAMPLE))
WHY = ('needs cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm), '
       'build/linkmap.json, the frames of python3 tools/native/rendercap.py '
       '(milestone 8\'s points, the demo3 set) and python3 tools/native/'
       'framesynth.py, the tables of python3 tools/native/rtables.py, the '
       'levels of python3 tools/native/levelconv.py --all')
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


ROUTINE_FRAMES = ('title-05', 'tour-31', 'tour-46')
HAVE_ROUTINES = all((MC.OUT / f).exists() for f in ROUTINE_FRAMES)
WHY_ROUTINES = ('needs the masked routine captures of python3 tools/native/'
                'maskcap.py')


@needs_build
class Model(unittest.TestCase):
    """The host model of upstream's masked phase: equal to ref816 on the
    sample, and every path of the checkpoint reached."""

    def test_model_equals_ref816_and_reaches_the_paths(self):
        sym = blink.Symbols()
        recip = MM.recip_table()
        for f, paths in SAMPLE.items():
            with self.subTest(frame=f):
                frame = FS.Frame(FRAMES / f)
                problems, info = MM.check(
                    frame, sym, MM.level_memory(frame.meta['level_src']),
                    recip)
                self.assertEqual(problems, [])
                for p in paths:
                    self.assertIn(p, info['paths'], p)

    def test_model_sees_a_wrong_rule(self):
        """The model's covered-range rule with >= for > differs from
        ref816 (the rule is upstream's, not a guess)."""
        sym = blink.Symbols()
        frame = FS.Frame(FRAMES / 'title-47')
        lm = MM.level_memory(frame.meta['level_src'])
        real = MM.Model.cvset

        def cvset(self, c, first, end, index):
            size = (self.cvend[c] - self.cvfirst[c]) & 0xFF
            if size + first > 0xFF or size + first > end:
                return
            self.cvfirst[c], self.cvend[c] = first, end
            self.cvrec[c] = (self.flushes, index)
        MM.Model.cvset = cvset
        try:
            problems, _ = MM.check(frame, sym, lm, MM.recip_table())
        finally:
            MM.Model.cvset = real
        self.assertTrue(any('covered' in p for p in problems), problems)


@needs_build
class Masked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RC.make()
        cls.sym = blink.Symbols()
        cls.b = RC.load_build(RC.OBJ, 'mtest')
        cls.cases = {f: RC.prepare_masked(FRAMES / f, cls.sym)
                     for f in SAMPLE}
        cls.bases = {f: RC.base_records(cls.b, f, window=True)
                     for f in RC.FILLS}

    def test_checkpoint_b_on_the_sample(self):
        for frame in SAMPLE:
            for fill in RC.FILLS:
                with self.subTest(frame=frame, fill=fill):
                    r = RC.check_masked(self.cases[frame], self.b, fill,
                                        self.bases[fill])
                    self.assertEqual(r['problems'], [])
                    self.assertNotIn('known', r)
                    self.assertGreater(r['records'], 0)
                    self.assertLessEqual(r['stack_bytes'] + R.IRQ_STACK,
                                         R.RENDER_STACK)
        # the clip log was compared (a captured frame's call log)
        truth = self.cases['title-05'].masked
        self.assertGreater(len(truth['cliplog']), 0)
        # the modelled flush of synth-pagefull, the extra pages
        self.assertEqual(self.cases['synth-pagefull'].masked['flushes'], 1)
        self.assertEqual(self.cases['synth-pagefull'].masked['xpnext'], 0xCE)

    def test_the_native_fallbacks(self):
        """A drawseg past DSW (fetched from RENDB) and a column of more
        posts than the card's buffer (far_postsc): no capture reaches
        either, so a scratch build with DSW 4 drawsegs and a buffer of 2
        posts must give the same outputs."""
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            obj = planted_obj(Path(t), (
                ('msprite.s', '        lda DS_SLOT\n        cmp #DSW_MAX\n',
                 '        lda DS_SLOT\n        cmp #4\n'),
                ('mfar.s', 'PT_MAX = 16\n', 'PT_MAX = 2\n')))
            b = RC.load_build(obj, 'mtest')
            base = RC.base_records(b, 0xA5, window=True)
            for frame in ('title-05', 'tour-31', 'synth-mwclose'):
                with self.subTest(frame=frame):
                    r = RC.check_masked(self.cases[frame], b, 0xA5, base)
                    self.assertEqual(r['problems'], [])

    def test_timing_by_phase(self):
        prof = RC.load_build(RC.OBJ, 'mprof')
        t = RC.timing_masked(self.cases['tour-31'], prof,
                             RC.base_records(prof, 0xA5, window=True))
        for profile in ('f121', 'fastpath'):
            self.assertGreater(t[profile]['sprites']['ms'], 0)
        # the same code: the cycles differ only by the interrupts, which
        # come on the model's clock
        a, b = (t[p]['sprites']['cycles'] for p in ('f121', 'fastpath'))
        self.assertLess(abs(a - b), a // 20)


@needs_build
@unittest.skipUnless(HAVE_ROUTINES, WHY_ROUTINES)
class Routines(unittest.TestCase):
    """Routine mode (checkpoint B item 1) on a sample: each call alone
    from the reference's entry state, both fills; and a bug it catches."""

    @classmethod
    def setUpClass(cls):
        RC.make()
        cls.sym = blink.Symbols()
        cls.b = RC.load_build(RC.OBJ, 'mtest')
        cls.paths = MR.case_paths(','.join(ROUTINE_FRAMES),
                                  ('sprite', 'vis', 'range', 'seg'))
        cls.bases = {f: RC.base_records(cls.b, f, window=True)
                     for f in RC.FILLS}

    def test_every_kind_equal(self):
        kinds = set()
        for p in self.paths:
            for fill in RC.FILLS:
                with self.subTest(case=p.name, frame=p.parent.name,
                                  fill=fill):
                    r = MR.check_case(p, self.b, fill, self.bases[fill],
                                      self.sym)
                    self.assertEqual(r['problems'], [])
                    kinds.add(r['kind'])
        self.assertEqual(kinds, {'sprite', 'vis', 'range', 'seg'})

    def test_a_bug_is_caught(self):
        """mceilingclip not read: tour-46's masked ranges differ."""
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            obj = planted_obj(Path(t), (('mwall.s', '        lda MCCLIP,y\n',
                                         '        lda #0\n'),))
            b = RC.load_build(obj, 'mtest')
            base = RC.base_records(b, 0xA5, window=True)
            problems = []
            for p in MR.case_paths('tour-46', ('seg', 'range')):
                problems += MR.check_case(p, b, 0xA5, base,
                                          self.sym)['problems']
            self.assertTrue(any('records' in p for p in problems), problems)


# bugs planted in a scratch copy (RENDER-MASKED.md 4.7, stage B): the name,
# the edits, the frames that show it, the words of the problems that must
# catch it
BUGS = (
    ('the drawsegs scanned first to last', (
        ('msprite.s', '@scan:  lda DS_TOT              ; the drawsegs from the '
         'last to the first:\n        sta DS_SLOT             ;   DS_SLOT '
         'counts the slots of those that\n        lda DSCOUNT             ;   '
         'clip (DSX1 not 255)\n        sta DS_K\n@ds:    lda DS_K\n        '
         'bne :+\n        jmp @end\n:       dec DS_K\n        ldx DS_K\n'
         '        lda DSX1,x              ; (255: neither clips nor has '
         'masked columns)\n        cmp #$FF\n        beq @ds\n        dec '
         'DS_SLOT\n',
         '@scan:  lda #$FF\n        sta DS_SLOT\n        sta DS_K\n'
         '@ds:    inc DS_K\n        lda DS_K\n        cmp DSCOUNT\n'
         '        bcc :+\n        jmp @end\n:       ldx DS_K\n'
         '        lda DSX1,x\n        cmp #$FF\n        beq @ds\n'
         '        inc DS_SLOT\n'),),
     ('title-05', 'demo3-344'), ('clip log', 'records')),
    ('the C code\'s -2 for "clip not set"', (
        ('msprite.s', ':       lda FLOORCLIP,x\n        cmp SPRBOT\n        '
         'beq @bfetch\n',
         ':       lda FLOORCLIP,x\n        cmp #$FE\n        beq @bfetch\n'),
        ('msprite.s', ':       lda FLOORCLIP,x\n        cmp SPRBOT\n        '
         'bne :+\n',
         ':       lda FLOORCLIP,x\n        cmp #$FE\n        bne :+\n')),
     ('title-05',), ('clip log',)),
    ('the side test\'s sign flipped', (
        ('msprite.s', ':       bmi :+\n        sec                     ; '
         'the back\n        rts\n:       clc                     ; the '
         'front\n',
         ':       bmi :+\n        clc\n        rts\n:       sec\n'),),
     ('demo3-344',), ('clip log', 'records')),
    ('visCol stopping at x2', (
        ('mvis.s', '@next:  jsr vm_step\n        bcc @col\n@done:  rts\n',
         '@next:  lda V_X\n        cmp SP_X2\n        bcs @done\n'
         '        jsr vm_step\n        bcc @col\n@done:  rts\n'),),
     ('demo3-048',), ('records',)),
    ('YHTAB from E for E - 1', (
        ('mvis.s', '        clc                     ; E - 1 of row -1: '
         'sprtopscreen - spryscale\n',
         '        sec                     ; E - 1 of row -1: '
         'sprtopscreen - spryscale\n'),),
     ('title-50',), ('records',)),
    ('a magnified run ignoring its clips', (
        ('mvis.s', '        lda (V_FCP),y           ; the same clips?\n'
         '        dec a\n        cmp V_HI\n        bne @back\n',
         '        lda (V_FCP),y           ; the same clips?\n'
         '        dec a\n        cmp V_HI\n        bra @run\n'),),
     ('demo3-114',), ('records',)),
    ('FZ_POS not kept', (
        ('mvis.s', '        lda FZPOS\n        sta V_FZ\n',
         '        lda #0\n        sta V_FZ\n'),),
     ('title-05',), ('records', 'fzpos')),
    ('UPOFS one byte off', (
        ('rrec.s', '        dec a                   ; s, upstream\'s size\n',
         '        nop\n'),),
     ('still-1', 'synth-mwlong'), ('upofs',)),
    ('the modelled flush not resetting UPOFS and XPUSED', (
        ('rrec.s', ':       sta UPOFS-1,y\n', ':       lda UPOFS-1,y\n'),
        ('rrec.s', '        stz XPUSED\n        inc UPFLUSH\n',
         '        inc UPFLUSH\n')),
     ('synth-pagefull',), ('upofs', 'flushes', 'xpnext')),
    ('a masked range clipped by sprbottomclip alone (MCCLIP not read)', (
        ('mwall.s', '        lda MCCLIP,y\n', '        lda #0\n'),),
     ('tour-46',), ('records',)),
    ('CVSET\'s test >= for >', (
        ('mvis.s', '        adc V_YL\n        bcs @done\n        cmp V_YH1\n'
         '        bcs @done\n',
         '        adc V_YL\n        bcs @done\n        cmp V_YH1\n'
         '        beq @set\n        bcs @done\n@set:\n'),),
     ('title-47',), ('cv', 'covering')),
    ('FSCUT missing for sprites', (
        ('mvis.s', 'vtexrec:\n        jsr vm_fscut\n', 'vtexrec:\n'),),
     ('demo-01',), ('spans',)),
    ('a masked column drawn twice', (
        ('mwall.s', '        lda MTCLO,y\n        cmp #$FF\n        beq @next\n',
         '        lda MTCLO,y\n        cmp #$FF\n        bra :+\n'),),
     ('tour-31',), ('records',)),
    ('one light for a two-light masked range', (
        ('mwall.s', '        cmp MW_S2\n        beq @one\n',
         '        cmp MW_S2\n        bra @one\n'),),
     ('synth-mwlight',), ('records',)),
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
                    for frame in frames:
                        r = RC.check_masked(self.case(frame), b, 0xA5, base)
                        self.assertTrue(r['problems'], (name, frame))
                        self.assertTrue(any(any(w in p for w in caught)
                                            for p in r['problems']),
                                        (name, frame, r['problems']))


if __name__ == '__main__':
    unittest.main()
