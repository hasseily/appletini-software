#!/usr/bin/env python3
"""Execute the PAL/NTSC tic clock on the real banked Apple memory mapper.

Builds a private PAL fixture in build/host/frame-clock. DOOM_CLOCK_BUILD
instead selects an existing integrated build without rebuilding it; its
metadata supplies the video standard unless DOOM_CLOCK_HZ overrides it.
Injected VBL counts test game-time accounting; instruction-cycle limits
are not hardware speed estimates.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_doom  # noqa: E402

EXTERNAL_BUILD = "DOOM_CLOCK_BUILD" in os.environ
BUILD = Path(os.environ.get("DOOM_CLOCK_BUILD", ROOT / "build/host/frame-clock"))
if not BUILD.is_absolute():
    BUILD = ROOT / BUILD
VIDEO_HZ = int(os.environ["DOOM_CLOCK_HZ"]) if "DOOM_CLOCK_HZ" in os.environ else None
DATA = ROOT / "build/data"
READY = ((not EXTERNAL_BUILD or (BUILD / "doom.lbl").is_file())
         and (DATA / "manifest.json").is_file()
         and run_doom.DEFAULT_ROM.is_file())
MAX_TICS = 4


@unittest.skipUnless(READY, "requires integrated clock build, data and Apple ROM")
class FrameClockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not EXTERNAL_BUILD:
            subprocess.run([sys.executable, str(ROOT / "tools/build_banked.py"),
                            "--build", str(BUILD), "--data", str(DATA),
                            "--python", sys.executable, "--profile",
                            "--video-hz", str(VIDEO_HZ or 50)], check=True,
                           stdout=subprocess.DEVNULL)
        metadata = json.loads((BUILD / "banked.json").read_text())
        cls.video_hz = VIDEO_HZ or metadata.get("default_video_hz", 50)
        if cls.video_hz not in (50, 60):
            raise ValueError(f"unsupported test video standard: {cls.video_hz}")

    def machine(self):
        doom = run_doom.Doom(BUILD, data=DATA, speed=33, fast=True)
        doom.boot()
        doom.machine.next_vbl = 1 << 60  # Tests supply each clock event explicitly.
        self.assertIn("clock_init", doom.labels, "build predates the 16-bit PAL clock")
        self.assertIn("clk_divisor", doom.labels)
        return doom

    @staticmethod
    def put_word(doom, name, value):
        address = doom.label(name)
        doom.machine[address] = value & 255
        doom.machine[address + 1] = (value >> 8) & 255

    def call(self, doom, name, irq_at=None, interrupts=False, limit=600_000):
        m, cpu = doom.machine, doom.mpu
        cpu.pc, cpu.sp = doom.label(name), 0xFF
        cpu.a, cpu.x, cpu.y = 0xA5, 0x37, 0xC2
        cpu.p = cpu.UNUSED | cpu.CARRY | (0 if interrupts else cpu.INTERRUPT)
        sentinel = 0xBFFF
        cpu.stPushWord(sentinel - 1)
        start, steps, injected = cpu.processorCycles, 0, False
        while cpu.processorCycles - start < limit:
            if steps == irq_at:
                m.mouse.vbl_pending = m.mouse.irq = True
                injected = True
            m.step()
            steps += 1
            if cpu.pc == sentinel and not m.sw["altzp"]:
                break
        else:
            self.fail(f"{name} did not return within {limit} model cycles: ${cpu.pc:04X}")
        self.assertEqual(cpu.sp, 0xFF)
        self.assertFalse(m.sw["altzp"] or m.sw["ramrd"] or m.sw["ramwrt"])
        self.assertEqual(bool(cpu.p & cpu.INTERRUPT), not interrupts)
        if irq_at is not None:
            self.assertTrue(injected, "injection point was beyond the call")
        return cpu.processorCycles - start

    def setup_clock(self, doom, hz, previous=0, accumulator=0, dropped=0):
        m = doom.machine
        m[doom.label("clk_divisor")] = 10 if hz == 50 else 12
        m[doom.label("clk_acc")] = accumulator
        self.put_word(doom, "clk_last", previous)
        self.put_word(doom, "vbl_count", previous)
        self.put_word(doom, "kdropped", dropped)

    def advance(self, doom, elapsed, *, limit=600_000):
        divisor = doom.byte("clk_divisor")
        accumulator = doom.byte("clk_acc")
        previous = doom.word("clk_last")
        dropped = doom.word("kdropped")
        due, residue = divmod(accumulator + elapsed * 7, divisor)
        current = (previous + elapsed) & 65535
        self.put_word(doom, "vbl_count", current)
        cycles = self.call(doom, "clock_tics", limit=limit)
        self.assertEqual(doom.mpu.a, min(due, MAX_TICS))
        self.assertEqual(doom.byte("tics_due"), min(due, MAX_TICS))
        self.assertEqual(bool(doom.mpu.p & doom.mpu.ZERO), due == 0)
        self.assertEqual(doom.byte("clk_acc"), residue)
        self.assertEqual(doom.word("clk_last"), current)
        self.assertEqual(doom.word("kdropped"),
                         (dropped + max(0, due - MAX_TICS)) & 65535)
        return min(due, MAX_TICS), cycles

    def test_initializer_uses_build_standard_and_atomic_wide_baseline(self):
        doom = self.machine()
        self.put_word(doom, "vbl_count", 0x91FF)
        self.put_word(doom, "clk_last", 0x3333)
        doom.machine[doom.label("clk_divisor")] = 0xA5
        doom.machine[doom.label("clk_acc")] = 9
        self.call(doom, "clock_init")
        self.assertEqual(doom.byte("clk_divisor"), 10 if self.video_hz == 50 else 12)
        self.assertEqual(doom.byte("clk_acc"), 0)
        self.assertEqual(doom.word("clk_last"), 0x91FF)
        self.advance(doom, 0)

    def test_initializer_irq_cannot_mix_low_and_high_clock_bytes(self):
        doom = self.machine()
        m = doom.machine
        for boundary in range(11):
            with self.subTest(boundary=boundary):
                self.put_word(doom, "vbl_count", 0x12FF)
                self.put_word(doom, "clk_last", 0xAABB)
                m.mouse.vbl_pending = m.mouse.irq = False
                before_irqs = m.irqs
                self.call(doom, "clock_init", irq_at=boundary, interrupts=True)
                self.assertIn(doom.word("clk_last"), (0x12FF, 0x1300))
                self.assertEqual(doom.word("vbl_count"), 0x1300)
                self.assertEqual(m.irqs, before_irqs + 1)
                self.assertEqual(doom.byte("clk_acc"), 0)

    def test_exact_35_tics_each_second_at_both_video_rates(self):
        doom = self.machine()
        for hz in (50, 60):
            with self.subTest(hz=hz):
                self.setup_clock(doom, hz, previous=0xFF80)
                for second in range(4):
                    tics = sum(self.advance(doom, 1)[0] for _ in range(hz))
                    self.assertEqual(tics, 35, f"second {second}")
                    self.assertEqual(doom.byte("clk_acc"), 0)
                self.assertEqual(doom.word("kdropped"), 0)

    def test_sustained_slow_frames_drop_excess_work_without_backlog(self):
        doom = self.machine()
        for hz, gaps in ((50, (15, 17, 18)), (60, (20, 19, 21))):
            with self.subTest(hz=hz):
                self.setup_clock(doom, hz, previous=0x12F8)
                tics = 0
                for _ in range(4):
                    for gap in gaps:
                        due, _ = self.advance(doom, gap)
                        self.assertEqual(due, 4)
                        tics += due
                        # No new VBL means no more work, even after a slow
                        # frame: excess whole tics were dropped, not deferred.
                        self.assertEqual(self.advance(doom, 0)[0], 0)
                self.assertEqual(tics, 48)
                self.assertEqual(doom.word("kdropped"), 92)

    def test_short_intervals_after_stall_resume_without_deferred_tics(self):
        doom = self.machine()
        for hz in (50, 60):
            with self.subTest(hz=hz):
                self.setup_clock(doom, hz, previous=0xFFFA)
                # Two seconds plus one VBL owe 70 whole tics and leave
                # seven fractional units at either video rate.
                self.assertEqual(self.advance(doom, hz * 2 + 1)[0], 4)
                self.assertEqual(doom.word("kdropped"), 66)
                self.assertEqual(doom.byte("clk_acc"), 7)
                for _ in range(3):
                    self.assertEqual(self.advance(doom, 0)[0], 0)
                # Preserve the fractional remainder, but never replay the
                # 66 discarded tics when normal short intervals resume.
                tics = self.advance(doom, 1)[0]
                self.assertEqual(tics, 1)
                tics += sum(self.advance(doom, 1)[0] for _ in range(hz - 1))
                self.assertEqual(tics, 35)
                self.assertEqual(doom.word("kdropped"), 66)
                self.assertEqual(doom.byte("clk_acc"), 7)

    def test_wide_elapsed_wrap_residue_and_exact_dropped_accounting(self):
        doom = self.machine()
        for hz in (50, 60):
            divisor = 10 if hz == 50 else 12
            for previous in (0, 0x00FF, 0x12F0, 0xFFFA):
                for elapsed in (0, 1, 16, 23, 24, 27, 28, 255, 256, 257,
                                4096, 65535):
                    for accumulator in (0, divisor - 1):
                        with self.subTest(hz=hz, previous=previous,
                                          elapsed=elapsed, accumulator=accumulator):
                            self.setup_clock(doom, hz, previous, accumulator, 65530)
                            self.advance(doom, elapsed)
                            # A second call must not replay elapsed time or drops.
                            self.advance(doom, 0)

    def test_long_pause_work_is_bounded_by_grouped_accounting(self):
        doom = self.machine()
        for hz in (50, 60):
            with self.subTest(hz=hz):
                self.setup_clock(doom, hz, previous=0xBEEF)
                _, cycles = self.advance(doom, 65535, limit=500_000)
                self.assertLess(cycles, 500_000)

    def test_irq_at_snapshot_instruction_boundaries_never_tears_clock(self):
        doom = self.machine()
        m = doom.machine
        # A carry between $12FF and $1300 makes a torn byte pair observable.
        for hz in (50, 60):
            divisor = 10 if hz == 50 else 12
            for boundary in range(24):
                with self.subTest(hz=hz, boundary=boundary):
                    self.setup_clock(doom, hz, previous=0x12FE)
                    self.put_word(doom, "vbl_count", 0x12FF)
                    m.mouse.vbl_pending = m.mouse.irq = False
                    before_irqs = m.irqs
                    self.call(doom, "clock_tics", irq_at=boundary, interrupts=True)
                    snapshot = doom.word("clk_last")
                    self.assertIn(snapshot, (0x12FF, 0x1300))
                    observed_delta = snapshot - 0x12FE
                    expected_due, expected_acc = divmod(observed_delta * 7, divisor)
                    first_due = doom.mpu.a
                    self.assertEqual((first_due, doom.byte("clk_acc")),
                                     (expected_due, expected_acc))
                    self.assertEqual(doom.word("kdropped"), 0)
                    self.assertEqual(m.irqs, before_irqs + 1)
                    self.assertEqual(doom.word("vbl_count"), 0x1300)
                    # Consume a post-snapshot IRQ exactly once on the next call.
                    self.call(doom, "clock_tics", interrupts=True)
                    total_due, total_acc = divmod(14, divisor)
                    self.assertEqual(first_due + doom.mpu.a, total_due)
                    self.assertEqual(doom.byte("clk_acc"), total_acc)
                    self.assertEqual(doom.word("clk_last"), 0x1300)

    def test_idle_wait_and_model_hook_notice_equal_low_bytes(self):
        doom = self.machine()
        m, cpu = doom.machine, doom.mpu
        self.put_word(doom, "clk_last", 0x1200)
        self.put_word(doom, "vbl_count", 0x1300)
        cpu.pc, cpu.p = doom.label("idle_wait"), cpu.UNUSED | cpu.INTERRUPT
        idle_cycles = m.idle_cycles
        for _ in range(20):
            m.step()
            if cpu.pc == doom.label("frame_top"):
                break
        else:
            self.fail("idle_wait ignored a change to the VBL high byte")
        self.assertEqual(m.idle_cycles, idle_cycles, "model skipped an already-pending clock change")

    def test_debug_bridge_changes_rate_only_on_video_key_edges(self):
        doom = self.machine()
        m = doom.machine
        self.put_word(doom, "vbl_count", 100)
        self.call(doom, "clock_init")
        # Reproduce the GAME phase, including real gates and far-write backend.
        image = doom.files["GAME.BIN"]
        m.main[0x0200:0x0200 + len(image)] = image
        bss, size = doom.label("__BSS_RUN__"), doom.label("__BSS_SIZE__")
        m.main[bss:bss + size] = bytes(size)
        m.main[doom.label("kspace")] = 1
        self.call(doom, "gb_init")
        keyboard = doom.label("_kin") + 4
        m.main[keyboard] = 0
        self.call(doom, "debug_sample", limit=3_000_000)
        self.assertEqual(doom.byte("_debug_hz", space="game"), self.video_hz)
        divisor = 10 if self.video_hz == 50 else 12
        self.assertEqual(doom.byte("clk_divisor"), divisor)
        m[doom.label("clk_acc")] = 7
        self.call(doom, "debug_sample", limit=3_000_000)
        self.assertEqual(doom.byte("clk_acc"), 7, "unchanged rate lost fractional time")

        for hz in (110 - self.video_hz, self.video_hz):
            m.main[keyboard] = ord("V")
            self.call(doom, "debug_sample", limit=3_000_000)
            self.assertEqual(doom.byte("_debug_hz", space="game"), hz)
            self.assertEqual(doom.byte("clk_divisor"), 10 if hz == 50 else 12)
            self.assertEqual(doom.byte("clk_acc"), 0)
            self.assertEqual(doom.word("clk_last"), 100)
            m[doom.label("clk_acc")] = 5
            self.call(doom, "debug_sample", limit=3_000_000)
            self.assertEqual(doom.byte("clk_acc"), 5, "held V changed the rate again")
            m.main[keyboard] = 0
            self.call(doom, "debug_sample", limit=3_000_000)
            self.assertEqual(doom.byte("clk_acc"), 5)

        # Clock code belongs to RENDER; the resident divisor must survive the
        # actual image replacement and drive its next conversion.
        image = doom.files["RENDER.BIN"]
        m.main[0x0200:0x0200 + len(image)] = image
        m.main[doom.label("kspace")] = 0
        self.advance(doom, 20)


if __name__ == "__main__":
    unittest.main()
