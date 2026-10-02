#!/usr/bin/env python3
"""Part mobjstate's checkpoint (milestone 10, wave 1; docs/GAME.md 2.4, 3.5;
docs/game-parts/mobjstate.md): its image, its captures, its routine-mode
runs on both fills and both profiles, its synthetic cases and its planted
bugs, and build/native/game/mobjstate/report.json.

Usage:  python3 tools/native/gparts/mobjstate.py --build
        python3 tools/native/gparts/mobjstate.py --capture [--jobs 2]
        python3 tools/native/gparts/mobjstate.py --check [--jobs 2]
                                                 [--sample K] [--entries ...]
        python3 tools/native/gparts/mobjstate.py --synthetic
        python3 tools/native/gparts/mobjstate.py --plants
        python3 tools/native/gparts/mobjstate.py --report

The image (build()): `make -f game.mk part P=mobjstate MS_TEST=1` from a
scratch copy of the build files whose gpos.s imports P_DelSecnode (the
stand-in of request R1: the skeleton's gpos.s cannot assemble once the
part is built), into build/native/game/mobjstate/; MS_TEST=1 adds the
part's test routines (game/mobjstate/mstest.s: the synthetic sequences).

The captures (capture()): tools/native/gamecap.py's, into the part's own
build/native/game/mobjstate/cases/ (its base RAM a run and its cases): every
call of demo3 of the checkpoint's entries and of P_RemoveThinker, 300 of
P_DelSecnode's 605, and explode in demo1 and demo2 too.

A run (run_one()): gameroutine.py's routine mode (the case's entry state
through the game manifest into a machine poisoned with $A5 or $5A, the
inputs of the entry's spec, the call, the state read back and compared
with the reference's return state, gcanon's routine mode, exclusions
R1-R6 only, every declared output), on a2vm under a cost profile (f121,
fastpath), with the write log: no CPU write outside the allowed places
(stray()), and the native-only globals checked (G_THLAST the thinker
list's last; G_ZMFREE's slots free). Each case runs from both fills under
both profiles (4 runs).

Eligible cases (GAME.md 3.5 step 6): every dispatch target the call
reached (the survey) is built (the core's, the part's). A P_SetMobjState
call that reaches an unbuilt action is run too, as a "stop check": the
native stops at the action's DCALL (GS_UNBUILTD and its ACTTAB number);
the mobj's state, tics, sprite and frame there must be the reference's at
the action's entry (ref816 --call of the case with the action's first byte
an RTL).
"""

import argparse
import json
import os
import re
import shutil
import statistics
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

from bridge.port import PortReader, PortWriter, PortError  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL, render_check as RC, \
    rlayout as R  # noqa: E402
from ref816 import bounded, calls as CL, title  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'mobjstate'
OUT = GL.GAME / PART
MYCASES = OUT / 'cases'
SHARED_CASES = GL.GAME / 'cases'
REPORT = OUT / 'report.json'
FILLS = (0xA5, 0x5A)
PROFILES = ('f121', 'fastpath')
NAME = 'ptest'
BUDGET = 1900                   # GAME.md 2.4: upstream 1,397 x 1.3
MODULES = ('mslist', 'msthink', 'msstate')
TEST_MODULES = ('mstest',)

# (request R1, gpos.s's import of P_DelSecnode, is applied: FCALL makes a
# built target .global; wave 1 as integrated)


class PartError(Exception):
    pass


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------

def build(game: Path = GL.GAME, bugs: Sequence[Tuple[str, str, str]] = (),
          test: bool = True) -> Path:
    """The part's image (game/mobjstate/ptest.*) from a scratch copy of
    the build files (game.mk, math.inc, integrated.txt, the part's
    fragment) and the bugs (file under
    src/native, old, new) applied to copies; every other source from the
    tree (game.mk's vpath). The scratch copy is deleted."""
    tmp = Path(tempfile.mkdtemp(prefix='tmp-mobjstate-build-',
                                dir=str(BUILD)))
    try:
        src = tmp / 'src'
        files = set(G.PLANT_COPY) | {'game/%s/part.mk' % PART}
        files |= {name for name, _, _ in bugs}
        for f in files:
            (src / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(SRC / f), str(src / f))
        for name, old, new in list(bugs):
            text = (src / name).read_text()
            if text.count(old) != 1:
                raise PartError('%s: the edit no longer applies: %r' % (
                    name, old[:60]))
            (src / name).write_text(text.replace(old, new))
        objs = game / PART / 'game' / PART
        if objs.exists():               # (ms.inc is no prerequisite)
            for p in objs.glob('*.o'):
                p.unlink()
        cmd = ['make', '-s', '-C', str(src), '-f', 'game.mk', 'part',
               'P=%s' % PART, 'ROOT=%s' % ROOT, 'GAME=%s' % game]
        if test:
            cmd.append('MS_TEST=1')
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


def module_ranges(b: RC.Build) -> Dict[str, List[Tuple[str, int, int]]]:
    """module -> [(segment, first, last)] from the image's map."""
    text = (b.obj / (b.name + '.map')).read_text()
    text = text.split('Modules list:', 1)[-1].split('Segment list:', 1)[0]
    out: Dict[str, List[Tuple[str, int, int]]] = {}
    module = None
    for line in text.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module and f and f[0] in b.segments:
            offs = int(next(x for x in f if x.startswith('Offs='))[5:], 16)
            size = int(next(x for x in f if x.startswith('Size='))[5:], 16)
            if size:
                lo = b.segments[f[0]][0] + offs
                out.setdefault(module, []).append((f[0], lo, lo + size - 1))
    return out


def sizes(b: RC.Build) -> Dict[str, Any]:
    ms = module_ranges(b)
    by = {m: sum(hi + 1 - lo for _, lo, hi in ms.get(m, ()))
          for m in MODULES + TEST_MODULES}
    part = sum(by[m] for m in MODULES)
    return {'modules': by, 'part_bytes': part, 'budget': BUDGET,
            'over_budget_pct': round(100.0 * (part - BUDGET) / BUDGET, 1),
            'groups': sorted({seg for m in MODULES for seg, _, _ in
                              ms.get(m, ())})}


# ---------------------------------------------------------------------------
# The cases
# ---------------------------------------------------------------------------

def use_cases(where: Path) -> None:
    """gamecap's case directory (its module global) for this process."""
    if GC.CASES != where:
        GC.CASES = where
        GC._BASES.clear()


# (run, file:label, how many: None every call, N evenly spread). The two
# delayed removers are entered by the walk's JML (callFn), which ref816's
# --capture does not count: their cases are the reference's own calls
# (--call) on the states after P_RemoveMobj's and P_RemoveThinker's
# captured calls (removers()).
CAPTURES = [
    ('demo3', 'p_tick65.s:P_SetMobjState', None),
    ('demo3', 'p_spawn65.s:P_RemoveMobj', None),
    ('demo3', 'p_map65.s:P_UnsetThingPosition', None),
    ('demo3', 'p_map65.s:P_DelSeclist', None),
    ('demo3', 'p_think65.s:P_RemoveThinker', None),
    ('demo3', 'p_mobj65.s:explode', None),
    ('demo3', 'p_map65.s:P_DelSecnode', 300),
    ('demo1', 'p_mobj65.s:explode', None),
    ('demo2', 'p_mobj65.s:explode', None),
]


def survey_hits(run: str, key: str) -> List[int]:
    """The survey's hits of key that ref816's --capture counts, in order:
    capture hit k is the k-th. The call log also counts an entry by a
    JML, which --capture does not (a JSR, JSL or JSR (a,x) only): such a
    hit never returns (its tic is -1 in the survey) and is left out
    (P_SetMobjState's hit 240 of demo3)."""
    sv = GC.survey_of(run)
    if sv is None:
        raise PartError('no survey of %s (python3 tools/native/gamecap.py '
                        '--survey)' % run)
    return [i + 1 for i, tic in enumerate(sv['routines'][key]['tic'])
            if tic != -1]


