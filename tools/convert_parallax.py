#!/usr/bin/env python3
"""Compile canonical RGBA parallax layers into exact DHGR row routines."""

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
HEADER = struct.Struct("<4sBBBBHHHH")
DIRECTORY_ENTRY = struct.Struct("<BH")
HEADER_SIZE = HEADER.size
DIRECTORY_OFFSET = HEADER_SIZE
BANK_IMAGES_OFFSET = 4096
BANK_IMAGE_SIZE = 32 * 1024
BANK_LOAD_ADDRESS = 0x2000
BANK_LIMIT_ADDRESS = BANK_LOAD_ADDRESS + BANK_IMAGE_SIZE
BANK_COUNT = 5
MAGIC = b"A13C"
VERSION = 1

ZP_AUX_BASE = 0xA0
ZP_MAIN_BASE = 0xC8
VIDEO7_COLOR = 0x80
DOT_MASK = 0x7F

OP_LDA_IMMEDIATE = 0xA9
OP_STA_ZP = 0x85
OP_TRB_ZP = 0x14
OP_TSB_ZP = 0x04
OP_LDA_ZP = 0xA5
OP_AND_IMMEDIATE = 0x29
OP_ORA_IMMEDIATE = 0x09
OP_RTS = 0x60

LAYERS = (
    "layer1_deep_space.png",
    "layer2_nebula.png",
    "layer3_asteroids.png",
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
             deep_space: bool) -> tuple[bytes, bytes]:
    data = bytearray(ROW_BYTES)
    opacity = bytearray(ROW_BYTES)
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
            opacity[byte_index] |= 1 << dot
            if (pattern >> (x & 3)) & 1:
                data[byte_index] |= 1 << dot
    return bytes(data), bytes(opacity)


def group_zp_address(group: int) -> int:
    if not 0 <= group < ROW_BYTES:
        raise AssetError(f"DHGR group {group} is outside the compiled row")
    if group & 1:
        return ZP_MAIN_BASE + (group >> 1)
    return ZP_AUX_BASE + (group >> 1)


def emit_grouped(code: bytearray, load_value: int, opcode: int,
                 addresses: list[int]) -> None:
    code.extend((OP_LDA_IMMEDIATE, load_value))
    for address in addresses:
        code.extend((opcode, address))


def compile_deep_row(data: bytes) -> bytes:
    groups: dict[int, list[int]] = {}
    for group, value in enumerate(data):
        groups.setdefault(value | VIDEO7_COLOR, []).append(
            group_zp_address(group)
        )

    code = bytearray()
    for value in sorted(groups):
        emit_grouped(code, value, OP_STA_ZP, groups[value])
    code.append(OP_RTS)
    return bytes(code)


def compile_overlay_row(data: bytes, opacity: bytes) -> bytes:
    full: dict[int, list[int]] = {}
    clear: dict[int, list[int]] = {}
    set_bits: dict[int, list[int]] = {}
    merge: list[tuple[int, int, int]] = []

    for group, (value, opaque) in enumerate(zip(data, opacity)):
        address = group_zp_address(group)
        if opaque == 0:
            continue
        if opaque == DOT_MASK:
            full.setdefault(value | VIDEO7_COLOR, []).append(address)
        elif value == 0:
            clear.setdefault(opaque, []).append(address)
        elif value == opaque:
            set_bits.setdefault(value, []).append(address)
        else:
            merge.append((address, opaque, value))

    code = bytearray()
    for value in sorted(full):
        emit_grouped(code, value, OP_STA_ZP, full[value])
    for opaque in sorted(clear):
        emit_grouped(code, opaque, OP_TRB_ZP, clear[opaque])
    for value in sorted(set_bits):
        emit_grouped(code, value, OP_TSB_ZP, set_bits[value])
    for address, opaque, value in merge:
        code.extend((
            OP_LDA_ZP, address,
            OP_AND_IMMEDIATE, (opaque ^ DOT_MASK) | VIDEO7_COLOR,
            OP_ORA_IMMEDIATE, value,
            OP_STA_ZP, address,
        ))
    code.append(OP_RTS)
    return bytes(code)


def compile_rows(assets: Path) \
        -> tuple[list[bytes], list[tuple[bytes, bytes]], list[int]]:
    routines: list[bytes] = []
    packed_rows: list[tuple[bytes, bytes]] = []
    layer_code_sizes: list[int] = []

    for layer_index, filename in enumerate(LAYERS):
        path = assets / filename
        if not path.is_file():
            raise AssetError(f"missing parallax source asset: {path}")
        layer_size = 0
        for row_number, rgba in enumerate(read_rgba_png(path)):
            data, opacity = pack_row(
                path, row_number, rgba, layer_index == 0
            )
            routine = (compile_deep_row(data) if layer_index == 0
                       else compile_overlay_row(data, opacity))
            routines.append(routine)
            packed_rows.append((data, opacity))
            layer_size += len(routine)
        layer_code_sizes.append(layer_size)
        print(
            f"layer {layer_index + 1}: {path.name}: "
            f"{layer_size} compiled bytes"
        )
    return routines, packed_rows, layer_code_sizes


