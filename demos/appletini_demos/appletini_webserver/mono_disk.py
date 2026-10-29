#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Deterministic root-only ProDOS disk packager for the A2MONO prototype.

The boot blocks and unmodified PRODOS kernel come from the existing demo
disk input. This module contains no operating-system implementation.
"""
from __future__ import annotations
import math
import struct

BLOCK = 512
ENTRY = 39


def word(data: bytes, at: int) -> int:
    return int.from_bytes(data[at:at + 2], "little")


def entries(image: bytes):
    previous, current = 0, 2
    seen = set()
    while current:
        if current in seen or current >= len(image) // BLOCK:
            raise ValueError("invalid ProDOS directory chain")
        seen.add(current)
        base = current * BLOCK
        if word(image, base) != previous:
            raise ValueError("invalid ProDOS directory backlink")
        for slot in range(1 if current == 2 else 0, 13):
            at = base + 4 + slot * ENTRY
            entry = image[at:at + ENTRY]
            if entry[0] >> 4:
                yield entry
        previous, current = current, word(image, base + 2)


def extract(image: bytes, name: str) -> bytes:
    """Read one root seedling/sapling file, without reading unrelated files."""
    for entry in entries(image):
        if entry[1:1 + (entry[0] & 15)].decode("ascii") != name:
            continue
        kind, key = entry[0] >> 4, word(entry, 17)
        length = int.from_bytes(entry[21:24], "little")
        count = math.ceil(length / BLOCK)
        if kind == 1 and count <= 1:
            blocks = [key]
        elif kind == 2 and count <= 256:
            index = image[key * BLOCK:(key + 1) * BLOCK]
            if len(index) != BLOCK:
                raise ValueError("short ProDOS sapling index")
            blocks = [index[i] | (index[i + 256] << 8) for i in range(count)]
        else:
            raise ValueError("unsupported storage for " + name)
        result = bytearray()
        for block in blocks:
            if not 0 < block < len(image) // BLOCK:
                raise ValueError("ProDOS file pointer outside image")
            result.extend(image[block * BLOCK:(block + 1) * BLOCK])
        return bytes(result[:length])
    raise ValueError("missing " + name)


def build_disk(template: bytes, program: bytes, overlays=()) -> bytes:
    """Make an 800 KiB .po with PRODOS and A2MONO.SYSTEM as first SYS."""
    if len(template) < 7 * BLOCK or len(template) % BLOCK:
        raise ValueError("expected a raw ProDOS-order template")
    if not program or len(program) > 0x9F00:
        raise ValueError("SYS exceeds the ProDOS load window")
    total, bitmap = 1600, 6
    image = bytearray(total * BLOCK)
    image[:2 * BLOCK] = template[:2 * BLOCK]
    for number in range(2, 6):
        struct.pack_into("<HH", image, number * BLOCK,
                         number - 1 if number > 2 else 0,
                         number + 1 if number < 5 else 0)
    files = [("PRODOS", extract(template, "PRODOS"), 0xFF, 0),
             ("A2MONO.SYSTEM", program, 0xFF, 0x2000)]
    files += [(name, payload, 0x06, 0x8B00) for name, payload in overlays]
    if len(files) > 12:
        raise ValueError("prototype root directory is full")
    header = bytearray(ENTRY)
    header[0:7] = b"\xF6A2MONO"
    stamp = (26 << 9) | (10 << 5) | 29
    struct.pack_into("<H", header, 24, stamp)
    header[28:33] = bytes((0, 0, 0xE3, ENTRY, 13))
    struct.pack_into("<HHH", header, 33, len(files), bitmap, total)
    image[2 * BLOCK + 4:2 * BLOCK + 43] = header
    next_block = 7
    for slot, (name, payload, filetype, aux) in enumerate(files, 1):
        count = max(1, math.ceil(len(payload) / BLOCK))
        if count > 256:
            raise ValueError("file exceeds sapling capacity")
        key = next_block
        next_block += count + (count > 1)
        first = key + (count > 1)
        if count > 1:
            for i in range(count):
                image[key * BLOCK + i] = (first + i) & 255
                image[key * BLOCK + 256 + i] = (first + i) >> 8
        image[first * BLOCK:first * BLOCK + len(payload)] = payload
        entry = bytearray(ENTRY)
        entry[0] = ((2 if count > 1 else 1) << 4) | len(name)
        entry[1:1 + len(name)] = name.encode("ascii")
        entry[16] = filetype
        struct.pack_into("<HH", entry, 17, key, count + (count > 1))
        entry[21:24] = len(payload).to_bytes(3, "little")
        struct.pack_into("<H", entry, 24, stamp)
        entry[30] = 0xE3
        struct.pack_into("<H", entry, 31, aux)
        struct.pack_into("<H", entry, 37, 2)
        at = 2 * BLOCK + 4 + slot * ENTRY
        image[at:at + ENTRY] = entry
    if next_block > total:
        raise ValueError("disk full")
    for block in range(next_block, total):
        image[bitmap * BLOCK + block // 8] |= 0x80 >> (block % 8)
    if extract(image, "A2MONO.SYSTEM") != program:
        raise ValueError("disk payload verification failed")
    return bytes(image)
