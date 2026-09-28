"""Tests of tools/v816/macro.py: parameters, arguments, substitution."""

import unittest

import support  # noqa: F401  (puts tools/ on the path)
from v816 import cpp, macro


def definition(parameters, *body):
    lines = [cpp.SourceLine(text, 'm.s', 10 + index)
             for index, text in enumerate(body)]
    return macro.Macro('M', macro.parameters(parameters), lines, 'm.s', 9)


def expand(parameters, body, arguments):
    found = macro.expand(definition(parameters, *body),
                         macro.arguments(arguments))
    return [text for text, _ in found]


class Parameters(unittest.TestCase):
    def test_list(self):
        self.assertEqual(macro.parameters(' first, end '),
                         ('first', 'end'))

    def test_none(self):
        self.assertEqual(macro.parameters('   '), ())

    def test_bad_names(self):
        for text in ('a,,b', '1a', 'a b', 'a,', 'a, a'):
            with self.assertRaises(macro.MacroError, msg=text):
                macro.parameters(text)


class Arguments(unittest.TestCase):
    def test_split_at_commas(self):
        self.assertEqual(macro.arguments(' dp:W_YL , ##12,x'),
                         ['dp:W_YL', '##12', 'x'])

    def test_none(self):
        self.assertEqual(macro.arguments('   ; comment'), [])

    def test_comment_is_dropped(self):
        self.assertEqual(macro.arguments(' a, b ; c, d'), ['a', 'b'])

    def test_empty_argument(self):
        self.assertEqual(macro.arguments('a,,b'), ['a', '', 'b'])

    def test_comma_in_string_and_character(self):
        self.assertEqual(macro.arguments('"a,b", \',\', c'),
                         ['"a,b"', "','", 'c'])

    def test_brackets_do_not_protect_a_comma(self):
        self.assertEqual(macro.arguments('(1,x), 2'), ['(1', 'x)', '2'])


class Substitution(unittest.TestCase):
    def test_manual_example(self):
        self.assertEqual(
            expand('a, b', ['  .byte \\a', '  .word \\b - 1', '  .long 0'],
                   ' 5, table'),
            ['  .byte 5', '  .word table - 1', '  .long 0'])

    def test_inside_a_word(self):
        self.assertEqual(expand('reg', ['1$: de\\reg', ' bne 1$'], 'x'),
                         ['1$: dex', ' bne 1$'])

    def test_longest_name_first(self):
        self.assertEqual(expand('a, aa', [' .byte \\aa, \\a, \\aaa'],
                                '1, 2'),
                         [' .byte 2, 1, 2a'])

    def test_name_has_no_end_mark(self):
        self.assertEqual(expand('n', [' lda \\n,s', ' lda \\next'], '3'),
                         [' lda 3,s', ' lda 3ext'])

    def test_argument_used_twice_and_not_at_all(self):
        self.assertEqual(expand('a, b', [' lda \\a', ' sta \\a+2'], 'p, q'),
                         [' lda p', ' sta p+2'])

    def test_argument_text_is_not_substituted_again(self):
        self.assertEqual(expand('a, b', [' .word \\a, \\b'], '\\b, 1'),
                         [' .word \\b, 1'])

    def test_argument_with_prefix_and_operator(self):
        self.assertEqual(
            expand('first, end', [' lda \\end', ' cmp \\first'],
                   ' dp: .tiny (x+1) , long:(y+2)'),
            [' lda long:(y+2)', ' cmp dp: .tiny (x+1)'])

    def test_register_after_a_comma_is_the_next_argument(self):
        self.assertEqual(macro.arguments('long:(y),x'), ['long:(y)', 'x'])

    def test_empty_argument(self):
        self.assertEqual(expand('a, b', [' lda \\a\\b'], ',5'), [' lda 5'])

    def test_backslash_without_a_parameter_stays(self):
        self.assertEqual(expand('n', [' .ascii "a\\t\\n"'], 'x'),
                         [' .ascii "a\\tx"'])
        self.assertEqual(expand('', [' .ascii "a\\n"'], ''),
                         [' .ascii "a\\n"'])

    def test_comment_of_a_body_line_is_dropped(self):
        self.assertEqual(expand('a', [' lda \\a ; the \\a and \\b'], '1'),
                         [' lda 1 '])

    def test_lines_keep_their_place(self):
        found = macro.expand(definition('a', ' nop', ' lda \\a'), ['1'])
        self.assertEqual([(line.file, line.line) for _, line in found],
                         [('m.s', 10), ('m.s', 11)])


class ArgumentCount(unittest.TestCase):
    def test_too_many(self):
        with self.assertRaises(macro.MacroError):
            expand('a', [' lda \\a'], '1, 2')

    def test_too_few(self):
        with self.assertRaises(macro.MacroError):
            expand('a, b', [' lda \\a'], '1')

    def test_none_for_a_macro_with_none(self):
        self.assertEqual(expand('', [' rtl'], ''), [' rtl'])


if __name__ == '__main__':
    unittest.main()
