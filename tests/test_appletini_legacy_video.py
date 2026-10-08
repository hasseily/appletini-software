"""Standard RGB memory-preview checks, including production C golden frames."""
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/appletini'))
from legacy_video import PALETTE, decode, hires_address, text_address


class LegacyVideoTests(unittest.TestCase):
    def setUp(self):
        self.main = bytearray(65536)
        self.aux = bytearray(65536)

    def frame(self, **switches):
        return decode(self.main, self.aux, switches)[1]

    def test_production_rgb_golden_frames(self):
        # Compiled unchanged step_hgr_rgb, step_dhgr_rgb, step_lores_crisp,
        # step_dlores_crisp and palette/helpers from appletini-one commit
        # 1a3e8d38c57814471640c748879af28dbf16b266, apple_cycle_renderer.c
        # and appletini_ntsc.c. Rendered 192x40 cells at scanner x=25..64,
        # RGB8 packed from BGRA32, page1. Input formula is independent of
        # the decoder; hashes retain exact neighboring-byte/color behavior.
        main = bytes(((i * 37) ^ (i >> 3) ^ 0xa5) & 255 for i in range(65536))
        aux = bytes(((i * 11) ^ (i >> 7) ^ 0x5a) & 255 for i in range(65536))
        for switches, dhires, expected in (
            ({'hires': True}, False,
             '9aff3afd45ee8db3ba30777ef9ba92432837efbc4ce7b9cc4f3e58394cee6017'),
            ({'hires': True, 'col80': True}, True,
             '46a34333734f40574414154124c0bfb3f18ba0edf7dac37c93ddf1eacf006ba5'),
            ({}, False,
             '984c6ea08d2449552e8fee2d2dd438775591de771f83907a8c231c87838a57a9'),
            ({'col80': True}, False,
             'b1f490fea3f769daa17b5eca56c5cf66491e95d75b43bd1647f32efb870d02cf'),
        ):
            with self.subTest(switches=switches, dhires=dhires):
                width, rows = decode(main, aux, switches, dhires=dhires)
                self.assertEqual((width, len(rows)), (560, 192))
                self.assertTrue(all(len(row) == 560 * 3 for row in rows))
                self.assertEqual(hashlib.sha256(b''.join(rows)).hexdigest(), expected)

    def test_scattered_screen_rows_and_screen_holes(self):
        self.assertEqual([text_address(y) for y in (0, 8, 64, 128, 184)],
                         [0x400, 0x480, 0x428, 0x450, 0x7d0])
        self.assertEqual([hires_address(y) for y in (0, 1, 8, 64, 191)],
                         [0x2000, 0x2400, 0x2080, 0x2028, 0x3fd0])
        self.main[0x478:0x480] = bytes([255]) * 8  # text page screen hole
        self.assertEqual(set(b''.join(self.frame())), {0})
        self.main[0x428] = 0x91
        rows = self.frame()
        self.assertEqual(rows[64][:42], PALETTE[1] * 14)
        self.assertEqual(rows[68][:42], PALETTE[9] * 14)
        self.assertEqual(rows[56][:42], PALETTE[0] * 14)

    def test_page2_and_80store_change_page_not_video_bank(self):
        self.main[0x400], self.main[0x800], self.aux[0x400] = 1, 2, 3
        self.assertEqual(self.frame()[0][:42], PALETTE[1] * 14)
        self.assertEqual(self.frame(page2=True)[0][:42], PALETTE[2] * 14)
        self.assertEqual(self.frame(page2=True, store80=True)[0][:42], PALETTE[1] * 14)
        self.main[0x2000], self.main[0x4000] = 0, 0x7f
        first = self.frame(hires=True)
        self.assertNotEqual(first, self.frame(hires=True, page2=True))
        self.assertEqual(first, self.frame(hires=True, page2=True, store80=True))

    def test_dlores_aux_rotation_and_80col_without_dhires(self):
        self.main[0x400], self.aux[0x400] = 0x92, 0x41
        rows = self.frame(col80=True)
        self.assertEqual(rows[0][:42], PALETTE[2] * 14)
        self.assertEqual(rows[4][:42], PALETTE[8] * 7 + PALETTE[9] * 7)
        self.assertEqual(rows, decode(self.main, self.aux, {'col80': 1}, dhires=True)[1])

    def test_supplied_rom_inverse_flash_altcharset_and_80_columns(self):
        rom = bytearray([0xff] * 4096)
        # Synthetic ROM independently exercises all three primary address
        # regions, and the alt-only 0x200 region (MouseText/inverse lowercase).
        rom[1 * 8] = 0xfe
        rom[0x400 + 1 * 8] = 0xfd
        rom[0x600 + 1 * 8] = 0xfb
        rom[0x200 + 1 * 8] = 0xf7
        self.main[0x400:0x404] = bytes((0x01, 0x41, 0x81, 0xc1))
        rows = decode(self.main, self.aux, {'text': 1}, video_rom=rom)[1]
        for cell, bit in ((0, 0), (1, 0), (2, 1), (3, 2)):
            pixels = rows[0][cell * 42:(cell + 1) * 42]
            self.assertEqual(pixels, b''.join(PALETTE[15 if x == bit else 0] * 2
                                             for x in range(7)))
        flashing = decode(self.main, self.aux, {'text': 1}, flash=True, video_rom=rom)[1]
        self.assertEqual(flashing[0][:42], rows[0][:42])
        self.assertEqual(flashing[0][42:84], bytes(b ^ 255 for b in rows[0][42:84]))
        alt = decode(self.main, self.aux, {'text': 1, 'altchar': 1},
                     flash=True, video_rom=rom)[1]
        self.assertEqual(alt[0][42:84], PALETTE[0] * 6 + PALETTE[15] * 2 + PALETTE[0] * 6)
        self.main[0x400], self.aux[0x400] = 0x81, 0xc1
        rows = decode(self.main, self.aux, {'text': 1, 'col80': 1}, video_rom=rom)[1]
        self.assertEqual(rows[0][:21], PALETTE[0] * 2 + PALETTE[15] + PALETTE[0] * 4)
        self.assertEqual(rows[0][21:42], PALETTE[0] + PALETTE[15] + PALETTE[0] * 5)

    def test_fallback_text_lowercase_flash_and_mouse_text_marker(self):
        self.main[0x400:0x404] = bytes((0xa0, 0x20, 0x60, 0xe1))
        rows = self.frame(text=True)
        self.assertEqual(rows[0][:42], PALETTE[0] * 14)
        self.assertEqual(rows[0][42:126], PALETTE[15] * 28)
        self.assertNotEqual(rows[2][126:168], PALETTE[0] * 14)  # lowercase a
        flashing = decode(self.main, self.aux, {'text': 1}, flash=True)[1]
        self.assertEqual(flashing[0][84:126], PALETTE[0] * 14)
        self.main[0x400] = 0x40
        self.assertEqual(self.frame(text=True, altchar=True)[0][:42], PALETTE[15] * 14)

    def test_mixed_text_starts_at_scanline_160(self):
        self.main[:] = bytes([0xa0]) * 65536
        full = self.frame(hires=True)
        mixed = self.frame(hires=True, mixed=True)
        text = self.frame(text=True)
        self.assertEqual(mixed[:160], full[:160])
        self.assertEqual(mixed[160:], text[160:])
        self.assertNotEqual(mixed[160:], full[160:])

    def test_hgr_40_column_dhires_is_mono_with_high_bit_carry(self):
        self.main[0x2000:0x2002] = bytes((0x40, 0x80))
        rows = decode(self.main, self.aux, {'hires': 1}, dhires=True)[1]
        self.assertEqual(rows[0][36:45], PALETTE[15] * 3)
        self.assertEqual(rows[0][45:84], PALETTE[0] * 13)
        self.assertEqual(set(rows[0]), {0, 255})

    def test_dhgr_ignores_high_bits_but_hgr_palette_uses_them(self):
        self.main[:] = bytes([1]) * 65536
        before = decode(self.main, self.aux, {'hires': 1, 'col80': 1}, dhires=True)[1]
        hgr = self.frame(hires=True)
        self.main[:] = bytes([129]) * 65536
        self.aux[:] = bytes([128]) * 65536
        self.assertEqual(before, decode(self.main, self.aux, {'hires': 1, 'col80': 1}, dhires=True)[1])
        self.assertNotEqual(hgr, self.frame(hires=True))

    def test_bounds(self):
        with self.assertRaises(ValueError):
            decode(self.main[:-1], self.aux, {})
        with self.assertRaises(ValueError):
            decode(self.main, self.aux, {}, video_rom=bytes(2048))


if __name__ == '__main__':
    unittest.main()
