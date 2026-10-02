#!/usr/bin/env python3
"""The routine-mode harness's native side (milestone 10, docs/GAME.md 3.5
steps 4-6): a case of tools/native/gamecap.py run on the native tic image
and compared with the reference.

Usage:  python3 tools/native/gameroutine.py --run demo3 --routine
            p_map65.s:P_CreateSecNodeList [--fills a5,5a] [--jobs 9]
            [--limit N] [--obj DIR]
        python3 tools/native/gameroutine.py --s2      (the skeleton's S2)
        python3 tools/native/gameroutine.py --eligible PART

For a case (gamecap.load_case): the reference's canonical states at the
call's entry and at its return (the bridge's Reader, tic decoding); the
native machine: the map's level base (the native setup's machine of the
map, build/native/levels/setup/tour-sk2-0M.img, which milestone 9's
acceptance keeps: the window, the level tables, LVS), poisoned
elsewhere with $A5 or $5A, the tic image (grun.Image), the entry state
written through the game manifest (native-game-1, the port writer) with
the routine mode's exclusions left out (gcanon.strip), the native-only
state derived from it (derived(): the thinker list's last, the free lists
empty, G_MOHWM, the level tables' places, the test globals 0), and the
entry's inputs (args.json: the upstream registers, direct-page and near
symbols to their native counterparts; a mobj pointer becomes its slot).
grun.run in routine mode; then the native state read back through the
manifest and compared with the reference's state at the return
(gcanon.compare, mode routine), and every declared output compared.

The entries and their arguments come from src/native/game/*/args.json
(src/native/game/README.md gives the schema): the skeleton's own
(src/native/game/skel/args.json: P_SpawnMobj, P_SetThingPosition,
P_CreateSecNodeList) and each part's.

--eligible PART: the part's entries' cases eligible now (every dispatch
target the call reached is built: the survey's reached targets, with
gcallgraph's owners) and those waiting, by the target they wait for.
"""

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge import memory as bmem, upstream  # noqa: E402
from bridge.layout import Manifest  # noqa: E402
from bridge.memory import MAIN  # noqa: E402
from bridge.port import PortReader, PortWriter, handle_decode, \
    handle_encode  # noqa: E402
from native import gamecap as GC, gcanon, glayout as GL, grun as G, \
    llayout as LL, lrun, levelconv as LC  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
BASES = BUILD / 'native' / 'levels' / 'setup'
BASE_RUN = 'tour-sk2'
ARGS_FORMAT = 'game-args 1'
TIC_GAMEMAP = 'g_game65.s:_g_gamemap'
DEFAULT_FILLS = (0xA5, 0x5A)


class HarnessError(Exception):
    pass


# ---------------------------------------------------------------------------
# args.json
# ---------------------------------------------------------------------------

def args_files() -> List[Path]:
    return sorted(SRC.glob('game/*/args.json'))


def all_args() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for p in args_files():
        d = json.loads(p.read_text())
        if d.get('format') != ARGS_FORMAT:
            raise HarnessError('%s: not %s' % (p, ARGS_FORMAT))
        for key, spec in d['entries'].items():
            if key in out:
                raise HarnessError('%s: %s declared twice' % (p, key))
            out[key] = dict(spec, file=str(p.relative_to(ROOT)))
    return out


# ---------------------------------------------------------------------------
# The level bases
# ---------------------------------------------------------------------------

def base_path(gamemap: int, bases: Path = BASES) -> Path:
    """The kept setup machine of the map (the tour's setups, by their
    setup.json's gamemap) in bases."""
    from native import setupcap
    for d in sorted(setupcap.SETUPS.glob(BASE_RUN + '-*')):
        p = d / 'setup.json'
        if p.exists() and json.loads(p.read_text())['gamemap'] == gamemap:
            return bases / (d.name + '.img')
    return bases / ('%s-map%d.img' % (BASE_RUN, gamemap))


def have_bases() -> bool:
    return all(base_path(m).exists() for m in range(1, 10))


_BASE_CACHE: Dict[Tuple[int, str], List[Tuple[int, int, int, bytes]]] = {}


def base_records(gamemap: int, bases: Path = BASES
                 ) -> List[Tuple[int, int, int, bytes]]:
    """The map's level base: the native setup's main $0000-$BFFF (the
    zero page too: the math's state) and its aux banks (the window, the
    level's tables, LVS, the game banks)."""
    key = (gamemap, str(bases))
    if key not in _BASE_CACHE:
        p = base_path(gamemap, bases)
        if not p.exists():
            raise HarnessError('no level base %s (python3 tools/native/'
                               'level_check.py --setup keeps it)' % p)
        out = []
        for kind, bank, address, data in LC.Image.parse(p.read_bytes()):
            if kind == 0:
                lo, hi = address, min(address + len(data), 0xC000)
                if lo < hi:
                    out.append((0, 0, lo, bytes(data[lo - address:
                                                     hi - address])))
            elif kind == 1 and bank not in (LL.GCODE0, LL.GCODE1,
                                            LL.GTEST):
                out.append((1, bank, address, bytes(data)))
        _BASE_CACHE[key] = out
    return _BASE_CACHE[key]


