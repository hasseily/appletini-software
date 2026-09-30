#!/usr/bin/env python3
"""Upstream's state at a wall call or a seg loop call as the native
renderer's (milestone 7, stage B; docs/RENDER.md 3.2, 4.1, 4.3): the one
place where upstream's WPAGE and near variables meet the native seg
descriptor SEGD and the frame block.

Usage:  python3 tools/native/segdesc.py CASE [--seg]

CASE is a routine case of tools/native/routinecap.py
(build/native/render/routines/FRAME/wKK.case.z). `wall_state` gives the
a2vm records of the state R_StoreWallRange enters with, `seg_state` the
state of the R_RenderSegLoop call inside it:

  - the frame's own state from its P0 (tools/native/framestate.py: the
    level's dynamic fields, TEXTRANS, LNMAP, the colormaps, the render
    inputs; the level's arrays are those of P0, since the renderer
    changes only validcount and ML_MAPPED there, routinecap.check_zone);
  - from the entry dump: the view, the light numbers, validcount, the
    clips (the words' low bytes: their high bytes must be 0), solidcol,
    the spans and covered ranges (FS_*, CV_*), the drawseg count and
    lastopening, rw_scalestep (kept from wall to wall), W_LCC, W_LFC,
    W_CEILW, W_FLOORW, didsolidcol;
  - for the wall: the call's arguments as the walk gives them (RENDER.md
    3.2): start, stop, the seg (BS_SEG, its record at SEGR), the front
    sector (FSEC, SC_CUR), the plane colours, worldbottom;
  - for the seg loop: the seg descriptor, field by field: the edges
    TF .. PLS (WPAGE's bytes as they are: the native edges keep
    upstream's form), the marks and textures (bytes: a texture number
    above 255 is refused), rw_x, rw_stopx, rw_scale, the drawseg's
    scale2, rw_distance, rw_lightlevel, rw_normalangle, rw_offset,
    rw_centerangle, the three texturemids, maskedtexturecol as an
    opening index less rw_x.

Every byte the state does not define is the harness's fill (RENDER.md
4.2), so a field read before it is written shows.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge import linkmap as blink  # noqa: E402
from native import framestate as FS, levelconv, rlayout as R  # noqa: E402
from native import routinecap as RCP  # noqa: E402

WPAGE = 0x000A00
BSPDP = 0x000951
DP_STOP = 0x0009EB                      # _Dp: the stop of R_StoreWallRange
W = {'TF': 0x2C, 'MC': 0xC0, 'MF': 0xC2, 'SEGTEX': 0xC4, 'MIDTEX': 0xC6,
     'TOPTEX': 0xC8, 'BOTTEX': 0xCA, 'MASKED': 0xCC, 'CANGLE': 0x7E,
     'OFFSET': 0x80, 'CEILW': 0xE4, 'FLOORW': 0xE6, 'FSC': 0xE8,
     'FSP': 0xE9, 'TOPR': 0xEA, 'BOTR': 0xEB, 'LCC': 0xEE, 'LFC': 0xF0}
DS_COUNT = 0x0AB600
DSX1_UP, DSX2_UP = 0x0AB500, 0x0AB580
SIZEOF_SEG, SIZEOF_SEC, SIZEOF_DS = 18, 58, 42
OFS_DS_SCALE2 = 12


class StateError(Exception):
    pass


def le(data: bytes) -> int:
    return int.from_bytes(data, 'little')


def s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


class Ref:
    """A dump of the reference read by symbol."""

    def __init__(self, dump, sym: blink.Symbols):
        self.d = dump
        self.sym = sym

    def read(self, address: int, n: int) -> bytes:
        return self.d.get(address, n)

    def u(self, address: int, n: int) -> int:
        return le(self.read(address, n))

    def g(self, name: str, n: int) -> int:
        return self.u(self.sym.address(name), n)

    def w(self, field: str, n: int = 2) -> int:
        return self.u(WPAGE + W[field], n)

    def low_bytes(self, name: str, count: int) -> bytes:
        data = self.read(self.sym.address(name), 2 * count)
        if any(data[2 * i + 1] for i in range(count)):
            raise StateError('%s has a high byte other than 0' % name)
        return bytes(data[2 * i] for i in range(count))

    def spans(self) -> Tuple[bytes, bytes]:
        """The 8 planes of the fill spans and the covered ranges, as
        framestate.records lays them out."""
        sp = self.read(0x23EF00, 0xC00)
        planes = []
        for table in range(4):
            base = 0x200 * table
            planes.append(bytes(sp[base + 2 * c] for c in range(160)))
            planes.append(bytes(sp[base + 2 * c + 1] for c in range(160)))
        cv = bytes(sp[0x800 + 2 * c] for c in range(160)) + \
            bytes(sp[0x800 + 2 * c + 1] for c in range(160))
        return b''.join(planes), cv

    def opening_index(self, ptr: int) -> int:
        """An opening pointer (24 bits) as an index into openings."""
        off = (ptr & 0xFFFFFF) - self.sym.address('openings')
        if off % 2:
            raise StateError('an odd opening pointer $%06X' % ptr)
        return off // 2


def byte_of(value: int, what: str) -> int:
    if not 0 <= value < 256:
        raise StateError('%s is %d: the native byte holds 0-255'
                         % (what, value))
    return value


class Built:
    """The records of a state, and what the harness needs to know of it."""

    def __init__(self):
        self.records: List[Tuple[int, int, int, bytes]] = []
        self.info: Dict[str, Any] = {}

    def main(self, address: int, data: bytes) -> None:
        self.records.append((0, 0, address, bytes(data)))

    def aux(self, bank: int, address: int, data: bytes) -> None:
        self.records.append((1, bank, address, bytes(data)))


def u32(v: int) -> bytes:
    return (v & 0xFFFFFFFF).to_bytes(4, 'little')


def u16(v: int) -> bytes:
    return (v & 0xFFFF).to_bytes(2, 'little')


class Level:
    """A frame's converted level (levelconv.py) as bytes by bank."""

    def __init__(self, directory: Path):
        self.dir = directory
        self.info = json.loads((directory / 'level.json').read_text())
        self.banks: Dict[int, bytearray] = {}
        for kind, bank, address, data in levelconv.Image.parse(
                (directory / 'level.img').read_bytes()):
            if kind != 1:
                continue
            m = self.banks.setdefault(bank, bytearray(0x10000))
            m[address:address + len(data)] = data

    def seg(self, n: int) -> bytes:
        a = R.SEGS.address(n)
        return bytes(self.banks[R.LVSEG][a:a + R.SEG_SIZE])


