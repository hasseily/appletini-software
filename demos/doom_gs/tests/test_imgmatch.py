"""Tests of tools/v816/imgmatch.py and linkmap.py: small programs with
images that are equal and images that are not, then upstream's
programs and the release image."""

import contextlib
import io
import json
import unittest

import support
from v816 import (asm816, expr, imgmatch, ir, link, memimage, scm,
                  sections)

RULES = '''
(define memories
  '((memory Near (address (#x020000 . #x027fff)) (section near))
    (memory NearBss (address (#x028000 . #x02ffff)) (section znear))
    (memory Code (address (#x030000 . #x03ffff))
            (section (startup #x030000) code data_init_table))
    (base-address _NearBaseAddress Near 0)
    ))
'''
SOURCE = '''
 .public __data_initialization_needed, LIMIT
LIMIT .equ 10
twice .macro
 asl a
 asl a
 .endm
 .section data_init_table
 .section startup, text, root
start: jsr .kbank work
 lda long:.sectionStart data_init_table
__data_initialization_needed:
 rtl
 .section code
work: lda abs:.near counter
 twice
 sta abs:.near state
 rts
 .section code
unused: .byte 0x77, 0x77
 .section near, data
state: .word 0x1234
 .section znear, bss
counter: .space 2
'''
# Fragments: 0 the equate, 1 data_init_table (empty), 2 startup,
# 3 work, 4 unused, 5 state, 6 counter.
PLACES = {('t.s', 2): 0x030000, ('t.s', 3): 0x030400,
          ('t.s', 5): 0x020010, ('t.s', 6): 0x028000}
TABLE_ADDRESS = 0x030100
TABLE = bytes.fromhex('00800200' '00000000' '0200')


def objects():
    return [support.assemble_clean(SOURCE, 't.s')]


def release_memory(change=None):
    """The image of the program at PLACES with its table; `change`
    gets the bytes of each region to spoil them."""
    program = link.Program(objects(), scm.parse(RULES))
    known = {program.fragments[key].atom: address
             for key, address in PLACES.items()}
    known[('section', 'sectionStart', 'data_init_table')] = TABLE_ADDRESS
    built = link.link(program, PLACES, known).memory
    built.load(TABLE_ADDRESS, TABLE, 'table')
    memory = memimage.MemoryImage()
    for region in built.regions:
        data = bytearray(built.read(region.address, region.length))
        if change:
            change(region.address, data)
        memory.load(region.address, bytes(data))
    return memory


def matched(change=None, extra=None):
    memory = release_memory(change)
    if extra:
        memory.load(*extra)
    return imgmatch.match(objects(), scm.parse(RULES), memory)


