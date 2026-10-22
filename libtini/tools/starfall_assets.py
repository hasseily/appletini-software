#!/usr/bin/env python3
"""Compile vendored CC0 Pixel Shmup art and STARFALL's small atlas to packed SHR cells.

Only Python's standard library is required. Source PNGs stay inside the exact
publisher archive; normal builds do not download or use Pillow/ImageMagick.
"""
from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import struct
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "assets/starfall/source/kenney_pixel-shmup.zip"
ARCHIVE_SHA256 = "e33fd626b799de343f18c81ebaa6f3bc161772fdd717acf3f223589ce74cf952"

# Zero is transparent in sprites and the navy playfield color on screen.
# The remaining entries retain Kenney's metal/cyan/orange/gold/lime ramps;
# three extra colors are available for stars, HUD and projectile effects.
PALETTE = (0x012, 0x345, 0x99B, 0xDDE, 0xFFF, 0x2BF, 0x09C, 0xF63,
           0xD41, 0xFB2, 0xDA0, 0xBD4, 0x8A1, 0x124, 0x95D, 0xF6B)
RGB = tuple(((p >> 8) * 17, ((p >> 4) & 15) * 17, (p & 15) * 17) for p in PALETTE)

# name, publisher archive member, destination content size, reverse 180 degrees.
# Every frame occupies a fixed 16x16 transparent cell (128 packed bytes).
FRAMES = (
    ("PLAYER", "Ships/ship_0000.png", 16, False),
    ("SCOUT", "Ships/ship_0009.png", 16, True),
    ("WEAVER", "Ships/ship_0007.png", 16, True),
    ("DART", "Ships/ship_0010.png", 16, True),
    ("HEAVY", "Ships/ship_0001.png", 16, True),
    ("GUNSHIP", "Ships/ship_0003.png", 16, True),
    ("POWER", "Tiles/tile_0025.png", 16, False),
    ("SHIELD", "Tiles/tile_0026.png", 16, False),
    ("REPAIR", "Tiles/tile_0024.png", 16, False),
    ("BOMB", "Tiles/tile_0018.png", 16, False),
    ("EXPLOSION0", "Tiles/tile_0004.png", 16, False),
    ("EXPLOSION1", "Tiles/tile_0005.png", 16, False),
    ("EXPLOSION2", "Tiles/tile_0007.png", 16, False),
)

# The optional parallax backdrop: Kenney's grey aircraft as distant traffic.
# Each is cropped to its opaque pixels, reduced to a square of content
# pixels with pixel-center nearest neighbor, then darkened by a palette
# remap: the farther, the darker and smaller. name, members with their
# pixel position in the 16x16 cell, content size, remap of palette indices.
MID_TONES = {1: 13, 2: 1, 3: 2, 4: 2}
FAR_TONES = {1: 13, 2: 1, 3: 1, 4: 1}
BACKDROP = (
    ("MID", (("Ships/ship_0012.png", 3, 3),), 10, MID_TONES),
    ("FAR", (("Ships/ship_0018.png", 1, 1), ("Ships/ship_0019.png", 9, 1),
             ("Ships/ship_0020.png", 1, 9), ("Ships/ship_0021.png", 9, 9)), 6, FAR_TONES),
)
# FAR's four 8x8 quadrants are separate scene images, 4 bytes by 8 rows.
FAR_IMAGES = (0, 4, 64, 68)

