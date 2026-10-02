#!/usr/bin/env python3
"""The bucket pass on a2vm, checked (milestone 8: stage A's prototype,
stage C's pass; docs/RENDER-MASKED.md 3.4, 4.3, 5.1 item 3).

Usage:  python3 tools/native/bucketcheck.py [--frames ...] [--sets ...]
                [--jobs 2] [--fills a5,5a] [--timing] [--json FILE]

For each captured frame (milestone 7's 188 by default), the staging the
bucket pass takes in the game: the native front end's records as it
staged them (render_check.py's frame mode on the build rwall: aux 0's
staging and the spill, in production order, each with its column byte),
then the masked phase's records (upstream's, until stage B makes them:
each column's records from its list's end at drawMasked, P3, to its end
at R_DrawLists, P4, K_NEXT dropped, in column order, the column byte
added), and the covered ranges at R_DrawLists (P4) with each covering
record as its sequence number in that staging. The pass
(src/native/bucket.s, build btest) runs on a2vm from a machine whose
every other byte is the fill: nb_frame (stage C: the bucket pass, the
groups of three batches, each batch's nb_batch and the replay, here the
driver's stand-in, where a2vm takes a snapshot). Each batch must equal
milestone 5's loader on the same records (tools/native/loader.py's
packing: batches of whole columns of at most 8,192 bytes from W $6000,
the column starts, loader.mark_fuzz's K_FUZZNOW marks): its W bytes,
COLLO/COLHI of its columns and its end, each covered column's record as
its W address; the batch list (main BK_FIRST .., its count BK_NB in zero
page) too; no write outside the pass's areas (the write log, by PC).
--timing runs it under a2vm's cost model, f121 and fastpath: ms of the
pass (cost phase 18: everything but the replay) a frame, and a staged
byte. tools/native/frame8.py runs the same comparison
(compare_batches) on every whole frame.

Speed wave 1 (docs/SPEED.md, part bucket; RENDER-MASKED.md 6.2
optimisation 10): the pass takes each column's count of W bytes from the
producers (rlayout MCNTLO/MCNTHI, kept by rrec.s's rec_room and
mrec_room), so the image holds them as the producers leave them
(counts(): every staged record's bytes less its column byte, 16 bits, the
high byte held at $FF past $FFFF) and RECDROP 0 (no batch dropped).
--obj runs another build directory (its btest and rwall).

check(..., release=True) runs a game build (-D RELEASE) against the
same loader with RENDER-MASKED.md 6.1's column cut (expected(release)):
tests/test_native_frame8.py's synthetic stagings use it, and the most
batches a frame can take (rlayout.MAXB).

A frame whose lists flush early (drawAllL) is left out (none is
captured). Every run is bounded (cycles, time, files), under nice, at
most two at a time, its directory under build/ deleted after it.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from a2vm import costs  # noqa: E402
from bridge import linkmap as blink  # noqa: E402
from native import layout as L5, levelconv, loader, rcanon, \
    render_check as RCK, rlayout as R  # noqa: E402
from ref816 import bounded, lists as ulists  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
OBJ = RCK.OBJ
A2VM = RCK.A2VM
UP_SIZES = {0: 11, 2: 5, 6: 7, 8: 4, 10: 4}
K_NEXT = 12
RECBANK = 0x1D0000
CYCLE_LIMIT = 50_000_000
SNAP = 'main:0000-00FF,main:0300-037F,main:1400-17C1,main:1980-1A7F,' \
    'main:6000-7FFF'
# a batch's bytes at most: the replay's record buffer (bucket.s RECBUF_SPAN;
# a test sets it smaller with a scratch build of bucket.s that uses the same
# span, so a frame takes more batches and groups)
BATCH_BYTES = L5.RECBUF_SIZE
WRITE_LOG = 'main:0000-00FF,main:0200-FFFF,lc,lc1,aux0-127,cpu:C000-C0FF'


class BucketError(Exception):
    pass


class Stream(NamedTuple):
    staged: bytes               # the staging, production order
    records: List[Tuple[int, bytes]]    # (column, upstream bytes) each
    covered: bytes              # CVFIRST, CVEND, CVRECLO, CVRECHI (640):
                                #   CVREC as sequence numbers
    cover_seq: Dict[int, int]   # column -> the covering record's number
    front: int                  # the front end's records


def masked_records(p3, p4, sym) -> Tuple[Dict[int, List[Tuple[int, bytes]]],
                                         Dict[int, int]]:
    """Each column's records of the masked phase: from its list's end at
    drawMasked (P3's COLW) to its end at R_DrawLists (P4's), through
    K_NEXT, upstream's bytes; and each record's address (bank $1D's
    page << 8 | offset) to its place in the column's list."""
    colw3 = p3.read(sym.address('COLW'), 320)
    colw4 = p4.read(sym.address('COLW'), 320)
    out: Dict[int, List[Tuple[int, bytes]]] = {}
    for c in range(160):
        pos = rcanon.le(colw3[2 * c:2 * c + 2])
        end = rcanon.le(colw4[2 * c:2 * c + 2])
        recs = []
        steps = 0
        while pos != end:
            steps += 1
            if steps > 4096:
                raise BucketError('column %d: the list does not end' % c)
            kind = p4.read(RECBANK + pos, 1)[0]
            if kind == K_NEXT:
                pos = p4.read(RECBANK + pos + 1, 1)[0] << 8
                continue
            if kind not in UP_SIZES:
                raise BucketError('column %d: a record of kind %d' % (c,
                                                                    kind))
            recs.append((pos, p4.read(RECBANK + pos, UP_SIZES[kind])))
            pos += UP_SIZES[kind]
        if recs:
            out[c] = recs
    return out, {}


