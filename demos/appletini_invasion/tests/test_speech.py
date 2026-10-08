#!/usr/bin/env python3
"""Build and run Invasion's real 65C02 speech scheduler with cl65 + sim65."""

import os
from pathlib import Path
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main():
    prefix = os.environ.get("CC65_PREFIX", "")
    with tempfile.TemporaryDirectory(prefix="invasion-speech-") as directory:
        temporary = Path(directory)
        obj = temporary / "speech_test.o"
        binary = temporary / "speech_test"
        subprocess.run(
            [prefix + "cl65", "-t", "sim65c02", "--cpu", "65c02",
             "--standard", "c99", "-Oirs", "-I", str(ROOT), "-c", "-o",
             str(obj), str(HERE / "speech_test.c")], check=True,
        )
        subprocess.run(
            [prefix + "cl65", "-t", "sim65c02", "-C",
             str(HERE / "speech_test.cfg"), "-o", str(binary), str(obj)],
            check=True,
        )
        subprocess.run(
            [prefix + "sim65", "-x", "5000000", str(binary)], check=True,
        )


if __name__ == "__main__":
    main()
