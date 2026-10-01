"""Milestone 8, stage C (docs/RENDER-MASKED.md 5.3, 4.7): the whole frame
of the native renderer (the weapon's clip pass, the weapon's draw, the
bucket pass, milestone 5's replay into the SHR) on a2vm against upstream
on ref816, and the disk image of acceptance 2.

A sample of checkpoint C (tools/native/frame8.py; the whole of it is
frame8.py --sets m7,demo3 --poisoned --timing): the whole frame, both
fills, on still-1, demo-10, a demo3 frame with shadows and fuzz marks
(demo3-053), synth-mwlong, synth-pagefull (its input screen composed from
an early flush), the weapon's synthetic frames (invis: the shadow weapon;
flash: the flash by R_DrawVisSprite; skipwall: the weapon rows skipped,
wclipSprite; wphigh: a psprite above WEAPONTOP) and synth-qmulh (the
patch header's reload): the clip pass at P1, the front end, the masked
phase at the weapon and at its end, the bucket check of each batch, all
of aux 0 $2000-$9FFF against P5, the SHR writes against the model, no
stray write, the stack. A poisoned screen on still-1 and demo3-053; the
timing of still-1; the bucket pass with a scratch build whose batches
are 2 KB (a frame of 5 or more batches: the groups of three, the parked
batches); the game build's ST_RECORDS policy (RENDER-MASKED.md 6.1) with
a scratch build whose staging ends at aux 0; the disk image on its first
3 frames, chained and full, on a2vm. Then that the checks fail: the bugs
of RENDER-MASKED.md 4.7's stage C list planted in scratch copies.

What it needs, and skips without: cc65 (ca65, ld65) on PATH;
build/a2vm/a2vm (make -C tools/a2vm); build/linkmap.json; the ref816
machine (python3 tools/ref816/title.py); the frames of python3
tools/native/rendercap.py (the m7 sets, demo3) and python3
tools/native/framesynth.py; the m5 captures (python3 tools/ref816/
capture.py); the tables of python3 tools/native/rtables.py; the levels of
python3 tools/native/levelconv.py --all; appletini-one's ProDOS (the disk).
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

from native import bucketcheck as BC, frame8 as F8, rdisk as RD, \
    render_check as RC, rlayout as R, sidecheck as SC  # noqa: E402
from bridge import linkmap as blink  # noqa: E402
from ref816 import title  # noqa: E402

ROOT = support.ROOT
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
FRAMES = RC.RENDER / 'frames'
SAMPLE = ('still-1', 'demo-10', 'demo3-053', 'synth-mwlong',
          'synth-pagefull', 'synth-invis', 'synth-flash', 'synth-skipwall',
          'synth-wphigh', 'synth-qmulh')

HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
READY = (HAVE_CC65 and RC.A2VM.exists() and title.MACHINE.exists() and
         (BUILD / 'linkmap.json').exists() and
         (RC.TABLES / 'tables.img').exists() and
         (F8.CAPTURES / 'still-1' / 'manifest.json').exists() and
         all((FRAMES / f / 'p5.dump.z').exists() for f in SAMPLE))
WHY = ('needs cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm), the '
       'ref816 machine, build/linkmap.json, the frames of python3 tools/'
       'native/rendercap.py (the m7 sets, demo3) and python3 tools/native/'
       'framesynth.py, the m5 captures (python3 tools/ref816/capture.py), '
       'the tables of python3 tools/native/rtables.py, the levels of '
       'python3 tools/native/levelconv.py --all')
needs_build = unittest.skipUnless(READY, WHY)

SOURCES = ('math.s', 'math.inc', 'rframe.s', 'rbsp.s', 'rlight.s',
           'auxlc.s', 'far.s', 'rdriver.s', 'rwall.s', 'rseg.s', 'rseg.inc',
           'rsky.s', 'rrec.s', 'render.cfg', 'render.mk', 'mmain.s',
           'mproj.s', 'mfar.s', 'msprite.s', 'mvis.s', 'mwall.s',
           'bucket.s', 'bdriver.s', 'bucket.cfg', 'wclip.s', 'wpsp.s',
           'mpsp.s', 'rrunner.s', 'replay.s')


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


class Cases:
    """The prepared frames, shared by the classes (each takes a few
    seconds)."""
    sym = None
    cases = {}

    @classmethod
    def get(cls, frame):
        if cls.sym is None:
            cls.sym = blink.Symbols()
        if frame not in cls.cases:
            cls.cases[frame] = F8.prepare8(FRAMES / frame, cls.sym)
        return cls.cases[frame]


@needs_build
class WholeFrame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RC.make()
        cls.b = RC.load_build(RC.OBJ, 'ftest')
        cls.bases = {f: RC.base_records(cls.b, f, window=True)
                     for f in RC.FILLS}

    def test_checkpoint_c_on_the_sample(self):
        for frame in SAMPLE:
            case = Cases.get(frame)
            for fill in RC.FILLS:
                with self.subTest(frame=frame, fill=fill):
                    r = F8.check8(case, self.b, fill, self.bases[fill])
                    self.assertEqual(r['problems'], [])
                    self.assertNotIn('known', r)
                    self.assertGreater(r['records'], 0)
                    self.assertEqual(r['differing'], 0)
                    self.assertEqual(r['shr_writes'], r['stores'])
                    self.assertLessEqual(r['stack_bytes'] + R.IRQ_STACK,
                                         R.RENDER_STACK)
        # the paths the sample stands for
        self.assertEqual(Cases.get('synth-pagefull').composed['flushes'], 1)
        self.assertEqual(Cases.get('synth-invis').clip['frvis'][
            R.FV['PAGE']], 0)                       # the shadow weapon
        self.assertEqual(Cases.get('synth-skipwall').final['fr_skip'], 1)
        self.assertEqual(Cases.get('still-1').clip['wpok'], 1)

    def test_batches_marks_and_the_chunk_cut(self):
        """demo3-053: two batches, the fuzz marks, a staging of many
        chunks (every one of more than 180 bytes cuts a record)."""
        r = F8.check8(Cases.get('demo3-053'), self.b, 0xA5,
                      self.bases[0xA5])
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['batches'], 2)
        self.assertGreater(r['marks'], 0)
        self.assertGreater(r['staged'], 180 * 10)

    def test_poisoned_screens(self):
        for frame in ('still-1', 'demo3-053'):
            with self.subTest(frame=frame):
                r = F8.poisoned8(Cases.get(frame), self.b, Cases.sym,
                                 self.bases[0x5A])
                self.assertEqual(r['problems'], [])
                self.assertGreater(r['changed'], 0)

    def test_timing(self):
        prof = RC.load_build(RC.OBJ, 'fprof')
        t = F8.timing8(Cases.get('still-1'), prof,
                       RC.base_records(prof, 0xA5, window=True))
        for profile in ('f121', 'fastpath'):
            for phase in ('clip', 'weapon', 'bucket', 'replay'):
                self.assertGreater(t[profile][phase]['ms'], 0, phase)
        self.assertLess(t['fastpath']['total_ms'], t['f121']['total_ms'])

    def test_known_divergence_is_not_a_pass(self):
        """A frame whose RULES is not 0 is listed by name, never equal
        (question 13): the run's RULES forced by a record."""
        case = Cases.get('still-1')
        base = list(self.bases[0xA5]) + [(0, 0, R.FRAME['RULES'],
                                          b'\x01')]
        real = F8.image_records

        def records(c, screen=None):
            return real(c, screen) + [(0, 0, R.FRAME['RULES'], b'\x01')]
        F8.image_records = records
        try:
            r = F8.check8(case, self.b, 0xA5, base)
        finally:
            F8.image_records = real
        self.assertIn('known', r)


