"""Tests of tools/v816/parse.py and of the JSON dump of tools/v816/ir.py:
lines, operands, directives, macros and the scopes of local labels."""

import io
import json
import unittest

import support  # noqa: F401  (puts tools/ on the path)
from v816 import cpp, expr, ir, lexer, parse
from v816.expr import Binary, Dot, Local, Number, Reloc, Symbol


def parse_text(text):
    lines = cpp.Preprocessor().process_text(text, name='t.s')
    return parse.parse_lines(lines, 't.s')


def unit_of(text):
    unit, _ = parse_text(text)
    if unit.errors:
        raise AssertionError('\n'.join(map(str, unit.errors)))
    return unit


def items_of(text):
    return list(unit_of(text).items())


def errors_of(text):
    unit, _ = parse_text(text)
    return [(error.where.line, error.message) for error in unit.errors]


def operand(text, mnemonic='lda'):
    return parse.parse_operand(lexer.tokenize(text), 0, mnemonic)


class Lines(unittest.TestCase):
    def test_label_with_and_without_colon(self):
        items = items_of('one:\ntwo\nthree: nop\nfour  nop\n')
        self.assertEqual(
            [(type(item).__name__, getattr(item, 'name', None)
              or item.mnemonic) for item in items],
            [('Label', 'one'), ('Label', 'two'), ('Label', 'three'),
             ('Instruction', 'nop'), ('Label', 'four'),
             ('Instruction', 'nop')])

    def test_label_after_blanks_needs_its_colon(self):
        items = items_of('  inner: nop\n')
        self.assertEqual(items[0].name, 'inner')
        self.assertEqual(errors_of('  inner nop\n'),
                         [(1, 'unknown instruction or macro "inner"')])

    def test_mnemonics_in_any_case(self):
        items = items_of(' NOP\n Lda #1\n')
        self.assertEqual([item.mnemonic for item in items], ['nop', 'lda'])

    def test_instruction_in_the_label_column_is_an_error(self):
        self.assertEqual(len(errors_of('nop\n')), 1)
        self.assertEqual(len(errors_of('lda #1\n')), 1)

    def test_where(self):
        items = items_of('\n\n nop ; comment\n')
        self.assertEqual(items[0].where, ir.Where('t.s', 3))

    def test_unknown_mnemonic(self):
        self.assertEqual(errors_of(' nop\n mov a, b\n nop\n'),
                         [(2, 'unknown instruction or macro "mov"')])

    def test_unknown_directive(self):
        self.assertEqual(errors_of(' .org 0x1000\n'),
                         [(1, 'unknown directive .org')])

    def test_errors_do_not_stop_the_parser(self):
        unit, _ = parse_text(' bad1\n nop\n .bad2\n lda (\n')
        self.assertEqual(len(unit.errors), 3)
        self.assertEqual(len(list(unit.items())), 1)

    def test_end_stops_the_parser(self):
        items = items_of(' nop\n .end\n this is not read\n')
        self.assertEqual(len(items), 1)


