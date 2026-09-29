"""Measures of the game's frames from a trace of ref816 (tracefile.py):
the numbers of docs/PROFILE.md, before any formatting.

Most measures are a list with a value for each recorded frame, which the
report gives as a median and a range; the code heat is also taken over
all the frames together, where the parts of a total must add up.

"Far" data is a data access (not the direct page, the stack, an opcode
or operand fetch, a vector, the I/O space or ROM) to a bank outside the
trace's near banks.
"""

import statistics
from typing import (Callable, Dict, Iterable, List, NamedTuple, Optional,
                    Sequence, Set, Tuple)

from ref816.tracefile import Frame, Trace

MASTER_HZ = 14318180

# Heat: address -> (instructions executed there, instruction length).
Heat = Dict[int, Tuple[int, int]]


class Spread(NamedTuple):
    median: float
    low: int
    high: int


def spread(values: Sequence[int]) -> Spread:
    if not values:
        return Spread(0, 0, 0)
    return Spread(statistics.median(values), min(values), max(values))


def check(trace: Trace) -> None:
    """The phases of each frame, with the cycles of the firmware traps,
    add up to the frame: ValueError if not (the trace lost counts)."""
    for frame in trace.frames:
        instructions = sum(c[0] for c in frame.cost.values())
        cycles = sum(c[1] for c in frame.cost.values()) + frame.firmware[1]
        if (instructions, cycles) != (frame.instructions, frame.cycles):
            raise ValueError('frame %d: the phases add up to %d '
                             'instructions and %d cycles, the frame has %d '
                             'and %d' % (frame.index, instructions, cycles,
                                         frame.instructions, frame.cycles))


def seconds(trace: Trace) -> float:
    """Machine time from the start of the first frame to the end of the
    last."""
    if not trace.frames:
        return 0.0
    return (trace.frames[-1].end.clock - trace.frames[0].start.clock) / \
        MASTER_HZ


# ---- phases ----

def phase_cost(trace: Trace, phases: Iterable[int], which: int
               ) -> List[int]:
    """Instructions (which = 0) or cycles (1) of `phases`, a frame each."""
    wanted = set(phases)
    return [sum(c[which] for p, c in f.cost.items() if p in wanted)
            for f in trace.frames]


def enters(trace: Trace, phase: int) -> List[int]:
    """Entries of `phase` (calls of its entries, or interrupts), a
    frame each."""
    return [f.enters.get(phase, 0) for f in trace.frames]


def firmware_cycles(trace: Trace) -> List[int]:
    """Cycles of the machine's firmware traps, a frame each."""
    return [f.firmware[1] for f in trace.frames]


# ---- memory accesses ----

def access_class(trace: Trace, space: str, bank: int) -> str:
    """program, direct, stack, near, far, io or vector."""
    if space == 'data':
        return 'near' if bank in trace.near else 'far'
    return space


def accesses(trace: Trace, keep: Callable[[int, str, int], bool]
             ) -> Tuple[List[int], List[int]]:
    """Reads and writes a frame of the accesses (phase, space, bank) that
    `keep` takes."""
    reads, writes = [], []
    for frame in trace.frames:
        r = w = 0
        for (phase, space, bank), (a, b) in frame.access.items():
            if keep(phase, space, bank):
                r += a
                w += b
        reads.append(r)
        writes.append(w)
    return reads, writes


def far_banks(trace: Trace) -> List[int]:
    return sorted({bank for f in trace.frames
                   for (_, space, bank) in f.access
                   if access_class(trace, space, bank) == 'far'})


def lines(trace: Trace, bank: int, which: int) -> List[int]:
    """Distinct lines of `bank` a frame: which = 0, 1, 2 for 8-byte
    lines, 64-byte lines and pages touched; 3, 4, 5 written."""
    return [f.lines.get(bank, (0,) * 6)[which] for f in trace.frames]


def switches(trace: Trace, phases: Optional[Iterable[int]] = None
             ) -> List[int]:
    wanted = None if phases is None else set(phases)
    return [sum(n for p, n in f.switches.items()
                if wanted is None or p in wanted) for f in trace.frames]


# ---- code heat ----

def heat(frames: Iterable[Frame], phases: Optional[Iterable[int]] = None
         ) -> Heat:
    """The heat of `frames` together, of `phases` (all by default)."""
    wanted = None if phases is None else set(phases)
    out: Heat = {}
    for frame in frames:
        for (phase, address), (count, length) in frame.heat.items():
            if wanted is not None and phase not in wanted:
                continue
            old = out.get(address, (0, 0))
            out[address] = (old[0] + count, max(old[1], length))
    return out