@needs_build
class Groups(unittest.TestCase):
    def test_small_batches(self):
        """A scratch build with 2 KB batches: demo-10 takes 5 or more, in
        groups of three (the later ones parked in RECW and brought back);
        the bucket check with the loader's packing at 2 KB, the screen."""
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            obj = planted_obj(Path(t), (
                ('bucket.s', 'RECBUF_SPAN = $2000', 'RECBUF_SPAN = $0800'),))
            b = RC.load_build(obj, 'ftest')
            base = RC.base_records(b, 0xA5, window=True)
            real = BC.BATCH_BYTES
            BC.BATCH_BYTES = 0x0800
            try:
                r = F8.check8(Cases.get('demo-10'), b, 0xA5, base)
            finally:
                BC.BATCH_BYTES = real
            self.assertEqual(r['problems'], [])
            self.assertGreaterEqual(r['batches'], 5)


@needs_build
class ReleasePolicy(unittest.TestCase):
    def test_st_records_in_the_game_build(self):
        """-D RELEASE with the staging's last area aux 0 (6.1): demo-10
        stages more than aux 0's 8 KB, so its later batches are dropped;
        the frame completes (no BRK), STATUS is ST_RECORDS, the bucket
        pass replays what was staged (the bucket check and the model's
        screen stores hold on the native staging), no stray write; its
        records and screen then differ from the reference's."""
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            obj = planted_obj(Path(t), (
                ('rrec.s', 'LAST_AREA = RECSP_LAST', 'LAST_AREA = 0'),
                ('render.mk', 'ASFLAGS = --cpu 65C02 -g',
                 'ASFLAGS = -D RELEASE --cpu 65C02 -g')))
            b = RC.load_build(obj, 'ftest')
            base = RC.base_records(b, 0xA5, window=True)
            keep = Path(t) / 'keep'
            r = F8.check8(Cases.get('demo-10'), b, 0xA5, base, keep=keep)
            end = RC.snapshot(keep, 'end')
            self.assertEqual(end.main(R.FRAME['STATUS'], 1)[0],
                             R.ST_RECORDS)
            self.assertEqual(end.main(R.FRAME['RECDROP'], 1)[0], 1)
            problems = r['problems']
            for p in problems:
                self.assertNotIn('stray', p)
                self.assertNotIn('stopped', p)
                self.assertNotIn('batch', p)
                self.assertNotIn('SHR writes', p)
            self.assertTrue(any('screen' in p for p in problems), problems)
            self.assertLessEqual(r['staged'], 0x2000)

    def test_the_last_area_s_end(self):
        """-D RELEASE with the real last area (the spill's last bank):
        rec_flush called alone (drv_bulk) on batches that end before, at
        and past its end. A batch ending exactly at $C000 is dropped like
        one past it (the copy's step at $C000 would otherwise look for an
        area after the last and stop the frame); the areas before the last
        step on as before."""
        F = R.FRAME
        last, before = R.RECSP[-1], R.RECSP[-2]
        rb = R.ZP2['RB']
        places = [F['STG_BANK'], F['STG_PTR'], F['STG_PTR'] + 1, rb,
                  F['RECDROP'], F['STATUS'], F['STATUS'], F['STATUS']]

        def case(bank, ptr, n, drop=0):
            return bytes([bank, ptr & 0xFF, ptr >> 8, n, drop, 0, 0, 0])

        def out(bank, ptr, drop, status):
            return bytes([bank, ptr & 0xFF, ptr >> 8, 0, drop, status,
                          status, status])
        cases = [
            (case(last, 0xC000 - 200, 200), out(last, 0xC000 - 200, 1, 2)),
            (case(last, 0xC000 - 201, 200), out(last, 0xBFFF, 0, 0)),
            (case(last, 0xC000 - 199, 200), out(last, 0xC000 - 199, 1, 2)),
            (case(last, 0xBF00, 255), out(last, 0xBFFF, 0, 0)),
            (case(last, 0xC000 - 255, 255), out(last, 0xC000 - 255, 1, 2)),
            (case(last, 0x0200, 100, 1), out(last, 0x0200, 1, 0)),
            (case(before, 0xC000 - 200, 200), out(last, 0x0200, 0, 0)),
            (case(before, 0xC000 - 100, 200), out(last, 0x0200 + 100, 0,
                                                  0)),
            (case(0, 0xC000 - 200, 200), out(R.RECSP[0], 0x0200, 0, 0)),
        ]
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            obj = planted_obj(Path(t), (
                ('render.mk', 'ASFLAGS = --cpu 65C02 -g',
                 'ASFLAGS = -D RELEASE --cpu 65C02 -g'),))
            b = RC.load_build(obj, 'ftest')
            got = SC.bulk(b, 'rec_flush', places, places,
                          [c for c, _ in cases], Path(t) / 'run')
        for (c, want), g in zip(cases, got):
            with self.subTest(case=c.hex()):
                self.assertEqual(g.hex(), want.hex())

    def test_a_column_past_the_replay_s_stage(self):
        """-D RELEASE with the replay's stage shrunk to 96 bytes (its
        pointer list from $8100, its texels from $80A0), so that on
        still-1 a column alone does not fit it: the column is cut where its
        records stop fitting (6.1), the frame completes with STATUS
        ST_RECORDS, no stray write (the cut's column end in COLLO/COLHI
        allowed to the game build's replay); the same scratch without
        RELEASE stops at the replay's BRK."""
        stage = (
            ('replay.s', '        stz     pl\n        lda     #>STAGE_END\n'
             '        sta     pl+1\n        stz     gdx\n',
             '        stz     pl\n        lda     #>(STAGE + $0100)\n'
             '        sta     pl+1\n        stz     gdx\n'),
            ('replay.s', '        stz     pl\n        lda     #>STAGE_END\n'
             '        sta     pl+1\n        lda     sc0\n',
             '        stz     pl\n        lda     #>(STAGE + $0100)\n'
             '        sta     pl+1\n        lda     sc0\n'),
            ('replay.s', '        sta     sc0\n        stz     gtop\n',
             '        sta     sc0\n        lda     #$A0\n'
             '        sta     gtop\n'))
        release = (('render.mk', 'ASFLAGS = --cpu 65C02 -g',
                    'ASFLAGS = -D RELEASE --cpu 65C02 -g'),)
        case = Cases.get('still-1')
        for game in (True, False):
            with self.subTest(release=game), \
                    tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
                obj = planted_obj(Path(t), stage + (release if game
                                                    else ()))
                b = RC.load_build(obj, 'ftest')
                base = RC.base_records(b, 0xA5, window=True)
                keep = Path(t) / 'keep'
                r = F8.check8(case, b, 0xA5, base, keep=keep, release=game)
                problems = r['problems']
                if not game:
                    self.assertTrue(any('stopped' in p for p in problems),
                                    problems)
                    continue
                end = RC.snapshot(keep, 'end')
                self.assertEqual(end.main(R.FRAME['STATUS'], 1)[0],
                                 R.ST_RECORDS)
                for p in problems:
                    self.assertNotIn('stray', p)
                    self.assertNotIn('stopped', p)
                    self.assertNotIn('batch', p)
                self.assertTrue(any('screen' in p for p in problems),
                                problems)