class OperandSyntax(unittest.TestCase):
    def test_none(self):
        self.assertEqual(operand('', 'rts'), ('', None, None))

    def test_accumulator(self):
        for mnemonic in ('asl', 'lsr', 'rol', 'ror', 'inc', 'dec'):
            self.assertEqual(operand('a', mnemonic), ('a', None, None))
            self.assertEqual(operand('A', mnemonic), ('a', None, None))

    def test_a_is_a_symbol_for_other_instructions(self):
        self.assertEqual(operand('a', 'lda'), ('e', None, Symbol('a')))

    def test_immediates(self):
        self.assertEqual(operand('#0x20'), ('#', None, Number(0x20)))
        self.assertEqual(operand('##0x1234'), ('##', None, Number(0x1234)))
        self.assertEqual(operand('#.byte2 x'),
                         ('#', None, Reloc('byte2', Symbol('x'))))
        self.assertEqual(operand('#(N + 1)'),
                         ('#', None, Binary('+', Symbol('N'), Number(1))))

    def test_address(self):
        self.assertEqual(operand('10'), ('e', None, Number(10)))
        self.assertEqual(operand('dp:W_X2'), ('e', 'dp', Symbol('W_X2')))
        self.assertEqual(operand('abs:10'), ('e', 'abs', Number(10)))
        self.assertEqual(operand('long:x'), ('e', 'long', Symbol('x')))
        self.assertEqual(operand('.near rw_stopx'),
                         ('e', None, Reloc('near', Symbol('rw_stopx'))))
        self.assertEqual(operand('.kbank genColumn', 'jsr'),
                         ('e', None, Reloc('kbank', Symbol('genColumn'))))

    def test_indexed(self):
        self.assertEqual(operand('10,x'), ('e,x', None, Number(10)))
        self.assertEqual(operand('abs:R_END,y'),
                         ('e,y', 'abs', Symbol('R_END')))
        self.assertEqual(operand('3,s'), ('e,s', None, Number(3)))
        self.assertEqual(operand('long:ssUp3 , X'),
                         ('e,x', 'long', Symbol('ssUp3')))

    def test_indirect(self):
        self.assertEqual(operand('(STRPTR)'),
                         ('(e)', None, Symbol('STRPTR')))
        self.assertEqual(operand('(.tiny DEST)'),
                         ('(e)', None, Reloc('tiny', Symbol('DEST'))))
        self.assertEqual(operand('(abs:vector)', 'jmp'),
                         ('(e)', 'abs', Symbol('vector')))
        self.assertEqual(operand('(table,x)', 'jsr'),
                         ('(e,x)', None, Symbol('table')))
        self.assertEqual(operand('(ptr),y'),
                         ('(e),y', None, Symbol('ptr')))
        self.assertEqual(operand('(3,s),y'), ('(e,s),y', None, Number(3)))

    def test_indirect_long(self):
        self.assertEqual(operand('[.tiny (_Dp+8)],y'),
                         ('[e],y', None,
                          Reloc('tiny', Binary('+', Symbol('_Dp'),
                                               Number(8)))))
        self.assertEqual(operand('[dp:ptr]'), ('[e]', 'dp', Symbol('ptr')))

    def test_bracket_that_belongs_to_the_expression(self):
        self.assertEqual(operand('(table+2),x'),
                         ('e,x', None, Binary('+', Symbol('table'),
                                              Number(2))))
        self.assertEqual(operand('(a+1)*2'),
                         ('e', None, Binary('*', Binary('+', Symbol('a'),
                                                        Number(1)),
                                            Number(2))))
        self.assertEqual(operand('(a)+(b)'),
                         ('e', None, Binary('+', Symbol('a'), Symbol('b'))))
        self.assertEqual(operand('long:(WPAGE+W_XS)'),
                         ('e', 'long', Binary('+', Symbol('WPAGE'),
                                              Symbol('W_XS'))))

    def test_branch_to_the_location_counter(self):
        self.assertEqual(operand('.+3', 'bpl'),
                         ('e', None, Binary('+', Dot(), Number(3))))

    def test_all_modes_are_known_to_the_ir(self):
        texts = ('', 'a', '#1', '##1', 'x', 'x,x', 'x,y', '1,s', '(x)',
                 '(x,x)', '(x),y', '(1,s),y', '[x]', '[x],y')
        modes = [operand(text, 'asl')[0] for text in texts]
        self.assertEqual(sorted(modes), sorted(ir.MODES))

    def test_errors(self):
        for text in ('(x', '[x', '[x],x', '[x,x]', '(x,y)', '(x,s)',
                     'x,z', 'x,', '#', '(x),y,x', 'x y', '1,2',
                     '(x,s),x'):
            with self.assertRaises((parse.ParseError, expr.ExprError),
                                   msg=text):
                operand(text)


class Equates(unittest.TestCase):
    def test_value(self):
        item, = items_of('BufSize: .equ 2 + Size\n')
        self.assertEqual((item.name, item.value, item.position,
                          item.location),
                         ('BufSize', Binary('+', Number(2), Symbol('Size')),
                          False, False))

    def test_without_colon(self):
        item, = items_of('BufNo .equ 7\n')
        self.assertEqual((item.name, item.value), ('BufNo', Number(7)))

    def test_code_position(self):
        items = items_of(' nop\nc17Return .equ .\n .byte 0x60\n'
                         'next .equ . + 2\n')
        self.assertEqual([type(item).__name__ for item in items],
                         ['Instruction', 'Equate', 'Data', 'Equate'])
        self.assertEqual(items[1].value, Dot())
        self.assertTrue(items[1].position)
        self.assertTrue(items[3].position)

    def test_equlab(self):
        item, = items_of('MyLocation: .equlab 0xD7\n')
        self.assertTrue(item.location)

    def test_needs_a_name(self):
        self.assertEqual(len(errors_of('  .equ 5\n')), 1)
        self.assertEqual(len(errors_of('1$ .equ 5\n')), 1)


