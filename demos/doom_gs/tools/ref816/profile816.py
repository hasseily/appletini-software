#!/usr/bin/env python3
"""Measured profiles of the game on ref816: docs/PROFILE.md from traces.

Usage:  python3 tools/ref816/profile816.py [--run] [--traces DIR]
                                           [--output FILE] [--widths FILE]

Two scenarios are traced (tools/ref816/trace.h) at the IIgs's own CPU
rate, 2,863,636 Hz: standing still in E1M1 (coverage/newgame.script from
its note "still" to "still-10s") and the title demo (coverage/title.script
from "demo" to "demo-25s"). Their traces go to build/ref816/traces/;
they are made when missing, and again with --run.

The report, tables of numbers from the traces and the text of
profile_template.md around them, goes to docs/PROFILE.md and to the
standard output; the register widths of every instruction the two runs
executed go to build/ref816/widths.json. The same traces give the same
files, byte for byte.

Nothing derived from the vendor runtime (cal_integer.s) goes into the
report: codemap.py makes all of its code one anonymous place, and every
table that lists places folds that place into its "N others" row, with
at least one place of the game, so that no row, and no difference of a
total and the rows, gives a figure of its own (fold). The rows it would
have had go to build/ref816/profile-withheld.json only.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import (Callable, Dict, Iterable, List, NamedTuple, Optional,
                    Sequence, Tuple, TypeVar)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import (codemap, make_image, marks, measures, run_script,  # noqa
                    script, title, tracefile)
from ref816.measures import spread  # noqa: E402
from ref816.tracefile import Trace  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = make_image.ROOT
TRACES = make_image.OUT_DIR / 'traces'
OUTPUT = ROOT / 'docs' / 'PROFILE.md'
WIDTHS = make_image.OUT_DIR / 'widths.json'
WITHHELD = make_image.OUT_DIR / 'profile-withheld.json'
TEMPLATE = HERE / 'profile_template.md'


class Scenario(NamedTuple):
    key: str                # names its trace and its values in the text
    script: str             # in coverage/
    start: str              # the notes that bound the frames
    end: str


SCENARIOS = (Scenario('still', 'newgame', 'still', 'still-10s'),
             Scenario('demo', 'title', 'demo', 'demo-25s'))


class Phase(NamedTuple):
    key: str                # its name in the trace
    title: str
    entries: Tuple[str, ...]    # symbols of the link map


# In the order of the report. "interrupt" and "other" are the trace's own.
PHASES = (
    Phase('tics', 'Game tics', ('P_Ticker',)),
    Phase('setup', 'Frame setup',
          ('vwFrame', 'R_FillStamps', 'R_RenderPlayerView')),
    Phase('bsp', 'BSP walk', ('R_RenderBSPNode',)),
    Phase('wall', 'Wall setup', ('R_StoreWallRange',)),
    Phase('seg', 'Seg loops', ('R_RenderSegLoop',)),
    Phase('sprites', 'Sprite projection', ('R_AddSprites',)),
    Phase('masked', 'Masked drawing', ('r_frame65.s:drawMasked',)),
    Phase('replay', 'Record replay', ('R_DrawLists',)),
    Phase('status', 'Status bar and HUD',
          ('ST_doPaletteStuff', 'ST_Drawer', 'HU_Drawer')),
    Phase('menu', 'Menu', ('M_Ticker', 'M_Drawer')),
    Phase('finish', 'Finish', ('I_FinishUpdate',)),
    Phase('interrupt', 'Interrupts', ()),
    Phase('other', 'Everything else', ()),
)
FRAME_ENTRY = 'R_RenderPlayerView'
NEAR_BANKS = (0x02,)
TIC_STACK = 'p_think65.s:LOGIC_SP'     # the top of the tic stack
FRAME_STACK_SECTION = 'stack'           # the frame stack's section

# The phase windows of docs/ARCHITECTURE.md section 3.2, as groups of
# phases; the replay is hand-written there, so it has none.
WINDOWS = (('Tics', ('tics',)),
           ('Render', ('setup', 'bsp', 'wall', 'seg', 'sprites', 'masked')),
           ('UI and 2D', ('status', 'menu', 'finish')),
           ('Rest', ('other', 'interrupt')))
# "The windows hold about 30 KB per phase, which is about 3,500 source
# instructions" (docs/ARCHITECTURE.md section 3.5).
WINDOW_INSTRUCTIONS = 3500
HOT_SHARES = (0.9, 0.99, 0.999)
# What the text weighs the measures with: the nominal CPU rate (P1) and
# cycles a translated instruction (P3) of docs/ARCHITECTURE.md section 6,
# its bytes of 65C02 code for a byte of 65816 code (section 3.5: 8.5
# bytes emitted for an instruction of about 2.7), and the target's bus
# cycle for a change of bank and time for a screen byte.
TARGET_HZ = 45e6
NATIVE_CYCLES = 18
EXPANSION = 8.5 / 2.7
SWITCH_US = 1.0
SCREEN_BYTE_US = 1.0
TOP_OTHER = 8           # functions listed for "Everything else"
TOP_FILES = 20          # source files listed in the heat by file
TOP_SMC = 16            # rows of writes to code
TOP_WIDTH_FILES = 15


# ---- running the traces ----

def trace_options(symbols: script.Symbols, scenario: Scenario,
                  path: Path) -> List[str]:
    """The machine's options that trace `scenario` into `path`."""
    options = ['--trace', str(path), '--trace-frame',
               '%06X' % symbols.address(FRAME_ENTRY),
               '--trace-from', scenario.start, '--trace-to', scenario.end,
               '--trace-stack-split', '%04X' % symbols.address(TIC_STACK)]
    for bank in NEAR_BANKS:
        options += ['--trace-near', '%02X' % bank]
    for phase in PHASES:
        for entry in phase.entries:
            options += ['--trace-phase', '%s=%06X' % (
                phase.key, symbols.address(entry))]
    return options