def hits_of(run: str, key: str, n: Optional[int]) -> List[int]:
    calls = len(survey_hits(run, key))
    if n is None or calls <= n:
        return list(range(1, calls + 1))
    return sorted({1 + (i * calls) // n for i in range(n)})


def _capture_job(job) -> str:
    run, key, hits = job
    use_cases(MYCASES)
    sv = GC.survey_of(run)
    tics = sv['routines'][key]['tic']
    made = GC.capture(run, key, hits, tics, say=lambda *a: None)
    return '%s %s: %d made, %d asked' % (run, key, len(made), len(hits))


def capture(jobs: int = 2, say=print) -> None:
    """Every capture of CAPTURES the part's case directory lacks: the
    first batch of each run alone (it writes the run's base), the rest
    jobs at a time."""
    use_cases(MYCASES)
    todo = []
    for run, key, n in CAPTURES:
        hits = hits_of(run, key, n)
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
    if not todo:
        return
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_capture_job, todo):
            say(got)


def case_paths(run: str, key: str, where: Path = MYCASES) -> List[Path]:
    use_cases(where)
    return sorted(GC.case_dir(run, key).glob('h*.case.z'))


def built_keys() -> set:
    p = next(x for x in GL.PARTS if x['name'] == PART)
    return set(p['routines'] + p['helpers'])


def reached_of(run: str, key: str) -> Dict[int, List[str]]:
    """The dispatch targets each call reached, by its capture hit."""
    sv = GC.survey_of(run)
    targets = sv['targets']
    r = sv['routines'][key]
    out = {}
    for k, h in enumerate(survey_hits(run, key), 1):
        v = r['reached'].get(str(h))
        if v:
            out[k] = [targets[i] for i in v]
    return out


def waiting_for(targets: Sequence[str]) -> List[str]:
    """The reached targets that are not built in the part's image (its
    image links the earlier waves, the integrated waves and the part:
    glayout.built_set, as game.mk's part target)."""
    wave = next(p['wave'] for p in GL.PARTS if p['name'] == PART)
    built = set(GL.built_set(max(wave - 1, GL.integrated_waves()), [PART]))
    return [t for t in targets if GL.owner_of(t) != 'core' and
            GL.owner_of(t) not in built]


_ACTKEYS: Dict[int, str] = {}


def action_key(address: int) -> str:
    """upstream's action at address: its file:label (ACTTAB's)."""
    if not _ACTKEYS:
        from native import gcallgraph as CG
        keys = GL.dispatch_entries(CG.load(write=False))['ACTTAB']
        nums = act_numbers()
        for a, n in nums.items():
            _ACTKEYS[a] = keys[n - 1]
    return _ACTKEYS.get(address, '?:$%06X' % address)


def reaches(key: str, case: GC.Case) -> List[str]:
    """The dispatch targets the call reaches, from the reference's memory
    at its entry: P_SetMobjState's state's action (no state of info65.s
    has 0 tics, so only the first state's; A_CyberAttack instead with the
    rocket cheat in its range), explode's through its type's death state;
    the part's other entries dispatch nothing. (The survey's reached
    targets miss the actions that are survey entries of another pass:
    A_Chase and A_Look for demo3's P_SetMobjState; request R6.)"""
    t = GC.CL.Linkmap()
    if key == 'p_mobj65.s:explode':
        ap = int.from_bytes(case.entry.read(dp_address(case, 'AP'), 4),
                            'little') & 0xFFFFFF
        mtype = case.entry.read(ap + uconst('UO_MO_TYPE'), 1)[0]
        info = t.address('info65.s:mobjinfo') + 64 * mtype
        state = int.from_bytes(case.entry.read(
            info + uconst('UO_MI_DEATHSTATE'), 2), 'little')
    elif key == 'p_tick65.s:P_SetMobjState':
        state = case.regs_in['a'] & 0xFFFF
    else:
        return []
    if not state:
        return []
    act = state_record(case.entry, state)['action']
    if not act:
        return []
    cheats = int.from_bytes(case.entry.read(
        t.address('g_game65.s:_g_player') + uconst('UO_PL_CHEATS'), 2),
        'little')
    if cheats & uconst('UC_CF_ENEMY_ROCKETS'):
        return [action_key(act), 'p_enemy65.s:A_CyberAttack']
    return [action_key(act)]


# ---------------------------------------------------------------------------
# The entries' specs (args.json, and the part's own for the kinds
# gameroutine's harness cannot convert: request R5)
# ---------------------------------------------------------------------------

LOCAL_SPECS = {
    'p_map65.s:P_DelSecnode': {
        'native': 'P_DelSecnode',
        'in': [{'from': 'dp:_Dp:4', 'to': 'ax', 'as': 'secnode'}],
        'out': [{'native': 'ax', 'upstream': 'xc', 'as': 'secnode'}]},
    'p_think65.s:P_RemoveThinkerDelayed': {
        'native': 'P_RemoveThinkerDelayed',
        'in': [{'from': 'dp:_Dp:4', 'to': 'zp:GA_0', 'as': 'thinker'}],
        'out': []},
    'p_think65.s:P_RemoveThinker': {
        'native': 'P_RemoveThinker',
        'in': [{'from': 'dp:_Dp:4', 'to': 'ax', 'as': 'thinker'}],
        'out': []},
}
AS_KINDS = {'mobj': ('mobj', 'zmobj'), 'secnode': ('secnode',),
            'sector': ('sector',),
            'thinker': ('mobj', 'zmobj', 'plat', 'door', 'floor',
                        'lightflash', 'strobe', 'glow', 'scroll',
                        'removed')}


def spec_of(key: str) -> Dict[str, Any]:
    if key in LOCAL_SPECS:
        return LOCAL_SPECS[key]
    return GR.all_args()[key]


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

# the write log: main but the zero page and the stack (always allowed),
# FC_A (the call's start: call_entry's write), the cards, every aux bank
LOG_RANGES = 'main:0069,main:0200-BFFF,lc,lc1,aux0-127'


def allowed_main(b: RC.Build) -> List[Tuple[int, int]]:
    """The main bytes any CPU write of a routine-mode run may reach
    (besides the zero page and the stack): bl_get's buffer, the stop
    codes, P_Random's and M_Random's indexes, validcount, the caches and
    the runtime's state, the game globals and the tic phase's own after
    them (glayout.TIC_MAIN_FIELDS: G_WSET, G_FPSSHOW), the part's scratch
    block, W's
    API buffers and the planes, AUXW, ghook's event buffer, the test
    routines' buffer, part pspr's flood stack."""
    lab = b.labels
    out = [(LL.BL_BUF, LL.BL_BUF + 0x100), (GL.GS_STATUS, GL.GS_ARG + 2),
           (LL.PRND, LL.MRND + 1), (LL.G_VALID, LL.G_VALID + 2),
           (LL.MOC, LL.MOC + LL.MOC_LINES * LL.MOC_LINE),
           (LL.SCC, LL.SCC + LL.SCC_LINES * LL.SCC_LINE),
           (LL.RT_STATE, LL.RT_END), (LL.GBLOCK, GL.TIC_MAIN_END),
           (lab['SB_MOBJSTATE'] if 'SB_MOBJSTATE' in lab else
            GL.scratch_blocks()[PART][0],
            GL.scratch_blocks()[PART][0] + 32),
           (LL.GW, LL.GW_END), (LL.PL_TNL, 0xC000)]
    lo, hi = b.segments['AUXW']
    out.append((lo, hi + 1))
    for name, n in (('hk_ev', 6), ('hk_y', 1), ('ms_t_res', 8),
                    ('ms_t_args', 16)):
        if name in lab:
            out.append((lab[name], lab[name] + n))
    # the scratch blocks of the other parts built in the image: a run may
    # reach any built routine (a dispatched action, a callback), which
    # writes its own part's block (wave 3 as integrated: look's loadTarget
    # under P_SetMobjState's A_FaceTarget); an unbuilt part's block stays
    # a stray
    names = GL.native_names()
    blocks = GL.scratch_blocks()
    for q in GL.PARTS:
        if q['name'] == PART or q['name'] not in blocks:
            continue
        if any(names.get(k) in lab for k in q['routines'] + q['helpers']):
            lo = blocks[q['name']][0]
            n = blocks[q['name']][1] if len(blocks[q['name']]) > 1 else 32
            out.append((lo, lo + n))
    # part pspr's flood work stack (ps_stack, 512 levels of 2 B), in its
    # group's slot: any caller of P_MovePsprites may reach a shot's noise
    # alert (wave 5 as integrated: docs/game-parts/player.md R5)
    if 'ps_stack' in lab:
        out.append((lab['ps_stack'], lab['ps_stack'] + 512 * 2))
    # the two places P_UpdateSpecials (part secfind) writes every tic, which
    # any caller of P_Ticker reaches: TEXTRANS (texturetranslation,
    # basepic .. basepic + 2) and the frame block's NUKAGE
    # (P_UpdateAnimatedFlat); both compared as canonical state (wave 6 as
    # integrated: docs/game-parts/tic.md R2)
    out.append((R.TEXTRANS, R.TEXTRANS + 256))
    out.append((R.FRAME['NUKAGE'], R.FRAME['NUKAGE'] + 1))
    return out


def allowed_aux(header: Dict[str, Any]) -> Dict[int, List[Tuple[int, int]]]:
    """The aux bytes the run may write (the far layer's write-backs and the
    part's stand-ins: whole records of the kinds the game state is made
    of), by bank: the mobjs' four groups, the planes and the hints, the
    sectors' two records, the lines, the blocklinks of the map, the
    specials, the sector nodes, GTEST's sound and hit logs."""
    def arr(a) -> Tuple[int, int]:
        return (a.base, a.base + a.stride * a.capacity)
    out: Dict[int, List[Tuple[int, int]]] = {}
    for bank in (R.RTH, LL.MOBJA, LL.MOBJB, LL.MOBJC):
        out[bank] = [arr(R.RTHINGS)]
    out[LL.MOBJP] = [(LL.PL_HINTL, LL.PL_HINTH + LL.HINT_SLOTS),
                     (LL.PL_TNL, LL.PL_TICS + LL.PLANE_SLOTS)]
    out[R.LVMAP] = [arr(R.SECTORS)]
    out[LL.LVG0] = [arr(LL.LINES)]
    # the sides (LVMAP): P_UseSpecialLine's P_ChangeSwitchTexture writes a
    # switch's side back with sd_put (wave 5 as integrated:
    # docs/game-parts/player.md R5)
    out[R.LVMAP].append(arr(R.SIDES))
    blinks = header['lvg1']['BLINKS']
    out[LL.LVG1] = [arr(LL.SECGS),
                    (blinks, blinks + 2 * header['counts']['blocks'])]
    out[LL.ZONE0] = [arr(LL.SPECS)]
    out[LL.ZONE1] = [arr(LL.SNODES)]
    out[LL.GTEST] = [(GL.GTB['GT_SOUNDS'], GL.GTB['GT_SOUNDS'] + 0x0C00),
                     (GL.GTB['GT_HITS'], GL.GTB['GT_HITS'] + 0x0400)]
    return out


def mt_far_operands(b: RC.Build) -> Set[int]:
    """The two operand bytes math.s's mt_far patches in its own code (the
    card's bank 1): its count and its stride."""
    lab = b.labels
    return {lab[n] + 1 for n in ('mt_far_count', 'mt_far_stride')
            if n in lab}


def stray(writes, b: RC.Build, header: Dict[str, Any]) -> List[str]:
    """CPU writes outside the allowed places: main outside allowed_main
    (and the zero page and the stack, not logged), the card outside the
    driver's descriptor and the IRQ vector (by the driver), an aux bank
    outside allowed_aux; the phase loader (far_pload) copies W's images
    and the planes into W, the far layer a group's code into its slot;
    math.s's mt_far patches its own two operands in the card's bank 1
    (the tables bank's reads of the game's math: wave 2 as integrated,
    docs/game-parts/damage.md R6)."""
    allowed = allowed_main(b)
    desc = b.segments['DESC']
    drv = b.segments['DRIVER']
    loader = b.segments['RLOAD']
    far = b.segments['RFAR']
    aux = allowed_aux(header)
    mfar = b.segments.get('MATHFAR')
    patched = mt_far_operands(b)
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
            continue                # (the test routine's own data is in
                                    #   the driver's area since wave 1's
                                    #   integration)
        elif w.storage == 'lc' and desc[0] <= w.offset <= desc[1]:
            continue                # the driver's descriptor, whoever
                                    #   writes it: a load run's driver reads
                                    #   the re-key record into it with
                                    #   far_get, the far layer's code (wave
                                    #   6 as integrated: tic.md R2)
        elif w.storage == 'lc1' and mfar and \
                mfar[0] <= w.pc <= mfar[1] and w.offset in patched:
            continue
        elif w.storage == 'aux' and any(
                lo <= w.offset < hi for lo, hi in aux.get(w.bank, ())):
            continue
        out.append('pc $%04X wrote %s %d $%04X' % (w.pc, w.storage, w.bank,
                                                     w.offset))
    return out


def call_clock(writes, b: RC.Build) -> Tuple[Optional[int], Optional[int]]:
    """(clock, CPU cycles) of the call: from call_entry's first write
    (FC_A) to the driver's write of dg_ra after it."""
    lab = b.labels
    start = end = None
    for cyc, w in writes:
        if start is None and w.pc == lab['call_entry']:
            start = cyc
        elif start is not None and w.offset == lab['dg_ra'] and \
                w.storage == 'lc':
            end = cyc
            break
    if start is None or end is None:
        return None, None
    return end[0] - start[0], end[1] - start[1]


def read_log(path: Path):
    out = []
    with open(str(path)) as handle:
        for line in handle:
            if line.startswith('#'):
                continue
            f = line.split()
            io = f[5] == 'io'
            out.append(((int(f[1]), int(f[2])), RC.Write(
                int(f[3], 16), int(f[4], 16), f[5], 0 if io else int(f[6]),
                int(f[4], 16) if io else int(f[7], 16))))
    return out


def native_checks(m) -> List[str]:
    """The native-only globals after the call: G_THLAST the last of the
    thinker list from G_THFIRST (the planes and the specials' records);
    every slot on G_ZMFREE's list a zone slot of kind FN_FREE, no slot
    twice."""
    out = []

    def u16(address: int) -> int:
        return m.main[address] | m.main[address + 1] << 8

    def plane(base: int, slot: int) -> int:
        return m.aux[LL.MOBJP][base + slot]
    G_ = LL.G
    h = u16(G_['G_THFIRST'])
    last = 0xFFFF
    seen = set()
    while h != 0xFFFF:
        if h in seen or len(seen) > 4096:
            out.append('the thinker list loops at %04X' % h)
            break
        seen.add(h)
        last = h
        if h < LL.SPEC_HANDLE:
            h = plane(LL.PL_TNL, h) | plane(LL.PL_TNH, h) << 8
        else:
            rec = LL.SPECS.base + LL.SPEC_SIZE * (h - LL.SPEC_HANDLE)
            bank = m.aux[LL.ZONE0]
            h = bank[rec + LL.SP['THNEXT']] | bank[rec + LL.SP['THNEXT'] +
                                                  1] << 8
    if u16(G_['G_THLAST']) != last:
        out.append('G_THLAST %04X, the list\'s last %04X' % (
            u16(G_['G_THLAST']), last))
    pool = u16(G_['G_POOLN'])
    zmn = u16(G_['G_ZMN'])
    h = u16(G_['G_ZMFREE'])
    seen = set()
    while h != 0xFFFF:
        if h in seen or not pool <= h < pool + zmn:
            out.append('G_ZMFREE\'s list holds %04X' % h)
            break
        seen.add(h)
        if plane(LL.PL_KIND, h) != LL.FN['FREE']:
            out.append('free zone slot %04X has kind %d' % (
                h, plane(LL.PL_KIND, h)))
        h = plane(LL.PL_TNL, h) | plane(LL.PL_TNH, h) << 8
    return out


def _convert(up: GR.Upstream, mf, data: bytes, kind: str, when: str = 'in'
             ) -> bytes:
    ptr = int.from_bytes(data, 'little') & 0xFFFFFF
    r = up.r_in if when == 'in' else up.r_out
    if ptr == 0:
        return b'\xff\xff'
    ref, why = r.classify(ptr, AS_KINDS[kind])
    if ref is None:
        raise GR.HarnessError('$%06X is no %s (%s)' % (ptr, kind, why))
    if ref.kind == 'removed':
        # (the port writer puts the specials waiting for their removal
        # after its home kind's objects, in the order of their ids)
        from bridge.fields import R as Ref
        state = up.s_in if when == 'in' else up.s_out
        home = mf.removed['home']
        base = len(state['objects'].get(home, {}))
        ref = Ref(home, base + sorted(state['objects']['removed']).index(
            ref.id), None)
    return GR.handle_of(mf, ref).to_bytes(2, 'little')


LINK_PROBLEM = re.compile(r'^(mobj|zmobj) (\d+): its (snext|sprev|bnext|'
                          r'bprev) link is on no list$')
ZONE_PROBLEM = re.compile(r'^(\d+) bytes of zone at \$([0-9A-Fa-f]+) are '
                          r'neither a field nor an exclusion$')
STALE_LINKS = ('snext', 'sprev', 'bnext', 'bprev')


def stale_link_problems(reader) -> Tuple[List[str], List[str]]:
    """(accepted, the others) of a reader's problems. Accepted: a mobj
    taken off its sector's and block's lists (P_UnsetThingPosition: in
    P_RemoveMobj before P_DelSeclist, in P_TryMove before the new place)
    keeps its own snext, sprev, bnext, bprev, as upstream's unlist leaves
    them; the bridge finds those 16 bytes on no list and claimed by
    nothing (its coverage check). Every such problem must name the links
    of a mobj that a link problem names, and nothing else: every
    canonical field is still decoded and compared."""
    linked = set()
    rest = []
    for p in reader.problems:
        m_ = LINK_PROBLEM.match(p)
        if m_:
            linked.add((m_.group(1), int(m_.group(2))))
        else:
            rest.append(p)
    accepted = [p for p in reader.problems if LINK_PROBLEM.match(p)]
    others = []
    for p in rest:
        m_ = ZONE_PROBLEM.match(p)
        ok = False
        if m_ and linked:
            a, n = int(m_.group(2), 16), int(m_.group(1))
            ok = True
            for k in range(n):
                ref, _ = reader.classify(a + k, ('mobj', 'zmobj'))
                if ref is None:
                    # (inside a field: the field's start)
                    for back in range(1, 4):
                        ref, _ = reader.classify(a + k - back,
                                                 ('mobj', 'zmobj'))
                        if ref is not None:
                            break
                if ref is None or (ref.kind, ref.id) not in linked or \
                        ref.field not in STALE_LINKS:
                    ok = False
                    break
        if ok:
            accepted.append(p)
        else:
            others.append(p)
    return accepted, others


class Prepared:
    """A case's reference side and the native inputs, made once for its
    fills and profiles: the reference's states (the bridge's reader), the
    game manifest of its map, the state written through it (the port
    writer) and the native-only globals derived from it, the registers
    and zero-page inputs of the entry's spec."""

    def __init__(self, case: GC.Case, spec: Dict[str, Any]):
        self.case = case
        self.spec = spec
        self.up = up = GR.Upstream(case)
        self.problems = []
        self.accepted = []
        for r in (up.r_in, up.r_out):
            acc, others = stale_link_problems(r)
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
            if item.get('as'):
                data = _convert(up, self.mf, data, item['as'])
            to = item['to']
            if to in ('a', 'x', 'y'):
                regs['axy'.index(to)] = data[0]
            elif to == 'ax':
                regs[0], regs[1] = data[0], data[1]
            elif to.startswith('zp:'):
                n = item.get('bytes', len(data))
                self.zp.append((GR.zp_address(to[3:]),
                                data[:n].ljust(n, b'\0')))
            elif to.startswith('main:'):
                n = item.get('bytes', len(data))
                self.zp.append((LL.G[to[5:]], data[:n].ljust(n, b'\0')))
            else:
                raise GR.HarnessError('an input destination %r' % to)
        self.regs = regs


def run_one(case, spec: Dict[str, Any], b: RC.Build, fill: int,
            profile: Optional[str], extra: Sequence = (),
            zp: Sequence[Tuple[int, bytes]] = (),
            regs_over: Optional[Dict[str, int]] = None,
            entry: Optional[str] = None, keep_crash: bool = False,
            prep: Optional[Prepared] = None, keep_done: bool = False
            ) -> Dict[str, Any]:
    """The case (or its Prepared) on image b at fill under profile (None:
    no cost model): the comparison, the declared outputs, the stray
    writes, the native checks, the call's clock and cycles, the lowest S.
    extra: image records after the state (synthetic data); zp: main
    bytes after the inputs; regs_over: native registers; entry: another
    native routine than the spec's; keep_crash: the stop's snapshot in
    _crash; keep_done: the end's in _done."""
    if prep is None:
        prep = Prepared(case, spec)
    case, up = prep.case, prep.up
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
    mf, header, banks, skip = prep.mf, prep.header, prep.banks, prep.skip
    img = G.Image(b, fill, store=True)
    img.recs += GR.base_records(up.gamemap)
    img.recs += prep.recs
    img.recs += list(extra)
    for a, d in list(prep.zp) + list(zp):
        img.main(a, d)
    regs = list(prep.regs)
    for k, v in (regs_over or {}).items():
        regs['axyp'.index(k)] = v
    name = entry or spec['native']
    img.poke_word('dg_entry', b.labels[name])
    img.poke_label('dg_grp', bytes([entry_group(b, name)]))
    work = Path(tempfile.mkdtemp(prefix='tmp-mobjstate-run-',
                                 dir=str(BUILD)))
    try:
        start = time.time()
        r = G.run(img, work, GL.MODES['ROUTINE'], None,
                  regs=tuple(regs), banks=banks, profile=profile,
                  write_log=LOG_RANGES)
        res['seconds'] = round(time.time() - start, 2)
        res['run_cycles'] = r.state.get('cycles')
        res['lowest_s'] = r.state.get('lowest_s')
        writes = read_log(work / 'writes.log') \
            if (work / 'writes.log').exists() else []
        res['clock'], res['cpu_cycles'] = call_clock(writes, b)
        st = stray([w for _, w in writes], b, header)
        res['strays'] = len(st)
        if st:
            res['stray_first'] = st[:4]
        ended = r.ended()
        res['ended'] = ended
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                cm = G.load_snapshot(p)
                res['stop'] = G.stop_codes(cm)
                if keep_crash:
                    res['_crash'] = cm
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
    diff += native_checks(m)
    res['fc_loads'] = m.main[GL.RT['FC_LOADS']] | \
        m.main[GL.RT['FC_LOADS'] + 1] << 8
    lab = b.labels
    out_regs = {'a': G.card_byte(m, lab['dg_ra']),
                'x': G.card_byte(m, lab['dg_rx']),
                'y': G.card_byte(m, lab['dg_ry'])}
    for item in spec.get('out', []):
        nv = item['native']
        value = out_regs['a'] | out_regs['x'] << 8 if nv == 'ax' else \
            out_regs[nv] if nv in out_regs else None
        if value is None:
            raise GR.HarnessError('a native output %r' % nv)
        raw = up.source(item['upstream'], 'out')
        if item.get('as') == 'secnode':
            diff += _node_output(item, value, raw, m, up, mf)
        elif item.get('as') == 'thinker':
            uv = int.from_bytes(raw, 'little') & 0xFFFFFF
            want = 0xFFFF
            if uv:
                ref, why = up.r_out.classify(uv, AS_KINDS['thinker'])
                want = GR.handle_of(mf, ref) if ref else None
            if value != want:
                diff.append('output %s: %04X, upstream\'s %s' % (
                    item['upstream'], value, want))
        elif item.get('as') == 'player':
            uv = int.from_bytes(raw, 'little') & 0xFFFFFF
            player = GC.CL.Linkmap().address('g_game65.s:_g_player')
            if (value == LL.G['G_PLAYER'], value == 0) != (uv == player,
                                                         uv == 0):
                diff.append('output %s: %04X, upstream\'s $%06X' % (
                    item['upstream'], value, uv))
        elif item.get('as'):
            kinds = AS_KINDS[item['as']]
            uv = int.from_bytes(raw, 'little') & 0xFFFFFF
            mine = None if value == 0xFFFF else \
                GR.ref_of_handle(mf, kinds[:1], value)
            theirs = None if uv == 0 else up.r_out.classify(uv, kinds)[0]
            a = nat['objects'].get(mine.kind, {}).get(mine.id) \
                if mine else None
            b_ = up.s_out['objects'].get(theirs.kind, {}).get(theirs.id) \
                if theirs else None
            if (a is None) != (b_ is None) or gcanon.strip(
                    {'globals': {}, 'objects': {'k': {0: a or {}}}},
                    skip) != gcanon.strip(
                    {'globals': {}, 'objects': {'k': {0: b_ or {}}}}, skip):
                diff.append('output %s: %s is not upstream\'s %s' % (
                    item['upstream'], mine, theirs))
        else:
            mask = (1 << (8 * item.get('bytes', 2))) - 1
            uv = int.from_bytes(raw, 'little')
            if value & mask != uv & mask:
                diff.append('output %s: %X != %X' % (item['upstream'],
                                                     value & mask,
                                                     uv & mask))
    res['diff'] = diff[:12]
    res['ok'] = not diff and not res['strays']
    if keep_done:
        res['_done'] = m
    return res


_GROUPS: Dict[str, Dict[str, int]] = {}


def entry_group(b: RC.Build, name: str) -> int:
    """The group of a native routine in the image (its gen/gplace.inc's
    GP_name_G; 0, the core, for the test routines). grun.run takes the
    first group whose slot range holds the routine's address, which is
    another group's when two groups of one slot both start there (request
    R3): run_one pokes dg_entry and dg_grp itself."""
    key = str(b.obj)
    if key not in _GROUPS:
        d = {}
        for line in (b.obj / 'gen' / 'gplace.inc').read_text().splitlines():
            m_ = re.match(r'GP_(\w+)_G = (\d+)$', line)
            if m_:
                d[m_.group(1)] = int(m_.group(2))
        _GROUPS[key] = d
    return _GROUPS[key].get(name, 0)


def _node_output(item, value: int, raw: bytes, m, up, mf) -> List[str]:
    """A sector node returned (P_DelSecnode's next): none on both sides,
    or the same node: its sector and its thing (a node of a thing's
    thread is the only one of its sector there)."""
    uv = int.from_bytes(raw, 'little') & 0xFFFFFF
    if (value == 0xFFFF) != (uv == 0):
        return ['output %s: %04X against $%06X' % (item['upstream'], value,
                                                   uv)]
    if value == 0xFFFF:
        return []
    ref, why = up.r_out.classify(uv, ('secnode',))
    if ref is None:
        return ['output %s: $%06X is no node (%s)' % (item['upstream'], uv,
                                                      why)]
    o = up.s_out['objects']['secnode'][ref.id]
    rec = LL.SNODES.base + LL.SN_SIZE * value
    bank = m.aux[LL.ZONE1]
    sector = bank[rec + LL.SN['SECTOR']]
    thing = bank[rec + LL.SN['THING']] | bank[rec + LL.SN['THING'] + 1] << 8
    want_t = GR.handle_of(mf, o['m_thing']) if o.get('m_thing') else 0xFFFF
    want_s = o['m_sector'].id if o.get('m_sector') else None
    if (sector, thing) != (want_s, want_t):
        return ['output %s: node %04X (sector %s, thing %04X), upstream\'s '
                '(sector %s, thing %04X)' % (item['upstream'], value, sector,
                                             thing, want_s, want_t)]
    return []


# ---------------------------------------------------------------------------
# The reference's own calls (synthetic cases: ref816 --call)
# ---------------------------------------------------------------------------

def dp_address(case: GC.Case, sym: str, off: int = 0) -> int:
    t = GC.CL.Linkmap()
    return (case.regs_in['d'] + t.address(sym) - t.direct_page + off) & \
        0xFFFF


def ref_call(entry, key: str, pokes: Sequence[Tuple[int, bytes]] = (),
             regs: Optional[Dict[str, int]] = None) -> Tuple[Any, Dict]:
    """upstream's routine key run alone on ref816 (--call) on the memory
    entry (a bridge Memory with its image header) with pokes and --reg
    registers: (the memory at its return, the call's state)."""
    mem = entry.copy()
    mem.header = entry.header
    for a, d in pokes:
        mem.write(a, d)
    work = Path(tempfile.mkdtemp(prefix='tmp-mobjstate-call-',
                                 dir=str(BUILD)))
    try:
        (work / 'entry.img').write_bytes(mem.image_bytes())
        address = GC.CL.Linkmap().address(key)
        cmd = [str(title.MACHINE), str(work / 'entry.img')]
        for k, v in (regs or {}).items():
            cmd += ['--reg', '%s=%X' % (k, v)]
        cmd += ['--call', '%06X' % address, '--call-writes',
                str(work / 'writes.img'), '--state', str(work / 'state.json'),
                '--cycles', '200000000']
        r = bounded.run(cmd, timeout=120, max_bytes=GC.MAX_FILE,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode:
            raise PartError('ref816 --call %s failed: %s' % (
                key, r.stdout[-600:]))
        state = json.loads((work / 'state.json').read_text())
        if not state['call']['returned']:
            raise PartError('%s did not return' % key)
        writes = GC.image_records(work / 'writes.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    after = mem.copy()
    after.header = mem.header
    for a, d in writes:
        after.write(a, d)
    return after, state['call']


def synthetic_case(base: GC.Case, key: str, entry_mem, after_mem,
                   call: Dict[str, Any], note: str) -> GC.Case:
    header = dict(base.header, routine=key, note=note, call=call)
    return GC.Case(header, entry_mem, after_mem, None)


def mobj_pointer(up: GR.Upstream, ref) -> int:
    return up.r_in.ref_address(ref)


# ---------------------------------------------------------------------------
# The stop check: a call that reaches an unbuilt action
# ---------------------------------------------------------------------------

_ACT: Dict[int, int] = {}


def act_numbers() -> Dict[int, int]:
    """upstream's action address -> its ACTTAB number."""
    if not _ACT:
        from bridge.linkmap import Symbols
        from native import gcallgraph as CG
        sym = Symbols()
        keys = GL.dispatch_entries(CG.load(write=False))['ACTTAB']
        for i, k in enumerate(keys, 1):
            if not k.startswith('?'):
                _ACT[sym.address(k)] = i
    return _ACT


def routine_number(key: str) -> int:
    keys = [k for p in GL.PARTS for k in p['routines'] + p['helpers']]
    return (keys + GL.CORE).index(key) + 1


def _line_of(m, slot: int) -> Optional[int]:
    """The mobj cache line of slot in a snapshot (MOC's tags), its main
    address."""
    for i in range(LL.MOC_LINES):
        if m.main[GL.RT['MOC_TL'] + i] | m.main[GL.RT['MOC_TH'] + i] << 8 \
                == slot:
            return LL.MOC + LL.MOC_LINE * i
    return None


def mobj_at_stop(m, slot: int) -> Optional[Dict[str, int]]:
    """The mobj's state, tics, sprite and frame in the stop's snapshot
    (its cache line, W's tics plane: nothing was flushed)."""
    line = _line_of(m, slot)
    if line is None:
        return None
    mm = m.main
    a = line + LL.MO_SIZE
    tics = mm[LL.PL_TICS + slot]
    return {'state': mm[a + LL.MA['STATE']] | mm[a + LL.MA['STATE'] + 1] << 8,
            'tics': tics - 256 if tics >= 128 else tics,
            'sprite': mm[line + R.RTHING['SPR']],
            'frame': int.from_bytes(bytes(mm[line + R.RTHING['FRAME']:
                                             line + R.RTHING['FRAME'] + 2]),
                                    'little', signed=True)}


def mobj_ref_fields(state: Dict[str, Any], ref) -> Dict[str, int]:
    o = state['objects'][ref.kind][ref.id]
    st = o.get('state')
    return {'state': st.id if st is not None else 0xFFFF,
            'tics': o['tics'], 'sprite': o['sprite'], 'frame': o['frame']}


STATES = 'info65.s:states'


def state_record(mem, n: int) -> Dict[str, int]:
    t = GC.CL.Linkmap()
    a = t.address(STATES) + 16 * n
    raw = mem.read(a, 16)
    return {'sprite': int.from_bytes(raw[0:2], 'little'),
            'frame': int.from_bytes(raw[2:4], 'little', signed=True),
            'tics': int.from_bytes(raw[4:6], 'little', signed=True),
            'action': int.from_bytes(raw[6:10], 'little') & 0xFFFFFF,
            'next': int.from_bytes(raw[10:12], 'little'), 'address': a}


def stop_check(case: GC.Case, b: RC.Build, fills=FILLS, profiles=PROFILES,
               cyber: bool = False, pokes=(), extra=()) -> List[Dict[str, Any]]:
    """A P_SetMobjState call whose state's action is not built (or, with
    the rocket cheat, A_CyberAttack): the native stops at the action's
    DCALL (FCALL A_CyberAttack) with the mobj's state, tics, sprite and
    frame those of the reference at the action's entry: ref816 --call of
    the case with the action's first byte an RTL."""
    spec = spec_of('p_tick65.s:P_SetMobjState')
    entry = case.entry.copy()
    entry.header = case.entry.header
    for a, d in pokes:
        entry.write(a, d)
    state = case.regs_in['a'] & 0xFFFF
    st = state_record(entry, state)
    action = st['action']
    if not action and not cyber:
        return [{'case': case.path.name if case.path else 'synthetic',
                 'ok': False, 'kind': 'stop',
                 'error': 'state %d has no action' % state}]
    if cyber:
        action = GC.CL.Linkmap().address('p_enemy65.s:A_CyberAttack')
    after, call = ref_call(entry, case.key, [(action, b'\x6b')],
                           {'a': state})
    rcase = synthetic_case(case, case.key, entry, after, call,
                           'the action an RTL (stop check)')
    prep = Prepared(rcase, spec)
    out = []
    if prep.problems:
        return [{'case': case.path.name if case.path else 'synthetic',
                 'ok': False, 'error': 'bridge: %s' % prep.problems[:2]}]
    mo = prep.up.ref(int.from_bytes(prep.up.source('dp:_Dp:4'), 'little'))
    want = mobj_ref_fields(prep.up.s_out, mo)
    slot = GR.handle_of(prep.mf, mo)
    if cyber:
        code = (GL.GS['UNBUILT'], routine_number('p_enemy65.s:A_CyberAttack'))
    else:
        code = (GL.GS['UNBUILTD'], act_numbers()[action] | 1 << 8)
    for fill in fills:
        for prof in profiles:
            r = run_one(rcase, spec, b, fill, prof, keep_crash=True,
                        prep=prep, extra=extra)
            cm = r.pop('_crash', None)
            diff = []
            if r.get('ended') == 'halt' or not r.get('stop'):
                diff.append('no stop: %s' % r.get('ended'))
            else:
                if tuple(r['stop'][:2]) != code:
                    diff.append('stop %s, not %s' % (r['stop'][:2], code))
                got = mobj_at_stop(cm, slot)
                if got != want:
                    diff.append('at the action: %s, upstream %s' % (got, want))
            if r.get('strays'):
                diff.append('%d stray writes' % r['strays'])
            r.update(ok=not diff, diff=diff, kind='stop', want=want,
                     action='$%06X' % action)
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Synthetic cases
# ---------------------------------------------------------------------------

def uconst(name: str) -> int:
    if not hasattr(uconst, 'd'):
        uconst.d = dict(GL.upstream_constants())
    return uconst.d[name]


def _ptr4(p: int) -> bytes:
    return (p & 0xFFFFFF).to_bytes(4, 'little')


def removers(case: GC.Case, delayed_key: str) -> Optional[GC.Case]:
    """The reference's own call of a delayed remover on the state after a
    captured P_RemoveMobj (P_RemoveThinker): its thinker's turn of the
    walk."""
    entry = case.after.copy()
    entry.header = case.entry.header
    ptr = int.from_bytes(case.entry.read(dp_address(case, '_Dp'), 4),
                         'little') & 0xFFFFFF
    pokes = [(dp_address(case, '_Dp'), _ptr4(ptr))]
    for a, d in pokes:
        entry.write(a, d)
    after, call = ref_call(entry, delayed_key)
    return synthetic_case(case, delayed_key, entry, after, call,
                          '%s after %s hit %d' % (delayed_key.split(':')[1],
                                                  case.key.split(':')[1],
                                                  case.header['hit']))


def explode_as_entry(case: GC.Case) -> GC.Case:
    """P_ExplodeMissile (no captured call: P_SpawnMissile's checkMissile
    is its only caller) on an explode case's state: _Dp = AP."""
    entry = case.entry.copy()
    entry.header = case.entry.header
    ap = case.entry.read(dp_address(case, 'AP'), 4)
    entry.write(dp_address(case, '_Dp'), ap)
    key = 'p_mobj65.s:P_ExplodeMissile'
    after, call = ref_call(entry, key)
    return synthetic_case(case, key, entry, after, call,
                          'P_ExplodeMissile on explode hit %d' %
                          case.header['hit'])


SEQ_SPEC = {'native': 'ms_t_seq', 'in': [], 'out': []}
MT_GIVEN, MT_PREV, MT_AGAIN = 1, 2, 4


def seq_case(base: GC.Case, flags: int, mtype: int = 0,
             given: Optional[int] = None, full_pool: bool = True,
             note: str = '') -> Tuple[GC.Case, Dict[str, Any]]:
    """ms_t_seq's steps on ref816, one --call after the other, from the
    base case's entry state (with full_pool the pool filled first, a puff
    spawned at the player's place for each free slot, so that the next
    spawn is a zone mobj): P_SpawnMobj at the player's place (unless MT_GIVEN:
    the mobj at pointer given), CS_PREV1 = it (MT_PREV), P_RemoveMobj,
    P_RemoveThingDelayed, P_SpawnMobj again (MT_AGAIN). The case (entry
    and the last return) and the native inputs."""
    t = GC.CL.Linkmap()
    mem = base.entry.copy()
    mem.header = base.entry.header
    up0 = GR.Upstream(GC.Case(base.header, mem, mem, None))
    pl = up0.s_in['objects']['player'][0]
    pmo = pl['mo']
    o = up0.s_in['objects'][pmo.kind][pmo.id]
    x, y = o['x'] & 0xFFFFFFFF, o['y'] & 0xFFFFFFFF
    z = 0x80000000
    info: Dict[str, Any] = {'flags': flags, 'type': mtype}
    s = base.regs_in['s']
    dp = dp_address(base, '_Dp')

    def spawn(m, kind=None):
        return ref_call(m, 'p_spawn65.s:P_SpawnMobj',
                        [(dp, y.to_bytes(4, 'little') +
                          z.to_bytes(4, 'little')),
                         ((s + 4) & 0xFFFF, (mtype if kind is None else
                                             kind).to_bytes(2, 'little'))],
                        {'a': x & 0xFFFF, 'x': x >> 16})
    tp = t.address('p_spawn65.s:TP_BITS')
    filled = 0
    while full_pool and any(mem.read(tp, LL.POOL_MAX // 8)):
        # the pool made full as the game fills it: a puff a free slot
        mem, _ = spawn(mem, uconst('UC_MT_PUFF'))
        filled += 1
        if filled > LL.POOL_MAX:
            raise PartError('the pool does not fill')
    info['filled'] = filled
    entry = mem.copy()
    entry.header = mem.header
    if flags & MT_GIVEN:
        ptr = given
        cur = mem
    else:
        cur, call = spawn(mem)
        ptr = (call['end']['x'] & 0xFF) << 16 | call['end']['a'] & 0xFFFF
    info['first'] = ptr
    if flags & MT_PREV:
        cur.write(t.address('p_sight65.s:CS_PREV1'), _ptr4(ptr))
    cur, call = ref_call(cur, 'p_spawn65.s:P_RemoveMobj', [(dp, _ptr4(ptr))])
    cur, call = ref_call(cur, 'p_think65.s:P_RemoveThingDelayed',
                         [(dp, _ptr4(ptr))])
    if flags & MT_AGAIN:
        cur, call = spawn(cur)
        info['second'] = (call['end']['x'] & 0xFF) << 16 | \
            call['end']['a'] & 0xFFFF
    case = synthetic_case(base, base.key, entry, cur, call, note)
    return case, info


def seq_run(case: GC.Case, info: Dict[str, Any], b: RC.Build,
            given_slot: Optional[int], fills=FILLS, profiles=PROFILES
            ) -> List[Dict[str, Any]]:
    """ms_t_seq natively from the case's entry state; the final states
    compared; the slots (ms_t_res): the first a zone slot when the pool
    is full, the second spawn's the first's again (the zone's free list:
    no slot handed out twice, and none taken while a live object holds
    it: the port reader refuses two objects in a slot); GT_ZPREV raised
    with MT_PREV, else not."""
    prep = Prepared(case, SEQ_SPEC)
    if prep.problems:
        return [{'case': case.header['note'], 'ok': False,
                 'error': 'bridge: %s' % prep.problems[:2]}]
    pl = prep.up.s_in['objects']['player'][0]
    o = prep.up.s_in['objects'][pl['mo'].kind][pl['mo'].id]
    zp = [(GR.zp_address('GA_X'), (o['x'] & 0xFFFFFFFF).to_bytes(4,
                                                                'little')),
          (GR.zp_address('GA_Y'), (o['y'] & 0xFFFFFFFF).to_bytes(4,
                                                                'little')),
          (GR.zp_address('GA_Z'), (0x80000000).to_bytes(4, 'little')),
          (GR.zp_address('GA_TYPE'), bytes([info['type']])),
          (LL.G['GT_ZPREV'], b'\0')]
    regs = {'y': info['flags']}
    if given_slot is not None:
        regs['a'], regs['x'] = given_slot & 0xFF, given_slot >> 8
    pool = prep.up.s_in['globals'].get('p_setup65.s:_g_thingPoolSize')
    out = []
    for fill in fills:
        for prof in profiles:
            r = run_one(case, SEQ_SPEC, b, fill, prof, zp=zp,
                        regs_over=regs, prep=prep, keep_done=True)
            m = r.pop('_done', None)
            r['kind'] = 'sequence'
            r['flags'] = info['flags']
            if m is not None:
                at = b.labels['ms_t_res']
                mem = m.main
                if at >= 0xC000:        # (the card's driver area since
                    mem, at = m.lc, at - 0xC000     # wave 1's integration)
                first = mem[at] | mem[at + 1] << 8
                second = mem[at + 2] | mem[at + 3] << 8
                r['slots'] = [first, second]
                more = []
                if info.get('zone') and not (isinstance(pool, int) and
                                             first >= pool):
                    more.append('the first spawn\'s slot %d is not a zone '
                                'slot (pool %s)' % (first, pool))
                if info['flags'] & MT_AGAIN and second != first:
                    more.append('the second spawn took slot %d, not the '
                                'freed %d' % (second, first))
                zprev = m.main[LL.G['GT_ZPREV']]
                if bool(zprev) != bool(info['flags'] & MT_PREV):
                    more.append('GT_ZPREV %d' % zprev)
                if more:
                    r['diff'] = (r.get('diff') or []) + more
                    r['ok'] = False
            out.append(r)
    return out


def gtab_state_records(mem, states: Sequence[int]) -> List[Tuple]:
    """Image records: the native GTAB's state records of states as the
    reference's memory has them (a synthetic poke of the states table on
    both sides: GTAB holds upstream's records)."""
    t = GC.CL.Linkmap()
    out = []
    for n in states:
        raw = mem.read(t.address(STATES) + 16 * n, 16)
        out.append((1, LL.GTAB, LL.GT['STATES'][0] + 16 * n, bytes(raw)))
    return out


def chain0_case(base: GC.Case) -> Tuple[GC.Case, List[Tuple]]:
    """A chain of 0-tic states (no state of info65.s has 0 tics: made by
    poking the states table on both sides): the call's state S and S+1
    get tics 0 and no action, S's next S+1, S+1's next S+2, S+2 tics 5
    and no action; P_SetMobjState must walk the chain to S+2."""
    t = GC.CL.Linkmap()
    mem = base.entry.copy()
    mem.header = base.entry.header
    s = base.regs_in['a'] & 0xFFFF
    chain = [s, s + 1, s + 2]
    for i, n in enumerate(chain):
        a = t.address(STATES) + 16 * n
        rec = bytearray(mem.read(a, 16))
        rec[4:6] = (0 if i < 2 else 5).to_bytes(2, 'little')
        rec[6:10] = bytes(4)
        if i < 2:
            rec[10:12] = chain[i + 1].to_bytes(2, 'little')
        mem.write(a, bytes(rec))
    after, call = ref_call(mem, base.key)
    case = synthetic_case(base, base.key, mem, after, call,
                          'a chain of 0-tic states from %d' % s)
    return case, gtab_state_records(mem, chain)


def rocket_cases(base: GC.Case) -> List[Tuple[str, GC.Case, bool, List]]:
    """The rocket cheat on a monster's P_SetMobjState call: with the cheat
    CF_ENEMY_ROCKETS on, states of the mobj's type in [missilestate,
    painstate) with an action call A_CyberAttack instead (the first and
    the last of the range, given an action; the native stops at the
    unbuilt A_CyberAttack); painstate and missilestate - 1 call their own
    action; with the cheat off missilestate calls its own. (what, the
    case with the state and the cheat poked, cyber expected, pokes)."""
    t = GC.CL.Linkmap()
    up = GR.Upstream(base)
    mo = up.ref(int.from_bytes(up.source('dp:_Dp:4'), 'little'))
    mtype = up.s_in['objects'][mo.kind][mo.id]['type']
    info = t.address('info65.s:mobjinfo') + 64 * mtype
    missile = int.from_bytes(base.entry.read(
        info + uconst('UO_MI_MISSILESTATE'), 2), 'little')
    pain = int.from_bytes(base.entry.read(info + uconst('UO_MI_PAINSTATE'),
                                          2), 'little')
    if not missile or pain <= missile:
        return []
    cheats = t.address('g_game65.s:_g_player') + uconst('UO_PL_CHEATS')
    old = int.from_bytes(base.entry.read(cheats, 2), 'little')
    on = (old | uconst('UC_CF_ENEMY_ROCKETS')).to_bytes(2, 'little')
    off = (old & ~uconst('UC_CF_ENEMY_ROCKETS')).to_bytes(2, 'little')
    out = []
    in_range = [n for n in range(missile, pain)
                if state_record(base.entry, n)['action']]
    picks = []
    if in_range:
        picks += [('cheat, missilestate range first', in_range[0], on, True),
                  ('cheat, missilestate range last', in_range[-1], on, True)]
        picks.append(('no cheat, missilestate range', in_range[0], off,
                      False))
    for what, n in (('cheat, painstate', pain),
                    ('cheat, missilestate - 1', missile - 1)):
        if state_record(base.entry, n)['action']:
            picks.append((what, n, on, False))
    for what, n, ch, cyber in picks:
        mem = base.entry.copy()
        mem.header = base.entry.header
        mem.write(cheats, ch)
        hdr = dict(base.header, call=dict(base.header['call'],
                                          start=dict(base.regs_in, a=n)))
        c = GC.Case(hdr, mem, mem, None)
        out.append(('%s (type %d, state %d)' % (what, mtype, n), c, cyber,
                    []))
    return out


def ref_case(base: GC.Case, key: str, pokes: Sequence[Tuple[int, bytes]],
             note: str, regs: Optional[Dict[str, int]] = None) -> GC.Case:
    """The reference's own call of key on base's entry state with pokes."""
    mem = base.entry.copy()
    mem.header = base.entry.header
    for a, d in pokes:
        mem.write(a, d)
    after, call = ref_call(mem, key, (), regs)
    if regs:
        call = dict(call)
    hdr = dict(base.header, routine=key, note=note, call=call)
    return GC.Case(hdr, mem, after, None)


# the synthetic entries' specs (the routine harness's schema)
BRAINLESS_SPEC = {'native': 'P_MobjBrainlessThinker',
                  'in': [{'from': 'dp:_Dp:4', 'to': 'zp:GA_0',
                          'as': 'mobj'}], 'out': []}
NEXT_SPEC = {'native': 'P_NextThinker',
             'in': [{'from': 'dp:_Dp:4', 'to': 'ax', 'as': 'thinker'}],
             'out': [{'native': 'ax', 'upstream': 'xc', 'as': 'thinker'}]}
ISPLAYER_SPEC = {'native': 'P_MobjIsPlayer',
                 'in': [{'from': 'dp:_Dp:4', 'to': 'ax', 'as': 'mobj'}],
                 'out': [{'native': 'ax', 'upstream': 'xc',
                          'as': 'player'}]}
REMOVETHING_SPEC = {'native': 'P_RemoveThing',
                    'in': [{'from': 'dp:_Dp:4', 'to': 'ax',
                            'as': 'thinker'}], 'out': []}


# ---------------------------------------------------------------------------
# The paths a call takes (the coverage report, GAME.md 3.5 step 2), from
# the reference's entry state
# ---------------------------------------------------------------------------

def path_of(key: str, up: GR.Upstream, case: GC.Case) -> str:
    try:
        s = up.s_in
        if key == 'p_tick65.s:P_SetMobjState':
            n = case.regs_in['a'] & 0xFFFF
            if n == 0:
                return 'S_NULL'
            return 'action' if state_record(case.entry, n)['action'] \
                else 'no action'
        if key == 'p_map65.s:P_DelSecnode':
            ptr = int.from_bytes(up.source('dp:_Dp:4'), 'little') & 0xFFFFFF
            ref, _ = up.r_in.classify(ptr, ('secnode',))
            if ref is None:
                return 'none'
            o = s['objects']['secnode'][ref.id]
            sec = o['m_sector']
            lst = s['objects']['sector'][sec.id].get('touching_thinglist') \
                or []
            first = bool(lst) and lst[0] == ref
            return 'sector first' if first else 'sector after'
        if key in ('p_spawn65.s:P_RemoveMobj',
                   'p_map65.s:P_UnsetThingPosition',
                   'p_mobj65.s:explode', 'p_mobj65.s:P_ExplodeMissile',
                   'p_think65.s:P_RemoveThingDelayed'):
            src = 'dp:AP:4' if key == 'p_mobj65.s:explode' else 'dp:_Dp:4'
            mo = up.ref(int.from_bytes(up.source(src), 'little'))
            o = s['objects'][mo.kind][mo.id]
            fl = o['flags']
            bits = []
            bits.append('zone' if mo.kind == 'zmobj' else 'pool')
            if fl & uconst('UC_MF_NOSECTOR'):
                bits.append('nosector')
            if fl & uconst('UC_MF_NOBLOCKMAP'):
                bits.append('noblockmap')
            if o.get('function') is None:
                bits.append('no function')
            return ', '.join(bits)
    except Exception as error:          # (a path is a report only)
        return 'unknown: %s' % type(error).__name__
    return ''


# ---------------------------------------------------------------------------
# The jobs (one a process at a time; the cases' directory and the image
# by job)
# ---------------------------------------------------------------------------

_BUILDS: Dict[str, RC.Build] = {}


def _build(obj: str) -> RC.Build:
    if obj not in _BUILDS:
        _BUILDS[obj] = load(Path(obj))
    return _BUILDS[obj]


def _clean(rs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for r in rs:
        r.pop('_crash', None)
        r.pop('_done', None)
    return rs


def _runs(case, spec, b, fills, profiles, kind, entry_key, path='',
          prep=None) -> List[Dict[str, Any]]:
    prep = prep or Prepared(case, spec)
    out = []
    for fill in fills:
        for prof in profiles:
            try:
                r = run_one(case, spec, b, fill, prof, prep=prep)
            except Exception as error:      # reported per run, never hidden
                r = {'ok': False, 'fill': '%02x' % fill, 'profile': prof,
                     'error': '%s: %s' % (type(error).__name__, error)}
            r.update(kind=kind, entry=entry_key, path=path,
                     case=r.get('case') or (case.path.name if case.path
                                            else case.header.get('note')))
            out.append(r)
    return out


def _job(job) -> List[Dict[str, Any]]:
    kind, where, path, key, obj, fills, profiles = job
    use_cases(Path(where))
    b = _build(obj)
    try:
        if kind == 'synthetic':
            return _clean(synthetic(path, b, fills, profiles))
        case = GC.load_case(Path(path))
        if kind == 'stop':
            rs = stop_check(case, b, fills, profiles)
            for r in rs:
                r.update(entry=key, path='action (unbuilt)',
                         case=Path(path).name)
            return _clean(rs)
        if kind == 'remover':
            c = removers(case, key)
            spec = spec_of(key)
            prep = Prepared(c, spec)
            return _clean(_runs(c, spec, b, fills, profiles, 'remover', key,
                                '' if prep.problems else
                                path_of(key, prep.up, c), prep))
        if kind == 'explodeM':
            c = explode_as_entry(case)
            spec = spec_of('p_mobj65.s:P_ExplodeMissile')
            prep = Prepared(c, spec)
            return _clean(_runs(c, spec, b, fills, profiles, 'synthetic',
                                'p_mobj65.s:P_ExplodeMissile',
                                path_of('p_mobj65.s:P_ExplodeMissile',
                                        prep.up, c), prep))
        spec = spec_of(key)
        prep = Prepared(case, spec)
        if kind == 'csnl':
            if prep.problems or GR.freed_nodes(prep.up) == 0:
                return []
            return _clean(_runs(case, spec, b, fills, profiles,
                                'newly eligible', 'p_map65.s:P_DelSecnode',
                                'from P_CreateSecNodeList', prep))
        return _clean(_runs(case, spec, b, fills, profiles, 'captured', key,
                            '' if prep.problems else
                            path_of(key, prep.up, case), prep))
    except Exception as error:              # reported, never hidden
        return [{'ok': False, 'kind': kind, 'entry': key,
                 'case': Path(path).name if kind != 'synthetic' else path,
                 'error': '%s: %s' % (type(error).__name__, error)}]


SYNTHETIC = ('zone-gate', 'zone-prev', 'no-function', 'no-function-zone',
             'chain0', 'rocket', 'brainless', 'next-thinker', 'is-player',
             'remove-thing', 'mv-sector', 'mv-block')
# P_TryMove's helpers (part trymove calls them from wave 4): upstream's
# mvSector, mvBlock run alone on ref816 (16-bit A and index: P = $04)
MVSECTOR_SPEC = {'native': 'mvSector',
                 'in': [{'from': 'dp:TP:4', 'to': 'ax', 'as': 'mobj'},
                        {'from': 'abs:p_map65.s:MV_SEC:4', 'to': 'zp:GA_0',
                         'as': 'sector', 'bytes': 1}], 'out': []}
MVBLOCK_SPEC = {'native': 'mvBlock',
                'in': [{'from': 'dp:TP:4', 'to': 'ax', 'as': 'mobj'},
                       {'from': 'abs:p_map65.s:tmx:4', 'to': 'zp:GA_X'},
                       {'from': 'abs:p_map65.s:tmy:4', 'to': 'zp:GA_Y'}],
                'out': []}


def _linked_things(up: GR.Upstream) -> List[Any]:
    """Mobjs in a sector's list and a block's: the player's, then the
    first and the second of the longest block list (a list's head and one
    after it)."""
    s = up.s_in
    out = [s['objects']['player'][0]['mo']]
    blocks = sorted(s['objects'].get('blocklink', {}).values(),
                    key=lambda b: -len(b.get('things') or []))
    if blocks and len(blocks[0]['things']) >= 2:
        out += [r for r in blocks[0]['things'][:2] if r not in out]
    return out


def _demo3(key: str) -> List[Path]:
    return case_paths('demo3', key)


def synthetic(name: str, b: RC.Build, fills=FILLS, profiles=PROFILES
              ) -> List[Dict[str, Any]]:
    """One synthetic group of GAME.md 2.4's row (and of the entries no run
    calls), built from demo3's captures and run."""
    out: List[Dict[str, Any]] = []
    rm = _demo3('p_spawn65.s:P_RemoveMobj')
    sm = _demo3('p_tick65.s:P_SetMobjState')

    def tag(rs, entry, what):
        for r in rs:
            r.update(kind='synthetic', entry=entry, path=what,
                     case='%s: %s' % (name, what))
        return rs
    if name in ('zone-gate', 'zone-prev', 'no-function-zone'):
        base = GC.load_case(rm[0])
        flags = {'zone-gate': MT_AGAIN, 'zone-prev': MT_PREV,
                 'no-function-zone': MT_AGAIN}[name]
        mtype = uconst('UC_MT_CLIP') if name == 'no-function-zone' else \
            uconst('UC_MT_PUFF')
        case, info = seq_case(base, flags, mtype,
                              note='%s: type %d, flags %d' % (name, mtype,
                                                              flags))
        info['zone'] = True
        out += tag(seq_run(case, info, b, None, fills, profiles),
                   'ms_t_seq', '%s (type %d)' % (name, mtype))
    elif name == 'no-function':
        for p in rm:
            base = GC.load_case(p)
            up = GR.Upstream(base)
            ptr = int.from_bytes(up.source('dp:_Dp:4'), 'little') & 0xFFFFFF
            mo = up.ref(ptr)
            if up.s_in['objects'][mo.kind][mo.id].get('function') is not None:
                continue
            mf = GR.manifest(up.gamemap)[0]
            case, info = seq_case(base, MT_GIVEN, given=ptr, full_pool=False,
                                  note='no-function: %s' % p.name)
            out += tag(seq_run(case, info, b, GR.handle_of(mf, mo), fills,
                               profiles), 'ms_t_seq',
                       'no function (%s, pooled)' % p.name)
            if len(out) >= 4 * len(fills) * len(profiles):
                break
    elif name == 'chain0':
        for p in sm:
            base = GC.load_case(p)
            n = base.regs_in['a'] & 0xFFFF
            if not n or state_record(base.entry, n)['action']:
                continue
            case, extra = chain0_case(base)
            spec = spec_of(base.key)
            prep = Prepared(case, spec)
            for fill in fills:
                for prof in profiles:
                    r = run_one(case, spec, b, fill, prof, extra=extra,
                                prep=prep)
                    out += tag([r], 'p_tick65.s:P_SetMobjState',
                               'chain of 0-tic states %d-%d' % (n, n + 2))
            break
    elif name == 'rocket':
        done = 0
        for p in sm:
            base = GC.load_case(p)
            for what, c, cyber, pokes in rocket_cases(base):
                state = c.regs_in['a'] & 0xFFFF
                if not cyber and state_record(c.entry, state)['action'] \
                        not in act_numbers():
                    continue
                act = state_record(c.entry, state)['action']
                target = 'p_enemy65.s:A_CyberAttack' if cyber else \
                    action_key(act)
                if not waiting_for([target]):
                    # the action the call makes is built in the image (wave
                    # 3 as integrated: A_FaceTarget; wave 6: the cheat's
                    # A_CyberAttack, part chase): the reference's own call,
                    # compared whole
                    rc = ref_case(c, 'p_tick65.s:P_SetMobjState', (),
                                  what, {'a': state})
                    spec = spec_of('p_tick65.s:P_SetMobjState')
                    prep = Prepared(rc, spec)
                    rs = [run_one(rc, spec, b, f, pr, prep=prep)
                          for f in fills for pr in profiles]
                else:
                    rs = stop_check(c, b, fills, profiles, cyber=cyber)
                out += tag(rs, 'p_tick65.s:P_SetMobjState', what)
                done += 1
            if done:
                break
    elif name == 'brainless':
        t = GC.CL.Linkmap()
        base = GC.load_case(sm[0])
        up = GR.Upstream(base)
        brainless = [(k, i) for k in ('mobj', 'zmobj')
                     for i, o in up.s_in['objects'].get(k, {}).items()
                     if o.get('function') ==
                     'p_tick65.s:P_MobjBrainlessThinker']
        for tics in (5, 1, -1):
            for k, i in brainless:
                o = up.s_in['objects'][k][i]
                st = o.get('state')
                if st is None:
                    continue
                if tics == 1 and state_record(
                        base.entry, state_record(base.entry,
                                                 st.id)['next'])['action']:
                    continue
                from bridge.fields import R as Ref
                ptr = up.r_in.ref_address(Ref(k, i, None))
                pokes = [(ptr + uconst('UO_MO_TICS'),
                          (tics & 0xFFFF).to_bytes(2, 'little')),
                         (dp_address(base, '_Dp'), _ptr4(ptr))]
                c = ref_case(base, 'p_tick65.s:P_MobjBrainlessThinker',
                             pokes, 'brainless, tics %d' % tics)
                out += tag(_runs(c, BRAINLESS_SPEC, b, fills, profiles,
                                 'synthetic', 'x'),
                           'p_tick65.s:P_MobjBrainlessThinker',
                           'tics %d' % tics)
                break
        del t
    elif name == 'next-thinker':
        base = GC.load_case(sm[0])
        up = GR.Upstream(base)
        th = up.s_in['globals']['p_think65.s:_g_thinkerclasscap']
        picks = [('none: the first', None), ('the first', th[0]),
                 ('the last: none', th[-1])]
        spec = [r for r in th if r.kind not in ('mobj', 'zmobj')]
        if spec:
            picks.append(('a special', spec[0]))
        for what, ref in picks:
            ptr = up.r_in.ref_address(ref) if ref is not None else 0
            c = ref_case(base, 'p_think65.s:P_NextThinker',
                         [(dp_address(base, '_Dp'), _ptr4(ptr))], what)
            out += tag(_runs(c, NEXT_SPEC, b, fills, profiles, 'synthetic',
                             'x'), 'p_think65.s:P_NextThinker', what)
    elif name == 'is-player':
        base = GC.load_case(sm[0])
        up = GR.Upstream(base)
        pmo = up.s_in['objects']['player'][0]['mo']
        other = next(R_ for R_ in up.s_in['globals'][
            'p_think65.s:_g_thinkerclasscap'] if R_.kind in ('mobj',
                                                              'zmobj')
            and R_ != pmo)
        for what, ref in (('the player\'s mobj', pmo), ('another', other)):
            ptr = up.r_in.ref_address(ref)
            c = ref_case(base, 'p_mobj65.s:P_MobjIsPlayer',
                         [(dp_address(base, '_Dp'), _ptr4(ptr))], what)
            out += tag(_runs(c, ISPLAYER_SPEC, b, fills, profiles,
                             'synthetic', 'x'), 'p_mobj65.s:P_MobjIsPlayer',
                       what)
    elif name == 'remove-thing':
        base = GC.load_case(sm[0])
        up = GR.Upstream(base)
        th = up.s_in['globals']['p_think65.s:_g_thinkerclasscap']
        picks = [('a mobj', next(r for r in th if r.kind in ('mobj',
                                                               'zmobj')))]
        spec = [r for r in th if r.kind not in ('mobj', 'zmobj')]
        if spec:
            picks.append(('a special', spec[0]))
        # (upstream removes a mobj with P_RemoveThing and a special with
        # P_RemoveThinker only: the bridge reads a mobj whose function is
        # P_RemoveThinkerDelayed as a special, and the other way round)
        for what, ref in picks:
            ptr = up.r_in.ref_address(ref)
            key, sp = ('p_think65.s:P_RemoveThing', REMOVETHING_SPEC) \
                if ref.kind in ('mobj', 'zmobj') else \
                ('p_think65.s:P_RemoveThinker',
                 LOCAL_SPECS['p_think65.s:P_RemoveThinker'])
            c = ref_case(base, key, [(dp_address(base, '_Dp'), _ptr4(ptr))],
                         what)
            out += tag(_runs(c, sp, b, fills, profiles, 'synthetic', 'x'),
                       key, what)
    elif name in ('mv-sector', 'mv-block'):
        from bridge.fields import R as Ref
        base = GC.load_case(_demo3('p_map65.s:P_UnsetThingPosition')[0])
        up = GR.Upstream(base)
        tlab = GC.CL.Linkmap()
        tp = dp_address(base, 'TP')
        nsec = len(up.s_in['objects']['sector'])
        bmx = up.s_in['globals']['p_setup65.s:_g_bmaporgx'] >> 16
        bmy = up.s_in['globals']['p_setup65.s:_g_bmaporgy'] >> 16
        bw = up.s_in['globals']['p_setup65.s:_g_bmapwidth']
        bh = up.s_in['globals']['p_setup65.s:_g_bmapheight']
        for mo in _linked_things(up):
            o = up.s_in['objects'][mo.kind][mo.id]
            ptr = up.r_in.ref_address(mo)
            if name == 'mv-sector':
                sec = o['subsector']
                cur = up.s_in['objects']['subsector'][sec.id]['sector'].id
                picks = [('to sector %d' % ((cur + k) % nsec),
                          (cur + k) % nsec) for k in (1, 7)]
                for what, s2 in picks:
                    sp = up.r_in.ref_address(Ref('sector', s2, None))
                    c = ref_case(base, 'p_map65.s:mvSector',
                                 [(tp, _ptr4(ptr)),
                                  (tlab.address('p_map65.s:MV_SEC'),
                                   _ptr4(sp))],
                                 'mvSector: %s %s' % (mo, what), {'p': 4})
                    out += tag(_runs(c, MVSECTOR_SPEC, b, fills, profiles,
                                     'synthetic', 'x'), 'p_map65.s:mvSector',
                               '%s %s' % ('player' if mo == up.s_in['objects'][
                                   'player'][0]['mo'] else 'thing', what))
                continue
            x, y = o['x'] >> 16, o['y'] >> 16
            picks = [('the same block', x, y),
                     ('the next block east', x + 128, y),
                     ('a block north', x, y + 384),
                     ('off the map west', bmx - 1, y),
                     ('off the map south', x, bmy - 1),
                     ('off the map east', bmx + 128 * bw, y),
                     ('off the map north', x, bmy + 128 * bh),
                     ('the far corner', bmx + 128 * bw - 1,
                      bmy + 128 * bh - 1)]
            for what, nx, ny in picks:
                c = ref_case(base, 'p_map65.s:mvBlock',
                             [(tp, _ptr4(ptr)),
                              (tlab.address('p_map65.s:tmx'),
                               ((nx & 0xFFFF) << 16).to_bytes(4, 'little')),
                              (tlab.address('p_map65.s:tmy'),
                               ((ny & 0xFFFF) << 16).to_bytes(4, 'little'))],
                             'mvBlock: %s %s' % (mo, what), {'p': 4})
                out += tag(_runs(c, MVBLOCK_SPEC, b, fills, profiles,
                                 'synthetic', 'x'), 'p_map65.s:mvBlock',
                           '%s' % what)
    else:
        raise PartError('no synthetic group %s' % name)
    return out


# ---------------------------------------------------------------------------
# The checkpoint
# ---------------------------------------------------------------------------

CSNL = 'p_map65.s:P_CreateSecNodeList'
CSNL_INDEX = OUT / 'csnl-freeing.json'


def _csnl_job(path: str) -> Optional[str]:
    use_cases(SHARED_CASES)
    case = GC.load_case(Path(path))
    up = GR.Upstream(case)
    if up.r_in.problems or up.r_out.problems:
        return None
    return Path(path).name if GR.freed_nodes(up) else None


def csnl_index(jobs: int = 2) -> List[str]:
    """The skeleton's demo3 P_CreateSecNodeList cases whose reference
    frees a node (S2's "waiting for P_DelSecnode": eligible with this
    part), kept in build/native/game/mobjstate/csnl-freeing.json."""
    paths = case_paths('demo3', CSNL, SHARED_CASES)
    if CSNL_INDEX.exists():
        d = json.loads(CSNL_INDEX.read_text())
        if d.get('cases') == len(paths):
            return d['freeing']
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        got = [x for x in pool.map(_csnl_job, [str(p) for p in paths],
                                   chunksize=16) if x]
    OUT.mkdir(parents=True, exist_ok=True)
    CSNL_INDEX.write_text(json.dumps({'cases': len(paths),
                                      'freeing': got}) + '\n')
    return got


def plan(obj: Path = OUT, fills=FILLS, profiles=PROFILES, sample: int = 1,
         entries: Optional[Sequence[str]] = None, synthetic_groups=SYNTHETIC,
         csnl: bool = True) -> Tuple[List[Tuple], Dict[str, Any]]:
    """The checkpoint's jobs and its eligibility table: every captured
    call of each entry (every sample-th) whose reached targets are built;
    P_SetMobjState's others as stop checks; the delayed removers on the
    states after P_RemoveMobj's and P_RemoveThinker's calls;
    P_ExplodeMissile on explode's; the skeleton's P_CreateSecNodeList
    cases that free a node; the synthetic groups."""
    o = str(obj)
    jobs: List[Tuple] = []
    elig: Dict[str, Any] = {}
    for run, key, n in CAPTURES:
        if entries and key not in entries:
            continue
        paths = case_paths(run, key)
        reached = reached_of(run, key)
        e = elig.setdefault(key, {})
        e[run] = r = {'survey_calls': len(survey_hits(run, key)),
                      'captured': len(paths), 'eligible': 0, 'waiting': {},
                      'survey_waiting': {}}
        for p in paths[::sample]:
            h = int(p.name[1:9])
            for t_ in waiting_for(reached.get(h, [])):
                r['survey_waiting'][t_] = r['survey_waiting'].get(t_, 0) + 1
            wait = waiting_for(reaches(key, GC.load_case(p))) if key in (
                'p_mobj65.s:explode', 'p_tick65.s:P_SetMobjState') else []
            if wait:
                for t_ in wait:
                    r['waiting'][t_] = r['waiting'].get(t_, 0) + 1
                if key == 'p_tick65.s:P_SetMobjState':
                    jobs.append(('stop', str(MYCASES), str(p), key, o, fills,
                                 profiles))
                continue
            r['eligible'] += 1
            jobs.append(('case', str(MYCASES), str(p), key, o, fills,
                         profiles))
            if key == 'p_spawn65.s:P_RemoveMobj':
                jobs.append(('remover', str(MYCASES), str(p),
                             'p_think65.s:P_RemoveThingDelayed', o, fills,
                             profiles))
            if key == 'p_think65.s:P_RemoveThinker':
                jobs.append(('remover', str(MYCASES), str(p),
                             'p_think65.s:P_RemoveThinkerDelayed', o, fills,
                             profiles))
            if key == 'p_mobj65.s:explode':
                jobs.append(('explodeM', str(MYCASES), str(p),
                             'p_mobj65.s:P_ExplodeMissile', o, fills,
                             profiles))
    if csnl and (not entries or CSNL in entries):
        names = csnl_index()[::sample]
        use_cases(SHARED_CASES)
        d = GC.case_dir('demo3', CSNL)
        use_cases(MYCASES)
        elig.setdefault(CSNL, {})['demo3'] = {
            'note': 'the skeleton\'s cases whose reference frees a node '
            '(S2\'s "waiting for P_DelSecnode")', 'eligible': len(names)}
        for name in names:
            jobs.append(('csnl', str(SHARED_CASES), str(d / name), CSNL, o,
                         fills, profiles))
    for name in synthetic_groups:
        jobs.append(('synthetic', str(MYCASES), name, '', o, fills,
                     profiles))
    return jobs, elig


def job_key(j: Tuple) -> str:
    kind, where, path, key, obj, fills, profiles = j
    return json.dumps([kind, Path(where).name, Path(path).name if kind !=
                       'synthetic' else path, key, list(fills),
                       list(profiles)])


def run_jobs(jobs: Sequence[Tuple], workers: int = 2, say=None,
             journal: Optional[Path] = None) -> List[Dict[str, Any]]:
    """The jobs' results; with a journal (a JSON-lines file), each job's
    results are appended as it ends and a job already there is not run
    again (an interrupted checkpoint resumes)."""
    out: List[Dict[str, Any]] = []
    done_keys: Dict[str, List[Dict[str, Any]]] = {}
    if journal is not None and journal.exists():
        for line in journal.read_text().splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue                    # (a line cut by the stop)
            done_keys[d['job']] = d['results']
    todo = []
    for j in jobs:
        k = job_key(j)
        if k in done_keys:
            out += done_keys[k]
        else:
            todo.append(j)
    if say and done_keys:
        say('%d jobs from the journal, %d to run' % (len(jobs) - len(todo),
                                                    len(todo)))

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
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for j, got in zip(todo, pool.map(_job, todo, chunksize=1)):
            keep(j, got)
            out += got
            done += 1
            if say and done % 100 == 0:
                say('%d of %d jobs' % (done, len(todo)))
    return out


def _stats(values: Sequence[int]) -> Dict[str, Any]:
    v = sorted(x for x in values if x is not None)
    if not v:
        return {'median': None, 'worst': None}
    return {'median': v[len(v) // 2], 'worst': v[-1]}


def undecodable(r: Dict[str, Any]) -> bool:
    """A captured call of P_DelSecnode whose reference state is no
    canonical state: inside P_DelSeclist, _s_sector_list still names the
    nodes freed before it (upstream clears it at the end), so its links
    are half made (the bridge's problems). Only these, and only from the
    reference's side, are counted apart; any other bridge problem is a
    failure."""
    return not r.get('ok') and r.get('kind') == 'captured' and \
        r.get('entry') == 'p_map65.s:P_DelSecnode' and \
        str(r.get('error', '')).startswith('bridge:')


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Per entry: the cases and runs, the failures, the paths, the call's
    clock (the profile's: fabric clocks, a2vm's --cost-timed) and CPU
    cycles, median and worst, on each profile; the lowest S; the stray
    writes."""
    out: Dict[str, Any] = {}
    for r in results:
        e = out.setdefault(r.get('entry') or '?', {
            'cases': set(), 'runs': 0, 'failures': 0, 'paths': {},
            'kinds': {}, 'clock': {}, 'cpu_cycles': {}, 'lowest_s': None,
            'strays': 0, 'first_failures': [], 'fc_loads': [],
            'stale_links': 0})
        if r.get('stale_links'):
            e['stale_links'] += 1
        if r.get('fc_loads') is not None:
            e['fc_loads'].append(r['fc_loads'])
        e['cases'].add(r.get('case'))
        e['runs'] += 1
        e['kinds'][r.get('kind')] = e['kinds'].get(r.get('kind'), 0) + 1
        p = r.get('path') or ''
        e['paths'][p] = e['paths'].get(p, 0) + 1
        if undecodable(r):
            # the reference's state at the entry or the return is no
            # canonical state (a structure in the middle of a change:
            # P_DelSecnode inside P_DelSeclist); counted apart, never equal
            e['undecodable'] = e.get('undecodable', 0) + 1
        elif not r.get('ok'):
            e['failures'] += 1
            if len(e['first_failures']) < 5:
                e['first_failures'].append({k: r.get(k) for k in (
                    'case', 'kind', 'fill', 'profile', 'ended', 'stop',
                    'error', 'diff', 'stray_first') if r.get(k)})
        prof = r.get('profile') or 'none'
        if r.get('kind') != 'stop':
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
        e['clock'] = {k: _stats(v) for k, v in e['clock'].items()}
        e['cpu_cycles'] = {k: _stats(v) for k, v in e['cpu_cycles'].items()}
        e['fc_loads'] = _stats(e['fc_loads'])
    return out


def check(jobs: int = 2, sample: int = 1, entries=None,
          synthetic_groups=SYNTHETIC, fills=FILLS, profiles=PROFILES,
          rebuild: bool = True, say=print) -> Dict[str, Any]:
    """The checkpoint on the part's image: report.json's checkpoint
    half."""
    if rebuild:
        build()
    b = load()
    js, elig = plan(OUT, fills, profiles, sample, entries, synthetic_groups)
    say('%d jobs' % len(js))
    start = time.time()
    journal = None
    if sample == 1 and not entries:
        # the journal of this image (its bytes' digest): another image's
        # is deleted
        import hashlib
        h = hashlib.sha256()
        for p in sorted(OUT.glob(NAME + '.*')):
            if p.suffix not in ('.lbl', '.map'):
                h.update(p.name.encode() + p.read_bytes())
        journal = OUT / ('journal-%s.jsonl' % h.hexdigest()[:16])
        for old in OUT.glob('journal-*.jsonl'):
            if old != journal:
                old.unlink()
    res = run_jobs(js, jobs, say, journal)
    rep = {'entries': summarize(res), 'eligibility': elig,
           'runs': len(res), 'failures': sum(1 for r in res
                                             if not r.get('ok') and
                                             not undecodable(r)),
           'undecodable': sum(1 for r in res if undecodable(r)),
           'strays': sum(r.get('strays') or 0 for r in res),
           'seconds': round(time.time() - start), 'fills': [
               '%02x' % f for f in fills], 'profiles': list(profiles),
           'sizes': sizes(b), 'sample': sample}
    return rep


# ---------------------------------------------------------------------------
# The planted bugs (GAME.md 2.4's row): each made in a scratch copy of the
# part's sources (build()'s bugs), its image built in a temporary
# directory, and run on the check that must catch it
# ---------------------------------------------------------------------------

MS = 'game/%s/' % PART
PLANTS: Dict[str, Dict[str, Any]] = {
    # the action called before the mobj's tics are set: the stop check
    # (the tics at the unbuilt action's DCALL are the old ones)
    'action-before-tics': {'check': 'stop', 'bugs': [
        (MS + 'msstate.s', """        lda GT_2                ; mobj->tics = st->tics (a byte: -1, 1-12)
        ldx GT_3
        jsr pl_get
        lda LW_STATE + U_ST_TICS
        sta PL_T
        lda GT_2
        ldx GT_3
        jsr pl_put
        jsr act_num             ; if (st->action): its ACTTAB number""",
         """        jsr act_num             ; (planted: the action before the tics)"""),
        (MS + 'msstate.s', """@next:  lda GT_2                ; while (!mobj->tics)""",
         """@next:  lda GT_2                ; (planted: the tics after the action)
        ldx GT_3
        jsr pl_get
        lda LW_STATE + U_ST_TICS
        sta PL_T
        lda GT_2
        ldx GT_3
        jsr pl_put
        lda GT_2""")]},
    # a mobj with no function freed at once (its pool bit), not linked and
    # left to the walk: P_RemoveMobj's captured calls of such mobjs, and
    # the synthetic removal
    'no-function-freed-at-once': {'check': 'no-function', 'bugs': [
        (MS + 'msthink.s', """        bne @on
        lda LR_MO               ; no function: P_AddThinker (the list's""",
         """        bne @on
        lda LR_MO               ; (planted: freed at once)
        ldx LR_MO+1
        FCALL poolFree
        rts
        lda LR_MO""")]},
    # a freed sector node not put on the free list (the node order: the
    # free list SN_FREE is a sequence). Wave 1 as integrated: GAME.md 2.4's
    # plant "a freed node put at the free list's tail" cannot be caught by
    # any check: the canonical model numbers the free nodes in the free
    # list's order (tools/bridge/identity.py: "the free list" last), so
    # the order of a free list is not state; its earlier catch came from
    # the plant's own interplay with the stand-ins' temporaries
    # (docs/game-parts/mobjstate.md). This plant breaks the free list
    # itself: P_DelSeclist's captured calls
    'node-not-freed': {'check': 'P_DelSeclist', 'bugs': [
        (MS + 'mslist.s', """        jsr sn_put
        lda GT_0
        sta G_SNFREE
        lda GT_1
        sta G_SNFREE+1
        lda DS_TN               ; the next node of the thing""",
         """        jsr sn_put
        lda DS_TN               ; (planted: not on the free list)""")]},
    # the block list's back link left as it was: the lists (the port
    # reader checks every prev along a list)
    'block-back-link-left': {'check': 'P_UnsetThingPosition', 'bugs': [
        (MS + 'mslist.s', """@next:  ldx UL_NX+1             ; next->prev = prev
        cpx #$FF
        beq @done""", """@next:  ldx UL_NX+1             ; next->prev = prev
        cpx #$FF
        beq @done
        lda UL_K                ; (planted: the block list's back link left)
        bne @done""")]},
    # the removal at once, not deferred to the thinker's turn of the walk
    # (whose next the walk read before the call): P_RemoveMobj's calls
    'removal-at-once': {'check': 'P_RemoveMobj', 'bugs': [
        (MS + 'msthink.s', """        ROUTINE P_RemoveThing
        ldy #FN_REMOVETHING""", """        ROUTINE P_RemoveThing
        sta MS_OBJ              ; (planted: removed at once)
        stx MS_OBJ+1
        FCALL P_RemoveThingDelayed
        rts
        ldy #FN_REMOVETHING""")]},
    # poolFree clearing the neighbour's bit: the pool's free bits (the
    # delayed remover's calls)
    'poolfree-neighbour': {'check': 'remover', 'bugs': [
        (MS + 'msthink.s', """        lda G_TPBITS,x
        ora @bit,y
        sta G_TPBITS,x
        rts
@bit:""", """        lda G_TPBITS,x
        ora @bit,y
        pha                     ; (planted: the neighbour's bit cleared)
        tya
        eor #1
        tay
        pla
        and @nbit,y
        sta G_TPBITS,x
        rts
@nbit:  .byte $FE, $FD, $FB, $F7, $EF, $DF, $BF, $7F
@bit:""")]},
    # CS_PREV left naming a freed zone slot (GAME.md 1.8 item 3): the
    # synthetic zone free of a mobj CS_PREV1 names
    'cs-prev-left': {'check': 'zone-prev', 'bugs': [
        (MS + 'msthink.s', """        lda #<STALE
        sta CS_PREV1,x
        lda #>STALE
        sta CS_PREV1+1,x
        lda #1
        sta GT_ZPREV""", """        nop                     ; (planted: CS_PREV left naming the slot)""")]},
}


def plant_jobs(check_name: str, obj: Path, limit: int = 24) -> List[Tuple]:
    """The jobs of a plant's named check, one fill, no cost model."""
    fills, profiles = (0xA5,), (None,)
    if check_name in SYNTHETIC:
        return [('synthetic', str(MYCASES), check_name, '', str(obj), fills,
                 profiles)]
    if check_name == 'stop':
        js, _ = plan(obj, fills, profiles, entries=[
            'p_tick65.s:P_SetMobjState'], synthetic_groups=('rocket',),
            csnl=False)
        return [j for j in js if j[0] in ('stop', 'synthetic')][:limit]
    if check_name == 'remover':
        js, _ = plan(obj, fills, profiles, entries=[
            'p_spawn65.s:P_RemoveMobj'], synthetic_groups=(), csnl=False)
        return [j for j in js if j[0] == 'remover'][:limit]
    if check_name == 'no-function':
        js, _ = plan(obj, fills, profiles, entries=[
            'p_spawn65.s:P_RemoveMobj'], synthetic_groups=('no-function',),
            csnl=False)
        return [j for j in js if j[0] == 'synthetic'] + \
            [j for j in js if j[0] == 'case']
    key = next(k for _, k, _ in CAPTURES if k.endswith(':' + check_name))
    js, _ = plan(obj, fills, profiles, entries=[key], synthetic_groups=(),
                 csnl=False)
    return [j for j in js if j[0] == 'case'][:limit]


def run_plant(name: str, say=None) -> Dict[str, Any]:
    """The plant's image in a temporary directory (deleted), its check's
    jobs until one fails: caught when one does."""
    p = PLANTS[name]
    tmp = Path(tempfile.mkdtemp(prefix='tmp-mobjstate-plant-',
                                dir=str(BUILD)))
    try:
        obj = build(tmp / 'game', p['bugs'])
        js = plant_jobs(p['check'], obj)
        ran = failed = 0
        first = None
        for j in js:
            for r in _job(j):
                ran += 1
                if not r.get('ok'):
                    failed += 1
                    first = first or {k: r.get(k) for k in (
                        'case', 'ended', 'stop', 'diff', 'error') if
                        r.get(k)}
            if failed:
                break
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
        _BUILDS.clear()
        _GROUPS.clear()
    out = {'check': p['check'], 'runs': ran, 'failed': failed,
           'caught': failed > 0, 'first': first}
    if say:
        say('%-28s %s' % (name, ('caught (%s): %s' % (p['check'], str(
            first)[:300])) if failed else 'NOT CAUGHT (%d runs)' % ran))
    return out


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def du_kb(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(str(path)):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total // 1024


def write_report(rep: Dict[str, Any], plants: Optional[Dict[str, Any]] =
                 None) -> Path:
    """build/native/game/mobjstate/report.json (GAME.md 2.5 item 2): per
    entry the cases and runs, failures, the call's clock and cycles on
    each profile, the lowest S, the stray writes; the sizes against the
    budget; the eligibility; the planted bugs; the part's build/ use."""
    out = dict(rep)
    out['format'] = 'game-part-report 1'
    out['part'] = PART
    out['wave'] = 1
    if plants is not None:
        out['plants'] = plants
    elif REPORT.exists():
        old = json.loads(REPORT.read_text())
        if 'plants' in old:
            out['plants'] = old['plants']
    out['build_kb'] = du_kb(OUT)
    out['notes'] = [
        'clock: the call\'s time from call_entry to its return under the '
        'profile (a2vm --cost-timed: fabric clocks); cpu_cycles: the '
        'W65C02S\'s cycles of the same span',
        'lowest_s: the lowest S of the run (the driver starts at $EF)',
        'stop checks: P_SetMobjState calls that reach an unbuilt action, '
        'checked at its DCALL against the reference at the action\'s entry',
        'sizes: the part\'s modules without mstest.s, the test routine '
        '(msapi.s, the API stand-ins of request R2, is gone since wave 1\'s '
        'integration)']
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=1, default=str) + '\n')
    return REPORT


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--synthetic', action='store_true',
                        help='the synthetic groups alone')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--entries', default='')
    args = parser.parse_args(argv)
    if args.build:
        b = load(build())
        print(json.dumps(sizes(b), indent=1))
    if args.capture:
        capture(args.jobs)
    if args.synthetic:
        b = load(build())
        res = run_jobs([('synthetic', str(MYCASES), n, '', str(OUT), FILLS,
                         PROFILES) for n in SYNTHETIC], args.jobs)
        for r in res:
            print('%-6s %-34s %s %s' % ('ok' if r.get('ok') else 'FAIL',
                                        r.get('entry'), r.get('path'),
                                        '' if r.get('ok') else
                                        (r.get('diff') or r.get('error'))))
        return 0 if all(r.get('ok') for r in res) else 1
    status = 0
    if args.check:
        rep = check(args.jobs, args.sample, [e for e in args.entries.split(
            ',') if e] or None)
        write_report(rep)
        for k, e in sorted(rep['entries'].items()):
            print('%-36s %4d cases %5d runs %3d failed  clock f121 %s '
                  'fastpath %s  S %s' % (
                      k, e['cases'], e['runs'], e['failures'],
                      e['clock'].get('f121'), e['clock'].get('fastpath'),
                      e['lowest_s']))
        print('runs %d, failures %d, stray writes %d, %d s' % (
            rep['runs'], rep['failures'], rep['strays'], rep['seconds']))
        status |= 1 if rep['failures'] or rep['strays'] else 0
    if args.plants:
        pl = {n: run_plant(n, print) for n in PLANTS}
        rep = json.loads(REPORT.read_text()) if REPORT.exists() else {}
        rep.pop('format', None)
        write_report(rep, pl)
        status |= 0 if all(p['caught'] for p in pl.values()) else 1
    return status


if __name__ == '__main__':
    sys.exit(main())
