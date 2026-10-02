#!/usr/bin/env python3
"""Part tic's checkpoint (milestone 10, wave 6; docs/GAME.md 2.4, 3.5;
docs/game-parts/tic.md), lean (the owner's rules of 2026-10-02: at most
40 calls a routine, the $A5 machine only, f121): its image, a sample of
its routines' captured calls, the reference's own calls of P_MobjThinker
and of a paused G_Ticker, its planted bugs, and
build/native/game/tic/report.json.

Usage:  python3 tools/native/gparts/tic.py --build
        python3 tools/native/gparts/tic.py --capture [--jobs 2]
        python3 tools/native/gparts/tic.py --synth [--jobs 2]
        python3 tools/native/gparts/tic.py --check [--jobs 2] [--sample K]
        python3 tools/native/gparts/tic.py --plants [--jobs 2]
        python3 tools/native/gparts/tic.py --report

The image (build()): `make -f game.mk part P=tic` from a scratch copy of
the build files and of the planted bugs' files, every other source from
the tree (game.mk's vpath), into build/native/game/tic/ (or a temporary
directory). It links waves 1-5 and the part: wave 6's other parts
(movers, wfire, chase) are not in it, so a call that reaches one of their
dispatch targets (A_Chase, T_VerticalDoor, T_PlatRaise, the weapons'
attacks) is not eligible (GAME.md 3.5 step 6).

The selection (at most QUOTA calls an entry, eligible calls only: every
dispatch target the survey saw the call reach is built in the image),
spread over the classes of the calls (the run's kind: a demo or the ring
of commands; the dispatch targets reached), the rare classes first:
P_RunThinkers (the walk; its classes take the removals of a mobj and of a
special, the states' actions, the slides), P_Ticker (and a run of 8
consecutive tics of demo2, so that leveltime crosses a multiple of 8: the
animated textures' and the flats' frames), G_Ticker (level tics with no
load: the command of a demo and of the ring), P_MapEnd. The captures
(--capture): tools/native/gamecap.py's, into the part's own
build/native/game/tic/cases/.

The reference's own calls (--synth, ref816 --call on captured states,
GAME.md 3.5's synthetic cases):
  P_MobjThinker  THTAB's (upstream enters it by the walk's JML [FN_P],
                 which --capture does not count): on the entry state of
                 captured P_RunThinkers calls, _Dp = a mobj of
                 P_MobjThinker's, chosen by class: momentum in x or y
                 (P_XYMovement), in the air or momz (P_ZMovement), tics 1
                 (its state ends), tics -1, other tics; a mobj whose state
                 would end in an action not built is not chosen
  paused         G_Ticker on a captured level tic of the tour (no demo)
                 with menuactive 1 and the tic's ring slot made different
                 from the player's command: basetic + 1, no command copied,
                 P_Ticker paused (viewz is not 1)
Each is saved in the case format against its run's base, with the
captured call's pages (so that the entry is the captured one) and the
call's writes.

A run (run_one()): part mobjstate's run machinery (the case's entry state
through the game manifest into a machine poisoned with $A5, the entry's
inputs of args.json, the call, the state read back and compared with the
reference's return state, gcanon's routine mode, exclusions R1-R7, the
write log's stray writes, the native-only globals), on a2vm under f121,
with the tic phase's own globals (G_WSET, G_FPSSHOW, G_ONGROUND) and the
demo bank (part flow's demob_records) written from the reference; the
outputs declared here: P_MapEnd's tmthing (GM_TMTHING), and every entry's
G_ONGROUND against upstream's PU_ONGROUND (part player's persistent
onground). A call that stops at an unbuilt dispatch target counts as
waiting (by the target), not as a failure.
"""

import argparse
import json
import random
import shutil
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

from native import gamecap as GC, gameroutine as GR, glayout as GL, \
    grun as G, llayout as LL, render_check as RC, \
    rlayout as R  # noqa: E402
from ref816 import bounded  # noqa: E402
import mobjstate as MS  # noqa: E402  (wave 1's harness: its run machinery)
import flowcheck as FC  # noqa: E402  (wave 1's: the demo bank's records)

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'tic'
WAVE = 6
OUT = GL.GAME / PART
MYCASES = OUT / 'cases'
REPORT = OUT / 'report.json'
FILL = 0xA5
PROFILE = 'f121'
NAME = 'ptest'
UPSTREAM_BYTES = 1155
BUDGET = 1500                   # GAME.md 2.4: upstream 1,155 x 1.3
MODULES = ('gtick', 'ptick')
JOBS = 2

GT = 'g_game65.s:G_Ticker'
PT = 'p_think65.s:P_Ticker'
RT = 'p_tick65.s:P_RunThinkers'
MT = 'p_tick65.s:P_MobjThinker'
ME = 'p_map65.s:P_MapEnd'
ENTRIES = (GT, PT, RT, MT, ME)
CAPTURED = (RT, PT, GT, ME)
QUOTA = {RT: 30, PT: 12, GT: 12, ME: 6, MT: 40}
CONSECUTIVE = ('demo2', PT, 8)  # a run of 8 tics: leveltime crosses 8k
MT_BASES = 10                   # P_RunThinkers cases the mobjs come from
DEMOS = ('demo3', 'demo1', 'demo2')
LOADS = ('g_game65.s:loadLevel', 'g_game65.s:doNewGame',
         'g_game65.s:doPlayDemo', 'g_game65.s:doWorldDone')
