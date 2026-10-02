#!/usr/bin/env python3
"""The routine harness's reference side (milestone 10, docs/GAME.md 3.5):
the survey of the game's entry routines in play, and the captures of
chosen calls, distilled into cases.

Usage:  python3 tools/native/gamecap.py --survey [--runs demo3,demo1,...]
        python3 tools/native/gamecap.py --capture FILE:LABEL --run demo3
                                        [--hits N,N-M | --all | --sample K]

The runs (RUNS): demo3 (the title loop to the end of its demo, lumps.py's
demo_script), demo1 and demo2 (the same with the lump placed as DEMO3,
lumps.options), newgame and tour (coverage/newgame.script, tour.script).
Each runs the release on ref816 at normal priority, bounded in wall
time, in file size and in log size; nothing of a run is kept but what
this tool distils.

--survey: a call log (ref816 --call-log, read from a pipe as it comes,
never stored) of G_Ticker's entries with _g_gametic, of every entry
routine of glayout.PARTS and of the skeleton's own routines in play
(SURVEY_CORE: P_SpawnMobj, P_SetThingPosition, P_CreateSecNodeList),
entry and return, and of every dispatch target (glayout's tables; entry
only, jumps=1 for the JML [dp] targets). Each call gets its tic (the
gametic of the last G_Ticker entry), its parent routine and the dispatch
targets reached inside it. Written to build/native/game/shared/survey/
RUN.json.z (format "game-survey 1"): for each routine its calls' tics
(one a call, in hit order), the dispatch targets each call reached (by
hit, only calls that reached any), the parent routines with their call
counts, the calls a tic (the median, p99 and most over the run's tics
with game activity); the run's tics. The index survey.json lists the
runs. The survey is the skeleton's and the integrator's: the parts only
read it (GAME.md 2.5).

--capture: ref816 --capture of chosen calls of one routine in one run, in
batches (BATCH calls a run, the free disk checked first), each raw
capture distilled at once into a case and deleted: build/native/game/
cases/RUN/ROUTINE/hNNNNNNNN.case.z (format "game-routine-case 1"): zlib of
a JSON header line (the routine, the run, the hit, the tic, the call's
registers at the entry and the return, its read and written bytes as
ranges, the pages kept), then the kept pages of RAM at the entry xor'ed
against the run's base (cases/RUN/base.ram.z: the whole RAM at the run's
first captured call, kept once a run), then the bytes the call wrote with
their values at its return. The pages kept: every page the bridge's
reader reads at the entry and after the return (so the reader decodes the
case's states exactly from them and the base), and every page the call
read or wrote. load_case() gives a case back as the memories at the entry
and at the return.
"""

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, \
    Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge import memory as bmem, upstream  # noqa: E402
from native import glayout as GL  # noqa: E402
from ref816 import bounded, calls as CL, lumps, run_script, script, \
    title  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
SURVEY = GL.SHARED / 'survey'
CASES = GL.GAME / 'cases'
RUNS = ('demo3', 'demo1', 'demo2', 'newgame', 'tour')
SURVEY_FORMAT = 'game-survey 1'
CASE_FORMAT = 'game-routine-case 1'
SURVEY_CORE = ('p_spawn65.s:P_SpawnMobj', 'p_map65.s:P_SetThingPosition',
               'p_map65.s:P_CreateSecNodeList')
TICKER = 'g_game65.s:G_Ticker'
TIC_NAME = '@tic'               # G_Ticker's entries with the gametic
DEMO_SECONDS = 3000
RUN_TIMEOUT = 1800              # a run's wall time
MAX_FILE = 1 << 30              # no file of a run past this
CALL_LOG_LIMIT = 8 << 30        # the survey's log, through the pipe
BATCH = 40                      # captures a run (6.3 MB of RAM each)
MIN_FREE = 20 * 10 ** 9
RAM_BANKS = [b for b in range(0x80)] + [0xE0, 0xE1]
PAGE = 0x100


