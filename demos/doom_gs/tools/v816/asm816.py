"""The 65816 instruction encoder.

encode() takes an instruction of the IR, the Value of its operand
(tools/v816/linear.py) and the address of the instruction, and gives
the bytes. Where the assembler cannot know a byte, the bytes have a
Hole: the place, the width, the value as an expression and its kind.
The linker (tools/v816/link.py) fills the holes.

How the size of an operand is chosen (manual, 21.3):

1. "#" is an 8-bit immediate and "##" a 16-bit one. The assembler does
   not follow the M and X flags. Instructions whose immediate has one
   size (rep, sep, pea) take that size with either mark.
2. dp:, abs: and long: give the size.
3. Without a prefix, an operand with .near or .kbank has 16 bits and
   one with .tiny has 8 bits. The byte and word operators say nothing
   about the size of an address, so they need a prefix here.
4. Without either, an operand that is a constant takes the shortest
   size that holds it and that the instruction has.
5. Any other operand, one that depends on the placement, takes 16 bits,
   or the one size that the instruction has.

What the release image proves. The built image equals the release
(tools/v816/imgmatch.py), which confirms rules 1 and 2, and rule 3 for
.near and .kbank. Upstream's sources give a prefix or an operator to
nearly every address, so the image says nothing about the rest: .tiny
without a prefix, a constant without a prefix and an operand of rule 5
occur only in instructions that have one size for the operand as
written (stack relative, indirect through the direct page, jmp
(abs)). Rules 4 and 5 are the examples of the manual; 8 bits for .tiny
is an assumption.

A branch to a place in the fragment of the branch is resolved at once,
because the distance does not depend on the placement.
"""

from typing import NamedTuple

from . import linear
from .opcodes import OPCODES, OPERAND_SIZES, immediate_sizes

# Kinds of hole: how the value becomes bytes.
KIND_DATA = 'data'          # .byte .word .address .long .quad
KIND_IMMEDIATE = 'imm'
KIND_DIRECT = 'dp'
KIND_ABSOLUTE = 'abs'
KIND_LONG = 'long'
KIND_BRANCH = 'rel'         # the value is the distance
ADDRESS_KINDS = {1: KIND_DIRECT, 2: KIND_ABSOLUTE, 3: KIND_LONG}

# The modes that each way of writing an operand can stand for, by the
# size of the address in bytes.
_SHAPES = {
    'e': {1: 'dp', 2: 'abs', 3: 'long'},
    'e,x': {1: 'dp,x', 2: 'abs,x', 3: 'long,x'},
    'e,y': {1: 'dp,y', 2: 'abs,y'},
    'e,s': {1: 'sr,s'},
    '(e)': {1: '(dp)', 2: '(abs)'},
    '(e,x)': {1: '(dp,x)', 2: '(abs,x)'},
    '(e),y': {1: '(dp),y'},
    '(e,s),y': {1: '(sr,s),y'},
    '[e]': {1: '[dp]', 2: '[abs]'},
    '[e],y': {1: '[dp],y'},
}
# The sources write the operand of pei, which is the address of a
# pointer in the direct page, without brackets.
_SHAPE_ALIASES = {('pei', 'e'): '(e)'}
_PREFIX_SIZES = {'dp': 1, 'abs': 2, 'long': 3}
_RELOC_SIZES = {'tiny': 1, 'near': 2, 'kbank': 2}
_DEFAULT_SIZE = 2


class EncodeError(ValueError):
    """The instruction cannot be encoded."""


class Hole(NamedTuple):
    """Bytes that the linker fills.

    offset  of the first byte, from the start of the encoded item (the
            assembler of a unit makes it an offset in the fragment)
    width   in bytes
    value   the linear.Value that belongs there; for a branch, the
            distance from the end of the instruction to the target
    kind    one of the KIND_ constants
    origin  offset of the instruction or datum that the hole is part
            of: the location counter, which .kbank needs
    """
    offset: int
    width: int
    value: linear.Value
    kind: str
    origin: int = 0


class Encoded(NamedTuple):
    """The bytes of an item; the bytes of each hole are 0."""
    data: bytes
    holes: tuple = ()


def little_endian(number, width):
    """`number` in `width` bytes, the low byte first; a negative number
    in two's complement."""
    return (number & (1 << 8 * width) - 1).to_bytes(width, 'little')


def fits(number, width, signed_too=True):
    """True when `number` can be the value of `width` bytes: as an
    unsigned number or, with `signed_too`, as a signed one."""
    low = -(1 << 8 * width - 1) if signed_too else 0
    return low <= number < 1 << 8 * width


