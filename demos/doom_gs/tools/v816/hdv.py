"""The upstream release disk image: header, segment table, loaded segments.

The image is a ProDOS volume. Upstream's loader does not use the file
system: block 1 of the volume (unused by ProDOS) holds a header with a
table of segments, and the loader reads each segment by block number and
copies it to its 24-bit address. The files DOOM.BOOT (the loader itself),
DOOM.DATA (the blocks of the segments) and DOOM.SETTINGS exist so that
ProDOS tools see the blocks as used.

The format is defined by upstream's tools/mkdisk.py (function volume) and
the header comment and segment loop of src/iigs/loader.s:

  0    "DOOMGS"
  6    disk number, 1 based          7    number of disks
  8    number of segments            10   entry point, 3 bytes
  14   blocks for each cell of the load bar
  16   segments, 8 bytes each: address (3), flags (1), first block (2),
       block count (2)
  368  the store map, 8 runs of 4 words: first store block, count, first
       disk block, disk
  432  build ID, 4 bytes             436  block of DOOM.SETTINGS
  438  last disk with data below the store
  439  number of banks of the level store
  448  for each block of the picture segment, its block in the picture

Segment flags:
  SEG_PIC  the 64 blocks of the title picture, stored in the order of the
           table at 448 so that the picture appears early in the load
  SEG_B1   the blocks hold a 16-bit length (0 means 65536) and a B1 stream

What this module returns is the memory contents after the load, so a
picture segment is put back in memory order and a B1 segment is decoded.
Sizes are multiples of 512 because mkdisk.py rounds every run of data to
whole blocks; the padding bytes are loaded too.

Two things the loader does are outside the segment list. It copies the
picture to the screen in bank $E1, and it uses bank $30 as scratch space
for B1 streams. One address is not what it seems: mkdisk.py moves the ELF
data of $00:DC00-$00:DEFF (the interrupt code) to $00:BA00-$00:BCFF, and
the game copies it up at run time, so that code executes $2200 above the
address it has in the segment list.
"""

import struct
from typing import Dict, List, NamedTuple, Tuple

from v816 import b1, prodos

BLOCK = prodos.BLOCK
HEADER_BLOCK = 1
MAGIC = b'DOOMGS'
HDR_DISK = 6
HDR_DISKS = 7
HDR_SEGS = 8
HDR_ENTRY = 10
HDR_STEP = 14
HDR_SEG = 16
HDR_STOREMAP = 368
HDR_BUILD = 432
HDR_SETTINGS = 436
HDR_RESDISKS = 438
HDR_STOREBANKS = 439
HDR_ORDER = 448
SEGMENT_ENTRY = 8
MAX_SEGMENTS = (HDR_STOREMAP - HDR_SEG) // SEGMENT_ENTRY
STOREMAP_RUNS = 8
SEG_PIC = 1
SEG_B1 = 2
PIC_BLOCKS = 64
STORE_BANK = 0x40               # STORE_BANK of src/iigs/loader.s

LOADER_FILE = 'DOOM.BOOT'
DATA_FILE = 'DOOM.DATA'
SETTINGS_FILE = 'DOOM.SETTINGS'

# Kinds of segment, by where upstream's linker script (src/iigs/iigs.scm)
# and Makefile put things. The header does not say what a segment is.
KIND_PICTURE = 'title picture'
KIND_B1 = 'B1 stream'
KIND_SETTINGS = 'settings'
KIND_CODE_BANK0 = 'code, bank $00'
KIND_NEAR_DATA = 'near data'
KIND_CODE = 'code, banks $03-$05'
KIND_DATA = 'resident data'
KIND_STORE = 'level store'


class HdvError(ValueError):
    """The image does not have the layout of an upstream disk image."""


class Segment(NamedTuple):
    """One segment as it is in memory after the load.

    The first three fields are the (address, bytes, flags) triple.
    `index` is the position in the header table, which is the load order.
    `first_block` and `block_count` say where the segment is on disk.
    """
    address: int
    data: bytes
    flags: int
    index: int
    first_block: int
    block_count: int

    @property
    def end(self) -> int:
        """The address after the last byte."""
        return self.address + len(self.data)


class StoreRun(NamedTuple):
    """A run of blocks of the level store on a disk (header store map)."""
    store_block: int
    count: int
    disk_block: int
    disk: int


class DiskImage(NamedTuple):
    """Everything the loader learns from one disk image."""
    volume_name: str
    disk: int
    disks: int
    entry: int
    bar_step: int
    build_id: int
    settings_block: int
    resident_disks: int
    store_banks: int
    store_map: List[StoreRun]
    segments: List[Segment]
    loader_address: int
    loader: bytes

    def level_store(self) -> Tuple[int, bytes]:
        """The level store as (address, bytes).

        The store is the data in banks from STORE_BANK. The loader puts it
        in memory only on a machine with RAM there; otherwise the game
        reads it from the disk through the store map.
        """
        parts = sorted(s for s in self.segments
                       if kind(self, s) == KIND_STORE)
        if not parts:
            raise HdvError('the image has no level store')
        for before, after in zip(parts, parts[1:]):
            if before.end != after.address:
                raise HdvError('the level store has a gap at $%06X'
                               % before.end)
        return parts[0].address, b''.join(s.data for s in parts)


