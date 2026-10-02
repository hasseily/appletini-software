#!/usr/bin/env python3
"""The host model of upstream's status bar and face (milestone 11, part
s2stbar; docs/SCREENS.md 1.5.1, docs/m11-parts/s2stbar.md): ST_Ticker
but M_Random (readyNum, the key boxes, updateFace, painOffset, muchPain,
ouch, turnHead, st_oldhealth), ST_Start (ST_initData, ST_createWidgets),
ST_Drawer (refresh, diffDraw, diffNum, diffIcon, restoreRect, updateIcon,
drawNum, the percent signs, stHide) and I_SaveStatusBackground, written
from upstream's src/iigs/st_stuff65.s and i_viigs65.s (the routines'
behaviour, with their 16-bit arithmetic and their quirks). ref816's runs
of the same routines are the truth it is checked against
(tools/native/s2stbar.py); the native code (src/native/s2_st.s,
s2t_st.s) is compared with ref816, and with this model's draws for the
coverage table.

The state is upstream's: words as upstream keeps them (`Tick`), the
widgets' old values (`Bar.old`, in the znear block's order), the back
buffer's rows (a 200-row buffer, only 168-199 used), STCACHE, the marks
(tools/native/s2draw.Marks). The patches are the 2D store's lumps by
name (`Glyphs`); the nibble tables are a palette's 1 KB (s2palmodel's
build_nibtab of GSSTAT's records, palettes 1-8).
"""

import struct
import sys
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, \
    Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import mathdefs as MD, s2draw as D  # noqa: E402

ST_Y = 168
ST_HEIGHT = 32
ROW = 160
ST_BYTES = ST_HEIGHT * ROW      # 5,120: STCACHE, the band
# st_stuff65.s [R :20-42]
ST_FACESTRIDE = 8
ST_NUMPAINFACES = 5
ST_TURNOFFSET = 3
ST_OUCHOFFSET = 5
ST_EVILGRINOFFSET = 6
ST_RAMPAGEOFFSET = 7
ST_GODFACE = 40
ST_DEADFACE = 41
ST_NUMFACES = 42
TICRATE = 35
ST_EVILGRINCOUNT = 2 * TICRATE
ST_STRAIGHTFACECOUNT = 18
ST_TURNCOUNT = TICRATE
ST_RAMPAGEDELAY = 2 * TICRATE
ST_MUCHPAIN = 20
LARGEAMMO = 1994
# offsets.inc
NUMWEAPONS = 9
NUMCARDS = 3
AM_NOAMMO = 5
CF_GODMODE = 2
PW_INVULNERABILITY = 0
ANG180_HI = 0x8000
ANG45_HI = 0x2000
AMMO_ROWS = (ST_Y + 5, ST_Y + 11, ST_Y + 17, ST_Y + 23)   # ammoRows

M16 = 0xFFFF
M32 = 0xFFFFFFFF


def w16(v: int) -> int:
    return v & M16


def s16(v: int) -> int:
    v &= M16
    return v - 0x10000 if v & 0x8000 else v


def neg(v: int) -> bool:
    return bool(v & 0x8000)


# ---------------------------------------------------------------------------
# The glyphs: ST_Init's lumps [R st_stuff65.s:104-118, :127-194]
# ---------------------------------------------------------------------------

TALL = tuple('STTNUM%d' % i for i in range(10))
SHORT = tuple('STYSNUM%d' % i for i in range(10))
KEYS = tuple('STKEYS%d' % i for i in range(NUMCARDS))
GRAY = tuple('STGNUM%d' % i for i in range(2, 8))
PERCENT = 'STTPRCNT'
ARMSBG = 'STARMS'
BAR = 'STBAR'


def _faces() -> Tuple[str, ...]:
    """nmFaces' order: for each pain level n, STFST n0-n2, STFTR n0, STFTL
    n0, STFOUCH n, STFEVL n, STFKILL n; then STFGOD0, STFDEAD0."""
    out = []
    for n in range(ST_NUMPAINFACES):
        out += ['STFST%d0' % n, 'STFST%d1' % n, 'STFST%d2' % n,
                'STFTR%d0' % n, 'STFTL%d0' % n, 'STFOUCH%d' % n,
                'STFEVL%d' % n, 'STFKILL%d' % n]
    return tuple(out + ['STFGOD0', 'STFDEAD0'])


