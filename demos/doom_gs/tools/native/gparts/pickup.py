#!/usr/bin/env python3
"""Part pickup's checkpoint (milestone 10, wave 2; docs/GAME.md 2.4, 3.5,
3.7; docs/game-parts/pickup.md): its image, its captures, its routine-mode
runs on both fills and both profiles, its synthetic and random cases, its
planted bugs, and build/native/game/pickup/report.json.

Usage:  python3 tools/native/gparts/pickup.py --build
        python3 tools/native/gparts/pickup.py --capture [--jobs 2]
        python3 tools/native/gparts/pickup.py --check [--jobs 2]
                                              [--sample K] [--groups ...]
        python3 tools/native/gparts/pickup.py --plants [--jobs 2]

The image (build()): `make -f game.mk part P=pickup` from a scratch copy of
the build files (game.mk, math.inc, integrated.txt, the fragments of the
integrated waves' parts and of this part: another part of wave 2, being
built at the same time, cannot break this build), with the planted bugs
applied to copies of the part's sources; into build/native/game/pickup/
(a plant's into a temporary directory). The messages' symbol numbers
are ggame.inc's SYM_*, upstream's small tables lgame.inc's U_* (request
P1, wave 2 as integrated).

The captures (capture()): tools/native/gamecap.py's, into the part's own
build/native/game/pickup/cases/: every P_TouchSpecialThing call of demo3,
demo1, demo2 and the tour, every C_Responder call of the tour and of
newgame.

The groups of cases (each case runs from both fills under both profiles:
4 runs; a group's cases come from the reference's own code, ref816 --call
on a captured state with pokes, never from a model):

  captured   every captured P_TouchSpecialThing call
  cheats     every captured C_Responder call that completes a cheat (the
             cheat's number found by upstream's own matcher run on the
             entry's memory: seqs, seqStart, CHT_P and the event's key),
             natively C_Responder with the number; the calls that complete
             none are checked to change no canonical state
  touch      GAME.md 2.4's synthetic touches: each E1 item type (the pickTab
             sprites of the things of E1M1-E1M9 in DOOM1.WAD, any skill) at
             each skill, from three player states (as captured; "needy":
             health 50, no armour, no ammo, fist and pistol, no cards, no
             backpack, no powers; "stocked": every weapon, half the ammo,
             every card, a backpack, health 150, armour 150, the map and
             invisibility for ever), the item a thing of the base case's
             level of its type with its z set to the toucher's (the item
             moved onto the player), or, when that level has none, the
             captured special made one (type, sprite, frame, state, flags)
  synth-cheats  every cheat of m_cheat65.s's table (C_Responder with the
             event of its last letter and that sequence one letter short)
             on two captured states, and on the states where each toggle
             is already on (god, noclip, rockets, the frame rate), a
             backpack is already there, the map is held, a power is for
             ever
  givepower  P_GivePower of each power from the three player states
  random     random player states (health, armour, ammo, maxima, weapons,
             cards, powers, the ready weapon: each field from its edge
             values or at random) and a random item of pickTab at a random
             skill; the reach (the item's z against the toucher's: the
             edges of the height and of -8 units) and a dead toucher

Every run: gameroutine's routine mode (the reference's entry state through
the game manifest into a machine poisoned with $A5 or $5A, the inputs of
the entry's spec, the call, the state read back and compared with the
reference's return state by gcanon's routine mode, exclusions R1-R7 only,
every declared output), on a2vm under the cost profile, with the write
log: no CPU write outside the allowed places, the native-only globals
consistent, and the player's mobj's RTHING flag (the renderer's MF_SHADOW)
equal to its MF_SHADOW.
"""

import argparse
import hashlib
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

from bridge.port import PortReader, PortError  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL, render_check as RC, \
    rlayout as R  # noqa: E402
from ref816 import bounded  # noqa: E402
import mobjstate as MS  # noqa: E402  (wave 1's harness pieces)

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'pickup'
OUT = GL.GAME / PART
MYCASES = OUT / 'cases'
REPORT = OUT / 'report.json'
FILLS = (0xA5, 0x5A)
PROFILES = ('f121', 'fastpath')
NAME = 'ptest'
BUDGET = 2100                   # GAME.md 2.4: upstream 1,611 x 1.3
MODULES = ('pickup', 'cheat')

TOUCH = 'p_inter65.s:P_TouchSpecialThing'
GIVEPOWER = 'p_inter65.s:P_GivePower'
RESPONDER = 'm_cheat65.s:C_Responder'
CAPTURES = [('demo3', TOUCH), ('demo1', TOUCH), ('demo2', TOUCH),
            ('tour', TOUCH), ('tour', RESPONDER), ('newgame', RESPONDER)]
# m_cheat65.s's table, in its order (ticcap.CHEATS: the stream's numbers)
CHEATS = ('cheatChoppers', 'cheatGod', 'cheatKfa', 'cheatFa', 'cheatNoclip',
          'cheatBeholdV', 'cheatBeholdS', 'cheatBeholdI', 'cheatBeholdR',
          'cheatBeholdA', 'cheatBeholdL', 'cheatClev', 'cheatEnd',
          'cheatRocket', 'cheatRate')
GROUPS = ('captured', 'cheats', 'touch', 'synth-cheats', 'givepower',
          'random')
SKILLS = 5
RANDOM_CASES = 160


class PartError(Exception):
    pass


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------

def _fragments() -> List[str]:
    """The fragments a part image of wave 2 needs: the integrated waves'
    parts and this part's."""
    integrated = int((SRC / 'game' / 'integrated.txt').read_text().split()[0])
    out = []
    for p in GL.PARTS:
        if p['wave'] <= integrated or p['name'] == PART:
            f = 'game/%s/part.mk' % p['name']
            if (SRC / f).exists():
                out.append(f)
    return out


def build(game: Path = GL.GAME, bugs: Sequence[Tuple[str, str, str]] = ()
          ) -> Path:
    """The part's image (GAME/pickup/ptest.*) from a scratch copy of the
    build files and the bugs (file under src/native, old, new) applied to
    copies; every other source from the tree (game.mk's vpath). The copy
    is deleted."""
    tmp = Path(tempfile.mkdtemp(prefix='tmp-pickup-build-', dir=str(BUILD)))
    try:
        src = tmp / 'src'
        files = {'game.mk', 'math.inc', 'game/integrated.txt'}
        files |= set(_fragments()) | {name for name, _, _ in bugs}
        for f in files:
            (src / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(SRC / f), str(src / f))
        for name, old, new in bugs:
            text = (src / name).read_text()
            if text.count(old) != 1:
                raise PartError('%s: the edit no longer applies: %r' % (
                    name, old[:60]))
            (src / name).write_text(text.replace(old, new))
        objs = game / PART / 'game' / PART
        if objs.exists():               # (pk.inc is no prerequisite)
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
    """The part's bytes against its budget, by module and by routine (the
    routines of the part table that hold code: grun.routine_sizes), and
    the groups its code is in."""
    ms = MS.module_ranges(b)
    by = {m: sum(hi + 1 - lo for _, lo, hi in ms.get(m, ())) for m in MODULES}
    part = sum(by.values())
    rs, _ = G.routine_sizes(b)
    p = next(x for x in GL.PARTS if x['name'] == PART)
    mine = {k: v for k, v in rs.items() if k in p['routines'] + p['helpers']}
    return {'modules': by, 'part_bytes': part, 'budget': BUDGET,
            'over_budget_pct': round(100.0 * (part - BUDGET) / BUDGET, 1),
            'routines': mine,
            'segments': sorted({seg for m in MODULES
                                for seg, _, _ in ms.get(m, ())})}


