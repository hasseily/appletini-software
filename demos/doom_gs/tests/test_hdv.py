"""Tests of tools/v816/hdv.py: synthetic images, then the release image."""

import hashlib
import struct
import unittest

import support
from v816 import hdv

BLOCK = hdv.BLOCK

# The segment table of the release image: (address, bytes, flags). The
# totals below are those of docs/ARCHITECTURE.md section 0.
RELEASE_SEGMENTS = [
    (0x2a0000, 32768, hdv.SEG_PIC),
    (0x004000, 8192, 0), (0x008000, 512, 0), (0x009000, 5632, 0),
    (0x00ae00, 2560, 0), (0x00ba00, 1024, 0),
    (0x020000, 30208, 0),
    (0x030000, 89600, 0), (0x046000, 2560, 0), (0x046c00, 512, 0),
    (0x048800, 13312, 0), (0x04be00, 12288, 0), (0x050000, 512, 0),
    (0x050800, 6144, 0), (0x052400, 6144, 0), (0x053e00, 4096, 0),
    (0x055000, 3072, 0), (0x056000, 5632, 0), (0x058800, 4096, 0),
    (0x059a00, 16384, 0), (0x05dc00, 5632, 0),
    (0x100000, 178688, 0), (0x1f0000, 131072, 0), (0x2c0000, 130560, 0),
    (0x400000, 1821696, 0),
    (0x2a8000, 32768, hdv.SEG_B1), (0x2b0000, 24428, hdv.SEG_B1),
    (0x007c00, 512, 0),
]


def picture_on_disk(picture, order):
    """The blocks of `picture` in the order they have on the disk."""
    return b''.join(picture[b * BLOCK:(b + 1) * BLOCK] for b in order)


class SyntheticImage(unittest.TestCase):
    def setUp(self):
        self.code = bytes(range(256)) * 5                  # 1280 bytes
        self.picture = b''.join(
            bytes([block]) * BLOCK for block in range(hdv.PIC_BLOCKS))
        self.store = b'L' * (3 * BLOCK)
        stream, self.plain = support.B1_ABABAB
        length = struct.pack('<H', len(self.plain))
        self.disk = hdv.parse(support.make_disk([
            (0x2a0000, hdv.SEG_PIC,
             picture_on_disk(self.picture, support.picture_order())),
            (0x030000, 0, self.code),
            (0x020000, 0, b'near'),
            (0x400000, 0, self.store),
            (0x2a8000, hdv.SEG_B1, length + stream),
        ]))

    def test_header_fields(self):
        disk = self.disk
        self.assertEqual(disk.volume_name, 'TEST')
        self.assertEqual((disk.disk, disk.disks), (1, 1))
        self.assertEqual(disk.entry, 0x030000)
        self.assertEqual(disk.bar_step, 3)
        self.assertEqual(disk.build_id, 0x12345678)
        self.assertEqual(disk.resident_disks, 1)
        self.assertEqual(disk.store_banks, 1)
        self.assertEqual(disk.store_map, [hdv.StoreRun(0, 3, 14 + 68, 1)])

    def test_loader(self):
        self.assertEqual(self.disk.loader_address, 0x6000)
        self.assertEqual(self.disk.loader, b'\x60' * 700)

    def test_segments_are_address_bytes_flags(self):
        triples = [tuple(s[:3]) for s in self.disk.segments]
        self.assertEqual(triples[1],
                         (0x030000, self.code + bytes(256), 0))
        self.assertEqual(triples[2],
                         (0x020000, b'near' + bytes(BLOCK - 4), 0))
        self.assertEqual([s.index for s in self.disk.segments],
                         list(range(6)))

    def test_disk_position(self):
        segment = self.disk.segments[1]
        self.assertEqual((segment.first_block, segment.block_count),
                         (14 + 64, 3))
        self.assertEqual(segment.end, 0x030600)

    def test_picture_is_put_in_memory_order(self):
        segment = self.disk.segments[0]
        self.assertEqual(segment.flags, hdv.SEG_PIC)
        self.assertEqual(segment.data, self.picture)

    def test_b1_segment_is_decoded(self):
        segment = self.disk.segments[4]
        self.assertEqual(segment[:3],
                         (0x2a8000, self.plain, hdv.SEG_B1))

    def test_settings_segment(self):
        segment = self.disk.segments[5]
        self.assertEqual(segment.address, 0x007c00)
        self.assertEqual(segment.data, b'S' * BLOCK)
        self.assertEqual(hdv.kind(self.disk, segment), hdv.KIND_SETTINGS)

    def test_level_store(self):
        self.assertEqual(self.disk.level_store(), (0x400000, self.store))

    def test_kinds_and_totals(self):
        self.assertEqual(
            [hdv.kind(self.disk, s) for s in self.disk.segments],
            [hdv.KIND_PICTURE, hdv.KIND_CODE, hdv.KIND_NEAR_DATA,
             hdv.KIND_STORE, hdv.KIND_B1, hdv.KIND_SETTINGS])
        self.assertEqual(hdv.totals(self.disk), {
            hdv.KIND_PICTURE: 64 * BLOCK, hdv.KIND_CODE: 3 * BLOCK,
            hdv.KIND_NEAR_DATA: BLOCK, hdv.KIND_STORE: 3 * BLOCK,
            hdv.KIND_B1: len(self.plain), hdv.KIND_SETTINGS: BLOCK})


