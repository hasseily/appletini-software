#!/usr/bin/env python3
"""The host model of the channel logic (src/native/fx_chan.s; milestone
11, part fxchan; sound track S4): upstream's S_StartSound,
S_StartSound2, sameOrigin, getChannel, priority, stopChannel,
S_StopSound, S_UpdateSounds and S_AdjustSoundParams [R
build/upstream/src/iigs/s_sound65.s:177-670], with NUM_CHANNELS a
parameter and the DOC replaced by one mailbox a channel (docs/SCREENS.md
3; tools/sound/README.md "The game side").

Usage:  python3 tools/sound/fxchan.py --inc OUT [--build fxch8|test|...]
            the generated include of fx_chan.s (the priority table, the
            constants it reads from upstream's files, the channel
            record, the places that are stand-ins until the integrator
            applies docs/m11-parts/fxchan.md's requests)
        python3 tools/sound/fxchan.py --table
            the priority table as read

Nothing of upstream's code is copied: the priority table is read from
upstream's sfxPriority lines [R s_sound65.s:1274-1285] and the constants
from its offsets.inc through tools/bridge/incfile.py, at run time. The
arithmetic of S_AdjustSoundParams is written here from the routine's
behaviour [R :431-670]; R_PointToAngle3 and finesineapprox are the
milestone 6 host models (tools/native/mathdefs.py), the divide is
C semantics (mathdefs.m_sdiv), never the vendor runtime.

The model's state is the native one (docs/SCREENS.md 4.4): each channel's
sound (0 free), origin (kind, handle), pickup flag and the origin's last
x, y; each mailbox's flags (STOP 1, START 2, VOLUME 4), sound, volume,
separation; the fake mobj FM's x, y; the listener's last x, y, angle and
whether there is one; snd_SfxVolume, gamemap. Two callbacks are the
world: pos(handle) -> (x, y, angle) or None (s2t_pos; the listener is
the handle LISTENER) and playing(c) -> bool (fx_isplaying). The model
also names the paths it takes (paths), the coverage labels of the
checkpoint (PATHS).
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, \
    Set, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'tools'))

from bridge import incfile  # noqa: E402
from native import mathdefs as MD  # noqa: E402

UPSTREAM = ROOT / 'build' / 'upstream' / 'src' / 'iigs'
SOUND_SRC = UPSTREAM / 's_sound65.s'
OFFSETS = UPSTREAM / 'offsets.inc'
MATH_TABLES = ROOT / 'build' / 'native' / 'math' / 'tables'

M32 = 0xFFFFFFFF
M16 = 0xFFFF
NORM_SEP = 128
STEREO_SWING = 96
CLIP_HI = 1200                  # S_CLIPPING_DIST >> FRACBITS
CLOSE_HI = 160                  # S_CLOSE_DIST >> FRACBITS
ATTENUATOR = CLIP_HI - CLOSE_HI
PICKUP_SOUND = 0x8000
LISTENER = 0xFFFE               # s2t_pos's handle of the listener
NO_HANDLE = 0xFFFF
# the origin kinds (s2layout.ORIGIN)
NONE, MOBJ, PLAYER, FM = 0, 1, 2, 3
# the mailbox flags (s2layout.MX_*)
MX_STOP, MX_START, MX_VOLUME = 0x01, 0x02, 0x04

# The channel record (CH_*, CHF_PICKUP, CHF_KIND: request FXCHAN-1) and
# LS_ON, SND_SFXVOL (request FXCHAN-2, after the mailboxes) are
# s2layout.py's since wave 4's integration, in the build's s2.inc.

# the coverage labels of S_StartSound and getChannel (the checkpoint fails
# when one has no compared call), and of S_AdjustSoundParams (reported)
PATHS = ('ss:pickup-bit', 'ss:pickup-oof-noway', 'ss:no-pickup',
         'ss:no-origin', 'ss:player', 'ss:fm', 'ss:origin-inaudible',
         'ss:origin-audible', 'ss:kill', 'ss:no-kill',
         'gc:free', 'gc:same-origin', 'gc:evict-equal', 'gc:evict-lower',
         'gc:none', 'ss:started', 'ss:start-failed')
ADJUST_PATHS = ('ap:no-listener', 'ap:zero', 'ap:clip', 'ap:map8-far',
                'ap:less1', 'ap:not-less1', 'ap:full', 'ap:dist',
                'ap:map8', 'ap:map8-clamp', 'ap:silent')


class ModelError(Exception):
    pass


# ---------------------------------------------------------------------------
# What is read from upstream's files
# ---------------------------------------------------------------------------

def priority_table(path: Path = SOUND_SRC) -> List[int]:
    """sfxPriority's bytes, in sfxenum_t order [R s_sound65.s:1274-1285]:
    the lines from the label to the next blank line."""
    lines = path.read_text().splitlines()
    out: List[int] = []
    on = False
    for line in lines:
        code = line.split(';', 1)[0]
        if code.startswith('sfxPriority:'):
            on = True
            code = code[len('sfxPriority:'):]
        elif on and not code.strip():
            break
        if not on:
            continue
        m = re.match(r'\s*\.byte\s+(.*)$', code)
        if not m:
            raise ModelError('sfxPriority: cannot read %r' % line)
        out += [int(v, 0) for v in m.group(1).split(',')]
    if not out:
        raise ModelError('no sfxPriority in %s' % path)
    return out


def constants() -> Dict[str, int]:
    c = incfile.as_dict(incfile.parse(OFFSETS))
    return {k: c[k] for k in ('CONST_SFX_OOF', 'CONST_SFX_NOWAY',
                              'CONST_NUMSFX', 'OFS_MO_X', 'OFS_MO_Y',
                              'OFS_MO_ANGLE', 'OFS_PL_MO')}


class Tables(NamedTuple):
    tanto: List[int]
    quarter: List[int]


def tables(path: Path = MATH_TABLES) -> Tables:
    planes = [(path / ('tanto%d.bin' % k)).read_bytes() for k in range(4)]
    n = min(len(p) for p in planes)
    tanto = [planes[0][i] | planes[1][i] << 8 | planes[2][i] << 16 |
             planes[3][i] << 24 for i in range(n)]
    lo = (path / 'quartlo.bin').read_bytes()
    hi = (path / 'quarthi.bin').read_bytes()
    quarter = [lo[i] | hi[i] << 8 for i in range(min(len(lo), len(hi)))]
    if n < 2049 or len(quarter) < 2048:
        raise ModelError('the math tables in %s are short' % path)
    return Tables(tanto, quarter)


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

def s16(v: int) -> int:
    return MD.s16(v)


def s32(v: int) -> int:
    return MD.s32(v)


class Chan:
    __slots__ = ('sfx', 'kind', 'pickup', 'handle', 'x', 'y')

    def __init__(self, sfx=0, kind=NONE, pickup=False, handle=NO_HANDLE,
                 x=0, y=0):
        self.sfx, self.kind, self.pickup, self.handle = sfx, kind, pickup, \
            handle
        self.x, self.y = x, y

    def key(self) -> Tuple[int, int]:
        return self.kind, self.handle

    def copy(self) -> 'Chan':
        return Chan(self.sfx, self.kind, self.pickup, self.handle, self.x,
                    self.y)


class Mail:
    __slots__ = ('flags', 'sound', 'vol', 'sep')

    def __init__(self, flags=0, sound=0, vol=0, sep=0):
        self.flags, self.sound, self.vol, self.sep = flags, sound, vol, sep

    def copy(self) -> 'Mail':
        return Mail(self.flags, self.sound, self.vol, self.sep)

    def tuple(self) -> Tuple[int, int, int, int]:
        return self.flags, self.sound, self.vol, self.sep


Pos = Optional[Tuple[int, int, int]]


class Model:
    """The channel logic with n channels."""

    def __init__(self, n: int, prio: Sequence[int], tabs: Tables,
                 consts: Dict[str, int], nosep: bool = False):
        self.n = n
        self.prio = list(prio)
        self.tabs = tabs
        self.oof = consts['CONST_SFX_OOF']
        self.noway = consts['CONST_SFX_NOWAY']
        self.numsfx = consts['CONST_NUMSFX']
        self.nosep = nosep          # MENUW's build: no separation in update
        self.chans = [Chan() for _ in range(n)]
        self.mail = [Mail() for _ in range(n)]
        self.fm = (0, 0)
        self.ls = (0, 0, 0)
        self.ls_on = False
        self.sndvol = 15
        self.gamemap = 1
        self.pos: Callable[[int], Pos] = lambda h: None
        self.playing: Callable[[int], bool] = lambda c: False
        self.paths: Set[str] = set()
        self.calls: List[Tuple[str, int]] = []      # ('stop'|'start'|..., c)
        self.vol = 0                # the last adjust's results (scratch)
        self.sep = 0
        self.aud = 0

    # ---- the mailboxes (fxplay.FxPlayer.mail_*: FXPLAY-4) ----

    def stop_channel(self, c: int) -> None:
        """stopChannel: a channel with a sound stops and is free."""
        ch = self.chans[c]
        if not ch.sfx:
            return
        ch.sfx = 0
        m = self.mail[c]
        m.flags = (m.flags | MX_STOP) & ~(MX_START | MX_VOLUME) & 0xFF
        self.calls.append(('stop', c))

    def mail_start(self, c: int) -> None:
        m = self.mail[c]
        m.flags |= MX_START
        m.sound, m.vol, m.sep = self.chans[c].sfx, self.vol & 0xFF, \
            self.sep & 0xFF
        self.calls.append(('start', c))

    def mail_volume(self, c: int) -> None:
        m = self.mail[c]
        m.flags |= MX_VOLUME
        m.vol = self.vol & 0xFF
        self.calls.append(('volume', c))

    # ---- S_StartSound, S_StartSound2 ----

    def start2(self, sfx: int, x: int, y: int) -> bool:
        self.fm = (x & M32, y & M32)
        self.paths.add('ss:fm')
        return self.start(sfx, FM, NO_HANDLE, x, y)

    def start(self, sfx: int, kind: int, handle: int, x: int, y: int
              ) -> bool:
        """S_StartSound; True when a mailbox start was made."""
        sfx &= M16
        if kind in (NONE, FM):
            handle = NO_HANDLE
        if sfx & PICKUP_SOUND:
            pickup = True
            self.paths.add('ss:pickup-bit')
        elif sfx in (self.oof, self.noway):
            pickup = True
            self.paths.add('ss:pickup-oof-noway')
        else:
            pickup = False
            self.paths.add('ss:no-pickup')
        sfx &= ~PICKUP_SOUND & M16
        if sfx == 0 or sfx >= self.numsfx:
            raise ModelError('a bad sound %d (upstream: I_Error)' % sfx)
        self.sep = NORM_SEP
        if kind == NONE or kind == PLAYER:
            self.paths.add('ss:no-origin' if kind == NONE else 'ss:player')
            self.vol = (self.sndvol * 8) & M16
        else:
            lis = self.listener()
            if lis is None:             # no listener: not audible, and
                self.paths.add('ap:no-listener')    # nothing computed
                self.paths.add('ss:origin-inaudible')
                return False
            if not self.adjust(x & M32, y & M32, lis):
                self.paths.add('ss:origin-inaudible')
                return False
            self.paths.add('ss:origin-audible')
        key = (kind, handle)
        for c, ch in enumerate(self.chans):         # kill the old sound
            if ch.sfx and ch.key() == key and ch.pickup == pickup:
                self.stop_channel(c)
                self.paths.add('ss:kill')
                break
        else:
            self.paths.add('ss:no-kill')
        c = self.get_channel(sfx, kind, handle, pickup, x, y)
        if c is None:
            return False
        self.mail_start(c)
        self.paths.add('ss:started')
        return True

    def get_channel(self, sfx, kind, handle, pickup, x, y) -> Optional[int]:
        key = (kind, handle)
        take = None
        for c, ch in enumerate(self.chans):
            if not ch.sfx:
                take = c
                self.paths.add('gc:free')
                break
            if kind != NONE and ch.key() == key and ch.pickup == pickup:
                self.stop_channel(c)
                take = c
                self.paths.add('gc:same-origin')
                break
        if take is None:
            new = self.prio[sfx]
            for c, ch in enumerate(self.chans):
                old = self.prio[ch.sfx]
                if old >= new:
                    self.paths.add('gc:evict-equal' if old == new
                                   else 'gc:evict-lower')
                    self.stop_channel(c)
                    take = c
                    break
            else:
                self.paths.add('gc:none')
                return None
        ch = self.chans[take]
        ch.sfx, ch.kind, ch.pickup, ch.handle = sfx, kind, pickup, handle
        ch.x, ch.y = x & M32, y & M32
        return take

    # ---- S_StopSound ----

    def stop(self, kind: int, handle: int) -> None:
        if kind in (NONE, FM):
            handle = NO_HANDLE
        for c, ch in enumerate(self.chans):
            if ch.sfx and ch.key() == (kind, handle):
                self.stop_channel(c)
                return

    # ---- S_UpdateSounds ----

    def listener(self) -> Pos:
        p = self.pos(LISTENER)
        if p is None:
            self.ls_on = False
            return None
        self.ls = tuple(v & M32 for v in p)
        self.ls_on = True
        return self.ls

    def update(self) -> None:
        lis = self.listener()
        if lis is None:             # musFrame: no player's mobj, no call
            return
        for c, ch in enumerate(self.chans):
            if not ch.sfx:
                continue
            if not self.playing(c):
                self.stop_channel(c)
                continue
            if ch.kind in (NONE, PLAYER):
                continue
            if ch.kind == FM:
                x, y = self.fm
            else:
                p = self.pos(ch.handle)
                if p is None:
                    raise ModelError('no position for the handle $%04X'
                                     % ch.handle)
                x, y = p[0] & M32, p[1] & M32
                ch.x, ch.y = x, y
            self.sep = NORM_SEP
            self.vol = self.sndvol & M16
            if self.adjust(x, y, lis, update=True):
                self.mail_volume(c)
            else:
                self.stop_channel(c)

    # ---- S_AdjustSoundParams ----

    def adjust(self, sx: int, sy: int, lis: Pos, update: bool = False
               ) -> bool:
        """vol, sep from the listener and the source; True if audible."""
        self.aud = 0
        if lis is None:
            self.paths.add('ap:no-listener')
            return False
        lx, ly, la = lis
        adx = _abs32((lx - sx) & M32)
        ady = _abs32((ly - sy) & M32)
        lo = adx if s32(adx) < s32(ady) else ady
        half = (s32(lo) >> 1) & M32
        dist = (adx + ady - half) & M32
        snd8 = (self.sndvol * 8) & M16
        if dist == 0:
            self.paths.add('ap:zero')
            return self._done(snd8)
        if (CLIP_HI << 16) < s32(dist):    # a signed compare (bvc)
            if self.gamemap != 8:
                self.paths.add('ap:clip')
                return False
            self.paths.add('ap:map8-far')
        if not (self.nosep and update):
            ang = MD.m_pta3((sx - lx) & M32, (sy - ly) & M32,
                            self.tabs.tanto) & M32
            if la >= ang:
                ang = (ang - 1) & M32
                self.paths.add('ap:less1')
            else:
                self.paths.add('ap:not-less1')
            index = (((ang - la) & M32) >> 16) >> 3
            sine = MD.m_sineapprox(index, self.tabs.quarter)
            prod = MD.m_mul32(sine, STEREO_SWING) & M32
            self.sep = (NORM_SEP - (prod >> 16)) & M16
        if s16(dist >> 16) < CLOSE_HI:      # a signed compare (bvc)
            self.paths.add('ap:full')
            return self._done(snd8)
        if self.gamemap == 8:
            self.paths.add('ap:map8')
            if (dist >> 16) > CLIP_HI or ((dist >> 16) == CLIP_HI and
                                          dist & M16):
                self.paths.add('ap:map8-clamp')
                dist = CLIP_HI << 16
            units = (((CLIP_HI << 16) - dist) & M32) >> 16
            factor = (snd8 - 15) & M16
            prod = MD.m_mul32(_sx16(factor), units) & M32
            q, _ = MD.m_sdiv(prod, ATTENUATOR, 32)
            return self._done((q + 15) & M16)
        self.paths.add('ap:dist')
        units = (((CLIP_HI << 16) - dist) & M32) >> 16
        prod = MD.m_mul32(_sx16(self.sndvol & M16), units) & M32
        prod = (prod << 3) & M32
        q, _ = MD.m_sdiv(prod, ATTENUATOR, 32)
        return self._done(q & M16)

    def _done(self, vol: int) -> bool:
        self.vol = vol & M16
        if vol == 0 or vol & 0x8000:
            self.paths.add('ap:silent')
            return False
        self.aud = 1
        return True

    # ---- state ----

    def snapshot(self):
        return ([c.copy() for c in self.chans], [m.copy() for m in self.mail],
                self.fm, self.ls, self.ls_on)


def _abs32(v: int) -> int:
    return (-v) & M32 if v & 0x80000000 else v


def _sx16(v: int) -> int:
    """a 16-bit value sign-extended to 32 bits (mulLong)."""
    v &= M16
    return (v | 0xFFFF0000) if v & 0x8000 else v


def new_model(n: int, nosep: bool = False) -> Model:
    return Model(n, priority_table(), tables(), constants(), nosep=nosep)


# ---------------------------------------------------------------------------
# The generated include of fx_chan.s
# ---------------------------------------------------------------------------

def inc_text() -> str:
    sys.path.insert(0, str(ROOT / 'tools'))
    from native import glayout as GL, llayout as LL, \
        s2layout as S  # noqa: E402
    c = constants()
    prio = priority_table()
    out = ['; Generated by tools/sound/fxchan.py --inc (part fxchan of',
           '; milestone 11). Do not edit. Read from upstream\'s files at',
           '; build time: the priority table [R s_sound65.s:1274-1285],',
           '; CONST_* of offsets.inc.', '']

    def eq(name, value, note=''):
        out.append('%-15s = $%04X%s' % (name, value,
                                        ('    ; ' + note) if note else ''))
    eq('FXC_GA', GL.GA_RANGE[0], 'the arguments (GAME.md 4.4, glayout)')
    eq('FXC_GT', GL.GT_RANGE[0], 'the temporaries')
    eq('FXC_GAMEMAP', LL.G['G_GAMEMAP'], 'gamemap (llayout G_GAMEMAP)')
    eq('FXC_LISTENER', LISTENER, 's2t_pos\'s handle of the listener')
    eq('FXC_PICKUPHI', PICKUP_SOUND >> 8, 'PICKUP_SOUND\'s high byte')
    eq('FXC_OOF', c['CONST_SFX_OOF'])
    eq('FXC_NOWAY', c['CONST_SFX_NOWAY'])
    eq('FXC_NUMSFX', c['CONST_NUMSFX'])
    eq('FXC_CLIPHI', CLIP_HI)
    eq('FXC_CLOSEHI', CLOSE_HI)
    eq('FXC_ATTEN', ATTENUATOR)
    eq('FXC_SWING', STEREO_SWING)
    if len(prio) != c['CONST_NUMSFX']:
        raise ModelError('%d priorities for %d sounds' % (
            len(prio), c['CONST_NUMSFX']))
    out += ['', '.macro FXC_PRIORITIES']
    for k in range(0, len(prio), 8):
        out.append('        .byte %s' % ', '.join(
            '%d' % v for v in prio[k:k + 8]))
    out += ['.endmacro', '']
    return '\n'.join(out) + '\n'


def write_if_changed(path: Path, text: str) -> None:
    if path.exists() and path.read_text() == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text)
    tmp.replace(path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--inc', type=Path)
    ap.add_argument('--table', action='store_true')
    args = ap.parse_args(argv)
    if args.table:
        prio = priority_table()
        print(', '.join(str(v) for v in prio))
        return 0
    if args.inc:
        write_if_changed(args.inc, inc_text())
        return 0
    ap.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())