def staged_form(column: int, data: bytes) -> bytes:
    """An upstream record with its column byte after the kind."""
    return bytes([data[0], column]) + data[1:]


def stream_of(frame, front: bytes, sym) -> Stream:
    """The staging of the frame: the front end's then the masked phase's
    records, and the covered ranges with sequence numbers."""
    p3, p4 = frame.dump('p3'), frame.dump('p4')
    records: List[Tuple[int, bytes]] = []
    at = 0
    while at < len(front):
        kind = front[at]
        size = {0: 12, 2: 6}.get(kind)
        if size is None:
            raise BucketError('the front end staged a kind %d' % kind)
        records.append((front[at + 1], front[at:at + 1] +
                        front[at + 2:at + size]))
        at += size
    nfront = len(records)
    masked, _ = masked_records(p3, p4, sym)
    seq_of: Dict[int, int] = {}
    staged = bytearray(front)
    for c in sorted(masked):
        for origin, data in masked[c]:
            seq_of[origin] = len(records)
            records.append((c, data))
            staged += staged_form(c, data)
    cv = p4.read(rcanon.MM_FS + 0x800, 0x400)
    first = bytes(cv[2 * c] for c in range(160))
    end = bytes(cv[2 * c + 1] for c in range(160))
    lo, hi = bytearray(160), bytearray(160)
    cover_seq = {}
    for c in range(160):
        if end[c] and first[c] < end[c]:
            origin = rcanon.le(cv[0x200 + 2 * c:0x200 + 2 * c + 2])
            if origin not in seq_of:
                raise BucketError('column %d: the covering record $%04X is '
                                  'no masked record of the column' % (c,
                                                                     origin))
            n = seq_of[origin]
            if records[n][0] != c:
                raise BucketError('column %d: its covering record is '
                                  'column %d\'s' % (c, records[n][0]))
            lo[c], hi[c] = n & 0xFF, n >> 8
            cover_seq[c] = n
    return Stream(bytes(staged), records, first + end + bytes(lo) +
                  bytes(hi), cover_seq, nfront)


class Expected(NamedTuple):
    batches: List[Tuple[int, int, bytes, List[int]]]   # first, end, the
                                                        #   bytes, starts
    cover_w: Dict[int, int]     # column -> the covering record's W address
    cut: Tuple[int, ...] = ()   # the game build's cut columns (6.1)


def expected(stream: Stream, release: bool = False) -> Expected:
    """milestone 5's loader on the same records: loader.mark_fuzz's marks
    and make_batches' packing (their W addresses as it gives them). With
    release, the game build's rule (RENDER-MASKED.md 6.1, bucket.s): a
    column whose records pass a batch's bytes keeps those before the first
    that would, and its batch ends with it; a covering record cut leaves
    its column no range (no W address)."""
    cols: List[List[loader.Rec]] = [[] for _ in range(160)]
    for n, (c, data) in enumerate(stream.records):
        cols[c].append(loader.Rec(c, n, data[0], data, 0, 0))
    cut = []
    if release:
        for c in range(160):
            total = 0
            for k, r in enumerate(cols[c]):
                if total + len(r.data) > BATCH_BYTES:
                    cols[c] = cols[c][:k]
                    cut.append(c)
                    break
                total += len(r.data)
    cols = loader.mark_fuzz(cols)
    batches, w_address = _batches(cols, cut)
    return Expected(batches, {c: w_address[n]
                              for c, n in stream.cover_seq.items()
                              if n in w_address}, tuple(cut))


