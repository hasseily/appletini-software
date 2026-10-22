"""Host checks for produced artifacts and the small ProDOS packager."""
from pathlib import Path
import sys
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import disk
import build
import profiler


class ObjectMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.object_path = ROOT / "build/obj/memory.o"
        cls.original = cls.object_path.read_bytes()
        cls.options, cls.options_size = struct.unpack_from("<II", cls.original, 8)
        # The documented ca65 OPT_DATETIME option tag, confined to the option
        # section. Real assembled machine code is never searched or patched.
        section = cls.original[cls.options:cls.options + cls.options_size]
        cls.timestamp = cls.options + section.index(0x40)

    def normalize(self, data):
        with tempfile.TemporaryDirectory(prefix="libtini-object-test-") as temporary:
            path = Path(temporary) / "throwaway.o"
            path.write_bytes(data)
            build.normalize_object(path)
            normalized = path.read_bytes()
            self.assertEqual(int(path.stat().st_mtime), build.OBJECT_EPOCH)
            return normalized

    def test_idempotent_and_only_translation_metadata_changes(self):
        self.assertEqual(self.normalize(self.original), self.original)
        changed = bytearray(self.original)
        changed[self.timestamp + 1] ^= 1
        self.assertEqual(self.normalize(changed), self.original)

    def test_wrong_object_format_rejected(self):
        for location in (0, 4):
            with self.subTest(location=location):
                changed = bytearray(self.original)
                changed[location] ^= 1
                with self.assertRaises(SystemExit):
                    self.normalize(changed)

    def test_missing_or_malformed_translation_option_rejected(self):
        missing = bytearray(self.original)
        missing[self.timestamp] = 0x41
        malformed = bytearray(self.original)
        struct.pack_into("<I", malformed, 12, self.options_size - 1)
        for changed in (missing, malformed):
            with self.assertRaises(SystemExit):
                self.normalize(changed)


class DiskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = (ROOT / "build-inputs/prodos/ProDOS_2_4_3.po").read_bytes()

    def test_payload_boundaries_and_reproducibility(self):
        kernel = disk.read_root_files(self.template)["PRODOS"]
        for length in (1, 512, 513, 1024, 32768):
            with self.subTest(length=length):
                payload = bytes((i * 29 + 7) & 255 for i in range(length))
                image = disk.build_image(self.template, payload)
                self.assertEqual(len(image), 280 * 512)
                self.assertEqual(image, disk.build_image(self.template, payload))
                files = disk.read_root_files(image)
                self.assertEqual(files, {"PRODOS": kernel, "LIBTINI.SYSTEM": payload})
                self.assertEqual(image[:1024], self.template[:1024])
                disk.validate_image(image)

    def test_bad_payload_and_name(self):
        for payload in (b"", bytes(32769)):
            with self.assertRaises(ValueError):
                disk.build_image(self.template, payload)
        for name in ("", "lower.system", "1BAD", "A/B", "TOO.LONG.SYSTEM.NAME"):
            with self.assertRaises(ValueError):
                disk.build_image(self.template, b"x", name)

    def test_corruption_detected(self):
        image = disk.build_image(self.template, bytes(range(256)) * 3)
        # Corrupt independent on-disk facts: free bitmap, file count, duplicate
        # allocation, directory chain. A valid extractor alone misses these.
        corruptions = [(6 * 512, 0x80), (2 * 512 + 4 + 33, 0x01),
                       (2 * 512 + 4 + 2 * 39 + 17, 0x01),
                       (3 * 512 + 2, 0x07)]
        for location, mask in corruptions:
            with self.subTest(location=location):
                broken = bytearray(image)
                broken[location] ^= mask
                with self.assertRaises(ValueError):
                    disk.validate_image(broken)

    def test_linked_program_packaged_exactly(self):
        binary = ROOT / "build/libtini.system"
        image = ROOT / "build/libtini.po"
        if not binary.exists() or not image.exists():
            self.skipTest("normal build artifacts not generated yet")
        self.assertEqual(disk.read_root_files(image.read_bytes())["LIBTINI.SYSTEM"],
                         binary.read_bytes())


def listed(offset, source, data=""):
    """A ca65 listing line: source text starts in column 24."""
    return f"{offset:06X}r 1  {data:<13}{source}"


