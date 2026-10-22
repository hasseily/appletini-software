import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location("ti_assets", Path(__file__).resolve().parents[1] / "tools/assets.py")
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


class GraphicsAssets(unittest.TestCase):
    def test_odd_width_pixel_and_mask_rows(self):
        image = assets.indexed(3, 2, [1, 0, 3, 0, 5, 6], True)
        self.assertEqual(image, b"TI4\0\3\0\2\0" + bytes([0x10, 0x30, 0x05, 0x60, 0xA0, 0x60]))

    def test_ppm_binary_header_and_pixel_whitespace(self):
        data = b"P6\n# comment\n2 1\n255\n" + bytes([10, 13, 32, 255, 0, 0])
        self.assertEqual(assets.ppm(data), (2, 1, [(10, 13, 32), (255, 0, 0)]))

    def test_ppm_ascii_and_quantization(self):
        data = b"P3 2 1 255 0 0 0 240 0 0"
        image, palette = assets.convert_ppm(data, [0, "#F00000"])
        self.assertEqual(image[-1], 0x01)
        self.assertEqual(struct.unpack("<16H", palette)[1], 0xF00)

    def test_reject_invalid_image_and_palette(self):
        for args in [(0, 1, []), (321, 1, [0] * 321), (1, 1, [16]), (1, 2, [0])]:
            with self.subTest(args=args[:2]), self.assertRaises(ValueError): assets.indexed(*args)
        for palette in [[], [4096], ["#nope"], [0] * 17]:
            with self.subTest(palette=palette), self.assertRaises(ValueError): assets.palette(palette)

    def test_reject_truncated_ppm(self):
        for data in [b"P6 1 1 255\n\0\0", b"P3 1 1 255 0 0 256", b"P7 1 1 255", b"P3 1 1 15 0 0 0"]:
            with self.subTest(data=data), self.assertRaises(ValueError): assets.ppm(data)

    def test_banked_font_format(self):
        data = assets.font({"width": 3, "height": 2, "first": 65, "glyphs": [[".#.", "###"]]})
        self.assertEqual(data, b"TIF1" + bytes([65, 1, 3, 2, 0x40, 0xE0]))
        with self.assertRaises(ValueError): assets.font({"width": 9, "height": 1, "glyphs": [["........."]]})

    def test_tile_ids_and_shape(self):
        self.assertEqual(assets.tilemap([[0, 1], [1, 0]], 2), b"TIM1\2\0\2\0\0\1\1\0")
        for rows in [[[0], [1, 2]], [[2]], []]:
            with self.subTest(rows=rows), self.assertRaises(ValueError): assets.tilemap(rows, 2)

    def test_pack_sorted_exact_offsets_and_payload(self):
        packed = assets.pack([("B", b"second"), ("A", b"first")])
        self.assertEqual(packed[:8], b"TPK1\2\0\0\0")
        self.assertEqual(packed[8:24], b"A" + bytes(15))
        self.assertEqual(struct.unpack_from("<II", packed, 24), (56, 5))
        self.assertEqual(struct.unpack_from("<II", packed, 48), (61, 6))
        self.assertEqual(packed[56:], b"firstsecond")
        self.assertEqual(packed, assets.pack([("A", b"first"), ("B", b"second")]))

    def test_pack_rejects_invalid_and_duplicate_entries(self):
        for entries in [[], [("a", b"x")], [("A", b"x"), ("A", b"y")], [("A", b"")], [("A", b"x")] * 17]:
            with self.subTest(entries=len(entries)), self.assertRaises(ValueError): assets.pack(entries)


if __name__ == "__main__": unittest.main()
