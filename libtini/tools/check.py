#!/usr/bin/env python3
"""Build both SDK variants and run focused host/actual-target release checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc65-home", required=True)
    parser.add_argument("--cc", required=True)
    parser.add_argument("--rom-boot", action="store_true",
                        help="also use bundled build-inputs/native-roms for real ProDOS boots")
    parser.add_argument("--only", help="rerun comma-separated named checks, preserving other recorded results")
    args = parser.parse_args()
    common = ["--cc65-home", args.cc65_home]
    compiler = ["--cc", args.cc]
    commands = [
        ("build-cpu", ["tools/build.py", *common, "--test-target"]),
        ("build-private", ["tools/build.py", *common, "--test-target", "--private", "--build-dir", "build/private"]),
        ("host-assets", ["-m", "unittest", "discover", "-s", "tests", "-p", "test_graphics_tools.py", "-v"]),
        ("host-speech", ["-m", "unittest", "discover", "-s", "tests", "-p", "test_speech.py", "-v"]),
        ("host-music", ["-m", "unittest", "discover", "-s", "tests", "-p", "test_music.py", "-v"]),
        ("host-starfall-assets", ["-m", "unittest", "discover", "-s", "tests", "-p", "test_starfall_assets.py", "-v"]),
        ("host-starfall", ["tests/test_starfall.py", *compiler]),
        ("host-input", ["tests/test_input.py", *compiler]),
        ("cpu-scene", ["tests/scene_validate.py", *common]),
        ("host-volumes", ["-m", "unittest", "discover", "-s", "tests", "-p", "test_disk_release.py", "-v"]),
        ("cpu-foundation", ["tools/test.py", "--no-build"]),
        ("native-foundation", ["tests/native_validate.py", *compiler]),
        ("native-graphics", ["tests/graphics_validate.py", *common, *compiler]),
        ("cpu-audio", ["tests/audio_validate.py"]),
        ("target-storage", ["tests/storage_validate.py", *common, *compiler]),
        ("target-net", ["tests/net_validate.py", *common]),
        ("target-private-fifo", ["tests/private_fifo_validate.py", *common]),
        ("target-amem", ["tests/amem_validate.py", *common]),
        ("native-benchmarks-direct", ["tools/benchmark.py", *common, *compiler, "--private", "--direct-launch",
                                      "--output", "build/benchmark/direct-results.json"]),
    ]
    if args.rom_boot:
        commands += [("native-benchmarks-boot", ["tools/benchmark.py", *common, *compiler, "--private",
                                                "--repeat", "2",
                                                "--output", "build/benchmark/results.json"]),
                     ("boot-audio", ["tests/audio_native_validate.py", *compiler])]
        commands += [("boot-starfall-arrival", ["tests/starfall_arrival_validate.py"]),
                     ("boot-starter", ["tests/starter_native_validate.py", *compiler]),
                     ("boot-starfall", ["tests/starfall_native_validate.py", *compiler]),
                     ("boot-starfall-phasor", ["tests/starfall_native_validate.py", *compiler, "--phasor"])]
    output = ROOT / "build/checks"
    output.mkdir(parents=True, exist_ok=True)
    # Avoid duplicate Windows PATH/Path keys in native compiler child processes.
    environment = {key: value for key, value in os.environ.items() if key.upper() != "PATH"}
    environment["PATH"] = os.environ.get("PATH", "")
    environment["CC65_HOME"] = str(Path(args.cc65_home).resolve())
    evidence = {"board_evidence": False, "real_prodos_boots": args.rom_boot, "checks": []}
    if args.only:
        selected = set(args.only.split(","))
        unknown = selected - {name for name, _ in commands}
        if unknown: raise SystemExit("Unknown check names: " + ", ".join(sorted(unknown)))
        commands = [(name, command) for name, command in commands if name in selected]
        previous = output / "validation.json"
        if previous.exists():
            evidence["checks"] = [item for item in json.loads(previous.read_text())["checks"]
                                  if item["name"] not in selected]
    for name, command in commands:
        log = output / (name + ".log")
        start = time.monotonic()
        with log.open("w") as stream:
            result = subprocess.run([sys.executable, *command], cwd=ROOT, env=environment,
                                    stdout=stream, stderr=subprocess.STDOUT)
        evidence["checks"].append({"name": name, "command": [sys.executable, *command],
                                    "exit_code": result.returncode, "seconds": round(time.monotonic() - start, 3),
                                    "log": log.relative_to(ROOT).as_posix()})
        (output / "validation.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(name + ": " + ("PASS" if result.returncode == 0 else "FAIL") + " (" + str(log.relative_to(ROOT)) + ")", flush=True)
        if result.returncode:
            print(log.read_text()[-6000:])
            return result.returncode
    evidence["build_manifests"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in (ROOT / "build/manifest.json", ROOT / "build/private/manifest.json")}
    (output / "validation.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
