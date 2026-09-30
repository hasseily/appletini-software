#!/usr/bin/env python3
"""Synthetic routine cases for the paths of R_StoreWallRange and
R_RenderSegLoop that no capture reaches (milestone 7, stage B;
docs/RENDER.md 4.1, "Synthetic cases"), with upstream's truth from
ref816 --call.

Usage:  python3 tools/native/routinesynth.py [--specs a,b,...]

Each case starts from a captured wall call (tools/native/routinecap.py)
of a chosen kind: its run goes on ref816 again to that call, which
--capture records whole (all RAM and the registers at the entry; the
machine is deterministic, and the capture must equal the captured call's
bank $02); the case's pokes change that state as the path needs; then
--call runs upstream's routine alone on the changed state, to its return
and, for a wall, stopped at its seg loop's entry and at the seg loop's
return site, each saving the ranges routinecap.py dumps (and bank $1D at
the return). The result is a case file of routinecap.py's format,
build/native/render/routines/synth-NAME/w00.case.z, whose header names
the captured frame (its P0 gives the level and the zone) and the pokes
(the harness applies those in the zone to P0 too: segdesc.PokedFrame).

The specs (SPECS): the paths of the coverage report the captures miss
(routinecap.PATHS; render_check.py --routines prints them):

    edgeslow    a bottom wall whose back floor has a fraction of its own:
                its edge is not from the shared low word (edgeSlow)
    mod16       a row offset of 45 on a single sided wall: rowMod's
                remainder for the texture's height (the vendor's _Mod16
                upstream when it is not a power of 2; sdiv16 natively)
    mod16neg    the same, -45 (the remainder + b)
    vmask       a two sided line with nothing to draw, given a mid
                texture: the masked-only loop (vMask)
    closed      a column of a loop of segvar.inc closed (floor clip -1):
                genColumn from the loop (L(slow))
    onecolslow  a wall of scaleSlow cut to one column: its scalestep stays
                the wall before's, and so do its edges' steps
    dsfull      the drawsegs full: R_StoreWallRange returns at once
    openfull    the openings nearly full: it returns after ML_MAPPED
    fsgeneral   (a seg loop call) a scale above 64.0: fsGeneral
    segearly    (a seg loop call) rw_stopx = rw_x: it returns at once (no
                captured call does: R_StoreWallRange's start <= stop)
    negsine     a view turned so that the wall's first column, and so
                every column, sees it from behind (angleb < 0): scaleFast
                bails out, and scaleSlow's sineLow reads with a negative
                index, which on the 65816 crosses into bank 3 (upstream's
                code); the native code takes its rule RULE_SINE at both
                ends (render_check.RULED; RENDER.md 3.9)
    grazefirst  a grazing view: only the wall's first column is seen from
                behind (angleb just past ANG180 there), a textured wall:
                RULE_SINE for scale1 and, in its seg loop, RULE_TANGENT
                (the texture angle 4096 and more: upstream's tcExact reads
                past finetangent part 4); the other end in the tables
    grazelast   the same at the last column (angleb just below 0: the
                texture angle 6144 and more)

Nothing else is kept: the capture's directory is deleted. Runs are
bounded (time, files) and under nice.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, \
    Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import rendercap as RC, routinecap as RCP  # noqa: E402
from ref816 import bounded, dumps, refimage, title  # noqa: E402

RUN_TIMEOUT = 600.0
CALL_TIMEOUT = 120.0
MAX_FILE = 64 << 20
RANGES = [(0x020000, 0x10000), (0x000900, 768), (0x0AB500, 1280),
          RC.FS_SPANS]
RECBANK = (0x1D0000, 0x10000)
SIZEOF_SEC, SIZEOF_SIDE, SIZEOF_DS = 58, 14, 42
OFS_SEG_SIDENUM, OFS_SEG_BACK = 12, 17
OFS_SIDE_ROWOFFSET, OFS_SIDE_MID = 6, 12
BSPDP = 0x000951
DP_STOP = 0x0009EB
MM_COLDIR = 0x250000


class SynthError(Exception):
    pass


class Spec(NamedTuple):
    name: str
    kind: str                   # 'wall' or 'seg': the routine --call runs
    pick: Callable              # (wall, Case) -> bool: a base call
    pokes: Callable             # (Memory, sym, Case, registers)
                                #   -> [(address, bytes)]


def u(mem: refimage.Memory, address: int, n: int) -> int:
    return int.from_bytes(mem.get(address, n), 'little')


def seg_address(mem: refimage.Memory) -> int:
    return u(mem, BSPDP, 3)


def side_address(mem, sym) -> int:
    return u(mem, sym.address('_g_sides'), 3) + SIZEOF_SIDE * u(
        mem, seg_address(mem) + OFS_SEG_SIDENUM, 2)


def back_address(mem, sym) -> int:
    back = mem.byte(seg_address(mem) + OFS_SEG_BACK)
    if back == 0xFF:
        raise SynthError('a one sided seg')
    return u(mem, sym.address('_g_sectors'), 3) + SIZEOF_SEC * back


def flags(case) -> Dict[str, int]:
    sle = case.points.get('SLE')
    if sle is None:
        return {}

    def w(o: int) -> int:
        return int.from_bytes(sle.get(0x000A00 + o, 2), 'little')
    return {'mc': w(0xC0), 'mf': w(0xC2), 'mid': w(0xC6), 'top': w(0xC8),
            'bot': w(0xCA), 'masked': w(0xCC), 'segtex': w(0xC4),
            'x': sle.header['cpu']['a'] & 0xFFFF,
            'stopx': int.from_bytes(sle.get(0x02AE70, 2), 'little')}


SEGVAR = {2, 4, 5, 6, 7, 8, 10, 12, 13, 14, 15, 20, 28}


def kind_of(f: Dict[str, int]) -> int:
    if f['masked']:
        return 66 if not (f['mc'] or f['mf'] or f['top'] or f['bot']) \
            else 64
    k = (8 if f['mf'] else 0) + (4 if f['mc'] else 0)
    return k + (16 if f['mid'] else (2 if f['bot'] else 0) +
                (1 if f['top'] else 0))


# -- the specs' pokes --------------------------------------------------------

def poke_edgeslow(mem, sym, case, regs):
    back = back_address(mem, sym)
    floor = u(mem, back, 4)
    return [(back, ((floor & 0xFFFF0000) | 0x4000).to_bytes(4, 'little'))]


def poke_rowoffset(value: int):
    def pokes(mem, sym, case, regs):
        return [(side_address(mem, sym) + OFS_SIDE_ROWOFFSET,
                 (value & 0xFFFF).to_bytes(2, 'little'))]
    return pokes


def poke_vmask(mem, sym, case, regs):
    side = side_address(mem, sym)
    made = [t for t in range(1, 256)
            if mem.get(MM_COLDIR + 4 * t + 2, 2) != b'\0\0']
    if not made:
        raise SynthError('no texture made')
    return [(side + OFS_SIDE_MID, made[0].to_bytes(2, 'little'))]


def poke_closed(mem, sym, case, regs):
    f = flags(case)
    x = (f['x'] + f['stopx']) // 2
    return [(sym.address('floorclip') + 2 * x, b'\0\0')]


def poke_onecol(mem, sym, case, regs):
    return [(DP_STOP, (regs.a & 0xFFFF).to_bytes(2, 'little'))]


def poke_dsfull(mem, sym, case, regs):
    full = (sym.address('_s_drawsegs') + 128 * SIZEOF_DS) & 0xFFFF
    return [(sym.address('ds_p'), full.to_bytes(2, 'little')),
            (0x0AB600, (128).to_bytes(2, 'little'))]


def poke_openfull(mem, sym, case, regs):
    last = sym.address('openings') + 2 * 2500
    return [(sym.address('lastopening'), last.to_bytes(3, 'little'))]


def poke_negsine(angleb: int, at: str = 'first'):
    """viewangle16 such that angleb = ANG90 + xtoviewangle[x] +
    viewangle16 - rw_normalangle is `angleb` at the wall's first column x
    (`at` 'first') or its last (R_StoreWallRange's stop, 'last'): a sine
    there is negative, so scaleFast bails out (the old way), and
    scaleSlow's sineLow reads below its table (r_iigs65.s:535-542).
    angleb falls from column to column (xtoviewangle does), so -8 at the
    first column puts the whole wall behind, $8008 there only that column,
    and -8 at the last only the last."""
    def pokes(mem, sym, case, regs):
        start = regs.a & 0xFFFF
        col = start if at == 'first' else u(mem, DP_STOP, 2)
        xtv = u(mem, sym.address('xtoviewangleTable') + 2 * col, 2)
        normal = u(mem, seg_address(mem) + 10, 2)
        view = (angleb - 0x4000 - xtv + normal) & 0xFFFF
        return [(sym.address('viewangle16'), view.to_bytes(2, 'little'))]
    return pokes


def poke_segearly(mem, sym, case, regs):
    """rw_stopx = rw_x: R_RenderSegLoop returns at once."""
    return [(sym.address('rw_stopx'), (regs.a & 0xFFFF).to_bytes(2,
                                                                 'little'))]


def poke_fsgeneral(mem, sym, case, regs):
    """rw_scale and the drawseg's scale1 (R_StoreWallRange sets both to
    the same: the native seg descriptor has one of them) at 80.0."""
    scale = (0x00500000).to_bytes(4, 'little')
    ds = 0x020000 | u(mem, sym.address('ds_p'), 2)
    return [(sym.address('rw_scale'), scale), (ds + 8, scale)]


def pick_kind(kinds, least_columns: int = 1, **need):
    def pick(w, case) -> bool:
        f = flags(case)
        if not f or kind_of(f) not in kinds:
            return False
        if f['stopx'] - f['x'] < least_columns:
            return False
        return all(bool(f[k]) == v for k, v in need.items())
    return pick


_HEIGHTS: Dict[str, Dict[str, int]] = {}


def height_of_mid(case) -> int:
    """The height of the seg loop's mid texture (its level's)."""
    from native import framestate as FS
    frame = case.header['frame']
    if frame not in _HEIGHTS:
        level = FS.level_of(FS.Frame(RC.FRAMES / frame), dumps.symbols())
        info = json.loads((level / 'level.json').read_text())
        _HEIGHTS[frame] = {t: v['height'] for t, v in
                           info['textures'].items()}
    return _HEIGHTS[frame].get(str(flags(case)['mid']), 0)


def pick_mod16(w, case) -> bool:
    """A single sided wall whose texture's height is not a power of 2."""
    if not pick_kind({28}, 8)(w, case):
        return False
    h = height_of_mid(case)
    return h > 0 and h & (h - 1) != 0


