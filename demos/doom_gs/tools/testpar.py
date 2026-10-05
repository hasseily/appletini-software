#!/usr/bin/env python3
"""Run the test modules of tests/ in parallel, with the results of the
canonical command (python3 -m unittest discover -s tests).

Usage:  python3 tools/testpar.py [--jobs N] [--timeout S] [--list]
                                 [--json FILE] [MODULE ...]

Each module runs in a process of its own, loaded the way the canonical
command loads it (unittest's discover from tests/, with the pattern
<module>.py), under tools/ref816/bounded.py's bounds: --timeout seconds of
wall time (default 1200; MODULE_TIMEOUTS gives a module more, with its
reason), files of at most 1 GiB (the tools' own bound). On a timeout or
an interrupt, the module's process and every process it started are
killed, whatever process group they are in (kill_tree). Up to
--jobs modules run at once (default 9, the ground rules' limit), the
longest first, from the times of the last run kept in
build/testpar-times.json (one number a module, rewritten at the end of
each run).

The races. Several modules build into the same directories under build/
or rewrite the same files there. Before the workers start, the runner
makes each shared build once (PREBUILD below), the very make the tests
run, so that the tests' own makes find it up to date and write nothing.
A module that still rewrites shared files after that (SHARED below) never
runs at the same time as another module that writes or reads them: they
run one after another, while the other modules go on in the other
workers. A prebuild step that fails is reported, and the modules that make
or use its build then run one after another too, as in the canonical
command. tests/README.md's section "The parallel runner" lists who writes
where, and the evidence.

The summary gives, for each module, its time, tests, failures, errors and
skips, then the totals, then the whole output of every module that failed,
erred, crashed or ran out of time. The exit status is 1 if any did, 0
otherwise. --json FILE also writes each test's outcome (for comparing two
runs). --list prints the schedule and runs nothing.

A work-in-progress module, tests/wip_test_*.py (a part's test while it is
built: docs/SCREENS.md 7.1), is outside unittest's pattern, so neither the
canonical command nor a run with no names takes it; it runs when named
(`python3 tools/testpar.py tests/wip_test_PART.py`), loaded the same
way.
"""

import argparse
import ast
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from ref816 import bounded  # noqa: E402

ROOT = HERE.parent
TESTS = ROOT / 'tests'
BUILD = ROOT / 'build'
TIMES = BUILD / 'testpar-times.json'
PATTERN = 'test*.py'                # unittest discover's default
WIP_PATTERN = 'wip_test_*.py'       # run only when named (discover)
JOBS = 9
TIMEOUT = 1200.0
# Modules that need more than --timeout, each with its own limit (never
# less than --timeout) and the reason. Both run an even sample by default
# (tests/README.md) and need the limit with DOOM_GS_FULL=1 only:
# milestone 10's checkpoint S runs milestone 9's whole acceptance again on
# the final layouts (57 setups from two fills, checkpoint B, the disk,
# frame8.py's 1,458 runs) with S2-S7 (1,301 s on 2026-10-01, 1,085 of them
# frame8.py on all 729 loaded-level frames)
MODULE_TIMEOUTS: Dict[str, float] = {
    'test_native_game_skeleton': 3600.0,
    # part geom's checkpoint on every case from both fills, the iterators'
    # 434 recording cases, 1.8 million random pairs, four plants: 2,164 s
    # at its 2 processes (docs/game-parts/geom.md R12, wave 1 as
    # integrated)
    'test_native_game_geom': 3600.0}
MAX_BYTES = bounded.TOOL_MAX_BYTES  # the largest file a tool may write
PREBUILD_TIMEOUT = 900.0
SHOW_LIMIT = 4 << 20                # the output shown of a failing module
SRC = ROOT / 'src' / 'native'


# ---------------------------------------------------------------------------
# The races (tests/README.md, "The parallel runner", has the evidence)
# ---------------------------------------------------------------------------

class Shared(NamedTuple):
    """Files under build/ that `writers` rewrite on every run and `readers`
    read: a writer never runs at the same time as another writer or a
    reader of the same files (they run one after another, in any
    worker); readers run together."""
    name: str
    writers: Sequence[str]
    readers: Sequence[str] = ()


class Step(NamedTuple):
    """A shared build, made once before the tests. `writers` run the same
    command themselves (it writes nothing once it is up to date);
    `readers` use what it makes. Should the step fail, they all become a
    Shared of their own, as in the canonical command."""
    name: str
    command: Sequence[str]          # run from ROOT
    needs: Sequence[str]            # programs on PATH it needs
    writers: Sequence[str]
    readers: Sequence[str] = ()


