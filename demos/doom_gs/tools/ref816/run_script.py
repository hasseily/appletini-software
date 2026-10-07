"""What makes a run of an input script on ref816 meaningless (problems),
the script's path (script_path), and the stops and marks the machine is
run with (STOPS, LOOP, RENDER): tools/native/rendercap.py's runs.

The run is watched for the game's error screen or its quit screen (the
machine stops at I_Error and I_Quit), a branch to itself and the opcodes
that only a CPU running data would meet, WDM and STP (--stop-on-fault),
a wait of the script that times out, I/O registers the machine does not
model (but the serial controller, which the game only switches off),
reads of the ROM or of a bank with no memory outside KNOWN_READS,
firmware errors, and a main loop that stops coming round (no call of
display for STUCK_CYCLES CPU cycles after the first). BRK and COP are
not faults: they go through the game's own vectors (upstream's
R_InitLists returns into 14 bytes of zero padding, 7 BRKs whose vector
is an RTI).
"""

import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import make_image, marks, script  # noqa: E402

ROOT = make_image.ROOT
COVERAGE = ROOT / 'coverage'

STOPS = (('i_iigs65.s', 'I_Error'), ('i_iigs65.s', 'I_Quit'))
LOOP = ('d_main65.s', 'displayCall')
RENDER = ('r_frame65.s', 'R_RenderPlayerView')
# Registers the machine leaves out on purpose: the serial controller,
# which the game only switches off.
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
