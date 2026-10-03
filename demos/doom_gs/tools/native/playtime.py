#!/usr/bin/env python3
"""The play build's timing on a2vm (docs/SPEED.md 1-2): ms a frame, FPS,
tics, the kernel's steps and the tic phase's group loads, for one scene.

Usage:  python3 tools/native/playtime.py --scene still|walk|demo3|bench
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
  bench   the menu's BENCHMARK (ESC at 7 s, OPTIONS, BENCHMARK: the menu
          path of tests/test_play_bench.py), all of demo3 timed: the
          frames after its load (the last K_TIC with a code); the run
          goes on to --seconds (200 by default; a2vm f121 shows the page
          at about 174 s), the page staying up, and its figures are read
          from the run's last snapshot: the frames, the realtics, the
          FPS text, the rows (docs/PLAY.md 15) and the timing's sums.
          (Not with --stop-word on DL_BRT: G_TimeDemoEnd writes its bytes
          high first, so the run stopped with the low byte still 0.)

--window S0-S1 (seconds) or --gametics G0-G1 overrides a scene's cut. A
frame is the time between two K_END dispatches of the kernel (dl_kern.s
k_end, which starts the next K_TIC); with gametics, a frame counts when
the gametic at its end is in (G0, G1].

The data comes from a2vm's --pclog (tools/a2vm/README.md, "The PC log"),
bounded by --pclog-limit: a line at each kernel dispatch (k_end, k_tic1,
k_load, k_call and its jsr, k_menu), at k_load's call of am_runs (k_lrun:
Y the bank of the image a K_LOAD brings; the render front end's window
and the masked image are named K_WLOAD and K_MLOAD), at gcall.s's gr_load
(a group into its slot) and at the VBL handler, with the gametic and the
step's call target. Reported:

  frames, ms a frame (mean, median, max), FPS, tics a frame and a second;
  the kernel's steps in ms a frame: K_TIC (the tic image back, the brain,
  the tics, the next list), K_WLOAD, nr_frame, K_MLOAD, nm_masked,
  nm_bkload, nb_frame, K_LOAD P2DW, s2_frame and any other step;
  gr_load calls a tic (in K_TIC only: the tic image's), VBL interrupts a
  frame; the memory-API PRIVATE requests (docs/SPEED.md 9, 10), each timed
  from its caller to its return and its bytes from the build (a group's
  copy length, grun.group_entry; the kernel's lists; the planes' pages
  from G_MOHWM): gr_load's (am_one to gr_loaded: X the group; a W slot's
  or a frame slot's by grp_slot), fs_restore's (to the brain's dl_rsback:
  the frame slots loaded since K_TIC), planes_out's (to fs_restore), the
  kernel's K_TIC core and planes (k_tcore, k_tplan, k_tbrain) and each
  K_LOAD (the step): requests, descriptors, pages and ms a frame, by kind
  (the transport's own PCs are in the card's bank 1, where bank 2's
  texture rows run in the replay, so they are not logged);
  the replay's share of nb_frame (nat_replay's entry to its return
  in nb_frame), and the benchmark's five phases as its page counts them
  (docs/PLAY.md 15): TIC (K_TIC), 3D (K_WLOAD, nr_frame), MASK (K_MLOAD,
  nm_masked, nm_bkload or OVLW, nb_frame but its replays), DRAW (the
  replays), REST (the other steps), and the timing's own K_CALLs of
  bt_mark apart (MARKS).

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
    'bench': {'seconds': 200.0},
}
BENCH_ESC = 7.0                 # the bench scene's ESC (the title page)
# the benchmark page's phases (docs/PLAY.md 15) from the steps
PHASES = ['TIC', '3D', 'MASK', 'DRAW', 'REST', 'MARKS']
PHASE_OF = {'K_TIC': 'TIC', 'K_WLOAD': '3D', 'nr_frame': '3D',
            'K_MLOAD': 'MASK', 'nm_masked': 'MASK', 'nm_bkload': 'MASK',
            'OVLW': 'MASK', 'K_LOAD OVLW': 'MASK', 'nb_frame': 'MASK',
            'bt_mark': 'MARKS'}
# the steps in the order of a level's frame (dl_disp.s c_level)
STEP_ORDER = ['K_TIC', 'K_WLOAD', 'nr_frame', 'K_MLOAD', 'nm_masked',
              'nm_bkload', 'nb_frame', 'K_LOAD P2DW', 's2_frame']
# the step a dispatch label starts
DISPATCH = OrderedDict([('k_end', 'K_TIC'), ('k_tic1', 'K_TIC'),
                        ('k_load', 'K_LOAD'), ('k_call', 'K_CALL'),
                        ('k_menu', 'K_MENU'), ('dl_halt', 'K_HALT')])
# a K_LOAD's step name by its image (the brain's img_wload and img_mload:
# the render front end's window and the masked image, which had steps of
# their own before the copy engine)
LOAD_STEP = {'WCODE': 'K_WLOAD', 'MCODE': 'K_MLOAD'}
# the images a K_LOAD may bring (their banks' symbols), and the prefix of
# their entries' XS_ names
IMAGES = [('P2DW', 's2_'), ('OVLW', 'OVLW'), ('PALW', 'palw_'),
          ('AMAPW', 'am_'), ('FINW', 'fin_'), ('WIW', 'wi_'),
          ('MENUW', 'm_')]


# the requests' PCs (docs/SPEED.md 10): in the tic phase (the tic image's
# labels: their addresses hold other images' code in other steps, so they
# count in K_TIC only) and in the kernel (the card's $FF00 page)
TIC_REQUEST_PCS = ('am_one', 'gr_loaded', 'fs_restore', 'dl_rsback',
                   'planes_out')
KERNEL_REQUEST_PCS = ('k_tcore', 'k_tplan', 'k_tbrain', 'k_lrun')
REQUEST_KINDS = ['W slot', 'frame slot', 'restore', 'planes out',
                 'K_TIC core', 'K_TIC planes', 'K_LOAD']


class TimeError(Exception):
    pass


def scene_script(scene: str, hz: float) -> str:
    def at(s: float) -> str:
        return 'cycle %d' % int(s * hz)
    if scene == 'demo3':
        return ''
    if scene == 'bench':
        t = BENCH_ESC
        keys = [(t, '27'), (t + 0.5, '0x0A'), (t + 1.0, '13')]
        keys += [(t + 1.5 + 0.5 * k, '0x0A') for k in range(3)]
        keys.append((t + 3.5, '13'))
        return ''.join('%s key %s\n' % (at(s), k) for s, k in keys)
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
    # the requests' bytes (docs/SPEED.md 10): each group's copy (its
    # length as gr_load copies it) and slot, each image's runs by its bank
    gbytes: Dict[int, int] = {}
    gslot: Dict[int, int] = {}
    ibytes: Dict[int, Tuple[int, int]] = {}  # bank: (descriptors, bytes)
    # a glue group's PCs (planes_out in DLG_D, dl_rsback in DLG_B) count
    # only while its slot holds it: name -> (slot, group)
    holder: Dict[str, Tuple[int, int]] = {}


def replay_pcs() -> Tuple[int, int]:
    """nat_replay's entry and the address nb_frame's jsr nat_replay
    returns to: nb_frame runs in main (BKFAR, which nm_bkload copies from
    the masked image MCODE), so the call is found in milestone 8's rcard
    link's masked image."""
    from native import render_check as RC
    rc = RC.load_build(RC.OBJ, 'rcard')
    lab, (w_lo, _) = rc.labels, rc.segments['MASKW']
    image = (rc.obj / 'rcard.wm').read_bytes()
    lo = lab['__BKFAR_LOAD__'] - w_lo
    hi = lo + rc.segments['BKFAR'][1] + 1 - rc.segments['BKFAR'][0]
    call = bytes([0x20, lab['nat_replay'] & 0xFF, lab['nat_replay'] >> 8])
    at = image.find(call, lo, hi)
    if at < 0 or image.find(call, at + 1, hi) >= 0:
        raise TimeError('not one jsr nat_replay in BKFAR')
    return lab['nat_replay'], lab['__BKFAR_RUN__'] + at - lo + 3