class ProfilerTests(unittest.TestCase):
    MAP = "\n".join([
        "Modules list:", "-------------", "game.o:",
        "    CODE              Offs=000000  Size=000040  Align=00001  Fill=0000",
        "    BSS               Offs=000000  Size=000004  Align=00001  Fill=0000",
        "build/libtini.lib(text.o):",
        "    CODE              Offs=000040  Size=000020  Align=00001  Fill=0000",
        "    LOWCODE           Offs=000000  Size=000008  Align=00001  Fill=0000",
        "    RODATA            Offs=000000  Size=000000  Align=00001  Fill=0000",
        "build/libtini.lib(other.o):",
        "    CODE              Offs=000060  Size=000010  Align=00001  Fill=0000",
        "", "", "Segment list:", "-------------",
        "Name                   Start     End    Size  Align",
        "----------------------------------------------------",
        "LOWCODE               001620  001627  000008  00001",
        "CODE                  0020E4  002153  000070  00001",
        "BSS                   00A0B7  00A0BA  000004  00001",
        "", "", "Exports list by name:", "---------------------",
        "_main                     002104 RLA"])

    def test_map_segments_and_module_offsets(self):
        starts, offsets = profiler.read_map(self.MAP)
        self.assertEqual(starts, {"LOWCODE": 0x1620, "CODE": 0x20E4, "BSS": 0xA0B7})
        # Empty segments are left out.
        self.assertEqual(offsets, {"game": {"CODE": 0, "BSS": 0}, "text": {"CODE": 0x40, "LOWCODE": 0},
                                   "other": {"CODE": 0x60}})

    def test_listing_labels_by_segment(self):
        listing = "\n".join([
            listed(0, '.segment\t"BSS"'), listed(0, "count:  .res 1", "xx"),
            listed(0, '.segment\t"CODE"'), listed(0, ".proc\t_hud: near"),
            listed(0x12, "        lda #0", "A9 00"), listed(0x20, "draw_line:"),
            listed(0x22, ":       dex", "CA"), listed(0x30, '.segment "LOWCODE"'),
            listed(4, "div6:   ldy #0", "A0 00"), "", "not a listing line"])
        self.assertEqual(profiler.read_listing(listing),
                         [("BSS", 0, "count"), ("CODE", 0, "_hud"), ("CODE", 0x20, "draw_line"),
                          ("LOWCODE", 4, "div6")])

    def test_names_resolve_to_linked_addresses(self):
        starts, offsets = profiler.read_map(self.MAP)
        listings = {"game": [("CODE", 0, "_hud"), ("CODE", 0x20, "_main")],
                    "text": [("CODE", 0, "draw"), ("LOWCODE", 4, "div6")],
                    "other": [("CODE", 2, "draw")]}
        found = profiler.locate(listings, starts, offsets, {"_main": 0x2104})
        entries = profiler.resolve(["hud", "_main", "text:draw", "div6"], found, {"_main": 0x2104})
        self.assertEqual(entries, {0x20E4: "hud", 0x2104: "_main", 0x2124: "text:draw", 0x1624: "div6"})
        with self.assertRaises(SystemExit):
            profiler.resolve(["draw"], found, {})
        with self.assertRaises(SystemExit):
            profiler.resolve(["missing"], found, {})
        # A listing that disagrees with the linked label file is stale.
        with self.assertRaises(SystemExit):
            profiler.locate(listings, starts, offsets, {"_main": 0x2105})

    def test_paths_include_callees_and_jumps(self):
        paths = profiler.Paths()
        self.assertTrue(paths.enter("A", 0, 100, 0xF0))
        self.assertTrue(paths.enter("B", 10, 200, 0xEE))
        # A loop back to B's first instruction is not another call.
        self.assertFalse(paths.enter("B", 12, 200, 0xEE))
        self.assertTrue(paths.leave(200, 30, 0xF0))
        paths.enter("B", 40, 200, 0xEE)
        # B's return address at another depth, and an unknown address.
        self.assertFalse(paths.leave(200, 42, 0xE0))
        self.assertFalse(paths.leave(999, 43, 0xF0))
        self.assertTrue(paths.leave(200, 45, 0xF0))
        self.assertTrue(paths.leave(100, 60, 0xF2))
        # D was reached by a jump from C, so one return ends both.
        paths.enter("C", 70, 300, 0xF0)
        paths.enter("D", 75, 300, 0xF0)
        self.assertTrue(paths.leave(300, 90, 0xF2))
        # A recursive call returns to the same address one level deeper.
        paths.enter("R", 100, 500, 0xF0)
        paths.enter("R", 105, 600, 0xEC)
        paths.enter("R", 110, 600, 0xE8)
        self.assertTrue(paths.leave(600, 115, 0xEA))
        self.assertTrue(paths.leave(600, 118, 0xEE))
        self.assertTrue(paths.leave(500, 120, 0xF2))
        paths.enter("E", 130, 400, 0xF0)
        paths.close(150)
        self.assertEqual(paths.totals, {"A/B": {"ticks": 25, "calls": 2}, "A": {"ticks": 60, "calls": 1},
                                        "C/D": {"ticks": 15, "calls": 1}, "C": {"ticks": 20, "calls": 1},
                                        "R/R/R": {"ticks": 5, "calls": 1}, "R/R": {"ticks": 13, "calls": 1},
                                        "R": {"ticks": 20, "calls": 1}, "E": {"ticks": 20, "calls": 1}})
        self.assertFalse(paths.stack)


if __name__ == "__main__":
    unittest.main()
