#!/usr/bin/env python3
"""The whole frame of the native renderer on a2vm against ref816
(milestone 8, stage C: docs/RENDER-MASKED.md 2.3, 2.4, 4.2-4.5, 5.3;
acceptance 1 and the timing report).

Usage:  python3 tools/native/frame8.py [--frames NAME,...] [--sets ...]
                [--jobs 2] [--fills a5,5a] [--timing] [--report FILE]
                [--poisoned] [--json FILE] [--keep DIR] [--no-build]
                [--report-from JSON]

For each captured frame (tools/native/rendercap.py; milestone 7's 188 and
the synthetic ones by default, --sets demo3 for every frame of demo3),
twice (every byte the frame does not define $A5, then $5A): the level
(levelconv.py: its banks, the patch store, the weapon profiles, FUZZDARK),
the tables, the code of the build ftest (the front end, the masked image
with the weapon and the bucket pass's BKFAR and BKFAR2, the bucket pass's
card part, milestone 5's replay: its row blocks, draw pass, tables and
drawers), the frame's state (framestate.py) and the input screen (below)
go into an a2vm image; the driver's drv_fframe runs the whole frame of
RENDER-MASKED.md 3.2, phases 1-13, with the mouse card's VBL interrupt
on: the front end's window, nr_frame (the weapon's clip pass in it), the
masked phase's window, nm_masked (the weapon at its end), nm_bkload, and
nb_frame (the bucket pass, then each batch's fuzz marks and replay). The
frame passes when, in both runs:

  - the run ends at the driver's halt, at least one interrupt taken;
  - the weapon's clip pass (a snapshot at nr_wskip's entry): FLOORCLIP,
    FRVIS (the native 12 bytes) and MM_WPOK equal P1's (weaponClipSame +
    3); the walk's entry and the front end's outputs at the walk's end
    equal P0b's and P3's (render_check's frame mode); the vissprites and
    the sort P3's and P3s's; the records, ranges, spans, page model, clip
    log to the weapon's draw P3w's (stages A and B);
  - at the masked phase's end (drv_mend): every record of the frame by
    column in the order made (upstream's early flushes, before and in the
    masked phase, then its lists at R_DrawLists, P4), the covered ranges
    and their records (a frame without an early flush), the spans, the
    page model (UPOFS, XPUSED against COLW, XPNEXT; the flushes), FZ_POS,
    floorclip and ceilingclip, the weapon skip (FR_SKIP, W_WSK, WPREV,
    WCLIP), FR_VIS and MM_WPOK, and the clip log against the call log
    (every R_DrawVisSprite call but the clip pass's, the weapon's draw
    included) equal P4's;
  - the bucket pass (a snapshot at each nat_replay call): each batch's
    records in W, its columns' starts in COLLO/COLHI, each covered
    column's record as its W address, the batch list, equal milestone
    5's loader (loader.mark_fuzz and its packing) on the native staging;
  - all of aux 0 $2000-$9FFF after the last batch's replay equals the
    screen at R_DrawLists' return (P5), byte for byte; the SHR writes
    equal the screen stores of the model (loader.screen_stores) and no
    other video page is written (MEMORY_MAP.md rule 3);
  - the write log (every storage but the stack page, the soft switches)
    holds no write outside each phase's allowed set, by the writing PC:
    the front end's (render_check.stray, milestone 7's), the masked
    phase's (rlayout.allowed_writes_masked), nm_bkload's, the bucket
    pass's (rlayout.allowed_writes_bucket), the replay's (MEMORY_MAP.md
    rule 6: its zero page, page 1, the covered ranges it clears, its
    scratch, the texel stage, the fuzz queue, the view's rows, its row
    block patches), the driver's;
  - the stack stays within the render budget with the IRQ's allowance.

A frame whose RULES is not 0 (a column seen from behind: NATIVE.md 15.1
row 13) is not compared: it is listed as a known divergence, never as
equal. A run that stops (BRK) after the masked phase still gets the
bucket check, on the native staging at its end against the batches
handed to the replay before the stop, so a bucket pass that broke them
is named beside the stop. Every run prints RENDER-MASKED.md 6.1 item 1's
margin: the staging's capacity against the largest staging of the
captured frames (at least rlayout.STAGING_MARGIN times; the synthetic
extremes must fit), and fails under it.

The input screen (RENDER-MASKED.md 2.3 item 4): P4's screen, where the
first early flush's screen (the first P2) differs from the screen at
stripEarly (PS) the flush's value (those bytes only a flush wrote); a
byte a flush wrote that also changed between PS and P4 fails the frame
(named). A frame without a flush takes P4 whole.

--poisoned (4.2): on the m5 frames and every tenth demo3 frame, a third
run from a screen whose pixels are milestone 5's pattern, against
upstream's R_DrawLists run by ref816 --call with the same screen (and
buffer): an m5 frame from its own capture (build/captures/NAME, every
byte its R_DrawLists read), a demo3 frame from the P4 state (the base
image build/native/base-entry.img, a demo3 entry, the frame's P4 ranges,
its colormaps from P0 and the level's fuzz table over it); the same call
on the captured screen must give P5 first, which checks the state.

--timing runs the profiling build fprof under a2vm's cost model, f121 and
fastpath (derived from the RTL, not measured on the card): each phase of
RENDER-MASKED.md 4.4 (1 the front end's window, 2 setup, 17 the clip
pass, 3 the walk, 9 wall setup, 10 the seg loops, 13 the masked window,
14 the drawseg copy, 11 the projection, 15 the sort, 4 the sprites and
masked walls, 16 the weapon, 18 the bucket pass, 12 the replay), ms,
65C02 cycles and soft-switch accesses; --report writes the timing report
(build/native/render/report8.md): per set and phase, the heaviest
frames, the whole frame with NATIVE.md 6's tics against NATIVE.md 1.1
and 6 FPS, and rdisk.py --check's FPS by VBL count when its results
exist; --report-from JSON writes it again from a --timing run's --json.

--levels loaded (milestone 9, stage B: docs/LEVELS.md 5.4, acceptance
2): each frame's level is not levelconv.py's conversion of its level
source but the level the native loader made from the store
(tools/native/level_check.py --load keeps each map's last load,
build/native/levels/loaded/e1mN.img), read back into the layout of the
source's conversion (lrun.harness_level: every byte from the loaded
machine; build/native/levels/loaded/src/), then the frame runs as
always (its state injected from P0, so the level's dynamic fields are
the frame's). A frame whose level source is synthetic (synth-*: a level
made with pokes, not the WAD's) is excluded by name.

Every run is bounded (cycles, time, file sizes), under nice, at most two
at a time, in a directory under build/ deleted after it.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from a2vm import costs  # noqa: E402
from bridge import linkmap as blink  # noqa: E402
from native import bucketcheck as BC, framestate as FS, layout as L5, \
    levelconv, loader, rcanon, render_check as RC, rlayout as R  # noqa: E402
from ref816 import bounded  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
RENDER = BUILD / 'native' / 'render'
REPORT = RENDER / 'report8.md'
CAPTURES = BUILD / 'captures'   # milestone 5's frames (ref816/capture.py)
SCREEN, SCREEN_SIZE = 0x2000, 0x8000
E1_SCREEN = 0xE12000
PIXELS = L5.PIXELS
CYCLE_LIMIT = 900_000_000
RUN_TIMEOUT = 600.0
KNOWN = RC.KNOWN_DIVERGENCE

SNAP8 = RC.MASK_SNAP + ',main:2000-BFFF,aux0:2000-9FFF,aux%d:8000-BFFF' \
    % R.RECW
PHASES8 = {1: 'window', 2: 'setup', 17: 'clip', 3: 'walk', 9: 'walls',
           10: 'segs', 13: 'mwindow', 14: 'dscopy', 11: 'project',
           15: 'sort', 4: 'sprites', 16: 'weapon', 18: 'bucket',
           12: 'replay', 0: 'driver'}


class F8Error(Exception):
    pass


# ---------------------------------------------------------------------------
# The case
# ---------------------------------------------------------------------------

class F8Case(NamedTuple):
    mc: RC.MaskCase
    screen: bytes               # the input screen (aux 0 $2000-$9FFF)
    composed: Dict[str, Any]    # how it was composed
    truth: bytes                # the screen at R_DrawLists' return (P5)
    final: Dict[str, Any]       # rcanon.final_truth (P4)
    clip: Dict[str, Any]        # rcanon.clip_truth (P1)
    fuzzdark: bytes
    index: Dict[int, int]


def compose_screen(frame) -> Tuple[bytes, Dict[str, Any]]:
    """The input screen of RENDER-MASKED.md 2.3 item 4."""
    p4 = frame.dump('p4').read(E1_SCREEN, SCREEN_SIZE)
    names = ['p2-%d' % k for k in range(frame.meta.get('flushes', 0))] + \
        ['p2m-%d' % k for k in range(frame.meta.get('mflushes', 0))]
    if not names:
        return p4, {'flushes': 0}
    first = min((frame.dump(n) for n in names),
                key=lambda d: d.header['cycles'])
    p2 = first.read(E1_SCREEN, SCREEN_SIZE)
    ps = frame.dump('ps').read(E1_SCREEN, SCREEN_SIZE)
    out = bytearray(p4)
    taken = []
    for i in range(SCREEN_SIZE):
        if p2[i] != ps[i]:
            if ps[i] != p4[i]:
                raise F8Error('%s: screen $%04X: a flush wrote it and the '
                              'render\'s end changed it after '
                              '(RENDER-MASKED.md 2.3 item 4)' % (
                                  frame.name, SCREEN + i))
            out[i] = p2[i]
            taken.append(i)
    return bytes(out), {'flushes': len(names), 'flushed_bytes': len(taken)}


def prepare8(directory: Path, sym: blink.Symbols) -> F8Case:
    mc = RC.prepare_masked(directory, sym)
    frame = mc.full.case.frame
    level_dir = mc.full.case.level_dir
    index = FS.store_index(mc.full.case.level)
    screen, composed = compose_screen(frame)
    truth = frame.dump('p5').read(E1_SCREEN, SCREEN_SIZE)
    fuzz = (level_dir / 'fuzzdark.bin').read_bytes()
    if len(fuzz) != 256:
        raise F8Error('%s: no fuzzdark.bin: convert the level again'
                      % level_dir)
    return F8Case(mc, screen, composed, truth,
                  rcanon.final_truth(frame, sym, index),
                  rcanon.clip_truth(frame, sym, index), fuzz, index)


def image_records(case: F8Case, screen: Optional[bytes] = None
                  ) -> List[Tuple[int, int, int, bytes]]:
    """The frame's records (the level, the state, the masked image's
    tables, FUZZDARK, the input screen), W's tables in the window."""
    recs = RC.to_window(case.mc.full.case.records)
    recs.append((1, 0, L5.FUZZDARK, case.fuzzdark))
    recs.append((1, 0, SCREEN, screen if screen is not None else
                 case.screen))
    return recs


