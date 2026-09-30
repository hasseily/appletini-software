"""Milestone 5: the native record replay (src/native, tools/native).

The replay's pixels and memory against upstream's R_DrawLists: on every
captured frame (build/captures, tools/ref816/capture.py) from the
captured screen and from a poisoned one, and on synthetic record streams
(tools/native/synth.py), with a check of every byte of the machine for
stray writes (tools/native/replay_check.py). Then that these checks do
fail: bugs planted in a scratch copy of the sources. And the card run's
disk on a2vm.

What each part needs, and skips without: cc65 (ca65, ld65) on PATH;
build/a2vm/a2vm and build/ref816/ref816 (make -C tools/a2vm, make -C
tools/ref816); build/linkmap.json (tools/v816/imgmatch.py); the captures
with their fuzz table (python3 tools/ref816/capture.py); for the
synthetic streams, build/native/base-entry.img (python3 tools/native/
synth.py --make-base); for the disk, appletini-one's ProDOS master.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

from native import a2run, disk, layout as L, loader, replay_check, rowgen, \
    synth  # noqa: E402
from ref816 import lists, title  # noqa: E402

ROOT = support.ROOT
SRC = ROOT / 'src' / 'native'
OBJ = ROOT / 'build' / 'native' / 'obj'
CAPTURES = ROOT / 'build' / 'captures'
LINKMAP = ROOT / 'build' / 'linkmap.json'


def capture_dirs():
    if not CAPTURES.is_dir():
        return []
    return sorted(p for p in CAPTURES.iterdir()
                  if (p / 'manifest.json').exists())


HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
needs_cc65 = unittest.skipUnless(HAVE_CC65, 'cc65 (ca65, ld65) is not on '
                                 'PATH')
needs_a2vm = unittest.skipUnless(a2run.A2VM.exists(), '%s is missing: '
                                 'make -C tools/a2vm' % a2run.A2VM)
needs_ref816 = unittest.skipUnless(title.MACHINE.exists(), '%s is missing: '
                                   'make -C tools/ref816' % title.MACHINE)
needs_linkmap = unittest.skipUnless(LINKMAP.exists(), '%s is missing: run '
                                    'python3 tools/v816/imgmatch.py'
                                    % LINKMAP)
needs_captures = unittest.skipUnless(
    capture_dirs() and all((d / 'fuzz.bin').exists()
                           for d in capture_dirs()),
    'no captures with fuzz.bin in build/captures: run python3 '
    'tools/ref816/capture.py')
needs_base = unittest.skipUnless(synth.BASE.exists(), '%s is missing: run '
                                 'python3 tools/native/synth.py --make-base'
                                 % synth.BASE)
needs_upstream = unittest.skipUnless(
    (support.UPSTREAM / 'src' / 'iigs' / 'i_viigs65.s').exists(),
    'the upstream clone is missing: run python3 tools/fetch_upstream.py')


def make(out=OBJ, src=SRC):
    """Build src into out; returns make's output."""
    result = subprocess.run(
        ['make', '-C', str(src), 'ROOT=%s' % ROOT, 'OUT=%s' % out],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True)
    if result.returncode:
        raise AssertionError('make failed:\n' + result.stdout)
    return result.stdout


_built = []


def build():
    """The build, made once for the run."""
    if not _built:
        make()
        _built.append(loader.read_build(OBJ))
    return _built[0]


# ---------------------------------------------------------------------------
# the layout and the generated code
# ---------------------------------------------------------------------------

class Layout(unittest.TestCase):

    @needs_linkmap
    def test_record_format_is_upstreams(self):
        units = json.loads(LINKMAP.read_text())['game']['units']
        lay = lists.layout(units)
        for kind, name in L.KIND_NAMES.items():
            self.assertEqual(lay.kinds[kind], name)
            self.assertEqual(lay.sizes[name], L.SIZES[kind], name)
        for name, offset in L.FIELDS.items():
            self.assertEqual(lay.fields[name], offset, name)
        self.assertEqual(lay.columns, L.COLUMNS)
        # the port's own kind is none of upstream's
        self.assertNotIn(L.K_FUZZNOW, lay.kinds)
        u = units['r_list65.s']
        self.assertEqual(u['CONST_VIEWHEIGHT'], L.VIEW_ROWS)
        self.assertEqual(u['PAGE_ROOM'], L.PAGE_ROOM)

    @needs_upstream
    def test_fuzz_directions_are_upstreams(self):
        text = (support.UPSTREAM / 'src' / 'iigs' /
                'i_viigs65.s').read_text()
        block = text.split('fuzzDir:', 1)[1].split('.section', 1)[0]
        values = [int(v) for v in re.findall(r'\b[01]\b', block)]
        self.assertEqual(tuple(values), L.FUZZ_DIR)

    def test_colormap_pages(self):
        pages = [L.cmap_page_a(level) for level in range(L.CMAP_LEVELS)] + \
            [L.cmap_page_b(level) for level in range(L.CMAP_LEVELS)]
        self.assertEqual(len(set(pages)), 2 * L.CMAP_LEVELS)
        for page in pages:
            self.assertTrue(0x04 <= page <= 0x07 or 0x20 <= page <= 0x5F)
        # the forbidden bytes of rule 8 are in page $40: colormap B level
        # 0 (loaded by PRIVATE, never stored to by the CPU)
        self.assertEqual(L.cmap_page_b(0), 0x40)

    def test_row_block_entries(self):
        self.assertEqual(L.tex_entry(0), 0xD000)
        self.assertEqual(L.tex_entry(1), 0xD000 + L.EVEN_BYTES)
        self.assertEqual(L.tex_entry(L.VIEW_ROWS), L.TEXLAND)
        self.assertLessEqual(L.TEXLAND, L.FILLE)

    def test_the_fuzz_queue(self):
        """Four arrays of FQMAX in aux 0 after the drawers, before the
        write-expensive $0400 (docs/MEMORY_MAP.md section 5), a byte index
        each; the port's kind has K_FUZZ's size and fits the draw pass's
        table (an even kind below K_OVL)."""
        arrays = (L.FQCOL, L.FQROW, L.FQCNT, L.FQPOS)
        self.assertEqual(arrays[0], L.FUZZQ)
        for first, second in zip(arrays, arrays[1:]):
            self.assertEqual(second - first, L.FQMAX)
        self.assertEqual(arrays[-1] + L.FQMAX, L.FUZZQ_END)
        self.assertLessEqual(L.AUXCODE_END, L.FUZZQ)
        self.assertLessEqual(L.FUZZQ_END, 0x0400)
        self.assertLess(L.FQMAX, 256)
        self.assertIn((L.FUZZQ, L.FUZZQ_END), L.ALLOWED_AUX0)
        self.assertEqual(L.SIZES[L.K_FUZZNOW], L.SIZES[L.K_FUZZ])
        self.assertNotIn(L.K_FUZZNOW, L.KIND_NAMES)
        self.assertTrue(L.K_FUZZNOW % 2 == 0 and L.K_FUZZNOW < L.K_OVL)

    def test_the_include_names_every_constant(self):
        text = L.include_text()
        for name, value in L.CONSTANTS:
            self.assertIn('%-16s= $%04X' % (name, value), text)


