#!/usr/bin/env python3
"""Part s2pal of milestone 11 (docs/SCREENS.md 1.3, 1.5.7, 1.5.8, 4.1,
6.3; docs/m11-parts/s2pal.md): the palettes, tints, gamma, SCBs, the
finish and the wipe, checked three ways.

1. The model (tools/native/s2palmodel.py) against ref816's captures
   (part s2cap's cases of demo3, newgame, tour and palette.script): every
   frame's palette work as display does it [R d_main65.s:377-558] from
   the state at the frame's start (PD0), the state at I_FinishUpdate's
   entry (PDF) and the screen's SCBs and palettes after it (CA) equal;
   the wipe's black step (PW); every TINTPAL a level frame holds equal to
   buildTints of its record and gamma; the events (the menu's close, the
   loading screen) through their I_FinishUpdate and I_ReloadPalette.
2. The nibble tables and TINTPAL after each level load, gamma change and
   new picture: ref816 dumps of NIBTAB and TINTPAL there (`nibcap`),
   against the model and the native PALW and s2_nib.
3. The native code on a2vm (the test image s2pt of src/native/m11/
   s2pal.mk: s2_pal.s, s2_nib.s, s2_palt.s, in P2DW's room; and PALW,
   s2_palw.s): each frame's case injected (both fills; plain and with the
   bytes the reference wrote poisoned), the frame's calls in display's
   order, a band published between s2_begin and s2_finish: the SCBs and
   palettes after s2_finish equal ref816's, the wipe's step equal to PW,
   the publish order of 1.3 on the write log (s2check.order), the palette
   state equal to the model's, no stray write.

Usage:  python3 tools/native/s2pal.py --model [--runs demo3,...]
        python3 tools/native/s2pal.py --nib       (capture and compare)
        python3 tools/native/s2pal.py --native [--jobs 2] [--every N]
        python3 tools/native/s2pal.py --timing
        python3 tools/native/s2pal.py --all       (the checkpoint)
"""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import s2cap as C, s2palmodel as M  # noqa: E402
from native import s2layout as _S  # noqa: E402

ROOT = C.ROOT
BUILD = ROOT / 'build'
M11 = BUILD / 'native' / 'm11'
WORK = M11 / 's2pal'
# the checkpoint's runs (SCREENS.md 7.3), then part s2cap's other screen
# runs, whose frames this part's palette work also runs in
RUNS = ('demo3', 'newgame', 'tour', 'palette', 'automap', 'menus', 'stbar',
        'finale', 'signs')

GS_LEVEL, GS_INTERMISSION, GS_FINALE, GS_DEMOSCREEN = 0, 1, 2, 3
AM_ACTIVE, AM_OVERLAY = 1, 2


class PalError(Exception):
    pass


# ---------------------------------------------------------------------------
# Upstream's values in a dump
# ---------------------------------------------------------------------------

def val(d: C.Dump, name: str, size: int = 2) -> int:
    return d.word(C.sym(name), size)


def pal_state(d: C.Dump) -> M.PalState:
    """The palette state of i_viigs65.s in a dump."""
    v = 'i_viigs65.s:'
    return M.PalState(d.get(C.sym(v + 'scb'), 200),
                      d.get(C.sym(v + 'palette'), 512),
                      *(val(d, v + f) for f in M.FLAGS))


def gamma_of(d: C.Dump) -> int:
    return val(d, 'm_menu65.s:_g_gamma')


def screen_pal(screen: bytes) -> bytes:
    """The screen's $9D00-$9FFF."""
    return screen[M.SCREEN_PAL_LO:M.SCREEN_PAL_LO + M.SCREEN_PAL_SIZE]


def state_diff(a: M.PalState, b: M.PalState) -> List[str]:
    out = []
    for f in ('scb', 'palette') + M.FLAGS:
        x, y = getattr(a, f), getattr(b, f)
        if f == 'palette' and not (a.palettecount or b.palettecount):
            continue            # (only a picture's palettes matter)
        if x != y:
            if isinstance(x, bytes):
                k = next(i for i in range(len(x)) if x[i] != y[i])
                out.append('%s[%d] %d, ref %d' % (f, k, x[k], y[k]))
            else:
                out.append('%s %d, ref %d' % (f, x, y))
    return out


# ---------------------------------------------------------------------------
# The release's records and pictures (build/ only)
# ---------------------------------------------------------------------------

class Lumps:
    """GSSTAT, GSOVL, each GSVIEWn and each picture, by lump number, from
    the release image (umodel.Release: resident lumps, or the store's
    units of the set that holds them)."""

    def __init__(self):
        from native import umodel as U
        self.U = U
        self.rel = U.Release()
        self.win = U.window(self.rel)
        self.cache: Dict[int, bytes] = {}

    def num(self, name: str) -> int:
        return self.rel.index(name)

    def name(self, num: int) -> str:
        return self.rel.names[num]

    def get(self, num: int) -> bytes:
        if num in self.cache:
            return self.cache[num]
        rel = self.rel
        if rel.resident(num):
            data = rel.resident_bytes(num)
        else:
            sets = [k for k, s in enumerate(rel.sets)
                    if any(e.lump == num for e in s.entries)]
            if not sets:
                raise PalError('lump %d (%s) is in no set' % (num,
                                                             rel.names[num]))
            data = self.U.release_lump(rel, sets[0] + 1, self.win, num)
        self.cache[num] = data
        return data

    def stat(self) -> bytes:
        return self.get(self.num('GSSTAT'))

    def ovl(self) -> bytes:
        return self.get(self.num('GSOVL'))

    def level(self, viewpalnum: int) -> Tuple[bytes, bytes, bytes]:
        return self.get(viewpalnum), self.stat(), self.ovl()


_LUMPS: Optional[Lumps] = None


def lumps() -> Lumps:
    global _LUMPS
    if _LUMPS is None:
        _LUMPS = Lumps()
    return _LUMPS


# ---------------------------------------------------------------------------
# A case's palette work, as display does it
# ---------------------------------------------------------------------------

class Inputs(NamedTuple):
    """What the frame's palette calls read at its start (upstream's
    values): the player's damagecount, powers[pw_strength], bonuscount,
    powers[pw_ironfeet]; the menu; st_palette; the HUD's message_on and
    message_new."""
    damage: int
    strength: int
    bonus: int
    ironfeet: int
    menuactive: int
    st_palette: int
    message_on: int
    message_new: int


def inputs_of(d: C.Dump, at: Optional[C.Dump] = None) -> Inputs:
    """The inputs at the frame's start `d`; the player's four fields from
    `at` (PDF) when given: the scripts' pokes of the player (palette.script
    [R coverage/m11/palette.script:219-225]) land at a tic boundary of
    ref816's that can fall inside display's frame, after PD0 and before
    ST_doPaletteStuff, and display itself changes none of the four
    (`poked` counts the frames where they differ)."""
    pl = C.sym('g_game65.s:_g_player')
    from native import s2state as SS
    ofs = SS.offsets()

    src = at if at is not None else d

    def p(key: str, k: int = 0) -> int:
        return src.word(pl + ofs[key] + 2 * k)
    return Inputs(p('OFS_PL_DAMAGECOUNT'), p('OFS_PL_POWERS', 1),
                  p('OFS_PL_BONUSCOUNT'), p('OFS_PL_POWERS', 3),
                  val(d, 'm_menu65.s:_g_menuactive'),
                  val(d, 'st_stuff65.s:st_palette'),
                  val(d, 'hu_stuff65.s:message_on'),
                  val(d, 'hu_stuff65.s:message_new'))


# the calls of the native frame (Step.op), in display's order
OP_SETPAL0 = 'setpal0'          # I_SetPalette(0): a level left
OP_PICTURE = 'picture'          # drawPicture's palette part (A: the lump)
OP_VIEWPAL = 'viewpal'          # I_ViewPalette(A)
OP_STRIP = 'strip'              # stripEarly (A: DD_PAUSED)
OP_APPLY = 'apply'              # I_ApplyColors (natively: nothing, D1)
OP_STPAL = 'stpal'              # ST_doPaletteStuff
OP_RELOAD = 'reload'            # I_ReloadPalette (the menu's, s2menu1)


class Step(NamedTuple):
    op: str
    arg: int = 0


class Plan(NamedTuple):
    """A case's palette work: `steps` from the state at its start, then
    the finish; or, `foreign` (a menu's or another part's palette work in
    the frame), the finish alone from the state at PDF."""
    kind: str                   # 'frame', 'menu', 'event'
    steps: Tuple[Step, ...]
    foreign: str                # '' or why
    wipe: bool                  # palettecount at the finish: the black step
    title: bool                 # titleWipe's path (X3)
    picture: int                # the new picture's lump, or -1


def display_steps(b: C.Dump, pdf: C.Dump) -> Tuple[List[Step], str]:
    """display's palette calls before M_Drawer [R d_main65.s:377-547],
    from the state at the frame's start; and why the frame has foreign
    palette work ('' when none)."""
    gs = val(b, 'g_game65.s:_g_gamestate')
    ogs = val(b, 'd_main65.s:oldgamestate')
    steps: List[Step] = []
    if gs != GS_LEVEL:
        if ogs == GS_LEVEL:
            steps.append(Step(OP_SETPAL0))
        before, after = val(b, 'i_viigs65.s:picturenum'), \
            val(pdf, 'i_viigs65.s:picturenum')
        if after != before and not after & 0x8000:
            steps.append(Step(OP_PICTURE, after))
        return steps, ''
    if val(b, '_g_gametic', 4) == val(b, '_g_basetic', 4):
        return steps, ''
    mode = val(b, 'am_map65.s:automapmode')
    view = 1 if not mode & AM_ACTIVE or mode & AM_OVERLAY else 0
    menu = val(b, 'm_menu65.s:_g_menuactive')
    paused = 1 if menu and view else 0
    if paused:
        return steps, 'a paused frame: the menu\'s view (s2menu1)'
    steps.append(Step(OP_VIEWPAL, 0 if view else M.AMAP_PAL))
    if view:
        steps.append(Step(OP_STRIP, paused))
        steps.append(Step(OP_APPLY))
    steps.append(Step(OP_STPAL))
    return steps, ''


def plan(case: C.Case) -> Optional[Plan]:
    """The palette work of a case with an I_FinishUpdate (PDF), else
    None."""
    pdf = case.one('PDF')
    if pdf is None:
        return None
    st = pal_state(pdf)
    # titleWipe's path [R w_level65.s:1418-1447]: a new picture whose
    # finish has no black step, so no PW (X3: the first title page over
    # the boot's gray title); counted and named by the report
    title = bool(st.palettecount) and case.one('PW') is None
    if case.head['kind'] == 'event':
        return Plan('event', (), 'an event (%s)' % case.before.point.split(
            ':')[1], bool(st.palettecount), title, -1)
    if case.before.point != 'PD0:display':
        return Plan('menu', (), 'a menu\'s frame (s2menu1)',
                    bool(st.palettecount), title, -1)
    steps, foreign = display_steps(case.before, pdf)
    pic = next((s.arg for s in steps if s.op == OP_PICTURE), -1)
    return Plan('frame', tuple(steps), foreign, bool(st.palettecount),
                title, pic)


