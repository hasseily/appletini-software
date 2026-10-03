#!/usr/bin/env python3
"""Part flow's checks (milestone 10, docs/GAME.md 2.4 row flow, 2.5, 3.5):
the game flow game-side (src/native/game/flow) against ref816.

Usage:  python3 tools/native/gparts/flowcheck.py --build
        python3 tools/native/gparts/flowcheck.py --capture [--jobs 2]
        python3 tools/native/gparts/flowcheck.py --logs
        python3 tools/native/gparts/flowcheck.py --checkpoint [--jobs 2]
        python3 tools/native/gparts/flowcheck.py --sweeps [--jobs 2]
        python3 tools/native/gparts/flowcheck.py --random [--count 100000]
        python3 tools/native/gparts/flowcheck.py --plants
        python3 tools/native/gparts/flowcheck.py --report

--build: the part's test image (make -f game.mk part P=flow) into
build/native/game/flow/ (request 2 of docs/game-parts/flow.md is applied:
FCALL makes a built target .global, so ghook.s's FCALL WI_Start needs no
.import and ca65 needs no --auto-import).

--capture: the reference's cases (gamecap.py's --capture, distilled the
same way) into build/native/game/flow/cases/RUN/ROUTINE/ (this part's
own directory: gamecap.CASES is pointed there), chosen by GAME.md 2.4's
minimums (CHOICE): every call of an entry with fewer than 300 calls, else
300 spread evenly over its runs plus each call whose path no other chosen
call takes (a path: the call's signature from the call logs of --logs),
plus the synthetic cases (ref816 --call on a captured entry state with
pokes: the secret exit, G_SecretExitLevel, the HUD's message with
messages off). WI_Ticker and HU_Ticker are entered by G_Ticker's JML, which
ref816 --capture does not count: their cases are made by --call from the
captured entry of the call before them (WI_checkForAccelerate, WI_Ticker's
first call, with bcnt one less and S three higher; AM_Ticker, which
G_Ticker calls just before its JML to HU_Ticker, from its return state).

--logs: one call-logged ref816 run of each run (demo3, demo1, demo2, tour):
every call of readDemoTiccmd, G_CheckDemoStatus, ST_Ticker, HU_Ticker,
WI_Ticker (jumps=1 for the JML'd ones) with the memory each reads and
writes (LOGGED), read from a pipe and kept distilled in
build/native/game/flow/logs/RUN.json.z: the sweeps' and the choice's
input.

--checkpoint: routine mode (GAME.md 3.5) on every chosen case, from both
poisoned machines ($A5, $5A), each under f121 and fastpath: the entry state
written through the game manifest, the entry's inputs (args.json), the
routine run through the harness entry fl_timed (its own time in cost
phase 30), the canonical state after the call against ref816's (gcanon
routine mode, exclusions R1-R6 only), the declared outputs, the stray CPU
writes (the write log against the places the part, the runtime and the
driver may write), the lowest S. The load-containing actions (doNewGame,
doPlayDemo, loadLevel, doWorldDone) run in the driver's routine-with-load
mode with the load image (milestone 9's ltest): the reference's state at
the action's call (its globals and player: the level is the load's), the
action up to the load, the load (nl_setup) and its re-key record (from
the run's tic reference, ticcap.py), the continuation g_resume (cost
phase 31), compared with ref816's state at the action's return.

--sweeps: every tic of the runs, as the native's sweep entry fl_sweep
calls the routine once a record with the reference's inputs of that call
and keeps its outputs: readDemoTiccmd on every tic of the three demos (the
command and demo_p), ST_Ticker (M_Random's index and value) and HU_Ticker
(player.message, G_MSGKEEP) on every tic of demo3, WI_Ticker on every
intermission tic of the tour (the wi counters, the player's buttons'
state, gameaction, didsecret, the sounds' count).

--random: each arithmetic helper of the part (times100, div1000,
signLong) on COUNT random inputs with 0, +-1 and the extremes, upstream's
on ref816 (mathref batch, build/native/math) against the native through
fl_sweep.

--plants: the planted bugs of GAME.md 2.4's row, each in a scratch copy
of the part's sources (a temporary directory, deleted), each must fail its
named check.

--report: build/native/game/flow/report.json from the results of the
runs above (results/*.json).

Every run is bounded (a2vm's cycles and time, ref816's, file sizes), its
temporary directory under build/ deleted after it.
"""

import argparse
import json
import os
import random
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from a2vm import costs  # noqa: E402
from bridge.fields import R  # noqa: E402
from bridge.port import PortReader, PortWriter  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL, lrun  # noqa: E402
from native import render_check as RC, setupcheck as SC  # noqa: E402
from ref816 import bounded, calls as CL, title  # noqa: E402

ROOT = HERE.parent.parent.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
FLOW = GL.GAME / 'flow'
CASES = FLOW / 'cases'
LOGS = FLOW / 'logs'
RESULTS = FLOW / 'results'
REPORT = FLOW / 'report.json'
ARGS = SRC / 'game' / 'flow' / 'args.json'
PART_SRC = ('game/flow/gflow.s', 'game/flow/gwi.s', 'game/flow/part.mk',
            'game/flow/args.json')
# (request 2 of docs/game-parts/flow.md applied: no --auto-import)
CA65 = 'ca65'
FILLS = (0xA5, 0x5A)
PROFILES = ('f121', 'fastpath')
PH_ENTRY, PH_RESUME = 30, 31
BUDGET = 2300                   # GAME.md 2.4: upstream 1,800 x 1.3
MATHREF = BUILD / 'native' / 'math' / 'mathref'
MATH_BASE = BUILD / 'native' / 'math' / 'captures' / 'tour'
MIN_FREE = 20 * 10 ** 9

# this part's cases are in its own directory: gamecap's case functions
# are pointed there (and given their own cache of the runs' bases) only
# for the time of a call, so that nothing else in the process sees it
_BASES: Dict[str, Any] = {}


class _OwnCases:
    def __enter__(self):
        self.saved = (GC.CASES, GC._BASES)
        GC.CASES, GC._BASES = CASES, _BASES

    def __exit__(self, *exc):
        GC.CASES, GC._BASES = self.saved
        return False


def case_dir(run: str, key: str) -> Path:
    with _OwnCases():
        return GC.case_dir(run, key)


def load_case(path: Path):
    with _OwnCases():
        return GC.load_case(Path(path))


def load_base(run: str):
    with _OwnCases():
        return GC.load_base(run)


def gc_capture(*args, **kwargs):
    with _OwnCases():
        return GC.capture(*args, **kwargs)


class FlowError(Exception):
    pass


def say(*args) -> None:
    print(*args, flush=True)


def check_disk() -> None:
    st = os.statvfs(str(BUILD))
    if st.f_bavail * st.f_frsize < MIN_FREE:
        raise FlowError('under 20 GB free: stopped')


def tmpdir(tag: str) -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='tmp-m10-flow-%s-' % tag,
                                 dir=str(BUILD)))


# ---------------------------------------------------------------------------
# The builds
# ---------------------------------------------------------------------------

def make_part(source: Path = SRC, game: Optional[Path] = None) -> Path:
    """make -f game.mk part P=flow (the image in game/flow, by default
    build/native/game/flow); a warning is a failure."""
    var = ['P=flow', 'ROOT=%s' % ROOT, 'CA65=%s' % CA65]
    if game is not None:
        var.append('GAME=%s' % game)
    r = bounded.run(['make', '-s', '-C', str(source), '-f', 'game.mk',
                     'part'] + var, timeout=600, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, universal_newlines=True)
    if r.returncode:
        raise FlowError('the build failed:\n' + r.stdout[-3000:])
    if 'arning' in r.stdout:
        raise FlowError('the build warns:\n' + r.stdout[-3000:])
    return (game or GL.GAME) / 'flow'


def planted(tmp: Path, bugs: Sequence[Tuple[str, str, str]]) -> Path:
    """The part's image built from a scratch copy of its sources (and
    game.mk) with each (file, old, new) applied once: the image's
    directory."""
    src = tmp / 'src'
    for f in set(G.PLANT_COPY) | set(PART_SRC):
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
    for name, old, new in bugs:
        p = src / name
        text = p.read_text()
        if text.count(old) != 1:
            raise FlowError('the bug no longer applies: %r' % old[:60])
        p.write_text(text.replace(old, new))
    return make_part(src, tmp / 'game')


def load_build(obj: Path = FLOW):
    return G.load_build(obj, 'ptest')


def level_build():
    return lrun.load_build(lrun.OBJ, 'ltest')


def part_sizes(b) -> Dict[str, int]:
    """The part's bytes by module, gflow.s without its test-only harness
    (TESTBUILD: not in the game)."""
    ms = G.module_sizes(b)
    return {'gflow': ms.get('gflow', 0) - test_bytes(b),
            'gwi': ms.get('gwi', 0)}


def test_bytes(b) -> int:
    """The test-only harness code and data of gflow.s (TESTBUILD), which
    the part's size leaves out: fl_timed to the end of fl_buf."""
    lab = b.labels
    if lab['fl_timed'] >= 0xC000:   # (in the driver's area: module_sizes
        return 0                    #   counts W's segments only)
    return lab['fl_buf'] + 192 - lab['fl_timed']


# ---------------------------------------------------------------------------
# The entries and their cases
# ---------------------------------------------------------------------------

def args_spec() -> Dict[str, Dict[str, Any]]:
    return json.loads(ARGS.read_text())['entries']


LOAD_ENTRIES = ('g_game65.s:doNewGame', 'g_game65.s:doPlayDemo',
                'g_game65.s:loadLevel', 'g_game65.s:doWorldDone')
# the entries captured by ref816 --capture: (key, runs)
CAPTURED = {
    'g_game65.s:readDemoTiccmd': ('demo3', 'demo1', 'demo2'),
    'g_game65.s:G_CheckDemoStatus': ('demo3', 'demo1', 'demo2'),
    'g_game65.s:doCompleted': ('tour',),
    'g_game65.s:G_DeferedInitNew': ('newgame', 'tour'),
    'g_game65.s:G_DeferedPlayDemo': ('demo3', 'demo1', 'demo2'),
    'g_game65.s:G_ExitLevel': ('tour',),
    'g_game65.s:G_ReloadDefaults': ('demo3', 'demo1', 'demo2', 'newgame',
                                    'tour'),
    'g_game65.s:checkOverrun': ('demo3', 'demo1', 'demo2'),
    'wi_stuff65.s:WI_End': ('tour',),
    'wi_stuff65.s:WI_checkForAccelerate': ('tour',),
    'st_stuff65.s:ST_Ticker': ('demo3',),
    'g_game65.s:doNewGame': ('newgame', 'tour'),
    'g_game65.s:doPlayDemo': ('demo3', 'demo1', 'demo2'),
    'g_game65.s:loadLevel': ('demo1', 'demo2'),
    'g_game65.s:doWorldDone': ('tour',),
    # the neighbours of the JML'd entries
    'am_map65.s:AM_Ticker': ('demo3',),
}
# made by --call: (key, the captured key it starts from, runs)
DERIVED = {
    'wi_stuff65.s:WI_Ticker': ('wi_stuff65.s:WI_checkForAccelerate',
                               ('tour',)),
    'hu_stuff65.s:HU_Ticker': ('am_map65.s:AM_Ticker', ('demo3',)),
}
MIN_CASES = 300


def survey_tics(run: str, key: str) -> Optional[List[int]]:
    sv = GC.survey_of(run)
    if sv is None or key not in sv['routines']:
        return None
    return sv['routines'][key]['tic']


