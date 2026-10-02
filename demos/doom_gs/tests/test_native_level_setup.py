"""Milestone 9, stage C: the native P_SetupLevel and the zone (docs/LEVELS.md
6.3; src/native/lsetup.s, gthink.s, gpos.s, gspawn.s, gweap.s, gspec.s,
gvalid.s; tools/native/setupcheck.py, level_check.py --setup --flood
--setup-timing --report-md, ldisk.py; the bridge's handle, sxbyte and bit
encodings).

Without build/: the three encodings and the manifest's new forms on a
hand-made layout (round trip and refusals); the game layout's places (the
special ranges, the mobj groups, the globals block, the zero page, the
include's names); the flood depth on hand-made graphs; the wrap fix's
renumbering on a hand-made state.

With cc65, a2vm, the store (python3 tools/native/wadconv.py --store), the
setup captures (python3 tools/native/setupcap.py) and the math tables
(python3 tools/native/rtables.py): acceptance 1 on a sample (E1M1 and
E1M7 at skills 2 and 4, a reload of E1M1 after its first load: canonical
state equal to ref816's, no stray write, the stack within 128 B, the
reload's static kinds equal to the first load's); the validcount wrap fix
(the lockstep build equal to the wrap capture, the release build to the
plain setup renumbered); the flood bound (acceptance 3) from the machines
of the nine skill-2 setups, and that it fails against a small stack; the
boot disk (with appletini-one's ProDOS: one map's setup, its CRCs). Then
bugs planted in scratch copies of the sources (docs/LEVELS.md 5.7, stage
C's), each caught by the check named; the block walk with y outer by the
synthetic setup secorder (no captured E1 setup can see it), G_PlayerReborn
without its clear by the capture reborn-kit (docs/LEVELS.md "Verification
of stage C").
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts tools/ on the path)

from bridge import canonical  # noqa: E402
from bridge.fields import R as Ref  # noqa: E402
from bridge.layout import FORMAT, Manifest  # noqa: E402
from bridge.memory import port_text  # noqa: E402
from bridge.port import PortError, PortReader, PortWriter  # noqa: E402
from native import llayout as LL, rlayout as R  # noqa: E402

ROOT = support.ROOT
BUILD = ROOT / 'build'

# acceptance 1's sample (docs/LEVELS.md 5.7): E1M1 and E1M7 at skills 2
# and 4, and E1M1's reload after its first load
SAMPLE = ('tour-sk2-01', 'tour-sk2-08', 'tour-sk4-01', 'tour-sk4-08',
          'reborn-e1m1-01', 'reborn-e1m1-02')


def ready():
    try:
        import test_native_level_load as TL
        from native import setupcap
    except ImportError:             # pragma: no cover
        return False
    if not TL.READY:
        return False
    names = {d.name for d in setupcap.setup_dirs()}
    return all(n in names for n in SAMPLE)


READY = ready()
WHY = ('needs cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm), the store '
       '(python3 tools/native/wadconv.py --store), the setup captures '
       '(python3 tools/native/setupcap.py, with the tour, reborn and wrap '
       'runs), their levels (python3 tools/native/level_check.py --conv), '
       'the math tables (python3 tools/native/rtables.py)')
needs_build = unittest.skipUnless(READY, WHY)


# ---------------------------------------------------------------------------
# The encodings (tools/bridge/layout.py, port.py)
# ---------------------------------------------------------------------------

def small_manifest():
    """A hand-made layout with the native game's forms: kind "m" of a
    constant count with a handle (two ranges: m and s's field "x", and a
    byte-offset range), a signed byte, a bit, a sequence of "end" form in
    a pool of one-byte handles and the links of list L as handles; kind
    "s" of 2; the head of L a list leaf with handle ranges."""
    at = [0x400200]

    def planes(n, cap):
        out = []
        for _ in range(n):
            out.append(port_text(at[0]))
            at[0] += cap
        return out

    h2 = {'enc': 'handle', 'bytes': 2, 'ranges': [
        {'lo': 0, 'n': 4, 'kind': 'm'},
        {'lo': 0x800, 'n': 2, 'kind': 's', 'field': 'x'},
        {'lo': 0x1000, 'n': 16, 'kind': 'blob', 'id': 0}]}
    ml = {'enc': 'handle', 'bytes': 2, 'ranges': [
        {'lo': 0, 'n': 4, 'kind': 'm'}]}
    leaves = [
        {'path': ['h'], 'enc': h2, 'planes': planes(2, 4)},
        {'path': ['d'], 'enc': {'enc': 'sxbyte'}, 'planes': planes(1, 4)},
        {'path': ['b'], 'enc': {'enc': 'bit', 'value': 4},
         'planes': planes(1, 1)},
        {'path': ['q'], 'enc': {'enc': 'seq', 'pool': 'Q', 'form': 'end'},
         'planes': planes(4, 4)},
        {'path': ['@L.next'], 'enc': ml, 'planes': planes(2, 4)},
        {'path': ['@L.prev'], 'enc': ml, 'planes': planes(2, 4)},
    ]
    data = {
        'format': FORMAT, 'name': 'small', 'symbols': [], 'tables': [],
        'lists': {'L': {'elements': ['m'], 'prev': True}},
        'pools': {'Q': {'capacity': 8, 'count': planes(2, 1),
                        'enc': {'enc': 'handle', 'bytes': 1, 'ranges': [
                            {'lo': 0, 'n': 2, 'kind': 's'}]},
                        'planes': planes(1, 8)}},
        'kinds': {
            'm': {'capacity': 4, 'count': 3, 'leaves': leaves},
            's': {'capacity': 2, 'count': 2, 'leaves': [
                {'path': ['x'], 'enc': {'enc': 'int', 'bytes': 1,
                                        'signed': False},
                 'planes': planes(1, 2)}]}},
        'globals': {'leaves': [
            {'path': ['u:head'], 'enc': dict(ml, enc='list', list='L'),
             'planes': planes(2, 1)}]},
    }
    return Manifest(json.loads(json.dumps(data)))


def small_state():
    m = {0: {'h': Ref('m', 2), 'd': -5, 'b': 4, 'q': [Ref('s', 1)]},
         1: {'h': Ref('s', 1, 'x'), 'd': 127, 'b': 0, 'q': []},
         2: {'h': None, 'd': -128, 'b': 4,
             'q': [Ref('s', 0), Ref('s', 1), Ref('s', 0)]}}
    s = {0: {'x': 9}, 1: {'x': 200}}
    return {'format': canonical.FORMAT,
            'globals': {'u:head': [Ref('m', 2), Ref('m', 0), Ref('m', 1)]},
            'objects': {'m': m, 's': s}}


class Encodings(unittest.TestCase):
    def test_round_trip(self):
        mf = small_manifest()
        state = small_state()
        memory = PortWriter(mf).write(state)
        back = PortReader(mf).read(memory)
        self.assertEqual(canonical.diff(state, back), [])
        # NULL is all ones; the bit of object 2 is bit 2 of the bitmap
        h = [lf for lf in mf.kinds['m']['leaves'] if lf.path == ('h',)][0]
        self.assertEqual(memory.u8(h.planes[0] + 2), 0xFF)
        self.assertEqual(memory.u8(h.planes[1] + 2), 0xFF)
        self.assertEqual(memory.u8(h.planes[1] + 1), 0x08)
        b = [lf for lf in mf.kinds['m']['leaves'] if lf.path == ('b',)][0]
        self.assertEqual(memory.u8(b.planes[0]), 0b101)
        # the "end" form: start and end, not the length
        q = [lf for lf in mf.kinds['m']['leaves'] if lf.path == ('q',)][0]
        self.assertEqual((memory.u8(q.planes[0] + 2),
                          memory.u8(q.planes[2] + 2)), (1, 4))

    def test_a_byte_offset_range(self):
        mf = small_manifest()
        state = small_state()
        state['objects']['m'][1]['h'] = Ref('blob', 0, 7)
        back = PortReader(mf).read(PortWriter(mf).write(state))
        self.assertEqual(back['objects']['m'][1]['h'], Ref('blob', 0, 7))

    def test_refusals(self):
        for what, change in (
                ('sxbyte', lambda s: s['objects']['m'][0].update(d=128)),
                ('bit', lambda s: s['objects']['m'][0].update(b=1)),
                ('handle', lambda s: s['objects']['m'][0].update(
                    h=Ref('m', 4))),
                ('handle field', lambda s: s['objects']['m'][0].update(
                    h=Ref('s', 0, 'y'))),
                ('pool element', lambda s: s['objects']['m'][0].update(
                    q=[Ref('m', 0)])),
                ('constant count', lambda s: s['objects']['m'].update(
                    {3: dict(s['objects']['m'][2]),
                     4: dict(s['objects']['m'][2])}))):
            with self.subTest(what):
                state = small_state()
                change(state)
                with self.assertRaises(PortError):
                    PortWriter(small_manifest()).write(state)

    def test_reader_refuses_a_handle_naming_nothing(self):
        mf = small_manifest()
        memory = PortWriter(mf).write(small_state())
        h = [lf for lf in mf.kinds['m']['leaves'] if lf.path == ('h',)][0]
        memory.put(h.planes[1] + 0, 0x05, 1)        # $05xx: no range
        with self.assertRaises(PortError):
            PortReader(mf).read(memory)
        memory = PortWriter(mf).write(small_state())
        q = [lf for lf in mf.kinds['m']['leaves'] if lf.path == ('q',)][0]
        memory.put(q.planes[2] + 2, 0, 1)           # an end before its start
        with self.assertRaises(PortError):
            PortReader(mf).read(memory)


# ---------------------------------------------------------------------------
# The game layout (tools/native/llayout.py)
# ---------------------------------------------------------------------------

class GameLayout(unittest.TestCase):
    def test_special_ranges(self):
        lo = 0
        for kind, n in LL.SPEC_KINDS:
            self.assertEqual(LL.SPEC_RANGE[kind], (lo, n))
            lo += n
        # every record in ZONE0, every handle above the mobjs' and below
        # the sector nodes' none
        self.assertLessEqual(LL.ROOM[0] + LL.SPEC_SIZE * lo, LL.ROOM[1])
        self.assertGreaterEqual(LL.SPEC_HANDLE, LL.MOBJ_CAP)
        self.assertLess(LL.SPEC_HANDLE + lo, 0xFFFF)

    def test_mobj_groups(self):
        # each game part's fields in a group of 24 bytes a slot, the 2,026
        # slots within the bank
        for part in (LL.MA, LL.MB, LL.MC):
            self.assertLessEqual(max(part.values()) + 2, 24)
        self.assertLessEqual(LL.ROOM[0] + 24 * LL.MOBJ_CAP, LL.ROOM[1])
        self.assertEqual(len(set(LL.MOBJ) & set(LL.SPARE)), 0)

    def test_globals_block(self):
        self.assertEqual(LL.GBLOCK, LL.LNMAP_END)
        self.assertLessEqual(LL.GLOBALS_END, 0x2000)
        # the pre-state record: the globals block, then the two random
        # bytes
        self.assertEqual(LL.PRE_RND, LL.GLOBALS_END - LL.GBLOCK)
        self.assertLessEqual(LL.PRE_RND + 2, LL.PRE_RECORD)

    def test_zero_page(self):
        lo, n = 0x18, sum(w for _, w in LL.LZPG)
        self.assertLessEqual(lo + n, 0x38)

    # lgame.inc takes upstream's constants through the link map and the
    # weapons' tables from the release
    @unittest.skipUnless((BUILD / 'linkmap.json').exists() and
                         (BUILD / 'release' / 'doom-hd.hdv').exists(),
                         'needs build/linkmap.json (python3 '
                         'tools/v816/imgmatch.py) and the release '
                         '(python3 tools/fetch_upstream.py)')
    def test_include_names(self):
        text = LL.game_include_text()
        names = [ln.split()[0] for ln in text.splitlines()
                 if ln and not ln.startswith(';')]
        self.assertEqual(len(names), len(set(names)))
        others = set()
        for t in (LL.include_text(), R.include_text()):
            others |= {ln.split()[0] for ln in t.splitlines()
                       if ln and not ln.startswith(';')}
        self.assertFalse(set(names) & others, 'lgame.inc shares a name')


# ---------------------------------------------------------------------------
# The host's parts of the checks (tools/native/setupcheck.py)
# ---------------------------------------------------------------------------

class HostChecks(unittest.TestCase):
    def test_flood_depth(self):
        from native import setupcheck as SC
        # a chain of 5 sectors: depth 5 from an end, 3 from the middle
        chain = [[1], [0, 2], [1, 3], [2, 4], [3]]
        none = [[] for _ in chain]
        self.assertEqual(SC.flood_depth(chain, none, 0), 5)
        self.assertEqual(SC.flood_depth(chain, none, 2), 3)
        # a sound-blocking line: entered with v = 1, then not past another
        self.assertEqual(SC.flood_depth([[], [], []], [[1], [2], []], 0), 2)
        # a sector reached again with fewer blocks is entered again
        self.assertEqual(SC.flood_depth([[1, 2], [], [1]],
                                        [[], [], []], 0), 2)

    def test_block_walk_model(self):
        """secorder.py's model of the walk on a hand-made level of 2 x 2
        blocks: a vertical line in block (0, 1) between sectors 1 and 2,
        a horizontal one in block (1, 0) between 3 and 4; a thing of
        radius 8 at the blocks' corner (128, 128) in sector 0 crosses
        both: x outer meets the first line first."""
        from native import secorder as SO
        lines = [{'bbox': [200, 100, 124, 124], 'slope': 1,
                  'v1': [124, 100], 'v2': [124, 200], 'front': 1,
                  'back': 2},
                 {'bbox': [124, 124, 100, 200], 'slope': 0,
                  'v1': [100, 124], 'v2': [200, 124], 'front': 3,
                  'back': 4}]
        level = {'orgx': 0, 'orgy': 0, 'w': 2, 'h': 2, 'lines': lines,
                 'lists': [[], [1], [0], []]}   # (x, y): y * w + x
        x_out = SO.walk(level, 128, 128, 8, 0, True)
        y_out = SO.walk(level, 128, 128, 8, 0, False)
        self.assertEqual(x_out, [0, 4, 3, 2, 1])
        self.assertEqual(y_out, [0, 2, 1, 4, 3])
        # a box short of the horizontal line: one order
        self.assertEqual(SO.walk(level, 128, 160, 8, 0, True),
                         SO.walk(level, 128, 160, 8, 0, False))

    def test_wrapped(self):
        from native import setupcheck as SC
        ref = {'globals': {'p_map65.s:validcount': 13},
               'objects': {'line': {0: {'validcount': 11},
                                    1: {'validcount': 0}},
                           'sector': {0: {'validcount': 12}}}}
        # plain from 10: walks 1, 2, 3 stamp 11, 12, 13; from $FFFE the
        # walk 2 wraps: walk 1 cleared (0), walks 2 and 3 stamp 1 and 2
        out = SC.wrapped(ref, 10, 0xFFFE)
        self.assertEqual(out['objects']['line'][0]['validcount'], 0)
        self.assertEqual(out['objects']['line'][1]['validcount'], 0)
        self.assertEqual(out['objects']['sector'][0]['validcount'], 1)
        self.assertEqual(out['globals']['p_map65.s:validcount'], 2)


# ---------------------------------------------------------------------------
# The setups on a2vm
# ---------------------------------------------------------------------------

@needs_build
class Setups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from native import lrun
        lrun.make()

    def test_sizes(self):
        from native import lrun
        for build in ('ltest', 'lcard'):
            b = lrun.load_build(lrun.OBJ, build)
            lo, hi = b.segments['LOADW']
            self.assertEqual(lo, LL.LW_CODE)
            self.assertLess(hi, LL.LW_CODE_END)
            self.assertEqual(b.segments['RLOAD'][1], 0xDE8E)
            sizes = lrun.module_sizes(b)
            for name in ('lsetup', 'gthink', 'gpos', 'gspawn', 'gweap',
                         'gspec', 'gvalid'):
                self.assertGreater(sizes.get(name, 0), 0, name)

    def test_acceptance_1_sample(self):
        from native import setupcheck as SC
        rep = SC.check_setups(fills=(0xA5,), names=SAMPLE)
        self.assertEqual(rep['failures'], [])
        self.assertEqual(sorted(rep['setups']), sorted(SAMPLE))
        for name, one in rep['setups'].items():
            self.assertTrue(one['fills']['A5']['ok'], name)
        self.assertTrue(rep['setups']['reborn-e1m1-02']['fills']['A5']
                        ['static_as_first'])
        self.assertTrue(all(r['stack_bytes'] + R.IRQ_STACK <= LL.GAME_STACK
                            for r in rep['runs']))
        self.assertTrue(all(z['ok'] for z in rep['zone'].values()))
        rep = SC.check_setups(fills=(0x5A,), names=('tour-sk4-08',))
        self.assertEqual(rep['failures'], [])

    def test_reborn_with_a_kit(self):
        """reborn-kit: the player at E holds every KIT value and ref816's
        G_PlayerReborn changes each, so the resets are observed; the
        native setup equals ref816's from both fills."""
        from native import levelconv as LC, setupcap, setupcheck as SC
        names = {d.name for d in setupcap.setup_dirs()}
        if not {'reborn-kit-01', 'reborn-kit-02'} <= names:
            self.skipTest('needs python3 tools/native/setupcap.py --runs '
                          'reborn-kit')
        d = setupcap.SETUPS / 'reborn-kit-02'
        em, rm = SC.e_memory(d), LC.load_memory(d / 'r.ram.z')
        pl = SC._schema().symbols.address('g_game65.s:_g_player')
        for at, size, value in setupcap.KIT:
            n = 4 if size == 'long' else 2
            e = int.from_bytes(em.read(pl + at, n), 'little')
            r = int.from_bytes(bytes(rm.read(pl + at, n)), 'little')
            self.assertEqual(e, value, at)
            self.assertNotEqual(r, value, at)
        rep = SC.check_setups(names=('reborn-kit',))
        self.assertEqual(rep['failures'], [])
        self.assertTrue(rep['setups']['reborn-kit-02']['fills']['5A']
                        ['static_as_first'])

    def test_block_walk_order(self):
        """secorder: E1M1 with three things moved to block corners where
        the walk's order shows; the native setup equals ref816's from both
        fills (the native run's store takes the same moves)."""
        from native import setupcap, setupcheck as SC
        if 'secorder-01' not in {d.name for d in setupcap.setup_dirs()}:
            self.skipTest('needs python3 tools/native/setupcap.py --runs '
                          'secorder')
        rep = SC.check_setups(names=('secorder',))
        self.assertEqual(rep['failures'], [])
        meta = json.loads((setupcap.SETUPS / 'secorder-01' /
                           'setup.json').read_text())
        self.assertTrue(meta['synthetic'])
        self.assertGreaterEqual(len(meta['things']), 2)

    def test_wrap_fix(self):
        from native import setupcap, setupcheck as SC
        names = {d.name for d in setupcap.setup_dirs()}
        if SC.WRAP_SETUP not in names or SC.PLAIN_SETUP not in names:
            self.skipTest('needs python3 tools/native/setupcap.py --runs '
                          'wrap,newgame')
        out = SC.check_wrap_fix()
        self.assertTrue(out['ok'], out['builds'])
        self.assertGreater(out['v0_wrap'], 0xFF00)
        self.assertLess(out['builds']['lfix']['validcount'], 0x100)
        self.assertNotEqual(out['builds']['ltest']['validcount'],
                            out['builds']['lfix']['validcount'])

    def test_flood_bound(self):
        from native import setupcheck as SC
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m9-flood-', dir=str(BUILD)))
        try:
            rep = SC.check_setups(fills=(0xA5,), names=(SC.KEEP_RUN,),
                                  keep=tmp)
            self.assertEqual(rep['failures'], [])
            fl = SC.check_flood(tmp)
            self.assertEqual(fl['failures'], [])
            self.assertEqual(len(fl['maps']), 9)
            self.assertTrue(all(r['depth'] <= SC.FLOOD_STACK
                                for r in fl['maps'].values()))
            self.assertEqual(fl['maps']['E1M2']['depth'], 93)
            # the check fails against a stack too small
            with mock.patch.object(SC, 'FLOOD_STACK', 80):
                small = SC.check_flood(tmp)
            self.assertTrue(any(f.startswith('E1M2:')
                                for f in small['failures']), small)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


