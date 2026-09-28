"""Tests of tools/v816/stats.py on small sources."""

import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)
from v816 import cpp, parse, stats

SOURCE = '''\
;;; a comment with lda ##1 and jsl x
#include "other.inc"
#if TICSTEP > 1
              sep     #0x20            ; both sides of an #if count
#else
              rep     #0x20
#endif
PUT           .macro  value
              lda     ##\\value
              sta     long:(table+2),x
              .endm
L(entry):     lda     long:floorclip,x
L(here)       .equ    .
f:            PUT     5
              jsr     .kbank g
              jsl     long:h
              jmp     long:h
              jmp     (abs:vector)
1$:           lda     [.tiny (_Dp+4)],y
              sta     [dp:ptr]
              lda     3,s
              lda     (5,s),y
              lda     .near value
              ldx     abs: .near (value + 2)
              phb
              plb
              xba
              bra     1$
              .byte   0x54, 0x02, 0x03  ; mvn
              .byte   0x54              ; mvn, banks below
              .byte   0x54, 1, 2, 3
              .byte   84, 84, 84, 84
              .asciz  "lda ##1"
'''


class SourceCounts(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'a.s'
        self.path.write_text(SOURCE)
        self.counts = stats.source_counts([self.path])

    def test_lines(self):
        self.assertEqual(self.counts['lines'], SOURCE.count('\n'))

    def test_preprocessor_lines(self):
        self.assertEqual(self.counts['preprocessor'],
                         {'include': 1, 'if': 1, 'else': 1, 'endif': 1})

    def test_macro_definitions(self):
        self.assertEqual(self.counts['macro_definitions'],
                         [(str(self.path), 8, 'PUT')])

    def test_instruction_lines(self):
        # the use of PUT, the equate and the data are none
        self.assertEqual(self.counts['instruction_lines'], 19)
        self.assertEqual(self.counts['mnemonics']['lda'], 6)

    def test_constructs(self):
        self.assertEqual(
            {name: count
             for name, count in self.counts['constructs'].items() if count},
            {'rep/sep': 2, 'jsl': 1, 'jsr': 1, 'long:': 4, 'jmp long:': 1,
             '[dp]': 2, ',s': 2, '## immediate': 1, '.near': 2,
             'phb/plb': 2, 'xba': 1, 'bra': 1, 'mvn': 2})

    def test_files_add_up(self):
        twice = stats.source_counts([self.path, self.path])
        self.assertEqual(twice['lines'], 2 * self.counts['lines'])
        self.assertEqual(twice['instruction_lines'], 38)


class UnitCounts(unittest.TestCase):
    TEXT = '''\
N             .equ    5
PUT           .macro  value
              lda     ##\\value
              sta     long:(table+2),x
              .endm
              .section farcode, text
f:            PUT     1
              PUT     2
here          .equ    .
1$:           lda     [.tiny (_Dp+4)],y
              lda     dp: .tiny x
              lda     ##.word0 STAGE + 2
              asl     a
              rts
              .byte   0x54, 0x02, 0x03
              .byte   0x54, 1, 2, 3
              .section znear, bss
v:            .space  2
              .section farcode
              .section farcode, text
              .public f
              .extern x, table
'''

    def setUp(self):
        lines = cpp.Preprocessor().process_text(self.TEXT)
        unit, _ = parse.parse_lines(lines, 't.s')
        self.assertEqual(unit.errors, [])
        self.counts = stats.unit_counts([unit, unit])

    def test_instructions(self):
        self.assertEqual(self.counts['instructions'], 2 * 9)
        self.assertEqual(self.counts['mnemonics']['lda'], 2 * 5)

    def test_modes(self):
        self.assertEqual(self.counts['modes'],
                         {'##': 6, 'e,x': 4, '[e],y': 2, 'e': 2, 'a': 2,
                          '': 2})

    def test_sizes(self):
        self.assertEqual(self.counts['sizes'],
                         {'': 6, 'long:': 4, '.tiny': 2, 'dp: .tiny': 2})

    def test_constructs(self):
        self.assertEqual(
            {name: count
             for name, count in self.counts['constructs'].items() if count},
            {'## immediate': 6, 'long:': 4, '[dp]': 2, 'mvn': 2})

    def test_nested_relocations(self):
        self.assertEqual(self.counts['nested_relocations'], 2)

    def test_fragments(self):
        self.assertEqual(self.counts['fragments'],
                         {'code': 2, 'farcode': 6, 'znear': 2})
        self.assertEqual(self.counts['filled_fragments'],
                         {'farcode': 2, 'znear': 2})
        self.assertEqual(self.counts['section_kinds'],
                         {'code': {'(none)'}, 'znear': {'bss'},
                          'farcode': {'text', '(none)'}})

    def test_other_items(self):
        self.assertEqual(
            [self.counts[name] for name in (
                'labels', 'local_labels', 'equates', 'position_equates')],
            [4, 2, 4, 2])
        self.assertEqual(self.counts['data'], {'.byte': 4, '.space': 2})
        self.assertEqual(self.counts['declarations'],
                         {'public': 2, 'extern': 4})


if __name__ == '__main__':
    unittest.main()