# ---------------------------------------------------------------------------
# The captures
# ---------------------------------------------------------------------------

def use_cases(where: Path = MYCASES) -> None:
    MS.use_cases(where)


def survey_hits(run: str, key: str) -> List[int]:
    sv = GC.survey_of(run)
    if sv is None:
        raise PartError('no survey of %s (python3 tools/native/gamecap.py '
                        '--survey)' % run)
    return [i + 1 for i, tic in enumerate(sv['routines'][key]['tic'])
            if tic != -1]


def _capture_job(job) -> str:
    run, key, hits = job
    use_cases(MYCASES)
    sv = GC.survey_of(run)
    made = GC.capture(run, key, hits, sv['routines'][key]['tic'],
                      say=lambda *a: None)
    return '%s %s: %d made, %d asked' % (run, key, len(made), len(hits))


def capture(jobs: int = 2, say=print) -> None:
    """Every capture of CAPTURES the part's case directory lacks: a run's
    first batch alone (it writes the run's base), the rest jobs at a
    time."""
    use_cases(MYCASES)
    todo = []
    for run, key in CAPTURES:
        hits = survey_hits(run, key)
        d = GC.case_dir(run, key)
        missing = [h for h in hits if not (d / ('h%08d.case.z' % h)).exists()]
        for i in range(0, len(missing), GC.BATCH):
            todo.append((run, key, missing[i:i + GC.BATCH]))
    first = []
    for run in sorted({t[0] for t in todo}):
        if not GC.base_path(run).exists():
            j = next(t for t in todo if t[0] == run)
            first.append(j)
            todo.remove(j)
    for j in first:
        say(_capture_job(j))
    if todo:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for got in pool.map(_capture_job, todo):
                say(got)


def case_paths(run: str, key: str) -> List[Path]:
    use_cases(MYCASES)
    return sorted(GC.case_dir(run, key).glob('h*.case.z'))


def have_captures() -> bool:
    return all(case_paths(run, key) or not survey_hits(run, key)
               for run, key in CAPTURES)


# ---------------------------------------------------------------------------
# Upstream's facts (the link map, the release's tables in a case's memory)
# ---------------------------------------------------------------------------

_T: List[Any] = []


def table():
    if not _T:
        _T.append(GC.CL.Linkmap())
    return _T[0]


def addr(key: str) -> int:
    return table().address(key)


def uc(name: str) -> int:
    return MS.uconst(name)


def player_field(name: str, k: int = 0) -> int:
    """The address of upstream's _g_player field UO_PL_<name> (element
    k of an array of words)."""
    return addr('g_game65.s:_g_player') + uc('UO_PL_' + name) + 2 * k


def numkeys() -> int:
    from bridge import incfile
    if not hasattr(numkeys, 'v'):
        numkeys.v = incfile.as_dict(incfile.parse(
            BUILD / 'upstream' / 'src' / 'iigs' / 'keys.inc'))['NUMKEYS']
    return numkeys.v


def sequences(mem) -> List[bytes]:
    """m_cheat65.s's sequences, from the memory's seqs and seqStart."""
    base = addr('m_cheat65.s:seqs')
    starts = addr('m_cheat65.s:seqStart')
    out = []
    for i in range(len(CHEATS)):
        s = base + mem.u16(starts + 2 * i)
        raw = bytearray()
        while mem.u8(s + len(raw)) and len(raw) < 32:
            raw.append(mem.u8(s + len(raw)))
        out.append(bytes(raw))
    return out


def event_of(case: GC.Case) -> Tuple[int, int]:
    """C_Responder's event (_Dp[0-3]): its address and its key's byte
    (data1's low byte); key -1 for an event that is not a key down."""
    ev = int.from_bytes(case.entry.read(MS.dp_address(case, '_Dp'), 4),
                        'little') & 0xFFFFFF
    if case.entry.u16(ev) != 0:
        return ev, -1
    return ev, case.entry.u16(ev + 2) & 0xFF


def cheat_of(case: GC.Case) -> Optional[int]:
    """The cheat a C_Responder call completes: upstream's matcher run on
    the entry's memory (each sequence's next character at CHT_P; the
    first sequence that reaches its end with this key), or None."""
    _, key = event_of(case)
    if key < 0 or key < numkeys():
        return None
    seqs = sequences(case.entry)
    chtp = addr('m_cheat65.s:CHT_P')
    for i, s in enumerate(seqs):
        p = case.entry.u16(chtp + 2 * i)
        if p < len(s) and s[p] == key and p + 1 == len(s):
            return i
    return None


def fps_show(mem) -> int:
    return mem.u16(addr('d_main65.s:_g_fps_show'))


# ---------------------------------------------------------------------------
# The specs and one run
# ---------------------------------------------------------------------------

def spec_of(key: str) -> Dict[str, Any]:
    return GR.all_args()[key]


def allowed_main(b: RC.Build) -> List[Tuple[int, int]]:
    """The main bytes a CPU write of the part's runs may reach (besides
    the zero page and the stack): bl_get's buffer, the stop codes, the
    random indexes, validcount, the caches and the runtime's state, the
    game globals (the player) and the tic phase's (G_FPSSHOW: idrate),
    the scratch blocks of this part and of the
    parts it calls (mobjstate's P_RemoveMobj, flow's G_ExitLevel), W's
    API buffers and the planes, AUXW, ghook's event buffer."""
    lab = b.labels
    blocks = GL.scratch_blocks()
    out = [(LL.BL_BUF, LL.BL_BUF + 0x100), (GL.GS_STATUS, GL.GS_ARG + 2),
           (LL.PRND, LL.MRND + 1), (LL.G_VALID, LL.G_VALID + 2),
           (LL.MOC, LL.MOC + LL.MOC_LINES * LL.MOC_LINE),
           (LL.SCC, LL.SCC + LL.SCC_LINES * LL.SCC_LINE),
           (LL.RT_STATE, LL.RT_END), (LL.GBLOCK, GL.TIC_MAIN_END),
           (LL.GW, LL.GW_END), (LL.PL_TNL, 0xC000)]
    for part in (PART, 'mobjstate', 'flow'):
        at, n = blocks[part]
        out.append((at, at + n))
    lo, hi = b.segments['AUXW']
    out.append((lo, hi + 1))
    for name, n in (('hk_ev', 6), ('hk_y', 1)):
        if name in lab:
            out.append((lab[name], lab[name] + n))
    return out


