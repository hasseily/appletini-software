"""Tests of tools/v816/place.py: layout recovery.

Each test assembles small units, links them at addresses of its choice
(support.linked_at) and takes the result as the release image. The
recovery gets the units and the image, not the addresses.
"""

import unittest

import support
from v816 import asm816, memimage, place
from v816.linear import Linear, Value

RULES = '''
(define memories
  '((memory DirectPage (address (#x000900 . #x0009ff)) (section ztiny))
    (memory Near (address (#x020000 . #x027fff)) (section near))
    (memory NearBss (address (#x028000 . #x02ffff)) (section znear))
    (memory Start (address (#x030000 . #x0300ff))
            (section (startup #x030000)))
    (memory Code3 (address (#x030100 . #x03ffff)) (section code tables))
    (memory Code4 (address (#x040000 . #x04ffff)) (section code))
    (memory FarBss (address (#x0d0000 . #x0dffff)) (section zfar))
    (base-address _DirectPageStart DirectPage 0)
    (base-address _NearBaseAddress Near 0)
    ))
'''

MAIN = '''
 .extern draw, think, table
 .section startup, text, root
start: jsl long:draw
 jsl long:think
 lda long:table
 lda abs:.near counter
 lda dp:.tiny zp
 lda long:far
 brl start
 .section znear, bss
 .space 6
counter: .space 2
 .section ztiny, bss
zp: .space 2
 .section zfar, bss
far: .space 0x100
'''
GAME = '''
 .public draw, think, table
 .section code
draw: ldx ##0x1111
 jsr .kbank shared
 rtl
 .section code
think: ldx ##0x2222
 jsr .kbank shared
 rtl
 .section code
shared: inc abs:.near state
 rts
 .section tables, rodata
table: .word draw, think
 .byte .byte2 draw
 .section near, data
state: .word 0x55aa
 .section code
unused: .ascii "never called"
'''
# The fragments of game.s: 0 draw, 1 think, 2 shared, 3 table, 4 state,
# 5 unused.
PLACES = {
    ('main.s', 0): 0x030000, ('main.s', 1): 0x028010,
    ('main.s', 2): 0x000940, ('main.s', 3): 0x0d1000,
    ('game.s', 0): 0x030400, ('game.s', 1): 0x030200,
    ('game.s', 2): 0x030300, ('game.s', 3): 0x030180,
    ('game.s', 4): 0x020400}


def recovered(sources, places, change=None, rules=RULES):
    """(program, layout) for `sources` linked at `places`. `change`
    gets the bytes of the image by bank, to spoil them."""
    program = support.program_of(sources, rules)
    memory = support.linked_at(program, places).memory
    if change:
        changed = memimage.MemoryImage()
        for region in memory.regions:
            data = bytearray(memory.read(region.address, region.length))
            change(region.address, data)
            changed.load(region.address, bytes(data))
        memory = changed
    return program, place.recover(program, memory)


class Recovery(unittest.TestCase):
    def setUp(self):
        self.program, self.layout = recovered(
            {'main.s': MAIN, 'game.s': GAME}, PLACES)

    def test_every_fragment_is_where_it_was_put(self):
        self.assertEqual(self.layout.addresses(), PLACES)
        self.assertEqual(self.layout.unplaced, [])
        self.assertEqual(self.layout.ambiguous, {})
        self.assertTrue(all(placement.exact for placement
                            in self.layout.placements.values()))

    def test_methods(self):
        methods = {key: placement.method
                   for key, placement in self.layout.placements.items()}
        self.assertEqual(methods[('main.s', 0)], place.METHOD_MATCH)
        for key in (('main.s', 1), ('main.s', 2), ('main.s', 3)):
            self.assertEqual(methods[key], place.METHOD_REFERENCE)

    def test_known_atoms(self):
        self.assertEqual(
            self.layout.known,
            {self.program.fragments[key].atom: address
             for key, address in PLACES.items()})

    def test_constraints_name_their_hole(self):
        found = self.layout.constraints[('fragment', 'main.s', 3)]
        self.assertEqual(found, [place.Constraint(
            ('fragment', 'main.s', 3), 0x0d1000, 0xffffff,
            ('main.s', 0), 18)])
        self.assertEqual(place.conflicts(self.layout.constraints,
                                         self.layout.known), [])

    def test_fragment_that_is_not_part_of_the_program(self):
        self.assertNotIn(('game.s', 5), self.layout.placements)
        self.assertNotIn(('game.s', 5), self.layout.unplaced)


