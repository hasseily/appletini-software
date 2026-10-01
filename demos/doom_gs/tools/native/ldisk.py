#!/usr/bin/env python3
"""The level store's boot disk (milestone 9, stages B and C; docs/LEVELS.md
1.7, 5.4): LEVELS.hdv, a ProDOS volume LEVELS whose LEVELS.SYSTEM loads
the whole store into RamWorks at boot and then sets up each map in turn
(nl_setup, from the E pre-state of the map's tour-sk2 setup), with the
CRCs of each setup's window and state against their expected values,
for the owner's card run at milestone 12.

Usage:  python3 tools/native/ldisk.py [--out FILE] [--check]
                [--profiles f121,fastpath] [--no-build]

It builds build/native/LEVELS.hdv (or --out) with the existing port's
disk writer (demos/doom/tools/build_disk.py, as rdisk.py does), holding:

  LEVELS.SYSTEM  src/native/lboot.s's boot code (build lcard: lcard.boot
                 at $2000), then the card image: main card bank 1
                 $D000-$DFFF (the quarter squares, the math's products,
                 the far layer, the phase loader), bank 2 (unused),
                 $E000-$FFFF (the runner, the vectors)
  CATALOG        the bank files to load, then the entries in turn: the
                 maps (the nine in a row, in reverse, then E1M5 twice:
                 level_check.SEQUENCE), and each one's pre-state
  TEXELS.n, PATCHES.n, MAPS.n, TABLES.n
                 the store's bank files (lstore.py, wadconv.py --store)
  CODE.1         a bank file of the load phase's image (bank LCODE at W's
                 addresses: lcard.w, lcard.lw)
  PRESTATE.1     stage C: the test pre-states (bank PRE_BANK): of each map,
                 its tour-sk2 setup's E (setupcheck.prestate, fill 0)
  CRCLIST.1      stage C (bank CRC_BANK): each map's two range lists (its
                 window.img's records, the main text page's slot holes left
                 out; its setup state's records by the counts of the
                 tour-sk2 R dump: the game globals, LNMAP, the mobjs, the
                 specials, the sector nodes, the sectors' records, the
                 blocklinks, the lines) and each entry's expected CRC-32s:
                 those of an image run of the release build lfix from the
                 same pre-state, whose canonical state equals ref816's R
                 dump (so the CRCs certify that state)

--check runs the disk's own LEVELS.SYSTEM on a2vm end to end: its MLI
trap serves the files, its memory API (--amem) the copies, the mouse
card's VBL interrupt the clock, under the cost model (--profiles); after
each setup (run_loaded) a snapshot: the machine must equal the map's
window.img outside its mask.img, its canonical state (native-level-1)
must equal the tour-sk2 R dump's, and after the first one every byte of
every bank file must be in its bank but those the map's window.img and
its setup change; at the end the runner's CRCs must be the expected
ones (every entry OK); every interrupt keeps the IRQ contract
(--irq-bounds: MEMORY_MAP.md rule 2). It prints the boot's time, each
setup's VBLs (50 Hz) and writes build/native/levels/ldisk.json. The
owner runs the same disk on the card at milestone 12.
"""

import argparse
import importlib.util
import json
import struct
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from a2vm import costs  # noqa: E402
from native import levelconv as LC, llayout as LL, lrun, lstore, \
    rlayout as R  # noqa: E402
from ref816 import bounded  # noqa: E402

DOOM_TOOLS = ROOT.parent / 'doom' / 'tools'
BUILD = ROOT / 'build'
OUT = BUILD / 'native' / 'LEVELS.hdv'
RESULTS = BUILD / 'native' / 'levels' / 'ldisk.json'
VOLUME = 'LEVELS'
SYSTEM = 'LEVELS.SYSTEM'
BOOT_SIZE = 0x0800
CAT_MAX = 0x0100                # lboot.s
C_NAMES = 16
MAX_MAPS = 40
FABRIC_HZ = 133_333_333
CHECK_TIMEOUT = 1800
SEQUENCE = tuple(range(1, 10)) + tuple(range(9, 0, -1)) + (5, 5)
CRC_BANK = LL.SPARE[3]          # lboot.s CRC_BANK (a spare bank: test data)
# what each setup's snapshot takes: lrun's (with the game's banks), the
# STORE banks, LCODE, the pre-states and the CRC lists
BOOT_RANGES = lrun.SNAP_RANGES_SETUP + ',' + ','.join(
    'aux%d:0200-BFFF' % b for b in LL.STORE_BANKS + (LL.LCODE, LL.PRE_BANK,
                                                     CRC_BANK)) + \
    ',lc:E000-FFFF'
