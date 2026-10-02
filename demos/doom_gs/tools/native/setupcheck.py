#!/usr/bin/env python3
"""The checks of milestone 9's stage C (docs/LEVELS.md 5.2, 5.4-5.6, 6.3):
the native P_SetupLevel on a2vm against ref816's setups.

    python3 tools/native/level_check.py --setup     # acceptance 1
    python3 tools/native/level_check.py --flood     # acceptance 3
    python3 tools/native/level_check.py --setup-timing

The pre-state (5.4): each setup's E dump (upstream's state at
P_SetupLevel's entry: banks $00, $02, $0D) written into the native game
globals block (main GBLOCK, llayout.py) and P_Random's and M_Random's
indexes through the manifest native-level-1 (llayout.manifest), as a test
pre-state record in bank PRE_BANK. Only what the setup reads or leaves as
it is goes in: every leaf of the game globals and the player but those
the setup always writes (GLOBAL_WRITES, PLAYER_WRITES), whose bytes stay
the run's poison, so a write the native setup misses shows. A leaf's value
is its E bytes decoded (numbers); a reference keeps E's bytes, which equal
R's for every reference the setup does not write, and is then R's
canonical value (the same bytes read against the level they point into);
a reference whose E and R bytes differ is one the setup writes, and a
leaf the classification says it does not write is then a failure.

Acceptance 1 (5.2): for each setup, ref816's R dump read by the bridge
(C_ref) against the native machine after nl_setup read through
native-level-1 by the port reader and renumbered (C_nat), canonical.diff
exact but the caches (schema.compare_skips 'lockstep': the caches of 5.2
exclusion 4, which the native layout does not keep); the other exclusions
of 5.2 are outside the canonical model already. Each run takes one
capture run's setups in its order (the reloads after their maps' first
loads), from both poisoned machines; after each setup the level window
equals the map's window.img outside its stage-C mask; the write log holds
no CPU write outside the setup's allowed set (llayout.allowed_writes_setup)
or the driver's (its pre-state copies), each setup's writes against its
own map's set (the log cut at each drv_loaded); the stack within the
budget; the
zone-mobj bound of each R dump within 2,026 - poolsize (3.1).
"""

import json
import shutil
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import levelconv as LC, llayout as LL, lstore, \
    rlayout as R  # noqa: E402
from native import setupcap  # noqa: E402

ROOT = HERE.parent.parent
LEVELS = ROOT / 'build' / 'native' / 'levels'

# what P_SetupLevel always writes (docs/LEVELS.md 2.1): not part of the
# pre-state (p_setup65.s:104-160, p_spawn65.s spawnPlayer, p_pspr65.s
# P_SetupPsprites, P_SpawnSpecials' buttons, the load's globals)
GLOBAL_WRITES = (
    ('g_game65.s:_g_totalkills',), ('g_game65.s:_g_totallive',),
    ('g_game65.s:_g_totalitems',), ('g_game65.s:_g_totalsecret',),
    ('g_game65.s:_g_wminfo', 'partime'), ('p_think65.s:_g_leveltime',),
    ('p_think65.s:_g_thinkerclasscap',), ('p_map65.s:_s_sector_list',),
    ('p_map65.s:SN_FREE',), ('p_setup65.s:_g_bmapwidth',),
    ('p_setup65.s:_g_bmapheight',), ('p_setup65.s:_g_bmaporgx',),
    ('p_setup65.s:_g_bmaporgy',), ('p_setup65.s:_g_blockmap',),
    ('p_setup65.s:_g_thingPoolSize',), ('p_sight65.s:LOGP',),
    ('p_setup65.s:_g_numsectors',), ('p_setup65.s:numsides',),
    ('p_setup65.s:_g_numlines',), ('p_setup65.s:numsubsectors',),
    ('p_setup65.s:numnodes',))
# the boot's constants (P_Init): the store's GTAB, not a pre-state
BOOT_GLOBALS = ('p_switch65.s:switchlist', 'p_switch65.s:SW_IDX',
                'p_spec65.s:animated_texture_basepic')
# milestone 10: the setup clears the line record's LR_OK too
# (p_setup65.s:104)
GLOBAL_WRITES = GLOBAL_WRITES + (('p_map65.s:LR_OK',),)
PLAYER_WRITES = (
    ('mo',), ('viewz',), ('killcount',), ('itemcount',), ('secretcount',),
    ('refire',), ('message',), ('damagecount',), ('bonuscount',),
    ('extralight',), ('fixedcolormap',), ('viewheight',), ('momx',),
    ('momy',), ('pendingweapon',), ('psprites', 0, 'state'),
    ('psprites', 0, 'tics'), ('psprites', 0, 'sy'), ('psprites', 1, 'state'))


KEEP_RUN = 'tour-sk2'           # the setups whose machines --setup keeps
                                #   (the flood check reads them)
FLOOD_STACK = 512               # docs/LEVELS.md 5.5: the native work stack


class SetupError(Exception):
    pass