def calls_of(run: str, key: str) -> int:
    """The calls of a captured key in a run: the skeleton's survey, or for
    AM_Ticker (not in the survey) this part's logs (one a ST_Ticker call:
    G_Ticker calls both in every level tic)."""
    t = survey_tics(run, key)
    if t is not None:
        return len(t)
    if key == 'am_map65.s:AM_Ticker':
        lg = load_log(run)
        return len(lg['calls']['ST_Ticker']) if lg else 0
    return 0


def even(n: int, k: int) -> List[int]:
    """k of the calls 1..n spread evenly (all of them when n <= k)."""
    if n <= k:
        return list(range(1, n + 1))
    return sorted({1 + (i * (n - 1)) // (k - 1) for i in range(k)})


def choose(key: str) -> Dict[str, List[int]]:
    """The hits to capture of a captured key, by run (GAME.md 2.4's
    minimums): all when the entry has fewer than 300 calls in all, else
    300 spread evenly over the runs' calls plus each call whose path
    (path_sig) no chosen call takes."""
    runs = CAPTURED.get(key) or DERIVED[key][1]
    src = DERIVED[key][0] if key in DERIVED else key
    counts = {r: calls_of(r, src) for r in runs}
    total = sum(counts.values())
    out: Dict[str, List[int]] = {}
    if total < MIN_CASES:
        return {r: list(range(1, n + 1)) for r, n in counts.items() if n}
    flat = [(r, h) for r in runs for h in range(1, counts[r] + 1)]
    picked = {flat[i - 1] for i in even(len(flat), MIN_CASES)}
    sigs = {}
    for r in runs:
        for h, s in path_sigs(r, key).items():
            sigs[(r, h)] = s
    seen = {sigs.get(x) for x in picked}
    for x in flat:
        s = sigs.get(x)
        if s is not None and s not in seen:
            seen.add(s)
            picked.add(x)
    for r, h in sorted(picked):
        out.setdefault(r, []).append(h)
    return out


def capture_hits(key: str) -> Dict[str, List[int]]:
    """The hits to capture of a key: its own choice, and the choice of
    each derived entry made from it (WI_Ticker's from
    WI_checkForAccelerate's, HU_Ticker's from AM_Ticker's)."""
    out = {r: set(h) for r, h in choose(key).items()}
    for d, (src, _) in DERIVED.items():
        if src == key:
            for r, h in choose(d).items():
                out.setdefault(r, set()).update(h)
    return {r: sorted(h) for r, h in out.items()}


# ---------------------------------------------------------------------------
# The reference's call logs (--logs)
# ---------------------------------------------------------------------------

def _pl(off: int, n: int) -> str:
    return '_g_player+%d:%d' % (off, n)


# upstream's player offsets (offsets.inc): cmd 6 (5 bytes), attackdown 99,
# usedown 101, message 113 (4), didsecret 153
UP_CMD, UP_ATK, UP_USE, UP_MSG, UP_SECRET = 6, 99, 101, 113, 153
WI_VARS = ('wi_stuff65.s:_g_acceleratestage:2', 'wi_stuff65.s:state:2',
           'wi_stuff65.s:cnt:2', 'wi_stuff65.s:bcnt:2',
           'wi_stuff65.s:cnt_time:4', 'wi_stuff65.s:cnt_total_time:4',
           'wi_stuff65.s:cnt_par:2', 'wi_stuff65.s:cnt_pause:2',
           'wi_stuff65.s:sp_state:2', 'wi_stuff65.s:cnt_kills:2',
           'wi_stuff65.s:cnt_items:2', 'wi_stuff65.s:cnt_secret:2',
           'wi_stuff65.s:snl_pointeron:2')
WI_NATIVE = ('WI_ACCEL', 'WI_STATE', 'WI_CNT', 'WI_BCNT', 'WI_CNTTIME',
             'WI_CNTTOTAL', 'WI_CNTPAR', 'WI_CNTPAUSE', 'WI_SPSTATE',
             'WI_CNTKILLS', 'WI_CNTITEMS', 'WI_CNTSECRET', 'WI_SNLPTR')
# (upstream's wi counters are 30 bytes in a row from _g_acceleratestage:
# one range of the call log, which takes at most 16)
WI_RANGE = ('wi_stuff65.s:_g_acceleratestage:30',)
WI_IN = '+'.join(WI_RANGE + ('_g_wminfo:40', '_g_gamemap:2',
                            'g_game65.s:secretexit:2', _pl(UP_CMD, 5),
                            _pl(UP_ATK, 2), _pl(UP_USE, 2),
                            '_g_gameaction:2', _pl(UP_SECRET, 2)))
WI_OUT = '+'.join(WI_RANGE + (_pl(UP_ATK, 2), _pl(UP_USE, 2),
                             '_g_gameaction:2', _pl(UP_SECRET, 2)))
LOGGED = {
    'readDemoTiccmd': 'g_game65.s:readDemoTiccmd,name=readDemoTiccmd,'
    'in=g_game65.s:demo_p:4+g_game65.s:demobuffer:4+'
    'g_game65.s:demolength:2+_g_demoplayback:2,'
    'out=%s+g_game65.s:demo_p:4+_g_demoplayback:2' % _pl(UP_CMD, 5),
    'G_CheckDemoStatus': 'g_game65.s:G_CheckDemoStatus,'
    'name=G_CheckDemoStatus,entry=1',
    'ST_Ticker': 'st_stuff65.s:ST_Ticker,name=ST_Ticker,'
    'in=m_random65.s:rndindex:2,'
    'out=m_random65.s:rndindex:2+st_stuff65.s:st_randomnumber:2',
    'HU_Ticker': 'hu_stuff65.s:HU_Ticker,name=HU_Ticker,jumps=1,'
    'in=%s+m_menu65.s:showMessages:2+'
    'hu_stuff65.s:_g_message_dontfuckwithme:2,'
    'out=%s+hu_stuff65.s:_g_message_dontfuckwithme:2'
    % (_pl(UP_MSG, 4), _pl(UP_MSG, 4)),
    'WI_Ticker': 'wi_stuff65.s:WI_Ticker,name=WI_Ticker,jumps=1,'
    'in=%s,out=%s' % (WI_IN, WI_OUT),
    'S_StartSound': 'S_StartSound,name=S_StartSound,entry=1',
}
LOG_RUNS = {'demo3': ('readDemoTiccmd', 'G_CheckDemoStatus', 'ST_Ticker',
                      'HU_Ticker'),
            'demo1': ('readDemoTiccmd', 'G_CheckDemoStatus'),
            'demo2': ('readDemoTiccmd', 'G_CheckDemoStatus'),
            'tour': ('WI_Ticker', 'S_StartSound')}


class LogReader:
    """A call log read as it comes: each logged routine's calls (hit
    order), their memory in and out (hex), and the sounds started inside
    each WI_Ticker call."""

    def __init__(self):
        self.calls: Dict[str, List[Dict[str, Any]]] = {}
        self.end: Dict[str, Any] = {}

    def read(self, handle) -> None:
        first = json.loads(handle.readline())
        names = [r['name'] for r in first['routines']]
        open_wi: Dict[int, Dict[str, Any]] = {}
        pending: List[Tuple[int, Dict[str, Any]]] = []
        for raw in handle:
            line = json.loads(raw)
            if line.get('end'):
                self.end = line
                break
            name = names[line['routine']]
            if name == 'S_StartSound':
                pending.append((line.get('parent', 0), line))
                continue
            rec = {'hit': line['hit'],
                   'in': ''.join(line['in']['mem']),
                   'out': ''.join((line['out'] or {}).get('mem', []))
                   if line.get('out') else None,
                   'returned': line.get('returned', True),
                   'call': line['call']}
            if name == 'WI_Ticker':
                rec['sounds'] = sum(1 for p, _ in pending
                                    if p == line['call'])
                pending = [(p, s) for p, s in pending if p != line['call']]
            self.calls.setdefault(name, []).append(rec)
        del open_wi


def log_path(run: str) -> Path:
    return LOGS / (run + '.json.z')


def load_log(run: str) -> Optional[Dict[str, Any]]:
    p = log_path(run)
    if not p.exists():
        return None
    return json.loads(zlib.decompress(p.read_bytes()))


def make_logs(runs: Sequence[str] = tuple(LOG_RUNS)) -> None:
    for run in runs:
        check_disk()
        work = tmpdir('log')
        lr = LogReader()
        start = time.time()
        try:
            fifo = work / 'calls.fifo'
            os.mkfifo(str(fifo))
            opts = CL.options([LOGGED[n] for n in LOG_RUNS[run]], fifo) + \
                ['--call-log-limit', str(2 << 30)]
            r = GC.machine(run, work, opts, reader=lr.read, fifo=fifo)
            if r['problems']:
                raise FlowError('%s: %s' % (run, '; '.join(r['problems'])))
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        LOGS.mkdir(parents=True, exist_ok=True)
        log_path(run).write_bytes(zlib.compress(json.dumps(
            {'run': run, 'calls': lr.calls, 'end': lr.end},
            separators=(',', ':')).encode(), 6))
        say('%s: %s, %.0f s' % (run, ', '.join(
            '%s %d' % (k, len(v)) for k, v in lr.calls.items()),
            time.time() - start))


def _u(hexs: str, at: int, n: int, signed: bool = False) -> int:
    return int.from_bytes(bytes.fromhex(hexs[2 * at:2 * (at + n)]), 'little',
                          signed=signed)


def path_sigs(run: str, key: str) -> Dict[int, Any]:
    """Each call's path signature (by hit) from this part's logs, for the
    choice: WI_Ticker (the state's sign, sp_state, a request, the stage
    left, gameaction set), WI_checkForAccelerate (its WI_Ticker's buttons
    and their states: the same calls), HU_Ticker (a message, messages on,
    kept), readDemoTiccmd (the end marker)."""
    lg = load_log(run)
    if lg is None:
        return {}
    out: Dict[int, Any] = {}
    if key in ('wi_stuff65.s:WI_Ticker', 'wi_stuff65.s:WI_checkForAccelerate'):
        for k, c in enumerate(lg['calls'].get('WI_Ticker', []), 1):
            i, o = c['in'], c['out'] or ''
            st, sp = _u(i, 2, 2, True), _u(i, 20, 2, True)
            acc = _u(i, 0, 2) != 0
            n = sum(int(x.split(':')[-1]) for x in WI_VARS)
            b = _u(i, n + 40 + 2 + 2 + 4, 1)
            if key.endswith('WI_Ticker'):
                out[k] = ('wi', st > 0, st < 0, sp, acc,
                          o[40:44] != i[40:44] if o else None,
                          _u(o, n + 4, 2) if o else None)
            else:
                out[k] = ('cfa', b & 3, _u(i, n + 40 + 2 + 2 + 5, 2) != 0,
                          _u(i, n + 40 + 2 + 2 + 7, 2) != 0)
    elif key == 'hu_stuff65.s:HU_Ticker':
        for k, c in enumerate(lg['calls'].get('HU_Ticker', []), 1):
            i = c['in']
            out[k] = ('hu', _u(i, 0, 4) != 0, _u(i, 4, 2) != 0,
                      _u(i, 6, 2) != 0)
    elif key == 'g_game65.s:readDemoTiccmd':
        calls = lg['calls'].get('readDemoTiccmd', [])
        for k, c in enumerate(calls, 1):
            out[k] = ('rd', c['out'] is not None and
                      _u(c['out'], 9, 2) == 0)
    return out


# ---------------------------------------------------------------------------
# Capturing and the synthetic cases
# ---------------------------------------------------------------------------

def case_paths(run: str, key: str) -> List[Path]:
    return sorted(case_dir(run, key).glob('h*.case.z'))


def capture_all(keys: Optional[Sequence[str]] = None) -> None:
    every = keys is None
    keys = list(keys or list(CAPTURED) + list(DERIVED))
    for key in keys:
        if key in DERIVED:
            continue
        for run, hits in capture_hits(key).items():
            tics = survey_tics(run, key)
            have = {int(p.name[1:9]) for p in case_paths(run, key)}
            todo = [h for h in hits if h not in have]
            if todo:
                gc_capture(run, key, todo, tics, batch=200, say=say)
    for key in keys:
        if key in DERIVED:
            derive(key)
    if every:
        synth_all()
        recall_poked()


def call_at(entry, address: int, regs: Dict[str, int],
            pokes: Sequence[Tuple[int, bytes]], header: Dict[str, Any],
            note: str):
    """A case made by ref816 --call of `address` on memory `entry` with
    pokes and the registers changed (regs): its return state from
    upstream's own code."""
    mem = entry.copy()
    mem.header = entry.header
    for a, d in pokes:
        mem.write(a, d)
    work = tmpdir('call')
    try:
        (work / 'entry.img').write_bytes(mem.image_bytes())
        cmd = [str(title.MACHINE), str(work / 'entry.img')]
        for k, v in regs.items():
            cmd += ['--reg', '%s=%X' % (k, v)]
        cmd += ['--call', '%06X' % address, '--call-writes',
                str(work / 'writes.img'), '--state',
                str(work / 'state.json')]
        r = bounded.run(cmd, timeout=120, max_bytes=GC.MAX_FILE,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode:
            raise FlowError('ref816 --call failed: %s' % r.stdout[-800:])
        state = json.loads((work / 'state.json').read_text())
        if not state['call']['returned']:
            raise FlowError('the call did not return')
        writes = GC.image_records(work / 'writes.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    after = mem.copy()
    for a, d in writes:
        after.write(a, d)
    h = dict(header, note=note, call=state['call'],
             writes=GC._ranges(writes))
    return GC.Case(h, mem, after, None)


def save_case(case, run: str, key: str, name: str) -> Path:
    """A made case in the case format (its pages against the run's base)
    under cases/RUN/ROUTINE/name."""
    base = load_base(run)
    pages = sorted(GC.reader_pages(case.entry) | GC.reader_pages(case.after)
                   | {p for a, n in case.header['writes']
                      for p in range(a >> 8, ((a + max(n, 1) - 1) >> 8) + 1)}
                   | {case.regs_in['s'] >> 8, case.regs_in['d'] >> 8,
                      (case.regs_in['d'] + 0xFF) >> 8 & 0xFF})
    payload = bytearray()
    for p in pages:
        a = p << 8
        mine = case.entry.read(a, GC.PAGE)
        theirs = base.read(a, GC.PAGE)
        payload += bytes(x ^ y for x, y in zip(mine, theirs))
    wbytes = bytearray()
    for a, n in case.header['writes']:
        wbytes += case.after.read(a, n)
    h = dict(case.header, routine=key, run=run,
             image_header=case.entry.header.hex(),
             pages=GC._compress_pages(pages))
    head = json.dumps(h, separators=(',', ':')).encode() + b'\n'
    d = case_dir(run, key)
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(zlib.compress(head + bytes(payload) + bytes(wbytes), 6))
    return p


def derive(key: str) -> None:
    """WI_Ticker's or HU_Ticker's cases from their neighbours' captures."""
    src, runs = DERIVED[key]
    table = CL.Linkmap()
    address = table.address(key)
    for run, hits in choose(key).items():
        for h in hits:
            name = 'h%08d.case.z' % h
            if (case_dir(run, key) / name).exists():
                continue
            p = case_dir(run, src) / name
            if not p.exists():
                raise FlowError('%s: no capture %s of %s' % (key, p, src))
            c = load_case(p)
            if key == 'wi_stuff65.s:WI_Ticker':
                # WI_checkForAccelerate's entry: inside WI_Ticker after
                # `inc bcnt` and its JSL: bcnt one less, S three higher
                bcnt = table.address('wi_stuff65.s:bcnt')
                v = (c.entry.u16(bcnt) - 1) & 0xFFFF
                mem, pokes = c.entry, [(bcnt, v.to_bytes(2, 'little'))]
            else:
                # AM_Ticker's return state: G_Ticker's JML to HU_Ticker
                # follows its JSL of AM_Ticker
                mem, pokes = c.after, []
            regs = {'s': (c.regs_in['s'] + 3) & 0xFFFF}
            hd = dict(c.header, routine=key)
            made = call_at(mem, address, regs, pokes, hd,
                           'derived from %s hit %d' % (src, h))
            save_case(made, run, key, name)
        say('%s %s: %d cases' % (run, key, len(hits)))


# the synthetic cases (GAME.md 2.4: the paths no run takes): name, key,
# the run and the case it starts from, the pokes (symbol, bytes)
SYNTH = [
    ('secret-exit', 'g_game65.s:doCompleted', 'tour', 1,
     [('g_game65.s:secretexit', b'\x01\x00')]),
    ('secret-exit-e1m9', 'g_game65.s:doCompleted', 'tour', 4,
     [('g_game65.s:secretexit', b'\x01\x00')]),
    ('hu-messages-off', 'hu_stuff65.s:HU_Ticker', 'demo3', None,
     [('m_menu65.s:showMessages', b'\x00\x00'),
      ('hu_stuff65.s:_g_message_dontfuckwithme', b'\x00\x00')]),
    ('hu-kept', 'hu_stuff65.s:HU_Ticker', 'demo3', None,
     [('m_menu65.s:showMessages', b'\x00\x00'),
      ('hu_stuff65.s:_g_message_dontfuckwithme', b'\x01\x00')]),
    # the intermission's stages no run takes (the tour's use key shows the
    # counts at once): WI_Ticker's first case with the stage poked
    ('wi-kills', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('_g_wminfo+20', (30).to_bytes(4, 'little')), ('wi_stuff65.s:sp_state', (2).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (0).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt_kills', (0).to_bytes(2, 'little', signed=True))]),
    ('wi-kills-total', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:sp_state', (2).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (0).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt_kills', (150).to_bytes(2, 'little', signed=True))]),
    ('wi-items', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('_g_wminfo+24', (40).to_bytes(4, 'little')), ('wi_stuff65.s:sp_state', (4).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (0).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt_items', (10).to_bytes(2, 'little', signed=True))]),
    ('wi-secret', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('_g_wminfo+28', (3).to_bytes(4, 'little')), ('wi_stuff65.s:sp_state', (6).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (0).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt_secret', (0).to_bytes(2, 'little', signed=True))]),
    ('wi-secret-total', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:sp_state', (6).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (0).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt_secret', (120).to_bytes(2, 'little', signed=True))]),
    ('wi-times', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:sp_state', (8).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (0).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt_time', (0).to_bytes(4, 'little', signed=True)), ('wi_stuff65.s:cnt_total_time', (0).to_bytes(4, 'little', signed=True)), ('wi_stuff65.s:cnt_par', (0).to_bytes(2, 'little', signed=True))]),
    ('wi-times-total', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:sp_state', (8).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (0).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt_time', (30000).to_bytes(4, 'little', signed=True)), ('wi_stuff65.s:cnt_total_time', (30000).to_bytes(4, 'little', signed=True)), ('wi_stuff65.s:cnt_par', (30000).to_bytes(2, 'little', signed=True))]),
    ('wi-pause', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:sp_state', (3).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (0).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt_pause', (1).to_bytes(2, 'little', signed=True))]),
    ('wi-pause-wait', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:sp_state', (5).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (0).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt_pause', (9).to_bytes(2, 'little', signed=True))]),
    ('wi-all-at-once', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:sp_state', (4).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (1).to_bytes(2, 'little', signed=True))]),
    ('wi-end-request', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:sp_state', (10).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (1).to_bytes(2, 'little', signed=True))]),
    ('wi-end-wait', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:sp_state', (10).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (0).to_bytes(2, 'little', signed=True))]),
    ('wi-shownext-blink', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:state', (1).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt', (25).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (0).to_bytes(2, 'little', signed=True))]),
    ('wi-shownext-request', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:state', (1).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt', (90).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (1).to_bytes(2, 'little', signed=True))]),
    ('wi-shownext-delay', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:state', (1).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt', (1).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:_g_acceleratestage', (0).to_bytes(2, 'little', signed=True))]),
    ('wi-nostate', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:state', (-1).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt', (5).to_bytes(2, 'little', signed=True))]),
    ('wi-nostate-end', 'wi_stuff65.s:WI_Ticker', 'tour', 'first',
     [('wi_stuff65.s:state', (-1).to_bytes(2, 'little', signed=True)), ('wi_stuff65.s:cnt', (1).to_bytes(2, 'little', signed=True))]),
]


