#!/usr/bin/env python3
"""Dumps of upstream's game state at G_Ticker entries, for the bridge.

Usage:  python3 tools/bridge/dumps.py [--out DIR] [--sets title,demo,...]
                                      [--jobs N]

Runs each coverage script, and demo3 to its end, on ref816 and keeps the
state at chosen entries of G_Ticker (g_game65.s), where one tic is done
and the next has not begun (docs/research/native-verification.md section
6.1). Only ref816's existing options are used, as tools/ref816/capture.py
does: a first run logs every entry (--mark), a second run captures the
chosen calls (--capture, footprint.h) and must end with the same RAM and
the same log. Each chosen call becomes a directory DIR/SET-NN/ with

    entry.img   all RAM at the entry, with the registers (a ref816 image)
    reads.img   the bytes the tic read before writing them (its footprint)
    writes.img  the bytes the tic wrote, with their last values
    exit.img    the same with their values at the return
    call.json   ref816's record of the call
    dump.json   the set, the script, the hit (the call of G_Ticker, from
                1), the note before it, and gametic, gamemap, gamestate,
                leveltime, demoplayback read from entry.img

The sets (SETS below):

    title     coverage/title.script: 3 tics spread from "demo" to
              "demo-25s"
    demo      title.script run on until demo3 ends (a script made here:
              wait for _g_demoplayback to fall to 0): 12 tics spread over
              the whole demo
    newgame   coverage/newgame.script: 8 tics from "still" to the end
    viewsize  coverage/viewsize.script: 3 tics after the first full-size
              shot
    tour      coverage/tour.script: the first tic after the shot of each
              of the nine maps

A note put into a script (note_after) changes nothing of the run. Runs
go under nice -n 10, at most --jobs at a time (default 2).

With --sweep N the tool keeps, for N calls spread over each whole run
(menus, loads and intermissions included), only the footprint (reads.img,
writes.img, call.json, dump.json) in build/bridge/sweep/SET-sNNN/: the
evidence of the liveness check (checks.py) on many more tics than the
dumps.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(TOOLS))

from ref816 import make_image, marks, refimage, run_script, script, \
    title  # noqa: E402

BUILD = make_image.BUILD
DUMPS = BUILD / 'bridge' / 'dumps'
ENTRY = 'g_game65.s:G_Ticker'
SWEEP = BUILD / 'bridge' / 'sweep'
FORMAT = 'bridge-dump 1'
SWEEP_FORMAT = 'bridge-footprint 1'


class Selection(NamedTuple):
    key: str
    script: str                 # a script of coverage/
    edit: Optional[Callable[[str], str]]    # changes to its text
    windows: Sequence[tuple]    # (start note, end note or None, count)


def note_after(pattern: str, note: str) -> Callable[[str], str]:
    """An edit: "note NOTE" after the one line that matches PATTERN
    (outside comments)."""
    def edit(text: str) -> str:
        lines = text.splitlines()
        found = [i for i, line in enumerate(lines)
                 if re.search(pattern, line.split('#')[0])]
        if len(found) != 1:
            raise ValueError('%d lines match %r' % (len(found), pattern))
        lines.insert(found[0] + 1, 'note %s' % note)
        return '\n'.join(lines) + '\n'
    return edit


def chain(*edits: Callable[[str], str]) -> Callable[[str], str]:
    def edit(text: str) -> str:
        for e in edits:
            text = e(text)
        return text
    return edit


def whole_demo(text: str) -> str:
    """title.script up to its note "demo-25s", then on until demo3 ends:
    the game leaves demo playback (G_CheckDemoStatus) at its end marker."""
    head, found, _ = text.partition('note demo-25s')
    if not found:
        raise ValueError('title.script has no note demo-25s')
    return (head + 'note demo-25s\n'
            'wait _g_demoplayback == 0 within 400s  # demo3 ends\n'
            'note demo-end\n'
            'at +1s stop\n')


TOUR_MAPS = (1, 2, 3, 9, 4, 5, 6, 7, 8)

SETS = (
    Selection('title', 'title', None, (('demo', 'demo-25s', 3),)),
    Selection('demo', 'title', whole_demo, (('demo', 'demo-end', 12),)),
    Selection('newgame', 'newgame', None, (('still', None, 8),)),
    Selection('viewsize', 'viewsize',
              note_after(r'\bshot size-full(\s|$)', 'bridge'),
              (('bridge', None, 3),)),
    Selection('tour', 'tour',
              chain(*(note_after(r'\bshot e1m%d\b' % n, 'bridge-e1m%d' % n)
                      for n in TOUR_MAPS)),
              tuple(('bridge-e1m%d' % n, None, 1) for n in TOUR_MAPS)),
)


def program_for(selection: Selection, symbols: script.Symbols) -> str:
    path = run_script.script_path(selection.script)
    text = path.read_text()
    if selection.edit:
        text = selection.edit(text)
    return script.compile_script(text, symbols, path.name)


def choose(selection: Selection, log: Sequence[marks.Entry],
           entry: int) -> List[tuple]:
    """(hit, note, mark) of the chosen calls. The last two calls of a run
    are never chosen: the run can end before they return."""
    hits, before, last_note = [], {}, {}
    name = '%06X' % entry
    note = None
    for e in log:
        if e.kind == 'note':
            before[e.what] = len(hits)
            note = e.what
        elif e.kind == 'mark' and e.what == name:
            hits.append((len(hits) + 1, note, e))
    usable = hits[:-2]
    chosen = []
    for start, end, count in selection.windows:
        if start not in before:
            raise ValueError('%s: no note %s in the run'
                             % (selection.key, start))
        first = before[start]
        stop = before[end] - 2 if end is not None else len(usable)
        inside = usable[first:stop]
        if len(inside) < count:
            raise ValueError('%s: %d calls after %s, not %d'
                             % (selection.key, len(inside), start, count))
        if count == 1:
            picked = [inside[0]]
        else:
            picked = [inside[round(i * (len(inside) - 1) / (count - 1))]
                      for i in range(count)]
        chosen += picked
    return chosen


def nice() -> None:
    try:
        os.nice(10)
    except OSError:
        pass


class Machine:
    """ref816 runs of one selection, under nice -n 10."""

    def __init__(self, directory: Path):
        self.directory = directory

    def run(self, program: str, symbols: script.Symbols,
            extra: Sequence[str]) -> Dict:
        run = run_script.Run(self.directory, self.directory / 'shots')
        # run_script.Run.execute with nice: the same options
        for path in (run.directory, run.shots):
            if path.exists():
                shutil.rmtree(str(path))
        run.dumps.mkdir(parents=True)
        run.shots.mkdir(parents=True)
        run.input.write_text(program)
        options = ['--input', str(run.input), '--shot-dir', str(run.dumps),
                   '--stop-on-fault', '--marks', str(run.marks_path),
                   '--state', str(run.state_path), '--frames',
                   str(script.frames(run_script.DEFAULT_LIMIT_SECONDS))]
        for unit, name in run_script.STOPS:
            options += ['--stop-pc', '%06X' % symbols.address(
                unit + ':' + name)]
        for unit, name in (run_script.LOOP, run_script.RENDER):
            options += ['--mark', '%06X' % symbols.address(
                unit + ':' + name)]
        command = [str(title.MACHINE), str(title.MEMORY), '--disk',
                   str(title.DISK)] + options + list(extra)
        result = subprocess.run(command, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                universal_newlines=True, preexec_fn=nice)
        if result.returncode:
            raise RuntimeError('ref816 failed (%d): %s'
                               % (result.returncode, result.stderr))
        state = json.loads(run.state_path.read_text())
        log = marks.read(run.marks_path)
        found = run_script.problems(state, log, symbols, program)
        if found:
            raise RuntimeError('; '.join(found))
        return state


def peek(memory: refimage.Memory, units: Dict, ref: str, size: int) -> int:
    unit, _, name = ref.partition(':')
    return memory.word(units[unit][name], size)


def spread(log: Sequence[marks.Entry], entry: int, count: int
           ) -> List[tuple]:
    """`count` calls spread evenly over the whole run (the last two
    apart), for a sweep."""
    hits, note = [], None
    name = '%06X' % entry
    for e in log:
        if e.kind == 'note':
            note = e.what
        elif e.kind == 'mark' and e.what == name:
            hits.append((len(hits) + 1, note, e))
    usable = hits[:-2]
    if len(usable) <= count:
        return usable
    return [usable[round(i * (len(usable) - 1) / (count - 1))]
            for i in range(count)]


def make_set(selection: Selection, out: Path, linkmap: Dict,
             sweep: int = 0) -> List[Dict]:
    """The dumps of a selection; with `sweep`, that many calls spread
    over the whole run, of which only the footprint is kept (reads.img,
    writes.img: the liveness check, checks.py)."""
    symbols = script.Symbols(linkmap)
    units = linkmap['game']['units']
    program = program_for(selection, symbols)
    entry = symbols.address(ENTRY)
    mark = ['--mark', '%06X' % entry]
    key = selection.key + ('-sweep' if sweep else '')
    # the runs' files, under the output directory (so the captures move
    # there) and deleted after, whatever happens
    work = Path(tempfile.mkdtemp(prefix='.runs-%s-' % key, dir=str(out)))
    try:
        return make_set_in(selection, out, work, symbols, units, program,
                           entry, mark, key, sweep)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def make_set_in(selection: Selection, out: Path, work: Path,
                symbols: script.Symbols, units: Dict, program: str,
                entry: int, mark: List[str], key: str,
                sweep: int) -> List[Dict]:
    first = Machine(work / key)
    state = first.run(program, symbols, mark)
    log = marks.read(first.directory / 'marks.txt')
    chosen = spread(log, entry, sweep) if sweep else \
        choose(selection, log, entry)
    raw = work / (key + '-raw')
    raw.mkdir(parents=True)
    options = mark + ['--capture', str(raw), '--capture-entry',
                      '%06X' % entry]
    for hit, _, _ in chosen:
        options += ['--capture-hit', str(hit)]
    second = Machine(work / (key + '-2'))
    again = second.run(program, symbols, options)
    if again['ram_fnv1a64'] != state['ram_fnv1a64'] or \
            (second.directory / 'marks.txt').read_bytes() != \
            (first.directory / 'marks.txt').read_bytes():
        raise RuntimeError('%s: the capturing run differs from the first'
                           % selection.key)
    made = []
    for number, (hit, note, logged) in enumerate(chosen, 1):
        source = raw / ('hit-%08d' % hit)
        call = json.loads((source / 'call.json').read_text())
        if call['cycles'] != logged.cycles:
            raise RuntimeError('%s: call %d captured at cycle %d, logged at '
                               '%d' % (selection.key, hit, call['cycles'],
                                       logged.cycles))
        if not call['call']['returned']:
            raise RuntimeError('%s: call %d did not return'
                               % (selection.key, hit))
        target = out / (('%s-s%03d' if sweep else '%s-%02d')
                        % (selection.key, number))
        if target.exists():
            shutil.rmtree(str(target))
        shutil.move(str(source), str(target))
        memory = refimage.load(refimage.read(target / 'entry.img'))
        info = {
            'format': FORMAT, 'name': target.name, 'set': selection.key,
            'script': selection.script, 'hit': hit, 'note': note,
            'cycles': call['cycles'], 'frame': call['frame'],
            'entry': {'symbol': ENTRY, 'address': entry},
            'gametic': peek(memory, units, 'g_game65.s:_g_gametic', 4),
            'gamemap': peek(memory, units, 'g_game65.s:_g_gamemap', 2),
            'gamestate': peek(memory, units, 'g_game65.s:_g_gamestate', 2),
            'leveltime': peek(memory, units, 'p_think65.s:_g_leveltime', 4),
            'demoplayback': peek(memory, units,
                                 'g_game65.s:_g_demoplayback', 2),
        }
        if sweep:
            info['format'] = SWEEP_FORMAT
            for name in ('entry.img', 'exit.img'):
                (target / name).unlink()
        (target / 'dump.json').write_text(json.dumps(info, indent=1) + '\n')
        made.append(info)
    return made


def dump_directories(root: Path = DUMPS) -> List[Path]:
    """The dumps under root, in name order."""
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if (p / 'dump.json').exists()
                  and (p / 'entry.img').exists())


def sweep_directories(root: Path = SWEEP) -> List[Path]:
    """The footprints of a sweep, in name order."""
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if (p / 'dump.json').exists()
                  and (p / 'reads.img').exists())


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, default=DUMPS)
    parser.add_argument('--sets', default=','.join(s.key for s in SETS))
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--sweep', type=int, default=0, metavar='N',
                        help='keep only the footprints of N calls spread '
                        'over each run, in build/bridge/sweep (unless '
                        '--out)')
    arguments = parser.parse_args(argv)
    if arguments.sweep and arguments.out == DUMPS:
        arguments.out = SWEEP
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
    if not title.MACHINE.exists():
        title.build_machine()
    title.ensure_image()
    linkmap = json.loads(make_image.LINKMAP.read_text())
    arguments.out.mkdir(parents=True, exist_ok=True)
    selections = [s for s in SETS if s.key in wanted]
    failed = False
    with ThreadPoolExecutor(max_workers=max(1, arguments.jobs)) as pool:
        futures = [(s, pool.submit(make_set, s, arguments.out, linkmap,
                                   arguments.sweep))
                   for s in selections]
        for selection, future in futures:
            try:
                for info in future.result():
                    print('%-12s hit %5d tic %5d map %d state %d '
                          'leveltime %d' % (
                              info['name'], info['hit'], info['gametic'],
                              info['gamemap'], info['gamestate'],
                              info['leveltime']))
            except (RuntimeError, ValueError) as error:
                print('%s: %s' % (selection.key, error), file=sys.stderr)
                failed = True
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
