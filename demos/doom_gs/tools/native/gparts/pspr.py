#!/usr/bin/env python3
"""Part pspr's checkpoint (milestone 10, wave 3; docs/GAME.md 2.4, 3.5;
docs/game-parts/pspr.md), lean (the owner's rules of 2026-10-02): its
image, a sample of its routines' captured calls, its synthetic cases, the
sign extensions' random check, its planted bugs, and
build/native/game/pspr/report.json.

Usage:  python3 tools/native/gparts/pspr.py --build
        python3 tools/native/gparts/pspr.py --capture [--jobs 2]
        python3 tools/native/gparts/pspr.py --check [--jobs 2] [--sample K]
        python3 tools/native/gparts/pspr.py --random [--count N]
        python3 tools/native/gparts/pspr.py --plants
        python3 tools/native/gparts/pspr.py --report

The image (build()): `make -f game.mk part P=pspr` from a scratch copy of
the build files and of the planted bugs' files, every other source from the
tree (game.mk's vpath), into build/native/game/pspr/ (or a temporary
directory).

The selection (at most LIMIT calls a routine, spread to reach as many
branches as the survey shows): P_MovePsprites by the class of its call (the
ACTTAB actions it reached, and whether the player fired in its tic: the
survey's fireWeapon calls), only the classes whose actions are built (no
wfire action: A_FirePistol, A_FireShotgun ...), LIMIT spread over the
classes; tickPsprite, fireWeapon, checkAmmo, P_CheckAmmo and
recursiveSound spread evenly over every run's calls (recursiveSound's
inner calls too: a call of P_RecursiveSound is a whole flood from its
sector, whatever level it is). The captures (--capture):
tools/native/gamecap.py's, into the part's build/native/game/pspr/cases/.

A run (run_one()): routine mode (the case's entry state through the game
manifest into a machine poisoned with $A5, the entry's inputs of
args.json, the call, the state read back and compared with the
reference's return state, gcanon's routine mode, exclusions R1-R7), on
a2vm under f121, with the write log: no CPU write outside the allowed
places (part mobjstate's shared rule, the part's scratch block and the
flood's work stack), every declared output equal, the native-only globals
consistent. One fill and one profile (the lean rules); the other fill and
fastpath are the final integration's.

The synthetic cases (SYNTHETIC), each a captured state with fields poked
and the reference's own call (ref816 --call):
  flood-e1m2, flood-e1m3  recursiveSound from the start sector of the
                deepest flood of the map (level_check.py --flood: E1M2 34,
                E1M3 29, 93 levels) with every two-sided line open (every
                sector's floor 0 and ceiling 128) and validcount new
  empty-weapon  P_MovePsprites with the pistol ready, the attack held and
                no clip: checkAmmo 0, no shot
  gunflash      P_MovePsprites with the rocket launcher ready and the
                attack: fireWeapon, its attack state's A_GunFlash, the
                flash's A_Light1, the noise alert
  saw-idle      P_MovePsprites with the chainsaw ready: its idle sound
  missile-held  P_MovePsprites with the rocket launcher ready, the attack
                held and attackdown set: no shot, the bob

The random check (--random): signExt4 and signExt0 on 100,000 inputs
each (0, +-1, the extremes, then random words) through upstream's helpers
(mathref batch on a captured P_MovePsprites call's machine) and the
native's (pstest.s ps_bulk), compared.
"""

import argparse
import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))

from bridge.port import PortReader, PortWriter, PortError  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, render_check as RC  # noqa: E402
from ref816 import bounded  # noqa: E402
import mobjstate as MS  # noqa: E402  (wave 1's harness: its generic parts)

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'pspr'
WAVE = 3
OUT = GL.GAME / PART
MYCASES = OUT / 'cases'
REPORT = OUT / 'report.json'
FILLS = (0xA5,)
PROFILES = ('f121',)
NAME = 'ptest'
UPSTREAM_BYTES = 894
BUDGET = 1200                   # GAME.md 2.4: upstream 894 x 1.3
MODULES = ('pspr', 'pflood')
TEST_MODULES = ('pstest',)
LIMIT = 40
JOBS = 2

