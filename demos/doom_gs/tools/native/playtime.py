#!/usr/bin/env python3
"""The play build's timing on a2vm (docs/SPEED.md 1-2): ms a frame, FPS,
tics, the kernel's steps and the tic phase's group loads, for one scene.

Usage:  python3 tools/native/playtime.py --scene still|walk|demo3
            [--profile f121|fastpath] [--disk FILE] [--play DIR]
            [--gametics G0-G1] [--window S0-S1] [--seconds S]
            [--idle exact|old|none] [--json OUT] [--keep DIR]

The disk (default build/native/DOOM.hdv) boots as playdisk.run boots it:
the MLI trap, the memory API, --cost-timed on the profile, and the
exact idle skips (playdisk.run's `idle`; --idle old measures the
skip of milestone 11, docs/SPEED.md 1 "The measurement artifact"). The
play link (--play, default build/native/play) gives the PCs, as labels
and symbols, never as fixed addresses; the disk must be the one that
link builds (playdisk.build, compared byte for byte), so the labels are
the disk's.

The scenes (the input is a2vm's, on the model's clock):

  still   a new game (RETURN at 8 s and 9 s: E1M1, skill 2), the player
          standing; the frames whose ends fall in 15-25 s (a 26 s run)
  walk    the same, the up arrow held from 12 s and a mouse turn of 160
          every 2 s from 13 s; the frames in 14-32 s (a 33 s run)
  demo3   no input: the title loop to its demo3 on E1M7 (the benchmark's
          demo); the frames cut by gametic, 1052-1796 by default, so that
          builds of different speeds compare the same game frames (at
          most 200 s of model time; the run ends once the gametic passes
          the cut, a2vm's --stop-word; give --seconds for a slower build)

--window S0-S1 (seconds) or --gametics G0-G1 overrides a scene's cut. A
frame is the time between two K_END dispatches of the kernel (dl_kern.s
k_end, which starts the next K_TIC); with gametics, a frame counts when
the gametic at its end is in (G0, G1].

The data comes from a2vm's --pclog (tools/a2vm/README.md, "The PC log"),
bounded by --pclog-limit: a line at each kernel dispatch (k_end, k_tic1,
k_load, k_call and its jsr, k_wload, k_mload, k_menu), at far_pload (the
image a K_LOAD brings), at gcall.s's gr_load (a group into its slot) and
at the VBL handler, with the gametic and the step's call target. Reported:

  frames, ms a frame (mean, median, max), FPS, tics a frame and a second;
  the kernel's steps in ms a frame: K_TIC (the tic image back, the brain,
  the tics, the next list), K_WLOAD, nr_frame, K_MLOAD, nm_masked,
  nm_bkload, nb_frame, K_LOAD P2DW, s2_frame and any other step;
  gr_load calls a tic (in K_TIC only: the tic image's), VBL interrupts a
  frame.

The run's directory (under build/, or --keep) is deleted after it.
"""

import argparse
import json
import shutil
import statistics
import sys
import tempfile
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(TOOLS))

from a2vm import costs  # noqa: E402
from native import playdisk as P, playlink as PK  # noqa: E402

PCLOG_LIMIT = 1500000           # lines (about 70 MB): demo3's 200 s is
                                # about 300,000
SCENES = {
    'still': {'seconds': 26.0, 'window': (15.0, 25.0)},
    'walk': {'seconds': 33.0, 'window': (14.0, 32.0)},
    'demo3': {'seconds': 200.0, 'gametics': (1052, 1796)},
}
# the steps in the order of a level's frame (dl_disp.s c_level)
STEP_ORDER = ['K_TIC', 'K_WLOAD', 'nr_frame', 'K_MLOAD', 'nm_masked',
              'nm_bkload', 'nb_frame', 'K_LOAD P2DW', 's2_frame']
# the step a dispatch label starts
DISPATCH = OrderedDict([('k_end', 'K_TIC'), ('k_tic1', 'K_TIC'),
                        ('k_load', 'K_LOAD'), ('k_call', 'K_CALL'),
                        ('k_wload', 'K_WLOAD'), ('k_mload', 'K_MLOAD'),
                        ('k_menu', 'K_MENU'), ('dl_halt', 'K_HALT')])
# the images a K_LOAD may bring (their banks' symbols), and the prefix of
# their entries' XS_ names
IMAGES = [('P2DW', 's2_'), ('OVLW', 'OVLW'), ('PALW', 'palw_'),
          ('AMAPW', 'am_'), ('FINW', 'fin_'), ('WIW', 'wi_'),
          ('MENUW', 'm_')]


class TimeError(Exception):
    pass


