"""Milestone 11, part s2data: the 2D store (docs/SCREENS.md 0.1 F5, 4.5,
7.3, 9 risks 3-4; docs/m11-parts/s2data.md).

tools/native/s2data.py:

- hand-made patches, places and bank files (no build/ needed): a patch
  written again equals its bytes, its column offsets low byte first; a
  raw from a patch; the places never cross a bin's end and go to bank
  125 when the budget's banks are full; the handles table's arrays; the
  bank files read back; check_places names a lump across a bank's end;
- the checkpoint on DOOM1.WAD and the release: every lump equal to the
  release's (a picture part by part) or taken from it; the store in
  GFX0-GFX3 and the free parts of 103-108 (no bank 125), the bytes a bank
  reported; a read-back of every lump through the handles table of the
  bank files equal to the release's; the include's constants equal to
  the table and assembled by ca65;
- the planted bugs, each in a scratch copy of s2data.py, each caught by
  its check.

Skips without build/ (DOOM1.WAD and the release image).
"""

import importlib.util
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support
from native import lstore
from native import s2data as D
from native import s2layout as L
from native import umodel as U

TOOL = support.ROOT / 'tools' / 'native' / 's2data.py'
needs_inputs = unittest.skipUnless(
    D.WAD.exists() and U.RELEASE.exists(),
    '%s or %s is missing: run python3 tools/fetch_upstream.py first'
    % (D.WAD.relative_to(support.ROOT), U.RELEASE.relative_to(support.ROOT)))


def column(posts):
    out = bytearray()
    for top, pixels in posts:
        out += bytes((top, len(pixels), pixels[0])) + bytes(pixels) + \
            bytes((pixels[-1],))
    return bytes(out + b'\xff')


def hand_patch(columns, left=-1, top=2, height=8):
    """A patch as DOOM1.WAD lays one out: the header, the offsets, the
    columns in order, a zero pad to 4 bytes."""
    head = struct.pack('<HHhh', len(columns), height, left, top)
    base = len(head) + 4 * len(columns)
    offsets, body = bytearray(), bytearray()
    for posts in columns:
        offsets += struct.pack('<I', base + len(body))
        body += column(posts)
    data = head + bytes(offsets) + bytes(body)
    return data + bytes(-len(data) % 4)


PATCH = hand_patch([[(0, [1, 2, 3])], [(1, [4]), (5, [5, 6])],
                    [(0, [7] * 8)]], height=8)


