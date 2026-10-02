#!/usr/bin/env python3
"""Part spawn's checkpoint (milestone 10, wave 2; docs/GAME.md 2.4, 3.5;
docs/game-parts/spawn.md): its image, the paths of its entries in the
reference's runs, its captures, its routine-mode runs on both fills and
both profiles, its synthetic cases, shr3's random check, its planted bugs,
and build/native/game/spawn/report.json.

Usage:  python3 tools/native/gparts/spawn.py --build
        python3 tools/native/gparts/spawn.py --paths [--jobs 2]
        python3 tools/native/gparts/spawn.py --capture [--jobs 2]
        python3 tools/native/gparts/spawn.py --check [--jobs 2] [--sample K]
                                             [--entries KEY,...]
        python3 tools/native/gparts/spawn.py --synthetic
        python3 tools/native/gparts/spawn.py --random [--count N]
        python3 tools/native/gparts/spawn.py --plants
        python3 tools/native/gparts/spawn.py --report

The image (build()): `make -f game.mk part P=spawn` from a scratch copy of
the build files (game.mk, math.inc, integrated.txt, every part's fragment)
and the planted bugs' files, every other source from the tree (game.mk's
vpath), into build/native/game/spawn/ (or a temporary directory).

The paths (--paths): each run of the survey (demo3, demo1, demo2, newgame,
tour) on ref816 once more, with --mark at the entries of P_ZMovement,
missileHit, isPlayer (p_mobj65.s) and P_IsAttackRangeMeleeRange
(p_attack65.s) and at the instructions that start each of their paths
(PATH_POINTS: found in upstream's source by text and placed by our own
assembler's spans, tools/v816, never by hand): each call's path is the
points its marks reach between its entry and its end (P_ZMovement's
zdone). The counts of entries must equal the survey's calls. Kept in
build/native/game/spawn/paths/RUN.json.z.

The selection (GAME.md 2.4 minimums, row spawn): every call of P_SpawnPuff,
P_SpawnBlood, missileHit and shr3 (each under 300 calls, or "every puff
and blood"); P_ZMovement: 300 of DEMO1's 5,864 spread evenly, then the
first call of every path no chosen call takes (any run); isPlayer and
P_IsAttackRangeMeleeRange: 300 of all runs' calls spread evenly, the same
way. The captures (--capture): tools/native/gamecap.py's, into the part's
own build/native/game/spawn/cases/.

A run (run_one()): gameroutine.py's routine mode (the case's entry state
through the game manifest into a machine poisoned with $A5 or $5A, the
entry's inputs of args.json, the call, the state read back and compared
with the reference's return state, gcanon's routine mode, exclusions
R1-R6, R7's named stale links), on a2vm under f121 and fastpath, with the
write log: no CPU write outside the allowed places, every declared output
equal, the native-only globals consistent (part mobjstate's checks). Each
case runs from both fills under both profiles (4 runs).

The synthetic cases (SYNTHETIC): captured entry states with fields poked
and the reference's own call (ref816 --call): a mobj rising into the
ceiling, one stuck through it, a missile into the ceiling and one into the
floor, the player's hard landing (alive and dead), the player's squat, a
mobj falling from rest; a punch's puff (attackrange = MELEERANGE); blood at
damage 8, 9, 12 and 13; P_IsAttackRangeMeleeRange at MELEERANGE and at a
range whose low word only matches.

shr3's random check (--random): 100,000 inputs (0, +-1, the extremes, the
shift's edges, then random 32-bit values) through upstream's shr3 (the
milestone 6 tool mathref, batch mode, on a captured shr3 call's machine)
and the native shr3 (sptest.s sp_bulk), compared.
"""

import argparse
import hashlib
import json
import os
import random
import shutil
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
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))

from bridge.port import PortReader, PortWriter, PortError  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL, render_check as RC  # noqa: E402
from ref816 import bounded, marks as MK  # noqa: E402
import mobjstate as MS  # noqa: E402  (wave 1's harness: its generic parts)

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'spawn'
WAVE = 2
OUT = GL.GAME / PART
MYCASES = OUT / 'cases'
PATHS = OUT / 'paths'
REPORT = OUT / 'report.json'
FILLS = (0xA5, 0x5A)
PROFILES = ('f121', 'fastpath')
NAME = 'ptest'
UPSTREAM_BYTES = 842
BUDGET = 1100                   # GAME.md 2.4: upstream 842 x 1.3
MODULES = ('spawn', 'zmove')
TEST_MODULES = ('sptest',)
MINIMUM = 300
JOBS = 2

PUFF = 'p_spawn65.s:P_SpawnPuff'
BLOOD = 'p_spawn65.s:P_SpawnBlood'
MELEE = 'p_attack65.s:P_IsAttackRangeMeleeRange'
ZMOVE = 'p_mobj65.s:P_ZMovement'
MHIT = 'p_mobj65.s:missileHit'
SHR3 = 'p_mobj65.s:shr3'
ISPL = 'p_mobj65.s:isPlayer'
ENTRIES = (PUFF, BLOOD, MELEE, ZMOVE, MHIT, SHR3, ISPL)


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


# ---------------------------------------------------------------------------
# What the checkpoint needs (the test file's skips name these commands)
# ---------------------------------------------------------------------------

def missing() -> Optional[str]:
    """None when the shared outputs, the survey, the level bases, ref816
    and a2vm are there; else what is missing and the command that makes
    it."""
    shared = GL.SHARED
    if not ((shared / 'gen' / 'ggame.inc').exists() and
            (shared / 'native-game-1.json').exists()):
        return ('the shared outputs (make -s -C src/native -f game.mk shared '
                'skel ROOT=$PWD)')
    if GC.survey_of('demo1') is None:
        return 'the survey (python3 tools/native/gamecap.py --survey)'
    if not GR.have_bases():
        return ('milestone 9\'s level bases (python3 tools/native/'
                'level_check.py --setup)')
    from ref816 import title
    if not (Path(G.A2VM).exists() and Path(title.MACHINE).exists()):
        return 'ref816 and a2vm (make -C tools/ref816; make -C tools/a2vm)'
    return None


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------

def build(game: Path = GL.GAME, bugs: Sequence[Tuple[str, str, str]] = ()
          ) -> Path:
    """The part's image (GAME/spawn/ptest.*) from a scratch copy of the
    build files and of the bugs' files (relative to src/native) with each
    bug (file, old, new) applied once; the copy is deleted."""
    tmp = Path(tempfile.mkdtemp(prefix='tmp-spawn-build-', dir=str(BUILD)))
    try:
        src = tmp / 'src'
        copy_files = set(G.PLANT_COPY) | {'game/%s/part.mk' % PART}
        copy_files |= {name for name, _, _ in bugs}
        for f in copy_files:
            (src / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(SRC / f), str(src / f))
        for name, old, new in bugs:
            text = (src / name).read_text()
            if text.count(old) != 1:
                raise PartError('%s: the edit no longer applies: %r' % (
                    name, old[:60]))
            (src / name).write_text(text.replace(old, new))
        objs = game / PART / 'game' / PART
        if objs.exists():               # (sp.inc is no prerequisite)
            for p in objs.glob('*.o'):
                p.unlink()
        # (SP_TEST=1: sptest.s, the random check's sp_bulk, is linked in
        # the part's own image only: wave 6 as integrated)
        cmd = ['make', '-s', '-C', str(src), '-f', 'game.mk', 'part',
               'P=%s' % PART, 'ROOT=%s' % ROOT, 'GAME=%s' % game,
               'SP_TEST=1']
        r = bounded.run(cmd, timeout=600, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, universal_newlines=True)
        if r.returncode:
            raise PartError('the build failed:\n' + r.stdout[-3000:])
        if 'arning' in r.stdout:
            raise PartError('the build warns:\n' + r.stdout[-3000:])
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    return game / PART