# ---------------------------------------------------------------------------
# A run
# ---------------------------------------------------------------------------

def events8(b: RC.Build) -> List[str]:
    lab = b.labels
    return ['pc %X snapshot clip' % lab['nr_wskip'],
            'pc %X snapshot bsp' % lab['nr_bsp'],
            'pc %X snapshot walk' % lab['drv_fload'],
            'pc %X snapshot psp' % lab['m_hook'],
            'pc %X snapshot mend' % lab['drv_mend'],
            'pc %X@* snapshot batch' % lab['nat_replay'],
            'pc %X snapshot end' % lab['drv_ret'],
            'pc %X snapshot crash' % lab['drv_crash']]


def code_ranges8(b: RC.Build) -> List[Tuple[int, int]]:
    return RC.code_ranges(b) + [b.segments[s] for s in (
        'BKFAR', 'BKFAR2', 'BKNEAR', 'RCODE', 'RHOT', 'TEXBLK', 'FILLE',
        'FILLO') if s in b.segments]


def boundary(timed, b: RC.Build, label: str, value: int) -> int:
    """The cycle the driver writes the cost phase `value` at or after
    `label` (its phase marks separate the phases)."""
    lo, hi = b.segments['DRIVER']
    for cycles, w in timed:
        if w.storage == 'main' and w.offset == R.PHASE and \
                lo <= w.pc <= hi and w.pc >= b.labels[label]:
            return cycles
    raise F8Error('no phase mark at %s in the write log' % label)