def field(value, width, kind, offset, what):
    """The Encoded of one value of `width` bytes at `offset` of an
    item: the bytes when the value is a constant, else a hole."""
    if value.is_constant:
        number = value.linear.constant
        if not fits(number, width):
            raise EncodeError('%s: %d does not fit in %d bits'
                              % (what, number, 8 * width))
        return Encoded(little_endian(number, width))
    return Encoded(bytes(width), (Hole(offset, width, value, kind),))


def address_sizes(mnemonic, written):
    """The forms that `mnemonic` has for an address written as
    `written` (a mode of the IR): a dictionary from the size of the
    address in bytes to the mode of tools/v816/opcodes.py."""
    shape = _SHAPES[_SHAPE_ALIASES.get((mnemonic, written), written)]
    return {size: mode for size, mode in shape.items()
            if mode in OPCODES[mnemonic]}


def _address_size(instruction, value, sizes):
    """The size in bytes of the address of `instruction`; `sizes` are
    the sizes that the instruction has for the operand as written."""
    if instruction.prefix:
        wanted = _PREFIX_SIZES[instruction.prefix]
    elif value.reloc:
        if value.reloc not in _RELOC_SIZES:
            raise EncodeError('%s: an address with .%s needs dp:, abs: or '
                              'long:' % (instruction.mnemonic, value.reloc))
        wanted = _RELOC_SIZES[value.reloc]
    elif value.is_constant:
        number = value.linear.constant
        fitting = [size for size in sizes
                   if fits(number, size, signed_too=False)]
        if not fitting:
            raise EncodeError('%s: the address %d does not fit'
                              % (instruction.mnemonic, number))
        return min(fitting)
    elif _DEFAULT_SIZE in sizes or len(sizes) > 1:
        wanted = _DEFAULT_SIZE
    else:
        wanted = sizes[0]
    if wanted not in sizes:
        raise EncodeError('%s has no %d-bit form of the operand "%s"'
                          % (instruction.mnemonic, 8 * wanted,
                             instruction.mode))
    return wanted


def _immediate(instruction, value):
    modes = OPCODES[instruction.mnemonic]
    if 'imm' not in modes:
        raise EncodeError('%s has no immediate operand'
                          % instruction.mnemonic)
    sizes = immediate_sizes(instruction.mnemonic)
    width = len(instruction.mode)           # "#" 1 byte, "##" 2 bytes
    if len(sizes) == 1:
        width = sizes[0]
    operand = field(value, width, KIND_IMMEDIATE, 1,
                    '%s %s' % (instruction.mnemonic, instruction.mode))
    return Encoded(bytes([modes['imm']]) + operand.data, operand.holes)


def _branch(instruction, value, position, mode):
    if instruction.mode != 'e' or instruction.prefix or value.reloc:
        raise EncodeError('%s needs a plain target'
                          % instruction.mnemonic)
    width = OPERAND_SIZES[mode]
    after = position.plus(linear.Linear(1 + width))
    distance = linear.Value(None, value.linear.plus(after, -1))
    opcode = bytes([OPCODES[instruction.mnemonic][mode]])
    if not distance.is_constant:
        return Encoded(opcode + bytes(width),
                       (Hole(1, width, distance, KIND_BRANCH),))
    number = distance.linear.constant
    if not -(1 << 8 * width - 1) <= number < 1 << 8 * width - 1:
        raise EncodeError('%s: the target is %d bytes away'
                          % (instruction.mnemonic, number))
    return Encoded(opcode + little_endian(number, width))


def encode(instruction, value, position):
    """The Encoded of `instruction` (ir.Instruction).

    `value` is the linear.Value of the operand, None when there is
    none. `position` is the address of the instruction as a Linear; a
    branch needs it.
    """
    modes = OPCODES.get(instruction.mnemonic)
    if modes is None:
        raise EncodeError('unknown instruction %s' % instruction.mnemonic)
    if 'move' in modes:
        raise EncodeError('%s: block moves are not implemented; the '
                          'sources write them as .byte'
                          % instruction.mnemonic)
    if instruction.mode in ('', 'a'):
        mode = 'acc' if instruction.mode == 'a' else 'imp'
        if mode not in modes:
            raise EncodeError('%s needs an operand' % instruction.mnemonic)
        return Encoded(bytes([modes[mode]]))
    if instruction.mode in ('#', '##'):
        return _immediate(instruction, value)
    for mode in ('rel8', 'rel16'):
        if mode in modes:
            return _branch(instruction, value, position, mode)
    sizes = address_sizes(instruction.mnemonic, instruction.mode)
    if not sizes:
        raise EncodeError('%s has no operand of the form "%s"'
                          % (instruction.mnemonic, instruction.mode))
    size = _address_size(instruction, value, sorted(sizes))
    operand = field(value, size, ADDRESS_KINDS[size], 1,
                    '%s %s' % (instruction.mnemonic, instruction.mode))
    return Encoded(bytes([modes[sizes[size]]]) + operand.data,
                   operand.holes)
