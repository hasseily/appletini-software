# DOOM GS speed plan

Written 2026-10-02 from three profilers' measurements and a planner's prototypes (workflow `doom-gs-speed-profile`); the owner's rule of the same day applies to every part: test only what a change touches (`MILESTONES.md`, ground rules).

Status: **wave 1 built and integrated (2026-10-02; section 5, `PLAY.md` 14); waves 2 and 3 planned.** The owner played `build/native/DOOM.hdv` on the card on 2026-10-02 and reported: "Everything seems to work except for the benchmark. It's indeed too slow and needs a speed optimization." This document holds the measurements behind that, three prototypes measured on a2vm, and the parts that make the game faster. Nothing in the game's output may change. The renderer's frames and the game's demo sync stay bit-exact against ref816 (NATIVE.md 15.1). Every item below changes only time: where code lives, how bytes are copied, and which pages are reloaded.

## 0. The owner's two findings

1. **The BENCHMARK menu item does nothing.** *Done in wave 1 (part bench, `docs/speed-parts/bench.md`): the menu's BENCHMARK plays demo3 timed and shows its FPS; each wave's on-card figure is that page's FPS.* OPTIONS, BENCHMARK sends `REQ_BENCH`. The brain drops it (`src/native/dl_brain.s:232`: "REQ_LOAD, REQ_BENCH, REQ_SAVESET: none in this version"). Upstream's benchmark plays demo3 at the normal tic rate and counts drawn frames. It then shows "BENCHMARK: DEMO3" with VIEW and FPS = 35000 × frames / realtics (`m_menu65.s` bmStart/bmTick/bmDone, about lines 2178-2530). The menu half is already built: `m2_bench` draws `M_BFPS` (SCREENS.md S2MENU2-1). The play half is not. Part `bench` builds it, which also gives the owner an FPS figure on the card after each wave.
2. **It is slow.** On a2vm f121 the game runs at 5.5 FPS standing still and 1.15 FPS in demo3, which is the benchmark's demo. Four fifths of the time goes to the tic phase's code paging, not to game logic and not to the renderer (section 2).

## 1. How it was measured

All runs used a2vm on the `f121` profile (`fastpath` for reference), with the play build booted as `playdisk.run` boots it. Each run was a scratch APFS clone of the tree (`cp -c -R`). The clone rebuilt `DOOM.hdv` byte-identical to the owner's (`cmp`). Frames were cut at the kernel's `K_END` dispatch, steps at each `run` dispatch and loads at `gr_load` entries, counted only in the tic image's context. The demo3 figures cover the **same gametics** in every build (1052-1796 and 1052-3004), so the same game frames are compared. Every frame there runs 4 tics (`MAXTICS`).

