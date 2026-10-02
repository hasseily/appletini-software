#!/usr/bin/env python3
"""The tic level's reference side (milestone 10, docs/GAME.md 3.6, 3.7,
S3, S4): each fixed run on ref816, decoded tic by tic, and the inputs the
native lockstep run needs.

Usage:  python3 tools/native/ticcap.py --runs demo3,demo1,demo2,newgame,tour
                                       [--jobs 4]
        python3 tools/native/ticcap.py --tables      (S4)
        python3 tools/native/ticcap.py --report

One ref816 run a fixed run (gamecap.RUNS), at normal priority, bounded,
with

  --dump-at G_Ticker (each tic in a level: _g_gamestate 0) and at the
            RTL of P_MapEnd (each setup's end; setupcap.routines), the
            game state's banks (RANGES), streamed through a pipe and
            decoded as they come (the bridge's Reader in tic mode; never
            stored): one digest a kind a tic (gcanon.digests), and the
            per-tic facts below
  call logs (a named pipe): G_Ticker with the gametic, R_RenderPlayerView
            with the gametic (the schedule: the gametic of each 3D
            frame), P_SetupLevel with the map and skill, P_CheckSight
            with t1, t2 and CS_PREV1/2 at its entry (the same-pair hits;
            a zone t1 opens a T3 window), P_RemoveMobj with the mobj (a
            zone mobj CS_PREV names opens a T3 window), I_GetTime with
            its value (the game units' calls: the stream's values),
            G_DeferedInitNew with its skill and caller (the menu's
            actions), the cheats' effects (m_cheat65.s's table)

The results, in build/native/game/shared/tic/RUN.json.z (format
"game-tic-reference 1"): each tic's gametic, digests, validcount, zone
mobj count, CS_PREV1/2 (raw), command (the ring's entry G_Ticker copies)
and bridge problems; the schedule; the setups with their re-key records
(GAME.md 3.6: the hint of each pool slot, CS_PREV1/2 as native handles);
the T3 windows (from the first tic after the event to the next setup);
validcount's wraps and whether one falls in a window; the same-pair
hits a tic; the I_GetTime values; the menu's actions; the cheats; the
script's pokes. And RUN.stream: the native stream file (GTEST's GT_STREAM
format, src/native/game/README.md): per tic its command and its events.

--tables (S4): on every setup's R dump (milestone 9's 57), upstream's
LNSEC and SS_ROW (bank $21, p_sight65.s) against LNSECF, LNSECB and
RJROW of the native setup's machine of the map (the level bases of
gameroutine.py), and the hint re-keying a round trip: each dump's
re-key record written as the driver writes it and read back through the
game manifest's sighthint leaves, equal to the dump's sighthints.
"""

import argparse
import hashlib
import json
import os
import shutil
import statistics
import struct
import sys
import tempfile
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge import memory as bmem, upstream  # noqa: E402
from bridge.fields import R  # noqa: E402
from native import gamecap as GC, gcanon, glayout as GL, \
    llayout as LL  # noqa: E402
from ref816 import calls as CL, dumps  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
OUT = GL.SHARED / 'tic'
FORMAT = 'game-tic-reference 1'
STREAM_MAGIC = b'GSTR'
STREAM_VERSION = 1
# the banks the bridge's tic reader reads (measured on the setup dumps,
# docs/GAME.md "Skeleton as built"); a read outside them is a problem
RANGES = '00-10+22+24+32-3A'
RANGE_BANKS = set(range(0x00, 0x11)) | {0x22, 0x24} | set(range(0x32, 0x3B))
DUMP_LIMIT = 64 << 30           # through the pipe, never stored
CMD_SIZE = 8
CMDS = 8                        # the ring (g_game65.s: MAXTICS 4)
CHEATS = ('cheatChoppers', 'cheatGod', 'cheatKfa', 'cheatFa', 'cheatNoclip',
          'cheatBeholdV', 'cheatBeholdS', 'cheatBeholdI', 'cheatBeholdR',
          'cheatBeholdA', 'cheatBeholdL', 'cheatClev', 'cheatEnd',
          'cheatRocket', 'cheatRate')
EV_CHEAT, EV_POKE, EV_MENU, EV_INITNEW = 1, 2, 3, 4


class TicError(Exception):
    pass


class DumpMemory(bmem.Memory):
    """A dump's banks; a read outside them is recorded."""

    def __init__(self, d: dumps.Dump):
        super().__init__()
        at = 0
        for start, size in d.ranges():
            self.write(start, d.data[at:at + size])
            at += size
        self.outside: set = set()

    def _check(self, address: int) -> None:
        if (address >> 16) not in RANGE_BANKS:
            self.outside.add(address >> 16)

    def read(self, address: int, length: int) -> bytes:
        self._check(address)
        return super().read(address, length)

    def u8(self, address: int) -> int:
        self._check(address)
        return super().u8(address)

    def uint(self, address: int, size: int) -> int:
        self._check(address)
        return super().uint(address, size)


# ---------------------------------------------------------------------------
# Decoding a dump (in a worker process)
# ---------------------------------------------------------------------------

_SYMS: Dict[str, int] = {}


def _syms() -> Dict[str, int]:
    if not _SYMS:
        t = CL.Linkmap()
        for name in ('g_game65.s:_g_gametic', 'p_map65.s:validcount',
                     'p_sight65.s:CS_PREV1', 'p_sight65.s:CS_PREV2',
                     'g_game65.s:cmds', 'p_setup65.s:_g_thingPool',
                     'p_setup65.s:_g_thingPoolSize', 'g_game65.s:_g_gamemap'):
            _SYMS[name] = t.address(name)
    return _SYMS


