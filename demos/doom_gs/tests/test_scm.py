"""Tests of tools/v816/scm.py: the reader of linker rules files."""

import unittest

import support
from v816 import scm

RULES = '''
;;; A comment
(define memories
  '((memory DirectPage (address (#x000900 . #x0009ff))
            (section registers ztiny))
    (memory Stack (address (#x000b00 . #x003fff))
            (section stack))
    ;; a comment between the rules
    (memory Code (address (#x030000 . #x03ffff))
            (section (startup #x030000) code (table (#x031000 . #x031fff))))
    (memory More (address (#x040000 . #x04ffff))
            (section code)
            (section far))
    (block stack (size #x3500))
    (base-address _DirectPageStart DirectPage 0)
    (base-address _NearBaseAddress More 16)
    ))
'''


def wrapped(rules):
    return "(define memories '(%s))" % rules


class Reader(unittest.TestCase):
    def test_atoms_lists_and_pairs(self):
        self.assertEqual(
            scm.read("(a (#x10 . #b101) 12 'c) ; rest\n-3 #o17 #d9"),
            [['a', (16, 5), 12, 'c'], -3, 15, 9])

    def test_brackets_must_balance(self):
        for text in ('(a', 'a)', '(a (b)'):
            with self.assertRaises(scm.ScmError):
                scm.read(text)

    def test_bad_pair_and_number(self):
        for text in ('(a . b c)', '(. a)', '(#xzz)'):
            with self.assertRaises(scm.ScmError):
                scm.read(text)


class Rules(unittest.TestCase):
    def setUp(self):
        self.rules = scm.parse(RULES)

    def test_memories(self):
        self.assertEqual(
            [(memory.name, memory.first, memory.last)
             for memory in self.rules.memories],
            [('DirectPage', 0x900, 0x9ff), ('Stack', 0xb00, 0x3fff),
             ('Code', 0x30000, 0x3ffff), ('More', 0x40000, 0x4ffff)])
        self.assertEqual(self.rules.memory('Stack').first, 0xb00)
        with self.assertRaises(scm.ScmError):
            self.rules.memory('Nowhere')

    def test_section_rules(self):
        self.assertEqual(self.rules.memory('Code').sections, (
            scm.SectionRule('startup', 0x30000, 0x3ffff, True),
            scm.SectionRule('code', 0x30000, 0x3ffff, False),
            scm.SectionRule('table', 0x31000, 0x31fff, False)))

    def test_several_section_lists(self):
        self.assertEqual(
            [rule.name for rule in self.rules.memory('More').sections],
            ['code', 'far'])

    def test_accepting(self):
        self.assertEqual(
            [memory.name for memory, _ in self.rules.accepting('code')],
            ['Code', 'More'])
        self.assertEqual(self.rules.accepting('nothing'), [])
        self.assertIsNone(self.rules.memory('Code').rule('far'))

    def test_blocks_and_base_addresses(self):
        self.assertEqual(self.rules.blocks, {'stack': 0x3500})
        self.assertEqual(self.rules.base_addresses, {
            '_DirectPageStart': 0x900, '_NearBaseAddress': 0x40010})


class Refused(unittest.TestCase):
    def refused(self, text):
        with self.assertRaises(scm.ScmError):
            scm.parse(text)

    def test_not_a_definition_of_memories(self):
        self.refused('(memory A (address (0 . 1)))')
        self.refused("(define other '())")

    def test_memory_without_address(self):
        self.refused(wrapped('(memory A (section code))'))

    def test_address_range_backwards(self):
        self.refused(wrapped('(memory A (address (9 . 1)) (section code))'))

    def test_section_outside_its_memory(self):
        self.refused(wrapped(
            '(memory A (address (#x100 . #x1ff)) (section (code #x200)))'))
        self.refused(wrapped(
            '(memory A (address (#x100 . #x1ff)) '
            '(section (code (#x180 . #x200))))'))

    def test_memory_defined_twice(self):
        memory = '(memory A (address (0 . 1)) (section code))'
        self.refused(wrapped(memory + memory))

    def test_rules_that_are_not_supported(self):
        self.refused(wrapped(
            '(memory A (address (0 . 1)) (type ram) (section code))'))
        self.refused(wrapped(
            '(memory A (address (0 . 1)) '
            '(placement-group bits (section code)))'))
        self.refused(wrapped('(scatter A)'))

    def test_base_address_of_unknown_memory(self):
        self.refused(wrapped('(base-address _X Nowhere 0)'))


@support.needs_upstream
class Upstream(unittest.TestCase):
    def rules(self, name):
        return scm.load(support.UPSTREAM / 'src' / 'iigs' / name)

    def test_game(self):
        rules = self.rules('iigs.scm')
        self.assertEqual(len(rules.memories), 68)
        self.assertEqual(rules.blocks, {'stack': 0x3500})
        self.assertEqual(rules.base_addresses, {
            '_DirectPageStart': 0x000900, '_NearBaseAddress': 0x020000})
        self.assertEqual(
            [(memory.name, rule.first, rule.fixed)
             for memory, rule in rules.accepting('startup')],
            [('Code3a', 0x030000, True)])
        self.assertEqual(
            [(memory.name, rule.first, rule.last)
             for memory, rule in rules.accepting('onelist')],
            [('ThirdList', 0x05a6d0, 0x05afff)])
        self.assertEqual(len(rules.accepting('coldcode')), 17)

    def test_boot_and_loader(self):
        self.assertEqual(self.rules('boot.scm').memories, (
            scm.Memory('Boot', 0x0800, 0x09ff, (
                scm.SectionRule('boot', 0x0800, 0x09ff, False),)),))
        self.assertEqual(self.rules('loader.scm').memories, (
            scm.Memory('Loader', 0x6000, 0x77ff, (
                scm.SectionRule('loader', 0x6000, 0x77ff, False),)),))


if __name__ == '__main__':
    unittest.main()