class EqualImages(unittest.TestCase):
    def setUp(self):
        self.report, self.map = matched()

    def test_report(self):
        self.assertTrue(imgmatch.clean(self.report))
        self.assertEqual(self.report['total_bytes'], 8 + 9 + 2 + 10)
        self.assertEqual(self.report['mismatch_bytes'], 0)
        self.assertEqual(self.report['mismatches'], [])
        self.assertEqual(self.report['fragments'], {
            'in_the_units': 7, 'part_of_the_program': 4, 'placed': 4,
            'placed_with_every_test_passed': 4, 'made_by_the_linker': 1})

    def test_fragment_that_is_not_part_of_the_program(self):
        self.assertEqual(self.report['not_part_of_the_program'], [
            {'fragment': 't.s#4', 'section': 'code', 'size': 2,
             'file': 't.s', 'line': 19, 'found_at': []}])

    def test_single_evidence(self):
        """The address of counter (bss) rests on the one hole that
        refers to it. Every other number has two things behind it:
        start and work their bytes and a hole, the table its bytes and
        the hole of .sectionStart data_init_table."""
        self.assertEqual(self.report['single_evidence'], [{
            'atom': 'the address of t.s#6', 'value': 0x028000,
            'mask': 0xffffff, 'fragment': 't.s#3', 'offset': 1}])
        support_ = {(entry['unit'], entry['number']): entry['support']
                    for entry in self.map['fragments']}
        self.assertEqual(support_, {
            ('(linker)', 0): 2, ('t.s', 2): 1, ('t.s', 3): 2,
            ('t.s', 5): 2, ('t.s', 6): 1})

    def test_note_on_the_table_of_the_linker(self):
        self.assertEqual(self.report['notes'], [sections.INIT_TABLE_NOTE])

    def test_report_is_json(self):
        json.dumps(self.report)
        json.dumps(self.map)

    def test_map_of_fragments(self):
        by_key = {(entry['unit'], entry['number']): entry
                  for entry in self.map['fragments']}
        self.assertEqual(sorted(by_key), [
            ('(linker)', 0), ('t.s', 2), ('t.s', 3), ('t.s', 5),
            ('t.s', 6)])
        self.assertEqual(by_key[('t.s', 3)], {
            'unit': 't.s', 'number': 3, 'section': 'code', 'kind': 'text',
            'modifiers': [], 'size': 9, 'initialised': True,
            'file': 't.s', 'line': 14, 'address': 0x030400,
            'method': 'reference', 'exact': True, 'support': 2,
            'labels': {'work': 0x030400}})
        self.assertEqual(by_key[('t.s', 6)]['address'], 0x028000)
        self.assertFalse(by_key[('t.s', 6)]['initialised'])
        self.assertEqual(by_key[('(linker)', 0)]['address'], TABLE_ADDRESS)
        self.assertNotIn('method', by_key[('(linker)', 0)])
        self.assertEqual(
            [(entry['unit'], entry['number'], entry['address'])
             for entry in self.map['dropped']],
            [('t.s', 0, None), ('t.s', 1, None), ('t.s', 4, None)])

    def test_map_of_symbols(self):
        self.assertEqual(self.map['units'], {'t.s': {
            'LIMIT': 10, '__data_initialization_needed': 0x030007,
            'counter': 0x028000, 'start': 0x030000, 'state': 0x020010,
            'unused': None, 'work': 0x030400}})
        self.assertEqual(self.map['exported'], {
            'LIMIT': 10, '__data_initialization_needed': 0x030007})
        self.assertEqual(self.map['linker'],
                         {'_NearBaseAddress': 0x020000})
        self.assertEqual(self.map['sections']['znear'],
                         {'first': 0x028000, 'last': 0x028001})
        self.assertEqual(self.map['sections']['data_init_table'],
                         {'first': 0x030100, 'last': 0x030109})


