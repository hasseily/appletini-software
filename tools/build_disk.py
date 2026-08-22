#!/usr/bin/env python3
"""Build a bootable ProDOS Appletini Invasion SmartPort image."""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MASTER = ROOT.parent / "appletini-one/software/ProDOS_2_4_3.po"
DEFAULT_JAR = (Path.home() /
               "Documents/accurapple/accurapple/speaker/AppleCommander-1.3.5.13-ac.jar")


def applesoft_hello() -> bytes:
    # 10 PRINT CHR$(4);"BRUN INVASION"
    body = bytes((0xBA, 0xE7)) + b"(4);\"BRUN INVASION\"" + b"\x00"
    start = 0x0801
    next_address = start + 4 + len(body)
    return struct.pack("<HH", next_address, 10) + body + b"\x00\x00"


def applecommander(jar: Path, *arguments: str, data: bytes | None = None,
                   check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ("java", "-jar", str(jar), *arguments), input=data,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--applecommander", type=Path,
                        default=Path(os.environ.get("APPLECOMMANDER_JAR", DEFAULT_JAR)))
    args = parser.parse_args()

    for path, description in ((args.program, "program"), (args.master, "DOS master"),
                              (args.applecommander, "AppleCommander")):
        if not path.is_file():
            raise SystemExit(f"missing {description}: {path}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        args.output.unlink()
    image = str(args.output)
    jar = args.applecommander

    # A 140K ProDOS image is intentionally classified as a 5.25-inch disk by
    # GSSquared. Create an 800K block volume so slot 7 takes the SmartPort path,
    # then seed only the two system files from the canonical local image.
    result = applecommander(jar, "-pro800", image, "A13INVASION")
    if result.returncode:
        raise SystemExit(result.stdout.decode(errors="replace"))
    boot_blocks = args.master.read_bytes()[:1024]
    with args.output.open("r+b") as block_image:
        block_image.write(boot_blocks)
    for name in ("PRODOS", "BASIC.SYSTEM"):
        payload = applecommander(jar, "-g", str(args.master), name).stdout
        if not payload:
            raise SystemExit(f"could not export {name} from {args.master}")
        result = applecommander(jar, "-p", image, name, "SYS", "$0000", data=payload)
        if result.returncode:
            raise SystemExit(result.stdout.decode(errors="replace"))

    result = applecommander(jar, "-p", image, "STARTUP", "BAS", "$0801",
                            data=applesoft_hello())
    if result.returncode:
        raise SystemExit(result.stdout.decode(errors="replace"))
    result = applecommander(jar, "-p", image, "INVASION", "BIN", "$6000",
                            data=args.program.read_bytes())
    if result.returncode:
        raise SystemExit(result.stdout.decode(errors="replace"))

    listing = applecommander(jar, "-ls", image).stdout.decode(errors="replace")
    if "INVASION" not in listing or "STARTUP" not in listing:
        raise SystemExit(f"disk verification failed:\n{listing}")
    if args.output.read_bytes()[:1024] != boot_blocks:
        raise SystemExit("ProDOS boot-block copy failed")
    if args.output.stat().st_size != 800 * 1024:
        raise SystemExit("SmartPort image is not exactly 800 KB")
    print(f"built {args.output} ({args.output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
