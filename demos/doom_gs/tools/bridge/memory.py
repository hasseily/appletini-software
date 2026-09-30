"""Memories the bridge reads and writes.

`Memory` is upstream's: 24-bit addresses, 64 KB banks, from a ref816
memory image (`tools/ref816/refimage.py`: a capture's entry.img) or a
`--dump-ram` file (banks $00-$7F, then $E0 and $E1). Bytes of no record
read 0.

`PortMemory` is the port's machine as a2vm sees it: main memory and the
128 RamWorks banks (aux 0 is the //e's auxiliary 64 KB). An address is
an int: `MAIN | offset` for main memory, `bank << 16 | offset` for aux
bank `bank` (0-127). It writes a2vm `--image` files (A2VMIMG1) and reads
a2vm snapshots (`NAME.ram`: main 64 KB, main LC 16 KB, main LC bank 1
4 KB, then the 128 aux banks; tools/a2vm/README.md).
"""

import struct
from pathlib import Path
from typing import Dict, Iterable, Iterator, Tuple

BANK = 0x10000


class Memory:
    """Upstream's RAM: banks of 64 KB, created when written."""

    def __init__(self):
        self.banks: Dict[int, bytearray] = {}

    @classmethod
    def from_records(cls, records: Iterable[Tuple[int, bytes]]
                     ) -> 'Memory':
        m = cls()
        for address, data in records:
            m.write(address, data)
        return m

    @classmethod
    def from_image(cls, path: Path) -> 'Memory':
        """A ref816 memory image (REF816I1): header, then records."""
        data = Path(path).read_bytes()
        if data[:8] != b'REF816I1':
            raise ValueError('%s: not a ref816 memory image' % path)
        m = cls()
        m.header = data[:32]
        at = 32
        while at < len(data):
            address, length = struct.unpack_from('<II', data, at)
            at += 8
            m.write(address, data[at:at + length])
            at += length
        return m

    @classmethod
    def from_dump(cls, path: Path) -> 'Memory':
        """A ref816 --dump-ram file: banks $00-$7F, $E0, $E1."""
        data = Path(path).read_bytes()
        if len(data) != 130 * BANK:
            raise ValueError('%s: %d bytes, not a RAM dump' % (path,
                                                               len(data)))
        m = cls()
        for i in range(130):
            bank = i if i < 0x80 else 0xe0 + i - 0x80
            m.banks[bank] = bytearray(data[i * BANK:(i + 1) * BANK])
        return m

    header = b''

    def copy(self) -> 'Memory':
        m = Memory()
        m.banks = {b: bytearray(d) for b, d in self.banks.items()}
        m.header = self.header
        return m

    def image_bytes(self) -> bytes:
        """A ref816 memory image: the header of the image this memory
        came from (registers and switches), then a record for each bank."""
        if len(self.header) != 32:
            raise ValueError('no ref816 image header to keep')
        out = bytearray(self.header)
        for bank in sorted(self.banks):
            out += struct.pack('<II', bank << 16, BANK)
            out += self.banks[bank]
        return bytes(out)

    def bank(self, bank: int) -> bytearray:
        data = self.banks.get(bank)
        if data is None:
            data = self.banks[bank] = bytearray(BANK)
        return data

    def read(self, address: int, length: int) -> bytes:
        out = bytearray()
        while length > 0:
            bank, offset = address >> 16, address & 0xffff
            count = min(length, BANK - offset)
            data = self.banks.get(bank)
            out += data[offset:offset + count] if data is not None \
                else bytes(count)
            address += count
            length -= count
        return bytes(out)

    def write(self, address: int, data: bytes) -> None:
        at = 0
        while at < len(data):
            bank, offset = (address + at) >> 16, (address + at) & 0xffff
            count = min(len(data) - at, BANK - offset)
            self.bank(bank)[offset:offset + count] = data[at:at + count]
            at += count

    def u8(self, address: int) -> int:
        data = self.banks.get(address >> 16)
        return data[address & 0xffff] if data is not None else 0

    def uint(self, address: int, size: int) -> int:
        if (address & 0xffff) + size <= BANK:
            data = self.banks.get(address >> 16)
            if data is None:
                return 0
            o = address & 0xffff
            return int.from_bytes(data[o:o + size], 'little')
        return int.from_bytes(self.read(address, size), 'little')

    def sint(self, address: int, size: int) -> int:
        v = self.uint(address, size)
        return v - (1 << (8 * size)) if v >> (8 * size - 1) else v

    def u16(self, address: int) -> int:
        return self.uint(address, 2)

    def u32(self, address: int) -> int:
        return self.uint(address, 4)

    def put(self, address: int, value: int, size: int) -> None:
        self.write(address, (value & ((1 << (8 * size)) - 1)).to_bytes(
            size, 'little'))


MAIN = 0x800000
AUX_BANKS = 128


def port_address(text: str) -> int:
    """"main:XXXX" or "aux:BB:XXXX" (hexadecimal) as a port address."""
    parts = text.split(':')
    if parts[0] == 'main' and len(parts) == 2:
        return MAIN | int(parts[1], 16)
    if parts[0] == 'aux' and len(parts) == 3:
        bank = int(parts[1], 16)
        if not 0 <= bank < AUX_BANKS:
            raise ValueError('%s: no aux bank %d' % (text, bank))
        return bank << 16 | int(parts[2], 16)
    raise ValueError('%s: not main:XXXX or aux:BB:XXXX' % text)


def port_text(address: int) -> str:
    if address & MAIN:
        return 'main:%04X' % (address & 0xffff)
    return 'aux:%02X:%04X' % (address >> 16, address & 0xffff)


class PortMemory(Memory):
    """The port's RAM: main (bank MAIN >> 16) and aux banks 0-127."""

    def image_bytes(self) -> bytes:
        """An a2vm --image file of every bank written (whole banks)."""
        out = bytearray(b'A2VMIMG1')
        for bank in sorted(self.banks):
            data = self.banks[bank]
            if bank == MAIN >> 16:
                kind, number = 0, 0
            elif bank < AUX_BANKS:
                kind, number = 1, bank
            else:
                raise ValueError('bank %X is not a port bank' % bank)
            # $0000-$BFFF of each: $C000-$CFFF is I/O, and the port's
            # layouts keep nothing in the language cards
            if any(data[0xc000:]):
                raise ValueError('bank %X: bytes at $C000-$FFFF, which an '
                                 'image of this tool does not load' % bank)
            out += struct.pack('<BBHI', kind, number, 0, 0xc000)
            out += data[:0xc000]
        return bytes(out)

    @classmethod
    def from_snapshot(cls, path: Path) -> 'PortMemory':
        data = Path(path).read_bytes()
        expected = BANK + 0x4000 + 0x1000 + AUX_BANKS * BANK
        if len(data) != expected:
            raise ValueError('%s: %d bytes, not an a2vm snapshot RAM'
                             % (path, len(data)))
        m = cls()
        m.banks[MAIN >> 16] = bytearray(data[:BANK])
        at = BANK + 0x4000 + 0x1000
        for bank in range(AUX_BANKS):
            m.banks[bank] = bytearray(data[at:at + BANK])
            at += BANK
        return m


def runs(memory: Memory, spans: Iterable[Tuple[int, int]]
         ) -> Iterator[Tuple[int, bytes]]:
    for start, end in spans:
        yield start, memory.read(start, end - start)