def scene_script(scene: str, hz: float) -> str:
    def at(s: float) -> str:
        return 'cycle %d' % int(s * hz)
    if scene == 'demo3':
        return ''
    lines = ['%s key 13' % at(8), '%s key 13' % at(9)]
    if scene == 'walk':
        lines.append('%s hold 0x0B' % at(12))
        lines += ['%s mouse 160 0' % at(s) for s in range(13, 32, 2)]
        lines.append('%s release' % at(32))
    return '\n'.join(lines) + '\n'


class Probe(NamedTuple):
    pcs: Dict[int, str]          # PC: its name
    bytes: List[str]             # --pclog-bytes, in order
    names: Dict[int, List[str]]  # a K_CALL target: its XS_ names
    banks: Dict[int, str]        # a bank: its image
    hz: float


def probe(disk: P.Disk, profile: str) -> Probe:
    """The PCs to log and how to read the lines, from the play link."""
    lab = P.labels(disk)
    sym = P.symbols(disk.play)
    pcs = {}
    for name in DISPATCH:
        pcs[lab[name]] = name
    pcs[lab['k_jsr']] = 'k_jsr'
    pcs[sym['XS_far_pload']] = 'far_pload'
    pcs[sym['XS_pl_vbl']] = 'pl_vbl'
    tic = PK.tic_build(disk.play).labels
    pcs[tic['gr_load']] = 'gr_load'
    if len(pcs) != len(DISPATCH) + 4:
        raise TimeError('two logged labels share a PC')
    # the jsr's operand (in the main card, the kernel's), the gametic
    gametic = sym['G_GAMETIC']
    log_bytes = ['lc.%X' % (lab['k_jsr'] + 1), 'lc.%X' % (lab['k_jsr'] + 2)]
    log_bytes += ['%X' % (gametic + i) for i in range(4)]
    names = defaultdict(list)
    for k, v in sym.items():
        if k.startswith('XS_'):
            names[v].append(k[3:])
    names[sym['OVLW_LO']].append('OVLW')
    banks = {sym['%s_BANK' % n]: n for n, _ in IMAGES + [('WCODE', ''),
                                                          ('MCODE', '')]
             if '%s_BANK' % n in sym}
    hz = costs.parameters(P.PROFILES[profile])['fabric_mhz'] * 1e6
    return Probe(pcs, log_bytes, dict(names), banks, hz)


class Line(NamedTuple):
    t: int
    name: str
    a: int
    x: int
    y: int
    target: int                  # the k_jsr operand
    gametic: int


def read_log(path: Path, pr: Probe) -> List[Line]:
    out = []
    with open(str(path)) as handle:
        for text in handle:
            if text.startswith('#'):
                continue
            f = text.split()
            if len(f) != 7 + len(pr.bytes):
                raise TimeError('a pclog line of %d fields' % len(f))
            b = [int(v, 16) for v in f[7:]]
            out.append(Line(int(f[0]), pr.pcs[int(f[1], 16)], int(f[2], 16),
                            int(f[3], 16), int(f[4], 16), b[0] | b[1] << 8,
                            b[2] | b[3] << 8 | b[4] << 16 | b[5] << 24))
    return out


def call_name(pr: Probe, target: int, image: Optional[str]) -> str:
    cands = pr.names.get(target, [])
    if image:
        prefix = dict(IMAGES + [('WCODE', 'nr_'), ('MCODE', 'nm_')]).get(
            image)
        mine = [c for c in cands if prefix and c.startswith(prefix)]
        if len(mine) == 1:
            return mine[0]
    if len(cands) == 1:
        return cands[0]
    return '|'.join(sorted(cands)) or 'call $%04X' % target


class Frame(NamedTuple):
    start: int
    end: int
    gametic: int                 # at its end
    tics: int
    steps: List[Tuple[str, int]]  # (name, clocks)
    loads: int                   # gr_load in K_TIC
    irqs: int


