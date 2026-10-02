#!/usr/bin/env python3
"""Part s2ovl's checks (docs/SCREENS.md 0.1 F9, 1.5.4, 4.1, 4.5, 7.3;
docs/m11-parts/s2ovl.md): the automap's overlay, its K_OVL records and
the image OVLW, against upstream's frames of coverage/m11/automap.script
on ref816.

The truth is milestone 8's frame capture (tools/native/rendercap.py, its
points P0 .. P5) of automap.script's level frames, made here into this
part's build directory: every frame that draws the overlay (AM_Drawer
between drawMasked and R_DrawLists: its K_OVL records are in P4's lists,
its FSCUTE in P4's spans, its pixels in P5's screen) and some frames
without it (the frames before the map is turned on and after it is
turned off). The level's conversion (levelconv.py) of the run's level
source goes into this part's directory too.

The native side is milestone 8's whole frame (the objects of render.mk's
ftest, read only) linked with this part's driver src/native/s2_ovd.s
(the frame mode of rdriver.s's drv_fframe, with the overlay's step:
OVLW loaded by far_pload from its bank in MASKW's place after nm_masked,
then am_ovl, which ends by calling OVLW's nm_bkload), and the image OVLW
itself (src/native/s2_ovl.s, part s2amap's s2_amline.s, milestone 8's
rrec.s with -D MREC and bucket.s, linked alone into MASKW's code room
$6800-$9BFF with BKFAR and BKFAR2 as data: build/native/m11/s2ovl/
ovlw.*). The injected state is milestone 8's (framestate.py from P0)
and the automap's (the state block SS_AMAPW, the palette state SS_PALST
from the frame's start, the level's lines, sides and sectors in their
native banks, the player, message_on, the nibble tables).

Checks, each frame, both fills ($A5, $5A):
  - milestone 8's whole comparison (frame8.compare): the clip pass, the
    walk, the vissprites, the masked phase at the weapon, and at the
    staging's end every record of the frame by column in the order made
    (the view's then the K_OVL ones), the spans (FSCUTE: the fill spans'
    ends), the covered ranges, the page model (UPOFS against COLW,
    XPNEXT), the clips, the weapon skip, the clip log; the bucket pass's
    batches against milestone 5's loader;
  - the screen after the replay (aux 0 $2000-$9FFF) equal to P5 but rows
    160-167 (the title band): black when upstream's titleBand ran
    (am_band 0 at AM_Drawer), else their value;
  - the automap's state after OVLW (SS_AMAPW) equal to the reference's at
    R_DrawLists (P4) but am_valid, which display zeroes after R_DrawLists
    [R d_main65.s:503]: 0; S2_MAIL's MAIL_AMTITLE when titleBand ran;
  - the write log: no write outside each phase's allowed set (milestone
    8's front end, masked phase, bucket pass and replay; OVLW's: its room,
    its zero page, the records' batch and staging, the spans, the page
    model, its state block, the title band's rows, S2_MAIL); milestone 8's
    W outside $6800-$9BFF untouched by OVLW;
  - frames without the overlay: the same frame image, OVLW not loaded,
    the whole comparison unchanged.

Usage:
  python3 tools/native/s2ovl.py --capture       the reference (ref816)
  python3 tools/native/s2ovl.py --check [--jobs 2] [--fills a5,5a]
  python3 tools/native/s2ovl.py --planted [--jobs 2]
  python3 tools/native/s2ovl.py --timing [--jobs 2]
  python3 tools/native/s2ovl.py --sizes
  python3 tools/native/s2ovl.py --all [--jobs 2]   (everything:
                                    build/native/m11/s2ovl/report.json)
"""

import argparse
import bisect
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import llayout as LL, rlayout as R, s2layout as S  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
M11 = BUILD / 'native' / 'm11'
OUT = M11 / 's2ovl'
FRAMES = OUT / 'frames'
LEVELS = OUT / 'levels'
SOURCE = ROOT / 'src' / 'native'
SCRIPT = 'm11/automap'
RUN_KEY = 'm11ovl'
JOBS = 2
PLAIN_FRAMES = 4                # frames without the overlay, each side


class OvlError(Exception):
    pass


# ---------------------------------------------------------------------------
# The capture: milestone 8's frames of automap.script (rendercap.py's run,
# with this part's choice of frames and its own directories)
# ---------------------------------------------------------------------------

def _rendercap():
    """rendercap.py, its level sources and levelconv.py's conversions in
    this part's directory (module attributes of this process only: both
    files are milestone 8's, read only)."""
    from native import levelconv, rendercap as RCAP
    RCAP.LEVEL_SOURCES = LEVELS / 'src'
    levelconv.LEVELS = LEVELS
    levelconv.SOURCES = LEVELS / 'src'
    return RCAP


def _marks_at(log, address: int) -> List[int]:
    name = '%06X' % address
    return [e.cycles for e in log if e.kind == 'mark' and e.what == name]


def choose_frames(RCAP, log, frames, r: Dict[str, int]
                  ) -> Dict[str, List[Any]]:
    """The overlay frames (AM_Drawer between drawMasked and R_DrawLists:
    display's overlay call [R d_main65.s:491-496]) and PLAIN_FRAMES
    usable frames without it before the first and after the last."""
    am = sorted(_marks_at(log, r['am']))
    dl = _marks_at(log, r['dl'])
    level = [f for f in frames[:-1] if RCAP.usable(f)]
    ovl, plain = [], []
    for f in level:
        end = dl[f.dl_hit - 1]
        k = bisect.bisect_right(am, f.dm_cycles)
        (ovl if k < len(am) and am[k] < end else plain).append(f)
    if not ovl:
        raise OvlError('no frame of %s draws the overlay' % SCRIPT)
    lo, hi = ovl[0].index, ovl[-1].index
    if [f.index for f in ovl] != [f.index for f in level
                                  if lo <= f.index <= hi]:
        raise OvlError('the overlay frames are not one run of frames')
    before = [f for f in plain if f.index < lo][-PLAIN_FRAMES:]
    after = [f for f in plain if f.index > hi][:PLAIN_FRAMES]
    return {'ovl': ovl, 'plain': before + after}


def capture(jobs: int = JOBS) -> Dict[str, Any]:
    """The frames into FRAMES (rendercap's two runs of the script, the
    first choosing, the second capturing), the level source into
    LEVELS/src."""
    from ref816 import dumps, title, make_image
    RCAP = _rendercap()
    for path in (make_image.RELEASE_IMAGE, make_image.LINKMAP):
        if not path.exists():
            raise OvlError('%s is missing (MILESTONES.md "Setting up")'
                           % path)
    title.build_machine()
    title.ensure_image()
    symbols = dumps.symbols()
    am_drawer = symbols.address('am_map65.s:AM_Drawer')
    routines = RCAP.routines
    marked = RCAP.MARKED
    choose = RCAP.choose

    def routines_am(s):
        out = routines(s)
        out['am'] = am_drawer
        return out

    def choose_ovl(spec, log, frames, r):
        if spec.key != RUN_KEY:
            return choose(spec, log, frames, r)
        return choose_frames(RCAP, log, frames, r)
    RCAP.routines = routines_am
    RCAP.MARKED = marked + ('am',)
    RCAP.choose = choose_ovl
    try:
        if FRAMES.exists():
            shutil.rmtree(str(FRAMES))
        FRAMES.mkdir(parents=True)
        (LEVELS / 'src').mkdir(parents=True, exist_ok=True)
        spec = RCAP.RunSpec(RUN_KEY, SCRIPT, None, ('ovl', 'plain'))
        with open(str(OUT / 'capture.log'), 'w') as log_file:
            res = RCAP.run_one(spec, symbols, FRAMES, log_file)
    finally:
        RCAP.routines, RCAP.MARKED, RCAP.choose = routines, marked, choose
    (OUT / 'capture.json').write_text(json.dumps(res, indent=1) + '\n')
    return res


def frame_dirs() -> List[Path]:
    if not (OUT / 'capture.json').exists():
        raise OvlError('no capture: python3 tools/native/s2ovl.py --capture')
    return sorted(d for d in FRAMES.iterdir()
                  if (d / 'frame.json').exists())


# ---------------------------------------------------------------------------
# Request S2OVL-1 (applied in wave 7): s2_amline.s's fast path's hook,
# assembled into OVLW with -D AM_FASTLINE (src/native/m11/s2ovl.mk)
# ---------------------------------------------------------------------------

# the hook's texts, each in part s2amap's s2_amline.s exactly once
AMLINE_HOOKS = (
    """        .import am_seg, am_plot, am_rowcol
.ifdef AM_FASTLINE
        .import am_fastsetup, am_fastline   ; (OVLW's: request S2OVL-1)
        .export toscreen, clipscr
.endif
""",
    """        jsr wallrot
.ifdef AM_FASTLINE
        jsr am_fastsetup        ; fastSetup [R am_map65.s:1665-1670]
.endif
:       stz AMI
""",
    """@draw:  sta COLI
.ifdef AM_FASTLINE
        jsr am_fastline         ; the rotation's fast turn: C = 1 drawn
        bcs @next               ;   [R am_map65.s:1771-1779]
.endif
        jsr slowline
""",
)


