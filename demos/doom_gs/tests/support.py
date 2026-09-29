"""Shared by the tests: paths, skip rules and small synthetic disk images.

The synthetic images let the parsers be tested without anything from
upstream. Tests of the real release image and of upstream's own tools
skip when tools/fetch_upstream.py has not filled build/.
"""

import atexit
import importlib.util
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / 'build'
UPSTREAM = BUILD / 'upstream'
RELEASE_IMAGE = BUILD / 'release' / 'doom-hd.hdv'

sys.path.insert(0, str(ROOT / 'tools'))

from v816 import hdv, prodos  # noqa: E402

BLOCK = prodos.BLOCK
NEED_FETCH = '%s is missing: run python3 tools/fetch_upstream.py first'

needs_release = unittest.skipUnless(
    RELEASE_IMAGE.exists(), NEED_FETCH % RELEASE_IMAGE.relative_to(ROOT))
needs_upstream = unittest.skipUnless(
    (UPSTREAM / 'tools' / 'b1.py').exists(),
    NEED_FETCH % UPSTREAM.relative_to(ROOT))

# Hand-assembled B1 streams (tools/v816/b1.py describes the format).
# Literals "ab", then a match at the new offset 2 of length 4.
B1_ABABAB = (bytes([0x00, 0x3e]) + b'ab' + bytes([0x02]), b'ababab')
# Literal "a", then a match at the previous offset (1 at the start) of
# length 3, then the literal "z".
B1_AAAAZ = (bytes([0x00, 0x9a]) + b'az', b'aaaaz')


