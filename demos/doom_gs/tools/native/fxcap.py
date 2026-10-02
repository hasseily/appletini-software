#!/usr/bin/env python3
"""The channel logic's cases and its checkpoint (milestone 11, part
fxchan; docs/SCREENS.md 3, comparisons 1-4; docs/m11-parts/fxchan.md).

Usage:  python3 tools/native/fxcap.py --capture [--runs demo3,...]
            [--jobs 2]                  the reference's sound calls
        python3 tools/native/fxcap.py --evict [--jobs 2]
            the eviction cases: ref816 --call of S_StartSound from
            synthetic states (a base state at a demo3 S_StartSound)
        python3 tools/native/fxcap.py --check [--random N] [--jobs 2]
            the checkpoint: every comparison, build/native/m11/fxchan/
            report.json
        python3 tools/native/fxcap.py --cost
            us a call on f121 and fastpath

The captures (ref816 runs of the release, the call log and three dump
points streamed through pipes and kept small): demo3, DEMO1, DEMO2 and
the tour, and `menu`, demo3 with the menu opened while a positional sound
plays and snd_SfxVolume then poked (the menu's volume, injected state
with a reason: the slider would take longer than the sound lasts). The
call log: S_StartSound, S_StartSound2, S_StopSound and S_UpdateSounds
(jumps=1: musFrame reaches it by JMP) with the channel block, FM,
snd_SfxVolume, gamemap and the player's mobj; their callees startSound,
stopChannel, isPlaying, docVolume, adjustParams (SS_C, SS_VOL, SS_SEP in
and out, the two mobjs' addresses) and absDelta (|delta| out). The
positions are not dumped (s2cap's open problem 1): the three dump points
inside adjustParams give the delta and the view angle where upstream
holds them in registers: at the JSL to R_PointToAngle3 (A, X: dx; _Dp:
dy) and at the two instructions after the view angle's loads (A: its
low, then high word). Where the angle is not reached (beyond the clip,
or a zero distance), absDelta's |dx|, |dy| are all the routine uses. So a
case's listener is (0, 0) (or FM less the delta when FM is a source of
the call, FM's absolute place being in the channel block), each source
the listener plus its delta, or less |delta|: upstream's arithmetic only
uses differences modulo 2^32, so the native routine on these positions
computes what upstream computed on the real ones (and the comparison
checks it on every call).

A reference call becomes a native case (fxcrun.Case): the channel table
(an origin's address to its kind and handle: 0 none, FM, the player's
mobj, else a mobj handle by address), mailboxes in a fixed pattern (a
busy channel's start and volume pending, a free one's stop), FM, the
listener, snd_SfxVolume, gamemap, the arguments, isPlaying's answers
(the reference's), the positions; its expected native outputs: the table
after, every mailbox after the reference's stops, starts and volumes
applied to the pattern (fxplay's mailbox rules), each adjust's audibility
with SS_VOL and SS_SEP when audible (the trace), FM after. A start that
upstream's startSound failed (X4: the sound not in the DOC plan) expects
the native decision: the start, without the reference's stop after it.
"""

import argparse
import hashlib
import json
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Set, \
    Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import fxcrun as R, s2cap as C, s2layout as S  # noqa: E402
from ref816 import bounded, dumps, refimage, title  # noqa: E402
from sound import fxchan as FX  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
PART = R.PART
CAP = PART / 'cap'
RUNS = ('demo3', 'demo1', 'demo2', 'tour', 'menu')
FORMAT = 'fxcap 1'
PIPE_LIMIT = 200 * 10 ** 6
JOBS = 2
M32 = 0xFFFFFFFF
NUM_UP = 8                      # upstream's NUM_CHANNELS [R s_sound65.s:30]
MENU_VOLUME = 8                 # the volume poked while the menu is up
EVICT_TIMEOUT = 60
SEED = 1101


class FxError(Exception):
    pass


# ---------------------------------------------------------------------------
# Upstream's places
# ---------------------------------------------------------------------------

class Places(NamedTuple):
    sym: Dict[str, int]
    chan: Tuple[int, int]           # the channel block (znear): address, size
    jsl_pta: int                    # adjustParams' JSL R_PointToAngle3
    pc_lalo: int                    # A = the view angle's low word
    pc_lahi: int                    # A = its high word
    dp: int                         # D at every call ($0900)
    consts: Dict[str, int]


_PLACES: Optional[Places] = None


def places() -> Places:
    global _PLACES
    if _PLACES is not None:
        return _PLACES
    names = ['S_StartSound', 'S_StartSound2', 'S_StopSound',
             'S_UpdateSounds', 'startSound', 'stopChannel', 'isPlaying',
             'docVolume', 'adjustParams', 'absDelta', 'units', 'getChannel',
             'CH_SFX', 'CH_ORIGIN', 'CH_PICKUP', 'CHANSFX', 'FM', 'SS_C',
             'SS_SFX', 'SS_VOL', 'SS_SEP', 'SS_T', 'snd_SfxVolume',
             'SND_PCM']
    sym = {n: C.sym('s_sound65.s:' + n) for n in names}
    for n in ('_g_gamemap', '_g_player', '_g_gametic', '_g_menuactive',
              '_Dp'):
        sym[n] = C.sym(n)
    sym['R_PointToAngle3'] = C.sym('r_iigs65.s:R_PointToAngle3')
    lo, hi = sym['adjustParams'], sym['units']
    sites = [a for a in C.jsl_sites(sym['R_PointToAngle3']) if lo <= a < hi]
    if len(sites) != 1:
        raise FxError('%d JSL R_PointToAngle3 in adjustParams' % len(sites))
    code = C.code().get(sites[0], hi - sites[0])
    at = [k for k in range(4, len(code) - 1) if code[k] == 0xB7]
    if len(at) < 2:
        raise FxError('the view angle\'s loads are not found')
    lalo, lahi = sites[0] + at[0] + 2, sites[0] + at[1] + 2
    if code[at[0] + 2] != 0xCD or code[at[1] + 2] != 0xED:
        raise FxError('the view angle\'s loads are not lda [_Dp],y; '
                      'cmp; ... lda [_Dp],y; sbc')
    chan = C._znear('s_sound65.s')
    if len(chan) != 1:
        raise FxError('s_sound65.s has %d znear fragments' % len(chan))
    _PLACES = Places(sym, chan[0], sites[0], lalo, lahi, 0x0900,
                     FX.constants())
    return _PLACES


def dp_abs(p: Places, name: str = '_Dp') -> int:
    return p.dp + p.sym[name] - C.direct_page()


# ---------------------------------------------------------------------------
# The capture
# ---------------------------------------------------------------------------

def routines(p: Places, run: str) -> List[Tuple[str, str]]:
    u = 's_sound65.s:'
    chan = '%06X:%d' % p.chan
    world = ('_g_gametic:4+s_sound65.s:snd_SfxVolume:2+_g_gamemap:2+'
             '_g_player:4+_g_menuactive:2')
    nomenu = '' if run == 'menu' else ',if=_g_menuactive:2:eq:0'
    top = '%%s,in=dp:_Dp:4+%s+%s,out=%s' % (chan, world, chan)
    ss = u + 'SS_C:2+' + u + 'SS_SFX:2+' + u + 'SS_VOL:2+' + u + 'SS_SEP:2'
    return [
        ('S_StartSound', top % (u + 'S_StartSound')),
        ('S_StartSound2', top % (u + 'S_StartSound2')),
        ('S_StopSound', top % (u + 'S_StopSound')),
        ('S_UpdateSounds', u + 'S_UpdateSounds,jumps=1,in=%s+%s,out=%s%s'
         % (chan, world, chan, nomenu)),
        ('startSound', u + 'startSound,in=' + ss),
        ('stopChannel', u + 'stopChannel,in=' + u + 'CH_SFX:16'),
        ('isPlaying', u + 'isPlaying' + nomenu),
        ('docVolume', u + 'docVolume,in=' + ss + nomenu),
        ('adjustParams', u + 'adjustParams,in=dp:_Dp:8+' + ss + ',out=' +
         ss + nomenu),
        ('absDelta', u + 'absDelta,out=' + u + 'SS_T:4' + nomenu),
    ]


def points(p: Places, run: str) -> List[C.Point]:
    dpa = dp_abs(p)
    cond = '' if run == 'menu' else ',if=%06X:2:eq:0' % p.sym['_g_menuactive']
    return [C._pc('P_PTA', p.jsl_pta, [(dpa, 4)], cond),
            C._pc('P_LALO', p.pc_lalo, [(dpa, 1)], cond),
            C._pc('P_LAHI', p.pc_lahi, [(dpa, 1)], cond)]


def menu_script(work: Path, tic: int) -> Path:
    """demo3 with snd_SfxVolume poked to MENU_VOLUME at gametic `tic` (a
    positional sound playing) and the menu opened in the same frame: its
    first paused frames' S_UpdateSounds see the new volume while the sound
    still plays (the menu's gray conversion then takes about 1.4 s of
    machine time, longer than the sounds)."""
    text = '\n'.join((
        '# part fxchan: the menu over demo3 while a positional sound plays',
        'wait d_main65.s:pagedrawn == 1 within 90s   # the title page',
        'wait _g_demoplayback == 1 within 60s',
        'wait _g_gamestate == 0 within 10s',
        'at %dt poke s_sound65.s:snd_SfxVolume %d   # the volume' % (
            tic, MENU_VOLUME),
        'press escape                         # the menu over the demo',
        'wait _g_menuactive == 1 within 10s',
        'at +150f stop', ''))
    path = work / 'menu.script'
    path.write_text(text)
    return path


class Sink:
    def __init__(self):
        self.lines: List[Dict] = []
        self.end: Optional[Dict] = None

    def feed(self, handle) -> None:
        first = handle.readline()
        if not first:
            raise FxError('the call log is empty')
        while True:
            line = handle.readline()
            if not line:
                break
            obj = json.loads(line)
            if obj.get('end'):
                self.end = obj
                break
            self.lines.append(obj)
        if self.end is None:
            raise FxError('the call log ends without its last line')


class DumpSink:
    def __init__(self):
        self.dumps: List[Dict] = []

    def feed(self, handle) -> None:
        for d in dumps.read(handle):
            h = d.header
            self.dumps.append({'point': h['point'], 'cycles': h['cycles'],
                               'a': h['cpu']['a'], 'x': h['cpu']['x'],
                               'd': h['cpu']['d'], 'data': d.data.hex()})


def capture(run: str, out: Path = CAP, menu_tic: Optional[int] = None
            ) -> Dict[str, Any]:
    C.check_disk(BUILD)
    p = places()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='cap-%s-' % run, dir=str(PART)))
    try:
        script_path = None
        machine_run = run
        if run == 'menu':
            if menu_tic is None:
                menu_tic = pick_menu_tic(out)
            script_path = menu_script(work, menu_tic)
            machine_run = 'demo3'
        logged = routines(p, run)
        pts = points(p, run)
        sink, dsink = Sink(), DumpSink()
        result = C.machine(machine_run, work, pts, logged, dsink.feed,
                           sink.feed, traffic=C.Traffic(PIPE_LIMIT),
                           script_path=script_path)
        names = [n for n, _ in logged]
        for c in sink.lines:
            c['name'] = names[c['routine']]
        body = {'format': FORMAT, 'run': run, 'routines': logged,
                'points': [x.text for x in pts], 'calls': sink.lines,
                'dumps': dsink.dumps, 'problems': result['problems'],
                'menu_tic': menu_tic, 'arrivals': sink.end.get('arrivals'),
                'end': result['state'].get('end')}
        blob = zlib.compress(json.dumps(body, sort_keys=True).encode(), 6)
        C.write_atomic(out / (run + '.json.z'), blob)
        return {'run': run, 'calls': len(sink.lines),
                'dumps': len(dsink.dumps), 'bytes': len(blob),
                'traffic': result['traffic'], 'problems': result['problems']}
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def load_capture(run: str, root: Path = CAP) -> Dict[str, Any]:
    path = root / (run + '.json.z')
    body = json.loads(zlib.decompress(path.read_bytes()))
    if body.get('format') != FORMAT:
        raise FxError('%s is not an fxcap capture' % path)
    return body