def amline_problems(source: Path = SOURCE) -> List[str]:
    """s2_amline.s has the fast path's hook (request S2OVL-1), each part
    once."""
    text = (source / 's2_amline.s').read_text()
    return ['s2_amline.s: the hook of S2OVL-1 is there %d times: %r'
            % (text.count(h), h.splitlines()[0])
            for h in AMLINE_HOOKS if text.count(h) != 1]


# ---------------------------------------------------------------------------
# OVLW's link map: MASKW's code room, the frame image's symbols
# ---------------------------------------------------------------------------

# what OVLW's objects import from the frame image (the far layer, the
# math, the replay that bucket.s's BKFAR calls); ld65 fails on any other
OVLW_IMPORTS = ('far_get', 'far_put', 'fixmul', 'mul32', 'fixmulang',
                'recip', 'umul16', 'umul16lo', 'sdiv16', 'sineapprox',
                'cosineapprox', 'nat_replay')
OVLW_RT = 0x9400                # its run time places (s2_ovl.s's NBUF ..)


def read_labels(path: Path) -> Dict[str, int]:
    out = {}
    for line in Path(path).read_text().splitlines():
        f = line.split()
        if len(f) == 3 and f[0] == 'al':
            out[f[2].lstrip('.')] = int(f[1], 16)
    return out


def ovlw_cfg_text(labels: Dict[str, int], planted_bkfar: bool = False
                  ) -> str:
    """ld65's map of OVLW: its stored bytes from $6800 to its run time
    places, BKFAR and BKFAR2 as data run at their main places, bucket.s's
    card part where the frame image has it (only its addresses matter:
    BKFAR calls it), the frame's symbols. planted_bkfar: the planted bug
    of nm_bkload copying BKFAR from MASKW's address (the frame image's
    __BKFAR_LOAD__) instead of OVLW's."""
    lo = S.IMAGE['OVLW'].stored[0]
    near = labels['__BKNEAR_LOAD__']
    lines = [
        '# Generated by tools/native/s2ovl.py --ovlw-cfg (part s2ovl, '
        'docs/m11-parts/s2ovl.md):',
        '# the image OVLW in MASKW\'s code room. Do not edit.',
        'MEMORY {',
        '    OVW:   start = $%04X, size = $%04X, file = "%%O.ovw";' % (
            lo, OVLW_RT - lo),
        '    BFAR:  start = $%04X, size = $%04X, file = "";' % (
            R.BKFAR_RUN, R.BKFAR_END - R.BKFAR_RUN),
        '    BFAR2: start = $%04X, size = $%04X, file = "";' % (
            R.BKFAR2_RUN, R.BKFAR2_END - R.BKFAR2_RUN),
        '    RCX:   start = $%04X, size = $%04X, file = "";' % (
            near, 0xFF00 - near),
        '}',
        'SEGMENTS {',
        '    OVLHEAD: load = OVW, type = ro;',
        '    S2CODE:  load = OVW, type = ro, define = yes;',
        '    MASKW:   load = OVW, type = rw, define = yes;',
        '    BKFAR:   load = OVW, run = BFAR, type = ro%s;' % (
            '' if planted_bkfar else ', define = yes'),
        '    BKFAR2:  load = OVW, run = BFAR2, type = ro, define = yes;',
        '    BKNEAR:  load = RCX, type = ro, define = yes;',
        '    BKCARD:  load = RCX, type = ro, optional = yes;',
        '}',
        'SYMBOLS {']
    for name in OVLW_IMPORTS:
        lines.append('    %s: type = export, value = $%04X;' % (
            name, labels[name]))
    if planted_bkfar:
        for k in ('LOAD', 'RUN', 'SIZE'):
            n = '__BKFAR_%s__' % k
            lines.append('    %s: type = export, value = $%04X;' % (
                n, labels[n]))
    lines += ['}', '']
    return '\n'.join(lines)


def write_ovlw_cfg(lbl: Path, out: Path, planted_bkfar: bool = False
                   ) -> None:
    text = ovlw_cfg_text(read_labels(lbl), planted_bkfar)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.read_text() == text:
        return
    tmp = out.with_name(out.name + '.tmp')
    tmp.write_text(text)
    tmp.replace(out)


# K_OVL in milestone 8's record walks (rcanon.py: request S2OVL-2, applied
# in wave 7)
K_OVL = 10
OVL_NATIVE = 5                  # K_OVL, the column, the row, keep, colour


# ---------------------------------------------------------------------------
# The builds
# ---------------------------------------------------------------------------

def make(m11: Path = M11, source: Path = SOURCE,
         variables: Sequence[str] = ()) -> None:
    from ref816 import bounded
    res = bounded.run(['nice', '-n', '10', 'make', '-s', '-C', str(source),
                       '-f', 'm11.mk', 'part', 'P=s2ovl', 'M11=%s' % m11,
                       'ROOT=%s' % ROOT] + list(variables), timeout=600,
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      universal_newlines=True)
    if res.returncode:
        raise OvlError('the build failed:\n' + res.stdout[-4000:])
    if 'arning' in res.stdout:
        raise OvlError('the build warns:\n' + res.stdout[-4000:])


class Ovlw(NamedTuple):
    data: bytes                 # its stored bytes from $6800
    labels: Dict[str, int]
    segments: Dict[str, Tuple[int, int]]   # run addresses, inclusive
    loads: Dict[str, int]       # load address of each segment
    runs: bytes                 # far_pload's page runs (and the 0)


def load_ovlw(obj: Path = OUT, name: str = 'ovlw') -> Ovlw:
    import re
    data = (obj / (name + '.ovw')).read_bytes()
    labels = read_labels(obj / (name + '.lbl'))
    text = (obj / (name + '.map')).read_text()
    segs, loads = {}, {}
    for m in re.finditer(r'^(\w+)\s+([0-9A-F]{6})\s+([0-9A-F]{6})\s+'
                         r'([0-9A-F]{6})', text, re.M):
        segs[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16))
    for s in segs:
        k = '__%s_LOAD__' % s
        loads[s] = labels.get(k, segs[s][0])
    lo = S.IMAGE['OVLW'].stored[0]
    pages = (len(data) + 255) // 256
    if lo + len(data) > OVLW_RT:
        raise OvlError('OVLW\'s stored bytes reach $%04X, its run time '
                       'places start at $%04X' % (lo + len(data), OVLW_RT))
    return Ovlw(data, labels, segs, loads, bytes([lo >> 8, pages, 0]))


def frame_build(obj: Path = OUT, name: str = 'ovf'):
    from native import render_check as RC
    return RC.load_build(obj, name)


# ---------------------------------------------------------------------------
# A frame: milestone 8's case and the automap's injected state
# ---------------------------------------------------------------------------

class DumpRef:
    """A rendercap dump as s2amap's Ref (get, word, sym)."""

    def __init__(self, d):
        self.d = d

    def get(self, address: int, length: int) -> bytes:
        return self.d.read(address, length)

    def word(self, address: int, size: int = 2) -> int:
        return int.from_bytes(self.get(address, size), 'little')

    def sym(self, name: str, size: int = 2) -> int:
        from native import s2amap as A
        return self.word(A.sym(name), size)

    def sym_bytes(self, name: str, size: int) -> bytes:
        from native import s2amap as A
        return self.get(A.sym(name), size)


class OvlCase(NamedTuple):
    name: str
    overlay: bool
    f8: Any                     # frame8.F8Case (its final truth with K_OVL)
    state_in: Optional[Dict[int, int]]  # the automap's state injected (None:
                                #   P0's), by upstream's addresses
    tics: int                   # am_ovl's A
    titleband: bool             # upstream's titleBand runs in the frame
    state_after: Dict[str, int]  # the automap's state at P4 (upstream's)
    variant: str                # '' or what was injected, and why
    counts: Dict[str, int]


NIBTAB_UP = 0x0B8000            # am_map65.s NIBTAB (MM_NIBTAB)
NIBTAB_SIZE = 0x4000


def level_ptrs(p0: DumpRef):
    from native import s2amap as A
    v = [p0.word(A.sym(n), z) for n, z in A.LEVEL_PTRS]
    return A.Level(v[0] & 0xFFFFFF, v[1], v[2] & 0xFFFFFF, v[3],
                   v[4] & 0xFFFFFF, v[5], v[6] & 0xFFFFFF)  # (player.mo)


_PD0: Dict[str, Any] = {}
_LOCK = __import__('threading').Lock()


def frame_start(cycles: int):
    """The palette state at the start of the frame whose R_FillStamps is
    at `cycles` (before display's I_ViewPalette): part s2cap's case of
    automap.script whose PD0 .. PD1 holds it (the same deterministic run
    of the script)."""
    from native import s2cap as C
    with _LOCK:
        if 'rc' not in _PD0:
            _pd0_open(C)
    hits = [e for e in _PD0['frames'] if e['cycles'][0] < cycles <
            e['cycles'][1]]
    if len(hits) != 1:
        raise OvlError('%d of s2cap\'s automap frames hold cycle %d'
                       % (len(hits), cycles))
    with _LOCK:
        return hits[0]['name'], _PD0['rc'].load(hits[0]).before