**The measurement artifact (fix first).** `playdisk.run` passed `--idle dl_bwait:vbl` with no condition (fixed by part measure: the skips are now conditioned on no tic due and, for `dl_bwait`, the brain's group in slot 2; `playtime.py --idle old` measures the old skip, which cost 9.9 ms a frame standing still; the 9.7 below was the profile of the one PC). a2vm then jumps to the next VBL the first time each frame reaches `$A66C`, even when a tic is already due. It also jumps whenever *any* slot-2 group's code sits at `$A66C`. Standing still this costs 9.7 ms a frame. After a re-placement it cost **49.5 ms a frame**, because P_Ticker's new group had an instruction there, run 244 times in 10 s. The card never waits there. Every figure below marked "card-equivalent" was measured with that `--idle` removed (`NOIDLE=1`, scratch patch). PLAY.md 8's 5.3 FPS reads about 5% low for the same reason.

**Commands** (part measure's `tools/native/playtime.py`, on `build/native/DOOM.hdv`, every PC from the play link's labels; it refuses a disk that `build/native/play` does not build):

- `python3 tools/native/playtime.py --scene still --profile f121`
- the same with `--scene walk`, with `--scene demo3` (gametics 1052-1796 by default), and with `--profile fastpath`.

The figures of sections 2 and 3 were first measured with scratch tools (a profiling a2vm, `prun2.py`, `kern.py`, `gtic.py`; the run dispatch then at `FF3B`, `gr_load` at `823A`); `playtime.py` reproduces every one of section 2's (`docs/speed-parts/measure.md`).

## 2. Baseline (the owner's build), ms a frame

| Scene (a2vm) | Frame, f121 | FPS f121 (card-eq.) | FPS fastpath | K_TIC | of which group paging | WCODE + MCODE + P2DW loads | nr_frame | nm_masked + bkload | nb_frame (bucket + replay) | s2_frame |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| E1M1 start, standing still (15-25 s) | 180.7 (190.6 with the artifact) | **5.53** | 6.48 (154.3 ms) | 112.3 (4 tics) | 99.1 (38.9 loads a tic, 100 µs a page) | 9.5 | 26.5 | 4.05 | 26.6 (9.1 + 17.2) | 1.97 |
| E1M1 walking and turning (14-32 s) | 465.9 with the artifact (about 454 card-eq.) | **2.2** | 2.7 (365.7 ms, frame profiler) | 369.5 | 331.5 (112.7 loads a tic) | 9.5 | 30.2 | 3.8 | 51.4 (replay draw 22.2) | 1.6 |
| demo3 on E1M7, the fight and benchmark scene, gametics 1052-1796 | 873.3 mean, 877 median, 1,656 max | **1.15** | about 1.4 (693 ms, tic profiler, 40-100 s) | 785.3 (196 a tic) | about 640 (241 loads a tic) | 9.5 | 22.3 | 7.8 | 44.8 | 3.54 |
| Lockstep demo3, gametics 2440-2640 and 2900-2990 (tic profiler, gprof build) | | | | 336-339 a tic | 302-306 a tic (409-417 loads) | | | | | |
| Lockstep demo3, worst tic and heaviest render | tic 2945: 1,089 ms (1,332 loads); render demo3-036: 164 | | | | | | 39.5 | 23.9 | 30.1 + 70.9 | |

- **Inside the still K_TIC:** the tic image load is 4.33, paging 99.1, far_put write-backs 3.43, the tic work itself about 6 ms, and IRQs 1.15.
- **Copy speeds (f121):**
  - far_pload: 63.8 µs a page.
  - gr_load, which makes one far_get call and one RAMRD window per page: 100.3 µs a page.
  - far_put: 131.8 µs a page.
- **The fight scene is demo3.** E1M1's skill-2 monsters near the start are ambush and none wakes, and PLAY.md 8's route script is not in the tree. In demo3 A_Chase runs 3.6 times a tic, A_Look 7.5 and P_CheckSight 373.
- **The causes, measured.** Groups 21 (P_RunThinkers) and 19 (P_SetMobjState) share slot 1 and swap 16 times a tic standing still. Only 3,351 B of the 13,312 B core hold game routines. `gplace.py`'s cost model charges 0.246 µs a byte (63 µs a page), but gr_load costs 100 µs a page and copies whole pages.

## 3. Three prototypes, measured (scratch only, not in the tree)

Each was built in the clone (`playdisk.py`) and run on a2vm. They are measurements of timing only. Lockstep exactness was **not** run on them: that is the parts' job.

| Build | Change | Still, card-eq. f121 | demo3, gametics 1052-1796 | demo3, 1052-3004 | Heaviest demo3 frame | Loads a tic |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| base | as played | 180.7 ms, 5.53 FPS | 873 ms, 1.15 FPS | (not reached in 200 s) | 1,656 ms | still 38.9; demo3 241 |
| copy | gr_load → one RAMRD window (`far_gcopy`, 35 B in the kernel's free card bytes `$FFBE`, 2× unrolled `lda (FA_SRC),y / sta (FA_DST),y`) | 157.6 with the artifact (−33.0) | | | | unchanged |
| E | the tic profiler's placement `opt-E-p0split.json` (42 groups) with two routines moved for the play core: ST_Ticker into group 4, `opening` into group 29 (the core was 23 B over because of dl_hook's 207 B, request P2) | 112.2 ms, 8.91 FPS (34.3 tics/s) | | | | still 17.6 |
| E1 = E + copy | | **100.2 ms, 9.98 FPS**, 35 tics/s; fastpath 95.3 ms, 10.5 FPS | **308 ms, 3.25 FPS** | 333.5 ms, 3.00 FPS | 689 ms | still 17.7; demo3 123 |
| E1L = E1 + lazy restore | fc_go pushes the slot's innermost needed group (`$80` + slot for none); fc_ret reloads only that | 97.6 ms, 10.25 FPS | 306 ms, 3.26 FPS | 331.9 ms, 3.01 FPS | 687 ms | still 15.4; demo3 121 |

**Findings from the prototypes:**
- The one-window copy and the re-placement give what the profilers predicted: copy −33 ms still, and E −67 ms of paging still (dry run −67).
- **The lazy restore does not.** The dry run predicted −35% of loads in demo3 (−39 ms a frame). Measured: −1.6% (−1.7 ms) in demo3 and −2.6 ms still. It stays in the plan as a cheap, safe change, ranked low. *Wave 1:* a placement trained for it does gain: still 18.7 → 11.4 loads a tic, measured (`docs/speed-parts/place.md`).
- After E1, demo3's frame (333.8 ms) breaks down as follows:
  - K_TIC: 250 (62.5 a tic).
    - Group copy: 134.8, 484 loads a frame at 64 µs a page.
    - Object API and planes far traffic: 69 (far_get 53.5, far_put 15.6).
    - Game code, gobj and the runtime: about 40.
    - IRQ: 4.3.
  - Render: 70.6.
  - Image loads: 14.4.
  - s2_frame: 3.6.
- **Standing still under E1** (100.2 ms, 3.5 tics a frame), the render and the image loads are now 71 ms of the frame: K_TIC 31.5 (group copy 16.1), WCODE 4.97, nr_frame 26.5, MCODE 2.54, nm_masked 3.8, nb_frame 26.8, P2DW 2.0, s2_frame 1.9.
- **Corrections to the profilers:**
  - The group copy cannot be inlined in the core (the frame profiler's "LOADW" option). With RAMRD on, opcode fetches from `$6600-$98DB` come from the RamWorks bank. That works by accident for GCODE0 (bank 72 holds the core at the same address) but not for GCODE1 groups (bank 73). It must live in the card: the FAR area has 34 B free at `$DFDE-$DFFF` and the kernel 60 B at `$FFBE-$FFF9`. *Wave 1 put it in the kernel: `far_gcopy` at `$FFD5-$FFF9` (`KERN_GCOPY`, a weak symbol of `game.cfg`; the `game.mk` images link `gdriver.s`'s per-page copy instead); the kernel's free bytes are now `$FFBE-$FFD4` (23 B).*
  - The tic profiler's text says "P_SetMobjState into the core", but its stored placement E keeps it in group 21 with P_RunThinkers. That works because P_RunThinkers and P_SetMobjState then share a group.

## 4. Optimizations ranked by saving per hour of work

The savings are for demo3 (the benchmark) and still, card-equivalent f121, in ms a frame. **[M]** means measured above. Everything else is the profilers' estimate or dry run, with a factor of 0.63 applied once the copy is fast. Hours are build plus exactness checks.

| # | Optimization | Saves demo3 | Saves still | Hours | Exactness check | Part |
| --: | --- | ---: | ---: | ---: | --- | --- |
| 1 | Re-placement of the tic code (`gplace.py` with the measured cost: pages × the real per-page cost, 5 µs a cross call, the restore rule; trained on recorded calls; core budget counting dl_hook) | about −490 [M: E alone ≈ E1 + 76] | −68.5 [M] | 8 | lockstep demo3, demo1, newgame, G1-G5 (`ticrun.py`, `test_native_game_lockstep`); `test_play_runs` | place: **built, wave 1**; with #2 and #14 −350.5 demo3, −50.0 still [M] |
| 2 | One-window group copy (`far_gcopy` in the card, gr_load calls it once a group) | −274 today; −76 after #1 [M: 64 vs 100 µs a page] | −33 today [M]; −12 after #1 [M] | 2 | lockstep runs as #1 (paging is invisible to state); DOOM.hdv scripted run | paging: **built, wave 1**; with #14 −246.9 demo3, −37.0 still [M] |
| 3 | The a2vm idle artifact (harness): condition the idle or drop it | 0 on the card (a2vm −10 to −50) | 0 (a2vm −9.7) | 2 | none to the game; `test_play_runs` still passes | measure: **done, wave 1** (a2vm −9.9 still, −10 demo3 [M]); `playtime.py` |
| 4 | Copy only the used bytes of a group's last page (byte length in the directory) | −10 to −16 [est.] | −2 to −4 | 2 | lockstep as #1 | ticloads |
| 5 | Object API: larger mobj and line caches, fewer far windows per miss (sized by a dry run of the mo/ln/sec tags) | −20 to −35 [est.] | −3 to −5 | 8 | lockstep as #1 (write-back coherence) | objapi |
| 6 | TIC_LC2: card bank 2 as 4 KB more resident tic code, the replay's bank-2 contents reloaded before nb_frame (+1 ms) | −43 [dry run F × 0.63] | −1.5 | 12 | lockstep; frame8 sample (replay bank reload); DOOM.hdv run | lc2 |
| 7 | Glue tickers resident (DLG_H, and DLG_S if room; the brain alone in slot 2) | −3 to −5 [est.] | −2 to −4 | 4 | DOOM.hdv scripted run (`test_play_runs`: HUD timeout, status face) | glue |
| 8 | Bucket pass: per-column counts from rec_room (optimization 10), chunk copy with patched abs,y, walk2 unrolled; faster rec_flush/mrec_flush | −5 to −6 median, −12 to −15 heavy | −4 to −4.5 | 10 | `frame8.py` demo3 sample both fills; `bucketcheck.py`; RENDER/REPLAY disk CRCs | bucket: **built, wave 1**: render −4.8 still, −4.5 at demo3's median, −13.2 heaviest [M]; walk 2 not unrolled (no room) |
| 9 | Lazy `$C073` (write RWBANK only when the bank differs; every bank-0 user writes it first) | −10 to −15 [est. from io time] | −3.5 [what-if M] | 14 | frame8 (all 533 demo3); lockstep; DOOM.hdv run (SHR writes) | lazybank |
| 10 | Replay texels: wrap-only spans copy only [ti,128) and [0,ti+count-128); patched span loop; the gather's stage need computed in walk 2 | −3 to −4.5 median, −9 to −20 heavy | −0.6 to −2 | 12 | frame8 demo3 sample; `replay_check.py`; disk CRCs | replay |
| 11 | far_pload 2× abs,y with patched operands; WCODE's run from `$65`; the tic image's from `$66` with a link-time identity assert of `$6000-$65FF` | −2.6 | −2.6 | 3 | DOOM.hdv run; frame8 sample (WCODE); the assert | frontend (far.s), ticloads (k_core) |
| 12 | Planes in and out only below G_MOHWM; TNL/TNH/KIND written back only when dirty; one RAMWRT window | −1 | −2 | 3 | lockstep (dirty flag covers every writer) | ticloads |
| 13 | Box-corner angle cache (optimization 2); weapon profile reuse (8); projection one window a sector chain (6) | −1 to −2 | −2 to −3 when still or turning | 6 | frame8 sample; FRVIS/WPREV invalidation | frontend |
| 14 | Lazy restore in gcall.s | −1.7 [M] | −2.6 [M] | 2 (prototype exists) | lockstep as #1 | paging: **built, wave 1** |
| 15 | Replay overlap: gather the next strip while the drain runs | 0 median, −1 to −2 two-strip frames | 0 | 6 | frame8 | replay |
| — | **The benchmark itself** (REQ_BENCH) | 0 | 0 | 5 | DOOM.hdv run to demo3's end; lockstep unchanged (the hook is a stop in lockstep builds) | bench: **built, wave 1** |

Not worth doing now:
- The game parts' own code is about 13 ms a frame in demo3.
- IRQs are 0.6-1.1% of the frame.
- MAXTICS stays 4: changing it changes which gametics are drawn.
- Optimization 5 (page-order fills) gains nothing at the median: the draw already runs at one byte an Apple cycle.

## 5. Expected FPS after each wave (f121, card-equivalent)

| After | Still E1M1 | demo3 mean (benchmark) | Heaviest demo3 frame | Basis |
| --- | ---: | ---: | ---: | --- |
| Today | 180.7 ms, **5.5 FPS** (21 tics/s) | 873 ms, **1.15 FPS** | 1,656 ms | M |
| Wave 1 (placement, copy, idle fix, bucket, the benchmark), expected | about 96 ms, **10.4 FPS**, 35 tics/s | 290-300 ms, **3.3-3.5 FPS** | about 650 ms | M for E1 (100.2 / 308-333 / 689), plus estimates for bucket (−4) and the retrained placement (0 to −30) |
| **Wave 1, measured** (integrated 2026-10-02) | **87.9 ms, 11.37 FPS**, 34.9 tics/s | **271.6 ms, 3.68 FPS** (median 271.5) | 635 ms | M: `playtime.py`, below |
| Wave 2 (object API, glue, last page, planes, image loads, replay, front end) | about 85 ms, **11.8 FPS** | 230-250 ms, **4.0-4.4 FPS** | about 520 ms | estimates of section 4 |
| Wave 3 (TIC_LC2, lazy `$C073`, a last re-placement) | about 80 ms, **12.5 FPS** | 180-200 ms, **5.0-5.6 FPS** | about 420 ms | estimates |

**Wave 1 as integrated** (2026-10-02): parts measure, bench, paging, place (`tools/native/gplace-wave1-lazy.json`) and bucket together, `build/native/DOOM.hdv`, a2vm, card-equivalent (the exact idle):

| Scene | Profile | Before (the owner's build) | After wave 1 | Change |
| --- | --- | ---: | ---: | ---: |
| E1M1 start, standing still, 15-25 s | f121 | 180.7 ms, 5.53 FPS; K_TIC 112.1; 38.84 loads a tic | **87.9 ms, 11.37 FPS** (median 87.1, max 107.0); K_TIC 24.4; 11.48 loads a tic; 34.9 tics/s | −92.8 ms |
| | fastpath | 154.3 ms, 6.48 FPS | **84.3 ms, 11.86 FPS**; K_TIC 20.0; s2_frame 8.9 | −70.0 ms |
| demo3, gametics 1052-1796, 186 frames | f121 | 873.3 ms mean, 877.2 median, 1,656 max, 1.15 FPS; 240.9 loads a tic | **271.6 ms mean, 271.5 median, 635 max, 3.68 FPS**; K_TIC 188.4; 63.5 loads a tic | −601.7 ms |
| | fastpath | 687.1 ms, 1.46 FPS (*) | **243.8 ms, 4.10 FPS** | −443.3 ms |
| The menu's BENCHMARK, all of demo3 (534 frames) | f121 | FPS 0.912 (*) | **FPS 3.318** (5,632 realtics, 301 ms a frame) | |
| | fastpath | FPS 1.177 (*) | **FPS 3.842** (4,864 realtics) | |

(*) Measured on the owner's build plus part bench alone (the benchmark did not exist before; part bench's +4 B of core and larger brain group make still 182.5 ms there against 180.7).

- **Still, f121, by step (ms a frame):** K_TIC 24.36, K_WLOAD 4.95, nr_frame 25.94, K_MLOAD 2.62, nm_masked 3.89, nm_bkload 0.21, nb_frame 22.19, P2DW 1.97, s2_frame 1.82. The render and the image loads are now 72% of the frame.
- **demo3, f121, by step:** K_TIC 188.37, K_WLOAD 4.96, nr_frame 21.92, K_MLOAD 2.62, nm_masked 7.70, nm_bkload 0.21, nb_frame 40.25, P2DW 1.98, s2_frame 3.54. The tic phase is still 69% of the frame: the object API's far traffic and the remaining group copy (63.5 loads a tic) are wave 2's.
- **Render alone** (`frame8.py --timing`, f121, the integrated renderer): still-1 59.36 ms, demo3-325 (median) 67.87, demo3-036 (heaviest) 151.14: part bucket's figures exactly.
- **Better than expected:** still 87.9 against about 96 ms, demo3 272 against 290-300 ms. The retrained placement (part place's model, trained for the lazy restore) gave more than the 0 to −30 ms estimated.
- **Commands:** `python3 tools/native/playtime.py --scene still|demo3 --profile f121|fastpath`; the benchmark: OPTIONS, BENCHMARK from the title page (`test_play_bench.to_benchmark(7)`) on the whole demo, a2vm stopped when `DL_BRT` is written (`--stop-word`), FPS by bmDone's formula from `DL_BVIEW` and `DL_BRT` (the page's text, as `test_play_bench` checks).

**Integration** (2026-10-02). What the integrator changed beyond the parts' own files, and why:

- The parts' requests: `playlayout.py` `DLM_FIELDS` names `DL_BENCH`, `DL_BVIEW`, `DL_BRT` (DLM 82 of 128 B; `dl.inc`'s fallback places removed); `s2_menu.s`'s bmStop comment; `play.mk`'s tic stamp depends on `placement.json`; `s2ovl.py` `ovlw_allowed()` lets OVLW's `mrec_room` write MCNT; `testpar.py` and `tests/README.md`: `build/native/play` written by `test_play_runs` and `test_play_bench`, read by `test_playtime`, and `playdisk.make` a guarded writer call; the docs each part named.
- The placement: `gplace.py --placement tools/native/gplace-wave1-lazy.json --no-search --write` (core 3,215 of 3,223 B against gprof's fixed 10,073 B; the play core 13,007 of 13,312 B).
- Three checks that the first suite run failed, each a test's assumption that wave 1 changed, not a game difference:
  1. `test_play_runs.Level.test_keys_move_turn_and_strafe` assumed the player faced about 130° after holding the left arrow for 1 s of model time; at the new frame rate it turns to 190°, so strafing left no longer goes west. The check now takes the strafe direction from the measured angle (angle + 90°): 204 units along it.
  2. `test_m11_s2ovl`'s `w_untouched` required W outside OVLW's room unchanged in OVLW's phase, but OVLW's `mrec_room` now adds its records to MCNT (`$6600-$669F`, `$6700-$679F`), by part bucket's design. Those two ranges are now excepted, like `BATCH`.
  3. `test_native_frame8`'s plant "a record lost at the bucket (walk 2 skips column 80's fills)" is still caught in both of its frames, but in demo3-053 no longer as a batch difference: with the producers' counts a lost record leaves a gap of stale bytes, and the fuzz marks' walk loops on it before batch 0 reaches the replay (the run ends on the write log's bound). `frame8.py` now names such a run "in the bucket pass" (and gives it the bucket check, as after a stop), and the plant accepts that besides `batch `.
