"""Milestone 9, stage A: the level converter and the store (docs/LEVELS.md
6.1; tools/native/maplumps.py, umodel.py, wadconv.py, lderive.py,
lstore.py, llayout.py, setupcap.py, level_check.py).

Without build/: the map transforms on hand-made lumps, the column memory's
allocator on a synthetic window, the static derivations' rules, the store
format's round trips and the memory-API rules, the generated scripts and
the setups found in a mark log, the bank map.

With the release, DOOM1.WAD and the link map: each map's lump image equals
the store's decoded units, and each game map lump the release's.

With the setup captures (python3 tools/native/setupcap.py): docs/LEVELS.md
5.3 items 1-6 on E1M1 and E1M7 (all their W dumps and level sources), the
derivations against their R dumps, and the store loaded on the host
(E1M1, E1M7, E1M1: the variants undone) equal to the window and, read
back, to levelconv.py's levels. Then that the checks fail: bugs planted in
scratch copies of the modules (docs/LEVELS.md 5.7).
"""

import contextlib
import importlib.util
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

from native import lderive as LD, llayout as LL, lstore as S, \
    maplumps as ML, rlayout as R, setupcap as SC, umodel as U  # noqa: E402

BUILD = support.ROOT / 'build'
HAVE_RELEASE = U.RELEASE.exists() and U.WAD_PATH.exists() and \
    U.LINKMAP.exists()
needs_release = unittest.skipUnless(
    HAVE_RELEASE, 'needs build/release, build/upstream/data/DOOM1.WAD and '
    'build/linkmap.json: run python3 tools/fetch_upstream.py and python3 '
    'tools/v816/imgmatch.py')


def have_setups() -> bool:
    if not HAVE_RELEASE:
        return False
    names = {d.name for d in SC.setup_dirs()}
    return {'tour-sk2-01', 'tour-sk2-08'} <= names


needs_setups = unittest.skipUnless(
    have_setups(), 'needs the setup captures: run python3 '
    'tools/native/setupcap.py (and the release, the WAD, the link map)')


def planted(tmp: Path, module, edits, name=None):
    """A scratch copy of a module with the edits, imported."""
    path = tmp / ((name or module.__name__.split('.')[-1]) + '_planted.py')
    text = Path(module.__file__).read_text()
    # the copy finds the tree (build/, tools/) as the original does
    text = text.replace('Path(__file__)', 'Path(%r)' % module.__file__)
    for old, new in edits:
        if text.count(old) != 1:
            raise AssertionError('the bug no longer applies: %r' % old)
        text = text.replace(old, new)
    path.write_text(text)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Without build/
# ---------------------------------------------------------------------------

def thing(x, y, angle, kind, options):
    return struct.pack('<hhhhh', x, y, angle, kind, options)


def side30(toff, roff, top, bottom, mid, sector):
    def n(s):
        return s.encode().ljust(8, b'\0')
    return struct.pack('<hh', toff, roff) + n(top) + n(bottom) + n(mid) + \
        struct.pack('<h', sector)


