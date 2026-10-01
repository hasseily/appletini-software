"""Milestone 7, stage C: the whole native front end on a2vm against
upstream on ref816, from R_FillStamps to drawMasked (docs/RENDER.md 2.4,
4.3-4.5, 5.3: frame mode, acceptance 1).

A sample of checkpoint C: the build without warnings and within its
budgets; frame mode (tools/native/render_check.py --frame-mode: the
render window loaded by the phase loader, R_FillStamps, the setup and
clears, the weapon skip, the walk, the wall setup, the seg loops with the
sky and the patchless columns, every output of RENDER.md 2.4 at
drawMasked, no stray write, interrupts taken) on captured frames and on
synthetic ones (tools/native/framesynth.py: no weapon, the automap
overlay, the stamps' refresh, patchless columns, the sky under a fixed
colormap, a view angle not a multiple of 64 with sky walls), both
fills; the timing's phases; the milestone 5 replay on the native
records (tools/native/render_replay.py) giving ref816's screen.
Then that the checks fail: bugs planted in a scratch copy of the sources
(RENDER.md 4.5's list for stage C, and more).

What it needs, and skips without: cc65 (ca65, ld65) on PATH;
build/a2vm/a2vm (make -C tools/a2vm); build/linkmap.json; the frames of
python3 tools/native/rendercap.py and python3 tools/native/framesynth.py,
the tables of python3 tools/native/rtables.py; for the replay, the
captures of python3 tools/ref816/capture.py and the milestone 5 build
(make -C src/native).
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

from native import framestate as FS, loader, render_check as RC, \
    render_replay, rlayout as R  # noqa: E402
from bridge import linkmap as blink  # noqa: E402

ROOT = support.ROOT
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
FRAMES = RC.RENDER / 'frames'
CAPTURED = ('still-1', 'demo-10', 'tour-46', 'lights-08', 'title-14')
SYNTH = ('synth-noweapon', 'synth-shadow', 'synth-automap',
         'synth-fsfill', 'synth-fswrap', 'synth-flat', 'synth-flatv06',
         'synth-flatv14', 'synth-skyfixed', 'synth-skyodd')

HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
READY = (HAVE_CC65 and RC.A2VM.exists() and
         (BUILD / 'linkmap.json').exists() and
         (RC.TABLES / 'tables.img').exists() and
         all((FRAMES / f / 'frame.json').exists() for f in CAPTURED + SYNTH))
WHY = ('needs cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm), '
       'build/linkmap.json, the frames of python3 tools/native/rendercap.py '
       'and python3 tools/native/framesynth.py, the tables of python3 '
       'tools/native/rtables.py')
needs_build = unittest.skipUnless(READY, WHY)
REPLAY_READY = READY and (render_replay.CAPTURES / 'still-1' /
                          'manifest.json').exists() and \
    (loader.OBJ / 'test.lc').exists()
needs_replay = unittest.skipUnless(
    REPLAY_READY, WHY + ', the captures of python3 tools/ref816/capture.py '
    'and the milestone 5 build (make -C src/native)')

SOURCES = ('math.s', 'math.inc', 'rframe.s', 'rbsp.s', 'rlight.s',
           'auxlc.s', 'far.s', 'rdriver.s', 'rwall.s', 'rseg.s', 'rseg.inc',
           'rsky.s', 'rrec.s', 'render.cfg', 'render.mk',
           # milestone 8 (render.mk builds them too)
           'mmain.s', 'mproj.s', 'mfar.s', 'msprite.s', 'mvis.s',
           'mwall.s', 'bucket.s',
           'bdriver.s', 'bucket.cfg', 'wclip.s', 'wpsp.s', 'mpsp.s',
           'rrunner.s', 'replay.s')


def planted_build(tmp: Path, bugs) -> RC.Build:
    """The sources copied to tmp/src with each (file, old, new) applied
    once, built into tmp/obj; the whole front end (rwall)."""
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
    return RC.load_build(tmp / 'obj', 'rwall')


@needs_build
class FrameMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RC.make()
        cls.b = RC.load_build(RC.OBJ, 'rwall')
        cls.sym = blink.Symbols()
        cls.cases = {f: RC.prepare_full(FRAMES / f, cls.sym)
                     for f in CAPTURED + SYNTH}
        cls.bases = {f: RC.base_records(cls.b, f, window=True)
                     for f in RC.FILLS}

    def check(self, frame, b=None, fill=0xA5):
        b = b or self.b
        base = self.bases[fill] if b is self.b else \
            RC.base_records(b, fill, window=True)
        return RC.check_full(self.cases[frame], b, fill, base)

    def test_build_fits_its_budgets(self):
        s = self.b.segments
        self.assertLessEqual(RC.w_end(self.b), R.WCODE_END - 1)
        self.assertLessEqual(s['RLOAD'][1], R.FAR_CARD_END - 1)
        mods = RC.module_sizes(name='rwall')
        for key, (seg, budget) in RC.BUDGETS_B.items():
            used = sum(mods.get(m, {}).get(seg, 0) for m in key.split('+'))
            self.assertLessEqual(used, budget, key)
        self.assertLessEqual(sum(mods['far.o'].values()), RC.CARD_BUDGET)

    def test_frame_mode_on_a_sample(self):
        for frame in CAPTURED + SYNTH:
            for fill in RC.FILLS:
                with self.subTest(frame=frame, fill=fill):
                    r = self.check(frame, fill=fill)
                    self.assertEqual(r['problems'], [])
                    self.assertGreater(r['records'], 0)
                    self.assertGreater(r['irqs'], 0)
                    self.assertLessEqual(r['stack_bytes'] + R.IRQ_STACK,
                                         R.RENDER_STACK)
                    self.assertGreater(r['windows']['read'], 0)

    def test_the_sample_reaches_its_paths(self):
        """Each sampled frame takes the path it stands for (so the
        comparisons above are not vacuous)."""
        c = self.cases
        self.assertGreater(self.check('tour-46')['sky'], 0)
        self.assertGreater(self.check('synth-skyodd')['sky'], 0)
        view = FS.Frame(FRAMES / 'synth-skyodd').dump('p0b').u(
            self.sym.address('viewangle16'), 2)
        self.assertEqual(view & 0x3F, 0x3F)     # sky_col's carry reachable
        fixed = c['synth-skyfixed']
        pages = {r[8] for v in fixed.truth['records'].values() for r in v
                 if r[0] == 'tex' and r[7] in fixed.sky}
        self.assertEqual(pages, {0x47})          # the fixed colormap 1
        for name in ('synth-noweapon', 'synth-shadow', 'synth-automap'):
            t = c[name].truth
            self.assertEqual(t['wprev'][R.FV['PATCH']:R.FV['PATCH'] + 2],
                             [0xFF, 0xFF], name)
            self.assertEqual(t['fr_skip'], 0, name)
        self.assertEqual(c['still-1'].case.truth['bsp_entry']['fr_skip'], 1)
        self.assertEqual(c['synth-automap'].truth['w_botr'], 160)
        self.assertEqual(set(c['synth-fsfill'].case.truth['bsp_entry']
                             ['fs_stamps']), {0})
        flat = sum(1 for v in c['synth-flat'].truth['records'].values()
                   for r in v if r[0] == 'fill')
        plain = sum(1 for v in c['still-1'].truth['records'].values()
                    for r in v if r[0] == 'fill')
        self.assertGreater(flat, plain)

    def test_timing_by_phase(self):
        prof = RC.load_build(RC.OBJ, 'rwprof')
        t = RC.timing_full(self.cases['still-1'], prof,
                           RC.base_records(prof, 0xA5, window=True))
        for profile in ('f121', 'fastpath'):
            for phase in ('window', 'setup', 'walk', 'walls', 'segs'):
                self.assertGreater(t[profile][phase]['ms'], 0, phase)
                self.assertGreater(t[profile][phase]['cycles'], 0, phase)
        # the same code: the cycles do not depend on the firmware. The VBL
        # interrupt comes at a time, not a cycle, so under the two profiles
        # its handler can fall in neighbouring phases (milestone 8's page
        # model moved one from segs to walls under fastpath on still-1):
        # the phases' sum is equal, each phase within the handlers' cycles
        phases = list(RC.PHASES.values())
        self.assertEqual(t['f121']['irqs'], t['fastpath']['irqs'])
        self.assertEqual(sum(t['f121'][p]['cycles'] for p in phases),
                         sum(t['fastpath'][p]['cycles'] for p in phases))
        for p in phases:
            self.assertLessEqual(abs(t['f121'][p]['cycles'] -
                                     t['fastpath'][p]['cycles']),
                                 100 * t['f121']['irqs'], p)
        self.assertGreater(t['f121']['walk']['ms'],
                           t['fastpath']['walk']['ms'])


@needs_replay
class Replay(unittest.TestCase):
    """The milestone 5 replay on the native records: ref816's screen."""

    def test_replay_on_native_records(self):
        sym = blink.Symbols()
        RC.make()
        b = RC.load_build(RC.OBJ, 'rwall')
        bases = {0xA5: RC.base_records(b, 0xA5, window=True)}
        build = loader.read_build()
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            for name in ('still-1', 'demo-10'):
                r = render_replay.check_one(name, sym, b, bases, build,
                                            (0xA5,), Path(t))
                self.assertEqual(r['problems'], [], name)
                self.assertEqual(r['A5']['differing_bytes'], 0)
                self.assertGreater(r['records']['native'], 600)

    def test_a_wrong_slot_is_caught(self):
        """One texel of each native slot wrong: the pixels differ."""
        sym = blink.Symbols()
        RC.make()
        b = RC.load_build(RC.OBJ, 'rwall')
        bases = {0xA5: RC.base_records(b, 0xA5, window=True)}
        build = loader.read_build()
        real = render_replay.slot_memory

        def wrong(capture, level_dir, cols):
            real(capture, level_dir, cols)
            for col in cols:
                for r in col:
                    if r.origin >= render_replay.NATIVE_ORIGIN and \
                            r.kind == 0:
                        for k in range(128):
                            v = capture.memory.byte(r.texels + k)
                            capture.memory.put(r.texels + k,
                                               bytes([v ^ 0x11]))
        render_replay.slot_memory = wrong
        try:
            with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
                r = render_replay.check_one('still-1', sym, b, bases, build,
                                            (0xA5,), Path(t))
        finally:
            render_replay.slot_memory = real
        self.assertGreater(r['A5']['differing_bytes'], 0)


