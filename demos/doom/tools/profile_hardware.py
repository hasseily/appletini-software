#!/usr/bin/env python3
"""Capture Doom's hardware VBL profile through Appletini's UART console.

Only `vtw status` and `vtw dump` are sent. The latter reads the live VTW
BRAM port, not the potentially stale DDR write mirror. Published snapshots
are protected by a sequence lock, because UART dumps are not atomic.

Live use needs pyserial (`python -m pip install pyserial`). Offline reports
and tests use only the Python standard library. See docs/PROFILING.md.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Callable

PROJECT = Path(__file__).resolve().parents[1]
PROMPT = b"cmd> "
CAPTURE_FORMAT = "appletini-doom-hardware-profile-v1"
CAVEAT = ("Phase counters are periodic VBL samples, not cycle counts. Short or "
          "repeating phases can lock to the sampling clock; compare longer runs "
          "and different workloads before attributing small differences.")
MEMORY_API_CAVEAT = ("This build can hold the CPU during ARM memory transfers. "
                     "VBL interrupts can coalesce during a hold, so use host-window "
                     "FPS/TPS; phase samples can underrepresent transfer time.")
DUMP_ROW = re.compile(r"^([0-9a-fA-F]{5}):((?: [0-9a-fA-F]{2}){1,16})\s*$")


class ProfileError(RuntimeError):
    """A malformed, incompatible, or incoherent hardware capture."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Layout:
    """Build-specific addresses and field sizes, emitted by the linker build."""

    def __init__(self, metadata: dict):
        self.metadata = metadata
        try:
            if metadata["format"] != 1:
                raise ValueError("unsupported metadata format")
            self.address = int(metadata["address"])
            self.size = int(metadata["size"])
            if not 1 <= self.size <= 0x1000:
                raise ValueError("snapshot must fit one vtw dump (1..4096 bytes)")
            if not 0 <= self.address < self.address + self.size <= 0x24000:
                raise ValueError("snapshot is outside live VTW shadow RAM")
            self.fields = metadata["fields"]
            required = {"magic", "build_id", "sequence", "clock", "frames", "tics", "hz"}
            if not required <= self.fields.keys():
                raise ValueError("missing required snapshot fields")
            occupied: set[int] = set()
            for name, field in self.fields.items():
                offset, width = field["offset"], field["width"]
                if not isinstance(offset, int) or not isinstance(width, int):
                    raise ValueError(f"noninteger field extent: {name}")
                extent = set(range(offset, offset + width))
                if width not in (1, 2, 4, 8) or offset < 0 or offset + width > self.size:
                    raise ValueError(f"invalid field extent: {name}")
                if occupied & extent:
                    raise ValueError(f"overlapping field: {name}")
                occupied |= extent
            self.magic = metadata["magic"].encode("ascii")
            self.build_id = bytes.fromhex(metadata["build_id"])
            if self.magic != b"DPR1" or len(self.build_id) != 4:
                raise ValueError("expected DPR1 and a four-byte build ID")
            if self.fields["magic"]["width"] != 4 or self.fields["build_id"]["width"] != 4:
                raise ValueError("magic and build_id fields must be four bytes")
            if self.fields["sequence"]["width"] != 2 or self.fields["hz"]["width"] != 1:
                raise ValueError("expected a 16-bit sequence and 8-bit hz field")
            self.stages = metadata["stages"]
            if not self.stages:
                raise ValueError("missing stage descriptions")
            names = set()
            stage_fields = set()
            for stage in self.stages:
                if stage["field"] not in self.fields or stage["field"] in required:
                    raise ValueError("unknown or reserved stage counter field")
                if stage["name"] in names or stage["field"] in stage_fields:
                    raise ValueError("duplicate stage name or field")
                names.add(stage["name"])
                stage_fields.add(stage["field"])
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ProfileError(f"invalid profiling metadata: {exc}") from exc

    def field_bytes(self, blob: bytes, name: str) -> bytes:
        field = self.fields[name]
        return blob[field["offset"]:field["offset"] + field["width"]]

    def decode(self, blob: bytes) -> dict:
        if len(blob) != self.size:
            raise ProfileError(f"expected {self.size} snapshot bytes, received {len(blob)}")
        if self.field_bytes(blob, "magic") != self.magic:
            raise ProfileError("profile magic mismatch: boot the profiling disk matching this build")
        if self.field_bytes(blob, "build_id") != self.build_id:
            raise ProfileError("profile build ID mismatch: use metadata from the disk running on hardware")
        values = {name: int.from_bytes(self.field_bytes(blob, name), "little")
                  for name in self.fields if name not in ("magic", "build_id")}
        if values["hz"] not in (50, 60):
            raise ProfileError("profile clock is not initialized to 50 or 60 Hz")
        return values

    def modulus(self, name: str) -> int:
        return 1 << (8 * self.fields[name]["width"])