def group_copies(play: Path, sym: Dict[str, int]
                 ) -> Tuple[Dict[int, int], Dict[int, int]]:
    """Each group's bytes as gr_load copies them (grun.group_entry: its
    whole pages and its tail) and its slot (the placement's GRPn_SLOT, the
    glue's own)."""
    from native import grun, playlayout as PL
    b = PK.tic_build(play)
    groups = PK.gplace_groups(play / 'tic' / 'gen' / 'gplace.inc')
    glue = {groups + off: slot for _, off, slot in PL.DL_GROUPS}
    size, slot = {}, {}
    for n in range(1, groups + len(PL.DL_GROUPS) + 1):
        path = b.obj / ('tic.g%d' % n)
        if not path.exists() or not path.stat().st_size:
            continue
        e = dict(grun.group_entry(0, 0, path.stat().st_size))
        size[n] = e['grp_pages'] * 256 + e['grp_tail']
        slot[n] = glue.get(n, sym.get('GRP%d_SLOT' % n, 1))
    return size, slot


def image_copies(play: Path, sym: Dict[str, int]
                 ) -> Dict[int, Tuple[int, int]]:
    """A K_LOAD's descriptors and bytes by its bank (playimg.inc's
    lists, the brain's)."""
    import re
    out = {}
    text = (play / 'gen' / 'playimg.inc').read_text()
    for m in re.finditer(r'^img_\w+: \.byte (.*)$', text, re.M):
        v = [int(x[1:], 16) if x.startswith('$') else int(x)
             for x in (y.strip() for y in m.group(1).split(','))]
        runs = [(v[i], v[i + 1]) for i in range(1, len(v) - 1, 2)]
        out[v[0]] = (len(runs), 256 * sum(n for _, n in runs))
    return out


