"""Milestone 9, stage B: the store's boot load and the 65C02 loader into
the level window (docs/LEVELS.md 6.2; src/native/lload.s, lgeom.s,
ldriver.s, lboot.s, level.cfg, level.mk; tools/native/lrun.py,
ldisk.py, level_check.py --load, frame8.py --levels loaded).

Without build/: the load layout's constants against the store's format
(lstore.py), the write log's ranges, the disk's catalog.

With cc65, a2vm, the store (python3 tools/native/wadconv.py --store), the
setup captures (python3 tools/native/setupcap.py; level_check.py --conv
writes their levelconv.py levels) and the math tables (python3
tools/native/rtables.py): checkpoint B on a sample (E1M1, E1M7, E1M1
from the $A5 machine: the variants undone; E1M7 from the $5A one): the
window against window.img, the read-back against levelconv.py's level of
the W dump, the derived parts against the R dump's canonical state, the
harness read-back against the converter's, no stray write, no byte
changed outside the loads' places; extreme lines poked into the store
(the box's overflow, dx and dy wrapping, odd and negative coordinates)
loaded by the 65C02 and by lstore.HostMachine, equal; the stops (a map
the store lacks, a codec). With appletini-one's ProDOS too: the boot
disk on a2vm. With the frames of milestones 7 and 8 too: frame8.py on
natively loaded levels for two frames, a synthetic one excluded. Then
that the checks fail: bugs planted in scratch copies of the sources
(docs/LEVELS.md 5.7, stage B's), each caught by the check named.
"""

import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

from native import llayout as LL, lstore as S, rlayout as R  # noqa: E402

ROOT = support.ROOT
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))


def ready():
    from native import level_check as K, lrun
    if not (HAVE_CC65 and lrun.A2VM.exists() and
            (S.STORE / 'store.json').exists() and
            (lrun.RC.TABLES / 'math' / 'squares.bin').exists()):
        return False
    dumps = K.dumps_of()
    return all(m in dumps and (K.REF / dumps[m].name / 'level.json').exists()
               and (K.CONV / ('e1m%d' % m) / 'level.json').exists()
               for m in (1, 7))


READY = ready()
WHY = ('needs cc65 on PATH, build/a2vm/a2vm (make -C tools/a2vm), the store '
       '(python3 tools/native/wadconv.py --store), the harness levels '
       '(python3 tools/native/wadconv.py), the setup captures and their '
       'levels (python3 tools/native/setupcap.py, python3 tools/native/'
       'level_check.py --conv), the math tables (python3 tools/native/'
       'rtables.py)')
needs_build = unittest.skipUnless(READY, WHY)

SOURCES = ('lload.s', 'lgeom.s', 'ldriver.s', 'lboot.s', 'far.s',
           'math.s', 'math.inc', 'auxlc.s', 'level.cfg', 'level.mk',
           # stage C's (level.mk links them into every build)
           'lsetup.s', 'gthink.s', 'gpos.s', 'gspawn.s', 'gweap.s',
           'gspec.s', 'gvalid.s')


def planted_obj(tmp: Path, bugs) -> Path:
    """The sources copied to tmp/src with each (file, old, new) applied
    once, built into tmp/obj."""
    from native import lrun
    src = tmp / 'src'
    src.mkdir()
    for name in SOURCES:
        shutil.copy(str(SRC / name), str(src / name))
    for name, old, new in bugs:
        text = (src / name).read_text()
        if text.count(old) != 1:
            raise AssertionError('the bug no longer applies to %s: %r'
                                 % (name, old))
        (src / name).write_text(text.replace(old, new))
    lrun.make(tmp / 'obj', src)
    return tmp / 'obj'


# ---------------------------------------------------------------------------
# Without build/
# ---------------------------------------------------------------------------

