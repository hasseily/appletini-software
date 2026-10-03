#!/usr/bin/env python3
"""Check the native replay against upstream's on captured and synthetic
frames, and time it.

Usage:  python3 tools/native/replay_check.py [DIR ...] [--jobs N]
                [--out DIR] [--json FILE] [--keep] [--quiet] [--breakdown]
                [--obj DIR]

With no DIR, every frame of build/captures/ (tools/ref816/capture.py).
A DIR may also be a synthetic stream of tools/native/synth.py.

For each frame, three a2vm runs of the native replay (src/native, built
by make -C src/native, or the build in --obj DIR: make -C src/native
OUT=DIR; the image from tools/native/loader.py):

  captured   from the captured screen; the truth is screen-after.bin
             (upstream's R_DrawLists on the reference)
  poisoned   from a poisoned screen (a pattern in the pixels, the SCBs
             and palettes as captured); the truth is ref816 --call of
             upstream's R_DrawLists on the same poisoned screen (and
             buffer, which its drawers read)
  fastpath   the captured run again under a2vm's fastpath cost profile

The first two run under the f121 profile and take a snapshot of the whole
machine (main, both language-card parts, all 128 aux banks) just before
and just after each call of the replay (one call a batch). Every byte the
frame and the build do not define is filled, $A5 in the captured run and
$5A in the poisoned one (tools/native/layout.py FILL_CAPTURED,
FILL_POISONED), so a stray store of any constant, zero included, changes
a byte in at least one run. Checked:

  * the run ends at the driver's halt (no crash, no stray end);
  * all of aux bank 0 $2000-$9FFF after the last call equals the truth,
    byte for byte;
  * no stray writes: across each call, every byte of every bank is
    unchanged outside the ranges the replay may write (tools/native/
    layout.py ALLOWED_MAIN, ALLOWED_AUX0, and the stack from $01C0 up to
    the driver's S, $01EF: the caller's frame above it is checked too;
    the language card must come back whole: its row-block patches are
    restored);
  * no stray writes, by a2vm's write log (--write-log, tools/native/
    a2run.py stray_ranges): no CPU write during a call into main or aux
    bank 0 outside those ranges, or into aux banks 1-127, whatever its
    value, so a store of the value already there is seen too (the
    language card is left to the snapshots: the replay patches and
    restores its row blocks there);
  * the soft switches and S after each call are those before it;
  * the replay's SHR writes (a2vm's shr_writes) equal the screen stores
    upstream makes for the frame (tools/native/loader.py screen_stores:
    the rows left after the covered-range cuts, the shadows' rows, the
    automap pixels), and it makes no other video writes (docs/
    MEMORY_MAP.md rule 3). The pixels alone cannot show a cut that is not
    made: the covering record paints its range again.

Times: the replay's phase (all its calls) under f121 and fastpath, in
milliseconds of the card's clock (a2vm's cost model, not yet measured on
the card: milestone 0). With --breakdown, the profiling build (src/native
built with -D PROFILE: it marks its parts as cost phases) also gives the
time of the gather's walk, its texel copies, the copies' soft-switch
writes (RAMRD on and off, one $C073 write a bank a group of descriptors)
and the draw (with the drain it waits for at the end) under both
profiles, with the texel bytes the copies move (tools/native/loader.py
texel_copies: a wrap copies its two runs only, speed wave 2).

Exit status 0 when every frame passes.
"""

import argparse
import json
import os
import shutil
import sys
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from native import a2run, loader, layout as L  # noqa: E402
from ref816 import capture as refcapture, title  # noqa: E402

CAPTURES = ROOT / 'build' / 'captures'
OUT = ROOT / 'build' / 'native' / 'check'
E1_SCREEN = refcapture.SCREEN
BUFFER = refcapture.BUFFER

# The pattern of tests/test_ref816_capture.py, over the pixels only.
POISON = bytes(((i * 7 + 3) ^ 0x5a) & 0xff for i in range(L.PIXELS))


def poisoned(screen: bytes) -> bytes:
    return POISON + screen[L.PIXELS:]


def crc(data: bytes) -> int:
    return zlib.crc32(data) & 0xffffffff