def decode(header: Dict[str, Any], data: bytes,
           watch: Sequence[Tuple[int, int]] = ()) -> Dict[str, Any]:
    """One dump's per-tic record (and its state's sighthints and CS_PREV
    for a setup's re-key record); watch: (address, size) of the script's
    pokes, their values at the tic."""
    d = dumps.Dump(header, data)
    m = DumpMemory(d)
    s = _syms()
    r = upstream.Reader(m, tic=True)
    state = r.read()
    g = state['globals']
    tic = m.u32(s['g_game65.s:_g_gametic'])
    rec: Dict[str, Any] = {
        'tic': tic, 'point': header['point'], 'cycles': header['cycles'],
        'problems': r.problems[:5] + (['read outside the dump: banks %s' %
                                       sorted(m.outside)] if m.outside
                                      else []),
        'digest': gcanon.digests(state, 'tic'),
        # (T1 in FRONT runs: line.r_flags left out; the final integration)
        'digest_front': gcanon.digests(state, 'tic', front=True),
        'validcount': g.get('p_map65.s:validcount'),
        'zmobjs': len(state['objects'].get('zmobj', {})),
        'mobjs': len(state['objects'].get('mobj', {})),
        'cs_prev': [m.u32(s['p_sight65.s:CS_PREV1']) & 0xFFFFFF,
                    m.u32(s['p_sight65.s:CS_PREV2']) & 0xFFFFFF],
        'cs_state': [_ref_text(g.get('p_sight65.s:CS_PREV1')),
                     _ref_text(g.get('p_sight65.s:CS_PREV2'))],
        'pool': [m.u32(s['p_setup65.s:_g_thingPool']) & 0xFFFFFF,
                 m.u16(s['p_setup65.s:_g_thingPoolSize'])],
        'gamemap': m.u16(s['g_game65.s:_g_gamemap']),
        'cmd': m.read(s['g_game65.s:cmds'] + CMD_SIZE * (tic & (CMDS - 1)),
                      CMD_SIZE).hex(),
        'menu': [g.get('m_menu65.s:_g_menuactive', 0),
                 g.get('m_menu65.s:showMessages', 0)],
        'watch': [m.uint(a, n) for a, n in watch]}
    if header['point'] == 1:
        rec['hints'] = [state['objects']['sighthint'][i]['line']
                        for i in sorted(state['objects'].get('sighthint',
                                                             {}))]
        rec['cs_refs'] = [_ref_tuple(g.get('p_sight65.s:CS_PREV1')),
                          _ref_tuple(g.get('p_sight65.s:CS_PREV2'))]
    return rec


def _ref_text(v: Any) -> Any:
    if isinstance(v, R):
        return '%s[%s]' % (v.kind, v.id)
    return v


def _ref_tuple(v: Any) -> Any:
    if isinstance(v, R):
        return [v.kind, v.id]
    return v


def _decode_job(item) -> Dict[str, Any]:
    return decode(*item)


# ---------------------------------------------------------------------------
# The call logs
# ---------------------------------------------------------------------------

def log_routines(watch: Sequence[Tuple[int, int]] = ()) -> List[str]:
    # (G_Ticker with the command ring and the script's poked places at
    # every entry, whatever the game state: the stream of the runs on the
    # ring, newgame and tour, needs the intermission's commands too; the
    # frame with the display's view rows, viewtop being 9 under a message
    # strip, which the native frame takes as a render input: the final
    # integration)
    extra = ''.join('+%06X:%d' % (a, n) for a, n in watch)
    out = ['g_game65.s:G_Ticker,name=@tic,in=_g_gametic:4+'
           'g_game65.s:cmds:%d%s,entry=1' % (CMD_SIZE * CMDS, extra),
           'r_frame65.s:R_RenderPlayerView,name=@frame,in=_g_gametic:4+'
           'viewtop:2+viewbottom:2+automapmode:2,entry=1',
           # (jumps=1: a new life on the same map enters it by a JML,
           # m_menu65.s bmLoad)
           'p_setup65.s:P_SetupLevel,name=@setup,in=_g_gamemap:2+'
           '_g_gameskill:2+_g_gametic:4,entry=1,jumps=1',
           'p_sight65.s:P_CheckSight,name=@sight,in=dp:_Dp:8+'
           'p_sight65.s:CS_PREV1:4+p_sight65.s:CS_PREV2:4+_g_gametic:4,'
           'entry=1',
           'p_spawn65.s:P_RemoveMobj,name=@remove,in=dp:_Dp:4+'
           '_g_gametic:4,entry=1',
           'I_GetTime,name=@time,in=_g_gametic:4',
           'g_game65.s:G_DeferedInitNew,name=@initnew,in=_g_gametic:4,'
           'entry=1']
    out += ['m_cheat65.s:%s,name=@cheat:%s,in=_g_gametic:4,entry=1'
            % (c, c) for c in CHEATS]
    return out