class Directives(unittest.TestCase):
    def test_numeric_data(self):
        items = items_of(' .byte 1, 2+3, .byte1 (x+7)\n .word x\n'
                         ' .address x\n .long 0, -1\n .quad 1\n')
        self.assertEqual([item.directive for item in items],
                         ['byte', 'word', 'address', 'long', 'quad'])
        self.assertEqual(items[0].values,
                         [Number(1), Binary('+', Number(2), Number(3)),
                          Reloc('byte1', Binary('+', Symbol('x'),
                                                Number(7)))])
        self.assertEqual(len(items[3].values), 2)

    def test_strings(self):
        items = items_of(' .ascii "and clean\\n"\n'
                         ' .asciz "STTNUM0", "STYSNUM0"\n')
        self.assertEqual(items[0].values, [b'and clean\n'])
        self.assertEqual(items[1].directive, 'asciz')
        self.assertEqual(items[1].values, [b'STTNUM0', b'STYSNUM0'])

    def test_strings_need_strings(self):
        self.assertEqual(len(errors_of(' .ascii 65\n')), 1)
        self.assertEqual(len(errors_of(' .byte "A"\n')), 1)

    def test_space_fillto_align(self):
        items = items_of(' .space 7\n .space N*2, 0xff\n .fillto 0x100\n'
                         ' .fillto 0x200, 0xea\n .align 4\n')
        self.assertEqual([type(item).__name__ for item in items],
                         ['Space', 'Space', 'FillTo', 'FillTo', 'Align'])
        self.assertEqual((items[0].count, items[0].fill),
                         (Number(7), None))
        self.assertEqual(items[1].fill, Number(0xff))
        self.assertEqual((items[3].offset, items[3].fill),
                         (Number(0x200), Number(0xea)))
        self.assertEqual(items[4].alignment, Number(4))

    def test_incbin(self):
        item, = items_of(' .incbin "rawdata.bin"\n')
        self.assertEqual(item.path, 'rawdata.bin')

    def test_declarations(self):
        unit = unit_of(' .public a, b\n .extern c\n .require d\n'
                       ' .global e\n .globl f\n .pubweak g\n')
        self.assertEqual(
            [(item.directive, item.name) for item in unit.declarations],
            [('public', 'a'), ('public', 'b'), ('extern', 'c'),
             ('require', 'd'), ('global', 'e'), ('globl', 'f'),
             ('pubweak', 'g')])
        self.assertEqual(unit.declarations[2].where.line, 2)

    def test_rtmodel(self):
        unit = unit_of(' .rtmodel version, "1"\n .rtmodel cpu, "*"\n')
        self.assertEqual([(item.name, item.value)
                          for item in unit.rtmodels],
                         [('version', '1'), ('cpu', '*')])

    def test_argdelim_is_not_implemented(self):
        self.assertEqual(errors_of(' .argdelim <>\n'),
                         [(1, 'unknown directive .argdelim')])


class Sections(unittest.TestCase):
    def test_fragments_in_order(self):
        unit = unit_of(' .section znear, bss\nv: .space 2\n'
                       ' .section farcode, text\nf: rtl\n'
                       ' .section znear, bss\nw: .space 2\n')
        self.assertEqual(
            [(fragment.section, fragment.kind, len(fragment.items))
             for fragment in unit.fragments],
            [('znear', 'bss', 2), ('farcode', 'text', 2),
             ('znear', 'bss', 2)])
        self.assertEqual(unit.fragments[1].where.line, 3)

    def test_kind_and_modifiers(self):
        unit = unit_of(' .section startup, text, root, noreorder\n'
                       ' .section registers, noinit\n'
                       ' .section stack\n .section Table, RODATA, NoRoot\n')
        self.assertEqual(
            [(fragment.section, fragment.kind, fragment.modifiers)
             for fragment in unit.fragments],
            [('startup', 'text', ('root', 'noreorder')),
             ('registers', None, ('noinit',)), ('stack', None, ()),
             ('Table', 'rodata', ('noroot',))])

    def test_source_starts_in_the_section_code(self):
        unit = unit_of(' nop\n .section farcode\n rtl\n')
        self.assertEqual([(fragment.section, fragment.where is None)
                          for fragment in unit.fragments],
                         [('code', True), ('farcode', False)])

    def test_unused_first_fragment_is_dropped(self):
        unit = unit_of('; comment\n .section farcode\n rtl\n')
        self.assertEqual([fragment.section for fragment in unit.fragments],
                         ['farcode'])

    def test_errors(self):
        self.assertEqual(len(errors_of(' .section\n')), 1)
        self.assertEqual(len(errors_of(' .section a, wrong\n')), 1)
        self.assertEqual(len(errors_of(' .section a, text, data\n')), 1)