def _schema():
    from bridge import upstream
    return upstream.Schema()


def store_meta() -> Dict[str, Any]:
    return json.loads((lstore.STORE / 'store.json').read_text())


def header_of(meta: Dict[str, Any], gamemap: int) -> Dict[str, Any]:
    return dict(meta['maps']['E1M%d' % gamemap]['header'], map=gamemap)


_MANIFESTS: Dict[int, Any] = {}
_SYMBOLS: List[str] = []


def manifest_of(gamemap: int, meta: Optional[Dict[str, Any]] = None):
    """native-level 1 of a map (a bridge Manifest), once a process."""
    from bridge.layout import Manifest
    if gamemap not in _MANIFESTS:
        if not _SYMBOLS:
            _SYMBOLS.extend(LL.symbol_list())
        meta = meta or store_meta()
        _MANIFESTS[gamemap] = Manifest(LL.manifest(header_of(meta, gamemap),
                                                   _SYMBOLS))
    return _MANIFESTS[gamemap]


# ---------------------------------------------------------------------------
# The pre-state
# ---------------------------------------------------------------------------

def e_memory(d: Path):
    """The E dump of a setup as a bridge Memory (banks $00, $02, $0D)."""
    from bridge import memory as bmem
    from native import rendercap
    data = rendercap.load_dump(d / 'e.dump.z').data
    m = bmem.Memory()
    for k, bank in enumerate((0x00, 0x02, 0x0D)):
        m.banks[bank] = bytearray(data[k * 0x10000:(k + 1) * 0x10000])
    return m


def upstream_extent(sch, root_type, address: int, path: Sequence[Any]):
    """The upstream address and type of a canonical path inside a value of
    root_type at address."""
    from bridge.fields import Array, Struct, Sub
    t = root_type
    for p in path:
        if isinstance(t, Sub):
            t = t.struct
        if isinstance(t, Struct):
            f = t.by_name[p]
            address += f.offset
            t = f.type
        elif isinstance(t, Array):
            address += p * t.elem.length
            t = t.elem
        else:
            raise SetupError('a path %r into %r' % (path, t))
    if isinstance(t, Sub):
        t = t.struct
    return address, t


def _get(obj: Any, path: Sequence[Any]) -> Any:
    for p in path:
        obj = obj[p]
    return obj


def leaf_value(sch, root_type, address: int, path, em, rm, ref_value):
    """A pre-state leaf's value: E's bytes (numbers, raw bytes); for a
    reference, R's canonical value when E's bytes are R's."""
    from bridge.fields import Int, Raw, Ref
    a, t = upstream_extent(sch, root_type, address, path)
    n = t.length if hasattr(t, 'length') else t.size
    eb, rb = em.read(a, n), rm.read(a, n)
    if isinstance(t, Int):
        return int.from_bytes(eb, 'little', signed=t.signed)
    if isinstance(t, Raw):
        return eb.hex()
    if isinstance(t, Ref):
        if eb != rb:
            raise SetupError('%s: a reference the setup does not write '
                             'differs between E and R' % (path,))
        return ref_value
    raise SetupError('%s: a value of %r' % (path, t))


def prestate(mf, d: Path, ref: Dict[str, Any], rm, fill: int,
             sch=None) -> bytes:
    """The test pre-state record of setup d (docs/LEVELS.md 5.4): the game
    globals block (fill but the injected leaves) and the two random
    indexes."""
    from bridge import schema
    from bridge.memory import MAIN, PortMemory
    from bridge.port import PortWriter
    sch = sch or _schema()
    em = e_memory(d)
    w = PortWriter(mf)
    w.m = PortMemory()
    w.pool_fill = {}
    w.m.write(MAIN | LL.GBLOCK, bytes([fill]) * LL.PRE_RND)
    w.m.write(MAIN | LL.PRND, bytes([fill]) * 2)
    w.m.write(MAIN | LL.G_VALID, bytes([fill]) * 2)
    types = {}
    for unit, labels in list(schema.GLOBALS.items()) + list(
            schema.EXTERNAL_GLOBALS.items()):
        for label, text in labels.items():
            if text.startswith('cache:'):
                text = text[6:]
            types['%s:%s' % (unit, label)] = text
    writes = set(GLOBAL_WRITES)
    for leaf in mf.globals:
        name = leaf.path[0]
        if leaf.enc['enc'] == 'table' or name in BOOT_GLOBALS:
            continue
        if any(leaf.path[:len(p)] == p for p in writes):
            continue
        text = types[name]
        t = sch.structs[text] if text in sch.structs else \
            schema.field_type(text, sch.structs)
        address = sch.symbols.address(name)
        value = leaf_value(sch, t, address, leaf.path[1:], em,
                           _MemoryOf(rm), _get(ref['globals'],
                                               leaf.path)
                           if _has(ref['globals'], leaf.path) else None)
        w.encode(leaf, 0, value)
    player = ref['objects']['player'][0]
    pl_addr = sch.symbols.address('g_game65.s:_g_player')
    for leaf in mf.kinds['player']['leaves']:
        if any(leaf.path[:len(p)] == p for p in PLAYER_WRITES):
            continue
        value = leaf_value(sch, sch.structs['PL'], pl_addr, leaf.path, em,
                           _MemoryOf(rm), _get(player, leaf.path))
        w.encode(leaf, 0, value)
    main = w.m.read(MAIN | LL.GBLOCK, LL.PRE_RND)
    rnd = w.m.read(MAIN | LL.PRND, 2)
    # milestone 10: validcount is the frame block's (G_VALID), after them
    valid = w.m.read(MAIN | LL.G_VALID, 2)
    return bytes(main) + bytes(rnd) + bytes(valid)