class Logs:
    def __init__(self, callers: GC.CallerMap):
        self.callers = callers
        self.frames: List[int] = []
        self.frame_view: List[List[int]] = []
        self.tic_cmds: Dict[int, str] = {}
        self.tic_watch: Dict[int, List[int]] = {}
        self.watch: Sequence[Tuple[int, int]] = ()
        self.setups: List[Dict[str, Any]] = []
        self.sight: Dict[int, List[Tuple[int, int, int, int]]] = {}
        self.removes: List[Tuple[int, int]] = []
        self.times: List[Dict[str, Any]] = []
        self.initnew: List[Dict[str, Any]] = []
        self.cheats: List[Dict[str, Any]] = []
        self.end: Dict[str, Any] = {}

    def read(self, handle) -> None:
        first = json.loads(handle.readline())
        names = [r['name'] for r in first['routines']]
        for raw in handle:
            line = json.loads(raw)
            if line.get('end'):
                self.end = line
                break
            name = names[line['routine']]
            mem = b''.join(bytes.fromhex(x) for x in line['in']['mem'])
            if name == '@frame':
                self.frames.append(int.from_bytes(mem[:4], 'little'))
                self.frame_view.append([int.from_bytes(mem[k:k + 2],
                                                       'little')
                                        for k in (4, 6, 8)])
            elif name == '@tic':
                tic = int.from_bytes(mem[:4], 'little')
                at = 4 + CMD_SIZE * (tic & (CMDS - 1))
                self.tic_cmds[tic] = mem[at:at + CMD_SIZE].hex()
                at = 4 + CMD_SIZE * CMDS
                vals = []
                for a, n in self.watch:
                    vals.append(int.from_bytes(mem[at:at + n], 'little'))
                    at += n
                self.tic_watch[tic] = vals
            elif name == '@setup':
                self.setups.append({'gamemap': int.from_bytes(mem[0:2],
                                                              'little'),
                                    'skill': int.from_bytes(mem[2:4],
                                                            'little'),
                                    'tic': int.from_bytes(mem[4:8],
                                                          'little'),
                                    'cycles': line['cycles']})
            elif name == '@sight':
                t1, t2, p1, p2 = struct.unpack_from('<IIII', mem, 0)
                tic = int.from_bytes(mem[16:20], 'little')
                self.sight.setdefault(tic, []).append(
                    (t1 & 0xFFFFFF, t2 & 0xFFFFFF, p1 & 0xFFFFFF,
                     p2 & 0xFFFFFF))
            elif name == '@remove':
                self.removes.append((int.from_bytes(mem[4:8], 'little'),
                                     int.from_bytes(mem[0:4], 'little')
                                     & 0xFFFFFF))
            elif name == '@time':
                caller = self.callers.head(line['from'])
                out = line['out'] or {}
                self.times.append({
                    'tic': int.from_bytes(mem[:4], 'little'),
                    'caller': caller,
                    'value': ((out.get('x', 0) & 0xFFFF) << 16) |
                    (out.get('a', 0) & 0xFFFF)})
            elif name == '@initnew':
                self.initnew.append({
                    'tic': int.from_bytes(mem[:4], 'little'),
                    'skill': line['in']['a'] & 0xFFFF,
                    'caller': self.callers.head(line['from']) or
                    _label_at(line['from']), 'from': line['from']})
            elif name.startswith('@cheat:'):
                self.cheats.append({'tic': int.from_bytes(mem[:4], 'little'),
                                    'cheat': name[7:],
                                    'number': CHEATS.index(name[7:])})


# ---------------------------------------------------------------------------
# A run
# ---------------------------------------------------------------------------

def capture_run(run: str, jobs: int = 4, say=print,
                script_text: Optional[str] = None,
                extra: Sequence[str] = (), out: Path = OUT
                ) -> Dict[str, Any]:
    """The run's tic reference (the module's docstring)."""
    from native import setupcap
    GC.check_disk()
    syms = GC.symbols()
    r = setupcap.routines(syms)
    points = ['pc=%06X,if=%06X:2:eq:0,ranges=%s' % (
        syms.address('g_game65.s:G_Ticker'),
        syms.address('_g_gamestate'), RANGES),
        'pc=%06X,ranges=%s' % (r['mapend'], RANGES)]
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-tic-', dir=str(BUILD)))
    records: List[Dict[str, Any]] = []
    logs = Logs(GC.CallerMap())
    start = time.time()
    try:
        fifo = work / 'calls.fifo'
        os.mkfifo(str(fifo))
        text = script_text if script_text is not None else \
            GC.program(run, work)[0].read_text()
        pokes = script_pokes(text, syms)
        watch = [(p['address'], p['size']) for p in pokes]
        logs.watch = watch
        opts = CL.options(log_routines(watch), fifo) + [
            '--call-log-limit', str(4 << 30)]
        for p in points:
            opts += ['--dump-at', p]
        opts += ['--dump-stream', '-', '--dump-limit', str(DUMP_LIMIT)]
        opts += list(extra)

        def stream_reader(handle):
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                pending = []
                for d in dumps.read(handle):
                    pending.append(pool.submit(_decode_job,
                                               (d.header, d.data, watch)))
                    while len(pending) > 4 * jobs:
                        records.append(pending.pop(0).result())
                for f in pending:
                    records.append(f.result())

        res = GC.machine(run, work, opts, reader=logs.read, fifo=fifo,
                         stream_reader=stream_reader,
                         script_text=script_text)
        problems = res['problems']
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    result = summarise(run, records, logs, pokes)
    result['run_problems'] = problems
    result['seconds'] = round(time.time() - start, 1)
    out.mkdir(parents=True, exist_ok=True)
    (out / (run + '.json.z')).write_bytes(zlib.compress(json.dumps(
        result, separators=(',', ':')).encode(), 6))
    (out / (run + '.stream')).write_bytes(stream_bytes(result))
    say('%s: %d tics decoded (%d with bridge problems), %d setups, %d '
        'frames, %.0f s' % (run, result['tics_decoded'],
                            result['tics_with_problems'],
                            len(result['setups']), len(result['schedule']),
                            result['seconds']))
    return result


SIZES = {'byte': 1, 'word': 2, 'long': 4}