def sym_address(table, text: str) -> int:
    base, _, off = text.partition('+')
    return table.address(base) + int(off or 0)


def synth_all() -> None:
    table = CL.Linkmap()
    for name, key, run, hit, pokes in SYNTH:
        out = case_dir(run, key) / ('s-%s.case.z' % name)
        if out.exists():
            continue
        if hit is None:         # the first case with a message set
            hit = message_hit(run, key)
        if hit == 'first':
            c = load_case(case_paths(run, key)[0])
        else:
            c = load_case(case_dir(run, key) / ('h%08d.case.z' % hit))
        made = call_at(c.entry, table.address(key), {},
                       [(sym_address(table, s), v) for s, v in pokes],
                       c.header, 'synthetic: %s' % name)
        save_case(made, run, key, out.name)
        say('synthetic %s: %s' % (name, out.name))
    # G_SecretExitLevel (no run calls it): G_ExitLevel's first case's state
    key = 'g_game65.s:G_SecretExitLevel'
    out = case_dir('tour', key) / 's-secret.case.z'
    if not out.exists():
        c = load_case(case_paths('tour', 'g_game65.s:G_ExitLevel')[0])
        made = call_at(c.entry, table.address(key), {}, [],
                       dict(c.header, routine=key),
                       'synthetic: G_SecretExitLevel at G_ExitLevel\'s call')
        save_case(made, 'tour', key, out.name)
    # G_WorldDone (entered by WI_Ticker's JML): at the tour's intermissions'
    # last WI_Ticker states, and after map 8 (gamemap poked 8), and with a
    # secret exit
    key = 'g_game65.s:G_WorldDone'
    wi = case_paths('tour', 'wi_stuff65.s:WI_Ticker')
    wd = case_paths('tour', 'g_game65.s:doWorldDone')
    # after map 8: the state after the tour's last load (E1M8: doWorldDone's
    # return), no level of another map under a poked gamemap
    for tag, src, after, pokes in (
            ('next', wi[-1:], False, []),
            ('map8', wd[-1:], True, []),
            ('secret', wi[-1:], False,
             [('g_game65.s:secretexit', b'\x01\x00')])):
        out = case_dir('tour', key) / ('s-%s.case.z' % tag)
        if out.exists() or not src:
            continue
        c = load_case(src[0])
        made = call_at(c.after if after else c.entry, table.address(key),
                       {}, [(table.address(s), v) for s, v in pokes],
                       dict(c.header, routine=key),
                       'synthetic: G_WorldDone (%s)' % tag)
        save_case(made, 'tour', key, out.name)


def poked_runs() -> List[str]:
    """The runs whose scripts poke memory (ticcap's stream events: the
    tour's stand-in for E1M3's secret exit, _g_wminfo.next)."""
    from native import ticcap as TC
    out = []
    for run in GC.RUNS:
        r = TC.load(run)
        if r and r.get('pokes'):
            out.append(run)
    return out


