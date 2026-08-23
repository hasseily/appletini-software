#!/usr/bin/env python3
"""Compile the eight RGBA player frames into one exact DHGR sprite bank."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from convert_parallax import (
    AssetError,
    DOT_MASK,
    RGB_TO_INDEX,
    VIDEO7_COLOR,
    read_rgba_png,
)


WIDTH = 56
HEIGHT = 64
GROUPS_PER_ROW = WIDTH // 7
BYTES_PER_GROUP = 2
ROW_SIZE = GROUPS_PER_ROW * BYTES_PER_GROUP
PHASE_COUNT = 4
FRAME_COUNT = 8
VARIANT_SIZE = HEIGHT * ROW_SIZE
BANK_SIZE = 32 * 1024
FRAMES = tuple(f"ship_f{index}.png" for index in range(FRAME_COUNT))
METADATA = "ship.json"


def validate_metadata(path: Path) -> None:
    try:
        metadata = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise AssetError(f"{path}: invalid ship metadata: {error}") from error

    expected_poses = {
        "neutral": [0, 1],
        "bank_left": [2, 3],
        "bank_right": [4, 5],
        "fire": [6, 7],
    }
    if metadata.get("frame_size") != [WIDTH, HEIGHT]:
        raise AssetError(f"{path}: expected frame_size [{WIDTH}, {HEIGHT}]")
    for pose, frames in expected_poses.items():
        if metadata.get(pose, {}).get("frames") != frames:
            raise AssetError(f"{path}: {pose} frames are not {frames}")


def pack_variant(path: Path, rows: list[bytes], group_phase: int) -> bytes:
    """Pack mask/data pairs for one origin group modulo four.

    A seven-dot DHGR group advances the global four-dot color phase by three.
    Keeping four origin-group variants therefore preserves every palette hue
    while the ship moves in native seven-dot increments.
    """
    origin_dot_phase = (group_phase * 7) & 3
    packed = bytearray()
    for row_number, rgba in enumerate(rows):
        data = bytearray(GROUPS_PER_ROW)
        opacity = bytearray(GROUPS_PER_ROW)
        for x in range(WIDTH):
            pixel_offset = x * 4
            rgb = tuple(rgba[pixel_offset:pixel_offset + 3])
            alpha = rgba[pixel_offset + 3]
            if alpha not in (0, 255):
                raise AssetError(
                    f"{path}: non-binary alpha {alpha} at ({x},{row_number})"
                )
            if not alpha:
                continue
            palette_index = RGB_TO_INDEX.get(rgb)
            if palette_index is None:
                raise AssetError(
                    f"{path}: color {rgb} is not in the Apple II palette "
                    f"at ({x},{row_number})"
                )
            pattern = (
                (palette_index >> 1) | ((palette_index & 1) << 3)
            ) & 0x0F
            group, dot = divmod(x, 7)
            opacity[group] |= 1 << dot
            if (pattern >> ((origin_dot_phase + x) & 3)) & 1:
                data[group] |= 1 << dot

        for group in range(GROUPS_PER_ROW):
            opaque = opacity[group]
            value = data[group]
            if value & ~opaque:
                raise AssetError(
                    f"{path}: row {row_number} group {group} sets a "
                    "transparent data bit"
                )
            packed.extend(((opaque ^ DOT_MASK) | VIDEO7_COLOR, value))

    if len(packed) != VARIANT_SIZE:
        raise AssetError(
            f"{path}: compiled variant is {len(packed)} bytes; "
            f"expected {VARIANT_SIZE}"
        )
    return bytes(packed)


def validate_variant(path: Path, packed: bytes) -> None:
    if len(packed) != VARIANT_SIZE:
        raise AssetError(f"{path}: invalid compiled variant size")
    for offset in range(0, len(packed), 2):
        keep = packed[offset]
        data = packed[offset + 1]
        if not keep & VIDEO7_COLOR or data & VIDEO7_COLOR:
            raise AssetError(f"{path}: invalid Video-7 selector encoding")
        opacity = (keep ^ DOT_MASK) & DOT_MASK
        if data & ~opacity:
            raise AssetError(f"{path}: data escapes its alpha mask")
        for background in range(128):
            actual = ((background | VIDEO7_COLOR) & keep) | data
            expected = (
                (background & (opacity ^ DOT_MASK)) | data | VIDEO7_COLOR
            )
            if actual != expected:
                raise AssetError(
                    f"{path}: mask/data ${keep:02X}/${data:02X} maps "
                    f"background ${background:02X} to ${actual:02X}; "
                    f"expected ${expected:02X}"
                )


def build_ship_bank(assets: Path) -> bytes:
    metadata_path = assets / METADATA
    if not metadata_path.is_file():
        raise AssetError(f"missing ship metadata: {metadata_path}")
    validate_metadata(metadata_path)

    output = bytearray()
    for frame_index, filename in enumerate(FRAMES):
        path = assets / filename
        if not path.is_file():
            raise AssetError(f"missing ship frame: {path}")
        rows = read_rgba_png(path, WIDTH, HEIGHT)
        opaque_pixels = sum(
            row[pixel + 3] == 255
            for row in rows
            for pixel in range(0, len(row), 4)
        )
        for group_phase in range(PHASE_COUNT):
            variant = pack_variant(path, rows, group_phase)
            validate_variant(path, variant)
            output.extend(variant)
        print(f"ship frame {frame_index}: {path.name}: {opaque_pixels} opaque pixels")

    if len(output) != BANK_SIZE:
        raise AssetError(
            f"compiled ship bank is {len(output)} bytes; expected {BANK_SIZE}"
        )
    return bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        output = build_ship_bank(args.assets)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(output)
    except (AssetError, OSError) as error:
        raise SystemExit(error) from error

    print(
        f"built {args.output} ({len(output)} bytes, "
        f"sha256 {hashlib.sha256(output).hexdigest()})"
    )


if __name__ == "__main__":
    main()
