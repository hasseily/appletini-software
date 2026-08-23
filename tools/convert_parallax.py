#!/usr/bin/env python3
"""Convert canonical RGBA parallax layers into a sparse DHGR XOR asset."""

from __future__ import annotations

import argparse
import binascii
import hashlib
import struct
import zlib
from pathlib import Path


WIDTH = 560
HEIGHT = 384
ROW_BYTES = WIDTH // 7
HEADER_SIZE = 16
CHUNK_HEADER_SIZE = 2
ROW_DIRECTORY_SIZE = HEIGHT * 2
MAX_FILE_SIZE = 12 * 1024
MAGIC = b"A13S"
VERSION = 1
SPEED_DENOMINATOR = 20

LAYERS = (
    ("layer1_deep_space.png", 0, 5, 8),
    ("layer2_nebula.png", 1, 12, 5),
    ("layer3_asteroids.png", 2, 28, 4),
)

PALETTE = (
    (0x00, 0x00, 0x00),
    (0x8A, 0x21, 0x40),
    (0x3C, 0x22, 0xA5),
    (0xC8, 0x47, 0xE4),
    (0x07, 0x65, 0x3E),
    (0x7B, 0x7E, 0x80),
    (0x30, 0x8E, 0xF3),
    (0xB9, 0xA9, 0xFD),
    (0x62, 0x4A, 0x00),
    (0xF2, 0x5E, 0x00),
    (0x7B, 0x7E, 0x80),
    (0xFF, 0xA1, 0xB8),
    (0x35, 0xC5, 0x45),
    (0xF2, 0xF3, 0xB4),
    (0x8B, 0xEE, 0xBF),
    (0xFF, 0xFF, 0xFF),
)

# The two real-NTSC greys have identical source RGB values. The supplied
# generator documents that it emits palette index 5, so retain the first index.
RGB_TO_INDEX: dict[tuple[int, int, int], int] = {}
for palette_index, palette_rgb in enumerate(PALETTE):
    RGB_TO_INDEX.setdefault(palette_rgb, palette_index)


class AssetError(ValueError):
    """A source asset does not satisfy the fixed runtime format."""