def recall_poked(max_cases: int = 20) -> Dict[str, Any]:
    """A capture's state at the return holds what the run's input wrote
    during the call; in a run whose script pokes memory, each case of an
    entry with few cases (no load: those run a level load) is run again
    alone on ref816 (--call of its entry state): a case whose return state
    differs from the capture's is set aside (cases/RUN/ROUTINE/
    poked.json, named in the report) and its --call twin (s-recall-...)
    is checked in its place."""
    table = CL.Linkmap()
    out: Dict[str, Any] = {}
    for run in poked_runs():
        for key in list(CAPTURED):
            if key in LOAD_ENTRIES or key == 'am_map65.s:AM_Ticker' or \
                    run not in CAPTURED[key]:
                continue
            paths = case_paths(run, key)
            if not paths or len(paths) > max_cases:
                continue
            d = case_dir(run, key)
            poked = {}
            for p in paths:
                c = load_case(p)
                again = call_at(c.entry, table.address(key), {}, [],
                                c.header, 'recalled: %s' % p.name)
                ranges = sorted(set(map(tuple, c.header['writes'])) |
                                set(map(tuple, again.header['writes'])))
                if any(c.after.read(a, n) != again.after.read(a, n)
                       for a, n in ranges):
                    poked[p.name] = 'the run\'s input wrote memory during ' \
                        'the call (a script poke); its --call twin ' \
                        's-recall-%s is checked in its place' % p.name
                    save_case(again, run, key, 's-recall-' + p.name)
            (d / 'poked.json').write_text(json.dumps(poked, indent=1) +
                                          '\n')
            out['%s %s' % (run, key)] = {'cases': len(paths),
                                         'poked': sorted(poked)}
            say('%s %s: %d cases run again alone, %d touched by the input'
                % (run, key, len(paths), len(poked)))
    return out


def set_aside(run: str, key: str) -> Dict[str, str]:
    p = case_dir(run, key) / 'poked.json'
    return json.loads(p.read_text()) if p.exists() else {}


def message_hit(run: str, key: str) -> int:
    for p in case_paths(run, key):
        c = load_case(p)
        a = CL.Linkmap().address('_g_player') + UP_MSG
        if c.entry.read(a, 4) != bytes(4):
            return c.header['hit']
    raise FlowError('no %s case of %s with a message' % (key, run))


def all_cases(key: str) -> List[Tuple[str, Path]]:
    runs = CAPTURED.get(key) or (DERIVED[key][1] if key in DERIVED else
                                 ('tour',))
    out = []
    for run in runs:
        aside = set_aside(run, key)
        for p in sorted(case_dir(run, key).glob('*.case.z')):
            if p.name not in aside:
                out.append((run, p))
    return out


# ---------------------------------------------------------------------------
# The native machine of a case
# ---------------------------------------------------------------------------

PLAIN_KINDS = ('symbol', 'lump', 'table', 'state')


def _plain(v: Any) -> bool:
    """A value the load's pre-state can hold: no reference to an object
    of a level (the load makes the level)."""
    if isinstance(v, R):
        return v.kind in PLAIN_KINDS
    if isinstance(v, (list, tuple)):
        return all(_plain(x) for x in v)
    if isinstance(v, dict):
        return all(_plain(x) for x in v.values())
    return True


def load_prestate(s_in: Dict[str, Any], setup: bool = True
                  ) -> Dict[str, Any]:
    """The globals and the player of a state with no level to write (a
    load-containing action's start, or the title loop's state), for the
    port writer: those naming a level object left out, and with `setup`
    those the setup always writes too (setupcheck.GLOBAL_WRITES,
    PLAYER_WRITES: they stay poisoned, so a write the native misses
    shows); no level objects (the load makes them)."""
    skip_g = ({p[0] for p in SC.GLOBAL_WRITES if len(p) == 1} if setup
              else set()) | set(SC.BOOT_GLOBALS)
    g = {}
    for k, v in s_in['globals'].items():
        if k in skip_g or not _plain(v):
            continue
        if setup and k == 'g_game65.s:_g_wminfo' and isinstance(v, dict):
            v = {f: x for f, x in v.items() if f != 'partime'}
        g[k] = v
    pl = dict(s_in['objects']['player'][0])
    if setup:
        for p in SC.PLAYER_WRITES:
            if len(p) == 1:
                pl.pop(p[0], None)
    pl = {f: v for f, v in pl.items() if _plain(v)}
    return {'globals': g, 'objects': {'player': {0: pl}}}


def read_plain(mf, memory, like: Dict[str, Any]) -> Dict[str, Any]:
    """The native globals and player fields that `like` has, decoded
    leaf by leaf through the manifest (a state with no level: the
    level's kinds are not read)."""
    from bridge.port import set_path
    r = PortReader(mf)
    r.m = memory
    r.problems = []
    gl: Dict[str, Any] = {}
    for leaf in mf.globals:
        if leaf.path[0] in like['globals'] and \
                leaf.enc['enc'] not in ('list', 'table'):
            set_path(gl, leaf.path, r.decode(leaf, 0), {})
    pl: Dict[str, Any] = {}
    want = like['objects']['player'][0]
    for leaf in mf.kinds['player']['leaves']:
        if leaf.path[0] in want:
            set_path(pl, leaf.path, r.decode(leaf, 0), {})
    return {'globals': gl, 'objects': {'player': {0: pl}}}


def trimmed(state: Dict[str, Any], like: Dict[str, Any]) -> Dict[str, Any]:
    """state's globals and player fields that `like` (a load_prestate)
    has: the comparison of a routine run on a state with no level."""
    pl = state['objects'].get('player', {}).get(0, {})
    return {'globals': {k: state['globals'].get(k) for k in like['globals']},
            'objects': {'player': {0: {f: pl.get(f) for f in
                                       like['objects']['player'][0]}}}}


def write_prestate(mf, s_in: Dict[str, Any], pm, setup: bool = True
                   ) -> Dict[str, Any]:
    """load_prestate()'s leaves through the manifest, leaf by leaf (as
    setupcheck.prestate writes a setup's: a leaf left out keeps the
    machine's poison); the pre-state."""
    from bridge.port import get_path
    pre = load_prestate(s_in, setup)
    w = PortWriter(mf)
    w.m = pm
    w.pool_fill = {}
    for leaf in mf.globals:
        if leaf.enc['enc'] in ('table', 'list'):
            continue
        try:
            value = get_path(pre['globals'], leaf.path)
        except (KeyError, IndexError, TypeError):
            continue
        w.encode(leaf, 0, value)
    pl = pre['objects']['player'][0]
    for leaf in mf.kinds['player']['leaves']:
        if leaf.path[0].startswith('@'):
            continue
        if setup and any(tuple(leaf.path[:len(p)]) == tuple(p)
                         for p in SC.PLAYER_WRITES):
            continue                # (the setup writes it: poisoned)
        try:
            value = get_path(pl, leaf.path)
        except (KeyError, IndexError, TypeError):
            continue
        w.encode(leaf, 0, value)
    return pre


def wad_name(text: bytes) -> str:
    """ExtractFileBase: after the last ':', '\\' or '/', up to 8 characters
    before a '.', upper case."""
    s = text.split(b'\0', 1)[0].decode('latin-1')
    for sep in (':', '\\', '/'):
        s = s.rsplit(sep, 1)[-1]
    return s.split('.', 1)[0][:8].upper()


def lump_by_name(mem, table, name: str) -> Optional[int]:
    """W_GetNumForName on the reference's directory: the last entry of
    the name."""
    fi = int.from_bytes(mem.read(table.address('w_wad65.s:fileinfo'), 3),
                        'little')
    count = mem.u16(table.address('w_wad65.s:numlumps'))
    found = None
    for i in range(count):
        n = mem.read(fi + 16 * i + 8, 8).split(b'\0', 1)[0]
        if n.decode('latin-1').upper() == name:
            found = i
    return found


DM_DIR, DM_LUMPS, DM_ESIZE = (dict(GL.DEMOB_LAYOUT)[k] for k in (
    'DM_DIR', 'DM_LUMPS', 'DM_ESIZE'))     # (glayout: request 1 applied)


def demob_records(up, mf) -> List[Tuple[int, int, int, bytes]]:
    """The demo bank (DEMOB, glayout.DEMOB_LAYOUT): the lumps the
    reference's state names (demobuffer, demo_p; the lump of defdemoname
    by W_GetNumForName on the reference's own directory, under that name)
    with their bytes from the reference's memory."""
    g = up.s_in['globals']
    mem = up.case.entry
    table = up.table
    named: Dict[int, Tuple[int, int]] = {}
    lumps = set()
    dn = g.get('g_game65.s:defdemoname')
    if isinstance(dn, R) and dn.kind == 'symbol':
        text = mem.read(table.address(dn.id) + (dn.field or 0), 16)
        i = lump_by_name(mem, table, wad_name(text))
        if i is not None:
            named[i] = (mf.symbol_of[dn.id], dn.field or 0)
            lumps.add(i)
    for k in ('g_game65.s:demobuffer', 'g_game65.s:demo_p'):
        v = g.get(k)
        if isinstance(v, R) and v.kind == 'lump':
            lumps.add(v.id)
    if not lumps:
        return []
    placement = up.r_in.placement.lumps
    data = bytearray([len(lumps)])
    at = DM_LUMPS
    out = []
    for i in sorted(lumps):
        address, size = placement[i]
        if at + size > LL.ROOM[1]:
            raise FlowError('the demo lumps pass DEMOB')
        nm = named.get(i, (0xFFFF, 0xFFFF))
        data += struct.pack('<HHHHH', nm[0], nm[1], i, size, at)
        out.append((1, LL.DEMOB, at, bytes(mem.read(address, size))))
        at += size
    out.append((1, LL.DEMOB, DM_DIR, bytes(data)))
    return out


def time_values(run: str) -> List[int]:
    from native import ticcap as TC
    r = TC.load(run)
    return [t['value'] for t in (r or {}).get('times', [])]


def rekey_of_state(gamemap: int, state: Dict[str, Any]) -> bytes:
    """The re-key record of a setup (GAME.md 3.6, ticcap.rekey_record_of)
    from the reference's state after it: its sight hints by pool slot and
    CS_PREV1/2. Upstream keys both by its zone addresses, which no native
    run can know: injected state with that reason, as ticcap's records
    are (ticcap's own records of the runs' later setups are empty: their
    states at the setup's end did not decode, an open point)."""
    from native import ticcap as TC
    g = state['globals']
    hints = [state['objects']['sighthint'][i]['line']
             for i in sorted(state['objects'].get('sighthint', {}))]
    return TC.rekey_record_of({
        'gamemap': gamemap, 'hints': hints,
        'cs_refs': [TC._ref_tuple(g.get('p_sight65.s:CS_PREV1')),
                    TC._ref_tuple(g.get('p_sight65.s:CS_PREV2'))]})


def rekey_for(run: str, gamemap: int, tic: int) -> bytes:
    """The re-key record of the run's setup at `tic` (ticcap.py's tic
    reference; GAME.md 3.6)."""
    from native import ticcap as TC
    r = TC.load(run)
    if r is None:
        raise FlowError('no tic reference of %s (python3 tools/native/'
                        'ticcap.py --runs %s)' % (run, run))
    for e in r['setups']:
        if e['gamemap'] == gamemap and e['tic'] == tic:
            return TC.rekey_record_of(e)
    raise FlowError('%s: no setup of E1M%d at tic %d in the tic reference'
                    % (run, gamemap, tic))


def native_value(item: Dict[str, Any], up, mf) -> bytes:
    data = up.source(item['from'])
    kind = item.get('as')
    if kind == 'mobj':
        h = GR.handle_of(mf, up.ref(int.from_bytes(data, 'little')))
        return h.to_bytes(2, 'little')
    if kind == 'symbol':
        p = int.from_bytes(data, 'little') & 0xFFFFFF
        if p == 0:
            return bytes(5)
        ref, why = up.r_in.classify(p, ('symbol',))
        if ref is None:
            raise FlowError('$%06X is no symbol (%s)' % (p, why))
        return bytes([1]) + struct.pack('<HH', mf.symbol_of[ref.id],
                                        ref.field or 0)
    return data