class CapError(Exception):
    pass


# ---------------------------------------------------------------------------
# The runs
# ---------------------------------------------------------------------------

def symbols() -> script.Symbols:
    return CL.Linkmap().symbols


def program(run: str, work: Path) -> Tuple[Path, List[str], float]:
    """The run's script (written into work), the machine's extra options
    (a placed lump) and its time limit in seconds."""
    title.build_machine()
    title.ensure_image()
    work.mkdir(parents=True, exist_ok=True)
    if run.startswith('demo'):
        name = 'DEMO' + run[4:]
        info = lumps.demo_info(lumps.read_wad()[name])
        path = work / (run + '.script')
        path.write_text(lumps.demo_script(info['map'], DEMO_SECONDS))
        extra = [] if name == 'DEMO3' else lumps.options(
            name, symbols(), out=work / 'lumps')
        return path, extra, DEMO_SECONDS + 120
    if run in ('newgame', 'tour'):
        return run_script.script_path(run), [], run_script.\
            DEFAULT_LIMIT_SECONDS
    stream = GL.SHARED / 'streams' / (run + '.lmp')
    if run[:1] == 'G' and run[1:].isdigit() and stream.exists():
        # a generated stream of ticgen.py (GAME.md 3.7): its lump placed as
        # DEMO3, the title loop to its end (the final integration)
        info = json.loads((stream.with_suffix('.json')).read_text())
        path = work / (run + '.script')
        path.write_text(lumps.demo_script(info['gamemap'], DEMO_SECONDS))
        extra = ['--wad', '%06X' % lumps.wad_address(symbols()),
                 '--lump', '%s:%06X:%s' % (lumps.ENTRY, lumps.DEST, stream)]
        return path, extra, DEMO_SECONDS + 120
    raise CapError('no run %s (one of %s)' % (run, ', '.join(RUNS)))


def check_disk() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    st = os.statvfs(str(BUILD))
    free = st.f_bavail * st.f_frsize
    if free < MIN_FREE:
        raise CapError('only %.1f GB free: captures stop below 20 GB'
                       % (free / 1e9))


def machine(run: str, work: Path, extra: Sequence[str],
            reader=None, fifo: Optional[Path] = None,
            stream_reader=None, script_text: Optional[str] = None
            ) -> Dict[str, Any]:
    """One run of the release on ref816 (run_script's checks), with extra
    options: reader(handle) reads fifo (a named pipe the machine writes,
    a call log) and stream_reader(handle) the machine's standard output (a
    dump stream, --dump-stream -) while the machine runs; script_text
    replaces the run's script. The run's state and problems."""
    path, more, seconds = program(run, work)
    if script_text is not None:
        path = work / (run + '-own.script')
        path.write_text(script_text)
    syms = symbols()
    prog = script.compile_script(path.read_text(), syms, path.name)
    (work / 'input.txt').write_text(prog)
    shots = work / 'shots'
    shots.mkdir(exist_ok=True)
    cmd = [str(title.MACHINE), str(title.MEMORY), '--disk', str(title.DISK),
           '--input', str(work / 'input.txt'), '--shot-dir', str(shots),
           '--stop-on-fault', '--marks', str(work / 'marks.txt'),
           '--state', str(work / 'state.json'),
           '--frames', str(script.frames(seconds))]
    for unit, name in run_script.STOPS:
        cmd += ['--stop-pc', '%06X' % syms.address(unit + ':' + name)]
    for unit, name in (run_script.LOOP, run_script.RENDER):
        cmd += ['--mark', '%06X' % syms.address(unit + ':' + name)]
    cmd += list(more) + list(extra)
    errors: List[BaseException] = []
    threads: List[threading.Thread] = []

    def start(target) -> None:
        def body():
            try:
                target()
            except BaseException as error:     # reported below
                errors.append(error)
        t = threading.Thread(target=body)
        t.daemon = True
        t.start()
        threads.append(t)

    if reader is not None and fifo is not None:
        def read_fifo():
            with open(str(fifo), 'rb') as handle:
                reader(handle)
        start(read_fifo)
    preexec = bounded._limits(MAX_FILE, RUN_TIMEOUT + bounded.CPU_SLACK)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE if stream_reader
                            else subprocess.DEVNULL,
                            stderr=subprocess.PIPE, preexec_fn=preexec,
                            start_new_session=True)
    err_box: List[bytes] = []
    start(lambda: err_box.append(proc.stderr.read()))
    if stream_reader is not None:
        def read_stream():
            stream_reader(proc.stdout)
            proc.stdout.read()          # (the rest, if the reader stopped)
        start(read_stream)
    try:
        proc.wait(timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, 9)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
        raise CapError('%s: ref816 did not finish in %d s' % (run,
                                                              RUN_TIMEOUT))
    if reader is not None and fifo is not None and threads[0].is_alive():
        threads[0].join(5)
        if threads[0].is_alive():
            # the machine never opened the pipe (it failed first): an EOF
            try:
                os.close(os.open(str(fifo), os.O_WRONLY | os.O_NONBLOCK))
            except OSError:
                pass
    for t in threads:
        t.join(3600)
    err = err_box[0] if err_box else b''
    if errors and proc.returncode in (0, -13):
        raise errors[0]
    if proc.returncode:
        raise CapError('%s: ref816 failed (%d%s): %s' % (
            run, proc.returncode, bounded.explain(proc.returncode, MAX_FILE),
            err.decode(errors='replace')[-1500:]))
    if errors:
        raise errors[0]
    state = json.loads((work / 'state.json').read_text())
    from ref816 import marks
    problems = run_script.problems(state, marks.read(work / 'marks.txt'),
                                   syms, prog)
    return {'state': state, 'problems': problems, 'script': path}


