#!/usr/bin/env python3
"""Wall queue pixels, scratch bounds and IRQ safety on the real Apple mapper.

Uses an existing integrated build (DOOM_WALL_BUILD) without rebuilding it.
The expected pixels are computed independently of the two-pass implementation.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_doom  # noqa: E402

BUILD = Path(os.environ.get("DOOM_WALL_BUILD", ROOT / "build/profile"))
DATA = ROOT / "build/data"
READY = (BUILD / "doom.lbl").is_file() and (DATA / "manifest.json").is_file()
READY = READY and run_doom.DEFAULT_ROM.is_file()


@unittest.skipUnless(READY, "requires integrated renderer build, data and Apple ROM")
class WallQueueTest(unittest.TestCase):
    def machine(self):
        doom = run_doom.Doom(BUILD, data=DATA, speed=33, fast=True)
        doom.boot()
        m = doom.machine
        m[0xC008] = m[0xC002] = m[0xC004] = 0
        m[0xC08B]
        m[0xC08B]
        m[doom.label("q_count")] = 0
        m[doom.label("cur_bank")] = 0xFF
        return doom

    @staticmethod
    def palette(bank, page, texel):
        return (bank * 7 + page * 31 + texel * 29) & 255

    def run_queue(self, entries, interrupt=False, destinations=None):
        doom = self.machine()
        m, cpu = doom.machine, doom.mpu
        kbuf = doom.label("kbuf")
        self.assertGreaterEqual(kbuf, 0xE000)
        self.assertLess(kbuf + 256, 0xFFFA)
        for bank in (60, 61):
            storage = m.bank_memory(bank)
            for page in (2, 7, 17):
                storage[page * 256:(page + 1) * 256] = bytes(
                    self.palette(bank, page, i) for i in range(256))
            storage[0x4000:0x4300] = bytes((i * 13 + (i >> 3) + bank) & 255
                                          for i in range(0x300))
        m.main[0x7000:0x9400] = bytes([0xA6]) * 0x2400
        expected = bytearray(m.main[0x7000:0x9400])
        m.lc[False][kbuf - 0xC000:kbuf - 0xC000 + 256] = bytes([0xD3]) * 256
        m[kbuf - 1], m[kbuf + 256] = 0x5A, 0xA5
        for i, (count, fraction, step, mask, bank, page, fill) in enumerate(entries):
            dest, source = 0x7001 + i * 0x120, 0x40E7 if i & 1 else 0x4000
            if destinations is not None:
                dest = destinations[i]
            values = dict(q_bank=bank, q_dlo=dest & 255, q_dhi=dest >> 8,
                          q_cnt=count, q_slo=source & 255, q_shi=0 if fill else source >> 8,
                          q_flo=fraction & 255, q_fhi=fraction >> 8,
                          q_stl=step & 255, q_sth=step >> 8, q_hm=mask, q_cm=page)
            for name, value in values.items():
                m[doom.label(name) + i] = value
            lo, row = fraction & 255, (fraction >> 8) & mask
            carry = 0
            for x in range(count or 256):
                texel = fraction & 255 if fill else m.bank_memory(bank)[source + row]
                expected[dest - 0x7000 + x] = self.palette(bank, page, texel)
                total = lo + (step & 255) + carry
                lo = total & 255
                row = (row + (step >> 8) + (total >> 8)) & mask
                # Legacy count=0 means 256 pixels. Its CPX #0 supplies carry
                # on intervening iterations; preserve this unusual behavior.
                carry = int(count == 0)
        m[doom.label("q_count")] = len(entries)
        if "profile_stage" in doom.labels:
            m.main[doom.label("profile_stage")] = 14  # walls
        cpu.pc, cpu.sp = doom.label("q_flush"), 0xFF
        cpu.p = cpu.UNUSED | (0 if interrupt else cpu.INTERRUPT)
        sentinel = 0xBFFF
        cpu.stPushWord(sentinel - 1)
        machine_class, injected = type(m), False
        original = machine_class.__setitem__
        original_read = machine_class.__getitem__
        scratch_writes = []

        def observe(machine, address, value):
            nonlocal injected
            if machine is m and kbuf <= address < kbuf + 256:
                scratch_writes.append(address)
                if interrupt is True and not injected:
                    machine.mouse.vbl_pending = machine.mouse.irq = True
                    injected = True
            original(machine, address, value)

        def observe_read(machine, address):
            nonlocal injected
            value = original_read(machine, address)
            if (machine is m and interrupt == "shade" and not injected
                    and kbuf <= address < kbuf + 256):
                machine.mouse.vbl_pending = machine.mouse.irq = True
                injected = True
            return value

        with patch.object(machine_class, "__setitem__", observe), \
                patch.object(machine_class, "__getitem__", observe_read):
            limit = cpu.processorCycles + 2_000_000
            while cpu.processorCycles < limit:
                m.step()
                if cpu.pc == sentinel:
                    break
            else:
                self.fail(f"q_flush did not return: ${cpu.pc:04X}")
        self.assertEqual(m.main[0x7000:0x9400], expected)
        self.assertEqual((m[kbuf - 1], m[kbuf + 256]), (0x5A, 0xA5))
        self.assertEqual(len(scratch_writes), sum((e[0] or 256) for e in entries if not e[6]))
        self.assertEqual(m[doom.label("q_count")], 0)
        self.assertEqual(cpu.sp, 0xFF)
        self.assertFalse(m.sw["ramrd"] or m.sw["ramwrt"] or m.sw["altzp"])
        self.assertFalse(m.lc_bank2)
        if interrupt:
            self.assertTrue(injected)
            self.assertGreater(m.irqs, 0)
            self.assertEqual(doom.word("vbl_count"), 1)

    def test_texture_steps_masks_pages_and_full_queue(self):
        counts = (1, 2, 7, 31, 63, 84, 127, 255)
        entries = [(counts[i % 8], (i * 3917) & 65535,
                    (0, 1, 255, 256, 257, 0x3FF, 0x80FF, 0xFFFF)[i % 8],
                    (0, 31, 63, 127, 255)[i % 5], 60 + i % 2,
                    (2, 7, 17)[i % 3], i % 6 == 0) for i in range(32)]
        self.run_queue(entries)

    def test_256_pixel_legacy_count_and_irq_during_staging(self):
        self.run_queue([(0, 0xF1FF, 0x03FF, 127, 60, 7, False),
                        (84, 0x12FE, 0x0081, 255, 61, 17, False),
                        (0, 0x002F, 0, 0, 60, 2, True)], interrupt=True)

    def test_empty_queue_preserves_ramrd_and_scratch(self):
        doom = self.machine()
        m, cpu = doom.machine, doom.mpu
        m[0xC003] = 0
        before = bytes(m.lc[False])
        cpu.pc, cpu.sp = doom.label("q_flush"), 0xFF
        cpu.p |= cpu.INTERRUPT
        cpu.stPushWord(0xBFFE)
        for _ in range(5):
            m.step()
            if cpu.pc == 0xBFFF:
                break
        self.assertEqual(cpu.pc, 0xBFFF)
        self.assertTrue(m.sw["ramrd"])
        self.assertEqual(bytes(m.lc[False]), before)

    def test_overlapping_pieces_bank_changes_and_irq_during_shading(self):
        self.run_queue([(84, 0xFF80, 0x0100, 255, 60, 2, False),
                        (31, 0x00FF, 0, 0, 61, 7, True),
                        (63, 0x00FF, 0x00FF, 63, 60, 17, False)],
                       interrupt="shade", destinations=(0x71F0, 0x7201, 0x71FF))


if __name__ == "__main__":
    unittest.main()
