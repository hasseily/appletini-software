#!/usr/bin/env python3
"""Write the memory that upstream's loader leaves for the game, for ref816.

Usage:  python3 tools/ref816/make_image.py [--image HDV] [--linkmap JSON]
                                          [--out DIR] [--banks N]

The reference machine starts the game at its entry point without the
boot block and the loader (src/iigs/boot.s, src/iigs/loader.s). This
script builds the state the loader would leave on an 8 MB IIgs booting
the release image from a hard disk in slot 7, and writes

  DIR/memory.img   the memory image (format below)
  DIR/disk.hdv     a copy of the disk image, which the machine serves to
                   the game's firmware calls
  DIR/loader.img   the loader alone, entered as the boot block leaves it:
                   running it on the machine up to the entry point gives
                   the memory of the real loader, to check memory.img

DIR is build/ref816 by default. The files hold upstream's code and data:
they stay in build/, which git ignores. The test of memory.img against
the loader is in tests/test_ref816_machine.py; the two differ only in
the loader's direct page and stack, its own variables, and the load
strip.

--banks N makes the image of a IIgs with RAM in banks $00 to N-1 instead
(64 for 4 MB): the loader then leaves the level store on the disk and
the game reads it through the firmware at each level. The machine keeps
its 8 MB; the game uses only the banks that BOOTINFO lists.

What the loader leaves, in the order it does it (with the shadow
register as the firmware leaves it, each write to bank $00 in the text
pages or the hi-res pages is also copied to bank $E0):
  - at $bb:8000 of each bank $7F down to $02, the bank number and its
    complement (its memory probe);
  - the loader itself at $00:6000 (DOOM.BOOT);
  - block 1 of the disk (the header) at $00:7800;
  - every segment of the header at its address, the level store too
    since its banks are RAM; the blocks of a B1 segment first go to
    $30:0000 and are decoded from there, so the stream of the last one
    stays in bank $30; the block buffer at $00:7A00 holds the last
    block read;
  - BOOTINFO at $00:7E00 (layout below);
  - the super hi-res screen: the title picture without its rows 191-199
    (the loader's load strip), its scan-line control bytes and its
    palettes, palettes 0-14 turned to grey by the loader's tables.
The loader's strip (disk icon, disk number, full bar) is not drawn: the
strip rows are black. The loader's direct page and stack are not
reproduced, nor its variables inside its own code, and memory the loader
never wrote is zero.

BOOTINFO (src/iigs/loader.s, read by src/iigs/m_config65.s and
src/iigs/w_level65.s):
  0 "DB"   2 ProDOS unit   3 SmartPort unit   4 block driver entry
  6 SmartPort entry   8 block of DOOM.SETTINGS   10 its disk (1)
  12 build ID   16 1: the store is in RAM   17 last disk with data below
  the store   18 number of disks   19 banks of the store
  20 RAM banks $00-$7F, a bit each   36 the header's store map (64 bytes)

The memory image: "REF816I1", then the registers at the start (PC, PBR,
DBR, A, X, Y, S, D as little-endian words and bytes, P, E), then the soft
switches $C029, $C034, $C035, $C036, padded to 32 bytes; then records of
a 32-bit address, a 32-bit length and the bytes, loaded in order.
"""

import argparse
import json
import shutil
import struct
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from v816 import hdv, prodos  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
BUILD = ROOT / 'build'
RELEASE_IMAGE = BUILD / 'release' / 'doom-hd.hdv'
LINKMAP = BUILD / 'linkmap.json'
OUT_DIR = BUILD / 'ref816'

MAGIC = b'REF816I1'
HEADER_SIZE = 32
BLOCK = hdv.BLOCK

# The machine (tools/ref816/iigs.h): 8 MB, the boot drive in slot 7 with
# its block driver at $C70A and SmartPort 3 bytes later.
RAM_BANKS = 0x80
DISK_SLOT = 7
DRIVER_ENTRY = 0xc70a
SMARTPORT_ENTRY = DRIVER_ENTRY + 3
PRODOS_UNIT = DISK_SLOT << 4            # drive 1
SMARTPORT_UNIT = 1

# The loader's addresses (src/iigs/loader.s).
HDR = 0x007800
BUF = 0x007a00
BOOTINFO = 0x007e00
STAGE = 0x300000
PROBE = 0x8000
FIRST_PROBED_BANK = 0x02
BI_SIZE = 100
BI_BANKS = 20
BI_STOREMAP = 36
STOREMAP_SIZE = 64

# The screen (src/iigs/loader.s): the picture record is an image of
# $E1:2000-$9FFF; the loader copies its rows above the load strip, and
# its bytes from the end of the pixels (the scan-line control bytes and
# the palettes), then greys palettes 0-14.
SCREEN = 0xe12000
SCREEN_SIZE = 0x8000
STRIP = 191 * 160
PIXELS_END = 200 * 160
PALETTES = 0x7e00
GREY_PALETTES = 15

