#!/usr/bin/env python3
"""Build the seed tables of the port: the built-in default table and the
table files on the disk.

A table is the object database of the original (LOGIC, WSET, PBDATA:
count, sizes, records) with the port's L-record convention: on disk and
in the built-in image, bytes 0-1 of every L-record hold (kind, frame) and
bytes 5-7, 10-15 are zero; `table_normalise` (main.s) fills them in from
the kind table when the table is installed. Vertex coordinates are table
units (x 0..153, y 0..191); a part is placed by shifting its kit template
(from parts.json) so that its sprite box lands at the requested position.

    python3 tools/make_tables.py --parts build/parts.json --out build/tables \
        [--default build/default_table.s]
"""

import argparse
import json
from pathlib import Path

WSET_DEFAULT = [4, 4, 3, 4]         # gravity, speed, kick, elasticity


def rotate_down(xs, ys):
    """Rotate the vertex lists so that the first edge goes down (Y0 < Y1),
    as the scan converter requires of every stored polygon."""
    n = len(xs)
    for k in range(n):
        if ys[k] < ys[(k + 1) % n]:
            return xs[k:] + xs[:k], ys[k:] + ys[:k]
    raise ValueError('degenerate polygon')


def polygon(xs, ys, colour, border=False):
    xs, ys = rotate_down(xs, ys)
    return bytes([2 if border else 1, colour, len(xs)] + xs + ys)


def part(parts, name, x, y):
    """A library object at sprite box position (x, y): the template shifted."""
    p = next(q for q in parts if q['name'] == name)
    dx = x - p['x0']
    dy = y - (p['y0'] - p['hoty'])
    xs = [v + dx for v in p['x']]
    ys = [v + dy for v in p['y']]
    assert all(0 <= v <= 153 for v in xs) and all(1 <= v <= 190 for v in ys), (name, xs, ys)
    rec = bytes([3, 0x10, len(xs)] + xs + ys)
    # L-record: kind, frame, y, x lo, x hi, h, w, stride, time, score, vectors, state
    lrec = bytearray(p['objlen'] - len(rec))
    lrec[0] = p['kind']
    lrec[1] = 0
    lrec[2] = p['y0'] + dy
    lrec[3] = p['x0'] + dx
    lrec[8] = p['time']
    lrec[9] = p['score']
    return rec + bytes(lrec)


def table_one(parts):
    objs = []
    # the border: the outside of this outline is the cabinet
    top_arc = [(150, 30), (146, 18), (138, 10), (126, 5), (110, 3), (44, 3), (28, 5), (16, 10), (8, 18), (3, 30)]
    xs = [3, 3, 150] + [v[0] for v in top_arc]
    ys = [30, 190, 190] + [v[1] for v in top_arc]
    objs.append(polygon(xs, ys, 11, border=True))
    # the launcher lane wall
    objs.append(polygon([139, 139, 141, 141], [60, 188, 188, 60], 2))
    # lower guides toward the flippers
    objs.append(polygon([3, 45, 45, 3], [156, 180, 184, 164], 3))
    objs.append(polygon([138, 138, 96, 96], [156, 164, 184, 180], 3))
    # the deflector at the lane's top: a solid triangle against the border
    # whose hypotenuse sends the ball left into the playfield
    objs.append(polygon([141, 150, 150], [44, 30, 44], 3))
    # parts
    objs.append(part(parts, 'LEFTFLIPPER', 46, 168))
    objs.append(part(parts, 'RIGHTFLIPPER', 78, 168))
    objs.append(part(parts, 'LKICK', 10, 132))
    objs.append(part(parts, 'RKICK', 108, 132))
    objs.append(part(parts, 'BMP1', 38, 56))
    objs.append(part(parts, 'BMP1', 80, 56))
    objs.append(part(parts, 'BMP2', 62, 84))
    objs.append(part(parts, 'LANE1', 46, 14))
    objs.append(part(parts, 'LANE1', 90, 14))
    objs.append(part(parts, 'ROLL1', 24, 24))
    objs.append(part(parts, 'ROLL2', 68, 20))
    objs.append(part(parts, 'ROLL3', 112, 24))
    objs.append(part(parts, 'DROP1', 96, 108))
    objs.append(part(parts, 'TARG4', 8, 92))
    objs.append(part(parts, 'TARG5', 8, 104))
    objs.append(part(parts, 'TARG6', 8, 116))
    objs.append(part(parts, 'SPIN1', 60, 118))
    objs.append(part(parts, 'LAUNCHER', 144, 176))
    objs.append(part(parts, 'BALL', 144, 150))
    return objs


