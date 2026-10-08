"""Standard SHR preview semantics against the Appletini renderer contract."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'appletini'))
from video import decode_shr


class SHRTests(unittest.TestCase):
    def test_display_geometry_is_independent_of_framebuffer_pixel_count(self):
        from cli import Machine, parser
        from video import frame_png
        machine = Machine(parser().parse_args(['debug', '--hex', 'db']))
        self.addCleanup(machine.close)

        def geometry():
            _, info = frame_png(machine)
            return tuple(info[key] for key in ('width', 'height', 'display_width', 'display_height'))

        self.assertEqual(geometry(), (560, 192, 560, 384))
        machine.check(machine.lib.ap_bus_write(machine.handle, 0xc029, 0xc1))
        self.assertEqual(geometry(), (320, 200, 640, 400))
        machine.write('aux0', 0x9d00, b'\x80')
        self.assertEqual(geometry(), (640, 200, 640, 400))
        machine.check(machine.lib.ap_slot7(machine.handle, b'supersprite'))
        machine.slot7 = 'supersprite'
        self.assertEqual(geometry(), (256, 192, 560, 384))

    def test_320_palette_high_nibble_first_and_firmware_scale(self):
        bank = bytearray(0x8000)
        bank[0] = 0x12
        bank[0x7e02:0x7e06] = bytes.fromhex('000ff000')
        width, rows = decode_shr(bank)
        self.assertEqual((width, len(rows), len(rows[0])), (320, 200, 960))
        self.assertEqual(rows[0][:6], bytes((240, 0, 0, 0, 240, 0)))

    def test_fill_carries_across_bytes_but_resets_each_scanline(self):
        bank = bytearray(0x8000)
        bank[0x7d00:0x7d02] = b'\x20\x20'
        bank[0x7e02:0x7e04] = b'\x0f\x00'
        bank[0] = 0x10
        _, rows = decode_shr(bank)
        self.assertEqual(rows[0], bytes((0, 0, 240)) * 320)
        self.assertEqual(rows[1], bytes(960))

    def test_640_palette_quadrants_and_mixed_geometry(self):
        bank = bytearray(0x8000)
        bank[0x7d00] = 0x80
        bank[0] = 0x1b  # Values 0,1,2,3 select colors 8,13,2,7.
        for color in range(16):
            bank[0x7e00 + 2 * color] = color
        width, rows = decode_shr(bank)
        self.assertEqual(width, 640)
        self.assertEqual(rows[0][:12], b''.join(bytes((0, 0, i * 16)) for i in (8, 13, 2, 7)))
        self.assertTrue(all(len(row) == 1920 for row in rows))

    def test_rejects_extended_modes_and_wrong_size(self):
        with self.assertRaises(ValueError):
            decode_shr(b'')
        for magic in (b'SHR4', b'3200', bytes.fromhex('d3c8d2b4')):
            bank = bytearray(0x8000)
            bank[0x7dfc:0x7e00] = magic
            with self.assertRaises(ValueError):
                decode_shr(bank)


if __name__ == '__main__':
    unittest.main()
