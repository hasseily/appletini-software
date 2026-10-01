#!/usr/bin/env python3
"""Frame captures of upstream's renderer for milestones 7 and 8
(docs/RENDER.md section 4.1, docs/RENDER-MASKED.md 4.1): the reference's
state at chosen frames, from R_FillStamps to the return of R_DrawLists,
with the calls of R_StoreWallRange, vtxAngle, R_AddSprites and the masked
phase's routines in between.

Usage:  python3 tools/native/rendercap.py [--runs newgame,m5demo,title,tour]
                                          [--out DIR] [--jobs 2]

Four runs of the release on ref816, each twice (the first to choose the
frames, the second to capture them), give the four frame sets:

    run      script                           sets
    newgame  coverage/newgame.script          still (m5: still-1..3),
                                              newgame (50)
    m5demo   coverage/title.script            demo (m5: demo-01..11)
    title    the title loop to demo3's end    title (50), demo3 (every
             (tools/ref816/lumps.py demo_script(7),   frame from the note
             written under build/)                    "demo" to "demo-end",
                                                      533: milestone 8)
    tour     coverage/tour.script, with the   e1m3 (m5: e1m3-1), tour (50:
             note "e1m3" after "shot e1m3"    5 or 6 a map, E1M1-E1M9)
             (as tools/ref816/capture.py)
    lights   LIGHTS_SCRIPT (below): a new     lights (12): the paths no
             game, gamma poked to 2, the      coverage script reaches, the
             cheats idbeholdl and idbeholdv   fixed colormaps and a gamma
                                              other than 0

The m5 frames are milestone 5's (tools/ref816/capture.py chooses their
R_DrawLists calls the same way, with its own code): for each, the frame
whose R_FillStamps comes last before that call. `newgame` takes 50 frames
evenly over all the run's level frames; `title` 50 evenly from the note
"demo" to "demo-end"; `tour` 5 or 6 evenly over each map's frames, the
map's first frame among them. The last frame of a run is never chosen, a
frame whose view is not the full view (VW_CUR) is never chosen, and a
frame must reach drawMasked. `demo3` takes every usable frame of demo3,
named by its index among the run's frames (demo3-000 ...); render_check.py
leaves it out unless it is asked for (milestone 7's 188 frames stay its
default).

The first run marks R_FillStamps, R_RenderBSPNode, the return of
weaponClip in weaponClipSame (weaponClipSame + 3), drawAllL (an early
flush of the lists), drawMasked, R_DrawLists and R_MakeTextureColumns,
and dumps the map number and the view size at each R_FillStamps. The
second run adds, as ref816 points (--dump-at, at most 64: the chosen
frames go in at most CLUSTERS ranges of frames, and every frame of a
range is dumped and the others dropped as the stream is read):

    P0   R_FillStamps          input: the near bank $02, $00:0900-$0BFF
                               (the C direct page, BSPDP, WPAGE), the zone
                               $06-$09, $0A:B500-$B9FF (the drawseg
                               columns, the view window), $0A:C500-$C8FF
                               (the weapon skip), FLATCM, the colormaps,
                               $23:0000-$7FFF (the vertex angles and their
                               stamps), $23:EF00-$FAFF (spans, covered
                               ranges)
    P0F  R_FillStamps          all RAM: the first chosen frame of each
                               level of a run, and the first chosen frame
                               after a texture made in play (the levels'
                               sources for tools/native/levelconv.py)
    P1   weaponClipSame + 3    the seam: bank $02 (floorclip, FR_VIS),
                               MM_WPOK
    P0b  R_RenderBSPNode       the clears: bank $02, $00:0900-$0BFF,
                               $0A:B500-$B9FF, $0A:C500-$C8FF, the spans
    P2   drawAllL              an early flush: bank $1D, bank $02
    P3   drawMasked            the truth: bank $02, bank $1D, the spans,
                               $0A:B500-$B9FF, $0A:C500-$C8FF,
                               $00:0900-$0BFF, the zone $06-$09
    P3s  drawMasked + 3        after sortSkip (milestone 8): bank $02
                               (FR_ORDER, FR_SKIP), $00:0A00-$0AFF (W_WSK)
    P3w  playerSkip            before the weapon's draw: bank $1D, bank $02
                               (COLW, XPNEXT), the spans
    PS   stripEarly            the render's end: $E1:2000-$9FFF
    P4   R_DrawLists           bank $1D, bank $02 (COLW, XPNEXT, FZ_POS),
                               the spans, $0A:C500-$C8FF, $E1:2000-$9FFF,
                               $00:0AB0-$0AB1 (W_WSK, milestone 8)
    P5   R_DrawLists' return   $E1:2000-$9FFF

and P0 also holds SPRBOUND ($22:7800, 220 bytes), P2 the screen. An early
flush in the masked phase (drawAllL after drawMasked) is a p2m-K dump.

and logs the calls of R_StoreWallRange (the start in A; the stop, BSPDP,
the plane colours, worldbottom and ds_p at the entry; solidcol at the
return), vtxAngle (entries), R_FillStamps (entries), R_MakeTextureColumns
(entries, the texture in A), the first call of viewSide (its registers
and return address, for the side check of tools/native/sidecheck.py),
and for milestone 8 the entries of R_AddSprites (the sector at _Dp+4, the
light in A), R_DrawVisSprite (the vissprite, VS_CLIP, mfloorclip,
mceilingclip, floorclip and ceilingclip), R_RenderMaskedSegRange (FR_DS,
_Dp+4, A), wcProf and wdProf. A frame's walk calls are those from its
R_FillStamps to drawMasked; its masked-phase calls those from drawMasked
to the next frame's R_FillStamps.
The second run must end with the first run's RAM and marks.

The stream is read from a pipe as the machine writes it; each chosen
frame's dumps are stored at once, zlib-compressed, in
build/native/render/frames/SET-NN/ (p0, p1, p0b, p2-K, p3, p3s, p3w,
p2m-K, ps, p4, p5 .dump.z: a dump's JSON header line then its bytes), with frame.json (the frame, its
hits, the level source) and calls.json (its calls); the full dumps go to
build/native/render/levels/src/NAME.ram.z (banks $00-$7F, $E0, $E1).
Nothing else is kept. All runs are under nice, bounded in time, in
stream size (--dump-limit), in call-log size and in file size; free disk
space is checked first (20 GB at least).
"""

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Optional, Sequence, \
    Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ref816 import bounded, capture, dumps, lumps, make_image, marks, \
    run_script, script, title  # noqa: E402