@needs_cc65
class Build(unittest.TestCase):

    def setUp(self):
        self.build = build()

    def test_builds_without_warnings(self):
        out = Path(tempfile.mkdtemp())
        try:
            output = make(out)
        finally:
            shutil.rmtree(str(out))
        self.assertNotIn('arning', output)
        self.assertNotIn('rror', output)

    def byte(self, address):
        return self.build.lc[address - 0xD000]

    def test_texture_row_blocks(self):
        for row in range(L.VIEW_ROWS):
            at = L.tex_entry(row)
            first = 0x98 if row % 2 == 0 else 0xA5      # TYA, LDA zp
            self.assertEqual(self.byte(at), first, row)
            store = at + (12 if row % 2 == 0 else 18)   # STA abs,X
            self.assertEqual(self.byte(store), 0x9D, row)
            target = self.byte(store + 1) | self.byte(store + 2) << 8
            self.assertEqual(target, L.row_address(row), row)
        self.assertEqual(self.byte(L.TEXLAND), 0x60)
        self.assertEqual(L.tex_entry(1) - L.tex_entry(0), L.EVEN_BYTES)
        self.assertEqual(L.tex_entry(2) - L.tex_entry(0), L.PAIR_BYTES)

    def test_fill_chains(self):
        for base, parity in ((L.FILLE, 0), (L.FILLO, 1)):
            for row in range(parity, L.VIEW_ROWS, 2):
                at = base + 3 * (row >> 1)
                self.assertEqual(self.byte(at), 0x9D)
                self.assertEqual(self.byte(at + 1) | self.byte(at + 2) << 8,
                                 L.row_address(row))
            self.assertEqual(self.byte(base + L.FILL_LAND), 0x60)

    def test_main_tables(self):
        t = self.build.main_tables
        for level in range(L.CMAP_LEVELS):
            self.assertEqual(t[L.CMPA - L.MAIN_TABLES + level],
                             L.cmap_page_a(level))
            self.assertEqual(t[L.CMPB - L.MAIN_TABLES + level],
                             L.cmap_page_b(level))
        for row in range(L.VIEW_ROWS + 1):
            entry = t[L.TEXLO - L.MAIN_TABLES + row] | \
                t[L.TEXHI - L.MAIN_TABLES + row] << 8
            self.assertEqual(entry, L.tex_entry(row))

    def test_aux_tables(self):
        t = self.build.aux_tables
        for row in range(200):
            address = t[L.ROWLO - L.AUX_TABLES + row] | \
                t[L.ROWHI - L.AUX_TABLES + row] << 8
            self.assertEqual(address, L.row_address(row))
        self.assertEqual(tuple(t[L.FZDIR - L.AUX_TABLES:L.FZDIR -
                                 L.AUX_TABLES + 50]), L.FUZZ_DIR)

    def test_rowgen_is_deterministic(self):
        self.assertEqual(rowgen.rows_text(), rowgen.rows_text())


class StrayWrites(unittest.TestCase):
    """The snapshot comparison of the harness, on made-up memory."""

    def test_page_one(self):
        """The descriptors and the copy loop, the stack from $01C0 to the
        caller's S, and nothing else of page 1: not the bytes between the
        copy loop and the stack floor, not the caller's frame above S."""
        before = bytes(a2run.RAM_SIZE)
        sp = L.DRV_STACK
        for address, stray in ((L.DESC, 0), (L.P1CODE_END - 1, 0),
                               (L.P1CODE_END, 1), (L.STACK_FLOOR - 1, 1),
                               (L.STACK_FLOOR, 0), (0x0100 + sp, 0),
                               (0x0100 + sp + 1, 1), (0x01FF, 1)):
            after = bytearray(before)
            after[address] = 0x77
            count, _ = a2run.stray_writes(before, bytes(after),
                                          a2run.allowed_offsets(sp))
            self.assertEqual(count, stray, '$%04X' % address)
        with self.assertRaises(ValueError):
            a2run.allowed_offsets(0xB0)         # S below the floor

    def test_outside_and_inside(self):
        before = bytearray(a2run.RAM_SIZE)
        after = bytearray(before)
        after[a2run.aux_offset(0, L.SCREEN + 5)] = 1      # allowed
        after[L.STAGE + 100] = 2                           # allowed
        after[a2run.aux_offset(0, L.FUZZQ)] = 7            # the fuzz queue
        after[a2run.aux_offset(0, L.FUZZQ_END - 1)] = 7
        self.assertEqual(a2run.stray_writes(bytes(before), bytes(after))[0],
                         0)
        after[a2run.aux_offset(0, L.VIEW_END)] = 3   # aux 0 past the view
        after[0x1000] = 4                      # main spans
        after[a2run.LC + 0x1000] = 5           # the card at $D000
        after[a2run.aux_offset(7, 0x4000)] = 6
        after[a2run.aux_offset(0, L.FUZZQ - 1)] = 8     # the drawers
        after[a2run.aux_offset(0, L.FUZZQ_END)] = 8     # past the queue
        after[L.FUZZQ] = 8                     # main at the queue's address
        count, shown = a2run.stray_writes(bytes(before), bytes(after))
        self.assertEqual(count, 7)
        self.assertIn('aux 0 $02BF: $00 -> $08', shown)
        self.assertIn('aux 0 $0400: $00 -> $08', shown)
        self.assertIn('main $02C0: $00 -> $08', shown)
        self.assertIn('aux 0 $8900: $00 -> $03', shown)
        self.assertIn('main $1000: $00 -> $04', shown)
        self.assertIn('card $D000: $00 -> $05', shown)
        self.assertIn('aux 7 $4000: $00 -> $06', shown)

    def test_write_log_ranges(self):
        """a2run.stray_ranges, a2vm's --write-log ranges, holds exactly the
        main and aux 0 bytes allowed_offsets() leaves out, and banks 1-127
        whole."""
        sp = L.DRV_STACK
        allowed = a2run.allowed_offsets(sp)
        inside = {'main': bytearray(0x10000), 'aux0': bytearray(0x10000)}
        banks = None
        for item in a2run.stray_ranges(sp).split(','):
            where, _, span = item.partition(':')
            if where == 'aux1-127':
                banks = where
                continue
            low, high = (int(x, 16) for x in span.split('-'))
            inside[where][low:high + 1] = b'\1' * (high - low + 1)
        self.assertEqual(banks, 'aux1-127')
        for name, base in (('main', a2run.MAIN), ('aux0', a2run.AUX)):
            for address in range(0x10000):
                offset = base + address
                ok = any(a <= offset < b for a, b in allowed)
                self.assertEqual(bool(inside[name][address]), not ok,
                                 '%s $%04X' % (name, address))

    def test_read_write_log(self):
        path = Path(tempfile.mkdtemp(dir=str(ROOT / 'build'))) / 'w.log'
        self.addCleanup(shutil.rmtree, str(path.parent))
        path.write_text('# a2vm write-log 1\n'
                        'w 120 118 F9B2 1A80 main 0 1A80 A5 A5\n'
                        'w 130 125 0808 C005 io - - - 11\n'
                        'w 140 131 080B 4000 aux 5 4000 00 22\n')
        writes = a2run.read_write_log(path)
        self.assertEqual([w.describe() for w in writes],
                         ['main $1A80: $A5 -> $A5 (pc $F9B2)',
                          'I/O: - -> $11 (pc $0808)',
                          'aux 5 $4000: $00 -> $22 (pc $080B)'])
        self.assertEqual((writes[0].clock, writes[2].address), (120, 0x4000))