# The soft switches $C029, $C034, $C035 and $C036 that the firmware
# leaves after a boot (an assumption: $C029 bit 0 set, border 0, the
# shadow register with only super hi-res shadowing off, fast speed), and
# after the loader, which sets $C029 bits 6 and 7 and clears the low
# nibble of $C034.
FIRMWARE_SWITCHES = (0x01, 0x00, 0x08, 0x80)
LOADER_SWITCHES = (0xc1, 0x00, 0x08, 0x80)

# The pages of banks $00 and $01 that the shadow register $08 copies to
# banks $E0 and $E1 (tools/ref816/iigs.c, shadow_write): text pages 1
# and 2, hi-res pages 1 and 2.
SHADOWED = ((0x0400, 0x0c00), (0x2000, 0x6000))

# The registers at the JML to the entry point: native mode after
# REP #$30, interrupts off since the loader's SEI, carry set by the last
# loop over the load bar's cells, D = 0 and DBR = 0 as the loader keeps
# them, X = the low word of the entry point and A = its bank (the last
# loads), S in page 1 where the boot block left it (an assumption). The
# boot block enters the loader in emulation mode with X = the ProDOS
# unit.
P_AT_ENTRY = 0x05
P_AT_BOOT = 0x34
S_AT_ENTRY = 0x01fb

LOADER_TABLES = ('GRAY_B', 'GRAY_G', 'GRAY_R', 'GRAYS')


class GreyTables(NamedTuple):
    """The loader's tables for greying a colour $0RGB: the index is
    (GRAY_R[R] + GRAY_G[G] + GRAY_B[B]) >> 4 into GRAYS."""
    blue: bytes
    green: bytes
    red: bytes
    greys: Tuple[int, ...]


class Registers(NamedTuple):
    pc: int
    pbr: int
    dbr: int
    a: int
    x: int
    y: int
    s: int
    d: int
    p: int
    e: int


def grey_tables(disk: hdv.DiskImage, linkmap: Dict) -> GreyTables:
    """The grey tables of the loader in `disk`, found by the addresses
    of their labels in the link map of tools/v816/imgmatch.py."""
    labels = linkmap['loader']['units']['loader.s']
    parts = []
    for name in LOADER_TABLES:
        start = labels[name] - disk.loader_address
        size = 32 if name == 'GRAYS' else 16
        if start < 0 or start + size > len(disk.loader):
            raise ValueError('%s is outside the loader' % name)
        parts.append(disk.loader[start:start + size])
    blue, green, red, greys = parts
    return GreyTables(blue, green, red, struct.unpack('<16H', greys))


def grey(colour: int, tables: GreyTables) -> int:
    """The grey the loader gives colour $0RGB."""
    total = (tables.red[colour >> 8 & 15] + tables.green[colour >> 4 & 15] +
             tables.blue[colour & 15])
    return tables.greys[total >> 4 & 15]


def loader_screen(picture: bytes, tables: GreyTables) -> bytes:
    """$E1:2000-$9FFF as the loader leaves it with `picture` loaded."""
    screen = bytearray(SCREEN_SIZE)
    screen[:STRIP] = picture[:STRIP]
    screen[PIXELS_END:] = picture[PIXELS_END:]
    for index in range(GREY_PALETTES * 16):
        at = PALETTES + 2 * index
        colour = struct.unpack_from('<H', screen, at)[0]
        struct.pack_into('<H', screen, at, grey(colour, tables))
    return bytes(screen)


def ram_bitmap(banks: int) -> bytes:
    """BOOTINFO's RAM banks: bank b is bit b & 7 of byte b >> 3."""
    bitmap = bytearray(16)
    for bank in range(banks):
        bitmap[bank >> 3] |= 1 << (bank & 7)
    return bytes(bitmap)


def store_in_ram(disk: hdv.DiskImage, banks: int) -> bool:
    """The loader's storeMode: the store loads when its banks are RAM."""
    return 0 < disk.store_banks and \
        hdv.STORE_BANK + disk.store_banks <= banks


def boot_info(disk: hdv.DiskImage, header: bytes, banks: int) -> bytes:
    """The BOOTINFO block for `disk`, whose block 1 is `header`."""
    info = bytearray(BI_SIZE)
    info[0:2] = b'DB'
    info[2] = PRODOS_UNIT
    info[3] = SMARTPORT_UNIT
    struct.pack_into('<HHH', info, 4, DRIVER_ENTRY, SMARTPORT_ENTRY,
                     disk.settings_block)
    info[10] = 1
    struct.pack_into('<I', info, 12, disk.build_id)
    stored = store_in_ram(disk, banks)
    info[16] = int(stored)
    info[17] = disk.resident_disks
    info[18] = disk.disks
    info[19] = disk.store_banks
    info[BI_BANKS:BI_BANKS + 16] = ram_bitmap(banks)
    info[BI_STOREMAP:BI_STOREMAP + STOREMAP_SIZE] = \
        header[hdv.HDR_STOREMAP:hdv.HDR_STOREMAP + STOREMAP_SIZE]
    return bytes(info)


def entry_registers(entry: int) -> Registers:
    return Registers(pc=entry & 0xffff, pbr=entry >> 16, dbr=0,
                     a=entry >> 16, x=entry & 0xffff, y=0, s=S_AT_ENTRY,
                     d=0, p=P_AT_ENTRY, e=0)