def common(frame: FS.Frame, ref: Ref, level: Dict[str, Any],
           sym: blink.Symbols, inputs: Dict[str, Any]) -> Built:
    """What both routines read: the frame's P0 state, then the entry's."""
    b = Built()
    b.records += FS.records(frame, inputs, level)
    F = R.FRAME
    b.main(F['VIEWX'], u32(ref.g('viewx', 4)))
    b.main(F['VIEWY'], u32(ref.g('viewy', 4)))
    b.main(F['VIEWZ'], u32(ref.g('viewz', 4)))
    b.main(F['VIEWANGLE'], u32(ref.g('viewangle', 4)))
    b.main(F['VIEWA16'], u16(ref.g('viewangle16', 2)))
    b.main(F['EXTRALIGHT'], u16(ref.g('extralight', 2)))
    b.main(F['LT_BASE'], u16(ref.g('LT_BASE', 2)))
    b.main(F['LT_FIXED'], u16(ref.g('LT_FIXED', 2)))
    b.main(F['VALIDCOUNT'], u16(ref.g('validcount', 2)))
    b.main(F['DSCOUNT'], bytes([byte_of(ref.u(DS_COUNT, 2), 'dsCount')]))
    b.main(F['LASTOPEN'], u16(ref.opening_index(ref.g('lastopening', 3))))
    b.main(F['RW_STEP'], u32(ref.g('rw_scalestep', 4)))
    for name, field in (('W_LCC', 'LCC'), ('W_LFC', 'LFC'),
                        ('W_CEILW', 'CEILW'), ('W_FLOORW', 'FLOORW')):
        b.main(F[name], u16(ref.w(field)))
    for name, field in (('W_FSC', 'FSC'), ('W_FSP', 'FSP'),
                        ('W_TOPR', 'TOPR'), ('W_BOTR', 'BOTR')):
        b.main(F[name], bytes([ref.w(field, 1)]))
    b.main(F['DIDSOLID'], bytes([byte_of(ref.g('didsolidcol', 2),
                                         'didsolidcol')]))
    b.main(F['STG_BANK'], b'\0')
    b.main(F['STG_PTR'], u16(R.STAGE))
    b.main(F['STATUS'], b'\0')
    b.main(F['RULES'], b'\0')
    b.main(R.FLOORCLIP, ref.low_bytes('floorclip', 160))
    b.main(R.CEILCLIP, ref.low_bytes('ceilingclip', 160))
    b.main(R.SOLIDCOL, ref.read(sym.address('solidcol'), 160))
    planes, cv = ref.spans()
    b.main(R.SPANS, planes)
    b.main(R.CVFIRST, cv)
    b.main(R.ZP2['RB'], b'\0')
    fpc, cpc = ref.g('floorplane_color', 2), ref.g('ceilingplane_color', 2)
    b.main(R.ZP['FPC'], u16(fpc))
    b.main(R.ZP['CPC'], u16(cpc))
    b.info.update({'dscount': ref.u(DS_COUNT, 2),
                   'lastopening': ref.opening_index(ref.g('lastopening', 3)),
                   'fpc': fpc, 'cpc': cpc})
    return b