def stray(writes, b: RC.Build, header: Dict[str, Any]) -> List[str]:
    """CPU writes outside the allowed places (mobjstate.stray's rules with
    this part's main places)."""
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
                continue            # a group's load
        elif w.storage == 'lc' and drv[0] <= w.pc <= drv[1] and (
                desc[0] <= w.offset <= desc[1] or w.offset >= 0xFFFE):
            continue
        elif w.storage == 'aux' and any(
                lo <= w.offset < hi for lo, hi in aux.get(w.bank, ())):
            continue
        out.append('pc $%04X wrote %s %d $%04X' % (w.pc, w.storage, w.bank,
                                                     w.offset))
    return out


def shadow_check(m, nat: Dict[str, Any], mf) -> List[str]:
    """The player's mobj's RTHING flags bit 0 (the renderer's MF_SHADOW,
    which no canonical field holds) against its MF_SHADOW."""
    pl = nat['objects'].get('player', {}).get(0)
    if not pl or pl.get('mo') is None:
        return []
    ref = pl['mo']
    o = nat['objects'][ref.kind][ref.id]
    slot = GR.handle_of(mf, ref)
    a = R.RTHINGS.base + R.RTHINGS.stride * slot + R.RTHING['FLAGS']
    got = m.aux[R.RTH][a] & 1
    want = 1 if o['flags'] & uc('UC_MF_SHADOW_HI') << 16 else 0
    if got != want:
        return ['the player\'s RTHING flag %d, its MF_SHADOW %d' % (got,
                                                                   want)]
    return []


def run_one(prep: 'MS.Prepared', b: RC.Build, fill: int,
            profile: Optional[str], regs_over: Optional[Dict[str, int]] = None,
            zp: Sequence[Tuple[int, bytes]] = ()) -> Dict[str, Any]:
    """The prepared case on image b at fill under profile: the
    comparison, the declared outputs, the stray writes, the native checks
    (mobjstate's, the shadow flag), the call's clock and cycles, the
    lowest S."""
    case, up, spec = prep.case, prep.up, prep.spec
    res: Dict[str, Any] = {'case': case.path.name if case.path else
                           case.header.get('note') or 'synthetic',
                           'routine': case.key, 'hit': case.header['hit'],
                           'fill': '%02x' % fill, 'profile': profile,
                           'ok': False}
    if prep.problems:
        res['error'] = 'bridge: ' + '; '.join(prep.problems[:3])
        return res
    mf, header, banks = prep.mf, prep.header, prep.banks
    img = G.Image(b, fill, store=True)
    img.recs += GR.base_records(up.gamemap)
    img.recs += prep.recs
    for a, d in list(prep.zp) + list(zp):
        img.main(a, d)
    regs = list(prep.regs)
    for k, v in (regs_over or {}).items():
        regs['axyp'.index(k)] = v
    name = spec['native']
    img.poke_word('dg_entry', b.labels[name])
    img.poke_label('dg_grp', bytes([MS.entry_group(b, name)]))
    work = Path(tempfile.mkdtemp(prefix='tmp-pickup-run-', dir=str(BUILD)))
    try:
        start = time.time()
        r = G.run(img, work, GL.MODES['ROUTINE'], None, regs=tuple(regs),
                  banks=banks, profile=profile, write_log=MS.LOG_RANGES)
        res['seconds'] = round(time.time() - start, 2)
        res['lowest_s'] = r.state.get('lowest_s')
        writes = MS.read_log(work / 'writes.log') \
            if (work / 'writes.log').exists() else []
        res['clock'], res['cpu_cycles'] = MS.call_clock(writes, b)
        st = stray([w for _, w in writes], b, header)
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
        nat = PortReader(mf).read(SC.port_memory(m))
    except PortError as error:
        res['diff'] = ['the port reader: %s' % error]
        return res
    diff = gcanon.compare(up.s_out, nat, 'routine')
    diff += MS.native_checks(m)
    diff += shadow_check(m, nat, mf)
    res['fc_loads'] = m.main[GL.RT['FC_LOADS']] | \
        m.main[GL.RT['FC_LOADS'] + 1] << 8
    lab = b.labels
    out_regs = {'a': G.card_byte(m, lab['dg_ra']),
                'x': G.card_byte(m, lab['dg_rx']),
                'y': G.card_byte(m, lab['dg_ry'])}
    for item in spec.get('out', []):
        nv = item['native']
        value = out_regs['a'] | out_regs['x'] << 8 if nv == 'ax' else \
            out_regs[nv]
        uv = int.from_bytes(up.source(item['upstream'], 'out'), 'little')
        mask = (1 << (8 * item.get('bytes', 2))) - 1
        if value & mask != uv & mask:
            diff.append('output %s: %X != %X' % (item['upstream'],
                                                 value & mask, uv & mask))
    res['diff'] = diff[:12]
    res['ok'] = not diff and not res['strays']
    return res


# ---------------------------------------------------------------------------
# The reference's own calls (synthetic cases)
# ---------------------------------------------------------------------------

def ref_case(base: GC.Case, key: str, pokes: Sequence[Tuple[int, bytes]],
             note: str, regs: Optional[Dict[str, int]] = None) -> GC.Case:
    """A synthetic case: upstream's routine key on ref816 (--call) on the
    base case's entry memory with pokes (and registers): the memory at its
    entry and at its return."""
    mem = base.entry.copy()
    mem.header = base.entry.header
    for a, d in pokes:
        mem.write(a, d)
    after, call = MS.ref_call(mem, key, (), regs)
    hdr = dict(base.header, routine=key, note=note, call=call)
    return GC.Case(hdr, mem, after, None)


def w16(v: int) -> bytes:
    return (v & 0xFFFF).to_bytes(2, 'little')


def w32(v: int) -> bytes:
    return (v & 0xFFFFFFFF).to_bytes(4, 'little')


def maxammo_defaults(mem) -> List[int]:
    a = addr('p_inter65.s:maxammo')
    return [mem.u16(a + 2 * k) for k in range(uc('UC_NUMAMMO'))]