def make_trace(scenario: Scenario, symbols: script.Symbols,
               directory: Path) -> Path:
    """Run the scenario's script traced; RuntimeError when the run has a
    problem (run_script.problems)."""
    path = run_script.script_path(scenario.script)
    program = script.compile_script(path.read_text(), symbols, path.name)
    directory.mkdir(parents=True, exist_ok=True)
    trace = directory / (scenario.key + '.trace')
    run_dir = run_script.RUNS / ('trace-' + scenario.key)
    run = run_script.Run(run_dir, run_dir / 'shots')
    state = run.execute(program, symbols, None,
                        run_script.DEFAULT_LIMIT_SECONDS,
                        trace_options(symbols, scenario, trace))
    found = run_script.problems(state, marks.read(run.marks_path), symbols,
                                program)
    if found:
        raise RuntimeError('the traced run of %s: %s'
                           % (scenario.script, '; '.join(found)))
    return trace


# ---- formatting ----

def number(value: float) -> str:
    return '{:,}'.format(int(round(value)))


def ranged(values: Sequence[int]) -> str:
    """"median (low-high)", or the one value when they are all equal."""
    s = spread(values)
    if s.low == s.high:
        return number(s.median)
    return '%s (%s-%s)' % (number(s.median), number(s.low), number(s.high))


def percent(part: float, whole: float, digits: int = 1) -> str:
    return '%.*f%%' % (digits, 100.0 * part / whole) if whole else '-'


def table(header: Sequence[str], rows: Iterable[Sequence[str]],
          text: int = 1) -> str:
    """A Markdown table: the first `text` columns left-aligned, the
    numbers after them right-aligned."""
    lines = ['| ' + ' | '.join(header) + ' |',
             '|' + '---|' * text + '---:|' * (len(header) - text)]
    lines += ['| ' + ' | '.join(row) + ' |' for row in rows]
    return '\n'.join(lines)


def hex_bank(bank: int) -> str:
    return '$%02X' % bank


T = TypeVar('T')


