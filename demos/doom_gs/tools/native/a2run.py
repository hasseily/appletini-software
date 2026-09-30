"""Run the native replay's test image on a2vm and read what it left.

The image is tools/native/loader.py's; its driver (src/native/driver.s)
calls the replay once a batch between drv_callK and drv_retK. A run can
take a snapshot at each of those points (the whole machine: main, both
language-card parts, all 128 aux banks), and can run under a2vm's cost
model (tools/a2vm/README.md, "The cost model") with the driver marking
the replay as phase 1 through the byte PHASE (--cost-phase), and can log
every CPU write into chosen ranges (a2vm's --write-log, tools/a2vm/
README.md "The write log"), which shows a store of the value already
there, as the snapshots cannot.

a2vm is used through its command line.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from a2vm import costs  # noqa: E402
from native import layout as L  # noqa: E402

A2VM = ROOT / 'build' / 'a2vm' / 'a2vm'
CYCLE_LIMIT = 400_000_000

# a snapshot's RAM (tools/a2vm/main.c write_ram)
MAIN = 0
LC = 0x10000                    # $C000-$FFFF, bank 2 at $D000
LC1 = 0x14000                   # bank 1 $D000-$DFFF
AUX = 0x15000                   # then bank n at AUX + n * $10000
RAM_SIZE = AUX + 128 * 0x10000


def aux_offset(bank: int, address: int) -> int:
    return AUX + bank * 0x10000 + address


class Snapshot(NamedTuple):
    state: Dict
    ram: bytes

    def aux0_screen(self) -> bytes:
        at = aux_offset(0, L.SCREEN)
        return self.ram[at:at + L.SCREEN_SIZE]


def read_snapshot(directory: Path, name: str) -> Snapshot:
    return Snapshot(json.loads((directory / (name + '.json')).read_text()),
                    (directory / (name + '.ram')).read_bytes())


def last_json_object(text: str) -> Dict:
    """The last JSON object of a cost report (one object a boundary, then
    the final one, each over several lines)."""
    start = text.rfind('{"final"')
    if start < 0:
        raise ValueError('no final record in the cost report')
    return json.loads(text[start:])


def run(image: Path, labels: Dict[str, int], directory: Path,
        batches: int, snapshots: bool = False,
        profile: Optional[str] = None, a2vm: Path = A2VM,
        write_log: Optional[str] = None) -> 'Run':
    """One run of the test image. `profile` (f121, fastpath...) turns the
    cost model on, timed, with the replay as phase 1. `write_log`: a2vm's
    --write-log ranges (stray_ranges() for instance); the run's `writes`
    are then the logged writes."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rom = directory / 'rom.bin'
    if not rom.exists():
        rom.write_bytes(bytes(0x4000))
    args = [str(a2vm), '--rom', str(rom), '--core', 'w65c02s',
            '--image', str(image),
            '--switch', 'lc_read=1', '--switch', 'lc_write=1',
            '--switch', 'lc_bank2=0', '--switch', 'newvideo=0xC1',
            '--reg', 'pc=%X' % labels['drv_start'],
            '--reg', 's=%X' % L.DRV_STACK,
            '--reg', 'p=34',
            '--stop-pc', '%X' % labels['drv_halt'],
            '--stop-pc', '%X' % labels['drv_crash'],
            '--cycles', str(CYCLE_LIMIT),
            '--state', str(directory / 'state.json')]
    if snapshots:
        events = []
        for k in range(batches):
            events.append('pc %X snapshot before%d'
                          % (labels['drv_call%d' % k], k))
            events.append('pc %X snapshot after%d'
                          % (labels['drv_ret%d' % k], k))
        (directory / 'events.txt').write_text('\n'.join(events) + '\n')
        args += ['--snapshot-dir', str(directory), '--input',
                 str(directory / 'events.txt')]
    log = directory / 'writes.log'
    if write_log:
        args += ['--write-log', write_log, '--write-log-file', str(log)]
    report = directory / 'cost.json'
    if profile:
        (directory / 'cost.txt').write_text(costs.text(profile))
        args += ['--cost', str(directory / 'cost.txt'), '--cost-timed',
                 '--cost-phase', '%X' % L.PHASE,
                 '--cost-report', str(report)]
    result = subprocess.run(args, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            universal_newlines=True)
    state_path = directory / 'state.json'
    if not state_path.exists():
        raise RuntimeError('a2vm failed: %s' % result.stdout)
    state = json.loads(state_path.read_text())
    cost = None
    if profile and report.exists():
        cost = last_json_object(report.read_text())['cost']
        cost['fabric_mhz'] = costs.parameters(profile)['fabric_mhz']
    shots = {}
    if snapshots:
        for k in range(batches):
            for name in ('before%d' % k, 'after%d' % k):
                if (directory / (name + '.ram')).exists():
                    shots[name] = read_snapshot(directory, name)
    writes = read_write_log(log) if write_log else None
    return Run(state, shots, cost, directory, labels, writes)


