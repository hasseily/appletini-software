#!/usr/bin/env python3
"""The tic level's native side (milestone 10, docs/GAME.md 3.6, 5.2-5.4):
a run of the lockstep build on a2vm, its state digested at every tic and
compared with the reference's (ticcap.py); the planted bugs, the timing
and the acceptance report.

Usage:  python3 tools/native/ticrun.py --run demo3 [--frames front|full|
                    none] [--fills a5[,5a]] [--tics N] [--jobs 8]
                    [--json FILE]
        python3 tools/native/ticrun.py --run demo1 --diff-at TIC
        python3 tools/native/ticrun.py --run demo3 --timing f121|fastpath
                    [--json FILE]
        python3 tools/native/ticrun.py --plant NAME|all [--json FILE]
        python3 tools/native/ticrun.py --report-md
        python3 tools/native/ticrun.py --selftest   (the machinery on the
                                                     skeleton's stub tic)

The image (build_image): the lockstep build (make -f game.mk game: every
part, LOCKSTEP, VCWRAP_UPSTREAM, TESTBUILD, TICLEVEL) with the load image
and, for frames, milestone 8's whole frame (render_records: rcard's W and
masked images in WCODE_BANK and MCODE_BANK, its replay's card parts, its
far_wload and far_mload, the main and aux 0 tables, the render tables);
the start state: the reference's at the G_Ticker entry of the run's first
setup's tic (a capture, start_case: the action that loads), its globals
and player written as part flow's load runs write them (no level: the
load makes it), the demo bank, the tic phase's globals; the renderer's
boot state (render_boot: milestone 11's s_rinit, the view's settings,
SPRBOUND by upstream's rule), and for FULL runs the persistent render
state of milestone 8's first capture (render_state_p0). GTEST holds the
schedule (the reference's frames after the start, each with the
display's view top: the message strip's rows or none), the stream of the
runs on the command ring (newgame, tour: every tic's command, the cheats,
the script's pokes, the menu's), the I_GetTime values, every setup's
re-key record, and each map's frame block level fields (GT_LEVELS). The
driver (gdriver.s, TICLEVEL) runs the tics from the start, the load
protocol, gametic + 1 after each tic, the frames (its display's part:
the fill spans' W_FSW/W_FSG, the intermission's snl_pointeron); a2vm's
--snapshot-stream gives the machine at every drv_tic, read as it comes
(never stored whole), each read through the game manifest of its map and
digested in worker processes (gcanon.digests, tic mode: FRONT runs leave
line.r_flags out, T1), and compared with the reference's digests of the
same gametic; the same-pair hits a tic against the reference's call log.
A FULL run compares every FULL_EVERY-th frame's records at the masked
phase's end (rcanon.final_*) and its view after the replay with milestone
8's capture of that frame (P4, P5), the message strip's rows excepted
when the display kept them. --diff-at keeps both states of a tic whole
(build/native/game/ticrun/) and prints the canonical diff.

A tic in which the native divides by zero (GT_DIV0) ends the comparison
of the run there, reported by name (T8).

--timing runs the gprof build under the cost model with a PC map of its
code (a2vm --cost-pcmap: each routine's subsystem, GAME.md 5.4's phases)
and a line a tic (--boundary drv_tic), no snapshot a tic.

--selftest runs the skeleton's image in lockstep mode with gtest.s's
stub ticker for a few tics with the snapshot stream, and checks that
every tic's snapshot comes, reads through the manifest and digests, with
the stream's bound kept.
"""

import argparse
import json
import shutil
import struct
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge.port import PortReader  # noqa: E402
from native import gcanon, glayout as GL, grun as G, llayout as LL, \
    render_check as RC, ticcap as TC  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
KEEP = GL.GAME / 'ticrun'
STREAM_LIMIT = 8 << 30          # through the pipe
SNAP_BANKS_EXTRA = (LL.MOBJP, LL.GTEST)


class TicRunError(Exception):
    pass


def ticker_label(b) -> Optional[str]:
    for name in ('G_Ticker', 'gt_tick'):
        if name in b.labels:
            return name
    return None


def digest_machine(m, mf, window: bool = False) -> Dict[str, str]:
    from native import setupcheck as SC
    nat = PortReader(mf).read(SC.port_memory(m))
    return gcanon.digests(nat, 'tic', window=window)