def fold(ranked: Sequence[T], limit: Optional[int],
         withhold: Callable[[T], bool]) -> Tuple[List[T], List[T], List[T]]:
    """The items of a table, `ranked` the first first, as (shown, rest,
    withheld): the first `limit` (all for None) that `withhold` does not
    take get a row each, and the rest and the withheld are summed in an
    "N others" row when the rest is not empty. The withheld never have a
    row of their own, and never are alone in the others row: when the
    rest would be empty, the last shown item joins them, so that neither
    a row nor a total minus the rows gives their figures. With nothing
    else to join, they are only in the totals.
    """
    withheld = [item for item in ranked if withhold(item)]
    visible = [item for item in ranked if not withhold(item)]
    shown = visible if limit is None else visible[:limit]
    rest = visible[len(shown):]
    if withheld and not rest and shown:
        rest = [shown.pop()]
    return shown, rest, withheld


def others(rest: Sequence, withheld: Sequence) -> str:
    return '%d others' % (len(rest) + len(withheld))


def is_vendor(name: str) -> bool:
    """A place, section or file of codemap's that is the vendor runtime."""
    return name == codemap.VENDOR


# ---- the report ----

class Report:
    """The tables and numbers of one trace."""

    def __init__(self, trace: Trace, code: codemap.CodeMap):
        measures.check(trace)
        if not trace.frames:
            raise ValueError('the trace has no frames')
        self.trace = trace
        self.code = code
        self.frames = trace.frames
        self.index = {phase.key: trace.phase(phase.key) for phase in PHASES}
        self.values: Dict[str, str] = {}
        # The rows fold() kept out of each table: for build/ only.
        self.withheld: Dict[str, List[List[str]]] = {}
        self._places: Dict[int, codemap.Place] = {}

    def place(self, address: int) -> codemap.Place:
        if address not in self._places:
            self._places[address] = self.code.place(address)
        return self._places[address]

    def phases_of(self, keys: Iterable[str]) -> List[int]:
        return [self.index[k] for k in keys]

    # -- 1. instructions and cycles by phase --

    def phase_table(self) -> str:
        total_cycles = sum(f.cycles for f in self.frames)
        rows = []
        for phase in PHASES:
            p = [self.index[phase.key]]
            cycles = measures.phase_cost(self.trace, p, 1)
            rows.append([phase.title,
                         ranged(measures.phase_cost(self.trace, p, 0)),
                         ranged(cycles), percent(sum(cycles), total_cycles)])
            self.values['share_' + phase.key] = percent(sum(cycles),
                                                        total_cycles, 0)
        # The machine's firmware traps: cycles with no instruction, in no
        # phase; a row only when a frame has some.
        firmware = measures.firmware_cycles(self.trace)
        if any(firmware):
            rows.append(["Firmware traps (the machine's)", '0',
                         ranged(firmware), percent(sum(firmware),
                                                   total_cycles)])
        self.values['firmware'] = number(sum(firmware))
        instructions = [f.instructions for f in self.frames]
        cycles = [f.cycles for f in self.frames]
        rows.append(['**Frame**', ranged(instructions), ranged(cycles),
                     '100%'])
        seconds = measures.seconds(self.trace)
        self.values.update(
            unclosed=number(sum(f.unclosed for f in self.frames)),
            jumps=number(sum(self.trace.jumps.values())),
            smc_mixed=number(self.trace.smc_mixed),
            frames=str(len(self.frames)),
            ms=number(1000 * seconds / len(self.frames)),
            fps='%.2f' % (len(self.frames) / seconds),
            instructions=number(spread(instructions).median),
            cycles=number(spread(cycles).median),
            cpi='%.2f' % (sum(cycles) / sum(instructions)))
        return table(['Phase', 'Instructions', 'Cycles', 'Share of cycles'],
                     rows)

    def other_table(self) -> str:
        """The functions that make up "Everything else"."""
        other = self.index['other']
        heat = measures.heat(self.frames, [other])
        by_function: Dict[str, int] = {}
        for address, (count, _) in heat.items():
            name = self.place(address).function
            by_function[name] = by_function.get(name, 0) + count
        total = sum(by_function.values())
        ranked = sorted(by_function.items(), key=lambda kv: (-kv[1], kv[0]))
        shown, rest, withheld = fold(ranked, TOP_OTHER,
                                     lambda kv: is_vendor(kv[0]))

        def row(name: str, count: int) -> List[str]:
            return [name, number(count / len(self.frames)),
                    percent(count, total)]
        rows = [row(name, count) for name, count in shown]
        if rest:
            rows.append(row(others(rest, withheld),
                            sum(c for _, c in rest + withheld)))
        self.withheld['other'] = [row(n, c) for n, c in withheld]
        return table(['Code (nearest label)', 'Instructions a frame (mean)',
                      'Share'], rows)

    # -- 2. memory accesses --

    def access_table(self) -> str:
        trace = self.trace
        classes = (('program', 'Opcode and operand fetches'),
                   ('direct', 'Direct page'), ('stack', 'Stack'),
                   ('near', 'Near data, bank $02'),
                   ('far', 'Far data, all other banks'),
                   ('io', 'I/O space and ROM'), ('vector', 'Vectors'))
        rows = []
        for key, name in classes:
            reads, writes = measures.accesses(
                trace, lambda p, s, b, key=key:
                measures.access_class(trace, s, b) == key)
            rows.append([name, ranged(reads), ranged(writes)])
            if key == 'far':
                total = [r + w for r, w in zip(reads, writes)]
                self.values['far'] = number(spread(total).median)
                self.values['far_share'] = percent(
                    sum(total), sum(f.instructions for f in self.frames), 0)
        return table(['Access', 'Reads', 'Writes'], rows)

    def bank_table(self) -> str:
        trace = self.trace
        rows = []
        banks = [(b, 'near') for b in sorted(trace.near)] + \
            [(b, '') for b in measures.far_banks(trace)]
        for bank, near in banks:
            reads, writes = measures.accesses(
                trace, lambda p, s, b, bank=bank: s == 'data' and b == bank)
            holds = self.code.bank(bank) or {
                0x01: 'shadowed screen, bank $E1', 0xe1: 'screen'}.get(
                    bank, '')
            if near:
                holds = 'near data (%s)' % holds
                self.values['near_pages'] = number(
                    spread(measures.lines(trace, bank, 2)).median)
            rows.append([hex_bank(bank), holds, ranged(reads), ranged(writes)]
                        + [ranged(measures.lines(trace, bank, i))
                           for i in range(3)])
        far = measures.far_banks(trace)
        reads, writes = measures.accesses(
            trace, lambda p, s, b: measures.access_class(trace, s, b) ==
            'far')
        lines = [[sum(v) for v in zip(*(measures.lines(trace, b, i)
                                        for b in far))] for i in range(3)]
        rows.append(['**Far**', '', ranged(reads), ranged(writes)] +
                    [ranged(v) for v in lines])
        for i, name in enumerate(('lines8', 'lines64', 'pages')):
            self.values['far_' + name] = number(spread(lines[i]).median)
        return table(['Bank', 'Holds', 'Reads', 'Writes', '8-byte lines',
                      '64-byte lines', 'Pages'], rows, 2)

    def far_phase_table(self) -> str:
        trace = self.trace
        rows = []
        for phase in PHASES:
            p = self.index[phase.key]
            reads, writes = measures.accesses(
                trace, lambda q, s, b, p=p: q == p and
                measures.access_class(trace, s, b) == 'far')
            changes = measures.switches(trace, [p])
            if any(reads) or any(writes) or any(changes):
                rows.append([phase.title, ranged(reads), ranged(writes),
                             ranged(changes)])
        changes = measures.switches(trace)
        self.values['replay_changes'] = percent(
            sum(measures.switches(trace, [self.index['replay']])),
            sum(changes), 0)
        rows.append(['**Frame**'] + [ranged(v) for v in measures.accesses(
            trace, lambda q, s, b: measures.access_class(trace, s, b) ==
            'far')] + [ranged(changes)])
        self.values['bank_changes'] = number(spread(changes).median)
        return table(['Phase', 'Far reads', 'Far writes', 'Bank changes'],
                     rows)

    # -- 3. code heat --

    def heat_totals(self) -> str:
        executed, hot = [], {share: [] for share in HOT_SHARES}
        for frame in self.frames:
            heat = measures.heat([frame])
            executed.append(measures.byte_count(measures.executed(heat)))
            for share in HOT_SHARES:
                hot[share].append(measures.byte_count(
                    measures.hot_set(heat, share)))
        rows = [['Executed at least once', ranged(executed)]]
        rows += [['%s of the instructions' % share_name(share),
                  ranged(hot[share])] for share in HOT_SHARES]
        self.values['executed_bytes'] = number(spread(executed).median)
        for share in HOT_SHARES:
            median = spread(hot[share]).median
            self.values['hot_%s' % share_key(share)] = number(median)
            self.values['hot_%s_native_kb' % share_key(share)] = number(
                median * EXPANSION / 1024)
        return table(['Code bytes', 'A frame'], rows)

    def heat_groups(self, key: str, group: Callable[[int], str], title: str,
                    limit: Optional[int] = None) -> str:
        """The heat of all the frames together, by `group` of address;
        `key` names the table's withheld rows."""
        heat = measures.heat(self.frames)
        columns = [measures.bytes_by(measures.executed(heat), group)]
        columns += [measures.bytes_by(measures.hot_set(heat, share), group)
                    for share in HOT_SHARES]
        names = sorted(columns[0], key=lambda n: tuple(
            -c.get(n, 0) for c in reversed(columns)) + (n,))
        shown, rest, withheld = fold(names, limit, is_vendor)
        rows = [[name] + [number(c.get(name, 0)) for c in columns]
                for name in shown]
        if rest:
            rows.append([others(rest, withheld)] + [
                number(sum(c.get(n, 0) for n in rest + withheld))
                for c in columns])
        self.withheld[key] = [[name] + [number(c.get(name, 0))
                                        for c in columns]
                              for name in withheld]
        rows.append(['**All**'] + [number(sum(c.values())) for c in columns])
        return table([title, 'Executed'] + [share_name(s)
                                            for s in HOT_SHARES], rows)

    def heat_phase_table(self) -> str:
        rows = []
        for phase in PHASES:
            p = self.index[phase.key]
            heat = measures.heat(self.frames, [p])
            if not heat:
                continue
            rows.append(
                [phase.title,
                 ranged(measures.phase_cost(self.trace, [p], 0)),
                 number(measures.byte_count(measures.executed(heat)))] +
                [number(measures.byte_count(measures.hot_set(heat, share)))
                 for share in HOT_SHARES])
        return table(['Phase', 'Instructions', 'Executed'] +
                     [share_name(s) for s in HOT_SHARES], rows)

    def window_table(self) -> str:
        """How much of each window's instructions its hottest code covers
        (P4)."""
        budgets = (WINDOW_INSTRUCTIONS // 2, WINDOW_INSTRUCTIONS,
                   2 * WINDOW_INSTRUCTIONS)
        rows, covered, total = [], {b: 0.0 for b in budgets}, 0
        for name, keys in WINDOWS:
            heat = measures.heat(self.frames, self.phases_of(keys))
            count = sum(c for c, _ in heat.values())
            if not count:
                continue
            total += count
            shares = {b: measures.coverage(heat, b) for b in budgets}
            for b in budgets:
                covered[b] += shares[b] * count
            rows.append([name, number(count / len(self.frames)),
                         number(len(heat))] +
                        ['%.1f%%' % (100 * shares[b]) for b in budgets])
        rows.append(['**All but the replay**', number(total /
                                                     len(self.frames)),
                     ''] + [percent(covered[b], total) for b in budgets])
        self.values['p4'] = percent(covered[WINDOW_INSTRUCTIONS], total)
        return table(['Window', 'Instructions a frame (mean)',
                      'Addresses executed'] +
                     ['Hottest %s cover' % number(b) for b in budgets], rows)

    # -- 5. writes to code --

    def smc_table(self) -> str:
        groups = measures.smc_groups(
            self.trace, lambda a: self.place(a).function)
        per_frame = measures.smc_per_frame(self.trace)
        self.values['smc_writes'] = number(spread(per_frame).median)
        self.values['smc_writers'] = str(len({g.writer for g in groups}))
        self.values['smc_targets'] = str(len({g.target for g in groups}))
        if not groups:
            return 'No write to code in these frames.'
        shown, rest, withheld = fold(
            groups, TOP_SMC, lambda g: is_vendor(str(self.place(g.writer)))
            or is_vendor(g.target))

        def row(g: measures.SmcGroup) -> List[str]:
            return ['%s ($%06X)' % (self.place(g.writer), g.writer), g.target,
                    ranged(g.per_frame), number(g.bytes)]
        rows = [row(g) for g in shown]
        self.withheld['smc'] = [row(g) for g in withheld]
        if rest:
            folded = rest + withheld
            counts = [sum(v) for v in zip(*(g.per_frame for g in folded))]
            rows.append(['%d other writer and target pairs' % len(folded),
                         '', ranged(counts),
                         number(sum(g.bytes for g in folded))])
        rows.append(['**All**', '', ranged(per_frame),
                     number(sum(g.bytes for g in groups))])
        return table(['Writing instruction', 'Target', 'Writes a frame',
                      'Bytes written'], rows, 2)

    # -- 6. stack --

    def stack_table(self) -> str:
        top = self.code.sections[FRAME_STACK_SECTION]['last']
        split = self.trace.split
        rows = []
        for name, low, start in (('Frame stack', False, top),
                                 ('Tic stack', True, split)):
            lows = [s for s in measures.stack_lows(self.trace, low)
                    if s is not None]
            if not lows:
                rows.append([name, '', '-', '-', '-'])
                continue
            deepest = min(lows)
            phase = min(
                (s, PHASES_BY_KEY[self.trace.phases[p]].title)
                for p in range(len(self.trace.phases))
                for s in measures.stack_lows(self.trace, low, [p])
                if s is not None)[1]
            rows.append([name + ' (top $%04X)' % start, phase,
                         ranged([start - s for s in lows]),
                         '$%04X' % deepest, number(start - deepest)])
            self.values['stack_%s' % ('tic' if low else 'frame')] = number(
                start - deepest)
        return table(['Stack', 'Phase at the lowest', 'Bytes used a frame',
                      'Lowest S', 'Most bytes used'], rows, 2)

    # -- 7. screen --

    def screen_table(self) -> str:
        trace = self.trace
        rows = [['All', ranged(measures.screen(trace, 3)),
                 ranged(measures.screen(trace, 2))],
                ['Directly', ranged(measures.screen(trace, 0)), ''],
                ['By shadowing', ranged(measures.screen(trace, 1)), '']]
        for phase in PHASES:
            p = [self.index[phase.key]]
            written = measures.screen(trace, 3, p)
            if any(written):
                rows.append([phase.title, ranged(written),
                             ranged(measures.screen(trace, 2, p))])
        self.values['screen_bytes'] = number(
            spread(measures.screen(trace, 3)).median)
        self.values['screen_changed'] = number(
            spread(measures.screen(trace, 2)).median)
        return table(['Writes to $E1:2000-$9CFF', 'Bytes a frame',
                      'Changed'], rows)

    # -- 8. the assumptions of ARCHITECTURE.md --

    def assumptions(self) -> Dict[str, str]:
        """P2, P6 and P8 measured (P4 is window_table's). P2 also without
        the game tics, and the instructions of one tic: the tics phase
        of a frame over the calls of its entry (P_Ticker) in it."""
        trace = self.trace
        replay, tics = self.index['replay'], self.index['tics']
        outside = [p for p in range(len(trace.phases)) if p != replay]
        p2 = measures.phase_cost(trace, outside, 0)
        p2_no_tics = measures.phase_cost(
            trace, [p for p in outside if p != tics], 0)
        calls = measures.enters(trace, tics)
        per_tic = [cost / n for cost, n in
                   zip(measures.phase_cost(trace, [tics], 0), calls) if n]
        far_reads, far_writes = measures.accesses(
            trace, lambda p, s, b: p != replay and
            measures.access_class(trace, s, b) == 'far')
        far = [r + w for r, w in zip(far_reads, far_writes)]
        changes = measures.switches(trace, outside)
        written = measures.screen(trace, 3)
        changed = measures.screen(trace, 2)
        return {
            'p2_ms': number(spread(p2).median * NATIVE_CYCLES / TARGET_HZ *
                            1000),
            'p6_ms': number(spread(changes).median * SWITCH_US / 1000),
            'p8_ms': '%.1f' % (spread(written).median * SCREEN_BYTE_US /
                               1000),
            'p8_changed_ms': '%.1f' % (spread(changed).median *
                                       SCREEN_BYTE_US / 1000),
            'p2': ranged(p2),
            'p2_no_tics': ranged(p2_no_tics),
            'tic': ranged(per_tic) if per_tic else '-',
            'tics': ranged(calls),
            'p6': '%s, %s of the instructions' % (
                ranged(far), percent(sum(far), sum(p2), 0)),
            'p6_changes': ranged(changes),
            'p8': '%s written, %s changed' % (ranged(written),
                                              ranged(changed)),
        }


