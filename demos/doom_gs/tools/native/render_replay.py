#!/usr/bin/env python3
"""The milestone 5 replay on the records the native front end made
(milestone 7, stage C): the SHR bytes of a frame against ref816's.

Usage:  python3 tools/native/render_replay.py [--frames NAME,...]
                [--fills a5,5a] [--json FILE]

For each frame that milestone 5 captured at R_DrawLists
(tools/ref816/capture.py, build/captures/NAME) and milestone 7 at
R_FillStamps (tools/native/rendercap.py, build/native/render/frames/NAME:
the same frame, rendercap.py chooses it as the one whose R_FillStamps
comes last before that R_DrawLists call):

  1. frame mode (render_check.check_full): the native front end runs the
     frame on a2vm, its outputs equal to the reference's at drawMasked;
     its records are taken from the staging and spill as it left them;
  2. each column's records for the replay: the native records (their
     texels the native level's 128-byte slots, RENDER.md 1.4), then
     upstream's records of the masked phase (sprites, masked walls, the
     weapon: every record of the column's list at R_DrawLists after the
     list's end at drawMasked, P3), which milestone 8 will make; the part
     of upstream's list before that end must be the list at drawMasked,
     record for record;
  3. milestone 5's loader (tools/native/loader.py, with these columns)
     and replay (src/native, build/native/obj/test.*) on a2vm, from the
     captured screen, every byte the frame does not define filled ($A5,
     then $5A): the SHR bytes (aux 0 $2000-$9FFF) must equal the captured
     screen after upstream's R_DrawLists, with no stray write and the
     screen stores of the model (tools/native/replay_check.py check_run).

So the native records drive the replay that milestone 5 checked on
upstream's: a record field, a texel slot or a column the native front end
got wrong shows in the pixels, whatever rcanon.py compared.
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge import linkmap as blink  # noqa: E402
from native import a2run, layout as L, loader, rcanon, render_check as RC, \
    rlayout as R, segdesc  # noqa: E402
from native import replay_check  # noqa: E402
from ref816 import lists  # noqa: E402

CAPTURES = replay_check.CAPTURES
NATIVE_ORIGIN = 0xF00000        # the native records' origins (not bank $1D)
SLOT_BANK = 0x80                # a native slot of bank n at bank $80 + n


class ReplayError(Exception):
    pass


def native_columns(end: rcanon.Snapshot) -> Dict[int, List[bytes]]:
    """The staged records (kind, column, fields) by column, in order, as
    upstream's records (kind, fields: R_SRC the native slot, its bank
    SLOT_BANK + the RamWorks bank)."""
    F = R.FRAME
    data = rcanon.staged_bytes(end, end.main(F['STG_BANK'], 1)[0],
                               int.from_bytes(end.main(F['STG_PTR'], 2),
                                              'little'))
    out: Dict[int, List[bytes]] = {}
    at = 0
    while at < len(data):
        kind = data[at]
        if kind == L.K_TEX:
            r = data[at:at + 12]
            rec = bytes([kind]) + r[2:8] + bytes([r[8], r[9],
                                                  SLOT_BANK + r[10]]) + \
                r[11:12]
            at += 12
        elif kind == L.K_FILL:
            r = data[at:at + 6]
            rec = bytes([kind]) + r[2:6]
            at += 6
        else:
            raise ReplayError('a staged record of kind %d' % kind)
        out.setdefault(r[1], []).append(rec)
    return out


def masked_records(capture: loader.Capture, p3, sym: blink.Symbols
                   ) -> Tuple[List[List[loader.Rec]], Dict[int, int]]:
    """Each column's records of upstream's list at R_DrawLists after its
    end at drawMasked (P3), as the loader's Recs; and each column's count
    of records before that end (checked against P3's list)."""
    lay = lists.layout(capture.units)
    colw3 = p3.read(sym.address('COLW'), 320)
    ends = [int.from_bytes(colw3[2 * c:2 * c + 2], 'little')
            for c in range(lay.columns)]
    at_p3 = rcanon.walk_lists(p3, sym, 'drawMasked')
    out: List[List[loader.Rec]] = [[] for _ in range(lay.columns)]
    before: Dict[int, int] = {}
    seen = [False] * lay.columns
    front: Dict[int, List[bytes]] = {}
    chain = -1
    for r in lists.walk(capture.memory.get, lay):
        c = r.column
        if not seen[c] and (r.page << 8 | r.offset) == ends[c]:
            seen[c] = True
        kind = r.data[0]
        if kind == L.K_NEXT:
            continue
        origin = lay.recbase + (r.page << 8) + r.offset
        if not seen[c]:
            front.setdefault(c, []).append(bytes(r.data))
            continue
        problem = loader.check_record(kind, r.data)
        if problem:
            raise ReplayError('column %d: %s' % (c, problem))
        if kind == L.K_TEX:
            chain = origin
        elif kind == L.K_TEXC and (not out[c] or out[c][-1].kind not in
                                   (L.K_TEX, L.K_TEXC)):
            raise ReplayError('column %d: a K_TEXC out of its chain' % c)
        out[c].append(loader.Rec(c, origin, kind, bytes(r.data), r.texels,
                                 chain))
    for c in range(lay.columns):
        got = [canon(x) for x in front.get(c, [])]
        want = at_p3.get(c, [])
        if got != want:
            raise ReplayError('column %d: the list at R_DrawLists does not '
                              'start with the list at drawMasked' % c)
        before[c] = len(got)
    return out, before


def canon(data: bytes) -> Tuple:
    """A record of upstream's lists as rcanon.walk_lists gives it."""
    if data[0] == L.K_TEX:
        return ('tex', data[1], data[2], data[3], data[4], data[5], data[6],
                int.from_bytes(data[7:10], 'little'), data[10])
    return ('fill', data[1], data[2], data[3], data[4])


def replay_columns(native: Dict[int, List[bytes]],
                   masked: List[List[loader.Rec]]) -> List[List[loader.Rec]]:
    out = []
    n = 0
    for c in range(len(masked)):
        col = []
        for data in native.get(c, []):
            origin = NATIVE_ORIGIN + n
            n += 1
            problem = loader.check_record(data[0], data)
            if problem:
                raise ReplayError('column %d: a native record: %s'
                                  % (c, problem))
            texels = int.from_bytes(data[7:10], 'little') \
                if data[0] == L.K_TEX else 0
            col.append(loader.Rec(c, origin, data[0], data, texels,
                                  origin if data[0] == L.K_TEX else -1))
        out.append(col + masked[c])
    return out


def slot_memory(capture: loader.Capture, level_dir: Path,
                cols: List[List[loader.Rec]]) -> None:
    """The native slots the records name, at SLOT_BANK + their bank, into
    the capture's memory, from the level's banks (levelconv.py)."""
    lv = segdesc.Level(level_dir)
    for col in cols:
        for r in col:
            if r.origin >= NATIVE_ORIGIN and r.kind == L.K_TEX:
                bank = (r.texels >> 16) - SLOT_BANK
                at = r.texels & 0xFFFF
                capture.memory.put(r.texels,
                                   bytes(lv.banks[bank][at:at + 128]))


def check_one(name: str, sym, b: RC.Build, bases, build: loader.Build,
              fills: Sequence[int], out: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {'frame': name, 'problems': []}
    fc = RC.prepare_full(RC.RENDER / 'frames' / name, sym)
    collect: Dict[str, Any] = {}
    r = RC.check_full(fc, b, 0xA5, bases[0xA5], collect=collect)
    if r['problems']:
        result['problems'] += ['frame mode: ' + p for p in r['problems']]
        return result
    capture = loader.read_capture(CAPTURES / name)
    native = native_columns(collect['end'])
    masked, before = masked_records(capture, fc.case.frame.dump('p3'), sym)
    cols = replay_columns(native, masked)
    slot_memory(capture, fc.case.level_dir, cols)
    result['records'] = {'native': sum(len(v) for v in native.values()),
                         'masked': sum(len(c) for c in masked)}
    truth = (CAPTURES / name / 'screen-after.bin').read_bytes()
    for fill in fills:
        work = out / ('%s-%02X' % (name, fill))
        package = loader.build_package(capture, build, fill=fill, cols=cols)
        batches = len(package.batches)
        image = work / 'image.img'
        work.mkdir(parents=True, exist_ok=True)
        image.write_bytes(package.image)
        run = a2run.run(image, build.labels, work, batches, snapshots=True,
                        profile='f121', write_log=a2run.stray_ranges())
        res = replay_check.check_run(run, batches, truth,
                                     package.counts['screen_stores'])
        result['%02X' % fill] = {k: res.get(k) for k in (
            'ended', 'differing_bytes', 'first', 'stray_writes',
            'stray_logged', 'shr_writes', 'stores_expected', 'ms',
            'screen_crc', 'truth_crc', 'ok')}
        if not res['ok']:
            result['problems'].append('%02X: %s' % (fill, json.dumps(
                result['%02X' % fill])))
        shutil.rmtree(str(work), ignore_errors=True)
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames')
    parser.add_argument('--fills', default='a5,5a')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--no-build', action='store_true')
    args = parser.parse_args(argv)
    if not args.no_build:
        RC.make()
    names = args.frames.split(',') if args.frames else sorted(
        d.name for d in CAPTURES.iterdir()
        if (d / 'manifest.json').exists() and
        (RC.RENDER / 'frames' / d.name / 'frame.json').exists()) \
        if CAPTURES.is_dir() else []
    if not names:
        print('no frames: run python3 tools/ref816/capture.py and '
              'python3 tools/native/rendercap.py', file=sys.stderr)
        return 1
    sym = blink.Symbols()
    b = RC.load_build(RC.OBJ, 'rwall')
    bases = {0xA5: RC.base_records(b, 0xA5, window=True)}
    build = loader.read_build()
    fills = [int(f, 16) for f in args.fills.split(',')]
    out = Path(tempfile.mkdtemp(prefix='tmp-render-replay-',
                                dir=str(RC.BUILD)))
    results = []
    failed = 0
    try:
        for name in names:
            try:
                r = check_one(name, sym, b, bases, build, fills, out)
            except (ReplayError, loader.LoadError, RC.CheckError,
                    rcanon.CanonError) as e:
                r = {'frame': name, 'problems': [str(e)]}
            results.append(r)
            failed += bool(r['problems'])
            line = '%-8s %s' % (name, 'FAIL' if r['problems'] else 'equal')
            if 'records' in r:
                line += ' (%d native records, %d of the masked phase)' % (
                    r['records']['native'], r['records']['masked'])
            for f in fills:
                x = r.get('%02X' % f)
                if x:
                    line += '; %02X: %d differing, %d stray (logged %s), ' \
                        'SHR writes %d of %d, %.2f ms' % (
                            f, x['differing_bytes'], x['stray_writes'],
                            x['stray_logged'], x['shr_writes'],
                            x['stores_expected'], x['ms'] or 0.0)
            print(line, flush=True)
            for p in r['problems'][:4]:
                print('    ' + p)
    finally:
        shutil.rmtree(str(out), ignore_errors=True)
    print('%d frames, %d failed' % (len(results), failed))
    if args.json:
        args.json.write_text(json.dumps(results, indent=1) + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