class DifferentImages(unittest.TestCase):
    def test_byte_of_an_instruction(self):
        def change(address, data):
            if address == 0x030400:
                data[4] = 0x4a          # the second asl is an lsr

        report, _ = matched(change)
        self.assertFalse(imgmatch.clean(report))
        self.assertEqual(report['mismatch_bytes'], 1)
        self.assertEqual(report['mismatches'], [{
            'fragment': 't.s#3', 'section': 'code',
            'fragment_address': 0x030400, 'mismatch_bytes': 1,
            'address': 0x030404, 'file': 't.s', 'line': 6,
            'item_offset': 4, 'item_length': 1,
            'macros': [{'macro': 'twice', 'file': 't.s', 'line': 16}],
            'expected': '4a', 'produced': '0a'}])
        self.assertEqual(
            [entry['fragment'] for entry in report['placed_inexactly']],
            ['t.s#3'])

    def test_first_bytes_that_differ_are_reported(self):
        def change(address, data):
            if address == 0x030400:
                data[3] ^= 0xff
                data[8] ^= 0xff

        report, _ = matched(change)
        self.assertEqual(report['mismatch_bytes'], 2)
        self.assertEqual(
            [(entry['address'], entry['line'], entry['mismatch_bytes'],
              entry['expected'], entry['produced'])
             for entry in report['mismatches']],
            [(0x030403, 5, 2, 'f5', '0a')])

    def test_bytes_in_no_fragment(self):
        report, _ = matched(extra=(0x031000, b'\0\0\x07\x08\0\x09\0'))
        self.assertEqual(report['total_bytes'], 29 + 7)
        self.assertEqual(report['mismatch_bytes'], 3)
        self.assertEqual(report['mismatches'], [
            {'fragment': None, 'address': 0x031002, 'mismatch_bytes': 2,
             'expected': '0708', 'produced': None},
            {'fragment': None, 'address': 0x031005, 'mismatch_bytes': 1,
             'expected': '09', 'produced': None}])

    def test_table_of_the_linker(self):
        def change(address, data):
            if address == TABLE_ADDRESS:
                data[8] = 4

        report, _ = matched(change)
        self.assertEqual(report['mismatch_bytes'], 1)
        self.assertEqual(report['mismatches'], [{
            'fragment': '(linker)#0', 'section': 'data_init_table',
            'fragment_address': TABLE_ADDRESS, 'mismatch_bytes': 1,
            'address': TABLE_ADDRESS + 8, 'file': None, 'line': None,
            'item_offset': 8, 'item_length': 2,
            'expected': '0400', 'produced': '0200'}])

    def test_fragment_that_is_not_found(self):
        """The image has other bytes where the fragment f was, and the
        one hole that refers to f holds too little to say where f
        is."""
        source = (' .section startup, root\n lda #.byte0 f\n'
                  ' .section code\nf: .ascii "abc"\n')
        rules = scm.parse(RULES)
        units = [support.assemble_clean(source, 't.s')]
        memory = memimage.MemoryImage()
        memory.load(0x030000, b'\xa9\x10')
        memory.load(0x030410, b'xyz')
        report, _ = imgmatch.match(units, rules, memory)
        self.assertEqual(
            [(entry['fragment'], entry['addresses'])
             for entry in report['unplaced']], [('t.s#1', [])])
        self.assertEqual(report['unsolved_symbols'],
                         ['the address of t.s#1'])
        self.assertEqual(
            [problem['message'] for problem in report['link_problems']],
            ['no value for the address of t.s#1'])
        # the byte of the hole and 3 bytes in no fragment differ; the
        # fragment without address has 3 bytes
        self.assertEqual(report['differing_bytes'], 4)
        self.assertEqual(report['mismatch_bytes'], 7)
        self.assertFalse(imgmatch.clean(report))

    def test_fragment_with_two_places(self):
        source = (' .section startup, root\n .require f\n rtl\n'
                  ' .public f\n .section code\nf: .ascii "abc"\n')
        memory = memimage.MemoryImage()
        memory.load(0x030000, b'\x6b')
        memory.load(0x030410, b'abcabc')
        report, _ = imgmatch.match(
            [support.assemble_clean(source, 't.s')], scm.parse(RULES),
            memory)
        self.assertEqual(
            [(entry['fragment'], entry['addresses'])
             for entry in report['ambiguous']],
            [('t.s#1', [0x030410, 0x030413])])
        self.assertEqual(report['differing_bytes'], 6)
        self.assertEqual(report['mismatch_bytes'], 9)

    def test_table_of_the_linker_not_in_the_image(self):
        """The one hole of crt0 is then all that says where the table
        is."""
        def change(address, data):
            if address == TABLE_ADDRESS:
                data[0] ^= 1

        report, map_ = matched(change)
        self.assertEqual(
            [entry['atom'] for entry in report['single_evidence']],
            ['the address of t.s#6', '.sectionStart data_init_table'])
        self.assertEqual(
            [entry['support'] for entry in map_['fragments']
             if entry['unit'] == '(linker)'], [1])

    def test_bss_fragment_that_nothing_places(self):
        source = (' .section startup, root\n .require buffer\n rtl\n'
                  ' .public buffer\n .section znear, bss\n'
                  'buffer: .space 8\n')
        memory = memimage.MemoryImage()
        memory.load(0x030000, b'\x6b')
        report, _ = imgmatch.match(
            [support.assemble_clean(source, 't.s')], scm.parse(RULES),
            memory)
        self.assertEqual(
            [entry['fragment'] for entry in report['unplaced']], ['t.s#1'])
        self.assertEqual(report['mismatch_bytes'], 0)
        self.assertFalse(imgmatch.clean(report))

    def test_clean_needs_every_fragment_placed(self):
        report, _ = matched()
        self.assertTrue(imgmatch.clean(report))
        report['fragments']['part_of_the_program'] += 1
        self.assertFalse(imgmatch.clean(report))

    def test_built_bytes_outside_the_image(self):
        source = (' .section startup, root\n jsl long:f\n'
                  ' .section code\nf: .space 4\n')
        rules = scm.parse(RULES)
        units = [support.assemble_clean(source, 't.s')]
        program = link.Program(units, rules)
        memory = memimage.MemoryImage()
        memory.load(0x030000, support.linked_at(
            program, {('t.s', 0): 0x030000, ('t.s', 1): 0x030ffe}
        ).memory.read(0x030000, 4))
        memory.load(0x030ffe, b'\0\0')
        report, _ = imgmatch.match(units, rules, memory)
        self.assertEqual(report['differing_bytes'], 0)
        self.assertEqual(report['mismatch_bytes'], 2)

    def test_errors_of_the_assembler(self):
        units = [support.assemble_text(
            ' .section startup, root\n lda nothing\n rtl\n', 't.s')]
        memory = memimage.MemoryImage()
        memory.load(0x030000, b'\x6b')
        report, _ = imgmatch.match(units, scm.parse(RULES), memory)
        self.assertEqual(report['assembler_errors'],
                         ['t.s:2: undefined symbol nothing'])
        self.assertEqual(report['mismatch_bytes'], 0)
        self.assertFalse(imgmatch.clean(report))