- **A stale load image found:** `playdisk.py` reads milestone 9's `lcard` (LCODE) from `build/native/levels/obj` without rebuilding it, and LCODE links the runtime's state, which part paging's `SLOT_NEED` moved by 2 B. The first DOOM.hdv of the integration held the old LCODE (19 bytes differ); the suite's prebuild remade `level.mk`, and the disk was rebuilt and measured again (every figure above is the rebuilt disk's; they equal the first's but for fastpath demo3, 243.9 → 243.8 ms). Section 7 step 2 now names `level.mk`.

Walking falls between still and demo3. E1 measured 160 ms (6.2 FPS) on a walk, but the route diverges from the base run because the input runs on model time, so it is not a like-for-like figure.

## 6. What exact optimizations can reach on F1.2.1, and what needs the firmware design

**F1.2.1, exact: about 12-13 FPS standing still and 5-6 FPS in demo3** (the benchmark), with the heaviest fights at 2.5-3.5 FPS.

After wave 3, demo3's frame is still about 4 tics × about 25 ms plus a render of about 65 ms (the replay's SHR drain alone has a floor of 22.5 ms at the median and 55-71 ms in the heaviest frames, at 0.985 µs a screen byte) plus 14 ms of image loads. demo3 keeps 4 tics a frame because the frame stays above 114 ms, so the game runs at about 20 tics a second, below real time. Standing still reaches 35 tics a second (real time) from wave 1 on. Below those figures, every remaining cost is a soft-switch window, a RamWorks line miss or the SHR drain, and F1.2.1 sets each of them.