def _pd0_open(C) -> None:
    root = C.run_dir('automap')
    if not (root / 'index.json').exists():
        raise OvlError('%s is missing: python3 tools/native/s2cap.py '
                       '--capture --runs automap' % root)
    rc = C.RunCases(root)
    _PD0['rc'] = rc
    _PD0['frames'] = list(rc.index['frames'])


def automap_records(f8, sym, fill: int,
                    state_in: Optional[Dict[int, int]] = None
                    ) -> Tuple[List[Tuple[int, int, int, bytes]],
                               Dict[str, Any]]:
    """The automap's state for OVLW (part s2amap's native forms of it):
    the state block from P0 (after the frame's tics, as at AM_Drawer), the
    palette state from the frame's start (s2cap's PD0: scb, viewpal), the
    level's lines, sides and sectors in their native banks (LVG0, LVS,
    LVG1, LNMAP, the count), the nibble tables (the level source's
    NIBTAB), the player (his mobj's handle: its RTHING slot, where the
    angle's low word goes too), message_on; S2_MAIL clear."""
    from native import framestate as FS, rendercap as RCAP
    from native import s2amap as A
    frame = f8.mc.full.case.frame
    p0 = DumpRef(frame.dump('p0'))
    lv = level_ptrs(p0)
    d = A.level_of(p0, lv, fill)
    if d.unfit:
        raise OvlError('%s: the level does not fit: %s' % (
            frame.name, '; '.join(d.unfit[:3])))
    ram = RCAP.load_ram(RCAP.LEVEL_SOURCES /
                        (frame.meta['level_src'] + '.ram.z'))
    nib = ram[NIBTAB_UP:NIBTAB_UP + NIBTAB_SIZE]
    recs = list(A.level_records(d, nib, lv.nlines))
    recs.append((0, 0, LL.LNMAP, d.lnmap))
    st = A.ref_state(p0) if state_in is None else state_in
    recs.append((1, S.S2STATE, S.SS['SS_AMAPW'],
                 A.encode_state(st, fill, 0, (0, 0, 0, 0))))
    name, pd0 = frame_start(frame.dump('p0').header['cycles'])
    for a, n in A.am_state_ranges():        # (the same frame: the same
        if pd0.get(a, n) != p0.get(a, n):    #   automap state at its start)
            raise OvlError('%s: s2cap\'s %s has another automap state'
                           % (frame.name, name))
    palst = bytearray([fill]) * S.PALST_SIZE
    pp = S.palst_places()
    palst[pp['PS_SCB']:pp['PS_SCB'] + 200] = pd0.get(
        A.sym('i_viigs65.s:scb'), 200)
    palst[pp['PS_VIEWPAL']] = pd0.word(A.sym('i_viigs65.s:viewpal')) & 0xFF
    recs.append((1, S.S2STATE, S.SS['SS_PALST'], bytes(palst)))
    # the player: milestone 8's RTHING slot of his mobj
    level = f8.mc.full.case.level
    secs = p0.word(sym.address('_g_sectors'), 3)
    slots = FS.slot_map(frame.dump('p0'), sym, secs,
                        level['counts']['sectors'])
    if lv.mo not in slots:
        raise OvlError('%s: the player\'s mobj is on no thing list'
                       % frame.name)
    slot = slots[lv.mo]
    pl = p0.get(A.sym('g_game65.s:_g_player'), A.SIZEOF_PL)
    allmap = int.from_bytes(pl[A.OFS_PL_POWERS + 2 * A.PW_ALLMAP:
                               A.OFS_PL_POWERS + 2 * A.PW_ALLMAP + 2],
                            'little')
    blk = bytearray(A.player_block(allmap, bytes(5), fill))
    po = A.player_offsets()
    blk[po['mo']:po['mo'] + 2] = struct.pack('<H', slot)
    recs.append((0, 0, LL.G['G_PLAYER'], bytes(blk)))
    angle = p0.get(lv.mo + A.OFS_MO['ANGLE'], 4)
    recs.append((1, R.RTH, R.RTHINGS.address(slot) + LL.TH_ANGLO,
                 angle[0:2]))
    gen = A.s2inc()
    hu_on = p0.sym('hu_stuff65.s:message_on')
    if hu_on > 1:
        raise OvlError('%s: message_on %d' % (frame.name, hu_on))
    recs.append((2, 0, gen['HU_ON'], bytes([hu_on])))
    recs.append((2, 0, gen['S2_MAIL'], bytes(1)))
    return recs, {'pd0': name, 'lines': lv.nlines, 'slot': slot,
                  'message_on': hu_on, 'allmap': allmap,
                  'viewpal_start': palst[pp['PS_VIEWPAL']]}


AM_FIELDS = ('automapmode', 'am_valid', 'am_band', 'AM_MODE', 'm_x', 'm_y',
             'm_w', 'm_h', 'scale_mtof', 'scale_ftom')


def prepare(d: Path, sym, variant: str = '') -> OvlCase:
    """A frame's case. variant '' (the frame as captured), 'band0' (the
    automap's state with am_band 0: upstream's titleBand runs, its rows
    black and its title gone; injected state with a reason: no captured
    frame reaches it, the full map leaves am_band 1), 'tics' (the automap's
    state as the overlay frame before left it at R_DrawLists, am_valid 0 as
    display leaves it, and am_ovl's A = the AM_Ticker calls in between:
    AM_Ticker at frame time, SCREENS.md 1.5.4)."""
    from native import frame8 as F8
    from native import s2amap as A
    f8 = F8.prepare8(d, sym)
    frame = f8.mc.full.case.frame
    p0 = DumpRef(frame.dump('p0'))
    p4 = DumpRef(frame.dump('p4'))
    mode = p0.sym('am_map65.s:automapmode')
    overlay = mode & (A.AM_ACTIVE | A.AM_OVERLAY) == \
        A.AM_ACTIVE | A.AM_OVERLAY
    if overlay != frame.name.startswith('ovl-'):
        raise OvlError('%s: automapmode %d' % (frame.name, mode))
    after = A.upstream_fields(A.ref_state(p4))
    nov = sum(1 for recs in f8.final['records'].values()
              for r in recs if r[0] == 'ovl')
    state_in, tics, band = None, 0, overlay and not p0.sym(
        'am_map65.s:am_band')
    name = frame.name
    if variant == 'band0':
        state_in = A.ref_state(p0)
        a = A.amsym('am_band')
        state_in[a] = state_in[a + 1] = 0
        band = True
        name += '+band0'
    elif variant == 'tics':
        state_in, tics = tics_state(d)
        name += '+tics'
    elif variant:
        raise ValueError(variant)
    return OvlCase(name, overlay, f8, state_in, tics, band, after, variant,
                   {'k_ovl': nov})


AMCAP = OUT / 'amcap'


def ticker_calls() -> List[Tuple[int, str, Dict[int, int], Dict[int, int]]]:
    """Part s2amap's capture of automap.script's AM_Ticker and
    AM_Responder calls (made into this part's directory when missing):
    (cycles, routine, the state in, the state out)."""
    from native import s2amap as A
    if '_calls' not in _PD0:
        if not (AMCAP / 'index.json').exists():
            A.capture(out=AMCAP, work_root=OUT)
        cap = A.Capture(AMCAP)
        _PD0['_calls'] = [(c.cycles, c.routine, c.state_in, c.state_out)
                          for c in A.calls(cap)]
    return _PD0['_calls']


def tics_state(d: Path) -> Tuple[Dict[int, int], int]:
    """The 'tics' variant's state and A (prepare): the state the overlay
    frame before left at R_DrawLists, or after an AM_Responder call in
    between that changed the automap's fields (AMAPW's am_responder, not
    OVLW's), and the AM_Ticker calls after it."""
    from native import framestate as FS
    from native import s2amap as A
    k = int(d.name.split('-')[1])
    prev = d.parent / ('ovl-%02d' % (k - 1))
    if k < 2 or not prev.exists():
        raise OvlError('%s has no overlay frame before it' % d.name)
    p4 = DumpRef(FS.Frame(prev).dump('p4'))
    lo = p4.d.header['cycles']
    hi = FS.Frame(d).dump('p0').header['cycles']
    st = A.ref_state(p4)
    a = A.amsym('am_valid')
    st[a] = st[a + 1] = 0           # (display, after R_DrawLists)
    tics = 0
    for cycles, routine, s_in, s_out in ticker_calls():
        if lo < cycles < hi:
            if routine == 'ticker':
                tics += 1
            elif A.upstream_fields(s_in) != A.upstream_fields(s_out):
                st, tics = dict(s_out), 0   # (the responder's: AMAPW's,
                                            #   the frame driver's call)
    return st, tics


def case_records(case: OvlCase, sym, fill: int, ov: Ovlw,
                 b) -> Tuple[List[Tuple[int, int, int, bytes]],
                             Dict[str, Any]]:
    """The frame's records (milestone 8's) and the overlay's: the
    automap's state, OVLW in its bank, the driver's page runs, fill and
    tics."""
    from native import frame8 as F8
    recs = F8.image_records(case.f8)
    info: Dict[str, Any] = {}
    if case.overlay:
        am, info = automap_records(case.f8, sym, fill, case.state_in)
        recs += am
    recs.append((1, S.OVLW_BANK, S.IMAGE['OVLW'].stored[0], ov.data))
    lab = b.labels
    recs.append((2, 0, lab['ovd_runs'], ov.runs))
    recs.append((2, 0, lab['ovd_fill'], bytes([fill])))
    recs.append((2, 0, lab['ovd_tics'], bytes([case.tics])))
    info['tics'] = case.tics
    return recs, info