PRE_FILL = 0                    # the pre-states' bytes no leaf holds
# CRCLIST (lboot.s): the lists' addresses, the expected CRCs, the lists
CL_LISTS, CL_EXPECT, CL_DATA = 0x0200, 0x0240, 0x0400
# the main text page's slot holes (MEMORY_MAP.md rule 9: firmware writes
# them): left out of the CRCs
HOLES = [(page + off, page + off + 8) for page in range(0x0400, 0x0800,
                                                        0x100)
         for off in (0x78, 0xF8)]


class DiskError(Exception):
    pass


def card_image(b) -> bytes:
    """The main card: bank 1 $D000-$DFFF, bank 2 $D000-$DFFF,
    $E000-$FFFF (lboot.s's boot copies them in that order)."""
    recs = lrun.card_records(b, 0)
    lc = next(d for k, _, _, d in recs if k == 2)
    lc1 = next(d for k, _, _, d in recs if k == 3)
    return bytes(lc1) + bytes(0x1000) + bytes(lc[0x2000:0x4000])


def system_file(b) -> bytes:
    boot = (b.obj / ('%s.boot' % b.name)).read_bytes()
    if len(boot) != BOOT_SIZE:
        raise DiskError('%s.boot is %d bytes, not %d' % (b.name, len(boot),
                                                         BOOT_SIZE))
    data = boot + card_image(b)
    # ProDOS loads the file at $2000 with CPU stores: never the firmware's
    # A2Li signature at $4078 (MEMORY_MAP.md rule 8)
    if data[0x4078 - 0x2000:0x407C - 0x2000] == bytes((0xC1, 0xB2, 0xCC,
                                                       0xE9)):
        raise DiskError('LEVELS.SYSTEM holds the A2Li signature at $4078')
    return data


def code_file(b) -> bytes:
    return lstore.bank_file([(bank, address, data) for _, bank, address,
                             data in lrun.load_image(b)])


def catalog(names: Sequence[str], maps: Sequence[int],
            pre: Optional[Sequence[int]] = None) -> bytes:
    if len(maps) > MAX_MAPS:
        raise DiskError('%d maps: the runner holds %d' % (len(maps),
                                                          MAX_MAPS))
    pre = list(pre) if pre is not None else [0xFF] * len(maps)
    cat = bytearray(C_NAMES)
    cat[0], cat[1] = len(names), len(maps)
    for n in names:
        entry = bytearray(16)
        entry[0] = len(n)
        entry[1:1 + len(n)] = n.encode('ascii')
        cat += entry
    cat += bytes(maps) + bytes(MAX_MAPS - len(maps)) + bytes(pre)
    if len(cat) > CAT_MAX:
        raise DiskError('the catalog is %d bytes, the runner holds %d'
                        % (len(cat), CAT_MAX))
    return bytes(cat)


def window_ranges(gamemap: int) -> List[Tuple[int, int, int, int]]:
    """The map's window.img records as CRC ranges (kind, bank, address,
    length), the main text page's slot holes left out."""
    out = []
    for kind, bank, address, data in LC.Image.parse(
            (lstore.STORE / ('e1m%d' % gamemap) / 'window.img').read_bytes()):
        start, end = address, address + len(data)
        cuts = sorted(h for h in HOLES if kind == 0 and h[0] < end and
                      h[1] > start)
        for lo, hi in cuts:
            if lo > start:
                out.append((kind, bank, start, lo - start))
            start = max(start, hi)
        if end > start:
            out.append((kind, bank, start, end - start))
    return out


