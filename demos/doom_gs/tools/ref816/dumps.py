#!/usr/bin/env python3
"""Dump streams of ref816 (--dump-at, --dump-stream): reading them, points
written with the game's symbols, and the check of milestone 6 against
the two-run method.

Usage:  python3 tools/ref816/dumps.py --verify [--out DIR]

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

--verify redoes the six captures of docs/research/native-verification.md
section 3.1 both ways and compares them. The two-run method: a first run
logs the entries of G_Ticker and R_DrawLists (--mark), and for each
capture a second run stops at the CPU cycle count of the first entry
after the note "cap" (--cycles) and dumps all RAM (--dump-ram). The
stream: one run of each script with --dump-at pc=ROUTINE,after=cap,hits=1
for both routines. For each capture the dump of the stream must be
byte for byte the file of --dump-ram, with the registers, cycles and
instructions of the second run's final state. The scripts are the
coverage scripts cut after a point with a note "cap", as that section's
helper cut them (SCRIPTS). Exit status 0 when all six are equal.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO, Dict, Iterator, List, NamedTuple, Optional, \
    Sequence, Tuple, Union

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import bounded, make_image, marks, run_script, script, \
    title  # noqa: E402

FORMAT = 'ref816-dump-stream 1'
OUT = make_image.OUT_DIR / 'dumps'
ROUTINES = ('G_Ticker', 'R_DrawLists')
# The captures of native-verification.md section 3.1: a coverage script,
# the line after which it is cut, and what follows the cut.
SCRIPTS = {
    'e1m1': ('newgame.script', 'note still',
             'at +5s note cap\nat +2s stop\n'),
    'demo': ('title.script', 'note demo',
             'at +10s note cap\nat +2s stop\n'),
    'e1m3': ('tour.script', 'at +3s shot e1m3',
             'at +2s note cap\nat +2s stop\n'),
}
LIMIT_SECONDS = 900
BANKS = re.compile(r'[0-9A-Fa-f]{1,2}(-[0-9A-Fa-f]{1,2})?$')


class Dump(NamedTuple):
    header: Dict
    data: bytes

    def ranges(self) -> List[Tuple[int, int]]:
        return [tuple(r) for r in self.header['ranges']]

    def get(self, address: int, length: int) -> bytes:
        """`length` bytes from `address`, which the dump must hold."""
        at = 0
        for start, size in self.ranges():
            if start <= address and address + length <= start + size:
                offset = at + address - start
                return self.data[offset:offset + length]
            at += size
        raise KeyError('$%06X+%d is not in the dump' % (address, length))


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


# ---- the check against the two-run method ----

def cut_script(name: str) -> str:
    """The coverage script of capture `name`, cut after its line and
    followed by the note "cap" and a stop (SCRIPTS)."""
    source, anchor, tail = SCRIPTS[name]
    text = (run_script.COVERAGE / source).read_text()
    head, found, rest = text.partition(anchor)
    if not found:
        raise ValueError('no %r in %s' % (anchor, source))
    return head + anchor + rest[:rest.find('\n') + 1] + tail


def machine(options: Sequence[str], shots: Path,
            machine_path: Path = title.MACHINE) -> None:
    """Run the release with `options`; the script's shots go to `shots`."""
    shots.mkdir(parents=True, exist_ok=True)
    command = [str(machine_path), str(title.MEMORY), '--disk',
               str(title.DISK), '--shot-dir', str(shots)] + \
        [str(o) for o in options]
    # bounded (the ground rules): a wall-time limit, and no file past
    # 1 GiB (the streams here hold two dumps of 8.5 MB)
    try:
        result = bounded.run(command, timeout=bounded.TOOL_TIMEOUT,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise RuntimeError('ref816 did not finish in %d s'
                           % bounded.TOOL_TIMEOUT)
    if result.returncode:
        raise RuntimeError('ref816 failed: ' + result.stderr)


class Capture(NamedTuple):
    name: str           # e1m1-G_Ticker ...
    cycles: int
    instructions: int
    pc: int
    at_entry: bool
    equal: bool         # the stream's dump equals the two-run method's
    differing: int      # bytes that differ
    registers_equal: bool


def verify(name: str, out: Path) -> List[Capture]:
    """Both methods for the captures of script `name`."""
    out.mkdir(parents=True, exist_ok=True)
    table = symbols()
    program = script.compile_script(cut_script(name), table, name)
    program_path = out / (name + '-input.txt')
    program_path.write_text(program)
    frames = str(script.frames(LIMIT_SECONDS))
    addresses = {r: table.address(r) for r in ROUTINES}

    # The two-run method: the marks, then a run to each entry.
    marks_path = out / (name + '-marks.txt')
    options = ['--input', program_path, '--frames', frames, '--marks',
               marks_path, '--state', out / (name + '-marks.json')]
    for address in addresses.values():
        options += ['--mark', '%06X' % address]
    machine(options, out / (name + '-shots'))
    log = marks.read(marks_path)
    cap = [e for e in log if e.kind == 'note' and e.what == 'cap'][0]

    # The stream: one run.
    stream_path = out / (name + '.stream')
    options = ['--input', program_path, '--frames', frames,
               '--dump-stream', stream_path, '--dump-max', len(ROUTINES),
               '--state', out / (name + '-stream.json')]
    for routine in ROUTINES:
        options += ['--dump-at', resolve('pc=%s,after=cap,hits=1' % routine,
                                         table)]
    machine(options, out / (name + '-shots'))
    stream = Stream(stream_path)
    if len(stream.dumps) != len(ROUTINES):
        raise RuntimeError('%s: %d dumps in the stream, not %d'
                           % (name, len(stream.dumps), len(ROUTINES)))

    results = []
    for index, (routine, address) in enumerate(addresses.items()):
        entry = [e for e in log if e.kind == 'mark' and
                 int(e.what, 16) == address and e.cycles > cap.cycles][0]
        stem = out / ('%s-%s' % (name, routine))
        ram = stem.with_suffix('.ram')
        state_path = stem.with_suffix('.json')
        machine(['--input', program_path, '--cycles', entry.cycles,
                 '--frames', frames, '--dump-ram', ram,
                 '--state', state_path], out / (name + '-shots'))
        state = json.loads(state_path.read_text())
        dump = [d for d in stream.dumps if d.header['point'] == index][0]
        two_run = ram.read_bytes()
        differing = 0 if two_run == dump.data else \
            sum(a != b for a, b in zip(two_run, dump.data)) + \
            abs(len(two_run) - len(dump.data))
        registers = {k: v for k, v in state['cpu'].items() if k != 'state'}
        results.append(Capture(
            name='%s-%s' % (name, routine), cycles=state['cycles'],
            instructions=state['instructions'], pc=state['cpu']['pc'],
            at_entry=state['cpu']['pc'] == address,
            equal=differing == 0 and dump.header['cycles'] ==
            state['cycles'] and dump.header['instructions'] ==
            state['instructions'] and dump.header['frame'] ==
            state['frames'],
            differing=differing,
            registers_equal=dump.header['cpu'] == registers))
        ram.unlink()
    stream_path.unlink()
    return results


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--verify', action='store_true', required=True)
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('names', nargs='*', default=sorted(SCRIPTS))
    arguments = parser.parse_args(argv)
    title.build_machine()
    title.ensure_image()
    ok = True
    for name in arguments.names:
        for c in verify(name, arguments.out):
            good = c.equal and c.registers_equal and c.at_entry
            ok = ok and good
            print('%-16s cycles %11d instructions %10d pc %06X  %s'
                  % (c.name, c.cycles, c.instructions, c.pc,
                     'equal' if good else
                     'DIFFERENT (%d bytes, registers %s, at entry %s)'
                     % (c.differing, c.registers_equal, c.at_entry)))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