def hottest(heat_map: Heat) -> List[Tuple[int, int, int]]:
    """(address, count, length), the most executed first (then by
    address, so that ties are stable)."""
    return sorted(((a, c, n) for a, (c, n) in heat_map.items()),
                  key=lambda item: (-item[1], item[0]))


def hot_set(heat_map: Heat, share: float) -> List[Tuple[int, int]]:
    """(address, length) of the fewest instructions that account for
    `share` (0-1) of the instructions executed, the hottest first."""
    total = sum(c for c, _ in heat_map.values())
    chosen, done = [], 0
    for address, count, length in hottest(heat_map):
        if done >= share * total:
            break
        chosen.append((address, length))
        done += count
    return chosen


def byte_count(instructions: Iterable[Tuple[int, int]]) -> int:
    """Bytes covered by the instructions (address, length)."""
    covered: Set[int] = set()
    for address, length in instructions:
        covered.update(range(address, address + length))
    return len(covered)


def bytes_by(instructions: Iterable[Tuple[int, int]],
             group: Callable[[int], str]) -> Dict[str, int]:
    """byte_count of the instructions of each group of their addresses."""
    parts: Dict[str, List[Tuple[int, int]]] = {}
    for address, length in instructions:
        parts.setdefault(group(address), []).append((address, length))
    return {name: byte_count(items) for name, items in parts.items()}


def executed(heat_map: Heat) -> List[Tuple[int, int]]:
    return [(a, n) for a, (_, n) in heat_map.items()]


def coverage(heat_map: Heat, budget: int) -> float:
    """The share of the instructions executed that the `budget` most
    executed instruction addresses account for."""
    ranked = hottest(heat_map)
    total = sum(c for _, c, _ in ranked)
    return sum(c for _, c, _ in ranked[:budget]) / total if total else 0.0


# ---- stack ----

def stack_lows(trace: Trace, low: bool, phases: Optional[Iterable[int]]
               = None) -> List[Optional[int]]:
    """The lowest S a frame above the split (low = False) or at or below
    it (True), of `phases` (all by default); None for a frame with none."""
    wanted = None if phases is None else set(phases)
    out = []
    for frame in trace.frames:
        values = [s[1 if low else 0] for p, s in frame.stack.items()
                  if wanted is None or p in wanted]
        values = [v for v in values if v is not None]
        out.append(min(values) if values else None)
    return out


# ---- screen ----

def screen(trace: Trace, which: int, phases: Optional[Iterable[int]] = None
           ) -> List[int]:
    """Writes a frame that reach the screen: which = 0 directly, 1 by
    shadowing, 2 those that changed the byte, 3 all."""
    wanted = None if phases is None else set(phases)
    out = []
    for frame in trace.frames:
        n = 0
        for phase, counts in frame.screen.items():
            if wanted is None or phase in wanted:
                n += counts[0] + counts[1] if which == 3 else counts[which]
        out.append(n)
    return out


# ---- writes to code ----

class SmcGroup(NamedTuple):
    writer: int                 # the address of the writing instruction
    target: str                 # the group of the bytes it writes
    per_frame: List[int]        # writes, a frame each
    bytes: int                  # distinct bytes written


def smc_groups(trace: Trace, target_group: Callable[[int], str]
               ) -> List[SmcGroup]:
    """Writes to code by writing instruction and target group, the most
    first."""
    index = {f.index: i for i, f in enumerate(trace.frames)}
    groups: Dict[Tuple[int, str], Tuple[List[int], Set[int]]] = {}
    for record in trace.smc:
        if record.frame not in index:
            continue
        key = (record.writer, target_group(record.target))
        counts, targets = groups.setdefault(
            key, ([0] * len(trace.frames), set()))
        counts[index[record.frame]] += record.count
        targets.add(record.target)
    rows = [SmcGroup(writer, target, counts, len(targets))
            for (writer, target), (counts, targets) in groups.items()]
    rows.sort(key=lambda row: (-sum(row.per_frame), row.writer, row.target))
    return rows


def smc_per_frame(trace: Trace) -> List[int]:
    index = {f.index: i for i, f in enumerate(trace.frames)}
    out = [0] * len(trace.frames)
    for record in trace.smc:
        if record.frame in index:
            out[index[record.frame]] += record.count
    return out


# ---- widths ----

def merge_widths(traces: Iterable[Trace]) -> Dict[int, Dict[str, Set[int]]]:
    merged: Dict[int, Dict[str, Set[int]]] = {}
    for trace in traces:
        for address, kinds in trace.widths.items():
            into = merged.setdefault(address, {k: set() for k in kinds})
            for kind, values in kinds.items():
                into[kind] |= values
    return merged