def stray_after(writes, b: RC.Build, release: bool = False) -> List[str]:
    """The writes after the masked phase: nm_bkload's, the bucket pass's,
    the replay's, the driver's; each by its allowed set. BKFAR2 runs at
    main $0200-$02FF, where the replay's aux-0 drawers run too: a PC there
    takes both sets. The replay's per-row copy loop runs from page 1.
    release: a game build (-D RELEASE), whose replay may also write
    COLLO/COLHI (a column cut at its stage, RENDER-MASKED.md 6.1)."""
    seg = b.segments
    bkload = [seg['MASKW']]
    bucket = [seg[s] for s in ('BKFAR', 'BKNEAR') if s in seg]
    shared = [seg['BKFAR2']]
    # (the replay's per-row copy loop runs from page 1, $0190-$01B4)
    replay = [seg[s] for s in ('RCODE', 'RHOT', 'TEXBLK', 'FILLE',
                               'FILLO')] + [(0x0100, 0x01B4)]
    drv = [seg['DRIVER'], seg['DESC']]
    sets = {
        'bkload': [(s, bk, lo, hi) for s, bk, lo, hi, _ in
                   R.allowed_writes_bkload()],
        'bucket': [(s, bk, lo, hi) for s, bk, lo, hi, _ in
                   R.allowed_writes_bucket()],
        'replay': replay_allowed() + ([('main', 0, L5.COLLO,
                                        L5.COLHI + 161)] if release else []),
        'driver': [('main', 0, 0xD8, 0x100), ('main', 0, R.PHASE, R.PHASE + 1),
                   ('lc', 0, 0xFFFE, 0x10000)],
    }
    sets['shared'] = sets['bucket'] + sets['replay']

    def inside(w, allowed) -> bool:
        return any(s == w.storage and (s != 'aux' or bk == w.bank) and
                   lo <= w.offset < hi for s, bk, lo, hi in allowed)
    out = []
    for w in writes:
        which = None
        for name, ranges in (('bkload', bkload), ('bucket', bucket),
                             ('shared', shared), ('replay', replay),
                             ('driver', drv)):
            if any(lo <= w.pc <= hi for lo, hi in ranges):
                which = name
                break
        if w.storage == 'io':
            ok = which in ('bucket', 'shared', 'replay') and \
                w.address in RC.IO_RENDER or \
                which == 'driver' and w.address in RC.IO_DRIVER
        else:
            ok = which is not None and inside(w, sets[which])
        if not ok:
            out.append('pc $%04X wrote %s %d $%04X' % (w.pc, w.storage,
                                                        w.bank, w.offset))
    return out


def replay_allowed() -> List[Tuple[str, int, int, int]]:
    """Milestone 5's replay (MEMORY_MAP.md rule 6, src/native/README.md
    "Memory"): its zero page, page 1's descriptors and copy loop, the
    covered ranges it clears, its scratch, the texel stage, the fuzz
    queue, the view's rows; its row-block patches in card bank 2 (restored
    before each record ends)."""
    return [('main', 0, 0x48, 0x70), ('main', 0, 0x0100, 0x01B5),
            ('main', 0, L5.CVFIRST, L5.CVRECLO),
            ('main', 0, L5.SCRATCH, L5.SCRATCH_END),
            ('main', 0, L5.STAGE, L5.STAGE_END),
            ('aux', 0, L5.FUZZQ, 0x0400),
            ('aux', 0, SCREEN, SCREEN + L5.VIEW_ROWS * 160),
            ('lc', 0, 0xD000, 0xDE00)]