def state_ranges(header: Dict[str, Any], ref: Dict[str, Any]
                 ) -> List[Tuple[int, int, int, int]]:
    """The setup state's records by the counts of a canonical state of the
    map after its setup (ref816's R dump: the native counts are the same,
    acceptance 1): the game globals and the random indexes, LNMAP, the
    pool's and the zone's mobjs (RTHING and the three game parts), each
    kind's specials, the sector nodes, the sectors (render and game
    parts), the blocklinks, the lines."""
    c = header['counts']
    o = ref['objects']
    out = [(0, 0, LL.GBLOCK, LL.GLOBALS_END - LL.GBLOCK),
           (0, 0, LL.PRND, 2), (0, 0, LL.LNMAP, LL.LNMAP_END - LL.LNMAP)]
    mobjs = len(o.get('mobj', {})) + len(o.get('zmobj', {}))
    for bank in (R.RTH,) + LL.MOBJ_BANKS:
        out.append((1, bank, R.RTHINGS.base, LL.MO_SIZE * mobjs))
    for kind, (lo, n) in LL.SPEC_RANGE.items():
        k = len(o.get(kind, {}))
        if k:
            out.append((1, LL.ZONE0, LL.SPECS.address(lo), LL.SPEC_SIZE * k))
    nodes = len(o.get('secnode', {}))
    if nodes:
        out.append((1, LL.ZONE1, LL.SNODES.base, LL.SN_SIZE * nodes))
    out += [(1, R.LVMAP, R.SECTORS.base, R.SEC_SIZE * c['sectors']),
            (1, LL.LVG1, LL.SECGS.base, LL.SECG_SIZE * c['sectors']),
            (1, LL.LVG1, header['lvg1']['BLINKS'], 2 * c['blocks']),
            (1, LL.LVG0, LL.LINES.base, LL.LINE_SIZE * c['lines'])]
    return [r for r in out if r[3]]


def crc_of(mach, ranges) -> int:
    import zlib
    crc = 0
    for kind, bank, address, n in ranges:
        data = bytes(mach.main[address:address + n]) if kind == 0 else \
            mach.read(bank, address, n)
        crc = zlib.crc32(data, crc)
    return crc & 0xFFFFFFFF


def setups(maps: Sequence[int]) -> Dict[int, Any]:
    """Each map's tour-sk2 setup: its directory, R state and memory."""
    from bridge import upstream
    from native import setupcap, setupcheck as SC
    out = {}
    for d in setupcap.setup_dirs([SC.KEEP_RUN]):
        m = json.loads((d / 'setup.json').read_text())['gamemap']
        if m in maps:
            rm = LC.load_memory(d / 'r.ram.z')
            out[m] = (d, upstream.Reader(rm).read(), rm)
    missing = sorted(set(maps) - set(out))
    if missing:
        raise DiskError('no tour-sk2 setup of E1M%s: run setupcap.py' %
                        missing)
    return out


def expected(maps: Sequence[int], pres: Dict[int, bytes],
             lists: Dict[int, Any], refs: Dict[int, Any],
             obj: Path = lrun.OBJ) -> Dict[int, Tuple[int, int]]:
    """Each map's expected CRCs: an image run of the release build (lfix)
    from its pre-state; its canonical state must equal the R dump's."""
    from native import setupcheck as SC
    b = lrun.load_build(obj, 'lfix')
    order = sorted(set(maps))
    work = Path(tempfile.mkdtemp(prefix='tmp-m9-expect-', dir=str(BUILD)))
    out = {}
    try:
        r = lrun.run(b, order, 0xA5, work, pre=list(range(len(order))),
                     prestates=[pres[m] for m in order], setup=True,
                     write_log=False)
        if r.ended() != 'halt':
            raise DiskError('the expected CRCs\' run: %s' % r.ended())
        skip = SC.skips()
        for m, p in zip(order, lrun.load_snapshots(work)):
            mach = lrun.SnapMachine.from_image(p)
            diff = SC.compare(refs[m][1], SC.native_state(
                mach, SC.manifest_of(m)), skip)
            if diff:
                raise DiskError('E1M%d: the expected run differs from '
                                'ref816: %s' % (m, diff[:3]))
            out[m] = (crc_of(mach, lists[m][0]), crc_of(mach, lists[m][1]))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return out


