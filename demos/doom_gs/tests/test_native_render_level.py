"""Milestone 7, stage A: the native renderer's layout, level and tables
(docs/RENDER.md 1, 3.3; tools/native/rlayout.py, levelconv.py,
rtables.py; the bridge's `stride`).

Without build/: the layout's checks, the pic encoding, the bridge's
strided leaves on hand-made data. With the level sources of
tools/native/rendercap.py (build/native/render/levels/src) and the link
map: levelconv on E1M1 and E1M7 with every check of RENDER.md 1.10, and
rtables with its checks. Then that the checks fail: a slot one column off
planted in a scratch copy of levelconv.py.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

from bridge.layout import Leaf, Manifest  # noqa: E402
from bridge.port import PortReader, PortWriter  # noqa: E402
from native import levelconv, rlayout as R  # noqa: E402

ROOT = support.ROOT
BUILD = ROOT / 'build'
SOURCES = levelconv.SOURCES
LINKMAP = BUILD / 'linkmap.json'


def source(name_glob: str):
    found = sorted(SOURCES.glob(name_glob)) if SOURCES.exists() else []
    return found[0] if found else None


HAVE_SOURCES = LINKMAP.exists() and source('tour-e1m1-*.ram.z') is not None \
    and source('tour-e1m7-*.ram.z') is not None
needs_sources = unittest.skipUnless(
    HAVE_SOURCES, 'needs build/linkmap.json (tools/v816/imgmatch.py) and '
    'the level sources of python3 tools/native/rendercap.py')


class Layout(unittest.TestCase):
    def test_checks_pass(self):
        R.check()
        self.assertLessEqual(R.frame_block_used(), 96)
        for name, at in R.ZP.items():
            self.assertTrue(R.ZP_OV1[0] <= at < R.ZP_OV1[1], name)
        self.assertLessEqual(R.OV1_USED, R.ZP_OV1[1] - R.ZP_OV1[0])
        self.assertEqual(R.VTX_STRIDE & 0xFF, 0)    # far.s adds pages
        self.assertEqual(R.VAL & 0xFF, 0)

    def test_include_has_every_constant(self):
        text = R.include_text()
        for name in ('NODEBASE', 'SECBASE', 'VAL', 'FB', 'VIEWX',
                     'VA_STAMP', 'FRP', 'BS_F', 'FA_SRC', 'SEAM_SOLID',
                     'SEC_VALID', 'ND_BOX1', 'PL_X', 'WBOT'):
            self.assertRegex(text, r'\n%s\s+= \$' % name)

    def test_allocation_overflow_fails(self):
        with self.assertRaises(ValueError):
            R.allocate([('A', 40), ('B', 3)], 0x18, 0x42)

    def test_records_fit_their_banks(self):
        for a in (R.SEGS, R.NODES, R.SUBS, R.SECTORS, R.SIDES):
            self.assertLessEqual(a.end, R.BANK_ROOM[1], a.name)
            self.assertGreaterEqual(a.base, R.BANK_ROOM[0], a.name)
        with self.assertRaises(IndexError):
            R.NODES.address(R.NODES.capacity)

    def test_pics(self):
        self.assertEqual(levelconv.pic_byte(-2, 'x', True), 0xFE)
        self.assertEqual(levelconv.pic_value(0xFE), -2)
        self.assertEqual(levelconv.pic_byte(127, 'x', False), 127)
        for bad, ceiling in ((-2, False), (128, True), (-1, True)):
            with self.assertRaises(levelconv.ConvError):
                levelconv.pic_byte(bad, 'x', ceiling)


class BridgeStride(unittest.TestCase):
    """The bridge's optional stride (RENDER.md 2.3) on hand-made data."""

    def manifest(self, stride):
        leaf = {'path': ['lightlevel'], 'enc': {'enc': 'int', 'bytes': 2,
                                                'signed': False},
                'planes': ['aux:07:8000', 'aux:07:8001']}
        if stride != 1:
            leaf['stride'] = stride
        return Manifest({
            'format': 'bridge-port-layout 1', 'name': 't', 'note': '',
            'symbols': [], 'tables': [], 'lists': {}, 'pools': {},
            'kinds': {'sector': {'capacity': 8,
                                 'count': ['main:03A0', 'main:03A1'],
                                 'leaves': [leaf]}},
            'globals': {'leaves': [{'path': ['g'], 'enc': {
                'enc': 'int', 'bytes': 1, 'signed': False},
                'planes': ['main:03A4']}]}})

    def test_round_trip_with_a_stride(self):
        state = {'format': 'bridge-canonical 1', 'globals': {'g': 1},
                 'objects': {'sector': {i: {'lightlevel': 100 + 300 * i}
                                        for i in range(3)}}}
        mf = self.manifest(16)
        memory = PortWriter(mf).write(state)
        self.assertEqual(memory.u16(7 << 16 | 0x8000 + 32), 700)
        self.assertEqual(memory.u16(7 << 16 | 0x8000 + 16), 400)
        back = PortReader(mf).read(memory)
        self.assertEqual(back['objects']['sector'], state['objects'][
            'sector'])

    def test_no_stride_is_unchanged(self):
        mf = self.manifest(1)
        self.assertNotIn('stride', mf.kinds['sector']['leaves'][0].to_json())
        state = {'format': 'bridge-canonical 1', 'globals': {'g': 1},
                 'objects': {'sector': {0: {'lightlevel': 5},
                                        1: {'lightlevel': 6}}}}
        memory = PortWriter(mf).write(state)
        self.assertEqual(memory.u8(7 << 16 | 0x8001), 6)

    def test_a_bad_stride_is_refused(self):
        with self.assertRaises(ValueError):
            Leaf(('x',), {'enc': 'int', 'bytes': 1, 'signed': False},
                 [0], stride=0)


