#!/usr/bin/env python3
"""Banked game execution against the existing flat 65C02 reference.

The banked side uses actual Apple II RAMRD/RAMWRT/ALTZP/RamWorks mapping,
including every opcode fetch. These are correctness tests, not TURBO timings.
"""
import json
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests/host"))
import bankedsim  # noqa: E402
import test_game_core as core  # noqa: E402
import test_game_sim as reference  # noqa: E402


class Banked(bankedsim.BankedGame, reference.Flat):
    """Share the existing semantic state readers, with actual banked memory."""

    def rview(self):
        # BANKED_GAME streams the header and records to its packet bank.
        raw = self.bank(124)[0x0200:0x0200 + 40 + 20 * 128]
        x, y, z, angle, extra, cmap, tic, nth, nps = struct.unpack_from("<iiiHBBHBB", raw)
        sprites = [struct.unpack_from("<BBii", raw, 20 + 10 * i) for i in range(nps)]
        things = [struct.unpack_from("<iiiHBBBBH", raw, 40 + 20 * i) for i in range(nth)]
        return dict(x=x, y=y, z=z, angle=angle, extralight=extra, colormap=cmap,
                    tic=tic, psprites=sprites, things=things)


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class BankedDifferentialTest(unittest.TestCase):
    def test_all_episode_one_maps_at_nightmare(self):
        game = Banked()
        immutable_end = game.L["__DATA_RUN__"]
        immutable_code = bytes(game.mem[0x0200:immutable_end])
        game.boot()
        reports = []
        for mapnum in range(1, 10):
            with self.subTest(map=mapnum):
                game.mem[game.L["_gameskill"]] = reference.O["sk_nightmare"]
                game.mem[game.L["_gamemap"]] = mapnum
                game.mem[game.L["_gameaction"]] = 1
                game.tic()
                for tic in range(36 if mapnum == 7 else 6):
                    game.tic(move=reference.KM_FORWARD if tic % 3 == 0 else 0,
                             buttons=reference.KB_FIRE, mouse=5)
                game.frame()
                self.assertEqual(game.byte("_gamemap"), mapnum)
                pool_bytes = game.word("_mobjs_end") - game.word("_mobjs")
                self.assertEqual(pool_bytes, 160 * reference.O["MO_SIZE"])
                self.assertTrue(game.stack_guard_intact())
                self.assertEqual(bytes(game.mem[0x0200:immutable_end]), immutable_code,
                                 "game code/RODATA changed; the phase snapshot skips them")
                reports.append(dict(map=mapnum, usage=game.stack_usage()))
        (bankedsim.OUT / "all-maps-stack-usage.json").write_text(
            json.dumps(reports, indent=2) + "\n")

    def compare(self, banked, flat, where, packet=False):
        for name in ("_leveltime",):
            self.assertEqual(banked.word(name), flat.word(name), f"{where}: {name}")
        for name in ("_prndindex", "_snd_count"):
            self.assertEqual(banked.byte(name), flat.byte(name), f"{where}: {name}")
        for reader in ("player", "player_more", "inventory", "things", "actor_extras"):
            self.assertEqual(getattr(banked, reader)(), getattr(flat, reader)(), f"{where}: {reader}")
        if packet:
            banked.frame()
            flat.frame()
            got, expected = banked.rview(), flat.rview()
            got["things"] = sorted(got["things"])
            expected["things"] = sorted(expected["things"])
            self.assertEqual(got, expected, f"{where}: render packet")

    def test_two_maps_with_movement_weapons_and_monsters(self):
        banked = Banked()
        self.assertEqual(banked.bank_groups["control"], 0,
                         "the control bank must use base auxiliary LC")
        flat = reference.Flat(out=ROOT / "build/host/banked-reference")
        banked.boot()
        flat.boot()
        self.compare(banked, flat, "E1M1 boot", packet=True)
        script = ([dict(move=reference.KM_FORWARD)] * 10
                  + [dict(buttons=reference.KB_FIRE, mouse=20)] * 18
                  + [dict(move=reference.KM_STRAFEL, buttons=reference.KB_RUN)] * 8)
        for tic, args in enumerate(script, 1):
            banked.tic(**args)
            flat.tic(**args)
            self.compare(banked, flat, f"E1M1 tic {tic}", packet=tic % 6 == 0)
        self.assertGreater(banked.byte("_snd_count"), 0, "weapon/monster actions ran")
        for game in (banked, flat):
            game.mem[game.L["_gamemap"]] = 8
            game.mem[game.L["_gameaction"]] = 1
            game.tic()
        self.compare(banked, flat, "E1M8 load", packet=True)
        for tic in range(1, 13):
            args = dict(move=reference.KM_FORWARD if tic < 7 else reference.KM_LEFT,
                        buttons=reference.KB_FIRE)
            banked.tic(**args)
            flat.tic(**args)
            self.compare(banked, flat, f"E1M8 tic {tic}", packet=tic % 6 == 0)
        usage = banked.stack_usage()
        (bankedsim.OUT / "stack-usage.json").write_text(json.dumps(usage, indent=2) + "\n")
        self.assertLess(usage["software_written_bytes"], 2048)
        self.assertIn(0, usage["hardware_written_bytes"],
                      "control execution did not use base auxiliary stack")
        self.assertTrue(banked.stack_guard_intact())
        self.assertTrue(all(depth < 256 for depth in usage["hardware_written_bytes"].values()))


if __name__ == "__main__":
    unittest.main()
