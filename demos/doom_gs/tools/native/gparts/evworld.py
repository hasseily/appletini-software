#!/usr/bin/env python3
"""Part evworld's checkpoint (milestone 10, docs/GAME.md 2.4 row evworld,
3.5; docs/game-parts/evworld.md): routine mode on the part's entries, its
synthetic cases on the nine maps and its planted bugs, in the lean form the
owner asked for on 2026-10-02 (at most LEAN calls a routine, one poisoned
machine, $A5).

Usage:  python3 tools/native/gparts/evworld.py --capture
        python3 tools/native/gparts/evworld.py --synthetic [--jobs 2]
        python3 tools/native/gparts/evworld.py --check [--jobs 2]
        python3 tools/native/gparts/evworld.py --plants
        python3 tools/native/gparts/evworld.py --report

Everything it writes is under build/native/game/evworld/ (the part's own
directory): the cases (cases/RUN/ROUTINE/hNNNNNNNN.case.z and each run's
base.ram.z, through tools/native/gamecap.py with its case directory pointed
here), the synthetic calls (synthetic/), report.json. The shared outputs
(build/native/game/shared/) are read only.

The run machinery is part secfind's and part lines' (tools/native/gparts/
secfind.py: Ref, Prep, Native, check_writes, ref_call, MapBase; lines.py:
the outputs with the carry, the switch's place, the tables), imported as
wave 1's integration asked; this tool adds the part's choice, paths, sound
events, synthetic cases and plants.

--capture: the chosen calls of the survey's runs (every call of EV_DoDoor,
newDoor and EV_DoPlat; of EV_VerticalDoor every call in a tic where a door
starts, then calls spread evenly up to LEAN), and the tour's
P_UpdateSpecials every TOUR_STEP-th call (the in-play states of the nine
maps for the synthetic calls).

--synthetic: on each map, ref816 --call of P_UseSpecialLine (usetab) and
P_CrossSpecialLine (crosstab) of door and plat lines, through LSTAB's
lnVDoor, lnDoor and lnPlat (GAME.md 2.4: "every door and plat special of
usetab/crosstab on every line of the nine maps that has it", cut to LEAN
calls: each special on its first lines over the maps), the locked doors
with and without their key, a monster at a door, a one-sided line, and the
lines used again on the state the first use left (a door turned around, a
plat on a sector whose floordata is set).

--check: the cases from the poisoned machine $A5 under f121 and fastpath,
compared with ref816 in gcanon.py's routine mode (R1-R6), the declared
outputs of src/native/game/evworld/args.json, the sound events (R6: the
handlers' sounds, from the reference's states: docs/game-parts/evworld.md),
no stray write. Writes report.json.

--plants: each planted bug built from a scratch copy of the part's sources
in a temporary directory (deleted), run on its named check, which must
fail.
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
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))

import secfind as SF  # noqa: E402  (wave 1's machinery)
import lines as LN  # noqa: E402  (wave 2's: outputs, switches, tables)
import mobjstate as MS  # noqa: E402  (the shared stray rule)
from bridge.port import PortReader  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL, rlayout as RL  # noqa: E402
from ref816 import calls as CL  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'evworld'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
SYN = OUT / 'synthetic'
REPORT = OUT / 'report.json'
ARGS = SRC / 'game' / PART / 'args.json'
IMAGE = 'ptest'
GC.CASES = CASES                # the part's own case directory (the
#                                 imports pointed it at lines')

DODOOR = 'p_doors65.s:EV_DoDoor'
VDOOR = 'p_doors65.s:EV_VerticalDoor'
NEWDOOR = 'p_doors65.s:newDoor'
DOPLAT = 'p_plats65.s:EV_DoPlat'
ENTRIES = (DODOOR, VDOOR, NEWDOOR, DOPLAT)
USE, CROSS = LN.USE, LN.CROSS
ALL_KEYS = ENTRIES + (USE, CROSS)
BASE_KEY = LN.BASE_KEY          # the tour's P_UpdateSpecials
TOUR_STEP = LN.TOUR_STEP
LEAN = 40                       # calls a routine (the owner's lean checks)
FILLS = (0xA5,)                 # one poisoned machine (lean)
PROFILES = SF.PROFILES
BATCH = 40
SYN_FORMAT = 'evworld-synthetic 1'
DOOR_USE = (1, 26, 27, 28, 31, 32, 33, 34)     # lnVDoor's specials
LOCKS = {26: 0, 32: 0, 27: 1, 34: 1, 28: 2, 33: 2}  # special -> the key


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
    """The part's test image (make -f game.mk part P=evworld); its
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
# The calls (lean: at most LEAN a routine)
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
    """The calls of an entry the checkpoint runs: all when LEAN or fewer;
    for EV_VerticalDoor first every call in a (run, tic) where a door
    starts (newDoor's tics: the new-door branch), then calls spread evenly
    over the rest up to LEAN."""
    calls = survey_calls(key)
    if len(calls) <= LEAN:
        return calls
    starts = {(run, tic) for run, _, tic in survey_calls(NEWDOOR)}
    first = [c for c in calls if (c[0], c[2]) in starts][:LEAN]
    rest = [c for c in calls if c not in first]
    n = LEAN - len(first)
    out = first + [rest[(i * len(rest)) // n] for i in range(n)]
    return sorted(set(out), key=calls.index)


def case_path(run: str, key: str, hit: int) -> Path:
    return GC.case_dir(run, key) / ('h%08d.case.z' % hit)


def base_calls() -> List[Tuple[str, int, int]]:
    return LN.base_calls()


def capture(keys: Sequence[str] = ENTRIES, bases: bool = True) -> int:
    want: Dict[Tuple[str, str], Dict[int, int]] = {}
    for key in keys:
        for run, hit, tic in chosen(key):
            want.setdefault((run, key), {})[hit] = tic
    if bases:
        for run, hit, tic in base_calls():
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


# ---------------------------------------------------------------------------
# The paths (the branches a call takes), from the reference's states
# ---------------------------------------------------------------------------

def _ptr(ref: 'SF.Ref', text: str, when: str = 'in') -> int:
    return int.from_bytes(ref.source(text, when), 'little') & 0xFFFFFF


def objects(s: Dict[str, Any], kind: str) -> Dict[int, Dict[str, Any]]:
    return s['objects'].get(kind, {})


def new_specials(ref: 'SF.Ref', kind: str) -> List[Dict[str, Any]]:
    """The specials of a kind the call made (identities by rank among the
    thinkers of the kind: the new ones come after the entry's)."""
    before = objects(ref.s_in, kind)
    after = objects(ref.s_out, kind)
    return [after[k] for k in sorted(after) if k not in before]


def the_player(s: Dict[str, Any]) -> Dict[str, Any]:
    pl = s['objects']['player']
    return pl[min(pl)]


def vdoor_path(ref: 'SF.Ref', line_id: int, thing) -> str:
    """EV_VerticalDoor's branch for the line and the thing."""
    s = ref.s_in
    line = objects(s, 'line')[line_id]
    player = LN.is_player(s, thing)
    sp = line['special']
    if sp in LOCKS:
        if not player:
            return 'locked-monster'
        if not the_player(s)['cards'][LOCKS[sp]]:
            return 'locked-nokey'
    if line['sidenum'][1] in (-1, None, 0xFFFF):
        return 'one-sided-%s' % ('player' if player else 'monster')
    back = objects(s, 'side')[line['sidenum'][1]]['sector']
    door = objects(s, 'sector')[back.id]['ceilingdata']
    if door is not None and (sp == 1 or 26 <= sp < 29):
        d = objects(s, door.kind)[door.id]
        if d['direction'] == -1:
            return 'turn-up'
        return 'turn-down-player' if player else 'turn-monster'
    return 'new-%d%s' % (sp, '-busy' if door is not None else '')


def path_of(key: str, ref: 'SF.Ref') -> str:
    s = ref.s_in
    if key == VDOOR:
        ln = ref.ref(_ptr(ref, 'dp:_Dp:4'), ('line',))
        th = ref.ref(_ptr(ref, 'dp:_Dp+4:4'), SF.kinds_of('mobj'))
        return vdoor_path(ref, ln.id, th)
    if key in (DODOOR, DOPLAT):
        kind = 'door' if key == DODOOR else 'plat'
        made = new_specials(ref, kind)
        t = ref.source('a')[0]
        return '%s-type%d-%d-made' % (kind, t, len(made))
    if key == NEWDOOR:
        return 'new'
    if key in (USE, CROSS):
        p = LN.path_of(key, ref)
        if 'lnVDoor' in p:
            ln = ref.ref(_ptr(ref, 'dp:_Dp+4:4'), ('line',))
            th = ref.ref(_ptr(ref, 'dp:_Dp:4'), SF.kinds_of('mobj'))
            p += ':' + vdoor_path(ref, ln.id, th)
        elif 'lnDoor' in p or 'lnPlat' in p:
            kind = 'door' if 'lnDoor' in p else 'plat'
            p += ':%d-made' % len(new_specials(ref, kind))
        return p
    return 'call'


# ---------------------------------------------------------------------------
# The sound events (R6): upstream's handlers' sounds, from its states
# ---------------------------------------------------------------------------

def door_sounds(ref: 'SF.Ref', tic: int, made: List[Dict[str, Any]],
                c: Dict[str, int]) -> List[Tuple[int, int, int, int]]:
    """EV_DoDoor's: each new door in order, close30ThenOpen the close
    sound, normal and open the open sound unless its top is the sector's
    ceiling at the call."""
    out = []
    for d in made:
        sec = d['sector'].id
        if d['type'] == c['UC_CLOSE30THENOPEN']:
            out.append((tic, 1, c['UC_SFX_DORCLS'], 0x8000 | sec))
        elif d['type'] in (c['UC_NORMAL'], c['UC_DOPEN']):
            ceil = objects(ref.s_in, 'sector')[sec]['ceilingheight']
            if d['topheight'] != ceil:
                out.append((tic, 1, c['UC_SFX_DOROPN'], 0x8000 | sec))
    return out


def plat_sounds(tic: int, made: List[Dict[str, Any]], c: Dict[str, int]
                ) -> List[Tuple[int, int, int, int]]:
    out = []
    for p in made:
        sec = p['sector'].id
        if p['type'] == c['UC_RAISETONEARESTANDCHANGE']:
            out.append((tic, 1, c['UC_SFX_STNMOV'], 0x8000 | sec))
        elif p['type'] == c['UC_DOWNWAITUPSTAY']:
            out.append((tic, 1, c['UC_SFX_PSTART'], 0x8000 | sec))
    return out


def vdoor_sounds(prep: 'SF.Prep', tic: int, line_id: int, thing,
                 c: Dict[str, int]) -> List[Tuple[int, int, int, int]]:
    ref = prep.ref
    path = vdoor_path(ref, line_id, thing)
    if path in ('locked-nokey', 'one-sided-player'):
        mo = the_player(ref.s_in)['mo']
        return [(tic, 0, c['UC_SFX_OOF'], SF.native_value(prep.mf, 'mobj',
                                                          mo))]
    if path.startswith('new-'):
        made = new_specials(ref, 'door')
        if len(made) != 1:
            raise PartError('EV_VerticalDoor made %d doors' % len(made))
        return [(tic, 1, c['UC_SFX_DOROPN'], 0x8000 | made[0]['sector'].id)]
    return []


def expected_sounds(prep: 'SF.Prep') -> List[Tuple[int, int, int, int]]:
    ref = prep.ref
    c = uconst()
    tic = ref.s_in['globals']['g_game65.s:_g_gametic'] & 0xFFFF
    key = prep.key
    if key == DODOOR:
        return door_sounds(ref, tic, new_specials(ref, 'door'), c)
    if key == DOPLAT:
        return plat_sounds(tic, new_specials(ref, 'plat'), c)
    if key == VDOOR:
        ln = ref.ref(_ptr(ref, 'dp:_Dp:4'), ('line',))
        th = ref.ref(_ptr(ref, 'dp:_Dp+4:4'), SF.kinds_of('mobj'))
        return vdoor_sounds(prep, tic, ln.id, th, c)
    if key == NEWDOOR:
        return []
    if key in (USE, CROSS):
        o = ref.s_in['objects']
        th = ref.ref(_ptr(ref, 'dp:_Dp:4' if key == USE else 'dp:_Dp+4:4'),
                     SF.kinds_of('mobj'))
        ln = ref.ref(_ptr(ref, 'dp:_Dp+4:4' if key == USE else 'dp:_Dp:4'),
                     ('line',))
        path = LN.path_of(key, ref)
        how, row = LN.find_special(ref, o['line'][ln.id], 'usetab' if
                                   key == USE else 'crosstab')
        if row is None or path.startswith('monster-') and (
                'not' in path or 'secret' in path):
            return []
        name = row[1].split(':')[1]
        if name == 'lnVDoor':
            got = vdoor_sounds(prep, tic, ln.id, th, c)
            started = 1
        elif name == 'lnDoor':
            made = new_specials(ref, 'door')
            got, started = door_sounds(ref, tic, made, c), int(bool(made))
        elif name == 'lnPlat':
            made = new_specials(ref, 'plat')
            got, started = plat_sounds(tic, made, c), int(bool(made))
        else:
            raise PartError('%s: not a handler of this part' % name)
        if key == USE and row[3] in (1, 2) and started:
            sw = LN.switch_place(ref, o['line'][ln.id])
            if sw != 'none':
                sec = o['side'][o['line'][ln.id]['sidenum'][0]]['sector']
                got.append((tic, 1, c['UC_SFX_SWTCHN'], 0x8000 | sec.id))
        return got
    return []


# ---------------------------------------------------------------------------
# One run (secfind's run_one with lines' outputs and this part's sounds)
# ---------------------------------------------------------------------------

def allowed_main(b) -> List[Tuple[int, int]]:
    """mobjstate's places (the object API's, the globals and the tic
    phase's after them, W's API buffers: the shared stray rule of wave 2's
    integration) and the parts' scratch blocks (W $9A00-$9DFF: R1; the
    part's own and its callees', secfind's finders')."""
    lo, hi = GL.WR['SCRATCH']
    return MS.allowed_main(b) + [(lo, hi)]


def stray(writes, b, header: Dict[str, Any]) -> List[str]:
    """CPU writes outside the allowed places (mobjstate.stray's rule with
    the part's scratch block: a new special's record and the free lists'
    globals are the allowed places of the kinds the game state is made
    of)."""
    allowed = allowed_main(b)
    desc = b.segments['DESC']
    drv = b.segments['DRIVER']
    loader = b.segments['RLOAD']
    far = b.segments['RFAR']
    aux = MS.allowed_aux(header)
    # the sides too: P_ChangeSwitchTexture (part lines) writes a switch's
    # side back (sd_put) after a door or plat button started
    sides = RL.SIDES
    aux[RL.LVMAP] = aux.get(RL.LVMAP, []) + [
        (sides.base, sides.base + sides.stride * sides.capacity)]
    mfar = b.segments.get('MATHFAR')
    patched = MS.mt_far_operands(b)
    out = []
    for w in writes:
        if w.storage == 'main':
            if w.offset < 0x0200 or any(lo <= w.offset < hi
                                         for lo, hi in allowed):
                continue
            if loader[0] <= w.pc <= loader[1] and 0x6000 <= w.offset:
                continue
            if far[0] <= w.pc <= far[1] and \
                    GL.WR['SLOT1'][0] <= w.offset < GL.WR['SLOT2'][1]:
                continue
        elif w.storage == 'lc' and drv[0] <= w.pc <= drv[1] and (
                desc[0] <= w.offset <= desc[1] or w.offset >= 0xFFFE or
                any(lo <= w.offset < hi for lo, hi in allowed)):
            continue
        elif w.storage == 'lc1' and mfar and \
                mfar[0] <= w.pc <= mfar[1] and w.offset in patched:
            continue
        elif w.storage == 'aux' and any(
                lo <= w.offset < hi for lo, hi in aux.get(w.bank, ())):
            continue
        out.append('pc $%04X wrote %s %d $%04X' % (w.pc, w.storage, w.bank,
                                                     w.offset))
    return out


def run_one(prep: 'SF.Prep', nat: 'SF.Native', fill: int, profile: str
            ) -> Dict[str, Any]:
    """One run of a case: the canonical state after the call against the
    reference's (routine mode), the declared outputs, the sound events, the
    native thinker list's checks (mobjstate's), the stray writes; the
    cycles from the routine's entry to its return, the lowest S."""
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
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-evworld-', dir=str(BUILD)))
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
        st = stray([w for _, w in writes], nat.b, prep.header)
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
    for run, hit, _ in base_calls():
        p = case_path(run, BASE_KEY, hit)
        if not p.exists():
            continue
        gm = GC.load_case(p).entry.u16(a)
        if gm not in out:
            out[gm] = p
    return out


class Base(LN.Base):
    """An in-play state (lines' Base): the sides of a line, the cards."""

    def line_side1(self, i: int) -> int:
        return self.m.u16(self.line(i) + self.c['UO_LINE_SIDENUM'] + 2)

    def cards(self) -> int:
        return self.player + self.c['UO_PL_CARDS']


def usetab_specials(m) -> Dict[int, Tuple[str, int, int]]:
    return {row[0]: (row[1], row[2], row[3])
            for row in LN.Tables.get(m)['usetab']}


def crosstab_specials(m) -> Dict[int, Tuple[str, int, int]]:
    return {row[0]: (row[1], row[2], row[3])
            for row in LN.Tables.get(m)['crosstab']}


MINE = ('p_switch65.s:lnVDoor', 'p_switch65.s:lnDoor', 'p_switch65.s:lnPlat')


def synthetic_plan(base: Base, seen: Dict[Tuple[str, int], int]
                   ) -> List[Dict[str, Any]]:
    """The map's synthetic calls. `seen` counts each (key, special) over
    the maps planned so far: a special's first line over the nine maps
    gets its calls (the lean cut of 'every line that has it'): the player
    (with its key for a locked door, and first without it), a monster at
    the doors monsters open (1, 32-34), and the player again on the state
    the first use left (`times`): a repeatable manual door twice more (sent
    down, then back up), a used-up one (31-34) once more with its special
    put back (a new door on a sector whose ceilingdata is set), a button
    (mode 2) and a walk-again line (crosstab mode 0) once more (the sector
    busy: a plat on a sector whose floordata is set, a door on one whose
    ceilingdata is)."""
    c = base.c
    out: List[Dict[str, Any]] = []

    def dp(*ptrs: int) -> List[Tuple[int, bytes]]:
        return [(base.dp + 4 * k, (p & 0xFFFFFF).to_bytes(4, 'little'))
                for k, p in enumerate(ptrs)]
    use = usetab_specials(base.m)
    cross = crosstab_specials(base.m)
    mon_at, _ = base.monster()
    cards = base.cards()
    for i in range(base.nlines):
        sp = base.line_special(i)
        for key, table in ((USE, use), (CROSS, cross)):
            if sp not in table or table[sp][0] not in MINE or \
                    seen.get((key, sp)):
                continue
            seen[(key, sp)] = 1
            note = 'line %d (special %d, tag %d)' % (i, sp, base.line_tag(i))
            handler = table[sp][0]
            mode = table[sp][2]
            if key == CROSS:            # walk again (mode 0): twice
                out.append({'key': CROSS, 'pokes': dp(base.line(i),
                                                      base.player_mo),
                            'regs': {'a': 0}, 'note': note + ', the player',
                            'times': 2 if mode == 0 else 1})
                continue
            pk = dp(base.player_mo, base.line(i))
            who = ', the player'
            if sp in LOCKS:     # without the key, then with it
                k = cards + 2 * LOCKS[sp]
                out.append({'key': USE, 'regs': {},
                            'pokes': pk + [(k, (0).to_bytes(2, 'little'))],
                            'note': note + ', the player without the key'})
                pk = pk + [(k, (1).to_bytes(2, 'little'))]
                who = ', the player with the key'
            rec = {'key': USE, 'pokes': pk, 'regs': {}, 'note': note + who,
                   'times': 1}
            if handler == 'p_switch65.s:lnVDoor' and sp < 31:
                rec['times'] = 3        # sent down, then back up
            elif handler == 'p_switch65.s:lnVDoor':
                rec['times'] = 2        # used up: the special again, a
                rec['again_pokes'] = [  #   new door on a busy sector
                    (base.line(i) + c['UO_LINE_SPECIAL'],
                     sp.to_bytes(2, 'little'))]
            elif mode == 2:
                rec['times'] = 2        # a button again: the sector busy
            out.append(rec)
            if sp in (1, 32, 33, 34):   # the doors monsters open
                out.append({'key': USE, 'pokes': dp(mon_at, base.line(i)),
                            'regs': {}, 'note': note + ', a monster'})
    # a one-sided line given special 1 (EV_VerticalDoor's oof): the player
    # and a monster, on the first map
    if not seen.get(('one-sided', 0)):
        one = [i for i in range(base.nlines)
               if base.line_side1(i) == 0xFFFF and not base.line_special(i)]
        if one:
            seen[('one-sided', 0)] = 1
            sp_at = base.line(one[0]) + c['UO_LINE_SPECIAL']
            for who, at in (('the player', base.player_mo),
                            ('a monster', mon_at)):
                out.append({'key': USE, 'pokes': dp(at, base.line(one[0])) +
                            [(sp_at, (1).to_bytes(2, 'little'))], 'regs': {},
                            'note': 'one-sided line %d as 1, %s' % (one[0],
                                                                    who)})
    return out


def ref_call(address: int, pre: Sequence[Tuple[int, bytes]],
             pokes: Sequence[Tuple[int, bytes]], regs: Dict[str, int],
             base: 'GC.Case', work: Path):
    """ref816 --call on the base's entry with `pre` (an earlier call's
    writes) and the pokes."""
    entry = base.entry.copy()
    entry.header = base.entry.header
    for a, d in pre:
        entry.write(a, d)
    (work / 'entry.img').write_bytes(entry.image_bytes())
    return SF.ref_call(address, pokes, regs, work)


def make_synthetic(base_path: Path, plan: List[Dict[str, Any]]
                   ) -> List[Dict[str, Any]]:
    """The planned calls run on ref816, each with its call state and
    writes; a call is made `times` times, each on the state the one before
    left (with `again_pokes` from the second on)."""
    base = Base(base_path)
    t = base.table
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-evworld-syn-',
                                 dir=str(BUILD)))
    out: List[Dict[str, Any]] = []
    try:
        for rec in plan:
            address = t.address(rec['key'])
            pre: List[Tuple[int, bytes]] = []
            for k in range(rec.get('times', 1)):
                pokes = list(rec['pokes']) + (
                    list(rec.get('again_pokes', [])) if k else [])
                call, writes = ref_call(address, pre, pokes, rec['regs'],
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
    seen: Dict[Tuple[str, int], int] = {}
    plans = []
    for m in sorted(bases):
        plans.append((str(bases[m]), synthetic_plan(Base(bases[m]), seen)))
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
                r.update(case=name, path=path, synthetic=kind != 'case')
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
            if progress and (i + 1) % 10 == 0:
                say('  %d of %d jobs, %d runs, %d failed (%.0f s)' % (
                    i + 1, len(jobs), len(out),
                    sum(1 for r in out if not r.get('ok')),
                    time.time() - start))
    return out


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    entries: Dict[str, Any] = {}
    for key in ALL_KEYS:
        rs = [r for r in results if r.get('entry') == key]
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
    # the door's top without - 4 FRACUNIT (topLowest)
    'top-without-4': ('doors', [(
        '''        lda GA_2
        sbc #4''',
        '''        lda GA_2
        sbc #0                  ; (planted: no - 4)''')]),
    # the plat's low from the other finder (the highest floor next to it)
    'low-other-finder': ('plats', [(
        '        FCALL P_FindLowestFloorSurrounding     ; above the '
        'sector\'s floor)',
        '        FCALL P_FindHighestFloorSurrounding    ; (planted)')]),
    # a plat started on a sector whose floordata is set (the busy test)
    'plat-busy-ignored': ('plats', [(
        '''        ldy #SEC_SIZE + SG_FLOORD + 1
        lda (GC_SP),y
        cmp #$FF
        bne @loop''',
        '''        ldy #SEC_SIZE + SG_FLOORD + 1
        lda (GC_SP),y
        cmp #$FF
        nop                     ; (planted: never busy)
        nop''')]),
}