def script_pokes(text: str, syms) -> List[Dict[str, Any]]:
    """The script's pokes (ref816's script.py: poke [byte|word|long]
    SYMBOL VALUE): line, text, address, size, value."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        words = line.split('#')[0].split()
        if not words or words[0] != 'poke':
            continue
        args = words[1:]
        size = SIZES.get(args[0], 2) if args else 2
        if args and args[0] in SIZES:
            args = args[1:]
        out.append({'line': n, 'text': line.strip(),
                    'address': syms.address(args[0]), 'size': size,
                    'value': int(args[1], 0)})
    return out


def poke_events(tics: Sequence[Dict[str, Any]],
                pokes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each poke at the first tic whose G_Ticker entry sees its value
    after a tic that did not (the script's poke lands between two tics):
    its canonical global and field (the bridge's schema), the value, and
    the native address the manifest gives that field."""
    out = []
    for k, p in enumerate(pokes):
        prev = None
        for t in tics:
            v = t['watch'][k] if k < len(t.get('watch', [])) else None
            if v == p['value'] and prev is not None and prev != v:
                out.append(dict(p, tic=t['tic'], **_canonical_of(p)))
                break
            prev = v
    return out


def _canonical_of(p: Dict[str, Any]) -> Dict[str, Any]:
    """The canonical global and field a poked address is, and its place
    in the native globals (the game manifest's leaf)."""
    from bridge.upstream import Schema
    from bridge.fields import Struct
    sch = Schema()
    label = None
    for unit, labels in list(schema_globals().items()):
        for name, text in labels.items():
            try:
                a = sch.symbols.address('%s:%s' % (unit, name))
            except KeyError:
                continue
            t = sch.structs.get(text.split(':')[-1])
            size = t.size if isinstance(t, Struct) else 4
            if a <= p['address'] < a + size:
                label = ('%s:%s' % (unit, name), t, p['address'] - a)
    if label is None:
        return {'canonical': None}
    name, t, off = label
    field = t.field_at(off).name if t is not None and t.field_at(off) \
        else None
    out = {'canonical': [name, field] if field else [name]}
    try:
        from native import gameroutine as GR
        mf, _, _ = GR.manifest(1)
        leaf = next(lf for lf in mf.globals
                    if list(lf.path) == out['canonical'])
        plane = leaf.planes[0]
        if (plane >> 16) == 0x80:
            out['native'] = plane & 0xFFFF
    except (StopIteration, Exception):
        pass
    return out


def schema_globals() -> Dict[str, Dict[str, str]]:
    from bridge import schema
    out: Dict[str, Dict[str, str]] = {}
    for d in (schema.GLOBALS, schema.EXTERNAL_GLOBALS, schema.TIC_GLOBALS):
        for unit, labels in d.items():
            out.setdefault(unit, {}).update(labels)
    return out