class Write(NamedTuple):
    """A line of a2vm's write log (tools/a2vm/README.md)."""
    clock: int                  # the machine's clock (the state's cycles)
    pc: int
    address: int
    storage: str                # main, aux, lc, lc1, or io
    bank: int
    offset: int
    old: Optional[int]
    new: int

    def describe(self) -> str:
        where = ('%s %d $%04X' % (self.storage, self.bank, self.offset)
                 if self.storage == 'aux' else
                 'I/O' if self.storage == 'io' else
                 '%s $%04X' % (self.storage, self.offset))
        old = '$%02X' % self.old if self.old is not None else '-'
        return '%s: %s -> $%02X (pc $%04X)' % (where, old, self.new, self.pc)


def read_write_log(path: Path) -> List[Write]:
    out = []
    for line in Path(path).read_text().splitlines():
        if line.startswith('#'):
            continue
        f = line.split()
        io = f[5] == 'io'
        out.append(Write(int(f[1]), int(f[3], 16), int(f[4], 16), f[5],
                         0 if io else int(f[6]), 0 if io else int(f[7], 16),
                         None if io else int(f[8], 16), int(f[9], 16)))
    return out


class Run(NamedTuple):
    state: Dict
    snapshots: Dict[str, Snapshot]
    cost: Optional[Dict]
    directory: Path
    labels: Dict[str, int]
    writes: Optional[List[Write]] = None

    def ended(self) -> str:
        """'halt' (the driver's end), 'crash' (a BRK), or a2vm's reason."""
        if self.state['end'] == 'stop-pc':
            if self.state['pc'] == self.labels['drv_halt']:
                return 'halt'
            if self.state['pc'] == self.labels['drv_crash']:
                return 'crash'
        return '%s at $%04X' % (self.state['end'], self.state['pc'])

    def replay_ms(self) -> float:
        """The time of phase 1 (the replay calls), in milliseconds."""
        clocks = self.cost['phases'][1]
        return clocks / (self.cost['fabric_mhz'] * 1000.0)

    def screen(self, batches: int) -> bytes:
        return self.snapshots['after%d' % (batches - 1)].aux0_screen()


# ---------------------------------------------------------------------------
# stray writes
# ---------------------------------------------------------------------------

def allowed_offsets(sp: int = L.DRV_STACK) -> List[Tuple[int, int]]:
    """The RAM offsets (snapshot coordinates) the replay may write when
    called with S = sp."""
    spans = [(MAIN + a, MAIN + b) for a, b in L.allowed_main(sp)]
    spans += [(aux_offset(0, a), aux_offset(0, b)) for a, b in
              L.ALLOWED_AUX0]
    return sorted(spans)


def complement(spans: Sequence[Tuple[int, int]], end: int = 0x10000
               ) -> List[Tuple[int, int]]:
    """The inclusive ranges of 0 .. end - 1 outside the half-open spans."""
    out, at = [], 0
    for start, stop in sorted(spans):
        if start > at:
            out.append((at, start - 1))
        at = max(at, stop)
    if at < end:
        out.append((at, end - 1))
    return out


def stray_ranges(sp: int = L.DRV_STACK) -> str:
    """a2vm --write-log ranges of everything the replay may not write when
    called with S = sp: main and aux bank 0 outside allowed_offsets(), and
    aux banks 1-127. The language card is left to the snapshots: the
    replay writes its row-block patches there and restores them."""
    items = ['main:%04X-%04X' % r for r in complement(L.allowed_main(sp))]
    items += ['aux0:%04X-%04X' % r for r in complement(L.ALLOWED_AUX0)]
    return ','.join(items + ['aux1-127'])


def describe(offset: int) -> str:
    if offset < LC:
        return 'main $%04X' % offset
    if offset < LC1:
        return 'card $%04X' % (offset - LC + 0xC000)
    if offset < AUX:
        return 'card bank 1 $%04X' % (offset - LC1 + 0xD000)
    bank, address = divmod(offset - AUX, 0x10000)
    return 'aux %d $%04X' % (bank, address)


def stray_writes(before: bytes, after: bytes,
                 allowed: Sequence[Tuple[int, int]] = None,
                 limit: int = 16) -> Tuple[int, List[str]]:
    """Bytes that differ outside the allowed spans (allowed_offsets() by
    default): (count, the first `limit` described)."""
    allowed = allowed_offsets() if allowed is None else allowed
    if len(before) != len(after):
        raise ValueError('snapshots of different sizes')
    count, shown = 0, []
    at = 0
    for start, end in list(allowed) + [(len(before), len(before))]:
        if before[at:start] != after[at:start]:
            for i in range(at, start):
                if before[i] != after[i]:
                    count += 1
                    if len(shown) < limit:
                        shown.append('%s: $%02X -> $%02X' % (
                            describe(i), before[i], after[i]))
        at = max(at, end)
    return count, shown


SWITCHES = ('store80', 'ramrd', 'ramwrt', 'altzp', 'lc_read', 'lc_write',
            'lc_bank2', 'bank')


def switch_changes(before: Dict, after: Dict) -> List[str]:
    return ['%s %s -> %s' % (name, before['switches'][name],
                             after['switches'][name])
            for name in SWITCHES
            if before['switches'][name] != after['switches'][name]]