def _make(makefile: str, out: Path, *variables: str) -> List[str]:
    return ['make', '-s', '-C', str(SRC), '-f', makefile,
            'ROOT=%s' % ROOT, 'OUT=%s' % out] + list(variables)


REF816_USERS = ('test_ref816_calllog', 'test_ref816_capture',
                'test_ref816_divscan', 'test_ref816_dump',
                'test_ref816_inject', 'test_ref816_trace')
# milestone 11's first half (docs/SCREENS.md 8.13): s2menu1.capture(),
# s2menu2.capture() and s2ovl.capture() run title.build_machine() and
# title.ensure_image() before their ref816 captures
REF816_USERS += ('test_m11_s2menu1', 'test_m11_s2menu2', 'test_m11_s2ovl')
CC65 = ('make', 'ca65', 'ld65')

PREBUILD: Tuple[Step, ...] = (
    # title.build_machine(): make -C tools/ref816 build/ref816/ref816
    # (tools/bridge/dumps.py too, when the machine is missing)
    Step('ref816 machine',
         ['make', '-s', '-C', str(ROOT / 'tools' / 'ref816'),
          str(BUILD / 'ref816' / 'ref816')], ('make', 'cc'),
         REF816_USERS + ('test_coverage', 'test_ref816_machine',
                         'test_bridge_dumps', 'test_native_game_skeleton',
                         'test_native_game_lockstep'),
         ('test_native_frame8', 'test_native_math', 'test_native_replay')),
    # title.ensure_image() writes build/ref816/memory.img, loader.img and
    # disk.hdv when they are missing, test_coverage and test_ref816_machine
    # rewrite them on every run (make_image.main([]), SHARED below). The
    # step rewrites them as those two do, so that a stale image is replaced
    # before any module reads it, whichever runs first.
    Step('ref816 image',
         [sys.executable, '-c', 'import sys; sys.path.insert(0, "tools"); '
          'from ref816 import make_image; sys.exit(make_image.main([]))'], (),
         REF816_USERS + ('test_bridge_dumps', 'test_interpreter',
                         'test_coverage', 'test_ref816_machine',
                         'test_native_game_skeleton',
                         'test_native_game_lockstep')),
    # test_native_math: make -C tools/native (build/native/math/mathref)
    Step('mathref', ['make', '-s', '-C', str(ROOT / 'tools' / 'native')],
         ('make', 'cc'), ('test_native_math',), ('test_native_render',)),
    # test_native_math: math.mk into build/native/math/obj
    Step('math.mk',
         _make('math.mk', BUILD / 'native' / 'math' / 'obj',
               'TABLES=%s' % (BUILD / 'native' / 'math' / 'tables')),
         CC65, ('test_native_math',)),
    # test_native_replay: src/native/Makefile into build/native/obj
    Step('replay (Makefile)',
         _make('Makefile', BUILD / 'native' / 'obj'), CC65,
         ('test_native_replay',), ('test_native_render_frame',)),
    # render_check.make(): render.mk into build/native/render/obj
    Step('render.mk',
         _make('render.mk', BUILD / 'native' / 'render' / 'obj'), CC65,
         ('test_native_frame8', 'test_native_masked',
          'test_native_masked_b', 'test_native_render',
          'test_native_render_frame', 'test_native_render_walls'),
         ('test_native_level_load', 'test_native_game_skeleton',
          'test_ticloads')),
    # lrun.make(): level.mk into build/native/levels/obj (play.mk runs the
    # same make first, for the load image it links: playdisk.make() in
    # test_play_runs and test_play_bench)
    Step('level.mk',
         _make('level.mk', BUILD / 'native' / 'levels' / 'obj'), CC65,
         ('test_native_level_load', 'test_native_level_setup',
          'test_native_game_skeleton', 'test_play_runs',
          'test_play_bench', 'test_play_cardprof', 'test_play_noamem')),
    # milestone 10: grun.make(): game.mk's shared outputs (build/native/
    # game/shared: the generated includes, game.cfg, the game manifests,
    # the call graph) and the skeleton's test image (build/native/game/
    # skel). The parts' tests only read them (src/native/game/README.md)
    # (the final integration: test_native_game_lockstep's ticrun.run makes
    # the lockstep image `game` the same way, and ref816's machine and
    # image for its start captures; test_objapi assembles gobj.s against
    # the skeleton's gen, speed wave 2)
    Step('game.mk',
         ['make', '-s', '-C', str(SRC), '-f', 'game.mk', 'shared', 'skel',
          'ROOT=%s' % ROOT], CC65, ('test_native_game_skeleton',
                                    'test_native_game_lockstep'),
         ('test_objapi',)),
)

