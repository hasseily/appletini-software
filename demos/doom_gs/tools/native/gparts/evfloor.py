#!/usr/bin/env python3
"""Part evfloor's checkpoint (milestone 10, docs/GAME.md 2.4 row evfloor,
3.5; docs/game-parts/evfloor.md): routine mode on the part's entries, its
synthetic cases on the nine maps and its planted bugs, in the lean form the
owner asked for on 2026-10-02 (at most LEAN calls a routine, one poisoned
machine, $A5).

Usage:  python3 tools/native/gparts/evfloor.py --capture
        python3 tools/native/gparts/evfloor.py --synthetic [--jobs 2]
        python3 tools/native/gparts/evfloor.py --check [--jobs 2]
        python3 tools/native/gparts/evfloor.py --plants
        python3 tools/native/gparts/evfloor.py --report

Everything it writes is under build/native/game/evfloor/ (the part's own
directory): the cases (cases/RUN/ROUTINE/hNNNNNNNN.case.z and each run's
base.ram.z, through tools/native/gamecap.py with its case directory pointed
here), the synthetic calls (synthetic/), report.json. The shared outputs
(build/native/game/shared/) are read only.

The run machinery is part secfind's, part lines' and part evworld's
(tools/native/gparts/secfind.py: Ref, Prep, Native, ref_call; lines.py:
the outputs, the switch's place, the tables; evworld.py: the stray rule
with the sides, the in-play bases, the new specials of a call), imported
as the earlier waves' integrations asked; this tool adds the part's
choice, paths, sound events, synthetic cases and plants.

--capture: every call of the part's entries in the survey's runs (EV_DoFloor
3, newFloor 2, all in demo3; EV_BuildStairs and EV_DoDonut none), and the
tour's P_UpdateSpecials every TOUR_STEP-th call (the in-play states of the
nine maps for the synthetic calls).

--synthetic: on each map, ref816 --call of P_UseSpecialLine (usetab) and
P_CrossSpecialLine (crosstab) on the lines whose special LSTAB sends to
lnFloor, lnStairs or lnDonut (GAME.md 2.4: "every floor, stairs and donut
special on every line of the nine maps that has it", cut to LEAN calls a
handler), the first line of each special used a second time on the state
the first use left (the busy floors), and EV_DoFloor called directly with
the two types no E1 line uses (lowerFloor 0 and a type past the table).

--check: the cases from the poisoned machine $A5 under f121 and fastpath,
compared with ref816 in gcanon.py's routine mode (R1-R6), the declared
outputs of src/native/game/evfloor/args.json, the sound events (R6: the
floors make none; a switch's sound after a started handler), no stray
write. Writes report.json.

--plants: each planted bug built from a scratch copy of the part's sources
in a temporary directory (deleted), run on its named check, which must
fail.
"""

import argparse
import json
import shutil
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

import secfind as SF  # noqa: E402  (wave 1's machinery)
import lines as LN  # noqa: E402  (wave 2's: outputs, switches, tables)
import mobjstate as MS  # noqa: E402  (the shared stray rule)
import evworld as EW  # noqa: E402  (wave 3's: the stray rule, the bases)
from bridge.port import PortReader  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL  # noqa: E402
from ref816 import calls as CL  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'evfloor'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
SYN = OUT / 'synthetic'
REPORT = OUT / 'report.json'
ARGS = SRC / 'game' / PART / 'args.json'
IMAGE = 'ptest'
GC.CASES = CASES                # the part's own case directory (the
#                                 imports pointed it at evworld's)

DOFLOOR = 'p_floor65.s:EV_DoFloor'
STAIRS = 'p_floor65.s:EV_BuildStairs'
DONUT = 'p_floor65.s:EV_DoDonut'
NEWFLOOR = 'p_floor65.s:newFloor'
ENTRIES = (DOFLOOR, STAIRS, DONUT, NEWFLOOR)
USE, CROSS = LN.USE, LN.CROSS
ALL_KEYS = ENTRIES + (USE, CROSS)
BASE_KEY = LN.BASE_KEY          # the tour's P_UpdateSpecials
LEAN = 40                       # calls a routine (the owner's lean checks)
FILLS = (0xA5,)                 # one poisoned machine (lean)
PROFILES = SF.PROFILES
BATCH = 40
SYN_FORMAT = 'evfloor-synthetic 1'
MINE = ('p_switch65.s:lnFloor', 'p_switch65.s:lnStairs',
        'p_switch65.s:lnDonut')