def _batches(cols, cut: Sequence[int] = ()
             ) -> Tuple[List[Tuple[int, int, bytes, List[int]]],
                        Dict[int, int]]:
    """make_batches' packing without its texel rewrite (the records'
    texels stay as staged: the pass copies bytes); a cut column ends its
    batch."""
    sizes = [sum(len(r.data) for r in c) for c in cols]
    out, w_address = [], {}
    c = 0
    while c < len(cols):
        first, total = c, 0
        while c < len(cols) and total + sizes[c] <= BATCH_BYTES:
            total += sizes[c]
            c += 1
            if c - 1 in cut:
                break
        if c == first:
            raise BucketError('column %d alone passes a batch' % c)
        data = bytearray()
        starts = []
        for column in range(first, c):
            starts.append(L5.RECBUF + len(data))
            for r in cols[column]:
                w_address[r.origin] = L5.RECBUF + len(data)
                data += r.data
        starts.append(L5.RECBUF + len(data))
        out.append((first, c, bytes(data), starts))
    return out, w_address


def build_labels(obj: Path = OBJ) -> Dict[str, int]:
    labels = {}
    for line in (obj / 'btest.lbl').read_text().splitlines():
        f = line.split()
        if len(f) == 3 and f[0] == 'al':
            labels[f[2].lstrip('.')] = int(f[1], 16)
    return labels


def segments(obj: Path = OBJ) -> Dict[str, Tuple[int, int]]:
    import re
    out = {}
    text = (obj / 'btest.map').read_text()
    for m in re.finditer(r'^(\w+)\s+([0-9A-F]{6})\s+([0-9A-F]{6})\s+'
                         r'([0-9A-F]{6})', text, re.M):
        out[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16))
    return out


def counts(stream: Stream) -> Tuple[bytes, bytes]:
    """Each column's count of W bytes as rec_room and mrec_room leave it
    (rrec.s): the low bytes, the high bytes (160 each). A count past $FFFF
    keeps its high byte at $FF."""
    lo, hi = [0] * 160, [0] * 160
    for c, data in stream.records:
        s = lo[c] + len(data)
        lo[c] = s & 0xFF
        if s > 0xFF:
            hi[c] = min(hi[c] + 1, 0xFF)
    return bytes(lo), bytes(hi)


def image(stream: Stream, fill: int, obj: Path = OBJ) -> bytes:
    """The a2vm image: the fill, the prototype, the staging, the frame
    block's staging pointer, status and RECDROP, the covered ranges, the
    column counts (MCNTLO/MCNTHI)."""
    recs: List[Tuple[int, int, int, bytes]] = []
    pattern = bytes([fill]) * 0x10000
    recs.append((0, 0, 0x0000, pattern[:0xC000]))
    for bank in range(128):
        recs.append((1, bank, 0, pattern))
    lc = bytearray(pattern[:0x4000])
    seg = segments(obj)
    near = (obj / 'btest.near').read_bytes()
    lo = seg['BKNEAR'][0]
    lc[lo - 0xC000:lo - 0xC000 + len(near)] = near
    drv = (obj / 'btest.drv').read_bytes()
    lc[0xE000 - 0xC000:0xE000 - 0xC000 + len(drv)] = drv
    recs.append((2, 0, 0xC000, bytes(lc)))
    recs.append((3, 0, 0xD000, pattern[:0x1000]))
    far = (obj / 'btest.bfar').read_bytes()
    recs.append((0, 0, seg['BKFAR'][0], far))
    far2 = (obj / 'btest.bfar2').read_bytes()
    recs.append((0, 0, seg['BKFAR2'][0], far2))
    # the staging: aux 0 $A000-$BFFF, then the spill banks from $0200
    data = stream.staged
    first = data[:R.STAGE_END - R.STAGE]
    recs.append((1, 0, R.STAGE, first))
    rest = data[len(first):]
    bank = None
    ptr = R.STAGE + len(first)
    k = 0
    while rest:
        if k >= len(R.RECSP):
            raise BucketError('the staging passes the spill')
        bank = R.RECSP[k]
        part = rest[:R.STAGE_END - 0x0200]
        recs.append((1, bank, 0x0200, part))
        rest = rest[len(part):]
        ptr = 0x0200 + len(part)
        k += 1
    F = R.FRAME
    recs.append((0, 0, F['STG_BANK'], bytes([bank or 0])))
    recs.append((0, 0, F['STG_PTR'], ptr.to_bytes(2, 'little')))
    recs.append((0, 0, F['STATUS'], b'\0'))
    recs.append((0, 0, F['RECDROP'], b'\0'))
    recs.append((0, 0, L5.CVFIRST, stream.covered))
    lo, hi = counts(stream)
    recs.append((0, 0, R.MCNTLO, lo))
    recs.append((0, 0, R.MCNTHI, hi))
    return RCK.image_bytes(recs)


