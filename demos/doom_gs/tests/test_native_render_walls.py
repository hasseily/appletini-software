"""Milestone 7, stage B: the native wall setup and seg loops on a2vm
against upstream's R_StoreWallRange and R_RenderSegLoop on ref816
(docs/RENDER.md 4.3, 4.5, 5.2: routine mode, acceptance 2; since stage C
with the sky, which stage B deferred).

A sample of checkpoint B: the build without warnings and within its
budgets; routine mode (tools/native/render_check.py --routines) on 20
captured calls of each routine spread over the captures, and on every
synthetic case (tools/native/routinesynth.py: the paths no capture
reaches), both fills, every output equal, no stray write, interrupts
taken inside; the rules of our own (RENDER.md 3.9) on the synthetic
cases where upstream leaves its tables, compared wherever it stays in
them; the generated loops (tools/native/seggen.py) against their
kinds. Then that the checks fail: bugs planted in a scratch copy of the
sources (RENDER.md 4.5's list for stage B, and more).

What it needs, and skips without: cc65 (ca65, ld65) on PATH;
build/a2vm/a2vm (make -C tools/a2vm); build/linkmap.json; the frames of
python3 tools/native/rendercap.py, the routine cases of python3
tools/native/routinecap.py and python3 tools/native/routinesynth.py, the
tables of python3 tools/native/rtables.py.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

from native import render_check as RC, rlayout as R, seggen  # noqa: E402
from bridge import linkmap as blink  # noqa: E402

ROOT = support.ROOT
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
ROUTINES = RC.ROUTINES
SYNTH = ('edgeslow', 'mod16', 'mod16neg', 'vmask', 'closed', 'onecolslow',
         'dsfull', 'openfull', 'fsgeneral', 'segearly')
RULED = ('negsine', 'grazefirst', 'grazelast')
SAMPLE_SIZE = 20

HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
READY = (HAVE_CC65 and RC.A2VM.exists() and
         (BUILD / 'linkmap.json').exists() and
         (RC.TABLES / 'tables.img').exists() and
         (ROUTINES / 'index.json').exists() and
         all((ROUTINES / ('synth-' + s) / 'w00.case.z').exists()
             for s in SYNTH + RULED))
WHY = ('needs cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm), '
       'build/linkmap.json, the captures of python3 tools/native/'
       'rendercap.py, python3 tools/native/routinecap.py and python3 '
       'tools/native/routinesynth.py, the tables of python3 tools/native/'
       'rtables.py')
needs_build = unittest.skipUnless(READY, WHY)

SOURCES = ('math.s', 'math.inc', 'rframe.s', 'rbsp.s', 'rlight.s',
           'auxlc.s', 'far.s', 'rdriver.s', 'rwall.s', 'rseg.s', 'rseg.inc',
           'rsky.s', 'rrec.s', 'render.cfg', 'render.mk',
           # milestone 8 (render.mk builds them too)
           'mmain.s', 'mproj.s', 'mfar.s', 'msprite.s', 'mvis.s',
           'mwall.s', 'bucket.s',
           'bdriver.s', 'bucket.cfg', 'wclip.s', 'wpsp.s', 'mpsp.s',
           'rrunner.s', 'replay.s')


def sample_cases():
    """SAMPLE_SIZE captured calls evenly over those without a sky (stage
    B's sample; the sky is test_sky_columns_are_equal's), and the
    synthetic cases."""
    walls = [w for w in RC.walls_index() if 'skyColumn' not in w['paths']]
    n = len(walls)
    picked = [walls[round(i * (n - 1) / (SAMPLE_SIZE - 1))]
              for i in range(SAMPLE_SIZE)]
    paths = [ROUTINES / w['frame'] / ('w%02d.case.z' % w['k'])
             for w in picked]
    return paths + [ROUTINES / ('synth-' + s) / 'w00.case.z' for s in SYNTH]


def planted_build(tmp: Path, bugs) -> RC.Build:
    """The sources copied to tmp/src with each (file, old, new) applied
    once, built into tmp/obj; the stage B build (rwall)."""
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


class Loops(unittest.TestCase):
    """The generator: 13 loops, each named after upstream's kind."""

    def test_the_kinds(self):
        numbers = sorted(k.number for k in seggen.KINDS)
        self.assertEqual(numbers, [2, 4, 5, 6, 7, 8, 10, 12, 13, 14, 15, 20,
                                   28])
        text = seggen.source()
        for k in seggen.KINDS:
            self.assertIn('\n%s:\n' % k.name, text)
            # a loop steps only the edges it uses (segvar.inc)
            body = text.split('\n%s:\n' % k.name)[1].split('jmp segdone')[0]
            self.assertEqual('STEP8E TF, TS' in body,
                             k.mc or k.top or k.one, k.name)
            self.assertEqual('STEP8E BF, BS' in body,
                             k.mf or k.bot or k.one, k.name)
            self.assertEqual('STEP8E PH, PHS' in body, k.top, k.name)
            self.assertEqual('STEP8E PL, PLS' in body, k.bot, k.name)
            self.assertEqual('jsr ceilfill' in body, k.mc, k.name)
            self.assertEqual('jsr floorfill' in body, k.mf, k.name)