def parse_dump(reply: str, address: int, length: int) -> bytes:
    """Validate the address and byte count of every requested dump row."""
    result = bytearray()
    for line in reply.splitlines():
        match = DUMP_ROW.fullmatch(line.strip())
        if not match:
            # Command echoes and informational lines are harmless; a malformed
            # dump row is rejected rather than silently converted to a short read.
            if re.match(r"^[0-9a-fA-F]{5}:", line.strip()):
                raise ProfileError(f"malformed vtw dump row: {line}")
            continue
        row = bytes.fromhex(match[2])
        expected = address + len(result)
        remaining = length - len(result)
        if int(match[1], 16) != expected or len(row) != min(16, remaining):
            raise ProfileError("vtw dump returned an unexpected address or row length")
        result += row
    if len(result) != length:
        raise ProfileError(f"incomplete vtw dump: expected {length} bytes, received {len(result)}")
    return bytes(result)


class Console:
    """Single-owner command session; never changes speed or pauses the CPU."""

    def __init__(self, port, timeout: float = 3.0):
        self.port = port
        self.timeout = timeout

    def _prompt(self, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        data = bytearray()
        while time.monotonic() < deadline:
            data += self.port.read(256)
            if data.endswith(PROMPT):
                return bytes(data)
        raise ProfileError("UART console timed out waiting for cmd> (close other serial terminals)")

    def synchronize(self) -> None:
        self.port.reset_input_buffer()
        # Clear any partial 128-byte firmware command before submitting an
        # empty line. In navigation mode backspace/CR are ignored. A colon
        # then enters a fresh command and emits the prompt on either UART.
        self.port.write(b"\x08" * 128 + b"\r:")
        self._prompt(self.timeout)

    def command(self, command: str) -> str:
        # Firmware leaves command mode after CR and does not print another
        # prompt. Re-enter it after the synchronous command completes so the
        # next prompt delimits this reply and leaves an empty command ready.
        self.port.write(command.encode("ascii") + b"\r:")
        reply = self._prompt(self.timeout).decode("ascii", errors="replace")
        return reply[:-len(PROMPT)]

    def dump(self, address: int, length: int) -> bytes:
        return parse_dump(self.command(f"vtw dump {address:05X} {length:X}"), address, length)


def read_snapshot(reader: Callable[[int, int], bytes], layout: Layout, retries: int = 8,
                  now: Callable[[], float] = time.monotonic,
                  pause: Callable[[float], None] = time.sleep) -> dict:
    """Accept only one stable even sequence across before/block/after reads."""
    field = layout.fields["sequence"]
    address, width = layout.address + field["offset"], field["width"]
    for attempt in range(1, retries + 1):
        start = now()
        before = int.from_bytes(reader(address, width), "little")
        if before & 1:
            pause(0.01)
            continue
        blob = reader(layout.address, layout.size)
        inside = int.from_bytes(layout.field_bytes(blob, "sequence"), "little")
        after = int.from_bytes(reader(address, width), "little")
        end = now()
        if before == inside == after and not after & 1:
            values = layout.decode(blob)
            return {"utc": utc_now(), "host_monotonic": (start + end) / 2,
                    "read_seconds": end - start, "attempts": attempt,
                    "raw_hex": blob.hex(), "values": values}
        pause(0.01)
    raise ProfileError(f"no stable profile snapshot after {retries} attempts")


def interval(previous: dict, current: dict, layout: Layout) -> dict:
    """Difference one interval, preserving wraps but excluding resets/gaps."""
    old, new = previous["values"], current["values"]
    host_seconds = current["host_monotonic"] - previous["host_monotonic"]
    result = {"start_utc": previous["utc"], "end_utc": current["utc"],
              "host_seconds": host_seconds, "valid": False}

    def reject(reason):
        result["reason"] = reason
        return result

    if host_seconds <= 0 or not math.isfinite(host_seconds):
        return reject("invalid_host_time")
    if old["hz"] != new["hz"]:
        return reject("clock_calibration_changed")
    hz = new["hz"]
    # Beyond one clock wrap there is no unique counter difference. Faster
    # counters are also checked below against the observed wall-clock delta.
    if host_seconds >= layout.modulus("clock") / hz:
        return reject("gap_exceeds_clock_wrap")
    delta = {name: (new[name] - old[name]) % layout.modulus(name)
             for name in ("clock", "frames", "tics")}
    stage_delta = {s["name"]: (new[s["field"]] - old[s["field"]])
                   % layout.modulus(s["field"]) for s in layout.stages}
    ticks = delta["clock"]
    if not ticks:
        return reject("unchanged_snapshot")
    # Publication is delayed to a frame boundary. Allow 10 seconds of slack
    # for a very slow frame/load, while detecting the huge delta from resets.
    tolerance = hz * (host_seconds + 10 + previous.get("read_seconds", 0)
                      + current.get("read_seconds", 0))
    if ticks > tolerance:
        return reject("counter_reset_or_incoherent_clock")
    if sum(stage_delta.values()) != ticks:
        return reject("phase_samples_do_not_sum_to_clock")
    if delta["frames"] > ticks + 1 or delta["tics"] > ticks + 8:
        return reject("counter_reset_or_incoherent_counts")
    seconds = ticks / hz
    samples = sum(stage_delta.values())
    result.update(valid=True, hz=hz, clock=ticks, seconds=seconds,
                  frames=delta["frames"], tics=delta["tics"],
                  fps=delta["frames"] / seconds, tps=delta["tics"] / seconds,
                  phase_samples=stage_delta,
                  phase_percent={name: count * 100 / samples
                                 for name, count in stage_delta.items()})
    return result


def report(capture: dict) -> dict:
    """Recompute a report from raw snapshots, never trusting stored rates."""
    if capture.get("format") != CAPTURE_FORMAT:
        raise ProfileError("unsupported capture format")
    layout = Layout(capture["metadata"])
    memory_api = capture["metadata"].get("memory_api_optional") is True
    snapshots = capture["snapshots"]
    for snapshot in snapshots:
        try:
            blob = bytes.fromhex(snapshot["raw_hex"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProfileError(f"invalid saved raw snapshot: {exc}") from exc
        snapshot["values"] = layout.decode(blob)
        if snapshot["values"]["sequence"] & 1:
            raise ProfileError("saved snapshot has an odd publication sequence")
    intervals = [interval(a, b, layout) for a, b in zip(snapshots, snapshots[1:])]
    valid = [item for item in intervals if item["valid"]]
    seconds = sum(item["seconds"] for item in valid)
    frames, tics = (sum(item[name] for item in valid) for name in ("frames", "tics"))
    phase_samples = {stage["name"]: sum(item["phase_samples"][stage["name"]]
                                        for item in valid) for stage in layout.stages}
    samples = sum(phase_samples.values())
    summary = {"valid_intervals": len(valid), "excluded_intervals": len(intervals) - len(valid),
               "seconds": seconds, "frames": frames, "tics": tics,
               "fps": frames / seconds if seconds else None,
               "tps": tics / seconds if seconds else None,
               "phase_samples": phase_samples,
               "phase_percent": {name: count * 100 / samples if samples else None
                                 for name, count in phase_samples.items()},
               "samples": samples,
               "caveat": CAVEAT + (" " + MEMORY_API_CAVEAT if memory_api else "")}
    # Check the calibrated IRQ clock against independent host time over a
    # long window. Snapshot publication makes short-window comparisons noisy.
    # Include unchanged polls in elapsed host time; they are useful duration
    # observations even though they add no counter differences.
    host_intervals = [item for item in intervals if item["valid"] or
                      item.get("reason") == "unchanged_snapshot"]
    host_seconds = sum(item["host_seconds"] for item in host_intervals)
    host_fps = frames / host_seconds if host_seconds and valid else None
    host_tps = tics / host_seconds if host_seconds and valid else None
    tolerance = max(3.0, host_seconds * 0.10)
    status = "insufficient_duration"
    if host_seconds >= 20 and valid:
        status = "consistent" if abs(seconds - host_seconds) <= tolerance else "mismatch"
    summary.update(
        timing_source="vbl_calibrated", counter_seconds=seconds,
        counter_fps=summary["fps"], counter_tps=summary["tps"],
        host_seconds=host_seconds, host_fps=host_fps, host_tps=host_tps,
        clock_check={"status": status, "tolerance_seconds": tolerance,
                     "selected_hz": sorted({item["hz"] for item in valid}),
                     "observed_interrupt_hz": samples / host_seconds if host_seconds else None},
        phase_shares_provisional=(status == "mismatch" or memory_api),
        memory_api_holds_possible=memory_api)
    for item in valid:
        item.update(timing_source="vbl_calibrated", clock_check=status,
                    counter_seconds=item["seconds"], counter_fps=item["fps"], counter_tps=item["tps"])
    if status == "mismatch" or memory_api:
        # Retain counter-derived rates for diagnostics, but do not present
        # them as elapsed hardware time. These host-window rates are estimates:
        # each endpoint reads a recently published frame-boundary snapshot.
        summary.update(timing_source="host_window", seconds=host_seconds,
                       fps=host_fps, tps=host_tps,
                       timing_reason="memory_api_holds" if memory_api else "clock_mismatch")
        for item in valid:
            item.update(timing_source="host_window", seconds=item["host_seconds"],
                        fps=item["frames"] / item["host_seconds"],
                        tps=item["tics"] / item["host_seconds"])
    capture["intervals"], capture["summary"] = intervals, summary
    return capture


def save_report(capture: dict, path: Path) -> None:
    if path.suffix.lower() != ".json":
        raise ProfileError("--out must end in .json (the companion report uses .csv)")
    report(capture)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve a complete previous report if interrupted during a write.
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(capture, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)
    stages = [stage["name"] for stage in capture["metadata"]["stages"]]
    csv_path = path.with_suffix(".csv")
    temporary_csv = csv_path.with_name(csv_path.name + ".tmp")
    fixed = ["start_utc", "end_utc", "valid", "reason", "host_seconds", "seconds",
             "hz", "clock", "frames", "tics", "fps", "tps", "timing_source", "clock_check",
             "counter_seconds", "counter_fps", "counter_tps"]
    columns = fixed + [f"{name}_{suffix}" for name in stages for suffix in ("samples", "percent")]
    with temporary_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for item in capture["intervals"]:
            row = {key: item.get(key, "") for key in fixed}
            for stage in stages:
                row[f"{stage}_samples"] = item.get("phase_samples", {}).get(stage, "")
                row[f"{stage}_percent"] = item.get("phase_percent", {}).get(stage, "")
            writer.writerow(row)
    temporary_csv.replace(csv_path)


def read_memory_api_state(dump: Callable, metadata: dict) -> dict | None:
    """Read stable resident probe/result bytes, outside the timed window."""
    info = metadata.get("memory_api")
    if info is None:
        return None
    if info.get("address_space") != "main_shadow":
        raise ProfileError("memory API state requires physical MAIN shadow addresses")
    addresses = [info["available_address"], info["status_address"]]
    if any(not isinstance(addr, int) or not 0xE000 <= addr < 0xFFFA for addr in addresses):
        raise ProfileError("invalid resident memory API state addresses")
    start, end = min(addresses), max(addresses) + 1
    raw = dump(start, end - start)
    if len(raw) != end - start:
        raise ProfileError("incomplete memory API state")
    return {"available": raw[addresses[0] - start],
            "last_status": raw[addresses[1] - start]}


def print_summary(capture: dict) -> None:
    summary = capture["summary"]
    if summary["fps"] is None:
        print("No valid measurement intervals; inspect excluded intervals/events in the JSON.")
        return
    mismatch = summary["clock_check"]["status"] == "mismatch"
    if mismatch:
        hz = "/".join(str(value) for value in summary["clock_check"]["selected_hz"])
        print(f"CLOCK MISMATCH: selected {hz} Hz; observed approximately "
              f"{summary['clock_check']['observed_interrupt_hz']:.2f} interrupts/host-second.")
        print(f"Counter-derived {summary['counter_seconds']:.1f}s disagrees with "
              f"{summary['host_seconds']:.1f}s host time; counter-derived FPS/TPS are unreliable.")
    timing = ("host window (approximate rates)"
              if summary["timing_source"] == "host_window" else "VBL-calibrated time")
    print(f"{summary['seconds']:.1f}s {timing}; {summary['frames']} frames, "
          f"{summary['tics']} tics; {summary['fps']:.2f} FPS, {summary['tps']:.2f} TPS")
    api = capture.get("transport", {}).get("memory_api_end")
    if api is not None:
        print(f"Memory API: {'enabled' if api['available'] == 1 else 'CPU fallback'}; "
              f"last status=${api['last_status']:02X}")
    if mismatch:
        print("Phase shares are provisional too: check the IRQ source/calibration and recapture.")
    for name, count in sorted(summary["phase_samples"].items(), key=lambda pair: -pair[1]):
        print(f"  {name:24s} {summary['phase_percent'][name]:6.2f}%  ({count} VBL samples)")
    if summary["excluded_intervals"]:
        print(f"Excluded intervals: {summary['excluded_intervals']} (see JSON/CSV reasons)")
    print(summary["caveat"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=PROJECT / "build/profile")
    parser.add_argument("--metadata", type=Path, help="override build/profile/profile.json")
    parser.add_argument("--port", default=os.environ.get("APPLETINI_PORT"))
    parser.add_argument("--baud", type=int, default=int(os.environ.get("APPLETINI_BAUD", "921600")))
    parser.add_argument("--seconds", type=float, default=60, help="host capture duration (default: 60)")
    parser.add_argument("--interval", type=float, default=2, help="seconds between snapshots (default: 2)")
    parser.add_argument("--out", type=Path, default=Path("doom-profile.json"))
    parser.add_argument("--label", default="", help="workload/map/mode description for this run")
    parser.add_argument("--mode", choices=("turbo", "standard", "unknown"), default="unknown",
                        help="record selected hardware mode; does not change it")
    parser.add_argument("--report", type=Path, help="rebuild JSON/CSV report from a saved capture, without UART")
    parser.add_argument("--list-ports", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.report:
            capture = json.loads(args.report.read_text())
            save_report(capture, args.out)
            print_summary(capture)
            return 0 if capture["summary"]["valid_intervals"] else 1
        try:
            import serial  # type: ignore  # optional live-capture dependency
        except ImportError as exc:
            raise ProfileError("live capture needs pyserial: python -m pip install pyserial") from exc
        if args.list_ports:
            from serial.tools import list_ports  # type: ignore
            for port in list_ports.comports():
                print(f"{port.device}\t{port.description}")
            return 0
        if not args.port:
            raise ProfileError("choose --port (or APPLETINI_PORT); use --list-ports to find it")
        if (not math.isfinite(args.seconds) or args.seconds <= 0 or
                not math.isfinite(args.interval) or args.interval < 0.1):
            raise ProfileError("--seconds must be positive and --interval must be at least 0.1 seconds")
        layout = Layout(json.loads((args.metadata or args.build / "profile.json").read_text()))
        capture = {"format": CAPTURE_FORMAT, "metadata": layout.metadata,
                   "started_utc": utc_now(), "label": args.label, "mode": args.mode,
                   "transport": {"kind": "vtw dump", "port": args.port, "baud": args.baud},
                   "snapshots": [], "events": []}
        kwargs = {"timeout": 0.1, "write_timeout": 3}
        if os.name == "posix":
            kwargs["exclusive"] = True
        with serial.Serial(args.port, args.baud, **kwargs) as port:
            console = Console(port)
            console.synchronize()
            capture["transport"]["status"] = console.command("vtw status")
            capture["transport"]["memory_api_start"] = read_memory_api_state(console.dump, layout.metadata)
            start = time.monotonic()
            deadline, next_sample = start + args.seconds, start
            print(f"Capturing {args.seconds:g}s from {args.port}; keep the selected workload running.")
            try:
                while True:
                    delay = next_sample - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    snapshot = read_snapshot(console.dump, layout)
                    capture["snapshots"].append(snapshot)
                    save_report(capture, args.out)
                    if time.monotonic() >= deadline:
                        break
                    next_sample = min(deadline, max(next_sample + args.interval, time.monotonic()))
            except KeyboardInterrupt:
                capture["events"].append({"utc": utc_now(), "kind": "interrupted"})
                print("\nCapture stopped; saving collected samples.")
            except (ProfileError, OSError) as exc:
                capture["events"].append({"utc": utc_now(), "kind": "capture_error", "message": str(exc)})
                capture["finished_utc"] = utc_now()
                save_report(capture, args.out)
                raise
            # Preserve both ends of firmware counters (including posted-write
            # queue statistics) for TURBO comparisons without polling them.
            try:
                capture["transport"]["status_end"] = console.command("vtw status")
                capture["transport"]["memory_api_end"] = read_memory_api_state(console.dump, layout.metadata)
            except (ProfileError, OSError) as exc:
                capture["events"].append({"utc": utc_now(), "kind": "status_end_error",
                                          "message": str(exc)})
        capture["finished_utc"] = utc_now()
        save_report(capture, args.out)
        print_summary(capture)
        print(f"Saved {args.out} and {args.out.with_suffix('.csv')}")
        return 0 if capture["summary"]["valid_intervals"] else 1
    except (ProfileError, OSError, ValueError) as exc:
        print(f"profile_hardware: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
