#!/usr/bin/env python3
"""Routine captures of upstream's masked phase for milestone 8, stage B
(docs/RENDER-MASKED.md 4.1, "Routine captures"): the reference's state at
the entry and the return of each call of R_DrawSprite, R_DrawVisSprite
and R_RenderMaskedSegRange (and maskedSeg, the drawseg loop's call of the
same range code) in the masked phase of the captured frames of milestone
7's sets (tools/native/rendercap.py).

Usage:  python3 tools/native/maskcap.py [--runs newgame,m5demo,...]
                                        [--jobs 2]

For each run of rendercap.py (the same scripts, so the same machine,
checked: both runs end with the capture run's RAM and marks), two more
runs of the release on ref816, as tools/native/routinecap.py does for the
walls:

  survey   a call log of R_DrawSprite, R_DrawVisSprite (entered by JML:
           jumps=1; its vissprite and VS_CLIP), R_RenderMaskedSegRange and
           maskedSeg, each call with its entry and return; a frame's calls
           are those between its drawMasked and its playerSkip (P3w), the
           weapon's R_DrawVisSprite (FR_VIS, after it) left out
  dump     ref816 points at each routine's entry and at each call site's
           return (the JSL + 4, maskedSeg's JSR + 3), in ranges of hits
           (at most 64 points), with the ranges RANGES (the near bank $02,
           the direct pages $00:0900-$0BFF, the drawseg columns
           $0A:B500-$B9FF, WCLIP, WPREV, WTMP $0A:C500-$C8FF, the spans
           $23:EF00-$FAFF) and the record bank $1D at a return. A dump is
           matched to its call by its cycle count.

A case is build/native/render/masked-routines/FRAME/KIND-NN.case.z (KIND
sprite, vis or mwall; NN its place in the frame): zlib of a JSON header
line (the call: its vissprite or drawseg and columns, the cycles; for a
sprite, whether it called R_DrawVisSprite and that call's clips), then
the entry's bytes, the return's xor the entry's (a call changes few bytes
of the ranges, so the pair compresses to little), then the records the
call appended in canonical form (rcanon.walk of bank $1D from the entry's
COLW to the return's) in the header. The level's arrays (the sectors,
sides, lines, things) are the frame's P0 and P3: the masked phase does
not write them.

Nothing else is kept. All runs are under nice, bounded in time, in
stream size, in call-log size and in file size; free disk space is
checked first (20 GB at least).
"""

import argparse
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

from native import rendercap as RC, routinecap as RCP  # noqa: E402
from ref816 import calls as calllog, dumps, lists as ulists, marks, \
    run_script, script, title  # noqa: E402

OUT = RC.RENDER / 'masked-routines'
FORMAT = 'render-masked-case 1'
RANGES = '02+000900:768+0AB500:1280+0AC500:1024+%06X:%d' % RC.FS_SPANS
POINT_BYTES = 0x10000 + 768 + 1280 + 1024 + RC.FS_SPANS[1]
CALL_LOG_LIMIT = 256 << 20
MARGIN = 64
SIZEOF_VIS = 42
K_TEX, K_FILL, K_TEXC, K_FUZZ, K_NEXT = 0, 2, 6, 8, 12
UP_SIZES = {K_TEX: 11, K_FILL: 5, K_TEXC: 7, K_FUZZ: 4, K_NEXT: 2}
# the routines of the survey and the dumps: the key, its entry, its call
# log text
ROUTINES = (('sprite', 'R_DrawSprite', 'R_DrawSprite,in=dp:_Dp:4'),
            ('vis', 'R_DrawVisSprite',
             'R_DrawVisSprite,jumps=1,in=dp:_Dp:4+VS_CLIP:2'),
            ('range', 'R_RenderMaskedSegRange', 'R_RenderMaskedSegRange,'
             'in=dp:_Dp:2+dp:_Dp+4:2'),
            ('seg', 'r_frame65.s:maskedSeg', 'r_frame65.s:maskedSeg,'
             'in=FR_DS:2'))


class CaptureError(Exception):
    pass


class Call(NamedTuple):
    frame: str
    kind: str                   # sprite, vis, range, seg
    k: int                      # its place among the frame's calls of kind
    hit: int
    cycles: int
    end_cycles: int
    info: Dict[str, Any]        # the vissprite, the drawseg, the columns


