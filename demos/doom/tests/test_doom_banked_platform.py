#!/usr/bin/env python3
"""The complete banked DOOM loader, game and renderer on the Apple mapper.

Boots the assembled ProDOS loader through FakeProDOS, executes real kernel
far copies and phase swaps, then drives input at actual main-kernel frame
boundaries. Cycle reports are properties of the test model, not hardware
TURBO performance estimates (PSRAM/cache/batched-video timing is not modeled).
"""
import json
import struct
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_doom  # noqa: E402

BUILD = ROOT / "build/host/banked-platform"
DATA = ROOT / "build/data"
READY = (DATA / "manifest.json").is_file() and run_doom.DEFAULT_ROM.is_file()


@unittest.skipUnless(READY, "requires converted game data and enhanced Apple II ROM")
class BankedPlatformTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, str(ROOT / "tools/build_banked.py"),
                        "--build", str(BUILD), "--data", str(DATA),
                        "--python", sys.executable], check=True,
                       stdout=subprocess.DEVNULL)
        subprocess.run([sys.executable, str(ROOT / "tools/check_link.py"),
                        "--build", str(BUILD)], check=True, stdout=subprocess.DEVNULL)

    def test_prodos_loader_and_live_game_render_frames(self):
        doom = run_doom.Doom(BUILD, data=DATA, fast=False)
        doom.boot()
        machine, cpu = doom.machine, doom.mpu
        meta = doom.banked
        self.assertIsNotNone(machine.prodos)
        self.assertFalse(machine.sw["altzp"])
        self.assertEqual(cpu.pc, doom.label("kernel_start"))
        # Check installation before gameplay can legitimately modify state.
        for bank in meta["banks"].values():
            self.assertEqual(machine.bank_memory(bank)[0xD000:0x10000],
                             (BUILD / f"GBANK{bank}.BIN").read_bytes(), f"code bank {bank}")
            stage = meta["code_staging"][str(bank)]
            self.assertEqual(machine.bank_memory(stage)[0x0200:0x3200],
                             (BUILD / f"GBANK{bank}.BIN").read_bytes(), f"staging bank {stage}")
        self.assertEqual(meta["banks"]["control"], 0)
        control_image = (BUILD / "GBANK0.BIN").read_bytes()
        control_code_end = doom.label("_rview")
        self.assertTrue(0xD000 < control_code_end < 0xFFFA)
        game_image = doom.files["GAME.BIN"]
        self.assertEqual(machine.bank_memory(meta["game_home"])[0x0200:0x0200 + len(game_image)],
                         game_image)
        for filename, bank, base in (("GAME.TABLES", meta["tables_bank"], 0x0200),
                                     ("GAME.INFO", meta["info_bank"], 0x6000)):
            image = (BUILD / filename).read_bytes()
            self.assertEqual(machine.bank_memory(bank)[base:base + len(image)], image, filename)

        def main_pc(name):
            # Auxiliary LC instructions deliberately reuse kernel addresses.
            return not machine.sw["altzp"] and cpu.pc == doom.label(name)

        def advance_to(name, limit=200_000_000):
            start = cpu.processorCycles
            while cpu.processorCycles - start < limit:
                machine.step()
                if main_pc("kernel_crash_stop"):
                    self.fail(f"kernel crash ${doom.byte('kcrash'):02X} while waiting for {name}")
                if main_pc(name):
                    return
            self.fail(f"no main {name}: PC=${cpu.pc:04X}, bank={machine.bank}, "
                      f"ALTZP={machine.sw['altzp']}")

        advance_to("frame_top")
        render_image = doom.files["RENDER.BIN"]
        self.assertEqual(machine.bank_memory(meta["render_home"])[0x0200:0x0200 + len(render_image)],
                         render_image)
        rows, packets, screens = [], [], []
        previous_cycles, previous_idle = cpu.processorCycles, machine.idle_cycles
        for frame in range(4):
            # The live keyboard/mouse drive the normal kernel input path.
            machine.hold(ord("W"))
            machine.mouse_delta(16, 0)
            advance_to("present_done")
            raw = machine.bank_memory(meta["packet_bank"])[meta["packet_address"]:
                                                           meta["packet_address"] + 20]
            packet = struct.unpack("<iiiHBBHBB", raw)
            packets.append(packet)
            pixels = bytes(machine.bank_memory(0)[0x2000:0x2000 + 320 * 84])
            self.assertGreater(len(set(pixels)), 8, "rendered SHR view is blank or uniform")
            screens.append(pixels)
            self.assertEqual(doom.byte("kcrash"), 0)
            self.assertFalse(machine.sw["altzp"])
            self.assertGreater(packet[7], 0, "the game published no visible things")
            # SHR, palettes, debug output and serial snapshots use base aux
            # lower RAM. They must never alter resident control LC code or
            # vectors; only GVIEW in that LC image is mutable packet storage.
            self.assertEqual(machine.bank_memory(0)[0xD000:control_code_end],
                             control_image[:control_code_end - 0xD000])
            self.assertEqual(machine.bank_memory(0)[0xFFFA:0x10000], control_image[-6:])
            strip = bytes(machine.bank_memory(0)[0x2000 + 320 * 88:0x2000 + 320 * 95])
            self.assertEqual(set(strip), {0, 4}, "hardware debug readout is missing")
            rows.append(dict(frame=frame, tics=doom.word("ktics"), packet_tic=packet[6],
                             model_work_cycles=cpu.processorCycles - previous_cycles
                             - (machine.idle_cycles - previous_idle),
                             model_frame_budget=machine.frame_cycles))
            previous_cycles, previous_idle = cpu.processorCycles, machine.idle_cycles
            if frame < 3:
                advance_to("frame_top")
        self.assertGreater(rows[-1]["tics"], rows[0]["tics"])
        self.assertGreater(packets[-1][6], packets[0][6])
        self.assertNotEqual(packets[-1][:4], packets[0][:4], "camera did not respond to input")
        self.assertNotEqual(screens[-1], screens[0], "display did not respond to the camera")
        machine.shr_image().save(BUILD / "banked-platform-final.png")
        (BUILD / "banked-platform-report.json").write_text(json.dumps(dict(
            timing_scope="test-model cycles only; not hardware TURBO timing",
            boot_model_cycles=doom.boot_cycles, frames=rows), indent=2) + "\n")

    def test_readout_clock_carry_from_main_and_auxiliary_irq(self):
        doom = run_doom.Doom(BUILD, data=DATA, fast=True)
        doom.boot()
        machine, cpu = doom.machine, doom.mpu
        clock = doom.label("vbl_count")

        def interrupt_and_return():
            saved_pc, saved_sp = cpu.pc, cpu.sp
            cpu.p &= ~cpu.INTERRUPT
            machine.mouse.vbl_pending = machine.mouse.irq = True
            cpu.irq()
            for _ in range(200):
                machine.step()
                if cpu.pc == saved_pc:
                    self.assertEqual(cpu.sp, saved_sp)
                    return
            self.fail("debug-clock IRQ did not return")

        # Both physical IRQ routes must update the same wide main clock.
        machine.main[clock:clock + 2] = b"\xFF\x12"
        cpu.pc, cpu.sp = 0x1234, 0xFF
        interrupt_and_return()
        self.assertEqual(machine.main[clock:clock + 2], b"\x00\x13")
        image = doom.files["GAME.BIN"]
        machine.main[0x0200:0x0200 + len(image)] = image
        machine.main[doom.label("gb_saved_sp") + 0x80] = 0xF0
        for group in ("control", "weapons"):
            with self.subTest(group=group):
                machine[0xC008] = 0
                machine.main[clock:clock + 2] = b"\xFF\xFF"
                machine[0xC073] = doom.banked["banks"][group]
                machine[0xC009] = 0
                cpu.pc, cpu.sp = 0xD111, 0xFA
                interrupt_and_return()
                self.assertTrue(machine.sw["altzp"])
                self.assertEqual(machine.main[clock:clock + 2], b"\x00\x00")


if __name__ == "__main__":
    unittest.main()