PHASES_BY_KEY = {phase.key: phase for phase in PHASES}


def share_name(share: float) -> str:
    return '%g%%' % (100 * share)


def share_key(share: float) -> str:
    return ('%g' % (100 * share)).replace('.', '_')


# ---- widths ----

def decode_mx(value: int) -> Dict[str, int]:
    return {'e': value >> 2 & 1, 'm': value >> 1 & 1, 'x': value & 1}


def widths_json(traces: Sequence[Trace], code: codemap.CodeMap) -> Dict:
    merged = measures.merge_widths(traces)
    addresses = {}
    for address in sorted(merged):
        kinds = merged[address]
        addresses['%06X' % address] = {
            'place': str(code.place(address)),
            'flags': [decode_mx(v) for v in sorted(kinds['mx'])],
            'd': ['%04X' % v for v in sorted(kinds['d'])],
            'dbr': ['%02X' % v for v in sorted(kinds['dbr'])]}
    return {'addresses': addresses,
            'summary': width_summary(merged)}


def width_summary(merged: Dict) -> Dict[str, int]:
    summary = {'executed': len(merged),
               'emulation': sum(1 for k in merged.values()
                                if any(v >> 2 for v in k['mx']))}
    for kind in tracefile.WIDTH_KINDS:
        summary['more_than_one_' + kind] = sum(
            1 for k in merged.values() if len(k[kind]) > 1)
        summary['most_' + kind] = max((len(k[kind]) for k in
                                       merged.values()), default=0)
    return summary


