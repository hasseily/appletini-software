# Speed plan, wave 1, part `measure`: exact, repeatable timing of the play build

Written 2026-10-02 for the integrator (SPEED.md section 7). This part covers SPEED.md section 4, item 3 (the a2vm idle artifact), and builds the timing tool that section 7 step 4 names (`tools/native/playtime.py`). Nothing of the game changes: no source of `src/native`, no build, no frame, no demo sync.

## What it does

### 1. The idle artifact, fixed in a2vm and in playdisk.run

- **The cause.** `playdisk.run` passed `--idle dl_bwait:vbl` and `--idle dl_mwait:vbl` with no condition. a2vm then jumped to the next VBL every time the PC reached `$A66C` (`dl_bwait`), in two cases where the card does not wait there:
  - a tic was already due;
  - another group's code sat at `$A66C`, because `dl_bwait` lives in slot 2.
- **New a2vm idle conditions** (`tools/a2vm/main.c` `add_idle`, `a2vm.c` `skip_idle`, `a2vm.h` `a2vm_idle`):
  - `byte=A,V`: the main byte at A holds V. A loop may have at most 4 of them.
  - `eq=A,B` now also reads the main language card: write the address as `lc.ADDR`, in `$C000-$FFFE`. The old form, with main words, behaves as before.
- **playdisk.run** (`run()` only) now passes these two loops by default (`idle='exact'`):
  - `dl_mwait`: `vbl:main:eq=lc.CLK_TICS,DL_LASTM`.
  - `dl_bwait`: `vbl:main:byte=SLOT_GRP+slot,XS_DLG_BRAIN:eq=lc.CLK_TICS,DL_LASTM`.
- **Where the values come from.** Every address is read from the play link's labels and symbols:
  - `dl_bwait` and `dl_mwait` are labels.
  - `SLOT_GRP`, `TW_SLOTn` and `TW_SLOTn_END` give the slot that holds `dl_bwait`.
  - The rest are symbols: `XS_DLG_BRAIN`, `CLK_TICS` and `DL_LASTM`.
  - With the build of 2026-10-02 the result is `BD0:vbl:main:eq=lc.E407,1F01` and `A66C:vbl:main:byte=19EE,1D:eq=lc.E407,1F01`.
- **Why the skip is now exact.** Both loops are `jsr pl_time / cmp DL_LASTM / beq loop`. `pl_time` returns `CLK_TICS`, which only the VBL interrupt changes. When the two words are equal and the brain's group is in the slot, the loop spins until the next VBL, so a jump to it gives the same frames.
  - Measured: on the title loop, where the skip fires (35 FPS, 1.9 s skipped in 12 s), and on demo3 (17.0 s skipped in 200 s), the exact skip gives the same frames, times, tics and loads as a run with no skip at all.