def probe(disk: P.Disk, profile: str) -> Probe:
    """The PCs to log and how to read the lines, from the play link."""
    lab = P.labels(disk)
    sym = P.symbols(disk.play)
    pcs = {}
    for name in DISPATCH:
        pcs[lab[name]] = name
    pcs[lab['k_jsr']] = 'k_jsr'
    pcs[sym['XS_pl_vbl']] = 'pl_vbl'
    tic = PK.tic_build(disk.play).labels
    pcs[tic['gr_load']] = 'gr_load'
    n = len(DISPATCH) + 3
    for name in TIC_REQUEST_PCS:
        pcs[tic[name]] = name
    for name in KERNEL_REQUEST_PCS:
        pcs[lab[name]] = name
    n += len(TIC_REQUEST_PCS) + len(KERNEL_REQUEST_PCS)
    entry, back = replay_pcs()
    pcs[entry] = 'nat_replay'
    pcs[back] = 'nb_rret'
    n += 2
    if len(pcs) != n:
        raise TimeError('two logged labels share a PC')
    # the jsr's operand (in the main card, the kernel's), the gametic; the
    # kernel's lists' counts (k_core's, k_planes' first: KLISTS, dl_kern.s)
    # and G_MOHWM (planes_out's pages)
    gametic = sym['G_GAMETIC']
    log_bytes = ['lc.%X' % (lab['k_jsr'] + 1), 'lc.%X' % (lab['k_jsr'] + 2)]
    log_bytes += ['%X' % (gametic + i) for i in range(4)]
    log_bytes += ['lc.%X' % (lab['k_core'] + 1),
                  'lc.%X' % (lab['k_planes'] + 1),
                  '%X' % sym['G_MOHWM'], '%X' % (sym['G_MOHWM'] + 1),
                  '%X' % (sym['SLOT_GRP'] + 1), '%X' % (sym['SLOT_GRP'] + 2)]
    names = defaultdict(list)
    for k, v in sym.items():
        if k.startswith('XS_'):
            names[v].append(k[3:])
    names[sym['OVLW_LO']].append('OVLW')
    if 'bt_mark' in lab:         # the benchmark's timing (docs/PLAY.md 15)
        names[lab['bt_mark']].append('bt_mark')
    banks = {sym['%s_BANK' % n]: n for n, _ in IMAGES + [('WCODE', ''),
                                                          ('MCODE', '')]
             if '%s_BANK' % n in sym}
    hz = costs.parameters(P.PROFILES[profile])['fabric_mhz'] * 1e6
    gbytes, gslot = group_copies(disk.play, sym)
    from native import playlayout as PL
    groups = PK.gplace_groups(disk.play / 'tic' / 'gen' / 'gplace.inc')
    glue = {name: (slot, groups + off) for name, off, slot in PL.DL_GROUPS}
    holder = {'planes_out': glue['DLG_D'], 'dl_rsback': glue['DLG_B']}
    return Probe(pcs, log_bytes, dict(names), banks, hz, gbytes, gslot,
                 image_copies(disk.play, sym), holder)


