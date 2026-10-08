"""Independent synthetic ProDOS fixtures for the read-only launcher reader."""

from pathlib import Path
import tempfile
import unittest

from tools.appletini.disk import DiskError, read_disk


def put_word(image, offset, value):
    image[offset:offset + 2] = value.to_bytes(2, "little")


def put_pointer(image, block, index, pointer):
    image[block * 512 + index] = pointer & 255
    image[block * 512 + 256 + index] = pointer >> 8


def put_entry(image, offset, name, storage, key, blocks, size, kind=6, aux=0x2000):
    entry = bytearray(39)
    entry[0] = storage << 4 | len(name)
    entry[1:1 + len(name)] = name.encode("ascii")
    entry[16] = kind
    put_word(entry, 17, key)
    put_word(entry, 19, blocks)
    entry[21:24] = size.to_bytes(3, "little")
    entry[30] = 0xC3
    put_word(entry, 31, aux)
    put_word(entry, 37, 2)
    image[offset:offset + 39] = entry


HEADER = 2 * 512 + 4
SEEDLING = HEADER + 39
SAPLING = SEEDLING + 39
TREE = 3 * 512 + 4


def fixture():
    """A two-block root directory containing all three legal file layouts.

    The tree's first 128 KiB and the sapling's middle block are sparse. All
    bytes are specified here; no ProDOS writer or external disk is imported.
    """
    image = bytearray(24 * 512)
    image[HEADER] = 0xF7
    image[HEADER + 1:HEADER + 8] = b"FIXTURE"
    image[HEADER + 30:HEADER + 33] = bytes((0xC3, 39, 13))
    put_word(image, HEADER + 33, 3)
    put_word(image, HEADER + 35, 6)
    put_word(image, HEADER + 37, 24)
    put_word(image, 2 * 512 + 2, 3)
    put_word(image, 3 * 512, 2)
    put_entry(image, SEEDLING, "GAME.SYSTEM", 1, 7, 1, 3, kind=255)
    put_entry(image, SAPLING, "SPRITES", 2, 8, 3, 1029, aux=0x4000)
    put_entry(image, TREE, "BACKGROUND", 3, 10, 3, 256 * 512 + 4)
    image[7 * 512:7 * 512 + 3] = b"\x4c\x00\x20"
    put_pointer(image, 8, 0, 9)
    put_pointer(image, 8, 2, 13)
    image[9 * 512:10 * 512] = b"S" * 512
    image[13 * 512:13 * 512 + 5] = b"END!!"
    put_pointer(image, 10, 1, 11)
    put_pointer(image, 11, 0, 12)
    image[12 * 512:12 * 512 + 4] = b"TREE"
    used = {0, 1, 2, 3, 6, 7, 8, 9, 10, 11, 12, 13}
    for block in range(24):
        if block not in used:
            image[6 * 512 + block // 8] |= 0x80 >> (block % 8)
    return image


class DiskTests(unittest.TestCase):
    def read(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.hdv"
            path.write_bytes(data)
            result = read_disk(path)
            self.assertEqual(path.read_bytes(), data, "reader modified the source")
            return result

    def rejects(self, data, message):
        with self.assertRaisesRegex(DiskError, message):
            self.read(data)

    def test_seedling_sapling_tree_sparse_and_metadata(self):
        name, files = self.read(fixture())
        self.assertEqual(name, "FIXTURE")
        self.assertEqual([f["name"] for f in files], ["GAME.SYSTEM", "SPRITES", "BACKGROUND"])
        self.assertEqual(files[0], {"name": "GAME.SYSTEM", "type": 255,
                                    "aux": 0x2000, "data": b"\x4c\x00\x20"})
        self.assertEqual(files[1]["aux"], 0x4000)
        self.assertEqual(files[1]["data"], b"S" * 512 + bytes(512) + b"END!!")
        self.assertEqual(files[2]["data"], bytes(256 * 512) + b"TREE")

    def test_deleted_entry_with_old_name_is_ignored(self):
        image = fixture()
        offset = SAPLING + 39
        image[offset:offset + 5] = b"\x04GONE"
        self.assertEqual(len(self.read(image)[1]), 3)

    def test_empty_seedling(self):
        image = fixture()
        put_entry(image, SEEDLING, "EMPTY", 1, 0, 0, 0)
        self.assertEqual(self.read(image)[1][0]["data"], b"")

    def test_image_alignment_and_truncation(self):
        for data in (b"", bytes(1024), fixture()[:-1]):
            with self.subTest(size=len(data)):
                self.rejects(data, "whole 512-byte blocks")
        self.rejects(fixture()[:-512], "total blocks")

    def test_header_type_and_geometry(self):
        for offset, value, message in ((0, 0xE7, "volume header"),
                                       (31, 0, "39-byte entries"),
                                       (32, 255, "13 entries")):
            with self.subTest(offset=offset):
                image = fixture()
                image[HEADER + offset] = value
                self.rejects(image, message)

    def test_invalid_name(self):
        image = fixture()
        image[SEEDLING + 1] = ord("/")
        self.rejects(image, "invalid ProDOS name")

    def test_directory_cycle(self):
        image = fixture()
        put_word(image, 3 * 512 + 2, 2)
        self.rejects(image, "directory chain cycle")

    def test_directory_backlink(self):
        image = fixture()
        put_word(image, 3 * 512, 0)
        self.rejects(image, "previous-block link")

    def test_directory_out_of_bounds(self):
        image = fixture()
        put_word(image, 3 * 512 + 2, 24)
        self.rejects(image, "outside volume bounds")

    def test_bitmap_overlap_and_bounds(self):
        for pointer, message in ((3, "overlaps allocation bitmap"),
                                 (24, "outside volume bounds"), (0, "bitmap pointer")):
            with self.subTest(pointer=pointer):
                image = fixture()
                put_word(image, HEADER + 35, pointer)
                self.rejects(image, message)

    def test_file_count(self):
        image = fixture()
        put_word(image, HEADER + 33, 2)
        self.rejects(image, "file count")

    def test_duplicate_names(self):
        image = fixture()
        put_entry(image, SAPLING, "GAME.SYSTEM", 2, 8, 3, 1029)
        self.rejects(image, "duplicate root filename")

    def test_nested_and_extended_files_rejected(self):
        for storage, message in ((13, "subdirectories are not supported"),
                                 (5, "unsupported ProDOS storage")):
            with self.subTest(storage=storage):
                image = fixture()
                image[SEEDLING] = storage << 4 | 11
                self.rejects(image, message)

    def test_wrong_file_header_pointer(self):
        image = fixture()
        put_word(image, SEEDLING + 37, 3)
        self.rejects(image, "file header")

    def test_file_pointer_outside_declared_volume(self):
        image = fixture() + bytes(512)  # Padding is not addressable storage.
        put_word(image, SEEDLING + 17, 24)
        self.rejects(image, "outside volume bounds")

    def test_index_pointer_out_of_bounds(self):
        for block, slot in ((8, 0), (8, 200), (10, 1), (11, 0)):
            with self.subTest(block=block, slot=slot):
                image = fixture()
                put_pointer(image, block, slot, 65535)
                self.rejects(image, "outside volume bounds")

    def test_index_cycles_and_data_aliases(self):
        for block, slot, pointer in ((8, 0, 8), (10, 1, 10), (11, 0, 10),
                                     (8, 1, 9), (8, 0, 7), (8, 0, 2)):
            with self.subTest(block=block, slot=slot, pointer=pointer):
                image = fixture()
                put_pointer(image, block, slot, pointer)
                self.rejects(image, "overlaps")

    def test_missing_key_pointer(self):
        for offset in (SEEDLING, SAPLING, TREE):
            with self.subTest(offset=offset):
                image = fixture()
                put_word(image, offset + 17, 0)
                self.rejects(image, "zero.*pointer")

    def test_eof_exceeds_storage_capacity(self):
        for offset, size in ((SEEDLING, 513), (SAPLING, 131073)):
            with self.subTest(offset=offset):
                image = fixture()
                image[offset + 21:offset + 24] = size.to_bytes(3, "little")
                self.rejects(image, "EOF exceeds")

    def test_blocks_used(self):
        image = fixture()
        put_word(image, TREE + 19, 2)
        self.rejects(image, "blocks-used count")

    def test_tree_overflow(self):
        image = fixture()
        put_pointer(image, 10, 128, 14)
        self.rejects(image, "maximum file size")


if __name__ == "__main__":
    unittest.main()
