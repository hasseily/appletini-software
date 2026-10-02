#!/usr/bin/env python3
"""The reference captures of milestone 11's first half (docs/SCREENS.md
6.1, part s2cap): ref816 runs of upstream with dump points and a call log
streamed through pipes and distilled into cases as they come; the raw
streams are never kept.

Usage:  python3 tools/native/s2cap.py --capture [--runs demo3,menus,...]
                                      [--out DIR] [--jobs 2]
        python3 tools/native/s2cap.py --check [--runs ...] [--twice]
                                      [--two-run N]
        python3 tools/native/s2cap.py --points     (the points, resolved)

The runs (RUNS): demo3 (the title loop to the end of its demo,
lumps.demo_script), newgame and tour (coverage/), demo1 and demo2 (the
same with the lump placed as DEMO3: the sound calls only, no screens, 6.1
"DEMO1 and DEMO2 (the sound calls)"), and this part's six scripts of
coverage/m11/: menus, automap, palette, finale, signs, stbar.

The points (a dump each time one fires; `points`):

  PD0:display  pc=displayCall when its operand is display (a frame of
       display's): the 2D state of 1.6 by unit (STATE: the near and znear
       data of st_stuff65.s, hu_stuff65.s, m_menu65.s, am_map65.s,
       wi_stuff65.s, f_finale65.s, i_viigs65.s, d_main65.s, g_game65.s
       (the player), s_sound65.s; viewtop, viewbottom, iigs_bindwait,
       keyTable, keyNames) and i_viigs65.s's zfar but TINTPAL (DRB, DRE)
  PD0:menu, PD0:skull  a menu's frame (displayCall then calls
       menuDisplayNear: uiDisplay never enters display) where it may
       first write: uiDisplay's jsl M_Drawer, staticUpToDate's skull
       path; uiDisplay's static turns, about 2,000 a second, write nothing
       and dump nothing
  PDX:*  the same three, every SCREEN_EVERY-th: the carried ranges, each
       checked equal to the value the distiller carried
  PC:NAME:ADDR  where a write of a carried range is complete: the
       screen at I_FinishUpdate's two RTLs, I_ShowDirty's, titleWipe's
       own return to D_Wipe's caller and the returns of bmSignBox (the
       busy sign's rows by MVN); STCACHE after I_SaveStatusBackground and
       V_DrawRaw; TINTPAL after buildTints; AM_LISTS after AM_Drawer with
       the map on. A frame's carried values at its start are CB, those
       it changed CA
  PV   R_RenderPlayerView's entry: viewtop, viewbottom, message_on,
       DD_PAUSED, automapmode, gametic (VIEWTOP, 1.5.2)
  PM   I_MenuPalette's entry when the menu's palette is not on: the
       screen under the menu (the view it grays)
  PDF  I_FinishUpdate (= D_Wipe), every arrival: the marks DRB, DRE and
       STATE (with DRY0, DRY1 and the palette state)
  PDS  I_ShowDirty: the marks and i_viigs65.s's znear
  PW   the jsr pictureColors of I_FinishUpdate's black path: the screen
       after the black palettes, newColors and the marked bytes (1.5.8)
  PD1  pc=displayCall+3 when its operand is display: display's frame
       ends (a menu's frame ends where the next thing begins; display's
       frame in which a menu opened, whose PD1 does not fire, at the next
       frame's start: lazy_ends)
  PU0, PU1  each JSL site of an event routine (bmSignOn, bmSignOff,
       bmSignLoading, bmSignSaving, bmDiskAsk, F_LoadScreen,
       I_MenuPaletteBack) and its return address: STATE and the screen

The call log (one pipe, `routines`): display (the turns' bounds, the
player's mo and the menu flag at their entry; their returns are the
two-run method's cycle counts), R_RenderPlayerView (PV again, with its
caller), G_Ticker (the gametic), ST_Ticker, HU_Ticker and F_Ticker (their
state and the player's fields at the entry and the return; the last two
by JMP: jumps=1), the sound calls (S_StartSound, S_StartSound2,
S_StopSound with _Dp, the gametic and the channel block; startSound,
stopChannel; isPlaying, docVolume, adjustParams and S_UpdateSounds,
jumps=1 since musFrame reaches it by JMP, while no menu is up),
I_FinishUpdate, I_ShowDirty, I_MenuPalette and the event routines.

The cases (build/native/m11/cases/RUN/, `RunCases`): index.json (each
frame and event with its place in cases.pack and its SHA-256, the blob
keys, the run's counts and problems), cases.pack (each case: zlib of a
JSON header line then its inline bytes; a range of BLOB_MIN bytes or more
is in blobs.pack by its SHA-256, once a run; a shorter one PD0 also has
is XOR'ed with it), calls.z (the call log). Level frames leave the
renderer's rows (X1, `Case.blank`) zero in CB, CA, PW and PC:SCREEN.

Every run is bounded (bounded.py's limits: 25 minutes, the files ref816
writes at most MAX_FILE, the pipes' traffic at most PIPE_LIMIT, counted
as it comes), at normal priority, at most JOBS at once; the free disk is
checked before a capture (20 GB) and the cases' total at the end (60 MB).
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, NamedTuple, \
    Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ref816 import bounded, dumps, lumps, make_image, marks as MK, \
    refimage, run_script, script, title  # noqa: E402

ROOT = make_image.ROOT           # (the tree's, also from a scratch copy)
BUILD = ROOT / 'build'
M11 = BUILD / 'native' / 'm11'
CASES = M11 / 'cases'
WORK = M11 / 's2cap'
COVERAGE_M11 = ROOT / 'coverage' / 'm11'
RUNS = ('demo3', 'newgame', 'tour', 'demo1', 'demo2', 'menus', 'automap',
        'palette', 'finale', 'signs', 'stbar')
SCRIPTS = ('menus', 'automap', 'palette', 'finale', 'signs', 'stbar')
SOUND_ONLY = ('demo1', 'demo2')
CASE_FORMAT = 's2cap-case 1'
CALLS_FORMAT = 's2cap-calls 1'
INDEX_FORMAT = 's2cap-index 1'
DEMO_SECONDS = 3000
RUN_TIMEOUT = 25 * 60           # a capture run's wall time (7.3's budget)
PIPE_LIMIT = 200 * 10 ** 6      # the pipes' traffic of a run (7.3's budget)
MAX_FILE = 64 << 20             # any file ref816 writes itself
CASES_LIMIT = 60 * 10 ** 6      # all cases (6.1)
MIN_FREE = 20 * 10 ** 9         # the ground rules: stop below 20 GB
JOBS = 2                        # the task's limit on parallel jobs
SCREEN = (0xE12000, 0x8000)
PAGE = 0x100

# the units whose near data are the 2D state (6.1 PD0), and the extra
# near words
STATE_UNITS = ('st_stuff65.s', 'hu_stuff65.s', 'm_menu65.s', 'am_map65.s',
               'wi_stuff65.s', 'f_finale65.s', 'i_viigs65.s', 'd_main65.s',
               'g_game65.s', 's_sound65.s')
STATE_SECTIONS = ('near', 'znear')
STATE_EXTRA = (('r_state65.s:viewtop', 2), ('r_state65.s:viewbottom', 2),
               ('i_iigs65.s:iigs_bindwait', 2),   # the key setup's wait
               ('i_iigs65.s:keyTable', 256),      # the bindings it draws
               ('m_menu65.s:keyNames', 1024),     # and their names (6.2)
               ('VW_MHID', 2))      # stHide's flag (S2STBAR-3, wave 4)
MERGE_GAP = 96                  # near ranges this close are one range
EVENT_ROUTINES = ('m_menu65.s:bmSignOn', 'm_menu65.s:bmSignOff',
                  'm_menu65.s:bmSignLoading', 'm_menu65.s:bmSignSaving',
                  'm_menu65.s:bmDiskAsk', 'f_finale65.s:F_LoadScreen',
                  'i_viigs65.s:I_MenuPaletteBack')
JSL, JSR, RTL = 0x22, 0x20, 0x6B
TINTPAL_SIZE = 14 * 384          # TINTS x TINT_ROW [R i_viigs65.s:85]
# PV (6.1): the frame's VIEWTOP inputs at R_RenderPlayerView's entry
PV_FIELDS = (('r_state65.s:viewtop', 2), ('r_state65.s:viewbottom', 2),
             ('hu_stuff65.s:message_on', 2), ('d_main65.s:DD_PAUSED', 2),
             ('am_map65.s:automapmode', 2), ('g_game65.s:_g_gametic', 4))
SCREEN_EVERY = 8                # PDX: the frame start's screen, sampled
UI_PALON_ON = 0x6D70            # i_viigs65.s: the menu's palette is on
BLOB_MIN = 1024                 # ranges this long go to the blob store
AM_ACTIVE, AM_OVERLAY = 1, 2    # automapmode [R d_main65.s:50-53]


class CapError(Exception):
    pass


# ---------------------------------------------------------------------------
# Symbols, the code, the points
# ---------------------------------------------------------------------------

_LINKMAP: Optional[Dict] = None


def linkmap() -> Dict:
    global _LINKMAP
    if _LINKMAP is None:
        with open(str(make_image.LINKMAP)) as handle:
            _LINKMAP = json.load(handle)
    return _LINKMAP


_SYMBOLS: Optional[script.Symbols] = None


def symbols() -> script.Symbols:
    global _SYMBOLS
    if _SYMBOLS is None:
        _SYMBOLS = script.Symbols(linkmap())
    return _SYMBOLS


_SYMS: Dict[str, int] = {}


def sym(name: str) -> int:
    if name not in _SYMS:
        _SYMS[name] = symbols().address(name)
    return _SYMS[name]


def direct_page() -> int:
    return linkmap()['game']['sections']['ztiny']['first']


def fragments(unit: str, sections: Sequence[str]) -> List[Tuple[int, int]]:
    """(address, size) of a unit's data fragments in `sections`."""
    out = []
    for f in linkmap()['game']['fragments']:
        if f['unit'] == unit and f['section'] in sections and \
                f['kind'] != 'text' and f['address'] is not None and \
                f['size']:
            out.append((f['address'], f['size']))
    return sorted(out)


def merge(ranges: Iterable[Tuple[int, int]], gap: int = 0
          ) -> List[Tuple[int, int]]:
    """Ranges sorted and joined when they overlap or are `gap` apart (in
    one bank)."""
    out: List[List[int]] = []
    for a, n in sorted(ranges):
        if out and a >> 16 == out[-1][0] >> 16 and \
                a <= out[-1][0] + out[-1][1] + gap:
            end = max(out[-1][0] + out[-1][1], a + n)
            out[-1][1] = end - out[-1][0]
        else:
            out.append([a, n])
    return [(a, n) for a, n in out]


def state_ranges() -> List[Tuple[int, int]]:
    rs: List[Tuple[int, int]] = []
    for u in STATE_UNITS:
        rs += fragments(u, STATE_SECTIONS)
    rs += [(sym(n), z) for n, z in STATE_EXTRA]
    return merge(rs, MERGE_GAP)