def crc_file(maps: Sequence[int], lists: Dict[int, Any],
             expect: Dict[int, Tuple[int, int]]) -> bytes:
    """CRCLIST.1: the lists' addresses (4 bytes a map from map 1), each
    entry's expected CRCs (8 bytes), the lists."""
    import struct as st
    if CL_LISTS + 4 * 9 > CL_EXPECT or CL_EXPECT + 8 * MAX_MAPS > CL_DATA:
        raise DiskError('CRCLIST\'s head')
    blob = bytearray(CL_DATA - LL.ROOM[0])
    at = CL_DATA
    data = bytearray()
    for m in range(1, 10):
        for j in range(2):
            ranges = lists.get(m, ([], []))[j]
            st.pack_into('<H', blob, CL_LISTS - LL.ROOM[0] + 4 * (m - 1) +
                         2 * j, at + len(data))
            data += st.pack('<H', len(ranges))
            for kind, bank, address, n in ranges:
                if not 0 < n < 0x10000:
                    raise DiskError('a range of %d bytes' % n)
                data += st.pack('<BBHH', kind, bank, address, n)
    for k, m in enumerate(maps):
        w, s = expect[m]
        st.pack_into('<II', blob, CL_EXPECT - LL.ROOM[0] + 8 * k, w, s)
    whole = bytes(blob + data)
    if LL.ROOM[0] + len(whole) > LL.ROOM[1]:
        raise DiskError('CRCLIST is %d bytes' % len(whole))
    return lstore.bank_file([(CRC_BANK, LL.ROOM[0], whole)])


def build(obj: Path = lrun.OBJ, maps: Sequence[int] = SEQUENCE
          ) -> Dict[str, Any]:
    from native import setupcheck as SC
    b = lrun.load_build(obj, 'lcard')
    store = lrun.store_files()
    data = [(p.name, p.read_bytes()) for p in store]
    data.append(('CODE.1', code_file(b)))
    order = sorted(set(maps))
    refs = setups(order)
    meta = SC.store_meta()
    pres = {m: SC.prestate(SC.manifest_of(m, meta), refs[m][0], refs[m][1],
                           refs[m][2], PRE_FILL) for m in order}
    lists = {m: (window_ranges(m), state_ranges(SC.header_of(meta, m),
                                                refs[m][1])) for m in order}
    expect = expected(maps, pres, lists, refs, obj)
    index = {m: k for k, m in enumerate(order)}
    data.append(('PRESTATE.1', lstore.bank_file([
        (LL.PRE_BANK, LL.ROOM[0] + LL.PRE_RECORD * index[m], pres[m])
        for m in order])))
    data.append(('CRCLIST.1', crc_file(maps, lists, expect)))
    names = [n for n, _ in data]
    files = [(SYSTEM, 0xFF, 0x2000, system_file(b)),
             ('CATALOG', 0x06, 0x0000, catalog(names, maps,
                                              [index[m] for m in maps]))]
    files += [(n, 0x06, 0x0000, d) for n, d in data]
    return {'files': files, 'labels': b.labels, 'maps': list(maps),
            'build': b, 'expect': {m: list(v) for m, v in expect.items()},
            'refs': {m: refs[m][1] for m in order}}


