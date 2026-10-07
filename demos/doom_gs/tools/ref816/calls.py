"""Call logs of ref816 (--call-log, --call-log-file): routines written with
the game's symbols (options), and the log read back (read).

Each routine is ENTRY[,KEY=VALUE...] as ref816 takes it
(tools/ref816/calllog.h), where ENTRY and the addresses of the ranges may
be symbols of the link map (a name, or unit:name, with +offset), and a
range may also be written dp:SYMBOL[+N]:LEN: the direct-page operand the
game's code writes as `dp:.tiny SYMBOL`, that is D plus SYMBOL's offset
from the base of the direct page (the section ztiny; tools/v816/expr.py).
So upstream's FixedMul (a in X:C, b in _Dp[0-3]; m_fixed65.s) is

    FixedMul,in=dp:_Dp:4

and its result is X:C of "out". The name defaults to ENTRY when that is a
symbol.

`read` returns a log's first line, its calls and its last line; each call
is the JSON object calllog.h describes, with "mem" as hex strings.
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import make_image, script  # noqa: E402

FORMAT = 'ref816-call-log 1'
DP_SECTION = 'ztiny'
RANGE_KEYS = ('in', 'out', 'mem')
HEX_ADDRESS = re.compile(r'[0-9A-Fa-f]{1,6}$')


class Linkmap:
    """The symbols of the link map and the base of the direct page."""

    def __init__(self, linkmap: Optional[Dict] = None):
        if linkmap is None:
            with open(str(make_image.LINKMAP)) as handle:
                linkmap = json.load(handle)
        self.symbols = script.Symbols(linkmap)
        self.direct_page = linkmap['game']['sections'][DP_SECTION]['first']

    def address(self, text: str) -> int:
        if HEX_ADDRESS.match(text):
            return int(text, 16)
        return self.symbols.address(text)


def _complete(part: str) -> bool:
    """Whether a part of a list of ranges has its :LEN."""
    return part.count(':') >= (2 if part.startswith('dp:') else 1)


def _ranges(value: str, table: Linkmap) -> str:
    out: List[str] = []
    part = ''
    for piece in value.split('+'):
        # d+OFF:LEN, s+OFF:LEN and a symbol with +offset have a + of
        # their own: join the pieces until the range has its :LEN.
        part = part + '+' + piece if part else piece
        if not _complete(part):
            continue
        if part.startswith('dp:'):
            where, _, length = part[3:].rpartition(':')
            offset = table.address(where) - table.direct_page
            if not 0 <= offset <= 0xffff:
                raise ValueError('%s is not in the direct page' % where)
            out.append('d+%X:%s' % (offset, length))
        elif part.startswith(('d+', 's+')):
            out.append(part)
        else:
            where, _, length = part.rpartition(':')
            out.append('%06X:%s' % (table.address(where), length))
        part = ''
    if part:
        raise ValueError('the range %s has no :LEN' % part)
    return '+'.join(out)


def resolve(text: str, table: Linkmap) -> str:
    """The routine `text` with its symbols as hex addresses."""
    entry, _, rest = text.partition(',')
    items = ['%06X' % table.address(entry)]
    named = False
    for item in rest.split(',') if rest else []:
        key, equals, value = item.partition('=')
        if key in RANGE_KEYS and equals:
            value = _ranges(value, table)
        elif key == 'if' and equals:
            where, colon, tail = value.partition(':')
            value = '%06X' % table.address(where) + colon + tail
        named = named or key == 'name'
        items.append(key + equals + value)
    if not named and not HEX_ADDRESS.match(entry):
        items.append('name=' + entry.replace('"', '').replace('\\', ''))
    return ','.join(items)


def options(routines: Sequence[str], path: Path,
            table: Optional[Linkmap] = None) -> List[str]:
    """The machine's options that log `routines` into `path`."""
    table = table or Linkmap()
    result = ['--call-log-file', str(path)]
    for routine in routines:
        result += ['--call-log', resolve(routine, table)]
    return result


def read(path: Path) -> Tuple[Dict, List[Dict], Dict]:
    """The first line, the calls and the last line of a log."""
    lines = path.read_text().splitlines()
    head = json.loads(lines[0])
    if head.get('format') != FORMAT:
        raise ValueError('%s is not a ref816 call log' % path)
    end = json.loads(lines[-1])
    if not end.get('end'):
        raise ValueError('%s ends without its last line' % path)
    return head, [json.loads(line) for line in lines[1:-1]], end
