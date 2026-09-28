"""The release image as the three programs that upstream links.

Upstream's Makefile links three programs, each with its rules file:

    game     src/iigs/iigs.scm     the segments of the disk header that
                                   hold code and initialised data
    boot     src/iigs/boot.scm     block 0 of the volume, run at $0800
    loader   src/iigs/loader.scm   the file DOOM.BOOT, run at $6000

targets() gives for each the memory that the program has when it runs,
as a memimage.MemoryImage. The addresses are those of the link. They
differ from the addresses of the disk header in one place: upstream's
tools/mkdisk.py stores the code that the linker put at $00DC00-$00DEFF
(the interrupt code) at $00BA00, and the game copies it up.

The bytes of a segment after the end of what the linker made are 0 on
the disk, because mkdisk.py fills each run of data to whole blocks of
512 bytes. They are part of the memory here, and the comparison counts
them.
"""

from typing import NamedTuple

from . import hdv, memimage, prodos

LINKED_KINDS = (hdv.KIND_CODE_BANK0, hdv.KIND_NEAR_DATA, hdv.KIND_CODE)
BOOT_ADDRESS = 0x0800
# elf_segments() of tools/mkdisk.py
MOVED_FIRST = 0x00dc00
MOVED_END = 0x00df00
MOVED_BY = 0x2200
RULES_FILES = {'game': 'iigs.scm', 'boot': 'boot.scm',
               'loader': 'loader.scm'}


class Target(NamedTuple):
    """The memory of one program of the release, and the name of its
    rules file in src/iigs."""
    name: str
    rules_file: str
    memory: memimage.MemoryImage


def disk_address(address):
    """Where the disk header says the byte of the link address
    `address` of the game is loaded."""
    if MOVED_FIRST <= address < MOVED_END:
        return address - MOVED_BY
    return address


def game_memory(image):
    """The memory of the game, at the addresses of the link."""
    memory = memimage.MemoryImage()
    stored_first = MOVED_FIRST - MOVED_BY
    stored_end = MOVED_END - MOVED_BY
    for segment in image.segments:
        if hdv.kind(image, segment) not in LINKED_KINDS:
            continue
        label = 'segment %d' % segment.index
        start = segment.address
        for first, end, shift in ((start, stored_first, 0),
                                  (stored_first, stored_end, MOVED_BY),
                                  (stored_end, segment.end, 0)):
            first = max(first, start)
            end = min(end, segment.end)
            if first < end:
                memory.load(first + shift,
                            segment.data[first - start:end - start], label)
    return memory


def targets(data):
    """The three Targets of the disk image in `data` (the bytes of the
    file)."""
    image = hdv.parse(data)
    boot = memimage.MemoryImage()
    boot.load(BOOT_ADDRESS, prodos.Volume(data).block(0), 'boot block')
    loader = memimage.MemoryImage()
    loader.load(image.loader_address, image.loader, hdv.LOADER_FILE)
    memories = {'game': game_memory(image), 'boot': boot, 'loader': loader}
    return [Target(name, RULES_FILES[name], memories[name])
            for name in ('game', 'boot', 'loader')]


def load(path):
    """The Targets of the disk image in the file `path`."""
    with open(path, 'rb') as handle:
        return targets(handle.read())