SPECS = (
    Spec('edgeslow', 'wall', pick_kind(SEGVAR, bot=True), poke_edgeslow),
    Spec('mod16', 'wall', pick_mod16, poke_rowoffset(45)),
    Spec('mod16neg', 'wall', pick_mod16, poke_rowoffset(-45)),
    Spec('vmask', 'wall', pick_kind({0}, 4), poke_vmask),
    Spec('closed', 'wall', pick_kind(SEGVAR, 3), poke_closed),
    Spec('onecolslow', 'wall', lambda w, c: 'scaleSlow' in w['paths'],
         poke_onecol),
    Spec('dsfull', 'wall', lambda w, c: True, poke_dsfull),
    Spec('openfull', 'wall', pick_kind(set(range(67)), 40), poke_openfull),
    Spec('fsgeneral', 'seg', pick_kind(SEGVAR, 4, segtex=True),
         poke_fsgeneral),
    Spec('segearly', 'seg', pick_kind(SEGVAR, 1), poke_segearly),
    # (a wall without a texture: its seg loop, from upstream's scales,
    # stays in the tables)
    Spec('negsine', 'wall', pick_kind({4, 8, 12}, 16), poke_negsine(-8)),
    Spec('grazefirst', 'wall', pick_kind({28}, 24),
         poke_negsine(0x8008, 'first')),
    Spec('grazelast', 'wall', pick_kind({28}, 24),
         poke_negsine(-8, 'last')),
)


