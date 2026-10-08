"""Behavioral checks for the public runner and persistent debugger protocol."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "emulator" / "appletini"
WRITE_ABCD = "a9418d0003a9428d0103a9438d0203a9448d0303db"


class AppletiniCLITests(unittest.TestCase):
    def invoke(self, *args, stdin=None):
        result = subprocess.run(
            [str(RUNNER), *args], input=stdin, text=True,
            cwd=ROOT, capture_output=True, timeout=60,
        )
        try:
            records = [json.loads(line) for line in result.stdout.splitlines()]
        except json.JSONDecodeError as exc:
            self.fail(f"stdout was not JSONL: {result.stdout!r}; stderr={result.stderr!r}: {exc}")
        self.assertTrue(records, result.stderr)
        for record in records:
            self.assertEqual(record["schema"], "appletini-cli-1")
        return result, records

    def debug(self, requests, *args):
        source = "\n".join(
            json.dumps(item) if not isinstance(item, str) else item
            for item in requests
        ) + "\n"
        return self.invoke("debug", *args, stdin=source)

    def test_raw_program_is_deterministic_and_dump_matches_assertion(self):
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "program.bin"
            dump = Path(temp) / "bytes.bin"
            binary.write_bytes(bytes.fromhex(WRITE_ABCD))
            args = (
                "run", "--binary", str(binary), "--steps", "100",
                "--expect", "main:0x300=41424344", "--require-stop",
                "--dump", f"main:0x300:4:{dump}",
            )
            first, records = self.invoke(*args)
            second, repeated = self.invoke(*args)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertTrue(records[0]["ok"])
            self.assertEqual(records[0]["reason"], "stp")
            self.assertEqual(records[0]["state"], repeated[0]["state"])
            self.assertTrue(records[0]["assertions"][0]["passed"])
            self.assertEqual(dump.read_bytes(), b"ABCD")

    def test_breakpoint_at_initial_pc_runs_no_instruction(self):
        result, records = self.invoke(
            "run", "--hex", WRITE_ABCD, "--steps", "100",
            "--breakpoint", "0x2000", "--expect", "main:0x300=00000000",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        record = records[0]
        self.assertEqual(record["reason"], "breakpoint")
        self.assertEqual(record["execution"]["steps"], 0)
        self.assertEqual(record["state"]["registers"]["pc"], 0x2000)

    def test_debugger_step_then_resume_to_breakpoint_preserves_machine(self):
        result, records = self.debug([
            {"cmd": "run", "id": "initial", "steps": 100, "breakpoints": ["0x2000"]},
            {"cmd": "step", "id": "load"},
            {"cmd": "run", "id": "store", "steps": 100, "breakpoints": ["0x2005"]},
            {"cmd": "read", "space": "main", "address": "0x300", "length": 4},
            {"cmd": "run", "steps": 100},
            {"cmd": "assert", "address": "0x300", "data": "41424344"},
            {"cmd": "quit"},
        ], "--hex", WRITE_ABCD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(records[0]["reason"], "breakpoint")
        self.assertEqual(records[1]["id"], "load")
        self.assertEqual(records[1]["state"]["registers"]["a"], 0x41)
        self.assertEqual(records[1]["state"]["registers"]["pc"], 0x2002)
        self.assertEqual(records[2]["state"]["registers"]["pc"], 0x2005)
        self.assertEqual(records[3]["data"], "41000000")
        self.assertEqual(records[4]["reason"], "stp")
        self.assertTrue(records[5]["assertion"]["passed"])

    def test_cycle_budget_stops_at_whole_instruction_boundary(self):
        result, records = self.invoke("run", "--hex", "80fe", "--cycles", "10")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = records[0]
        self.assertEqual(record["reason"], "cycles")
        self.assertEqual(record["state"]["ticks"], 12)
        self.assertEqual(record["state"]["cycles"], 12)
        self.assertEqual(record["execution"]["steps"], 4)

    def test_missing_required_stop_and_assertion_failure_are_nonzero(self):
        result, records = self.invoke(
            "run", "--hex", "80fe", "--steps", "10", "--require-stop",
        )
        self.assertEqual(result.returncode, 3)
        self.assertFalse(records[0]["ok"])
        failed, records = self.invoke(
            "run", "--hex", WRITE_ABCD, "--steps", "100",
            "--expect", "main:0x300=deadbeef",
        )
        self.assertEqual(failed.returncode, 1)
        self.assertFalse(records[0]["ok"])
        self.assertEqual(records[0]["assertions"][0]["actual"], "41424344")

    def test_raw_write_bounds_are_atomic_and_do_not_alias_aux(self):
        result, records = self.debug([
            {"cmd": "write", "address": "0xffff", "data": "aa"},
            {"cmd": "write", "address": "0xffff", "data": "bbcc"},
            {"cmd": "read", "address": "0xffff", "length": 1},
            {"cmd": "write", "space": "aux127", "address": "0x1234", "data": "55"},
            {"cmd": "read", "space": "aux127", "address": "0x1234", "length": 1},
            {"cmd": "read", "space": "aux0", "address": "0x1234", "length": 1},
            {"cmd": "read", "space": "main", "address": "0x1234", "length": 1},
            {"cmd": "read", "space": "aux128", "address": 0, "length": 1},
            {"cmd": "quit"},
        ])
        self.assertEqual(result.returncode, 2)
        self.assertFalse(records[1]["ok"])
        self.assertEqual(records[2]["data"], "aa")
        self.assertEqual(records[4]["data"], "55")
        self.assertEqual(records[5]["data"], "00")
        self.assertEqual(records[6]["data"], "00")
        self.assertFalse(records[7]["ok"])

    def test_invalid_register_batch_has_no_partial_effect(self):
        result, records = self.debug([
            {"cmd": "registers", "values": {"a": 7}},
            {"cmd": "registers", "values": {"a": 9, "x": 256}},
            {"cmd": "registers"},
            {"cmd": "quit"},
        ])
        self.assertEqual(result.returncode, 2)
        self.assertFalse(records[1]["ok"])
        self.assertEqual(records[2]["registers"]["a"], 7)

    def test_malformed_requests_report_errors_and_session_recovers(self):
        result, records = self.debug([
            "{", [], {"cmd": "unknown", "id": 3},
            {"cmd": "state", "extra": True, "id": 4},
            {"cmd": "step", "steps": True, "id": 5},
            {"cmd": "write", "address": "0x300", "data": "beef", "id": 6},
            {"cmd": "assert", "address": "0x300", "data": "beef", "id": 7},
            {"cmd": "quit", "id": 8},
        ])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(records), 8)
        self.assertTrue(all(not row["ok"] for row in records[:5]))
        self.assertEqual(records[2]["id"], 3)
        self.assertEqual(records[6]["id"], 7)
        self.assertTrue(records[6]["assertion"]["passed"])

    def test_raw_inspection_does_not_trigger_softswitches(self):
        result, records = self.debug([
            {"cmd": "state"},
            {"cmd": "read", "space": "main", "address": "0xc003", "length": 1},
            {"cmd": "state"},
            {"cmd": "bus-write", "address": "0xc003", "value": 0},
            {"cmd": "state"},
            {"cmd": "quit"},
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(records[0]["state"]["switches"]["ramrd"])
        self.assertFalse(records[2]["state"]["switches"]["ramrd"])
        self.assertTrue(records[4]["state"]["switches"]["ramrd"])

    def test_turbo_requires_explicit_selection_and_reports_model_version(self):
        normal, base = self.invoke("run", "--hex", "db", "--steps", "10")
        turbo, fast = self.invoke(
            "run", "--hex", "db", "--steps", "10", "--profile", "turbo-f122",
        )
        self.assertEqual(normal.returncode, 0, normal.stderr)
        self.assertEqual(turbo.returncode, 0, turbo.stderr)
        self.assertEqual(base[0]["machine"]["profile"], "ultrawarp")
        self.assertEqual(base[0]["machine"]["ram_bytes"], 8 * 1024 * 1024)
        self.assertEqual(base[0]["machine"]["slot2"], "mouse")
        self.assertEqual(base[0]["machine"]["slot4"], "phasor")
        self.assertEqual(base[0]["machine"]["slot7"], "smartport")
        self.assertEqual(base[0]["machine"]["clock_unit"], "cpu-cycle")
        self.assertFalse(base[0]["machine"]["hardware_timing_validated"])
        self.assertEqual(fast[0]["machine"]["clock_unit"], "fabric-clock")
        self.assertEqual(fast[0]["machine"]["cost_firmware_commit"], "3101934")
        self.assertEqual(fast[0]["machine"]["timing"], "historical-turbo-cost-model")
        self.assertFalse(fast[0]["machine"]["hardware_timing_validated"])

    def test_keyboard_controller_state_reaches_apple_and_selected_slot2(self):
        result, records = self.debug([
            {"cmd": "keyboard-state", "codes": ["KeyQ", "Space"]},
            {"cmd": "bus-read", "address": "0xc061"},
            {"cmd": "configure", "slot2": "4play"},
            {"cmd": "bus-read", "address": "0xc0a0"},
            {"cmd": "keyboard-state", "codes": []},
            {"cmd": "bus-read", "address": "0xc0a0"},
            {"cmd": "configure", "slot2": "snes"},
            {"cmd": "keyboard-state", "codes": ["KeyJ", "KeyK", "Enter"]},
            {"cmd": "bus-write", "address": "0xc0a0", "value": 0},
            {"cmd": "bus-read", "address": "0xc0a0"},
            {"cmd": "bus-write", "address": "0xc0a1", "value": 0},
            {"cmd": "bus-read", "address": "0xc0a0"},
            {"cmd": "quit"},
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(records[1]["value"] & 0x80, 0x80)
        self.assertEqual(records[2]["machine"]["slot2"], "4play")
        self.assertEqual(records[3]["value"], 0xA5)
        self.assertEqual(records[5]["value"], 0x20)
        self.assertEqual(records[6]["machine"]["slot2"], "snes")
        self.assertEqual(records[9]["value"] & 0x80, 0x80)  # B released, active low.
        self.assertEqual(records[11]["value"] & 0x80, 0)  # Y held after one clock.

    def test_live_acceleration_preserves_state_and_uses_stable_budget_ticks(self):
        result, records = self.debug([
            {"cmd": "write", "address": "0x300", "data": "cafe"},
            {"cmd": "run", "steps": 10},
            {"cmd": "configure", "profile": "vtw26"},
            {"cmd": "state"},
            {"cmd": "run", "cycles": 300},
            {"cmd": "assert", "address": "0x300", "data": "cafe"},
            {"cmd": "configure", "profile": "mhz1"},
            {"cmd": "run", "cycles": 400},
            {"cmd": "quit"},
        ], "--hex", "80fe")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(records[3]["state"], records[1]["state"])
        self.assertEqual(records[2]["machine"]["profile"], "vtw26")
        self.assertEqual(records[2]["machine"]["clock_profile"], "ultrawarp")
        self.assertEqual(records[2]["machine"]["clock_unit"], "machine-tick")
        self.assertEqual(records[4]["execution"]["steps"], 200)
        self.assertEqual(records[7]["execution"]["steps"], 10)
        self.assertTrue(records[5]["assertion"]["passed"])

    def test_invalid_acceleration_and_slot_configuration_is_atomic(self):
        result, records = self.debug([
            {"cmd": "configure", "profile": "vtw26", "slot2": "bad"},
            {"cmd": "configure", "profile": "turbo-f122", "slot2": "snes"},
            {"cmd": "configure", "profile": 26},
            {"cmd": "state"},
            {"cmd": "quit"},
        ], "--hex", "80fe")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(all(not row["ok"] for row in records[:3]))
        self.assertIn("restart", records[1]["error"])
        self.assertEqual(records[3]["machine"]["profile"], "ultrawarp")
        self.assertEqual(records[3]["machine"]["slot2"], "mouse")
        self.assertEqual(records[3]["state"]["ticks"], 0)

    def test_load_rejects_program_crossing_io_space(self):
        result, records = self.invoke(
            "run", "--hex", "eadb", "--load-address", "0xbfff", "--steps", "10",
        )
        self.assertEqual(result.returncode, 2)
        self.assertFalse(records[0]["ok"])
        self.assertIn("$C000", records[0]["error"])


if __name__ == "__main__":
    unittest.main()
