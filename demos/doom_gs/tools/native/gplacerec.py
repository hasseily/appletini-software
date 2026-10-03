#!/usr/bin/env python3
"""The tic phase's call traffic, recorded for the placement's model
(docs/speed-parts/place.md): a scene of the play build (DOOM.hdv) or of
the lockstep build on a2vm, its write log read through a pipe by gtrace
(tools/gplace/gtrace.c), which writes the calls and returns between the
tic code's units, the loads that happened, and a line a phase (the clock
at its start and end, the tics, the loads and pages). Nothing in a2vm
changes: the write log of the stack page, SLOT_GRP, FC_T, FC_GRP and
G_GAMETIC is enough (gtrace.c's header). The same run measures the frame
(a phase starts at each K_TIC: ms a frame from one start to the next) and
the paging.

Usage:  python3 tools/native/gplacerec.py SCENE [SCENE ...] [--out DIR]
                [--play DIR] [--profile f121|fastpath] [--jobs N]
                [--bwait-idle] [--no-build] [--keep-traces]
        python3 tools/native/gplacerec.py --report [--out DIR]

SCENE (SCENES): still, walk, fight (E1M1 after NEW GAME, a model-time
window), demo3, demo3b, demo3w (the title loop's demo3 on E1M7, gametic
windows: 1052-1400, 1400-1796, and docs/SPEED.md's 1052-1796), lock3a,
lock3b (the lockstep build's demo3, gametic windows). Each writes
DIR/SCENE.ev (the events, gsim's input), SCENE.json (its units, the
build's placement, the measured figures). DIR is build/native/game/gplace
by default. The play scenes run without the kernel's idle at dl_bwait
(card-equivalent: docs/SPEED.md 1) unless --bwait-idle.

Every run is bounded: a2vm by model cycles and wall time, gtrace's output
by bounded.run's file size; the write log never touches the disk (a FIFO
in a temporary directory, deleted after the run).
"""

import argparse
import concurrent.futures as CF
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import glayout as GL  # noqa: E402
from ref816 import bounded  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
OUT = GL.GAME / 'gplace'
TOOLS = ROOT / 'tools' / 'gplace'
GTRACE = BUILD / 'gplace' / 'gtrace'
GSIM = BUILD / 'gplace' / 'gsim'
TIC_UNIT = 'g_game65.s:G_Ticker'
OUTSIDE, CORE = '@outside', '@core'
EV_MAX = 1 << 30                # gtrace's events file, at most
LINES_MAX = 4_000_000_000       # the write log's lines (a pipe), at most
GLUE_SEGS = {'DLGB': 'DLG_B', 'DLGC': 'DLG_C', 'DLGD': 'DLG_D',
             'DLGH': 'DLG_H', 'S2CODE': 'DLG_H', 'S2RODATA': 'DLG_H',
             'DLGS': 'DLG_S', 'S2TCODE': 'DLG_S', 'S2TRODATA': 'DLG_S'}
UP, DOWN, LEFT, RIGHT = '0x0B', '0x0A', '0x08', '0x15'


def _at(s: float, hz: float) -> str:
    return 'cycle %d' % int(s * hz)


