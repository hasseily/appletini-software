"""Read root files from raw ProDOS-order .po/.hdv images without modifying them.

This is a small independent reader, not a boot or filesystem emulator. Seedling,
sapling and tree files are supported, including sparse sapling/tree blocks.
Subdirectories and extended/resource-fork files are rejected explicitly. Logical
extraction is bounded to 256 MiB even when a small image contains sparse files.
"""

from __future__ import annotations

import os
from pathlib import Path
import re


BLOCK_SIZE = 512
ENTRY_SIZE = 39
ENTRIES_PER_BLOCK = 13
MAX_IMAGE_BYTES = 65536 * BLOCK_SIZE
MAX_EXTRACTED_BYTES = 256 * 1024 * 1024


class DiskError(ValueError):
    """An invalid image or a ProDOS feature this root-file reader cannot load."""


def _word(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "little")


def _name(entry: bytes, context: str) -> str:
    length = entry[0] & 15
    name = entry[1:1 + length]
    if not re.fullmatch(rb"[A-Za-z][A-Za-z0-9.]{0,14}", name):
        raise DiskError(f"{context}: invalid ProDOS name {name!r}")
    return name.decode("ascii")


class _Volume:
    def __init__(self, data: bytes):
        if len(data) % BLOCK_SIZE or not 3 * BLOCK_SIZE <= len(data) <= MAX_IMAGE_BYTES:
            raise DiskError("expected a raw ProDOS-order image of 3–65536 whole 512-byte blocks")
        self.data = data
        self.blocks = len(data) // BLOCK_SIZE
        first = self.block(2)
        header = first[4:4 + ENTRY_SIZE]
        if header[0] >> 4 != 15:
            raise DiskError("block 2 is not a ProDOS volume header (use a raw .po or .hdv image)")
        self.name = _name(header, "volume header")
        if header[31] != ENTRY_SIZE or header[32] != ENTRIES_PER_BLOCK:
            raise DiskError("volume header: expected 39-byte entries and 13 entries per block")
        total = _word(header, 37)
        if not 3 <= total <= self.blocks:
            raise DiskError(f"volume header: total blocks {total} exceeds image bounds or is invalid")
        # A raw 32 MiB image may have one unused block beyond ProDOS's 65535.
        self.blocks = total
        self.claimed = {0: "boot block", 1: "boot block"}
        bitmap = _word(header, 35)
        if bitmap < 3:
            raise DiskError("volume header: invalid allocation bitmap pointer")
        for number in range(bitmap, bitmap + (total + 4095) // 4096):
            self.claim(number, "allocation bitmap")
        self.entries: list[bytes] = []
        previous, number = 0, 2
        seen: set[int] = set()
        while number:
            if number in seen:
                raise DiskError(f"directory chain cycle at block {number}")
            seen.add(number)
            self.claim(number, "root directory")
            block = self.block(number)
            if _word(block, 0) != previous:
                raise DiskError(f"directory block {number}: invalid previous-block link")
            for index in range(1 if number == 2 else 0, ENTRIES_PER_BLOCK):
                start = 4 + index * ENTRY_SIZE
                entry = block[start:start + ENTRY_SIZE]
                if entry[0] >> 4:  # Deleted entries may retain their old name.
                    self.entries.append(entry)
            previous, number = number, _word(block, 2)
        if len(self.entries) != _word(header, 33):
            raise DiskError("volume header: file count does not match the root directory")

    def block(self, number: int) -> bytes:
        if not 0 <= number < self.blocks:
            raise DiskError(f"block {number} is outside volume bounds ({self.blocks} blocks)")
        return self.data[number * BLOCK_SIZE:(number + 1) * BLOCK_SIZE]

    def claim(self, number: int, owner: str) -> bytes:
        block = self.block(number)
        if number in self.claimed:
            raise DiskError(f"{owner}: block {number} overlaps {self.claimed[number]} (duplicate pointer or cycle)")
        self.claimed[number] = owner
        return block

    @staticmethod
    def pointers(index: bytes) -> list[int]:
        return [index[i] | (index[256 + i] << 8) for i in range(256)]

    def file(self, entry: bytes, name: str) -> bytes:
        storage = entry[0] >> 4
        if storage == 13:
            raise DiskError(f"{name}: subdirectories are not supported; this launcher loads root files only")
        if storage not in (1, 2, 3):
            raise DiskError(f"{name}: unsupported ProDOS storage type ${storage:X}")
        if _word(entry, 37) != 2:
            raise DiskError(f"{name}: file header does not point to the root directory")
        size = int.from_bytes(entry[21:24], "little")
        if size > {1: 512, 2: 256 * 512, 3: 0xFFFFFF}[storage]:
            raise DiskError(f"{name}: EOF exceeds storage type {storage} capacity")
        key = _word(entry, 17)
        before = len(self.claimed)
        if storage == 1:
            if key == 0 and size:
                raise DiskError(f"{name}: nonempty seedling has a zero data pointer")
            pointers = [key]
        else:
            if key == 0:
                raise DiskError(f"{name}: zero index pointer")
            index = self.claim(key, f"{name} index")
            pointers = self.pointers(index)
            if storage == 3:
                if any(pointers[128:]):
                    raise DiskError(f"{name}: tree master index exceeds maximum file size")
                data_pointers: list[int] = []
                for pointer in pointers[:128]:
                    if pointer:
                        branch = self.claim(pointer, f"{name} sapling index")
                        data_pointers.extend(self.pointers(branch))
                    else:
                        data_pointers.extend([0] * 256)
                pointers = data_pointers
        # Check all allocated pointers, including any blocks beyond EOF. This
        # also rejects data blocks that alias an index, directory or other file.
        for pointer in pointers:
            if pointer:
                self.claim(pointer, f"{name} data")
        allocated = len(self.claimed) - before
        if allocated != _word(entry, 19):
            raise DiskError(f"{name}: blocks-used count {_word(entry, 19)} does not match {allocated} allocated blocks")
        result = bytearray(size)
        for i, pointer in enumerate(pointers[:(size + 511) // 512]):
            if pointer:
                start = i * BLOCK_SIZE
                count = min(BLOCK_SIZE, size - start)
                result[start:start + count] = self.block(pointer)[:count]
        return bytes(result)


def read_disk(path: str | os.PathLike[str]) -> tuple[str, list[dict]]:
    """Return ``(volume_name, [{name, type, aux, data}, ...])`` in disk order.

    All root files, including PRODOS, are returned. Filesystem errors propagate
    as ``OSError``; malformed or unsupported volumes raise ``DiskError``.
    The source is opened only for reading. Container formats such as 2MG and
    nibble/DOS-order images are not accepted.
    """
    with Path(path).open("rb") as source:
        data = source.read(MAX_IMAGE_BYTES + 1)
    volume = _Volume(data)
    total_size = sum(int.from_bytes(entry[21:24], "little") for entry in volume.entries)
    if total_size > MAX_EXTRACTED_BYTES:
        raise DiskError(f"root files exceed the {MAX_EXTRACTED_BYTES // (1024 * 1024)} MiB extraction limit")
    files: list[dict] = []
    names: set[str] = set()
    for entry in volume.entries:
        name = _name(entry, "root file")
        if name.upper() in names:
            raise DiskError(f"duplicate root filename {name!r}")
        names.add(name.upper())
        files.append({"name": name, "type": entry[16], "aux": _word(entry, 31),
                      "data": volume.file(entry, name)})
    return volume.name, files
