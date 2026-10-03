"""Milestone 11, first half, part plboot (docs/SCREENS.md 2.5, 4.5, 6.5,
7.3; docs/m11-parts/plboot.md): DOOM.SYSTEM (src/native/pl_boot.s) and
DOOM.hdv (tools/native/pldisk.py).

Without build/: the link's map against s2layout.py's places; the boot's
places in pl_boot.s against pldisk.py's; the catalog, CRCLIST and the
songs' packing on synthetic files; the disk's layout check on overlapping
synthetic segments; the card image's offsets; the machine's poison.

With cc65, make, build/a2vm/a2vm, S2's player (make -C src/sound),
milestone 8's rcard and tables, milestone 9's lcard and store, the parts'
builds (make -f src/native/m11.mk), the WAD and appletini-one's ProDOS:

- the link and the disk built into a temporary directory with no warning;
  the sizes against the budget (pl_boot.s at most 2 KB, the boot in
  $2000-$2FFF, FXCODE in its room, the ready loop in the platform's
  $FF00-$FFF9); every image of the code library linked against the card
  the boot installs;
- the checkpoint (SCREENS.md 6.5's boot row): DOOM.hdv under the MLI trap
  with --amem, f121 and fastpath: every CRC equal (the boot's own check,
  and every bank file's byte in its bank), PL_STATUS ready, the card as
  the image, the clock running, the boot's time reported; no mouse card,
  too few banks each stop with its message; no memory API (slot 7 empty,
  or the API unavailable) goes on with its message (docs/PLAY.md 19); no
  music goes on with its message, the effects off and no AY write but the
  probe's;
- the planted bugs, each in a scratch copy, caught.

Run by name: python3 tools/testpar.py tests/test_m11_plboot.py
"""

import re
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import support  # noqa: F401  (sys.path)

from native import llayout as LL  # noqa: E402
from native import lstore  # noqa: E402
from native import pldisk as P  # noqa: E402
from native import s2layout as S  # noqa: E402
from sound import mus  # noqa: E402

SOURCE = support.ROOT / 'src' / 'native' / 'pl_boot.s'


def equates() -> dict:
    """pl_boot.s's NAME = $HEX (or decimal) lines."""
    out = {}
    for m in re.finditer(r'^(\w+)\s+=\s+(\$[0-9A-Fa-f]+|\d+)\s*(?:;.*)?$',
                         SOURCE.read_text(), re.M):
        v = m.group(2)
        out[m.group(1)] = int(v[1:], 16) if v.startswith('$') else int(v)
    return out


