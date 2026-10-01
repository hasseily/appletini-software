#!/usr/bin/env python3
"""The checks of milestone 9 (docs/LEVELS.md 5.3, 6.1): stage A's
converter (wadconv.py, from DOOM1.WAD and the release) against
levelconv.py's conversion of ref816's states.

Usage:  python3 tools/native/level_check.py --conv [--maps 1-9]
        python3 tools/native/level_check.py --derive [--maps 1-9]

--conv, for every end-of-load dump (W) of tools/native/setupcap.py and
every level source of tools/native/rendercap.py:

  1. level.img byte for byte, all banks, but one named range: the rotate
     and flipmask bytes of a sprite frame both sides flag as not a frame
     (SPRFR_BAD: upstream's bytes after the sprite's frames);
  2. level.json equal but the provenance fields (source, key, sources,
     checks, sector_base, the weapons' count of reference checks);
  3. texmap.json, patchmap.json, mtables.img, fuzzdark.bin byte for byte;
     wtables.img byte for byte but two named parts that hold upstream's
     history: TXHT (levelconv's entry 0 or equal; equal for every texture
     the map's load loads) and FLATCM past the map's flats (GSFLATn's
     count; the converter's 0);
  4. every slot's 128 bytes and every stored lump's tail (implied by 1,
     counted);
  5. umodel.py's window against the dump: the image banks to W_COLSTART,
     the column memory (COLDIR, the tables, every byte to colmem, the
     rest of colmem's bank) and the zeroed bank after it; the game form
     of each map lump against the release's (umodel.load: the lump image
     equals the store's decoded units);
  6. a level source (taken in play): the static parts: as 1-4 but the
     sector records and the sides' textures and offsets (play changes
     them), a difference in a slot or tail inplay.json lists as
     changeable reported by name; the synthetic sources (synth-*, levels
     made with pokes) by name, not compared, and so the synthetic setups
     (setup.json "synthetic": secorder, whose map things are moved).

The W dumps of tour-sk2 are converted by levelconv.py into
build/native/levels/ref/SETUP/ (its files) for stage B's read-back.
Report: build/native/levels/check-a.json.

--derive: lderive.py's static derivations (the lines' fields, the
subsectors' sectors, the line tables, the sound origins, the flood lists)
against the canonical state of every R dump (tools/bridge).

--load (stage B, docs/LEVELS.md 6.2, checkpoint B): the 65C02 loader
(src/native/level.mk's build ltest) on a2vm (tools/native/lrun.py's image
runs), from both poisoned machines ($A5, $5A), the nine maps in a row,
in reverse and one map twice (20 loads a run): after every load the
machine equals the map's window.img outside its mask.img (the static
and derived parts, the colormaps in main, FUZZDARK in aux 0, the W and
masked tables in the code banks, the shared stores after the variants);
read back into harness form through the game layout's texmap.json and
patchmap.json it equals levelconv.py's level of the map's tour-sk2 W dump
(lstore.readback: every slot, stored lump and tail, PHDR, SPRFR, TXMP,
the TX tables); the static fields of the manifest native-level-1 equal
the canonical state of the map's tour-sk2 R dump; the whole level read
back into the harness layout (lrun.harness_level) equals wadconv.py's
harness level of the map byte for byte (level.img but the rotate and
flipmask bytes of the frames both flag as not frames, wtables.img,
mtables.img, fuzzdark.bin), which stage A showed equal to levelconv.py's
but three named parts of upstream's history; the write log holds no CPU
write outside the load's allowed set (llayout.allowed_writes_load) or the
driver's; the stack within the load's budget. A second run of the same
loads ends with a whole-machine snapshot: no byte of main, the card or
any RamWorks bank changed but those the loads may leave (each loaded
map's window.img, the load's scratch, the driver's): the memory API's
copies, which the write log cannot see, are checked so. The write log is
cut at each drv_loaded, so each load's CPU writes are checked against its
own map's places, and each map is loaded alone once more with a
whole-machine snapshot, every byte it changed within that map's own
places (the sequence's whole-machine check allows the union of its
maps'). The last load of
each map is kept (build/native/levels/loaded/e1mN.img) for frame8.py
--levels loaded (acceptance 2). Report: build/native/levels/check-b.json.
--load-timing: the profiling build lprof, each map loaded alone under
f121 and fastpath: the time of each cost phase.

--setup (stage C, docs/LEVELS.md 6.3, acceptance 1): setupcheck.py's
check of the native P_SetupLevel (nl_setup, the build ltest) on every
setup capture, from both poisoned machines: the canonical state equal to
ref816's R dump's but the caches, the window outside stage C's mask
equal to window.img, each reload's static level kinds equal to its map's
first load's, no stray write, the stack within the budget, each R dump's
zone-mobj bound within the native room. Report: check-c.json.
--flood (acceptance 3): each map's flood depths (setupcheck.flood) from
the flood lists of its natively set-up window. --setup-timing: lprof,
each map's tour-sk2 setup alone under f121 and fastpath (timing-c.json).
--report: build/native/levels/report.md from the reports (5.6).

--store: the game layout (lstore.py's files, wadconv.py --store) loaded on
the host (lstore.HostMachine: the bank files, then each map's load
program, its variants and the static steps), the nine maps in a row, in
reverse, and one map twice: after every load the machine equals the
map's window.img outside its mask.img; read back into harness form
through the map's game texmap.json and patchmap.json it equals
levelconv.py's level of the map's tour-sk2 W dump (every slot, every
stored lump and tail, PHDR, SPRFR, TXMP, the TX tables); and the static
fields the manifest native-level-1 (llayout.manifest_static) names, read
by the bridge's port reader, equal the canonical state of the map's
tour-sk2 R dump.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import levelconv as LC, rlayout as R, umodel as U, \
    wadconv as WC  # noqa: E402
from native import setupcap  # noqa: E402

ROOT = HERE.parent.parent
LEVELS = ROOT / 'build' / 'native' / 'levels'
REF = LEVELS / 'ref'
REPORT = LEVELS / 'check-a.json'
PROVENANCE = ('source', 'key', 'sources', 'checks', 'sector_base')
REF_SET = 'tour-sk2'


class CheckError(Exception):
    pass


def frame_index(info: Dict[str, Any]) -> Dict[Tuple[int, int], int]:
    """(sprite, frame) -> its SPRFR record."""
    out, k = {}, 0
    for s, n in enumerate(info['sprites']['frames_per_sprite']):
        for f in range(n):
            out[(s, f)] = k
            k += 1
    return out


def json_diff(a: Any, b: Any, path: str = '') -> List[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append('%s/%s only in %s' % (path, k, 'the reference'
                                                  if k in a else 'ours'))
                continue
            out += json_diff(a[k], b[k], '%s/%s' % (path, k))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += json_diff(x, y, '%s[%d]' % (path, i))
        return out
    return [] if a == b else ['%s: %s, ours %s' % (path, str(a)[:80],
                                                    str(b)[:80])]


def plain(info: Dict[str, Any]) -> Dict[str, Any]:
    """level.json without its provenance fields (a JSON round trip)."""
    out = json.loads(json.dumps(info))
    for k in PROVENANCE:
        out.pop(k, None)
    out.get('sprites', {}).get('weapons', {}).pop('checked', None)
    out.get('sprites', {}).pop('overrun', None)
    return out


def compare(mine: LC.Level, facts: Dict[str, Any], ref: LC.Level,
            static_only: bool = False,
            changeable: Sequence[str] = ()) -> Dict[str, Any]:
    """Items 1-4 (static_only: item 6). Raises CheckError on a difference
    outside the named ranges; returns the counts and the named
    differences."""
    out: Dict[str, Any] = {'named': {}}
    named = out['named']
    # -- the named ranges of level.img
    skip: Dict[int, set] = {}

    def skip_range(bank: int, start: int, length: int) -> None:
        skip.setdefault(bank, set()).update(range(start, start + length))
    fidx = frame_index(ref.info)
    bad_ref = {tuple(x) for x in ref.info['sprites']['not_frames']}
    bad_mine = {tuple(x) for x in mine.info['sprites']['not_frames']}
    if bad_ref != bad_mine:
        raise CheckError('frames flagged as not frames: %s, ours %s'
                         % (sorted(bad_ref), sorted(bad_mine)))
    for sf in bad_ref:
        a = R.SPRFRS.address(fidx[sf])
        skip_range(R.SPRT, a + R.SPRFR['ROT'], 1)
        skip_range(R.SPRT, a + R.SPRFR['FLIP'], 1)
    named['SPRFR rotate and flipmask of frames that are not frames'] = \
        len(bad_ref)
    if static_only:
        c = ref.info['counts']
        skip_range(R.LVMAP, R.SECTORS.base, R.SEC_SIZE * c['sectors'])
        for i in range(c['sides']):
            skip_range(R.LVMAP, R.SIDES.address(i), R.SIDE['SECTOR'])
        named['sector records, sides\' textures and offsets (play '
              'changes them)'] = c['sectors'] + c['sides']
    # -- item 1
    rb, mb = ref.banks, mine.banks
    if sorted(rb.data) != sorted(mb.data):
        raise CheckError('banks %s, ours %s' % (sorted(rb.data),
                                               sorted(mb.data)))
    compared = 0
    slots_by_addr = {}
    for key, ptr in mine.texmap['slots'].items():
        slots_by_addr[key] = ptr
    changeable = set(changeable)
    changed_named = []
    for bank in sorted(rb.data):
        if rb.used[bank] != mb.used[bank]:
            at = next(i for i in range(0x10000)
                      if rb.used[bank][i] != mb.used[bank][i])
            raise CheckError('bank %d: the bytes written differ at $%04X'
                             % (bank, at))
        a, b = rb.data[bank], mb.data[bank]
        sk = skip.get(bank, set())
        if a != b:
            diffs = [i for i in range(0x10000) if a[i] != b[i]
                     and i not in sk]
            if diffs:
                where = slot_at(mine, bank, diffs[0])
                if where and where in changeable:
                    changed_named.append(where)
                else:
                    raise CheckError('bank %d differs at $%04X (%s)%s' % (
                        bank, diffs[0], where or 'no slot',
                        ', %d bytes' % len(diffs)))
        compared += sum(rb.used[bank]) - len(sk)
    out['level_img_bytes'] = compared
    if changed_named:
        named['slots inplay.json lists, changed in play'] = sorted(
            set(changed_named))
    # -- item 3, the W tables
    for addr in sorted(ref.wtables):
        a, b = ref.wtables[addr], mine.wtables[addr]
        if addr == R.TXHT:
            loaded = set(facts['loaded'])
            hist = 0
            for t in range(256):
                if a[t] == b[t]:
                    continue
                if a[t] != 0 or t in loaded:
                    raise CheckError('TXHT[%d]: %d, ours %d' % (t, a[t],
                                                                b[t]))
                hist += 1
            for t in loaded:
                if 0 <= t < 256 and a[t] == 0 and b[t] != 0:
                    raise CheckError('TXHT[%d] of a loaded texture is 0' % t)
            named['TXHT entries 0 in upstream (no load since the boot)'] = \
                hist
            continue
        if addr == R.FLATCM:
            n = facts['flats']
            hist = 0
            for cm in range(34):
                for f in range(32):
                    i = cm * 32 + f
                    if f < n:
                        if a[i] != b[i]:
                            raise CheckError('FLATCM[%d][%d]: %d, ours %d'
                                             % (cm, f, a[i], b[i]))
                    elif b[i] != 0:
                        raise CheckError('FLATCM past the flats is not 0')
                    elif a[i] != 0:
                        hist += 1
            named['FLATCM bytes past the map\'s %d flats (the map '
                  'before\'s)' % n] = hist
            continue
        if a != b:
            at = next(i for i in range(len(a)) if a[i] != b[i])
            raise CheckError('W table $%04X differs at +%d' % (addr, at))
    if ref.mtables != mine.mtables:
        raise CheckError('mtables.img differs')
    if ref.fuzzdark != mine.fuzzdark:
        raise CheckError('fuzzdark.bin differs')
    if ref.texmap != mine.texmap:
        raise CheckError('texmap.json differs: %s' % json_diff(
            ref.texmap, mine.texmap)[:3])
    if ref.patchmap != mine.patchmap:
        raise CheckError('patchmap.json differs')
    # -- item 2
    d = json_diff(plain(ref.info), plain(mine.info))
    if d:
        raise CheckError('level.json: %s' % '; '.join(d[:5]))
    # -- item 4 (counts)
    out['slots'] = len(mine.texmap['slots'])
    out['tails'] = len(mine.info['sprites']['store'])
    out['open_ended'] = len(mine.info['open_ended'])
    return out


def slot_at(level: LC.Level, bank: int, at: int) -> Optional[str]:
    """The texture slot or stored lump of a level.img byte."""
    info = level.info
    for t, e in info['textures'].items():
        if e['bank'] == bank and e['base'] <= at < \
                e['base'] + LC.SLOT * (e['widthmask'] + 1):
            return '%s:%d' % (t, (at - e['base']) // LC.SLOT)
    sky = info['sky']
    if sky['bank'] == bank and sky['base'] <= at < \
            sky['base'] + LC.SLOT * sky['columns']:
        return 'sky:%d' % ((at - sky['base']) // LC.SLOT)
    for e in info['sprites']['store']:
        if e['bank'] == bank and e['at'] <= at < \
                e['at'] + e['size'] + LC.TAIL:
            return 'lump %s%s' % (e['name'], ' (tail)' if at >= e['at'] +
                                  e['size'] else '')
    return None


def reference(memory, sym, name: str) -> LC.Level:
    """levelconv.py's conversion with its own checks (run_one's)."""
    level = LC.convert(memory, sym, name)
    up = LC.Upstream(memory, sym)
    n = LC.check_decode(level, up.state)
    level.info['checks'].append('decode equals upstream on %d objects' % n)
    slots = LC.check_slots(level, memory)
    level.info['checks'].append('%d slots equal the reference' % slots)
    lumps = LC.check_store(level, memory)
    level.info['checks'].append('%d stored lumps and their tails equal the '
                                'reference' % lumps)
    fields = LC.check_bridge(level, up.state)
    level.info['checks'].append('the bridge reads %d render fields back'
                                % fields)
    return level


def check_conv(maps: Sequence[int], write_ref: bool = True) -> Dict:
    gd = U.game_data()
    sym = LC.symbols()
    loads: Dict[int, Tuple[U.Load, LC.Level, Dict, Dict]] = {}

    def ours(gamemap: int):
        if gamemap not in loads:
            ld = U.load(gd, gamemap)
            level, facts = WC.convert(gd, ld)
            inplay = WC.in_play(gd, ld, level)
            loads[gamemap] = (ld, level, facts, inplay)
        return loads[gamemap]
    report: Dict[str, Any] = {'format': 'level-check-a 1', 'w': {},
                              'sources': {}, 'maps': {}, 'failures': []}
    start = time.time()
    for d in setupcap.setup_dirs():
        if not (d / 'w.ram.z').exists():
            continue
        meta = json.loads((d / 'setup.json').read_text())
        gamemap = meta['gamemap']
        if gamemap not in maps:
            continue
        if meta.get('synthetic'):
            report['w'][d.name] = {'ok': None, 'gamemap': gamemap,
                                   'skill': meta['gameskill'],
                                   'note': 'synthetic (map things moved '
                                   'with pokes): not compared'}
            continue
        try:
            ld, mine, facts, inplay = ours(gamemap)
            memory = LC.load_memory(d / 'w.ram.z')
            ref = reference(memory, sym, d.name)
            res = compare(mine, facts, ref)
            res['window'] = U.compare_window(ld, memory.read)
            if write_ref and meta['run'] == REF_SET:
                LC.write(ref, REF / d.name)
            res['ok'] = True
        except (CheckError, U.ModelError, LC.ConvError, WC.ConvError) \
                as error:
            res = {'ok': False, 'error': str(error)}
            report['failures'].append('%s: %s' % (d.name, error))
        report['w'][d.name] = dict(res, gamemap=gamemap,
                                   skill=meta['gameskill'])
        print('%s E1M%d: %s' % (d.name, gamemap, 'ok' if res['ok'] else
                                'FAILED: ' + res['error']), flush=True)
    for src in sorted(LC.SOURCES.glob('*.ram.z')):
        name = src.name[:-len('.ram.z')]
        if name.startswith('synth-'):
            report['sources'][name] = {'ok': None, 'note': 'synthetic (a '
                                       'level made with pokes): not '
                                       'compared'}
            continue
        memory = LC.load_memory(src)
        gamemap = memory.u16(LC.symbols().address('_g_gamemap'))
        if gamemap not in maps:
            continue
        try:
            ld, mine, facts, inplay = ours(gamemap)
            ref = reference(memory, sym, src.name)
            res = compare(mine, facts, ref, static_only=True,
                          changeable=inplay['changeable_slots'])
            res['ok'] = True
        except (CheckError, U.ModelError, LC.ConvError, WC.ConvError) \
                as error:
            res = {'ok': False, 'error': str(error)}
            report['failures'].append('%s: %s' % (name, error))
        report['sources'][name] = dict(res, gamemap=gamemap)
        print('%s E1M%d: %s' % (name, gamemap, 'ok' if res['ok'] else
                                'FAILED: ' + res['error']), flush=True)
    for gamemap, (ld, level, facts, inplay) in sorted(loads.items()):
        report['maps']['E1M%d' % gamemap] = {
            'made_load': len(ld.made_load), 'made_more': len(ld.made_more),
            'colmem': '$%06X' % ld.columns.colmem,
            'holes': len(ld.columns.holes),
            'slots': len(level.texmap['slots']),
            'tails': len(level.info['sprites']['store']),
            'inplay': [t['name'] for t in inplay['textures']],
            'changeable_slots': len(inplay['changeable_slots']),
            'changeable_tails': len(inplay['changeable_tails']),
            'slots_reaching_free': len(inplay['slots_reaching_free']),
            'tails_reaching_free': len(inplay['tails_reaching_free'])}
    report['seconds'] = round(time.time() - start, 1)
    return report


SEQUENCE = tuple(range(1, 10)) + tuple(range(9, 0, -1)) + (5, 5)


def manifest_check(hm, state: Dict[str, Any]) -> int:
    """The static fields through the bridge's port reader and
    llayout.manifest_static, against a canonical state: the fields
    compared."""
    from bridge.layout import Manifest
    from bridge.memory import MAIN, PortMemory
    from bridge.port import PortReader
    from native import llayout as LL
    pm = PortMemory()
    pm.write(MAIN | 0x0300, bytes(hm.main[0x0300:0x0400]))
    for bank in (R.LVSEG, R.LVMAP, LL.LVG0, LL.LVG1):
        pm.write(bank << 16 | 0x0200, bytes(hm.aux[bank][0x0200:0xC000]))
    got = PortReader(Manifest(LL.manifest_static())).read(pm)['objects']
    want = state['objects']
    n = 0
    for kind, objs in got.items():
        if len(objs) != len(want[kind]):
            raise CheckError('%d %ss read, the reference %d' % (
                len(objs), kind, len(want[kind])))
        for i, o in objs.items():
            for k, v in o.items():
                w = want[kind][i][k]
                if isinstance(v, list):
                    if list(w) != v:
                        raise CheckError('%s %d %s: %r, the reference %r'
                                         % (kind, i, k, v, w))
                    n += len(v)
                    continue
                if w != v:
                    raise CheckError('%s %d %s: %r, the reference %r'
                                     % (kind, i, k, v, w))
                n += 1
    return n


def check_store(sequence: Sequence[int] = SEQUENCE) -> Dict[str, Any]:
    from bridge import upstream
    from native import lstore
    meta = json.loads((lstore.STORE / 'store.json').read_text())
    files = [lstore.STORE / n for n in sorted(meta['files'])]
    hm = lstore.HostMachine(files, tuple(meta['directory']))
    dumps = {}
    for d in setupcap.setup_dirs([REF_SET]):
        dumps[json.loads((d / 'setup.json').read_text())['gamemap']] = d
    states: Dict[int, Dict[str, Any]] = {}
    report: Dict[str, Any] = {'format': 'level-check-store 1',
                              'loads': [], 'failures': []}
    for m in sequence:
        d = lstore.STORE / ('e1m%d' % m)
        try:
            before = hm.requests_done
            hm.load(m)
            res = {'map': m, 'requests': hm.requests_done - before,
                   'window_bytes': lstore.compare_window(hm, d)}
            res['readback'] = lstore.readback(hm, m, d,
                                              REF / dumps[m].name)
            if m not in states:
                reader = upstream.Reader(LC.load_memory(dumps[m] /
                                                        'r.ram.z'))
                states[m] = reader.read()
            res['manifest_fields'] = manifest_check(hm, states[m])
            res['ok'] = True
        except (lstore.StoreError, CheckError, KeyError) as error:
            res = {'map': m, 'ok': False, 'error': str(error)}
            report['failures'].append('E1M%d: %s' % (m, error))
        report['loads'].append(res)
        print('E1M%d: %s' % (m, 'ok %s' % {k: v for k, v in res.items()
                                           if k not in ('ok', 'map')}
                             if res['ok'] else 'FAILED: ' + res['error']),
              flush=True)
    return report


LOADED = LEVELS / 'loaded'
CONV = LEVELS / 'conv'


def dumps_of(run: str = REF_SET) -> Dict[int, Path]:
    out = {}
    for d in setupcap.setup_dirs([run]):
        out[json.loads((d / 'setup.json').read_text())['gamemap']] = d
    return out


def window_ranges(gamemap: int) -> Tuple[Dict[int, set], set]:
    """The bytes a load of the map leaves (its window.img and mask.img):
    by aux bank (0: aux 0), and main's."""
    from native import lstore
    d = lstore.STORE / ('e1m%d' % gamemap)
    aux: Dict[int, set] = {}
    main: set = set()
    for name in ('window.img', 'mask.img'):
        for kind, bank, address, data in LC.Image.parse(
                (d / name).read_bytes()):
            r = range(address, address + len(data))
            if kind == 0:
                main.update(r)
            else:
                aux.setdefault(bank, set()).update(r)
    return aux, main