def pick_menu_tic(root: Path = CAP) -> int:
    """A gametic of demo3 at which a positional sound (an origin neither
    none nor the player's mobj) has played for a few frames and goes on:
    the first S_UpdateSounds with a docVolume whose next 4 calls also
    have one."""
    body = load_capture('demo3', root)
    p = places()
    ups = [c for c in body['calls'] if c['name'] == 'S_UpdateSounds']
    vols = {c['parent'] for c in body['calls'] if c['name'] == 'docVolume'}
    flags = [c['call'] in vols for c in ups]
    for k in range(3, len(ups) - 4):
        if all(flags[k - 3:k + 5]):
            w = world_of(p, mem_in(ups[k], 1, 5))
            return w['gametic'] + 1
    raise FxError('no positional sound in demo3 lasts 8 frames')


# ---------------------------------------------------------------------------
# Calls into cases
# ---------------------------------------------------------------------------

def mem_in(call: Dict, k: int, n: int = 1) -> bytes:
    """The in ranges k .. k + n - 1, joined."""
    return b''.join(bytes.fromhex(x) for x in call['in']['mem'][k:k + n])


def mem_out(call: Dict, k: int, n: int = 1) -> bytes:
    return b''.join(bytes.fromhex(x) for x in call['out']['mem'][k:k + n])


def le(b: bytes, at: int, n: int) -> int:
    return int.from_bytes(b[at:at + n], 'little')


def world_of(p: Places, w: bytes) -> Dict[str, int]:
    return {'gametic': le(w, 0, 4), 'sndvol': le(w, 4, 2),
            'gamemap': le(w, 6, 2), 'player': le(w, 8, 4),
            'menu': le(w, 12, 2)}


class Table(NamedTuple):
    sfx: List[int]
    origin: List[int]
    pickup: List[int]
    fm: Tuple[int, int]


def table_of(p: Places, block: bytes) -> Table:
    base = p.chan[0]
    c = p.consts

    def at(name, k, n):
        o = p.sym[name] - base + k * n
        return le(block, o, n)
    fm = p.sym['FM'] - base
    return Table([at('CH_SFX', k, 2) for k in range(NUM_UP)],
                 [at('CH_ORIGIN', k, 4) for k in range(NUM_UP)],
                 [at('CH_PICKUP', k, 2) for k in range(NUM_UP)],
                 (le(block, fm + c['OFS_MO_X'], 4),
                  le(block, fm + c['OFS_MO_Y'], 4)))


class Adj(NamedTuple):
    c: int                      # SS_C / 2 at the entry
    lis: int                    # the listener's address (0: none)
    src: int                    # the source's address
    aud: bool
    vol: int                    # SS_VOL, SS_SEP at the return
    sep: int
    adx: Optional[int]
    ady: Optional[int]
    dxy: Optional[Tuple[int, int]]
    la: Optional[int]


class Ref(NamedTuple):
    """A top-level call of the reference."""
    run: str
    hit: int
    op: str
    world: Dict[str, int]
    sfx: int
    origin: int
    before: Table
    after: Table
    events: List[Tuple]         # ('stop', c) ('start', c, sfx, vol, sep,
                                # ok) ('play', c, ans) ('vol', c, vol, sep)
    adjs: List[Adj]


OPS = {'S_StartSound': 'start', 'S_StartSound2': 'start2',
       'S_StopSound': 'stop', 'S_UpdateSounds': 'update'}


def refs_of(body: Dict) -> List[Ref]:
    p = places()
    calls = body['calls']
    by_parent: Dict[int, List[Dict]] = {}
    for c in calls:
        by_parent.setdefault(c['parent'], []).append(c)
    dumps_sorted = sorted(body['dumps'], key=lambda d: d['cycles'])
    dcycles = [d['cycles'] for d in dumps_sorted]
    out = []
    import bisect

    def dumps_in(call):
        lo = bisect.bisect_left(dcycles, call['cycles'])
        hi = bisect.bisect_right(dcycles, call['out']['cycles'])
        return dumps_sorted[lo:hi]

    def children(call, name=None):
        kids = sorted(by_parent.get(call['call'], []),
                      key=lambda c: c['call'])
        return [k for k in kids if name is None or k['name'] == name]

    for c in sorted(calls, key=lambda c: c['call']):
        op = OPS.get(c['name'])
        if op is None or not c.get('returned'):
            continue
        if op == 'start' and c['depth'] > 0:
            continue            # S_StartSound2's fall into S_StartSound
        if c['depth'] > 0 and op != 'start':
            # nested top calls: S_StartSound2 is never nested
            pass
        top = c
        if op == 'start2':
            kids_all = children(c)
        else:
            kids_all = children(c)
        k0 = 0 if op == 'update' else 1      # after _Dp
        before = table_of(p, mem_in(top, k0))
        after = table_of(p, mem_out(top, 0))
        world = world_of(p, mem_in(top, k0 + 1, 5))
        events: List[Tuple] = []
        adjs: List[Adj] = []
        # S_StartSound2's own children are S_StartSound's (it falls
        # through, no call); S_StartSound inside S_StartSound2 does not
        # exist: a fall, not a call
        for k in kids_all:
            n = k['name']
            if n == 'stopChannel':
                ch = k['in']['x'] // 2
                had = le(mem_in(k, 0), 2 * ch, 2)
                if had:
                    events.append(('stop', ch))
            elif n == 'startSound':
                m = mem_in(k, 0, 4)
                ok = bool(k['out']['p'] & 1)
                events.append(('start', le(m, 0, 2) // 2, le(m, 2, 2),
                               le(m, 4, 2), le(m, 6, 2), ok))
            elif n == 'isPlaying':
                events.append(('play', k['in']['x'] // 2,
                               bool(k['out']['p'] & 1)))
            elif n == 'docVolume':
                m = mem_in(k, 0, 4)
                events.append(('vol', k['in']['x'] // 2, le(m, 4, 2),
                               le(m, 6, 2)))
            elif n == 'adjustParams':
                m = mem_in(k, 0, 5)
                mo = mem_out(k, 0, 4)
                ads = children(k, 'absDelta')
                adx = le(mem_out(ads[0], 0), 0, 4) if len(ads) > 0 else None
                ady = le(mem_out(ads[1], 0), 0, 4) if len(ads) > 1 else None
                dd = dumps_in(k)
                dxy = la = None
                pta = [d for d in dd if d['point'] == 0]
                lalo = [d for d in dd if d['point'] == 1]
                lahi = [d for d in dd if d['point'] == 2]
                if pta:
                    d = pta[0]
                    if d['d'] != p.dp:
                        raise FxError('D is $%04X, not $%04X' % (d['d'],
                                                                 p.dp))
                    dy = int.from_bytes(bytes.fromhex(d['data'])[:4],
                                        'little')
                    dxy = ((d['a'] | d['x'] << 16) & M32, dy)
                if lalo and lahi:
                    la = (lalo[0]['a'] | lahi[0]['a'] << 16) & M32
                adjs.append(Adj(le(m, 8, 2) // 2, le(m, 0, 4), le(m, 4, 4),
                                bool(k['out']['p'] & 1), le(mo, 4, 2),
                                le(mo, 6, 2), adx, ady, dxy, la))
                events.append(('adj', len(adjs) - 1))
        sfx = top['in']['a'] if op in ('start', 'start2') else 0
        origin = le(mem_in(top, 0), 0, 4)
        out.append(Ref(body['run'], c['hit'], op, world, sfx, origin,
                       before, after, events, adjs))
    return out


# ---------------------------------------------------------------------------
# A reference call as a native case
# ---------------------------------------------------------------------------

NO = FX.NO_HANDLE
PLAYER_HANDLE = 0x0001


class Native(NamedTuple):
    """A case's native input (host terms) and what it must give."""
    ref: Optional[Ref]
    op: str
    sfx: int
    kind: int
    handle: int
    x: int
    y: int
    chans: List[FX.Chan]
    mail: List[FX.Mail]
    fm: Tuple[int, int]
    sndvol: int
    gamemap: int
    lis: Optional[Tuple[int, int, int]]
    pos: Dict[int, Tuple[int, int, int]]
    play: List[bool]
    # expected (reference), None where not compared
    exp_table: Optional[List[Tuple[int, int, int, int]]]
    exp_mail: Optional[List[Tuple[int, int, int, int]]]
    exp_trace: Optional[List[Tuple[Optional[int], int, int, int]]]
    exp_fm: Optional[Tuple[int, int]]
    x4: bool                    # a failed start of upstream (injected)
    labels: Set[str]


def ident(p: Places, addr: int, player: int, ids: Dict[int, int]
          ) -> Tuple[int, int]:
    if addr == 0:
        return FX.NONE, NO
    if addr == p.sym['FM']:
        return FX.FM, NO
    if addr == player:
        return FX.PLAYER, PLAYER_HANDLE
    if addr not in ids:
        ids[addr] = 0x0200 + len(ids)
    return FX.MOBJ, ids[addr]


def mail_pattern(chans: Sequence[FX.Chan]) -> List[FX.Mail]:
    out = []
    for k, ch in enumerate(chans):
        if ch.sfx:
            out.append(FX.Mail(FX.MX_START | FX.MX_VOLUME, ch.sfx,
                               0x40 + k, 0x80 + k))
        else:
            out.append(FX.Mail(FX.MX_STOP, 0, 0, 0))
    return out


def apply_mail(mail: List[FX.Mail], ev: Tuple) -> None:
    kind = ev[0]
    if kind == 'stop':
        m = mail[ev[1]]
        m.flags = (m.flags | FX.MX_STOP) & ~(FX.MX_START | FX.MX_VOLUME) \
            & 0xFF
    elif kind == 'start':
        m = mail[ev[1]]
        m.flags |= FX.MX_START
        m.sound, m.vol, m.sep = ev[2] & 0xFF, ev[3] & 0xFF, ev[4] & 0xFF
    elif kind == 'vol':
        m = mail[ev[1]]
        m.flags |= FX.MX_VOLUME
        m.vol = ev[2] & 0xFF


def delta_of(a: Adj) -> Optional[Tuple[int, int]]:
    """source - listener: exact at the angle's JSL, else -|d| (so that
    listener - source = |d|), None when no absDelta ran (no listener)."""
    if a.dxy is not None:
        return a.dxy
    if a.adx is None or a.ady is None:
        return None
    return ((-a.adx) & M32, (-a.ady) & M32)


