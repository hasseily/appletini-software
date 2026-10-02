# Speed plan, wave 1, part `place`: the tic code placed by the machine's cost

Written 2026-10-02 for the integrator (SPEED.md section 7). This part covers SPEED.md section 4, item 1. It changes only where code lives: no source of `src/native` changed. The game's state and frames stay the same (the lockstep run below).

## Results

| a2vm f121, card-equivalent | still E1M1 (15-25 s) | demo3, gametics 1052-1796 (186 frames) |
| --- | ---: | ---: |
| HEAD, the owner's build | 180.7 ms, 5.53 FPS, 38.84 loads a tic | 873.3 ms, 1.15 FPS, 240.9 loads a tic |
| Part paging alone (HEAD's placement, far_gcopy, lazy restore) | 143.64 ms, 6.96 FPS, 36.61 | 626.37 ms, 1.60 FPS, 238.65 |
| **Paging + `gplace-wave1-lazy.json`** (the placement to integrate) | **93.61 ms, 10.68 FPS**, 11.42 | **275.83 ms, 3.63 FPS**, 63.50 |
| This part alone: `gplace-wave1-eager.json`, HEAD's gcall.s | 118.43 ms, 8.44 FPS, 18.71 | 382.40 ms, 2.62 FPS, 90.73 |
| This part alone: `gplace-wave1-lazy.json`, HEAD's gcall.s | 146.18 ms, 6.84 FPS, 38.70 | 514.99 ms, 1.94 FPS, 163.23 |

- **With part paging, this part's gain is −50.0 ms a frame standing still and −350.5 ms a frame in demo3.**
  - Standing still now runs at 35 tics a second (3.27 tics a frame).
  - demo3 still draws 4 tics a frame, the same frames as the base.
  - The tic phase falls from 75.3 to 25.0 ms a frame standing still, and from 538.4 to 187.7 in demo3.
- **On its own, with HEAD's eager restore and per-page copy, the eager file** gives:
  - still: −62.3 ms a frame (SPEED.md expected −68);
  - demo3: −490.9 ms a frame (SPEED.md expected about −490), with 489 pages a tic, 49 ms a tic of copy at 100.3 µs a page (SPEED.md expected 35-45 ms).
- **The model predicted every figure in the table.** Each load count above is gsim's on the recordings, to the second decimal:
  - still: 11.25, 18.69, 38.69 modelled against 11.42, 18.71, 38.70 measured. Still's window holds other frames in each build.
  - demo3: 63.50, 90.73, 163.23 modelled and measured.

Measured with this part's recorder in scratch APFS clones of HEAD: clone A, HEAD plus the placement; clone B, HEAD plus paging's `gcall.s`, `gdriver.s`, `dl_kern.s` and `glayout.py`, plus the placement. In each clone:

```
rm build/native/play/tic/gen/stamp; python3 tools/native/playdisk.py
python3 tools/native/gplacerec.py still demo3w --jobs 1 --no-build --out DIR
```

The base rows are the same command on HEAD and on clone B with HEAD's placement. They match SPEED.md 2 and paging.md: 180.7 / 38.84, 873.3, 143.64 / 36.61, 626.37.

## What it does

### 1. The recorder: `tools/native/gplacerec.py` and `tools/gplace/gtrace.c`

- **No change to a2vm.** a2vm's existing `--write-log` of the stack page, `SLOT_GRP`, `FC_T`, `FC_GRP` and `G_GAMETIC` shows every call of the tic image. The log goes through a FIFO in a `build/tmp-gplacerec-*` directory into `gtrace`, so it never touches the disk.
- **How gtrace reads it** (its header has the details):
  - A JSR is the two writes of one instruction at S and S − 1 with the value PC + 2. An interrupt pushes PC, a BRK a third byte, so neither passes for one.
  - Its target is read in the image's own bytes, with the slot's group as `SLOT_GRP` says.
  - `fc_call`, `dc_call` and the kernel's `jsr k_go` are named by `FC_T` and `FC_GRP`. That happens when `fc_go` pushes, or when `dc_call` writes `FC_T + 1` with `FC_GRP` 0 (a core entry).
  - A return is seen late: a push at S = a means every frame whose JSR wrote at an address up to a has returned. The returns therefore come out in order, before the next call.
  - `gr_load`'s writes of `SLOT_GRP` are the loads that happened, which gives the model's check.
  - **Phases.** A phase starts at the `$FF` that `k_tic` (play) or `core_in`/`drv_game` (lockstep) writes to `SLOT_GRP + 1`.
    - It ends at the kernel's next step (play), or at the driver's `jsr call_frame` or `jsr load` (lockstep). A tic with no frame keeps its slots.
    - A phase that the end of the run cuts is dropped.
  - The runtime range, whose writes are not calls, is gcall.s's code only. `build_map` refuses a range that overlaps a routine.
- **The units.**
  - The part table's routines, by `file:label`. A routine's range ends at the next table label, or at a label after a `.segment "GCORE"`: `g_resume`, `weaponinfo`.
  - The core's other code (`@core`).
  - Each glue group of the play link.
- **The scenes** (`SCENES`):
  - `still`, `walk` and `fight`: E1M1 after NEW GAME, model-time windows.
  - From the title loop, by gametic: `demo3` (1052-1400), `demo3b` (1400-1796) and `demo3w` (1052-1796, SPEED.md's).
  - From the lockstep build: `lock3a` (2440-2640) and `lock3b` (2900-2990).
  - Each scene writes `build/native/game/gplace/SCENE.ev` and `SCENE.json`.
- **It also measures the frame.** A phase starts at each `K_TIC`, so the run gives:
  - ms a frame from one start to the next;
  - the tic phase's ms, tics, loads and pages.
  - The play scenes run without the idle at `dl_bwait` (card-equivalent).
  - On the owner's build it reproduces SPEED.md 2 exactly.

### 2. The model: `tools/native/gplacesim.py` and `tools/gplace/gsim.c`

- **What gsim does.** It replays a scene's calls and returns through `gcall.s`'s paging, under any placement:
  - A call to a group other than the caller's is an `fc_call`, costed at `--call-us` (5 µs).
  - The call loads the target's group when the slot holds another.
  - At the return, the saved group comes back: `eager` (HEAD: the slot's group at the call) or `lazy` (paging's `SLOT_NEED`).
  - It answers loads, pages, fc_call calls and tics, in about 1 ms a placement for the four training scenes.
- **The check** (`gplacesim.py --check`): each scene, replayed under its own build's placement, must give exactly the loads its run recorded. All seven do, with no phase differing:
  - still 11,068 loads;
  - walk 13,042;
  - fight 17,642;
  - demo3 63,142;
  - demo3b 75,458;
  - lock3a 49,610;
  - lock3b 22,400.
- **Across placements.** These scenes were recorded under the final placement. Replayed under HEAD's placement, they give the loads that HEAD's own runs recorded: demo3 220.82, demo3b 258.55, lock3a 409.09, lock3b 418.32 loads a tic, all equal.
- **The lazy restore.** The model's figures agree with paging's measurements:
  - still 38.88 → 36.63, measured 38.8 → 36.6;
  - demo3 −2.25, measured −2.2;
  - E3's still 17.50 → 15.25, measured 17.7 → 15.4 (SPEED.md 3, E1L).
  - The tic profiler's −35% was that dry run's own error.
  - A placement trained for the lazy rule gains much more from it: still 18.71 → 11.42 measured.

### 3. The placement: `tools/native/gplace.py`

- **The cost.** Pages loaded × `--page-us` (100.3 µs today, 63.8 with far_gcopy, the default), plus `--call-us` (5 µs) for each call through fc_call.
  - It is computed under `--restore auto|lazy|eager`.
  - `auto`, the default, takes the builds' own restore: lazy when their `ggame.inc` has `SLOT_NEED`. Builds that disagree are refused.
- **Training.** The objective is the sum, in ms a tic, over `TRAIN`: still, walk, demo3 and lock3a. `HOLD` (fight, demo3b, lock3b) is evaluated only.
- **The search** is deterministic for a given `--seed`:
  1. It starts from `--placement FILE` or the current `placement.json`.
  2. **Repair:** while a rule is broken, it makes the cheapest move that shrinks the breach, or merges a whole group into another.
  3. **Sweeps** of single moves:
     - each hot unit to the core, to another group, or to a new group in either slot;
     - each group to the other slot;
     - two hot units exchanged.
  4. **Annealing** with `--anneal` steps (default 40,000, about a minute), then the sweeps again.
  - `--no-search` takes the placement as it is, after checking every rule.
- **The rules.** Every candidate is checked against all of them:
  - AFFINITY units move whole, split only by source file.
  - A_Chase's callees never share A_Chase's slot.
  - The APART pairs never share a slot.
  - `hard_refs`: a routine that reaches another without FCALL keeps it in its group or in the core.
  - `placement_asserts`: the sources' `.assert GP_x_G`. sight.s keeps `P_CheckSight` in the core for its test entries; the lockstep build stops otherwise, as a first try showed.
  - A group holds at most 2,048 − `GROUP_MARGIN` B.
  - There are at most **43 groups**. The play disk's `CODE.2` is one bank file of at most 49 segments: W and the core, 5 glue groups and the game's. A 47-group try failed in `lstore.bank_file`.
  - The groups' pages pack into GCODE0 and GCODE1.
  - Core: the table routines plus each build's fixed core code fit in 13,312 − `CORE_MARGIN` − `--core-reserve`.
- **The sizes** are measured.
  - Each routine is measured in every linked build (the play tic image, `game`, `gprof`), each under its own placement.
  - Then ±3 B for each FCALL site that the placement turns into or out of `fc_call`. The sites come from the sources, a macro's FCALLs counted where it is used, and are exact from the links where a site is `fc_call`.
  - A build whose `gplace.inc` is newer than its map is refused (a failed link).
  - **Checked on the final links:** every group's bytes matched in all three builds, and the core in `game` and `gprof`. In the play link the core is predicted 13 B high: the test-only bytes of P_CheckSight.
- **P2.** The core budget is the largest fixed core of all the builds, so the play link's `dl_hook.o` and the lockstep's `ghook.o`/`grec.o` are both counted. Today the lockstep builds bind: gprof 10,063 B against play 9,791 B.
- `--heuristic` keeps waves 1-6's placement, with its cost now counted in pages.

### 4. The placements delivered

| File | For | Groups | Core: table + gprof's fixed | Training cost (ms a tic, summed) |
| --- | --- | ---: | ---: | ---: |
| `tools/native/gplace-wave1-lazy.json` | wave 1 with part paging: **the one to integrate** | 43 | 3,215 + 10,063 = 13,278 of 13,312 B (CORE_MARGIN's 16 B and 16 B more kept free) | 66.70 (lazy, 63.8 µs) |
| `tools/native/gplace-wave1-eager.json` | HEAD's gcall.s, if paging's lazy restore is not integrated (not run in lockstep) | 43 | 3,208 + 10,063 | 88.28 (eager, 63.8 µs) |

Modelled ms a tic of copy and calls (`gplacesim.py --eval FILE --restore R --page-us P`):

| Placement | Setting | still | demo3 | demo3b (held out) | lock3a | lock3b (held out) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| HEAD | eager, 100.3 | 24.02 | 156.49 | 186.06 | 305.10 | 311.62 |
| HEAD | lazy, 63.8 | 14.56 | 99.01 | 117.86 | 193.47 | 197.63 |
| **lazy file** | **lazy, 63.8** | **3.17** | **21.34** | **23.40** | **35.13** | **38.96** |
| eager file | eager, 100.3 | 8.49 | 47.55 | 51.07 | 66.86 | 78.93 |
| eager file | lazy, 63.8 | 4.84 | 29.79 | 32.05 | 42.75 | 50.43 |
| lazy file | eager, 100.3 | 15.44 | 78.34 | 86.39 | 100.99 | 108.86 |

The lazy file is the better one only with the lazy restore. Without it, it keeps still at 38.7 loads a tic, because its groups share slots with their core callers. That is why the restore setting is `auto` and why the eager file exists.

## The check (the owner's rule: one lockstep run)

In clone A, with `gplace-wave1-lazy.json` as `build/native/game/shared/placement.json` and every build relinked:

- `playdisk.py`: core 12,993 of 13,312 B, 43 groups.
- `make -f game.mk game gprof release skel`: no warnings; the cores are 13,268 B (game) and 13,278 B (gprof).

```
python3 tools/native/ticrun.py --run demo3 --frames front --fills a5 --jobs 2
```

**Result: ok.** Gametics 1051-3185, 2,134 tics compared, 0 failures. `same_pair_hits` 1009/1009, no tic differing. 113 s.

This was the second run. The first one, on an earlier placement, was also ok. Its recordings had missed the calls made from the core's code: the runtime range wrongly spanned gcall.s's GCORE tables up to its code. The measured demo3 loads (186.3 a tic) then disagreed with the model (160.8). The recorder was fixed, `build_map` now guards against it, and the seven scenes were recorded again and the placements retrained. The run above is on the final placement.

Two planted bugs, each caught and then removed:

- gsim restoring at every return: 2 failures in `test_gplace_model`;
- gtrace losing the returns of the outermost frames: 1 failure.

## For the integrator (files this part does not own)

1. **The recordings.** The seven scenes are in `build/native/game/gplace/` (6.8 MB). They hold calls between routines by name, so they do not depend on the placement.
   - To record them again: `python3 tools/native/gplacerec.py still walk fight demo3 demo3b lock3a lock3b --jobs 2` (about 8 minutes).
   - It needs a play link and a lockstep build of one placement, as `make` leaves them.
2. **Taking the placement**, after paging's files are in. This replaces SPEED.md 7, step 1.
   1. `python3 tools/native/gplace.py --placement tools/native/gplace-wave1-lazy.json --no-search --write`
      - It checks every rule against the builds' sizes and writes `placement.json`.
      - On the tree's builds as they stood while I wrote this, it passes (`--restore lazy` given, as only the play link had paging's edits then): play's fixed core 9,805 B with bench's and paging's edits; the test builds not yet rebuilt.
      - Paging adds 10 B to every build's core. The 18 B left free (the 16 B kept and 2) cover it, with 8 B to spare.
      - If bench's `ghook.s` adds more, drop `--no-search`. The repair then moves the cheapest unit out of the core, and the search refines it (about a minute).
   2. Make the play link follow it. `src/native/play.mk`'s `$(TIC)/gen/stamp` does not depend on `placement.json`, so `playdisk.py` alone keeps the old groups.
      - For now: `rm build/native/play/tic/gen/stamp` before `python3 tools/native/playdisk.py`.
      - The fix: add `$(wildcard $(ROOT)/build/native/game/shared/placement.json)` to that rule's prerequisites, as game.mk's image stamp has.
   3. `make -s -C src/native -f game.mk game gprof release skel ROOT=$PWD`, then SPEED.md 7, step 2.
   4. Later waves: `python3 tools/native/gplace.py --write`, which starts from the current placement.json. Use `--core-reserve N` for growth the builds do not have yet.
3. **GAME.md 4.3.**
   - Rule 4's cost becomes: the pages loaded × the measured cost of a page, plus 5 µs a call through fc_call, under gcall.s's restore, on recorded call traffic.
   - The rules list becomes: A_Chase, APART, AFFINITY by source file, the sources' asserts, 43 groups, and the core counting every build's fixed code.
   - "A_Chase … go to the core first" is now the search's choice. This placement keeps A_Chase and P_CheckSight in the core.
4. **play-requests.md P2:** done.
5. **SPEED.md.**
   - Section 3: E's lazy restore result stands. Add: "a placement trained for it does gain: still 18.7 → 11.4 loads a tic, measured".
   - Section 5's wave 1 row: the results table above.
6. **Tests.** `tests/test_gplace_model.py`: 11 tests, 0.4 s. The scenes test reads `build/native/game/gplace`. It builds `build/gplace` through `make -C tools/gplace`, its own directory, and shares nothing else, so it needs no line in testpar's race table.

## Open problems

- **The search is a local search.** Seeds and starts reach different optima.
  - Training cost: 66.7-79.7 under the lazy rule, 88.3-102.7 under the eager one.
  - The delivered files are the best of several 200,000-300,000-step runs. A search with moves that evict a unit to make room could still gain.
- **`gplace.py --write` with the default anneal** (40,000 steps) from a poor start gives a worse placement than the files. Start from the file with `--placement`.
- **The recordings are HEAD's code.**
  - A part that changes which routines call which needs them recorded again.
  - A routine with no recording is placed by its size alone.
  - The walk is not like for like across builds: its input runs on model time.
- **The model counts only the paging.** The other costs of K_TIC (the object API, the planes) do not move with the placement.
- **The lockstep run used HEAD's eager gcall.s.** Exactness does not depend on the restore. The lazy restore with this placement ran only in clone B's play-build timing runs (`gplacerec.py`), with no frame compared.
