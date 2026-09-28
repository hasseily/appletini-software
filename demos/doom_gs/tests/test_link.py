"""Tests of tools/v816/link.py: names across units, the bytes of
holes, the built image."""

import unittest

import support
from v816 import asm816, link, linear
from v816.linear import Linear, Value

RULES = '''
(define memories
  '((memory DirectPage (address (#x000900 . #x0009ff)) (section ztiny))
    (memory Near (address (#x020000 . #x02ffff)) (section near znear))
    (memory Code (address (#x030000 . #x03ffff)) (section code tables))
    (memory More (address (#x040000 . #x04ffff)) (section far))
    (base-address _DirectPageStart DirectPage 0)
    (base-address _NearBaseAddress Near 0)
    ))
'''

MAIN = '''
 .public main
 .extern helper, counter, zp, LIMIT, _NearBaseAddress
 .section code, text, root
main: lda ##LIMIT
 sta abs:.near counter
 inc dp:.tiny (zp+1)
 jsr .kbank local
 jsl long:helper
 lda ##.word2 _NearBaseAddress
 bra main
local: rts
'''
LIBRARY = '''
 .public helper, counter, zp, LIMIT, unused
 .extern main
LIMIT .equ 0x1234
 .section far
helper: jmp long:main
 .section far
unused: rts
 .section znear, bss
 .space 0x10
counter: .space 2
 .section ztiny, bss
zp: .space 4
'''
# The fragments of lib.s: 0 is the "code" that every source starts in
# (it holds the equate), 1 helper, 2 unused, 3 znear, 4 ztiny.
PLACES = {('main.s', 0): 0x030100, ('lib.s', 1): 0x040000,
          ('lib.s', 3): 0x020200, ('lib.s', 4): 0x000920}


def hole(value, width=2, kind=asm816.KIND_ABSOLUTE, origin=0):
    return asm816.Hole(origin + 1, width, value, kind, origin)


class Names(unittest.TestCase):
    def setUp(self):
        self.program = support.program_of(
            {'main.s': MAIN, 'lib.s': LIBRARY}, RULES)

    def test_no_problems(self):
        self.assertEqual(self.program.problems, [])
        self.assertEqual(self.program.undefined(), [])

    def test_holes_have_the_values_of_other_units(self):
        values = [each.value for each in self.program.holes[('main.s', 0)]]
        own = ('fragment', 'main.s', 0)
        self.assertEqual(values, [
            linear.constant(0x1234),
            Value('near', Linear.atom(('fragment', 'lib.s', 3), 0x10)),
            Value('tiny', Linear.atom(('fragment', 'lib.s', 4), 1)),
            Value('kbank', Linear.atom(own, 20)),
            Value(None, Linear.atom(('fragment', 'lib.s', 1))),
            linear.constant(2)])

    def test_constants_of_other_units_and_of_the_rules(self):
        built = support.linked_at(self.program, PLACES)
        self.assertEqual(built.memory.read(0x030100, 3).hex(), 'a93412')
        self.assertEqual(built.memory.read(0x03010f, 3).hex(), 'a90200')

    def test_symbols_of_each_unit(self):
        self.assertEqual(self.program.symbols['lib.s']['LIMIT'],
                         linear.constant(0x1234))
        self.assertEqual(
            self.program.symbols['main.s']['local'],
            Value(None, Linear.atom(('fragment', 'main.s', 0), 20)))
        self.assertEqual(sorted(self.program.exports),
                         ['LIMIT', 'counter', 'helper', 'main', 'unused',
                          'zp'])

    def test_reachable(self):
        self.assertEqual(self.program.reachable(), {
            ('main.s', 0), ('lib.s', 1), ('lib.s', 3), ('lib.s', 4)})

    def test_built_image(self):
        built = support.linked_at(self.program, PLACES)
        self.assertEqual(built.problems, [])
        self.assertEqual(
            built.memory.read(0x030100, 21).hex(),
            'a93412' '8d1002' 'e621' '201401' '22000004' 'a90200' '80ec'
            '60')
        self.assertEqual(built.memory.read(0x040000, 4).hex(), '5c000103')
        self.assertEqual(built.key_at(0x030105), ('main.s', 0))
        self.assertEqual(built.key_at(0x040003), ('lib.s', 1))
        self.assertIsNone(built.key_at(0x040004))
        self.assertIsNone(built.key_at(0x020200))