def upstream_module(name):
    """The module tools/<name>.py of the fetched upstream clone."""
    path = UPSTREAM / 'tools' / (name + '.py')
    spec = importlib.util.spec_from_file_location('upstream_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VolumeBuilder:
    """Builds a ProDOS volume image with files in chosen blocks."""

    def __init__(self, name, total_blocks):
        self.name = name
        self.image = bytearray(total_blocks * BLOCK)
        self.total_blocks = total_blocks
        self.entries = []
        self.next_free = total_blocks - 1   # index blocks go at the end

    def write(self, block, data):
        self.image[block * BLOCK:block * BLOCK + len(data)] = data

    def _index_block(self, pointers):
        block = self.next_free
        self.next_free -= 1
        data = bytearray(BLOCK)
        for position, pointer in enumerate(pointers):
            data[position] = pointer & 0xff
            data[256 + position] = pointer >> 8
        self.write(block, data)
        return block

    def add_file(self, name, data, first_block, file_type=6, aux_type=0):
        """File `name` with `data` in blocks from `first_block`."""
        count = max(1, -(-len(data) // BLOCK))
        blocks = list(range(first_block, first_block + count))
        self.write(first_block, data)
        if count == 1:
            storage, key = prodos.STORAGE_SEEDLING, first_block
        elif count <= 256:
            storage, key = prodos.STORAGE_SAPLING, self._index_block(blocks)
        else:
            storage = prodos.STORAGE_TREE
            key = self._index_block(
                [self._index_block(blocks[start:start + 256])
                 for start in range(0, count, 256)])
        entry = bytearray(prodos.ENTRY_LENGTH)
        entry[0] = storage << 4 | len(name)
        entry[1:1 + len(name)] = name.encode('ascii')
        entry[16] = file_type
        struct.pack_into('<HH', entry, 17, key, count)
        entry[21:24] = len(data).to_bytes(3, 'little')
        entry[30] = 0xc3
        struct.pack_into('<H', entry, 31, aux_type)
        self.entries.append(entry)

    def build(self):
        """The image, with a volume directory of one or more blocks."""
        header = bytearray(prodos.ENTRY_LENGTH)
        header[0] = prodos.STORAGE_VOLUME_HEADER << 4 | len(self.name)
        header[1:1 + len(self.name)] = self.name.encode('ascii')
        header[31] = prodos.ENTRY_LENGTH
        header[32] = 13
        struct.pack_into('<HHH', header, 33, len(self.entries), 6,
                         self.total_blocks)
        slots = [header] + self.entries
        blocks = list(range(2, 2 + -(-len(slots) // 13)))
        for position, block in enumerate(blocks):
            data = bytearray(BLOCK)
            struct.pack_into(
                '<HH', data, 0,
                blocks[position - 1] if position else 0,
                blocks[position + 1] if position + 1 < len(blocks) else 0)
            for slot, entry in enumerate(slots[13 * position:][:13]):
                start = 4 + slot * prodos.ENTRY_LENGTH
                data[start:start + prodos.ENTRY_LENGTH] = entry
            self.write(block, data)
        return bytes(self.image)


def picture_order():
    """A permutation of the 64 picture blocks that is not the identity."""
    return bytes(reversed(range(hdv.PIC_BLOCKS)))


def make_disk(segments, entry=0x030000, order=None, magic=hdv.MAGIC,
              data_blocks=None):
    """A disk image in upstream's layout.

    `segments` is a list of (address, flags, disk data); the disk data of
    each is padded to whole blocks and they go in DOOM.DATA one after
    the other from block 14. A settings segment at $007C00 follows, as on
    upstream's disks. `data_blocks` sets the length of DOOM.DATA in
    blocks when it must differ from the blocks of the segments.
    """
    first = 14
    padded = [data + bytes(-len(data) % BLOCK) for _, _, data in segments]
    used = sum(len(data) // BLOCK for data in padded)
    if data_blocks is None:
        data_blocks = used
    settings_block = first + max(used, data_blocks)
    builder = VolumeBuilder('TEST', settings_block + 8)
    builder.add_file(hdv.LOADER_FILE, b'\x60' * 700, 8, aux_type=0x6000)
    builder.add_file(hdv.DATA_FILE, bytes(data_blocks * BLOCK), first)
    builder.add_file(hdv.SETTINGS_FILE, b'S' * BLOCK, settings_block,
                     file_type=0x5a)
    header = bytearray(BLOCK)
    header[0:6] = magic
    header[hdv.HDR_DISK] = 1
    header[hdv.HDR_DISKS] = 1
    header[hdv.HDR_SEGS] = len(segments) + 1
    struct.pack_into('<I', header, hdv.HDR_ENTRY, entry)
    struct.pack_into('<H', header, hdv.HDR_STEP, 3)
    struct.pack_into('<I', header, hdv.HDR_BUILD, 0x12345678)
    struct.pack_into('<H', header, hdv.HDR_SETTINGS, settings_block)
    header[hdv.HDR_RESDISKS] = 1
    header[hdv.HDR_ORDER:hdv.HDR_ORDER + hdv.PIC_BLOCKS] = \
        order if order is not None else picture_order()
    block = first
    table = []
    for (address, flags, _), data in zip(segments, padded):
        builder.write(block, data)
        table.append((address | flags << 24, block, len(data) // BLOCK))
        if address >> 16 >= hdv.STORE_BANK:
            header[hdv.HDR_STOREBANKS] = -(-len(data) // 0x10000)
            struct.pack_into('<HHHH', header, hdv.HDR_STOREMAP,
                             0, len(data) // BLOCK, block, 1)
        block += len(data) // BLOCK
    table.append((0x007c00, settings_block, 1))
    for position, item in enumerate(table):
        struct.pack_into('<IHH', header, hdv.HDR_SEG + 8 * position, *item)
    builder.write(1, header)
    return builder.build()


_frontend_results = []


def frontend_results():
    """The results of the front end for upstream's default build, made
    once for all tests. The generated sources are made first, as the
    driver does."""
    from v816 import frontend
    if not _frontend_results:
        frontend.generate()
        _frontend_results.extend(frontend.run())
    return _frontend_results


def assemble_text(text, name='t.s'):
    """The ObjectFile (tools/v816/objfile.py) of the source `text`; the
    unit has the name `name`. Errors of the front end fail the test;
    errors of the assembler are in the ObjectFile."""
    from v816 import cpp, objfile, parse
    lines = cpp.Preprocessor().process_text(text, name=name)
    unit, _ = parse.parse_lines(lines, name)
    if unit.errors:
        raise AssertionError('\n'.join(map(str, unit.errors)))
    return objfile.assemble(unit, name)


def assemble_clean(text, name='t.s'):
    """As assemble_text(); errors of the assembler fail the test too."""
    unit = assemble_text(text, name)
    if unit.errors:
        raise AssertionError('\n'.join(map(str, unit.errors)))
    return unit


def program_of(sources, rules_text):
    """The link.Program of `sources`, a dictionary from unit name to
    source text, with the rules file `rules_text`."""
    from v816 import link, scm
    units = [assemble_clean(text, name) for name, text in sources.items()]
    return link.Program(units, scm.parse(rules_text))


def linked_at(program, places):
    """The link.Linked of `program` with its fragments at `places`, a
    dictionary from key to address. The tests of the layout recovery
    use the memory of the result as the release image."""
    from v816 import link
    known = {program.fragments[key].atom: address
             for key, address in places.items()}
    return link.link(program, places, known)


_match_results = []


def match_results():
    """(report, link maps) of tools/v816/imgmatch.py for the release
    image, made once for all tests."""
    from v816 import imgmatch
    if not _match_results:
        _match_results.extend(
            imgmatch.run(RELEASE_IMAGE, frontend_results()))
    return _match_results


_release_targets = []


def release_targets():
    """The release.Targets of the release image, with the memories of
    the game that upstream's rules and sources give, made once for all
    tests."""
    from v816 import imgmatch, release, scm
    if not _release_targets:
        rules = scm.load(UPSTREAM / 'src' / 'iigs' /
                         release.RULES_FILES['game'])
        objects = imgmatch.assemble(frontend_results(), 'game')
        memories = release.linked_memories(
            rules, imgmatch.initialised_sections(objects))
        _release_targets.extend(release.load(str(RELEASE_IMAGE), memories))
    return _release_targets


_ref816_built = []


def ref816_build():
    """Build everything of tools/ref816 (the machine, the vector harness
    and the two test programs) once, from scratch, into a directory of
    their own under build/, removed when the tests end. Returns
    (directory, what the compiler said)."""
    if not _ref816_built:
        BUILD.mkdir(exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix='test-ref816-', dir=str(BUILD)))
        atexit.register(shutil.rmtree, str(out), True)
        result = subprocess.run(
            ['make', '-B', '-C', str(ROOT / 'tools' / 'ref816'),
             'OUT=%s' % out, 'all'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)
        _ref816_built.extend([out, result])
    out, result = _ref816_built
    if result.returncode:
        raise AssertionError('make failed:\n' + result.stdout)
    return out, result.stdout


_a2vm_built = []


def a2vm_build():
    """Build everything of tools/a2vm (the vector harness, the self test
    and the bench) once, from scratch, into a directory of their own under
    build/, removed when the tests end. Returns (directory, what the
    compiler said)."""
    if not _a2vm_built:
        BUILD.mkdir(exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix='test-a2vm-', dir=str(BUILD)))
        atexit.register(shutil.rmtree, str(out), True)
        result = subprocess.run(
            ['make', '-B', '-C', str(ROOT / 'tools' / 'a2vm'),
             'OUT=%s' % out, 'all'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)
        _a2vm_built.extend([out, result])
    out, result = _a2vm_built
    if result.returncode:
        raise AssertionError('make failed:\n' + result.stdout)
    return out, result.stdout