from ref816 import calls as calllog  # noqa: E402

ROOT = make_image.ROOT
RENDER = make_image.BUILD / 'native' / 'render'
FRAMES = RENDER / 'frames'
LEVEL_SOURCES = RENDER / 'levels' / 'src'
FORMAT = 'render-frame-capture 1'

MIN_FREE_BYTES = 20 * 10 ** 9
RUN_TIMEOUT = 3600.0            # seconds of host time a run
LIMIT_SECONDS = 900             # machine seconds of a script (not demo3)
DEMO_LIMIT_SECONDS = 3000       # demo3's own bound (lumps.demo_script)
CALL_LOG_LIMIT = 512 << 20
MAX_FILE = 1 << 30              # no file of a run past this
MAX_POINTS = 64                 # ref816's --dump-at points
FULL_VIEW = 0xA50A              # VW_CUR: VW_TAG | 10 (viewwin.inc)
DUMP_BYTES = {'P0': 590220, 'P1': 70000, 'P0b': 100000, 'P2': 173000,
              'P3': 530000, 'P3s': 66000, 'P3w': 135000, 'PS': 32768,
              'P4': 168000, 'P5': 32768, 'P0F': 130 * 0x10000, 'SMALL': 64}
# the points of each chosen frame (a --dump-at point per range of frames
# each): kind, the Frame's hit field, the stored name
FRAME_POINTS = (('P0', 'fs_hit', 'p0'), ('P1', 'seam_hit', 'p1'),
                ('P0b', 'bsp_hit', 'p0b'), ('P3', 'dm_hit', 'p3'),
                ('P3s', 'dm3_hit', 'p3s'), ('P3w', 'ps_hit', 'p3w'),
                ('PS', 'se_hit', 'ps'), ('P4', 'dl_hit', 'p4'),
                ('P5', 'dlr_hit', 'p5'))

# symbols (the link map) and upstream constants (memmap.inc, viewwin.inc)
MM_BV = 0x0A0000
VW_CUR = MM_BV + 0xB802
MM_WPOK = 0x0AC84A
FS_SPANS = (0x23EF00, 0xC00)            # FS_*, CV_* (lists.inc)
MM_SPRBOUND = (0x227800, 4 * 55)        # memmap.inc, CONST_NUMSPRITES
SCREEN = (0xE12000, 0x8000)


class RunSpec(NamedTuple):
    key: str
    script: Optional[str]               # a coverage script, or None: demo3
    note_after: Optional[Tuple[str, str]]   # (line, note) put after it
    sets: Tuple[str, ...]


# The lights run: paths no coverage script reaches (the renderer's fixed
# colormaps and a gamma other than 0; RENDER.md 4.1: "a path with no frame
# gets frames added from the scripts"). The new game of newgame.script,
# then in E1M1 the gamma poked to 2, the light amplification visor
# (idbeholdl: fixedcolormap 1) and invulnerability (idbeholdv: the
# inverse colormap, 32), turning, all through upstream's own code.
LIGHTS_SCRIPT = '''# rendercap.py: the lights run (fixed colormaps, gamma)
wait d_main65.s:pagedrawn == 1 within 90s
at +1s press escape
wait _g_menuactive == 1 within 10s
wait m_menu65.s:currentMenu == 0 within 1
wait m_menu65.s:itemOn == 0 within 1
at +1s press return
wait m_menu65.s:currentMenu == 2 within 10s
wait m_menu65.s:itemOn == 2 within 1
at +1s press return
wait _g_usergame == 1 within 10s
wait _g_gamestate == 0 within 10s
wait long _g_gametic grows 1 within 60s
wait _g_gamemap == 1 within 1
at +2s note lights
poke word _g_gamma 2
at +2s type idbeholdl
at +2s key down left
at +20t key up left
at +2s type idbeholdv
at +2s key down right
at +30t key up right
at +2s poke word _g_gamma 0
at +2s note lights-end
at +1s stop
'''
LIGHTS_SIZE = 12

