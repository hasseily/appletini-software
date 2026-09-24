#!/usr/bin/env python3
"""Original PCS .PB HGR picture decoding and playfield colour mapping."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import pb_art  # noqa: E402
import make_tables  # noqa: E402


class TestPBArtwork(unittest.TestCase):
    def test_zero_and_literal_runs(self):
        # One 256-byte literal, then 31 full pages of zeroes, then the
        # original compressor's 1/1 end marker.
        first = bytes(range(256))
        stream = bytes([0]) + first + bytes([1, 0]) * 31 + bytes([1, 1])
        self.assertEqual(pb_art.decode_hgr_artwork(stream), first + bytes(31 * 256))

    def test_rejects_malformed_runs(self):
        for stream in (b"", b"\x01", b"\x02A", b"\x01\x01",
                       bytes([1, 0]) * 33 + b"\x01\x01",
                       bytes([1, 0]) * 32):
            with self.subTest(stream=stream[:4], length=len(stream)):
                with self.assertRaises(ValueError):
                    pb_art.decode_hgr_artwork(stream)

    def test_final_run_can_cross_hgr_page_boundary(self):
        stream = bytes([1, 0]) * 32 + bytes([1, 24, 1, 1, 1, 1])
        self.assertEqual(pb_art.decode_hgr_artwork(stream), bytes(8192))

    def test_budgeco_zero_run_stream(self):
        stream = b"\x80\x00" * 31 + b"\x80\xFE\x7F\x00\x80\x01"
        decoded = pb_art.decode_hgr_artwork(stream)
        self.assertEqual(decoded, bytes(31 * 256 + 254) + b"\x7F\x00")
        with self.assertRaises(ValueError):
            pb_art.decode_hgr_artwork(b"\x80\x00" * 31 + b"\x80\x01")

    def test_hgr_scanline_interleave(self):
        self.assertEqual([pb_art.hgr_row_offset(y) for y in (0, 1, 7, 8, 64, 191)],
                         [0, 0x400, 0x1C00, 0x80, 0x28, 0x1FD0])
        with self.assertRaises(ValueError):
            pb_art.hgr_row_offset(192)

    def test_artifact_colours_and_overlay_encoding(self):
        hgr = bytearray(pb_art.HGR_SIZE)
        start = pb_art.hgr_row_offset(64)
        hgr[start] = 0b01010001  # x0 isolated violet, x4 isolated violet, x6 isolated violet
        hgr[start + 1] = 0b10000011  # x7 and x8 adjacent white, alternate phase
        hgr[start + 2] = 0b10001010  # x15 orange, x17 orange
        pixels = pb_art.hgr_to_overlay_pixels(bytes(hgr))
        self.assertEqual(len(pixels), 192)
        self.assertEqual(len(pixels[0]), 154)
        self.assertEqual(pixels[0][:20], [0] * 20)
        self.assertEqual(pixels[64][0], 14)
        self.assertEqual(pixels[64][4], 14)
        self.assertEqual(pixels[64][6:9], [4, 4, 4])
        self.assertEqual(pixels[64][15], 7)
        chunk = make_tables.overlay_chunk(pixels)
        tiles, data = make_tables.decode_overlay(chunk)
        self.assertTrue(tiles[3 * 8] & 1)
        self.assertIn((8, 0), data)
        with self.assertRaises(ValueError):
            pb_art.hgr_to_overlay_pixels(bytes(16))


if __name__ == "__main__":
    unittest.main()
