#!/usr/bin/env python3
"""Part plinput's a2vm runs, checkpoint and planted bugs (milestone 11;
docs/SCREENS.md 2.4, 6.4, 6.5, 7.3; docs/m11-parts/plinput.md).

A run: the input's test image (build/native/m11/plinput/plit: MENUW's room,
the test driver s2_drv with pl_vbl the handler, S2's player in the card,
pl_it.s's plt_run) over one sequence of tools/native/plmodel.py at 6, 10
or 35 polls a second under a cost profile with --cost-timed: the schedule
at main $A000 (8 bytes a poll), the sequence's a2vm input events at the
boundaries (plt_polled, right after each pl_poll) and at pl_xhi (a report
between the two reads of X). Each boundary: a snapshot (main $0000-$03FF,
the key table $1F80-$1FFF, the schedule, the card's clock) and a cost line
(phase 31: the poll). The checks, at every poll: the input block
$03B3-$03ED and the key table equal to the model's; the clock's tics the
poll's; pl_action's answers; the write log: pl_input.o's code writes only
the input block, its zero page and the mouse's X, pl_keys.o's also the key
table and the mouse's window; the stack.

Every run is bounded (cycles, wall time, file sizes) in a tempfile
directory under build/ that is deleted after it.

Usage:
  python3 tools/native/plinput.py --checkpoint [--jobs J]   the checkpoint,
                     every sequence at 6, 10, 35 polls a second (f121), at
                     35 on fastpath; the timing, the sizes; report.json
  python3 tools/native/plinput.py --planted [--jobs J]      the planted
                     bugs, each in a scratch copy of the sources
  python3 tools/native/plinput.py --one NAME [--rate R]     one sequence
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from a2vm import costs  # noqa: E402
from native import lrun, plkeys as K, plmodel as M, rlayout as R, \
    s2layout as S, s2run as SR  # noqa: E402
from ref816 import bounded  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
PART = BUILD / 'native' / 'm11' / 'plinput'
SOURCE = ROOT / 'src' / 'native'
SOUND65 = BUILD / 'sound65'
A2VM = SR.A2VM
RUN_TIMEOUT = 300.0
MAX_FILE = 32 << 20
WRITE_LOG_LIMIT = 2_000_000
JOBS = 2
STD_PAL = 0x00
SCHED = 0xA000                  # pl_it.s's PLT_SCHED
ENTRY = 8
PROFILES = ('f121', 'fastpath')
BUDGET_POLL = 600               # SCREENS.md 4.1: pl_poll
PLZ_RANGE = S.PL_ZP              # PLZ: 16 bytes (PLINPUT-4)
GLUE_ZP = (0x80, 0x82)          # pl_it.s's PTR
MOUSE_X_IO = frozenset({0xC0A1, 0xC0A2})
MOUSE_WINDOW_IO = frozenset(range(0xC0A7, 0xC0AD))
KEYTAB = (M.KEYTAB, M.KEYTAB + 128)
BLOCK = (S.INPUT_LO, S.INPUT_END)


class InputError(Exception):
    pass


def make(m11: Optional[Path] = None, source: Optional[Path] = None) -> None:
    SR.make('plinput', m11=m11 or SR.M11, source=source or SR.SOURCE)


def have_prerequisites() -> bool:
    return SR.A2VM.exists() and (SOUND65 / 'player.o').exists() and \
        (SR.TABLES / 'math' / 'squares.bin').exists()


def load(part: Path = PART) -> SR.Build:
    return SR.load_build(part, 'plit', 'MENUW')


def module_ranges(b: SR.Build) -> Dict[str, List[Tuple[int, int]]]:
    """Each module's segments in the image: [(first, last)] inclusive, from
    ld65's map (the module list's offsets in each segment)."""
    text = (b.obj / (b.name + '.map')).read_text()
    out: Dict[str, List[Tuple[int, int]]] = {}
    part = text.split('Segment list:')[0]
    module = None
    for line in part.splitlines():
        m = re.match(r'^(\S+)\.o:\s*$', line)
        if m:
            module = m.group(1)
            continue
        m = re.match(r'^\s+(\w+)\s+Offs=([0-9A-F]+)\s+Size=([0-9A-F]+)',
                     line)
        if m and module and m.group(1) in b.segments:
            lo = b.segments[m.group(1)][0] + int(m.group(2), 16)
            size = int(m.group(3), 16)
            if size:
                out.setdefault(module, []).append((lo, lo + size - 1))
    return out


def sizes(part: Path = PART) -> Dict[str, Any]:
    b = load(part)
    ms = S.read_map((part / 'plit.map').read_text()).modules
    return {'pl_input': ms.get('pl_input', 0), 'pl_poll_budget': BUDGET_POLL,
            'pl_keys': ms.get('pl_keys', 0),
            'room': (part / 'plit.sizes').read_text().splitlines()[-1],
            'segments': {k: sum(hi + 1 - lo for lo, hi in v) for k, v in
                         module_ranges(b).items() if k.startswith('pl_')}}


# ---------------------------------------------------------------------------
# A run
# ---------------------------------------------------------------------------

class SeqRun(NamedTuple):
    name: str
    rate: int
    profile: str
    ended: str
    status: Optional[int]
    blocks: List[bytes]
    tables: List[bytes]
    tics: List[int]
    sched: bytes                        # the schedule at the stop
    poll_ms: List[float]
    stray: Tuple[int, List[str]]
    stack: Optional[int]                # the deepest S below the driver's


def schedule_bytes(seq: M.Sequence_, rate: int) -> bytes:
    out = bytearray()
    for t, p in zip(M.tics(rate, len(seq.polls)), seq.polls):
        out += bytes([t & 0xFF, t >> 8, p.menu, p.flags, p.a4 & 0xFF,
                      p.a5 & 0xFF, 0, 0])
    return bytes(out)


def owners(b: SR.Build) -> List[SR.Owner]:
    mods = module_ranges(b)
    block = ('main', 0) + BLOCK
    plz = ('main', 0) + PLZ_RANGE
    glue_data = b.segments.get('S2DATA')
    out = [SR.driver_owner(b), SR.loader_owner(b, (SR.image_load(b),)),
           SR.Owner('pl_input', tuple(mods['pl_input']), (block, plz),
                    MOUSE_X_IO),
           SR.Owner('pl_keys', tuple(mods['pl_keys']),
                    (block, plz, ('main', 0) + KEYTAB),
                    MOUSE_X_IO | MOUSE_WINDOW_IO),
           SR.Owner('pl_it', tuple(mods['pl_it']),
                    (('main', 0, R.PHASE, R.PHASE + 1),
                     ('main', 0, S.INPUT['PL_QHEAD'], S.INPUT['PL_QHEAD'] + 1),
                     ('main', 0, S.INPUT['PL_MDX'], S.INPUT['PL_MDX'] + 2),
                     ('main', 0, M.LO + M.OFF['PL_BIND'],
                      M.LO + M.OFF['PL_BIND'] + 1),
                     ('main', 0, SCHED, SCHED + 256 * ENTRY),
                     ('main', 0) + GLUE_ZP,
                     ('main', 0, glue_data[0], glue_data[1] + 1)),
                    frozenset({0xC0AE})),
           # the clock, the handler, S2's player (snd_init, snd_tick), the
           # effect player (fx_init, fx_step, fx_burst): the card and the
           # IRQ's zero page (MEMORY_MAP.md rule 2)
           SR.Owner('irq+player', tuple(mods.get('pl_irq', []) +
                                        mods.get('player', []) +
                                        mods.get('fx-card', [])),
                    (('main', 0, 0xD8, 0x100), ('lc', 0, 0xE000, 0x10000)),
                    frozenset(range(0xC0A0, 0xC0B0)) |
                    frozenset(range(0xC400, 0xC500)))]
    return out


def boot_records(pl_bind: int = M.BIND_IDLE) -> List[Tuple[int, int, int,
                                                             bytes]]:
    """The input block as pl_init leaves it (the model's), with PL_BIND,
    and the key table's defaults: what another part's runs start a frame
    image with (wave 5's integration; S2WI-3)."""
    block = M.Input()
    block.init()
    block.put('PL_BIND', pl_bind)
    return [(0, 0, BLOCK[0], bytes(block.mem)),
            (0, 0, KEYTAB[0], bytes(block.keys))]


def image_owners(b: SR.Build) -> List[SR.Owner]:
    """The input's writers in another image's write log (the frame images
    that link pl_poll, MENUW's pl_keys; wave 5's integration): pl_poll the
    input block, PLZ and the mouse's X; pl_keys also the key table and the
    mouse's window; pl_irq.s's pl_time (in the card, as the release) only
    CLK_TIME3, as it runs under the test driver's handler there."""
    mods = module_ranges(b)
    block = ('main', 0) + BLOCK
    plz = ('main', 0) + PLZ_RANGE
    out = [SR.Owner('pl_input', tuple(mods['pl_input']), (block, plz),
                    MOUSE_X_IO)]
    if 'pl_keys' in mods:
        out.append(SR.Owner('pl_keys', tuple(mods['pl_keys']),
                            (block, plz, ('main', 0) + KEYTAB),
                            MOUSE_X_IO | MOUSE_WINDOW_IO))
    if 'pl_irq' in mods:
        t3 = S.CLOCK['CLK_TIME3']
        out.append(SR.Owner('pl_time', tuple(mods['pl_irq']),
                            (('lc', 0, t3, t3 + 1),), frozenset()))
    return out


def run_sequence(seq: M.Sequence_, rate: int, work: Path,
                 profile: str = 'f121', fill: int = 0xA5,
                 part: Path = PART) -> SeqRun:
    b = load(part)
    lab = b.labels
    n = len(seq.polls)
    work.mkdir(parents=True, exist_ok=True)
    calls = [SR.Call('plt_run', n, STD_PAL)]
    loads = (SR.image_load(b),)
    recs = SR.base_records(b, fill) + [
        (0, 0, SCHED, schedule_bytes(seq, rate)),
        SR.descriptor_record(b, loads, calls)]
    (work / 'image.bin').write_bytes(lrun.RC.image_bytes(recs))
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    (work / 'cost.txt').write_text(costs.text(profile))
    fabric = costs.parameters(profile)['fabric_mhz'] * 1e6
    seconds = M.tics(rate, n)[-1] / 34.9 + 2.0
    code = [b.segments[s] for s in S.IMG_SEGMENTS if s in b.segments]
    events = ['pc %X snapshot stop' % lab['s2d_stop'],
              'pc %X snapshot stop' % lab['pl_crash']]
    events += M.a2vm_events(seq, lab['pl_xhi'])
    (work / 'events.txt').write_text('\n'.join(events) + '\n')
    args = [str(A2VM), '--rom', str(work / 'rom.bin'),
            '--core', 'w65c02s', '--amem', '--via-ora-nh',
            '--image', str(work / 'image.bin'),
            '--switch', 'lc_read=1', '--switch', 'lc_write=1',
            '--switch', 'lc_bank2=0',
            '--reg', 'pc=%X' % lab['s2d_start'],
            '--reg', 's=%X' % S.DRV_STACK, '--reg', 'p=34',
            '--cost', str(work / 'cost.txt'), '--cost-timed',
            '--cost-phase', '%X' % R.PHASE,
            '--cost-report', str(work / 'cost.json'),
            '--cycles', str(int(seconds * fabric)),
            '--lowest-s-in', ','.join('%X-%X' % r for r in code),
            '--boundary', '%X' % lab['plt_polled'],
            '--snapshot-boundaries',
            '--state', str(work / 'state.json'),
            '--snapshot-dir', str(work),
            '--snapshot-ranges', 'main:0000-03FF,main:%04X-%04X,'
            'main:%04X-%04X,lc:E400-E41F' % (
                KEYTAB[0], KEYTAB[1] - 1, SCHED, SCHED + n * ENTRY - 1),
            '--idle', '%X:vbl:eq=%X,%X' % (lab['plt_idle'], lab['vbl_count'],
                                           lab['plt_seen']),
            '--irq-bounds', SR.IRQ_BOUNDS,
            '--write-log', SR.WRITE_LOG,
            '--write-log-file', str(work / 'writes.log'),
            '--write-log-limit', str(WRITE_LOG_LIMIT),
            '--input', str(work / 'events.txt'),
            '--stop-pc', '%X' % lab['s2d_stop'],
            '--stop-pc', '%X' % lab['pl_crash']]
    try:
        result = bounded.run(args, timeout=RUN_TIMEOUT, max_bytes=MAX_FILE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise InputError('a2vm did not finish in %d s' % RUN_TIMEOUT)
    state_path = work / 'state.json'
    if not state_path.exists():
        raise InputError('a2vm failed: %s' % result.stdout[-2000:])
    state = json.loads(state_path.read_text())
    pc = state.get('pc')
    # the driver's BRK reaches pl_vbl, whose crash stop ends the run
    ended = 'stop' if state.get('end') == 'stop-pc' and \
        pc in (lab['s2d_stop'], lab['pl_crash']) else '%s at $%04X%s' % (
            state.get('end'), pc or 0,
            (': ' + state['halt']) if state.get('halt') else '')
    blocks, tables, tics_ = [], [], []
    t = S.CLOCK['CLK_TICS'] - 0xC000
    for k in range(1, n + 1):
        p = work / ('boundary-%04d.img' % k)
        if not p.exists():
            break
        m = SR.read_snapshot(p)
        blocks.append(bytes(m.main[BLOCK[0]:BLOCK[1]]))
        tables.append(bytes(m.main[KEYTAB[0]:KEYTAB[1]]))
        tics_.append(int.from_bytes(bytes(m.lc[t:t + 2]), 'little'))
    status, sched = None, b''
    stop = work / 'stop.img'
    if stop.exists():
        m = SR.read_snapshot(stop)
        status = m.main[S.PL_STATUS]
        sched = bytes(m.main[SCHED:SCHED + n * ENTRY])
    mhz = costs.parameters(profile)['fabric_mhz']
    poll_ms = []
    cost_path = work / 'cost.json'
    if cost_path.exists():
        for line in cost_path.read_text().splitlines():
            if line.startswith('{"boundary"'):
                c = json.loads(line)
                poll_ms.append(c['phases'][S.PHASE_PLATFORM] / mhz / 1000.0)
    st = SR.stray(SR.read_writes(work / 'writes.log'), owners(b))
    low = state.get('lowest_s', {}).get('ranges', [])
    depths = [S.DRV_STACK - x['s'] for x in low if x.get('s') is not None]
    return SeqRun(seq.name, rate, profile, ended, status, blocks, tables,
                  tics_, sched, poll_ms, st, max(depths) if depths else None)


def describe_block(got: bytes, want: bytes) -> str:
    diffs = []
    for name, off in sorted(M.OFF.items(), key=lambda x: x[1]):
        n = {'PL_QUEUE': M.QBYTES, 'PL_MDX': 2, 'PL_MLX': 2,
             'PL_REPTIC': 2}.get(name, 1)
        if got[off:off + n] != want[off:off + n]:
            diffs.append('%s %s, the model %s' % (
                name, got[off:off + n].hex(), want[off:off + n].hex()))
    return '; '.join(diffs)


def problems_of(seq: M.Sequence_, r: SeqRun) -> List[str]:
    """The run against the model, poll by poll."""
    tag = '%s @%d %s' % (seq.name, r.rate, r.profile)
    out = []
    if r.ended != 'stop' or r.status != S.S2S['DONE']:
        out.append('%s: ended %s, status %s' % (tag, r.ended, r.status))
    want = M.run(seq, r.rate)
    times = M.tics(r.rate, len(seq.polls))
    if len(r.blocks) != len(seq.polls):
        out.append('%s: %d polls seen of %d' % (tag, len(r.blocks),
                                                len(seq.polls)))
    for k, (blk, tab) in enumerate(zip(r.blocks, r.tables)):
        if r.tics[k] != times[k]:
            out.append('%s: poll %d at tic %d, the schedule\'s %d' % (
                tag, k, r.tics[k], times[k]))
        if blk != want.blocks[k]:
            out.append('%s: poll %d: %s (the queue %s, the model %s)' % (
                tag, k, describe_block(blk, want.blocks[k]),
                _events(blk), want.events[k]))
            break
        if list(tab) != want.tables[k]:
            bad = [c for c in range(128) if tab[c] != want.tables[k][c]]
            out.append('%s: poll %d: the key table differs at %s' % (
                tag, k, ', '.join('$%02X' % c for c in bad[:6])))
            break
    for k, (a, x) in want.actions.items():
        got = tuple(r.sched[k * ENTRY + 6:k * ENTRY + 8])
        if got != (a, x):
            out.append('%s: poll %d: pl_action(%d) %s, the model %s' % (
                tag, k, seq.polls[k].a4, got, (a, x)))
    n, shown = r.stray
    if n:
        out.append('%s: %d stray writes: %s' % (tag, n, shown[:4]))
    return out


def _events(block: bytes) -> List[Tuple[int, int]]:
    st = M.Input()
    st.mem = bytearray(block)
    return st.events()


def check_one(seq: M.Sequence_, rate: int, profile: str, root: Path,
              part: Path = PART, fill: int = 0xA5) -> Dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix='run-', dir=str(root)))
    try:
        r = run_sequence(seq, rate, work, profile, fill, part)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return {'name': seq.name, 'rate': rate, 'profile': profile,
            'polls': len(r.blocks), 'problems': problems_of(seq, r),
            'poll_ms': r.poll_ms, 'stack': r.stack,
            'events': sum(len(e) for e in M.run(seq, rate).events)}


def stats(values: Sequence[float]) -> Dict[str, float]:
    v = sorted(values)
    if not v:
        return {}
    return {'n': len(v), 'median': round(v[len(v) // 2], 4),
            'p99': round(v[min(len(v) - 1, (99 * len(v)) // 100)], 4),
            'worst': round(v[-1], 4)}


def check_all(jobs: int = JOBS, part: Path = PART,
              plan: Optional[Sequence[Tuple[int, str]]] = None,
              names: Optional[Sequence[str]] = None,
              stop_on_problem: bool = False) -> Dict[str, Any]:
    """Every sequence (or those named) at each (rate, profile) of `plan`."""
    seqs = [s for s in M.sequences() if names is None or s.name in names]
    plan = plan or [(6, 'f121'), (10, 'f121'), (35, 'f121'),
                    (35, 'fastpath')]
    root = Path(tempfile.mkdtemp(prefix='tmp-m11-plinput-', dir=str(BUILD)))
    results: List[Dict[str, Any]] = []
    try:
        with ThreadPoolExecutor(max(1, min(jobs, 4))) as ex:
            futs = [ex.submit(check_one, s, rate, prof, root, part,
                              0xA5 if i % 2 == 0 else 0x5A)
                    for i, (rate, prof) in enumerate(plan) for s in seqs]
            for f in futs:
                results.append(f.result())
                if stop_on_problem and results[-1]['problems']:
                    for g in futs:
                        g.cancel()
                    break
    finally:
        shutil.rmtree(str(root), ignore_errors=True)
    problems = [p for r in results for p in r['problems']]
    timing = {}
    for prof in sorted({p for _, p in plan}):
        ms = [v for r in results if r['profile'] == prof
              for v in r['poll_ms'] if v > 0]
        timing[prof] = stats(ms)
    return {'sequences': len(seqs), 'runs': len(results),
            'polls': sum(r['polls'] for r in results),
            'events': sum(r['events'] for r in results),
            'stack': max((r['stack'] or 0) for r in results) if results
            else None,
            'timing_ms': timing, 'problems': problems}


# ---------------------------------------------------------------------------
# The planted bugs (each in a scratch copy of the sources)
# ---------------------------------------------------------------------------

PLANTED: Tuple[Tuple[str, str, str, str], ...] = (
    ('the auto-repeat posting a key down', 'pl_input.s',
     '        cpy PL_HELD\n        beq @keys               ; the held key '
     'again: the //e\'s repeat\n',
     '        cpy PL_HELD\n        nop\n        nop\n'),
    ('the held key not going up when another comes', 'pl_input.s',
     '@new:   tya\n        tax                     ; the new key is held\n',
     '@new:   ldx PL_HELD\n        bne :+\n        tya\n        tax\n:\n'),
    ('the tap\'s up in the same poll', 'pl_input.s',
     '        bpl @new                ; up already: a tap\n',
     '        bmi :+\n        ldx #0\n        bra @keys\n:\n'),
    ('the mouse\'s sequence byte not re-read', 'pl_input.s',
     '        cpx MOUSE_SEQ\n        beq pl_mxok\n',
     '        bra pl_mxok\n'),
    ('the counts not shared by two keys of one Doom key', 'pl_input.s',
     '        ora PLZ_M,y\n        sta PLZ_M,y\n',
     '        eor PLZ_M,y\n        sta PLZ_M,y\n'),
    ('a lower-case code not folded (typing p fires mouse 2)', 'pl_input.s',
     '        sbc #$1F                ; (carry clear: less $20)\n', ''),
    ('a full queue dropping a key instead of deferring it', 'pl_input.s',
     '        bcc @room\n', '        bra @room\n'),
    # not one of SCREENS.md 7.3's: the write log's check of 6.5's "the
    # state only in $03B3-$03ED" (a byte below the block, which no
    # snapshot comparison reads)
    ('the poll keeping a byte below the block', 'pl_input.s',
     '        stz PLZ_CH\n', '        stz PLZ_CH\n        stz PL_QUEUE-1\n'),
)


def plant(dest: Path, file: str, old: str, new: str) -> Path:
    """A scratch copy of the sources the build reads (src/native's m11.mk,
    m11/s2lay.mk, m11/plinput.mk and the part's sources) with one change;
    the others come from the tree (m11.mk's vpath)."""
    src = dest / 'src'
    (src / 'm11').mkdir(parents=True)
    for name in ('m11.mk', 'pl_input.s', 'pl_keys.s', 'pl_input.inc',
                 'pl_it.s'):
        shutil.copy2(str(SOURCE / name), str(src / name))
    for name in ('s2lay.mk', 'plinput.mk'):
        shutil.copy2(str(SOURCE / 'm11' / name), str(src / 'm11' / name))
    text = (src / file).read_text()
    if text.count(old) != 1:
        raise InputError('the planted change\'s text is not once in %s'
                         % file)
    (src / file).write_text(text.replace(old, new))
    return src


def planted(jobs: int = JOBS, rates: Sequence[int] = (10, 35)
            ) -> List[Dict[str, Any]]:
    """Each planted bug's build and the sequences at `rates` (f121): the
    problems it made (each must be caught)."""
    out = []
    root = Path(tempfile.mkdtemp(prefix='tmp-m11-plinput-planted-',
                                 dir=str(BUILD)))
    try:
        for i, (what, file, old, new) in enumerate(PLANTED):
            d = root / ('p%d' % i)
            src = plant(d, file, old, new)
            m11 = d / 'm11'
            SR.make('plinput', m11=m11, source=src)
            res = check_all(jobs, m11 / 'plinput',
                            plan=[(r, 'f121') for r in rates],
                            stop_on_problem=False)
            out.append({'bug': what, 'problems': len(res['problems']),
                        'first': res['problems'][:2]})
            shutil.rmtree(str(d), ignore_errors=True)
    finally:
        shutil.rmtree(str(root), ignore_errors=True)
    return out


# ---------------------------------------------------------------------------

def model_problems() -> List[str]:
    """The host side's own checks: the key table's rules; pl_keys.s's
    defaults equal to plkeys.DEFAULTS (read from the source); the model's
    sequences well formed."""
    out = list(K.problems())
    text = (SOURCE / 'pl_keys.s').read_text()
    body = text.split('pl_defs:', 1)[1].split('DEFAULTS_SIZE', 1)[0]
    vals: List[int] = []
    for line in body.splitlines():
        line = line.split(';', 1)[0].strip()
        if not line.startswith('.byte'):
            continue
        for item in re.findall(r"'.'|\$[0-9A-Fa-f]+|\d+", line[5:]):
            if item.startswith("'"):
                vals.append(ord(item[1]))
            elif item.startswith('$'):
                vals.append(int(item[1:], 16))
            else:
                vals.append(int(item))
    pairs = sorted(zip(vals[0::2], vals[1::2]))
    if pairs != sorted(K.DEFAULTS):
        out.append('pl_keys.s\'s defaults differ from plkeys.DEFAULTS')
    for s in M.sequences():
        M.torn_visit(s)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--checkpoint', action='store_true')
    parser.add_argument('--planted', action='store_true')
    parser.add_argument('--one')
    parser.add_argument('--rate', type=int, default=35)
    parser.add_argument('--profile', default='f121')
    parser.add_argument('--jobs', type=int, default=JOBS)
    parser.add_argument('--no-build', action='store_true')
    args = parser.parse_args(argv)
    if not args.no_build:
        make()
    if args.one:
        seq = next(s for s in M.sequences() if s.name == args.one)
        res = check_all(1, plan=[(args.rate, args.profile)],
                        names=[seq.name])
        print(json.dumps(res, indent=1))
        return 1 if res['problems'] else 0
    if args.checkpoint:
        mp = model_problems()
        res = check_all(args.jobs)
        res['model_problems'] = mp
        res['sizes'] = sizes()
        PART.mkdir(parents=True, exist_ok=True)
        (PART / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
        print('%d sequences, %d runs, %d polls, %d events; stack %s B' % (
            res['sequences'], res['runs'], res['polls'], res['events'],
            res['stack']))
        for prof, t in res['timing_ms'].items():
            print('%s: a poll %s ms' % (prof, t))
        print('sizes: pl_input %d of %d B, pl_keys %d B' % (
            res['sizes']['pl_input'], BUDGET_POLL, res['sizes']['pl_keys']))
        bad = mp + res['problems']
        print('checkpoint %s: %d problems' % ('passes' if not bad else
                                              'FAILS', len(bad)))
        for p in bad[:20]:
            print('  ' + p)
        return 1 if bad else 0
    if args.planted:
        res = planted(args.jobs)
        for r in res:
            print('%-55s %s (%d problems) %s' % (
                r['bug'], 'caught' if r['problems'] else 'MISSED',
                r['problems'], r['first'][:1]))
        return 0 if all(r['problems'] for r in res) else 1
    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