def native_of(ref: Ref, nchan: int = NUM_UP,
              ids: Optional[Dict[int, int]] = None) -> Native:
    p = places()
    player = ref.world['player']
    if ids is None:
        ids = {}
    chans = []
    for k in range(nchan):
        kind, h = ident(p, ref.before.origin[k], player, ids)
        chans.append(FX.Chan(ref.before.sfx[k] & 0xFF, kind,
                             bool(ref.before.pickup[k]), h, 0, 0))
    mail = mail_pattern(chans)
    exp_mail = [m.copy() for m in mail]
    labels: Set[str] = set()
    x4 = False
    for ev in ref.events:
        if ev[0] == 'start':
            apply_mail(exp_mail, ev)
            if not ev[5]:
                x4 = True
                labels.add('ss:start-failed')
            else:
                labels.add('ss:started')
        elif ev[0] == 'stop':
            if x4 and ev[1] == [e for e in ref.events
                                if e[0] == 'start'][-1][1]:
                continue        # X4: the failed start's stop, injected
            apply_mail(exp_mail, ev)
        elif ev[0] == 'vol':
            apply_mail(exp_mail, ev)
    # the positions: the listener at (0, 0), or anchored by FM
    fm = ref.before.fm if ref.op != 'start2' else ref.after.fm
    lx = ly = 0
    for a in ref.adjs:
        if a.src == p.sym['FM']:
            d = delta_of(a)
            if d is not None:
                lx, ly = (fm[0] - d[0]) & M32, (fm[1] - d[1]) & M32
            break
    la = next((a.la for a in ref.adjs if a.la is not None), 0)
    lis = (lx, ly, la) if player else None
    pos: Dict[int, Tuple[int, int, int]] = {}
    src_xy: Dict[int, Tuple[int, int]] = {}
    for a in ref.adjs:
        d = delta_of(a)
        if d is None:
            continue
        xy = ((lx + d[0]) & M32, (ly + d[1]) & M32)
        old = src_xy.get(a.src)
        if old is not None and old != xy:
            if a.dxy is None:
                continue        # keep the exact one
        src_xy[a.src] = xy
    for addr, xy in src_xy.items():
        kind, h = ident(p, addr, player, ids)
        if kind == FX.MOBJ:
            pos[h] = (xy[0], xy[1], 0)
    play = [False] * nchan
    for ev in ref.events:
        if ev[0] == 'play':
            play[ev[1]] = ev[2]
    # the call's arguments
    kind, h = ident(p, ref.origin, player, ids) if ref.op != 'start2' \
        else (FX.FM, NO)
    x = y = 0
    if ref.op in ('start', 'start2'):
        if kind == FX.FM:
            x, y = ref.after.fm
        elif kind == FX.MOBJ and ref.origin in src_xy:
            x, y = src_xy[ref.origin]
    exp_table = []
    for k in range(nchan):
        kk, hh = ident(p, ref.after.origin[k], player, ids)
        sfx = ref.after.sfx[k] & 0xFF
        exp_table.append((sfx, kk, bool(ref.after.pickup[k]), hh))
    if x4:
        st = [e for e in ref.events if e[0] == 'start'][-1]
        c = st[1]
        e = exp_table[c]
        exp_table[c] = (st[2] & 0xFF, e[1], e[2], e[3])
    trace = []
    for a in ref.adjs:
        if not a.lis:
            continue            # no listener: the native asks s2t_pos only
        trace.append((a.c if ref.op == 'update' else None, a.aud,
                      a.vol & 0xFFFF, a.sep & 0xFFFF))
    exp_fm = ref.after.fm if ref.op == 'start2' else None
    sfx = ref.sfx & 0xFFFF
    return Native(ref, ref.op, sfx, kind, h, x, y, chans, mail,
                  ref.before.fm, ref.world['sndvol'] & 0xFF,
                  ref.world['gamemap'], lis, pos, play, exp_table,
                  [m.tuple() for m in exp_mail], trace, exp_fm, x4, labels)


# ---------------------------------------------------------------------------
# Natives into fxcrun cases; the model on them
# ---------------------------------------------------------------------------

def chan_bytes(chans: Sequence[FX.Chan]) -> bytes:
    out = bytearray()
    for ch in chans:
        out += bytes([ch.sfx & 0xFF, (ch.kind & 3) | (0x80 if ch.pickup
                                                      else 0)])
        out += struct.pack('<HII', ch.handle & 0xFFFF, ch.x & M32,
                           ch.y & M32)
    return bytes(out)


def mail_bytes(mail: Sequence[FX.Mail]) -> bytes:
    return b''.join(bytes([m.flags & 0xFF, m.sound & 0xFF, m.vol & 0xFF,
                           m.sep & 0xFF]) for m in mail)


def s2t_tail(fm, lis, ls_on, sndvol) -> bytes:
    lx, ly, la = lis if lis is not None else (0, 0, 0)
    return struct.pack('<IIIII', fm[0] & M32, fm[1] & M32, lx & M32,
                       ly & M32, la & M32) + bytes([0x80 if ls_on else 0,
                                                    sndvol & 0xFF])


def args_bytes(n: Native) -> bytes:
    return struct.pack('<HBHII', n.sfx & 0xFFFF, n.kind, n.handle & 0xFFFF,
                       n.x & M32, n.y & M32)


def pos_bytes(n: Native) -> bytes:
    entries = []
    if n.lis is not None:
        entries.append((FX.LISTENER, n.lis))
    for h, xyz in sorted(n.pos.items()):
        entries.append((h, xyz))
    if len(entries) > R.POS_MAX:
        raise FxError('%d positions' % len(entries))
    out = bytes([len(entries)])
    for h, (x, y, a) in entries:
        out += struct.pack('<HIII', h, x & M32, y & M32, a & M32)
    return out


def case_of(b: R.Build, n: Native, voices: Optional[bytes] = None,
            first: bool = True) -> R.Case:
    """The fxcrun case of a native input (first: the whole state; else
    only the world and the arguments, the sequence's state carried)."""
    lab = b.labels
    s2t = b.s2t_base + S.S2T['FM_X']
    pokes = []
    if first:
        tail = s2t_tail(n.fm, n.lis, n.lis is not None, n.sndvol)
        pokes += [(b.sc_base, chan_bytes(n.chans) + mail_bytes(n.mail)),
                  (s2t, tail[:R.S2T_RUN]),
                  (R.extra_base(b), tail[R.S2T_RUN:])]
    pokes += [(FX_GAMEMAP, struct.pack('<H', n.gamemap)),
              (FX_GA, args_bytes(n))]
    if 'fcd_play' in lab:
        pokes.append((lab['fcd_play'], bytes(1 if x else 0 for x in n.play)
                      + bytes(8 - len(n.play))))
    if 'fcd_posn' in lab:
        pokes.append((lab['fcd_posn'], pos_bytes(n)))
    if voices is not None:
        pokes.append((S.FXV_BASE, voices))
    return R.Case(n.op, pokes)


FX_GA = 0x48
FX_GAMEMAP = 0x1DBE


def check_consts() -> None:
    from native import glayout as GL, llayout as LL
    if GL.GA_RANGE[0] != FX_GA or LL.G['G_GAMEMAP'] != FX_GAMEMAP:
        raise FxError('the arguments\' or gamemap\'s place moved')


def model_of(n: Native, nosep: bool = False) -> FX.Model:
    m = FX.new_model(len(n.chans), nosep=nosep)
    m.chans = [c.copy() for c in n.chans]
    m.mail = [x.copy() for x in n.mail]
    m.fm = n.fm
    m.ls = n.lis if n.lis is not None else (0, 0, 0)
    m.ls_on = n.lis is not None
    m.sndvol = n.sndvol
    m.gamemap = n.gamemap
    world = dict(n.pos)
    lis = n.lis
    m.pos = lambda h: (lis if h == FX.LISTENER else world.get(h))
    play = list(n.play)
    m.playing = lambda c: play[c]
    return m


def model_call(m: FX.Model, n: Native) -> List[Tuple]:
    """Run the op on the model; its trace (c, aud, vol, sep) per adjust
    (c None for a start)."""
    trace: List[Tuple] = []
    orig = m.adjust
    if n.op == 'update':
        _update_traced(m, trace, orig)
        return trace

    def traced(sx, sy, lis, update=False):
        r = orig(sx, sy, lis, update)
        trace.append((None, m.aud, m.vol & 0xFFFF, m.sep & 0xFFFF))
        return r
    m.adjust = traced
    try:
        if n.op == 'start':
            m.start(n.sfx, n.kind, n.handle, n.x, n.y)
        elif n.op == 'start2':
            m.start2(n.sfx, n.x, n.y)
        elif n.op == 'stop':
            m.stop(n.kind, n.handle)
    finally:
        m.adjust = orig
    return trace


def _update_traced(m: FX.Model, trace: List[Tuple], orig) -> None:
    """FX.Model.update with each adjust's channel in the trace."""
    def wrapped(c):
        def f(sx, sy, lis, update=False):
            r = orig(sx, sy, lis, update)
            trace.append((c, m.aud, m.vol & 0xFFFF, m.sep & 0xFFFF))
            return r
        return f
    lis = m.listener()
    if lis is None:
        return
    for c, ch in enumerate(m.chans):
        if not ch.sfx:
            continue
        if not m.playing(c):
            m.stop_channel(c)
            continue
        if ch.kind in (FX.NONE, FX.PLAYER):
            continue
        if ch.kind == FX.FM:
            x, y = m.fm
        else:
            pp = m.pos(ch.handle)
            if pp is None:
                raise FX.ModelError('no position for $%04X' % ch.handle)
            x, y = pp[0] & M32, pp[1] & M32
            ch.x, ch.y = x, y
        m.sep = FX.NORM_SEP
        m.vol = m.sndvol & 0xFFFF
        if wrapped(c)(x, y, lis, update=True):
            m.mail_volume(c)
        else:
            m.stop_channel(c)


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------

def native_trace(b: R.Build, out: R.Out) -> List[Tuple]:
    lab = b.labels
    return out.trace


def ref_table(out: R.Out, nchan: int) -> List[Tuple[int, int, int, int]]:
    t = []
    for k in range(nchan):
        r = out.table[k * S.CHAN_SIZE:(k + 1) * S.CHAN_SIZE]
        t.append((r[0], r[1] & 3, bool(r[1] & 0x80), r[2] | r[3] << 8))
    return t


def full_state(out: R.Out, nchan: int) -> bytes:
    return out.table + out.mail + out.s2t


def model_state(m: FX.Model) -> bytes:
    lis = m.ls if m.ls_on else (m.ls if m.ls else (0, 0, 0))
    return chan_bytes(m.chans) + mail_bytes(m.mail) + \
        struct.pack('<IIIII', m.fm[0] & M32, m.fm[1] & M32, m.ls[0] & M32,
                    m.ls[1] & M32, m.ls[2] & M32) + \
        bytes([0x80 if m.ls_on else 0, m.sndvol & 0xFF])


def compare_ref(n: Native, out: R.Out, nchan: int, nosep: bool = False
                ) -> List[str]:
    """The native outputs against the reference's (the fields the
    reference has)."""
    probs = []
    got = ref_table(out, nchan)
    for k in range(nchan):
        e = n.exp_table[k]
        g = got[k]
        if e[0] != g[0] or (e[0] and (e[1:] != g[1:])):
            probs.append('channel %d: %s, the reference %s' % (k, g, e))
    gm = [tuple(out.mail[4 * k:4 * k + 4]) for k in range(nchan)]
    for k in range(nchan):
        if gm[k] != tuple(n.exp_mail[k]):
            probs.append('mailbox %d: %s, the reference %s' % (
                k, gm[k], n.exp_mail[k]))
    tr = out.trace
    if len(tr) != len(n.exp_trace):
        probs.append('%d adjusts, the reference %d' % (len(tr),
                                                       len(n.exp_trace)))
    else:
        for (gc, ga, gv, gs), (ec, ea, ev, es) in zip(tr, n.exp_trace):
            if bool(ga) != bool(ea) or (ec is not None and gc != ec):
                probs.append('adjust of channel %s: audible %d, the '
                             'reference %s %d' % (gc, ga, ec, ea))
            elif ea and (gv != ev or (not nosep and gs != es)):
                probs.append('adjust of channel %s: vol %d sep %d, the '
                             'reference %d %d' % (gc, gv, gs, ev, es))
    if n.exp_fm is not None:
        fm = struct.unpack('<II', out.s2t[:8])
        if fm != tuple(n.exp_fm):
            probs.append('FM %s, the reference %s' % (fm, n.exp_fm))
    return probs


