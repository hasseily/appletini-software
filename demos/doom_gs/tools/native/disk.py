#!/usr/bin/env python3
"""The card run of the native replay: a bootable ProDOS disk.

Usage:  python3 tools/native/disk.py [DIR ...] [--out FILE] [--reps N]
                                     [--wait N] [--check] [--profile P]

With no DIR, every frame of build/captures/. Builds build/native/
REPLAY.hdv (or --out), a ProDOS volume REPLAY made with the existing
port's disk writer (demos/doom/tools/build_disk.py: the boot blocks and
PRODOS of appletini-one's ProDOS_2_4_3.po), holding:

  REPLAY.SYSTEM   src/native/runner.s: card.boot then card.lc of the build
  CATALOG         the frames: their files, names, expected CRCs, banks
  F01 ...         one file a frame: records of bank, address, length and
                  bytes for RamWorks banks. Frame k (from 0) has its
                  texels in banks 1 + 7k .. 4 + 7k, its records in 5 + 7k,
                  a copy of its main $0200-$5FFF in 6 + 7k and of its aux 0
                  (the drawers, their tables, the screen) in 7 + 7k: the
                  a2vm image of tools/native/loader.py with --bank-base
                  1 + 7k, the main and aux-0 parts moved into banks. The
                  runner loads main's colormaps and tables and aux 0's
                  drawers and tables from those copies by memory-API
                  PRIVATE copies, the rest by CPU (src/native/runner.s)

On the card (8 MB RamWorks, the Appletini's mouse card in slot 2, its
memory API in slot 7: F1.1.4 or later), boot
the disk: it loads, then shows each frame for --wait VBLs after one run
of the replay, runs it --reps more times (default 200), then the same
loop without the replay, and ends on a table: each frame's CRC-32 of aux
0 $2000-$9FFF, OK when it equals the reference's (tools/ref816 on the
IIgs release), and milliseconds a run at 50 Hz: the loop with the replay,
the loop without it, and their difference, the replay's time (VBLs * 20
ms / --reps, rounded to 0.1 ms: at 200 runs one VBL is 0.1 ms a run; at
NTSC multiply by 0.834). A key runs them all again.

--check runs the disk's own REPLAY.SYSTEM on a2vm, its MLI trap serving
the files and its memory API (--amem) the PRIVATE copies, under the cost
model (--profile, default f121) on the model's clock, to the table; it
prints each frame's CRC, whether it equals the expected one, and both
loops' VBL counts and times, to compare with the harness's time (tools/
native/replay_check.py). Every interrupt is held to the game's
contract (docs/MEMORY_MAP.md rule 2: zero page $D8-$FF, the stack,
$E000-$FFFF, the mouse card; a2vm --irq-bounds). The first frame's
restore is checked with snapshots before and after it: no CPU store to a
write-expensive page but aux 0's screen (rule 3: a2vm's video writes less
its SHR writes), main $0878-$087F unchanged (rule 8), and the PRIVATE
copies made. It exits 1 unless every CRC is OK, the restore passes,
the runner's table shows the times, and the loop with the replay took
more VBLs than the loop without it (a base loop that still calls the
replay would read as a replay of about 0 ms; check_failures).
"""

import argparse
import importlib.util
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Dict, List, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from a2vm import costs  # noqa: E402
from native import a2run, loader, layout as L  # noqa: E402
from ref816 import bounded  # noqa: E402

DOOM_TOOLS = ROOT.parent / 'doom' / 'tools'
OUT = ROOT / 'build' / 'native' / 'REPLAY.hdv'
VOLUME = 'REPLAY'
SYSTEM = 'REPLAY.SYSTEM'
BANKS_A_FRAME = 7
MAIN_COPY = 5                   # bank base + 5: main $0200-$5FFF
AUX_COPY = 6                    # bank base + 6: aux 0
CAT_FIRST, CAT_ENTRY, MAX_FRAMES = 4, 48, 20
MAIN_SPAN = (0x0200, 0x6000)
AUX_SPANS = ((0x0200, 0x0400), (0x0800, 0x0C00), (0x2000, 0xA000))
REPS = 200                      # timed runs a frame: 0.1 ms a VBL a run
WAIT = 150                      # VBLs each frame is shown
# The bounds of the a2vm check: card seconds (the machine's clock, 133.33
# million fabric clocks a second) for a frame's load, its showing and each
# timed run (the heaviest synthetic stream takes 0.12 s a run, the loop
# without the replay about 0.003), and host seconds for the whole run.
RUN_S, FRAME_S, FABRIC_HZ = 0.25, 5.0, 133_333_333
CHECK_TIMEOUT = 3600