def paeth(left: int, above: int, upper_left: int) -> int:
    prediction = left + above - upper_left
    left_distance = abs(prediction - left)
    above_distance = abs(prediction - above)
    upper_left_distance = abs(prediction - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def read_rgba_png(path: Path) -> list[bytes]:
    payload = path.read_bytes()
    if payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssetError(f"{path}: not a PNG file")

    position = 8
    ihdr: bytes | None = None
    compressed = bytearray()
    saw_iend = False
    while position < len(payload):
        if position + 12 > len(payload):
            raise AssetError(f"{path}: truncated PNG chunk")
        length = struct.unpack_from(">I", payload, position)[0]
        chunk_end = position + 12 + length
        if chunk_end > len(payload):
            raise AssetError(f"{path}: truncated PNG chunk data")
        chunk_type = payload[position + 4:position + 8]
        chunk_data = payload[position + 8:position + 8 + length]
        expected_crc = struct.unpack_from(">I", payload, position + 8 + length)[0]
        actual_crc = binascii.crc32(chunk_type)
        actual_crc = binascii.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise AssetError(f"{path}: bad {chunk_type!r} CRC")
        position = chunk_end

        if chunk_type == b"IHDR":
            if ihdr is not None:
                raise AssetError(f"{path}: duplicate IHDR")
            ihdr = chunk_data
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            saw_iend = True
            break

    if position != len(payload):
        raise AssetError(f"{path}: trailing data after IEND")
    if ihdr is None or len(ihdr) != 13 or not compressed or not saw_iend:
        raise AssetError(f"{path}: incomplete PNG")

    width, height, depth, color_type, compression, filtering, interlace = (
        struct.unpack(">IIBBBBB", ihdr)
    )
    if (width, height) != (WIDTH, HEIGHT):
        raise AssetError(
            f"{path}: expected {WIDTH}x{HEIGHT}, got {width}x{height}"
        )
    if (depth, color_type, compression, filtering, interlace) != (8, 6, 0, 0, 0):
        raise AssetError(
            f"{path}: expected non-interlaced RGBA8 PNG, got "
            f"depth={depth} type={color_type} compression={compression} "
            f"filter={filtering} interlace={interlace}"
        )

    try:
        filtered = zlib.decompress(compressed)
    except zlib.error as error:
        raise AssetError(f"{path}: invalid IDAT stream: {error}") from error
    stride = WIDTH * 4
    expected_size = HEIGHT * (stride + 1)
    if len(filtered) != expected_size:
        raise AssetError(
            f"{path}: expected {expected_size} decompressed bytes, "
            f"got {len(filtered)}"
        )

    rows: list[bytes] = []
    previous = bytes(stride)
    source_offset = 0
    for row_number in range(HEIGHT):
        filter_type = filtered[source_offset]
        source_offset += 1
        scanline = bytearray(filtered[source_offset:source_offset + stride])
        source_offset += stride
        if filter_type > 4:
            raise AssetError(
                f"{path}: unsupported PNG filter {filter_type} on row {row_number}"
            )
        for index in range(stride):
            left = scanline[index - 4] if index >= 4 else 0
            above = previous[index]
            upper_left = previous[index - 4] if index >= 4 else 0
            if filter_type == 1:
                scanline[index] = (scanline[index] + left) & 0xFF
            elif filter_type == 2:
                scanline[index] = (scanline[index] + above) & 0xFF
            elif filter_type == 3:
                scanline[index] = (
                    scanline[index] + ((left + above) >> 1)
                ) & 0xFF
            elif filter_type == 4:
                scanline[index] = (
                    scanline[index] + paeth(left, above, upper_left)
                ) & 0xFF
        previous = bytes(scanline)
        rows.append(previous)
    return rows


def pack_row(path: Path, row_number: int, rgba: bytes,
             deep_space: bool) -> tuple[bytes, bytes, bytes]:
    data = bytearray(ROW_BYTES)
    active = bytearray(ROW_BYTES)
    white = bytearray(ROW_BYTES)
    for x in range(WIDTH):
        pixel_offset = x * 4
        rgb = tuple(rgba[pixel_offset:pixel_offset + 3])
        alpha = rgba[pixel_offset + 3]
        if alpha not in (0, 255):
            raise AssetError(
                f"{path}: non-binary alpha {alpha} at ({x},{row_number})"
            )
        palette_index = RGB_TO_INDEX.get(rgb)
        if palette_index is None:
            raise AssetError(
                f"{path}: color {rgb} is not in the Apple II palette "
                f"at ({x},{row_number})"
            )
        if deep_space and alpha != 255:
            raise AssetError(
                f"{path}: deep-space layer is not opaque at ({x},{row_number})"
            )

        # DHGR's four-dot color pattern is the palette nibble rotated right.
        pattern = ((palette_index >> 1) | ((palette_index & 1) << 3)) & 0x0F
        byte_index, dot = divmod(x, 7)
        if alpha:
            active[byte_index] = 1
            if palette_index == 15:
                white[byte_index] = 1
            if (pattern >> (x & 3)) & 1:
                data[byte_index] |= 1 << dot
    return bytes(data), bytes(active), bytes(white)


def encode_row(data: bytes, active: bytes, white: bytes,
               row_number: int, layer_index: int, divisor: int) -> bytes:
    del active
    eligible = [group for group, value in enumerate(data) if value]
    quota = (len(eligible) + divisor - 1) // divisor

    def selection_rank(group: int) -> int:
        # Avalanche the two-dimensional byte coordinate before ranking it.
        # The old affine modulus selected one diagonal lattice per layer,
        # which showed up as moving black bands across the source artwork.
        value = ((row_number * ROW_BYTES + group)
                 ^ ((layer_index + 1) * 0x9E3779B9)) & 0xFFFFFFFF
        value ^= value >> 16
        value = (value * 0x7FEB352D) & 0xFFFFFFFF
        value ^= value >> 15
        value = (value * 0x846CA68B) & 0xFFFFFFFF
        value ^= value >> 16
        return value

    selected = set(sorted(eligible, key=selection_rank)[:quota])
    if layer_index == 0:
        selected.update(group for group in eligible if white[group])

    pairs = bytearray()
    for group in sorted(selected):
        if data[group]:
            pairs.extend((group, data[group]))
    count = len(pairs) // 2
    if count > ROW_BYTES:
        raise AssetError(f"row {row_number}: {count} entries exceeds {ROW_BYTES}")
    return bytes((count,)) + bytes(pairs)


def encode_layer(path: Path, layer_index: int, speed_numerator: int,
                 divisor: int) -> tuple[bytes, int]:
    rows = read_rgba_png(path)
    records = [
        encode_row(*pack_row(path, row_number, row, layer_index == 0),
                   row_number, layer_index, divisor)
        for row_number, row in enumerate(rows)
    ]

    record_offset = CHUNK_HEADER_SIZE + ROW_DIRECTORY_SIZE
    offsets = bytearray()
    for record in records:
        if record_offset > 0xFFFF:
            raise AssetError(f"{path}: row directory offset overflow")
        offsets.extend(struct.pack("<H", record_offset))
        record_offset += len(record)

    chunk = bytes((speed_numerator, SPEED_DENOMINATOR)) \
        + bytes(offsets) + b"".join(records)
    entry_count = sum(record[0] for record in records)
    print(
        f"layer {layer_index + 1}: {path.name}: {len(chunk)} bytes, "
        f"{entry_count} XOR entries"
    )
    return chunk, entry_count


def validate_output(output: bytes) -> None:
    if len(output) >= MAX_FILE_SIZE:
        raise AssetError(
            f"encoded asset is {len(output)} bytes; must be below {MAX_FILE_SIZE}"
        )
    magic, version, layer_count, row_bytes, reserved, height, *chunk_offsets = (
        struct.unpack_from("<4sBBBBH3H", output)
    )
    if (magic, version, layer_count, row_bytes, reserved, height) != (
            MAGIC, VERSION, len(LAYERS), ROW_BYTES, 0, HEIGHT):
        raise AssertionError("global header failed validation")
    if list(chunk_offsets) != sorted(chunk_offsets):
        raise AssertionError("chunk offsets are not ordered")

    for layer_index, chunk_offset in enumerate(chunk_offsets):
        chunk_end = (chunk_offsets[layer_index + 1]
                     if layer_index + 1 < len(chunk_offsets) else len(output))
        if not (HEADER_SIZE <= chunk_offset < chunk_end <= len(output)):
            raise AssertionError("chunk extent is invalid")
        numerator, denominator = output[chunk_offset:chunk_offset + 2]
        if (numerator, denominator) != (LAYERS[layer_index][2],
                                       SPEED_DENOMINATOR):
            raise AssertionError("chunk speed failed validation")
        row_offsets = struct.unpack_from(f"<{HEIGHT}H", output,
                                         chunk_offset + CHUNK_HEADER_SIZE)
        expected_row = CHUNK_HEADER_SIZE + ROW_DIRECTORY_SIZE
        for row_offset in row_offsets:
            if row_offset != expected_row:
                raise AssertionError("row offset failed validation")
            position = chunk_offset + row_offset
            count = output[position]
            if count > ROW_BYTES:
                raise AssertionError("row entry count exceeds row width")
            position += 1
            previous_x = -1
            for _ in range(count):
                x, data = output[position:position + 2]
                if x <= previous_x or x >= ROW_BYTES or not 0 < data < 0x80:
                    raise AssertionError("invalid sparse XOR entry")
                previous_x = x
                position += 2
            expected_row += 1 + count * 2
        if chunk_offset + expected_row != chunk_end:
            raise AssertionError("chunk length failed validation")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    chunks = []
    for filename, layer_index, speed_numerator, divisor in LAYERS:
        path = args.assets / filename
        if not path.is_file():
            raise SystemExit(f"missing parallax source asset: {path}")
        try:
            chunk, _ = encode_layer(path, layer_index, speed_numerator, divisor)
            chunks.append(chunk)
        except (AssetError, OSError) as error:
            raise SystemExit(error) from error

    chunk_offsets = []
    next_offset = HEADER_SIZE
    for chunk in chunks:
        if next_offset > 0xFFFF:
            raise AssetError("chunk offset exceeds the 16-bit file format")
        chunk_offsets.append(next_offset)
        next_offset += len(chunk)
    header = struct.pack(
        "<4sBBBBH3H",
        MAGIC,
        VERSION,
        len(LAYERS),
        ROW_BYTES,
        0,
        HEIGHT,
        *chunk_offsets,
    )
    output = header + b"".join(chunks)
    try:
        validate_output(output)
    except AssetError as error:
        raise SystemExit(error) from error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    print(
        f"built {args.output} ({len(output)} bytes, "
        f"sha256 {hashlib.sha256(output).hexdigest()})"
    )


if __name__ == "__main__":
    main()