SHARED: Tuple[Shared, ...] = (
    # support.frontend_results() runs frontend.generate(), which rewrites
    # build/gen/drawcol.s and loadfont.s (open(..., 'w'), not atomic)
    Shared('build/gen', ('test_cppcheck', 'test_frontend', 'test_imgmatch',
                         'test_release', 'test_sections')),
    # make_image.main([]) rewrites build/ref816/memory.img, loader.img
    # (write_bytes) and disk.hdv (copyfile) in place; the others run
    # build/ref816/ref816 on them
    Shared('build/ref816 image', ('test_coverage', 'test_ref816_machine'),
           REF816_USERS + ('test_bridge_dumps', 'test_interpreter')),
    # playdisk.make() rebuilds build/native/play (play.mk) in its
    # setUpClass; test_playtime.ExactIdle copies that directory and runs
    # its disk, so it must not see a rebuild half done (speed wave 1);
    # test_ticloads and test_play_glue's Tickers read its links (speed
    # wave 2); test_calib copies the game's routines out of its card and
    # tic links (calibdisk.play_parts); test_play_noamem runs the disk
    # without the memory API as test_play_bench runs it, and test_amcpu
    # reads its tic link's CPU version (docs/PLAY.md 19); test_vidhd reads
    # its links and bank files for the VidHD's records (docs/PLAY.md 22)
    Shared('build/native/play', ('test_play_runs', 'test_play_bench',
                                 'test_play_cardprof', 'test_play_noamem'),
           ('test_playtime', 'test_ticloads', 'test_play_glue',
            'test_calib', 'test_amcpu', 'test_vidhd')),
)


# ---------------------------------------------------------------------------
# The guard: every module that writes shared files is in the tables
# ---------------------------------------------------------------------------

# (owner, function) -> the PREBUILD step or SHARED entry among whose writers
# a module that makes the call must be. The owner is the module the
# function comes from, by its last name (`title` for ref816.title,
# `render_check` for `from native import render_check as RC`).
WRITER_CALLS: Dict[Tuple[str, str], str] = {
    ('support', 'frontend_results'): 'build/gen',
    ('support', 'match_results'): 'build/gen',
    ('support', 'release_targets'): 'build/gen',
    ('make_image', 'main'): 'build/ref816 image',
    ('title', 'build_machine'): 'ref816 machine',
    ('title', 'ensure_image'): 'ref816 image',
    ('render_check', 'make'): 'render.mk',
    ('lrun', 'make'): 'level.mk',
    ('grun', 'make'): 'game.mk',
    ('playdisk', 'make'): 'build/native/play',
}
# A `make` builds into the directory given as its first argument (or obj=,
# out=): one that names a computed directory (tmp / 'obj') builds a private
# copy, one that names none, or a module's constant (OBJ, mathrun.OBJ), the
# shared one. make_image.main writes the shared image unless given --out.
# A module's own `def make` of a makefile of src/native (test_native_math,
# test_native_replay) counts as the PREBUILD step that runs that makefile.


def _step_of_makefile(makefile: str) -> Optional[str]:
    """The PREBUILD step that runs make with `makefile` in src/native."""
    for step in PREBUILD:
        command = list(step.command)
        if '-C' not in command or command[command.index('-C') + 1] != \
                str(SRC):
            continue
        name = (command[command.index('-f') + 1] if '-f' in command
                else 'Makefile')
        if name == makefile:
            return step.name
    return None


def _writes_shared(call: ast.Call, function: str) -> bool:
    """Whether `call` of `function` writes the shared files rather than a
    private copy."""
    if function == 'main':          # make_image.main(['--out', private])
        if call.args and isinstance(call.args[0], ast.List):
            return not any(isinstance(e, ast.Constant) and e.value == '--out'
                           for e in call.args[0].elts)
        return True
    if function != 'make':
        return True
    out = call.args[0] if call.args else next(
        (k.value for k in call.keywords if k.arg in ('obj', 'out')), None)
    return out is None or isinstance(out, (ast.Name, ast.Attribute))