# ---------------------------------------------------------------------------
# The write log and the stray writes
# ---------------------------------------------------------------------------

WRITE_RANGES = ','.join(['main:0000-00FF', 'main:0200-BFFF', 'aux0-127',
                         'lc', GL.LC1_LOG, 'cpu:C000-C001', 'cpu:C006-C072',
                         'cpu:C074-C0FF', 'cpu:C800-CFFF'])


def inc_value(name: str, obj: Path = FLOW) -> int:
    """An equate of the part's generated ggame.inc."""
    for line in (obj / 'gen' / 'ggame.inc').read_text().splitlines():
        f = line.split()
        if len(f) >= 3 and f[0] == name and f[1] == '=':
            return int(f[2].lstrip('$'), 16)
    raise FlowError('no %s in ggame.inc' % name)


PL = {'_'.join(str(x) for x in path).upper(): at
      for path, _, at in LL.player_layout()}


def allowed_places(b) -> List[Tuple[str, int, int, int]]:
    """What the part's routines, the runtime and the driver may write in a
    routine run (no object of a level: the part reads and writes globals
    only): the zero page, the cost phase, the random indexes, the globals
    block (the player, WI_*, the test globals), the part's scratch block,
    the runtime's state and caches, W's images and planes (the driver's
    and fc_call's loads), MOBJP (the planes out), GTEST (the logs and the
    sweeps' records), the driver's descriptor and vector, the test-only
    harness data (fl_*)."""
    lab = b.labels
    desc = b.segments['DESC']
    out = [('main', 0, 0x0000, 0x0100), ('main', 0, LL.R.PHASE,
                                          LL.R.PHASE + 1),
           ('main', 0, LL.PRND, LL.MRND + 1),
           ('main', 0, LL.GBLOCK, GL.TIC_MAIN_END),     # (G_WSET too)
           # TEXTRANS: g_resume's textures of the load (wave 1 as
           # integrated, flow.md request 6)
           ('main', 0, LL.R.TEXTRANS, LL.R.TEXTRANS + 256),
           ('main', 0, inc_value('SB_FLOW', b.obj),
            inc_value('SB_FLOW', b.obj) + inc_value('SB_FLOW_SIZE', b.obj)),
           ('main', 0, LL.RT_STATE, LL.RT_END),
           ('main', 0, LL.MOC, LL.MOC + LL.MOC_LINES * LL.MOC_LINE),
           ('main', 0, LL.SCC, LL.SCC + LL.SCC_LINES * LL.SCC_LINE),
           ('main', 0, LL.BL_BUF, LL.BL_BUF + 0x100),
           ('main', 0, 0x6000, GL.WR['SLOT2'][1]),
           ('main', 0, LL.GW, LL.GW_END),
           ('main', 0, LL.PL_TNL, LL.PL_TICS + LL.PLANE_SLOTS),
           ('aux', LL.MOBJP, 0, 0x10000), ('aux', LL.GTEST, 0, 0x10000),
           ('lc', 0, desc[0], desc[1] + 1), ('lc', 0, 0xFFFE, 0x10000)]
    if 'fl_tgt' in lab:         # the test-only harness data (fl_*: in the
        # card's driver area since wave 1's integration)
        out.append(('lc' if lab['fl_tgt'] >= 0xC000 else 'main', 0,
                    lab['fl_tgt'], lab['fl_buf'] + 192))
    return out


def _inside(w, places) -> bool:
    return any(s == w.storage and (s != 'aux' or bank == w.bank) and
               lo <= w.offset < hi for s, bank, lo, hi in places)


IO_OK = lrun.IO_LOAD | lrun.IO_DRIVER


def strays(writes, b, load_header: Optional[Dict[str, Any]] = None
           ) -> List[str]:
    """The CPU writes outside the allowed places; a load run's writes
    between the action's return (the driver's dg_ra) and the load's end
    (drv_loaded's dg_loads) may also go where the setup writes
    (llayout.allowed_writes_setup of the loaded map)."""
    mine = allowed_places(b)
    load = list(mine)
    if load_header is not None:
        load += [(s, bank, lo, hi) for s, bank, lo, hi, _ in
                 LL.allowed_writes_setup(load_header)]
    lab = b.labels
    out = []
    phase = 0
    for w in writes:
        if w.storage == 'lc' and w.offset == lab['dg_ra'] and phase == 0 \
                and load_header is not None:
            phase = 1
        if w.storage == 'io':
            ok = w.address in IO_OK
        else:
            ok = _inside(w, load if phase == 1 else mine)
        if w.storage == 'lc' and w.offset == lab['dg_loads'] and phase == 1:
            phase = 2
        if not ok:
            out.append('pc $%04X wrote %s %d $%04X' % (
                w.pc, w.storage, w.bank, w.offset))
    return out


# ---------------------------------------------------------------------------
# A case's run
# ---------------------------------------------------------------------------

_GROUPS: Dict[str, Dict[str, int]] = {}


def group_of(b, name: str) -> int:
    """A routine's group in the build (its gen/gplace.inc's GP_name_G: an
    address alone does not tell, all the groups of a slot start at its
    first byte); a label that is no routine of the table (a helper the
    harness calls) is in the group whose segment holds it, when one
    does."""
    key = str(b.obj)
    if key not in _GROUPS:
        g = {}
        for line in (b.obj / 'gen' / 'gplace.inc').read_text().splitlines():
            f = line.split()
            if len(f) == 3 and f[0].startswith('GP_') and \
                    f[0].endswith('_G') and f[1] == '=':
                g[f[0][3:-2]] = int(f[2])
        _GROUPS[key] = g
    if name in _GROUPS[key]:
        return _GROUPS[key][name]
    addr = b.labels[name]
    if GL.WR['SLOT1'][0] <= addr < GL.WR['SLOT2'][1]:
        lst = (b.obj / (b.name + '.lbl'))
        del lst
        raise FlowError('%s is in a slot and no routine of the table'
                        % name)
    return 0


def phase_us(work: Path, profile: str) -> Dict[int, float]:
    """The cost model's time of each phase, in microseconds."""
    text = (work / 'cost.json').read_text()
    cost = json.loads(text[text.rfind('{"final"'):])['cost']
    mhz = costs.parameters(profile)['fabric_mhz']
    return {k: v / mhz for k, v in enumerate(cost['phases']) if v}


def phase_cycles(work: Path) -> Dict[int, int]:
    """The core's cycles of each phase (the report's phase_cycles)."""
    text = (work / 'cost.json').read_text()
    cost = json.loads(text[text.rfind('{"final"'):])['cost']
    return {k: v for k, v in enumerate(cost.get('phase_cycles', [])) if v}


def run_case(case, spec: Dict[str, Any], b, fill: int, profile: str,
             level=None, keep_state: bool = False) -> Dict[str, Any]:
    """The case on the part's image b, fill, profile; the comparison."""
    up = GR.Upstream(case)
    load = bool(spec.get('load'))
    res: Dict[str, Any] = {'case': case.path.name if case.path else '?',
                           'routine': case.key, 'run': case.header['run'],
                           'hit': case.header['hit'], 'fill': '%02x' % fill,
                           'profile': profile, 'ok': False}
    # a state with no level (the title loop: G_DeferedPlayDemo,
    # G_DeferedInitNew, G_ReloadDefaults there): the globals and the
    # player only, written and compared (the bridge reads no level there)
    nolevel = not load and bool(up.r_in.problems or up.r_out.problems)
    probs = up.r_out.problems if load else []
    if probs:
        res['error'] = 'bridge: ' + '; '.join(probs[:3])
        return res
    if nolevel:
        res['nolevel'] = True
    table = up.table
    gm_out = case.after.u16(table.address(GR.TIC_GAMEMAP))
    if not 1 <= gm_out <= 9:       # (no level: the globals' manifest of
        gm_out = 1                 #   any map)
    gm_in = up.gamemap if 1 <= up.gamemap <= 9 else gm_out
    if load:
        mf_w, header_w, _ = GR.manifest(gm_out)
        state = None
    else:
        mf_w, header_w, _ = GR.manifest(gm_in)
        state = up.s_in
    mf_r, header_r, banks = GR.manifest(gm_out)
    skip = gcanon.skips('routine', up.s_in)
    img = G.Image(b, fill, level=level if load else None, store=True)
    img.recs += GR.base_records(gm_in)
    pm = G.tracked_memory()
    pre = None
    if load:
        write_prestate(mf_w, up.s_in, pm)
    elif nolevel:
        pre = write_prestate(mf_w, up.s_in, pm, setup=False)
        # (the lists and tables of the level, which a state with no level
        # holds as empty or partial: neither written nor compared)
        pre['globals'] = {k: v for k, v in pre['globals'].items()
                          if not isinstance(v, list)}
    else:
        PortWriter(mf_w).write(gcanon.strip(state, skip), pm)
    img.recs += G.port_records(pm)
    img.recs += GR.derived(pm, header_w)
    img.recs += demob_records(up, mf_w)
    lab = b.labels
    regs = [0, 0, 0, 0x34]
    for item in spec.get('in', []):
        data = native_value(item, up, mf_w)
        to = item['to']
        if to in ('a', 'x', 'y'):
            regs['axy'.index(to)] = data[0]
        elif to == 'ax':
            regs[0], regs[1] = data[0], data[1]
        elif to.startswith('zp:'):
            n = item.get('bytes', len(data))
            img.main(GR.zp_address(to[3:]), data[:n].ljust(n, b'\0'))
        elif to.startswith('main:'):
            n = item.get('bytes', len(data))
            img.main(LL.G[to[5:]], data[:n].ljust(n, b'\0'))
        else:
            raise FlowError('an input destination %r' % to)
    target = lab[spec['native']]
    img.poke_word('fl_tgt', target)
    img.poke_label('fl_tgrp', bytes([group_of(b, spec['native'])]))
    if load:
        run = case.header['run']
        tic = up.case.after.u32(table.address('_g_gametic')) \
            if hasattr(up.case.after, 'u32') else int.from_bytes(
                case.after.read(table.address('_g_gametic'), 4), 'little')
        img.poke_word('dg_resume', lab['fl_tresume'])
        img.recs += GR.wset_records(case.entry)   # (upstream's W_SET)
        img.poke_label('dg_rekey', b'\0')
        img.gtest(GL.GTB['GT_REKEYS'], rekey_of_state(gm_out, up.s_out))
        times = time_values(run)
        img.poke_word('dg_tcount', len(times))
        img.gtest(GL.GTB['GT_TIMES'], struct.pack('<I', len(times)) +
                  b''.join(struct.pack('<I', v & 0xFFFFFFFF)
                           for v in times))
    work = tmpdir('run')
    try:
        mode = GL.MODES['ROUTINE_LOAD' if load else 'ROUTINE']
        r = G.run(img, work, mode, 'fl_timed', regs=tuple(regs),
                  banks=banks, profile=profile, write_log=WRITE_RANGES)
        ended = r.ended()
        res['ended'] = ended
        low = r.state.get('lowest_s', {}).get('s')
        res['stack'] = (G.DRV_STACK - low) if low is not None else None
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                res['stop'] = G.stop_codes(G.load_snapshot(p))
            return res
        ph = phase_us(work, profile)
        pc = phase_cycles(work)
        res['us'] = round(ph.get(PH_ENTRY, 0.0), 2)
        res['cycles'] = pc.get(PH_ENTRY, 0)
        if load:
            res['us_resume'] = round(ph.get(PH_RESUME, 0.0), 2)
            res['cycles_resume'] = pc.get(PH_RESUME, 0)
        writes = RC.read_writes(work / 'writes.log')
        res['writes'] = len(writes)
        st = strays(writes, b, header_r if load else None)
        res['strays'] = len(st)
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    if pre is not None:
        nat = read_plain(mf_r, SC.port_memory(m), pre)
        diff = gcanon.compare(trimmed(up.s_out, pre), trimmed(nat, pre),
                              'routine')
    else:
        nat = PortReader(mf_r).read(SC.port_memory(m))
        diff = gcanon.compare(up.s_out, nat, 'routine')
    out_regs = {'a': G.card_byte(m, lab['dg_ra']),
                'x': G.card_byte(m, lab['dg_rx']),
                'y': G.card_byte(m, lab['dg_ry'])}
    for item in spec.get('out', []):
        nv = item['native']
        if nv == 'ax':
            value = out_regs['a'] | out_regs['x'] << 8
        elif nv in out_regs:
            value = out_regs[nv]
        elif nv.startswith('main:'):
            a = LL.G[nv[5:]]
            value = int.from_bytes(bytes(m.main[a:a + item.get('bytes', 2)]),
                                   'little')
        elif nv.startswith('zp:'):
            a = GR.zp_address(nv[3:])
            value = int.from_bytes(bytes(m.main[a:a + item.get('bytes', 2)]),
                                   'little')
        else:
            raise FlowError('a native output %r' % nv)
        uv = int.from_bytes(up.source(item['upstream'], 'out'), 'little')
        mask = (1 << (8 * item.get('bytes', 2))) - 1
        if value & mask != uv & mask:
            diff.append('output %s: %X != %X' % (item['upstream'],
                                                 value & mask, uv & mask))
    if st:
        diff += ['stray: ' + s for s in st[:4]]
    res['diff'] = diff[:12]
    res['ok'] = not diff
    if keep_state:
        res['native'] = nat
    return res