class SyntheticDetails(unittest.TestCase):
    def test_b1_length_zero_is_64k(self):
        # A stored length of 0 means 65536. The hand-made stream gives 6
        # bytes, so the decoder must go on past them and run out of input.
        stream, _ = support.B1_ABABAB
        image = support.make_disk(
            [(0x2b0000, hdv.SEG_B1, struct.pack('<H', 0) + stream)])
        with self.assertRaises(hdv.HdvError) as caught:
            hdv.parse(image)
        self.assertIn('segment 0: the stream ends', str(caught.exception))

    def test_store_in_two_segments(self):
        disk = hdv.parse(support.make_disk([
            (0x400000, 0, b'a' * BLOCK), (0x400200, 0, b'b' * BLOCK)]))
        self.assertEqual(disk.level_store(),
                         (0x400000, b'a' * BLOCK + b'b' * BLOCK))

    def test_store_with_a_gap(self):
        disk = hdv.parse(support.make_disk([
            (0x400000, 0, b'a' * BLOCK), (0x400400, 0, b'b' * BLOCK)]))
        with self.assertRaises(hdv.HdvError):
            disk.level_store()

    def test_no_store(self):
        disk = hdv.parse(support.make_disk([(0x030000, 0, b'code')]))
        with self.assertRaises(hdv.HdvError):
            disk.level_store()
        self.assertEqual(disk.store_map, [])

    def test_bank_zero_and_resident_data_kinds(self):
        disk = hdv.parse(support.make_disk([
            (0x004000, 0, b'low'), (0x100000, 0, b'IWAD')]))
        self.assertEqual(
            [hdv.kind(disk, s) for s in disk.segments[:2]],
            [hdv.KIND_CODE_BANK0, hdv.KIND_DATA])


