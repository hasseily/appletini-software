#!/usr/bin/env python3
"""Write a bootable ProDOS volume image (.hdv, 512-byte blocks, ProDOS order).

Usage:
  python3 tools/mkdisk.py -o MUSIC.hdv -v MUSIC -m assets/ProDOS_2_4_3.po \\
      FILE,TYPE,AUX [FILE,TYPE,AUX ...]

Each FILE goes on the volume under its own name (upper case), with the
ProDOS file type TYPE (SYS, BIN, TXT or a hex number) and the auxiliary
type AUX (hex). The boot blocks and the PRODOS file come from the master
image (-m); PRODOS is placed second in the directory, after the first
file, which is the .SYSTEM program ProDOS runs at boot. A TXT file's line
ends are written as carriage returns.

The volume is sized to its files plus 64 free blocks. The image is read
back and checked file by file before it is written. Python 3 standard
library only.
"""

import argparse
import sys
from pathlib import Path

BLOCK = 512
MAX_BLOCKS = 0xFFFF
DIRECTORY_BLOCKS = (2, 3, 4, 5)
FIRST_BITMAP_BLOCK = 6
BLOCKS_PER_BITMAP = BLOCK * 8
ENTRY_LENGTH = 0x27
ENTRIES_PER_BLOCK = 0x0D
MAX_ENTRIES = ENTRIES_PER_BLOCK * len(DIRECTORY_BLOCKS) - 1     # 51
FREE_BLOCKS = 64
ACCESS_DEFAULT = 0xC3               # destroy, rename, write, read
SEEDLING, SAPLING, TREE, VOLUME_HEADER = 1, 2, 3, 0xF
TYPES = {'SYS': 0xFF, 'BIN': 0x06, 'TXT': 0x04}


class DiskError(RuntimeError):
    pass


def u16(data, offset):
    return data[offset] | (data[offset + 1] << 8)


# ---------------------------------------------------------------------------
# reading (the master image, and the check of the new one)
# ---------------------------------------------------------------------------

def block(image, number):
    if not 0 <= number < len(image) // BLOCK:
        raise DiskError('block %d is outside the image' % number)
    return image[number * BLOCK:(number + 1) * BLOCK]


def list_volume(image):
    """(volume name, total blocks, [entry dicts]) of a ProDOS-order image."""
    first = block(image, 2)
    head = first[4:4 + ENTRY_LENGTH]
    if head[0] >> 4 != VOLUME_HEADER:
        raise DiskError('block 2 is not a ProDOS volume directory')
    name = head[1:1 + (head[0] & 0xF)].decode('ascii')
    entries, number, seen = [], 2, set()
    while number:
        if number in seen:
            raise DiskError('the directory chain loops')
        seen.add(number)
        data = block(image, number)
        for index in range(1 if number == 2 else 0, ENTRIES_PER_BLOCK):
            raw = data[4 + index * ENTRY_LENGTH:4 + (index + 1) * ENTRY_LENGTH]
            if raw[0]:
                entries.append({
                    'storage': raw[0] >> 4,
                    'name': raw[1:1 + (raw[0] & 0xF)].decode('ascii'),
                    'type': raw[16], 'key': u16(raw, 17),
                    'eof': raw[21] | (raw[22] << 8) | (raw[23] << 16),
                    'aux': u16(raw, 31)})
        number = u16(data, 2)
    return name, u16(head, 37), entries


