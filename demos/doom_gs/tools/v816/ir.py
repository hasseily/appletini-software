"""The intermediate representation that the front end produces.

One Unit for each source file that the assembler is run on. A unit is an
ordered list of section fragments: each .section directive starts a
fragment, and the linker places fragments, not files. A fragment is an
ordered list of items, each with the place it came from.

Nothing here has a size or an address yet: the encoder chooses operand
sizes and the linker places the fragments. Expressions are trees of
tools/v816/expr.py.

Addressing modes are recorded as written, not as decided:

    ''            no operand            'a'           the accumulator
    '#'  '##'     immediate, 8 and 16 bits
    'e'           an address            'e,x' 'e,y' 'e,s'
    '(e)' '(e,x)' '(e),y' '(e,s),y'     '[e]' '[e],y'

`prefix` holds dp, abs or long when the operand has one.
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple

MODES = ('', 'a', '#', '##', 'e', 'e,x', 'e,y', 'e,s',
         '(e)', '(e,x)', '(e),y', '(e,s),y', '[e]', '[e],y')


@dataclass(frozen=True)
class Expansion:
    """One level of macro expansion: the macro and the line that used
    it."""
    macro: str
    file: str
    line: int


@dataclass(frozen=True)
class Where:
    """The source line of an item. For an item from a macro, `file` and
    `line` are the line of the macro body, and `expansions` lists the
    uses that led to it, the outermost first."""
    file: str
    line: int
    expansions: Tuple[Expansion, ...] = ()


@dataclass
class Label:
    """A label at the current position. A local label ("N$") belongs to
    the scope with the number `scope`; for other labels it is None."""
    name: str
    scope: Optional[int]
    where: Where

    @property
    def local(self):
        return self.scope is not None


@dataclass
class Equate:
    """NAME .equ expression. When the expression uses the location
    counter, as in "X .equ .", the symbol is a position in the code and
    `position` is true. `location` is true for .equlab."""
    name: str
    value: object
    position: bool
    location: bool
    where: Where


@dataclass
class Instruction:
    mnemonic: str               # lower case
    mode: str                   # one of MODES
    prefix: Optional[str]       # 'dp', 'abs', 'long' or None
    operand: object             # expression tree, or None
    where: Where


@dataclass
class Data:
    """.byte .word .address .long .quad: `values` are expression trees.
    .ascii .asciz: `values` are bytes objects, one for each string of
    the list, without the 0 that .asciz puts after each."""
    directive: str              # without the dot
    values: list
    where: Where


@dataclass
class Space:
    """.space count[, fill]"""
    count: object
    fill: object                # expression tree, or None
    where: Where


@dataclass
class FillTo:
    """.fillto offset[, fill]; the offset is from the fragment start."""
    offset: object
    fill: object
    where: Where


@dataclass
class Align:
    alignment: object
    where: Where


@dataclass
class IncBin:
    path: str
    where: Where


@dataclass
class Fragment:
    """The items between one .section directive and the next.

    `kind` is text, data, rodata or bss, or None when the directive gave
    none (the linker then uses the default, text). `modifiers` are as
    written: root, noroot, reorder, noreorder, noinit."""
    section: str
    kind: Optional[str]
    modifiers: Tuple[str, ...]
    where: Optional[Where]      # None for the implied "code" at the start
    items: list = field(default_factory=list)


@dataclass
class Declaration:
    """A name of .public, .extern, .require or similar."""
    directive: str
    name: str
    where: Where


@dataclass
class RtModel:
    name: str
    value: str
    where: Where


@dataclass
class MacroInfo:
    """A macro definition, for the statistics and for overrides."""
    name: str
    parameters: Tuple[str, ...]
    lines: int
    where: Where


@dataclass
class Error:
    message: str
    where: Where

    def __str__(self):
        text = '%s:%d: %s' % (self.where.file, self.where.line,
                              self.message)
        for expansion in reversed(self.where.expansions):
            text += '\n    in macro %s used at %s:%d' % (
                expansion.macro, expansion.file, expansion.line)
        return text


@dataclass
class Unit:
    """All that one run of the assembler reads."""
    path: str
    fragments: list = field(default_factory=list)
    declarations: list = field(default_factory=list)
    rtmodels: list = field(default_factory=list)
    macros: list = field(default_factory=list)
    errors: list = field(default_factory=list)