# ---------------------------------------------------------------------------
# The survey
# ---------------------------------------------------------------------------

def survey_entries() -> List[str]:
    keys = [k for p in GL.PARTS for k in p['routines']]
    return [k for k in keys if not k.startswith('?')] + list(SURVEY_CORE)


def survey_targets(graph=None) -> List[str]:
    from native import gcallgraph as CG
    graph = graph or CG.load(write=False)
    out: List[str] = []
    for keys in GL.dispatch_entries(graph).values():
        for k in keys:
            if not k.startswith('?') and k not in out:
                out.append(k)
    return out


def _addressable(keys: Sequence[str], table: CL.Linkmap) -> List[str]:
    out = []
    for k in keys:
        try:
            table.address(k)
        except (KeyError, script.ScriptError):
            continue
        out.append(k)
    return out


MAX_LOGGED = 64                 # ref816's --call-log routines


class CallerMap:
    """A code address -> the game unit's head (file:label) that holds it
    (the link map's text labels, gcallgraph's heads)."""

    def __init__(self, graph=None):
        import bisect
        from bridge.linkmap import Symbols
        from native import gcallgraph as CG
        graph = graph or CG.load(write=False)
        self._bisect = bisect
        spans = []
        for f in Symbols().fragments:
            if f.kind != 'text':
                continue
            for lab in f.labels:
                key = graph.head_of('%s:%s' % (lab.unit, lab.name))
                if key:
                    spans.append((lab.address, lab.address + lab.size, key))
        spans.sort()
        self.starts = [a for a, _, _ in spans]
        self.spans = spans

    def head(self, address: int) -> Optional[str]:
        i = self._bisect.bisect_right(self.starts, address) - 1
        if i >= 0 and self.spans[i][0] <= address < self.spans[i][1]:
            return self.spans[i][2]
        return None