# name: (kind, script events [(seconds, event)], window, run length)
# window: ('clock', from_s, to_s) or ('gametic', from, to)
SCENES: Dict[str, Dict[str, Any]] = {
    # E1M1's start, standing still (docs/SPEED.md 2's scene)
    'still': {'kind': 'play', 'events': [(8.0, 'key 13'), (9.0, 'key 13')],
              'window': ('clock', 15.0, 25.0), 'seconds': 26.5},
    # E1M1, walking and turning (the arrows held in turn)
    'walk': {'kind': 'play', 'events': [(8.0, 'key 13'), (9.0, 'key 13')] + [
        (12.0, 'hold ' + UP), (14.0, 'release'), (14.1, 'hold ' + LEFT),
        (14.9, 'release'), (15.0, 'hold ' + UP), (17.0, 'release'),
        (17.1, 'hold ' + RIGHT), (18.4, 'release'), (18.5, 'hold ' + UP),
        (20.5, 'release'), (20.6, 'hold ' + LEFT), (21.4, 'release'),
        (21.5, 'hold ' + UP), (23.0, 'release')],
             'window': ('clock', 12.0, 23.0), 'seconds': 24.5},
    # E1M1, the pistol fired from the start, walking north (held out)
    'fight': {'kind': 'play', 'events': [(8.0, 'key 13'), (9.0, 'key 13'),
                                         (11.5, 'buttons 1 0'),
                                         (12.0, 'hold ' + UP),
                                         (15.0, 'release'),
                                         (34.0, 'buttons 0 0')],
              'window': ('clock', 16.0, 34.0), 'seconds': 35.5},
    # the title loop's demo3 (E1M7, the benchmark's demo): SPEED.md's
    # gametics 1052-1796 in two halves, the first for the training
    'demo3': {'kind': 'play', 'events': [],
              'window': ('gametic', 1052, 1400), 'seconds': 170.0},
    'demo3b': {'kind': 'play', 'events': [],
               'window': ('gametic', 1400, 1796), 'seconds': 230.0},
    # SPEED.md's whole window (the measure of a build: demo3 and demo3b)
    'demo3w': {'kind': 'play', 'events': [],
               'window': ('gametic', 1052, 1796), 'seconds': 230.0},
    # the lockstep build's demo3 (the tic profiler's windows)
    'lock3a': {'kind': 'lock', 'run': 'demo3',
               'window': ('gametic', 2440, 2640)},
    'lock3b': {'kind': 'lock', 'run': 'demo3',
               'window': ('gametic', 2900, 2990)},
}
TRAIN = ('still', 'walk', 'demo3', 'lock3a')
HOLD = ('fight', 'demo3b', 'lock3b')


class RecError(Exception):
    pass


def make_tools() -> None:
    """build/gplace/gtrace and gsim (tools/gplace/Makefile), no warning."""
    r = bounded.run(['make', '-s', '-C', str(TOOLS)], timeout=300,
                    max_bytes=64 << 20, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, universal_newlines=True)
    if r.returncode or 'arning' in r.stdout:
        raise RecError('make -C tools/gplace:\n' + r.stdout[-3000:])


# ---------------------------------------------------------------------------
# The map of a tic build: its bytes, its units, its addresses
# ---------------------------------------------------------------------------

def inc_symbols(dirs: Sequence[Path]) -> Dict[str, int]:
    import re
    out: Dict[str, int] = {}
    for d in dirs:
        for p in sorted(Path(d).glob('*.inc')):
            for line in p.read_text().splitlines():
                m = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'
                             r'(\$[0-9A-Fa-f]+|[0-9]+)\s*(;.*)?$', line)
                if m:
                    v = m.group(2)
                    out[m.group(1)] = int(v[1:], 16) if v[0] == '$' \
                        else int(v)
    return out


def fixed_labels(src: Path = ROOT / 'src' / 'native') -> List[str]:
    """The labels where a part's source puts code in the core whatever
    the placement (the first label after a .segment "GCORE" or "LOADW":
    flow's g_resume, damage's weaponinfo): the end of the routine before
    them, in the link's ranges."""
    import re
    out = []
    for f in sorted(src.glob('game/*/*.s')):
        armed = False
        for line in f.read_text(errors='replace').splitlines():
            if re.match(r'^\s*\.segment\s+"(GCORE|LOADW)"', line):
                armed = True
                continue
            m = re.match(r'^([A-Za-z_]\w*):', line)
            if armed and m:
                out.append(m.group(1))
                armed = False
    return out


def unit_ranges(b, glue: Optional[Dict[str, int]] = None,
                cuts: Optional[Sequence[str]] = None
                ) -> List[Tuple[str, int, int, int]]:
    """(unit, group, lo, hi) of a tic build's code: each table routine
    from its label to the next table label of its module's part of a
    segment (grun.routine_sizes's rule; a group's bytes before its first
    label are that routine's) or to a fixed label (fixed_labels: the
    core's code from there), the core's other code CORE, the glue's
    groups (play) one unit each."""
    from native import grun as G
    if cuts is None:
        cuts = fixed_labels()
    cut_at = {b.labels[n] for n in cuts if n in b.labels}
    names = GL.native_names()
    keys = [k for p in GL.PARTS for k in p['routines'] + p['helpers']
            if not GL.inlined(k)]
    by_name = {names[k]: k for k in keys}
    group = G.entry_groups(b)
    lab = b.labels
    out = []
    for module, seg, lo, hi in G.contributions(b):
        if glue and seg in GLUE_SEGS:
            out.append(('@glue:' + GLUE_SEGS[seg], glue[GLUE_SEGS[seg]],
                        lo, hi))
            continue
        if not (seg in G.CODE_SEGMENTS or seg.startswith('GGRP')):
            continue
        g = 0 if seg in G.CODE_SEGMENTS else int(seg[4:])
        at = sorted({(a, n) for n, a in lab.items()
                     if n in by_name and group.get(n, 0) == g and
                     lo <= a < hi})
        if not at:
            if g:
                out.append(('@group:%d' % g, g, lo, hi))
            continue
        if g and at[0][0] > lo:
            at[0] = (lo, at[0][1])
        stops = sorted({a for a, _ in at} | {c for c in cut_at
                                              if lo <= c < hi} | {hi})
        for a, n in at:
            end = next(x for x in stops if x > a) if a < hi else hi
            if end > a:
                out.append((by_name[n], g, a, end))
    return out


