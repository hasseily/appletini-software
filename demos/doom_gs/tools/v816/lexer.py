"""Tokens of one line of Calypsi assembly, after the preprocessor.

The syntax is that of chapter 21 of the Calypsi manual
(docs/research/calypsi-assembler-chapter.txt):
- ";" starts a comment, except inside a string or character constant
- symbols start with a letter or "_"; a name or a number with "$" at its
  end is a local label ("loop$", "3$")
- numbers: decimal, 0x hexadecimal, 0b binary, octal with a leading 0,
  and character constants
- a word that starts with "." is a directive or an operator (".byte",
  ".near"); a "." alone is the location counter
- "##" is one token: the marker of a 16-bit immediate

Back-quoted symbols and sign-style local labels ("+", "--") are part of
the language but not of upstream's sources; they are not implemented, and
a back quote is an error.

Escapes in strings and character constants are read as in C. The manual
does not describe them; the sources use \\n and \\t only. (Assumption
until the image match has checked the bytes of the strings.)
"""

import re
from collections import namedtuple

Token = namedtuple('Token', 'kind text value column')
Token.__doc__ = """A token.

kind    'ident', 'local', 'number', 'string', 'word' (a directive or
        operator that starts with "."), 'dot' or 'op'
text    as written; for a 'word' in lower case
value   the integer of a 'number', the bytes of a 'string', else None
column  offset in the line, 0 for the label column"""


class LexError(ValueError):
    """The line has text that is not a token."""


_TOKEN_RE = re.compile(r"""
    (?P<space>[ \t\f\v]+)
  | (?P<number>[0-9][0-9A-Za-z_]*\$?)
  | (?P<ident>[A-Za-z_][A-Za-z_0-9]*\$?)
  | (?P<word>\.[A-Za-z][A-Za-z_0-9]*)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<char>'(?:[^'\\]|\\.)[^']*')
  | (?P<op>\#\#|<<|>>|<=|>=|==|!=|[-+*/%&|^~!<>()\[\],:\#.])
""", re.VERBOSE)

_ESCAPES = {'n': 10, 't': 9, 'r': 13, '0': 0, 'a': 7, 'b': 8, 'f': 12,
            'v': 11, '\\': 92, "'": 39, '"': 34}


def strip_comment(line):
    """`line` without its ";" comment."""
    position = 0
    while position < len(line):
        char = line[position]
        if char == ';':
            return line[:position]
        if char in '"\'':
            match = _TOKEN_RE.match(line, position)
            if match and match.lastgroup in ('string', 'char'):
                position = match.end()
                continue
        position += 1
    return line


def number(text):
    """The value of the numeric constant `text`."""
    try:
        lower = text.lower()
        if lower.startswith('0x'):
            return int(lower[2:], 16)
        if lower.startswith('0b'):
            return int(lower[2:], 2)
        if len(text) > 1 and text[0] == '0':
            return int(text, 8)
        return int(text, 10)
    except ValueError:
        raise LexError('bad number "%s"' % text)


def unescape(text):
    """The bytes of the inside of a string or character constant."""
    out = bytearray()
    position = 0
    while position < len(text):
        char = text[position]
        position += 1
        if char != '\\':
            out += char.encode('utf-8', errors='surrogateescape')
            continue
        escape = text[position:position + 1]
        position += 1
        if escape == 'x':
            digits = re.match('[0-9A-Fa-f]{1,2}', text[position:])
            if not digits:
                raise LexError('bad escape in "%s"' % text)
            out.append(int(digits.group(), 16))
            position += digits.end()
        elif escape in _ESCAPES:
            out.append(_ESCAPES[escape])
        else:
            raise LexError('unknown escape "\\%s" in "%s"' % (escape, text))
    return bytes(out)


def tokenize(line):
    """The tokens of `line`; the comment and the white space are left
    out."""
    line = strip_comment(line)
    tokens = []
    position = 0
    while position < len(line):
        match = _TOKEN_RE.match(line, position)
        if not match:
            raise LexError('unexpected "%s" at column %d'
                           % (line[position], position + 1))
        kind = match.lastgroup
        text = match.group()
        if kind == 'number':
            if text.endswith('$'):
                if not text[:-1].isdigit():
                    raise LexError('bad local label "%s"' % text)
                tokens.append(Token('local', text, None, position))
            else:
                tokens.append(Token('number', text, number(text), position))
        elif kind == 'ident':
            local = text.endswith('$')
            tokens.append(Token('local' if local else 'ident', text, None,
                                position))
        elif kind == 'word':
            tokens.append(Token('word', text.lower(), None, position))
        elif kind == 'string':
            tokens.append(Token('string', text, unescape(text[1:-1]),
                                position))
        elif kind == 'char':
            value = unescape(text[1:-1])
            if len(value) != 1:
                raise LexError('character constant %s is not one byte'
                               % text)
            tokens.append(Token('number', text, value[0], position))
        elif kind == 'op':
            tokens.append(Token('dot' if text == '.' else 'op', text, None,
                                position))
        position = match.end()
    return tokens