class Layout(unittest.TestCase):
    def test_header_and_program_offsets_are_the_stores(self):
        self.assertEqual(LL.BLOCK_KINDS, S.BLOCK_KINDS)
        self.assertEqual(LL.HEADER_COUNTS, S.HEADER_COUNTS)
        self.assertEqual(LL.LH_SIZE, S.HEADER_SIZE)
        part = S.Part(3)
        part.header = {'counts': {k: 100 + i for i, k in
                                  enumerate(S.HEADER_COUNTS)},
                       'lvg1': {'LTAB': 0x1000, 'FLIDX': 0x2000,
                                'FLENT': 0x3000, 'BLINKS': 0x4000},
                       'reject': 0x5000,
                       'blockmap': {'orgx': -1, 'orgy': 2, 'columns': 3,
                                    'rows': 4},
                       'sky': (9, 0x0200),
                       'lumps': {'BLOCKMAP': 13, 'REJECT': 12}}
        part.where = {k: (77 + i % 3, 0x0200 + 16 * i) for i, k in
                      enumerate(S.BLOCK_KINDS)}
        part.blocks = {k: bytes(i + 1) for i, k in enumerate(S.BLOCK_KINDS)}
        data = S.header_bytes(part)
        self.assertEqual(len(data), LL.LH_SIZE)
        # the offsets the 65C02 uses (llayout.inc)
        k = LL.BLOCK_KINDS.index('PROGRAM')
        at = LL.LH_BLOCKS + LL.LH_BLOCK * k
        self.assertEqual(data[at], part.where['PROGRAM'][0])
        self.assertEqual(struct.unpack_from('<H', data, at + 2)[0],
                         part.where['PROGRAM'][1])
        self.assertEqual(struct.unpack_from('<H', data, at + 4)[0],
                         len(part.blocks['PROGRAM']))
        self.assertEqual(struct.unpack_from('<H', data, LL.LH_LVG1 + 4)[0],
                         0x3000)
        self.assertEqual(struct.unpack_from(
            '<H', data, LL.LH_COUNTS + 2 * LL.HEADER_COUNTS.index('flood'))[0],
            100 + S.HEADER_COUNTS.index('flood'))
        part.steps = [('VARIANTS', 3), ('LINES', 0), ('END', 0)]
        part.requests = [[S.descriptor(LL.AMEM_FILL, None, (1, 6, 0x200), 5,
                                       7)]]
        prog = S.program_bytes(part)
        self.assertEqual(prog[:LL.LP_HEAD], b'LP' + bytes([3, 3, 1, 0]))
        self.assertEqual(prog[LL.LP_HEAD], LL.STEPS['VARIANTS'])

    def test_include_and_its_checks(self):
        text = LL.include_text()
        self.assertIn('LW_HDR', text)
        self.assertIn('LG_BOX', text)
        names = [ln.split()[0] for ln in text.splitlines()
                 if ln and not ln.startswith(';')]
        self.assertEqual(len(names), len(set(names)))
        rnames = {ln.split()[0] for ln in R.include_text().splitlines()
                  if ln and not ln.startswith(';')}
        self.assertFalse(set(names) & rnames, 'llayout.inc and rlayout.inc '
                         'share a name')

    def test_allowed_writes_of_a_load(self):
        counts = {'sectors': 3, 'subsectors': 2, 'lines': 4}
        lvg1 = {'BLINKS': 0x0300}
        got = LL.allowed_writes_load(counts, lvg1)
        lvmap = [(lo, hi) for s, bank, lo, hi, _ in got if bank == R.LVMAP
                 and s == 'aux']
        self.assertEqual(lvmap, [(R.SUBS.address(i), R.SUBS.address(i) + 1)
                                 for i in range(2)])
        lvg0 = [(lo, hi) for s, bank, lo, hi, _ in got if bank == LL.LVG0]
        self.assertEqual(lvg0, [(LL.LINES.base, LL.LINES.address(4))])

    def test_complement_and_catalog(self):
        from native import ldisk, lrun
        self.assertEqual(lrun.complement([(2, 4), (6, 7)], 0, 10),
                         [(0, 1), (4, 5), (7, 9)])
        self.assertEqual(lrun.complement([(0, 10)], 0, 10), [])
        cat = ldisk.catalog(['TEXELS.1', 'CODE.1'], [1, 9, 1])
        self.assertEqual(cat[:2], bytes([2, 3]))
        self.assertEqual(cat[16:25], b'\x08TEXELS.1')
        maps = 16 + 2 * 16          # the maps after the names
        self.assertEqual(cat[maps:maps + 3], bytes([1, 9, 1]))
        # stage C: each map's pre-state after the 40 map slots, none ($FF)
        self.assertEqual(cat[maps + ldisk.MAX_MAPS:], b'\xff' * 3)
        cat = ldisk.catalog(['A'], [1, 7], [0, 1])
        self.assertEqual(cat[-2:], bytes([0, 1]))
        with self.assertRaises(ldisk.DiskError):
            ldisk.catalog(['A'], list(range(1, 42)))


# ---------------------------------------------------------------------------
# The loader on a2vm
# ---------------------------------------------------------------------------