def _has(obj: Any, path: Sequence[Any]) -> bool:
    try:
        _get(obj, path)
        return True
    except (KeyError, IndexError, TypeError):
        return False


class _MemoryOf:
    """A bridge Memory's read for a levelconv memory (the R dump)."""

    def __init__(self, m):
        self.m = m

    def read(self, address: int, n: int) -> bytes:
        return bytes(self.m.read(address, n))


# ---------------------------------------------------------------------------
# The native state read back
# ---------------------------------------------------------------------------

def port_memory(mach):
    """A SnapMachine (main, aux banks) as the bridge's PortMemory."""
    from bridge.memory import MAIN, PortMemory
    pm = PortMemory()
    pm.write(MAIN, bytes(mach.main[0:0xC000]))
    for bank, data in mach.aux.items():
        pm.write(bank << 16, bytes(data[0:0xC000]))
    return pm


def native_state(mach, mf) -> Dict[str, Any]:
    from bridge.port import PortReader
    return PortReader(mf).read(port_memory(mach))


def skips(sch=None) -> List[str]:
    """What acceptance 1 does not compare: the caches (docs/LEVELS.md 5.2
    exclusion 4), which the native layout does not keep."""
    from bridge import schema
    sch = sch or _schema()
    out = schema.compare_skips(sch.structs, 'lockstep')
    for name in LL.NOT_KEPT + LL.NOT_KEPT_FIELDS:
        if name not in out:
            raise SetupError('%s is not a cache of the bridge' % name)
    return out


def compare(ref: Dict[str, Any], nat: Dict[str, Any], skip: Sequence[str]
            ) -> List[str]:
    from bridge import canonical
    return canonical.diff(ref, nat, skip=skip, limit=20)