def check8(case: F8Case, b: RC.Build, fill: int, base: Sequence,
           keep: Optional[Path] = None, screen: Optional[bytes] = None,
           truth: Optional[bytes] = None,
           release: bool = False) -> Dict[str, Any]:
    """One run of the whole frame (the module docstring). release: b is
    a game build (-D RELEASE): its replay's cut may write COLLO/COLHI."""
    fc = case.mc.full
    name = fc.case.frame.name
    work = Path(tempfile.mkdtemp(prefix='tmp-m8-frame-', dir=str(BUILD)))
    try:
        lab = b.labels
        ranges = ','.join('%X-%X' % r for r in code_ranges8(b))
        extra = ['--speed', '1', '--snapshot-ranges', SNAP8,
                 '--irq-bounds', RC.IRQ_BOUNDS, '--lowest-s-in', ranges,
                 '--write-log', RC.WRITE_LOG, '--write-log-file',
                 str(work / 'writes.log'), '--write-log-limit',
                 str(RC.WRITE_LOG_LIMIT), '--every-limit', str(R.MAXB + 2)]
        state = RC.a2vm_run(b, list(base) + image_records(case, screen),
                            work, events8(b), extra, start='drv_fframe',
                            cycles=CYCLE_LIMIT, timeout=RUN_TIMEOUT)
        out: Dict[str, Any] = {'frame': name, 'fill': fill, 'problems': []}
        if state.get('pc') == lab['drv_crash']:
            try:
                status = RC.snapshot(work, 'crash').main(R.FRAME['STATUS'],
                                                         1)[0]
            except RC.CheckError:
                status = None
            out['problems'].append('the frame stopped (BRK), status %s: %s'
                                   % (status, RC.STATUS_NAMES.get(status,
                                                                  '?')))
            out['problems'] += crash_bucket(work)
            return out
        if state.get('end') != 'stop-pc' or state.get('pc') != \
                lab['drv_halt']:
            out['problems'].append('the run ended with %s at $%04X' % (
                state.get('end'), state.get('pc', -1)))
            return out
        snaps = {n: RC.snapshot(work, n) for n in
                 ('clip', 'bsp', 'walk', 'psp', 'mend', 'end')}
        batches = one_a_call(sorted(work.glob('batch-*.img')))
        rules = snaps['walk'].main(R.FRAME['RULES'], 1)[0] | \
            snaps['end'].main(R.FRAME['RULES'], 1)[0]
        out['rules'] = rules
        if rules:
            out['known'] = 'rules %d: %s' % (rules, KNOWN)
            return out
        out['problems'] += compare(case, snaps, batches, out)
        # the SHR (P5), the model's screen stores, other video pages
        got = snaps['end'].aux(0, SCREEN, SCREEN_SIZE)
        want = truth if truth is not None else case.truth
        diff = [i for i in range(SCREEN_SIZE) if got[i] != want[i]]
        out['differing'] = len(diff)
        out['screen_crc'] = '%08X' % (zlib.crc32(got) & 0xFFFFFFFF)
        if diff:
            i = diff[0]
            out['problems'].append(
                'the screen: %d bytes differ (first $%04X row %d col %d: '
                'native $%02X, reference $%02X)' % (
                    len(diff), SCREEN + i, i // 160, i % 160, got[i],
                    want[i]))
        out['shr_writes'] = state.get('shr_writes')
        other = state.get('video_writes', 0) - state.get('shr_writes', 0)
        if other:
            out['problems'].append('%d video writes outside the SHR' % other)
        if 'stores' in out and out['shr_writes'] != out['stores']:
            out['problems'].append('%s SHR writes, the model %d' % (
                out['shr_writes'], out['stores']))
        irqs = int.from_bytes(snaps['end'].main(0xD8, 2), 'little')
        if irqs == 0:
            out['problems'].append('no interrupt was taken')
        # the write log, by phase
        timed = RC.read_writes_timed(work / 'writes.log')
        edge1 = boundary(timed, b, 'drv_fload', 26)
        edge2 = boundary(timed, b, 'drv_mend', 36)
        front = [w for c, w in timed if c < edge1]
        masked = [w for c, w in timed if edge1 <= c < edge2]
        after = [w for c, w in timed if c >= edge2]
        strays = RC.stray(front, b, fc.case.level, stage_b=True) + \
            RC.stray_masked(masked, b) + stray_after(after, b, release)
        if strays:
            out['problems'].append('%d stray writes: %s' % (
                len(strays), '; '.join(strays[:5])))
        low = None
        for r in state.get('lowest_s', {}).get('ranges', []):
            if r.get('s') is not None:
                low = r['s'] if low is None else min(low, r['s'])
        out['stack_bytes'] = None if low is None else RC.DRV_STACK - low
        out['problems'] += RC.stack_problem(out['stack_bytes'])
        out.update({'irqs': irqs, 'writes': len(timed),
                    'cycles': state.get('cycles'),
                    'flushes': case.composed['flushes']})
        return out
    finally:
        if keep is not None:
            shutil.copytree(str(work), str(keep), dirs_exist_ok=True)
        shutil.rmtree(str(work), ignore_errors=True)


BK_B = 0x33                     # bucket.s: the batch being replayed


def crash_bucket(work: Path) -> List[str]:
    """After a stop (BRK) past the masked phase's end: the bucket check
    on the native staging (the snapshot mend) against the batches the
    pass handed the replay before the stop, so a bucket pass that broke
    the batches is named, not only the replay's stop it caused."""
    if not (work / 'mend.img').exists():
        return []
    try:
        exp = BC.expected(native_stream(RC.snapshot(work, 'mend')))
    except (BC.BucketError, rcanon.CanonError) as e:
        return ['the bucket check: %s' % e]
    batches = one_a_call(sorted(work.glob('batch-*.img')))
    return ['the bucket check (before the stop): ' + p for p in
            BC.compare_batches(batches, exp, stopped=True)]


def one_a_call(paths: List[Path]) -> List[Path]:
    """The snapshots at nat_replay, one a call: an interrupt taken at its
    first instruction returns there, and a2vm's every-visit event fires
    again (the same batch, BK_B)."""
    out, last = [], None
    for p in paths:
        s = rcanon.Snapshot(levelconv.Image.parse(p.read_bytes()))
        b = s.main(BK_B, 1)[0]
        if b != last:
            out.append(p)
        last = b
    return out


def compare(case: F8Case, snaps: Dict[str, rcanon.Snapshot],
            batches: List[Path], out: Dict[str, Any]) -> List[str]:
    """Every comparison but the screen's: the phases' outputs and the
    bucket pass."""
    mc = case.mc
    fc = mc.full
    nsec = fc.case.level['counts']['sectors']
    problems: List[str] = []
    # the weapon's clip pass (P1)
    nclip = rcanon.clip_native(snaps['clip'])
    for key in ('floorclip', 'frvis', 'wpok'):
        if nclip[key] != case.clip[key]:
            problems.append('the clip pass: %s: native %r, reference %r' % (
                key, nclip[key], case.clip[key]))
    # the front end (milestone 7's frame mode at the walk's end)
    problems += RC.entry_diff(fc.case.truth, rcanon.native(
        snaps['bsp'], snaps['walk'], nsec))
    try:
        nat = rcanon.frame_native(snaps['walk'], fc.slots, nsec, fc.nlines)
    except rcanon.CanonError as e:
        return problems + ['the front end\'s outputs: %s' % e]
    if 'vtxangle' not in fc.truth:
        del nat['vtxangle']
    problems += ['walk\'s end: ' + p for p in rcanon.diff_frame(fc.truth,
                                                                nat)]
    # stages A and B, at the weapon's draw
    vis = rcanon.vis_native(snaps['psp'])
    problems += rcanon.diff_vis(mc.vis, vis)
    problems += rcanon.dsw_problems(snaps['psp'])
    try:
        mnat = rcanon.masked_native(snaps['psp'], fc.slots, mc.pmap, True,
                                    list(mc.masked['masked']), batch=True)
        problems += ['at the weapon: ' + p for p in
                     rcanon.diff_masked(mc.masked, mnat)]
        # stage C: the frame's end
        fnat = rcanon.final_native(snaps['mend'], fc.slots, mc.pmap, True)
        problems += rcanon.diff_final(case.final, fnat)
    except rcanon.CanonError as e:
        return problems + ['the masked outputs: %s' % e]
    out['vissprites'] = len(vis['vis'])
    out['records'] = sum(len(v) for v in fnat['records'].values())
    out['cliplog'] = len(fnat.get('cliplog') or [])
    # the bucket pass: each batch against milestone 5's loader
    try:
        stream = native_stream(snaps['mend'])
        exp = BC.expected(stream)
    except (BC.BucketError, rcanon.CanonError) as e:
        return problems + ['the bucket check: %s' % e]
    problems += BC.compare_batches(batches, exp)
    out['batches'] = len(exp.batches)
    out['staged'] = len(stream.staged)
    out['marks'] = sum(BC._marks(data) for _, _, data, _ in exp.batches)
    out['stores'] = stores_of(exp, stream)
    return problems