def frames_of_run(key: str) -> List[Path]:
    """The captured frames of a run (milestone 7's sets; not the
    synthetic frames, whose calls are not the run's)."""
    return [d for d in RCP.frames_of_run(key)
            if 'synthetic' not in json.loads((d / 'frame.json')
                                             .read_text())]


def calls_of(frame_dirs: Sequence[Path], log_path: Path, sym
             ) -> Tuple[List[Call], Dict[str, int]]:
    """The masked-phase calls of the captured frames, and the return
    sites."""
    head, lines, _ = calllog.read(log_path)
    names = [r['name'] for r in head['routines']]
    by_name = {name: key for key, _, name in
               [(k, e, t.split(',')[0]) for k, e, t in ROUTINES]}
    vbase = sym.address('vissprites')
    drawsegs = sym.address('_s_drawsegs') & 0xFFFF
    sites: Dict[str, set] = {}
    out: List[Call] = []
    spans = []
    for d in frame_dirs:
        meta = json.loads((d / 'frame.json').read_text())
        lo = meta['frame']['dm_cycles']
        hi = RC.load_dump(d / 'p3w.dump.z').header['cycles']
        spans.append((lo, hi, d.name))
    spans.sort()
    counts: Dict[Tuple[str, str], int] = {}
    for ln in lines:
        key = by_name.get(names[ln['routine']])
        if key is None:
            continue
        c = ln['cycles']
        frame = next((n for lo, hi, n in spans if lo <= c < hi), None)
        if frame is None:
            continue
        info: Dict[str, Any] = {}
        if key in ('vis', 'sprite'):
            mem = ln['in']['mem']
            ptr = int.from_bytes(bytes.fromhex(mem[0]), 'little') & 0xFFFFFF
            if key == 'vis' and int.from_bytes(bytes.fromhex(mem[1]),
                                               'little'):
                continue                    # the weapon's clip pass
            if not vbase <= ptr < vbase + SIZEOF_VIS * 80:
                if key == 'vis':
                    continue                # the weapon's draw
                raise CaptureError('%s: R_DrawSprite of $%06X' % (frame, ptr))
            if (ptr - vbase) % SIZEOF_VIS:
                raise CaptureError('%s: no vissprite at $%06X' % (frame, ptr))
            info['vis'] = (ptr - vbase) // SIZEOF_VIS
        if key in ('range', 'seg'):
            mem = ln['in']['mem']
            ds = int.from_bytes(bytes.fromhex(mem[0]), 'little')
            info['ds'] = (ds - drawsegs) // 42
            if key == 'range':
                info['x1'] = ln['in']['a'] & 0xFFFF
                info['x2'] = int.from_bytes(bytes.fromhex(mem[1]), 'little')
        if not ln.get('returned', True) or ln.get('out') is None:
            raise CaptureError('%s: a %s call that does not return'
                               % (frame, key))
        sites.setdefault(key, set()).add(ln['from'])
        n = counts.get((frame, key), 0)
        counts[(frame, key)] = n + 1
        out.append(Call(frame, key, n, ln['hit'], c, ln['out']['cycles'],
                        info))
    site = {}
    for key, v in sites.items():
        if key == 'vis':
            continue                        # (JML: no return site of its own)
        if len(v) != 1:
            raise CaptureError('%s is called from %d sites' % (key, len(v)))
        site[key] = next(iter(v)) + (3 if key == 'seg' else 4)
    return out, site