FACES = _faces()
# every glyph of the bar in one table (the native st_glyph's order)
GLYPHS = TALL + SHORT + GRAY + KEYS + FACES + (PERCENT, ARMSBG, BAR)
G_TALL, G_SHORT, G_GRAY, G_KEYS, G_FACES = 0, 10, 20, 26, 29
G_PERCENT, G_ARMSBG, G_BAR = 71, 72, 73


class Glyphs:
    """The status bar's lumps by name (the 2D store's bytes)."""

    def __init__(self, lumps: Dict[str, bytes]):
        self.lumps = lumps

    def __getitem__(self, name: str) -> bytes:
        return self.lumps[name]

    def width(self, name: str) -> int:
        return struct.unpack_from('<H', self.lumps[name], 0)[0]

    def header(self, name: str) -> Tuple[int, int, int, int]:
        """width, height, left and top offsets (words)."""
        return struct.unpack_from('<HHHH', self.lumps[name], 0)


# ---------------------------------------------------------------------------
# The widgets [R st_stuff65.s:240-385]
# ---------------------------------------------------------------------------

class Num(NamedTuple):
    name: str
    x: int
    y: int
    width: int
    glyphs: Tuple[str, ...]


class Icon(NamedTuple):
    name: str
    x: int
    y: int
    glyphs: Tuple[str, ...]


NUMS = ([Num('ready', 44, ST_Y + 3, 3, TALL),
         Num('health', 90, ST_Y + 3, 3, TALL),
         Num('armor', 221, ST_Y + 3, 3, TALL)] +
        [Num('ammo%d' % i, 288, AMMO_ROWS[i], 3, SHORT) for i in range(4)] +
        [Num('maxammo%d' % i, 314, AMMO_ROWS[i], 3, SHORT)
         for i in range(4)])