class _Source:
    """A Python file of tests/ or tools/: its imports, its top-level
    functions and the shared writes each of them makes."""

    cache: Dict[Path, Optional['_Source']] = {}

    @classmethod
    def of_module(cls, dotted: str, tests: Path) -> Optional['_Source']:
        for base in (tests, HERE):
            path = base.joinpath(*dotted.split('.')).with_suffix('.py')
            if path.is_file():
                return cls.of(path)
        return None

    @classmethod
    def of(cls, path: Path) -> Optional['_Source']:
        if path not in cls.cache:
            try:
                cls.cache[path] = cls(path)
            except (OSError, SyntaxError, ValueError):
                cls.cache[path] = None
        return cls.cache[path]

    def __init__(self, path: Path):
        self.path = path
        self.tree = ast.parse(path.read_text(), str(path))
        # local name -> (the dotted module it comes from, its name there)
        self.alias: Dict[str, Tuple[str, str]] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module and \
                    not node.level:
                for a in node.names:
                    self.alias[a.asname or a.name] = (node.module, a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        package, _, name = a.name.rpartition('.')
                        self.alias[a.asname] = (package, name)
        self.functions = {n.name: n for n in self.tree.body
                          if isinstance(n, ast.FunctionDef)}
        self.local: Dict[Tuple[str, str], str] = {}
        if 'make' in self.functions:
            strings = [n.value for n in ast.walk(self.functions['make'])
                       if isinstance(n, ast.Constant)
                       and isinstance(n.value, str)]
            makefile = next((s for s in strings if s.endswith('.mk')),
                            'Makefile' if 'make' in strings else None)
            step = _step_of_makefile(makefile) if makefile else None
            if step:
                self.local[(path.stem, 'make')] = step
        self.memo: Dict[str, List[Tuple[str, str]]] = {}

    def resolve(self, call: ast.Call) -> Tuple[Optional[Tuple[str, str]],
                                               Optional[str]]:
        """(owner, function) of `call` and the dotted module of the
        function, when known."""
        f = call.func
        if isinstance(f, ast.Attribute):
            v = f.value
            if isinstance(v, ast.Name):
                if v.id in self.alias:
                    package, name = self.alias[v.id]
                    dotted = '%s.%s' % (package, name) if package else name
                    return (name, f.attr), dotted
                return (v.id, f.attr), v.id
            if isinstance(v, ast.Attribute):
                return (v.attr, f.attr), None
        elif isinstance(f, ast.Name):
            if f.id in self.functions:
                return (self.path.stem, f.id), ''
            if f.id in self.alias:
                package, name = self.alias[f.id]
                return (package.split('.')[-1], name), package
        return None, None

    def writes(self, node: ast.AST, tests: Path,
               seen: frozenset = frozenset()) -> List[Tuple[str, str]]:
        """The shared writes of the calls under `node`: (entry, the chain
        of calls that makes it), following the functions of tests/ and
        tools/ it calls."""
        out = []
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            key, dotted = self.resolve(call)
            if key is None:
                continue
            entry = WRITER_CALLS.get(key) or self.local.get(key)
            here = '%s.%s() (%s:%d)' % (key[0], key[1], self.path.name,
                                        call.lineno)
            if entry:
                if _writes_shared(call, key[1]):
                    out.append((entry, here))
                continue
            source = self if dotted == '' else (
                _Source.of_module(dotted, tests) if dotted else None)
            if source is None or key[1] not in source.functions:
                continue
            for entry, chain in source.function_writes(key[1], tests, seen):
                out.append((entry, here + ' -> ' + chain))
        return out

    def function_writes(self, name: str, tests: Path,
                        seen: frozenset) -> List[Tuple[str, str]]:
        tag = (self.path, name)
        if tag in seen:
            return []
        if name not in self.memo:
            self.memo[name] = self.writes(self.functions[name], tests,
                                          seen | {tag})
        return self.memo[name]


# The calls the guard follows that do not write, by what the code does at
# run time: (module, entry, the call that starts the chain) -> why.
NOT_WRITES: Dict[Tuple[str, str, str], str] = {
    ('test_native_level_load', 'render.mk', 'frame8.main()'):
        'it passes --no-build, so frame8.main() skips its RC.make(); the '
        'module reads build/native/render/obj (a reader of render.mk)',
    ('test_native_game_skeleton', 'render.mk', 'frame8.main()'):
        'S1 passes --no-build, as test_native_level_load does',
}


def unlisted(tests: Path = TESTS) -> List[str]:
    """Every test module that writes shared files and is not among the
    writers of their entry in PREBUILD or SHARED: one that calls a function
    of WRITER_CALLS, or a function of tests/ or tools/ that does, at any
    depth (but for NOT_WRITES). For tests/ itself, also every entry of
    NOT_WRITES that no longer matches a call."""
    entries = {s.name: s for s in SHARED}
    entries.update({s.name: s for s in PREBUILD})
    _Source.cache.clear()
    problems, used = [], set()
    for module in discover(tests=tests):
        source = _Source.of(tests / (module + '.py'))
        if source is None:
            problems.append('%s.py cannot be read' % module)
            continue
        for entry, chain in source.writes(source.tree, tests):
            if module in entries[entry].writers:
                continue
            first = chain.split(' (', 1)[0]
            if (module, entry, first) in NOT_WRITES:
                used.add((module, entry, first))
                continue
            problems.append('%s writes %s, by %s, and is not among its '
                            'writers' % (module, entry, chain))
    if tests == TESTS:
        for stale in sorted(set(NOT_WRITES) - used):
            problems.append('NOT_WRITES %s matches no call any more' %
                            (stale,))
    return problems


def conflicts(shared: Sequence[Shared]) -> Dict[str, set]:
    """For each module, the modules it may not run at the same time as."""
    out: Dict[str, set] = {}
    for s in shared:
        users = set(s.writers) | set(s.readers)
        for w in s.writers:
            out.setdefault(w, set()).update(users - {w})
            for u in users - {w}:
                out.setdefault(u, set()).add(w)
    return out


# ---------------------------------------------------------------------------
# One module
# ---------------------------------------------------------------------------

# Run in a fresh interpreter from ROOT: unittest's own main, as `python3 -m
# unittest discover -s tests -p <module>.py` runs it, with a result that
# also writes each test's outcome to a file.
WORKER = r'''
import importlib.util, json, sys, unittest
module, out = sys.argv[1], sys.argv[2]
# bounded.run's limits, set here rather than in a preexec_fn (which is not
# safe in a runner with threads): tools/ref816/bounded.py loaded from its
# path, so that nothing is added to sys.path or sys.modules
spec = importlib.util.spec_from_file_location('_testpar_bounded', sys.argv[5])
bounded = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bounded)
bounded._limits(int(sys.argv[3]), int(sys.argv[4]))()
del spec, bounded
outcomes = {}
RANK = {'ok': 0, 'skip': 0, 'expected failure': 0,
        'unexpected success': 1, 'fail': 2, 'error': 3}

def note(test, what):
    key = test.id()
    if RANK[what] >= RANK.get(outcomes.get(key), -1):
        outcomes[key] = what

class Result(unittest.TextTestResult):
    def addSuccess(self, test):
        super().addSuccess(test); note(test, 'ok')
    def addFailure(self, test, err):
        super().addFailure(test, err); note(test, 'fail')
    def addError(self, test, err):
        super().addError(test, err); note(test, 'error')
    def addSkip(self, test, reason):
        super().addSkip(test, reason); note(test, 'skip')
    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err); note(test, 'expected failure')
    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test); note(test, 'unexpected success')
    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            failed = issubclass(err[0], test.failureException)
            note(test, 'fail' if failed else 'error')

class Runner(unittest.TextTestRunner):
    resultclass = Result
    def run(self, test):
        result = super().run(test)
        with open(out, 'w') as handle:
            json.dump({'run': result.testsRun,
                       'failures': len(result.failures),
                       'errors': len(result.errors),
                       'skipped': len(result.skipped),
                       'expected_failures': len(result.expectedFailures),
                       'unexpected_successes':
                           len(result.unexpectedSuccesses),
                       'successful': result.wasSuccessful(),
                       'outcomes': outcomes}, handle)
        return result

program = unittest.main(
    module=None, testRunner=Runner, exit=False,
    argv=['python3 -m unittest', 'discover', '-s', 'tests',
          '-p', module + '.py'])
sys.exit(0 if program.result.wasSuccessful() else 1)
'''


class Outcome(NamedTuple):
    module: str
    seconds: float
    status: str                     # ok, failed, crashed, timeout
    counts: Dict[str, int]
    outcomes: Dict[str, str]
    output: str
    returncode: Optional[int]


COUNTS = ('run', 'failures', 'errors', 'skipped', 'expected_failures',
          'unexpected_successes')


def read_output(path: Path, limit: int = SHOW_LIMIT) -> str:
    """The text of `path`, its first `limit` bytes and a note beyond."""
    try:
        size = path.stat().st_size
        with open(str(path), 'rb') as handle:
            data = handle.read(limit)
    except OSError:
        return ''
    text = data.decode('utf-8', 'replace')
    if size > limit:
        text += '\n[testpar: %d more bytes not shown]\n' % (size - limit)
    return text


def judge(module: str, seconds: float, returncode: Optional[int],
          result: Optional[dict], output: str,
          timed_out: bool = False) -> Outcome:
    """The Outcome of a module from what its process left."""
    if timed_out:
        status = 'timeout'
    elif result is None:
        status = 'crashed'
    elif result.get('successful') and returncode == 0:
        status = 'ok'
    elif result.get('successful'):
        status = 'crashed'          # the tests passed, the process did not
    else:
        status = 'failed'
    counts = {k: int((result or {}).get(k, 0)) for k in COUNTS}
    return Outcome(module, seconds, status, counts,
                   dict((result or {}).get('outcomes', {})), output,
                   returncode)


LIVE: set = set()                   # the process groups of running modules
LIVE_LOCK = threading.Lock()
STOPPING = []


def _process_table() -> List[Tuple[int, int, int]]:
    """(pid, parent, process group) of every process, from ps; nothing if
    ps fails."""
    try:
        text = subprocess.run(
            ['ps', '-A', '-o', 'pid=', '-o', 'ppid=', '-o', 'pgid='],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, universal_newlines=True,
            timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 3 and all(f.isdigit() for f in fields):
            rows.append((int(fields[0]), int(fields[1]), int(fields[2])))
    return rows


def _groups_below(roots: set, table: Sequence[Tuple[int, int, int]]) -> set:
    """The process groups of the descendants of `roots`."""
    children: Dict[int, List[Tuple[int, int]]] = {}
    for pid, parent, group in table:
        children.setdefault(parent, []).append((pid, group))
    groups, seen, todo = set(), set(roots), list(roots)
    while todo:
        for pid, group in children.get(todo.pop(), ()):
            if pid not in seen:
                seen.add(pid)
                groups.add(group)
                todo.append(pid)
    return groups


def kill_tree(pid: int) -> None:
    """Kill the process group of `pid` (a worker, the leader of its own
    session) and every process group its descendants are in: bounded.run,
    and so support.run and the tools' makes and machines, starts each child
    in a session of its own, which killing the worker's group alone would
    leave running. Every group is stopped (SIGSTOP) as it is found, so
    that nothing forks out of reach while the tree is walked, then all of
    them are killed."""
    own = os.getpgrp()
    stopped: List[int] = []

    def stop(group):
        if group in stopped or group == own or group <= 1:
            return
        try:
            os.killpg(group, signal.SIGSTOP)
        except (ProcessLookupError, PermissionError):
            return
        stopped.append(group)

    stop(pid)
    for _ in range(100):            # each pass stops at least one group
        table = _process_table()
        roots = {pid} | {p for p, _, g in table if g in stopped}
        new = _groups_below(roots, table) - set(stopped) - {own}
        if not new:
            break
        for group in sorted(new):
            stop(group)
    for group in stopped:
        bounded._kill_group(group)
    bounded._kill_group(pid)


def stop_all() -> None:
    """Kill every running module and all it started, and any module
    started after."""
    with LIVE_LOCK:
        STOPPING.append(True)
        for pid in LIVE:
            kill_tree(pid)


def run_module(module: str, scratch: Path, timeout: float,
               root: Path = ROOT) -> Outcome:
    """Run <root>/tests/<module>.py in a process of its own, from
    `root`."""
    log = scratch / (module + '.log')
    out = scratch / (module + '.json')
    env = dict(os.environ, TESTPAR_MODULE=module)
    start = time.monotonic()
    returncode, timed_out = None, False
    # bounded.run's three bounds (the worker sets the file and CPU limits
    # itself), with the process kept in LIVE so that an interrupted runner
    # can stop it (main())
    cpu = int(math.ceil(timeout)) + bounded.CPU_SLACK
    with open(str(log), 'wb') as handle:
        process = subprocess.Popen(
            [sys.executable, '-c', WORKER, module, str(out), str(MAX_BYTES),
             str(cpu), str(Path(bounded.__file__).resolve())],
            cwd=str(root), env=env, stdin=subprocess.DEVNULL, stdout=handle,
            stderr=subprocess.STDOUT, start_new_session=True)
        with LIVE_LOCK:
            LIVE.add(process.pid)
            if STOPPING:
                kill_tree(process.pid)
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            if process.poll() is None:  # a timeout or an interrupt
                kill_tree(process.pid)  # it and all it started
            bounded._kill_group(process.pid)
            process.wait()
            with LIVE_LOCK:
                LIVE.discard(process.pid)
    seconds = time.monotonic() - start
    result = None
    try:
        result = json.loads(out.read_text())
    except (OSError, ValueError):
        pass
    output = read_output(log)
    if timed_out:
        output += '\n[testpar: killed after %.0f s]\n' % timeout
    elif returncode is not None and returncode < 0:
        why = bounded.explain(returncode, MAX_BYTES)
        output += '\n[testpar: ended by signal %d%s]\n' % (
            -returncode, ' (%s)' % why if why else '')
    return judge(module, seconds, returncode, result, output, timed_out)


# ---------------------------------------------------------------------------
# The schedule
# ---------------------------------------------------------------------------

def discover(names: Sequence[str] = (), tests: Path = TESTS) -> List[str]:
    """The test modules of `tests` (unittest's pattern), or `names`. A
    work-in-progress module (tests/wip_test_*.py, which the pattern and
    so the canonical command leave out) runs only when it is named."""
    found = sorted(p.stem for p in tests.glob(PATTERN) if p.is_file())
    if not names:
        return found
    named = found + sorted(p.stem for p in tests.glob(WIP_PATTERN)
                           if p.is_file())
    wanted = [Path(n).name for n in names]     # tests/test_x.py too
    wanted = [n[:-3] if n.endswith('.py') else n for n in wanted]
    unknown = [n for n in wanted if n not in named]
    if unknown:
        raise SystemExit('testpar: no such test module: %s'
                         % ', '.join(unknown))
    return [n for n in named if n in wanted]


def load_times(path: Path = TIMES) -> Dict[str, float]:
    try:
        data = json.loads(path.read_text())
        return {str(k): float(v) for k, v in data.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def save_times(times: Dict[str, float], modules: Sequence[str],
               path: Path = TIMES) -> None:
    """Rewrite the timing file: one entry a test module that exists."""
    if not path.parent.is_dir():
        return
    keep = {m: round(times[m], 1) for m in sorted(times) if m in modules}
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(keep, indent=0, sort_keys=True) + '\n')
    os.replace(str(tmp), str(path))


def order(modules: Sequence[str], times: Dict[str, float],
          tests: Path = TESTS) -> List[str]:
    """The modules longest first. One with no time yet counts as longer
    than any known (new modules start early), by the size of its source
    among themselves."""
    def cost(m):
        if m in times:
            return (0, times[m], m)
        try:
            return (1, (tests / (m + '.py')).stat().st_size, m)
        except OSError:
            return (1, 0, m)
    return sorted(modules, key=cost, reverse=True)


def dispatch(modules: Sequence[str], conflict: Dict[str, set], jobs: int,
             run) -> None:
    """Call run(module) for each of `modules` in `jobs` threads: each
    thread takes the first module of the list that conflicts with none of
    those running. Nothing conflicts with a module when nothing runs, so
    the list always empties."""
    pending = list(modules)
    running: set = set()
    cond = threading.Condition()
    errors: List[BaseException] = []

    def ready():
        for m in pending:
            if not conflict.get(m, set()) & running:
                return m
        return None

    def worker():
        while True:
            with cond:
                while pending and not errors and ready() is None:
                    cond.wait()
                if not pending or errors:
                    return
                module = ready()
                pending.remove(module)
                running.add(module)
            try:
                run(module)
            except BaseException as error:  # noqa: B902 (re-raised below)
                with cond:
                    errors.append(error)
            finally:
                with cond:
                    running.discard(module)
                    cond.notify_all()

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(max(1, min(jobs, len(modules))))]
    for t in threads:
        t.start()
    try:
        for t in threads:
            t.join()
    except BaseException as error:      # an interrupt: start nothing more
        with cond:
            errors.append(error)
            cond.notify_all()
        raise
    if errors:
        raise errors[0]


# ---------------------------------------------------------------------------
# The prebuild
# ---------------------------------------------------------------------------

class Built(NamedTuple):
    step: Step
    ok: bool
    seconds: float
    output: str


def prebuild(steps: Sequence[Step], modules: Sequence[str]) -> List[Built]:
    """Run each step one of whose writers is among `modules`, one at a
    time."""
    done = []
    for step in steps:
        if not any(m in modules for m in step.writers):
            continue
        start = time.monotonic()
        missing = [p for p in step.needs if not shutil.which(p)]
        if missing:
            done.append(Built(step, False, 0.0, '%s is missing from PATH'
                              % ', '.join(missing)))
            continue
        try:
            result = bounded.run(
                step.command, timeout=PREBUILD_TIMEOUT, max_bytes=MAX_BYTES,
                cwd=str(ROOT), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True)
            ok, text = result.returncode == 0, result.stdout
        except subprocess.TimeoutExpired:
            ok, text = False, 'timed out after %.0f s' % PREBUILD_TIMEOUT
        except OSError as error:
            ok, text = False, str(error)
        done.append(Built(step, ok, time.monotonic() - start, text))
    return done


# ---------------------------------------------------------------------------
# The summary
# ---------------------------------------------------------------------------

def summary(outcomes: Sequence[Outcome], built: Sequence[Built],
            wall: float, jobs: int) -> Tuple[str, int]:
    """The report of a run, and its exit status."""
    lines = []
    if built:
        lines.append('prebuild:')
        for b in built:
            lines.append('  %-28s %6.1f s  %s' % (
                b.step.name, b.seconds,
                'ok' if b.ok else 'FAILED (its writers ran alone)'))
        lines.append('')
    lines.append('%-32s %8s %6s %5s %5s %5s  %s' % (
        'module', 'seconds', 'tests', 'fail', 'error', 'skip', 'status'))
    total = dict.fromkeys(COUNTS, 0)
    bad = []
    for o in sorted(outcomes, key=lambda o: o.module):
        for k in COUNTS:
            total[k] += o.counts[k]
        lines.append('%-32s %8.1f %6d %5d %5d %5d  %s' % (
            o.module, o.seconds, o.counts['run'], o.counts['failures'],
            o.counts['errors'], o.counts['skipped'], o.status))
        if o.status != 'ok':
            bad.append(o)
    lines.append('')
    extra = ''
    if total['expected_failures'] or total['unexpected_successes']:
        extra = ', %d expected failures, %d unexpected successes' % (
            total['expected_failures'], total['unexpected_successes'])
    lines.append('%d modules, %d tests: %d failures, %d errors, %d skipped%s'
                 % (len(outcomes), total['run'], total['failures'],
                    total['errors'], total['skipped'], extra))
    lines.append('wall time %.1f s with %d jobs (the modules: %.1f s)' % (
        wall, jobs, sum(o.seconds for o in outcomes)))
    for b in built:
        if not b.ok:
            lines += ['', '=' * 70, 'prebuild %s failed:' % b.step.name,
                      '  ' + ' '.join(b.step.command), b.output.rstrip()]
    for o in bad:
        lines += ['', '=' * 70,
                  '%s: %s (exit status %s)' % (o.module, o.status.upper(),
                                               o.returncode),
                  '=' * 70, o.output.rstrip()]
    lines.append('')
    lines.append('FAILED: %s' % ', '.join(o.module for o in bad) if bad
                 else 'OK')
    return '\n'.join(lines) + '\n', 1 if bad else 0


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description='Run the test modules of tests/ in parallel.')
    parser.add_argument('modules', nargs='*', metavar='MODULE',
                        help='only these modules (default: all)')
    parser.add_argument('--jobs', '-j', type=int, default=JOBS,
                        help='modules at once (default %d)' % JOBS)
    parser.add_argument('--timeout', type=float, default=TIMEOUT,
                        help='seconds a module may take (default %.0f)'
                        % TIMEOUT)
    parser.add_argument('--json', type=Path,
                        help='write every test outcome to this file')
    parser.add_argument('--list', action='store_true',
                        help='print the schedule and run nothing')
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error('--jobs must be at least 1')
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    modules = discover(args.modules)
    times = load_times()
    plan = order(modules, times)
    if args.list:
        conflict = conflicts(SHARED)
        for m in plan:
            print('%-32s %8s  %s' % (
                m, '%.1f s' % times[m] if m in times else 'new',
                ' '.join(sorted(conflict.get(m, ())))))
        return 0

    start = time.monotonic()
    built = prebuild(PREBUILD, modules)
    shared = list(SHARED) + [Shared(b.step.name, b.step.writers,
                                    b.step.readers)
                             for b in built if not b.ok]
    conflict = conflicts(shared)
    outcomes: List[Outcome] = []
    lock = threading.Lock()

    with tempfile.TemporaryDirectory(prefix='testpar-') as scratch:
        def run(module):
            o = run_module(module, Path(scratch),
                           max(args.timeout, MODULE_TIMEOUTS.get(module, 0)))
            with lock:
                outcomes.append(o)
                print('[%2d/%d] %-32s %7.1f s  %s' % (
                    len(outcomes), len(modules), module, o.seconds,
                    o.status), flush=True)

        try:
            dispatch(plan, conflict, args.jobs, run)
        except KeyboardInterrupt:
            stop_all()
            print('\ntestpar: interrupted; the running modules were killed '
                  '(their temporary directories may remain in build/)',
                  file=sys.stderr)
            return 130
        except BaseException:
            stop_all()
            raise

    wall = time.monotonic() - start
    for o in outcomes:
        if o.status in ('ok', 'failed'):
            times[o.module] = o.seconds
    save_times(times, discover())
    text, status = summary(outcomes, built, wall, args.jobs)
    print()
    sys.stdout.write(text)
    if args.json:
        args.json.write_text(json.dumps(
            {o.module: {'status': o.status, 'seconds': round(o.seconds, 1),
                        'counts': o.counts, 'outcomes': o.outcomes}
             for o in outcomes}, indent=1, sort_keys=True) + '\n')
    return status


if __name__ == '__main__':
    sys.exit(main())
