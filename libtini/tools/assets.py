#!/usr/bin/env python3
"""Deterministic, standard-library-only libtini graphics/resource compiler."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import struct

BANK_BYTES = 48640


def indexed(width, height, indices, mask=False):
    """TI4 image, optional appended 1bpp opacity mask; zero is transparent."""
    if not (1 <= width <= 320 and 1 <= height <= 200) or len(indices) != width * height:
        raise ValueError("image dimensions/pixel count exceed the 320x200 surface contract")
    if any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < 16 for v in indices):
        raise ValueError("indexed pixels must be integers 0..15")
    stride, mask_stride = (width + 1) // 2, (width + 7) // 8
    pixels, opacity = bytearray(stride * height), bytearray(mask_stride * height)
    for y in range(height):
        for x in range(width):
            value = indices[y * width + x]
            pixels[y * stride + x // 2] |= value << (0 if x & 1 else 4)
            if value:
                opacity[y * mask_stride + x // 8] |= 128 >> (x & 7)
    return b"TI4\0" + struct.pack("<HH", width, height) + pixels + (opacity if mask else b"")


def palette(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 16:
        raise ValueError("palette needs 1..16 0RGB integers or #RRGGBB strings")
    result = []
    for value in values:
        if isinstance(value, str):
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise ValueError("invalid RGB color")
            rgb = [int(value[i:i + 2], 16) // 16 for i in (1, 3, 5)]
            value = rgb[0] << 8 | rgb[1] << 4 | rgb[2]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 4095:
            raise ValueError("palette value outside 12-bit 0RGB")
        result.append(value)
    return result + [0] * (16 - len(result))


def ppm(data):
    """Read P3/P6 PPM (8-bit channels); comments and whitespace in header."""
    pos = 0
    def token():
        nonlocal pos
        while pos < len(data):
            if data[pos] in b" \t\r\n": pos += 1
            elif data[pos] == 35:
                while pos < len(data) and data[pos] not in b"\r\n": pos += 1
            else: break
        start = pos
        while pos < len(data) and data[pos] not in b" \t\r\n#": pos += 1
        if start == pos: raise ValueError("truncated PPM header")
        return data[start:pos]
    magic = token()
    if magic not in (b"P3", b"P6"): raise ValueError("input must be P3 or P6 PPM")
    width, height, maximum = int(token()), int(token()), int(token())
    if not 1 <= width <= 320 or not 1 <= height <= 200 or maximum != 255:
        raise ValueError("PPM must be 1..320 x 1..200 with maxval 255")
    length = width * height * 3
    if magic == b"P6":
        if pos >= len(data) or data[pos] not in b" \t\r\n": raise ValueError("missing PPM raster separator")
        if data[pos:pos + 2] == b"\r\n": pos += 2
        else: pos += 1
        raster = data[pos:]
        if len(raster) != length: raise ValueError("PPM raster size mismatch")
        channels = list(raster)
    else:
        channels = []
        for _ in range(length):
            value = int(token())
            if not 0 <= value <= 255: raise ValueError("PPM channel outside 0..255")
            channels.append(value)
        if re.sub(rb"#[^\r\n]*", b"", data[pos:]).strip(): raise ValueError("extra PPM raster data")
    return width, height, list(zip(channels[::3], channels[1::3], channels[2::3]))


def convert_ppm(data, colors, masked=False):
    width, height, rgb = ppm(data)
    colors = palette(colors)
    components = [((c >> 8) * 16, (c >> 4 & 15) * 16, (c & 15) * 16) for c in colors]
    indices = [min(range(16), key=lambda n: sum((a - b) ** 2 for a, b in zip(pixel, components[n])))
               for pixel in rgb]
    return indexed(width, height, indices, masked), struct.pack("<16H", *colors)


def font(spec):
    width, height, first = spec["width"], spec["height"], spec.get("first", 32)
    glyphs = spec["glyphs"]
    if not 1 <= width <= 8 or not 1 <= height <= 16 or not 0 <= first <= 255 or not 1 <= len(glyphs) <= 255 or first + len(glyphs) > 256:
        raise ValueError("font exceeds bounded 8x16 / 255-glyph contract")
    payload = bytearray()
    for rows in glyphs:
        if len(rows) != height: raise ValueError("glyph height mismatch")
        for row in rows:
            if len(row) != width or any(c not in ".#" for c in row): raise ValueError("glyph rows need width pixels of . and #")
            payload.append(sum((128 >> x) for x, value in enumerate(row) if value == "#"))
    return b"TIF1" + bytes((first, len(glyphs), width, height)) + payload


def tilemap(rows, tile_count=256):
    if not rows or not 1 <= len(rows) <= 256 or not rows[0] or not 1 <= len(rows[0]) <= 256 or not 1 <= tile_count <= 256:
        raise ValueError("tile map dimensions/count outside contract")
    width = len(rows[0])
    if any(len(row) != width for row in rows): raise ValueError("ragged tile map")
    if any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < tile_count for row in rows for v in row): raise ValueError("tile ID outside tileset")
    return b"TIM1" + struct.pack("<HH", width, len(rows)) + bytes(v for row in rows for v in row)


def pack(entries):
    """TPK1 header + sorted 24-byte directory + concatenated exact payloads."""
    if not 1 <= len(entries) <= 16: raise ValueError("resource packs need 1..16 entries")
    entries = sorted(entries, key=lambda item: item[0])
    seen, directory, payload = set(), bytearray(), bytearray()
    offset = 8 + len(entries) * 24
    for name, data in entries:
        if not re.fullmatch(r"[A-Z][A-Z0-9_.]{0,14}", name) or name in seen:
            raise ValueError("entry names need unique upper-case ASCII identifiers, 1..15 bytes")
        if not data or len(data) > 4 * 1024 * 1024: raise ValueError("entry size outside 1..4MiB")
        seen.add(name)
        directory += name.encode().ljust(16, b"\0") + struct.pack("<II", offset, len(data))
        payload += data
        offset += len(data)
    if offset > 0xFFFFFF: raise ValueError("pack exceeds the 24-bit ProDOS EOF limit")
    return b"TPK1" + struct.pack("<HH", len(entries), 0) + directory + payload


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="kind", required=True)
    for kind in ("image", "indexed", "font", "map", "pack"):
        c = sub.add_parser(kind)
        c.add_argument("input", type=Path); c.add_argument("output", type=Path)
        c.add_argument("--report", type=Path)
        if kind == "image":
            c.add_argument("--palette", type=Path, required=True)
            c.add_argument("--palette-output", type=Path)
            c.add_argument("--masked", action="store_true")
    a = p.parse_args()
    if a.kind == "image":
        result, colors = convert_ppm(a.input.read_bytes(), json.loads(a.palette.read_text()), a.masked)
        if a.palette_output: a.palette_output.write_bytes(colors)
    else:
        spec = json.loads(a.input.read_text())
        if a.kind == "indexed": result = indexed(spec["width"], spec["height"], spec["pixels"], spec.get("masked", False))
        elif a.kind == "font": result = font(spec)
        elif a.kind == "map": result = tilemap(spec["rows"], spec.get("tile_count", 256))
        else:
            entries = []
            for entry in spec["entries"]:
                candidate = a.input.parent / entry["path"]
                path = candidate.resolve()
                linked = any(p.is_symlink() or getattr(p, "is_junction", lambda: False)()
                             for p in (candidate, *candidate.parents))
                if not path.is_relative_to(a.input.parent.resolve()) or linked or not path.is_file():
                    raise ValueError("pack inputs must be ordinary files under the manifest directory")
                entries.append((entry["name"], path.read_bytes()))
            result = pack(entries)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(result)
    report = {"bytes": len(result), "bank_window_bytes": BANK_BYTES,
              "minimum_resource_banks": (len(result) + BANK_BYTES - 1) // BANK_BYTES,
              "private_transport_required": False}
    if a.report: a.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
