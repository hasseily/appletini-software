#!/usr/bin/env python3
"""Part s2fin's checks (docs/SCREENS.md 1.5.6-1.5.8, 4.7, 6, 7.3; docs/
m11-parts/s2fin.md): the image FINW (the finale, the title page, the
loading screen, the busy sign) and the tic side s2t_fin.s against
upstream on ref816.

The truth:
  - part s2cap's captures (build/native/m11/cases/): the frames of
    finale.script whose game state is the finale, the title page's drawn
    frame of finale.script, signs.script and demo3, and their events
    F_LoadScreen and bmSignOn: the state at the start (PD0, PU0), at
    I_FinishUpdate's entry (PDF), the wipe's black step (PW), the screen
    after (PD1's carried screen, PU1);
  - this part's own capture (`--capture`, build/native/m11/s2fin/cap/RUN.z;
    the same scripts on ref816): the screen around each bmSignOff that puts
    the rows back (bmSignOff is also reached by JMP, so s2cap has no event
    of it), bmSignOn's text and sign state, the nibble tables (NIBTAB) and
    TINTPAL where upstream changes them (part s2pal's points), and the call
    log of F_Ticker, WI_checkForAccelerate (its result is f_ticker's input:
    the hook calls milestone 10's routine first) and F_StartFinale.

The native side is the test image s2ft (src/native/s2_fint.s, the glue;
src/native/s2_fin.s, FINW's code; src/native/s2t_fin.s, the tic side;
the shared drawers, publish, palettes, effect service and pl_poll) on
a2vm under the test driver. Each case is staged in RamWorks (WI_ACCEL, the
card's F_*, GAMMA, PALST, FINW's own block, the SCBs and palettes, or a
whole screen), then its routine runs in the cost phase 30; a snapshot
after each call, the write log judged (no stray write; the publish order of
SCREENS.md 1.3 with the wipe's black step; the screen at the wipe's step
rebuilt from the log against PW).

Checks:
  - every finale frame and the title page (fin_frame), F_LoadScreen
    (fin_load), every bmSignOn (fin_signon) and the bmSignOff after it
    (fin_signoff, chained in the same run): the whole screen ($2000-$9FFF:
    s2layout's regions 'fin' and 'colors'; $9DC8-$9DFF kept) equal to the
    reference's after it; injected from both fills (fill $A5 with the
    screen's colours as captured; fill $5A with every byte the frame marked
    poisoned) and the finale chained (PALST and the nibble tables carried
    by the native code, the tic's state injected as the tics leave it);
  - F_MID and WI_ACCEL after F_Drawer (its textSpeed) equal to the
    reference's at I_FinishUpdate; PALST's scb, palette and picturenum too;
  - X3: the first title page's black step (upstream's titleWipe has none
    over the boot's gray title), named and counted;
  - f_ticker on every F_Ticker of finale.script (injected and chained) and
    f_start on F_StartFinale: the card's F_*, WI_ACCEL, G_GAMEACTION,
    G_GAMESTATE, AUTOMAP's AM_ACTIVE equal to the reference's after it.

Usage:
  python3 tools/native/s2fin.py --inc OUT       the generated s2fin.inc
  python3 tools/native/s2fin.py --capture [--jobs 2]
  python3 tools/native/s2fin.py --check [--profile f121] [--jobs 2]
  python3 tools/native/s2fin.py --planted [--jobs 2]
  python3 tools/native/s2fin.py --all [--jobs 2] (the capture when missing,
                                    the checks, the timing on f121 and
                                    fastpath, the planted bugs, the sizes:
                                    build/native/m11/s2fin/report.json)
"""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import s2layout as S  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
M11 = BUILD / 'native' / 'm11'
OUT = M11 / 's2fin'
CAP = OUT / 'cap'
SOURCE = ROOT / 'src' / 'native'
SHARED_GEN = M11 / 'shared' / 'gen'
KEEP_GEN = ('s2.inc', 's2-release.inc', 's2-m11.inc', 's2-fxch8.inc',
            'rlayout.inc')
RUNS = ('finale', 'signs', 'demo3')
JOBS = 2
PROFILES = ('f121', 'fastpath')
GS_LEVEL, GS_FINALE, GS_DEMOSCREEN = 0, 2, 3
FILLS = ((0xA5, False), (0x5A, True))     # (fill, poisoned)
CAP_FORMAT = 's2fin-cap 1'

# the glue's stage (src/native/s2_fint.s)
T_STAGE = 80
PER_BANK = 21
REC = 0x0900
REC_VARS, REC_PALST, REC_OWN, REC_SCREEN, REC_CTL = 0, 0x100, 0x400, 0x500, \
    0x800
K_FRAME, K_LOAD, K_SIGNON, K_SIGNOFF = 0, 1, 2, 3
F_LEFT, F_PAGE, F_CHAINED, F_INIT = 1, 2, 4, 8
SCREEN_BANK0 = 70               # whole screens: one a bank, 70 ..
TIC_IN, TIC_OUT = 60, 61        # the tic records' banks
TIC_REC = 16
MAX_CASES = S.DRV_CALLS - 1     # the driver's call list
CASE_CYCLES = 60_000_000      # a case's bound (a text frame: 21 M [M])
DRAIN_US = 0.991        # µs a published byte drains on F1.2.1 [M: s2draw.md]
LOAD_US = 0.246         # µs a byte of far_pload [A on M: NATIVE.md 4.3]
FONT = (0x21, 0x5F)             # '!' .. '_'
TEXTS = {'txLoading': 0, 'txSaving': 1, 'txInsert': 2}
BUSY_H = 24                     # [R m_menu65.s:1761]


class FinError(Exception):
    pass


# ---------------------------------------------------------------------------
# The generated include
# ---------------------------------------------------------------------------

def release():
    from native import umodel as U
    return U.Release()


def const_of(name: str) -> int:
    """A CONST_* of upstream's offsets.inc."""
    path = BUILD / 'upstream' / 'src' / 'iigs' / 'offsets.inc'
    for line in path.read_text().splitlines():
        f = line.split()
        if len(f) >= 3 and f[0] == name and f[1] == '.equ':
            return int(f[2], 0)
    raise FinError('%s is not in %s' % (name, path))


def e1text() -> bytes:
    """The end text's bytes in the release (f_finale65.s's e1text ..
    e1end)."""
    from native import s2cap as C
    a, e = C.sym('f_finale65.s:e1text'), C.sym('f_finale65.s:e1end')
    return C.code().get(a, e - a)


class Glyph(NamedTuple):
    char: int
    bank: int
    address: int
    width: int
    height: int
    top: int


def font() -> List[Glyph]:
    """'!' .. '_': each glyph's place in the 2D store (part s2data's
    manifest) and its patch's width, height and top offset (DOOM1.WAD's)."""
    from native import s2data as D
    path = M11 / 's2data' / 's2data.json'
    if not path.exists():
        raise FinError('%s is missing: make -C src/native -f m11.mk part '
                       'P=s2data' % path)
    lumps = {x['name']: x for x in json.loads(path.read_text())['lumps']}
    wad = D.read_wad()
    out = []
    for c in range(FONT[0], FONT[1] + 1):
        name = 'STCFN%03d' % c
        p = D.parse_patch(wad[name])
        x = lumps[name]
        out.append(Glyph(c, x['bank'], x['address'], p.width, p.height,
                         p.top))
    return out


def inc_text() -> str:
    rel = release()
    gs = font()
    bad = [g for g in gs if g.top > 0 or g.height - g.top > 8 or
           g.width > 63]
    if bad:     # s2_fin.s's GLYPH_H and its width arithmetic
        raise FinError('a glyph s2_fin.s cannot band: %r' % (bad[0],))
    lines = ['; Generated by tools/native/s2fin.py (part s2fin, '
             'docs/m11-parts/s2fin.md). Do not edit.', '',
             '; the pictures\' lump numbers in the release (upstream\'s '
             'picturenum, PALST\'s PS_PICTURE)',
             'FIN_HELP2NUM    = $%04X' % rel.index('HELP2'),
             'FIN_TITLENUM    = $%04X' % rel.index('TITLEPIC'),
             '; offsets.inc\'s CONST_GS_FINALE; the end text\'s length '
             '(e1end - e1text)',
             'FIN_GS_FINALE   = $%04X' % const_of('CONST_GS_FINALE'),
             'FIN_E1LENGTH    = %d' % len(e1text()),
             '; the font \'!\' .. \'_\': each glyph\'s bank, address and '
             'width']
    for i, g in enumerate(gs):
        lines.append('FIN_FB_%d = %d' % (i, g.bank))
        lines.append('FIN_FA_%d = $%04X' % (i, g.address))
        lines.append('FIN_FW_%d = %d' % (i, g.width))
    return '\n'.join(lines) + '\n'