def model_of(case: C.Case, d: C.Dump, screen: bytes) -> M.Model:
    return M.Model(pal_state(d), screen_pal(screen),
                   case.carried('TINTPAL'), gamma_of(d))


class Result(NamedTuple):
    """One case through the model."""
    name: str
    plan: Plan
    start: M.PalState           # the native run's palette state
    start_screen: bytes         # and its $9D00-$9FFF
    inputs: Optional[Inputs]
    final: M.PalState
    final_screen: bytes
    written: Dict[int, int]     # the bytes the frame's palette work wrote
    mid_screen: Optional[bytes]  # after the black step and newColors
    st_palette: int
    message_new: int
    invalidated: int
    strip_clears: int
    start_gamma: int
    applied: int                # stores I_ApplyColors made (D1)
    problems: List[str]
    paths: Optional[Dict[str, int]] = None   # the model's branches
    reloaded: int = -1          # I_ReloadPalette's level branch (1) or not


def run_steps(m: M.Model, steps: Sequence[Step], inp: Inputs,
              lp: Optional['Lumps']) -> Tuple[int, int]:
    """The steps on the model; (st_palette, message_new) after."""
    stp, new = inp.st_palette, inp.message_new
    for s in steps:
        if s.op == OP_SETPAL0:
            m.set_palette(0)
        elif s.op == OP_PICTURE:
            if lp is None:
                raise PalError('a picture needs the release\'s lumps')
            m.draw_picture(s.arg, lp.get(s.arg))
        elif s.op == OP_VIEWPAL:
            m.view_palette(s.arg)
        elif s.op == OP_STRIP:
            new = m.strip_early(s.arg, inp.message_on, inp.message_new,
                                inp.menuactive)
        elif s.op == OP_APPLY:
            m.apply_colors()
        elif s.op == OP_STPAL:
            stp = m.st_do_palette_stuff(inp.damage, inp.strength, inp.bonus,
                                        inp.ironfeet, inp.menuactive, stp)
        elif s.op == OP_RELOAD:
            m.reload_palette(None)
    return stp, new


def through_model(name: str, case: C.Case, pl: Plan,
                  lp: Optional[Lumps]) -> Result:
    """A case through the model, compared with the reference: the state
    at PDF, the screen after the finish (CA), the wipe's PW."""
    problems: List[str] = []
    pdf = case.one('PDF')
    b = case.before
    before_screen = case.screen_before
    inp = inputs_of(b, pdf) if pl.kind == 'frame' else None
    if pl.foreign:
        # the finish alone from the state at PDF, over the screen the
        # model makes up to the foreign work (display's steps until the
        # menu's: none of them write the screen but I_ApplyColors)
        m = model_of(case, b, before_screen)
        if inp is not None:
            run_steps(m, pl.steps, inp, lp)
        screen0 = bytes(m.screen)
        m = M.Model(pal_state(pdf), screen0, case.carried('TINTPAL'),
                    gamma_of(pdf))
        start, start_screen = m.state(), bytes(m.screen)
        gamma0 = gamma_of(pdf)
        stp, new = (inp.st_palette, inp.message_new) if inp else (0, 0)
    else:
        m = model_of(case, b, before_screen)
        start, start_screen = m.state(), bytes(m.screen)
        gamma0 = gamma_of(b)
        stp, new = run_steps(m, pl.steps, inp, lp)
        problems += ['at PDF: ' + x for x in state_diff(m.state(),
                                                        pal_state(pdf))]
        if inp is not None and stp != val(pdf, 'st_stuff65.s:st_palette'):
            problems.append('st_palette %d, ref %d' % (
                stp, val(pdf, 'st_stuff65.s:st_palette')))
    n0 = 0 if pl.foreign else len(m.stores)
    mid_at = m.finish_update(title=pl.title)
    mid = None
    if mid_at is not None:
        scr = bytearray(start_screen if pl.foreign else screen_pal(
            before_screen))
        for o, v in m.stores[:mid_at]:
            scr[o - M.SCREEN_PAL_LO] = v
        mid = bytes(scr)
        pw = case.one('PW')
        if pw is None:
            problems.append('a black step without PW')
        else:
            ref = screen_pal(pw.get(*C.SCREEN))
            if ref != mid:
                k = next(i for i in range(len(mid)) if mid[i] != ref[i])
                problems.append('PW: $%04X %02X, ref %02X' % (
                    0x9D00 + k, mid[k], ref[k]))
    elif case.one('PW') is not None:
        problems.append('PW without a black step')
    after = screen_pal(case.screen_after)
    if bytes(m.screen) != after:
        k = next(i for i in range(len(after)) if m.screen[i] != after[i])
        problems.append('after: $%04X %02X, ref %02X' % (
            0x9D00 + k, m.screen[k], after[k]))
    return Result(name, pl, start, start_screen, inp, m.state(),
                  bytes(m.screen), M.stores_written(m.stores), mid, stp,
                  new, m.invalidated, m.strip_clears, gamma0, n0, problems,
                  dict(m.paths))


def tintpal_check(case: C.Case, lp: Lumps, seen: Dict[str, str]
                  ) -> List[str]:
    """A level's TINTPAL (the frame's start) is buildTints of its record
    and gamma: checked once a distinct TINTPAL."""
    b = case.before
    if val(b, 'i_viigs65.s:picturenum') & 0x8000 == 0:
        return []
    vp = val(b, 'i_viigs65.s:viewpalnum')
    if vp & 0x8000:
        return []
    tint = case.carried('TINTPAL')
    key = hashlib.sha256(tint).hexdigest()
    if key in seen:
        return []
    t = bytearray(M.TINTPAL_SIZE)
    view, stat, ovl = lp.level(vp)
    M.build_tints(t, view, stat, ovl, gamma_of(b))
    seen[key] = '%s gamma %d' % (lp.name(vp), gamma_of(b))
    if bytes(t) != tint:
        k = next(i for i in range(len(t)) if t[i] != tint[i])
        return ['TINTPAL of %s: byte %d %02X, ref %02X' % (seen[key], k,
                                                          t[k], tint[k])]
    return []


def event_reload(case: C.Case, lp: Lumps) -> Optional[List[str]]:
    """An event whose TINTPAL was rebuilt after its I_FinishUpdate (the
    menu's close with a new gamma: I_ReloadPalette [R
    i_viigs65.s:2199-2202], dumped at buildTints' return, PC:TINTPAL):
    the model's I_ReloadPalette equal to it. None: no rebuild."""
    if case.head['kind'] != 'event':
        return None
    dumps = [d for d in case.dumps if d.point.startswith('PC:TINTPAL')]
    if not dumps:
        return None
    a = case.after
    m = M.Model(pal_state(a), bytes(M.SCREEN_PAL_SIZE),
                case.carried('TINTPAL'), gamma_of(a))
    m.picturenum = 0xFFFF       # (a level: I_ReloadPalette's branch)
    vp = val(a, 'i_viigs65.s:viewpalnum')
    m.reload_palette(lp.level(vp))
    ref = dumps[-1].get(C.sym('i_viigs65.s:TINTPAL'), M.TINTPAL_SIZE)
    if bytes(m.tintpal) != ref:
        k = next(i for i in range(len(ref)) if m.tintpal[i] != ref[i])
        return ['the reloaded TINTPAL (%s, gamma %d): byte %d %02X, ref '
                '%02X' % (lp.name(vp), m.gamma, k, m.tintpal[k], ref[k])]
    if not (val(a, 'i_viigs65.s:levelcopy') and m.levelcopy):
        return ['the reload left levelcopy %d, ref %d' % (
            m.levelcopy, val(a, 'i_viigs65.s:levelcopy'))]
    return []


# ---------------------------------------------------------------------------
# The model against the reference
# ---------------------------------------------------------------------------

def model_run(run: str, keep: bool = False) -> Dict[str, Any]:
    """Every case of a run through the model; the counts and problems,
    and (keep) the results."""
    rc = C.RunCases(C.CASES / run)
    lp = lumps()
    out: Dict[str, Any] = {'run': run, 'frames': 0, 'events': 0,
                           'finishes': 0, 'static': 0, 'full': 0,
                           'foreign': {}, 'wipes': 0, 'title': 0,
                           'pictures': 0, 'tintpals': 0, 'reloads': 0,
                           'problems': []}
    results: List[Result] = []
    seen: Dict[str, str] = {}
    items = [(e, c, 'frame') for e, c in rc.frames()] + \
        [(e, c, 'event') for e, c in rc.events()]
    for e, case, kind in items:
        out['frames' if kind == 'frame' else 'events'] += 1
        name = '%s/%s' % (run, e['name'])
        if kind == 'frame':
            out['problems'] += ['%s: %s' % (name, x)
                                for x in tintpal_check(case, lp, seen)]
        else:
            r = event_reload(case, lp)
            if r is not None:
                out['reloads'] += 1
                out['problems'] += ['%s: %s' % (name, x) for x in r]
        pl = plan(case)
        if pl is None:
            out['static'] += 1
            if case.head.get('changed') and 'SCREEN' in case.head['changed']:
                a, b = screen_pal(case.screen_after), \
                    screen_pal(case.screen_before)
                if a != b:
                    out['problems'].append('%s: no I_FinishUpdate, but the '
                                           'palettes changed' % name)
            continue
        out['finishes'] += 1
        if pl.foreign:
            out['foreign'][pl.foreign] = out['foreign'].get(pl.foreign,
                                                            0) + 1
        else:
            out['full'] += 1
        out['wipes'] += pl.wipe
        out['title'] += pl.title
        out['pictures'] += pl.picture >= 0
        if pl.kind == 'frame' and inputs_of(case.before) != inputs_of(
                case.before, case.one('PDF')):
            out['poked'] = out.get('poked', 0) + 1
        r = through_model(name, case, pl, lp)
        out['problems'] += ['%s: %s' % (name, x) for x in r.problems]
        if r.applied:
            out['d1'] = out.get('d1', 0) + 1
        for k, v in (r.paths or {}).items():
            out.setdefault('paths', {})[k] = out.get('paths', {}).get(
                k, 0) + v
        if keep:
            results.append(r)
    out['tintpals'] = len(seen)
    if keep:
        out['results'] = results
    return out


# ---------------------------------------------------------------------------
# The nibble tables: ref816 dumps after each level load, new picture and
# gamma change (`nibcap`)
# ---------------------------------------------------------------------------

NIBTAB_ADDR = 0x0B8000          # MM_NIBTAB [R memmap.inc:37]
NIB_DIR = WORK / 'nib'
NIB_FORMAT = 's2pal-nib 1'