# ---------------------------------------------------------------------------
# The manifests
# ---------------------------------------------------------------------------

_MF: Dict[int, Tuple[Manifest, Dict[str, Any], List[int]]] = {}


def manifest(gamemap: int) -> Tuple[Manifest, Dict[str, Any], List[int]]:
    """The game manifest of the map, its header, and the aux banks it
    names."""
    if gamemap not in _MF:
        from native import setupcheck as SC
        meta = SC.store_meta()
        header = dict(SC.header_of(meta, gamemap), map=gamemap)
        d = GL.manifest(header, LL.symbol_list())
        text = json.dumps(d)
        banks = sorted({int(b, 16) for b in re.findall(r'aux:([0-9A-Fa-f]+):',
                                                       text)})
        _MF[gamemap] = (Manifest(d), header, banks)
    return _MF[gamemap]


def handle_of(mf: Manifest, ref) -> int:
    """A reference's native handle (any handle leaf that can name its
    kind)."""
    for spec in list(mf.kinds.values()):
        for leaf in spec['leaves']:
            enc = leaf.enc
            if enc.get('enc') == 'handle' and any(
                    r['kind'] == ref.kind for r in enc['ranges']):
                return handle_encode(enc, ref, 'handle_of')
    raise HarnessError('no handle names %r' % (ref,))


def ref_of_handle(mf: Manifest, kinds: Sequence[str], value: int):
    for spec in list(mf.kinds.values()):
        for leaf in spec['leaves']:
            enc = leaf.enc
            if enc.get('enc') == 'handle' and {r['kind'] for r in
                                               enc['ranges']} >= set(kinds):
                return handle_decode(enc, value, 'ref_of_handle')
    raise HarnessError('no handle names %s' % (kinds,))


# ---------------------------------------------------------------------------
# The native-only state
# ---------------------------------------------------------------------------

def _word(pm, address: int) -> int:
    return pm.u16(address)