def own_places(gamemap: int, header: Dict[str, Any]
               ) -> Tuple[Dict[int, set], set]:
    """What a load of the map may leave changed in the whole machine: its
    window.img and mask.img, the load's allowed writes, the load image in
    W, the IRQ count and the cost phase (by aux bank, and main's)."""
    from native import llayout as LL
    aux, main = window_ranges(gamemap)
    for s_, bank, lo, hi, _ in LL.allowed_writes_load(header['counts'],
                                                     header['lvg1']):
        if s_ == 'main':
            main.update(range(lo, hi))
        else:
            aux.setdefault(bank, set()).update(range(lo, hi))
    main.update(range(0x6000, LL.LW_CODE_END))      # the image
    main.update(range(0xD8, 0xDA))                  # the IRQ count
    main.add(R.PHASE)
    return aux, main


def derived_check(mach, header: Dict[str, Any], state: Dict[str, Any]
                  ) -> Dict[str, int]:
    """The derived parts the load's 65C02 steps left (each subsector's
    sector, each sector's line count, line table, sound origin, tag and
    old special, its two flood sequences) read from the machine and
    compared with a canonical state of the map after its setup (the
    bridge's reading of ref816's R dump), as lderive.compare compares the
    host's: raises CheckError on a difference."""
    import struct
    from native import lderive as LD
    from native import llayout as LL
    objs = state['objects']
    c = header['counts']
    v = header['lvg1']
    out = {'subsectors': 0, 'sectors': 0, 'entries': 0, 'flood': 0}
    lvmap = mach.aux[R.LVMAP]
    lvg1 = mach.aux[LL.LVG1]
    subs = objs['subsector']
    if len(subs) != c['subsectors']:
        raise CheckError('%d subsectors, the reference %d' % (
            c['subsectors'], len(subs)))
    for i in range(c['subsectors']):
        got = lvmap[R.SUBS.address(i) + R.SUB['SECTOR']]
        if LD.ref_id(subs[i]['sector'], 'sector') != got:
            raise CheckError('subsector %d: sector %d, the reference %s'
                             % (i, got, subs[i]['sector']))
        out['subsectors'] += 1
    secs = objs['sector']
    bufs = objs.get('linebuf', {})
    if len(secs) != c['sectors'] or len(bufs) != c['linetable']:
        raise CheckError('%d sectors and %d line table entries, the '
                         'reference %d and %d' % (c['sectors'],
                                                  c['linetable'], len(secs),
                                                  len(bufs)))
    for s in range(c['sectors']):
        rec = bytes(lvg1[LL.SECGS.address(s):LL.SECGS.address(s) +
                         LL.SECG_SIZE])
        G = LL.SECG
        count, first = struct.unpack_from('<HH', rec, G['LCOUNT'])
        ref = secs[s]
        if ref['linecount'] != count:
            raise CheckError('sector %d: %d lines, the reference %d' % (
                s, count, ref['linecount']))
        lines = [struct.unpack_from('<H', lvg1, v['LTAB'] + 2 * k)[0]
                 for k in range(first, first + count)]
        if count:
            if LD.ref_id(ref['lines'], 'linebuf') != first:
                raise CheckError('sector %d: its table at %d, the '
                                 'reference\'s at %s' % (s, first,
                                                         ref['lines']))
            want = [LD.ref_id(bufs[first + k]['line'], 'line')
                    for k in range(count)]
            if lines != want:
                raise CheckError('sector %d: lines %s, the reference %s'
                                 % (s, lines[:6], want[:6]))
        org = list(struct.unpack_from('<ii', rec, G['SOUNDX']))
        if org != list(ref['soundorg']):
            raise CheckError('sector %d: sound origin %s, the reference %s'
                             % (s, org, list(ref['soundorg'])))
        tag = struct.unpack_from('<h', rec, G['TAG'])[0]
        old = struct.unpack_from('<b', rec, G['OLDSPECIAL'])[0]
        if (tag, old) != (ref['tag'], ref['oldspecial']):
            raise CheckError('sector %d: tag %d, old special %d, the '
                             'reference %d, %d' % (s, tag, old, ref['tag'],
                                                   ref['oldspecial']))
        f0, fe, fb, end = struct.unpack_from('<HHHH', lvg1, v['FLIDX'] +
                                             LL.FLIDX_SIZE * s)
        ent = lvg1[v['FLENT']:v['FLENT'] + c['flood']]
        fl, fsb = list(ent[f0:fe]), list(ent[fb:end])
        rfl = [LD.ref_id(x, 'sector') for x in ref['flood']]
        rfsb = [LD.ref_id(x, 'sector') for x in ref['flood_sb']]
        if (fl, fsb) != (rfl, rfsb):
            raise CheckError('sector %d: flood %s/%s, the reference %s/%s'
                             % (s, fl, fsb, rfl, rfsb))
        out['sectors'] += 1
        out['entries'] += count
        out['flood'] += len(fl) + len(fsb)
    return out