def poked_lines(seed_lines: bytes):
    """E1M1's first six compact lines with extreme coordinates (sides,
    flags, special and tag kept)."""
    coords = [(-20000, -20000, 20000, 20000), (30000, -30000, -30000, 30000),
              (-32768, 5, 32767, 5), (7, -32768, 7, 32767),
              (-3, -5, -3, -5), (-1, 32767, 1, -32768)]
    out = bytearray(seed_lines)
    for i, c in enumerate(coords):
        struct.pack_into('<hhhh', out, LL.LINEC_SIZE * i, *c)
    return bytes(out)


def synthetic_run(test, obj=None):
    """E1M1 with poked lines, loaded by the 65C02 (a2vm) and by
    lstore.HostMachine: the differences in LVG0's lines, LVG1's tables
    and records, LVMAP's subsector sectors (a list, empty when equal)."""
    from native import lrun
    meta = json.loads((S.STORE / 'store.json').read_text())
    h = meta['maps']['E1M1']
    blk = h['blocks']['LINES']
    hm = S.HostMachine(lrun.store_files(), tuple(meta['directory']))
    seed = hm.read(blk['bank'], blk['address'], LL.LINEC_SIZE * 6)
    data = poked_lines(seed)
    hm.write(blk['bank'], blk['address'], data)
    hm.load(1)
    b = lrun.load_build(obj or lrun.OBJ, 'ltest')
    work = Path(tempfile.mkdtemp(prefix='tmp-m9-test-', dir=str(BUILD)))
    try:
        r = lrun.run(b, [1], 0xA5, work, snapshots=True, write_log=False,
                     extra_records=[(1, blk['bank'], blk['address'], data)])
        test.assertEqual(r.ended(), 'halt')
        mach = lrun.SnapMachine.from_image(lrun.load_snapshots(work)[0])
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    c = h['header']['counts']
    v = h['header']['lvg1']
    diffs = []
    for bank, lo, hi in ((LL.LVG0, LL.LINES.base, LL.LINES.address(c['lines'])),
                         (LL.LVG1, LL.SECGS.base, v['BLINKS'])):
        a = bytes(mach.aux[bank][lo:hi])
        e = bytes(hm.aux[bank][lo:hi])
        if a != e:
            at = next(i for i in range(len(a)) if a[i] != e[i])
            diffs.append('bank %d $%04X' % (bank, lo + at))
    for i in range(c['subsectors']):
        a = R.SUBS.address(i)
        if mach.aux[R.LVMAP][a] != hm.aux[R.LVMAP][a]:
            diffs.append('subsector %d' % i)
    return diffs


class PerLoadWrites(unittest.TestCase):
    """The stray check of a run of several loads takes each load's writes
    against its own map's places (lrun.stray_by_load: the write log cut
    at each drv_loaded), not the union of the run's maps'."""

    def build(self):
        from types import SimpleNamespace
        return SimpleNamespace(
            labels={'drv_loaded': 0xC123, 'dl_k': 0xCF00},
            segments={'LOADW': (0x6600, 0x7FFF), 'RFAR': (0xDC00, 0xDCFF),
                      'MATHW': (0x6000, 0x63FF), 'AUXW': (0x6400, 0x65FF),
                      'DRIVER': (0xC100, 0xC2FF), 'RLOAD': (0xDD00, 0xDE8E),
                      'DESC': (0xCF00, 0xCF3F)})

    def test_a_write_into_another_maps_place(self):
        from unittest import mock
        from native import lrun
        from native.render_check import Write
        # map A may write aux 10 $1000-$10FF, map B aux 10 $2000-$20FF
        places = {'A': [('aux', 10, 0x1000, 0x1100, 'a')],
                  'B': [('aux', 10, 0x2000, 0x2100, 'b')]}
        a, b_ = {'counts': 'A', 'lvg1': None}, {'counts': 'B', 'lvg1': None}
        end = Write(0xC123, 0xCF00, 'lc', 0, 0xCF00)   # inc dl_k
        log = [Write(0x6700, 0x1000, 'aux', 10, 0x1000), end,
               Write(0x6700, 0x2000, 'aux', 10, 0x2000),
               Write(0x6700, 0x1080, 'aux', 10, 0x1080), end]
        with mock.patch.object(lrun.LL, 'allowed_writes_load',
                               lambda counts, lvg1: places[counts]):
            union = lrun.stray(log, self.build(), [a, b_])
            own = lrun.stray_by_load(log, self.build(), [a, b_])
            self.assertEqual(union, [])
            self.assertEqual(own, ['load 2: pc $6700 wrote aux 10 $1080'])
            # the cut must find one end a load
            with self.assertRaises(lrun.RunError):
                lrun.stray_by_load(log[:-1], self.build(), [a, b_])


