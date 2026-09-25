#!/usr/bin/env python3
"""Plane spans against independent flat-coordinate math on the Apple mapper.

Uses an existing integrated build (DOOM_PLANE_BUILD), without rebuilding it.
Expected pixels and final coordinates do not depend on the loop implementation.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_doom  # noqa: E402

BUILD = Path(os.environ.get("DOOM_PLANE_BUILD", ROOT / "build/profile"))
DATA = ROOT / "build/data"
READY = ((BUILD / "doom.lbl").is_file() and (DATA / "manifest.json").is_file()
         and run_doom.DEFAULT_ROM.is_file())


@unittest.skipUnless(READY, "requires integrated renderer build, data and Apple ROM")
class PlaneSpanTest(unittest.TestCase):
    def machine(self):
        doom = run_doom.Doom(BUILD, data=DATA, speed=33, fast=True)
        doom.boot()
        m = doom.machine
        m[0xC008] = m[0xC002] = m[0xC004] = 0
        m[0xC08B]
        m[0xC08B]
        m[doom.label("cur_bank")] = 0xFF
        for bank in (60, 61):
            storage = m.bank_memory(bank)
            for page in (2, 7, 17):
                storage[page * 256:(page + 1) * 256] = bytes(
                    self.palette(bank, page, texel) for texel in range(256))
            storage[0x4000:0x5000] = bytes(
                (i * 13 + (i >> 4) * 29 + bank) & 255 for i in range(0x1000))
        return doom

    @staticmethod
    def palette(bank, page, texel):
        return (texel * 37 + page * 19 + bank * 3) & 255

    @staticmethod
    def put_word(doom, name, value):
        address = doom.label(name)
        doom.machine[address] = value & 255
        doom.machine[address + 1] = (value >> 8) & 255

    def call(self, doom, label, a=0, x=0, y=0, carry=False, irq=False):
        m, cpu = doom.machine, doom.mpu
        cpu.pc, cpu.sp = doom.label(label), 0xFF
        cpu.a, cpu.x, cpu.y = a, x, y
        cpu.p = cpu.UNUSED | (cpu.CARRY if carry else 0) | (0 if irq else cpu.INTERRUPT)
        sentinel = 0xBFFF
        cpu.stPushWord(sentinel - 1)
        limit = cpu.processorCycles + 2_000_000
        while cpu.processorCycles < limit:
            m.step()
            if cpu.pc == sentinel:
                break
        else:
            self.fail(f"{label} did not return: ${cpu.pc:04X}")
        self.assertEqual(cpu.sp, 0xFF)
        self.assertFalse(m.sw["ramrd"] or m.sw["ramwrt"] or m.sw["altzp"])
        self.assertFalse(m.lc_bank2)

    def span(self, doom, count, xf, yf, xs, ys, bank=60, page=7,
             flat=0x4000, dest=0x6203, carry=False, interrupt=None):
        m, cpu = doom.machine, doom.mpu
        n = count or 256
        kbuf = doom.label("kbuf")
        self.assertGreaterEqual(kbuf, 0xE000)
        self.assertLess(kbuf + 256, 0xFFFA)
        row = 83
        for name, value in (("rc_xs0", xs & 255), ("rc_xs1", xs >> 8),
                            ("rc_ys0", ys & 255), ("rc_ys1", ys >> 8)):
            m[doom.label(name) + row] = value
        self.call(doom, "span_setflat", flat & 255, flat >> 8)
        self.call(doom, "span_setrow", page, y=row)
        self.put_word(doom, "sp_xf", xf)
        self.put_word(doom, "sp_yf", yf)
        self.put_word(doom, "sp_dp", dest)
        m[doom.label("sp_n")] = count
        if "profile_stage" in doom.labels:
            m.main[doom.label("profile_stage")] = 16  # planes
        m.main[0x6000:0xC000] = bytes([0xA6]) * 0x6000
        expected = bytearray(m.main[0x6000:0xC000])
        texels = []
        storage = m.bank_memory(bank)
        for pixel in range(n):
            x = ((xf + pixel * xs) & 65535) >> 11
            y = ((yf + pixel * ys) & 65535) >> 11
            texel = storage[flat + y * 32 + x]
            texels.append(texel)
            expected[dest - 0x6000 + pixel * 84] = self.palette(bank, page, texel)
        m.lc[False][kbuf - 0xC000:kbuf - 0xC000 + 256] = bytes([0xD3]) * 256
        m[kbuf - 1], m[kbuf + 256] = 0x5A, 0xA5
        storage_before = bytes(storage[0x0200:0x5000])
        writes, injected = [], False
        before_irqs = m.irqs
        before_vbl = doom.word("vbl_count")
        before_bank = m[doom.label("cur_bank")]
        bank_writes = []
        machine_class = type(m)
        original_write = machine_class.__setitem__
        original_read = machine_class.__getitem__

        def observe_write(machine, address, value):
            nonlocal injected
            if machine is m:
                if address == 0xC073:
                    bank_writes.append(value)
                if kbuf <= address < kbuf + 256:
                    writes.append(address)
                    if interrupt == "gather" and not injected:
                        machine.mouse.vbl_pending = machine.mouse.irq = True
                        injected = True
            original_write(machine, address, value)

        def observe_read(machine, address):
            nonlocal injected
            value = original_read(machine, address)
            if (machine is m and interrupt == "shade" and not injected
                    and kbuf <= address < kbuf + 256):
                machine.mouse.vbl_pending = machine.mouse.irq = True
                injected = True
            return value

        with patch.object(machine_class, "__setitem__", observe_write), \
                patch.object(machine_class, "__getitem__", observe_read):
            self.call(doom, "span_draw", bank, carry=carry, irq=bool(interrupt))
        self.assertEqual(m.main[0x6000:0xC000], expected,
                         "span pixels or untouched destination bytes differ")
        self.assertEqual(bytes(storage[0x0200:0x5000]), storage_before,
                         "span wrote into the selected far bank")
        self.assertEqual(doom.word("sp_xf"), (xf + n * xs) & 65535)
        self.assertEqual(doom.word("sp_yf"), (yf + n * ys) & 65535)
        self.assertEqual(doom.word("sp_dp"), (dest + ((n * 84) & 0xFF00)) & 65535)
        self.assertEqual(cpu.y, (n * 84) & 255)
        self.assertEqual(m[doom.label("sp_n")], 0)
        self.assertEqual(m[doom.label("cur_bank")], bank)
        self.assertEqual(m.bank, bank)
        self.assertEqual(bank_writes, [] if bank == before_bank else [bank])
        self.assertEqual((m[kbuf - 1], m[kbuf + 256]), (0x5A, 0xA5))
        self.assertEqual(len(writes), n, "staging wrote the wrong number of texels")
        self.assertEqual(set(writes), set(range(kbuf, kbuf + n)))
        self.assertEqual(bytes(m[kbuf + i] for i in range(n)), bytes(texels))
        self.assertEqual(bytes(m[kbuf + i] for i in range(n, 256)), bytes([0xD3]) * (256 - n))
        if interrupt:
            self.assertTrue(injected, f"IRQ was not injected during {interrupt}")
            self.assertEqual(m.irqs, before_irqs + 1)
            self.assertEqual(doom.word("vbl_count"), (before_vbl + 1) & 65535)

    def test_lengths_fraction_wraps_quarters_and_bank_changes(self):
        cases = (
            (1,   0x0000, 0x0000, 0x0000, 0x0000, 60, 2,  0x4000, 0x6203),
            (2,   0x07FF, 0x4000, 0x0001, 0xFFFF, 60, 7,  0x45B7, 0x63FE),
            (31,  0xFFFF, 0x8000, 0x07FF, 0x0800, 61, 17, 0x4800, 0x64FF),
            (84,  0x8001, 0xC000, 0x0800, 0x0001, 61, 2,  0x4000, 0x6501),
            (160, 0xFFF0, 0xFFFF, 0xFFFF, 0x8001, 60, 7,  0x45B7, 0x6203),
            (255, 0x7F01, 0x07FF, 0x8001, 0x1234, 61, 17, 0x4800, 0x63FE),
            (0,   0xFEFF, 0xFFEE, 0x2345, 0xFCFF, 60, 2,  0x4000, 0x64FF),
        )
        for carry in (False, True):
            doom = self.machine()
            for case in cases:
                with self.subTest(count=case[0], bank=case[5], entry_carry=carry):
                    self.span(doom, *case, carry=carry)

    def test_irq_during_gather_and_shading_preserves_pixels_and_mapping(self):
        for where in ("gather", "shade"):
            with self.subTest(where=where):
                self.span(self.machine(), 160, 0xFFFF, 0x7FF0, 0xFFFE, 0x7FFF,
                          bank=61, page=17, flat=0x45B7, dest=0x64FF,
                          carry=True, interrupt=where)


if __name__ == "__main__":
    unittest.main()
