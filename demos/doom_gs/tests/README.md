# The tests

`python3 -m unittest discover -s tests`, run from `demos/doom_gs`, is the
canonical command: one process runs every module, one after another (about
8 minutes). Tests that need `build/` skip with a clear message when it is
missing. The ground rules are in
[`docs/MILESTONES.md`](../docs/MILESTONES.md#ground-rules).

## The parallel runner

`python3 tools/testpar.py` runs the same modules with the same results in
about a fifth of the time (100 s instead of 500 s on the owner's Mac). Each module runs in a process of its own, loaded
the way the canonical command loads it (unittest's `discover` from
`tests/`, with the pattern `<module>.py`). Up to 9 run at once (`--jobs N`),
the longest first, from the times of the last run (`build/testpar-times.json`,
one number a module, rewritten each run). Each has a time limit (`--timeout`,
1,200 s by default) and the bounds of `tools/ref816/bounded.py`, which the
module's process sets on itself. A timeout or Ctrl-C kills the module's
process and every process it started, whatever process group it is in
(`bounded.run`, and so `support.run` and the tools' makes and machines,
starts each child in a session of its own): the runner stops each group it
finds under the module, walks the tree again until no new group appears,
then kills them all. A module killed that way may leave its temporary
directories in `build/`.

It prints one summary: for each module its time, tests, failures, errors
and skips, then the totals, then the whole output of every module that
failed, erred, crashed or ran out of time. The exit status is 1 if any did.
`--json FILE` also writes each test's outcome, `--list` the order and the
conflicts, and module names run only those modules.

```
python3 tools/testpar.py                     # everything, 9 at a time
python3 tools/testpar.py test_native_render  # one module (or tests/test_native_render.py)
python3 tools/testpar.py --list              # the order, nothing run
```

### The races

In one process the modules run one after another, so it does not matter
that several of them write the same files under `build/`. Run at the same
time they would race. The runner removes every race it found, without
changing a test:

- **The prebuild.** Before the workers start, the runner runs each shared
  build once, with the very command the tests run. The tests' own makes
  then find it up to date and write nothing. A step that fails is
  reported; the modules that make or use its build then run one after
  another, as in the canonical command.
- **Exclusive writers.** A module that rewrites shared files on every run,
  whatever the prebuild did, never runs at the same time as another module
  that writes or reads them. Readers run together, and the other modules
  go on in the other workers.

Who writes where (`PREBUILD` and `SHARED` in `tools/testpar.py`):

| Shared files under `build/` | How they are written | Written by | Read by | Runner |
| --- | --- | --- | --- | --- |
| `ref816/ref816` | `make -C tools/ref816 build/ref816/ref816` (`title.build_machine()`) | ref816_calllog, ref816_capture, ref816_divscan, ref816_dump, ref816_inject, ref816_trace, ref816_machine, coverage, bridge_dumps (when it is missing) | native_frame8, native_math, native_replay | prebuild |
| `ref816/memory.img`, `loader.img`, `disk.hdv`, when missing | `title.ensure_image()` | ref816_calllog, ref816_capture, ref816_divscan, ref816_dump, ref816_inject, ref816_trace, interpreter, bridge_dumps (in `tools/bridge/dumps.py`) | the same | prebuild: `make_image.main([])`, which rewrites them as coverage and ref816_machine do, so a stale image is replaced before any module reads it |
| `ref816/memory.img`, `loader.img`, `disk.hdv`, always | `make_image.main([])`: `write_bytes` and `copyfile`, in place | coverage, ref816_machine | ref816_calllog, ref816_capture, ref816_divscan, ref816_dump, ref816_inject, ref816_trace, interpreter, bridge_dumps (the machine reads them) | exclusive |
| `gen/drawcol.s`, `gen/loadfont.s`, always | `frontend.generate()` (`support.frontend_results()`) | cppcheck, frontend, imgmatch, release, sections | the same | exclusive |
| `native/math/mathref` | `make -C tools/native` | native_math | native_render (`sidecheck.MATHREF`) | prebuild |
| `native/math/obj` | `math.mk` with `TABLES=build/native/math/tables` | native_math | | prebuild |
| `native/obj` | `src/native/Makefile` (the replay) | native_replay | native_render_frame (`loader.read_build()`) | prebuild |
| `native/render/obj` | `render.mk` (`render_check.make()`) | native_frame8, native_masked, native_masked_b, native_render, native_render_frame, native_render_walls | native_level_load | prebuild |
| `native/levels/obj` | `level.mk` (`lrun.make()`) | native_level_load, native_level_setup | | prebuild |

Nothing but the table says who writes where, so a module added later that
writes shared files would race the others unseen: a plain failure now and
then, or no failure and a different `build/`. `Tables` in
`test_testpar.py` guards the known writers: every module that calls one of
`WRITER_CALLS` in `tools/testpar.py` (`support.frontend_results`,
`match_results`, `release_targets`, `make_image.main` without `--out`,
`title.build_machine`, `title.ensure_image`, `render_check.make` and
`lrun.make` into their own build, and a module's own `make` of a makefile of
`src/native`), directly or through functions of `tests/` and `tools/` at
any depth, must be among the writers of its entry. `NOT_WRITES` lists the
calls the scan follows that do not write at run time (one:
native_level_load runs `frame8.main` with `--no-build`). A new kind of
shared write, or a module that only reads shared files, still has to be
added to the table by hand.

Written by one module only, so no race between modules: `ref816/runs/` and
`ref816/shots/` under names of their own (`test-calllog`, `divscan-title`,
`test-lump-*`, `capture-*`, `title.png`), `ref816/test-calllog`,
`ref816/test-divscan`, `ref816/test-dumps`, `ref816/test-lumps`,
`test-calls.log`, and native_frame8's fixed scratch directory
`tmp-m8-rdisk-f121` (deleted after). Everything else a test writes goes
in a `tempfile` directory of its own. `support.ref816_build()` and
`support.a2vm_build()` build with `make -B` into such directories too: the
canonical command makes each once, the runner once in each module that
uses it (more work, no race). Eighteen files still lower their own
priority with `nice -n 10` or `os.nice(10)`, from before the owner lifted
that limit: `tests/test_bridge.py` and `test_bridge_dumps.py`,
`tools/bridge/dumps.py` and `port.py`, and in `tools/native` bucketcheck,
frame8, framesynth, ldisk, lrun, mathcap, mathcheck, mathrun, rdisk,
render_check, rendercap, replay_check, routinesynth and sidecheck. The
runner does not change them. The make of `src/native/Makefile` reruns
`rowgen.py` every time (`gen/rows.s` is older than `rowgen.py`), which
writes only what changed, so it stays a no-op.

How the table was made (2026-10-01): every module was run alone, after the
canonical command, with an audit hook (`sys.addaudithook`) in every Python
process recording the files opened for writing or reading under `build/`,
the directories removed and made, the temporary directories and every
command started (`make`, `ref816`, `a2vm`, ...), and with a snapshot of
`build/` (size, time and SHA-256 of every file) before and after it. The
snapshots show what the C tools wrote; the command lines show what they
read. Then the sources were read for the writes that happen only when
something is missing or out of date (the makes, `ensure_image()`).

### The proof

On 2026-10-01, after the fixes of the runner's review (the image prebuild,
the tree kill, the guard, the limits set in the module, `tests/` paths),
with the 66 modules of that day, from one tree whose sources did not change
during the runs (a hash of `src/`, `tools/`, `tests/` and `docs/` before
and after each):

| Run | Wall time | Tests | Result |
| --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | 498.5 s | 1,412 | OK |
| `python3 tools/testpar.py` (9 jobs), first | 103.7 s | 1,412 | OK |
| second | 103.1 s | 1,412 | OK |
| third | 98.7 s | 1,412 | OK |

The same 1,412 test ids passed in each run (the serial run's from its
`-v` output, the runner's from `--json`). Snapshots of `build/` (SHA-256 of
every file) after each run differ only in `testpar-times.json`: no file
was added, removed or changed. A first try of the third pass (125.5 s, OK)
was set aside: another session started a whole runner pass in the same
tree a minute before it ended, and its snapshot caught that run's
temporary directory. The third pass above ran alone (no other runner or
`unittest discover` process during it).

A stale image, the case the image prebuild fixes: in a copy-on-write clone
of the tree, with `build/ref816/memory.img` cut to 1 MB and the times file
set so that coverage and ref816_machine run last, the 10 modules of the
image ran at 9 jobs: all 10 passed (162 tests), and the image was whole
again (2,663,420 bytes) before the first reader started. In the review's
run of the same case before the fix, 8 modules failed in the first pass.

The tree kill: a module running `bounded.run` on a shell loop that appends
to a file, interrupted after 3 s: with the old kill (the worker's process
group only) the file grew from 6 to 14 lines in the 4 s after the runner
returned 130 and the loop survived with PPID 1; with `kill_tree` it stayed
at 6 lines and no process was left. `RunModule` in `test_testpar.py` checks
the same for a timeout, with a process and its child each in a session of
its own; with the old kill both survive and the test fails.