@needs_build
class Walls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RC.make()
        cls.b = RC.load_build(RC.OBJ, 'rwall')
        cls.sym = blink.Symbols()
        cls.bases = {f: RC.base_records(cls.b, f) for f in RC.FILLS}

    def run_case(self, path: Path, kind: str, b=None, fill=0xA5):
        b = b or self.b
        rt = RC.prepare_routine(path, kind, self.sym)
        base = self.bases[fill] if b is self.b else RC.base_records(b, fill)
        return RC.check_routine(rt, b, fill, base)

    def test_build_fits_its_budgets(self):
        s = self.b.segments
        self.assertLessEqual(RC.w_end(self.b), R.WCODE_END - 1)
        self.assertLessEqual(s['RFAR'][1], R.FAR_CARD_END - 1)
        mods = RC.module_sizes(name='rwall')
        for key, (seg, budget) in RC.BUDGETS_B.items():
            used = sum(mods.get(m, {}).get(seg, 0) for m in key.split('+'))
            self.assertLessEqual(used, budget, key)

    def test_routine_mode_on_a_sample(self):
        irqs = 0
        for path in sample_cases():
            loaded = RC.RCP.load_case(path)
            for kind, first in (('wall', 'SWE'), ('seg', 'SLE')):
                if first not in loaded.points:
                    continue
                for fill in RC.FILLS:
                    with self.subTest(case=RC.case_name(path), kind=kind,
                                      fill=fill):
                        r = self.run_case(path, kind, fill=fill)
                        self.assertEqual(r['problems'], [])
                        self.assertLessEqual(r['stack_bytes'] + R.IRQ_STACK,
                                             R.RENDER_STACK)
                        irqs += bool(r['irqs'])
        self.assertGreater(irqs, 10)

    def test_the_rules_of_our_own(self):
        """A column seen from behind (RENDER.md 3.9): upstream's sineLow
        reads its own code and tcExact reads past finetangent; the native
        code runs to the end with its rules (the scale 256, the tangent
        table's end), says so in RULES, and equals upstream wherever
        upstream stays in its tables (render_check.ruled_diff). The whole
        wall behind (negsine), and only its first or last column
        (grazefirst, grazelast: both rules, both branches of the tangent
        rule); negsine's seg loop, untextured, needs no rule."""
        seen = 0
        for spec in RULED:
            path = ROUTINES / ('synth-' + spec) / 'w00.case.z'
            for kind in ('wall', 'seg'):
                for fill in RC.FILLS:
                    with self.subTest(case=spec, kind=kind, fill=fill):
                        r = self.run_case(path, kind, fill=fill)
                        want = RC.RULED[spec].get(kind)
                        if want is None:
                            self.assertEqual(r['problems'], [])
                            self.assertEqual(r['rules'], 0)
                            continue
                        self.assertEqual(r['rules'], want[0])
                        self.assertEqual(RC.ruled_ok(spec, r), [])
                        self.assertTrue(any('rules %d:' % want[0] in p
                                            for p in r['problems']))
                        seen |= r['rules']
        self.assertEqual(seen, R.RULE_SINE | R.RULE_TANGENT)

    def test_sky_columns_are_equal(self):
        """The calls that draw a sky column (stage B deferred them; stage
        C's rsky.s draws them): four spread over the captures, both
        routines, both fills."""
        walls = [w for w in RC.walls_index() if 'skyColumn' in w['paths']]
        n = len(walls)
        self.assertGreater(n, 40)
        for w in (walls[round(i * (n - 1) / 3)] for i in range(4)):
            path = ROUTINES / w['frame'] / ('w%02d.case.z' % w['k'])
            for kind in ('wall', 'seg'):
                for fill in RC.FILLS:
                    with self.subTest(case=RC.case_name(path), kind=kind,
                                      fill=fill):
                        r = self.run_case(path, kind, fill=fill)
                        self.assertEqual(r['problems'], [])
                        self.assertGreater(r['records'], 0)