class Twins(unittest.TestCase):
    """Two fragments with the same bytes."""

    TWINS = (' .section code\nf1: lda #1\n rtl\n'
             ' .section code\nf2: lda #1\n rtl\n')
    PLACES = {('t.s', 0): 0x030000, ('t.s', 1): 0x030200,
              ('t.s', 2): 0x040300}

    def test_told_apart_by_the_holes_that_refer_to_them(self):
        source = (' .section startup, root\n jsl long:f1\n jsl long:f2\n'
                  + self.TWINS)
        _, layout = recovered({'t.s': source}, self.PLACES)
        self.assertEqual(layout.addresses(), self.PLACES)

    def test_ambiguous_when_nothing_tells_them_apart(self):
        source = (' .section startup, root\n .require f1\n .require f2\n'
                  ' nop\n .public f1, f2\n' + self.TWINS)
        _, layout = recovered({'t.s': source}, self.PLACES)
        self.assertEqual(layout.addresses(), {('t.s', 0): 0x030000})
        self.assertEqual(layout.ambiguous, {
            ('t.s', 1): [0x030200, 0x040300],
            ('t.s', 2): [0x030200, 0x040300]})
        self.assertEqual(layout.unplaced, [])


class LowBits(unittest.TestCase):
    """A 16-bit hole gives the low 16 bits of an address; the bytes of
    the fragment decide the bank."""

    SOURCE = (' .section startup, root\n .word f\n'
              ' .section code\nf: lda #%d\n rtl\n')

    def test_bank_by_the_bytes(self):
        for address in (0x031234, 0x041234):
            places = {('t.s', 0): 0x030000, ('t.s', 1): address}
            _, layout = recovered({'t.s': self.SOURCE % 7}, places)
            self.assertEqual(layout.addresses(), places)
            self.assertEqual(
                layout.constraints[('fragment', 't.s', 1)][0][:3],
                (('fragment', 't.s', 1), 0x1234, 0xffff))


class Damaged(unittest.TestCase):
    """The image differs from what the units give."""

    def test_placed_by_reference(self):
        def change(address, data):
            if address == 0x030400:
                data[1] ^= 0xff         # the operand of ldx in draw

        _, layout = recovered({'main.s': MAIN, 'game.s': GAME}, PLACES,
                              change)
        self.assertEqual(layout.addresses(), PLACES)
        self.assertEqual(layout.placements[('game.s', 0)],
                         place.Placement(0x030400, 'reference', False))
        self.assertEqual(
            [key for key, placement in layout.placements.items()
             if not placement.exact], [('game.s', 0)])

    def test_placed_approximately(self):
        source = (' .section startup, root\n .require f\n nop\n'
                  ' .public f\n .section code\n'
                  'f: .ascii "0123456789"\n .byte 1, 2, 3\n'
                  ' .ascii "abcdefghij"\n')
        places = {('t.s', 0): 0x030000, ('t.s', 1): 0x045000}

        def change(address, data):
            if address == 0x045000:
                data[11] = 0xee

        _, layout = recovered({'t.s': source}, places, change)
        self.assertEqual(layout.placements[('t.s', 1)],
                         place.Placement(0x045000, 'approximate', False))

    def test_not_found(self):
        def change(address, data):
            if address == 0x030180:
                data[:] = bytes(len(data))

        source = MAIN.replace(' lda long:table\n', ' .require table\n')
        _, layout = recovered({'main.s': source, 'game.s': GAME}, PLACES,
                              change)
        self.assertEqual(layout.unplaced, [('game.s', 3)])
        self.assertNotIn(('game.s', 3), layout.placements)

    def test_one_reference_of_three_is_wrong(self):
        source = MAIN.replace(' brl start\n', ' sta abs:.near counter\n'
                              ' inc abs:.near counter\n')

        def change(address, data):
            if address == 0x030000:
                data[13] ^= 0x01        # lda abs:.near counter

        _, layout = recovered({'main.s': source, 'game.s': GAME}, PLACES,
                              change)
        self.assertEqual(layout.placements[('main.s', 1)],
                         place.Placement(0x028010, 'reference', False))
        self.assertEqual(
            place.conflicts(layout.constraints, layout.known),
            [place.Constraint(('fragment', 'main.s', 1), 0x028011,
                              0xffffff, ('main.s', 0), 13)])

    def test_references_that_contradict_each_other(self):
        source = MAIN.replace(' brl start\n', ' sta abs:.near counter\n')

        def change(address, data):
            if address == 0x030000:
                data[13] ^= 0x01

        _, layout = recovered({'main.s': source, 'game.s': GAME}, PLACES,
                              change)
        self.assertEqual(layout.unplaced, [('main.s', 1)])
        self.assertEqual(
            [(constraint.value, constraint.offset) for constraint
             in place.conflicts(layout.constraints, layout.known)],
            [(0x028011, 13), (0x028010, 22)])