ZONE = (0x060000, 0x0A0000)             # the zone banks $06-$09


class PokedDump(FS.Dump):
    """A dump of the frame with a synthetic case's pokes in the zone."""

    def __init__(self, base: FS.Dump, pokes: List[Tuple[int, bytes]]):
        self.d = base.d
        self.header = base.header
        self.pokes = pokes

    def read(self, address: int, length: int) -> bytes:
        data = bytearray(self.d.get(address, length))
        for at, value in self.pokes:
            for i, byte in enumerate(value):
                if address <= at + i < address + length:
                    data[at + i - address] = byte
        return bytes(data)


class PokedFrame(FS.Frame):
    """A captured frame as a synthetic case changed it
    (routinesynth.py): its pokes in the zone (the level's dynamic arrays)
    apply to the frame's dumps; those elsewhere are in the case's own
    dumps already."""

    def __init__(self, directory: Path, pokes: List[Tuple[int, bytes]]):
        super().__init__(directory)
        self.pokes = [(a, v) for a, v in pokes if ZONE[0] <= a < ZONE[1]]

    def dump(self, what: str) -> FS.Dump:
        return PokedDump(super().dump(what), self.pokes)


def frame_of(case: RCP.Case) -> FS.Frame:
    directory = RCP.RC.FRAMES / case.header['frame']
    pokes = case.header.get('pokes')
    if pokes:
        return PokedFrame(directory, [(a, bytes.fromhex(v))
                                      for a, v in pokes])
    return FS.Frame(directory)