def native_stream(mend: rcanon.Snapshot) -> BC.Stream:
    """The native staging at the masked phase's end as the bucket check's
    stream: each record (its column, upstream's bytes), the covered ranges
    with their sequence numbers."""
    F = R.FRAME
    m = mend.main
    staged = rcanon.staged_bytes(mend, m(F['STG_BANK'], 1)[0],
                                 rcanon.le(m(F['STG_PTR'], 2)))
    records = []
    at = 0
    while at < len(staged):
        kind = staged[at]
        size = rcanon.NATIVE_SIZES.get(kind)
        if size is None:
            raise BC.BucketError('a staged record of kind %d' % kind)
        records.append((staged[at + 1], staged[at:at + 1] +
                        staged[at + 2:at + size]))
        at += size
    first, end = m(L5.CVFIRST, 160), m(L5.CVEND, 160)
    lo, hi = m(L5.CVRECLO, 160), m(L5.CVRECHI, 160)
    cover = {}
    for c in range(160):
        if end[c] and first[c] < end[c]:
            n = lo[c] | hi[c] << 8
            if n < len(records):        # (a dropped record: none, 6.1)
                if records[n][0] != c:
                    raise BC.BucketError('column %d: its covering record %d '
                                         'is column %d\'s' % (
                                             c, n, records[n][0]))
                cover[c] = n
    return BC.Stream(staged, records, bytes(first + end + lo + hi), cover,
                     0)


def stores_of(exp: 'BC.Expected', stream: BC.Stream) -> int:
    """The screen stores upstream makes for these records (the loader's
    model: the covered-range cut, the shadows' rows)."""
    cols: List[List[loader.Rec]] = [[] for _ in range(160)]
    for n, (c, data) in enumerate(stream.records):
        cols[c].append(loader.Rec(c, n, data[0], data, 0, 0))
    w_address = {}
    for first, end, data, starts in exp.batches:
        for i, c in enumerate(range(first, end)):
            at = starts[i]
            for r in cols[c]:
                w_address[r.origin] = at
                at += len(r.data)
    cv = stream.covered
    lo, hi = bytearray(160), bytearray(160)
    for c, w in exp.cover_w.items():
        lo[c], hi[c] = w & 0xFF, w >> 8
    covered = bytes(cv[:320]) + bytes(lo) + bytes(hi)
    first, end = cv[:160], cv[160:320]
    for c in range(160):
        if end[c] and first[c] < end[c] and c not in exp.cover_w:
            covered = covered[:c] + b'\0' + covered[c + 1:160 + c] + b'\0' + \
                covered[161 + c:]
    state = loader.State(b'', covered, (b'', b'', b''), 0)
    return loader.screen_stores(cols, state, w_address)


# ---------------------------------------------------------------------------
# Timing (fprof)
# ---------------------------------------------------------------------------

def timing8(case: F8Case, b: RC.Build, base: Sequence) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for profile in ('f121', 'fastpath'):
        work = Path(tempfile.mkdtemp(prefix='tmp-m8-ftime-',
                                     dir=str(BUILD)))
        try:
            (work / 'cost.txt').write_text(costs.text(profile))
            report = work / 'cost.json'
            extra = ['--cost', str(work / 'cost.txt'), '--cost-timed',
                     '--cost-phase', '%X' % R.PHASE, '--cost-report',
                     str(report)]
            state = RC.a2vm_run(b, list(base) + image_records(case), work,
                                [], extra, start='drv_fframe',
                                cycles=CYCLE_LIMIT, timeout=RUN_TIMEOUT)
            if state.get('pc') != b.labels['drv_halt']:
                raise F8Error('%s: the timing run ended at $%04X' % (
                    case.mc.full.case.frame.name, state.get('pc', -1)))
            text = report.read_text()
            cost = json.loads(text[text.rfind('{"final"'):])['cost']
            mhz = costs.parameters(profile)['fabric_mhz']
            res = {}
            for k, name in PHASES8.items():
                res[name] = {'ms': round(cost['phases'][k] /
                                         (mhz * 1000.0), 4),
                             'cycles': cost['phase_cycles'][k],
                             'io': cost['phase_io'][k]}
            res['total_ms'] = round(sum(cost['phases'][k] for k in PHASES8
                                        if k) / (mhz * 1000.0), 4)
            res['irqs'] = state.get('irqs', 0)
            out[profile] = res
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    return out


# ---------------------------------------------------------------------------
# The poisoned screen (4.2)
# ---------------------------------------------------------------------------