**What needs the firmware design** (docs/firmware: the zero-page bank pair, the lazy SHR mirror, the quiet switches):
- **The tic phase's code room and far access.** The pair build (milestone 13, MEMORY_MAP 4.4) moves the tics to the aux card. That makes most of the remaining paging (after wave 3, about 40 ms a frame in demo3) and most of the object API's windows (about 40 ms) disappear. No exact change on F1.2.1 can do the same: the core is 13 KB, the slots 4 KB, and a group copy costs at least about 64 µs a page against a RamWorks floor of about 31.
- **The replay's drain** (22.5 ms median, up to 71 heaviest). The lazy SHR class plus moving the flush off the critical path is the only lever. On F1.2.1 nothing exact goes below the drain floor except writing fewer bytes.
- **The fast path alone (a2vm `fastpath`) is not enough.** On the E1 build it gives 95.3 ms against 100.2 standing still (−5%). It does not remove paging, and it moves the SHR flush into s2_frame (+7.6 ms). The pair is the lever. NATIVE.md 1.1's design-plus-pair estimate (18-29 demo FPS) predates milestone 10's measurements. After waves 1-3, about 10-15 FPS in demo3 is a fair estimate, not measured.

## 7. Integrator's steps (after each wave)

The owner's rule (2026-10-02, `MILESTONES.md` ground rules): test only what changed, with the one check that covers it, then the fast full suite once.

