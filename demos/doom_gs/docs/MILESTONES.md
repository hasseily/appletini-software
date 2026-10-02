# DOOM GS milestones: handoff brief

This file lets any engineer, or any AI agent, continue the port without the
conversation that started it. It states what is done, what is in progress,
and the exact specification and acceptance tests of the next steps.

Status as of 2026-09-30.

## Read first

1. [`README.md`](../README.md): what the port is, and the licensing rules.
2. The section "Direction since 2026-09-30" below: the owner chose a native
   65C02 rewrite. [`NATIVE.md`](NATIVE.md) is its architecture, once written
   (see the status table).
3. [`ARCHITECTURE.md`](ARCHITECTURE.md): the earlier virtual-65816 design.
   Its end state is superseded; section 0 (facts settled from the source)
   and section 7 (verification) still hold.
4. [`research/iigs-platform.md`](research/iigs-platform.md) and
   [`research/iigs-renderer.md`](research/iigs-renderer.md): how upstream
   works, with file and line references.
5. [`research/appletini-hardware.md`](research/appletini-hardware.md): what
   the target is fast and slow at.

## Goal

Port [Webifi's Apple IIgs DOOM](https://github.com/Webifi/iigs-doom) (GPL-2,
about 82,000 lines of 65816 assembly for the Calypsi assembler) to an
enhanced Apple //e with an Appletini card. The owner wants "their whole game
to run on 65c02 and the Appletini with the SHR techniques they use". The
Appletini's accelerator is a W65C02S soft core, so no 65816 code runs as is.

The approach, since 2026-09-30, is a native rewrite: every routine becomes
65C02 code with data layouts chosen for the 65C02, keeping upstream's SHR
techniques. Music is converted from the WAD's MUS songs to the Phasor. Every
step is checked against a reference that runs the original release. The
earlier plan, a virtual 65816 machine (ARCHITECTURE.md), was measured too
slow in milestone 3.

## Ground rules

These are firm. Breaking one is a defect even if the tests pass.