def stop_of(b, name: str, profile: str = 'f121') -> Optional[int]:
    """The stop code (GS_STATUS) a routine ends a run with, from a tour
    state (victory: W_StartFinale's GS_FINALE); None when it returns."""
    case = load_case(case_paths('tour', 'g_game65.s:doCompleted')[0])
    r = run_case(case, {'native': name, 'in': [], 'out': []}, b, 0xA5,
                 profile)
    if r.get('ended') == 'halt':
        return None
    return (r.get('stop') or (None,))[0]


def _job(job) -> List[Dict[str, Any]]:
    path, obj, key, combos = job
    b = load_build(Path(obj))
    spec = args_spec()[key]
    level = level_build() if spec.get('load') else None
    case = load_case(Path(path))
    out = []
    for fill, profile in combos:
        try:
            out.append(run_case(case, spec, b, fill, profile, level))
        except Exception as error:      # reported per case, never hidden
            out.append({'case': Path(path).name, 'routine': key,
                        'fill': '%02x' % fill, 'profile': profile,
                        'ok': False, 'error': '%s: %s' % (
                            type(error).__name__, error)})
    return out


COMBOS = [(f, p) for f in FILLS for p in PROFILES]


def run_entry(key: str, obj: Path = FLOW, jobs: int = 2,
              paths: Optional[Sequence[Path]] = None,
              combos=COMBOS) -> List[Dict[str, Any]]:
    paths = list(paths if paths is not None else
                 [p for _, p in all_cases(key)])
    work = [(str(p), str(obj), key, tuple(combos)) for p in paths]
    out: List[Dict[str, Any]] = []
    if jobs <= 1:
        for w in work:
            out += _job(w)
        return out
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_job, work, chunksize=2):
            out += got
    return out


# the checkpoint's entries (GAME.md 2.4 row flow): every routine with
# captured or synthetic cases
CHECKPOINT = ('g_game65.s:readDemoTiccmd', 'g_game65.s:G_CheckDemoStatus',
              'g_game65.s:doCompleted', 'wi_stuff65.s:WI_Ticker',
              'st_stuff65.s:ST_Ticker', 'hu_stuff65.s:HU_Ticker',
              'g_game65.s:G_DeferedInitNew', 'g_game65.s:G_DeferedPlayDemo',
              'g_game65.s:doNewGame', 'g_game65.s:doPlayDemo',
              'g_game65.s:loadLevel', 'g_game65.s:doWorldDone',
              'g_game65.s:G_ExitLevel', 'g_game65.s:G_SecretExitLevel',
              'g_game65.s:G_WorldDone', 'g_game65.s:G_ReloadDefaults',
              'g_game65.s:checkOverrun', 'wi_stuff65.s:WI_End',
              'wi_stuff65.s:WI_checkForAccelerate')


