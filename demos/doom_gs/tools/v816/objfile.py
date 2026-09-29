"""The assembler of a unit: from the IR to fragments of bytes with holes.

assemble() does what the Calypsi assembler does for one source file. An
ObjectFile is what an object file of the vendor holds, as far as the
link needs it: for each section fragment its bytes, the holes that the
linker fills (relocations), and the offsets of its labels; the symbols
that the unit exports; its errors.

The size of an instruction can depend on the value of a constant that
is the distance of two labels, and the offsets of the labels depend on
the sizes. The assembler therefore lays the unit out again until no
offset changes.

Sections of the kind bss, and sections with the modifier noinit, have
a size and labels, and no bytes.
"""

from dataclasses import dataclass, field
from typing import Dict, List, NamedTuple, Optional, Tuple

from . import asm816, ir, linear

DATA_WIDTHS = {'byte': 1, 'word': 2, 'address': 3, 'long': 4, 'quad': 8}
EXPORTS = ('public', 'global', 'globl', 'pubweak')
IMPORTS = ('extern', 'require')
MAX_PASSES = 12


class Span(NamedTuple):
    """The bytes of one item of the source."""
    offset: int
    length: int
    where: ir.Where


@dataclass
class ObjectFragment:
    """A section fragment after the assembler.

    `key` names it in the link: (unit name, number of the fragment in
    the unit). `data` has `size` bytes when the fragment is
    `initialised`, else none. `labels` maps each label that is not
    local to its offset. `requires` are the names of the .require
    directives in the fragment.

    `kind` is the kind of the .section directive, or text when the
    directive gives none; `kind_given` tells the two apart. Taking
    text is an assumption: text is the default kind of a section, but
    the manual does not say whether a .section NAME without a kind
    takes the kind that NAME is given elsewhere. link.Program reports
    every link where the answer would matter: a fragment without a
    kind in a section that another fragment gives a kind other than
    text.
    """
    key: Tuple[str, int]
    section: str
    kind: str
    modifiers: Tuple[str, ...]
    where: Optional[ir.Where]
    size: int = 0
    alignment: int = 1
    data: bytes = b''
    holes: List[asm816.Hole] = field(default_factory=list)
    spans: List[Span] = field(default_factory=list)
    labels: Dict[str, int] = field(default_factory=dict)
    requires: List[str] = field(default_factory=list)
    kind_given: bool = True

    @property
    def initialised(self):
        return self.kind != 'bss' and 'noinit' not in self.modifiers

    @property
    def cleared(self):
        """True for a fragment with a size that the startup code fills
        with zeros: the kind bss without noinit."""
        return (self.kind == 'bss' and 'noinit' not in self.modifiers
                and self.size > 0)

    @property
    def atom(self):
        """The atom that stands for the address of the fragment."""
        return (linear.FRAGMENT,) + self.key

    def span_at(self, offset):
        """The Span that holds the byte at `offset`, or None."""
        low, high = 0, len(self.spans)
        while low < high:
            middle = (low + high) // 2
            if self.spans[middle].offset + self.spans[middle].length \
                    <= offset:
                low = middle + 1
            else:
                high = middle
        if low < len(self.spans) and self.spans[low].offset <= offset:
            return self.spans[low]
        return None


@dataclass
class ObjectFile:
    """A unit after the assembler.

    `symbols` maps every name that the unit defines, labels and
    equates, to its linear.Value; `exports` are the names of `symbols`
    that other units see; `imports` are the names of .extern.
    """
    name: str
    path: str
    fragments: List[ObjectFragment] = field(default_factory=list)
    symbols: Dict[str, linear.Value] = field(default_factory=dict)
    exports: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    errors: List[ir.Error] = field(default_factory=list)


