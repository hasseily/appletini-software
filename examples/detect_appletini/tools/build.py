#!/usr/bin/env python3
"""Assemble the standalone SmartPort GETDIB detection example."""
import os
from pathlib import Path
import shutil
import subprocess


PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    assembler = os.environ.get("ACME_EXE") or shutil.which("acme") or str(
        Path.home() / "tools" / "acme" / "acme.exe")
    output = PROJECT / "build" / "detect_appletini.bin"
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([assembler, "-f", "plain", "-o", str(output),
                    str(PROJECT / "detect_appletini.a65")], check=True)
    if not 0 < output.stat().st_size <= 0x100:
        raise RuntimeError("Detection example overlaps its $0900 DIB buffer")
    print(f"Built {output} ({output.stat().st_size} bytes at $0800)")


if __name__ == "__main__":
    main()
