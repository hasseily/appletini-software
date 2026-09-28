"""Tests of tools/v816/expr.py: every operator of the manual's table,
the relocation and section operators, and the address prefixes."""

import unittest

import support  # noqa: F401  (puts tools/ on the path)
from v816 import expr, lexer
from v816.expr import (Binary, Dot, Local, Number, Reloc, SectionOp,
                       Symbol, Unary)


def tree(text, scope=0):
    return expr.parse_all(lexer.tokenize(text), scope)


def environment(**changes):
    settings = dict(
        symbols={'table': 0x123456, 'near_var': 0x021234,
                 'dp_var': 0x000910, 'five': 5, 'here': 0x035000,
                 'there': 0x04c000},
        locals={(7, '1$'): 0x030010},
        sections={'stack': (0x000b00, 0x003fff)},
        dot=0x035100, direct_page_base=0x000900, near_base=0x020000)
    settings.update(changes)
    return expr.Environment(**settings)


def value(text, scope=0, **changes):
    return expr.evaluate(tree(text, scope), environment(**changes))


class UnaryOperators(unittest.TestCase):
    def test_bitwise_not(self):
        self.assertEqual(value('~0'), -1)
        self.assertEqual(value('~0x0f & 0xff'), 0xf0)

    def test_logical_not(self):
        self.assertEqual(value('!0'), 1)
        self.assertEqual(value('!5'), 0)
        self.assertEqual(value('!!5'), 1)

    def test_negate(self):
        self.assertEqual(value('-5'), -5)
        self.assertEqual(value('- -5'), 5)

    def test_plus(self):
        self.assertEqual(value('+5'), 5)


class BinaryOperators(unittest.TestCase):
    def test_multiply(self):
        self.assertEqual(value('6 * 7'), 42)

    def test_divide(self):
        self.assertEqual(value('42 / 5'), 8)
        self.assertEqual(value('-7 / 2'), -3)

    def test_modulo(self):
        self.assertEqual(value('42 % 5'), 2)
        self.assertEqual(value('-7 % 2'), -1)

    def test_division_by_zero(self):
        for text in ('1 / 0', '1 % 0'):
            with self.assertRaises(expr.ExprError):
                value(text)

    def test_add_and_subtract(self):
        self.assertEqual(value('2 + 3'), 5)
        self.assertEqual(value('2 - 3'), -1)

    def test_shifts(self):
        self.assertEqual(value('1 << 16'), 0x10000)
        self.assertEqual(value('0x123456 >> 16'), 0x12)
        self.assertEqual(value('-256 >> 4'), -16)

    def test_negative_shift_count(self):
        with self.assertRaises(expr.ExprError):
            value('1 << -1')

    def test_comparisons(self):
        self.assertEqual([value(text) for text in (
            '2 > 1', '1 > 2', '1 < 2', '2 < 1', '2 >= 2', '1 >= 2',
            '2 <= 2', '2 <= 1')], [1, 0, 1, 0, 1, 0, 1, 0])

    def test_equality(self):
        self.assertEqual([value(text) for text in (
            '2 == 2', '2 == 3', '2 != 3', '2 != 2')], [1, 0, 1, 0])

    def test_bit_operators(self):
        self.assertEqual(value('0b1100 & 0b1010'), 0b1000)
        self.assertEqual(value('0b1100 ^ 0b1010'), 0b0110)
        self.assertEqual(value('0b1100 | 0b1010'), 0b1110)