def write_inc(path: Path) -> None:
    text = inc_text()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        return
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text)
    tmp.replace(path)


def inc_values(path: Path) -> Dict[str, int]:
    out = {}
    for line in path.read_text().splitlines():
        f = line.split(';')[0].split('=')
        if len(f) == 2:
            v = f[1].strip()
            try:
                out[f[0].strip()] = int(v[1:], 16) if v.startswith('$') \
                    else int(v)
            except ValueError:
                pass
    return out


# ---------------------------------------------------------------------------
# This part's capture
# ---------------------------------------------------------------------------

def sign_off() -> Tuple[int, int]:
    """VW_SGON's address [R viewwin.inc:69] and bmSignOff's RTL after its
    jsr bmSignBox [R m_menu65.s:1820-1827], from bmSignOff's code: lda long
    VW_SGON, beq, lda #0, sta long VW_SGON, ldy #1, jsr bmSignBox, rtl."""
    from native import s2cap as C
    a = C.sym('m_menu65.s:bmSignOff')
    box = C.sym('m_menu65.s:bmSignBox')
    code = C.code().get(a, 20)
    on = int.from_bytes(code[1:4], 'little')
    if code[0] != 0xAF or code[9] != 0x8F or code[10:13] != code[1:4] or \
            code[16:20] != bytes([0x20, box & 0xFF, box >> 8 & 0xFF, 0x6B]):
        raise FinError('bmSignOff is not as m_menu65.s has it: %s'
                       % code.hex())
    return on, a + 19


def cap_points() -> List[Any]:
    """The nibble tables' points (part s2pal's: I_SetLevelPalette's,
    drawPicture's and I_MenuPaletteBack's returns), bmSignOn's entry (the
    sign's state and its text, A), bmSignOff's entry with the sign on and
    its return (the screen)."""
    from native import s2cap as C, s2pal as P
    pts = P.nib_points()
    on, rtl = sign_off()
    pts.append(C._pc('SON', C.sym('m_menu65.s:bmSignOn'), [(on, 2)]))
    pts.append(C._pc('SO0', C.sym('m_menu65.s:bmSignOff'), [C.SCREEN],
                     ',if=%06X:2:ne:0' % on))
    pts.append(C._pc('SO1', rtl, [C.SCREEN]))
    return pts


def cap_routines() -> List[Tuple[str, str]]:
    from native import s2cap as C
    fi = 'f_finale65.s:%s:%d' % C._znear_first('f_finale65.s')
    acc = 'wi_stuff65.s:_g_acceleratestage:2'
    return [('F_Ticker', 'f_finale65.s:F_Ticker,jumps=1,mem=%s+'
             '_g_gameaction:2+%s' % (fi, acc)),
            ('WI_checkForAccelerate', 'wi_stuff65.s:WI_checkForAccelerate,'
             'mem=%s' % acc),
            ('F_StartFinale', 'f_finale65.s:F_StartFinale,jumps=1,mem=%s+'
             '_g_gameaction:2+_g_gamestate:2+am_map65.s:automapmode:2+%s'
             % (fi, acc))]


def capture(run: str) -> Dict[str, Any]:
    """One run of the release on ref816 (part s2cap's script and machine)
    with cap_points and cap_routines, distilled as it comes into
    CAP/RUN.z (zlib of JSON; the screens and tables once each)."""
    from native import s2cap as C
    from ref816 import dumps as D
    CAP.mkdir(parents=True, exist_ok=True)
    pts = cap_points()
    work = Path(tempfile.mkdtemp(prefix='tmp-cap-%s-' % run, dir=str(OUT)))
    blobs: Dict[str, str] = {}
    out: Dict[str, Any] = {'format': CAP_FORMAT, 'run': run, 'nib': [],
                           'son': [], 'soff': [], 'blobs': blobs}
    pending: List[Optional[Dict[str, Any]]] = [None]

    def blob(data: bytes) -> str:
        key = hashlib.sha256(data).hexdigest()
        if key not in blobs:
            blobs[key] = zlib.compress(data, 6).hex()
        return key

    def reader(handle) -> None:
        for d in D.read(handle):
            p = pts[d.header['point']]
            parts, at = [], 0
            for _, n in p.ranges:
                parts.append(d.data[at:at + n])
                at += n
            cyc = d.header['cycles']
            kind = p.name.split(':')[0]
            if kind in ('PL', 'PP', 'PG'):
                out['nib'].append({
                    'point': p.name, 'cycles': cyc,
                    'nibtab': blob(parts[0]), 'tintpal': blob(parts[1]),
                    'near': parts[2].hex(), 'znear': parts[3].hex(),
                    'gamma': int.from_bytes(parts[4], 'little')})
            elif kind == 'SON':
                out['son'].append({'cycles': cyc, 'cpu': d.header.get('cpu'),
                                   'on': int.from_bytes(parts[0], 'little')})
            elif kind == 'SO0':
                pending[0] = {'cycles': cyc, 'before': blob(parts[0])}
            elif kind == 'SO1' and pending[0] is not None:
                pending[0]['after'] = blob(parts[0])
                pending[0]['end'] = cyc
                out['soff'].append(pending[0])
                pending[0] = None
    sink = C.CallSink()
    try:
        info = C.machine(run, work, pts, cap_routines(), reader, sink.feed)
        if info['problems']:
            raise FinError('%s: %s' % (run, info['problems'][:4]))
        names = [n for n, _ in cap_routines()]
        out['calls'] = [dict(c, name=names[c['routine']])
                        for c in sink.lines]
        out['traffic'] = info['traffic']
        C.write_atomic(CAP / (run + '.z'),
                       zlib.compress(json.dumps(out).encode(), 6))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return {'run': run, 'nib': len(out['nib']), 'son': len(out['son']),
            'soff': len(out['soff']), 'calls': len(out.get('calls', [])),
            'traffic': out.get('traffic')}


class Capture(NamedTuple):
    run: str
    data: Dict[str, Any]

    def blob(self, key: str) -> bytes:
        b = zlib.decompress(bytes.fromhex(self.data['blobs'][key]))
        if hashlib.sha256(b).hexdigest() != key:
            raise FinError('%s: a blob does not match its key' % self.run)
        return b

    def nib_at(self, cycles: int) -> Optional[Dict[str, Any]]:
        """The last nibble dump before `cycles` (the tables then)."""
        best = None
        for r in self.data['nib']:
            if r['cycles'] < cycles:
                best = r
        return best


def load_capture(run: str) -> Capture:
    path = CAP / (run + '.z')
    if not path.exists():
        raise FinError('%s is missing: python3 tools/native/s2fin.py '
                       '--capture' % path)
    data = json.loads(zlib.decompress(path.read_bytes()))
    if data.get('format') != CAP_FORMAT:
        raise FinError('%s: not %s' % (path, CAP_FORMAT))
    return Capture(run, data)


def capture_all(jobs: int = JOBS) -> List[Dict[str, Any]]:
    from native import s2cap as C
    print(C.df_report())
    with ThreadPoolExecutor(max(1, min(jobs, 2))) as ex:
        return list(ex.map(capture, RUNS))


# ---------------------------------------------------------------------------
# The cases
# ---------------------------------------------------------------------------

class Case(NamedTuple):
    name: str
    run: str
    kind: int                   # K_*
    flags: int                  # fin_frame's F_LEFT, F_PAGE
    case: Any                   # s2cap.Case (None: a sign-off)
    start: int                  # the cycle it starts at
    want: bytes                 # the screen after ($2000-$9FFF)
    screen: Optional[bytes]     # a whole screen staged before (the signs)
    black: bool                 # a new picture: the wipe's black step
    x3: bool                    # upstream's titleWipe (no black step)
    pw: Optional[bytes]         # the screen at the wipe's step (PW)
    text: int                   # fin_signon's text and digit
    digit: int
    sign_on: int                # the sign's state before (VW_SGON)
    group: str                  # 'finale', 'page', 'load', 'sign'
    stage: int                  # finalestage at the start (the finale)


def _screen_of(d) -> bytes:
    from native import s2cap as C
    return d.get(*C.SCREEN)