RUNS = (
    RunSpec('newgame', 'newgame', None, ('still', 'newgame')),
    RunSpec('m5demo', 'title', None, ('demo',)),
    RunSpec('title', None, None, ('title', 'demo3')),
    RunSpec('tour', 'tour', ('shot e1m3', 'e1m3'), ('e1m3', 'tour')),
    RunSpec('lights', 'lights', None, ('lights',)),
)
M5 = {s.key: s for s in capture.SETS}          # still, demo, e1m3
SET_SIZE = 50


# ---------------------------------------------------------------------------
# The programs
# ---------------------------------------------------------------------------

def program(spec: RunSpec, symbols: script.Symbols, work: Path) -> str:
    if spec.script == 'lights':
        return script.compile_script(LIGHTS_SCRIPT, symbols, 'lights')
    if spec.script is None:
        path = work / 'demo3.script'
        path.write_text(lumps.demo_script(7, DEMO_LIMIT_SECONDS))
        return script.compile_script(path.read_text(), symbols, path.name)
    if spec.note_after:
        line, note = spec.note_after
        return capture.program_for(capture.Selection(
            note, spec.script, note, None, 1, line), symbols)
    path = run_script.script_path(spec.script)
    return script.compile_script(path.read_text(), symbols, path.name)


def limit_seconds(spec: RunSpec) -> int:
    return DEMO_LIMIT_SECONDS + 120 if spec.script is None else \
        LIMIT_SECONDS


# ---------------------------------------------------------------------------
# A streamed, bounded run of the machine
# ---------------------------------------------------------------------------

def free_bytes(path: Path) -> int:
    st = os.statvfs(str(path))
    return st.f_bavail * st.f_frsize