def load(obj: Path = OUT) -> RC.Build:
    return G.load_build(obj, NAME)


def sizes(b: RC.Build) -> Dict[str, Any]:
    ms = MS.module_ranges(b)
    by = {m: sum(hi + 1 - lo for _, lo, hi in ms.get(m, ()))
          for m in MODULES + TEST_MODULES}
    part = sum(by[m] for m in MODULES)
    return {'modules': by, 'part_bytes': part, 'budget': BUDGET,
            'upstream_bytes': UPSTREAM_BYTES,
            'over_budget_pct': round(100.0 * (part - BUDGET) / BUDGET, 1),
            'segments': sorted({seg for m in MODULES for seg, _, _ in
                                ms.get(m, ())})}


def inc_value(b: RC.Build, name: str) -> int:
    """A symbol of the image's generated ggame.inc."""
    for line in (b.obj / 'gen' / 'ggame.inc').read_text().splitlines():
        f = line.split()
        if len(f) >= 3 and f[0] == name and f[1] == '=':
            return int(f[2].lstrip('$'), 16)
    raise PartError('%s is not in ggame.inc' % name)


# the part's scratch block's names (game/spawn/sp.inc), offsets in SB_SPAWN
SB_NAMES = {'SP_TH': 12, 'SP_DMG': 14, 'ZM_MO': 16, 'ZM_PL': 18,
            'AT_RANGE': 28}


def place(b: RC.Build, name: str) -> int:
    """A place of sp.inc: AT_RANGE is GM_ATRANGE once the integrator has
    made it (request 1), else the stand-in in the scratch block."""
    if name == 'AT_RANGE' and 'GM_ATRANGE' in GL.TGW:
        return GL.TGW['GM_ATRANGE']
    return inc_value(b, 'SB_SPAWN') + SB_NAMES[name]


# ---------------------------------------------------------------------------
# The paths (--paths): ref816 --mark at the entries and the path points
# ---------------------------------------------------------------------------

# file:label -> (the definition's line, the end's line, [(path, text of the
# line that starts it)]); the points' lines are the first after the
# definition that hold the text (TICSTEP 1: P_ZMovement's ENTER line)
PATH_POINTS = {
    ZMOVE: ('P_ZMovement:  ENTER', 'zdone:', [
        ('squat', 'viewheight -= floorz - z'),
        ('floor', '10$:'),
        ('fall', 'the player lands hard'),
        ('hard', 'deltaviewheight = momz >> 3'),
        ('oof', '##CONST_SFX_OOF'),
        ('stop', '14$:'),
        ('air', '30$:'),
        ('gravity', 'if (!momz) momz = -GRAVITY'),
        ('rest', '##(0x10000 - GRAVITY_HI)'),
        ('ceiling', 'if (momz > 0) momz = 0'),
        ('rise', '41$:'),
        ('end', 'zdone:')]),
    MHIT: ('missileHit:', 'shr3:', [
        ('missile', 'ldy     ##OFS_MO_FLAGS'),
        ('explode', 'jsr     .kbank explode')]),
    ISPL: ('isPlayer:', 'P_XYMovement', [
        ('lo', 'lda     dp:.tiny (AP+2)'),
        ('player', 'lda     ##1')]),
    MELEE: ('P_IsAttackRangeMeleeRange:', 'P_AimLineAttack', [
        ('lo', 'lda     .near (AT_RANGE+2)'),
        ('melee', 'lda     ##1')]),
}
PATHS_FORMAT = 'spawn-paths 1'


def path_pcs() -> Dict[str, Dict[str, int]]:
    """file:label -> {'entry': its address, path: the address of the
    instruction that starts it}: the source line found by its text, its
    offset from our assembler's spans (tools/v816: the unit assembled as
    the release is built), the routine's address from the link map."""
    from v816 import frontend, objfile
    table = GC.CL.Linkmap()
    by_unit: Dict[str, List[str]] = {}
    for key in PATH_POINTS:
        by_unit.setdefault(key.split(':')[0], []).append(key)
    out: Dict[str, Dict[str, int]] = {}
    for src in frontend.sources():
        unit = src.path.name
        if unit not in by_unit:
            continue
        lines = src.path.read_text().splitlines()
        o = objfile.assemble(frontend.process(src).unit, unit)
        for key in by_unit[unit]:
            label = key.split(':')[1]
            start, end, points = PATH_POINTS[key]
            first = next(i for i, t in enumerate(lines, 1)
                         if t.startswith(start))
            frag = next(f for f in o.fragments
                        if label in dict(f.labels))
            base = dict(frag.labels)[label]
            entry = table.address(key)
            d = {'entry': entry}
            for name, text in points:
                n = next(i for i, t in enumerate(lines, 1)
                         if i > first and text in t)
                spans = [s for s in frag.spans if s.where.line == n and
                         s.where.file.endswith('/' + unit) and
                         not s.where.expansions]
                if not spans:
                    raise PartError('%s: no code at line %d (%s)' % (
                        key, n, name))
                d[name] = entry + spans[0].offset - base
            out[key] = d
    if set(out) != set(PATH_POINTS):
        raise PartError('path points not found: %s' % (
            set(PATH_POINTS) - set(out)))
    return out


class CallSpans:
    """The calls of the call log, read as they come: per routine, each
    call's hit, its entry's and its return's cycles (a call still open at
    the run's end: its return None)."""

    def __init__(self):
        self.calls: Dict[str, List[Tuple[int, int, Optional[int]]]] = {}

    def read(self, handle) -> None:
        first = json.loads(handle.readline())
        if first.get('format') != GC.CL.FORMAT:
            raise PartError('not a call log')
        names = [r['name'] for r in first['routines']]
        for raw in handle:
            line = json.loads(raw)
            if line.get('end'):
                break
            out = line.get('out') or {}
            self.calls.setdefault(names[line['routine']], []).append(
                (line['hit'], line['cycles'],
                 out.get('cycles') if line.get('returned') else None))


def classify(spans: Dict[str, List[Tuple[int, int, Optional[int]]]],
             entries: Sequence[MK.Entry], pcs: Dict[str, Dict[str, int]]
             ) -> Dict[str, List[str]]:
    """file:label -> each call's path, in hit order: the names of its own
    points whose marks fall between its entry and its return (cycles,
    both ends included), a point marked twice in a row once (an interrupt
    taken at a marked instruction returns to it: a second arrival);
    P_ZMovement's also holds the points of the isPlayer and missileHit
    calls inside it (pl., mh.) and 'mh' for each missileHit call."""
    where: Dict[int, Tuple[str, str]] = {}
    for key, d in pcs.items():
        for name, pc in d.items():
            if name != 'entry':
                where[pc] = (key, name)
    points: Dict[str, List[Tuple[int, str]]] = {k: [] for k in pcs}
    for e in entries:
        if e.kind == 'mark' and int(e.what, 16) in where:
            key, name = where[int(e.what, 16)]
            points[key].append((e.cycles, name))
    import bisect
    out: Dict[str, List[str]] = {}
    for key in pcs:
        calls = sorted(spans.get(key, []))
        pts = points[key]
        cyc = [c for c, _ in pts]
        res = []
        for i, (hit, lo, hi) in enumerate(calls):
            if hit != i + 1:
                raise PartError('%s: call %d logged as hit %d' % (
                    key, i + 1, hit))
            hi = hi if hi is not None else 1 << 62
            names: List[str] = []
            a = bisect.bisect_left(cyc, lo)
            b_ = bisect.bisect_right(cyc, hi)
            for _, n in pts[a:b_]:
                if not names or names[-1] != n:
                    names.append(n)
            res.append((lo, hi, names))
        out[key] = res
    # P_ZMovement's calls with the isPlayer and missileHit inside them
    zm = out[ZMOVE]
    zlo = [lo for lo, _, _ in zm]
    for key, tag in ((ISPL, 'pl'), (MHIT, 'mh')):
        for lo, hi, names in out[key]:
            i = bisect.bisect_right(zlo, lo) - 1
            if i >= 0 and zm[i][0] <= lo <= zm[i][1]:
                if key == MHIT:
                    zm[i][2].append('mh')
                zm[i][2].extend('%s.%s' % (tag, n) for n in names)
    return {k: [','.join(n) or '-' for _, _, n in v] for k, v in out.items()}