def frames_of(lines: List[Line], pr: Probe) -> List[Frame]:
    """The frames between consecutive K_END dispatches, with their
    steps."""
    out = []
    cur = None                   # the frame being read
    step = None                  # [name, start]
    image = None
    for ln in lines:
        if ln.name in DISPATCH:
            if cur is not None and step is not None:
                cur['steps'].append((step[0], ln.t - step[1]))
            kind = DISPATCH[ln.name]
            if ln.name == 'k_end':
                if cur is not None:
                    out.append(Frame(cur['start'], ln.t, ln.gametic,
                                     ln.gametic - cur['gametic'],
                                     cur['steps'], cur['loads'],
                                     cur['irqs']))
                cur = {'start': ln.t, 'gametic': ln.gametic, 'steps': [],
                       'loads': 0, 'irqs': 0}
            step = [kind, ln.t]
            if kind == 'K_WLOAD':
                image = 'WCODE'
            elif kind == 'K_MLOAD':
                image = 'MCODE'
            elif kind == 'K_TIC':
                image = 'TIC'
            elif kind == 'K_LOAD':
                image = None
        elif ln.name == 'k_jsr' and step is not None and \
                step[0] == 'K_CALL':
            step[0] = call_name(pr, ln.target, image)
        elif ln.name == 'far_pload' and step is not None and \
                step[0] == 'K_LOAD' and image is None:
            image = pr.banks.get(ln.y, 'bank $%02X' % ln.y)
            step[0] = 'K_LOAD %s' % image
        elif ln.name == 'gr_load' and cur is not None and \
                step is not None and step[0] == 'K_TIC':
            cur['loads'] += 1
        elif ln.name == 'pl_vbl' and cur is not None:
            cur['irqs'] += 1
    return out


def report(frames: List[Frame], pr: Probe, cut: str,
           window: Optional[Tuple[float, float]],
           gametics: Optional[Tuple[int, int]]) -> Dict[str, Any]:
    if gametics:
        g0, g1 = gametics
        sel = [f for f in frames if g0 < f.gametic <= g1]
    else:
        t0, t1 = window[0] * pr.hz, window[1] * pr.hz
        sel = [f for f in frames if t0 <= f.start and f.end <= t1]
    if not sel:
        raise TimeError('no frame in %s (the run has %d frames, gametic '
                        '%s)' % (cut, len(frames),
                                 '%d-%d' % (frames[0].gametic,
                                            frames[-1].gametic)
                                 if frames else '-'))
    ms = [(f.end - f.start) / pr.hz * 1000 for f in sel]
    total = sum(ms)
    tics = sum(f.tics for f in sel)
    steps = defaultdict(float)
    for f in sel:
        for name, clocks in f.steps:
            steps[name] += clocks / pr.hz * 1000
    order = [s for s in STEP_ORDER if s in steps] + \
        sorted(s for s in steps if s not in STEP_ORDER)
    loads = sum(f.loads for f in sel)
    return OrderedDict([
        ('cut', cut),
        ('frames', len(sel)),
        ('gametic', [sel[0].gametic - sel[0].tics, sel[-1].gametic]),
        ('seconds', [round(sel[0].start / pr.hz, 3),
                     round(sel[-1].end / pr.hz, 3)]),
        ('ms_mean', round(total / len(sel), 2)),
        ('ms_median', round(statistics.median(ms), 2)),
        ('ms_max', round(max(ms), 2)),
        ('fps', round(1000.0 * len(sel) / total, 3)),
        ('tics_frame', round(tics / len(sel), 3)),
        ('tics_second', round(tics * 1000.0 / total, 2)),
        ('steps_ms', OrderedDict((s, round(steps[s] / len(sel), 2))
                                 for s in order)),
        ('loads_tic', round(loads / tics, 2) if tics else None),
        ('loads_frame', round(loads / len(sel), 2)),
        ('irqs_frame', round(sum(f.irqs for f in sel) / len(sel), 2)),
    ])


def the_disk(play: Path, disk_path: Optional[Path], work: Path) -> P.Disk:
    """The play link's disk, checked to be `disk_path` byte for byte (None:
    the link's own, as built)."""
    built = P.build(play, work / 'link.hdv')
    if disk_path is not None and \
            built.path.read_bytes() != Path(disk_path).read_bytes():
        raise TimeError('%s is not the disk the play link %s builds (give '
                        'its --play)' % (disk_path, play))
    (work / 'link.hdv').unlink()
    return built