class Helpers(unittest.TestCase):
    def test_differing(self):
        expected = memimage.MemoryImage()
        expected.load(0x030000, b'abcdef')
        expected.load(0x04fffe, b'\0\0\0z')
        built = memimage.MemoryImage()
        built.load(0x030002, b'cXe')
        self.assertEqual(
            imgmatch.differing(expected, built),
            [0x030000, 0x030001, 0x030003, 0x030005, 0x050001])

    def test_outside(self):
        expected = memimage.MemoryImage()
        expected.load(0x030000, b'abcd')
        built = memimage.MemoryImage()
        built.load(0x02ffff, b'xabcdyz')
        self.assertEqual(imgmatch.outside(expected, built), 3)


class CommandLine(unittest.TestCase):
    def test_image_that_is_missing(self):
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            status = imgmatch.main(
                ['--image', str(support.BUILD / 'no-such-image.hdv')])
        self.assertEqual(status, 1)
        self.assertIn('is missing', errors.getvalue())


def unconfirmed(unit):
    """The instructions of `unit` whose operand size the release image
    cannot confirm: an address without prefix and without .near or
    .kbank, in an instruction that has more than one size for it
    (rules 3 to 5 of tools/v816/asm816.py)."""
    found = []
    for item in unit.items():
        if (not isinstance(item, ir.Instruction) or item.prefix
                or item.mode in ('', 'a', '#', '##')
                or any(mode.startswith('rel') for mode
                       in asm816.OPCODES[item.mnemonic])):
            continue
        tree = item.operand
        if isinstance(tree, expr.Binary) and isinstance(tree.left,
                                                        expr.Reloc):
            tree = tree.left
        if isinstance(tree, expr.Reloc) and tree.op in ('near', 'kbank'):
            continue
        if len(asm816.address_sizes(item.mnemonic, item.mode)) > 1:
            found.append(item)
    return found


