"""Expressions of the Calypsi assembler: syntax tree, parser, evaluation.

The grammar is that of sections 21.5 to 21.7 and 21.10 of the manual.
Binary operators, from the weakest (1) to the strongest (8):

    1  |        2  ^        3  &        4  == !=
    5  < > <= >=            6  << >>    7  + -        8  * / %

All prefix operators have precedence 9: ~ ! - +, the relocation operators
and the section operators. They bind more strongly than any binary
operator, so ".near foo+2" is "(.near foo)+2".

Relocation operators (values as the linker computes them):

    .byte0 .byte1 .byte2   one byte of the value, counted from the low end
    .word0 .word2          the low and the high 16 bits of a 32-bit value
    .tiny                  the value minus the base of the direct page
    .near                  the value minus the base of the near area
    .kbank                 the low 16 bits; the bank must be that of the
                           instruction (jmp and jsr in the program bank)

Section operators take the name of a section: .sectionStart,
.sectionEnd (the last address, not the one after it) and .sectionSize.

An address can start with dp:, abs: or long:, which sets the size of
the operand of the instruction (8, 16 or 24 bits). That prefix is not
part of the expression; parse_address returns it beside the tree.

Assumptions, where the manual is silent: comparisons and "!" give 1 for
true; division rounds towards zero and the remainder has the sign of the
dividend, as in C. The sources do not divide negative numbers.
"""

from dataclasses import dataclass
from typing import Optional

PREFIXES = ('dp', 'abs', 'long')
RELOCATIONS = ('.byte0', '.byte1', '.byte2', '.word0', '.word2',
               '.tiny', '.near', '.kbank')
SECTION_OPERATORS = ('.sectionstart', '.sectionend', '.sectionsize')
UNARY_OPERATORS = ('~', '!', '-', '+')
BINARY_LEVELS = (
    ('|',), ('^',), ('&',), ('==', '!='), ('<', '>', '<=', '>='),
    ('<<', '>>'), ('+', '-'), ('*', '/', '%'))


class ExprError(ValueError):
    """The expression cannot be parsed or evaluated."""


@dataclass(frozen=True)
class Number:
    value: int


@dataclass(frozen=True)
class Symbol:
    name: str


@dataclass(frozen=True)
class Local:
    """A local label "N$". `scope` is the number of the scope that the
    reference is in (tools/v816/parse.py gives the numbers)."""
    name: str
    scope: int


@dataclass(frozen=True)
class Dot:
    """The location counter: the address of the instruction or datum."""


@dataclass(frozen=True)
class Unary:
    op: str
    operand: object


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Reloc:
    """A relocation operator (without its dot: "near", "byte1")."""
    op: str
    operand: object


@dataclass(frozen=True)
class SectionOp:
    """A section operator: "sectionStart", "sectionEnd", "sectionSize"."""
    op: str
    section: str


_SECTION_NAMES = {'.sectionstart': 'sectionStart',
                  '.sectionend': 'sectionEnd',
                  '.sectionsize': 'sectionSize'}


class _Parser:
    def __init__(self, tokens, position, scope):
        self.tokens = tokens
        self.position = position
        self.scope = scope

    def _peek(self):
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return None

    def _next(self, what):
        token = self._peek()
        if token is None:
            raise ExprError('the line ends where %s should be' % what)
        self.position += 1
        return token

    def binary(self, level=0):
        if level == len(BINARY_LEVELS):
            return self.unary()
        left = self.binary(level + 1)
        while True:
            token = self._peek()
            if (token is None or token.kind != 'op'
                    or token.text not in BINARY_LEVELS[level]):
                return left
            self.position += 1
            left = Binary(token.text, left, self.binary(level + 1))

    def unary(self):
        token = self._next('an expression')
        if token.kind == 'op' and token.text in UNARY_OPERATORS:
            return Unary(token.text, self.unary())
        if token.kind == 'word' and token.text in RELOCATIONS:
            return Reloc(token.text[1:], self.unary())
        if token.kind == 'word' and token.text in SECTION_OPERATORS:
            name = self._next('a section name')
            if name.kind != 'ident':
                raise ExprError('%s needs a section name, not "%s"'
                                % (token.text, name.text))
            return SectionOp(_SECTION_NAMES[token.text], name.text)
        if token.kind == 'number':
            return Number(token.value)
        if token.kind == 'ident':
            return Symbol(token.text)
        if token.kind == 'local':
            return Local(token.text, self.scope)
        if token.kind == 'dot':
            return Dot()
        if token.kind == 'op' and token.text == '(':
            inner = self.binary()
            closing = self._next('")"')
            if closing.text != ')':
                raise ExprError('")" expected, not "%s"' % closing.text)
            return inner
        raise ExprError('unexpected "%s" in an expression' % token.text)


def parse(tokens, position=0, scope=0):
    """The tree of the expression that starts at tokens[position], and
    the position of the token after it."""
    parser = _Parser(tokens, position, scope)
    return parser.binary(), parser.position


def parse_all(tokens, scope=0):
    """The tree of the expression that `tokens` is; tokens after the
    expression are an error."""
    tree, position = parse(tokens, 0, scope)
    if position != len(tokens):
        raise ExprError('unexpected "%s" after the expression'
                        % tokens[position].text)
    return tree


