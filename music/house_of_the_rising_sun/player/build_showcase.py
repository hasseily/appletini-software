#!/usr/bin/env python3
"""Build the Appletini demo-disk SYS player and both streams without make."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
FRAMEWORK = (HERE / "../../song_to_phasor").resolve()


def build():
    output = HERE / "build/showcase"
    output.mkdir(parents=True, exist_ok=True)
    ca65 = os.environ.get("CA65", "ca65")
    ld65 = os.environ.get("LD65", "ld65")
    subprocess.run([sys.executable, "arrangement.py"], cwd=HERE.parent, check=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(FRAMEWORK) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    subprocess.run([sys.executable, str(HERE / "prepare.py"),
                    str(HERE.parent / "score.json"), str(HERE / "build")],
                   env=env, check=True)
    for name, source, extra in (
        ("demo", HERE / "demo.s", ["-D", "SHOWCASE=1"]),
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
    print(f"Showcase player: {output / 'SUN.SYSTEM'}")


if __name__ == "__main__":
    build()
