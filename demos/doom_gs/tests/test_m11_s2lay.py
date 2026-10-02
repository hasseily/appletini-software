"""Milestone 11, first half, part s2lay (docs/SCREENS.md 4, 6.2-6.4, 7.3):
the layouts (tools/native/s2layout.py), the makefile (src/native/m11.mk,
m11/s2lay.mk), the test driver (src/native/s2_drv.s, its test image
s2_lt.s), the runner (tools/native/s2run.py) and the checker
(tools/native/s2check.py).

Without build/: s2layout.check() against rlayout.py, llayout.py and
glayout.py (imported: milestone 10's GS_STATUS and GS_ARG must not meet
the input block); every phase constant of the layouts and every phase the
sources write in 0-31, 31 only the platform's; the size check of a
synthetic map one byte over its room; s2check on a hand-made case and on
two hand-made write logs, one in upstream's publish order and one not;
the planted bugs of the layouts and the checker, each in a scratch copy.

With cc65, build/a2vm/a2vm and the math tables (python3 tools/native/
rtables.py): the s2lay build (no warning, the driver within its 600 B),
an empty call list from both poisoned machines writing nothing outside
the driver's and the phase loader's sets (the write log, and the whole
machine at the stop), the calls and their snapshots, a routine's stop,
the stub's VBL count under the IRQ contract, the cost phases; and the
planted driver writing one byte of aux 0, caught.

Run by name: python3 tools/testpar.py tests/test_m11_s2lay.py
"""

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

import support

from native import s2check as K, s2layout as S  # noqa: E402

ROOT = support.ROOT
BUILD = ROOT / 'build'
TOOLS = ROOT / 'tools' / 'native'
SRC = ROOT / 'src' / 'native'
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))


def ready() -> bool:
    from native import s2run
    return HAVE_CC65 and s2run.A2VM.exists() and \
        (s2run.TABLES / 'math' / 'squares.bin').exists()


READY = ready()
WHY = ('needs cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm) and the '
       'math tables (python3 tools/native/rtables.py)')
needs_build = unittest.skipUnless(READY, WHY)


PLANTED = [0]