class Host(unittest.TestCase):
    def test_patch_written_again_is_its_bytes(self):
        p = D.parse_patch(PATCH)
        self.assertEqual((p.width, p.height, p.left, p.top), (3, 8, -1, 2))
        self.assertEqual(D.encode_patch(p), PATCH)
        # the offsets: 32 bits, low byte first
        self.assertEqual(D.encode_patch(p)[8:12], bytes((20, 0, 0, 0)))
        self.assertEqual(len(PATCH) % 4, 0)

    def test_parse_refuses_a_gap_and_a_tail(self):
        gap = bytearray(PATCH)
        struct.pack_into('<I', gap, 12, struct.unpack_from('<I', gap, 12)[0]
                         + 1)
        with self.assertRaises(D.StoreError):
            D.parse_patch(bytes(gap))
        with self.assertRaises(D.StoreError):
            D.parse_patch(PATCH + b'\x01')

    def test_raw_of_a_patch(self):
        full = hand_patch([[(0, [10 + x + 3 * y for y in range(2)])]
                           for x in range(3)], left=0, top=0, height=2)
        raw = D.raw_of_patch(D.parse_patch(full))
        self.assertEqual(raw, bytes((10, 11, 12, 13, 14, 15)))
        with self.assertRaises(D.StoreError):       # a pixel not covered
            D.raw_of_patch(D.parse_patch(PATCH))

    def lumps(self, sizes):
        return [D.Lump('L%d' % k, k, 'flat', 'DOOM1.WAD', bytes([k]) * n)
                for k, n in enumerate(sizes)]

    def test_places_stay_in_their_bin_and_overflow_to_125(self):
        bins = [D.Bin(109, 0x0200, 0x0300, 'a'), D.Bin(110, 0x0200, 0x0280,
                                                       'b')]
        lumps = self.lumps([0x60, 0x60, 0x40, 0x70])
        store = D.place(lumps, bins)
        for m in lumps:
            p = store.places[m.name]
            room = [b for b in bins + [D.over_bin()] if b.bank == p.bank][0]
            self.assertTrue(room.lo <= p.address and
                            p.address + p.size <= room.end, m.name)
        # the table (4 x 5 bytes) first in bank 109; from the largest:
        # L3 and L0 in 109, L1 in 110, L2 (64 B) past both bins
        self.assertEqual(store.directory, D.Place(109, 0x0200, 20))
        self.assertEqual({n: (p.bank, p.address)
                          for n, p in store.places.items()},
                         {'L3': (109, 0x0214), 'L0': (109, 0x0284),
                          'L1': (110, 0x0200),
                          'L2': (D.OVER_BUDGET, 0x0200)})

    def test_the_handles_table(self):
        lumps = self.lumps([3, 0x123])
        places = {'L0': D.Place(109, 0x1234, 3),
                  'L1': D.Place(110, 0xBEEF, 0x123)}
        self.assertEqual(D.directory_bytes(lumps, places),
                         bytes((109, 110, 0x34, 0xEF, 0x12, 0xBE, 3, 0x23,
                                0, 1)))

    def test_bank_files_read_back(self):
        lumps = self.lumps([0x100, 0x80])
        store = D.place(lumps, [D.Bin(109, 0x0200, 0xC000, 'a')])
        files = D.bank_files(store)
        self.assertEqual(list(files), ['GFX.1'])
        banks = D.read_back(files)
        for m in lumps:
            p = store.places[m.name]
            self.assertEqual(bytes(banks[p.bank][p.address:p.address +
                                                 p.size]), m.data)

    def test_a_lump_across_the_bank_end_is_named(self):
        lumps = self.lumps([0x10])
        store = D.Store(lumps, {'L0': D.Place(109, 0xBFF8, 0x10)},
                        D.Place(109, 0x0200, 5), {})
        problems = D.check_places(store)
        self.assertTrue(any('across the bank\'s end' in p
                            for p in problems), problems)
        with self.assertRaises(lstore.StoreError):
            D.bank_files(store)

    def test_a_patch_column_near_the_bank_end_does_not_fit(self):
        m = D.Lump('P', 0, 'patch', 'DOOM1.WAD', PATCH)
        last = max(o for o, _ in D.patch_columns(PATCH))
        fetch = D.fetch_bytes()
        self.assertGreaterEqual(fetch, 1024)
        at = D.ROOM[1] - fetch - last
        self.assertTrue(D.fits(m, at, D.ROOM[1], fetch))
        self.assertFalse(D.fits(m, at + 1, D.ROOM[1], fetch))

    def test_the_bins_avoid_the_other_users(self):
        bins = D.bins()
        self.assertEqual([b.bank for b in bins[:4]], list(L.GFX))
        for b in bins:
            self.assertTrue(D.ROOM[0] <= b.lo < b.end <= D.ROOM[1], b)
            self.assertNotEqual(b.bank, L.S2PAL)
            for bank, lo, hi, whose in D.reserved():
                self.assertFalse(bank == b.bank and b.lo < hi and lo < b.end,
                                 '%s meets %s' % (b.what, whose))
        self.assertTrue(all(b.bank in L.GFX or 103 <= b.bank <= 108
                            for b in bins))
        # GSSTAT's and GSOVL's places: s2pal's in S2PAL, clear of every
        # other user (S2DATA-3 as integrated)
        fixed = D.fixed_bins()
        self.assertEqual(sorted(b.what.split()[0] for b in fixed),
                         sorted(D.FIXED))
        for b in fixed:
            self.assertEqual(b.bank, L.S2PAL)
            for bank, lo, hi, whose in D.reserved():
                self.assertFalse(bank == b.bank and b.lo < hi and lo < b.end,
                                 '%s meets %s' % (b.what, whose))