_CODE: Optional[refimage.Memory] = None


def code() -> refimage.Memory:
    """The release's memory at its entry (the game's code)."""
    global _CODE
    if _CODE is None:
        _CODE = refimage.load(refimage.read(title.MEMORY))
    return _CODE


def text_fragments() -> List[Tuple[int, int]]:
    return [(f['address'], f['size']) for f in linkmap()['game']['fragments']
            if f['kind'] == 'text' and f['address'] is not None and
            f['size'] and f['unit'] != 'cal_integer.s']


def find(op: bytes, lo: int, hi: int) -> List[int]:
    """The addresses in [lo, hi) where the bytes `op` are."""
    data = code().get(lo, hi - lo)
    out, at = [], data.find(op)
    while at >= 0:
        out.append(lo + at)
        at = data.find(op, at + 1)
    return out


def jsl_sites(target: int) -> List[int]:
    op = bytes([JSL, target & 0xFF, (target >> 8) & 0xFF, target >> 16])
    out: List[int] = []
    for a, n in text_fragments():
        out += find(op, a, a + n)
    return sorted(out)


class Point(NamedTuple):
    name: str
    text: str                   # ref816's --dump-at, addresses in hex
    ranges: Tuple[Tuple[int, int], ...]


def _ranges_text(ranges: Sequence[Tuple[int, int]]) -> str:
    return '+'.join('%06X:%d' % (a, n) for a, n in ranges)


def _pc(name: str, address: int, ranges: Sequence[Tuple[int, int]],
        extra: str = '') -> Point:
    if len(ranges) > 32:
        raise CapError('%s has %d ranges (ref816 takes 32)' % (name,
                                                              len(ranges)))
    return Point(name, 'pc=%06X%s,ranges=%s' % (address, extra,
                                                _ranges_text(ranges)),
                 tuple(ranges))


class Places(NamedTuple):
    display_call: int
    frame_end: int              # displayCall + 3: the frame's end
    finish: int                 # I_FinishUpdate = D_Wipe
    show_dirty: int
    black_colors: int           # the jsr pictureColors of the black path
    events: Tuple[Tuple[str, int], ...]     # (routine, JSL site)
    state: Tuple[Tuple[int, int], ...]
    ivzsmall: Tuple[int, int]   # i_viigs65.s's zfar before TINTPAL
    ivznear: Tuple[Tuple[int, int], ...]
    marks: Tuple[int, int]
    amlists: Tuple[int, int]
    automapmode: int
    render: int                 # R_RenderPlayerView
    pv: Tuple[Tuple[int, int], ...]
    menu_palette: int           # I_MenuPalette
    ui_palon: int               # UI_PALON: $6D70 while the menu's palette
    carried: Tuple[Tuple[str, Tuple[int, int], Tuple[int, ...]], ...]
    # (name, range, the addresses where a write of it is complete)
    display: int                # display: displayCall's target in a frame
    menu_start: int             # uiDisplay's jsl M_Drawer: a menu frame
    skull_start: int            # staticUpToDate's 2$: the skull redrawn
    am_returns: Tuple[int, ...]  # AM_Drawer's returns in display


def jsr_sites(target: int) -> List[int]:
    """The JSR abs sites to `target` in the text of its own bank."""
    op = bytes([JSR, target & 0xFF, (target >> 8) & 0xFF])
    out: List[int] = []
    for a, n in text_fragments():
        if a >> 16 == target >> 16:
            out += find(op, a, a + n)
    return sorted(out)


def places() -> Places:
    s = symbols()
    dc = s.address('d_main65.s:displayCall')
    if code().get(dc, 1)[0] != JSR:
        raise CapError('displayCall is not a JSR')
    finish = s.address('i_viigs65.s:I_FinishUpdate')
    apply_ = s.address('i_viigs65.s:I_ApplyColors')
    show = s.address('i_viigs65.s:I_ShowDirty')
    pc_ = s.address('i_viigs65.s:pictureColors')
    nc = s.address('i_viigs65.s:newColors')
    sd = s.address('i_viigs65.s:showDirty')
    black = find(bytes([JSR, pc_ & 0xFF, (pc_ >> 8) & 0xFF]), finish, apply_)
    if len(black) != 1:
        raise CapError('I_FinishUpdate has %d jsr pictureColors' % len(black))
    # I_FinishUpdate's two returns: the black path's rtl after its jsr
    # pictureColors, the other path's after jsr newColors, jsr showDirty
    plain = find(bytes([JSR, nc & 0xFF, nc >> 8 & 0xFF, JSR, sd & 0xFF,
                        sd >> 8 & 0xFF, RTL]), finish, apply_)
    rtls = [black[0] + 3] + [x + 6 for x in plain]
    if len(plain) != 1 or code().get(black[0] + 3, 1)[0] != RTL or \
            code().get(show, 4) != bytes([JSR, sd & 0xFF, sd >> 8 & 0xFF,
                                          RTL]):
        raise CapError('the returns of I_FinishUpdate, I_ShowDirty are not '
                       'where the source has them')
    events = []
    for r in EVENT_ROUTINES:
        for site in jsl_sites(s.address(r)):
            events.append((r.partition(':')[2], site))
    ivz = fragments('i_viigs65.s', ('zfar',))
    tint = s.address('i_viigs65.s:TINTPAL')
    if len(ivz) != 1 or not ivz[0][0] < tint < ivz[0][0] + ivz[0][1] or \
            tint + TINTPAL_SIZE != ivz[0][0] + ivz[0][1]:
        raise CapError('TINTPAL is not the end of i_viigs65.s\'s zfar')
    amf = fragments('am_map65.s', ('coldfar',))
    drb = s.address('i_viigs65.s:DRB')
    if s.address('i_viigs65.s:DRE') != drb + 200:
        raise CapError('DRE does not follow DRB')
    # the writers' returns: STCACHE by I_SaveStatusBackground (V_DrawRaw
    # falls into it [R i_viigs65.s:1355-1367]), TINTPAL by buildTints
    stc = [x + 4 for r in ('i_viigs65.s:I_SaveStatusBackground',
                           'i_viigs65.s:V_DrawRaw')
           for x in jsl_sites(s.address(r))]
    bt = [x + 3 for x in jsr_sites(s.address('i_viigs65.s:buildTints'))]
    if len(bt) != 2 or not stc:
        raise CapError('buildTints has %d callers, STCACHE %d' % (len(bt),
                                                                 len(stc)))
    # the busy sign's rows saved and put back by MVN (bmSignBox; bmSignOff
    # is also reached by JMP [R m_menu65.s:1798, w_level65.s:519])
    box = [x + 3 for x in jsr_sites(s.address('m_menu65.s:bmSignBox'))]
    ui = s.address('i_viigs65.s:uiDisplay')
    md = s.address('m_menu65.s:M_Drawer')
    menu = [x for x in jsl_sites(md) if ui <= x < s.address(
        'i_viigs65.s:I_MenuPalette')]
    sud = s.address('d_main65.s:staticUpToDate')
    sk = s.address('d_main65.s:skullshown')
    skull = find(bytes([0x38, 0x60, 0xAD, sk & 0xFF, sk >> 8 & 0xFF]), sud,
                 s.address('d_main65.s:restoreRect'))
    amd = s.address('am_map65.s:AM_Drawer')
    am = [x + 4 for x in jsl_sites(amd)
          if s.address('d_main65.s:display') <= x < s.address(
              'd_main65.s:onlyTics')]
    if len(box) < 2 or len(menu) != 1 or len(skull) != 1 or len(am) != 2:
        raise CapError('bmSignBox %d, uiDisplay %d, staticUpToDate %d, '
                       'AM_Drawer %d sites' % (len(box), len(menu),
                                               len(skull), len(am)))
    # titleWipe (the first title page) returns to D_Wipe's caller itself
    # after its MVN of rows 191-199: tsc, clc, adc #3, tcs, rtl [R
    # w_level65.s:1430-1447]
    tw = s.address('w_level65.s:titleWipe')
    tail = find(bytes([0x3B, 0x18, 0x69, 0x03, 0x00, 0x1B, RTL]), tw,
                tw + 0x80)
    if len(tail) != 1:
        raise CapError('titleWipe has %d returns to its caller' % len(tail))
    carried = (('SCREEN', SCREEN, tuple(sorted(rtls + [show + 3] + box +
                                               [tail[0] + 6]))),
               ('STCACHE', (s.address('i_viigs65.s:STCACHE'), 5120),
                tuple(sorted(stc))),
               ('TINTPAL', (tint, TINTPAL_SIZE), tuple(bt)),
               ('AMLISTS', amf[0], tuple(am)))
    return Places(dc, dc + 3, finish, show, black[0], tuple(events),
                  tuple(state_ranges()), (ivz[0][0], tint - ivz[0][0]),
                  tuple(merge(fragments('i_viigs65.s', ('znear',)))),
                  (drb, 400), amf[0], s.address('am_map65.s:automapmode'),
                  s.address('r_frame65.s:R_RenderPlayerView'),
                  tuple((s.address(n), z) for n, z in PV_FIELDS),
                  s.address('i_viigs65.s:I_MenuPalette'),
                  s.address('i_viigs65.s:UI_PALON'), carried,
                  s.address('d_main65.s:display'), menu[0], skull[0] + 2,
                  tuple(am))


def points(p: Places, screens: bool = True) -> List[Point]:
    """The dump points of a run (6.1), in --dump-at order."""
    if not screens:
        return []
    st = list(p.state)
    carried = [r for _, r, _ in p.carried]
    # a frame starts where it may first write: display's frames at the
    # main loop's call (displayCall's operand is display: no menu), a
    # menu's at uiDisplay's jsl M_Drawer or at staticUpToDate's skull path
    # (uiDisplay's static frames, thousands a second, write nothing and
    # dump only PD1's word)
    disp = ',if=%06X:2:eq:0x%04X' % (p.display_call + 1, p.display & 0xFFFF)
    out = [_pc('PD0:display', p.display_call, st + [p.ivzsmall], disp),
           _pc('PDX:display', p.display_call, carried,
               disp + ',hits=1-/%d' % SCREEN_EVERY),
           _pc('PD0:menu', p.menu_start, st + [p.ivzsmall]),
           _pc('PDX:menu', p.menu_start, carried,
               ',hits=1-/%d' % SCREEN_EVERY),
           _pc('PD0:skull', p.skull_start, st + [p.ivzsmall]),
           _pc('PDX:skull', p.skull_start, carried,
               ',hits=1-/%d' % SCREEN_EVERY),
           _pc('PV', p.render, list(p.pv)),
           _pc('PM', p.menu_palette, [SCREEN],
               ',if=%06X:2:ne:0x%X' % (p.ui_palon, UI_PALON_ON)),
           _pc('PDF', p.finish, [p.marks] + st),
           _pc('PDS', p.show_dirty, [p.marks] + list(p.ivznear)),
           _pc('PW', p.black_colors, [SCREEN]),
           _pc('PD1', p.frame_end, [p.pv[-1]], disp)]
    for name, rng, ats in p.carried:
        # the list is written by AM_Drawer in the full mode (any of
        # ROTATE and FOLLOW with ACTIVE): every return with a mode on
        cond = ',if=%06X:2:ne:0' % p.automapmode \
            if name == 'AMLISTS' else ''
        for at in ats:
            out.append(_pc('PC:%s:%06X' % (name, at), at, [rng], cond))
    for routine, site in p.events:
        out.append(_pc('PU0:%s:%06X' % (routine, site), site, st + [SCREEN]))
        out.append(_pc('PU1:%s:%06X' % (routine, site), site + 4,
                       st + [SCREEN]))
    if len(out) > 64:
        raise CapError('%d points (ref816 takes 64)' % len(out))
    return out