def synthetic_stream(columns, covered=()) -> 'BC.Stream':
    """A staging made of records of the given kinds (columns: {column:
    list of kinds, 0 K_TEX, 2 K_FILL}), produced round robin over the
    columns (so that each walk meets every column's records spread over
    the staging), and covered ranges (column, record's index in its
    column, first row, end row)."""
    sizes = {0: 11, 2: 5}
    queues = {c: list(kinds) for c, kinds in columns.items()}
    records, seq_of = [], {}
    while any(queues.values()):
        for c in sorted(queues):
            if queues[c]:
                kind = queues[c].pop(0)
                k = len(columns[c]) - len(queues[c]) - 1
                seq_of[(c, k)] = len(records)
                data = bytes([kind]) + bytes((c + k + i) & 0x7F
                                             for i in range(1, sizes[kind]))
                records.append((c, data))
    staged = b''.join(BC.staged_form(c, d) for c, d in records)
    first, end, lo, hi = (bytearray(160) for _ in range(4))
    cover = {}
    for c, k, a, e in covered:
        n = seq_of[(c, k)]
        first[c], end[c], lo[c], hi[c] = a, e, n & 0xFF, n >> 8
        cover[c] = n
    return BC.Stream(staged, records, bytes(first + end + lo + hi), cover,
                     0)


