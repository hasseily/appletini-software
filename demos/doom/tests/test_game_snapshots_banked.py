#!/usr/bin/env python3
"""Sector snapshots must avoid the banked build's persistent phase images."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests/host"))
import bankedsim  # noqa: E402
import gamesim  # noqa: E402
import test_game_core as core  # noqa: E402

OUT = ROOT / "build/host/banked-snapshots"


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class BankedSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.game = bankedsim.BankedGame(out=OUT)
        self.game.boot()
        self.manifest = json.loads((gamesim.DATA / "manifest.json").read_text())

    def force_rollover(self, bank):
        game = self.game
        game.mem[game.L["snap_nextbank"]] = bank
        cursor = game.L["snap_next"]
        game.mem[cursor:cursor + 2] = (0xBFF0).to_bytes(2, "little")

    def sector_chunks(self, mapnum):
        desc = self.manifest["maps"][f"E1M{mapnum}"]["arrays"]["SECTORS"]
        remaining = desc["count"]
        bank = desc["bank"]
        while remaining:
            count = min(remaining, 1 << desc["log2"])
            yield self.game.bank(bank), desc["addr"], count * desc["elsize"]
            remaining -= count
            bank += 1

    def test_rollover_skips_phase_images_and_roundtrips_sectors(self):
        game = self.game
        # Actual mapped RAM, including the banks occupied by the phase images.
        reserved = {}
        for bank in (125, 124, 122):
            canary = bytes([bank]) * (0xC000 - 0x0200)
            game.bank(bank)[0x0200:0xC000] = canary
            reserved[bank] = canary

        for mapnum, start, expected_bank in ((2, 126, 123), (3, 123, 121)):
            with self.subTest(map=mapnum):
                chunks = list(self.sector_chunks(mapnum))
                original = b"".join(bytes(bank[addr:addr + size])
                                    for bank, addr, size in chunks)
                self.force_rollover(start)
                game.ccall("_P_ResetLevelData", (mapnum, 1))
                self.assertEqual(game.byte("snap_bank", mapnum - 1), expected_bank)
                address = game.byte("snap_lo", mapnum - 1) | game.byte("snap_hi", mapnum - 1) << 8
                self.assertEqual(address, 0x0200)
                self.assertEqual(bytes(game.bank(expected_bank)[address:address + len(original)]),
                                 original)
                # Revisit restores the sector bytes, exercising the saved
                # bank/address through the same API used by level changes.
                for bank, addr, size in chunks:
                    bank[addr:addr + size] = bytes([0x5A]) * size
                game.ccall("_P_ResetLevelData", (mapnum, 1))
                restored = b"".join(bytes(bank[addr:addr + size])
                                    for bank, addr, size in chunks)
                self.assertEqual(restored, original)
                for bank, canary in reserved.items():
                    self.assertEqual(bytes(game.bank(bank)[0x0200:0xC000]), canary)
                self.assertTrue(game.stack_guard_intact())

    def test_rollover_rejects_data_and_renderer_cache_banks(self):
        # DD_LAST_BANK + 1 belongs to the renderer cache, so exhausting the
        # next bank must crash before overwriting either owner.
        last_data_bank = self.manifest["banks"]["last"]
        self.force_rollover(last_data_bank + 2)
        with self.assertRaisesRegex(gamesim.Crash, r"kernel_crash \$23"):
            self.game.ccall("_P_ResetLevelData", (2, 1))


if __name__ == "__main__":
    unittest.main()