OTHER_TYPE = 7                  # a floor type past upstream's table


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


def uconst() -> Dict[str, int]:
    return SF.uconst()


def missing() -> Optional[str]:
    """Why the checkpoint cannot run (None: it can)."""
    return SF.missing()


def build(game: Optional[Path] = None, source: Path = SRC) -> Path:
    """The part's test image (make -f game.mk part P=evfloor); its
    directory."""
    variables = ['P=%s' % PART]
    if game is not None:
        variables.append('GAME=%s' % game)
    G.make('part', variables, source)
    return (game or GL.GAME) / PART


def args() -> Dict[str, Dict[str, Any]]:
    """The part's declarations, and part lines' for the synthetic calls
    through its entries."""
    d = json.loads(ARGS.read_text())
    if d.get('format') != GR.ARGS_FORMAT:
        raise PartError('%s is not %s' % (ARGS, GR.ARGS_FORMAT))
    out = dict(d['entries'])
    lines = LN.args()
    out[USE], out[CROSS] = lines[USE], lines[CROSS]
    return out


# ---------------------------------------------------------------------------
# The calls (lean: at most LEAN a routine; the part's are fewer)
# ---------------------------------------------------------------------------

def survey_calls(key: str) -> List[Tuple[str, int, int]]:
    """Every call of an entry over the survey's runs: (run, hit, tic). The
    part's entries reach no dispatch table, so every call is eligible."""
    out = []
    for run in GC.RUNS:
        sv = GC.survey_of(run)
        r = sv['routines'].get(key) if sv else None
        if not r:
            continue
        for hit in range(1, r['calls'] + 1):
            if r['reached'].get(str(hit)):
                raise PartError('%s %s call %d reaches a dispatch target'
                                % (run, key, hit))
            out.append((run, hit, r['tic'][hit - 1]))
    return out