def wall_state(case: RCP.Case, sym: blink.Symbols) -> Built:
    """R_StoreWallRange's entry (SWE) as native records."""
    if 'SWE' not in case.points:
        raise StateError('a case of the seg loop only')
    frame = frame_of(case)
    level_dir = FS.level_of(frame, sym)
    level = json.loads((level_dir / 'level.json').read_text())
    inputs = FS.read_inputs(frame, sym, level)
    ref = Ref(case.points['SWE'], sym)
    b = common(frame, ref, level, sym, inputs)
    p0 = frame.dump('p0')
    segs = p0.u(sym.address('_g_segs'), 3)
    sectors = p0.u(sym.address('_g_sectors'), 3)
    dp = ref.read(BSPDP, 12)
    seg, rs = divmod(le(dp[0:3]) - segs, SIZEOF_SEG)
    sector, rc = divmod(le(dp[9:12]) - sectors, SIZEOF_SEC)
    if rs or rc or seg < 0 or sector < 0:
        raise StateError('the call\'s seg or sector is not one')
    start = case.points['SWE'].header['cpu']['a'] & 0xFFFF
    stop = ref.u(DP_STOP, 2)
    if not (0 <= start <= stop < 160):
        raise StateError('a wall from %d to %d' % (start, stop))
    lv = Level(level_dir)
    b.main(R.SEGBUF, lv.seg(seg))
    b.main(R.ZP['SEGR'], u16(R.SEGBUF))
    b.main(R.ZP['BS_SEG'], u16(seg))
    b.main(R.ZP['SC_CUR'], bytes([sector]))
    b.main(R.FSEC, levelconv.sector_record(inputs['sectors'][sector],
                                           sector))
    b.main(R.SPILLS['WBOT'], u32(ref.g('worldbottom', 4)))
    b.info.update({'start': start, 'stop': stop, 'seg': seg,
                   'sector': sector, 'level': level_dir.name,
                   'ds_p': (ref.g('ds_p', 2) - (sym.address('_s_drawsegs')
                                                & 0xFFFF)) // SIZEOF_DS})
    b.info['line'] = le(lv.seg(seg)[R.SEG['LINE']:R.SEG['LINE'] + 2])
    return b


def seg_state(case: RCP.Case, sym: blink.Symbols) -> Built:
    """R_RenderSegLoop's entry (SLE) as native records: the seg
    descriptor."""
    if 'SLE' not in case.points:
        raise StateError('the wall made no seg loop call')
    frame = frame_of(case)
    level_dir = FS.level_of(frame, sym)
    level = json.loads((level_dir / 'level.json').read_text())
    inputs = FS.read_inputs(frame, sym, level)
    ref = Ref(case.points['SLE'], sym)
    b = common(frame, ref, level, sym, inputs)
    Z, S = R.ZP2, R.SPILLS
    b.main(Z['TF'], ref.read(WPAGE + W['TF'], 32))
    flags = {}
    for name in ('MC', 'MF', 'SEGTEX', 'MIDTEX', 'TOPTEX', 'BOTTEX',
                 'MASKED'):
        v = byte_of(ref.w(name), 'W_' + name)
        flags[name] = v
        b.main(Z['W' + name], bytes([v]))
    x = case.points['SLE'].header['cpu']['a'] & 0xFFFF
    stopx = ref.g('rw_stopx', 2)
    if not (0 <= x < 256 and 0 < stopx <= 160):
        raise StateError('a seg from %d to %d' % (x, stopx))
    b.main(S['SD_X'], bytes([x]))
    b.main(Z['X2END'], bytes([stopx]))
    b.main(S['SD_SCALE'], u32(ref.g('rw_scale', 4)))
    ds = 0x020000 | ref.g('ds_p', 2)
    b.main(S['SD_SCALE2'], u32(ref.u(ds + OFS_DS_SCALE2, 4)))
    b.main(S['SD_DIST'], u16(ref.g('rw_distance', 2)))
    b.main(S['SD_LIGHT'], bytes([byte_of(ref.g('rw_lightlevel', 2),
                                         'rw_lightlevel')]))
    b.main(S['SD_NORMAL'], u16(ref.g('rw_normalangle', 2)))
    b.main(S['SD_OFFSET'], u16(ref.w('OFFSET')))
    b.main(S['SD_CANGLE'], u16(ref.w('CANGLE')))
    b.main(S['SD_MIDMID'], u32(ref.g('rw_midtexturemid', 4)))
    b.main(S['SD_TOPMID'], u32(ref.g('rw_toptexturemid', 4)))
    b.main(S['SD_BOTMID'], u32(ref.g('rw_bottomtexturemid', 4)))
    maskb = None
    if flags['MASKED']:
        maskb = ref.opening_index(ref.g('maskedtexturecol', 3))
        b.main(S['SD_MASKB'], u16(maskb))
    b.info.update({'x': x, 'stopx': stopx, 'flags': flags,
                   'maskb': maskb, 'level': level_dir.name})
    return b


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('case', type=Path)
    parser.add_argument('--seg', action='store_true')
    args = parser.parse_args(argv)
    sym = blink.Symbols()
    case = RCP.load_case(args.case)
    try:
        built = seg_state(case, sym) if args.seg else wall_state(case, sym)
    except (StateError, FS.FrameError, levelconv.ConvError) as error:
        print('segdesc: %s' % error, file=sys.stderr)
        return 1
    print(json.dumps(built.info, indent=1))
    print('%d records, %d bytes' % (len(built.records),
                                    sum(len(r[3]) for r in built.records)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
