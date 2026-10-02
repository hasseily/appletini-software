#!/usr/bin/env python3
"""Part s2stbar of milestone 11 (docs/SCREENS.md 1.5.1, 1.6, 4.1, 4.4,
4.7, 6; docs/m11-parts/s2stbar.md): the status bar and the face, checked
against ref816.

1. The model (tools/native/s2stmodel.py) against the reference: every
   ST_Ticker of the captured runs (part s2cap's call logs, the turned
   head's positions from this part's own capture `pos`), every level
   frame's ST_Drawer (the screen's rows 168-199, STCACHE, the widgets'
   old values and the marks after it), ST_Start (`pos`'s log), and the
   synthetic cases by ref816 --call (`synth`: the menu's stHide, the
   glyphs and places no run shows, the face's rare paths).
2. The native code on a2vm: src/native/s2_st.s (P2DW: st_drawer) in the
   test image s2sb, src/native/s2t_st.s (st_ticker, st_start) in the test
   image s2st; each case injected from both fills, the frames also with
   every byte the reference marked poisoned, and demo3's level frames
   chained (the 2D state carried by the native code alone).

Usage:  python3 tools/native/s2stbar.py --inc OUT/s2stbar.inc
        python3 tools/native/s2stbar.py --capture [--runs demo3,...]
        python3 tools/native/s2stbar.py --model
        python3 tools/native/s2stbar.py --native [--jobs 2]
        python3 tools/native/s2stbar.py --all [--jobs 2]   (the checkpoint)

Each check mode (--capture, --model, --native, --tics, --synth, --chain,
--plants, --all) exits with status 1 when it reports a problem (or a
planted bug it does not catch), 0 otherwise.
"""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zlib
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import s2cap as C, s2stmodel as M  # noqa: E402

ROOT = C.ROOT
BUILD = ROOT / 'build'
M11 = BUILD / 'native' / 'm11'
WORK = M11 / 's2stbar'
POS = WORK / 'pos'
POS_FORMAT = 's2stbar-pos 1'
# the runs whose ST_Ticker calls are compared (the checkpoint's demo3 and
# newgame, then the other runs that play a level)
TIC_RUNS = ('demo3', 'newgame', 'tour', 'stbar', 'menus', 'palette',
            'automap', 'finale', 'signs')


class StError(Exception):
    pass


# ---------------------------------------------------------------------------
# The capture of the turned head's inputs and of ST_Start (`pos`)
# ---------------------------------------------------------------------------

def st_block() -> str:
    """st_stuff65.s's znear block as a call-log range (s2cap's form)."""
    return 'st_stuff65.s:%s:%d' % C._znear_first('st_stuff65.s')


PLAYER_RANGE = 'g_game65.s:_g_player:155'


def pos_routines() -> List[Any]:
    """ST_Ticker as part s2cap logs it (so the calls pair up one to one),
    R_PointToAngle3 with its arguments (A, X: dx; _Dp[0-3]: dy) and
    the player's angle turnHead keeps in ST_PX, ST_PW, and ST_Start with
    the state and newpal (I_SetPalette's)."""
    st = st_block()
    return [('ST_Ticker', 'st_stuff65.s:ST_Ticker,mem=%s+%s'
             % (st, PLAYER_RANGE)),
            ('R_PointToAngle3', 'R_PointToAngle3,in=dp:_Dp:4+'
             'st_stuff65.s:ST_PX:4'),
            ('ST_Start', 'st_stuff65.s:ST_Start,mem=%s+%s+'
             'i_viigs65.s:newpal:2' % (st, PLAYER_RANGE))]


def capture_pos(run: str) -> Dict[str, Any]:
    """One run of the release on ref816 (part s2cap's script and machine)
    with pos_routines' call log: every ST_Ticker's entry memory (its
    SHA-256, to pair it with s2cap's log), the R_PointToAngle3 calls made
    under a ST_Ticker (turnHead's: dx, dy, the player's angle, the
    result), every ST_Start. Written to POS/RUN.json.z."""
    POS.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='tmp-pos-%s-' % run,
                                 dir=str(WORK)))
    try:
        sink = C.CallSink()
        logged = pos_routines()
        result = C.machine(run, work, [], logged, None, sink.feed)
        names = [n for n, _ in logged]
        tickers: Dict[int, int] = {}       # call number -> its index
        out: Dict[str, Any] = {'format': POS_FORMAT, 'run': run,
                               'problems': list(result['problems']),
                               'tickers': [], 'pta3': {}, 'starts': []}
        pending: List[Dict[str, Any]] = []
        for c in sink.lines:
            name = names[c['routine']]
            if name == 'ST_Ticker':
                k = len(out['tickers'])
                tickers[c['call']] = k
                mem = C.mem_of(c, 'in')
                out['tickers'].append(hashlib.sha256(
                    b''.join(mem)).hexdigest()[:20])
            elif name == 'R_PointToAngle3':
                pending.append(c)
            elif name == 'ST_Start':
                out['starts'].append({
                    'in': [m.hex() for m in C.mem_of(c, 'in')],
                    'out': [m.hex() for m in C.mem_of(c, 'out')],
                    'frame': c.get('frame'), 'cycles': c.get('cycles')})
        # a callee's line comes before its caller's: pair them afterwards
        for c in pending:
            k = tickers.get(c.get('parent'))
            if k is None:
                continue
            regs = c['in']
            dp, px = C.mem_of(c, 'in')
            out['pta3'][str(k)] = {
                'dx': (regs['a'] & 0xFFFF) | (regs['x'] & 0xFFFF) << 16,
                'dy': int.from_bytes(dp, 'little'),
                'angle': int.from_bytes(px, 'little'),
                'result': (c['out']['a'] & 0xFFFF) |
                (c['out']['x'] & 0xFFFF) << 16}
        blob = zlib.compress(json.dumps(out, sort_keys=True).encode(), 6)
        C.write_atomic(POS / ('%s.json.z' % run), blob)
        return out
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def load_pos(run: str) -> Dict[str, Any]:
    path = POS / ('%s.json.z' % run)
    if not path.exists():
        raise StError('%s is missing: python3 tools/native/s2stbar.py '
                      '--capture --runs %s' % (path, run))
    out = json.loads(zlib.decompress(path.read_bytes()))
    if out.get('format') != POS_FORMAT:
        raise StError('%s: not a pos file' % path)
    return out


# ---------------------------------------------------------------------------
# Upstream's state in the dumps and call logs
# ---------------------------------------------------------------------------