def menu_events(tics: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The menu's state (menuactive, showMessages) at each tic it
    changes."""
    out = []
    prev = None
    for t in tics:
        m = t.get('menu')
        if prev is not None and m != prev:
            out.append({'tic': t['tic'], 'menuactive': m[0],
                        'showMessages': m[1]})
        prev = m
    return out


def summarise(run: str, records: List[Dict[str, Any]], logs: Logs,
              pokes: List[Dict[str, Any]]) -> Dict[str, Any]:
    tics = [x for x in records if x['point'] == 0]
    ends = [x for x in records if x['point'] == 1]
    # the setups and their re-key records
    setups = []
    ends = sorted(ends, key=lambda x: x['cycles'])
    for i, s in enumerate(logs.setups):
        # the setup's end: the first P_MapEnd return after its entry (by
        # the machine's cycles; P_MapEnd also runs outside the setups, so
        # the i-th return is not the i-th setup's: wave 1 as integrated,
        # docs/game-parts/flow.md request 7)
        e = next((x for x in ends if x['cycles'] > s['cycles']), None)
        rec = {'gamemap': s['gamemap'], 'skill': s['skill'], 'tic': s['tic']}
        if e is not None:
            rec['rekey'] = rekey_record_of(e).hex()
            rec['problems'] = e['problems']
        setups.append(rec)
    # the T3 windows: from the tic after an event to the next setup
    setup_tics = sorted(s['tic'] for s in logs.setups)
    pools = _pools([(x['tic'], x['pool']) for x in tics])
    events: List[Tuple[int, str]] = []
    for tic, calls in sorted(logs.sight.items()):
        for t1, t2, p1, p2 in calls:
            if _zone(t1, tic, pools):
                events.append((tic, 'zone t1 $%06X' % t1))
                break
    prev_by_tic = {x['tic']: x['cs_prev'] for x in tics}
    for tic, mo in logs.removes:
        prev = prev_by_tic.get(tic)
        if prev and mo in prev and _zone(mo, tic, pools):
            events.append((tic, 'zone mobj $%06X in CS_PREV removed' % mo))
    windows = []
    for tic, why in sorted(events):
        nxt = next((t for t in setup_tics if t > tic), None)
        if windows and windows[-1]['from'] <= tic + 1 <= (
                windows[-1]['to'] if windows[-1]['to'] is not None
                else 1 << 40):
            continue
        windows.append({'from': tic + 1, 'to': nxt, 'why': why})
    # validcount's wraps
    wraps = []
    for a, b in zip(tics, tics[1:]):
        va, vb = a['validcount'], b['validcount']
        if isinstance(va, int) and isinstance(vb, int) and vb < va:
            inside = any(w['from'] <= b['tic'] and (w['to'] is None or
                                                    b['tic'] < w['to'])
                         for w in windows)
            wraps.append({'tic': b['tic'], 'from': va, 'to': vb,
                          'in_window': inside})
    # the same-pair hits a tic
    hits = {}
    for tic, calls in logs.sight.items():
        n = sum(1 for t1, t2, p1, p2 in calls if (t1, t2) == (p1, p2))
        if n:
            hits[str(tic)] = n
    # the schedule: frames a tic
    sched = logs.frames
    per = {}
    for g in sched:
        per[g] = per.get(g, 0) + 1
    gaps = [b - a for a, b in zip(sched, sched[1:]) if b > a]
    reach = _tic_reach()
    game_times = [t for t in logs.times if t['caller'] in reach]
    start = min((s['tic'] for s in logs.setups), default=0)
    watch_tics = [{'tic': t, 'watch': v}
                  for t, v in sorted(logs.tic_watch.items())]
    return {
        'format': FORMAT, 'run': run,
        'tics': [{k: x[k] for k in ('tic', 'digest', 'digest_front',
                                    'validcount', 'zmobjs', 'mobjs',
                                    'cs_prev', 'cmd', 'problems')}
                 for x in tics],
        'tics_decoded': len(tics),
        'tics_with_problems': sum(1 for x in tics if x['problems']),
        'first_problems': [(x['tic'], x['problems']) for x in tics
                           if x['problems']][:5],
        'schedule': sched,
        'tics_a_frame': {'median': statistics.median(gaps) if gaps else None,
                         'counts': _count(gaps)},
        'setups': setups, 'windows': windows, 'wraps': wraps,
        'wraps_in_windows': sum(1 for w in wraps if w['in_window']),
        'same_pair_hits': hits,
        'times': game_times, 'all_times': len(logs.times),
        'menu_actions': logs.initnew, 'cheats': logs.cheats,
        'menu_states': menu_events(tics),
        'pokes': poke_events(watch_tics if watch_tics else tics, pokes),
        'frame_view': logs.frame_view,
        'tic_cmds': {str(t): c for t, c in sorted(logs.tic_cmds.items())
                     if t >= start},
        'zone_mobjs_most': max((x['zmobjs'] for x in tics), default=0),
        'call_log_end': logs.end.get('arrivals')}


def _label_at(address: int) -> Optional[str]:
    """The link map's label at or before a code address (a caller outside
    the game units: the menu's)."""
    from bridge.linkmap import Symbols
    best = None
    for f in Symbols().fragments:
        if f.kind == 'text' and f.address <= address < f.address + f.size:
            for lab in f.labels:
                if lab.address <= address:
                    best = '%s:%s' % (lab.unit, lab.name)
    return best


def _count(xs: Sequence[int]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for x in xs:
        out[str(x)] = out.get(str(x), 0) + 1
    return out


_REACH: List[set] = []


def _tic_reach() -> set:
    """What the tic reaches (gcallgraph.tic_reach): an I_GetTime call
    from there is the game's (the main loop's own calls are not)."""
    if not _REACH:
        from native import gcallgraph as CG
        _REACH.append(CG.tic_reach(CG.load(write=False)))
    return _REACH[0]


MO_SIZE = 120                   # upstream's mobj (offsets.inc's MO)


def _in_pool(address: int, pool: Tuple[int, int]) -> bool:
    base, n = pool
    return base <= address < base + n * MO_SIZE


def _pools(seq: Sequence[Tuple[int, Sequence[int]]]
           ) -> Dict[int, List[Tuple[int, int]]]:
    """Each tic's pools: the one at its G_Ticker entry and the next
    tic's (a load inside the tic moves the pool)."""
    seq = sorted(seq)
    out: Dict[int, List[Tuple[int, int]]] = {}
    for i, (tic, pool) in enumerate(seq):
        out[tic] = [tuple(pool)]
        if i + 1 < len(seq):
            out[tic].append(tuple(seq[i + 1][1]))
    return out


def _zone(address: int, tic: int,
          pools: Dict[int, List[Tuple[int, int]]]) -> bool:
    """A mobj outside the pool (the tic's, before and after a load in
    it): a zone mobj. A tic with no pool known is no evidence."""
    ps = pools.get(tic)
    return bool(ps) and not any(_in_pool(address, p) for p in ps)


def rekey_record_of(e: Dict[str, Any]) -> bytes:
    """A setup's re-key record (GAME.md 3.6; GL.REKEY_RECORD bytes): the
    map, CS_PREV1/2 as native handles, a pad, the hint of each pool slot
    (low bytes, then high bytes)."""
    hints = list(e.get('hints', []))[:LL.POOL_MAX]
    hints += [0] * (LL.POOL_MAX - len(hints))
    cs = [_native_handle(e['gamemap'], x) for x in e.get('cs_refs',
                                                         [None, None])]
    return (bytes([e['gamemap'] & 0xFF]) + struct.pack('<HH', *cs) +
            b'\0' + bytes(h & 0xFF for h in hints) +
            bytes(h >> 8 for h in hints))


def _native_handle(gamemap: int, ref: Any) -> int:
    if ref is None:
        return 0xFFFF
    if ref == 'stale':
        return LL.STALE
    from native import gameroutine as GR
    mf, _, _ = GR.manifest(gamemap)
    return GR.handle_of(mf, R(ref[0], ref[1], None))


def stream_bytes(result: Dict[str, Any]) -> bytes:
    """The native stream file (src/native/game/README.md, "The stream"):
    'GSTR', the version, the tic count (4); per tic its gametic's low
    word (2), the command (8), the events' count (1) and each event (its
    kind, its length, its bytes); then the I_GetTime values (count 4, 4
    each)."""
    ev: Dict[int, List[bytes]] = {}
    for c in result['cheats']:
        ev.setdefault(c['tic'], []).append(bytes([EV_CHEAT, 1,
                                                  c['number']]))
    for m in result['menu_actions']:
        ev.setdefault(m['tic'], []).append(bytes([EV_INITNEW, 1,
                                                  m['skill'] & 0xFF]))
    for m in result.get('menu_states', []):
        ev.setdefault(m['tic'], []).append(bytes([
            EV_MENU, 2, m['menuactive'] & 0xFF, m['showMessages'] & 0xFF]))
    for p in result['pokes']:
        if p.get('native') is None:
            continue
        body = struct.pack('<HB', p['native'], p['size']) + \
            (p['value'] & ((1 << (8 * p['size'])) - 1)).to_bytes(
                p['size'], 'little')
        ev.setdefault(p['tic'], []).append(bytes([EV_POKE, len(body)]) +
                                           body)
    # every G_Ticker of the run from its first setup's tic (the run's
    # start: its events are already in the start's state), with the ring's
    # command of that tic (the final integration: the intermission's
    # commands too; the level tics' alone before)
    cmds = {int(k): v for k, v in result.get('tic_cmds', {}).items()}
    if not cmds:
        cmds = {t['tic']: t['cmd'] for t in result['tics']}
    start = min((s['tic'] for s in result['setups']), default=min(cmds))
    order = [t for t in sorted(cmds) if t >= start]
    out = bytearray(STREAM_MAGIC + bytes([STREAM_VERSION]) +
                    struct.pack('<I', len(order)))
    for t in order:
        es = ev.get(t, []) if t > start else []
        out += struct.pack('<H', t & 0xFFFF) + bytes.fromhex(cmds[t])
        out += bytes([len(es)]) + b''.join(es)
    out += struct.pack('<I', len(result['times']))
    for t in result['times']:
        out += struct.pack('<I', t['value'] & 0xFFFFFFFF)
    return bytes(out)


def load(run: str, out: Path = OUT) -> Optional[Dict[str, Any]]:
    p = out / (run + '.json.z')
    if not p.exists():
        return None
    return json.loads(zlib.decompress(p.read_bytes()))


# ---------------------------------------------------------------------------
# A light scan (call logs only: ticgen.py's acceptance of a stream)
# ---------------------------------------------------------------------------

COVERAGE = ('g_game65.s:G_PlayerReborn', 'p_inter65.s:P_DamageMobj',
            'p_pspr65.s:bringUpWeapon', 'p_switch65.s:P_UseSpecialLine',
            'p_doors65.s:EV_DoDoor', 'p_doors65.s:EV_VerticalDoor',
            'p_plats65.s:EV_DoPlat', 'p_floor65.s:EV_DoFloor',
            'p_telept65.s:EV_Teleport', 'p_attack65.s:P_RadiusAttack',
            'p_path65.s:P_PathTraverse', 'p_pspr65.s:recursiveSound',
            'p_inter65.s:P_TouchSpecialThing')


def scan(run: str, script_text: Optional[str] = None,
         extra: Sequence[str] = (), say=print) -> Dict[str, Any]:
    """One ref816 run with call logs only: each tic's validcount, pool
    and CS_PREV (G_Ticker's entry), the T3 events (P_CheckSight's zone
    t1, P_RemoveMobj of a zone mobj CS_PREV names), the zone mobjs made
    (P_SpawnMobj's results outside the pool), the coverage items' calls
    (COVERAGE), and the game's divides by zero (divscan.py's five vendor
    entries, inputs only). The windows and the wraps as summarise()."""
    from ref816 import divscan
    GC.check_disk()
    syms = GC.symbols()
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-scan-', dir=str(BUILD)))
    tics: List[Dict[str, Any]] = []
    sight: Dict[int, List[Tuple[int, int, int, int]]] = {}
    removes: List[Tuple[int, int]] = []
    spawns: List[Tuple[int, int]] = []
    setups: List[int] = []
    cover: Dict[str, int] = {k: 0 for k in COVERAGE}
    div0 = []
    try:
        fifo = work / 'calls.fifo'
        os.mkfifo(str(fifo))
        routines = [
            'g_game65.s:G_Ticker,name=@tic,in=_g_gametic:4+'
            'p_map65.s:validcount:2+p_setup65.s:_g_thingPool:4+'
            'p_setup65.s:_g_thingPoolSize:2+p_sight65.s:CS_PREV1:4+'
            'p_sight65.s:CS_PREV2:4,entry=1',
            'p_setup65.s:P_SetupLevel,name=@setup,in=_g_gametic:4,entry=1,'
            'jumps=1',
            'p_sight65.s:P_CheckSight,name=@sight,in=dp:_Dp:8+'
            'p_sight65.s:CS_PREV1:4+p_sight65.s:CS_PREV2:4+_g_gametic:4,'
            'entry=1',
            'p_spawn65.s:P_RemoveMobj,name=@remove,in=dp:_Dp:4+'
            '_g_gametic:4,entry=1',
            'p_spawn65.s:P_SpawnMobj,name=@spawn,in=_g_gametic:4']
        routines += ['%s,name=@cov:%s,entry=1' % (k, k) for k in COVERAGE]
        opts = CL.options(routines, fifo) + ['--call-log-limit',
                                             str(4 << 30)]
        with open(str(GC.CL.make_image.LINKMAP)) as h:
            code = divscan.Code(json.load(h))
        div_opts = divscan.log_options(code, fifo)
        # (one log: the divides' --call-log items join the others)
        opts += [x for i, x in enumerate(div_opts)
                 if i >= 2]
        opts += list(extra)

        def read(handle):
            first = json.loads(handle.readline())
            names = [r['name'] for r in first['routines']]
            for raw in handle:
                line = json.loads(raw)
                if line.get('end'):
                    break
                name = names[line['routine']]
                mem = b''.join(bytes.fromhex(x) for x in line['in']['mem'])
                if name == '@tic':
                    t, v, pb, pn, c1, c2 = struct.unpack_from('<IHIHII',
                                                              mem, 0)
                    tics.append({'tic': t, 'validcount': v,
                                 'pool': [pb & 0xFFFFFF, pn],
                                 'cs_prev': [c1 & 0xFFFFFF, c2 & 0xFFFFFF]})
                elif name == '@setup':
                    setups.append(int.from_bytes(mem[:4], 'little'))
                elif name == '@sight':
                    t1, t2, p1, p2 = struct.unpack_from('<IIII', mem, 0)
                    tic = int.from_bytes(mem[16:20], 'little')
                    sight.setdefault(tic, []).append(
                        (t1 & 0xFFFFFF, t2 & 0xFFFFFF, p1 & 0xFFFFFF,
                         p2 & 0xFFFFFF))
                elif name == '@remove':
                    removes.append((int.from_bytes(mem[4:8], 'little'),
                                    int.from_bytes(mem[0:4], 'little') &
                                    0xFFFFFF))
                elif name == '@spawn':
                    out = line['out'] or {}
                    spawns.append((int.from_bytes(mem[:4], 'little'),
                                   ((out.get('x', 0) & 0xFF) << 16) |
                                   (out.get('a', 0) & 0xFFFF)))
                elif name.startswith('@cov:'):
                    cover[name[5:]] += 1
                elif name in divscan.BY_NAME:
                    d = divscan.BY_NAME[name]
                    regs = line['in']
                    dp = bytes.fromhex(regs['mem'][0]) if regs['mem'] \
                        else bytes(8)
                    if d.divisor == 'x':
                        dv = regs['x'] & (0xFF if regs['p'] & 0x10
                                          else 0xFFFF)
                    else:
                        dv = int.from_bytes(dp[4:8], 'little')
                    if dv == 0 and code.symbols is not None:
                        div0.append({'routine': name, 'from': line['from'],
                                     'frame': line['frame']})

        res = GC.machine(run, work, opts, reader=read, fifo=fifo,
                         script_text=script_text)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    pools = _pools([(t['tic'], t['pool']) for t in tics])
    prev_of = {t['tic']: t['cs_prev'] for t in tics}
    events = []
    for tic, calls in sorted(sight.items()):
        if any(_zone(t1, tic, pools) for t1, _, _, _ in calls):
            events.append((tic, 'zone t1'))
    for tic, mo in removes:
        if mo in (prev_of.get(tic) or ()) and _zone(mo, tic, pools):
            events.append((tic, 'zone mobj in CS_PREV removed'))
    windows = []
    for tic, why in sorted(events):
        nxt = next((t for t in sorted(setups) if t > tic), None)
        if windows and (windows[-1]['to'] is None or
                        tic + 1 < windows[-1]['to']):
            continue
        windows.append({'from': tic + 1, 'to': nxt, 'why': why})
    wraps = []
    for a, b in zip(tics, tics[1:]):
        if b['validcount'] < a['validcount']:
            inside = any(w['from'] <= b['tic'] and (w['to'] is None or
                                                    b['tic'] < w['to'])
                         for w in windows)
            wraps.append({'tic': b['tic'], 'in_window': inside})
    zone = sum(1 for tic, a in spawns if _zone(a, tic, pools))
    return {'run': run, 'problems': res['problems'], 'tics': len(tics),
            'setups': setups, 'windows': windows, 'wraps': wraps,
            'wraps_in_windows': sum(1 for w in wraps if w['in_window']),
            'zone_mobjs': zone, 'coverage': cover, 'div0': div0}


# ---------------------------------------------------------------------------
# S4: the tables and the re-keying
# ---------------------------------------------------------------------------

LNSEC = 0x21C000                # p_sight65.s: MM_B3F + $C000
SS_ROW = 0x214000               # MM_B3F + $4000


def check_tables(say=print, bases: Optional[Path] = None
                 ) -> Dict[str, Any]:
    """S4 on every setup dump, against the level bases in bases (default:
    gameroutine.BASES, milestone 9's kept setup machines)."""
    from native import gameroutine as GR, levelconv as LC, setupcap
    from bridge.port import PortReader
    from bridge.memory import PortMemory
    report: Dict[str, Any] = {'setups': {}, 'failures': []}
    lvs_of: Dict[int, bytes] = {}
    for d in setupcap.setup_dirs():
        info = json.loads((d / 'setup.json').read_text())
        m = info['gamemap']
        rm = LC.load_memory(d / 'r.ram.z')
        r = upstream.Reader(rm, tic=True)
        st = r.read()
        nlines = len(st['objects']['line'])
        nsub = len(st['objects']['subsector'])
        if m not in lvs_of:
            recs = GR.base_records(m, bases or GR.BASES)
            rec = next(x for x in recs if x[0] == 1 and x[1] == LL.LVS)
            lvs_of[m] = bytes(rec[2]) + bytes(rec[3])  # (padded to $0000)
        lvs = lvs_of[m]
        fails = []
        for ln in range(nlines):
            f, b = rm.read(LNSEC + 2 * ln, 2)
            nf = lvs[LL.LVS_LNSECF + ln]
            nb = lvs[LL.LVS_LNSECB + ln]
            if (f, b) != (nf, nb):
                fails.append('line %d: LNSEC %d,%d, LNSECF/B %d,%d' % (
                    ln, f, b, nf, nb))
        for ss in range(nsub):
            sec = st['objects']['subsector'][ss]['sector'].id
            up = rm.u16(SS_ROW + 2 * ss)
            nat = lvs[LL.LVS_RJROW + 2 * sec] | lvs[LL.LVS_RJROW + 2 * sec +
                                                     1] << 8
            if up != nat:
                fails.append('subsector %d (sector %d): SS_ROW %d, RJROW %d'
                             % (ss, sec, up, nat))
        # the re-keying, a round trip through the manifest's leaves
        mf, _, _ = GR.manifest(m)
        e = {'gamemap': m,
             'hints': [st['objects']['sighthint'][i]['line']
                       for i in sorted(st['objects']['sighthint'])],
             'cs_refs': [_ref_tuple(st['globals'].get(
                 'p_sight65.s:CS_PREV1')), _ref_tuple(st['globals'].get(
                     'p_sight65.s:CS_PREV2'))]}
        rec = rekey_record_of(e)
        pm = PortMemory()
        n = LL.POOL_MAX
        pm.write((LL.MOBJP << 16) | LL.PL_HINTL, rec[6:6 + n])
        pm.write((LL.MOBJP << 16) | LL.PL_HINTH, rec[6 + n:6 + 2 * n])
        rd = PortReader(mf)
        rd.m = pm
        leaf = mf.kinds['sighthint']['leaves'][0]
        back = [rd.decode(leaf, i) for i in range(len(e['hints']))]
        if back != e['hints']:
            fails.append('the hints do not come back')
        from bridge.port import handle_decode
        for k, name in ((0, 'CS_PREV1'), (1, 'CS_PREV2')):
            h = struct.unpack_from('<H', rec, 1 + 2 * k)[0]
            leaf = next(lf for lf in mf.globals
                        if lf.path[0] == 'p_sight65.s:' + name)
            v = handle_decode(leaf.enc, h, name)
            want = st['globals'].get('p_sight65.s:' + name)
            if v != want:
                fails.append('%s: %r back, %r' % (name, v, want))
        report['setups'][d.name] = {'gamemap': m, 'lines': nlines,
                                    'subsectors': nsub,
                                    'failures': fails[:5]}
        if fails:
            report['failures'].append('%s: %s' % (d.name, fails[0]))
    say('%d setup dumps: LNSEC/SS_ROW against LNSECF/LNSECB/RJROW and '
        'the re-keying: %d failures' % (len(report['setups']),
                                        len(report['failures'])))
    return report


# S7's planted bug for S4: RJROW of the next sector (lgeom.s lg_gtabs)
RJROW_PLANT = [('lgeom.s', '''        stz LG_C                ; RJROW: s * numsectors, from 0 in steps of
''', '''        lda LG_NS               ; (planted: the next sector's row) RJROW
        sta LG_C
''')]


def planted_tables(bugs=RJROW_PLANT, fill: int = 0xA5) -> Dict[str, Any]:
    """S4 on level bases made by a planted loader: the load image built
    from a scratch copy of the sources (level.mk with the planted files;
    the rest from the tree), the tour-sk2 setups run on it (milestone 9's
    setup check, which keeps their machines), then check_tables on
    them. Everything in a scratch directory under build/, deleted."""
    from native import lrun, setupcheck as SC
    tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-s4plant-', dir=str(BUILD)))
    try:
        src = tmp / 'src'
        src.mkdir()
        keep_files = {'level.mk', 'level.cfg'} | {
            p.name for p in lrun.SOURCE.glob('*.inc')}
        for f in keep_files | {n for n, _, _ in bugs}:
            shutil.copy(str(lrun.SOURCE / f), str(src / f))
        for name, old, new in bugs:
            text = (src / name).read_text()
            if text.count(old) != 1:
                raise TicError('the bug no longer applies: %r' % old)
            (src / name).write_text(text.replace(old, new))
        lrun.make(tmp / 'obj', src)
        keep = tmp / 'keep'
        SC.check_setups((fill,), [SC.KEEP_RUN], obj=tmp / 'obj', keep=keep)
        return check_tables(say=lambda *a: None, bases=keep)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def report_lines(result: Dict[str, Any]) -> List[str]:
    hits = result['same_pair_hits']
    hv = sorted(hits.values())
    return [
        '%s: %d tics decoded, %d with bridge problems' % (
            result['run'], result['tics_decoded'],
            result['tics_with_problems']),
        '  schedule: %d frames, tics a frame %s' % (
            len(result['schedule']), result['tics_a_frame']),
        '  setups: %s' % [(s['gamemap'], s['skill'], s['tic'])
                          for s in result['setups']],
        '  T3 windows: %s' % [(w['from'], w['to'], w['why'])
                              for w in result['windows']],
        '  validcount wraps: %d (%d in a window)' % (
            len(result['wraps']), result['wraps_in_windows']),
        '  same-pair hits: %d tics, %d hits (most %s a tic)' % (
            len(hits), sum(hv), hv[-1] if hv else 0),
        '  I_GetTime values the game read: %s' % [
            (t['tic'], t['value'], t['caller']) for t in result['times']][:6],
        '  menu actions: %s' % [(m['tic'], m['skill'], m['caller'])
                                for m in result['menu_actions']],
        '  cheats: %s' % [(c['tic'], c['cheat']) for c in result['cheats']],
        '  pokes: %s' % [(p['tic'], p['text'], p.get('canonical'),
                          p.get('native')) for p in result['pokes']],
        '  menu states: %s' % [(m['tic'], m['menuactive'],
                                m['showMessages'])
                               for m in result.get('menu_states', [])][:8],
        '  zone mobjs at most %d' % result['zone_mobjs_most']]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--runs')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--tables', action='store_true')
    parser.add_argument('--planted', action='store_true',
                        help='with --tables: the planted RJROW bug')
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args(argv)
    if args.tables:
        rep = planted_tables() if args.planted else check_tables()
        for f in rep['failures'][:10]:
            print('  ' + f)
        return 1 if rep['failures'] else 0
    if args.runs:
        bad = 0
        for run in args.runs.split(','):
            res = capture_run(run, args.jobs)
            for line in report_lines(res):
                print(line)
            bad += bool(res['tics_with_problems'] or res['run_problems'])
        return 1 if bad else 0
    if args.report:
        for run in GC.RUNS:
            res = load(run)
            if res:
                for line in report_lines(res):
                    print(line)
        return 0
    parser.error('nothing to do')
    return 2


if __name__ == '__main__':
    sys.exit(main())