def pack_banks(routines: list[bytes]) \
        -> tuple[list[tuple[int, int]], list[bytes]]:
    locations: list[tuple[int, int]] = []
    bank_images = [bytearray(BANK_IMAGE_SIZE) for _ in range(BANK_COUNT)]
    bank_index = 0
    bank_offset = 0

    for routine_index, routine in enumerate(routines):
        if not routine or len(routine) > BANK_IMAGE_SIZE:
            raise AssetError(
                f"compiled routine {routine_index} has invalid size "
                f"{len(routine)}"
            )
        if bank_offset + len(routine) > BANK_IMAGE_SIZE:
            bank_index += 1
            bank_offset = 0
        if bank_index >= BANK_COUNT:
            raise AssetError("compiled rows exceed five 32 KiB bank images")

        address = BANK_LOAD_ADDRESS + bank_offset
        locations.append((bank_index + 1, address))
        bank_images[bank_index][bank_offset:bank_offset + len(routine)] = routine
        bank_offset += len(routine)

    used_banks = bank_index + 1
    if used_banks != BANK_COUNT:
        raise AssetError(
            f"compiled rows occupy {used_banks} banks; expected {BANK_COUNT}"
        )
    return locations, [bytes(image) for image in bank_images]


def build_output(routines: list[bytes]) \
        -> tuple[bytes, list[tuple[int, int]]]:
    locations, bank_images = pack_banks(routines)
    header = HEADER.pack(
        MAGIC,
        VERSION,
        len(LAYERS),
        ROW_BYTES,
        BANK_COUNT,
        WIDTH,
        HEIGHT,
        DIRECTORY_OFFSET,
        BANK_IMAGES_OFFSET,
    )
    directory = b"".join(
        DIRECTORY_ENTRY.pack(bank, address)
        for bank, address in locations
    )
    prefix = header + directory
    if len(prefix) > BANK_IMAGES_OFFSET:
        raise AssetError("compiled row directory overlaps the bank images")
    output = prefix + bytes(BANK_IMAGES_OFFSET - len(prefix)) \
        + b"".join(bank_images)
    return output, locations


def emulate_routine(code: bytes, initial: bytearray) -> bytearray:
    memory = bytearray(initial)
    accumulator = 0
    pc = 0
    while pc < len(code):
        opcode = code[pc]
        pc += 1
        if opcode == OP_RTS:
            if pc != len(code):
                raise AssetError("compiled row has data after RTS")
            return memory
        if pc >= len(code):
            raise AssetError("compiled row ends inside an instruction")
        operand = code[pc]
        pc += 1
        if opcode == OP_LDA_IMMEDIATE:
            accumulator = operand
        elif opcode == OP_LDA_ZP:
            accumulator = memory[operand]
        elif opcode == OP_STA_ZP:
            memory[operand] = accumulator
        elif opcode == OP_TRB_ZP:
            memory[operand] &= (~accumulator) & 0xFF
        elif opcode == OP_TSB_ZP:
            memory[operand] |= accumulator
        elif opcode == OP_AND_IMMEDIATE:
            accumulator &= operand
        elif opcode == OP_ORA_IMMEDIATE:
            accumulator |= operand
        else:
            raise AssetError(f"compiled row contains opcode ${opcode:02X}")
    raise AssetError("compiled row has no RTS")