def player_pokes(mem, variant: str) -> List[Tuple[int, bytes]]:
    """The pokes of a player state (the module's doc: captured, needy,
    stocked)."""
    if variant == 'captured':
        return []
    na, nw, nc, npw = (uc('UC_NUMAMMO'), uc('UC_NUMWEAPONS'),
                       uc('UC_NUMCARDS'), 6)
    mx = maxammo_defaults(mem)
    out: List[Tuple[int, bytes]] = []

    def put(name, v, k=0):
        out.append((player_field(name, k), w16(v)))
    if variant == 'needy':
        put('HEALTH', 50)
        put('ARMORPOINTS', 0)
        put('ARMORTYPE', 0)
        for k in range(na):
            put('AMMO', 0, k)
            put('MAXAMMO', mx[k], k)
        for k in range(nw):
            put('WEAPONOWNED', 1 if k in (uc('UC_WP_FIST'),
                                           uc('UC_WP_PISTOL')) else 0, k)
        put('READYWEAPON', uc('UC_WP_FIST'))
        put('PENDINGWEAPON', uc('UC_WP_NOCHANGE'))
        for k in range(nc):
            put('CARDS', 0, k)
        put('BACKPACK', 0)
        for k in range(npw):
            put('POWERS', 0, k)
    elif variant == 'stocked':
        put('HEALTH', 150)
        put('ARMORPOINTS', 150)
        put('ARMORTYPE', 1)
        for k in range(na):
            put('MAXAMMO', 2 * mx[k], k)
            put('AMMO', mx[k], k)
        for k in range(nw):
            put('WEAPONOWNED', 1, k)
        put('READYWEAPON', uc('UC_WP_PISTOL'))
        for k in range(nc):
            put('CARDS', 1, k)
        put('BACKPACK', 1)
        for k in range(npw):
            put('POWERS', 0, k)
        put('POWERS', 1, uc('UC_PW_ALLMAP'))
        put('POWERS', 0xFFFF, uc('UC_PW_INVISIBILITY'))
    else:
        raise PartError('no player state %s' % variant)
    return out


def player_mobj_pokes(mem, up: GR.Upstream, health: int
                      ) -> List[Tuple[int, bytes]]:
    """The player's mobj's health with the player's (upstream keeps them
    equal)."""
    pl = up.s_in['objects']['player'][0]
    ptr = up.r_in.ref_address(pl['mo'])
    return [(ptr + uc('UO_MO_HEALTH'), w16(health))]


# ---- the items ------------------------------------------------------------

PICK_SPRITES = ('ARM1', 'ARM2', 'BON1', 'BON2', 'SOUL', 'BKEY', 'YKEY',
                'RKEY', 'STIM', 'MEDI', 'PINS', 'SUIT', 'PMAP', 'PVIS',
                'CLIP', 'AMMO', 'ROCK', 'BROK', 'SHEL', 'SBOX', 'BPAK',
                'MGUN', 'CSAW', 'LAUN', 'SHOT')


def mobjinfo(mem, mtype: int, field: str, n: int = 2) -> int:
    a = addr('info65.s:mobjinfo') + 64 * mtype + uc('UO_MI_' + field)
    return int.from_bytes(mem.read(a, n), 'little')


def state_record(mem, n: int) -> Dict[str, int]:
    """info65.s's state n in mem (mobjstate.state_record with the link
    map read once)."""
    a = addr('info65.s:states') + 16 * n
    raw = mem.read(a, 16)
    return {'sprite': int.from_bytes(raw[0:2], 'little'),
            'frame': int.from_bytes(raw[2:4], 'little', signed=True),
            'address': a}


_TYPES: Dict[int, Dict[int, str]] = {}


def item_types(mem) -> Dict[int, str]:
    """item_types_of(mem), once a process (the release's tables are the
    same in every case)."""
    if not _TYPES:
        _TYPES[0] = item_types_of(mem)
    return _TYPES[0]


def item_types_of(mem) -> Dict[int, str]:
    """The mobj types of the E1 maps' things (DOOM1.WAD, any skill) whose
    spawn state's sprite is one of pickTab's: type -> sprite name."""
    from native import maplumps as ML
    from ref816 import lumps
    wad = ML.read_wad(lumps.WAD.read_bytes())
    sprites = {uc('UC_SPR_' + s): s for s in PICK_SPRITES}
    by_ednum = {}
    ntypes = 1 + max(v for k, v in GL.upstream_constants()
                     if k.startswith('UC_MT_'))
    for t in range(ntypes):
        ed = mobjinfo(mem, t, 'DOOMEDNUM')
        if ed and ed != 0xFFFF:
            by_ednum.setdefault(ed, t)
    out: Dict[int, str] = {}
    for gamemap in range(1, 10):
        lm = ML.map_lumps(wad, gamemap)
        raw = lm['THINGS']
        for k in range(0, len(raw) - 9, 10):
            ed = int.from_bytes(raw[k + 6:k + 8], 'little')
            if int.from_bytes(raw[k + 8:k + 10], 'little') & \
                    ML.MTF_NOTSINGLE:
                continue                # (not in a single player game)
            t = by_ednum.get(ed)
            if t is None:
                continue
            st = state_record(mem, mobjinfo(mem, t, 'SPAWNSTATE'))
            if st['sprite'] in sprites:
                out[t] = sprites[st['sprite']]
    return out


def morph_pokes(mem, up: GR.Upstream, ptr: int, mtype: int
                ) -> List[Tuple[int, bytes]]:
    """The mobj at ptr made a thing of type mtype: its type, its spawn
    state (sprite, frame, state) and its info's flags."""
    sn = mobjinfo(mem, mtype, 'SPAWNSTATE')
    st = state_record(mem, sn)
    return [(ptr + uc('UO_MO_TYPE'), bytes([mtype])),
            (ptr + uc('UO_MO_SPRITE'), w16(st['sprite'])),
            (ptr + uc('UO_MO_FRAME'), w16(st['frame'])),
            (ptr + uc('UO_MO_STATE'), w32(st['address'])),
            (ptr + uc('UO_MO_FLAGS'), w32(mobjinfo(mem, mtype, 'FLAGS',
                                                   4)))]


# ---------------------------------------------------------------------------
# The cases of each group
# ---------------------------------------------------------------------------

def _decodable(case: GC.Case) -> bool:
    try:
        up = GR.Upstream(case)
    except Exception:
        return False
    return not (up.r_in.problems or up.r_out.problems)


def touch_bases() -> List[Path]:
    """The captured P_TouchSpecialThing cases the synthetic touches start
    from: the first decodable case of each run's level whose reference
    takes the thing."""
    out = []
    for run in ('demo3', 'demo1', 'demo2'):
        for p in case_paths(run, TOUCH):
            c = GC.load_case(p)
            if _decodable(c) and taken(GR.Upstream(c)):
                out.append(p)
                break
    return out


def taken(up: GR.Upstream) -> bool:
    """The reference's call took the thing: P_RemoveMobj changed it (off
    its lists, its function the removal: P_RemoveThingDelayed), or it is
    gone."""
    ptr = int.from_bytes(up.source('dp:_Dp:4'), 'little') & 0xFFFFFF
    ref, _ = up.r_in.classify(ptr, ('mobj', 'zmobj'))
    if ref is None:
        return False
    after = up.s_out['objects'].get(ref.kind, {}).get(ref.id)
    return after is None or after != up.s_in['objects'][ref.kind][ref.id]