def zone_bound(rm) -> Dict[str, int]:
    """The zone mobjs upstream's zone could still hold at an R dump
    (docs/LEVELS.md 3.1): its free, cache and level-special blocks' bytes
    over 136 (a mobj's block is 144 bytes: a conservative divisor)."""
    from bridge import upstream
    reader = upstream.Reader(rm)
    reader.walk_zone()
    z = reader.s.zone
    free = cache = levspec = 0
    for a, size, tag, user in reader.blocks:
        if user == 0:
            free += size
        elif tag == z.cache:
            cache += size
        elif tag == z.levspec:
            levspec += size
    return {'free': free, 'cache': cache, 'levspec': levspec,
            'bound': (free + cache + levspec) // 136}


# ---------------------------------------------------------------------------
# Acceptance 1
# ---------------------------------------------------------------------------

def groups(names: Optional[Sequence[str]] = None) -> List[List[Path]]:
    """The setups by capture run, in each run's order (a reload after its
    map's first load)."""
    out: Dict[str, List[Tuple[int, Path]]] = {}
    for d in setupcap.setup_dirs():
        meta = json.loads((d / 'setup.json').read_text())
        if names and d.name not in names and meta['run'] not in names:
            continue
        out.setdefault(meta['run'], []).append((meta['setup']['index'], d))
    return [[d for _, d in sorted(v)] for k, v in sorted(out.items())]


# the static level kinds (docs/LEVELS.md 2.1 "One path"): a reload's
# against its map's first load (the dynamic fields differ by construction:
# prndindex, validcount, the line stamps, the reborn player, the things)
STATIC_KINDS = ('seg', 'node', 'subsector', 'side', 'blockmap', 'reject',
                'linebuf')
STATIC_FIELDS = {
    'line': ('v1', 'v2', 'dx', 'dy', 'sidenum', 'bbox', 'tag', 'flags',
             'slopetype', 'special'),
    'sector': ('floorheight', 'ceilingheight', 'floorpic', 'ceilingpic',
               'lightlevel', 'soundorg', 'lines', 'linecount', 'oldspecial',
               'tag', 'flood', 'flood_sb')}


def static_part(state: Dict[str, Any]) -> Dict[str, Any]:
    o = state['objects']
    out = {k: o.get(k, {}) for k in STATIC_KINDS}
    for k, fields in STATIC_FIELDS.items():
        out[k] = {i: {f: x[f] for f in fields} for i, x in
                  o.get(k, {}).items()}
    return out


def thing_records(metas: Sequence[Dict[str, Any]], meta: Dict[str, Any]
                  ) -> List[Tuple[int, int, int, bytes]]:
    """A synthetic setup's moved map things (setupcap.py's run secorder:
    "things", each [index, x, y]) as image records over the store's THINGS
    block of its map, so the native run spawns from the same things as
    ref816's; a map of the run with moves must not be set up unmoved in
    the same run (one store an image)."""
    out = []
    moved: Dict[int, Any] = {}
    for m in metas:
        moved.setdefault(m['gamemap'], set()).add(
            json.dumps(m.get('things', [])))
    for gamemap, kinds in sorted(moved.items()):
        if len(kinds) != 1:
            raise SetupError('E1M%d is set up with and without moved things '
                             'in one run' % gamemap)
        things = json.loads(next(iter(kinds)))
        if not things:
            continue
        block = meta['maps']['E1M%d' % gamemap]['blocks']['THINGS']
        if block['codec']:
            raise SetupError('a THINGS block with a codec')
        for index, x, y in things:
            at = LL.MTHING_SIZE * index
            if at + LL.MTHING_SIZE > block['length']:
                raise SetupError('map thing %d past the block' % index)
            out.append((1, block['bank'], block['address'] + at +
                        LL.MTHING['X'], struct.pack('<h', x)))
            out.append((1, block['bank'], block['address'] + at +
                        LL.MTHING['Y'], struct.pack('<h', y)))
    return out


def check_setups(fills=(0xA5, 0x5A), names: Optional[Sequence[str]] = None,
                 obj: Optional[Path] = None, build: str = 'ltest',
                 keep: Optional[Path] = None) -> Dict[str, Any]:
    from bridge import upstream
    from native import lrun
    from native import render_check as RC
    b = lrun.load_build(obj or lrun.OBJ, build)
    meta = store_meta()
    sch = _schema()
    skip = skips(sch)
    report: Dict[str, Any] = {'format': 'level-check-c 1', 'skips': skip,
                              'setups': {}, 'runs': [], 'failures': []}
    refs: Dict[str, Any] = {}
    for group in groups(names):
        statics: Dict[Tuple[int, int], Any] = {}
        metas = [json.loads((d / 'setup.json').read_text()) for d in group]
        maps = [m['gamemap'] for m in metas]
        headers = [header_of(meta, m) for m in maps]
        for d in group:
            if d.name not in refs:
                rm = LC.load_memory(d / 'r.ram.z')
                refs[d.name] = (upstream.Reader(rm).read(), rm)
        for fill in fills:
            work = Path(tempfile.mkdtemp(prefix='tmp-m9-setup-',
                                         dir=str(ROOT / 'build')))
            res: Dict[str, Any] = {'fill': '%02X' % fill,
                                   'setups': [d.name for d in group],
                                   'problems': []}
            try:
                pres = [prestate(manifest_of(m, meta), d, refs[d.name][0],
                                 refs[d.name][1], fill, sch)
                        for m, d in zip(maps, group)]
                r = lrun.run(b, maps, fill, work, pre=list(range(len(maps))),
                             prestates=pres, setup=True,
                             extra_records=thing_records(metas, meta))
                res['end'] = r.ended()
                res['cycles'] = r.state.get('cycles')
                if r.ended() != 'halt':
                    res['problems'].append('the run ended: %s (stop %s)' % (
                        r.ended(), lrun.status_of(r)))
                shots = lrun.load_snapshots(work)
                if len(shots) != len(group):
                    res['problems'].append('%d setups, %d snapshots' % (
                        len(group), len(shots)))
                for k, (d, m, p) in enumerate(zip(group, maps, shots)):
                    one = report['setups'].setdefault(d.name, {
                        'gamemap': m, 'gameskill': metas[k]['gameskill'],
                        'kind': metas[k]['kind'], 'fills': {}})
                    try:
                        mach = lrun.SnapMachine.from_image(p)
                        if keep is not None and fill == fills[0] and \
                                metas[k]['run'] == KEEP_RUN:
                            keep.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(str(p), str(keep / (d.name +
                                                                '.img')))
                        nat = native_state(mach, manifest_of(m, meta))
                        diff = compare(refs[d.name][0], nat, skip)
                        if diff:
                            raise SetupError('%d differences: %s' % (
                                len(diff), '; '.join(diff[:6])))
                        sd = lstore.STORE / ('e1m%d' % m)
                        window = lstore.compare_window(mach, sd)
                        one['fills']['%02X' % fill] = {
                            'ok': True, 'window_bytes': window,
                            'objects': {kk: len(v) for kk, v in
                                        nat['objects'].items()}}
                        if metas[k]['kind'] == 'reload':
                            first = statics.get((m, fill))
                            if first is None:
                                raise SetupError('a reload with no first '
                                                 'load of its map before')
                            if static_part(nat) != first:
                                raise SetupError('the reload\'s static '
                                                 'level kinds differ from '
                                                 'the first load\'s')
                            one['fills']['%02X' % fill]['static_as_first'] \
                                = True
                        else:
                            statics[(m, fill)] = static_part(nat)
                    except (SetupError, lstore.StoreError, lrun.RunError,
                            KeyError, ValueError) as error:
                        one['fills']['%02X' % fill] = {'ok': False,
                                                       'error': str(error)}
                        res['problems'].append('%s: %s' % (d.name, error))
                    print('%02X %s E1M%d: %s' % (
                        fill, d.name, m, 'ok' if one['fills'][
                            '%02X' % fill]['ok'] else 'FAILED: ' +
                        one['fills']['%02X' % fill]['error'][:300]),
                        flush=True)
                writes = RC.read_writes(work / 'writes.log')
                strays = lrun.stray_by_load(writes, b, headers,
                                            setup=True)
                res['cpu_writes'] = len(writes)
                if strays:
                    res['problems'].append('%d stray CPU writes: %s' % (
                        len(strays), '; '.join(strays[:4])))
                low = None
                for rr in r.state.get('lowest_s', {}).get('ranges', []):
                    if rr.get('s') is not None:
                        low = rr['s'] if low is None else min(low, rr['s'])
                res['stack_bytes'] = None if low is None else \
                    lrun.DRV_STACK - low
                if low is None or res['stack_bytes'] + R.IRQ_STACK > \
                        LL.GAME_STACK:
                    res['problems'].append('the stack: %s B + %d for the '
                                           'IRQ over %d' % (
                                               res['stack_bytes'],
                                               R.IRQ_STACK, LL.GAME_STACK))
            except (SetupError, lrun.RunError) as error:
                res['problems'].append(str(error))
            finally:
                shutil.rmtree(str(work), ignore_errors=True)
            report['runs'].append(res)
            for p_ in res['problems']:
                report['failures'].append('%02X: %s' % (fill, p_))
            print('%02X %s: %d setups, %d problems, %s CPU writes, stack %s '
                  'B' % (fill, metas[0]['run'], len(group),
                         len(res['problems']), res.get('cpu_writes'),
                         res.get('stack_bytes')), flush=True)
    # each map's zone-mobj bound at its R dumps (docs/LEVELS.md 3.1)
    report['zone'] = {}
    for name, (state, rm) in sorted(refs.items()):
        zb = zone_bound(rm)
        pool = state['globals']['p_setup65.s:_g_thingPoolSize']
        zb.update(pool=pool, room=LL.MOBJ_CAP - pool,
                  ok=zb['bound'] <= LL.MOBJ_CAP - pool)
        report['zone'][name] = zb
        if not zb['ok']:
            report['failures'].append('%s: the zone could hold %d mobjs, '
                                      'the native room is %d' % (
                                          name, zb['bound'],
                                          LL.MOBJ_CAP - pool))
    return report


# ---------------------------------------------------------------------------
# Acceptance 3: the flood depths (docs/LEVELS.md 5.5)
# ---------------------------------------------------------------------------

def flood_depth(flood: Sequence[Sequence[int]],
                flood_sb: Sequence[Sequence[int]], start: int) -> int:
    """The deepest call of P_RecursiveSound from sector `start` with every
    two-sided line open (p_pspr65.s recursiveSound: a sector entered again
    only with fewer sound blocks; its lines without ML_SOUNDBLOCK with its
    blocks v, then, when v is 0, those with it with v = 1), each list in
    its order: the depth of the native work stack."""
    n = len(flood)
    valid = [False] * n
    trav = [0] * n
    deepest = 0
    # an explicit stack of frames: (sector, v, part, position)
    stack: List[List[int]] = []

    def enter(s: int, v: int) -> bool:
        if valid[s] and trav[s] <= v + 1:
            return False
        valid[s] = True
        trav[s] = v + 1
        stack.append([s, v, 0, 0])
        return True
    enter(start, 0)
    deepest = 1
    while stack:
        f = stack[-1]
        s, v, part, pos = f
        lst = flood[s] if part == 0 else flood_sb[s]
        if pos < len(lst):
            f[3] += 1
            other = lst[pos]
            if enter(other, v if part == 0 else 1):
                deepest = max(deepest, len(stack))
            continue
        if part == 0 and v == 0:
            f[1], f[2], f[3] = 1, 1, 0      # the ML_SOUNDBLOCK part, v = 1
            continue
        stack.pop()
    return deepest


def check_flood(keep: Path) -> Dict[str, Any]:
    """Each map's worst flood depth and its bound (2 x its sectors) against
    the native work stack, from the flood lists of its tour-sk2 setup's
    machine (the kept images of --setup)."""
    from native import lrun
    report: Dict[str, Any] = {'format': 'level-flood 1', 'stack':
                              FLOOD_STACK, 'maps': {}, 'failures': []}
    meta = store_meta()
    for d in setupcap.setup_dirs([KEEP_RUN]):
        m = json.loads((d / 'setup.json').read_text())['gamemap']
        path = keep / (d.name + '.img')
        if not path.exists():
            report['failures'].append('%s is missing: run level_check.py '
                                      '--setup' % path)
            continue
        state = native_state(lrun.SnapMachine.from_image(path),
                             manifest_of(m, meta))
        secs = state['objects']['sector']
        n = len(secs)
        fl = [[r.id for r in secs[s]['flood']] for s in range(n)]
        fsb = [[r.id for r in secs[s]['flood_sb']] for s in range(n)]
        depths = [flood_depth(fl, fsb, s) for s in range(n)]
        worst = max(depths)
        row = {'sectors': n, 'depth': worst, 'start': depths.index(worst),
               'bound': 2 * n, 'stack': FLOOD_STACK,
               'entries': sum(len(x) + len(y) for x, y in zip(fl, fsb))}
        row['ok'] = worst <= FLOOD_STACK and row['bound'] <= FLOOD_STACK
        report['maps']['E1M%d' % m] = row
        if not row['ok']:
            report['failures'].append('E1M%d: depth %d, bound %d, stack %d'
                                      % (m, worst, row['bound'],
                                         FLOOD_STACK))
    return report


# ---------------------------------------------------------------------------
# Timing (docs/LEVELS.md 5.6)
# ---------------------------------------------------------------------------

def setup_timing(maps: Sequence[int] = tuple(range(1, 10)),
                 profiles=('f121', 'fastpath')) -> Dict[str, Any]:
    """Each map's tour-sk2 setup alone (its pre-state, nl_setup) in the
    profiling build lprof under each profile: the cost phases in ms (the
    model's: a2vm's, not the card's)."""
    from a2vm import costs
    from bridge import upstream
    from native import lrun
    b = lrun.load_build(lrun.OBJ, 'lprof')
    meta = store_meta()
    sch = _schema()
    dirs = {json.loads((d / 'setup.json').read_text())['gamemap']: d
            for d in setupcap.setup_dirs([KEEP_RUN])}
    out: Dict[str, Any] = {'format': 'level-setup-timing 1', 'maps': {}}
    for m in maps:
        d = dirs[m]
        rm = LC.load_memory(d / 'r.ram.z')
        ref = upstream.Reader(rm).read()
        pre = prestate(manifest_of(m, meta), d, ref, rm, 0xA5, sch)
        row = {}
        for profile in profiles:
            work = Path(tempfile.mkdtemp(prefix='tmp-m9-stime-',
                                         dir=str(ROOT / 'build')))
            try:
                r = lrun.run(b, [m], 0xA5, work, snapshots=False,
                             write_log=False, profile=profile, pre=[0],
                             prestates=[pre], setup=True)
                if r.ended() != 'halt':
                    raise SetupError('E1M%d: %s' % (m, r.ended()))
                text = (work / 'cost.json').read_text()
                cost = json.loads(text[text.rfind('{"final"'):])['cost']
                mhz = costs.parameters(profile)['fabric_mhz']
                ph = {lrun.PHASES.get(k, str(k)):
                      round(v / (mhz * 1000.0), 3)
                      for k, v in enumerate(cost['phases']) if v}
                ph['total'] = round(sum(v for k, v in ph.items()
                                        if k not in ('image', 'driver')), 3)
                row[profile] = ph
            finally:
                shutil.rmtree(str(work), ignore_errors=True)
        out['maps']['E1M%d' % m] = row
        print('E1M%d: %s' % (m, '; '.join('%s %.1f ms (%s)' % (
            p, row[p]['total'], ', '.join('%s %.1f' % (k, v) for k, v in
                                          row[p].items() if k != 'total'))
            for p in profiles)), flush=True)
    return out


# ---------------------------------------------------------------------------
# The validcount wrap fix (docs/LEVELS.md 3.4)
# ---------------------------------------------------------------------------

WRAP_SETUP, PLAIN_SETUP = 'wrap-01', 'newgame-01'


def wrapped(ref: Dict[str, Any], v0_plain: int, v0_wrap: int
            ) -> Dict[str, Any]:
    """The release build's expected state from the wrap capture's E (its
    validcount v0_wrap, near $FFFF): the plain setup's (E validcount
    v0_plain), its walks the same, the stamps renumbered: walk i (1 up)
    stamps v0_plain + i in the plain setup; from v0_wrap the walk W =
    65,536 - v0_wrap wraps, clears every stamp and counts again from 1,
    so walk i stamps 0 before W (cleared) and i - W + 1 from it."""
    import copy
    w = 0x10000 - v0_wrap
    out = copy.deepcopy(ref)

    def stamp(s: int) -> int:
        if s == 0:
            return 0
        i = (s - v0_plain) & 0xFFFF
        return i - w + 1 if i >= w else 0
    for ln in out['objects']['line'].values():
        ln['validcount'] = stamp(ln['validcount'])
    for sec in out['objects']['sector'].values():
        sec['validcount'] = stamp(sec['validcount'])
    out['globals']['p_map65.s:validcount'] = stamp(
        ref['globals']['p_map65.s:validcount'])
    return out


def check_wrap_fix(obj: Optional[Path] = None, fill: int = 0xA5
                   ) -> Dict[str, Any]:
    """The release build (lfix) from the wrap capture's E: the plain
    setup's canonical state with its stamps renumbered (wrapped); the
    lockstep build (ltest) from the same E: the wrap capture's own (the
    acceptance's --setup checks it too)."""
    from bridge import upstream
    from native import lrun
    meta = store_meta()
    sch = _schema()
    dirs = {d.name: d for d in setupcap.setup_dirs()}
    if WRAP_SETUP not in dirs or PLAIN_SETUP not in dirs:
        raise SetupError('no %s or %s: run setupcap.py --runs wrap,newgame'
                         % (WRAP_SETUP, PLAIN_SETUP))
    dw, dp = dirs[WRAP_SETUP], dirs[PLAIN_SETUP]
    rw_mem = LC.load_memory(dw / 'r.ram.z')
    ref_w = upstream.Reader(rw_mem).read()
    ref_p = upstream.Reader(LC.load_memory(dp / 'r.ram.z')).read()
    vc = sch.symbols.address('p_map65.s:validcount')
    v0w = e_memory(dw).u16(vc)
    v0p = e_memory(dp).u16(vc)
    m = json.loads((dw / 'setup.json').read_text())['gamemap']
    pre = prestate(manifest_of(m, meta), dw, ref_w, rw_mem, fill, sch)
    out: Dict[str, Any] = {'v0_wrap': v0w, 'v0_plain': v0p, 'builds': {}}
    skip = skips(sch)
    for build, want in (('lfix', wrapped(ref_p, v0p, v0w)),
                        ('ltest', ref_w)):
        b = lrun.load_build(obj or lrun.OBJ, build)
        work = Path(tempfile.mkdtemp(prefix='tmp-m9-wrap-',
                                     dir=str(ROOT / 'build')))
        try:
            r = lrun.run(b, [m], fill, work, pre=[0], prestates=[pre],
                         setup=True, write_log=False)
            if r.ended() != 'halt':
                raise SetupError('%s: %s' % (build, r.ended()))
            shots = lrun.load_snapshots(work)
            nat = native_state(lrun.SnapMachine.from_image(shots[0]),
                               manifest_of(m, meta))
            out['builds'][build] = {
                'validcount': nat['globals']['p_map65.s:validcount'],
                'diff': compare(want, nat, skip)}
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    out['ok'] = all(not x['diff'] for x in out['builds'].values())
    return out


# ---------------------------------------------------------------------------
# The report (docs/LEVELS.md 5.6)
# ---------------------------------------------------------------------------

# 1.6's table as stage C leaves it: (row, NATIVE.md 4.4's banks, banks
# here, what they are)
BANK_ROWS = (
    ('Code library', '3-5', 5, 'CODE 112-115, LCODE 98'),
    ('Level window, current map', '22-24', 7,
     'LVSEG, LVMAP, LVG0-2, LVC, SPRT\'s map part'),
    ('Level store, all maps', 'about 28', 14 + 31 + 17 + 1,
     'STORE0-13, the texel store (31), the patch store (17), WPRO'),
    ('Zone', '4', 1 + len(LL.MOBJ) + 2,
     'RTH, MOBJA-C (69-71), ZONE0, ZONE1'),
    ('Big tables', 'about 6', 10, 'FSTEP0.., MT_*, LOGTAB, GTAB'),
    ('Per-map sight and move tables', '3-4', 1, 'LVS'),
    ('WAD directory, resident lumps, 2D caches', '4-5', 6, '105-110'),
    ('Records (pair build)', '1', 6, 'RECSP, RECW, RENDB'),
    ('Songs and effects', '5', 5, '100-104'),
)


def _ms(x: Optional[float]) -> str:
    return '' if x is None else '%.1f' % x


def write_report(path: Path) -> None:
    """build/native/levels/report.md from the reports of --setup, --flood,
    --setup-timing, --load-timing and ldisk.py --check, and the sizes of
    the ltest and lcard builds."""
    from native import lrun
    def load(name: str) -> Any:
        p = LEVELS / name
        return json.loads(p.read_text()) if p.exists() else None
    c, fl, tc, tb = (load('check-c.json'), load('flood.json'),
                     load('timing-c.json'), load('timing-b.json'))
    disk = load('ldisk.json')
    out = ['# Milestone 9: the level load and P_SetupLevel, measured', '',
           'Written by `python3 tools/native/level_check.py --report-md` '
           'from the reports in `build/native/levels`. a2vm\'s model '
           'times, not the card\'s (milestone 12).', '']
    out += ['## Acceptance 1: the setups against ref816', '']
    if c is None:
        out.append('No `check-c.json`: run `level_check.py --setup`.')
    else:
        ok = sum(1 for x in c['setups'].values()
                 if all(f['ok'] for f in x['fills'].values()))
        stacks = [r.get('stack_bytes') for r in c['runs']
                  if r.get('stack_bytes') is not None]
        out.append('%d of %d setups equal (canonical state, both fills, '
                   'skips: %s); %d runs, %d failures; stack %s B below the '
                   'driver (+%d for the IRQ, of %d).' % (
                       ok, len(c['setups']), ', '.join(c['skips']),
                       len(c['runs']), len(c['failures']),
                       '-'.join(str(x) for x in (min(stacks), max(stacks)))
                       if stacks else '?', R.IRQ_STACK, LL.GAME_STACK))
        if c.get('zone'):
            least = min(c['zone'].items(),
                        key=lambda kv: kv[1]['room'] - kv[1]['bound'])
            out.append('')
            out.append('The zone: every setup\'s mobj bound within the '
                       'native room; the least margin %d (%s: bound %d, '
                       'room %d).' % (least[1]['room'] - least[1]['bound'],
                                      least[0], least[1]['bound'],
                                      least[1]['room']))
        if c.get('wrap'):
            w = c['wrap']
            out.append('')
            out.append('The validcount wrap (3.4): from validcount $%04X, '
                       'lfix equal to the plain setup renumbered '
                       '(validcount %s), ltest equal to the wrap capture: '
                       '%s.' % (w['v0_wrap'], w['builds']['lfix']
                                ['validcount'], 'ok' if w['ok'] else
                                'FAILED'))
    out += ['', '## Acceptance 3: the flood depths', '']
    if fl is None:
        out.append('No `flood.json`: run `level_check.py --flood`.')
    else:
        out += ['| Map | Sectors | Worst depth | Bound | Stack |',
                '| --- | ---: | ---: | ---: | ---: |']
        for m, r in sorted(fl['maps'].items()):
            out.append('| %s | %d | %d | %d | %d |' % (
                m, r['sectors'], r['depth'], r['bound'], r['stack']))
    out += ['', '## Load and setup time per map (ms)', '']
    if tc is None:
        out.append('No `timing-c.json`: run `level_check.py '
                   '--setup-timing`.')
    else:
        steps = ('variants', 'copies', 'lines', 'group', 'flood', 'cmaps',
                 'private', 'spawn', 'specials', 'setup')
        for prof in ('f121', 'fastpath'):
            out += ['', '`%s`:' % prof, '',
                    '| Map | ' + ' | '.join(steps) + ' | total |',
                    '| --- |' + ' ---: |' * (len(steps) + 1)]
            for m, row in sorted(tc['maps'].items()):
                ph = row[prof]
                out.append('| %s | %s | %s |' % (
                    m, ' | '.join(_ms(ph.get(k)) for k in steps),
                    _ms(ph.get('total'))))
        if tb:
            out += ['', 'Stage B\'s load alone (`timing-b.json`), f121 / '
                    'fastpath: ' + ', '.join(
                        '%s %.1f / %.1f' % (m, r['f121']['load'],
                                            r['fastpath']['load'])
                        for m, r in sorted(tb['maps'].items())) + '.']
    out += ['', '## The boot disk', '']
    if disk is None:
        out.append('No `ldisk.json`: run `ldisk.py --check`.')
    else:
        for r in disk:
            vb = [x['vbls'] for x in r['loads']]
            out.append('`%s`: boot %.1f ms; %d setups, VBLs %d-%d; '
                       'problems %d; CRCs OK %d of %d.' % (
                           r['profile'], r['boot_ms'], len(r['loads']),
                           min(vb), max(vb), len(r['problems']),
                           sum(1 for x in r['loads']
                               if x.get('crc_ok') == 3), len(r['loads'])))
    out += ['', '## Sizes (4.4)', '']
    for build in ('ltest', 'lcard'):
        try:
            b = lrun.load_build(lrun.OBJ, build)
        except Exception as error:      # (no build)
            out.append('%s: %s' % (build, error))
            continue
        out += ['`%s`:' % build, '', '    ' + '\n    '.join(
            lrun.sizes(b)), '']
    out += ['## Banks against NATIVE.md 4.4', '',
            '| Row | NATIVE.md 4.4 | Here | Banks |',
            '| --- | ---: | ---: | --- |']
    total = 0
    for row, there, here, what in BANK_ROWS:
        total += here
        out.append('| %s | %s | %d | %s |' % (row, there, here, what))
    out.append('| **Total** | **76-82** | **%d** | |' % total)
    assert total == LL.BANKS_TOTAL - len(LL.SPARE), total
    spare = ', '.join(str(x) for x in LL.SPARE)
    out += ['', 'Used %d of %d; spare %d: %s (stage A had 112 used: the '
            'mobjs\' game part takes 3 banks, not 6).' % (
                LL.BANKS_TOTAL - len(LL.SPARE), LL.BANKS_TOTAL,
                len(LL.SPARE), spare), '']
    path.write_text('\n'.join(out) + '\n')