class Line(NamedTuple):
    t: int
    name: str
    a: int
    x: int
    y: int
    target: int                  # the k_jsr operand
    gametic: int
    more: Tuple[int, ...] = ()   # the other logged bytes (probe's order)


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
                            b[2] | b[3] << 8 | b[4] << 16 | b[5] << 24,
                            tuple(b[6:])))
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
    replay: int = 0              # nb_frame's clocks in nat_replay
    # the memory-API requests by kind (REQUEST_KINDS): [requests,
    # descriptors, bytes, clocks]
    amem: Dict[str, List[int]] = {}


FS_FIRST = 3                     # glayout.FRAME_FIRST: the frame slots
PLANES = 4                       # planes_out's and k_planes' runs


def frames_of(lines: List[Line], pr: Probe) -> List[Frame]:
    """The frames between consecutive K_END dispatches, with their
    steps."""
    out = []
    cur = None                   # the frame being read
    step = None                  # [name, start]
    image = None
    req = None                   # the open request: [kind, start, n, bytes]

    def close(t):
        nonlocal req
        if req is not None and cur is not None:
            a = cur['amem'].setdefault(req[0], [0, 0, 0, 0])
            a[0] += 1
            a[1] += req[2]
            a[2] += req[3]
            a[3] += t - req[1]
        req = None

    def open_(kind, t, n, nbytes):
        nonlocal req
        close(t)
        req = [kind, t, n, nbytes]

    for ln in lines:
        if ln.name in DISPATCH:
            close(ln.t)
            if cur is not None and step is not None:
                cur['steps'].append((step[0], ln.t - step[1]))
            kind = DISPATCH[ln.name]
            if ln.name == 'k_end':
                if cur is not None:
                    out.append(Frame(cur['start'], ln.t, ln.gametic,
                                     ln.gametic - cur['gametic'],
                                     cur['steps'], cur['loads'],
                                     cur['irqs'], cur['replay'],
                                     cur['amem']))
                cur = {'start': ln.t, 'gametic': ln.gametic, 'steps': [],
                       'loads': 0, 'irqs': 0, 'replay': 0, 'rstart': None,
                       'amem': {}, 'fsl': []}
            if kind == 'K_TIC' and cur is not None:
                cur['fsl'] = []
            step = [kind, ln.t]
            if kind == 'K_TIC':
                image = 'TIC'
            elif kind == 'K_LOAD':
                image = None
        elif ln.name == 'k_jsr' and step is not None and \
                step[0] == 'K_CALL':
            step[0] = call_name(pr, ln.target, image)
        elif ln.name == 'k_lrun' and step is not None and \
                step[0] == 'K_LOAD' and image is None:
            image = pr.banks.get(ln.y, 'bank $%02X' % ln.y)
            step[0] = LOAD_STEP.get(image, 'K_LOAD %s' % image)
            n, nbytes = pr.ibytes.get(ln.y, (0, 0))
            open_('K_LOAD', ln.t, n, nbytes)
        elif ln.name == 'gr_load' and cur is not None and \
                step is not None and step[0] == 'K_TIC':
            cur['loads'] += 1
        elif ln.name == 'pl_vbl' and cur is not None:
            cur['irqs'] += 1
        elif ln.name in TIC_REQUEST_PCS + KERNEL_REQUEST_PCS and (
                cur is None or step is None or step[0] != 'K_TIC'):
            pass                # (another image's code at the core's PC)
        elif ln.name in pr.holder and \
                ln.more[3 + pr.holder[ln.name][0]] != pr.holder[ln.name][1]:
            pass                # (another group's code in the slot)
        elif ln.name == 'am_one':
            slot = pr.gslot.get(ln.x, 1)
            if slot >= FS_FIRST:
                cur['fsl'].append(ln.x)
            open_('frame slot' if slot >= FS_FIRST else 'W slot', ln.t, 1,
                  pr.gbytes.get(ln.x, 0))
        elif ln.name == 'planes_out':
            mohwm = ln.more[2] | ln.more[3] << 8
            pages = min(max((mohwm + 255) >> 8, 1), 3)
            open_('planes out', ln.t, PLANES, PLANES * 256 * pages)
        elif ln.name == 'fs_restore':
            close(ln.t)
            if cur['fsl']:
                open_('restore', ln.t, len(cur['fsl']),
                      sum(pr.gbytes.get(g, 0) for g in cur['fsl']))
                cur['fsl'] = []
        elif ln.name == 'k_tcore':
            open_('K_TIC core', ln.t, 1, 256 * ln.more[0])
        elif ln.name == 'k_tplan':
            open_('K_TIC planes', ln.t, PLANES, PLANES * 256 * ln.more[1])
        elif ln.name in ('gr_loaded', 'dl_rsback', 'k_tbrain'):
            close(ln.t)
        elif ln.name == 'nat_replay' and cur is not None:
            cur['rstart'] = ln.t
        elif ln.name == 'nb_rret' and cur is not None and \
                cur['rstart'] is not None:
            cur['replay'] += ln.t - cur['rstart']
            cur['rstart'] = None
    return out


