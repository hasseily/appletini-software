#!/usr/bin/env python3
"""Synthetic frames for the paths of the frame that no capture reaches
(milestone 7, stage C; docs/RENDER.md 4.1 "Synthetic cases", 5.3), with
upstream's truth from ref816 --call.

Usage:  python3 tools/native/framesynth.py [--specs a,b,...]

Each synthetic frame starts from a captured frame (tools/native/
rendercap.py): its run goes on ref816 again to that frame's R_FillStamps,
which --capture records whole (all RAM and the registers at the entry;
the machine is deterministic, and the capture's bank $02 must equal the
frame's P0). The spec's pokes change that state; then --call runs the
frame from display's JSL to R_FillStamps (the capture's return address
less 3, with S above it) on the changed state, once for each of
rendercap's points, stopped there: R_FillStamps (P0), the return of
weaponClip in weaponClipSame (P1, the seam), R_RenderBSPNode (P0b) and
drawMasked (P3), each saving rendercap.py's ranges of the point. A run
that reaches drawAllL (an early flush) first is refused. The result is a
frame directory of rendercap.py's format, build/native/render/frames/
synth-NAME/, whose frame.json names the base frame, the spec and its
pokes; calls.json has no calls: --call cannot run with ref816's call log,
so a synthetic frame has neither checkpoint A's wall calls nor the count
of vertex angles (render_check.py leaves both out for it).

The specs (SPECS): what the captures miss (render_check.py
--frame-mode's coverage):

    noweapon    no weapon (the psprite's state 0): weaponClipSame's "no
                weapon" (WPREV's lump $FFFF, no skip)
    shadow      the invisibility power: the shadow weapon (FR_VIS has no
                colormap)
    automap     the automap overlay (automapmode AM_ACTIVE | AM_OVERLAY,
                viewbottom AM_TITLEY as display sets it): no weapon skip,
                the view's row after it changes (W_BOTR: no old spans),
                the clips of the shorter view
    skyfixed    the fixed colormap 1 (the light amplification visor) on a
                frame with sky walls: the sky's colormap page (no capture
                has both)
    fsfill      W_FSC 127: the 128-frame refresh of the span stamps
                (fsFill; one captured frame does it at 0)
    fswrap      W_FSC 255: the stamp wraps to 0 and refreshes
    flat        a third of every made texture's columns without a patch
                (the top byte of its column entry 1): tierFlat, a K_FILL
                of the texture's colour with its span cut; the level is
                converted again from the frame's level source with the
                same pokes (levels/src/synth-flat-SRC)
    flatsky     the same on a frame with sky walls
    flatv06, flatv14
                the same on frames with loops of kind 6 and 14 (a bottom
                wall under a ceiling, no top wall), where upstream's
                tierFlat leaves DC_ROW (the row of the ceiling clip) at the
                tier's first row
    skyodd      the player's angle with the low 6 bits of its high word
                63 on a frame with sky walls: the captured angles are
                multiples of 64 (keyboard, demo) and xtoviewangle's of 8,
                so no capture shows a sky column one angle unit off; the
                game reaches such angles (the death view turns by ANG5 or
                to the attacker, p_user65.s:578-650)

Runs are bounded (time, files) and under nice.
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

from native import rendercap as RC, routinesynth as RS  # noqa: E402
from ref816 import bounded, dumps, refimage, title  # noqa: E402

CALL_TIMEOUT = 300.0
MAX_FILE = 64 << 20
MM_COLDIR = 0x250000
OFS_PL_POWERS, PW_INVISIBILITY = 41, 2
OFS_PL_PSPRITES = 129
OFS_PL_FIXEDCOLORMAP = 127
OFS_PL_MO, OFS_MO_ANGLE = 0, 32         # framestate.py's
AM_ACTIVE_OVERLAY = 3
AM_TITLEY = 168 - 1 - 7
WPAGE = 0x000A00
W_FSC = 0xE8


class SynthError(Exception):
    pass


class Spec(NamedTuple):
    name: str
    base: str                   # the captured frame it starts from
    pokes: Callable             # (Memory, sym) -> [(address, bytes)]
    level: bool                 # the pokes change the level: convert a
                                #   level source with them


# -- the specs' pokes --------------------------------------------------------

def poke_noweapon(mem, sym):
    return [(sym.address('_g_player') + OFS_PL_PSPRITES, bytes(4))]


def poke_shadow(mem, sym):
    return [(sym.address('_g_player') + OFS_PL_POWERS + 2 * PW_INVISIBILITY,
             (1000).to_bytes(2, 'little'))]


def poke_automap(mem, sym):
    return [(sym.address('automapmode'),
             AM_ACTIVE_OVERLAY.to_bytes(2, 'little')),
            (sym.address('viewbottom'), AM_TITLEY.to_bytes(2, 'little'))]


def poke_fixed(mem, sym):
    """The light amplification visor's colormap (1) for the player: the
    sky's records take the fixed colormap's page."""
    return [(sym.address('_g_player') + OFS_PL_FIXEDCOLORMAP,
             (1).to_bytes(2, 'little'))]


def poke_angle_low(low6: int):
    """The player's mobj angle with bits 16-21 (the low 6 bits of
    viewangle16) set to low6: (viewangle >> 16) + xtoviewangle[x] then has
    all six bits below the sky's texel column set for some columns."""
    def pokes(mem, sym):
        mo = int.from_bytes(mem.get(sym.address('_g_player') + OFS_PL_MO,
                                    3), 'little')
        angle = int.from_bytes(mem.get(mo + OFS_MO_ANGLE, 4), 'little')
        angle = (angle & ~(0x3F << 16)) | (low6 << 16)
        return [(mo + OFS_MO_ANGLE, angle.to_bytes(4, 'little'))]
    return pokes