ARMS = [Icon('arms%d' % i, 111 + (i % 3) * 12, ST_Y + 4 + (i // 3) * 10,
             (GRAY[i], SHORT[i + 2])) for i in range(6)]
FACE = Icon('face', 143, ST_Y, FACES)
KEYBOX = [Icon('key%d' % i, 239, ST_Y + 3 + 10 * i, KEYS)
          for i in range(NUMCARDS)]
# the znear block's order of the widgets (upstream's W_READY .. W_KEYBOXES)
WIDGETS: List = NUMS + ARMS + [FACE] + KEYBOX
WIDGET = {w.name: w for w in WIDGETS}
OLD_NAMES = tuple(w.name for w in WIDGETS)
PERCENTS = ((90, ST_Y + 3), (221, ST_Y + 3))


# ---------------------------------------------------------------------------
# The ticker's state and inputs (upstream's words)
# ---------------------------------------------------------------------------

class Tick(NamedTuple):
    """ST_Ticker's and ST_Start's state [R st_stuff65.s:75-95]. `ready`
    is W_READY's value pointer, as a source: ('ammo', k) for the player's
    ammo[k] (k 0-5: 4 and 5 read maxammo[0], [1], upstream's layout),
    ('large',) largeammo, ('fps',) the frame rate."""
    faceindex: int
    facecount: int
    priority: int
    oldhealth: int
    lastattackdown: int
    oldhealthPO: int
    lastcalc: int
    randomnumber: int
    keyboxes: Tuple[int, int, int]
    oldweaponsowned: Tuple[int, ...]
    refreshed: int
    running: int
    palette: int
    ready: Tuple


class Player(NamedTuple):
    """The player's fields the status bar reads (upstream's words; mo
    and attacker as their far pointers)."""
    health: int
    armorpoints: int
    ammo: Tuple[int, ...]       # ammo[0-3], then maxammo[0-3]
    readyweapon: int
    weaponowned: Tuple[int, ...]
    cards: Tuple[int, ...]
    powers: Tuple[int, ...]
    cheats: int
    damagecount: int
    bonuscount: int
    attackdown: int
    mo: int
    attacker: int

    @property
    def maxammo(self) -> Tuple[int, ...]:
        return self.ammo[4:8]


class Pos(NamedTuple):
    """turnHead's inputs: the attacker's x, y less the player's mobj's
    (32 bits each), and that mobj's angle."""
    dx: int
    dy: int
    angle: int


class TickTrace(NamedTuple):
    """What one ST_Ticker did (the branches, for the paths' table)."""
    paths: Tuple[str, ...]
    badguyangle: Optional[int]


def ready_source(readyweapon: int, weaponinfo_ammo: Sequence[int],
                 fps_show: int, check: bool = True) -> Tuple:
    """readyNum [R :400-418] (check) or ST_createWidgets' pointer [R
    :245-254] (no NOAMMO check: ammo[5] is maxammo[1])."""
    if check and fps_show:
        return ('fps',)
    a = weaponinfo_ammo[readyweapon]
    if check and a == AM_NOAMMO:
        return ('large',)
    return ('ammo', a)


def _div16(a: int, b: int) -> int:
    """_Div16 as the C's signed division (truncation toward 0)."""
    a, b = s16(a), s16(b)
    q = abs(a) // abs(b)
    return w16(-q if (a < 0) != (b < 0) else q)


class Ticker:
    """ST_Ticker but M_Random, and ST_Start, on upstream's words."""

    def __init__(self, weaponinfo_ammo: Sequence[int],
                 tanto: Sequence[int]):
        self.wammo = tuple(weaponinfo_ammo)
        self.tanto = tanto

    # painOffset [R :420-441]
    def pain_offset(self, st: Dict, p: Player) -> int:
        h = p.health
        if not neg(w16(h - 101)):
            h = 100
        if h != st['oldhealthPO']:
            st['oldhealthPO'] = h
            t = w16(100 - h)
            v = w16(t * 4 + t)
            st['lastcalc'] = w16(_div16(v, 101) << 3)
        return st['lastcalc']

    # muchPain [R :582-590]: N of (20 - st_oldhealth) + health, the add's
    # overflow corrected
    @staticmethod
    def much_pain(st: Dict, p: Player) -> bool:
        t = w16(ST_MUCHPAIN - st['oldhealth'])
        r = w16(t + p.health)
        v = (~(t ^ p.health) & (t ^ r)) & 0x8000
        return bool((r & 0x8000) ^ v)

    def ouch(self, st: Dict, p: Player) -> None:
        st['facecount'] = ST_TURNCOUNT
        st['faceindex'] = w16(self.pain_offset(st, p) + ST_OUCHOFFSET)

    def turn_head(self, st: Dict, p: Player, pos: Pos,
                  paths: List[str]) -> int:
        """turnHead [R :601-677]: the face turns to the attacker."""
        angle = pos.angle & M32
        bad = MD.m_pta3(pos.dx, pos.dy, self.tanto)
        if angle >= bad:                    # (bcs 1$: angle >= badguyangle)
            diff = (angle - bad) & M32
            i = 1 if diff <= 0x80000000 else 0
            paths.append('turn-angle>=bad')
        else:
            diff = (bad - angle) & M32
            i = 1 if diff > 0x80000000 else 0
            paths.append('turn-angle<bad')
        st['facecount'] = ST_TURNCOUNT
        st['faceindex'] = self.pain_offset(st, p)
        if diff >> 16 < ANG45_HI:
            add = ST_RAMPAGEOFFSET
            paths.append('turn-headon')
        elif i:
            add = ST_TURNOFFSET
            paths.append('turn-right')
        else:
            add = ST_TURNOFFSET + 1
            paths.append('turn-left')
        st['faceindex'] = w16(st['faceindex'] + add)
        return bad

    def update_face(self, st: Dict, p: Player, pos: Optional[Pos],
                    paths: List[str]) -> Optional[int]:
        """updateFace [R :443-580]."""
        bad = None
        if neg(w16(st['priority'] - 10)) and p.health == 0:
            st['priority'] = 9
            st['faceindex'] = ST_DEADFACE
            st['facecount'] = 1
            paths.append('dead')
        if neg(w16(st['priority'] - 9)) and p.bonuscount != 0:
            drawn = 0
            old = list(st['oldweaponsowned'])
            for i in range(NUMWEAPONS):
                if p.weaponowned[i] != old[i]:
                    old[i] = p.weaponowned[i]
                    drawn += 1
            st['oldweaponsowned'] = tuple(old)
            if drawn:
                st['priority'] = 8
                st['facecount'] = ST_EVILGRINCOUNT
                st['faceindex'] = w16(self.pain_offset(st, p) +
                                      ST_EVILGRINOFFSET)
                paths.append('grin')
            else:
                paths.append('bonus-no-new-weapon')
        if neg(w16(st['priority'] - 8)) and p.damagecount != 0 and \
                p.attacker != 0 and p.attacker != p.mo:
            st['priority'] = 7
            if self.much_pain(st, p):
                self.ouch(st, p)
                paths.append('attacked-ouch')
            else:
                if pos is None:
                    raise ValueError('turnHead without the positions')
                bad = self.turn_head(st, p, pos, paths)
                paths.append('attacked-turn')
        if neg(w16(st['priority'] - 7)) and p.damagecount != 0:
            if self.much_pain(st, p):
                st['priority'] = 7
                self.ouch(st, p)
                paths.append('damage-ouch')
            else:
                st['priority'] = 6
                st['facecount'] = ST_TURNCOUNT
                st['faceindex'] = w16(self.pain_offset(st, p) +
                                      ST_RAMPAGEOFFSET)
                paths.append('damage-rampage')
        if neg(w16(st['priority'] - 6)):
            if p.attackdown:
                if st['lastattackdown'] == M16:
                    st['lastattackdown'] = ST_RAMPAGEDELAY
                    paths.append('attack-start')
                else:
                    st['lastattackdown'] = w16(st['lastattackdown'] - 1)
                    if st['lastattackdown'] == 0:
                        st['priority'] = 5
                        st['faceindex'] = w16(self.pain_offset(st, p) +
                                              ST_RAMPAGEOFFSET)
                        st['facecount'] = 1
                        st['lastattackdown'] = 1
                        paths.append('rampage')
                    else:
                        paths.append('attack-count')
            else:
                st['lastattackdown'] = M16
        if neg(w16(st['priority'] - 5)) and \
                ((p.cheats & CF_GODMODE) | p.powers[PW_INVULNERABILITY]):
            st['priority'] = 4
            st['faceindex'] = ST_GODFACE
            st['facecount'] = 1
            paths.append('god')
        if st['facecount'] == 0:
            po = self.pain_offset(st, p)
            st['faceindex'] = w16(po + (st['randomnumber'] % 3))
            st['facecount'] = ST_STRAIGHTFACECOUNT
            st['priority'] = 0
            paths.append('straight')
        st['facecount'] = w16(st['facecount'] - 1)
        return bad

    def ticker(self, t: Tick, p: Player, rnd: int, fps_show: int,
               pos: Optional[Pos] = None) -> Tuple[Tick, TickTrace]:
        """ST_Ticker [R :384-418] with M_Random's value `rnd`."""
        st = t._asdict()
        paths: List[str] = []
        st['randomnumber'] = rnd & 0xFF
        st['ready'] = ready_source(p.readyweapon, self.wammo, fps_show)
        st['keyboxes'] = tuple(k if p.cards[k] else M16
                               for k in range(NUMCARDS))
        bad = self.update_face(st, p, pos, paths)
        st['oldhealth'] = w16(p.health)
        return Tick(**st), TickTrace(tuple(paths), bad)

    def start(self, t: Tick, p: Player) -> Tuple[Tick, Optional[int]]:
        """ST_Start [R :216-385]: the new state and I_SetPalette's
        argument (None when ST_Stop does not call it)."""
        st = t._asdict()
        setpal = None
        st['refreshed'] = 0
        if st['running']:
            setpal = 0
            st['running'] = 0
        st['faceindex'] = 0
        st['palette'] = M16
        st['oldhealth'] = M16
        st['oldweaponsowned'] = tuple(p.weaponowned)
        st['keyboxes'] = (M16, M16, M16)
        st['ready'] = ready_source(p.readyweapon, self.wammo, 0, check=False)
        st['running'] = 1
        return Tick(**st), setpal


def start_old() -> Dict[str, int]:
    """ST_createWidgets' old values: 0 for the numbers, -1 for the
    icons."""
    return {w.name: (0 if isinstance(w, Num) else M16) for w in WIDGETS}


# ---------------------------------------------------------------------------
# The drawer
# ---------------------------------------------------------------------------

class Values(NamedTuple):
    """What ST_Drawer reads besides its own state: each number widget's
    value (ready by its pointer), each icon's (arms: weaponowned[i + 1];
    face: st_faceindex; keys: keyboxes), the menu."""
    nums: Dict[str, int]
    icons: Dict[str, int]
    menuactive: int


def values_of(t: Tick, p: Player, menuactive: int, fps_rate: int = 0
              ) -> Values:
    nums = {'health': w16(p.health), 'armor': w16(p.armorpoints)}
    for i in range(4):
        nums['ammo%d' % i] = w16(p.ammo[i])
        nums['maxammo%d' % i] = w16(p.ammo[4 + i])
    r = t.ready
    if r[0] == 'large':
        nums['ready'] = LARGEAMMO
    elif r[0] == 'fps':
        nums['ready'] = w16(fps_rate)
    else:
        nums['ready'] = w16(p.ammo[r[1]])
    icons = {'arms%d' % i: w16(p.weaponowned[i + 1]) for i in range(6)}
    icons['face'] = w16(t.faceindex)
    for i in range(NUMCARDS):
        icons['key%d' % i] = w16(t.keyboxes[i])
    return Values(nums, icons, menuactive)


class Draw(NamedTuple):
    """A patch the drawer drew: the widget, the glyph, the place (for
    numbers, the digit's place 1-3 from the right; else 0)."""
    widget: str
    glyph: str
    place: int


class Bar:
    """ST_Drawer's state: the back buffer (200 rows), STCACHE, the marks,
    the widgets' old values, st_refreshed, stcachenum's "the cache holds
    STBAR" (V_DrawRaw's fast path), and the strip's flags stHide reads
    (message_on, VW_MHID, iigs_textShown's first slot)."""

    def __init__(self, glyphs: Glyphs, tables: D.Tables, buf: bytes,
                 stcache: bytes, old: Dict[str, int], refreshed: int,
                 stcache_valid: bool, message_on: int = 0, mhid: int = 0,
                 text_shown: int = 0):
        self.g = glyphs
        self.t = tables
        self.buf = bytearray(buf)
        self.stcache = bytearray(stcache)
        self.old = dict(old)
        self.refreshed = refreshed
        self.stcache_valid = stcache_valid
        self.message_on = message_on
        self.mhid = mhid
        self.text_shown = text_shown
        self.marks = D.Marks()
        self.draws: List[Draw] = []
        self.restores: List[Tuple[int, int, int, int]] = []

    # V_DrawNumPatchNotScaled
    def patch(self, widget: str, glyph: str, x: int, y: int,
              place: int = 0) -> None:
        data = self.g[glyph]
        px, py = D.vpatch_position(data, x, y)
        D.draw_patch(self.buf, self.marks, data, px, py, self.t)
        self.draws.append(Draw(widget, glyph, place))

    # I_RestoreStatusRect [R i_viigs65.s:1624-1694]
    def restore_status_rect(self, x: int, y: int, w: int, h: int) -> None:
        y0 = w16(y - ST_Y)
        y1 = w16(y0 + h)
        if neg(y0):
            y0 = 0
        # y1 > 32: 32 (the signed compare with its overflow corrected)
        if s16(y1) > ST_HEIGHT:
            y1 = ST_HEIGHT
        b0 = w16(s16(x) >> 1)
        if neg(b0):
            b0 = 0
        b1 = w16(s16(w16(x + w - 1)) >> 1)
        if s16(b1) >= 160:
            b1 = 159
        if not D.rect_empty(y0, y1, b0, b1):
            for r in range(s16(y0), s16(y1)):
                o = (ST_Y + r) * ROW
                self.buf[o + b0:o + b1 + 1] = \
                    self.stcache[r * ROW + b0:r * ROW + b1 + 1]
        ya, yb = w16(y0 + ST_Y), w16(y1 + ST_Y)
        if not D.rect_empty(ya, yb, b0, b1):
            D.mark_rect(self.marks, ya, yb, b0, b1)
            self.restores.append((ya, yb, b0, b1))

    # restoreRect [R st_stuff65.s:878-926]: count patches num wide, the
    # last at x
    def restore_rect(self, x: int, y: int, glyph: str, count: int) -> None:
        w, h, lo, to = self.g.header(glyph)
        pw = w16(count * w)
        left = w16(x - lo - pw + w)
        top = w16(y - to)
        self.restore_status_rect(left, top, pw, h)

    # STlib_drawNum [R :944-998]
    def draw_num(self, n: Num, value: int) -> None:
        digits = n.width
        num = w16(value)
        self.old[n.name] = num
        if neg(num):
            if digits == 2 and num < 0x10000 - 9:
                num = 0x10000 - 9
            elif digits == 3 and num < 0x10000 - 99:
                num = 0x10000 - 99
            num = w16(-num)
        if num == LARGEAMMO:
            return
        w = self.g.width(n.glyphs[0])
        x = n.x
        if num == 0:
            self.patch(n.name, n.glyphs[0], w16(x - w), n.y, 1)
        place = 0
        while num and digits:
            digits -= 1
            place += 1
            x = w16(x - w)
            self.patch(n.name, n.glyphs[num % 10], x, n.y, place)
            num //= 10

    # STlib_updateMultIcon [R :928-942]
    def update_icon(self, ic: Icon, value: int) -> None:
        if value != M16:
            self.patch(ic.name, ic.glyphs[value], ic.x, ic.y)
        self.old[ic.name] = value

    def percent(self, k: int) -> None:
        x, y = PERCENTS[k]
        self.patch('percent%d' % k, PERCENT, x, y)

    # ST_diffNum [R :839-874]
    def diff_num(self, n: Num, value: int) -> bool:
        if w16(value) == self.old[n.name]:
            return False
        w = self.g.width(n.glyphs[0])
        self.restore_rect(w16(n.x - w), n.y, n.glyphs[0], n.width)
        self.draw_num(n, value)
        return True

    # ST_diffIcon [R :876-905]
    def diff_icon(self, ic: Icon, value: int) -> None:
        old = self.old[ic.name]
        if w16(value) == old:
            return
        if old != M16:
            self.restore_rect(ic.x, ic.y, ic.glyphs[old], 1)
        self.update_icon(ic, w16(value))

    def nums_order(self) -> List[Num]:
        """ready, then (ammo i, maxammo i) for i in 0-3 (W_AMMO[i] then
        W_MAXAMMO[i], each row of ammoRows in turn)."""
        out = [WIDGET['ready']]
        for i in range(4):
            out += [WIDGET['ammo%d' % i], WIDGET['maxammo%d' % i]]
        return out

    # refresh [R :749-806]
    def refresh(self, v: Values, bar: bytes) -> None:
        if self.stcache_valid:          # V_DrawRaw: the cached bar
            self.buf[ST_Y * ROW:200 * ROW] = self.stcache
            D.mark_rect(self.marks, ST_Y, 200, 0, 159)
        else:
            D.draw_raw(self.buf, self.marks, bar, ST_Y * 320,
                       ST_HEIGHT * 320, self.t)
            self.stcache[:] = self.buf[ST_Y * ROW:200 * ROW]
            self.stcache_valid = True
        self.draws.append(Draw('bar', BAR, 0))
        self.patch('armsbg', ARMSBG, 104, ST_Y)
        self.stcache[:] = self.buf[ST_Y * ROW:200 * ROW]   # I_SaveStatus..
        for n in self.nums_order():
            self.draw_num(n, v.nums[n.name])
        self.draw_num(WIDGET['health'], v.nums['health'])
        self.draw_num(WIDGET['armor'], v.nums['armor'])
        self.percent(0)
        self.percent(1)
        self.update_icon(FACE, v.icons['face'])
        for k in KEYBOX:
            self.update_icon(k, v.icons[k.name])
        for a in ARMS:
            self.update_icon(a, v.icons[a.name])

    # diffDraw [R :808-837]
    def diff_draw(self, v: Values) -> None:
        for n in self.nums_order():
            self.diff_num(n, v.nums[n.name])
        if self.diff_num(WIDGET['health'], v.nums['health']):
            self.percent(0)
        if self.diff_num(WIDGET['armor'], v.nums['armor']):
            self.percent(1)
        self.diff_icon(FACE, v.icons['face'])
        for k in KEYBOX:
            self.diff_icon(k, v.icons[k.name])
        for a in ARMS:
            self.diff_icon(a, v.icons[a.name])

    # stHide [R :1173-1210]
    def st_hide(self) -> None:
        self.buf[ST_Y * ROW:200 * ROW] = bytes(ST_BYTES)
        D.mark_rect(self.marks, ST_Y, 200, 0, 159)
        if self.message_on or self.mhid:
            self.message_on = 0
            self.text_shown = 0
            self.mhid = 1
            self.buf[0:10 * ROW] = bytes(10 * ROW)
            D.mark_rect(self.marks, 0, 10, 0, 159)

    # ST_Drawer [R :734-747]
    def drawer(self, v: Values, bar: bytes) -> str:
        if v.menuactive:
            self.refreshed = 0
            self.st_hide()
            return 'hide'
        if self.refreshed == 0:
            self.refresh(v, bar)
            self.refreshed = w16(self.refreshed + 1)
            return 'refresh'
        self.diff_draw(v)
        return 'diff'


def tables_of(nibtab: bytes, scb: bytes) -> D.Tables:
    """The row tables of the screen's SCBs (rowPalette's: the palette's
    page, the row's parity, the right pixel 2 pages on)."""
    rowl = bytes((scb[r] & 0x0F) * 4 + (r & 1) for r in range(200))
    return D.Tables(nibtab, rowl, bytes(p + 2 for p in rowl),
                    tuple(p << 8 for p in rowl))