@needs_build
class BucketLimits(unittest.TestCase):
    """The bucket pass (build btest) at the limits of RENDER-MASKED.md 6.1
    and of its batch list."""

    def test_the_most_batches(self):
        """45 columns of 4,097 W bytes (372 K_TEX and a K_FILL each, 4,470
        bytes staged: 201,150 in all, the staging's 202,752 nearly full):
        no two fit one batch, so the frame takes MAXB (45) batches, the
        bound rlayout.py proves; each equals the loader's. (The list held
        26 before 2026-10-01: such a frame stopped the bucket pass.)"""
        stream = synthetic_stream(
            {c: [0] * 372 + [2] for c in range(45)},
            covered=((10, 5, 20, 40), (44, 371, 0, 168)))
        self.assertLessEqual(len(stream.staged), R.STAGING_BYTES)
        RC.make()
        r = BC.check(stream, 0xA5, cycles=400_000_000, write_log=False)
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['batches'], R.MAXB)

    def test_a_column_past_a_batch(self):
        """Column 3 holds 760 K_TEX (8,360 W bytes, more than a batch):
        the test build stops (BRK, ST_BUCKET); the game build (-D RELEASE)
        cuts it after its 744th record (8,184 bytes; its batch ends with
        it), clears its covered range (its covering record, the 750th, was
        cut), keeps column 5's, sets ST_RECORDS, and every batch equals
        the loader's with the same rule."""
        stream = synthetic_stream(
            {2: [0] * 300, 3: [0] * 760, 4: [2] * 3, 5: [0] * 400 + [2],
             9: [2] * 10},
            covered=((3, 749, 10, 100), (5, 2, 0, 50)))
        RC.make()
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            with self.assertRaises(BC.BucketError) as e:
                BC.run(stream, 0xA5, Path(t) / 'run')
        self.assertIn('BRK', str(e.exception))
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            obj = planted_obj(Path(t), (
                ('render.mk', 'ASFLAGS = --cpu 65C02 -g',
                 'ASFLAGS = -D RELEASE --cpu 65C02 -g'),))
            r = BC.check(stream, 0xA5, obj=obj, release=True)
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['cut'], [3])
        self.assertEqual(r['status'], R.ST_RECORDS)
        exp = BC.expected(stream, release=True)
        self.assertNotIn(3, exp.cover_w)
        self.assertIn(5, exp.cover_w)
        self.assertEqual([(f, e) for f, e, _, _ in exp.batches],
                         [(0, 3), (3, 4), (4, 160)])


