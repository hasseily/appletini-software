"""Field types and structures of the bridge's schema.

A structure (`Struct`) is a list of fields that tile its size exactly:
every byte of a record belongs to one field. A field has a type:

    Int(size, signed)   a number of 1, 2 or 4 bytes, little-endian
    Ref(targets)        a far pointer to one of the object kinds `targets`
    Fn()                a thinker function: 24 bits
    Array(elem, n)      n values of a type
    Sub(struct)         a structure inside a structure
    Raw(size)           bytes that are not numbers or pointers (names)

and a class: state, cache, list (a link of a list), thinker (the thinker
header) or kindcache.
"""

from typing import Any, Dict, NamedTuple, Sequence, Tuple


class Int(NamedTuple):
    size: int
    signed: bool

    @property
    def length(self) -> int:
        return self.size


class Ref(NamedTuple):
    targets: Tuple[str, ...]

    @property
    def length(self) -> int:
        return 4


class Fn(NamedTuple):
    @property
    def length(self) -> int:
        return 3


class Raw(NamedTuple):
    size: int

    @property
    def length(self) -> int:
        return self.size


class Array(NamedTuple):
    elem: Any
    count: int

    @property
    def length(self) -> int:
        return self.elem.length * self.count


class Sub(NamedTuple):
    struct: Any

    @property
    def length(self) -> int:
        return self.struct.size


I8, U8 = Int(1, True), Int(1, False)
I16, U16 = Int(2, True), Int(2, False)
I32, U32 = Int(4, True), Int(4, False)
FIXED = I32
ANGLE = U32


def spec(text: str, targets: Dict[str, Tuple[str, ...]] = None):
    """A type from a short spec: i8 u8 i16 u16 i32 u32 fixed angle, raw:N,
    ref:K1|K2, fn, with *N for arrays (`i16*6`)."""
    base, star, count = text.partition('*')
    if base.startswith('ref:'):
        t = Ref(tuple(base[4:].split('|')))
    elif base.startswith('raw:'):
        t = Raw(int(base[4:]))
    elif base == 'fn':
        t = Fn()
    else:
        t = {'i8': I8, 'u8': U8, 'i16': I16, 'u16': U16, 'i32': I32,
             'u32': U32, 'fixed': FIXED, 'angle': ANGLE}[base]
    return Array(t, int(count)) if star else t


class Field(NamedTuple):
    name: str
    offset: int
    type: Any
    cls: str = 'state'

    @property
    def end(self) -> int:
        return self.offset + self.type.length


class StructError(ValueError):
    pass


class Struct:
    def __init__(self, name: str, size: int, fields: Sequence[Field]):
        self.name = name
        self.size = size
        self.fields = list(fields)
        at = 0
        for f in self.fields:
            if f.offset != at:
                raise StructError('%s: %s at %d, expected %d'
                                  % (name, f.name, f.offset, at))
            at = f.end
        if at != size:
            raise StructError('%s: fields end at %d, size %d'
                              % (name, at, size))