def scopes(items):
    """For each label, and for each instruction that refers to a local
    label: (name or mnemonic, scope)."""
    found = []
    for item in items:
        if isinstance(item, ir.Label):
            found.append((item.name, item.scope))
        elif isinstance(item, ir.Instruction) and item.operand is not None:
            found += [(item.mnemonic, node.scope)
                      for node in expr.walk(item.operand)
                      if isinstance(node, Local)]
    return found


class LocalLabels(unittest.TestCase):
    def test_label_starts_a_scope(self):
        found = scopes(items_of(
            'first:\n1$: dex\n bne 1$\nsecond:\n1$: dey\n bne 1$\n'))
        first, second = found[1][1], found[4][1]
        self.assertNotEqual(first, second)
        self.assertEqual(found, [('first', None), ('1$', first),
                                 ('bne', first), ('second', None),
                                 ('1$', second), ('bne', second)])

    def test_forward_reference(self):
        found = scopes(items_of('f:\n beq 15$\n iny\n15$: rts\n'))
        self.assertEqual(found[1][1], found[2][1])

    def test_names_with_letters(self):
        self.assertEqual(errors_of('f:\nloop$: dex\n bne loop$\n'), [])

    def test_label_is_not_visible_after_the_next_label(self):
        self.assertEqual(
            errors_of('f:\nloop$: dex\nfoo: ldx #5\n bne loop$\n'),
            [(4, 'local label loop$ is not defined in its scope')])

    def test_label_is_not_visible_before_the_label_above_it(self):
        self.assertEqual(
            errors_of('f:\n bne 1$\ng:\n1$: rts\n'),
            [(2, 'local label 1$ is not defined in its scope')])

    def test_same_name_twice_in_a_scope(self):
        found = errors_of('f:\n1$: nop\n1$: nop\n')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 3)
        self.assertIn('defined twice', found[0][1])

    def test_scope_before_the_first_label(self):
        self.assertEqual(errors_of('1$: dex\n bne 1$\n'), [])

    def test_equate_does_not_start_a_scope(self):
        unit, counts = parse_text(
            'f:\n1$: dex\nhere .equ .\nN .equ 5\n bne 1$\n')
        self.assertEqual(unit.errors, [])
        self.assertEqual(counts['across_equates'], 1)

    def test_reference_that_crosses_no_equate(self):
        _, counts = parse_text('N .equ 5\nf:\n1$: dex\n bne 1$\n')
        self.assertEqual(counts['across_equates'], 0)

    def test_section_does_not_start_a_scope(self):
        self.assertEqual(
            errors_of('f:\n bne 1$\n .section other\n1$: rts\n'), [])

    def test_local_labels_in_data(self):
        self.assertEqual(errors_of('t:\n .word 1$, 2$-1$\n1$: nop\n'
                                   '2$: nop\n'), [])
        self.assertEqual(len(errors_of('t:\n .word 1$\nu:\n1$: nop\n')), 1)

    def test_scope_count(self):
        _, counts = parse_text('a:\nb:\nc:\n')
        self.assertEqual(counts['scopes'], 4)


WAITREG = ('waitreg .macro reg\n'
           '1$: de\\reg\n'
           ' bne 1$\n'
           ' .endm\n')


