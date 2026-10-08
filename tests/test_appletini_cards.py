"""Exercise the native slot-7 protocol through guest code and bus accesses."""

import ctypes as C
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/appletini"


class CardsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["make", "-C", str(TOOL)], check=True, capture_output=True)
        suffix = "dylib" if sys.platform == "darwin" else "so"
        cls.lib = C.CDLL(str(TOOL / f"build/libappletini.{suffix}"))
        signatures = {
            "ap_new": ([C.c_char_p, C.c_char_p, C.c_double, C.c_double,
                        C.c_uint, C.c_uint, C.c_char_p, C.c_size_t], C.c_void_p),
            "ap_free": ([C.c_void_p], None),
            "ap_get": ([C.c_void_p, C.c_char_p], C.c_uint64),
            "ap_set_reg": ([C.c_void_p, C.c_char_p, C.c_uint], C.c_int),
            "ap_run": ([C.c_void_p, C.c_uint64, C.c_uint64,
                        C.POINTER(C.c_uint16), C.c_uint], C.c_int),
            "ap_read": ([C.c_void_p, C.c_uint, C.c_uint, C.c_uint,
                         C.c_void_p, C.c_size_t], C.c_int),
            "ap_write": ([C.c_void_p, C.c_uint, C.c_uint, C.c_uint,
                          C.c_void_p, C.c_size_t], C.c_int),
            "ap_bus_read": ([C.c_void_p, C.c_uint], C.c_int),
            "ap_bus_write": ([C.c_void_p, C.c_uint, C.c_uint], C.c_int),
            "ap_slot7": ([C.c_void_p, C.c_char_p], C.c_int),
            "ap_mount_disk": ([C.c_void_p, C.c_char_p], C.c_int),
            "ap_card_read": ([C.c_void_p, C.c_char_p, C.c_uint,
                              C.c_void_p, C.c_size_t], C.c_int),
            "ap_halt": ([C.c_void_p], C.c_char_p),
            "ap_input": ([C.c_void_p, C.c_char_p, C.c_int, C.c_int], C.c_int),
            "ap_prodos": ([C.c_void_p, C.c_char_p, C.c_char_p], C.c_int),
        }
        for name, (args, result) in signatures.items():
            function = getattr(cls.lib, name)
            function.argtypes, function.restype = args, result

    def setUp(self):
        error = C.create_string_buffer(256)
        self.m = self.lib.ap_new(None, None, 13_000_000, 63.695246, 262, 128,
                                 error, len(error))
        self.assertTrue(self.m, error.value)
        self.addCleanup(self.lib.ap_free, self.m)
        self.work = tempfile.TemporaryDirectory(prefix="appletini-cards-")
        self.addCleanup(self.work.cleanup)
        self.disk = Path(self.work.name) / "test.po"
        self.original = bytes(range(256)) * 4
        self.disk.write_bytes(self.original)
        self.assertEqual(self.lib.ap_mount_disk(self.m, str(self.disk).encode()), 1)

    def read(self, addr, size, kind=0, bank=0):
        output = C.create_string_buffer(size)
        self.assertEqual(self.lib.ap_read(self.m, kind, bank, addr, output, size), 1)
        return output.raw

    def write(self, addr, data, kind=0, bank=0):
        self.assertEqual(self.lib.ap_write(self.m, kind, bank, addr, data, len(data)), 1)

    def br(self, address):
        return self.lib.ap_bus_read(self.m, address)

    def bw(self, address, value):
        self.assertEqual(self.lib.ap_bus_write(self.m, address, value), 1)

    def card(self, kind, size):
        output = C.create_string_buffer(size)
        self.assertEqual(self.lib.ap_card_read(self.m, kind.encode(), 0, output, size), 1)
        return output.raw

    def command(self, family, payload, count):
        self.assertEqual(self.br(0xC701), 0x20)
        for value in payload:
            self.bw(0xCFF0, value)
        self.bw(0xCFF1, family)
        self.assertEqual(self.br(0xCFF1) & 0xC0, 0x80)
        self.assertEqual(self.br(0xCFF1) & 0x20, 0, "UltraWarp has no private vTW port")
        output = []
        for _ in range(count):
            first = self.br(0xCFF0)
            self.assertEqual(self.br(0xCFF0), first, "DATA must not pop on read")
            output.append(first)
            self.bw(0xCFF2, 0)
        return bytes(output)

    @staticmethod
    def request(command, unit=1, selector=0):
        return bytes((command, 3, unit, 0, 6, selector, 0, 0, 0, 0))

    def run_program(self, code, steps=50):
        self.write(0x2000, code)
        self.assertEqual(self.lib.ap_set_reg(self.m, b"pc", 0x2000), 1)
        return self.lib.ap_run(self.m, steps, 0, None, 0)

    def test_fifo_status_getdib_and_explicit_errors(self):
        dib = self.command(2, self.request(0, unit=0, selector=3), 32)
        self.assertEqual(dib[:4], b"\0\x1d\0\1")
        self.assertEqual(dib[11], 12)
        self.assertEqual(dib[12:24], b"Appletini SP")
        device = self.command(2, self.request(0, selector=3), 28)
        self.assertEqual(device[:7], b"\0\x19\0\xf8\2\0\0")
        self.assertEqual(device[8:20], b"Appletini HD")
        self.assertEqual(self.command(2, self.request(0, unit=2), 1), b"\x28")
        self.assertEqual(self.command(2, self.request(9), 1), b"\x21")
        self.assertEqual(self.command(2, b"\1", 1), b"\x21")
        self.assertEqual(self.command(2, self.request(3), 1), b"\x2b")
        self.br(0xCFFF)
        self.assertEqual(self.br(0xCFF1), 0)

    def test_fifo_blocks_overlay_and_write_preflight(self):
        result = self.command(2, self.request(1, selector=1), 513)
        self.assertEqual(result, b"\0" + self.original[512:])
        replacement = b"z" * 512
        self.assertEqual(self.command(0x82, self.request(2), 1), b"\0")
        self.assertEqual(self.command(2, replacement, 1), b"\0")
        self.assertEqual(self.command(2, self.request(1), 513), b"\0" + replacement)
        self.assertEqual(self.disk.read_bytes(), self.original)
        self.assertEqual(self.command(2, self.request(1, selector=2), 1), b"\x27")
        prodos = bytes((1, 0x70, 0, 6, 0, 0))
        self.assertEqual(self.command(1, prodos, 513), b"\0" + replacement)

    def test_amem_coexists_and_ignores_unspecified_padding(self):
        request = bytearray(self.request(0, unit=0, selector=0x80))
        request[6:] = b"ABCD"
        result = self.command(2, request, 35)
        self.assertEqual(result[:7], b"\0\x20\0AMEM")
        self.assertEqual(self.lib.ap_halt(self.m), b"")

    def test_smartport_entry_skips_inline_bytes_and_maps_result_buffer(self):
        self.write(0x300, b"\3\0\0\4\3\0\0\0\0")
        self.bw(0xC005, 0)  # RAMWRT -> aux; stack and parameter reads stay main.
        result = self.run_program(b"\x20\x0d\xc7\0\0\3\xdb")
        self.assertEqual(result, 4)
        self.assertEqual(self.read(0x409, 12, kind=1), b"Appletini SP")
        self.assertEqual(self.read(0x409, 12), bytes(12))
        self.assertEqual(self.lib.ap_get(self.m, b"s"), 255)
        self.assertEqual(self.lib.ap_get(self.m, b"p") & 1, 0)
        self.assertEqual(self.lib.ap_get(self.m, b"x"), 29)

    def test_prodos_entry_reads_mounted_blocks(self):
        self.write(0x42, bytes((1, 0x70, 0, 6, 1, 0)))
        self.assertEqual(self.run_program(b"\x20\x0a\xc7\xdb"), 4)
        self.assertEqual(self.read(0x600, 512), self.original[512:])

    def test_supersprite_vram_control_ay_and_slot_exclusion(self):
        self.assertEqual(self.lib.ap_slot7(self.m, b"supersprite"), 1)
        self.assertEqual(self.br(0xC701), 0)
        self.assertEqual(self.br(0xCFF1), 0)
        self.bw(0xC0F1, 0xFF)
        self.bw(0xC0F1, 0x7F)  # Write address 3FFF, then wrap to zero.
        self.bw(0xC0F0, 0xAA)
        self.bw(0xC0F0, 0xBB)
        self.bw(0xC0F1, 0xFF)
        self.bw(0xC0F1, 0x3F)
        self.assertEqual(self.br(0xC0F0), 0xAA)
        self.assertEqual(self.br(0xC0F0), 0xBB)
        self.bw(0xC0F1, 0x80)
        self.br(0xC0F1)  # Status clears partial control command.
        self.bw(0xC0F1, 0x42)
        self.bw(0xC0F1, 0x87)
        self.assertEqual(self.card("supersprite-regs", 8)[7], 0x42)
        self.bw(0xC0FE, 1)
        self.bw(0xC0FC, 0xFF)
        self.assertEqual(self.br(0xC0FE), 15)
        self.bw(0xC0F3, 0)
        self.bw(0xC0F6, 0)
        self.assertEqual(self.card("supersprite-state", 8)[4:6], b"\0\1")
        self.bw(0xC0F7, 0)
        self.assertEqual(self.card("supersprite-regs", 8), bytes(8))
        self.assertEqual(self.card("supersprite-vram", 16384)[0], 0xBB)
        self.assertEqual(self.lib.ap_slot7(self.m, b"smartport"), 1)
        self.assertEqual(self.command(2, self.request(1), 513), b"\0" + self.original[:512])

    def test_supersprite_vblank_irq_is_acknowledged_by_status_read(self):
        self.assertEqual(self.lib.ap_slot7(self.m, b"supersprite"), 1)
        self.br(0xC083)
        self.br(0xC083)
        self.write(0xFFFE, b"\0\x30", kind=2)
        self.write(0x3000, b"\xad\xf1\xc0\xee\0\4\x40")
        self.write(0x2000, b"\xea\x4c\0\x20")
        self.assertEqual(self.lib.ap_set_reg(self.m, b"pc", 0x2000), 1)
        self.assertEqual(self.lib.ap_set_reg(self.m, b"p", 0x20), 1)
        self.bw(0xC0F1, 0x20)
        self.bw(0xC0F1, 0x81)
        ticks = self.lib.ap_get(self.m, b"frame_ticks")
        self.assertEqual(self.lib.ap_run(self.m, 0, ticks, None, 0), 1)
        self.assertEqual(self.read(0x400, 1), b"\1")
        self.assertEqual(self.lib.ap_get(self.m, b"irqs"), 1)
        self.assertEqual(self.card("supersprite-state", 8)[0], 0)

    def test_apple_keys_and_joystick_buttons_are_independent(self):
        for key, button, address in ((b"oa", 0, 0xC061), (b"ca", 1, 0xC062)):
            self.assertEqual(self.lib.ap_input(self.m, key, 1, 0), 1)
            self.assertEqual(self.lib.ap_input(self.m, b"button", button, 0), 1)
            self.assertEqual(self.br(address), 0x80)
            self.assertEqual(self.lib.ap_input(self.m, b"button", button, 1), 1)
            self.assertEqual(self.lib.ap_input(self.m, key, 0, 0), 1)
            self.assertEqual(self.br(address), 0x80)
            self.assertEqual(self.lib.ap_input(self.m, b"button", button, 0), 1)
            self.assertEqual(self.br(address), 0)

    def test_prodos_quit_stops_at_os_exit(self):
        self.assertEqual(self.lib.ap_prodos(self.m, b"TEST", b"TEST.SYSTEM"), 1)
        self.write(0x300, bytes(4))
        self.assertEqual(self.run_program(b"\x20\0\xbf\x65\0\3\xdb"), 5)
        self.assertEqual(self.lib.ap_halt(self.m), b"")
        steps = self.lib.ap_get(self.m, b"steps")
        self.assertEqual(self.lib.ap_run(self.m, 100, 0, None, 0), 5)
        self.assertEqual(self.lib.ap_get(self.m, b"steps"), steps)

    def test_smartport_inline_page_crossing_stack_wrap_and_cmp_flags(self):
        self.write(0x300, b"\3\0\xf0\4\3\0\0\0\0")
        self.write(0x20FC, b"\x20\x0d\xc7\0\0\3\xdb")
        self.assertEqual(self.lib.ap_set_reg(self.m, b"pc", 0x20FC), 1)
        self.assertEqual(self.lib.ap_set_reg(self.m, b"s", 0), 1)
        self.assertEqual(self.lib.ap_run(self.m, 20, 0, None, 0), 4)
        self.assertEqual(self.lib.ap_get(self.m, b"s"), 0)
        self.assertEqual(self.lib.ap_get(self.m, b"pc"), 0x2103)
        self.assertEqual(self.read(0x4F9, 12), b"Appletini SP")
        self.assertEqual(self.lib.ap_get(self.m, b"p") & 0x83, 0x80)

    def test_pending_mouse_irq_precedes_smartport_entry_trap(self):
        self.br(0xC083)
        self.br(0xC083)
        self.write(0xFFFE, b"\0\x30", kind=2)
        self.write(0x3000, b"\x48\xa9\3\x8d\xaf\xc0\x68\x40")
        self.write(0x300, b"\3\0\0\4\3\0\0\0\0")
        self.write(0x2000, b"\x20\x0d\xc7\0\0\3\xdb")
        self.assertEqual(self.lib.ap_set_reg(self.m, b"pc", 0x2000), 1)
        self.assertEqual(self.lib.ap_set_reg(self.m, b"p", 0x20), 1)
        self.assertEqual(self.lib.ap_run(self.m, 1, 0, None, 0), 0)
        self.assertEqual(self.lib.ap_get(self.m, b"pc"), 0xC70D)
        self.bw(0xC0AE, 3)  # Enable mouse and movement IRQ.
        self.assertEqual(self.lib.ap_input(self.m, b"mouse", 1, 0), 1)
        self.assertEqual(self.lib.ap_run(self.m, 1, 0, None, 0), 0)
        self.assertEqual(self.lib.ap_get(self.m, b"pc"), 0x3000)
        self.assertEqual(self.lib.ap_get(self.m, b"irqs"), 1)
        self.assertEqual(self.read(0x409, 12), bytes(12))
        self.assertEqual(self.lib.ap_run(self.m, 30, 0, None, 0), 4)
        self.assertEqual(self.read(0x409, 12), b"Appletini SP")
        self.assertEqual(self.lib.ap_get(self.m, b"s"), 255)

    def test_supersprite_collision_fifth_sprite_and_termination(self):
        self.assertEqual(self.lib.ap_slot7(self.m, b"supersprite"), 1)

        def vram(address, data):
            self.bw(0xC0F1, address & 255)
            self.bw(0xC0F1, 0x40 | (address >> 8))
            for value in data:
                self.bw(0xC0F0, value)

        def register(number, value):
            self.bw(0xC0F1, value)
            self.bw(0xC0F1, 0x80 | number)

        register(1, 0x40)  # Visible, 8x8, unmagnified, IRQ disabled.
        register(5, 0x20)  # Attributes at 1000.
        register(6, 0)     # Patterns at 0000.
        self.bw(0xC0F6, 0)
        vram(0, b"\xff" * 8)
        attributes = bytearray()
        for index in range(5):
            attributes += bytes((10, index * 16, 0, 1))
        attributes += b"\xd0\0\0\0"
        vram(0x1000, attributes)
        self.write(0x2000, b"\xea\x4c\0\x20")
        self.assertEqual(self.lib.ap_set_reg(self.m, b"pc", 0x2000), 1)
        frame = self.lib.ap_get(self.m, b"frame_ticks")

        def next_status():
            self.assertEqual(self.lib.ap_run(self.m, 0, frame, None, 0), 1)
            return self.br(0xC0F1)

        self.assertEqual(next_status(), 0xC4)  # Fifth sprite index 4.
        self.assertEqual(self.br(0xC0F1), 0x44)  # Only frame flag clears.
        vram(0x1005, b"\0")  # Sprite 1 overlaps sprite 0.
        self.assertEqual(next_status(), 0xE4)
        vram(0x1004, b"\xd0")  # First terminator hides all later sprites.
        self.assertEqual(next_status(), 0x9F)
        # Transparent patterns collide too in Appletini's current PS renderer.
        vram(0x1000, bytes((10, 0, 0, 0, 10, 0, 0, 0, 0xD0, 0, 0, 0)))
        self.assertEqual(next_status(), 0xBF)


if __name__ == "__main__":
    unittest.main()