def truth_on(directory: Path, manifest: Dict, screen: bytes,
             scratch: Path) -> bytes:
    """Upstream's R_DrawLists run by ref816 --call on the frame's state
    with `screen` in both the SHR screen and the drawers' buffer: the
    screen after it (32 KB at $E1:2000)."""
    scratch.mkdir(parents=True, exist_ok=True)
    path = scratch / 'screen-in.bin'
    path.write_bytes(screen)
    if manifest.get('synthetic'):
        from native import synth
        return synth.oracle(directory, manifest, screen, scratch)
    state = refcapture.run_call(title.MACHINE, directory, manifest, scratch,
                                [(E1_SCREEN, path), (BUFFER, path)])
    if state['end']['reason'] != 'return':
        raise RuntimeError('ref816 --call did not return: %s' % state['end'])
    return state['screen']


def compare(screen: bytes, truth: bytes, limit: int = 8) -> Dict:
    differ = [i for i in range(L.SCREEN_SIZE) if screen[i] != truth[i]]
    return {'differing_bytes': len(differ),
            'first': ['$%04X row %d col %d: $%02X, truth $%02X' % (
                L.SCREEN + i, i // L.ROW_BYTES, i % L.ROW_BYTES, screen[i],
                truth[i]) for i in differ[:limit]]}


def check_run(run: a2run.Run, batches: int, truth: bytes,
              stores: Optional[int] = None) -> Dict:
    """The checks of one run. stores: the screen stores upstream makes
    (loader.screen_stores), or None not to check them."""
    out = {'ended': run.ended()}
    if out['ended'] != 'halt':
        out['ok'] = False
        return out
    screen = run.screen(batches)
    out.update(compare(screen, truth))
    out['screen_crc'] = '%08X' % crc(screen)
    out['truth_crc'] = '%08X' % crc(truth)
    stray, shown, switches = 0, [], []
    shr = other_video = 0
    for k in range(batches):
        before = run.snapshots['before%d' % k]
        after = run.snapshots['after%d' % k]
        count, first = a2run.stray_writes(
            before.ram, after.ram, a2run.allowed_offsets(before.state['sp']))
        stray += count
        shr += after.state['shr_writes'] - before.state['shr_writes']
        other_video += (after.state['video_writes'] -
                        before.state['video_writes']) - \
            (after.state['shr_writes'] - before.state['shr_writes'])
        shown += ['call %d: %s' % (k, s) for s in first]
        switches += ['call %d: %s' % (k, s) for s in
                     a2run.switch_changes(before.state, after.state)]
        if after.state['sp'] != before.state['sp']:
            switches.append('call %d: S $%02X -> $%02X' % (
                k, before.state['sp'], after.state['sp']))
    out['stray_writes'] = stray
    out['stray_first'] = shown[:8]
    logged = logged_strays(run, batches)
    if logged is not None:
        out['stray_logged'] = len(logged)
        out['stray_logged_first'] = logged[:8]
    out['switch_changes'] = switches
    out['shr_writes'] = shr
    out['stores_expected'] = stores
    out['other_video_writes'] = other_video
    out['ms'] = round(run.replay_ms(), 3) if run.cost else None
    out['ok'] = (out['differing_bytes'] == 0 and stray == 0 and
                 not out.get('stray_logged') and
                 not switches and other_video == 0 and
                 (stores is None or shr == stores))
    return out


def logged_strays(run: a2run.Run, batches: int) -> Optional[List[str]]:
    """The writes of the write log (a2run.stray_ranges) made during a call
    of the replay, from the snapshot before it to the one after it, by
    the machine's clock; None when the run has no log."""
    if run.writes is None:
        return None
    windows = [(k, run.snapshots['before%d' % k].state['cycles'],
                run.snapshots['after%d' % k].state['cycles'])
               for k in range(batches)]
    out = []
    for w in run.writes:
        for k, start, end in windows:
            if start <= w.clock <= end:
                out.append('call %d: %s' % (k, w.describe()))
    return out


