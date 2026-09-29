#!/usr/bin/env python3
"""Run an input script on ref816 and collect its screen shots.

Usage:  python3 tools/ref816/run_script.py SCRIPT... [--cpu-hz N]
                                           [--twice] [--limit SECONDS]

Each SCRIPT (a path, or the name of one in coverage/) is compiled into
the machine's input program (script.py) and run on the release image
from its entry point, as tools/ref816/title.py does. The shots go to
build/ref816/shots/NAME/ as PNG files; the program, the final state,
the log of marks and a report go to build/ref816/runs/NAME/.

The run is watched for what would make it meaningless: the game's error
screen or its quit screen (the machine stops at I_Error and I_Quit), a
branch to itself and the opcodes that only a CPU running data would
meet, WDM and STP (--stop-on-fault), a wait of the script that times
out, I/O registers the machine does not model (but the serial
controller, which the game only switches off), reads of the ROM or of a
bank with no memory outside KNOWN_READS, firmware errors, and a main
loop that stops coming round (no call of display for STUCK_CYCLES
CPU cycles after the first). A script must end with its own stop. BRK
and COP are not faults: they go through the game's own vectors
(upstream's R_InitLists returns into 14 bytes of zero padding, 7 BRKs
whose vector is an RTI); the report counts them and names the first.

The report gives, between each note of the script and the next, the 3D
frames drawn per second of machine time and the median instructions and
cycles of one such frame (marks.py). --twice runs the script again and
checks that the RAM and the shots come out the same.

--cpu-hz is the rate of the CPU in the IIgs's fast mode: an ideal 65816
with memory of uniform speed (iigs.h). Without it the CPU takes the
IIgs's own 5 master clocks a cycle (2,863,636 Hz).

Exit status 0 when every script ran to its stop with nothing of the
above (and the same twice with --twice), 1 otherwise.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import make_image, marks, script, shot, title  # noqa: E402

ROOT = make_image.ROOT
COVERAGE = ROOT / 'coverage'
SHOTS = title.SHOTS
RUNS = make_image.OUT_DIR / 'runs'

STOPS = (('i_iigs65.s', 'I_Error'), ('i_iigs65.s', 'I_Quit'))
LOOP = ('d_main65.s', 'displayCall')
RENDER = ('r_frame65.s', 'R_RenderPlayerView')
# Registers the machine leaves out on purpose (tests/test_ref816_machine.py
# test_only_known_gaps_in_the_model): the serial controller, which the
# game only switches off.
KNOWN_IO = {'C039'}


class KnownRead(NamedTuple):
    """Reads that the machine answers with 0 (it has no ROM image and no
    memory outside banks $00-$7F and $E0-$E1) and that the game makes on
    purpose. All of it comes from the link map: the reading instruction
    must be in the function `unit:label`, and the addresses it reads must
    be the `length` bytes from the symbol `symbol`, `count` reads in all."""
    kind: str           # 'rom' or 'unmapped'
    unit: str
    label: str          # the function that reads
    symbol: str         # the first address it reads
    length: int
    count: int          # reads in a run
    why: str


# tests/test_ref816_machine.py test_only_known_gaps_in_the_model checks
# that a run meets exactly these.
KNOWN_READS = (
    KnownRead('rom', 'irq65.s', 'IIGS_StartInterrupts', 'VECTORS', 32, 32,
              'copies the ROM\'s 65816 vectors ($00:FFE0-$FFFF) to RAM '
              'before it maps RAM there (bit 6 of $C035), then writes its '
              'own IRQ, BRK, COP, ABORT and NMI vectors over them; with no '
              'ROM image the other vectors are 0, and the game never uses '
              'them'),
    KnownRead('unmapped', 'm_menu65.s', 'bmAccelOff', 'TW_ID', 1, 1,
              'the TransWarp GS probe: the signature "TWGS" in bank $BC, '
              'which reads 0 here, so the game finds no card (read once; '
              'the rest of the signature is not read)'),
)
# The longest wait for the main loop in the scripts is a level load of
# E1M9 or so: 74 million cycles.
STUCK_CYCLES = 200000000
DEFAULT_LIMIT_SECONDS = 900


def script_path(name: str) -> Path:
    path = Path(name)
    if path.exists():
        return path
    candidate = COVERAGE / (name if name.endswith('.script')
                            else name + '.script')
    if candidate.exists():
        return candidate
    raise FileNotFoundError('no script %s (nor %s)' % (name, candidate))


def label_of(symbols: script.Symbols, address: int) -> str:
    """"unit:label+offset" of the nearest label at or below `address`."""
    best = None
    for unit, labels in symbols.units.items():
        for name, value in labels.items():
            if isinstance(value, int) and value <= address and \
                    (best is None or value > best[0]):
                best = (value, unit, name)
    if best is None:
        return '$%06X' % address
    value, unit, name = best
    return '%s:%s+%d ($%06X)' % (unit, name, address - value, address)


def source(program: str, line: int) -> str:
    """Where line `line` of the compiled `program` comes from in its
    script ("name.script:N"), from the comment script.py puts there."""
    lines = program.splitlines()
    if 0 < line <= len(lines) and '#' in lines[line - 1]:
        return lines[line - 1].split('#', 1)[1].strip()
    return 'line %d of the program' % line


def function_of(symbols: script.Symbols, address: int) -> str:
    """"unit:label" of the nearest label at or below `address`."""
    return label_of(symbols, address).split('+')[0]


def unexplained_reads(missing: Dict, symbols: script.Symbols) -> List[str]:
    """The reads of the ROM and of banks with no memory (the "unmodelled"
    of the machine's state) that KNOWN_READS does not account for, and
    the reads KNOWN_READS expects that did not come as expected."""
    found = []
    if missing.get('read_sites_lost'):
        found.append('reads of ROM or of no memory by more instructions '
                     'than the machine keeps: %d reads not placed'
                     % missing['read_sites_lost'])
    for kind in ('rom', 'unmapped'):
        known = [k for k in KNOWN_READS if k.kind == kind]
        counts = {k: 0 for k in known}
        for site in missing.get(kind + '_read_sites', []):
            where = function_of(symbols, site['pc'])
            match = None
            for k in known:
                first = symbols.address('%s:%s' % (k.unit, k.symbol))
                if where == '%s:%s' % (k.unit, k.label) and \
                        first <= site['first'] and \
                        site['last'] < first + k.length:
                    match = k
            if match is None:
                found.append('%s reads: %d at $%06X-$%06X by %s'
                             % (kind, site['count'], site['first'],
                                site['last'], label_of(symbols, site['pc'])))
            else:
                counts[match] += site['count']
        placed = sum(s['count'] for s in missing.get(kind + '_read_sites',
                                                    []))
        if placed != missing[kind + '_reads'] and \
                not missing.get('read_sites_lost'):
            found.append('%s reads: %d, of which %d by known instructions'
                         % (kind, missing[kind + '_reads'], placed))
        for k, count in counts.items():
            if count and count != k.count:
                found.append('%s reads of %s:%s from %s: %d, not %d'
                             % (kind, k.unit, k.label, k.symbol, count,
                                k.count))
    return found


def problems(state: Dict, log: Sequence[marks.Entry],
             symbols: script.Symbols, program: str = '') -> List[str]:
    """What makes the run meaningless (see the module's docstring);
    `program` is the input program, to say where a wait was."""
    found = []
    end = state['end']
    if end['reason'] == 'stop-pc':
        text = ' / '.join(row.strip() for row in state['text_page']
                          if row.strip())
        found.append('the game reached %s; the text page says: %s'
                     % (label_of(symbols, end['pc']), text))
    elif end['reason'] == 'spin':
        found.append('the CPU spins at %s' % label_of(symbols, end['pc']))
    elif end['reason'] == 'opcode':
        found.append('the CPU executed WDM or STP at %s'
                     % label_of(symbols, end['pc']))
    elif end['reason'] == 'timeout':
        found.append('the wait of %s timed out at %.1f s'
                     % (source(program, end['line']), state['seconds']))
    elif end['reason'] == 'late':
        found.append('%s came after its frame'
                     % source(program, end['line']))
    elif end['reason'] != 'stop':
        found.append('the run hit its %s limit at %.1f s before the '
                     'script stopped' % (end['reason'], state['seconds']))
    missing = state['unmodelled']
    io = (set(missing['io_reads']) | set(missing['io_writes'])) - KNOWN_IO
    if io:
        found.append('I/O registers not modelled: %s' % ', '.join(sorted(io)))
    for name in ('rom_writes', 'slot_rom_reads', 'unmapped_writes',
                 'adb_unknown_commands'):
        if missing[name]:
            found.append('%s: %d' % (name, missing[name]))
    found += unexplained_reads(missing, symbols)
    if state['firmware']['errors']:
        found.append('%d firmware errors' % state['firmware']['errors'])
    gap = marks.longest_gap(log, symbols.address(':'.join(LOOP)))
    if gap is None:
        found.append('the main loop never ran')
    elif gap['cycles'] > STUCK_CYCLES:
        found.append('the main loop did not come round for %d cycles '
                     '(%.1f s) from %.1f s' % (gap['cycles'], gap['seconds'],
                                               gap['from']))
    return found


class Run:
    """One run of a script: its files and results."""

    def __init__(self, directory: Path, shots: Path):
        self.directory = directory
        self.shots = shots
        self.input = directory / 'input.txt'
        self.state_path = directory / 'state.json'
        self.marks_path = directory / 'marks.txt'
        self.dumps = directory / 'dumps'

    def execute(self, program: str, symbols: script.Symbols,
                cpu_hz: Optional[int], limit_seconds: float,
                extra: Sequence[str] = ()) -> Dict:
        """Run the machine; `extra` are more of its options (such as
        those of a trace)."""
        for path in (self.directory, self.shots):
            if path.exists():
                shutil.rmtree(str(path))
        self.dumps.mkdir(parents=True)
        self.shots.mkdir(parents=True)
        self.input.write_text(program)
        options = ['--input', str(self.input), '--shot-dir', str(self.dumps),
                   '--stop-on-fault', '--marks', str(self.marks_path),
                   '--state', str(self.state_path),
                   '--frames', str(script.frames(limit_seconds))]
        if cpu_hz:
            options += ['--cpu-hz', str(cpu_hz)]
        for unit, name in STOPS:
            options += ['--stop-pc', '%06X' % symbols.address(unit + ':' +
                                                              name)]
        for unit, name in (LOOP, RENDER):
            options += ['--mark', '%06X' % symbols.address(unit + ':' + name)]
        command = [str(title.MACHINE), str(title.MEMORY), '--disk',
                   str(title.DISK)] + options + list(extra)
        result = subprocess.run(command, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                universal_newlines=True)
        if result.returncode:
            raise RuntimeError('ref816 failed: ' + result.stderr)
        return json.loads(self.state_path.read_text())

    def pictures(self) -> Dict[str, Dict]:
        """Each dump as a PNG in the shots directory, with its stats and
        those of the game's view (shot.view_stats)."""
        out = {}
        for dump in sorted(self.dumps.glob('*.shr')):
            target, info = shot.convert(dump, self.shots)
            view = shot.view_stats(dump.read_bytes())
            out[dump.stem] = {
                'png': str(target), 'colours': info.colours,
                'commonest_share': info.commonest_share,
                'view': view._asdict(),
                'full_3d_view': shot.full_3d_view(view)}
        return out


def run(path: Path, cpu_hz: Optional[int] = None, twice: bool = False,
        limit_seconds: float = DEFAULT_LIMIT_SECONDS, runs: Path = RUNS,
        shots: Path = SHOTS) -> Dict:
    """Run the script at `path` and return its report (also written to
    RUNS/NAME/report.json)."""
    name = path.stem
    with open(str(make_image.LINKMAP)) as handle:
        symbols = script.Symbols(json.load(handle))
    program = script.compile_script(path.read_text(), symbols, path.name)
    first = Run(runs / name, shots / name)
    state = first.execute(program, symbols, cpu_hz, limit_seconds)
    log = marks.read(first.marks_path)
    render = symbols.address(':'.join(RENDER))
    report = {
        'script': str(path), 'cpu_hz': state['cpu_hz'],
        'end': state['end'], 'seconds': state['seconds'],
        'frames': state['frames'], 'cycles': state['cycles'],
        'instructions': state['instructions'],
        'ram_fnv1a64': state['ram_fnv1a64'],
        'problems': problems(state, log, symbols, program),
        'software_interrupts': {
            'brk': state['opcodes']['brk'], 'cop': state['opcodes']['cop'],
            'first': label_of(symbols, state['opcodes']['first_brk_pc'])
            if state['opcodes']['brk'] + state['opcodes']['cop'] else None},
        'shots': first.pictures(),
        'intervals': [i._asdict() for i in marks.intervals(log, render)],
    }
    if twice:
        second = Run(runs / (name + '-again'),
                     runs / (name + '-again') / 'shots')
        again = second.execute(program, symbols, cpu_hz, limit_seconds)
        same_dumps = all(
            dump.read_bytes() == (second.dumps / dump.name).read_bytes()
            for dump in first.dumps.glob('*.shr'))
        report['deterministic'] = (
            again['ram_fnv1a64'] == state['ram_fnv1a64'] and
            again['cycles'] == state['cycles'] and same_dumps and
            second.marks_path.read_bytes() == first.marks_path.read_bytes())
        if not report['deterministic']:
            report['problems'].append('a second run differs')
        shutil.rmtree(str(second.directory))
    (first.directory / 'report.json').write_text(
        json.dumps(report, indent=2) + '\n')
    return report


def summary(report: Dict) -> str:
    lines = ['%s at %.0f Hz: %s after %.1f s of machine time, %d frames, '
             'RAM %s' % (report['script'], report['cpu_hz'],
                         report['end']['reason'], report['seconds'],
                         report['frames'], report['ram_fnv1a64'])]
    soft = report['software_interrupts']
    if soft['first']:
        lines.append('  BRK %d, COP %d, the first at %s'
                     % (soft['brk'], soft['cop'], soft['first']))
    if 'deterministic' in report:
        lines.append('  same run twice: %s' % report['deterministic'])
    for name, info in report['shots'].items():
        view = info['view']
        lines.append('  shot %s: %d colours; view: %d colours, %d different '
                     'rows, %dx%d%s' % (
                         name, info['colours'], view['view_colours'],
                         view['distinct_rows'], view['window'][2],
                         view['window'][3],
                         ', a 3D view' if info['full_3d_view'] else ''))
    for i in report['intervals']:
        cost = ''
        if i['median_cycles'] is not None:
            cost = ', a frame %.0f instructions, %.0f cycles (median of ' \
                   '%d)' % (i['median_instructions'], i['median_cycles'],
                            i['frames_measured'])
        lines.append('  %s to %s: %.2f s, %d 3D frames, %.2f a second%s'
                     % (i['start'], i['end'], i['seconds'], i['rendered'],
                        i['frames_per_second'], cost))
    for problem in report['problems']:
        lines.append('  PROBLEM: ' + problem)
    return '\n'.join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('scripts', nargs='+')
    parser.add_argument('--cpu-hz', type=int)
    parser.add_argument('--twice', action='store_true')
    parser.add_argument('--limit', type=float, default=DEFAULT_LIMIT_SECONDS,
                        help='seconds of machine time at most')
    arguments = parser.parse_args(argv)
    for path in (make_image.RELEASE_IMAGE, make_image.LINKMAP):
        if not path.exists():
            print('%s is missing: run python3 tools/fetch_upstream.py and '
                  'python3 tools/v816/imgmatch.py first' % path,
                  file=sys.stderr)
            return 1
    title.build_machine()
    title.ensure_image()
    failed = False
    for name in arguments.scripts:
        try:
            report = run(script_path(name), arguments.cpu_hz,
                         arguments.twice, arguments.limit)
        except (FileNotFoundError, script.ScriptError) as error:
            print(error, file=sys.stderr)
            return 1
        print(summary(report))
        failed = failed or bool(report['problems'])
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