def passes(entries: Sequence[str], targets: Sequence[str],
           graph=None) -> List[Tuple[List[str], List[str]]]:
    """The survey's runs: each logs G_Ticker, some entries and the
    dispatch targets they can reach (gcallgraph.reach_targets), at most
    MAX_LOGGED routines, so that each call's reached targets are seen in
    the run that logs it."""
    from native import gcallgraph as CG
    graph = graph or CG.load(write=False)
    tset = set(targets)
    reach: Dict[str, Set[str]] = {}
    for k in entries:
        got: Set[str] = set()
        for ks in CG.reach_targets(graph, k).values():
            got |= set(ks) & tset
        reach[k] = got
    order = sorted(entries, key=lambda k: (-len(reach[k]), k))
    out: List[Tuple[List[str], Set[str]]] = []

    def size(es: Sequence[str], ts: Set[str]) -> int:
        return 1 + len(set(es) | ts)     # (the gametic's G_Ticker too)

    def apart(es: Sequence[str], k: str) -> bool:
        # an entry is never in the pass of an entry that reaches it, nor
        # of one it reaches: a dispatch target entered by JML and logged
        # with its return names its dispatcher's caller as its parent, so
        # the dispatcher's reached targets would miss it (wave 1 as
        # integrated: docs/game-parts/mobjstate.md R6, geom.md R10); logged
        # entry-only in the dispatcher's pass, it names the dispatcher
        return not (reach[k] & set(es)) and all(k not in reach[e]
                                                for e in es)

    for k in order:
        for es, ts in out:
            if size(list(es) + [k], ts | reach[k]) <= MAX_LOGGED and \
                    apart(es, k):
                es.append(k)
                ts |= reach[k]
                break
        else:
            if size([k], reach[k]) > MAX_LOGGED:
                raise CapError('%s reaches %d targets' % (k, len(reach[k])))
            out.append(([k], set(reach[k])))
    return [(es, sorted(ts - set(es))) for es, ts in out]


def survey_options(fifo: Path, entries: Sequence[str],
                   targets: Sequence[str],
                   dispatched: Sequence[str] = ()) -> List[str]:
    """The pass's call-log options: an entry that is also a dispatch
    target (dispatched) is logged with jumps=1 (a thinker is entered by
    JML [dp])."""
    routines = ['%s,name=%s,in=_g_gametic:4,entry=1' % (TICKER, TIC_NAME)]
    routines += ['%s,name=%s%s' % (k, k, ',jumps=1' if k in dispatched
                                   else '') for k in entries]
    routines += ['%s,name=%s,entry=1,jumps=1' % (k, k) for k in targets]
    return CL.options(routines, fifo) + ['--call-log-limit',
                                         str(CALL_LOG_LIMIT)]