# ---------------------------------------------------------------------------
# The machine
# ---------------------------------------------------------------------------

def capture_entry(spec_run: RC.RunSpec, routine: int, hit: int, sym,
                  work: Path) -> refimage.Image:
    """All RAM at call `hit` of `routine` in the run (ref816 --capture)."""
    prog = RC.program(spec_run, sym, work)
    (work / 'input.txt').write_text(prog)
    cap = work / 'capture'
    cap.mkdir()
    extra = ['--capture', str(cap), '--capture-entry', '%06X' % routine,
             '--capture-hit', str(hit)]
    command = RC.machine_command(work / 'input.txt', work, sym,
                                 RC.limit_seconds(spec_run), extra)
    result = bounded.run(['nice', '-n', '10'] + command,
                         timeout=RUN_TIMEOUT, max_bytes=MAX_FILE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         universal_newlines=True)
    if result.returncode:
        raise SynthError('the capture failed: %s' % result.stderr[-1000:])
    entry = cap / ('hit-%08d' % hit) / 'entry.img'
    if not entry.exists():
        raise SynthError('no capture of call %d' % hit)
    return refimage.read(entry)


def call(image: Path, pokes: Optional[Path], routine: int,
         stop: Optional[int], with_records: bool, work: Path
         ) -> Tuple[Dict, dumps.Dump]:
    """ref816 --call of `routine` on the image and the pokes (stopped at
    `stop` when given): the final state, and the saved ranges as one
    dump."""
    command = ['nice', '-n', '10', str(title.MACHINE), str(image)]
    if pokes is not None:
        command += ['--load-image', str(pokes)]
    ranges = list(RANGES) + ([RECBANK] if with_records else [])
    files = []
    for k, (address, length) in enumerate(ranges):
        path = work / ('save-%d.bin' % k)
        files.append(path)
        command += ['--save', '%06X:0x%X:%s' % (address, length, path)]
    command += ['--call', '%06X' % routine, '--cycles', '400000000']
    if stop is not None:
        command += ['--stop-pc', '%06X' % stop]
    result = bounded.run(command, timeout=CALL_TIMEOUT, max_bytes=MAX_FILE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         universal_newlines=True)
    if result.returncode:
        raise SynthError('--call failed (%d): %s' % (result.returncode,
                                                     result.stderr[-1000:]))
    state = json.loads(result.stdout)
    data = b''.join(p.read_bytes() for p in files)
    for p in files:
        p.unlink()
    header = {'cpu': registers_of(state), 'cycles': state.get('cycles', 0),
              'ranges': [list(r) for r in ranges], 'bytes': len(data)}
    return state, dumps.Dump(header, data)


