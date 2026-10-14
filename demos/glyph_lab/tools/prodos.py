#!/usr/bin/env python3
"""Minimal ProDOS block-image reader and writer (no external tools).

read_file() exports one file from the root directory of a ProDOS-order
image. build_image() makes a bootable volume: the boot blocks come from a
master image, files are stored as seedling, sapling or tree files.
"""

from pathlib import Path

BLOCK = 512
ENTRY_LENGTH = 0x27
ENTRIES_PER_BLOCK = 0x0D
TYPE_BIN, TYPE_SYS = 0x06, 0xFF


def _block(image, number):
    return image[number * BLOCK:(number + 1) * BLOCK]


def _word(data, offset):
    return data[offset] | (data[offset + 1] << 8)


def read_file(image_path, name):
    image = Path(image_path).read_bytes()
    block = 2
    while block:
        data = _block(image, block)
        for index in range(ENTRIES_PER_BLOCK):
            entry = data[4 + index * ENTRY_LENGTH:4 + (index + 1) * ENTRY_LENGTH]
            storage, length = entry[0] >> 4, entry[0] & 15
            if storage not in (1, 2, 3):
                continue
            if entry[1:1 + length].decode("ascii") != name:
                continue
            key = _word(entry, 0x11)
            eof = entry[0x15] | (entry[0x16] << 8) | (entry[0x17] << 16)
            if storage == 1:
                blocks = [key]
            else:
                def index_list(number):
                    raw = _block(image, number)
                    return [raw[i] | (raw[256 + i] << 8) for i in range(256)]
                if storage == 2:
                    blocks = index_list(key)
                else:
                    blocks = [b for master in index_list(key) if master
                              for b in index_list(master)]
            out = b"".join(_block(image, b) if b else bytes(BLOCK)
                           for b in blocks)
            return out[:eof]
        block = _word(data, 2)
    raise FileNotFoundError(name)


def build_image(path, volume, master_path, files, total_blocks=1600):
    """files: list of (name, type, aux type, data)."""
    image = bytearray(total_blocks * BLOCK)
    master = Path(master_path).read_bytes()
    image[0:2 * BLOCK] = master[0:2 * BLOCK]
    bitmap_block = 6
    next_free = [bitmap_block + (total_blocks + 4095) // 4096]

    def allocate():
        number = next_free[0]
        next_free[0] += 1
        if number >= total_blocks:
            raise ValueError("volume is full")
        return number

    def put(number, data):
        image[number * BLOCK:number * BLOCK + len(data)] = data

    def index_block(numbers):
        raw = bytearray(BLOCK)
        for i, number in enumerate(numbers):
            raw[i] = number & 255
            raw[256 + i] = number >> 8
        return raw

    entries = []
    for name, file_type, aux_type, data in files:
        if not 1 <= len(name) <= 15:
            raise ValueError("ProDOS names hold 1 to 15 characters: %s" % name)
        count = max(1, (len(data) + BLOCK - 1) // BLOCK)
        if count == 1:
            storage, key = 1, allocate()
            put(key, data)
            used = 1
        elif count <= 256:
            storage, key = 2, allocate()
            numbers = [allocate() for _ in range(count)]
            put(key, index_block(numbers))
            used = count + 1
        else:
            storage, key = 3, allocate()
            masters, numbers, used = [], [], 1
            for start in range(0, count, 256):
                masters.append(allocate())
                used += 1
            for m, start in zip(masters, range(0, count, 256)):
                part = [allocate() for _ in range(min(256, count - start))]
                put(m, index_block(part))
                numbers.extend(part)
                used += len(part)
            put(key, index_block(masters))
        if count > 1:
            for i, number in enumerate(numbers):
                put(number, data[i * BLOCK:(i + 1) * BLOCK])
        entry = bytearray(ENTRY_LENGTH)
        entry[0] = (storage << 4) | len(name)
        entry[1:1 + len(name)] = name.encode("ascii")
        entry[0x10] = file_type
        entry[0x11], entry[0x12] = key & 255, key >> 8
        entry[0x13], entry[0x14] = used & 255, used >> 8
        entry[0x15] = len(data) & 255
        entry[0x16] = (len(data) >> 8) & 255
        entry[0x17] = len(data) >> 16
        entry[0x1E] = 0xE3                      # access: unlocked
        entry[0x1F], entry[0x20] = aux_type & 255, aux_type >> 8
        entry[0x25], entry[0x26] = 2, 0         # header pointer
        entries.append(entry)

    # Volume directory: blocks 2-5.
    for number in range(2, 6):
        raw = bytearray(BLOCK)
        previous = number - 1 if number > 2 else 0
        following = number + 1 if number < 5 else 0
        raw[0], raw[1] = previous & 255, previous >> 8
        raw[2], raw[3] = following & 255, following >> 8
        put(number, raw)
    header = bytearray(ENTRY_LENGTH)
    header[0] = 0xF0 | len(volume)
    header[1:1 + len(volume)] = volume.encode("ascii")
    header[0x1E] = 0xC3
    header[0x1F] = ENTRY_LENGTH
    header[0x20] = ENTRIES_PER_BLOCK
    header[0x21], header[0x22] = len(entries) & 255, len(entries) >> 8
    header[0x23], header[0x24] = bitmap_block & 255, bitmap_block >> 8
    header[0x25], header[0x26] = total_blocks & 255, total_blocks >> 8
    slots = [header] + entries
    for position, entry in enumerate(slots):
        number = 2 + position // ENTRIES_PER_BLOCK
        offset = 4 + (position % ENTRIES_PER_BLOCK) * ENTRY_LENGTH
        start = number * BLOCK + offset
        image[start:start + ENTRY_LENGTH] = entry

    # Volume bitmap: one bit per block, 1 = free, most significant bit first.
    bits = bytearray((total_blocks + 7) // 8)
    for number in range(next_free[0], total_blocks):
        bits[number >> 3] |= 0x80 >> (number & 7)
    put(bitmap_block, bits)
    Path(path).write_bytes(image)
    return next_free[0]