class Survey:
    """The call logs of a run's passes read as they come (calllog.h's
    format: a call's line at its return, a callee before its caller; an
    entry-only line at the entry)."""

    def __init__(self, entries: Sequence[str], targets: Sequence[str],
                 callers: CallerMap):
        self.entries = list(entries)
        self.targets = list(targets)
        self.target_index = {k: i for i, k in enumerate(targets)}
        self.callers = callers
        self.tics: List[int] = []
        self.calls: Dict[str, List[int]] = {k: [] for k in entries}
        self.reached: Dict[str, Dict[int, List[int]]] = {
            k: {} for k in entries}
        self.parents: Dict[str, Dict[str, int]] = {k: {} for k in entries}
        self.target_calls: Dict[str, int] = {k: 0 for k in targets}
        self.per_tic: Dict[str, Dict[int, int]] = {k: {} for k in entries}
        self.lines = 0
        self.first_pass = True
        self.ends: List[Dict[str, Any]] = []

    def read(self, handle) -> None:
        first = json.loads(handle.readline())
        if first.get('format') != CL.FORMAT:
            raise CapError('not a call log')
        names = [r['name'] for r in first['routines']]
        only = [bool(r.get('entry_only')) for r in first['routines']]
        tic = -1
        pending: Dict[int, Set[int]] = {}
        target_parent: Dict[int, int] = {}

        def add(parent: int, got: Set[int]) -> None:
            while parent in target_parent:
                parent = target_parent[parent]
            if parent:
                pending.setdefault(parent, set()).update(got)

        for raw in handle:
            line = json.loads(raw)
            if line.get('end'):
                self.ends.append(line)
                break
            self.lines += 1
            name = names[line['routine']]
            if name == TIC_NAME:
                tic = int.from_bytes(bytes.fromhex(line['in']['mem'][0]),
                                     'little')
                if self.first_pass:
                    self.tics.append(tic)
                continue
            if only[line['routine']]:
                if name not in self.calls:
                    self.target_calls[name] += 1
                target_parent[line['call']] = line['parent']
                add(line['parent'], {self.target_index[name]})
                continue
            hit = line['hit']
            got = pending.pop(line['call'], set())
            if name in self.target_index:
                self.target_calls[name] += 1
                add(line['parent'], {self.target_index[name]})
            lst = self.calls[name]
            while len(lst) < hit - 1:
                lst.append(-1)
            lst.append(tic)
            if got:
                self.reached[name][hit] = sorted(got)
                add(line['parent'], got)
            self.per_tic[name][tic] = self.per_tic[name].get(tic, 0) + 1
            caller = self.callers.head(line['from'])
            if caller:
                d = self.parents[name]
                d[caller] = d.get(caller, 0) + 1
        self.first_pass = False

    def result(self, run: str) -> Dict[str, Any]:
        active = sorted(set(self.tics))
        out: Dict[str, Any] = {'format': SURVEY_FORMAT, 'run': run,
                               'tics': len(self.tics),
                               'first_tic': active[0] if active else None,
                               'last_tic': active[-1] if active else None,
                               'lines': self.lines,
                               'targets': self.targets,
                               'target_calls': self.target_calls,
                               'routines': {}}
        for k in self.entries:
            tics = self.calls[k]
            per = self.per_tic[k]
            counts = [per.get(t, 0) for t in active]
            out['routines'][k] = {
                'calls': len(tics), 'tic': tics,
                'reached': {str(h): v for h, v in self.reached[k].items()},
                'parents': self.parents[k],
                'per_tic': _stats(counts)}
        return out


def _stats(counts: Sequence[int]) -> Dict[str, float]:
    if not counts:
        return {'mean': 0, 'median': 0, 'p99': 0, 'most': 0}
    s = sorted(counts)
    return {'mean': round(sum(s) / len(s), 3),
            'median': statistics.median(s),
            'p99': s[min(len(s) - 1, int(len(s) * 0.99))], 'most': s[-1]}


def survey(run: str, out: Path = SURVEY, say=print) -> Dict[str, Any]:
    """The run's survey, in passes (passes()); the first pass's tics are
    the run's (every pass runs the same machine: the tics checked
    equal)."""
    table = CL.Linkmap()
    entries = _addressable(survey_entries(), table)
    targets = _addressable(survey_targets(), table)
    plan = passes(entries, targets)
    sv = Survey(entries, targets, CallerMap())
    start = time.time()
    for i, (es, ts) in enumerate(plan):
        check_disk()
        work = Path(tempfile.mkdtemp(prefix='tmp-m10-survey-',
                                     dir=str(BUILD)))
        try:
            fifo = work / 'calls.fifo'
            os.mkfifo(str(fifo))
            tics_before = list(sv.tics)
            r = machine(run, work, survey_options(fifo, es, ts, targets),
                        reader=sv.read, fifo=fifo)
            if r['problems']:
                raise CapError('%s: %s' % (run, '; '.join(r['problems'])))
            if i and sv.tics != tics_before:
                raise CapError('%s: pass %d saw other tics' % (run, i))
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        say('%s: pass %d of %d (%d entries, %d targets), %.0f s' % (
            run, i + 1, len(plan), len(es), len(ts), time.time() - start))
    res = sv.result(run)
    res['seconds'] = round(time.time() - start, 1)
    res['passes'] = len(plan)
    out.mkdir(parents=True, exist_ok=True)
    (out / (run + '.json.z')).write_bytes(zlib.compress(json.dumps(
        res, separators=(',', ':')).encode(), 6))
    write_index(out)
    return res


