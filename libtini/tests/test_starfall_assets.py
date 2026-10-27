"""Offline source provenance, packed art and authored speech checks for STARFALL."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import unittest
from unittest import mock
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import speech
import starfall_assets as art
import starfall_bosses as bosses
import starfall_pack


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def small_png(*, depth=8, color=3, interlace=0, raw=b"\x00\x00\x01\x00\x01\x00", alpha=b"\x00\xff"):
    """A two-by-two transparent/red PNG, authored independently of the decoder."""
    header = struct.pack(">IIBBBBB", 2, 2, depth, color, 0, 0, interlace)
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header)
            + png_chunk(b"PLTE", b"\x00\x00\x00\xff\x00\x00")
            + png_chunk(b"tRNS", alpha) + png_chunk(b"IDAT", zlib.compress(raw))
            + png_chunk(b"IEND", b""))


class StarfallAssetTests(unittest.TestCase):
    def test_original_source_and_license_match_recorded_provenance(self):
        provenance = json.loads((ROOT / "assets/starfall/provenance.json").read_text())
        source = art.ARCHIVE.read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), art.ARCHIVE_SHA256)
        self.assertEqual(provenance["archive_sha256"], art.ARCHIVE_SHA256)
        self.assertEqual(provenance["publisher"], "Kenney")
        self.assertEqual(provenance["license"], "CC0-1.0")
        self.assertEqual(provenance["source_page"], "https://kenney.nl/assets/pixel-shmup")
        self.assertTrue(provenance["download_url"].startswith("https://kenney.nl/"))
        self.assertEqual(ROOT / "assets/starfall" / provenance["archive"], art.ARCHIVE)
        with zipfile.ZipFile(art.ARCHIVE) as archive:
            for member, digest in provenance["members"].items():
                with self.subTest(member=member):
                    self.assertEqual(hashlib.sha256(archive.read(member)).hexdigest(), digest)
            publisher_license = archive.read("License.txt")
        self.assertEqual((ROOT / "assets/starfall/source/License.txt").read_bytes(), publisher_license)
        self.assertIn(b"Creative Commons Zero, CC0", publisher_license)
        self.assertIn(b"Kenney", publisher_license)
        self.assertTrue({frame[1] for frame in art.FRAMES}.issubset(provenance["members"]))
        self.assertEqual([frame["id"] for frame in provenance["frames"]], [frame[0] for frame in art.FRAMES])
        self.assertEqual([(entry["id"], entry["members"], entry["content_pixels"]) for entry in provenance["backdrop"]],
                         [(name, [m[0] for m in members], size) for name, members, size, _ in art.BACKDROP])
        self.assertTrue({m[0] for entry in art.BACKDROP for m in entry[1]}.issubset(provenance["members"]))

    def test_compilation_is_deterministic_and_rejects_unverified_source(self):
        self.assertEqual(art.compile_assets(), art.compile_assets())
        with mock.patch.object(art, "ARCHIVE") as archive:
            archive.read_bytes.return_value = b"unverified or damaged publisher archive"
            with self.assertRaisesRegex(ValueError, "archive SHA-256 mismatch"):
                art.compile_assets()

    def test_packed_header_preserves_pixels_transparency_and_fixed_dimensions(self):
        header, frames = art.compile_assets()
        # Archive cells, the atlas, then the backdrop cells.
        self.assertEqual(len(frames), len(art.FRAMES) + 1 + len(art.BACKDROP))
        self.assertIn("#define SF_ART_WIDTH 16U", header)
        self.assertIn("#define SF_ART_HEIGHT 16U", header)
        self.assertIn("#define SF_ART_FRAME_BYTES 128U", header)
        self.assertIn(f"SF_ART_ATLAS = {len(art.FRAMES)},", header)
        packed_section = header.split("static const uint8_t sf_sprite_pixels", 1)[1]
        packed = [int(value, 16) for value in re.findall(r"0x([0-9a-f]{2})\b", packed_section)]
        self.assertEqual(len(packed), len(frames) * 128)
        self.assertLessEqual(len(packed) + 32 + 3 * len(art.SUBSPRITES), 2176)
        names = [frame[0] for frame in art.FRAMES] + ["ATLAS"] + [entry[0] for entry in art.BACKDROP]
        for i, frame in enumerate(frames):
            with self.subTest(frame=names[i]):
                decoded = [pixel for byte in packed[i * 128:(i + 1) * 128] for pixel in (byte >> 4, byte & 15)]
                self.assertEqual(decoded, frame)
                self.assertEqual(len(frame), 16 * 16)
                self.assertIn(0, frame)
                self.assertTrue(any(frame))
                self.assertTrue(all(0 <= pixel < 16 for pixel in frame))
                if i < len(art.FRAMES):
                    # Archive art never uses 13..15; the game reserves and animates them.
                    self.assertTrue(all(pixel < 13 for pixel in frame))

    def test_backdrop_is_darkened_and_far_aircraft_fit_their_quadrants(self):
        header, frames = art.compile_assets()
        far = frames[-1]
        tones = set(art.MID_TONES.values()) | set(art.FAR_TONES.values()) | {0}
        for name, cell in zip(("MID", "FAR"), frames[-2:]):
            with self.subTest(cell=name):
                self.assertIn(f"SF_ART_{name} = ", header)
                self.assertTrue(set(cell) <= tones and any(cell))
        offsets = [int(o) for o in re.findall(r"\{&sf_sprite_pixels\[SF_ART_FAR\]\[(\d+)\], 4, 8, 8\}", header)]
        self.assertEqual(offsets, list(art.FAR_IMAGES))
        for offset in offsets:
            left, top = offset % 8 * 2, offset // 8
            quadrant = [far[(top + y) * 16 + left + x] for y in range(8) for x in range(8)]
            self.assertTrue(any(quadrant))
        # Every far pixel lies in one of the four quadrants' images.
        self.assertEqual(sum(1 for pixel in far if pixel),
                         sum(1 for offset in offsets for y in range(8) for x in range(8)
                             if far[(offset // 8 + y) * 16 + offset % 8 * 2 + x]))

    def test_atlas_sub_sprites_round_trip_and_fit_their_scene_images(self):
        header, frames = art.compile_assets()
        atlas = frames[len(art.FRAMES)]
        records = [tuple(map(int, record)) for record in re.findall(
            r"\{&sf_sprite_pixels\[SF_ART_ATLAS\]\[(\d+)\], (\d+), (\d+), 8\}", header)]
        self.assertEqual(len(records), len(art.SUBSPRITES))
        covered = set()
        for (name, x, y, rows), (offset, row_bytes, height) in zip(art.SUBSPRITES, records):
            with self.subTest(sub=name):
                self.assertIn(f"SF_SUB_{name} = ", header)
                self.assertEqual(offset, y * 8 + x // 2)
                self.assertEqual((row_bytes * 2, height), (len(rows[0]), len(rows)))
                # Each image's rows, 8 bytes apart, stay inside the 128-byte cell.
                self.assertLessEqual(offset + (height - 1) * 8 + row_bytes, 128)
                for dy, row in enumerate(rows):
                    for dx, mark in enumerate(row):
                        self.assertEqual(atlas[(y + dy) * 16 + x + dx], 0 if mark == "." else int(mark, 16))
                        covered.add((y + dy) * 16 + x + dx)
        self.assertTrue(all(atlas[i] == 0 for i in range(256) if i not in covered))
        for bad in ((("ODD", 1, 0, ("44",)),), (("WIDE", 14, 0, ("4444",)),),
                    (("A", 0, 0, ("44",)), ("B", 0, 0, ("44",)))):
            with self.subTest(bad=bad[0][0]), mock.patch.object(art, "SUBSPRITES", bad):
                with self.assertRaises(ValueError):
                    art.atlas()

    def test_indexed_png_transparency_and_bit_depths(self):
        expected = [(0, 0, 0, 0), (255, 0, 0, 255), (255, 0, 0, 255), (0, 0, 0, 0)]
        # The two indices in each row fit one packed byte for sub-byte depths.
        for depth, raw in ((1, b"\x00\x40\x00\x80"), (2, b"\x00\x10\x00\x40"),
                           (4, b"\x00\x01\x00\x10"), (8, b"\x00\x00\x01\x00\x01\x00")):
            with self.subTest(depth=depth):
                self.assertEqual(art.png_indexed(small_png(depth=depth, raw=raw)), (2, 2, expected))

    def test_malformed_pngs_fail_before_sprite_conversion(self):
        corrupt_crc = bytearray(small_png())
        corrupt_crc[29] ^= 1  # IHDR CRC, leaving all payload bytes unchanged.
        cases = {
            "signature": b"not a PNG",
            "truncated chunk": small_png()[:-2],
            "CRC": bytes(corrupt_crc),
            "truecolor": small_png(color=2),
            "unsupported depth": small_png(depth=16),
            "interlace": small_png(interlace=1),
            "invalid filter": small_png(raw=b"\x05\x00\x01\x00\x01\x00"),
            "palette index": small_png(raw=b"\x00\x00\x02\x00\x01\x00"),
            "partial alpha": small_png(alpha=b"\x00\x80"),
            "short raster": small_png(raw=b"\x00\x00\x01"),
            "long raster": small_png(raw=b"\x00\x00\x01\x00\x01\x00\x00"),
        }
        for name, data in cases.items():
            with self.subTest(reason=name), self.assertRaises(ValueError):
                art.png_indexed(data)

    def test_starfall_requested_speech_and_local_pronunciations_compile_without_numbers(self):
        manifest = json.loads((ROOT / "examples/starfall/speech.json").read_text())
        requested = {"SAY_GREAT": "Great shot!", "SAY_EXCELLENT": "Excellent!", "SAY_OVER": "Game over.",
                     "SAY_WARNING": "Warning!", "SAY_RECORD": "New record!"}
        for name, text in requested.items():
            self.assertEqual(manifest["phrases"][name], text)
        header, records = speech.compile_manifest(manifest, "starfall_speech", include_numbers=False)
        self.assertEqual((header, records), speech.compile_manifest(manifest, "starfall_speech", include_numbers=False))
        self.assertEqual(len(records), len(manifest["phrases"]))
        self.assertFalse(any(record[0].startswith("TI_NUMBER_") for record in records))
        self.assertNotIn("starfall_speech_numbers", header)
        self.assertIn("{starfall_speech_phrases," + str(len(records)) + ",0}", header)
        by_name = {record[0]: record for record in records}
        self.assertEqual(by_name["SAY_GREAT"][3], "G R AY T PA SH AA T".split())
        self.assertEqual(by_name["SAY_EXCELLENT"][3], "EH K S UH L UH N T".split())
        self.assertEqual(by_name["SAY_WARNING"][3], "W AO R N IH NG".split())
        self.assertEqual(by_name["SAY_RECORD"][3], "N UW PA R IH K AO R D".split())
        # The native validator matches phrases 3..5 by their compiled order.
        self.assertEqual([record[0] for record in records][3:6], ["SAY_GREAT", "SAY_EXCELLENT", "SAY_OVER"])
        for word in ("GREAT", "SHOT", "EXCELLENT", "WARNING", "NEW"):
            self.assertIn(word, manifest["pronunciations"])
        self.assertTrue(all(0 < len(record[2]) <= 255 for record in records))
        self.assertTrue(all(0 <= code < 192 for record in records for code in record[2]))


class StarfallBossTests(unittest.TestCase):
    def test_boss_art_matches_its_provenance(self):
        record = json.loads((bosses.SOURCE / "provenance.json").read_text())
        self.assertEqual(record["license"], "MIT")
        self.assertEqual(len(record["files"]), 55)
        for name, digest in record["files"].items():
            self.assertEqual(hashlib.sha256((bosses.SOURCE / name).read_bytes()).hexdigest(), digest, name)

    def test_art_files_hold_record_strips_and_frames(self):
        converted = [bosses.convert(boss) for boss in bosses.verify()]
        self.assertEqual([boss["name"] for boss in converted], ["MANTA", "EXCALIBUR", "SCARAB", "COMET", "BULWARK"])
        for boss in converted:
            data = boss["art"]
            strips, slots = struct.unpack_from("<HH", data)
            self.assertEqual((strips, slots), (boss["strip_bytes"], boss["slot_bytes"]))
            self.assertEqual(data[4:4 + bosses.RECORD], bosses.record_bytes(boss))
            self.assertLessEqual(boss["width"], 100)
            self.assertLessEqual(boss["height"], 77)
            self.assertLessEqual(len(boss["bands"]), bosses.BANDS)
            # Strips are 8 lines from the top, on whole bytes, and inside the boss.
            for index, (x, y, nbytes, rows) in enumerate(boss["bands"]):
                self.assertEqual(x % 2, 0)
                self.assertEqual(y % bosses.BAND, 0)
                self.assertLessEqual(x + 2 * nbytes, boss["width"] + 1)
                self.assertEqual(boss["images"][index][1:3], (nbytes, rows))
            self.assertEqual(sum(b[2] * b[3] for b in boss["bands"]), strips)
            # Each part has eight frames in the file, and two images on one slot.
            self.assertEqual(sum(boss["frame_bytes"]), slots)
            end = 4 + bosses.RECORD + strips
            for part, (x, y, nbytes, rows, hit) in enumerate(boss["parts"]):
                self.assertEqual(x % 2, 0)
                self.assertEqual(boss["frames_at"][part], end)
                self.assertEqual(boss["frame_bytes"][part], nbytes * rows)
                end += 8 * nbytes * rows
                first, second = boss["images"][bosses.BANDS + 2 * part:bosses.BANDS + 2 * part + 2]
                self.assertEqual(first, second)
                self.assertGreaterEqual(first[0], strips)
            self.assertEqual(end, len(data))
            # Two boss colors, twelve shared ones, and nothing in the animated slot 15.
            self.assertEqual(len(boss["slots"]), 2)
            self.assertTrue(set(boss["table"].values()) <= set(range(1, 15)))

    def test_pack_places_art_after_the_boss_overlay_and_checks_its_fit(self):
        symbols = {"__BOSS_START__": 0x9000, "__BOSS_LAST__": 0x9800, "__BOSS_SIZE__": 0x1000,
                   "__TITLE_START__": 0x9000, "__TITLE_LAST__": 0x9100, "__TITLE_SIZE__": 0x1000}
        art_file = struct.pack("<HH", 0x500, 0x100) + bytes(0x700)
        data = starfall_pack.build([("TITLE", "TITLE", False, b"T" * 16),
                                    ("MANTA", "BOSS", True, art_file)], symbols)
        self.assertEqual(data[:4], b"SF\x02\x00")
        self.assertEqual(struct.unpack_from("<IHH", data, 4), (20, 16, 0x9000))
        self.assertEqual(struct.unpack_from("<IHH", data, 12), (36, len(art_file), 0x9800))
        too_big = struct.pack("<HH", 0x780, 0x100) + bytes(8)
        with self.assertRaises(SystemExit):
            starfall_pack.build([("MANTA", "BOSS", True, too_big)], symbols)


if __name__ == "__main__":
    unittest.main()
