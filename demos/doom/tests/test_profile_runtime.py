#!/usr/bin/env python3
"""Execute the hardware profiler through real IRQ, banking and renderer paths.

These checks validate counters and publication, not hardware TURBO timing.
"""
import hashlib
import json
import struct
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import profile_hardware  # noqa: E402
import run_doom  # noqa: E402

BUILD = ROOT / "build/host/profile-runtime"
DATA = ROOT / "build/data"
READY = (DATA / "manifest.json").is_file() and run_doom.DEFAULT_ROM.is_file()


@unittest.skipUnless(READY, "requires converted game data and enhanced Apple II ROM")
class ProfileRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, str(ROOT / "tools/build_banked.py"),
                        "--build", str(BUILD), "--data", str(DATA),
                        "--python", sys.executable, "--profile"], check=True,
                       stdout=subprocess.DEVNULL)
        subprocess.run([sys.executable, str(ROOT / "tools/check_link.py"),
                        "--build", str(BUILD)], check=True, stdout=subprocess.DEVNULL)
        cls.metadata = json.loads((BUILD / "profile.json").read_text())
        cls.layout = profile_hardware.Layout(cls.metadata)

    def machine(self):
        doom = run_doom.Doom(BUILD, data=DATA, speed=33, fast=True)
        doom.boot()
        return doom

    def game_context(self):
        doom = self.machine()
        m = doom.machine
        image = doom.files["GAME.BIN"]
        m.main[0x0200:0x0200 + len(image)] = image
        m.main[doom.label("kspace")] = 1
        m.main[doom.label("gb_saved_sp") + 0x80] = 0xE0
        return doom

    @staticmethod
    def put_word(doom, name, value, offset=0):
        address = doom.label(name) + offset
        doom.machine[address] = value & 255
        doom.machine[address + 1] = (value >> 8) & 255

    def snapshot(self, doom):
        return bytes(doom.machine.bank_memory(0)[0xA000:0xA000 + self.layout.size])

    def call_publish(self, doom):
        m, cpu = doom.machine, doom.mpu
        sentinel = 0xBFFF
        cpu.pc, cpu.sp = doom.label("profile_publish"), 0xFF
        cpu.p |= cpu.INTERRUPT
        cpu.stPushWord(sentinel - 1)
        writes = []
        for _ in range(10000):
            if cpu.pc == doom.label("far_write"):
                pointer = m[doom.label("far_ptr")] | m[doom.label("far_ptr") + 1] << 8
                length = m[doom.label("far_len")] | m[doom.label("far_len") + 1] << 8
                writes.append(bytes(m[pointer + i] for i in range(length)))
            m.step()
            if cpu.pc == sentinel:
                self.assertEqual(cpu.sp, 0xFF)
                self.assertFalse(m.sw["altzp"])
                self.assertFalse(m.sw["ramrd"])
                self.assertFalse(m.sw["ramwrt"])
                return writes
        self.fail(f"profile_publish did not return: ${cpu.pc:04X}")

    def test_irq_all_stages_preserves_registers_and_mapping_and_wraps(self):
        for auxiliary, group in ((False, "control"), (False, "weapons"),
                                 (True, "control"), (True, "weapons")):
            for half in (1, 2):
                mappings = ((False, False),) if auxiliary else (
                    (False, False), (True, False), (False, True), (True, True))
                for ramrd, ramwrt in mappings:
                    with self.subTest(auxiliary=auxiliary, group=group, half=half,
                                      ramrd=ramrd, ramwrt=ramwrt):
                        doom = self.game_context()
                        m, cpu = doom.machine, doom.mpu
                        samples = doom.label("profile_samples")
                        values = [0xFFFF if i % 2 else 0x12FF for i in range(13)]
                        for i, value in enumerate(values):
                            self.put_word(doom, "profile_samples", value, i * 2)
                        self.put_word(doom, "vbl_count", 0xFFF8)
                        bank = doom.banked["banks"][group]
                        m.bank_memory(bank)[0xFFFE:0x10000] = doom.label("gb_irq").to_bytes(2, "little")
                        m[0xC073] = bank
                        switch = 0xC08B if half == 1 else 0xC083
                        m[switch]
                        m[switch]
                        m[0xC003 if ramrd else 0xC002] = 0
                        m[0xC005 if ramwrt else 0xC004] = 0
                        m[0xC009 if auxiliary else 0xC008] = 0
                        for i in range(13):
                            m.main[doom.label("profile_stage")] = i * 2
                            if auxiliary:
                                # The IRQ must consult main ZP, not this bank's byte.
                                m.bank_memory(bank)[doom.label("profile_stage")] = 0xFE
                            mapping = (m.bank, dict(m.sw), m.lc_bank2, m.lc_read, m.lc_write)
                            cpu.pc, cpu.sp = 0xD111, 0xFA
                            cpu.a, cpu.x, cpu.y = 0xA5, 0x73, 0xBC
                            cpu.p = cpu.UNUSED | cpu.CARRY | cpu.DECIMAL | cpu.OVERFLOW
                            expected_p = cpu.p
                            # A CPU IRQ alone is not a VBL. The card must
                            # identify the source before the clock advances.
                            m.mouse.vbl_pending = m.mouse.irq = True
                            m._interrupt()
                            for _ in range(200):
                                m.step()
                                if cpu.pc == 0xD111:
                                    break
                            else:
                                self.fail("profiling IRQ did not return")
                            self.assertEqual((cpu.a, cpu.x, cpu.y, cpu.sp), (0xA5, 0x73, 0xBC, 0xFA))
                            self.assertEqual(cpu.p & ~cpu.BREAK, expected_p)
                            self.assertEqual((m.bank, m.sw, m.lc_bank2, m.lc_read, m.lc_write), mapping)
                            values[i] = (values[i] + 1) & 0xFFFF
                            actual = bytes(m.lc[False][samples - 0xC000:samples - 0xC000 + 26])
                            self.assertEqual(struct.unpack("<13H", actual), tuple(values))
                            self.assertFalse(m.mouse.vbl_pending)
                            self.assertFalse(m.mouse.irq)
                            expected_clock = bytes(m.main[doom.label("vbl_count"):
                                                          doom.label("vbl_count") + 2])
                            for unrelated in (False, True):
                                # First emulate a stale physical IRQ after
                                # ACK, then a non-VBL mouse cause. Neither may
                                # alter the clock or the phase histogram.
                                m.mouse.move_irq = unrelated
                                m.mouse.button_pending = unrelated
                                m.mouse.irq = unrelated
                                m._interrupt()
                                for _ in range(200):
                                    m.step()
                                    if cpu.pc == 0xD111:
                                        break
                                else:
                                    self.fail("non-VBL IRQ did not return")
                                self.assertEqual((cpu.a, cpu.x, cpu.y, cpu.sp),
                                                 (0xA5, 0x73, 0xBC, 0xFA))
                                self.assertEqual(cpu.p & ~cpu.BREAK, expected_p)
                                self.assertEqual((m.bank, m.sw, m.lc_bank2, m.lc_read, m.lc_write),
                                                 mapping)
                                self.assertEqual(bytes(m.main[doom.label("vbl_count"):
                                                               doom.label("vbl_count") + 2]),
                                                 expected_clock)
                                self.assertEqual(bytes(m.lc[False][samples - 0xC000:
                                                                  samples - 0xC000 + 26]), actual)
                                self.assertFalse(m.mouse.irq)
                                self.assertFalse(m.mouse.move_irq)
                                self.assertFalse(m.mouse.button_pending)
                        self.assertEqual(m.main[doom.label("vbl_count"):doom.label("vbl_count") + 2],
                                         (5).to_bytes(2, "little"))

    def test_brk_still_crashes_through_both_irq_routes(self):
        for auxiliary, group in ((False, "weapons"), (True, "control"), (True, "weapons")):
            with self.subTest(auxiliary=auxiliary, group=group):
                doom = self.game_context()
                m, cpu = doom.machine, doom.mpu
                bank = doom.banked["banks"][group]
                m[0xC073] = bank
                m[0xC009 if auxiliary else 0xC008] = 0
                # Execute an actual BRK rather than injecting an IRQ with
                # the software-interrupt status bit manufactured by a test.
                m[0xBFFF] = 0
                cpu.pc, cpu.sp = 0xBFFF, 0xFA
                cpu.p = cpu.UNUSED | cpu.INTERRUPT
                for _ in range(1000):
                    m.step()
                    if not m.sw["altzp"] and cpu.pc == doom.label("kernel_crash_stop"):
                        break
                else:
                    self.fail("BRK did not reach kernel_crash_stop")
                self.assertEqual(doom.byte("kcrash"), 1)

    def test_publication_sequence_throttle_wrap_and_host_interval(self):
        doom = self.game_context()
        m = doom.machine
        m.main[doom.label("_debug_hz")] = 50
        self.put_word(doom, "vbl_count", 65500)
        self.put_word(doom, "kframes", 65530)
        self.put_word(doom, "ktics", 65520)
        self.put_word(doom, "profile_samples", 65500, 14)
        writes = self.call_publish(doom)
        self.assertEqual([len(data) for data in writes], [2, 44, 2])
        self.assertEqual([int.from_bytes(data[:2], "little") for data in writes], [1, 1, 2])
        first = self.snapshot(doom)
        values = self.layout.decode(first)
        self.assertEqual((values["sequence"], values["clock"], values["hz"]), (2, 65500, 50))
        self.assertEqual(values["walls"], 65500)
        self.assertEqual(self.call_publish(doom), [])
        self.assertEqual(self.snapshot(doom), first)
        self.put_word(doom, "vbl_count", 65559)
        self.assertEqual(self.call_publish(doom), [])
        self.assertEqual(self.snapshot(doom), first)

        self.put_word(doom, "vbl_count", 65560)
        self.put_word(doom, "kframes", 65537)
        self.put_word(doom, "ktics", 65548)
        self.put_word(doom, "profile_samples", 65560, 14)
        writes = self.call_publish(doom)
        self.assertEqual([int.from_bytes(data[:2], "little") for data in writes], [3, 3, 4])
        second = self.snapshot(doom)
        report = profile_hardware.interval(
            dict(values=self.layout.decode(first), utc="first", host_monotonic=10),
            dict(values=self.layout.decode(second), utc="second", host_monotonic=11.2), self.layout)
        self.assertTrue(report["valid"], report)
        self.assertEqual((report["clock"], report["frames"], report["tics"]), (60, 7, 28))
        self.assertEqual(report["phase_samples"]["walls"], 60)
        self.assertAlmostEqual(report["fps"], 7 / 1.2)
        # Sequence arithmetic must also survive its own independent rollover.
        self.put_word(doom, "profile_snapshot", 65534)
        self.put_word(doom, "vbl_count", 65620)
        writes = self.call_publish(doom)
        self.assertEqual([int.from_bytes(data[:2], "little") for data in writes], [65535, 65535, 0])
        self.assertEqual(self.layout.decode(self.snapshot(doom))["sequence"], 0)
        self.assertEqual(self.call_publish(doom), [], "sequence rollover must not bypass throttling")

    def test_postlink_build_identity_matches_actual_images(self):
        labels = run_doom.labels_from(BUILD / "doom.lbl")
        offset = labels["profile_snapshot"] + 6 - 0x0200
        digest = hashlib.sha256((DATA / "manifest.json").read_bytes())
        for name, expected_hash in self.metadata["images"].items():
            blob = (BUILD / name).read_bytes()
            self.assertEqual(hashlib.sha256(blob).hexdigest(), expected_hash)
            if name == "GAME.BIN":
                self.assertEqual(blob[offset:offset + 4].hex(), self.metadata["build_id"])
                blob = blob[:offset] + bytes(4) + blob[offset + 4:]
            digest.update(name.encode())
            digest.update(blob)
        self.assertEqual(digest.digest()[:4].hex(), self.metadata["build_id"])

    def test_five_real_frames_keep_sample_totals_readout_and_snapshot_coherent(self):
        doom = self.machine()
        m, cpu = doom.machine, doom.mpu

        def advance(name):
            self.assertTrue(doom.run_to(name, 200_000_000), f"did not reach {name}")
            self.assertEqual(doom.byte("kcrash"), 0)

        advance("frame_top")
        snapshots = []
        first_screen = None
        for frame in range(5):
            m.hold(ord("W"))
            m.mouse_delta(16, 0)
            advance("present_done")
            samples = sum(doom.word("profile_samples") if i == 0 else
                          doom.byte("profile_samples", offset=i * 2) |
                          doom.byte("profile_samples", offset=i * 2 + 1) << 8 for i in range(13))
            self.assertEqual(samples & 65535, doom.word("vbl_count"))
            values = self.layout.decode(self.snapshot(doom))
            self.assertEqual(values["sequence"] & 1, 0)
            self.assertEqual(sum(values[s["field"]] for s in self.layout.stages) & 65535,
                             values["clock"])
            snapshots.append(dict(values=values, utc=str(frame),
                                  host_monotonic=cpu.processorCycles / m.frame_cycles / 60))
            strip = bytes(m.bank_memory(0)[0x2000 + 320 * 88:0x2000 + 320 * 95])
            self.assertEqual(set(strip), {0, 4}, "FPS/TPS strip is missing")
            screen = bytes(m.bank_memory(0)[0x2000:0x2000 + 320 * 84])
            self.assertGreater(len(set(screen)), 8)
            if first_screen is None:
                first_screen = screen
            if frame < 4:
                advance("frame_top")
        self.assertNotEqual(first_screen, screen)
        reports = [profile_hardware.interval(a, b, self.layout)
                   for a, b in zip(snapshots, snapshots[1:])]
        valid = [report for report in reports if report["valid"]]
        self.assertTrue(valid, reports)
        self.assertTrue(all(report["valid"] or report["reason"] == "unchanged_snapshot"
                            for report in reports), reports)
        self.assertGreater(sum(report["frames"] for report in valid), 0)
        self.assertEqual(doom.word("kframes"), 4)  # increment follows present_done
        self.assertGreater(doom.word("ktics"), 4)
        m.shr_image().save(BUILD / "profile-runtime-final.png")


if __name__ == "__main__":
    unittest.main()