# the call log: (name, routine text with symbols; calls.py's form)
def routines(jumps_update: bool = True) -> List[Tuple[str, str]]:
    # the channel block: s_sound65.s's znear (CH_SFX, CH_ORIGIN, CH_PICKUP,
    # CHANSFX, USECOUNT, the pool, FM, the SS_* arguments)
    chan = 's_sound65.s:%s:%d' % _znear_first('s_sound65.s')
    snd = 's_sound65.s:%s,in=dp:_Dp:4+_g_gametic:4+' + chan + ',out=' + chan
    st = 'st_stuff65.s:%s:%d' % _znear_first('st_stuff65.s')
    hu = 'hu_stuff65.s:%s:%d' % _znear_first('hu_stuff65.s')
    fi = 'f_finale65.s:%s:%d' % _znear_first('f_finale65.s')
    pl = 'g_game65.s:_g_player:155'
    # musFrame runs S_UpdateSounds in every turn of the main loop, about
    # 2,000 a second while a menu is up and nothing is drawn: it and its
    # per-turn callees are logged while no menu is up (6.1's check is on
    # those turns; a menu's sounds, S_StartSound, are all logged)
    nomenu = ',if=_g_menuactive:2:eq:0'
    out = [
        ('display', 'd_main65.s:display,in=g_game65.s:_g_player:4+'
         '_g_menuactive:2'),
        ('R_RenderPlayerView', 'r_frame65.s:R_RenderPlayerView,entry=1,in='
         'r_state65.s:viewtop:2+r_state65.s:viewbottom:2+'
         'hu_stuff65.s:message_on:2+d_main65.s:DD_PAUSED:2+'
         'am_map65.s:automapmode:2+_g_gametic:4'),
        ('G_Ticker', 'g_game65.s:G_Ticker,entry=1,in=_g_gametic:4'),
        ('ST_Ticker', 'st_stuff65.s:ST_Ticker,mem=%s+%s' % (st, pl)),
        # G_Ticker reaches HU_Ticker and F_Ticker by JMP [R
        # g_game65.s:615-623]: jumps=1, as S_UpdateSounds
        ('HU_Ticker', 'hu_stuff65.s:HU_Ticker,jumps=1,mem=%s+%s+'
         'm_menu65.s:showMessages:2+'
         'hu_stuff65.s:_g_message_dontfuckwithme:2' % (hu, pl)),
        ('F_Ticker', 'f_finale65.s:F_Ticker,jumps=1,mem=%s+_g_gameaction:2+'
         'wi_stuff65.s:_g_acceleratestage:2' % fi),
        ('S_StartSound', snd % 'S_StartSound'),
        ('S_StartSound2', snd % 'S_StartSound2'),
        ('S_StopSound', snd % 'S_StopSound'),
        ('startSound', 's_sound65.s:startSound,mem=%s' % chan),
        ('isPlaying', 's_sound65.s:isPlaying,in=%s%s' % (chan, nomenu)),
        ('docVolume', 's_sound65.s:docVolume,in=%s%s' % (chan, nomenu)),
        ('stopChannel', 's_sound65.s:stopChannel,mem=%s' % chan),
        ('adjustParams', 's_sound65.s:adjustParams,in=dp:_Dp:8+%s,out=%s%s'
         % (chan, chan, nomenu)),
        ('S_UpdateSounds', 's_sound65.s:S_UpdateSounds,%smem=%s+'
         '_g_gametic:4%s' % ('jumps=1,' if jumps_update else '', chan,
                             nomenu)),
        ('I_FinishUpdate', 'i_viigs65.s:I_FinishUpdate'),
        ('I_ShowDirty', 'i_viigs65.s:I_ShowDirty'),
    ]
    for r in EVENT_ROUTINES:
        out.append((r.partition(':')[2], r))
    out.append(('I_MenuPalette', 'i_viigs65.s:I_MenuPalette'))
    return out


def _znear(unit: str) -> List[Tuple[int, int]]:
    return fragments(unit, ('znear',))


def _znear_first(unit: str) -> Tuple[str, int]:
    """A label at the start of the unit's (one) znear fragment, and the
    fragment's size."""
    fr = _znear(unit)
    if len(fr) != 1:
        raise CapError('%s has %d znear fragments' % (unit, len(fr)))
    a, n = fr[0]
    labels = linkmap()['game']['units'][unit]
    names = sorted(k for k, v in labels.items() if v == a)
    if not names:
        raise CapError('%s: no label at its znear start' % unit)
    return names[0], n


def _znear_size(unit: str) -> int:
    fr = _znear(unit)
    if len(fr) != 1:
        raise CapError('%s has %d znear fragments' % (unit, len(fr)))
    return fr[0][1]


# ---------------------------------------------------------------------------
# The runs
# ---------------------------------------------------------------------------

def check_disk(path: Path = BUILD) -> int:
    """The free bytes; CapError below 20 GB (the ground rules)."""
    path.mkdir(parents=True, exist_ok=True)
    st = os.statvfs(str(path))
    free = st.f_bavail * st.f_frsize
    if free < MIN_FREE:
        raise CapError('only %.1f GB free: captures stop below 20 GB'
                       % (free / 1e9))
    return free


def df_report() -> str:
    """`df -h /System/Volumes/Data` (the task's rule), or of build/."""
    target = '/System/Volumes/Data'
    if not Path(target).exists():
        target = str(BUILD)
    r = bounded.run(['df', '-h', target], timeout=30, max_bytes=1 << 20,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    universal_newlines=True)
    return r.stdout.strip()


def ready() -> None:
    """The machine and the release image exist (built by milestone 2's
    commands; never rebuilt here, the build is shared)."""
    for p in (title.MACHINE, title.MEMORY, title.DISK, make_image.LINKMAP):
        if not p.exists():
            raise CapError('%s is missing: build ref816 first (MILESTONES.md'
                           ' "Setting up")' % p)


def script_of(run: str, work: Path) -> Tuple[Path, List[str], float]:
    """The run's script (written into work for the demos), the machine's
    extra options (a placed lump) and its time limit in machine seconds."""
    if run.startswith('demo'):
        name = 'DEMO' + run[4:]
        info = lumps.demo_info(lumps.read_wad()[name])
        path = work / (run + '.script')
        path.write_text(lumps.demo_script(info['map'], DEMO_SECONDS))
        extra = [] if name == 'DEMO3' else lumps.options(
            name, symbols(), out=work / 'lumps')
        return path, extra, DEMO_SECONDS + 120
    if run in ('newgame', 'tour'):
        return run_script.script_path(run), [], \
            run_script.DEFAULT_LIMIT_SECONDS
    if run in SCRIPTS:
        return COVERAGE_M11 / (run + '.script'), [], \
            run_script.DEFAULT_LIMIT_SECONDS
    raise CapError('no run %s (one of %s)' % (run, ', '.join(RUNS)))


def resolve_routine(text: str) -> str:
    from ref816 import calls as CL
    return CL.resolve(text, CL.Linkmap(linkmap()))


class Traffic:
    """The bytes read from a run's pipes, against PIPE_LIMIT."""

    def __init__(self, limit: int = PIPE_LIMIT):
        self.limit = limit
        self.total = 0
        self.lock = threading.Lock()

    def add(self, n: int) -> None:
        with self.lock:
            self.total += n
            if self.total > self.limit:
                raise CapError('the pipes passed %d bytes' % self.limit)


class CountingReader:
    """A binary pipe whose reads count against a Traffic."""

    def __init__(self, handle, traffic: Traffic):
        self.handle = handle
        self.traffic = traffic

    def readline(self) -> bytes:
        line = self.handle.readline()
        self.traffic.add(len(line))
        return line

    def read(self, n: int = -1) -> bytes:
        data = self.handle.read(n)
        self.traffic.add(len(data))
        return data

    def close(self) -> None:
        pass