MOVE = 'p_pspr65.s:P_MovePsprites'
TICK = 'p_pspr65.s:tickPsprite'
FIRE = 'p_pspr65.s:fireWeapon'
CHECK = 'p_pspr65.s:checkAmmo'
PCHECK = 'p_pspr65.s:P_CheckAmmo'
FLOOD = 'p_pspr65.s:recursiveSound'
ENTRIES = (MOVE, TICK, FIRE, CHECK, PCHECK, FLOOD)
QUOTA = {MOVE: LIMIT, TICK: 20, FIRE: 20, CHECK: 20, PCHECK: 20,
         FLOOD: LIMIT}


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
    """The part's image (GAME/pspr/ptest.*) from a scratch copy of the
    build files and of the bugs' files (relative to src/native) with each
    bug (file, old, new) applied once; the copy is deleted."""
    tmp = Path(tempfile.mkdtemp(prefix='tmp-pspr-build-', dir=str(BUILD)))
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
        if objs.exists():               # (pspr.inc is no prerequisite)
            for p in objs.glob('*.o'):
                p.unlink()
        cmd = ['make', '-s', '-C', str(src), '-f', 'game.mk', 'part',
               'P=%s' % PART, 'ROOT=%s' % ROOT, 'GAME=%s' % game,
               'PS_TEST=1']         # (pstest.s: part.mk)
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
    """The part's bytes: code (the work stack apart: data in the flood's
    group), against the budget."""
    ms = MS.module_ranges(b)
    by = {m: sum(hi + 1 - lo for _, lo, hi in ms.get(m, ()))
          for m in MODULES + TEST_MODULES}
    stack = inc_value(b, 'FL_BYTES', 'pspr.inc')
    code = sum(by[m] for m in MODULES) - stack
    return {'modules': by, 'work_stack': stack, 'part_bytes': code,
            'budget': BUDGET, 'upstream_bytes': UPSTREAM_BYTES,
            'over_budget_pct': round(100.0 * (code - BUDGET) / BUDGET, 1),
            'segments': sorted({seg for m in MODULES for seg, _, _ in
                                ms.get(m, ())}),
            'flood_group_bytes': sum(hi + 1 - lo for seg, lo, hi in
                                     ms.get('pflood', ()))}


def inc_value(b: RC.Build, name: str, inc: str = 'ggame.inc') -> int:
    """A symbol of the image's generated ggame.inc, or a constant of the
    part's pspr.inc (by its listing: FL_BYTES)."""
    if inc == 'ggame.inc':
        for line in (b.obj / 'gen' / 'ggame.inc').read_text().splitlines():
            f = line.split()
            if len(f) >= 3 and f[0] == name and f[1] == '=':
                return int(f[2].lstrip('$'), 16)
        raise PartError('%s is not in ggame.inc' % name)
    if name == 'FL_BYTES':
        return 512 * 2
    raise PartError(name)


SB_NAMES = {'PS_TGT': 0}


def place(b: RC.Build, name: str) -> int:
    return inc_value(b, 'SB_PSPR') + SB_NAMES[name]


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


def eligible(run: str, key: str, hit: int) -> List[str]:
    """The dispatch targets the call reached that are not built in the
    part's image: empty when the call is eligible."""
    built = set(GL.built_set(extra=[PART]))
    return [t for t in reached(run, key, hit)
            if (GL.owner_of(t) or 'core') not in built | {'core'}]


def move_class(run: str, hit: int, fired: set) -> str:
    sv = survey(run)
    tic = sv['routines'][MOVE]['tic'][hit - 1]
    acts = sorted(t.split(':')[1] for t in reached(run, MOVE, hit))
    return '+'.join(acts or ['none']) + ('+fire' if tic in fired else '')


def calls_of(key: str) -> List[Tuple[str, int, str]]:
    """(run, hit, class) of every eligible call of key in the runs."""
    out = []
    for run in GC.RUNS:
        sv = survey(run)
        if not sv:
            continue
        n = sv['routines'].get(key, {}).get('calls', 0)
        fired = set(sv['routines'].get(FIRE, {}).get('tic', []))
        if key == FLOOD:
            # the survey counts more calls of recursiveSound than ref816's
            # --capture does (demo1: 3,421 against 3,368; the call log also
            # counts some recursive entries --capture does not): only the
            # first 90%, every one of which --capture reaches (a capture
            # hit k is a whole flood from its sector whatever its level)
            n = n * 9 // 10
        for h in range(1, n + 1):
            if eligible(run, key, h):
                continue
            cls = move_class(run, h, fired) if key == MOVE else \
                key.split(':')[1]
            out.append((run, h, cls))
    return out


