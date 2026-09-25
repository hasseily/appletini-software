#!/usr/bin/env python3
"""Real 65C02 gateway execution against the platform's RamWorks mapper.

These tests check mapping and calling semantics, not TURBO/PSRAM timing.
No converted game data, game build, or Apple ROM file is required.
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import a2sim  # noqa: E402


class MappingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="doom-lc-map-")
        self.addCleanup(self.tmp.cleanup)
        rom = Path(self.tmp.name) / "rom.bin"
        rom.write_bytes(bytes([0xEA]) * 0x4000)
        self.m = a2sim.Machine(rom, mouse=False, ramworks_banks=4, io_cycles=0)

    def enable(self, half=2):
        switch = 0xC083 if half == 2 else 0xC08B
        self.m[switch]
        self.m[switch]

    def test_selected_bank_owns_zero_page_stack_and_both_lc_halves(self):
        m = self.m
        m[0xC009] = 0
        for bank in range(4):
            m[0xC073] = bank
            self.enable(2)
            for address in (0x42, 0x1EF, 0xD000, 0xE000, 0xFFFE):
                m[address] = 0x10 + bank
            self.enable(1)
            m[0xD000] = 0x20 + bank
        for bank in range(4):
            m[0xC073] = bank
            self.enable(2)
            for address in (0x42, 0x1EF, 0xD000, 0xE000, 0xFFFE):
                self.assertEqual(m[address], 0x10 + bank)
            self.enable(1)
            self.assertEqual(m[0xD000], 0x20 + bank)
            self.assertEqual(m[0xE000], 0x10 + bank)
            self.assertEqual(m.bank_memory(bank)[0xC000], 0x20 + bank)
            self.assertEqual(m.bank_memory(bank)[0xD000], 0x10 + bank)

    def test_main_lc_is_independent_of_ramworks_selection(self):
        m = self.m
        self.enable(2)
        m[0xD000] = 0x35
        m[0xE000] = 0x36
        self.enable(1)
        m[0xD000] = 0x37
        for bank in range(4):
            m[0xC073] = bank
            self.assertEqual(m[0xD000], 0x37)
            self.assertEqual(m[0xE000], 0x36)
            self.enable(2)
            self.assertEqual(m[0xD000], 0x35)
            self.enable(1)
        self.assertEqual(m.lc[False][0x1000], 0x35)
        self.assertEqual(m.lc_bank1[False][0], 0x37)

    def test_base_aux_legacy_views_remain_live(self):
        m = self.m
        m[0xC009] = 0
        self.enable(2)
        m.lc[True][0x2000] = 0x81
        self.assertEqual(m[0xE000], 0x81)
        self.enable(1)
        m[0xD000] = 0x82
        self.assertEqual(m.lc_bank1[True][0], 0x82)
        m[0xC073] = 2
        m[0xD000] = 0x83
        self.assertEqual(m.lc_bank1[True][0], 0x82)

    def test_bank_aliasing_and_lc_read_write_latches(self):
        m = self.m
        m[0xC009] = 0
        m[0xC073] = 1
        self.enable(2)
        m[0xD234] = 0x52
        m[0xC073] = 5               # four-bank machine: 5 aliases 1
        self.assertEqual(m[0xD234], 0x52)
        m[0xC080]                   # RAM reads, writes disabled
        m[0xD234] = 0x99
        self.assertEqual(m[0xD234], 0x52)
        m[0xC082]                   # ROM visible; RAM remains untouched
        self.assertEqual(m[0xD234], 0xEA)
        self.enable(2)
        self.assertEqual(m[0xD234], 0x52)


@unittest.skipUnless(shutil.which("ca65") and shutil.which("ld65"), "requires cc65 tools")
class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="doom-bank-call-")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.build = Path(cls.tmp.name)
        cls.rom = cls.build / "rom.bin"
        cls.rom.write_bytes(bytes([0xEA]) * 0x4000)
        sources = [ROOT / "src/kernel/gamebanks.s", ROOT / "tests/host/gamebanks_fixture.s"]
        for source in sources:
            subprocess.run(["ca65", "-I", str(ROOT / "src/kernel"), str(source),
                            "-o", str(cls.build / (source.stem + ".o"))], check=True)
        subprocess.run(["ld65", "-C", str(ROOT / "tests/host/gamebanks_fixture.cfg"),
                        "gamebanks.o", "gamebanks_fixture.o", "-Ln", "fixture.lbl"],
                       cwd=cls.build, check=True)
        cls.labels = {line.split()[2].lstrip("."): int(line.split()[1], 16)
                      for line in (cls.build / "fixture.lbl").read_text().splitlines()}
        cls.images = {name: (cls.build / name).read_bytes()
                      for name in ("main.bin", "a.bin", "b.bin", "lc.bin")}

    def run_fixture(self, inject_at=None):
        L = self.labels
        m = a2sim.Machine(self.rom, mouse=False, ramworks_banks=4, io_cycles=0)
        m.main[0x0200:0x2000] = self.images["main.bin"]
        m.lc[False][0x1000:] = self.images["lc.bin"]
        for bank, name in ((1, "a.bin"), (2, "b.bin")):
            data = m.bank_memory(bank)
            data[0xD000:] = self.images[name]
            data[0xFFFE:] = L["gb_irq"].to_bytes(2, "little")
        m.lc[False][0x3FFE:] = L["fixture_main_irq"].to_bytes(2, "little")
        m.bank_memory(3)[0x2000] = 0xA6
        m[0xC083]
        m[0xC083]
        cpu = m.mpu
        cpu.pc = L["start"]
        pending = delivered = False
        trace = []
        for step in range(15000):
            if step == inject_at:
                pending = True
            if pending and not cpu.p & cpu.INTERRUPT:
                cpu.irq()
                pending = False
                delivered = True
            if cpu.pc == L["finished"]:
                self.assertEqual(m.main[L["error"]], 0, (inject_at, "assembly checks"))
                self.assertEqual(m.main[L["shared"]], 7)
                self.assertEqual(m.main[L["visits"]], 3)
                self.assertEqual(cpu.sp, 0xFF)
                self.assertFalse(m.sw["altzp"])
                self.assertFalse(m.sw["ramrd"])
                self.assertFalse(m.sw["ramwrt"])
                self.assertEqual(m.main[L["gb_current"]], 0x80)
                self.assertEqual(m.main[0xE0:0xE2], b"\x00\xb0")
                self.assertEqual(m.main[0xAFF6:0xAFF8], b"\xbe\xef")
                self.assertEqual(m.main[0xAFFA:0xAFFC], b"\xca\xfe")
                for bank in (1, 2):
                    self.assertEqual(m.main[L["gb_saved_sp"] + bank], 0xFF)
                if inject_at is not None:
                    self.assertTrue(delivered)
                    self.assertEqual(m.main[L["irq_count"]], 1)
                return trace
            trace.append(cpu.pc)
            cpu.step()
        self.fail(f"fixture did not finish: injection {inject_at}, PC=${cpu.pc:04X}")

    def test_nested_bank_calls_and_main_kernel_bridge(self):
        self.run_fixture()

    def test_irq_at_each_instruction_boundary_of_banked_execution(self):
        trace = self.run_fixture()
        first = trace.index(self.labels["gb_call"]) - 1
        # Cover initial main->A entry, A->B->A recursion, the main-LC
        # kernel call that changes C073, and all reverse transitions.
        for injection in range(first, len(trace)):
            with self.subTest(instruction=injection):
                self.run_fixture(injection)


if __name__ == "__main__":
    unittest.main()