def poke_fsc(value: int):
    def pokes(mem, sym):
        return [(WPAGE + W_FSC, bytes([value]))]
    return pokes


def poke_flat(mem, sym):
    """Every made texture's columns c with c % 3 == 1: the top byte of the
    column entry 1 (upstream's "no patch", r_seg65.s:1509; TIER's test is
    the entry's high word >= $0100)."""
    out = []
    for t in range(256):
        entry = mem.get(MM_COLDIR + 4 * t, 4)
        if entry[2] == 0 and entry[3] == 0:
            continue
        table = entry[0] | entry[1] << 8 | entry[2] << 16
        for c in range(entry[3] + 1):
            if c % 3 == 1:
                out.append((table + 4 * c + 3, b'\x01'))
    if not out:
        raise SynthError('no texture made')
    return out


SPECS = (
    Spec('noweapon', 'still-2', poke_noweapon, False),
    Spec('shadow', 'still-2', poke_shadow, False),
    Spec('automap', 'newgame-10', poke_automap, False),
    Spec('skyfixed', 'tour-46', poke_fixed, False),
    Spec('fsfill', 'still-1', poke_fsc(127), False),
    Spec('fswrap', 'demo-10', poke_fsc(255), False),
    Spec('flat', 'still-1', poke_flat, True),
    Spec('flatsky', 'newgame-18', poke_flat, True),
    Spec('flatv06', 'demo-10', poke_flat, True),
    Spec('flatv14', 'title-14', poke_flat, True),
    Spec('skyodd', 'tour-46', poke_angle_low(63), False),
)


# ---------------------------------------------------------------------------
# The machine
# ---------------------------------------------------------------------------

def parse_ranges(text: str) -> List[Tuple[int, int]]:
    """rendercap.ranges_of's text as (address, length) pairs."""
    out = []
    for item in text.split('+'):
        if ':' in item:
            address, length = item.split(':')
            out.append((int(address, 16), int(length)))
        elif '-' in item:
            first, last = (int(x, 16) for x in item.split('-'))
            out.append((first << 16, (last - first + 1) << 16))
        else:
            out.append((int(item, 16) << 16, 0x10000))
    return out


def run_to(entry: Path, pokes: Optional[Path], start: int, s: int,
           stops: Sequence[int], ranges: List[Tuple[int, int]], work: Path
           ) -> Tuple[Dict, dumps.Dump]:
    """ref816 --call from `start` (S = s) on the image and the pokes,
    stopped at the first of `stops`: the final state and the ranges as
    one dump (its header's cpu: the registers there)."""
    command = ['nice', '-n', '10', str(title.MACHINE), str(entry)]
    if pokes is not None:
        command += ['--load-image', str(pokes)]
    files = []
    for k, (address, length) in enumerate(ranges):
        path = work / ('save-%d.bin' % k)
        files.append(path)
        command += ['--save', '%06X:0x%X:%s' % (address, length, path)]
    command += ['--reg', 's=%X' % s, '--call', '%06X' % start,
                '--cycles', '400000000']
    for stop in stops:
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
    header = {'cpu': RS.registers_of(state),
              'cycles': state.get('cycles', 0),
              'ranges': [list(r) for r in ranges], 'bytes': len(data)}
    return state, dumps.Dump(header, data)


def check_p0(d: dumps.Dump, base: dumps.Dump, pokes) -> None:
    """The run reaches R_FillStamps with the frame's state: its P0 equals
    the captured frame's, the pokes applied, in every range they share."""
    poked = refimage.Memory()
    for address, length in base.header['ranges']:
        poked.put(address, base.get(address, length))
    for address, data in pokes:
        if poked.is_known(address):
            poked.put(address, data)
    for address, length in d.header['ranges']:
        want = poked.get(address, length)
        got = d.get(address, length)
        if got != want:
            bad = next(i for i in range(length) if got[i] != want[i])
            raise SynthError('P0 differs from the frame\'s at $%06X'
                             % (address + bad))