def width_tables(traces: Sequence[Trace], code: codemap.CodeMap,
                 values: Dict[str, str],
                 withheld: Optional[Dict] = None) -> Tuple[str, str]:
    merged = measures.merge_widths(traces)
    summary = width_summary(merged)
    names = {'mx': '(M, X)', 'd': 'D', 'dbr': 'DBR'}
    rows = []
    for kind in tracefile.WIDTH_KINDS:
        rows.append([names[kind],
                     number(summary['executed'] -
                            summary['more_than_one_' + kind]),
                     number(summary['more_than_one_' + kind]),
                     number(summary['most_' + kind])])
        values['widths_' + kind] = number(summary['more_than_one_' + kind])
    values['widths_executed'] = number(summary['executed'])
    values['widths_emulation'] = number(summary['emulation'])
    first = table(['Register', 'Addresses with one value',
                   'With more than one', 'Most values at one address'], rows)

    by_unit: Dict[str, List[int]] = {}
    for address, kinds in merged.items():
        counts = by_unit.setdefault(code.place(address).unit, [0, 0, 0, 0])
        counts[0] += 1
        for i, kind in enumerate(tracefile.WIDTH_KINDS, 1):
            counts[i] += len(kinds[kind]) > 1
    ranked = sorted(by_unit.items(),
                    key=lambda kv: (-sum(kv[1][1:]), kv[0]))
    ranked = [item for item in ranked if sum(item[1][1:])]
    shown, rest, hidden = fold(ranked, TOP_WIDTH_FILES,
                               lambda item: is_vendor(item[0]))
    rows = [[unit] + [number(n) for n in counts] for unit, counts in shown]
    if rest:
        rows.append([others(rest, hidden)] + [
            number(sum(c[i] for _, c in rest + hidden)) for i in range(4)])
    if withheld is not None:
        withheld['widths_files'] = [[unit] + [number(n) for n in counts]
                                    for unit, counts in hidden]
    second = table(['Source file', 'Addresses executed',
                    'More than one (M, X)', 'More than one D',
                    'More than one DBR'], rows)
    return first, second