def validate_routine(code: bytes, data: bytes, opacity: bytes,
                     layer_index: int) -> None:
    output_addresses = {
        group_zp_address(group) for group in range(ROW_BYTES)
    }
    pc = 0
    while pc < len(code):
        opcode = code[pc]
        pc += 1
        if opcode == OP_RTS:
            if pc != len(code):
                raise AssetError("compiled row has trailing bytes")
            break
        if pc >= len(code):
            raise AssetError("compiled row has a truncated operand")
        operand = code[pc]
        pc += 1
        if opcode in (OP_STA_ZP, OP_TRB_ZP, OP_TSB_ZP, OP_LDA_ZP) \
                and operand not in output_addresses:
            raise AssetError(
                f"compiled row accesses invalid zero-page byte ${operand:02X}"
            )
        if opcode not in (
                OP_LDA_IMMEDIATE, OP_STA_ZP, OP_TRB_ZP, OP_TSB_ZP,
                OP_LDA_ZP, OP_AND_IMMEDIATE, OP_ORA_IMMEDIATE):
            raise AssetError(f"compiled row contains opcode ${opcode:02X}")
    else:
        raise AssetError("compiled row has no RTS")

    # Every output cell is independent. Running all 128 possible seven-dot
    # inputs therefore proves every generated operation, including partial
    # opacity. Give each cell a different value in a trial so an accidental
    # cross-cell read also fails while all 128 inputs still rotate through
    # every address.
    for input_dots in range(128):
        initial = bytearray(256)
        for group in range(ROW_BYTES):
            address = group_zp_address(group)
            initial[address] = ((input_dots + group) & DOT_MASK) | VIDEO7_COLOR
        actual = emulate_routine(code, initial)
        for group in range(ROW_BYTES):
            address = group_zp_address(group)
            if layer_index == 0:
                expected = data[group] | VIDEO7_COLOR
            else:
                keep = (opacity[group] ^ DOT_MASK) | VIDEO7_COLOR
                expected = (initial[address] & keep) | data[group]
            if actual[address] != expected:
                raise AssetError(
                    f"compiled layer {layer_index + 1} row operation for "
                    f"group {group} maps ${actual[address]:02X}, expected "
                    f"${expected:02X} from input ${initial[address]:02X}"
                )


def validate_output(output: bytes, routines: list[bytes],
                    packed_rows: list[tuple[bytes, bytes]],
                    locations: list[tuple[int, int]]) -> None:
    expected_size = BANK_IMAGES_OFFSET + BANK_COUNT * BANK_IMAGE_SIZE
    if len(output) != expected_size:
        raise AssetError(
            f"compiled asset is {len(output)} bytes; expected {expected_size}"
        )
    expected_header = (
        MAGIC, VERSION, len(LAYERS), ROW_BYTES, BANK_COUNT,
        WIDTH, HEIGHT, DIRECTORY_OFFSET, BANK_IMAGES_OFFSET,
    )
    if HEADER.unpack_from(output) != expected_header:
        raise AssetError("compiled asset header failed validation")

    entry_count = len(LAYERS) * HEIGHT
    if not (len(routines) == len(packed_rows) == len(locations) == entry_count):
        raise AssetError(
            "compiled asset does not contain one routine per source row"
        )
    directory_end = DIRECTORY_OFFSET + entry_count * DIRECTORY_ENTRY.size
    if directory_end > BANK_IMAGES_OFFSET:
        raise AssetError("compiled asset directory is too large")
    if any(output[directory_end:BANK_IMAGES_OFFSET]):
        raise AssetError("compiled asset directory padding is not zero")

    parsed_locations = [
        DIRECTORY_ENTRY.unpack_from(
            output, DIRECTORY_OFFSET + index * DIRECTORY_ENTRY.size
        )
        for index in range(entry_count)
    ]
    if parsed_locations != locations:
        raise AssetError("compiled asset directory failed validation")

    for index, ((bank, address), routine, packed) in enumerate(
            zip(locations, routines, packed_rows)):
        if not 1 <= bank <= BANK_COUNT:
            raise AssetError(f"routine {index} has invalid bank {bank}")
        if not BANK_LOAD_ADDRESS <= address < BANK_LIMIT_ADDRESS:
            raise AssetError(
                f"routine {index} has invalid address ${address:04X}"
            )
        offset = address - BANK_LOAD_ADDRESS
        if offset + len(routine) > BANK_IMAGE_SIZE:
            raise AssetError(f"routine {index} crosses a bank boundary")
        file_offset = BANK_IMAGES_OFFSET + (bank - 1) * BANK_IMAGE_SIZE + offset
        if output[file_offset:file_offset + len(routine)] != routine:
            raise AssetError(f"routine {index} does not match its bank image")
        validate_routine(
            routine, packed[0], packed[1], index // HEIGHT
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        routines, packed_rows, _ = compile_rows(args.assets)
        output, locations = build_output(routines)
        validate_output(output, routines, packed_rows, locations)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(output)
    except (AssetError, OSError) as error:
        raise SystemExit(error) from error

    code_size = sum(map(len, routines))
    max_routine = max(map(len, routines))
    print(
        f"built {args.output} ({len(output)} bytes, "
        f"{code_size} compiled bytes, {BANK_COUNT} banks, "
        f"max routine {max_routine} bytes, "
        f"sha256 {hashlib.sha256(output).hexdigest()})"
    )


if __name__ == "__main__":
    main()
