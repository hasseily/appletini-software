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
        self.assertEqual(a2run.stray_writes(bytes(before), bytes(after))[0],
                         0)
        after[a2run.aux_offset(0, L.VIEW_END)] = 3   # aux 0 past the view
        after[0x1000] = 4                      # main spans
        after[a2run.LC + 0x1000] = 5           # the card at $D000
        after[a2run.aux_offset(7, 0x4000)] = 6
        count, shown = a2run.stray_writes(bytes(before), bytes(after))
        self.assertEqual(count, 4)
        self.assertIn('aux 0 $8900: $00 -> $03', shown)
        self.assertIn('main $1000: $00 -> $04', shown)
        self.assertIn('card $D000: $00 -> $05', shown)
        self.assertIn('aux 7 $4000: $00 -> $06', shown)


# ---------------------------------------------------------------------------
# the loader
# ---------------------------------------------------------------------------

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
                self.assertEqual(r[run]['shr_writes'],
                                 r[run]['stores_expected'], r['name'])
                self.assertEqual(r[run]['other_video_writes'], 0, r['name'])
            self.assertTrue(r['ok'], r['name'])
        self.assertGreater(max(r['records']['batches'] for r in results), 1)
        self.assertGreater(max(r['records']['strips'] for r in results), 1)


# ---------------------------------------------------------------------------
# the checks can fail
# ---------------------------------------------------------------------------

# Bugs planted in a scratch copy of replay.s: (name, [(the text replaced,
# its replacement), ...], the frame, what must catch it: 'pixels' the
# screen against the truth, 'stray' the snapshot comparison, 'stores' the
# count of SHR writes against upstream's screen stores). A frame named
# synth-* is a synthetic stream of tools/native/synth.py.
DRAW_END = '@done:  sta     WRMAIN\n        ldx     sc0\n'
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
     [(DRAW_END, DRAW_END.replace('@done:  sta', '@done:  stz     $A000\n'
                                  '        sta'))], 'still-1', 'stray'),
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


# ---------------------------------------------------------------------------
# the card run, on a2vm
# ---------------------------------------------------------------------------

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
            files = disk.files_of(frames, OBJ, 2, 2)
            disk.build_disk(files, out / 'T.hdv')
            image = (out / 'T.hdv').read_bytes()
            self.assertEqual(len(image) % 512, 0)
            results = disk.check(frames, files, OBJ, out / 'run', 'f121')
            for r, d in zip(results, dirs):
                truth = (d / 'screen-after.bin').read_bytes()
                self.assertEqual(int(r['crc'], 16),
                                 zlib.crc32(truth) & 0xffffffff, r['name'])
                self.assertTrue(r['ok'])
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