def scratch_module(tmp: Path, name: str, bugs):
    """tools/native/NAME.py copied into tmp with each (old, new) applied
    once, imported under its own name (its imports are the tree's)."""
    text = (TOOLS / (name + '.py')).read_text()
    for old, new in bugs:
        if text.count(old) != 1:
            raise AssertionError('the bug no longer applies to %s: %r'
                                 % (name, old))
        text = text.replace(old, new)
    # (a name of its own each time: a cached bytecode of an earlier copy
    # of the same size and second must never be taken)
    PLANTED[0] += 1
    stem = 'planted_%s_%d' % (name, PLANTED[0])
    path = tmp / (stem + '.py')
    path.write_text(text)
    spec = importlib.util.spec_from_file_location(stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Hand-made cases
# ---------------------------------------------------------------------------

def screen_case(fill: int = 0xA5):
    """A status bar frame: the screen before (injected rows 0-99, the rest
    poison), the reference's after (the status bar rows changed, the first
    and the last row included), the native after equal."""
    before = bytearray([fill]) * K.SCREEN_SIZE
    for i in range(100 * S.ROW_BYTES):
        before[i] = (i * 7) & 0xFF
    ref = bytearray(before)
    for row in range(S.VIEWHEIGHT, S.ROWS):
        for b in range(0, S.ROW_BYTES, 3):
            at = row * S.ROW_BYTES + b
            ref[at] = (row + b) & 0xFF ^ 0x3C
    return bytes(before), bytes(ref), bytes(ref)


def write_log(black: bool, band_early: bool = False,
              picture_early: bool = False, scb_late: bool = False):
    """A frame's aux-0 stores: (black) the 512 palette bytes 0, newColors
    (SCBs, palettes), bands, the picture's colours."""
    stores = []
    if black:
        stores += [K.Store(S.PALETTES + i, 0) for i in range(512)]
    stores += [K.Store(S.SCB + r, 0x01) for r in range(S.VIEWHEIGHT,
                                                        S.ROWS)]
    stores += [K.Store(S.PALETTES + 32 * 3 + i, 0x11) for i in range(32)]
    bands = [K.Store(S.SHR + S.ROW_BYTES * S.VIEWHEIGHT + i, i & 0xFF)
             for i in range(400)]
    pictures = [K.Store(S.PALETTES + i, 0x22) for i in range(64)]
    stores += bands + pictures
    if band_early:              # one band store before the last black one
        stores.insert(300, bands[0])
    if picture_early:
        k = stores.index(pictures[0])
        stores.insert(k - 100, stores.pop(k))
    if scb_late:
        stores.append(K.Store(S.SCB + 3, 0x02))
    return stores


# ---------------------------------------------------------------------------
# Without build/
# ---------------------------------------------------------------------------

class Layout(unittest.TestCase):
    def test_check_passes_against_the_three_layouts(self):
        g = S.glayout_module()
        if (TOOLS / 'glayout.py').exists():
            self.assertIsNotNone(g)
            # milestone 10's stops: GS_STATUS a byte, GS_ARG a word
            stops = [r for r in g.regions() if r.space == 'main' and
                     r.start <= g.GS_ARG < r.end]
            self.assertTrue(stops)
            for r in stops:
                self.assertFalse(r.start < S.INPUT_END and
                                 S.INPUT_LO < r.end, r)
        self.assertEqual(S.problems_of(g), [])
        S.check(g)

    def test_input_block(self):
        self.assertEqual(S.PL_STATUS, 0x03AE)
        self.assertEqual(S.INPUT['PL_QUEUE'], S.INPUT_LO)
        self.assertEqual(S.INPUT['PL_QHEAD'] - S.INPUT['PL_QUEUE'], 45)
        used = max(S.INPUT[n] + k for n, k in S.INPUT_FIELDS)
        self.assertLessEqual(used, 0x03EE)      # PRND, MRND after it

    def test_phases(self):
        consts = dict(S.layout_phases([S]))
        self.assertEqual(consts['s2layout.PHASE_2D'], 30)
        self.assertEqual(consts['s2layout.PHASE_PLATFORM'], 31)
        found, unread = S.source_phases()
        self.assertEqual(unread, [])
        self.assertTrue(found)
        drv = [v for w, v in found if 'src/native/s2_drv.s' in w]
        self.assertEqual(sorted(set(drv)), [0, 30])
        self.assertTrue(all(0 <= v <= 31 for _, v in found))
        # 31 is the platform's input poll (4.8; request PLINPUT-7): only a
        # platform source writes it
        self.assertTrue(all(S.is_platform(w) for w, v in found if v == 31))
        self.assertEqual(S.phase_problems([S.R, S.LL, S]), [])

    def test_the_first_designs_three_code_banks_cannot_hold_six_images(self):
        # (request S2LAY-1, applied: every image's stored pages start at
        # $6600, so one image a bank, 95-97 added)
        with self.assertRaises(S.PackError) as cm:
            S.pack(S.budget_extents(), S.FIRST_CODE_BANKS)
        self.assertIn('WIW', str(cm.exception))
        banks = S.image_banks()
        self.assertEqual(banks['P2DW'], 107)
        self.assertEqual(banks['MENUW'], 108)
        self.assertEqual(len({banks[i.name] for i in S.IMAGES}), 7)

    def test_pack_shares_a_bank_between_disjoint_runs(self):
        got = S.pack({'P2DW': (0x6600, 0x7000), 'MENUW': (0x7000, 0x8000),
                      'AMAPW': (0x6F00, 0x7100)}, (1, 2))
        self.assertEqual(got, {'P2DW': 1, 'MENUW': 1, 'AMAPW': 2})
        with self.assertRaises(S.PackError):
            S.pack({'P2DW': (0x6600, 0x7000), 'MENUW': (0x6600, 0x6700)},
                   (1,))

    def test_size_check_rejects_one_byte_over_the_room(self):
        def map_text(end):
            return ('Modules list:\n-------------\ns2_lt.o:\n'
                    '    S2CODE            Offs=000000  Size=%06X  '
                    'Align=00001  Fill=0000\n\nSegment list:\n'
                    '-------------\nName                   Start     End'
                    '    Size  Align\n'
                    '----------------------------------------------------\n'
                    'S2CODE                006600  %06X  %06X  00001\n'
                    % (end - 0x6600, end - 1, end - 0x6600))
        for image in ('P2DW', 'MENUW', 'AMAPW', 'WIW', 'FINW', 'PALW'):
            lo, hi = S.IMAGE[image].stored
            rows, problems = S.check_map(image, map_text(hi))
            self.assertEqual(problems, [], image)
            rows, problems = S.check_map(image, map_text(hi + 1))
            self.assertEqual(len(problems), 1, image)
            self.assertIn('over its room', problems[0])
            self.assertIn('by 1 B', problems[0])

    def test_includes_of_each_build(self):
        for build, (s2t, sc, n) in {'test': (0xE443, 0xE8C0, 3),
                                    'release': (0xE443, 0xE8C0, 3),
                                    'm11': (0xEE00, 0xEE40, 3),
                                    'fxch8': (0xE443, 0xE000, 8)}.items():
            consts = dict(S.constants(build))
            self.assertEqual((consts['S2T_BASE'], consts['SC_BASE'],
                              consts['NUM_CHANNELS']), (s2t, sc, n), build)
            text = S.include_text(build)
            self.assertIn('PHV_2D          = $003C', text)
            # (wave 4: LS_ON, SND_SFXVOL after the mailboxes, FXCHAN-2)
            self.assertEqual(consts['LS_ON'], sc + n * 16, build)
            self.assertEqual(consts['SND_SFXVOL'], sc + n * 16 + 1, build)
        self.assertEqual(S.sc_size(8), 8 * 16 + 2)
        self.assertEqual(S.sc_size(3), 50)

    def test_s2inc_names_meet_no_other_include(self):
        import re
        from native import llayout as LL, rlayout as R
        mine = {n for n, _ in S.constants() + S.zeropage()}
        others = {n for n, _ in R.constants() + R.zeropage() +
                  LL.constants() + LL.zeropage() + LL.game_constants()}
        g = S.glayout_module()
        if g is not None:
            others |= {n for n, _ in g.constants() + g.zeropage()}
        others |= set(re.findall(r'^(\w+)\s*=', (SRC / 'math.inc')
                                 .read_text(), re.M))
        self.assertEqual(sorted(mine & others), [])

    def test_the_two_region_implementations_agree(self):
        for rg in S.REGIONS.values():
            self.assertEqual(rg.offsets(), K.offsets(rg), rg.name)
        self.assertEqual(len(K.offsets(S.REGIONS['stbar'])), 32 * 160)
        self.assertEqual(len(K.offsets(S.REGIONS['colors'])), 200 + 512)

    def test_field_map(self):
        screens = {f.screen for f in S.field_map()}
        self.assertEqual(screens, {'stbar', 'hud', 'palettes', 'menus',
                                   'automap', 'intermission', 'finale'})
        p2dw = S.state_places('P2DW')
        self.assertGreaterEqual(min(p2dw.values()), 0xBF00)
        cards = {f.place.partition('+')[0] for f in S.field_map()
                 if f.kind == 'card'}
        self.assertLessEqual(cards, set(S.S2T))
        if support.BUILD.joinpath('linkmap.json').exists():
            from bridge import linkmap
            self.assertEqual(S.linkmap_problems(linkmap.Symbols()), [])

    def test_compare_a_handmade_case(self):
        before, ref, after = screen_case()
        rg = S.REGIONS['stbar']
        r = K.compare(ref, before, after, rg)
        self.assertTrue(r.ok, r.problems())
        self.assertEqual(r.compared, 32 * 160)
        # a byte of the region wrong; a byte outside changed
        bad = bytearray(after)
        bad[199 * 160 + 3] ^= 1
        self.assertEqual(len(K.compare(ref, before, bytes(bad), rg).differ),
                         1)
        bad = bytearray(after)
        bad[167 * 160 + 3] ^= 1
        self.assertEqual(len(K.compare(ref, before, bytes(bad), rg)
                             .outside), 1)
        # both fills
        before5, ref5, after5 = screen_case(0x5A)
        self.assertTrue(K.compare(ref5, before5, after5, rg).ok)

    def test_exclusions_counted_and_named(self):
        before, ref, after = screen_case()
        view = bytearray(after)
        view[50 * 160] ^= 0xFF          # a view byte: excluded by X1
        rg = S.REGIONS['stbar']
        r = K.compare(ref, before, bytes(view), rg, [K.x1(0xFFFF)])
        self.assertTrue(r.ok)
        self.assertEqual(r.excluded['X1'], 168 * 160)
        r = K.compare(ref, before, bytes(view), rg, [K.x1(9)])
        self.assertEqual(r.excluded['X1'], 158 * 160)
        # X2: rows that must be black
        r = K.compare(ref, before, after, rg, [K.x2([(170, 171)])])
        self.assertEqual(r.excluded['X2'], 2 * 160)
        self.assertTrue(r.black)
        text = '\n'.join(K.report([('case', r)], x4=3))
        for name in ('X1', 'X2', 'X3', 'X4'):
            self.assertIn(name, text)
        self.assertIn('X4        3', text)

    def test_publish_order(self):
        self.assertEqual(K.order(write_log(True), True), [])
        self.assertEqual(K.order(write_log(False), False), [])
        bad = K.order(write_log(True, band_early=True), True)
        self.assertEqual(len(bad), 1)
        self.assertIn('before the last black palette store', bad[0])
        self.assertTrue(K.order(write_log(True, picture_early=True), True))
        self.assertTrue(K.order(write_log(False, scb_late=True), False))
        self.assertTrue(K.order(write_log(True)[1:], True))
        self.assertTrue(K.order([K.Store(0x9DFC, 0x53)], False))


class Planted(unittest.TestCase):
    """Each bug in a scratch copy, caught by the check named."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='tmp-m11-s2lay-',
                                         dir=str(BUILD) if BUILD.exists()
                                         else None))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def layout_problems(self, bugs):
        m = scratch_module(self.tmp, 's2layout', bugs)
        return m.problems_of(S.glayout_module(), ROOT)

    def test_two_regions_overlapping(self):
        p = self.layout_problems([(
            "'stbar': rows('stbar', 's2stbar', VIEWHEIGHT, ROWS - 1),",
            "'stbar': rows('stbar', 's2stbar', VIEWHEIGHT - 1, ROWS - 1),")])
        self.assertTrue(any('regions view' in x and 'stbar' in x and
                            'overlap' in x for x in p), p)

    def test_two_images_stored_over_each_other_in_one_bank(self):
        p = self.layout_problems([(
            """            if all(first + count <= f or f + c <= first
                   for f, c, _ in placed[b]):""",
            """            if True:  # (planted: the runs' overlap ignored)""")])
        self.assertTrue(any('bank 107: the stored pages of' in x and
                            'overlap' in x for x in p), p)

    def test_input_block_at_03b0(self):
        if not (TOOLS / 'glayout.py').exists():
            self.skipTest('no glayout.py')
        p = self.layout_problems([(
            'INPUT_LO, INPUT_END = 0x03B3, 0x03EE',
            'INPUT_LO, INPUT_END = 0x03B0, 0x03EB')])
        self.assertTrue(any('overlaps glayout the stop codes' in x
                            for x in p), p)

    def harness_root(self, text: str) -> Path:
        root = self.tmp / 'root'
        shutil.rmtree(str(root), ignore_errors=True)
        (root / 'src' / 'native').mkdir(parents=True)
        (root / 'src' / 'native' / 'x.s').write_text(text)
        return root

    def test_phase_31_outside_the_platform(self):
        # milestone 10's test-build harness may time itself in 30 and 31
        # (wave 4 as integrated); the game's code may not write 31
        game = '        lda #62\n        sta PHASE\n'
        p = S.phase_problems([S], self.harness_root(game))
        self.assertTrue(any('x.s:2 writes the phase 31' in x for x in p), p)
        for text in ('.ifdef TESTBUILD\n' + game + '.endif\n',
                     '.if .defined(TESTBUILD)\n' + game + '.endif\n',
                     '.ifndef TESTBUILD\n.else\n' + game + '.endif\n'):
            root = self.harness_root(text)
            self.assertEqual(S.phase_problems([S], root), [], text)
            found, unread = S.source_phases(root, harness=True)
            at = 'src/native/x.s:%d' % (text.count('\n') - 1)
            self.assertEqual((found, unread), ([(at, 31)], []), text)
            self.assertEqual(S.source_phases(root), ([], []))
        for text in ('.ifndef TESTBUILD\n' + game + '.endif\n',
                     '.ifdef TESTBUILD\n.else\n' + game + '.endif\n',
                     '.ifdef OTHER\n' + game + '.endif\n'):
            root = self.harness_root(text)
            p = S.phase_problems([S], root)
            self.assertTrue(any('writes the phase 31' in x for x in p),
                            (text, p))
        # a harness's phase is still 0-31 and readable
        root = self.harness_root('.ifdef TESTBUILD\n        lda #64\n'
                                 '        sta PHASE\n        lda Q\n'
                                 '        sta PHASE\n.endif\n')
        p = S.phase_problems([S], root)
        self.assertTrue(any('harness) writes the phase 32' in x for x in p),
                        p)
        self.assertTrue(any('harness) writes PHASE with a value' in x
                            for x in p), p)

    def test_phase_constant_32(self):
        p = self.layout_problems([('PHASE_2D = 30 ', 'PHASE_2D = 32 ')])
        self.assertTrue(any('PHASE_2D is 32, outside 0-31' in x
                            for x in p), p)
        # (and the driver's store of it, read from the source)
        self.assertTrue(any('s2_drv.s' in x and 'phase 32' in x
                            for x in p), p)

    def test_region_off_by_one_row_in_s2check(self):
        k = scratch_module(self.tmp, 's2check', [(
            '        for row in range(r0, r1 + 1):',
            '        for row in range(r0, r1):')])
        before, ref, after = screen_case()
        r = k.compare(ref, before, after, S.REGIONS['stbar'])
        self.assertFalse(r.ok)
        self.assertTrue(r.outside)      # row 199 seen as outside

    def test_band_store_before_the_last_black_passing(self):
        k = scratch_module(self.tmp, 's2check', [(
            """            if kind(s.offset) != 'palette' or s.value != 0:
                out.append""",
            """            if kind(s.offset) != 'palette' or s.value != 0:
                k += 1
                continue
                out.append""")])
        log = write_log(True, band_early=True)
        self.assertEqual(k.order(log, True), [])    # the planted judge
        self.assertNotEqual(K.order(log, True), [])     # the real one


# ---------------------------------------------------------------------------
# With the build: the driver on a2vm
# ---------------------------------------------------------------------------

@needs_build
class Driver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from native import s2run as SR
        cls.SR = SR
        SR.make()
        cls.b = SR.load_build(SR.S2LAY, 's2lt', 'P2DW')

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='tmp-m11-s2lay-',
                                         dir=str(BUILD)))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def owners(self, r, extra=()):
        SR = self.SR
        return [SR.driver_owner(r.build), SR.loader_owner(r.build, r.loads)
                ] + list(extra)

    def test_sizes(self):
        lo, hi = self.b.segments['DRIVER']
        self.assertLessEqual(hi + 1 - lo, S.DRV_CODE_BUDGET)
        d = self.b.segments['DESC']
        self.assertTrue(S.DRV[0] <= lo and d[1] < S.DRV[1])
        sizes = (self.SR.S2LAY / 's2lt.sizes').read_text()
        self.assertIn('room', sizes)
        rows, problems = S.check_map('P2DW', (self.SR.S2LAY /
                                              's2lt.map').read_text())
        self.assertEqual(problems, [])

    def test_empty_list_from_both_poisoned_machines(self):
        SR = self.SR
        for fill in S2_FILLS:
            work = self.tmp / ('%02x' % fill)
            r = SR.run(self.b, [], fill, work, whole=True)
            self.assertEqual(r.ended(), 'stop')
            self.assertEqual(r.status(), S.S2S['DONE'])
            n, shown = SR.stray(r.writes(), self.owners(r))
            self.assertEqual(n, 0, shown)
            before = SR.Machine.of(r.records)
            after = SR.read_snapshot(work / 'stop.img')
            n, shown = SR.changed_outside(before, after, self.owners(r))
            self.assertEqual(n, 0, shown)
            # the image is in W after the load
            img = SR.area_bytes(self.b, 'IMG')
            self.assertEqual(bytes(after.main[0x6600:0x6600 + len(img)]),
                             img)
            shutil.rmtree(str(work))

    def test_calls_snapshots_and_a_stop(self):
        SR = self.SR
        calls = [SR.Call('s2t_echo', 1, 2, 3), SR.Call('s2t_nop'),
                 SR.Call('s2t_echo', 0xFE, 0x80, 0x7F),
                 SR.Call('s2t_stop', 0x7E)]
        r = SR.run(self.b, calls, 0x5A, self.tmp / 'r',
                   snap_ranges='main:BF00-BFFF')
        self.assertEqual(r.ended(), 'stop')
        self.assertEqual(r.status(), 0x7E)
        snaps = r.calls()
        self.assertEqual(len(snaps), 3)     # the stop's call never returns
        self.assertEqual(bytes(snaps[0].main[0xBFFD:0xC000]), b'\x01\x02\x03')
        self.assertEqual(bytes(snaps[1].main[0xBFFD:0xC000]), b'\x01\x02\x03')
        self.assertEqual(bytes(snaps[2].main[0xBFFD:0xC000]), b'\xfe\x80\x7f')
        img = SR.Owner('image', tuple(self.b.segments[s] for s in
                                      S.IMG_SEGMENTS
                                      if s in self.b.segments),
                       (('main', 0, 0xBFFD, 0xC000),
                        ('main', 0, S.PL_STATUS, S.PL_STATUS + 1)),
                       frozenset())
        n, shown = SR.stray(r.writes(), self.owners(r, [img]))
        self.assertEqual(n, 0, shown)
        # without the image's set, its writes are strays
        n, _ = SR.stray(r.writes(), self.owners(r))
        self.assertEqual(n, 7)

    def test_vbl_stub_under_the_irq_contract(self):
        SR = self.SR
        r = SR.run(self.b, [SR.Call('s2t_wait', 5)], 0xA5, self.tmp / 'r',
                   ay_log=True)
        self.assertEqual(r.ended(), 'stop')     # (the bounds held)
        self.assertEqual(r.status(), S.S2S['DONE'])
        self.assertGreaterEqual(r.state.get('irqs', 0), 5)
        self.assertEqual(len(SR.irq_lengths(r)), r.state['irqs'])
        depth = SR.stack_depth(r)
        self.assertIsNotNone(depth)
        self.assertLessEqual(depth + S.IRQ_STACK, S.STACK_2D + S.IRQ_STACK)

    def test_cost_phases(self):
        SR = self.SR
        for profile in ('f121', 'fastpath'):
            r = SR.run(self.b, [SR.Call('s2t_wait', 2)], 0xA5,
                       self.tmp / profile, profile=profile, write_log=False)
            self.assertEqual(r.ended(), 'stop')
            ms = SR.phase_ms(r, profile)
            # (two VBLs: at least one whole PAL frame, 20 ms)
            self.assertGreater(ms.get(S.PHASE_2D, 0), 20.0, ms)
            self.assertGreater(ms.get(S.PHASE_DRIVER, 0), 0, ms)
            self.assertNotIn(S.PHASE_PLATFORM, ms)

    def test_planted_driver_writing_aux_0(self):
        SR = self.SR
        src = self.tmp / 'src'
        (src / 'm11').mkdir(parents=True)
        shutil.copy(str(SRC / 'm11.mk'), str(src / 'm11.mk'))
        shutil.copy(str(SRC / 'm11' / 's2lay.mk'), str(src / 'm11'))
        text = (SRC / 's2_drv.s').read_text()
        old = '        sta INTCXROMOFF         ; (slot 7'
        self.assertEqual(text.count(old), 1)
        (src / 's2_drv.s').write_text(text.replace(old, (
            '        sta RAMWRTON            ; (planted: aux 0 $2000)\n'
            '        sta $2000\n'
            '        sta RAMWRTOFF\n') + old))
        SR.make(m11=self.tmp / 'm11', source=src)
        b = SR.load_build(self.tmp / 'm11' / 's2lay', 's2lt', 'P2DW')
        r = SR.run(b, [], 0xA5, self.tmp / 'r', whole=True)
        self.assertEqual(r.ended(), 'stop')
        n, shown = SR.stray(r.writes(), self.owners(r))
        self.assertGreaterEqual(n, 1)
        self.assertTrue(any('aux 0 $2000' in s for s in shown), shown)
        before = SR.Machine.of(r.records)
        after = SR.read_snapshot(self.tmp / 'r' / 'stop.img')
        n, shown = SR.changed_outside(before, after, self.owners(r))
        self.assertEqual(n, 1, shown)


S2_FILLS = (0xA5, 0x5A)


if __name__ == '__main__':
    unittest.main()