class Precedence(unittest.TestCase):
    """Each level of the table against the level below it."""

    def test_unary_over_multiply(self):
        self.assertEqual(tree('-2 * 3'),
                         Binary('*', Unary('-', Number(2)), Number(3)))

    def test_multiply_over_add(self):
        self.assertEqual(value('2 + 3 * 4'), 14)
        self.assertEqual(value('2 * 3 + 4'), 10)
        self.assertEqual(value('20 - 12 / 4 % 2'), 19)

    def test_add_over_shift(self):
        self.assertEqual(value('1 << 2 + 1'), 8)
        self.assertEqual(value('16 >> 1 + 1'), 4)

    def test_shift_over_comparison(self):
        self.assertEqual(value('4 < 1 << 3'), 1)
        self.assertEqual(value('1 << 3 >= 8'), 1)

    def test_comparison_over_equality(self):
        self.assertEqual(value('1 == 2 > 1'), 1)
        self.assertEqual(value('0 != 2 <= 1'), 0)

    def test_equality_over_and(self):
        self.assertEqual(value('6 & 2 == 2'), 0)    # 6 & (2 == 2)
        self.assertEqual(value('7 & 2 != 3'), 1)

    def test_and_over_exclusive_or(self):
        self.assertEqual(value('1 ^ 3 & 2'), 3)     # 1 ^ (3 & 2)

    def test_exclusive_or_over_or(self):
        self.assertEqual(value('1 | 3 ^ 1'), 3)     # 1 | (3 ^ 1)
        self.assertEqual(tree('1 | 2 ^ 3 & 4'),
                         Binary('|', Number(1),
                                Binary('^', Number(2),
                                       Binary('&', Number(3), Number(4)))))

    def test_left_to_right_in_one_level(self):
        self.assertEqual(value('10 - 4 - 3'), 3)
        self.assertEqual(value('100 / 10 / 5'), 2)
        self.assertEqual(value('1 << 2 << 3'), 32)

    def test_brackets(self):
        self.assertEqual(value('(2 + 3) * 4'), 20)
        self.assertEqual(value('((1))'), 1)


class Operands(unittest.TestCase):
    def test_symbol(self):
        self.assertEqual(tree('table'), Symbol('table'))
        self.assertEqual(value('table + five'), 0x12345b)

    def test_symbols_are_case_sensitive(self):
        with self.assertRaises(expr.ExprError):
            value('Table')

    def test_local_label_has_the_scope_of_its_place(self):
        self.assertEqual(tree('1$', scope=7), Local('1$', 7))
        self.assertEqual(value('1$ + 1', scope=7), 0x030011)
        with self.assertRaises(expr.ExprError):
            value('1$', scope=8)

    def test_location_counter(self):
        self.assertEqual(tree('.+3'), Binary('+', Dot(), Number(3)))
        self.assertEqual(value('. + 3'), 0x035103)
        self.assertEqual(value('table - .'), 0x123456 - 0x035100)

    def test_location_counter_where_there_is_none(self):
        with self.assertRaises(expr.ExprError):
            value('.', dot=None)