def derived(pm, header: Dict[str, Any]) -> List[Tuple[int, int, int, bytes]]:
    """The native globals no canonical field holds, from the state the
    port writer wrote (docs/GAME.md 1.3-1.5): the thinker list's last, the
    zone's and the specials' free lists empty (the writer packs the
    objects of each kind from slot 0), G_MOHWM, the pool bits past the
    pool, the level tables' places (the map's header), the load action
    and the test globals 0."""
    G_ = LL.G
    out: List[Tuple[int, int, int, bytes]] = []

    def main(name: str, data: bytes) -> None:
        out.append((0, 0, G_[name], data))

    pooln = _word(pm, MAIN | G_['G_POOLN'])
    zmn = _word(pm, MAIN | G_['G_ZMN'])
    main('G_MOHWM', (pooln + zmn).to_bytes(2, 'little'))
    main('G_ZMFREE', b'\xff\xff')
    main('G_SPFREE', b'\xff' * (2 * len(LL.SPEC_KINDS)))
    written = pm.written.get(MAIN >> 16, set())
    tp = bytearray(LL.POOL_MAX // 8)
    for i in range(len(tp)):
        a = G_['G_TPBITS'] + i
        tp[i] = pm.u8(MAIN | a) if a in written else 0
    main('G_TPBITS', bytes(tp))
    # the thinker list's last: G_THFIRST through the planes and the
    # specials' records
    h = _word(pm, MAIN | G_['G_THFIRST'])
    last = 0xFFFF
    seen = 0
    while h != 0xFFFF and seen < 4096:
        last = h
        seen += 1
        if h < LL.SPEC_HANDLE:
            h = pm.u8((LL.MOBJP << 16) | (LL.PL_TNL + h)) | \
                pm.u8((LL.MOBJP << 16) | (LL.PL_TNH + h)) << 8
        else:
            rec = LL.SPECS.base + LL.SPEC_SIZE * (h - LL.SPEC_HANDLE)
            h = pm.u16((LL.ZONE0 << 16) | (rec + LL.SP['THNEXT']))
    main('G_THLAST', last.to_bytes(2, 'little'))
    lvg1 = header['lvg1']
    main('G_LTABAT', bytes(lvg1['LTAB'].to_bytes(2, 'little') +
                           lvg1['FLIDX'].to_bytes(2, 'little') +
                           lvg1['FLENT'].to_bytes(2, 'little') +
                           lvg1['BLINKS'].to_bytes(2, 'little') +
                           header['reject'].to_bytes(2, 'little')))
    main('G_LOADACT', b'\0')
    for name in ('GT_HINT', 'GT_ZPREV', 'GT_SCHED', 'GT_STREAM',
                 'GT_REKEY', 'GT_TIC'):
        main(name, bytes(dict(LL.GLOBAL_FIELDS)[name]))
    return out


# ---------------------------------------------------------------------------
# The upstream side of the arguments
# ---------------------------------------------------------------------------

class Upstream:
    """A case's reference: its memories, registers, states and pointers."""

    def __init__(self, case: GC.Case):
        self.case = case
        self.table = GC.CL.Linkmap()
        self.r_in = upstream.Reader(case.entry, tic=True)
        self.s_in = self.r_in.read()
        self.r_out = upstream.Reader(case.after, tic=True)
        self.s_out = self.r_out.read()
        self.gamemap = case.entry.u16(self.table.address(TIC_GAMEMAP))

    def source(self, text: str, when: str = 'in') -> bytes:
        regs = self.case.regs_in if when == 'in' else self.case.regs_out
        mem = self.case.entry if when == 'in' else self.case.after
        if text in ('a', 'x', 'y'):
            return (regs[text] & 0xFFFF).to_bytes(2, 'little')
        if text == 'xc':
            return ((regs['x'] & 0xFFFF) << 16 | (regs['a'] & 0xFFFF)
                    ).to_bytes(4, 'little')
        kind, _, rest = text.partition(':')
        where, _, length = rest.rpartition(':')
        n = int(length)
        if kind == 'dp':
            sym, _, off = where.partition('+')
            a = self.case.regs_in['d'] + self.table.address(sym) - \
                self.table.direct_page + int(off or 0)
            return mem.read(a & 0xFFFF, n)
        if kind == 's':
            return mem.read((self.case.regs_in['s'] + int(where)) & 0xFFFF,
                            n)
        if kind == 'abs':
            sym, _, off = where.partition('+')
            return mem.read(self.table.address(sym) + int(off or 0), n)
        raise HarnessError('an upstream source %r' % text)

    def ref(self, pointer: int, when: str = 'in'):
        r = self.r_in if when == 'in' else self.r_out
        ref, why = r.classify(pointer & 0xFFFFFF, ('mobj', 'zmobj'))
        if ref is None:
            raise HarnessError('$%06X is no mobj (%s)' % (pointer, why))
        return ref


def lv_set_address() -> int:
    """Upstream's W_SET (w_level65.s LV_SET, bank 0): the map the level
    window holds, which bmLoad compares with gamemap (m_menu65.s:1780-
    1789)."""
    from bridge import schema
    from bridge.linkmap import Symbols
    return schema.Constants(Symbols()).local('w_level65.s', 'LV_SET')


def wset_records(memory) -> List[Tuple[int, int, int, bytes]]:
    """The native G_WSET (glayout.TIC_MAIN_FIELDS) from the reference's
    W_SET in memory (a case's or a dump's: .u16): the state a run that
    loads a level starts from (wave 1 as integrated: g_resume's textures
    of the load). Not canonical: the harness writes it as it writes
    native-only state (derived())."""
    v = memory.u16(lv_set_address())
    return [(0, 0, GL.TGM['G_WSET'], bytes([v & 0xFF]))]


def fps_show_address() -> int:
    """Upstream's _g_fps_show (d_main65.s): idrate's frame rate flag."""
    from bridge.linkmap import Symbols
    return Symbols().address('d_main65.s:_g_fps_show') & 0xFFFFFF


def onground_address() -> int:
    """Upstream's PU_ONGROUND (p_user65.s): the player's onground."""
    from bridge.linkmap import Symbols
    return Symbols().address('p_user65.s:PU_ONGROUND') & 0xFFFFFF


def tic_main_records(memory) -> List[Tuple[int, int, int, bytes]]:
    """Every native global of glayout.TIC_MAIN_FIELDS from the reference's
    in memory: G_WSET (wset_records), G_FPSSHOW, the low byte of
    _g_fps_show (wave 2 as integrated: docs/game-parts/pickup.md P4), and
    G_ONGROUND, the low byte of PU_ONGROUND (wave 5 as integrated:
    docs/game-parts/player.md R1). Not canonical: written as native-only
    state at a run's start."""
    v = memory.u16(fps_show_address())
    g = memory.u16(onground_address())
    return wset_records(memory) + [
        (0, 0, GL.TGM['G_FPSSHOW'], bytes([v & 0xFF])),
        (0, 0, GL.TGM['G_ONGROUND'], bytes([g & 0xFF]))]


def zp_address(name: str) -> int:
    if name in GL.GA_NAMES:
        return GL.ZGA['GA_0'] + GL.GA_NAMES[name]
    for table in (GL.ZGA, GL.ZGT, GL.ZA, GL.ZC, GL.ZAT):
        if name in table:
            return table[name]
    raise HarnessError('no zero-page name %s' % name)


# ---------------------------------------------------------------------------
# One case
# ---------------------------------------------------------------------------

class Result(dict):
    @property
    def ok(self) -> bool:
        return bool(self.get('ok'))


def run_case(case: GC.Case, spec: Dict[str, Any], b, fill: int,
             work_root: Path = BUILD) -> Result:
    """The case on the native image b at `fill`; the comparison."""
    up = Upstream(case)
    res = Result(case=str(case.path.name) if case.path else '?',
                 routine=case.key, hit=case.header['hit'],
                 tic=case.header['tic'], fill='%02x' % fill, ok=False)
    probs = up.r_in.problems + up.r_out.problems
    if probs:
        res['error'] = 'bridge: ' + '; '.join(probs[:3])
        return res
    mf, header, banks = manifest(up.gamemap)
    skip = gcanon.skips('routine', up.s_in)
    img = G.Image(b, fill, store=True)
    img.recs += base_records(up.gamemap)     # (after the image's own)
    pm = G.tracked_memory()
    PortWriter(mf).write(gcanon.strip(up.s_in, skip), pm)
    img.recs += G.port_records(pm)
    img.recs += derived(pm, header)
    # the inputs
    regs = [0, 0, 0, 0x34]
    for item in spec.get('in', []):
        data = up.source(item['from'])
        if item.get('as') == 'mobj':
            # a NULL pointer is the native none, $FFFF (wave 2 as
            # integrated: docs/game-parts/damage.md R5)
            pointer = int.from_bytes(data, 'little') & 0xFFFFFF
            h = 0xFFFF if pointer == 0 else handle_of(mf, up.ref(pointer))
            data = h.to_bytes(2, 'little')
        to = item['to']
        if to in ('a', 'x', 'y'):
            regs['axy'.index(to)] = data[0]
        elif to == 'ax':
            regs[0], regs[1] = data[0], data[1]
        elif to.startswith('zp:'):
            n = item.get('bytes', len(data))
            img.main(zp_address(to[3:]), data[:n].ljust(n, b'\0'))
        elif to.startswith('main:'):
            n = item.get('bytes', len(data))
            img.main(LL.G[to[5:]], data[:n].ljust(n, b'\0'))
        else:
            raise HarnessError('an input destination %r' % to)
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-routine-',
                                 dir=str(work_root)))
    try:
        start = time.time()
        r = G.run(img, work, GL.MODES['ROUTINE'], spec['native'],
                  regs=tuple(regs), banks=banks)
        res['seconds'] = round(time.time() - start, 2)
        res['cycles'] = r.state.get('cycles')
        res['lowest_s'] = r.state.get('lowest_s')
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
    nat = PortReader(mf).read(SC.port_memory(m))
    diff = gcanon.compare(up.s_out, nat, 'routine')
    # the declared outputs
    lab = b.labels
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
            n = item.get('bytes', 2)
            value = int.from_bytes(bytes(m.main[a:a + n]), 'little')
        else:
            raise HarnessError('a native output %r' % nv)
        uv = int.from_bytes(up.source(item['upstream'], 'out'), 'little')
        if item.get('as') == 'mobj' and (uv & 0xFFFFFF == 0 or
                                         value & 0xFFFF == 0xFFFF):
            if not (uv & 0xFFFFFF == 0 and value & 0xFFFF == 0xFFFF):
                diff.append('output %s: %X, upstream %X (one of them none)'
                            % (item['upstream'], value, uv))
        elif item.get('as') == 'mobj':
            mine = ref_of_handle(mf, ('mobj', 'zmobj'), value)
            theirs = up.ref(uv, 'out')
            a = nat['objects'].get(mine.kind, {}).get(mine.id)
            b_ = up.s_out['objects'].get(theirs.kind, {}).get(theirs.id)
            if gcanon.strip({'globals': {}, 'objects': {'k': {0: a or {}}}},
                            skip) != gcanon.strip(
                    {'globals': {}, 'objects': {'k': {0: b_ or {}}}}, skip):
                diff.append('output %s: %s is not the mobj upstream returns '
                            '(%s)' % (item['upstream'], mine, theirs))
        else:
            mask = (1 << (8 * item.get('bytes', 2))) - 1
            if value & mask != uv & mask:
                diff.append('output %s: %X != %X' % (item['upstream'],
                                                     value & mask, uv & mask))
    res['diff'] = diff[:12]
    res['ok'] = not diff
    return res