class BadImages(unittest.TestCase):
    def test_wrong_magic(self):
        image = support.make_disk([(0x030000, 0, b'x')], magic=b'DOOMXX')
        with self.assertRaises(hdv.HdvError):
            hdv.parse(image)

    def test_unknown_flag(self):
        with self.assertRaises(hdv.HdvError):
            hdv.parse(support.make_disk([(0x030000, 4, b'x')]))

    def test_picture_of_wrong_size(self):
        with self.assertRaises(hdv.HdvError):
            hdv.parse(support.make_disk(
                [(0x2a0000, hdv.SEG_PIC, bytes(63 * BLOCK))]))

    def test_picture_order_not_a_permutation(self):
        with self.assertRaises(hdv.HdvError):
            hdv.parse(support.make_disk(
                [(0x2a0000, hdv.SEG_PIC, bytes(64 * BLOCK))],
                order=bytes(64)))

    def test_segment_outside_the_data_file(self):
        image = support.make_disk([(0x030000, 0, bytes(4 * BLOCK))],
                                  data_blocks=2)
        with self.assertRaises(hdv.HdvError) as caught:
            hdv.parse(image)
        self.assertIn('block 16', str(caught.exception))

    def test_too_many_segments(self):
        image = bytearray(support.make_disk([(0x030000, 0, b'x')]))
        image[BLOCK + hdv.HDR_SEGS] = hdv.MAX_SEGMENTS + 1
        with self.assertRaises(hdv.HdvError):
            hdv.parse(bytes(image))


@support.needs_release
class ReleaseImage(unittest.TestCase):
    """The acceptance numbers of stage 1 (docs/ARCHITECTURE.md section 0)."""

    @classmethod
    def setUpClass(cls):
        data = support.RELEASE_IMAGE.read_bytes()
        cls.sha256 = hashlib.sha256(data).hexdigest()
        cls.disk = hdv.parse(data)

    def test_image_is_the_pinned_release(self):
        self.assertEqual(
            self.sha256,
            '2716166dda1d87faf3bdec572ddcf652379a54da78f1dcccdd0897e00b23bd0d')

    def test_segment_count_and_entry(self):
        self.assertEqual(len(self.disk.segments), 28)
        self.assertEqual(self.disk.entry, 0x030000)

    def test_segment_addresses_sizes_flags(self):
        self.assertEqual(
            [(s.address, len(s.data), s.flags) for s in self.disk.segments],
            RELEASE_SEGMENTS)

    def test_totals(self):
        sums = hdv.totals(self.disk)
        self.assertEqual(sums[hdv.KIND_CODE_BANK0], 17920)
        self.assertEqual(sums[hdv.KIND_CODE], 169984)
        self.assertEqual(
            sums[hdv.KIND_CODE_BANK0] + sums[hdv.KIND_CODE], 187904)
        self.assertEqual(sums[hdv.KIND_NEAR_DATA], 30208)
        self.assertEqual(sums[hdv.KIND_STORE], 1821696)

    def test_level_store(self):
        address, store = self.disk.level_store()
        self.assertEqual((address, len(store)), (0x400000, 1821696))
        self.assertEqual(self.disk.store_banks, 28)
        self.assertEqual(self.disk.store_map,
                         [hdv.StoreRun(0, 3558, 1365, 1)])

    def test_header(self):
        disk = self.disk
        self.assertEqual(disk.volume_name, 'DOOM')
        self.assertEqual((disk.disk, disk.disks, disk.resident_disks),
                         (1, 1, 1))
        self.assertEqual(disk.settings_block, 4944)
        self.assertEqual((disk.loader_address, len(disk.loader)),
                         (0x6000, 3072))

    def test_b1_segments_are_streams_inside_the_store(self):
        # mkdisk.py makes them aliases of song data in the store
        run = self.disk.store_map[0]
        for segment in self.disk.segments:
            if segment.flags & hdv.SEG_B1:
                self.assertGreaterEqual(segment.first_block, run.disk_block)
                self.assertLessEqual(
                    segment.first_block + segment.block_count,
                    run.disk_block + run.count)

    def test_code_segments_stay_in_their_bank_group(self):
        for segment in self.disk.segments:
            if hdv.kind(self.disk, segment) == hdv.KIND_CODE:
                self.assertLessEqual(segment.end, 0x060000)
            if hdv.kind(self.disk, segment) == hdv.KIND_CODE_BANK0:
                self.assertLessEqual(segment.end, 0x010000)


if __name__ == '__main__':
    unittest.main()