def run_cases(run: str) -> Tuple[List[Case], List[str], int]:
    """A run's FINW cases (in order), the frames excluded (named), and the
    page's static frames (display's onlyTics: nothing drawn)."""
    from native import s2cap as C
    rc = C.RunCases(C.run_dir(run))
    cap = load_capture(run)
    texts = {C.sym('m_menu65.s:' + n) & 0xFFFF: k for n, k in TEXTS.items()}
    out: List[Case] = []
    excluded: List[str] = []
    static = 0
    for e, c in rc.frames():
        b = c.before
        if b.point != 'PD0:display':
            continue
        gs = C.val(b, 'g_game65.s:_g_gamestate')
        if gs not in (GS_FINALE, GS_DEMOSCREEN):
            continue
        name = '%s/f%06d' % (run, e['frame'])
        pdf = c.one('PDF')
        if pdf is None:
            if gs == GS_DEMOSCREEN:
                static += 1
                continue
            excluded.append('%s: no I_FinishUpdate' % name)
            continue
        if C.val(b, 'm_menu65.s:_g_menuactive') or c.one('PM') is not None:
            excluded.append('%s: a menu over it (s2menu1)' % name)
            continue
        flags = F_LEFT if C.val(b, 'd_main65.s:oldgamestate') == GS_LEVEL \
            else 0
        if gs == GS_DEMOSCREEN:
            flags |= F_PAGE
        black = bool(C.val(pdf, 'i_viigs65.s:palettecount'))
        pw = c.one('PW')
        out.append(Case(name, run, K_FRAME, flags, c, b.head['cycles'],
                        c.screen_after, None, black, black and pw is None,
                        _screen_of(pw) if pw is not None else None, 0, 0, 0,
                        'page' if gs == GS_DEMOSCREEN else 'finale',
                        C.val(b, 'f_finale65.s:finalestage')))
    sons = list(cap.data['son'])
    for e, c in rc.events():
        r = e['routine']
        name = '%s/e%s-%s' % (run, e['name'][1:], r)
        b = c.before
        if r == 'F_LoadScreen':
            pdf = c.one('PDF')
            black = bool(pdf is not None and
                         C.val(pdf, 'i_viigs65.s:palettecount'))
            out.append(Case(name, run, K_LOAD, 0, c, b.head['cycles'],
                            c.screen_after, None, black, False,
                            _screen_of(c.one('PW')) if black and
                            c.one('PW') is not None else None, 0, 0, 0,
                            'load', 0))
        elif r == 'bmSignOn':
            son = [s for s in sons if b.head['cycles'] <= s['cycles'] <
                   c.after.head['cycles']]
            if len(son) != 1:
                raise FinError('%s: %d bmSignOn entries in the capture' % (
                    name, len(son)))
            a = son[0]['cpu']['a'] & 0xFFFF
            if a not in texts:
                raise FinError('%s: the text $%04X is none of upstream\'s'
                               % (name, a))
            out.append(Case(name, run, K_SIGNON, 0, c, b.head['cycles'],
                            c.screen_after, c.screen_before, False, False,
                            None, texts[a], 0, son[0]['on'], 'sign', 0))
        elif r in ('bmSignOff', 'bmSignLoading', 'bmSignSaving',
                   'bmDiskAsk'):
            raise FinError('%s: no case kind for %s yet' % (name, r))
    for k, so in enumerate(cap.data['soff']):
        out.append(Case('%s/soff%d' % (run, k), run, K_SIGNOFF, 0, None,
                        so['cycles'], cap.blob(so['after']),
                        cap.blob(so['before']), False, False, None, 0, 0, 1,
                        'sign', 0))
    out.sort(key=lambda x: x.start)
    return out, excluded, static


def all_cases(runs: Sequence[str] = RUNS
              ) -> Tuple[List[Case], List[str], Dict[str, int]]:
    cs: List[Case] = []
    ex: List[str] = []
    static: Dict[str, int] = {}
    for run in runs:
        a, b, n = run_cases(run)
        cs += a
        ex += b
        static[run] = n
    return cs, ex, static


def kind_name(c: Case) -> str:
    if c.kind == K_FRAME:
        if c.group == 'page':
            return 'page'
        if c.stage:
            return 'picture (new)' if c.black else 'picture'
        return 'text'
    return {K_LOAD: 'load screen', K_SIGNON: 'sign on',
            K_SIGNOFF: 'sign off'}[c.kind]


def screen_region() -> S.Region:
    fin, col = S.REGIONS['fin'], S.REGIONS['colors']
    return S.Region('finale', 's2fin', fin.rows, col.scbs, col.palettes)


class Stage(NamedTuple):
    rec: bytes                  # the case's REC bytes
    before: bytes               # aux 0 $2000-$9FFF when the call starts
    screen: Optional[bytes]     # a whole screen to stage (its own bank)
    tintpal: bytes
    nibtab: bytes


def stage(c: Case, fill: int, poison: bool, flags: int,
          vars_: Optional[bytes] = None) -> Stage:
    """A case's stage record. vars_: WI_ACCEL and the card's F_* to use
    (a chain's tic state); else the case's."""
    from native import llayout as LL, s2state as ST
    cap = load_capture(c.run)
    nib = cap.nib_at(c.start)
    if nib is None:
        raise FinError('%s: no nibble tables before it' % c.name)
    rec = bytearray(REC)
    ctl = bytearray(6)
    ctl[0] = c.kind
    ctl[1] = flags
    ctl[2] = fill
    ctl[4], ctl[5] = c.text, c.digit
    tintpal = cap.blob(nib['tintpal'])
    if c.case is not None:
        inj = ST.inject(c.case, 'finale', fill, with_screen=False)
        pal = ST.inject(c.case, 'palettes', fill, with_screen=False)
        for i in (inj, pal):
            if i.unfit:
                raise FinError('%s: unfit %s' % (c.name, i.unfit))
        palst = bytearray([fill]) * S.PALST_SIZE
        own = bytearray([fill]) * 256
        var = bytearray([fill]) * 8
        acc = LL.G['WI_ACCEL']
        s2t = S.BUILDS['test'].s2t_base
        fst = s2t + S.S2T['F_STAGE']
        ss_pal, ss_own = S.SS['SS_PALST'], S.SS['SS_FINW']
        for kind, bank, address, data in inj.records + pal.records:
            for k, v in enumerate(data):
                a = address + k
                if kind == ST.MAIN and acc <= a < acc + 2:
                    var[a - acc] = v
                elif kind == ST.LC and fst <= a < fst + 6:
                    var[2 + a - fst] = v
                elif kind == ST.AUX and bank == S.S2STATE:
                    if ss_pal <= a < ss_pal + S.PALST_SIZE:
                        palst[a - ss_pal] = v
                    elif ss_own <= a < ss_own + 256:
                        own[a - ss_own] = v
        gamma = None
        for pl in pal.places:
            if pl.ref.endswith('_g_gamma'):
                gamma = pl.value
        if gamma is None:
            raise FinError('%s: no gamma' % c.name)
        palst[S.palst_places()['PS_BEGUN']] = 0
        # F_SIGNON (s2layout's FINW_NATIVE, S2FIN-1): VW_SGON's
        own[S.state_places('FINW')['F_SIGNON'] -
            S.OWN_STATE['FINW'][1]] = c.sign_on
        if vars_ is not None:
            var[:8] = vars_
        rec[REC_VARS:REC_VARS + 8] = var
        rec[REC_VARS + 8:REC_VARS + 10] = bytes([gamma & 0xFF, gamma >> 8])
        rec[REC_PALST:REC_PALST + S.PALST_SIZE] = palst
        rec[REC_OWN:REC_OWN + 256] = own
        try:
            tintpal = c.case.carried('TINTPAL')
        except KeyError:
            pass
    if c.screen is not None:
        ctl[3] = 1                      # (the bank: stage_records sets it)
        before = c.screen
    else:
        screen, _ = ST.screen_image(c.case, fill, poison)
        tail = screen[S.SCB - S.SHR:]
        rec[REC_SCREEN:REC_SCREEN + len(tail)] = tail
        before = bytes([fill]) * (S.SCB - S.SHR) + tail
    rec[REC_CTL:REC_CTL + 6] = ctl
    return Stage(bytes(rec), before, c.screen, tintpal,
                 cap.blob(nib['nibtab']))