def nib_ranges() -> List[Tuple[int, int]]:
    v = 'i_viigs65.s:'
    near = C.sym(v + 'viewpalnum')
    zn = C.sym(v + 'scb')
    return [(NIBTAB_ADDR, M.NIBTAB_SIZE),
            (C.sym(v + 'TINTPAL'), M.TINTPAL_SIZE),
            (near, C.sym(v + 'picturenum') + 2 - near),
            (zn, C.sym(v + 'newpal') + 2 - zn),
            (C.sym('m_menu65.s:_g_gamma'), 2)]


def nib_points() -> List[C.Point]:
    """PL: I_SetLevelPalette's returns; PP: drawPicture's returns; PG: the
    returns of I_MenuPaletteBack, whose jmp I_ReloadPalette rebuilds the
    tints when the gamma changed [R i_viigs65.s:2197-2202]."""
    rng = nib_ranges()
    out = []
    for at in C.jsl_sites(C.sym('i_viigs65.s:I_SetLevelPalette')):
        out.append(C._pc('PL:%06X' % (at + 4), at + 4, rng))
    for at in C.jsr_sites(C.sym('i_viigs65.s:drawPicture')):
        out.append(C._pc('PP:%06X' % (at + 3), at + 3, rng))
    for at in C.jsl_sites(C.sym('i_viigs65.s:I_MenuPaletteBack')):
        out.append(C._pc('PG:%06X' % (at + 4), at + 4, rng))
    if len(out) < 3:
        raise PalError('the nibble points did not resolve: %s' % out)
    return out


class Nib(NamedTuple):
    """One dump: the point, the cycle, the tables, TINTPAL, the palette
    state and the gamma."""
    point: str
    cycles: int
    nibtab: bytes
    tintpal: bytes
    near: bytes                 # viewpalnum .. picturenum
    znear: bytes                # scb .. newpal
    gamma: int

    def word(self, name: str) -> int:
        v = 'i_viigs65.s:'
        rng = nib_ranges()
        for (a, n), data in ((rng[2], self.near), (rng[3], self.znear)):
            s = C.sym(v + name)
            if a <= s < a + n:
                return int.from_bytes(data[s - a:s - a + 2], 'little')
        raise KeyError(name)

    def state(self) -> M.PalState:
        rng = nib_ranges()
        a = rng[3][0]
        v = 'i_viigs65.s:'
        scb = C.sym(v + 'scb') - a
        pal = C.sym(v + 'palette') - a
        return M.PalState(self.znear[scb:scb + 200],
                          self.znear[pal:pal + 512],
                          *(self.word(f) for f in M.FLAGS))


def nib_capture(run: str, out: Path = NIB_DIR) -> Dict[str, Any]:
    """One run's dumps, distilled as they come into out/RUN.z (zlib of a
    JSON list; the tables and TINTPALs once each, by SHA-256)."""
    from ref816 import dumps as D
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='tmp-s2pal-nib-%s-' % run,
                                 dir=str(WORK)))
    pts = nib_points()
    rows: List[Dict[str, Any]] = []
    blobs: Dict[str, str] = {}

    def blob(data: bytes) -> str:
        key = hashlib.sha256(data).hexdigest()
        if key not in blobs:
            blobs[key] = zlib.compress(data, 6).hex()
        return key

    def reader(handle) -> None:
        for d in D.read(handle):
            p = pts[d.header['point']]
            parts = []
            at = 0
            for _, n in p.ranges:
                parts.append(d.data[at:at + n])
                at += n
            rows.append({'point': p.name, 'cycles': d.header['cycles'],
                         'nibtab': blob(parts[0]), 'tintpal': blob(parts[1]),
                         'near': parts[2].hex(), 'znear': parts[3].hex(),
                         'gamma': int.from_bytes(parts[4], 'little')})
    try:
        info = C.machine(run, work, pts, [], reader, None)
        if info['problems']:
            raise PalError('%s: %s' % (run, info['problems'][:4]))
        data = {'format': NIB_FORMAT, 'run': run, 'rows': rows,
                'blobs': blobs, 'traffic': info['traffic'],
                'points': [p.text for p in pts]}
        C.write_atomic(out / (run + '.z'),
                       zlib.compress(json.dumps(data).encode(), 6))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return {'run': run, 'dumps': len(rows), 'traffic': info['traffic']}


def nib_load(run: str, root: Path = NIB_DIR) -> List[Nib]:
    data = json.loads(zlib.decompress((root / (run + '.z')).read_bytes()))
    if data.get('format') != NIB_FORMAT:
        raise PalError('%s: not %s' % (run, NIB_FORMAT))
    cache: Dict[str, bytes] = {}

    def get(key: str) -> bytes:
        if key not in cache:
            b = zlib.decompress(bytes.fromhex(data['blobs'][key]))
            if hashlib.sha256(b).hexdigest() != key:
                raise PalError('%s: a blob does not match its key' % run)
            cache[key] = b
        return cache[key]
    return [Nib(r['point'], r['cycles'], get(r['nibtab']), get(r['tintpal']),
                bytes.fromhex(r['near']), bytes.fromhex(r['znear']),
                r['gamma']) for r in data['rows']]


def nib_model(run: str) -> Dict[str, Any]:
    """The model against each nibble dump of a run: after a level load
    (PL) the tables of palettes 0-11 from the level's records and 12-15
    unchanged since the dump before, TINTPAL buildTints' and the rows; after
    a new picture (PP with palettecount set) all 16 tables from its pairs,
    its rows and palettes; after the menu's close (PG) the tables of the
    last load or picture."""
    lp = lumps()
    out: Dict[str, Any] = {'run': run, 'levels': 0, 'pictures': 0,
                           'same_picture': 0, 'closes': 0, 'problems': []}
    prev: Optional[Nib] = None
    last: Optional[bytes] = None
    for k, n in enumerate(nib_load(run)):
        kind = n.point.split(':')[0]
        tag = '%s/%s#%d' % (run, n.point, k)
        st = n.state()
        if kind == 'PL':
            out['levels'] += 1
            vp = n.word('viewpalnum')
            m = M.Model(st, bytes(M.SCREEN_PAL_SIZE),
                        bytes(M.TINTPAL_SIZE), n.gamma,
                        prev.nibtab if prev else bytes(M.NIBTAB_SIZE))
            m.set_level_palette(*lp.level(vp))
            lo = 0 if prev else 0
            hi = M.NIBTAB_SIZE if prev else M.LEVEL_PALS * 0x400
            if bytes(m.nibtab[lo:hi]) != n.nibtab[lo:hi]:
                out['problems'].append('%s: the level\'s nibble tables (%s)'
                                       % (tag, lp.name(vp)))
            if bytes(m.tintpal) != n.tintpal:
                out['problems'].append('%s: TINTPAL' % tag)
            if bytes(m.scb) != st.scb:
                out['problems'].append('%s: the rows' % tag)
            for f in ('picturenum', 'viewpal', 'strippal'):
                if getattr(m, f) != getattr(st, f):
                    out['problems'].append('%s: %s %d, ref %d' % (
                        tag, f, getattr(m, f), getattr(st, f)))
            last = n.nibtab
        elif kind == 'PP':
            num = n.word('picturenum')
            if not st.palettecount:
                out['same_picture'] += 1
            else:
                out['pictures'] += 1
                m = M.Model(st._replace(picturenum=0xFFFF), bytes(
                    M.SCREEN_PAL_SIZE), bytes(M.TINTPAL_SIZE), n.gamma,
                    bytes(M.NIBTAB_SIZE))
                m.draw_picture(num, lp.get(num))
                if bytes(m.nibtab) != n.nibtab:
                    out['problems'].append('%s: %s\'s nibble tables' % (
                        tag, lp.name(num)))
                d = state_diff(m.state(), st)
                out['problems'] += ['%s: %s' % (tag, x) for x in d]
                last = n.nibtab
        else:
            out['closes'] += 1
            if last is not None and n.nibtab != last:
                out['problems'].append('%s: the tables changed across the '
                                       'menu' % tag)
        prev = n
    return out


# ---------------------------------------------------------------------------
# The native places: the generated include s2pal.inc
# ---------------------------------------------------------------------------

# S2PAL's places (SCREENS.md 4.5's bank 106: TINTPAL, the 16 nibble tables
# S2NIB, GSSTAT, GSOVL, GRAYMAP), PS_TXTINV and s2_pal's and s2_nib's zero
# page $78-$7F are s2layout's (requests S2PAL-1 to -3, applied in wave 3's
# integration) and in s2.inc
S2PAL_PLACES = tuple(_S.S2PAL_PLACES)
S2PAL_AT = dict(_S.S2PAL_AT)
assert _S.S2PAL_SIZE['S2P_TINTPAL'] == M.TINTPAL_SIZE and \
    _S.S2PAL_SIZE['S2P_NIB'] == M.NIBTAB_SIZE
# page 1 $0100-$017F: newColors' bounce for TINTPAL's row (SCREENS.md 4.2:
# page 1 below $01B4 is free outside the replay; the stack stays at or
# above $01C0)
BOUNCE, BOUNCE_SIZE = 0x0100, 128
# the player's fields ST_doPaletteStuff reads (milestone 10's player,
# llayout.player_layout, read only)
PLAYER_FIELDS = (('S2P_DAMAGE', ('damagecount',)),
                 ('S2P_STRENGTH', ('powers', 1)),
                 ('S2P_BONUS', ('bonuscount',)),
                 ('S2P_IRONFEET', ('powers', 3)))


def inc_values() -> List[Tuple[str, int]]:
    from native import llayout as LL
    out: List[Tuple[str, int]] = []
    pl = {tuple(p): at for p, _, at in LL.player_layout()}
    out += [('S2P_PLAYER', LL.G['G_PLAYER']),
            ('S2P_MENUACTIVE', LL.G['G_MENUACTIVE'])]
    out += [(n, pl[p]) for n, p in PLAYER_FIELDS]
    out += [('S2P_LVC', LL.LVC), ('S2P_GSVIEW', LL.LVC_GSVIEW)]
    out += [('S2P_BOUNCE', BOUNCE), ('S2P_BOUNCE_SIZE', BOUNCE_SIZE)]
    return out


def inc_text() -> str:
    lines = ['; Generated by tools/native/s2pal.py (part s2pal, '
             'docs/m11-parts/s2pal.md). Do not edit.',
             '; (S2PAL\'s places, PS_TXTINV and S2P_A-S2P_F are in s2.inc.)',
             '']
    for n, v in inc_values():
        lines.append('%-16s= $%04X' % (n, v))
    return '\n'.join(lines) + '\n'


def write_inc(path: Path) -> None:
    text = inc_text()
    if path.exists() and path.read_text() == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# The native frames on a2vm
# ---------------------------------------------------------------------------