def write_index(out: Path = SURVEY) -> None:
    index = {'format': 'game-survey-index 1', 'runs': {}}
    for p in sorted(out.glob('*.json.z')):
        s = load_survey(p)
        index['runs'][s['run']] = {
            'file': p.name, 'tics': s['tics'],
            'calls': sum(r['calls'] for r in s['routines'].values()),
            'routines_called': sum(1 for r in s['routines'].values()
                                   if r['calls'])}
    (out.parent / 'survey.json').write_text(json.dumps(index, indent=1) +
                                            '\n')


def load_survey(path: Path) -> Dict[str, Any]:
    d = json.loads(zlib.decompress(Path(path).read_bytes()))
    if d.get('format') != SURVEY_FORMAT:
        raise CapError('%s is not a survey' % path)
    return d


def survey_of(run: str) -> Optional[Dict[str, Any]]:
    p = SURVEY / (run + '.json.z')
    return load_survey(p) if p.exists() else None


# ---------------------------------------------------------------------------
# The captures and the cases
# ---------------------------------------------------------------------------

class Tracked(bmem.Memory):
    """A memory that records the pages read."""

    def __init__(self, banks: Dict[int, bytearray]):
        super().__init__()
        self.banks = banks
        self.pages: Set[int] = set()

    def _mark(self, address: int, length: int) -> None:
        for p in range(address >> 8, ((address + max(length, 1) - 1) >> 8)
                       + 1):
            self.pages.add(p)

    def read(self, address: int, length: int) -> bytes:
        self._mark(address, length)
        return super().read(address, length)

    def u8(self, address: int) -> int:
        self._mark(address, 1)
        return super().u8(address)

    def uint(self, address: int, size: int) -> int:
        self._mark(address, size)
        return int.from_bytes(super().read(address, size), 'little')


def reader_pages(mem: bmem.Memory, tic: bool = True) -> Set[int]:
    t = Tracked(mem.banks)
    upstream.Reader(t, tic=tic).read()
    return t.pages


def image_records(path: Path) -> List[Tuple[int, bytes]]:
    import struct
    data = path.read_bytes()
    if data[:8] != b'REF816I1':
        raise CapError('%s: not a ref816 image' % path)
    out = []
    at = 32
    while at < len(data):
        address, length = struct.unpack_from('<II', data, at)
        at += 8
        out.append((address, data[at:at + length]))
        at += length
    return out


def _pages_of(records: Sequence[Tuple[int, bytes]]) -> Set[int]:
    out: Set[int] = set()
    for a, d in records:
        for p in range(a >> 8, ((a + max(len(d), 1) - 1) >> 8) + 1):
            out.add(p)
    return out


def _ranges(records: Sequence[Tuple[int, bytes]]) -> List[List[int]]:
    return [[a, len(d)] for a, d in records]


def base_path(run: str) -> Path:
    return CASES / run / 'base.ram.z'


def load_base(run: str) -> bmem.Memory:
    data = zlib.decompress(base_path(run).read_bytes())
    m = bmem.Memory()
    for i, bank in enumerate(RAM_BANKS):
        m.banks[bank] = bytearray(data[i * 0x10000:(i + 1) * 0x10000])
    return m


def _ram_bytes(m: bmem.Memory) -> bytes:
    return b''.join(bytes(m.banks.get(b, bytes(0x10000))) for b in RAM_BANKS)