class StagingMargin(unittest.TestCase):
    """RENDER-MASKED.md 6.1 item 1 as frame8.py checks it on every run:
    the capacity at least STAGING_MARGIN times the largest staging of the
    captured frames, every frame within it (no hand-entered figure)."""

    def test_the_check(self):
        cap = R.STAGING_BYTES
        top = cap // R.STAGING_MARGIN
        ok = [{'frame': 'demo3-036', 'staged': top},
              {'frame': 'synth-pagefull', 'staged': top * 2}]
        self.assertTrue(F8.staging_margin(ok)[1])
        for bad in ([{'frame': 'demo3-036', 'staged': top + 1}],
                    [{'frame': 'synth-pagefull', 'staged': cap + 1}]):
            text, good = F8.staging_margin(bad)
            self.assertFalse(good)
            self.assertIn('Below', text)


# bugs planted in a scratch copy (RENDER-MASKED.md 4.7, stage C): the name,
# the edits, the frames that show it, the words of the problems that must
# catch it
BUGS = (
    ('wdProf\'s order as visPost\'s (the highest post first)', (
        ('mpsp.s', '        ldx #0                  ; the lowest post of the '
         'column\n@post:  lda WPLST,x             ; a + 1 (0: no more posts)'
         '\n        beq @next\n',
         '        ldx #0\n@end:   lda WPLST,x\n        beq @post\n'
         '        inx\n        inx\n        inx\n        inx\n        inx\n'
         '        bra @end\n@post:  txa\n        beq @next\n        dex\n'
         '        dex\n        dex\n        dex\n        dex\n'),
        ('mpsp.s', '@up:    inx                     ; the post above\n'
         '        inx\n        inx\n        inx\n        inx\n'
         '        bra @post\n', '@up:    bra @post\n')),
     ('newgame-20',), ('records',)),
    ('wclipSprite missing', (
        ('mvis.s', '        jsr vwclip\n', ''),),
     ('demo3-372',), ('records',)),
    ('the flash not drawn', (
        ('mpsp.s', '        ldx #1\n        bra pspsprite\n',
         '        rts\n'),),
     ('synth-flash',), ('records', 'clip log')),
    ('the clip pass\'s run start one row low', (
        ('wclip.s', '        adc WP_YH0              ;   (carry set)\n',
         '        adc WP_YH0\n        inc a\n'),),
     ('still-1',), ('the clip pass: floorclip',)),
    ('a covered range\'s W address one byte off', (
        ('bucket.s', '        lda BK_P\n        sta CVRECLO,x\n',
         '        lda BK_P\n        inc a\n        sta CVRECLO,x\n'),),
     ('still-1',), ('covering record',)),
    ('K_FUZZNOW marks missing', (
        ('bucket.s', '        lda #K_FUZZNOW\n        sta (BK_P)\n',
         '        lda #K_FUZZ\n        sta (BK_P)\n'),),
     ('demo3-053',), ('batch',)),
    ('a batch starting one column late (the split inside the batches)', (
        ('bucket.s', '        beq @stop               ;   walk 1)\n'
         '        iny\n        bra @batch\n',
         '        beq @stop\n        inx\n        iny\n        bra @batch\n'),),
     ('demo-10',), ('batch ',)),
    ('a record lost at the bucket (walk 2 skips column 80\'s fills)', (
        ('bucket.s', 'walk2:  ldx P1+1,y\n',
         'walk2:  ldx P1+1,y\n        cpx #80\n        bne :+\n'
         '        lda P1,y\n        cmp #K_FILL\n        beq @seq\n:\n'),),
     ('still-1', 'demo3-053'), ('batch ',)),
    ('the record cut by a chunk\'s end dropped', (
        ('bucket.s', '@mv:    cpy BK_LEN\n        beq @mvd\n',
         '@mv:    bra @mvd\n        beq @mvd\n'),),
     ('still-1',), ('batch', 'stopped', 'bucket')),
    ('the psprite\'s sy as 16 bits (its fraction dropped)', (
        ('wpsp.s', '        sbc PSP0_SY,y\n', '        sbc #0\n'),
        ('wpsp.s', '        sbc PSP0_SY+1,y\n', '        sbc #0\n')),
     ('demo3-053',), ('frvis', 'records')),
    ('the patch header not reloaded for wdProf', (
        ('mpsp.s', '        jsr mwp_head            ; the patch\'s header',
         '        ; the patch\'s header'),),
     ('synth-qmulh',), ('records', 'screen')),
    ('a store into the masked image\'s code', (
        ('mpsp.s', '        sta DS_IDX\n        ldx FRVIS+FV_PATCH',
         '        sta DS_IDX\n        sta visdraw\n        ldx FRVIS+FV_PATCH'),),
     ('still-1',), ('stray',)),
)