MOBJ_CLASSES = ('xy', 'z', 'end', 'ever', 'tics')
SYNTH_NAMES = ('paused',)
# G_Ticker's loads (the load protocol, GAME.md 3.4: GT_LOAD with G_LOADACT,
# the driver's load, g_tresume, the action loop again, WI_End, the new
# level's first P_Ticker): its call at the first tic of each action that
# loads, in these runs
LOAD_RUNS = (('tour', 'g_game65.s:doNewGame'),
             ('tour', 'g_game65.s:doWorldDone'),
             ('newgame', 'g_game65.s:doNewGame'),
             ('demo3', 'g_game65.s:doPlayDemo'),
             ('demo1', 'g_game65.s:loadLevel'))
# G_Ticker in the intermission (WI_Ticker; the tour's tics with
# WI_checkForAccelerate and no load): this many, spread
INTER = ('tour', 'wi_stuff65.s:WI_checkForAccelerate', 2)


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


def missing() -> Optional[str]:
    """None when the shared outputs, the survey, the level bases, ref816
    and a2vm are there; else what is missing and its command."""
    shared = GL.SHARED
    if not ((shared / 'gen' / 'ggame.inc').exists() and
            (shared / 'native-game-1.json').exists()):
        return ('the shared outputs (make -s -C src/native -f game.mk shared '
                'skel ROOT=$PWD)')
    if GC.survey_of('demo2') is None:
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
    """The part's image (GAME/tic/ptest.*) from a scratch copy of the
    build files and of the bugs' files (relative to src/native) with each
    bug (file, old, new) applied once; the copy is deleted."""
    tmp = Path(tempfile.mkdtemp(prefix='tmp-tic-build-', dir=str(BUILD)))
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
        if objs.exists():               # (tic.inc is no prerequisite)
            for p in objs.glob('*.o'):
                p.unlink()
        cmd = ['make', '-s', '-C', str(src), '-f', 'game.mk', 'part',
               'P=%s' % PART, 'ROOT=%s' % ROOT, 'GAME=%s' % game]
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
    """The part's bytes against its budget, and the segments they are in
    (g_tresume, the driver's, in the card's DRIVER area: counted apart)."""
    ms = MS.module_ranges(b)
    by: Dict[str, int] = {}
    driver = 0
    for m in MODULES:
        for seg, lo, hi in ms.get(m, ()):
            if seg == 'DRIVER':
                driver += hi + 1 - lo
            else:
                by[m] = by.get(m, 0) + hi + 1 - lo
    code = sum(by.values())
    return {'modules': by, 'part_bytes': code, 'driver_bytes': driver,
            'budget': BUDGET, 'upstream_bytes': UPSTREAM_BYTES,
            'over_budget_pct': round(100.0 * (code - BUDGET) / BUDGET, 1),
            'segments': {m: sorted({seg for seg, _, _ in ms.get(m, ())})
                         for m in MODULES}}


# ---------------------------------------------------------------------------
# The selection and the captures
# ---------------------------------------------------------------------------

_SV: Dict[str, Any] = {}


def survey(run: str) -> Optional[Dict[str, Any]]:
    if run not in _SV:
        _SV[run] = GC.survey_of(run)
    return _SV[run]


