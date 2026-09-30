#!/usr/bin/env python3
"""Capture upstream's record replay (R_DrawLists) at chosen frames.

Usage:  python3 tools/ref816/capture.py [--out DIR] [--sets still,demo,e1m3]
                                        [--keep-raw] [--no-verify]

Makes the frame set of milestone 5 (docs/NATIVE.md section 13) in
build/captures/, one directory a frame:

    still-1 .. still-3   coverage/newgame.script, the first three frames
                         after the note "still" (standing in E1M1)
    demo-01 .. demo-11   coverage/title.script, eleven frames spread evenly
                         from the note "demo" to "demo-25s" (demo3, E1M7)
    e1m3-1               coverage/tour.script, the first frame after its
                         shot "e1m3" (a note "e1m3" is put after that line
                         of the script, which changes nothing of the run)

Each script runs twice on ref816 (run_script.py's checks both times). The
first run logs the calls of R_DrawLists (--mark) to choose them; the
second captures them (--capture, footprint.h), and must end with the
same RAM. A raw capture (entry.img: all RAM at the R_DrawLists entry;
reads.img and writes.img: the replay's footprint) is then distilled into
the files the replay reads and writes, listed in manifest.json
(write_manifest below gives the format), and the raw files are deleted
(--keep-raw keeps them in DIR/raw/).

Unless --no-verify, each frame is then checked with --call: upstream's
R_DrawLists, run alone on the distilled state (context.img and the
"before" files), must write exactly the bytes of writes.img, leave
screen-after.bin and buffer-after.bin, and take the instructions and
cycles of the capture. The result goes into the manifest ("verified").
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import bounded, lists, make_image, marks, refimage, \
    run_script, script, title  # noqa: E402

CAPTURES = make_image.BUILD / 'captures'
FORMAT = 'ref816-replay-capture 1'
ENTRY = 'r_list65.s:R_DrawLists'
FLUSH = 'r_list65.s:drawAllL'
GAMETIC = 'g_game65.s:_g_gametic'
SCREEN = 0xe12000
BUFFER = 0x012000
SCREEN_SIZE = 0x8000
PIXELS = 0x7d00                 # $2000-$9CFF: 200 rows of 160 bytes
VIEW_ROWS = 168
ROW = 160


class Selection(NamedTuple):
    key: str
    script: str
    start: str                  # the note after which frames are chosen
    end: Optional[str]          # and before which (None: the first `count`)
    count: int
    note_after: Optional[str]   # put "note START" after the line with this


SETS = (
    Selection('still', 'newgame', 'still', None, 3, None),
    Selection('demo', 'title', 'demo', 'demo-25s', 11, None),
    Selection('e1m3', 'tour', 'e1m3', None, 1, 'shot e1m3'),
)


class Region(NamedTuple):
    name: str
    address: int
    size: int
    what: str


# ---- the script and the choice of frames ----

def program_for(selection: Selection, symbols: script.Symbols) -> str:
    path = run_script.script_path(selection.script)
    text = path.read_text()
    if selection.note_after:
        lines = text.splitlines()
        found = [i for i, line in enumerate(lines)
                 if re.search(r'\b%s\b' % re.escape(selection.note_after),
                              line.split('#')[0])]
        if len(found) != 1:
            raise ValueError('%s: %d lines with "%s"' % (
                path.name, len(found), selection.note_after))
        lines.insert(found[0] + 1, 'note %s' % selection.start)
        text = '\n'.join(lines) + '\n'
    return script.compile_script(text, symbols, path.name)


class Hit(NamedTuple):
    hit: int                    # the call of R_DrawLists, from 1
    mark: marks.Entry
    flushes: int                # calls of drawAllL since the call before


def calls(log: Sequence[marks.Entry], entry: int, flush: int
          ) -> Tuple[List[Hit], Dict[str, int]]:
    """Every call of R_DrawLists in the log, and for each note the
    number of calls before it."""
    hits, before, flushes = [], {}, 0
    entry_name, flush_name = '%06X' % entry, '%06X' % flush
    for e in log:
        if e.kind == 'note':
            before[e.what] = len(hits)
        elif e.kind == 'mark' and e.what == flush_name:
            flushes += 1
        elif e.kind == 'mark' and e.what == entry_name:
            hits.append(Hit(len(hits) + 1, e, flushes))
            flushes = 0
    return hits, before


def choose(selection: Selection, hits: Sequence[Hit],
           before: Dict[str, int]) -> List[Hit]:
    """The frames of the selection. The last call of the run is never
    one: the run can end before it returns."""
    hits = hits[:-1]
    if selection.start not in before:
        raise ValueError('no note %s in the run' % selection.start)
    first = before[selection.start]
    if selection.end is None:
        chosen = list(hits[first:first + selection.count])
    else:
        if selection.end not in before:
            raise ValueError('no note %s in the run' % selection.end)
        inside = hits[first:before[selection.end]]
        n = len(inside)
        if n < selection.count:
            chosen = list(inside)
        else:
            chosen = [inside[round(i * (n - 1) / (selection.count - 1))]
                      for i in range(selection.count)]
    if len(chosen) < selection.count:
        raise ValueError('%s: %d frames, not %d' % (
            selection.key, len(chosen), selection.count))
    return chosen


# ---- the regions the replay reads ----

def regions(units: Dict) -> List[Region]:
    """The named "before" regions, all from the link map."""
    u = units['r_list65.s']
    lay = lists.layout(units)
    found = []
    for page, count in lists.record_pages(lay):
        found.append(Region(
            'records-%02x' % page, lay.recbase + (page << 8), count << 8,
            'the column records (lists.inc): pages $%02X-$%02X of bank $%02X'
            % (page, page + count - 1, lay.recbase >> 16)))
    end_lists = u['colOrder'] + 2 * lay.columns
    found.append(Region('lists', u['COLW'], end_lists - u['COLW'],
                        'COLW (the end of each column list), XPNEXT, '
                        'colOrder (r_list65.s)'))
    found.append(Region('screen', SCREEN, SCREEN_SIZE,
                        'the SHR screen: pixels $E1:2000-$9CFF, SCBs '
                        '$9D00-$9DFF, palettes $9E00-$9FFF'))
    found.append(Region('buffer', BUFFER, SCREEN_SIZE,
                        'bank $01 $2000-$9FFF, where the drawers write '
                        '(with SHR shadowing on, also to $E1)'))
    stride = u['FS_EVEN'] - u['FS_ROW']
    found.append(Region('spans', u['FS_ROW'],
                        u['CV_REC'] + stride - u['FS_ROW'],
                        'fill spans FS_ROW, FS_EVEN, FS_ODD, FS_STAMP and '
                        'covered ranges CV_ROW, CV_REC (lists.inc)'))
    found.append(Region('weapon', u['WCLIP'],
                        u['WTMP'] + 2 * lay.columns - u['WCLIP'],
                        'weapon skip WCLIP, WPREV, WTMP (lists.inc)'))
    maps = units['drawcol.s']
    size = maps['iigs_shrcmapB'] - maps['iigs_shrcmapA']
    found.append(Region('colormaps', maps['iigs_shrcmapA'], 2 * size,
                        'iigs_shrcmapA and iigs_shrcmapB (drawcol.s)'))
    # The shadow drawer (fuzzColumn, r_sprite65.s) darkens each screen
    # byte it reads through this table; a replay on another screen reads
    # other entries, so all 256 are kept (i_viigs65.s fills 256).
    found.append(Region('fuzz', units['i_viigs65.s']['FUZZ_DARKEN'], 256,
                        'FUZZ_DARKEN (i_viigs65.s): the darker colour of '
                        'each screen byte, read by the shadow drawer'))
    return found


def subtract(spans: Sequence[Tuple[int, int]],
             taken: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """(start, end) spans less the (start, end) spans of `taken`."""
    out = []
    for start, end in spans:
        pieces = [(start, end)]
        for t0, t1 in taken:
            pieces = [p for a, b in pieces
                      for p in ((a, min(b, t0)), (max(a, t1), b))
                      if p[0] < p[1]]
        out += pieces
    return out


# ---- distilling a raw capture ----

def bank_counts(runs: Sequence[Tuple[int, bytes]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for address, data in runs:
        key = '%02X' % (address >> 16)
        counts[key] = counts.get(key, 0) + len(data)
    return dict(sorted(counts.items()))


def file_entry(name: str, filename: str, what: str, when: str,
               data: bytes, address: Optional[int] = None,
               ranges: Optional[List[Tuple[int, int]]] = None) -> Dict:
    entry = {'name': name, 'file': filename, 'when': when, 'what': what,
             'format': 'raw' if address is not None else 'image',
             'size': len(data) if ranges is None
             else sum(length for _, length in ranges),
             'sha256': hashlib.sha256(data).hexdigest()}
    if address is not None:
        entry['address'] = address
        entry['at'] = '$%02X:%04X' % (address >> 16, address & 0xffff)
    if ranges is not None:
        entry['ranges'] = [[a, n] for a, n in ranges]
    return entry


def screen_counts(before: bytes, after: bytes) -> Dict[str, int]:
    changed = [i for i in range(SCREEN_SIZE) if before[i] != after[i]]
    return {'changed': len(changed),
            'changed_view': sum(1 for i in changed
                                if i < VIEW_ROWS * ROW),
            'changed_pixels': sum(1 for i in changed if i < PIXELS),
            'changed_scb_palettes': sum(1 for i in changed if i >= PIXELS)}


def distill(raw: Path, out: Path, units: Dict, info: Dict) -> Dict:
    """The capture directory `out` from the raw capture `raw`; returns
    its manifest (also written to out/manifest.json)."""
    if out.exists():
        shutil.rmtree(str(out))
    out.mkdir(parents=True)
    call = json.loads((raw / 'call.json').read_text())
    entry_image = refimage.read(raw / 'entry.img')
    reads_image = refimage.read(raw / 'reads.img')
    writes_data = (raw / 'writes.img').read_bytes()
    writes_image = refimage.parse(writes_data)
    exit_image = refimage.read(raw / 'exit.img')
    memory = refimage.load(entry_image)
    lay = lists.layout(units)
    files = []
    problems = []

    named = regions(units)
    for region in named:
        data = memory.get(region.address, region.size)
        (out / (region.name + '.bin')).write_bytes(data)
        files.append(file_entry(region.name, region.name + '.bin',
                                region.what, 'before', data,
                                address=region.address))
    taken = [(r.address, r.address + r.size) for r in named]

    records = list(lists.walk(memory.get, lay))
    counts = lists.summary(records, lay)
    colormap_pages = sorted(set(
        r.field(lay, 'R_CMP') for r in records if r.kind == 'K_TEX'))
    texel_spans = subtract([(a, a + n) for a, n in
                            lists.texel_ranges(records)], taken)
    texel_runs = lists.merge(texel_spans)
    texel_records = [(a, memory.get(a, n)) for a, n in texel_runs]
    data = refimage.image_bytes(entry_image.registers,
                                entry_image.switches, texel_records)
    (out / 'texels.img').write_bytes(data)
    files.append(file_entry(
        'texels', 'texels.img', 'the texels of the K_TEX and K_TEXC '
        'records: %d bytes from each texel address (lists.inc R_TI is 7 '
        'bits), less the regions above' % lists.TEXEL_SPAN, 'before',
        data, ranges=texel_runs))
    taken += [(a, a + n) for a, n in texel_runs]

    # The rest of what the replay read first: its code, direct page,
    # stack, tables; with the values it read.
    mask = refimage.Memory()
    for a, b in taken:
        mask.put(a, bytes(b - a))
    context: List[Tuple[int, bytes]] = []
    differ = 0
    for address, data in reads_image.records:
        run = None
        for i, value in enumerate(data):
            at = address + i
            if mask.is_known(at):
                differ += memory.byte(at) != value
                run = None
            elif run is not None:
                run.append(value)
            else:
                run = bytearray([value])
                context.append((at, run))
    context = [(a, bytes(d)) for a, d in context]
    if differ:
        problems.append('%d bytes read first differ from the memory at '
                        'the entry' % differ)
    window = units['r_list65.s']
    window_banks = range(window['MM_WINDOW'], window['MM_WINDOW_END'])
    window_context = sum(len(d) for a, d in context
                         if (a >> 16) in window_banks)
    if window_context:
        problems.append('%d bytes of the level window read outside the '
                        'texels of the records' % window_context)
    data = refimage.image_bytes(entry_image.registers,
                                entry_image.switches, context)
    (out / 'context.img').write_bytes(data)
    files.append(file_entry(
        'context', 'context.img', 'everything else the replay read before '
        'writing it (code, direct page, stack, tables), with the values '
        'read, and the registers and soft switches at the entry: the '
        'image to run --call on', 'before', data,
        ranges=[(a, len(d)) for a, d in context]))

    after = refimage.Memory([(r.address, memory.get(r.address, r.size))
                             for r in named if r.name in ('screen',
                                                          'buffer')])
    for address, data in writes_image.records:
        after.put(address, data)
    for name, address in (('screen-after', SCREEN),
                          ('buffer-after', BUFFER)):
        data = after.get(address, SCREEN_SIZE)
        (out / (name + '.bin')).write_bytes(data)
        files.append(file_entry(
            name, name + '.bin', 'the %s after the replay' % name[:-6],
            'after', data, address=address))
    (out / 'writes.img').write_bytes(writes_data)
    files.append(file_entry(
        'writes', 'writes.img', 'every byte the replay wrote, with its value '
        'at the return, and the registers and soft switches at the return',
        'after', writes_data,
        ranges=[(a, len(d)) for a, d in writes_image.records]))

    # Bytes an interrupt inside the replay wrote after the replay did:
    # only the stack below S may be one.
    overwritten = [a + i for (a, d), (_, e) in zip(writes_image.records,
                                                  exit_image.records)
                   for i in range(len(d)) if d[i] != e[i]]
    stack = entry_image.registers.s
    if any(a >> 16 or a > stack for a in overwritten):
        problems.append('an interrupt inside the replay changed bytes it '
                        'wrote outside the stack: %s' % ', '.join(
                            '$%06X' % a for a in overwritten[:8]))

    screen_before = memory.get(SCREEN, SCREEN_SIZE)
    screen_after = after.get(SCREEN, SCREEN_SIZE)
    written_screen = sum(
        1 for a, d in writes_image.records for i in range(len(d))
        if SCREEN <= a + i < SCREEN + PIXELS)
    screen = screen_counts(screen_before, screen_after)
    screen['written_pixels'] = written_screen
    screen['buffer_equals_screen_before'] = (
        memory.get(BUFFER, PIXELS) == screen_before[:PIXELS])

    gametic = units['g_game65.s']['_g_gametic']
    manifest = {
        'format': FORMAT,
        'name': out.name,
        'script': info['script'],
        'note': call['note'],
        'hit': call['hit'],
        'frame': call['frame'],
        'seconds': call['clock'] / marks.MASTER_HZ,
        'cycles': call['cycles'],
        'gametic': memory.word(gametic, 4),
        'entry': {'symbol': ENTRY, 'address': call['entry']},
        'registers': entry_image.registers._asdict(),
        'switches': entry_image.switches._asdict(),
        'files': files,
        'records': dict(counts, extra_pages=(
            (memory.byte(lay.xpnext) or 0x100) - lay.xp_first),
            colormap_pages=colormap_pages),
        'early_flushes': info['flushes'],
        'replay': {k: call['call'][k] for k in (
            'instructions', 'cycles', 'interrupts', 'bytes_read',
            'bytes_written', 'io', 'rom_reads', 'unmapped_reads')},
        'returned': call['call']['returned'],
        'screen': screen,
        'context_by_bank': bank_counts(context),
        'written_by_bank': bank_counts(writes_image.records),
        'written_then_changed_by_interrupts': overwritten,
        'problems': problems,
    }
    if not call['call']['returned']:
        problems.append('the capture did not return')
    write_manifest(out, manifest)
    return manifest


def write_manifest(out: Path, manifest: Dict) -> None:
    """manifest.json: "format", the frame ("name", "script", "note",
    "hit": the call of R_DrawLists from 1, "frame": the video frame,
    "seconds" and "cycles" of machine time, "gametic"), "entry",
    "registers" and "switches" at the entry, and "files": each with its
    "name", "file", "when" (before or after the replay), "what",
    "format" (raw: "address" and "at" say where its "size" bytes go;
    image: a ref816 memory image whose records are "ranges", [address,
    length]), and "sha256". Then what was measured: "records" (counts by
    kind, bytes, extra pages, the colormap pages of K_TEX records),
    "early_flushes" (drawAllL calls since the frame before: lists drawn
    early, not in this capture), "replay" (instructions, cycles,
    interrupts, bytes read and written, I/O; all without the interrupts
    inside the replay), "screen" (bytes changed and written),
    "context_by_bank", "written_by_bank",
    "written_then_changed_by_interrupts" (addresses the replay wrote and
    an interrupt inside it wrote again: its stack), "problems", and after
    --call, "verified"."""
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n')


def read_manifest(directory: Path) -> Dict:
    return json.loads((directory / 'manifest.json').read_text())


# ---- --call on a capture ----

def call_options(directory: Path, manifest: Dict,
                 loads: Sequence[Tuple[int, Path]] = ()) -> List[str]:
    """The machine's arguments to run the replay alone on the capture in
    `directory`: its context.img as the image, every "before" file
    loaded, then `loads` (address, file) over them."""
    options = [str(directory / 'context.img')]
    for f in manifest['files']:
        if f['when'] != 'before' or f['name'] == 'context':
            continue
        if f['format'] == 'raw':
            options += ['--load', '%06X:%s' % (f['address'],
                                               directory / f['file'])]
        else:
            options += ['--load-image', str(directory / f['file'])]
    for address, path in loads:
        options += ['--load', '%06X:%s' % (address, path)]
    options += ['--call', '%06X' % manifest['entry']['address']]
    return options


def run_call(machine: Path, directory: Path, manifest: Dict, scratch: Path,
             loads: Sequence[Tuple[int, Path]] = ()) -> Dict:
    """Run the replay alone; returns the state, with the screen and
    buffer after it ('screen', 'buffer') and the writes image
    ('writes')."""
    scratch.mkdir(parents=True, exist_ok=True)
    screen, buffer, writes = (scratch / 'screen.bin', scratch / 'buffer.bin',
                              scratch / 'writes.img')
    command = [str(machine)] + call_options(directory, manifest, loads) + [
        '--save', '%06X:0x%X:%s' % (SCREEN, SCREEN_SIZE, screen),
        '--save', '%06X:0x%X:%s' % (BUFFER, SCREEN_SIZE, buffer),
        '--call-writes', str(writes)]
    # bounded (the ground rules): --call stops at 10^9 cycles by itself;
    # the wall-time limit and the file-size limit are the backstop
    try:
        result = bounded.run(command, timeout=bounded.TOOL_TIMEOUT,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise RuntimeError('ref816 --call did not finish in %d s'
                           % bounded.TOOL_TIMEOUT)
    if result.returncode:
        raise RuntimeError('ref816 --call failed: ' + result.stderr)
    state = json.loads(result.stdout)
    state['screen'] = screen.read_bytes()
    state['buffer'] = buffer.read_bytes()
    state['writes'] = writes.read_bytes()
    return state


def verify(machine: Path, directory: Path, scratch: Path) -> Dict:
    """--call on the capture against its own "after" (see the module's
    docstring); the result is also put into the manifest."""
    manifest = read_manifest(directory)
    state = run_call(machine, directory, manifest, scratch)
    call = state['call']
    captured = refimage.read(directory / 'writes.img')
    again = refimage.parse(state['writes'])
    result = {
        'returned': call['returned'] and state['end']['reason'] == 'return',
        'screen_equal': state['screen'] ==
        (directory / 'screen-after.bin').read_bytes(),
        'buffer_equal': state['buffer'] ==
        (directory / 'buffer-after.bin').read_bytes(),
        'writes_equal': again.records == captured.records,
        'registers_equal': again.registers == captured.registers and
        again.switches == captured.switches,
        'instructions_equal': call['instructions'] ==
        manifest['replay']['instructions'],
        'cycles_equal': call['cycles'] == manifest['replay']['cycles'],
        'reads_outside': call['rom_reads'] + call['unmapped_reads'],
    }
    result['ok'] = all(v is True for k, v in result.items()
                       if k != 'reads_outside') and \
        not result['reads_outside']
    manifest['verified'] = result
    write_manifest(directory, manifest)
    return result


# ---- the runs ----

def run_selection(selection: Selection, symbols: script.Symbols,
                  units: Dict, out: Path, keep_raw: bool,
                  check: bool) -> List[Dict]:
    program = program_for(selection, symbols)
    entry, flush = symbols.address(ENTRY), symbols.address(FLUSH)
    marks_options = ['--mark', '%06X' % entry, '--mark', '%06X' % flush]
    runs = run_script.RUNS
    first = run_script.Run(runs / ('capture-' + selection.key),
                           runs / ('capture-' + selection.key) / 'shots')
    state = first.execute(program, symbols, None,
                          run_script.DEFAULT_LIMIT_SECONDS, marks_options)
    log = marks.read(first.marks_path)
    found = run_script.problems(state, log, symbols, program)
    if found:
        raise RuntimeError('%s: %s' % (selection.script, '; '.join(found)))
    hits, before = calls(log, entry, flush)
    chosen = choose(selection, hits, before)

    raw = out / 'raw' / selection.key
    if raw.exists():
        shutil.rmtree(str(raw))
    raw.mkdir(parents=True)
    options = marks_options + ['--capture', str(raw), '--capture-entry',
                               '%06X' % entry]
    for hit in chosen:
        options += ['--capture-hit', str(hit.hit)]
    second = run_script.Run(runs / ('capture-' + selection.key + '-2'),
                            runs / ('capture-' + selection.key + '-2') /
                            'shots')
    again = second.execute(program, symbols, None,
                           run_script.DEFAULT_LIMIT_SECONDS, options)
    found = run_script.problems(again, marks.read(second.marks_path),
                                symbols, program)
    if found:
        raise RuntimeError('%s, capturing: %s' % (selection.script,
                                                  '; '.join(found)))
    if again['ram_fnv1a64'] != state['ram_fnv1a64'] or \
            second.marks_path.read_bytes() != first.marks_path.read_bytes():
        raise RuntimeError('%s: the capturing run differs from the first'
                           % selection.script)

    manifests = []
    width = len(str(selection.count))
    for number, hit in enumerate(chosen, 1):
        raw_hit = raw / ('hit-%08d' % hit.hit)
        call = json.loads((raw_hit / 'call.json').read_text())
        if call['cycles'] != hit.mark.cycles:
            raise RuntimeError('%s: call %d was captured at cycle %d, '
                               'logged at %d' % (selection.key, hit.hit,
                                                 call['cycles'],
                                                 hit.mark.cycles))
        name = '%s-%0*d' % (selection.key, width, number)
        manifest = distill(raw_hit, out / name, units, {
            'script': run_script.script_path(selection.script).name,
            'flushes': hit.flushes})
        if check:
            verify(title.MACHINE, out / name, raw / 'verify')
            manifest = read_manifest(out / name)
        manifests.append(manifest)
    for directory in (first.directory, second.directory):
        shutil.rmtree(str(directory), ignore_errors=True)
    if not keep_raw:
        shutil.rmtree(str(raw))
    return manifests


def directory_size(directory: Path) -> int:
    return sum(p.stat().st_size for p in directory.iterdir() if p.is_file())


def summary(manifest: Dict, size: int) -> str:
    r, s = manifest['records'], manifest['screen']
    line = ('%-8s %s hit %d frame %d tic %d: %d records (%d B), %d KB; '
            'replay %d instructions, %d cycles; screen: %d bytes written, '
            '%d changed' % (
                manifest['name'], manifest['script'], manifest['hit'],
                manifest['frame'], manifest['gametic'], r['records'],
                r['bytes'], (size + 512) // 1024,
                manifest['replay']['instructions'],
                manifest['replay']['cycles'], s['written_pixels'],
                s['changed']))
    if 'verified' in manifest:
        line += '; --call %s' % ('equal' if manifest['verified']['ok']
                                 else 'DIFFERS')
    for problem in manifest['problems']:
        line += '\n  PROBLEM: ' + problem
    return line


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, default=CAPTURES)
    parser.add_argument('--sets', default=','.join(s.key for s in SETS))
    parser.add_argument('--keep-raw', action='store_true')
    parser.add_argument('--no-verify', action='store_true')
    arguments = parser.parse_args(argv)
    wanted = arguments.sets.split(',')
    unknown = set(wanted) - set(s.key for s in SETS)
    if unknown:
        parser.error('no set %s' % ', '.join(sorted(unknown)))
    for path in (make_image.RELEASE_IMAGE, make_image.LINKMAP):
        if not path.exists():
            print('%s is missing: run python3 tools/fetch_upstream.py and '
                  'python3 tools/v816/imgmatch.py first' % path,
                  file=sys.stderr)
            return 1
    title.build_machine()
    title.ensure_image()
    with open(str(make_image.LINKMAP)) as handle:
        linkmap = json.load(handle)
    symbols = script.Symbols(linkmap)
    units = linkmap['game']['units']
    arguments.out.mkdir(parents=True, exist_ok=True)
    failed = False
    for selection in SETS:
        if selection.key not in wanted:
            continue
        for manifest in run_selection(selection, symbols, units,
                                      arguments.out, arguments.keep_raw,
                                      not arguments.no_verify):
            size = directory_size(arguments.out / manifest['name'])
            print(summary(manifest, size))
            failed = failed or bool(manifest['problems']) or (
                'verified' in manifest and not manifest['verified']['ok'])
    if not arguments.keep_raw:
        shutil.rmtree(str(arguments.out / 'raw'), ignore_errors=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