def cases_with(kind: str, has=(), lacks=('skyColumn',), count: int = 4):
    """`count` captured calls (kind, FRAME/wKK) spread over the captures
    whose paths (routinecap.PATHS) include `has` and exclude `lacks`."""
    walls = [w for w in RC.walls_index()
             if all(p in w['paths'] for p in has) and
             not any(p in w['paths'] for p in lacks)]
    n = len(walls)
    if n == 0:
        raise AssertionError('no captured call with %s' % (has,))
    picked = [walls[round(i * (n - 1) / max(1, count - 1))]
              for i in range(min(count, n))]
    return tuple((kind, '%s/w%02d' % (w['frame'], w['k'])) for w in picked)


# bugs planted in a scratch copy: the name, the edits, the cases (kind,
# case, a function of RC.walls_index for the captured ones) that show it,
# and the words of the problem that must catch it
BUGS = (
    ('qmulh without its carry', (
        ('math.s', '        adc MT+1\n        lda M_R+2\n',
         '        adc MT+1\n        clc\n        lda M_R+2\n'),),
     lambda: cases_with('wall', ('scaleFast',), count=40),
     ('drawseg', 'records', 'rw_step')),
    ('STEP8E stepping all four bytes', (
        ('rseg.inc', '.macro STEP8E v, s\n        clc\n        lda v+1\n',
         '.macro STEP8E v, s\n        clc\n        lda v\n        adc s\n'
         '        sta v\n        lda v+1\n'),),
     lambda: cases_with('seg', count=12), ('records', 'clip', 'spans')),
    ('W_FSP compared where W_FSC is due', (
        ('rseg.s', '        lda FSSTT,x             ; the frame before\'s, '
         'with the same bytes?\n        cmp W_FSP\n',
         '        lda FSSTT,x             ; the frame before\'s, with the '
         'same bytes?\n        cmp W_FSC\n'),),
     lambda: tuple(('seg', 'still-2/w%02d' % k) for k in range(0, 34, 3)),
     ('spans', 'records')),
    ('W_LV not set for a seg of one light (upstream\'s C26 base kept)', (
        ('rseg.s', ':       stz WLV\n        lda LT_FIXED+1\n',
         ':       lda LT_FIXED+1\n'),),
     lambda: cases_with('seg', ('tcExact',), ('skyColumn', 'c26LightSetup')),
     ('records',)),
    ('saveClip one column short', (
        ('rwall.s', 'saveceil:\n        jsr saveat\n        sta DSBUF+'
         'DS_TOPCLIP\n        stx DSBUF+DS_TOPCLIP+1\n        sta RAMWRTON\n'
         '        ldy SW_START\n',
         'saveceil:\n        jsr saveat\n        sta DSBUF+DS_TOPCLIP\n'
         '        stx DSBUF+DS_TOPCLIP+1\n        sta RAMWRTON\n'
         '        ldy SW_START\n        iny\n'),),
     lambda: (('wall', 'still-1/w00'),), ('openings',)),
    ('the fill bytes of an odd first row not swapped', (
        ('rseg.s', '        lda GT\n        lsr a\n        bcs @odd\n',
         '        lda GT\n        lsr a\n        bra @odd\n'),),
     lambda: (('seg', 'still-1/w00'),), ('records',)),
    ('the texture u exact every 4 columns, not 8', (
        ('rseg.s', '        adc #8\n        ldy #3\n',
         '        adc #4\n        ldy #2\n'),),
     lambda: cases_with('seg', ('tcExact',)), ('records',)),
    ('the line not mapped', (
        ('rwall.s', '        ora BITS,x\n', '        eor BITS,x\n'),),
     lambda: (('wall', 'still-1/w00'), ('wall', 'demo-05/w00')),
     ('mapped', 'lnmap')),
    ('rw_scalestep of one column of scaleSlow set to 0', (
        ('rwall.s', '        MOV32 SD_SCALE, SD_SCALE2\n        rts\n:       '
         'txa\n', '        MOV32 SD_SCALE, SD_SCALE2\n        stz RW_STEP\n'
         '        rts\n:       txa\n'),),
     lambda: (('wall', 'synth-onecolslow/w00'),), ('records', 'rw_step')),
    ('edgeSlow with the step and the scale swapped', (
        ('rwall.s', '@slow:  MOV32 SW_Q, M_A\n        MOV32 SD_SCALE, M_B\n',
         '@slow:  MOV32 SW_Q, M_A\n        MOV32 RW_STEP, M_B\n'),),
     lambda: (('wall', 'synth-edgeslow/w00'),), ('records', 'clip')),
    ('rowMod\'s negative remainder not corrected', (
        ('rwall.s', '        sta SW_T+1\n        bpl :+\n        clc\n',
         '        sta SW_T+1\n        bra :+\n        clc\n'),),
     lambda: (('wall', 'synth-mod16neg/w00'),), ('records',)),
    ('a column closed by the loop without genColumn', (
        ('seggen.py', "    op('jsr gencol', 'closed: genColumn')\n",
         "    op('nop', 'closed: genColumn')\n"),),
     lambda: (('seg', 'synth-closed/w00'),),
     ('records', 'clip', 'solidcol')),
    ('fsGeneral shifted one too few', (
        ('rseg.s', '        lda #22                 ; >> 22 - s (s = 8 or 9 '
         'here)\n', '        lda #21                 ; >> 22 - s (s = 8 or 9 '
         'here)\n'),),
     lambda: (('seg', 'synth-fsgeneral/w00'),), ('records',)),
    ('a store into the hot game globals', (
        ('rwall.s', 'nr_storewall:\n        sta SW_START\n',
         'nr_storewall:\n        stz $1A80\n        sta SW_START\n'),),
     lambda: (('wall', 'still-1/w00'),), ('stray',)),
    ('RULE_SINE\'s scale 512, not 256', (
        ('rwall.s', '        jmp @256                ; the scale 256\n',
         '        stz M_R\n        lda #2\n        sta M_R+1\n'
         '        stz M_R+2\n        stz M_R+3\n        rts\n'),),
     lambda: (('wall', 'synth-grazefirst/w00'),
              ('wall', 'synth-grazelast/w00')), ('drawseg', 'rw_step')),
    ('RULE_SINE not flagged in RULES', (
        ('rwall.s', '        lda #RULE_SINE\n        tsb RULES\n', ''),),
     lambda: (('wall', 'synth-negsine/w00'),), ('rules',)),
    ('RULE_TANGENT not flagged in RULES', (
        ('rseg.s', '        lda #RULE_TANGENT\n        tsb RULES\n', ''),),
     lambda: (('seg', 'synth-grazelast/w00'),), ('rules',)),
    ('RULE_TANGENT taken below 4096 too (every texture angle of part 4 '
     'the table\'s end)', (
        ('rseg.s', '        cmp #>1024\n        bcs @past\n',
         '        cmp #>0\n        bcs @past\n'),),
     lambda: (('seg', 'synth-grazelast/w00'),) +
     cases_with('seg', ('tcExact',), count=4), ('records', 'rules')),
)