def compare_model(n: Native, out: R.Out, m: FX.Model, trace: List[Tuple],
                  nchan: int) -> List[str]:
    probs = []
    if full_state(out, nchan) != model_state(m):
        a, b = full_state(out, nchan), model_state(m)
        k = next(i for i in range(min(len(a), len(b))) if a[i] != b[i]) \
            if len(a) == len(b) else -1
        probs.append('the state differs from the model\'s at byte %d '
                     '(native %s, model %s)' % (k, a[max(0, k - 2):k + 6].hex(),
                                               b[max(0, k - 2):k + 6].hex()))
    tr = [(c, int(a), v, s) for c, a, v, s in out.trace]
    mt = [(c if n.op == 'update' else None, int(a), v, s)
          for c, a, v, s in trace]
    if [(t[1], t[2], t[3]) if t[1] else (t[1],) for t in tr] != \
            [(t[1], t[2], t[3]) if t[1] else (t[1],) for t in mt] or \
            (n.op == 'update' and [t[0] for t in tr] != [t[0] for t in mt]):
        probs.append('the trace %s, the model %s' % (tr[:4], mt[:4]))
    return probs


# ---------------------------------------------------------------------------
# The eviction cases (comparison 3): ref816 --call of S_StartSound and
# S_StartSound2 from synthetic states
# ---------------------------------------------------------------------------

BASE = CAP / 'base.img'
FAKE = 0x7E1000                 # fake mobjs: x, y at their offsets
DEGEN = 0x7E0800                # S_StartSound2's point
BASE_TIC = 1200


def base_script(work: Path) -> Path:
    path = work / 'base.script'
    path.write_text('\n'.join((
        '# part fxchan: demo3 to its first S_StartSound in the level',
        'wait d_main65.s:pagedrawn == 1 within 90s',
        'wait _g_demoplayback == 1 within 60s',
        'wait _g_gamestate == 0 within 10s',
        'at %dt stop' % BASE_TIC, '')))
    return path


def capture_base(out: Path = BASE) -> Dict[str, Any]:
    """The whole machine at an S_StartSound entry of demo3 in E1M7 (the
    5th), as a ref816 memory image: the base of the eviction cases."""
    C.check_disk(BUILD)
    p = places()
    work = Path(tempfile.mkdtemp(prefix='cap-base-', dir=str(PART)))
    got: List[dumps.Dump] = []
    try:
        pt = C.Point('BASE', 'pc=%06X,hits=5' % p.sym['S_StartSound'], ())

        def feed(handle):
            for d in dumps.read(handle):
                got.append(d)
        C.machine('demo3', work, [pt], [], feed, None,
                  script_path=base_script(work),
                  traffic=C.Traffic(PIPE_LIMIT))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    if len(got) != 1:
        raise FxError('%d base dumps' % len(got))
    d = got[0]
    cpu, sw = d.header['cpu'], d.header['switches']
    regs = refimage.Registers(pc=cpu['pc'] & 0xFFFF, pbr=cpu['pc'] >> 16,
                              dbr=cpu['dbr'], a=cpu['a'], x=cpu['x'],
                              y=cpu['y'], s=cpu['s'], d=cpu['d'], p=cpu['p'],
                              e=cpu['e'])
    switches = refimage.Switches(sw['newvideo'], sw['border'], sw['shadow'],
                                 sw['speed'])
    records = []
    at = 0
    for a, n in d.ranges():
        records.append((a, d.data[at:at + n]))
        at += n
    out.parent.mkdir(parents=True, exist_ok=True)
    C.write_atomic(out, refimage.image_bytes(regs, switches, records))
    return {'cycles': d.header['cycles'], 'bytes': len(d.data)}


class Syn(NamedTuple):
    """A synthetic call: S_StartSound or S_StartSound2 from this state."""
    name: str
    op: str                     # start, start2
    sfx: int
    kind: int
    handle: int
    xy: Tuple[int, int]         # the origin's (or the point's) position
    table: List[Tuple[int, int, int, bool]]     # sfx, kind, handle, pickup
    fm: Tuple[int, int]
    lis: Optional[Tuple[int, int, int]]
    sndvol: int
    gamemap: int
    fail: bool


class Base(NamedTuple):
    mem: refimage.Memory
    player: int                 # the player's mobj


_BASE: Optional[Base] = None


def base() -> Base:
    global _BASE
    if _BASE is None:
        img = refimage.read(BASE)
        mem = refimage.load(img)
        p = places()
        player = int.from_bytes(mem.get(p.sym['_g_player'], 4), 'little')
        for a in (FAKE, DEGEN):
            if any(mem.get(a, 0x800)):
                raise FxError('the fake mobjs\' place $%06X is not free' % a)
        _BASE = Base(mem, player)
    return _BASE


def address_of(kind: int, handle: int, player: int) -> int:
    p = places()
    if kind == FX.NONE:
        return 0
    if kind == FX.FM:
        return p.sym['FM']
    if kind == FX.PLAYER:
        return player
    return FAKE + 0x40 * (handle - 0x200)


def syn_pokes(s: Syn, bs: Base) -> List[Tuple[int, bytes]]:
    p = places()
    c = p.consts
    out = []
    player = bs.player if s.lis is not None else 0
    sfx = b''.join(struct.pack('<H', e[0]) for e in s.table)
    org = b''.join(struct.pack('<I', address_of(e[1], e[2], bs.player))
                   for e in s.table)
    pick = b''.join(struct.pack('<H', 1 if e[3] else 0) for e in s.table)
    out += [(p.sym['CH_SFX'], sfx), (p.sym['CH_ORIGIN'], org),
            (p.sym['CH_PICKUP'], pick), (p.sym['CHANSFX'], bytes(16)),
            (p.sym['FM'] + c['OFS_MO_X'], struct.pack('<I', s.fm[0] & M32)),
            (p.sym['FM'] + c['OFS_MO_Y'], struct.pack('<I', s.fm[1] & M32)),
            (p.sym['snd_SfxVolume'], struct.pack('<H', s.sndvol)),
            (p.sym['_g_gamemap'], struct.pack('<H', s.gamemap)),
            (p.sym['_g_player'], struct.pack('<I', player))]
    if s.lis is not None:
        out += [(bs.player + c['OFS_MO_X'], struct.pack('<I', s.lis[0])),
                (bs.player + c['OFS_MO_Y'], struct.pack('<I', s.lis[1])),
                (bs.player + c['OFS_MO_ANGLE'], struct.pack('<I', s.lis[2]))]
    if s.op == 'start2':
        origin = DEGEN
        out.append((DEGEN, struct.pack('<II', s.xy[0] & M32, s.xy[1] & M32)))
    else:
        origin = address_of(s.kind, s.handle, bs.player)
        if s.kind == FX.MOBJ:
            out += [(origin + c['OFS_MO_X'], struct.pack('<I', s.xy[0])),
                    (origin + c['OFS_MO_Y'], struct.pack('<I', s.xy[1]))]
    out.append((dp_abs(p), struct.pack('<I', origin)))
    if s.fail:
        out.append((p.sym['SND_PCM'] + 4 * (s.sfx & 0x7FFF), bytes(4)))
    return out


def run_syn(s: Syn, work: Path) -> Dict[str, Any]:
    """ref816 --call of the synthetic call: the stops, the start, whether
    getChannel was reached (audible) with SS_VOL, SS_SEP, the table
    after."""
    bs = base()
    p = places()
    work.mkdir(parents=True, exist_ok=True)
    pokes = work / 'pokes.img'
    regs = refimage.read(BASE).registers
    sw = refimage.read(BASE).switches
    pokes.write_bytes(refimage.image_bytes(regs, sw, syn_pokes(s, bs)))
    stream = work / 'calls.stream'
    chan = work / 'chan.bin'
    u = p.sym
    pts = ['pc=%06X,ranges=%06X:16' % (u['stopChannel'], u['CH_SFX']),
           'pc=%06X,ranges=%06X:2+%06X:2+%06X:2+%06X:2' % (
               u['startSound'], u['SS_C'], u['SS_SFX'], u['SS_VOL'],
               u['SS_SEP']),
           'pc=%06X,ranges=%06X:2+%06X:2' % (u['getChannel'], u['SS_VOL'],
                                             u['SS_SEP'])]
    entry = u['S_StartSound2' if s.op == 'start2' else 'S_StartSound']
    cmd = [str(title.MACHINE), str(BASE), '--load-image', str(pokes),
           '--reg', 'a=%X' % (s.sfx & 0xFFFF), '--call', '%06X' % entry,
           '--cycles', '50000000', '--state', str(work / 'state.json'),
           '--dump-stream', str(stream), '--dump-limit', '1000000',
           '--dump-max', '64',
           '--save', '%06X:%d:%s' % (p.chan[0], p.chan[1], chan)]
    for x in pts:
        cmd += ['--dump-at', x]
    r = bounded.run(cmd, timeout=EVICT_TIMEOUT, max_bytes=64 << 20,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    universal_newlines=True)
    if r.returncode:
        raise FxError('%s: ref816 --call failed: %s' % (s.name,
                                                       r.stdout[-800:]))
    state = json.loads((work / 'state.json').read_text())
    if not state.get('call', {}).get('returned'):
        raise FxError('%s: the call did not return' % s.name)
    ds = list(dumps.Stream(stream).dumps)
    events: List[Tuple] = []
    getch = None
    for d in ds:
        k = d.header['point']
        if k == 0:
            ch = d.header['cpu']['x'] // 2
            if le(d.data, 2 * ch, 2):
                events.append(('stop', ch))
        elif k == 1:
            events.append(['start', le(d.data, 0, 2) // 2, le(d.data, 2, 2),
                           le(d.data, 4, 2), le(d.data, 6, 2), True])
        else:
            getch = (le(d.data, 0, 2), le(d.data, 2, 2))
    st = [e for e in events if e[0] == 'start']
    if st:
        k = events.index(st[-1])
        if any(e[0] == 'stop' and e[1] == st[-1][1] for e in events[k + 1:]):
            st[-1][5] = False
    events = [tuple(e) for e in events]
    after = table_of(p, chan.read_bytes())
    shutil.rmtree(str(work), ignore_errors=True)
    return {'events': events, 'getch': getch, 'after': after}