def poisoned_truth(case: F8Case, sym: blink.Symbols, screen: bytes,
                   scratch: Path) -> bytes:
    """Upstream's R_DrawLists by ref816 --call on the frame's P4 state
    with `screen` in the SHR screen and the drawers' buffer: the base
    image (a real R_DrawLists entry), P4's ranges (bank $1D, the near
    bank, the spans and covered ranges, the weapon skip), the frame's
    colormaps (P0) and its level's fuzz table over it."""
    from native import synth
    from ref816 import capture as refcapture, title
    frame = case.mc.full.case.frame
    scratch.mkdir(parents=True, exist_ok=True)
    m5 = CAPTURES / frame.name
    if (m5 / 'manifest.json').exists():
        # an m5 frame: its own capture's context (every byte its
        # R_DrawLists read; the base image is another level's)
        spath = scratch / 'screen-in.bin'
        spath.write_bytes(screen)
        state = refcapture.run_call(
            title.MACHINE, m5, refcapture.read_manifest(m5), scratch,
            [(E1_SCREEN, spath), (refcapture.BUFFER, spath)])
        if state['end']['reason'] != 'return':
            raise F8Error('ref816 --call did not return: %s' % state['end'])
        return state['screen']
    loads = []
    p4 = frame.dump('p4')
    for i, (lo, n) in enumerate(p4_ranges(p4)):
        path = scratch / ('p4-%d.bin' % i)
        path.write_bytes(p4.read(lo, n))
        loads.append((lo, path))
    cm = sym.address('iigs_shrcmapA')
    path = scratch / 'cmaps.bin'
    path.write_bytes(frame.dump('p0').read(cm, 2 * 34 * 256))
    loads.append((cm, path))
    path = scratch / 'fuzz.bin'
    path.write_bytes(case.fuzzdark)
    loads.append((levelconv.MM_FUZZ_DARKEN, path))
    spath = scratch / 'screen-in.bin'
    spath.write_bytes(screen)
    loads += [(E1_SCREEN, spath), (0x012000, spath)]
    out = scratch / 'screen-out.bin'
    command = ['nice', '-n', '10', str(title.MACHINE), str(synth.BASE)]
    for address, p in loads:
        command += ['--load', '%06X:%s' % (address, p)]
    command += ['--call', '%06X' % synth.entry_address(),
                '--save', '%06X:0x%X:%s' % (E1_SCREEN, SCREEN_SIZE, out)]
    result = bounded.run(command, timeout=300, max_bytes=64 << 20,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         universal_newlines=True)
    if result.returncode:
        raise F8Error('ref816 --call failed: %s' % result.stderr[-500:])
    state = json.loads(result.stdout)
    if state['end']['reason'] != 'return':
        raise F8Error('ref816 --call did not return: %s' % state['end'])
    return out.read_bytes()


def p4_ranges(p4) -> List[Tuple[int, int]]:
    """The ranges of a P4 dump (rendercap.ranges_of('P4')) but its screen:
    (address, length)."""
    out = []
    for lo, n in p4.d.ranges():
        if lo == E1_SCREEN:
            continue
        out.append((lo, n))
    return out


def poisoned8(case: F8Case, b: RC.Build, sym: blink.Symbols,
              base: Sequence) -> Dict[str, Any]:
    from native import replay_check
    work = Path(tempfile.mkdtemp(prefix='tmp-m8-poison-', dir=str(BUILD)))
    try:
        again = poisoned_truth(case, sym, case.screen, work / 'captured')
        if again != case.truth:
            k = next(i for i in range(SCREEN_SIZE)
                     if again[i] != case.truth[i])
            return {'problems': ['--call on the captured screen does not '
                                 'give P5 (first $%04X): the state is not '
                                 'the frame\'s' % (SCREEN + k)]}
        screen = replay_check.poisoned(case.screen)
        truth = poisoned_truth(case, sym, screen, work / 'poisoned')
        r = check8(case, b, 0x5A, base, screen=screen, truth=truth)
        r['changed'] = sum(1 for i in range(PIXELS) if truth[i] != screen[i])
        return r
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def set_of(name: str) -> str:
    return name.rsplit('-', 1)[0]


def _median(values: List[float]) -> float:
    v = sorted(values)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def report_text(results: List[Dict[str, Any]]) -> str:
    rows = [r for r in results if 'timing' in r]
    sets: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        sets.setdefault(set_of(r['frame']), []).append(r)
    lines = ['# Milestone 8: the whole frame\'s timing (a2vm, not the card)',
             '',
             'Generated by `python3 tools/native/frame8.py --timing '
             '--report`. a2vm\'s cost model (`f121`: F1.2.1; `fastpath`: the '
             'firmware design without the pair), derived from the RTL and '
             'calibrated on one hardware frame (milestone 3), not measured '
             'on the card. ms a frame, median (range), from the front end\'s '
             'window to the replay\'s last SHR write (RENDER-MASKED.md 3.2 '
             'phases 1-13); render only (no tics, status bar, input, sound).',
             '']
    names = [n for k, n in sorted(PHASES8.items(), key=lambda x: (
        [1, 2, 17, 3, 9, 10, 13, 14, 11, 15, 4, 16, 18, 12, 0].index(x[0])))
        if k]
    for profile in ('f121', 'fastpath'):
        lines += ['## %s' % profile, '',
                  '| Set | Frames | ' + ' | '.join(names) + ' | Total | '
                  'Render-only FPS |',
                  '| --- | ---: | ' + ' | '.join('---:' for _ in names) +
                  ' | ---: | ---: |']
        for key in sorted(sets):
            rs = sets[key]
            cells = []
            for n in names:
                v = [r['timing'][profile][n]['ms'] for r in rs]
                cells.append('%.2f (%.2f-%.2f)' % (_median(v), min(v),
                                                    max(v)))
            t = [r['timing'][profile]['total_ms'] for r in rs]
            cells.append('%.2f (%.2f-%.2f)' % (_median(t), min(t), max(t)))
            cells.append('%.1f (%.1f-%.1f)' % (1000.0 / _median(t),
                                                1000.0 / max(t),
                                                1000.0 / min(t)))
            lines.append('| %s | %d | %s |' % (key, len(rs),
                                               ' | '.join(cells)))
        lines.append('')
    lines += ['## The heaviest frames (f121 total)', '',
              '| Frame | Total ms | Front end | Masked | Bucket | Replay |',
              '| --- | ---: | ---: | ---: | ---: | ---: |']
    heavy = sorted(rows, key=lambda r: -r['timing']['f121']['total_ms'])[:10]
    for r in heavy:
        t = r['timing']['f121']
        front = sum(t[n]['ms'] for n in ('window', 'setup', 'clip', 'walk',
                                         'walls', 'segs'))
        masked = sum(t[n]['ms'] for n in ('mwindow', 'dscopy', 'project',
                                          'sort', 'sprites', 'weapon'))
        lines.append('| %s | %.2f | %.2f | %.2f | %.2f | %.2f |' % (
            r['frame'], t['total_ms'], front, masked, t['bucket']['ms'],
            t['replay']['ms']))
    lines += against_6fps(sets)
    lines += ['', '## The staging (RENDER-MASKED.md 6.1 item 1)', '',
              staging_margin(results)[0]]
    lines += disk_vbls(DISK_RESULTS)
    return '\n'.join(lines) + '\n'


