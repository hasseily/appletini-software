#!/usr/bin/env python3
"""Part lines's checkpoint (milestone 10, docs/GAME.md 2.4 row lines, 3.5;
docs/game-parts/lines.md): routine mode on the part's entries, its
synthetic cases on the nine maps and its planted bugs.

Usage:  python3 tools/native/gparts/lines.py --capture [--runs demo3,...]
        python3 tools/native/gparts/lines.py --synthetic [--jobs 2]
        python3 tools/native/gparts/lines.py --check [--jobs 2]
                [--keys FILE:LABEL,...] [--sample K] [--json FILE]
        python3 tools/native/gparts/lines.py --plants [--keys NAME,...]
        python3 tools/native/gparts/lines.py --eligible
        python3 tools/native/gparts/lines.py --report

Everything it writes is under build/native/game/lines/ (the part's own
directory): the cases (cases/RUN/ROUTINE/hNNNNNNNN.case.z and each run's
base.ram.z, through tools/native/gamecap.py with its case directory pointed
here), the synthetic calls (synthetic/), report.json. The shared outputs
(build/native/game/shared/: the survey, the includes, the manifests) are
read only.

The run machinery (the reference's states, the native pre-state through
the port writer, the runs and the write log) is part secfind's
(tools/native/gparts/secfind.py: Ref, Prep, Native, check_writes, ref_call,
MapBase, Shared), imported as wave 1's integration asked; this tool adds the
part's eligibility, choice, paths, outputs (the carry), sound events and
synthetic cases.

--capture: every eligible call of the part's entries in the survey's runs
(GAME.md 3.5 step 6: a call is eligible when every dispatch target it
reached is built: the integrated waves' parts and this one; until waves 3
and 4 fill LSTAB those are the calls with no handler, a light or an exit),
so that each call's path is known; and the tour's P_UpdateSpecials every
TOUR_STEP-th call, the in-play states of the nine maps for the synthetic
calls.

--synthetic: the synthetic calls on each of the nine maps (ref816 --call on
the in-play state with the arguments poked): P_ChangeSwitchTexture on every
line whose front side shows a switch texture, once and again (a button),
and on lines without one; the button list with the line pressed already,
with a slot taken, full (I_Error); P_UseSpecialLine on the exits (11, 51)
by the player alive, dead (health 0 and below) and by a monster, and on
lines with no special of usetab or no tag; lnExit itself; P_CrossSpecialLine
of a light line (special 35: walk once) by the player from each side and
by a monster, and of 97 by a missile (the shots that trigger nothing).

--check: the chosen captured calls (GAME.md 2.4's minimums: every eligible
call of an entry with fewer than 300, else 300 spread evenly and every
call whose path no chosen call takes) and every synthetic call, from both
poisoned machines ($A5, $5A), under f121 and fastpath, compared with
ref816 in gcanon.py's routine mode (exclusions R1-R6 only), the declared
outputs of src/native/game/lines/args.json compared (with the carry), the
sound events compared (R6), no stray write. Writes report.json.

--plants: each planted bug of GAME.md 2.4 built from a scratch copy of the
part's sources in a temporary directory (deleted), run on its named check,
which must fail.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))

import secfind as SF  # noqa: E402  (wave 1's machinery)
from bridge.port import PortReader  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL  # noqa: E402
from ref816 import bounded, calls as CL, title  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'lines'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
SYN = OUT / 'synthetic'
REPORT = OUT / 'report.json'
ARGS = SRC / 'game' / PART / 'args.json'
PART_SRC = SRC / 'game' / PART
IMAGE = 'ptest'
GC.CASES = CASES                # the part's own case directory (secfind's
#                                 import pointed it at secfind's)

USE = 'p_switch65.s:P_UseSpecialLine'
CROSS = 'p_switch65.s:P_CrossSpecialLine'
FIND = 'p_switch65.s:findSpecial'
CHANGE = 'p_switch65.s:P_ChangeSwitchTexture'
EXIT = 'p_switch65.s:lnExit'
ENTRIES = (USE, CROSS, FIND, CHANGE)
ALL_KEYS = ENTRIES + (EXIT,)            # lnExit: synthetic calls only
BASE_KEY = 'p_spec65.s:P_UpdateSpecials'    # the synthetic calls' states
TOUR_STEP = 20
MINIMUM = 300
FILLS = SF.FILLS
PROFILES = SF.PROFILES
BATCH = 120
RUN_CYCLES = SF.RUN_CYCLES
NOTAGS = SF.NOTAGS              # p_spec65.s's notags (checked by secfind)
MISSILES = ('UC_MT_ROCKET', 'UC_MT_TROOPSHOT', 'UC_MT_BRUISERSHOT')
SYN_FORMAT = 'lines-synthetic 1'


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


def uconst() -> Dict[str, int]:
    return SF.uconst()


# ---------------------------------------------------------------------------
# What the part needs of build/
# ---------------------------------------------------------------------------

def missing() -> Optional[str]:
    """Why the checkpoint cannot run (None: it can)."""
    return SF.missing()


def build(game: Optional[Path] = None, source: Path = SRC) -> Path:
    """The part's test image (make -f game.mk part P=lines); its
    directory."""
    variables = ['P=%s' % PART]
    if game is not None:
        variables.append('GAME=%s' % game)
    G.make('part', variables, source)
    return (game or GL.GAME) / PART


# ---------------------------------------------------------------------------
# Upstream's tables (p_switch65.s's spectab, read from the release's memory)
# ---------------------------------------------------------------------------

def lstab_names() -> List[str]:
    """LSTAB's targets in their order (an entry's number is its index + 1)."""
    return GL.dispatch_entries()['LSTAB']


def upstream_spectab(mem) -> Dict[str, List[Tuple[int, str, int, int]]]:
    """usetab's and crosstab's entries in a memory of the release: (special,
    the handler's file:label, argument, mode)."""
    t = CL.Linkmap()
    by_addr = {t.address(k) & 0xFFFF: k for k in lstab_names()}
    out: Dict[str, List[Tuple[int, str, int, int]]] = {}
    for name, lo, hi in (('usetab', 'usetab', 'usetab_end'),
                         ('crosstab', 'crosstab', 'crosstab_end')):
        a, end = t.address('p_switch65.s:' + lo), t.address(
            'p_switch65.s:' + hi)
        rows = []
        while a < end:
            sp, fn, arg, mode = (mem.u16(a + 2 * k) for k in range(4))
            rows.append((sp, by_addr[fn], arg, mode))
            a += 8
        out[name] = rows
    return out


# ---------------------------------------------------------------------------
# Eligibility and the calls (GAME.md 3.5 step 6, 2.4's minimums)
# ---------------------------------------------------------------------------

def built() -> Set[str]:
    return set(GL.built_set(extra=[PART]))


def eligible_calls(key: str) -> Tuple[List[Tuple[str, int, int]],
                                      Dict[str, int]]:
    """The eligible calls of an entry over the survey's runs, (run, hit,
    tic), and the waiting ones by the target they wait for."""
    ok_parts = built()
    out: List[Tuple[str, int, int]] = []
    waiting: Dict[str, int] = {}
    for run in GC.RUNS:
        sv = GC.survey_of(run)
        r = sv['routines'].get(key) if sv else None
        if not r:
            continue
        targets = sv['targets']
        for hit in range(1, r['calls'] + 1):
            miss = []
            for i in r['reached'].get(str(hit), []):
                owner = GL.owner_of(targets[i])
                if owner != 'core' and owner not in ok_parts:
                    miss.append(targets[i])
            if miss:
                for m in miss:
                    waiting[m] = waiting.get(m, 0) + 1
            else:
                out.append((run, hit, r['tic'][hit - 1]))
    return out, waiting


def case_path(run: str, key: str, hit: int) -> Path:
    return GC.case_dir(run, key) / ('h%08d.case.z' % hit)


def base_calls() -> List[Tuple[str, int, int]]:
    sv = GC.survey_of('tour')
    tics = sv['routines'][BASE_KEY]['tic'] if sv else []
    return [('tour', h, tics[h - 1]) for h in range(1, len(tics) + 1,
                                                    TOUR_STEP)]


def capture(keys: Sequence[str] = ENTRIES, runs: Sequence[str] = GC.RUNS,
            batch: int = BATCH, bases: bool = True) -> int:
    """Every eligible call's case (those made are kept), and the bases."""
    want: Dict[Tuple[str, str], Dict[int, int]] = {}
    for key in keys:
        for run, hit, tic in eligible_calls(key)[0]:
            want.setdefault((run, key), {})[hit] = tic
    if bases:
        for run, hit, tic in base_calls():
            want.setdefault((run, BASE_KEY), {})[hit] = tic
    made = 0
    for (run, key), hits in sorted(want.items()):
        if run not in runs:
            continue
        todo = sorted(h for h in hits if not case_path(run, key, h).exists())
        if not todo:
            continue
        top = max(hits)
        tics = [hits.get(h, -1) for h in range(1, top + 1)]
        start = time.time()
        got = GC.capture(run, key, todo, tics, batch=batch, say=say)
        made += len(got)
        say('%s %s: %d cases (%.0f s)' % (run, key, len(got),
                                          time.time() - start))
    return made


def captured(key: str) -> List[Tuple[str, int, int, Path]]:
    """The eligible calls of an entry whose cases exist."""
    out = []
    for run, hit, tic in eligible_calls(key)[0]:
        p = case_path(run, key, hit)
        if p.exists():
            out.append((run, hit, tic, p))
    return out


# ---------------------------------------------------------------------------
# The paths (the coverage of GAME.md 3.5 step 2), from the reference's
# canonical state at the call's entry
# ---------------------------------------------------------------------------

def _ptr(ref: 'SF.Ref', text: str, when: str = 'in') -> int:
    return int.from_bytes(ref.source(text, when), 'little') & 0xFFFFFF


class Tables:
    """Upstream's spectab, once."""
    _t: Optional[Dict[str, List[Tuple[int, str, int, int]]]] = None

    @classmethod
    def get(cls, mem) -> Dict[str, List[Tuple[int, str, int, int]]]:
        if cls._t is None:
            cls._t = upstream_spectab(mem)
        return cls._t


def find_special(ref: 'SF.Ref', line: Dict[str, Any], table: str
                 ) -> Tuple[str, Optional[Tuple[int, str, int, int]]]:
    """findSpecial's outcome for a line (P_CheckTag, then the table)."""
    if not line['tag'] and line['special'] not in NOTAGS:
        return 'notag', None
    for row in Tables.get(ref.case.entry)[table]:
        if row[0] == line['special']:
            return 'found', row
    return 'none', None


def player_mo(s: Dict[str, Any]):
    """The player's mobj reference in a canonical state."""
    pl = s['objects']['player']
    return pl[min(pl)]['mo']


def is_player(s: Dict[str, Any], ref) -> bool:
    mo = player_mo(s)
    return mo is not None and ref is not None and mo.kind == ref.kind and \
        mo.id == ref.id


def path_of(key: str, ref: 'SF.Ref') -> str:
    s = ref.s_in
    o = s['objects']
    c = uconst()
    if key in (USE, CROSS, EXIT):
        if key == USE:
            th = ref.ref(_ptr(ref, 'dp:_Dp:4'), SF.kinds_of('mobj'))
            ln = ref.ref(_ptr(ref, 'dp:_Dp+4:4'), ('line',))
        elif key == CROSS:
            ln = ref.ref(_ptr(ref, 'dp:_Dp:4'), ('line',))
            th = ref.ref(_ptr(ref, 'dp:_Dp+4:4'), SF.kinds_of('mobj'))
        else:
            ln = ref.ref(_ptr(ref, 'abs:p_switch65.s:SW_LINE:4'), ('line',))
            th = ref.ref(_ptr(ref, 'abs:p_switch65.s:SW_THING:4'),
                         SF.kinds_of('mobj'))
        line = o['line'][ln.id]
        mo = o[th.kind][th.id]
        who = 'player' if is_player(s, th) else 'monster'
        if key == EXIT:
            dead = o['player'][min(o['player'])]['health'] <= 0
            return 'exit-%s%s-%s' % (who, '-dead' if dead and who == 'player'
                                     else '', 'secret' if ref.source('a')[0]
                                     else 'normal')
        if who == 'monster':
            if key == USE:
                if line['flags'] & c['UC_ML_SECRET']:
                    return 'monster-secret'
                if not (line['special'] == 1 or 32 <= line['special'] < 35):
                    return 'monster-not-a-door'
            else:
                if mo['type'] in [c[m] for m in MISSILES]:
                    return 'missile'
                if line['special'] not in (97, 88):
                    return 'monster-not-97-88'
        how, row = find_special(ref, line, 'usetab' if key == USE else
                                'crosstab')
        if row is None:
            return '%s-%s' % (who, how)
        name = row[1].split(':')[1]
        if name == 'lnExit':
            dead = o['player'][min(o['player'])]['health'] <= 0
            name += '-dead' if dead and who == 'player' else ''
        return '%s-%s-mode%d' % (who, name, row[3])
    if key == FIND:
        ln = ref.ref(_ptr(ref, 'abs:p_switch65.s:SW_LINE:4'), ('line',))
        table = 'usetab' if ref.case.regs_in['x'] & 0xFFFF == 0 else \
            'crosstab'
        how, row = find_special(ref, o['line'][ln.id], table)
        return '%s-%s%s' % (table, how, '-' + row[1].split(':')[1]
                            if row else '')
    if key == CHANGE:
        ln = ref.ref(_ptr(ref, 'dp:_Dp:4'), ('line',))
        again = ref.source('a')[0] != 0 or ref.source('a')[1] != 0
        place = switch_place(ref, o['line'][ln.id])
        out = '%s-%s' % ('again' if again else 'once', place)
        if again and place != 'none':
            out += '-' + button_case(ref, ln.id)
        return out
    return 'call'


PLACES = ('top', 'middle', 'bottom')


def switchlist(ref: 'SF.Ref') -> List[int]:
    t = CL.Linkmap()
    a = t.address('p_switch65.s:switchlist')
    return [ref.case.entry.u16(a + 2 * i) for i in range(38)]


def side_textures(side: Dict[str, Any]) -> List[int]:
    return [side['toptexture'], side['midtexture'], side['bottomtexture']]


def switch_place(ref: 'SF.Ref', line: Dict[str, Any]) -> str:
    """The place of the front side's switch texture (upstream's scan:
    p_switch65.s:240-261), 'none' without one."""
    side = ref.s_in['objects']['side'][line['sidenum'][0]]
    tex = side_textures(side)
    for sw in switchlist(ref):
        for k in range(3):
            if sw == tex[k]:
                return PLACES[k]
    return 'none'


def button_case(ref: 'SF.Ref', line_id: int) -> str:
    bs = ref.s_in['objects']['button']
    busy = [b for b in (bs[k] for k in sorted(bs)) if b['btimer']]
    if any(b['line'] is not None and b['line'].id == line_id for b in busy):
        return 'pressed'
    if len(busy) == len(bs):
        return 'full'
    return 'slot%d' % next(i for i, k in enumerate(sorted(bs))
                           if not bs[k]['btimer'])


# ---------------------------------------------------------------------------
# The choice (GAME.md 2.4's minimums)
# ---------------------------------------------------------------------------

def rel(p: Path) -> str:
    """A case's name in paths.json: its path under the part's directory."""
    return str(Path(p).relative_to(OUT))


def _path_job(item: Tuple[str, str]) -> Tuple[str, str]:
    key, path = item
    try:
        return path, path_of(key, SF.Ref(GC.load_case(OUT / path)))
    except Exception as error:          # reported with the choice
        return path, 'error: %s: %s' % (type(error).__name__, error)


PATHS_FILE = OUT / 'paths.json'


def all_paths(keys: Sequence[str] = ENTRIES, jobs: int = 2,
              refresh: bool = False) -> Dict[str, Dict[str, str]]:
    """Each captured eligible call's path (kept in paths.json: the
    reference's decoding is slow)."""
    have: Dict[str, Dict[str, str]] = {}
    if PATHS_FILE.exists() and not refresh:
        have = json.loads(PATHS_FILE.read_text())
    todo = []
    for key in keys:
        known = have.setdefault(key, {})
        for run, hit, tic, p in captured(key):
            if rel(p) not in known:
                todo.append((key, rel(p)))
    if todo:
        if jobs <= 1:
            got = [_path_job(t) for t in todo]
        else:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                got = list(pool.map(_path_job, todo, chunksize=8))
        for (key, _), (path, kind) in zip(todo, got):
            have[key][path] = kind
        PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PATHS_FILE.write_text(json.dumps(have, indent=0, sort_keys=True))
    return have


def selection(key: str, paths: Optional[Dict[str, Dict[str, str]]] = None
              ) -> List[Path]:
    """The chosen calls of an entry: every eligible call when fewer than
    MINIMUM, else MINIMUM spread evenly over them and the first call of
    each path that no chosen call takes."""
    calls = captured(key)
    if len(calls) <= MINIMUM:
        return [p for _, _, _, p in calls]
    chosen = [calls[(i * len(calls)) // MINIMUM][3] for i in range(MINIMUM)]
    paths = paths if paths is not None else all_paths((key,))
    kinds = paths.get(key, {})
    seen = {kinds.get(rel(p)) for p in chosen}
    for _, _, _, p in calls:
        k = kinds.get(rel(p))
        if k is not None and k not in seen:
            seen.add(k)
            chosen.append(p)
    return chosen


# ---------------------------------------------------------------------------
# One run (secfind's run_one with this part's outputs and sound events)
# ---------------------------------------------------------------------------

def outputs(prep: 'SF.Prep', nat: 'SF.Native', m) -> List[str]:
    """The declared outputs against upstream's: secfind's forms, and "c"
    (the carry: dg_rp's bit 0 against upstream's P), "when": "c" (compared
    only when upstream's carry is set), "div" (upstream's value divided)."""
    lab = nat.b.labels
    regs = {'a': G.card_byte(m, lab['dg_ra']),
            'x': G.card_byte(m, lab['dg_rx']),
            'y': G.card_byte(m, lab['dg_ry']),
            'c': G.card_byte(m, lab['dg_rp']) & 1}
    up_c = prep.case.regs_out['p'] & 1
    out = []
    for item in prep.spec.get('out', []):
        if item.get('when') == 'c' and not up_c:
            continue
        nv = item['native']
        n = item.get('bytes', 2)
        if nv == 'ax':
            value = regs['a'] | regs['x'] << 8
        elif nv in regs:
            value = regs[nv]
        elif nv.startswith('zp:'):
            a = GR.zp_address(nv[3:])
            value = int.from_bytes(bytes(m.main[a:a + n]), 'little')
        else:
            raise PartError('a native output %r' % nv)
        if item['upstream'] == 'c':
            want = up_c
        else:
            raw = prep.ref.source(item['upstream'], 'out')
            kind = item.get('as')
            if kind:
                r = prep.ref.ref(int.from_bytes(raw, 'little'),
                                 SF.kinds_of(kind), 'out')
                want = SF.native_value(prep.mf, kind, r)
            else:
                want = int.from_bytes(raw, 'little') // item.get('div', 1)
        mask = (1 << (8 * n)) - 1
        if value & mask != want & mask:
            out.append('output %s (%s): %X, upstream %X' % (
                nv, item['upstream'], value & mask, want & mask))
    return out


def expected_sounds(prep: 'SF.Prep') -> List[Tuple[int, int, int, int]]:
    """The sound events upstream's call makes (R6: compared as events):
    P_ChangeSwitchTexture's S_StartSound2(front sector's soundorg,
    sfx_swtchn) when the front side shows a switch texture; lnExit's
    S_StartSound(thing, sfx_noway) for a dead player, else its switch's.
    (The handlers of waves 3 and 4 make their own: GAME.md 2.4, an open
    point of docs/game-parts/lines.md.)"""
    ref = prep.ref
    s = ref.s_in
    o = s['objects']
    c = uconst()
    tic = s['globals']['g_game65.s:_g_gametic'] & 0xFFFF

    def switch(line_id: int) -> List[Tuple[int, int, int, int]]:
        line = o['line'][line_id]
        if switch_place(ref, line) == 'none':
            return []
        sec = o['side'][line['sidenum'][0]]['sector']
        return [(tic, 1, c['UC_SFX_SWTCHN'], 0x8000 | sec.id)]

    def exit_(thing, line_id: int) -> List[Tuple[int, int, int, int]]:
        health = o['player'][min(o['player'])]['health']
        if is_player(s, thing) and health <= 0:
            return [(tic, 0, c['UC_SFX_NOWAY'],
                     SF.native_value(prep.mf, 'mobj', thing))]
        return switch(line_id)
    key = prep.key
    if key == CHANGE:
        ln = ref.ref(_ptr(ref, 'dp:_Dp:4'), ('line',))
        return switch(ln.id)
    if key == EXIT:
        ln = ref.ref(_ptr(ref, 'abs:p_switch65.s:SW_LINE:4'), ('line',))
        th = ref.ref(_ptr(ref, 'abs:p_switch65.s:SW_THING:4'),
                     SF.kinds_of('mobj'))
        return exit_(th, ln.id)
    if key in (USE, CROSS):
        th = ref.ref(_ptr(ref, 'dp:_Dp:4' if key == USE else 'dp:_Dp+4:4'),
                     SF.kinds_of('mobj'))
        ln = ref.ref(_ptr(ref, 'dp:_Dp+4:4' if key == USE else 'dp:_Dp:4'),
                     ('line',))
        path = path_of(key, ref)
        how, row = find_special(ref, o['line'][ln.id], 'usetab' if
                                key == USE else 'crosstab')
        if row is None or not path.split('-')[0] in ('player', 'monster'):
            return []
        if path.startswith('monster-') and ('not' in path or 'secret' in
                                            path):
            return []
        if row[1] == EXIT:
            return exit_(th, ln.id)
        if row[1] == 'p_switch65.s:lnLight':
            return []           # EV_LightTurnOn makes none; mode 1: no switch
        if row[1] in ('p_switch65.s:lnVDoor', 'p_switch65.s:lnDoor',
                      'p_switch65.s:lnPlat'):
            # part evworld's handlers (wave 3 as integrated: evworld.md
            # request 3): its model of their sounds, then the switch's
            import evworld
            GC.CASES = CASES    # (evworld's first import points it at its own)
            return evworld.expected_sounds(prep)
        if row[1] in ('p_switch65.s:lnFloor', 'p_switch65.s:lnStairs',
                      'p_switch65.s:lnDonut'):
            # part evfloor's handlers (wave 4 as integrated: evfloor.md
            # request 3): the floors make no sound; the switch's after a
            # started handler
            import evfloor
            GC.CASES = CASES    # (evfloor's first import points it at its own)
            return evfloor.expected_sounds(prep)
        # another handler of waves 3-4: its own sounds and the switch's
        # after it are not modelled; fail loudly rather than compare
        # against none
        raise PartError('the sound events of %s are not modelled (docs/'
                        'game-parts/lines.md, request 5)' % row[1])
    return []


def run_one(prep: 'SF.Prep', nat: 'SF.Native', fill: int, profile: str
            ) -> Dict[str, Any]:
    """One run of a case (secfind.run_one's steps): equal, the differences,
    the cycles from the routine's entry to its return, the lowest S, the
    strays."""
    spec = prep.spec
    res: Dict[str, Any] = {'case': prep.case.path.name if prep.case.path
                           else prep.case.header.get('note', 'synthetic'),
                           'entry': prep.key, 'fill': '%02x' % fill,
                           'profile': profile, 'ok': False}
    if prep.ref.problems:
        res['error'] = 'bridge: ' + '; '.join(prep.ref.problems[:3])
        return res
    img = prep.image(nat, fill)
    pre, canon = prep.pre_state(img, fill)
    entry = nat.b.labels[spec['native']]
    img.poke_word('dg_entry', entry)
    img.poke_label('dg_grp', bytes([nat.group(spec['native'])]))
    events = ['pc %X@1 snapshot start' % entry,
              'pc %X@1 snapshot ret' % nat.ret]
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-lines-', dir=str(BUILD)))
    try:
        r = G.run(img, work, GL.MODES['ROUTINE'], None,
                  regs=tuple(prep.regs), events=events,
                  banks=list(prep.banks) + [LL.GTEST],
                  profile=profile, write_log=SF.LOG_RANGES, cycles=RUN_CYCLES)
        ended = r.ended()
        res['ended'] = ended
        res['lowest_s'] = r.state.get('lowest_s')
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                res['stop'] = G.stop_codes(G.load_snapshot(p))
            return res
        c0, c1 = SF.snapshot_cycles(work, 'start'), \
            SF.snapshot_cycles(work, 'ret')
        res['cycles'] = c1 - c0 if c0 is not None and c1 is not None \
            else None
        if c0 is None:
            raise PartError('no snapshot at the routine\'s entry')
        w = SF.check_writes(work / 'writes.log', canon, c0)
        res['stray'] = w.strays
        res['stray_first'] = w.stray
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    if w.canonical:
        from native import setupcheck as SC
        nat_state = PortReader(prep.mf).read(SC.port_memory(m))
        res['decoded'] = True
    else:
        nat_state = pre
    diff = gcanon.compare(prep.ref.s_out, nat_state, 'routine')
    diff += outputs(prep, nat, m)
    got, want = SF.sounds(m), expected_sounds(prep)
    res['sounds'] = len(got)
    if got != want:
        diff.append('sound events %s, expected %s' % (got[:4], want[:4]))
    if w.strays:
        diff.append('%d stray writes: %s' % (w.strays, w.stray))
    res['diff'] = diff[:12]
    res['ok'] = not diff
    return res


def run_error(prep: 'SF.Prep', nat: 'SF.Native', fill: int, profile: str
              ) -> Dict[str, Any]:
    """A call whose reference ends in I_Error (it never returns): the
    native must stop with GS_ERROR."""
    spec = prep.spec
    res: Dict[str, Any] = {'case': prep.case.header.get('note'),
                           'entry': prep.key, 'fill': '%02x' % fill,
                           'profile': profile, 'ok': False,
                           'expect': 'GS_ERROR'}
    img = prep.image(nat, fill)
    img.poke_word('dg_entry', nat.b.labels[spec['native']])
    img.poke_label('dg_grp', bytes([nat.group(spec['native'])]))
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-lines-', dir=str(BUILD)))
    try:
        r = G.run(img, work, GL.MODES['ROUTINE'], None,
                  regs=tuple(prep.regs), banks=list(prep.banks) + [LL.GTEST],
                  profile=profile, cycles=RUN_CYCLES)
        res['ended'] = r.ended()
        p = work / 'crash.img'
        if p.exists():
            res['stop'] = G.stop_codes(G.load_snapshot(p))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    st = res.get('stop')
    res['ok'] = res['ended'] != 'halt' and st is not None and \
        st[0] == GL.GS['ERROR']
    if not res['ok']:
        res['diff'] = ['expected the stop GS_ERROR: ended %s, stop %s' % (
            res['ended'], st)]
    return res


# ---------------------------------------------------------------------------
# args.json
# ---------------------------------------------------------------------------

def args() -> Dict[str, Dict[str, Any]]:
    d = json.loads(ARGS.read_text())
    if d.get('format') != GR.ARGS_FORMAT:
        raise PartError('%s is not %s' % (ARGS, GR.ARGS_FORMAT))
    return d['entries']


# ---------------------------------------------------------------------------
# The synthetic cases (ref816 --call on an in-play state of each map)
# ---------------------------------------------------------------------------

def map_bases() -> Dict[int, Path]:
    """A captured P_UpdateSpecials of the tour on each map: the in-play
    states of the synthetic calls."""
    out: Dict[int, Path] = {}
    a = CL.Linkmap().address(GR.TIC_GAMEMAP)
    for run, hit, _ in base_calls():
        p = case_path(run, BASE_KEY, hit)
        if not p.exists():
            continue
        gm = GC.load_case(p).entry.u16(a)
        if gm not in out:
            out[gm] = p
    return out


class Base(SF.MapBase):
    """An in-play state: SF.MapBase with the mobjs and the player."""

    def __init__(self, path: Path):
        super().__init__(path)
        t = self.table
        c = self.c
        self.player = t.address('_g_player')
        self.player_mo = self.m.u32(self.player + c['UO_PL_MO']) & 0xFFFFFF
        self.ref = SF.Ref(self.case)

    def monster(self) -> Tuple[int, Any]:
        """The first live monster of the pool (a mobj that counts as a kill,
        not the player, not a missile): its upstream address and slot."""
        o = self.ref.s_in['objects']
        missiles = [self.c[m] for m in MISSILES]
        for ident in sorted(o['mobj']):
            mo = o['mobj'][ident]
            if mo.get('free') or mo['type'] in missiles or \
                    mo['health'] <= 0:
                continue
            kill = self.c['UC_MF_COUNTKILL_LO'] | \
                self.c['UC_MF_COUNTKILL_HI'] << 16
            if mo['flags'] & kill and not (
                    player_mo(self.ref.s_in) is not None and
                    player_mo(self.ref.s_in).id == ident):
                return self.ref.r_in.placement.address('mobj', ident), ident
        raise PartError('no monster on E1M%d' % self.gamemap)


def synthetic_plan(base: Base) -> List[Dict[str, Any]]:
    """The synthetic calls of a map (the module's docstring)."""
    c = base.c
    out: List[Dict[str, Any]] = []
    o = base.ref.s_in['objects']

    def dp(*ptrs: int) -> List[Tuple[int, bytes]]:
        return [(base.dp + 4 * k, (p & 0xFFFFFF).to_bytes(4, 'little'))
                for k, p in enumerate(ptrs)]
    sw = switchlist(base.ref)
    switch_lines, plain = [], []
    for i in range(base.nlines):
        tex = side_textures(o['side'][o['line'][i]['sidenum'][0]])
        (switch_lines if any(t in sw for t in tex) else plain).append(i)
    # P_ChangeSwitchTexture: every switch line, once and again; two plain
    for i in switch_lines + plain[:2]:
        for again in (0, 1):
            out.append({'key': CHANGE, 'pokes': dp(base.line(i)),
                        'regs': {'a': again}, 'shared': 1,
                        'note': 'line %d, %s' % (i, 'again' if again
                                                 else 'once')})
    # the button list: pressed already, slot 0 taken, full
    btn = base.table.address('_g_buttonlist')
    if switch_lines:
        i, j = switch_lines[0], (switch_lines + plain)[1]

        def button(line: int, timer: int) -> bytes:
            side = base.line_side0(line)
            sec = base.side_sector(side)
            rec = (base.line(line).to_bytes(4, 'little') +
                   c['UC_TOP'].to_bytes(2, 'little') +
                   (7).to_bytes(2, 'little') + timer.to_bytes(2, 'little') +
                   (base.sector(sec) + c['UO_SEC_SOUNDORG']).to_bytes(
                       4, 'little'))
            if len(rec) != c['US_BTN']:
                raise PartError('a button is %d bytes' % c['US_BTN'])
            return rec
        for note, recs in (('pressed', [(1, i, 5)]),
                           ('slot 0 taken', [(0, j, 9)]),
                           ('slot 0 pressed, slot 2 taken',
                            [(0, i, 3), (2, j, 30)]),
                           ('full', [(k, j, 4 + k) for k in range(4)])):
            pokes = dp(base.line(i)) + [
                (btn + k * c['US_BTN'], button(ln, timer))
                for k, ln, timer in recs]
            out.append({'key': CHANGE, 'pokes': pokes, 'regs': {'a': 1},
                        'note': 'line %d, again, buttons %s' % (i, note),
                        'expect': 'error' if note == 'full' else None})
    # P_UseSpecialLine: the exits by the player alive and dead, a monster
    mon_at, _ = base.monster()
    hp = base.player + c['UO_PL_HEALTH']
    exits = [i for i in range(base.nlines)
             if base.line_special(i) in (11, 51)]
    for i in exits:
        for note, pk in (('alive', []),
                         ('health 0', [(hp, (0).to_bytes(2, 'little'))]),
                         ('health -5', [(hp, (0xFFFB).to_bytes(2, 'little'))])):
            out.append({'key': USE, 'pokes': dp(base.player_mo, base.line(i))
                        + pk, 'regs': {},
                        'note': 'line %d (special %d), the player %s' % (
                            i, base.line_special(i), note)})
            out.append({'key': EXIT, 'pokes': dp(base.line(i)) + [
                (base.table.address('p_switch65.s:SW_THING'),
                 base.player_mo.to_bytes(4, 'little')),
                (base.table.address('p_switch65.s:SW_LINE'),
                 base.line(i).to_bytes(4, 'little'))] + pk,
                'regs': {'a': 1 if base.line_special(i) == 51 else 0},
                'note': 'lnExit, line %d, the player %s' % (i, note)})
        out.append({'key': USE, 'pokes': dp(mon_at, base.line(i)),
                    'regs': {}, 'shared': 1,
                    'note': 'line %d (special %d), a monster' % (
                        i, base.line_special(i))})
    # P_UseSpecialLine of lines with no special of usetab, or no tag
    use_specials = {row[0] for row in Tables.get(base.m)['usetab']}
    others = [i for i in range(base.nlines) if base.line_special(i) and
              base.line_special(i) not in use_specials][:3]
    notag = [i for i in range(base.nlines)
             if base.line_special(i) and not base.line_tag(i) and
             base.line_special(i) not in NOTAGS][:2]
    for i in others + notag:
        for who, at in (('the player', base.player_mo), ('a monster',
                                                         mon_at)):
            out.append({'key': USE, 'pokes': dp(at, base.line(i)),
                        'regs': {}, 'shared': 1,
                        'note': 'line %d (special %d), %s' % (
                            i, base.line_special(i), who)})
    # P_CrossSpecialLine: a light line (35, walk once) by the player from
    # each side and by a monster; 97 by a missile (an imp's shot)
    tagged = [i for i in range(base.nlines) if base.line_tag(i)]
    sp_at = lambda i: base.line(i) + c['UO_LINE_SPECIAL']  # noqa: E731
    for i in [k for k in range(base.nlines) if base.line_special(k) == 35]:
        for side in (0, 1):             # the map's own light lines (E1M3)
            out.append({'key': CROSS, 'pokes': dp(base.line(i),
                                                  base.player_mo),
                        'regs': {'a': side}, 'shared': 1,
                        'note': 'line %d (special 35, tag %d), the player, '
                                'side %d' % (i, base.line_tag(i), side)})
    for i in tagged[:2]:
        pk = [(sp_at(i), (35).to_bytes(2, 'little'))]
        for side in (0, 1):
            out.append({'key': CROSS, 'pokes': dp(base.line(i),
                                                  base.player_mo) + pk,
                        'regs': {'a': side},
                        'note': 'line %d as 35 (tag %d), the player, side '
                                '%d' % (i, base.line_tag(i), side)})
        out.append({'key': CROSS, 'pokes': dp(base.line(i), mon_at) + pk,
                    'regs': {'a': 0},
                    'note': 'line %d as 35, a monster' % i})
    ty = mon_at + c['UO_MO_TYPE']
    for i in (tagged + plain)[:1]:
        for m in MISSILES:
            pk = [(sp_at(i), (97).to_bytes(2, 'little')),
                  (ty, c[m].to_bytes(2, 'little'))]
            out.append({'key': CROSS, 'pokes': dp(base.line(i), mon_at) + pk,
                        'regs': {'a': 0},
                        'note': 'line %d as 97, a %s' % (i, m[6:].lower())})
    # findSpecial from each table on lines of every special of the map
    for i in [k for k in range(base.nlines) if base.line_special(k)][:12]:
        for x in (0, 1):
            off = 0 if x == 0 else 8 * len(Tables.get(base.m)['usetab'])
            end = 8 * len(Tables.get(base.m)['usetab']) if x == 0 else \
                off + 8 * len(Tables.get(base.m)['crosstab'])
            out.append({'key': FIND, 'pokes': [(base.table.address(
                'p_switch65.s:SW_LINE'), base.line(i).to_bytes(4, 'little'))],
                'regs': {'x': off, 'y': end}, 'shared': 1,
                'note': 'line %d (special %d), %s' % (
                    i, base.line_special(i), 'usetab' if x == 0 else
                    'crosstab')})
    return out


ERROR_TEXT = 'P_STARTBUTTON: NO BUTTON SLOTS LEFT!'   # p_switch65.s:108
ERROR_CYCLES = 3_000_000        # I_Error's text and its loop, well within


def ref_error_call(address: int, pokes, regs, work: Path) -> Dict[str, Any]:
    """ref816 --call of a call that must end in I_Error: it never returns,
    it stops in I_Error's last loop (i_iigs65.s:325, within 256 bytes of
    I_Error) with the message on the text page."""
    cmd = [str(title.MACHINE), str(work / 'entry.img')]
    for k, (a, d) in enumerate(pokes):
        f = work / ('poke%d.bin' % k)
        f.write_bytes(d)
        cmd += ['--load', '%06X:%s' % (a, f)]
    for k, v in regs.items():
        cmd += ['--reg', '%s=%X' % (k, v)]
    cmd += ['--call', '%06X' % address, '--state', str(work / 'state.json'),
            '--cycles', str(ERROR_CYCLES)]
    r = bounded.run(cmd, timeout=120, max_bytes=1 << 26,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode:
        raise PartError('ref816 --call failed: %s' % r.stdout[-600:])
    state = json.loads((work / 'state.json').read_text())
    at = CL.Linkmap().address('I_Error')
    pc = state['call']['end']['pc']
    return {'returned': bool(state['call']['returned']), 'pc': pc,
            'i_error': at <= pc < at + 256 and any(
                x.strip() == ERROR_TEXT for x in state.get('text_page', []))}


def make_synthetic(base_path: Path) -> List[Dict[str, Any]]:
    """The map's synthetic calls run on ref816: each record with its call
    state and writes."""
    base = Base(base_path)
    t = base.table
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-lines-syn-',
                                 dir=str(BUILD)))
    out: List[Dict[str, Any]] = []
    try:
        entry = base.case.entry.copy()
        entry.header = base.case.entry.header
        (work / 'entry.img').write_bytes(entry.image_bytes())
        for rec in synthetic_plan(base):
            address = t.address(rec['key'])
            regs = dict(rec['regs'])
            if rec.get('expect') == 'error':
                got = ref_error_call(address, rec['pokes'], regs, work)
                if got['returned'] or not got['i_error']:
                    raise PartError('%s: not an I_Error: %s' % (rec['note'],
                                                               got))
                call, writes = {'error': got}, []
            else:
                call, writes = SF.ref_call(address, rec['pokes'], regs, work)
            out.append(dict(rec, address=address, call=call,
                            pokes=[[a, d.hex()] for a, d in rec['pokes']],
                            writes=[[a, d.hex()] for a, d in writes],
                            base=str(base_path.relative_to(OUT))))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return out


def _syn_job(path: str) -> List[Dict[str, Any]]:
    return make_synthetic(Path(path))


def write_synthetic(jobs: int = 2) -> Dict[str, int]:
    SYN.mkdir(parents=True, exist_ok=True)
    bases = map_bases()
    absent = sorted(set(range(1, 10)) - set(bases))
    if absent:
        raise PartError('no in-play state of E1M%s (--capture)' % absent)
    maps = sorted(bases)
    counts = {}
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        got = dict(zip(maps, pool.map(_syn_job, [str(bases[m])
                                                 for m in maps])))
    for m, recs in got.items():
        (SYN / ('e1m%d.json.z' % m)).write_bytes(zlib.compress(json.dumps(
            {'format': SYN_FORMAT, 'map': m, 'records': recs},
            separators=(',', ':')).encode(), 6))
        counts['E1M%d' % m] = len(recs)
    return counts


def synthetic_names() -> List[str]:
    return ['e1m%d' % m for m in range(1, 10)]


def load_synthetic(name: str) -> List[Dict[str, Any]]:
    p = SYN / (name + '.json.z')
    if not p.exists():
        raise PartError('no synthetic cases %s (--synthetic)' % p)
    d = json.loads(zlib.decompress(p.read_bytes()))
    if d.get('format') != SYN_FORMAT:
        raise PartError('%s is not %s' % (p, SYN_FORMAT))
    return d['records']


_BASE_CASES: Dict[str, GC.Case] = {}


def synthetic_case(rec: Dict[str, Any]) -> GC.Case:
    base = rec['base']
    if base not in _BASE_CASES:
        _BASE_CASES.clear()
        _BASE_CASES[base] = GC.load_case(OUT / base)
    b = _BASE_CASES[base]
    entry = b.entry.copy()
    entry.header = b.entry.header
    for a, d in rec['pokes']:
        entry.write(a, bytes.fromhex(d))
    after = entry.copy()
    for a, d in rec['writes']:
        after.write(a, bytes.fromhex(d))
    call = rec['call']
    if 'error' in call:                 # the I_Error case: the entry's own
        call = dict(b.header['call'])   #   registers with the arguments'
        start = dict(call['start'])
        for k, v in rec['regs'].items():
            start[k] = v
        call['start'] = start
        call['end'] = start
    header = dict(b.header, routine=rec['key'], note=rec['note'],
                  call=call, hit=0,
                  writes=[[a, len(d) // 2] for a, d in rec['writes']])
    return GC.Case(header, entry, after, None)


# ---------------------------------------------------------------------------
# The checkpoint (--check)
# ---------------------------------------------------------------------------

def _check_job(job) -> List[Dict[str, Any]]:
    kind, items, obj, fills, profiles = job
    nat = SF.Native(Path(obj))
    spec_all = args()
    out: List[Dict[str, Any]] = []
    shared = _Shared()
    for item in items:
        expect = None
        if kind == 'case':
            key, path = item
            name = '/'.join(Path(path).parts[-3:])
            ref = port = pre = None
            try:
                case = GC.load_case(Path(path))
            except Exception as error:
                out.append({'case': name, 'entry': key, 'ok': False,
                            'error': '%s: %s' % (type(error).__name__,
                                                 error)})
                continue
        else:
            key = item['key']
            name = '%s: %s' % (item['base'], item['note'])
            expect = item.get('expect')
            case = synthetic_case(item)
            ref, port, pre = shared.get(item, case)
        try:
            prep = SF.Prep(case, key, spec_all[key], ref=ref, port=port,
                           pre=pre)
            if kind != 'case' and item.get('shared') and ref is not None:
                shared.port = prep.port
            path = path_of(key, prep.ref)
        except Exception as error:      # reported per case, never hidden
            out.append({'case': name, 'entry': key, 'ok': False,
                        'synthetic': kind != 'case',
                        'error': '%s: %s' % (type(error).__name__, error)})
            continue
        for fill in fills:
            for profile in profiles:
                try:
                    if expect == 'error':
                        r = run_error(prep, nat, fill, profile)
                    else:
                        r = run_one(prep, nat, fill, profile)
                except Exception as error:
                    r = {'entry': key, 'fill': '%02x' % fill,
                         'profile': profile, 'ok': False,
                         'error': '%s: %s' % (type(error).__name__, error)}
                r.update(case=name, path=path, synthetic=kind != 'case')
                out.append(r)
    return out


class _Shared(SF.Shared):
    """secfind's Shared with this part's base directory."""

    def get(self, rec: Dict[str, Any], case: GC.Case):
        if not rec.get('shared'):
            return None, None, None
        if self.base != rec['base']:
            self.base, self.ref, self.port = rec['base'], SF.Ref(case), None
            self.pre = {}
        pokes: Set[int] = set()
        for a, d in rec['pokes']:
            pokes.update(range(a, a + len(d) // 2))
        if pokes & self.ref.read_bytes:
            return None, None, None
        return SF.derive_ref(self.ref, case), self.port, self.pre


def check_jobs(keys: Sequence[str] = ALL_KEYS, sample: int = 1,
               synthetic: bool = True, captured_: bool = True,
               obj: Path = OUT, fills: Sequence[int] = FILLS,
               profiles: Sequence[str] = PROFILES,
               names: Optional[Sequence[str]] = None, select=None,
               chunk: int = 12) -> List[Tuple]:
    """The checkpoint's jobs: the chosen captured calls of keys (every
    sample-th) and the synthetic records (of names, select(record) true)."""
    jobs: List[Tuple] = []
    if captured_:
        paths = all_paths([k for k in keys if k in ENTRIES])
        for key in keys:
            if key not in ENTRIES:
                continue
            ps = selection(key, paths)[::sample]
            for i in range(0, len(ps), chunk):
                jobs.append(('case', [(key, str(p)) for p in
                                      ps[i:i + chunk]], str(obj),
                             tuple(fills), tuple(profiles)))
    if synthetic:
        for name in (names or synthetic_names()):
            recs = []
            for key in keys:
                recs += [r for r in load_synthetic(name) if r['key'] == key
                         and (select is None or select(r))][::sample]
            for i in range(0, len(recs), 4 * chunk):
                jobs.append(('synthetic', recs[i:i + 4 * chunk], str(obj),
                             tuple(fills), tuple(profiles)))
    return jobs


def run_jobs(jobs: List[Tuple], workers: int = 2,
             progress: bool = True) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    start = time.time()
    if workers <= 1:
        for j in jobs:
            out += _check_job(j)
        return out
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, got in enumerate(pool.map(_check_job, jobs)):
            out += got
            if progress and (i + 1) % 20 == 0:
                say('  %d of %d jobs, %d runs, %d failed (%.0f s)' % (
                    i + 1, len(jobs), len(out),
                    sum(1 for r in out if not r.get('ok')),
                    time.time() - start))
    return out


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Per entry: the cases (eligible, run, waiting), runs, failures, stray
    writes, paths, cycles (median and worst a profile), the lowest S."""
    entries: Dict[str, Any] = {}
    spec_all = args()
    for key in ALL_KEYS:
        rs = [r for r in results if r.get('entry') == key]
        cases = {(r.get('case'), bool(r.get('synthetic'))) for r in rs}
        if key in ENTRIES:
            elig, waiting = eligible_calls(key)
        else:
            elig, waiting = [], {}
        e: Dict[str, Any] = {
            'native': spec_all[key]['native'],
            'calls_eligible': len(elig), 'calls_waiting': waiting,
            'cases_captured': sum(1 for _, s in cases if not s),
            'cases_synthetic': sum(1 for _, s in cases if s),
            'runs': len(rs),
            'failures': sum(1 for r in rs if not r.get('ok')),
            'stray_writes': sum(r.get('stray') or 0 for r in rs),
            'paths': {}, 'cycles': {}}
        for r in rs:
            if 'path' in r and r.get('fill') == '%02x' % FILLS[0] and \
                    r.get('profile') == PROFILES[0]:
                p = ('synthetic ' if r.get('synthetic') else '') + r['path']
                e['paths'][p] = e['paths'].get(p, 0) + 1
        for profile in PROFILES:
            cyc = sorted(r['cycles'] for r in rs if r.get('profile') ==
                         profile and r.get('cycles') is not None)
            if cyc:
                mhz = SF.fabric_mhz(profile)
                e['cycles'][profile] = {
                    'median': cyc[len(cyc) // 2], 'worst': cyc[-1],
                    'median_us': round(cyc[len(cyc) // 2] / mhz, 1),
                    'worst_us': round(cyc[-1] / mhz, 1),
                    'unit': 'fabric clocks (%g MHz), from the routine\'s '
                            'entry to its return' % mhz}
        ls = [r['lowest_s']['s'] for r in rs if isinstance(
            r.get('lowest_s'), dict)]
        e['lowest_s'] = min(ls) if ls else None
        e['first_failures'] = [r for r in rs if not r.get('ok')][:3]
        entries[key] = e
    return entries


# ---------------------------------------------------------------------------
# The planted bugs (--plants)
# ---------------------------------------------------------------------------

# name -> (the check that must catch it, [(old, new)] edits of lines.s)
PLANTS = {
    # a walk-once special (crosstab mode 1) not cleared when its handler
    # started
    'walk-once-not-cleared': ('walk-once', [(
        '''        ldy SB_MD               ; walk once (1) and started: no more
        beq @no                 ;   special''',
        '''        ldy SB_MD               ; (planted: never cleared)
        bra @no''')]),
    # a monster treated as the player: every special of usetab
    'monster-allowed': ('monster', [(
        '''        IS_PLAYER SB_TH
        beq @find
        SW_LINE SB_LN           ; a monster: not a secret line,''',
        '''        IS_PLAYER SB_TH
        bra @find               ; (planted: monsters too)
        SW_LINE SB_LN           ; a monster: not a secret line,''')]),
    # the button's timer one tic short
    'button-timer-short': ('buttons', [(
        'BUTTONTIME = UC_TICRATE         ; p_switch65.s:21',
        'BUTTONTIME = UC_TICRATE - 1     ; (planted: a tic short)')]),
}


def plant_build(name: str, tmp: Path) -> Path:
    """The part's test image with the planted bug `name`, from a scratch
    copy of its sources in tmp (game.mk and its includes, the parts'
    fragments, this part's sources; the rest from the tree through
    game.mk's vpath): the image's directory."""
    _, edits = PLANTS[name]
    src = tmp / 'src'
    files = list(G.PLANT_COPY) + ['game/%s/%s' % (PART, f) for f in
                                  ('part.mk', 'lines.s')]
    for f in files:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
    target = src / 'game' / PART / 'lines.s'
    text = target.read_text()
    for old, new in edits:
        if text.count(old) != 1:
            raise PartError('the planted bug %s no longer applies: %r' % (
                name, old[:60]))
        text = text.replace(old, new)
    target.write_text(text)
    return build(game=tmp / 'game', source=src)


def plant_check(check: str, obj: Path) -> Dict[str, Any]:
    """A planted image on its named check (fill $A5 under f121)."""
    one = dict(fills=(FILLS[0],), profiles=(PROFILES[0],))
    if check == 'walk-once':
        jobs = check_jobs(keys=(CROSS,), captured_=False, obj=obj,
                          names=('e1m1', 'e1m3'),
                          select=lambda r: 'as 35' in r['note'] or
                          'special 35' in r['note'], **one)
    elif check == 'monster':
        jobs = check_jobs(keys=(USE,), synthetic=False, obj=obj, sample=10,
                          **one)
        jobs += check_jobs(keys=(USE,), captured_=False, obj=obj,
                           names=('e1m1',),
                           select=lambda r: 'monster' in r['note'], **one)
    elif check == 'buttons':
        jobs = check_jobs(keys=(CHANGE,), captured_=False, obj=obj,
                          names=('e1m1',),
                          select=lambda r: r['regs'].get('a') == 1, **one)
    else:
        raise PartError('no check %s' % check)
    res = run_jobs(jobs, workers=2, progress=False)
    bad = [r for r in res if not r.get('ok')]
    return {'runs': len(res), 'failed': len(bad),
            'first': (bad[0].get('diff') or [bad[0].get('error') or
                                             bad[0].get('ended')])[:2]
            if bad else None}


def plants(names: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    out = {}
    for name in (names or list(PLANTS)):
        check = PLANTS[name][0]
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-lines-plant-',
                                    dir=str(BUILD)))
        try:
            obj = plant_build(name, tmp)
            r = plant_check(check, obj)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        r['check'] = check
        r['caught'] = r['failed'] > 0
        out[name] = r
        say('%-22s %-10s %s' % (name, check, 'caught: %d of %d runs fail, '
                                '%s' % (r['failed'], r['runs'], r['first'])
                                if r['caught'] else 'NOT CAUGHT (%d runs)' %
                                r['runs']))
    return out


# ---------------------------------------------------------------------------
# Sizes (docs/GAME.md 4.7: the part's budget)
# ---------------------------------------------------------------------------

BUDGET = next(p['native'] for p in GL.PARTS if p['name'] == PART)
UPSTREAM_BYTES = next(p['up'] for p in GL.PARTS if p['name'] == PART)
LABELS = ('P_UseSpecialLine', 'P_CrossSpecialLine', 'findSpecial',
          'P_ChangeSwitchTexture', 'lnExit')


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """The part's bytes (lines.o) against its budget; each routine's bytes
    (to the next of the part's routines in its segment) and group."""
    b = G.load_build(obj, IMAGE)
    text = (obj / (IMAGE + '.map')).read_text()
    mods = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    chunks: List[Tuple[str, int, int]] = []
    module = None
    for line in mods.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module == 'lines' and f and f[0] in b.segments:
            off = next(int(x[5:], 16) for x in f if x.startswith('Offs='))
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            lo = b.segments[f[0]][0] + off
            chunks.append((f[0], lo, lo + size))
    nat = SF.Native(obj)
    routines = {}
    for seg, lo, hi in chunks:
        g = int(seg[4:]) if seg.startswith('GGRP') else 0
        inside = sorted((b.labels[n], n) for n in LABELS
                        if lo <= b.labels[n] < hi and nat.group(n) == g)
        for k, (a, n) in enumerate(inside):
            end = inside[k + 1][0] if k + 1 < len(inside) else hi
            routines[n] = {'bytes': end - a, 'group': nat.group(n),
                           'segment': seg}
    routines['findSpecial']['tables'] = b.labels['crosstab_end'] - \
        b.labels['spectab']
    total = sum(hi - lo for _, lo, hi in chunks)
    groups = sorted({r['group'] for r in routines.values()})
    image = [x for x in G.sizes(b) if not x.startswith('group ') or
             int(x.split()[1]) in groups]
    return {'bytes': total, 'budget': BUDGET, 'upstream': UPSTREAM_BYTES,
            'over_10_percent': total > BUDGET * 1.1, 'routines': routines,
            'image': image}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def du_kb(path: Path) -> int:
    r = subprocess.run(['du', '-sk', str(path)], stdout=subprocess.PIPE,
                       universal_newlines=True)
    return int(r.stdout.split()[0]) if r.returncode == 0 else -1


def write_report(results: Optional[Sequence[Dict[str, Any]]] = None,
                 **parts) -> Dict[str, Any]:
    rep: Dict[str, Any] = {}
    if REPORT.exists():
        rep = json.loads(REPORT.read_text())
    rep.update(format='game-part-report 1', part=PART,
               wave=next(p['wave'] for p in GL.PARTS if p['name'] == PART),
               exclusions=[n for n, _, _ in gcanon.ROUTINE_EXCLUSIONS])
    if results is not None:
        rep['entries'] = summarize(results)
        rep['runs'] = len(results)
        rep['failures'] = sum(1 for r in results if not r.get('ok'))
        rep['stray_writes'] = sum(r.get('stray') or 0 for r in results)
        ls = [r['lowest_s']['s'] for r in results
              if isinstance(r.get('lowest_s'), dict)]
        rep['lowest_s'] = min(ls) if ls else None
    rep.update(parts)
    rep['build_kb'] = du_kb(OUT)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, indent=1, default=str) + '\n')
    return rep


def print_report(rep: Dict[str, Any]) -> None:
    for key, e in rep.get('entries', {}).items():
        cyc = '; '.join('%s %s/%s us' % (p, c['median_us'], c['worst_us'])
                        for p, c in e['cycles'].items())
        say('%-40s %4d+%-4d cases %5d runs %d failed %d stray, S %s; %s' % (
            key, e['cases_captured'], e['cases_synthetic'], e['runs'],
            e['failures'], e['stray_writes'], e['lowest_s'], cyc))
    if 'sizes' in rep:
        sz = rep['sizes']
        say('bytes %d of %d (upstream %d)' % (sz['bytes'], sz['budget'],
                                             sz['upstream']))
    for name, r in rep.get('plants', {}).items():
        say('planted %-22s %s' % (name, 'caught' if r['caught'] else
                                  'NOT CAUGHT'))


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--synthetic', action='store_true')
    parser.add_argument('--paths', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--eligible', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--runs', default=','.join(GC.RUNS))
    parser.add_argument('--keys', default=None)
    parser.add_argument('--batch', type=int, default=BATCH)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--json', type=Path)
    a = parser.parse_args(argv)
    runs = [r for r in a.runs.split(',') if r]
    why = missing()
    if why:
        print('cannot run: %s' % why, file=sys.stderr)
        return 2
    if a.eligible:
        for key in ENTRIES:
            elig, waiting = eligible_calls(key)
            say('%-40s eligible %d, waiting %s' % (key, len(elig), waiting))
        return 0
    if a.capture:
        keys = a.keys.split(',') if a.keys else list(ENTRIES)
        n = capture(keys, runs, batch=a.batch)
        say('%d cases made' % n)
        return 0
    if a.synthetic:
        start = time.time()
        counts = write_synthetic(a.jobs)
        say('synthetic calls: %s (%.0f s)' % (counts, time.time() - start))
        return 0
    if a.paths:
        p = all_paths(jobs=a.jobs)
        for key, kinds in p.items():
            count: Dict[str, int] = {}
            for k in kinds.values():
                count[k] = count.get(k, 0) + 1
            say('%s: %s' % (key, json.dumps(count, sort_keys=True)))
        return 0
    if a.check:
        keys = a.keys.split(',') if a.keys else list(ALL_KEYS)
        start = time.time()
        build()
        jobs = check_jobs(keys, a.sample)
        say('%d jobs' % len(jobs))
        res = run_jobs(jobs, a.jobs)
        rep = write_report(res, sizes=sizes(), check_seconds=round(
            time.time() - start), sample=a.sample)
        if a.json:
            a.json.write_text(json.dumps(res, indent=1) + '\n')
        print_report(rep)
        return 1 if rep['failures'] else 0
    if a.plants:
        build()
        r = plants(a.keys.split(',') if a.keys else None)
        write_report(plants=r)
        return 0 if all(x['caught'] for x in r.values()) else 1
    if a.report:
        print_report(json.loads(REPORT.read_text()))
        return 0
    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