def native_syn(s: Syn, res: Dict[str, Any]) -> Native:
    bs = base()
    p = places()
    chans = [FX.Chan(e[0] & 0xFF, e[1], e[3], e[2] if e[1] in
                     (FX.MOBJ, FX.PLAYER) else NO, 0, 0) for e in s.table]
    for ch in chans:
        if ch.kind == FX.PLAYER:
            ch.handle = PLAYER_HANDLE
    mail = mail_pattern(chans)
    exp_mail = [m.copy() for m in mail]
    labels: Set[str] = set()
    x4 = False
    events = res['events']
    st = [e for e in events if e[0] == 'start']
    for ev in events:
        if ev[0] == 'start':
            apply_mail(exp_mail, ev)
            if not ev[5]:
                x4 = True
                labels.add('ss:start-failed')
        elif ev[0] == 'stop':
            if x4 and st and ev[1] == st[-1][1]:
                continue
            apply_mail(exp_mail, ev)
    rev = {}
    for e in s.table:
        rev[address_of(e[1], e[2], bs.player)] = (e[1], e[2])
    rev[address_of(s.kind, s.handle, bs.player)] = (s.kind, s.handle)
    rev[p.sym['FM']] = (FX.FM, NO)
    rev[bs.player] = (FX.PLAYER, PLAYER_HANDLE)
    rev[0] = (FX.NONE, NO)
    after = res['after']
    exp_table = []
    for k in range(NUM_UP):
        kind, h = rev.get(after.origin[k], (None, None))
        if kind is None:
            raise FxError('%s: an unknown origin $%06X' % (s.name,
                                                           after.origin[k]))
        if kind in (FX.NONE, FX.FM):
            h = NO
        exp_table.append((after.sfx[k] & 0xFF, kind,
                          bool(after.pickup[k]), h))
    if x4:
        c = st[-1][1]
        e = exp_table[c]
        exp_table[c] = (st[-1][2] & 0xFF, e[1], e[2], e[3])
    trace = []
    kind = FX.FM if s.op == 'start2' else s.kind
    if kind in (FX.MOBJ, FX.FM) and s.lis is not None:
        g = res['getch']
        trace.append((None, g is not None, g[0] if g else 0,
                      g[1] if g else 0))
    pos = {}
    if s.op == 'start' and s.kind == FX.MOBJ:
        pos[s.handle] = (s.xy[0], s.xy[1], 0)
    handle = s.handle if s.kind in (FX.MOBJ, FX.PLAYER) else NO
    if s.kind == FX.PLAYER:
        handle = PLAYER_HANDLE
    return Native(None, s.op, s.sfx & 0xFFFF,
                  FX.FM if s.op == 'start2' else s.kind, handle,
                  s.xy[0], s.xy[1], chans, mail, s.fm, s.sndvol,
                  s.gamemap, s.lis, pos, [False] * NUM_UP, exp_table,
                  [m.tuple() for m in exp_mail], trace,
                  s.xy if s.op == 'start2' else None, x4, labels)


def syn_cases(seed: int = SEED) -> List[Syn]:
    """The directed cases of comparison 3, then random ones."""
    prio = FX.priority_table()
    by = {}
    for sfx, pr in enumerate(prio):
        if sfx:
            by.setdefault(pr, []).append(sfx)
    pistol, bgact, plpain = 1, 46, 19       # priorities 64, 120, 96
    assert prio[pistol] == 64 and prio[bgact] == 120 and prio[plpain] == 96
    rng = random.Random(seed)
    U = 1 << 16
    lis0 = (0x00100000, 0x00200000, 0)
    out: List[Syn] = []

    def full(sfxs, kinds=None):
        t = []
        for k, sfx in enumerate(sfxs):
            kind = kinds[k] if kinds else FX.MOBJ
            t.append((sfx, kind, 0x210 + k if kind == FX.MOBJ else NO,
                      False))
        return t

    def syn(name, table, op='start', sfx=pistol, kind=FX.MOBJ, handle=0x200,
            xy=None, fm=(0x00300000, 0x00400000), lis=lis0, sndvol=15,
            gamemap=1, fail=False):
        if xy is None:
            xy = ((lis0[0] + 300 * U) & M32, (lis0[1] + 40 * U) & M32)
        out.append(Syn(name, op, sfx, kind, handle, xy, table, fm, lis,
                       sndvol, gamemap, fail))
    empty = [(0, FX.NONE, NO, False)] * NUM_UP
    # the priorities, the table full (getChannel's eviction)
    syn('none: every priority higher', full([pistol] * 8), sfx=bgact)
    syn('evict equal', full([pistol] * 3 + [bgact] + [pistol] * 4),
        sfx=bgact)
    syn('evict lower (a higher number)',
        full([pistol] * 5 + [bgact] + [pistol] * 2), sfx=plpain)
    syn('evict: the first not lower', full([pistol, pistol, bgact, pistol,
                                            plpain, pistol, pistol, pistol]),
        sfx=plpain)
    syn('evict: equal before lower', full([pistol, plpain, bgact] +
                                          [pistol] * 5), sfx=plpain)
    # the same origin
    t = list(empty)
    t[3] = (bgact, FX.MOBJ, 0x200, False)
    syn('kill: same origin, same kind', t)
    t = list(empty)
    t[3] = (bgact, FX.MOBJ, 0x200, True)
    syn('no kill: same origin, the pickup flag', t)
    syn('kill: the pickup flag on both', [e if k != 3 else
                                          (bgact, FX.MOBJ, 0x200, True)
                                          for k, e in enumerate(empty)],
        sfx=pistol | 0x8000)
    t = full([pistol] * 8)
    t[2] = (pistol, FX.MOBJ, 0x200, False)
    t[6] = (pistol, FX.MOBJ, 0x200, False)
    syn('kill, then getChannel\'s same origin', t, sfx=bgact)
    t = full([bgact] * 8)
    t[4] = (bgact, FX.MOBJ, 0x200, True)
    syn('full: same origin, other kind: evicted by priority', t,
        sfx=bgact)
    # no origin, the player
    t = list(empty)
    t[1] = (plpain, FX.NONE, NO, False)
    syn('no origin kills no origin', t, kind=FX.NONE, handle=NO)
    t = list(empty)
    t[1] = (plpain, FX.NONE, NO, True)
    syn('no origin, other kind', t, kind=FX.NONE, handle=NO)
    t = list(empty)
    t[5] = (plpain, FX.PLAYER, NO, False)
    syn('the player\'s origin kills the player\'s', t, kind=FX.PLAYER,
        handle=PLAYER_HANDLE)
    syn('no origin, full: getChannel skips the same origin',
        [(pistol, FX.NONE, NO, False)] * 8, kind=FX.NONE, handle=NO,
        sfx=bgact)
    # the pickup kinds
    syn('pickup: oof', list(empty), sfx=25, kind=FX.PLAYER,
        handle=PLAYER_HANDLE)
    syn('pickup: noway', list(empty), sfx=48, kind=FX.PLAYER,
        handle=PLAYER_HANDLE)
    syn('pickup: PICKUP_SOUND', list(empty), sfx=33 | 0x8000)
    # a failed start (no samples)
    syn('a failed start', list(empty), fail=True)
    syn('a failed start, full: evicted, then stopped',
        full([pistol] * 3 + [bgact] + [pistol] * 4), sfx=bgact, fail=True)
    # S_StartSound2
    t = list(empty)
    t[2] = (bgact, FX.FM, NO, False)
    syn('S_StartSound2 kills FM\'s', t, op='start2', sfx=21,
        kind=FX.FM, handle=NO)
    syn('S_StartSound2 into an empty table', list(empty), op='start2',
        sfx=16, kind=FX.FM, handle=NO)
    # S_AdjustSoundParams' edges
    for name, dxy, la in (('straight ahead, east, the view 0', (500, 0), 0),
                          ('straight ahead, north, the view 90',
                           (0, 500), 0x40000000),
                          ('straight behind, west', (-500, 0), 0),
                          ('south, the view 270', (0, -700), 0xC0000000)):
        syn('separation: ' + name, list(empty),
            xy=((lis0[0] + dxy[0] * U) & M32, (lis0[1] + dxy[1] * U) & M32),
            lis=(lis0[0], lis0[1], la))
    syn('zero distance', list(empty), xy=lis0[:2])
    for d in (159, 160, 161, 1199, 1200, 1201, 1500, 40000):
        for gm in (1, 8):
            for vol in ((15, 1, 0) if gm == 8 and d >= 1199 else (15,)):
                syn('distance %d, map %d, volume %d' % (d, gm, vol),
                    list(empty), xy=((lis0[0] + d * U + 0x123) & M32,
                                     lis0[1]),
                    gamemap=gm, sndvol=vol)
    syn('no listener', list(empty), lis=None)
    syn('distance with the min halved odd', list(empty),
        xy=((lis0[0] + 333 * U + 1) & M32, (lis0[1] - 777 * U - 3) & M32))
    # random states
    for k in range(80):
        table = []
        for c in range(NUM_UP):
            busy = rng.random() < 0.85
            kind = rng.choice((FX.NONE, FX.MOBJ, FX.MOBJ, FX.PLAYER, FX.FM))
            h = rng.choice((0x200, 0x201, 0x202)) if kind == FX.MOBJ else NO
            table.append((rng.randrange(1, 53) if busy else 0, kind, h,
                          rng.random() < 0.3))
        op = 'start2' if rng.random() < 0.15 else 'start'
        kind = FX.FM if op == 'start2' else rng.choice(
            (FX.NONE, FX.MOBJ, FX.MOBJ, FX.PLAYER))
        h = rng.choice((0x200, 0x201, 0x202)) if kind == FX.MOBJ else NO
        dist = rng.choice((0, 50, 200, 700, 1100, 1300, 5000))
        ang = rng.random() * 6.2832
        import math
        xy = ((lis0[0] + int(dist * math.cos(ang) * U)) & M32,
              (lis0[1] + int(dist * math.sin(ang) * U)) & M32)
        sfx = rng.randrange(1, 53) | (0x8000 if rng.random() < 0.1 else 0)
        syn('random %d' % k, table, op=op, sfx=sfx, kind=kind, handle=h,
            xy=xy, lis=(lis0[0], lis0[1], rng.randrange(0, 1 << 32)),
            gamemap=rng.choice((1, 8)), sndvol=rng.randrange(0, 16))
    return out


EVICT = CAP / 'evict.json'


def evict_natives(jobs: int = JOBS) -> List[Tuple[Syn, Native]]:
    """The synthetic cases with the reference's results: ref816 --call
    each (kept in cap/evict.json, keyed by the cases and the base image,
    so a planted bug's run does not redo them)."""
    if not BASE.exists():
        capture_base()
    cases = syn_cases()
    key = hashlib.sha256(json.dumps([list(map(str, s)) for s in cases])
                         .encode() + hashlib.sha256(BASE.read_bytes())
                         .digest()).hexdigest()
    results = None
    if EVICT.exists():
        saved = json.loads(EVICT.read_text())
        if saved.get('key') == key:
            results = [{'events': [tuple(e) for e in r['events']],
                        'getch': tuple(r['getch']) if r['getch'] else None,
                        'after': Table(*[tuple(x) if k == 3 else x
                                         for k, x in enumerate(r['after'])])}
                       for r in saved['results']]
    if results is None:
        temp = Path(tempfile.mkdtemp(prefix='tmp-evict-', dir=str(PART)))
        try:
            def one(k):
                return run_syn(cases[k], temp / ('s%03d' % k))
            with ThreadPoolExecutor(max_workers=jobs) as ex:
                results = list(ex.map(one, range(len(cases))))
        finally:
            shutil.rmtree(str(temp), ignore_errors=True)
        C.write_atomic(EVICT, json.dumps({
            'key': key, 'results': [{'events': r['events'],
                                     'getch': r['getch'],
                                     'after': list(r['after'])}
                                    for r in results]}).encode())
    return [(s, native_syn(s, r)) for s, r in zip(cases, results)]


# ---------------------------------------------------------------------------
# A batch of single calls: native against the reference and the model
# ---------------------------------------------------------------------------

class Verdict(NamedTuple):
    n: Native
    ref: List[str]              # problems against the reference
    model: List[str]            # problems against the model
    model_ref: List[str]        # the model's own against the reference
    paths: Set[str]


def run_natives(b: R.Build, natives: Sequence[Native], nosep: bool = False,
                jobs: int = JOBS, profile: Optional[str] = None,
                with_ref: bool = True) -> Tuple[List[Verdict], List[float]]:
    check_consts()
    cases = [case_of(b, n) for n in natives]
    records, cost = R.run(b, cases, profile=profile, jobs=jobs)
    out = []
    for n, rec in zip(natives, records):
        o = R.decode(b, rec)
        m = model_of(n, nosep=nosep)
        tr = model_call(m, n)
        ref = compare_ref(n, o, len(n.chans), nosep) if with_ref else []
        mod = compare_model(n, o, m, tr, len(n.chans))
        mref = []
        if with_ref:
            mref = model_against_ref(n, m, tr, nosep)
        paths = set(m.paths) | n.labels
        out.append(Verdict(n, ref, mod, mref, paths))
    return out, cost


