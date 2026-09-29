"""Read the trace files of ref816 (--trace; the format is in
tools/ref816/trace.h).

A trace has a header (the phases, their entry addresses, the near banks,
the stack split), the notes of the input, the frames of the game it
recorded, and what covers the whole run: the writes to code, the entries
reached by a jump, and the widths every instruction ran with.
"""

from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

SPACES = ('program', 'direct', 'stack', 'data', 'io', 'vector')
WIDTH_KINDS = ('mx', 'd', 'dbr')
OTHER, INTERRUPT = 0, 1


class Counts(NamedTuple):
    clock: int          # master clocks
    cycles: int
    instructions: int


class Frame:
    """One frame of the game: what each phase did in it."""

    def __init__(self, index: int, start: Counts, end: Counts):
        self.index = index
        self.start = start
        self.end = end
        self.cost: Dict[int, Tuple[int, int]] = {}      # instructions, cycles
        self.enters: Dict[int, int] = {}    # calls of an entry, interrupts
        # The machine's firmware traps: calls, and the cycles they charge
        # with no instruction, which no phase has.
        self.firmware: Tuple[int, int] = (0, 0)
        # (phase, space, bank): (reads, writes)
        self.access: Dict[Tuple[int, str, int], Tuple[int, int]] = {}
        # bank: touched 8, 64, 256; written 8, 64, 256
        self.lines: Dict[int, Tuple[int, ...]] = {}
        self.switches: Dict[int, int] = {}
        # phase: lowest S above the split, at or below it (None: none)
        self.stack: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
        # phase: direct, shadowed, changed
        self.screen: Dict[int, Tuple[int, int, int]] = {}
        # (phase, address): (count, length)
        self.heat: Dict[Tuple[int, int], Tuple[int, int]] = {}
        # (phase, opcode, mx): instructions, mx = E << 2 | M << 1 | X
        self.ops: Dict[Tuple[int, int, int], int] = {}
        # phase: program fetches that entered another page, and those
        # the model of the interpreter's code cache missed
        self.code: Dict[int, Tuple[int, int]] = {}
        self.unclosed = 0

    @property
    def instructions(self) -> int:
        return self.end.instructions - self.start.instructions

    @property
    def cycles(self) -> int:
        return self.end.cycles - self.start.cycles


class Smc(NamedTuple):
    frame: int
    writer: int
    target: int
    count: int


class Trace:
    def __init__(self) -> None:
        self.phases: List[str] = []
        self.entries: Dict[int, int] = {}       # address: phase
        self.near: Set[int] = set()
        self.split = 0
        self.notes: List[Tuple[str, Counts]] = []
        self.frames: List[Frame] = []
        self.smc: List[Smc] = []
        self.smc_mixed = 0
        self.jumps: Dict[int, int] = {}
        # address: {'mx': {values}, 'd': {...}, 'dbr': {...}}
        self.widths: Dict[int, Dict[str, Set[int]]] = {}
        self.end: Optional[Counts] = None

    def phase(self, name: str) -> int:
        return self.phases.index(name)


def _stack(word: str) -> Optional[int]:
    return None if word == '-' else int(word, 16)


def parse(text: str) -> Trace:
    """The trace in `text`; ValueError for a line that is not one of the
    format's, or a trace cut short (no end line)."""
    lines = text.splitlines()
    if not lines or lines[0] != 'ref816-trace 1':
        raise ValueError('not a ref816 trace (version 1)')
    trace = Trace()
    frame: Optional[Frame] = None
    for number, line in enumerate(lines[1:], 2):
        words = line.split()
        try:
            kind, args = words[0], words[1:]
            if kind == 'phase':
                if int(args[0]) != len(trace.phases):
                    raise ValueError('phases out of order')
                trace.phases.append(args[1])
            elif kind == 'entry':
                trace.entries[int(args[0], 16)] = int(args[1])
            elif kind == 'near':
                trace.near.add(int(args[0], 16))
            elif kind == 'split':
                trace.split = int(args[0], 16)
            elif kind == 'note':
                trace.notes.append((args[0], Counts(*map(int, args[1:4]))))
            elif kind == 'frame':
                numbers = [int(word) for word in args]
                frame = Frame(numbers[0], Counts(*numbers[1:4]),
                              Counts(*numbers[4:7]))
                trace.frames.append(frame)
            elif kind in ('cost', 'enters', 'firmware', 'access', 'lines',
                          'switches', 'stack', 'screen', 'heat', 'op',
                          'code', 'unclosed'):
                if frame is None:
                    raise ValueError('%s before any frame' % kind)
                _frame_line(frame, kind, args)
            elif kind == 'smc':
                trace.smc.append(Smc(int(args[0]), int(args[1], 16),
                                     int(args[2], 16), int(args[3])))
            elif kind == 'smc-mixed':
                trace.smc_mixed = int(args[0])
            elif kind == 'jumps':
                trace.jumps[int(args[0])] = int(args[1])
            elif kind == 'width':
                if args[1] not in WIDTH_KINDS:
                    raise ValueError('no width kind %s' % args[1])
                kinds = trace.widths.setdefault(
                    int(args[0], 16), {k: set() for k in WIDTH_KINDS})
                kinds[args[1]].add(int(args[2], 16))
            elif kind == 'end':
                trace.end = Counts(*map(int, args[:3]))
            else:
                raise ValueError('unknown record')
        except (IndexError, ValueError) as error:
            raise ValueError('line %d of the trace: %s (%r)'
                             % (number, error, line)) from None
    if trace.end is None:
        raise ValueError('the trace has no end line: cut short?')
    return trace


def _frame_line(frame: Frame, kind: str, args: List[str]) -> None:
    if kind == 'cost':
        frame.cost[int(args[0])] = (int(args[1]), int(args[2]))
    elif kind == 'enters':
        frame.enters[int(args[0])] = int(args[1])
    elif kind == 'firmware':
        frame.firmware = (int(args[0]), int(args[1]))
    elif kind == 'access':
        if args[1] not in SPACES:
            raise ValueError('no space %s' % args[1])
        frame.access[(int(args[0]), args[1], int(args[2], 16))] = (
            int(args[3]), int(args[4]))
    elif kind == 'lines':
        if len(args) != 7:
            raise ValueError('lines has a bank and six counts')
        frame.lines[int(args[0], 16)] = tuple(int(w) for w in args[1:])
    elif kind == 'switches':
        frame.switches[int(args[0])] = int(args[1])
    elif kind == 'stack':
        frame.stack[int(args[0])] = (_stack(args[1]), _stack(args[2]))
    elif kind == 'screen':
        frame.screen[int(args[0])] = (int(args[1]), int(args[2]),
                                      int(args[3]))
    elif kind == 'heat':
        frame.heat[(int(args[0]), int(args[1], 16))] = (int(args[2]),
                                                        int(args[3]))
    elif kind == 'op':
        if len(args) != 4:
            raise ValueError('op has a phase, an opcode, widths and a count')
        opcode, mx = int(args[1], 16), int(args[2])
        if opcode > 0xff or mx > 7:
            raise ValueError('no opcode %s or widths %s' % (args[1], args[2]))
        frame.ops[(int(args[0]), opcode, mx)] = int(args[3])
    elif kind == 'code':
        if len(args) != 3:
            raise ValueError('code has a phase and two counts')
        frame.code[int(args[0])] = (int(args[1]), int(args[2]))
    else:
        frame.unclosed = int(args[0])


def read(path: Path) -> Trace:
    return parse(path.read_text())
