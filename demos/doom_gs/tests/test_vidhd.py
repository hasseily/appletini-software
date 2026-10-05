"""The VidHD's records (docs/PLAY.md 22, tools/native/vidhd.py).

Without build/: vh_go's bytes (its branch to its RTS, its own CMP operand
as the last value, $C035 written twice between PHP, SEI and PLP), the
trampolines', the rooms against the layouts (the kernel's padding before
KLISTS, the channel block's tail, AMEMCPUF's room, BT_EXT's room below
rule 8's $0878), the table's size against pl_boot.s.

With the play build (build/native/play: python3 tools/native/playdisk.py):
vidhd.play_patches, whose checks (each replaced instruction's bytes, each
room free and zero) pass; its table in vh_patch's size; each record's bank
one of the patched images' or main (0); every screen window a JSR vh_wa.

The runs on a2vm --vidhd (the benchmark, the scripted tour, the old disk)
are docs/PLAY.md 22's, run by hand: each takes minutes.
"""

import re
import unittest

from support import BUILD, ROOT

from native import amcpu, glayout as GL, playlayout as PL  # noqa: E402
from native import s2layout as S, vidhd as V  # noqa: E402

PLAY = BUILD / 'native' / 'play'
HAVE = (PLAY / 'card' / 'plboot.lbl').exists()
WHY = 'needs the play build (python3 tools/native/playdisk.py)'


class Pure(unittest.TestCase):

    def test_go_code(self):
        code = V.go_code()
        self.assertEqual(len(code), V.GO_END - V.GO)
        self.assertEqual(code[:2], bytes([0xC9, V.SH_OFF]))   # CMP #last
        # BEQ to the final RTS
        self.assertEqual(code[2], 0xF0)
        self.assertEqual(V.GO + 4 + code[3], V.GO_END - 1)
        self.assertEqual(code[-1], 0x60)
        # its own operand is the last value
        self.assertEqual(code[4:7], bytes([0x8D, (V.GO + 1) & 0xFF,
                                           (V.GO + 1) >> 8]))
        # $C035 twice in a row, interrupts masked between them
        self.assertEqual(code[7:-1], bytes([0x08, 0x78, 0x8D, 0x35, 0xC0,
                                            0x8D, 0x35, 0xC0, 0x28]))

    def test_off_then(self):
        self.assertEqual(V.off_then(0x1234),
                         bytes([0xA9, 0x18, 0x20, V.GO & 0xFF, V.GO >> 8,
                                0x4C, 0x34, 0x12]))

    def test_rooms(self):
        self.assertEqual(V.GO_END, PL.BT_REPLAY - 12)        # KLISTS
        self.assertTrue(PL.KERNEL[0] <= V.GO < V.GO_END <= PL.KERNEL[1])
        cb = S.BUILDS['release']
        self.assertGreaterEqual(V.KR, cb.sc_base + S.sc_size(cb.channels))
        self.assertLessEqual(V.KR_END, cb.sc_base + 64)
        lo, hi = GL.AMEM_CPU['AMEMCPUF']
        self.assertTrue(lo < V.WA and V.WA_END <= hi)
        self.assertTrue(PL.BT_EXT[0] < V.SC and V.SC_END <= PL.BT_EXT[1])
        self.assertLessEqual(V.SC_END, 0x0878)              # rule 8

    def test_patch_size(self):
        text = (ROOT / 'src' / 'native' / 'pl_boot.s').read_text()
        m = re.search(r'^VHPATCH_SIZE\s+=\s+(\d+)', text, re.M)
        self.assertEqual(int(m.group(1)), V.PATCH_SIZE)


@unittest.skipUnless(HAVE, WHY)
class Built(unittest.TestCase):

    def test_records(self):
        records = V.play_patches(PLAY)
        table = amcpu.table(records, V.PATCH_SIZE)
        self.assertEqual(len(table), V.PATCH_SIZE)
        banks = {0, PL.DLBANK, S.OVLW_BANK} | \
            {S.image_banks()[n] for n in ('P2DW', 'MENUW', 'AMAPW', 'WIW',
                                          'FINW')}
        from native import rlayout as R
        banks.add(R.MCODE_BANK)
        self.assertEqual({b for b, _, _ in records}, banks)
        wa = bytes([0x20, V.WA & 0xFF, V.WA >> 8])
        self.assertEqual(sum(1 for b, _, d in records if d == wa and b),
                         sum(V.WINDOW_COUNTS.values()))
        go = [d for b, a, d in records if b == 0 and a == V.GO]
        self.assertEqual(go, [V.go_code()])


if __name__ == '__main__':
    unittest.main()
