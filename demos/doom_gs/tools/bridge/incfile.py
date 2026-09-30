"""Upstream's include files: the `.equ` constants, in file order.

A small parser of its own for the lines `NAME .equ EXPRESSION` of
upstream's `src/iigs/*.inc` (offsets.inc, memmap.inc, info.inc, lists.inc
and the rest), with the expressions those files use: numbers (decimal,
`0x` hexadecimal, `'c'` characters), names defined earlier in the same
file or given by the caller, `+ - * / % << >> & | ^ ~` and parentheses.
Lines inside `#if`/`#endif` are read as they come (the files use the
guards only to be included once).

Nothing is copied: the bridge reads the files in build/upstream at run
time. tests/test_bridge.py checks every value against build/linkmap.json,
whose values come from our own assembler (tools/v816).
"""

import re
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

EQU = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s+\.equ\s+(.+?)\s*(;.*)?$')


class Constant(NamedTuple):
    name: str
    value: int
    line: int
    text: str           # the expression as written


class IncError(ValueError):
    pass


TOKEN = re.compile(r"\s*(0x[0-9A-Fa-f]+|\d+|'.'|[A-Za-z_][A-Za-z0-9_]*|"
                   r"<<|>>|[-+*/%&|^~()])")


def evaluate(text: str, names: Dict[str, int]) -> int:
    """The value of an expression of the include files."""
    tokens = []
    at = 0
    text = text.strip()
    while at < len(text):
        m = TOKEN.match(text, at)
        if not m:
            raise IncError('cannot read %r at %r' % (text, text[at:]))
        tokens.append(m.group(1))
        at = m.end()
    pos = [0]

    def peek() -> Optional[str]:
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def take() -> str:
        t = peek()
        if t is None:
            raise IncError('%r ends too soon' % text)
        pos[0] += 1
        return t

    def primary() -> int:
        t = take()
        if t == '(':
            v = binary(0)
            if take() != ')':
                raise IncError('%r: ) missing' % text)
            return v
        if t == '-':
            return -primary()
        if t == '+':
            return primary()
        if t == '~':
            return ~primary()
        if t.startswith("'"):
            return ord(t[1])
        if t[0].isdigit():
            return int(t, 0)
        if t in names:
            return names[t]
        raise IncError('%r: %s is not defined' % (text, t))

    levels = [('|',), ('^',), ('&',), ('<<', '>>'), ('+', '-'),
              ('*', '/', '%')]

    def binary(level: int) -> int:
        if level == len(levels):
            return primary()
        v = binary(level + 1)
        while peek() in levels[level]:
            op = take()
            w = binary(level + 1)
            if op == '|':
                v |= w
            elif op == '^':
                v ^= w
            elif op == '&':
                v &= w
            elif op == '<<':
                v <<= w
            elif op == '>>':
                v >>= w
            elif op == '+':
                v += w
            elif op == '-':
                v -= w
            elif op == '*':
                v *= w
            elif op == '/':
                v = int(v / w)
            else:
                v = v - int(v / w) * w
        return v

    value = binary(0)
    if peek() is not None:
        raise IncError('%r: %r left over' % (text, peek()))
    return value


def parse(path: Path, given: Optional[Dict[str, int]] = None
          ) -> List[Constant]:
    """The constants of one include file, in order. `given` are names
    defined elsewhere (another include) that its expressions may use."""
    names = dict(given or {})
    out = []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        m = EQU.match(line.strip())
        if not m:
            continue
        name, expr = m.group(1), m.group(2)
        value = evaluate(expr, names)
        names[name] = value
        out.append(Constant(name, value, number, expr))
    return out


def as_dict(constants: List[Constant]) -> Dict[str, int]:
    return {c.name: c.value for c in constants}