def selection(key: str) -> List[Tuple[str, int, str]]:
    """At most QUOTA[key] calls: P_MovePsprites's spread over its classes
    (each class its share, every class at least one), the others spread
    over every run's calls."""
    calls = calls_of(key)
    quota = QUOTA[key]
    if key != MOVE:
        return spread(calls, quota)
    by: Dict[str, List[Tuple[str, int, str]]] = {}
    for c in calls:
        by.setdefault(c[2], []).append(c)
    share = max(1, quota // max(1, len(by)))
    chosen: List[Tuple[str, int, str]] = []
    for cls in sorted(by):
        chosen += spread(by[cls], share)
    rest = [c for c in calls if c not in set(chosen)]
    chosen += spread(rest, max(0, quota - len(chosen)))
    return sorted(chosen[:quota], key=lambda c: (GC.RUNS.index(c[0]), c[1]))


def _capture_job(job) -> str:
    run, key, hits = job
    MS.use_cases(MYCASES)
    tics = GC.survey_of(run)['routines'][key]['tic']
    made = GC.capture(run, key, hits, tics, say=lambda *a: None)
    return '%s %s: %d made of %d' % (run, key, len(made), len(hits))


def capture_plan() -> List[Tuple[str, str, List[int]]]:
    """(run, key, hits) of the cases the part's directory lacks: the
    selection, and for the synthetic cases P_MovePsprites calls of the tour
    on E1M2 and E1M3 (its calls spread)."""
    MS.use_cases(MYCASES)
    want: Dict[Tuple[str, str], List[int]] = {}
    for key in ENTRIES:
        for run, h, _ in selection(key):
            want.setdefault((run, key), []).append(h)
    n = survey('tour')['routines'][MOVE]['calls']
    want.setdefault(('tour', MOVE), []).extend(
        h for h in spread(list(range(1, n + 1)), 24))
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
    MS.use_cases(MYCASES)
    out = []
    for run, hit, cls in selection(key):
        p = GC.case_dir(run, key) / ('h%08d.case.z' % hit)
        if p.exists():
            out.append((run, p, cls))
    return out


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def uconst(name: str) -> int:
    return MS.uconst(name)


def sym(name: str) -> int:
    return GC.CL.Linkmap().address(name)


def exported(name: str) -> int:
    """A symbol of the release's link map (its exported table)."""
    if not hasattr(exported, 'd'):
        exported.d = json.loads((BUILD / 'linkmap.json').read_text())[
            'game']['exported']
    return exported.d[name]


def psp_number(x: int) -> int:
    base = (exported('_g_player') + uconst('UO_PL_PSPRITES')) & 0xFFFF
    k, r = divmod((x & 0xFFFF) - base, uconst('US_PSP'))
    if r or k not in (0, 1):
        raise GR.HarnessError('$%04X is no psprite' % x)
    return k


def sector_number(case: GC.Case, x: int, dbr: int) -> int:
    base = int.from_bytes(case.entry.read(exported('_g_sectors'), 4),
                          'little') & 0xFFFFFF
    k, r = divmod((dbr << 16 | (x & 0xFFFF)) - base, uconst('US_SEC'))
    n = case.entry.u16(exported('_g_numsectors'))
    if r or not 0 <= k < n:
        raise GR.HarnessError('$%02X:%04X is no sector' % (dbr, x))
    return k


class Prep:
    """A case's reference side and its native inputs (mobjstate.Prepared's,
    with the part's destinations sb: and conversions psp and sector)."""

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
            data = up.source(item['from'])
            kind = item.get('as')
            if kind == 'psp':
                data = bytes([psp_number(int.from_bytes(data, 'little'))])
            elif kind == 'sector':
                data = bytes([sector_number(case, int.from_bytes(
                    data, 'little'), case.regs_in['dbr'])])
            elif kind:
                data = MS._convert(up, self.mf, data, kind)
            to = item['to']
            n = item.get('bytes', len(data))
            if to in ('a', 'x', 'y'):
                regs['axy'.index(to)] = data[0]
            elif to.startswith('zp:'):
                self.zp.append((GR.zp_address(to[3:]),
                                data[:n].ljust(n, b'\0')))
            elif to.startswith('sb:'):
                self.zp.append((place(b, to[3:]), data[:n].ljust(n, b'\0')))
            else:
                raise GR.HarnessError('an input destination %r' % to)
        self.regs = regs


def allowed_extra(b: RC.Build) -> List[Tuple[int, int]]:
    """The part's own places beyond mobjstate's shared rule: its scratch
    block and the flood's work stack (in its group's slot)."""
    sb = inc_value(b, 'SB_PSPR')
    st = b.labels['ps_stack']
    return [(sb, sb + inc_value(b, 'SB_PSPR_SIZE')),
            (st, st + inc_value(b, 'FL_BYTES', 'pspr.inc'))]


def stray(writes, b: RC.Build, header: Dict[str, Any]) -> List[str]:
    extra = allowed_extra(b)
    rest = [w for w in writes if not (w.storage == 'main' and any(
        lo <= w.offset < hi for lo, hi in extra))]
    return MS.stray(rest, b, header)


def run_one(prep: Prep, b: RC.Build, fill: int, profile: Optional[str]
            ) -> Dict[str, Any]:
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
    work = Path(tempfile.mkdtemp(prefix='tmp-pspr-run-', dir=str(BUILD)))
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
    return res


def outputs(prep: Prep, b: RC.Build, m) -> List[str]:
    lab = b.labels
    regs = {'a': G.card_byte(m, lab['dg_ra']),
            'x': G.card_byte(m, lab['dg_rx']),
            'y': G.card_byte(m, lab['dg_ry'])}
    out = []
    for item in prep.spec.get('out', []):
        nv, n = item['native'], item.get('bytes', 2)
        value = regs[nv]
        uv = int.from_bytes(prep.up.source(item['upstream'], 'out'),
                            'little')
        mask = (1 << (8 * n)) - 1
        if value & mask != uv & mask:
            out.append('output %s: %X != %X' % (item['upstream'],
                                                value & mask, uv & mask))
    return out


# ---------------------------------------------------------------------------
# The synthetic cases: a captured state poked, the reference's own call
# ---------------------------------------------------------------------------

FRAC = 0x10000
STATE_SIZE = 16                 # info.inc's STATEADDR: states + 16 * C
FLOOD_STARTS = {2: 34, 3: 29}   # level_check.py --flood (LEVELS.md 5.5)


def u16(v: int) -> bytes:
    return (v & 0xFFFF).to_bytes(2, 'little')


def s32(v: int) -> bytes:
    return (v & 0xFFFFFFFF).to_bytes(4, 'little')


def player() -> int:
    return exported('_g_player')


def psp_pokes(state: int, tics: int) -> List[Tuple[int, bytes]]:
    """The weapon psprite at state with tics (a far pointer into states)."""
    p = player() + uconst('UO_PL_PSPRITES')
    st = exported('states') + STATE_SIZE * state
    return [(p + uconst('UO_PSP_STATE'), s32(st)),
            (p + uconst('UO_PSP_TICS'), u16(tics))]


def ready_pokes(weapon: str, attack: bool, attackdown: int = 0,
                ammo: Optional[Tuple[str, int]] = None
                ) -> List[Tuple[int, bytes]]:
    """The player with weapon ready (its ready state, 1 tic left), alive,
    no change pending, the attack button as given."""
    pl = player()
    w = uconst('UC_WP_' + weapon)
    ready = {'PISTOL': 'UC_S_PISTOL', 'MISSILE': 'UC_S_MISSILE',
             'CHAINSAW': 'UC_S_SAW'}[weapon]
    cmd = pl + uconst('UO_PL_CMD') + uconst('UO_TC_BUTTONS')
    out = psp_pokes(uconst(ready), 1)
    out += [(pl + uconst('UO_PL_READYWEAPON'), u16(w)),
            (pl + uconst('UO_PL_PENDINGWEAPON'), u16(uconst('UC_WP_NOCHANGE'))),
            (pl + uconst('UO_PL_HEALTH'), u16(100)),
            (pl + uconst('UO_PL_PLAYERSTATE'), u16(uconst('UC_PST_LIVE'))),
            (pl + uconst('UO_PL_ATTACKDOWN'), u16(attackdown)),
            (cmd, bytes([uconst('UC_BT_ATTACK') if attack else 0]))]
    if ammo:
        out.append((pl + uconst('UO_PL_AMMO') + 2 * uconst('UC_AM_' + ammo[0]),
                    u16(ammo[1])))
    return out


def _tour_case(gamemap: Optional[int] = None) -> GC.Case:
    """A captured P_MovePsprites call of the tour (on gamemap)."""
    MS.use_cases(MYCASES)
    d = GC.case_dir('tour', MOVE)
    for p in sorted(d.glob('h*.case.z')):
        c = GC.load_case(p)
        if gamemap is None or GR.Upstream(c).gamemap == gamemap:
            return c
    raise PartError('no tour P_MovePsprites case on E1M%s (python3 '
                    'tools/native/gparts/pspr.py --capture)' % gamemap)


def _move_case(pokes, note: str) -> GC.Case:
    return GC.call_case(_tour_case(1), pokes, note)


def flood_case(gamemap: int) -> GC.Case:
    """recursiveSound(the deepest flood's start, 0) on a tour state of the
    map: every sector's floor 0 and ceiling 128 (every two-sided line
    open), validcount + 1, RS_TGT the player's mobj."""
    base = _tour_case(gamemap)
    mem = base.entry
    secs = int.from_bytes(mem.read(exported('_g_sectors'), 4),
                          'little') & 0xFFFFFF
    n = mem.u16(exported('_g_numsectors'))
    size = uconst('US_SEC')
    pokes = []
    for i in range(n):
        a = secs + i * size
        pokes += [(a + uconst('UO_SEC_FLOORHEIGHT'), s32(0)),
                  (a + uconst('UO_SEC_CEILINGHEIGHT'), s32(128 * FRAC))]
    vc = exported('validcount')
    pokes.append((vc, u16(mem.u16(vc) + 1)))
    mo = mem.read(player() + uconst('UO_PL_MO'), 4)
    pokes.append((sym('p_pspr65.s:RS_TGT'), mo))
    start = secs + FLOOD_STARTS[gamemap] * size
    regs = {'a': 0, 'x': start & 0xFFFF, 'y': 0, 'dbr': start >> 16}
    entry = mem.copy()
    entry.header = mem.header
    for a, d in pokes:
        entry.write(a, d)
    after, call = MS.ref_call(entry, FLOOD, (), regs)
    call = dict(call, start=dict(call['start'], **regs)) \
        if 'start' in call else call
    hdr = dict(base.header, routine=FLOOD, note='flood-e1m%d' % gamemap,
               call=call)
    return GC.Case(hdr, entry, after, None)


def synthetic_case(name: str) -> GC.Case:
    if name.startswith('flood-e1m'):
        return flood_case(int(name[-1]))
    if name == 'empty-weapon':
        return _move_case(ready_pokes('PISTOL', True, ammo=('CLIP', 0)),
                          name)
    if name == 'gunflash':
        return _move_case(ready_pokes('MISSILE', True, ammo=('MISL', 5)),
                          name)
    if name == 'saw-idle':
        return _move_case(ready_pokes('CHAINSAW', False), name)
    if name == 'missile-held':
        return _move_case(ready_pokes('MISSILE', True, attackdown=1,
                                      ammo=('MISL', 5)), name)
    raise PartError('no synthetic case %s' % name)


def synthetic_took(name: str, case: GC.Case) -> List[str]:
    """What the reference's own call must show for the case to be the one
    it is named for."""
    a, b_ = case.entry, case.after
    pl = player()
    out = []
    vc = exported('validcount')
    if name.startswith('flood'):
        secs = int.from_bytes(a.read(exported('_g_sectors'), 4),
                              'little') & 0xFFFFFF
        n = a.u16(exported('_g_numsectors'))
        off = uconst('UO_SEC_VALIDCOUNT')
        stamped = sum(1 for i in range(n) if b_.u16(
            secs + i * uconst('US_SEC') + off) == a.u16(vc))
        if stamped < n // 2:
            out.append('only %d of %d sectors flooded' % (stamped, n))
    elif name in ('empty-weapon', 'missile-held'):
        if a.u16(vc) != b_.u16(vc):
            out.append('a noise alert')
    elif name == 'gunflash':
        if a.u16(vc) == b_.u16(vc):
            out.append('no noise alert')
        if b_.u16(pl + uconst('UO_PL_EXTRALIGHT')) != 1:
            out.append('no A_Light1')
    return ['synthetic %s: %s' % (name, x) for x in out]


SYNTHETIC = ('flood-e1m2', 'flood-e1m3', 'empty-weapon', 'gunflash',
             'saw-idle', 'missile-held')


def synthetic_key(name: str) -> str:
    return FLOOD if name.startswith('flood') else MOVE


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
    the entry, its class, the image, fills, profiles."""
    kind, what, key, path, obj, fills, profiles = job
    MS.use_cases(MYCASES)
    b = _build(obj)
    label = ('%s/%s' % (Path(what).parent.parent.name, Path(what).name)
             if kind == 'case' else what)
    try:
        case = GC.load_case(Path(what)) if kind == 'case' else \
            synthetic_case(what)
        spec = GR.all_args()[key]
        prep = Prep(case, spec, b)
    except Exception as error:              # reported, never hidden
        return [{'ok': False, 'kind': kind, 'entry': key, 'path': path,
                 'case': label,
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
            r.update(kind=kind, entry=key, path=path, case=label)
            out.append(r)
    return out


def plan(obj: Path = OUT, fills=FILLS, profiles=PROFILES, sample: int = 1,
         entries: Optional[Sequence[str]] = None,
         synthetic_names: Sequence[str] = SYNTHETIC
         ) -> Tuple[List[Tuple], Dict[str, Any]]:
    o = str(obj)
    jobs: List[Tuple] = []
    elig: Dict[str, Any] = {}
    for key in ENTRIES:
        if entries and key not in entries:
            continue
        cases = case_paths(key)
        e = elig.setdefault(key, {'selected': len(selection(key)),
                                  'captured': len(cases)})
        e['calls'] = {run: survey(run)['routines'].get(key, {}).get(
            'calls', 0) for run in GC.RUNS}
        for run, p, cls in cases[::sample]:
            jobs.append(('case', str(p), key, cls, o, tuple(fills),
                         tuple(profiles)))
    for name in synthetic_names:
        key = synthetic_key(name)
        if entries and key not in entries:
            continue
        jobs.append(('synthetic', name, key, 'synthetic: ' + name, o,
                     tuple(fills), tuple(profiles)))
    return jobs, elig


def run_jobs(jobs: Sequence[Tuple], workers: int = JOBS
             ) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if workers <= 1:
        for j in jobs:
            out += _job(j)
        return out
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for got in pool.map(_job, jobs, chunksize=1):
            out += got
    return out


def check(jobs: int = JOBS, sample: int = 1, entries=None,
          synthetic_names: Sequence[str] = SYNTHETIC, rebuild: bool = True
          ) -> Dict[str, Any]:
    if rebuild:
        build()
    b = load()
    js, elig = plan(OUT, FILLS, PROFILES, sample, entries, synthetic_names)
    start = time.time()
    res = run_jobs(js, jobs)
    rep = {'entries': MS.summarize(res), 'selection': elig,
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
# The random check: signExt4, signExt0 (GAME.md 2.4 "Arithmetic")
# ---------------------------------------------------------------------------

BULK_IN, BULK_OUT = 93, 94
BULK_ROOM = 0xC000 - 0x0200
EDGES = (0, 1, -1, 2, -2, 0x7FFF, -0x8000, 0x7FFE, -0x7FFF, 0x8000, 0xFFFF,
         0x00FF, 0x0100, 0x7F, 0x80, -0x80, -0x81)


def word_inputs(n: int, seed: int = 1) -> List[int]:
    rnd = random.Random(seed)
    out = [v & 0xFFFF for v in EDGES]
    while len(out) < n:
        out.append(rnd.randrange(0x10000))
    return out[:n]


def native_bulk(b: RC.Build, mode: int, values: Sequence[int]) -> List[bytes]:
    per = min(BULK_ROOM // 2, BULK_ROOM // 4)
    out: List[bytes] = []
    for start in range(0, len(values), per):
        chunk = values[start:start + per]
        img = G.Image(b, 0xA5, store=False)
        img.aux(BULK_IN, 0x0200, b''.join(u16(v) for v in chunk))
        work = Path(tempfile.mkdtemp(prefix='tmp-pspr-bulk-', dir=str(BUILD)))
        try:
            k = len(chunk)
            r = G.run(img, work, GL.MODES['ROUTINE'], 'ps_bulk',
                      regs=(mode, k & 0xFF, k >> 8, 0x34), banks=[BULK_OUT])
            if r.ended() != 'halt':
                raise PartError('ps_bulk ended %s' % r.ended())
            m = G.load_snapshot(work / 'done.img')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        data = bytes(m.aux[BULK_OUT][0x0200:0x0200 + 4 * k])
        out += [data[i:i + 4] for i in range(0, len(data), 4)]
    return out


def random_check(n: int = 100_000, seed: int = 1,
                 b: Optional[RC.Build] = None) -> Dict[str, Any]:
    """signExt4 and signExt0 on n inputs each: upstream's (mathref batch
    on a captured P_MovePsprites call's machine: C in, _Dp[4-7] or
    _Dp[0-3] out) against the native (ps_bulk: M_B or M_A)."""
    import sight as SG
    case = _tour_case(None)
    b = b or load()
    vals = word_inputs(n, seed)
    recs = b''.join(u16(v) for v in vals)
    out: Dict[str, Any] = {'inputs': len(vals), 'seed': seed,
                           'edges': len(EDGES)}
    for mode, name, dp in ((0, 'signExt4', 4), (1, 'signExt0', 0)):
        pc = sym('p_pspr65.s:' + name)
        at = MS.dp_address(case, '_Dp', dp)
        ups = SG.mathref(case, name, pc, ['a'], ['%06X 4' % at], recs, 4)
        nat = native_bulk(b, mode, vals)
        model = [s32(v - 0x10000 if v & 0x8000 else v) for v in vals]
        bad = [(v, u.hex(), m_.hex()) for v, u, m_ in zip(vals, ups, nat)
               if u != m_]
        out[name] = {'compared': min(len(ups), len(nat)),
                     'different': len(bad) + abs(len(ups) - len(nat)),
                     'first': bad[:5],
                     'upstream_is_the_sign_extension': sum(
                         1 for u, m_ in zip(ups, model) if u == m_)}
    return out


# ---------------------------------------------------------------------------
# The planted bugs (lean: three, the mistakes most likely to happen), each
# in a scratch copy of the part's sources, its image in a temporary
# directory, run on its check
# ---------------------------------------------------------------------------

PS = 'game/%s/' % PART
PLANTS: Dict[str, Dict[str, Any]] = {
    # a work stack of 80 (GAME.md 2.4's row): E1M2's flood (93 levels)
    # stops
    'stack-80': {'check': 'flood-e1m2', 'bugs': [
        (PS + 'pspr.inc', 'FL_DEPTH = 512', 'FL_DEPTH = 512\n'
         'FL_PLANT = 80                  ; (planted: a stack of 80)'),
        (PS + 'pflood.s', """        lda PS_SP+1
        cmp #>FL_DEPTH
        bcs @deep""", """        lda PS_SP+1
        bne @deep
        lda PS_SP
        cmp #FL_PLANT
        bcs @deep""")]},
    # the bob's x from the sine (GAME.md 2.4's row: the bob's x from the
    # wrong table): A_WeaponReady's bob, in the captured P_MovePsprites
    # calls of a moving player
    'bob-x-sine': {'check': MOVE, 'bugs': [
        (PS + 'pspr.s', """        jsr finecosine          ; cos (32 bits)""",
         """        jsr finesine            ; (planted: the sine)""")]},
    # a closed opening (openrange 0) let through: the flood passes closed
    # doors: the captured floods
    'opening-zero-open': {'check': FLOOD, 'bugs': [
        (PS + 'pflood.s', """        lda GT_6
        beq @shut
        sec
        rts""", """        sec                     ; (planted: 0 is open)
        rts""")]},
}


def plant_jobs(plant: Dict[str, Any], obj: Path, limit: int = 40
               ) -> List[Tuple]:
    check_ = plant['check']
    if check_ in SYNTHETIC:
        js, _ = plan(obj, (0xA5,), (None,), entries=[synthetic_key(check_)],
                     synthetic_names=[check_])
        return [j for j in js if j[0] == 'synthetic']
    js, _ = plan(obj, (0xA5,), (None,), entries=[check_], synthetic_names=())
    return spread(js, limit)


def run_plant(name: str) -> Dict[str, Any]:
    p = PLANTS[name]
    tmp = Path(tempfile.mkdtemp(prefix='tmp-pspr-plant-', dir=str(BUILD)))
    try:
        obj = build(tmp / 'game', p['bugs'])
        res = run_jobs(plant_jobs(p, obj), JOBS)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
        _BUILDS.clear()
    bad = [r for r in res if not r.get('ok')]
    return {'check': p['check'], 'runs': len(res), 'failed': len(bad),
            'caught': bool(bad),
            'first': [{k: r.get(k) for k in ('case', 'path', 'diff', 'error',
                                             'ended', 'stop') if r.get(k)}
                      for r in bad[:2]]}


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
        out['random'] = rnd
    out['build_kb'] = MS.du_kb(OUT)
    out['notes'] = [
        'lean checkpoint (the owner\'s rules of 2026-10-02): at most %d '
        'captured calls a routine, one fill ($A5), f121 only; the other '
        'fill and fastpath are the final integration\'s' % LIMIT,
        'clock: the call\'s time under f121 (fabric clocks); cpu_cycles: '
        'the W65C02S\'s cycles; every slot empty at the call (an upper '
        'bound)',
        'paths: P_MovePsprites by the ACTTAB actions its call reached and '
        '+fire when the player fired in its tic; synthetic cases by name',
        'sizes: pspr.s and pflood.s, the work stack (1,024 B of data in '
        'the flood\'s group) apart; pstest.s is test-only (the driver\'s '
        'area)']
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=1, default=str) + '\n')
    return REPORT


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--random', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--jobs', type=int, default=JOBS)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--count', type=int, default=100_000)
    parser.add_argument('--entries', default='')
    parser.add_argument('--synthetic', default=None,
                        help='only these synthetic cases (comma list)')
    args = parser.parse_args(argv)
    status = 0
    if args.build:
        print(json.dumps(sizes(load(build())), indent=1))
    if args.capture:
        capture(args.jobs)
    if args.check:
        names = SYNTHETIC if args.synthetic is None else tuple(
            x for x in args.synthetic.split(',') if x)
        rep = check(args.jobs, args.sample,
                    [e for e in args.entries.split(',') if e] or None, names)
        write_report(rep)
        for k, e in sorted(rep['entries'].items()):
            print('%-34s %4d cases %4d runs %3d failed  cycles %s  S %s' % (
                k, len(e['cases']) if isinstance(e['cases'], (list, set))
                else e['cases'], e['runs'], e['failures'],
                e['cpu_cycles'].get('f121'), e['lowest_s']))
            for f in e['first_failures'][:3]:
                print('   ', json.dumps(f, default=str)[:600])
        print('runs %d, failures %d, stray writes %d, %d s' % (
            rep['runs'], rep['failures'], rep['strays'], rep['seconds']))
        status |= 1 if rep['failures'] or rep['strays'] else 0
    if args.random:
        r = random_check(args.count)
        print(json.dumps(r, indent=1))
        write_report({}, rnd=r)
        status |= 1 if r['signExt4']['different'] or \
            r['signExt0']['different'] else 0
    if args.plants:
        pl = {}
        for n in PLANTS:
            pl[n] = run_plant(n)
            print('%-20s %s' % (n, ('caught: %d of %d runs fail: %s' % (
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