# ---------------------------------------------------------------------------
# Many cases
# ---------------------------------------------------------------------------

def case_paths(run: str, key: str) -> List[Path]:
    return sorted(GC.case_dir(run, key).glob('h*.case.z'))


def _job(job: Tuple[str, str, Dict[str, Any], str, Sequence[int]]
         ) -> List[Dict[str, Any]]:
    path, obj, spec, name, fills = job
    b = G.load_build(Path(obj), name)
    case = GC.load_case(Path(path))
    out = []
    for fill in fills:
        try:
            out.append(dict(run_case(case, spec, b, fill)))
        except Exception as error:      # reported per case, never hidden
            out.append({'case': Path(path).name, 'fill': '%02x' % fill,
                        'ok': False, 'error': '%s: %s' % (
                            type(error).__name__, error)})
    return out


def run_cases(paths: Sequence[Path], key: str, obj: Path, name: str = 'skel',
              fills: Sequence[int] = DEFAULT_FILLS, jobs: int = 9,
              spec: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    spec = spec or all_args()[key]
    work = [(str(p), str(obj), spec, name, tuple(fills)) for p in paths]
    out: List[Dict[str, Any]] = []
    if jobs <= 1:
        for w in work:
            out += _job(w)
        return out
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_job, work, chunksize=4):
            out += got
    return out