# ---------------------------------------------------------------------------
# the loader
# ---------------------------------------------------------------------------

class FuzzMark(unittest.TestCase):
    """loader.mark_fuzz: a shadow of rows a .. e - 1 is drawn in place
    (K_FUZZNOW) when a later record of its column paints a row from a - 1
    to e."""

    @staticmethod
    def rec(kind, *fields):
        size = L.SIZES[kind]
        data = bytes((kind,) + fields) + bytes(size - 1 - len(fields))
        return loader.Rec(0, 0, kind, data, 0, 0)

    def marked(self, column):
        out = loader.mark_fuzz([column])[0]
        self.assertEqual([r.kind for r in out], [r.kind for r in column])
        return [r.data[0] == L.K_FUZZNOW for r in out]

    def test_the_rows_around_a_shadow(self):
        shadow = self.rec(L.K_FUZZ, 50, 10, 3)          # rows 50-59
        cases = [   # (the later record, marked)
            (self.rec(L.K_TEX, 40, 49), False),          # to row 48
            (self.rec(L.K_TEX, 40, 50), True),           # row 49: read
            (self.rec(L.K_FILL, 60, 70), True),          # row 60: read
            (self.rec(L.K_FILL, 61, 70), False),
            (self.rec(L.K_TEXC, 55, 56), True),          # inside
            (self.rec(L.K_TEX, 0, 168), True),           # over it
            (self.rec(L.K_OVL, 49, 0x0F, 0x10), True),
            (self.rec(L.K_OVL, 48, 0x0F, 0x10), False),
            (self.rec(L.K_OVL, 60, 0x0F, 0x10), True),
            (self.rec(L.K_OVL, 61, 0x0F, 0x10), False),
            (self.rec(L.K_FUZZ, 40, 10, 0), True),       # rows 40-49
            (self.rec(L.K_FUZZ, 40, 9, 0), False),       # to 48: it reads
                                                         #   49, unwritten
            (self.rec(L.K_FUZZ, 60, 5, 0), True),
            (self.rec(L.K_FUZZ, 61, 5, 0), False),
        ]
        for later, marked in cases:
            got = self.marked([shadow, later])
            self.assertEqual(got[0], marked, later.data.hex())
            self.assertFalse(got[1])            # nothing after it
            # a record before the shadow never marks it
            self.assertEqual(self.marked([later, shadow])[1], False)

    def test_only_its_column_and_the_last_record_count(self):
        a = self.rec(L.K_FUZZ, 10, 5, 0)                # rows 10-14
        b = self.rec(L.K_FUZZ, 30, 5, 0)
        near = self.rec(L.K_FILL, 15, 20)
        self.assertEqual(self.marked([a, b, near]), [True, False, False])
        self.assertEqual(self.marked([a, near, b]), [True, False, False])
        cols = loader.mark_fuzz([[a], [near]])
        self.assertEqual(cols[0][0].data[0], L.K_FUZZ)  # another column
        # the other fields stay
        self.assertEqual(loader.mark_fuzz([[a, near]])[0][0].data[1:],
                         a.data[1:])