@needs_build
class Loader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from native import lrun
        lrun.make()

    def test_sizes(self):
        from native import lrun
        b = lrun.load_build(lrun.OBJ, 'ltest')
        lo, hi = b.segments['LOADW']
        self.assertEqual(lo, LL.LW_CODE)
        self.assertLess(hi, LL.LW_CODE_END)
        # the card is unchanged: the far layer and the phase loader end
        # where milestone 8's do (MEMORY_MAP.md 13: $DE8E)
        self.assertEqual(b.segments['RLOAD'][1], 0xDE8E)
        sizes = lrun.module_sizes(b)
        self.assertLessEqual(sizes['lload'], lrun.BUDGETS['lload'])
        self.assertLessEqual(sizes['lload'] + sizes['lgeom'],
                             lrun.BUDGETS['lload'] + lrun.BUDGETS['lgeom'])

    def test_checkpoint_b_sample(self):
        from native import level_check as K
        rep = K.check_load(fills=(0xA5,), sequence=(1, 7, 1),
                           keep_loaded=False)
        self.assertEqual(rep['failures'], [])
        loads = rep['runs'][0]['loads']
        self.assertEqual(len(loads), 3)
        self.assertTrue(all(x['ok'] for x in loads))
        self.assertGreater(loads[1]['window_bytes'], 100000)
        self.assertGreater(loads[1]['derived']['flood'], 0)
        self.assertEqual(rep['runs'][0]['changed_outside'], 0)
        # each map alone: no byte changed outside its own places
        self.assertEqual(rep['runs'][0]['changed_outside_alone'],
                         {'E1M1': 0, 'E1M7': 0})
        rep = K.check_load(fills=(0x5A,), sequence=(7,), keep_loaded=False)
        self.assertEqual(rep['failures'], [])

    def test_synthetic_lines_equal_the_hosts(self):
        self.assertEqual(synthetic_run(self), [])

    def test_stops(self):
        from native import lrun
        b = lrun.load_build(lrun.OBJ, 'ltest')
        meta = json.loads((S.STORE / 'store.json').read_text())
        hb = meta['maps']['E1M1']['blocks']['HEADER']
        codec = hb['address'] + LL.LH_BLOCKS + LL.LH_BLOCK * \
            LL.BLOCK_KINDS.index('LINES') + 1
        for maps, extra, want in (([10], [], LL.LS['MAP']),
                                  ([1], [(1, hb['bank'], codec, b'\x01')],
                                   LL.LS['CODEC'])):
            work = Path(tempfile.mkdtemp(prefix='tmp-m9-test-',
                                         dir=str(BUILD)))
            try:
                r = lrun.run(b, maps, 0xA5, work, snapshots=True,
                             write_log=False, extra_records=extra)
                self.assertEqual(r.ended(), 'crash')
                self.assertEqual(lrun.status_of(r), want)
            finally:
                shutil.rmtree(str(work), ignore_errors=True)


@needs_build
class Disk(unittest.TestCase):
    def test_boot_disk_two_maps(self):
        from native import ldisk, lrun
        try:
            ldisk.disk_writer()
        except Exception as e:      # pragma: no cover (the writer's tree)
            self.skipTest('the disk writer: %s' % e)
        bd = ldisk.disk_writer()
        if not bd.DEFAULT_MASTER.is_file():
            self.skipTest('needs appletini-one\'s ProDOS (%s)'
                          % bd.DEFAULT_MASTER)
        lrun.make()
        disk = ldisk.build(maps=(1, 7))
        work = Path(tempfile.mkdtemp(prefix='tmp-m9-test-', dir=str(BUILD)))
        try:
            r = ldisk.check(disk, work, 'f121')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        self.assertEqual(r['problems'], [])
        self.assertEqual([x['map'] for x in r['loads']], [1, 7])
        self.assertGreater(r['loads'][0]['store_bytes'], 3_000_000)
        self.assertTrue(all(x['vbls'] for x in r['loads']))


def have_frames():
    from native import frame8 as F8, render_check as RC
    from native import level_check as K
    return READY and all((RC.RENDER / 'frames' / f / 'p5.dump.z').exists()
                         for f in ('tour-01', 'synth-flat')) and \
        (RC.TABLES / 'tables.img').exists() and \
        (RC.OBJ / 'ftest.lbl').exists() and F8 is not None and K


