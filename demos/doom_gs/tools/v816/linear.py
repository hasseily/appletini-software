"""Values that are known up to the placement of the program.

The assembler does not know where the linker puts a fragment, so the
value of a label is "the address of its fragment plus an offset". A
Linear is such a value: a constant plus a sum of atoms, each with a
coefficient. An atom stands for a number that only the linker knows:

    ('fragment', unit, index)   the address of a fragment of a unit
    ('symbol', name)            a symbol of another unit, or of the linker
    ('section', op, name)       .sectionStart, .sectionEnd, .sectionSize

A Linear without atoms is a constant: "an expression that the assembler
can solve" of the manual (21.3.2). The difference of two labels of one
fragment is a constant too, because the atoms cancel.

A Value is a Linear with the relocation operator that stands before it,
if any. The operators are not linear, so they stay symbolic until the
link, except for the byte and word operators on a constant.

symbolic() makes the Value of an expression tree of tools/v816/expr.py.
"""

from typing import NamedTuple, Optional

from . import expr

FRAGMENT = 'fragment'
SYMBOL = 'symbol'
SECTION = 'section'

# Relocation operators that give the low bits of their operand, or the
# operand minus a base: adding a constant before or after them gives
# the same bits in the place of the value.
_HOISTED = ('byte0', 'word0', 'tiny', 'near', 'kbank')
_PARTS = {'byte0': (0, 0xff), 'byte1': (8, 0xff), 'byte2': (16, 0xff),
          'word0': (0, 0xffff), 'word2': (16, 0xffff)}
_NO_NAMES = expr.Environment({}, {}, {})


class LinearError(ValueError):
    """The expression has no value of the form that a relocation can
    hold."""


class Linear:
    """constant + sum of coefficient * atom. Immutable."""

    __slots__ = ('constant', 'terms')

    def __init__(self, constant=0, terms=()):
        self.constant = constant
        self.terms = tuple(sorted((atom, coefficient)
                                  for atom, coefficient in dict(terms).items()
                                  if coefficient))

    @classmethod
    def atom(cls, atom, constant=0):
        """The value of `atom` plus `constant`."""
        return cls(constant, ((atom, 1),))

    @property
    def is_constant(self):
        return not self.terms

    def atoms(self):
        """The atoms that the value depends on."""
        return [atom for atom, _ in self.terms]

    def plus(self, other, sign=1):
        """self + sign * other"""
        terms = dict(self.terms)
        for atom, coefficient in other.terms:
            terms[atom] = terms.get(atom, 0) + sign * coefficient
        return Linear(self.constant + sign * other.constant, terms.items())

    def times(self, factor):
        return Linear(self.constant * factor,
                      [(atom, coefficient * factor)
                       for atom, coefficient in self.terms])

    def substitute(self, values):
        """The value with each atom of `values` (a map from atom to
        number or Linear) replaced; other atoms stay."""
        result = Linear(self.constant)
        for atom, coefficient in self.terms:
            value = values.get(atom)
            if value is None:
                value = Linear.atom(atom)
            elif not isinstance(value, Linear):
                value = Linear(value)
            result = result.plus(value.times(coefficient))
        return result

    def __eq__(self, other):
        return (isinstance(other, Linear)
                and self.constant == other.constant
                and self.terms == other.terms)

    def __hash__(self):
        return hash((self.constant, self.terms))

    def __repr__(self):
        return 'Linear(%r, %r)' % (self.constant, self.terms)


class Value(NamedTuple):
    """A Linear and the relocation operator that applies to it ("near",
    "word0", ...; None when there is none)."""
    reloc: Optional[str]
    linear: Linear

    @property
    def is_constant(self):
        """True when the assembler knows the number."""
        return self.reloc is None and self.linear.is_constant

    def substitute(self, values):
        return simplify(self.reloc, self.linear.substitute(values))


def constant(number):
    """The Value of a number."""
    return Value(None, Linear(number))