@needs_cc65
@needs_linkmap
@needs_captures
class Loader(unittest.TestCase):

    def test_batches_and_texels(self):
        build_ = build()
        for name in ('still-1', 'demo-10'):
            capture = loader.read_capture(CAPTURES / name)
            package = loader.build_package(capture, build_)
            cols = loader.columns(capture)
            total = sum(len(r.data) for c in cols for r in c)
            self.assertEqual(sum(len(b.records) for b in package.batches),
                             total)
            self.assertEqual(total + sum(
                2 for r in lists.walk(capture.memory.get,
                                      lists.layout(capture.units))
                if r.kind == 'K_NEXT'), capture.manifest['records']['bytes'])
            first = 0
            for b in package.batches:
                self.assertEqual(b.first, first)
                self.assertLessEqual(len(b.records), L.RECBUF_SIZE)
                first = b.end
            self.assertEqual(first, L.COLUMNS)
            for c in cols:
                for r in c:
                    if r.kind not in (L.K_TEX, L.K_TEXC):
                        continue
                    bank, address = package.texels.where[r.origin]
                    self.assertIn(bank, range(1, 1 + L.TEXEL_BANKS))
                    self.assertGreaterEqual(address, L.BANK_ROOM[0])
                    self.assertLessEqual(address + 128, L.BANK_ROOM[1])
                    self.assertEqual(
                        bytes(package.texels.banks[bank][address:
                                                         address + 128]),
                        capture.memory.get(r.texels, 128))
        self.assertEqual(package.counts['batches'], 2)       # demo-10

    def test_the_image_fills_what_the_frame_leaves(self):
        """Every byte the frame and the build do not define takes the fill,
        the free and forbidden bytes between the tables included; without
        a fill they are not in the image at all."""
        build_ = build()
        capture = loader.read_capture(CAPTURES / 'still-1')
        image = loader.build_package(capture, build_, fill=0xA5).image
        ram = bytearray(a2run.RAM_SIZE)
        records = disk.image_records(image)
        for kind, bank, address, data in records:
            at = {loader.ImageWriter.MAIN: a2run.MAIN + address,
                  loader.ImageWriter.LC: a2run.LC + address - 0xC000,
                  loader.ImageWriter.LC1: a2run.LC1 + address - 0xD000,
                  loader.ImageWriter.AUX: a2run.aux_offset(bank, address)
                  }[kind]
            ram[at:at + len(data)] = data
        for offset in (0x1A80, 0x0878, 0x087F, 0x09A9, 0x0AF3,
                       a2run.LC + 0xE480 - 0xC000,
                       a2run.LC + 0xDBD1 - 0xC000,
                       a2run.LC1 + 0x0000, a2run.aux_offset(0, 0xA000),
                       a2run.aux_offset(0, 0x0C00),
                       a2run.aux_offset(90, 0x4000)):
            self.assertEqual(ram[offset], 0xA5, a2run.describe(offset))
        for start, end in L.MAIN_TABLE_RANGES:
            self.assertEqual(ram[start:end],
                             build_.main_tables[start - L.MAIN_TABLES:
                                                end - L.MAIN_TABLES])
        # no fill: nothing but the frame, and never the forbidden bytes
        plain = loader.build_package(capture, build_).image
        for kind, bank, address, data in disk.image_records(plain):
            if kind != loader.ImageWriter.MAIN:
                continue
            for start, end in L.FORBIDDEN_MAIN:
                if address < end and start < address + len(data):
                    # colormap B level 0 covers $4078-$407F: data, loaded
                    # by PRIVATE on the card (tools/native/disk.py)
                    self.assertEqual(address & 0xFF00, 0x4000,
                                     '$%04X' % address)

    def test_screen_stores_model(self):
        """The model of upstream's screen stores: every row drawn, less the
        rows the covered-range cuts take."""
        build_ = build()
        capture = loader.read_capture(CAPTURES / 'still-1')
        package = loader.build_package(capture, build_)
        self.assertEqual(package.counts['screen_stores'], 8519)
        cols = loader.columns(capture)
        drawn = sum(r.data[2] - r.data[1] if r.kind != L.K_FUZZ else
                    r.data[2] for c in cols for r in c
                    if r.kind != L.K_OVL) + package.counts['K_OVL']
        self.assertGreater(drawn, package.counts['screen_stores'])

    def test_records_the_replay_cannot_draw_are_refused(self):
        good = {L.K_TEX: bytes([L.K_TEX, 10, 20]) + bytes(8),
                L.K_TEXC: bytes([L.K_TEXC, 0, 168]) + bytes(4),
                L.K_FILL: bytes([L.K_FILL, 167, 168, 1, 2]),
                L.K_FUZZ: bytes([L.K_FUZZ, 1, 166, 49]),
                L.K_OVL: bytes([L.K_OVL, 167, 0x0F, 0x30])}
        for kind, data in good.items():
            self.assertIsNone(loader.check_record(kind, data),
                              L.KIND_NAMES[kind])
        bad = [(L.K_TEX, bytes([L.K_TEX, 20, 20]) + bytes(8)),
               (L.K_TEX, bytes([L.K_TEX, 20, 19]) + bytes(8)),
               (L.K_TEXC, bytes([L.K_TEXC, 100, 169]) + bytes(4)),
               (L.K_FILL, bytes([L.K_FILL, 5, 5, 1, 2])),
               (L.K_FUZZ, bytes([L.K_FUZZ, 10, 0, 0])),
               (L.K_FUZZ, bytes([L.K_FUZZ, 0, 5, 0])),
               (L.K_FUZZ, bytes([L.K_FUZZ, 161, 7, 0])),
               (L.K_OVL, bytes([L.K_OVL, 168, 0, 0]))]
        for kind, data in bad:
            self.assertIsNotNone(loader.check_record(kind, data),
                                 data.hex())
        # and columns() refuses a frame with one
        capture = loader.read_capture(CAPTURES / 'still-1')
        lay = lists.layout(capture.units)
        first = next(r for r in lists.walk(capture.memory.get, lay)
                     if r.kind == 'K_TEX')
        at = lay.recbase + (first.page << 8) + first.offset
        broken = capture.memory
        saved = broken.get(at + L.FIELDS['R_END'], 1)
        broken.put(at + L.FIELDS['R_END'],
                   bytes([first.data[L.FIELDS['R_ROW']]]))
        try:
            with self.assertRaises(loader.LoadError):
                loader.columns(capture)
        finally:
            broken.put(at + L.FIELDS['R_END'], saved)

    def test_a_frame_needs_its_fuzz_table(self):
        capture = loader.read_capture(CAPTURES / 'still-1')
        manifest = dict(capture.manifest)
        manifest['files'] = [f for f in manifest['files']
                             if f['name'] != 'fuzz']
        with self.assertRaises(loader.LoadError):
            loader.fuzz_table(capture._replace(manifest=manifest))


# ---------------------------------------------------------------------------
# the replay against upstream's
# ---------------------------------------------------------------------------

def check_all(dirs, build_, out):
    return [replay_check.check_frame(d, out, build_) for d in dirs]