def stage_records(stages: Sequence[Stage]) -> List[Tuple[int, int, int,
                                                         bytes]]:
    banks: Dict[int, bytearray] = {}
    out = []
    j = 0
    for k, st in enumerate(stages):
        bank, i = divmod(k, PER_BANK)
        data = banks.setdefault(T_STAGE + bank, bytearray(0xC000 - 0x0200))
        rec = bytearray(st.rec)
        if st.screen is not None:
            rec[REC_CTL + 3] = SCREEN_BANK0 + j
            out.append((1, SCREEN_BANK0 + j, 0x0200, st.screen))
            j += 1
        data[i * REC:(i + 1) * REC] = rec
    if j > T_STAGE - SCREEN_BANK0:
        raise FinError('%d whole screens in one run' % j)
    return [(1, b, 0x0200, bytes(d)) for b, d in sorted(banks.items())] + out


# ---------------------------------------------------------------------------
# The build and the machine
# ---------------------------------------------------------------------------

def make(source: Path = SOURCE, m11: Path = M11) -> None:
    from native import s2run as SR
    SR.make('s2fin', m11, source)


def build_of(obj: Path = OUT):
    from native import s2run as SR
    if not (obj / 's2ft.map').exists():
        raise FinError('%s is missing: make -C src/native -f m11.mk part '
                       'P=s2fin' % (obj / 's2ft.map'))
    return SR.load_build(obj, 's2ft', 'FINW')


_STORE: Optional[List[Tuple[int, int, int, bytes]]] = None


def store_records() -> List[Tuple[int, int, int, bytes]]:
    """The 2D store (part s2data's GFX.n: the pictures, the flat, the
    font)."""
    global _STORE
    if _STORE is None:
        from native import lstore
        files = sorted((M11 / 's2data').glob('GFX.*'))
        if not files:
            raise FinError('no GFX.n in %s: make -f m11.mk part P=s2data' %
                           (M11 / 's2data'))
        # built whole, then published in one assignment: the check's job
        # threads call this at once, and a thread must never see a store
        # half read (the wave 8 integration: a partial store made a run
        # crash or run away now and then)
        store = []
        for p in files:
            for bank, address, data in lstore.read_bank_file(p.read_bytes()):
                store.append((1, bank, address, bytes(data)))
        _STORE = store
    return _STORE


def card_records(gen: Dict[str, int]) -> List[Tuple[int, int, int, bytes]]:
    """The effects' card state as at a boot with no sound: the voices
    idle, the mailboxes empty, FX_ON 0 (fx_service then only empties)."""
    voices = gen['VOICES'] * gen['VOICE_SIZE']
    mails = gen['NUM_CHANNELS'] * 4
    return [(2, 0, gen['FXV_BASE'], bytes(voices)),
            (2, 0, gen['SC_MAIL'], bytes(mails)),
            (2, 0, gen['FX_ON'], bytes(3))]


def module_pcs(b) -> Dict[str, Tuple[int, int]]:
    from native import s2drawcase as DC
    return DC.module_pcs(b)


def owners(b, loads, gen: Dict[str, int]):
    """The writers of a run of s2ft and what each may write."""
    from native import llayout as LL, plinput as PI, rlayout as R, \
        s2run as SR
    pcs = module_pcs(b)
    lab = b.labels
    data = b.segments['S2DATA']
    fa = ('main', 0, 0x0000, 0x0006)
    s2zp = ('main', 0, 0x48, 0x78)
    palzp = ('main', 0, 0x78, 0x80)
    fzp = ('main', 0, 0x80, 0xA5)
    gzp = ('main', 0, 0xB0, 0xB9)
    band = ('main', 0, S.IMAGE['FINW'].runtime[0][0], 0xBC00)
    palst = ('main', 0, S.PALST_W, S.PALST_W + S.PALST_SIZE)
    own = ('main', 0, S.PALST_W + S.PALST_SIZE, 0xC000)
    dat = ('main', 0, data[0], data[1] + 1)
    acc = ('main', 0, LL.G['WI_ACCEL'], LL.G['WI_ACCEL'] + 2)
    act = ('main', 0, LL.G['G_GAMEACTION'], LL.G['G_GAMEACTION'] + 2)
    gst = ('main', 0, LL.G['G_GAMESTATE'], LL.G['G_GAMESTATE'] + 2)
    am = ('main', 0, R.FRAME['AUTOMAP'], R.FRAME['AUTOMAP'] + 1)
    s2t = S.BUILDS['test'].s2t_base
    card = ('lc', 0, s2t + S.S2T['F_STAGE'], s2t + S.S2T['F_MID'] + 1)
    mid = ('lc', 0, s2t + S.S2T['F_MID'], s2t + S.S2T['F_MID'] + 1)
    pixels = ('aux', 0, S.SHR, S.SCB)
    colors = ('aux', 0, S.SCB, S.SCREEN_END)
    ss_pal = ('aux', S.S2STATE, S.SS['SS_PALST'],
              S.SS['SS_PALST'] + S.PALST_SIZE)
    ss_own = ('aux', S.S2STATE, S.SS['SS_FINW'], S.SS['SS_FINW'] + 3)
    ss_own_g = ('aux', S.S2STATE, S.SS['SS_FINW'], S.SS['SS_FINW'] + 256)
    nib = ('aux', S.S2PAL, S.S2PAL_AT['S2P_NIB'],
           S.S2PAL_AT['S2P_NIB'] + S.S2PAL_SIZE['S2P_NIB'])
    begun = lab['s2_begun']
    gamma = S.resolve_game('GAMMA')[1]
    io_window = frozenset({0xC002, 0xC003, 0xC004, 0xC005, 0xC073})
    amem = frozenset({0xC700, 0xCFF0, 0xCFF1, 0xCFF2, 0xCFFF})
    fxcard = tuple(('lc', 0, lo, hi) for lo, hi in (
        (gen['FXV_BASE'], gen['FXV_BASE'] + gen['VOICES'] *
         gen['VOICE_SIZE']),
        (gen['FX_ON'], gen['FX_RING']),
        (gen['SC_MAIL'], gen['SC_MAIL'] + gen['NUM_CHANNELS'] * 4)))
    return [
        SR.driver_owner(b), SR.loader_owner(b, loads),
        # (the far layer: for FINW, s2_pal, s2_nib and the glue, which
        # stages PALST and the own block and writes the tics' outputs)
        SR.Owner('the far layer', (b.segments['RFAR'],),
                 (fa, s2zp, fzp, gzp, band, palst, own, dat, ss_pal,
                  ss_own_g, nib, ('aux', TIC_OUT, 0x0200, 0xC000)),
                 io_window),
        SR.Owner('the test glue', (pcs['s2_fint'],),
                 (fa, gzp, dat, acc, act, gst, am, card,
                  ('main', 0, R.PHASE, R.PHASE + 2),
                  ('main', 0, gamma, gamma + 2), pixels, colors, ss_pal,
                  ss_own_g), frozenset({0xC004, 0xC005})),
        SR.Owner('s2_fin', (pcs['s2_fin'],),
                 (fa, s2zp, fzp, dat, own, acc, mid,
                  ('main', 0, begun, begun + 1), ('main', 0, S.PL_STATUS,
                                                   S.PL_STATUS + 1)), amem),
        SR.Owner('s2t_fin', (pcs['s2t_fin'],), (acc, act, gst, am, card),
                 frozenset()),
        SR.Owner('s2_draw', (pcs['s2_draw'],), (fa, s2zp), frozenset()),
        SR.Owner('s2_pub', (pcs['s2_pub'],),
                 (s2zp, pixels, ('main', 0, begun, begun + 1)),
                 frozenset({0xC004, 0xC005})),
        SR.Owner('s2_pal', (pcs['s2_pal'],), (fa, palzp, palst, colors),
                 frozenset({0xC004, 0xC005})),
        SR.Owner('s2_nib', (pcs['s2_nib'],), (fa, palzp, palst),
                 frozenset()),
        SR.Owner('fx_service', (pcs['fx'],), fxcard, frozenset()),
    ] + PI.image_owners(b)


def write_log_ranges(b, full: bool) -> str:
    """Every CPU write but: the stack page, the far layer's arguments and
    the drawers' zero page ($00-$05, $48-$7F), the image's code (its loops
    patch their operands) and FINW's runtime W ($8000-$BBFF: the band, the
    marks, the slots, the fetch buffer); unless `full`, the pixel rows
    1-198 (32 KB a frame: the whole screen is compared on the snapshots;
    rows 0 and 199, a frame's first and last band stores, stay for the
    order). `full` (the signs, the wipes, the load screen): every screen
    store, for the wipe's step and the sign's rows."""
    lo, hi = b.segments['S2DATA']
    aux0 = 'aux0' if full else 'aux0:0000-209F,aux0:9C60-FFFF'
    return ('main:0006-0047,main:0080-00FF,main:0200-65FF,main:%04X-%04X,'
            'main:BC00-FFFF,lc,lc1,%s,aux1-127,cpu:C000-C0FF' % (lo, hi,
                                                                aux0))