def staging_margin(results: List[Dict[str, Any]]) -> Tuple[str, bool]:
    """RENDER-MASKED.md 6.1 item 1 on the run's frames: the staging's
    capacity at least rlayout.STAGING_MARGIN times the largest staging of
    the captured frames; every frame, the synthetic extremes included,
    within it."""
    staged = [(r['staged'], r['frame']) for r in results
              if isinstance(r.get('staged'), int)]
    if not staged:
        return 'No frame staged (no staging measured).', True
    captured = [x for x in staged if not x[1].startswith('synth-')]
    worst = max(staged)
    ok = worst[0] <= R.STAGING_BYTES
    text = 'Capacity %d B (aux 0 and %d spill banks).' % (
        R.STAGING_BYTES, len(R.RECSP))
    if captured:
        top = max(captured)
        ok = ok and R.STAGING_BYTES >= R.STAGING_MARGIN * top[0]
        text += ' Largest captured staging %d B (%s): %.1f times, at ' \
            'least %d required.' % (top[0], top[1], R.STAGING_BYTES /
                                    top[0], R.STAGING_MARGIN)
    text += ' Largest of all %d B (%s): %.1f times.%s' % (
        worst[0], worst[1], R.STAGING_BYTES / worst[0],
        '' if ok else ' **Below the requirement.**')
    return text, ok


# NATIVE.md 6's tics at 4 a frame, ms (RENDER-MASKED.md 6.2's row): still,
# the demo (its median frame), the heaviest fight; NATIVE.md 1.1's whole
# render on F1.2.1
TICS = {'still': (3.0, 6.7), 'demo3': (18.4, 41.3), 'heavy': (41.3, 41.3)}
NATIVE_11 = {'still': (36, 75), 'demo3': (61, 127)}
MIN_FPS = 6.0
DISK_RESULTS = RENDER / 'rdisk.json'