def group_files(b) -> Dict[int, Tuple[Path, int, int]]:
    """group -> (file, slot address, bytes) of a tic build's groups (its
    GGRPn segments and the glue's: every G memory area with a file)."""
    out: Dict[int, Tuple[Path, int, int]] = {}
    for p in sorted(b.obj.glob('%s.g*' % b.name)):
        try:
            n = int(p.suffix[2:])
        except ValueError:
            continue
        data = p.read_bytes()
        if not data:
            continue
        lo = None
        seg = b.segments.get('GGRP%d' % n)
        if seg is not None:
            lo = seg[0]
            size = min(len(data), seg[1] + 1 - seg[0])
        else:
            size = len(data)
        out[n] = (p, lo if lo is not None else -1, size)
    return out


def glue_groups(b, groups: int) -> Dict[str, int]:
    from native import playlayout as PL
    return {name: groups + off for name, off, _ in PL.DL_GROUPS}


def build_map(b, kind: str, window: Tuple[str, float, float], hz: float,
              boot=None, play: Optional[Path] = None
              ) -> Tuple[str, List[str], Dict[str, Any]]:
    """gtrace's map of a tic build: kind 'play' (the play link's tic image
    with the kernel's boot labels) or 'lock' (the lockstep build with its
    driver). Returns (map text, the units by number, facts)."""
    from native import grun as G
    lab = b.labels
    gen = [b.obj / 'gen']
    if play is not None:
        gen.append(play / 'gen')
    sym = inc_symbols(gen)
    groups = G.groups_of(b)
    ngroups = max([n for n, *_ in groups] or [0])
    glue = None
    slots = {}
    if kind == 'play':
        from native import playlink as PK, playlayout as PL
        gn = PK.gplace_groups(b.obj / 'gen' / 'gplace.inc')
        glue = glue_groups(b, gn)
        slots.update({gn + off: s for _, off, s in PL.DL_GROUPS})
    ranges = unit_ranges(b, glue)
    units = [OUTSIDE, CORE]
    uid = {OUTSIDE: 0, CORE: 1}
    for u, *_ in ranges:
        if u not in uid:
            uid[u] = len(units)
            units.append(u)
    lines = ['# gtrace map (tools/native/gplacerec.py)',
             'slots %X %X %X' % (GL.WR['SLOT1'][0], GL.WR['SLOT2'][0],
                                 GL.WR['SLOT2'][1])]
    # the frame slots (docs/SPEED.md 9): each group's slot (gplace.inc's
    # GRPn_SLOT), a frame slot's addresses its group's memory area's (the
    # link's map)
    gslot = {int(k[3:-5]): v for k, v in sym.items()
             if k.startswith('GRP') and k.endswith('_SLOT')}
    cfgs = [q for q in (b.obj / 'play.cfg', b.obj / 'game.cfg')
            if q.exists()]
    areas = {}
    if cfgs:
        import re
        areas = {int(m.group(1)): (int(m.group(2), 16),
                                   int(m.group(3), 16))
                 for m in re.finditer(r'^\s*G(\d+):\s+start = \$([0-9A-F]+)'
                                      r', size = \$([0-9A-F]+),',
                                      cfgs[0].read_text(), re.M)}
    for n, sl in sorted(gslot.items()):
        if sl >= GL.FRAME_FIRST and n in areas:
            lo, size = areas[n]
            lines.append('fslot %d %X %X' % (sl, lo, lo + size))
            slots[n] = sl
    w = b.obj / ('%s.w' % b.name)
    core = b.obj / ('%s.core' % b.name)
    lines.append('grp 0 6000 %X %s 0' % (w.stat().st_size, w))
    lines.append('grp 0 6600 %X %s 0' % (core.stat().st_size, core))
    pages: Dict[int, int] = {}
    for n, (p, lo, size) in sorted(group_files(b).items()):
        if lo < 0:
            seg = [v for k, v in b.segments.items() if k in GLUE_SEGS and
                   glue and glue[GLUE_SEGS[k]] == n]
            lo = min(s[0] for s in seg) if seg else GL.WR['SLOT1'][0]
        lines.append('grp %d %X %X %s 0' % (n, lo, size, p))
        pages[n] = (size + 0xFF) >> 8
        lines.append('pages %d %d' % (n, pages[n]))
        if n not in slots:
            slots[n] = gslot.get(n, 1 if lo < GL.WR['SLOT2'][0] else 2)
    if kind == 'lock' and 'DRIVER' in b.segments:
        lce = b.obj / ('%s.lce' % b.name)
        lines.append('grp 0 E000 %X %s 0' % (lce.stat().st_size, lce))
    lines.append('unit 1 0 6000 %X' % GL.WR['SCRATCH'][0])
    for u, g, lo, hi in ranges:
        lines.append('unit %d %d %X %X' % (uid[u], g, lo, hi))
    # the runtime's code: gcall.s's part of the segment that holds fc_call
    # (its dispatch tables in GCORE are data, and the core's code between
    # the two is the game's)
    gcall = [(lo, hi) for m, s, lo, hi in G.contributions(b)
             if m == 'gcall' and s in G.CODE_SEGMENTS and
             lo <= lab['fc_call'] < hi]
    if not gcall:
        raise RecError('no gcall code in the build')
    rt_lo, rt_hi = gcall[0]
    clash = [u for u, g, lo, hi in ranges
             if g == 0 and lo < rt_hi and hi > rt_lo]
    if clash:
        # (a write there is not a call: no routine's code may be in it)
        raise RecError('the runtime range $%04X-$%04X holds %s' % (
            rt_lo, rt_hi, clash[:3]))
    for name, v in (('slotgrp', sym['SLOT_GRP']), ('fct', sym['FC_T']),
                    ('fcgrp', sym['FC_GRP']),
                    ('gametic', sym['G_GAMETIC']),
                    ('fc_call', lab['fc_call']), ('dc_call', lab['dc_call']),
                    ('dc_end', lab['act_num']), ('fc_go', lab['fc_go']),
                    ('fc_ret', lab['fc_ret']), ('rt_lo', rt_lo),
                    ('rt_hi', rt_hi)):
        lines.append('addr %s %X' % (name, v))
    if kind == 'play':
        kl = boot.labels
        lines.append('on %X %X' % (kl['k_tic'], kl['dl_run']))
        lo, hi = boot.segments['DLKERN']
        lines.append('offpc %X %X' % (kl['dl_run'], hi + 1))
        for seg in ('DLKMAIN', 'DLKMAIN2'):
            if seg in boot.segments:
                lo, hi = boot.segments[seg]
                lines.append('offpc %X %X' % (lo, hi + 1))
    else:
        lo, hi = b.segments['DRIVER']
        lines.append('on %X %X' % (lo, hi + 1))
        # (the driver's calls that put another image in W: the frame's
        # renderer, the level's load; a tic with no frame keeps the slots)
        for name in ('call_frame', 'load'):
            lines.append('offt %X' % lab[name])
    if TIC_UNIT in uid:
        lines.append('tic %d' % uid[TIC_UNIT])
    if window[0] == 'gametic':
        lines.append('window %d %d' % (window[1], window[2]))
    else:
        lines.append('clocks %d %d' % (int(window[1] * hz),
                                       int(window[2] * hz)))
    facts = {'pages': {str(k): v for k, v in pages.items()},
             # (gcall.s's restore: the lazy one keeps SLOT_NEED, part
             # paging's of wave 1)
             'restore': 'lazy' if 'SLOT_NEED' in sym else 'eager',
             'slots': {str(k): v for k, v in slots.items()},
             'glue': glue or {}, 'groups': ngroups,
             'placement': placement_of_build(b, ranges),
             # (the stack by the CPU's address; the rest in main: a
             # render image's aux writes at the same addresses are not the
             # tic image's)
             'write_log': 'cpu:0100-01FF,main:%04X-%04X,main:%04X-%04X,'
                          'main:%04X,main:%04X-%04X' % (
                              sym['SLOT_GRP'], sym['SLOT_GRP'] +
                              sym.get('FS_FIRST', 3) + sym.get('FS_MAX', 0) -
                              1,
                              sym['FC_T'], sym['FC_T'] + 1, sym['FC_GRP'],
                              sym['G_GAMETIC'], sym['G_GAMETIC'] + 3)}
    return '\n'.join(lines) + '\n', units, facts


