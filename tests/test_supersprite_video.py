"""Small register/VRAM fixtures exercise the static Appletini VDP preview."""

import unittest

from tools.appletini.supersprite_video import PALETTE, decode


def graphics1():
    vram = bytearray(16384)
    regs = bytearray((0, 0x40, 8, 0xFF, 0, 0x7E, 3, 1))
    vram[0x3F00] = 0xD0  # Empty sprite list.
    return vram, regs


def sprite(vram, index, *, y=255, x=0, pattern=0, color=2, early=False):
    offset = 0x3F00 + index * 4
    vram[offset:offset + 4] = bytes((y, x, pattern, color | (0x80 if early else 0)))
    if index < 31:
        vram[offset + 4] = 0xD0


def pixel(rows, x, y):
    return rows[y][x * 3:x * 3 + 3]


class SuperSpriteVideoTests(unittest.TestCase):
    def test_validation_and_mixed_modes(self):
        with self.assertRaisesRegex(ValueError, "16384"):
            decode(bytes(10), bytes(8))
        with self.assertRaisesRegex(ValueError, "8 VDP registers"):
            decode(bytes(16384), bytes(9))
        for r0, r1 in ((2, 0x50), (2, 0x48), (0, 0x58), (2, 0x58)):
            with self.subTest(r0=r0, r1=r1):
                regs = bytearray(8)
                regs[0], regs[1] = r0, r1
                with self.assertRaisesRegex(ValueError, "mixed"):
                    decode(bytes(16384), regs)

    def test_blank_frame_and_input_immutability(self):
        vram, regs = graphics1()
        regs[1] = 0
        regs[7] = 6
        before = bytes(vram), bytes(regs)
        width, rows = decode(vram, regs)
        self.assertEqual(width, 256)
        self.assertEqual(len(rows), 192)
        self.assertTrue(all(row == b"\xd4\x52\x4d" * 256 for row in rows))
        self.assertEqual((bytes(vram), bytes(regs)), before)

    def test_graphics1_pattern_color_groups_and_zero_backdrop(self):
        vram, regs = graphics1()
        regs[7] = 7
        vram[0x2000] = 9
        vram[9 * 8] = 0x81
        vram[0x3FC1] = 0x20
        _, rows = decode(vram, regs)
        self.assertEqual(pixel(rows, 0, 0), b"\x21\xc8\x42")
        self.assertEqual(pixel(rows, 7, 0), PALETTE[2])
        self.assertEqual(pixel(rows, 1, 0), PALETTE[7])
        self.assertEqual(pixel(rows, 0, 1), PALETTE[7])
        self.assertEqual(pixel(rows, 8, 0), PALETTE[7])

    def test_graphics2_three_banks_ignore_lower_mask_bits_like_firmware(self):
        vram = bytearray(16384)
        regs = bytearray((2, 0x40, 6, 0x80, 0, 0x3F, 7, 1))
        vram[0x1F80] = 0xD0
        for third, color in enumerate((2, 4, 6)):
            vram[0x1800 + third * 256] = 1
            offset = third * 2048 + 8
            vram[offset] = 0x80
            vram[0x2000 + offset] = (color << 4) | 1
        _, rows = decode(vram, regs)
        for third, color in enumerate((2, 4, 6)):
            self.assertEqual(pixel(rows, 0, third * 64), PALETTE[color])
            self.assertEqual(pixel(rows, 1, third * 64), PALETTE[1])
        regs[3], regs[4] = 0xFF, 3
        self.assertEqual(decode(vram, regs)[1], rows)

    def test_text_six_pixel_glyphs_current_firmware_alignment_and_no_sprites(self):
        vram, regs = graphics1()
        regs[1] = 0x50
        regs[7] = 0xF4
        vram[0x2000] = vram[0x2000 + 39] = 1
        vram[8] = 0x84
        sprite(vram, 0, x=10, color=2)
        vram[0x1800:0x1808] = bytes([255]) * 8
        _, rows = decode(vram, regs)
        for x in (0, 5, 234, 239):
            self.assertEqual(pixel(rows, x, 0), PALETTE[15])
        for x in (1, 6, 10, 240, 255):
            self.assertEqual(pixel(rows, x, 0), PALETTE[4])

    def test_multicolor_four_by_four_cells_and_pattern_row_selection(self):
        vram, regs = graphics1()
        regs[1] = 0x48
        vram[:8] = bytes((0x23, 0x45, 0x67, 0x89, 0xAB, 0xCD, 0xEF, 0))
        _, rows = decode(vram, regs)
        for y, left, right in ((0, 2, 3), (3, 2, 3), (4, 4, 5), (8, 6, 7),
                               (24, 14, 15), (28, 1, 1), (32, 2, 3)):
            self.assertEqual(pixel(rows, 0, y), PALETTE[left])
            self.assertEqual(pixel(rows, 3, y), PALETTE[left])
            self.assertEqual(pixel(rows, 4, y), PALETTE[right])
            self.assertEqual(pixel(rows, 7, y), PALETTE[right])

    def test_sprite_priority_transparency_and_terminator(self):
        vram, regs = graphics1()
        vram[0x1800:0x1808] = bytes([255]) * 8
        sprite(vram, 0, color=2)
        sprite(vram, 1, color=6)
        _, rows = decode(vram, regs)
        self.assertEqual(pixel(rows, 0, 0), PALETTE[2])
        vram[0x3F03] = 0
        _, rows = decode(vram, regs)
        self.assertEqual(pixel(rows, 0, 0), PALETTE[6])
        vram[0x3F00] = 0xD0  # Terminator also excludes all later entries.
        _, rows = decode(vram, regs)
        self.assertEqual(pixel(rows, 0, 0), PALETTE[1])

    def test_four_per_line_includes_transparent_and_clipped_sprites(self):
        vram, regs = graphics1()
        vram[0x1800:0x1808] = bytes([255]) * 8
        for index in range(4):
            sprite(vram, index, x=0, color=0, early=True)
        sprite(vram, 4, x=10, color=2)
        _, rows = decode(vram, regs)
        self.assertEqual(pixel(rows, 10, 0), PALETTE[1])
        # Move the first sprite off this line: fifth becomes fourth and draws.
        vram[0x3F00] = 50
        _, rows = decode(vram, regs)
        self.assertEqual(pixel(rows, 10, 0), PALETTE[2])

    def test_sprite_wrapped_negative_y_earlyclock_and_top_plus_one(self):
        vram, regs = graphics1()
        vram[0x1800:0x1808] = bytes([255]) * 8
        sprite(vram, 0, y=254, x=31, color=2, early=True)
        _, rows = decode(vram, regs)
        self.assertEqual(pixel(rows, 0, 0), PALETTE[2])
        self.assertEqual(pixel(rows, 6, 6), PALETTE[2])
        self.assertEqual(pixel(rows, 7, 0), PALETTE[1])
        self.assertEqual(pixel(rows, 0, 7), PALETTE[1])
        sprite(vram, 0, y=0, x=0, color=2)
        _, rows = decode(vram, regs)
        self.assertEqual(pixel(rows, 0, 0), PALETTE[1])
        self.assertEqual(pixel(rows, 0, 1), PALETTE[2])

    def test_16_pixel_sprite_quadrants_and_pattern_alignment(self):
        vram, regs = graphics1()
        regs[1] |= 2
        sprite(vram, 0, pattern=7, color=2)
        # Pattern 7 is aligned down to 4. Quadrant layout is TL, BL, TR, BR.
        base = 0x1800 + 4 * 8
        for offset, bits in ((0, 0x80), (8, 0x40), (16, 0x20), (24, 0x10)):
            vram[base + offset] = bits
        _, rows = decode(vram, regs)
        for x, y in ((0, 0), (1, 8), (10, 0), (11, 8)):
            self.assertEqual(pixel(rows, x, y), PALETTE[2])
        for x, y in ((8, 0), (0, 8), (16, 0), (0, 16)):
            self.assertEqual(pixel(rows, x, y), PALETTE[1])

    def test_magnified_sprites(self):
        for size16 in (False, True):
            with self.subTest(size16=size16):
                vram, regs = graphics1()
                regs[1] |= 1 | (2 if size16 else 0)
                sprite(vram, 0, x=10, color=8)
                vram[0x1800] = 0x80
                _, rows = decode(vram, regs)
                for x, y in ((10, 0), (11, 0), (10, 1), (11, 1)):
                    self.assertEqual(pixel(rows, x, y), PALETTE[8])
                for x, y in ((12, 0), (10, 2)):
                    self.assertEqual(pixel(rows, x, y), PALETTE[1])


if __name__ == "__main__":
    unittest.main()