def check_disk(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    free = free_bytes(path)
    if free < MIN_FREE_BYTES:
        raise RuntimeError('only %.1f GB free: the captures stop below 20 GB'
                           % (free / 1e9))


def machine_command(prog_path: Path, work: Path, symbols: script.Symbols,
                    seconds: float, extra: Sequence[str]) -> List[str]:
    """The machine's command line, as run_script.Run.execute builds it
    (the stops, the main loop's marks), with the shots in `work`."""
    shots = work / 'shots'
    shots.mkdir(parents=True, exist_ok=True)
    options = ['--input', str(prog_path), '--shot-dir', str(shots),
               '--stop-on-fault', '--marks', str(work / 'marks.txt'),
               '--state', str(work / 'state.json'),
               '--frames', str(script.frames(seconds))]
    for unit, name in run_script.STOPS:
        options += ['--stop-pc', '%06X' % symbols.address(unit + ':' +
                                                          name)]
    for unit, name in (run_script.LOOP, run_script.RENDER):
        options += ['--mark', '%06X' % symbols.address(unit + ':' + name)]
    return [str(title.MACHINE), str(title.MEMORY), '--disk',
            str(title.DISK)] + options + list(extra)


class Streamed:
    """The machine with its dump stream on a pipe, bounded: a wall-time
    watchdog kills its process group, RLIMIT_FSIZE bounds its files, and
    it runs under nice (the ground rules)."""

    def __init__(self, command: Sequence[str], timeout: float):
        self.timeout = timeout
        self.timed_out = False
        preexec = bounded._limits(MAX_FILE, int(timeout) +
                                  bounded.CPU_SLACK)
        self.process = subprocess.Popen(
            ['nice', '-n', '10'] + [str(c) for c in command],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True, preexec_fn=preexec)
        self.watchdog = threading.Timer(timeout, self.kill)
        self.watchdog.daemon = True
        self.watchdog.start()
        self.stderr = b''
        self.reader = threading.Thread(target=self._drain_stderr)
        self.reader.daemon = True
        self.reader.start()

    def _drain_stderr(self) -> None:
        data = self.process.stderr.read()
        self.stderr = data if data else b''

    def kill(self) -> None:
        self.timed_out = True
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def dumps(self) -> Iterator[dumps.Dump]:
        return dumps.read(self.process.stdout)

    def finish(self) -> int:
        try:
            rest = self.process.stdout.read()
            del rest
            code = self.process.wait()
        finally:
            self.watchdog.cancel()
            self.reader.join(5)
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        if self.timed_out:
            raise RuntimeError('ref816 did not finish in %d s'
                               % self.timeout)
        why = bounded.explain(code, MAX_FILE)
        if code:
            raise RuntimeError('ref816 failed (%d%s): %s' % (
                code, ', ' + why if why else '',
                self.stderr.decode(errors='replace')[-2000:]))
        return code


# ---------------------------------------------------------------------------
# The first run: the frames
# ---------------------------------------------------------------------------

class Frame(NamedTuple):
    index: int                  # among the run's R_FillStamps, from 0
    fs_hit: int                 # R_FillStamps arrival, from 1
    cycles: int
    bsp_hit: int
    seam_hit: int
    dm_hit: int
    dm_cycles: int
    dl_hit: int                 # the R_DrawLists call after it (0: none)
    flush_hits: Tuple[int, ...]  # drawAllL arrivals before drawMasked
    gamemap: int
    view: int                   # VW_CUR
    textures_made: int          # R_MakeTextureColumns calls before it,
                                #   since the run's start
    dm3_hit: int = 0            # drawMasked + 3 (after sortSkip)
    ps_hit: int = 0             # playerSkip
    se_hit: int = 0             # stripEarly
    dlr_hit: int = 0            # R_DrawLists' return
    mflush_hits: Tuple[int, ...] = ()   # drawAllL arrivals after
                                        #   drawMasked, before R_DrawLists


def drawlists_return(symbols: script.Symbols) -> int:
    """The address after display's JSL R_DrawLists (d_main65.s:502), read
    from the release's memory image: the JSL is found by its bytes
    after the label dmLevel77, never assumed."""
    from ref816 import refimage
    mem = refimage.load(refimage.read(title.MEMORY))
    start = symbols.address('d_main65.s:dmLevel77')
    target = symbols.address(capture.ENTRY)
    want = bytes([0x22]) + target.to_bytes(3, 'little')
    code = mem.get(start, 32)
    at = code.find(want)
    if at < 0:
        raise RuntimeError('no JSL R_DrawLists after dmLevel77')
    return start + at + 4


def routines(symbols: script.Symbols) -> Dict[str, int]:
    return {
        'fs': symbols.address('R_FillStamps'),
        'bsp': symbols.address('R_RenderBSPNode'),
        'seam': symbols.address('weaponClipSame') + 3,
        'flush': symbols.address(capture.FLUSH),
        'dm': symbols.address('drawMasked'),
        'dl': symbols.address(capture.ENTRY),
        'tex': symbols.address('R_MakeTextureColumns'),
        'dm3': symbols.address('drawMasked') + 3,
        'ps': symbols.address('playerSkip'),
        'se': symbols.address('stripEarly'),
        'dlr': drawlists_return(symbols),
    }


MARKED = ('fs', 'bsp', 'seam', 'flush', 'dm', 'dl', 'tex', 'dm3', 'ps',
          'se', 'dlr')


def mark_options(r: Dict[str, int]) -> List[str]:
    out = []
    for key in MARKED:
        if key in r:
            out += ['--mark', '%06X' % r[key]]
    return out


def small_point(symbols: script.Symbols) -> str:
    return dumps.resolve('pc=R_FillStamps,ranges=_g_gamemap:2+%06X:2'
                         % VW_CUR, symbols)


def frames_of(log: Sequence[marks.Entry], small: Dict[int, Tuple[int, int]],
              r: Dict[str, int]) -> List[Frame]:
    """The run's frames from its marks: each R_FillStamps and the marks
    of the same frame after it."""
    names = {'%06X' % v: k for k, v in r.items()}
    counts = {k: 0 for k in r}
    frames: List[Dict] = []
    textures = 0
    cur = None
    for e in log:
        if e.kind != 'mark' or e.what not in names:
            continue
        key = names[e.what]
        counts[key] += 1
        hit = counts[key]
        if key == 'fs':
            cur = {'index': len(frames), 'fs_hit': hit, 'cycles': e.cycles,
                   'bsp_hit': 0, 'seam_hit': 0, 'dm_hit': 0,
                   'dm_cycles': 0, 'dl_hit': 0, 'flush_hits': [],
                   'textures_made': textures, 'dm3_hit': 0, 'ps_hit': 0,
                   'se_hit': 0, 'dlr_hit': 0, 'mflush_hits': []}
            frames.append(cur)
        elif key == 'tex':
            textures += 1
        elif cur is None:
            continue
        elif key == 'bsp' and not cur['bsp_hit']:
            cur['bsp_hit'] = hit
        elif key == 'seam' and not cur['seam_hit']:
            cur['seam_hit'] = hit
        elif key == 'flush' and not cur['dm_hit']:
            cur['flush_hits'].append(hit)
        elif key == 'flush' and not cur['dl_hit']:
            cur['mflush_hits'].append(hit)
        elif key == 'dm' and not cur['dm_hit']:
            cur['dm_hit'] = hit
            cur['dm_cycles'] = e.cycles
        elif key == 'dl' and not cur['dl_hit']:
            cur['dl_hit'] = hit
        elif key in ('dm3', 'ps', 'se', 'dlr') and cur['dm_hit'] and \
                not cur[key + '_hit']:
            cur[key + '_hit'] = hit
    out = []
    for f in frames:
        gamemap, view = small.get(f['fs_hit'], (0, 0))
        out.append(Frame(f['index'], f['fs_hit'], f['cycles'], f['bsp_hit'],
                         f['seam_hit'], f['dm_hit'], f['dm_cycles'],
                         f['dl_hit'], tuple(f['flush_hits']), gamemap, view,
                         f['textures_made'], f['dm3_hit'], f['ps_hit'],
                         f['se_hit'], f['dlr_hit'],
                         tuple(f['mflush_hits'])))
    return out


def usable(f: Frame) -> bool:
    return bool(f.bsp_hit and f.seam_hit and f.dm_hit and f.dm3_hit and
                f.ps_hit and f.se_hit and f.dl_hit and f.dlr_hit) and \
        f.view == FULL_VIEW


def evenly(frames: Sequence[Frame], count: int) -> List[Frame]:
    n = len(frames)
    if n < count:
        raise ValueError('%d frames, not %d' % (n, count))
    if count == 1:
        return [frames[0]]
    return [frames[round(i * (n - 1) / (count - 1))] for i in range(count)]


def choose(spec: RunSpec, log: Sequence[marks.Entry],
           frames: Sequence[Frame], r: Dict[str, int]
           ) -> Dict[str, List[Frame]]:
    """The chosen frames of each set of the run (module docstring)."""
    level = [f for f in frames[:-1] if usable(f)]
    notes = {}
    for e in log:
        if e.kind == 'note':
            notes.setdefault(e.what, e.cycles)
    out = {}
    for name in spec.sets:
        if name in M5:
            hits, before = capture.calls(log, r['dl'], r['flush'])
            chosen = capture.choose(M5[name], hits, before)
            by_dl = {f.dl_hit: f for f in frames if f.dl_hit}
            picked = []
            for h in chosen:
                f = by_dl.get(h.hit)
                if f is None or not usable(f):
                    raise RuntimeError('%s: the frame of R_DrawLists call %d '
                                       'is not usable' % (name, h.hit))
                picked.append(f)
            out[name] = picked
        elif name == 'newgame':
            out[name] = evenly(level, SET_SIZE)
        elif name == 'title':
            lo, hi = notes['demo'], notes['demo-end']
            out[name] = evenly([f for f in level if lo < f.cycles < hi],
                               SET_SIZE)
        elif name == 'demo3':
            lo, hi = notes['demo'], notes['demo-end']
            out[name] = [f for f in level if lo < f.cycles < hi]
        elif name == 'lights':
            lo, hi = notes['lights'], notes['lights-end']
            out[name] = evenly([f for f in level if lo < f.cycles < hi],
                               LIGHTS_SIZE)
        elif name == 'tour':
            maps = sorted({f.gamemap for f in level})
            if maps != list(range(1, 10)):
                raise RuntimeError('tour: maps %s, not E1M1-E1M9' % maps)
            base, extra = divmod(SET_SIZE, len(maps))
            picked = []
            for i, m in enumerate(maps):
                of_map = [f for f in level if f.gamemap == m]
                picked += evenly(of_map, base + (1 if i < extra else 0))
            out[name] = picked
        else:
            raise ValueError(name)
    return out


def names_of(chosen: Dict[str, List[Frame]]) -> List[Tuple[str, Frame]]:
    out = []
    for name, frames in chosen.items():
        if name in M5:
            width = len(str(M5[name].count))
            out += [('%s-%0*d' % (name, width, i), f)
                    for i, f in enumerate(frames, 1)]
        elif name == 'demo3':
            out += [('%s-%03d' % (name, f.index), f) for f in frames]
        else:
            out += [('%s-%02d' % (name, i), f)
                    for i, f in enumerate(frames, 1)]
    return out


def clusters(indexes: Sequence[int], most: int) -> List[Tuple[int, int]]:
    """The chosen frame indexes as at most `most` ranges, the fewest
    frames dumped: the closest neighbours merge first."""
    runs = [[i, i] for i in sorted(set(indexes))]
    while len(runs) > most:
        k = min(range(len(runs) - 1),
                key=lambda j: runs[j + 1][0] - runs[j][1])
        runs[k][1] = runs[k + 1][1]
        del runs[k + 1]
    return [tuple(x) for x in runs]


# ---------------------------------------------------------------------------
# The second run: points and call logs
# ---------------------------------------------------------------------------

def ranges_of(kind: str, s: script.Symbols) -> str:
    near = '02'
    dp = '000900:768'
    zone = '06-09'
    bv = '%06X:1280' % (MM_BV + 0xB500)
    weapon = '0AC500:1024'
    spans = '%06X:%d' % FS_SPANS
    screen = '%06X:%d' % SCREEN
    if kind == 'P0':
        return '+'.join([near, dp, zone, bv, weapon,
                         '%06X:%d' % (s.address('FLATCM'), 34 * 32),
                         '%06X:%d' % (s.address('iigs_shrcmapA'),
                                      2 * 34 * 256),
                         '230000:32768', spans, '%06X:%d' % MM_SPRBOUND])
    if kind == 'P0b':
        return '+'.join([near, dp, bv, weapon, spans])
    if kind == 'P1':
        return '+'.join([near, '%06X:2' % MM_WPOK])
    if kind == 'P2':
        return '+'.join(['1D', near, screen])
    if kind == 'P3':
        return '+'.join([near, '1D', spans, bv, weapon, dp, zone])
    if kind == 'P3s':
        return '+'.join([near, '000A00:256'])
    if kind == 'P3w':
        return '+'.join(['1D', near, spans])
    if kind in ('PS', 'P5'):
        return screen
    if kind == 'P4':
        return '+'.join(['1D', near, spans, weapon, screen, '000AB0:2'])
    raise ValueError(kind)


class Plan(NamedTuple):
    points: List[Tuple[str, str]]       # (kind, point text)
    full: Dict[int, str]                # fs_hit -> level source name
    expected_bytes: int
    expected_dumps: int


def plan(spec: RunSpec, frames: Sequence[Frame],
         chosen: List[Tuple[str, Frame]], symbols: script.Symbols,
         r: Dict[str, int]) -> Plan:
    by_index = {f.index: f for f in frames}
    # the full dumps: the first chosen frame of each map, and the first
    # chosen frame after each texture made in play
    full = {}
    seen = {}
    for name, f in sorted(chosen, key=lambda x: x[1].index):
        key = (f.gamemap, f.textures_made)
        if key in seen:
            continue
        seen[key] = f
        full[f.fs_hit] = '%s-e1m%d-t%d' % (spec.key, f.gamemap,
                                           f.textures_made)
    # ranges of frames: the points each takes, within ref816's 64
    most = (MAX_POINTS - 2 - len(full)) // len(FRAME_POINTS)
    ranges = clusters([f.index for _, f in chosen], most)
    points = [('SMALL', small_point(symbols))]
    count, size = 0, 0
    where = {'P0': 'fs', 'P1': 'seam', 'P0b': 'bsp', 'P3': 'dm',
             'P3s': 'dm3', 'P3w': 'ps', 'PS': 'se', 'P4': 'dl', 'P5': 'dlr'}
    for lo, hi in ranges:
        a, b = by_index[lo], by_index[hi]
        for kind, field, _ in FRAME_POINTS:
            points.append((kind, dumps.resolve(
                'pc=%06X,hits=%d-%d,ranges=%s' % (
                    r[where[kind]], getattr(a, field), getattr(b, field),
                    ranges_of(kind, symbols)), symbols)))
        n = hi - lo + 1
        count += len(FRAME_POINTS) * n
        size += n * sum(DUMP_BYTES[k] for k, _, _ in FRAME_POINTS)
    points.append(('P2', dumps.resolve('pc=drawAllL,ranges=%s'
                                       % ranges_of('P2', symbols), symbols)))
    flushes = sum(len(f.flush_hits) + len(f.mflush_hits) for f in frames)
    count += flushes
    size += flushes * DUMP_BYTES['P2']
    for hit in sorted(full):
        points.append(('P0F', dumps.resolve('pc=R_FillStamps,hits=%d' % hit,
                                            symbols)))
    count += len(full) + len(frames)
    size += len(full) * DUMP_BYTES['P0F'] + len(frames) * 4096
    if len(points) > MAX_POINTS:
        raise RuntimeError('%d points: ref816 takes %d' % (len(points),
                                                           MAX_POINTS))
    return Plan(points, full, size, count)


def call_routines() -> List[str]:
    return [
        'R_StoreWallRange,in=dp:_Dp:2+BSPDP:12+floorplane_color:2+'
        'ceilingplane_color:2+worldbottom:4+ds_p:2+lastopening:2,'
        'out=solidcol:160',
        'r_bsp65.s:vtxAngle,entry=1',
        'R_FillStamps,entry=1',
        'R_MakeTextureColumns,entry=1',
        'r_bsp65.s:viewSide,entry=1,hits=1,in=s+1:2',
        # milestone 8 (RENDER-MASKED.md 4.1): the listed sectors, and the
        # masked phase's calls
        'R_AddSprites,entry=1,in=dp:_Dp+4:3',
        # (R_DrawSprite and the weapon enter R_DrawVisSprite by JML)
        'R_DrawVisSprite,entry=1,jumps=1,in=dp:_Dp:4+VS_CLIP:2+'
        'mfloorclip:4+mceilingclip:4+floorclip:320+ceilingclip:320',
        'R_RenderMaskedSegRange,entry=1,in=FR_DS:2+dp:_Dp+4:4',
        'r_frame65.s:maskedSeg,entry=1,in=FR_DS:2',
        'wcProf,entry=1',
        'wdProf,entry=1',
    ]


# the masked phase's routines of the call log, by the key calls.json
# stores their calls under (a frame's calls from drawMasked on)
MASKED_CALLS = {'R_DrawVisSprite': 'drawvis',
                'R_RenderMaskedSegRange': 'maskedseg',
                'r_frame65.s:maskedSeg': 'maskeddrawseg', 'wdProf': 'wdprof'}


def write_dump(path: Path, d: dumps.Dump) -> None:
    head = json.dumps(d.header, separators=(',', ':')).encode() + b'\n'
    path.write_bytes(zlib.compress(head + d.data, 6))


def load_dump(path: Path) -> dumps.Dump:
    """A dump stored by this tool."""
    raw = zlib.decompress(Path(path).read_bytes())
    nl = raw.index(b'\n')
    header = json.loads(raw[:nl])
    data = raw[nl + 1:]
    if len(data) != header['bytes']:
        raise ValueError('%s is cut short' % path)
    return dumps.Dump(header, data)


def load_ram(path: Path) -> bytes:
    """A level source: all RAM (banks $00-$7F, $E0, $E1)."""
    data = zlib.decompress(Path(path).read_bytes())
    if len(data) != 130 * 0x10000:
        raise ValueError('%s is not a whole RAM' % path)
    return data


def frames_of_cycles(bounds: Sequence[Tuple[int, int, str]], cycles: int
                     ) -> List[str]:
    """The chosen frames (names: a frame may be in two sets) whose
    R_FillStamps to drawMasked holds `cycles`."""
    return [name for lo, hi, name in bounds if lo <= cycles < hi]


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def run_one(spec: RunSpec, symbols: script.Symbols, out: Path,
            log_file=None) -> Dict:
    def say(text):
        line = '[%s] %s' % (spec.key, text)
        print(line, flush=True)
        if log_file:
            log_file.write(line + '\n')
            log_file.flush()

    check_disk(out)
    tmp = Path(tempfile.mkdtemp(prefix='tmp-render-%s-' % spec.key,
                                dir=str(make_image.BUILD)))
    try:
        prog = program(spec, symbols, tmp)
        seconds = limit_seconds(spec)
        r = routines(symbols)

        # -- the first run: marks and the small dumps
        w1 = tmp / 'first'
        w1.mkdir()
        (w1 / 'input.txt').write_text(prog)
        start = time.time()
        cmd = machine_command(w1 / 'input.txt', w1, symbols, seconds,
                              mark_options(r) + [
                                  '--dump-at', small_point(symbols),
                                  '--dump-stream', '-',
                                  '--dump-limit', str(64 << 20)])
        run = Streamed(cmd, RUN_TIMEOUT)
        small = {}
        for d in run.dumps():
            data = d.data
            small[d.header['hit']] = (int.from_bytes(data[0:2], 'little'),
                                      int.from_bytes(data[2:4], 'little'))
        run.finish()
        state1 = json.loads((w1 / 'state.json').read_text())
        log1 = marks.read(w1 / 'marks.txt')
        problems = run_script.problems(state1, log1, symbols, prog)
        if problems:
            raise RuntimeError('first run: ' + '; '.join(problems))
        frames = frames_of(log1, small, r)
        chosen_sets = choose(spec, log1, frames, r)
        chosen = names_of(chosen_sets)
        textures = [e for e in log1 if e.kind == 'mark' and
                    e.what == '%06X' % r['tex']]
        say('first run: %d frames, %d chosen, %d textures made, %.0f s'
            % (len(frames), len(chosen), len(textures), time.time() - start))

        # -- the second run
        p = plan(spec, frames, chosen, symbols, r)
        check_disk(out)
        w2 = tmp / 'second'
        w2.mkdir()
        (w2 / 'input.txt').write_text(prog)
        call_log = w2 / 'calls.log'
        extra = mark_options(r)
        for kind, text in p.points:
            extra += ['--dump-at', text]
        extra += ['--dump-stream', '-', '--dump-limit',
                  str(int(p.expected_bytes * 1.5) + (64 << 20)),
                  '--dump-max', str(int(p.expected_dumps * 1.5) + 1000)]
        extra += calllog.options(call_routines(), call_log)
        extra += ['--call-log-limit', str(CALL_LOG_LIMIT)]
        start = time.time()
        run = Streamed(machine_command(w2 / 'input.txt', w2, symbols,
                                       seconds, extra), RUN_TIMEOUT)
        kinds = [k for k, _ in p.points]
        by_hit: Dict[Tuple[str, int], List[Tuple[str, str]]] = {}
        for name, f in chosen:
            keys = [((kind, getattr(f, field)), what)
                    for kind, field, what in FRAME_POINTS]
            keys += [(('P2', h), 'p2-%d' % k)
                     for k, h in enumerate(f.flush_hits)]
            keys += [(('P2', h), 'p2m-%d' % k)
                     for k, h in enumerate(f.mflush_hits)]
            for key, what in keys:
                by_hit.setdefault(key, []).append((name, what))
        staging = tmp / 'frames'
        staging.mkdir()
        got: Dict[str, set] = {name: set() for name, _ in chosen}
        full_got = {}
        LEVEL_SOURCES.mkdir(parents=True, exist_ok=True)
        for d in run.dumps():
            kind = kinds[d.header['point']]
            if kind == 'SMALL':
                continue
            if kind == 'P0F':
                name = p.full[d.header['hit']]
                if len(d.data) != 130 * 0x10000:
                    raise RuntimeError('full dump %s: %d bytes'
                                       % (name, len(d.data)))
                target = LEVEL_SOURCES / (name + '.ram.z')
                target.write_bytes(zlib.compress(d.data, 6))
                full_got[name] = {
                    'cycles': d.header['cycles'],
                    'switches': d.header.get('switches'),
                    'cpu': d.header.get('cpu'),
                    'sha256': hashlib.sha256(d.data).hexdigest()}
                continue
            for name, what in by_hit.get((kind, d.header['hit']), ()):
                directory = staging / name
                directory.mkdir(exist_ok=True)
                write_dump(directory / (what + '.dump.z'), d)
                got[name].add(what)
        run.finish()
        state2 = json.loads((w2 / 'state.json').read_text())
        log2 = (w2 / 'marks.txt').read_bytes()
        if state2['ram_fnv1a64'] != state1['ram_fnv1a64'] or \
                log2 != (w1 / 'marks.txt').read_bytes():
            raise RuntimeError('the capturing run differs from the first')
        problems = run_script.problems(state2, marks.read(w2 / 'marks.txt'),
                                       symbols, prog)
        if problems:
            raise RuntimeError('second run: ' + '; '.join(problems))
        say('second run: %d frames stored, %d full dumps, %.0f s'
            % (len(got), len(full_got), time.time() - start))

        # -- the calls, by frame
        head, lines, end = calllog.read(call_log)
        rnames = [x['name'] for x in head['routines']]
        bounds = sorted((f.cycles, f.dm_cycles, name) for name, f in chosen)
        # the masked phase: drawMasked to the next frame's R_FillStamps
        after = {f.index: f for f in frames}
        mbounds = sorted((f.dm_cycles, after[f.index + 1].cycles
                          if f.index + 1 in after else 1 << 62, name)
                         for name, f in chosen)
        per: Dict[str, Dict] = {name: {'storewall': [], 'vtxangle': 0,
                                       'textures': [], 'addsprites': [],
                                       'wcprof': 0, 'drawvis': [],
                                       'maskedseg': [], 'maskeddrawseg': [],
                                       'wdprof': 0}
                                for name, _ in chosen}
        viewside = None
        for line in lines:
            routine = rnames[line['routine']]
            if routine == 'r_bsp65.s:viewSide':
                viewside = line
                continue
            if routine in MASKED_CALLS:
                for name in frames_of_cycles(mbounds, line['cycles']):
                    key = MASKED_CALLS[routine]
                    if key == 'wdprof':
                        per[name][key] += 1
                    else:
                        per[name][key].append({'in': line['in'],
                                               'from': line.get('from')})
                continue
            for name in frames_of_cycles(bounds, line['cycles']):
                if routine == 'R_StoreWallRange':
                    per[name]['storewall'].append(line)
                elif routine == 'r_bsp65.s:vtxAngle':
                    per[name]['vtxangle'] += 1
                elif routine == 'R_MakeTextureColumns':
                    per[name]['textures'].append(line['in']['a'])
                elif routine == 'R_AddSprites':
                    per[name]['addsprites'].append(
                        [int.from_bytes(bytes.fromhex(line['in']['mem'][0]),
                                        'little'), line['in']['a']])
                elif routine == 'wcProf':
                    per[name]['wcprof'] += 1

        # -- the frames
        sources = sorted(p.full.items())
        results = []
        for name, f in chosen:
            missing = ({what for _, _, what in FRAME_POINTS} | {
                'p2-%d' % k for k in range(len(f.flush_hits))} | {
                'p2m-%d' % k for k in range(len(f.mflush_hits))}) - \
                got[name]
            if missing:
                raise RuntimeError('%s: no dumps %s' % (name,
                                                        sorted(missing)))
            level_src = None
            for hit, src in sources:
                fr = next(x for x in frames if x.fs_hit == hit)
                if fr.gamemap == f.gamemap and \
                        fr.textures_made == f.textures_made and \
                        hit <= f.fs_hit:
                    level_src = src
            if level_src is None:
                raise RuntimeError('%s: no level source' % name)
            directory = staging / name
            meta = {'format': FORMAT, 'name': name,
                    'set': name.rsplit('-', 1)[0], 'run': spec.key,
                    'script': spec.script or 'demo3',
                    'frame': f._asdict(), 'level_src': level_src,
                    'flushes': len(f.flush_hits),
                    'mflushes': len(f.mflush_hits)}
            (directory / 'frame.json').write_text(
                json.dumps(meta, indent=1) + '\n')
            (directory / 'calls.json').write_text(
                json.dumps(per[name], separators=(',', ':')) + '\n')
            target = out / name
            if target.exists():
                shutil.rmtree(str(target))
            shutil.move(str(directory), str(target))
            results.append({'name': name, 'walls':
                            len(per[name]['storewall']),
                            'vtxangle': per[name]['vtxangle'],
                            'flushes': len(f.flush_hits),
                            'level_src': level_src})
        for name, info in full_got.items():
            (LEVEL_SOURCES / (name + '.json')).write_text(json.dumps(
                dict(info, name=name, run=spec.key), indent=1) + '\n')
        if viewside is not None:
            (LEVEL_SOURCES / ('%s-viewside.json' % spec.key)).write_text(
                json.dumps(viewside, indent=1) + '\n')
        return {'run': spec.key, 'frames': results,
                'textures_made': len(textures),
                'full_dumps': sorted(full_got),
                'frames_in_run': len(frames)}
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--runs', default=','.join(s.key for s in RUNS))
    parser.add_argument('--out', type=Path, default=FRAMES)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args(argv)
    wanted = args.runs.split(',')
    specs = [s for s in RUNS if s.key in wanted]
    if len(specs) != len(wanted):
        parser.error('unknown run in %s' % args.runs)
    for path in (make_image.RELEASE_IMAGE, make_image.LINKMAP):
        if not path.exists():
            print('%s is missing: run python3 tools/fetch_upstream.py and '
                  'python3 tools/v816/imgmatch.py first' % path,
                  file=sys.stderr)
            return 1
    title.build_machine()
    title.ensure_image()
    symbols = dumps.symbols()
    args.out.mkdir(parents=True, exist_ok=True)
    check_disk(args.out)
    with open(str(RENDER / 'rendercap.log'), 'a') as log_file:
        with ThreadPoolExecutor(max(1, min(2, args.jobs))) as pool:
            results = list(pool.map(
                lambda s: run_one(s, symbols, args.out, log_file), specs))
    report_path = RENDER / 'rendercap.json'
    report = json.loads(report_path.read_text()) if report_path.exists() \
        else {}
    for res in results:
        report[res['run']] = res
    report_path.write_text(json.dumps(report, indent=1) + '\n')
    for res in results:
        walls = [x['walls'] for x in res['frames']]
        print('%s: %d frames of %d, walls a frame %d-%d, %d textures made, '
              'full dumps %s' % (res['run'], len(res['frames']),
                                 res['frames_in_run'], min(walls),
                                 max(walls), res['textures_made'],
                                 ', '.join(res['full_dumps'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