def allowed() -> List[Tuple[str, int, int, int]]:
    """What the pass may write (rlayout.allowed_writes_bucket: its zero
    page, page 1's chunk, the batch list, the column tables, the covered
    ranges, CVDONE, W's batches, RECW, the frame block's status, the cost
    phase), and the driver's IRQ vector."""
    return [(s, bank, lo, hi) for s, bank, lo, hi, _ in
            R.allowed_writes_bucket()] + [('lc', 0, 0xFFFE, 0x10000)]


def run(stream: Stream, fill: int, work: Path, cost: Optional[str] = None,
        obj: Path = OBJ, cycles: int = CYCLE_LIMIT,
        write_log: bool = True) -> Dict[str, Any]:
    lab = build_labels(obj)
    work.mkdir(parents=True, exist_ok=True)
    (work / 'image.bin').write_bytes(image(stream, fill, obj))
    rom = work / 'rom.bin'
    rom.write_bytes(bytes(0x4000))
    args = ['nice', '-n', '10', str(A2VM), '--rom', str(rom),
            '--core', 'w65c02s', '--image', str(work / 'image.bin'),
            '--switch', 'lc_read=1', '--switch', 'lc_write=1',
            '--switch', 'lc_bank2=0',
            '--reg', 'pc=%X' % lab['bdrv'], '--reg', 's=EF',
            '--reg', 'p=34',
            '--stop-pc', '%X' % lab['bdrv_halt'],
            '--stop-pc', '%X' % lab['bdrv_crash'],
            '--cycles', str(cycles),
            '--state', str(work / 'state.json'),
            '--snapshot-dir', str(work)]
    if cost:
        (work / 'cost.txt').write_text(costs.text(cost))
        args += ['--cost', str(work / 'cost.txt'), '--cost-timed',
                 '--cost-phase', '%X' % R.PHASE, '--cost-report',
                 str(work / 'cost.json')]
    else:
        (work / 'events.txt').write_text(
            'pc %X@* snapshot batch\n' % lab['bdrv_replay'])
        args += ['--input', str(work / 'events.txt'),
                 '--snapshot-ranges', SNAP, '--every-limit',
                 str(R.MAXB + 2)]
        if write_log:
            args += ['--write-log', WRITE_LOG,
                     '--write-log-file', str(work / 'writes.log'),
                     '--write-log-limit', '2000000']
    try:
        result = bounded.run(args, timeout=300, max_bytes=256 << 20,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise BucketError('a2vm did not finish in 300 s')
    state_path = work / 'state.json'
    if not state_path.exists():
        raise BucketError('a2vm failed: %s' % result.stdout[-2000:])
    state = json.loads(state_path.read_text())
    if state.get('pc') != lab['bdrv_halt']:
        raise BucketError('the run ended with %s at $%04X%s' % (
            state.get('end'), state.get('pc', -1),
            ' (bdrv_crash: a BRK)' if state.get('pc') == lab['bdrv_crash']
            else ''))
    return state


def compare_batches(snaps: Sequence[Path], exp: Expected,
                    stopped: bool = False) -> List[str]:
    """Each batch's snapshot (at the replay's call) against the loader's:
    the batch list, its W bytes, its columns' starts and end, each covered
    column's record as its W address; a cut column's covered range cleared
    when its record was cut. stopped: the run stopped (BRK) after the
    snapshots given, so fewer batches are no problem by themselves."""
    problems = []
    if len(snaps) > len(exp.batches) or \
            len(snaps) < len(exp.batches) and not stopped:
        problems.append('%d batches, the loader %d' % (len(snaps),
                                                       len(exp.batches)))
    for b, (path, (first, end, data, starts)) in enumerate(
            zip(snaps, exp.batches)):
        s = rcanon.Snapshot(levelconv.Image.parse(path.read_bytes()))
        m = s.main
        if m(0x70, 1)[0] != len(exp.batches) or \
                m(R.BK_FIRST + b, 1)[0] != first or \
                m(R.BK_FIRST + b + 1, 1)[0] != end:
            problems.append('batch %d: the batch list' % b)
        got = m(0x6000, len(data))
        if got != data:
            k = next(i for i in range(len(data)) if got[i] != data[i])
            problems.append('batch %d: W $%04X: $%02X, the loader $%02X'
                            % (b, 0x6000 + k, got[k], data[k]))
        for i, c in enumerate(range(first, end + 1)):
            w = m(L5.COLLO + c, 1)[0] | m(L5.COLHI + c, 1)[0] << 8
            if w != starts[i]:
                problems.append('batch %d: column %d starts $%04X, the '
                                'loader $%04X' % (b, c, w, starts[i]))
                break
        for c in range(first, end):
            if c in exp.cover_w:
                w = m(L5.CVRECLO + c, 1)[0] | m(L5.CVRECHI + c, 1)[0] << 8
                if w != exp.cover_w[c]:
                    problems.append('column %d: its covering record at '
                                    '$%04X, the loader $%04X' % (
                                        c, w, exp.cover_w[c]))
            elif c in exp.cut and m(L5.CVEND + c, 1)[0] and \
                    m(L5.CVFIRST + c, 1)[0] < m(L5.CVEND + c, 1)[0]:
                problems.append('column %d: cut, its covering record cut, '
                                'its range not cleared' % c)
    return problems


def check(stream: Stream, fill: int, obj: Path = OBJ,
          release: bool = False, cycles: int = CYCLE_LIMIT,
          write_log: bool = True) -> Dict[str, Any]:
    """One run of the pass (build btest of obj; release: a build with -D
    RELEASE, checked by the game build's rule), its batches against the
    loader's, its writes (unless write_log is off: a staging so large that
    the log would pass its limit). Out: the problems, the counts, the
    status the last batch saw."""
    exp = expected(stream, release)
    work = Path(tempfile.mkdtemp(prefix='tmp-m8-bucket-', dir=str(BUILD)))
    try:
        run(stream, fill, work, obj=obj, cycles=cycles, write_log=write_log)
        snaps = sorted(work.glob('batch-*.img'))
        problems = compare_batches(snaps, exp)
        status = rcanon.Snapshot(levelconv.Image.parse(
            snaps[-1].read_bytes())).main(R.FRAME['STATUS'], 1)[0] \
            if snaps else None
        if not write_log:
            return {'problems': problems, 'batches': len(exp.batches),
                    'staged': len(stream.staged), 'status': status,
                    'cut': list(exp.cut)}
        seg = segments(obj)
        code = [seg[k] for k in ('BKNEAR', 'BKFAR', 'BKFAR2')]
        drv = [seg['BDRIVER']]
        ok = allowed()
        strays = []
        for w in RCK.read_writes(work / 'writes.log'):
            if w.storage == 'io':
                if w.address not in RCK.IO_RENDER:
                    strays.append('pc $%04X wrote $%04X' % (w.pc, w.address))
                continue
            by_code = any(lo <= w.pc <= hi for lo, hi in code + drv)
            fine = by_code and any(
                s == w.storage and (s != 'aux' or bank == w.bank) and
                lo <= w.offset < hi for s, bank, lo, hi in ok)
            if not fine:
                strays.append('pc $%04X wrote %s %d $%04X' % (
                    w.pc, w.storage, w.bank, w.offset))
        if strays:
            problems.append('%d stray writes: %s' % (len(strays),
                                                     '; '.join(strays[:4])))
        return {'problems': problems, 'batches': len(exp.batches),
                'staged': len(stream.staged), 'status': status,
                'cut': list(exp.cut),
                'records': len(stream.records),
                'masked': len(stream.records) - stream.front,
                'covered': len(stream.cover_seq),
                'marks': sum(_marks(data) for _, _, data, _ in exp.batches),
                'shadows': sum(1 for c, d in stream.records if d[0] == 8)}
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def _marks(data: bytes) -> int:
    n, at = 0, 0
    sizes = {0: 11, 2: 5, 4: 4, 6: 7, 8: 4, 10: 4}
    while at < len(data):
        n += data[at] == 4
        at += sizes[data[at]]
    return n


def timing(stream: Stream, obj: Path = OBJ) -> Dict[str, Any]:
    out = {}
    for profile in ('f121', 'fastpath'):
        work = Path(tempfile.mkdtemp(prefix='tmp-m8-btime-',
                                     dir=str(BUILD)))
        try:
            run(stream, 0xA5, work, cost=profile, obj=obj)
            text = (work / 'cost.json').read_text()
            cost = json.loads(text[text.rfind('{"final"'):])['cost']
            mhz = costs.parameters(profile)['fabric_mhz']
            out[profile] = {'ms': round(cost['phases'][18] /
                                        (mhz * 1000.0), 4),
                            'cycles': cost['phase_cycles'][18],
                            'io': cost['phase_io'][18]}
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    return out


def front_staging(directory: Path, sym, fill: int = 0xA5,
                  obj: Path = OBJ) -> bytes:
    """The native front end's staging of the frame (frame mode on the
    build rwall), with its check: the frame must equal the reference."""
    fc = RCK.prepare_full(directory, sym)
    b = RCK.load_build(obj, 'rwall')
    collect: Dict[str, Any] = {}
    res = RCK.check_full(fc, b, fill, RCK.base_records(b, fill, window=True),
                         collect=collect)
    if res['problems']:
        raise BucketError('the front end differs: %s' % res['problems'][:2])
    end = collect['end']
    F = R.FRAME
    return rcanon.staged_bytes(end, end.main(F['STG_BANK'], 1)[0],
                               rcanon.le(end.main(F['STG_PTR'], 2)))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames')
    parser.add_argument('--sets')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--fills', default='a5,5a')
    parser.add_argument('--timing', action='store_true')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--obj', type=Path, default=OBJ)
    args = parser.parse_args(argv)
    if not args.no_build:
        RCK.make(args.obj)
    if not A2VM.exists():
        print('%s is missing: make -C tools/a2vm' % A2VM, file=sys.stderr)
        return 1
    sym = blink.Symbols()
    dirs = RCK.frame_dirs(args.frames, args.sets)
    fills = [int(f, 16) for f in args.fills.split(',')]

    def one(d: Path) -> Dict[str, Any]:
        from native import framestate as FS
        frame = FS.Frame(d)
        if frame.meta.get('flushes') or frame.meta.get('mflushes'):
            return {'frame': d.name, 'skipped': 'early flushes'}
        try:
            stream = stream_of(frame, front_staging(d, sym, obj=args.obj),
                               sym)
            out = {'frame': d.name, 'runs': []}
            for f in fills:
                r = check(stream, f, obj=args.obj)
                r['fill'] = f
                out['runs'].append(r)
            if args.timing:
                out['timing'] = timing(stream, obj=args.obj)
            return out
        except (BucketError, rcanon.CanonError, RCK.CheckError) as e:
            return {'frame': d.name, 'runs': [{'problems': [str(e)]}]}
    results = []
    failed = 0
    with ThreadPoolExecutor(max(1, min(2, args.jobs))) as pool:
        for res in pool.map(one, dirs):
            results.append(res)
            if 'skipped' in res:
                print('%-12s skipped: %s' % (res['frame'], res['skipped']))
                continue
            bad = [p for r in res['runs'] for p in r['problems']]
            failed += bool(bad)
            r0 = res['runs'][0]
            line = '%-12s %s' % (res['frame'], 'DIFFERS' if bad else 'equal')
            if 'staged' in r0:
                line += (' (%d B staged, %d records, %d masked, %d batches, '
                         '%d covered, %d shadows, %d marks)' % (
                             r0['staged'], r0['records'], r0['masked'],
                             r0['batches'], r0['covered'], r0['shadows'],
                             r0['marks']))
            if 'timing' in res:
                line += ' f121 %.2f ms, fastpath %.2f ms' % (
                    res['timing']['f121']['ms'],
                    res['timing']['fastpath']['ms'])
            print(line, flush=True)
            for p in bad[:6]:
                print('    ' + p)
    n = sum(1 for r in results if 'runs' in r)
    print('%d frames, %d runs, %d frames differ' % (
        n, sum(len(r.get('runs', [])) for r in results), failed))
    if args.json:
        args.json.write_text(json.dumps(results, indent=1) + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