def read_file(image, entry):
    storage, key = entry['storage'], entry['key']
    if storage == SEEDLING:
        pointers = [key]
    elif storage == SAPLING:
        index = block(image, key)
        pointers = [index[i] | (index[256 + i] << 8) for i in range(256)]
    elif storage == TREE:
        master = block(image, key)
        pointers = []
        for i in range(128):
            sub = master[i] | (master[256 + i] << 8)
            if not sub:
                pointers += [0] * 256
                continue
            index = block(image, sub)
            pointers += [index[j] | (index[256 + j] << 8) for j in range(256)]
    else:
        raise DiskError('%s: storage type %d' % (entry['name'], storage))
    out = bytearray()
    for pointer in pointers[:(entry['eof'] + BLOCK - 1) // BLOCK]:
        out += block(image, pointer) if pointer else bytes(BLOCK)
    return bytes(out[:entry['eof']])


def extract_prodos(master_path):
    """(boot blocks 0-1, the PRODOS file) of the master image."""
    image = Path(master_path).read_bytes()
    for entry in list_volume(image)[2]:
        if entry['name'] == 'PRODOS' and entry['type'] == TYPES['SYS']:
            return image[:2 * BLOCK], read_file(image, entry)
    raise DiskError('%s holds no PRODOS system file' % master_path)


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------

def encode_name(name):
    name = name.upper()
    if not 1 <= len(name) <= 15 or not name[0].isalpha() \
            or any(not (c.isalnum() or c == '.') for c in name):
        raise DiskError('invalid ProDOS name %r' % name)
    return name.encode('ascii')


def file_block_count(size):
    data = max(1, (size + BLOCK - 1) // BLOCK)
    if data == 1:
        return 1
    if data <= 256:
        return data + 1
    return data + 1 + (data + 255) // 256


def bitmap_blocks(total):
    return (total + BLOCKS_PER_BITMAP - 1) // BLOCKS_PER_BITMAP


def volume_size(sizes):
    """The smallest volume holding files of these sizes plus FREE_BLOCKS."""
    used = FIRST_BITMAP_BLOCK + sum(file_block_count(s) for s in sizes) + \
        FREE_BLOCKS
    total = used + bitmap_blocks(used)
    total += bitmap_blocks(total) - bitmap_blocks(used)
    if total > MAX_BLOCKS:
        raise DiskError('the files need %d blocks' % total)
    return max(280, total)


class Volume:
    def __init__(self, name, total):
        self.name = encode_name(name)
        self.total = total
        self.bitmap = tuple(range(FIRST_BITMAP_BLOCK,
                                  FIRST_BITMAP_BLOCK + bitmap_blocks(total)))
        self.image = bytearray(total * BLOCK)
        self.used = [False] * total
        for number in (0, 1) + DIRECTORY_BLOCKS + self.bitmap:
            self.used[number] = True
        self.next_free = self.bitmap[-1] + 1
        self.entries = []

    def alloc(self):
        while self.next_free < self.total and self.used[self.next_free]:
            self.next_free += 1
        if self.next_free >= self.total:
            raise DiskError('the volume is full')
        self.used[self.next_free] = True
        self.next_free += 1
        return self.next_free - 1

    def put(self, number, data):
        self.image[number * BLOCK:number * BLOCK + len(data)] = data

    def put_index(self, number, pointers):
        index = bytearray(BLOCK)
        for i, pointer in enumerate(pointers):
            index[i], index[256 + i] = pointer & 0xFF, pointer >> 8
        self.put(number, index)

    def put_data(self, chunks):
        numbers = []
        for chunk in chunks:
            numbers.append(self.alloc())
            self.put(numbers[-1], chunk)
        return numbers

    def add_file(self, name, data, file_type, aux):
        """Allocated as ProDOS does: the index block, then its data blocks."""
        if len(self.entries) >= MAX_ENTRIES:
            raise DiskError('the volume directory is full')
        if not data:
            raise DiskError('%s is empty' % name)
        chunks = [data[i:i + BLOCK] for i in range(0, len(data), BLOCK)]
        key = self.alloc()
        if len(chunks) == 1:
            storage, count = SEEDLING, 1
            self.put(key, chunks[0])
        elif len(chunks) <= 256:
            storage, count = SAPLING, 1 + len(chunks)
            self.put_index(key, self.put_data(chunks))
        elif len(chunks) <= 256 * 128:
            storage, count, subindex = TREE, 1, []
            for start in range(0, len(chunks), 256):
                subindex.append(self.alloc())
                group = self.put_data(chunks[start:start + 256])
                self.put_index(subindex[-1], group)
                count += 1 + len(group)
            self.put_index(key, subindex)
        else:
            raise DiskError('%s is too large' % name)
        encoded = encode_name(name)
        entry = bytearray(ENTRY_LENGTH)
        entry[0] = (storage << 4) | len(encoded)
        entry[1:1 + len(encoded)] = encoded
        entry[16] = file_type
        entry[17:19] = key.to_bytes(2, 'little')
        entry[19:21] = count.to_bytes(2, 'little')
        entry[21:24] = len(data).to_bytes(3, 'little')
        entry[30] = ACCESS_DEFAULT
        entry[31:33] = aux.to_bytes(2, 'little')
        entry[37:39] = (2).to_bytes(2, 'little')    # the header's block
        self.entries.append(bytes(entry))

    def finish(self):
        entries = list(self.entries)
        for position, number in enumerate(DIRECTORY_BLOCKS):
            data = bytearray(BLOCK)
            prev = DIRECTORY_BLOCKS[position - 1] if position else 0
            nxt = DIRECTORY_BLOCKS[position + 1] \
                if position + 1 < len(DIRECTORY_BLOCKS) else 0
            data[0:2] = prev.to_bytes(2, 'little')
            data[2:4] = nxt.to_bytes(2, 'little')
            first = 0
            if position == 0:
                head = bytearray(ENTRY_LENGTH)
                head[0] = (VOLUME_HEADER << 4) | len(self.name)
                head[1:1 + len(self.name)] = self.name
                head[30] = ACCESS_DEFAULT
                head[31] = ENTRY_LENGTH
                head[32] = ENTRIES_PER_BLOCK
                head[33:35] = len(self.entries).to_bytes(2, 'little')
                head[35:37] = FIRST_BITMAP_BLOCK.to_bytes(2, 'little')
                head[37:39] = self.total.to_bytes(2, 'little')
                data[4:4 + ENTRY_LENGTH] = head
                first = 1
            for index in range(first, ENTRIES_PER_BLOCK):
                if not entries:
                    break
                offset = 4 + index * ENTRY_LENGTH
                data[offset:offset + ENTRY_LENGTH] = entries.pop(0)
            self.put(number, data)
        # the bitmap: a set bit is a free block, block n is bit 7 - n % 8
        # of byte n // 8
        bitmap = bytearray(len(self.bitmap) * BLOCK)
        for number in range(self.total):
            if not self.used[number]:
                bitmap[number // 8] |= 0x80 >> (number % 8)
        for index, number in enumerate(self.bitmap):
            self.put(number, bitmap[index * BLOCK:(index + 1) * BLOCK])
        return bytes(self.image)


def parse_file(spec):
    """FILE,TYPE,AUX -> (ProDOS name, type, aux, bytes)."""
    try:
        path, kind, aux = spec.rsplit(',', 2)
        file_type = TYPES.get(kind.upper())
        if file_type is None:
            file_type = int(kind, 16)
        aux = int(aux, 16)
    except ValueError:
        raise DiskError('%r: expected FILE,TYPE,AUX' % spec)
    data = Path(path).read_bytes()
    if file_type == TYPES['TXT']:
        data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r')
    return Path(path).name.upper(), file_type, aux, data


def build(volume, master, specs):
    boot, prodos = extract_prodos(master)
    files = [parse_file(spec) for spec in specs]
    if not files:
        raise DiskError('no files')
    files.insert(1, ('PRODOS', TYPES['SYS'], 0x0000, prodos))
    names = [f[0] for f in files]
    if len(set(names)) != len(names):
        raise DiskError('two files have the same name')
    disk = Volume(volume, volume_size([len(f[3]) for f in files]))
    disk.put(0, boot)
    for name, file_type, aux, data in files:
        disk.add_file(name, data, file_type, aux)
    image = disk.finish()
    # the check: the directory reads back with every file, byte for byte
    name, total, entries = list_volume(image)
    if name != volume.upper() or total * BLOCK != len(image):
        raise DiskError('the volume header reads back wrong')
    if [(e['name'], e['type'], e['aux']) for e in entries] != \
            [f[:3] for f in files]:
        raise DiskError('the directory reads back wrong')
    for entry, f in zip(entries, files):
        if read_file(image, entry) != f[3]:
            raise DiskError('%s reads back wrong' % f[0])
    return image, files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('-o', '--output', required=True, type=Path)
    parser.add_argument('-v', '--volume', required=True)
    parser.add_argument('-m', '--master', required=True, type=Path,
                        help='a ProDOS image: its boot blocks and PRODOS')
    parser.add_argument('files', nargs='+', metavar='FILE,TYPE,AUX')
    args = parser.parse_args(argv)
    try:
        image, files = build(args.volume, args.master, args.files)
    except (DiskError, OSError) as error:
        print('mkdisk: %s' % error, file=sys.stderr)
        return 1
    args.output.write_bytes(image)
    print('%s: %d blocks, volume %s' % (args.output, len(image) // BLOCK,
                                        args.volume.upper()))
    for name, file_type, aux, data in files:
        print('  %-15s $%02X $%04X %6d bytes' % (name, file_type, aux,
                                                  len(data)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