def phases_of(f: Frame) -> Dict[str, int]:
    """A frame's clocks by the benchmark page's phases (PHASES)."""
    out = dict.fromkeys(PHASES, 0)
    for name, clocks in f.steps:
        out[PHASE_OF.get(name, 'REST')] += clocks
    out['MASK'] -= f.replay
    out['DRAW'] += f.replay
    return out


def private_of(sel: List[Frame], pr: Probe) -> Dict[str, Any]:
    """The memory-API requests a frame, by kind and in all: requests,
    descriptors, pages (bytes / 256), ms; and us a request."""
    out = OrderedDict()
    total = [0, 0, 0, 0]
    for kind in REQUEST_KINDS:
        s = [sum(f.amem.get(kind, [0, 0, 0, 0])[i] for f in sel)
             for i in range(4)]
        if not s[0]:
            continue
        total = [a + b for a, b in zip(total, s)]
        out[kind] = OrderedDict([
            ('requests_frame', round(s[0] / len(sel), 2)),
            ('descriptors_frame', round(s[1] / len(sel), 2)),
            ('pages_frame', round(s[2] / 256 / len(sel), 2)),
            ('ms_frame', round(s[3] / pr.hz * 1000 / len(sel), 3)),
            ('us_request', round(s[3] / pr.hz * 1e6 / s[0], 1))])
    out['all'] = OrderedDict([
        ('requests_frame', round(total[0] / len(sel), 2)),
        ('descriptors_frame', round(total[1] / len(sel), 2)),
        ('pages_frame', round(total[2] / 256 / len(sel), 2)),
        ('ms_frame', round(total[3] / pr.hz * 1000 / len(sel), 3))])
    return out


def report(frames: List[Frame], pr: Probe, cut: str,
           window: Optional[Tuple[float, float]],
           gametics: Optional[Tuple[int, int]],
           after: Optional[int] = None) -> Dict[str, Any]:
    if after is not None:
        sel = [f for f in frames if f.start >= after]
    elif gametics:
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
    phases = defaultdict(float)
    for f in sel:
        for name, clocks in phases_of(f).items():
            phases[name] += clocks / pr.hz * 1000
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
        ('replay_ms', round(sum(f.replay for f in sel) / pr.hz * 1000 /
                            len(sel), 2)),
        ('private', private_of(sel, pr)),
        ('phases_ms', OrderedDict((s, round(phases[s] / len(sel), 2))
                                  for s in PHASES)),
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
            timeout: float = 3600.0, amem: bool = True) -> Dict[str, Any]:
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
        sym = P.symbols(d.play)
        bench = scene == 'bench'
        if bench:               # the page up at the run's end
            gametics = window = None
        elif gametics:          # the run ends once the cut is logged
            extra += ['--stop-word', '%X:%d' % (sym['G_GAMETIC'],
                                                gametics[1] + 1)]
        r = P.run(d, scene_script(scene, pr.hz), work / 'run', profile,
                  seconds, timeout=timeout,
                  snap_ranges='main:1D00-1FFF,main:BF00-BFFF',
                  extra=extra, a2vm=a2vm, idle=idle, amem=amem)
        if r.state.get('end') not in ('cycles', 'stop-word'):
            raise TimeError('the run ended with %s: %s' % (
                r.state.get('end'), r.state.get('halt') or r.out[-800:]))
        if gametics and r.state.get('end') != 'stop-word':
            raise TimeError('the run did not reach its end in %g s of '
                            'model time (give --seconds)' % seconds)
        lines = read_log(log, pr)
        frames = frames_of(lines, pr)
        after = None
        if bench:
            tics = [ln.t for ln in lines if ln.name == 'k_tic1']
            if not tics:
                raise TimeError('no K_TIC with a code: no benchmark')
            after = tics[-1]
            cut = 'the benchmark, after its load'
        else:
            cut = ('gametics %d-%d' % gametics) if gametics else \
                ('%g-%g s' % window)
        out = OrderedDict([('scene', scene), ('profile', profile),
                           ('disk', str(disk) if disk else
                            'the play link\'s'), ('idle', idle),
                           ('amem', amem),
                           ('run_seconds', round(
                               r.state.get('run_cycles', 0) / pr.hz, 2)),
                           ('idle_skipped_ms', round(
                               r.state.get('idle_cycles', 0) / pr.hz * 1000,
                               1)),
                           ('host_seconds',
                            round(r.state.get('host_seconds', 0), 1))])
        out.update(report(frames, pr, cut, window, gametics, after))
        if bench:
            out['bench'] = bench_page(r, sym)
            if not out['bench']['realtics']:
                raise TimeError('no result page in %g s of model time '
                                '(give --seconds)' % seconds)
        return out
    finally:
        if not keep:
            shutil.rmtree(str(work), ignore_errors=True)