@needs_cc65
@needs_a2vm
@needs_ref816
@needs_linkmap
@needs_captures
class CapturedFrames(unittest.TestCase):

    def test_every_captured_frame(self):
        out = Path(tempfile.mkdtemp(dir=str(ROOT / 'build' / 'native')))
        try:
            results = check_all(capture_dirs(), build(), out)
        finally:
            shutil.rmtree(str(out))
        self.assertEqual(len(results), 15)
        names = [r['name'] for r in results]
        for prefix, count in (('still-', 3), ('demo-', 11), ('e1m3-', 1)):
            self.assertEqual(sum(n.startswith(prefix) for n in names),
                             count)
        for r in results:
            self.assertNotIn('error', r, r['name'])
            for run in ('captured', 'poisoned'):
                self.assertEqual(r[run]['ended'], 'halt', r['name'])
                self.assertEqual(r[run]['differing_bytes'], 0,
                                 (r['name'], run, r[run]['first']))
                self.assertEqual(r[run]['stray_writes'], 0,
                                 (r['name'], run, r[run]['stray_first']))
                self.assertEqual(r[run]['stray_logged'], 0,
                                 (r['name'], run,
                                  r[run]['stray_logged_first']))
                self.assertEqual(r[run]['switch_changes'], [], r['name'])
                self.assertEqual(r[run]['shr_writes'],
                                 r[run]['stores_expected'], r['name'])
                self.assertEqual(r[run]['other_video_writes'], 0, r['name'])
            # the poisoned truth is not the poison: the replay drew
            self.assertGreater(r['poisoned']['truth_changed_from_poison'],
                               8000, r['name'])
            self.assertTrue(r['ok'], r['name'])
            self.assertGreater(r['ms_f121'], 0)
            self.assertGreater(r['ms_fastpath'], 0)
        batches = {r['name']: r['records']['batches'] for r in results}
        self.assertEqual(batches['demo-10'], 2)
        self.assertEqual(batches['demo-11'], 2)
        self.assertGreater(sum(r['records']['K_FUZZ'] for r in results), 0)


@needs_cc65
@needs_a2vm
@needs_ref816
@needs_linkmap
@needs_base
class SyntheticStreams(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(dir=str(ROOT / 'build' / 'native')))
        units = loader.load_units()
        header = synth.base_image()
        base = synth.refimage.load(header)
        cls.dirs = []
        for style in synth.STYLES:
            directory = cls.out / ('synth-' + style)
            synth.write_stream(directory, style, 7000 +
                               synth.STYLES.index(style), units, base,
                               header)
            cls.dirs.append(directory)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.out))

    def test_the_streams_cover_the_format(self):
        units = loader.load_units()
        kinds = {k: 0 for k in L.KIND_NAMES}
        fuzz_positions, levels, parities, rows = set(), set(), set(), set()
        cuts = pages = 0
        covers = {L.K_TEX: 0, L.K_TEXC: 0}
        behind_skipped = all_start_in = 0
        for d in self.dirs:
            capture = loader.read_capture(d, units)
            pages += capture.manifest['records']['extra_pages']
            cuts += capture.manifest['records']['cuts']
            cols = loader.columns(capture)
            texels = loader.place_texels(capture, cols, 1)
            _, w_address = loader.make_batches(cols, texels)
            state = loader.convert_state(capture, cols, w_address)
            for c, recs in enumerate(cols):
                c0 = state.covered[c]
                c1 = state.covered[L.COLUMNS + c]
                if not (c1 and c0 < c1):
                    continue
                word = state.covered[2 * L.COLUMNS + c] | \
                    state.covered[3 * L.COLUMNS + c] << 8
                cover = next(r for r in recs if w_address[r.origin] == word)
                covers[cover.kind] += 1
                csf = csi = 0
                for x in recs:
                    if x is cover:
                        break
                    if x.kind == L.K_TEX:
                        csf, csi = x.data[5], x.data[6]
                    a, e = x.data[1], x.data[2]
                    # texStart with all 128 texels copied, an odd first
                    # row, an even end of the range
                    if (x.kind in (L.K_TEX, L.K_TEXC) and c0 <= a < c1 < e
                            and a % 2 == 1 and c1 % 2 == 0 and
                            loader.stage_need(x.data, csf, csi)[0] == 'all'):
                        all_start_in += 1
                for x, y in zip(recs, recs[1:]):
                    if y is cover:
                        break
                    if (x.kind == L.K_TEX and y.kind == L.K_TEXC and
                            c0 <= x.data[1] and x.data[2] <= c1 and
                            y.data[2] > c1):
                        behind_skipped += 1
            for c in cols:
                for r in c:
                    kinds[r.kind] += 1
                    if r.kind == L.K_FUZZ:
                        fuzz_positions.add(r.data[L.FIELDS['R_POS']])
                    if r.kind == L.K_TEX:
                        levels.add(r.data[L.FIELDS['R_CMP']] -
                                   L.CMAP_FIRST)
                    if r.kind in (L.K_TEX, L.K_TEXC, L.K_FILL):
                        a, e = r.data[1], r.data[2]
                        parities.add((a % 2, e % 2))
                        rows.update((a, e - 1))
        for kind in (L.K_TEX, L.K_TEXC, L.K_FILL, L.K_FUZZ, L.K_OVL):
            self.assertGreater(kinds[kind], 50, L.KIND_NAMES[kind])
        self.assertEqual(fuzz_positions, set(range(50)))
        self.assertEqual(levels, set(range(L.CMAP_LEVELS)))
        self.assertEqual(parities, {(0, 0), (0, 1), (1, 0), (1, 1)})
        self.assertTrue({0, 1, 166, 167} <= rows)
        self.assertGreater(cuts, 100)
        self.assertGreater(pages, 0)
        # covering records of both kinds; K_TEXC chains that go on past
        # the range behind a K_TEX the range hides
        self.assertGreater(covers[L.K_TEX], 50)
        self.assertGreater(covers[L.K_TEXC], 20)
        self.assertGreater(behind_skipped, 10)
        self.assertGreater(all_start_in, 5)

    def test_every_stream_equals_upstream(self):
        results = check_all(self.dirs, build(), self.out / 'check')
        for r in results:
            self.assertNotIn('error', r, r['name'])
            for run in ('captured', 'poisoned'):
                self.assertEqual(r[run]['differing_bytes'], 0,
                                 (r['name'], run, r[run]['first']))
                self.assertEqual(r[run]['stray_writes'], 0,
                                 (r['name'], run, r[run]['stray_first']))
                self.assertEqual(r[run]['stray_logged'], 0,
                                 (r['name'], run,
                                  r[run]['stray_logged_first']))
                self.assertEqual(r[run]['shr_writes'],
                                 r[run]['stores_expected'], r['name'])
                self.assertEqual(r[run]['other_video_writes'], 0, r['name'])
            self.assertTrue(r['ok'], r['name'])
        self.assertGreater(max(r['records']['batches'] for r in results), 1)
        self.assertGreater(max(r['records']['strips'] for r in results), 1)
        # the fuzz queue: fuzzedge's shadows are marked or queued, never
        # drawn in place for want of room; fuzzfull fills the queue
        # in two strips, and has marked ones
        counts = {r['name']: r['records'] for r in results}
        edge, full = counts['synth-fuzzedge'], counts['synth-fuzzfull']
        self.assertGreater(edge['fuzz_now'], 50)
        self.assertGreater(edge['fuzz_queued'], 50)
        self.assertEqual(edge['fuzz_full'], 0)
        self.assertGreaterEqual(full['strips'], 2)
        self.assertGreater(full['fuzz_full'], 2 * L.FQMAX)
        self.assertEqual(full['fuzz_queued'], full['strips'] * L.FQMAX)
        self.assertGreater(full['fuzz_now'], 10)