class _Names(linear.Context):
    """The names of a unit, for linear.symbolic(). `position` is set
    to the place of the item that is being assembled."""

    def __init__(self, assembler):
        self.assembler = assembler
        self.position = None        # (fragment number, item number)
        self.memo = {}
        self.active = []

    def _place(self, fragment, item):
        assembler = self.assembler
        return linear.Value(None, linear.Linear.atom(
            assembler.atoms[fragment], assembler.offsets[fragment][item]))

    def dot(self):
        return self._place(*self.position)

    def local(self, scope, name):
        place = self.assembler.locals.get((scope, name))
        if place is None:
            raise linear.LinearError('undefined local label %s' % name)
        return self._place(*place)

    def symbol(self, name):
        assembler = self.assembler
        if name in assembler.labels:
            return self._place(*assembler.labels[name])
        if name in assembler.equates:
            return self._equate(name)
        if name in assembler.imports:
            return linear.Value(None, linear.Linear.atom(
                (linear.SYMBOL, name)))
        raise linear.LinearError('undefined symbol %s' % name)

    def _equate(self, name):
        if name in self.memo:
            return self.memo[name]
        if name in self.active:
            raise linear.LinearError('the equate %s uses itself' % name)
        fragment, item, tree = self.assembler.equates[name]
        outer = self.position
        self.position = (fragment, item)
        self.active.append(name)
        try:
            value = linear.symbolic(tree, self)
        finally:
            self.active.pop()
            self.position = outer
        self.memo[name] = value
        return value