def model_against_ref(n: Native, m: FX.Model, tr: List[Tuple],
                      nosep: bool) -> List[str]:
    """The model against the reference (so that the model is the
    reference's in the configuration the comparison has)."""
    nchan = len(n.chans)
    got = [(c.sfx, c.kind, c.pickup, c.handle) for c in m.chans]
    probs = []
    for k in range(nchan):
        e, g = n.exp_table[k], got[k]
        if e[0] != g[0] or (e[0] and e[1:] != g[1:]):
            probs.append('model channel %d: %s, the reference %s' % (k, g, e))
    for k in range(nchan):
        if m.mail[k].tuple() != tuple(n.exp_mail[k]):
            probs.append('model mailbox %d: %s, the reference %s' % (
                k, m.mail[k].tuple(), n.exp_mail[k]))
    if len(tr) != len(n.exp_trace):
        probs.append('model: %d adjusts, the reference %d' % (
            len(tr), len(n.exp_trace)))
    else:
        for (gc, ga, gv, gs), (ec, ea, ev, es) in zip(tr, n.exp_trace):
            if bool(ga) != bool(ea) or (ec is not None and gc != ec) or \
                    (ea and (gv != ev or (not nosep and gs != es))):
                probs.append('model adjust %s: %s %d %d, the reference '
                             '%s %d %d' % (gc, ga, gv, gs, ea, ev, es))
    return probs


# ---------------------------------------------------------------------------
# Chains: a state carried from call to call (and from image to image)
# ---------------------------------------------------------------------------

def state_case(b: R.Build, n: Native, state: bytes) -> R.Case:
    """n's case with the carried state (the table, the mailboxes, FM to
    LS_ANGLE as an out record has them; SND_SFXVOL n's) in place of n's
    own."""
    c = case_of(b, n)
    nch = b.channels * (S.CHAN_SIZE + S.MAIL_SIZE)
    s2t = b.s2t_base + S.S2T['FM_X']
    pokes = [(b.sc_base, state[:nch]), (s2t, state[nch:nch + R.S2T_RUN]),
             (R.extra_base(b) + S.SC_EXTRA['SND_SFXVOL'],
              bytes([n.sndvol]))]
    return R.Case(c.op, pokes + c.pokes[3:])


def out_state(o: R.Out) -> bytes:
    return o.table + o.mail + o.s2t


def menu_chain(paused: int = 6, jobs: int = 1) -> Dict[str, Any]:
    """The MENUW linkage (SCREENS.md 7.3): the menu run's last S_UpdateSounds
    before the menu opened on the tic image's build (fxc8: the positions
    from s2t_pos, kept in the channel table and LS_*), then each call up
    to the paused frames' S_UpdateSounds on MENUW's (fxcm8: -D
    FXC_NOSEP, fx_pcache's positions), the state carried, every call
    compared with the reference (the stops, the volumes)."""
    body = load_capture('menu')
    refs = refs_of(body)
    first = next(i for i, r in enumerate(refs) if r.op == 'update' and
                 r.world['menu'] and r.world['sndvol'] == MENU_VOLUME)
    pre = max(i for i in range(first) if refs[i].op == 'update' and
              not refs[i].world['menu'])
    chain = refs[pre:first + paused]
    ids: Dict[int, int] = {}
    b8, bm = R.load('fxc8'), R.load('fxcm8')
    out = {'calls': [], 'problems': [], 'volumes': 0, 'stops': 0,
           'paused': 0}
    state: Optional[bytes] = None
    for k, ref in enumerate(chain):
        n = native_of(ref, ids=ids)
        b = b8 if k == 0 else bm
        if state is None:
            case = case_of(b, n)
            mail0 = [m.copy() for m in n.mail]
        else:
            case = state_case(b, n, state)
            nch = b.channels * S.CHAN_SIZE
            mail0 = [FX.Mail(*state[nch + 4 * c:nch + 4 * c + 4])
                     for c in range(b.channels)]
        recs, _ = R.run(b, [case], jobs=1)
        o = R.decode(b, recs[0])
        exp = [m.copy() for m in mail0]
        for ev in ref.events:
            if ev[0] in ('stop', 'start', 'vol'):
                apply_mail(exp, ev)
                if ev[0] == 'vol' and ref.world['menu']:
                    out['volumes'] += 1
                if ev[0] == 'stop' and ref.world['menu']:
                    out['stops'] += 1
        n2 = n._replace(exp_mail=[m.tuple() for m in exp])
        probs = compare_ref(n2, o, b.channels, nosep=(k > 0))
        if ref.op == 'update' and ref.world['menu']:
            out['paused'] += 1
        out['calls'].append({'op': ref.op, 'menu': ref.world['menu'],
                             'sndvol': ref.world['sndvol'],
                             'image': b.name, 'problems': probs})
        out['problems'] += ['%s %d (%s): %s' % (ref.op, k, b.name, x)
                            for x in probs]
        state = out_state(o)
    if not out['volumes']:
        out['problems'].append('no paused volume was compared')
    return out


# ---------------------------------------------------------------------------
# Comparison 4: a start in a frame's tic, then that frame's sc_update
# ---------------------------------------------------------------------------

def two_tic(build: str = 'fxc8r') -> Dict[str, Any]:
    """A start (each origin kind) into an idle machine (no voice active,
    the mailboxes empty), then the frame's sc_update with fxplay's
    fx_isplaying: the channel still plays and its mailbox still holds the
    start; a start then a stop in one frame: free, the stop set, the
    start cleared; an update after the voice became active (fx_service's
    work, injected, the mailbox emptied): it plays; then a stop."""
    b = R.load(build)
    nch = b.channels
    probs: List[str] = []
    U = 1 << 16
    lis = (0, 0, 0)
    cases: List[R.Case] = []
    checks: List[Tuple[str, Any]] = []
    empty = [FX.Chan() for _ in range(nch)]
    mail0 = [FX.Mail() for _ in range(nch)]
    idle = bytes(S.VOICES * S.VOICE_SIZE)
    for kind, h, sfx in ((FX.MOBJ, 0x200, 46), (FX.NONE, NO, 1),
                         (FX.FM, NO, 16), (FX.PLAYER, PLAYER_HANDLE, 19)):
        pos = {0x200: (300 * U, 50 * U, 0)}
        st = Native(None, 'start2' if kind == FX.FM else 'start', sfx, kind,
                    h, 300 * U, 50 * U, empty, mail0, (300 * U, 50 * U), 15,
                    1, lis, pos, [False] * nch, None, None, None, None,
                    False, set())
        up = st._replace(op='update')
        cases.append(case_of(b, st, voices=idle))
        cases.append(R.Case('update', case_of(b, up, first=False).pokes,
                            True))
        checks.append(('start %d' % kind, None))
        checks.append(('update %d' % kind, kind))
    # a start, then a stop in the same frame: free, stop set, no start
    st = Native(None, 'start', 46, FX.MOBJ, 0x200, 300 * U, 50 * U, empty,
                mail0, (0, 0), 15, 1, lis, {0x200: (300 * U, 50 * U, 0)},
                [False] * nch, None, None, None, None, False, set())
    cases.append(case_of(b, st, voices=idle))
    checks.append(('start, then a stop', None))
    cases.append(R.Case('stop', case_of(b, st._replace(op='stop'),
                                        first=False).pokes, True))
    checks.append(('the stop of a pending start', 'stop'))
    # the voice active (fx_service took the start), then a stop, update
    v = bytearray(idle)
    v[S.VOICE['V_FLAGS']] = 0x80
    v[S.VOICE['V_CHAN']] = 0
    st = Native(None, 'start', 46, FX.MOBJ, 0x200, 300 * U, 50 * U, empty,
                mail0, (0, 0), 15, 1, lis, {0x200: (300 * U, 50 * U, 0)},
                [False] * nch, None, None, None, None, False, set())
    cases.append(case_of(b, st, voices=bytes(v)))
    checks.append(('start, voice', None))
    cases.append(R.Case('update', [(b.sc_base + nch * S.CHAN_SIZE,
                                    bytes(4))], True))
    checks.append(('update, the voice active, the mailbox emptied', 'voice'))
    stop = st._replace(op='stop')
    cases.append(R.Case('stop', case_of(b, stop, first=False).pokes, True))
    checks.append(('stop', 'stop'))
    recs, _ = R.run(b, cases, jobs=1)
    for (name, what), rec in zip(checks, recs):
        o = R.decode(b, rec)
        sfx0, flags0 = o.table[0], o.mail[0]
        if what is None:
            if not (sfx0 and flags0 & FX.MX_START):
                probs.append('%s: channel 0 %d, mailbox $%02X' % (
                    name, sfx0, flags0))
        elif what == 'voice':
            if not sfx0 or flags0 & FX.MX_START:
                probs.append('%s: channel 0 %d, mailbox $%02X' % (
                    name, sfx0, flags0))
        elif what == 'stop':
            if sfx0 or flags0 & FX.MX_START or not flags0 & FX.MX_STOP:
                probs.append('%s: channel 0 %d, mailbox $%02X' % (
                    name, sfx0, flags0))
        else:
            if not sfx0 or not flags0 & FX.MX_START:
                probs.append('%s: the start\'s channel was freed (%d, '
                             'mailbox $%02X)' % (name, sfx0, flags0))
    return {'build': build, 'cases': len(cases), 'problems': probs}


# ---------------------------------------------------------------------------
# The 3-channel build against the model: random call sequences
# ---------------------------------------------------------------------------

def random_sequences(count: int, seed: int = SEED, nchan: int = 3
                     ) -> List[List[Tuple[Native, bytes]]]:
    """count sequences of 1-6 calls from random states: each (native,
    voices); a sequence's later calls carry the state."""
    import math
    rng = random.Random(seed)
    U = 1 << 16
    out = []
    handles = (0x200, 0x201, 0x202, 0x203)
    for k in range(count):
        chans = []
        for c in range(nchan):
            kind = rng.choice((FX.NONE, FX.MOBJ, FX.MOBJ, FX.PLAYER, FX.FM))
            chans.append(FX.Chan(rng.randrange(1, 53) if rng.random() < 0.8
                                 else 0, kind, rng.random() < 0.25,
                                 rng.choice(handles) if kind == FX.MOBJ
                                 else (PLAYER_HANDLE if kind == FX.PLAYER
                                       else NO),
                                 rng.randrange(1 << 32),
                                 rng.randrange(1 << 32)))
        mail = [FX.Mail(rng.randrange(8), rng.randrange(1, 53),
                        rng.randrange(128), rng.randrange(256))
                for _ in range(nchan)]
        lx, ly = rng.randrange(1 << 32), rng.randrange(1 << 32)
        la = rng.choice((0, 0x40000000, 0x80000000, 0xC0000000,
                         rng.randrange(1 << 16) << 16, rng.randrange(1 << 32)))
        lis = (lx, ly, la) if rng.random() < 0.95 else None

        def near():
            d = rng.choice((0, 1, 100, 159, 160, 161, 600, 1199, 1200, 1201,
                            3000, 40000))
            a = rng.random() * 2 * math.pi
            if rng.random() < 0.15:
                a = rng.choice((0, math.pi / 2, math.pi, 3 * math.pi / 2))
            return ((lx + int(d * math.cos(a) * U) + rng.randrange(-3, 4))
                    & M32, (ly + int(d * math.sin(a) * U)) & M32)
        pos = {h: near() + (0,) for h in handles}
        fm = near()
        voices = bytearray(S.VOICES * S.VOICE_SIZE)
        for v in range(S.VOICES):
            voices[v * S.VOICE_SIZE + S.VOICE['V_FLAGS']] = \
                0x80 if rng.random() < 0.5 else 0
            voices[v * S.VOICE_SIZE + S.VOICE['V_CHAN']] = rng.randrange(
                nchan + 1)
        sndvol = rng.randrange(16)
        gamemap = rng.choice((1, 2, 7, 8, 8))
        seq = []
        for j in range(rng.randrange(1, 7)):
            op = rng.choice(('start', 'start', 'start2', 'stop', 'update',
                             'update'))
            kind = rng.choice((FX.NONE, FX.MOBJ, FX.MOBJ, FX.PLAYER)) \
                if op != 'start2' else FX.FM
            if op == 'stop':
                kind = rng.choice((FX.NONE, FX.MOBJ, FX.MOBJ, FX.PLAYER,
                                   FX.FM))
            h = rng.choice(handles) if kind == FX.MOBJ else (
                PLAYER_HANDLE if kind == FX.PLAYER else NO)
            sfx = rng.choice((rng.randrange(1, 53), 25, 48)) | (
                0x8000 if rng.random() < 0.1 else 0)
            x, y = pos[h][:2] if kind == FX.MOBJ else (
                near() if op == 'start2' else (0, 0))
            seq.append((Native(None, op, sfx, kind, h, x, y, chans, mail,
                               fm, sndvol, gamemap, lis, pos,
                               [False] * nchan, None, None, None, None,
                               False, set()), bytes(voices)))
        out.append(seq)
    return out