1. **The placement.** `python3 tools/native/gplace.py --write` starts from the current `placement.json` (code sizes change with every wave); give `--placement FILE` to start from a part's file, `--no-search` to take it as it is (wave 1: `--placement tools/native/gplace-wave1-lazy.json --no-search --write`). A part that changes which routines call which needs `python3 tools/native/gplacerec.py still walk fight demo3 demo3b lock3a lock3b --jobs 2` first (about 8 minutes).
2. **Build**, with no warnings: `make -s -C src/native -f game.mk shared game gprof release skel ROOT=$PWD`; the load image `make -s -C src/native -f level.mk ROOT=$PWD` (LCODE links the runtime's state: `playdisk.py` reads it and does not rebuild it); the renderer `make -s -C src/native -f render.mk ROOT=$PWD` and milestone 11's images `make -s -C src/native -f m11.mk images ROOT=$PWD` (OVLW carries its own copy of the bucket pass and `mrec_room`: rebuild it with the renderer; `s2ovl.image_problems()` must be `[]`); then `python3 tools/native/playdisk.py` (`play.mk`'s tic stamp now follows `placement.json`).
3. **The checks of what changed, once each:**
   - game code, its placement or the paging: `python3 tools/native/ticrun.py --run demo3 --frames front --fills a5 --jobs 2`;
   - the renderer: `python3 tools/native/frame8.py --no-build --fills a5 --frames ...` on about 20 frames (demo3-036, the ten heaviest by `build/native/render/report8.md`, every 50th demo3 frame);
   - a menu or the kernel: a scripted run of that feature (the benchmark: `python3 -m unittest test_play_bench` from `tests/`);
   - then `python3 tools/testpar.py`.
4. **Measure** with `tools/native/playtime.py` (still and demo3, f121 and fastpath) and the menu's BENCHMARK; write the figures into section 5 and `PLAY.md` 8, and the parts' notes (`docs/speed-parts/*.md`) into this document.

## 8. Risks

- **Re-placement.** A routine that reaches another routine's code with a plain `jsr` instead of FCALL breaks when they are placed apart. AFFINITY units are split only across source files, `planes.s` asserts its pair, and a break shows at link time or in lockstep. A group must stay within 2,048 B minus GROUP_MARGIN, and the core within its room, counting dl_hook (the first try of E overflowed by 23 B).
- **far_gcopy's home.** The lockstep and test images (gdriver, ticrun timing) have no play kernel. Choose one routine every image links (preferred: a new segment appended after MFAR in the FAR area, 30 B with a branch into far_pload's tail, 34 B free), or the kernel bytes plus far_get's loop under `.ifdef` in the other builds. The IRQ handler stays within its bounds, as for far_pload.
- **TIC_LC2.** Tic code in card bank 2 cannot call the bank-1 math products or the far layer without a bank switch. Each switch is a `$C08x` bus access that clears the TURBO caches. Measure before committing.
- **Lazy `$C073`.** Every image, handler and SHR writer that assumes `$C073` = 0 must write it first. A miss writes the screen or the staging into the wrong bank: frame8, the disk CRCs and the DOOM.hdv shots catch it.
- **The lazy restore.** As safe as today's rule: it keeps every active frame's group. The `$80`+slot encoding keeps 1 B a call on the stack, and SLOT_NEED must be reset with SLOT_GRP at K_TIC and in gdriver's go_reset path.
