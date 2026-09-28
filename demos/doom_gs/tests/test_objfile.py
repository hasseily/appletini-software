"""Tests of tools/v816/objfile.py: the assembler of a unit."""

import unittest

import support
from v816 import linear
from v816.linear import Linear, Value


def fragment_of(text):
    return support.assemble_clean(text).fragments[0]


def messages(text):
    return [(error.where.line, error.message)
            for error in support.assemble_text(text).errors]


class Data(unittest.TestCase):
    def test_numbers_of_each_width(self):
        self.assertEqual(
            fragment_of(' .byte 1, 0xff, -1\n .word 0x1234, -2\n'
                        ' .address 0x123456\n .long 0x12345678, 1\n'
                        ' .quad 0x0102030405060708\n').data.hex(),
            '01ffff' '3412feff' '563412' '7856341201000000'
            '0807060504030201')

    def test_strings(self):
        self.assertEqual(
            fragment_of(' .ascii "ab", "c"\n .asciz "de", "f\\n"\n').data,
            b'abc' b'de\0f\n\0')

    def test_number_that_does_not_fit(self):
        self.assertEqual(messages(' nop\n .byte 256\n'),
                         [(2, '.byte: 256 does not fit in 8 bits')])
        self.assertEqual(len(messages(' .word -0x8001\n')), 1)

    def test_addresses_are_holes(self):
        fragment = fragment_of(
            ' .extern p\nhere: .byte 1, .byte2 p\n .word here\n'
            ' .long p + 1\n')
        self.assertEqual(fragment.data.hex(), '0100' '0000' '00000000')
        self.assertEqual(
            [(hole.offset, hole.width, hole.kind, hole.origin, hole.value)
             for hole in fragment.holes],
            [(1, 1, 'data', 0,
              Value('byte2', Linear.atom(('symbol', 'p')))),
             (2, 2, 'data', 2, Value(None, Linear.atom(fragment.atom))),
             (4, 4, 'data', 4,
              Value(None, Linear.atom(('symbol', 'p'), 1)))])

    def test_space_fillto_and_align(self):
        self.assertEqual(
            fragment_of(' .byte 1\n .space 2\n .space 2, 0xee\n'
                        ' .fillto 8, 0x55\n .byte 2\n .align 4\n'
                        ' .byte 3\n').data.hex(),
            '01' '0000' 'eeee' '555555' '02' '000000' '03')

    def test_alignment_of_the_fragment(self):
        fragment = fragment_of(' .align 2\n nop\n .align 8\n .align 4\n')
        self.assertEqual(fragment.alignment, 8)
        self.assertEqual(fragment.size, 8)
        self.assertEqual(fragment_of(' nop\n').alignment, 1)

    def test_sizes_must_be_constants(self):
        self.assertEqual(messages('x: .space x\n'),
                         [(1, 'the size must be a constant')])
        self.assertEqual(len(messages('x: .space 1, x\n')), 1)
        self.assertEqual(len(messages(' .space -1\n')), 1)
        self.assertEqual(len(messages(' nop\n nop\n .fillto 1\n')), 1)
        self.assertEqual(len(messages(' .space 1, 256\n')), 1)

    def test_incbin_is_refused(self):
        self.assertEqual(len(messages(' .incbin "data.bin"\n')), 1)


class Fragments(unittest.TestCase):
    SOURCE = ('first: nop\n'
              ' .section vars, bss\n'
              'v1: .space 2\n'
              'v2: .space 3\n'
              ' .section registers, noinit\n'
              'r: .space 20\n'
              ' .section tables, rodata, root, noreorder\n'
              't: .word v2, first\n')

    def setUp(self):
        self.unit = support.assemble_clean(self.SOURCE, 'u.s')

    def test_keys_sections_and_kinds(self):
        self.assertEqual(
            [(fragment.key, fragment.section, fragment.kind,
              fragment.modifiers, fragment.size)
             for fragment in self.unit.fragments],
            [(('u.s', 0), 'code', 'text', (), 1),
             (('u.s', 1), 'vars', 'bss', (), 5),
             (('u.s', 2), 'registers', 'text', ('noinit',), 20),
             (('u.s', 3), 'tables', 'rodata', ('root', 'noreorder'), 4)])

    def test_bss_and_noinit_have_no_bytes(self):
        code, variables, registers, tables = self.unit.fragments
        self.assertEqual(
            [fragment.initialised for fragment in self.unit.fragments],
            [True, False, False, True])
        self.assertEqual(variables.data, b'')
        self.assertEqual(registers.data, b'')
        self.assertEqual(
            [fragment.cleared for fragment in self.unit.fragments],
            [False, True, False, False])

    def test_labels_and_atoms(self):
        variables = self.unit.fragments[1]
        self.assertEqual(variables.labels, {'v1': 0, 'v2': 2})
        self.assertEqual(variables.atom, ('fragment', 'u.s', 1))
        tables = self.unit.fragments[3]
        self.assertEqual(
            [hole.value.linear for hole in tables.holes],
            [Linear.atom(variables.atom, 2),
             Linear.atom(self.unit.fragments[0].atom)])

    def test_bytes_in_a_section_without_bytes(self):
        self.assertEqual(
            messages(' .section vars, bss\n .byte 1\n'),
            [(1, 'the section vars has no bytes in the program, but the '
                 'source gives it some')])
        self.assertEqual(len(messages(
            ' .section vars, bss\nv: .word v\n')), 1)

    def test_spans(self):
        fragment = fragment_of('a1: nop\n lda #1\nb1: .word 1, 2\n rts\n')
        self.assertEqual(
            [(span.offset, span.length, span.where.line)
             for span in fragment.spans],
            [(0, 1, 1), (1, 2, 2), (3, 4, 3), (7, 1, 4)])
        self.assertEqual(fragment.span_at(0).where.line, 1)
        self.assertEqual(fragment.span_at(2).where.line, 2)
        self.assertEqual(fragment.span_at(6).where.line, 3)
        self.assertEqual(fragment.span_at(7).where.line, 4)
        self.assertIsNone(fragment.span_at(8))

    def test_span_of_a_macro_line(self):
        fragment = fragment_of('two .macro\n nop\n rts\n .endm\n two\n')
        span = fragment.span_at(1)
        self.assertEqual(span.where.line, 3)
        self.assertEqual([use.line for use in span.where.expansions], [5])