def summary(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {'runs': len(results),
                           'equal': sum(1 for r in results if r.get('ok')),
                           'cases': len({(r.get('run'), r['case'])
                                         for r in results})}
    out['failed'] = out['runs'] - out['equal']
    for p in PROFILES:
        us = sorted(r['us'] for r in results if r.get('profile') == p and
                    r.get('us') is not None)
        out['us_' + p] = {'median': us[len(us) // 2] if us else None,
                          'worst': us[-1] if us else None}
        cy = sorted(r['cycles'] for r in results if r.get('profile') == p
                    and r.get('cycles') is not None)
        out['cycles_' + p] = {'median': cy[len(cy) // 2] if cy else None,
                              'worst': cy[-1] if cy else None}
        ur = sorted(r['us_resume'] for r in results
                    if r.get('profile') == p and r.get('us_resume'))
        if ur:
            out['us_resume_' + p] = {'median': ur[len(ur) // 2],
                                     'worst': ur[-1]}
    out['strays'] = sum(r.get('strays', 0) for r in results)
    st = [r['stack'] for r in results if r.get('stack') is not None]
    out['stack_most'] = max(st) if st else None
    out['first_failures'] = [{k: v for k, v in r.items() if k != 'native'}
                             for r in results if not r.get('ok')][:4]
    return out


def checkpoint(jobs: int = 2, keys: Sequence[str] = CHECKPOINT
               ) -> Dict[str, Any]:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {}
    for key in keys:
        start = time.time()
        res = run_entry(key, jobs=jobs)
        s = summary(res)
        s['eligible'] = s['cases']
        s['seconds'] = round(time.time() - start, 1)
        report[key] = s
        (RESULTS / (key.replace(':', '_') + '.json')).write_text(
            json.dumps({'key': key, 'summary': s, 'results': res},
                       indent=1) + '\n')
        say('%s: %d cases, %d runs, %d equal, %d failed, strays %d, '
            'f121 %s us, fastpath %s us (%.0f s)' % (
                key, s['cases'], s['runs'], s['equal'], s['failed'],
                s['strays'], s['us_f121'], s['us_fastpath'],
                s['seconds']))
        for f in s['first_failures'][:2]:
            say('   ', json.dumps(f)[:700])
    return report


# ---------------------------------------------------------------------------
# The sweeps
# ---------------------------------------------------------------------------

SW_HDR = GL.GTB['GT_SCHEDULE']
SW_REC = SW_HDR + 0x80
SW_END = GL.GTB['GT_TIMES']
SW_ITEMS = 24


# the harness's helpers that are no routine of the table: the routine
# whose group (segment) holds each
HOST = {'times100': 'WI_Ticker'}


def sweep_image(b, fill: int, case, items_in, items_out, target: str,
                records: Sequence[bytes]):
    """The image of a sweep: the state of `case` (a captured call of the
    routine: a sane machine), then the sweep's header and records."""
    up = GR.Upstream(case)
    gm = up.gamemap if 1 <= up.gamemap <= 9 else 1
    mf, header, banks = GR.manifest(gm)
    img = G.Image(b, fill, store=True)
    img.recs += GR.base_records(gm)
    pm = G.tracked_memory()
    PortWriter(mf).write(gcanon.strip(up.s_in, gcanon.skips(
        'routine', up.s_in)), pm)
    img.recs += G.port_records(pm)
    img.recs += GR.derived(pm, header)
    img.recs += demob_records(up, mf)
    lab = b.labels
    addr = lab[target]
    items = list(items_in) + list(items_out)
    if len(items) > SW_ITEMS:
        raise FlowError('%d sweep items' % len(items))
    rlen = sum(n for _, n in items)
    hdr = struct.pack('<HHBBBB', len(records), addr,
                      group_of(b, HOST.get(target, target)), len(items_in),
                      len(items_out), rlen)
    for a, n in items:
        hdr += struct.pack('<HB', a, n)
    img.gtest(SW_HDR, hdr)
    data = b''.join(r.ljust(rlen, b'\0') for r in records)
    if SW_REC + len(data) > SW_END:
        raise FlowError('the sweep\'s records pass GT_TIMES')
    img.gtest(SW_REC, data)
    return img, banks, rlen


def run_sweep(b, fill: int, profile: Optional[str], case, items_in,
              items_out, target: str, records: Sequence[bytes]
              ) -> Tuple[List[bytes], Dict[str, Any]]:
    img, banks, rlen = sweep_image(b, fill, case, items_in, items_out,
                                   target, records)
    work = tmpdir('sweep')
    try:
        r = G.run(img, work, GL.MODES['ROUTINE'], 'fl_sweep',
                  banks=(LL.GTEST,), profile=profile,
                  write_log=WRITE_RANGES)
        info = {'ended': r.ended()}
        if r.ended() != 'halt':
            p = work / 'crash.img'
            if p.exists():
                info['stop'] = G.stop_codes(G.load_snapshot(p))
            return [], info
        writes = RC.read_writes(work / 'writes.log')
        info['strays'] = strays(writes, b)[:4]
        info['stray_count'] = len(strays(writes, b))
        m = G.load_snapshot(work / 'done.img')
        if profile:
            ph = phase_us(work, profile)
            info['us_total'] = round(sum(ph.values()), 1)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    g = m.aux[LL.GTEST]
    nin = sum(n for _, n in items_in)
    out = []
    for k in range(len(records)):
        at = SW_REC + rlen * k
        out.append(bytes(g[at + nin:at + rlen]))
    return out, info


def chunks(xs: Sequence[Any], n: int) -> List[Sequence[Any]]:
    return [xs[i:i + n] for i in range(0, len(xs), n)]


def zp(name: str) -> int:
    return GR.zp_address(name)


def sweep_demo(run: str, b, combos) -> Dict[str, Any]:
    """readDemoTiccmd on every tic of the demo: each call's demo_p (as
    the lump's offset) and demoplayback in; the command, demo_p, demoplayback
    and the demo's end (GT_FLAGS) out, against the reference's."""
    lg = load_log(run)
    if lg is None:
        raise FlowError('no log of %s (--logs)' % run)
    calls = lg['calls']['readDemoTiccmd']
    cases = case_paths(run, 'g_game65.s:readDemoTiccmd')
    if not cases:
        raise FlowError('no readDemoTiccmd case of %s (--capture)' % run)
    case = load_case(cases[0])
    base = int.from_bytes(bytes.fromhex(calls[0]['in'][8:16]), 'little') \
        & 0xFFFFFF
    G_ = LL.G
    items_in = [(G_['G_DEMOP'] + 3, 2), (G_['G_DEMOPLAY'], 2),
                (G_['GT_FLAGS'], 1)]
    items_out = [(G_['G_PLAYER'] + PL['CMD_FORWARDMOVE'], 5),
                 (G_['G_DEMOP'] + 3, 2), (G_['G_DEMOPLAY'], 2),
                 (G_['GT_FLAGS'], 1)]
    recs, want = [], []
    for c in calls:
        i, o = c['in'], c['out']
        p = _u(i, 0, 4) & 0xFFFFFF
        recs.append(struct.pack('<HHB', (p - base) & 0xFFFF, _u(i, 10, 2),
                                0))
        if o is None:
            want.append(None)
            continue
        po = _u(o, 5, 4) & 0xFFFFFF
        ended = _u(o, 9, 2) == 0
        want.append((None if ended else bytes.fromhex(o[:10]),
                     (po - base) & 0xFFFF, _u(o, 9, 2), 1 if ended else 0))
    return _sweep_compare('readDemoTiccmd', run, b, combos, case, items_in,
                          items_out, recs, want, _demo_got, 2400)


def _demo_got(got: bytes):
    cmd, pos, play, flags = got[:5], got[5] | got[6] << 8, \
        got[7] | got[8] << 8, got[9] & 1
    return cmd, pos, play, flags


def _demo_eq(w, g) -> bool:
    cmd, pos, play, flags = g
    return (w[0] is None or w[0] == cmd) and w[1:] == (pos, play, flags)


def _sweep_compare(name, run, b, combos, case, items_in, items_out, recs,
                   want, decode, size, eq=None) -> Dict[str, Any]:
    eq = eq or _demo_eq
    rlen = sum(n for _, n in list(items_in) + list(items_out))
    size = min(size, (SW_END - SW_REC) // rlen)
    out: Dict[str, Any] = {'calls': len(recs), 'runs': 0, 'failed': 0,
                           'first': [], 'strays': 0, 'us_total': {}}
    for fill, profile in combos:
        start = 0
        for part in chunks(list(range(len(recs))), size):
            got, info = run_sweep(b, fill, profile, case, items_in,
                                  items_out, _target(name),
                                  [recs[k] for k in part])
            out['runs'] += 1
            if not got:
                out['failed'] += len(part)
                out['first'].append('%s %02x: ended %s %s' % (
                    name, fill, info.get('ended'), info.get('stop')))
                continue
            out['strays'] += info.get('stray_count', 0)
            if info.get('us_total'):
                out['us_total'].setdefault(profile, 0.0)
                out['us_total'][profile] += info['us_total']
            for k, g in zip(part, got):
                w = want[k]
                if w is None:
                    continue
                if not eq(w, decode(g)):
                    out['failed'] += 1
                    if len(out['first']) < 4:
                        out['first'].append('%s %s call %d (%02x %s): %r, '
                                            'the reference %r' % (
                                                name, run, k + 1, fill,
                                                profile, decode(g), w))
            start += len(part)
    return out


def _target(name: str) -> str:
    return {'readDemoTiccmd': 'readDemoTiccmd', 'ST_Ticker': 'ST_Ticker',
            'HU_Ticker': 'HU_Ticker', 'WI_Ticker': 'WI_Ticker',
            'times100': 'times100', 'div1000': 'div1000',
            'signLong': 'signLong'}[name]


def sweep_st(run: str, b, combos) -> Dict[str, Any]:
    """ST_Ticker on every tic: M_Random's index in; the index and the
    value out."""
    lg = load_log(run)
    calls = lg['calls']['ST_Ticker']
    case = load_case(case_paths(run, 'st_stuff65.s:ST_Ticker')[0])
    items_in = [(LL.MRND, 1)]
    items_out = [(LL.MRND, 1), (b.labels['fl_ra'], 1)]
    recs = [bytes([_u(c['in'], 0, 1)]) for c in calls]
    want = [(_u(c['out'], 0, 1), _u(c['out'], 2, 1)) for c in calls]
    return _sweep_compare('ST_Ticker', run, b, combos, case, items_in,
                          items_out, recs, want,
                          lambda g: (g[0], g[1]), 9000,
                          eq=lambda w, g: w == g)


def sweep_hu(run: str, b, combos) -> Dict[str, Any]:
    """HU_Ticker on every tic: a message set or not (its tag), showMessages
    and G_MSGKEEP in; the message's tag and G_MSGKEEP out."""
    lg = load_log(run)
    calls = lg['calls']['HU_Ticker']
    case = load_case(case_paths(run, 'hu_stuff65.s:HU_Ticker')[0])
    G_ = LL.G
    pm = G_['G_PLAYER'] + PL['MESSAGE']
    items_in = [(pm, 5), (G_['G_SHOWMSG'], 2), (G_['G_MSGKEEP'], 2)]
    items_out = [(pm, 1), (G_['G_MSGKEEP'], 2)]
    recs, want = [], []
    for c in calls:
        i, o = c['in'], c['out']
        msg = _u(i, 0, 4) != 0
        recs.append((b'\x01\x00\x00\x00\x00' if msg else bytes(5)) +
                    bytes.fromhex(i[8:16]))
        want.append((1 if _u(o, 0, 4) else 0, _u(o, 4, 2)))
    return _sweep_compare('HU_Ticker', run, b, combos, case, items_in,
                          items_out, recs, want,
                          lambda g: (g[0], g[1] | g[2] << 8), 6000,
                          eq=lambda w, g: w == g)


def sweep_wi(run: str, b, combos) -> Dict[str, Any]:
    """WI_Ticker on every intermission tic: the wi counters, G_WMINFO,
    gamemap, secretexit, the player's buttons, attackdown, usedown,
    gameaction and didsecret in; the counters, attackdown, usedown,
    gameaction, didsecret and the sounds started out."""
    lg = load_log(run)
    calls = lg['calls']['WI_Ticker']
    case = load_case(case_paths(run, 'wi_stuff65.s:WI_Ticker')[0])
    G_, P_ = LL.G, PL
    pl = G_['G_PLAYER']
    # (the native wi counters are upstream's 30 bytes in its order, from
    # WI_ACCEL; attackdown and usedown are next to each other)
    at = G_[WI_NATIVE[0]]
    for n, v in zip(WI_NATIVE, WI_VARS):
        if G_[n] != at:
            raise FlowError('the wi counters are not in upstream\'s order')
        at += int(v.split(':')[-1])
    if P_['USEDOWN'] != P_['ATTACKDOWN'] + 2:
        raise FlowError('attackdown and usedown apart')
    wi = [(G_['WI_ACCEL'], 30)]
    tail_in = [(G_['G_WMINFO'], 40), (G_['G_GAMEMAP'], 2),
               (G_['G_SECRETEXIT'], 2), (pl + P_['CMD_FORWARDMOVE'], 5),
               (pl + P_['ATTACKDOWN'], 4), (G_['G_GAMEACTION'], 2),
               (pl + P_['DIDSECRET'], 2), (G_['GT_SNDLOG'], 2)]
    items_in = wi + tail_in
    items_out = wi + [(pl + P_['ATTACKDOWN'], 4), (G_['G_GAMEACTION'], 2),
                      (pl + P_['DIDSECRET'], 2), (G_['GT_SNDLOG'], 2)]
    recs, want = [], []
    for c in calls:
        i, o = c['in'], c['out']
        recs.append(bytes.fromhex(i) + b'\0\0')
        want.append(bytes.fromhex(o) + struct.pack('<H', c['sounds']))
    return _sweep_compare('WI_Ticker', run, b, combos, case, items_in,
                          items_out, recs, want, lambda g: g, 120,
                          eq=lambda w, g: w == g)


def sweeps(obj: Path = FLOW, combos=((0xA5, 'f121'), (0x5A, 'fastpath'))
           ) -> Dict[str, Any]:
    b = load_build(obj)
    out = {}
    for run in ('demo3', 'demo1', 'demo2'):
        out['readDemoTiccmd/' + run] = sweep_demo(run, b, combos)
    out['ST_Ticker/demo3'] = sweep_st('demo3', b, combos)
    out['HU_Ticker/demo3'] = sweep_hu('demo3', b, combos)
    out['WI_Ticker/tour'] = sweep_wi('tour', b, combos)
    for k, v in out.items():
        say('%s: %d calls, %d runs, %d failed, strays %d %s' % (
            k, v['calls'], v['runs'], v['failed'], v['strays'],
            '; '.join(v['first'][:2])))
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / 'sweeps.json').write_text(json.dumps(out, indent=1) + '\n')
    return out


# ---------------------------------------------------------------------------
# The arithmetic helpers against upstream's (mathref batch)
# ---------------------------------------------------------------------------

def edge_values(bits: int) -> List[int]:
    m = (1 << bits) - 1
    h = 1 << (bits - 1)
    return [0, 1, m, 2, m - 1, h, h - 1, h + 1, 100, 1000, 999, 1001]


HELPERS = {
    # name: (upstream label, upstream in items, upstream out items,
    #        native in items, native out items, input bits)
    'times100': ('wi_stuff65.s:times100', [('_Dp', 4)], [('_Dp', 4)],
                 [('M_A', 4)], [('M_A', 4)], 32),
    'div1000': ('g_game65.s:div1000', [('g_game65.s:GG_T', 4)],
                ['a', 'x', ('_Dp', 4)], [('GA_0', 4)],
                [('GA_4', 4), ('GA_0', 4)], 32),
    'signLong': ('g_game65.s:signLong', ['a', 'x'],
                 [('_g_wminfo+20', 4)],
                 [('FC_A', 1), ('FC_X', 1), ('FC_Y', 1)],
                 [('G_WMINFO+20', 4)], 16),
}


def _native_addr(name: str) -> int:
    base, _, off = name.partition('+')
    if base in LL.G:
        a = LL.G[base]
    elif base in ('M_A', 'M_B', 'M_R', 'M_T'):
        a = {'M_A': 0xC0, 'M_B': 0xC4, 'M_R': 0xC8, 'M_T': 0xCC}[base]
    elif base.startswith('GA_') and base[3:].isdigit():
        a = GR.zp_address('GA_0') + int(base[3:])
    else:
        a = GR.zp_address(base)
    return a + int(off or 0)


def helper_inputs(name: str, count: int, seed: int = 10) -> List[int]:
    bits = HELPERS[name][5]
    rng = random.Random(seed)
    if bits == 16:
        return list(range(1 << 16))          # every value
    vals = edge_values(bits)
    vals += [(-v) & ((1 << bits) - 1) for v in (1, 2, 100, 1000)]
    while len(vals) < count:
        vals.append(rng.getrandbits(bits))
    return vals[:count]


def upstream_batch(name: str, values: Sequence[int]) -> List[bytes]:
    label, up_in, up_out, _, _, bits = HELPERS[name]
    table = CL.Linkmap()
    work = tmpdir('mathref')
    try:
        def item(it) -> str:
            if isinstance(it, str):
                return it
            sym, n = it
            s, _, off = sym.partition('+')
            return '%06X %d' % (table.address(s) + int(off or 0), n)
        spec = ['routine %s %06X' % (name, table.address(label))]
        spec += ['in ' + item(it) for it in up_in]
        spec += ['out ' + item(it) for it in up_out]
        (work / 'spec.txt').write_text('\n'.join(spec) + '\n')
        entry = load_case(case_paths(
            'tour', 'g_game65.s:doCompleted')[0]).regs_in
        (work / 'e.entry').write_text(
            'pc %06X\ndbr %02X\nd %04X\np 00\ne 0\ns 3FF0\na 0\nx 0\ny 0\n'
            'ret 2\nstack 00 00\nswitches %s\n' % (
                table.address(label), entry['dbr'], entry['d'],
                (MATH_BASE / 'mrandom.entry').read_text().split(
                    'switches', 1)[1].strip().splitlines()[0]))
        data = bytearray()
        for v in values:
            if name == 'signLong':
                data += struct.pack('<HH', v, 20)
            else:
                data += struct.pack('<I', v)
        (work / 'cases.bin').write_bytes(bytes(data))
        r = bounded.run([str(MATHREF), 'batch', str(MATH_BASE / 'base.ram'),
                         str(work / 'e.entry'), str(work / 'spec.txt'), name,
                         str(work / 'cases.bin'), str(work / 'out.bin')],
                        timeout=1800, max_bytes=1 << 28,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True)
        if r.returncode:
            raise FlowError('mathref batch %s: %s' % (name, r.stderr[-500:]))
        raw = (work / 'out.bin').read_bytes()
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    n_out = sum(2 if isinstance(it, str) else it[1] for it in up_out)
    size = n_out + 4
    return [raw[k:k + n_out] for k in range(0, len(raw), size)]


def native_batch(name: str, values: Sequence[int], b, fill: int = 0xA5
                 ) -> List[bytes]:
    _, _, _, n_in, n_out, bits = HELPERS[name]
    items_in = [(_native_addr(a), n) for a, n in n_in]
    items_out = [(_native_addr(a), n) for a, n in n_out]
    case = load_case(case_paths('tour', 'g_game65.s:doCompleted')[0])
    recs = []
    for v in values:
        if name == 'signLong':
            recs.append(bytes([v & 0xFF, v >> 8, 20]))
        else:
            recs.append(struct.pack('<I', v))
    rlen = sum(n for _, n in n_in + n_out)
    size = (SW_END - SW_REC) // rlen
    out: List[bytes] = []
    for part in chunks(recs, size):
        got, info = run_sweep(b, fill, None, case, items_in, items_out,
                              name, part)
        if not got:
            raise FlowError('the native %s: %s' % (name, info))
        out += got
    return out


def compare_helper(name: str, count: int, b) -> Dict[str, Any]:
    values = helper_inputs(name, count)
    up = upstream_batch(name, values)
    nat = native_batch(name, values, b)
    bad = []
    for v, u, n in zip(values, up, nat):
        if name == 'div1000':
            uq = u[0:2] + u[2:4]          # X:C: C low, X high words
            want = uq + u[4:8]
        else:
            want = u
        if want != n:
            bad.append((v, want.hex(), n.hex()))
    return {'inputs': len(values), 'failed': len(bad),
            'first': bad[:4], 'exhaustive': HELPERS[name][5] == 16}


# the random check's own planted bug: times100 without its * 64 term
HELPER_PLANT = ('game/flow/gwi.s', """        jsr @x2                 ; * 64
        jsr @add""", """        jsr @x2                 ; (planted: no * 64 term)
        nop
        nop
        nop""")


def random_plant(count: int = 500) -> Dict[str, Any]:
    """The random check catches a planted helper bug (a scratch copy)."""
    tmp = tmpdir('rplant')
    try:
        b = load_build(planted(tmp, [HELPER_PLANT]))
        return compare_helper('times100', count, b)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


def random_checks(count: int = 100000, obj: Path = FLOW) -> Dict[str, Any]:
    b = load_build(obj)
    out = {n: compare_helper(n, count, b) for n in HELPERS}
    out['planted times100'] = random_plant()
    for n, r in out.items():
        say('%s: %d inputs%s, %d failed %s' % (
            n, r['inputs'], ' (every value)' if r['exhaustive'] else '',
            r['failed'], r['first'][:2]))
    out['planted times100']['caught'] = out['planted times100']['failed'] > 0
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / 'random.json').write_text(json.dumps(out, indent=1) + '\n')
    return out


# ---------------------------------------------------------------------------
# The planted bugs (GAME.md 2.4 row flow): name, the check, the edits
# ---------------------------------------------------------------------------

PLANTS = {
    'angleturn-not-shifted': ('readDemoTiccmd', [(
        'game/flow/gflow.s',
        """        stz PLR + PL_CMD_ANGLETURN      ; angleturn = byte << 8
        lda FL_CMD+2
        sta PLR + PL_CMD_ANGLETURN + 1""",
        """        lda FL_CMD+2                    ; (planted: not shifted)
        sta PLR + PL_CMD_ANGLETURN
        stz PLR + PL_CMD_ANGLETURN + 1""")]),
    'secret-exit-next-map': ('doCompleted', [(
        'game/flow/gflow.s',
        """        lda #8                  ; next: the secret level 9 (8), or 4 (3)""",
        """        lda #9                  ; (planted: the next map's)""")]),
    'kills-step-not-2': ('WI_Ticker', [(
        'game/flow/gwi.s',
        """        lda (GT_0)
        adc #2
        sta (GT_0)""",
        """        lda (GT_0)
        adc #1                  ; (planted: a step of 1)
        sta (GT_0)""")]),
    'm-random-not-called': ('ST_Ticker', [(
        'game/flow/gwi.s',
        # (the final integration: since milestone 11's request R4 st_tick
        # calls g_mrandom and goes on to ST_TickerHook)
        """        jsr g_mrandom           ; M_Random (gthink.s; st_randomnumber is""",
        """        lda #0                  ; (planted: no M_Random)""")]),
    'demoplayback-not-set': ('doPlayDemo', [(
        'game/flow/gflow.s',
        """        lda #1
        sta G_DEMOPLAY
        stz G_DEMOPLAY+1
        jsr I_GetTime""",
        """        lda #0                  ; (planted: no demoplayback)
        sta G_DEMOPLAY
        stz G_DEMOPLAY+1
        jsr I_GetTime""")]),
    'message-cleared-messages-off': ('HU_Ticker', [(
        'game/flow/gwi.s',
        """        ora G_MSGKEEP+1
        beq @rts""",
        """        ora G_MSGKEEP+1
        nop                     ; (planted: messages off cleared too)
        nop""")]),
}
# each plant's check: the entry and the cases it runs (all of the entry's
# cases but for the sweeps' long lists: a sample with the paths)
PLANT_CHECK = {
    'readDemoTiccmd': ('g_game65.s:readDemoTiccmd', 12),
    'doCompleted': ('g_game65.s:doCompleted', 0),
    'WI_Ticker': ('wi_stuff65.s:WI_Ticker', 0),
    'ST_Ticker': ('st_stuff65.s:ST_Ticker', 12),
    'doPlayDemo': ('g_game65.s:doPlayDemo', 0),
    'HU_Ticker': ('hu_stuff65.s:HU_Ticker', -1),
}


def plant_cases(check: str) -> List[Path]:
    key, k = PLANT_CHECK[check]
    paths = [p for _, p in all_cases(key)]
    if k == -1:                 # the synthetic cases only
        return [p for p in paths if p.name.startswith('s-')]
    if k:
        return paths[::max(1, len(paths) // k)][:k]
    return paths


def run_plant(name: str, jobs: int = 2) -> Dict[str, Any]:
    check, bugs = PLANTS[name]
    key = PLANT_CHECK[check][0]
    paths = plant_cases(check)
    tmp = tmpdir('plant')
    try:
        obj = planted(tmp, bugs)
        res = run_entry(key, obj=obj, jobs=jobs, paths=paths,
                        combos=[(0xA5, 'f121')])
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    failed = [r for r in res if not r.get('ok')]
    return {'check': check, 'routine': key, 'cases': len(paths),
            'failed': len(failed), 'caught': bool(failed),
            'first': ((failed[0].get('diff') or [failed[0].get('error') or
                                                 failed[0].get('ended')])
                      [:2] if failed else None)}


def plants(jobs: int = 2) -> Dict[str, Any]:
    out = {}
    for name in PLANTS:
        r = run_plant(name, jobs)
        out[name] = r
        say('%-30s %s' % (name, ('caught: %d of %d cases fail: %s' % (
            r['failed'], r['cases'], str(r['first'])[:200]))
            if r['caught'] else 'NOT CAUGHT (%d cases)' % r['cases']))
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / 'plants.json').write_text(json.dumps(out, indent=1) + '\n')
    return out


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def du(path: Path) -> int:
    total = 0
    for p in path.rglob('*'):
        if p.is_file():
            total += p.stat().st_size
    return total


def write_report() -> Dict[str, Any]:
    b = load_build()
    sizes = part_sizes(b)
    rep: Dict[str, Any] = {
        'format': 'game-part-report 1', 'part': 'flow', 'wave': 1,
        'bytes': {'native': sum(sizes.values()), 'modules': sizes,
                  'budget': BUDGET, 'test_only_bytes': test_bytes(b)},
        'entries': {}, 'build_bytes': du(FLOW)}
    for p in sorted(RESULTS.glob('*.json')):
        d = json.loads(p.read_text())
        if 'summary' in d:
            s = d['summary']
            key = d['key']
            lowest = s.get('stack_most')
            rep['entries'][key] = {
                'cases_eligible': s.get('eligible', s['cases']),
                'cases_run': s['cases'], 'runs': s['runs'],
                'failures': s['failed'], 'stray_writes': s['strays'],
                'cycles_f121': s.get('cycles_f121'),
                'cycles_fastpath': s.get('cycles_fastpath'),
                'us_f121': s.get('us_f121'),
                'us_fastpath': s.get('us_fastpath'),
                'us_resume_f121': s.get('us_resume_f121'),
                'us_resume_fastpath': s.get('us_resume_fastpath'),
                'stack_bytes_most': lowest,
                'lowest_s': None if lowest is None else
                '$01%02X' % (G.DRV_STACK - lowest)}
        else:
            rep[p.stem] = d
    rep['failures'] = sum(e['failures'] for e in rep['entries'].values())
    rep['stray_writes'] = sum(e['stray_writes'] for e in
                              rep['entries'].values())
    st = [e['stack_bytes_most'] for e in rep['entries'].values()
          if e['stack_bytes_most'] is not None]
    rep['stack_bytes_most'] = max(st) if st else None
    rep['lowest_s'] = None if not st else '$01%02X' % (G.DRV_STACK -
                                                       max(st))
    rep['victory_stop'] = G.GS_NAMES.get(stop_of(b, 'victory'))
    rep['grep_check'] = GR.grep_check(SRC / 'game' / 'flow',
                                      ('gflow.s', 'gwi.s'))
    REPORT.write_text(json.dumps(rep, indent=1) + '\n')
    return rep


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--build', action='store_true')
    ap.add_argument('--capture', action='store_true')
    ap.add_argument('--keys')
    ap.add_argument('--logs', action='store_true')
    ap.add_argument('--checkpoint', action='store_true')
    ap.add_argument('--sweeps', action='store_true')
    ap.add_argument('--random', action='store_true')
    ap.add_argument('--count', type=int, default=100000)
    ap.add_argument('--plants', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--jobs', type=int, default=2)
    a = ap.parse_args(argv)
    keys = a.keys.split(',') if a.keys else None
    status = 0
    if a.build:
        make_part()
        b = load_build()
        say('flow: %s B of %d (gflow %d, gwi %d); test-only %d B' % (
            sum(part_sizes(b).values()), BUDGET, part_sizes(b)['gflow'],
            part_sizes(b)['gwi'], test_bytes(b)))
    if a.logs:
        make_logs()
    if a.capture:
        capture_all(keys)
    if a.checkpoint:
        rep = checkpoint(a.jobs, keys or CHECKPOINT)
        status |= any(s['failed'] or s['strays'] for s in rep.values())
    if a.sweeps:
        rep = sweeps()
        status |= any(v['failed'] or v['strays'] for v in rep.values())
    if a.random:
        rep = random_checks(a.count)
        status |= any(v['failed'] for k, v in rep.items()
                      if not k.startswith('planted'))
        status |= not rep['planted times100']['caught']
    if a.plants:
        rep = plants(a.jobs)
        status |= not all(v['caught'] for v in rep.values())
    if a.report:
        rep = write_report()
        say(json.dumps({k: v for k, v in rep.items() if k != 'entries'},
                       indent=1)[:2000])
    return 1 if status else 0


if __name__ == '__main__':
    sys.exit(main())
