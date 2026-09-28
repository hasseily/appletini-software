"""A sparse image of the 24-bit address space of the 65816.

The image is built by loading segments in order, as the loader does, so a
later segment overwrites an earlier one where they overlap. For every
byte the image remembers which load put it there. That answers "which
segment holds address X" and tells loaded zero bytes from memory that
nothing was loaded to.
"""

import os
from array import array
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

BANK_SIZE = 0x10000
ADDRESS_SPACE = 0x1000000
_NOT_LOADED = -1


class Region(NamedTuple):
    """One load: where it went, how long it is, what the caller called it."""
    index: int
    address: int
    length: int
    label: str

    @property
    def end(self) -> int:
        """The address after the last byte."""
        return self.address + self.length


class Overlap(NamedTuple):
    """Bytes that region `later` loaded over bytes of region `earlier`."""
    address: int
    length: int
    earlier: int
    later: int


class MemoryImage:
    """Sparse memory, one 64 KB array for each bank that holds data."""

    def __init__(self):
        self.regions = []       # type: List[Region]
        self.overlaps = []      # type: List[Overlap]
        self._data = {}         # type: Dict[int, bytearray]
        self._owner = {}        # type: Dict[int, array]

    @classmethod
    def from_segments(cls, segments: Iterable) -> 'MemoryImage':
        """An image of `segments`, each an (address, bytes, flags, ...)
        tuple, loaded in the order given."""
        image = cls()
        for number, segment in enumerate(segments):
            image.load(segment[0], segment[1], 'segment %d' % number)
        return image

    def load(self, address: int, data: bytes, label: str = '') -> Region:
        """Put `data` at `address`; it may cross bank boundaries."""
        if address < 0 or address + len(data) > ADDRESS_SPACE:
            raise ValueError('$%06X + %d bytes is outside 24 bits'
                             % (address, len(data)))
        region = Region(len(self.regions), address, len(data), label)
        self.regions.append(region)
        position = 0
        while position < len(data):
            bank, offset = divmod(address + position, BANK_SIZE)
            count = min(BANK_SIZE - offset, len(data) - position)
            self._load_in_bank(region, bank, offset,
                               data[position:position + count])
            position += count
        return region

    def _load_in_bank(self, region, bank, offset, data) -> None:
        if bank not in self._data:
            self._data[bank] = bytearray(BANK_SIZE)
            self._owner[bank] = array('h', [_NOT_LOADED]) * BANK_SIZE
        end = offset + len(data)
        owners = self._owner[bank]
        if owners[offset:end].count(_NOT_LOADED) != len(data):
            self._note_overlaps(region, bank, offset, end)
        self._data[bank][offset:end] = data
        owners[offset:end] = array('h', [region.index]) * len(data)

    def _note_overlaps(self, region, bank, offset, end) -> None:
        owners = self._owner[bank]
        start = offset
        while start < end:
            earlier = owners[start]
            stop = start + 1
            while stop < end and owners[stop] == earlier:
                stop += 1
            if earlier != _NOT_LOADED:
                self.overlaps.append(Overlap(
                    bank * BANK_SIZE + start, stop - start,
                    earlier, region.index))
            start = stop

    def region_at(self, address: int) -> Optional[Region]:
        """The region whose data is at `address`, or None when nothing
        was loaded there."""
        bank, offset = divmod(address, BANK_SIZE)
        owners = self._owner.get(bank)
        if owners is None or owners[offset] == _NOT_LOADED:
            return None
        return self.regions[owners[offset]]

    def read(self, address: int, length: int) -> bytes:
        """`length` loaded bytes from `address`.

        Raises KeyError when any of them was never loaded: a caller that
        compares images must not take a hole for zero bytes.
        """
        out = bytearray()
        while len(out) < length:
            bank, offset = divmod(address + len(out), BANK_SIZE)
            count = min(BANK_SIZE - offset, length - len(out))
            owners = self._owner.get(bank)
            if owners is None or \
                    _NOT_LOADED in owners[offset:offset + count]:
                raise KeyError('nothing loaded in $%06X-$%06X'
                               % (address, address + length - 1))
            out += self._data[bank][offset:offset + count]
        return bytes(out)

    def banks(self) -> List[int]:
        """The banks that hold loaded bytes, in order."""
        return sorted(self._data)

    def extents(self, bank: int) -> List[Tuple[int, int]]:
        """The loaded ranges of `bank` as (first address, end address),
        in order, adjacent ranges joined."""
        owners = self._owner.get(bank)
        if owners is None:
            return []
        loaded = bytes(owner != _NOT_LOADED for owner in owners)
        ranges = []
        start = loaded.find(1)
        while start >= 0:
            stop = loaded.find(0, start)
            if stop < 0:
                stop = BANK_SIZE
            ranges.append((bank * BANK_SIZE + start, bank * BANK_SIZE + stop))
            start = loaded.find(1, stop)
        return ranges

    def loaded_bytes(self, bank: int) -> int:
        """How many bytes of `bank` are loaded."""
        return sum(end - start for start, end in self.extents(bank))

    def bank_bytes(self, bank: int, fill: int = 0) -> bytes:
        """The 64 KB of `bank`, bytes that are not loaded set to `fill`."""
        if bank not in self._data:
            return bytes([fill]) * BANK_SIZE
        out = bytearray([fill]) * BANK_SIZE
        for start, end in self.extents(bank):
            low, high = start % BANK_SIZE, (end - 1) % BANK_SIZE + 1
            out[low:high] = self._data[bank][low:high]
        return bytes(out)

    def dump(self, directory: str, fill: int = 0) -> List[str]:
        """Write each bank with data to `directory` as bankXX.bin (64 KB,
        holes set to `fill`) and return the paths.

        The files hold upstream's code and data: `directory` must be in
        build/, never in a place that is committed.
        """
        os.makedirs(directory, exist_ok=True)
        paths = []
        for bank in self.banks():
            path = os.path.join(directory, 'bank%02X.bin' % bank)
            with open(path, 'wb') as handle:
                handle.write(self.bank_bytes(bank, fill))
            paths.append(path)
        return paths
