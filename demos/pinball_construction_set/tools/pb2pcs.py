#!/usr/bin/env python3
"""Convert an original DOS 3.3 Pinball Construction Set .PB into .PCS.

DISK.S writes a DOS binary file: a four-byte (address, length) header,
followed by LOGIC (24), WSET (4), PBDATA (count, sizes, records) and the
COMPRESS stream for the HGR page. The port retains the polygon database,
gate wiring and object state. Library L-records need a new sprite pointer,
so this module replaces their original HGR pointer with (kind, frame),
which the port's table_normalise resolves when loading the .PCS file.

The original bitmap addresses and frame offsets are derived from RUN.S;
hard-coded numeric addresses would silently misclassify parts if the
upstream source changed. Use ``--no-artwork`` only when the saved HGR edits
are deliberately unwanted.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re

import kinds
import parts as partsmod


PROJECT = Path(__file__).resolve().parents[1]
UPSTREAM = PROJECT / 'upstream'
DOS_LOAD_ADDRESS = 0x4000
MAX_OBJECTS = 128               # render.s objcolor[128]


@dataclass(frozen=True)
class PBTable:
    """The original payload split at the end of its object records."""

    address: int
    length: int
    database: bytes
    artwork: bytes             # original DISK.S COMPRESS stream, terminal 01 01 included
    records: tuple[bytes, ...]


def split_database(payload: bytes) -> tuple[bytes, bytes, tuple[bytes, ...]]:
    """Split PBBASE memory at its record boundary, preserving HGR bytes."""
    if len(payload) < 29:
        raise ValueError('PB payload is shorter than LOGIC, WSET and PBDATA')
    count = payload[28]
    if not 1 <= count <= MAX_OBJECTS:
        raise ValueError(f'unsupported object count {count}; maximum is {MAX_OBJECTS}')
    if len(payload) < 29 + count:
        raise ValueError('PB object-size table is truncated')
    sizes = payload[29:29 + count]
    pos = 29 + count
    records = []
    for i, size in enumerate(sizes):
        if not 9 <= size <= 255 or pos + size > len(payload):
            raise ValueError(f'PB object {i} has a truncated or invalid size ({size})')
        rec = payload[pos:pos + size]
        objid, n = rec[0], rec[2]
        if objid not in (1, 2, 3) or n < 3:
            raise ValueError(f'PB object {i} has invalid type or vertex count')
        minimum = 3 + 2 * n + (16 if objid == 3 else 0)
        if size < minimum or (objid != 3 and size != minimum):
            raise ValueError(f'PB object {i} has {size} bytes; expected at least {minimum}')
        records.append(bytes(rec))
        pos += size
    return payload[:pos], payload[pos:], tuple(records)


def parse_pb(data: bytes, *, header: bool | None = None) -> PBTable:
    """Parse an original .PB file or its headerless DOS payload.

    ``header=None`` recognizes the normal $4000 DOS binary header and also
    accepts a headerless extracted data fork. DOS sector padding after the
    advertised length is ignored. ``header=True`` requires the header.
    """
    has_header = len(data) >= 4 and data[:2] == DOS_LOAD_ADDRESS.to_bytes(2, 'little')
    if header is True and not has_header:
        raise ValueError('PB file has no $4000 DOS binary header')
    if header is False:
        has_header = False
    if has_header:
        length = int.from_bytes(data[2:4], 'little')
        if length > len(data) - 4:
            raise ValueError('PB header length exceeds available payload')
        payload = data[4:4 + length]
    else:
        payload = data
        length = len(data)
    database, artwork, records = split_database(payload)
    return PBTable(DOS_LOAD_ADDRESS, length, database, artwork, records)


_EQU = re.compile(r'^([A-Z][A-Z0-9]*)\s+EQU\s+([^; ]+)')
_TERM = re.compile(r'^\$([0-9A-Fa-f]+)$|^(\d+)$|^([A-Z][A-Z0-9]*)$')


def bitmap_symbols(run_lines: list[str]) -> dict[str, int]:
    """Resolve RUN.S's BITMAPS/part EQU chain; only simple +/- terms needed."""
    expressions = {}
    for line in run_lines:
        match = _EQU.match(line)
        if match:
            expressions[match.group(1)] = match.group(2)
    values: dict[str, int] = {}
    visiting: set[str] = set()

    def value(expr: str) -> int:
        terms = re.split(r'([+-])', expr)
        total = 0
        sign = 1
        for term in terms:
            if term == '+':
                sign = 1
                continue
            if term == '-':
                sign = -1
                continue
            match = _TERM.fullmatch(term)
            if not match:
                raise ValueError(f'unsupported RUN.S address expression {expr!r}')
            if match.group(1):
                n = int(match.group(1), 16)
            elif match.group(2):
                n = int(match.group(2))
            else:
                name = match.group(3)
                if name in visiting:
                    raise ValueError(f'cyclic RUN.S symbol {name}')
                if name not in values:
                    if name not in expressions:
                        raise ValueError(f'unknown RUN.S symbol {name}')
                    visiting.add(name)
                    values[name] = value(expressions[name])
                    visiting.remove(name)
                n = values[name]
            total += sign * n
        return total

    # Only resolve symbols reachable from BITMAPS; other RUN.S expressions
    # include assembler syntax that is immaterial to the saved sprite fields.
    value('BITMAPS')
    for name in ('LAUNCHERB', 'LFLIPB', 'RFLIPB', 'BMP1B', 'BMP2B', 'BMP3B',
                 'BMP4B', 'BMP5B', 'BMP6B', 'LKICKB', 'RKICKB', 'KNOCK1B',
                 'KNOCK2B', 'ROLLB', 'LFLIP2B', 'RFLIP2B', 'LANEB', 'DROP1B',
                 'DROP2B', 'CATCH1B', 'CATCH2B', 'SPINB', 'MAGB', 'BALLB'):
        value(name)
    return values