def plant_build(name: str, tmp: Path) -> Path:
    _, edits = PLANTS[name]
    src = tmp / 'src'
    files = list(G.PLANT_COPY) + ['game/%s/%s' % (PART, f) for f in
                                  ('part.mk', 'evworld.s')]
    for f in files:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
    target = src / 'game' / PART / 'evworld.s'
    text = target.read_text()
    for old, new in edits:
        if text.count(old) != 1:
            raise PartError('the planted bug %s no longer applies: %r' % (
                name, old[:60]))
        text = text.replace(old, new)
    target.write_text(text)
    return build(game=tmp / 'game', source=src)


def plant_jobs(check: str, obj: Path) -> List[Tuple]:
    one = dict(fills=(FILLS[0],), profiles=(PROFILES[0],))
    if check == 'doors':
        return check_jobs(keys=(USE, CROSS), captured_=False, obj=obj,
                          select=lambda r: 'use' not in r['note'] and
                          'monster' not in r['note'] and 'no key' not in
                          r['note'], names=('e1m1', 'e1m2'), **one)
    if check == 'plats':
        return check_jobs(keys=(USE, CROSS), captured_=False, obj=obj,
                          select=lambda r: r['key'] in (USE, CROSS) and
                          ('special 62' in r['note'] or 'special 88' in
                           r['note'] or 'special 22' in r['note'] or
                           'special 20' in r['note']), **one)
    raise PartError('no check %s' % check)


def plants(names: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    out = {}
    for name in (names or list(PLANTS)):
        check = PLANTS[name][0]
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-evworld-plant-',
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
LABELS = ('EV_DoDoor', 'newDoor', 'EV_VerticalDoor', 'EV_DoPlat', 'lnDoor',
          'lnPlat', 'lnVDoor')


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """The part's bytes (evworld.o) against its budget; each routine's
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
    rep['build_kb'] = du_kb(OUT)
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