# ---------------------------------------------------------------------------
# the checks can fail
# ---------------------------------------------------------------------------

# Bugs planted in a scratch copy of replay.s: (name, [(the text replaced,
# its replacement), ...], the frame, what must catch it: 'pixels' the
# screen against the truth, 'stray' the snapshot comparison, 'logged' a2vm's
# write log alone (the snapshots cannot see the store), 'stores' the count
# of SHR writes against upstream's screen stores). A frame named synth-* is
# a synthetic stream of tools/native/synth.py.
DRAW_END = '@done:  jsr     fuzz_queue\n        sta     WRMAIN\n        ldx     sc0\n'
BUGS = (
    ('fill bytes by the wrong parity',
     [('@draw:  lda     ta                      ; the even rows\n'
       '        inc     a\n',
       '@draw:  lda     ta                      ; the even rows\n'
       '        eor     #1\n'
       '        inc     a\n')], 'demo-01', 'pixels'),
    ('a stray store into the fill spans',
     [(DRAW_END, DRAW_END.replace('ldx', 'stz     $1000\n        ldx'))],
     'still-1', 'stray'),
    ('a row block left patched',
     [('        jsr     jtent\n        lda     xop\n        sta     (xo)\n'
       '@skip:  lda     dsz\n',
       '        jsr     jtent\n        lda     xop\n'
       '@skip:  lda     dsz\n')], 'still-1', 'stray'),
    ('an odd first row without its rounded carry',
     [('        inc     a\n:       and     #$7F\n        tay\n@enter:',
       ':       and     #$7F\n        tay\n@enter:')], 'demo-01', 'pixels'),
    # zero stored where the frame leaves memory undefined (the fill)
    ('a zero stored into main $1A80 (the hot game globals)',
     [(DRAW_END, DRAW_END.replace('ldx', 'stz     $1A80\n        ldx'))],
     'still-1', 'stray'),
    ('a zero stored into aux 0 $A000 during the draw',
     [(DRAW_END, DRAW_END.replace('@done:  jsr', '@done:  stz     $A000\n'
                                  '        jsr'))], 'still-1', 'stray'),
    ('a zero stored into the card at $E480 (the player\'s lists)',
     [(DRAW_END, DRAW_END.replace('ldx', 'stz     $E480\n        ldx'))],
     'still-1', 'stray'),
    ('a store into the caller\'s stack frame',
     [('nat_replay:\n        sta     gcol\n',
       'nat_replay:\n        phx\n        tsx\n        stz     $0104,x\n'
       '        plx\n        sta     gcol\n')], 'still-1', 'stray'),
    ('a store below the stack floor',
     [(DRAW_END, DRAW_END.replace('ldx', 'stz     $01B8\n        ldx'))],
     'still-1', 'stray'),
    # a store of the value already there (A is free at the draw's end)
    ('the value of main $1A80 stored back into it',
     [(DRAW_END, DRAW_END.replace('ldx', 'lda     $1A80\n        sta     '
                                  '$1A80\n        ldx'))],
     'still-1', 'logged'),
    ('no covered-range cut at all',
     [('        lda     CVEND,x                 ; a covered range?\n'
       '        beq     dloop\n',
       '        lda     CVEND,x                 ; a covered range?\n'
       '        bra     dloop\n')], 'still-1', 'stores'),
    # the covered-range cases, on the synthetic stream made for them
    ('the cut skipped', [
        ('        lda     CVEND,x                 ; a covered range?\n'
         '        beq     dloop\n',
         '        lda     CVEND,x                 ; a covered range?\n'
         '        bra     dloop\n')], 'synth-rows', 'stores'),
    ('texStart: the position not advanced',
     [('        jsr     advance                 ; rows c1 .. e - 1\n', '')],
     'synth-rows', 'pixels'),
    ('texStart: advanced one row too many',
     [('advance:\n        lda     cv1\n        sec\n        sbc     ta\n',
       'advance:\n        lda     cv1\n        sec\n        sbc     ta\n'
       '        inc     a\n')], 'synth-rows', 'pixels'),
    ('fillStart: the bytes swapped when the first row changes',
     [('        lda     cv1\n        sta     ta\n        bra     @draw\n'
       '@low:   lda     te\n',
       '        lda     cv1\n        sta     ta\n        lda     fr\n'
       '        ldx     sf2\n        sta     sf2\n        stx     fr\n'
       '        bra     @draw\n@low:   lda     te\n'),
      # (room in the draw pass's 512 bytes for the four instructions)
      ('        cmp     #K_OVL+1\n        bcs     bad\n        bit     #1\n'
       '        bne     bad\n', '')], 'synth-rows', 'pixels'),
    ('a texture ending in the range cut one row short',
     [(':       lda     cv0                     ; rows a .. c0 - 1\n'
       '        sta     te\n',
       ':       lda     cv0                     ; rows a .. c0 - 1\n'
       '        dec     a\n        sta     te\n')], 'synth-rows', 'pixels'),
    # the fuzz queue, on the synthetic streams made for it
    ('a K_FUZZNOW queued as a K_FUZZ',
     [('        cmp     #K_FUZZ\n'
       '        bne     @now                    ; K_FUZZNOW: in place\n', '')],
     'synth-fuzzedge', 'pixels'),
    ('the queue never full',
     [('        cpx     #FQMAX\n'
       '        bcs     @now                    ; the queue is full: in '
       'place\n', '')], 'synth-fuzzfull', 'stray'),
    ('a record the full queue has no room for dropped',
     [('        bcs     @now                    ; the queue is full: in '
       'place\n', '        bcs     @next\n')], 'synth-fuzzfull', 'pixels'),
    ('the queue never drawn',
     [(DRAW_END, DRAW_END.replace('@done:  jsr     fuzz_queue\n',
                                  '@done:\n'))], 'synth-fuzzfull', 'pixels'),
)


