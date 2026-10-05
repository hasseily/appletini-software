#!/usr/bin/env python3
"""Build a PAL-default disk for a physical Phasor and real SSI-263 chips."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
FRAMEWORK = (HERE / "../../song_to_phasor").resolve()
DOOM = (HERE / "../../doom").resolve()


def build(score=None, ssi_effective_clock_hz=None):
    output = HERE / "build/physical"
    output.mkdir(parents=True, exist_ok=True)
    ca65 = os.environ.get("CA65", "ca65")
    ld65 = os.environ.get("LD65", "ld65")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(FRAMEWORK) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    command = [sys.executable, str(HERE / "prepare.py"),
               str(score or HERE.parent / "score.json"), str(output),
               "--profile", "physical-ssi263"]
    if ssi_effective_clock_hz is not None:
        command += ["--ssi-effective-clock-hz", str(ssi_effective_clock_hz)]
    subprocess.run(command, env=env, check=True)
    for name, source, extra in (
        ("demo", HERE / "demo.s", ["-D", "PHYSICAL_SSI=1", "-D", "DEFAULT_REGION=1"]),
        ("phasor", FRAMEWORK / "player/phasor.s", []),
        ("memory_reader", FRAMEWORK / "player/memory_reader.s", []),
    ):
        subprocess.run([ca65, "--cpu", "65C02", "-g", "-I",
                        str(FRAMEWORK / "player"), *extra, "-o",
                        str(output / f"{name}.o"), "-l",
                        str(output / f"{name}.lst"), str(source)], check=True)
    subprocess.run([ld65, "-C", str(HERE / "player.cfg"), "-o",
                    str(output / "SUN.SYSTEM"), "-Ln", str(output / "sun.lbl"),
                    "-m", str(output / "sun.map"),
                    *(str(output / f"{name}.o")
                      for name in ("demo", "phasor", "memory_reader"))], check=True)
    subprocess.run([sys.executable, str(DOOM / "tools/mkdisk.py"),
                    "-o", str(output / "RISING.SUN.hdv"), "-v", "RISING.SUN",
                    "-m", str(DOOM / "assets/ProDOS_2_4_3.po"),
                    str(output / "SUN.SYSTEM") + ",SYS,2000",
                    str(output / "SUN.NTSC") + ",BIN,3000",
                    str(output / "SUN.PAL") + ",BIN,3000"], check=True)
    # A small, deterministic bundle can be sent directly to a hardware tester.
    members = {
        "RISING.SUN.hdv": (output / "RISING.SUN.hdv").read_bytes(),
        "README.md": (HERE.parent / "PHYSICAL_PHASOR.md").read_bytes(),
        "compile.json": (output / "compile.json").read_bytes(),
    }
    members["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in members.items()).encode()
    archive = output / "RISING.SUN-Physical-SSI263.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, data)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for name, data in members.items():
            assert bundle.read(name) == data
    print(f"Physical hardware test bundle: {archive}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score", type=Path, default=HERE.parent / "score.json")
    parser.add_argument("--ssi-effective-clock-hz", type=float,
                        help="measured effective SSI clock; overrides both regional defaults")
    args = parser.parse_args()
    build(args.score, args.ssi_effective_clock_hz)