class Macros(unittest.TestCase):
    def test_manual_example(self):
        items = items_of(WAITREG + ' ldx #100\n waitreg x\n1$: lda #0\n')
        self.assertEqual(
            [(type(item).__name__, getattr(item, 'mnemonic', None)
              or item.name) for item in items],
            [('Instruction', 'ldx'), ('Label', '1$'),
             ('Instruction', 'dex'), ('Instruction', 'bne'),
             ('Label', '1$'), ('Instruction', 'lda')])

    def test_expansion_has_its_own_scope(self):
        found = scopes(items_of(
            WAITREG + 'f:\n1$: nop\n waitreg x\n waitreg y\n bne 1$\n'))
        outer = found[1][1]
        first, second = found[2][1], found[4][1]
        self.assertEqual(len({outer, first, second}), 3)
        self.assertEqual(found, [
            ('f', None), ('1$', outer), ('1$', first), ('bne', first),
            ('1$', second), ('bne', second), ('bne', outer)])

    def test_scope_of_the_use_is_back_after_a_label_in_the_macro(self):
        text = ('entry .macro name\n\\name:\n1$: nop\n bra 1$\n .endm\n'
                'f:\n1$: nop\n entry g\n bra 1$\n')
        found = scopes(items_of(text))
        self.assertEqual(found[1], ('1$', found[-1][1]))
        self.assertEqual(found[2], ('g', None))
        self.assertNotEqual(found[3][1], found[1][1])

    def test_macro_cannot_see_the_labels_of_its_use(self):
        text = 'jump .macro\n bra 1$\n .endm\nf:\n1$: nop\n jump\n'
        self.assertEqual(
            errors_of(text),
            [(2, 'local label 1$ is not defined in its scope')])

    def test_nested_expansions(self):
        text = ('inner .macro reg\n1$: de\\reg\n bne 1$\n .endm\n'
                'outer .macro a, b\n1$: inner \\a\n inner \\b\n'
                ' bra 1$\n .endm\n'
                'f:\n outer x, y\n')
        items = items_of(text)
        found = scopes(items)
        outer = found[1][1]
        self.assertEqual(found[-1], ('bra', outer))
        self.assertEqual(len({scope for _, scope in found[1:]}), 3)
        dex = items[3]
        self.assertEqual(dex.mnemonic, 'dex')
        self.assertEqual(dex.where, ir.Where('t.s', 2, (
            ir.Expansion('outer', 't.s', 11),
            ir.Expansion('inner', 't.s', 6))))

    def test_where_of_an_expanded_line(self):
        items = items_of(WAITREG + '\n waitreg x\n')
        self.assertEqual(items[1].where, ir.Where(
            't.s', 2, (ir.Expansion('waitreg', 't.s', 6),)))

    def test_use_after_a_label(self):
        items = items_of(WAITREG + 'f: waitreg x\n')
        self.assertEqual([type(item).__name__ for item in items],
                         ['Label', 'Label', 'Instruction', 'Instruction'])

    def test_operands_as_arguments(self):
        text = ('FSCUT .macro first, end\n lda \\end\n cmp \\first\n'
                ' .endm\n FSCUT dp: .tiny (x+1), ##12\n')
        items = items_of(text)
        self.assertEqual((items[0].mode, items[0].operand),
                         ('##', Number(12)))
        self.assertEqual((items[1].mode, items[1].prefix),
                         ('e', 'dp'))

    def test_macro_without_parameters(self):
        items = items_of('return .macro\n rtl\n .endm\nf: return\n')
        self.assertEqual(items[1].mnemonic, 'rtl')

    def test_names_are_case_sensitive(self):
        self.assertEqual(len(errors_of(WAITREG + ' WAITREG x\n')), 1)

    def test_macro_info(self):
        unit = unit_of(WAITREG)
        self.assertEqual(unit.macros, [ir.MacroInfo(
            'waitreg', ('reg',), 2, ir.Where('t.s', 1))])

    def test_counts(self):
        text = ('wait .macro n\n ldx #\\n\n1$: dex\n bne 1$\n .endm\n'
                ' wait 1\n wait 2\n nop\n')
        unit, counts = parse_text(text)
        self.assertEqual(counts['expansions'], {'wait': 2})
        # three lines of the body and the nop
        self.assertEqual(counts['source_instructions'], 4)
        self.assertEqual(sum(isinstance(item, ir.Instruction)
                             for item in unit.items()), 7)

    def test_mnemonic_made_from_an_argument_is_not_counted(self):
        _, counts = parse_text(WAITREG + ' waitreg x\n')
        self.assertEqual(counts['source_instructions'], 1)

    def test_body_is_not_parsed_before_its_use(self):
        self.assertEqual(
            errors_of('m .macro\n wrong\n .endm\n nop\n'), [])
        self.assertEqual(
            errors_of('m .macro\n wrong\n .endm\n m\n'),
            [(2, 'unknown instruction or macro "wrong"')])

    def test_error_names_the_use(self):
        unit, _ = parse_text('m .macro\n wrong\n .endm\n\n m\n')
        self.assertIn('in macro m used at t.s:5', str(unit.errors[0]))

    def test_definition_errors(self):
        self.assertEqual(len(errors_of('m .macro\n nop\n')), 1)
        self.assertEqual(len(errors_of(' .endm\n')), 1)
        self.assertEqual(len(errors_of(' .macro\n .endm\n')), 2)
        self.assertEqual(len(errors_of(
            'm .macro\n .endm\nm .macro\n .endm\n')), 1)
        self.assertEqual(len(errors_of('m .macro 1\n .endm\n')), 1)
        self.assertEqual(len(errors_of('nop .macro\n .endm\n')), 1)
        self.assertEqual(len(errors_of('1$ .macro\n .endm\n')), 1)
        self.assertEqual(
            errors_of('m .macro\nn .macro\n .endm\n')[0],
            (2, '.macro inside the macro m'))

    def test_wrong_number_of_arguments(self):
        self.assertEqual(len(errors_of(WAITREG + ' waitreg\n')), 1)
        self.assertEqual(len(errors_of(WAITREG + ' waitreg x, y\n')), 1)

    def test_macro_that_uses_itself(self):
        found = errors_of('m .macro\n m\n .endm\n m\n')
        self.assertEqual(len(found), 1)
        self.assertIn('nested too deeply', found[0][1])

    def test_label_with_the_name_of_a_macro(self):
        self.assertEqual(len(errors_of(WAITREG + 'waitreg: nop\n')), 1)