def touch_case(base: GC.Case, mtype: int, skill: int, variant: str,
               mems: Optional[Dict[int, str]] = None) -> GC.Case:
    """The synthetic touch: base's state, the player state variant, the
    skill, a thing of type mtype on the player (a thing of the level of
    that type with its z the toucher's, or the base's special made one)."""
    up = GR.Upstream(base)
    mem = base.entry
    pokes = player_pokes(mem, variant)
    if variant == 'needy':
        pokes += player_mobj_pokes(mem, up, 50)
    elif variant == 'stocked':
        pokes += player_mobj_pokes(mem, up, 150)
    pokes.append((addr('g_game65.s:_g_gameskill'), w16(skill)))
    tptr = int.from_bytes(up.source('dp:_Dp+4:4'), 'little') & 0xFFFFFF
    tz = mem.read(tptr + uc('UO_MO_Z'), 4)
    found = None
    for kind in ('mobj', 'zmobj'):
        for i, o in sorted(up.s_in['objects'].get(kind, {}).items()):
            if o.get('type') == mtype:
                from bridge.fields import R as Ref
                found = up.r_in.ref_address(Ref(kind, i, None))
                break
        if found:
            break
    how = 'moved'
    if found is None:
        found = int.from_bytes(up.source('dp:_Dp:4'), 'little') & 0xFFFFFF
        pokes += morph_pokes(mem, up, found, mtype)
        how = 'made'
    pokes.append((found + uc('UO_MO_Z'), tz))
    pokes.append((MS.dp_address(base, '_Dp'), w32(found)))
    note = 'touch type %d %s, skill %d, %s (%s)' % (
        mtype, (mems or {}).get(mtype, '?'), skill, variant, how)
    return ref_case(base, TOUCH, pokes, note)


def responder_bases() -> List[Path]:
    """Two captured C_Responder cases of the tour in a level (decodable):
    the first and the last that complete a cheat."""
    got = [p for p in case_paths('tour', RESPONDER)
           if cheat_of(GC.load_case(p)) is not None]
    out = [p for p in (got[:1] + got[-1:]) if _decodable(GC.load_case(p))]
    return sorted(set(out))


def cheat_case(base: GC.Case, number: int, pokes=(), note: str = ''
               ) -> GC.Case:
    """C_Responder on base's state with the event of the cheat's last
    letter, its sequence one letter short and every other at its start."""
    mem = base.entry
    seqs = sequences(mem)
    ev, _ = event_of(base)
    chtp = addr('m_cheat65.s:CHT_P')
    p = [(ev, w16(0)), (ev + 2, w16(seqs[number][-1]))]
    for i, s in enumerate(seqs):
        p.append((chtp + 2 * i, w16(len(s) - 1 if i == number else 0)))
    c = ref_case(base, RESPONDER, p + list(pokes),
                 note or 'cheat %s' % CHEATS[number])
    if cheat_of(c) != number:
        raise PartError('the event does not complete %s' % CHEATS[number])
    return c


SYNTH_CHEAT_STATES = (
    ('as captured', None),
    ('god on', ('CHEATS', 'UC_CF_GODMODE')),
    ('noclip on', ('CHEATS', 'UC_CF_NOCLIP')),
    ('rockets on', ('CHEATS', 'UC_CF_ENEMY_ROCKETS')),
    ('backpack', ('BACKPACK', None)),
    ('the map held', ('POWERS', 'UC_PW_ALLMAP')),
    ('powers for ever', ('POWERS*', None)),
    ('frame rate on', ('FPS', None)))


def state_pokes(mem, what) -> List[Tuple[int, bytes]]:
    if what is None:
        return []
    field, const = what
    if field == 'CHEATS':
        v = mem.u16(player_field('CHEATS')) | uc(const)
        return [(player_field('CHEATS'), w16(v))]
    if field == 'BACKPACK':
        mx = maxammo_defaults(mem)
        return [(player_field('BACKPACK'), w16(1))] + [
            (player_field('MAXAMMO', k), w16(2 * mx[k]))
            for k in range(len(mx))]
    if field == 'POWERS':
        return [(player_field('POWERS', uc(const)), w16(1))]
    if field == 'POWERS*':
        return [(player_field('POWERS', k), w16(0xFFFF)) for k in range(6)]
    if field == 'FPS':
        return [(addr('d_main65.s:_g_fps_show'), w16(1))]
    raise PartError(field)


def givepower_case(base: GC.Case, power: int, variant: str) -> GC.Case:
    up = GR.Upstream(base)
    mem = base.entry
    pokes = player_pokes(mem, variant)
    if variant != 'captured':
        pokes += player_mobj_pokes(mem, up, 50 if variant == 'needy'
                                   else 150)
    pl = addr('g_game65.s:_g_player')
    pokes.append((MS.dp_address(base, '_Dp'), w32(pl)))
    return ref_case(base, GIVEPOWER, pokes, 'P_GivePower %d, %s' % (
        power, variant), {'a': power})


EDGES16 = (0, 1, 2, 99, 100, 101, 199, 200, 201, 0x7FFF, 0x8000, 0xFFFF,
           0xFFFE, 0x7FFE)


def random_case(base: GC.Case, rng: random.Random, types: Dict[int, str]
                ) -> GC.Case:
    """A random player state, item, skill and reach (the module's doc)."""
    up = GR.Upstream(base)
    mem = base.entry
    pokes: List[Tuple[int, bytes]] = []

    def v16():
        return rng.choice(EDGES16) if rng.random() < 0.6 else \
            rng.randrange(0x10000)
    health = v16()
    pokes.append((player_field('HEALTH'), w16(health)))
    pokes += player_mobj_pokes(mem, up, health if rng.random() < 0.9
                               else v16())
    for f in ('ARMORPOINTS', 'ARMORTYPE', 'BACKPACK', 'READYWEAPON',
              'BONUSCOUNT', 'ITEMCOUNT'):
        v = v16() if f not in ('ARMORTYPE', 'READYWEAPON') else \
            rng.randrange(uc('UC_NUMWEAPONS') + 1) if f == 'READYWEAPON' \
            else rng.randrange(3)
        pokes.append((player_field(f), w16(v)))
    for k in range(uc('UC_NUMAMMO')):
        mx = rng.choice((maxammo_defaults(mem)[k], v16()))
        pokes.append((player_field('MAXAMMO', k), w16(mx)))
        pokes.append((player_field('AMMO', k), w16(rng.choice(
            (0, mx, mx - 1, v16())))))
    for k in range(uc('UC_NUMWEAPONS')):
        pokes.append((player_field('WEAPONOWNED', k), w16(rng.choice(
            (0, 1, 0, 1, v16())))))
    for k in range(uc('UC_NUMCARDS')):
        pokes.append((player_field('CARDS', k), w16(rng.choice((0, 1)))))
    for k in range(6):
        pokes.append((player_field('POWERS', k), w16(rng.choice(
            (0, 0, 1, 0xFFFF, v16())))))
    skill = rng.randrange(SKILLS)
    pokes.append((addr('g_game65.s:_g_gameskill'), w16(skill)))
    mtype = rng.choice(sorted(types))
    sptr = int.from_bytes(up.source('dp:_Dp:4'), 'little') & 0xFFFFFF
    tptr = int.from_bytes(up.source('dp:_Dp+4:4'), 'little') & 0xFFFFFF
    pokes += morph_pokes(mem, up, sptr, mtype)
    if rng.random() < 0.3:
        flags = mobjinfo(mem, mtype, 'FLAGS', 4) | \
            uc('UC_MF_DROPPED_HI') << 16
        pokes.append((sptr + uc('UO_MO_FLAGS'), w32(flags)))
    tz = int.from_bytes(mem.read(tptr + uc('UO_MO_Z'), 4), 'little',
                        signed=True)
    height = int.from_bytes(mem.read(tptr + uc('UO_MO_HEIGHT'), 4),
                            'little', signed=True)
    dz = rng.choice((0, 0, 0, height, height + 1, -8 << 16, (-8 << 16) - 1,
                     rng.randrange(-(16 << 16), height + (8 << 16))))
    pokes.append((sptr + uc('UO_MO_Z'), w32(tz + dz)))
    note = 'random type %d %s skill %d dz %d health %d' % (
        mtype, types[mtype], skill, dz, health)
    return ref_case(base, TOUCH, pokes, note)