STAGE, PICS, TINTS_BANK = 61, 62, 63       # s2_palt.s's T_STAGE, ...
CASES_A_RUN = 16
MARKER, CLEARED = 0xBFF0, 0xBFF1           # s2_palt.s
OPS = {OP_SETPAL0: 1, OP_VIEWPAL: 2, OP_STRIP: 3, OP_STPAL: 4,
       OP_PICTURE: 5, OP_RELOAD: 6}
RELOADED = 0xBFF2
GLUE_ZP = (0x80, 0x88)
SNAP = 'aux0:9D00-9FFF,aux104:0200-04FF,aux106:1800-57FF,main:BC00-BFFF,' \
       'lc:E440-E47F'


def palst_native(st: M.PalState, begun: int = 0, txtinv: int = 0) -> bytes:
    """PALST's native form (s2layout.palst_places, PS_TXTINV after it):
    the bytes, words and flags of the palette state."""
    from native import s2layout as S
    pl = S.palst_places()
    out = bytearray(S.PALST_SIZE)
    out[pl['PS_SCB']:pl['PS_SCB'] + 200] = st.scb
    out[pl['PS_PALETTE']:pl['PS_PALETTE'] + 512] = st.palette
    for name, f in (('PS_NEWPAL', 'newpal'), ('PS_CURTINT', 'curtint'),
                    ('PS_LEVELCOPY', 'levelcopy'),
                    ('PS_SCBCHANGED', 'scbchanged'),
                    ('PS_VIEWPAL', 'viewpal'), ('PS_STRIPPAL', 'strippal')):
        v = getattr(st, f)
        if not 0 <= v < 256:
            raise PalError('%s %d does not fit a byte' % (f, v))
        out[pl[name]] = v
    if st.palettecount not in (0, 256):
        raise PalError('palettecount %d: upstream sets 0 or 256'
                       % st.palettecount)
    out[pl['PS_PALCOUNT']] = 1 if st.palettecount else 0
    out[pl['PS_PICTURE']:pl['PS_PICTURE'] + 2] = \
        st.picturenum.to_bytes(2, 'little')
    out[pl['PS_BEGUN']] = begun
    out[pl['PS_TXTINV']] = txtinv
    return bytes(out)


def palst_decode(data: bytes) -> Tuple[M.PalState, int, int]:
    """(the state, PS_BEGUN, PS_TXTINV) of PALST's native bytes."""
    from native import s2layout as S
    pl = S.palst_places()
    b = {n: data[pl[n]] for n in ('PS_NEWPAL', 'PS_CURTINT', 'PS_LEVELCOPY',
                                  'PS_SCBCHANGED', 'PS_VIEWPAL',
                                  'PS_STRIPPAL', 'PS_PALCOUNT')}
    st = M.PalState(data[pl['PS_SCB']:pl['PS_SCB'] + 200],
                    data[pl['PS_PALETTE']:pl['PS_PALETTE'] + 512],
                    b['PS_NEWPAL'], b['PS_CURTINT'], b['PS_LEVELCOPY'],
                    256 if b['PS_PALCOUNT'] else 0, b['PS_SCBCHANGED'],
                    int.from_bytes(data[pl['PS_PICTURE']:pl['PS_PICTURE'] +
                                        2], 'little'),
                    b['PS_VIEWPAL'], b['PS_STRIPPAL'])
    return st, data[pl['PS_BEGUN']], data[pl['PS_TXTINV']]


def sx(v: int) -> int:
    """A signed byte's upstream word."""
    return (v - 256) & 0xFFFF if v & 0x80 else v


class NCase(NamedTuple):
    """A case for the native run: the model's result and what it
    stages."""
    r: Result
    band: bool
    tint: bytes
    picture: Optional[bytes]    # the lump's bytes from offset 32,000


def ncase_of(r: Result, k: int, tintpal: bytes, lp: Lumps) -> NCase:
    """Every wipe frame publishes a band (its PW step is between s2_begin
    and s2_finish); the others alternate, so both s2_finish paths run."""
    band = r.mid_screen is not None or k % 2 == 0
    pic = None
    if r.plan.picture >= 0:
        pic = lp.get(r.plan.picture)[M.PICTURE_SCB:]
    return NCase(r, band, tintpal, pic)


def stage(cases: Sequence[NCase], fill: int, poison: bool,
          timing: bool = False
          ) -> Tuple[List[Tuple[int, int, int, bytes]], List[str]]:
    """The records of a batch: the cases in STAGE, their TINTPALs in
    TINTS_BANK, their pictures in PICS."""
    from native import s2layout as S
    recs: List[Tuple[int, int, int, bytes]] = []
    tints: List[bytes] = []
    pics: List[bytes] = []
    calls: List[str] = []
    for k, c in enumerate(cases):
        r = c.r
        if c.tint not in tints:
            tints.append(c.tint)
        j = tints.index(c.tint)
        screen = bytearray(r.start_screen)
        if poison:
            for o in r.written:
                screen[o - M.SCREEN_PAL_LO] = fill
        inp = r.inputs or Inputs(0, 0, 0, 0, 0, 0, 0, 0)
        block = bytearray(0x640)
        block[0:0x300] = palst_native(r.start)
        block[0x300:0x600] = screen
        for at, v in ((0, inp.damage), (2, inp.strength), (4, inp.bonus),
                      (6, inp.ironfeet), (8, inp.menuactive)):
            block[0x600 + at:0x602 + at] = v.to_bytes(2, 'little')
        stp = inp.st_palette
        if not (stp < 0x80 or stp >= 0xFF80):
            raise PalError('%s: st_palette %d does not fit its signed byte'
                           % (r.name, stp))
        block[0x60A] = stp & 0xFF
        block[0x60B] = inp.message_on & 0xFF
        block[0x60C] = inp.message_new & 0xFF
        block[0x60D] = r.start_gamma
        block[0x60E] = j
        block[0x60F] = 2 if timing else (1 if c.band else 0)
        at = 0x610
        steps = [s for s in r.plan.steps if s.op != OP_APPLY] \
            if not r.plan.foreign else []
        for s in steps:
            block[at] = OPS[s.op]
            block[at + 1] = s.arg & 0xFF
            block[at + 2] = (s.arg >> 8) & 0xFF
            at += 3
            if s.op == OP_PICTURE:
                if c.picture not in pics:
                    pics.append(c.picture)
                block[at] = pics.index(c.picture)
                at += 1
        if at > 0x630:
            raise PalError('%s: too many steps' % r.name)
        recs.append((1, STAGE, 0x0200 + k * 0x800, bytes(block)))
        calls.append(r.name)
    if len(tints) > 8 or len(pics) > 8:
        raise PalError('a batch with %d TINTPALs, %d pictures'
                       % (len(tints), len(pics)))
    for j, t in enumerate(tints):
        recs.append((1, TINTS_BANK, 0x0200 + j * 0x1600, t))
    for j, pic in enumerate(pics):
        recs.append((1, PICS, 0x0200 + j * 0x1400, pic))
    recs.append((0, 0, GLUE_ZP[0], bytes(GLUE_ZP[1] - GLUE_ZP[0])))
    # S2PAL's TINTPAL starts as the fill: the glue puts the first in
    return recs, calls


def owners(b, loads) -> List[Any]:
    """The writers of a run of s2pp or s2pf and what each may write."""
    from native import s2drawcase as DC, s2layout as S, s2run as SR, \
        rlayout as R
    pcs = glue_pcs(b)
    lab = b.labels
    pst = lab['s2_palst']
    marks = lab['s2_marks']
    io_w = frozenset({0xC004, 0xC005})
    io_window = frozenset({0xC002, 0xC003, 0xC004, 0xC005, 0xC073})
    zp_pal = ('main', 0, 0x78, 0x80)
    far_zp = ('main', 0, 0x0000, 0x0006)
    stp = ('main', 0, 0xBF2B, 0xBF2C)          # P_STPALETTE
    s2t = S.BUILDS['test'].s2t_base
    hu = ('lc', 0, s2t + S.S2T['HU_ON'], s2t + S.S2T['HU_NEW'] + 1)
    nbuf = lab.get('s2_nbuf')
    out = [SR.driver_owner(b), SR.loader_owner(b, loads),
           SR.Owner('the far layer', (b.segments['RFAR'],),
                    (('main', 0, 0x0000, 0x0006),
                     ('main', 0, M_BOUNCE[0], M_BOUNCE[1]),
                     ('main', 0, S.W_LO, S.W_HI),
                     ('aux', S.S2STATE, 0x0200, 0x0500),
                     ('aux', S.S2PAL, 0x0200, 0xC000)), io_window),
           SR.Owner('the test glue', (pcs['s2_palt'],),
                    (('main', 0, GLUE_ZP[0], GLUE_ZP[1]), far_zp,
                     ('main', 0, R.PHASE, R.PHASE + 1),
                     ('main', 0, S.W_LO, S.W_HI), ('main', 0, 0x0384, 0x0386),
                     ('main', 0, 0x0048, 0x0078),
                     ('main', 0, 0x1C80, 0x1C80 + 148),
                     ('main', 0, 0x1E6B, 0x1E6D),
                     ('aux', 0, 0x9D00, 0xA000), hu,
                     ('lc', 0, s2t, s2t + 61)), io_w),
           SR.Owner('s2_pal', (pcs['s2_pal'],),
                    (zp_pal, far_zp, ('main', 0, pst, pst + S.PALST_SIZE),
                     stp, hu, ('aux', 0, 0x9D00, 0x9DC8),
                     ('aux', 0, 0x9E00, 0xA000)), io_w),
           SR.Owner('s2_pub', (pcs['s2_pub'],),
                    (('main', 0, 0x0048, 0x0078),
                     ('aux', 0, 0x2000 + 100 * 160, 0x2000 + 102 * 160),
                     ('main', 0, marks + 0x40, marks + 0x80),
                     ('main', 0, pst + 0x2D1, pst + 0x2D2)), io_w)]
    if 's2_nib' in pcs:
        out.append(SR.Owner('s2_nib', (pcs['s2_nib'],),
                            (zp_pal, far_zp,
                             ('main', 0, pst, pst + S.PALST_SIZE),
                             ('main', 0, nbuf, nbuf + 0x500)), frozenset()))
    return out


M_BOUNCE = (BOUNCE, BOUNCE + BOUNCE_SIZE)


def glue_pcs(b) -> Dict[str, Tuple[int, int]]:
    """Each module's code (s2drawcase.module_pcs), the glue's assembled
    with -D P2DW (s2_palt-p) named s2_palt."""
    from native import s2drawcase as DC
    pcs = DC.module_pcs(b)
    if 's2_palt-p' in pcs:
        pcs['s2_palt'] = pcs.pop('s2_palt-p')
    return pcs


class NativeOut(NamedTuple):
    cases: int
    problems: List[str]
    writes: int
    stray: int
    stack: Optional[int]
    ms: Dict[int, float]