# ---- the document ----

def phase_detection(symbols: script.Symbols) -> str:
    rows = []
    for phase in PHASES:
        if phase.entries:
            entries = ', '.join('`%s` $%06X' % (e.split(':')[-1],
                                                symbols.address(e))
                                for e in phase.entries)
            how = 'a call of an entry to its return'
        elif phase.key == 'interrupt':
            entries = 'the IRQ and NMI vectors'
            how = 'the entry (its first push) to the return'
        else:
            entries = ''
            how = 'outside the others'
        rows.append([phase.title, entries, how])
    return table(['Phase', 'Entries', 'Boundaries'], rows, 3)


def document(traces: Dict[str, Trace], code: codemap.CodeMap,
             symbols: script.Symbols, template: str,
             withheld: Optional[Dict] = None) -> str:
    """PROFILE.md from a trace of each scenario. The rows that fold()
    keeps out of it go into `withheld`, when given, by scenario and
    table."""
    if withheld is None:
        withheld = {}
    values: Dict[str, str] = {'phase_detection': phase_detection(symbols),
                              'window_instructions':
                                  number(WINDOW_INSTRUCTIONS)}
    for scenario in SCENARIOS:
        report = Report(traces[scenario.key], code)
        tables = {
            'phases': report.phase_table(),
            'other': report.other_table(),
            'access': report.access_table(),
            'banks': report.bank_table(),
            'far_phases': report.far_phase_table(),
            'heat': report.heat_totals(),
            'heat_sections': report.heat_groups(
                'heat_sections', lambda a: report.place(a).section,
                'Section'),
            'heat_files': report.heat_groups(
                'heat_files', lambda a: report.place(a).unit, 'Source file',
                TOP_FILES),
            'heat_phases': report.heat_phase_table(),
            'windows': report.window_table(),
            'smc': report.smc_table(),
            'stack': report.stack_table(),
            'screen': report.screen_table(),
        }
        tables.update(report.assumptions())
        tables.update(report.values)
        for name, text in tables.items():
            values['%s_%s' % (scenario.key, name)] = text
        withheld[scenario.key] = report.withheld
    values['widths'], values['widths_files'] = width_tables(
        [traces[s.key] for s in SCENARIOS], code, values, withheld)
    return template.format(**values)