def distil(raw: Path, run: str, key: str, tic: int, base: bmem.Memory
           ) -> bytes:
    """A raw capture (hit-N/) as a case's bytes."""
    call = json.loads((raw / 'call.json').read_text())
    entry = bmem.Memory.from_image(raw / 'entry.img')
    writes = image_records(raw / 'exit.img')
    reads = image_records(raw / 'reads.img')
    after = entry.copy()
    for a, d in writes:
        after.write(a, d)
    pages = reader_pages(entry) | reader_pages(after) | _pages_of(reads) | \
        _pages_of(writes)
    for reg in ('d', 's'):                  # the direct page, the stack
        v = call['call']['start'][reg]
        pages |= {v >> 8, (v + 0xFF) >> 8 & 0xFF}
    pages = sorted(pages)
    payload = bytearray()
    for p in pages:
        a = p << 8
        mine = entry.read(a, PAGE)
        theirs = base.read(a, PAGE)
        payload += bytes(x ^ y for x, y in zip(mine, theirs))
    wbytes = bytearray()
    for a, d in writes:
        wbytes += d
    header = {'format': CASE_FORMAT, 'run': run, 'routine': key,
              'hit': call['hit'], 'tic': tic, 'note': call.get('note'),
              'cycles': call['cycles'], 'call': call['call'],
              'image_header': entry.header.hex(),
              'pages': _compress_pages(pages), 'writes': _ranges(writes),
              'reads': _ranges(reads)}
    head = json.dumps(header, separators=(',', ':')).encode() + b'\n'
    return zlib.compress(head + bytes(payload) + bytes(wbytes), 6)


def _compress_pages(pages: Sequence[int]) -> List[List[int]]:
    out: List[List[int]] = []
    for p in pages:
        if out and out[-1][0] + out[-1][1] == p:
            out[-1][1] += 1
        else:
            out.append([p, 1])
    return out


def _expand_pages(runs: Sequence[Sequence[int]]) -> List[int]:
    return [p for a, n in runs for p in range(a, a + n)]


class Case:
    def __init__(self, header: Dict[str, Any], entry: bmem.Memory,
                 after: bmem.Memory, path: Optional[Path] = None):
        self.header = header
        self.entry = entry
        self.after = after
        self.path = path

    @property
    def key(self) -> str:
        return self.header['routine']

    @property
    def regs_in(self) -> Dict[str, int]:
        return self.header['call']['start']

    @property
    def regs_out(self) -> Dict[str, int]:
        return self.header['call']['end']


_BASES: Dict[str, bmem.Memory] = {}


def load_case(path: Path) -> Case:
    raw = zlib.decompress(Path(path).read_bytes())
    nl = raw.index(b'\n')
    header = json.loads(raw[:nl])
    if header.get('format') != CASE_FORMAT:
        raise CapError('%s is not a case' % path)
    run = header['run']
    if run not in _BASES:
        _BASES[run] = load_base(run)
    entry = _BASES[run].copy()
    entry.header = bytes.fromhex(header['image_header'])
    at = nl + 1
    for p in _expand_pages(header['pages']):
        a = p << 8
        theirs = entry.read(a, PAGE)
        entry.write(a, bytes(x ^ y for x, y in zip(raw[at:at + PAGE],
                                                   theirs)))
        at += PAGE
    after = entry.copy()
    for a, n in header['writes']:
        after.write(a, raw[at:at + n])
        at += n
    return Case(header, entry, after, Path(path))