def plan_points(calls: Sequence[Call], sites: Dict[str, int], sym
                ) -> Tuple[List[Tuple[str, str]], int, int]:
    """The points: each routine's entry and each return site, over ranges
    of hits (the dumps: those matched by cycles are kept)."""
    points = []
    count = 0
    entry_of = {k: e for k, e, _ in ROUTINES}
    kinds = sorted({c.kind for c in calls})
    # maskedSeg's return site is also reached by drawsegs without masked
    # columns, so its returns are cycle points of their own
    seg_returns = sorted({c.end_cycles for c in calls if c.kind == 'seg'})
    per = len(kinds) + len([k for k in kinds if k in ('sprite', 'range')])
    most = max(1, (64 - len(seg_returns)) // max(per, 1))
    for kind in kinds:
        hits = [c.hit for c in calls if c.kind == kind]
        groups = RC.clusters(hits, most)
        for lo, hi in groups:
            hi += MARGIN
            points.append(('%s-in' % kind, dumps.resolve(
                'pc=%s,hits=%d-%d,ranges=%s' % (entry_of[kind], lo, hi,
                                                RANGES), sym)))
            count += hi - lo + 1
    # the returns: every arrival at a site in the hit range of its calls
    # (a site is reached only by the returns of its calls)
    for cyc in seg_returns:
        points.append(('seg-out', 'cycle=%d,ranges=%s+1D' % (cyc, RANGES)))
        count += 1
    for kind in ('sprite', 'range'):
        if kind not in sites:
            continue
        hits = [c.hit for c in calls if c.kind == kind]
        for lo, hi in RC.clusters(hits, most):
            points.append(('%s-out' % kind, 'pc=%06X,hits=%d-%d,ranges=%s+1D'
                           % (sites[kind], lo, hi + MARGIN, RANGES)))
            count += hi + MARGIN - lo + 1
    if len(points) > 64:
        raise CaptureError('%d points: ref816 takes 64' % len(points))
    return points, count, count * (POINT_BYTES + 0x10000)


def appended(entry: dumps.Dump, exit_: dumps.Dump, sym
             ) -> Tuple[Dict[int, List[Tuple]], Dict[int, int]]:
    """The records a call appended to each column's list (bank $1D at the
    return, from the entry's COLW to the return's, K_NEXT followed and
    dropped), canonical as rcanon.walk_lists_all's; and each appended
    record's place -> its index among the column's appended records."""
    colw = sym.address('COLW')
    c0, c1 = entry.get(colw, 320), exit_.get(colw, 320)
    bank = exit_.get(0x1D0000, 0x10000)
    out: Dict[int, List[Tuple]] = {}
    places: Dict[int, int] = {}
    for c in range(160):
        pos = c0[2 * c] | c0[2 * c + 1] << 8
        end = c1[2 * c] | c1[2 * c + 1] << 8
        recs: List[Tuple] = []
        chain = None
        steps = 0
        while pos != end:
            steps += 1
            if steps > 4096:
                raise CaptureError('column %d: the list does not reach its '
                                   'end' % c)
            kind = bank[pos]
            if kind == K_NEXT:
                pos = bank[pos + 1] << 8
                continue
            if kind not in UP_SIZES:
                raise CaptureError('column %d: a record of kind %d'
                                   % (c, kind))
            r = bank[pos:pos + UP_SIZES[kind]]
            places[c << 16 | pos] = len(recs)
            if kind == K_TEX:
                chain = r[9]
                recs.append(('tex', r[1], r[2], r[3], r[4], r[5], r[6],
                             r[7] | r[8] << 8 | r[9] << 16, r[10]))
            elif kind == K_FILL:
                recs.append(('fill', r[1], r[2], r[3], r[4]))
            elif kind == K_TEXC:
                if chain is None:
                    raise CaptureError('column %d: a K_TEXC whose chain was '
                                       'not made in the call' % c)
                recs.append(('texc', r[1], r[2], r[3], r[4],
                             chain << 16 | r[5] | r[6] << 8))
            else:
                recs.append(('fuzz', r[1], r[2], r[3]))
            pos += UP_SIZES[kind]
        if recs:
            out[c] = recs
    return out, places


def store(out: Path, call: Call, entry: dumps.Dump, exit_: dumps.Dump,
          sym, extra: Dict[str, Any]) -> int:
    common = entry.ranges()
    if exit_.ranges()[:len(common)] != common:
        raise CaptureError('the return does not hold the entry\'s ranges')
    n = sum(size for _, size in common)
    recs, places = appended(entry, exit_, sym)
    # the covered ranges the call set: their record as its index among the
    # column's appended records
    cvrec = {}
    sp0 = entry.get(RC.FS_SPANS[0], RC.FS_SPANS[1])
    sp1 = exit_.get(RC.FS_SPANS[0], RC.FS_SPANS[1])
    for c in range(160):
        if sp1[0x800 + 2 * c:0x800 + 2 * c + 2] != \
                sp0[0x800 + 2 * c:0x800 + 2 * c + 2] or \
                sp1[0xA00 + 2 * c:0xA00 + 2 * c + 2] != \
                sp0[0xA00 + 2 * c:0xA00 + 2 * c + 2]:
            if sp1[0x800 + 2 * c] < sp1[0x800 + 2 * c + 1]:
                place = sp1[0xA00 + 2 * c] | sp1[0xA00 + 2 * c + 1] << 8
                cvrec[c] = places.get(c << 16 | place, 'not appended')
    header = {'format': FORMAT, 'frame': call.frame, 'kind': call.kind,
              'k': call.k, 'hit': call.hit, 'info': call.info,
              'ranges': common,
              'cpu': {'in': entry.header['cpu'], 'out': exit_.header['cpu']},
              'cycles': {'in': entry.header['cycles'],
                         'out': exit_.header['cycles']},
              'records': {str(c): v for c, v in recs.items()},
              'cvrec': {str(c): v for c, v in cvrec.items()}}
    header.update(extra)
    data = json.dumps(header, separators=(',', ':')).encode() + b'\n' + \
        entry.data[:n] + RCP.xor(exit_.data[:n], entry.data[:n])
    target = out / call.frame
    target.mkdir(parents=True, exist_ok=True)
    path = target / ('%s-%02d.case.z' % (call.kind, call.k))
    path.write_bytes(zlib.compress(data, 6))
    return path.stat().st_size


class Case(NamedTuple):
    header: Dict[str, Any]
    entry: dumps.Dump
    exit: dumps.Dump


def load_case(path: Path) -> Case:
    raw = zlib.decompress(Path(path).read_bytes())
    nl = raw.index(b'\n')
    header = json.loads(raw[:nl])
    if header.get('format') != FORMAT:
        raise CaptureError('%s is not a masked routine case' % path)
    body = raw[nl + 1:]
    n = sum(size for _, size in header['ranges'])
    if len(body) != 2 * n:
        raise CaptureError('%s is cut short' % path)
    a = body[:n]
    b = RCP.xor(body[n:], a)
    mk = lambda data, which: dumps.Dump(  # noqa: E731
        {'cpu': header['cpu'][which], 'cycles': header['cycles'][which],
         'ranges': header['ranges'], 'bytes': n}, data)
    return Case(header, mk(a, 'in'), mk(b, 'out'))


def run_one(spec: RC.RunSpec, symbols: script.Symbols, out: Path,
            log_file=None) -> Dict[str, Any]:
    def say(text):
        line = '[%s] %s' % (spec.key, text)
        print(line, flush=True)
        if log_file:
            log_file.write(line + '\n')
            log_file.flush()

    frame_dirs = frames_of_run(spec.key)
    if not frame_dirs:
        return {'run': spec.key, 'cases': 0}
    RC.check_disk(out)
    tmp = Path(tempfile.mkdtemp(prefix='tmp-m8-mcap-%s-' % spec.key,
                                dir=str(RC.make_image.BUILD)))
    try:
        prog = RC.program(spec, symbols, tmp)
        seconds = RC.limit_seconds(spec)
        r = RC.routines(symbols)
        # -- the survey
        w1 = tmp / 'survey'
        w1.mkdir()
        (w1 / 'input.txt').write_text(prog)
        log = w1 / 'calls.log'
        extra = RC.mark_options(r) + calllog.options(
            [t for _, _, t in ROUTINES], log)
        extra += ['--call-log-limit', str(CALL_LOG_LIMIT)]
        start = time.time()
        run = RC.Streamed(RC.machine_command(w1 / 'input.txt', w1, symbols,
                                             seconds, extra), RC.RUN_TIMEOUT)
        run.finish()
        state1 = json.loads((w1 / 'state.json').read_text())
        log1 = marks.read(w1 / 'marks.txt')
        problems = run_script.problems(state1, log1, symbols, prog)
        if problems:
            raise CaptureError('survey: ' + '; '.join(problems))
        calls, sites = calls_of(frame_dirs, log, symbols)
        log.unlink()
        say('survey: %d calls in %d frames (%s), %.0f s' % (
            len(calls), len(frame_dirs), ', '.join(
                '%s %d' % (k, sum(1 for c in calls if c.kind == k))
                for k in ('sprite', 'vis', 'range', 'seg')),
            time.time() - start))
        # -- the dumps
        points, count, size = plan_points(calls, sites, symbols)
        RC.check_disk(out)
        w2 = tmp / 'dump'
        w2.mkdir()
        (w2 / 'input.txt').write_text(prog)
        extra = RC.mark_options(r)
        for _, text in points:
            extra += ['--dump-at', text]
        extra += ['--dump-stream', '-', '--dump-limit',
                  str(int(size * 1.5) + (64 << 20)),
                  '--dump-max', str(int(count * 1.5) + 1000)]
        start = time.time()
        run = RC.Streamed(RC.machine_command(w2 / 'input.txt', w2, symbols,
                                             seconds, extra), RC.RUN_TIMEOUT)
        kinds = [k for k, _ in points]
        want: Dict[Tuple[str, int], List[Call]] = {}
        for c in calls:
            want.setdefault(('%s-in' % c.kind, c.cycles), []).append(c)
            out_kind = 'sprite' if c.kind == 'vis' else c.kind
            want.setdefault(('%s-out' % out_kind, c.end_cycles),
                            []).append(c)
        got: Dict[Tuple[str, int], dumps.Dump] = {}
        for d in run.dumps():
            key = (kinds[d.header['point']], d.header['cycles'])
            if key in want and key not in got:
                got[key] = d
        run.finish()
        state2 = json.loads((w2 / 'state.json').read_text())
        if state2['ram_fnv1a64'] != state1['ram_fnv1a64'] or \
                (w2 / 'marks.txt').read_bytes() != \
                (w1 / 'marks.txt').read_bytes():
            raise CaptureError('the dump run differs from the survey')
        stored, total = 0, 0
        vis_by_sprite: Dict[Tuple[str, int], Call] = {}
        for c in calls:
            if c.kind == 'vis':
                vis_by_sprite[(c.frame, c.end_cycles)] = c
        for c in calls:
            out_kind = 'sprite' if c.kind == 'vis' else c.kind
            e = got.get(('%s-in' % c.kind, c.cycles))
            x = got.get(('%s-out' % out_kind, c.end_cycles))
            if e is None or x is None:
                raise CaptureError('%s %s %d: no dumps' % (c.frame, c.kind,
                                                           c.k))
            extra: Dict[str, Any] = {}
            if c.kind == 'sprite':
                v = vis_by_sprite.get((c.frame, c.end_cycles))
                extra['drawvis'] = None
                if v is not None:
                    ve = got[('vis-in', v.cycles)]
                    fl = ve.get(symbols.address('floorclip'), 320)
                    ce = ve.get(symbols.address('ceilingclip'), 320)
                    extra['drawvis'] = {
                        'vis': v.info['vis'],
                        'floorclip': [fl[2 * i] for i in range(160)],
                        'ceilclip': [ce[2 * i] for i in range(160)]}
            total += store(out, c, e, x, symbols, extra)
            stored += 1
        say('dump: %d cases, %.1f MB, %.0f s' % (stored, total / 1e6,
                                                  time.time() - start))
        return {'run': spec.key, 'cases': stored, 'bytes': total,
                'sites': sites,
                'kinds': {k: sum(1 for c in calls if c.kind == k)
                          for k in ('sprite', 'vis', 'range', 'seg')}}
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--runs', default=','.join(
        s.key for s in RC.RUNS))
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args(argv)
    wanted = args.runs.split(',')
    specs = [s for s in RC.RUNS if s.key in wanted]
    if len(specs) != len(wanted):
        parser.error('unknown run in %s' % args.runs)
    if not RC.FRAMES.exists():
        print('no frames: run python3 tools/native/rendercap.py first',
              file=sys.stderr)
        return 1
    title.build_machine()
    title.ensure_image()
    symbols = dumps.symbols()
    args.out.mkdir(parents=True, exist_ok=True)
    RC.check_disk(args.out)
    try:
        with open(str(RC.RENDER / 'maskcap.log'), 'a') as log_file:
            with ThreadPoolExecutor(max(1, min(2, args.jobs))) as pool:
                results = list(pool.map(
                    lambda s: run_one(s, symbols, args.out, log_file),
                    specs))
    except CaptureError as error:
        print('maskcap: %s' % error, file=sys.stderr)
        return 1
    index_path = args.out / 'index.json'
    index = json.loads(index_path.read_text()) if index_path.exists() \
        else {}
    for res in results:
        index[res['run']] = res
    index_path.write_text(json.dumps(index, indent=1) + '\n')
    for res in results:
        print('%s: %d cases, %s MB (%s)' % (
            res['run'], res['cases'], round(res.get('bytes', 0) / 1e6, 1),
            ', '.join('%s %d' % kv for kv in
                      sorted(res.get('kinds', {}).items()))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