# ---- the command line ----

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--run', action='store_true',
                        help='make the traces again')
    parser.add_argument('--traces', type=Path, default=TRACES)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--widths', type=Path, default=WIDTHS)
    arguments = parser.parse_args(argv)
    for path in (make_image.RELEASE_IMAGE, make_image.LINKMAP):
        if not path.exists():
            print('%s is missing: run python3 tools/fetch_upstream.py and '
                  'python3 tools/v816/imgmatch.py first' % path,
                  file=sys.stderr)
            return 1
    with open(str(make_image.LINKMAP)) as handle:
        linkmap = json.load(handle)
    symbols = script.Symbols(linkmap)
    code = codemap.CodeMap(linkmap)
    paths = {s.key: arguments.traces / (s.key + '.trace') for s in SCENARIOS}
    missing = [s for s in SCENARIOS
               if arguments.run or not paths[s.key].exists()]
    if missing:
        title.build_machine()
        title.ensure_image()
        for scenario in missing:
            print('tracing %s ...' % scenario.script, file=sys.stderr)
            make_trace(scenario, symbols, arguments.traces)
    traces = {key: tracefile.read(path) for key, path in paths.items()}
    withheld: Dict = {}
    text = document(traces, code, symbols, TEMPLATE.read_text(), withheld)
    arguments.output.write_text(text)
    arguments.widths.parent.mkdir(parents=True, exist_ok=True)
    arguments.widths.write_text(json.dumps(
        widths_json(list(traces.values()), code), indent=1) + '\n')
    # build/ only: the vendor runtime's own rows (see the docstring).
    WITHHELD.write_text(json.dumps(withheld, indent=1, sort_keys=True) +
                        '\n')
    print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