def kind(image: DiskImage, segment: Segment) -> str:
    """What `segment` holds, one of the KIND_ constants."""
    bank = segment.address >> 16
    if segment.flags & SEG_PIC:
        return KIND_PICTURE
    if segment.flags & SEG_B1:
        return KIND_B1
    if segment.first_block == image.settings_block:
        return KIND_SETTINGS
    if bank >= STORE_BANK:
        return KIND_STORE
    if bank == 0x00:
        return KIND_CODE_BANK0
    if bank == 0x02:
        return KIND_NEAR_DATA
    if 0x03 <= bank <= 0x05:
        return KIND_CODE
    return KIND_DATA


def totals(image: DiskImage) -> Dict[str, int]:
    """The number of bytes of each kind of segment."""
    sums = {}  # type: Dict[str, int]
    for segment in image.segments:
        name = kind(image, segment)
        sums[name] = sums.get(name, 0) + len(segment.data)
    return sums


def parse(data: bytes) -> DiskImage:
    """The disk image in `data` (the bytes of a .hdv or .po file)."""
    volume = prodos.Volume(data)
    header = volume.block(HEADER_BLOCK)
    if header[:len(MAGIC)] != MAGIC:
        raise HdvError('block 1 does not start with %r' % MAGIC)
    count = header[HDR_SEGS]
    if count > MAX_SEGMENTS:
        raise HdvError('%d segments, the header holds %d'
                       % (count, MAX_SEGMENTS))
    allowed = set(volume.data_blocks(DATA_FILE))
    allowed.update(volume.data_blocks(SETTINGS_FILE))
    order = header[HDR_ORDER:HDR_ORDER + PIC_BLOCKS]
    segments = []
    for index in range(count):
        word, first, blocks = struct.unpack_from(
            '<IHH', header, HDR_SEG + index * SEGMENT_ENTRY)
        address, flags = word & 0xffffff, word >> 24
        numbers = range(first, first + blocks)
        stray = [n for n in numbers if n not in allowed]
        if stray:
            raise HdvError(
                'segment %d: block %d is not in %s or %s'
                % (index, stray[0], DATA_FILE, SETTINGS_FILE))
        raw = b''.join(volume.block(n) for n in numbers)
        segments.append(Segment(
            address=address, data=_loaded(index, raw, flags, order),
            flags=flags, index=index, first_block=first, block_count=blocks))
    store_map = []
    for run in range(STOREMAP_RUNS):
        entry = StoreRun(*struct.unpack_from(
            '<HHHH', header, HDR_STOREMAP + 8 * run))
        if entry.count:
            store_map.append(entry)
    return DiskImage(
        volume_name=volume.name,
        disk=header[HDR_DISK],
        disks=header[HDR_DISKS],
        entry=int.from_bytes(header[HDR_ENTRY:HDR_ENTRY + 3], 'little'),
        bar_step=struct.unpack_from('<H', header, HDR_STEP)[0],
        build_id=struct.unpack_from('<I', header, HDR_BUILD)[0],
        settings_block=struct.unpack_from('<H', header, HDR_SETTINGS)[0],
        resident_disks=header[HDR_RESDISKS],
        store_banks=header[HDR_STOREBANKS],
        store_map=store_map,
        segments=segments,
        loader_address=volume.entry(LOADER_FILE).aux_type,
        loader=volume.read_file(LOADER_FILE))


def _loaded(index: int, raw: bytes, flags: int, order: bytes) -> bytes:
    """The memory contents that the disk blocks `raw` of a segment give."""
    if flags & ~(SEG_PIC | SEG_B1):
        raise HdvError('segment %d: unknown flags $%02X' % (index, flags))
    if flags & SEG_B1:
        if flags & SEG_PIC or len(raw) < 2:
            raise HdvError('segment %d: not a B1 segment' % index)
        length = struct.unpack_from('<H', raw, 0)[0] or 0x10000
        try:
            return b1.decode(raw[2:], length)
        except b1.B1Error as error:
            raise HdvError('segment %d: %s' % (index, error))
    if flags & SEG_PIC:
        if len(raw) != PIC_BLOCKS * BLOCK or \
                sorted(order) != list(range(PIC_BLOCKS)):
            raise HdvError('segment %d: not a picture of %d blocks'
                           % (index, PIC_BLOCKS))
        picture = bytearray(len(raw))
        for position, block in enumerate(order):
            picture[block * BLOCK:(block + 1) * BLOCK] = \
                raw[position * BLOCK:(position + 1) * BLOCK]
        return bytes(picture)
    return raw


def load(path: str) -> DiskImage:
    """The disk image in the file `path`."""
    with open(path, 'rb') as handle:
        return parse(handle.read())
