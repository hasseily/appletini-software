"""Tests of tools/v816/linear.py: values that depend on the placement."""

import unittest

import support  # noqa: F401  (puts tools/ on the path)
from v816 import expr, lexer, linear
from v816.linear import Linear, Value

A = ('fragment', 'a.s', 0)
B = ('fragment', 'a.s', 1)
P = ('symbol', 'p')


class Names(linear.Context):
    """a and a4 are in fragment A, b in fragment B, p is imported,
    N is 5; the location counter is at A + 8."""

    def symbol(self, name):
        values = {'a': Linear.atom(A), 'a4': Linear.atom(A, 4),
                  'b': Linear.atom(B, 2), 'p': Linear.atom(P),
                  'N': Linear(5)}
        if name not in values:
            return super().symbol(name)
        return Value(None, values[name])

    def local(self, scope, name):
        if (scope, name) == (3, '1$'):
            return Value(None, Linear.atom(A, 6))
        return super().local(scope, name)

    def dot(self):
        return Value(None, Linear.atom(A, 8))


def value(text, scope=3):
    return linear.symbolic(expr.parse_all(lexer.tokenize(text), scope),
                           Names())


class LinearValues(unittest.TestCase):
    def test_terms_with_coefficient_zero_are_dropped(self):
        self.assertEqual(Linear(3, [(A, 0)]), Linear(3))
        self.assertTrue(Linear(3, [(A, 0)]).is_constant)

    def test_plus_minus_times(self):
        total = Linear.atom(A, 1).plus(Linear.atom(B, 2))
        self.assertEqual(total, Linear(3, [(A, 1), (B, 1)]))
        self.assertEqual(total.plus(Linear.atom(A, 1), -1),
                         Linear(2, [(B, 1)]))
        self.assertEqual(total.times(-2), Linear(-6, [(A, -2), (B, -2)]))
        self.assertEqual(total.atoms(), [A, B])
        self.assertEqual(total.coefficient(B), 1)
        self.assertEqual(total.coefficient(P), 0)

    def test_substitute(self):
        total = Linear(1, [(A, 1), (P, 2)])
        self.assertEqual(total.substitute({A: 0x1000}),
                         Linear(0x1001, [(P, 2)]))
        self.assertEqual(total.substitute({P: Linear.atom(B, 3)}),
                         Linear(7, [(A, 1), (B, 2)]))
        self.assertEqual(total.substitute({A: 1, P: 2}), Linear(6))

    def test_equal_values_have_equal_hashes(self):
        self.assertEqual(hash(Linear(1, [(A, 1), (B, 1)])),
                         hash(Linear(1, [(B, 1), (A, 1)])))


class Symbolic(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(value('N * 3 + (1 << 4)'), linear.constant(31))
        self.assertEqual(value('~N & 0xff'), linear.constant(0xfa))
        self.assertEqual(value('-N'), linear.constant(-5))
        self.assertEqual(value('!N'), linear.constant(0))
        self.assertEqual(value('7 / 2 + 7 % 4'), linear.constant(6))

    def test_names(self):
        self.assertEqual(value('a4 + N'), Value(None, Linear.atom(A, 9)))
        self.assertEqual(value('.'), Value(None, Linear.atom(A, 8)))
        self.assertEqual(value('1$ - 1'), Value(None, Linear.atom(A, 5)))
        self.assertEqual(value('p'), Value(None, Linear.atom(P)))

    def test_distance_in_a_fragment_is_a_constant(self):
        self.assertEqual(value('a4 - a'), linear.constant(4))
        self.assertEqual(value('. - 1$'), linear.constant(2))
        self.assertTrue(value('(a4 - a) * 2 + 1').is_constant)

    def test_distance_between_fragments_is_not(self):
        distance = value('b - a')
        self.assertFalse(distance.is_constant)
        self.assertEqual(distance.linear, Linear(2, [(A, -1), (B, 1)]))

    def test_product_with_a_constant(self):
        self.assertEqual(value('2 * a4').linear, Linear(8, [(A, 2)]))
        self.assertEqual(value('a4 * N').linear, Linear(20, [(A, 5)]))

    def test_section_operators_are_atoms(self):
        self.assertEqual(
            value('(.sectionStart table) + 4'),
            Value(None, Linear.atom(('section', 'sectionStart', 'table'),
                                    4)))

    def test_relocation_operators(self):
        self.assertEqual(value('.near (a + 2)'),
                         Value('near', Linear.atom(A, 2)))
        self.assertEqual(value('.word2 p'), Value('word2', Linear.atom(P)))
        self.assertFalse(value('.tiny 4').is_constant)

    def test_byte_or_word_of_a_constant(self):
        self.assertEqual(value('.byte1 0x123456'), linear.constant(0x34))
        self.assertEqual(value('.word2 0x123456'), linear.constant(0x12))
        self.assertEqual(value('.byte0 (N + 0x100)'), linear.constant(5))

    def test_operator_before_a_sum(self):
        for text in ('.word0 p + 2', '2 + .word0 p', '.word0 p - -2'):
            self.assertEqual(value(text),
                             Value('word0', Linear.atom(P, 2)), text)
        self.assertEqual(value('.near a - 1'),
                         Value('near', Linear.atom(A, -1)))

    def test_substitute_a_value(self):
        self.assertEqual(value('.byte2 p').substitute({P: 0x123456}),
                         linear.constant(0x12))
        self.assertEqual(value('.near p').substitute({P: 0x20010}),
                         Value('near', Linear(0x20010)))


class NotAValue(unittest.TestCase):
    def refused(self, text):
        with self.assertRaises(linear.LinearError):
            value(text)

    def test_operators_on_addresses(self):
        for text in ('a * b', 'a >> 8', 'a & 0xff', '~a', '!a', '1 / a',
                     'a == b'):
            self.refused(text)

    def test_relocation_operator_inside_an_expression(self):
        for text in ('.word2 p + 1', '.byte1 p + 1', '2 - .word0 p',
                     '(.word0 p) * 2', '-.word0 p', '.word0 .word0 p',
                     '.word0 p + .word0 p', '.word0 p + a'):
            self.refused(text)

    def test_undefined_names(self):
        self.refused('nothing')
        self.refused('2$')

    def test_division_by_zero(self):
        self.refused('1 / (N - 5)')

    def test_context_without_names(self):
        tree = expr.parse_all(lexer.tokenize('. + x + 1$'))
        with self.assertRaises(linear.LinearError):
            linear.symbolic(tree, linear.Context())


if __name__ == '__main__':
    unittest.main()
