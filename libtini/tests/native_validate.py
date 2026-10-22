#!/usr/bin/env python3
"""Run diagnostic + target tests on the repository's native Appletini machine.

These are emulator checks. Profile clocks/costs do not establish board timing.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import native_emulator


def labels(path):
    result = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "al":
            result[fields[2].lstrip(".")] = int(fields[1], 16)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", required=True, help="installed GCC executable")
    args = parser.parse_args()
    library = native_emulator.build(args.cc)
    sys.path.insert(0, str(native_emulator.FRONT))
    import cli
    from video import screenshot
    cli.build_library = lambda: library
    native_emulator.OUT.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("libtini_disk_packager", ROOT / "tools/disk.py")
    packager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packager)
    test_disk = ROOT / "build/native/test_target.po"
    test_disk.write_bytes(packager.build_image((ROOT / "build/libtini.po").read_bytes(),
                                              (ROOT / "build/test_target.system").read_bytes()))
    evidence = {"source_revision": native_emulator.source_revision(),
                "disk_sha256": native_emulator.digest(ROOT / "build/libtini.po"),
                "diagnostic_sha256": native_emulator.digest(ROOT / "build/libtini.system"),
                "board_evidence": False, "profiles": []}
    for profile in ("vtw33", "turbo-f122"):
        options = cli.parser().parse_args(["debug", "--disk", str(ROOT / "build/libtini.po"),
                                         "--system", "LIBTINI.SYSTEM", "--profile", profile])
        machine = cli.Machine(options)
        try:
            # Independent data behind the shared AUX0 screen and probe address.
            # This is model storage, not a mounted ProDOS RAM-disk fixture.
            auxiliary = bytes((i * 31 + (i >> 8) + 19) & 255 for i in range(65536))
            machine.write("aux0", 0, auxiliary)
            fixtures = [(0x80, bytes((i * 13 + 7) & 255 for i in range(26))),
                        (0x100, bytes([0x4A]) * 64),
                        (0x140, bytes((i * 5 + 11) & 255 for i in range(64))),
                        (0x3F2, bytes([0x19, 0xBF, 0x1A]))]
            for address, data in fixtures:
                machine.write("main", address, data)
            # Valid main-code entry with non-default readable display flags.
            machine.check(machine.lib.ap_bus_write(machine.handle, 0xC001, 0))
            machine.check(machine.lib.ap_bus_write(machine.handle, 0xC055, 0))
            machine.check(machine.lib.ap_bus_write(machine.handle, 0xC053, 0))
            machine.check(machine.lib.ap_bus_write(machine.handle, 0xC00F, 0))
            machine.check(machine.lib.ap_bus_write(machine.handle, 0xC00D, 0))
            entry_switches = machine.state()["switches"].copy()
            displayed = machine.run(frames=120)
            assert displayed["reason"] == "cycles", displayed
            assert displayed["state"]["newvideo"] == 0xC1, displayed
            binary_labels = labels(ROOT / "build/libtini.lbl")
            assert "_results" in binary_labels, "diagnostic must export its five test results"
            assert machine.read("main", binary_labels["_results"], 5) == bytes([1]) * 5
            image = ROOT / f"build/native/diagnostic-{profile}.png"
            preview = screenshot(machine, image)
            # All writes have been ordinary CPU writes through the AUX switches.
            assert displayed["state"]["shr_writes"] >= 32768
            machine.check(machine.lib.ap_input(machine.handle, b"key", 13, 0))
            exited = machine.run(frames=20)
            assert exited["reason"] == "quit", exited
            state = exited["state"]
            assert state["newvideo"] == 1 and state["bank"] == 0
            assert state["switches"] == entry_switches, (state["switches"], entry_switches)
            assert machine.read("aux0", 0, 65536) == auxiliary
            for address, data in fixtures:
                assert machine.read("main", address, len(data)) == data, hex(address)
            evidence["profiles"].append({"profile": profile, "machine": machine.metadata(),
                                         "screen": displayed, "exit": exited,
                                         "preview": preview, "preview_sha256": native_emulator.digest(image),
                                         "restored_aux0_bytes": 65536,
                                         "restored_zero_page_bytes": 26,
                                         "restored_trampoline_bytes": 64,
                                         "preserved_prodos_stack_bytes": 64,
                                         "preserved_reset_vector_bytes": 3})
        finally:
            machine.close()

        # The same full C/assembly target suite that runs under py65.
        options = cli.parser().parse_args(["debug", "--disk", str(test_disk),
                                         "--system", "LIBTINI.SYSTEM", "--profile", profile])
        machine = cli.Machine(options)
        try:
            result = machine.run(steps=30_000_000, timeout=30)
            assert result["reason"] == "quit", result
            binary_labels = labels(ROOT / "build/test_target.lbl")
            failed = int.from_bytes(machine.read("main", binary_labels["_test_failed"], 2), "little")
            checks = int.from_bytes(machine.read("main", binary_labels["_test_checks"], 2), "little")
            assert not failed, (profile, failed)
            assert checks > 4000, checks
            evidence["profiles"][-1]["target_suite"] = {"checks": checks, "failed": failed, "run": result}
        finally:
            machine.close()
        print(profile + ": diagnostic screen, state/AUX restoration, MLI QUIT, " + str(checks) + " target checks passed")
    first, second = evidence["profiles"]
    assert first["preview_sha256"] == second["preview_sha256"], "profile-dependent diagnostic screen"
    path = ROOT / "build/native/validation.json"
    path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(path)


if __name__ == "__main__":
    main()