class TheChecksCanFail(unittest.TestCase):
    """Each planted bug fails its frame's check, by the check named."""

    def plant(self, bugs, frames):
        scratch = Path(tempfile.mkdtemp(dir=str(ROOT / 'build' / 'native')))
        try:
            for number, (name, edits, frame, caught) in enumerate(bugs):
                src = scratch / ('src-%d' % number)
                shutil.copytree(str(SRC), str(src))
                text = (src / 'replay.s').read_text()
                for old, new in edits:
                    self.assertEqual(text.count(old), 1, name)
                    text = text.replace(old, new)
                (src / 'replay.s').write_text(text)
                obj = scratch / ('obj-%d' % number)
                make(obj, src)
                bad = loader.read_build(obj)
                r = replay_check.check_frame(frames[frame],
                                             scratch / 'check', bad)
                self.assertNotIn('error', r, name)
                self.assertFalse(r['ok'], name)
                runs = (r['captured'], r['poisoned'])
                for x in runs:
                    self.assertEqual(x['ended'], 'halt', name)
                if caught == 'pixels':
                    self.assertGreater(sum(x['differing_bytes']
                                           for x in runs), 0, name)
                elif caught == 'stray':
                    self.assertGreater(sum(x['stray_writes'] for x in runs),
                                       0, name)
                elif caught == 'logged':
                    self.assertEqual(sum(x['stray_writes'] for x in runs),
                                     0, name)
                    self.assertGreater(sum(x['stray_logged'] for x in runs),
                                       0, name)
                else:
                    self.assertTrue(any(x['shr_writes'] !=
                                        x['stores_expected'] for x in runs),
                                    name)
        finally:
            shutil.rmtree(str(scratch))

    @needs_cc65
    @needs_a2vm
    @needs_ref816
    @needs_linkmap
    @needs_captures
    def test_planted_bugs_are_caught(self):
        self.plant([b for b in BUGS if not b[2].startswith('synth-')],
                   {d.name: d for d in capture_dirs()})

    @needs_cc65
    @needs_a2vm
    @needs_ref816
    @needs_linkmap
    @needs_base
    def test_planted_cut_bugs_are_caught_on_the_rows_stream(self):
        """synth-rows alone must catch every covered-range bug: one case a
        column, nothing repainting the rows a case keeps or loses."""
        out = Path(tempfile.mkdtemp(dir=str(ROOT / 'build' / 'native')))
        try:
            header = synth.base_image()
            directory = out / 'synth-rows'
            synth.write_stream(directory, 'rows',
                               7000 + synth.STYLES.index('rows'),
                               loader.load_units(),
                               synth.refimage.load(header), header)
            self.plant([b for b in BUGS if b[2] == 'synth-rows'],
                       {'synth-rows': directory})
        finally:
            shutil.rmtree(str(out))

    @needs_cc65
    @needs_a2vm
    @needs_ref816
    @needs_linkmap
    @needs_base
    def test_planted_fuzz_queue_bugs_are_caught(self):
        """synth-fuzzedge and synth-fuzzfull catch the queue's bugs, and
        two bugs of the loader's mark on fuzzedge: the mark missing (every
        shadow queued, the later records drawn before the ones they
        touch), and a mark that ignores later shadows (a shadow queued
        behind a later one that a third record makes draw in place)."""
        out = Path(tempfile.mkdtemp(dir=str(ROOT / 'build' / 'native')))
        try:
            header = synth.base_image()
            dirs = {}
            for style in ('fuzzedge', 'fuzzfull'):
                dirs['synth-' + style] = out / ('synth-' + style)
                synth.write_stream(dirs['synth-' + style], style,
                                   7000 + synth.STYLES.index(style),
                                   loader.load_units(),
                                   synth.refimage.load(header), header)
            self.plant([b for b in BUGS if b[2] in dirs], dirs)
            saved = loader.mark_fuzz

            def fuzz_blind(cols):
                """The mark with every later K_FUZZ left out."""
                marked = []
                for column in cols:
                    marked.append([saved([[r] + [x for x in column[i + 1:]
                                                 if x.kind != L.K_FUZZ]])
                                   [0][0] if r.kind == L.K_FUZZ else r
                                   for i, r in enumerate(column)])
                return marked

            good = replay_check.check_frame(dirs['synth-fuzzedge'],
                                            out / 'check', build())
            self.assertTrue(good['ok'])
            for mark in (lambda cols: cols, fuzz_blind):
                loader.mark_fuzz = mark
                try:
                    r = replay_check.check_frame(dirs['synth-fuzzedge'],
                                                 out / 'check', build())
                finally:
                    loader.mark_fuzz = saved
                self.assertLess(r['records']['fuzz_now'],
                                good['records']['fuzz_now'])
                for run in ('captured', 'poisoned'):
                    self.assertGreater(r[run]['differing_bytes'], 0, run)
            # the blind mark's pixels differ by the order alone: no shadow
            # was drawn in place for want of room
            self.assertEqual(r['records']['fuzz_full'], 0)
        finally:
            shutil.rmtree(str(out))


# ---------------------------------------------------------------------------
# the card run, on a2vm
# ---------------------------------------------------------------------------