def check_frame(directory: Path, out: Path, build: loader.Build,
                keep: bool = False, units: Optional[Dict] = None) -> Dict:
    directory = Path(directory)
    work = out / directory.name
    if work.exists():
        shutil.rmtree(str(work))
    work.mkdir(parents=True)
    capture = loader.read_capture(directory, units)
    manifest = capture.manifest
    result = {'name': directory.name, 'ok': False}
    try:
        package = loader.build_package(capture, build,
                                       fill=L.FILL_CAPTURED)
        batches = len(package.batches)
        stores = package.counts['screen_stores']
        result['records'] = package.counts
        result['batch_columns'] = [[b.first, b.end] for b in package.batches]
        image = work / 'captured.img'
        image.write_bytes(package.image)

        captured_screen = loader.screen_bytes(capture)
        truth = (directory / 'screen-after.bin').read_bytes()
        run = a2run.run(image, build.labels, work / 'captured', batches,
                        snapshots=True, profile='f121',
                        write_log=a2run.stray_ranges())
        result['captured'] = check_run(run, batches, truth, stores)

        poison = poisoned(captured_screen)
        poison_truth = truth_on(directory, manifest, poison,
                                work / 'oracle')
        package_p = loader.build_package(capture, build, poison,
                                         fill=L.FILL_POISONED)
        image_p = work / 'poisoned.img'
        image_p.write_bytes(package_p.image)
        run = a2run.run(image_p, build.labels, work / 'poisoned', batches,
                        snapshots=True, profile='f121',
                        write_log=a2run.stray_ranges())
        result['poisoned'] = check_run(run, batches, poison_truth, stores)
        result['poisoned']['truth_changed_from_poison'] = sum(
            1 for i in range(L.PIXELS) if poison_truth[i] != poison[i])

        run = a2run.run(image, build.labels, work / 'fastpath', batches,
                        profile='fastpath')
        result['fastpath_ended'] = run.ended()
        result['ms_f121'] = result['captured'].get('ms')
        result['ms_fastpath'] = round(run.replay_ms(), 3) \
            if run.ended() == 'halt' else None
        result['screen_bytes_written'] = manifest.get('screen', {}).get(
            'written_pixels')
        result['ok'] = (result['captured']['ok'] and
                        result['poisoned']['ok'] and
                        result['fastpath_ended'] == 'halt')
    except (loader.LoadError, RuntimeError) as error:
        result['error'] = str(error)
    if not keep:        # (8.4 MB each; the write logs up to 2 MB)
        for path in (list(work.rglob('*.ram')) + list(work.glob('*.img')) +
                     list(work.rglob('writes.log'))):
            path.unlink()
    return result


def breakdown(directory: Path, out: Path, prof: loader.Build,
              units: Optional[Dict] = None, keep: bool = False) -> Dict:
    """walk, copy, draw milliseconds of the profiling build, both
    profiles."""
    capture = loader.read_capture(directory, units)
    package = loader.build_package(capture, prof)
    work = out / directory.name / 'breakdown'
    work.mkdir(parents=True, exist_ok=True)
    image = work / 'prof.img'
    image.write_bytes(package.image)
    parts = {}
    for profile in ('f121', 'fastpath'):
        run = a2run.run(image, prof.labels, work / profile,
                        len(package.batches), profile=profile)
        if run.ended() != 'halt':
            raise RuntimeError('the profiling build ended: %s' % run.ended())
        mhz = run.cost['fabric_mhz'] * 1000.0
        phases = run.cost['phases']
        parts[profile] = {name: round(phases[i] / mhz, 3) for i, name in
                          ((1, 'walk'), (2, 'copy'), (4, 'switch'),
                           (3, 'draw'))}
        parts[profile]['switch_writes'] = copy_switch_writes(package)
    if not keep:
        for path in [image] + list(work.rglob('*.ram')):
            path.unlink()
    return parts


def copy_switch_writes(package: loader.Package) -> int:
    """The soft-switch writes of the gather's copies (src/native/replay.s
    run_descriptors): for each group of at most MAXDESC descriptors, RAMRD
    on, one $C073 write for each texel bank the group copies from, $C073
    back to 0, RAMRD off."""
    return sum(3 + banks for banks in loader.copy_groups(package))


def frame_dirs(arguments: List[str]) -> List[Path]:
    if arguments:
        return [Path(a) for a in arguments]
    if not CAPTURES.is_dir():
        return []
    return sorted(p for p in CAPTURES.iterdir()
                  if (p / 'manifest.json').exists())