def placement_of_build(b, ranges) -> Dict[str, int]:
    """Each table routine's group in the build (0 the core)."""
    return {u: g for u, g, *_ in ranges if not u.startswith('@')}


# ---------------------------------------------------------------------------
# The runs
# ---------------------------------------------------------------------------

def _pipe_run(map_text: str, work: Path, run_a2vm
              ) -> Tuple[Path, Path, str]:
    """a2vm (run_a2vm(extra_args), the write log's file and bound) with
    its write log into a FIFO that gtrace reads; (events, summary, a2vm's
    output tail)."""
    make_tools()
    fifo = work / 'wlog.fifo'
    os.mkfifo(str(fifo))
    (work / 'map.txt').write_text(map_text)
    ev, sm = work / 'events.ev', work / 'summary.txt'
    gt = subprocess.Popen(
        ['/bin/sh', '-c', 'exec "$0" "$1" "$2" "$3" < "$4"', str(GTRACE),
         str(work / 'map.txt'), str(ev), str(sm), str(fifo)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True,
        preexec_fn=lambda: _fsize(EV_MAX))
    extra = ['--write-log-file', str(fifo),
             '--write-log-limit', str(LINES_MAX)]
    try:
        tail = run_a2vm(extra)
    finally:
        # (a2vm that never opened the FIFO leaves gtrace waiting: a writer
        # that opens and closes it ends gtrace's input)
        try:
            fd = os.open(str(fifo), os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
        except OSError:
            pass
        try:
            out, _ = gt.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            gt.kill()
            out, _ = gt.communicate()
            raise RecError('gtrace did not finish')
    if gt.returncode:
        raise RecError('gtrace failed (%d): %s' % (gt.returncode, out[-500:]))
    return ev, sm, tail


def _fsize(n: int) -> None:
    import resource
    resource.setrlimit(resource.RLIMIT_FSIZE, (n, n))


def play_run(scene: str, play: Path, work: Path, profile: str,
             bwait_idle: bool = False, timeout: float = 3600.0
             ) -> Dict[str, Any]:
    from a2vm import costs
    from native import playdisk as P, playlink as PK, pldisk
    sc = SCENES[scene]
    prof = P.PROFILES[profile]
    hz = costs.parameters(prof)['fabric_mhz'] * 1e6
    disk = P.build(play, work / 'DOOM.hdv')
    boot = pldisk.load_boot(play / 'card')
    b = PK.tic_build(play)
    map_text, units, facts = build_map(b, 'play', sc['window'], hz, boot,
                                       play)
    manifest = []
    for name, file_type, aux, data in disk.files:
        if name == 'PRODOS':
            continue
        (work / name).write_bytes(data)
        manifest.append('%s %02X %04X %s' % (name, file_type, aux,
                                             work / name))
    (work / 'prodos.txt').write_text('\n'.join(manifest) + '\n')
    (work / 'DOOM.hdv').unlink()
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    (work / 'poison.img').write_bytes(pldisk.poison_image())
    (work / 'cost.txt').write_text(costs.text(prof))
    script = ''.join('%s %s\n' % (_at(t, hz), e) for t, e in sc['events'])
    (work / 'events.txt').write_text(P.script_events(disk, script))
    lab = P.labels(disk)
    args = [str(P.A2VM), '--rom', str(work / 'rom.bin'),
            '--core', 'w65c02s', '--via-ora-nh',
            '--image', str(work / 'poison.img'),
            '--prodos', str(work / 'prodos.txt'),
            '--volume', pldisk.VOLUME, '--launched', pldisk.SYSTEM,
            '--load', '2000:%s' % (work / pldisk.SYSTEM),
            '--reg', 'pc=2000', '--reg', 's=FF',
            '--cost', str(work / 'cost.txt'), '--cost-timed',
            '--irq-bounds', P.IRQ_BOUNDS,
            '--idle', '%X:vbl' % lab['dl_mwait'],
            # (no stop at the boot's bt_halt: frame slots run code at its
            # address, main $2000-$5FFF; playdisk.boot_halted)
            '--stop-pc', '%X' % lab['pl_crash'],
            '--stop-pc', '%X' % lab['dl_halt'],
            '--cycles', str(int(sc['seconds'] * hz)),
            '--every-limit', '64',
            '--input', str(work / 'events.txt'),
            '--amem', '--state', str(work / 'state.json'),
            '--write-log', facts['write_log']]
    if bwait_idle:
        args += ['--idle', '%X:vbl' % lab['dl_bwait']]

    def go(extra):
        r = bounded.run(args + extra, timeout=timeout, max_bytes=64 << 20,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        universal_newlines=True)
        return r.stdout[-2000:]
    ev, sm, tail = _pipe_run(map_text, work, go)
    state = json.loads((work / 'state.json').read_text()) \
        if (work / 'state.json').exists() else {}
    return {'ev': ev, 'sum': sm, 'units': units, 'facts': facts, 'hz': hz,
            'end': state.get('end'), 'tail': tail,
            'build': 'play %s' % play, 'profile': prof}


def lock_run(scene: str, work: Path, profile: str, image: str = 'game',
             timeout: float = 7200.0) -> Dict[str, Any]:
    from a2vm import costs
    from native import grun as G, ticcap as TC, ticrun as T
    sc = SCENES[scene]
    ref = TC.load(sc['run'])
    if ref is None:
        raise RecError('no reference of %s' % sc['run'])
    G.make(image)
    b = G.load_build(G.GAME / image, image)
    hz = costs.parameters(profile)['fabric_mhz'] * 1e6
    map_text, units, facts = build_map(b, 'lock', sc['window'], hz)
    img, case, up, banks = T.build_image(sc['run'], ref, b, 0xA5, 'front',
                                         int(sc['window'][2]) + 1,
                                         lambda *a: None)
    img.poke_label('dg_nosnap', b'\1')
    extra0 = ['--write-log', facts['write_log']]

    def go(extra):
        r = G.run(img, work / 'run', GL.MODES['LOCKSTEP'], banks=banks,
                  profile=profile, cycles=400_000_000_000, timeout=timeout,
                  extra=extra0 + list(extra))
        return 'end %s' % r.ended()
    ev, sm, tail = _pipe_run(map_text, work, go)
    return {'ev': ev, 'sum': sm, 'units': units, 'facts': facts, 'hz': hz,
            'end': tail, 'tail': tail, 'build': 'lockstep %s' % image,
            'profile': profile}


def summarize(sum_path: Path, hz: float) -> Dict[str, Any]:
    """The figures of a run's phases: frames (a phase written and the next
    phase's start known), ms a frame (start to next start), the tic
    phase's ms a frame, tics, loads and pages a tic."""
    rows, totals = [], {}
    for line in sum_path.read_text().splitlines():
        if line.startswith('#'):
            k, v = line[1:].split()
            totals[k] = int(v)
            continue
        f = [int(x) for x in line.split()]
        rows.append(f)
    frames = []
    for i, r in enumerate(rows):
        if r[0] != 1 or i + 1 >= len(rows):
            continue
        frames.append({'ms': (rows[i + 1][1] - r[1]) / hz * 1000,
                       'tic_ms': (r[2] - r[1]) / hz * 1000, 'gametic': r[3],
                       'tics': r[4], 'loads': r[5], 'pages': r[6]})
    n = len(frames)
    tics = sum(f['tics'] for f in frames)
    out = dict(totals)
    if n:
        ms = sum(f['ms'] for f in frames) / n
        out.update({'frames': n, 'tics': tics,
                    'ms_a_frame': round(ms, 2),
                    'fps': round(1000.0 / ms, 3),
                    'tic_phase_ms_a_frame': round(
                        sum(f['tic_ms'] for f in frames) / n, 2),
                    'tics_a_frame': round(tics / n, 3),
                    'loads_a_tic': round(sum(f['loads'] for f in frames) /
                                         max(tics, 1), 2),
                    'pages_a_tic': round(sum(f['pages'] for f in frames) /
                                         max(tics, 1), 2),
                    'max_ms': round(max(f['ms'] for f in frames), 1),
                    'gametics': [frames[0]['gametic'],
                                 frames[-1]['gametic'] + frames[-1]['tics']]})
    else:
        out.update({'frames': 0})
    return out


def record(scene: str, out: Path = OUT, play: Optional[Path] = None,
           profile: str = 'f121', bwait_idle: bool = False,
           say=print) -> Dict[str, Any]:
    """One scene: its events and its figures into OUT (SCENE.ev,
    SCENE.json)."""
    from native import playdisk as P
    sc = SCENES[scene]
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='tmp-gplacerec-%s-' % scene,
                                 dir=str(BUILD)))
    t0 = time.time()
    try:
        if sc['kind'] == 'play':
            r = play_run(scene, play or P.PLAY, work, profile, bwait_idle)
        else:
            r = lock_run(scene, work, profile)
        fig = summarize(r['sum'], r['hz'])
        meta = {'format': 'gplace-trace 1', 'scene': scene,
                'kind': sc['kind'], 'window': list(sc['window']),
                'build': r['build'], 'profile': r['profile'],
                'bwait_idle': bwait_idle, 'end': r['end'],
                'host_s': round(time.time() - t0, 1),
                'units': r['units'], 'facts': r['facts'],
                'figures': fig}
        dst = out / ('%s.ev' % scene)
        shutil.move(str(r['ev']), str(dst))
        meta['events_sha256'] = hashlib.sha256(dst.read_bytes()).hexdigest()
        (out / ('%s.json' % scene)).write_text(json.dumps(meta, indent=1))
        say('%s: %s' % (scene, json.dumps({k: fig.get(k) for k in (
            'frames', 'tics', 'ms_a_frame', 'fps', 'tic_phase_ms_a_frame',
            'loads_a_tic', 'pages_a_tic', 'calls', 'pending_lost',
            'unknown_target')})))
        if not fig.get('frames'):
            raise RecError('%s: no phase in the window (%s; a2vm: %s)' % (
                scene, r['end'], r['tail'][-400:]))
        return meta
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def report(out: Path = OUT) -> List[str]:
    lines = []
    for p in sorted(out.glob('*.json')):
        m = json.loads(p.read_text())
        if m.get('format') != 'gplace-trace 1':
            continue
        f = m['figures']
        lines.append('%-7s %-8s frames %4s  %8s ms a frame  %6s FPS  tic '
                     'phase %8s ms  %6s loads a tic  %6s pages a tic' % (
                         m['scene'], m['profile'][:8], f.get('frames'),
                         f.get('ms_a_frame'), f.get('fps'),
                         f.get('tic_phase_ms_a_frame'), f.get('loads_a_tic'),
                         f.get('pages_a_tic')))
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('scenes', nargs='*')
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--play', type=Path)
    parser.add_argument('--profile', default='f121',
                        choices=('f121', 'fastpath'))
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--bwait-idle', action='store_true')
    parser.add_argument('--no-build', action='store_true',
                        help='use the play build as it is (no make)')
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args(argv)
    if args.report:
        print('\n'.join(report(args.out)))
        return 0
    bad = [s for s in args.scenes if s not in SCENES]
    if bad or not args.scenes:
        parser.error('scenes: %s' % ', '.join(SCENES))
    make_tools()
    if any(SCENES[s]['kind'] == 'play' for s in args.scenes) and \
            not args.no_build:
        from native import playdisk as P
        P.make(args.play or P.PLAY)
    if any(SCENES[s]['kind'] == 'lock' for s in args.scenes):
        from native import grun as G
        G.make('game')
    jobs = max(1, min(args.jobs, len(args.scenes)))
    with CF.ThreadPoolExecutor(jobs) as ex:
        futs = {ex.submit(record, s, args.out, args.play, args.profile,
                          args.bwait_idle): s for s in args.scenes}
        bad = 0
        for f in CF.as_completed(futs):
            try:
                f.result()
            except Exception as e:      # (each scene's failure, reported)
                print('%s: %s' % (futs[f], e), file=sys.stderr)
                bad += 1
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
