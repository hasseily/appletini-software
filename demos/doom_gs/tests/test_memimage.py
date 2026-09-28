"""Tests of tools/v816/memimage.py."""

import shutil
import tempfile
import unittest
from pathlib import Path

import support
from v816 import hdv, memimage


class Loading(unittest.TestCase):
    def setUp(self):
        self.image = memimage.MemoryImage()

    def test_read_back(self):
        self.image.load(0x031000, b'hello', 'greeting')
        self.assertEqual(self.image.read(0x031000, 5), b'hello')
        self.assertEqual(self.image.read(0x031001, 3), b'ell')

    def test_region_at(self):
        first = self.image.load(0x020000, bytes(16), 'first')
        second = self.image.load(0x020010, bytes(16), 'second')
        self.assertEqual(self.image.region_at(0x02000f), first)
        self.assertEqual(self.image.region_at(0x020010), second)
        self.assertEqual(self.image.region_at(0x02001f).label, 'second')
        self.assertIsNone(self.image.region_at(0x020020))
        self.assertIsNone(self.image.region_at(0x7f0000))

    def test_hole_is_not_zero_bytes(self):
        self.image.load(0x001000, bytes(4))
        self.image.load(0x001008, bytes(4))
        with self.assertRaises(KeyError):
            self.image.read(0x001000, 12)
        with self.assertRaises(KeyError):
            self.image.read(0x050000, 1)

    def test_load_across_banks(self):
        data = bytes(range(256)) * 600          # 153,600 bytes
        region = self.image.load(0x10ff00, data, 'wad')
        self.assertEqual(self.image.banks(), [0x10, 0x11, 0x12, 0x13])
        self.assertEqual(self.image.read(0x10ff00, len(data)), data)
        self.assertEqual(self.image.region_at(0x120000), region)
        self.assertEqual(region.end, 0x10ff00 + len(data))
        self.assertEqual(self.image.extents(0x10), [(0x10ff00, 0x110000)])
        self.assertEqual(self.image.extents(0x11), [(0x110000, 0x120000)])
        self.assertEqual(self.image.loaded_bytes(0x13),
                         len(data) - 0x100 - 0x20000)

    def test_later_load_wins_and_overlap_is_recorded(self):
        self.image.load(0x040000, b'AAAAAAAA')
        self.image.load(0x040004, b'BBBBBBBB')
        self.assertEqual(self.image.read(0x040000, 12), b'AAAABBBBBBBB')
        self.assertEqual(self.image.region_at(0x040003).index, 0)
        self.assertEqual(self.image.region_at(0x040004).index, 1)
        self.assertEqual(self.image.overlaps,
                         [memimage.Overlap(0x040004, 4, 0, 1)])

    def test_extents_join_adjacent_loads(self):
        self.image.load(0x000200, bytes(0x100))
        self.image.load(0x000300, bytes(0x100))
        self.image.load(0x008000, bytes(1))
        self.assertEqual(self.image.extents(0),
                         [(0x000200, 0x000400), (0x008000, 0x008001)])
        self.assertEqual(self.image.extents(1), [])

    def test_outside_address_space(self):
        with self.assertRaises(ValueError):
            self.image.load(0xffff00, bytes(0x101))
        with self.assertRaises(ValueError):
            self.image.load(-1, b'x')
        self.image.load(0xffff00, bytes(0x100))

    def test_bank_bytes_fill(self):
        self.image.load(0x030002, b'\x01\x02')
        bank = self.image.bank_bytes(3, fill=0xea)
        self.assertEqual(len(bank), 0x10000)
        self.assertEqual(bank[:6], b'\xea\xea\x01\x02\xea\xea')
        self.assertEqual(self.image.bank_bytes(9, fill=0xff),
                         b'\xff' * 0x10000)

    def test_from_segments_takes_tuples(self):
        image = memimage.MemoryImage.from_segments(
            [(0x001000, b'ab', 0), (0x002000, b'cd', 2)])
        self.assertEqual(image.region_at(0x002001).index, 1)
        self.assertEqual(image.read(0x001000, 2), b'ab')

    def test_dump(self):
        self.image.load(0x00fffe, b'\x11\x22\x33\x44')
        support.BUILD.mkdir(exist_ok=True)
        directory = tempfile.mkdtemp(prefix='test-dump-',
                                     dir=str(support.BUILD))
        self.addCleanup(shutil.rmtree, directory)
        paths = self.image.dump(str(Path(directory) / 'banks'))
        self.assertEqual([Path(p).name for p in paths],
                         ['bank00.bin', 'bank01.bin'])
        self.assertEqual(Path(paths[0]).read_bytes()[-2:], b'\x11\x22')
        self.assertEqual(Path(paths[1]).read_bytes(),
                         b'\x33\x44' + bytes(0xfffe))


@support.needs_release
class ReleaseMemory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.disk = hdv.load(str(support.RELEASE_IMAGE))
        cls.memory = memimage.MemoryImage.from_segments(cls.disk.segments)

    def test_no_segment_overlaps_another(self):
        self.assertEqual(self.memory.overlaps, [])

    def test_entry_point_is_in_the_first_code_segment(self):
        region = self.memory.region_at(self.disk.entry)
        self.assertEqual(self.disk.segments[region.index].address, 0x030000)

    def test_region_index_is_segment_index(self):
        for segment in self.disk.segments:
            for address in (segment.address, segment.end - 1):
                self.assertEqual(self.memory.region_at(address).index,
                                 segment.index)

    def test_banks(self):
        self.assertEqual(
            self.memory.banks(),
            [0x00, 0x02, 0x03, 0x04, 0x05, 0x10, 0x11, 0x12, 0x1f, 0x20,
             0x2a, 0x2b, 0x2c, 0x2d] + list(range(0x40, 0x5c)))

    def test_loaded_bytes_equal_segment_bytes(self):
        loaded = sum(self.memory.loaded_bytes(bank)
                     for bank in self.memory.banks())
        self.assertEqual(loaded, sum(len(s.data) for s in self.disk.segments))

    def test_unloaded_memory(self):
        self.assertIsNone(self.memory.region_at(0x006000))   # the loader
        self.assertIsNone(self.memory.region_at(0x027b00))   # near BSS
        self.assertIsNone(self.memory.region_at(0xe12000))   # the screen

    def test_segments_read_back(self):
        for segment in self.disk.segments:
            self.assertEqual(
                self.memory.read(segment.address, len(segment.data)),
                segment.data)


if __name__ == '__main__':
    unittest.main()