@unittest.skipUnless(READY and have_frames(), WHY + '; the frames of '
                     'python3 tools/native/rendercap.py and framesynth.py, '
                     'the build of src/native/render.mk')
class Frames(unittest.TestCase):
    def test_frame8_on_loaded_levels(self):
        from native import frame8 as F8, level_check as K, lrun
        from native import framestate as FS
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m9-test-', dir=str(BUILD)))
        saved = (lrun.LOADED, FS.LEVEL_HOOK)
        try:
            lrun.LOADED = tmp / 'loaded'
            K.LOADED = lrun.LOADED
            rep = K.check_load(fills=(0xA5,), sequence=(1,))
            self.assertEqual(rep['failures'], [])
            out = tmp / 'frames.json'
            code = F8.main(['--levels', 'loaded', '--frames',
                            'tour-01,synth-flat', '--fills', 'a5',
                            '--json', str(out), '--no-build'])
            self.assertEqual(code, 0)
            res = json.loads(out.read_text())
            self.assertEqual([r['frame'] for r in res], ['tour-01'])
            self.assertEqual(res[0]['problems'], [])
            self.assertTrue((tmp / 'loaded' / 'src').exists())
        finally:
            lrun.LOADED, FS.LEVEL_HOOK = saved
            K.LOADED = lrun.LOADED
            shutil.rmtree(str(tmp), ignore_errors=True)


# ---------------------------------------------------------------------------
# Planted bugs (docs/LEVELS.md 5.7, stage B's)
# ---------------------------------------------------------------------------