def check_load(fills=(0xA5, 0x5A), sequence: Sequence[int] = SEQUENCE,
               keep_loaded: bool = True, obj: Optional[Path] = None
               ) -> Dict[str, Any]:
    import shutil
    import tempfile
    from bridge import upstream
    from native import lrun, lstore
    from native import llayout as LL
    from native import render_check as RC
    b = lrun.load_build(obj or lrun.OBJ, 'ltest')
    dumps = dumps_of()
    states: Dict[int, Dict[str, Any]] = {}
    headers = {}
    meta = json.loads((lstore.STORE / 'store.json').read_text())
    for m in set(sequence):
        h = meta['maps']['E1M%d' % m]['header']
        headers[m] = {'counts': h['counts'], 'lvg1': h['lvg1']}
    report: Dict[str, Any] = {'format': 'level-check-b 1', 'runs': [],
                              'failures': [], 'sequence': list(sequence)}
    last = {m: k for k, m in enumerate(sequence)}
    for fill in fills:
        work = Path(tempfile.mkdtemp(prefix='tmp-m9-load-',
                                     dir=str(ROOT / 'build')))
        res: Dict[str, Any] = {'fill': '%02X' % fill, 'loads': [],
                               'problems': []}
        try:
            r = lrun.run(b, sequence, fill, work, snapshots=True)
            res['end'] = r.ended()
            res['cycles'] = r.state.get('cycles')
            if r.ended() != 'halt':
                res['problems'].append('the run ended: %s (stop %s)' % (
                    r.ended(), lrun.status_of(r)))
            shots = lrun.load_snapshots(work)
            if len(shots) != len(sequence):
                res['problems'].append('%d loads, %d snapshots' % (
                    len(sequence), len(shots)))
            for k, (m, p) in enumerate(zip(sequence, shots)):
                one: Dict[str, Any] = {'map': m}
                if keep_loaded and fill == fills[0] and last[m] == k:
                    LOADED.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(str(p), str(LOADED / ('e1m%d.img' % m)))
                try:
                    mach = lrun.SnapMachine.from_image(p)
                    d = lstore.STORE / ('e1m%d' % m)
                    one['window_bytes'] = lstore.compare_window(mach, d)
                    one['readback'] = lstore.readback(mach, m, d,
                                                      REF / dumps[m].name)
                    if m not in states:
                        states[m] = upstream.Reader(LC.load_memory(
                            dumps[m] / 'r.ram.z')).read()
                    one['manifest_fields'] = manifest_check(mach, states[m])
                    one['derived'] = derived_check(mach, headers[m],
                                                   states[m])
                    hl = lrun.harness_level(mach, m, CONV / ('e1m%d' % m))
                    one['harness'] = lrun.compare_harness(hl, CONV /
                                                          ('e1m%d' % m))
                    if mach.main[LL.LV_VARMAP] != m:
                        raise CheckError('LV_VARMAP %d' %
                                         mach.main[LL.LV_VARMAP])
                    one['ok'] = True
                except (lstore.StoreError, lrun.RunError, CheckError,
                        KeyError) as error:
                    one.update(ok=False, error=str(error))
                    res['problems'].append('load %d (E1M%d): %s' % (k + 1, m,
                                                                     error))
                res['loads'].append(one)
                print('%02X load %2d E1M%d: %s' % (
                    fill, k + 1, m, 'ok' if one['ok'] else
                    'FAILED: ' + one['error']), flush=True)
            writes = RC.read_writes(work / 'writes.log')
            strays = lrun.stray_by_load(writes, b,
                                        [headers[m] for m in sequence])
            res['cpu_writes'] = len(writes)
            if strays:
                res['problems'].append('%d stray CPU writes: %s' % (
                    len(strays), '; '.join(strays[:4])))
            low = None
            for rr in r.state.get('lowest_s', {}).get('ranges', []):
                if rr.get('s') is not None:
                    low = rr['s'] if low is None else min(low, rr['s'])
            res['stack_bytes'] = None if low is None else lrun.DRV_STACK - low
            if low is None or res['stack_bytes'] + R.IRQ_STACK > \
                    LL.LOAD_STACK:
                res['problems'].append('the stack: %s B + %d for the IRQ '
                                       'over %d' % (res['stack_bytes'],
                                                    R.IRQ_STACK,
                                                    LL.LOAD_STACK))
            res['irqs'] = None
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        # the whole machine at the end of the same loads
        work = Path(tempfile.mkdtemp(prefix='tmp-m9-whole-',
                                     dir=str(ROOT / 'build')))
        try:
            r = lrun.run(b, sequence, fill, work, snapshots=False,
                         whole=True, write_log=False)
            if r.ended() != 'halt':
                res['problems'].append('the whole run ended: %s' % r.ended())
            else:
                end = lrun.SnapMachine.from_ram(work / 'final.ram') \
                    if (work / 'final.ram').exists() else \
                    lrun.SnapMachine.from_ram(next(work.glob('*.ram')))
                res['irqs'] = end.main[0xD8] | end.main[0xD9] << 8
                if not res['irqs']:
                    res['problems'].append('no interrupt was taken')
                aux: Dict[int, set] = {}
                main: set = set()
                for m in set(sequence):
                    a, mm = own_places(m, headers[m])
                    for bank, rr in a.items():
                        aux.setdefault(bank, set()).update(rr)
                    main.update(mm)
                n, shown = lrun.changed_outside(b, fill, sequence, end, aux,
                                                main)
                res['changed_outside'] = n
                if n:
                    res['problems'].append('%d bytes changed outside the '
                                           'loads\' places: %s' % (
                                               n, ', '.join(shown)))
                # the card: only the driver's count and the vectors
                lab = b.labels
                card_before = bytearray(0x5000)
                for kind, bank, address, data in \
                        lrun.card_records(b, fill) + \
                        [lrun.map_list(b, sequence)]:
                    off = address - 0xC000 if kind == 2 else \
                        0x4000 + address - 0xD000
                    card_before[off:off + len(data)] = data
                okc = set(range(lab['dl_k'] - 0xC000, lab['dl_k'] + 1 -
                                0xC000)) | {0xFFFE - 0xC000, 0xFFFF - 0xC000}
                bad = [i for i in range(0x5000) if card_before[i] !=
                       end.card[i] and i not in okc]
                if bad:
                    res['problems'].append('the card changed at %d bytes '
                                           '(first $%04X)' % (len(bad),
                                                               bad[0]))
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        # each map loaded alone: every byte changed within that map's own
        # places (the sequence's check allows the union of its maps')
        res['changed_outside_alone'] = {}
        for m in sorted(set(sequence)):
            work = Path(tempfile.mkdtemp(prefix='tmp-m9-alone-',
                                         dir=str(ROOT / 'build')))
            try:
                r = lrun.run(b, [m], fill, work, snapshots=False,
                             whole=True, write_log=False)
                if r.ended() != 'halt':
                    res['problems'].append('E1M%d alone: the run ended: %s'
                                           % (m, r.ended()))
                    continue
                end = lrun.SnapMachine.from_ram(work / 'final.ram') \
                    if (work / 'final.ram').exists() else \
                    lrun.SnapMachine.from_ram(next(work.glob('*.ram')))
                aux, main = own_places(m, headers[m])
                n, shown = lrun.changed_outside(b, fill, [m], end, aux, main)
                res['changed_outside_alone']['E1M%d' % m] = n
                if n:
                    res['problems'].append('E1M%d alone: %d bytes changed '
                                           'outside its places: %s' % (
                                               m, n, ', '.join(shown)))
            finally:
                shutil.rmtree(str(work), ignore_errors=True)
        report['runs'].append(res)
        for p_ in res['problems']:
            report['failures'].append('%02X: %s' % (fill, p_))
        print('%02X: %d loads, %d problems; %s CPU writes, stack %s B, '
              '%s interrupts' % (fill, len(res['loads']),
                                 len(res['problems']), res.get('cpu_writes'),
                                 res.get('stack_bytes'), res.get('irqs')),
              flush=True)
    return report