class Symbols(unittest.TestCase):
    def test_labels_equates_and_exports(self):
        unit = support.assemble_clean(
            ' .public start, SIZE\n .extern other\n'
            'SIZE .equ end - start\n'
            'start: nop\n'
            'HERE .equ . + 1\n'
            'end: rts\n'
            'ALIAS .equ other + 2\n', 'u.s')
        atom = unit.fragments[0].atom
        self.assertEqual(unit.symbols, {
            'SIZE': linear.constant(1),
            'start': Value(None, Linear.atom(atom)),
            'HERE': Value(None, Linear.atom(atom, 2)),
            'end': Value(None, Linear.atom(atom, 1)),
            'ALIAS': Value(None, Linear.atom(('symbol', 'other'), 2))})
        self.assertEqual(unit.exports, ['start', 'SIZE'])
        self.assertEqual(unit.imports, ['other'])

    def test_local_labels_are_not_symbols(self):
        unit = support.assemble_clean('a1: nop\n1$: bra 1$\n')
        self.assertEqual(list(unit.symbols), ['a1'])
        self.assertEqual(unit.fragments[0].labels, {'a1': 0})

    def test_name_defined_twice(self):
        self.assertEqual(messages('x: nop\nx: nop\n'),
                         [(2, 'x is defined twice')])
        self.assertEqual(messages('x .equ 1\nx: nop\n'),
                         [(2, 'x is defined twice')])

    def test_undefined_name(self):
        self.assertEqual(messages(' lda nothing\n'),
                         [(1, 'undefined symbol nothing')])

    def test_exported_and_not_defined(self):
        self.assertEqual(messages(' .public nothing\n nop\n'),
                         [(1, 'nothing is exported and not defined')])

    def test_equate_that_uses_itself(self):
        found = messages('X .equ Y + 1\nY .equ X + 1\n lda #X\n')
        self.assertEqual(found, [(3, 'the equate X uses itself'),
                                 (2, 'the equate Y uses itself')])

    def test_wrong_equate_that_nothing_uses(self):
        self.assertEqual(messages('X .equ nothing + 1\n nop\n'),
                         [(1, 'undefined symbol nothing')])

    def test_equate_with_a_relocation_operator(self):
        unit = support.assemble_clean(
            ' .extern p\nLOW .equ .word0 p\n lda ##LOW\n')
        self.assertEqual(unit.fragments[0].holes[0].value,
                         Value('word0', Linear.atom(('symbol', 'p'))))

    def test_require_belongs_to_its_fragment(self):
        unit = support.assemble_clean(
            ' .section one\n nop\n .section two\n .require helper\n rts\n'
            ' .section three\n nop\n')
        self.assertEqual([fragment.requires for fragment in unit.fragments],
                         [[], ['helper'], []])
        self.assertEqual(unit.imports, ['helper'])


class Passes(unittest.TestCase):
    def test_size_that_depends_on_a_later_distance(self):
        """With an lda of 2 bytes the distance is 0x100, which needs
        an lda of 3 bytes; the distance is then 0x101."""
        fragment = fragment_of(
            'start: lda end - start\n .space 0xfe\nend: rts\n')
        self.assertEqual(fragment.data[:3].hex(), 'ad0101')
        self.assertEqual(fragment.size, 0x102)
        self.assertEqual(fragment.labels['end'], 0x101)

    def test_short_form_when_the_distance_fits(self):
        fragment = fragment_of(
            'start: lda end - start\n .space 0xfd\nend: rts\n')
        self.assertEqual(fragment.data[:2].hex(), 'a5ff')
        self.assertEqual(fragment.labels['end'], 0xff)

    def test_errors_are_reported_once(self):
        self.assertEqual(len(messages(' lda nothing\n lda end - 1\n'
                                      'end: rts\n')), 1)


if __name__ == '__main__':
    unittest.main()