def machine(run: str, work: Path, pts: Sequence[Point],
            logged: Sequence[Tuple[str, str]], dump_reader, log_reader,
            pokes: Optional[Path] = None, traffic: Optional[Traffic] = None,
            timeout: float = RUN_TIMEOUT, extra: Sequence[str] = (),
            script_path: Optional[Path] = None) -> Dict[str, Any]:
    """One run of the release on ref816 with run_script's stops and checks:
    dump_reader(handle) reads the dump stream (stdout) and log_reader(
    handle) the call log (a named pipe) while the machine runs. The run's
    state, problems and traffic."""
    ready()
    path, more, seconds = script_of(run, work)
    if script_path is not None:
        path = script_path
    syms = symbols()
    prog = script.compile_script(path.read_text(), syms, path.name)
    (work / 'input.txt').write_text(prog)
    shots = work / 'shots'
    shots.mkdir(exist_ok=True)
    traffic = traffic or Traffic()
    cmd = [str(title.MACHINE), str(title.MEMORY), '--disk', str(title.DISK),
           '--input', str(work / 'input.txt'), '--shot-dir', str(shots),
           '--stop-on-fault', '--marks', str(work / 'marks.txt'),
           '--state', str(work / 'state.json'),
           '--frames', str(script.frames(seconds))]
    for unit, name in run_script.STOPS:
        cmd += ['--stop-pc', '%06X' % syms.address(unit + ':' + name)]
    for unit, name in (run_script.LOOP, run_script.RENDER):
        cmd += ['--mark', '%06X' % syms.address(unit + ':' + name)]
    cmd += list(more)
    fifo = None
    if logged:
        fifo = work / 'calls.fifo'
        if fifo.exists():
            fifo.unlink()
        os.mkfifo(str(fifo))
        cmd += ['--call-log-file', str(fifo), '--call-log-limit',
                str(PIPE_LIMIT)]
        for _, text in logged:
            cmd += ['--call-log', resolve_routine(text)]
    if pts:
        cmd += ['--dump-stream', '-', '--dump-limit', str(PIPE_LIMIT)]
        for p in pts:
            cmd += ['--dump-at', p.text]
    if pokes is not None:
        cmd += ['--poke-file', str(pokes)]
    cmd += list(extra)
    errors: List[BaseException] = []
    threads: List[threading.Thread] = []

    def start(target) -> threading.Thread:
        def body():
            try:
                target()
            except BaseException as error:     # reported below
                errors.append(error)
        t = threading.Thread(target=body)
        t.daemon = True
        t.start()
        threads.append(t)
        return t

    fifo_thread = None
    if fifo is not None:
        def read_fifo():
            with open(str(fifo), 'rb') as handle:
                try:
                    log_reader(CountingReader(handle, traffic))
                finally:
                    while handle.read(1 << 16):    # (drain: never block it)
                        pass
        fifo_thread = start(read_fifo)
    preexec = bounded._limits(MAX_FILE, int(timeout) + bounded.CPU_SLACK)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE if pts
                            else subprocess.DEVNULL,
                            stderr=subprocess.PIPE, preexec_fn=preexec,
                            start_new_session=True)
    err_box: List[bytes] = []
    start(lambda: err_box.append(proc.stderr.read()[-20000:]))
    if pts:
        def read_stream():
            try:
                dump_reader(CountingReader(proc.stdout, traffic))
            finally:
                while proc.stdout.read(1 << 16):
                    pass
        start(read_stream)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        bounded._kill_group(proc.pid)
        proc.wait()
        raise CapError('%s: ref816 did not finish in %d s' % (run, timeout))
    finally:
        bounded._kill_group(proc.pid)
    if fifo_thread is not None and fifo_thread.is_alive():
        fifo_thread.join(10)
        if fifo_thread.is_alive():      # never opened: give it an EOF
            try:
                os.close(os.open(str(fifo), os.O_WRONLY | os.O_NONBLOCK))
            except OSError:
                pass
    for t in threads:
        t.join(600)
    for handle in (proc.stdout, proc.stderr):
        if handle is not None:
            handle.close()
    if fifo is not None and fifo.exists():
        fifo.unlink()
    err = err_box[0] if err_box else b''
    if proc.returncode:
        raise CapError('%s: ref816 failed (%d%s): %s' % (
            run, proc.returncode, bounded.explain(proc.returncode, MAX_FILE),
            err.decode(errors='replace')[-1500:]))
    if errors:
        raise errors[0]
    state = json.loads((work / 'state.json').read_text())
    problems = run_script.problems(state, MK.read(work / 'marks.txt'), syms,
                                   prog)
    if path.parent == work:            # a demo's, written in the work
        shown = 'lumps.demo_script: ' + path.name
    else:
        try:
            shown = str(path.relative_to(ROOT))
        except ValueError:
            shown = str(path)
    return {'state': state, 'problems': problems, 'traffic': traffic.total,
            'script': shown}


# ---------------------------------------------------------------------------
# Cases: the file format
# ---------------------------------------------------------------------------

class Dump(NamedTuple):
    """One dump of a case: its point, its moment and its memory."""
    point: str
    head: Dict[str, Any]        # cycles, frame, hit, cpu, ...
    ranges: Tuple[Tuple[int, int], ...]
    data: bytes

    def get(self, address: int, length: int) -> bytes:
        at = 0
        for a, n in self.ranges:
            if a <= address and address + length <= a + n:
                return self.data[at + address - a:at + address - a + length]
            at += n
        raise KeyError('$%06X+%d is not in %s' % (address, length,
                                                 self.point))

    def has(self, address: int, length: int = 1) -> bool:
        return any(a <= address and address + length <= a + n
                   for a, n in self.ranges)

    def word(self, address: int, size: int = 2) -> int:
        return int.from_bytes(self.get(address, size), 'little')


class Case(NamedTuple):
    """A frame (PD0 .. PD1) or an event (PU0 .. PU1). `SB` is the screen
    at the frame's start (PDX when sampled there, else the screen the
    frame before or the last event left: head 'screen_from'); `blank`
    lists the screen rows the case does not define (X1: the renderer's
    view rows of a level frame), zero in SB, PD1 and PW."""
    head: Dict[str, Any]
    dumps: Tuple[Dump, ...]

    def all(self, point: str) -> List[Dump]:
        return [d for d in self.dumps if d.point.split(':')[0] == point]

    def one(self, point: str) -> Optional[Dump]:
        found = self.all(point)
        return found[0] if found else None

    def first_of(self, names: Sequence[str]) -> Dump:
        for d in self.dumps:
            if d.point.split(':')[0] in names:
                return d
        raise KeyError('no %s in the case' % '/'.join(names))

    @property
    def before(self) -> Dump:
        """The state at the start (PD0, or PU0 for an event)."""
        return self.first_of(('PD0', 'PU0'))

    @property
    def after(self) -> Dump:
        """PD1 (display's frames) or PU1 (events); a menu frame has none
        (it ends where the next thing begins)."""
        return self.first_of(('PD1', 'PU1'))

    def carried(self, name: str, after: bool = False) -> bytes:
        """A frame's carried range (SCREEN, STCACHE, TINTPAL) at its start
        (CB), or at its end (after: CA when it changed in the frame)."""
        for point in (('CA', 'CB') if after else ('CB',)):
            d = self.one(point)
            if d is not None and name in d.head['names']:
                return d.get(*d.ranges[d.head['names'].index(name)])
        raise KeyError('the case has no %s' % name)

    @property
    def screen_before(self) -> bytes:
        if self.head['kind'] == 'event':
            return self.first_of(('PU0',)).get(*SCREEN)
        return self.carried('SCREEN')

    @property
    def screen_after(self) -> bytes:
        if self.head['kind'] == 'event':
            return self.after.get(*SCREEN)
        return self.carried('SCREEN', after=True)

    def blank_offsets(self) -> List[int]:
        """The screen offsets (from $2000) the case leaves undefined."""
        out: List[int] = []
        for r0, r1 in self.head.get('blank', []):
            out += range(r0 * 160, (r1 + 1) * 160)
        return out


class Pack:
    """An append-only file of zlib'd records: (offset, length) each."""

    def __init__(self, path: Path):
        self.path = path
        self.size = path.stat().st_size if path.exists() else 0

    def add(self, blob: bytes) -> Tuple[int, int]:
        with open(str(self.path), 'ab') as handle:
            handle.write(blob)
        at = self.size
        self.size += len(blob)
        return at, len(blob)

    def read(self, at: int, n: int) -> bytes:
        with open(str(self.path), 'rb') as handle:
            handle.seek(at)
            data = handle.read(n)
        if len(data) != n:
            raise ValueError('%s: a record is cut short' % self.path)
        return data


class BlobStore:
    """A run's content-addressed store (blobs.pack, the keys in
    index.json): each distinct range of BLOB_MIN bytes or more once, by
    its SHA-256 (identical screens and caches are stored once a run)."""

    def __init__(self, root: Path, keys: Optional[Dict[str, List[int]]] = None):
        self.pack = Pack(root / 'blobs.pack')
        self.keys: Dict[str, List[int]] = dict(keys or {})

    def put(self, data: bytes) -> str:
        key = hashlib.sha256(data).hexdigest()
        if key not in self.keys:
            at, n = self.pack.add(zlib.compress(data, 6))
            self.keys[key] = [at, n, len(data)]
        return key

    def get(self, key: str) -> bytes:
        at, n, _ = self.keys[key]
        data = zlib.decompress(self.pack.read(at, n))
        if hashlib.sha256(data).hexdigest() != key:
            raise ValueError('blob %s does not match its key' % key)
        return data


def encode_case(head: Dict[str, Any], dlist: Sequence[Dump],
                store: BlobStore) -> bytes:
    """A case file: zlib of the header line then the inline bytes. A
    range of BLOB_MIN bytes or more goes to the store (by its SHA-256); a
    shorter one the first dump also has is XOR'ed with it."""
    base = dlist[0] if dlist else None
    entries = []
    body = bytearray()
    for i, d in enumerate(dlist):
        at = 0
        parts = []
        for a, n in d.ranges:
            data = d.data[at:at + n]
            at += n
            if n >= BLOB_MIN:
                parts.append([a, n, 'blob:' + store.put(data)])
            elif i and base is not None and base.has(a, n):
                body += _xor(data, base.get(a, n))
                parts.append([a, n, 'xor'])
            else:
                body += data
                parts.append([a, n, 'raw'])
        entries.append({'point': d.point, 'head': d.head, 'ranges': parts})
    h = dict(head)
    h['format'] = CASE_FORMAT
    h['dumps'] = entries
    raw = json.dumps(h, sort_keys=True, separators=(',', ':')).encode() + \
        b'\n' + bytes(body)
    return zlib.compress(raw, 6)


def _xor(a: bytes, b: bytes) -> bytes:
    n = len(a)
    return (int.from_bytes(a, 'little') ^ int.from_bytes(b, 'little')
            ).to_bytes(n, 'little')


def decode_case(blob: bytes, store: BlobStore) -> Case:
    raw = zlib.decompress(blob)
    nl = raw.index(b'\n')
    head = json.loads(raw[:nl])
    if head.get('format') != CASE_FORMAT:
        raise ValueError('not an s2cap case')
    at = nl + 1
    out: List[Dump] = []
    for e in head.pop('dumps'):
        data = bytearray()
        ranges = []
        for a, n, how in e['ranges']:
            if how.startswith('blob:'):
                part = store.get(how[5:])
            elif how in ('raw', 'xor'):
                part = raw[at:at + n]
                at += n
                if how == 'xor':
                    part = _xor(part, out[0].get(a, n))
            else:
                raise ValueError('a range stored as %s' % how)
            if len(part) != n:
                raise ValueError('%s: a range is cut short' % e['point'])
            data += part
            ranges.append((a, n))
        out.append(Dump(e['point'], e['head'], tuple(ranges), bytes(data)))
    if at != len(raw):
        raise ValueError('bytes after the last dump')
    return Case(head, tuple(out))