class Ref:
    """Upstream's places: the st znear block (st_stuff65.s, from
    statusbarnum), the player (offsets.inc's OFS_PL_*)."""

    def __init__(self):
        from native import s2state as SS
        self.st = C.sym('st_stuff65.s:statusbarnum')
        self.st_size = C._znear_first('st_stuff65.s')[1]
        self.pl = C.sym('g_game65.s:_g_player')
        self.ofs = SS.offsets()
        self.largeammo = C.sym('st_stuff65.s:largeammo') & 0xFFFF
        self.fps = C.sym('_g_fps_framerate') & 0xFFFF
        self.ammo = (self.pl + self.ofs['OFS_PL_AMMO']) & 0xFFFF

    def off(self, name: str) -> int:
        return C.sym('st_stuff65.s:' + name) - self.st

    def word(self, st: bytes, name: str, k: int = 0) -> int:
        at = self.off(name) + 2 * k
        return int.from_bytes(st[at:at + 2], 'little')

    def pword(self, pl: bytes, key: str, k: int = 0, size: int = 2) -> int:
        at = self.ofs[key] + 2 * k
        return int.from_bytes(pl[at:at + size], 'little')

    def ready_of(self, ptr: int) -> tuple:
        if ptr == 0:
            return ('none',)        # before the first ST_createWidgets
        if ptr == self.largeammo:
            return ('large',)
        if ptr == self.fps:
            return ('fps',)
        k = (ptr - self.ammo) & 0xFFFF
        if k % 2 or k > 0x1FE:
            raise StError('W_READY points at $%04X' % ptr)
        return ('ammo', k // 2)     # (k > 7: past the player, X-ST1)

    def ready_ptr(self, src: tuple) -> int:
        if src[0] == 'none':
            return 0
        if src[0] == 'large':
            return self.largeammo
        if src[0] == 'fps':
            return self.fps
        return (self.ammo + 2 * src[1]) & 0xFFFF

    def tick(self, st: bytes) -> M.Tick:
        w = lambda n, k=0: self.word(st, n, k)  # noqa: E731
        return M.Tick(
            w('st_faceindex'), w('st_facecount'), w('st_priority'),
            w('st_oldhealth'), w('st_lastattackdown'), w('st_oldhealthPO'),
            w('st_lastcalc'), w('st_randomnumber'),
            tuple(w('keyboxes', k) for k in range(M.NUMCARDS)),
            tuple(w('oldweaponsowned', k) for k in range(M.NUMWEAPONS)),
            w('st_refreshed'), w('st_running'), w('st_palette'),
            self.ready_of(self.word(st, 'W_READY', 4)))

    def player(self, pl: bytes) -> M.Player:
        p = lambda key, k=0, n=2: self.pword(pl, key, k, n)  # noqa: E731
        return M.Player(
            p('OFS_PL_HEALTH'), p('OFS_PL_ARMORPOINTS'),
            tuple(p('OFS_PL_AMMO', k) for k in range(8)),
            p('OFS_PL_READYWEAPON'),
            tuple(p('OFS_PL_WEAPONOWNED', k) for k in range(M.NUMWEAPONS)),
            tuple(p('OFS_PL_CARDS', k) for k in range(M.NUMCARDS)),
            tuple(p('OFS_PL_POWERS', k) for k in range(6)),
            p('OFS_PL_CHEATS'), p('OFS_PL_DAMAGECOUNT'),
            p('OFS_PL_BONUSCOUNT'), p('OFS_PL_ATTACKDOWN'),
            p('OFS_PL_MO', 0, 4), p('OFS_PL_ATTACKER', 0, 4))

    def old(self, st: bytes) -> Dict[str, int]:
        """The widgets' old values (NW_OLDNUM, IW_OLDINUM) in the znear
        block's order."""
        out = {}
        at = self.off('W_READY')
        for w in M.WIDGETS:
            if isinstance(w, M.Num):
                out[w.name] = int.from_bytes(st[at + 6:at + 8], 'little')
                at += 12
            else:
                out[w.name] = int.from_bytes(st[at + 4:at + 6], 'little')
                at += 10
        return out


_REF: Optional[Ref] = None


def ref() -> Ref:
    global _REF
    if _REF is None:
        _REF = Ref()
    return _REF


TICK_STATE = ('faceindex', 'facecount', 'priority', 'oldhealth',
              'lastattackdown', 'oldhealthPO', 'lastcalc', 'randomnumber',
              'keyboxes', 'oldweaponsowned', 'ready')


def tick_diff(a: M.Tick, b: M.Tick, fields=TICK_STATE) -> List[str]:
    return ['%s %s, ref %s' % (f, getattr(a, f), getattr(b, f))
            for f in fields if getattr(a, f) != getattr(b, f)]


# ---------------------------------------------------------------------------
# The release's tables and the 2D store's glyphs (build/ only)
# ---------------------------------------------------------------------------

class Assets(NamedTuple):
    glyphs: M.Glyphs
    places: Dict[str, Tuple[int, int, int]]   # name: bank, address, size
    handles: Dict[str, int]
    nibtab: bytes               # 16 KB: palettes 1-8 from GSSTAT, else 0
    gsstat: bytes
    wammo: Tuple[int, ...]      # weaponinfo[w].ammo
    tanto: Tuple[int, ...]
    banks: Dict[int, bytearray]  # the 2D store's banks (GFX.n read back)


_ASSETS: Optional[Assets] = None
WAMMO_ENTRIES = 11
S2DATA = M11 / 's2data'
TABLES = BUILD / 'native' / 'render' / 'tables' / 'math'


def assets() -> Assets:
    global _ASSETS
    if _ASSETS is not None:
        return _ASSETS
    import struct
    from native import s2data as SD, s2palmodel as PM, umodel as U
    man_path = S2DATA / 's2data.json'
    if not man_path.exists():
        raise StError('%s is missing: make -C src/native -f m11.mk part '
                      'P=s2data' % man_path)
    man = json.loads(man_path.read_text())
    banks = SD.read_back(SD.load_files(S2DATA))
    places, handles, lumps = {}, {}, {}
    for e in man['lumps']:
        places[e['name']] = (e['bank'], e['address'], e['size'])
        handles[e['name']] = e['handle']
        if e['name'] in M.GLYPHS or e['name'] == 'GSSTAT':
            lumps[e['name']] = bytes(banks[e['bank']][
                e['address']:e['address'] + e['size']])
    gsstat = lumps.pop('GSSTAT')
    nib = bytearray(16 * 0x400)
    for n in range(1, PM.STAT_PALS + 1):
        at = PM.STAT_RECS + (n - 1) * PM.PALREC_SIZE + PM.PALREC_PAIRS
        nib[n * 0x400:(n + 1) * 0x400] = PM.build_nibtab(gsstat[at:at + 256])
    rel = U.Release()
    # weaponinfo's ammo types, and the 2 entries after its 9 that
    # readyNum reads for a ready weapon out of range (wp_nochange 10:
    # stbar.script's state after its health 0 poke, X-ST1): the release's
    # bytes past the table, as upstream reads them
    wi = rel.table('p_pspr65.s:weaponinfo', 12 * WAMMO_ENTRIES)
    wammo = tuple(struct.unpack_from('<H', wi, 12 * w)[0]
                  for w in range(WAMMO_ENTRIES))
    planes = [(TABLES / ('tanto%d.bin' % k)).read_bytes() for k in range(4)]
    tanto = tuple(sum(planes[k][i] << (8 * k) for k in range(4))
                  for i in range(2049))
    _ASSETS = Assets(M.Glyphs(lumps), places, handles, bytes(nib), gsstat,
                     wammo, tanto, banks)
    return _ASSETS


# ---------------------------------------------------------------------------
# The ticker: the model against the reference's ST_Ticker calls
# ---------------------------------------------------------------------------

class TicCase(NamedTuple):
    run: str
    k: int                      # the call's index among the run's
    before: M.Tick
    after: M.Tick
    player: M.Player
    poked: bool                 # the player changed inside the call
    rnd: int
    pos: Optional[M.Pos]
    pta3: Optional[int]         # the reference's R_PointToAngle3 result
    st_in: bytes                # the st block at the entry, and the exit
    st_out: bytes


def tic_cases(run: str) -> List[TicCase]:
    """The run's ST_Ticker calls (part s2cap's log), each paired with
    this part's capture `pos` (the same call: the SHA-256 of its entry
    memory) for turnHead's inputs."""
    r = ref()
    calls = C.RunCases(C.run_dir(run)).calls().of('ST_Ticker')
    pos = load_pos(run)
    if len(pos['tickers']) != len(calls):
        raise StError('%s: %d ST_Ticker in s2cap\'s log, %d in pos'
                      % (run, len(calls), len(pos['tickers'])))
    out = []
    for k, c in enumerate(calls):
        mem_in = C.mem_of(c, 'in')
        mem_out = C.mem_of(c, 'out')
        sha = hashlib.sha256(b''.join(mem_in)).hexdigest()[:20]
        if sha != pos['tickers'][k]:
            raise StError('%s: ST_Ticker %d differs between the captures'
                          % (run, k))
        st_in, pl_in = mem_in
        st_out, pl_out = mem_out
        # ST_Ticker writes nothing of the player: a difference between its
        # entry and its return is a script's poke inside the call (ref816
        # pokes at its own tic boundary, which can fall there: palette.
        # script's damagecount once), and the routine read the new value
        poked = pl_in != pl_out
        after = r.tick(st_out)
        p3 = pos['pta3'].get(str(k))
        out.append(TicCase(run, k, r.tick(st_in), after,
                           r.player(pl_out if poked else pl_in), poked,
                           after.randomnumber,
                           M.Pos(p3['dx'], p3['dy'], p3['angle'])
                           if p3 else None,
                           p3['result'] if p3 else None, st_in, st_out))
    return out


def ticker() -> M.Ticker:
    a = assets()
    return M.Ticker(a.wammo, a.tanto)


def tic_model(runs: Sequence[str]) -> Dict[str, Any]:
    """Every ST_Ticker of the runs through the model: the state after it
    equal to the reference's; turnHead's R_PointToAngle3 equal; the
    paths taken counted."""
    tk = ticker()
    out: Dict[str, Any] = {'runs': {}, 'paths': {}, 'problems': []}
    for run in runs:
        n = 0
        for tc in tic_cases(run):
            got, tr = tk.ticker(tc.before, tc.player, tc.rnd, 0, tc.pos)
            for p in tr.paths:
                out['paths'][p] = out['paths'].get(p, 0) + 1
            d = tick_diff(got, tc.after)
            if tr.badguyangle is not None and tr.badguyangle != tc.pta3:
                d.append('R_PointToAngle3 $%08X, ref $%08X'
                         % (tr.badguyangle, tc.pta3))
            if (tc.pos is None) != (tr.badguyangle is None):
                d.append('turnHead %s, the reference\'s %s' % (
                    tr.badguyangle is not None, tc.pos is not None))
            if d:
                out['problems'].append('%s ST_Ticker %d: %s'
                                       % (run, tc.k, '; '.join(d[:4])))
            if tc.poked:
                out['poked'] = out.get('poked', []) + ['%s:%d' % (run,
                                                                tc.k)]
            n += 1
        out['runs'][run] = n
    return out


# ---------------------------------------------------------------------------
# The drawer: the model against the reference's level frames
# ---------------------------------------------------------------------------

GS_LEVEL = 0
SCREEN_ROWS = (M.ST_Y * M.ROW, 200 * M.ROW)     # rows 168-199 of $2000
SCB_AT = 0x9D00 - 0x2000


class FrameCase(NamedTuple):
    """A level frame's status bar: what ST_Drawer reads and what the
    reference has after it."""
    run: str
    name: str
    k: int                      # the frame's index in the run
    tick: M.Tick                # the st block at the start (PD0)
    player: M.Player
    poked: Tuple[str, ...]      # the fields a script poked inside the frame
    full_map: bool              # a full automap frame (AM_Drawer marks)
    menuactive: int
    fps_show: int
    fps_rate: int
    old: Dict[str, int]
    stcache_valid: bool
    scb: bytes                  # i_viigs65.s's scb (200)
    screen: bytes               # aux 0 $2000-$9FFF at the start
    stcache: bytes
    message_on: int
    mhid: int
    text_shown: int
    # after
    screen_after: bytes
    stcache_after: bytes
    old_after: Dict[str, int]
    refreshed_after: int
    drb: bytes                  # the marks of rows 168-199 at PDF
    dre: bytes
    marked: Tuple[int, ...]     # screen offsets the frame marked
    records: Tuple              # s2state's injection of the 'stbar' screen
    unfit: Tuple
    text_raw: bytes             # iigs_textShown's 4 bytes
    strip: bool = False         # rows 0-9 compared (stHide cleared them)


def level_frame(case: C.Case) -> bool:
    b = case.before
    if b.point != 'PD0:display' or case.one('PDF') is None:
        return False
    if b.word(C.sym('g_game65.s:_g_gamestate')) != GS_LEVEL:
        return False
    return b.word(C.sym('_g_gametic'), 4) != b.word(C.sym('_g_basetic'), 4)


def frame_case(run: str, k: int, e: Dict[str, Any], case: C.Case
               ) -> FrameCase:
    r = ref()
    b, pdf = case.before, case.one('PDF')
    st0 = b.get(r.st, r.st_size)
    st1 = pdf.get(r.st, r.st_size)
    pl0 = b.get(r.pl, 155)
    pl1 = pdf.get(r.pl, 155)
    sym = C.sym
    drb = pdf.get(sym('i_viigs65.s:DRB'), 200)
    dre = pdf.get(sym('i_viigs65.s:DRE'), 200)
    marked = []
    for row in range(M.ST_Y, 200):
        if dre[row]:
            marked += range(row * M.ROW + drb[row], row * M.ROW + dre[row])
    fps_at = sym('_g_fps_framerate')
    mhid_at = sym('VW_MHID')
    player, poked = seen_player(r.tick(st0), r.player(pl0), r.player(pl1),
                                r.old(st1))
    mode = b.word(sym('am_map65.s:automapmode'))
    from native import s2state as SS
    inj = SS.inject(case, 'stbar', 0, with_screen=False)
    return FrameCase(
        run, e['name'], k, r.tick(st0), player, poked,
        mode & 3 == 1,
        b.word(sym('m_menu65.s:_g_menuactive')), b.word(sym('_g_fps_show')),
        b.word(fps_at) if b.has(fps_at, 2) else 0,
        r.old(st0),
        b.word(sym('i_viigs65.s:stcachenum')) ==
        r.word(st0, 'statusbarnum'),
        b.get(sym('i_viigs65.s:scb'), 200), case.screen_before,
        case.carried('STCACHE'), b.word(sym('hu_stuff65.s:message_on')),
        b.word(mhid_at) if b.has(mhid_at, 2) else 0,   # (captured since
        b.word(sym('i_viigs65.s:iigs_textShown')),      # wave 4)
        case.screen_after, case.carried('STCACHE', after=True),
        r.old(st1), r.word(st1, 'st_refreshed'),
        drb[M.ST_Y:], dre[M.ST_Y:], tuple(marked), tuple(inj.records),
        tuple(inj.unfit), b.get(sym('i_viigs65.s:iigs_textShown'), 4))


def seen_player(t: M.Tick, p0: M.Player, p1: M.Player,
                old_after: Dict[str, int]) -> Tuple[M.Player, Tuple]:
    """The player as ST_Drawer read it. display writes nothing of the
    player, but a script's poke can land inside the frame (ref816 pokes
    at its own tic boundary), and a cheat of buildNewTiccmds's events
    after ST_Drawer (the tour's god mode): a field ST_Drawer reads that
    differs between PD0 and PDF takes the value its widget shows after
    the frame (its old value: what drawNum or updateIcon was given),
    which must be one of the two. The fields so taken from PDF."""
    reads: Dict[Tuple[str, int], str] = {('health', 0): 'health',
                                         ('armorpoints', 0): 'armor'}
    for i in range(4):
        reads[('ammo', i)] = 'ammo%d' % i
        reads[('ammo', 4 + i)] = 'maxammo%d' % i
    for i in range(6):
        reads[('weaponowned', i + 1)] = 'arms%d' % i
    fields = p0._asdict()
    poked = []
    for (name, k), widget in list(reads.items()) + (
            [(('ammo', t.ready[1]), 'ready')]
            if t.ready[0] == 'ammo' and t.ready[1] < 8 else []):
        v0 = getattr(p0, name) if name in ('health', 'armorpoints') \
            else getattr(p0, name)[k]
        v1 = getattr(p1, name) if name in ('health', 'armorpoints') \
            else getattr(p1, name)[k]
        if v0 == v1 or old_after[widget] != M.w16(v1):
            continue
        if name in ('health', 'armorpoints'):
            fields[name] = v1
        else:
            vals = list(fields[name])
            vals[k] = v1
            fields[name] = tuple(vals)
        poked.append('%s[%d]' % (name, k))
    return M.Player(**fields), tuple(sorted(set(poked)))


def frame_cases(run: str) -> List[FrameCase]:
    out = []
    rc = C.RunCases(C.run_dir(run))
    for k, (e, case) in enumerate(rc.frames()):
        if level_frame(case):
            out.append(frame_case(run, k, e, case))
    return out


def ready_known(fc: FrameCase) -> bool:
    """X-ST1: the ready number's pointer past the player's ammo and
    maxammo (a ready weapon out of range: upstream shows a word of its
    memory the native machine does not have)."""
    return not (fc.tick.ready[0] == 'ammo' and fc.tick.ready[1] > 7)


def model_frame(fc: FrameCase) -> Tuple[M.Bar, str]:
    a = assets()
    t = M.tables_of(a.nibtab, fc.scb)
    buf = bytearray(fc.screen[:32000])
    bar = M.Bar(a.glyphs, t, buf, fc.stcache, fc.old, fc.tick.refreshed,
                fc.stcache_valid, fc.message_on, fc.mhid, fc.text_shown)
    tick = fc.tick
    if not ready_known(fc):
        tick = tick._replace(ready=('ammo', 0))   # (X-ST1: not compared)
    v = M.values_of(tick, fc.player, fc.menuactive, fc.fps_rate)
    kind = bar.drawer(v, a.glyphs[M.BAR])
    return bar, kind


def ready_rect(fc: FrameCase) -> List[int]:
    """The ready number's bytes (its restore rectangle: X-ST1)."""
    a = assets()
    n = M.WIDGET['ready']
    w, h, lo, to = a.glyphs.header(n.glyphs[0])
    x0 = n.x - lo - 3 * w
    out = []
    for row in range(n.y - to, n.y - to + h):
        out += range(row * M.ROW + x0 // 2, row * M.ROW + (n.x - lo) // 2)
    return out


def marks_of(drb: bytes, dre: bytes) -> Tuple[Tuple[int, int], ...]:
    """Each row's marked bytes [DRB, DRE) (DRE 0: none; showDirty
    clears DRE only)."""
    return tuple((drb[r], dre[r]) if dre[r] else (0, 0)
                 for r in range(len(dre)))


def frame_model_check(fc: FrameCase, bar: M.Bar) -> List[str]:
    out = []
    skip = set() if ready_known(fc) else set(ready_rect(fc))
    lo, hi = SCREEN_ROWS
    for o in range(lo, hi):
        if o in skip:
            continue
        if bar.buf[o] != fc.screen_after[o]:
            out.append('the screen at $%04X: $%02X, ref $%02X' % (
                0x2000 + o, bar.buf[o], fc.screen_after[o]))
            break
    if bytes(bar.stcache) != fc.stcache_after:
        out.append('STCACHE differs')
    old = dict(bar.old)
    ref_old = dict(fc.old_after)
    if not ready_known(fc):
        old.pop('ready')
        ref_old.pop('ready')
    if old != ref_old:
        out.append('old values %s' % {k: (v, ref_old[k]) for k, v in
                                       old.items() if v != ref_old[k]})
    if bar.refreshed != fc.refreshed_after:
        out.append('st_refreshed %d, ref %d' % (bar.refreshed,
                                                fc.refreshed_after))
    mine = marks_of(bar.marks.drb[M.ST_Y:], bar.marks.dre[M.ST_Y:])
    theirs = marks_of(fc.drb, fc.dre)
    if fc.full_map:     # AM_Drawer's marks too: the status bar's inside
        bad = any(b and not (d and c <= a and b <= d)
                  for (a, b), (c, d) in zip(mine, theirs))
    else:
        bad = mine != theirs
    if bad and not skip:
        out.append('the marks differ: %s, ref %s' % (
            [m for m in mine if m[1]][:3], [m for m in theirs if m[1]][:3]))
    return out


def frame_model(runs: Sequence[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {'runs': {}, 'kinds': {}, 'problems': [],
                           'poked': [], 'x_st1': 0}
    for run in runs:
        n = 0
        for fc in frame_cases(run):
            bar, kind = model_frame(fc)
            out['kinds'][kind] = out['kinds'].get(kind, 0) + 1
            for p in frame_model_check(fc, bar):
                out['problems'].append('%s %s: %s' % (run, fc.name, p))
            if fc.poked:
                out['poked'].append('%s:%s %s' % (run, fc.name,
                                                  ','.join(fc.poked)))
            if not ready_known(fc):
                out['x_st1'] += 1
            n += 1
        out['runs'][run] = n
    return out


# ---------------------------------------------------------------------------
# The generated include: the places s2_st.s and s2t_st.s need beyond
# s2.inc and s2data.inc
# ---------------------------------------------------------------------------

PLAYER_FIELDS = (('PO_MO', ('mo',)), ('PO_HEALTH', ('health',)),
                 ('PO_ARMOR', ('armorpoints',)), ('PO_POWERS', ('powers', 0)),
                 ('PO_CARDS', ('cards', 0)), ('PO_READYW', ('readyweapon',)),
                 ('PO_OWNED', ('weaponowned', 0)), ('PO_AMMO', ('ammo', 0)),
                 ('PO_ATTACKDOWN', ('attackdown',)),
                 ('PO_CHEATS', ('cheats',)),
                 ('PO_DAMAGE', ('damagecount',)),
                 ('PO_BONUS', ('bonuscount',)),
                 ('PO_ATTACKER', ('attacker',)))
# the stand-ins of this part's requests (docs/m11-parts/s2stbar.md 6) still
# open: their places until milestone 10 gives them (S2STBAR-1 to -3 are
# s2layout.py's since wave 4's integration, in s2.inc)
STANDINS = (
    ('GT_POS', '$%02X' % 0x5C, 'S2STBAR-4: s2t_pos\'s answer, GT_0-GT_11 '
     '(x, y, angle: 4 bytes each), milestone 10\'s GT_*'),
)


def inc_values() -> List[Tuple[str, int]]:
    from native import llayout as LL
    at = {tuple(path): a for path, enc, a in LL.player_layout()}
    out = [('G_PLAYER', LL.G['G_PLAYER']),
           ('G_MENUACTIVE', LL.G['G_MENUACTIVE'])]
    out += [(name, at[path]) for name, path in PLAYER_FIELDS]
    out += [('AM_NOAMMO', M.AM_NOAMMO), ('CF_GODMODE', M.CF_GODMODE),
            ('NO_HANDLE', LL.NO_HANDLE)]
    out += [('ST_WAMMO%d' % w, v) for w, v in enumerate(assets().wammo)]
    return out


def inc_text() -> str:
    lines = ['; s2stbar.inc: part s2stbar\'s places beyond s2.inc and '
             's2data.inc (generated', '; by tools/native/s2stbar.py --inc; '
             'docs/m11-parts/s2stbar.md). Do not edit.', '']
    for name, value in inc_values():
        lines.append('%-16s= $%04X' % (name, value))
    lines += ['', '; STANDIN: requests of docs/m11-parts/s2stbar.md 6']
    for name, expr, why in STANDINS:
        lines.append('%-16s= %-16s; STANDIN %s' % (name, expr, why))
    return '\n'.join(lines) + '\n'


def write_inc(path: Path) -> None:
    from native import s2layout as S
    S.write_if_changed(path, inc_text())


# ---------------------------------------------------------------------------
# The tic side's test image: its map and its sizes
# ---------------------------------------------------------------------------

TIC_W = (0x6000, 0x7000)        # MATHW (the game's math, pta3), AUXW
TIC_IMG = (0x7000, 0xC000)      # the module and its glue
TIC_SEGMENTS = ('S2TCODE', 'S2TRODATA')
TIC_BUDGET = 900                # SCREENS.md 4.7, 7.3
DRAW_BUDGET = 2000              # P2DW's s2stbar row (SCREENS.md 4.1)


def cfg_tic() -> str:
    """s2layout's map of P2DW with W widened for the game's math (math.s
    without RENDER: MATHW 2,133 B and MATHRND, against the render math's
    1,427 B in $6000-$6592) and the module's segments in the room from
    $7000."""
    from native import s2layout as S
    text = S.cfg_text('P2DW')
    w = '    W:      start = $6000, size = $%04X, file = "%%O.w";' % (
        S.IMAGE_LO - 0x6000)
    img = [ln for ln in text.splitlines() if ln.startswith('    IMG:')][0]
    if w not in text:
        raise StError('s2layout\'s map changed: no %r' % w)
    text = text.replace(w, '    W:      start = $%04X, size = $%04X, '
                        'file = "%%O.w";' % (TIC_W[0], TIC_W[1] - TIC_W[0]))
    text = text.replace(img, '    IMG:    start = $%04X, size = $%04X, '
                        'file = "%%O.img";' % (TIC_IMG[0],
                                               TIC_IMG[1] - TIC_IMG[0]))
    seg = '    MATHW:     load = W,   type = ro, define = yes;'
    text = text.replace(seg, seg + '\n    MATHRND:   load = W,   type = ro;')
    # the module's segments before S2DATA: the loader's pages end with
    # the image's last segment of s2layout's (IMG_SEGMENTS)
    seg = '    S2DATA:    load = IMG, type = rw, define = yes, optional = yes;'
    text = text.replace(seg, ''.join(
        '    %-10s load = IMG, type = ro, define = yes, optional = yes;\n'
        % (s + ':') for s in TIC_SEGMENTS) + seg)
    return text.replace('the image P2DW', 'part s2stbar\'s tic test image '
                        '(P2DW\'s map, W widened)')


def module_bytes(map_text: str, segments: Sequence[str]) -> Dict[str, int]:
    """Each module's bytes in the named segments (ld65's map)."""
    import re
    out: Dict[str, int] = {}
    part = map_text.split('Modules list:', 1)[-1].split('Segment list:',
                                                          1)[0]
    module = None
    for line in part.splitlines():
        if line and not line.startswith(' ') and \
                line.rstrip().endswith(':'):
            module = Path(line.strip()[:-1].split('(')[0]).stem
            continue
        f = line.split()
        if module and f and f[0] in segments:
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            out[module] = out.get(module, 0) + size
    del re
    return out


def check_tic_map(text: str) -> Tuple[List[str], List[str]]:
    n = module_bytes(text, TIC_SEGMENTS).get('s2t_st', 0)
    rows = ['s2st   s2t_st (tic side)  %6d of %6d B%s' % (
        n, TIC_BUDGET, '  OVER BUDGET' if n > TIC_BUDGET else '')]
    return rows, (['s2t_st is %d B, over its %d B' % (n, TIC_BUDGET)]
                  if n > TIC_BUDGET else [])


# ---------------------------------------------------------------------------
# The native drawer on a2vm: the test image s2sb (s2_st.s, s2_stt.s)
# ---------------------------------------------------------------------------

CASES_A_RUN = 16                # (the write log: about 40,000 lines a frame)
SYNTH_A_RUN = 4
T_CASE, T_BLOB, BLOBS_A_BANK = 50, 52, 9
GLUE_ZP = (0x80, 0x88)
ROWS_LO, ROWS_HI = 0x2000 + M.ST_Y * M.ROW, 0x2000 + 200 * M.ROW
STRIP_HI = 0x2000 + 10 * M.ROW
OWN_W = 0xBF00                  # P2DW's own block in W (s2layout OWN_STATE)


_TEST_CONSTANTS: Dict[str, int] = {}


def stand(name: str) -> int:
    """A place of the test build: a stand-in's (STANDINS) or s2.inc's
    (s2layout's constants: the requests applied)."""
    from native import s2layout as S
    expr = dict((n, e) for n, e, _ in STANDINS).get(name)
    if expr is None:
        if not _TEST_CONSTANTS:
            _TEST_CONSTANTS.update(S.constants('test'))
        return _TEST_CONSTANTS[name]
    if expr.startswith('S2T_BASE + '):
        return S.BUILDS['test'].s2t_base + int(expr.split('+')[1])
    return int(expr.strip('$'), 16)


BUILD_DIR = [WORK]             # the images' directory (a planted bug's)


def build(name: str):
    from native import s2run as SR
    return SR.load_build(BUILD_DIR[0], name, 'P2DW')


def make_part() -> None:
    """The part's images (make -f m11.mk part P=s2stbar)."""
    from native import s2run as SR
    SR.make('s2stbar')


_FIXED: Optional[List[Tuple[int, int, int, bytes]]] = None


def fixed_records() -> List[Tuple[int, int, int, bytes]]:
    """What every run's machine holds besides the case: the 2D store (part
    s2data's bank files, segment by segment) and the status bar's nibble
    tables in S2PAL's S2NIB (palettes 1-8; the others stay the fill)."""
    global _FIXED
    if _FIXED is None:
        from native import lstore, s2data as SD, s2layout as S
        recs = []
        for name, data in sorted(SD.load_files(S2DATA).items()):
            for bank, address, seg in lstore.read_bank_file(data):
                recs.append((1, bank, address, seg))
        nib = assets().nibtab
        recs.append((1, S.S2PAL, S.S2PAL_AT['S2P_NIB'] + 0x400,
                     nib[0x400:9 * 0x400]))
        _FIXED = recs
    return _FIXED


def ready_code(src: tuple) -> int:
    if src[0] == 'none':
        return 0xFD             # s2state.READY_NONE: st_init's
    if src[0] == 'large':
        return 0xFE
    if src[0] == 'fps':
        return 0xFF
    return src[1] & 0xFF


def put_word(buf: bytearray, at: int, v: int) -> None:
    buf[at:at + 2] = (v & 0xFFFF).to_bytes(2, 'little')


class Carried(NamedTuple):
    """The native 2D state at a chained run's start: P2DW's own block, the
    card's S2T block, STCACHE, STBUF, aux 0's rows 168-199."""
    own: bytes
    card: bytes
    stcache: bytes
    stbuf: bytes
    rows: bytes


# the card's bytes of the tic side (the reference's tics write them):
# a chained frame takes them from the reference, the rest is carried
TIC_FIELDS = ('ST_FACEINDEX', 'ST_FACECOUNT', 'ST_PRIORITY', 'ST_OLDHEALTH',
              'ST_LASTATTACK', 'ST_OLDHEALTHPO', 'ST_LASTCALC', 'ST_RANDOM',
              'ST_KEYBOXES', 'ST_OLDWEAPONS', 'HU_ON')


class Staged(NamedTuple):
    fc: FrameCase
    record: bytes               # the case's 1 KB record (T_CASE)
    blobs: Tuple[Optional[bytes], Optional[bytes], Optional[bytes]]
    poisoned: Tuple[int, ...]   # aux 0 offsets set to the fill


def staged(fc: FrameCase, fill: int, poison: bool,
           carried: Optional[Carried] = None, chain: bool = False
           ) -> Staged:
    """A frame's record: injected (every place from the reference's
    case: s2state's injection, then this part's stand-ins and the player
    as ST_Drawer read it), or chained (the game's inputs and the tic
    side's card bytes from the reference; the 2D state carried: from
    `carried` at a run's start, else left in the machine)."""
    from native import s2layout as S, s2state as SS
    host = SS.Host(fill)
    for rec in fc.records:
        host.put(*rec)
    base = S.BUILDS['test'].s2t_base
    own = bytearray(host.get('aux', S.S2STATE, S.SS['SS_P2DW'], 256))
    card = bytearray(host.get('lc', 0, base, S.S2T_SIZE))
    player = bytearray(host.get('main', 0, inc_value('G_PLAYER'), 148))
    stcache = host.get('aux', S.S2STATE, S.SS['SS_STCACHE'], M.ST_BYTES)
    pl = fc.player
    put_word(player, inc_value('PO_HEALTH'), pl.health)
    put_word(player, inc_value('PO_ARMOR'), pl.armorpoints)
    for k in range(8):
        put_word(player, inc_value('PO_AMMO') + 2 * k, pl.ammo[k])
    for k in range(M.NUMWEAPONS):
        put_word(player, inc_value('PO_OWNED') + 2 * k, pl.weaponowned[k])
    card[stand('ST_READY') - base] = ready_code(fc.tick.ready)
    card[stand('ST_RUNNING') - base] = fc.tick.running & 0xFF
    card[S.S2T['HU_ON']] = fc.message_on & 0xFF
    st = S.state_places('P2DW')
    own[st['P_TXTSHOWN'] - OWN_W + 0x0:st['P_TXTSHOWN'] - OWN_W + 4] = \
        fc.text_raw
    own[stand('P_MHID') - OWN_W] = fc.mhid & 0xFF
    put_word(own, stand('P_FPSRATE') - OWN_W, fc.fps_rate)
    lo, hi = SCREEN_ROWS
    rows = bytearray(fc.screen[lo:hi])
    hit: Tuple[int, ...] = ()
    if poison:
        hit = tuple(o for o in fc.marked if lo <= o < hi)
        if fc.full_map:
            # AM_Drawer marks too (rows 168-169 of a full list's redraw:
            # part s2amap's): the status bar's own marks are poisoned, the
            # model's, which frame_model_check finds inside the reference's
            bar, _ = model_frame(fc)
            mine = set()
            for r in range(M.ST_Y, 200):
                if bar.marks.dre[r]:
                    mine.update(range(r * M.ROW + bar.marks.drb[r],
                                      r * M.ROW + bar.marks.dre[r]))
            hit = tuple(o for o in hit if o in mine)
        for o in hit:
            rows[o - lo] = fill
    mask = bytearray([1]) * S.S2T_SIZE
    inject = True
    blobs: Tuple = (stcache, fc.screen[lo:hi], bytes(rows))
    if chain:
        mask = bytearray(S.S2T_SIZE)
        for name in TIC_FIELDS:
            n = dict(S.S2T_FIELDS)[name]
            mask[S.S2T[name]:S.S2T[name] + n] = bytes([1]) * n
        mask[stand('ST_READY') - base] = 1
        mask[stand('ST_RUNNING') - base] = 1
        if fc.tick.refreshed == 0:          # an ST_Start since: its 0
            mask[S.S2T['ST_REFRESHED']] = 1
        inject = False
        blobs = (None, None, None)
        if carried is not None:
            for i in range(S.S2T_SIZE):
                if not mask[i]:
                    card[i] = carried.card[i]
            mask = bytearray([1]) * S.S2T_SIZE
            own = bytearray(carried.own)
            inject = True
            blobs = (carried.stcache, carried.stbuf, carried.rows)
            hit = ()
    rec = bytearray([fill]) * 0x400
    rec[0x000:0x100] = own
    rec[0x100:0x100 + S.S2T_SIZE] = card
    rec[0x140:0x140 + S.S2T_SIZE] = mask
    rec[0x180:0x180 + 148] = player
    rec[0x220:0x220 + 200] = fc.scb
    put_word(rec, 0x2F0, fc.menuactive)
    rec[0x2F2] = 1 if inject else 0
    return Staged(fc, bytes(rec), blobs, hit)


_INC: Optional[Dict[str, int]] = None


def inc_value(name: str) -> int:
    global _INC
    if _INC is None:
        _INC = dict(inc_values())
    return _INC[name]


def stage_records(batch: Sequence[Staged]
                  ) -> List[Tuple[int, int, int, bytes]]:
    recs: List[Tuple[int, int, int, bytes]] = []
    blob_ids: Dict[bytes, int] = {}
    for k, sc in enumerate(batch):
        ids = []
        for blob in sc.blobs:
            if blob is None:
                ids.append(0xFF)
                continue
            if blob not in blob_ids:
                j = len(blob_ids)
                blob_ids[blob] = j
                recs.append((1, T_BLOB + j // BLOBS_A_BANK,
                             0x0200 + (j % BLOBS_A_BANK) * 0x1400, blob))
            ids.append(blob_ids[blob])
        rec = bytearray(sc.record)
        rec[0x2F3:0x2F6] = bytes(ids)
        recs.append((1, T_CASE, 0x0200 + k * 0x400, bytes(rec)))
    if len(blob_ids) > 9 * (T_CASE - T_BLOB + 99):
        raise StError('too many blobs')
    return recs


def sb_owners(b, loads) -> List[Any]:
    """The writers of an s2sb run and what each may write."""
    from native import rlayout as R, s2drawcase as DC, s2layout as S, \
        s2run as SR
    pcs = DC.module_pcs(b)
    lab = b.labels
    marks = lab['s2_marks']
    io_w = frozenset({0xC004, 0xC005})
    io_window = frozenset({0xC002, 0xC003, 0xC004, 0xC005, 0xC073})
    zp = ('main', 0, 0x48, 0x78)
    far_zp = ('main', 0, 0x0000, 0x0006)
    base = S.BUILDS['test'].s2t_base
    ss = S.S2STATE
    own = ('aux', ss, S.SS['SS_P2DW'], S.SS['SS_P2DW'] + 256)
    stc = ('aux', ss, S.SS['SS_STCACHE'], S.SS['SS_STCACHE'] + M.ST_BYTES)
    stb = ('aux', ss, stand('SS_STBUF'), stand('SS_STBUF') + M.ST_BYTES)
    band = ('main', 0, S.IMAGE['P2DW'].runtime[0][0],
            S.IMAGE['P2DW'].runtime[0][1])
    data = b.segments['S2DATA']
    st_data = ('main', 0, data[0], data[1] + 1)
    st = S.state_places('P2DW')
    return [
        SR.driver_owner(b), SR.loader_owner(b, loads),
        SR.Owner('the far layer', (b.segments['RFAR'],),
                 (far_zp, zp,
                  ('main', 0, 0x8300, 0xC000), own, stc, stb), io_window),
        SR.Owner('the test glue', (pcs['s2_stt'],),
                 (('main', 0, GLUE_ZP[0], GLUE_ZP[1]), far_zp,
                  ('main', 0, R.PHASE, R.PHASE + 1), st_data, band,
                  ('main', 0, inc_value('G_PLAYER'),
                   inc_value('G_PLAYER') + 148),
                  ('main', 0, inc_value('G_MENUACTIVE'),
                   inc_value('G_MENUACTIVE') + 2),
                  ('main', 0, S.PALST_W, S.PALST_W + 200),
                  ('lc', 0, base, base + S.S2T_SIZE),
                  ('aux', 0, ROWS_LO, ROWS_HI)), io_w),
        SR.Owner('s2_st', (pcs['s2_st'],),
                 (zp, far_zp, ('main', 0, 0xB0, 0xD8), band,
                  ('main', 0, marks, marks + 0x100), st_data,
                  ('lc', 0, base + S.S2T['ST_REFRESHED'],
                   base + S.S2T['ST_REFRESHED'] + 1),
                  ('lc', 0, base + S.S2T['HU_ON'], base + S.S2T['HU_ON'] + 1),
                  ('main', 0, st['P_OLDREADY'], st['P_OLDREADY'] + 42),
                  ('main', 0, st['P_TXTSHOWN'], st['P_TXTSHOWN'] + 2),
                  ('main', 0, stand('P_MHID'), stand('P_MHID') + 1)),
                 frozenset()),
        SR.Owner('s2_draw', (pcs['s2_draw'],),
                 (zp, far_zp, band, ('main', 0, marks, marks + 0x100),
                  ('main', 0, 0xB800, 0xBC00), ('main', 0, pcs['s2_draw'][0],
                                                pcs['s2_draw'][1] + 1)),
                 frozenset()),
        SR.Owner('s2_pub', (pcs['s2_pub'],),
                 (zp, ('aux', 0, ROWS_LO, ROWS_HI),
                  ('aux', 0, 0x2000, STRIP_HI),
                  ('main', 0, marks + 0x40, marks + 0x80),
                  ('main', 0, lab['s2_begun'], lab['s2_begun'] + 1)), io_w),
        # part s2pal's s2_pal (s2_begin): never runs here, the frame's
        # s2_begun (PALST's PS_BEGUN) being set, so it may write nothing
        # (the palettes and SCBs are s2pal's region; until the final
        # integration the stand-in s2_beginstub.s)
        SR.Owner('s2_pal (s2_begin, never run)', (pcs['s2_pal'],),
                 (), frozenset()),
        SR.Owner('the math', (b.segments['MATHW'],),
                 (('main', 0, 0xB0, 0xD8),), frozenset()),
    ]


def snap_ranges(b) -> str:
    from native import s2layout as S
    nibs = b.labels['stx_nibs']
    ss = S.S2STATE
    return ','.join([
        'aux0:2000-263F', 'aux0:%04X-%04X' % (ROWS_LO, ROWS_HI - 1),
        'main:BF00-BFFF', 'main:%04X-%04X' % (nibs, nibs),
        'lc:%04X-%04X' % (S.BUILDS['test'].s2t_base,
                          S.BUILDS['test'].s2t_base + S.S2T_SIZE - 1),
        'aux%d:%04X-%04X' % (ss, S.SS['SS_P2DW'], S.SS['SS_P2DW'] + 255),
        'aux%d:%04X-%04X' % (ss, S.SS['SS_STCACHE'],
                             S.SS['SS_STCACHE'] + M.ST_BYTES - 1),
        'aux%d:%04X-%04X' % (ss, stand('SS_STBUF'),
                             stand('SS_STBUF') + M.ST_BYTES - 1)])


def published(writes, b) -> Dict[int, List[Any]]:
    """Each case's aux 0 stores by s2_pub (cut at the glue's write of
    the case's number)."""
    from native import s2drawcase as DC
    pcs = DC.module_pcs(b)
    marker = b.labels['stx_marker']
    out: Dict[int, List[Any]] = {}
    k = -1
    for w in writes:
        if w.storage == 'main' and w.offset == marker and \
                pcs['s2_stt'][0] <= w.pc <= pcs['s2_stt'][1]:
            k = w.new
            continue
        if k >= 0 and w.storage == 'aux' and w.bank == 0 and \
                pcs['s2_pub'][0] <= w.pc <= pcs['s2_pub'][1]:
            out.setdefault(k, []).append(w)
    return out


def marks_of_writes(ws, y0: int, n: int) -> Tuple[Tuple[int, int], ...]:
    """Each screen row's [first, last + 1) of the stores (rows y0 ..
    y0 + n - 1); (0, 0) for none."""
    out = [(0, 0)] * n
    for w in ws:
        o = w.offset - 0x2000
        r, c = o // M.ROW - y0, o % M.ROW
        if 0 <= r < n:
            a, e = out[r]
            out[r] = (c, c + 1) if e == 0 else (min(a, c), max(e, c + 1))
    return tuple(out)


class NativeOut(NamedTuple):
    cases: int
    problems: List[str]
    writes: int
    stray: int
    stack: Optional[int]
    nibs: List[int]
    carried: Optional[Carried]
    ms: Dict[int, float] = {}


def native_batch(b, batch: Sequence[Staged], fill: int, label: str,
                 profile: Optional[str] = None) -> NativeOut:
    """One a2vm run of up to 32 frames: each frame's screen rows,
    STCACHE, STBUF, old values, ST_REFRESHED and published bytes against
    the reference; the write log's strays."""
    from native import s2layout as S, s2run as SR
    recs = fixed_records() + stage_records(batch)
    calls = [SR.Call('stx_case', k) for k in range(len(batch))]
    work = Path(tempfile.mkdtemp(prefix='tmp-run-', dir=str(WORK)))
    problems: List[str] = []
    try:
        try:
            run = SR.run(b, calls, fill, work, extra_records=recs,
                         snap_ranges=snap_ranges(b), profile=profile)
        except SR.RunError as error:
            return NativeOut(len(batch), ['%s: %s' % (label, error)], 0, 0,
                             None, [], None)
        if run.ended() != 'stop' or run.status() != S.S2S['DONE']:
            return NativeOut(len(batch), ['%s: the run ended %s, status %s'
                                          % (label, run.ended(),
                                             run.status())],
                             0, 0, None, [], None)
        snaps = run.calls()
        if len(snaps) != len(calls):
            return NativeOut(len(batch), ['%s: %d snapshots for %d calls'
                                          % (label, len(snaps),
                                             len(calls))],
                             0, 0, None, [], None)
        writes = run.writes()
        n_stray, shown = SR.stray(writes, sb_owners(b, run.loads))
        problems += ['%s: stray %s' % (label, x) for x in shown]
        pub = published(writes, b)
        nibs = []
        base = S.BUILDS['test'].s2t_base
        ss = S.S2STATE
        st = S.state_places('P2DW')
        for k, sc in enumerate(batch):
            fc = sc.fc
            snap = snaps[k]
            tag = '%s %s %s (fill %02X%s)' % (label, fc.run, fc.name, fill,
                                             ', poisoned' if sc.poisoned
                                             else '')
            aux0 = snap.storage('aux', 0)
            skip = set() if ready_known(fc) else set(ready_rect(fc))
            lo, hi = SCREEN_ROWS
            for o in range(lo, hi):
                if o not in skip and aux0[0x2000 + o] != fc.screen_after[o]:
                    problems.append('%s: the screen at $%04X: $%02X, ref '
                                    '$%02X' % (tag, 0x2000 + o,
                                               aux0[0x2000 + o],
                                               fc.screen_after[o]))
                    break
            if fc.strip:
                for o in range(0, 10 * M.ROW):
                    if aux0[0x2000 + o] != fc.screen_after[o]:
                        problems.append('%s: the strip at $%04X: $%02X, '
                                        'ref $%02X' % (
                                            tag, 0x2000 + o,
                                            aux0[0x2000 + o],
                                            fc.screen_after[o]))
                        break
            own = snap.main
            for j, w in enumerate(M.WIDGETS):
                if w.name == 'ready' and skip:
                    continue
                at = st['P_OLDREADY'] + 2 * j
                got = own[at] | own[at + 1] << 8
                if got != fc.old_after[w.name]:
                    problems.append('%s: %s\'s old value %d, ref %d' % (
                        tag, w.name, got, fc.old_after[w.name]))
            refr = snap.lc[base + S.S2T['ST_REFRESHED'] - 0xC000]
            if refr != fc.refreshed_after:
                problems.append('%s: ST_REFRESHED %d, ref %d' % (
                    tag, refr, fc.refreshed_after))
            bank = snap.storage('aux', ss)
            stc = bytes(bank[S.SS['SS_STCACHE']:S.SS['SS_STCACHE'] +
                             M.ST_BYTES])
            if stc != fc.stcache_after:
                problems.append('%s: STCACHE differs' % tag)
            stb = bytes(bank[stand('SS_STBUF'):stand('SS_STBUF') +
                             M.ST_BYTES])
            if fc.refreshed_after and not skip and \
                    stb != fc.screen_after[lo:hi]:
                problems.append('%s: STBUF is not the screen\'s rows' % tag)
            mine = marks_of_writes(pub.get(k, []), M.ST_Y, M.ST_HEIGHT)
            theirs = marks_of(fc.drb, fc.dre)
            if fc.full_map:
                bad = any(e and not (d and c <= a and e <= d)
                          for (a, e), (c, d) in zip(mine, theirs))
            else:
                bad = mine != theirs
            if bad and not skip:
                problems.append('%s: published %s, the marks %s' % (
                    tag, [m for m in mine if m[1]][:3],
                    [m for m in theirs if m[1]][:3]))
            nibs.append(snap.main[b.labels['stx_nibs']])
        last = snaps[-1]
        bank = last.storage('aux', ss)
        carried = Carried(
            bytes(bank[S.SS['SS_P2DW']:S.SS['SS_P2DW'] + 256]),
            bytes(last.lc[base - 0xC000:base - 0xC000 + S.S2T_SIZE]),
            bytes(bank[S.SS['SS_STCACHE']:S.SS['SS_STCACHE'] + M.ST_BYTES]),
            bytes(bank[stand('SS_STBUF'):stand('SS_STBUF') + M.ST_BYTES]),
            bytes(last.storage('aux', 0)[ROWS_LO:ROWS_HI]))
        ms = SR.phase_ms(run, profile) if profile else {}
        return NativeOut(len(batch), problems, len(writes), n_stray,
                         SR.stack_depth(run), nibs, carried, ms)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def native_frames(runs: Sequence[str], jobs: int = 2,
                  fills=(0xA5, 0x5A), poisons=(False, True),
                  limit: Optional[int] = None,
                  names: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Every level frame of the runs, injected, from both fills, plain and
    poisoned, in batches of 32."""
    from concurrent.futures import ThreadPoolExecutor
    b = build('s2sb')
    jobs_list = []
    for run in runs:
        fcs = (synth_frames(jobs) if run == 'synth' else
               frame_cases(run))[:limit]
        if names is not None:
            fcs = [fc for fc in fcs if fc.name in names]
        # (a synthetic frame redraws every widget: about 8 times the
        # write log's lines of a captured frame)
        step = SYNTH_A_RUN if run == 'synth' else CASES_A_RUN
        for fill in fills:
            for poison in poisons:
                for i in range(0, len(fcs), step):
                    jobs_list.append((run, fill, poison, fcs[i:i + step]))

    def one(job):
        run, fill, poison, fcs = job
        batch = [staged(fc, fill, poison) for fc in fcs]
        return native_batch(b, batch, fill, run)
    out: Dict[str, Any] = {'cases': 0, 'problems': [], 'writes': 0,
                           'stray': 0, 'stack': 0, 'nibs': {}, 'runs': 0}
    with ThreadPoolExecutor(max(1, jobs)) as ex:
        for res in ex.map(one, jobs_list):
            out['cases'] += res.cases
            out['problems'] += res.problems
            out['writes'] += res.writes
            out['stray'] += res.stray
            out['stack'] = max(out['stack'], res.stack or 0)
            for n in res.nibs:
                out['nibs'][n] = out['nibs'].get(n, 0) + 1
            out['runs'] += 1
    return out


# ---------------------------------------------------------------------------
# The native tic side on a2vm: the test image s2st (s2t_st.s, s2t_stt.s)
# ---------------------------------------------------------------------------

T_TIC, TICS_A_BANK = 40, 188
T_RES, RES_A_BANK = 70, 376
TIC_CHUNK = 255
TIC_CALLS_A_RUN = 2             # (the write log: about 750 lines a case)
OP_TICKER, OP_START, OP_INIT = 0, 1, 2
NEWPAL_BEFORE = 0x5A            # newpal before ST_Start (its 0 shows)
# the card's status bar fields (s2layout's S2T) and their encodings
CARD_TICK = (('ST_FACEINDEX', 'faceindex', 'byte'),
             ('ST_FACECOUNT', 'facecount', 'word'),
             ('ST_PRIORITY', 'priority', 'byte'),
             ('ST_OLDHEALTH', 'oldhealth', 'word'),
             ('ST_LASTATTACK', 'lastattackdown', 'sxbyte'),
             ('ST_OLDHEALTHPO', 'oldhealthPO', 'word'),
             ('ST_LASTCALC', 'lastcalc', 'byte'),
             ('ST_RANDOM', 'randomnumber', 'byte'),
             ('ST_REFRESHED', 'refreshed', 'byte'))


def enc(v: int, how: str) -> Tuple[bytes, bool]:
    if how == 'word':
        return (v & 0xFFFF).to_bytes(2, 'little'), True
    if how == 'byte':
        return bytes([v & 0xFF]), 0 <= v < 256
    s = M.s16(v)
    return bytes([s & 0xFF]), -128 <= s < 128       # sxbyte


def card_bytes(t: M.Tick, fill: int) -> Tuple[bytes, List[str]]:
    """The native card block of a Tick (the status bar's fields, the
    stand-ins ST_READY and ST_RUNNING; the rest the fill) and the fields
    that do not fit."""
    from native import s2layout as S
    base = S.BUILDS['test'].s2t_base
    out = bytearray([fill]) * S.S2T_SIZE
    unfit = []

    def put(name, data, ok, what):
        out[S.S2T[name]:S.S2T[name] + len(data)] = data
        if not ok:
            unfit.append(what)
    for name, f, how in CARD_TICK:
        data, ok = enc(getattr(t, f), how)
        put(name, data, ok, f)
    for k in range(M.NUMCARDS):
        data, ok = enc(t.keyboxes[k], 'sxbyte')
        out[S.S2T['ST_KEYBOXES'] + k] = data[0]
        if not ok:
            unfit.append('keyboxes')
    for k in range(M.NUMWEAPONS):
        data, ok = enc(t.oldweaponsowned[k], 'byte')
        out[S.S2T['ST_OLDWEAPONS'] + k] = data[0]
        if not ok:
            unfit.append('oldweaponsowned')
    out[stand('ST_READY') - base] = ready_code(t.ready)
    if t.ready[0] == 'ammo' and t.ready[1] >= 0xFD:    # (READY_NONE..)
        unfit.append('ready')
    out[stand('ST_RUNNING') - base] = t.running & 0xFF
    return bytes(out), unfit


CARD_COMPARED = None


def card_compared() -> List[Tuple[str, int, int]]:
    """(name, offset, bytes) of the card's bytes the comparison reads."""
    from native import s2layout as S
    base = S.BUILDS['test'].s2t_base
    out = [(n, S.S2T[n], dict(S.S2T_FIELDS)[n]) for n, _, _ in CARD_TICK]
    out += [('ST_KEYBOXES', S.S2T['ST_KEYBOXES'], 3),
            ('ST_OLDWEAPONS', S.S2T['ST_OLDWEAPONS'], 9),
            ('ST_READY', stand('ST_READY') - base, 1),
            ('ST_RUNNING', stand('ST_RUNNING') - base, 1)]
    return out


PLAYER_INTS = (('health',), ('armorpoints',), ('readyweapon',),
               ('attackdown',), ('cheats',), ('damagecount',),
               ('bonuscount',))


def player_bytes(p: M.Player, fill: int) -> bytes:
    """The native player (llayout.player_layout) of the fields the status
    bar reads; mo the handle 0, attacker 0 (the same mobj), 1 (another)
    or NO_HANDLE (none), as s2state's injection."""
    from native import llayout as LL
    at = {tuple(path): a for path, e, a in LL.player_layout()}
    out = bytearray([fill]) * 148
    for path in PLAYER_INTS:
        put_word(out, at[path], getattr(p, path[0]))
    for name, n in (('ammo', 4), ('powers', 6), ('cards', 3),
                    ('weaponowned', 9)):
        vals = getattr(p, name)
        for k in range(n):
            put_word(out, at[(name, k)], vals[k])
    for k in range(4):
        put_word(out, at[('maxammo', k)], p.ammo[4 + k])
    put_word(out, at[('mo',)], 0)
    put_word(out, at[('attacker',)], LL.NO_HANDLE if p.attacker == 0 else
             (0 if p.attacker == p.mo else 1))
    return bytes(out)


class TicStage(NamedTuple):
    name: str
    op: int
    card: bytes                 # before
    player: bytes
    rnd: int
    fps: int
    table: Tuple                # s2t_pos: handle 0's and 1's x, y, angle
    want_card: Optional[bytes]  # after (the compared bytes)
    want_p2dw: Optional[bytes]  # ST_Start: P_OLDREADY .. P_STPALETTE
    want_newpal: Optional[int]
    unfit: List[str]


def tic_stage(tc: TicCase, fill: int) -> TicStage:
    card, unfit = card_bytes(tc.before, fill)
    want, unfit2 = card_bytes(tc.after, fill)
    pos = tc.pos or M.Pos(0, 0, 0)
    return TicStage('%s:%d' % (tc.run, tc.k), OP_TICKER, card,
                    player_bytes(tc.player, fill), tc.rnd, 0,
                    ((0, 0, pos.angle), (pos.dx, pos.dy, 0)),
                    want, None, None, unfit + unfit2)


def synth_stage(sc: 'SynthTic', fill: int) -> TicStage:
    """A synthetic tic's stage: ST_Ticker's or ST_Start's, the positions
    of its mobjs as they are (handle 0 the player's, 1 the attacker)."""
    from native import s2layout as S
    card, unfit = card_bytes(sc.before, fill)
    want, unfit2 = card_bytes(sc.after, fill)
    p2dw = newpal = None
    if sc.ti.op == OP_START:
        r = ref()
        old = r.old(sc.st_after)
        buf = bytearray()
        for w in M.WIDGETS:
            buf += old[w.name].to_bytes(2, 'little')
        data, ok = enc(sc.after.palette, 'sxbyte')
        buf += data
        if not ok:
            unfit2.append('palette')
        p2dw = bytes(buf)
        newpal = sc.newpal & 0xFF
        del S
    return TicStage('synth:' + sc.ti.name, sc.ti.op, card,
                    player_bytes(sc.player, fill), sc.after.randomnumber,
                    sc.ti.fps_show, sc.table, want, p2dw, newpal,
                    unfit + unfit2)


def tic_record(ts: TicStage) -> bytes:
    rec = bytearray(256)
    rec[0:len(ts.card)] = ts.card
    rec[0x40:0x40 + 148] = ts.player
    rec[0xD8] = ts.rnd & 0xFF
    rec[0xD9] = ts.op
    rec[0xDA] = ts.fps
    rec[0xDB] = NEWPAL_BEFORE
    for h, (x, y, a) in enumerate(ts.table):
        at = 0xE0 + 14 * h
        rec[at:at + 2] = h.to_bytes(2, 'little')
        rec[at + 2:at + 6] = (x & M.M32).to_bytes(4, 'little')
        rec[at + 6:at + 10] = (y & M.M32).to_bytes(4, 'little')
        rec[at + 10:at + 14] = (a & M.M32).to_bytes(4, 'little')
    return bytes(rec)


def module_ranges(b, segments: Sequence[str]) -> Dict[str, List]:
    """Each module's ranges in the segments (ld65's map), inclusive."""
    text = (b.obj / (b.name + '.map')).read_text()
    out: Dict[str, List] = {}
    module = None
    part = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    for line in part.splitlines():
        if line and not line.startswith(' ') and line.rstrip().endswith(':'):
            module = Path(line.strip()[:-1].split('(')[0]).stem
            continue
        f = line.split()
        if module and f and f[0] in segments and f[0] in b.segments:
            offs = int(f[1][5:], 16)
            size = int(f[2][5:], 16)
            start = b.segments[f[0]][0]
            if size:
                out.setdefault(module, []).append((start + offs,
                                                   start + offs + size - 1))
    return out


def st_owners(b, loads) -> List[Any]:
    from native import rlayout as R, s2layout as S, s2run as SR
    m = module_ranges(b, ('S2CODE', 'S2TCODE', 'MATHW', 'MATHLC',
                          'MATHFAR'))
    base = S.BUILDS['test'].s2t_base
    far_zp = ('main', 0, 0x0000, 0x0006)
    data = b.segments['S2DATA']
    glue_data = ('main', 0, data[0], data[1] + 1)
    sb = b.labels['st_sb']
    io_window = frozenset({0xC002, 0xC003, 0xC004, 0xC005, 0xC073})
    ss = S.S2STATE
    p2 = S.SS['SS_P2DW']
    return [
        SR.driver_owner(b), SR.loader_owner(b, loads),
        SR.Owner('the far layer', (b.segments['RFAR'],),
                 (far_zp, glue_data, ('aux', ss, S.SS['SS_PALST'],
                                      p2 + 256)) +
                 tuple(('aux', k, 0x0200, 0xC000)
                       for k in range(T_RES, T_RES + 8)), io_window),
        SR.Owner('the test glue', tuple(m['s2t_stt']),
                 (('main', 0, GLUE_ZP[0], GLUE_ZP[1]), far_zp,
                  ('main', 0, R.PHASE, R.PHASE + 1), glue_data,
                  ('main', 0, inc_value('G_PLAYER'),
                   inc_value('G_PLAYER') + 148),
                  ('lc', 0, base, base + S.S2T_SIZE),
                  ('main', 0, 0x5C, 0x68)), frozenset()),
        SR.Owner('s2t_st', tuple(m['s2t_st']),
                 (far_zp, ('main', 0, 0xB0, 0xD8), ('main', 0, sb, sb + 32),
                  ('lc', 0, base + S.S2T['ST_FACEINDEX'],
                   base + S.S2T['ST_REFRESHED'] + 1),
                  ('lc', 0, stand('ST_READY'), stand('ST_RUNNING') + 1)),
                 frozenset()),
        SR.Owner('the math', tuple(m['math-g']),
                 (('main', 0, 0xB0, 0xD8),) +
                 tuple(('lc1', 0, lo, hi + 1) for lo, hi in m['math-g']
                       if lo >= 0xD000), io_window),
    ]


# math.inc's tantoangle planes in RamWorks (pta3 reads them through mt_far)
MT_TBANK, TANTO0, TANTO_STRIDE = 120, 0x6000, 9


def math_records() -> List[Tuple[int, int, int, bytes]]:
    return [(1, MT_TBANK, TANTO0 + 256 * TANTO_STRIDE * k,
             (TABLES / ('tanto%d.bin' % k)).read_bytes()) for k in range(4)]


class TicOut(NamedTuple):
    cases: int
    problems: List[str]
    writes: int
    stray: int
    stack: Optional[int]
    ms: Dict[int, float]


def tic_batch(b, stages: Sequence[TicStage], fill: int,
              profile: Optional[str] = None) -> TicOut:
    """One a2vm run of the stages (at most 8 x 255): each case's card
    block, and for ST_Start the P2DW state and newpal it wrote, against
    the reference's."""
    from native import s2layout as S, s2run as SR
    if len(stages) > S.DRV_CALLS * TIC_CHUNK:
        raise StError('%d cases in one run' % len(stages))
    recs = list(math_records())
    for k, ts in enumerate(stages):
        recs.append((1, T_TIC + k // TICS_A_BANK,
                     0x0200 + (k % TICS_A_BANK) * 0x100, tic_record(ts)))
    calls = [SR.Call('stt_run', i >> 8, i & 0xFF,
                     min(TIC_CHUNK, len(stages) - i))
             for i in range(0, len(stages), TIC_CHUNK)]
    nres = (len(stages) + RES_A_BANK - 1) // RES_A_BANK
    work = Path(tempfile.mkdtemp(prefix='tmp-tic-', dir=str(WORK)))
    problems: List[str] = []
    try:
        try:
            run = SR.run(b, calls, fill, work, extra_records=recs,
                         snap_ranges=','.join('aux%d:0200-BFFF' % (T_RES + i)
                                              for i in range(nres)),
                         profile=profile)
        except SR.RunError as error:
            return TicOut(len(stages), ['tics: %s' % error], 0, 0, None, {})
        if run.ended() != 'stop' or run.status() != S.S2S['DONE']:
            return TicOut(len(stages), ['the tic run ended %s, status %s'
                                        % (run.ended(), run.status())],
                          0, 0, None, {})
        end = run.calls()[-1]
        writes = run.writes()
        n_stray, shown = SR.stray(writes, st_owners(b, run.loads))
        problems += ['tics: stray ' + x for x in shown]
        cmp = card_compared()
        for k, ts in enumerate(stages):
            bank = end.storage('aux', T_RES + k // RES_A_BANK)
            at = 0x0200 + (k % RES_A_BANK) * 0x80
            res = bytes(bank[at:at + 0x80])
            if ts.want_card is not None:
                for name, o, n in cmp:
                    if res[o:o + n] != ts.want_card[o:o + n]:
                        problems.append('%s (fill %02X): %s %s, ref %s' % (
                            ts.name, fill, name, res[o:o + n].hex(),
                            ts.want_card[o:o + n].hex()))
            if ts.want_p2dw is not None and \
                    res[0x40:0x40 + len(ts.want_p2dw)] != ts.want_p2dw:
                problems.append('%s (fill %02X): P2DW\'s state %s, ref %s'
                                % (ts.name, fill,
                                   res[0x40:0x40 + 43].hex(),
                                   ts.want_p2dw.hex()))
            if ts.want_newpal is not None and res[0x6C] != ts.want_newpal:
                problems.append('%s (fill %02X): newpal %d, ref %d' % (
                    ts.name, fill, res[0x6C], ts.want_newpal))
            if ts.unfit:
                problems.append('%s: unfit %s' % (ts.name, ts.unfit))
        from native import s2run as SR2
        ms = SR2.phase_ms(run, profile) if profile else {}
        return TicOut(len(stages), problems, len(writes), n_stray,
                      SR.stack_depth(run), ms)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def native_tics(runs: Sequence[str], jobs: int = 2,
                fills=(0xA5, 0x5A)) -> Dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor
    from native import s2layout as S
    b = build('s2st')
    jobs_list = []
    for run in runs:
        for fill in fills:
            if run == 'synth':
                stages = [synth_stage(sc, fill) for sc in synth_tics(jobs)]
            else:
                stages = [tic_stage(tc, fill) for tc in tic_cases(run)]
            step = TIC_CALLS_A_RUN * TIC_CHUNK
            for i in range(0, len(stages), step):
                jobs_list.append((fill, stages[i:i + step]))
    out: Dict[str, Any] = {'cases': 0, 'problems': [], 'writes': 0,
                           'stray': 0, 'stack': 0, 'runs': 0}
    with ThreadPoolExecutor(max(1, jobs)) as ex:
        for res in ex.map(lambda j: tic_batch(b, j[1], j[0]), jobs_list):
            out['cases'] += res.cases
            out['problems'] += res.problems
            out['writes'] += res.writes
            out['stray'] += res.stray
            out['stack'] = max(out['stack'], res.stack or 0)
            out['runs'] += 1
    return out


# ---------------------------------------------------------------------------
# Synthetic frames: ST_Drawer by ref816 --call (the menu's stHide, each
# glyph at each place, the edges), on part s2draw's base state
# ---------------------------------------------------------------------------

SYNTH = WORK / 'synth'
SYNTH_FORMAT = 's2stbar-synth 1'
SHRBUF = 0x012000
STCACHE = 0x01A200
NIBTAB = 0x0B8000
VALUES = tuple(range(10)) + tuple(range(10, 100, 10)) + \
    tuple(range(100, 1000, 100))     # each digit at each place


class SynthIn(NamedTuple):
    name: str
    nums: Dict[str, int]        # every number widget's value but ready's
    ready: tuple                # W_READY's pointer as a source
    face: int
    keys: Tuple[int, int, int]
    arms: Tuple[int, ...]       # weaponowned[1-6]
    old: Dict[str, int]
    refreshed: int
    menuactive: int = 0
    message_on: int = 0
    mhid: int = 0
    text_shown: int = 0x0101
    fps_rate: int = 0
    stcache_valid: bool = True


def synth_inputs() -> List[SynthIn]:
    """42 frames that draw every number widget's digits at each place
    (VALUES, each widget its own phase), every face (and restore the one
    before), each key, each arm gray and yellow, the percent signs; the
    ready number of each ammo, LARGEAMMO and the frame rate; the edges
    (negative numbers, past 999, -1994); refreshes from STCACHE and from
    the raw bar; the menu's stHide with and without the strip's clear."""
    out = []
    nums = [w.name for w in M.NUMS if w.name != 'ready']
    for i in range(M.ST_NUMFACES):
        v = {n: VALUES[(i + 3 * j) % len(VALUES)] for j, n in
             enumerate(nums)}
        ready = ('ammo', i % 8) if i % 9 else ('large',)
        if i == 13:
            ready = ('fps',)
        keys = tuple(k if (i + k) % 2 else 0xFFFF for k in range(3))
        arms = tuple((i >> j) & 1 for j in range(6))
        old = {n: (v[n] + 1) & 0xFFFF for n in nums}
        old['ready'] = 0x7FFF
        old['face'] = (i + 1) % M.ST_NUMFACES
        for k in range(3):
            old['key%d' % k] = k if keys[k] == 0xFFFF else 0xFFFF
        for j in range(6):
            old['arms%d' % j] = 1 - arms[j]
        out.append(SynthIn('glyphs-%02d' % i, v, ready, i, keys, arms, old,
                           1, fps_rate=(i * 7) % 1000))
    base = out[0]
    for n, v in enumerate(VALUES):      # the ready number: each value
        out.append(base._replace(name='ready-%02d' % n, nums=dict(
            base.nums, ammo2=v), ready=('ammo', 2),
            old=dict(base.old, ready=(v + 1) & 0xFFFF)))
    edges = {'health': 0xFFFB, 'armor': 0xFF6A, 'ammo0': 1234,
             'ammo1': 0x10000 - 1994, 'maxammo0': 0x8000, 'maxammo1': 99,
             'ammo2': 1994, 'ammo3': 0xFFFF}
    out.append(base._replace(name='edges', nums=dict(base.nums, **edges)))
    out.append(base._replace(name='refresh-cached', refreshed=0))
    out.append(base._replace(name='refresh-raw', refreshed=0,
                             stcache_valid=False))
    for on in (0, 1):
        for mhid in (0, 1):
            out.append(base._replace(name='hide-%d%d' % (on, mhid),
                                     menuactive=1, message_on=on,
                                     mhid=mhid))
    return out


def synth_pokes(si: SynthIn) -> List[Tuple[int, bytes]]:
    r = ref()
    w = lambda v: (v & 0xFFFF).to_bytes(2, 'little')  # noqa: E731
    st, pl, o = r.st, r.pl, r.ofs
    pokes = [(pl + o['OFS_PL_HEALTH'], w(si.nums['health'])),
             (pl + o['OFS_PL_ARMORPOINTS'], w(si.nums['armor']))]
    for k in range(4):
        pokes.append((pl + o['OFS_PL_AMMO'] + 2 * k,
                      w(si.nums['ammo%d' % k])))
        pokes.append((pl + o['OFS_PL_MAXAMMO'] + 2 * k,
                      w(si.nums['maxammo%d' % k])))
    for j in range(6):
        pokes.append((pl + o['OFS_PL_WEAPONOWNED'] + 2 * (j + 1),
                      w(si.arms[j])))
    pokes.append((st + r.off('W_READY') + 8, w(r.ready_ptr(si.ready))))
    pokes.append((st + r.off('st_faceindex'), w(si.face)))
    for k in range(3):
        pokes.append((st + r.off('keyboxes') + 2 * k, w(si.keys[k])))
    pokes.append((st + r.off('st_refreshed'), w(si.refreshed)))
    at = r.off('W_READY')
    for wd in M.WIDGETS:
        if isinstance(wd, M.Num):
            pokes.append((st + at + 6, w(si.old[wd.name])))
            at += 12
        else:
            pokes.append((st + at + 4, w(si.old[wd.name])))
            at += 10
    sym = C.sym
    pokes += [(sym('m_menu65.s:_g_menuactive'), w(si.menuactive)),
              (sym('hu_stuff65.s:message_on'), w(si.message_on)),
              (sym('VW_MHID'), w(si.mhid)),
              (sym('i_viigs65.s:iigs_textShown'), w(si.text_shown)),
              (sym('_g_fps_framerate'), w(si.fps_rate)),
              (sym('i_viigs65.s:DRE'), bytes(200)),
              (sym('i_viigs65.s:DRY0'), bytes(4))]
    if not si.stcache_valid:
        pokes.append((sym('i_viigs65.s:stcachenum'), w(0xFFFF)))
    return pokes


def synth_saves() -> List[Tuple[int, int]]:
    r = ref()
    sym = C.sym
    return [(SHRBUF, 32000), (STCACHE, M.ST_BYTES), (r.st, r.st_size),
            (sym('i_viigs65.s:DRB'), 200), (sym('i_viigs65.s:DRE'), 200),
            (sym('hu_stuff65.s:message_on'), 2), (sym('VW_MHID'), 2),
            (sym('i_viigs65.s:iigs_textShown'), 4)]


def synth_truth(inputs: Sequence[SynthIn], jobs: int = 2
                ) -> List[List[str]]:
    """ref816 --call of ST_Drawer on the base state with each input
    poked: the saves (hex), cached by the inputs', the base's and this
    file's hash."""
    from concurrent.futures import ThreadPoolExecutor
    from native import s2drawcase as DC
    base = DC.BASE
    if not base.exists():
        raise StError('%s is missing: python3 tools/native/s2drawcase.py '
                      '(part s2draw\'s truth base)' % base)
    key = hashlib.sha256(json.dumps([list(map(str, i)) for i in inputs])
                         .encode() + hashlib.sha256(base.read_bytes())
                         .digest() + Path(__file__).read_bytes()
                         ).hexdigest()[:16]
    cache = SYNTH / ('drawer-%s.json.z' % key)
    if cache.exists():
        return json.loads(zlib.decompress(cache.read_bytes()))
    SYNTH.mkdir(parents=True, exist_ok=True)
    routine = C.sym('st_stuff65.s:ST_Drawer')
    pokes = [synth_pokes(si) for si in inputs]     # (before the threads)
    saves = synth_saves()

    def one(k: int) -> List[str]:
        work = Path(tempfile.mkdtemp(prefix='tmp-call-', dir=str(SYNTH)))
        try:
            path = work / 'pokes.img'
            DC.write_pokes(path, pokes[k])
            _, data = DC.call(base, [path], routine, {}, saves, work)
            return [d.hex() for d in data]
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    with ThreadPoolExecutor(max(1, jobs)) as ex:
        out = list(ex.map(one, range(len(inputs))))
    C.write_atomic(cache, zlib.compress(json.dumps(out).encode(), 6))
    return out


def synth_frames(jobs: int = 2) -> List[FrameCase]:
    """The synthetic frames as cases, with their truth."""
    from native import s2layout as S
    from ref816 import refimage
    from native import s2drawcase as DC
    inputs = synth_inputs()
    truth = synth_truth(inputs, jobs)
    mem = refimage.load(refimage.read(DC.BASE))
    r = ref()
    a = assets()
    sym = C.sym
    st0 = mem.get(r.st, r.st_size)
    pl0 = mem.get(r.pl, 155)
    scb = mem.get(sym('i_viigs65.s:scb'), 200)
    nib = mem.get(NIBTAB, 16 * 0x400)
    for p in set(b & 15 for b in scb[M.ST_Y:200]):
        if nib[p * 0x400:(p + 1) * 0x400] != a.nibtab[p * 0x400:
                                                      (p + 1) * 0x400]:
            raise StError('the base\'s NIBTAB %d is not GSSTAT\'s' % p)
    buf0 = mem.get(SHRBUF, 32000) + bytes(768)
    stc0 = mem.get(STCACHE, M.ST_BYTES)
    out = []
    for si, data in zip(inputs, truth):
        buf, stc, st1, drb, dre, mon, mhid, shown = \
            [bytes.fromhex(x) for x in data]
        tick0 = r.tick(st0)
        tick = tick0._replace(faceindex=si.face, keyboxes=si.keys,
                              refreshed=si.refreshed, ready=si.ready)
        p0 = r.player(pl0)
        ammo = tuple(si.nums['ammo%d' % k] for k in range(4)) + \
            tuple(si.nums['maxammo%d' % k] for k in range(4))
        player = p0._replace(health=si.nums['health'],
                             armorpoints=si.nums['armor'], ammo=ammo,
                             weaponowned=(p0.weaponowned[0],) + si.arms +
                             p0.weaponowned[7:])
        own = bytearray(256)
        st = S.state_places('P2DW')
        own[st['P_FPS'] - OWN_W] = 1 if si.ready[0] == 'fps' else 0
        for j, w in enumerate(M.WIDGETS):
            put_word(own, st['P_OLDREADY'] - OWN_W + 2 * j, si.old[w.name])
        own[st['P_STPALETTE'] - OWN_W] = tick0.palette & 0xFF
        card, unfit = card_bytes(tick, 0)
        records = ((1, S.S2STATE, S.SS['SS_P2DW'], bytes(own)),
                   (2, 0, S.BUILDS['test'].s2t_base, card),
                   (0, 0, inc_value('G_PLAYER'),
                    player_bytes(player, 0)),
                   (1, S.S2STATE, S.SS['SS_STCACHE'], stc0))
        after = bytes(buf) + bytes(768)
        marked = []
        for row in list(range(10)) + list(range(M.ST_Y, 200)):
            if dre[row]:
                marked += range(row * M.ROW + drb[row],
                                row * M.ROW + dre[row])
        old = {}
        for k, wd in enumerate(M.WIDGETS):
            old[wd.name] = si.old[wd.name]
        out.append(FrameCase(
            'synth', si.name, len(out), tick, player, (), False,
            si.menuactive, 1 if si.ready[0] == 'fps' else 0, si.fps_rate,
            old, si.stcache_valid, scb, buf0, stc0, si.message_on, si.mhid,
            si.text_shown, after, stc, r.old(st1),
            r.word(st1, 'st_refreshed'), drb[M.ST_Y:], dre[M.ST_Y:],
            tuple(marked), records, tuple(unfit),
            si.text_shown.to_bytes(2, 'little') + bytes(2),
            bool(si.menuactive and (si.message_on or si.mhid))))
    return out


def synth_model() -> Dict[str, Any]:
    out: Dict[str, Any] = {'frames': 0, 'kinds': {}, 'problems': []}
    for fc in synth_frames():
        bar, kind = model_frame(fc)
        out['kinds'][kind] = out['kinds'].get(kind, 0) + 1
        for p in frame_model_check(fc, bar):
            out['problems'].append('synth %s: %s' % (fc.name, p))
        if fc.strip and bytes(bar.buf[:10 * M.ROW]) != \
                fc.screen_after[:10 * M.ROW]:
            out['problems'].append('synth %s: the strip differs' % fc.name)
        out['frames'] += 1
    return out


# ---------------------------------------------------------------------------
# Synthetic tics: ST_Ticker's and ST_Start's paths by ref816 --call
# ---------------------------------------------------------------------------

# the player's fields every synthetic tic pokes first (the base state is
# the tour in god mode)
TIC_PLAYER_DEFAULTS = {'health': 100, 'damagecount': 0, 'bonuscount': 0,
                       'cheats': 0, 'attackdown': 0, 'readyweapon': 1,
                       'powers': (0, 0, 0, 0, 0, 0), 'cards': (0, 0, 0)}
FAKE_MOBJ = SHRBUF              # the attacker: x, y poked there (the back
                                #   buffer: ST_Ticker never reads it)


class TicIn(NamedTuple):
    name: str
    op: int                     # OP_TICKER or OP_START
    player: Dict[str, Any]      # fields of the player poked (upstream's)
    tick: Dict[str, Any]        # fields of the st block poked
    attacker: Optional[Tuple[int, int]]   # the fake mobj's x, y
    angle: Optional[int]        # the player's mobj's angle poked
    fps_show: int = 0


def tic_inputs() -> List[TicIn]:
    """Every path of updateFace at its edges, the turned head all
    around, readyNum's three sources, the key boxes, ST_Start with and
    without ST_Stop and with a weapon of no ammo."""
    out: List[TicIn] = []
    z = TicIn('', OP_TICKER, {}, {'priority': 0, 'facecount': 5,
                                  'oldhealth': 100, 'lastattackdown': 0xFFFF},
              None, None)
    out.append(z._replace(name='dead', player={'health': 0}))
    out.append(z._replace(name='dead-pri10', player={'health': 0},
                          tick=dict(z.tick, priority=10)))
    for b, w in ((6, 1), (6, 0), (0, 1)):
        out.append(z._replace(name='grin-%d-%d' % (b, w), player={
            'bonuscount': b, 'weaponowned': (1, 1, 0, w, 0, 0, 0, 0, 0)},
            tick=dict(z.tick, oldweaponsowned=(1, 1, 0, 0, 0, 0, 0, 0, 0))))
    out.append(z._replace(name='grin-pri9', player={
        'bonuscount': 6, 'weaponowned': (1, 1, 1, 0, 0, 0, 0, 0, 0)},
        tick=dict(z.tick, priority=9)))
    for h in (50, 79, 80, 81):              # muchPain at its edge
        out.append(z._replace(name='attacked-%d' % h, player={
            'health': h, 'damagecount': 10}, attacker=(0, 0), angle=0))
        out.append(z._replace(name='damage-%d' % h, player={
            'health': h, 'damagecount': 10}))
    for k in range(16):                     # the turned head all around
        for a in (0, 0x20000000, 0xC0000000):
            dx = (1 if k in (0, 1, 2, 14, 15) else -1 if 6 <= k <= 10
                  else 0) * (100 << 16) + (k * 7 << 16)
            dy = (1 if 2 <= k <= 6 else -1 if 10 <= k <= 14 else 0) * \
                (100 << 16) + (k * 3 << 16)
            out.append(z._replace(name='turn-%02d-%08X' % (k, a), player={
                'health': 90, 'damagecount': 5}, attacker=(dx, dy), angle=a,
                tick=dict(z.tick, oldhealth=95)))
    out.append(z._replace(name='attacked-self', player={
        'damagecount': 5}, attacker=None, angle=0,
        tick=dict(z.tick, oldhealth=95)))
    for last in (0xFFFF, 70, 2, 1, 0):
        out.append(z._replace(name='attack-%d' % last, player={
            'attackdown': 1}, tick=dict(z.tick, lastattackdown=last)))
    out.append(z._replace(name='attack-up', player={'attackdown': 0},
                          tick=dict(z.tick, lastattackdown=40)))
    out.append(z._replace(name='god-cheat', player={'cheats': 2}))
    out.append(z._replace(name='god-invul', player={'powers': (30, 0, 0,
                                                               0, 0, 0)}))
    out.append(z._replace(name='god-pri5', player={'cheats': 2},
                          tick=dict(z.tick, priority=5)))
    for fc in (0, 1):
        for h in (100, 150, 60, 0x8000, 0xFFF0):
            out.append(z._replace(name='straight-%d-%d' % (fc, h),
                                  player={'health': h},
                                  tick=dict(z.tick, facecount=fc,
                                            oldhealthPO=0x1234)))
    out.append(z._replace(name='much-overflow', player={
        'health': 0x7FF0, 'damagecount': 1},
        tick=dict(z.tick, oldhealth=0x8010)))
    for rw in (0, 1, 2, 5, 7):
        out.append(z._replace(name='ready-%d' % rw, player={
            'readyweapon': rw}))
    out.append(z._replace(name='ready-fps', fps_show=1))
    out.append(z._replace(name='keys', player={'cards': (0, 5, 0x100)}))
    for running in (0, 1):
        for rw in (0, 1, 7):
            out.append(TicIn('start-%d-%d' % (running, rw), OP_START,
                             {'readyweapon': rw, 'weaponowned':
                              (1, 1, 0, 1, 0, 0, 0, 0, 1)},
                             {'running': running, 'faceindex': 9,
                              'palette': 3}, None, None))
    return out


def tic_pokes(ti: TicIn, mo: int) -> List[Tuple[int, bytes]]:
    r = ref()
    w = lambda v: (v & 0xFFFF).to_bytes(2, 'little')  # noqa: E731
    sym = C.sym
    pokes: List[Tuple[int, bytes]] = []
    keys = {'health': 'OFS_PL_HEALTH', 'damagecount': 'OFS_PL_DAMAGECOUNT',
            'bonuscount': 'OFS_PL_BONUSCOUNT', 'cheats': 'OFS_PL_CHEATS',
            'attackdown': 'OFS_PL_ATTACKDOWN',
            'readyweapon': 'OFS_PL_READYWEAPON'}
    arrays = {'weaponowned': 'OFS_PL_WEAPONOWNED', 'powers': 'OFS_PL_POWERS',
              'cards': 'OFS_PL_CARDS'}
    fields = dict(TIC_PLAYER_DEFAULTS, **ti.player)
    for f, v in fields.items():
        if f in keys:
            pokes.append((r.pl + r.ofs[keys[f]], w(v)))
        else:
            for k, x in enumerate(v):
                pokes.append((r.pl + r.ofs[arrays[f]] + 2 * k, w(x)))
    st = {'priority': 'st_priority', 'facecount': 'st_facecount',
          'oldhealth': 'st_oldhealth', 'lastattackdown': 'st_lastattackdown',
          'oldhealthPO': 'st_oldhealthPO', 'faceindex': 'st_faceindex',
          'running': 'st_running', 'palette': 'st_palette'}
    for f, v in ti.tick.items():
        if f == 'oldweaponsowned':
            for k, x in enumerate(v):
                pokes.append((r.st + r.off('oldweaponsowned') + 2 * k,
                              w(x)))
        else:
            pokes.append((r.st + r.off(st[f]), w(v)))
    if ti.attacker is not None:
        x, y = ti.attacker
        pokes += [(FAKE_MOBJ + 12, (x & M.M32).to_bytes(4, 'little')),
                  (FAKE_MOBJ + 16, (y & M.M32).to_bytes(4, 'little')),
                  (r.pl + r.ofs['OFS_PL_ATTACKER'],
                   FAKE_MOBJ.to_bytes(4, 'little'))]
    elif ti.name == 'attacked-self':
        pokes.append((r.pl + r.ofs['OFS_PL_ATTACKER'],
                      mo.to_bytes(4, 'little')))
    else:
        pokes.append((r.pl + r.ofs['OFS_PL_ATTACKER'], bytes(4)))
    if ti.angle is not None:
        pokes.append((mo + 32, (ti.angle & M.M32).to_bytes(4, 'little')))
    pokes.append((sym('_g_fps_show'), w(ti.fps_show)))
    pokes.append((sym('i_viigs65.s:newpal'), w(NEWPAL_BEFORE)))
    return pokes


def tic_truth(inputs: Sequence[TicIn], jobs: int = 2) -> List[List[str]]:
    """ref816 --call of ST_Ticker or ST_Start on the base state, each
    input poked: the st block and the player before (after the pokes)
    and after, newpal after; cached."""
    from concurrent.futures import ThreadPoolExecutor
    from native import s2drawcase as DC
    from ref816 import refimage
    base = DC.BASE
    if not base.exists():
        raise StError('%s is missing: python3 tools/native/s2drawcase.py'
                      % base)
    key = hashlib.sha256(json.dumps([list(map(str, i)) for i in inputs])
                         .encode() + hashlib.sha256(base.read_bytes())
                         .digest() + Path(__file__).read_bytes()
                         ).hexdigest()[:16]
    cache = SYNTH / ('ticker-%s.json.z' % key)
    if cache.exists():
        return json.loads(zlib.decompress(cache.read_bytes()))
    SYNTH.mkdir(parents=True, exist_ok=True)
    r = ref()
    mem = refimage.load(refimage.read(base))
    mo = mem.word(r.pl + r.ofs['OFS_PL_MO'], 4)
    pokes = [tic_pokes(ti, mo) for ti in inputs]
    saves = [(r.st, r.st_size), (r.pl, 155),
             (C.sym('i_viigs65.s:newpal'), 2), (mo + 12, 4), (mo + 16, 4),
             (mo + 32, 4)]
    routines = {OP_TICKER: C.sym('st_stuff65.s:ST_Ticker'),
                OP_START: C.sym('st_stuff65.s:ST_Start')}

    def one(k: int) -> List[str]:
        work = Path(tempfile.mkdtemp(prefix='tmp-call-', dir=str(SYNTH)))
        try:
            path = work / 'pokes.img'
            DC.write_pokes(path, pokes[k])
            _, data = DC.call(base, [path], routines[inputs[k].op], {},
                              saves, work)
            return [d.hex() for d in data]
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    with ThreadPoolExecutor(max(1, jobs)) as ex:
        out = list(ex.map(one, range(len(inputs))))
    C.write_atomic(cache, zlib.compress(json.dumps(out).encode(), 6))
    return out


class SynthTic(NamedTuple):
    ti: TicIn
    before: M.Tick
    player: M.Player
    after: M.Tick
    pos: Optional[M.Pos]
    table: Tuple
    newpal: int
    st_after: bytes


def synth_tics(jobs: int = 2) -> List[SynthTic]:
    from native import s2drawcase as DC
    from ref816 import refimage
    inputs = tic_inputs()
    truth = tic_truth(inputs, jobs)
    r = ref()
    mem = refimage.load(refimage.read(DC.BASE))
    st0 = bytearray(mem.get(r.st, r.st_size))
    pl0 = bytearray(mem.get(r.pl, 155))
    mo = mem.word(r.pl + r.ofs['OFS_PL_MO'], 4)
    out = []
    for ti, data in zip(inputs, truth):
        st1, pl1, newpal, mx, my, ma = [bytes.fromhex(x) for x in data]
        st, pl = bytearray(st0), bytearray(pl0)
        for a, v in tic_pokes(ti, mo):          # the pokes on the base
            if r.st <= a < r.st + r.st_size:
                st[a - r.st:a - r.st + len(v)] = v
            elif r.pl <= a < r.pl + 155:
                pl[a - r.pl:a - r.pl + len(v)] = v
        x0, y0, a0 = [int.from_bytes(v, 'little') for v in (mx, my, ma)]
        pos, table = None, ((x0, y0, a0), (0, 0, 0))
        if ti.attacker is not None:
            x1, y1 = ti.attacker
            pos = M.Pos((x1 - x0) & M.M32, (y1 - y0) & M.M32, a0)
            table = ((x0, y0, a0), (x1, y1, 0))
        out.append(SynthTic(ti, r.tick(bytes(st)), r.player(bytes(pl)),
                            r.tick(st1), pos, table,
                            int.from_bytes(newpal, 'little'), st1))
    return out


def synth_tic_model() -> Dict[str, Any]:
    tk = ticker()
    out: Dict[str, Any] = {'cases': 0, 'paths': {}, 'problems': []}
    for sc in synth_tics():
        if sc.ti.op == OP_TICKER:
            got, tr = tk.ticker(sc.before, sc.player, sc.after.randomnumber,
                                sc.ti.fps_show, sc.pos)
            for p in tr.paths:
                out['paths'][p] = out['paths'].get(p, 0) + 1
            d = tick_diff(got, sc.after)
        else:
            got, setpal = tk.start(sc.before, sc.player)
            d = tick_diff(got, sc.after, TICK_STATE + ('refreshed',
                                                       'running', 'palette'))
            want = 0 if setpal == 0 else NEWPAL_BEFORE
            if sc.newpal != want:
                d.append('newpal %d, ref %d' % (want, sc.newpal))
        if d:
            out['problems'].append('synth %s: %s' % (sc.ti.name,
                                                     '; '.join(d[:4])))
        out['cases'] += 1
    return out


# ---------------------------------------------------------------------------
# The chained run, the coverage table, the timing
# ---------------------------------------------------------------------------

def native_chain(run: str = 'demo3', fill: int = 0xA5) -> Dict[str, Any]:
    """The run's level frames in order from the first frame's injected
    state only: each later frame gets the game's inputs and the tic
    side's card bytes from the reference, the 2D state (P2DW's own block,
    STCACHE, STBUF, the screen's rows, ST_REFRESHED) is the native
    code's, carried between the a2vm runs by their snapshots."""
    b = build('s2sb')
    fcs = frame_cases(run)
    carried: Optional[Carried] = None
    out: Dict[str, Any] = {'frames': 0, 'problems': [], 'stray': 0,
                           'runs': 0}
    for i in range(0, len(fcs), CASES_A_RUN):
        batch = []
        for j, fc in enumerate(fcs[i:i + CASES_A_RUN]):
            if i == 0 and j == 0:
                batch.append(staged(fc, fill, False))
            else:
                batch.append(staged(fc, fill, False, carried=carried if
                                    j == 0 else None, chain=True))
        res = native_batch(b, batch, fill, 'chain')
        out['frames'] += res.cases
        out['problems'] += res.problems
        out['stray'] += res.stray
        out['runs'] += 1
        if res.carried is None:
            out['problems'].append('chain: no state after frame %d' % i)
            break
        carried = res.carried
    return out


def coverage_universe() -> List[Tuple[str, str, int]]:
    """Each widget x glyph x place the bar can show: a number widget's
    digits 0-9 at places 1 and 2 (from the right), 1-9 at place 3 (no
    leading 0 below 1,000); each face, each key at its box, each arm gray
    and yellow, the two percent signs, STARMS, STBAR."""
    out = []
    for n in M.NUMS:
        for place in (1, 2, 3):
            for d in range(1 if place == 3 else 0, 10):
                out.append((n.name, n.glyphs[d], place))
    for g in M.FACES:
        out.append(('face', g, 0))
    for k in range(M.NUMCARDS):
        out.append(('key%d' % k, M.KEYS[k], 0))
    for a in M.ARMS:
        out += [(a.name, a.glyphs[0], 0), (a.name, a.glyphs[1], 0)]
    out += [('percent0', M.PERCENT, 0), ('percent1', M.PERCENT, 0),
            ('armsbg', M.ARMSBG, 0), ('bar', M.BAR, 0)]
    return out


def coverage(frames: Sequence[FrameCase]) -> Dict[str, Any]:
    """The draws of the frames (the model's, every frame compared equal
    natively), against the universe; a combination never drawn fails."""
    seen: Dict[Tuple[str, str, int], int] = {}
    for fc in frames:
        bar, _ = model_frame(fc)
        for d in bar.draws:
            key = (d.widget, d.glyph, d.place)
            seen[key] = seen.get(key, 0) + 1
    uni = coverage_universe()
    missing = [u for u in uni if u not in seen]
    by_widget: Dict[str, List[int]] = {}
    for u in uni:
        row = by_widget.setdefault(u[0], [0, 0])
        row[0] += 1
        row[1] += 1 if u in seen else 0
    return {'universe': len(uni), 'drawn': len(uni) - len(missing),
            'missing': ['%s %s place %d' % m for m in missing],
            'by_widget': by_widget,
            'extra': sorted('%s %s %d' % k for k in seen if k not in uni)}


def frame_kind(fc: FrameCase) -> str:
    """For the timing: 'refresh', 'nothing' (no widget changed), 'face'
    (only the face), else 'widgets'."""
    bar, kind = model_frame(fc)
    if kind != 'diff':
        return kind
    ws = set(d.widget for d in bar.draws)
    if not ws:
        return 'nothing'
    if ws == {'face'}:
        return 'face'
    return 'widgets'


def timing(profiles=('f121', 'fastpath'), per_kind: int = 6,
           jobs: int = 2) -> Dict[str, Any]:
    """Each kind of frame (nothing changed, the face changed, other
    widgets, a full refresh) of demo3 and the tour, each frame alone in
    its run, st_drawer in the cost phase 30: ms a frame (median, worst),
    the nibble tables fetched."""
    from concurrent.futures import ThreadPoolExecutor
    b = build('s2sb')
    picked: Dict[str, List[FrameCase]] = {}
    for run in ('demo3', 'tour'):
        for fc in frame_cases(run):
            k = frame_kind(fc)
            if len(picked.setdefault(k, [])) < per_kind and \
                    ready_known(fc):
                picked[k].append(fc)
    jobs_list = [(k, fc, prof) for k, fcs in picked.items() for fc in fcs
                 for prof in profiles]

    def one(job):
        k, fc, prof = job
        res = native_batch(b, [staged(fc, 0xA5, False)], 0xA5,
                           'timing', profile=prof)
        return k, prof, res
    out: Dict[str, Any] = {}
    problems = []
    with ThreadPoolExecutor(max(1, jobs)) as ex:
        for k, prof, res in ex.map(one, jobs_list):
            problems += res.problems
            row = out.setdefault(k, {}).setdefault(prof, {'ms': [],
                                                          'nibs': []})
            row['ms'].append(round(res.ms.get(30, 0.0), 3))
            row['nibs'] += res.nibs
    for k, by in out.items():
        for prof, row in by.items():
            ms = sorted(row['ms'])
            row['median'] = ms[len(ms) // 2] if ms else None
            row['worst'] = ms[-1] if ms else None
    return {'kinds': out, 'problems': problems}


def tic_timing(profiles=('f121', 'fastpath')) -> Dict[str, Any]:
    """st_ticker's µs a call: demo3's first 255 tics in one run (the
    phase 30 around each call), and the turned head's tics alone."""
    b = build('s2st')
    tcs = tic_cases('demo3')
    turn = [tc for tc in tcs if tc.pos is not None][:20]
    out: Dict[str, Any] = {}
    for prof in profiles:
        for name, cases in (('demo3', tcs[:255]), ('turnhead', turn)):
            res = tic_batch(b, [tic_stage(tc, 0xA5) for tc in cases], 0xA5,
                            profile=prof)
            us = res.ms.get(30, 0.0) * 1000.0 / max(1, len(cases))
            out.setdefault(name, {})[prof] = round(us, 1)
            if res.problems:
                out.setdefault('problems', []).extend(res.problems[:5])
    return out


# ---------------------------------------------------------------------------
# The planted bugs, each in a scratch copy of the sources
# ---------------------------------------------------------------------------

class Plant(NamedTuple):
    name: str
    what: str
    source: str                 # the file of src/native changed
    old: str
    new: str
    check: str                  # 'tics' or 'frames'


PLANTS = (
    Plant('pain-cache', 'painOffset\'s cache not refreshed (a health '
          'change keeps the old offset)', 's2t_st.s',
          '        bne @calc\n        cpy ST_OLDHEALTHPO+1\n',
          '        bra @done\n        cpy ST_OLDHEALTHPO+1\n', 'tics'),
    Plant('grin-any', 'the evil grin on any weapon change (no bonus '
          'needed)', 's2t_st.s',
          '        lda PLR + PO_BONUS\n        ora PLR + PO_BONUS+1\n'
          '        beq @att\n',
          '        lda #1\n        ora PLR + PO_BONUS+1\n'
          '        beq @att\n', 'tics'),
    Plant('sides', 'the turned head\'s sides swapped', 's2t_st.s',
          '        lda SB_I\n        bne :+\n        iny\n',
          '        lda SB_I\n        beq :+\n        iny\n', 'tics'),
    Plant('oldwidth', 'diffNum restoring the old number\'s width (its '
          'digits) instead of the widget\'s 3', 's2_st.s',
          '        lda #3                  ; (every number widget\'s width)'
          '\n        sta rr_cnt\n',
          '        jsr oldx\n        ldy #1\n        lda P_OLDREADY+1,x\n'
          '        bne @w3\n        lda P_OLDREADY,x\n        cmp #10\n'
          '        bcc @wd\n        iny\n        cmp #100\n'
          '        bcc @wd\n@w3:    ldy #3\n@wd:    sty rr_cnt\n', 'frames'),
    Plant('large', 'drawNum of LARGEAMMO (its digits drawn)', 's2_st.s',
          '        bne @go\n        rts\n@go:',
          '        bne @go\n        nop\n@go:', 'frames'),
    Plant('ammorows', 'the ammo rows in ammoRows\' wrong order (the first '
          'two swapped)', 's2_st.s',
          '        .byte ST_Y + 5, ST_Y + 11, ST_Y + 17, ST_Y + 23\n'
          '        .byte ST_Y + 5, ST_Y + 11, ST_Y + 17, ST_Y + 23\n',
          '        .byte ST_Y + 11, ST_Y + 5, ST_Y + 17, ST_Y + 23\n'
          '        .byte ST_Y + 11, ST_Y + 5, ST_Y + 17, ST_Y + 23\n',
          'frames'),
)


def plant_build(pl: Plant, root: Path) -> Path:
    """The part built from a scratch copy of its makefiles and of the
    planted file (the others from the tree) into root/m11: its images'
    directory."""
    from native import s2run as SR
    src = ROOT / 'src' / 'native'
    copy = root / 'src'
    (copy / 'm11').mkdir(parents=True)
    for name in ('m11.mk', 'm11/s2lay.mk', 'm11/s2stbar.mk'):
        shutil.copy(str(src / name), str(copy / name))
    text = (src / pl.source).read_text()
    if text.count(pl.old) != 1:
        raise StError('%s: the planted text is in %s %d times' % (
            pl.name, pl.source, text.count(pl.old)))
    (copy / pl.source).write_text(text.replace(pl.old, pl.new))
    m11 = root / 'm11'
    gen = m11 / 'shared' / 'gen'
    gen.mkdir(parents=True)
    for f in (M11 / 'shared' / 'gen').iterdir():
        shutil.copy(str(f), str(gen / f.name))
    (m11 / 's2data').mkdir()
    for f in ('s2data.inc', 's2data.json'):
        shutil.copy(str(S2DATA / f), str(m11 / 's2data' / f))
    old = ['-o', str(gen / 's2.inc'), '-o', str(gen / 's2-release.inc'),
           '-o', str(gen / 's2-m11.inc'), '-o', str(gen / 's2-fxch8.inc'),
           '-o', str(gen / 'rlayout.inc')]
    SR.make('s2stbar', m11=m11, source=copy, variables=old)
    return m11 / 's2stbar'


# the frames a quick plant run draws (the test's): every widget and
# glyph group redrawn, the ready number LARGEAMMO, the edges
QUICK_FRAMES = ('glyphs-00', 'glyphs-01', 'glyphs-02', 'glyphs-03', 'edges',
                'ready-00')


def plant_run(pl: Plant, jobs: int = 2, quick: bool = False
              ) -> Dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix='tmp-plant-', dir=str(WORK)))
    try:
        BUILD_DIR[0] = plant_build(pl, root)
        if pl.check == 'tics':
            res = native_tics(['synth'], jobs, fills=(0xA5,))
        else:
            res = native_frames(['synth'] if quick else
                                ['synth', 'newgame'], jobs, fills=(0xA5,),
                                poisons=(False,),
                                names=QUICK_FRAMES if quick else None)
        return {'name': pl.name, 'what': pl.what,
                'caught': bool(res['problems']),
                'problems': len(res['problems']),
                'first': res['problems'][:1]}
    finally:
        BUILD_DIR[0] = WORK
        shutil.rmtree(str(root), ignore_errors=True)


# ---------------------------------------------------------------------------
# The sizes, the checkpoint
# ---------------------------------------------------------------------------

def sizes() -> Dict[str, int]:
    """s2_st's bytes in P2DW's room (S2CODE, S2RODATA, S2DATA), s2t_st's
    in its own segments, of the built images' maps."""
    d = BUILD_DIR[0]
    a = module_bytes((d / 's2sb.map').read_text(),
                     ('S2CODE', 'S2RODATA', 'S2DATA'))
    b = module_bytes((d / 's2st.map').read_text(), TIC_SEGMENTS)
    return {'s2_st': a.get('s2_st', 0), 's2t_st': b.get('s2t_st', 0)}


def checkpoint(jobs: int = 2, plants: bool = True,
               timing_too: bool = True) -> Dict[str, Any]:
    """The part's checkpoint (SCREENS.md 7.3), report.json in WORK."""
    import time
    t0 = time.time()
    rep: Dict[str, Any] = {'problems': []}
    make_part()
    rep['sizes'] = sizes()
    if rep['sizes']['s2_st'] > DRAW_BUDGET:
        rep['problems'].append('s2_st is %d B, over %d' % (
            rep['sizes']['s2_st'], DRAW_BUDGET))
    if rep['sizes']['s2t_st'] > TIC_BUDGET:
        rep['problems'].append('s2t_st is %d B, over %d' % (
            rep['sizes']['s2t_st'], TIC_BUDGET))
    m = tic_model(TIC_RUNS)
    rep['model_tics'] = {k: m[k] for k in ('runs', 'paths')}
    rep['model_tics']['poked'] = m.get('poked', [])
    rep['problems'] += m['problems']
    m = frame_model(TIC_RUNS)
    rep['model_frames'] = {k: m[k] for k in ('runs', 'kinds', 'poked',
                                             'x_st1')}
    rep['problems'] += m['problems']
    m = synth_tic_model()
    rep['model_synth_tics'] = {k: m[k] for k in ('cases', 'paths')}
    rep['problems'] += m['problems']
    m = synth_model()
    rep['model_synth_frames'] = {k: m[k] for k in ('frames', 'kinds')}
    rep['problems'] += m['problems']
    frames = [fc for r in TIC_RUNS for fc in frame_cases(r)] + \
        synth_frames(jobs)
    cov = coverage(frames)
    rep['coverage'] = {k: cov[k] for k in ('universe', 'drawn', 'missing',
                                           'by_widget')}
    rep['problems'] += ['coverage: never drawn: ' + x
                        for x in cov['missing']]
    n = native_tics(list(TIC_RUNS) + ['synth'], jobs)
    rep['native_tics'] = {k: n[k] for k in ('cases', 'runs', 'stray',
                                            'stack')}
    rep['problems'] += n['problems']
    n = native_frames(list(TIC_RUNS) + ['synth'], jobs)
    rep['native_frames'] = {k: n[k] for k in ('cases', 'runs', 'stray',
                                              'stack', 'nibs')}
    rep['problems'] += n['problems']
    c = native_chain('demo3')
    rep['chain'] = {k: c[k] for k in ('frames', 'runs', 'stray')}
    rep['problems'] += c['problems']
    if timing_too:
        rep['timing'] = timing(jobs=jobs)
        rep['problems'] += rep['timing'].pop('problems')
        rep['tic_timing'] = tic_timing()
        rep['problems'] += rep['tic_timing'].pop('problems', [])
    if plants:
        rep['plants'] = [plant_run(pl, jobs) for pl in PLANTS]
        rep['problems'] += ['planted bug not caught: ' + x['name']
                            for x in rep['plants'] if not x['caught']]
    rep['seconds'] = round(time.time() - t0, 1)
    rep['ok'] = not rep['problems']
    C.write_atomic(WORK / 'report.json',
                   json.dumps(rep, indent=1, sort_keys=True).encode())
    return rep


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--model', action='store_true')
    parser.add_argument('--inc', metavar='OUT')
    parser.add_argument('--cfg-tic', metavar='OUT')
    parser.add_argument('--check-tic-map', metavar='MAP')
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--tics', action='store_true')
    parser.add_argument('--synth', action='store_true')
    parser.add_argument('--chain', action='store_true')
    parser.add_argument('--coverage', action='store_true')
    parser.add_argument('--timing', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--runs', default=','.join(TIC_RUNS))
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args(argv)
    runs = [r for r in args.runs.split(',') if r]
    # every check run below that reports a problem (or a planted bug not
    # caught) makes the exit status 1, whichever modes were asked
    failed = []
    if args.inc:
        write_inc(Path(args.inc))
        return 0
    if args.cfg_tic:
        from native import s2layout as S
        S.write_if_changed(Path(args.cfg_tic), cfg_tic())
        return 0
    if args.check_tic_map:
        rows, problems = check_tic_map(Path(args.check_tic_map).read_text())
        print('\n'.join(rows + problems))
        return 1 if problems else 0
    if args.capture:
        from concurrent.futures import ThreadPoolExecutor
        print(C.df_report(), flush=True)
        C.check_disk(BUILD)

        def one(run):
            out = capture_pos(run)
            return run, len(out['tickers']), len(out['pta3']), \
                len(out['starts']), out['problems']
        with ThreadPoolExecutor(max(1, args.jobs)) as ex:
            for run, n, p, s, problems in ex.map(one, runs):
                print('%s: %d ST_Ticker, %d turnHead, %d ST_Start, '
                      'problems %s' % (run, n, p, s, problems), flush=True)
                if problems:
                    failed.append('capture')
    if args.native:
        res = native_frames(runs, args.jobs, limit=args.limit)
        print('native frames: %d cases in %d runs, %d writes, %d stray, '
              'stack %d B, nibble fetches %s, %d problems' % (
                  res['cases'], res['runs'], res['writes'], res['stray'],
                  res['stack'], sorted(res['nibs'].items()),
                  len(res['problems'])))
        for p in res['problems'][:30]:
            print('  ' + p)
        if res['problems']:
            failed.append('native')
    if args.all:
        rep = checkpoint(args.jobs)
        print(json.dumps({k: v for k, v in rep.items()
                          if k != 'problems'}, indent=1, sort_keys=True))
        print('%d problems' % len(rep['problems']))
        for p in rep['problems'][:40]:
            print('  ' + p)
        return 0 if rep['ok'] else 1
    if args.plants:
        for pl in PLANTS:
            res = plant_run(pl, args.jobs)
            print('%s: %s, %d problems, %s' % (
                pl.name, 'caught' if res['caught'] else 'NOT CAUGHT',
                res['problems'], res['first']))
            if not res['caught']:
                failed.append('plants')
    if args.chain:
        res = native_chain()
        print('chain: %d frames in %d runs, %d stray, %d problems' % (
            res['frames'], res['runs'], res['stray'], len(res['problems'])))
        for p in res['problems'][:30]:
            print('  ' + p)
        if res['problems']:
            failed.append('chain')
    if args.coverage:
        frames = [fc for r in runs for fc in frame_cases(r)] + \
            synth_frames(args.jobs)
        res = coverage(frames)
        print('coverage: %d of %d drawn; missing %s' % (
            res['drawn'], res['universe'], res['missing'][:40]))
    if args.timing:
        print(json.dumps(timing(jobs=args.jobs), indent=1))
        print(json.dumps(tic_timing(), indent=1))
    if args.synth:
        res = synth_tic_model()
        print('synthetic tics (model): %d, paths %s, %d problems' % (
            res['cases'], res['paths'], len(res['problems'])))
        for p in res['problems'][:30]:
            print('  ' + p)
        if res['problems']:
            failed.append('synth')
        res = synth_model()
        print('synthetic frames (model): %d, kinds %s, %d problems' % (
            res['frames'], res['kinds'], len(res['problems'])))
        for p in res['problems'][:30]:
            print('  ' + p)
        if res['problems']:
            failed.append('synth')
    if args.tics:
        res = native_tics(runs, args.jobs)
        print('native tics: %d cases in %d runs, %d writes, %d stray, '
              'stack %d B, %d problems' % (
                  res['cases'], res['runs'], res['writes'], res['stray'],
                  res['stack'], len(res['problems'])))
        for p in res['problems'][:30]:
            print('  ' + p)
        if res['problems']:
            failed.append('tics')
    if args.model:
        res = tic_model(runs)
        print('ticker: %s calls, paths %s, poked inside %s, %d problems'
              % (res['runs'], res['paths'], res.get('poked'),
                 len(res['problems'])))
        for p in res['problems'][:20]:
            print('  ' + p)
        if res['problems']:
            failed.append('model')
        res = frame_model(runs)
        print('frames: %s, kinds %s, poked inside %s, X-ST1 %d, %d problems'
              % (res['runs'], res['kinds'], res['poked'], res['x_st1'],
                 len(res['problems'])))
        for p in res['problems'][:20]:
            print('  ' + p)
        if res['problems']:
            failed.append('model')
    if failed:
        print('failed: %s' % ', '.join(sorted(set(failed))))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