class Span(NamedTuple):
    start: int
    end: int
    writes: List[Any]


def spans(b, writes) -> List[Span]:
    """Each call of the glue: PHASE written PHV_2D, then 0."""
    from native import rlayout as R
    glue = module_pcs(b)['s2_fint']
    out: List[Span] = []
    cur: Optional[List[Any]] = None
    start = 0
    for w in writes:
        if w.storage == 'main' and w.offset == R.PHASE and \
                glue[0] <= w.pc <= glue[1]:
            if w.new == 2 * S.PHASE_2D:
                cur, start = [], w.clock
            elif w.new == 0 and cur is not None:
                out.append(Span(start, w.clock, cur))
                cur = None
            continue
        if cur is not None:
            cur.append(w)
    return out


def ms(profile: str, clocks: int) -> float:
    from a2vm import costs
    return clocks / (costs.parameters(profile)['fabric_mhz'] * 1000.0)


def gen_values() -> Dict[str, int]:
    return inc_values(SHARED_GEN / 's2.inc')


# ---------------------------------------------------------------------------
# A run of up to 31 cases
# ---------------------------------------------------------------------------

class Job(NamedTuple):
    tag: str
    cases: Tuple[Case, ...]
    fill: int
    poison: bool
    chained: bool
    vars_: Tuple[Optional[bytes], ...]  # a chain's tic state, each case
    state: Optional[bytes] = None       # a chain going on: SS_PALST,
    #                                     SS_FINW and S2NIB as the last
    #                                     run left them


def expected(c: Case) -> Dict[str, Any]:
    """The reference's state after the case: PALST's fields and the
    finale's at I_FinishUpdate's entry (frames, the load screen) or at the
    return (the sign); nothing for a sign-off."""
    from native import s2cap as C
    if c.case is None:
        return {}
    d = c.case.one('PDF')
    if d is None or c.kind == K_SIGNON:
        d = c.case.after
    sym = C.sym
    out = {'scb': d.get(sym('i_viigs65.s:scb'), 200),
           'palette': d.get(sym('i_viigs65.s:palette'), 512),
           'picture': C.val(d, 'i_viigs65.s:picturenum')}
    if c.group == 'finale':
        out['mid'] = C.val(d, 'f_finale65.s:midstage')
        out['accel'] = C.val(d, 'wi_stuff65.s:_g_acceleratestage')
    return out


def rebuild(before: bytes, stores: Sequence[Any]) -> bytes:
    """The screen after `stores` (s2check.Store) from `before`."""
    out = bytearray(before)
    for s in stores:
        out[s.offset - S.SHR] = s.value
    return bytes(out)


def at_wipe_step(stores: Sequence[Any]) -> Sequence[Any]:
    """The stores before pictureColors: up to the last pixel store."""
    from native import s2check as K
    last = max((i for i, s in enumerate(stores) if K.kind(s.offset) ==
                'band'), default=-1)
    return stores[:last + 1]


def run_job(job: Job, b, profile: Optional[str], work_root: Path,
            gen: Dict[str, int]) -> Dict[str, Any]:
    from native import llayout as LL, plinput as PI, s2check as K, \
        s2run as SR
    if not 0 < len(job.cases) <= MAX_CASES:
        raise FinError('%s: %d cases' % (job.tag, len(job.cases)))
    stages = []
    for i, c in enumerate(job.cases):
        flags = c.flags
        if (job.chained and (i or job.state is not None)) or \
                c.kind == K_SIGNOFF:
            flags |= F_CHAINED          # (a sign-off: after its sign-on)
        stages.append(stage(c, job.fill, job.poison, flags, job.vars_[i]))
    # (a sign-off reads neither: it puts the saved rows back)
    tints = {st.tintpal for c, st in zip(job.cases, stages)
             if c.kind != K_SIGNOFF}
    nibs = {st.nibtab for c, st in zip(job.cases, stages)
            if c.kind != K_SIGNOFF}
    if len(tints) != 1 or (len(nibs) != 1 and not job.chained):
        raise FinError('%s: %d TINTPALs, %d nibble table sets' % (
            job.tag, len(tints), len(nibs)))
    recs = store_records() + stage_records(stages) + card_records(gen) + \
        [(1, S.S2PAL, S.S2PAL_AT['S2P_TINTPAL'], stages[0].tintpal),
         (1, S.S2PAL, S.S2PAL_AT['S2P_NIB'], stages[0].nibtab)]
    recs += PI.boot_records()
    if job.state is not None:           # a chain goes on
        ss = S.SS
        recs += [(1, S.S2STATE, ss['SS_PALST'],
                  job.state[:S.PALST_SIZE]),
                 (1, S.S2STATE, ss['SS_FINW'],
                  job.state[S.PALST_SIZE:S.PALST_SIZE + 256]),
                 (1, S.S2PAL, S.S2PAL_AT['S2P_NIB'],
                  job.state[S.PALST_SIZE + 256:])]
    # every screen store logged for the wipe's step and the signs (not in
    # a chain: its 31 frames would pass the log's bound)
    full = not job.chained and any(c.black or c.group in ('sign', 'load')
                                   for c in job.cases)
    calls = [SR.Call('fint_case', k) for k in range(len(stages))]
    s2t = S.BUILDS['test'].s2t_base
    acc = LL.G['WI_ACCEL']
    snap = 'aux0:2000-9FFF,main:BC00-BFFF,main:%04X-%04X,lc:%04X-%04X' % (
        acc, acc + 1, s2t + S.S2T['F_STAGE'], s2t + S.S2T['F_MID'])
    if job.chained:
        snap += ',aux%d:%04X-%04X,aux%d:%04X-%04X,aux%d:%04X-%04X' % (
            S.S2STATE, S.SS['SS_PALST'], S.SS['SS_PALST'] + S.PALST_SIZE - 1,
            S.S2STATE, S.SS['SS_FINW'], S.SS['SS_FINW'] + 255,
            S.S2PAL, S.S2PAL_AT['S2P_NIB'], S.S2PAL_AT['S2P_NIB'] +
            S.S2PAL_SIZE['S2P_NIB'] - 1)
    work = Path(tempfile.mkdtemp(prefix='tmp-run-', dir=str(work_root)))
    problems: List[str] = []
    try:
        r = SR.run(b, calls, job.fill, work, extra_records=recs,
                   write_log=False, snap_ranges=snap, profile=profile,
                   cycles=CASE_CYCLES * len(calls), timeout=600.0,
                   extra_args=[
                       '--write-log', write_log_ranges(b, full),
                       '--write-log-file', str(work / 'writes.log'),
                       '--write-log-limit', str(SR.WRITE_LOG_LIMIT)])
        if r.ended() != 'stop' or r.status() != S.S2S['DONE']:
            st = r.status()
            return {'tag': job.tag, 'cases': len(job.cases), 'problems': [
                '%s: the run ended %s, status %s' % (
                    job.tag, r.ended(), 'none' if st is None else
                    '$%02X' % st)], 'times': [], 'stray': 0, 'stack': None,
                'writes': 0, 'x3': 0, 'state': None}
        snaps = r.calls()
        writes = r.writes()
        n_stray, stray_list = SR.stray(writes, owners(b, r.loads, gen))
        sps = spans(b, writes)
        stack = SR.stack_depth(r)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    if n_stray:
        problems.append('%s: %d stray writes: %s' % (job.tag, n_stray,
                                                    stray_list[:3]))
    if len(snaps) != len(job.cases) or len(sps) != len(job.cases):
        raise FinError('%s: %d snapshots, %d calls for %d cases' % (
            job.tag, len(snaps), len(sps), len(job.cases)))
    region = screen_region()
    times = []
    x3 = 0
    pp = S.palst_places()
    w = S.PALST_W
    for c, st, m, sp in zip(job.cases, stages, snaps, sps):
        tag = '%s (fill %02X%s%s)' % (c.name, job.fill,
                                      ', poisoned' if job.poison else '',
                                      ', chained' if job.chained else '')
        got = bytes(m.storage('aux', 0)[S.SHR:S.SCREEN_END])
        res = K.compare(c.want, st.before, got, region)
        for a, v, ref in res.differ[:1]:
            row = (a - S.SHR) // S.ROW_BYTES if a < S.SCB else None
            problems.append('%s: %s $%04X: $%02X, ref $%02X%s' % (
                tag, 'row %d byte %d,' % (row, (a - S.SHR) % S.ROW_BYTES)
                if row is not None else 'colours', a, v, ref,
                ' (%d bytes differ)' % len(res.differ)
                if len(res.differ) > 1 else ''))
        for a, v, was in res.outside[:1]:
            problems.append('%s: $%04X changed outside the region: $%02X, '
                            'was $%02X' % (tag, a, v, was))
        want = expected(c)
        if 'scb' in want and c.kind != K_SIGNON:
            if bytes(m.main[w + pp['PS_SCB']:w + pp['PS_SCB'] + 200]) != \
                    want['scb']:
                problems.append('%s: PALST scb differs' % tag)
            if bytes(m.main[w + pp['PS_PALETTE']:w + pp['PS_PALETTE'] +
                            512]) != want['palette']:
                problems.append('%s: PALST palette differs' % tag)
            pic = m.main[w + pp['PS_PICTURE']] | \
                m.main[w + pp['PS_PICTURE'] + 1] << 8
            if pic != want['picture']:
                problems.append('%s: picturenum $%04X, ref $%04X' % (
                    tag, pic, want['picture']))
        if 'mid' in want:
            mid = m.lc[s2t + S.S2T['F_MID'] - 0xC000]
            a = m.main[acc] | m.main[acc + 1] << 8
            if mid != want['mid'] or a != want['accel']:
                problems.append('%s: F_MID %d, WI_ACCEL %d; ref %d, %d' % (
                    tag, mid, a, want['mid'], want['accel']))
        if c.kind in (K_SIGNON, K_SIGNOFF):
            on = m.main[S.PALST_W + S.PALST_SIZE + 2]
            if on != (1 if c.kind == K_SIGNON else 0):
                problems.append('%s: F_SIGNON %d' % (tag, on))
        stores = K.screen_stores(sp.writes)
        if c.kind in (K_FRAME, K_LOAD):
            problems += ['%s: order: %s' % (tag, x)
                         for x in K.order(stores, c.black)]
        elif any(K.kind(s.offset) != 'band' for s in stores):
            problems.append('%s: the sign wrote a colour or an SCB' % tag)
        if c.x3:
            x3 += 1
        elif c.black and full:
            if c.pw is None:
                problems.append('%s: a black step without PW' % tag)
            else:
                mid_screen = rebuild(st.before, at_wipe_step(stores))
                rr = K.compare(c.pw, st.before, mid_screen, region)
                if rr.differ:
                    a, v, ref = rr.differ[0]
                    problems.append('%s: the wipe\'s step (PW) $%04X: $%02X,'
                                    ' ref $%02X (%d bytes differ)' % (
                                        tag, a, v, ref, len(rr.differ)))
        if profile:
            times.append((kind_name(c), ms(profile, sp.end - sp.start)))
    state = None
    if job.chained:
        aux, nib = m.storage('aux', S.S2STATE), m.storage('aux', S.S2PAL)
        state = bytes(aux[S.SS['SS_PALST']:S.SS['SS_PALST'] +
                          S.PALST_SIZE]) + \
            bytes(aux[S.SS['SS_FINW']:S.SS['SS_FINW'] + 256]) + \
            bytes(nib[S.S2PAL_AT['S2P_NIB']:S.S2PAL_AT['S2P_NIB'] +
                      S.S2PAL_SIZE['S2P_NIB']])
    return {'tag': job.tag, 'cases': len(job.cases), 'problems': problems,
            'times': times, 'stray': n_stray, 'stack': stack,
            'writes': len(writes), 'x3': x3, 'state': state}