class RunCases:
    """A captured run: its index, its cases (cases.pack) and blobs."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.index = json.loads((self.root / 'index.json').read_text())
        self.store = BlobStore(self.root, self.index['blobs']['keys'])
        self.pack = Pack(self.root / 'cases.pack')

    def load(self, entry: Dict[str, Any]) -> Case:
        blob = self.pack.read(entry['at'], entry['bytes'])
        if hashlib.sha256(blob).hexdigest() != entry['sha256']:
            raise ValueError('%s: case %s does not match its SHA-256'
                             % (self.root, entry['name']))
        return decode_case(blob, self.store)

    def frames(self) -> Iterator[Tuple[Dict[str, Any], Case]]:
        for e in self.index['frames']:
            yield e, self.load(e)

    def events(self) -> Iterator[Tuple[Dict[str, Any], Case]]:
        for e in self.index['events']:
            yield e, self.load(e)

    def frame(self, k: int) -> Case:
        return self.load(self.index['frames'][k])

    def calls(self) -> 'Calls':
        return load_calls(self.root / 'calls.z')


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(data)
    os.replace(str(tmp), str(path))


# ---------------------------------------------------------------------------
# The distiller: the dump stream into cases, as it comes
# ---------------------------------------------------------------------------

DUMP_KEYS = ('dump', 'hit', 'note', 'frame', 'clock', 'cycles',
             'instructions', 'cpu', 'switches')
ROW = 160
VIEW_ROWS = 168                 # rows 0-167 the view (X1)
# HU_TITLEY [R hu_stuff65.s:20-22] .. +7: STCFN036, STCFN064, STCFN081
# are 8 high (S2HUD-5, wave 4: the region 'title' is rows 160-167)
TITLE_ROWS = (160, 167)


def x1_rows(pv: Dump, p: 'Places') -> List[Tuple[int, int]]:
    """The renderer's rows of a level frame (exclusion X1, 6.3): rows
    0-167 when viewtop is $FFFF, 10-167 when it is 9; the map title's
    rows 160-167 stay defined when the overlay is on (the HUD draws them,
    region 'title')."""
    top = pv.word(p.pv[0][0])
    first = 0 if top == 0xFFFF else top + 1
    mode = pv.word(p.automapmode)
    if mode & (AM_ACTIVE | AM_OVERLAY) == AM_ACTIVE | AM_OVERLAY:
        return [(r0, r1) for r0, r1 in ((first, TITLE_ROWS[0] - 1),
                                        (TITLE_ROWS[1] + 1, VIEW_ROWS - 1))
                if r0 <= r1]
    return [(first, VIEW_ROWS - 1)]


def blanked(d: Dump, rows: Sequence[Tuple[int, int]]) -> Dump:
    """d with the screen rows `rows` zero."""
    if not rows or not d.has(*SCREEN):
        return d
    at = 0
    for a, n in d.ranges:
        if (a, n) == SCREEN:
            break
        at += n
    data = bytearray(d.data)
    for r0, r1 in rows:
        data[at + r0 * ROW:at + (r1 + 1) * ROW] = bytes((r1 + 1 - r0) * ROW)
    return Dump(d.point, d.head, d.ranges, bytes(data))


class Distiller:
    """Reads a dump stream and writes a case at each frame's end (PD1)
    and each event's return (PU1). The carried ranges (the screen,
    STCACHE, TINTPAL) are dumped where a write of them completes (PC:*)
    and at every SCREEN_EVERY-th frame start (PDX); their value at a
    frame's start (CB) is the last one dumped, and each PDX must equal
    it. Keeps no raw dump beyond the open frame, the open events and the
    carried values."""

    def __init__(self, out: Path, names: Sequence[str],
                 p: Optional['Places'] = None, run: Optional[str] = None):
        self.out = out
        self.run = run or out.name
        self.names = list(names)
        self.places = p or places()
        self.store = BlobStore(out)
        self.pack = Pack(out / 'cases.pack')
        self.frame: Optional[List[Dump]] = None
        self.events: List[List[Dump]] = []
        self.loose: List[Dump] = []     # dumps outside frames and events
        self.frames: List[Dict[str, Any]] = []
        self.eventlist: List[Dict[str, Any]] = []
        self.problems: List[str] = []
        self.end: Optional[Dict] = None
        self.count = 0
        self.carry: Dict[str, Optional[bytes]] = {
            n: None for n, _, _ in self.places.carried}
        self.carry_from: Dict[str, str] = {
            n: 'none' for n, _, _ in self.places.carried}
        self.start: Dict[str, Optional[bytes]] = {}
        self.carry_checks = 0           # PDX samples equal to the carried
        self.stray_returns = 0          # a PU1 reached by another path
        self.static_frames = 0          # PD1 with no frame open
        self.open_at_end = False
        self.lazy_ends = 0
        self.by_point: Dict[str, int] = {}
        self.pdx_inside = 0
        self.just_started = False
        self.last_static: Optional[Tuple[bytes, int]] = None
        self.merged = 0

    def range_of(self, name: str) -> Tuple[int, int]:
        for n, r, _ in self.places.carried:
            if n == name:
                return r
        raise KeyError(name)

    def feed(self, handle) -> None:
        stream = dumps.Stream.__new__(dumps.Stream)
        stream.info, stream.end = {}, None
        for d in dumps.read(handle, stream):
            self.count += 1
            name = self.names[d.header['point']]
            self.by_point[name] = self.by_point.get(name, 0) + \
                len(d.data) + 300
            head = {k: d.header[k] for k in DUMP_KEYS if k in d.header}
            self.take(Dump(name, head, tuple(tuple(r) for r in
                                             d.header['ranges']), d.data))
        self.end = stream.end
        if self.frame is not None and self.frame[0].point != 'PD0:display':
            self.close_frame()
        if self.frame is not None:
            self.open_at_end = True     # the script's stop, inside a frame

    def where(self) -> str:
        return 'frame %d' % len(self.frames) if self.frame is not None \
            else 'after frame %d' % (len(self.frames) - 1)

    def take(self, d: Dump) -> None:
        kind = d.point.split(':')[0]
        started, self.just_started = self.just_started, False
        if self.frame is not None and self.frame[0].point != 'PD0:display' \
                and kind in ('PD0', 'PD1', 'PU0', 'PU1'):
            self.close_frame()          # a menu frame ends where the next
                                        #   thing begins
        elif self.frame is not None and d.point in ('PD0:display',
                                                    'PD0:menu'):
            # display's frame whose PD1 did not fire: a menu opened in it
            # (uiOpen changed displayCall's operand, PD1's test); the
            # menu pauses the tics, so nothing came between its end and
            # this start
            self.lazy_ends += 1
            self.close_frame()
        if kind == 'PD0':
            if self.frame is not None:  # (display's own static check:
                return                  #   staticUpToDate's skull path)
            self.frame = [d]
            self.just_started = True
            self.start = dict(self.carry)
            self.start_from = dict(self.carry_from)
        elif kind == 'PDX':
            if not started:
                self.pdx_inside += 1        # a check point inside a frame
                return                      #   (the carried may be stale)
            for n, r, _ in self.places.carried:
                value = d.get(*r)
                old = self.carry[n]
                if old is not None and old != value:
                    diff = sum(1 for x, y in zip(value, old) if x != y)
                    self.problems.append(
                        'frame %d: %s at its start differs from the value '
                        '%s left in %d bytes' % (len(self.frames), n,
                                                 self.carry_from[n], diff))
                elif old is not None:
                    self.carry_checks += 1
                self.carry[n] = self.start[n] = value
                self.carry_from[n] = self.start_from[n] = 'PDX'
        elif kind == 'PC':
            name = d.point.split(':')[1]
            self.carry[name] = d.get(*self.range_of(name))
            self.carry_from[name] = '%s (%s)' % (d.point, self.where())
            self.hold(d)
        elif kind == 'PD1':
            if self.frame is None:
                self.static_frames += 1     # a menu frame that wrote nothing
                return
            self.frame.append(d)
            self.close_frame()
        elif kind == 'PU0':
            names = [n for n, _, _ in self.places.carried if n != 'SCREEN']
            if all(self.carry[n] is not None for n in names):
                cb = self.carried_dump('CB', self.carry, names,
                                       self.carry_from)
                self.events.append([d, cb])
            else:
                self.events.append([d])
        elif kind == 'PU1':
            site = d.point.split(':', 1)[1]
            if not self.events or \
                    self.events[-1][0].point.split(':', 1)[1] != site:
                self.stray_returns += 1     # its return address is also a
                return                      # branch target: not a return
            ev = self.events.pop()
            ev.append(d)
            self.carry['SCREEN'] = d.get(*SCREEN)
            self.carry_from['SCREEN'] = d.point
            self.close_event(ev)
        else:                           # PDA, PV, PM, PDF, PDS, PW
            self.hold(d)

    def hold(self, d: Dump) -> None:
        for holder in (self.events[-1] if self.events else None,
                       self.frame):
            if holder is not None:
                holder.append(d)
        if not self.events and self.frame is None:
            self.loose.append(d)

    def carried_dump(self, name: str, values: Dict[str, Optional[bytes]],
                     names: Sequence[str], frm: Dict[str, str]) -> Dump:
        rs = tuple(self.range_of(n) for n in names)
        return Dump(name, {'names': list(names),
                           'from': {n: frm[n] for n in names}}, rs,
                    b''.join(values[n] for n in names))

    def close_frame(self) -> None:
        fr = self.frame
        self.frame = None
        k = len(self.frames)
        name = 'f%06d' % k
        missing = [n for n, v in self.start.items() if v is None]
        if missing:
            self.problems.append('frame %d: no %s at its start'
                                 % (k, ', '.join(missing)))
            return
        pvs = [x for x in fr if x.point == 'PV']
        if len(pvs) > 1:
            self.problems.append('frame %d: %d PV' % (k, len(pvs)))
        menu = any(x.point == 'PM' for x in fr)
        paused = bool(pvs) and pvs[0].word(self.places.pv[3][0]) != 0
        rows = x1_rows(pvs[0], self.places) \
            if pvs and not menu and not paused else []
        order = [n for n, _, _ in self.places.carried]
        cb = self.carried_dump('CB', self.start, order, self.start_from)
        changed = [n for n in order if self.carry[n] != self.start[n]]
        dlist = [fr[0], blanked(cb, rows)]
        if changed:
            dlist.append(blanked(self.carried_dump(
                'CA', self.carry, changed, self.carry_from), rows))
        dlist += [blanked(x, rows) if x.point.startswith(('PW', 'PC:SCREEN'))
                  else x for x in fr[1:] if not x.point.startswith('PDX')]
        # a frame that wrote nothing (its start, its end) and whose start
        # is the frame before's, which was the same: one case, repeated
        if [x.point.split(':')[0] for x in dlist] == ['PD0', 'CB', 'PD1'] \
                and not self.loose and not changed:
            key = hashlib.sha256(fr[0].point.encode() + fr[0].data +
                                 cb.data + fr[-1].data).digest()
            if self.last_static is not None and self.last_static[0] == key:
                entry = self.frames[self.last_static[1]]
                entry['repeat'] += 1
                entry['cycles_last'] = fr[-1].head['cycles']
                self.merged += 1
                return
            self.last_static = (key, k)
        else:
            self.last_static = None
        head = {'run': self.run, 'kind': 'frame', 'index': k,
                'cycles': [fr[0].head['cycles'], fr[-1].head['cycles']],
                'frame': fr[0].head['frame'], 'note': fr[0].head['note'],
                'blank': rows, 'changed': changed,
                'loose_before': [x.point for x in self.loose]}
        self.loose = []
        blob = encode_case(head, dlist, self.store)
        at, _ = self.pack.add(blob)
        self.frames.append({'name': name, 'at': at,
                            'cycles': head['cycles'],
                            'frame': head['frame'], 'note': head['note'],
                            'points': [x.point for x in dlist],
                            'blank': rows, 'bytes': len(blob),
                            'repeat': 1,
                            'sha256': hashlib.sha256(blob).hexdigest()})

    def close_event(self, ev: List[Dump]) -> None:
        k = len(self.eventlist)
        name = 'e%05d' % k
        routine, site = ev[0].point.split(':')[1:3]
        head = {'run': self.run, 'kind': 'event', 'index': k,
                'routine': routine, 'site': site,
                'cycles': [ev[0].head['cycles'], ev[-1].head['cycles']],
                'in_frame': len(self.frames) if self.frame is not None
                else None}
        blob = encode_case(head, ev, self.store)
        at, _ = self.pack.add(blob)
        self.eventlist.append({'name': name, 'at': at, 'routine': routine,
                               'site': site, 'cycles': head['cycles'],
                               'in_frame': head['in_frame'],
                               'bytes': len(blob),
                               'sha256': hashlib.sha256(blob).hexdigest()})


class CallSink:
    """The call log read from its pipe: every line kept (they are small),
    each routine's calls counted."""

    def __init__(self):
        self.head: Optional[Dict] = None
        self.lines: List[Dict] = []
        self.end: Optional[Dict] = None

    def feed(self, handle) -> None:
        first = handle.readline()
        if not first:
            raise CapError('the call log is empty')
        self.head = json.loads(first)
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
            raise CapError('the call log ends without its last line')