def database(objs, wset=WSET_DEFAULT, logic=None):
    logic = logic or [0] * 24
    pbdata = bytes([len(objs)] + [len(o) for o in objs]) + b''.join(objs)
    return bytes(logic) + bytes(wset) + pbdata


# --- the overlay chunk (docs/DESIGN.md section 11, src/files.s) ---------
# The magnifier's pixel edits: 192 rows of 154 nibbles (0 = no edit) as
# 20 x 24 tiles of 8x8 pixels. The chunk is "OVL1", the 72-byte tile map
# (byte 3*row + col//8, bit col%8 set when the tile holds edits) and the
# set tiles' pixels, 8 rows of 4 bytes each in tile order, run-length
# coded: n (1..127) = n literal bytes, $80|n = the next byte n times,
# 0 = the end.
OV_COLS, OV_ROWS, OV_TILE = 20, 24, 32
OV_MAP = 72


def rle_encode(data):
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        run = 1
        while i + run < n and data[i + run] == data[i] and run < 127:
            run += 1
        if run >= 3:
            out += bytes([0x80 | run, data[i]])
            i += run
            continue
        j = i
        while j < n and j - i < 127:
            if j + 2 < n and data[j] == data[j + 1] == data[j + 2]:
                break
            j += 1
        out.append(j - i)
        out += data[i:j]
        i = j
    out.append(0)
    return bytes(out)


def rle_decode(data, pos=0):
    """(the decoded bytes, the position after the end marker)."""
    out = bytearray()
    while True:
        control = data[pos]
        pos += 1
        if control == 0:
            return bytes(out), pos
        if control & 0x80:
            out += bytes([data[pos]]) * (control & 0x7F)
            pos += 1
        else:
            out += data[pos:pos + control]
            pos += control


def tile_bytes(pixels, row, col):
    """The 32 bytes of tile (row, col) of a 192 x 154 nibble array (rows of
    ints 0..15; pixels past x 153 read as 0)."""
    out = bytearray()
    for y in range(8 * row, 8 * row + 8):
        line = pixels[y]
        for x in range(8 * col, 8 * col + 8, 2):
            left = line[x] if x < len(line) else 0
            right = line[x + 1] if x + 1 < len(line) else 0
            out.append((left << 4) | right)
    return bytes(out)