def tic_vars(c: Case) -> bytes:
    """A frame's tic state as the tics leave it (WI_ACCEL, the card's F_*:
    the reference's at the frame's start)."""
    from native import s2cap as C
    b = c.case.before
    acc = C.val(b, 'wi_stuff65.s:_g_acceleratestage')
    st = C.val(b, 'f_finale65.s:finalestage')
    cnt = C.val(b, 'f_finale65.s:finalecount', 4)
    mid = C.val(b, 'f_finale65.s:midstage')
    if st > 255 or mid > 255:
        raise FinError('%s: finalestage %d, midstage %d: not bytes' % (
            c.name, st, mid))
    return bytes([acc & 0xFF, acc >> 8, st]) + cnt.to_bytes(4, 'little') + \
        bytes([mid])


def run_chain(chain: Sequence[Job], b, work_root: Path,
              gen: Dict[str, int]) -> List[Dict[str, Any]]:
    """A chain's jobs in order, each from the native state the last
    left."""
    out: List[Dict[str, Any]] = []
    state = None
    for i, job in enumerate(chain):
        if i:
            if state is None:
                break
            job = job._replace(state=state)
        res = run_job(job, b, None, work_root, gen)
        out.append(res)
        state = res['state']
    return out


def jobs_of(cs: Sequence[Case], modes: Sequence[str]
            ) -> Tuple[List[Job], List[Job]]:
    """The injected jobs and the chained ones (the finale's frames in
    order from the first one's state, PALST and the nibble tables carried
    by the native code, the tic's state injected as the tics leave it)."""
    inj: List[Job] = []
    if 'injected' in modes:
        for fill, poison in FILLS:
            groups: Dict[Any, List[Case]] = {}
            for c in cs:
                if c.kind == K_SIGNOFF:
                    continue            # with its sign-on, below
                key = (c.run, c.group, c.stage, c.black) \
                    if c.group != 'sign' else (c.name,)
                groups.setdefault(key, []).append(c)
            for g in groups.values():
                g2: List[Case] = []
                for c in g:             # a sign-on's sign-off after it
                    g2.append(c)
                    if c.kind == K_SIGNON:
                        nxt = [x for x in cs if x.run == c.run and
                               x.kind == K_SIGNOFF and x.start > c.start]
                        later = [x for x in cs if x.run == c.run and
                                 x.kind == K_SIGNON and x.start > c.start]
                        if nxt and (not later or nxt[0].start <
                                    later[0].start):
                            g2.append(nxt[0])
                for i in range(0, len(g2), MAX_CASES):
                    part = tuple(g2[i:i + MAX_CASES])
                    inj.append(Job('injected %02X %s..%s' % (
                        fill, part[0].name, part[-1].name), part, fill,
                        poison and part[0].group != 'sign', False,
                        tuple(None for _ in part)))
    chained: List[Job] = []
    if 'chained' in modes:
        fin = [c for c in cs if c.group == 'finale']
        for i in range(0, len(fin), MAX_CASES):
            part = tuple(fin[i:i + MAX_CASES])
            chained.append(Job('chained (%s..%s)' % (part[0].name,
                                                     part[-1].name), part,
                               0xA5, False, True,
                               tuple(tic_vars(c) for c in part)))
    return inj, chained


# ---------------------------------------------------------------------------
# The tic side
# ---------------------------------------------------------------------------

class Tic(NamedTuple):
    name: str
    kind: int                   # 0 f_ticker, 1 f_start
    card: bytes                 # F_STAGE, F_COUNT, F_MID before
    accel: int                  # WI_ACCEL before (after the check)
    action: int
    state: int
    automap: int
    check_set: bool             # the check changed acceleratestage
    want: Dict[str, Any]


def _fin(mem: bytes) -> Tuple[int, int, int]:
    st = int.from_bytes(mem[0:2], 'little')
    cnt = int.from_bytes(mem[2:6], 'little')
    mid = int.from_bytes(mem[6:8], 'little')
    return st, cnt, mid


def _card(st: int, cnt: int, mid: int, name: str) -> bytes:
    if st > 255 or mid > 255:
        raise FinError('%s: finalestage %d, midstage %d: not bytes' % (
            name, st, mid))
    return bytes([st]) + cnt.to_bytes(4, 'little') + bytes([mid])