class NameProblems(unittest.TestCase):
    def test_exported_twice(self):
        program = support.program_of(
            {'a.s': ' .public x\nx: nop\n', 'b.s': ' .public x\nx: nop\n'},
            RULES)
        self.assertEqual([problem.message for problem in program.problems],
                         ['b.s: x is exported by another unit too'])

    def test_exported_with_an_operator(self):
        program = support.program_of(
            {'a.s': ' .public x\n .extern p\nx .equ .word0 p\n'}, RULES)
        self.assertEqual(len(program.problems), 1)

    def test_undefined(self):
        program = support.program_of(
            {'a.s': ' .extern nowhere\n jsl nowhere\n'}, RULES)
        self.assertEqual(program.undefined(), ['nowhere'])

    def test_export_that_is_an_equate_of_an_import(self):
        program = support.program_of({
            'a.s': ' .public alias\n .extern real\nalias .equ real + 1\n',
            'b.s': ' .public real\nreal: nop\n',
            'c.s': ' .extern alias\n jsl alias\n'}, RULES)
        self.assertEqual(
            program.holes[('c.s', 0)][0].value.linear,
            Linear.atom(('fragment', 'b.s', 0), 1))

    def test_no_value_for_a_hole(self):
        program = support.program_of(
            {'a.s': ' .extern nowhere\n nop\n jsl nowhere\n'}, RULES)
        built = support.linked_at(program, {('a.s', 0): 0x030000})
        self.assertEqual(built.problems, [
            link.Problem('no value for nowhere', ('a.s', 0), 2)])
        self.assertEqual(built.memory.read(0x030000, 5).hex(),
                         'ea22000000')

    def test_fragments_that_overlap(self):
        program = support.program_of(
            {'a.s': ' .section code\n nop\n nop\n .section code\n rts\n'},
            RULES)
        built = support.linked_at(
            program, {('a.s', 0): 0x030000, ('a.s', 1): 0x030001})
        self.assertEqual(
            [problem.message for problem in built.problems],
            ['1 bytes at $030001 are in two fragments: a.s#0 and a.s#1'])


class Reachable(unittest.TestCase):
    def reachable(self, sources):
        return support.program_of(sources, RULES).reachable()

    def test_root_by_name(self):
        self.assertEqual(self.reachable({'a.s': (
            ' .public __program_root_section\n'
            ' .section code\n__program_root_section: jsr .kbank f\n'
            ' .section code\nf: rts\n'
            ' .section code\ng: rts\n')}), {('a.s', 0), ('a.s', 1)})

    def test_nothing_without_a_root(self):
        self.assertEqual(self.reachable({'a.s': ' nop\n'}), set())

    def test_require(self):
        self.assertEqual(self.reachable({'a.s': (
            ' .public part\n'
            ' .section code, root\n .require part\n nop\n'
            ' .section code\npart: rts\n')}), {('a.s', 0), ('a.s', 1)})

    def test_initialization_when_a_section_is_cleared(self):
        startup = (
            ' .public __data_initialization_needed\n'
            ' .section code, root\n%s nop\n'
            ' .section code, noroot\n__data_initialization_needed: rts\n'
            ' .section znear, bss\nv: .space 2\n')
        self.assertEqual(self.reachable({'a.s': startup % ''}),
                         {('a.s', 0)})
        self.assertEqual(
            self.reachable({'a.s': startup % ' lda abs:.near v\n'}),
            {('a.s', 0), ('a.s', 1), ('a.s', 2)})