def stream_run(img: G.Image, work: Path, banks: Sequence[int],
               on_tic, tics: int, timeout: float = G.RUN_TIMEOUT,
               events: Sequence[str] = ()) -> G.Run:
    """A lockstep run with the snapshot stream on a named pipe, each
    snapshot given to on_tic(head, machine) as it comes."""
    import os
    fifo = work / 'snaps.fifo'
    work.mkdir(parents=True, exist_ok=True)
    os.mkfifo(str(fifo))
    errors: List[BaseException] = []

    def body():
        try:
            with open(str(fifo), 'rb') as handle:
                for head, m in G.read_stream(handle):
                    if m is None:
                        break
                    on_tic(head, m)
        except BaseException as error:
            errors.append(error)
    t = threading.Thread(target=body)
    t.daemon = True
    t.start()
    lab = img.b.labels
    r = G.run(img, work, GL.MODES['LOCKSTEP'],
              events=['pc %X@* snapshot tic' % lab['drv_tic']] +
              list(events), banks=banks,
              stream=(fifo, STREAM_LIMIT), every_limit=tics + 8,
              cycles=200_000_000_000, timeout=timeout)
    t.join(5)
    if t.is_alive():
        try:
            os.close(os.open(str(fifo), os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            pass
        t.join(60)
    if errors:
        raise errors[0]
    return r


def selftest(fill: int = 0xA5, tics: int = 6) -> Dict[str, Any]:
    """The machinery on the skeleton's image: lockstep with the stub
    ticker (a plain tic: gametic + 1) from the demo3 setup's level base,
    the snapshot stream read and digested a tic at a time."""
    from native import gameroutine as GR
    b = G.load_build(G.GAME / 'skel', 'skel')
    img = G.Image(b, fill, store=True)
    gamemap = 7
    img.recs += GR.base_records(gamemap)
    lab = b.labels
    img.poke_label('gt_act', b'\0')         # (no load: plain tics)
    img.poke_label('gt_cont', bytes(9))
    img.poke_label('gt_reent', b'\0')
    img.poke_label('gt_tphase', b'\1')
    img.main(LL.G['G_GAMEACTION'], b'\0\0')
    img.poke_word('dg_ticker', lab['gt_tstub'])
    img.poke_word('dg_resume', lab['gt_rstub'])
    img.poke_word('dg_frame', 0)
    start = struct.unpack_from('<I', bytes(_main_of(img, LL.G['G_GAMETIC'],
                                                    4)))[0]
    img.poke_label('dg_stop', struct.pack('<I', start + tics))
    img.gtest(GL.GTB['GT_SCHEDULE'], bytes(3))
    mf, _, banks = GR.manifest(gamemap)
    got: List[Dict[str, Any]] = []

    def on_tic(head, m):
        got.append({'gametic': struct.unpack_from(
            '<I', bytes(m.main[LL.G['G_GAMETIC']:LL.G['G_GAMETIC'] + 4]))[0],
            'digest': digest_machine(m, mf)})
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-ticrun-', dir=str(BUILD)))
    try:
        r = stream_run(img, work, list(banks) + list(SNAP_BANKS_EXTRA),
                       on_tic, tics)
        ended = r.ended()
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    problems = []
    if ended != 'halt':
        problems.append('the run ended %s' % ended)
    want = list(range(start, start + tics + 1))     # (the last: the end)
    if [x['gametic'] for x in got] != want:
        problems.append('tics %s, expected %s' % (
            [x['gametic'] for x in got], want))
    # every tic's digests: equal but the globals (gametic moves)
    for a, c in zip(got, got[1:]):
        kinds = gcanon.differing_kinds(a['digest'], c['digest'])
        if kinds != ['globals']:
            problems.append('tic %d to %d: kinds %s changed' % (
                a['gametic'], c['gametic'], kinds))
    return {'tics': len(got), 'problems': problems, 'first': got[:1]}


def _main_of(img: G.Image, address: int, n: int) -> bytes:
    """The image's main bytes at address (the last record that holds
    them)."""
    out = bytearray(n)
    for kind, bank, a, data in img.recs:
        if kind == 0 and a <= address and address + n <= a + len(data):
            out[:] = data[address - a:address - a + n]
    return bytes(out)


# ---------------------------------------------------------------------------
# A lockstep run (GAME.md 3.6, 5.2; the final integration)
# ---------------------------------------------------------------------------

GT = 'g_game65.s:G_Ticker'
CASES = KEEP / 'cases'          # the runs' start states (G_Ticker captures)
RENDER_OBJ = BUILD / 'native' / 'render' / 'obj'
RENDER_NAME = 'rcard'           # milestone 8's whole frame (RENDER.SYSTEM's)
TICS_A_SECOND = 400             # a bound: a2vm's tics a second at least
DECODE_JOBS = 8


def start_case(run_name: str, ref: Dict[str, Any], say=print):
    """The reference's state at the G_Ticker entry of the run's first
    setup's tic (the action that loads: the run's start, as part tic's
    load cases), captured once into CASES."""
    from native import gamecap as GC
    from native.gparts import mobjstate as MS
    tic = ref['setups'][0]['tic']
    MS.use_cases(CASES)
    p = GC.case_dir(run_name, GT) / ('h%08d.case.z' % (tic + 1))
    if not p.exists():
        sv = GC.survey_of(run_name)
        tics = sv['routines'][GT]['tic'] if sv else None
        if tics is not None and tics[tic] != tic:
            raise TicRunError('%s: G_Ticker hit %d is tic %d' % (
                run_name, tic + 1, tics[tic]))
        GC.capture(run_name, GT, [tic + 1], tics, say=say)
    return GC.load_case(p)


def ref_state(run_name: str, tic: int, say=print) -> Dict[str, Any]:
    """The reference's canonical state at the G_Ticker entry of `tic`
    (a capture, kept in CASES): a failing tic's state kept whole."""
    from native import gamecap as GC, gameroutine as GR
    from native.gparts import mobjstate as MS
    MS.use_cases(CASES)
    p = GC.case_dir(run_name, GT) / ('h%08d.case.z' % (tic + 1))
    if not p.exists():
        sv = GC.survey_of(run_name)
        tics = sv['routines'][GT]['tic'] if sv else None
        GC.capture(run_name, GT, [tic + 1], tics, say=say)
    return GR.Upstream(GC.load_case(p)).s_in


def render_records(rb, fill: int) -> List[Tuple[int, int, int, bytes]]:
    """Milestone 8's whole frame (the render build rb, rcard) in the tic
    image's machine, as RENDER.SYSTEM and the play disk place it: the W
    image in WCODE_BANK and the masked image in MCODE_BANK (the phase
    loader's), the replay's card parts (bank 2 $D000-$DFFF, $F900), the
    far layer's far_wload (its W length) and far_mload (MFAR) over the tic
    image's, the main and aux 0 tables, the render tables. Every other
    byte of the card is the tic image's (the test driver at $E000)."""
    from native import layout as L5, levelconv
    from native import rlayout as RL
    out: List[Tuple[int, int, int, bytes]] = []
    seg = rb.segments

    def part(name: str) -> bytes:
        return (rb.obj / ('%s.%s' % (rb.name, name))).read_bytes()
    lc2, rc, far = part('lc2'), part('rc'), part('far')
    for s_, data, base, kind in (('TEXBLK', lc2, 0xD000, 2),
                                 ('FILLE', lc2, 0xD000, 2),
                                 ('FILLO', lc2, 0xD000, 2),
                                 ('RHOT', lc2, 0xD000, 2),
                                 ('RCODE', rc, 0xF900, 2),
                                 ('BKNEAR', rc, 0xF900, 2),
                                 ('RLOAD', far, 0xDC00, 3),
                                 ('MFAR', far, 0xDC00, 3)):
        lo, hi = seg[s_]
        out.append((kind, 0, lo, data[lo - base:hi + 1 - base]))
    m08 = part('m08')
    for lo, hi in L5.MAIN_TABLE_RANGES:
        out.append((0, 0, lo, m08[lo - L5.MAIN_TABLES:hi - L5.MAIN_TABLES]))
    out.append((1, 0, L5.AUXCODE, part('a02')))
    a08 = part('a08')
    for lo, hi in L5.AUX_TABLE_RANGES:
        out.append((1, 0, lo, a08[lo - L5.AUX_TABLES:hi - L5.AUX_TABLES]))
    w = part('w')
    wend = RC.w_end(rb)
    out.append((1, RL.WCODE_BANK, 0x6000, w[:wend + 1 - 0x6000]))
    lo, hi = seg['MASKW']
    out.append((1, RL.MCODE_BANK, lo, part('wm')))
    for rec in levelconv.Image.parse((RC.TABLES / 'tables.img').read_bytes()):
        out.append(rec)
    return out


def render_boot(up) -> List[Tuple[int, int, int, bytes]]:
    """The renderer's own state at the run's start, as the boot leaves it
    (milestone 11's s_rinit, docs/PLAY.md 9 item 5: the frame block's
    persistent fields 0, the spans and their stamps 0, the covered ranges
    0, WPREV 0; GT_LEVELS gives the level's fields after each load), with
    the view's settings of the reference (viewtop, viewbottom, gamma, the
    automap's mode: not game state; the full view in every run), SKYFLAT
    the sky's pic byte, and SPRBOUND by upstream's rule from every sprite
    lump (playdisk.sprbound, the play disk's). The game fields of the
    frame block (VALIDCOUNT, NUKAGE) are the pre-state's, written after
    these records."""
    from native import levelconv, playdisk, rlayout as RL
    F = RL.FRAME
    t = up.table
    mem = up.case.entry

    def u16(name: str) -> int:
        return mem.u16(t.address(name))
    fb = bytearray(RL.FB_END - RL.FB)
    for name, value in (('VIEWTOP', u16('viewtop')),
                        ('VIEWBOT', u16('viewbottom')),
                        ('SKYFLAT', levelconv.SKY_PIC),
                        ('AUTOMAP', u16('automapmode'))):
        fb[F[name] - RL.FB] = value & 0xFF
    out = [(0, 0, RL.FB, bytes(fb)),
           (0, 0, RL.RINS['GAMMA'], struct.pack('<H', u16('_g_gamma'))),
           (0, 0, RL.SPANS, bytes(RL.CVFIRST - RL.SPANS)),
           (0, 0, RL.CVFIRST, bytes(320)),
           (0, 0, RL.WPREV, bytes(RL.FV_SIZE)),
           (1, RL.SPRT, RL.SPRBOUND_T, playdisk.sprbound())]
    return out


def level_fields() -> bytes:
    """GT_LEVELS: each map's frame block level fields from its header in
    the store (NUMNODES, NVERT, SKYBANK/SKYLO/SKYHI; milestone 11's
    s_level reads the same), E1M1 first."""
    from native import setupcheck as SC
    meta = SC.store_meta()
    out = bytearray()
    for m in range(1, 10):
        h = SC.header_of(meta, m)
        bank, base = h['sky']
        out += struct.pack('<HHBBB', h['counts']['nodes'],
                           h['counts']['vertices'], bank, base & 0xFF,
                           base >> 8)
    assert len(out) == 9 * GL.GT_LEVEL_RECORD
    return bytes(out)


VIEW_NONE, VIEW_HEIGHT = 0xFFFF, 168    # upstream's viewtop -1, viewbottom
AM_OVERLAY = 0x03                       # automapmode AM_ACTIVE | AM_OVERLAY


def schedule_bytes(ref: Dict[str, Any], start: int, kind_of) -> bytes:
    """GT_SCHEDULE: the reference's frames after the run's start tic, 3
    bytes each (the gametic's low word, the kind: kind_of(index, gametic),
    with FRAME_STRIP when the display kept the message strip's rows:
    viewtop 9, the reference's frame view), then a kind 0."""
    out = bytearray()
    views = ref.get('frame_view')
    if views is None or len(views) != len(ref['schedule']):
        raise TicRunError('the reference has no frame views (python3 '
                          'tools/native/ticcap.py --runs %s again)'
                          % ref['run'])
    n = 0
    for g, (top, bottom, am) in zip(ref['schedule'], views):
        if g <= start:
            continue
        if bottom != VIEW_HEIGHT or (am & AM_OVERLAY) == AM_OVERLAY or \
                top not in (VIEW_NONE, GL.VIEW_STRIPTOP):
            raise TicRunError('frame %d: viewtop %d, viewbottom %d, '
                              'automapmode %d: no such view in the '
                              'driver' % (g, top, bottom, am))
        kind = kind_of(n, g) | (GL.FRAME_STRIP if top == GL.VIEW_STRIPTOP
                                else 0)
        out += struct.pack('<HB', g & 0xFFFF, kind)
        n += 1
    out += bytes(3)
    if len(out) > 0x1000:
        raise TicRunError('%d frames: GT_SCHEDULE holds %d' % (
            n, 0x1000 // 3 - 1))
    return bytes(out)


def _digest_job(job) -> Tuple[int, int, Dict[str, str], List[str]]:
    """A snapshot's canonical digests (in a worker): (gametic, map,
    digests, problems)."""
    gametic, gamemap, main, aux, window, front = job
    from native import gameroutine as GR
    from bridge.memory import MAIN, PortMemory
    pm = PortMemory()
    pm.write(MAIN, main)
    for bank, data in aux.items():
        pm.write(bank << 16, data)
    mf, _, _ = GR.manifest(gamemap)
    try:
        nat = PortReader(mf).read(pm)
    except Exception as error:      # (reported per tic)
        return gametic, gamemap, {}, ['the port reader: %s' % error]
    d = gcanon.digests(nat, 'tic', window=window, front=front)
    d['@zmobjs'] = len(nat['objects'].get('zmobj', {}))
    return gametic, gamemap, d, []


def native_state(m) -> Dict[str, Any]:
    from native import gameroutine as GR, setupcheck as SC
    gm = struct.unpack_from('<H', bytes(m.main[LL.G['G_GAMEMAP']:
                                             LL.G['G_GAMEMAP'] + 2]))[0]
    mf, _, _ = GR.manifest(gm)
    return PortReader(mf).read(SC.port_memory(m))


# ---------------------------------------------------------------------------
# FULL frames (acceptance 5): the whole frame in the lockstep, its record
# stream and its view compared with milestone 8's captures of ref816
# ---------------------------------------------------------------------------

FRAMES8 = BUILD / 'native' / 'render' / 'frames'
FULL_EVERY = 10                 # a compared frame every 10 (the lean rule)
E1_SCREEN, VIEW_BYTES = 0xE12000, 168 * 160
FULL_BANKS = (0,) + tuple(range(51, 55)) + (8, 7)     # aux 0, RECSP, RENDB,
                                                      # LVMAP (rlayout)
STRIP_BYTES = (9 + 1) * 160     # the message strip's rows 0-9


def frame_dir(run_name: str, index: int) -> Path:
    return FRAMES8 / ('%s-%03d' % (run_name, index))


def store_maps(gamemap: int):
    """The native store's texel slots (bank, address) and patch map as
    upstream's addresses (lstore.py's texmap.json, patchmap.json), and
    each lump's patch store index: rcanon's slots, pmap and index for a
    level the native loader made (the lockstep's), where milestone 8's
    frame mode took the level source's conversion."""
    d = BUILD / 'native' / 'levels' / 'store' / ('e1m%d' % gamemap)
    tm = json.loads((d / 'texmap.json').read_text())['slots']
    slots = {(b_, a): ptr for b_, a, ptr in tm.values()}
    pm = json.loads((d / 'patchmap.json').read_text())['entries']
    pmap = sorted((e[0], e[1], e[2], e[3]) for e in pm)
    index = {e[4]: e[5] for e in pm}
    return slots, pmap, index


def render_state_p0(index_frame: Path) -> List[Tuple[int, int, int, bytes]]:
    """The renderer's own persistent state of a milestone 8 capture's P0
    (framestate.py's injection, RENDER-MASKED.md 2.3), the game's fields
    left out (the run's own state holds them: the sectors, sides, things,
    validcount, TEXTRANS, LNMAP, the level's counts and sky, the player's
    view, the colormaps): GAME.md 5.2 row 5's "the renderer's persistent
    state from ref816 at the run's start only". The vertex cache's stamp
    0: the load rewrites the cache's planes."""
    from bridge import linkmap as blink
    from native import framestate as FS, rlayout as RL
    sym = blink.Symbols()
    frame = FS.Frame(index_frame)
    level_dir = FS.level_of(frame, sym)
    level = json.loads((level_dir / 'level.json').read_text())
    inputs = FS.read_inputs(frame, sym, level)
    recs = FS.records(frame, inputs, level)
    F = RL.FRAME
    keep_fb = {F[k] for k in ('SKYFLAT', 'AUTOMAP', 'W_FSC', 'W_FSP',
                              'W_TOPR', 'W_BOTR', 'W_FSG', 'W_FSW',
                              'FR_SKIP', 'W_WSK', 'MM_WPOK', 'VA_VX', 'VA_VY',
                              'RW_STEP', 'W_LCC', 'W_LFC', 'W_CEILW',
                              'W_FLOORW', 'FZPOS')}
    keep_main = {RL.RINS['GAMMA'], RL.SPANS, RL.CVFIRST, RL.WCLIP, RL.WPREV,
                 RL.FRVIS, RL.WTMP}
    out = []
    for kind, bank, addr, data in recs:
        if kind == 0 and (addr in keep_fb or addr in keep_main):
            out.append((kind, bank, addr, data))
    # SPRBOUND: upstream computes it during the level set's first frame
    # (r_thing65.s frameInit), so the first capture's P0 holds none yet
    # (zeros, which reject the sprites at the view's edges): the next
    # frame's, the bounds of the whole run
    nxt = index_frame.parent / (index_frame.name[:-3] + '%03d' % (
        int(index_frame.name[-3:]) + 1))
    p0 = FS.Frame(nxt).dump('p0')
    out.append((1, RL.SPRT, RL.SPRBOUND_T,
                p0.read(FS.MM_SPRBOUND, 4 * RL.NUMSPRITES)))
    out.append((0, 0, F['VA_STAMP'], b'\0'))
    out.append((0, 0, F['VA_COUNT'], b'\0\0'))
    return out


def _full_job(job) -> Dict[str, Any]:
    """A compared FULL frame (in a worker): the native records at the
    masked phase's end against the capture's P4, the view after the
    replay against its P5 (but the message strip's rows when the display
    kept them: upstream's HUD text, milestone 11's)."""
    run_name, index, gametic, gamemap, strip, mend, fend = job
    from bridge import linkmap as blink
    from native import framestate as FS, rcanon
    out: Dict[str, Any] = {'frame': '%s-%03d' % (run_name, index),
                           'gametic': gametic, 'strip': strip}
    d = frame_dir(run_name, index)
    if not d.exists():
        out['problems'] = ['no capture %s' % d.name]
        return out
    sym = blink.Symbols()
    frame = FS.Frame(d)
    slots, pmap, pindex = store_maps(gamemap)
    try:
        truth = rcanon.final_truth(frame, sym, pindex)
        snap = rcanon.Snapshot(mend)
        nat = rcanon.final_native(snap, slots, pmap, False)
    except rcanon.CanonError as error:
        out['problems'] = ['the records: %s' % error]
        return out
    out['rules'] = nat.get('rules', 0)
    probs = rcanon.diff_final(dict(truth, cliplog=None),
                              dict(nat, cliplog=None))
    out['records'] = sum(len(v) for v in nat['records'].values())
    want = frame.dump('p5').read(E1_SCREEN, VIEW_BYTES)
    got = fend
    lo = STRIP_BYTES if strip else 0
    diff = [i for i in range(lo, VIEW_BYTES) if got[i] != want[i]]
    out['view_differing'] = len(diff)
    if strip:
        out['strip_differing'] = sum(1 for i in range(STRIP_BYTES)
                                     if got[i] != want[i])
    if diff:
        i = diff[0]
        probs.append('the view: %d bytes differ (first row %d col %d: '
                     'native $%02X, reference $%02X)' % (
                         len(diff), i // 160, i % 160, got[i], want[i]))
    out['problems'] = probs
    return out


def _in_window(windows, tic: int) -> bool:
    return any(w['from'] <= tic and (w['to'] is None or tic < w['to'])
               for w in windows)


def run(run_name: str, fills: Sequence[int] = (0xA5,),
        image: str = 'game', tics: Optional[int] = None,
        frames: str = 'front', jobs: int = DECODE_JOBS,
        say=print, keep_fail: bool = True) -> Dict[str, Any]:
    """The run in lockstep-schedule mode on each fill: every tic's
    digests against the reference's (GAME.md 3.6)."""
    ref = TC.load(run_name)
    if ref is None:
        raise TicRunError('no reference of %s (python3 tools/native/'
                          'ticcap.py --runs %s)' % (run_name, run_name))
    G.make(image)
    b = G.load_build(G.GAME / image, image)
    if ticker_label(b) is None:
        return {'run': run_name, 'ok': False,
                'stopped': 'G_Ticker is not built'}
    out: Dict[str, Any] = {'run': run_name, 'image': image,
                           'frames': frames, 'fills': {}}
    for fill in fills:
        out['fills']['%02x' % fill] = run_fill(run_name, ref, b, fill,
                                               tics, frames, jobs, say,
                                               keep_fail)
    out['ok'] = all(r.get('ok') for r in out['fills'].values())
    return out


def build_image(run_name: str, ref: Dict[str, Any], b, fill: int,
                frames: str, stop: int, say=print):
    from native import gameroutine as GR
    from native.gparts import flowcheck as FC
    case = start_case(run_name, ref, say)
    up = GR.Upstream(case)
    if up.r_out.problems:
        raise TicRunError('the start\'s bridge problems: %s' %
                          up.r_out.problems[:3])
    table = up.table
    gm_out = case.after.u16(table.address(GR.TIC_GAMEMAP))
    gm_in = up.gamemap if 1 <= up.gamemap <= 9 else gm_out
    mf, header, banks = GR.manifest(gm_out)
    level = FC.level_build()
    img = G.Image(b, fill, level=level, store=True)
    img.recs += GR.base_records(gm_in)
    rb = None
    if frames != 'none':
        rb = RC.load_build(RENDER_OBJ, RENDER_NAME)
        img.recs += render_records(rb, fill)
        img.recs += render_boot(up)
        if frames == 'full':
            img.recs += render_state_p0(frame_dir(run_name, 0))
    pm = G.tracked_memory()
    FC.write_prestate(mf, up.s_in, pm)
    img.recs += G.port_records(pm)
    img.recs += GR.derived(pm, header)
    img.recs += FC.demob_records(up, mf)
    img.recs += GR.tic_main_records(case.entry)
    lab = b.labels
    img.poke_word('dg_ticker', lab['g_ttick'])
    img.poke_word('dg_resume', lab['g_tresume'])
    img.poke_label('dg_rekey', b'\0')
    img.poke_label('dg_nosnap', b'\0')     # (DESC is poisoned)
    img.poke_label('dg_wipe', b'\0')
    recs = b''.join(bytes.fromhex(s['rekey']) for s in ref['setups'])
    if len(recs) > GL.GTB['GT_SOUNDS'] - GL.GTB['GT_REKEYS']:
        raise TicRunError('%d setups: GT_REKEYS holds fewer' %
                          len(ref['setups']))
    img.gtest(GL.GTB['GT_REKEYS'], recs)
    times = [t['value'] for t in ref.get('times', [])]
    img.poke_word('dg_tcount', len(times))
    img.gtest(GL.GTB['GT_TIMES'], struct.pack('<I', len(times)) +
              b''.join(struct.pack('<I', v & 0xFFFFFFFF) for v in times))
    img.poke_label('dg_stop', struct.pack('<I', stop))
    start = ref['setups'][0]['tic']
    stream_path = TC.OUT / (run_name + '.stream')
    if run_name in ('newgame', 'tour') or run_name.startswith('ring-'):
        data = stream_path.read_bytes()
        if len(data) > GL.GTB['GT_TIMES'] - GL.GTB['GT_STREAMB']:
            raise TicRunError('the stream passes GT_STREAMB')
        img.gtest(GL.GTB['GT_STREAMB'], data)
        img.poke_word('dg_strm', GL.GTB['GT_STREAMB'] + 9)
        img.poke_word('dg_scnt', struct.unpack_from('<I', data, 5)[0])
    else:
        img.poke_word('dg_strm', 0)
        img.poke_word('dg_scnt', 0)
    if rb is not None:
        rl = rb.labels
        for name, label in (('dg_fwl', 'far_wload'), ('dg_frame', 'nr_frame'),
                            ('dg_fml', 'far_mload'), ('dg_fmm', 'nm_masked'),
                            ('dg_fbl', 'nm_bkload'), ('dg_fnb', 'nb_frame')):
            img.poke_word(name, rl[label])
        if frames == 'front':
            kind_of = lambda i, g: GL.FRAME_FRONT      # noqa: E731
        else:
            kind_of = lambda i, g: GL.FRAME_FULL + (   # noqa: E731
                1 if i % FULL_EVERY == 0 else 0)
        img.gtest(GL.GTB['GT_SCHEDULE'], schedule_bytes(ref, start, kind_of))
        img.gtest(GL.GTB['GT_LEVELS'], level_fields())
    else:
        img.poke_word('dg_frame', 0)
        img.gtest(GL.GTB['GT_SCHEDULE'], bytes(3))
    return img, case, up, banks


def run_fill(run_name: str, ref: Dict[str, Any], b, fill: int,
             tics: Optional[int], frames: str, jobs: int, say=print,
             keep_fail: bool = True) -> Dict[str, Any]:
    from concurrent.futures import ProcessPoolExecutor
    import time
    from native import gameroutine as GR
    ref_tics = {t['tic']: t for t in ref['tics']}
    order = sorted(ref_tics)
    front = frames == 'front'
    if front and 'digest_front' not in ref['tics'][0]:
        raise TicRunError('the reference has no FRONT digests (python3 '
                          'tools/native/ticcap.py --runs %s again)' %
                          run_name)
    last = order[-1] if tics is None else order[min(tics, len(order)) - 1]
    stop = last + 1
    img, case, up, _ = build_image(run_name, ref, b, fill, frames, stop, say)
    banks = set()
    for m in range(1, 10):
        banks |= set(GR.manifest(m)[2])
    banks = banks | set(SNAP_BANKS_EXTRA)
    if frames == 'full':
        banks |= set(FULL_BANKS)
    banks = sorted(banks)
    windows = ref.get('windows', [])
    res: Dict[str, Any] = {'fill': '%02x' % fill, 'start':
                           ref['setups'][0]['tic'], 'last': last}
    start = res['start']
    full_frames = [(i, g, top) for i, (g, (top, _, _)) in enumerate(
        (g, v) for g, v in zip(ref['schedule'], ref.get('frame_view', []))
        if g > start) if i % FULL_EVERY == 0 and g <= last]
    full_jobs: List[Any] = []
    pending: Dict[str, Any] = {}
    events = []
    if frames == 'full':
        events = ['pc %X@* snapshot mend' % b.labels['drv_fmend'],
                  'pc %X@* snapshot fend' % b.labels['drv_fend']]
    futures = []
    seen: List[int] = []
    hits: Dict[int, int] = {}
    keep: Dict[int, Any] = {}
    pool = ProcessPoolExecutor(max_workers=jobs)
    lab = b.labels
    hl = LL.G.get('GT_HITLOG')

    def on_tic(head, m):
        name = str(head.get('name', ''))
        if name.startswith('mend'):
            pending['mend'] = [(0, 0, 0, bytes(m.main[0:0xC000]))] + [
                (1, bk, 0x0200, bytes(d[0x0200:0xC000]))
                for bk, d in m.aux.items()]
            return
        if name.startswith('fend'):
            k = len(full_jobs)
            if k < len(full_frames):
                i, g, top = full_frames[k]
                gm = struct.unpack_from('<H', bytes(
                    m.main[LL.G['G_GAMEMAP']:LL.G['G_GAMEMAP'] + 2]))[0]
                job = (run_name, i, g, gm, top == GL.VIEW_STRIPTOP,
                       pending.pop('mend', []),
                       bytes(m.aux[0][0x2000:0x2000 + VIEW_BYTES]))
                full_jobs.append(pool.submit(_full_job, job))
            return
        if name.startswith('crash'):
            res['stop'] = G.stop_codes(m)
            res['crash_gametic'] = struct.unpack_from('<I', bytes(
                m.main[LL.G['G_GAMETIC']:LL.G['G_GAMETIC'] + 4]))[0]
            return
        g = struct.unpack_from('<I', bytes(m.main[LL.G['G_GAMETIC']:
                                                  LL.G['G_GAMETIC'] + 4]))[0]
        gm = struct.unpack_from('<H', bytes(m.main[LL.G['G_GAMEMAP']:
                                                   LL.G['G_GAMEMAP'] + 2]))[0]
        if seen and seen[-1] == g:
            # (an interrupt taken at drv_tic returns to it and a2vm's
            # every-visit event fires again: the same snapshot twice)
            return
        seen.append(g)
        dz = m.main[LL.G['GT_DIV0']] | m.main[LL.G['GT_DIV0'] + 1] << 8
        if dz and 't8' not in res:
            res['t8'] = g                   # (T8: a division by zero)
        hw = m.main[LL.G['G_MOHWM']] | m.main[LL.G['G_MOHWM'] + 1] << 8
        res['mohwm_max'] = max(res.get('mohwm_max', 0), hw)
        # the same-pair hits logged since the last snapshot, by their tic
        if hl is not None:
            n = m.main[hl] | m.main[hl + 1] << 8
            log = m.aux.get(LL.GTEST)
            for k in range(min(n, 0x400 // GL.HIT_EVENT)):
                at = GL.GTB['GT_HITS'] + GL.HIT_EVENT * k
                t = log[at] | log[at + 1] << 8 if log else -1
                hits[t] = hits.get(t, 0) + 1
        if g in ref_tics and 1 <= gm <= 9:
            main = bytes(m.main[0:0xC000])
            aux = {bk: bytes(d[0:0xC000]) for bk, d in m.aux.items()}
            futures.append(pool.submit(_digest_job, (
                g, gm, main, aux, _in_window(windows, g), front)))
            if len(keep) < 3 and g in (last,):
                keep[g] = None
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-ticrun-', dir=str(BUILD)))
    t0 = time.time()
    try:
        r = stream_run(img, work, banks, on_tic, (last - res['start']) + 8,
                       timeout=max(900.0, (last - res['start']) /
                                   TICS_A_SECOND * 60), events=events)
        res['ended'] = r.ended()
        res['cycles'] = r.state.get('cycles')
        if res['ended'] != 'halt':
            p = work / 'crash.img'
            if p.exists():
                cm = G.load_snapshot(p)
                res['stop'] = G.stop_codes(cm)
                res['crash_gametic'] = struct.unpack_from(
                    '<I', bytes(cm.main[LL.G['G_GAMETIC']:
                                        LL.G['G_GAMETIC'] + 4]))[0]
            res['pc'] = r.state.get('pc')
        digests = {}
        for f in futures:
            g, gm, d, probs = f.result()
            digests[g] = (gm, d, probs)
        full = [f.result() for f in full_jobs]
    finally:
        pool.shutdown()
        shutil.rmtree(str(work), ignore_errors=True)
    res['seconds'] = round(time.time() - t0, 1)
    res['snapshots'] = len(seen)
    compared, failures = 0, []
    for g in order:
        if g > last or ('t8' in res and g > res['t8']):
            break                       # (T8 ends the comparison there)
        if g not in digests:
            failures.append({'tic': g, 'why': 'no native snapshot'})
            continue
        gm, d, probs = digests[g]
        zm = d.pop('@zmobjs', 0)
        res['zmobjs_max'] = max(res.get('zmobjs_max', 0), zm)
        want = ref_tics[g]['digest_front' if front else 'digest']
        if _in_window(windows, g):
            want = None                 # (re-digested below if it fails)
        compared += 1
        if probs:
            failures.append({'tic': g, 'why': probs[:2]})
        elif want is not None and gcanon.differing_kinds(want, d):
            failures.append({'tic': g, 'kinds': gcanon.differing_kinds(
                want, d)})
    res['tics_compared'] = compared
    res['failures'] = len(failures)
    # milestone 9's gate "the block walk's order on every move": the tics
    # whose sector nodes or block lists the reference changed, each
    # compared as sequences
    key = 'digest_front' if front else 'digest'
    changed = {'secnode': 0, 'blocklink': 0}
    prev = None
    for g in order:
        if g > last:
            break
        d = ref_tics[g][key]
        if prev is not None:
            for k in changed:
                if d.get(k, gcanon.EMPTY_TABLE) != prev.get(
                        k, gcanon.EMPTY_TABLE):
                    changed[k] += 1
        prev = d
    res['tics_changed'] = changed
    res['first_failures'] = failures[:8]
    # the same-pair hits a tic against the reference's
    # (the hits of tics start < tic < last: the reference's run can end
    # inside its last tic, whose calls its log then lacks)
    want_hits = {int(k): v for k, v in ref.get('same_pair_hits', {}).items()
                 if res['start'] < int(k) < last}
    got_hits = {k: v for k, v in hits.items() if res['start'] < k < last}
    res['same_pair_hits'] = {'reference': sum(want_hits.values()),
                             'native': sum(got_hits.values()),
                             'tics_differing': sorted(
                                 k for k in set(want_hits) | set(got_hits)
                                 if want_hits.get(k) != got_hits.get(k))[:20]}
    res['ok'] = (not failures and res['ended'] == 'halt' and
                 not res['same_pair_hits']['tics_differing'])
    if frames == 'full':
        t7 = [f['frame'] for f in full if f.get('rules')]
        bad = [f for f in full if f.get('problems') and not f.get('rules')]
        res['full'] = {'frames_compared': len(full), 'frames_scheduled':
                       len(full_frames), 'failures': len(bad), 'T7': t7,
                       'strip_frames': [f['frame'] for f in full
                                        if f.get('strip')],
                       'records': sum(f.get('records', 0) for f in full),
                       'first_failures': [{k: v for k, v in f.items()
                                           if k in ('frame', 'gametic',
                                                    'problems')}
                                          for f in bad[:6]]}
        res['ok'] = res['ok'] and not bad and len(full) == len(full_frames)
    return res


# ---------------------------------------------------------------------------
# The timing report (GAME.md 5.4): the gprof build on a2vm's cost model,
# each tic's time by subsystem from a PC map of the build (a2vm
# --cost-pcmap: the phase of the code that runs, the innermost by
# construction), a line a tic (--boundary drv_tic)
# ---------------------------------------------------------------------------

PH_EXIT, PH_TIC, PH_LOAD = 18, 30, 31
PHASE_NAMES = {18: 'entry/exit', 19: 'walk', 20: 'moves', 21: 'sight',
               22: 'traces', 23: 'monsters', 24: 'combat', 25: 'player',
               26: 'world', 27: 'flow', 28: 'paging', 29: 'object API',
               30: 'math', 31: 'load'}
PART_PHASE = {
    'tic': 19, 'mobjstate': 19,
    'xymove': 20, 'trymove': 20, 'checkpos': 20, 'geom': 20,
    'sight': 21, 'path': 22, 'tracel': 22, 'tracet': 22,
    'look': 23, 'chasemove': 23, 'chase': 23,
    'attack': 24, 'damage': 24, 'missile': 24, 'wfire': 24, 'spawn': 24,
    'player': 25, 'pspr': 25, 'pickup': 25,
    'secfind': 26, 'planes': 26, 'movers': 26, 'evworld': 26,
    'evfloor': 26, 'lines': 26, 'teleport': 26, 'flow': 27}
MODULE_PHASE = {'gthink': 19, 'gpos': 20, 'gvalid-u': 20, 'gvalid': 20,
                'zmove': 20, 'gspawn': 24, 'gweap': 25, 'gspec': 26,
                'gtick': 27, 'ghook': 27, 'gcall': 28, 'gobj': 29,
                'math-g': 30, 'math-r': 30, 'gdriver': 27, 'grec': 27,
                'auxlc': 30}


def module_parts() -> Dict[str, str]:
    """Each part source's module (its object's stem) and its part (the
    fragments' *_SRC)."""
    import re
    out: Dict[str, str] = {}
    for f in sorted((ROOT / 'src' / 'native' / 'game').glob('*/part.mk')):
        part = f.parent.name
        for m in re.finditer(r'game/%s/([\w-]+)\.s' % part, f.read_text()):
            out[m.group(1)] = part
    return out


def pcmap_text(b) -> str:
    """The PC map of a tic image b (a2vm --cost-pcmap): each module's code
    with its subsystem's phase (PART_PHASE by its part, MODULE_PHASE for
    the runtime and milestone 9's core), the groups conditional on the
    slot's group (SLOT_GRP + the slot); the far layer split: far_pload
    (RLOAD) is the paging's, the rest the object API's."""
    parts = module_parts()
    slot_grp = GL.TGM.get('SLOT_GRP') or _inc_value(b, 'SLOT_GRP')
    lines = ['# a2vm --cost-pcmap of %s (tools/native/ticrun.py)' % b.name]
    for module, seg, lo, hi in G.contributions(b):
        if module == 'far':
            ph = 28 if seg == 'RLOAD' else (30 if seg == 'MATHFAR' else 29)
        elif module in MODULE_PHASE:
            ph = MODULE_PHASE[module]
        elif module in parts:
            ph = PART_PHASE[parts[module]]
        else:
            ph = 27
        if seg.startswith('GGRP'):
            n = int(seg[4:])
            slot = 1 if lo < GL.WR['SLOT2'][0] else 2
            lines.append('%04X %04X %d %04X %d' % (lo, hi - 1, ph,
                                                   slot_grp + slot, n))
        else:
            lines.append('%04X %04X %d' % (lo, hi - 1, ph))
    return '\n'.join(lines) + '\n'


def _inc_value(b, name: str) -> int:
    for line in (b.obj / 'gen' / 'ggame.inc').read_text().splitlines():
        f = line.split()
        if len(f) >= 3 and f[0] == name and f[1] == '=':
            return int(f[2].lstrip('$'), 16)
    raise TicRunError('no %s in ggame.inc' % name)


def timing(run_name: str, profile: str = 'f121', fill: int = 0xA5,
           frames: str = 'front', say=print) -> Dict[str, Any]:
    """The run on the gprof build under the cost model (profile), each
    tic's subsystems: a line a G_Ticker entry (the tic, then the frame
    the schedule puts after it, then the driver's flush and snapshot
    point), its phases' microseconds: the tic's (PHASE_NAMES, 18-30), the
    load's (31), the frame's (milestone 8's phases 0-17)."""
    from a2vm import costs
    import time
    ref = TC.load(run_name)
    G.make('gprof')
    b = G.load_build(G.GAME / 'gprof', 'gprof')
    last = ref['tics'][-1]['tic']
    img, case, up, banks = build_image(run_name, ref, b, fill, frames,
                                       last + 1, say)
    img.poke_label('dg_nosnap', b'\1')
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-tictime-', dir=str(BUILD)))
    t0 = time.time()
    try:
        (work / 'pcmap.txt').write_text(pcmap_text(b))
        lab = b.labels
        r = G.run(img, work, GL.MODES['LOCKSTEP'], banks=banks,
                  profile=profile, cycles=400_000_000_000,
                  timeout=max(1800.0, (last - ref['setups'][0]['tic']) /
                              TICS_A_SECOND * 300),
                  extra=['--boundary', '%X' % lab['drv_tic'],
                         '--cost-pcmap', str(work / 'pcmap.txt'),
                         '--cost-pcmap-when', str(PH_TIC)])
        ended = r.ended()
        mhz = costs.parameters(profile)['fabric_mhz']
        rows = []
        for line in (work / 'cost.json').read_text().splitlines():
            if not line.startswith('{"boundary"'):
                continue
            d = json.loads(line)
            rows.append([c / mhz for c in d['phases']])
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    start = ref['setups'][0]['tic']
    # row k: from the k-th drv_tic to the next: the tic of gametic
    # start + k - 1 (row 0: the driver's start to the first snapshot)
    tics = []
    for k, ph in enumerate(rows[1:], 0):
        g = start + k
        tic_us = sum(ph[19:31])
        tics.append({'tic': g, 'us': ph, 'tic_us': tic_us,
                     'frame_us': sum(ph[0:18]), 'load_us': ph[31]})
    return {'run': run_name, 'profile': profile, 'ended': ended,
            'seconds': round(time.time() - t0, 1), 'start': start,
            'level_tics': [t['tic'] for t in ref['tics']], 'tics': tics,
            'schedule': [g for g in ref['schedule'] if g > start]}


def timing_summary(t: Dict[str, Any]) -> Dict[str, Any]:
    """Each subsystem's time a level tic (ms: median, p99, worst), the
    tic's total, and each frame's tic phase (the tics since the frame
    before, the loads apart)."""
    level = set(t['level_tics'])
    rows = [x for x in t['tics'] if x['tic'] in level and not x['load_us']]

    def stats(vals):
        v = sorted(vals)
        if not v:
            return None
        return {'median': round(v[len(v) // 2] / 1000, 3),
                'p99': round(v[min(len(v) - 1, int(0.99 * len(v)))] / 1000,
                             3),
                'worst': round(v[-1] / 1000, 3)}
    out = {'tics': len(rows), 'tic': stats([x['tic_us'] for x in rows])}
    for ph, name in PHASE_NAMES.items():
        if ph == PH_LOAD:
            continue
        out[name] = stats([x['us'][ph] for x in rows])
    # the frames' tic phases: the tics between a frame and the one before
    by_tic = {x['tic']: x for x in t['tics']}
    frames = []
    prev = None
    for g in t['schedule']:
        if prev is not None and g > prev:
            span = [by_tic[k] for k in range(prev, g) if k in by_tic]
            if all(x['tic'] in level and not x['load_us'] for x in span):
                tic = sum(x['tic_us'] for x in span)
                ent = sum(x['us'][PH_EXIT] for x in span)
                pag = sum(x['us'][28] for x in span)
                frames.append({'gametic': g, 'tics': len(span),
                               'tic_ms': round(tic / 1000, 3),
                               'exit_ms': round(ent / 1000, 3),
                               'phase_ms': round((tic + ent) / 1000, 3),
                               'paging_ms': round(pag / 1000, 3)})
        prev = g
    out['frames'] = frames
    out['frame_tic_phase'] = stats([f['phase_ms'] * 1000 for f in frames])
    return out


# ---------------------------------------------------------------------------
# One planted bug an acceptance run (the owner's lean rule: show each run
# can fail): the parts' own plants, built into a scratch game image
# ---------------------------------------------------------------------------

def plants() -> Dict[str, Dict[str, Any]]:
    """name: the run, its frames, the tics to run, the bugs (src/native
    relative file, old, new) and where the plant comes from."""
    sys.path.insert(0, str(HERE / 'gparts'))
    import tic as TK
    import flowcheck as FC
    import mobjstate as MS
    return {
        'demo3-leveltime-first': {
            'run': 'demo3', 'frames': 'front', 'tics': 200,
            'bugs': TK.PLANTS['leveltime-first']['bugs'],
            'from': 'part tic (tic.py PLANTS)'},
        'tour-m-random-not-called': {
            'run': 'tour', 'frames': 'front', 'tics': None,
            'bugs': FC.PLANTS['m-random-not-called'][1],
            'from': 'part flow (flowcheck.py PLANTS)'},
        'demo2-angleturn-not-shifted': {
            'run': 'demo2', 'frames': 'front', 'tics': 200,
            'bugs': FC.PLANTS['angleturn-not-shifted'][1],
            'from': 'part flow (flowcheck.py PLANTS)'},
        # (chase's random-order, tried first, was not reached: no
        # zombieman fires at the player in G1)
        'G1-removal-at-once': {
            'run': 'G1', 'frames': 'front', 'tics': None,
            'bugs': MS.PLANTS['removal-at-once']['bugs'],
            'from': 'part mobjstate (mobjstate.py PLANTS)'},
        'demo3-full-strip-ignored': {
            'run': 'demo3', 'frames': 'full', 'tics': 400,
            'bugs': [('gdriver.s', """        bit dg_fr+2
        bpl :+
        lda #VIEW_STRIPTOP""", """        bit dg_fr+2
        bra :+                  ; (planted: the strip's rows ignored)
        lda #VIEW_STRIPTOP""")],
            'from': 'the driver\'s render input (gdriver.s)'},
    }


def run_plant(name: str, fill: int = 0xA5, jobs: int = 2,
              say=print) -> Dict[str, Any]:
    """A plant built in a scratch copy (grun.planted, target game), its
    run: caught when the run fails."""
    p = plants()[name]
    ref = TC.load(p['run'])
    tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-ticplant-', dir=str(BUILD)))
    try:
        obj = G.planted(tmp, p['bugs'], 'game')
        b = G.load_build(obj, 'game')
        r = run_fill(p['run'], ref, b, fill, p['tics'], p['frames'], jobs,
                     say)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    first = r.get('first_failures', [])[:2]
    full = r.get('full') or {}
    return {'plant': name, 'run': p['run'], 'frames': p['frames'],
            'from': p['from'], 'tics_compared': r.get('tics_compared'),
            'failures': r.get('failures'),
            'full_failures': full.get('failures'),
            'caught': not r.get('ok'), 'first': first,
            'full_first': (full.get('first_failures') or [])[:1]}


def machine_at(run_name: str, tic: int, fill: int = 0xA5,
               image: str = 'game', frames: str = 'front', say=print,
               events: Sequence[str] = ()):
    """The native machine at the G_Ticker entry of `tic` (the run to that
    tic): a SnapMachine, or None and how the run ended."""
    ref = TC.load(run_name)
    G.make(image)
    b = G.load_build(G.GAME / image, image)
    img, case, up, _ = build_image(run_name, ref, b, fill, frames, tic + 1,
                                   say)
    from native import gameroutine as GR
    banks = set()
    for m in range(1, 10):
        banks |= set(GR.manifest(m)[2])
    banks = sorted(banks | set(SNAP_BANKS_EXTRA))
    got: Dict[str, Any] = {}

    def on_tic(head, m):
        if not str(head.get('name', 'tic')).startswith('tic'):
            got.setdefault('other', []).append((head, m))
            return
        g = struct.unpack_from('<I', bytes(m.main[LL.G['G_GAMETIC']:
                                                  LL.G['G_GAMETIC'] + 4]))[0]
        if g == tic:
            got['m'] = m
        elif g == tic - 1:
            got['before'] = m
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-ticdiff-', dir=str(BUILD)))
    try:
        r = stream_run(img, work, banks, on_tic, tic - ref['setups'][0]['tic']
                       + 8, events=events)
        got['ended'] = r.ended()
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    got['ref'] = ref
    return got


def diff_at(run_name: str, tic: int, fill: int = 0xA5,
            image: str = 'game', frames: str = 'front', say=print,
            limit: int = 40) -> Dict[str, Any]:
    """The canonical diff at a tic (GAME.md 3.6's first differing tic,
    both states kept whole in KEEP): the run to that tic, its native
    state against the reference's (a capture of that tic's G_Ticker
    entry)."""
    got = machine_at(run_name, tic, fill, image, frames, say)
    ref = got['ref']
    if 'm' not in got:
        return {'tic': tic, 'error': 'no snapshot (the run ended %s)' %
                got['ended']}
    nat = native_state(got['m'])
    want = ref_state(run_name, tic, say)
    window = _in_window(ref.get('windows', []), tic)
    diff = gcanon.compare(want, nat, 'tic', window=window,
                          front=frames == 'front', limit=limit)
    KEEP.mkdir(parents=True, exist_ok=True)
    from bridge import canonical
    for name, st in (('native', nat), ('reference', want)):
        p = KEEP / ('%s-%d-%02x-%s.json' % (run_name, tic, fill, name))
        canonical.save(st, p)
    return {'tic': tic, 'diff': diff, 'kept': str(KEEP)}


# ---------------------------------------------------------------------------
# The report (GAME.md 5.3, lean): build/native/game/report.md from the
# final runs' JSON in build/native/game/acceptance/
# ---------------------------------------------------------------------------

ACCEPT = GL.GAME / 'acceptance'
REPORT_MD = GL.GAME / 'report.md'
FINAL_RUNS = (('1', 'demo3', 'front'), ('2', 'newgame', 'front'),
              ('2', 'tour', 'front'), ('3', 'demo1', 'front'),
              ('3', 'demo2', 'front'), ('4', 'G1', 'front'),
              ('4', 'G3', 'front'), ('4', 'G5', 'front'),
              ('5', 'demo3', 'full'))
TIMING_RUNS = ('demo3', 'demo1', 'demo2', 'G1', 'G3', 'G5', 'newgame',
               'tour')
PLANE_CAP = 768


def result_path(acc: str, run_name: str, frames: str) -> Path:
    return ACCEPT / ('A%s-%s-%s.json' % (acc, run_name, frames))


def timing_of(run_name: str, profile: str) -> Optional[Dict[str, Any]]:
    """A timing run's summary, made again from its per-tic rows."""
    p = ACCEPT / ('T-%s-%s.json' % (run_name, profile))
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    ref = TC.load(run_name)
    start = ref['setups'][0]['tic']
    t = {'tics': [{'tic': x['tic'], 'us': x['phases'],
                   'tic_us': x['tic_us'], 'load_us': x['load_us']}
                  for x in d['raw']],
         'level_tics': [x['tic'] for x in ref['tics']],
         'schedule': [g for g in ref['schedule'] if g > start]}
    return dict(timing_summary(t), ended=d.get('ended'),
                seconds=d.get('seconds'))


def render_ms(profile: str = 'f121') -> Dict[str, float]:
    """Milestone 8's measured render time of each demo3 frame (f121: the
    whole frame, frame8.py --timing, build/native/render/frame8-demo3.json)
    by frame name."""
    p = BUILD / 'native' / 'render' / 'frame8-demo3.json'
    out = {}
    for r in json.loads(p.read_text()):
        t = (r.get('timing') or {}).get(profile)
        if t:
            out[r['frame']] = t['total_ms']
    return out


def fps_rows(t: Dict[str, Any], ref: Dict[str, Any],
             profile: str = 'f121') -> Dict[str, Any]:
    """Each demo3 frame: its measured tic phase (the 4 tics since the
    frame before and the tic image's exit and entry) plus milestone 8's
    render time: the frame time and FPS; and with the tics a faster frame
    would run (35 x the frame time in seconds, rounded up, 1 to 4: the
    tic cost a tic the frame's mean), solved per frame."""
    import math
    rms = render_ms(profile)
    start = ref['setups'][0]['tic']
    sched = [g for g in ref['schedule'] if g > start]
    rows = []
    for f in t['frames']:
        i = sched.index(f['gametic'])
        name = 'demo3-%03d' % i
        if name not in rms:
            continue
        r = rms[name]
        per = f['tic_ms'] / max(1, f['tics'])
        ms4 = r + f['phase_ms']
        n = 4
        for _ in range(8):
            ms = r + f['exit_ms'] + n * per
            m = min(4, max(1, int(math.ceil(35.0 * ms / 1000.0))))
            if m == n:
                break
            n = m
        rows.append({'frame': name, 'render_ms': r,
                     'tic_phase_ms': f['phase_ms'],
                     'nopaging_ms': ms4 - f.get('paging_ms', 0.0),
                     'ms': ms4,
                     'fps': 1000.0 / ms4, 'tics_solved': n,
                     'ms_solved': ms, 'fps_solved': 1000.0 / ms})
    return {'rows': rows}


def _md_stats(st: Optional[Dict[str, Any]]) -> str:
    if not st:
        return '-'
    return '%.2f / %.2f / %.2f' % (st['median'], st['p99'], st['worst'])


def report_md() -> str:
    lines = ['# Milestone 10: the acceptance report', '',
             'Made by `python3 tools/native/ticrun.py --report-md` from the '
             'final runs in `build/native/game/acceptance/` (docs/GAME.md '
             '5.3, the lean rules of 2026-10-02: each run once, from the '
             '`$A5` machine). Reference: `ref816` (`ticcap.py`); native: '
             'the `game` build (every part, `LOCKSTEP`, `VCWRAP_UPSTREAM`, '
             '`TESTBUILD`, `TICLEVEL`) on a2vm.', '',
             '## 1. Acceptance', '',
             '| # | Run | Frames | Tics compared | Failures | Same-pair '
             'hits (ref / native) | Setups | Zone mobjs (most) | Highest '
             'slot (of %d) | T3 | T8 | T7 | Result |' % PLANE_CAP,
             '| --: | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | '
             '--- | --- | --- | --- |']
    gates = {'zmobjs': 0, 'secnode': 0, 'blocklink': 0, 'hw': 0}
    for acc, name, frames in FINAL_RUNS:
        p = result_path(acc, name, frames)
        if not p.exists():
            lines.append('| %s | %s | %s | - | - | - | - | - | - | - | - | '
                         '- | not run |' % (acc, name, frames))
            continue
        d = json.loads(p.read_text())
        f = d['fills']['a5']
        ref = TC.load(name)
        hits = f['same_pair_hits']
        t7 = (f.get('full') or {}).get('T7', [])
        ok = 'equal' if f.get('ok') else '**fails**'
        gates['zmobjs'] = max(gates['zmobjs'], f.get('zmobjs_max', 0))
        gates['hw'] = max(gates['hw'], f.get('mohwm_max', 0))
        for k in ('secnode', 'blocklink'):
            gates[k] += (f.get('tics_changed') or {}).get(k, 0)
        lines.append('| %s | %s | %s | %d | %d | %d / %d | %d | %d | %d | '
                     '%s | %s | %s | %s |' % (
                         acc, name, frames.upper(), f['tics_compared'],
                         f['failures'], hits['reference'], hits['native'],
                         len(ref['setups']), f.get('zmobjs_max', 0),
                         f.get('mohwm_max', 0),
                         len(ref.get('windows', [])) or 'none',
                         f.get('t8', 'none'),
                         ', '.join(t7) or 'none', ok))
    full = result_path('5', 'demo3', 'full')
    if full.exists():
        fu = json.loads(full.read_text())['fills']['a5'].get('full') or {}
        lines += ['', 'Acceptance 5 (FULL frames, every %d-th compared): '
                  '%d of %d frames compared, %d failures, %d records, the '
                  'message strip\'s rows 0-9 excluded in %d frames (the '
                  'HUD\'s text, milestone 11\'s), T7 frames: %s.' % (
                      FULL_EVERY, fu.get('frames_compared', 0),
                      fu.get('frames_scheduled', 0), fu.get('failures', 0),
                      fu.get('records', 0), len(fu.get('strip_frames', [])),
                      ', '.join(fu.get('T7', [])) or 'none')]
    ap = GL.GAME / 'path' / 'acc6-final-run.json'
    ag = GL.GAME / 'path' / 'acc6-final.json'
    if ap.exists():
        a6 = json.loads(ap.read_text())
        maps = json.loads(ag.read_text()) if ag.exists() else []
        lines += ['', 'Acceptance 6 (`P_PathTraverse` by `--call`, '
                  '`path.py --acceptance-final`, then `--run-final`): %d '
                  'traces of more than 64 intercepts (%s), each never '
                  'stopping and stopping at k = 1, 8, 32, 64, 65: %d runs, '
                  '%d failures, %d undecodable, %d intercepts delivered '
                  'in the never-stopping runs.' % (
                      a6['traces'], ', '.join('E1M%d %d of %d tried' % (
                          m['map'], m['kept'], m['tried']) for m in maps),
                      a6['runs'], a6['failures'], a6['undecodable'],
                      a6['intercepts'])]
    pl = ACCEPT / 'plants.json'
    if pl.exists():
        lines += ['', '**One planted bug a run** (each built into a scratch '
                  'game image and the run made on it):', '',
                  '| Plant | From | Run | Caught | First difference |',
                  '| --- | --- | --- | --- | --- |']
        for o in json.loads(pl.read_text()):
            first = o['first'][:1] or o.get('full_first') or []
            lines.append('| `%s` | %s | %s %s | %s | %s |' % (
                o['plant'], o['from'], o['run'], o['frames'].upper(),
                'yes' if o['caught'] else '**no**',
                json.dumps(first)[:160].replace('|', '/')))
        pp = GL.GAME / 'path' / 'acc6-final-plant.json'
        if pp.exists():
            o = json.loads(pp.read_text())
            lines.append('| `%s` | %s | acceptance 6, every 7th trace '
                         '(%d runs) | %s (%d failed) | %s |' % (
                             o['plant'], o['from'], o['runs'],
                             'yes' if o['caught'] else '**no**',
                             o['failed'],
                             json.dumps((o['first'] or [])[:1])[:160]))
    lines += ['', '## 2. The gates of milestone 9', '',
              '| Gate | Evidence |', '| --- | --- |',
              '| One `validcount` | Every tic\'s `validcount` and every '
              'line and sector stamp equal in every run above, the native '
              'front end raising the joined count (`rframe.s` `gv_inc`) |',
              '| A zone mobj created, `LS_ZONE`, no slot twice | Zone mobjs '
              'in G1 and G3 (at most %d at a tic), compared every tic; the '
              'port reader refuses two objects in one slot; the highest '
              'mobj slot of any run %d, of the planes\' %d |' % (
                  gates['zmobjs'], gates['hw'], PLANE_CAP),
              '| The block walk\'s order on every move | %d tics with the '
              'sector nodes changed and %d with the block lists changed, '
              'each compared as a sequence |' % (gates['secnode'],
                                                 gates['blocklink'])]
    s4 = ACCEPT / 's4.json'
    if s4.exists():
        d = json.loads(s4.read_text())
        lines.append('| Bank `$21`\'s tables (S4) | `ticcap.py --tables`: '
                     '%d setup dumps, `LNSEC`/`SS_ROW` against `LNSECF`, '
                     '`LNSECB`, `RJROW` and the re-keying: %d failures |' % (
                         len(d['setups']), len(d['failures'])))
    lines += ['', '## 3. Timing (a2vm cost model, the `gprof` build)', '',
              'Each level tic\'s time by subsystem: the PC map of the build '
              '(`a2vm --cost-pcmap`: the phase of the code that runs, the '
              'innermost by construction), ms, median / p99 / worst; FRONT '
              'frames between (their own phases apart), no snapshot a '
              'tic. The tics of a load are left out.', '']
    names = [PHASE_NAMES[k] for k in sorted(PHASE_NAMES) if k not in
             (PH_EXIT, PH_LOAD)]
    lines += ['| Run | Profile | Tics | Tic | ' + ' | '.join(names) + ' |',
              '| --- | --- | ---: | --- | ' + ' | '.join('---' for _ in names)
              + ' |']
    for run_name in TIMING_RUNS:
        for prof in ('f121', 'fastpath'):
            t = timing_of(run_name, prof)
            if t is None:
                continue
            lines.append('| %s | %s | %d | %s | %s |' % (
                run_name, prof, t['tics'], _md_stats(t['tic']),
                ' | '.join(_md_stats(t[n]) for n in names)))
    for prof in ('f121', 'fastpath'):
        t = timing_of('demo3', prof)
        if t is None:
            continue
        fr = fps_rows(t, TC.load('demo3'), prof)['rows']
        if fr:
            npg = sorted(r['nopaging_ms'] for r in fr)
            ms = sorted(r['ms'] for r in fr)
            msn = sorted(r['ms_solved'] for r in fr)
            ph = sorted(r['tic_phase_ms'] for r in fr)
            under = [r['frame'] for r in fr if r['fps'] < 6]
            under_s = [r['frame'] for r in fr if r['fps_solved'] < 6]
            lines += ['', '**demo3\'s frames** (%s; the render time is '
                      'milestone 8\'s measured one, `report8.md`): %d '
                      'frames; the tic phase (4 tics, the exit and entry) '
                      'median %.1f ms, worst %.1f; the frame median %.1f ms '
                      '(%.2f FPS), worst %.1f (%.2f FPS, %s); %d frames '
                      'under 6 FPS. With the tics a faster frame would run, '
                      'solved per frame: median %.1f ms (%.2f FPS), worst '
                      '%.1f (%.2f FPS), %d under 6 FPS. Without the group '
                      'loads (phase 28), for the owner: median %.1f ms '
                      '(%.2f FPS), worst %.1f (%.2f FPS).' % (
                          prof, len(fr), ph[len(ph) // 2], ph[-1],
                          ms[len(ms) // 2], 1000 / ms[len(ms) // 2], ms[-1],
                          1000 / ms[-1], max(fr, key=lambda r: r['ms'])[
                              'frame'], len(under), msn[len(msn) // 2],
                          1000 / msn[len(msn) // 2], msn[-1], 1000 / msn[-1],
                          len(under_s), npg[len(npg) // 2],
                          1000 / npg[len(npg) // 2], npg[-1],
                          1000 / npg[-1])]
    pg = ACCEPT / 'paging.json'
    if pg.exists():
        d = json.loads(pg.read_text())
        lines += ['', '**The group loads** (phase 28; demo3, the whole run '
                  'on the `game` build, every write of a slot\'s group '
                  'number logged): %.1f loads a tic. The pairs of one slot '
                  'that alternate most:' % d['loads_a_tic'], '',
                  '| Slot | Groups | Alternations a tic | Their routines '
                  '(the first of each) |', '| ---: | --- | ---: | --- |']
        names = {g['group']: g['routines'] for g in d['groups']}
        seen = set()
        for p in d['pairs']:
            key = (p['slot'], min(p['from'], p['to']), max(p['from'],
                                                           p['to']))
            if key in seen:
                continue
            seen.add(key)
            lines.append('| %d | %d, %d | %.1f | %s; %s |' % (
                p['slot'], p['from'], p['to'], 2 * p['a_tic'],
                ', '.join(names.get(p['from'], [])[:5]) or '?',
                ', '.join(names.get(p['to'], [])[:5]) or '?'))
    sz = ACCEPT / 'sizes.txt'
    if sz.exists():
        lines += ['', '## 4. Sizes', '', '```', sz.read_text().rstrip(),
                  '```']
    lines += ['', '## 5. Left out by the lean rules', '',
              '- the `$5A` fill (one poisoned machine, `$A5`);',
              '- the tour by map in 9 runs;',
              '- G2, G4, G6-G10 (3 generated streams of 10);',
              '- the sound events per tic against `ref816`\'s call log;',
              '- planted-bug campaigns beyond one a run.', '']
    return '\n'.join(lines) + '\n'


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--run')
    parser.add_argument('--fills', default='a5')
    parser.add_argument('--image', default='game')
    parser.add_argument('--tics', type=int)
    parser.add_argument('--frames', default='front',
                        choices=('none', 'front', 'full'))
    parser.add_argument('--jobs', type=int, default=DECODE_JOBS)
    parser.add_argument('--json', type=Path)
    parser.add_argument('--diff-at', type=int)
    parser.add_argument('--timing', help='a profile: f121 or fastpath')
    parser.add_argument('--plant', help='a planted bug (plants()), or all')
    parser.add_argument('--report-md', action='store_true')
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args(argv)
    if args.report_md:
        REPORT_MD.write_text(report_md())
        print('%s written' % REPORT_MD)
        return 0
    if args.plant:
        names = list(plants()) if args.plant == 'all' else [args.plant]
        out = [run_plant(n, jobs=args.jobs) for n in names]
        for o in out:
            print(json.dumps(o)[:600])
        if args.json:
            args.json.write_text(json.dumps(out, indent=1) + '\n')
        return 0 if all(o['caught'] for o in out) else 1
    if args.timing:
        t = timing(args.run, args.timing, frames=args.frames)
        summ = timing_summary(t)
        out = {'run': args.run, 'profile': args.timing, 'ended': t['ended'],
               'seconds': t['seconds'], 'summary': summ}
        print(json.dumps({k: v for k, v in out.items()}, indent=1)[:4000])
        if args.json:
            args.json.write_text(json.dumps(dict(out, raw=[
                {'tic': x['tic'], 'tic_us': round(x['tic_us'], 1),
                 'frame_us': round(x['frame_us'], 1),
                 'load_us': round(x['load_us'], 1),
                 'phases': [round(v, 1) for v in x['us']]}
                for x in t['tics']])) + '\n')
        return 0
    if args.diff_at is not None:
        r = diff_at(args.run, args.diff_at, int(args.fills.split(',')[0], 16),
                    args.image, args.frames)
        for line in r.get('diff', []):
            print(line)
        print(json.dumps({k: v for k, v in r.items() if k != 'diff'}))
        return 1 if r.get('diff') or r.get('error') else 0
    if args.selftest:
        r = selftest()
        print('selftest: %d tics streamed and digested; %s' % (
            r['tics'], r['problems'] or 'ok'))
        return 1 if r['problems'] else 0
    if not args.run:
        parser.error('--run RUN, --plant, --report-md or --selftest')
    r = run(args.run, [int(x, 16) for x in args.fills.split(',')],
            args.image, args.tics, args.frames, args.jobs)
    print(json.dumps(r, indent=1))
    if args.json:
        args.json.write_text(json.dumps(r, indent=1) + '\n')
    return 0 if r.get('ok') else 1


if __name__ == '__main__':
    sys.exit(main())