def measure(scene: str, profile: str = 'f121',
            disk: Optional[Path] = P.OUT,
            play: Path = P.PLAY, gametics: Optional[Tuple[int, int]] = None,
            window: Optional[Tuple[float, float]] = None,
            seconds: Optional[float] = None, idle: str = 'exact',
            keep: Optional[Path] = None, a2vm: Path = P.A2VM,
            timeout: float = 3600.0) -> Dict[str, Any]:
    spec = SCENES[scene]
    if gametics is None and window is None:
        gametics = spec.get('gametics')
        window = spec.get('window')
    seconds = seconds or spec['seconds']
    if window and window[1] > seconds:
        seconds = window[1] + 1
    work = Path(keep) if keep else Path(tempfile.mkdtemp(
        prefix='tmp-playtime-', dir=str(P.BUILD)))
    try:
        work.mkdir(parents=True, exist_ok=True)
        d = the_disk(Path(play), Path(disk) if disk else None, work)
        pr = probe(d, profile)
        log = work / 'pc.log'
        extra = ['--pclog', str(log),
                 '--pclog-pcs', ','.join('%X' % pc for pc in sorted(pr.pcs)),
                 '--pclog-bytes', ','.join(pr.bytes),
                 '--pclog-limit', str(PCLOG_LIMIT)]
        if gametics:            # the run ends once the cut is logged
            extra += ['--stop-word', '%X:%d' % (P.symbols(d.play)[
                'G_GAMETIC'], gametics[1] + 1)]
        r = P.run(d, scene_script(scene, pr.hz), work / 'run', profile,
                  seconds, timeout=timeout, snap_ranges='main:1D00-1FFF',
                  extra=extra, a2vm=a2vm, idle=idle)
        if r.state.get('end') not in ('cycles', 'stop-word'):
            raise TimeError('the run ended with %s: %s' % (
                r.state.get('end'), r.state.get('halt') or r.out[-800:]))
        if gametics and r.state.get('end') != 'stop-word':
            raise TimeError('the run did not pass gametic %d in %g s of '
                            'model time (give --seconds)' % (gametics[1],
                                                              seconds))
        frames = frames_of(read_log(log, pr), pr)
        cut = ('gametics %d-%d' % gametics) if gametics else \
            ('%g-%g s' % window)
        out = OrderedDict([('scene', scene), ('profile', profile),
                           ('disk', str(disk) if disk else
                            'the play link\'s'), ('idle', idle),
                           ('run_seconds', round(
                               r.state.get('run_cycles', 0) / pr.hz, 2)),
                           ('idle_skipped_ms', round(
                               r.state.get('idle_cycles', 0) / pr.hz * 1000,
                               1)),
                           ('host_seconds',
                            round(r.state.get('host_seconds', 0), 1))])
        out.update(report(frames, pr, cut, window, gametics))
        return out
    finally:
        if not keep:
            shutil.rmtree(str(work), ignore_errors=True)


def text(r: Dict[str, Any]) -> str:
    lines = ['%s, %s, %s (idle %s): %d frames, gametics %d-%d, %.1f-%.1f s'
             % (r['scene'], r['profile'], r['cut'], r['idle'], r['frames'],
                r['gametic'][0], r['gametic'][1], r['seconds'][0],
                r['seconds'][1]),
             '  ms a frame: mean %.1f, median %.1f, max %.1f; %.2f FPS' % (
                 r['ms_mean'], r['ms_median'], r['ms_max'], r['fps']),
             '  tics: %.2f a frame, %.1f a second; gr_load %s a tic '
             '(%.1f a frame); VBL interrupts %.1f a frame' % (
                 r['tics_frame'], r['tics_second'], r['loads_tic'],
                 r['loads_frame'], r['irqs_frame']),
             '  steps, ms a frame:']
    for k, v in r['steps_ms'].items():
        lines.append('    %-24s %8.2f' % (k, v))
    lines.append('  (a2vm: %g s of model time in %.0f s; idle loops '
                 'skipped: %.1f ms)' % (r['run_seconds'], r['host_seconds'],
                                        r['idle_skipped_ms']))
    return '\n'.join(lines)


def pair(text_: str, kind) -> Tuple:
    a, _, b = text_.partition('-')
    return kind(a), kind(b)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--scene', required=True, choices=sorted(SCENES))
    parser.add_argument('--profile', default='f121',
                        choices=sorted(P.PROFILES))
    parser.add_argument('--disk', type=Path, default=P.OUT)
    parser.add_argument('--play', type=Path, default=P.PLAY)
    parser.add_argument('--gametics', help='G0-G1')
    parser.add_argument('--window', help='S0-S1, seconds')
    parser.add_argument('--seconds', type=float)
    parser.add_argument('--idle', default='exact',
                        choices=['exact', 'old', 'none'])
    parser.add_argument('--json', type=Path)
    parser.add_argument('--keep', type=Path)
    parser.add_argument('--a2vm', type=Path, default=P.A2VM,
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    gone = P.missing()
    if gone:
        print('playtime: build/ lacks: %s' % '; '.join(gone),
              file=sys.stderr)
        return 2
    try:
        r = measure(args.scene, args.profile, args.disk, args.play,
                    pair(args.gametics, int) if args.gametics else None,
                    pair(args.window, float) if args.window else None,
                    args.seconds, args.idle, args.keep, args.a2vm)
    except (TimeError, P.PlayError) as e:
        print('playtime: %s' % e, file=sys.stderr)
        return 1
    print(text(r))
    if args.json:
        args.json.write_text(json.dumps(r, indent=1) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
