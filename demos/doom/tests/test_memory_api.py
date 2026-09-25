#!/usr/bin/env python3
"""Execute the assembled LC memory helper against the opt-in SmartPort model."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import a2sim
import run_doom

EXTERNAL_BUILD = "DOOM_MEMORY_API_BUILD" in os.environ
BUILD = Path(os.environ.get("DOOM_MEMORY_API_BUILD", ROOT / "build/host/memory-api"))
if not BUILD.is_absolute():
    BUILD = ROOT / BUILD
DATA = ROOT / "build/data"
READY = (not EXTERNAL_BUILD or ((BUILD / "AMEM.BIN").is_file() and (BUILD / "doom.lbl").is_file())) \
    and (DATA / "manifest.json").is_file() and run_doom.DEFAULT_ROM.is_file()


@unittest.skipUnless(READY, "requires a linked AMEM candidate, converted data and Apple ROM")
class MemoryApiAssemblyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not EXTERNAL_BUILD:
            subprocess.run([sys.executable, str(ROOT / "tools/build_banked.py"),
                            "--build", str(BUILD), "--data", str(DATA),
                            "--python", sys.executable, "--profile"], check=True,
                           stdout=subprocess.DEVNULL)

    def machine(self, service=None):
        doom = run_doom.Doom(BUILD, DATA, speed=33, fast=True)
        doom.machine.smartport = service
        doom.install_fast()
        doom.machine.main[0x7F8] = 0xD3
        return doom

    def call(self, doom, name, *, a=0, x=0, y=0, lc1=False,
             irq_at_fifo=False, limit=3_000_000):
        m, cpu = doom.machine, doom.mpu
        m.lc_read = m.lc_write = True
        m.lc_bank2 = not lc1
        cpu.sp = 0xFF
        if irq_at_fifo:
            cpu.p &= ~cpu.INTERRUPT
        else:
            cpu.p |= cpu.INTERRUPT
        cpu.a, cpu.x, cpu.y = a, x, y
        cpu.stPushWord(0xBFEE)
        cpu.pc = doom.label(name)
        stop = cpu.processorCycles + limit
        injected = False
        while cpu.processorCycles < stop:
            if irq_at_fifo and not injected and m.smartport.selected:
                m.mouse.vbl_pending = m.mouse.irq = True
                injected = True
            m.step()
            if cpu.pc in (0xBFEF, doom.label("kernel_crash_stop")):
                if cpu.pc == 0xBFEF:
                    self.assertEqual(cpu.sp, 0xFF)
                    if irq_at_fifo:
                        self.assertTrue(injected, "no FIFO ownership to inject an IRQ into")
                        self.assertFalse(cpu.p & cpu.INTERRUPT)
                return cpu.pc == 0xBFEF
        self.fail(f"{name} did not finish: PC=${cpu.pc:04X}")

    def state(self, doom, name):
        return doom.machine[doom.label(name)]

    def probe(self, service):
        doom = self.machine(service)
        m = doom.machine
        protected_start = doom.label("__RZP_RUN__")
        pattern = bytes((i * 29 + 83) & 255 for i in range(256 - protected_start))
        m.main[protected_start:256] = pattern
        mapping = dict(m.sw)
        self.assertTrue(self.call(doom, "amem_init"))
        self.assertTrue(m.lc_bank2)
        self.assertEqual(m.main[0x7F8], 0xD3)
        self.assertEqual(m.main[protected_start:256], pattern)
        self.assertEqual(m.sw, mapping)
        self.assertFalse(service.selected if service else False)
        return doom

    def test_probe_requires_signature_private_transport_and_capabilities(self):
        for service, expected, requests in [
            (None, 0, 0),
            (a2sim.FakeSmartPortMemory(private_port=False), 0, 0),
            (a2sim.FakeSmartPortMemory(supported=False), 0, 1),
            (a2sim.FakeSmartPortMemory(available=False), 0, 1),
            (a2sim.FakeSmartPortMemory(), 1, 1),
        ]:
            with self.subTest(service=service, expected=expected):
                doom = self.probe(service)
                self.assertEqual(self.state(doom, "amem_available"), expected)
                self.assertEqual(len(service.requests) if service else 0, requests)
        service = a2sim.FakeSmartPortMemory()
        service.rom[1] = 0
        doom = self.probe(service)
        self.assertEqual(self.state(doom, "amem_available"), 0)
        self.assertEqual(service.requests, [])

    def test_malformed_capability_replies_leave_legacy_path_available(self):
        for offset, value in [(0, ord("X")), (4, 2), (6, 15), (7, 0),
                              (8, 3), (10, 1), (11, 3), (12, 1),
                              (13, 0xBF), (14, 124)]:
            with self.subTest(offset=offset):
                service = a2sim.FakeSmartPortMemory()
                service.caps[offset] = value
                doom = self.probe(service)
                self.assertEqual(self.state(doom, "amem_available"), 0)

    def test_phase_save_and_load_match_legacy_without_rom_workspace_damage(self):
        pattern = bytes((i * 37 + (i >> 4) + 91) & 255 for i in range(1024))
        for service in (None, a2sim.FakeSmartPortMemory()):
            with self.subTest(accelerated=service is not None):
                doom = self.probe(service)
                m = doom.machine
                m.main[0x8000:0x8400] = pattern
                m.bank_memory(10)[0x7FFF:0x8401] = bytes([0xA7]) * 1026
                self.assertTrue(self.call(doom, "phase_save", a=10, x=0x80, y=0x84, lc1=True))
                self.assertEqual(m.bank_memory(10)[0x8000:0x8400], pattern)
                self.assertEqual(m.bank_memory(10)[0x7FFF], 0xA7)
                self.assertEqual(m.bank_memory(10)[0x8400], 0xA7)
                m.main[0x8000:0x8400] = bytes([0xEA]) * 1024
                self.assertTrue(self.call(doom, "phase_load", a=10, x=0x80, y=0x84, lc1=True))
                self.assertEqual(m.main[0x8000:0x8400], pattern)
                self.assertEqual(m.main[0x7F8], 0xD3)
                self.assertFalse(m.sw["ramrd"] or m.sw["ramwrt"] or m.sw["altzp"])
                if service:
                    self.assertEqual([item[0] for item in service.completed], [1, 1])
                    self.assertFalse(service.selected)

    def test_game_save_uses_rounded_arena_extent(self):
        service = a2sim.FakeSmartPortMemory()
        doom = self.probe(service)
        m = doom.machine
        pointer = doom.label("_arena_ptr")
        m.main[pointer:pointer + 2] = (0x8189).to_bytes(2, "little")
        bank = doom.banked["game_home"]
        m.main[0x8000:0x8200] = bytes([0x73]) * 512
        m.bank_memory(bank)[0x8200] = 0xA6
        self.assertTrue(self.call(doom, "phase_save", a=bank, x=0x80, y=0x84, lc1=True))
        self.assertEqual(service.completed[-1][-1], 512)
        self.assertEqual(m.bank_memory(bank)[0x8200], 0xA6)
        self.assertEqual(self.state(doom, "phase_game_end"), 0x82)

    def test_mouse_irq_preserves_fifo_ownership_overlay_and_mapping(self):
        service = a2sim.FakeSmartPortMemory()
        doom = self.probe(service)
        m = doom.machine
        m.next_vbl = 1 << 60
        pattern = bytes((i * 17 + (i >> 3) + 39) & 255 for i in range(1024))
        m.main[0x8000:0x8400] = pattern
        before_irq, before_vbl = m.irqs, doom.word("vbl_count")
        self.assertTrue(self.call(doom, "phase_save", a=10, x=0x80, y=0x84,
                                  lc1=True, irq_at_fifo=True))
        self.assertEqual(m.bank_memory(10)[0x8000:0x8400], pattern)
        self.assertEqual(m.irqs, before_irq + 1)
        self.assertEqual(doom.word("vbl_count"), (before_vbl + 1) & 65535)
        self.assertFalse(m.lc_bank2 or m.sw["ramrd"] or m.sw["ramwrt"] or m.sw["altzp"])
        self.assertFalse(service.selected)
        self.assertEqual(m.main[0x7F8], 0xD3)
        self.assertEqual(service.completed, [(1, (0, 0, 0x8000), (1, 10, 0x8000), 1024)])

    def test_unavailable_before_execution_disables_api_and_falls_back_once(self):
        service = a2sim.FakeSmartPortMemory(fail_before=0x60)
        doom = self.probe(service)
        m = doom.machine
        pattern = bytes(range(256))
        m.main[0x8000:0x8100] = pattern
        self.assertTrue(self.call(doom, "phase_save", a=10, x=0x80, y=0x81, lc1=True))
        self.assertEqual(m.bank_memory(10)[0x8000:0x8100], pattern)
        self.assertEqual(self.state(doom, "amem_available"), 0)
        self.assertEqual(service.completed, [])
        m.main[0x8000:0x8100] = bytes(256)
        count = len(service.requests)
        self.assertTrue(self.call(doom, "phase_load", a=10, x=0x80, y=0x81, lc1=True))
        self.assertEqual(len(service.requests), count)
        self.assertEqual(m.main[0x8000:0x8100], pattern)

    def test_partial_execution_error_crashes_without_cpu_retry(self):
        service = a2sim.FakeSmartPortMemory(fail_after=0, partial_bytes=37)
        doom = self.probe(service)
        m = doom.machine
        m.main[0x8000:0x8100] = bytes([0x31]) * 256
        m.bank_memory(10)[0x8000:0x8100] = bytes([0xA5]) * 256
        self.assertFalse(self.call(doom, "phase_save", a=10, x=0x80, y=0x81, lc1=True))
        self.assertEqual(self.state(doom, "amem_status"), 0x67)
        self.assertEqual(m.bank_memory(10)[0x8000:0x8025], bytes([0x31]) * 37)
        self.assertEqual(m.bank_memory(10)[0x8025:0x8100], bytes([0xA5]) * 219)
        self.assertEqual(len(service.partial_writes), 1)
        self.assertEqual(len(service.requests), 2)

    def test_fill_clears_only_view_buffer(self):
        for service in (None, a2sim.FakeSmartPortMemory(),
                        a2sim.FakeSmartPortMemory(fail_before=0x60)):
            with self.subTest(service=service):
                doom = self.probe(service)
                m = doom.machine
                start, size = doom.label("VIEWBUF"), doom.label("VIEWBUF_SIZE")
                ktmp = doom.label("ktmp")
                m.main[ktmp:ktmp + 2] = start.to_bytes(2, "little")
                m.main[start - 1:start + size + 1] = bytes([0x62]) * (size + 2)
                self.assertTrue(self.call(doom, "amem_clear", a=size & 255,
                                          x=size >> 8, y=0x53, lc1=True))
                self.assertEqual(m.main[start:start + size], bytes(size))
                self.assertEqual(m.main[start - 1], 0x62)
                self.assertEqual(m.main[start + size], 0x62)
                self.assertFalse(m.lc_bank2)
                self.assertFalse(m.sw["ramrd"] or m.sw["ramwrt"] or m.sw["altzp"])
                if service and not service.fail_before:
                    self.assertEqual(service.completed[-1][0], 2)
                elif service:
                    self.assertEqual(self.state(doom, "amem_available"), 0)
                    self.assertEqual(service.completed, [])


if __name__ == "__main__":
    unittest.main()