# ---------------------------------------------------------------------------
# The paths (the coverage report)
# ---------------------------------------------------------------------------

def touch_path(up: GR.Upstream) -> str:
    try:
        s = up.s_in
        sp = up.ref(int.from_bytes(up.source('dp:_Dp:4'), 'little'))
        tp = up.ref(int.from_bytes(up.source('dp:_Dp+4:4'), 'little'))
        so, to = s['objects'][sp.kind][sp.id], s['objects'][tp.kind][tp.id]
        delta = so['z'] - to['z']
        if to['height'] < delta:
            return 'out of reach (above)'
        if delta < -(8 << 16):
            return 'out of reach (below)'
        if to['health'] <= 0:
            return 'dead toucher'
        spr = {uc('UC_SPR_' + n): n for n in PICK_SPRITES}.get(so['sprite'],
                                                                '?')
        return '%s %s' % (spr, 'taken' if taken(up) else 'not taken')
    except Exception as error:          # (a path is a report only)
        return 'unknown: %s' % type(error).__name__


# ---------------------------------------------------------------------------
# The jobs
# ---------------------------------------------------------------------------

_BUILDS: Dict[str, RC.Build] = {}


def _build(obj: str) -> RC.Build:
    if obj not in _BUILDS:
        _BUILDS[obj] = load(Path(obj))
    return _BUILDS[obj]


def _runs(case: GC.Case, key: str, b, fills, profiles, group: str,
          path: str, regs_over=None, zp=()) -> List[Dict[str, Any]]:
    spec = spec_of(key)
    prep = MS.Prepared(case, spec)
    if not prep.problems and key == TOUCH:
        path = (path + ': ' if path else '') + touch_path(prep.up)
    out = []
    for fill in fills:
        for prof in profiles:
            try:
                r = run_one(prep, b, fill, prof, regs_over, zp)
            except Exception as error:      # reported per run, never hidden
                r = {'ok': False, 'fill': '%02x' % fill, 'profile': prof,
                     'error': '%s: %s' % (type(error).__name__, error)}
            r.update(group=group, entry=key, path=path,
                     case=r.get('case') or case.header.get('note'))
            out.append(r)
    return out


def fps_zp(case: GC.Case) -> List[Tuple[int, bytes]]:
    """G_FPSSHOW, the persistent byte of _g_fps_show (request P4, wave 2
    as integrated: glayout.TIC_MAIN_FIELDS), from the reference's
    entry."""
    return [(GL.TGM['G_FPSSHOW'], bytes([1 if fps_show(case.entry) else 0]))]


def _job(job) -> List[Dict[str, Any]]:
    group, what, obj, fills, profiles = job
    use_cases(MYCASES)
    b = _build(obj)
    try:
        if group == 'captured':
            return _runs(GC.load_case(Path(what)), TOUCH, b, fills, profiles,
                         group, '')
        if group == 'cheats':
            case = GC.load_case(Path(what))
            n = cheat_of(case)
            if n is None:
                # no cheat: nothing native to run (matching keys is
                # milestone 11's); the reference must change no canonical
                # state. A call outside a level (the menus, the
                # intermission) has no level state to decode: counted
                # apart, and only when it completes no cheat
                up = GR.Upstream(case)
                if up.r_in.problems or up.r_out.problems:
                    return [{'ok': True, 'group': 'no cheat',
                             'entry': RESPONDER, 'case': Path(what).name,
                             'path': 'no cheat completed (no level state)',
                             'native': False}]
                diff = gcanon.compare(up.s_in, up.s_out, 'routine')
                return [{'ok': not diff, 'group': 'no cheat',
                         'entry': RESPONDER, 'case': Path(what).name,
                         'path': 'no cheat completed', 'native': False,
                         'diff': diff[:4]}]
            return _runs(case, RESPONDER, b, fills, profiles, group,
                         CHEATS[n], {'a': n}, fps_zp(case))
        if group == 'touch':
            base, mtype, skill, variant = what
            types = item_types(GC.load_case(Path(base)).entry)
            c = touch_case(GC.load_case(Path(base)), mtype, skill, variant,
                           types)
            return _runs(c, TOUCH, b, fills, profiles, group,
                         '%s %s' % (types.get(mtype), variant))
        if group == 'synth-cheats':
            base, number, state = what
            bc = GC.load_case(Path(base))
            pokes = state_pokes(bc.entry, dict(SYNTH_CHEAT_STATES)[state])
            c = cheat_case(bc, number, pokes, 'cheat %s, %s' % (
                CHEATS[number], state))
            return _runs(c, RESPONDER, b, fills, profiles, group,
                         '%s, %s' % (CHEATS[number], state), {'a': number},
                         fps_zp(c))
        if group == 'givepower':
            base, power, variant = what
            c = givepower_case(GC.load_case(Path(base)), power, variant)
            return _runs(c, GIVEPOWER, b, fills, profiles, group,
                         'power %d, %s' % (power, variant),
                         {'a': power})
        if group == 'random':
            base, seed = what
            bc = GC.load_case(Path(base))
            types = item_types(bc.entry)
            c = random_case(bc, random.Random(seed), types)
            return _runs(c, TOUCH, b, fills, profiles, group, '')
        raise PartError('no group %s' % group)
    except Exception as error:              # reported, never hidden
        return [{'ok': False, 'group': group, 'entry': '?',
                 'case': str(what)[:120],
                 'error': '%s: %s' % (type(error).__name__, error)}]


