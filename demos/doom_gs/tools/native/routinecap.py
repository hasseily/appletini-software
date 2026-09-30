#!/usr/bin/env python3
"""Routine captures of upstream's wall setup and seg loop for milestone 7,
stage B (docs/RENDER.md 4.1, "Routine captures"): the reference's state
at the entry and the return of R_StoreWallRange and of the
R_RenderSegLoop call it makes, for every wall call of the captured
frames of tools/native/rendercap.py.

Usage:  python3 tools/native/routinecap.py [--runs newgame,m5demo,...]
                                           [--jobs 2]

For each run of rendercap.py (the same scripts, so the same machine,
checked: both runs end with the capture run's RAM and marks), two more
runs of the release on ref816:

  survey   a call log of R_StoreWallRange and R_RenderSegLoop (entry
           and return), drawAllL (entries: an early flush of the lists)
           and the routines of upstream's paths (PATHS: scaleSlow,
           edgeSlow, _Mod16's entries only, genColumn, fstepHigh ...).
           The wall calls of each captured frame must be its calls.json's
           (hit, cycles, start), which ties the cases to the frames. Each
           wall call gets the seg loop call made inside it (none when it
           returns early), a flag when an early flush fell inside it, and
           the paths taken inside it (the coverage report).
  dump     ref816 points (at most 64: the calls go in at most CLUSTERS
           ranges of hits, and the calls of a range that are not wanted
           are dropped as the stream is read):
              SWE  pc=R_StoreWallRange            the entry
              SLE  pc=R_RenderSegLoop             its seg loop's entry
              SLR  the seg loop's return site     (r_wall65.s, the JSL + 4)
              SWR  the wall's return site         (r_bsp65.s, the JSL + 4)
           with the ranges RANGES (the near bank $02, the direct pages
           $00:0900-$0BFF, the drawseg columns $0A:B500-$B9FF, the spans
           $23:EF00-$FAFF), and the record bank $1D at SWR. A dump is
           matched to its call by its cycle count (Wall.moments), not by
           its hit: an interrupt taken at a pc point's instruction returns
           to it, a second arrival that shifts the hits after it.

A case is stored in build/native/render/routines/FRAME/wKK.case.z (KK the
call's place in the frame's calls.json): zlib of a JSON header line, then
SWE's bytes, SLE xor SWE, SLR xor SLE, SWR xor SLR (xor: the four hold the
same ranges, and a call changes few bytes, so the chain compresses to
little), then bank $1D at SWR. The level's arrays at the call (sectors,
sides, lines, texturetranslation, textureheight) are the frame's P0: the
renderer writes only the sectors' validcount and the lines' ML_MAPPED
there during a frame, which `check_zone` verifies on every frame (P0
against P3).

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

from native import rendercap as RC  # noqa: E402
from ref816 import calls as calllog, dumps, marks, run_script, script, \
    title  # noqa: E402

ROUTINES = RC.RENDER / 'routines'
FORMAT = 'render-routine-case 1'
RANGES = '02+000900:768+0AB500:1280+%06X:%d' % RC.FS_SPANS
CLUSTERS = 15                   # 4 points a range, 64 at most
CALL_LOG_LIMIT = 256 << 20
POINT_BYTES = 0x10000 + 768 + 1280 + RC.FS_SPANS[1]
KINDS = ('SWE', 'SLE', 'SLR', 'SWR')
MARGIN = 64                     # arrivals past a range's last call


class CaptureError(Exception):
    pass


class Wall(NamedTuple):
    frame: str
    k: int                      # its place in the frame's calls.json
    hit: int                    # R_StoreWallRange's arrival
    cycles: int
    end_cycles: int
    start: int
    sl_hit: int                 # its R_RenderSegLoop call (0: none)
    sl_cycles: int              #   its entry and return
    sl_end_cycles: int
    flushed: bool               # an early flush inside the call
    paths: Dict[str, int]       # PATHS taken inside the call (counts)

    def moments(self) -> Dict[str, int]:
        """The cycle counts of the four dumps (a dump is matched by its
        cycles: a pc point counts the arrivals at its address, and an
        interrupt taken at that instruction boundary returns to it, a
        second arrival that shifts the hits after it)."""
        out = {'SWE': self.cycles, 'SWR': self.end_cycles}
        if self.sl_hit:
            out.update(SLE=self.sl_cycles, SLR=self.sl_end_cycles)
        return out


# ---------------------------------------------------------------------------
# The frames of a run, and the zone check
# ---------------------------------------------------------------------------

def frames_of_run(key: str, root: Path = RC.FRAMES) -> List[Path]:
    out = []
    for d in sorted(root.iterdir()) if root.exists() else []:
        meta = d / 'frame.json'
        if meta.exists() and json.loads(meta.read_text())['run'] == key:
            out.append(d)
    return out


def check_zone(directory: Path, sym) -> int:
    """P0 and P3 of a frame differ in the zone only in the sectors'
    validcount and the lines' r_flags: what a routine case takes from P0
    is what it read. The count of bytes that differ."""
    p0 = RC.load_dump(directory / 'p0.dump.z')
    p3 = RC.load_dump(directory / 'p3.dump.z')
    z0, z3 = p0.get(0x060000, 0x40000), p3.get(0x060000, 0x40000)
    u = lambda d, n, s: int.from_bytes(d.get(sym.address(n), s),  # noqa
                                       'little')
    secs, nsec = u(p0, '_g_sectors', 3), u(p0, '_g_numsectors', 2)
    lines, nl = u(p0, '_g_lines', 3), u(p0, '_g_numlines', 2)
    count = 0
    for i in range(len(z0)):
        if z0[i] == z3[i]:
            continue
        a = 0x060000 + i
        count += 1
        if secs <= a < secs + 58 * nsec and (a - secs) % 58 in (20, 21):
            continue
        if lines <= a < lines + 36 * nl and (a - lines) % 36 in (32, 33):
            continue
        raise CaptureError('%s: the zone changed at $%06X between P0 and '
                           'P3' % (directory.name, a))
    return count


# ---------------------------------------------------------------------------
# The survey run
# ---------------------------------------------------------------------------

# The paths of upstream's wall setup and seg loops that a wall call takes
# (RENDER.md 4.1's coverage report), from the survey's call log: each
# routine's entries inside the call. fsGeneral is reached by BRL from
# fstepHigh (a scale high word above $40 in A); tierFlat by BRA (its
# R_DrawColumnFlat); the loops by JMP (varTab), hence jumps=1.
PATHS = (('scaleSlow', 'r_wall65.s:scaleSlow,entry=1'),
         ('scaleFast', 'r_wall65.s:scaleFast,entry=1'),
         ('distAny', 'r_wall65.s:distAny,entry=1'),
         ('edgeSlow', 'r_wall65.s:edgeSlow,entry=1'),
         ('mod16', '_Mod16,entry=1'),
         ('genColumn', 'r_seg65.s:genColumn,entry=1'),
         ('genLoop', 'r_seg65.s:genLoop,entry=1,jumps=1'),
         ('vMask', 'r_seg65.s:vMask,entry=1,jumps=1'),
         ('skyColumn', 'r_seg65.s:skyColumn,entry=1'),
         ('tcExact', 'r_seg65.s:tcExact,entry=1'),
         ('fstepHigh', 'r_seg65.s:fstepHigh,entry=1'),
         ('c26LightSetup', 'r_seg65.s:c26LightSetup,entry=1'),
         ('drawColumnFlat', 'R_DrawColumnFlat,entry=1'))


def survey_routines() -> List[str]:
    return ['R_StoreWallRange', 'R_RenderSegLoop', 'drawAllL,entry=1'] + \
        [text for _, text in PATHS]


def walls_of(frame_dirs: Sequence[Path], log_path: Path
             ) -> Tuple[List[Wall], Dict[str, int]]:
    """The wall calls of the captured frames, checked against their
    calls.json, with their seg loop calls; and the return sites."""
    head, lines, _ = calllog.read(log_path)
    names = [r['name'] for r in head['routines']]
    sw = [ln for ln in lines if names[ln['routine']] == 'R_StoreWallRange']
    sl = [ln for ln in lines if names[ln['routine']] == 'R_RenderSegLoop']
    fl = [ln['cycles'] for ln in lines if names[ln['routine']] == 'drawAllL']
    path_of = {text.split(',')[0]: key for key, text in PATHS}
    by_path: Dict[str, List[Tuple[int, int]]] = {}
    for ln in lines:
        key = path_of.get(names[ln['routine']])
        if key is not None:
            by_path.setdefault(key, []).append((ln['cycles'],
                                                ln['in']['a']))
    by_hit = {ln['hit']: ln for ln in sw}
    sites = {'sw': {ln['from'] for ln in sw}, 'sl': {ln['from'] for ln in sl}}
    for k, v in sites.items():
        if len(v) != 1:
            raise CaptureError('%s is called from %d sites' % (k, len(v)))
    sl_sorted = sorted((ln['cycles'], ln['hit'], ln['out']['cycles'])
                       for ln in sl)
    out = []
    for d in frame_dirs:
        name = d.name
        calls = json.loads((d / 'calls.json').read_text())['storewall']
        for k, c in enumerate(calls):
            got = by_hit.get(c['hit'])
            if got is None or got['cycles'] != c['cycles'] or \
                    got['in']['a'] != c['in']['a']:
                raise CaptureError('%s call %d: the survey differs from the '
                                   'capture' % (name, k))
            lo, hi = got['cycles'], got['out']['cycles']
            inside = [x for x in sl_sorted if lo < x[0] < hi]
            if len(inside) > 1:
                raise CaptureError('%s call %d: %d seg loops inside'
                                   % (name, k, len(inside)))
            sl_lo, sl_hit, sl_hi = inside[0] if inside else (0, 0, 0)
            paths = {}
            for key, calls in by_path.items():
                n = sum(1 for cyc, _ in calls if lo < cyc < hi)
                if n:
                    paths[key] = n
            gen = sum(1 for cyc, a in by_path.get('fstepHigh', ())
                      if lo < cyc < hi and a & 0xFFFF > 0x40)
            if gen:
                paths['fsGeneral'] = gen
            out.append(Wall(name, k, c['hit'], lo, hi, got['in']['a'] &
                            0xFFFF, sl_hit, sl_lo, sl_hi,
                            any(lo < f < hi for f in fl), paths))
    return out, {k: next(iter(v)) + 4 for k, v in sites.items()}


# ---------------------------------------------------------------------------
# The dump run
# ---------------------------------------------------------------------------

def ranges_of_hits(hits: Sequence[int], most: int) -> List[Tuple[int, int]]:
    return RC.clusters(list(hits), most)


def plan_points(walls: Sequence[Wall], sites: Dict[str, int],
                sym) -> Tuple[List[Tuple[str, str]], int, int]:
    """The points, and the dumps and bytes the stream may hold."""
    groups = ranges_of_hits([w.hit for w in walls], CLUSTERS)
    points = []
    count = 0
    by_hit = {w.hit: w for w in walls}
    all_sw = sorted(by_hit)
    for lo, hi in groups:
        sl = [by_hit[h].sl_hit for h in all_sw if lo <= h <= hi and
              by_hit[h].sl_hit]
        # the arrivals of a pc point run ahead of the calls by the
        # interrupts taken at its instruction (Wall.moments): MARGIN more
        hi += MARGIN
        points.append(('SWE', dumps.resolve('pc=R_StoreWallRange,hits=%d-%d,'
                                            'ranges=%s' % (lo, hi, RANGES),
                                            sym)))
        points.append(('SWR', 'pc=%06X,hits=%d-%d,ranges=%s+1D' % (
            sites['sw'], lo, hi, RANGES)))
        if sl:
            points.append(('SLE', dumps.resolve(
                'pc=R_RenderSegLoop,hits=%d-%d,ranges=%s' % (
                    min(sl), max(sl) + MARGIN, RANGES), sym)))
            points.append(('SLR', 'pc=%06X,hits=%d-%d,ranges=%s' % (
                sites['sl'], min(sl), max(sl) + MARGIN, RANGES)))
        count += 4 * (hi - lo + 1)
    if len(points) > 64:
        raise CaptureError('%d points: ref816 takes 64' % len(points))
    return points, count, count * (POINT_BYTES + 0x4000)


def xor(a: bytes, b: bytes) -> bytes:
    return (int.from_bytes(a, 'little') ^ int.from_bytes(b, 'little')
            ).to_bytes(len(a), 'little')


def store(out: Path, wall: Wall, got: Dict[str, dumps.Dump]) -> int:
    swe, swr = got['SWE'], got['SWR']
    common = swe.ranges()
    if swr.ranges()[:len(common)] != common:
        raise CaptureError('SWR does not hold SWE\'s ranges')
    n = sum(size for _, size in common)
    chain = [swe.data[:n]]
    order = ['SWE']
    if wall.sl_hit:
        for kind in ('SLE', 'SLR'):
            if got[kind].ranges() != common:
                raise CaptureError('%s does not hold SWE\'s ranges' % kind)
            chain.append(got[kind].data[:n])
            order.append(kind)
    chain.append(swr.data[:n])
    order.append('SWR')
    blob = [chain[0]] + [xor(chain[i], chain[i - 1])
                         for i in range(1, len(chain))]
    rec = swr.get(0x1D0000, 0x10000)
    header = {'format': FORMAT, 'frame': wall.frame, 'k': wall.k,
              'hit': wall.hit, 'sl_hit': wall.sl_hit, 'start': wall.start,
              'flushed': wall.flushed, 'ranges': common, 'order': order,
              'cpu': {k: got[k].header['cpu'] for k in order},
              'cycles': {k: got[k].header['cycles'] for k in order}}
    data = json.dumps(header, separators=(',', ':')).encode() + b'\n' + \
        b''.join(blob) + rec
    target = out / wall.frame
    target.mkdir(parents=True, exist_ok=True)
    path = target / ('w%02d.case.z' % wall.k)
    path.write_bytes(zlib.compress(data, 6))
    return path.stat().st_size


class Case(NamedTuple):
    header: Dict[str, Any]
    points: Dict[str, dumps.Dump]       # SWE, SLE, SLR, SWR (as dumps)


def load_case(path: Path) -> Case:
    raw = zlib.decompress(Path(path).read_bytes())
    nl = raw.index(b'\n')
    header = json.loads(raw[:nl])
    if header.get('format') != FORMAT:
        raise CaptureError('%s is not a routine case' % path)
    body = raw[nl + 1:]
    n = sum(size for _, size in header['ranges'])
    parts = []
    at = 0
    prev = None
    for kind in header['order']:
        chunk = body[at:at + n]
        at += n
        cur = chunk if prev is None else xor(chunk, prev)
        parts.append((kind, cur))
        prev = cur
    rec = body[at:at + 0x10000]
    if len(rec) != 0x10000:
        raise CaptureError('%s is cut short' % path)
    out = {}
    for kind, data in parts:
        ranges = [list(r) for r in header['ranges']]
        if kind == header['order'][-1]:       # the record bank: the last
            ranges = ranges + [[0x1D0000, 0x10000]]
            data = data + rec
        h = {'cpu': header['cpu'][kind], 'cycles': header['cycles'][kind],
             'ranges': ranges, 'bytes': len(data)}
        out[kind] = dumps.Dump(h, data)
    return Case(header, out)


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

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
    zone = {d.name: check_zone(d, symbols) for d in frame_dirs}
    RC.check_disk(out)
    tmp = Path(tempfile.mkdtemp(prefix='tmp-render-rcap-%s-' % spec.key,
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
        extra = RC.mark_options(r) + calllog.options(survey_routines(), log)
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
        walls, sites = walls_of(frame_dirs, log)
        log.unlink()
        say('survey: %d wall calls in %d frames, %d with an early flush, '
            '%.0f s' % (len(walls), len(frame_dirs),
                        sum(w.flushed for w in walls), time.time() - start))

        # -- the dumps
        points, count, size = plan_points(walls, sites, symbols)
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
        want: Dict[Tuple[str, int], List[Wall]] = {}
        for w in walls:
            for kind, cycles in w.moments().items():
                want.setdefault((kind, cycles), []).append(w)
        pending: Dict[Tuple[str, int], Dict[str, dumps.Dump]] = {}
        stored, total = 0, 0
        seen = set()
        for d in run.dumps():
            kind = kinds[d.header['point']]
            key = (kind, d.header['cycles'])
            if key not in want or key in seen:
                continue
            seen.add(key)
            for w in want[key]:
                got = pending.setdefault((w.frame, w.k), {})
                got[kind] = d
                if kind != 'SWR':
                    continue
                need = {'SWE', 'SWR'} | ({'SLE', 'SLR'} if w.sl_hit else
                                        set())
                if set(got) != need:
                    raise CaptureError('%s call %d: dumps %s' % (
                        w.frame, w.k, sorted(got)))
                if got['SWE'].header['cpu']['a'] & 0xFFFF != w.start:
                    raise CaptureError('%s call %d: A at the entry $%04X, '
                                       'the log $%04X' % (
                                           w.frame, w.k,
                                           got['SWE'].header['cpu']['a'],
                                           w.start))
                total += store(out, w, got)
                stored += 1
                del pending[(w.frame, w.k)]
        run.finish()
        state2 = json.loads((w2 / 'state.json').read_text())
        if state2['ram_fnv1a64'] != state1['ram_fnv1a64'] or \
                (w2 / 'marks.txt').read_bytes() != \
                (w1 / 'marks.txt').read_bytes():
            raise CaptureError('the dump run differs from the survey')
        if stored != len(walls) or pending:
            raise CaptureError('%d of %d cases stored' % (stored, len(walls)))
        say('dump: %d cases, %.1f MB, %.0f s' % (stored, total / 1e6,
                                                  time.time() - start))
        index = [w._asdict() for w in walls]
        totals: Dict[str, int] = {}
        for w in walls:
            for key in w.paths:
                totals[key] = totals.get(key, 0) + 1
        return {'run': spec.key, 'cases': stored, 'bytes': total,
                'flushed': sum(w.flushed for w in walls),
                'no_segloop': sum(not w.sl_hit for w in walls),
                'zone_bytes_changed': zone, 'walls': index,
                'sites': sites, 'paths': totals}
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--runs', default=','.join(s.key for s in RC.RUNS))
    parser.add_argument('--out', type=Path, default=ROUTINES)
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
        with open(str(RC.RENDER / 'routinecap.log'), 'a') as log_file:
            with ThreadPoolExecutor(max(1, min(2, args.jobs))) as pool:
                results = list(pool.map(
                    lambda s: run_one(s, symbols, args.out, log_file),
                    specs))
    except CaptureError as error:
        print('routinecap: %s' % error, file=sys.stderr)
        return 1
    index_path = args.out / 'index.json'
    index = json.loads(index_path.read_text()) if index_path.exists() \
        else {}
    for res in results:
        index[res['run']] = res
    index_path.write_text(json.dumps(index, indent=1) + '\n')
    for res in results:
        print('%s: %d cases, %s MB, %d without a seg loop, %d with an early '
              'flush; walls taking each path: %s' % (
                  res['run'], res['cases'],
                  round(res.get('bytes', 0) / 1e6, 1),
                  res.get('no_segloop', 0), res.get('flushed', 0),
                  ', '.join('%s %d' % kv for kv in
                            sorted(res.get('paths', {}).items()))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