class Transforms(unittest.TestCase):
    def test_things_filtered_and_packed(self):
        raw = thing(10, -20, 90, 1, 7) + thing(0, 0, 0, 2, 7) + \
            thing(5, 5, 180, 3004, 16 | 4) + thing(1, 2, 315, 3001, 3) + \
            thing(3, 4, 0, 11, 7)
        out = ML.things(raw)
        self.assertEqual(len(out), 16)
        self.assertEqual(struct.unpack('<hhhbb', out[:8]), (10, -20, 1, 2, 7))
        self.assertEqual(struct.unpack('<hhhbb', out[8:]),
                         (1, 2, 3001, 7, 3))

    def test_sides_are_packed_and_specials_keep_theirs(self):
        verts = [(0, 0), (64, 0), (64, 64)]
        raw = struct.pack('<HHhhhHH', 0, 1, 1, 0, 0, 0, 0xFFFF) + \
            struct.pack('<HHhhhHH', 1, 2, 4, 0, 0, 1, 2) + \
            struct.pack('<HHhhhHH', 2, 0, 1, 11, 3, 3, 0xFFFF)
        lines = ML.lines_of(raw, verts)
        names = ['-', 'STARTAN3', 'DOOR1']
        sides = ML.sides_of(side30(0, 0, '-', '-', 'STARTAN3', 0) * 2 +
                            side30(8, 300, 'DOOR1', '-', '-', 1) +
                            side30(0, 0, '-', '-', 'STARTAN3', 0), names)
        self.assertEqual(sides[2][1], ML.low(300))
        packed_lines, packed = ML.pack_sides(lines, sides)
        # lines 0 and 1 share the identical side; line 2 (special 11) gets
        # its own copy of it
        self.assertEqual([ln[4] for ln in packed_lines], [0, 0, 2])
        self.assertEqual(packed_lines[1][5], 1)
        self.assertEqual(len(packed), 3)
        self.assertEqual(packed[2], packed[0])

    def test_segs_back_sector(self):
        verts = [(0, 0), (64, 0)]
        lines = [[0, 0, 64, 0, 0, 1, 4, 0, 0], [0, 0, 64, 0, 0, 1, 0, 0, 0]]
        sides = [(0, 0, 0, 0, 0, 3), (0, 0, 0, 0, 0, 5)]
        raw = struct.pack('<HHhHhh', 0, 1, 0, 0, 0, 0) + \
            struct.pack('<HHhHhh', 0, 1, 0, 0, 1, 0) + \
            struct.pack('<HHhHhh', 0, 1, 0x7000, 1, 0, 0)
        out = ML.segs(raw, verts, lines, sides)
        recs = [struct.unpack_from('<hhhhhHHHbb', out, 18 * i)
                for i in range(3)]
        self.assertEqual(recs[0][8:], (3, 5))
        self.assertEqual(recs[1][8:], (5, 3))
        self.assertEqual(recs[2][8:], (3, -1))      # not ML_TWOSIDED
        self.assertEqual(recs[2][5], 0xB000)        # angle + $4000

    def test_ssectors_in_order(self):
        self.assertEqual(ML.ssectors(struct.pack('<hhhh', 3, 0, 2, 3)),
                         bytes([3, 2]))
        with self.assertRaises(ML.LumpError):
            ML.ssectors(struct.pack('<hhhh', 3, 0, 2, 4))

    def test_blockmap_shares_suffixes(self):
        lists = [[1, 2, 3], [2, 3], [], [7]]
        head = struct.pack('<hhhh', -64, -64, 2, 2)
        body = bytearray()
        offs = []
        at = 4 + len(lists)
        for lst in lists:
            offs.append(at + len(body) // 2)
            body += struct.pack('<h', 0) + b''.join(
                struct.pack('<h', v) for v in lst) + struct.pack('<h', -1)
        raw = head + struct.pack('<4H', *offs) + bytes(body)
        out = ML.blockmap(raw)
        o = struct.unpack_from('<4H', out, 8)
        # [1, 2, 3] stored first; [2, 3] and [] point into it; [7] alone
        self.assertEqual(o[1], o[0] + 1)
        self.assertEqual(o[2], o[0] + 3)
        self.assertNotEqual(struct.unpack_from('<h', out, 2 * o[1])[0], 0)
        for k, lst in enumerate(lists):
            at, got = 2 * o[k] + 2, []
            while struct.unpack_from('<h', out, at)[0] != -1:
                got.append(struct.unpack_from('<h', out, at)[0])
                at += 2
            self.assertEqual(got, lst)

    def test_texture1_and_pnames(self):
        tex = bytearray(struct.pack('<ii', 1, 8))
        tex += b'WALL\0\0\0\0' + struct.pack('<ihhih', 0, 64, 128, 0, 2)
        tex += struct.pack('<hhhhh', 0, 0, 0, 1, 0)
        tex += struct.pack('<hhhhh', 32, -8, 1, 1, 0)
        out = ML.texture1(bytes(tex))
        t = ML.textures(out)[0]
        self.assertEqual((t.name, t.width, t.height), ('WALL', 64, 128))
        self.assertEqual(t.patches, [(0, 0, 0), (32, -8, 1)])
        self.assertEqual(ML.pnames(struct.pack('<i', 1) + b'w13_1\0\0\0'),
                         struct.pack('<i', 1) + b'W13_1\0\0\0')

    def test_flat_numbers_one_to_one(self):
        def sec(f, c):
            return struct.pack('<hh', 0, 128) + f.ljust(8, b'\0') + \
                c.ljust(8, b'\0') + struct.pack('<hhh', 160, 0, 0)
        wad = sec(b'FLOOR4_8', b'F_SKY1') + sec(b'NUKAGE1', b'FLOOR4_8')
        good = struct.pack('<hhhhbbh', 0, 128, 3, -2, -96, 0, 0) + \
            struct.pack('<hhhhbbh', 0, 128, 0, 3, -96, 0, 0)
        self.assertEqual(ML.flat_numbers(wad, good),
                         {'FLOOR4_8': 3, 'F_SKY1': -2, 'NUKAGE1': 0})
        bad = struct.pack('<hhhhbbh', 0, 128, 3, -2, -96, 0, 0) + \
            struct.pack('<hhhhbbh', 0, 128, 0, 4, -96, 0, 0)
        with self.assertRaises(ML.LumpError):
            ML.flat_numbers(wad, bad)


class Allocator(unittest.TestCase):
    """umodel.Columns' colAlloc rules on a synthetic window of three
    banks."""

    def setUp(self):
        self.mem = U.Memory()
        for b in (0x2A, 0x2B):
            self.mem.define(b, 'test')
        banks = [0x2A, 0x2B, 0x2C]
        nxt = {b: 0 for b in range(256)}
        nxt[0x2A], nxt[0x2B] = 0x2B, 0x2C
        self.win = U.Window(banks, nxt, 3)
        self.cold = bytes([0xFF] * 33)

    def cols(self, colstart):
        return U.Columns(self.mem, self.win, colstart, self.cold, [],
                         lambda p: 0, lambda lump: 0)

    def test_hot_column_skips_the_cache_pages_and_a_cold_block_fills_the_hole(
            self):
        c = self.cols(0x2A0800)
        a = c.alloc(0x200, True, 'hot')
        self.assertEqual(a, 0x2A2000)
        self.assertEqual(c.holes, [[0x0800, 0x2000, 0x2A]])
        b = c.alloc(100, False, 'cold')
        self.assertEqual(b, 0x2A0800)
        self.assertEqual(c.holes[0][0], 0x0864)
        # a hot block under $0901 stays where it is
        c2 = self.cols(0x2A0800)
        self.assertEqual(c2.alloc(0x100, True, 'hot'), 0x2A0800)
        self.assertEqual(c2.holes, [])

    def test_next_bank_zeroed_within_overread(self):
        c = self.cols(0x2AFF00)
        self.mem.write(0x2B0010, b'\x55')
        a = c.alloc(0x81, False, 'cold')
        self.assertEqual(a, 0x2B0000)
        self.assertEqual(self.mem.read(0x2B0010, 1), b'\0')
        c3 = self.cols(0x2AFF00)
        self.assertEqual(c3.alloc(0x7F, False, 'fits'), 0x2AFF00)

    def test_lv_zb_skips_a_zeroed_bank(self):
        c = self.cols(0x2A0000)
        c.lv_zb = 0x2B
        self.mem.write(0x2B0000, b'\x77')
        c.zero_bank(0x2B)
        self.assertEqual(c.lv_zb, 0)
        self.assertEqual(self.mem.read(0x2B0000, 1), b'\x77')

    def test_the_holes_kept_are_sixteen(self):
        c = self.cols(0x2A0800)
        for _ in range(18):
            c.alloc(0x2000 - 0x0800, True, 'hot')
            c.colmem = (c.colmem & 0xFF0000) | 0x0800
        self.assertEqual(len(c.holes), U.CM_MAX)
        self.assertEqual(len(c.lost_holes), 2)


class Derivations(unittest.TestCase):
    def test_box_is_a_true_signed_compare(self):
        f = LD.line_fields([0, -20000, 10, 20000, 0, 0xFFFF, 1, -1, 5])
        self.assertEqual(f['bbox'], [20000, -20000, 0, 10])
        self.assertEqual(f['dy'], LD.s16(40000))
        self.assertEqual(f['special'], -1)
        self.assertEqual(f['slopetype'], LD.ST_NEGATIVE)
        self.assertEqual(LD.line_fields([0, 0, 0, 5, 0, 0, 0, 0, 0])
                         ['slopetype'], LD.ST_VERTICAL)
        self.assertEqual(LD.line_fields([0, 0, 5, 5, 0, 0, 0, 0, 0])
                         ['slopetype'], LD.ST_POSITIVE)

    def test_half_is_arithmetic(self):
        self.assertEqual(LD.half(-3), -2)
        self.assertEqual(LD.half(0x80000000), -0x40000000)
        self.assertEqual(LD.half(5), 2)

    def test_planted_box_without_the_flip_is_caught(self):
        with tempfile.TemporaryDirectory(prefix='tmp-level-') as t:
            bad = planted(Path(t), LD, (('    if v1y < v2y:',
                                         '    if LD_s16(v1y - v2y) < 0:'),
                                        ('ST_HORIZONTAL, ST_VERTICAL',
                                         'LD_s16 = lambda v: (v & 0xFFFF) - '
                                         '(0x10000 if v & 0x8000 else 0)\n'
                                         'ST_HORIZONTAL, ST_VERTICAL')))
            ln = [0, -20000, 10, 20000, 0, 0xFFFF, 1, -1, 5]
            self.assertNotEqual(bad.line_fields(ln)['bbox'],
                                LD.line_fields(ln)['bbox'])

    def test_planted_half_toward_zero_is_caught(self):
        with tempfile.TemporaryDirectory(prefix='tmp-level-') as t:
            bad = planted(Path(t), LD, (('    return s32(v) >> 1',
                                         '    return int(s32(v) / 2)'),))
            self.assertNotEqual(bad.half(-3), LD.half(-3))


class StoreFormat(unittest.TestCase):
    def test_bank_file_round_trip(self):
        segs = [(9, 0x0200, b'abc'), (77, 0xBFFF, b'z')]
        data = S.bank_file(segs)
        self.assertEqual(data[:4], b'A2DM')
        self.assertEqual(len(data), 256 + 4)
        self.assertEqual(S.read_bank_file(data), segs)
        with self.assertRaises(S.StoreError):
            S.bank_file([(127, 0x0200, b'a')])
        with self.assertRaises(S.StoreError):
            S.bank_file([(9, 0xBFFF, b'ab')])

    def test_requests_split_and_private(self):
        copies = [((1, 7, 0x0200), (1, 6, 0x0200), 30000, 0)] * 2 + \
            [((1, 7, 0x0200), (0, 0, 0x2000), 4, 0)] * 20
        reqs = S.requests_of(copies)
        sizes = [sum(struct.unpack_from('<H', d, 10)[0] for d in r)
                 for r in reqs]
        self.assertEqual(sizes[0], LL.REQUEST_BYTES)    # split in the copy
        self.assertTrue(all(s <= LL.REQUEST_BYTES for s in sizes))
        self.assertTrue(all(1 <= len(r) <= LL.AMEM_MAX for r in reqs))
        self.assertEqual(sum(sizes), 60000 + 80)
        self.assertEqual(sum(len(r) for r in reqs), 23)
        last = reqs[-1][-1]
        self.assertEqual(last[1] & 1, 1)        # main: PRIVATE
        self.assertEqual(reqs[0][0][1] & 1, 0)
        with self.assertRaises(S.StoreError):
            S.descriptor(1, (1, 7, 0x0200), (1, 6, 0xBF00), 0x200)

    def test_host_machine_checks_requests(self):
        hm = S.HostMachine([], (77, 0x0200))
        d = bytearray(S.descriptor(1, (1, 7, 0x0200), (0, 0, 0x2000), 4))
        hm.request([bytes(d)])
        d[1] = 0                                # no PRIVATE to main
        with self.assertRaises(S.StoreError):
            hm.request([bytes(d)])
        ov = S.descriptor(1, (1, 7, 0x0200), (1, 7, 0x0202), 4)
        with self.assertRaises(S.StoreError):
            hm.request([ov])
        fill = S.descriptor(2, None, (1, 8, 0x0300), 3, 0xAA)
        hm.request([fill])
        self.assertEqual(hm.read(8, 0x0300, 4), b'\xaa\xaa\xaa\xa5')

    def test_program_round_trip(self):
        part = S.Part(4)
        part.steps = [('VARIANTS', 4), ('COPYREQ', 0), ('END', 0)]
        part.requests = [[S.descriptor(2, None, (1, 6, 0x0200), 10, 1)]]
        steps, reqs = S.parse_program(S.program_bytes(part))
        self.assertEqual(steps, [(2, 4), (1, 0), (0, 0)])
        self.assertEqual(reqs, part.requests)

    def test_canonical_is_the_most_common(self):
        self.assertEqual(S.canonical({1: b'a', 2: b'b', 3: b'b'}), b'b')
        self.assertEqual(S.canonical({4: b'a', 2: b'b'}), b'b')


class Scripts(unittest.TestCase):
    def test_skill_scripts(self):
        for k in range(5):
            text = SC.tour_text(k)
            self.assertIn('wait m_menu65.s:itemOn == %d within 2s' % k, text)
            self.assertIn('wait _g_gameskill == %d within 10s' % k, text)
            self.assertEqual(text.count('press y'), 1 if k == 4 else 0)
            moves = text.count('press up') + text.count('press down')
            self.assertEqual(moves, abs(k - 2))
        self.assertIn('poke word _g_player+4 2', SC.reborn_text(6))

    def test_setups_from_marks(self):
        from ref816 import marks
        r = {'setup': 1, 'mapend': 2, 'done': 3, 'tex': 4}
        log = [marks.Entry('mark', '%06X' % a, 0, c, 0) for a, c in (
            (2, 5), (1, 10), (4, 11), (2, 12), (4, 13), (3, 14), (2, 15),
            (4, 16), (1, 20), (2, 21), (2, 22))]
        found = SC.setups_of(log, r)
        self.assertEqual(len(found), 2)
        self.assertEqual((found[0].r_hit, found[0].w_hit, found[0].made_load,
                          found[0].made_play), (2, 1, 2, 1))
        self.assertEqual((found[1].r_hit, found[1].w_hit), (4, 0))


class Layout(unittest.TestCase):
    def test_bank_map(self):
        LL.check()
        uses = dict(LL.bank_map())
        # 112 at stage A; stage C's mobj game part takes 3 banks, not 6
        # (docs/LEVELS.md "Stage C as built")
        self.assertEqual(len(uses), 109)
        self.assertEqual(LL.MOBJ, (69, 70, 71))
        self.assertTrue({72, 73, 74} <= set(LL.SPARE))
        self.assertEqual(len(uses) + len(LL.SPARE), LL.BANKS_TOTAL)
        self.assertEqual(len(LL.TEX_BANKS), 31)
        for b in (R.LVSEG, R.LVMAP, R.RENDB, R.SPRT, R.WPRO, R.RTH):
            self.assertIn(b, uses)
        self.assertNotIn(127, uses)

    def test_static_manifest_loads(self):
        from bridge.layout import Manifest
        m = Manifest(LL.manifest_static())
        self.assertEqual(sorted(m.kinds), ['line', 'node', 'sector', 'seg',
                                           'side', 'subsector'])


# ---------------------------------------------------------------------------
# With the release
# ---------------------------------------------------------------------------

@needs_release
class Release(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = U.game_data()

    def test_maps_lumps_and_images(self):
        win = U.window(self.gd.rel)
        for m in range(1, 10):
            ld = U.load(self.gd, m)         # its lump image = the units
            marker = self.gd.rel.index('E1M%d' % m)
            for k, name in enumerate(ML.GAME_ML):
                ref = U.release_lump(self.gd.rel, m, win, marker + 1 + k)
                self.assertEqual(ld.game.lumps[name], ref,
                                 'E1M%d %s' % (m, name))

    def test_window_banks(self):
        win = U.window(self.gd.rel)
        self.assertEqual(win.banks[:22], list(range(0x2A, 0x40)))
        self.assertEqual(win.banks[22:24], [0x0E, 0x0F])
        self.assertEqual(win.banks[24], 0x40 + self.gd.rel.store_banks)
        self.assertEqual(win.next[win.banks[win.pict - 1]], 0)

    def test_planted_blockmap_without_sharing_is_caught(self):
        with tempfile.TemporaryDirectory(prefix='tmp-level-') as t:
            ml = planted(Path(t), ML, ((
                '        for prev, at in stored:',
                '        for prev, at in []:'),), 'maplumps')
            game = ml.GameMap(self.gd.wad, 1, self.gd.tex_names,
                              U.load(self.gd, 1).flat_numbers)
            win = U.window(self.gd.rel)
            marker = self.gd.rel.index('E1M1')
            ref = U.release_lump(self.gd.rel, 1, win, marker + 9)
            self.assertNotEqual(game.lumps['BLOCKMAP'], ref)


# ---------------------------------------------------------------------------
# With the setup captures
# ---------------------------------------------------------------------------

@needs_setups
class Conversion(unittest.TestCase):
    """docs/LEVELS.md 5.3 items 1-6 on E1M1 and E1M7."""

    def test_items_1_to_6(self):
        from native import level_check
        with contextlib.redirect_stdout(io.StringIO()):
            report = level_check.check_conv([1, 7], write_ref=False)
        self.assertEqual(report['failures'], [])
        self.assertGreaterEqual(len(report['w']), 12)
        self.assertGreaterEqual(sum(1 for r in report['sources'].values()
                                    if r['ok']), 6)

    def test_derivations_against_the_r_dumps(self):
        with contextlib.redirect_stdout(io.StringIO()):
            report = LD.check_all([1, 7])
        self.assertEqual(report['failures'], [])


def first_w(gamemap: int) -> Path:
    for d in SC.setup_dirs(['tour-sk2']):
        if json.loads((d / 'setup.json').read_text())['gamemap'] == gamemap:
            return d
    raise AssertionError('no tour-sk2 setup of E1M%d' % gamemap)


@needs_setups
class Planted(unittest.TestCase):
    """Bugs planted in scratch copies, each caught by its check."""

    @classmethod
    def setUpClass(cls):
        from native import levelconv as LC, level_check, wadconv as WC
        cls.LC, cls.LCK, cls.WC = LC, level_check, WC
        cls.sym = LC.symbols()
        cls.refs = {}
        for m in (3, 7):
            mem = LC.load_memory(first_w(m) / 'w.ram.z')
            cls.refs[m] = (mem, LC.convert(mem, cls.sym, 'w'))

    def compare_with(self, umod, wmod, m):
        gd = umod.game_data()
        ld = umod.load(gd, m)
        level, facts = wmod.convert(gd, ld)
        mem, ref = self.refs[m]
        self.LCK.compare(level, facts, ref)
        umod.compare_window(ld, mem.read)

    def test_the_unplanted_modules_pass(self):
        self.compare_with(U, self.WC, 7)

    def test_tail_off_by_one(self):
        with tempfile.TemporaryDirectory(prefix='tmp-level-') as t:
            w = planted(Path(t), self.WC, ((
                '            banks.put(bank, at, m.read(address, need))',
                '            banks.put(bank, at, m.read(address, size) + '
                'm.read(address + size + 1, TAIL))'),
            ), 'wadconv')
            with self.assertRaises(self.LCK.CheckError):
                self.compare_with(U, w, 7)

    def test_cold_block_after_its_hole(self):
        with tempfile.TemporaryDirectory(prefix='tmp-level-') as t:
            u = planted(Path(t), U, (('        if not hot:\n            for h',
                                      '        if False:\n            for h'),
                                     ), 'umodel')
            with self.assertRaises((self.LCK.CheckError, U.ModelError,
                                    u.ModelError)):
                self.compare_with(u, self.WC, 7)

    def test_without_more_columns(self):
        with tempfile.TemporaryDirectory(prefix='tmp-level-') as t:
            u = planted(Path(t), U, (('    cols.more(gd.switchlist, '
                                      'gd.basepic)', '    pass'),), 'umodel')
            with self.assertRaises((self.LCK.CheckError, U.ModelError,
                                    u.ModelError)):
                self.compare_with(u, self.WC, 7)

    def test_without_the_more_banks_test(self):
        with tempfile.TemporaryDirectory(prefix='tmp-level-') as t:
            u = planted(Path(t), U, (('            if index is None or '
                                      'index >= MORE_BANKS:',
                                      '            if index is None:'),),
                        'umodel')
            with self.assertRaises((self.LCK.CheckError, U.ModelError,
                                    u.ModelError)):
                self.compare_with(u, self.WC, 3)

    def test_flood_walked_first_to_last(self):
        from bridge import upstream
        state = upstream.Reader(self.LC.load_memory(
            first_w(7) / 'r.ram.z')).read()
        gd = U.game_data()
        game = U.load(gd, 7).game
        LD.compare(game, state)
        with tempfile.TemporaryDirectory(prefix='tmp-level-') as t:
            ld = planted(Path(t), LD, ((
                '        for i in range(len(lines) - 1, -1, -1):',
                '        for i in range(len(lines)):'),), 'lderive')
            with self.assertRaises(ld.DeriveError):
                ld.compare(game, state)
            ld2 = planted(Path(t), LD, ((
                '            if back is not None and back != front:',
                '            if back is not None:'),), 'lderive2')
            with self.assertRaises(ld2.DeriveError):
                ld2.compare(game, state)


@needs_setups
class Store(unittest.TestCase):
    """The store loaded on the host: E1M1, E1M7, E1M1 (the variants
    undone), each against its window and, read back, levelconv.py's level
    of its W dump; planted bugs of the variant step and the tables."""

    @classmethod
    def setUpClass(cls):
        from native import levelconv as LC
        cls.LC = LC
        cls.tmp = tempfile.TemporaryDirectory(prefix='tmp-level-store-')
        root = Path(cls.tmp.name)
        cls.gd = U.game_data()
        cls.result = S.build(cls.gd, (1, 7))
        cls.meta = S.write(cls.result, root / 'store')
        sym = LC.symbols()
        cls.refs = {}
        for m in (1, 7):
            ref = LC.convert(LC.load_memory(first_w(m) / 'w.ram.z'), sym, 'w')
            LC.write(ref, root / 'ref' / str(m))
            cls.refs[m] = root / 'ref' / str(m)
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def machine(self, store=S):
        files = [self.root / 'store' / n for n in sorted(self.meta['files'])]
        return store.HostMachine(files, tuple(self.meta['directory']))

    def run_loads(self, hm, store=S):
        for m in (1, 7, 1):
            hm.load(m)
            d = self.root / 'store' / ('e1m%d' % m)
            store.compare_window(hm, d)
            store.readback(hm, m, d, self.refs[m])

    def test_loads_window_and_readback(self):
        self.run_loads(self.machine())
        t = self.meta['tally']
        self.assertGreater(t['texel_store']['blocks'], 50)

    def test_planted_variant_not_undone(self):
        with tempfile.TemporaryDirectory(prefix='tmp-level-') as t:
            s = planted(Path(t), S, ((
                "        old = self.main[LL.LV_VARMAP]\n        if old:",
                "        old = self.main[LL.LV_VARMAP]\n        if False:"),
            ), 'lstore')
            with self.assertRaises(s.StoreError):
                self.run_loads(self.machine(s), s)

    def test_planted_varmap_not_set(self):
        with tempfile.TemporaryDirectory(prefix='tmp-level-') as t:
            s = planted(Path(t), S, ((
                '        self.main[LL.LV_VARMAP] = gamemap',
                '        pass'),), 'lstore')
            with self.assertRaises(s.StoreError):
                self.run_loads(self.machine(s), s)

    def test_planted_txbank_and_phdr(self):
        for old, new in (
                ("        txbank[t], txlo[t], txhi[t] = bank, base & 0xFF, "
                 "base >> 8", "        txbank[t], txlo[t], txhi[t] = bank, "
                 "(base + 128) & 0xFF, (base + 128) >> 8"),
                ("    index = {lump: k + 1 for k, lump in enumerate(order)}",
                 "    index = {lump: k + 2 for k, lump in enumerate(order)}")):
            with tempfile.TemporaryDirectory(prefix='tmp-level-') as t:
                s = planted(Path(t), S, ((old, new),), 'lstore')
                try:
                    result = s.build(self.gd, (1, 7))
                    meta = s.write(result, Path(t) / 'store')
                except s.StoreError:
                    continue            # (refused while built: caught)
                files = [Path(t) / 'store' / n for n in sorted(meta['files'])]
                hm = s.HostMachine(files, tuple(meta['directory']))
                with self.assertRaises(s.StoreError):
                    for m in (1, 7):
                        hm.load(m)
                        s.readback(hm, m, Path(t) / 'store' / ('e1m%d' % m),
                                   self.refs[m])


if __name__ == '__main__':
    unittest.main()