def original_sprite_frames(upstream: Path = UPSTREAM) -> dict[int, tuple[int, int]]:
    """Map every original HGR bitmap pointer to (port kind, frame)."""
    run = partsmod.read_source(upstream, 'RUN.S')
    templates = {p['name']: p for p in partsmod.parse_templates(run)}
    symbols = bitmap_symbols(run)
    fxlen = partsmod.parse_table(run, 'FXLEN')
    if len(fxlen) != 16:
        raise ValueError('RUN.S FXLEN table must have 16 entries')
    pointers: dict[int, tuple[int, int]] = {}
    for kind, name in enumerate(partsmod.KIT_ORDER):
        template = templates[name]
        if template['id'] != 3:
            continue
        base = bitmap_address(template['bitmap'], symbols)
        count = partsmod.FRAMES[name]
        if name in ('LEFTFLIPPER', 'RIGHTFLIPPER', 'LFLIPPER2', 'RFLIPPER2'):
            start = 8 if name.endswith('2') else 0
            offsets = [sum(fxlen[start:start + frame]) for frame in range(count)]
        else:
            offsets = [frame * template['stride'] for frame in range(count)]
        for frame, offset in enumerate(offsets):
            pointer = base + offset
            if pointer in pointers:
                raise ValueError(f'RUN.S bitmap ${pointer:04X} belongs to two kinds')
            pointers[pointer] = kind, frame
    return pointers


def bitmap_address(expr: str, symbols: dict[str, int]) -> int:
    """Evaluate a template's `DA BITMAP` or `DA BITMAP+offset`."""
    match = re.fullmatch(r'([A-Z][A-Z0-9]*)(?:\+(\d+))?', expr)
    if not match or match.group(1) not in symbols:
        raise ValueError(f'unknown bitmap reference {expr!r}')
    return symbols[match.group(1)] + int(match.group(2) or 0)


def port_colour(old: int) -> int:
    return kinds.hgr_fill_to_palette(old)


def convert_database(db: bytes, pointers: dict[int, tuple[int, int]] | None = None) -> bytes:
    """Convert original LOGIC/WSET/PBDATA into port disk representation."""
    source, artwork, records = split_database(db)
    if artwork:
        raise ValueError('convert_database needs database bytes only')
    if pointers is None:
        pointers = original_sprite_frames()
    out = bytearray(source[:29 + len(records)])   # LOGIC, WSET, count, size table
    for i, rec in enumerate(records):
        converted = bytearray(rec)
        converted[1] = port_colour(rec[1])
        if rec[0] == 3:
            pos = 3 + 2 * rec[2]
            old = rec[pos:pos + 16]
            pointer = int.from_bytes(old[:2], 'little')
            if pointer not in pointers:
                raise ValueError(f'PB object {i} has unknown bitmap pointer ${pointer:04X}')
            kind, frame = pointers[pointer]
            x = 7 * old[3] + old[4]
            if old[4] > 6 or x > 319:
                raise ValueError(f'PB object {i} has invalid bitmap X coordinate')
            converted[pos:pos + 16] = bytes((kind, frame, old[2], x & 0xff,
                                              x >> 8, 0, 0, 0, old[8], old[9],
                                              0, 0, 0, 0, 0, 0))
        out.extend(converted)
    return bytes(out)


def convert_pb(data: bytes, *, artwork: bool = True,
               pointers: dict[int, tuple[int, int]] | None = None) -> bytes:
    """Full original .PB to the port's PCS1/OVL1 bytes."""
    import make_tables

    table = parse_pb(data)
    db = convert_database(table.database, pointers)
    pixels = None
    if artwork:
        if not table.artwork:
            raise ValueError('PB file has no compressed HGR artwork')
        from pb_art import decode_hgr_artwork, hgr_to_overlay_pixels
        pixels = hgr_to_overlay_pixels(decode_hgr_artwork(table.artwork))
    return make_tables.pcs_file(db, pixels)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('source', type=Path, help='original .PB file')
    parser.add_argument('output', type=Path, nargs='?', help='destination .PCS file')
    parser.add_argument('--no-artwork', action='store_true', help='omit saved HGR pixel edits')
    args = parser.parse_args()
    output = args.output or args.source.with_suffix('.PCS')
    pcs = convert_pb(args.source.read_bytes(), artwork=not args.no_artwork)
    output.write_bytes(pcs)
    print(f'{args.source.name} -> {output.name} ({len(pcs)} bytes)')


if __name__ == '__main__':
    main()