def against_6fps(sets: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    """The whole frame (render + NATIVE.md 6's tics; the status bar,
    input and sound, 1-4% more by NATIVE.md 1.2, not counted) against
    NATIVE.md 1.1's estimate and 6 FPS, f121."""
    if 'demo3' not in sets or 'still' not in sets:
        return []
    out = ['', '## Against NATIVE.md 1.1, 1.2 and 6 FPS (f121)', '',
           'Render: this report\'s totals; tics: NATIVE.md 6 at 4 a frame '
           '(RENDER-MASKED.md 6.2: %.1f-%.1f ms still, %.1f-%.1f at the '
           'demo, %.1f in the heaviest fight); the status bar, input and '
           'sound (1-4%% by NATIVE.md 1.2) not counted.' % (
               TICS['still'] + TICS['demo3'] + TICS['heavy'][:1]), '',
           '| Frame | Render ms | NATIVE.md 1.1 render | + tics, ms | FPS |',
           '| --- | ---: | ---: | ---: | ---: |']
    still = _median([r['timing']['f121']['total_ms'] for r in sets['still']])
    d3 = [r['timing']['f121']['total_ms'] for r in sets['demo3']]
    med, worst = _median(d3), max(d3)
    for name, ms, tics, est in (
            ('still (median)', still, TICS['still'], NATIVE_11['still']),
            ('demo3 median', med, TICS['demo3'], NATIVE_11['demo3']),
            ('demo3 worst', worst, TICS['heavy'], NATIVE_11['demo3'])):
        lo, hi = ms + tics[0], ms + tics[1]
        out.append('| %s | %.2f | %d-%d | %.1f-%.1f | %.1f-%.1f |' % (
            name, ms, est[0], est[1], lo, hi, 1000.0 / hi, 1000.0 / lo))
    budget = 1000.0 / MIN_FPS
    under_lo = sum(1 for ms in d3 if ms + TICS['demo3'][0] > budget)
    under_hi = sum(1 for ms in d3 if ms + TICS['heavy'][1] > budget)
    out += ['', 'demo3 frames under %.0f FPS: %d of %d with %.1f ms of tics, '
            '%d with %.1f ms (a render over %.1f, or %.1f, ms).' % (
                MIN_FPS, under_lo, len(d3), TICS['demo3'][0], under_hi,
                TICS['heavy'][1], budget - TICS['demo3'][0],
                budget - TICS['heavy'][1])]
    return out


def disk_vbls(path: Path) -> List[str]:
    """FPS by VBL count: rdisk.py --check's run of the disk image on
    a2vm (the mouse card's VBL on the model's clock)."""
    if not path.exists():
        return ['', 'FPS by VBL count: no rdisk.py --check results (%s).'
                % path]
    rep = json.loads(path.read_text())
    out = ['', '## FPS by VBL count (rdisk.py --check, a2vm)', '',
           '%d demo3 frames, %s .. %s, rendered by RENDER.SYSTEM (the '
           'frame\'s data applied before its VBL count starts).' % (
               len(rep['frames']), rep['frames'][0], rep['frames'][-1]), '',
           '| Profile | Mode | CRCs equal | VBLs (50 Hz) | ms a frame | FPS |',
           '| --- | --- | ---: | ---: | ---: | ---: |']
    for c in rep.get('checks', []):
        for mode in ('chained', 'full'):
            m = c.get(mode)
            if m:
                n = len(m['frames'])
                out.append('| %s | %s | %d of %d | %d | %.1f | %.2f |' % (
                    c['profile'], mode, m['ok'], n, m['vbls'],
                    20.0 * m['vbls'] / n, m['fps50'] or 0))
    out += ['', 'a2vm\'s mouse card gives 50 VBLs a second on the model\'s '
            'clock; the counts agree with this report\'s phase sums over '
            'the same frames. The owner\'s card counts its own VBLs (60 a '
            'second on an NTSC machine: FPS = frames x 60 / VBLs).']
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def poison_set(dirs: Sequence[Path]) -> List[Path]:
    """The m5 frames and every tenth demo3 frame (4.2)."""
    out = []
    for d in dirs:
        s = set_of(d.name)
        if s in ('still', 'demo', 'e1m3'):
            out.append(d)
        elif s == 'demo3' and int(d.name.rsplit('-', 1)[1]) % 10 == 0:
            out.append(d)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames')
    parser.add_argument('--sets')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--fills', default='a5,5a')
    parser.add_argument('--timing', action='store_true')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--poisoned', action='store_true')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--keep', type=Path)
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--obj', type=Path, default=RC.OBJ)
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--levels', choices=('converted', 'loaded'),
                        default='converted')
    parser.add_argument('--report-from', type=Path,
                        help='write --report from this --json of a '
                        '--timing run, running nothing')
    args = parser.parse_args(argv)
    if args.report_from:
        args.report = args.report or REPORT
        args.report.write_text(report_text(json.loads(
            args.report_from.read_text())))
        return 0
    if not args.no_build:
        RC.make(args.obj)
    if not RC.A2VM.exists():
        print('%s is missing: make -C tools/a2vm' % RC.A2VM, file=sys.stderr)
        return 1
    dirs = RC.frame_dirs(args.frames, args.sets)
    if not dirs:
        print('no frames: run python3 tools/native/rendercap.py',
              file=sys.stderr)
        return 1
    sym = blink.Symbols()
    b = RC.load_build(args.obj, 'ftest')
    fills = [int(f, 16) for f in args.fills.split(',')] if args.fills else []
    bases = {f: RC.base_records(b, f, window=True) for f in set(fills) |
             ({0x5A} if args.poisoned else set())}
    prof = RC.load_build(args.obj, 'fprof') if args.timing else None
    pbase = RC.base_records(prof, 0xA5, window=True) if prof else None
    poison = set(d.name for d in poison_set(dirs)) if args.poisoned else set()
    if args.levels == 'loaded':
        from native import lrun
        FS.LEVEL_HOOK = lrun.loaded_level_hook()

    def one(d: Path) -> List[Dict[str, Any]]:
        if args.levels == 'loaded':
            src = FS.Frame(d).meta['level_src']
            if src.startswith('synth-'):
                return [{'frame': d.name, 'problems': [],
                         'excluded': 'level source %s (a level made with '
                                     'pokes, not the WAD\'s)' % src}]
        try:
            case = prepare8(d, sym)
        except (FS.FrameError, levelconv.ConvError, rcanon.CanonError,
                RC.CheckError, F8Error) as e:
            return [{'frame': d.name, 'problems': ['prepare: %s' % e]}]
        out = []
        for f in fills:
            try:
                out.append(check8(case, b, f, bases[f], args.keep and
                                  args.keep / ('%s-%02X' % (d.name, f))))
            except (RC.CheckError, F8Error) as e:
                out.append({'frame': d.name, 'fill': f,
                            'problems': [str(e)]})
        if d.name in poison:
            try:
                r = poisoned8(case, b, sym, bases[0x5A])
            except (RC.CheckError, F8Error) as e:
                r = {'problems': [str(e)]}
            r.update({'frame': d.name, 'fill': 'poisoned'})
            out.append(r)
        if prof is not None and out and not out[0]['problems'] and \
                not out[0].get('known'):
            try:
                out[0]['timing'] = timing8(case, prof, pbase)
            except (RC.CheckError, F8Error) as e:
                out[0]['problems'].append(str(e))
        return out
    results = []
    failed = known = 0
    with ThreadPoolExecutor(max(1, min(2, args.jobs))) as pool:
        for rs in pool.map(one, dirs):
            for r in rs:
                results.append(r)
                if r.get('excluded'):
                    status = 'EXCLUDED (%s)' % r['excluded']
                elif r.get('known'):
                    known += 1
                    status = 'KNOWN DIVERGENCE (%s)' % r['known']
                elif r['problems']:
                    failed += 1
                    status = 'DIFFERS'
                else:
                    status = 'equal'
                fill = r.get('fill')
                line = '%-12s %s: %s' % (
                    r['frame'], '%02X' % fill if isinstance(fill, int) else
                    (fill or '--'), status)
                if 'records' in r:
                    line += (' (%d records, %d vissprites, %d clip log, '
                             '%s batches, %s marks, %s B staged, SHR %s, '
                             'stack %s, %d irqs%s)' % (
                                 r['records'], r['vissprites'],
                                 r['cliplog'], r.get('batches'),
                                 r.get('marks'), r.get('staged'),
                                 r.get('shr_writes'), r['stack_bytes'],
                                 r['irqs'],
                                 ', %d flushes' % r['flushes']
                                 if r.get('flushes') else ''))
                if 'timing' in r:
                    t = r['timing']
                    line += ' f121 %.2f ms, fastpath %.2f ms' % (
                        t['f121']['total_ms'], t['fastpath']['total_ms'])
                if r['problems'] or args.verbose or r.get('known') or \
                        r.get('excluded'):
                    print(line, flush=True)
                for p in r['problems'][:8]:
                    print('    ' + p)
    excluded = sorted(r['frame'] for r in results if r.get('excluded'))
    results = [r for r in results if not r.get('excluded')]
    frames = len({r['frame'] for r in results})
    equal = sum(1 for r in results if not r['problems'] and
                not r.get('known'))
    if args.levels == 'loaded':
        print('levels: natively loaded (build/native/levels/loaded); '
              'excluded by name: %s' % (', '.join(excluded) or 'none'))
    print('%d frames, %d runs: %d equal, %d failed, %d known divergences '
          '(%s); %d records, %d clip log calls compared' % (
              frames, len(results), equal, failed, known,
              ', '.join(sorted({r['frame'] for r in results
                                if r.get('known')})) or 'none',
              sum(r.get('records', 0) for r in results if not r['problems']),
              sum(r.get('cliplog', 0) for r in results
                  if not r['problems'])))
    flushed = sorted({r['frame'] for r in results if r.get('flushes')})
    if flushed:
        print('frames whose input screen was composed (early flushes): %s'
              % ', '.join(flushed))
    margin, margin_ok = staging_margin(results)
    print('the staging: ' + margin)
    if args.json:
        args.json.write_text(json.dumps(results, indent=1) + '\n')
    if args.report and prof is not None:
        args.report.write_text(report_text(results))
    return 1 if failed or not margin_ok else 0


if __name__ == '__main__':
    sys.exit(main())