class Rules(unittest.TestCase):
    def test_section_at_a_fixed_address(self):
        """The bytes of startup are in the code memory too; the rules
        allow the fixed address only."""
        source = ' .section startup, root\n rtl\n .section code\n rtl\n'
        places = {('t.s', 0): 0x030000, ('t.s', 1): 0x030100}
        source += ' .public last\nlast .equ .\n'
        program = support.program_of({'t.s': source}, RULES)
        memory = support.linked_at(program, places).memory
        layout = place.recover(program, memory)
        self.assertEqual(layout.addresses(), {('t.s', 0): 0x030000})

    def test_address_outside_the_memories_of_the_section(self):
        source = (' .section startup, root\n jsl long:f\n'
                  ' .section code\nf: rtl\n')
        places = {('t.s', 0): 0x030000, ('t.s', 1): 0x050000}
        _, layout = recovered({'t.s': source}, places)
        self.assertEqual(layout.unplaced, [('t.s', 1)])

    def test_alignment(self):
        source = (' .section startup, root\n .require f\n nop\n'
                  ' .public f\n .section code\n .align 4\nf: rtl\n')
        for address, found in ((0x031000, True), (0x031002, False)):
            places = {('t.s', 0): 0x030000, ('t.s', 1): address}
            _, layout = recovered({'t.s': source}, places)
            self.assertEqual(('t.s', 1) in layout.placements, found)

    def test_empty_fragment_with_a_label(self):
        source = (' .section startup, root\n .word end\n lda long:end\n'
                  ' .section code\nend:\n')
        places = {('t.s', 0): 0x030000, ('t.s', 1): 0x04ffff + 1}
        _, layout = recovered({'t.s': source}, places)
        self.assertEqual(layout.addresses(), places)


class Solve(unittest.TestCase):
    BASES = {'_DirectPageStart': 0x900, '_NearBaseAddress': 0x20000}
    P = ('symbol', 'p')

    def solve(self, value, data, width=None, kind=asm816.KIND_DATA,
              known=None, origin=0):
        data = bytes.fromhex(data)
        hole = asm816.Hole(origin + 1, width or len(data), value, kind,
                           origin)
        found = place.solve(hole, 0x031000, data, known or {}, self.BASES)
        return found and (found.atom, found.value, found.mask)

    def test_whole_address(self):
        value = Value(None, Linear.atom(self.P, 2))
        self.assertEqual(self.solve(value, '563412'),
                         (self.P, 0x123454, 0xffffff))
        self.assertEqual(self.solve(value, '56341200'),
                         (self.P, 0x123454, 0xffffff))

    def test_low_bits(self):
        value = Value(None, Linear.atom(self.P, 2))
        self.assertEqual(self.solve(value, '0100'),
                         (self.P, 0xffff, 0xffff))
        self.assertEqual(
            self.solve(Value('word0', Linear.atom(self.P)), '3412'),
            (self.P, 0x1234, 0xffff))

    def test_too_few_bits(self):
        for reloc, data in ((None, '12'), ('byte0', '12'), ('byte1', '12'),
                            ('byte2', '12'), ('word2', '1200')):
            self.assertIsNone(
                self.solve(Value(reloc, Linear.atom(self.P)), data))

    def test_operators_with_a_base(self):
        self.assertEqual(
            self.solve(Value('near', Linear.atom(self.P, 1)), '3412'),
            (self.P, 0x021233, 0xffffff))
        self.assertEqual(
            self.solve(Value('tiny', Linear.atom(self.P)), '12'),
            (self.P, 0x000912, 0xffffff))
        self.assertEqual(
            self.solve(Value('kbank', Linear.atom(self.P)), '3412'),
            (self.P, 0x031234, 0xffffff))

    def test_branch(self):
        own = ('fragment', 'a.s', 0)
        value = Value(None, Linear(-5, [(self.P, 1), (own, -1)]))
        self.assertEqual(
            self.solve(value, 'fbff', kind=asm816.KIND_BRANCH,
                       known={own: 0x031000}),
            (self.P, 0x031000, 0xffffff))
        self.assertEqual(
            self.solve(value, '10', kind=asm816.KIND_BRANCH,
                       known={own: 0x031000}),
            (self.P, 0x031015, 0xffffff))

    def test_negative_coefficient(self):
        value = Value(None, Linear(0x100, [(self.P, -1)]))
        self.assertEqual(self.solve(value, 'f000'),
                         (self.P, 0x0010, 0xffff))

    def test_values_that_cannot_be_solved(self):
        other = ('symbol', 'q')
        for terms in ([(self.P, 2)], [(self.P, 1), (other, 1)], []):
            self.assertIsNone(
                self.solve(Value(None, Linear(0, terms)), '563412'))


class Pattern(unittest.TestCase):
    def test_holes_match_any_bytes(self):
        fragment = support.assemble_clean(
            ' .extern p\n lda #1\n jsl p\n .byte 0x2e, 10\n').fragments[0]
        compiled = place.pattern(fragment)
        self.assertTrue(compiled.fullmatch(
            bytes.fromhex('a901' '220a0d00' '2e0a')))
        self.assertFalse(compiled.fullmatch(
            bytes.fromhex('a901' '220a0d00' '2f0a')))
        self.assertFalse(compiled.fullmatch(
            bytes.fromhex('a901' '220a0d00' '2e0a' '00')))


if __name__ == '__main__':
    unittest.main()
