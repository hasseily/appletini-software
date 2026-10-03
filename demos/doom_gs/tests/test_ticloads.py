"""The speed plan's part ticloads (docs/speed-parts/ticloads.md): the tic
phase's loads made smaller, checked where they are decided at build time.

  - grun.group_entry, gcall.s's group directory: a group's whole pages
    and the bytes of the page after them that gr_load copies (its length
    rounded up to an even count, at least the group; the page whole for a
    group under a page or a tail past TAIL_MAX).
  - playdisk.abs_writes, the sweep behind the shared-W rule: it finds the
    65C02's absolute stores and read-modify-writes, plain and indexed.
  - The play build's links (skipped when build/ lacks it): the group link
    check (playdisk.group_problems) and the shared-W rule
    (playdisk.shared_w_problems: the tic image's, P2DW's and WCODE's MATHW
    and AUXW the same, no write there from P2DW's load to K_TIC but AUXW's
    self-set operands, the kernel's lists at KLISTS) hold; each catches a
    planted fault (a label past a group, a write into the shared W).
"""

import sys
import unittest
from unittest import mock

from support import ROOT

sys.path.insert(0, str(ROOT / 'tools'))

from native import grun as G, playdisk as P, pldisk  # noqa: E402


def entry(size):
    return dict(G.group_entry(72, 2, size))


class Directory(unittest.TestCase):
    def test_covers_the_group_and_no_more_than_its_even_length(self):
        for size in range(1, 0x801):
            e = entry(size)
            copied = 256 * e['grp_pages'] + e['grp_tail']
            self.assertGreaterEqual(copied, size)
            self.assertGreaterEqual(e['grp_pages'], 1)
            self.assertEqual(e['grp_tail'] & 1, 0)
            tail = (size & 0xFF) + (size & 1)
            if size >= 0x100 and 0 < tail <= G.TAIL_MAX:
                self.assertEqual(copied, (size + 1) & ~1, size)
            else:
                self.assertEqual(e['grp_tail'], 0, size)
                self.assertEqual(copied, (size + 0xFF) & ~0xFF, size)

    def test_examples(self):
        self.assertEqual(entry(1976), dict(grp_bank=72, grp_src=2,
                                           grp_pages=7, grp_tail=184))
        self.assertEqual(entry(1895)['grp_tail'], 104)     # odd: one more
        self.assertEqual(entry(228), dict(grp_bank=72, grp_src=2,
                                          grp_pages=1, grp_tail=0))
        self.assertEqual(entry(0x700)['grp_pages'], 7)
        self.assertEqual(entry(0x6E1)['grp_pages'], 7)     # 225: whole
        self.assertEqual(entry(0x6E1)['grp_tail'], 0)
        with self.assertRaises(G.RunError):
            entry(0x801)


class Sweep(unittest.TestCase):
    def test_absolute_writes(self):
        code = bytes([0xA9, 0x00,               # lda #0
                      0x8D, 0x10, 0x60,         # sta $6010
                      0xAD, 0x20, 0x60,         # lda $6020 (a read)
                      0x9D, 0x00, 0x65,         # sta $6500,x
                      0xEE, 0xFF, 0x65,         # inc $65FF
                      0x9C, 0x00, 0x66,         # stz $6600 (past)
                      0x0C, 0x30, 0x61,         # tsb $6130
                      0x91, 0x10,               # sta ($10),y (indirect)
                      0x20, 0x8D, 0x60,         # jsr $608D (no store)
                      0x60])
        got = P.abs_writes(code, 0x7000, 0x6000, 0x6600)
        self.assertEqual(got, [(0x7002, 0x6010), (0x7008, 0x6500),
                               (0x700B, 0x65FF), (0x7011, 0x6130)])

    def test_lengths(self):
        self.assertEqual([P.op_length(op) for op in
                          (0x00, 0x20, 0x60, 0x10, 0xA9, 0xB9, 0x99, 0xAD,
                           0x0F, 0xCB, 0x5C, 0xE8)],
                         [1, 3, 1, 2, 2, 3, 3, 3, 3, 1, 3, 1])


@unittest.skipUnless((P.PLAY / 'tic' / 'tic.map').exists() and
                     (pldisk.RCARD / 'rcard.map').exists() and
                     not pldisk.missing(),
                     'build/ lacks the play build (python3 '
                     'tools/native/playdisk.py)')
class Links(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        boot = pldisk.load_boot(P.PLAY / 'card')
        cls.main = pldisk.card_images(boot)[1]

    def test_groups(self):
        self.assertEqual(P.group_problems(P.PLAY), [])

    def test_shared_w(self):
        self.assertEqual(P.shared_w_problems(P.PLAY, self.main), [])

    def test_planted_label_past_a_group(self):
        b = P.PK.tic_build(P.PLAY)
        labels = dict(b.labels, planted_past=0xADFF)
        with mock.patch.object(P.PK, 'tic_build',
                               return_value=b._replace(labels=labels)):
            got = P.group_problems(P.PLAY)
        self.assertTrue(any('planted_past' in g for g in got), got)

    def test_planted_write_into_the_shared_w(self):
        lo = P.PL.KERNEL[0] + 0x2000 - 0xE000
        main = bytearray(self.main)
        at = main.index(bytes([0x8D]), lo)          # a store of the kernel
        main[at + 1:at + 3] = bytes([0x00, 0x61])   #   aimed at $6100
        got = P.shared_w_problems(P.PLAY, bytes(main))
        self.assertTrue(any('the kernel writes $6100' in g for g in got),
                        got)


if __name__ == '__main__':
    unittest.main()
