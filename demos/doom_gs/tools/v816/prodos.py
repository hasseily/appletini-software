"""Read-only access to a ProDOS volume image in block order (.po, .hdv).

Only what the release image needs: the volume directory (no
subdirectories) and the three storage types of a standard file. The image
is never modified.
"""

import struct
from typing import List, NamedTuple

BLOCK = 512
VOLUME_DIR_BLOCK = 2
ENTRY_LENGTH = 39
STORAGE_SEEDLING, STORAGE_SAPLING, STORAGE_TREE = 1, 2, 3
STORAGE_VOLUME_HEADER = 15


class ProdosError(ValueError):
    """The image is not a ProDOS volume this reader understands."""


class FileEntry(NamedTuple):
    """One file of the volume directory."""
    name: str
    storage_type: int
    file_type: int
    key_block: int
    blocks_used: int
    length: int
    access: int
    aux_type: int


class Volume:
    """A ProDOS volume held in memory.

    `name` and `total_blocks` come from the volume directory header;
    `files` maps each file name to its FileEntry, in directory order.
    """

    def __init__(self, image: bytes):
        if not image or len(image) % BLOCK:
            raise ProdosError(
                'image length %d is not a multiple of %d' % (len(image), BLOCK))
        self.image = image
        self.name = ''
        self.total_blocks = 0
        self.files = {}  # type: Dict[str, FileEntry]
        self._read_directory()

    def block(self, number: int) -> bytes:
        """The 512 bytes of block `number`."""
        if not 0 <= number < len(self.image) // BLOCK:
            raise ProdosError('block %d is outside the image' % number)
        return self.image[number * BLOCK:(number + 1) * BLOCK]

    def _read_directory(self) -> None:
        number = VOLUME_DIR_BLOCK
        seen = set()
        first = True
        while number:
            if number in seen:
                raise ProdosError('the volume directory chain loops')
            seen.add(number)
            data = self.block(number)
            _previous, following = struct.unpack_from('<HH', data, 0)
            if first:
                self._read_header(data[4:4 + ENTRY_LENGTH])
            per_block = (BLOCK - 4) // self.entry_length
            for slot in range(1 if first else 0, per_block):
                start = 4 + slot * self.entry_length
                self._read_entry(data[start:start + self.entry_length])
            first = False
            number = following

    def _read_header(self, header: bytes) -> None:
        if header[0] >> 4 != STORAGE_VOLUME_HEADER:
            raise ProdosError('block 2 does not hold a volume directory header')
        self.name = header[1:1 + (header[0] & 15)].decode('ascii')
        self.entry_length = header[31]
        if self.entry_length < ENTRY_LENGTH:
            raise ProdosError('directory entry length %d' % self.entry_length)
        self.total_blocks = struct.unpack_from('<H', header, 37)[0]

    def _read_entry(self, entry: bytes) -> None:
        storage = entry[0] >> 4
        if storage == 0:
            return                      # a free or deleted slot
        name = entry[1:1 + (entry[0] & 15)].decode('ascii')
        key_block, blocks_used = struct.unpack_from('<HH', entry, 17)
        self.files[name] = FileEntry(
            name=name, storage_type=storage, file_type=entry[16],
            key_block=key_block, blocks_used=blocks_used,
            length=int.from_bytes(entry[21:24], 'little'),
            access=entry[30],
            aux_type=struct.unpack_from('<H', entry, 31)[0])

    def entry(self, name: str) -> FileEntry:
        """The directory entry of file `name`."""
        try:
            return self.files[name]
        except KeyError:
            raise ProdosError('no file %s on volume %s' % (name, self.name))

    def data_blocks(self, name: str) -> List[int]:
        """The block numbers of the data of file `name`, in file order.

        A block number of 0 is a sparse block (all zero bytes).
        """
        entry = self.entry(name)
        count = max(1, -(-entry.length // BLOCK))
        if entry.storage_type == STORAGE_SEEDLING:
            blocks = [entry.key_block]
        elif entry.storage_type == STORAGE_SAPLING:
            blocks = self._index(entry.key_block)
        elif entry.storage_type == STORAGE_TREE:
            blocks = []
            for index in self._index(entry.key_block)[:-(-count // 256)]:
                blocks += self._index(index) if index else [0] * 256
        else:
            raise ProdosError(
                '%s: storage type %d is not a standard file'
                % (name, entry.storage_type))
        return blocks[:count]

    def _index(self, number: int) -> List[int]:
        """The 256 pointers of an index block: low bytes, then high bytes."""
        data = self.block(number)
        return [data[i] | data[256 + i] << 8 for i in range(256)]

    def read_file(self, name: str) -> bytes:
        """The contents of file `name`."""
        out = bytearray()
        for number in self.data_blocks(name):
            out += self.block(number) if number else bytes(BLOCK)
        return bytes(out[:self.entry(name).length])