# ---------------------------------------------------------------------------
# A run
# ---------------------------------------------------------------------------

SCREEN, SCREEN_SIZE = 0x2000, 0x8000
TITLE_ROWS = (160, 168)         # the title band (AM_TITLEY .. f_h - 1)
TITLE_AT = SCREEN + TITLE_ROWS[0] * 160
TITLE_SIZE = (TITLE_ROWS[1] - TITLE_ROWS[0]) * 160
IO_OVL = {0xC002, 0xC003, 0xC004, 0xC005, 0xC073}
BK_ZP = (0x24, 0x28)            # bucket.s's BK_P, BK_Q (nm_bkload)


def snap_ranges() -> str:
    from native import frame8 as F8
    return F8.SNAP8 + ',aux%d:%04X-%04X,lc:E400-E4FF' % (
        S.S2STATE, S.SS['SS_PALST'], S.SS['SS_AMAPW'] + 0xFF)


def events(b, overlay: bool) -> List[str]:
    lab = b.labels
    out = ['pc %X snapshot clip' % lab['nr_wskip'],
           'pc %X snapshot bsp' % lab['nr_bsp'],
           'pc %X snapshot walk' % lab['ovd_fload'],
           'pc %X snapshot psp' % lab['m_hook'],
           'pc %X@* snapshot batch' % lab['nat_replay'],
           'pc %X snapshot end' % lab['drv_ret'],
           'pc %X snapshot crash' % lab['drv_crash']]
    if overlay:
        out += ['pc %X snapshot pre' % lab['ovd_ovl'],
                'pc %X snapshot post' % lab['ovd_post']]
    else:
        out += ['pc %X snapshot plain' % lab['ovd_plain']]
    return out


def merged_mend(pre, post):
    """The state after am_ovl's last batch, before its nm_bkload: the
    snapshot after both, with what nm_bkload writes (BKFAR, BKFAR2, its
    pointers: rlayout.allowed_writes_bkload, checked on the write log) as
    the snapshot before OVLW has it (nothing of am_ovl's is there)."""
    m = post.mem[(0, 0)]
    src = pre.mem[(0, 0)]
    for lo, hi in ((R.BKFAR_RUN, R.BKFAR_END), (R.BKFAR2_RUN, R.BKFAR2_END),
                   BK_ZP):
        m[lo:hi] = src[lo:hi]
    return post


def ovlw_pcs(ov: Ovlw) -> Dict[str, List[Tuple[int, int]]]:
    seg = ov.segments
    bk = ov.labels['nm_bkload']
    mk = seg['MASKW']
    return {'am': [seg['OVLHEAD'], seg['S2CODE']],
            'rrec': [(mk[0], bk - 1)],
            'bkload': [(bk, mk[1])]}


def ovlw_allowed(b) -> Dict[str, List[Tuple[str, int, int, int]]]:
    gen = __import__('native.s2amap', fromlist=['s2inc']).s2inc()
    lo = S.IMAGE['OVLW'].stored[0]
    hi = S.IMAGE['OVLW'].stored[1]
    zfar = ('main', 0, R.ZP_FAR[0], R.ZP_FAR[1])
    math = ('main', 0, R.ZP_MATH[0], R.ZP_MATH[1])
    return {
        'am': [zfar, ('main', 0, 0x80, 0xB0), math,
               ('main', 0, OVLW_RT, hi), ('main', 0, R.BATCH, R.BATCH + 256),
               ('main', 0, R.FSTOP, R.FSBOT + R.VIEWWIDTH),
               ('aux', 0, TITLE_AT, TITLE_AT + TITLE_SIZE),
               ('lc', 0, gen['S2_MAIL'], gen['S2_MAIL'] + 1),
               ('main', 0, S.PL_STATUS, S.PL_STATUS + 1),
               ('main', 0, R.ZPD['MRB'], R.ZPD['MRB'] + 1),
               # the frame block's AUTOMAP (am_setauto: the renderer's)
               ('main', 0, R.FRAME['AUTOMAP'], R.FRAME['AUTOMAP'] + 1)],
        'rrec': [zfar, ('main', 0, R.ZP_OV1[0], R.ZP_OV1[1]),
                 ('main', 0, R.FB, R.FB_END),
                 ('main', 0, R.UPOFS, R.UPOFS + R.VIEWWIDTH),
                 ('aux', 0, R.STAGE, R.STAGE_END)] +
        [('aux', k, 0x0200, R.STAGE_END) for k in R.RECSP],
        'bkload': [(s, k, a, e) for s, k, a, e, _ in
                   R.allowed_writes_bkload()],
        'far': [zfar, ('main', 0, lo, hi), ('main', 0, 0x80, 0xB0),
                ('aux', S.S2STATE, S.SS['SS_AMAPW'],
                 S.SS['SS_AMAPW'] + 256)],
        # (the math's far table reads: mt_far's operands, as
        # render_check.stray_masked allows them)
        'math': [math] + [('lc1', 0, b.labels[n] + 1, b.labels[n] + 2)
                          for n in ('mt_far_count', 'mt_far_stride')],
        'driver': [('main', 0, 0xD8, 0x100), ('main', 0, R.PHASE,
                                              R.PHASE + 1),
                   ('lc', 0, 0xFFFE, 0x10000)],
    }


def stray_ovlw(writes, b, ov: Ovlw) -> List[str]:
    """The writes from OVLW's load to the bucket pass: by the writing PC,
    OVLW's (am_ovl and s2_amline, the masked copy of rrec.s, nm_bkload),
    the far layer's, the math's, the driver's (its interrupt)."""
    from native import render_check as RC
    pcs = ovlw_pcs(ov)
    seg = b.segments
    pcs['far'] = [seg[s] for s in ('RFAR', 'RLOAD') if s in seg]
    pcs['math'] = [seg[s] for s in ('MATHLC', 'MATHW', 'MATHFAR', 'AUXW')
                   if s in seg]
    pcs['driver'] = [seg['DRIVER'], seg['DESC']]
    allowed = ovlw_allowed(b)
    out = []
    for w in writes:
        which = None
        for name in ('am', 'rrec', 'bkload', 'far', 'math', 'driver'):
            if any(lo <= w.pc <= hi for lo, hi in pcs[name]):
                which = name
                break
        if w.storage == 'io':
            ok = which in ('am', 'rrec', 'far', 'math') and \
                w.address in IO_OVL or \
                which == 'driver' and w.address in RC.IO_DRIVER
        else:
            ok = which is not None and any(
                s == w.storage and (s != 'aux' or k == w.bank) and
                a <= w.offset < e for s, k, a, e in allowed[which])
        if not ok:
            out.append('pc $%04X (%s) wrote %s %d $%04X' % (
                w.pc, which or '?', w.storage, w.bank, w.offset))
    return out


def stray_poison(writes, b) -> List[str]:
    """The driver's poison of OVLW's room (and its interrupt's counter,
    the phase mark, the mouse card's acknowledge)."""
    from native import render_check as RC
    seg = b.segments
    drv = [seg['DRIVER'], seg['DESC']]
    lo, hi = S.IMAGE['OVLW'].stored
    out = []
    for w in writes:
        if w.storage == 'io':
            ok = w.address in RC.IO_DRIVER
        else:
            ok = w.storage == 'main' and (
                lo <= w.offset < hi or 0x80 <= w.offset < 0x82 or
                0xD8 <= w.offset < 0x100 or w.offset == R.PHASE)
        ok = ok and any(a <= w.pc <= e for a, e in drv)
        if not ok:
            out.append('pc $%04X (the poison) wrote %s %d $%04X' % (
                w.pc, w.storage, w.bank, w.offset))
    return out


def w_untouched(pre, post) -> List[str]:
    """Milestone 8's W outside OVLW's room ($6000-$67FF, $9C00-$BFFF) as
    the masked phase left it, but the records' batch BATCH."""
    out = []
    for lo, hi in ((0x6000, S.IMAGE['OVLW'].stored[0]),
                   (S.IMAGE['OVLW'].stored[1], R.BATCH),
                   (R.BATCH + 256, 0xC000)):
        a, b = pre.main(lo, hi - lo), post.main(lo, hi - lo)
        if a != b:
            i = next(k for k in range(hi - lo) if a[k] != b[k])
            out.append('W $%04X changed in OVLW\'s phase ($%02X to $%02X)'
                       % (lo + i, a[i], b[i]))
    return out


def am_state_problems(case: OvlCase, end) -> List[str]:
    """The automap's state block after OVLW against the reference's at
    R_DrawLists (P4); am_valid 0 (display's, after R_DrawLists)."""
    from native import s2amap as A
    blk = end.aux(S.S2STATE, S.SS['SS_AMAPW'],
                  A.state_places()['A_OB'] + 8 - S.OWN_STATE['AMAPW'][1])
    nat = A.decode_state(blk)
    want = dict(case.state_after)
    want['am_valid'] = 0
    out = []
    for k, v in sorted(want.items()):
        if nat.get(k) != v:
            out.append('the automap\'s %s: native %r, reference %r' % (
                k, nat.get(k), v))
    return out


