#!/usr/bin/env python3
"""Build a bootable ProDOS Appletini Invasion SmartPort image."""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
from pathlib import Path


SOFTWARE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_APPLETINI_ROOT = SOFTWARE_ROOT.parent / "appletini-one"
APPLETINI_ROOT = Path(
    os.environ.get("APPLETINI_ROOT", str(DEFAULT_APPLETINI_ROOT))
).expanduser().resolve()
DEFAULT_MASTER = APPLETINI_ROOT / "software/ProDOS_2_4_3.po"
DEFAULT_JAR = (Path.home() /
               "Documents/accurapple/accurapple/speaker/AppleCommander-1.3.5.13-ac.jar")
A13C_HEADER = struct.Struct("<4sBBBBHHHH")
A13C_BANK_IMAGE_SIZE = 32 * 1024
A13C_BANK_COUNT = 6
A13C_PREFIX_SIZE = 4096


def applecommander(jar: Path, *arguments: str, data: bytes | None = None,
                   check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ("java", "-jar", str(jar), *arguments), input=data,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", type=Path, required=True)
    parser.add_argument("--parallax", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--applecommander", type=Path,
                        default=Path(os.environ.get("APPLECOMMANDER_JAR", DEFAULT_JAR)))
    args = parser.parse_args()

    for path, description in ((args.system, "system program"),
                              (args.parallax, "A13C parallax asset"),
                              (args.master, "DOS master"),
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
    # then seed ProDOS itself and the direct-boot game system file.
    result = applecommander(jar, "-pro800", image, "A13INVASION")
    if result.returncode:
        raise SystemExit(result.stdout.decode(errors="replace"))
    boot_blocks = args.master.read_bytes()[:1024]
    with args.output.open("r+b") as block_image:
        block_image.write(boot_blocks)
    prodos = applecommander(jar, "-g", str(args.master), "PRODOS").stdout
    if not prodos:
        raise SystemExit(f"could not export PRODOS from {args.master}")
    result = applecommander(jar, "-p", image, "PRODOS", "SYS", "$0000", data=prodos)
    if result.returncode:
        raise SystemExit(result.stdout.decode(errors="replace"))
    system_payload = args.system.read_bytes()
    if len(system_payload) <= 0x4000 \
            or system_payload[:3] != bytes((0x4C, 0x00, 0x60)) \
            or any(system_payload[3:0x4000]):
        raise SystemExit(
            "system program is not a JMP $6000 plus padded $6000 payload"
        )
    if 0x2000 + len(system_payload) > 0xB000:
        raise SystemExit("system program overlaps the $B000 software stack")
    result = applecommander(jar, "-p", image, "INVASION.SYSTEM", "SYS", "$2000",
                            data=system_payload)
    if result.returncode:
        raise SystemExit(result.stdout.decode(errors="replace"))

    parallax_payload = args.parallax.read_bytes()
    expected_parallax_size = A13C_PREFIX_SIZE + (
        A13C_BANK_COUNT * A13C_BANK_IMAGE_SIZE
    )
    if len(parallax_payload) != expected_parallax_size:
        raise SystemExit(
            f"A13C asset is {len(parallax_payload)} bytes; "
            f"expected {expected_parallax_size}"
        )
    header = A13C_HEADER.unpack_from(parallax_payload)
    if header != (b"A13C", 1, 3, 80, 6, 560, 384, 16, 4096):
        raise SystemExit(f"invalid A13C header: {header!r}")
    result = applecommander(jar, "-p", image, "PARALLAX", "BIN", "$2000",
                            data=parallax_payload)
    if result.returncode:
        raise SystemExit(result.stdout.decode(errors="replace"))

    listing = applecommander(jar, "-ll", image).stdout.decode(errors="replace")
    if ("INVASION.SYSTEM" not in listing or "PARALLAX" not in listing
            or "A=$2000" not in listing):
        raise SystemExit(f"disk verification failed:\n{listing}")
    for obsolete in ("BASIC.SYSTEM", "STARTUP", "INVASION BIN"):
        if obsolete in listing:
            raise SystemExit(f"unexpected BASIC launcher file {obsolete}:\n{listing}")
    installed = applecommander(jar, "-g", image, "INVASION.SYSTEM").stdout
    if installed != system_payload:
        raise SystemExit("INVASION.SYSTEM verification failed")
    installed_parallax = applecommander(jar, "-g", image, "PARALLAX").stdout
    if installed_parallax != parallax_payload:
        raise SystemExit("PARALLAX verification failed")
    if args.output.read_bytes()[:1024] != boot_blocks:
        raise SystemExit("ProDOS boot-block copy failed")
    if args.output.stat().st_size != 800 * 1024:
        raise SystemExit("SmartPort image is not exactly 800 KB")
    print(f"built {args.output} ({args.output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