def tics(run: str = 'finale') -> List[Tic]:
    """F_Ticker's calls (with WI_checkForAccelerate's result: f_ticker's
    input) and F_StartFinale's, in order."""
    from native import s2cap as C
    cap = load_capture(run)
    calls = cap.data['calls']
    checks = {c['parent']: c for c in calls
              if c['name'] == 'WI_checkForAccelerate'}
    out = []
    for c in sorted(calls, key=lambda x: x['cycles']):
        if c['name'] == 'F_Ticker':
            i, o = C.mem_of(c, 'in'), C.mem_of(c, 'out')
            ch = checks.get(c['call'])
            if ch is None:
                raise FinError('F_Ticker %d without its check' % c['call'])
            ci, co = C.mem_of(ch, 'in')[0], C.mem_of(ch, 'out')[0]
            if ci != i[2]:
                raise FinError('F_Ticker %d: the check\'s acceleratestage '
                               'is not the entry\'s' % c['call'])
            st, cnt, mid = _fin(i[0])
            name = '%s/t%06d.%d' % (run, c['frame'], c['call'])
            ost, ocnt, omid = _fin(o[0])
            out.append(Tic(name, 0, _card(st, cnt, mid, name),
                           int.from_bytes(co, 'little'),
                           int.from_bytes(i[1], 'little'), GS_FINALE, 0,
                           ci != co, {
                               'card': _card(ost, ocnt, omid, name),
                               'accel': int.from_bytes(o[2], 'little'),
                               'action': int.from_bytes(o[1], 'little')}))
        elif c['name'] == 'F_StartFinale':
            i, o = C.mem_of(c, 'in'), C.mem_of(c, 'out')
            name = '%s/start%06d' % (run, c['frame'])
            st, cnt, mid = _fin(i[0])
            ost, ocnt, omid = _fin(o[0])
            out.append(Tic(name, 1, _card(st, cnt, mid, name),
                           int.from_bytes(i[4], 'little'),
                           int.from_bytes(i[1], 'little'),
                           int.from_bytes(i[2], 'little'),
                           int.from_bytes(i[3], 'little') & 0xFF, False, {
                               'card': _card(ost, ocnt, omid, name),
                               'accel': int.from_bytes(o[4], 'little'),
                               'action': int.from_bytes(o[1], 'little'),
                               'state': int.from_bytes(o[2], 'little'),
                               'automap': int.from_bytes(o[3], 'little')
                               & 0xFF}))
    return out


def tic_record(t: Tic, mode: int) -> bytes:
    r = bytearray(TIC_REC)
    r[0] = t.kind
    r[1] = mode
    r[2:8] = t.card
    r[8:10] = t.accel.to_bytes(2, 'little')
    r[10:12] = t.action.to_bytes(2, 'little')
    r[12:14] = t.state.to_bytes(2, 'little')
    r[14] = t.automap
    return bytes(r)


def tic_run(ts: Sequence[Tic], chained: bool, b, profile: Optional[str],
            work_root: Path, gen: Dict[str, int]) -> Dict[str, Any]:
    """Every tic in one call of fint_tics: injected (each from the
    reference's state) or chained (the card's F_* carried by the native
    code from the first; WI_ACCEL taken when the check changed it, as the
    hook calls the check first)."""
    from native import llayout as LL, s2run as SR
    if len(ts) > 2900:
        raise FinError('%d tics: more than a bank' % len(ts))
    recs_in = bytearray(16) + b''.join(
        tic_record(t, 7 if not chained or k == 0 else
                   (6 if t.kind == 1 else (2 if t.check_set else 0)))
        for k, t in enumerate(ts))
    recs_in[0:2] = len(ts).to_bytes(2, 'little')
    recs = [(1, TIC_IN, 0x0200, bytes(recs_in)),
            (1, TIC_OUT, 0x0200, bytes(TIC_REC * len(ts)))] + \
        card_records(gen) + [(0, 0, LL.G['WI_ACCEL'], bytes(2))]
    work = Path(tempfile.mkdtemp(prefix='tmp-tic-', dir=str(work_root)))
    problems: List[str] = []
    mode = 'chained' if chained else 'injected'
    try:
        r = SR.run(b, [SR.Call('fint_tics', TIC_IN, TIC_OUT)], 0xA5, work,
                   extra_records=recs, write_log=False,
                   snap_ranges='aux%d:0200-%04X' % (
                       TIC_OUT, 0x0200 + TIC_REC * len(ts) - 1),
                   profile=profile, extra_args=[
                       '--write-log', 'main:0000-00FF,main:0200-FFFF,lc,'
                       'aux1-127,cpu:C000-C0FF',
                       '--write-log-file', str(work / 'writes.log'),
                       '--write-log-limit', str(SR.WRITE_LOG_LIMIT)])
        if r.ended() != 'stop' or r.status() != S.S2S['DONE']:
            return {'problems': ['tics (%s): the run ended %s' % (
                mode, r.ended())], 'us': [], 'stray': 0, 'mode': mode}
        snap = r.calls()[0].storage('aux', TIC_OUT)
        writes = r.writes()
        n_stray, stray_list = SR.stray(writes, owners(b, r.loads, gen))
        sps = spans(b, writes)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    if n_stray:
        problems.append('tics (%s): %d stray writes: %s' % (
            mode, n_stray, stray_list[:3]))
    if len(sps) != len(ts):
        problems.append('tics (%s): %d calls timed for %d' % (
            mode, len(sps), len(ts)))
    for k, t in enumerate(ts):
        o = bytes(snap[0x0200 + TIC_REC * k:0x0200 + TIC_REC * (k + 1)])
        got = {'card': o[0:6], 'accel': int.from_bytes(o[6:8], 'little'),
               'action': int.from_bytes(o[8:10], 'little'),
               'state': int.from_bytes(o[10:12], 'little'),
               'automap': o[12] & 1}
        want = dict(t.want)
        if 'automap' in want:
            want['automap'] &= 1
        for key, v in want.items():
            if got[key] != v:
                problems.append('%s (%s): %s %s, ref %s' % (
                    t.name, mode, key, got[key].hex() if key == 'card'
                    else got[key], v.hex() if key == 'card' else v))
                break
    us = [ms(profile, sp.end - sp.start) * 1000.0 for sp in sps] \
        if profile else []
    return {'problems': problems, 'us': us, 'stray': n_stray,
            'tics': len(ts), 'mode': mode,
            'starts': sum(1 for t in ts if t.kind == 1)}


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def check(profile: Optional[str] = None, obj: Path = OUT, jobs: int = JOBS,
          modes: Sequence[str] = ('injected', 'chained')) -> Dict[str, Any]:
    b = build_of(obj)
    gen = gen_values()
    cs, excluded, static = all_cases()
    if not cs:
        raise FinError('no case in the captures')
    inj, chained = jobs_of(cs, modes)
    ts = tics()
    work_root = Path(tempfile.mkdtemp(prefix='tmp-s2fin-run-',
                                      dir=str(obj)))
    try:
        with ThreadPoolExecutor(max(1, min(jobs, 4))) as ex:
            futs = [ex.submit(run_job, j, b, profile if j.fill == 0xA5
                              else None, work_root, gen) for j in inj]
            cfut = ex.submit(run_chain, chained, b, work_root, gen) \
                if chained else None
            tfuts = [ex.submit(tic_run, ts, m == 'chained', b, profile if
                               m == 'injected' else None, work_root, gen)
                     for m in modes]
            results = [f.result() for f in futs]
            if cfut is not None:
                results += cfut.result()
            tres = [f.result() for f in tfuts]
    finally:
        shutil.rmtree(str(work_root), ignore_errors=True)
    problems = [p for r in results for p in r['problems']]
    problems += [p for r in tres for p in r['problems']]
    kinds: Dict[str, int] = {}
    for c in cs:
        k = kind_name(c)
        kinds[k] = kinds.get(k, 0) + 1
    return {
        'cases': len(cs), 'kinds': kinds, 'excluded': excluded,
        'static_page_frames': static,
        'x3': sum(r['x3'] for r in results
                  if r['tag'].startswith('injected A5')),
        'x3_frames': [c.name for c in cs if c.x3],
        'tics': len(ts), 'runs': [{k: v for k, v in r.items()
                                   if k not in ('times', 'state')}
                                  for r in results],
        'tic_runs': [{k: v for k, v in r.items() if k != 'us'}
                     for r in tres],
        'times': [x for r in results for x in r['times']],
        'tic_us': [x for r in tres for x in r['us']],
        'stray': sum(r['stray'] for r in results + tres),
        'stack': max((r['stack'] or 0) for r in results),
        'problems': problems, 'profile': profile, 'modes': list(modes)}


# ---------------------------------------------------------------------------
# The planted bugs (each in a scratch copy of the sources)
# ---------------------------------------------------------------------------