def with_shadow(address: int, data: bytes) -> List[Tuple[int, bytes]]:
    """The load of `data` at `address` and the copies the shadow
    register makes of it."""
    out = [(address, data)]
    bank, offset = address >> 16, address & 0xffff
    if bank > 1:
        return out
    if offset + len(data) > 0x10000:
        raise ValueError('a load at $%06X crosses its bank' % address)
    for low, high in SHADOWED:
        start, end = max(offset, low), min(offset + len(data), high)
        if start < end:
            out.append((0xe00000 | bank << 16 | start,
                        data[start - offset:end - offset]))
    return out


def records(disk: hdv.DiskImage, volume: prodos.Volume,
            tables: GreyTables, banks: int = RAM_BANKS
            ) -> List[Tuple[int, bytes]]:
    """What the loader writes, as (address, bytes) in the order it
    writes them."""
    if disk.disks != 1:
        raise ValueError('only a one-disk image boots without prompts; '
                         'this is disk %d of %d' % (disk.disk, disk.disks))
    out = [(bank << 16 | PROBE, bytes([bank, bank ^ 0xff]))
           for bank in range(banks - 1, FIRST_PROBED_BANK - 1, -1)]
    out.append((disk.loader_address, disk.loader))
    header = volume.block(hdv.HEADER_BLOCK)
    out.append((HDR, header))
    stored = store_in_ram(disk, banks)
    last_block = header
    picture = None
    for segment in disk.segments:
        if segment.address >> 16 >= hdv.STORE_BANK and not stored:
            continue
        raw = b''.join(volume.block(n) for n in range(
            segment.first_block, segment.first_block + segment.block_count))
        if segment.flags & hdv.SEG_B1:
            out.append((STAGE, raw))
        if segment.flags & hdv.SEG_PIC:
            picture = segment.data
        out.extend(with_shadow(segment.address, segment.data))
        last_block = raw[-BLOCK:]
    if picture is None:
        raise ValueError('the image has no title picture')
    out.append((BUF, last_block))
    out.append((BOOTINFO, boot_info(disk, header, banks)))
    out.append((SCREEN, loader_screen(picture, tables)))
    return out


def loader_registers(disk: hdv.DiskImage) -> Registers:
    return Registers(pc=disk.loader_address & 0xffff, pbr=0, dbr=0, a=0,
                     x=PRODOS_UNIT, y=0, s=S_AT_ENTRY, d=0, p=P_AT_BOOT, e=1)


def image_bytes(registers: Registers, loads: List[Tuple[int, bytes]],
                switches: Tuple[int, int, int, int] = LOADER_SWITCHES
                ) -> bytes:
    """The memory image file for ref816."""
    r = registers
    header = MAGIC + struct.pack(
        '<HBBHHHHHBB4B', r.pc, r.pbr, r.dbr, r.a, r.x, r.y, r.s, r.d, r.p,
        r.e, *switches)
    header += bytes(HEADER_SIZE - len(header))
    body = b''.join(struct.pack('<II', address, len(data)) + data
                    for address, data in loads)
    return header + body


def build(image_path: Path, linkmap_path: Path,
          banks: int = RAM_BANKS) -> Tuple[bytes, bytes]:
    """The memory image for the disk image at `image_path`, and the
    image that runs its loader."""
    data = image_path.read_bytes()
    disk = hdv.parse(data)
    with open(str(linkmap_path)) as handle:
        tables = grey_tables(disk, json.load(handle))
    loads = records(disk, prodos.Volume(data), tables, banks)
    loader = image_bytes(loader_registers(disk),
                         [(disk.loader_address, disk.loader)],
                         FIRMWARE_SWITCHES)
    return image_bytes(entry_registers(disk.entry), loads), loader


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--image', type=Path, default=RELEASE_IMAGE)
    parser.add_argument('--linkmap', type=Path, default=LINKMAP)
    parser.add_argument('--out', type=Path, default=OUT_DIR)
    parser.add_argument('--banks', type=int, default=RAM_BANKS,
                        choices=range(0x40, RAM_BANKS + 1), metavar='N',
                        help='RAM banks $00 to N-1, 64 to 128 (default 128)')
    arguments = parser.parse_args(argv)
    for path, how in ((arguments.image, 'python3 tools/fetch_upstream.py'),
                      (arguments.linkmap, 'python3 tools/v816/imgmatch.py')):
        if not path.exists():
            print('%s is missing: run %s first' % (path, how),
                  file=sys.stderr)
            return 1
    memory, loader = build(arguments.image, arguments.linkmap,
                           arguments.banks)
    arguments.out.mkdir(parents=True, exist_ok=True)
    (arguments.out / 'memory.img').write_bytes(memory)
    (arguments.out / 'loader.img').write_bytes(loader)
    shutil.copyfile(str(arguments.image), str(arguments.out / 'disk.hdv'))
    print('wrote %s (%d bytes) and %s' % (
        arguments.out / 'memory.img', len(memory),
        arguments.out / 'disk.hdv'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
