#!/usr/bin/env python3
"""Convert STARFALL's five bosses for the game.

Reads assets/starfall/bosses offline and checks every file against
provenance.json. Writes a C header with the geometry of each boss and one art
file for each boss, which tools/starfall_pack.py puts in STARFALL.PAK.

Colors: the pack uses Kenney's Pixel Shmup palette. Twelve of its colors are
in STARFALL's palette. The two missing colors that a boss uses most take
palette slots 13 and 14 during its sector, the darker one in slot 13. The
third maps to the nearest of the twelve.

Body: frame 0 of the hull, cut into 8-line strips from the top of the boss.
Each strip keeps only the whole bytes between its first and last opaque
pixel. Parts: four intact and four destroyed frames of each weapon. A part at
an odd x gets one transparent column on the left, so that every image starts
on a packed byte.

Art file of a boss, little-endian: the bytes of all strips (16 bits), the
bytes of one frame of each part (16 bits), the boss's sf_boss_art record as
cc65 lays it out (RECORD bytes), the strips, then each part's eight frames.
The game copies the record to its variables and the strips to the overlay
window, below one frame slot for each part. It reads each part frame from
the pack when it changes. The header gives the same records to the host
build of the simulation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/starfall/bosses"
BAND = 8
PARTS = 3
FRAMES = 4

# STARFALL's palette (tools/starfall_assets.py), as 8-bit RGB.
SF = (0x012, 0x345, 0x99B, 0xDDE, 0xFFF, 0x2BF, 0x09C, 0xF63,
      0xD41, 0xFB2, 0xDA0, 0xBD4, 0x8A1, 0x124, 0x95D, 0xF6B)
SF_RGB = [((c >> 8) * 17, ((c >> 4) & 15) * 17, (c & 15) * 17) for c in SF]
# Pack color to STARFALL index, for the twelve colors that STARFALL has.
SHARED = {0x434A5F: 1, 0xFFFFFF: 4, 0xDCE1E7: 3, 0x959AB1: 2, 0x2CC5F6: 5, 0x11A5D4: 6,
          0xFC683B: 7, 0xDE4B1E: 8, 0xB6D53C: 11, 0x92B115: 12, 0xFFBD20: 9, 0xE2A106: 10}
BOSS_SLOTS = (13, 14)
BANDS = 10
# The cc65 size of sf_boss_art: no padding, 16-bit pointers.
RECORD = 3 + 3 * BANDS + 6 + 12 + 5 * (BANDS + 2 * PARTS) + 12 + 6 + 12


def png(data: bytes):
    """Width, height and rows of palette indices plus the PLTE colors of a
    noninterlaced 4-bit or 8-bit indexed PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    position, chunks = 8, {}
    while position < len(data):
        size = struct.unpack_from(">I", data, position)[0]
        kind = data[position + 4:position + 8]
        payload = data[position + 8:position + 8 + size]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != struct.unpack_from(">I", data, position + 8 + size)[0]:
            raise ValueError("PNG chunk CRC mismatch")
        chunks.setdefault(kind, []).append(payload)
        position += size + 12
        if kind == b"IEND":
            break
    width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", chunks[b"IHDR"][0])
    if color != 3 or depth not in (4, 8) or interlace:
        raise ValueError("expected a noninterlaced 4-bit or 8-bit indexed PNG")
    plte = b"".join(chunks[b"PLTE"])
    colors = [int.from_bytes(plte[i:i + 3], "big") for i in range(0, len(plte), 3)]
    stride = (width * depth + 7) // 8
    raw = zlib.decompress(b"".join(chunks[b"IDAT"]))
    if len(raw) != height * (stride + 1):
        raise ValueError("PNG decompressed size mismatch")
    rows, previous = [], bytearray(stride)
    for y in range(height):
        base = y * (stride + 1)
        kind, line = raw[base], bytearray(raw[base + 1:base + 1 + stride])
        for x in range(stride):
            a = line[x - 1] if x else 0
            b = previous[x]
            c = previous[x - 1] if x else 0
            if kind == 1:
                line[x] = (line[x] + a) & 255
            elif kind == 2:
                line[x] = (line[x] + b) & 255
            elif kind == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            elif kind:
                raise ValueError("invalid PNG filter")
        previous = line
        rows.append([(line[(x * depth) // 8] >> (8 - depth - (x * depth) % 8)) & ((1 << depth) - 1)
                     for x in range(width)])
    return width, height, rows, colors


def strip(path: Path):
    """The four frames of a horizontal strip, as lists of color rows; 0 is transparent."""
    width, height, rows, colors = png(path.read_bytes())
    if width % FRAMES:
        raise ValueError(path.name + ": width is not four frames")
    size = width // FRAMES
    return size, height, [[[colors[v] if v else None for v in row[k * size:(k + 1) * size]]
                           for row in rows] for k in range(FRAMES)]


def nearest(rgb: int, choices):
    r, g, b = rgb >> 16, (rgb >> 8) & 255, rgb & 255
    return min(choices, key=lambda i: ((SF_RGB[i][0] - r) ** 2 + (SF_RGB[i][1] - g) ** 2 +
                                       (SF_RGB[i][2] - b) ** 2, i))


def mapping(images):
    """Pack color to STARFALL index for one boss, and its two slot colors."""
    use = {}
    for frame in images:
        for row in frame:
            for rgb in row:
                if rgb is not None and rgb not in SHARED:
                    use[rgb] = use.get(rgb, 0) + 1
    missing = sorted(use, key=lambda rgb: (-use[rgb], rgb))
    chosen = sorted(missing[:2], key=lambda rgb: sum(((rgb >> s) & 255) for s in (16, 8, 0)))
    table = dict(SHARED)
    slots = []
    for slot, rgb in zip(BOSS_SLOTS, chosen):
        table[rgb] = slot
        slots.append(((rgb >> 20) & 15) << 8 | ((rgb >> 12) & 15) << 4 | ((rgb >> 4) & 15))
    for rgb in missing[2:]:
        table[rgb] = nearest(rgb, range(1, 13))
    while len(slots) < 2:
        slots.append(SF[BOSS_SLOTS[len(slots)]])
    return table, slots


def packed(rows, x0, x1, table):
    """Bytes of rows between pixel x0 (even) and x1 (exclusive, even), high nibble first."""
    out = bytearray()
    for row in rows:
        for x in range(x0, x1, 2):
            pair = [table[row[x + i]] if 0 <= x + i < len(row) and row[x + i] is not None else 0
                    for i in (0, 1)]
            out.append(pair[0] << 4 | pair[1])
    return bytes(out)


def convert(boss):
    folder = SOURCE / boss["folder"]
    width, height = boss["size"]
    bw, bh, body = strip(folder / boss["body"]["sheet"])
    bx, by = boss["body"]["offset"]
    if (bx, by) != (0, 0):
        raise ValueError(boss["name"] + ": the body must start at the top-left corner")
    parts = []
    for part in boss["parts"]:
        pw, ph, intact = strip(folder / part["intact"])
        dw, dh, destroyed = strip(folder / part["destroyed"])
        if (pw, ph) != (dw, dh):
            raise ValueError(boss["name"] + ": intact and destroyed frames differ in size")
        parts.append((part, pw, ph, intact + destroyed))
    if len(parts) != PARTS:
        raise ValueError(boss["name"] + ": a boss has three parts")
    table, slots = mapping([body[0], *(frame for part in parts for frame in part[3])])
    frame0 = body[0]
    bands, strips = [], bytearray()
    for y0 in range(0, bh, BAND):
        rows = frame0[y0:y0 + BAND]
        xs = [x for row in rows for x, rgb in enumerate(row) if rgb is not None]
        if not xs:
            continue
        x0, x1 = min(xs) & ~1, (max(xs) + 2) & ~1
        bands.append((x0, y0, (x1 - x0) // 2, len(rows)))
        strips += packed(rows, x0, x1, table)
    if len(bands) > BANDS:
        raise ValueError(boss["name"] + ": more than ten body strips")
    geometry, frames, slot_bytes = [], bytearray(), 0
    for part, pw, ph, images in parts:
        x, y = part["offset"]
        pad = x & 1
        span = (pw + pad + 1) & ~1
        geometry.append((x - pad, y, span // 2, ph, part["hitbox"]))
        for image in images:
            frames += packed(image, -pad, span - pad, table)
        slot_bytes += span // 2 * ph
    # Images: offsets in the window after the overlay, then 1x1 rectangles.
    images, at = [], 0
    for x0, y0, nbytes, rows in bands:
        images.append((at, nbytes, rows, nbytes))
        at += nbytes * rows
    images += [(0, 1, 1, 0)] * (BANDS - len(bands))
    frame_bytes, frames_at, start = [], [], 4 + RECORD + len(strips)
    for x, y, nbytes, rows, _ in geometry:
        images += [(at, nbytes, rows, nbytes)] * 2
        frame_bytes.append(nbytes * rows)
        frames_at.append(start)
        at += nbytes * rows
        start += nbytes * rows * 2 * FRAMES
    boss = {"name": boss["name"].upper(), "width": width, "height": height,
            "bands": bands, "parts": geometry, "slots": slots, "images": images,
            "frame_bytes": frame_bytes, "frames_at": frames_at,
            "strip_bytes": len(strips), "slot_bytes": slot_bytes,
            "table": table, "frame0": frame0, "intact": [p[3][0] for p in parts]}
    record = record_bytes(boss)
    boss["art"] = struct.pack("<HH", len(strips), slot_bytes) + record + bytes(strips) + bytes(frames)
    return boss


def fields(boss):
    """The values of sf_boss_art, in order, as (C text, bytes)."""
    bands, parts = boss["bands"], boss["parts"]

    def u8(values, width):
        values = list(values) + [0] * (width - len(list(values)))
        return "{" + ",".join(map(str, values)) + "}", bytes(values)

    def column(index, source, width):
        return u8([item[index] for item in source], width)
    items = [(str(boss["width"]), bytes([boss["width"]])), (str(boss["height"]), bytes([boss["height"]])),
             (str(len(bands)), bytes([len(bands)])),
             column(0, bands, BANDS), column(1, bands, BANDS), column(2, bands, BANDS),
             column(0, parts, PARTS), column(1, parts, PARTS),
             *(u8([p[4][k] for p in parts], PARTS) for k in range(4))]
    images = "{" + ",".join("{%d,%d,%d,%d}" % image for image in boss["images"]) + "}"
    items.append((images, b"".join(struct.pack("<HBBB", *image) for image in boss["images"])))
    for values in (boss["frame_bytes"], boss["frames_at"]):
        items.append(("{" + ",".join(map(str, values)) + "}", struct.pack("<3H", *values)))
    items.append((str(boss["strip_bytes"]), struct.pack("<H", boss["strip_bytes"])))
    items.append(("{" + ",".join(f"0x{c:03X}" for c in boss["slots"]) + "}", struct.pack("<2H", *boss["slots"])))
    name = boss["name"].encode()
    items.append(('"' + boss["name"] + '"', name + bytes(12 - len(name))))
    return items


def record_bytes(boss):
    data = b"".join(value for _, value in fields(boss))
    if len(data) != RECORD:
        raise ValueError("record size")
    return data


def header(bosses):
    lines = ["/* Generated by tools/starfall_bosses.py from assets/starfall/bosses. */",
             "#ifndef STARFALL_BOSSES_H", "#define STARFALL_BOSSES_H", "#include <stdint.h>",
             "#define SF_BOSSES 5", f"#define SF_BOSS_BANDS {BANDS}", f"#define SF_BOSS_PARTS {PARTS}",
             f"#define SF_BOSS_RECORD {RECORD}",
             "/* A boss image: an offset in the window after the boss overlay, or a",
             " * 1x1 rectangle when stride is zero, and the fields of ti_image. */",
             "typedef struct sf_boss_image { uint16_t offset; uint8_t row_bytes,rows,stride; } sf_boss_image;",
             "/* Positions and sizes are pixels from the top-left corner of the boss,",
             " * except band_bytes: bytes in a row, two pixels each. A part's hit box",
             " * is its intact footprint. images: the body strips, then two on the",
             " * frame slot of each part. frames_at: where each part's eight frames",
             " * are in the art file. colors are the 0RGB values of palette slots 13",
             " * and 14 in the boss sector. */",
             "typedef struct sf_boss_art {",
             "    uint8_t width,height,bands;",
             "    uint8_t band_x[SF_BOSS_BANDS],band_y[SF_BOSS_BANDS],band_bytes[SF_BOSS_BANDS];",
             "    uint8_t part_x[SF_BOSS_PARTS],part_y[SF_BOSS_PARTS];",
             "    uint8_t hit_x[SF_BOSS_PARTS],hit_y[SF_BOSS_PARTS],hit_w[SF_BOSS_PARTS],hit_h[SF_BOSS_PARTS];",
             "    sf_boss_image images[SF_BOSS_BANDS+2*SF_BOSS_PARTS];",
             "    uint16_t frame_bytes[SF_BOSS_PARTS],frames_at[SF_BOSS_PARTS];",
             "    uint16_t strip_bytes,colors[2];",
             "    char name[12];",
             "} sf_boss_art;",
             "/* The records for the host. On the 65C02 each art file holds its own. */",
             "#if defined(SF_BOSS_ART_TABLE) && !defined(__CC65__)",
             "static const sf_boss_art sf_boss_arts[SF_BOSSES]={"]
    for boss in bosses:
        lines.append("    {" + ",".join(text for text, _ in fields(boss)) + "},")
    lines += ["};", "#endif", "#endif", ""]
    return "\n".join(lines)


def preview(bosses, path: Path):
    """A PPM of each boss as the game composes it: strips, then intact part frames."""
    scale, gap = 3, 8
    total_w = sum(b["width"] for b in bosses) * scale + gap * (len(bosses) + 1)
    total_h = max(b["height"] for b in bosses) * scale + 2 * gap
    image = [[SF_RGB[0]] * total_w for _ in range(total_h)]
    left = gap
    for boss in bosses:
        colors = list(SF_RGB)
        for slot, value in zip(BOSS_SLOTS, boss["slots"]):
            colors[slot] = ((value >> 8) * 17, ((value >> 4) & 15) * 17, (value & 15) * 17)

        def put(x, y, index):
            if index:
                for dy in range(scale):
                    for dx in range(scale):
                        image[gap + y * scale + dy][left + x * scale + dx] = colors[index]
        for x0, y0, nbytes, rows in boss["bands"]:
            for y in range(rows):
                for x in range(nbytes * 2):
                    rgb = boss["frame0"][y0 + y][x0 + x] if x0 + x < boss["width"] else None
                    put(x0 + x, y0 + y, boss["table"][rgb] if rgb is not None else 0)
        for (x0, y0, nbytes, rows, _), frame in zip(boss["parts"], boss["intact"]):
            pad = 1 if frame and len(frame[0]) < nbytes * 2 else 0
            for y, row in enumerate(frame):
                for x, rgb in enumerate(row):
                    if rgb is not None:
                        put(x0 + pad + x, y0 + y, boss["table"][rgb])
        left += boss["width"] * scale + gap
    path.write_bytes(f"P6 {total_w} {total_h} 255\n".encode() +
                     bytes(c for row in image for px in row for c in px))


def verify():
    record = json.loads((SOURCE / "provenance.json").read_text())
    for name, digest in record["files"].items():
        if hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() != digest:
            raise SystemExit("boss art differs from provenance.json: " + name)
    return [boss for boss in json.loads((SOURCE / "bosses.json").read_text())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--header", type=Path, required=True)
    parser.add_argument("--art", type=Path, required=True, help="output folder of starfall_boss1.bin..5")
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    bosses = [convert(boss) for boss in verify()]
    args.header.write_text(header(bosses))
    args.art.mkdir(parents=True, exist_ok=True)
    for number, boss in enumerate(bosses, 1):
        (args.art / f"starfall_boss{number}.bin").write_bytes(boss["art"])
    if args.preview:
        preview(bosses, args.preview)
    print("STARFALL bosses: " + ", ".join(
        f"{b['name']} {b['width']}x{b['height']} strips {b['strip_bytes']} B + slots {b['slot_bytes']} B"
        for b in bosses))


if __name__ == "__main__":
    main()