class WithThePreprocessor(unittest.TestCase):
    def test_labels_made_by_paste(self):
        text = ('#define CAT2(a, b) a ## b\n#define CAT(a, b) CAT2(a, b)\n'
                '#define L(x) CAT(V_NAME, x)\n#define V_NAME v04\n'
                'L(slow):      rep     #0x20\n'
                'L(c17slow)    .equ    .\n'
                '              lda     ##L(slow)\n')
        items = items_of(text)
        self.assertEqual(items[0].name, 'v04slow')
        self.assertEqual(items[1].mode, '#')
        self.assertEqual((items[2].name, items[2].position),
                         ('v04c17slow', True))
        self.assertEqual((items[3].mode, items[3].operand),
                         ('##', Symbol('v04slow')))

    def test_comment_from_a_define_body(self):
        items = items_of('#define V_CC1R W_YL   ; no top wall\n'
                         ' lda dp:V_CC1R\n')
        self.assertEqual((items[0].prefix, items[0].operand),
                         ('dp', Symbol('W_YL')))


class Json(unittest.TestCase):
    def test_dump(self):
        unit = unit_of(WAITREG + ' .section farcode, text\n .public f\n'
                       'f: waitreg x\n .asciz "A"\n .word 1$ + .\n'
                       '1$: .space 2\nN .equ .near (f + 1)\n')
        stream = io.StringIO()
        ir.dump_json(unit, stream)
        plain = json.loads(stream.getvalue())
        self.assertEqual(plain['type'], 'Unit')
        self.assertEqual(plain['path'], 't.s')
        self.assertEqual(plain['declarations'][0]['name'], 'f')
        self.assertEqual(plain['macros'][0]['parameters'], ['reg'])
        fragment, = plain['fragments']
        self.assertEqual((fragment['section'], fragment['kind']),
                         ('farcode', 'text'))
        items = fragment['items']
        self.assertEqual([item['type'] for item in items],
                         ['Label', 'Label', 'Instruction', 'Instruction',
                          'Data', 'Data', 'Label', 'Space', 'Equate'])
        self.assertEqual(items[2]['mnemonic'], 'dex')
        self.assertEqual(items[2]['where']['expansions'],
                         [{'type': 'Expansion', 'macro': 'waitreg',
                           'file': 't.s', 'line': 7}])
        self.assertEqual(items[4]['values'],
                         [{'type': 'bytes', 'hex': '41'}])
        self.assertEqual(items[5]['values'][0]['left']['type'], 'Local')
        self.assertEqual(items[5]['values'][0]['right'], {'type': 'Dot'})
        self.assertEqual(items[8]['value'],
                         {'type': 'Reloc', 'op': 'near', 'operand': {
                             'type': 'Binary', 'op': '+',
                             'left': {'type': 'Symbol', 'name': 'f'},
                             'right': {'type': 'Number', 'value': 1}}})


if __name__ == '__main__':
    unittest.main()
