#!/usr/bin/env python3
"""Wrap the $6000 game as a direct-boot ProDOS $2000 SYS file."""

from __future__ import annotations

import argparse
from pathlib import Path


SYSTEM_LOAD = 0x2000
GAME_LOAD = 0x6000
GAME_OFFSET = GAME_LOAD - SYSTEM_LOAD
SAFE_LIMIT = 0xB000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not args.program.is_file():
        raise SystemExit(f"missing game binary: {args.program}")
    program = args.program.read_bytes()
    if GAME_LOAD + len(program) > SAFE_LIMIT:
        raise SystemExit(
            f"game ends at ${GAME_LOAD + len(program) - 1:04X}, "
            f"overlapping the software-stack region at ${SAFE_LIMIT:04X}"
        )

    # ProDOS loads SYS files contiguously at their $2000 auxiliary address.
    # A three-byte entry jumps over the DHGR pages; padding positions the
    # already-$6000-linked game at exactly its run address. No relocation code
    # runs and the game may immediately clear main $2000-$5FFF for video.
    system = bytearray((0x4C, GAME_LOAD & 0xFF, GAME_LOAD >> 8))
    system.extend(bytes(GAME_OFFSET - len(system)))
    system.extend(program)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(system)
    print(
        f"built {args.output} ({len(system)} bytes; game "
        f"${GAME_LOAD:04X}-${GAME_LOAD + len(program) - 1:04X})"
    )


if __name__ == "__main__":
    main()