def chosen(key: str) -> List[Tuple[str, int, int]]:
    """The calls of an entry the checkpoint runs: all up to LEAN, then
    spread evenly."""
    calls = survey_calls(key)
    if len(calls) <= LEAN:
        return calls
    return [calls[(i * len(calls)) // LEAN] for i in range(LEAN)]


def case_path(run: str, key: str, hit: int) -> Path:
    return GC.case_dir(run, key) / ('h%08d.case.z' % hit)


def capture(keys: Sequence[str] = ENTRIES, bases: bool = True) -> int:
    want: Dict[Tuple[str, str], Dict[int, int]] = {}
    for key in keys:
        for run, hit, tic in chosen(key):
            want.setdefault((run, key), {})[hit] = tic
    if bases:
        for run, hit, tic in LN.base_calls():
            want.setdefault((run, BASE_KEY), {})[hit] = tic
    made = 0
    for (run, key), hits in sorted(want.items()):
        todo = sorted(h for h in hits if not case_path(run, key, h).exists())
        if not todo:
            continue
        top = max(hits)
        tics = [hits.get(h, -1) for h in range(1, top + 1)]
        start = time.time()
        got = GC.capture(run, key, todo, tics, batch=BATCH, say=say)
        made += len(got)
        say('%s %s: %d cases (%.0f s)' % (run, key, len(got),
                                          time.time() - start))
    return made


def captured(key: str) -> List[Path]:
    return [case_path(run, key, hit) for run, hit, _ in chosen(key)
            if case_path(run, key, hit).exists()]


def captures_complete() -> Optional[str]:
    """Why the captures are incomplete (None: every chosen call is there)."""
    for key in ENTRIES:
        n = len(chosen(key))
        if len(captured(key)) != n:
            return '%d of %d captures of %s' % (len(captured(key)), n, key)
    return None


# ---------------------------------------------------------------------------
# The paths (the branches a call takes), from the reference's states
# ---------------------------------------------------------------------------

def new_floors(ref: 'SF.Ref') -> List[Dict[str, Any]]:
    return EW.new_specials(ref, 'floor')


def _ptr(ref: 'SF.Ref', text: str, when: str = 'in') -> int:
    return int.from_bytes(ref.source(text, when), 'little') & 0xFFFFFF


def made_text(ref: 'SF.Ref') -> str:
    """The floors a call made, by type: 'type4x2,type1x1' ('none')."""
    count: Dict[int, int] = {}
    for f in new_floors(ref):
        count[f['type']] = count.get(f['type'], 0) + 1
    return ','.join('type%dx%d' % (t, n) for t, n in sorted(count.items())) \
        or 'none'


def busy_tagged(ref: 'SF.Ref', line_id: int) -> int:
    """The sectors with the line's tag whose floor moves at the call."""
    s = ref.s_in['objects']
    tag = s['line'][line_id]['tag']
    return sum(1 for sec in s['sector'].values()
               if sec['tag'] == tag and sec['floordata'] is not None)


def path_of(key: str, ref: 'SF.Ref') -> str:
    if key in (DOFLOOR, STAIRS, DONUT):
        ln = ref.ref(_ptr(ref, 'dp:_Dp:4'), ('line',))
        out = '%s-%s' % (key.split(':')[1], made_text(ref))
        if key == DOFLOOR:
            out += '-arg%d' % (ref.source('a')[0])
        busy = busy_tagged(ref, ln.id)
        return out + ('-busy%d' % busy if busy else '')
    if key == NEWFLOOR:
        return 'new-type%d' % ref.source('a')[0]
    if key in (USE, CROSS):
        p = LN.path_of(key, ref)
        if any(m.split(':')[1] in p for m in MINE):
            ln = ref.ref(_ptr(ref, 'dp:_Dp+4:4' if key == USE else
                              'dp:_Dp:4'), ('line',))
            p += ':' + made_text(ref)
            busy = busy_tagged(ref, ln.id)
            if busy:
                p += '-busy%d' % busy
        return p
    return 'call'


# ---------------------------------------------------------------------------
# The sound events (R6): the floors make none; the switch's after them
# ---------------------------------------------------------------------------

def expected_sounds(prep: 'SF.Prep') -> List[Tuple[int, int, int, int]]:
    """Upstream's events in the call: EV_DoFloor, EV_BuildStairs,
    EV_DoDonut and newFloor make none (their sounds are T_MoveFloor's,
    part planes'); P_UseSpecialLine of a switch (mode 1) or a button (mode
    2) whose handler started makes the switch's (lines' rule: the front
    sector's sound origin, sfx_swtchn, when the front side shows a switch
    texture)."""
    ref = prep.ref
    key = prep.key
    if key not in (USE, CROSS):
        return []
    c = uconst()
    o = ref.s_in['objects']
    tic = ref.s_in['globals']['g_game65.s:_g_gametic'] & 0xFFFF
    ln = ref.ref(_ptr(ref, 'dp:_Dp+4:4' if key == USE else 'dp:_Dp:4'),
                 ('line',))
    path = LN.path_of(key, ref)
    how, row = LN.find_special(ref, o['line'][ln.id], 'usetab' if
                               key == USE else 'crosstab')
    if row is None or path.startswith('monster-'):
        return []
    if row[1] not in MINE:
        raise PartError('%s: not a handler of this part' % row[1])
    started = bool(new_floors(ref))
    got: List[Tuple[int, int, int, int]] = []
    if key == USE and row[3] in (1, 2) and started:
        if LN.switch_place(ref, o['line'][ln.id]) != 'none':
            sec = o['side'][o['line'][ln.id]['sidenum'][0]]['sector']
            got.append((tic, 1, c['UC_SFX_SWTCHN'], 0x8000 | sec.id))
    return got


# ---------------------------------------------------------------------------
# One run (secfind's run_one with lines' outputs and this part's sounds)
# ---------------------------------------------------------------------------

def run_one(prep: 'SF.Prep', nat: 'SF.Native', fill: int, profile: str
            ) -> Dict[str, Any]:
    """One run of a case: the canonical state after the call against the
    reference's (routine mode), the declared outputs, the sound events, the
    native thinker list's checks (mobjstate's), the stray writes
    (evworld's rule: mobjstate's places, the parts' scratch blocks, the
    sides a switch changes); the cycles from the routine's entry to its
    return, the lowest S."""
    spec = prep.spec
    res: Dict[str, Any] = {'case': prep.case.path.name if prep.case.path
                           else prep.case.header.get('note', 'synthetic'),
                           'entry': prep.key, 'fill': '%02x' % fill,
                           'profile': profile, 'ok': False}
    if prep.ref.problems:
        res['error'] = 'bridge: ' + '; '.join(prep.ref.problems[:3])
        return res
    img = prep.image(nat, fill)
    prep.pre_state(img, fill)
    entry = nat.b.labels[spec['native']]
    img.poke_word('dg_entry', entry)
    img.poke_label('dg_grp', bytes([nat.group(spec['native'])]))
    events = ['pc %X@1 snapshot start' % entry,
              'pc %X@1 snapshot ret' % nat.ret]
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-evfloor-', dir=str(BUILD)))
    try:
        r = G.run(img, work, GL.MODES['ROUTINE'], None,
                  regs=tuple(prep.regs), events=events,
                  banks=list(prep.banks) + [LL.GTEST],
                  profile=profile, write_log=MS.LOG_RANGES,
                  cycles=SF.RUN_CYCLES)
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
        writes = MS.read_log(work / 'writes.log')
        st = EW.stray([w for _, w in writes], nat.b, prep.header)
        res['stray'] = len(st)
        res['stray_first'] = st[:4]
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    from native import setupcheck as SC
    nat_state = PortReader(prep.mf).read(SC.port_memory(m))
    diff = gcanon.compare(prep.ref.s_out, nat_state, 'routine')
    diff += LN.outputs(prep, nat, m)
    diff += MS.native_checks(m)
    got, want = SF.sounds(m), expected_sounds(prep)
    res['sounds'] = len(got)
    if got != want:
        diff.append('sound events %s, expected %s' % (got[:4], want[:4]))
    if st:
        diff.append('%d stray writes: %s' % (len(st), st[:4]))
    res['diff'] = diff[:12]
    res['ok'] = not diff
    return res


# ---------------------------------------------------------------------------
# The synthetic cases (ref816 --call on an in-play state of each map)
# ---------------------------------------------------------------------------

def map_bases() -> Dict[int, Path]:
    """A captured P_UpdateSpecials of the tour on each map."""
    out: Dict[int, Path] = {}
    a = CL.Linkmap().address(GR.TIC_GAMEMAP)
    for run, hit, _ in LN.base_calls():
        p = case_path(run, BASE_KEY, hit)
        if not p.exists():
            continue
        gm = GC.load_case(p).entry.u16(a)
        if gm not in out:
            out[gm] = p
    return out


def branch_tags(base: 'EW.Base') -> Dict[str, List[int]]:
    """The tags whose sectors take EV_DoFloor's two branches the lines'
    calls do not reach (from the base's canonical state): 'same', a
    sector whose highest floor next to it is its own (turboLower: no + 8);
    'clamp', one whose lowest ceiling next to it is above its own
    (raiseFloor: the dest is its ceiling)."""
    o = base.ref.s_in['objects']
    near: Dict[int, set] = {}
    for line in o['line'].values():
        s0, s1 = line['sidenum']
        if s1 in (-1, None, 0xFFFF) or s0 in (-1, None, 0xFFFF):
            continue
        f, b = o['side'][s0]['sector'].id, o['side'][s1]['sector'].id
        near.setdefault(f, set()).add(b)
        near.setdefault(b, set()).add(f)
    out: Dict[str, List[int]] = {'same': [], 'clamp': []}
    for i, s in sorted(o['sector'].items()):
        others = [o['sector'][k] for k in near.get(i, ()) if k != i]
        if not s['tag'] or not others:
            continue
        if max(x['floorheight'] for x in others) == s['floorheight']:
            out['same'].append(s['tag'])
        if min(x['ceilingheight'] for x in others) > s['ceilingheight']:
            out['clamp'].append(s['tag'])
    return out


def synthetic_plan(base: 'EW.Base', seen: Dict[Any, int]
                   ) -> List[Dict[str, Any]]:
    """The map's synthetic calls. Every line whose special LSTAB sends to
    this part's handlers, by the player, one line of each (special, tag)
    on a map (the others have the same effect: a handler reads only the
    line's tag; the lean cut), until LEAN calls of the handler over the
    maps planned so far (`seen` counts them; a special's first line is
    always planned); the first line of
    each special over the maps is used twice (`times`: the second use on
    the state the first left, its special put back when the first used it
    up: the tagged floors busy); on the first map with a floor line,
    EV_DoFloor itself with lowerFloor (0) and a type past the table; and
    EV_DoFloor itself on the first lines of branch_tags' tags."""
    c = base.c
    out: List[Dict[str, Any]] = []

    def dp(*ptrs: int) -> List[Tuple[int, bytes]]:
        return [(base.dp + 4 * k, (p & 0xFFFFFF).to_bytes(4, 'little'))
                for k, p in enumerate(ptrs)]
    use = EW.usetab_specials(base.m)
    cross = EW.crosstab_specials(base.m)
    for i in range(base.nlines):
        sp = base.line_special(i)
        for key, table in ((USE, use), (CROSS, cross)):
            if sp not in table or table[sp][0] not in MINE:
                continue
            handler = table[sp][0]
            tag = base.line_tag(i)
            if (base.gamemap, key, sp, tag) in seen:
                continue        # the same effect as a line planned already
            seen[(base.gamemap, key, sp, tag)] = 1
            if seen.get((key, sp)) and seen.get(handler, 0) >= LEAN:
                continue
            note = 'line %d (special %d, tag %d)' % (i, sp, base.line_tag(i))
            if key == USE:
                pokes = dp(base.player_mo, base.line(i))
                regs: Dict[str, int] = {}
            else:
                pokes = dp(base.line(i), base.player_mo)
                regs = {'a': 0}
            rec = {'key': key, 'pokes': pokes, 'regs': regs,
                   'note': note + ', the player', 'times': 1,
                   'handler': handler}
            if not seen.get((key, sp)):
                seen[(key, sp)] = 1
                rec['times'] = 2        # again on the state left: busy
                rec['again_pokes'] = [  # (its special back if used up)
                    (base.line(i) + c['UO_LINE_SPECIAL'],
                     sp.to_bytes(2, 'little'))]
            seen[handler] = seen.get(handler, 0) + rec['times']
            out.append(rec)
            if handler == 'p_switch65.s:lnFloor' and \
                    not seen.get('direct'):
                seen['direct'] = 1
                for t in (c['UC_LOWERFLOOR'], OTHER_TYPE):
                    out.append({'key': DOFLOOR, 'pokes': dp(base.line(i)),
                                'regs': {'a': t}, 'times': 1,
                                'handler': DOFLOOR,
                                'note': note + ', EV_DoFloor type %d' % t})
    # EV_DoFloor's turboLower with no + 8 and raiseFloor up to the ceiling
    # (branch_tags), once over the maps, on a line with the tag
    tags = branch_tags(base)
    for what, t in (('same', c['UC_TURBOLOWER']),
                    ('clamp', c['UC_RAISEFLOOR'])):
        if seen.get(what):
            continue
        lines = [i for i in range(base.nlines)
                 if base.line_tag(i) in tags[what][:1]]
        if lines:
            seen[what] = 1
            i = lines[0]
            out.append({'key': DOFLOOR, 'pokes': dp(base.line(i)),
                        'regs': {'a': t}, 'times': 1, 'handler': DOFLOOR,
                        'note': 'line %d (tag %d), EV_DoFloor type %d (%s)'
                                % (i, base.line_tag(i), t, what)})
    return out


def make_synthetic(base_path: Path, plan: List[Dict[str, Any]]
                   ) -> List[Dict[str, Any]]:
    """The planned calls run on ref816, each with its call state and
    writes; a call is made `times` times, each on the state the one before
    left (with `again_pokes` from the second on)."""
    base = EW.Base(base_path)
    t = base.table
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-evfloor-syn-',
                                 dir=str(BUILD)))
    out: List[Dict[str, Any]] = []
    try:
        for rec in plan:
            address = t.address(rec['key'])
            pre: List[Tuple[int, bytes]] = []
            for k in range(rec.get('times', 1)):
                pokes = list(rec['pokes']) + (
                    list(rec.get('again_pokes', [])) if k else [])
                call, writes = EW.ref_call(address, pre, pokes, rec['regs'],
                                           base.case, work)
                note = rec['note'] + ('' if k == 0 else ', use %d' % (k + 1))
                out.append(dict(rec, note=note, address=address, call=call,
                                pre=[[a, d.hex()] for a, d in pre],
                                pokes=[[a, d.hex()] for a, d in pokes],
                                again_pokes=None,
                                writes=[[a, d.hex()] for a, d in writes],
                                base=str(base_path.relative_to(OUT))))
                pre = list(pre) + pokes + list(writes)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return out