def native_batch(build, cases: Sequence[NCase], fill: int, poison: bool,
                 profile: Optional[str] = None) -> NativeOut:
    """One a2vm run of a batch: every case's snapshots against the model's
    and the reference's, the write log's strays and order."""
    from native import s2check as K, s2layout as S, s2run as SR
    recs, names = stage(cases, fill, poison)
    calls = []
    for k in range(len(cases)):
        calls += [SR.Call('s2y_case', k), SR.Call('s2y_end')]
    work = Path(tempfile.mkdtemp(prefix='tmp-s2pal-run-', dir=str(WORK)))
    problems: List[str] = []
    try:
        run = SR.run(build, calls, fill, work, extra_records=recs,
                     snap_ranges=SNAP, profile=profile)
        if run.ended() != 'stop' or run.status() != S.S2S['DONE']:
            return NativeOut(len(cases), ['the run ended %s, status %s' % (
                run.ended(), run.status())], 0, 0, None, {})
        snaps = run.calls()
        if len(snaps) != len(calls):
            return NativeOut(len(cases), ['%d snapshots for %d calls' % (
                len(snaps), len(calls))], 0, 0, None, {})
        writes = run.writes()
        n_stray, shown = SR.stray(writes, owners(build, run.loads))
        problems += ['stray: ' + x for x in shown]
        per_case = split_writes(writes, build)
        s2t = S.BUILDS['test'].s2t_base
        for k, c in enumerate(cases):
            r = c.r
            mid, end = snaps[2 * k], snaps[2 * k + 1]
            tag = '%s (fill %02X%s)' % (r.name, fill,
                                        ', poisoned' if poison else '')
            scr = bytes(end.storage('aux', 0)[0x9D00:0xA000])
            if scr != r.final_screen:
                i = next(i for i in range(len(scr))
                         if scr[i] != r.final_screen[i])
                problems.append('%s: after s2_finish $%04X %02X, ref %02X'
                                % (tag, 0x9D00 + i, scr[i],
                                   r.final_screen[i]))
            if r.mid_screen is not None and c.band:
                ms = bytes(mid.storage('aux', 0)[0x9D00:0xA000])
                if ms != r.mid_screen:
                    i = next(i for i in range(len(ms))
                             if ms[i] != r.mid_screen[i])
                    problems.append('%s: the wipe\'s step (PW) $%04X %02X, '
                                    'ref %02X' % (tag, 0x9D00 + i, ms[i],
                                                  r.mid_screen[i]))
            st, begun, txt = palst_decode(bytes(
                end.storage('aux', S.S2STATE)[0x0200:0x0500]))
            d = state_diff(st, r.final)
            problems += ['%s: PALST %s' % (tag, x) for x in d]
            if begun:
                problems.append('%s: s2_begun left set' % tag)
            if txt != (1 if r.invalidated else 0):
                problems.append('%s: PS_TXTINV %d, the model %d' % (
                    tag, txt, r.invalidated))
            if r.inputs is not None and not r.plan.foreign:
                got = sx(end.main[0xBF2B])
                if got != r.st_palette & 0xFFFF:
                    problems.append('%s: st_palette %d, the model %d' % (
                        tag, got, r.st_palette))
                hn = end.lc[s2t + S.S2T['HU_NEW'] - 0xC000]
                if hn != r.message_new & 0xFF:
                    problems.append('%s: message_new %d, the model %d' % (
                        tag, hn, r.message_new))
                if r.reloaded >= 0 and mid.main[RELOADED] != r.reloaded:
                    problems.append('%s: s2_reload\'s C %d, the model %d'
                                    % (tag, mid.main[RELOADED], r.reloaded))
                cl = mid.main[CLEARED]
                if any(s.op == OP_STRIP for s in r.plan.steps) and \
                        cl != (1 if r.strip_clears else 0):
                    problems.append('%s: the strip\'s clear %d, the model '
                                    '%d' % (tag, cl, r.strip_clears))
            if c.picture is not None:
                got = bytes(mid.storage('aux', S.S2PAL)[0x1800:0x5800])
                if (r.paths or {}).get('drawPicture: new'):
                    want = b''.join(M.build_nibtab(c.picture[
                        M.PICTURE_PAIRS - M.PICTURE_SCB + 256 * i:])
                        for i in range(16))
                else:           # the picture on the screen: none built
                    want = bytes([fill]) * len(got)
                if got != want:
                    problems.append('%s: the picture\'s nibble tables' % tag)
            stores = K.screen_stores([w for w in per_case.get(k, [])])
            problems += ['%s: order: %s' % (tag, x) for x in K.order(
                stores, bool(r.start.palettecount) or bool(
                    r.mid_screen is not None) or r.plan.title)]
        ms = SR.phase_ms(run, profile) if profile else {}
        return NativeOut(len(cases), problems, len(writes), n_stray,
                         SR.stack_depth(run), ms)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def split_writes(writes, build) -> Dict[int, List[Any]]:
    """Each case's writes by the code under test (s2_pal, s2_nib, s2_pub),
    cut at the glue's write of the case's number."""
    pcs = glue_pcs(build)
    mine = [pcs[m] for m in ('s2_pal', 's2_nib', 's2_pub') if m in pcs]
    out: Dict[int, List[Any]] = {}
    k = -1
    for w in writes:
        if w.storage == 'main' and w.offset == MARKER and \
                pcs['s2_palt'][0] <= w.pc <= pcs['s2_palt'][1]:
            k = w.new
            continue
        if k >= 0 and any(lo <= w.pc <= hi for lo, hi in mine):
            out.setdefault(k, []).append(w)
    return out


def native_cases(runs: Sequence[str]) -> Tuple[List[Tuple[str, List[NCase]]],
                                               Dict[str, Any]]:
    """Every case with an I_FinishUpdate of the runs through the model,
    in batches for the native runs: the level's and the menus' frames and
    the events on s2pp (P2DW's room), the frames with a new picture on
    s2pf (WIW's room, s2_nib linked); at most 16 cases, 8 TINTPALs and 8
    pictures a batch."""
    lp = lumps()
    batches: List[Tuple[str, List[NCase]]] = []
    counts: Dict[str, Any] = {}
    for run in runs:
        o = model_run(run, keep=True)
        if o['problems']:
            raise PalError('the model differs from ref816 in %s: %s' % (
                run, o['problems'][:3]))
        counts[run] = {k: v for k, v in o.items() if k != 'results'}
        rc = C.RunCases(C.CASES / run)
        idx = {'%s/%s' % (run, e['name']): e
               for e in rc.index['frames'] + rc.index['events']}
        cur: Dict[str, List[NCase]] = {'s2pp': [], 's2pf': []}
        for k, r in enumerate(o['results']):
            img = 's2pf' if r.plan.picture >= 0 else 's2pp'
            tint = rc.load(idx[r.name]).carried('TINTPAL')
            c = ncase_of(r, k, tint, lp)
            b = cur[img]
            tints = {x.tint for x in b} | {tint}
            pics = {x.picture for x in b if x.picture} | (
                {c.picture} if c.picture else set())
            if len(b) == CASES_A_RUN or len(tints) > 8 or len(pics) > 8:
                batches.append((img, b))
                cur[img] = b = []
            b.append(c)
        for img, b in cur.items():
            if b:
                batches.append((img, b))
    return batches, counts


IMAGE_ROOM = {'s2pp': 'P2DW', 's2pf': 'WIW', 'palw': 'PALW'}


# where the images are (a planted bug's scratch build sets it)
BUILD_DIR = WORK


def build(name: str):
    from native import s2run as SR
    return SR.load_build(BUILD_DIR, name, IMAGE_ROOM[name])


def make_part() -> None:
    from native import s2run as SR
    SR.make('s2pal')


def native_all(runs: Sequence[str], jobs: int = 2,
               fills: Sequence[int] = (0xA5, 0x5A),
               poisons: Sequence[bool] = (False, True),
               every: int = 1) -> Dict[str, Any]:
    """Every batch from both fills, plain and poisoned."""
    batches, counts = native_cases(runs)
    builds = {n: build(n) for n in ('s2pp', 's2pf')}
    jobs_list = [(img, b, fill, poison)
                 for k, (img, b) in enumerate(batches) if k % every == 0
                 for fill in fills for poison in poisons]

    def one(job):
        img, b, fill, poison = job
        return img, native_batch(builds[img], b, fill, poison)
    out: Dict[str, Any] = {'runs': list(runs), 'counts': counts,
                           'batches': len(batches), 'a2vm_runs': 0,
                           'cases': 0, 'by_image': {}, 'writes': 0,
                           'stray': 0, 'stack': 0, 'problems': []}
    with ThreadPoolExecutor(max(1, jobs)) as ex:
        for img, r in ex.map(one, jobs_list):
            out['a2vm_runs'] += 1
            out['cases'] += r.cases
            out['by_image'][img] = out['by_image'].get(img, 0) + r.cases
            out['writes'] += r.writes
            out['stray'] += r.stray
            out['stack'] = max(out['stack'], r.stack or 0)
            out['problems'] += r.problems
    return out