def call_case(case: 'Case', pokes: Sequence[Tuple[int, bytes]],
              note: str = 'synthetic') -> 'Case':
    """A synthetic case: the case's entry memory with pokes (address,
    bytes), the call run alone on ref816 (--call on the memory image,
    --call-writes): its return state from upstream's own code."""
    entry = case.entry.copy()
    entry.header = case.entry.header
    for a, d in pokes:
        entry.write(a, d)
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-call-', dir=str(BUILD)))
    try:
        (work / 'entry.img').write_bytes(entry.image_bytes())
        address = CL.Linkmap().address(case.key)
        cmd = [str(title.MACHINE), str(work / 'entry.img'), '--call',
               '%06X' % address, '--call-writes', str(work / 'writes.img'),
               '--state', str(work / 'state.json')]
        r = bounded.run(cmd, timeout=120, max_bytes=MAX_FILE,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode:
            raise CapError('ref816 --call failed: %s' % r.stdout[-800:])
        state = json.loads((work / 'state.json').read_text())
        if not state['call']['returned']:
            raise CapError('the call did not return')
        writes = image_records(work / 'writes.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    after = entry.copy()
    for a, d in writes:
        after.write(a, d)
    header = dict(case.header, note=note, call=state['call'],
                  writes=_ranges(writes))
    return Case(header, entry, after, None)


def case_dir(run: str, key: str) -> Path:
    return CASES / run / GL.native_names().get(key, key.replace(':', '_'))


def capture(run: str, key: str, hits: Sequence[int],
            tics: Optional[Sequence[int]] = None, batch: int = BATCH,
            say=print) -> List[Path]:
    """The cases of `hits` of routine `key` in run `run` (captured in
    batches; the ones already made are kept)."""
    table = CL.Linkmap()
    entry = table.address(key)
    out = case_dir(run, key)
    out.mkdir(parents=True, exist_ok=True)
    todo = [h for h in hits if not (out / ('h%08d.case.z' % h)).exists()]
    made: List[Path] = []
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        check_disk()
        work = Path(tempfile.mkdtemp(prefix='tmp-m10-cap-', dir=str(BUILD)))
        try:
            raw = work / 'raw'
            raw.mkdir()
            opts = ['--capture', str(raw), '--capture-entry',
                    '%06X' % entry]
            for h in part:
                opts += ['--capture-hit', str(h)]
            r = machine(run, work, opts)
            if r['problems']:
                raise CapError('%s: %s' % (run, '; '.join(r['problems'])))
            if not base_path(run).exists():
                first = bmem.Memory.from_image(
                    raw / ('hit-%08d' % part[0]) / 'entry.img')
                base_path(run).parent.mkdir(parents=True, exist_ok=True)
                base_path(run).write_bytes(zlib.compress(_ram_bytes(first),
                                                         6))
            base = _BASES.get(run) or load_base(run)
            _BASES[run] = base
            for h in part:
                d = raw / ('hit-%08d' % h)
                tic = tics[h - 1] if tics is not None and h - 1 < len(tics) \
                    else -1
                p = out / ('h%08d.case.z' % h)
                p.write_bytes(distil(d, run, key, tic, base))
                shutil.rmtree(str(d))
                made.append(p)
            say('%s %s: %d cases (%d of %d)' % (run, key, len(part),
                                                 i + len(part), len(todo)))
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    return made


def parse_hits(text: str) -> List[int]:
    out: List[int] = []
    for part in text.split(','):
        if '-' in part:
            a, b = part.split('-')
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--survey', action='store_true')
    parser.add_argument('--runs', default=','.join(RUNS))
    parser.add_argument('--capture')
    parser.add_argument('--run')
    parser.add_argument('--hits')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--sample', type=int)
    args = parser.parse_args(argv)
    if args.survey:
        for run in [r for r in args.runs.split(',') if r]:
            s = survey(run)
            called = sum(1 for r in s['routines'].values() if r['calls'])
            print('%s: %d tics, %d log lines, %d of %d entries called, '
                  '%.0f s' % (run, s['tics'], s['lines'], called,
                              len(s['routines']), s['seconds']))
        return 0
    if args.capture:
        if not args.run:
            parser.error('--capture needs --run')
        sv = survey_of(args.run)
        tics = sv['routines'][args.capture]['tic'] if sv and \
            args.capture in sv['routines'] else None
        if args.hits:
            hits = parse_hits(args.hits)
        elif tics is None:
            parser.error('no survey of %s: give --hits' % args.run)
        elif args.all:
            hits = list(range(1, len(tics) + 1))
        else:
            n = args.sample or 20
            step = max(1, len(tics) // n)
            hits = list(range(1, len(tics) + 1, step))[:n]
        made = capture(args.run, args.capture, hits, tics)
        print('%d cases made in %s' % (len(made),
                                        case_dir(args.run, args.capture)))
        return 0
    parser.error('nothing to do')
    return 2


if __name__ == '__main__':
    sys.exit(main())