@support.needs_upstream
@support.needs_release
class Release(unittest.TestCase):
    """Upstream's sources against the release image."""

    @classmethod
    def setUpClass(cls):
        cls.report, cls.maps = support.match_results()

    def test_images_are_equal(self):
        self.assertEqual(self.report['mismatch_bytes'], 0)
        self.assertEqual(self.report['total_bytes'], 218112 + 512 + 3072)
        self.assertTrue(self.report['equal'])
        for name, program in self.report['programs'].items():
            self.assertTrue(imgmatch.clean(program), name)
            self.assertEqual(program['mismatches'], [], name)

    def test_image_is_the_pinned_release(self):
        import fetch_upstream
        self.assertEqual(self.report['image_sha256'],
                         fetch_upstream.RELEASE_SHA256)

    def test_numbers_that_rest_on_one_reference(self):
        """Every number is in the report or has a second source. The
        two bss fragments are read from a .near operand each; if
        upstream gains or loses such a fragment, look at it."""
        game = self.report['programs']['game']
        self.assertEqual(
            [entry['atom'] for entry in game['single_evidence']],
            ['the address of r_data65.s#3', 'the address of r_sprite65.s#2'])
        weak = sorted('the address of %s#%d' % (entry['unit'],
                                                entry['number'])
                      for entry in self.maps['game']['fragments']
                      if entry['support'] == 1 and not entry['initialised'])
        self.assertEqual(weak, [entry['atom'] for entry
                                in game['single_evidence']])
        for name in ('boot', 'loader'):
            self.assertEqual(
                self.report['programs'][name]['single_evidence'], [])

    def test_every_fragment_of_the_programs_is_placed(self):
        for name, program in self.report['programs'].items():
            counts = program['fragments']
            self.assertEqual(counts['placed'],
                             counts['part_of_the_program'], name)
            self.assertEqual(counts['placed_with_every_test_passed'],
                             counts['placed'], name)
            self.assertEqual(program['undefined_symbols'], [], name)
        self.assertEqual(
            self.report['programs']['game']['fragments']
            ['made_by_the_linker'], 1)

    def test_fragments_that_are_not_part_of_the_game(self):
        """The linker leaves out what nothing refers to. Their bytes
        are nowhere in the image. (The fragments of the vendor's
        runtime file are left out of the list here; see the README.)"""
        dropped = self.report['programs']['game']['not_part_of_the_program']
        self.assertTrue(all(entry['found_at'] == [] for entry in dropped))
        self.assertEqual(
            [entry['fragment'] for entry in dropped
             if not entry['fragment'].startswith('cal_integer.s#')],
            ['d_main65.s#1', 'm_fixed65.s#7'])
        for name in ('boot', 'loader'):
            self.assertEqual(
                self.report['programs'][name]['not_part_of_the_program'],
                [])

    def test_entry_points(self):
        game = self.maps['game']
        self.assertEqual(game['exported']['__program_start'], 0x030000)
        self.assertEqual(self.maps['boot']['exported']['bootStart'],
                         0x0800)
        self.assertEqual(
            self.maps['loader']['fragments'][0]['address'], 0x6000)

    def test_sections_of_the_game(self):
        sections_ = self.maps['game']['sections']
        self.assertEqual(sections_['stack'],
                         {'first': 0x000b00, 'last': 0x003fff})
        self.assertEqual(sections_['ztiny']['first'], 0x000900)
        self.assertEqual(sections_['znear']['first'], 0x027b00)
        self.assertEqual(sections_['irqcode']['first'], 0x00dd00)
        self.assertEqual(sections_['data_init_table']['first'], 0x050000)

    def test_every_symbol_of_the_program_has_a_value(self):
        game = self.maps['game']
        dropped = {(entry['unit'], label)
                   for entry in game['dropped']
                   for label in self.labels_of(entry)}
        without = {(unit, name) for unit, names in game['units'].items()
                   for name, value in names.items() if value is None}
        self.assertEqual(without, dropped)

    def labels_of(self, entry):
        results = [result for result in support.frontend_results()
                   if result.source.path.name == entry['unit']]
        fragment = results[0].unit.fragments[entry['number']]
        return [item.name for item in fragment.items
                if isinstance(item, ir.Label) and not item.local]

    def test_operand_sizes_that_the_image_cannot_confirm(self):
        """Every address of the sources has a prefix, .near or .kbank,
        or its instruction has one size only. If this fails, upstream
        has an instruction whose size rests on the manual alone."""
        found = [item for result in support.frontend_results()
                 for item in unconfirmed(result.unit)]
        self.assertEqual(
            [(item.where.file, item.where.line) for item in found], [])

    def test_summary(self):
        lines = imgmatch.summary(self.report)
        self.assertEqual(lines[-2:], ['mismatch_bytes 0',
                                      'total_bytes 221696'])
        self.assertEqual(len(lines), 5)


if __name__ == '__main__':
    unittest.main()