@needs_build
class PlantedBugs(unittest.TestCase):
    """The checks fail on a wrong stage C."""

    def test_bugs_are_caught(self):
        for name, edits, frames, caught in BUGS:
            with self.subTest(bug=name):
                with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
                    obj = planted_obj(Path(t), edits)
                    b = RC.load_build(obj, 'ftest')
                    base = RC.base_records(b, 0xA5, window=True)
                    for frame in frames:
                        r = F8.check8(Cases.get(frame), b, 0xA5, base)
                        self.assertTrue(r['problems'], (name, frame))
                        self.assertTrue(any(any(w in p for w in caught)
                                            for p in r['problems']),
                                        (name, frame, r['problems']))

    def test_input_screen_composition(self):
        """The input screen of 2.3 item 4 on the flush frame: P4 whole
        differs from the composition in the bytes the flush wrote (the
        rule is exercised). RENDER-MASKED.md 4.7's planted bug "the input
        screen taken from P4 whole" is not observable on synth-pagefull,
        the only flush frame: every one of those bytes is drawn again by
        the frame's records (no pre-flush shadow reads them), so both
        inputs give P5 ("Stage C as built")."""
        RC.make()
        b = RC.load_build(RC.OBJ, 'ftest')
        case = Cases.get('synth-pagefull')
        p4 = case.mc.full.case.frame.dump('p4').read(F8.E1_SCREEN,
                                                     F8.SCREEN_SIZE)
        differ = sum(1 for i in range(F8.SCREEN_SIZE)
                     if p4[i] != case.screen[i])
        self.assertEqual(differ, case.composed['flushed_bytes'])
        self.assertGreater(differ, 0)
        r = F8.check8(case._replace(screen=p4), b, 0xA5,
                      RC.base_records(b, 0xA5, window=True))
        self.assertEqual(r['problems'], [])