# Hand-authored projectiles and effects share one further 16x16 cell, the
# atlas. They use palette indices directly; "." is transparent. Each entry is
# name, x, y and rows; x is even so each sub-sprite starts on a packed byte.
# No archive art uses indices 14 (purple) or 15 (pink), so the game can
# animate those two colors through the palette.
SUBSPRITES = (
    ("ORB", 0, 0, (".ff.", "f44f", "f44f", ".ff.")),
    ("FAN", 4, 0, (".77.", "7997", "7997", ".77.")),
    ("NEEDLE", 8, 0, ("88", "88", "77", "77", "99", "44")),
    ("BOLT", 10, 0, ("44", "44", "55", "55", "55", "66", "66", "dd")),
    ("LANCE", 12, 0, (".44.", ".44.", "9449", "9449", "9999", ".99.", ".77.", ".77.")),
    ("FLAME0", 0, 4, ("9449", "9999", ".77.", ".77.", ".8..")),
    ("FLAME1", 4, 4, ("9449", ".99.", ".77.", "..8.", "....")),
    ("SPARK0", 0, 10, (".99.", "9449", "9449", ".99.")),
    ("SPARK1", 4, 10, ("4....4", ".9..9.", "..44..", "..44..", ".9..9.", "4....4")),
    # A wingman: shimmer (14) glows with the shield; blue (13) wings.
    ("WING", 10, 8, ("..44..", "..ee..", ".e44e.", "eeddee", "e.ee.e", "..99..", "..77..")),
)