- **The other choices.** `run(idle='old')` keeps the unconditioned skip, so the artifact can still be measured. `run(idle='none')` skips nothing.
- **New run() parameters.** `extra` passes more a2vm options (playtime's `--pclog`). `a2vm` selects the machine binary.

### 2. New a2vm options (README "Running it", "The PC log")

- **`--pclog FILE`**, with `--pclog-pcs LIST` (at most 64), `--pclog-bytes LIST` (at most 16, main or `lc.`), `--pclog-from N` and `--pclog-limit N` (default 1,000,000 lines).
  - It writes one line before each instruction run at those PCs: `CLOCK PC A X Y S ALTZP BYTE...`.
  - The line comes after the idle skip. There is no line for an interrupt's entry or for a waiting CPU.
  - Once the limit is reached, the next line halts the run (exit status 1), so a log is either complete or the run fails.
  - The log only observes: a test checks that the state is identical with it and without it.
- **`--stop-word ADDR:N`** ends the run (end `stop-word`) once the 32-bit main word at ADDR, having been below N, is at least N. The condition counts only after the word has been below N, because the poison image fills `G_GAMETIC` with a large value before the game sets it.

### 3. `tools/native/playtime.py`

```
python3 tools/native/playtime.py --scene still|walk|demo3 --profile f121|fastpath
    [--disk FILE] [--play DIR] [--gametics G0-G1] [--window S0-S1]
    [--seconds S] [--idle exact|old|none] [--json OUT] [--keep DIR]
```

- **The disk.** The default is `build/native/DOOM.hdv`. It is checked byte for byte against the disk that `--play` builds (default `build/native/play`), so the labels belong to that disk.
- **The scenes.**
  - `still`: a new game, frames in 15-25 s.
  - `walk`: the up arrow held and `mouse 160 0` every 2 s, frames in 14-32 s.
  - `demo3`: the title loop's demo, frames whose end gametic is in (1052, 1796]. The run stops at gametic 1797 through `--stop-word`. It fails when it does not get there; give `--seconds`, default 200.
- **The data** comes from `--pclog` at these labels:
  - `k_end`, `k_tic1`, `k_load`, `k_call`, `k_jsr` (whose operand names the call), `k_wload`, `k_mload`, `k_menu` and `dl_halt`;
  - `XS_far_pload` (its Y names the image of a K_LOAD), the tic image's `gr_load`, and `XS_pl_vbl`.
- **Where the log lines come from.** No fixed address is used: every PC is a label or symbol of the play link. The bytes logged are `k_jsr+1` and `k_jsr+2` in the card, and `G_GAMETIC`.
- **Output.**
  - ms a frame: mean, median and max.
  - FPS, tics a frame and tics a second.
  - Each kernel step in ms a frame: K_TIC, K_WLOAD, nr_frame, K_MLOAD, nm_masked, nm_bkload, nb_frame, K_LOAD P2DW, s2_frame, and any other step by name.
  - gr_load calls a tic (in K_TIC only), VBL interrupts a frame, and the idle time skipped.
- Each run lives in a `build/tmp-playtime-*` directory that is deleted afterwards.

## The check, and the measurements

The checks:

- `python3 -m unittest test_play_runs` (from `tests/`): 8 tests, OK, 73.5 s. This is the play runs' check with the new idle as the default.
- `python3 -m unittest test_playtime test_a2vm_pclog`: 15 tests, OK, 13 s. `test_playtime.ExactIdle` runs the title loop twice, once with the exact skip and once with none, and requires the same frames.
- Two planted bugs, each caught, then removed:
  - the byte condition ignored in `skip_idle`: 2 failures in `test_a2vm_pclog`;
  - the exact skip without its tic-due condition: `ExactIdle` failed, 207 frames against 208.
- `make -B -C tools/a2vm OUT=... all`: no warnings.

The measurements (a2vm f121 unless marked) used `build/native/DOOM.hdv` of 17:45, the owner's build, and a copy of the `build/native/play` that builds it byte for byte.

| Scene | Command | Old idle | Exact idle (card-equivalent) | Gain |
| --- | --- | ---: | ---: | ---: |
| still, 15-25 s | `playtime.py --scene still` | 190.6 ms, 5.25 FPS | **180.7 ms, 5.53 FPS** (median 180.3, max 193.3), 38.84 loads a tic | −9.9 ms, +0.28 FPS |
| still, fastpath | `playtime.py --scene still --profile fastpath` | | **154.3 ms, 6.48 FPS** | |
| demo3, gametics 1052-1796 | `playtime.py --scene demo3` | 883.3 ms, 1.13 FPS (the old run reached only gametic 1788 in 200 s) | **873.3 ms mean, 877.2 median, 1,656.1 max, 1.15 FPS**, 240.9 loads a tic | −10.0 ms |
| walk, 14-32 s | `playtime.py --scene walk` | 465.9 ms, 2.15 FPS | 376.0 ms, 2.66 FPS | not like for like (below) |

- **Run with `--idle none`,** still, walk and demo3 give exactly the figures of the exact column. That column is the card-equivalent one that SPEED.md 1 asked for, the same as the scratch `NOIDLE=1`.
- **Every SPEED.md 2 target is reproduced:**
  - still: 180.7 card-equivalent and 190.6 with the old idle, 38.9 loads a tic;
  - demo3: 873.3 ms mean, 877 median, 1,656 max, 1.15 FPS, 241 loads a tic;
  - fastpath still: 154.3 ms.
- **The steps match SPEED.md 2.**
  - Still: K_TIC 112.1, K_WLOAD 4.95, nr_frame 26.5, K_MLOAD 2.55, nm_masked 3.84, nm_bkload 0.21, nb_frame 26.5, P2DW 1.98, s2_frame 2.04.
  - demo3: K_TIC 785.3, nr_frame 22.3, nm_masked 7.62, nb_frame 44.8, s2_frame 3.54.
- **Host time** for one run: still 13 s, walk 21 s, demo3 about 100 s.

## For the integrator (files this part does not own)

1. **SPEED.md section 1.**
   - Replace the "Commands" list with:
     - `python3 tools/native/playtime.py --scene still --profile f121`
     - the same with `--scene walk`, with `--scene demo3` (gametics 1052-1796 by default), and with `--profile fastpath`.
   - Change the artifact paragraph's first sentence to: "`playdisk.run` passed ... (fixed by part measure: the skips are now conditioned on no tic due and, for `dl_bwait`, the brain's group in slot 2; `playtime.py --idle old` measures the old skip)". The old skip cost 9.9 ms a frame standing still; SPEED's 9.7 was the profile of the one PC.
   - In section 4, row 3 is done.