def plan(obj: Path = OUT, fills=FILLS, profiles=PROFILES, sample: int = 1,
         groups: Sequence[str] = GROUPS) -> Tuple[List[Tuple], Dict]:
    """The checkpoint's jobs and its case counts: every sample-th case of
    each group."""
    o = str(obj)
    jobs: List[Tuple] = []
    elig: Dict[str, Any] = {}
    use_cases(MYCASES)
    if 'captured' in groups:
        for run, key in CAPTURES:
            if key != TOUCH:
                continue
            paths = case_paths(run, key)
            elig.setdefault(key, {})[run] = {
                'survey_calls': len(survey_hits(run, key)),
                'captured': len(paths), 'eligible': len(paths),
                'waiting': {}}
            jobs += [('captured', str(p), o, fills, profiles)
                     for p in paths[::sample]]
    if 'cheats' in groups:
        for run, key in CAPTURES:
            if key != RESPONDER:
                continue
            paths = case_paths(run, key)
            elig.setdefault(key, {})[run] = {
                'survey_calls': len(survey_hits(run, key)),
                'captured': len(paths), 'eligible': len(paths),
                'waiting': {}}
            jobs += [('cheats', str(p), o, fills, profiles) for p in paths]
    bases = touch_bases() if {'touch', 'givepower', 'random'} & set(groups) \
        else []
    if 'touch' in groups and bases:
        types = item_types(GC.load_case(bases[0]).entry)
        k = 0
        for mtype in sorted(types):
            for skill in range(SKILLS):
                for variant in ('captured', 'needy', 'stocked'):
                    base = bases[k % len(bases)]
                    k += 1
                    if k % sample == 0 or sample == 1:
                        jobs.append(('touch', (str(base), mtype, skill,
                                               variant), o, fills, profiles))
    if 'synth-cheats' in groups:
        rb = responder_bases()
        k = 0
        for base in rb:
            for number in range(len(CHEATS)):
                for state, _ in SYNTH_CHEAT_STATES:
                    k += 1
                    if sample == 1 or k % sample == 0:
                        jobs.append(('synth-cheats', (str(base), number,
                                                      state), o, fills,
                                     profiles))
    if 'givepower' in groups and bases:
        for power in range(6):
            for variant in ('captured', 'needy', 'stocked'):
                jobs.append(('givepower', (str(bases[power % len(bases)]),
                                           power, variant), o, fills,
                             profiles))
    if 'random' in groups and bases:
        for seed in range(0, RANDOM_CASES, sample):
            jobs.append(('random', (str(bases[seed % len(bases)]), seed), o,
                         fills, profiles))
    return jobs, elig


def job_key(j: Tuple) -> str:
    group, what, obj, fills, profiles = j
    w = Path(what).name if isinstance(what, str) else \
        [Path(what[0]).name] + list(what[1:])
    return json.dumps([group, w, list(fills), list(profiles)])


def run_jobs(jobs: Sequence[Tuple], workers: int = 2, say=None,
             journal: Optional[Path] = None) -> List[Dict[str, Any]]:
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
            out += done[k]
        else:
            todo.append(j)

    def keep(j, got):
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
            if say and n % 50 == 0:
                say('%d of %d jobs' % (n, len(todo)))
    return out


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Per entry: cases and runs, failures, the groups and paths, the
    call's clock and CPU cycles (median, worst) on each profile, the lowest
    S, the stray writes, the group loads."""
    out: Dict[str, Any] = {}
    for r in results:
        e = out.setdefault(r.get('entry') or '?', {
            'cases': set(), 'runs': 0, 'failures': 0, 'groups': {},
            'paths': {}, 'clock': {}, 'cpu_cycles': {}, 'lowest_s': None,
            'strays': 0, 'first_failures': [], 'fc_loads': [],
            'reference_only': 0})
        e['cases'].add((r.get('group'), r.get('case')))
        if r.get('native') is False:
            e['reference_only'] += 1
        else:
            e['runs'] += 1
        g = r.get('group') or '?'
        e['groups'][g] = e['groups'].get(g, 0) + 1
        p = r.get('path') or ''
        e['paths'][p] = e['paths'].get(p, 0) + 1
        if not r.get('ok'):
            e['failures'] += 1
            if len(e['first_failures']) < 5:
                e['first_failures'].append({k: r.get(k) for k in (
                    'case', 'group', 'fill', 'profile', 'ended', 'stop',
                    'error', 'diff', 'stray_first') if r.get(k)})
        if r.get('fc_loads') is not None:
            e['fc_loads'].append(r['fc_loads'])
        prof = r.get('profile')
        if prof:
            e['clock'].setdefault(prof, []).append(r.get('clock'))
            e['cpu_cycles'].setdefault(prof, []).append(r.get('cpu_cycles'))
        s = r.get('lowest_s')
        if isinstance(s, dict):
            s = s.get('s')
        if s is not None:
            e['lowest_s'] = s if e['lowest_s'] is None else \
                min(e['lowest_s'], s)
        e['strays'] += r.get('strays') or 0
    for e in out.values():
        e['cases'] = len(e['cases'])
        e['clock'] = {k: MS._stats(v) for k, v in e['clock'].items()}
        e['cpu_cycles'] = {k: MS._stats(v) for k, v in
                           e['cpu_cycles'].items()}
        e['fc_loads'] = MS._stats(e['fc_loads'])
    return out


def image_digest(obj: Path = OUT) -> str:
    h = hashlib.sha256()
    for p in sorted(obj.glob(NAME + '.*')):
        if p.suffix not in ('.lbl', '.map'):
            h.update(p.name.encode() + p.read_bytes())
    return h.hexdigest()[:16]


def check(jobs: int = 2, sample: int = 1, groups: Sequence[str] = GROUPS,
          rebuild: bool = True, say=print) -> Dict[str, Any]:
    """The checkpoint on the part's image: report.json's checkpoint
    half (a journal of this image resumes an interrupted full run)."""
    if rebuild:
        build()
    b = load()
    js, elig = plan(OUT, FILLS, PROFILES, sample, groups)
    say('%d jobs' % len(js))
    start = time.time()
    journal = None
    if sample == 1 and tuple(groups) == GROUPS:
        journal = OUT / ('journal-%s.jsonl' % image_digest())
        for old in OUT.glob('journal-*.jsonl'):
            if old != journal:
                old.unlink()
    res = run_jobs(js, jobs, say, journal)
    return {'entries': summarize(res), 'eligibility': elig,
            'runs': sum(1 for r in res if r.get('native') is not False),
            'failures': sum(1 for r in res if not r.get('ok')),
            'strays': sum(r.get('strays') or 0 for r in res),
            'seconds': round(time.time() - start),
            'fills': ['%02x' % f for f in FILLS],
            'profiles': list(PROFILES), 'sizes': sizes(b), 'sample': sample,
            'groups': list(groups)}


# ---------------------------------------------------------------------------
# The planted bugs (GAME.md 2.4's row): each in a scratch copy of the
# part's sources, built in a temporary directory, run on its check
# ---------------------------------------------------------------------------

PK = 'game/%s/' % PART
PLANTS: Dict[str, Dict[str, Any]] = {
    # ammo doubled at the wrong skill: at hard (3) instead of nightmare (4)
    'ammo-doubled-at-hard': {'check': 'touch-ammo', 'bugs': [
        (PK + 'pickup.s', """        cmp #UC_SK_NIGHTMARE
        bne @add""", """        cmp #UC_SK_HARD         ; (planted: hard, not nightmare)
        bne @add""")]},
    # a weapon already owned giving no ammo
    'owned-weapon-no-ammo': {'check': 'touch-weapon', 'bugs': [
        (PK + 'pickup.s', """        stx PK_DROP
        asl a                   ; weaponinfo[weapon].ammo: damage's table""",
         """        stx PK_DROP
        asl a                   ; (planted: an owned weapon: no ammo)
        tax
        lda PLR + PL_WEAPONOWNED_0,x
        ora PLR + PL_WEAPONOWNED_0 + 1,x
        bne @none
        lda PK_WPN
        asl a                   ; weaponinfo[weapon].ammo: damage's table""")]},
    # the backpack not doubling the maxima
    'backpack-no-double': {'check': 'touch-backpack', 'bugs': [
        (PK + 'pickup.s', """:       asl PLR + PL_MAXAMMO_0,x
        rol PLR + PL_MAXAMMO_0 + 1,x
        dex
        dex
        bpl :-
        lda #1
        sta PLR + PL_BACKPACK""", """:       dex                     ; (planted: the maxima not doubled)
        dex
        bpl :-
        lda #1
        sta PLR + PL_BACKPACK""")]},
    # another item's message: the stimpack's is the medikit's
    'stim-medikit-message': {'check': 'touch-stim', 'bugs': [
        (PK + 'pickup.s', """<(SYM_p_inter_msgRedCard), <(SYM_p_inter_msgStim)""",
         """<(SYM_p_inter_msgRedCard), <(SYM_p_inter_msgMedikit)""")]},
}
PLANT_SPRITES = {'touch-ammo': ('CLIP', 'AMMO', 'SHEL', 'SBOX', 'ROCK',
                                'BROK'),
                 'touch-weapon': ('MGUN', 'SHOT', 'LAUN'),
                 'touch-backpack': ('BPAK',), 'touch-stim': ('STIM',)}