def line(r: Dict) -> str:
    if 'error' in r:
        return '%-10s ERROR %s' % (r['name'], r['error'])
    c, p = r['captured'], r['poisoned']
    return ('%-15s %s  records %4d (%5d B, %d batch%s, %d strip%s)  '
            'differing %d / %d  stray %d / %d (logged %d / %d)  '
            'stores %d / %d of %d  f121 %6.2f ms  fastpath %6.2f ms' % (
                r['name'], 'ok  ' if r['ok'] else 'FAIL',
                sum(r['records'][k] for k in ('K_TEX', 'K_FILL', 'K_TEXC',
                                              'K_FUZZ', 'K_OVL')),
                r['records']['bytes'], r['records']['batches'],
                'es' if r['records']['batches'] > 1 else '',
                r['records']['strips'],
                's' if r['records']['strips'] > 1 else '',
                c.get('differing_bytes', -1), p.get('differing_bytes', -1),
                c.get('stray_writes', -1), p.get('stray_writes', -1),
                c.get('stray_logged', -1), p.get('stray_logged', -1),
                c.get('shr_writes', -1), p.get('shr_writes', -1),
                r['records'].get('screen_stores', -1),
                r['ms_f121'] or 0.0, r['ms_fastpath'] or 0.0))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('dirs', nargs='*')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--json', type=Path)
    parser.add_argument('--keep', action='store_true',
                        help='keep the images and snapshots (8.4 MB '
                        'each)')
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--breakdown', action='store_true',
                        help='also time the walk, copies and draw')
    parser.add_argument('--obj', type=Path, default=loader.OBJ,
                        help='the build (make -C src/native OUT=DIR)')
    args = parser.parse_args(argv)
    if not a2run.A2VM.exists():
        print('%s is missing: make -C tools/a2vm' % a2run.A2VM,
              file=sys.stderr)
        return 1
    if not title.MACHINE.exists():
        print('%s is missing: make -C tools/ref816' % title.MACHINE,
              file=sys.stderr)
        return 1
    dirs = frame_dirs(args.dirs)
    if not dirs:
        print('no frames: run python3 tools/ref816/capture.py',
              file=sys.stderr)
        return 1
    try:
        os.nice(10)
    except OSError:
        pass
    build = loader.read_build(args.obj)
    units = loader.load_units()
    jobs = max(1, min(args.jobs, 4))
    with ThreadPoolExecutor(jobs) as pool:
        results = list(pool.map(
            lambda d: check_frame(d, args.out, build, args.keep, units),
            dirs))
    if args.breakdown:
        prof = loader.read_build(args.obj, name='prof')
        with ThreadPoolExecutor(jobs) as pool:
            parts = list(pool.map(
                lambda d: breakdown(d, args.out, prof, units, args.keep),
                dirs))
        for r, part in zip(results, parts):
            r['breakdown'] = part
    if not args.quiet:
        for r in results:
            print(line(r))
            if 'breakdown' in r:
                print('    ' + '   '.join(
                    '%s: walk %.2f, copy %.2f, switches %.2f, draw %.2f '
                    'ms' % (profile, p['walk'], p['copy'], p['switch'],
                            p['draw'])
                    for profile, p in r['breakdown'].items()) +
                    '   (%d switch writes, %d texel bytes copied)' % (
                        r['breakdown']['f121']['switch_writes'],
                        r['records']['copy_bytes']))
            for run in ('captured', 'poisoned'):
                for text in (r.get(run, {}).get('first', []) +
                             r.get(run, {}).get('stray_first', []) +
                             r.get(run, {}).get('stray_logged_first', []) +
                             r.get(run, {}).get('switch_changes', [])):
                    print('    %s: %s' % (run, text))
                if r.get(run, {}).get('other_video_writes'):
                    print('    %s: %d video writes outside the SHR screen'
                          % (run, r[run]['other_video_writes']))
    if args.json:
        args.json.write_text(json.dumps(results, indent=1) + '\n')
    failed = [r['name'] for r in results if not r['ok']]
    print('%d frames, %d passed%s' % (len(results), len(results) -
                                      len(failed), (': FAILED ' + ', '.join(
                                          failed)) if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