def check(case: OvlCase, b, ov: Ovlw, sym, fill: int, base: Sequence,
          keep: Optional[Path] = None) -> Dict[str, Any]:
    """One run of the frame (the module's docstring)."""
    from native import frame8 as F8, render_check as RC
    name = case.name
    work = Path(tempfile.mkdtemp(prefix='tmp-run-', dir=str(OUT)))
    out: Dict[str, Any] = {'frame': name, 'fill': fill, 'problems': [],
                           'overlay': case.overlay}
    try:
        lab = b.labels
        recs, info = case_records(case, sym, fill, ov, b)
        out.update(info)
        ranges = ','.join('%X-%X' % r for r in F8.code_ranges8(b))
        extra = ['--speed', '1', '--snapshot-ranges', snap_ranges(),
                 '--irq-bounds', RC.IRQ_BOUNDS, '--lowest-s-in', ranges,
                 '--write-log', RC.WRITE_LOG, '--write-log-file',
                 str(work / 'writes.log'), '--write-log-limit',
                 str(RC.WRITE_LOG_LIMIT), '--every-limit', str(R.MAXB + 2)]
        state = RC.a2vm_run(b, list(base) + recs, work,
                            events(b, case.overlay), extra,
                            start='ovd_frame', cycles=F8.CYCLE_LIMIT,
                            timeout=F8.RUN_TIMEOUT)
        if state.get('pc') == lab['drv_crash']:
            try:
                status = RC.snapshot(work, 'crash').main(
                    R.FRAME['STATUS'], 1)[0]
            except RC.CheckError:
                status = None
            out['problems'].append('the frame stopped (BRK), status %s: %s'
                                   % (status, RC.STATUS_NAMES.get(status,
                                                                  '?')))
            return out
        if state.get('end') != 'stop-pc' or state.get('pc') != \
                lab['drv_halt']:
            out['problems'].append('the run ended with %s at $%04X' % (
                state.get('end'), state.get('pc', -1)))
            return out
        snaps = {n: RC.snapshot(work, n) for n in
                 ('clip', 'bsp', 'walk', 'psp', 'end')}
        if case.overlay:
            pre, post = RC.snapshot(work, 'pre'), RC.snapshot(work, 'post')
            out['problems'] += w_untouched(pre, post)
            snaps['mend'] = merged_mend(pre, post)
        else:
            snaps['mend'] = RC.snapshot(work, 'plain')
        batches = F8.one_a_call(sorted(work.glob('batch-*.img')))
        rules = snaps['walk'].main(R.FRAME['RULES'], 1)[0] | \
            snaps['end'].main(R.FRAME['RULES'], 1)[0]
        out['rules'] = rules
        if rules:
            out['known'] = 'rules %d: %s' % (rules, F8.KNOWN)
            return out
        out['problems'] += F8.compare(case.f8, snaps, batches, out)
        # the screen: P5, the title band black when titleBand ran
        got = snaps['end'].aux(0, SCREEN, SCREEN_SIZE)
        want = bytearray(case.f8.truth)
        if case.titleband:
            want[TITLE_AT - SCREEN:TITLE_AT - SCREEN + TITLE_SIZE] = \
                bytes(TITLE_SIZE)
        diff = [i for i in range(SCREEN_SIZE) if got[i] != want[i]]
        out['differing'] = len(diff)
        out['screen_crc'] = '%08X' % (zlib.crc32(got) & 0xFFFFFFFF)
        if diff:
            i = diff[0]
            out['problems'].append(
                'the screen: %d bytes differ (first $%04X row %d col %d: '
                'native $%02X, reference $%02X)' % (
                    len(diff), SCREEN + i, i // 160, i % 160, got[i],
                    want[i]))
        out['shr_writes'] = state.get('shr_writes')
        other = state.get('video_writes', 0) - state.get('shr_writes', 0)
        if other:
            out['problems'].append('%d video writes outside the SHR' % other)
        stores = out.get('stores', 0) + (TITLE_SIZE if case.titleband
                                         else 0)
        if 'stores' in out and out['shr_writes'] != stores:
            out['problems'].append('%s SHR writes, the model %d' % (
                out['shr_writes'], stores))
        irqs = int.from_bytes(snaps['end'].main(0xD8, 2), 'little')
        if irqs == 0:
            out['problems'].append('no interrupt was taken')
        if case.overlay:
            out['problems'] += am_state_problems(case, snaps['end'])
            gen = __import__('native.s2amap',
                             fromlist=['s2inc']).s2inc()
            mail = snaps['end'].read(2, 0, gen['S2_MAIL'], 1)[0]
            want_mail = S.MAIL_AMTITLE if case.titleband else 0
            if mail != want_mail:
                out['problems'].append('S2_MAIL $%02X, $%02X wanted' % (
                    mail, want_mail))
        # the write log, by phase
        timed = RC.read_writes_timed(work / 'writes.log')
        e1 = F8.boundary(timed, b, 'ovd_fload', 26)
        if case.overlay:
            ea = F8.boundary(timed, b, 'ovd_ovl', 0)
            eb = F8.boundary(timed, b, 'ovd_load', 60)
            ec = F8.boundary(timed, b, 'ovd_post', 36)
        else:
            ea = eb = ec = F8.boundary(timed, b, 'ovd_plain', 36)
        front = [w for c, w in timed if c < e1]
        masked = [w for c, w in timed if e1 <= c < ea]
        poison = [w for c, w in timed if ea <= c < eb]
        ovl = [w for c, w in timed if eb <= c < ec]
        after = [w for c, w in timed if c >= ec]
        fc = case.f8.mc.full
        strays = RC.stray(front, b, fc.case.level, stage_b=True) + \
            RC.stray_masked(masked, b) + stray_poison(poison, b) + \
            stray_ovlw(ovl, b, ov) + F8.stray_after(after, b)
        out['ovl_writes'] = len(ovl)
        if strays:
            kinds: Dict[str, int] = {}
            for s in strays:
                k = s.split(' wrote ')[0] + ' ' + \
                    ' '.join(s.split(' wrote ')[1].split()[:2])
                kinds[k] = kinds.get(k, 0) + 1
            out['problems'].append('%d stray writes: %s; by kind %s' % (
                len(strays), '; '.join(strays[:5]),
                ', '.join('%s x%d' % kv for kv in sorted(kinds.items())[:8])))
        low = None
        for r in state.get('lowest_s', {}).get('ranges', []):
            if r.get('s') is not None:
                low = r['s'] if low is None else min(low, r['s'])
        out['stack_bytes'] = None if low is None else RC.DRV_STACK - low
        out['problems'] += RC.stack_problem(out['stack_bytes'])
        out.update({'irqs': irqs, 'writes': len(timed),
                    'cycles': state.get('cycles'),
                    'titleband': case.titleband, 'k_ovl':
                    case.counts['k_ovl']})
        return out
    except (OvlError, RC.CheckError, F8.F8Error) as e:
        out['problems'].append(str(e))
        return out
    finally:
        if keep is not None:
            shutil.copytree(str(work), str(keep), dirs_exist_ok=True)
        shutil.rmtree(str(work), ignore_errors=True)


# ---------------------------------------------------------------------------
# The checkpoint
# ---------------------------------------------------------------------------

FILLS = (0xA5, 0x5A)


BAND0_FRAMES = ('ovl-01', 'ovl-21')     # (message_on 1 and 0)


def jobs_of(dirs: Sequence[Path], variants: bool) -> List[Tuple[Path, str]]:
    """Each frame as captured; with `variants`, also the 'band0' frames
    and every overlay frame after the first as 'tics' (prepare)."""
    out = [(d, '') for d in dirs]
    if variants:
        out += [(d, 'band0') for d in dirs if d.name in BAND0_FRAMES]
        out += [(d, 'tics') for d in dirs if d.name.startswith('ovl-') and
                d.name != 'ovl-01']
    return out


def run_checks(names: Optional[Sequence[str]] = None,
               fills: Sequence[int] = FILLS, jobs: int = JOBS,
               obj: Path = OUT, ovlw: str = 'ovlw', build: str = 'ovf',
               verbose: bool = True, variants: bool = True
               ) -> List[Dict[str, Any]]:
    """Every captured frame (or those named) and its variants, each
    fill."""
    from bridge import linkmap as blink
    from native import render_check as RC
    dirs = frame_dirs()
    if names:
        dirs = [d for d in dirs if d.name in names]
    _rendercap()
    sym = blink.Symbols()
    b = frame_build(obj, build)
    ov = load_ovlw(obj, ovlw)
    bases = {f: RC.base_records(b, f, window=True) for f in fills}
    todo = jobs_of(dirs, variants)
    if any(v == 'tics' for _, v in todo):
        ticker_calls()                  # (once, before the threads)

    def one(job: Tuple[Path, str]) -> List[Dict[str, Any]]:
        d, variant = job
        try:
            case = prepare(d, sym, variant)
        except Exception as e:      # (named in the report, never dropped)
            return [{'frame': d.name + ('+' + variant if variant else ''),
                     'problems': ['prepare: %s: %s' % (
                         type(e).__name__, e)]}]
        return [check(case, b, ov, sym, f, bases[f]) for f in fills]
    results = []
    with ThreadPoolExecutor(max(1, min(4, jobs))) as pool:
        for rs in pool.map(one, todo):
            for r in rs:
                results.append(r)
                if verbose:
                    status = 'KNOWN (%s)' % r['known'] if r.get('known') \
                        else 'DIFFERS' if r['problems'] else 'equal'
                    fill = r.get('fill')
                    print('%-10s %s: %s%s' % (
                        r['frame'], '%02X' % fill if fill else '--', status,
                        ' (%d records, %d K_OVL, %s batches, %s writes in '
                        'OVLW\'s phase, stack %s)' % (
                            r.get('records', 0), r.get('k_ovl', 0),
                            r.get('batches'), r.get('ovl_writes'),
                            r.get('stack_bytes')) if 'records' in r else ''),
                        flush=True)
                    for q in r['problems'][:6]:
                        print('    ' + q, flush=True)
    return results


