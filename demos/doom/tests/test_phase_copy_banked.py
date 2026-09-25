#!/usr/bin/env python3
"""Run banked phase copies on the real assembled Apple memory mapper.

Use an existing integrated build; these tests deliberately do not rebuild it,
so they can run beside the larger platform tests without racing their linker.
Set DOOM_PHASE_COPY_BUILD to test a different build directory.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_doom  # noqa: E402

BUILD = Path(os.environ.get("DOOM_PHASE_COPY_BUILD", ROOT / "build/copy-opt"))
DATA = ROOT / "build/data"
READY = ((BUILD / "doom.lbl").is_file() and (DATA / "manifest.json").is_file()
         and run_doom.DEFAULT_ROM.is_file())


def pattern(length, seed):
    """Vary both page and byte so swapped/repeated pages cannot pass."""
    return bytes((seed + 37 * i + 11 * (i >> 8)) & 255 for i in range(length))


@unittest.skipUnless(READY, "requires an integrated phase-copy build and game data")
class PhaseCopyTest(unittest.TestCase):
    def machine(self):
        doom = run_doom.Doom(BUILD, data=DATA, speed=33, fast=True)
        doom.boot()
        m = doom.machine
        self.assertIn("phase_game_end", doom.labels,
                      "build must contain the live-arena phase-copy optimization")
        self.assertIn("_arena_ptr", doom.labels)
        m[0xC008] = 0
        m[0xC002] = 0
        m[0xC004] = 0
        m[0xC08B]
        m[0xC08B]
        self.assertEqual(m[doom.label("phase_game_end")], 0xB8,
                         "initial game load must retain the complete boot image")
        return doom

    def set_arena(self, doom, end):
        address = doom.label("_arena_ptr")
        doom.machine.main[address:address + 2] = end.to_bytes(2, "little")

    def call(self, doom, name, bank, first, last):
        m, cpu = doom.machine, doom.mpu
        self.assertFalse(m.sw["altzp"])
        self.assertFalse(m.sw["ramrd"])
        self.assertFalse(m.sw["ramwrt"])
        self.assertFalse(m.lc_bank2)
        cpu.pc, cpu.sp = doom.label(name), 0xFF
        cpu.a, cpu.x, cpu.y = bank, first, last
        cpu.p |= cpu.INTERRUPT
        sentinel = 0xBFFF
        cpu.stPushWord(sentinel - 1)
        writes = []
        machine_class = type(m)
        original_write = machine_class.__setitem__

        def observe_write(machine, address, value):
            if machine is m and 0x0200 <= address < 0xC000:
                target = machine.bank if machine._aux_selected(address, "ramwrt") else None
                writes.append((target, address))
            original_write(machine, address, value)

        with patch.object(machine_class, "__setitem__", observe_write):
            for _ in range(400000):
                m.step()
                if cpu.pc == sentinel:
                    break
            else:
                self.fail(f"{name} did not return: PC=${cpu.pc:04X}")
        self.assertEqual(cpu.sp, 0xFF)
        self.assertFalse(m.sw["altzp"])
        self.assertFalse(m.sw["ramrd"])
        self.assertFalse(m.sw["ramwrt"])
        self.assertFalse(m.lc_bank2)
        return writes

    def test_renderer_copies_keep_the_callers_range_in_both_directions(self):
        doom = self.machine()
        m = doom.machine
        bank = doom.banked["render_home"]
        self.assertEqual(bank, 122)
        start, end = 0x0C00, 0x1E00
        m.main[0x0200:0xC000] = pattern(0xBE00, 0x19)
        storage = m.bank_memory(bank)
        storage[0x0200:0xC000] = pattern(0xBE00, 0x83)
        expected = bytearray(storage[0x0200:0xC000])
        expected[start - 0x0200:end - 0x0200] = m.main[start:end]
        writes = self.call(doom, "phase_save", bank, start >> 8, end >> 8)
        self.assertEqual(storage[0x0200:0xC000], expected)
        self.assertEqual(writes, [(bank, address) for address in range(start, end)])
        self.assertEqual(m[doom.label("phase_game_end")], 0xB8,
                         "renderer saves must not alter the game extent")

        m.main[0x0200:0xC000] = pattern(0xBE00, 0x57)
        expected = bytearray(m.main[0x0200:0xC000])
        expected[start - 0x0200:end - 0x0200] = storage[start:end]
        writes = self.call(doom, "phase_load", bank, start >> 8, end >> 8)
        self.assertEqual(m.main[0x0200:0xC000], expected)
        self.assertEqual(writes, [(None, address) for address in range(start, end)])
        self.assertEqual(m[doom.label("phase_game_end")], 0xB8)

    def test_game_rounds_live_extent_up_and_never_writes_the_skipped_tail(self):
        for arena_end in (0x4800, 0x4801, 0x487F, 0x48FF, 0xB380):
            with self.subTest(arena_end=f"${arena_end:04X}"):
                doom = self.machine()
                m = doom.machine
                bank = doom.banked["game_home"]
                self.assertEqual(bank, 125)
                start = doom.label("__DATA_RUN__") & 0xFF00
                end = (arena_end + 255) & 0xFF00
                m.main[0x0200:0xC000] = pattern(0xBE00, 0x35)
                self.set_arena(doom, arena_end)
                source = bytes(m.main[start:end])
                storage = m.bank_memory(bank)
                storage[0x0200:0xC000] = pattern(0xBE00, 0xA1)
                expected = bytearray(storage[0x0200:0xC000])
                expected[start - 0x0200:end - 0x0200] = source
                stack = bytes(m.main[0xB800:0xC000])
                writes = self.call(doom, "phase_save", bank, start >> 8, 0xB8)
                self.assertEqual(storage[0x0200:0xC000], expected)
                self.assertEqual(writes, [(bank, address) for address in range(start, end)],
                                 "save wrote outside live pages, including dead scratch or stack")
                self.assertEqual(m[doom.label("phase_game_end")], end >> 8)
                self.assertEqual(m.main[0xB800:0xC000], stack)

                # Renderer replacement destroys the near allocator value.
                # The next load must use the preserved LC byte instead.
                m.main[0x0200:0xB800] = pattern(0xB600, 0xCF)
                self.set_arena(doom, 0x2201)
                expected = bytearray(m.main[0x0200:0xC000])
                expected[:end - 0x0200] = storage[0x0200:end]
                writes = self.call(doom, "phase_load", bank, 0x02, 0xB8)
                self.assertEqual(m.main[0x0200:0xC000], expected)
                self.assertEqual(writes, [(None, address) for address in range(0x0200, end)],
                                 "load did not use the saved game extent")
                self.assertEqual(m.main[0xB800:0xC000], stack)
                self.assertEqual(m[doom.label("phase_game_end")], end >> 8)

    def test_extent_grows_and_shrinks_between_game_renderer_pairs(self):
        doom = self.machine()
        m = doom.machine
        game_bank = doom.banked["game_home"]
        render_bank = doom.banked["render_home"]
        storage = m.bank_memory(game_bank)
        start = doom.label("__DATA_RUN__") & 0xFF00
        # Exercise the initial load before any allocator extent was saved.
        expected_boot = bytes(storage[0x0200:0xB800])
        stack = pattern(0x0800, 0xE7)
        m.main[0xB800:0xC000] = stack
        writes = self.call(doom, "phase_load", game_bank, 0x02, 0xB8)
        self.assertEqual(m.main[0x0200:0xB800], expected_boot)
        self.assertEqual(writes, [(None, address) for address in range(0x0200, 0xB800)])

        for step, arena_end in enumerate((0x4801, 0x7300, 0x4200, 0x7301)):
            with self.subTest(step=step, arena_end=f"${arena_end:04X}"):
                end = (arena_end + 255) & 0xFF00
                m.main[start:0xB800] = pattern(0xB800 - start, 0x21 + step)
                self.set_arena(doom, arena_end)
                active = bytes(m.main[start:arena_end])
                tail = bytes(storage[end:0xC000])
                self.call(doom, "phase_save", game_bank, start >> 8, 0xB8)
                self.assertEqual(storage[start:arena_end], active)
                self.assertEqual(storage[end:0xC000], tail)
                self.assertEqual(m[doom.label("phase_game_end")], end >> 8)

                # Use the real renderer restore helper to overwrite game BSS.
                m.bank_memory(render_bank)[0x0200:0x8D00] = pattern(0x8B00, 0x93 + step)
                self.call(doom, "phase_load", render_bank, 0x02, 0x8D)
                self.assertEqual(m[doom.label("phase_game_end")], end >> 8)
                dead_main = bytes(m.main[end:0xC000])
                self.call(doom, "phase_load", game_bank, 0x02, 0xB8)
                self.assertEqual(m.main[start:arena_end], active)
                self.assertEqual(m.main[end:0xC000], dead_main)
                self.assertEqual(m.main[0xB800:0xC000], stack)


if __name__ == "__main__":
    unittest.main()
