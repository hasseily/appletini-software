#!/usr/bin/env python3
"""Packet flag lookups match the full metadata in real banked memory."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests/host"))
import bankedsim  # noqa: E402
import test_game_core as core  # noqa: E402
import test_game_sim as reference  # noqa: E402
import profile_doom  # noqa: E402


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class PacketFlagsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.game = bankedsim.BankedGame(out=ROOT / "build/packet-opt/test-game")

    def test_every_type_matches_full_metadata(self):
        game = self.game
        control_bank = game.bank_groups["control"]
        table = game.machine.bank_memory(control_bank)
        address = game.L[f"gb{control_bank}_mi_viewflags"]
        self.assertGreaterEqual(address, 0xD000)
        self.assertLessEqual(address + reference.O["NUMMOBJTYPES"], 0xFFFA)
        self.assertNotIn("_mi_viewflags", game.L, "lookup leaked into near RAM")
        info = game.machine.bank_memory(1)
        count = reference.O["NUMMOBJTYPES"]
        self.assertEqual(count, 90)
        for kind in range(count):
            flags = 0x6000 + kind * reference.O["MI_SIZE"] + reference.O["MI_FLAGS"]
            with self.subTest(kind=kind):
                self.assertEqual(table[address + kind],
                                 (info[flags] & 0x08) | (info[flags + 2] & 0x04))

    def test_packet_does_not_fetch_object_metadata(self):
        game = self.game
        game.boot()
        reads = []
        trap_address = game.L["trap_far_read"]
        original = game.traps[trap_address]

        def record_read():
            reads.append(game.mem[game.L["far_src"] + 2])
            return original()

        game.traps[trap_address] = record_read
        try:
            game.frame()
        finally:
            game.traps[trap_address] = original
        self.assertNotIn(1, reads, "packet construction still fetches mobjinfo")

    def test_scratch_excludes_arena_and_video_memory(self):
        game = self.game
        start = game.L["_intercepts"]
        length = game.L["__GINTERCEPTS_SIZE__"]
        end = start + length
        self.assertEqual((start, length, end), (0xB380, 1152, 0xB800))
        self.assertEqual(game.word("_arena_bounds", 2), start)
        self.assertEqual(game.word("_arena_bounds"),
                         game.L["__BSS_RUN__"] + game.L["__BSS_SIZE__"])
        self.assertEqual(end, game.machine.software_stack_floor)

    def test_scratch_poison_does_not_change_packet_or_post_video_writes(self):
        game = self.game
        game.boot()
        game.frame()

        def active_packet():
            raw = game.bank(124)[0x0200:0x0200 + 2600]
            nthings, npsprites = raw[18], raw[19]
            return bytes(raw[:20] + raw[20:20 + npsprites * 10]
                         + raw[40:40 + nthings * 20])

        expected = active_packet()
        control_bank = game.bank_groups["control"]
        control_storage = game.machine.bank_memory(control_bank)
        packet_start = game.L["_rview"]
        packet_end = packet_start + 2600

        def immutable_control():
            # The packet is mutable; the resident control code, lookup
            # tables and IRQ vectors surrounding it must stay intact.
            return bytes(control_storage[0xD000:packet_start]
                         + control_storage[packet_end:0x10000])

        code_and_vectors = immutable_control()
        start = game.L["_intercepts"]
        end = start + game.L["__GINTERCEPTS_SIZE__"]
        symbols = profile_doom.Symbols(ROOT / "build/packet-opt/test-game/game.dbg")
        machine_class = type(game.machine)
        original_write = machine_class.__setitem__

        for seed in (0x55, 0xA7):
            with self.subTest(seed=seed):
                game.machine.main[start:end] = bytes(
                    (seed + 37 * i) & 0xFF for i in range(end - start))
                guards = bytes((game.machine.main[start - 1], game.machine.main[end]))
                scratch_writes = []
                view_video_writes = []

                def observe_write(machine, address, value):
                    if 0x0200 <= address < 0xC000 and not machine._aux_selected(address, "ramwrt"):
                        if start <= address < end:
                            scratch_writes.append(address)
                        if (0x0400 <= address < 0x0C00 or 0x2000 <= address < 0x6000):
                            if machine.sw["altzp"] and machine.bank == control_bank:
                                owner = symbols.lookup(f"bank:{control_bank}:lc2", machine.mpu.pc)
                                # The shared 32-bit work area still has a
                                # few writes here; it is distinct from the
                                # candidate/path scratch being relocated.
                                in_work_area = game.L["W"] <= address < game.L["W"] + 256
                                if owner["module"] == "a_view.o" and not in_work_area:
                                    view_video_writes.append(address)
                    original_write(machine, address, value)

                # Scope the observer to this frame and restore the normal mapper.
                with patch.object(machine_class, "__setitem__", observe_write):
                    game.frame()
                self.assertEqual(active_packet(), expected)
                self.assertEqual(immutable_control(), code_and_vectors,
                                 "packet/far calls modified resident control code or IRQ vectors")
                self.assertGreater(len(scratch_writes), 2600,
                                   "packet construction did not exercise the relocated scratch")
                self.assertEqual(view_video_writes, [],
                                 "view scratch stores entered a posted video window")
                self.assertEqual(bytes((game.machine.main[start - 1], game.machine.main[end])),
                                 guards, "packet construction overwrote a scratch boundary")


if __name__ == "__main__":
    unittest.main()
