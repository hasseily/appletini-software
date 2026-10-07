"""Dump streams of ref816 (--dump-at, --dump-stream): reading them, and
points written with the game's symbols.

A point (tools/ref816/points.h) is KEY=VALUE items: pc=ADDR, frame=SET or
cycle=SET first, then hits=SET, after=NOTE, if=ADDR:SIZE:TEST:VALUE and
ranges=R+R... `resolve` turns the symbols of the link map in a point into
the hex addresses the machine takes: pc=G_Ticker, if=_g_gametic:4:ge:100,
ranges=_g_player:155. A symbol is a name, or unit:name, as the scripts
write them (script.Symbols), with +offset.

A stream is a line of JSON, {"format": "ref816-dump-stream 1", "points":
[...]}; then for each dump a line of JSON followed by its bytes (the
header's "bytes"); then {"end": REASON, "dumps": N}. `read` yields the
dumps; `Stream` also keeps the first and last lines.
"""

import json
import re
import sys
from pathlib import Path
from typing import BinaryIO, Dict, Iterator, NamedTuple, Optional, Union

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import make_image, script  # noqa: E402

FORMAT = 'ref816-dump-stream 1'
BANKS = re.compile(r'[0-9A-Fa-f]{1,2}(-[0-9A-Fa-f]{1,2})?$')


class Dump(NamedTuple):
    header: Dict
    data: bytes


class Stream:
    """A whole stream read from a file: its first line (`info`), its
    dumps and its last line (`end`)."""

    def __init__(self, source: Union[str, Path, BinaryIO]):
        self.info: Dict = {}
        self.end: Optional[Dict] = None
        self.dumps = list(read(source, self))


def read(source: Union[str, Path, BinaryIO],
         stream: Optional[Stream] = None) -> Iterator[Dump]:
    """The dumps of a stream, one at a time (a file, or a pipe)."""
    handle = open(str(source), 'rb') if isinstance(source, (str, Path)) \
        else source
    try:
        first = json.loads(handle.readline())
        if first.get('format') != FORMAT:
            raise ValueError('not a ref816 dump stream')
        if stream is not None:
            stream.info = first
        while True:
            line = handle.readline()
            if not line:
                raise ValueError('the stream ends without its end line')
            header = json.loads(line)
            if 'end' in header:
                if stream is not None:
                    stream.end = header
                return
            data = handle.read(header['bytes'])
            if len(data) != header['bytes']:
                raise ValueError('dump %d is cut short' % header['dump'])
            yield Dump(header, data)
    finally:
        if handle is not source:
            handle.close()


# ---- points with symbols ----

def _address(symbols: script.Symbols, text: str) -> str:
    """A hex address, or a symbol (with +offset) as hex."""
    if re.match(r'[0-9A-Fa-f]{1,6}$', text):
        return text.upper()
    return '%06X' % symbols.address(text)


def resolve(text: str, symbols: script.Symbols) -> str:
    """The point `text` with the symbols of pc=, if= and ranges= as hex
    addresses (a hex address stays as it is)."""
    items = []
    for item in text.split(','):
        key, equals, value = item.partition('=')
        if equals and key == 'pc':
            value = _address(symbols, value)
        elif equals and key == 'if':
            where, colon, rest = value.partition(':')
            value = _address(symbols, where) + colon + rest
        elif equals and key == 'ranges':
            parts, pending = [], ''
            for part in value.split('+'):
                # "symbol+offset:LEN" was split at its own +
                part = pending + part
                pending = ''
                where, colon, rest = part.partition(':')
                if not colon and not BANKS.match(part):
                    pending = part + '+'
                    continue
                parts.append(_address(symbols, where) + colon + rest
                             if colon else part)
            if pending:
                raise ValueError('ranges: %s has no length' % pending[:-1])
            value = '+'.join(parts)
        items.append(key + equals + value)
    return ','.join(items)


def symbols() -> script.Symbols:
    with open(str(make_image.LINKMAP)) as handle:
        return script.Symbols(json.load(handle))