HAVE_DISK = (RD.DOOM_TOOLS / 'build_disk.py').exists() and \
    (RC.RENDER / 'frame8-demo3.json').exists()
WHY_DISK = ('needs demos/doom/tools/build_disk.py, appletini-one\'s ProDOS '
            'and frame8.py\'s demo3 results (python3 tools/native/frame8.py '
            '--sets demo3 --json build/native/render/frame8-demo3.json)')


@needs_build
@unittest.skipUnless(HAVE_DISK, WHY_DISK)
class Disk(unittest.TestCase):
    """The disk image (acceptance 2) on the first 3 frames of its window,
    run on a2vm: chained, then full, every CRC the reference's."""

    @classmethod
    def setUpClass(cls):
        RC.make()
        window, _ = RD.choose(RD.FRAMES, None, RC.RENDER /
                              'frame8-demo3.json', blink.Symbols())
        cls.first = int(window[0].name.rsplit('-', 1)[1])

    def run_disk(self, obj: Path, t: Path):
        out = t / 'R.hdv'
        rj = t / 'r.json'
        code = RD.main(['--frames', '3', '--first', str(self.first),
                        '--no-build', '--obj', str(obj), '--out', str(out),
                        '--json', str(rj), '--check', '--profiles', 'f121'])
        return code, json.loads(rj.read_text())

    def test_three_frames_both_modes(self):
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            code, rep = self.run_disk(RC.OBJ, Path(t))
            self.assertEqual(code, 0)
            check = rep['checks'][0]
            self.assertTrue(check['statics']['ok'])
            for mode in ('chained', 'full'):
                self.assertEqual(check[mode]['ok'], 3, mode)
                self.assertGreater(check[mode]['vbls'], 0)

    def test_the_runner_one_byte_off(self):
        """The runner's aux 0 records (the screen and its patch) one byte
        off: the CRCs differ."""
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            obj = planted_obj(Path(t), (
                ('rrunner.s', '        bne     :+\n        lda     #0\n'
                 ':       sta     BANKSEL\n',
                 '        bne     :+\n        inc     rec_at\n'
                 '        lda     #0\n:       sta     BANKSEL\n'),))
            code, rep = self.run_disk(obj, Path(t))
            self.assertEqual(code, 1)
            check = rep['checks'][0] if rep['checks'] else None
            if check is not None:
                self.assertLess(check['chained']['ok'], 3)


if __name__ == '__main__':
    unittest.main()