def png_indexed(data: bytes):
    """Decode the publisher's noninterlaced indexed PNGs, including PNG filters.

    This deliberately supports only the input format needed here: color type 3,
    bit depths 1/2/4/8. CRCs and inflated size are checked before pixel access.
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    position, chunks = 8, {}
    while position < len(data):
        if position + 12 > len(data):
            raise ValueError("truncated PNG chunk")
        size = struct.unpack_from(">I", data, position)[0]
        kind = data[position + 4:position + 8]
        payload = data[position + 8:position + 8 + size]
        if position + size + 12 > len(data):
            raise ValueError("truncated PNG data")
        crc = struct.unpack_from(">I", data, position + 8 + size)[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != crc:
            raise ValueError("PNG chunk CRC mismatch")
        chunks.setdefault(kind, []).append(payload)
        position += size + 12
        if kind == b"IEND":
            break
    if len(chunks.get(b"IHDR", [])) != 1 or len(chunks[b"IHDR"][0]) != 13:
        raise ValueError("invalid PNG IHDR")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", chunks[b"IHDR"][0])
    if not (1 <= width <= 64 and 1 <= height <= 64) or color != 3 or depth not in (1, 2, 4, 8):
        raise ValueError("expected small indexed PNG with 1/2/4/8 bit indices")
    if compression or filtering or interlace:
        raise ValueError("unsupported PNG compression/filter/interlace method")
    palette = b"".join(chunks.get(b"PLTE", []))
    transparency = b"".join(chunks.get(b"tRNS", []))
    if not palette or len(palette) % 3 or len(palette) > 768:
        raise ValueError("invalid indexed PNG palette")
    stride = (width * depth + 7) // 8
    expected = height * (stride + 1)
    inflater = zlib.decompressobj()
    raw = inflater.decompress(b"".join(chunks.get(b"IDAT", [])), expected + 1)
    if len(raw) != expected or not inflater.eof or inflater.unconsumed_tail:
        raise ValueError("PNG decompressed size mismatch")
    result, previous = [], bytearray(stride)
    for y in range(height):
        base = y * (stride + 1)
        filter_type = raw[base]
        row = bytearray(raw[base + 1:base + 1 + stride])
        for x in range(stride):
            left = row[x - 1] if x else 0
            above = previous[x]
            upper_left = previous[x - 1] if x else 0
            if filter_type == 0:
                prediction = 0
            elif filter_type == 1:
                prediction = left
            elif filter_type == 2:
                prediction = above
            elif filter_type == 3:
                prediction = (left + above) // 2
            elif filter_type == 4:
                estimate = left + above - upper_left
                differences = (abs(estimate - left), abs(estimate - above), abs(estimate - upper_left))
                prediction = (left, above, upper_left)[differences.index(min(differences))]
            else:
                raise ValueError("invalid PNG filter")
            row[x] = (row[x] + prediction) & 255
        for x in range(width):
            bit = x * depth
            index = (row[bit // 8] >> (8 - depth - bit % 8)) & ((1 << depth) - 1)
            if index * 3 + 2 >= len(palette):
                raise ValueError("PNG palette index out of range")
            alpha = transparency[index] if index < len(transparency) else 255
            if alpha not in (0, 255):
                raise ValueError("sprite source must have binary transparency")
            result.append(tuple(palette[index * 3:index * 3 + 3]) + (alpha,))
        previous = row
    return width, height, result


def atlas():
    """Return the hand-authored cell and (name, byte offset, width, height)."""
    cell, used, records = [0] * 256, set(), []
    for name, x, y, rows in SUBSPRITES:
        width, height = len(rows[0]), len(rows)
        if x % 2 or width % 2 or any(len(row) != width for row in rows):
            raise ValueError("sub-sprite must be byte aligned: " + name)
        if x + width > 16 or y + height > 16:
            raise ValueError("sub-sprite leaves the atlas cell: " + name)
        area = {(y + dy) * 16 + x + dx for dy in range(height) for dx in range(width)}
        if area & used:
            raise ValueError("sub-sprites overlap: " + name)
        used |= area
        for dy, row in enumerate(rows):
            for dx, mark in enumerate(row):
                cell[(y + dy) * 16 + x + dx] = 0 if mark == "." else int(mark, 16)
        records.append((name, y * 8 + x // 2, width, height))
    return cell, records


def nearest(pixel):
    return min(range(1, 13), key=lambda i: sum((a - b) ** 2 for a, b in zip(pixel[:3], RGB[i])))


def backdrop_cell(archive, members, size, tones):
    """One 16x16 cell of cropped, reduced and darkened aircraft."""
    cell = [0] * 256
    for member, left, top in members:
        width, height, rgba = png_indexed(archive.read(member))
        opaque = [(x, y) for y in range(height) for x in range(width) if rgba[y * width + x][3]]
        if not opaque or left + size > 16 or top + size > 16:
            raise ValueError("backdrop aircraft changed or leaves its cell: " + member)
        x0, y0 = min(x for x, _ in opaque), min(y for _, y in opaque)
        side = max(max(x for x, _ in opaque) - x0, max(y for _, y in opaque) - y0) + 1
        # Center the content's bounding box in a square of that side.
        x0 -= (side - (max(x for x, _ in opaque) - x0 + 1)) // 2
        y0 -= (side - (max(y for _, y in opaque) - y0 + 1)) // 2
        for y in range(size):
            for x in range(size):
                source_x = x0 + ((2 * x + 1) * side) // (2 * size)
                source_y = y0 + ((2 * y + 1) * side) // (2 * size)
                if not (0 <= source_x < width and 0 <= source_y < height):
                    continue
                pixel = rgba[source_y * width + source_x]
                if pixel[3]:
                    index = nearest(pixel)
                    cell[(top + y) * 16 + left + x] = tones.get(index, index)
    return cell


def compile_assets():
    """Return generated C header text and the unpacked 16x16 cells."""
    archive_bytes = ARCHIVE.read_bytes()
    if hashlib.sha256(archive_bytes).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("STARFALL publisher archive SHA-256 mismatch")
    frames = []
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        for name, member, size, reverse in FRAMES:
            width, height, rgba = png_indexed(archive.read(member))
            if width != height or width < size:
                raise ValueError("sprite source dimensions changed: " + name)
            cell = [0] * 256
            inset = (16 - size) // 2
            for y in range(size):
                for x in range(size):
                    # Pixel-center nearest neighbor: 32->16 samples source
                    # coordinates 1,3,...; 16->16 copies; no host filtering.
                    source_x = ((2 * x + 1) * width) // (2 * size)
                    source_y = ((2 * y + 1) * height) // (2 * size)
                    pixel = rgba[source_y * width + source_x]
                    if not pixel[3]:
                        continue
                    index = nearest(pixel)
                    dest_x, dest_y = (size - 1 - x, size - 1 - y) if reverse else (x, y)
                    cell[(dest_y + inset) * 16 + dest_x + inset] = index
            frames.append(cell)
        backdrop = [backdrop_cell(archive, members, size, tones) for _, members, size, tones in BACKDROP]
    cell, subsprites = atlas()
    frames.append(cell)
    frames += backdrop
    names = [frame[0] for frame in FRAMES] + ["ATLAS"] + [entry[0] for entry in BACKDROP]
    lines = ["/* Generated by tools/starfall_assets.py from Kenney Pixel Shmup (CC0)",
             " * and the hand-authored STARFALL atlas. */",
             "#ifndef STARFALL_ASSETS_H", "#define STARFALL_ASSETS_H", "#include <stdint.h>",
             "#define SF_ART_WIDTH 16U", "#define SF_ART_HEIGHT 16U", "#define SF_ART_FRAME_BYTES 128U", "enum {"]
    lines += [f"    SF_ART_{name} = {i}," for i, name in enumerate(names)]
    lines += [f"    SF_ART_COUNT = {len(names)}", "};", "#define SF_ART_SWEEPER SF_ART_WEAVER", "enum {"]
    lines += [f"    SF_SUB_{record[0]} = {i}," for i, record in enumerate(subsprites)]
    lines += [f"    SF_SUB_COUNT = {len(subsprites)}", "};",
              "static const uint16_t sf_palette[16] = {", "    " + ", ".join(f"0x{p:03x}U" for p in PALETTE), "};",
              "/* Atlas sub-sprites as libtini ti_image initializers: pixels in the",
              " * atlas cell, bytes per row, rows and the cell's 8-byte stride. */",
              "#define SF_SUB_IMAGES \\"]
    lines += [f"    {{&sf_sprite_pixels[SF_ART_ATLAS][{offset}], {width // 2}, {height}, 8}}"
              + (", \\" if i < len(subsprites) - 1 else "")
              for i, (_, offset, width, height) in enumerate(subsprites)]
    lines += ["/* The four 8x8 far aircraft of the backdrop, as ti_image initializers. */",
              f"#define SF_FAR_COUNT {len(FAR_IMAGES)}", "#define SF_FAR_IMAGES \\"]
    lines += [f"    {{&sf_sprite_pixels[SF_ART_FAR][{offset}], 4, 8, 8}}" + (", \\" if i < len(FAR_IMAGES) - 1 else "")
              for i, offset in enumerate(FAR_IMAGES)]
    lines += ["static const uint8_t sf_sprite_pixels[SF_ART_COUNT][SF_ART_FRAME_BYTES] = {"]
    for name, pixels in zip(names, frames):
        packed = [(pixels[i] << 4) | pixels[i + 1] for i in range(0, 256, 2)]
        lines.append("    { /* " + name + " */")
        lines += ["        " + ", ".join(f"0x{b:02x}" for b in packed[i:i + 16]) + "," for i in range(0, 128, 16)]
        lines.append("    },")
    lines += ["};", "#endif", ""]
    return "\n".join(lines), frames


def preview_ppm(frames, scale=4):
    """Portable P6 contact sheet, seven columns, no imaging dependencies."""
    width, height = 7 * 24 * scale, (len(frames) + 6) // 7 * 24 * scale
    result = bytearray()
    for y in range(height):
        for x in range(width):
            cx, cy = x // scale, y // scale
            frame = (cy // 24) * 7 + cx // 24
            sx, sy = cx % 24 - 4, cy % 24 - 4
            index = (frames[frame][sy * 16 + sx]
                     if frame < len(frames) and 0 <= sx < 16 and 0 <= sy < 16 else 0)
            result.extend(RGB[index])
    return f"P6\n{width} {height}\n255\n".encode("ascii") + result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--header", type=Path, required=True)
    parser.add_argument("--preview", type=Path, help="optional PPM contact sheet")
    args = parser.parse_args()
    header, frames = compile_assets()
    args.header.parent.mkdir(parents=True, exist_ok=True)
    args.header.write_text(header, encoding="ascii", newline="\n")
    if args.preview:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        args.preview.write_bytes(preview_ppm(frames))
    print(f"STARFALL: {len(FRAMES)} CC0 sprites, an atlas of {len(SUBSPRITES)} sub-sprites and "
          f"{len(BACKDROP)} backdrop cells, {len(frames) * 128} packed pixel bytes, 32 palette bytes")


if __name__ == "__main__":
    main()