class StoredBytes(unittest.TestCase):
    BASES = {'_DirectPageStart': 0x900, '_NearBaseAddress': 0x20000}
    A = ('fragment', 'a.s', 0)

    def stored(self, value, width=2, kind=asm816.KIND_ABSOLUTE,
               known=None, base=0x30000):
        result = link.stored(hole(value, width, kind), base,
                             known or {self.A: 0x21234}, self.BASES)
        return (result.data.hex(), result.problem)

    def test_unknown_atom(self):
        value = Value(None, Linear.atom(('symbol', 'p')))
        self.assertIsNone(link.stored(hole(value), 0, {}, self.BASES))

    def test_address_without_operator(self):
        value = Value(None, Linear.atom(self.A, 1))
        self.assertEqual(self.stored(value), ('3512', None))
        self.assertEqual(self.stored(value, 3, asm816.KIND_LONG),
                         ('351202', None))
        self.assertEqual(self.stored(value, 4, asm816.KIND_DATA),
                         ('35120200', None))

    def test_parts(self):
        for reloc, width, expected in (
                ('byte0', 1, '34'), ('byte1', 1, '12'), ('byte2', 1, '02'),
                ('word0', 2, '3412'), ('word2', 2, '0200')):
            self.assertEqual(
                self.stored(Value(reloc, Linear.atom(self.A)), width,
                            asm816.KIND_IMMEDIATE), (expected, None))

    def test_near(self):
        self.assertEqual(self.stored(Value('near', Linear.atom(self.A))),
                         ('3412', None))
        data, problem = self.stored(Value('near', Linear.atom(self.A)),
                                    known={self.A: 0x31234})
        self.assertEqual(data, '3412')
        self.assertIn('outside the area', problem)

    def test_tiny(self):
        value = Value('tiny', Linear.atom(self.A, 2))
        self.assertEqual(
            self.stored(value, 1, asm816.KIND_DIRECT, {self.A: 0x910}),
            ('12', None))
        self.assertIsNotNone(
            self.stored(value, 1, asm816.KIND_DIRECT, {self.A: 0xa00})[1])
        self.assertIsNotNone(
            self.stored(value, 1, asm816.KIND_DIRECT, {self.A: 0x8f0})[1])

    def test_kbank(self):
        value = Value('kbank', Linear.atom(self.A))
        self.assertEqual(self.stored(value, base=0x20000), ('3412', None))
        data, problem = self.stored(value, base=0x30000)
        self.assertEqual(data, '3412')
        self.assertIn('not in the bank', problem)

    def test_operator_without_its_base(self):
        result = link.stored(hole(Value('near', Linear(0x20000))), 0, {},
                             {})
        self.assertIn('_NearBaseAddress', result.problem)

    def test_branch(self):
        value = Value(None, Linear(-3))
        self.assertEqual(self.stored(value, 1, asm816.KIND_BRANCH),
                         ('fd', None))
        self.assertEqual(
            self.stored(Value(None, Linear(127)), 1, asm816.KIND_BRANCH),
            ('7f', None))
        for distance in (128, -129):
            self.assertIsNotNone(self.stored(
                Value(None, Linear(distance)), 1, asm816.KIND_BRANCH)[1])
        self.assertEqual(
            self.stored(Value(None, Linear(-0x8000)), 2,
                        asm816.KIND_BRANCH), ('0080', None))


class Texts(unittest.TestCase):
    def test_atoms(self):
        self.assertEqual(link.atom_text(('fragment', 'a.s', 3)),
                         'the address of a.s#3')
        self.assertEqual(link.atom_text(('symbol', 'main')), 'main')
        self.assertEqual(
            link.atom_text(('section', 'sectionEnd', 'stack')),
            '.sectionEnd stack')


if __name__ == '__main__':
    unittest.main()