@needs_build
class Disk(unittest.TestCase):
    def test_setup_disk_one_map(self):
        from native import ldisk, lrun
        try:
            bd = ldisk.disk_writer()
        except Exception as e:      # pragma: no cover (the writer's tree)
            self.skipTest('the disk writer: %s' % e)
        if not bd.DEFAULT_MASTER.is_file():
            self.skipTest('needs appletini-one\'s ProDOS (%s)'
                          % bd.DEFAULT_MASTER)
        lrun.make()
        disk = ldisk.build(maps=(7,))
        work = Path(tempfile.mkdtemp(prefix='tmp-m9-test-', dir=str(BUILD)))
        try:
            r = ldisk.check(disk, work, 'fastpath')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        self.assertEqual(r['problems'], [])
        self.assertEqual([x['map'] for x in r['loads']], [7])
        self.assertEqual(r['loads'][0]['canonical'], 'equal')
        self.assertEqual(r['loads'][0]['crc_ok'], 3)


# ---------------------------------------------------------------------------
# Planted bugs (docs/LEVELS.md 5.7, stage C's)
# ---------------------------------------------------------------------------

@needs_build
class Planted(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='tmp-m9-plant-',
                                         dir=str(BUILD)))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def failures(self, bugs, names=('tour-sk2-01',)):
        import test_native_level_load as TL
        from native import setupcheck as SC
        obj = TL.planted_obj(self.tmp, bugs)
        rep = SC.check_setups(fills=(0xA5,), names=names, obj=obj)
        return rep['failures']

    def assertDiffers(self, f):
        self.assertTrue(any('differences' in x for x in f), f)

    def test_pool_lowest_free_slot(self):
        self.assertDiffers(self.failures([('gthink.s', """gt_pooltake:
        ldx #POOL_MAX / 8 - 1
@byte:  lda G_TPBITS,x
        bne @found
        dex
        bpl @byte""", """gt_pooltake:
        ldx #0                  ; (planted: from the lowest byte)
@byte:  lda G_TPBITS,x
        bne @found
        inx
        cpx #POOL_MAX / 8
        bne @byte"""), ('gthink.s', """@found: ldy #7                  ; its highest bit
:       asl a
        bcs :+
        dey
        bra :-""", """@found: ldy #0                  ; (planted: its lowest bit)
:       lsr a
        bcs :+
        iny
        bra :-""")]))

    def test_pooltake_lowest_bit_of_the_highest_byte(self):
        self.assertDiffers(self.failures([('gthink.s', """@found: ldy #7                  ; its highest bit
:       asl a
        bcs :+
        dey
        bra :-""", """@found: ldy #0                  ; (planted: its lowest bit)
:       lsr a
        bcs :+
        iny
        bra :-""")]))

    def test_random_after_the_tics(self):
        self.assertDiffers(self.failures([('gspawn.s', """@random:
        jsr g_random            ; (only for compatibility)""", """@random:
        nop                     ; (planted: after the tics, below)
        nop
        nop"""), ('gspawn.s', """        jsr gs_mobj
        lda LW_MOB + MO_XTICS + 1       ; tics > 0: 1 + P_Random() % tics""",
                                              """        jsr gs_mobj
        jsr g_random            ; (planted: P_SpawnMobj's, after)
        lda LW_MOB + MO_XTICS + 1       ; tics > 0: 1 + P_Random() % tics""")]))

    def test_a_thinker_for_tics_minus_one(self):
        self.assertDiffers(self.failures([('gspawn.s', """        cmp #$FF
        bne @fn
        ldx #FN_NONE
@fn:""", """        cmp #$FF
        bne @fn
        nop                     ; (planted: a thinker all the same)
        nop
@fn:""")]))

    def test_a_missing_secret_count(self):
        self.assertDiffers(self.failures([('gspec.s', """        inc G_TOTALSECRET
        bne @next
        inc G_TOTALSECRET+1
        bne @next
        inc G_TOTALSECRET+2
        bne @next
        inc G_TOTALSECRET+3
        bra @next""", """        bra @next               ; (planted: not counted)""")]))

    def test_a_thing_after_its_blocks_head(self):
        # a block's list with a thing in it: the new thing after it (the
        # tail of a list of one), not at the head
        self.assertDiffers(self.failures([('gpos.s', """        jsr g_get
        lda GC_H
        sta MO_A + MA_BNEXT""", """        jsr g_get
        lda GC_H+1              ; (planted: after an existing head)
        cmp #$FF
        beq @empty
        lda #$FF
        sta MO_A + MA_BNEXT
        sta MO_A + MA_BNEXT + 1
        lda GC_H
        sta MO_A + MA_BPREV
        lda GC_H+1
        sta MO_A + MA_BPREV + 1
        lda #MA_BNEXT
        jmp link_prev
@empty: lda GC_H
        sta MO_A + MA_BNEXT""")]))

    def test_a_light_spawner_leaving_the_special(self):
        self.assertDiffers(self.failures([('gspec.s', """        jsr no_special
        lda #1                  ; in sync: count 1, else (P_Random() & 7)""",
                                           """        nop                     ; (planted: the special left)
        nop
        nop
        lda #1                  ; in sync: count 1, else (P_Random() & 7)""")]))

    def test_stray_store_into_lvseg(self):
        f = self.failures([('gspawn.s', """        jsr gp_setpos           ; the blocks and the sector (GC_SEC)""",
                            """        jsr gp_setpos           ; the blocks and the sector (GC_SEC)
        lda #LVSEG              ; (planted: a seg's byte written back)
        sta FA_BANK
        stz FA_SRC
        lda #$02
        sta FA_SRC+1
        lda #<LW_SREC
        ldx #>LW_SREC
        ldy #1
        jsr g_get
        stz FA_DST
        lda #$02
        sta FA_DST+1
        lda #<LW_SREC
        ldx #>LW_SREC
        ldy #1
        jsr g_put""")])
        self.assertTrue(any('stray CPU writes' in x and 'aux %d' % R.LVSEG
                            in x for x in f), f)
        self.assertFalse(any('differences' in x for x in f), f)

    def test_player_reborn_without_its_clear(self):
        """G_PlayerReborn keeping the old player (only viewz cleared):
        the reborn-kit capture, whose player at E holds a kit, differs in
        the player's resets (health, armour, powers, cards, the backpack,
        weapons, ammunition and its maxima)."""
        from native import setupcap
        names = {d.name for d in setupcap.setup_dirs()}
        if not {'reborn-kit-01', 'reborn-kit-02'} <= names:
            self.skipTest('needs python3 tools/native/setupcap.py --runs '
                          'reborn-kit')
        f = self.failures([('gspawn.s', """        lda #<PLR
        ldx #>PLR
        ldy #PL_SIZE
        jsr g_zero""", """        stz PLR + PL_VIEWZ_G    ; (planted: the old player kept)
        stz PLR + PL_VIEWZ_G + 1
        stz PLR + PL_VIEWZ_G + 2
        stz PLR + PL_VIEWZ_G + 3""")], names=('reborn-kit',))
        self.assertDiffers(f)
        text = ' '.join(f)
        self.assertIn('reborn-kit-02', text)
        self.assertNotIn('reborn-kit-01', text)
        # (the failure names the first six of the differences, in the
        # player's field order)
        for field in ('player[0].ammo', 'player[0].armorpoints',
                      'player[0].backpack', 'player[0].cards'):
            self.assertIn(field, text)

    def test_block_walk_y_outer(self):
        """P_CreateSecNodeList's block walk with y outer and x inner: the
        captured setups cannot see it (docs/LEVELS.md "Stage C as built"),
        the synthetic setup secorder must."""
        from native import setupcap
        if 'secorder-01' not in {d.name for d in setupcap.setup_dirs()}:
            self.skipTest('needs python3 tools/native/setupcap.py --runs '
                          'secorder')
        f = self.failures([('gpos.s', """        lda GS_XL               ; x outer, y inner
        sta GS_BX
@col:   lda GS_YL
        sta GS_BY
@blk:   jsr walkblock
        lda GS_BY
        cmp GS_YH
        beq :+
        inc GS_BY
        bra @blk
:       lda GS_BX
        cmp GS_XH
        beq @own
        inc GS_BX
        bra @col""", """        lda GS_YL               ; (planted: y outer, x inner)
        sta GS_BY
@col:   lda GS_XL
        sta GS_BX
@blk:   jsr walkblock
        lda GS_BX
        cmp GS_XH
        beq :+
        inc GS_BX
        bra @blk
:       lda GS_BY
        cmp GS_YH
        beq @own
        inc GS_BY
        bra @col""")], names=('secorder',))
        self.assertDiffers(f)
        self.assertTrue(any('secnode' in x and 'm_sector' in x for x in f), f)

    def test_validcount_wrap_without_the_clear(self):
        """The release build's wrap fix removed: the wrap check fails."""
        import test_native_level_load as TL
        from native import setupcap, setupcheck as SC
        names = {d.name for d in setupcap.setup_dirs()}
        if SC.WRAP_SETUP not in names:
            self.skipTest('needs python3 tools/native/setupcap.py --runs '
                          'wrap,newgame')
        obj = TL.planted_obj(self.tmp, [('gvalid.s', """        jsr gv_clear
        lda #1
        sta G_VALID""", """        nop                     ; (planted: no clear, from 0)
        nop
        nop""")])
        out = SC.check_wrap_fix(obj)
        self.assertFalse(out['ok'])
        self.assertTrue(out['builds']['lfix']['diff'])
        self.assertFalse(out['builds']['ltest']['diff'])


if __name__ == '__main__':
    unittest.main()