def simplify(reloc, linear):
    """The Value of `reloc` applied to `linear`: a byte or a word of a
    constant is a constant."""
    if reloc in _PARTS and linear.is_constant:
        shift, mask = _PARTS[reloc]
        return constant(linear.constant >> shift & mask)
    return Value(reloc, linear)


class Context:
    """What symbolic() asks for the names in an expression. The
    assembler makes a subclass for each unit."""

    def symbol(self, name):
        """The Value of the symbol `name`."""
        raise LinearError('undefined symbol %s' % name)

    def local(self, scope, name):
        """The Value of the local label `name` of `scope`."""
        raise LinearError('undefined local label %s' % name)

    def dot(self):
        """The Value of the location counter."""
        raise LinearError('"." where there is no location counter')


def _numbers(op, left, right):
    tree = expr.Binary(op, expr.Number(left), expr.Number(right))
    try:
        return expr.evaluate(tree, _NO_NAMES)
    except expr.ExprError as error:
        raise LinearError(str(error))


def _binary(tree, context):
    left = symbolic(tree.left, context)
    right = symbolic(tree.right, context)
    if left.reloc or right.reloc:
        return _hoist(tree, left, right)
    if tree.op == '+':
        return Value(None, left.linear.plus(right.linear))
    if tree.op == '-':
        return Value(None, left.linear.plus(right.linear, -1))
    if tree.op == '*' and right.is_constant:
        return Value(None, left.linear.times(right.linear.constant))
    if tree.op == '*' and left.is_constant:
        return Value(None, right.linear.times(left.linear.constant))
    if left.is_constant and right.is_constant:
        return constant(_numbers(tree.op, left.linear.constant,
                                 right.linear.constant))
    raise LinearError('"%s" of a value that depends on the placement: %s'
                      % (tree.op, expr.text(tree)))


def _hoist(tree, left, right):
    """(operator value) + constant, which the sources write without the
    brackets that the manual asks for (".word0 NAME + 2"). For the
    operators of _HOISTED it is the operator on (value + constant)."""
    if (tree.op in ('+', '-') and left.reloc in _HOISTED
            and right.is_constant):
        sign = 1 if tree.op == '+' else -1
        return Value(left.reloc, left.linear.plus(right.linear, sign))
    if tree.op == '+' and right.reloc in _HOISTED and left.is_constant:
        return Value(right.reloc, right.linear.plus(left.linear))
    raise LinearError('a relocation operator inside an expression: %s'
                      % expr.text(tree))


def symbolic(tree, context):
    """The Value of the expression `tree`. Raises LinearError for an
    expression whose value is not a Value, such as the product of two
    addresses."""
    if isinstance(tree, expr.Number):
        return constant(tree.value)
    if isinstance(tree, expr.Symbol):
        return context.symbol(tree.name)
    if isinstance(tree, expr.Local):
        return context.local(tree.scope, tree.name)
    if isinstance(tree, expr.Dot):
        return context.dot()
    if isinstance(tree, expr.SectionOp):
        return Value(None, Linear.atom((SECTION, tree.op, tree.section)))
    if isinstance(tree, expr.Reloc):
        inner = symbolic(tree.operand, context)
        if inner.reloc:
            raise LinearError('a relocation operator inside another: %s'
                              % expr.text(tree))
        return simplify(tree.op, inner.linear)
    if isinstance(tree, expr.Unary):
        inner = symbolic(tree.operand, context)
        if inner.reloc:
            raise LinearError('a relocation operator inside an '
                              'expression: %s' % expr.text(tree))
        if tree.op == '+':
            return inner
        if tree.op == '-':
            return Value(None, inner.linear.times(-1))
        if inner.is_constant:
            return constant(expr.evaluate(
                expr.Unary(tree.op, expr.Number(inner.linear.constant)),
                _NO_NAMES))
        raise LinearError('"%s" of a value that depends on the placement: '
                          '%s' % (tree.op, expr.text(tree)))
    if isinstance(tree, expr.Binary):
        return _binary(tree, context)
    raise LinearError('not an expression: %r' % (tree,))