def timing(runs: Sequence[str], profile: str, jobs: int = 2,
           every: int = 1) -> Dict[str, Any]:
    """Each case alone in a run (no band: s2_finish runs s2_begin), the
    cost phase 30 only around the code under test: s2_palget, the frame's
    palette calls, s2_begin, s2_finish, s2_palput, in ms; the median, p99
    and worst by kind (a wipe, a frame copying a TINTPAL row, one writing
    the SCBs only, one writing nothing). `every`: one case in N."""
    from native import s2run as SR
    batches, _ = native_cases(runs)
    builds = {n: build(n) for n in ('s2pp', 's2pf')}
    jobs_list = [(img, c) for img, b in batches for c in b]
    jobs_list = jobs_list[::max(1, every)]

    def one(job):
        img, c = job
        recs, _ = stage([c], 0xA5, False, timing=True)
        work = Path(tempfile.mkdtemp(prefix='tmp-s2pal-time-',
                                     dir=str(WORK)))
        try:
            r = SR.run(builds[img], [SR.Call('s2y_case', 0),
                                     SR.Call('s2y_end')], 0xA5, work,
                       extra_records=recs, write_log=False,
                       profile=profile)
            if r.ended() != 'stop':
                raise PalError('a timing run ended %s' % r.ended())
            return c.r, SR.phase_ms(r, profile).get(30, 0.0)
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    kinds: Dict[str, List[float]] = {}
    with ThreadPoolExecutor(max(1, jobs)) as ex:
        for r, ms in ex.map(one, jobs_list):
            k = 'wipe' if r.mid_screen is not None or r.plan.title \
                else ('TINTPAL row' if any(o >= M.PAL_OFS for o in r.written)
                      else ('SCBs' if r.written else 'nothing'))
            kinds.setdefault(k, []).append(ms)
            kinds.setdefault('all', []).append(ms)
    out: Dict[str, Any] = {'profile': profile}
    for k, v in sorted(kinds.items()):
        v.sort()
        out[k] = {'frames': len(v), 'median': round(v[len(v) // 2], 3),
                  'p99': round(v[min(len(v) - 1, (99 * len(v)) // 100)], 3),
                  'worst': round(v[-1], 3)}
    return out


# ---------------------------------------------------------------------------
# ST_doPaletteStuff's paths the captures do not take: ref816 --call
# ---------------------------------------------------------------------------

def stpal_inputs() -> List[Inputs]:
    """Each path of ST_doPaletteStuff at its edges [R st_stuff65.s:
    1103-1171]: the red (each step, the cap, the menu's half, the
    berserk's fade and its signed compare), the gold (each step, the
    cap), the radiation suit (above 128, at and below it with bit 3 on
    and off: the blink), none; st_palette equal (no I_SetPalette) and
    not; and the 16-bit edges."""
    out: List[Inputs] = []
    z = Inputs(0, 0, 0, 0, 0, 0, 0, 0)
    for d in (1, 7, 8, 9, 15, 16, 17, 40, 56, 57, 63, 64, 100, 300,
              0x7FF8, 0x7FF9, 0x8000, 0xFFF9, 0xFFFF):
        for menu in (0, 1):
            out.append(z._replace(damage=d, menuactive=menu))
    for st in (1, 63, 64, 65, 300, 640, 704, 705, 767, 768, 1000, 0x7FFF,
               0x8000, 0xFFFF):
        for d in (0, 5, 12, 13, 0xFFF0):
            out.append(z._replace(strength=st, damage=d))
    for b in (1, 2, 8, 9, 16, 17, 24, 25, 100, 0x7FF9, 0xFFFF):
        out.append(z._replace(bonus=b))
        out.append(z._replace(bonus=b, ironfeet=200))
    for f in (1, 7, 8, 9, 15, 16, 24, 120, 127, 128, 129, 130, 136, 200,
              0x7FFF, 0x8000, 0x8008, 0xFFF7, 0xFFFF):
        out.append(z._replace(ironfeet=f))
    for stp in (0, 1, 9, 13, 0xFFFF):
        out.append(z._replace(st_palette=stp))
        out.append(z._replace(st_palette=stp, damage=20))
        out.append(z._replace(st_palette=stp, ironfeet=200))
    return out


SYNTH_DIR = WORK / 'synth'


def stpal_truth(inputs: Sequence[Inputs], jobs: int = 2
                ) -> List[Tuple[int, int]]:
    """ref816 --call of ST_doPaletteStuff on a state of the release in
    play (part s2draw's base.img: all RAM in a level frame of the tour)
    with each input poked: (st_palette, newpal) after it. Cached by the
    inputs' and this file's hash."""
    from native import s2drawcase as DC
    from native import s2state as SS
    base = DC.BASE
    if not base.exists():
        raise PalError('%s is missing: run python3 tools/native/'
                       's2drawcase.py first (part s2draw\'s truth base)'
                       % base)
    key = hashlib.sha256(json.dumps([list(i) for i in inputs]).encode() +
                         hashlib.sha256(base.read_bytes()).digest() +
                         b'%d' % C.sym('st_stuff65.s:ST_doPaletteStuff')
                         ).hexdigest()[:16]
    cache = SYNTH_DIR / ('stpal-%s.json' % key)
    if cache.exists():
        return [tuple(x) for x in json.loads(cache.read_text())]
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    pl = C.sym('g_game65.s:_g_player')
    ofs = SS.offsets()
    newpal = C.sym('i_viigs65.s:newpal')
    stp = C.sym('st_stuff65.s:st_palette')
    menu = C.sym('m_menu65.s:_g_menuactive')
    routine = C.sym('st_stuff65.s:ST_doPaletteStuff')

    def one(k_inp):
        k, inp = k_inp
        work = Path(tempfile.mkdtemp(prefix='tmp-s2pal-call-',
                                     dir=str(SYNTH_DIR)))
        try:
            w = lambda v: v.to_bytes(2, 'little')  # noqa: E731
            pokes = [(pl + ofs['OFS_PL_DAMAGECOUNT'], w(inp.damage)),
                     (pl + ofs['OFS_PL_POWERS'] + 2, w(inp.strength)),
                     (pl + ofs['OFS_PL_BONUSCOUNT'], w(inp.bonus)),
                     (pl + ofs['OFS_PL_POWERS'] + 6, w(inp.ironfeet)),
                     (menu, w(inp.menuactive)), (stp, w(inp.st_palette)),
                     (newpal, w(M.NO_PALETTE_CHANGE))]
            path = work / 'pokes.img'
            DC.write_pokes(path, pokes)
            _, data = DC.call(base, [path], routine, {},
                              [(stp, 2), (newpal, 2)], work)
            return (int.from_bytes(data[0], 'little'),
                    int.from_bytes(data[1], 'little'))
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    with ThreadPoolExecutor(max(1, jobs)) as ex:
        out = list(ex.map(one, enumerate(inputs)))
    C.write_atomic(cache, json.dumps(out).encode())
    return out


def stpal_synth(jobs: int = 2) -> Tuple[List[Result], List[str]]:
    """The synthetic cases: the model against ref816's --call (st_palette
    and newpal), and each as a frame's Result for the native runs (a
    level's state with tint 0 on the screen, the frame's steps
    ST_doPaletteStuff alone, then the finish)."""
    inputs = stpal_inputs()
    truth = stpal_truth(inputs, jobs)
    problems: List[str] = []
    out: List[Result] = []
    tint = bytearray(M.TINTPAL_SIZE)
    for k in range(M.TINTPAL_SIZE):
        tint[k] = (k * 7 + k // 384) & 0xFF
    st0 = M.PalState(bytes(200), bytes(512), M.NO_PALETTE_CHANGE, 0, 0, 0,
                     0, 0xFFFF, 0, 0)
    pl = Plan('frame', (Step(OP_STPAL),), '', False, False, -1)
    for k, (inp, (rstp, rnew)) in enumerate(zip(inputs, truth)):
        name = 'synth/stpal-%03d' % k
        m = M.Model(st0, bytes(M.SCREEN_PAL_SIZE), bytes(tint), 0)
        stp = m.st_do_palette_stuff(inp.damage, inp.strength, inp.bonus,
                                    inp.ironfeet, inp.menuactive,
                                    inp.st_palette)
        if (stp, m.newpal) != (rstp, rnew):
            problems.append('%s %s: the model st_palette %d newpal %d, '
                            'ref %d %d' % (name, inp, stp, m.newpal, rstp,
                                           rnew))
        if not (stp < 0x80 or stp >= 0xFF80) or not (
                m.newpal < M.TINTS or m.newpal == M.NO_PALETTE_CHANGE):
            # a value P_STPALETTE cannot hold, or a tint past TINTPAL's
            # 14 (upstream's newColors would read past it): the model
            # and ref816 compared, no native frame (counted)
            continue
        m.finish_update()
        out.append(Result(name, pl, st0, bytes(M.SCREEN_PAL_SIZE), inp,
                          m.state(), bytes(m.screen),
                          M.stores_written(m.stores), None, stp,
                          inp.message_new, m.invalidated, m.strip_clears, 0,
                          0, [], dict(m.paths)))
    return out, problems


def stpal_paths() -> Dict[str, int]:
    """How many of the synthetic inputs take each path of
    ST_doPaletteStuff (by the model's own branches: a path with none
    fails the test)."""
    out: Dict[str, int] = {}
    for inp in stpal_inputs():
        cnt = inp.damage
        if inp.strength:
            bzc = M.w16(12 - (inp.strength >> 6))
            if bzc != cnt and not M.neg16(bzc - cnt):
                out['berserk'] = out.get('berserk', 0) + 1
                cnt = bzc
        if cnt:
            k = 'red, menu' if inp.menuactive else 'red'
            a = M.asr16(M.asr16(M.asr16(cnt + 7)))
            if not M.neg16(a - M.NUMREDPALS):
                k += ', capped'
        elif inp.bonus:
            a = M.asr16(M.asr16(M.asr16(M.w16(inp.bonus + 7))))
            k = 'gold, capped' if not M.neg16(a - M.NUMBONUSPALS) \
                else 'gold'
        elif not M.neg16(inp.ironfeet - 129):
            k = 'suit'
        elif inp.ironfeet & 8:
            k = 'suit, blink on'
        elif inp.ironfeet:
            k = 'suit, blink off'
        else:
            k = 'none'
        out[k] = out.get(k, 0) + 1
    return out


def misc_synth() -> List[Result]:
    """The palette calls' branches the captured frames cannot take or take
    rarely (stripEarly paused and with a menu up; the strip kept, cleared
    again and restored; the full automap's rows; I_ReloadPalette's two
    branches; a level left: I_SetPalette(0)), each from a hand-made level
    state through the model, for the native runs."""
    tint = synth_tint()
    base = M.PalState(bytes(200), bytes(512), M.NO_PALETTE_CHANGE, 3, 0, 0,
                      0, 0xFFFF, 0, 0)
    z = Inputs(0, 0, 0, 0, 0, 0, 0, 0)
    msg = M.MSG_PAL
    specs = [
        ('strip-paused', base, z._replace(message_on=1, message_new=1),
         [Step(OP_STRIP, 1)]),
        ('strip-menu', base, z._replace(message_on=1, menuactive=1),
         [Step(OP_STRIP, 0)]),
        ('strip-kept', base._replace(strippal=msg),
         z._replace(message_on=1), [Step(OP_STRIP, 0)]),
        ('strip-again', base._replace(strippal=msg),
         z._replace(message_on=1, message_new=1), [Step(OP_STRIP, 0)]),
        ('strip-off', base._replace(strippal=msg), z, [Step(OP_STRIP, 0)]),
        ('strip-off-automap', base._replace(viewpal=M.AMAP_PAL,
                                            strippal=msg), z,
         [Step(OP_STRIP, 0)]),
        ('viewpal-automap', base, z, [Step(OP_VIEWPAL, M.AMAP_PAL)]),
        ('viewpal-back', base._replace(viewpal=M.AMAP_PAL,
                                       strippal=M.AMAP_PAL), z,
         [Step(OP_VIEWPAL, 0), Step(OP_STRIP, 0)]),
        ('reload-picture', base._replace(picturenum=0x0095), z,
         [Step(OP_RELOAD)]),
        ('reload-level', base, z, [Step(OP_RELOAD)]),
        ('setpal0', base._replace(curtint=5), z, [Step(OP_SETPAL0)]),
        ('setpal0-picture', base._replace(curtint=5, picturenum=0x0144), z,
         [Step(OP_SETPAL0)]),
        # drawPicture of the picture on the screen: nothing (s2pf)
        ('picture-same', base._replace(picturenum=lumps().num('TITLEPIC')),
         z, [Step(OP_PICTURE, lumps().num('TITLEPIC'))]),
    ]
    out: List[Result] = []
    for name, st, inp, steps in specs:
        st = st._replace(scb=bytes((x * 3) & 0x0F for x in range(200)))
        m = M.Model(st, bytes(M.SCREEN_PAL_SIZE), tint, 0)
        pic = next((x.arg for x in steps if x.op == OP_PICTURE), -1)
        pl = Plan('frame', tuple(steps), '', False, False, pic)
        stp, new = run_steps(m, steps, inp, lumps())
        reloaded = -1
        if any(x.op == OP_RELOAD for x in steps):
            reloaded = 1 if st.picturenum & 0x8000 else 0
        m.finish_update()
        out.append(Result('synth/' + name, pl, st, bytes(M.SCREEN_PAL_SIZE),
                          inp, m.state(), bytes(m.screen),
                          M.stores_written(m.stores), None, stp, new,
                          m.invalidated, m.strip_clears, 0, 0, [],
                          dict(m.paths), reloaded))
    return out


def synth_tint() -> bytes:
    tint = bytearray(M.TINTPAL_SIZE)
    for k in range(M.TINTPAL_SIZE):
        tint[k] = (k * 7 + k // 384) & 0xFF
    return bytes(tint)


def synth_native(jobs: int = 2) -> Dict[str, Any]:
    """The synthetic cases on s2pp, both fills, plain and poisoned."""
    results, problems = stpal_synth(jobs)
    results += misc_synth()
    tint = synth_tint()
    lp = lumps()
    cases = [NCase(r, k % 2 == 0, tint, lp.get(r.plan.picture)[
        M.PICTURE_SCB:] if r.plan.picture >= 0 else None)
        for k, r in enumerate(results)]
    builds = {n: build(n) for n in ('s2pp', 's2pf')}
    batches = []
    for img, part in (('s2pp', [c for c in cases if c.picture is None]),
                      ('s2pf', [c for c in cases if c.picture is not None])):
        batches += [(builds[img], part[i:i + CASES_A_RUN])
                    for i in range(0, len(part), CASES_A_RUN)]
    jobs_list = [(b, bt, f, p) for b, bt in batches for f in (0xA5, 0x5A)
                 for p in (False, True)]
    paths: Dict[str, int] = {}
    for r in results:
        for k, v in (r.paths or {}).items():
            paths[k] = paths.get(k, 0) + v
    out: Dict[str, Any] = {'inputs': len(stpal_inputs()),
                           'native_cases': len(cases), 'a2vm_runs': 0,
                           'paths': stpal_paths(), 'model_paths': paths,
                           'problems': list(problems)}
    with ThreadPoolExecutor(max(1, jobs)) as ex:
        for r in ex.map(lambda j: native_batch(*j), jobs_list):
            out['a2vm_runs'] += 1
            out['problems'] += r.problems
    return out


# ---------------------------------------------------------------------------
# PALW and s2_picpal on a2vm, against the nibble dumps
# ---------------------------------------------------------------------------

PIC_BANK = 62
PALW_SNAP = 'aux106:0200-57FF,aux104:0200-04FF,main:BC00-BEFF'


class PCase(NamedTuple):
    name: str
    kind: str                   # 'level', 'gamma', 'picture'
    nib: Nib
    before_nib: Optional[bytes]


def palw_cases(runs: Sequence[str]) -> List[PCase]:
    out: List[PCase] = []
    for run in runs:
        prev: Optional[Nib] = None
        for k, n in enumerate(nib_load(run)):
            kind = n.point.split(':')[0]
            name = '%s/%s#%d' % (run, n.point, k)
            if kind == 'PL':
                out.append(PCase(name, 'level', n,
                                 prev.nibtab if prev else None))
            elif kind == 'PG' and n.tintpal != (prev.tintpal if prev
                                                else b''):
                out.append(PCase(name, 'gamma', n, n.nibtab))
            elif kind == 'PP' and n.state().palettecount:
                out.append(PCase(name, 'picture', n, None))
            prev = n
    return out


def palw_run(b, pc: PCase, fill: int, profile: Optional[str] = None,
             times: Optional[List[float]] = None) -> List[str]:
    """One case on PALW: palw_level, palw_gamma or s2_picpal from a state
    whose fields it must write are scrambled; S2PAL, PALST against the
    dump."""
    from native import llayout as LL, s2layout as S, s2run as SR
    lp = lumps()
    n = pc.nib
    st = n.state()
    vp = n.word('viewpalnum')
    view, stat, ovl = lp.level(vp) if not vp & 0x8000 else (b'', b'', b'')
    recs = [(1, LL.LVC, LL.LVC_GSVIEW, view),
            (1, S.S2PAL, S2PAL_AT['S2P_GSSTAT'], stat),
            (1, S.S2PAL, S2PAL_AT['S2P_GSOVL'], ovl),
            (0, 0, 0x0384, bytes([n.gamma, 0]))]
    if pc.before_nib is not None:
        recs.append((1, S.S2PAL, S2PAL_AT['S2P_NIB'], pc.before_nib))
    if pc.kind == 'level':
        before = st._replace(scb=bytes([fill]) * 200, picturenum=0x0101,
                             viewpal=7, strippal=7, levelcopy=0,
                             scbchanged=0)
        calls = [SR.Call('palw_level')]
    elif pc.kind == 'gamma':
        before = st._replace(levelcopy=0)
        calls = [SR.Call('palw_gamma')]
    else:
        num = n.word('picturenum')
        before = st._replace(scb=bytes([fill]) * 200,
                             palette=bytes([fill]) * 512, palettecount=0,
                             scbchanged=0, picturenum=0xFFFF)
        pic = lp.get(num)[M.PICTURE_SCB:]
        recs += [(1, PIC_BANK, 0x0200, pic),
                 (0, 0, 0x0050, bytes([PIC_BANK, 0x00, 0x02]))]
        calls = [SR.Call('s2_picpal', num & 0xFF, num >> 8)]
    recs.append((1, S.S2STATE, S.SS['SS_PALST'], palst_native(before)))
    work = Path(tempfile.mkdtemp(prefix='tmp-s2pal-palw-', dir=str(WORK)))
    tag = '%s (%s, fill %02X)' % (pc.name, pc.kind, fill)
    out: List[str] = []
    try:
        if pc.kind == 'picture':
            calls = [SR.Call('palw_getst')] + calls + [SR.Call('palw_putst')]
        r = SR.run(b, calls, fill, work, extra_records=recs,
                   snap_ranges=PALW_SNAP, profile=profile)
        if r.ended() != 'stop' or r.status() != S.S2S['DONE']:
            return ['%s: ended %s, status %s' % (tag, r.ended(), r.status())]
        if profile and times is not None:
            times.append(SR.phase_ms(r, profile).get(30, 0.0))
        snap = r.calls()[-1]
        bank = snap.storage('aux', S.S2PAL)
        nib = bytes(bank[S2PAL_AT['S2P_NIB']:S2PAL_AT['S2P_NIB'] +
                         M.NIBTAB_SIZE])
        lo = 0
        hi = M.LEVEL_PALS * 0x400 if pc.kind == 'level' else M.NIBTAB_SIZE
        if pc.kind == 'level' and pc.before_nib is not None:
            hi = M.NIBTAB_SIZE
        if pc.kind == 'level' and pc.before_nib is None and \
                nib[hi:] != bytes([fill]) * (M.NIBTAB_SIZE - hi):
            out.append('%s: tables 12-15 written' % tag)
        if nib[lo:hi] != n.nibtab[lo:hi]:
            k = next(i for i in range(lo, hi) if nib[i] != n.nibtab[i])
            out.append('%s: the nibble tables: palette %d byte $%03X %02X, '
                       'ref %02X' % (tag, k // 0x400, k % 0x400, nib[k],
                                     n.nibtab[k]))
        if pc.kind != 'picture':
            t = bytes(bank[S2PAL_AT['S2P_TINTPAL']:S2PAL_AT['S2P_TINTPAL'] +
                           M.TINTPAL_SIZE])
            if t != n.tintpal:
                k = next(i for i in range(len(t)) if t[i] != n.tintpal[i])
                out.append('%s: TINTPAL byte %d %02X, ref %02X' % (
                    tag, k, t[k], n.tintpal[k]))
        got, begun, txt = palst_decode(bytes(
            snap.storage('aux', S.S2STATE)[0x0200:0x0500]))
        want = st._replace(levelcopy=1) if pc.kind == 'gamma' else st
        out += ['%s: PALST %s' % (tag, x) for x in state_diff(got, want)]
        if txt != (0 if pc.kind == 'gamma' else 1):
            out.append('%s: PS_TXTINV %d' % (tag, txt))
        owners_ = [SR.driver_owner(b), SR.loader_owner(b, r.loads)]
        pcs = glue_pcs(b)
        owners_ += [
            SR.Owner('the far layer', (b.segments['RFAR'],),
                     (('main', 0, 0x0000, 0x0006), ('main', 0, S.W_LO,
                                                    S.W_HI),
                      ('aux', S.S2STATE, 0x0200, 0x0500),
                      ('aux', S.S2PAL, 0x0200, 0x5800)),
                     frozenset({0xC002, 0xC003, 0xC004, 0xC005, 0xC073})),
            SR.Owner('PALW and s2_nib', tuple(pcs[m] for m in
                                              ('s2_palw', 's2_nib')),
                     (('main', 0, 0x0078, 0x0080),
                      ('main', 0, 0x0000, 0x0006),
                      ('main', 0, 0x8000, 0xC000),
                      ('main', 0, pcs['s2_palw'][0],
                       pcs['s2_palw'][1] + 1)), frozenset())]
        n_stray, shown = SR.stray(r.writes(), owners_)
        out += ['%s: stray: %s' % (tag, x) for x in shown]
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return out


def palw_all(runs: Sequence[str], jobs: int = 2) -> Dict[str, Any]:
    b = build('palw')
    cases = palw_cases(runs)
    jobs_list = [(pc, f) for pc in cases for f in (0xA5, 0x5A)]
    out: Dict[str, Any] = {'cases': len(cases), 'a2vm_runs': len(jobs_list),
                           'kinds': {}, 'problems': []}
    for pc in cases:
        out['kinds'][pc.kind] = out['kinds'].get(pc.kind, 0) + 1
    with ThreadPoolExecutor(max(1, jobs)) as ex:
        for probs in ex.map(lambda j: palw_run(b, *j), jobs_list):
            out['problems'] += probs
    return out


def palw_timing(runs: Sequence[str], profile: str) -> Dict[str, Any]:
    """PALW's palw_level and palw_gamma and s2_picpal (with PALST's get
    and put around it), each case alone under the cost model (the driver's
    phase 30 around each call): ms, the worst of each kind."""
    b = build('palw')
    out: Dict[str, Any] = {'profile': profile}
    for pc in palw_cases(runs):
        times: List[float] = []
        probs = palw_run(b, pc, 0xA5, profile, times)
        if probs:
            raise PalError(probs[0])
        k = out.setdefault(pc.kind, {'cases': 0, 'worst': 0.0})
        k['cases'] += 1
        k['worst'] = round(max(k['worst'], sum(times)), 3)
    return out


# ---------------------------------------------------------------------------
# Planted bugs (each in a scratch copy of the sources)
# ---------------------------------------------------------------------------

class Plant(NamedTuple):
    name: str
    path: str                   # under src/native
    old: str
    new: str
    check: str                  # 'frames:RUN', 'palw:RUN', 'synth'
    more: Tuple[str, ...] = ()  # a second edit (old, new)


PLANTS = (
    Plant('gamma applied twice', 's2_nib.s',
          '        lda gammatab,x\n        sta S2P_E\n',
          '        lda gammatab,x\n        ora S2P_D\n        tax\n'
          '        lda gammatab,x\n        sta S2P_E\n', 'palw:palette'),
    Plant('the tint row of newpal - 1', 's2_pal.s',
          '        beq @scb\n        sta PST+PS_CURTINT\n',
          '        beq @scb\n        dec a\n        sta PST+PS_CURTINT\n',
          'frames:palette'),
    Plant('the black step skipped', 's2_pal.s',
          '        lda PST+PS_PALCOUNT\n        beq newcolors\n',
          '        lda PST+PS_PALCOUNT\n        bra newcolors\n',
          'frames:palette'),
    # s2_publish calls s2_begin after its band's stores, in the same
    # call: both snapshots (after the band, after s2_finish) pass
    Plant('the black palettes after the first band', 's2_pub.s',
          '        lda s2_begun            ; the frame\'s first band: '
          's2_begin\n        bne :+\n        jsr s2_begin\n        lda #1\n'
          '        sta s2_begun\n:       lda S2_DRY0',
          '        lda S2_DRY0', 'frames:palette',
          ('        sta RAMWRTOFF\n        ldx S2_DRY0',
           '        sta RAMWRTOFF\n        lda s2_begun\n        bne :+\n'
           '        jsr s2_begin\n        lda #1\n        sta s2_begun\n'
           ':       ldx S2_DRY0')),
    Plant('a radiation suit blink on bit 3 of the wrong byte', 's2_pal.s',
          '        lda PLR+S2P_IRONFEET\n        and #8\n',
          '        lda PLR+S2P_IRONFEET+1\n        and #8\n', 'synth'),
    Plant('the strip\'s palette not restored', 's2_pal.s',
          '@off:   lda PST+PS_VIEWPAL\n', '@off:   bra @done\n',
          'frames:demo3'),
    Plant('TINT_ROW 512 instead of 384', 's2_pal.s',
          'TINT_ROW    = 384\n', 'TINT_ROW    = 512\n', 'frames:palette'),
)


def plant_run(pl: Plant, jobs: int = 2) -> Dict[str, Any]:
    """Build the part from a scratch copy with the bug planted, run its
    check: the failures (the plant is caught when there is one)."""
    global BUILD_DIR
    from native import s2run as SR
    src = ROOT / 'src' / 'native'
    scratch = Path(tempfile.mkdtemp(prefix='tmp-s2pal-plant-',
                                    dir=str(WORK)))
    saved = BUILD_DIR
    try:
        s = scratch / 'src'
        (s / 'm11').mkdir(parents=True)
        shutil.copy(str(src / 'm11.mk'), str(s / 'm11.mk'))
        for f in ('s2lay.mk', 's2pal.mk'):
            shutil.copy(str(src / 'm11' / f), str(s / 'm11' / f))
        text = (src / pl.path).read_text()
        if text.count(pl.old) != 1:
            raise PalError('%s: the text to plant is in %s %d times'
                           % (pl.name, pl.path, text.count(pl.old)))
        text = text.replace(pl.old, pl.new)
        if pl.more:
            if text.count(pl.more[0]) != 1:
                raise PalError('%s: the second edit is in %s %d times'
                               % (pl.name, pl.path,
                                  text.count(pl.more[0])))
            text = text.replace(pl.more[0], pl.more[1])
        (s / pl.path).write_text(text)
        m11 = scratch / 'm11'
        SR.make('s2pal', m11=m11, source=s)
        BUILD_DIR = m11 / 's2pal'
        kind, _, run = pl.check.partition(':')
        if kind == 'frames':
            o = native_all([run], jobs, fills=(0xA5,), poisons=(False,))
        elif kind == 'palw':
            o = palw_all([run], jobs)
        else:
            o = synth_native(jobs)
        probs = o['problems']
        return {'plant': pl.name, 'caught': bool(probs),
                'failures': len(probs), 'first': probs[:3],
                'only_order': bool(probs) and all(': order: ' in x
                                                  for x in probs)}
    finally:
        BUILD_DIR = saved
        shutil.rmtree(str(scratch), ignore_errors=True)


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

# every branch of the model's routines (s2palmodel.Model.took): the
# checkpoint fails when one is taken by no compared case
MODEL_PATHS = (
    "I_ViewPalette: the same", "I_ViewPalette: new, the view's",
    "I_ViewPalette: new, the automap's", 'I_MessageStrip: on, a clear',
    'I_MessageStrip: on, kept', 'I_MessageStrip: off',
    'I_MessageStrip: the rows set', 'stripEarly: paused',
    'stripEarly: a menu', 'ST_doPaletteStuff: a new tint',
    'ST_doPaletteStuff: the same', 'newColors: a new tint, a level',
    'newColors: a new tint, a picture', 'newColors: the SCBs',
    'newColors: a TINTPAL row', 'pictureColors',
    'the finish: titleWipe (X3)', 'the finish: the black step',
    'I_ReloadPalette: a picture', 'I_ReloadPalette: a level',
    'drawPicture: the same', 'drawPicture: new')


def checkpoint(runs: Sequence[str], jobs: int = 2, plants: bool = True,
               timing_profiles: Sequence[str] = ('f121', 'fastpath')
               ) -> Dict[str, Any]:
    """The part's checkpoint: the model against ref816 (frames, events,
    TINTPALs, gamma reloads; the nibble dumps), the native frames (both
    fills, plain and poisoned, the wipe's step, the order), PALW and
    s2_picpal against the nibble dumps, the synthetic ST_doPaletteStuff
    cases against ref816's --call, the timing, the planted bugs. Written
    to build/native/m11/s2pal/report.json."""
    WORK.mkdir(parents=True, exist_ok=True)
    rep: Dict[str, Any] = {'runs': list(runs), 'problems': []}
    missing = [r for r in runs if not (NIB_DIR / (r + '.z')).exists()]
    if missing:
        with ThreadPoolExecutor(max(1, jobs)) as ex:
            rep['nib_capture'] = list(ex.map(nib_capture, missing))
    rep['model'] = []
    for run in runs:
        o = model_run(run)
        rep['problems'] += o.pop('problems')
        rep['model'].append(o)
    rep['nib_model'] = []
    for run in runs:
        o = nib_model(run)
        rep['problems'] += o.pop('problems')
        rep['nib_model'].append(o)
    o = native_all(runs, jobs)
    o.pop('counts')
    rep['problems'] += o.pop('problems')
    rep['native'] = o
    o = palw_all(runs, jobs)
    rep['problems'] += o.pop('problems')
    rep['palw'] = o
    o = synth_native(jobs)
    rep['problems'] += o.pop('problems')
    rep['synth'] = o
    cover: Dict[str, int] = {p: 0 for p in MODEL_PATHS}
    for src in rep['model'] + [{'paths': o['model_paths']}]:
        for k, v in src.get('paths', {}).items():
            cover[k] = cover.get(k, 0) + v
    rep['coverage'] = cover
    rep['problems'] += ['the path "%s" is never taken' % k
                        for k, v in cover.items() if not v]
    rep['timing'] = [timing(runs, prof, jobs) for prof in timing_profiles]
    rep['palw_timing'] = [palw_timing(runs, prof)
                          for prof in timing_profiles]
    if plants:
        rep['plants'] = [plant_run(pl, jobs) for pl in PLANTS]
        rep['problems'] += ['planted bug not caught: %s' % x['plant']
                            for x in rep['plants'] if not x['caught']]
        if not rep['plants'][3]['only_order']:
            rep['problems'].append('the plant "%s" is not caught by the '
                                   'order alone' % PLANTS[3].name)
    rep['ok'] = not rep['problems']
    C.write_atomic(WORK / 'report.json',
                   json.dumps(rep, indent=1, sort_keys=True).encode())
    return rep


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--inc', metavar='OUT')
    parser.add_argument('--model', action='store_true')
    parser.add_argument('--nib', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--runs', default=','.join(RUNS))
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--palw', action='store_true')
    parser.add_argument('--synth', action='store_true')
    parser.add_argument('--timing', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--all', action='store_true',
                        help='the checkpoint (report.json)')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args(argv)
    runs = [r for r in args.runs.split(',') if r]
    if args.inc:
        write_inc(Path(args.inc))
        return 0
    if (args.native or args.palw or args.synth or args.timing or
            args.plants or args.all) and not args.no_build:
        make_part()
    if args.all:
        rep = checkpoint(runs, args.jobs)
        show = {k: v for k, v in rep.items() if k != 'problems'}
        print(json.dumps(show, indent=1, sort_keys=True))
        for x in rep['problems'][:30]:
            print('  ' + x)
        print('checkpoint %s: %d problems' % ('passes' if rep['ok'] else
                                              'FAILS', len(rep['problems'])))
        return 0 if rep['ok'] else 1
    bad = 0
    if args.capture:
        WORK.mkdir(parents=True, exist_ok=True)
        print(C.df_report())
        with ThreadPoolExecutor(max(1, args.jobs)) as ex:
            for r in ex.map(nib_capture, runs):
                print('nib capture %(run)s: %(dumps)d dumps, %(traffic)d '
                      'bytes' % r)
    if args.model:
        for run in runs:
            o = model_run(run)
            probs = o.pop('problems')
            bad += len(probs)
            print(json.dumps(o, sort_keys=True))
            for p in probs[:20]:
                print('  ' + p)
    if args.nib:
        for run in runs:
            o = nib_model(run)
            probs = o.pop('problems')
            bad += len(probs)
            print(json.dumps(o, sort_keys=True))
            for p in probs[:20]:
                print('  ' + p)
    for flag, fn in ((args.native, lambda: native_all(runs, args.jobs)),
                     (args.palw, lambda: palw_all(runs, args.jobs)),
                     (args.synth, lambda: synth_native(args.jobs))):
        if flag:
            o = fn()
            probs = o.pop('problems')
            o.pop('counts', None)
            bad += len(probs)
            print(json.dumps(o, sort_keys=True))
            for p in probs[:20]:
                print('  ' + p)
    if args.timing:
        for prof in ('f121', 'fastpath'):
            print(json.dumps(timing(runs, prof, args.jobs), sort_keys=True))
    if args.plants:
        for pl in PLANTS:
            o = plant_run(pl, args.jobs)
            bad += not o['caught']
            print(json.dumps(o))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