SPEED = '''speed:
        lda F_MID
        bne @fast
'''
SPEED_PLANTED = '''speed:
        lda F_MID               ; (planted: the mid stage ignored)
'''
PLANTED = (
    ('the text speed\'s mid stage ignored', (
        ('s2_fin.s', SPEED, SPEED_PLANTED),
        ('s2t_fin.s', SPEED, SPEED_PLANTED))),
    ('the new line 11 rows down off by one', (
        ('s2_fin.s', 'TEXT_DY  = 11\n', 'TEXT_DY  = 12\n'),)),
    ('the sign\'s rows not put back', (
        ('s2_fin.s', '''        jsr sgrows
        jsr s2_publish
        stz s2_begun
@r:     rts
''', '''        jsr sgrows
        stz s2_begun            ; (planted: not published)
@r:     rts
'''),)),
)


def plant(k: int, jobs: int = JOBS) -> Tuple[str, List[str]]:
    """Planted bug k in a scratch copy: built, then the injected checks
    (both fills, the tics); the problems it gives."""
    name, edits = PLANTED[k]
    scratch = Path(tempfile.mkdtemp(prefix='tmp-s2fin-plant-', dir=str(OUT)))
    try:
        src = scratch / 'src'
        (src / 'm11').mkdir(parents=True)
        shutil.copy(str(SOURCE / 'm11.mk'), str(src / 'm11.mk'))
        for f in ('s2lay.mk', 's2fin.mk'):
            shutil.copy(str(SOURCE / 'm11' / f), str(src / 'm11' / f))
        for f in ('s2_fin.s', 's2t_fin.s', 's2_fint.s'):
            shutil.copy(str(SOURCE / f), str(src / f))
        for source, old, new in edits:
            text = (src / source).read_text()
            if text.count(old) != 1:
                raise FinError('planted %r: %r is not found once in %s' % (
                    name, old[:40], source))
            (src / source).write_text(text.replace(old, new))
        m11 = scratch / 'm11'
        (m11 / 'shared' / 'gen').mkdir(parents=True)
        for f in KEEP_GEN:
            shutil.copy(str(SHARED_GEN / f), str(m11 / 'shared' / 'gen' / f))
        (m11 / 's2data').mkdir()
        for f in (M11 / 's2data').glob('s2data.*'):
            shutil.copy(str(f), str(m11 / 's2data' / f.name))
        make(src, m11)
        try:
            res = check(None, m11 / 's2fin', jobs, ('injected',))
        except Exception as error:  # a run that fails is a catch too
            text = str(error).strip().splitlines()
            return name, ['the run failed: %s' % (text[0] if text else
                                                  type(error).__name__)]
        return name, res['problems']
    finally:
        shutil.rmtree(str(scratch), ignore_errors=True)


def planted(jobs: int = JOBS) -> List[Dict[str, Any]]:
    out = []
    for k in range(len(PLANTED)):
        name, problems = plant(k, jobs)
        out.append({'bug': name, 'caught': bool(problems),
                    'failures': len(problems),
                    'first': problems[0] if problems else None})
    return out


# ---------------------------------------------------------------------------
# The sizes, the timing, the report
# ---------------------------------------------------------------------------

def module_segments(text: str, module: str) -> Dict[str, int]:
    part = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    segs: Dict[str, int] = {}
    mod = None
    for line in part.splitlines():
        if line and not line.startswith(' ') and line.rstrip().endswith(':'):
            mod = Path(line.strip()[:-1].split('(')[0]).stem
            continue
        f = line.split()
        if mod == module and f:
            segs[f[0]] = int(f[2][5:], 16)
    return segs


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """FINW (finw: the image without the test glue) against its room and
    the size table; s2_fin's segments against the part's budget; the tic
    side's (s2t_fin in s2ft) against its 250 B."""
    text = (obj / 'finw.map').read_text()
    fin = module_segments(text, 's2_fin')
    tic = module_segments((obj / 's2ft.map').read_text(), 's2t_fin')
    return {'s2_fin': fin, 'code': fin.get('S2CODE', 0), 'code_budget': 1600,
            'data': fin.get('S2RODATA', 0) + fin.get('S2DATA', 0),
            # (500 until wave 6's integration, S2FIN-3: the end text and
            # the font's table)
            'data_budget': 700, 'tic': sum(tic.values()), 'tic_budget': 250,
            'table': (obj / 'finw.sizes').read_text().splitlines()}


def stats(values: Sequence[float]) -> Dict[str, float]:
    v = sorted(values)
    if not v:
        return {}
    return {'n': len(v), 'median': round(v[len(v) // 2], 3),
            'p99': round(v[min(len(v) - 1, (99 * len(v)) // 100)], 3),
            'worst': round(v[-1], 3)}


def timing(res: Dict[str, Any]) -> Dict[str, Any]:
    by: Dict[str, List[float]] = {}
    for kind, v in res['times']:
        by.setdefault(kind + ' (ms)', []).append(v)
    out = {k: stats(v) for k, v in sorted(by.items())}
    out['tic (us)'] = stats(res['tic_us'])
    return out


def report(jobs: int = JOBS) -> Dict[str, Any]:
    t0 = time.time()
    if not all((CAP / (r + '.z')).exists() for r in RUNS):
        capture_all(jobs)
    out: Dict[str, Any] = {'part': 's2fin', 'checks': {}, 'timing': {}}
    for profile in PROFILES:
        res = check(profile, OUT, jobs,
                    ('injected', 'chained') if profile == 'f121'
                    else ('injected',))
        out['checks'][profile] = {k: v for k, v in res.items()
                                  if k not in ('times', 'tic_us')}
        out['timing'][profile] = timing(res)
    sz = sizes()
    out['sizes'] = sz
    stored = sum(n for m, n in S.read_map(
        (OUT / 'finw.map').read_text()).modules.items()
        if S.module_row(m) != 'MATHW')
    out['load_ms'] = round(stored * LOAD_US / 1000.0, 2)
    out['drain_ms'] = {'a whole screen': round((32000 + 512) * DRAIN_US /
                                               1000.0, 2),
                       'the sign\'s rows': round(BUSY_H * 160 * DRAIN_US /
                                                 1000.0, 2)}
    out['planted'] = planted(jobs)
    problems = [p for c in out['checks'].values() for p in c['problems']]
    problems += ['planted bug not caught: %s' % p['bug']
                 for p in out['planted'] if not p['caught']]
    if any('room' in line and 'OVER' in line for line in sz['table']):
        problems.append('FINW is over its room')
    if sz['tic'] > sz['tic_budget']:
        problems.append('s2t_fin is over its budget')
    out['problems'] = problems
    out['ok'] = not problems
    out['seconds'] = round(time.time() - t0, 1)
    (OUT / 'report.json').write_text(json.dumps(out, indent=1) + '\n')
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--inc', type=Path)
    ap.add_argument('--capture', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--planted', action='store_true')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--profile', choices=PROFILES)
    ap.add_argument('--mode', choices=('injected', 'chained'))
    ap.add_argument('--jobs', type=int, default=JOBS)
    args = ap.parse_args(argv)
    if args.inc:
        write_inc(args.inc)
        return 0
    if args.capture:
        for r in capture_all(args.jobs):
            print(json.dumps(r))
        return 0
    if args.check:
        res = check(args.profile, OUT, args.jobs,
                    (args.mode,) if args.mode else ('injected', 'chained'))
        print('%d cases %s, %d tics, %d runs, %d stray, stack %d B; '
              'excluded %d; X3 %d; static page frames %s' % (
                  res['cases'], res['kinds'], res['tics'], len(res['runs']),
                  res['stray'], res['stack'], len(res['excluded']),
                  res['x3'], res['static_page_frames']))
        if args.profile:
            print(json.dumps(timing(res)))
        for p in res['problems'][:30]:
            print('  ' + p)
        print('%d problems' % len(res['problems']))
        return 1 if res['problems'] else 0
    if args.planted:
        bad = 0
        for p in planted(args.jobs):
            print('%-45s %s' % (p['bug'], 'caught (%d): %s' % (
                p['failures'], p['first']) if p['caught'] else 'NOT CAUGHT'))
            bad += not p['caught']
        return 1 if bad else 0
    if args.all:
        out = report(args.jobs)
        print(json.dumps({k: out[k] for k in ('timing', 'planted', 'load_ms',
                                              'drain_ms', 'ok')}, indent=1))
        for p in out['problems'][:30]:
            print('  ' + p)
        return 0 if out['ok'] else 1
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
