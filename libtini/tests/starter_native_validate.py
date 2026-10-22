#!/usr/bin/env python3
"""Boot the starter game from ProDOS and drive it through held keys and a stick.

The program image and state are never patched; only exported state and the
native machine are read. Timing belongs to the emulator models, not a board.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import native_emulator
from apple2_model import read_labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="C:/msys64/ucrt64/bin/gcc.exe")
    parser.add_argument("--private", action="store_true", help="validate build/private outputs")
    args = parser.parse_args()
    library = native_emulator.build(args.cc)
    sys.path.insert(0, str(native_emulator.FRONT))
    import cli
    from video import screenshot
    cli.build_library = lambda: library

    build_dir = ROOT / ("build/private" if args.private else "build")
    output = ROOT / ("build/starter/native-ui-private" if args.private else "build/starter/native-ui")
    output.mkdir(parents=True, exist_ok=True)
    labels = read_labels(build_dir / "starter.lbl")
    disk_path = build_dir / "starter.po"
    image = (build_dir / "starter.system").read_bytes()
    evidence = {"board_evidence": False, "private_build": args.private, "state_mutations": False,
                "disk_sha256": native_emulator.digest(disk_path),
                "system_sha256": native_emulator.digest(build_dir / "starter.system"), "runs": []}
    for profile in ("vtw33", "turbo-f122"):
        rom = ROOT / "build-inputs/native-roms"
        options = cli.parser().parse_args([
            "debug", "--boot", "--disk", str(disk_path), "--profile", profile,
            "--rom", str(rom / "Apple2e_Enhanced.rom"),
            "--slot7-rom", str(rom / "smartport_a2retronet_style_c700.mem"),
            "--slot7-c8-rom", str(rom / "smartport_a2retronet_style_c800.mem"),
            "--video-rom", str(rom / "apple2e-video.bin"),
        ])
        machine = cli.Machine(options)
        trace = []
        poll_address = labels["_ti_input_poll"]

        def position():
            return [int.from_bytes(machine.read("main", labels[name], 2), "little", signed=True)
                    for name in ("_starter_x", "_starter_y")]

        def settle():
            if machine.get("pc") == poll_address:
                machine.run(steps=1)
            result = machine.run(frames=360, breakpoints=[poll_address], timeout=30)
            assert result["reason"] == "breakpoint", (profile, "input poll deadline", result)
            return position()

        def advance(frames):
            if machine.get("pc") == poll_address:
                machine.run(steps=1)
            while frames:
                count = min(frames, 6)
                assert machine.run(frames=count, timeout=30)["reason"] == "cycles"
                frames -= count
            return settle()

        def send(kind, value=0, extra=0):
            machine.check(machine.lib.ap_input(machine.handle, kind, value, extra))

        try:
            for _ in range(8):
                entry = machine.run(frames=600, breakpoints=[0x2000], timeout=30)
                assert entry["reason"] == "breakpoint", entry
                if machine.read("main", 0x2000, 16) == image[:16]:
                    assert machine.read("main", 0x2000, len(image)) == image, (profile, "SYS load differs")
                    machine.run(steps=1)
                    break
                machine.run(steps=1)
            else:
                raise AssertionError("starter SYS entry was not observed")
            start = settle()
            assert start == [152, 92] and machine.get("newvideo") == 0xC1, (profile, start)
            # Let the stick calibrate at the emulator's resting 128.
            advance(12)
            assert position() == start, (profile, "resting stick moved the square", position())
            trace.append({"event": "started", "position": start})

            # Held keys move the square; release stops it.
            send(b"hold", ord("D"))
            moved = advance(20)
            assert moved[0] > start[0] and moved[1] == start[1], (profile, "held D", moved)
            send(b"release")
            stopped = advance(4)
            assert advance(10) == stopped, (profile, "released key kept moving")
            send(b"hold", ord("W"))
            moved = advance(20)
            assert moved[1] < stopped[1] and moved[0] == stopped[0], (profile, "held W", moved)
            send(b"release")
            stopped = advance(4)
            assert advance(10) == stopped, (profile, "released W kept moving")
            trace.append({"event": "held-keys-move-and-release-stops", "position": stopped})

            # The calibrated stick moves it too, and stops at rest.
            send(b"paddle", 0, 20)
            moved = advance(20)
            assert moved[0] < stopped[0] and moved[1] == stopped[1], (profile, "stick left", moved)
            send(b"paddle", 0, 128)
            stopped = advance(4)
            assert advance(10) == stopped, (profile, "centred stick kept moving")
            trace.append({"event": "stick-moves-and-centres", "position": stopped})
            screenshot(machine, output / f"play-{profile}.png")

            send(b"key", ord("Q"))
            for _ in range(30):
                assert machine.run(frames=6, timeout=30)["reason"] == "cycles"
            assert machine.get("newvideo") == 1, (profile, "SHR not restored")
            irqs = machine.get("irqs")
            for _ in range(5):
                machine.run(frames=6, timeout=30)
            assert machine.get("irqs") == irqs, (profile, "IRQ continues after shutdown")
            trace.append({"event": "q-returns-to-prodos", "post_exit_irqs": irqs})
            evidence["runs"].append({"profile": profile, "machine": machine.metadata(), "trace": trace})
            print(f"starter native {profile}: held keys, stick, release stops and clean exit PASS", flush=True)
        except Exception:
            screenshot(machine, output / f"failure-{profile}.png")
            (output / f"failure-{profile}.json").write_text(json.dumps(
                {"trace": trace, "position": position(), "machine": machine.state()}, indent=2) + "\n")
            raise
        finally:
            machine.close()
    (output / "validation.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
