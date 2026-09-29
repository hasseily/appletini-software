"""Tests of tools/v816/evidence.py: how many things in the image give
each number of the layout."""

import unittest

import support
from v816 import evidence, link, place, sections

RULES = '''
(define memories
  '((memory Stack (address (#x000b00 . #x003fff)) (section stack))
    (memory Heap (address (#x004000 . #x007fff)) (section heap))
    (memory NearBss (address (#x028000 . #x02ffff)) (section znear))
    (memory Code (address (#x030000 . #x03ffff))
            (section (startup #x030000) code))
    (block stack (size #x3500))
    (block heap (size #x1000))
    (base-address _NearBaseAddress NearBss 0)
    ))
'''
HEAP_END = ('section', 'sectionEnd', 'heap')
STACK_END = ('section', 'sectionEnd', 'stack')


def weighed(source, places, known=None):
    """(program, Evidence) for `source` linked at `places`, with the
    numbers `known` of the atoms that are not addresses."""
    program = support.program_of({'t.s': source}, RULES)
    numbers = {program.fragments[key].atom: address
               for key, address in places.items()}
    numbers.update(known or {})
    memory = link.link(program, places, numbers).memory
    layout = place.recover(program, memory)
    finished = sections.finish(program, layout)
    return program, evidence.weigh(program, layout, finished, memory)


class Fragments(unittest.TestCase):
    def test_bss_with_one_reference(self):
        source = (' .section startup, root\n lda abs:.near v\n rtl\n'
                  ' .section znear, bss\nv: .space 2\n')
        program, found = weighed(source, {('t.s', 0): 0x030000,
                                          ('t.s', 1): 0x028010})
        atom = program.fragments[('t.s', 1)].atom
        self.assertEqual(found.support[atom], 1)
        self.assertEqual([(each[0], each[1].key, each[1].offset)
                          for each in found.single],
                         [(atom, ('t.s', 0), 1)])
        self.assertEqual(evidence.fragment_support(found, ('t.s', 1)), 1)

    def test_bss_with_two_references(self):
        source = (' .section startup, root\n lda abs:.near v\n'
                  ' sta abs:.near v\n rtl\n'
                  ' .section znear, bss\nv: .space 2\n')
        program, found = weighed(source, {('t.s', 0): 0x030000,
                                          ('t.s', 1): 0x028010})
        self.assertEqual(found.support[program.fragments[('t.s', 1)].atom],
                         2)
        self.assertEqual(found.single, [])

    def test_bytes_and_a_reference(self):
        source = (' .section startup, root\n jsr .kbank f\n rtl\n'
                  ' .section code\nf: rts\n')
        program, found = weighed(source, {('t.s', 0): 0x030000,
                                          ('t.s', 1): 0x030100})
        self.assertEqual(evidence.fragment_support(found, ('t.s', 0)), 1)
        self.assertEqual(evidence.fragment_support(found, ('t.s', 1)), 2)
        self.assertEqual(found.single, [])


class SectionOperators(unittest.TestCase):
    def test_block_that_fills_its_memory(self):
        """The extent of the stack comes from the rules file too."""
        source = ' .section stack\n .section startup, root\n' \
                 ' lda long:.sectionEnd stack\n'
        _, found = weighed(source, {('t.s', 1): 0x030000},
                           {STACK_END: 0x3fff})
        self.assertEqual(found.support[STACK_END], 2)
        self.assertEqual(found.single, [])

    def test_section_known_from_the_image_only(self):
        source = ' .section heap\n .section startup, root\n' \
                 ' lda long:.sectionEnd heap\n'
        _, found = weighed(source, {('t.s', 1): 0x030000},
                           {HEAP_END: 0x4fff})
        self.assertEqual(found.support[HEAP_END], 1)
        self.assertEqual([each[0] for each in found.single], [HEAP_END])

    def test_extent_of_placed_fragments(self):
        source = (' .section startup, root\n lda abs:.near v\n'
                  ' lda long:.sectionStart znear\n rtl\n'
                  ' .section znear, bss\nv: .space 2\n')
        start = ('section', 'sectionStart', 'znear')
        _, found = weighed(source, {('t.s', 0): 0x030000,
                                    ('t.s', 1): 0x028010},
                           {start: 0x028010})
        self.assertEqual(found.support[start], 2)


if __name__ == '__main__':
    unittest.main()