def _paths_job(run: str) -> Dict[str, Any]:
    pcs = path_pcs()
    GC.check_disk()
    work = Path(tempfile.mkdtemp(prefix='tmp-spawn-paths-', dir=str(BUILD)))
    try:
        fifo = work / 'calls.fifo'
        os.mkfifo(str(fifo))
        log = CallSpans()
        opts = GC.CL.options(['%s,name=%s' % (k, k) for k in pcs], fifo) + \
            ['--call-log-limit', str(GC.CALL_LOG_LIMIT)]
        for d in pcs.values():
            for name, pc in d.items():
                if name != 'entry':
                    opts += ['--mark', '%06X' % pc]
        r = GC.machine(run, work, opts, reader=log.read, fifo=fifo)
        if r['problems']:
            raise PartError('%s: %s' % (run, '; '.join(r['problems'])))
        res = classify(log.calls, MK.read(work / 'marks.txt'), pcs)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    sv = GC.survey_of(run)
    for key, calls in res.items():
        n = sv['routines'].get(key, {}).get('calls', 0)
        if len(calls) != n:
            raise PartError('%s %s: %d calls logged, the survey has %d' % (
                run, key, len(calls), n))
    d = {'format': PATHS_FORMAT, 'run': run, 'pcs': pcs, 'routines': res}
    PATHS.mkdir(parents=True, exist_ok=True)
    (PATHS / (run + '.json.z')).write_bytes(zlib.compress(json.dumps(
        d, separators=(',', ':')).encode(), 6))
    return {'run': run, 'calls': {k: len(v) for k, v in res.items()}}


def paths(jobs: int = JOBS, runs: Sequence[str] = GC.RUNS) -> None:
    todo = [r for r in runs if load_paths(r) is None]
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_paths_job, todo):
            say('paths %s: %s' % (got['run'], got['calls']))


def load_paths(run: str) -> Optional[Dict[str, Any]]:
    p = PATHS / (run + '.json.z')
    if not p.exists():
        return None
    d = json.loads(zlib.decompress(p.read_bytes()))
    if d.get('format') != PATHS_FORMAT:
        raise PartError('%s is not a path log' % p)
    return d


def path_class(run: str, key: str, hit: int) -> str:
    d = paths_of(run)
    if d is None or key not in d['routines']:
        return '?'
    calls = d['routines'][key]
    return calls[hit - 1] if 0 < hit <= len(calls) else '?'


# ---------------------------------------------------------------------------
# The selection and the captures
# ---------------------------------------------------------------------------

_SV: Dict[str, Any] = {}


def survey(run: str) -> Optional[Dict[str, Any]]:
    """The survey of run (read once a process)."""
    if run not in _SV:
        _SV[run] = GC.survey_of(run)
    return _SV[run]


_PL: Dict[str, Any] = {}


def paths_of(run: str) -> Optional[Dict[str, Any]]:
    if run not in _PL:
        _PL[run] = load_paths(run)
    return _PL[run]


def calls_of(key: str, runs: Sequence[str] = GC.RUNS
             ) -> List[Tuple[str, int, str]]:
    """(run, hit, path) of every call of key in the runs."""
    out = []
    for run in runs:
        sv = survey(run)
        n = sv['routines'].get(key, {}).get('calls', 0) if sv else 0
        d = paths_of(run)
        cls = d['routines'].get(key) if d else None
        for h in range(1, n + 1):
            out.append((run, h, cls[h - 1] if cls else '?'))
    return out