2. **SPEED.md section 5's "Today" row** stays 180.7 ms / 5.5 FPS and 873 ms / 1.15 FPS; it is now what `playtime.py` reports by default.
3. **PLAY.md section 8.**
   - The still row's 5.3 FPS / 190 ms was the artifact. The exact figure is **5.53 FPS, 180.7 ms**: K_TIC 112.1 ms, render (nr_frame + nm_masked + nm_bkload + nb_frame) 57.1 ms, loads and s2_frame 11.5 ms.
   - Replace the "To measure again" paragraph with `python3 tools/native/playtime.py --scene still|walk|demo3`.
4. **PLAY.md section 10.**
   - Add `python3 tools/native/playtime.py --scene still|walk|demo3 [--profile fastpath]` to the commands.
   - Add two rows to the test table:
     - `test_playtime`: the timing's reading (synthetic logs); the exact idle against no idle on the title loop.
     - `test_a2vm_pclog`: a2vm's idle `byte=` and `eq=lc.` conditions, `--pclog`, `--stop-word`.
5. **tools/testpar.py / tests/README.md race table.**
   - `test_play_runs` rewrites `build/native/play` (`playdisk.make()` in its `setUpClass`). `test_playtime.ExactIdle` reads it: it copies the directory first, but a copy taken during a rebuild could be torn.
   - Add `Shared('build/native/play', ('test_play_runs', 'test_play_bench'), ('test_playtime',))`. Both writers call `P.make()`; `test_play_bench` is part bench's new test. `test_play_glue` does not build the play link.
   - `test_play_bench`'s runs go through `playdisk.run`, so they get the exact idle by default. If the benchmark's frames wait in a loop other than `dl_bwait`, that loop is not skipped (exact, only slower on the host).
   - `test_a2vm_pclog` builds its own a2vm in a `build/test-a2vm-pclog-*` directory and touches nothing shared.
6. **The walk is not like for like across builds.**
   - Its input arrives on model time, so a faster or slower build turns at other gametics. The old idle walked 38 frames over gametics 156-308 at 112.6 loads a tic. The exact idle walked 47 frames over 160-348 at 93.9 loads a tic.
   - Compare builds on still and demo3. A gametic-locked walk would need input events by gametic, which a2vm does not have.
7. **Coordination with part `bench`.** `dl_brain.s` (bench) and `dl_kern.s` (being edited in the tree now) must keep:
   - the labels `dl_bwait` and `dl_mwait`;
   - their loops in the form `jsr pl_time / cmp DL_LASTM / beq`: no tic due ⇔ `CLK_TICS` = `DL_LASTM` as words;
   - `dl_bwait` inside one slot (`TW_SLOT1` or `TW_SLOT2`), in the group `XS_DLG_BRAIN`.
   - If the benchmark's loop waits for something else, its idle needs its own condition. `run()` raises `PlayError` if `dl_bwait` is in no slot. If a loop's form changes, `test_playtime.ExactIdle` (exact against none) fails.
8. **The shared binary.** `build/a2vm/a2vm` was replaced by the new build with an atomic `mv`. Its `.o` files in `build/a2vm` are older than the sources, so the next `make -C tools/a2vm` relinks it to the same program.
9. **A side effect of this part's check.** `test_play_runs`' `setUpClass` rebuilt `build/native/play` at 19:53 from the tree as it stood, including other wave-1 parts' uncommitted changes to `dl_brain.s`, `gcall.s` and others. `build/native/DOOM.hdv` (17:45) was not rebuilt, so the two no longer match until the integrator's `playdisk.py` run. `playtime.py` refuses a disk that does not match its play link and says so.