def seq_model(seq: List[Tuple[Native, bytes]]) -> List[Tuple[bytes, List]]:
    """The model over a sequence: after each call its state and trace."""
    n0, voices = seq[0]
    m = model_of(n0)
    act = [(voices[v * S.VOICE_SIZE + S.VOICE['V_FLAGS']] & 0x80,
            voices[v * S.VOICE_SIZE + S.VOICE['V_CHAN']])
           for v in range(S.VOICES)]
    m.playing = lambda c: bool(m.mail[c].flags & FX.MX_START) or \
        any(f and ch == c for f, ch in act)
    out = []
    for n, _ in seq:
        m.sndvol, m.gamemap = n.sndvol, n.gamemap
        tr = model_call(m, n)
        out.append((model_state(m), tr))
    return out


def check_random(count: int, build: str = 'fxc3', jobs: int = JOBS,
                 seed: int = SEED) -> Dict[str, Any]:
    b = R.load(build)
    seqs = random_sequences(count, seed, b.channels)
    cases: List[R.Case] = []
    for seq in seqs:
        for j, (n, voices) in enumerate(seq):
            if j == 0:
                cases.append(case_of(b, n, voices=voices))
            else:
                c = case_of(b, n, first=False)
                cases.append(R.Case(n.op, [x for x in c.pokes
                                           if x[0] == FX_GA], True))
    records, _ = R.run(b, cases, jobs=jobs)
    probs: List[str] = []
    calls = 0
    paths: Set[str] = set()
    at = 0
    ops: Dict[str, int] = {}
    for k, seq in enumerate(seqs):
        model = seq_model(seq)
        for j, ((n, _), (state, tr)) in enumerate(zip(seq, model)):
            o = R.decode(b, records[at])
            at += 1
            calls += 1
            ops[n.op] = ops.get(n.op, 0) + 1
            got = out_state(o)
            if got != state:
                i = next(i for i in range(len(got)) if got[i] != state[i])
                probs.append('sequence %d call %d (%s): byte %d native %s '
                             'model %s' % (k, j, n.op, i,
                                           got[max(0, i - 2):i + 6].hex(),
                                           state[max(0, i - 2):i + 6].hex()))
                break
            gt = [(c if n.op == 'update' else None, a, v, s)
                  for c, a, v, s in o.trace]
            mt = [(c, a, v, s) for c, a, v, s in tr]
            if [x if x[1] else x[:2] for x in gt] != \
                    [x if x[1] else x[:2] for x in mt]:
                probs.append('sequence %d call %d (%s): trace %s, model %s'
                             % (k, j, n.op, gt[:3], mt[:3]))
                break
    return {'build': build, 'sequences': count, 'calls': calls, 'ops': ops,
            'problems': probs[:50], 'failed': len(probs)}


# ---------------------------------------------------------------------------
# The captured call streams on 3 channels, against the model
# ---------------------------------------------------------------------------

def replay3(run: str, build: str = 'fxc3', jobs: int = JOBS
            ) -> Dict[str, Any]:
    """Every captured call of a run, in order, on 3 channels: before each
    call the model's state (3 channels; the voices of a host stand-in for
    fx_service at each S_UpdateSounds: a start's voice plays (its sound
    mod 7) + 2 frames, a stop silences it, the mailboxes are then empty),
    the call's arguments, the world (positions: the reference's call's,
    else the last known; isPlaying through fxplay's fx_isplaying); after
    it the native state and trace must equal the model's."""
    b = R.load(build)
    nchan = b.channels
    body = load_capture(run)
    refs = [r for r in refs_of(body)
            if not (r.op == 'update' and r.world['menu'])]
    ids: Dict[int, int] = {}
    m = FX.new_model(nchan)
    voices = [[False, 0, 0] for _ in range(S.VOICES)]   # active, chan, left
    last: Dict[int, Tuple[int, int, int]] = {}
    last_lis: Optional[Tuple[int, int, int]] = None
    cases, expect = [], []
    for ref in refs:
        n8 = native_of(ref, ids=ids)
        if ref.op == 'update':          # the frame's service, then update
            for c in range(nchan):
                f = m.mail[c].flags
                if f & (FX.MX_STOP | FX.MX_START):
                    for v in voices:
                        if v[0] and v[1] == c:
                            v[0] = False
                if f & FX.MX_START:
                    v = voices[c]
                    v[0], v[1], v[2] = True, c, m.mail[c].sound % 7 + 2
                m.mail[c] = FX.Mail()
            for v in voices:
                if v[0]:
                    v[2] -= 1
                    if v[2] <= 0:
                        v[0] = False
        last.update(n8.pos)
        if n8.lis is not None:
            last_lis = n8.lis
        lis = n8.lis if n8.lis is not None else (
            last_lis if ref.world['player'] else None)
        pos = dict(last)
        n = n8._replace(chans=[c.copy() for c in m.chans],
                        mail=[x.copy() for x in m.mail], fm=m.fm,
                        lis=lis, pos=pos, play=[False] * nchan)
        vb = bytearray(S.VOICES * S.VOICE_SIZE)
        for k, v in enumerate(voices):
            vb[k * S.VOICE_SIZE + S.VOICE['V_FLAGS']] = 0x80 if v[0] else 0
            vb[k * S.VOICE_SIZE + S.VOICE['V_CHAN']] = v[1]
        if len(pos) + 1 > R.POS_MAX:        # keep the call's own and the
            keep = {h: pos[h] for h in pos   # channels' handles
                    if h in n8.pos or any(c.handle == h for c in m.chans)
                    or h == n8.handle}
            n = n._replace(pos=keep)
        cases.append(case_of(b, n, voices=bytes(vb)))
        act = [(v[0], v[1]) for v in voices]
        m.playing = (lambda a: lambda c: bool(m.mail[c].flags & FX.MX_START)
                     or any(f and ch == c for f, ch in a))(act)
        mp = dict(n.pos)
        m.pos = (lambda pp, ll: lambda h: ll if h == FX.LISTENER
                 else pp.get(h))(mp, lis)
        m.ls = lis if lis is not None else (0, 0, 0)    # as poked
        m.ls_on = lis is not None
        m.sndvol, m.gamemap = n.sndvol, n.gamemap
        tr = model_call(m, n)
        expect.append((model_state(m), tr, n.op))
    records, _ = R.run(b, cases, jobs=jobs)
    probs = []
    for k, (rec, (state, tr, op)) in enumerate(zip(records, expect)):
        o = R.decode(b, rec)
        got = out_state(o)
        if got != state:
            i = next(i for i in range(len(got)) if got[i] != state[i])
            probs.append('call %d (%s): byte %d native %s model %s' % (
                k, op, i, got[max(0, i - 2):i + 6].hex(),
                state[max(0, i - 2):i + 6].hex()))
            continue
        gt = [(c if op == 'update' else None, a, v, s)
              for c, a, v, s in o.trace]
        if [x if x[1] else x[:2] for x in gt] != \
                [x if x[1] else x[:2] for x in tr]:
            probs.append('call %d (%s): trace %s, model %s' % (
                k, op, gt[:3], tr[:3]))
    return {'run': run, 'build': build, 'calls': len(cases),
            'problems': probs[:20], 'failed': len(probs)}


# ---------------------------------------------------------------------------
# The checkpoint
# ---------------------------------------------------------------------------

REQUIRED = tuple(x for x in FX.PATHS if x != 'gc:same-origin')
UNREACHABLE = {
    'gc:same-origin': 'getChannel\'s same-origin stop [R s_sound65.s:'
    '293-302] follows S_StartSound\'s kill of the first busy channel with '
    'the same origin and kind [R :245-258], whose test is the same for '
    'an origin (none is skipped by both): that channel is then free, and '
    'every channel before it is busy with another origin or kind, so '
    'getChannel takes it as free before it reaches a second one'}


def check_captured(runs: Sequence[str] = RUNS, jobs: int = JOBS
                   ) -> Dict[str, Any]:
    b = R.load('fxc8')
    out: Dict[str, Any] = {'runs': {}, 'problems': [], 'paths': {}}
    paths: Dict[str, int] = {}
    for run in runs:
        refs = [r for r in refs_of(load_capture(run))
                if not (r.op == 'update' and r.world['menu'])]
        vs, _ = run_natives(b, [native_of(r) for r in refs], jobs=jobs)
        ops: Dict[str, int] = {}
        for v in vs:
            ops[v.n.op] = ops.get(v.n.op, 0) + 1
            for x in v.paths:
                paths[x] = paths.get(x, 0) + 1
        bad = [v for v in vs if v.ref or v.model or v.model_ref]
        out['runs'][run] = {'calls': len(vs), 'ops': ops,
                            'x4': sum(v.n.x4 for v in vs), 'bad': len(bad)}
        for v in bad[:10]:
            out['problems'].append('%s %s %d: %s' % (
                run, v.n.op, v.n.ref.hit, (v.ref + v.model + v.model_ref)[0]))
    out['paths'] = paths
    return out


def check_evict(jobs: int = JOBS) -> Dict[str, Any]:
    pairs = evict_natives(jobs)
    b = R.load('fxc8')
    vs, _ = run_natives(b, [n for _, n in pairs], jobs=jobs)
    paths: Dict[str, int] = {}
    probs = []
    for (s, _), v in zip(pairs, vs):
        for x in v.paths:
            paths[x] = paths.get(x, 0) + 1
        for x in (v.ref + v.model + v.model_ref)[:1]:
            probs.append('%s: %s' % (s.name, x))
    return {'cases': len(pairs), 'x4': sum(v.n.x4 for v in vs),
            'paths': paths, 'problems': probs}


def coverage(*path_counts: Dict[str, int]) -> Dict[str, Any]:
    total: Dict[str, int] = {}
    for pc in path_counts:
        for k, v in pc.items():
            total[k] = total.get(k, 0) + v
    missing = [x for x in REQUIRED if not total.get(x)]
    return {'paths': {x: total.get(x, 0) for x in FX.PATHS +
                      FX.ADJUST_PATHS},
            'unreachable': UNREACHABLE, 'missing': missing,
            'problems': ['the path %s has no compared call' % x
                         for x in missing]}


PCACHE_BUDGET = 90              # 60 until wave 4 (FXCHAN-5)