class Relocations(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(value('.byte0 table'), 0x56)
        self.assertEqual(value('.byte1 table'), 0x34)
        self.assertEqual(value('.byte2 table'), 0x12)

    def test_words(self):
        self.assertEqual(value('.word0 table'), 0x3456)
        self.assertEqual(value('.word2 table'), 0x0012)
        self.assertEqual(value('.word2 0x12345678'), 0x1234)

    def test_parts_of_a_negative_value(self):
        self.assertEqual(value('.byte0 -1'), 0xff)
        self.assertEqual(value('.word0 (0 - 2)'), 0xfffe)

    def test_tiny_is_relative_to_the_direct_page(self):
        self.assertEqual(value('.tiny dp_var'), 0x10)
        self.assertEqual(value('.tiny (dp_var + 2)'), 0x12)

    def test_near_is_relative_to_the_near_base(self):
        self.assertEqual(value('.near near_var'), 0x1234)
        self.assertEqual(value('.near (near_var + 2)'), 0x1236)

    def test_kbank_in_the_bank_of_the_instruction(self):
        self.assertEqual(value('.kbank here'), 0x5000)

    def test_kbank_in_another_bank(self):
        with self.assertRaises(expr.ExprError):
            value('.kbank there')

    def test_binds_like_a_unary_operator(self):
        self.assertEqual(tree('.near near_var + 2'),
                         Binary('+', Reloc('near', Symbol('near_var')),
                                Number(2)))
        self.assertEqual(tree('.byte1 (table + 7)'),
                         Reloc('byte1', Binary('+', Symbol('table'),
                                               Number(7))))
        self.assertEqual(tree('.word0 -1'),
                         Reloc('word0', Unary('-', Number(1))))

    def test_nested(self):
        self.assertEqual(value('.byte0 .word2 0x12345678'), 0x34)

    def test_names_are_not_case_sensitive(self):
        self.assertEqual(tree('.NEAR x'), Reloc('near', Symbol('x')))


class SectionOperators(unittest.TestCase):
    def test_values(self):
        self.assertEqual(value('.sectionStart stack'), 0x0b00)
        self.assertEqual(value('.sectionEnd stack'), 0x3fff)
        self.assertEqual(value('.sectionSize stack'), 0x3500)

    def test_size_is_one_plus_end_minus_start(self):
        self.assertEqual(
            value('.sectionSize stack'),
            value('1 + .sectionEnd stack - .sectionStart stack'))

    def test_tree(self):
        self.assertEqual(tree('.sectionStart data_init_table + 4'),
                         Binary('+', SectionOp('sectionStart',
                                               'data_init_table'),
                                Number(4)))
        self.assertEqual(tree('.word0 (.sectionSize stack)'),
                         Reloc('word0', SectionOp('sectionSize', 'stack')))

    def test_unknown_section(self):
        with self.assertRaises(expr.ExprError):
            value('.sectionStart nothing')

    def test_needs_a_name(self):
        with self.assertRaises(expr.ExprError):
            tree('.sectionStart 5')


class Addresses(unittest.TestCase):
    def address(self, text):
        tokens = lexer.tokenize(text)
        prefix, node, position = expr.parse_address(tokens)
        return prefix, node, [token.text for token in tokens[position:]]

    def test_prefixes(self):
        for prefix in expr.PREFIXES:
            self.assertEqual(self.address(prefix + ':10'),
                             (prefix, Number(10), []))

    def test_prefix_in_capitals_and_with_blanks(self):
        self.assertEqual(self.address('DP: .tiny (foo+2)'),
                         ('dp', Reloc('tiny', Binary('+', Symbol('foo'),
                                                     Number(2))), []))

    def test_no_prefix(self):
        self.assertEqual(self.address('foo+1'),
                         (None, Binary('+', Symbol('foo'), Number(1)), []))

    def test_symbol_with_the_name_of_a_prefix(self):
        self.assertEqual(self.address('long + 1'),
                         (None, Binary('+', Symbol('long'), Number(1)),
                          []))

    def test_stops_at_the_register(self):
        self.assertEqual(self.address('long:(WPAGE+W_XS),x'),
                         ('long', Binary('+', Symbol('WPAGE'),
                                         Symbol('W_XS')), [',', 'x']))


class Errors(unittest.TestCase):
    def test_syntax(self):
        for text in ('', '1 +', '(1', '1 2', '* 3', '1 + )', '.byte 1',
                     '"text"', ', 1'):
            with self.assertRaises(expr.ExprError, msg=text):
                tree(text)

    def test_undefined_symbol(self):
        with self.assertRaises(expr.ExprError):
            value('nothing + 1')


class Text(unittest.TestCase):
    def test_text_parses_to_the_same_tree(self):
        for text in ('1 + 2 * 3', '(1 + 2) * 3', '.near (foo + 2)',
                     '.near foo + 2', '-(a << 2) | ~b', '. + 3',
                     '.word0 (.sectionSize stack)', '!a == b', '3$ - 1'):
            first = tree(text, scope=4)
            self.assertEqual(tree(expr.text(first), scope=4), first, text)


class Walk(unittest.TestCase):
    def test_root_first(self):
        nodes = list(expr.walk(tree('.near (a + 1)')))
        self.assertEqual([type(node).__name__ for node in nodes],
                         ['Reloc', 'Binary', 'Symbol', 'Number'])


if __name__ == '__main__':
    unittest.main()