class CardTimes(unittest.TestCase):

    def test_milliseconds_a_run(self):
        """disk.run_ms, the runner's tenths: VBLs * 20 ms / REPS, rounded
        to 0.1 ms, at most 999.9; at 200 runs a VBL is 0.1 ms."""
        self.assertEqual(disk.REPS, 200)
        self.assertEqual(disk.run_ms(362, 200), 36.2)
        self.assertEqual(disk.run_ms(0, 200), 0.0)
        self.assertEqual(disk.run_ms(7, 3), 46.7)       # 46.67
        self.assertEqual(disk.run_ms(1, 3), 6.7)        # 6.67
        self.assertEqual(disk.run_ms(1, 6), 3.3)        # 3.33
        self.assertEqual(disk.run_ms(65535, 200), 999.9)
        self.assertEqual(disk.run_ms(1540, 32), 962.5)

    def test_what_fails_the_check(self):
        """disk.py --check exits 1 on each check_failures line: a base
        loop no faster than the loop with the replay among them."""
        good = {'name': 'f', 'ok': True, 'crc': '0', 'expected': '0',
                'restore': {'ok': True}, 'shown_ok': True, 'shown': [],
                'vbls_loop': 402, 'vbls_without': 266, 'ms_loop': 40.2,
                'ms_without': 26.6, 'ms': 13.6}
        self.assertEqual(disk.check_failures([good]), [])
        for change in ({'vbls_without': 402}, {'vbls_without': 403},
                       {'ok': False}, {'shown_ok': False}):
            bad = dict(good, **change)
            self.assertEqual(len(disk.check_failures([good, bad])), 1,
                             change)

    def test_the_check_is_bounded(self):
        # the a2vm check's cycle bound covers the runs it times
        self.assertGreater(disk.check_cycles(15, 200, 150),
                           15 * 2 * 200 * 0.12 * disk.FABRIC_HZ)


@needs_cc65
@needs_a2vm
@needs_linkmap
@needs_captures
class CardDisk(unittest.TestCase):

    def test_the_disk_runs_on_a2vm(self):
        master = disk.disk_writer().DEFAULT_MASTER
        if not master.is_file():
            self.skipTest('%s is missing (appletini-one)' % master)
        build()
        out = Path(tempfile.mkdtemp(dir=str(ROOT / 'build' / 'native')))
        try:
            dirs = [CAPTURES / 'still-1', CAPTURES / 'demo-11']
            card = loader.read_build(OBJ, 'card')
            frames = disk.prepare(dirs, card)
            # 3 runs: VBLs * 200 / 3 needs the runner's rounding
            files = disk.files_of(frames, OBJ, 3, 2)
            disk.build_disk(files, out / 'T.hdv')
            image = (out / 'T.hdv').read_bytes()
            self.assertEqual(len(image) % 512, 0)
            results = disk.check(frames, files, OBJ, out / 'run', 'f121')
            for r, d in zip(results, dirs):
                truth = (d / 'screen-after.bin').read_bytes()
                self.assertEqual(int(r['crc'], 16),
                                 zlib.crc32(truth) & 0xffffffff, r['name'])
                self.assertTrue(r['ok'])
                # the table shows both loops and their difference, as
                # disk.run_ms computes them from the VBL counts
                self.assertTrue(r['shown_ok'], (r['shown'], r['ms_loop'],
                                                r['ms_without'], r['ms']))
                self.assertGreater(r['vbls_loop'], r['vbls_without'])
            self.assertEqual(disk.check_failures(results), [])
            lines = (out / 'run' / 'screen.txt').read_text().splitlines()
            for r in results:
                line = next(t for t in lines
                            if t.startswith(r['name'].upper()))
                self.assertIn(' %s OK ' % r['crc'], line)
            restore = results[0]['restore']
            self.assertEqual(restore['other_video_writes'], 0)
            self.assertTrue(restore['hole_0878_kept'])
            self.assertEqual(restore['amem_requests'], 1)
            # the colormap B level 0 bytes there, put by the PRIVATE copy
            capture = loader.read_capture(dirs[0])
            self.assertEqual(restore['main_4078'], loader.colormap_pages(
                capture)[0x40][0x78:0x80].hex())
        finally:
            shutil.rmtree(str(out))

    def test_a_base_loop_that_calls_the_replay_is_caught(self):
        """A carry set before timed's ROR: both loops call the replay, the
        CRCs stay right, and check_failures names the frame."""
        master = disk.disk_writer().DEFAULT_MASTER
        if not master.is_file():
            self.skipTest('%s is missing (appletini-one)' % master)
        out = Path(tempfile.mkdtemp(dir=str(ROOT / 'build' / 'native')))
        try:
            src = out / 'src'
            shutil.copytree(str(SRC), str(src))
            text = (src / 'runner.s').read_text()
            old = 'timed:  ror     withrep\n'
            self.assertEqual(text.count(old), 1)
            (src / 'runner.s').write_text(text.replace(
                old, 'timed:  sec\n        ror     withrep\n'))
            obj = out / 'obj'
            make(obj, src)
            dirs = [CAPTURES / 'still-1']
            frames = disk.prepare(dirs, loader.read_build(obj, 'card'))
            files = disk.files_of(frames, obj, 3, 1)
            results = disk.check(frames, files, obj, out / 'run', 'f121')
            self.assertTrue(results[0]['ok'])
            self.assertFalse(results[0]['timed_ok'])
            failures = disk.check_failures(results)
            self.assertEqual(len(failures), 1, failures)
            self.assertIn('without the replay', failures[0])
        finally:
            shutil.rmtree(str(out))

    def test_a_cpu_restore_of_the_colormaps_is_caught(self):
        """The runner as it was: main $0200-$5FFF restored by CPU stores,
        $0878-$087F and $4078-$407F included (docs/MEMORY_MAP.md rules 3
        and 8)."""
        master = disk.disk_writer().DEFAULT_MASTER
        if not master.is_file():
            self.skipTest('%s is missing (appletini-one)' % master)
        out = Path(tempfile.mkdtemp(dir=str(ROOT / 'build' / 'native')))
        try:
            src = out / 'src'
            shutil.copytree(str(SRC), str(src))
            text = (src / 'runner.s').read_text()
            old = ('        lda     #$0C\n        ldx     #$20\n'
                   '        jsr     to_main\n')
            self.assertEqual(text.count(old), 1)
            (src / 'runner.s').write_text(text.replace(
                old, old.replace('#$0C', '#$04').replace('#$20', '#$60')))
            obj = out / 'obj'
            make(obj, src)
            dirs = [CAPTURES / 'still-1']
            frames = disk.prepare(dirs, loader.read_build(obj, 'card'))
            files = disk.files_of(frames, obj, 1, 1)
            results = disk.check(frames, files, obj, out / 'run', 'f121')
            restore = results[0]['restore']
            self.assertFalse(results[0]['ok'])
            self.assertGreater(restore['other_video_writes'], 16000)
            self.assertFalse(restore['hole_0878_kept'])
        finally:
            shutil.rmtree(str(out))


if __name__ == '__main__':
    unittest.main()