def overlay_chunk(pixels=None):
    """"OVL1", the tile map and the RLE stream of the set tiles; no pixels
    (or none set) gives an empty map and the end marker alone."""
    tiles = bytearray(OV_MAP)
    stream = bytearray()
    if pixels is not None:
        for row in range(OV_ROWS):
            for col in range(OV_COLS):
                tile = tile_bytes(pixels, row, col)
                if any(tile):
                    tiles[3 * row + col // 8] |= 1 << (col % 8)
                    stream += tile
    return b'OVL1' + bytes(tiles) + rle_encode(bytes(stream))


def decode_overlay(chunk):
    """The inverse: (tile map, {(row, col): 32 bytes}) of a chunk starting
    at "OVL1"; raises ValueError for a malformed chunk."""
    if chunk[:4] != b'OVL1':
        raise ValueError('no OVL1 mark')
    tiles = chunk[4:4 + OV_MAP]
    stream, end = rle_decode(chunk, 4 + OV_MAP)
    out = {}
    for row in range(OV_ROWS):
        for col in range(OV_COLS):
            if tiles[3 * row + col // 8] & (1 << (col % 8)):
                if len(stream) < OV_TILE * (len(out) + 1):
                    raise ValueError('stream too short')
                out[(row, col)] = stream[OV_TILE * len(out):OV_TILE * (len(out) + 1)]
    if len(stream) != OV_TILE * len(out):
        raise ValueError('stream length %d for %d tiles' % (len(stream), len(out)))
    return bytes(tiles), out


def pcs_file(db, pixels=None):
    """A table file: "PCS1", the database image, the overlay chunk."""
    return b'PCS1' + db + overlay_chunk(pixels)


def split_pcs_file(data):
    """(database image, overlay chunk) of a table file; ValueError if it
    is not one."""
    if data[:4] != b'PCS1':
        raise ValueError('no PCS1 mark')
    count = data[4 + 28]
    sizes = data[4 + 29:4 + 29 + count]
    end = 4 + 29 + count + sum(sizes)
    return data[4:end], data[end:]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--parts', required=True)
    ap.add_argument('--out', required=True, help='directory for the .PCS files')
    ap.add_argument('--default', help='write the built-in table as ca65 data')
    ap.add_argument('--pb-dir', help='also convert every original .PB in this directory')
    args = ap.parse_args()
    parts = json.loads(Path(args.parts).read_text())['parts']
    tables = {'TABLE1': table_one(parts)}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sources = ()
    if args.pb_dir:
        pb_dir = Path(args.pb_dir)
        if pb_dir.exists() and not pb_dir.is_dir():
            raise ValueError('original .PB path is not a directory: %s' % pb_dir)
        sources = tuple(source for source in sorted(pb_dir.iterdir(), key=lambda p: p.name.upper())
                        if source.is_file() and source.suffix.upper() == '.PB') if pb_dir.is_dir() else ()
    # --out is a generated table directory. Clear PCS files from previous
    # source sets, otherwise removing a .PB leaves a ghost on the HDV.
    current = {'TABLE1.PCS', *(source.stem.upper() + '.PCS' for source in sources)}
    for old in out.iterdir():
        if old.is_file() and old.suffix.upper() == '.PCS' and old.name.upper() not in current:
            old.unlink()
    for name, objs in tables.items():
        data = pcs_file(database(objs))
        assert split_pcs_file(data)[0] == database(objs) and decode_overlay(split_pcs_file(data)[1])
        (out / (name + '.PCS')).write_bytes(data)
    converted = []
    if sources:
        from pb2pcs import convert_pb

        for source in sources:
            name = source.stem.upper()
            if name in tables:
                raise ValueError('%s would overwrite the built-in table' % source.name)
            if not (1 <= len(name) <= 11 and name[0].isalpha()
                    and all(c.isalnum() or c == '.' for c in name)):
                raise ValueError('%s cannot be a ProDOS .PCS filename' % source.name)
            destination = out / (name + '.PCS')
            destination.write_bytes(convert_pb(source.read_bytes()))
            converted.append(name)
    if args.default:
        db = database(tables['TABLE1'])
        lines = ['; Generated by tools/make_tables.py. Do not edit.',
                 '; The built-in table: LOGIC, WSET, PBDATA (L-records hold kind, frame).',
                 '.setcpu "65C02"', '.export default_table, default_table_len',
                 '.segment "RODATA"', 'default_table:']
        for i in range(0, len(db), 16):
            lines.append('        .byte ' + ','.join('$%02X' % b for b in db[i:i + 16]))
        lines.append('default_table_len: .word %d' % len(db))
        Path(args.default).write_text('\n'.join(lines) + '\n')
    print('tables: %s (%d bytes seed)' % (', '.join([*tables, *converted]),
                                            len(database(tables['TABLE1']))))


if __name__ == '__main__':
    main()