@needs_sources
class Levels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sym = levelconv.symbols()

    def convert(self, glob):
        path = source(glob)
        memory = levelconv.load_memory(path)
        level = levelconv.convert(memory, self.sym, path.name)
        up = levelconv.Upstream(memory, self.sym)
        return path, memory, level, up

    def test_e1m1(self):
        _, memory, level, up = self.convert('tour-e1m1-*.ram.z')
        c = level.info['counts']
        # RENDER.md 1.2's table
        self.assertEqual((c['sectors'], c['segs'], c['nodes'],
                          c['vertices']), (85, 732, 236, 467))
        self.assertEqual(level.info['bsp_depth'], 18)
        self.assertGreater(levelconv.check_decode(level, up.state), 1500)
        self.assertGreater(levelconv.check_slots(level, memory), 3000)
        self.assertGreater(levelconv.check_bridge(level, up.state), 1000)

    def test_e1m7_and_a_second_dump(self):
        path, memory, level, up = self.convert('tour-e1m7-*.ram.z')
        self.assertEqual(level.info['counts']['nodes'], 466)
        self.assertLessEqual(level.info['bsp_depth'], R.NODEF_DEPTH)
        levelconv.check_decode(level, up.state)
        levelconv.check_slots(level, memory)
        second = levelconv.bridge_dump_of(7)
        if second is None:
            self.skipTest('no bridge tour dump of E1M7 (python3 '
                          'tools/bridge/dumps.py)')
        other = levelconv.Upstream(levelconv.load_memory(second), self.sym)
        self.assertEqual(levelconv.static_fields(up.state),
                         levelconv.static_fields(other.state))

    def test_the_vertex_numbers_are_upstreams_up_to_renaming(self):
        _, _, level, _ = self.convert('tour-e1m1-*.ram.z')
        upv = level.info['upstream_vertex']
        self.assertEqual(len(set(upv)), len(upv))

    def test_a_slot_one_column_off_is_caught(self):
        """A bug planted in a scratch copy of levelconv.py: the slot
        check (RENDER.md 4.5, stage A's first planted bug)."""
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            copy = Path(t) / 'levelconv_bug.py'
            text = (ROOT / 'tools' / 'native' / 'levelconv.py').read_text()
            old = ("            banks.put(bank, base + SLOT * c,\n"
                   "                      slot_source(ptr, '%d:%d' % (t, "
                   "c)))")
            new = ("            banks.put(bank, base + SLOT * ((c + 1) & "
                   "wm),\n                      slot_source(ptr, '%d:%d' "
                   "% (t, c)))")
            self.assertEqual(text.count(old), 1, 'the bug no longer applies')
            copy.write_text(text.replace(old, new))
            spec = importlib.util.spec_from_file_location('levelconv_bug',
                                                          copy)
            bug = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bug)
            memory = bug.load_memory(source('tour-e1m1-*.ram.z'))
            level = bug.convert(memory, self.sym)
            with self.assertRaisesRegex(bug.ConvError, 'slot differs'):
                bug.check_slots(level, memory)


@needs_sources
class Tables(unittest.TestCase):
    def test_tables_and_their_checks(self):
        from native import rtables
        with tempfile.TemporaryDirectory(dir=str(BUILD)) as t:
            out = Path(t)
            ram = rtables.ram_of(source('tour-e1m1-*.ram.z'))
            report = rtables.build(ram, levelconv.symbols(), out)
            self.assertIn('FSTEP entries 512-65535 equal 33554431 / L',
                          report['checks'])
            self.assertEqual(len((out / 'smap.bin').read_bytes()), 64)
            self.assertEqual((out / 'c26rev.bin').read_bytes(),
                             bytes(reversed((out / 'pgt.bin')
                                            .read_bytes()[:85])))
            # an FSTEP entry changed in the RAM: the formula check fails
            bad = bytearray(ram)
            bad[rtables.MM_FSTEP + 2 * 1000] ^= 1
            with self.assertRaisesRegex(rtables.TableError, 'FSTEP'):
                rtables.build(bytes(bad), levelconv.symbols(), out / 'b')


if __name__ == '__main__':
    unittest.main()