def spread(items: Sequence[Any], n: int) -> List[Any]:
    if len(items) <= n:
        return list(items)
    return [items[(i * len(items)) // n] for i in range(n)]


def selection(key: str) -> List[Tuple[str, int, str]]:
    """The captured calls of key (GAME.md 2.4's minimums, row spawn)."""
    calls = calls_of(key)
    if key in (PUFF, BLOOD, MHIT, SHR3) or len(calls) < MINIMUM:
        return calls
    base = [c for c in calls if c[0] == 'demo1'] if key == ZMOVE else calls
    chosen = spread(base, MINIMUM)
    have = {c[2] for c in chosen}
    for c in calls:
        if c[2] not in have:
            chosen.append(c)
            have.add(c[2])
    return sorted(set(chosen), key=lambda c: (GC.RUNS.index(c[0]), c[1]))


def _capture_job(job) -> str:
    run, key, hits = job
    MS.use_cases(MYCASES)
    tics = GC.survey_of(run)['routines'][key]['tic']
    made = GC.capture(run, key, hits, tics, say=lambda *a: None)
    return '%s %s: %d made of %d' % (run, key, len(made), len(hits))


def capture(jobs: int = JOBS) -> None:
    """Every case of the selection the part's directory lacks: a run's
    first batch alone (it writes the run's base), the rest jobs at a
    time."""
    MS.use_cases(MYCASES)
    todo = []
    for key in ENTRIES:
        sel = selection(key)
        for run in GC.RUNS:
            hits = [h for r, h, _ in sel if r == run]
            d = GC.case_dir(run, key)
            miss = [h for h in hits
                    if not (d / ('h%08d.case.z' % h)).exists()]
            for i in range(0, len(miss), GC.BATCH):
                todo.append((run, key, miss[i:i + GC.BATCH]))
    first = []
    for run in sorted({t[0] for t in todo}):
        if not GC.base_path(run).exists():
            j = next(t for t in todo if t[0] == run)
            first.append(j)
            todo.remove(j)
    if first:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for got in pool.map(_capture_job, first):
                say(got)
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_capture_job, todo):
            say(got)


def case_paths(key: str) -> List[Tuple[str, Path, str]]:
    """(run, case file, path) of the selection's captured cases."""
    MS.use_cases(MYCASES)
    out = []
    for run, hit, cls in selection(key):
        p = GC.case_dir(run, key) / ('h%08d.case.z' % hit)
        if p.exists():
            out.append((run, p, cls))
    return out


def eligible(run: str, key: str, hit: int) -> List[str]:
    """The dispatch targets the call reached (the survey) that are not
    built in the part's image: empty when the call is eligible."""
    sv = survey(run)
    built = set(GL.built_set(extra=[PART]))
    r = sv['routines'].get(key, {})
    reached = [sv['targets'][i] for i in r.get('reached', {}).get(
        str(hit), [])]
    return [t for t in reached
            if (GL.owner_of(t) or 'core') not in built | {'core'}]


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def source(up: GR.Upstream, text: str, when: str = 'in') -> bytes:
    """An upstream source of args.json, with the part's own: cx (C:X, C
    the high word: shr3's operand and result) and c (the carry)."""
    regs = up.case.regs_in if when == 'in' else up.case.regs_out
    if text == 'cx':
        return ((regs['a'] & 0xFFFF) << 16 | (regs['x'] & 0xFFFF)
                ).to_bytes(4, 'little')
    if text == 'c':
        return bytes([regs['p'] & 1])
    return up.source(text, when)


class Prep:
    """A case's reference side and its native inputs, once for its fills
    and profiles (mobjstate.Prepared's, with the part's destinations sb:
    and its sources cx and c)."""

    def __init__(self, case: GC.Case, spec: Dict[str, Any], b: RC.Build):
        self.case = case
        self.spec = spec
        self.up = up = GR.Upstream(case)
        self.problems: List[str] = []
        self.accepted: List[str] = []
        for r in (up.r_in, up.r_out):
            acc, others = MS.stale_link_problems(r)
            self.accepted += acc
            self.problems += others
        if self.problems:
            return
        self.mf, self.header, self.banks = GR.manifest(up.gamemap)
        self.skip = gcanon.skips('routine', up.s_in)
        pm = G.tracked_memory()
        PortWriter(self.mf).write(gcanon.strip(up.s_in, self.skip), pm)
        self.recs = G.port_records(pm) + GR.derived(pm, self.header)
        regs = [0, 0, 0, 0x34]
        self.zp: List[Tuple[int, bytes]] = []
        for item in spec.get('in', []):
            data = source(up, item['from'])
            if item.get('as'):
                data = MS._convert(up, self.mf, data, item['as'])
            to = item['to']
            n = item.get('bytes', len(data))
            if to in ('a', 'x', 'y'):
                regs['axy'.index(to)] = data[0]
            elif to == 'ax':
                regs[0], regs[1] = data[0], data[1]
            elif to.startswith('zp:'):
                self.zp.append((GR.zp_address(to[3:]),
                                data[:n].ljust(n, b'\0')))
            elif to.startswith('sb:'):
                self.zp.append((place(b, to[3:]), data[:n].ljust(n, b'\0')))
            elif to.startswith('main:'):
                self.zp.append((LL.G[to[5:]], data[:n].ljust(n, b'\0')))
            else:
                raise GR.HarnessError('an input destination %r' % to)
        self.regs = regs


def allowed_main(b: RC.Build) -> List[Tuple[int, int]]:
    """mobjstate's places (the object API's, the globals, mobjstate's
    scratch block: explode, P_SetMobjState and P_RemoveMobj are its) and
    the part's scratch block."""
    sb = inc_value(b, 'SB_SPAWN')
    return MS.allowed_main(b) + [(sb, sb + inc_value(b, 'SB_SPAWN_SIZE'))]


def stray(writes, b: RC.Build, header: Dict[str, Any]) -> List[str]:
    """CPU writes outside the allowed places (mobjstate.stray's rule with
    the part's scratch block)."""
    allowed = allowed_main(b)
    desc = b.segments['DESC']
    drv = b.segments['DRIVER']
    loader = b.segments['RLOAD']
    far = b.segments['RFAR']
    aux = MS.allowed_aux(header)
    out = []
    for w in writes:
        if w.storage == 'main':
            if w.offset < 0x0200 or any(lo <= w.offset < hi
                                         for lo, hi in allowed):
                continue
            if loader[0] <= w.pc <= loader[1] and 0x6000 <= w.offset:
                continue            # the phase loader: W's image, planes
            if far[0] <= w.pc <= far[1] and \
                    GL.WR['SLOT1'][0] <= w.offset < GL.WR['SLOT2'][1]:
                continue            # a group's load (gr_load, far_get)
        elif w.storage == 'lc' and drv[0] <= w.pc <= drv[1] and (
                desc[0] <= w.offset <= desc[1] or w.offset >= 0xFFFE or
                any(lo <= w.offset < hi for lo, hi in allowed)):
            continue
        elif w.storage == 'aux' and any(
                lo <= w.offset < hi for lo, hi in aux.get(w.bank, ())):
            continue
        out.append('pc $%04X wrote %s %d $%04X' % (w.pc, w.storage, w.bank,
                                                     w.offset))
    return out


def run_one(prep: Prep, b: RC.Build, fill: int, profile: Optional[str],
            keep: bool = False) -> Dict[str, Any]:
    """The case on image b at fill under profile (None: no cost model):
    the comparison, the declared outputs, the stray writes, the native
    checks, the call's clock and cycles, the lowest S."""
    case, up, spec = prep.case, prep.up, prep.spec
    res: Dict[str, Any] = {'case': case.path.name if case.path else
                           case.header.get('note') or 'synthetic',
                           'routine': case.key, 'hit': case.header['hit'],
                           'fill': '%02x' % fill, 'profile': profile,
                           'ok': False}
    if prep.problems:
        res['error'] = 'bridge: ' + '; '.join(prep.problems[:3])
        return res
    if prep.accepted:
        res['stale_links'] = len(prep.accepted)
    img = G.Image(b, fill, store=True)
    img.recs += GR.base_records(up.gamemap)
    img.recs += prep.recs
    for a, d in prep.zp:
        img.main(a, d)
    name = spec['native']
    img.poke_word('dg_entry', b.labels[name])
    img.poke_label('dg_grp', bytes([G.entry_group(b, name)]))
    work = Path(tempfile.mkdtemp(prefix='tmp-spawn-run-', dir=str(BUILD)))
    try:
        start = time.time()
        r = G.run(img, work, GL.MODES['ROUTINE'], None,
                  regs=tuple(prep.regs), banks=prep.banks, profile=profile,
                  write_log=MS.LOG_RANGES)
        res['seconds'] = round(time.time() - start, 2)
        res['lowest_s'] = r.state.get('lowest_s')
        writes = MS.read_log(work / 'writes.log') \
            if (work / 'writes.log').exists() else []
        res['clock'], res['cpu_cycles'] = MS.call_clock(writes, b)
        st = stray([w for _, w in writes], b, prep.header)
        res['strays'] = len(st)
        if st:
            res['stray_first'] = st[:4]
        ended = r.ended()
        res['ended'] = ended
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                res['stop'] = G.stop_codes(G.load_snapshot(p))
            return res
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    from native import setupcheck as SC
    try:
        nat = PortReader(prep.mf).read(SC.port_memory(m))
    except PortError as error:
        res['diff'] = ['the port reader: %s' % error]
        return res
    diff = gcanon.compare(up.s_out, nat, 'routine')
    diff += MS.native_checks(m)
    res['fc_loads'] = m.main[GL.RT['FC_LOADS']] | \
        m.main[GL.RT['FC_LOADS'] + 1] << 8
    diff += outputs(prep, b, m)
    res['diff'] = diff[:12]
    res['ok'] = not diff and not res['strays']
    if keep:
        res['_done'] = m
    return res


def outputs(prep: Prep, b: RC.Build, m) -> List[str]:
    """Every declared output of the entry against upstream's."""
    lab = b.labels
    regs = {'a': G.card_byte(m, lab['dg_ra']),
            'x': G.card_byte(m, lab['dg_rx']),
            'y': G.card_byte(m, lab['dg_ry']),
            'p': G.card_byte(m, lab['dg_rp'])}
    out = []
    for item in prep.spec.get('out', []):
        nv, n = item['native'], item.get('bytes', 2)
        if nv == 'ax':
            value = regs['a'] | regs['x'] << 8
        elif nv in ('a', 'x', 'y'):
            value = regs[nv]
        elif nv == 'c':
            value, n = regs['p'] & 1, 1
        elif nv.startswith('zp:'):
            a = GR.zp_address(nv[3:])
            value = int.from_bytes(bytes(m.main[a:a + n]), 'little')
        elif nv.startswith('sb:'):
            a = place(b, nv[3:])
            value = int.from_bytes(bytes(m.main[a:a + n]), 'little')
        else:
            raise GR.HarnessError('a native output %r' % nv)
        raw = source(prep.up, item['upstream'], 'out')
        uv = int.from_bytes(raw, 'little')
        mask = (1 << (8 * n)) - 1
        if value & mask != uv & mask:
            out.append('output %s: %X != %X' % (item['upstream'],
                                                value & mask, uv & mask))
    return out


# ---------------------------------------------------------------------------
# The synthetic cases: a captured state poked, the reference's own call
# ---------------------------------------------------------------------------

def uconst(name: str) -> int:
    return MS.uconst(name)


def mobj_ptr(case: GC.Case, sym: str = '_Dp') -> int:
    return int.from_bytes(case.entry.read(MS.dp_address(case, sym), 4),
                          'little') & 0xFFFFFF


def field(case: GC.Case, ptr: int, name: str, n: int = 4,
          signed: bool = True) -> int:
    return int.from_bytes(case.entry.read(ptr + uconst(name), n), 'little',
                          signed=signed)


def s32(v: int) -> bytes:
    return (v & 0xFFFFFFFF).to_bytes(4, 'little')


FRAC = 0x10000


def player_ptr(case: GC.Case) -> int:
    t = GC.CL.Linkmap()
    return int.from_bytes(case.entry.read(
        t.address('g_game65.s:_g_player') + uconst('UO_PL_MO'), 4),
        'little') & 0xFFFFFF


def zm_kind(case: GC.Case) -> Dict[str, Any]:
    p = mobj_ptr(case)
    flags = field(case, p, 'UO_MO_FLAGS', signed=False)
    return {'ptr': p, 'player': p == player_ptr(case),
            'missile': bool(flags >> 16 & uconst('UC_MF_MISSILE_HI')),
            'noclip': bool(flags & uconst('UC_MF_NOCLIP_LO')),
            'nogravity': bool(flags & uconst('UC_MF_NOGRAVITY_LO')),
            'z': field(case, p, 'UO_MO_Z'),
            'floorz': field(case, p, 'UO_MO_FLOORZ'),
            'ceilingz': field(case, p, 'UO_MO_CEILINGZ'),
            'height': field(case, p, 'UO_MO_HEIGHT'),
            'momz': field(case, p, 'UO_MO_MOMZ')}


def _first(key: str, pred) -> GC.Case:
    for _, p, _ in case_paths(key):
        c = GC.load_case(p)
        if pred(c):
            return c
    raise PartError('no captured %s case for the synthetic case' % key)


def _zm_synthetic(name: str) -> GC.Case:
    """P_ZMovement on a captured state with the mobj's fields poked."""
    def mobj(missile=False, player=False, gravity=None):
        def pred(c):
            k = zm_kind(c)
            if k['player'] != player or k['missile'] != missile or \
                    k['noclip']:
                return False
            if gravity is not None and k['nogravity'] == gravity:
                return False
            return k['ceilingz'] - k['floorz'] > k['height'] + 16 * FRAC
        return _first(ZMOVE, pred)
    if name == 'zm-ceiling-rise':
        c = mobj()
        pk = 'momz'
    elif name == 'zm-ceiling-stuck':
        c = mobj(gravity=True)
        pk = 'stuck'
    elif name == 'zm-ceiling-missile':
        c = mobj(missile=True)
        pk = 'momz'
    elif name == 'zm-floor-missile':
        c = mobj(missile=True)
        pk = 'down'
    elif name in ('zm-hard-landing', 'zm-hard-landing-dead'):
        c = mobj(player=True)
        pk = 'hard'
    elif name == 'zm-squat':
        c = mobj(player=True)
        pk = 'squat'
    elif name == 'zm-rest':
        c = mobj(gravity=True)
        pk = 'rest'
    else:
        raise PartError('no synthetic case %s' % name)
    k = zm_kind(c)
    p = k['ptr']
    zf, zc, h = k['floorz'], k['ceilingz'], k['height']
    pokes = []
    if pk == 'momz':        # from mid-air into the ceiling
        z = zf + (zc - zf - h) // 2
        pokes += [(p + uconst('UO_MO_Z'), s32(z)),
                  (p + uconst('UO_MO_MOMZ'), s32(zc - (z + h) + 3 * FRAC))]
    elif pk == 'stuck':     # through the ceiling, not rising
        pokes += [(p + uconst('UO_MO_Z'), s32(zc - h + 2 * FRAC)),
                  (p + uconst('UO_MO_MOMZ'), s32(0))]
    elif pk == 'down':      # into the floor
        z = zf + (zc - zf - h) // 2
        pokes += [(p + uconst('UO_MO_Z'), s32(z)),
                  (p + uconst('UO_MO_MOMZ'), s32(-(z - zf) - 2 * FRAC))]
    elif pk == 'hard':      # the player falls fast onto the floor
        pokes += [(p + uconst('UO_MO_Z'), s32(zf + 4 * FRAC)),
                  (p + uconst('UO_MO_MOMZ'), s32(-10 * FRAC - 0x1234))]
        if name.endswith('dead'):
            pokes.append((p + uconst('UO_MO_HEALTH'), bytes(2)))
    elif pk == 'squat':     # the player below a step's floor
        pokes += [(p + uconst('UO_MO_Z'), s32(zf - 6 * FRAC - 0x2345)),
                  (p + uconst('UO_MO_MOMZ'), s32(0))]
    elif pk == 'rest':      # in the air with no height momentum
        pokes += [(p + uconst('UO_MO_Z'), s32(zf + (zc - zf - h) // 2)),
                  (p + uconst('UO_MO_MOMZ'), s32(0))]
    return _call(c, ZMOVE, pokes, name)


def _call(base: GC.Case, key: str, pokes, note: str,
          regs: Optional[Dict[str, int]] = None) -> GC.Case:
    entry = base.entry.copy()
    entry.header = base.entry.header
    for a, d in pokes:
        entry.write(a, d)
    after, call = MS.ref_call(entry, key, (), regs)
    hdr = dict(base.header, routine=key, note=note, call=call)
    return GC.Case(hdr, entry, after, None)


def _range_poke(value: int) -> Tuple[int, bytes]:
    t = GC.CL.Linkmap()
    return (t.address('p_attack65.s:AT_RANGE'), s32(value))


MELEERANGE = 64 * FRAC


def synthetic_case(name: str) -> GC.Case:
    if name.startswith('zm-'):
        return _zm_synthetic(name)
    if name == 'puff-punch':
        c = _first(PUFF, lambda c: True)
        return _call(c, PUFF, [_range_poke(MELEERANGE)], name)
    if name.startswith('blood-'):
        dmg = int(name.split('-')[1])
        c = _first(BLOOD, lambda c: True)
        s = c.regs_in['s']
        return _call(c, BLOOD, [((s + 4) & 0xFFFF, (dmg & 0xFFFF).to_bytes(
            2, 'little'))], name)
    if name == 'melee-range':
        c = _first(MELEE, lambda c: True)
        return _call(c, MELEE, [_range_poke(MELEERANGE)], name)
    if name == 'melee-lo-only':
        c = _first(MELEE, lambda c: True)
        return _call(c, MELEE, [_range_poke(MELEERANGE + FRAC)], name)
    raise PartError('no synthetic case %s' % name)


def synthetic_took(name: str, case: GC.Case) -> List[str]:
    """What the reference's own call must show for the synthetic case to
    be the case it is named for (else the case proves nothing)."""
    def f(mem, ptr, n, size=4):
        return int.from_bytes(mem.read(ptr + uconst(n), size), 'little',
                              signed=True)
    out = []
    if name.startswith('zm-'):
        p = mobj_ptr(case)
        a, b_ = case.entry, case.after
        top = f(b_, p, 'UO_MO_CEILINGZ') - f(b_, p, 'UO_MO_HEIGHT')
        missile = uconst('UC_MF_MISSILE_HI') << 16
        t_ = GC.CL.Linkmap().address('g_game65.s:_g_player')
        if name in ('zm-ceiling-rise', 'zm-ceiling-stuck') and \
                f(b_, p, 'UO_MO_Z') != top:
            out.append('z is not ceilingz - height')
        if name == 'zm-ceiling-rise' and f(b_, p, 'UO_MO_MOMZ') != 0:
            out.append('momz is not 0')
        if name in ('zm-ceiling-missile', 'zm-floor-missile') and (
                not f(a, p, 'UO_MO_FLAGS') & missile or
                f(b_, p, 'UO_MO_FLAGS') & missile):
            out.append('the missile did not explode')
        if name.startswith('zm-hard-landing'):
            d = int.from_bytes(b_.read(t_ + uconst('UO_PL_DELTAVIEWHEIGHT'),
                                       4), 'little', signed=True)
            if d != f(a, p, 'UO_MO_MOMZ') >> 3:
                out.append('no hard landing')
        if name == 'zm-squat' and a.read(t_ + uconst('UO_PL_VIEWHEIGHT'),
                                         4) == b_.read(
                t_ + uconst('UO_PL_VIEWHEIGHT'), 4):
            out.append('no squat')
        if name == 'zm-rest' and f(b_, p, 'UO_MO_MOMZ') != -2 * FRAC:
            out.append('no fall from rest')
    if name == 'melee-range' and case.regs_out['a'] & 0xFFFF != 1:
        out.append('not the melee range')
    return ['synthetic %s: %s' % (name, x) for x in out]


SYNTHETIC = ('zm-ceiling-rise', 'zm-ceiling-stuck', 'zm-ceiling-missile',
             'zm-floor-missile', 'zm-hard-landing', 'zm-hard-landing-dead',
             'zm-squat', 'zm-rest', 'puff-punch', 'blood-8', 'blood-9',
             'blood-12', 'blood-13', 'melee-range', 'melee-lo-only')


def synthetic_key(name: str) -> str:
    return ZMOVE if name.startswith('zm-') else PUFF if name.startswith(
        'puff') else BLOOD if name.startswith('blood') else MELEE


# ---------------------------------------------------------------------------
# The jobs
# ---------------------------------------------------------------------------

_BUILDS: Dict[str, RC.Build] = {}


def _build(obj: str) -> RC.Build:
    if obj not in _BUILDS:
        _BUILDS[obj] = load(Path(obj))
    return _BUILDS[obj]


def _job(job) -> List[Dict[str, Any]]:
    """kind ('case' or 'synthetic'), the case file or the synthetic name,
    the entry, its path, the image, fills, profiles."""
    kind, what, key, path, obj, fills, profiles = job
    MS.use_cases(MYCASES)
    b = _build(obj)
    try:
        case = GC.load_case(Path(what)) if kind == 'case' else \
            synthetic_case(what)
        spec = GR.all_args()[key]
        prep = Prep(case, spec, b)
    except Exception as error:              # reported, never hidden
        return [{'ok': False, 'kind': kind, 'entry': key, 'path': path,
                 'case': Path(what).name if kind == 'case' else what,
                 'error': '%s: %s' % (type(error).__name__, error)}]
    took = synthetic_took(what, case) if kind == 'synthetic' else []
    out = []
    for fill in fills:
        for prof in profiles:
            try:
                r = run_one(prep, b, fill, prof)
                if took:
                    r['ok'] = False
                    r['diff'] = took + r.get('diff', [])
            except Exception as error:      # reported per run
                r = {'ok': False, 'fill': '%02x' % fill, 'profile': prof,
                     'error': '%s: %s' % (type(error).__name__, error)}
            r.update(kind=kind, entry=key, path=path,
                     case=Path(what).name if kind == 'case' else what)
            out.append(r)
    return out


def blood_path(case: GC.Case) -> str:
    d = int.from_bytes(case.entry.read((case.regs_in['s'] + 4) & 0xFFFF, 2),
                       'little', signed=True)
    return 'BLOOD3' if d < 9 else 'BLOOD2' if d <= 12 else 'BLOOD1'


def plan(obj: Path = OUT, fills=FILLS, profiles=PROFILES, sample: int = 1,
         entries: Optional[Sequence[str]] = None,
         synthetic_names: Sequence[str] = SYNTHETIC
         ) -> Tuple[List[Tuple], Dict[str, Any]]:
    """The checkpoint's jobs and its eligibility table."""
    o = str(obj)
    jobs: List[Tuple] = []
    elig: Dict[str, Any] = {}
    for key in ENTRIES:
        if entries and key not in entries:
            continue
        e = elig.setdefault(key, {})
        for run, p, cls in case_paths(key)[::sample]:
            r = e.setdefault(run, {'calls': survey(run)['routines'][
                key]['calls'], 'captured': 0, 'eligible': 0, 'waiting': {}})
            r['captured'] += 1
            hit = int(p.name[1:9])
            wait = eligible(run, key, hit)
            if wait:
                for t in wait:
                    r['waiting'][t] = r['waiting'].get(t, 0) + 1
                continue
            r['eligible'] += 1
            if key == BLOOD:
                cls = blood_path(GC.load_case(p))
            elif key == PUFF:       # (one P_IsAttackRangeMeleeRange a puff)
                cls = 'melee test: ' + path_class(run, MELEE, hit)
            elif key == SHR3:
                cls = 'shr3'
            jobs.append(('case', str(p), key, cls, o, tuple(fills),
                         tuple(profiles)))
    for name in synthetic_names:
        key = synthetic_key(name)
        if entries and key not in entries:
            continue
        jobs.append(('synthetic', name, key, 'synthetic: ' + name, o,
                     tuple(fills), tuple(profiles)))
    return jobs, elig


def job_key(j: Tuple) -> str:
    kind, what, key, path, obj, fills, profiles = j
    return json.dumps([kind, Path(what).parent.parent.name + '/' +
                       Path(what).name if kind == 'case' else what, key,
                       list(fills), list(profiles)])


def label(j: Tuple, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A captured case's results named RUN/FILE (hits repeat across
    runs)."""
    if j[0] == 'case':
        name = '%s/%s' % (Path(j[1]).parent.parent.name, Path(j[1]).name)
        for r in results:
            r['case'] = name
    for r in results:
        r['path'] = j[3]
    return results


def run_jobs(jobs: Sequence[Tuple], workers: int = JOBS, journal:
             Optional[Path] = None, quiet: bool = False
             ) -> List[Dict[str, Any]]:
    """The jobs' results; with a journal (JSON lines), each job's results
    are appended as it ends and a job already there is not run again."""
    out: List[Dict[str, Any]] = []
    done: Dict[str, List[Dict[str, Any]]] = {}
    if journal is not None and journal.exists():
        for line in journal.read_text().splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            done[d['job']] = d['results']
    todo = []
    for j in jobs:
        k = job_key(j)
        if k in done:
            out += label(j, done[k])
        else:
            todo.append(j)
    if done and not quiet:
        say('%d jobs from the journal, %d to run' % (len(jobs) - len(todo),
                                                    len(todo)))

    def keep(j, got):
        label(j, got)
        if journal is not None:
            with open(str(journal), 'a') as handle:
                handle.write(json.dumps({'job': job_key(j), 'results': got},
                                        default=str) + '\n')
    if workers <= 1:
        for j in todo:
            got = _job(j)
            keep(j, got)
            out += got
        return out
    n = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for j, got in zip(todo, pool.map(_job, todo, chunksize=1)):
            keep(j, got)
            out += got
            n += 1
            if not quiet and n % 100 == 0:
                say('%d of %d jobs' % (n, len(todo)))
    return out


def image_digest(obj: Path = OUT) -> str:
    h = hashlib.sha256()
    for p in sorted(obj.glob(NAME + '.*')):
        if p.suffix not in ('.lbl', '.map'):
            h.update(p.name.encode() + p.read_bytes())
    return h.hexdigest()[:16]


def check(jobs: int = JOBS, sample: int = 1, entries=None,
          synthetic_names: Sequence[str] = SYNTHETIC, rebuild: bool = True,
          quiet: bool = False) -> Dict[str, Any]:
    """The checkpoint on the part's image: report.json's checkpoint
    half."""
    if rebuild:
        build()
    b = load()
    js, elig = plan(OUT, FILLS, PROFILES, sample, entries, synthetic_names)
    if not quiet:
        say('%d jobs' % len(js))
    start = time.time()
    journal = None
    if sample == 1 and not entries:
        journal = OUT / ('journal-%s.jsonl' % image_digest())
        for old in OUT.glob('journal-*.jsonl'):
            if old != journal:
                old.unlink()
    res = run_jobs(js, jobs, journal, quiet)
    rep = {'entries': MS.summarize(res), 'eligibility': elig,
           'runs': len(res),
           'failures': sum(1 for r in res if not r.get('ok')),
           'strays': sum(r.get('strays') or 0 for r in res),
           'seconds': round(time.time() - start),
           'fills': ['%02x' % f for f in FILLS], 'profiles': list(PROFILES),
           'sizes': sizes(b), 'sample': sample}
    rep['paths_taken'] = {k: sorted(e['paths']) for k, e in
                          rep['entries'].items()}
    return rep


# ---------------------------------------------------------------------------
# shr3's random check (GAME.md 2.4 "Arithmetic")
# ---------------------------------------------------------------------------

BULK_IN, BULK_OUT = 93, 94
BULK_ROOM = 0xC000 - 0x0200
EDGES = (0, 1, -1, 2, -2, 7, -7, 8, -8, 9, -9, 15, -15, 16, -16,
         0x7FFFFFFF, -0x80000000, 0x7FFFFFF8, -0x7FFFFFF8, 0xFFFF, 0x10000,
         -0x10000, 0x8000, -0x8000, 0x7FFF, -0x7FFF, 0x10007, -0x10007,
         0x80000, -0x80000, 0x290000, -0x290000)


def shr3_inputs(n: int, seed: int = 1) -> List[int]:
    rnd = random.Random(seed)
    out = list(EDGES)
    while len(out) < n:
        k = len(out) % 4
        if k == 0:
            out.append(rnd.randint(-0x80000000, 0x7FFFFFFF))
        elif k == 1:
            out.append(rnd.randint(-0x400000, 0x400000))   # momz-like
        elif k == 2:
            out.append(rnd.randint(-64, 64))
        else:
            out.append(rnd.choice((1, -1)) * (1 << rnd.randint(0, 30)) +
                       rnd.randint(-8, 8))
    return [((v + 0x80000000) & 0xFFFFFFFF) - 0x80000000 for v in out[:n]]


def native_bulk(b: RC.Build, values: Sequence[int]) -> List[int]:
    per = BULK_ROOM // 4
    out: List[int] = []
    for start in range(0, len(values), per):
        chunk = values[start:start + per]
        img = G.Image(b, 0xA5, store=False)
        img.aux(BULK_IN, 0x0200, b''.join(s32(v) for v in chunk))
        work = Path(tempfile.mkdtemp(prefix='tmp-spawn-bulk-',
                                     dir=str(BUILD)))
        try:
            k = len(chunk)
            r = G.run(img, work, GL.MODES['ROUTINE'], 'sp_bulk',
                      regs=(0, k & 0xFF, k >> 8, 0x34), banks=[BULK_OUT])
            if r.ended() != 'halt':
                raise PartError('sp_bulk ended %s' % r.ended())
            m = G.load_snapshot(work / 'done.img')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        data = bytes(m.aux[BULK_OUT][0x0200:0x0200 + 4 * len(chunk)])
        out += [int.from_bytes(data[i:i + 4], 'little', signed=True)
                for i in range(0, len(data), 4)]
    return out


def random_check(n: int = 100_000, seed: int = 1,
                 b: Optional[RC.Build] = None) -> Dict[str, Any]:
    """shr3 on n inputs: upstream's (mathref batch on a captured shr3
    call's machine: A the high word, X the low word in, the same out)
    against the native (sp_bulk) and against the arithmetic shift."""
    import sight as SG
    MS.use_cases(MYCASES)
    cases = case_paths(SHR3)
    if not cases:
        raise PartError('no shr3 case (python3 tools/native/gparts/spawn.py '
                        '--capture)')
    case = GC.load_case(cases[0][1])
    b = b or load()
    vals = shr3_inputs(n, seed)
    recs = b''.join(struct.pack('<HH', (v >> 16) & 0xFFFF, v & 0xFFFF)
                    for v in vals)
    pc = GC.CL.Linkmap().address(SHR3)
    ups = SG.mathref(case, 'shr3', pc, ['a', 'x'], ['a', 'x'], recs, 4)
    upv = []
    for u in ups:
        hi, lo = struct.unpack('<HH', u)
        v = hi << 16 | lo
        upv.append(v - (1 << 32) if v & 0x80000000 else v)
    nat = native_bulk(b, vals)
    bad = [(v, u, m_) for v, u, m_ in zip(vals, upv, nat) if u != m_]
    model = sum(1 for v, u in zip(vals, upv) if u == v >> 3)
    return {'inputs': len(vals), 'compared': min(len(upv), len(nat)),
            'different': len(bad) + abs(len(upv) - len(nat)),
            'first': bad[:5], 'edges': len(EDGES),
            'upstream_is_the_arithmetic_shift': model, 'seed': seed}


# ---------------------------------------------------------------------------
# The planted bugs (GAME.md 2.4's row): each in a scratch copy of the
# part's sources, its image in a temporary directory, run on its check
# ---------------------------------------------------------------------------

SP = 'game/%s/' % PART
PLANTS: Dict[str, Dict[str, Any]] = {
    # gravity after the floor clamp: a mobj that lands (or sits on its
    # floor) still gets gravity: P_ZMovement's calls of the floor path
    'gravity-after-floor-clamp': {'check': ZMOVE, 'paths': 'floor', 'bugs': [
        (SP + 'zmove.s', """        FCALL missileHit
        bcc @ceil
        rts
@air:""", """        FCALL missileHit
        bcs @r                  ; (planted: gravity after the floor clamp)
        jsr zget
        bra @air
@r:     rts
@air:""")]},
    # the puff's z P_Random taken after the tics' (the index): the puff
    # spawned at z, its tics noise, then the z noise on its z
    'puff-z-random-after-tics': {'check': PUFF, 'paths': None, 'bugs': [
        (SP + 'spawn.s', """        ROUTINE P_SpawnPuff
        FCALL zNoise            ; z += noise (saveXYZ: GA_X..GA_Z kept)
        lda #UC_MT_PUFF         ; the puff
        FCALL spawnXYZ
        ldy #1                  ; momz = FRACUNIT
        jsr momz
        lda SP_TH               ; the tics' noise
        ldx SP_TH+1
        FCALL ticsNoise""", """        ROUTINE P_SpawnPuff
        lda #UC_MT_PUFF         ; (planted: the z noise after the tics')
        FCALL spawnXYZ
        ldy #1
        jsr momz
        lda SP_TH
        ldx SP_TH+1
        FCALL ticsNoise
        lda SP_TH
        ldx SP_TH+1
        jsr mo_get
        ldy #TH_Z + 3
        ldx #3
:       lda (GC_MP),y
        sta GA_Z,x
        dey
        dex
        bpl :-
        FCALL zNoise
        lda SP_TH
        ldx SP_TH+1
        jsr mo_get
        ldy #TH_Z + 3
        ldx #3
:       lda GA_Z,x
        sta (GC_MP),y
        dey
        dex
        bpl :-
        lda #D_RTH
        jsr mo_dirty""")]},
    # blood's state thresholds one off (damage < 10 and damage < 14):
    # P_SpawnBlood's captured calls and the synthetic damages
    'blood-thresholds-off': {'check': BLOOD, 'paths': None, 'bugs': [
        (SP + 'spawn.s', """        sbc #9
        lda SP_DMG+1""", """        sbc #10                 ; (planted: one off)
        lda SP_DMG+1"""),
        (SP + 'spawn.s', """        sbc #13
        lda SP_DMG+1""", """        sbc #14                 ; (planted: one off)
        lda SP_DMG+1""")]},
    # the squat's deltaviewheight shift: >> 2 for >> 3 (the value doubled
    # after shr3): P_ZMovement's calls of the squat path
    'squat-shift': {'check': ZMOVE, 'paths': 'squat', 'bugs': [
        (SP + 'zmove.s', """        FCALL shr3
        jsr dvh
        jsr zget                ; (the line again)""", """        FCALL shr3
        asl GA_0                ; (planted: >> 2, not >> 3)
        rol GA_1
        rol GA_2
        rol GA_3
        jsr dvh
        jsr zget                ; (the line again)""")]},
}


def plant_jobs(plant: Dict[str, Any], obj: Path, limit: int = 40
               ) -> List[Tuple]:
    """The plant's check: its entry's eligible captured cases (those whose
    path holds the plant's path, when it names one), then its synthetic
    cases; one fill, no cost model."""
    key = plant['check']
    js, _ = plan(obj, (0xA5,), (None,), entries=[key])
    cases = [j for j in js if j[0] == 'case' and (
        plant['paths'] is None or plant['paths'] in j[3].split(','))]
    synth = [j for j in js if j[0] == 'synthetic' and (
        plant['paths'] is None or plant['paths'] in j[1])]
    return synth + spread(cases, limit)


def run_plant(name: str) -> Dict[str, Any]:
    p = PLANTS[name]
    tmp = Path(tempfile.mkdtemp(prefix='tmp-spawn-plant-', dir=str(BUILD)))
    try:
        obj = build(tmp / 'game', p['bugs'])
        js = plant_jobs(p, obj)
        res = run_jobs(js, JOBS, quiet=True)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
        _BUILDS.clear()
    bad = [r for r in res if not r.get('ok')]
    return {'check': p['check'] + (' (%s)' % p['paths'] if p['paths']
                                   else ''),
            'runs': len(res), 'failed': len(bad), 'caught': bool(bad),
            'first': [{k: r.get(k) for k in ('case', 'path', 'diff',
                                             'error', 'ended', 'stop')
                       if r.get(k)} for r in bad[:2]]}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def write_report(rep: Dict[str, Any], plants: Optional[Dict[str, Any]] = None,
                 rnd: Optional[Dict[str, Any]] = None) -> Path:
    out = {}
    if REPORT.exists():
        out = json.loads(REPORT.read_text())
    out.update(rep)
    out['format'] = 'game-part-report 1'
    out['part'] = PART
    out['wave'] = WAVE
    if plants is not None:
        out['plants'] = plants
    if rnd is not None:
        out['random'] = {'shr3': rnd}
    out['build_kb'] = MS.du_kb(OUT)
    out['notes'] = [
        'clock: the call\'s time from call_entry to its return under the '
        'profile (a2vm --cost-timed: fabric clocks); cpu_cycles: the '
        'W65C02S\'s cycles of the same span; every slot empty at the call, '
        'so a paged callee is loaded (an upper bound)',
        'lowest_s: the lowest S of the run (the driver starts at $EF)',
        'paths: P_ZMovement, missileHit, isPlayer, P_IsAttackRangeMeleeRange '
        'by the reference\'s path marks (--paths); P_SpawnBlood by the '
        'state its damage chooses; synthetic cases by name',
        'sizes: spawn.s and zmove.s; sptest.s is test-only (the driver\'s '
        'area)']
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=1, default=str) + '\n')
    return REPORT


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--paths', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--synthetic', action='store_true')
    parser.add_argument('--random', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--jobs', type=int, default=JOBS)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--count', type=int, default=100_000)
    parser.add_argument('--entries', default='')
    args = parser.parse_args(argv)
    status = 0
    if args.build:
        print(json.dumps(sizes(load(build())), indent=1))
    if args.paths:
        paths(args.jobs)
    if args.capture:
        capture(args.jobs)
    if args.synthetic:
        build()
        js, _ = plan(entries=None, sample=1 << 30)
        js = [j for j in js if j[0] == 'synthetic']
        res = run_jobs(js, args.jobs, quiet=True)
        for r in res:
            print('%-4s %-26s %-8s %-4s %s' % (
                'ok' if r.get('ok') else 'FAIL', r.get('case'),
                r.get('profile'), r.get('fill'), '' if r.get('ok') else
                (r.get('diff') or r.get('error') or r.get('stop'))))
        status |= 0 if all(r.get('ok') for r in res) else 1
    if args.check:
        rep = check(args.jobs, args.sample,
                    [e for e in args.entries.split(',') if e] or None)
        write_report(rep)
        for k, e in sorted(rep['entries'].items()):
            print('%-42s %4d cases %5d runs %3d failed  cycles f121 %s '
                  'fastpath %s  S %s' % (
                      k, e['cases'], e['runs'], e['failures'],
                      e['cpu_cycles'].get('f121'),
                      e['cpu_cycles'].get('fastpath'), e['lowest_s']))
        print('runs %d, failures %d, stray writes %d, %d s' % (
            rep['runs'], rep['failures'], rep['strays'], rep['seconds']))
        status |= 1 if rep['failures'] or rep['strays'] else 0
    if args.random:
        r = random_check(args.count)
        print(json.dumps(r, indent=1))
        write_report({}, rnd=r)
        status |= 1 if r['different'] else 0
    if args.plants:
        pl = {}
        for n in PLANTS:
            pl[n] = run_plant(n)
            print('%-28s %s' % (n, ('caught: %d of %d runs fail: %s' % (
                pl[n]['failed'], pl[n]['runs'], str(pl[n]['first'])[:300]))
                if pl[n]['caught'] else 'NOT CAUGHT (%d runs)' %
                pl[n]['runs']))
        write_report({}, plants=pl)
        status |= 0 if all(p['caught'] for p in pl.values()) else 1
    if args.report:
        print(REPORT.read_text() if REPORT.exists() else 'no report yet')
    return status


if __name__ == '__main__':
    sys.exit(main())
