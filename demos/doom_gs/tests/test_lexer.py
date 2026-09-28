"""Tests of tools/v816/lexer.py."""

import unittest

import support  # noqa: F401  (puts tools/ on the path)
from v816 import lexer


def kinds(line):
    return [(token.kind, token.text) for token in lexer.tokenize(line)]


def values(line):
    return [token.value for token in lexer.tokenize(line)]


class Numbers(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(values('65 0x1ff 0X1F 077 0b1011 0B11 0 007'),
                         [65, 0x1ff, 0x1f, 0o77, 0b1011, 3, 0, 7])

    def test_character_constants(self):
        self.assertEqual(values("'A' ' ' ';' '0' '\\n' '\\'' '\\\\' '\"'"),
                         [65, 32, 59, 48, 10, 39, 92, 34])

    def test_character_constant_is_a_number(self):
        self.assertEqual(kinds("'A'"), [('number', "'A'")])

    def test_bad_numbers(self):
        for text in ('09', '0x', '0b12', '12ab', '0xfg', "'ab'"):
            with self.assertRaises(lexer.LexError, msg=text):
                lexer.tokenize(text)


class Names(unittest.TestCase):
    def test_symbols(self):
        self.assertEqual(kinds('_4 a_symbol abc Test1'),
                         [('ident', '_4'), ('ident', 'a_symbol'),
                          ('ident', 'abc'), ('ident', 'Test1')])

    def test_local_labels(self):
        self.assertEqual(kinds('loop$ 3$ 100$'),
                         [('local', 'loop$'), ('local', '3$'),
                          ('local', '100$')])

    def test_local_label_with_a_bad_number(self):
        with self.assertRaises(lexer.LexError):
            lexer.tokenize('0x3$')

    def test_words_with_a_dot_are_lower_case(self):
        self.assertEqual(kinds('.byte .sectionStart .NEAR'),
                         [('word', '.byte'), ('word', '.sectionstart'),
                          ('word', '.near')])

    def test_location_counter(self):
        self.assertEqual(kinds('bpl .+3'),
                         [('ident', 'bpl'), ('dot', '.'), ('op', '+'),
                          ('number', '3')])

    def test_back_quote_is_not_implemented(self):
        with self.assertRaises(lexer.LexError):
            lexer.tokenize('`a symbol`')


class Operators(unittest.TestCase):
    def test_all(self):
        text = '~ ! - + * / % << >> > < >= <= == != & ^ | ( ) [ ] , : # ##'
        self.assertEqual([token.text for token in lexer.tokenize(text)],
                         text.split())
        self.assertTrue(all(token.kind == 'op'
                            for token in lexer.tokenize(text)))

    def test_without_blanks(self):
        self.assertEqual([token.text for token in lexer.tokenize(
            'a<<2>=b!=~c')],
            ['a', '<<', '2', '>=', 'b', '!=', '~', 'c'])

    def test_immediate_markers(self):
        self.assertEqual(kinds('lda ##-1'),
                         [('ident', 'lda'), ('op', '##'), ('op', '-'),
                          ('number', '1')])
        self.assertEqual(kinds('lda #.byte0 x')[1:3],
                         [('op', '#'), ('word', '.byte0')])


class Strings(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(values('"STBAR"'), [b'STBAR'])

    def test_escapes(self):
        self.assertEqual(values(r'"a\n\t\\\"\'\0\x41"'),
                         [b'a\n\t\\"\'\0A'])

    def test_unknown_escape(self):
        with self.assertRaises(lexer.LexError):
            lexer.tokenize(r'"\q"')

    def test_semicolon_and_quote_inside(self):
        self.assertEqual(values('"you\'re; here" ; comment'),
                         [b"you're; here"])

    def test_string_without_end(self):
        with self.assertRaises(lexer.LexError):
            lexer.tokenize('.ascii "abc')


class CommentsAndColumns(unittest.TestCase):
    def test_comment_is_dropped(self):
        self.assertEqual(kinds("dex ; it's a comment \"x"),
                         [('ident', 'dex')])

    def test_line_of_comment_only(self):
        self.assertEqual(lexer.tokenize(';;; text'), [])
        self.assertEqual(lexer.tokenize(''), [])

    def test_semicolon_in_a_character_constant(self):
        self.assertEqual(values("cmp #';' ; comment"), [None, None, 59])

    def test_strip_comment(self):
        self.assertEqual(lexer.strip_comment('a ";" b ; c ; d'), 'a ";" b ')

    def test_columns(self):
        tokens = lexer.tokenize('lab:  lda #1')
        self.assertEqual([token.column for token in tokens],
                         [0, 3, 6, 10, 11])
        self.assertEqual(lexer.tokenize('  nop')[0].column, 2)


if __name__ == '__main__':
    unittest.main()