def bench_page(r: P.Run, sym: Dict[str, int]) -> Dict[str, Any]:
    """The benchmark's result from the run's last snapshot (the page up:
    MENUW in W): the frames, the realtics, the page's FPS text and rows
    (M_BFPS, M_BROWS), the timing's sums in bus cycles (BT_S) and its
    overflows."""
    import struct
    m = r.images['final'][(0, 0)]

    def text(at, n):
        return bytes(m[at:at + n]).split(b'\0')[0].decode('ascii', 'replace')
    out = OrderedDict([
        ('frames', struct.unpack_from('<H', m, sym['DL_BVIEW'])[0]),
        ('realtics', struct.unpack_from('<I', m, sym['DL_BRT'])[0]),
        ('fps', text(sym['M_BFPS'], 8))])
    if 'M_BROWS' in sym:         # (a build before the timing: none)
        out['rows'] = [text(sym['M_BROWS'] + 32 * i, 32) for i in range(3)]
    if 'BT_S' in sym:
        sums = [struct.unpack_from('<I', m, sym['BT_S'] + 4 * i)[0]
                for i in range(5)]
        out['cycles'] = OrderedDict(zip(PHASES[:5], sums))
        out['overflows'] = m[sym['BT_OVF']]
    return out


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
    pv = r.get('private')
    if pv and pv['all']['requests_frame']:
        a = pv['all']
        at = len(lines) - 1
        lines.insert(at, '  the memory-API PRIVATE requests: %.2f a frame '
                     '(%.2f descriptors), %.1f pages, %.2f ms; by kind:' % (
                         a['requests_frame'], a['descriptors_frame'],
                         a['pages_frame'], a['ms_frame']))
        for kind, v in pv.items():
            if kind == 'all':
                continue
            at += 1
            lines.insert(at, '    %-14s %6.2f requests %6.2f descriptors '
                         '%6.1f pages %7.3f ms (%.1f us a request)' % (
                             kind, v['requests_frame'],
                             v['descriptors_frame'], v['pages_frame'],
                             v['ms_frame'], v['us_request']))
    for k, v in r['steps_ms'].items():
        lines.append('    %-24s %8.2f' % (k, v))
    lines.append('  the benchmark page\'s phases, ms a frame (nb_frame\'s '
                 'replays %.2f):' % r['replay_ms'])
    lines.append('    ' + '  '.join('%s %.2f' % kv
                                    for kv in r['phases_ms'].items()))
    if 'bench' in r:
        b = r['bench']
        lines.append('  the benchmark\'s page: %d frames, %d realtics, '
                     'FPS %s' % (b['frames'], b['realtics'], b['fps']))
        for row in b.get('rows', []):
            lines.append('    %s' % row)
    if 'bench' in r and 'cycles' in r['bench']:
        lines.append('  the machine\'s own timing (overflows %d), ms a '
                     'frame (at 1,015,625 Hz):' % b['overflows'])
        lines.append('    ' + '  '.join(
            '%s %.2f' % (k, v / max(b['frames'], 1) / 1015.625)
            for k, v in b['cycles'].items()))
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
    parser.add_argument('--no-amem', action='store_true',
                        help='no memory API: the CPU copies (docs/PLAY.md '
                        '19)')
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
                    args.seconds, args.idle, args.keep, args.a2vm,
                    amem=not args.no_amem)
    except (TimeError, P.PlayError) as e:
        print('playtime: %s' % e, file=sys.stderr)
        return 1
    print(text(r))
    if args.json:
        args.json.write_text(json.dumps(r, indent=1) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