@needs_build
class Planted(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='tmp-m9-plant-',
                                         dir=str(BUILD)))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def failures(self, bugs, sequence=(1,)):
        from native import level_check as K
        obj = planted_obj(self.tmp, bugs)
        rep = K.check_load(fills=(0xA5,), sequence=sequence,
                           keep_loaded=False, obj=obj)
        return rep['failures']

    def test_box_without_the_overflow_flip(self):
        # (no E1 line spans 32,768 units: the poked lines show it)
        obj = planted_obj(self.tmp, [(
            'lgeom.s', """        sbc LW_LC + 5,x
        bvc :+
        eor #$80
:       bmi @lt""", """        sbc LW_LC + 5,x
        bmi @lt""")])
        self.assertTrue(synthetic_run(self, obj))

    def test_halfsum_without_the_sign(self):
        f = self.failures([('lgeom.s', """asr:    sta LG_A+3
        cmp #$80""", """asr:    sta LG_A+3
        clc""")])
        self.assertTrue(any('differs from window.img' in x or 'sound' in x
                            for x in f), f)

    def test_line_twice_in_a_sector_that_is_both_sides(self):
        f = self.failures([('lgeom.s', """        cmp LG_F
        beq :+
        jsr put_entry
:       jsr pf_pb_inc""", """        cmp LG_F
        jsr put_entry           ; (planted: the back even if the front)
        jsr pf_pb_inc"""), ('lgeom.s', """:       lda LG_B
        cmp LG_F
        beq :+
        tax""", """:       lda LG_B
        cmp LG_F
        nop                     ; (planted)
        nop
        tax""")])
        self.assertTrue(any('differs from window.img' in x for x in f), f)

    def test_flood_walked_first_to_last(self):
        f = self.failures([('lgeom.s', """@lines: jsr lines_src           ; the lines, from the last
        lda LG_N
        sta LG_I
        lda LG_N+1
        sta LG_I+1
@line:  lda LG_I
        ora LG_I+1
        jeq @index
        lda LG_I
        bne :+
        dec LG_I+1
:       dec LG_I
""", """@lines: jsr lines_src           ; (planted: first to last)
        lda #$FF
        sta LG_I
        sta LG_I+1
@line:  inc LG_I
        bne :+
        inc LG_I+1
:       lda LG_I
        cmp LG_N
        bne :+
        lda LG_I+1
        cmp LG_N+1
        jeq @index
:
""")])
        self.assertTrue(any('LVG1' in x or 'bank %d' % LL.LVG1 in x or
                            'flood' in x for x in f), f)

    def test_stray_store_into_lvseg(self):
        f = self.failures([('lgeom.s', """        jsr get_be2
        lda LW_BE
        and LW_BE+1""", """        jsr get_be2
        lda FA_SRC              ; (planted: the word written back)
        sta FA_DST
        lda FA_SRC+1
        sta FA_DST+1
        lda #<LW_BE
        ldx #>LW_BE
        ldy #2
        jsr putw
        lda LW_BE
        and LW_BE+1""")])
        self.assertTrue(any('stray CPU writes' in x and 'aux %d' % R.LVSEG
                            in x for x in f), f)
        self.assertFalse(any('window.img' in x for x in f), f)

    def test_variants_not_undone(self):
        f = self.failures([('lload.s', """        lda LV_VARMAP
        beq @apply""", """        lda LV_VARMAP
        bra @apply""")], sequence=(1, 7, 1))
        # the first load has nothing to undo; the second finds the
        # first's variants in its slots, the third the second's
        self.assertFalse(any('load 1 ' in x for x in f), f)
        self.assertTrue(any('load 2 (E1M7)' in x for x in f), f)
        self.assertTrue(any('load 3 (E1M1)' in x for x in f), f)

    def test_varmap_not_set(self):
        f = self.failures([('lload.s', """        lda LP_ARG
        sta LV_VARMAP
        rts""", """        lda LP_ARG
        nop
        nop
        rts""")], sequence=(1, 7, 1))
        self.assertTrue(any('LV_VARMAP' in x or 'load 3' in x for x in f), f)

    def test_request_without_its_last_descriptor(self):
        f = self.failures([('lload.s', """        jsr far_get
        clc                     ; the next request""", """        jsr far_get
        jsr planted_drop
        clc                     ; the next request"""), ('lload.s', """        brk
        .byte 0
""", """        brk
        .byte 0
planted_drop:                   ; (planted: the last descriptor dropped)
        dec LW_REQ + REQ_HEAD - 3
        sec
        lda LW_REQ + 10
        sbc #16
        sta LW_REQ + 10
        lda LW_REQ + 11
        sbc #0
        sta LW_REQ + 11
        rts
""")])
        self.assertTrue(f)

    def test_colormap_b_through_a(self):
        f = self.failures([('lgeom.s', """        lda LW_CMB,x""",
                            """        lda LW_CMA,x""")])
        self.assertTrue(any('bank %d $' % LL.LVC in x or 'main $' in x
                            for x in f), f)

    def test_boot_one_bank_off(self):
        from native import ldisk, lrun
        bd = ldisk.disk_writer()
        if not bd.DEFAULT_MASTER.is_file():
            self.skipTest('needs appletini-one\'s ProDOS')
        obj = planted_obj(self.tmp, [('lboot.s', """        lda hdr
        sta RWBANK              ; a RamWorks bank""", """        lda hdr
        cmp #9                  ; (planted: bank 9 into bank 10)
        bne :+
        inc a
:       sta RWBANK              ; a RamWorks bank""")])
        disk = ldisk.build(obj, maps=(1,))
        work = self.tmp / 'disk'
        r = ldisk.check(disk, work, 'f121')
        self.assertTrue(any('the boot left' in x or 'window.img' in x
                            for x in r['problems']), r['problems'])
        del lrun

    def test_frames_see_the_subsector_sectors(self):
        """Acceptance 2's check can fail: a GROUP that gives every
        subsector sector 0 (the only renderer-visible byte the 65C02
        computes), its level read back, a frame against ref816."""
        from native import frame8 as F8, level_check as K, lrun
        from native import framestate as FS
        if not have_frames():
            self.skipTest('needs the frames of rendercap.py')
        obj = planted_obj(self.tmp, [('lgeom.s', """@side:  jsr sidesec_be          ; its sector, into the subsector's record
        sta LW_BE+6""", """@side:  jsr sidesec_be          ; its sector, into the subsector's record
        lda #0                  ; (planted)
        sta LW_BE+6""")])
        saved = (lrun.LOADED, FS.LEVEL_HOOK)
        try:
            lrun.LOADED = self.tmp / 'loaded'
            K.LOADED = lrun.LOADED
            rep = K.check_load(fills=(0xA5,), sequence=(1,), obj=obj)
            self.assertTrue(rep['failures'])
            self.assertTrue((lrun.LOADED / 'e1m1.img').exists())
            code = F8.main(['--levels', 'loaded', '--frames', 'tour-01',
                            '--fills', 'a5', '--no-build'])
            self.assertEqual(code, 1)
        finally:
            lrun.LOADED, FS.LEVEL_HOOK = saved
            K.LOADED = lrun.LOADED
