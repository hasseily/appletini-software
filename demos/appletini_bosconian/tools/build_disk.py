#!/usr/bin/env python3
"""Build the bootable 800 KB ProDOS SmartPort image for Appletini Bosconian.

Pure Python, no Java or AppleCommander. The image is a plain block image
(1600 blocks of 512 bytes, ProDOS order):

  blocks 0-1   boot code copied from the master ProDOS_2_4_3.po
  blocks 2-5   volume directory A13BOSCO (4 blocks, linked)
  block  6     volume bitmap
  blocks 7..   PRODOS (SYS, aux $0000, extracted from the master image)
               and BOSCO.SYSTEM (SYS, aux $2000)

ProDOS boots, loads the PRODOS file, and runs the first *.SYSTEM file in
the volume directory, which is BOSCO.SYSTEM.

The master image comes from $APPLETINI_ROOT/software/ProDOS_2_4_3.po
(default ../../../appletini-one). After writing, the script re-reads its
own image with the reader below and compares every file byte for byte.

The reader (`list_volume`, `read_file`) is also importable so the smoke
test can check the disk it boots.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


BLOCK = 512
TOTAL_BLOCKS = 1600                 # 800 KB SmartPort volume
VOLUME_NAME = "A13BOSCO"
DIRECTORY_BLOCKS = (2, 3, 4, 5)
BITMAP_BLOCK = 6
FIRST_DATA_BLOCK = 7
ENTRY_LENGTH = 0x27
ENTRIES_PER_BLOCK = 0x0D
ACCESS_DEFAULT = 0xC3               # destroy, rename, write, read
FILE_TYPE_SYS = 0xFF
STORAGE_SEEDLING = 1
STORAGE_SAPLING = 2
STORAGE_TREE = 3
STORAGE_VOLUME_HEADER = 0xF

SOFTWARE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_APPLETINI_ROOT = SOFTWARE_ROOT.parent / "appletini-one"
APPLETINI_ROOT = Path(
    os.environ.get("APPLETINI_ROOT", str(DEFAULT_APPLETINI_ROOT))
).expanduser().resolve()
DEFAULT_MASTER = APPLETINI_ROOT / "software/ProDOS_2_4_3.po"

# DOS 3.3 sector order of the two halves of each ProDOS block (for .dsk)
DOS_SECTORS = ((0, 14), (13, 12), (11, 10), (9, 8), (7, 6), (5, 4), (3, 2), (1, 15))


class DiskError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
class Image:
    """Block access to a .po (block order) or .dsk (DOS order) image."""

    def __init__(self, data: bytes, dos_order: bool | None = None):
        self.data = data
        if len(data) % BLOCK:
            raise DiskError(f"image size {len(data)} is not a multiple of 512")
        self.blocks = len(data) // BLOCK
        if dos_order is None:
            dos_order = False
            if not self._looks_like_volume_directory(False) \
                    and self._looks_like_volume_directory(True):
                dos_order = True
        self.dos_order = dos_order

    def _looks_like_volume_directory(self, dos_order: bool) -> bool:
        if self.blocks <= 2:
            return False
        saved = getattr(self, "dos_order", False)
        self.dos_order = dos_order
        try:
            block = self.read(2)
        finally:
            self.dos_order = saved
        return (block[4] >> 4) == STORAGE_VOLUME_HEADER and 1 <= (block[4] & 0xF) <= 15

    def read(self, number: int) -> bytes:
        if not 0 <= number < self.blocks:
            raise DiskError(f"block {number} is outside the image ({self.blocks} blocks)")
        if not self.dos_order:
            return self.data[number * BLOCK:(number + 1) * BLOCK]
        track, index = divmod(number, 8)
        out = b""
        for sector in DOS_SECTORS[index]:
            offset = (track * 16 + sector) * 256
            out += self.data[offset:offset + 256]
        return out


def _u16(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def _u24(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16)


def parse_entry(entry: bytes) -> dict:
    storage = entry[0] >> 4
    name_length = entry[0] & 0x0F
    return {
        "storage": storage,
        "name": entry[1:1 + name_length].decode("ascii", errors="replace"),
        "file_type": entry[16],
        "key": _u16(entry, 17),
        "blocks_used": _u16(entry, 19),
        "eof": _u24(entry, 21),
        "creation": entry[24:28],
        "version": entry[28],
        "min_version": entry[29],
        "access": entry[30],
        "aux": _u16(entry, 31),
        "last_mod": entry[33:37],
        "header_pointer": _u16(entry, 37),
    }


def parse_volume_header(block: bytes) -> dict:
    head = block[4:4 + ENTRY_LENGTH]
    return {
        "storage": head[0] >> 4,
        "name": head[1:1 + (head[0] & 0x0F)].decode("ascii", errors="replace"),
        "creation": head[24:28],
        "version": head[28],
        "min_version": head[29],
        "access": head[30],
        "entry_length": head[31],
        "entries_per_block": head[32],
        "file_count": _u16(head, 33),
        "bitmap_pointer": _u16(head, 35),
        "total_blocks": _u16(head, 37),
    }


def list_volume(image: Image) -> tuple[dict, list[dict], list[int]]:
    """Walk the volume directory. Returns (header, entries, directory blocks)."""
    first = image.read(2)
    header = parse_volume_header(first)
    if header["storage"] != STORAGE_VOLUME_HEADER:
        raise DiskError("block 2 is not a ProDOS volume directory")
    entry_length = header["entry_length"] or ENTRY_LENGTH
    per_block = header["entries_per_block"] or ENTRIES_PER_BLOCK
    entries: list[dict] = []
    chain: list[int] = []
    number = 2
    seen: set[int] = set()
    while number:
        if number in seen:
            raise DiskError("directory block chain loops")
        seen.add(number)
        chain.append(number)
        block = image.read(number)
        start = 1 if number == 2 else 0
        for index in range(start, per_block):
            offset = 4 + index * entry_length
            raw = block[offset:offset + entry_length]
            if len(raw) < ENTRY_LENGTH or raw[0] == 0:
                continue
            entries.append(parse_entry(raw))
        number = _u16(block, 2)
    return header, entries, chain


def file_blocks(image: Image, entry: dict) -> tuple[list[int], list[int]]:
    """Return (index blocks, data block pointers in file order; 0 = sparse)."""
    storage, key = entry["storage"], entry["key"]
    if storage == STORAGE_SEEDLING:
        return [], [key]
    if storage == STORAGE_SAPLING:
        index = image.read(key)
        return [key], [index[i] | (index[256 + i] << 8) for i in range(256)]
    if storage == STORAGE_TREE:
        master = image.read(key)
        index_blocks = [key]
        data: list[int] = []
        for i in range(128):
            pointer = master[i] | (master[256 + i] << 8)
            if pointer == 0:
                data.extend([0] * 256)
                continue
            index_blocks.append(pointer)
            index = image.read(pointer)
            data.extend(index[j] | (index[256 + j] << 8) for j in range(256))
        return index_blocks, data
    raise DiskError(f"unsupported storage type {storage} for {entry['name']}")


def read_file(image: Image, entry: dict) -> bytes:
    _, pointers = file_blocks(image, entry)
    eof = entry["eof"]
    needed = (eof + BLOCK - 1) // BLOCK
    out = bytearray()
    for pointer in pointers[:needed]:
        out += image.read(pointer) if pointer else bytes(BLOCK)
    return bytes(out[:eof])


def find_entry(entries: list[dict], name: str) -> dict:
    for entry in entries:
        if entry["name"].upper() == name.upper():
            return entry
    raise DiskError(f"file {name} not found; have {[e['name'] for e in entries]}")


def extract_prodos(master_path: Path) -> tuple[bytes, bytes]:
    """Return (boot blocks 0-1, PRODOS file contents) from the master image."""
    master = Image(master_path.read_bytes())
    _, entries, _ = list_volume(master)
    entry = find_entry(entries, "PRODOS")
    if entry["file_type"] != FILE_TYPE_SYS:
        raise DiskError(f"master PRODOS has file type ${entry['file_type']:02X}, not SYS")
    prodos = read_file(master, entry)
    if len(prodos) < 8 * 1024:
        raise DiskError(f"master PRODOS is only {len(prodos)} bytes")
    boot = master.read(0) + master.read(1)
    return boot, prodos


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------
def encode_name(name: str) -> bytes:
    name = name.upper()
    if not 1 <= len(name) <= 15 or not name[0].isalpha() \
            or any(not (c.isalnum() or c == ".") for c in name):
        raise DiskError(f"invalid ProDOS name {name!r}")
    return name.encode("ascii")


class VolumeWriter:
    def __init__(self, volume_name: str = VOLUME_NAME, total_blocks: int = TOTAL_BLOCKS):
        self.total_blocks = total_blocks
        self.image = bytearray(total_blocks * BLOCK)
        self.used = [False] * total_blocks
        for number in (0, 1, *DIRECTORY_BLOCKS, BITMAP_BLOCK):
            self.used[number] = True
        self.next_free = FIRST_DATA_BLOCK
        self.volume_name = encode_name(volume_name)
        self.entries: list[bytes] = []

    def _alloc(self) -> int:
        while self.next_free < self.total_blocks and self.used[self.next_free]:
            self.next_free += 1
        if self.next_free >= self.total_blocks:
            raise DiskError("volume is full")
        number = self.next_free
        self.used[number] = True
        self.next_free += 1
        return number

    def _write_block(self, number: int, data: bytes) -> None:
        if len(data) > BLOCK:
            raise DiskError("block data too long")
        self.image[number * BLOCK:number * BLOCK + len(data)] = data

    def set_boot_blocks(self, boot: bytes) -> None:
        if len(boot) != 2 * BLOCK:
            raise DiskError("boot code must be exactly two blocks")
        self._write_block(0, boot[:BLOCK])
        self._write_block(1, boot[BLOCK:])

    def add_file(self, name: str, data: bytes, file_type: int, aux: int) -> dict:
        if len(self.entries) >= (ENTRIES_PER_BLOCK - 1) + ENTRIES_PER_BLOCK * 3:
            raise DiskError("volume directory is full")
        if not data:
            raise DiskError(f"{name}: empty files are not supported")
        # Allocate like ProDOS does: index block first, then its data blocks.
        # No sparse blocks: every block is written.
        chunks = [data[offset:offset + BLOCK] for offset in range(0, len(data), BLOCK)]
        data_blocks: list[int] = []
        index_blocks: list[int] = []
        if len(chunks) == 1:
            storage = STORAGE_SEEDLING
            key = self._alloc()
            self._write_block(key, chunks[0])
            data_blocks.append(key)
        elif len(chunks) <= 256:
            storage = STORAGE_SAPLING
            key = self._alloc()
            index_blocks.append(key)
            data_blocks = self._write_data(chunks)
            self._write_index(key, data_blocks)
        elif len(chunks) <= 256 * 128:
            storage = STORAGE_TREE
            key = self._alloc()
            index_blocks.append(key)
            subindex: list[int] = []
            for start in range(0, len(chunks), 256):
                number = self._alloc()
                index_blocks.append(number)
                subindex.append(number)
                group = self._write_data(chunks[start:start + 256])
                data_blocks.extend(group)
                self._write_index(number, group)
            self._write_index(key, subindex)
        else:
            raise DiskError(f"{name}: file too large")
        entry = bytearray(ENTRY_LENGTH)
        encoded = encode_name(name)
        entry[0] = (storage << 4) | len(encoded)
        entry[1:1 + len(encoded)] = encoded
        entry[16] = file_type
        entry[17:19] = key.to_bytes(2, "little")
        blocks_used = len(data_blocks) + len(index_blocks)
        entry[19:21] = blocks_used.to_bytes(2, "little")
        entry[21:24] = len(data).to_bytes(3, "little")
        # creation date/time 24..27 = 0, version 28 = 0, min_version 29 = 0
        entry[30] = ACCESS_DEFAULT
        entry[31:33] = aux.to_bytes(2, "little")
        # last mod 33..36 = 0
        entry[37:39] = (2).to_bytes(2, "little")   # header pointer: key block
        self.entries.append(bytes(entry))
        return {"name": name, "storage": storage, "key": key,
                "blocks_used": blocks_used, "eof": len(data),
                "data_blocks": data_blocks, "index_blocks": index_blocks}

    def _write_data(self, chunks: list[bytes]) -> list[int]:
        numbers = []
        for chunk in chunks:
            number = self._alloc()
            self._write_block(number, chunk)
            numbers.append(number)
        return numbers

    def _write_index(self, number: int, pointers: list[int]) -> None:
        block = bytearray(BLOCK)
        for i, pointer in enumerate(pointers):
            block[i] = pointer & 0xFF
            block[256 + i] = pointer >> 8
        self._write_block(number, block)

    def finish(self) -> bytes:
        # directory blocks
        entries = list(self.entries)
        for position, number in enumerate(DIRECTORY_BLOCKS):
            block = bytearray(BLOCK)
            prev = DIRECTORY_BLOCKS[position - 1] if position else 0
            nxt = DIRECTORY_BLOCKS[position + 1] if position + 1 < len(DIRECTORY_BLOCKS) else 0
            block[0:2] = prev.to_bytes(2, "little")
            block[2:4] = nxt.to_bytes(2, "little")
            first = 0
            if position == 0:
                head = bytearray(ENTRY_LENGTH)
                head[0] = (STORAGE_VOLUME_HEADER << 4) | len(self.volume_name)
                head[1:1 + len(self.volume_name)] = self.volume_name
                # reserved 16..23 = 0, creation 24..27 = 0, version 28 = 0,
                # min_version 29 = 0
                head[30] = ACCESS_DEFAULT
                head[31] = ENTRY_LENGTH
                head[32] = ENTRIES_PER_BLOCK
                head[33:35] = len(self.entries).to_bytes(2, "little")
                head[35:37] = BITMAP_BLOCK.to_bytes(2, "little")
                head[37:39] = self.total_blocks.to_bytes(2, "little")
                block[4:4 + ENTRY_LENGTH] = head
                first = 1
            for index in range(first, ENTRIES_PER_BLOCK):
                if not entries:
                    break
                offset = 4 + index * ENTRY_LENGTH
                block[offset:offset + ENTRY_LENGTH] = entries.pop(0)
            self._write_block(number, block)
        if entries:
            raise DiskError("directory overflow")
        # bitmap: bit set = free, block i -> byte i//8, bit 7 - i%8
        bitmap = bytearray(BLOCK)
        for number in range(self.total_blocks):
            if not self.used[number]:
                bitmap[number // 8] |= 0x80 >> (number % 8)
        self._write_block(BITMAP_BLOCK, bitmap)
        return bytes(self.image)


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------
def verify_image(data: bytes, expected: dict[str, tuple[int, int, bytes]]) -> list[str]:
    """Check the image against the files it should contain; return notes."""
    image = Image(data, dos_order=False)
    header, entries, chain = list_volume(image)
    notes = []
    if header["name"] != VOLUME_NAME:
        raise DiskError(f"volume name is {header['name']!r}")
    if header["total_blocks"] != TOTAL_BLOCKS or header["bitmap_pointer"] != BITMAP_BLOCK:
        raise DiskError("volume header geometry is wrong")
    if header["file_count"] != len(entries) or len(entries) != len(expected):
        raise DiskError(f"file count {header['file_count']} != {len(entries)} entries")
    if list(chain) != list(DIRECTORY_BLOCKS):
        raise DiskError(f"directory chain is {chain}")
    used: set[int] = {0, 1, BITMAP_BLOCK, *DIRECTORY_BLOCKS}
    for entry in entries:
        name = entry["name"]
        if name not in expected:
            raise DiskError(f"unexpected file {name}")
        file_type, aux, contents = expected[name]
        if entry["file_type"] != file_type or entry["aux"] != aux:
            raise DiskError(f"{name}: type ${entry['file_type']:02X} aux ${entry['aux']:04X}")
        if entry["header_pointer"] != 2 or entry["access"] != ACCESS_DEFAULT:
            raise DiskError(f"{name}: bad header pointer or access")
        index_blocks, pointers = file_blocks(image, entry)
        data_used = [p for p in pointers if p]
        if entry["blocks_used"] != len(index_blocks) + len(data_used):
            raise DiskError(f"{name}: blocks_used {entry['blocks_used']} != "
                            f"{len(index_blocks)} index + {len(data_used)} data")
        for number in index_blocks + data_used:
            if number in used:
                raise DiskError(f"{name}: block {number} used twice")
            used.add(number)
        if read_file(image, entry) != contents:
            raise DiskError(f"{name}: read back does not match")
        notes.append(f"{name:16s} type ${file_type:02X} aux ${aux:04X} "
                     f"{len(contents):7d} bytes storage {entry['storage']} "
                     f"key {entry['key']} blocks {entry['blocks_used']}")
    bitmap = image.read(BITMAP_BLOCK)
    for number in range(TOTAL_BLOCKS):
        free = bool(bitmap[number // 8] & (0x80 >> (number % 8)))
        if free == (number in used):
            raise DiskError(f"bitmap disagrees about block {number}")
    if any(bitmap[TOTAL_BLOCKS // 8:]):
        raise DiskError("bitmap marks blocks beyond the volume as free")
    return notes


# ---------------------------------------------------------------------------
def build(system: bytes, master: Path, output: Path,
          system_name: str = "BOSCO.SYSTEM") -> list[str]:
    boot, prodos = extract_prodos(master)
    writer = VolumeWriter()
    writer.set_boot_blocks(boot)
    writer.add_file("PRODOS", prodos, FILE_TYPE_SYS, 0x0000)
    writer.add_file(system_name, system, FILE_TYPE_SYS, 0x2000)
    data = writer.finish()
    notes = verify_image(data, {
        "PRODOS": (FILE_TYPE_SYS, 0x0000, prodos),
        system_name.upper(): (FILE_TYPE_SYS, 0x2000, system),
    })
    if data[:2 * BLOCK] != boot:
        raise DiskError("boot block copy failed")
    if len(data) != TOTAL_BLOCKS * BLOCK:
        raise DiskError("image size is wrong")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--system", type=Path, required=True,
                        help="linked $2000 SYS program (build/BOSCO.SYSTEM)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER,
                        help="ProDOS master image (boot blocks and PRODOS file)")
    parser.add_argument("--name", default="BOSCO.SYSTEM")
    args = parser.parse_args()

    for path, what in ((args.system, "system program"), (args.master, "ProDOS master")):
        if not path.is_file():
            raise SystemExit(f"missing {what}: {path}")
    system = args.system.read_bytes()
    if len(system) < 16 or 0x2000 + len(system) > 0xB000:
        raise SystemExit(f"system program has an unusable size: {len(system)} bytes")
    try:
        notes = build(system, args.master, args.output, args.name)
    except DiskError as error:
        raise SystemExit(f"disk build failed: {error}")
    for note in notes:
        print("  " + note)
    print(f"built {args.output} ({args.output.stat().st_size} bytes, "
          f"{TOTAL_BLOCKS} blocks, volume {VOLUME_NAME})")


if __name__ == "__main__":
    main()
