#!/usr/bin/env python3
"""Call logs of ref816 (--call-log, --call-log-file): routines written with
the game's symbols, the log read back, and a command that logs routines
through a script.

Usage:  python3 tools/ref816/calls.py RUN ROUTINE... [--out FILE]

Each ROUTINE is ENTRY[,KEY=VALUE...] as ref816 takes it
(tools/ref816/calllog.h), where ENTRY and the addresses of the ranges may
be symbols of the link map (a name, or unit:name, with +offset), and a
range may also be written dp:SYMBOL[+N]:LEN: the direct-page operand the
game's code writes as `dp:.tiny SYMBOL`, that is D plus SYMBOL's offset
from the base of the direct page (the section ztiny; tools/v816/expr.py).
So upstream's FixedMul (a in X:C, b in _Dp[0-3]; m_fixed65.s) is

    FixedMul,in=dp:_Dp:4

and its result is X:C of "out". The name defaults to ENTRY when that is a
symbol. RUN is a coverage script (or a path), or DEMO1, DEMO2 or DEMO3:
the title loop to the end of that demo (lumps.py; DEMO1 and DEMO2 placed
as DEMO3). The log goes to FILE (default build/ref816/calls/RUN.log).

`read` returns a log's first line, its calls and its last line; each call
is the JSON object calllog.h describes, with "mem" as hex strings; `Call`
wraps one with its registers and memory as numbers and bytes.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Optional, Sequence, \
    Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import lumps, make_image, run_script, script, title  # noqa: E402

FORMAT = 'ref816-call-log 1'
OUT = make_image.OUT_DIR / 'calls'
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


class Call(NamedTuple):
    """A call of a log: its routine's name and its line, with the memory
    of in and out as bytes."""
    name: str
    line: Dict
    memory_in: List[bytes]
    memory_out: List[bytes]

    @property
    def registers_in(self) -> Dict[str, int]:
        return {k: v for k, v in self.line['in'].items() if k != 'mem'}

    @property
    def registers_out(self) -> Optional[Dict[str, int]]:
        out = self.line['out']
        return None if out is None else \
            {k: v for k, v in out.items() if k != 'mem'}


def calls(path: Path) -> Iterator[Call]:
    head, lines, _ = read(path)
    names = [r['name'] for r in head['routines']]
    for line in lines:
        out = line['out']
        yield Call(names[line['routine']], line,
                   [bytes.fromhex(m) for m in line['in']['mem']],
                   [bytes.fromhex(m) for m in out['mem']] if out else [])


DEMOS = ('DEMO1', 'DEMO2', 'DEMO3')


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run')
    parser.add_argument('routines', nargs='+')
    parser.add_argument('--out', type=Path)
    arguments = parser.parse_args(argv)
    title.build_machine()
    title.ensure_image()
    table = Linkmap()
    demo = arguments.run if arguments.run in DEMOS else None
    name = demo.lower() if demo else Path(arguments.run).stem
    out = arguments.out or OUT / (name + '.log')
    out.parent.mkdir(parents=True, exist_ok=True)
    extra = options(arguments.routines, out, table)
    limit = run_script.DEFAULT_LIMIT_SECONDS
    if demo:
        info = lumps.demo_info(lumps.read_wad()[demo])
        path = OUT / (name + '.script')
        path.write_text(lumps.demo_script(info['map']))
        if demo != 'DEMO3':
            extra += lumps.options(demo, table.symbols, out=OUT)
        limit = 3120
    else:
        path = run_script.script_path(arguments.run)
    report = run_script.run(path, limit_seconds=limit, extra=extra,
                            name='calls-' + name)
    print(run_script.summary(report))
    _, lines, end = read(out)
    print('%s: %d calls logged; arrivals %s' % (out, len(lines),
                                               end['arrivals']))
    return 1 if report['problems'] else 0


if __name__ == '__main__':
    sys.exit(main())