def registers_of(state: Dict) -> Dict[str, int]:
    """The registers at the end of a run (ref816's final state)."""
    for key in ('cpu', 'registers'):
        if isinstance(state.get(key), dict):
            return state[key]
    raise SynthError('the final state has no registers: %s'
                     % sorted(state))


def image_dump(mem: refimage.Memory, registers) -> dumps.Dump:
    data = b''.join(mem.get(a, n) for a, n in RANGES)
    return dumps.Dump({'cpu': dict(registers._asdict()), 'cycles': 0,
                       'ranges': [list(r) for r in RANGES],
                       'bytes': len(data)}, data)


def write_case(out: Path, header: Dict, points: Dict[str, dumps.Dump]
               ) -> Path:
    order = [k for k in ('SWE', 'SLE', 'SLR', 'SWR') if k in points]
    n = sum(size for _, size in RANGES)
    chain = [points[k].data[:n] for k in order]
    blob = [chain[0]] + [RCP.xor(chain[i], chain[i - 1])
                         for i in range(1, len(chain))]
    rec = points[order[-1]].get(*RECBANK)
    header = dict(header, format=RCP.FORMAT,
                  ranges=[list(r) for r in RANGES], order=order,
                  cpu={k: points[k].header['cpu'] for k in order},
                  cycles={k: points[k].header['cycles'] for k in order})
    data = json.dumps(header, separators=(',', ':')).encode() + b'\n' + \
        b''.join(blob) + rec
    if out.exists():
        shutil.rmtree(str(out))
    out.mkdir(parents=True)
    path = out / 'w00.case.z'
    path.write_bytes(zlib.compress(data, 6))
    return path


# ---------------------------------------------------------------------------
# One spec
# ---------------------------------------------------------------------------

def base_walls() -> List[Dict[str, Any]]:
    index = json.loads((RCP.ROUTINES / 'index.json').read_text())
    out = []
    for spec in RC.RUNS:
        run = index.get(spec.key, {})
        for w in run.get('walls', []):
            out.append(dict(w, run=spec.key, sites=run['sites']))
    return out