def level_source(spec: Spec, base_src: str, pokes) -> str:
    """The frame's level source with the pokes (a new source, so a new
    conversion): its name."""
    name = 'synth-%s-%s' % (spec.name, base_src)
    ram = bytearray(RC.load_ram(RC.LEVEL_SOURCES / (base_src + '.ram.z')))
    for address, data in pokes:
        bank = address >> 16
        if bank >= 0x80:
            raise SynthError('a level poke outside banks $00-$7F')
        at = (bank << 16) | (address & 0xFFFF)
        ram[at:at + len(data)] = data
    (RC.LEVEL_SOURCES / (name + '.ram.z')).write_bytes(
        zlib.compress(bytes(ram), 6))
    info = json.loads((RC.LEVEL_SOURCES / (base_src + '.json')).read_text())
    info.update({'name': name, 'synthetic': spec.name, 'base': base_src,
                 'pokes': len(pokes)})
    (RC.LEVEL_SOURCES / (name + '.json')).write_text(
        json.dumps(info, indent=1) + '\n')
    return name


def make_one(spec: Spec, sym, work: Path) -> Dict[str, Any]:
    base_dir = RC.FRAMES / spec.base
    meta = json.loads((base_dir / 'frame.json').read_text())
    run = next(r for r in RC.RUNS if r.key == meta['run'])
    fs = sym.address('R_FillStamps')
    image = RS.capture_entry(run, fs, meta['frame']['fs_hit'], sym, work)
    mem = refimage.Memory(image.records)
    p0 = RC.load_dump(base_dir / 'p0.dump.z')
    if mem.get(0x020000, 0x10000) != p0.get(0x020000, 0x10000):
        raise SynthError('the capture is not the frame\'s R_FillStamps')
    regs = image.registers
    s = regs.s
    ret = int.from_bytes(mem.get(s + 1, 3), 'little')
    start = ret - 3                     # display's JSL R_FillStamps
    if mem.byte(start) != 0x22 or \
            int.from_bytes(mem.get(start + 1, 3), 'little') != fs:
        raise SynthError('the return address is not after a JSL '
                         'R_FillStamps')
    pokes = spec.pokes(mem, sym)
    entry_path = work / 'entry.img'
    entry_path.write_bytes(refimage.image_bytes(regs, image.switches,
                                                image.records))
    poke_path = work / 'pokes.img'
    poke_path.write_bytes(refimage.image_bytes(
        regs, image.switches, [(a, bytes(d)) for a, d in pokes]))
    out = RC.FRAMES / ('synth-' + spec.name)
    staging = work / 'frame'
    staging.mkdir()
    # each point is reached before an early flush (drawAllL), which
    # would refuse the spec
    flush = sym.address(RC.capture.FLUSH)
    cycles = {}
    for what, kind, where in (('p0', 'P0', fs),
                              ('p1', 'P1', sym.address('weaponClipSame') + 3),
                              ('p0b', 'P0b', sym.address('R_RenderBSPNode')),
                              ('p3', 'P3', sym.address('drawMasked'))):
        st, d = run_to(entry_path, poke_path, start, s + 3, (where, flush),
                       parse_ranges(RC.ranges_of(kind, sym)), work)
        if st['end']['reason'] != 'stop-pc':
            raise SynthError('%s: --call ended with %s' % (
                what, st['end']['reason']))
        if st['end']['pc'] != where:
            raise SynthError('%s: the frame flushes its lists early'
                             % what)
        if what == 'p0':
            check_p0(d, p0, pokes)
        RC.write_dump(staging / (what + '.dump.z'), d)
        cycles[what] = d.header['cycles']
    level_src = meta['level_src']
    if spec.level:
        level_src = level_source(spec, level_src, pokes)
    meta = dict(meta, name='synth-' + spec.name, set='synth',
                synthetic=spec.name, base=spec.base, level_src=level_src,
                flushes=0, call_cycles=cycles,
                pokes=[[a, bytes(d).hex()] for a, d in pokes])
    (staging / 'frame.json').write_text(json.dumps(meta, indent=1) + '\n')
    (staging / 'calls.json').write_text(json.dumps(
        {'storewall': [], 'vtxangle': None, 'textures': []}) + '\n')
    if out.exists():
        shutil.rmtree(str(out))
    shutil.move(str(staging), str(out))
    return {'spec': spec.name, 'base': spec.base, 'pokes': len(pokes),
            'level_src': level_src, 'frame': str(out)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--specs', default=','.join(s.name for s in SPECS))
    args = parser.parse_args(argv)
    wanted = args.specs.split(',')
    specs = [s for s in SPECS if s.name in wanted]
    if len(specs) != len(wanted):
        parser.error('unknown spec in %s' % args.specs)
    for s in specs:
        if not (RC.FRAMES / s.base / 'frame.json').exists():
            print('no frame %s: run python3 tools/native/rendercap.py'
                  % s.base, file=sys.stderr)
            return 1
    title.build_machine()
    title.ensure_image()
    sym = dumps.symbols()
    RC.check_disk(RC.FRAMES)
    failed = 0
    for spec in specs:
        work = Path(tempfile.mkdtemp(prefix='tmp-render-fsynth-',
                                     dir=str(RC.make_image.BUILD)))
        try:
            res = make_one(spec, sym, work)
            print('%-9s from %s, %d pokes%s' % (
                res['spec'], res['base'], res['pokes'],
                ', level source %s' % res['level_src']
                if spec.level else ''), flush=True)
        except (SynthError, RS.SynthError, RuntimeError) as error:
            print('%-9s FAILED: %s' % (spec.name, error), flush=True)
            failed += 1
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