# ---------------------------------------------------------------------------
# The planted bugs, each in a scratch copy
# ---------------------------------------------------------------------------

# the planted driver: the overlay's step before the masked phase (its
# records before the view's last batch: the masked phase's), after the
# walk's snapshot; main's $0C00-$0EFF and $0200-$02FF kept in RECW around
# it (OVLW's nm_bkload writes them; the masked phase reads the clips
# there); the harness's labels kept in their order after the masked phase
EARLY_OLD = """        jsr nr_frame
ovd_fload:
        lda #26                 ; the cost phase 13: the masked load
        sta PHASE
        jsr far_mload
        stz PHASE
        jsr nm_masked
        lda AUTOMAP             ; the overlay on: OVLW
        and #AM_ON_OVL
        cmp #AM_ON_OVL
        bne ovd_plain
ovd_ovl:
        stz PHASE               ; (the driver's phase 0: the masked phase's
        jsr poison              ;   end in the write log)
ovd_load:
        lda #60                 ; the cost phase 30: OVLW's load, am_ovl
        sta PHASE
        lda #<ovd_runs
        ldx #>ovd_runs
        ldy #OVLW_BANK
        jsr far_pload
        lda ovd_tics
        jsr OVLW_ENTRY          ; am_ovl, then OVLW's nm_bkload
ovd_post:
        bra ovd_bucket
"""
EARLY_NEW = """        jsr nr_frame
ovd_fload:
        lda AUTOMAP             ; PLANTED: the overlay before the masked
        and #AM_ON_OVL          ;   phase
        cmp #AM_ON_OVL
        bne @no
        sec
        jsr keep
        jsr poison
        lda #<ovd_runs
        ldx #>ovd_runs
        ldy #OVLW_BANK
        jsr far_pload
        lda ovd_tics
        jsr OVLW_ENTRY
        clc
        jsr keep
@no:    lda #26
        sta PHASE
        jsr far_mload
        stz PHASE
        jsr nm_masked
        lda AUTOMAP
        and #AM_ON_OVL
        cmp #AM_ON_OVL
        bne ovd_plain
ovd_ovl:
        stz PHASE
ovd_load:
        lda #60
        sta PHASE
ovd_post:
        lda #36
        sta PHASE
        jsr nm_bkload
        bra ovd_bucket
keep:   php                     ; C = 1: main to RECW, else back
        ldx #0
@page:  lda kpages,x
        beq @done
        plp
        php
        stz FA_SRC
        stz FA_DST
        bcc @back
        sta FA_SRC+1
        txa
        clc
        adc #2
        sta FA_DST+1
        bra @go
@back:  sta FA_DST+1
        txa
        clc
        adc #2
        sta FA_SRC+1
@go:    lda #RECW
        sta FA_BANK
        stz FA_N
        phx
        plp
        php
        bcc :+
        jsr far_put
        bra :++
:       jsr far_get
:       plx
        inx
        bra @page
@done:  plp
        rts
kpages: .byte $0C, $0D, $0E, $02, 0
"""

EARLY_IMPORT = ("""        .import far_pload, nm_bkload, nb_frame, drv_irq, drv_ret
""", """        .import far_pload, nm_bkload, nb_frame, drv_irq, drv_ret
        .import far_get, far_put
""")

# (file, ((old, new), ...), what): each old text is in the file exactly
# once
PLANTED = (
    ('s2_ovl.s', (("""        lda #$0F                ; x even: keep the low nibble""",
                   """        lda #$F0                ; PLANTED: x even keeps the high one"""),),
     'the kept nibble $F0 for an even x'),
    ('s2_ovl.s', (("""        lda LNY                 ; FSCUTE: the end LNY + 1, the first LNY
        inc a
""", """        lda LNY                 ; PLANTED: FSCUTE's end without + 1
"""),), 'FSCUTE\'s end row not + 1'),
    ('s2_ovd.s', ((EARLY_OLD, EARLY_NEW), EARLY_IMPORT),
     'the records before the view\'s last batch (the overlay before the '
     'masked phase)'),
    ('ovlw.cfg', (),
     'nm_bkload copying BKFAR from MASKW\'s address instead of OVLW\'s'),
    ('s2_ovl.s', (("""am_fastline:
        lda ST_MODE""", """am_fastline:
        clc                     ; PLANTED: no fast turn: the 32-bit path
        rts
        lda ST_MODE"""),), 'the fast turn never taken (every line by the '
     '32-bit path)'),
)
PLANT_FRAMES = ('ovl-01', 'ovl-10', 'ovl-21', 'plain-01')
KEEP_GEN = ('s2.inc', 's2-release.inc', 's2-m11.inc', 's2-fxch8.inc',
            'rlayout.inc')


def plant(k: int, jobs: int = JOBS) -> Dict[str, Any]:
    """Planted bug k in a scratch copy (its sources, or OVLW's link map),
    built into a scratch M11, run on PLANT_FRAMES with fill $A5: the
    checks that fail."""
    from native import render_check as RC
    fname, edits, what = PLANTED[k]
    tmp = Path(tempfile.mkdtemp(prefix='tmp-plant-', dir=str(OUT)))
    try:
        src = tmp / 'src' / 'native'
        (src / 'm11').mkdir(parents=True)
        for f in ('m11.mk',):
            shutil.copy(str(SOURCE / f), str(src / f))
        for f in ('s2lay.mk', 's2ovl.mk'):
            shutil.copy(str(SOURCE / 'm11' / f), str(src / 'm11' / f))
        m11 = tmp / 'm11'
        variables = ['S2OV_R=%s' % (OUT / 'render')]
        if fname != 'ovlw.cfg':
            text = (SOURCE / fname).read_text()
            for old, new in edits:
                if text.count(old) != 1:
                    raise OvlError('planted bug %d: its text is in %s %d '
                                   'times' % (k, fname, text.count(old)))
                text = text.replace(old, new)
            (src / fname).write_text(text)
        _make_in(src, m11, variables)
        if fname == 'ovlw.cfg':
            obj = m11 / 's2ovl'
            cfg = obj / 'ovlw.cfg'
            cfg.write_text(ovlw_cfg_text(read_labels(obj / 'ovf.lbl'),
                                         planted_bkfar=True))
            later = time.time() + 2
            import os
            os.utime(str(cfg), (later, later))
            _make_in(src, m11, variables)
        res = run_checks(PLANT_FRAMES, (0xA5,), jobs, obj=m11 / 's2ovl',
                         verbose=False)
        failing = [r for r in res if r['problems']]
        return {'bug': what, 'runs': len(res), 'failing': len(failing),
                'caught': bool(failing),
                'first': ['%s: %s' % (r['frame'], r['problems'][0])
                          for r in failing][:4]}
    except (OvlError, RC.CheckError) as e:
        return {'bug': what, 'caught': False, 'error': str(e)}
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


def _make_in(src: Path, m11: Path, variables: Sequence[str]) -> None:
    from ref816 import bounded
    res = bounded.run(['nice', '-n', '10', 'make', '-s', '-C', str(src),
                       '-f', 'm11.mk', 'part', 'P=s2ovl', 'M11=%s' % m11,
                       'ROOT=%s' % ROOT] + list(variables), timeout=600,
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      universal_newlines=True)
    if res.returncode:
        raise OvlError('the scratch build failed:\n' + res.stdout[-3000:])


def planted(jobs: int = JOBS, which: Optional[Sequence[int]] = None
            ) -> List[Dict[str, Any]]:
    out = []
    for k in (which if which is not None else range(len(PLANTED))):
        r = plant(k, jobs)
        print('planted %d: %s: %s%s' % (
            k + 1, r['bug'], 'caught' if r['caught'] else 'NOT CAUGHT',
            ' (%d of %d runs fail)' % (r['failing'], r['runs'])
            if 'runs' in r else ''), flush=True)
        for line in r.get('first', [])[:2]:
            print('    ' + line[:300], flush=True)
        if 'error' in r:
            print('    ' + r['error'][:600], flush=True)
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Timing (SCREENS.md 6.4): the profiling builds ovfp and ovlwp under
# a2vm's cost model, f121 and fastpath
# ---------------------------------------------------------------------------