def load_timing(maps: Sequence[int] = tuple(range(1, 10)),
                profiles=('f121', 'fastpath')) -> Dict[str, Any]:
    import shutil
    import tempfile
    from a2vm import costs
    from native import lrun
    b = lrun.load_build(lrun.OBJ, 'lprof')
    out: Dict[str, Any] = {'format': 'level-load-timing 1', 'maps': {}}
    for m in maps:
        row = {}
        for profile in profiles:
            work = Path(tempfile.mkdtemp(prefix='tmp-m9-time-',
                                         dir=str(ROOT / 'build')))
            try:
                r = lrun.run(b, [m], 0xA5, work, snapshots=False,
                             write_log=False, profile=profile)
                if r.ended() != 'halt':
                    raise CheckError('E1M%d: %s' % (m, r.ended()))
                text = (work / 'cost.json').read_text()
                cost = json.loads(text[text.rfind('{"final"'):])['cost']
                mhz = costs.parameters(profile)['fabric_mhz']
                ph = {lrun.PHASES.get(k, str(k)):
                      round(v / (mhz * 1000.0), 3)
                      for k, v in enumerate(cost['phases']) if v}
                ph['load'] = round(sum(v for k, v in ph.items()
                                       if k not in ('image', 'driver')), 3)
                row[profile] = ph
            finally:
                shutil.rmtree(str(work), ignore_errors=True)
        out['maps']['E1M%d' % m] = row
        print('E1M%d: %s' % (m, '; '.join('%s %.1f ms (%s)' % (
            p, row[p]['load'], ', '.join('%s %.1f' % (k, v) for k, v in
                                         row[p].items() if k != 'load'))
            for p in profiles)), flush=True)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--conv', action='store_true')
    parser.add_argument('--derive', action='store_true')
    parser.add_argument('--store', action='store_true')
    parser.add_argument('--load', action='store_true')
    parser.add_argument('--load-timing', action='store_true')
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--flood', action='store_true')
    parser.add_argument('--setup-timing', action='store_true')
    parser.add_argument('--report-md', action='store_true')
    parser.add_argument('--setups', default='',
                        help='setup or run names (default: all)')
    parser.add_argument('--fills', default='a5,5a')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--maps', default='1-9')
    parser.add_argument('--no-ref', action='store_true',
                        help='do not write levelconv.py\'s conversions')
    parser.add_argument('--report', type=Path, default=REPORT)
    args = parser.parse_args(argv)
    maps = WC.parse_maps(args.maps)
    if not setupcap.setup_dirs():
        print('no setup captures in %s: run python3 tools/native/'
              'setupcap.py first' % setupcap.SETUPS, file=sys.stderr)
        return 1
    if args.derive:
        from native import lderive
        report = lderive.check_all(maps)
        path = LEVELS / 'check-derive.json'
        path.write_text(json.dumps(report, indent=1) + '\n')
        print('%d R dumps: %d failures' % (len(report['setups']),
                                          len(report['failures'])))
        return 1 if report['failures'] else 0
    if args.setup or args.flood or args.setup_timing or args.report_md:
        from native import lrun, setupcheck as SC
        if not args.no_build and not args.report_md:
            lrun.make()
        names = [x for x in args.setups.split(',') if x] or None
        if args.setup:
            report = SC.check_setups(tuple(int(x, 16) for x in
                                           args.fills.split(',')), names,
                                     keep=LEVELS / 'setup')
            if names is None:
                # the validcount wrap fix (docs/LEVELS.md 3.4)
                try:
                    report['wrap'] = SC.check_wrap_fix()
                    if not report['wrap']['ok']:
                        report['failures'].append('the wrap fix: %s' % {
                            k: v['diff'][:3] for k, v in
                            report['wrap']['builds'].items()})
                except SC.SetupError as error:
                    report['failures'].append(str(error))
                print('the wrap fix: %s' % ('ok' if report.get('wrap', {})
                                            .get('ok') else 'FAILED'))
            (LEVELS / 'check-c.json').write_text(json.dumps(
                report, indent=1) + '\n')
            ok = sum(1 for s in report['setups'].values()
                     if all(f['ok'] for f in s['fills'].values()))
            print('%d of %d setups equal ref816\'s, %d runs: %d failures'
                  % (ok, len(report['setups']), len(report['runs']),
                     len(report['failures'])))
            for f in report['failures'][:10]:
                print('  ' + f)
            return 1 if report['failures'] else 0
        if args.flood:
            report = SC.check_flood(LEVELS / 'setup')
            (LEVELS / 'flood.json').write_text(json.dumps(
                report, indent=1) + '\n')
            for m, r in sorted(report['maps'].items()):
                print('%s: %d sectors, worst depth %d (sector %d), bound '
                      '%d, stack %d: %s' % (m, r['sectors'], r['depth'],
                                            r['start'], r['bound'],
                                            r['stack'], 'ok' if r['ok']
                                            else 'FAILED'))
            return 1 if report['failures'] else 0
        if args.setup_timing:
            report = SC.setup_timing(maps)
            (LEVELS / 'timing-c.json').write_text(json.dumps(
                report, indent=1) + '\n')
            return 0
        SC.write_report(LEVELS / 'report.md')
        print('wrote %s' % (LEVELS / 'report.md'))
        return 0
    if args.load or args.load_timing:
        from native import lrun
        if not args.no_build:
            lrun.make()
        if args.load_timing:
            report = load_timing(maps)
            (LEVELS / 'timing-b.json').write_text(json.dumps(
                report, indent=1) + '\n')
            return 0
        report = check_load(tuple(int(x, 16) for x in
                                  args.fills.split(',')))
        (LEVELS / 'check-b.json').write_text(json.dumps(report, indent=1) +
                                             '\n')
        print('%d runs: %d failures' % (len(report['runs']),
                                        len(report['failures'])))
        for f in report['failures'][:10]:
            print('  ' + f)
        return 1 if report['failures'] else 0
    if args.store:
        report = check_store()
        (LEVELS / 'check-store.json').write_text(json.dumps(report,
                                                            indent=1) + '\n')
        print('%d loads: %d failures' % (len(report['loads']),
                                         len(report['failures'])))
        return 1 if report['failures'] else 0
    if not args.conv:
        parser.error('--conv, --derive or --store')
    report = check_conv(maps, not args.no_ref)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=1) + '\n')
    nw = sum(1 for r in report['w'].values() if r['ok'])
    ns = sum(1 for r in report['sources'].values() if r['ok'])
    print('%d of %d W dumps and %d of %d level sources equal (%d synthetic '
          'not compared); %d failures; %.0f s' % (
              nw, sum(1 for r in report['w'].values() if r['ok'] is not None),
              ns,
              sum(1 for r in report['sources'].values()
                  if r['ok'] is not None),
              sum(1 for r in list(report['sources'].values()) +
                  list(report['w'].values()) if r['ok'] is None),
              len(report['failures']), report['seconds']))
    return 1 if report['failures'] else 0


if __name__ == '__main__':
    sys.exit(main())