def _syn_job(item: Tuple[str, List[Dict[str, Any]]]):
    path, plan = item
    return make_synthetic(Path(path), plan)


def write_synthetic(jobs: int = 2) -> Dict[str, int]:
    SYN.mkdir(parents=True, exist_ok=True)
    bases = map_bases()
    absent = sorted(set(range(1, 10)) - set(bases))
    if absent:
        raise PartError('no in-play state of E1M%s (--capture)' % absent)
    seen: Dict[Any, int] = {}
    plans = []
    for m in sorted(bases):
        plans.append((str(bases[m]), synthetic_plan(EW.Base(bases[m]),
                                                    seen)))
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        got = list(pool.map(_syn_job, plans))
    counts = {}
    for m, recs in zip(sorted(bases), got):
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
    for a, d in rec['pre'] + rec['pokes']:
        entry.write(a, bytes.fromhex(d))
    after = entry.copy()
    for a, d in rec['writes']:
        after.write(a, bytes.fromhex(d))
    header = dict(b.header, routine=rec['key'], note=rec['note'],
                  call=rec['call'], hit=0,
                  writes=[[a, len(d) // 2] for a, d in rec['writes']])
    return GC.Case(header, entry, after, None)


# ---------------------------------------------------------------------------
# The checkpoint (--check)
# ---------------------------------------------------------------------------

def _check_job(job) -> List[Dict[str, Any]]:
    kind, items, obj, fills, profiles = job
    GC.CASES = CASES
    nat = SF.Native(Path(obj))
    spec_all = args()
    out: List[Dict[str, Any]] = []
    for item in items:
        if kind == 'case':
            key, path = item
            name = '/'.join(Path(path).parts[-3:])
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
            case = synthetic_case(item)
        try:
            prep = SF.Prep(case, key, spec_all[key])
            path = path_of(key, prep.ref)
        except Exception as error:      # reported per case, never hidden
            out.append({'case': name, 'entry': key, 'ok': False,
                        'synthetic': kind != 'case',
                        'error': '%s: %s' % (type(error).__name__, error)})
            continue
        for fill in fills:
            for profile in profiles:
                try:
                    r = run_one(prep, nat, fill, profile)
                except Exception as error:
                    r = {'entry': key, 'fill': '%02x' % fill,
                         'profile': profile, 'ok': False,
                         'error': '%s: %s' % (type(error).__name__, error)}
                r.update(case=name, path=path, synthetic=kind != 'case',
                         handler=item.get('handler') if kind != 'case'
                         else key)
                out.append(r)
    return out


def check_jobs(keys: Sequence[str] = ALL_KEYS, synthetic: bool = True,
               captured_: bool = True, obj: Path = OUT,
               fills: Sequence[int] = FILLS,
               profiles: Sequence[str] = PROFILES,
               names: Optional[Sequence[str]] = None, select=None,
               sample: int = 1, chunk: int = 6) -> List[Tuple]:
    jobs: List[Tuple] = []
    if captured_:
        for key in keys:
            if key not in ENTRIES:
                continue
            ps = captured(key)[::sample]
            for i in range(0, len(ps), chunk):
                jobs.append(('case', [(key, str(p)) for p in
                                      ps[i:i + chunk]], str(obj),
                             tuple(fills), tuple(profiles)))
    if synthetic:
        for name in (names or synthetic_names()):
            recs = [r for r in load_synthetic(name) if r['key'] in keys and
                    (select is None or select(r))][::sample]
            for i in range(0, len(recs), chunk):
                jobs.append(('synthetic', recs[i:i + chunk], str(obj),
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
            if progress and (i + 1) % 5 == 0:
                say('  %d of %d jobs, %d runs, %d failed (%.0f s)' % (
                    i + 1, len(jobs), len(out),
                    sum(1 for r in out if not r.get('ok')),
                    time.time() - start))
    return out


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Per entry (the synthetic calls through P_UseSpecialLine and
    P_CrossSpecialLine also by the handler they reach)."""
    entries: Dict[str, Any] = {}
    groups = [(key, lambda r, k=key: r.get('entry') == k)
              for key in ALL_KEYS]
    groups += [(h, lambda r, h=h: r.get('handler') == h) for h in MINE]
    for key, pick in groups:
        rs = [r for r in results if pick(r)]
        cases = {(r.get('case'), bool(r.get('synthetic'))) for r in rs}
        e: Dict[str, Any] = {
            'calls_in_survey': len(survey_calls(key)) if key in ENTRIES
            else None,
            'cases_eligible': len(survey_calls(key)) if key in ENTRIES
            else None,
            'cases_captured': sum(1 for _, s in cases if not s),
            'cases_synthetic': sum(1 for _, s in cases if s),
            'runs': len(rs),
            'failures': sum(1 for r in rs if not r.get('ok')),
            'stray_writes': sum(r.get('stray') or 0 for r in rs),
            'paths': {}, 'cycles': {}}
        for r in rs:
            if 'path' in r and r.get('profile') == PROFILES[0]:
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
# The planted bugs (--plants): the three most likely mistakes (lean)
# ---------------------------------------------------------------------------

PLANTS = {
    # the stairs following the other side: the step is the line's back
    # sector, the next one its front
    'stairs-other-side': ('stairs', [(
        '''        ldy #LINE_SIZE          ; the front sector is this step''',
        '''        ldy #LINE_SIZE + 1      ; (planted: the back one)'''), (
        '''        ldy #LINE_SIZE + 1
        lda (GC_LP),y
        sta SB_T''',
        '''        ldy #LINE_SIZE          ; (planted: the front one)
        lda (GC_LP),y
        sta SB_T''')]),
    # the donut's destination: the pool's own (outer) floor, not the model's
    'donut-outer-floor': ('donut', [(
        '''.macro S3FLOOR
        lda SB_S3''',
        '''.macro S3FLOOR
        lda SB_S2                       ; (planted: the pool's floor)''')]),
    # turboLower at FLOORSPEED, not four times it
    'turbo-speed': ('turbo', [(
        '        lda #4 * FLOORSPEED_HI',
        '        lda #FLOORSPEED_HI      ; (planted: x 1)')]),
}


def plant_build(name: str, tmp: Path) -> Path:
    _, edits = PLANTS[name]
    src = tmp / 'src'
    files = list(G.PLANT_COPY) + ['game/%s/%s' % (PART, f) for f in
                                  ('part.mk', 'evfloor.s')]
    for f in files:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
    target = src / 'game' / PART / 'evfloor.s'
    text = target.read_text()
    for old, new in edits:
        if text.count(old) != 1:
            raise PartError('the planted bug %s no longer applies: %r' % (
                name, old[:60]))
        text = text.replace(old, new)
    target.write_text(text)
    return build(game=tmp / 'game', source=src)


STAIRS_H = 'p_switch65.s:lnStairs'
DONUT_H = 'p_switch65.s:lnDonut'
TURBO = (36, 70, 98)            # the turboLower specials (spectab)


def plant_select(check: str):
    if check == 'stairs':
        return lambda r: r.get('handler') == STAIRS_H and 'use 2' not in \
            r['note']
    if check == 'donut':
        return lambda r: r.get('handler') == DONUT_H and 'use 2' not in \
            r['note']
    if check == 'turbo':
        return lambda r: any('(special %d,' % s in r['note'] for s in TURBO) \
            and 'use 2' not in r['note']
    raise PartError('no check %s' % check)


def plant_jobs(check: str, obj: Path) -> List[Tuple]:
    one = dict(fills=(FILLS[0],), profiles=(PROFILES[0],))
    return check_jobs(keys=(USE, CROSS), captured_=False, obj=obj,
                      select=plant_select(check), **one)


def plants(names: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    out = {}
    for name in (names or list(PLANTS)):
        check = PLANTS[name][0]
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-evfloor-plant-',
                                    dir=str(BUILD)))
        try:
            obj = plant_build(name, tmp)
            res = run_jobs(plant_jobs(check, obj), workers=2, progress=False)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        bad = [r for r in res if not r.get('ok')]
        r = {'check': check, 'runs': len(res), 'failed': len(bad),
             'caught': bool(bad),
             'first': (bad[0].get('diff') or [bad[0].get('error') or
                                              bad[0].get('ended')])[:2]
             if bad else None}
        out[name] = r
        say('%-20s %-6s %s' % (name, check, 'caught: %d of %d runs fail, %s'
                               % (r['failed'], r['runs'], r['first'])
                               if r['caught'] else 'NOT CAUGHT (%d runs)' %
                               r['runs']))
    return out


# ---------------------------------------------------------------------------
# Sizes (docs/GAME.md 4.7: the part's budget)
# ---------------------------------------------------------------------------

BUDGET = next(p['native'] for p in GL.PARTS if p['name'] == PART)
UPSTREAM_BYTES = next(p['up'] for p in GL.PARTS if p['name'] == PART)
LABELS = ('EV_DoFloor', 'newFloor', 'floorUp', 'setDest', 'halfSpeed',
          'EV_BuildStairs', 'stairStep', 'nextStep', 'EV_DoDonut',
          'lnFloor', 'lnStairs', 'lnDonut')


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """The part's bytes (evfloor.o) against its budget; each routine's
    bytes and group."""
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
        if module == PART and f and f[0] in b.segments:
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
    total = sum(hi - lo for _, lo, hi in chunks)
    return {'bytes': total, 'budget': BUDGET, 'upstream': UPSTREAM_BYTES,
            'over_10_percent': total > BUDGET * 1.1, 'routines': routines}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def write_report(results: Optional[Sequence[Dict[str, Any]]] = None,
                 **parts) -> Dict[str, Any]:
    rep: Dict[str, Any] = {}
    if REPORT.exists():
        rep = json.loads(REPORT.read_text())
    rep.update(format='game-part-report 1', part=PART,
               wave=next(p['wave'] for p in GL.PARTS if p['name'] == PART),
               lean='at most %d calls a routine, fill $A5 only (the owner\'s '
                    'lean checks of 2026-10-02)' % LEAN,
               fills=['%02x' % f for f in FILLS], profiles=list(PROFILES),
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
    rep['build_kb'] = EW.du_kb(OUT)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, indent=1, default=str) + '\n')
    return rep


def print_report(rep: Dict[str, Any]) -> None:
    for key, e in rep.get('entries', {}).items():
        cyc = '; '.join('%s %s/%s us' % (p, c['median_us'], c['worst_us'])
                        for p, c in e['cycles'].items())
        say('%-34s %3d+%-3d cases %4d runs %d failed %d stray, S %s; %s' % (
            key, e['cases_captured'], e['cases_synthetic'], e['runs'],
            e['failures'], e['stray_writes'], e['lowest_s'], cyc))
    if 'sizes' in rep:
        sz = rep['sizes']
        say('bytes %d of %d (upstream %d)' % (sz['bytes'], sz['budget'],
                                             sz['upstream']))
    for name, r in rep.get('plants', {}).items():
        say('planted %-20s %s' % (name, 'caught' if r['caught'] else
                                  'NOT CAUGHT'))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--synthetic', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--keys', default=None)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--json', type=Path)
    a = parser.parse_args(argv)
    why = missing()
    if why:
        print('cannot run: %s' % why, file=sys.stderr)
        return 2
    if a.capture:
        keys = a.keys.split(',') if a.keys else list(ENTRIES)
        say('%d cases made' % capture(keys))
        return 0
    if a.synthetic:
        start = time.time()
        counts = write_synthetic(a.jobs)
        say('synthetic calls: %s (%.0f s)' % (counts, time.time() - start))
        return 0
    if a.check:
        keys = a.keys.split(',') if a.keys else list(ALL_KEYS)
        start = time.time()
        build()
        jobs = check_jobs(keys)
        say('%d jobs' % len(jobs))
        res = run_jobs(jobs, a.jobs)
        rep = write_report(res, sizes=sizes(), check_seconds=round(
            time.time() - start))
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