# ---------------------------------------------------------------------------
# A capture
# ---------------------------------------------------------------------------

def capture(run: str, out: Path, work_root: Path = WORK,
            jumps_update: bool = True, point_hook=None,
            pokes: Optional[Path] = None,
            script_path: Optional[Path] = None) -> Dict[str, Any]:
    """Capture `run` into out (a directory of its own, emptied first).
    point_hook(points) may change the points (the planted bugs). The
    run's index."""
    check_disk(BUILD)
    if out.exists():
        shutil.rmtree(str(out))
    out.mkdir(parents=True)
    work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='cap-%s-' % run, dir=str(work_root)))
    try:
        p = places()
        pts = points(p, screens=run not in SOUND_ONLY)
        if point_hook is not None:
            pts = point_hook(pts, p)
        logged = routines(jumps_update)
        dist = Distiller(out, [x.name for x in pts], p, run)
        sink = CallSink()
        traffic = Traffic()
        try:
            result = machine(run, work, pts, logged, dist.feed, sink.feed,
                             pokes=pokes, traffic=traffic,
                             script_path=script_path)
        except CapError as error:
            top = sorted(dist.by_point.items(), key=lambda x: -x[1])[:6]
            raise CapError('%s (the dumps by point: %s; the call log: %d '
                           'lines)' % (error, ', '.join(
                               '%s %d MB' % (n, b // 10 ** 6)
                               for n, b in top), len(sink.lines)))
        names = [n for n, _ in logged]
        calls = distil_calls(sink, names)
        blob = zlib.compress(calls, 6)
        write_atomic(out / 'calls.z', blob)
        if dist.end is None and pts:
            dist.problems.append('the dump stream had no end line')
        index = {
            'format': INDEX_FORMAT, 'run': run, 'script': result['script'],
            'points': [{'name': x.name, 'text': x.text} for x in pts],
            'routines': [{'name': n, 'text': t} for n, t in logged],
            'frames': dist.frames, 'events': dist.eventlist,
            'loose_after': [x.point for x in dist.loose],
            'calls': {'file': 'calls.z', 'bytes': len(blob),
                      'sha256': hashlib.sha256(blob).hexdigest(),
                      'count': len(sink.lines),
                      'arrivals': sink.end.get('arrivals') if sink.end
                      else None},
            'dumps': dist.count, 'traffic': result['traffic'],
            'traffic_by_point': dist.by_point,
            'carry_checks': dist.carry_checks,
            'static_frames': dist.static_frames,
            'open_at_end': dist.open_at_end,
            'lazy_ends': dist.lazy_ends,
            'merged_frames': dist.merged, 'pdx_inside': dist.pdx_inside,
            'stray_returns': dist.stray_returns,
            'blobs': {'count': len(dist.store.keys),
                      'bytes': dist.store.pack.size,
                      'keys': dist.store.keys},
            'cases_bytes': dist.pack.size,
            'problems': result['problems'] + dist.problems,
            'end': result['state'].get('end'),
            'seconds': result['state'].get('seconds'),
        }
        write_atomic(out / 'index.json',
                     json.dumps(index, indent=1, sort_keys=True).encode())
        return index
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def distil_calls(sink: CallSink, names: Sequence[str]) -> bytes:
    """The call log as JSON lines: the routines' names, then each call
    (its routine by name, the registers, the memory as hex)."""
    out = [json.dumps({'format': CALLS_FORMAT, 'routines': list(names),
                       'head': sink.head}, sort_keys=True)]
    for c in sink.lines:
        c = dict(c)
        c['name'] = names[c['routine']]
        out.append(json.dumps(c, sort_keys=True, separators=(',', ':')))
    out.append(json.dumps(sink.end, sort_keys=True))
    return ('\n'.join(out) + '\n').encode()


class Calls(NamedTuple):
    names: List[str]
    lines: List[Dict[str, Any]]

    def of(self, name: str) -> List[Dict[str, Any]]:
        return [c for c in self.lines if c['name'] == name]


def load_calls(path: Path) -> Calls:
    text = zlib.decompress(Path(path).read_bytes()).decode()
    rows = text.splitlines()
    head = json.loads(rows[0])
    if head.get('format') != CALLS_FORMAT:
        raise ValueError('not an s2cap call file')
    return Calls(head['routines'], [json.loads(r) for r in rows[1:-1]])


def mem_of(call: Dict[str, Any], which: str = 'in') -> List[bytes]:
    side = call.get(which) or {}
    return [bytes.fromhex(m) for m in side.get('mem', [])]


def run_dir(run: str, root: Path = CASES) -> Path:
    return root / run


def read_index(run: str, root: Path = CASES) -> Dict[str, Any]:
    return json.loads((run_dir(run, root) / 'index.json').read_text())


def tree_size(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file())


def capture_all(runs: Sequence[str], root: Path = CASES, jobs: int = JOBS
                ) -> Dict[str, Dict[str, Any]]:
    print(df_report(), flush=True)
    check_disk(BUILD)
    results: Dict[str, Dict[str, Any]] = {}

    def one(run: str) -> Tuple[str, Dict[str, Any]]:
        return run, capture(run, root / run)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for run, idx in pool.map(one, runs):
            results[run] = idx
            print('%s: %d frames, %d events, %d calls, %.1f MB of pipes, '
                  '%d problems' % (run, len(idx['frames']),
                                   len(idx['events']), idx['calls']['count'],
                                   idx['traffic'] / 1e6,
                                   len(idx['problems'])), flush=True)
    size = tree_size(root)
    if size > CASES_LIMIT:
        raise CapError('the cases take %d bytes (limit %d)' % (size,
                                                               CASES_LIMIT))
    return results


# ---------------------------------------------------------------------------
# The scripts' goals: what each names, checked on the captured state
# ---------------------------------------------------------------------------

MENU_ITEMS = {0: 6, 2: 5, 4: 8, 6: 5, 8: 11, 10: 8, 12: 3, 16: 5}
MESSAGES = (0, 4, 8, 12)        # NIGHTMARE, QUIT, ENDGAME, SAVEDEAD
TINTS = {'red': range(1, 9), 'bonus': range(9, 13), 'radiation': (13,)}
PL_OFS = {'health': 35, 'armorpoints': 37, 'powers': 41, 'cards': 53,
          'backpack': 59, 'readyweapon': 61, 'weaponowned': 65, 'ammo': 83,
          'maxammo': 91, 'cheats': 103, 'damagecount': 117,
          'bonuscount': 119}    # offsets.inc OFS_PL_* (s2state reads it)
AMMO_CLASSES = (0, 9, 10, 99, 100, 200, 400)


def _pl(d: Dump, field: str, i: int = 0) -> int:
    return d.word(sym('_g_player') + PL_OFS[field] + 2 * i)


def _goal(out: List[str], ok: bool, what: str) -> None:
    out.append(('ok ' if ok else 'missed ') + what)


def goals_check(run: str, rc: 'RunCases') -> List[str]:
    """Each of the script's named pages, modes, messages and value
    classes reached, on the frames' state at their start (PD0), their
    dumps and the events (6.1, the checkpoint)."""
    frames = [c for _, c in rc.frames()]
    events = [(e, c) for e, c in rc.events()]
    starts = [c.before for c in frames]
    out: List[str] = []
    if run == 'menus':
        seen: Dict[int, set] = {}
        kinds = set()
        for b in starts:
            if val(b, '_g_menuactive'):
                seen.setdefault(val(b, 'm_menu65.s:currentMenu'),
                                set()).add(val(b, 'm_menu65.s:itemOn'))
            if val(b, 'm_menu65.s:messageToPrint'):
                kinds.add(val(b, 'm_menu65.s:messageKind'))
        for m, n in sorted(MENU_ITEMS.items()):
            _goal(out, set(range(n)) <= seen.get(m, set()),
                  'menu %d, its %d rows (seen %s)' % (
                      m, n, sorted(seen.get(m, set()))))
        for k in MESSAGES:
            _goal(out, k in kinds, 'message kind %d' % k)
        kt = sym('i_iigs65.s:keyTable')
        tables = [b.get(kt, 256) for b in starts]
        changed = [i for i, t in enumerate(tables) if t != tables[0]]
        _goal(out, bool(changed) and tables[-1] == tables[0] and
              any(tables[i] == tables[0] for i in range(changed[0],
                                                       len(tables))),
              'a binding changed and the defaults back')
        _goal(out, any(val(b, 'i_iigs65.s:iigs_bindwait') for b in starts),
              'the key setup waiting for a key')
        _goal(out, any(c.one('PM') is not None and
                       val(c.before, '_g_gamestate') == 0 for c in frames),
              'the menu opened over the view (the gray view)')
        ingame = [b for b in starts if val(b, '_g_usergame') and
                  val(b, '_g_gamestate') == 0]
        _goal(out, {0, 1} <= {val(b, 'm_menu65.s:showMessages')
                              for b in ingame}, 'messages off and on')
        _goal(out, any(val(b, 'hu_stuff65.s:message_on') for b in ingame),
              'the HUD\'s message on')
    elif run == 'automap':
        modes = [val(b, 'am_map65.s:automapmode') for b in starts]
        full = [b for b, m in zip(starts, modes)
                if m & (AM_ACTIVE | AM_OVERLAY) == AM_ACTIVE]
        _goal(out, bool(full), 'the full map')
        _goal(out, any(m & (AM_ACTIVE | AM_OVERLAY) == AM_ACTIVE |
                       AM_OVERLAY for m in modes), 'the overlay')
        _goal(out, any(m & 8 == 0 for m in modes if m & 1) and
              any(m & 8 for m in modes if m & 1), 'follow off and on')
        _goal(out, len({b.get(sym('am_map65.s:scale_mtof'), 4)
                        for b in full}) >= 3, 'zoomed out and in')
        _goal(out, len({b.get(sym('am_map65.s:m_x'), 4) for b, m in
                        zip(starts, modes) if m & 9 == 1}) >= 2,
              'panned with follow off')
        _goal(out, any(_pl(b, 'powers', 4) for b in starts),
              'the computer map (powers[pw_allmap])')
        _goal(out, any(c.one('PV') is not None and
                       val(c.one('PV'), 'am_map65.s:automapmode') & 3 == 3
                       for c in frames), 'a view rendered with the overlay')
        _goal(out, modes[-1] == 0 and any(modes), 'the map off at the end')
    elif run == 'palette':
        gammas = {val(b, 'm_menu65.s:_g_gamma') for b in starts
                  if not val(b, '_g_menuactive') and
                  val(b, '_g_gamestate') == 0}
        _goal(out, gammas >= {0, 1, 2, 3, 4},
              'gamma 0-4 with the view on screen (seen %s)' % sorted(gammas))
        tints = {val(d, 'i_viigs65.s:curtint') for c in frames
                 for d in c.all('PDF')}
        for name, rng in TINTS.items():
            _goal(out, bool(tints & set(rng)), 'the %s tint' % name)
    elif run == 'finale':
        _goal(out, any(val(b, '_g_gamestate') == 2 for b in starts),
              'the finale')
        stages = {val(b, 'f_finale65.s:finalestage') for b in starts
                  if val(b, '_g_gamestate') == 2}
        _goal(out, {0, 1} <= stages, 'the text and the picture')
        _goal(out, any(val(b, 'f_finale65.s:midstage') for b in starts),
              'the text accelerated (the mid stage)')
        _goal(out, bool(rc.calls().of('F_Ticker')), 'F_Ticker logged')
    elif run == 'signs':
        names = {e['routine'] for e, _ in events}
        _goal(out, bool(names & {'bmSignLoading', 'bmSignOn'}),
              'the busy sign (%s)' % sorted(names))
        _goal(out, 'F_LoadScreen' in names, 'the world-done load')
        _goal(out, any(c.screen_before != c.screen_after for e, c in events
                       if e['routine'] in ('bmSignLoading', 'bmSignOn')),
              'the sign drawn')
    elif run == 'stbar':
        for i in range(3):
            _goal(out, any(_pl(b, 'cards', i) for b in starts), 'key %d' % i)
        for i in range(9):
            _goal(out, any(_pl(b, 'weaponowned', i) for b in starts),
                  'arm %d owned' % i)
        ready = {_pl(b, 'readyweapon') for b in starts}
        _goal(out, ready >= set(range(6)), 'ready weapons 0-5 (the fist: '
              'LARGEAMMO)')
        for v in AMMO_CLASSES:
            _goal(out, any(all(_pl(b, 'ammo', i) == v for i in range(4))
                           for b in starts), 'ammo %d' % v)
            _goal(out, any(all(_pl(b, 'maxammo', i) == v for i in range(4))
                           for b in starts), 'maxammo %d' % v)
        for v in (0, 100, 200):
            _goal(out, any(_pl(b, 'health') == v for b in starts),
                  'health %d' % v)
        for v in (0, 200):
            _goal(out, any(_pl(b, 'armorpoints') == v for b in starts),
                  'armour %d' % v)
        _goal(out, any(_pl(b, 'cheats') & 2 for b in starts), 'god mode')
        _goal(out, any(_pl(b, 'backpack') for b in starts), 'the backpack')
        _goal(out, any(_pl(b, 'damagecount') for b in starts),
              'the pain face (damagecount)')
        _goal(out, any(_pl(b, 'bonuscount') for b in starts),
              'the evil grin (a new weapon, bonuscount)')
    return out


# ---------------------------------------------------------------------------
# The checks (the checkpoint of SCREENS.md 7.3, part s2cap)
# ---------------------------------------------------------------------------

def val(d: Dump, name: str, size: int = 2) -> int:
    return d.word(sym(name), size)


def level_frame(case: Case) -> Optional[bool]:
    """Whether display drew the view this frame (6.1's "level frame"):
    display's frame, gametic != basetic at its start, and at I_FinishUpdate
    gamestate GS_LEVEL, DD_VIEW 1, DD_PAUSED 0. None for a paused frame
    (the menu's render of the view under it may or may not come)."""
    if case.head['kind'] != 'frame' or case.before.point != 'PD0:display':
        return False
    b = case.before
    if val(b, '_g_gametic', 4) == val(b, '_g_basetic', 4):
        return False
    pdf = case.one('PDF')
    if pdf is None:
        return False
    if val(pdf, 'd_main65.s:DD_PAUSED'):
        return None
    return val(pdf, '_g_gamestate') == 0 and \
        val(pdf, 'd_main65.s:DD_VIEW') == 1


def check_frames(rc: 'RunCases') -> Dict[str, Any]:
    """Every case decodes; PV in every level frame and its VIEWTOP rule."""
    out: Dict[str, Any] = {'frames': 0, 'events': 0, 'repeats': 0,
                           'level': 0, 'paused': 0, 'pv': 0,
                           'decode_problems': [], 'pv_problems': []}
    for e, case in rc.frames():
        out['frames'] += 1
        out['repeats'] += e.get('repeat', 1)
        try:
            for name in ('SCREEN', 'STCACHE', 'TINTPAL', 'AMLISTS'):
                case.carried(name)
                case.carried(name, after=True)
            for o in case.blank_offsets():
                if case.screen_after[o] or case.screen_before[o]:
                    raise ValueError('a blank row is not zero')
        except (KeyError, ValueError) as error:
            out['decode_problems'].append('%s: %s' % (e['name'], error))
            continue
        pvs = case.all('PV')
        out['pv'] += len(pvs)
        lv = level_frame(case)
        if lv is None:
            out['paused'] += 1
            continue
        if lv:
            out['level'] += 1
            if len(pvs) != 1:
                out['pv_problems'].append('%s: a level frame with %d PV'
                                          % (e['name'], len(pvs)))
                continue
            pv = pvs[0]
            top = val(pv, 'r_state65.s:viewtop')
            msg = val(pv, 'hu_stuff65.s:message_on')
            if top != (STRIP_TOP if msg else 0xFFFF):
                out['pv_problems'].append(
                    '%s: viewtop $%04X with message_on %d' % (e['name'], top,
                                                             msg))
        elif pvs:
            out['pv_problems'].append('%s: PV in a frame that is not a '
                                      'level frame' % e['name'])
    for e, case in rc.events():
        out['events'] += 1
        if case.before.get(*SCREEN) is None:
            out['decode_problems'].append(e['name'])
    return out


STRIP_TOP = 9                   # viewtop with the message strip [R d_main65.s:472]


def check_sounds(calls: Calls, sound_run: bool) -> Dict[str, Any]:
    """S_UpdateSounds once in every main-loop turn where the player has a
    mobj (musFrame, before displayCall), none in the others; isPlaying
    called under it once for each channel with a sound."""
    frames = sorted(calls.of('display'), key=lambda c: c['cycles'])
    ups = sorted(calls.of('S_UpdateSounds'), key=lambda c: c['cycles'])
    out: Dict[str, Any] = {'turns': len(frames), 'with_mobj': 0,
                           'updates': len(ups), 'problems': []}
    j = 0
    prev = -1
    for f in frames:
        c = f['cycles']
        n = 0
        while j < len(ups) and ups[j]['cycles'] < c:
            if ups[j]['cycles'] > prev:
                n += 1
            j += 1
        prev = c
        mo = int.from_bytes(mem_of(f)[0], 'little')
        menu = int.from_bytes(mem_of(f)[1], 'little')
        want = 1 if mo and not menu else 0
        out['with_mobj'] += want
        if n != want and len(out['problems']) < 20:
            out['problems'].append('the turn at cycle %d: %d S_UpdateSounds '
                                   'with mo $%06X' % (c, n, mo))
        elif n != want:
            out['problems'].append('...')
    by_parent: Dict[int, int] = {}
    for c in calls.of('isPlaying'):
        by_parent[c['parent']] = by_parent.get(c['parent'], 0) + 1
    bad = 0
    for u in ups:
        ch = mem_of(u)[0][:16]
        active = sum(1 for i in range(0, 16, 2) if ch[i] | ch[i + 1])
        if by_parent.get(u['call'], 0) != active:
            bad += 1
    if bad:
        out['problems'].append('%d S_UpdateSounds whose isPlaying calls are '
                               'not their channels with a sound' % bad)
    for name in ('isPlaying', 'docVolume', 'stopChannel', 'startSound',
                 'adjustParams', 'S_StartSound', 'S_StartSound2',
                 'S_StopSound'):
        out[name] = len(calls.of(name))
    # the tic points (6.1): HU_Ticker follows ST_Ticker in every level tic
    out['ST_Ticker'] = len(calls.of('ST_Ticker'))
    out['HU_Ticker'] = len(calls.of('HU_Ticker'))
    out['F_Ticker'] = len(calls.of('F_Ticker'))
    if out['ST_Ticker'] != out['HU_Ticker']:
        out['problems'].append('%d ST_Ticker but %d HU_Ticker' % (
            out['ST_Ticker'], out['HU_Ticker']))
    if sound_run and not (ups and out['isPlaying'] and out['docVolume'] and
                          out['stopChannel']):
        out['problems'].append('a sound run without S_UpdateSounds, '
                               'isPlaying, docVolume and stopChannel')
    return out


def check_injection(rc: 'RunCases', every: int = 1) -> Dict[str, Any]:
    """Each case (every `every`-th frame and every event) injected for
    each screen, both fills, plain and poisoned, and read back equal on
    the host; the poisoned screen checked."""
    from native import s2state as ST
    out: Dict[str, Any] = {'injections': 0, 'problems': [], 'unfit': {},
                           'deferred': set()}
    todo = [x for i, x in enumerate(rc.frames()) if i % every == 0] + \
        list(rc.events())
    for e, case in todo:
        hit = set(ST.marked(case)) | set(case.blank_offsets())
        for screen in ST.SCREENS:
            for fill in (0xA5, 0x5A):
                for poison in (False, True):
                    inj = ST.inject(case, screen, fill, poison)
                    h = ST.host_of(inj)
                    diff = ST.read_back(h.get, inj)
                    if poison:
                        diff += ST.poison_problems(h.get, case, inj, hit)
                    out['injections'] += 1
                    for ref, v, enc in inj.unfit:
                        out['unfit'].setdefault(ref, [enc, v])
                    out['deferred'].update(r for r, _ in inj.deferred)
                    if diff and len(out['problems']) < 20:
                        out['problems'].append('%s %s %02X%s: %s' % (
                            e['name'], screen, fill, ' poisoned' if poison
                            else '', '; '.join(diff[:3])))
    out['deferred'] = sorted(out['deferred'])
    return out


def a2vm_injection(rc: 'RunCases', picks: Sequence[int],
                   work_root: Path = WORK) -> Dict[str, Any]:
    """The injection on a2vm: part s2lay's test image (s2lt, read only)
    under the test driver with an empty call list, each picked frame's
    records for every screen, both fills, poisoned; the whole machine at
    the driver's stop read back equal (the records reach a2vm's machine
    and nothing of the run moves them)."""
    from native import s2run as SR, s2state as ST
    out: Dict[str, Any] = {'runs': 0, 'problems': []}
    obj = M11 / 's2lay'
    if not (obj / 's2lt.map').exists():
        out['problems'].append('no %s/s2lt (make -C src/native -f m11.mk '
                               'part P=s2lay)' % obj)
        return out
    b = SR.load_build(obj, 's2lt', 'P2DW')
    work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='inj-', dir=str(work_root)))
    try:
        for k in picks:
            case = rc.frame(k)
            for fill in SR.FILLS:
                injs = [ST.inject(case, scr, fill, poison=True)
                        for scr in ST.SCREENS]
                recs: List[Any] = []
                for inj in injs:
                    recs += inj.records
                r = SR.run(b, [], fill, work / ('%d-%02x' % (k, fill)),
                           extra_records=recs, whole=True, write_log=False)
                out['runs'] += 1
                if r.ended() != 'stop':
                    out['problems'].append('frame %d: the run ended %s'
                                           % (k, r.ended()))
                    continue
                m = SR.read_snapshot(r.work / 'stop.img')
                get = ST.snapshot_getter(m)
                for inj in injs:
                    diff = ST.read_back(get, inj) + \
                        ST.poison_problems(get, case, inj)
                    if diff:
                        out['problems'].append('frame %d %s %02X: %s' % (
                            k, inj.screen, fill, '; '.join(diff[:3])))
                shutil.rmtree(str(r.work), ignore_errors=True)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return out


