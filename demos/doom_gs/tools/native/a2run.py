"""Run the native replay's test image on a2vm and read what it left.

The image is tools/native/loader.py's; its driver (src/native/driver.s)
calls the replay once a batch between drv_callK and drv_retK. A run can
take a snapshot at each of those points (the whole machine: main, both
language-card parts, all 128 aux banks), and can run under a2vm's cost
model (tools/a2vm/README.md, "The cost model") with the driver marking
the replay as phase 1 through the byte PHASE (--cost-phase).

a2vm is used as it is, through its command line: nothing in tools/a2vm is
changed.
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
        profile: Optional[str] = None, a2vm: Path = A2VM) -> 'Run':
    """One run of the test image. `profile` (f121, fastpath...) turns the
    cost model on, timed, with the replay as phase 1."""
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
    return Run(state, shots, cost, directory, labels)


class Run(NamedTuple):
    state: Dict
    snapshots: Dict[str, Snapshot]
    cost: Optional[Dict]
    directory: Path
    labels: Dict[str, int]

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
