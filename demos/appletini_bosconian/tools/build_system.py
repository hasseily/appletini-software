#!/usr/bin/env python3
"""Copy the linked $2000 program to build/BOSCO.SYSTEM after a few checks.

The program is linked at $2000 by bosconian.cfg and crt0's STARTUP segment
is its first byte, so the linker output already is the ProDOS SYS file.
This script only checks that the image looks like code that starts at
$2000 and that it does not reach the software stack at $BB00.
"""

from __future__ import annotations

import argparse
from pathlib import Path


LOAD_ADDRESS = 0x2000
SAFE_LIMIT = 0xBB00
# opcodes a startup routine may plausibly begin with
START_OPCODES = {
    0x4C: "JMP", 0x78: "SEI", 0xD8: "CLD", 0x20: "JSR",
    0xA2: "LDX #", 0xA9: "LDA #", 0xA0: "LDY #", 0xEA: "NOP",
    0x8D: "STA abs", 0x9C: "STZ abs",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not args.program.is_file():
        raise SystemExit(f"missing program: {args.program}")
    program = args.program.read_bytes()
    if len(program) < 16:
        raise SystemExit(f"program is only {len(program)} bytes")
    first = program[0]
    if first not in START_OPCODES:
        raise SystemExit(
            f"program does not start with code at ${LOAD_ADDRESS:04X}: "
            f"first byte is ${first:02X}"
        )
    end = LOAD_ADDRESS + len(program)
    if end > SAFE_LIMIT:
        raise SystemExit(
            f"program ends at ${end - 1:04X}, past the ${SAFE_LIMIT:04X} "
            "software-stack limit"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(program)
    print(
        f"built {args.output} ({len(program)} bytes; "
        f"${LOAD_ADDRESS:04X}-${end - 1:04X}, starts with {START_OPCODES[first]})"
    )


if __name__ == "__main__":
    main()