def summary(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ok = sum(1 for r in results if r.get('ok'))
    cyc = sorted(r['cycles'] for r in results if r.get('cycles'))
    return {'runs': len(results), 'equal': ok, 'failed': len(results) - ok,
            'cycles_median': cyc[len(cyc) // 2] if cyc else None,
            'cycles_worst': cyc[-1] if cyc else None,
            'first_failures': [r for r in results if not r.get('ok')][:5]}


# ---------------------------------------------------------------------------
# Eligibility (GAME.md 3.5 step 6)
# ---------------------------------------------------------------------------

def eligibility(part: str, built: Optional[Sequence[str]] = None
                ) -> Dict[str, Any]:
    """Per entry of the part, per run: the calls whose reached dispatch
    targets are all built (with the part itself), and the calls waiting,
    by the target they wait for."""
    built = set(GL.built_set() if built is None else built) | {part}
    p = next(x for x in GL.PARTS if x['name'] == part)
    out: Dict[str, Any] = {}
    for run in GC.RUNS:
        sv = GC.survey_of(run)
        if sv is None:
            continue
        targets = sv['targets']
        for key in p['routines']:
            r = sv['routines'].get(key)
            if r is None:
                continue
            waiting: Dict[str, int] = {}
            ok = 0
            for hit in range(1, r['calls'] + 1):
                reached = r['reached'].get(str(hit), [])
                miss = [targets[i] for i in reached
                        if (GL.owner_of(targets[i]) or 'core') not in built
                        and GL.owner_of(targets[i]) != 'core']
                if miss:
                    for t in miss:
                        waiting[t] = waiting.get(t, 0) + 1
                else:
                    ok += 1
            e = out.setdefault(key, {})
            e[run] = {'calls': r['calls'], 'eligible': ok,
                      'waiting': waiting}
    return out


# ---------------------------------------------------------------------------
# S2 (GAME.md 3.9)
# ---------------------------------------------------------------------------

S2_ROUTINES = ('p_spawn65.s:P_SpawnMobj', 'p_map65.s:P_SetThingPosition',
               'p_map65.s:P_CreateSecNodeList')
ONFLOORZ = -0x80000000
ONCEILINGZ = 0x7FFFFFFF


def z_mode(case: GC.Case) -> str:
    up_z = int.from_bytes(Upstream.source(_Light(case), 'dp:_Dp+4:4'),
                          'little', signed=True)
    if up_z == ONFLOORZ:
        return 'floor'
    if up_z == ONCEILINGZ:
        return 'ceiling'
    return 'given'


class _Light(Upstream):
    """Upstream's sources without the readers (for classifying)."""

    def __init__(self, case: GC.Case):
        self.case = case
        self.table = GC.CL.Linkmap()


def lr_use(case: GC.Case) -> int:
    t = GC.CL.Linkmap()
    return case.entry.u16(t.address('p_map65.s:LR_USE'))


def caller_of(case: GC.Case, cm: GC.CallerMap) -> Optional[str]:
    """The routine that called the case's call (its JSL's return address
    on the stack at the entry)."""
    s = case.regs_in['s']
    return cm.head(int.from_bytes(case.entry.read((s + 1) & 0xFFFF, 3),
                                  'little'))


def freed_nodes(up: Upstream) -> int:
    """Sector nodes the reference's call deleted (P_DelSecnode): the
    nodes of _s_sector_list at the entry (the thing's old list) whose
    sector is not in the thing's list at the return (addSecnode takes a
    node of the old list again for a sector still touched)."""
    gi, go = up.s_in, up.s_out
    old = gi['globals'].get('p_map65.s:_s_sector_list') or []
    sec_in = [gi['objects']['secnode'][r.id]['m_sector'] for r in old]
    thing = up.ref(int.from_bytes(up.source('dp:_Dp:4'), 'little'))
    now = go['objects'][thing.kind][thing.id].get(
        'touching_sectorlist') or []
    sec_out = {go['objects']['secnode'][r.id]['m_sector'] for r in now}
    return sum(1 for x in sec_in if x not in sec_out)


DEL_SECNODE = 'p_map65.s:P_DelSecnode'


def classify(key: str, case: GC.Case, res: Dict[str, Any],
             cm: GC.CallerMap) -> str:
    """A result's class for the S2 report: equal; waiting (the native
    stopped at an unbuilt routine the reference ran: P_DelSecnode, when
    the reference freed a node); undecodable (the reference's entry
    state is not a canonical state: a mobj in the middle of its spawn);
    failed."""
    if res.get('ok'):
        return 'equal'
    err = res.get('error') or ''
    if err.startswith('bridge:'):
        return 'undecodable'
    stop = res.get('stop')
    if stop and stop[0] == GL.GS['UNBUILT']:
        keys = [k for p in GL.PARTS for k in p['routines'] + p['helpers']]
        number = (keys + GL.CORE).index(DEL_SECNODE) + 1
        if stop[1] == number and freed_nodes(Upstream(case)) > 0:
            return 'waiting:' + DEL_SECNODE
    return 'failed'


def _s2_job(job) -> List[Dict[str, Any]]:
    path, obj, key, fills = job
    b = G.load_build(Path(obj), 'skel')
    spec = all_args()[key]
    case = GC.load_case(Path(path))
    cm = GC.CallerMap()
    lt = _Light(case)
    info: Dict[str, Any] = {'case': Path(path).name, 'routine': key,
                            'hit': case.header['hit'],
                            'caller': caller_of(case, cm)}
    if key == 'p_spawn65.s:P_SpawnMobj':
        z = int.from_bytes(lt.source('dp:_Dp+4:4'), 'little', signed=True)
        info['z'] = 'floor' if z == ONFLOORZ else 'ceiling' \
            if z == ONCEILINGZ else 'given'
        info['type'] = int.from_bytes(lt.source('s:4:2'), 'little')
    if key == 'p_map65.s:P_CreateSecNodeList':
        info['lr_use'] = lr_use(case)
    out = []
    for fill in fills:
        try:
            r = dict(run_case(case, spec, b, fill))
        except Exception as error:
            r = {'ok': False, 'error': '%s: %s' % (type(error).__name__,
                                                   error)}
        r.update(info, fill='%02x' % fill)
        r['class'] = classify(key, case, r, cm)
        out.append(r)
    return out


def ceiling_cases(n: int = 4) -> List[GC.Case]:
    """Synthetic P_SpawnMobj cases with z = ONCEILINGZ (no run of the
    survey spawns under a ceiling in play): n in-play cases of demo3 with
    their z poked, run on ref816 alone (gamecap.call_case)."""
    out = []
    paths = case_paths('demo3', 'p_spawn65.s:P_SpawnMobj')
    for p in paths[len(paths) - 1::-max(1, len(paths) // (4 * n))][:n]:
        c = GC.load_case(p)
        lt = _Light(c)
        za = (c.regs_in['d'] + lt.table.address('_Dp') -
              lt.table.direct_page + 4) & 0xFFFF
        out.append(GC.call_case(c, [(za, ONCEILINGZ.to_bytes(4, 'little'))],
                                'ceiling z (synthetic)'))
    return out


def s2(obj: Path = G.GAME / 'skel', sample: int = 1, jobs: int = 9,
       fills: Sequence[int] = DEFAULT_FILLS, say=print) -> Dict[str, Any]:
    """S2 (GAME.md 3.9): the three routines' demo3 cases (every sample-th),
    both fills, classified; the synthetic ceiling spawns; the grep check."""
    report: Dict[str, Any] = {'routines': {}, 'failures': []}
    for key in S2_ROUTINES:
        paths = case_paths('demo3', key)[::sample]
        work = [(str(p), str(obj), key, tuple(fills)) for p in paths]
        res: List[Dict[str, Any]] = []
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for got in pool.map(_s2_job, work, chunksize=4):
                res += got
        classes: Dict[str, int] = {}
        for r in res:
            classes[r['class']] = classes.get(r['class'], 0) + 1
        by: Dict[str, Dict[str, int]] = {}
        for r in res:
            for k in ('z', 'caller', 'lr_use'):
                if k in r:
                    d = by.setdefault(k, {})
                    v = '%s=%s/%s' % (r[k], r['class'], r['fill'])
                    d[v] = d.get(v, 0) + 1
        report['routines'][key] = {'cases': len(paths), 'runs': len(res),
                                   'classes': classes, 'by': by}
        for r in res:
            if r['class'] == 'failed':
                report['failures'].append('%s %s %s: %s' % (
                    key, r['case'], r['fill'], (r.get('diff') or
                                                [r.get('error') or
                                                 r.get('ended')])[:2]))
        say('%s: %d cases, %d runs: %s' % (key, len(paths), len(res),
                                            classes))
    # the ceiling z mode, synthetic
    b = G.load_build(obj, 'skel')
    spec = all_args()['p_spawn65.s:P_SpawnMobj']
    ceil = {'runs': 0, 'equal': 0}
    for c in ceiling_cases():
        for fill in fills:
            r = run_case(c, spec, b, fill)
            ceil['runs'] += 1
            ceil['equal'] += bool(r.ok)
            if not r.ok:
                report['failures'].append('ceiling: %s' % r.get('diff'))
    report['ceiling_synthetic'] = ceil
    say('P_SpawnMobj, ONCEILINGZ (synthetic): %d runs, %d equal' % (
        ceil['runs'], ceil['equal']))
    report['grep'] = grep_check()
    report['failures'] += report['grep']
    say('the grep check: %s' % (report['grep'] or 'no cached kind reached '
                                'past the API'))
    return report


# the game core outside gobj.s (GAME.md 3.9 S2, review 2)
GREP_FILES = ('gthink.s', 'gpos.s', 'gspawn.s', 'gspec.s', 'gvalid.s',
              'gweap.s', 'lsetup.s')
FAR_CALLS = ('g_get', 'g_put', 'g_put2', 'far_get', 'far_put')
# the cached kinds' banks: mobjs (RTH, MOBJA-C); sectors (LVMAP's render
# records, LVG1's game records); lines (LVG0); specials (ZONE0). LVG1 also
# holds tables no cache keeps (the blocklinks, LTAB, FLIDX, FLENT): a far
# access to LVG1 must name one of them.
CACHED_BANKS = ('RTH', 'MOBJA', 'MOBJB', 'MOBJC', 'LVMAP', 'LVG0', 'ZONE0')
LVG1_TABLES = ('G_BLINKSAT', 'G_LTABAT', 'G_FLIDXAT', 'G_FLENTAT')


# helpers that set FA_BANK to a bank no cache keeps (lload.s ld_block: a
# lump of the store)
BANK_HELPERS = {'ld_block': 'STORE'}


def _code(line: str) -> List[str]:
    """A source line's instruction words: its comment and labels off."""
    words = line.split(';')[0].split()
    while words and words[0].endswith(':'):
        words = words[1:]
    return words


def grep_check(root: Path = SRC, files: Sequence[str] = GREP_FILES
               ) -> List[str]:
    """Every far access (jsr g_get, g_put, far_get, far_put) of the game
    core outside gobj.s: its bank (the nearest `lda #BANK` before its `sta
    FA_BANK`) is a literal and no cached kind's (CACHED_BANKS; LVG1 only
    for its uncached tables, named within the 40 lines before)."""
    out = []
    for name in files:
        p = root / name
        if not p.exists():
            continue
        lines = [_code(x) for x in p.read_text().splitlines()]
        for i, code in enumerate(lines):
            if len(code) < 2 or code[0] != 'jsr' or code[1] not in FAR_CALLS:
                continue
            bank = None
            for j in range(i - 1, max(-1, i - 24), -1):
                c = lines[j]
                if len(c) >= 2 and c[0] == 'jsr' and c[1] in BANK_HELPERS:
                    bank = '#' + BANK_HELPERS[c[1]]
                    break
                if len(c) >= 2 and c[0] == 'sta' and c[1] == 'FA_BANK':
                    for k in range(j - 1, max(-1, j - 6), -1):
                        d = lines[k]
                        if len(d) >= 2 and d[0] == 'lda':
                            bank = d[1]
                            break
                    break
            where = '%s:%d' % (name, i + 1)
            if bank is None or not bank.startswith('#'):
                out.append('%s: %s of a bank that is not a literal (%s)' % (
                    where, code[1], bank))
                continue
            bank = bank[1:]
            if bank in CACHED_BANKS:
                out.append('%s: %s of %s, a cached kind\'s bank' % (
                    where, code[1], bank))
            if bank == 'LVG1':
                near = ' '.join(' '.join(x) for x in lines[max(0, i - 40):i])
                if not any(t in near for t in LVG1_TABLES):
                    out.append('%s: %s of LVG1 names none of its uncached '
                               'tables' % (where, code[1]))
    return out


# S7's planted bugs for S2: (the cases they must fail on: P_CreateSecNodeList
# with LR_USE 1 or 0; the edits of src/native files)
S2_PLANTS = {
    # a missed write-back: a line's stamp left out of its bank (ln_dirty
    # marks nothing): the walk's stamps are lost at the flush
    'missed-write-back': (0, [('gobj.s', """        lda #1
        sta LNC_DT,x
        rts
@none:  lda #GS_API""", """        lda #0                  ; (planted: not marked)
        sta LNC_DT,x
        rts
@none:  lda #GS_API""")]),
    # gp_secnodes walking and stamping with LR_USE set (mvNodes' record
    # ignored)
    'lr-use-walk': (1, [('gpos.s', """@range: lda G_LRUSE             ; the line record (mvNodes): its lines'
        beq @walk               ;   sectors, no walk and no stamp
        stz G_LRUSE""", """@range: stz G_LRUSE             ; (planted: the walk all the same)
        bra @walk
        stz G_LRUSE""")]),
}


def run_s2_plant(name: str, n: int = 12, fill: int = 0xA5
                 ) -> Dict[str, Any]:
    """The planted bug's S2 run: a planted skeleton image (grun.planted),
    on n P_CreateSecNodeList cases of the plant's LR_USE that the tree's
    image passes; the failures it gives (a caught bug gives some)."""
    import tempfile as _t
    lr, bugs = S2_PLANTS[name]
    key = 'p_map65.s:P_CreateSecNodeList'
    good = G.load_build(G.GAME / 'skel', 'skel')
    spec = all_args()[key]
    chosen = []
    for p in case_paths('demo3', key)[300::7]:
        c = GC.load_case(p)
        if lr_use(c) != lr:
            continue
        if run_case(c, spec, good, fill).ok:
            chosen.append(c)
        if len(chosen) >= n:
            break
    tmp = Path(_t.mkdtemp(prefix='tmp-m10-s2plant-', dir=str(BUILD)))
    try:
        obj = G.planted(tmp, bugs)
        b = G.load_build(obj, 'skel')
        fails = [r for r in (run_case(c, spec, b, fill) for c in chosen)
                 if not r.ok]
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    return {'cases': len(chosen), 'failed': len(fails),
            'first': (fails[0].get('diff') or [fails[0].get('ended')])[:2]
            if fails else None}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--run', default='demo3')
    parser.add_argument('--routine')
    parser.add_argument('--fills', default='a5,5a')
    parser.add_argument('--jobs', type=int, default=9)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--obj', type=Path, default=G.GAME / 'skel')
    parser.add_argument('--name', default='skel')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--eligible')
    parser.add_argument('--s2', action='store_true')
    parser.add_argument('--plants', action='store_true',
                        help='S7: the planted bugs S2 must catch')
    parser.add_argument('--sample', type=int, default=1)
    args = parser.parse_args(argv)
    if args.plants:
        bad = 0
        for name in S2_PLANTS:
            r = run_s2_plant(name)
            bad += not r['failed']
            print('%-20s %s' % (name, ('caught: %d of %d cases fail: %s' % (
                r['failed'], r['cases'], r['first'])) if r['failed']
                else 'NOT CAUGHT (%d cases)' % r['cases']))
        return 1 if bad else 0
    if args.s2:
        rep = s2(args.obj, args.sample, args.jobs,
                 [int(x, 16) for x in args.fills.split(',')])
        if args.json:
            args.json.write_text(json.dumps(rep, indent=1) + '\n')
        for f in rep['failures'][:10]:
            print('  ' + f)
        return 1 if rep['failures'] else 0
    if args.eligible:
        print(json.dumps(eligibility(args.eligible), indent=1))
        return 0
    if not args.routine:
        parser.error('--routine FILE:LABEL')
    paths = case_paths(args.run, args.routine)
    if args.limit:
        paths = paths[:args.limit]
    fills = [int(x, 16) for x in args.fills.split(',')]
    start = time.time()
    res = run_cases(paths, args.routine, args.obj, args.name, fills,
                    args.jobs)
    s = summary(res)
    print('%s %s: %d cases, %d runs: %d equal, %d failed (%.0f s)' % (
        args.run, args.routine, len(paths), s['runs'], s['equal'],
        s['failed'], time.time() - start))
    for f in s['first_failures']:
        print('  %s' % json.dumps(f)[:600])
    if args.json:
        args.json.write_text(json.dumps({'summary': s, 'results': res},
                                        indent=1) + '\n')
    return 1 if s['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