def disk_writer():
    path = DOOM_TOOLS / 'build_disk.py'
    spec = importlib.util.spec_from_file_location('doom_build_disk_l', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_disk(files, output: Path) -> None:
    bd = disk_writer()
    bd.VOLUME_NAME = VOLUME
    master = bd.DEFAULT_MASTER
    if not master.is_file():
        raise FileNotFoundError('%s is missing (appletini-one\'s ProDOS; '
                                'set APPLETINI_ROOT)' % master)
    boot, prodos = bd.extract_prodos(master)
    everything = [files[0], ('PRODOS', bd.FILE_TYPE_SYS, 0x0000, prodos)] + \
        files[1:]
    writer = bd.VolumeWriter(VOLUME, bd.volume_size([f[3] for f in
                                                     everything]))
    writer.set_boot_blocks(boot)
    for name, file_type, aux, data in everything:
        writer.add_file(name, data, file_type, aux)
    image = writer.finish()
    expected = {name: (t, aux, data) for name, t, aux, data in everything}
    bd.verify_image(image, expected, order=[f[0] for f in everything])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(image)


def check(disk: Dict[str, Any], work: Path, profile: str) -> Dict[str, Any]:
    """One a2vm run of the disk (the module docstring)."""
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    lab = disk['labels']
    manifest = []
    for name, file_type, aux, data in disk['files']:
        path = work / name
        path.write_bytes(data)
        manifest.append('%s %02X %04X %s' % (name, file_type, aux, path))
    (work / 'prodos.txt').write_text('\n'.join(manifest) + '\n')
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    (work / 'cost.txt').write_text(costs.text(profile))
    maps = disk['maps']
    events = ['pc %X snapshot start' % lab['run_start'],
              'pc %X@* snapshot load' % lab['run_loaded'],
              'pc %X snapshot done' % lab['run_done'],
              'pc %X stop' % lab['run_done']]
    (work / 'events.txt').write_text('\n'.join(events) + '\n')
    args = [str(lrun.A2VM), '--rom', str(work / 'rom.bin'),
            '--core', 'w65c02s', '--amem',
            '--prodos', str(work / 'prodos.txt'),
            '--volume', VOLUME, '--launched', SYSTEM,
            '--load', '2000:%s' % (work / SYSTEM),
            '--reg', 'pc=2000', '--reg', 's=FF',
            '--cost', str(work / 'cost.txt'), '--cost-timed',
            '--irq-bounds', '00D8-01FF,C0A0-C0AF,E000-FFFF',
            '--stop-pc', '%X' % lab['run_crash'],
            '--cycles', str(int(120 * FABRIC_HZ)),
            '--snapshot-dir', str(work),
            '--snapshot-ranges', BOOT_RANGES,
            '--every-limit', str(len(maps) + 1),
            '--input', str(work / 'events.txt'),
            '--state', str(work / 'state.json')]
    result = bounded.run(['nice', '-n', '10'] + args,
                         timeout=CHECK_TIMEOUT, max_bytes=256 << 20,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         universal_newlines=True)
    state_path = work / 'state.json'
    if not state_path.exists():
        raise DiskError('a2vm failed: %s' % result.stdout[-1000:])
    state = json.loads(state_path.read_text())
    out: Dict[str, Any] = {'profile': profile, 'end': state.get('end'),
                           'pc': state.get('pc'), 'problems': []}
    if state.get('pc') == lab['run_crash'] or \
            not (work / 'done.json').exists():
        out['problems'].append('the runner did not reach run_done (pc '
                               '$%04X, %s)' % (state.get('pc', -1),
                                               state.get('end')))
        return out
    start = json.loads((work / 'start.json').read_text())
    done = json.loads((work / 'done.json').read_text())
    out['boot_cycles'] = start.get('cycles')
    out['boot_ms'] = round(start.get('cycles', 0) * 1000.0 /
                           (costs.parameters(profile)['fabric_mhz'] * 1e6),
                           1) if profile else None
    shots = sorted(work.glob('load-*.img'))
    if len(shots) != len(maps):
        out['problems'].append('%d loads, %d snapshots' % (len(maps),
                                                           len(shots)))
    from native import setupcheck as SC
    files = [lstore.read_bank_file(d) for n, _, _, d in disk['files'][2:]
             if n not in ('PRESTATE.1', 'CRCLIST.1')]
    loads = []
    skip = SC.skips()
    for k, (m, p) in enumerate(zip(maps, shots)):
        mach = lrun.SnapMachine.from_image(p)
        one = {'map': m}
        try:
            one['window_bytes'] = lstore.compare_window(
                mach, lstore.STORE / ('e1m%d' % m))
            diff = SC.compare(disk['refs'][m], SC.native_state(
                mach, SC.manifest_of(m)), skip)
            if diff:
                raise DiskError('the canonical state differs from '
                                'ref816\'s: %s' % '; '.join(diff[:3]))
            one['canonical'] = 'equal'
            if k == 0:
                one['store_bytes'] = store_check(mach, files, m)
            one['ok'] = True
        except (lstore.StoreError, DiskError, lrun.RunError) as error:
            one.update(ok=False, error=str(error))
            out['problems'].append('load %d (E1M%d): %s' % (k + 1, m, error))
        loads.append(one)
        p.unlink()
    # each load's VBLs (rn_results), from the end's snapshot
    vbls = []
    cardimg = [r for r in LC.Image.parse((work / 'done.img').read_bytes())
               if r[0] == 2] if (work / 'done.img').exists() else []
    for k in range(len(maps)):
        at = lab['rn_results'] + 2 * k
        v = None
        for kind, bank, address, data in cardimg:
            if address <= at < address + len(data) - 1:
                v = data[at - address] | data[at - address + 1] << 8
        vbls.append(v)
    for one, v in zip(loads, vbls):
        one['vbls'] = v
    # the runner's CRCs and their matches (rn_crcs, rn_ok)
    crcs = card_bytes(cardimg, lab['rn_crcs'], 8 * len(maps))
    oks = card_bytes(cardimg, lab['rn_ok'], len(maps))
    for k, one in enumerate(loads):
        if crcs is None or oks is None:
            out['problems'].append('no results table')
            break
        w, s = struct.unpack_from('<II', crcs, 8 * k)
        one['crc_window'] = '%08X' % w
        one['crc_state'] = '%08X' % s
        one['crc_ok'] = oks[k]
        want = disk['expect'][one['map']]
        if (w, s) != tuple(want) or oks[k] != 3:
            out['problems'].append('entry %d (E1M%d): CRCs %08X %08X, '
                                   'expected %08X %08X, OK flags %d' % (
                                       k + 1, one['map'], w, s, want[0],
                                       want[1], oks[k]))
    out['loads'] = loads
    out['screen'] = text_screen(work / 'done.img')
    if not out['screen'] or not out['screen'][-1].startswith('SETUPS OK'):
        out['problems'].append('the screen\'s last row: %r' % (
            out['screen'][-1] if out['screen'] else None))
    out['cycles'] = state.get('cycles')
    out['done_cycles'] = done.get('cycles')
    return out


def text_screen(path: Path) -> List[str]:
    """The text page (main $0400-$07FF) of a snapshot, as 24 rows."""
    if not path.exists():
        return []
    mach = lrun.SnapMachine.from_image(path)
    rows = []
    for r in range(24):
        base = 0x0400 + (r % 8) * 0x80 + (r // 8) * 0x28
        rows.append(''.join(chr(b & 0x7F) if 0x20 <= (b & 0x7F) < 0x7F
                            else '.' for b in mach.main[base:base + 40])
                    .rstrip())
    return rows


def card_bytes(cardimg, at: int, n: int) -> Optional[bytes]:
    for kind, bank, address, data in cardimg:
        if address <= at and at + n <= address + len(data):
            return bytes(data[at - address:at - address + n])
    return None


def store_check(mach, files, gamemap: int) -> int:
    """Every bank file's byte in its bank, but those the map's window.img
    (its load) changes."""
    changed: Dict[int, set] = {}
    for kind, bank, address, data in LC.Image.parse(
            (lstore.STORE / ('e1m%d' % gamemap) / 'window.img').read_bytes()):
        if kind == 1:
            changed.setdefault(bank, set()).update(
                range(address, address + len(data)))
    for bank in (R.RTH,) + LL.MOBJ_BANKS + (LL.ZONE0, LL.ZONE1):
        # (the setup's: stage C)
        changed.setdefault(bank, set()).update(range(LL.ROOM[0],
                                                     LL.ROOM[1]))
    n = 0
    for segs in files:
        for bank, address, data in segs:
            got = mach.read(bank, address, len(data))
            if got != data:
                sk = changed.get(bank, set())
                for i in range(len(data)):
                    if got[i] != data[i] and address + i not in sk:
                        raise DiskError('bank %d $%04X: the boot left $%02X, '
                                        'the bank file $%02X' % (
                                            bank, address + i, got[i],
                                            data[i]))
            n += len(data)
    return n


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--profiles', default='f121,fastpath')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--json', type=Path, default=RESULTS)
    args = parser.parse_args(argv)
    if not args.no_build:
        lrun.make()
    disk = build()
    write_disk(disk['files'], args.out)
    print('%s: %d bytes, %d files (%s)' % (
        args.out, args.out.stat().st_size, len(disk['files']) + 1,
        ', '.join('%s %d' % (n, len(d)) for n, _, _, d in disk['files'])))
    if not args.check:
        return 0
    results = []
    failed = 0
    for profile in args.profiles.split(','):
        work = Path(tempfile.mkdtemp(prefix='tmp-m9-disk-', dir=str(BUILD)))
        try:
            r = check(disk, work, profile)
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        results.append(r)
        failed += len(r['problems'])
        print('%s: boot %s ms; %d setups, %s; %d problems' % (
            profile, r.get('boot_ms'), len(r.get('loads', [])),
            ' '.join('E1M%d %s VBL' % (x['map'], x.get('vbls'))
                     for x in r.get('loads', [])), len(r['problems'])))
        for p in r['problems'][:6]:
            print('  ' + p)
        for row in r.get('screen', [])[:24] if profile == \
                args.profiles.split(',')[0] else []:
            print('  | ' + row)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(results, indent=1) + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