PROFILES = ('f121', 'fastpath')
PHASES = {1: 'window', 2: 'setup', 17: 'clip', 3: 'walk', 9: 'walls',
          10: 'segs', 13: 'mwindow', 14: 'dscopy', 11: 'project',
          15: 'sort', 4: 'sprites', 16: 'weapon', 30: 'ovlw',
          18: 'bucket', 12: 'replay', 0: 'driver'}
DRAIN_US = 0.991        # µs a published byte drains on F1.2.1 [M: s2draw.md]


def cost_run(b, recs, start: str, profile: str) -> Dict[str, Any]:
    from a2vm import costs
    from native import frame8 as F8, render_check as RC
    work = Path(tempfile.mkdtemp(prefix='tmp-time-', dir=str(OUT)))
    try:
        (work / 'cost.txt').write_text(costs.text(profile))
        report = work / 'cost.json'
        extra = ['--cost', str(work / 'cost.txt'), '--cost-timed',
                 '--cost-phase', '%X' % R.PHASE, '--cost-report',
                 str(report)]
        state = RC.a2vm_run(b, recs, work, [], extra, start=start,
                            cycles=F8.CYCLE_LIMIT, timeout=F8.RUN_TIMEOUT)
        if state.get('pc') != b.labels['drv_halt']:
            raise OvlError('a timing run ended at $%04X' % state.get('pc',
                                                                    -1))
        text = report.read_text()
        cost = json.loads(text[text.rfind('{"final"'):])['cost']
        mhz = costs.parameters(profile)['fabric_mhz']
        res = {name: round(cost['phases'][k] / (mhz * 1000.0), 4)
               for k, name in PHASES.items()}
        res['total_ms'] = round(sum(cost['phases'][k] for k in PHASES
                                    if k) / (mhz * 1000.0), 4)
        return res
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def stats(values: Sequence[float]) -> Dict[str, float]:
    v = sorted(values)
    if not v:
        return {}
    return {'n': len(v), 'median': round(v[len(v) // 2], 3),
            'p99': round(v[min(len(v) - 1, (99 * len(v)) // 100)], 3),
            'worst': round(v[-1], 3)}


def timing(jobs: int = JOBS, obj: Path = OUT) -> Dict[str, Any]:
    """Each frame as captured (fill $A5) on the profiling builds: the
    whole frame's phases; OVLW's load alone (ovd_ltime); OVLW's work =
    the phase 30 less the load (am_ovl and its nm_bkload's copy)."""
    from bridge import linkmap as blink
    from native import render_check as RC
    _rendercap()
    sym = blink.Symbols()
    b = frame_build(obj, 'ovfp')
    ov = load_ovlw(obj, 'ovlwp')
    base = RC.base_records(b, 0xA5, window=True)
    out: Dict[str, Any] = {}
    lrecs = list(base) + [(1, S.OVLW_BANK, S.IMAGE['OVLW'].stored[0],
                           ov.data),
                          (2, 0, b.labels['ovd_runs'], ov.runs)]
    load = {p: cost_run(b, lrecs, 'ovd_ltime', p)['ovlw'] for p in PROFILES}
    cases = []
    for d in frame_dirs():
        cases.append(prepare(d, sym))

    def one(case: OvlCase) -> Dict[str, Any]:
        recs, _ = case_records(case, sym, 0xA5, ov, b)
        r = {'frame': case.name, 'overlay': case.overlay,
             'k_ovl': case.counts['k_ovl']}
        for p in PROFILES:
            r[p] = cost_run(b, list(base) + recs, 'ovd_frame', p)
        return r
    with ThreadPoolExecutor(max(1, min(4, jobs))) as pool:
        frames = list(pool.map(one, cases))
    out['load_ms'] = load
    out['load_bytes'] = len(ov.data)
    out['frames'] = frames
    summary: Dict[str, Any] = {}
    for p in PROFILES:
        s: Dict[str, Any] = {}
        for kind, sel in (('overlay', True), ('plain', False)):
            fr = [f for f in frames if f['overlay'] == sel]
            s[kind] = {k: stats([f[p][k] for f in fr]) for k in
                       ('total_ms', 'replay', 'bucket', 'ovlw', 'mwindow')}
            if sel:
                s[kind]['ovlw_work'] = stats([f[p]['ovlw'] - load[p]
                                              for f in fr])
        summary[p] = s
    out['summary'] = summary
    out['title_drain_ms'] = round(TITLE_SIZE * DRAIN_US / 1000.0, 3)
    return out


# ---------------------------------------------------------------------------
# Sizes and the images' static checks
# ---------------------------------------------------------------------------

BUDGET_OWN = 4500               # s2_ovl (SCREENS.md 7.3)
ROOM = S.IMAGE['OVLW'].stored[1] - S.IMAGE['OVLW'].stored[0]


def module_sizes(map_text: str) -> Dict[str, Dict[str, int]]:
    """Each module's bytes by segment (ld65's map)."""
    out: Dict[str, Dict[str, int]] = {}
    part = map_text.split('Modules list:', 1)[-1].split('Segment list:',
                                                        1)[0]
    module = None
    for line in part.splitlines():
        if line and not line.startswith(' ') and line.rstrip().endswith(':'):
            module = Path(line.strip()[:-1].split('(')[0]).stem
            continue
        f = line.split()
        if module and f and any(x.startswith('Size=') for x in f):
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            out.setdefault(module, {})[f[0]] = size
    return out


def image_problems(obj: Path = OUT) -> List[str]:
    """OVLW's BKFAR and BKFAR2 are the frame image's (MASKW's), byte for
    byte (the same run addresses, the same card part); OVLW's entry is its
    first byte; its stored bytes stay below its run time places."""
    out = []
    for ovlw, frame in (('ovlw', 'ovf'), ('ovlwp', 'ovfp')):
        ov = load_ovlw(obj, ovlw)
        fl = read_labels(obj / (frame + '.lbl'))
        wm = (obj / (frame + '.wm')).read_bytes()
        lo = S.IMAGE['OVLW'].stored[0]
        for seg in ('BKFAR', 'BKFAR2'):
            size = ov.labels['__%s_SIZE__' % seg]
            if size != fl['__%s_SIZE__' % seg]:
                out.append('%s: %s %d B, the frame image\'s %d B' % (
                    ovlw, seg, size, fl['__%s_SIZE__' % seg]))
                continue
            a = ov.labels['__%s_LOAD__' % seg] - lo
            m = fl['__%s_LOAD__' % seg] - R.MCODE
            if ov.data[a:a + size] != wm[m:m + size]:
                out.append('%s: %s differs from the frame image\'s' % (
                    ovlw, seg))
            if ov.labels['__%s_RUN__' % seg] != fl['__%s_RUN__' % seg]:
                out.append('%s: %s runs elsewhere' % (ovlw, seg))
        if ov.data[:3] != bytes([0x4C, ov.labels['am_ovl'] & 0xFF,
                                 ov.labels['am_ovl'] >> 8]):
            out.append('%s: its first bytes are not jmp am_ovl' % ovlw)
    return out


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    ov = load_ovlw(obj)
    mods = module_sizes((obj / 'ovlw.map').read_text())
    own = mods.get('s2_ovl', {})
    out = {'s2_ovl': sum(own.values()), 's2_ovl_budget': BUDGET_OWN,
           's2_amline': sum(mods.get('s2_amline-ovl', {}).values()),
           'rrec': sum(mods.get('rrec-m', {}).values()),
           'bucket': mods.get('bucket', {}),
           'stored': len(ov.data), 'room': ROOM,
           'stored_end': '$%04X' % (S.IMAGE['OVLW'].stored[0] +
                                    len(ov.data) - 1),
           'runtime': '$%04X-$%04X' % (OVLW_RT,
                                       S.IMAGE['OVLW'].stored[1] - 1),
           'size_table': (obj / 'ovlw.sizes').read_text().splitlines()}
    out['problems'] = []
    if out['s2_ovl'] > BUDGET_OWN:
        out['problems'].append('s2_ovl %d B over its %d' % (out['s2_ovl'],
                                                          BUDGET_OWN))
    if S.IMAGE['OVLW'].stored[0] + len(ov.data) > OVLW_RT:
        out['problems'].append('OVLW\'s stored bytes reach its run time '
                               'places')
    out['problems'] += image_problems(obj) + frame_problems(obj) + \
        amline_problems()
    return out


# the frame image's objects (src/native/m11/s2ovl.mk's S2OV_F8 and
# S2OV_F8P): render.mk's ftest and fprof, in their link order
F8_OBJS = ('rframe', 'rbsp', 'rlight', 'auxlc', 'far', 'wclip', 'wpsp',
           'gvalid-r', 'rwall', 'rseg', 'rsky', 'rrec', 'segloops',
           'mmain-c', 'mproj-c', 'mfar-c', 'msprite-c', 'mvis-c', 'mwall-c',
           'mpsp-c', 'rrec-m', 'wpsp-m', 'math-r', 'rdriver-f', 'bucket',
           'replay-r')
F8P_OBJS = ('rframe-p', 'rbsp-p', 'rlight-p', 'auxlc-p', 'far-p', 'wclip-p',
            'wpsp-p', 'gvalid-r-p', 'rwall-p', 'rseg-p', 'rsky-p', 'rrec-p',
            'segloops-p', 'mmain-p', 'mproj-p', 'mfar-p', 'msprite-p',
            'mvis-p', 'mwall-p', 'mpsp-p', 'rrec-mp', 'wpsp-m', 'math-r',
            'rdriver-f', 'bucket-p', 'replay-r')
FRAME_FILES = ('w', 'wm', 'lc1', 'far', 'rc', 'lc2', 'm08', 'a02', 'a08',
               'vec', 'boot')


def mk_objects(name: str) -> List[str]:
    """A list of object stems of src/native/m11/s2ovl.mk."""
    text = (SOURCE / 'm11' / 's2ovl.mk').read_text().replace('\\\n', ' ')
    import re
    m = re.search(r'^%s :=(.*)$' % name, text, re.M)
    if not m:
        raise OvlError('s2ovl.mk has no %s' % name)
    return m.group(1).split()


def render_mk_objects(var: str) -> List[str]:
    """render.mk's ftest or fprof objects (FTEST_OBJS, FPROF_OBJS) as
    stems, its variables expanded (milestone 8's makefile, read)."""
    import re
    text = (SOURCE / 'render.mk').read_text().replace('\\\n', ' ')
    vars_: Dict[str, str] = {}
    for m in re.finditer(r'^(\w+)\s*:=(.*)$', text, re.M):
        vars_[m.group(1)] = m.group(2)

    def expand(s: str) -> str:
        for _ in range(8):
            s = re.sub(r'\$\((\w+):%=\$\(OUT\)/%([-\w]*)\.o\)',
                       lambda m: ' '.join('$(OUT)/%s%s.o' % (w, m.group(2))
                                          for w in expand(
                                              vars_[m.group(1)]).split()), s)
            s = re.sub(r'\$\((\w+)\)', lambda m: vars_.get(
                m.group(1), '$(%s)' % m.group(1)) if m.group(1) != 'OUT'
                else '$(OUT)', s)
        return s
    return [Path(w).stem for w in expand(vars_[var]).split()]


def frame_problems(obj: Path = OUT) -> List[str]:
    """The frame images are milestone 8's whole frame: their objects are
    render.mk's ftest's and fprof's in its order (and s2ovl.mk's lists
    and this tool's are the same), and linked without this part's driver
    they give the same bytes in every file but the driver's (ftest's
    driver part a prefix of the frame image's)."""
    out = []
    for mine, var, tool in (('S2OV_F8', 'FTEST_OBJS', F8_OBJS),
                            ('S2OV_F8P', 'FPROF_OBJS', F8P_OBJS)):
        got = mk_objects(mine)
        want = render_mk_objects(var)
        if got != want:
            out.append('s2ovl.mk\'s %s is not render.mk\'s %s: %s, %s' % (
                mine, var, got, want))
        if list(tool) != got:
            out.append('s2ovl.py\'s list is not s2ovl.mk\'s %s' % mine)
    tmp = Path(tempfile.mkdtemp(prefix='tmp-ftest-', dir=str(OUT)))
    try:
        for name, objs in (('ovf', F8_OBJS), ('ovfp', F8P_OBJS)):
            res = subprocess.run(
                ['ld65', '-C', str(SOURCE / 'render.cfg'), '-o',
                 str(tmp / name)] + [str(OUT / 'render' / (o + '.o'))
                                     for o in objs],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, timeout=120)
            if res.returncode:
                out.append('ld65: %s' % res.stdout[-500:])
                continue
            for ext in FRAME_FILES:
                a = (tmp / ('%s.%s' % (name, ext))).read_bytes()
                b = (obj / ('%s.%s' % (name, ext))).read_bytes()
                if a != b:
                    out.append('%s.%s differs from milestone 8\'s frame' % (
                        name, ext))
            out += driver_problems(tmp, obj, name)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    return out


def _desc(path: Path) -> Tuple[int, int]:
    import re
    m = re.search(r'^DESC\s+([0-9A-F]{6})\s+([0-9A-F]{6})',
                  path.read_text(), re.M)
    if not m:
        raise OvlError('%s has no DESC' % path)
    return int(m.group(1), 16), int(m.group(2), 16)


def driver_problems(tmp: Path, obj: Path, name: str) -> List[str]:
    """rdriver.s's bytes in the frame image's .lce are milestone 8's but
    for its operands that name its descriptor (DESC, bss, after the
    driver segment: it moves by this part's driver code)."""
    subprocess.run(['ld65', '-C', str(SOURCE / 'render.cfg'), '-o',
                    str(tmp / name), '-m', str(tmp / (name + '.map'))] +
                   [str(OUT / 'render' / (o + '.o')) for o in
                    (F8_OBJS if name == 'ovf' else F8P_OBJS)],
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                   timeout=120, check=True)
    a = (tmp / (name + '.lce')).read_bytes()
    b = (obj / (name + '.lce')).read_bytes()
    lo_a, hi_a = _desc(tmp / (name + '.map'))
    lo_b, _ = _desc(obj / (name + '.map'))
    delta = lo_b - lo_a
    bad = []
    k = 0
    while k < len(a):
        if k < len(b) and a[k] == b[k]:
            k += 1
            continue
        wa = int.from_bytes(a[k:k + 2], 'little')
        wb = int.from_bytes(b[k:k + 2], 'little')
        if lo_a <= wa <= hi_a and wb == wa + delta:
            k += 2
            continue
        bad.append(k)
        k += 1
    if bad:
        return ['%s.lce: rdriver.s\'s part differs at $%04X (not a '
                'descriptor operand)' % (name, 0xE000 + bad[0])]
    return []


def summary_line(res: Sequence[Dict[str, Any]]) -> str:
    runs = len(res)
    bad = [r for r in res if r['problems']]
    ovl = [r for r in res if r.get('overlay') and not r['problems']]
    return ('%d runs (%d frames and variants), %d with problems; %d K_OVL '
            'records compared in %d overlay runs' % (
                runs, len({r['frame'] for r in res}), len(bad),
                sum(r.get('k_ovl', 0) for r in ovl), len(ovl)))


def run_all(jobs: int = JOBS) -> Dict[str, Any]:
    t0 = time.time()
    make()
    if not (OUT / 'capture.json').exists():
        capture(jobs)
    report: Dict[str, Any] = {'sizes': sizes()}
    res = run_checks(None, FILLS, jobs, verbose=False)
    report['check'] = {'summary': summary_line(res), 'runs': res}
    report['planted'] = planted(jobs)
    report['timing'] = timing(jobs)
    report['seconds'] = round(time.time() - t0)
    problems = report['sizes']['problems'] + \
        ['%s %s: %s' % (r['frame'], r.get('fill'), q) for r in res
         for q in r['problems']] + \
        ['planted bug not caught: %s' % r['bug']
         for r in report['planted'] if not r['caught']]
    report['problems'] = problems
    report['ok'] = not problems
    (OUT / 'report.json').write_text(json.dumps(report, indent=1) + '\n')
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--ovlw-cfg', nargs=2, type=Path,
                        metavar=('FRAME_LBL', 'OUT'))
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--planted', action='store_true')
    parser.add_argument('--timing', action='store_true')
    parser.add_argument('--sizes', action='store_true')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--frames')
    parser.add_argument('--fills', default='a5,5a')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--jobs', type=int, default=JOBS)
    args = parser.parse_args(argv)
    if args.ovlw_cfg:
        write_ovlw_cfg(*args.ovlw_cfg)
        return 0
    if args.capture:
        res = capture(args.jobs)
        print('%d frames captured of %d in the run: %s' % (
            len(res['frames']), res['frames_in_run'],
            ', '.join(f['name'] for f in res['frames'])))
        return 0
    if args.all:
        rep = run_all(args.jobs)
        print(rep['check']['summary'])
        print('sizes: s2_ovl %d of %d B, OVLW %d of %d B stored' % (
            rep['sizes']['s2_ovl'], BUDGET_OWN, rep['sizes']['stored'],
            ROOM))
        for q in rep['problems'][:20]:
            print('  ' + q)
        print('report.json: %s (%d s)' % ('ok' if rep['ok'] else 'PROBLEMS',
                                          rep['seconds']))
        return 0 if rep['ok'] else 1
    if args.sizes:
        if not args.no_build:
            make()
        print(json.dumps(sizes(), indent=1))
        return 0
    if args.timing:
        if not args.no_build:
            make()
        res = timing(args.jobs)
        print(json.dumps({'load_ms': res['load_ms'],
                          'load_bytes': res['load_bytes'],
                          'title_drain_ms': res['title_drain_ms'],
                          'summary': res['summary']}, indent=1))
        return 0
    if args.planted:
        if not args.no_build:
            make()
        res = planted(args.jobs)
        return 0 if all(r['caught'] for r in res) else 1
    if args.check:
        if not args.no_build:
            make()
        res = run_checks(args.frames.split(',') if args.frames else None,
                         [int(f, 16) for f in args.fills.split(',')],
                         args.jobs)
        bad = [r for r in res if r['problems']]
        print('%d runs, %d with problems' % (len(res), len(bad)))
        return 1 if bad else 0
    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
