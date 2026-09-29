"""Tests of tools/v816/sections.py: section extents and
data_init_table."""

import unittest

import support
from v816 import place, sections

RULES = '''
(define memories
  '((memory DirectPage (address (#x000900 . #x0009ff))
            (section registers ztiny))
    (memory Stack (address (#x000b00 . #x003fff)) (section stack))
    (memory Heap (address (#x004000 . #x007fff)) (section heap))
    (memory NearBss (address (#x028000 . #x02ffff)) (section znear))
    (memory Code (address (#x030000 . #x03ffff))
            (section (startup #x030000) code data_init_table))
    (block stack (size #x3500))
    (block heap (size #x1000))
    (base-address _DirectPageStart DirectPage 0)
    (base-address _NearBaseAddress NearBss 0)
    ))
'''

STARTUP = '''
 .section stack
 .section data_init_table
 .public __data_initialization_needed
 .section registers, noinit
regs: .space 20
 .section startup, text, root, noreorder
 ldx ##.sectionEnd stack
 lda dp:.tiny regs
 .section startup, text, noroot, noreorder
__data_initialization_needed:
 cpx ##.word0 (.sectionSize data_init_table)
 lda long:(.sectionStart data_init_table),x
 .section startup, text, root, noreorder
 lda abs:.near v1
 lda abs:.near v2
 lda dp:.tiny z
 jsr .kbank code1
 jsr .kbank code2
 rtl
 .section code
code1: rts
 nop
 .section code
code2: rts
 .section znear, bss
v1: .space 0x10
 .section znear, bss
v2: .space 0x20
 .section ztiny, bss
z: .space 4
'''
# Fragments: 0 stack and 1 data_init_table (empty), 2 registers, 3 to
# 5 startup, 6 and 7 code, 8 and 9 znear, 10 ztiny.
PLACES = {
    ('s.s', 2): 0x000930, ('s.s', 3): 0x030000, ('s.s', 4): 0x030005,
    ('s.s', 5): 0x03000c, ('s.s', 6): 0x030200, ('s.s', 7): 0x030100,
    ('s.s', 8): 0x028100, ('s.s', 9): 0x028040, ('s.s', 10): 0x000904}
TABLE_ADDRESS = 0x030300
TABLE = ('40800200' '00000000' 'd000'       # znear $028040, $D0 bytes
         '04090000' '00000000' '0400')      # ztiny $000904, 4 bytes


def release(program):
    """The image that the vendor's linker would make: the fragments at
    PLACES, the table at TABLE_ADDRESS."""
    known = {program.fragments[key].atom: address
             for key, address in PLACES.items()}
    known.update({
        ('section', 'sectionEnd', 'stack'): 0x3fff,
        ('section', 'sectionSize', 'data_init_table'): 20,
        ('section', 'sectionStart', 'data_init_table'): TABLE_ADDRESS})
    from v816 import link
    memory = link.link(program, PLACES, known).memory
    memory.load(TABLE_ADDRESS, bytes.fromhex(TABLE), 'table')
    return memory


class Finish(unittest.TestCase):
    def setUp(self):
        self.program = support.program_of({'s.s': STARTUP}, RULES)
        self.memory = release(self.program)
        self.layout = place.recover(self.program, self.memory)
        self.finished = sections.finish(self.program, self.layout)

    def test_layout(self):
        self.assertEqual(self.layout.addresses(), PLACES)

    def test_no_problems(self):
        self.assertEqual(self.finished.problems, [])

    def test_table(self):
        self.assertEqual(
            sections.init_table(self.program, PLACES).hex(), TABLE)
        self.assertEqual(self.finished.addresses[sections.INIT_TABLE_KEY],
                         TABLE_ADDRESS)
        table = self.program.fragments[sections.INIT_TABLE_KEY]
        self.assertEqual(table.data.hex(), TABLE)
        self.assertEqual(table.section, 'data_init_table')

    def test_extents(self):
        self.assertEqual(self.finished.extents, {
            'stack': (0x000b00, 0x003fff),
            'registers': (0x000930, 0x000943),
            'startup': (0x030000, 0x03001a),
            'code': (0x030100, 0x030201),
            'znear': (0x028040, 0x02810f),
            'ztiny': (0x000904, 0x000907),
            'data_init_table': (TABLE_ADDRESS, TABLE_ADDRESS + 19)})

    def test_section_operators(self):
        known = self.finished.known
        self.assertEqual(known[('section', 'sectionEnd', 'stack')], 0x3fff)
        self.assertEqual(
            known[('section', 'sectionSize', 'data_init_table')], 20)
        self.assertEqual(known[('section', 'sectionSize', 'znear')], 0xd0)
        self.assertEqual(known[('section', 'sectionStart', 'code')],
                         0x030100)

    def test_block_that_does_not_fill_its_memory(self):
        self.assertNotIn('heap', self.finished.extents)