def parse_address(tokens, position=0, scope=0):
    """An expression with an optional prefix dp:, abs: or long:.

    Returns (prefix or None, tree, position after the expression)."""
    prefix = None
    if (position + 1 < len(tokens)
            and tokens[position].kind == 'ident'
            and tokens[position].text.lower() in PREFIXES
            and tokens[position + 1].text == ':'):
        prefix = tokens[position].text.lower()
        position += 2
    tree, position = parse(tokens, position, scope)
    return prefix, tree, position


def walk(tree):
    """All nodes of `tree`, the root first."""
    yield tree
    if isinstance(tree, (Unary, Reloc)):
        yield from walk(tree.operand)
    elif isinstance(tree, Binary):
        yield from walk(tree.left)
        yield from walk(tree.right)


@dataclass
class Environment:
    """What the value of an expression depends on.

    symbols   value by name
    locals    value by (scope, name)
    sections  (first address, last address) by section name
    dot       the location counter, or None where there is none
    """
    symbols: dict
    locals: dict
    sections: dict
    dot: Optional[int] = None
    direct_page_base: int = 0
    near_base: int = 0


def _divide(left, right):
    if right == 0:
        raise ExprError('division by zero')
    quotient = abs(left) // abs(right)
    return quotient if (left < 0) == (right < 0) else -quotient


def _shift_count(count):
    if count < 0:
        raise ExprError('negative shift count')
    return count


_BINARY = {
    '|': lambda a, b: a | b,
    '^': lambda a, b: a ^ b,
    '&': lambda a, b: a & b,
    '==': lambda a, b: int(a == b),
    '!=': lambda a, b: int(a != b),
    '<': lambda a, b: int(a < b),
    '>': lambda a, b: int(a > b),
    '<=': lambda a, b: int(a <= b),
    '>=': lambda a, b: int(a >= b),
    '<<': lambda a, b: a << _shift_count(b),
    '>>': lambda a, b: a >> _shift_count(b),
    '+': lambda a, b: a + b,
    '-': lambda a, b: a - b,
    '*': lambda a, b: a * b,
    '/': _divide,
    '%': lambda a, b: a - b * _divide(a, b),
}

_UNARY = {
    '~': lambda a: ~a,
    '!': lambda a: int(a == 0),
    '-': lambda a: -a,
    '+': lambda a: a,
}

_PARTS = {
    'byte0': (0, 0xff), 'byte1': (8, 0xff), 'byte2': (16, 0xff),
    'word0': (0, 0xffff), 'word2': (16, 0xffff),
}


def _relocate(op, value, environment):
    if op in _PARTS:
        shift, mask = _PARTS[op]
        return value >> shift & mask
    if op == 'tiny':
        return value - environment.direct_page_base
    if op == 'near':
        return value - environment.near_base
    if environment.dot is None:
        raise ExprError('.kbank where there is no location counter')
    if value >> 16 != environment.dot >> 16:
        raise ExprError('.kbank: $%06X is not in bank $%02X'
                        % (value, environment.dot >> 16))
    return value & 0xffff


def _section(tree, environment):
    if tree.section not in environment.sections:
        raise ExprError('unknown section %s' % tree.section)
    first, last = environment.sections[tree.section]
    if tree.op == 'sectionStart':
        return first
    if tree.op == 'sectionEnd':
        return last
    return 1 + last - first


def evaluate(tree, environment):
    """The value of `tree`, a signed integer without a range limit.

    The user of the value checks the range that its place allows."""
    if isinstance(tree, Number):
        return tree.value
    if isinstance(tree, Symbol):
        if tree.name not in environment.symbols:
            raise ExprError('undefined symbol %s' % tree.name)
        return environment.symbols[tree.name]
    if isinstance(tree, Local):
        key = (tree.scope, tree.name)
        if key not in environment.locals:
            raise ExprError('undefined local label %s' % tree.name)
        return environment.locals[key]
    if isinstance(tree, Dot):
        if environment.dot is None:
            raise ExprError('"." where there is no location counter')
        return environment.dot
    if isinstance(tree, Unary):
        return _UNARY[tree.op](evaluate(tree.operand, environment))
    if isinstance(tree, Binary):
        return _BINARY[tree.op](evaluate(tree.left, environment),
                                evaluate(tree.right, environment))
    if isinstance(tree, Reloc):
        return _relocate(tree.op, evaluate(tree.operand, environment),
                         environment)
    if isinstance(tree, SectionOp):
        return _section(tree, environment)
    raise ExprError('not an expression: %r' % (tree,))


def text(tree):
    """`tree` as source text, fully parenthesised where it nests."""
    if isinstance(tree, Number):
        return str(tree.value)
    if isinstance(tree, (Symbol, Local)):
        return tree.name
    if isinstance(tree, Dot):
        return '.'
    if isinstance(tree, Unary):
        return '%s%s' % (tree.op, _nested(tree.operand))
    if isinstance(tree, Reloc):
        return '.%s %s' % (tree.op, _nested(tree.operand))
    if isinstance(tree, SectionOp):
        return '.%s %s' % (tree.op, tree.section)
    if isinstance(tree, Binary):
        return '%s %s %s' % (_nested(tree.left), tree.op,
                             _nested(tree.right))
    raise ExprError('not an expression: %r' % (tree,))


def _nested(tree):
    if isinstance(tree, (Binary, Reloc, SectionOp)):
        return '(%s)' % text(tree)
    return text(tree)