def disk_writer():
    """demos/doom/tools/build_disk.py, the existing port's writer."""
    path = DOOM_TOOLS / 'build_disk.py'
    spec = importlib.util.spec_from_file_location('doom_build_disk', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def image_records(image: bytes) -> List[Tuple[int, int, int, bytes]]:
    """(kind, bank, address, bytes) of an A2VMIMG1 image."""
    out, at = [], 8
    while at < len(image):
        kind, bank, address, length = struct.unpack_from('<BBHI', image, at)
        at += 8
        out.append((kind, bank, address, image[at:at + length]))
        at += length
    return out


def frame_file(package: loader.Package, build: loader.Build,
               base: int) -> bytes:
    """The frame's records for the boot code: bank, address (2), length
    (2), the bytes; then a record of length 0."""
    main = bytearray(0x10000)
    aux0 = bytearray(0x10000)
    out = bytearray()
    for kind, bank, address, data in image_records(package.image):
        if kind == loader.ImageWriter.LC:
            if data != build.lc:
                raise ValueError('the image\'s card is not the card build')
        elif kind == loader.ImageWriter.MAIN:
            main[address:address + len(data)] = data
        elif kind == loader.ImageWriter.AUX and bank == 0:
            aux0[address:address + len(data)] = data
        elif kind == loader.ImageWriter.AUX:
            out += record(bank, address, data)
        else:
            raise ValueError('an image record of kind %d' % kind)
    out += record(base + MAIN_COPY, MAIN_SPAN[0],
                  bytes(main[MAIN_SPAN[0]:MAIN_SPAN[1]]))
    for start, end in AUX_SPANS:
        out += record(base + AUX_COPY, start, bytes(aux0[start:end]))
    return bytes(out + bytes(5))


def record(bank: int, address: int, data: bytes) -> bytes:
    out = bytearray()
    for at in range(0, len(data), 0xFF00):      # lengths are 16 bits
        piece = data[at:at + 0xFF00]
        out += struct.pack('<BHH', bank, address + at, len(piece)) + piece
    return bytes(out)


class Frame:
    def __init__(self, directory: Path, package: loader.Package, base: int,
                 data: bytes, crc: int):
        self.directory, self.package, self.base = directory, package, base
        self.data, self.crc = data, crc
        self.name = directory.name


def prepare(dirs: List[Path], build: loader.Build) -> List[Frame]:
    if len(dirs) > MAX_FRAMES:
        raise ValueError('at most %d frames' % MAX_FRAMES)
    units = loader.load_units()
    frames = []
    for k, directory in enumerate(dirs):
        base = 1 + BANKS_A_FRAME * k
        if base + BANKS_A_FRAME - 1 > 126:
            raise ValueError('frame %d needs RamWorks bank %d' % (
                k, base + BANKS_A_FRAME - 1))
        capture = loader.read_capture(directory, units)
        package = loader.build_package(capture, build, bank_base=base)
        truth = (directory / 'screen-after.bin').read_bytes()
        frames.append(Frame(directory, package, base,
                            frame_file(package, build, base),
                            zlib.crc32(truth) & 0xffffffff))
    return frames


def catalog(frames: List[Frame], reps: int, wait: int) -> bytes:
    out = bytearray((len(frames), reps, wait, 0))
    for k, f in enumerate(frames):
        name = 'F%02d' % (k + 1)
        entry = bytearray(CAT_ENTRY)
        entry[0] = len(name)
        entry[1:1 + len(name)] = name.encode('ascii')
        shown = f.name.upper()[:12].ljust(12).encode('ascii')
        entry[16:28] = shown
        entry[28:32] = f.crc.to_bytes(4, 'little')
        entry[32] = f.base
        out += entry
    return bytes(out)


HOLE_SENTINEL = bytes(range(0xB0, 0xB8))
A2LI = bytes((0xC1, 0xB2, 0xCC, 0xE9))    # 'A2Li' | $80 (docs/MEMORY_MAP.md
                                            #   rule 8)


def system_file(obj: Path) -> bytes:
    boot = (obj / 'card.boot').read_bytes()
    lc = (obj / 'card.lc').read_bytes()
    if len(boot) != 0x800 or len(lc) != 0x3000:
        raise ValueError('card.boot is 2 KB and card.lc 12 KB')
    data = boot + lc
    # ProDOS loads the file at $2000 with CPU stores, so its bytes at
    # $4078 reach the firmware's shadow of main: never its A2Li signature
    if data[0x4078 - 0x2000:0x407C - 0x2000] == A2LI:
        raise ValueError('REPLAY.SYSTEM holds the A2Li signature at $4078')
    return data


def files_of(frames: List[Frame], obj: Path, reps: int, wait: int
             ) -> List[Tuple[str, int, int, bytes]]:
    out = [(SYSTEM, 0xFF, 0x2000, system_file(obj)),
           ('CATALOG', 0x06, 0x0000, catalog(frames, reps, wait))]
    for k, f in enumerate(frames):
        out.append(('F%02d' % (k + 1), 0x06, 0x0000, f.data))
    return out


def build_disk(files, output: Path) -> None:
    bd = disk_writer()
    bd.VOLUME_NAME = VOLUME         # (this copy of the module only: its
    master = bd.DEFAULT_MASTER      #   check reads the name from there)
    if not master.is_file():
        raise FileNotFoundError('%s is missing (appletini-one\'s ProDOS; '
                                'set APPLETINI_ROOT)' % master)
    boot, prodos = bd.extract_prodos(master)
    everything = [(SYSTEM,) + files[0][1:],
                  ('PRODOS', bd.FILE_TYPE_SYS, 0x0000, prodos)] + files[1:]
    # ProDOS runs the first *.SYSTEM file of the volume directory
    writer = bd.VolumeWriter(VOLUME, bd.volume_size([f[3] for f in
                                                     everything]))
    writer.set_boot_blocks(boot)
    for name, file_type, aux, data in everything:
        writer.add_file(name, data, file_type, aux)
    image = writer.finish()
    expected = {name: (t, aux, data) for name, t, aux, data in everything}
    bd.verify_image(image, expected, order=[f[0] for f in everything])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(image)


# ---------------------------------------------------------------------------
# the check on a2vm
# ---------------------------------------------------------------------------

def check(frames: List[Frame], files, obj: Path, work: Path,
          profile: str) -> List[Dict]:
    work = work.resolve()
    listing = next(data for name, _, _, data in files if name == 'CATALOG')
    reps, wait = listing[1], listing[2]
    work.mkdir(parents=True, exist_ok=True)
    labels = loader.read_labels(obj / 'card.lbl')
    (work / 'events.txt').write_text(
        'pc %X snapshot restore0\npc %X snapshot restore1\n' % (
            labels['run_restore'], labels['run_restored']))
    manifest = []
    for name, file_type, aux, data in files:
        path = work / name
        path.write_bytes(data)
        manifest.append('%s %02X %04X %s' % (name, file_type, aux, path))
    (work / 'prodos.txt').write_text('\n'.join(manifest) + '\n')
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    # a sentinel in main $0878-$087F, which nothing may write (rule 8): a
    # CPU copy of the frame's main copy (zero there) would change it
    (work / 'hole.bin').write_bytes(HOLE_SENTINEL)
    (work / 'cost.txt').write_text(costs.text(profile))
    args = [str(a2run.A2VM), '--rom', str(work / 'rom.bin'),
            '--core', 'w65c02s', '--amem',
            '--prodos', str(work / 'prodos.txt'),
            '--volume', VOLUME, '--launched', SYSTEM,
            '--load', '2000:%s' % (work / SYSTEM),
            '--load', '0878:%s' % (work / 'hole.bin'),
            '--reg', 'pc=2000', '--reg', 's=FF',
            '--cost', str(work / 'cost.txt'), '--cost-timed',
            '--idle', '%X:vbl' % labels['run_wait'],
            # the IRQ contract of docs/MEMORY_MAP.md rule 2, checked on
            # every interrupt (many land inside the replay)
            '--irq-bounds', '00D8-01FF,C0A0-C0AF,E000-FFFF',
            '--stop-pc', '%X' % labels['run_key'],
            '--stop-pc', '%X' % labels['run_crash'],
            '--cycles', str(check_cycles(len(frames), reps, wait)),
            '--snapshot-dir', str(work), '--final-snapshot',
            '--input', str(work / 'events.txt'),
            '--state', str(work / 'state.json')]
    result = bounded.run(args, timeout=CHECK_TIMEOUT, max_bytes=1 << 30,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         universal_newlines=True)
    state = json.loads((work / 'state.json').read_text())
    if state['end'] != 'stop-pc' or state['pc'] != labels['run_key']:
        raise RuntimeError('the card run ended with %s at $%04X: %s' % (
            state['end'], state['pc'], result.stdout[-500:]))
    restore = restore_check(work)
    ram = (work / 'final.ram').read_bytes()
    results = labels['results']
    out = []
    for k, f in enumerate(frames):
        at = a2run.LC + results - 0xC000 + 8 * k
        crc = int.from_bytes(ram[at:at + 4], 'little')
        with_replay = int.from_bytes(ram[at + 4:at + 6], 'little')
        without = int.from_bytes(ram[at + 6:at + 8], 'little')
        out.append({'name': f.name, 'crc': '%08X' % crc,
                    'expected': '%08X' % f.crc,
                    'ok': crc == f.crc and restore['ok'],
                    'restore': restore,
                    'vbls': with_replay - without,
                    'vbls_loop': with_replay, 'vbls_without': without,
                    'ms_loop': run_ms(with_replay, reps),
                    'ms_without': run_ms(without, reps),
                    'ms': run_ms(max(0, with_replay - without), reps),
                    'timed_ok': with_replay > without})
    screen = text_screen(ram)
    (work / 'screen.txt').write_text('\n'.join(screen) + '\n')
    (work / 'final.ram').unlink()
    # the runner's own arithmetic: row 2 + k of its table shows frame k's
    # LOOP, BASE and REPLAY, which must be run_ms of its VBL counts
    for k, r in enumerate(out):
        fields = screen[2 + k].split() if 2 + k < len(screen) else []
        try:
            r['shown'] = [float(x) for x in fields[-3:]]
        except ValueError:
            r['shown'] = []
        r['shown_ok'] = r['shown'] == [r['ms_loop'], r['ms_without'],
                                       r['ms']]
    return out


def check_failures(results: List[Dict]) -> List[str]:
    """What makes --check fail, one line a problem (empty: it passes): a
    CRC or the restore wrong, the runner's table not showing its VBL
    counts' times, or a loop with the replay no slower than the loop
    without it."""
    out = []
    for r in results:
        if not r['ok']:
            out.append('%s: CRC %s, expected %s, restore %s' % (
                r['name'], r['crc'], r['expected'],
                'OK' if r['restore']['ok'] else 'WRONG'))
        if not r['shown_ok']:
            out.append('%s: the runner\'s table shows %s, not %s' % (
                r['name'], r['shown'],
                [r['ms_loop'], r['ms_without'], r['ms']]))
        if r['vbls_without'] >= r['vbls_loop']:
            out.append('%s: the loop without the replay took %d VBLs, the '
                       'loop with it %d: the base loop calls the replay, '
                       'or the replay does nothing' % (
                           r['name'], r['vbls_without'], r['vbls_loop']))
    return out


def check_cycles(frames: int, reps: int, wait: int) -> int:
    """The a2vm check's cycle bound (--cost-timed: fabric clocks)."""
    seconds = frames * (FRAME_S + wait * 0.02 + 2 * reps * RUN_S)
    return int(seconds * FABRIC_HZ)


def run_ms(vbls: int, reps: int) -> float:
    """Milliseconds a run at 50 Hz, as the runner shows them: VBLs * 20
    / REPS rounded to 0.1 (src/native/runner.s tenths), at most 999.9."""
    tenths = (vbls * 200 + reps // 2) // reps
    return min(tenths, 9999) / 10.0


def restore_check(work: Path) -> Dict:
    """The first frame's restore, from the snapshots around it: its video
    writes outside aux 0's screen (none may be: docs/MEMORY_MAP.md rule
    3), main $0878-$087F (never written: rule 8), the memory-API requests
    it made (one) and main $4078-$407F after it (the colormap, which only
    that request can have put there)."""
    shots = [a2run.read_snapshot(work, name)
             for name in ('restore0', 'restore1')]
    before, after = (s.state for s in shots)
    other = (after['video_writes'] - before['video_writes']) - \
        (after['shr_writes'] - before['shr_writes'])
    hole = [shots[i].ram[a2run.MAIN + 0x0878:a2run.MAIN + 0x0880]
            for i in (0, 1)]
    requests = after['amem']['requests'] - before['amem']['requests']
    out = {'other_video_writes': other,
           'hole_0878_kept': hole[0] == hole[1] == HOLE_SENTINEL,
           'amem_requests': requests,
           'main_4078': shots[1].ram[a2run.MAIN + 0x4078:
                                     a2run.MAIN + 0x4080].hex()}
    out['ok'] = other == 0 and out['hole_0878_kept'] and requests == 1
    for name in ('restore0', 'restore1'):
        for suffix in ('.ram', '.json'):
            (work / (name + suffix)).unlink()
    return out


def text_screen(ram: bytes) -> List[str]:
    """The 24 rows of the 40-column text page 1 (main $0400)."""
    rows = []
    for r in range(24):
        at = 0x0400 + (r % 8) * 0x80 + (r // 8) * 0x28
        rows.append(''.join(chr(b & 0x7F) if 0x20 <= (b & 0x7F) < 0x7F
                            else '?' for b in ram[at:at + 40]).rstrip())
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('dirs', nargs='*')
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--reps', type=int, default=REPS)
    parser.add_argument('--wait', type=int, default=WAIT)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--profile', default='f121')
    args = parser.parse_args(argv)
    if not 1 <= args.reps <= 255:
        parser.error('--reps is 1-255 (one byte of the catalog)')
    dirs = [Path(d) for d in args.dirs] or sorted(
        p for p in (ROOT / 'build' / 'captures').iterdir()
        if (p / 'manifest.json').exists())
    obj = loader.OBJ
    build = loader.read_build(obj, 'card')
    frames = prepare(dirs, build)
    files = files_of(frames, obj, args.reps, args.wait)
    build_disk(files, args.out)
    size = args.out.stat().st_size
    print('%s: %d frames, %d bytes (%d blocks)' % (args.out, len(frames),
                                                   size, size // 512))
    for k, f in enumerate(frames):
        print('  F%02d %-12s CRC %08X  banks %d-%d  %d bytes' % (
            k + 1, f.name, f.crc, f.base, f.base + BANKS_A_FRAME - 1,
            len(f.data)))
    if args.check:
        results = check(frames, files, obj, args.out.parent / 'disk-check',
                        args.profile)
        for r in results:
            print('  a2vm %-12s CRC %s %s  %d runs: loop %d VBLs %.1f ms, '
                  'base %d VBLs %.1f ms, replay %.1f ms a run' % (
                      r['name'], r['crc'], 'OK' if r['ok'] else
                      'DIFFERS from %s' % r['expected'], args.reps,
                      r['vbls_loop'], r['ms_loop'], r['vbls_without'],
                      r['ms_without'], r['ms']))
        wrong = [r['name'] for r in results if not r['shown_ok']]
        print('  the runner\'s table %s' % (
            'shows these times' if not wrong else
            'DIFFERS from them for ' + ', '.join(wrong)))
        print('  the first restore: %d video writes outside the screen, '
              '$0878-$087F %s, %d memory-API request%s' % (
                  results[0]['restore']['other_video_writes'],
                  'untouched' if results[0]['restore']['hole_0878_kept']
                  else 'WRITTEN', results[0]['restore']['amem_requests'],
                  '' if results[0]['restore']['amem_requests'] == 1
                  else 's'))
        print('  the text screen at the end (%s):' % (
            args.out.parent / 'disk-check' / 'screen.txt'))
        for text in (args.out.parent / 'disk-check' /
                     'screen.txt').read_text().splitlines():
            if text:
                print('    | ' + text)
        failures = check_failures(results)
        for line in failures:
            print('  FAILED ' + line)
        if failures:
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
