"""Tests of tools/v816/prodos.py."""

import unittest

import support
from v816 import prodos

BLOCK = prodos.BLOCK


def pattern(length, seed):
    """`length` bytes that differ from block to block."""
    return bytes((seed + i + (i >> 9) * 7) & 0xff for i in range(length))


class SyntheticVolume(unittest.TestCase):
    def setUp(self):
        self.small = pattern(100, 1)
        self.medium = pattern(3 * BLOCK + 17, 2)
        self.large = pattern(300 * BLOCK, 3)
        builder = support.VolumeBuilder('UNIT.TEST', 400)
        builder.add_file('SEED', self.small, 10, file_type=4)
        builder.add_file('SAPLING', self.medium, 11, aux_type=0x6000)
        builder.add_file('TREE', self.large, 20)
        for number in range(14):        # fill a second directory block
            builder.add_file('F%d' % number, b'', 330 + number)
        builder.add_file('LAST', b'last', 350)
        self.volume = prodos.Volume(builder.build())

    def test_volume_header(self):
        self.assertEqual(self.volume.name, 'UNIT.TEST')
        self.assertEqual(self.volume.total_blocks, 400)

    def test_entry_fields(self):
        entry = self.volume.entry('SAPLING')
        self.assertEqual(entry.storage_type, prodos.STORAGE_SAPLING)
        self.assertEqual(entry.length, len(self.medium))
        self.assertEqual(entry.aux_type, 0x6000)
        self.assertEqual(entry.file_type, 6)
        self.assertEqual(self.volume.entry('SEED').file_type, 4)

    def test_all_storage_types_read_back(self):
        self.assertEqual(self.volume.read_file('SEED'), self.small)
        self.assertEqual(self.volume.read_file('SAPLING'), self.medium)
        self.assertEqual(self.volume.read_file('TREE'), self.large)

    def test_data_blocks(self):
        self.assertEqual(self.volume.data_blocks('SEED'), [10])
        self.assertEqual(self.volume.data_blocks('SAPLING'),
                         [11, 12, 13, 14])
        self.assertEqual(self.volume.data_blocks('TREE'),
                         list(range(20, 320)))

    def test_directory_chain_is_followed(self):
        self.assertEqual(len(self.volume.files), 18)
        self.assertEqual(self.volume.read_file('LAST'), b'last')

    def test_missing_file(self):
        with self.assertRaises(prodos.ProdosError):
            self.volume.entry('NOPE')


class BadImages(unittest.TestCase):
    def test_length_not_in_blocks(self):
        with self.assertRaises(prodos.ProdosError):
            prodos.Volume(bytes(BLOCK * 8 + 1))

    def test_empty(self):
        with self.assertRaises(prodos.ProdosError):
            prodos.Volume(b'')

    def test_no_volume_header(self):
        with self.assertRaises(prodos.ProdosError):
            prodos.Volume(bytes(BLOCK * 8))

    def test_directory_loop(self):
        image = bytearray(support.VolumeBuilder('LOOP', 16).build())
        image[2 * BLOCK + 2] = 2        # the next block of block 2 is 2
        with self.assertRaises(prodos.ProdosError):
            prodos.Volume(bytes(image))

    def test_block_outside_image(self):
        volume = prodos.Volume(support.VolumeBuilder('SMALL', 16).build())
        with self.assertRaises(prodos.ProdosError):
            volume.block(16)


@support.needs_release
class ReleaseVolume(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.volume = prodos.Volume(support.RELEASE_IMAGE.read_bytes())

    def test_volume(self):
        self.assertEqual(self.volume.name, 'DOOM')
        self.assertEqual(self.volume.total_blocks, 5208)
        self.assertEqual(
            list(self.volume.files),
            ['DOOM.BOOT', 'DOOM.DATA', 'DOOM.SETTINGS', 'README'])

    def test_loader_file(self):
        entry = self.volume.entry('DOOM.BOOT')
        self.assertEqual((entry.length, entry.aux_type), (3072, 0x6000))
        self.assertEqual(self.volume.data_blocks('DOOM.BOOT'),
                         list(range(8, 14)))

    def test_data_file_is_contiguous(self):
        blocks = self.volume.data_blocks('DOOM.DATA')
        self.assertEqual(self.volume.entry('DOOM.DATA').storage_type,
                         prodos.STORAGE_TREE)
        # block 14 is the index block of DOOM.BOOT; the header's first
        # segment starts at block 15
        self.assertEqual(blocks, list(range(15, 15 + 4908)))

    def test_readme_is_text(self):
        text = self.volume.read_file('README')
        self.assertTrue(text.startswith(b'Doom for the Apple IIgs\r'))


if __name__ == '__main__':
    unittest.main()