def spread(items: Sequence[Any], n: int) -> List[Any]:
    if len(items) <= n:
        return list(items)
    return [items[(i * len(items)) // n] for i in range(n)]


def reached(run: str, key: str, hit: int) -> List[str]:
    sv = survey(run)
    r = sv['routines'].get(key, {})
    return [sv['targets'][i] for i in r.get('reached', {}).get(str(hit), [])]


def unbuilt(targets: Sequence[str]) -> List[str]:
    """The targets not built in the part's image (waves 1-5 and tic)."""
    built = set(GL.built_set(extra=[PART])) | {'core'}
    return [t for t in targets if (GL.owner_of(t) or 'core') not in built]


def tics_of(run: str, key: str) -> List[int]:
    return list(survey(run)['routines'].get(key, {}).get('tic', []))


def calls_of(key: str) -> List[Tuple[str, int, str]]:
    """(run, hit, class) of every eligible call of key: its reached
    targets built; G_Ticker only in a level tic with no load in it (the
    load protocol's tics are part flow's checkpoint and the integration's),
    and not in a run's last level tic (the demo's end)."""
    out = []
    for run in GC.RUNS:
        sv = survey(run)
        if not sv:
            continue
        r = sv['routines'].get(key)
        if not r:
            continue
        level = sorted(set(tics_of(run, PT)))
        levels = set(level)
        loads = set()
        for k in LOADS:
            loads |= set(tics_of(run, k))
        kind = 'demo' if run in DEMOS else 'ring'
        for h in range(1, r['calls'] + 1):
            got = reached(run, key, h)
            if unbuilt(got):
                continue
            tic = r['tic'][h - 1]
            if not level or tic == level[-1] or (
                    key in (GT, PT, ME) and tic in loads):
                continue
            if tic not in levels:
                continue
            cls = '+'.join([kind] + sorted(t.split(':')[1] for t in got))
            out.append((run, h, cls))
    return out


def _by_class(calls: Sequence[Tuple[str, int, str]], quota: int
              ) -> List[Tuple[str, int, str]]:
    """quota calls spread over the classes (each class its share, the
    rare ones first), the rest spread over every call."""
    by: Dict[str, List[Tuple[str, int, str]]] = {}
    for c in calls:
        by.setdefault(c[2], []).append(c)
    share = max(1, quota // max(1, len(by)))
    picked: List[Tuple[str, int, str]] = []
    for cls in sorted(by, key=lambda k: (len(by[k]), k)):
        picked += spread(by[cls], share)
    picked = picked[:quota]
    rest = [c for c in calls if c not in set(picked)]
    return picked + spread(rest, max(0, quota - len(picked)))


def selection(key: str) -> List[Tuple[str, int, str]]:
    """At most QUOTA[key] calls: for G_Ticker and P_Ticker half from the
    demos and half from the runs on the ring of commands (newgame, tour),
    each half spread over its classes; for P_Ticker first a run of
    consecutive tics (CONSECUTIVE); the others spread over their
    classes."""
    calls = calls_of(key)
    quota = QUOTA[key]
    chosen: List[Tuple[str, int, str]] = []
    if key == CONSECUTIVE[1]:
        run, _, n = CONSECUTIVE
        mine = [c for c in calls if c[0] == run]
        mid = len(mine) // 2
        chosen += mine[mid:mid + n]
    left = [c for c in calls if c not in set(chosen)]
    room = quota - len(chosen)
    if key in (GT, PT):
        ring = [c for c in left if c[2].startswith('ring')]
        demo = [c for c in left if not c[2].startswith('ring')]
        half = _by_class(ring, room // 2)
        chosen += half + _by_class(demo, room - len(half))
    else:
        chosen += _by_class(left, room)
    return sorted(chosen, key=lambda c: (GC.RUNS.index(c[0]), c[1]))


def load_selection() -> List[Tuple[str, int, str]]:
    """(run, hit, class) of G_Ticker's calls that load (LOAD_RUNS: the
    first tic of the action), eligible ones only."""
    out = []
    for run, action in LOAD_RUNS:
        sv = survey(run)
        tics = tics_of(run, action) if sv else []
        if not tics:
            continue
        r = sv['routines'][GT]
        for h in range(1, r['calls'] + 1):
            if r['tic'][h - 1] == tics[0] and not unbuilt(reached(run, GT,
                                                                  h)):
                out.append((run, h, 'load: ' + action.split(':')[1]))
                break
    return out


def inter_selection() -> List[Tuple[str, int, str]]:
    """(run, hit, class) of G_Ticker's calls in the intermission
    (INTER), eligible ones only."""
    run, key, n = INTER
    sv = survey(run)
    if not sv:
        return []
    tics = set(tics_of(run, key))
    loads = set()
    for k in LOADS:
        loads |= set(tics_of(run, k))
    r = sv['routines'][GT]
    hits = [h for h in range(1, r['calls'] + 1)
            if r['tic'][h - 1] in tics and r['tic'][h - 1] not in loads and
            not unbuilt(reached(run, GT, h))]
    return [(run, h, 'ring+intermission') for h in spread(hits, n)]


def _capture_job(job) -> str:
    run, key, hits = job
    MS.use_cases(MYCASES)
    tics = survey(run)['routines'][key]['tic']
    made = GC.capture(run, key, hits, tics, say=lambda *a: None)
    return '%s %s: %d made of %d' % (run, key, len(made), len(hits))


def capture_plan() -> List[Tuple[str, str, List[int]]]:
    MS.use_cases(MYCASES)
    want: Dict[Tuple[str, str], List[int]] = {}
    for key in CAPTURED:
        for run, h, _ in selection(key):
            want.setdefault((run, key), []).append(h)
    for run, h, _ in load_selection() + inter_selection():
        want.setdefault((run, GT), []).append(h)
    todo = []
    for (run, key), hits in sorted(want.items()):
        d = GC.case_dir(run, key)
        miss = sorted({h for h in hits
                       if not (d / ('h%08d.case.z' % h)).exists()})
        for i in range(0, len(miss), GC.BATCH):
            todo.append((run, key, miss[i:i + GC.BATCH]))
    return todo


def capture(jobs: int = JOBS) -> None:
    MS.use_cases(MYCASES)
    todo = capture_plan()
    first = []
    for run in sorted({t[0] for t in todo}):
        if not GC.base_path(run).exists():
            j = next(t for t in todo if t[0] == run)
            first.append(j)
            todo.remove(j)
    for batch in (first, todo):
        if batch:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                for got in pool.map(_capture_job, batch):
                    say(got)


def case_paths(key: str) -> List[Tuple[str, Path, str]]:
    """(run, path, class) of the key's cases: the captured selection, or
    for P_MobjThinker and the synthetic G_Ticker the saved reference
    calls."""
    MS.use_cases(MYCASES)
    out = []
    if key == MT:
        for p in sorted(MYCASES.glob('*/P_MobjThinker/s*.case.z')):
            out.append((p.parent.parent.name, p,
                        p.name.split('-')[2].split('.')[0]))
        return out
    for run, hit, cls in selection(key):
        p = GC.case_dir(run, key) / ('h%08d.case.z' % hit)
        if p.exists():
            out.append((run, p, cls))
    if key == GT:
        for run, hit, cls in load_selection() + inter_selection():
            p = GC.case_dir(run, key) / ('h%08d.case.z' % hit)
            if p.exists():
                out.append((run, p, cls))
        for p in sorted(MYCASES.glob('*/G_Ticker/s*.case.z')):
            out.append((p.parent.parent.name, p, 'synthetic: ' +
                        p.name.split('-')[1].split('.')[0]))
    return out


# ---------------------------------------------------------------------------
# The reference's own calls (synthetic cases)
# ---------------------------------------------------------------------------

def save_case(case: GC.Case, base: GC.Case, run: str, key: str,
              name: str) -> Path:
    """A reference call on base's entry (with pokes) in the case format:
    the pages of base (so that the entry is base's but the pokes), the
    reader's and the call's writes, xor'ed against the run's base."""
    MS.use_cases(MYCASES)
    rb = GC.load_base(run)
    pages = set(GC._expand_pages(base.header['pages']))
    pages |= GC.reader_pages(case.entry) | GC.reader_pages(case.after)
    for a, n in case.header['writes']:
        pages |= set(range(a >> 8, ((a + max(n, 1) - 1) >> 8) + 1))
    for reg in ('d', 's'):
        v = case.regs_in[reg]
        pages |= {v >> 8, (v + 0xFF) >> 8 & 0xFF}
    pages = sorted(pages)
    payload = bytearray()
    for p in pages:
        a = p << 8
        mine = case.entry.read(a, GC.PAGE)
        theirs = rb.read(a, GC.PAGE)
        payload += bytes(x ^ y for x, y in zip(mine, theirs))
    wbytes = bytearray()
    for a, n in case.header['writes']:
        wbytes += case.after.read(a, n)
    h = dict(case.header, routine=key, run=run,
             image_header=case.entry.header.hex(),
             pages=GC._compress_pages(pages))
    head = json.dumps(h, separators=(',', ':')).encode() + b'\n'
    d = GC.case_dir(run, key)
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(zlib.compress(head + bytes(payload) + bytes(wbytes), 6))
    return p


def ref_call(base: GC.Case, key: str, pokes: Sequence[Tuple[int, bytes]],
             note: str) -> GC.Case:
    """upstream's key run alone on ref816 (gamecap.call_case: --call,
    --call-writes) on base's entry with pokes: a case whose header names
    key and the call's own writes."""
    shim = GC.Case(dict(base.header, routine=key), base.entry, base.after,
                   None)
    return GC.call_case(shim, pokes, note)


def ptr(mem, at: int) -> int:
    return int.from_bytes(mem.read(at, 4), 'little') & 0xFFFFFF


def mobj_class(m: Dict[str, Any]) -> str:
    if m['momx'] or m['momy']:
        return 'xy'
    if m['z'] != m['floorz'] or m['momz']:
        return 'z'
    if m['tics'] == -1:
        return 'ever'
    if m['tics'] == 1:
        return 'end'
    return 'tics'


def state_end_built(case: GC.Case, m: Dict[str, Any]) -> bool:
    """False when the mobj's state ends this tic (tics 1) in a next state
    whose action is not built in the image (the native would stop at its
    DCALL: not eligible)."""
    if m['tics'] != 1 or m.get('state') is None:
        return True
    cur = MS.state_record(case.entry, m['state'].id)
    nxt = MS.state_record(case.entry, cur['next'])
    if not nxt['action']:
        return True
    try:
        key = MS.action_key(nxt['action'])
    except Exception:           # (no ACTTAB entry: not ours to call)
        return False
    return not unbuilt([key])


def mobj_plan() -> List[Tuple[str, Path, int, str]]:
    """(run, P_RunThinkers case, mobj id, class): at most QUOTA[MT],
    spread over the classes, from MT_BASES of the part's P_RunThinkers
    cases."""
    from bridge.fields import R as Ref  # noqa: F401
    bases = spread(case_paths(RT), MT_BASES)
    by: Dict[str, List[Tuple[str, Path, int, str]]] = {}
    for run, p, _ in bases:
        case = GC.load_case(p)
        up = GR.Upstream(case)
        for mid, m in sorted(up.s_in['objects'].get('mobj', {}).items()):
            if m.get('free') or m.get('function') != MT:
                continue
            if not state_end_built(case, m):
                continue
            cls = mobj_class(m)
            by.setdefault(cls, []).append((run, p, mid, cls))
    share = max(1, QUOTA[MT] // max(1, len(by)))
    out: List[Tuple[str, Path, int, str]] = []
    for cls in sorted(by, key=lambda k: (len(by[k]), k)):
        out += spread(by[cls], share)
    rest = [x for v in by.values() for x in v if x not in out]
    out += spread(rest, max(0, QUOTA[MT] - len(out)))
    return out[:QUOTA[MT]]


def _mobj_job(item) -> str:
    run, p, mid, cls = item
    MS.use_cases(MYCASES)
    from bridge.fields import R as Ref
    base = GC.load_case(Path(p))
    name = 's%08d-%04d-%s.case.z' % (base.header['hit'], mid, cls)
    if (GC.case_dir(run, MT) / name).exists():
        return '%s %s: kept' % (run, name)
    up = GR.Upstream(base)
    pointer = up.r_in.ref_address(Ref('mobj', mid, None))
    at = MS.dp_address(base, '_Dp', 0)
    case = ref_call(base, MT, [(at, pointer.to_bytes(4, 'little'))],
                    'mobj %d (%s) of %s h%d' % (mid, cls, run,
                                                base.header['hit']))
    save_case(case, base, run, MT, name)
    return '%s %s: made' % (run, name)


def paused_cases() -> List[Tuple[str, Path]]:
    """The tour's captured level tics (no demo) the paused case comes
    from: the first of the selection."""
    return [(run, p) for run, p, _ in case_paths(GT)
            if run == 'tour' and p.name.startswith('h')][:1]


def _paused_job(item) -> str:
    run, p = item
    MS.use_cases(MYCASES)
    base = GC.load_case(Path(p))
    name = 's%08d-paused.case.z' % base.header['hit']
    if (GC.case_dir(run, GT) / name).exists():
        return '%s %s: kept' % (run, name)
    t = GC.CL.Linkmap()
    mem = base.entry
    gametic = int.from_bytes(mem.read(t.address('g_game65.s:_g_gametic'),
                                      4), 'little')
    slot = t.address('g_game65.s:cmds') + 8 * (gametic & 7)
    pl = t.address('g_game65.s:_g_player') + MS.uconst('UO_PL_CMD')
    have = mem.read(pl, 5)
    cmd = bytes([(have[0] + 0x19) & 0xFF, (have[1] + 0x05) & 0xFF,
                 (have[2] + 0x00) & 0xFF, (have[3] + 0x03) & 0xFF,
                 have[4] ^ 0x02])
    pokes = [(t.address('m_menu65.s:_g_menuactive'), b'\x01\x00'),
             (slot, cmd)]
    case = ref_call(base, GT, pokes, 'paused: menuactive 1, ring slot %d '
                    'not the player\'s command' % (gametic & 7))
    save_case(case, base, run, GT, name)
    return '%s %s: made' % (run, name)


def synth(jobs: int = JOBS) -> None:
    """The reference's own calls: P_MobjThinker's and the paused tic."""
    MS.use_cases(MYCASES)
    plan = mobj_plan()
    work = [('m', x) for x in plan] + [('p', x) for x in paused_cases()]
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_synth_job, work):
            say(got)


def _synth_job(job) -> str:
    kind, item = job
    return _mobj_job(item) if kind == 'm' else _paused_job(item)


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def args() -> Dict[str, Dict[str, Any]]:
    return json.loads((SRC / 'game' / PART / 'args.json').read_text())[
        'entries']


ONGROUND = {'native': 'main:G_ONGROUND',
            'upstream': 'abs:p_user65.s:PU_ONGROUND:2', 'bytes': 1}


def outputs(prep: 'MS.Prepared', spec: Dict[str, Any], m) -> List[str]:
    """The outputs MS.run_one does not read: gw:NAME (a place of GW,
    ggame.inc) as a mobj or none, main:NAME of the tic phase's globals
    (glayout.TGM)."""
    out = []
    up = prep.up
    for item in list(spec.get('out', [])) + [ONGROUND]:
        nv, n = item['native'], item.get('bytes', 2)
        kind, _, name = nv.partition(':')
        at = GL.TGM[name] if kind == 'main' and name in GL.TGM else \
            LL.G[name] if kind == 'main' else GL.TGW[name]
        value = int.from_bytes(bytes(m.main[at:at + n]), 'little')
        raw = up.source(item['upstream'], 'out')
        uv = int.from_bytes(raw, 'little')
        if item.get('as') == 'mobj':
            uv &= 0xFFFFFF
            want = 0xFFFF if uv == 0 else GR.handle_of(
                prep.mf, up.ref(uv, 'out'))
            if value != want:
                out.append('output %s: %04X, upstream\'s %04X' % (
                    item['upstream'], value, want))
        else:
            mask = (1 << (8 * n)) - 1
            if value & mask != uv & mask:
                out.append('output %s: %X != %X' % (
                    item['upstream'], value & mask, uv & mask))
    return out


WAITING = (GL.GS['UNBUILT'], GL.GS['UNBUILTD'])

# The part's stray rule is part mobjstate's shared rule (MS.stray), which
# since wave 6's integration allows TEXTRANS and NUKAGE (P_UpdateSpecials'
# places, compared as canonical state) and the driver's descriptor whoever
# writes it (a load run's far_get of the re-key record): tic.md R2.
def stray(writes, b: RC.Build, header: Dict[str, Any]) -> List[str]:
    return MS.stray(writes, b, header)


def run_one(case: GC.Case, key: str, b: RC.Build,
            fill: int = FILL, profile: Optional[str] = PROFILE
            ) -> Dict[str, Any]:
    spec = args()[key]
    plain = dict(spec, out=[])
    prep = MS.Prepared(case, plain)
    if prep.problems:
        return {'case': case.path.name if case.path else '?',
                'routine': key, 'ok': False,
                'error': 'bridge: ' + '; '.join(prep.problems[:3])}
    extra = GR.tic_main_records(case.entry) + \
        FC.demob_records(prep.up, prep.mf)
    res = MS.run_one(case, plain, b, fill, profile, extra=extra,
                     prep=prep, keep_done=True)
    m = res.pop('_done', None)
    res['routine'] = key
    res['run'] = case.header.get('run')
    stop = res.get('stop')
    if stop and stop[0] in WAITING:
        res['waiting'] = '%s %d' % (G.GS_NAMES.get(stop[0], stop[0]),
                                    stop[1])
    if m is not None:
        diff = outputs(prep, spec, m)
        if diff:
            res['diff'] = (res.get('diff') or []) + diff
            res['ok'] = False
    return res


def _phase_writes(writes, b: RC.Build):
    """The write log split at the load (FC.strays' phases): the writes
    before the driver's dg_ra (the call up to GT_LOAD) and after its
    dg_loads (the continuation and the rest of the tic), and those
    between (the load: nl_setup and the driver)."""
    lab = b.labels
    outside, load = [], []
    phase = 0
    for w in writes:
        if w.storage == 'lc' and w.offset == lab['dg_ra'] and phase == 0:
            phase = 1
        (load if phase == 1 else outside).append(w)
        if w.storage == 'lc' and w.offset == lab['dg_loads'] and phase == 1:
            phase = 2
    return outside, load


HINT_TABLE = ('p_sight65.s:SIGHTHINT', 0x8000)
CS_PREV = ('p_sight65.s:CS_PREV1', 9)   # CS_PREV1, CS_PREV2, CS_PREVR


def setup_rekey(case: GC.Case, gamemap: int) -> bytes:
    """The re-key record of the call's setup (GAME.md 3.6: the hints by
    pool slot and CS_PREV1/2 at the setup's end). The capture has the
    reference's state at the call's entry and return only, and the call
    goes on after the load with the new level's tic, whose sight checks
    change the hints (flow's load runs end at the continuation, where the
    return is the setup's end); ticcap.py's records of these setups are
    empty (an open point of flow's). Nothing between the call's entry and
    the setup's end writes upstream's SIGHTHINT table or CS_PREV (only
    P_CheckSight does, p_sight65.s:138-150, 304-352): so the setup's end
    is the return's memory with the entry's table and CS_PREV, decoded
    (the pool, the new level's, is the return's)."""
    from bridge import upstream as U
    t = GC.CL.Linkmap()
    mem = case.after.copy()
    mem.header = case.after.header
    for name, n in (HINT_TABLE, CS_PREV):
        a = t.address(name)
        mem.write(a, case.entry.read(a, n))
    r = U.Reader(mem, tic=True)
    state = r.read()
    if r.problems:
        raise GR.HarnessError('the setup\'s end: ' + '; '.join(
            r.problems[:3]))
    return FC.rekey_of_state(gamemap, state)


def run_load(case: GC.Case, b: RC.Build, level, fill: int = FILL,
             profile: Optional[str] = PROFILE) -> Dict[str, Any]:
    """A G_Ticker call that loads (part flow's load runs, FC.run_case's
    method): the reference's globals and player at the entry (no level:
    the load makes it, FC.write_prestate), the demo bank, the tic phase's
    globals, the re-key record of the setup (the run's tic reference),
    the I_GetTime values; the driver's routine-with-load mode with
    dg_resume = g_tresume (flow's g_resume, then G_Ticker's action loop);
    the whole canonical state after the call compared with the
    reference's; no stray write (the part's rule, and during the load the
    setup's places, llayout.allowed_writes_setup)."""
    from bridge.port import PortReader, PortError
    from native import gcanon, setupcheck as SC
    up = GR.Upstream(case)
    res: Dict[str, Any] = {'case': case.path.name if case.path else '?',
                           'routine': GT, 'run': case.header.get('run'),
                           'hit': case.header['hit'], 'fill': '%02x' % fill,
                           'profile': profile, 'ok': False, 'load': True}
    if up.r_out.problems:
        res['error'] = 'bridge: ' + '; '.join(up.r_out.problems[:3])
        return res
    table = up.table
    gm_out = case.after.u16(table.address(GR.TIC_GAMEMAP))
    gm_in = up.gamemap if 1 <= up.gamemap <= 9 else gm_out
    mf, header, banks = GR.manifest(gm_out)
    img = G.Image(b, fill, level=level, store=True)
    img.recs += GR.base_records(gm_in)
    pm = G.tracked_memory()
    FC.write_prestate(mf, up.s_in, pm)
    img.recs += G.port_records(pm)
    img.recs += GR.derived(pm, header)
    img.recs += FC.demob_records(up, mf)
    img.recs += GR.tic_main_records(case.entry)
    lab = b.labels
    img.poke_word('dg_entry', lab['G_Ticker'])
    img.poke_label('dg_grp', bytes([MS.entry_group(b, 'G_Ticker')]))
    img.poke_word('dg_resume', lab['g_tresume'])
    img.poke_label('dg_rekey', b'\0')
    img.gtest(GL.GTB['GT_REKEYS'], setup_rekey(case, gm_out))
    times = FC.time_values(case.header['run'])
    img.poke_word('dg_tcount', len(times))
    img.gtest(GL.GTB['GT_TIMES'], len(times).to_bytes(4, 'little') +
              b''.join((v & 0xFFFFFFFF).to_bytes(4, 'little')
                       for v in times))
    work = Path(tempfile.mkdtemp(prefix='tmp-tic-load-', dir=str(BUILD)))
    try:
        start = time.time()
        r = G.run(img, work, GL.MODES['ROUTINE_LOAD'], None,
                  regs=(0, 0, 0, 0x34), banks=banks, profile=profile,
                  write_log=MS.LOG_RANGES)
        res['seconds'] = round(time.time() - start, 2)
        res['lowest_s'] = r.state.get('lowest_s')
        writes = [w for _, w in MS.read_log(work / 'writes.log')] \
            if (work / 'writes.log').exists() else []
        outside, load = _phase_writes(writes, b)
        # (and the load image's own code area: lload.s game_step patches
        # its call, gs_go)
        setup = [(st, bank, lo, hi) for st, bank, lo, hi, _ in
                 LL.allowed_writes_setup(header)] + [
                     ('main', 0, LL.LW_CODE, LL.LW_CODE_END)]
        load = [w for w in load if not any(
            st == w.storage and (st != 'aux' or bank == w.bank) and
            lo <= w.offset < hi for st, bank, lo, hi in setup)]
        st_ = stray(outside + load, b, header)
        res['strays'] = len(st_)
        if st_:
            res['stray_first'] = st_[:4]
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
    try:
        nat = PortReader(mf).read(SC.port_memory(m))
    except PortError as error:
        res['diff'] = ['the port reader: %s' % error]
        return res
    diff = gcanon.compare(up.s_out, nat, 'routine') + MS.native_checks(m)
    res['loads'] = G.card_byte(m, lab['dg_loads'])
    if res['loads'] != 1:
        diff.append('%s loads, not 1' % res['loads'])
    res['diff'] = diff[:12]
    res['ok'] = not diff and not res['strays']
    return res


_LEVEL: List[Any] = []


def _job(job) -> List[Dict[str, Any]]:
    path, obj, key, cls = job
    MS.use_cases(MYCASES)
    b = G.load_build(Path(obj), NAME)
    try:
        case = GC.load_case(Path(path))
        if cls.startswith('load'):
            if not _LEVEL:
                _LEVEL.append(FC.level_build())
            r = run_load(case, b, _LEVEL[0])
        else:
            r = run_one(case, key, b)
    except Exception as error:      # reported per case, never hidden
        r = {'case': Path(path).name, 'routine': key, 'ok': False,
             'error': '%s: %s' % (type(error).__name__, error)}
    r['class'] = cls
    r['case'] = '%s/%s' % (Path(path).parent.parent.name, Path(path).name)
    return [r]


def plan(obj: Path = OUT, sample: int = 1, keys: Sequence[str] = ENTRIES,
         synthetic: bool = True) -> List[Tuple]:
    """The runs: every case of each key, or with sample K every K-th
    (at least one a key); G_Ticker's synthetic and load cases always (with
    synthetic)."""
    out = []
    for key in keys:
        paths = case_paths(key)
        syn = [x for x in paths if x[2].startswith(('synthetic', 'load',
                                                    'ring+intermission'))]
        paths = [x for x in paths if x not in syn]
        if sample > 1:
            paths = spread(paths, max(1, len(paths) // sample))
        if synthetic:
            paths += syn
        out += [(str(p), str(obj), key, cls) for _, p, cls in paths]
    return out


def run_jobs(jobs: Sequence[Tuple], workers: int = JOBS
             ) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if workers <= 1:
        for j in jobs:
            out += _job(j)
        return out
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for got in pool.map(_job, jobs):
            out += got
    return out


def _stats(values: Sequence[int]) -> Dict[str, Any]:
    v = sorted(x for x in values if x is not None)
    return {'median': v[len(v) // 2] if v else None,
            'worst': v[-1] if v else None}


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    entries: Dict[str, Any] = {}
    for key in ENTRIES:
        rs = [r for r in results if r['routine'] == key]
        run = [r for r in rs if not r.get('waiting')]
        bad = [r for r in run if not r.get('ok')]
        waiting: Dict[str, int] = {}
        for r in rs:
            if r.get('waiting'):
                waiting[r['waiting']] = waiting.get(r['waiting'], 0) + 1
        low = [r['lowest_s']['s'] for r in run
               if isinstance(r.get('lowest_s'), dict) and
               r['lowest_s'].get('s') is not None]
        entries[key] = {
            'eligible': len(rs), 'run': len(run), 'failures': len(bad),
            'waiting': waiting,
            'strays': sum(r.get('strays', 0) for r in run),
            'cpu_cycles_f121': _stats([r.get('cpu_cycles') for r in run]),
            'lowest_s': min(low) if low else None,
            'classes': sorted({r.get('class', '') for r in run}),
            'first_failures': [{k: v for k, v in r.items()
                                if k in ('case', 'class', 'diff', 'error',
                                         'stop', 'stray_first', 'ended')}
                               for r in bad[:4]]}
    return {'entries': entries,
            'runs': sum(e['run'] for e in entries.values()),
            'failures': sum(e['failures'] for e in entries.values()),
            'strays': sum(e['strays'] for e in entries.values())}


def check(jobs: int = JOBS, sample: int = 1,
          keys: Sequence[str] = ENTRIES, obj: Path = OUT) -> Dict[str, Any]:
    MS.use_cases(MYCASES)
    results = run_jobs(plan(obj, sample, keys), jobs)
    rep = summarize(results)
    rep['fill'] = '%02x' % FILL
    rep['profile'] = PROFILE
    return rep


# ---------------------------------------------------------------------------
# The planted bugs
# ---------------------------------------------------------------------------

TK = 'game/%s/' % PART
PLANTS = {
    # the walk reads a special's next after its turn: a removed special's
    # link is then its kind's free list (gt_spfree), so the walk follows
    # it (P_RunThinkers' cases with P_RemoveThinkerDelayed)
    'next-after-call': {
        'bugs': [(TK + 'ptick.s', '''        DCALL THTAB
rt_step:''', '''        DCALL THTAB
        lda RT_TH
        ldx RT_TH+1
        cpx #>SPEC_HANDLE
        bcc rt_step
        jsr sp_get
        ldy #SP_THNEXT
        lda (GC_XP),y
        sta RT_NEXT
        iny
        lda (GC_XP),y
        sta RT_NEXT+1
rt_step:''')],
        'key': RT, 'classes': ('P_RemoveThinkerDelayed',)},
    # leveltime + 1 before P_UpdateSpecials (the animated textures and
    # NUKAGE a tic early: P_Ticker's run of 8 tics)
    'leveltime-first': {
        'bugs': [(TK + 'ptick.s', '''        FCALL P_UpdateSpecials
        FCALL P_MapEnd
        inc G_LEVELTIME         ; leveltime++, after the specials
        bne pt_rts
        inc G_LEVELTIME+1
        bne pt_rts
        inc G_LEVELTIME+2
        bne pt_rts
        inc G_LEVELTIME+3
pt_rts: rts''', '''        inc G_LEVELTIME
        bne :+
        inc G_LEVELTIME+1
        bne :+
        inc G_LEVELTIME+2
        bne :+
        inc G_LEVELTIME+3
:       FCALL P_UpdateSpecials
        FCALL P_MapEnd
pt_rts: rts''')],
        'key': PT, 'classes': ()},
    # the ring's command copied while the menu pauses the tic (and no
    # basetic + 1): the synthetic paused tic
    'paused-copy': {
        'bugs': [(TK + 'gtick.s', '''        lda G_MENUACTIVE
        ora G_MENUACTIVE+1
        beq gt_copy''', '''        lda G_MENUACTIVE
        ora G_MENUACTIVE+1
        bra gt_copy''')],
        'key': GT, 'classes': ('synthetic: paused',)},
}


def plant_jobs(name: str, obj: Path) -> List[Tuple]:
    p = PLANTS[name]
    jobs = []
    for _, path, cls in case_paths(p['key']):
        if p['classes'] and not any(c in cls for c in p['classes']):
            continue
        jobs.append((str(path), str(obj), p['key'], cls))
    return jobs


def run_plant(name: str, workers: int = JOBS) -> Dict[str, Any]:
    """The plant built in a temporary game directory, its check's cases
    run on it: caught when one of them fails."""
    p = PLANTS[name]
    tmp = Path(tempfile.mkdtemp(prefix='tmp-tic-plant-', dir=str(BUILD)))
    try:
        obj = build(tmp / 'game', p['bugs'])
        rs = run_jobs(plant_jobs(name, obj), workers)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    failed = [r for r in rs if not r.get('ok') and not r.get('waiting')]
    return {'plant': name, 'check': '%s %s' % (p['key'], ', '.join(
        p['classes']) or 'every case'), 'runs': len(rs),
            'failed': len(failed), 'caught': bool(failed),
            'first': [{k: v for k, v in r.items()
                       if k in ('case', 'diff', 'stop', 'error')}
                      for r in failed[:2]]}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def du_kb(path: Path) -> int:
    r = bounded.run(['du', '-sk', str(path)], timeout=120,
                    stdout=subprocess.PIPE, universal_newlines=True)
    return int(r.stdout.split()[0]) if r.returncode == 0 else -1


def write_report(rep: Dict[str, Any], plants: Optional[Dict[str, Any]] = None
                 ) -> Dict[str, Any]:
    b = load()
    out = {'format': 'game-part-report 1', 'part': PART, 'wave': WAVE,
           'lean': 'the owner\'s rules of 2026-10-02: at most 40 calls a '
                   'routine, fill $A5, f121',
           'image': str(OUT / NAME), 'sizes': sizes(b),
           'checkpoint': rep, 'build_kb': du_kb(OUT)}
    if plants is not None:
        out['plants'] = plants
    elif REPORT.exists():
        old = json.loads(REPORT.read_text())
        if 'plants' in old:
            out['plants'] = old['plants']
    REPORT.write_text(json.dumps(out, indent=1) + '\n')
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--build', action='store_true')
    ap.add_argument('--capture', action='store_true')
    ap.add_argument('--synth', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--plants', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--list', action='store_true',
                    help='print the selection')
    ap.add_argument('--jobs', type=int, default=JOBS)
    ap.add_argument('--sample', type=int, default=1)
    ap.add_argument('--entries', default='')
    a = ap.parse_args(argv)
    why = missing()
    if why:
        say('missing: ' + why)
        return 2
    MS.use_cases(MYCASES)
    if a.build:
        build()
        say(json.dumps(sizes(load()), indent=1))
    if a.list:
        for key in CAPTURED:
            sel = selection(key)
            say('%s: %d calls, classes %s' % (key, len(sel), sorted(
                {c for _, _, c in sel})))
    if a.capture:
        capture(a.jobs)
    if a.synth:
        synth(a.jobs)
    rep = None
    if a.check:
        keys = [k for k in ENTRIES if not a.entries or
                k.split(':')[1] in a.entries.split(',')]
        rep = check(a.jobs, a.sample, keys)
        say(json.dumps(rep, indent=1))
    plants = None
    if a.plants:
        plants = {}
        for name in PLANTS:
            plants[name] = run_plant(name, a.jobs)
            say(json.dumps(plants[name]))
    if a.report or rep is not None or plants is not None:
        if rep is None and REPORT.exists():
            rep = json.loads(REPORT.read_text()).get('checkpoint')
        write_report(rep or {}, plants)
    return 0


if __name__ == '__main__':
    sys.exit(main())
