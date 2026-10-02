# The tests

`python3 -m unittest discover -s tests`, run from `demos/doom_gs`, is the
canonical command: one process runs every module, one after another (8
minutes on 2026-10-01 with 66 modules; not timed since: the 128 modules'
own times in the parallel run of 2026-10-02 add up to 5,141 s). Tests
that need `build/` skip with a clear message when it is missing. The ground rules are in
[`docs/MILESTONES.md`](../docs/MILESTONES.md#ground-rules).

Unit tests stay quick: a check that reruns a whole checkpoint or
acceptance (hundreds of frames, setups or routine cases) runs an even
sample by default, and all of it with `DOOM_GS_FULL=1` in the environment
(`support.FULL`; `support.every(items, step, keep)` takes every step-th
item and the ones `keep` names, or all of them with `DOOM_GS_FULL=1`). The
sample is fewer cases only: every routine, every path kind a test asserts,
every planted bug and every kind of assertion stay in the default run; a
count that a test checks against the whole capture (214 intermission
frames, 1,304 starts) is still checked on the whole capture, and the run's
own count against the sample. "All of it" is what the module ran before
it sampled; the acceptance commands themselves (`frame8.py`,
`level_check.py`, the tic checks, each part's `--check`) always run in
full. `test_native_game_skeleton`'s frame check on loaded levels was the
first (2026-10-01: all 729 frames took about 18 of its 22 minutes).

On 2026-10-02 the game parts' and milestone 11's modules made the
parallel suite about 48 minutes long (127 modules whose times added up to
14,119 s; `test_native_game_geom` alone 2,872 s). These modules now sample
by default, and the suite took 575.8 s with 9 jobs (128 modules, 2,092
tests, 0 failures, the 26 `DOOM_GS_FULL` skips; the modules' times 5,141
s), every module under 4.5 minutes and most under 3 (the longest:
native_game_skeleton 262 s, native_game_flow 216 s, damage, mobjstate,
geom and m11_s2amap 179-191 s; alone each takes 115-140 s, but they start
together, the longest first):

| Module | By default | With `DOOM_GS_FULL=1` (as before) |
| --- | --- | --- |
| native_game_geom | of each entry's chosen calls every 30th, then of those and the synthetic cases the first of each path (`paths_of`) and up to 3, and a call for any declared path left; the iterators' every 40th call; 10,000 random pairs a map and posMul inputs; the plants on 5,000 pairs, every 80th iterator call, every 20th `P_LineOpening` case | every case, the 434 iterator calls, 100,000 pairs, 20,000 a plant, every 20th and 5th |
| native_game_tracel | every 100th captured case (`TRACEL_SAMPLE`), a tenth of each random check's inputs (gOf's 65,536 all) | every 5th, every input |
| native_game_secfind | the entries of at most 10 cases whole, every 100th of the others; every 200th synthetic call a map; E1M1's six leveltimes (32,768 among them) and four button endings; the plants on every 10th finder call, every 30th `T_Glow` call with the two thinkers, four leveltimes | at most 40 whole, every 10th; every 20th; E1M1 and E1M3 whole; each plant's whole check |
| native_game_flow | 2 captured cases an entry and every synthetic one; the first and fourth world-done load; the loads each from one fill and profile in turn; the helpers on 1,000 inputs (signLong every 8th and the edges); each plant on 2 captured cases and the synthetic ones | 6 a case, 8 loads, both fills and profiles, 3,000 (signLong all), every case |
| native_game_skeleton | S1's setups of every 5th capture run, checkpoint B's loads of the nine maps in a row and E1M5 twice, every 60th loaded-level frame; S2's every 50th case; 2 in-play drops; S7's routine plants on 2 cases | every setup, the whole sequence (in reverse too), all 729 frames, every 10th, every drop, 8 |
| native_game_mobjstate | every 240th captured case; each synthetic group from one of ($A5, f121), ($5A, fastpath) in turn; the plants two at a time | every 8th, every group from both fills under both profiles, one at a time |
| native_game_pickup | every 60th captured and synthetic touch and random state; every 6th captured `C_Responder` call and every one that completes a cheat; each cheat once and each power once; the plants on every 10th touch | every 6th of each group, every cheat call and power case, every touch |
| native_game_lines | of each entry's chosen calls the first of each path (`paths.json`) and up to 4; the switches' first line and line 0 once and again a map, the buttons on E1M1-2; E1M1's use, exit and cross cases, every 8th `findSpecial` a map; the monster plant on every 50th use | the crossings and switches whole, every 10th use and choice, every 4th switch line, every map's cases, every 10th use |
| native_game_spawn | the first captured call of each (entry, path) and up to 4 an entry; each plant on 4 captured cases and its synthetic ones | every 8th, 40 |
| native_game_damage | every 80th captured case from both fills under both profiles; each synthetic group from one combination in turn; 20,000 thrust inputs | every 8th, every group from all four, 100,000 |
| native_game_sight | 2 calls of each path class an entry and at least 5; 20,000 random inputs; the plants on 2 cases (every 75th slope) | every 20th and 15th, 100,000, 10 (every 30th) |
| m11_s2ovl | every 4th frame and both titleBand frames, with their variants; the plants on ovl-10 and plain-01 | every frame, the four plant frames |
| m11_s2wi | every 4th intermission frame and each new picture injected, every 4th intermission chained; the plants on that sample from $A5 | every frame, both fills |
| m11_s2menu1 | every 4th frame and every open and close; every 4th `M_Responder` call and `M_Ticker` chain | all |
| m11_s2menu2 | every 6th frame of each run and the first of each page and kind; s2menu1's calls as above | all |
| m11_fxchan | every 5th captured call of each run; 1,000 random sequences | every call, 10,000 |
| m11_s2amap | the plants on every 3rd injected frame and every 2nd stretch chained | every frame |
| m11_s2stbar | newgame's native frames and tics, every 4th | all |
| m11_s2pal | every 2nd batch of 16 frames, the plants too | every batch |
| m11_s2fin | the plants from $A5 | both fills |
| m11_s2hud | the plants on newgame and automap (the synthetic cases all) | every run |
| m11_plinput | the plants at rate 35 | 10 and 35 |
| m11_fxplay | `fxrun65.checkpoint(quick=True)`: three of the 18 lone-effect combinations, three songs, every other scenario | the whole checkpoint |

Earlier modules that sample the same way: native_game_attack, checkpos,
missile, chase, look, path, evfloor (and the other parts with a `FULL`
switch); their `DOOM_GS_FULL` skips are the 26 skipped tests of a plain
run.

## The parallel runner

`python3 tools/testpar.py` runs the same modules with the same results in
a fraction of the time (on 2026-10-01, 66 modules: 100 s instead of 500 s
on the owner's Mac; on 2026-10-02, 128 modules: 576 s). Each module runs in a process of its own, loaded
the way the canonical command loads it (unittest's `discover` from
`tests/`, with the pattern `<module>.py`). Up to 9 run at once (`--jobs N`),
the longest first, from the times of the last run (`build/testpar-times.json`,
one number a module, rewritten each run). Each has a time limit (`--timeout`,
1,200 s by default; `MODULE_TIMEOUTS` gives `test_native_game_skeleton`,
milestone 10's checkpoint S with milestone 9's whole acceptance, and
`test_native_game_geom` 3,600 s, which they need with `DOOM_GS_FULL=1`)
and the bounds of `tools/ref816/bounded.py`, which the
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
conflicts, and module names run only those modules. A work-in-progress
module, `tests/wip_test_*.py` (a part's test while it is built,
[`docs/SCREENS.md`](../docs/SCREENS.md) 7.1), is outside the pattern, so
neither the canonical command nor a run without names takes it; it runs
when named (`test_testpar.py` checks both).

```
python3 tools/testpar.py                     # everything, 9 at a time
python3 tools/testpar.py test_native_render  # one module (or tests/test_native_render.py)
python3 tools/testpar.py --list              # the order, nothing run
python3 tools/testpar.py tests/wip_test_PART.py      # a work-in-progress module, by name
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
| `ref816/ref816` | `make -C tools/ref816 build/ref816/ref816` (`title.build_machine()`) | ref816_calllog, ref816_capture, ref816_divscan, ref816_dump, ref816_inject, ref816_trace, ref816_machine, coverage, bridge_dumps (when it is missing), native_game_skeleton (milestone 10's tools: `gamecap.py`), native_game_lockstep (`ticrun.py`'s start captures) | native_frame8, native_math, native_replay | prebuild |
| `ref816/memory.img`, `loader.img`, `disk.hdv`, when missing | `title.ensure_image()` | ref816_calllog, ref816_capture, ref816_divscan, ref816_dump, ref816_inject, ref816_trace, interpreter, bridge_dumps (in `tools/bridge/dumps.py`), native_game_skeleton (`gamecap.py`), native_game_lockstep (`ticrun.py`) | the same | prebuild: `make_image.main([])`, which rewrites them as coverage and ref816_machine do, so a stale image is replaced before any module reads it |
| `ref816/memory.img`, `loader.img`, `disk.hdv`, always | `make_image.main([])`: `write_bytes` and `copyfile`, in place | coverage, ref816_machine | ref816_calllog, ref816_capture, ref816_divscan, ref816_dump, ref816_inject, ref816_trace, interpreter, bridge_dumps (the machine reads them) | exclusive |
| `gen/drawcol.s`, `gen/loadfont.s`, always | `frontend.generate()` (`support.frontend_results()`) | cppcheck, frontend, imgmatch, release, sections | the same | exclusive |
| `native/math/mathref` | `make -C tools/native` | native_math | native_render (`sidecheck.MATHREF`) | prebuild |
| `native/math/obj` | `math.mk` with `TABLES=build/native/math/tables` | native_math | | prebuild |
| `native/obj` | `src/native/Makefile` (the replay) | native_replay | native_render_frame (`loader.read_build()`) | prebuild |
| `native/render/obj` | `render.mk` (`render_check.make()`) | native_frame8, native_masked, native_masked_b, native_render, native_render_frame, native_render_walls | native_level_load, native_game_skeleton | prebuild |
| `native/levels/obj` | `level.mk` (`lrun.make()`; `play.mk` runs the same make first, for the load image it links) | native_level_load, native_level_setup, native_game_skeleton, play_runs, play_bench and play_cardprof (`playdisk.make()`) | | prebuild |
| `native/game/shared`, `native/game/skel` | `game.mk shared skel` (`grun.make()`): milestone 10's generated includes, `game.cfg`, the game manifests, the call graph, and the skeleton's test image | native_game_skeleton, native_game_lockstep (`ticrun.run()` makes the lockstep image `game`, `gprof` for its timing) | every part's test (`test_native_game_<part>`, from wave 1: they only read them; their skip message names `make -s -C src/native -f game.mk shared skel ROOT=$PWD`) | prebuild |
| `native/play` | `playdisk.make()` (`make -f play.mk`) in the module's `setUpClass` | play_runs, play_bench, play_cardprof | playtime (`ExactIdle` copies the directory, then runs its disk) | exclusive (speed wave 1) |

Nothing but the table says who writes where, so a module added later that
writes shared files would race the others unseen: a plain failure now and
then, or no failure and a different `build/`. `Tables` in
`test_testpar.py` guards the known writers: every module that calls one of
`WRITER_CALLS` in `tools/testpar.py` (`support.frontend_results`,
`match_results`, `release_targets`, `make_image.main` without `--out`,
`title.build_machine`, `title.ensure_image`, `render_check.make`,
`lrun.make`, `grun.make` and `playdisk.make` into their own build, and a module's own `make` of a makefile of
`src/native`), directly or through functions of `tests/` and `tools/` at
any depth, must be among the writers of its entry. `NOT_WRITES` lists the
calls the scan follows that do not write at run time (two:
native_level_load and native_game_skeleton run `frame8.main` with
`--no-build`). A new kind of
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
