"""Runner stops distinguish auxiliary LC aliases from real kernel events."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import run_doom  # noqa: E402
import doomdbg  # noqa: E402


class ScriptedMachine:
    def __init__(self, events):
        self.events = iter(events)
        self.mpu = SimpleNamespace(pc=0x0200, processorCycles=0, sp=0xFF,
                                   p=0x20, a=0, x=0, y=0, INTERRUPT=0x04)
        self.main = bytearray(65536)
        self.sw = {"altzp": False}
        self.prodos = None
        self.frame_cycles = 100
        self.speed = 33
        self.idle_cycles = self.io_accesses = self.shr_writes = 0
        self.steps = 0

    def step(self):
        self.steps += 1
        self.mpu.processorCycles += 10
        self.mpu.pc, self.sw["altzp"] = next(self.events, (0x0200, False))

    def shr_image(self):
        return mock.Mock()


def scripted_doom(events, banked=True):
    doom = run_doom.Doom.__new__(run_doom.Doom)
    doom.machine = ScriptedMachine(events)
    doom.mpu = doom.machine.mpu
    doom.banked = {"banks": {"test": 96}} if banked else None
    doom.labels = dict(kernel_start=0x0200, frame_top=0xE000, present_blit=0xE100, present_done=0xE200,
                       present_wait=0xE300, kernel_crash_stop=0xE400)
    doom.boot_cycles = 0
    doom.start_cycle = None
    doom.fast = True
    doom.data_files = {}
    doom.boot = lambda: 0
    doom.byte = lambda name: 0x23 if name == "kcrash" else 0
    return doom


def scripted_debugger(events):
    debugger = doomdbg.Dbg.__new__(doomdbg.Dbg)
    debugger.d = scripted_doom(events)
    debugger.m = debugger.d.machine
    debugger.mpu = debugger.m.mpu
    debugger.L = debugger.d.labels
    debugger.L["test_routine"] = 0xE500
    debugger.cycles = debugger.regs = None
    return debugger


class KernelHookTest(unittest.TestCase):
    def test_run_to_ignores_auxiliary_alias_and_repeats_advance(self):
        doom = scripted_doom([(0xE200, True), (0xD100, True),
                              (0xE200, False), (0xE200, False)])
        self.assertTrue(doom.run_to("present_done", 100))
        self.assertEqual(doom.machine.steps, 3)
        self.assertTrue(doom.run_to("present_done", 100))
        self.assertEqual(doom.machine.steps, 4)

    def test_run_to_limit_does_not_accept_auxiliary_alias(self):
        doom = scripted_doom([(0xE200, True)] * 3)
        self.assertFalse(doom.run_to("present_done", 30))
        self.assertEqual(doom.machine.steps, 3)

    def test_runner_crash_exits_nonzero_and_reports_even_when_quiet(self):
        for banked in (True, False):
            with self.subTest(banked=banked), tempfile.TemporaryDirectory() as directory:
                events = ([(0xE400, True)] if banked else []) + [(0xE400, False)]
                doom = scripted_doom(events, banked)
                args = SimpleNamespace(build=None, data=None, rom=None, speed=33, banks=128,
                                       fast=True, out=directory, do=[], shot=[], quiet=True,
                                       trace=[], trace_limit=0, frames=1,
                                       stats=str(Path(directory) / "stats.json"))
                error = io.StringIO()
                with mock.patch.object(run_doom, "Doom", return_value=doom), \
                        contextlib.redirect_stderr(error):
                    runner = run_doom.Runner(args)
                    self.assertEqual(runner.run(), 1)
                self.assertEqual(doom.machine.steps, len(events))
                self.assertIn("kernel crash $23", error.getvalue())
                report = json.loads(Path(args.stats).read_text())
                self.assertEqual(report["exit_reason"], "kernel_crash")
                self.assertEqual(report["crash"]["code"], 0x23)
                self.assertEqual(report["crash"]["pc"], 0xE400)


class DebuggerHookTest(unittest.TestCase):
    def test_call_ignores_auxiliary_return_and_crash_aliases(self):
        driver = doomdbg.DRIVER
        debugger = scripted_debugger([(driver + 6, False), (driver + 9, True),
                                      (0xE400, True), (driver + 9, False)])
        self.assertEqual(debugger.call("test_routine"), 30)
        self.assertEqual(debugger.m.steps, 4)
        self.assertEqual((debugger.mpu.pc, debugger.mpu.sp, debugger.mpu.p),
                         (0x0200, 0xFF, 0x20))

    def test_call_finishes_a_paused_game_phase_before_injecting_driver(self):
        driver = doomdbg.DRIVER
        # A partial phase copy may already use main ZP and still contain a
        # mixture of renderer/game bytes, so both mapping states must settle.
        for altzp in (True, False):
            debugger = scripted_debugger([(0xE000, True), (0xE000, False),
                                          (driver + 6, False), (driver + 9, False)])
            debugger.mpu.pc = 0xD400
            debugger.m.sw["altzp"] = altzp
            self.assertEqual(debugger.call("test_routine"), 10)
            self.assertEqual(debugger.m.steps, 4)
            self.assertEqual(debugger.mpu.pc, 0xE000)

    def test_call_and_run_frames_raise_on_main_kernel_crash(self):
        for operation in (lambda d: d.call("test_routine"), lambda d: d.run_frames(1)):
            debugger = scripted_debugger([(0xE400, True), (0xE400, False)])
            with self.assertRaisesRegex(RuntimeError, r"kernel crash \$23"):
                operation(debugger)
            self.assertEqual(debugger.m.steps, 2)


if __name__ == "__main__":
    unittest.main()