def checkpoint_of(module, rel, wad, out):
    """Build with a module (the tree's s2data or a planted copy) into out;
    the tree's checks of what it built (each problem list by name)."""
    result = {}
    store = module.place(module.make_lumps(rel, wad))
    result['places'] = D.check_places(store)
    result['sources'] = D.check_sources(store.lumps, rel, wad)
    try:
        module.write(store, out)
    except (module.StoreError, lstore.StoreError) as error:
        result['files'] = [str(error)]
        return result
    files = D.load_files(out)
    result['read-back'] = D.check_read_back(files, store.lumps, rel)
    result['include'] = D.check_include((out / 's2data.inc').read_text(),
                                        files, store.lumps)
    return result


@needs_inputs
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='s2data-test-'))
        cls.addClassCleanup(shutil.rmtree, cls.tmp)
        cls.out = cls.tmp / 'out'
        cls.run_ = support.run([sys.executable, str(TOOL), '--out',
                                str(cls.out)], timeout=180,
                               max_bytes=16 << 20,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
        cls.rel = U.Release()
        cls.wad = D.read_wad()

    def test_the_tool_builds_and_checks(self):
        self.assertEqual(self.run_.returncode, 0,
                         self.run_.stdout + self.run_.stderr)
        for name in ('sources', 'places', 'read-back', 'include'):
            self.assertRegex(self.run_.stdout, r'(?m)^%s\s+OK$' % name)
        self.assertIn('budget (GFX0-GFX3 and the free parts of 103-108): '
                      'met', self.run_.stdout)
        if '-v' in sys.argv:
            print('\n' + self.run_.stdout)

    def test_the_checkpoint_on_the_files(self):
        store = D.store_of_manifest(self.out, self.rel, self.wad)
        result = D.checkpoint(store, D.load_files(self.out), self.rel,
                              self.wad, (self.out / 's2data.inc').read_text())
        self.assertEqual({k: v for k, v in result.items() if v}, {})

    def test_the_lumps_and_their_sources(self):
        lumps = D.make_lumps(self.rel, self.wad)
        names = [m.name for m in lumps]
        # every 2D lump of the release, once, in directory order
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual([m.number for m in lumps], sorted(m.number
                                                           for m in lumps))
        for n in D.PICTURES + D.RECORDS + D.RAWS + D.FLATS + (
                'M_DOOM', 'STTNUM0', 'STFST00', 'WINUM0', 'WILV08'):
            self.assertIn(n, names)
        self.assertNotIn('STIMA0', names)       # a sprite
        kinds = {}
        for m in lumps:
            kinds.setdefault((m.kind, m.source), []).append(m.name)
        self.assertEqual(sorted(kinds[('picture', 'release')]),
                         sorted(D.PICTURES))
        self.assertEqual(sorted(kinds[('record', 'release')]),
                         sorted(D.RECORDS))
        self.assertEqual(kinds[('raw', 'DOOM1.WAD')], ['STBAR'])
        self.assertEqual(kinds[('flat', 'DOOM1.WAD')], ['FLOOR4_8'])
        # the patches upstream drew or recoloured, from the release
        self.assertEqual(sorted(kinds[('patch', 'release')]),
                         sorted(['M_ARUN', 'M_GAMMA', 'M_MOUSE', 'M_MSPEED',
                                 'M_MMOVE', 'M_CTRLS'] +
                                list(D.RELEASE_PATCHES)))
        self.assertGreater(len(kinds[('patch', 'DOOM1.WAD')]), 200)
        self.assertEqual(D.check_sources(lumps, self.rel, self.wad), [])
        # the handles: the rank in the directory, so the digit runs
        # stay consecutive
        handles = D.handles_of(self.rel)
        self.assertEqual([handles[m.number] for m in lumps],
                         list(range(len(lumps))))
        for first, count in (('STTNUM0', 10), ('WINUM0', 10),
                             ('WILV00', 9), ('STKEYS0', 3)):
            h = handles[self.rel.index(first)]
            self.assertEqual(names[h:h + count],
                             [first[:-1] + str(k) for k in range(count)])

    def test_the_budget(self):
        store = D.store_of_manifest(self.out, self.rel, self.wad)
        banks = {p.bank for p in store.places.values()}
        self.assertNotIn(D.OVER_BUDGET, banks)
        self.assertTrue(banks <= set(L.GFX) | set(range(103, 109)), banks)
        # in S2PAL only GSSTAT and GSOVL, at s2pal's places (S2DATA-3)
        self.assertEqual({n: (p.bank, p.address)
                          for n, p in store.places.items()
                          if p.bank == L.S2PAL},
                         {n: (L.S2PAL, L.S2PAL_AT[s])
                          for n, s in D.FIXED.items()})
        # the pictures each whole in one of GFX0-GFX3
        self.assertEqual(sorted(store.places[n].bank for n in D.PICTURES),
                         sorted(store.places[n].bank for n in D.PICTURES
                                if store.places[n].bank in L.GFX))
        total = sum(len(m.data) for m in store.lumps)
        used = sum(u for _, u in D.usage(store))
        self.assertEqual(used, total + store.directory.size)
        self.assertLessEqual(len(D.segments(store)), D.LL.BANKFILE_MAX_SEGS)

    def test_sfx_fits_below_the_store(self):
        sfx = support.BUILD / 'native' / 'm11' / 'fxconv'
        sizes = [f.stat().st_size for f in (sfx / 'SFX.1', sfx / 'SFXAUTO.1')
                 if f.exists()]
        if not sizes:
            self.skipTest('part fxconv\'s SFX.1 is not built')
        self.assertLessEqual(max(sizes), D.SFX_ROOM[1] - D.SFX_ROOM[0])

    def test_the_include_assembles(self):
        ca65 = shutil.which('ca65')
        if ca65 is None:
            self.skipTest('no ca65')
        src = self.tmp / 't.s'
        src.write_text('.include "s2data.inc"\n'
                       '.byte H_STTNUM0, HBANK_M_DOOM, <HADDR_TITLEPIC\n'
                       '.byte GFXDIR_BANK, GFX_NH\n'
                       '.word GFXDIR_BK, GFXDIR_SZHI, PIC_PALS, GFX_FETCH\n')
        run = support.run([ca65, '-I', str(self.out), '-o',
                           str(self.tmp / 't.o'), str(src)], timeout=60,
                          max_bytes=1 << 20, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)
        self.assertEqual((run.returncode, run.stdout, run.stderr),
                         (0, '', ''))


# Each planted bug: the text of s2data.py it replaces (exactly once), its
# replacement, and the check that must catch it.
PLANTED = {
    'a patch\'s column offsets byte-swapped (big-endian)': (
        "        offsets += struct.pack('<I', base + len(body))\n",
        "        offsets += struct.pack('>I', base + len(body))\n",
        'sources'),
    'a lump placed across a bank end': (
        '    if address + len(lump.data) > end:\n        return False\n',
        '    if address >= end:\n        return False\n',
        'places'),
    'a picture\'s palettes from the wrong record': (
        '                            picture_bytes(pictures[name])))\n',
        '                            picture_bytes(dict(\n'
        '                                pictures[name], palettes=pictures[\n'
        '                                    PICTURES[PICTURES.index(name)'
        ' - 1]][\'palettes\']))))\n',
        'sources'),
}


@needs_inputs
class Planted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='s2data-planted-'))
        cls.addClassCleanup(shutil.rmtree, cls.tmp)
        cls.rel = U.Release()
        cls.wad = D.read_wad()

    def planted(self, label):
        old, new, _ = PLANTED[label]
        source = TOOL.read_text()
        self.assertEqual(source.count(old), 1, label)
        k = list(PLANTED).index(label)
        path = self.tmp / ('s2data_%d.py' % k)
        path.write_text(source.replace(old, new))
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_tree_passes(self):
        result = checkpoint_of(D, self.rel, self.wad, self.tmp / 'tree')
        self.assertEqual({k: v for k, v in result.items() if v}, {})

    def test_each_planted_bug_is_caught(self):
        caught = {}
        for k, label in enumerate(PLANTED):
            check = PLANTED[label][2]
            result = checkpoint_of(self.planted(label), self.rel, self.wad,
                                   self.tmp / ('out%d' % k))
            self.assertTrue(result.get(check), '%s was not caught by %s: %s'
                            % (label, check, result))
            caught[label] = (check, result[check][0])
        if '-v' in sys.argv:
            for label, (check, why) in caught.items():
                print('%s: %s: %s' % (label, check, why[:110]))


if __name__ == '__main__':
    unittest.main()