def frame_calls(calls: Calls) -> List[Dict[str, Any]]:
    return sorted(calls.of('display'), key=lambda c: c['cycles'])


def two_run(run: str, rc: 'RunCases', n: int, work_root: Path = WORK
            ) -> Dict[str, Any]:
    """The two-run method on n frames with marked bytes: a run to the
    cycle count where the frame's display (or menuDisplayNear) returned
    (the call log's), with --save of the screen; its screen must equal
    the case's at the frame's end outside the undefined rows, and one of
    them must differ from the frame's start (the check has teeth)."""
    from native import s2state as ST
    out: Dict[str, Any] = {'checked': 0, 'problems': [], 'teeth': 0}
    if run in SOUND_ONLY or n <= 0:
        return out
    fcalls = frame_calls(rc.calls())
    ins = [c['cycles'] for c in fcalls]
    y0, y1 = sym('i_viigs65.s:DRY0'), sym('i_viigs65.s:DRY1')
    eligible = []
    for e in rc.index['frames']:
        if 'PDF' not in e['points'] or e['points'][0] != 'PD0:display':
            continue
        case = rc.load(e)
        pdf = case.one('PDF')
        if pdf.word(y0) >= pdf.word(y1):
            continue
        c0 = e['cycles'][0]     # (PD0 at displayCall's JSR: display's
        k = max((i for i, x in enumerate(ins) if x <= c0 + 64),  # entry
                default=None)                           # a few cycles on)
        if k is None or not c0 <= ins[k] or \
                not fcalls[k].get('returned'):
            continue
        eligible.append((e, fcalls[k]['out']['cycles'],
                         len(ST.marked(case))))
    if not eligible:
        out['problems'].append('no frame with marked bytes to check')
        return out
    # the frames that mark the most bytes (PDF's marks: I_FinishUpdate is
    # about to copy them), so the check has teeth; then the first
    picks = sorted(range(1, len(eligible)), key=lambda i: (
        -eligible[i][2], i))[:max(n - 1, 1)]
    picks = sorted(set(picks) | ({0} if n > 1 or not picks else set()))
    work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='tworun-%s-' % run,
                                 dir=str(work_root)))
    try:
        for i in picks:
            e, cycles, _ = eligible[i]
            saved = work / 'screen.bin'
            if saved.exists():
                saved.unlink()
            machine(run, work, [], [], None, None, extra=[
                '--cycles', str(cycles), '--save',
                'E12000:32768:%s' % saved])
            got = saved.read_bytes()
            case = rc.load(e)
            blank = set(case.blank_offsets())
            after = case.screen_after
            diff = [o for o in range(len(got)) if o not in blank and
                    got[o] != after[o]]
            if diff:
                out['problems'].append('%s: %d bytes differ from the run to '
                                       'cycle %d (first $%04X)' % (
                                           e['name'], len(diff), cycles,
                                           0x2000 + diff[0]))
            if any(got[o] != case.screen_before[o] for o in range(len(got))
                   if o not in blank):
                out['teeth'] += 1
            out['checked'] += 1
        if not out['teeth']:
            out['problems'].append('no checked frame changed the screen')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return out