# bugs planted in a scratch copy (RENDER.md 4.5, stage C, and more): the
# name, the edits, the frames that show it, and the words of the problems
# that must catch it
BUGS = (
    ('fsFill at the wrong frame (every 64)', (
        ('rframe.s', '        bit #$7F\n', '        bit #$3F\n'),),
     ('tour-24',), ('fs_stamps', 'spans', 'records')),
    ('the first skipping frame\'s WCLIP copy missing', (
        ('rframe.s', '        lda T0                  ; the first frame that '
         'skips: WCLIP =\n        bne @done', '        lda T0                '
         '  ; the first frame that skips: WCLIP =\n        bra @done'),),
     ('still-1',), ('wclip',)),
    ('the sky column one texel column off', (
        ('rsky.s', '        rol a\n        lsr a                   ; its '
         'slot', '        rol a\n        inc a\n        lsr a              '
         '     ; its slot'),),
     ('tour-46',), ('records',)),
    ('the sky column one angle unit off (sec for clc, RENDER.md 4.5)', (
        ('rsky.s', 'sky_col:\n        clc ', 'sky_col:\n        sec '),),
     ('synth-skyodd',), ('records',)),
    ('the sky\'s page always colormap A\'s, not the fixed colormap\'s', (
        ('rsky.s', '        lda LT_FIXED+1          ;   A\'s full light\n',
         '        lda #0                  ;   A\'s full light\n'),),
     ('synth-skyfixed',), ('records',)),
    ('tierFlat writing DC_ROW (upstream runs it on the C direct page)', (
        ('rsky.s', '@flat:  pla\n        lda YL ', '@flat:  pla\n'
         '        lda YL\n        sta DCROW\n        lda YL '),),
     ('synth-flatv06', 'synth-flatv14'), ('ceilclip', 'records')),
    ('the flat colour\'s rows swapped (colormap B on the even rows)', (
        ('rsky.s', '        lda CMAPA0,y            ;   rows), B\'s (odd '
         'rows), full light\n        sta GT+2\n        lda CMAPB0,y\n',
         '        lda CMAPB0,y            ;   rows), B\'s (odd rows), full '
         'light\n        sta GT+2\n        lda CMAPA0,y\n'),),
     ('synth-flat', 'synth-flatv06', 'synth-flatv14'), ('records',)),
    ('a patchless column\'s bit read one column off', (
        ('rsky.s', '        lda GT+1                ; the bit of c\n',
         '        lda GT+1                ; the bit of c\n        inc a\n'),),
     ('synth-flat',), ('records', 'no slot')),
    ('the automap overlay ignored by the weapon skip', (
        ('rframe.s', '        cmp #3\n        beq @none\n',
         '        cmp #3\n        nop\n        nop\n'),),
     ('synth-automap',), ('fr_skip', 'wprev', 'w_wsk')),
    ('the shadow weapon not tested', (
        ('rframe.s', '        lda FRVIS+FV_PAGE       ; not the shadow weapon (no '
         'colormap)\n        beq @none\n',
         '        lda FRVIS+FV_PAGE\n        nop\n        nop\n'),),
     ('synth-shadow',), ('fr_skip', 'wprev', 'w_wsk')),
    ('no plane colours reset by R_FillStamps', (
        ('rframe.s', '        sta W_LCC+1             ;   colormaps can '
         'change between frames)\n', '        nop                     ;   '
         'colormaps can change between frames)\n        nop\n        nop\n'),),
     ('still-1', 'demo-10'), ('w_lcc', 'records', 'w_ceilw')),
    ('the last batch not flushed', (
        ('rframe.s', '        jmp rec_flush           ; the last batch',
         '        rts                     ; the last batch'),),
     ('still-1',), ('records',)),
    ('the phase loader one page of code short', (
        ('far.s', '__RENDERW_SIZE__ + $FF) >> 8) - WL_FIRST)',
         '__RENDERW_SIZE__ + $FF) >> 8) - WL_FIRST - 1)'),),
     ('still-1',), ('records', 'stopped', 'ended', 'differ')),
    ('the phase loader without the per-level tables', (
        ('far.s', '        .byte WTABLES_PAGE, WTABLES_PAGES, 0\n',
         '        .byte 0, 0, 0\n'),),
     ('still-1',), ('records', 'stopped', 'ended', 'no slot', 'differ')),
    ('a store into the hot game globals', (
        ('rsky.s', 'sky_col:\n        clc ', 'sky_col:\n        stz $1A80\n'
         '        clc '),),
     ('tour-46',), ('stray',)),
    ('a store into the phase loader\'s code in the card', (
        ('rframe.s', '        .import rec_start, rec_flush\n',
         '        .import rec_start, rec_flush, far_wload\n'),
        ('rframe.s', 'nr_frame:\n        MARK 2\n',
         'nr_frame:\n        lda #$EA\n        sta far_wload\n'
         '        MARK 2\n')),
     ('still-1',), ('stray',)),
)


@needs_build
class PlantedBugs(unittest.TestCase):
    """The checks fail on a wrong front end."""

    @classmethod
    def setUpClass(cls):
        cls.sym = blink.Symbols()
        cls.cases = {}

    def case(self, frame):
        if frame not in self.cases:
            self.cases[frame] = RC.prepare_full(FRAMES / frame, self.sym)
        return self.cases[frame]

    def test_bugs_are_caught(self):
        for name, edits, frames, caught in BUGS:
            with self.subTest(bug=name):
                with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
                    b = planted_build(Path(t), edits)
                    base = RC.base_records(b, 0xA5, window=True)
                    problems = []
                    for frame in frames:
                        r = RC.check_full(self.case(frame), b, 0xA5, base)
                        problems += r['problems']
                    self.assertTrue(problems, name)
                    self.assertTrue(any(any(w in p for w in caught)
                                        for p in problems), problems)


if __name__ == '__main__':
    unittest.main()
