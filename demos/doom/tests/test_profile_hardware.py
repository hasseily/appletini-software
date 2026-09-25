#!/usr/bin/env python3
"""UART parsing, coherent snapshot reads, and hardware profile arithmetic."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import profile_hardware as profiler


def metadata():
    specs = [("magic", 4), ("build_id", 4), ("sequence", 2), ("clock", 2),
             ("frames", 2), ("tics", 2), ("hz", 1), ("game", 2), ("render", 2)]
    fields, offset = {}, 0
    for name, width in specs:
        fields[name] = {"offset": offset, "width": width}
        offset += width
    return {"format": 1, "address": 0xE780, "size": offset,
            "magic": "DPR1", "build_id": "01234567", "fields": fields,
            "stages": [{"name": name, "field": name} for name in ("game", "render")]}


def blob(layout, **values):
    result = bytearray(layout.size)
    values = {"sequence": 2, "clock": 100, "frames": 10, "tics": 40,
              "hz": 60, "game": 30, "render": 70, **values}
    for name, value in values.items():
        field = layout.fields[name]
        result[field["offset"]:field["offset"] + field["width"]] = value.to_bytes(field["width"], "little")
    for name, value in (("magic", b"DPR1"), ("build_id", bytes.fromhex("01234567"))):
        start = layout.fields[name]["offset"]
        result[start:start + len(value)] = value
    return bytes(result)


def snapshot(layout, host=1, **values):
    raw = blob(layout, **values)
    return {"utc": f"2026-09-24T00:00:{host:05.2f}+00:00", "host_monotonic": host,
            "read_seconds": 0.04, "attempts": 1, "raw_hex": raw.hex(), "values": layout.decode(raw)}


class FirmwareUART:
    """Relevant uart_control_poll protocol, including its one-command mode.

    Colon enters command mode and emits cmd>; CR executes the buffered line,
    leaves command mode, and emits no new prompt. A leading colon while in
    command mode is an ordinary character and would corrupt the command.
    Reads are deliberately fragmented across command echoes, rows and prompts.
    """

    def __init__(self, partial=None, chunk=7):
        self.command_mode = partial is not None
        self.command_buffer = partial or ""
        self.writes = []
        self.executed = []
        self.idle_input = []
        self.output = bytearray(b"stale unrelated reply\r\ncmd> ")
        self.chunk = chunk

    def reset_input_buffer(self):
        self.output.clear()

    def write(self, data):
        self.writes.append(data)
        for byte in data:
            if self.command_mode:
                if byte in (10, 13):
                    self.output += b"\r\n"
                    command = self.command_buffer
                    self.command_mode = False
                    self.command_buffer = ""
                    self.executed.append(command)
                    if command == "vtw status":
                        self.output += b"vtw: RUNNING\r\nvtw: TURBO selected\r\n"
                    elif command == "vtw dump 0E780 2":
                        self.output += b"0E780: 01 02\r\n"
                    elif command == "vtw dump 0E782 4":
                        self.output += b"0E782: 03 04 05 06\r\n"
                    elif command:
                        self.output += b"Unknown cmd. Use :help\r\n"
                elif byte in (8, 127) and self.command_buffer:
                    self.command_buffer = self.command_buffer[:-1]
                    self.output += b"\b \b"
                elif 32 <= byte <= 126 and len(self.command_buffer) < 127:
                    self.command_buffer += chr(byte)
                    self.output.append(byte)
            elif byte in (ord(":"), ord(";")):
                self.command_mode = True
                self.command_buffer = ""
                self.output += b"\r\ncmd> "
            elif byte not in (8, 10, 13, 127):
                self.idle_input.append(byte)
        return len(data)

    def read(self, count):
        count = min(count, self.chunk)
        data = bytes(self.output[:count])
        del self.output[:count]
        return data


class HardwareProfileTest(unittest.TestCase):
    def setUp(self):
        self.layout = profiler.Layout(metadata())

    def test_memory_api_state_uses_physical_resident_metadata(self):
        self.assertIsNone(profiler.read_memory_api_state(None, metadata()))
        data = metadata()
        data["memory_api"] = {"address_space": "main_shadow",
                              "available_address": 0xE123, "status_address": 0xE124}
        calls = []
        def dump(address, length):
            calls.append((address, length))
            return b"\x01\x00"
        self.assertEqual(profiler.read_memory_api_state(dump, data),
                         {"available": 1, "last_status": 0})
        self.assertEqual(calls, [(0xE123, 2)])
        data["memory_api"]["address_space"] = "cpu"
        with self.assertRaises(profiler.ProfileError):
            profiler.read_memory_api_state(dump, data)

    def test_dump_accepts_echo_and_exact_partial_row(self):
        reply = "vtw dump 0E780 12\r\n0E780: " + " ".join(f"{i:02X}" for i in range(16))
        reply += "\r\n0E790: 10 11\r\ncmd> "
        self.assertEqual(profiler.parse_dump(reply, 0xE780, 18), bytes(range(18)))

    def test_dump_rejects_missing_wrong_duplicate_and_corrupt_rows(self):
        for reply in ("", "0E781: 01 02", "0E780: 01", "0E780: 01 ZZ",
                      "0E780: 01 02\n0E780: 01 02"):
            with self.subTest(reply=reply), self.assertRaises(profiler.ProfileError):
                profiler.parse_dump(reply, 0xE780, 2)

    def test_layout_rejects_overlap_and_bad_bounds(self):
        for key, value in (("size", 0), ("address", 0x24000), ("build_id", "AA")):
            data = metadata()
            data[key] = value
            with self.subTest(key=key), self.assertRaises(profiler.ProfileError):
                profiler.Layout(data)
        data = metadata()
        data["fields"]["clock"]["offset"] = data["fields"]["frames"]["offset"]
        with self.assertRaises(profiler.ProfileError):
            profiler.Layout(data)

    def test_decode_rejects_old_disk_and_uninitialized_clock(self):
        for offset in (0, 4):
            raw = bytearray(blob(self.layout))
            raw[offset] ^= 1
            with self.assertRaises(profiler.ProfileError):
                self.layout.decode(raw)
        with self.assertRaises(profiler.ProfileError):
            self.layout.decode(blob(self.layout, hz=0))

    def test_seqlock_retries_publication_mid_dump(self):
        old, new = blob(self.layout), blob(self.layout, sequence=4)
        responses = iter([b"\x02\0", old, b"\x04\0", b"\x04\0", new, b"\x04\0"])
        times = iter([1.0, 1.1, 2.0, 2.1])
        got = profiler.read_snapshot(lambda *_: next(responses), self.layout,
                                     now=lambda: next(times), pause=lambda _: None)
        self.assertEqual(got["attempts"], 2)
        self.assertEqual(got["values"]["sequence"], 4)
        self.assertAlmostEqual(got["read_seconds"], .1)
        self.assertAlmostEqual(got["host_monotonic"], 2.05)

    def test_seqlock_rejects_odd_and_inside_mismatch(self):
        with self.assertRaises(profiler.ProfileError):
            profiler.read_snapshot(lambda *_: b"\x03\0", self.layout, retries=2, pause=lambda _: None)
        responses = iter([b"\x02\0", blob(self.layout, sequence=4), b"\x02\0"])
        with self.assertRaises(profiler.ProfileError):
            profiler.read_snapshot(lambda *_: next(responses), self.layout, retries=1, pause=lambda _: None)

    def test_rates_and_phase_shares_use_hardware_clock(self):
        a = snapshot(self.layout)
        b = snapshot(self.layout, host=3.3, clock=220, frames=16, tics=110, game=60, render=160)
        result = profiler.interval(a, b, self.layout)
        self.assertTrue(result["valid"])
        self.assertEqual((result["seconds"], result["fps"], result["tps"]), (2, 3, 35))
        self.assertEqual(result["phase_percent"], {"game": 25, "render": 75})

    def test_wraps_all_sixteen_bit_counters(self):
        a = snapshot(self.layout, clock=65500, frames=65534, tics=65500, game=65520, render=65516)
        b = snapshot(self.layout, host=3, clock=84, frames=4, tics=34, game=14, render=70)
        result = profiler.interval(a, b, self.layout)
        self.assertTrue(result["valid"])
        self.assertEqual(result["phase_samples"], {"game": 30, "render": 90})
        self.assertEqual(result["fps"], 3)

    def test_reset_calibration_stall_and_long_gap_are_excluded(self):
        a = snapshot(self.layout, clock=5000, frames=500, tics=2000, game=1000, render=4000)
        cases = [(snapshot(self.layout, host=3), "counter_reset_or_incoherent_clock"),
                 (snapshot(self.layout, host=3, hz=50), "clock_calibration_changed"),
                 (dict(a, host_monotonic=3), "unchanged_snapshot"),
                 (snapshot(self.layout, host=2000), "gap_exceeds_clock_wrap")]
        for current, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(profiler.interval(a, current, self.layout)["reason"], reason)

    def test_incoherent_stage_totals_are_excluded(self):
        a = snapshot(self.layout)
        b = snapshot(self.layout, host=3, clock=220, frames=16, tics=110, game=60, render=159)
        self.assertEqual(profiler.interval(a, b, self.layout)["reason"], "phase_samples_do_not_sum_to_clock")

    def test_pal_rates_and_weighted_aggregate(self):
        snapshots = [snapshot(self.layout, hz=50),
                     snapshot(self.layout, host=3, sequence=4, hz=50, clock=200,
                              frames=16, tics=110, game=80, render=120),
                     snapshot(self.layout, host=7, sequence=6, hz=50, clock=400,
                              frames=28, tics=250, game=100, render=300)]
        capture = {"format": profiler.CAPTURE_FORMAT, "metadata": metadata(), "snapshots": snapshots}
        # Reports decode raw bytes rather than trusting precomputed stored values.
        capture["snapshots"][1]["values"]["clock"] = 42
        result = profiler.report(capture)["summary"]
        self.assertEqual((result["seconds"], result["fps"], result["tps"]), (6, 3, 35))
        self.assertAlmostEqual(result["phase_percent"]["game"], 70 / 3)

    def test_json_csv_offline_roundtrip_and_raw_validation(self):
        capture = {"format": profiler.CAPTURE_FORMAT, "metadata": metadata(),
                   "snapshots": [snapshot(self.layout), snapshot(self.layout, host=3,
                   clock=220, frames=16, tics=110, game=60, render=160)]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            profiler.save_report(capture, path)
            restored = json.loads(path.read_text())
            self.assertEqual(profiler.report(restored)["summary"]["fps"], 3)
            self.assertIn("game_percent", path.with_suffix(".csv").read_text())
            restored["snapshots"][0]["raw_hex"] = "zz"
            with self.assertRaises(profiler.ProfileError):
                profiler.report(restored)

    def test_memory_api_build_uses_host_time_even_below_mismatch_threshold(self):
        meta = metadata()
        meta["memory_api_optional"] = True
        capture = {"format": profiler.CAPTURE_FORMAT, "metadata": meta,
                   "snapshots": [snapshot(self.layout, host=1, hz=50),
                                 snapshot(self.layout, host=61, hz=50, sequence=4,
                                          clock=2950, frames=190, tics=760,
                                          game=980, render=1970)]}
        result = profiler.report(capture)["summary"]
        self.assertEqual(result["clock_check"]["status"], "consistent")
        self.assertEqual(result["timing_source"], "host_window")
        self.assertEqual(result["timing_reason"], "memory_api_holds")
        self.assertEqual((result["seconds"], result["fps"], result["tps"]), (60, 3, 12))
        self.assertEqual(result["counter_seconds"], 57)
        self.assertTrue(result["phase_shares_provisional"])
        self.assertIn("coalesce", result["caveat"])

    def test_console_synchronizes_from_idle_without_executing_commands(self):
        port = FirmwareUART()
        console = profiler.Console(port, timeout=.05)
        console.synchronize()
        self.assertTrue(port.command_mode)
        self.assertEqual(port.command_buffer, "")
        self.assertEqual(port.executed, [])
        self.assertEqual(port.idle_input, [])
        self.assertFalse(port.output, "the fresh prompt must be consumed")
        self.assertEqual(port.writes, [b"\x08" * 128 + b"\r:"])

    def test_console_synchronizes_by_erasing_partial_commands(self):
        for partial in ("", "vtw off", "vtw speed 1mhz", "x" * 127):
            with self.subTest(partial=partial):
                port = FirmwareUART(partial=partial, chunk=3)
                console = profiler.Console(port, timeout=.05)
                console.synchronize()
                self.assertEqual(port.executed, [""],
                                 "synchronization must not execute a partial command")
                self.assertTrue(port.command_mode)
                self.assertEqual(port.command_buffer, "")
                self.assertEqual(port.idle_input, [])
                self.assertEqual(console.dump(0xE780, 2), b"\x01\x02")
                self.assertEqual(port.executed, ["", "vtw dump 0E780 2"])

    def test_console_reenters_command_mode_after_each_complete_reply(self):
        port = FirmwareUART(chunk=1)
        console = profiler.Console(port, timeout=.05)
        console.synchronize()
        status = console.command("vtw status")
        self.assertIn("vtw: RUNNING\r\nvtw: TURBO selected\r\n", status)
        self.assertNotIn("stale unrelated reply", status)
        self.assertEqual(console.dump(0xE780, 2), b"\x01\x02")
        self.assertEqual(console.dump(0xE782, 4), b"\x03\x04\x05\x06")
        self.assertEqual(port.executed,
                         ["vtw status", "vtw dump 0E780 2", "vtw dump 0E782 4"])
        self.assertEqual(port.writes[1:],
                         [b"vtw status\r:", b"vtw dump 0E780 2\r:", b"vtw dump 0E782 4\r:"])
        self.assertTrue(port.command_mode)
        self.assertEqual(port.command_buffer, "")
        self.assertEqual(port.idle_input, [])

    def test_firmware_fixture_requires_explicit_new_prompt(self):
        port = FirmwareUART()
        port.reset_input_buffer()
        port.write(b":")
        self.assertTrue(bytes(port.output).endswith(profiler.PROMPT))
        port.reset_input_buffer()
        port.write(b"vtw status\r")
        self.assertIn(b"vtw: RUNNING", bytes(port.output))
        self.assertFalse(bytes(port.output).endswith(profiler.PROMPT))
        self.assertFalse(port.command_mode)
        port.write(b":")
        self.assertTrue(port.command_mode)
        self.assertTrue(bytes(port.output).endswith(profiler.PROMPT))


class ClockValidationTest(unittest.TestCase):
    def capture(self, elapsed, ticks, duplicate=False):
        layout = profiler.Layout(metadata())
        a = snapshot(layout, host=1, hz=50, clock=100, frames=10, tics=40,
                     game=30, render=70)
        snapshots = [a]
        for index in range(1, 31):
            count = ticks*index//30
            snapshots.append(snapshot(layout, host=1+elapsed*index/30, hz=50,
                                      sequence=2+index*2, clock=100+count,
                                      frames=10+4*index, tics=40+16*index,
                                      game=30+count//2, render=70+count-count//2))
        if duplicate:
            snapshots.insert(1, dict(a, host_monotonic=1+elapsed/60))
        return {"format": profiler.CAPTURE_FORMAT, "metadata": metadata(), "snapshots": snapshots}

    def test_wrong_irq_clock_uses_explicit_host_estimate_and_keeps_counter_rates(self):
        capture = profiler.report(self.capture(60, 4600))
        result = capture["summary"]
        self.assertEqual(result["clock_check"]["status"], "mismatch")
        self.assertEqual(result["timing_source"], "host_window")
        self.assertEqual((result["seconds"], result["fps"], result["tps"]), (60, 2, 8))
        self.assertAlmostEqual(result["counter_seconds"], 92)
        self.assertAlmostEqual(result["counter_fps"], 120/92)
        self.assertTrue(result["phase_shares_provisional"])
        self.assertEqual(capture["intervals"][0]["timing_source"], "host_window")
        self.assertAlmostEqual(sum(item["counter_seconds"] for item in capture["intervals"]), 92)

    def test_correct_clock_and_snapshot_polling_slack_keep_calibrated_rates(self):
        result = profiler.report(self.capture(60, 3000))["summary"]
        self.assertEqual(result["clock_check"]["status"], "consistent")
        self.assertEqual(result["timing_source"], "vbl_calibrated")
        self.assertEqual(result["fps"], 2)
        result = profiler.report(self.capture(61.5, 3000))["summary"]
        self.assertEqual(result["clock_check"]["status"], "consistent")
        self.assertFalse(result["phase_shares_provisional"])

    def test_unchanged_polls_are_included_in_host_duration(self):
        result = profiler.report(self.capture(60, 3000, duplicate=True))["summary"]
        self.assertEqual(result["host_seconds"], 60)
        self.assertEqual(result["host_fps"], 2)
        self.assertEqual(result["clock_check"]["status"], "consistent")


if __name__ == "__main__":
    unittest.main()