| Rule | Why |
| --- | --- |
| This directory is licensed GPL-2 (`LICENSE`), the owner's decision of 2026-09-30. Code rewritten from upstream is committed here under it. | The native port is a derivative of upstream, which is GPL-2. |
| Never commit upstream's own files, upstream's generated code, the release image, the WAD, ROM images or third-party test vectors. Fetch them into `build/`, which is ignored. | They are fetched pinned; the WAD and the ROMs are not ours to redistribute. This follows [The Bilestoad](../../bilestoad/README.md). |
| Nothing of upstream's `src/iigs/cal_integer.s` may leave `build/`: no copies, excerpts or translations of its code, and no routine written from reading it. The port's replacements are written from the call sites and the documented behaviour only. Facts about the file, such as its length or a `file:line` reference, are fine. | It is a copy of the Calypsi vendor runtime, licensed for that toolchain only. |
| The Calypsi manual extract stays in `build/reference/`. | Vendor copyright. |
| Emulated machines are deterministic: the same inputs give the same run, byte for byte. No host time, no randomness. | Lockstep comparison depends on it. |
| Python tools use the standard library only and run on Python 3.9 to 3.14. C tools are C11, standard library only, built by a `Makefile` with `-Wall -Wextra` and no warnings. | Reproducible builds on the owner's Mac. |
| Unit tests live in `tests/` and run with `python3 -m unittest discover -s tests` from this directory. Tests that need `build/` skip with a clear message when it is missing. `python3 tools/testpar.py` is the fast way to run the same tests, with the same results: it runs the modules in 9 parallel processes, makes the shared builds once before they start, and never runs a module that rewrites shared files at the same time as the other modules that use them (about 100 s instead of 500 s; [`tests/README.md`](../tests/README.md) has the race table and the proof of 2026-10-01). The canonical command stays the reference. | One command checks everything. |
| Batch runs (cost tables, captures, frame checks, many emulator runs) may use up to 9 parallel jobs (the Mac has 11 cores and 18 GB) at normal priority; no `nice`. Keep at least 3 GB of memory free. | On 2026-10-01 the owner lifted the earlier limit (4 jobs under `nice -n 10`, set when seven runs at full speed made the Mac sluggish on 2026-09-30): "I'm not really using the computer. Don't throttle the checks, raise the parallel jobs." If the owner says the Mac is in use again, go back to 4 jobs under `nice -n 10`. |
| Every run that writes files has a bound: dump streams and logs take a size or count limit, emulator runs a cycle or time limit, and a test fails rather than grows. Temporary output goes in a `build/tmp-*` or `tempfile` directory that is deleted after the run; scratch copies of the tree are deleted when the work is done. Check `df -h` before a large run. | On 2026-09-30 a test of `ref816 --dump-at` wrote a 90 GB stream in a scratch copy and filled the owner's disk, and an a2vm test with no cycle limit ran for over an hour. |
| Scratch space is shared: several agents of one session use the same scratchpad and `build/` at once. Put your temporary files in a directory of your own (`mkdtemp`, or a subdirectory named after your task) and delete only what you created; never delete by wildcard in a shared directory. | On 2026-10-01 two cleanups emptied the session's shared scratchpad and deleted other agents' files (a milestone 10 survey's call logs and the workflow scripts). |
| Only test what changed: a fix or optimization gets the one check that covers the code it touches (game code: one lockstep demo3 run; the renderer: `frame8.py` on about 20 frames; a menu or the kernel: a scripted run of that feature), then the fast full suite once. No playthroughs of other features, no reruns of earlier milestones' acceptance, no second poisoned fill, at most two planted bugs. | The owner, 2026-10-02: "Only test what changed because otherwise it'll take way too long", after asking the same day to "reduce the checks dramatically". |
| Do not weaken a test, and do not special-case game addresses or file names to force a result. Report what does not work. | Earlier stages were independently reviewed for exactly this. |
| Work on branch `claude/iigs-doom-port`. Commit only finished, tested milestones or documents. | The owner approved commits and pushes on this branch. |

## Setting up

From `demos/doom_gs`:

```
python3 tools/fetch_upstream.py            # clone at 8ea2eac, release image, into build/
python3 tools/v816/imgmatch.py             # assemble, link, compare with the release
python3 -m unittest discover -s tests      # all unit tests
```

The reference machine of milestone 2 (about 10 minutes for everything):

```
python3 tools/ref816/fetch_vectors.py      # 65816 test vectors into build/vectors/
make -C tools/ref816 vectors selftest machinetest
python3 tools/ref816/title.py              # boots the release to its title screen
python3 tools/ref816/run_script.py title newgame viewsize tour --twice
python3 tools/ref816/profile816.py --run   # traces, then docs/PROFILE.md
```

The target model and the interpreter of milestone 3 (about 15 minutes):

```
python3 tools/a2vm/fetch_vectors.py        # 65C02 test vectors into build/vectors/
make -C tools/a2vm all vectors selftest bench compare
python3 tools/a2vm/cost_report.py          # the cost model against the hardware
make -C src/vm sizes vectors selftest
python3 tools/ref816/make_image.py && make -C src/vm contact
python3 tools/a2vm/interpreter_report.py --run   # then docs/INTERPRETER.md
```

`make -C tools/ref816 clean` deletes all of `build/ref816`, and
`make -C tools/a2vm clean` deletes `build/a2vm/interp`; regenerate them
with the commands above.

`fetch_upstream.py` pins upstream commit
`8ea2eac8b650daf2cf66127c4be6d3f8654dd335` and the release image
`doom-hd.hdv` with SHA-256
`2716166dda1d87faf3bdec572ddcf652379a54da78f1dcccdd0897e00b23bd0d`. It also
accepts `--from-local-clone DIR` and `--from-local-image FILE`.

Host tools used so far: Python 3.14 from Homebrew, Apple clang, cc65 2.18,
Verilator 5.050. The Calypsi assembler itself is not needed: it is an x86-64
binary and the owner's Mac has no Rosetta.

## Status

| # | Milestone | State |
| --- | --- | --- |
| 0 | Hardware microbenchmarks on the Appletini | Not started. Needs the physical card and the owner. |
| 1 | Front end, 65816 assembler and linker, image match | **Done**, commit `89bb480f`. |
| 2 | Reference machine runs the release; measured profiles | **Done**, see the results below. |
| 3 | Target machine model with cost model; 65816 interpreter | **Done**, see the results below. |
| 4 | Native rewrite: architecture (`NATIVE.md`), with a measured experiment | **Written and reviewed** (two reviews, findings applied). **Reviewed by the owner** on 2026-09-30: every question of section 15 is answered, and section 15.1 says what each answer changes. |
| S1 | Sound: MUS to Phasor converter, player model, WAV renders (`tools/sound/`) | **Done**, commit `ae6a28bd`; the 6-voice fallback was removed on 2026-09-30 (owner's decision), and a card that cannot switch to native mode gets no music. Steals and writes at or below the design in every song. Awaits the owner's ear: `build/sound/*.wav`. |
| S2 | Sound: the 65C02 player (`src/sound/`), a2vm's AY log, slot-4 slowdown and interrupt bounds | **Done** 2026-09-30, reviewed once, the review's 7 defects fixed and checked by rerunning the tests. AY writes equal the model's at every interrupt, 13 songs, PAL and NTSC. Player's cost at window 512: 13.0-29.6 ms a second. Since 2026-09-30 one layout, native12: the 6-voice layout is removed from S1 and S2 (`NATIVE.md` 15.1, row 11), and on a card that cannot switch to native mode `snd_probe` answers `SND_NO_MUSIC` (`src/sound/README.md`, "No music"). |
| 5 | Native replay on captured records; byte-level memory map; ref816 capture and `--call` | **Done on a2vm** 2026-09-30, reviewed once, the review's 9 defects applied (8 fixed with tests, 1 documented). 0 differing bytes in aux `$2000-$9FFF`, 0 stray writes and upstream's screen-store count, on 15 captured frames (E1M1 still, E1M7 demo, E1M3) and 10 synthetic streams, from the captured and a poisoned screen. F1.2.1 replay: 16.9 ms still, 21.5-35.1 ms demo. `docs/MEMORY_MAP.md` settles the language card. **Card run 2026-09-30** (`docs/results/replay-card-2026-09-30.md`): all 15 CRCs OK; frames without fuzz within 0-7% of a2vm; frames with fuzz 11-40% slower (demo-10, demo-11 fail the 25% timing acceptance). **Cause found and confirmed** (`docs/results/fuzz-timing-2026-09-30.md`): the firmware coalescer scans every 256-byte page it drains, so scattered column bytes drain about 4 times slower than a2vm assumed, and the replay's RAMRD toggles around each fuzz record wait for two such drains. With the scan modelled (`build/fuzz-timing/a2vm-coalescer.patch`, to apply after milestone 6) every frame is within 0-7% of the card. Fix: draw the fuzz records after each strip in one RAMRD window (demo-10 46 to 33 ms); its disk `build/fuzz-timing/REPLAY-defer.hdv` **ran on the card on 2026-09-30: all CRCs OK, demo-10 48.1 to 36.2 ms, demo-11 49.3 to 36.2, every frame within 25% of a2vm, so milestone 5's acceptance is met**. Follow-ups done 2026-09-30: the fuzz queue is in `src/native` (the loader marks the shadows a later record overlaps as `K_FUZZNOW`), a2vm models the coalescer's page scan (the existing port's calibration unchanged at 248.6 ms), and the card runner times 200 runs and prints both loops. |
| 6 | Harness and math: ref816 `--dump-at`, `--call-log`, `--poke-file`, lump placement, division-by-zero scan; a2vm write log, lowest S, snapshot ranges, the zero-page pair (profiles `f121zp`, `fastzp`); state bridge v1 (`tools/bridge/`); native math | **Done** 2026-09-30, two verification rounds and fixes. Bridge: 35 dumps, 0 raw pointers, every byte accounted for, round trips exact. Math (`src/native/MATH.md`): every routine equal to upstream's on 1 million random plus every logged input. No division by zero in any coverage run or demo (31 of 46 divide sites ran). Tools now bound themselves: ref816 `--dump-limit`, a2vm's default cycle cap, `tools/ref816/bounded.py`. |
| S3 | Sound: the music disk (`build/sound/MUSIC.hdv` by `tools/sound/musicdisk.py`; `src/sound/music.s`, `aytime.s`, `music.cfg`), the AY timing test, the Doom configuration profile (`vtw.slowdown.cycles=32`) | **Done on a2vm** 2026-09-30, reviewed once, the review's 9 findings applied (7 checks and fixes with tests, the results and these tables updated). The disk boots through a2vm's MLI trap; 20 s of each of the 13 songs, every key (with the arrows' wrap, T while music plays, ESC and Q) equal player.py at every interrupt; the quit puts ProDOS's card back and the Phasor in Mockingboard mode; no music on a card locked to Mockingboard mode. Timing test: a write 41.01 cycles (40.4 us), tail 513.0 cycles at window 512 and 33.0 at window 32, FW-S1 9.2 cycles a write; its screen checked row by row. Not yet run on the card: the owner tests at milestone 12 (`tools/sound/README.md`, "The music disk"). |
| 7 | Renderer front end: frame setup, BSP walk, wall setup, seg loops, planes, to `R_DrawMasked` entry (`docs/RENDER.md`, `src/native`, `tools/native/levelconv.py`) | **Done** 2026-09-30: designed, reviewed, built in three stages, verified once and the verifier's 5 defects fixed. **Stage A built** 2026-09-30 (`docs/RENDER.md` "Stage A as built", `src/native/README.md` "The front end"): checkpoint A passes: the level converter on all nine maps with every check, the tables equal to the reference's, check A3 0 differences in 4,994,932 cases (so upstream's `c14Bounds` is dropped), and on 177 captured frames, each from two poisoned machines, the BSP walk's 3,595 wall calls, the sector stamps, the vertex angles computed and the frame-start clears equal to `ref816`'s with no stray write. The walk is slower than estimated on a2vm's model (7.2 ms standing still on F1.2.1, median 3.8 ms in demo3). **Stage B built** 2026-09-30 (`docs/RENDER.md` "Stage B as built"): `R_StoreWallRange` and `R_RenderSegLoop` with our own generator of the 13 loops (`tools/native/seggen.py`), the records, fills and spans; checkpoint B (acceptance 2) passes: in routine mode 1,010 calls of each routine equal to `ref816`'s (1,000 captured calls evenly over the frames, the coverage's additions, the synthetic cases for the paths no capture takes), both fills, 0 stray writes, all 13 loops, genColumn and vMask exercised, 62 calls with a sky column deferred to stage C; all 3,595 captured calls equal but those 62. Wall setup 6.0 ms and seg loops 10.9 ms standing still on F1.2.1 (routine mode), within the estimates; in demo3 2.8 and 6.7 ms (medians), above them. **Stage C built** 2026-09-30 (`docs/RENDER.md` "Stage C as built"): the plane stamps, the weapon skip, the sky and the patchless columns (`src/native/rsky.s`), the whole frame from `R_FillStamps` to `drawMasked` with the render window loaded by the phase loader; **acceptance 1 passes**: on the 15 `m5` frames, 50 each of `newgame`, `title` (demo3) and `tour`, the 12 `lights` frames and 10 synthetic frames (`tools/native/framesynth.py`: no weapon, the shadow weapon, the automap overlay, the stamps' refresh, patchless columns, the sky under a fixed colormap), 374 runs from both poisoned machines, every output of RENDER.md 2.4 at `drawMasked` equal to `ref816`'s (103,431 records, 3,925 drawsegs with their openings, clips, spans, stamps, weapon skip, validcounts, lines mapped, vertex angles), 0 stray writes (soft switches now included); **acceptance 2 closed**: all 3,603 wall and 3,604 seg loop calls equal, the 62 with a sky included; the milestone 5 replay on the native records gives `ref816`'s screen on its 15 frames (0 differing bytes). Timing (a2vm f121, not the card): the window load 4.54 ms; standing still the window and front end 30.0 ms against 20-38 estimated, demo3 20.1 ms median against 10.8-18.3 (the walk, wall setup and seg loops each above). **Verified** 2026-09-30: 5 defects, all confirmed and applied (`docs/RENDER.md` "Verification of stage C"): the write filter now allows only the vertex gather's entries in card bank 1 (a store into the phase loader is caught); a column seen from behind (a legal grazing view) no longer stops the frame but takes rules of our own, flagged in `RULES` and compared with upstream wherever it stays in its tables (RENDER.md 3.9; the owner's question 13 in `NATIVE.md` 15: such a frame differs from `ref816` in lockstep); the render stack budget raised to 112 B (79 B measured + 24 B IRQ); the synthetic frame `skyodd` shows a one-unit sky error; the record spill's row corrected. After it: acceptance 1 188 frames, 376 runs, 0 differences; acceptance 2 3,608 cases, 14,424 runs, all equal or ruled as required; the replay 0 differing bytes; standing still 29.8 ms, demo3 20.0 ms median. The owner answered question 13 of `NATIVE.md` 15 (the grazing-view rules) on 2026-09-30: a known difference, skipped and reported by name in lockstep. |
| 8 | The whole renderer: sprites, masked walls, the weapon, the bucket pass, the replay (`docs/RENDER-MASKED.md`) | **Done** 2026-10-01: built and verified on a2vm (three stages, then one verification round; not yet run on the card, which waits for milestone 12). Designed and reviewed. **Stage A built** 2026-09-30, on a2vm, not yet reviewed (`docs/RENDER-MASKED.md` "Stage A as built", `src/native/README.md` "The masked phase"): the patch store, sprite frames, patch headers, scale records and render things from the level converter (all 17 level sources pass every check, 18 since stage B's `synth-mwclose`, all 18 again on 2026-10-01; the overrun measured: up to 127 texels past a post, 124 bytes past a lump, so the 128-byte tails stay); the walk lists its sectors, and the masked phase projects their things and sorts the vissprites (`mproj.s`, 2,683 B of the masked image's 13,312). Checkpoint A passes: on milestone 7's 188 frames, 5 new synthetic ones and all 533 `demo3` frames, both fills, 1,452 runs, the 15,930 vissprites, their order, `FR_SKIP`, `W_WSK` and the listed sectors equal `ref816`'s, milestone 7's outputs unchanged, no stray write; the bucket pass's prototype equals `loader.py`'s bucketing and fuzz marks on 192 frames (1,073 B: 366 in the card, 707 in main `$0C00`). Timing (f121): the projection and sort 2.44 ms at demo3's median frame, 6.19 at worst; the bucket pass 1.37 µs a staged byte, 6.54 ms at the demo median, 19.25 at worst, slower than estimated: the heaviest fight now 5.9-6.2 FPS by the estimate. **Stage B built** 2026-09-30, on a2vm, not yet reviewed (`docs/RENDER-MASKED.md` "Stage B as built"): `R_DrawSprite`, `R_DrawVisSprite` (with the magnified runs and the shadows) and `R_RenderMaskedSegRange` natively (`msprite.s`, `mvis.s`, `mwall.s`), the model of upstream's list pages in every producer, the clip log. Checkpoint B passes: routine mode 2,145 captured calls, 4,290 runs from both fills, all equal; on 197 frames (milestone 7's 188 and 9 synthetic) and all 533 `demo3` frames, both fills, 1,460 runs, every record by column with its kind, `UPOFS`/`XPUSED` against `COLW`/`XPNEXT`, covered ranges, spans, `FZ_POS` and the clip log against the call log equal `ref816`'s, no stray write; `synth-mwlong` and `synth-pagefull` take a page's end, the extra pages and a flush and equal; milestone 7's frame mode passes again (394 runs); 15 planted bugs caught. Masked image 7,425 of 13,312 B, card bank 1 989 of 1,024 B. Timing (f121): the sprites and masked walls 2.55 ms at demo3's median, 17.34 at worst before the weapon, near the top of the estimate. **Stage C built** 2026-10-01, on a2vm, not yet reviewed or run on the card (`docs/RENDER-MASKED.md` "Stage C as built"): the weapon (its clip pass in the front end in place of milestone 7's seam, its draw from the converter's profiles or by `R_DrawVisSprite`, the flash), the bucket pass finished (batches in groups of three, the covered ranges' W addresses, the fuzz marks), milestone 5's replay after it, the whole frame into the SHR, the release build's `ST_RECORDS` policy, `RENDER.SYSTEM` and its disk. **Acceptance 1 passes**: on milestone 7's 188 frames, 13 synthetic frames and all 533 `demo3` frames, both fills, 1,468 runs, the record stream and every output at the masked phase's end equal `ref816`'s, each batch equals `loader.py`'s, all of aux 0 `$2000-$9FFF` equals the screen at `R_DrawLists`' return, 0 stray writes, 0 frames with `RULES` ≠ 0; the 69 poisoned screens equal their `--call` truth. **Acceptance 2 on a2vm**: `build/native/RENDER.hdv` renders `demo3-020` .. `119` with every CRC equal to `ref816`'s, chained and fully injected, under `f121` and `fastpath` (the owner's card run waits for milestone 12). Timing (a2vm f121, render only): 64.3 ms still, 72.5 ms at `demo3`'s median, 164.5 ms at its worst; with the tic estimates 14.1-14.9, 8.8-11.0 and 4.9 FPS, 3 to 10 of 533 `demo3` frames under 6 FPS; by VBL count 10.5 FPS (`fastpath` 12.1) over the disk's 100 frames. **Verified** 2026-10-01 (`docs/RENDER-MASKED.md` "Verification of stage C"): 7 defects, all confirmed, none rejected; 5 fixed with tests: (1) the game build could still stop: a batch ending exactly at the last area's end (now dropped), a batch list of 26 where up to 45 batches can come (`rlayout.py` now proves 45; the list moved to zero page `$71-$9E` and `DSX2`), and 6.1's column limits unbuilt (now the game build cuts a column past a batch's 8,192 bytes in the bucket pass and one past the replay's stage in the replay, `ST_RECORDS`; test builds still stop); (3) a bucket pass that broke the batches is now named after the replay's `BRK` (planted bugs require it, one more planted); (4) 6.1's 8× staging margin restated for the captured frames and measured by `frame8.py` on every run (11.9×; `synth-pagefull` 7.8×) instead of a hand-entered figure; (5) `W_WSK` captured at `R_DrawLists` (all frames captured again: only the P4 dumps changed; 0 in all 734); (6) the tables' and docs' level-source counts 18. After them: **acceptance 1** 734 frames, 1,537 runs (69 poisoned) all equal, 0 frames with `RULES` ≠ 0; **acceptance 2** `RENDER.hdv` rebuilt, 400 of 400 CRCs, VBLs `f121` 467/472, `fastpath` 417/414; timing unchanged (still 64.1 ms, `demo3` median 72.4, worst 164.4: 14.1-14.9, 8.8-11.0, 4.9 FPS with tics); 1,289 tests OK; `build/` +1.3 MB. **Open:** (2) the heaviest fight is under 6 FPS (3 to 10 of 533 `demo3` frames; candidates: optimisations 4, 5 and 10 of 6.2, the bucket pass and the replay, 101 of `demo3-036`'s 164 ms): planned as a performance pass after milestone 11, before the owner's milestone 12 test, once the tics are measured rather than estimated. Accepted 2026-10-01: (7) stage B's change to milestone 7's frame timing test (equal phase sums and interrupt counts, each phase within 100 cycles an interrupt, in place of equal seg-loop cycles), because the VBL interrupt lands by time and so in a neighbouring phase under the other profile, which made the old assertion wrong, not the code; 6.1 item 1's restatement for captured frames (`frame8.py` measures the margin on every run). Committed 2026-10-01. |
| 9 | Level loading: our own converter from `DOOM1.WAD`, the store, the loader, the native `P_SetupLevel` and the zone (`docs/LEVELS.md`) | **Done** 2026-10-01: built and verified on a2vm (three stages, then one verification round; not yet run on the card, which waits for milestone 12). Designed and reviewed 2026-10-01. **Stage A built** 2026-10-01, on the host, not yet reviewed (`docs/LEVELS.md` "Stage A as built"): `tools/native/maplumps.py`, `umodel.py`, `wadconv.py`, `lstore.py`, `lderive.py`, `llayout.py`, `setupcap.py`, `level_check.py`; `levelconv.py` format `render-level 3` (the side's sector in byte 7). Checkpoint A passes: 53 setups captured (51 W points), 0 bridge problems, every W dump's canonical state equal to its R dump's; on all 51 W dumps the converter's levels equal `levelconv.py`'s byte for byte but three named parts of upstream's history (`TXHT`, `FLATCM` past the map's flats, one flagged frame's two bytes), the window model equals the dumps (image, column memory, zeroed bank, `COLDIR`) and every game map lump the release's; the 13 level sources' static parts equal; `inplay.json`: E1M2 5 and E1M3 5 textures made only in play, no slot or tail reaching a free byte (no known difference). Beyond the checkpoint: the static steps (`LINES`, `GROUP`, `FLOOD`) on the host equal all 53 R dumps; the store loaded on the host (20 loads in a row, in reverse, twice) equals each map's `window.img` and, read back, `levelconv.py`'s levels. Store: 116 texel blocks in 31 banks, 410 lumps in 17, level parts 870 KB in 14 banks and the texel slack: 112 of 126 banks, 14 spare, no codec. `build/` +0.43 GB. **Stage B built** 2026-10-01, on a2vm, not yet reviewed (`docs/LEVELS.md` "Stage B as built", `src/native/README.md` "The level load"): `src/native/lload.s`, `lgeom.s`, `ldriver.s`, `lboot.s` (`LEVELS.SYSTEM`), `level.cfg`, `level.mk`; `tools/native/lrun.py`, `ldisk.py`, `level_check.py --load`, `frame8.py --levels loaded`; the store's directory fixed at STORE0 `$0200`. **Checkpoint B passes**: from both poisoned machines, the nine maps in a row, in reverse and E1M5 twice (40 loads), after every load the window equals `window.img`, read back it equals levelconv.py's level of the W dump slot for slot and the converter's harness level byte for byte, the static and derived canonical parts equal the R dumps', 0 stray CPU writes, 0 bytes changed outside the loads' places (whole-machine diff), stack 13 B; `LEVELS.hdv` boots on a2vm (`f121`, `fastpath`), every bank file in place, the same 20 windows. **Acceptance 2 passes**: `frame8.py --levels loaded`, 729 frames, 1,458 runs, all equal (5 synthetic frames with poked levels excluded by name). Loads (model, static part) 101-275 ms on `f121`, 58-152 on `fastpath`; boot 1.14 s on `f121`. `lload.s` 929 of 1,200 B, `lgeom.s` 2,059 of 2,000 B. 21 tests, 11 planted bugs caught. `build/` +0.04 GB. **Stage C built** 2026-10-01, on a2vm, not yet reviewed (`docs/LEVELS.md` "Stage C as built", `MEMORY_MAP.md` 16): the game core `src/native/gthink.s`, `gpos.s`, `gspawn.s`, `gweap.s`, `gspec.s`, `gvalid.s` and `lsetup.s` (`nl_setup`); the zone (`RTH` 2,026 slots, `MOBJA-C`, `ZONE0-1`); the manifest `native-level-1` with every dynamic kind and the bridge's `handle`, `sxbyte`, `bit` encodings; `tools/native/setupcheck.py`, `level_check.py --setup --flood --setup-timing --report-md`, the `wrap` capture; the setup disk. **Acceptance 1 passes**: 54 of 54 setups (with the reloads and the wrap capture) from both poisoned machines, canonical state equal to ref816's with 5.2's exclusions only, 0 stray writes, stack 27-29 B (+24 IRQ), every zone bound within the room (least margin 428), the reloads' static kinds equal their first loads'; the release wrap fix equal to the plain setup renumbered. **Acceptance 3 passes**: worst flood depths 23-93, all within 512. The disk: 20 setups on a2vm (`f121`, `fastpath`), every CRC as expected, boot 1.14 s (`f121`). Load and setup (model) 191-654 ms on `f121`, 116-399 on `fastpath`. Sizes 8,339 of 9,700 B (`gthink.s` + `gvalid.s` 1,252 of 700). Banks: 109 of 126. 24 tests, 9 planted bugs caught; the block walk's order is not observable at the captured setups (a design error, recorded). `build/` +0.04 GB (3.49 GB in all). **Verified** 2026-10-01 (`docs/LEVELS.md` "Verification of stage C"): 7 defects, all confirmed, none rejected; 5 fixed with tests, 2 recorded as open items where the task allowed it: (1) a test that errored without `build/` now skips (`test_include_names`; the three level test files without `build/`: 85 tests OK, 47 skipped); (2) `G_PlayerReborn`'s resets were never observed (the reborn players at E already held the reset values): a capture `reborn-kit` gives the player a kit before `PST_REBORN`, and `G_PlayerReborn` without its clear, planted, fails on it with 11 differences; (4) the block walk's order: a synthetic setup `secorder` (`tools/native/secorder.py`: three E1M1 things moved, in ref816's `THINGS` lump and the native store alike, to block corners where the order shows) equals ref816's, and the walk with y outer, planted, fails on it (12 sector-node differences); (6) the stale texts corrected (`LEVELS.md` status, 1.6, 3.2: `MOBJA-C` in banks 69-71, 109 of 126 used, 17 spare; `MEMORY_MAP.md` 3.5's flood stack 1,536 B) and `report.md` regenerated with `--load-timing` and `ldisk.py --check`; (7) each load's and each setup's CPU writes are now checked against its own map's places (the write log cut at each `drv_loaded`), and `--load` loads each map alone with a whole-machine diff against its own places. After them: captures 57 setups, 0 bridge problems; `--conv` 53 of 53 W dumps, `--derive` 57 R dumps, 0 failures; checkpoint B 40 loads, 0 failures, 0 bytes outside (the sequence and each map alone); **acceptance 1** 57 of 57 setups equal ref816's, 28 runs, 0 failures, stack 27-29 B, least zone margin 428, the wrap fix ok; **acceptance 2** 729 frames, 1,458 runs, all equal; **acceptance 3** worst flood depths 23-93, within 512; the disk 20 setups, every CRC as expected, boot 1,144.5 ms `f121`, 851.6 ms `fastpath`. Load and setup (model) unchanged, 191.0-654.2 ms `f121`, 116.4-398.8 `fastpath`; the load alone 101.1-275.1 ms `f121`, 57.9-153.0 `fastpath`. 30 + 22 + 39 level tests. `build/` +0.02 GB (3.5 GB in all). **Open:** (3) the renderer's `validcount` wrap call in release builds (`LEVELS.md` 3.4, listed under stage C) is deferred to milestones 10-11, for the owner (`NATIVE.md` 15.1 row 4): milestone 10 joins the renderer's frame count and the game's, milestone 11's release frame then gets the clear and its test; (5) no setup creates a zone mobj (upstream's pool has one slot a map thing, so none can), so the zone branch of `poolTake`, the `zmobj` handles and `LS_ZONE` are a named gate of milestone 10's lockstep, which spawns mobjs in play. Waits for the owner's card run at milestone 12. |
| 10 | The game logic (`docs/GAME.md`) | **Done on a2vm** 2026-10-02 (nothing committed; not yet run on the card, which waits for milestone 12): designed and reviewed; the skeleton built (`GAME.md` "Skeleton as built", checkpoint S); wave 1 (`geom`, `mobjstate`, `secfind`, `flow`, `sight`) built and integrated (`GAME.md` "Wave 1 as integrated", each part's record in `docs/game-parts/`); wave 2 (`tracel`, `damage`, `pickup`, `lines`, `spawn`) built and integrated 2026-10-02 (`GAME.md` "Wave 2 as integrated"; finished lean at the owner's request of 2026-10-02: from wave 3 on, an integration applies the requests, rebuilds with no warnings and runs the wave's tests and the suite once, without rerunning earlier parts' checkpoints; 78 modules, 1,578 tests OK); wave 3 (`tracet`, `checkpos`, `pspr`, `evworld`, `look`) built and integrated lean 2026-10-02 (`GAME.md` "Wave 3 as integrated": the requests applied but pspr R3 and R5, refused because the core is full; `aproxdist` in the tic images' core; three earlier parts' harnesses fixed for the built actions and callbacks; 103 modules, 1,905 tests, 0 failures, 7 `DOOM_GS_FULL` skips); wave 4 (`path`, `trymove`, `planes`, `evfloor`, `teleport`) integrated lean 2026-10-02 (`GAME.md` "Wave 4 as integrated"); wave 5 (`attack`, `player`, `xymove`, `missile`, `chasemove`) integrated lean 2026-10-02 (`GAME.md` "Wave 5 as integrated": every request applied but player R1 (c), the bridge's `PU_ONGROUND`; `GM_LINETARGET`, `G_ONGROUND`, `SKY_PIC` shared; the placement remade from the measured wave image with a new rule `APART` (path's walk and the traversers in different slots) and an exhaustive slot search, 1.58 ms a tic by the model; the suite once, 114 modules, 1,997 tests, 1 failure (part path's checkpoint: its captured calls now run their real traversers, which needed their callers' context from the reference; fixed, path's 40 captured calls equal)). Wave 6 (`movers`, `wfire`, `tic`, `chase`) integrated lean 2026-10-02 (`GAME.md` "Wave 6 as integrated"; every part built, `integrated.txt` 6). **Final integration and acceptance 2026-10-02** (`GAME.md` "Acceptance", `build/native/game/report.md`), **with the checks reduced at the owner's request of 2026-10-02**: each run once from one poisoned machine (`$A5`), one planted bug a run. Every compared tic equal to `ref816`'s: demo3 in lockstep-schedule mode with `FRONT` frames to the demo's end (2,134 tics); newgame (512) and the tour (427 level tics, 9 setups, cheats, the poke, intermissions) on the ring of commands; DEMO1 (5,026, 8 setups) and DEMO2 (3,836); generated streams G1, G3, G5 (2,000 each: movement, running, strafing, fire, use, weapon changes, 4 deaths and reborns, zone mobjs); demo3 with `FULL` frames, every tic and every 10th frame's records and view (54 frames, 31,439 records) equal to milestone 8's captures; `P_PathTraverse` on 203 traces of more than 64 intercepts, 1,218 runs equal; same-pair hits equal in every run; no T3, T7 or T8 case; every planted bug caught; milestone 9's gates closed (one `validcount`, zone mobjs with no slot twice, the block walk's order, bank `$21`'s tables). Found and fixed by the runs: the test driver never raised gametic and kept stale cache tags after a frame; the bridge numbered zone mobjs' sector nodes by slot; the driver gained the stream, the frames and the display's three game-visible writes (`TICLEVEL`). **Timing** (a2vm, `gprof`, a PC map of the code: `a2vm --cost-pcmap`): the game code 3-4 ms a tic, but the tic 233.8 ms at demo3's median on `f121` (176.5 `fastpath`) because the tic image's group loads take 89% (300 a tic: the placement's same-slot calls its model did not count): demo3 at 0.94 FPS median with milestone 8's render, every frame under 6 FPS; 5.2 FPS without the group loads (`RENDER-MASKED.md` 6.2 [M] rows, `NATIVE.md` 6): the performance pass before milestone 12 starts with the code placement. **Left out by the reduction**: the `$5A` fill, the tour by map, G2, G4, G6-G10, the sound events against `ref816`'s call log, more than one plant a run, 500 traces (203), the bank-2 measurement; the automatic bisection is still not built. Sizes: the parts 51,543 B of 57,300 budgeted, the core 13,295 of 13,312 B, 28 groups. The suite once (`python3 tools/testpar.py --jobs 3`, 3,288 s): 122 modules, 2,052 tests, 1 failure, 0 errors, 26 `DOOM_GS_FULL` skips; the failure was `test_testpar`'s guard (the new `test_native_game_lockstep` was not yet among the race table's writers): listed, and `test_testpar` then OK alone. `build/` +0.10 GB (the milestone 2.92 GB). |
| 11 | The 2D screens, the platform, the effects (`docs/SCREENS.md`), then the whole game | **First half built** 2026-10-02 on a2vm, verified the same day (`docs/SCREENS.md` 8.15: 5 defects, all confirmed and fixed, none rejected: `make -f m11.mk all` from an empty `build/native/m11` now builds the store first; the abandoned `tmp-*` directories of a stopped run deleted, 0.2 GB; part s2ovl's links no longer rerun on every make; `s2stbar.py`'s check modes exit 1 on a problem; the effect voices' and rings' memory map rows sent to the integrator (`design.md` R2 item 7) and SCREENS.md 10 row 3 corrected; new `tests/wip_test_m11_build.py`, 8 tests; the suite without milestone 10's `test_native_game_*`: 88 modules, 1,721 tests, 0 failures, 0 skipped), nothing committed (`docs/SCREENS.md` 8.5-8.15, each part's record in `docs/m11-parts/`, `src/native/README.md` "The 2D screens and the platform"): 20 parts in 8 waves, integrated. The status bar and face, the HUD with its cached drawer, the menus (the view saved by the memory API, //e key names), the full automap and its overlay (`OVLW`, `K_OVL` records), the intermission, the finale, pages, signs and the black-first wipe, the palettes and `PALW`; the tic-side tickers and channel logic for milestone 10's hooks; the IRQ `pl_vbl` with a 16-bit fractional clock, the //e input, `DOOM.SYSTEM` and `DOOM.hdv`. **Acceptance of the first half passes**: every 2D region equal to `ref816`'s from injected state with both fills and the poisoned marked bytes, the chained runs, the publish order on every write log, `VIEWTOP` equal at all 734 `PV` points, 0 stray writes; the clock 34.9544 (PAL) and 34.9633 (NTSC) tics a second; 55 input sequences equal to the model; `DOOM.hdv` boots on a2vm with every CRC (`f121` 5.84 s); every planted bug of the 20 parts caught; the full suite green with the 20 `tests/test_m11_*` modules (87 modules, 1,713 tests, 0 failures, 0 skipped). Sizes within every room (`P2DW` 6,093 of 7,424 B linked whole). Timing (a2vm `f121`): `P2DW` about 2.8 ms a level frame with nothing changed, a status bar refresh 44 ms, a menu open 137 ms, an intermission frame 81 ms median. **The second half keeps**: the game's frame driver (`P2DW`'s `s2_frame` glue, `VIEWTOP`, the images' loads and calls: `docs/m11-parts/design.md` R7), `G_BuildTiccmd`'s wiring, `G_Responder`, the title loop, saves and loads, the static PRIVATE tables at boot (R7 item 15), the release's 2D and tic images on `DOOM.hdv` (R7 item 14), and the whole-game acceptance of `NATIVE.md` 13 row 11 (lockstep demo3, screen compares by gametic, save and load). Milestone 10 keeps R4-R6 and R8 (the hooks into the tic-side modules). **The playable game assembled** 2026-10-02 on a2vm, not yet on the card, nothing committed (`docs/PLAY.md`): `build/native/DOOM.hdv` (4,027,392 B) links all 29 parts of milestone 10 with milestones 7-9 and 11, no stub left; played with scripted input from the title loop through E1M1's exit, the intermission and E1M2, and a 2,750 s run over both maps; a renderer table bug found in play and fixed (`xtoviewangle` missing from the boot's copies); milestone 11's R4 and R5 applied in part flow. Frame rate (f121, not optimised): 5.3 FPS standing on E1M1, 2.7 in a fight, the tics' code paging measured as the cause (`docs/PLAY.md` 8). |
| S4 | Sound: the effects (`tools/sound/README.md` "Effects (S4)") | **Built on a2vm** 2026-10-02 with milestone 11's first half, not yet heard: our own converter from `DS*`/`DP*` (52 scripts, `SFX.1` 11,385 B) checked against a second independent model, the ten most frequent effects hand-tuned (first versions), the 65C02 effect player on chip 3 in the music's interrupt (stereo by a left or right voice), upstream's channel logic with 3 channels; with no effect playing the AY writes stay S2's byte for byte (13 songs). Cost on D_E1M1 in the Doom profile: 5.99 ms a second with the music alone, 16.24 with effects at demo3's start rate; worst interrupt 2,048 µs. The test disk `build/sound/SOUNDS.hdv` waits for the owner's ear and the tuning (milestone 12). Verified with milestone 11's first half 2026-10-02 (`docs/SCREENS.md` 8.15): the effect voices `$E413-$E442` and rings `$E740-$E8BF` are built, their `MEMORY_MAP.md` rows wait for the integrator (`docs/m11-parts/design.md` R2 item 7); nothing in the player changed, `tests/test_sound_*` and the `test_m11_fx*` modules green. |
| SP1 | Speed wave 1 (`docs/SPEED.md`; parts in `docs/speed-parts/`): the menu's BENCHMARK, the exact a2vm idle and `playtime.py`, the one-window group copy and the lazy restore, the placement by the machine's cost, the faster bucket pass | **Integrated on a2vm** 2026-10-02 (not committed; not yet run on the card): lockstep demo3 2,134 tics 0 failures; frame8 23 of 23 frames equal; 127 modules, 2,088 tests, 3 failures on the first run (each a check that assumed the old speed or layout; fixed, and the three modules then passed alone: `SPEED.md` 5, "Integration"). a2vm f121, card-equivalent: standing still 5.53 → **11.37 FPS**, demo3 1.15 → **3.68 FPS**, the menu's BENCHMARK 0.912 → **3.318** (`SPEED.md` 5, `PLAY.md` 8 and 14) |
| 12, 13 | The whole game on the card; the pair back end, view sizes, release | Defined in `NATIVE.md` section 13. Not started. |

## Milestone 1: done

Our own tools assemble and link upstream's sources and rebuild the v1.0
release with **0 differing bytes of 221,696**: the game (218,112 bytes), the
boot block (512) and the loader (3,072).

| Part | Files |
| --- | --- |
| Fetch and release reader | `tools/fetch_upstream.py`, `tools/v816/prodos.py`, `hdv.py`, `b1.py`, `memimage.py`, `tools/list_segments.py` |
| Front end | `tools/v816/cpp.py`, `lexer.py`, `expr.py`, `macro.py`, `parse.py`, `ir.py`, `frontend.py` |
| Back end | `tools/v816/opcodes.py`, `asm816.py`, `linear.py`, `objfile.py`, `scm.py`, `link.py`, `sections.py` |
| Layout recovery and report | `tools/v816/place.py`, `release.py`, `imgmatch.py`, `linkmap.py`, `report.py`, `stats.py` |
| Statistics | [`FRONTEND_STATS.md`](FRONTEND_STATS.md), regenerated by `frontend.py --stats` |

Outputs in `build/`: `linkmap.json` (address of every section fragment and
value of every symbol) and `match-report.json`.

The Calypsi linker may place section fragments in any order, so the layout
is **recovered** from the release image, not predicted. A build of modified
sources will need its own placement.

An independent review found no cheating and two medium weaknesses; they are
step 2.0 below.

## Milestone 2: reference machine and measured profiles

### Results

Done on 2026-09-29, independently reviewed, with the review's findings fixed
and verified.

| Check | Result |
| --- | --- |
| 65816 core against SingleStepTests (commit `db6b104`) | 5,120,000 cases: 0 register, memory, cycle-count or bus failures; 44 known issues in two narrow rules, each citing the published errata of the vector set |
| Title screen | Reached from the release image; the colour DOOM title picture |
| Game clock | 34.955 tics per emulated second, as the DOC settings predict |
| Scripts | `title`, `newgame`, `viewsize` and `tour` run to their end at 2.86 MHz and 12 MHz, twice each with identical RAM hashes; all nine maps visited |
| Unit tests | 735, none skipped |

Frame cost on an ideal 65816 with no wait states, 4 tics per frame:

| Scene | Instructions a frame | Cycles a frame | Frames a second at 2.86 MHz | at 12 MHz |
| --- | ---: | ---: | ---: | ---: |
| Standing still in E1M1 | 331,325 | 1,123,634 | 2.50 | 10.79 |
| Title demo, E1M7 | 461,187 | 1,604,459 | 1.64 | 6.19 |

The full measurements are in [`PROFILE.md`](PROFILE.md). What they change:

- **Register widths.** Only 70 of 38,793 executed addresses run with more
  than one accumulator and index width, so static width inference works
  almost everywhere. `build/ref816/widths.json` lists every exception.
- **Stack.** At most 86 bytes on the frame stack and 228 on the tic stack,
  far below the 4 KB the architecture reserved.
- **Where the time goes.** The record replay is 34% of the cycles standing
  still and 42% in the demo; the seg loops are 32% standing still. Both are
  planned as hand-written code.
- **Screen.** Standing still, only 152 of the 8,519 screen bytes written a
  frame change the stored value; in the demo 15,262 of 21,881.
- **The assumptions of ARCHITECTURE.md section 6.** Instructions outside the
  replay are about half the assumed 450,000; far accesses outside the replay
  are 30,000 to 47,000, fewer than assumed but a larger share of the
  instructions. Section 8 of `PROFILE.md` gives each.

Known limits: the machine has no wait states, so its times are those of an
ideal CPU; counts per frame do not depend on that. It has not been compared
with GSSquared or a real IIgs. `$C039` (serial) is the only register the game
touches that it does not model.

### Specification


A 65816 machine on the host that runs upstream's release, plays it under
script, and measures what the port needs to know. It replaces the assumed
figures in ARCHITECTURE.md section 6 with measured ones and produces the
register-width map the translator needs.

Everything new goes in `tools/ref816/`, `coverage/` and `docs/PROFILE.md`.

### 2.0 Fix the milestone 1 review findings

Each fix gets a unit test. The image match must stay at 0 differing bytes.

| # | Where | Fix |
| --- | --- | --- |
| 1 | `place.py`, `sections.py` | An address resting on one reference has no independent check. List such atoms as `single_evidence` in `match-report.json`, and add a `support` count per fragment to `linkmap.json`. |
| 2 | `place.py`, `imgmatch.py` | A reachable fragment without bytes that nothing refers to is silently dropped. Report every reachable unplaced fragment of size above 0 as unplaced, and require placed == part of the program in `clean()`. |
| 3 | `sections.py` | `data_init_table` is reconstructed from one image. Say so in the report, and add a test that fails on a copy entry or a different order. |
| 4 | `hdv.py`, `release.py` | Linked segments are chosen by hard-coded bank numbers. Derive them from the rules file's memories that accept initialised sections. |
| 5 | `place.py` | The docstring of `solve()` is wrong about the minimum hole width. |
| 6 | `objfile.py` | A `.section NAME` without a kind is taken as text. Document it, and report an error when fragments of one section differ in kind. |
| 7 | `sections.py` | Report a problem when a fixed-address section does not start at its fixed address. |
| 8 | `memimage.py` | Region owners are signed 16-bit. Widen, or fail clearly at the limit. |

### 2.1 The 65816 core

`tools/ref816/cpu816.c`, `cpu816.h`. Exact registers, flags and memory
effects for every opcode in native and emulation modes, including:

- decimal mode, 8- and 16-bit accumulator and index, and truncation of X and
  Y when the index flag is set;
- direct-page relocation with the emulation-mode page-wrap rules;
- stack-relative modes;
- MVN and MVP one byte per step, so an interrupt can fall between steps;
- BRK, COP, RTI, WAI, STP, and IRQ and NMI entry in both modes;
- cycle counts from the manufacturer's table, including 16-bit modes, a
  nonzero direct-page low byte, page crossings and taken branches.

The bus is two callbacks, `read(addr24)` and `write(addr24, value)`, plus IRQ
set and clear.

Check it against the public
[SingleStepTests](https://github.com/SingleStepTests) 65816 vectors, fetched
into `build/vectors/` by `tools/ref816/fetch_vectors.py`, which pins the
commit. Compare registers and memory for every case; report cycle mismatches
separately. Known-unreliable cases are listed by opcode with the reason, never
silently skipped.

**Acceptance:** builds with no warnings; every opcode passes in both modes, or
each exception is listed with evidence; a unit test runs a sample of the
vectors, and a `make` target runs all of them.

### 2.2 The machine around the core

`tools/ref816/iigs.c`, `iigs.h`, `main.c`. Only as much IIgs as the game needs.
The register list is in `research/iigs-platform.md` section 2.7.

| Area | What to model |
| --- | --- |
| Memory | 8 MB in banks `$00-$7F`, plus `$E0` and `$E1`. Shadow register `$C035`: bit 3 gates SHR shadowing of bank `$01` `$2000-$9FFF` into `$E1`; bit 6 turns banks `$00/$01` I/O and language card into RAM, where the game puts its vectors at `$00:FFE0`. Speed `$C036`, new-video `$C029`, border `$C034`, VBL flag `$C019` from emulated time. Interrupt registers `$C023`, `$C032`, `$C041`, `$C047`, `$C027`. |
| Accelerators | ZipGS `$C059-$C05F` and the TransWarp GS signature in bank `$BC` read as absent, unless the game will not start without one. If so, model the minimum and say so. |
| Clock and sound | The game's only clock is the Ensoniq DOC through the sound GLU at `$C03C-$C03F`: oscillator 31 free-running as the tic clock, oscillator 30 as a one-shot alarm raising IRQ. Model enough that `I_GetTime` runs at the right rate against emulated cycles and the music interrupt fires. No audio output. |
| Input | ADB microcontroller at `$C026/$C027` (the game polls it directly), mouse at `$C024`. Scripted key presses, releases and mouse motion must reach the game. |
| Start-up | `tools/ref816/make_image.py` writes `build/ref816/memory.img` from the release (segments at their addresses, level store at `$40:0000` as in 8 MB mode) and the BOOTINFO block the loader leaves (layout in `loader.s` and `m_config65.s`). Start at the entry point in native mode with the state `crt0.s` expects. |
| Disk | Trap the slot-firmware calls the game makes to save settings and, in 4 MB mode, load levels. Serve them from a copy of the disk in `build/`, never from `build/release`. |
| Screenshots | `tools/ref816/shot.py` turns a dump of `$E1:2000-$9FFF` into a PNG using only `zlib`: 320 mode, per-line palettes, border. |
| Command line | Run N cycles or N video frames, with optional screen dumps and a final state dump: registers and a hash of all RAM. |

**Acceptance:**

1. `make` builds with no warnings; all tests pass.
2. The game reaches its title screen, and a PNG of it is written to
   `build/ref816/shots/`. The image is 320x200 or 640x400, has more than 8
   colours, and shows the DOOM title picture.
3. Two runs with the same arguments give the same final RAM hash.
4. The game clock runs at about 35 tics per emulated second.

List every approximated or stubbed hardware behaviour, with its address.

### 2.3 Playing under script

- An input script format documented in `tools/ref816/README.md`, with lines
  such as `at <tic> key down <name>`, `key up <name>`, `mouse <dx> <dy>`,
  `button down|up`, `shot <name>`, `stop`. Default bindings are in
  `i_iigs65.s` (`keyTable`) and `m_config65.s`.
- `tools/ref816/run_script.py` runs a script and writes its shots to
  `build/ref816/shots/<script>/`.
- Four scripts in `coverage/`:

| Script | Content |
| --- | --- |
| `title.script` | The title loop until demo3 has played at least 20 emulated seconds, a shot every 5 s |
| `newgame.script` | New game on the default skill through the menus; stand still in E1M1 for 10 s; walk, turn, fire, open the first door |
| `viewsize.script` | Every view size through the options menu, a shot at each |
| `tour.script` | Each of the nine maps through the `idclev` cheat (`m_cheat65.s`), 5 s and a shot each |

**Acceptance:**

1. All four scripts run to the end without an unimplemented register, an
   illegal opcode, the game's error screen (`I_Error`) or a stuck loop.
2. E1M1 shots show a 3D view.
3. Each script is deterministic.
4. Report rendered frames per emulated second, and 65816 instructions and
   cycles per rendered frame (median over at least 20 frames), for the title
   demo and for standing still in E1M1, on an ideal 65816 with uniform
   memory. Report cycles, not wall time.

### 2.4 Measured profiles

Tracing in `tools/ref816/trace.c`, enabled by options so an untraced run
stays fast, and a report tool `tools/ref816/profile816.py` that maps
addresses to symbols through `build/linkmap.json`. `docs/PROFILE.md` folds the
code of `cal_integer.s` into its "others" rows and never shows it on its own;
its separate figures go to `build/ref816/profile-withheld.json`.

Measure per rendered frame, median and range over at least 20 frames, for
standing still in E1M1 and for the title demo:

1. Instructions and cycles by phase: game tics (`P_Ticker` and callees), frame
   setup, BSP walk, wall setup (`R_StoreWallRange`), seg loops
   (`R_RenderSegLoop`), sprite projection, masked drawing, record replay
   (`R_DrawLists`), status bar and HUD, menu, finish (`I_FinishUpdate`),
   interrupts, other. Say how each boundary was detected; upstream marks
   phases only in a `PHASES` build.
2. Memory accesses by kind: direct page, stack, bank `$02` near data, and far
   data by bank, reads and writes apart. For far data also the distinct
   8-byte lines, 64-byte lines and 256-byte pages touched per bank per frame,
   and the number of bank changes between consecutive far accesses.
3. Code heat: bytes executed at least once per frame, and the bytes covering
   90%, 99% and 99.9% of executed instructions, by section and source file.
4. Register-width map: for each executed address, the values of the M and X
   flags, the direct-page register and the data-bank register it ran with.
   Write `build/ref816/widths.json` and count the addresses seen with more
   than one value of each.
5. Self-modification: every write to a byte later executed, grouped by the
   writing instruction and the target symbol, with counts per frame.
6. Stack: the lowest stack pointer per frame, for the main and tic stacks.
7. Screen: bytes written to `$E1:2000-$9CFF` per frame, and how many changed
   the stored value.

Write the results to `docs/PROFILE.md` as tables, each with a short paragraph
on what it implies for the target. The target has about 90 KB of fast memory,
slow extended memory behind a small cache, bus cycles of about 1 µs for bank
switches, and about 1 µs per screen byte written. Replace assumptions P2, P4,
P6 and P8 of ARCHITECTURE.md section 6 with measured values in a section of
`PROFILE.md`; do not edit ARCHITECTURE.md.

**Acceptance:** `profile816.py` regenerates `PROFILE.md` deterministically
from trace files; a unit test checks it on a small synthetic trace; the
numbers in `PROFILE.md` are the ones the tool printed.

### 2.5 Independent review

Someone who did not write the code checks it. Review; do not rewrite.

1. Build from clean, run all tests, the full vector run, and at least the
   title and newgame scripts. Report the real numbers.
2. Check determinism.
3. Look for anything that makes the measurements untrustworthy. Examples: a
   game address special-cased to get past a problem; a stub that changes game
   behaviour, such as a clock at the wrong rate, which would change tics per
   frame and every per-frame count; wrongly attributed phases; counts that
   include the emulator's own traps.
4. Check the ground rules: nothing from upstream, the release, ROMs or the
   vectors outside `build/`.
5. Look at three screenshots and say what they show.
6. List real defects with file and line, most serious first. Fix only trivial
   ones.

Commit milestone 2 only after the review passes.

## Milestone 3: target machine model and 65816 interpreter

### Results

Done on 2026-09-30, independently reviewed, with the review's findings fixed
and verified.

| Check | Result |
| --- | --- |
| a2vm's 65C02 core against SingleStepTests (WDC 65C02, commit `2f6980a`) | 2,540,000 cases: 0 register, memory, cycle or bus failures. 10,029 known issues, all `STA a,X` and `STA a,Y` within a page, where the dummy read follows the Appletini RTL (`ST_INDEX_DUMMY` in `w65c02_core.sv`), as the firmware's own harness does. About 215 million instructions a second. |
| a2vm against `demos/doom/tools/a2sim.py` | Exact match over 20 frames of the existing Doom port and a full ProDOS loader boot: every byte of main memory, the language cards and all 128 RamWorks banks, every soft switch, the registers, the cycle count and the final screen. 57 to 78 times faster. |
| Cost model against the hardware (E1M1 standing still, existing port) | 248.6 ms a frame against 248 ms measured, **with one parameter fitted**: the ARM's AXI register latency (`axi_us`), 0.135 µs. At the firmware documents' estimate of 0.305 µs the copy phases were 2.0 to 2.3 times too slow; the frame total and the copy phases alone give the same fit (0.133 and 0.137 µs). The independent checks: walls, planes, tics, masked drawing and the blit within 11% phase by phase, and the card's own counters within 3%. Milestone 0 measures `axi_us`. |
| Firmware design, same frames | 188.6 ms, 32% more frames a second. One lazy SHR flush a frame, caused by the port's `$C073` write before a memory API call, costs 27 ms of it. |
| Interpreter on the 65816 vectors | 5,120,000 cases: 0 register or memory failures; the same 44 known issues as milestone 2 |
| Interpreter size | Core 1,782 of 4,096 bytes, far layer 227 of 1,228, handlers 3,604 of 4,096 |
| First contact with the game | 322,215 instructions identical to `ref816`, registers and every write, up to the game's first I/O access |

**The interpreter is slower than the architecture assumed.** An interpreted
game instruction costs 299 to 319 65C02 cycles: 5.3 to 5.7 µs on today's
firmware and 4.4 to 4.6 µs with the firmware design, against 3.2 µs assumed
(P5). An all-interpreted frame would take 1.5 to 2.7 s. Details are in
[`INTERPRETER.md`](INTERPRETER.md).

- 54% of those cycles are in the far layer: every direct-page and stack byte
  goes through it.
- On today's firmware, 24% of the time is bus cycles for RAMRD, RAMWRT and
  `$C073` around far accesses. The zero-page bank pair proposed for the
  firmware would remove most of them.
- So the translator must cover more of the frame than planned, and the far
  layer is the first thing to optimise.

Known limits: the game's memory map exists only in the host harness. The
first contact stops at the first I/O access, because the platform layer does
not exist yet.

**After the native direction.** These measurements are why the owner chose a
native rewrite. `a2vm` and its cost model stay central: every native routine
runs and is timed on it. The interpreter is kept as a tool, at most a
bring-up aid; it is not in the shipped game.

### Specification


Two pieces every later milestone needs, whatever the firmware decisions:

- `a2vm`, a fast model of the Appletini target, to run port code on the host.
- A 65816 interpreter written in 65C02 assembly. It is tier 0 of the
  architecture: it runs cold code, code with unclassified self-modification,
  and anything the translator refuses.

New code goes in `tools/a2vm/` (host tool) and `src/vm/` (port code that runs
on the Apple, assembled with ca65 from cc65 2.18).

### 3.1 `a2vm`, the target model

A C11 program with the same build rules as `tools/ref816`.

| Part | What to model |
| --- | --- |
| CPU | W65C02S, including RMB, SMB, BBR, BBS, WAI and STP, exact in registers, flags and memory effects, with the datasheet's cycle counts. Check it against a public per-opcode vector set for the WDC 65C02 fetched into `build/vectors/` (the SingleStepTests organisation has one); list any unreliable cases by opcode with the reason. |
| Memory | Enhanced //e main 64 KB and 128 RamWorks banks selected by `$C071/$C073`, with RAMRD, RAMWRT, ALTZP, 80STORE, PAGE2, HIRES and both language cards per bank, exactly as [`demos/doom/tools/a2sim.py`](../../doom/tools/a2sim.py) models them. |
| Devices | `$C019`, keyboard `$C000/$C010`, Open and Solid Apple, the mouse card in slot 2 with its VBL interrupt, the memory API FIFO at `$CFF0-$CFF2` in slot 7 with the version 1 rules of `README_MEMORY_API.md` in appletini-one (COPY, FILL, PRIVATE, every validation error), and screen dumps of standard SHR and the PAL256 extension from aux bank 0 `$2000-$9FFF`. |
| Start-up | Load ca65 binaries at given addresses and banks, or run a ProDOS system file through a trap of the MLI entry, as `a2sim.py`'s `FakeProDOS` does. |
| Cost model | Every access classed as fast memory (main or base aux), extended memory through the one-line cache (hit, clean miss, dirty miss), a `$Cxxx` bus cycle, an SHR write that leaves bytes pending in the mirror, a mapping change that clears the TURBO caches, or a memory API request. Costs come from a parameter file with two profiles: F1.2.1 today, and F1.2.1 with the changes of the firmware design doc. Report time per frame and per phase in both. |

The parameters are derived from the RTL, as `docs/firmware/` explains, until
milestone 0 measures them. Say so in the output.

**Validation against `a2sim.py`.** `a2vm` has a compatibility mode that
counts cycles the way `a2sim.py` does. In that mode it runs the existing
Doom port's banked build for 20 rendered frames and must match `a2sim.py`
at every frame boundary: RAM of every bank, the screen, registers and cycle
count. The existing port and its tools are in [`demos/doom`](../../doom/README.md);
its README explains how to build it and run it with `tools/run_doom.py`.

**Acceptance for 3.1:**

1. Builds with no warnings; the 65C02 vectors pass, or each exception is
   listed with evidence.
2. The 20-frame comparison with `a2sim.py` matches exactly.
3. `a2vm` runs those frames at least 20 times faster than `a2sim.py`.
4. For the same 20 frames it reports frame time under both cost profiles.
   Today's profile must come within 25% of the 248 ms per frame measured on
   hardware, or the report must say which parameter is suspected.

### 3.2 The interpreter

`src/vm/`: a 65816 interpreter in 65C02 assembly that runs on `a2vm`.

- The virtual 65816 state lives in main zero page: A, B, X, Y, S, D, DBR,
  PBR, P, and the M, X and E flags.
- The virtual 24-bit address space maps onto the Appletini as
  ARCHITECTURE.md section 3.3 describes: a table from each virtual 32 KB
  half-bank to `$4000-$BFFF` of one RamWorks bank, with the special cases for
  virtual banks `$00`, `$01`, `$02` and `$E1`. For this milestone the table
  may be simpler, but it must keep far reads and writes behind one interface
  so the planner of milestone 7 can change it.
- Code is fetched through a cache of 256-byte pages in fast memory. A write
  to a cached page invalidates it, so self-modifying code stays correct.
- Every 65816 opcode in native and emulation mode, including decimal mode,
  MVN and MVP a byte at a time, WAI, STP, BRK, COP, RTI and interrupt entry.
- The interpreter's own code fits the budget of ARCHITECTURE.md section 3.2:
  4 KB of core in main language card `$E000-$FFFF` plus 4 KB of handlers in
  language card bank 1. If it cannot fit, say what it needs.

**Acceptance for 3.2:**

1. Correctness: the SingleStepTests 65816 vectors of milestone 2, run through
   the interpreter on `a2vm`, pass in registers and memory for every opcode
   in both modes. Cycle and bus records are not compared. Exceptions are
   listed with evidence, and the 44 known issues of milestone 2 are handled
   the same way.
2. Cost: the median and the range of 65C02 cycles per interpreted 65816
   instruction, by opcode and weighted by the instruction mix of
   `docs/PROFILE.md`, under both cost profiles. This replaces assumption P5
   of ARCHITECTURE.md section 6.
3. First contact with the game: the interpreter runs upstream's image, from
   the entry point, in lockstep with `ref816`. The comparison is of the
   virtual registers after every instruction and of every memory write, up
   to the first access to the IIgs I/O space. Report how far it got.
4. A unit test in `tests/` runs a sample of the vectors through the
   interpreter, and a `make` target runs all of them.

### 3.3 Independent review

As in 2.5: build from clean, rerun every acceptance test, look for shortcuts
that make a result untrustworthy, check the ground rules, and list real
defects most serious first.

## Milestone 0: hardware costs

This needs the physical Appletini and the owner, so it can run in parallel
with milestones 2 and 3. ARCHITECTURE.md section 12 has the file list.

- Timed loops: straight-line code in fast memory; a far read in the same bank
  and after a bank change; sequential and random extended-memory reads and
  writes; an SHR store burst followed by one `$Cxxx` access; memory API
  copies of 1 KB, 16 KB and 48 KB; code run from an extended bank.
- Each loop reports microseconds from the memory API's STATUS counter, and
  repeats within 5%.
- A standard 320-mode SHR picture with per-row palettes. Upstream uses
  standard SHR; the existing Doom port uses only the PAL256 extension.

## Owner's plan for testing (2026-09-30)

"Make S3. Then keep going with the milestones as planned. I'll test at
milestone 12." Build S3 (the music disk), then milestones 7 to 12 in order;
each is verified on a2vm and against `ref816` and committed without waiting
for a card run. The owner's next card test is milestone 12, the whole game.

## Direction since 2026-09-30: a native rewrite

The owner's words: "To go faster we'll probably have to fully rewrite and
optimize the 65816 code into 65c02 code. The music I think is originally
midi, and we should translate it directly to the phasor. Don't use the
ensonic as a base."

What this means for the plan:

- **Native code.** Every routine becomes 65C02 code, with data layouts chosen
  for the 65C02. The translator and the virtual 65816 machine of
  ARCHITECTURE.md are no longer the end state.
- **Kept from upstream.** The game's behaviour, and its SHR techniques:
  per-column records, record replay, dithered colormaps, fill spans and
  covered ranges.
- **Verification.** A native routine is checked against `ref816` through a
  state bridge that reads upstream's structures by symbol and converts them
  to the port's layout: routine by routine, tic by tic (demo sync), and
  frame by frame (the SHR bytes).
- **Music.** The WAD's MUS lumps (`D_E1M1` and the rest) are converted on the
  host to event streams for the Phasor's four AY-3-8913 chips. Upstream
  renders the same songs through a SoundFont into Ensoniq DOC sample units
  (`tools/music` in the clone); that is not used.
- **Firmware.** The port must run on F1.2.1 as it is and use the proposed
  zero-page bank pair when present. `a2vm` must model the pair.
- **Licence.** Code translated from upstream is a derivative of GPL-2 code.
  On 2026-09-30 the owner licensed this directory GPL-2, so it is committed
  like the rest.

**Expected speed.** `NATIVE.md` section 1 estimates 13 to 29 frames a
second standing still in E1M1 on F1.2.1, and 24 to 35 with the firmware
design and the zero-page pair (35 is the game's cap). In the title demo:
7.9 to 19, and 18 to 35. These rest on measurements plus assumptions: the
native cycle count (about 1.37 times upstream's, from an opcode-by-opcode
count; three routines written natively measured 0.95, 1.2 to 1.3 and 2.1
to 2.5 times), and a2vm's cost model. They assume the fast-memory plan
fits, which is `NATIVE.md`'s top risk.

### Milestone 4: native architecture

Done on 2026-09-30 by a design run, which changed no tool, test or source:

| Output | Content |
| --- | --- |
| `research/native-modules.md` | Every upstream module: size, heat, 16-bit share, self-modification, data; subsystems and rewrite order |
| `research/native-verification.md` | The state bridge and the routine, tic and frame tests, checked on a real dump |
| `research/native-memory.md` | Code and data map, per-phase windows through the memory API, far access on F1.2.1 and with the pair, what `a2vm` must add |
| `research/native-experiment.md` | Three hot routines written natively, checked on captured inputs, bytes and cycles against upstream. The code stays in `build/native-experiment/`. |
| `research/native-sound.md` | MUS to Phasor converter and player, sound effects, tests |
| `NATIVE.md` | The architecture: frame-rate estimates on both firmware variants, the milestones from 5 with acceptance tests, risks, questions for the owner |

Two reviews (correctness, hardware) checked `NATIVE.md`, and a last step
applied their findings: 28 applied, one in part. Its prototypes and the
natively written routines are in `build/native-design/` and
`build/native-experiment/`, which git ignores; they are rebuilt as tools
once the licence is decided.

**Owner's answers (2026-09-30), `NATIVE.md` 15.1.** The decisions that
bind later work: renderer arithmetic stays exact; the release is gated on
lockstep-schedule mode and the port fixes upstream's `validcount` wrap (a
build option keeps upstream's behaviour for the lockstep tests); our own
divides, with our own result for division by zero; 6 FPS minimum on
F1.2.1; 8 MB of RamWorks and the mouse card are required; PAL and NTSC;
any load time; view sizes only if simple; music every VBL, no 6-voice
fallback, effects generated with the 10 most frequent hand-tuned, stereo by
voice choice; main zero page only for the pair (D4); a Doom configuration
profile with `vtw.slowdown.cycles=32` now, and FW-S1 later with the
firmware design.

## Related work outside this directory

| Item | Where | State |
| --- | --- | --- |
| Firmware design for faster extended memory and SHR (zero-page bank pair enabled at `$C069`, lazy SHR mirror, relaxed PSRAM admission, and four more) | A Claude Doc in the owner's account, "vTW Memory Fast Path: Design". Its source material is [`firmware/`](firmware/); the zero-page pair is in `firmware/zpbank-spec.md` and `zpbank-review.md`. | Awaiting the owner's review, 35 open questions. Nothing implemented. Change 8, FW-S1 (Phasor port writes skip the slot-4 slowdown), added 2026-09-30 from `firmware/fws1-spec.md` and `fws1-review.md`; the review's simulation narrowed it to ORB and ORA without handshake. |
| Effect of those changes on the existing port | `a2vm`'s cost model (milestone 3) | +32% frames a second from firmware alone; about +54% if the port also stops writing `$C073` before its memory API call |
| Firmware source | [hasseily/appletini-one](https://github.com/hasseily/appletini-one), `origin/main` at F1.2.1 | 21 of its 30 testbenches run under Verilator without Vivado, with a behavioural `LUT6` model |
| Existing Doom port | [`demos/doom`](../../doom/README.md), branch `claude/iigs-doom-port` | 4.03 FPS measured on hardware, E1M1 idle, TURBO |

## If a run was interrupted

Each milestone is built by a sequence of agents that do not commit. If the
work stopped partway:

1. `git status` in the repository. Uncommitted files belong to the milestone
   marked "Next" in the status table; its specification says which step
   writes which directory.
2. Run the unit tests and `tools/v816/imgmatch.py`. Earlier milestones must
   still pass: 0 differing bytes, and all tests green.
3. Treat every uncommitted file as unreviewed. Rebuild it and check it
   against the acceptance tests of its step before building on it.
4. `build/` can always be recreated with `tools/fetch_upstream.py` and
   `tools/ref816/fetch_vectors.py`.