class _Assembler:
    def __init__(self, unit, name):
        self.unit = unit
        self.name = name
        self.atoms = [(linear.FRAGMENT, name, number)
                      for number in range(len(unit.fragments))]
        self.offsets = [[0] * (len(fragment.items) + 1)
                        for fragment in unit.fragments]
        self.labels = {}            # name -> (fragment, item)
        self.locals = {}            # (scope, name) -> (fragment, item)
        self.equates = {}           # name -> (fragment, item, tree)
        self.imports = set()
        self.errors = []
        self.names = _Names(self)

    def _error(self, message, where):
        self.errors.append(ir.Error(message, where))

    def _collect(self):
        for declaration in self.unit.declarations:
            if declaration.directive in IMPORTS:
                self.imports.add(declaration.name)
        for number, fragment in enumerate(self.unit.fragments):
            for index, item in enumerate(fragment.items):
                if isinstance(item, ir.Label) and item.local:
                    self.locals[(item.scope, item.name)] = (number, index)
                elif isinstance(item, (ir.Label, ir.Equate)):
                    self._define(item, number, index)

    def _define(self, item, number, index):
        if item.name in self.labels or item.name in self.equates:
            self._error('%s is defined twice' % item.name, item.where)
        elif isinstance(item, ir.Label):
            self.labels[item.name] = (number, index)
        else:
            self.equates[item.name] = (number, index, item.value)

    # ----- one item

    def _value(self, tree):
        return linear.symbolic(tree, self.names)

    def _constant(self, tree, what):
        value = self._value(tree)
        if not value.is_constant:
            raise asm816.EncodeError('%s must be a constant' % what)
        return value.linear.constant

    def _fill(self, item, count):
        fill = 0
        if item.fill is not None:
            fill = self._constant(item.fill, 'the fill value')
            if not asm816.fits(fill, 1):
                raise asm816.EncodeError('the fill value %d is not a byte'
                                         % fill)
        if count < 0:
            raise asm816.EncodeError('a negative size: %d' % count)
        return asm816.Encoded(asm816.little_endian(fill, 1) * count)

    def _data(self, item):
        if item.directive in ('ascii', 'asciz'):
            end = b'\0' if item.directive == 'asciz' else b''
            return asm816.Encoded(b''.join(text + end
                                           for text in item.values))
        width = DATA_WIDTHS[item.directive]
        data = bytearray()
        holes = []
        for tree in item.values:
            part = asm816.field(self._value(tree), width, asm816.KIND_DATA,
                                len(data), '.' + item.directive)
            data += part.data
            holes += part.holes
        return asm816.Encoded(bytes(data), tuple(holes))

    def _encode(self, item, number, offset):
        """The Encoded of `item`, which is at `offset` of the fragment
        with the number `number`."""
        if isinstance(item, ir.Instruction):
            value = None
            if item.operand is not None:
                value = self._value(item.operand)
            position = linear.Linear.atom(self.atoms[number], offset)
            return asm816.encode(item, value, position)
        if isinstance(item, ir.Data):
            return self._data(item)
        if isinstance(item, ir.Space):
            return self._fill(item, self._constant(item.count, 'the size'))
        if isinstance(item, ir.FillTo):
            target = self._constant(item.offset, 'the offset')
            return self._fill(item, target - offset)
        if isinstance(item, ir.Align):
            alignment = self._constant(item.alignment, 'the alignment')
            if alignment < 1:
                raise asm816.EncodeError('the alignment %d' % alignment)
            return asm816.Encoded(bytes(-offset % alignment))
        if isinstance(item, ir.IncBin):
            raise asm816.EncodeError('.incbin is not implemented; the '
                                     'sources do not use it')
        return asm816.Encoded(b'')      # a label or an equate

    # ----- passes

    def _pass(self, last):
        """Lay out all fragments with the offsets of the pass before.
        Returns the list of (item, Encoded or None) of each fragment;
        errors are recorded in the last pass only."""
        self.names.memo = {}
        changed = False
        encoded = []
        for number, fragment in enumerate(self.unit.fragments):
            offset = 0
            row = []
            for index, item in enumerate(fragment.items):
                if self.offsets[number][index] != offset:
                    self.offsets[number][index] = offset
                    changed = True
                self.names.position = (number, index)
                try:
                    result = self._encode(item, number, offset)
                except (asm816.EncodeError, linear.LinearError) as error:
                    if last:
                        self._error(str(error), item.where)
                    result = asm816.Encoded(b'')
                row.append(result)
                offset += len(result.data)
            if self.offsets[number][-1] != offset:
                self.offsets[number][-1] = offset
                changed = True
            encoded.append(row)
        return encoded, changed

    def run(self):
        self._collect()
        for _ in range(MAX_PASSES):
            _, changed = self._pass(last=False)
            if not changed:
                break
        else:
            self._error('the sizes of the instructions do not settle',
                        ir.Where(self.unit.path, 0))
        encoded, _ = self._pass(last=True)
        result = ObjectFile(self.name, self.unit.path,
                            imports=sorted(self.imports))
        for number, fragment in enumerate(self.unit.fragments):
            result.fragments.append(
                self._fragment(number, fragment, encoded[number]))
        self._symbols(result)
        self._requires(result)
        result.errors = self.errors
        return result

    def _fragment(self, number, fragment, encoded):
        made = ObjectFragment(
            (self.name, number), fragment.section, fragment.kind or 'text',
            fragment.modifiers, fragment.where,
            size=self.offsets[number][-1],
            kind_given=fragment.kind is not None)
        data = bytearray()
        for index, item in enumerate(fragment.items):
            offset = self.offsets[number][index]
            result = encoded[index]
            if isinstance(item, ir.Label) and not item.local:
                made.labels[item.name] = offset
            if isinstance(item, ir.Align):
                made.alignment = max(made.alignment,
                                     self._constant(item.alignment, ''))
            if result.data:
                made.spans.append(Span(offset, len(result.data),
                                       item.where))
            data += result.data
            made.holes += [hole._replace(offset=hole.offset + offset,
                                         origin=offset)
                           for hole in result.holes]
        if made.initialised:
            made.data = bytes(data)
        elif any(data) or made.holes:
            self._error('the section %s has no bytes in the program, but '
                        'the source gives it some' % fragment.section,
                        fragment.where or ir.Where(self.unit.path, 0))
            made.holes = []
        return made

    def _symbols(self, result):
        self.names.memo = {}
        reported = {error.message for error in self.errors}
        for name in list(self.labels) + list(self.equates):
            self.names.position = None
            try:
                result.symbols[name] = self.names.symbol(name)
            except linear.LinearError as error:
                if str(error) not in reported:      # else: where used
                    number, index, _ = self.equates[name]
                    item = self.unit.fragments[number].items[index]
                    self._error(str(error), item.where)
        for declaration in self.unit.declarations:
            if declaration.directive not in EXPORTS:
                continue
            if declaration.name in result.symbols:
                result.exports.append(declaration.name)
            else:
                self._error('%s is exported and not defined'
                            % declaration.name, declaration.where)

    def _requires(self, result):
        """Gives each .require to its fragment. The IR keeps the
        declarations apart from the fragments, so the fragment is found
        by the place: the last .section line of the same file before
        the directive, else the first fragment."""
        for declaration in self.unit.declarations:
            if declaration.directive != 'require':
                continue
            before = [
                fragment for fragment in result.fragments
                if fragment.where is not None
                and fragment.where.file == declaration.where.file
                and fragment.where.line <= declaration.where.line]
            chosen = max(before, key=lambda fragment: fragment.where.line,
                         default=result.fragments[0])
            chosen.requires.append(declaration.name)


def assemble(unit, name):
    """The ObjectFile of `unit` (ir.Unit). `name` names the unit in the
    keys of its fragments; it must be unique in the link."""
    return _Assembler(unit, name).run()
