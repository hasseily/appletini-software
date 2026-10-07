"""ref816 memory images: read, and a sparse memory to load them into.

An image (main.c, make_image.py) is a 32-byte header, "REF816I1" then
the registers and the soft switches, then records: a 32-bit address, a
32-bit length and the bytes, all little-endian. footprint.c writes its
reads and writes images in the same format (footprint.h).
"""

import struct
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple, Union

from ref816 import make_image

MAGIC = make_image.MAGIC
HEADER = make_image.HEADER_SIZE
BANK = 0x10000
Registers = make_image.Registers
HEADER_FORMAT = '<HBBHHHHHBB4B'


class Switches(NamedTuple):
    newvideo: int
    border: int
    shadow: int
    speed: int


class Image(NamedTuple):
    registers: Registers
    switches: Switches
    records: List[Tuple[int, bytes]]


def parse(data: bytes) -> Image:
    if len(data) < HEADER or data[:len(MAGIC)] != MAGIC:
        raise ValueError('not a ref816 memory image')
    fields = struct.unpack_from(HEADER_FORMAT, data, len(MAGIC))
    registers = Registers(pc=fields[0], pbr=fields[1], dbr=fields[2],
                          a=fields[3], x=fields[4], y=fields[5], s=fields[6],
                          d=fields[7], p=fields[8], e=fields[9])
    switches = Switches(*fields[10:14])
    records = []
    at = HEADER
    while at < len(data):
        if len(data) - at < 8:
            raise ValueError('a record is cut short')
        address, length = struct.unpack_from('<II', data, at)
        at += 8
        if length > len(data) - at:
            raise ValueError('the record at $%06X is cut short' % address)
        records.append((address, bytes(data[at:at + length])))
        at += length
    return Image(registers, switches, records)


def read(path: Union[str, Path]) -> Image:
    return parse(Path(path).read_bytes())


class Memory:
    """Bytes at 24-bit addresses, with which of them are known."""

    def __init__(self, records: Iterable[Tuple[int, bytes]] = ()):
        self.banks: Dict[int, bytearray] = {}
        self.known: Dict[int, bytearray] = {}
        for address, data in records:
            self.put(address, data)

    def put(self, address: int, data: bytes) -> None:
        at = 0
        while at < len(data):
            bank, offset = (address + at) >> 16, (address + at) & 0xffff
            count = min(len(data) - at, BANK - offset)
            if bank not in self.banks:
                self.banks[bank] = bytearray(BANK)
                self.known[bank] = bytearray(BANK)
            self.banks[bank][offset:offset + count] = data[at:at + count]
            self.known[bank][offset:offset + count] = b'\1' * count
            at += count

    def get(self, address: int, length: int) -> bytes:
        """The bytes (0 where not known)."""
        out = bytearray()
        at = 0
        while at < length:
            bank, offset = (address + at) >> 16, (address + at) & 0xffff
            count = min(length - at, BANK - offset)
            data = self.banks.get(bank)
            out += data[offset:offset + count] if data else bytes(count)
            at += count
        return bytes(out)


def load(image: Image, memory: Optional[Memory] = None) -> Memory:
    memory = memory if memory is not None else Memory()
    for address, data in image.records:
        memory.put(address, data)
    return memory