class Problems(unittest.TestCase):
    def finished(self, change):
        program = support.program_of({'s.s': STARTUP}, RULES)
        memory = release(program)
        data = bytearray(memory.read(0x030000, 0x1b))
        change(data)
        memory.load(0x030000, bytes(data), 'changed')
        return sections.finish(program, place.recover(program, memory))

    def messages(self, change):
        return [(problem.message, problem.key, problem.offset)
                for problem in self.finished(change).problems]

    def test_size_of_the_table_in_the_image_differs(self):
        def change(data):
            data[6] = 30            # cpx ##.word0 (.sectionSize ...)

        self.assertEqual(self.messages(change), [
            ('the image has $1E in the bits $FFFF of .sectionSize '
             'data_init_table', ('s.s', 4), 1)])

    def test_end_of_the_stack_in_the_image_differs(self):
        def change(data):
            data[1] = 0xfe          # ldx ##.sectionEnd stack

        self.assertEqual(self.messages(change), [
            ('the image has $3FFE in the bits $FFFF of .sectionEnd stack',
             ('s.s', 3), 1)])


class PartlyKnown(unittest.TestCase):
    SOURCE = (' .section heap\n .section startup, root\n'
              ' ldx ##.sectionEnd heap\n')

    def test_only_the_low_bits_of_a_section_without_fragments(self):
        program = support.program_of({'s.s': self.SOURCE}, RULES)
        atom = ('section', 'sectionEnd', 'heap')
        from v816 import link
        memory = link.link(program, {('s.s', 1): 0x030000},
                           {('fragment', 's.s', 1): 0x030000,
                            atom: 0x4fff}).memory
        finished = sections.finish(program,
                                   place.recover(program, memory))
        self.assertEqual(finished.known[atom], 0x4fff)
        self.assertEqual(
            [problem.message for problem in finished.problems],
            ['the image gives only the low 16 bits of .sectionEnd heap'])


class FixedAddress(unittest.TestCase):
    RULES = '''
(define memories
  '((memory Code (address (#x030000 . #x03ffff))
            (section (startup #x030000)))
    ))
'''
    SOURCE = (' .section startup, root\n .byte 1, 2, 3, 4\n'
              ' .section startup, root\n .byte 5, 6, 7, 8\n')

    def problems(self, first):
        program = support.program_of({'s.s': self.SOURCE}, self.RULES)
        places = {('s.s', 0): first, ('s.s', 1): first + 4}
        memory = support.linked_at(program, places).memory
        layout = place.recover(program, memory)
        self.assertEqual(layout.addresses(), places)
        return [problem.message
                for problem in sections.finish(program, layout).problems]

    def test_section_that_starts_at_its_address(self):
        self.assertEqual(self.problems(0x030000), [])

    def test_section_that_starts_elsewhere(self):
        """With two fragments the rules let each go anywhere in the
        memory (place.py); the section must still start at $030000."""
        self.assertEqual(self.problems(0x030100), [
            'the section startup starts at $030100, its fixed address '
            'is $030000'])


@support.needs_upstream
@support.needs_release
class ReleaseTable(unittest.TestCase):
    """What init_table() assumes of data_init_table, against the one
    image it was read from. If an upstream links initialised data that
    the startup code copies, or the linker orders the table otherwise,
    this fails before the image comparison says why."""

    def test_entries_clear_the_bss_sections_in_the_order_of_names(self):
        game = support.match_results()[1]['game']
        extent = game['sections'][sections.INIT_TABLE]
        memory = support.release_targets()[0].memory
        data = memory.read(extent['first'],
                           1 + extent['last'] - extent['first'])
        size = sections.INIT_ENTRY.size
        self.assertEqual(len(data) % size, 0)
        entries = [sections.INIT_ENTRY.unpack_from(data, offset)
                   for offset in range(0, len(data), size)]
        self.assertEqual([entry for entry in entries if entry[1] != 0], [],
                         'entries that copy data')
        cleared = sorted({
            entry['section'] for entry in game['fragments']
            if entry['kind'] == 'bss' and 'noinit' not in entry['modifiers']
            and entry['size']})
        self.assertEqual(
            [(start, size) for start, _, size in entries],
            [(game['sections'][name]['first'],
              1 + game['sections'][name]['last']
              - game['sections'][name]['first']) for name in cleared])


class NoTable(unittest.TestCase):
    def test_program_without_sections_to_clear(self):
        program = support.program_of(
            {'s.s': ' .section startup, root\n rtl\n'}, RULES)
        memory = support.linked_at(program, {('s.s', 0): 0x030000}).memory
        finished = sections.finish(program,
                                   place.recover(program, memory))
        self.assertEqual(finished.problems, [])
        self.assertNotIn(sections.INIT_TABLE_KEY, program.fragments)

    def test_table_without_address(self):
        source = (' .section startup, root\n lda abs:.near v\n'
                  ' .section znear, bss\nv: .space 2\n')
        program = support.program_of({'s.s': source}, RULES)
        places = {('s.s', 0): 0x030000, ('s.s', 1): 0x028000}
        memory = support.linked_at(program, places).memory
        finished = sections.finish(program,
                                   place.recover(program, memory))
        self.assertEqual(
            [problem.message for problem in finished.problems],
            ['data_init_table has 10 bytes and no address'])


if __name__ == '__main__':
    unittest.main()