def plant_jobs(check_name: str, obj: Path) -> List[Tuple]:
    """The plant's check: the synthetic touches of its items (every skill,
    every player state), one fill, no cost model."""
    js, _ = plan(obj, (0xA5,), (None,), 1, ('touch',))
    want = PLANT_SPRITES[check_name]
    out = []
    types = None
    for j in js:
        base, mtype, skill, variant = j[1]
        if types is None:
            types = item_types(GC.load_case(Path(base)).entry)
        if types.get(mtype) in want:
            out.append(j)
    return out


def run_plant(name: str, say=None, workers: int = 2) -> Dict[str, Any]:
    """The plant's image in a temporary directory (deleted), its check's
    jobs: caught when one of them fails."""
    p = PLANTS[name]
    tmp = Path(tempfile.mkdtemp(prefix='tmp-pickup-plant-', dir=str(BUILD)))
    try:
        obj = build(tmp / 'game', p['bugs'])
        js = plant_jobs(p['check'], obj)
        res = run_jobs(js, workers)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
        _BUILDS.clear()
    failed = [r for r in res if not r.get('ok')]
    out = {'check': p['check'], 'runs': len(res), 'failed': len(failed),
           'caught': bool(failed),
           'first': {k: failed[0].get(k) for k in ('case', 'diff', 'error',
                                                    'ended', 'stop')
                     if failed[0].get(k)} if failed else None}
    if say:
        say('%-24s %s' % (name, ('caught (%s): %d of %d runs fail: %s' % (
            p['check'], len(failed), len(res), str(out['first'])[:300]))
            if failed else 'NOT CAUGHT (%d runs)' % len(res)))
    return out


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def write_report(rep: Dict[str, Any], plants: Optional[Dict[str, Any]] =
                 None) -> Path:
    out = dict(rep)
    out['format'] = 'game-part-report 1'
    out['part'] = PART
    out['wave'] = 2
    if plants is not None:
        out['plants'] = plants
    elif REPORT.exists():
        old = json.loads(REPORT.read_text())
        if 'plants' in old:
            out['plants'] = old['plants']
    out['build_kb'] = MS.du_kb(OUT)
    out['notes'] = [
        'clock: the call\'s time from call_entry to its return under the '
        'profile (a2vm --cost-timed: fabric clocks); cpu_cycles: the '
        'W65C02S\'s cycles of the same span; each with every slot empty '
        'at the call (an upper bound)',
        'lowest_s: the lowest S of the run (the driver starts at $EF)',
        'C_Responder: the captured calls that complete no cheat are not run '
        'natively (matching keys is milestone 11\'s); the reference\'s '
        'canonical state is checked unchanged by them (reference_only)',
        'power and m_cheat_giveAmmo (rts routines upstream, no captured '
        'call) run inside the cheat cases (idbehold*, idchoppers, idfa, '
        'idkfa); the pickTab helpers inside the touches']
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=1, default=str) + '\n')
    return REPORT


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--groups', default=','.join(GROUPS))
    args = parser.parse_args(argv)
    status = 0
    if args.build:
        print(json.dumps(sizes(load(build())), indent=1))
    if args.capture:
        capture(args.jobs)
    if args.check:
        groups = tuple(g for g in args.groups.split(',') if g)
        rep = check(args.jobs, args.sample, groups)
        write_report(rep)
        for k, e in sorted(rep['entries'].items()):
            print('%-34s %4d cases %5d runs %3d failed  clock f121 %s '
                  'fastpath %s  S %s  groups %s' % (
                      k, e['cases'], e['runs'], e['failures'],
                      e['clock'].get('f121'), e['clock'].get('fastpath'),
                      e['lowest_s'], e['groups']))
            for f in e['first_failures'][:3]:
                print('    %s' % json.dumps(f, default=str)[:500])
        print('runs %d, failures %d, stray writes %d, %d s' % (
            rep['runs'], rep['failures'], rep['strays'], rep['seconds']))
        status |= 1 if rep['failures'] or rep['strays'] else 0
    if args.plants:
        pl = {n: run_plant(n, print, args.jobs) for n in PLANTS}
        rep = json.loads(REPORT.read_text()) if REPORT.exists() else {}
        rep.pop('format', None)
        write_report(rep, pl)
        status |= 0 if all(p['caught'] for p in pl.values()) else 1
    return status


if __name__ == '__main__':
    sys.exit(main())