def same_capture(a: Path, b: Path) -> List[str]:
    """Two captures of a run: every file byte for byte."""
    out = []
    names = sorted({p.name for p in a.iterdir()} | {p.name for p in
                                                    b.iterdir()})
    for n in names:
        pa, pb = a / n, b / n
        if not pa.exists() or not pb.exists():
            out.append('%s is in one capture only' % n)
        elif hashlib.sha256(pa.read_bytes()).digest() != \
                hashlib.sha256(pb.read_bytes()).digest():
            out.append('%s differs' % n)
    return out


def check_run(run: str, root: Path = CASES, twice: bool = False,
              two_runs: int = 3, inject_every: int = 1) -> Dict[str, Any]:
    rc = RunCases(root / run)
    idx = rc.index
    rep: Dict[str, Any] = {'run': run, 'capture_problems': idx['problems'],
                           'traffic': idx['traffic'],
                           'carry_checks': idx['carry_checks']}
    rep['frames'] = check_frames(rc)
    rep['sounds'] = check_sounds(rc.calls(), True)
    rep['injection'] = check_injection(rc, inject_every)
    if run not in SOUND_ONLY and rc.index['frames']:
        n = len(rc.index['frames'])
        rep['a2vm_injection'] = a2vm_injection(rc, sorted({0, n // 2}))
    else:
        rep['a2vm_injection'] = {'runs': 0, 'problems': []}
    rep['two_run'] = two_run(run, rc, two_runs)
    rep['goals'] = goals_check(run, rc) if run in SCRIPTS else []
    if twice:
        scratch = WORK / ('twice-' + run)
        try:
            capture(run, scratch)
            rep['twice'] = same_capture(root / run, scratch)
        finally:
            shutil.rmtree(str(scratch), ignore_errors=True)
    probs = []
    probs += ['capture: ' + x for x in idx['problems']]
    probs += rep['frames']['decode_problems'] + rep['frames']['pv_problems']
    probs += ['sounds: ' + x for x in rep['sounds']['problems']]
    probs += ['inject: ' + x for x in rep['injection']['problems']]
    probs += ['inject on a2vm: ' + x for x in
              rep['a2vm_injection']['problems']]
    probs += ['two-run: ' + x for x in rep['two_run']['problems']]
    probs += ['goal: ' + x for x in rep['goals'] if not x.startswith('ok ')]
    probs += ['twice: ' + x for x in rep.get('twice', [])]
    rep['problems'] = probs
    return rep


def check_all(runs: Sequence[str], root: Path = CASES, twice: bool = False,
              two_run: int = 3, jobs: int = JOBS) -> Dict[str, Any]:
    """check_run for each run (jobs at once), the cases' total size; the
    report in build/native/m11/s2cap/report.json."""
    reports: Dict[str, Dict[str, Any]] = {}

    def one(run: str) -> Tuple[str, Dict[str, Any]]:
        return run, check_run(run, root, twice=twice, two_runs=two_run)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for run, rep in pool.map(one, runs):
            reports[run] = rep
            print('%s: %d problems' % (run, len(rep['problems'])),
                  flush=True)
    size = tree_size(root)
    summary = {'cases_bytes': size, 'cases_limit': CASES_LIMIT,
               'runs': {}}
    ok = size <= CASES_LIMIT
    for run, rep in reports.items():
        f, snd = rep['frames'], rep['sounds']
        summary['runs'][run] = {
            'frames': f['frames'], 'repeats': f['repeats'],
            'events': f['events'], 'level_frames': f['level'],
            'pv': f['pv'], 'paused': f['paused'],
            'turns': snd['turns'], 'S_UpdateSounds': snd['updates'],
            'isPlaying': snd['isPlaying'], 'docVolume': snd['docVolume'],
            'stopChannel': snd['stopChannel'],
            'S_StartSound': snd['S_StartSound'],
            'S_StartSound2': snd['S_StartSound2'],
            'S_StopSound': snd['S_StopSound'],
            'ST_Ticker': snd['ST_Ticker'], 'HU_Ticker': snd['HU_Ticker'],
            'F_Ticker': snd['F_Ticker'],
            'injections': rep['injection']['injections'],
            'a2vm_injections': rep['a2vm_injection']['runs'],
            'unfit': rep['injection']['unfit'],
            'two_run': rep['two_run'].get('checked', 0),
            'carry_checks': rep['carry_checks'],
            'traffic_MB': round(rep['traffic'] / 1e6, 1),
            'goals': len(rep['goals']),
            'twice': 'same' if twice and not rep.get('twice') else
            rep.get('twice', 'not run'),
            'problems': rep['problems']}
        ok = ok and not rep['problems']
    deferred = sorted({d for r in reports.values()
                       for d in r['injection']['deferred']})
    summary['deferred'] = deferred
    out = {'ok': ok, 'summary': summary}
    WORK.mkdir(parents=True, exist_ok=True)
    write_atomic(WORK / 'report.json', json.dumps(out, indent=1,
                                                  sort_keys=True).encode())
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--points', action='store_true')
    parser.add_argument('--runs', default=','.join(RUNS))
    parser.add_argument('--out', type=Path, default=CASES)
    parser.add_argument('--jobs', type=int, default=JOBS)
    parser.add_argument('--twice', action='store_true',
                        help='with --check: capture again into a scratch '
                        'directory and compare every case')
    parser.add_argument('--two-run', type=int, default=3,
                        help='with --check: PD1 screens a run checked by '
                        'the two-run method')
    a = parser.parse_args(argv)
    runs = [r for r in a.runs.split(',') if r]
    for r in runs:
        if r not in RUNS:
            parser.error('no run %s' % r)
    if a.points:
        p = places()
        for x in points(p):
            print(x.name, x.text[:120])
        for n, t in routines():
            print(n, resolve_routine(t)[:120])
        return 0
    if a.capture:
        capture_all(runs, a.out, a.jobs)
    if a.check:
        report = check_all(runs, a.out, twice=a.twice, two_run=a.two_run,
                           jobs=a.jobs)
        print(json.dumps(report['summary'], indent=1, sort_keys=True))
        return 0 if report['ok'] else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