@needs_build
class PlantedBugs(unittest.TestCase):
    """The checks fail on a wrong wall setup or seg loop."""

    @classmethod
    def setUpClass(cls):
        cls.sym = blink.Symbols()

    def test_bugs_are_caught(self):
        for name, edits, cases_of, caught in BUGS:
            cases = cases_of()
            with self.subTest(bug=name):
                with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
                    tmp = Path(t)
                    seg_bug = [e for e in edits if e[0] == 'seggen.py']
                    b = self.build(tmp, edits, seg_bug)
                    problems = []
                    for kind, case in cases:
                        path = RC.routine_cases(case)[0]
                        rt = RC.prepare_routine(path, kind, self.sym)
                        r = RC.check_routine(rt, b, 0xA5,
                                             RC.base_records(b, 0xA5))
                        spec = RC.spec_of(rt.name)
                        if kind in RC.RULED.get(spec or '', {}):
                            problems += RC.ruled_ok(spec, r)
                        else:
                            problems += r['problems']
                    self.assertTrue(problems, name)
                    self.assertTrue(any(any(w in p for w in caught)
                                        for p in problems), problems)

    def build(self, tmp: Path, edits, seg_bug) -> RC.Build:
        if not seg_bug:
            return planted_build(tmp, edits)
        # a bug of the generator: its copy writes the build's loops
        gen = tmp / 'seggen.py'
        text = (ROOT / 'tools' / 'native' / 'seggen.py').read_text()
        for name, old, new in seg_bug:
            if text.count(old) != 1:
                raise AssertionError('the bug no longer applies: %r' % old)
            text = text.replace(old, new)
        gen.write_text(text)
        src = tmp / 'src'
        src.mkdir()
        for f in SOURCES:
            shutil.copy(str(SRC / f), str(src / f))
        RC.make(tmp / 'obj', src, ['SEGGEN=%s' % gen])
        return RC.load_build(tmp / 'obj', 'rwall')

if __name__ == '__main__':
    unittest.main()