def make_one(spec: Spec, sym, work: Path) -> Dict[str, Any]:
    base = None
    for w in base_walls():
        path = RCP.ROUTINES / w['frame'] / ('w%02d.case.z' % w['k'])
        case = RCP.load_case(path)
        if spec.pick(w, case):
            base = (w, case)
            break
    if base is None:
        raise SynthError('no captured call to start from')
    w, case = base
    run = next(r for r in RC.RUNS if r.key == w['run'])
    routine = sym.address('R_StoreWallRange' if spec.kind == 'wall'
                          else 'R_RenderSegLoop')
    hit = w['hit'] if spec.kind == 'wall' else w['sl_hit']
    first = 'SWE' if spec.kind == 'wall' else 'SLE'
    image = capture_entry(run, routine, hit, sym, work)
    mem = refimage.Memory(image.records)
    if mem.get(0x020000, 0x10000) != case.points[first].get(0x020000,
                                                           0x10000):
        raise SynthError('the capture is not the captured call')
    pokes = spec.pokes(mem, sym, case, image.registers)
    for address, data in pokes:
        mem.put(address, data)
    entry_path = work / 'entry.img'
    entry_path.write_bytes(refimage.image_bytes(image.registers,
                                                image.switches,
                                                image.records))
    poke_path = None
    if pokes:
        poke_path = work / 'pokes.img'
        poke_path.write_bytes(refimage.image_bytes(
            image.registers, image.switches,
            [(a, bytes(d)) for a, d in pokes]))
    points = {first: image_dump(mem, image.registers)}
    state, last = call(entry_path, poke_path, routine, None, True, work)
    if state['end']['reason'] != 'return':
        raise SynthError('--call ended with %s' % state['end']['reason'])
    points['SWR' if spec.kind == 'wall' else 'SLR'] = last
    if spec.kind == 'wall':
        sl = sym.address('R_RenderSegLoop')
        st, sle = call(entry_path, poke_path, routine, sl, False, work)
        if st['end']['reason'] == 'stop-pc':
            points['SLE'] = sle
            st, slr = call(entry_path, poke_path, routine, w['sites']['sl'],
                           False, work)
            if st['end']['reason'] != 'stop-pc':
                raise SynthError('no seg loop return')
            points['SLR'] = slr
    header = {'frame': w['frame'], 'k': w['k'], 'hit': w['hit'],
              'sl_hit': w['sl_hit'] if 'SLE' in points else 0,
              'start': image.registers.a & 0xFFFF if spec.kind == 'wall'
              else w['start'], 'flushed': False,
              'synthetic': spec.name, 'kind': spec.kind,
              'pokes': [[a, bytes(d).hex()] for a, d in pokes]}
    path = write_case(RCP.ROUTINES / ('synth-' + spec.name), header, points)
    return {'spec': spec.name, 'base': '%s/w%02d' % (w['frame'], w['k']),
            'pokes': header['pokes'], 'points': sorted(points),
            'case': str(path)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--specs', default=','.join(s.name for s in SPECS))
    args = parser.parse_args(argv)
    wanted = args.specs.split(',')
    specs = [s for s in SPECS if s.name in wanted]
    if len(specs) != len(wanted):
        parser.error('unknown spec in %s' % args.specs)
    if not (RCP.ROUTINES / 'index.json').exists():
        print('no routine captures: run python3 tools/native/routinecap.py',
              file=sys.stderr)
        return 1
    title.build_machine()
    title.ensure_image()
    sym = dumps.symbols()
    RC.check_disk(RCP.ROUTINES)
    failed = 0
    report = {}
    for spec in specs:
        work = Path(tempfile.mkdtemp(prefix='tmp-render-synth-',
                                     dir=str(RC.make_image.BUILD)))
        try:
            res = make_one(spec, sym, work)
            report[spec.name] = res
            print('%-11s from %s, pokes %s, %s' % (
                res['spec'], res['base'], res['pokes'],
                ','.join(res['points'])))
        except (SynthError, RCP.CaptureError) as error:
            print('%-11s FAILED: %s' % (spec.name, error))
            failed += 1
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    path = RCP.ROUTINES / 'synth.json'
    old = json.loads(path.read_text()) if path.exists() else {}
    old.update(report)
    path.write_text(json.dumps(old, indent=1) + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
