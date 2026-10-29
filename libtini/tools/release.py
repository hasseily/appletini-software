#!/usr/bin/env python3
"""Create deterministic source/local-release archives and verify isolated builds."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import boot_roms

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ("assets", "cfg", "design", "docs", "examples", "games", "include", "src", "tests", "tools", "services")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files():
    selected = [ROOT / name for name in (".gitignore", "AGENTS.md", "LICENSE", "README.md")]
    for name in boot_roms.FILES:
        path = ROOT / "build-inputs/native-roms" / name
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise SystemExit("Source archive cannot contain links: " + str(path))
        if not path.is_file():
            raise SystemExit("Missing bundled boot input: " + str(path))
        selected.append(path)
    for name in DIRECTORIES:
        for path in (ROOT / name).rglob("*"):
            if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
                continue
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise SystemExit("Source archive cannot contain links: " + str(path))
            if path.is_file():
                selected.append(path)
    return sorted(selected)


def archive(destination, entries):
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for name, data in sorted(entries):
            item = zipfile.ZipInfo(name, (2026, 10, 20, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            output.writestr(item, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc65-home")
    parser.add_argument("--verify-isolation", action="store_true")
    args = parser.parse_args()
    for directory in (ROOT / "build", ROOT / "build/private"):
        manifest = json.loads((directory / "manifest.json").read_text())
        for name, expected in manifest["inputs"].items():
            path = ROOT / name
            if not path.is_file() or digest(path) != expected:
                raise SystemExit("Stale build input; rebuild before release: " + name)
        for name, expected in manifest["outputs"].items():
            path = ROOT / name
            if not path.is_file() or digest(path) != expected["sha256"] or path.stat().st_size != expected["bytes"]:
                raise SystemExit("Missing/changed build output: " + name)
    selected = source_files()
    evidence = {"source_files": len(selected), "source_sha256": {
        path.relative_to(ROOT).as_posix(): digest(path) for path in selected},
        "automated_checks_are_board_evidence": False, "firmware_baseline": "F1.3.2 core; F1.3.3 optional networking",
        "board_report": "https://github.com/hasseily/appletini-one/blob/F1.3.3/README_RSA_STRESS_CHECKPOINT.md"}
    prior_isolation = ROOT / "build/selfcontained-check.json"
    if not args.verify_isolation and prior_isolation.exists():
        previous = json.loads(prior_isolation.read_text())
        if previous.get("source_sha256") == evidence["source_sha256"]:
            evidence["isolated_builds"] = previous.get("isolated_builds", {})
            if "source_export" in previous: evidence["source_export"] = previous["source_export"]
    if args.verify_isolation:
        isolated = ROOT / "build/selfcontained-release"
        attempt = 1
        while isolated.exists():
            attempt += 1
            isolated = ROOT / ("build/selfcontained-release-" + str(attempt))
        isolated.mkdir(parents=True)
        evidence["source_export"] = isolated.relative_to(ROOT).as_posix()
        for source in selected:
            target = isolated / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        lock = json.loads((ROOT / "tools/prodos-input.json").read_text())
        installed = isolated / lock["path"]
        installed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / lock["path"], installed)
        comparisons = {}
        for private in (False, True):
            command = [sys.executable, "tools/build.py", "--test-target"]
            if args.cc65_home:
                command += ["--cc65-home", args.cc65_home]
            directory = Path("build/private" if private else "build")
            if private:
                command += ["--private", "--build-dir", str(directory)]
            log = ROOT / "build" / ("isolation-private.log" if private else "isolation-cpu.log")
            with log.open("w") as output:
                subprocess.run(command, cwd=isolated, stdout=output, stderr=subprocess.STDOUT, check=True)
            manifest = json.loads((ROOT / directory / "manifest.json").read_text())
            other = json.loads((isolated / directory / "manifest.json").read_text())
            if manifest != other:
                raise SystemExit("Isolated build manifest differs: " + str(directory))
            for name, expected in manifest["outputs"].items():
                if digest(isolated / name) != expected["sha256"]:
                    raise SystemExit("Isolated output differs: " + name)
            comparisons[str(directory)] = {"identical_outputs": len(manifest["outputs"]),
                                           "manifest_sha256": digest(ROOT / directory / "manifest.json")}
        evidence["isolated_builds"] = comparisons
        (ROOT / "build/selfcontained-check.json").write_text(json.dumps(evidence, indent=2) + "\n")
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    archive(destination / "libtini-source.zip", [(path.relative_to(ROOT).as_posix(), path.read_bytes()) for path in selected])
    entries = [("source/" + path.relative_to(ROOT).as_posix(), path.read_bytes()) for path in selected]
    for directory, prefix in ((ROOT / "build", "cpu"), (ROOT / "build/private", "amem")):
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        entries.append((prefix + "/manifest.json", manifest_path.read_bytes()))
        for name in manifest["outputs"]:
            source = ROOT / name
            entries.append((prefix + "/" + source.name, source.read_bytes()))
    for name in ("native/validation.json", "graphics/validation.json", "audio/validation.json",
                 "audio_native/validation.json", "storage/validation.json", "amem/validation.json",
                 "net/validation.json", "private_fifo/validation.json", "starfall/arrival/validation.json",
                 "starter-check.json", "selfcontained-check.json",
                 "starfall/native-ui/validation.json", "starfall/native-ui-phasor/validation.json",
                 "checks/validation.json", "benchmark/results.json",
                 "benchmark/direct-results.json", "benchmark/cpu/build.json", "benchmark/private/build.json"):
        path = ROOT / "build" / name
        if path.exists():
            entries.append(("evidence/" + name, path.read_bytes()))
    for folder in ("native", "audio_native", "starfall/native-ui", "starfall/native-ui-phasor"):
        for path in sorted((ROOT / "build" / folder).glob("*.png")):
            entries.append(("previews/" + folder + "/" + path.name, path.read_bytes()))
    for path in sorted((ROOT / "build/checks").glob("*.log")):
        entries.append(("evidence/checks/" + path.name, path.read_bytes()))
    for variant in ("cpu", "private"):
        for name in ("benchmark.system", "benchmark.po", "benchmark.map", "benchmark.lbl"):
            path = ROOT / "build/benchmark" / variant / name
            if path.exists():
                entries.append(("benchmarks/" + variant + "/" + name, path.read_bytes()))
    entries.append(("LOCAL-INPUTS.txt", b"Local build package: boot disks contain the separately installed ProDOS 2.4.3.\n"
                    b"The source includes the enhanced //e and slot-7 boot ROMs with their notices.\n"
                    b"No FPGA/ARM firmware or host compiler binaries are included.\n"
                    b"Check ProDOS distribution terms before sharing disks. Source-only archive omits OS bytes.\n"
                    b"Read docs/reference/testing.html for scoped board, host and emulator evidence.\n"))
    archive(destination / "libtini-local-release.zip", entries)
    evidence["archives"] = {path.name: {"bytes": path.stat().st_size, "sha256": digest(path)}
                            for path in sorted(destination.glob("libtini-*.zip"))}
    (destination / "manifest.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence["archives"], indent=2))


if __name__ == "__main__":
    main()