class Pure(unittest.TestCase):

    def test_places_agree(self):
        e = equates()
        self.assertEqual(e['STAGE'], P.STAGE)
        self.assertEqual(e['STAGE_SIZE'], P.HALF)
        self.assertEqual(e['BOOT_END'], P.BOOT_HI)
        self.assertEqual(e['CAT_MAX'], P.CAT_MAX)
        self.assertEqual(e['C_NAMES'], P.C_NAMES)
        self.assertEqual(e['ENTRY'], P.ENTRY)
        self.assertEqual(0xBF00 - e['CRCBUF'], P.CRC_MAX)
        self.assertEqual(e['BANKS'], P.BANKS)
        self.assertEqual(e['AMEM_MAX'], LL.AMEM_MAX)
        # the disk's stop is s2layout's (PLBOOT-1, applied in wave 8): in
        # s2.inc, not defined by pl_boot.s, and no other stop's code
        self.assertNotIn('PL_DISK', e)
        self.assertEqual(P.PL_DISK, S.PL['DISK'])
        self.assertIn(('PL_DISK', P.PL_DISK), S.constants('release'))
        codes = list(S.PL.values()) + list(S.S2S.values()) + \
            list(LL.LS.values())
        self.assertEqual(codes.count(P.PL_DISK), 1)
        self.assertEqual(len(set(codes)), len(codes))
        # the buffers in order, below ProDOS's global page
        order = ['STAGE', 'IOBUF', 'CATBUF', 'HDRBUF', 'BOUNCE', 'CRC_T0',
                 'CRCBUF']
        self.assertEqual([e[n] for n in order], sorted(e[n] for n in order))
        self.assertGreaterEqual(e['IOBUF'], e['STAGE'] + e['STAGE_SIZE'])
        self.assertGreaterEqual(e['CRCBUF'], e['CRC_T3'] + 0x100)
        self.assertEqual(e['ZP_PAIR'], 6)

    def test_cfg(self):
        text = P.cfg_text()
        areas = {m.group(1): (int(m.group(2), 16), int(m.group(3), 16))
                 for m in re.finditer(r'^\s+(\w+):\s+start = \$([0-9A-F]+), '
                                      r'size = \$([0-9A-F]+)', text, re.M)}
        card = {n: (lo, hi) for n, lo, hi in S.S2_CARD}
        self.assertEqual(areas['SND'], (0xE900, 0xF505 - 0xE900))
        self.assertEqual(areas['FXC'], (S.FX_CODE[0],
                                        S.FX_CODE[1] - S.FX_CODE[0]))
        self.assertEqual(areas['RING'][0], card['the song ring and its '
                                                 'mirror'][0])
        self.assertEqual(areas['PLAT'], (0xFF00, 0xFA))
        self.assertEqual(areas['VEC'], (0xFFFA, 6))
        self.assertEqual(areas['BOOT'], (0x2000, 0x1000))
        for seg in ('PLBOOT', 'S2CODE', 'S2RODATA', 'SNDBOOT'):
            self.assertIn('%s:' % seg, text)
            self.assertRegex(text, r'%s:\s+load = BOOT' % seg)

    def test_catalog(self):
        cat = P.catalog(['TEXELS.1', 'GFX.1'])
        self.assertEqual(len(cat), P.CAT_MAX)
        self.assertEqual(cat[0], 2)
        self.assertEqual(cat[16:16 + 9], b'\x08TEXELS.1')
        self.assertEqual(cat[32:32 + 6], b'\x05GFX.1')
        with self.assertRaises(P.DiskError):
            P.catalog(['F%d' % k for k in range(P.MAX_FILES + 1)])

    def test_crc_list(self):
        files = [('A.1', lstore.bank_file([(7, 0x0200, b'abc'),
                                           (9, 0x1000, b'\x01' * 300)])),
                 ('B.1', lstore.bank_file([(3, 0xBF00, b'z' * 256)]))]
        aux, main = bytes(range(256)) * 64, bytes(P.HALF)
        entries = P.crc_entries(files, aux, main)
        self.assertEqual(entries[0], (7, 0x0200, 3, zlib.crc32(b'abc')))
        self.assertEqual(entries[2][:3], (3, 0xBF00, 256))
        self.assertEqual(entries[3], (0, P.STAGE, P.HALF, zlib.crc32(aux)))
        self.assertEqual(entries[4], (0, P.STAGE, P.HALF, zlib.crc32(main)))
        data = P.crc_file(entries)
        self.assertEqual(struct.unpack_from('<H', data)[0], 5)
        self.assertEqual(len(data), 2 + 9 * 5)
        self.assertEqual(struct.unpack_from('<BHHI', data, 2 + 9),
                         (9, 0x1000, 300, zlib.crc32(b'\x01' * 300)))
        with self.assertRaises(P.DiskError):
            P.crc_file([(1, 0x200, 1, 0)] * (P.CRC_MAX // 9 + 1))

    def test_layout(self):
        good = [('A.1', lstore.bank_file([(7, 0x0200, b'a' * 16)])),
                ('B.1', lstore.bank_file([(7, 0x0210, b'b' * 16)]))]
        self.assertEqual(P.layout_problems(good), [])
        bad = [('A.1', lstore.bank_file([(7, 0x0200, b'a' * 16)])),
               ('B.1', lstore.bank_file([(7, 0x020F, b'b' * 16)]))]
        self.assertEqual(len(P.layout_problems(bad)), 1)
        self.assertIn('meets', P.layout_problems(bad)[0])

    def test_songs(self):
        songs = [('S%d' % k, bytes([k]) * n) for k, n in enumerate(
            (22352, 15972, 15920, 14030, 13100, 12868, 10649, 9642, 7280,
             7262, 6838, 740, 498))]
        segs = P.song_segments(songs)
        bank, at, directory = segs[0]
        # the directory's place is s2layout's (PLBOOT-2, applied in wave 8)
        self.assertEqual((bank, at), P.SONG_DIR)
        self.assertEqual(P.SONG_DIR, S.SONG_DIR)
        self.assertIn(('SONG_DIR_BANK', bank), S.constants('release'))
        self.assertIn(('SONG_DIR', at), S.constants('release'))
        self.assertEqual(len(songs), S.SONG_COUNT)
        self.assertEqual(len(mus.UPSTREAM_SONGS), S.SONG_COUNT)
        self.assertEqual(len(directory), S.SONG_DIR_ENTRY * len(songs))
        for k, (b, a, data) in enumerate(segs[1:]):
            self.assertEqual(data, songs[k][1])
            self.assertIn(b, S.SONGS)
            self.assertGreaterEqual(a, LL.ROOM[0])
            self.assertLessEqual(a + len(data), LL.ROOM[1])
            self.assertEqual(struct.unpack_from('<BH', directory, 3 * k),
                             (b, a))
        self.assertEqual(P.layout_problems(
            [('SONGS.1', lstore.bank_file(segs))]), [])
        with self.assertRaises(P.DiskError):
            P.song_segments([('BIG', bytes(LL.ROOM[1] - LL.ROOM[0] + 1))])

    def test_card_offset(self):
        self.assertEqual(P.card_offset(0xD000, True), 0)
        self.assertEqual(P.card_offset(0xD000, False), 0x1000)
        self.assertEqual(P.card_offset(0xE000, True), 0x2000)
        self.assertEqual(P.card_offset(0xFFFF, False), 0x3FFF)

    def test_poison(self):
        img = P.poison_image()
        self.assertEqual(img[:8], b'A2VMIMG1')
        at, kinds = 8, []
        while at < len(img):
            kind, bank, address, n = struct.unpack_from('<BBHI', img, at)
            kinds.append((kind, bank, address, n))
            at += 8 + n
        self.assertEqual(at, len(img))
        self.assertIn((0, 0, 0x0000, 0x18), kinds)     # the pair with it
        self.assertIn((2, 0, 0xD000, 0x3000), kinds)   # ProDOS's card


def why_not() -> str:
    lack = P.missing()
    return 'needs %s' % '; '.join(lack) if lack else ''


WHY = why_not()


@unittest.skipIf(WHY, WHY)
class Disk(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='tmp-plboot-test-',
                                        dir=str(P.BUILD)))
        cls.disk = P.build(cls.tmp / 'DOOM.hdv', cls.tmp / 'm11')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_files_and_sizes(self):
        names = [f[0] for f in self.disk.files]
        self.assertEqual(names[:5], ['DOOM.SYSTEM', 'PRODOS', 'CATALOG',
                                     'CRCLIST', 'LC.BIN'])
        for n in ('CODE.1', 'RTABLES.1', 'SONGS.1', 'SFX.1', 'GFX.1',
                  'HUDTXT.1', 'TEXELS.1', 'PATCHES.1', 'MAPS.1', 'TABLES.1'):
            self.assertIn(n, names)
        z = P.sizes(self.disk.boot)
        self.assertLessEqual(z['PLBOOT'], 2048)
        self.assertLessEqual(z['PLBOOT'] + z['S2CODE'] + z['S2RODATA'] +
                             z['SNDBOOT'], P.BOOT_HI - P.BOOT_LO)
        self.assertLessEqual(z['FXCODE'], S.FX_CODE[1] - S.FX_CODE[0])
        self.assertLessEqual(z['PLRES'], 0xFFFA - 0xFF00)
        lab = self.disk.boot.labels
        self.assertEqual(struct.unpack_from('<H', self.disk.main,
                                            0x3FFE)[0], lab['pl_vbl'])
        self.assertEqual(len(self.disk.entries),
                         len(P.segments_of(self.disk.bank_files)) + 2)
        self.assertEqual(P.layout_problems(self.disk.bank_files), [])

    def test_images_agree_with_the_card(self):
        self.assertEqual(P.image_problems(self.disk.main), [])

    def test_checkpoint(self):
        results = P.check_all(self.disk, 2)
        bad = ['%s: %s' % (r['check'], p) for r in results
               for p in r['problems']]
        self.assertEqual(bad, [])
        self.assertEqual([r['check'] for r in results], list(P.CHECK))
        for r in results[:4]:
            self.assertGreater(r['boot_ms'], 0)

    def test_planted(self):
        lines = []
        missed = P.planted(self.disk, 2, out=lines.append)
        self.assertEqual(missed, [], '\n'.join(lines))
        self.assertGreaterEqual(len(lines), len(P.PLANTED))


if __name__ == '__main__':
    unittest.main()