def sizes() -> Dict[str, Any]:
    """The objects' bytes (ld65's map: S2CODE, S2RODATA) against the
    budgets: fx_chan s2layout's (1,100 since wave 4, FXCHAN-5: the tic
    image's object, rel/; MENUW's, -D FXC_NOSEP, in fxcmw), fx_pcache
    PCACHE_BUDGET."""
    def module(map_path: Path, stem: str) -> int:
        ms = S.read_map(map_path.read_text())
        return ms.modules.get(stem, 0)
    out: Dict[str, Any] = {}
    lst = (PART / 'rel' / 'fx_chan.lst').read_text() \
        if (PART / 'rel' / 'fx_chan.lst').exists() else ''
    m8 = PART / 'fxc8.map'
    text = m8.read_text()
    seg = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    out['fx_chan (FXCH8, traced)'] = _module_bytes(seg, 'fx_chan.o')
    mw = PART / 'fxcmw.map'
    seg = mw.read_text().split('Modules list:', 1)[1].split(
        'Segment list:', 1)[0]
    out['fx_chan (MENUW, -D FXC_NOSEP)'] = _module_bytes(seg,
                                                         'fx_chan-ns.o')
    out['fx_pcache'] = _module_bytes(seg, 'fx_pcache.o')
    out['fx_chan (the tic image)'] = _obj_bytes(PART / 'rel' / 'fx_chan.o')
    out['budget'] = {'fx_chan': S.SHARED_BUDGETS['fx_chan'],
                     'fx_pcache': PCACHE_BUDGET}
    out['menuw_sizes'] = (PART / 'fxcmw.sizes').read_text().splitlines()
    del lst
    return out


def _module_bytes(seg: str, name: str) -> int:
    total, on = 0, False
    for line in seg.splitlines():
        if line and not line.startswith(' '):
            on = line.strip().rstrip(':').split('(')[0].endswith(name)
            continue
        f = line.split()
        if on and f and f[0] in ('S2CODE', 'S2RODATA', 'S2DATA'):
            total += int(next(x for x in f if x.startswith('Size='))[5:], 16)
    return total


def _obj_bytes(obj: Path) -> int:
    """S2CODE + S2RODATA of an object, from its listing's segment sizes
    (od65 would do; the listing's last address of each segment)."""
    r = bounded.run(['od65', '--dump-segsize', str(obj)], timeout=30,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    universal_newlines=True)
    total = 0
    for line in r.stdout.splitlines():
        f = line.replace(':', ' ').split()
        if len(f) >= 2 and f[0] in ('S2CODE', 'S2RODATA', 'S2DATA'):
            total += int(f[-1])
    return total


def cost(profiles: Sequence[str] = ('f121', 'fastpath'), count: int = 400,
         jobs: int = JOBS) -> Dict[str, Any]:
    """us a call: the 3-channel build (fxplay's fx_isplaying, a table for
    s2t_pos) on the first calls of random sequences, by operation, and
    FXCH8 on demo3's captured calls by operation; phase 30 around the
    call (the stand-ins' time included)."""
    out: Dict[str, Any] = {}
    b3 = R.load('fxc3')
    seqs = random_sequences(count, SEED + 7, b3.channels)
    by: Dict[str, List[R.Case]] = {}
    for seq in seqs:
        n, v = seq[0]
        by.setdefault(n.op, []).append(case_of(b3, n, voices=v))
    b8 = R.load('fxc8')
    refs = [r for r in refs_of(load_capture('demo3'))]
    by8: Dict[str, List[R.Case]] = {}
    for r in refs:
        by8.setdefault(r.op, []).append(case_of(b8, native_of(r)))
    for prof in profiles:
        for name, b, groups in (('3 channels', b3, by), ('FXCH8 demo3', b8,
                                                         by8)):
            for op, cs in sorted(groups.items()):
                _, us = R.run(b, cs, profile=prof, jobs=jobs)
                runs = R.chunks(b, cs)
                tot = sum(u * len(c) for u, c in zip(us, runs))
                out.setdefault(prof, {}).setdefault(name, {})[op] = {
                    'calls': len(cs), 'us': round(tot / max(1, len(cs)), 2)}
    return out


def check(random_count: int = 10000, jobs: int = JOBS, with_cost: bool = True,
          say=print) -> Dict[str, Any]:
    t0 = time.time()
    rep: Dict[str, Any] = {'format': 'fxchan-report 1'}
    for name in R.BUILDS:
        miss = R.have(name)
        if miss:
            raise FxError(miss)
    rep['captured'] = check_captured(jobs=jobs)
    say('captured: %s' % json.dumps(rep['captured']['runs']))
    rep['evict'] = check_evict(jobs)
    say('evict: %d cases, %d problems' % (rep['evict']['cases'],
                                          len(rep['evict']['problems'])))
    rep['coverage'] = coverage(rep['captured']['paths'],
                               rep['evict']['paths'])
    say('coverage: missing %s' % rep['coverage']['missing'])
    rep['two_tic'] = [two_tic('fxc8r'), two_tic('fxc3')]
    rep['menu'] = menu_chain()
    say('menu: %d paused, %d volumes, %d problems' % (
        rep['menu']['paused'], rep['menu']['volumes'],
        len(rep['menu']['problems'])))
    rep['replay3'] = [replay3(r, jobs=jobs) for r in RUNS if r != 'menu']
    say('replay3: %s' % [(x['run'], x['calls'], x['failed'])
                         for x in rep['replay3']])
    rep['random'] = check_random(random_count, jobs=jobs)
    say('random: %d sequences, %d calls, %d failed' % (
        rep['random']['sequences'], rep['random']['calls'],
        rep['random']['failed']))
    rep['sizes'] = sizes()
    if with_cost:
        rep['cost'] = cost(jobs=jobs)
    probs = []
    probs += ['captured: ' + x for x in rep['captured']['problems']]
    probs += ['evict: ' + x for x in rep['evict']['problems']]
    probs += rep['coverage']['problems']
    for x in rep['two_tic']:
        probs += ['two-tic %s: %s' % (x['build'], y) for y in x['problems']]
    probs += ['menu: ' + x for x in rep['menu']['problems']]
    for x in rep['replay3']:
        probs += ['replay3 %s: %s' % (x['run'], y) for y in x['problems']]
    probs += ['random: ' + x for x in rep['random']['problems']]
    rep['problems'] = probs
    rep['ok'] = not probs
    rep['seconds'] = round(time.time() - t0, 1)
    C.write_atomic(PART / 'report.json',
                   json.dumps(rep, indent=1, sort_keys=True).encode())
    return rep


# ---------------------------------------------------------------------------
# The planted bugs (SCREENS.md 7.3), each in a scratch copy built apart
# ---------------------------------------------------------------------------

class Plant(NamedTuple):
    name: str
    file: str                   # fx_chan.s, or fx.s (src/sound, fxplay's)
    old: str
    new: str
    check: str                  # evict, two_tic, random


PLANTED = (
    Plant('the separation\'s "less 1" not taken', 'fx_chan.s',
          '        lda #0\n        rol a\n        eor #1\n        lsr a\n',
          '        sec\n', 'evict'),
    Plant('map 8\'s floor of 15 dropped', 'fx_chan.s',
          '@dist:  jsr map8\n        bne @far\n',
          '@dist:  jsr map8\n        bra @far\n', 'evict'),
    Plant('priority compared with >', 'fx_chan.s',
          '        bcs @evict\n        jsr next\n',
          '        beq @g4\n        bcs @evict\n@g4:    jsr next\n', 'evict'),
    Plant('the pickup flag ignored in sameOrigin\'s kill', 'fx_chan.s',
          '        beq @k2\n        jsr samep\n',
          '        beq @k2\n        jsr same\n', 'evict'),
    Plant('S_StartSound2 with its own origin instead of FM', 'fx_chan.s',
          '        lda #ORG_FM\n        sta A_KIND\n',
          '        lda #ORG_MOBJ\n        sta A_KIND\n', 'evict'),
    Plant('isPlaying without the pending start', 'fx.s',
          '        and #MX_START\n        bne @yes',
          '        and #0\n        bne @yes', 'two_tic'),
    Plant('a stop that leaves the mailbox\'s start set', 'fx_chan.s',
          '        and #<~(MX_START | MX_VOLUME)\n',
          '        and #<~MX_VOLUME\n', 'two_tic'),
)

PLANT_SOURCES = ('fx_chan.s', 'fx_pcache.s', 'fx_cdrv.s')


def run_planted(plant: Plant, jobs: int = JOBS) -> List[str]:
    """Build the scratch copy with the bug and run its check: the
    problems it reports (none means the bug was not caught)."""
    temp = Path(tempfile.mkdtemp(prefix='tmp-plant-', dir=str(PART)))
    keep = R.PART
    try:
        src = temp / 'src'
        src.mkdir()
        for f in PLANT_SOURCES:
            shutil.copy2(str(R.SOURCE / f), str(src / f))
        shutil.copy2(str(ROOT / 'src' / 'sound' / 'fx.s'), str(src / 'fx.s'))
        path = src / plant.file
        text = path.read_text()
        if text.count(plant.old) != 1:
            raise FxError('%s: the text to change is found %d times' % (
                plant.name, text.count(plant.old)))
        path.write_text(text.replace(plant.old, plant.new))
        part = temp / 'fxchan'
        R.make(part=part, source=src, fxsrc=src)
        R.use_part(part)
        if plant.check == 'evict':
            return check_evict(jobs)['problems']
        if plant.check == 'two_tic':
            return two_tic('fxc8r')['problems'] + two_tic('fxc3')['problems']
        return check_random(200, jobs=jobs)['problems']
    finally:
        R.use_part(keep)
        shutil.rmtree(str(temp), ignore_errors=True)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def capture_all(runs: Sequence[str], jobs: int = JOBS, say=print
                ) -> List[Dict]:
    out = []
    first = [r for r in runs if r == 'demo3']
    rest = [r for r in runs if r not in ('demo3', 'menu')]
    last = [r for r in runs if r == 'menu']
    for r in first:
        out.append(capture(r))
        say(json.dumps(out[-1]))
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        for res in ex.map(capture, rest):
            out.append(res)
            say(json.dumps(res))
    for r in last:
        out.append(capture(r))
        say(json.dumps(out[-1]))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--capture', action='store_true')
    ap.add_argument('--evict', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--cost', action='store_true')
    ap.add_argument('--no-cost', action='store_true')
    ap.add_argument('--planted', action='store_true')
    ap.add_argument('--random', type=int, default=10000)
    ap.add_argument('--runs', default=','.join(RUNS))
    ap.add_argument('--jobs', type=int, default=JOBS)
    args = ap.parse_args(argv)
    if args.capture:
        print(C.df_report())
        capture_all(args.runs.split(','), args.jobs)
        if not BASE.exists() or 'demo3' in args.runs.split(','):
            print(json.dumps(capture_base()))
        return 0
    if args.evict:
        r = check_evict(args.jobs)
        print(json.dumps(r, indent=1))
        return 0 if not r['problems'] else 1
    if args.cost:
        print(json.dumps(cost(jobs=args.jobs), indent=1))
        return 0
    if args.planted:
        bad = 0
        for plant in PLANTED:
            probs = run_planted(plant, args.jobs)
            print('%-50s %s' % (plant.name, ('caught: ' + probs[0])
                                 if probs else 'NOT CAUGHT'))
            bad += not probs
        return 1 if bad else 0
    if args.check:
        rep = check(args.random, args.jobs, not args.no_cost)
        print('ok' if rep['ok'] else '\n'.join(rep['problems'][:40]))
        return 0 if rep['ok'] else 1
    ap.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())
