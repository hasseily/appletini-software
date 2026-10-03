# DOOM GS speed plan

Written 2026-10-02 from three profilers' measurements and a planner's prototypes (workflow `doom-gs-speed-profile`); the owner's rule of the same day applies to every part: test only what a change touches (`MILESTONES.md`, ground rules).

Status: **waves 1 and 2 built and integrated (2026-10-02 and 2026-10-03; section 5, `PLAY.md` 14 and 16); the frame slots built (2026-10-03; section 9, `PLAY.md` 17); the frame's bulk copies by the copy engine (2026-10-03; section 10, `PLAY.md` 18: a2vm `f122-nod2` 5.677 → 6.519 FPS); wave 3 planned.** The card (F1.2.2, the Disk II's acceleration off) ran wave 2's benchmark at 3.830 FPS; a2vm `f122-nod2` matches it and predicted 5.68 FPS with the frame slots; the card gave 5.648 (sections 5 and 9). The owner played `build/native/DOOM.hdv` on the card on 2026-10-02 and reported: "Everything seems to work except for the benchmark. It's indeed too slow and needs a speed optimization." This document holds the measurements behind that, three prototypes measured on a2vm, and the parts that make the game faster. Nothing in the game's output may change. The renderer's frames and the game's demo sync stay bit-exact against ref816 (NATIVE.md 15.1). Every item below changes only time: where code lives, how bytes are copied, and which pages are reloaded.

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
| 4 | Copy only the used bytes of a group's last page (byte length in the directory) | −10 to −16 [est.] | −2 to −4 | 2 | lockstep as #1 | ticloads: **built, wave 2**: −3.6 demo3, −0.75 still [M] (the placement fills groups near 2,048 B); with request 3, one window a group (gdriver.s's far_gcopy from byte Y), about −1.2 more in demo3 [M by the part] |
| 5 | Object API: larger mobj and line caches, fewer far windows per miss (sized by a dry run of the mo/ln/sec tags) | −20 to −35 [est.] | −3 to −5 | 8 | lockstep as #1 (write-back coherence) | objapi: **built, wave 2**: one page-1 window a miss, gets from the most recent line; caches stay 8/8/8/5 (bigger ones buy about 1.5 ms in room that does not exist): −13.4 demo3, −0.8 still [M]; what reaches further is in `speed-parts/objapi.md` 5 |
| 6 | TIC_LC2: card bank 2 as 4 KB more resident tic code, the replay's bank-2 contents reloaded before nb_frame (+1 ms) | −43 [dry run F × 0.63] | −1.5 | 12 | lockstep; frame8 sample (replay bank reload); DOOM.hdv run | lc2 |
| 7 | Glue tickers resident (DLG_H, and DLG_S if room; the brain alone in slot 2) | −3 to −5 [est.] | −2 to −4 | 4 | DOOM.hdv scripted run (`test_play_runs`: HUD timeout, status face) | glue: **built, wave 2** (the HUD's ticker; the status bar's has no room): −1.65 demo3, −1.3 still [M] |
| 8 | Bucket pass: per-column counts from rec_room (optimization 10), chunk copy with patched abs,y, walk2 unrolled; faster rec_flush/mrec_flush | −5 to −6 median, −12 to −15 heavy | −4 to −4.5 | 10 | `frame8.py` demo3 sample both fills; `bucketcheck.py`; RENDER/REPLAY disk CRCs | bucket: **built, wave 1**: render −4.8 still, −4.5 at demo3's median, −13.2 heaviest [M]; walk 2 not unrolled (no room) |
| 9 | Lazy `$C073` (write RWBANK only when the bank differs; every bank-0 user writes it first) | −10 to −15 [est. from io time] | −3.5 [what-if M] | 14 | frame8 (all 533 demo3); lockstep; DOOM.hdv run (SHR writes) | lazybank |
| 10 | Replay texels: wrap-only spans copy only [ti,128) and [0,ti+count-128); patched span loop; the gather's stage need computed in walk 2 | −3 to −4.5 median, −9 to −20 heavy | −0.6 to −2 | 12 | frame8 demo3 sample; `replay_check.py`; disk CRCs | replay: **wraps built, wave 2**: render −0.43 still, −1.97 at demo3's median, −3.69 demo3 mean, −8.3 to −26.2 in the ten heaviest [M]; the patched loop measured slower, the stage need has no place: not built |
| 11 | far_pload 2× abs,y with patched operands; WCODE's run from `$65`; the tic image's from `$66` with a link-time identity assert of `$6000-$65FF` | −2.6 | −2.6 | 3 | DOOM.hdv run; frame8 sample (WCODE); the assert | **built, wave 2**: WCODE from `$65` (`far_wloadt`, K_WLOAD 4.95 → 4.70) and the tic image's core from `$66` after P2DW (`playdisk.shared_w_problems`); the patched loop gives nothing on F1.2.1 (13% fewer cycles, the same 4.92 ms: a page costs its RamWorks reads; fastpath −0.57 ms a WCODE load), not built |
| 12 | Planes in and out only below G_MOHWM; TNL/TNH/KIND written back only when dirty; one RAMWRT window | −1 | −2 | 3 | lockstep (dirty flag covers every writer) | ticloads: **built, wave 2** but the dirty flag: with #11's `$66`, −1.4 demo3, −2.6 still [M]; the dirty flag measured +0.9 demo3, −0.14 still (a compare in pl_put, 1,200 a frame), dropped |
| 13 | Box-corner angle cache (optimization 2); weapon profile reuse (8); projection one window a sector chain (6) | −1 to −2 | −2 to −3 when still or turning | 6 | frame8 sample; FRVIS/WPREV invalidation | frontend: **corner cache and the weapon clip pass's reuse built, wave 2** (with #11's far_wloadt: −2.4 still, −0.4 demo3 [M]); the projection's not built |
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
| **Wave 2, measured** (integrated 2026-10-03) | **80.3 ms, 12.45 FPS** | **247.2 ms, 4.04 FPS** (median 245.8) | 647 ms (not like for like: the cut groups other tics) | M: `playtime.py`, below |
| **Wave 2, a2vm corrected by the card** (2026-10-03; the rows above: the model before) | **96.2 ms, 10.40 FPS** | **297.0 ms, 3.37 FPS** (median 297.3); the benchmark 3.004 FPS, the card 3.015 | 737 ms | M: `playtime.py`, below ("a2vm corrected by the card") |
| **The frame slots, measured** (2026-10-03, a2vm corrected; section 9) | **90.8 ms, 11.02 FPS** | **203.7 ms, 4.91 FPS** (median 205.8); the benchmark **4.641 FPS** | 370 ms | M: `playtime.py`, section 9 |
| **The copy engine, measured** (2026-10-03, a2vm `f122-nod2`, the card's setting; section 10) | **58.9 ms, 16.97 FPS** (before 72.7, 13.75) | **143.7 ms, 6.96 FPS** (median 149.4; before 166.5, 6.01); the benchmark **6.519 FPS** (before 5.677) | 259 ms | M: `playtime.py`, section 10 |
| Wave 3 (TIC_LC2, lazy `$C073`, a last re-placement) | about 80 ms, **12.5 FPS** | 180-200 ms, **5.0-5.6 FPS** | about 420 ms | estimates |

**Wave 1 as integrated** (2026-10-02): parts measure, bench, paging, place (`tools/native/gplace-wave1-lazy.json`) and bucket together, `build/native/DOOM.hdv`, a2vm, card-equivalent (the exact idle):

| Scene | Profile | Before (the owner's build) | After wave 1 | Change |
| --- | --- | ---: | ---: | ---: |
| E1M1 start, standing still, 15-25 s | f121 | 180.7 ms, 5.53 FPS; K_TIC 112.1; 38.84 loads a tic | **87.9 ms, 11.37 FPS** (median 87.1, max 107.0); K_TIC 24.4; 11.48 loads a tic; 34.9 tics/s | −92.8 ms |
| | fastpath | 154.3 ms, 6.48 FPS | **84.3 ms, 11.86 FPS**; K_TIC 20.0; s2_frame 8.9 | −70.0 ms |
| demo3, gametics 1052-1796, 186 frames | f121 | 873.3 ms mean, 877.2 median, 1,656 max, 1.15 FPS; 240.9 loads a tic | **271.6 ms mean, 271.5 median, 635 max, 3.68 FPS**; K_TIC 188.4; 63.5 loads a tic | −601.7 ms |
| | fastpath | 687.1 ms, 1.46 FPS (*) | **243.8 ms, 4.10 FPS** | −443.3 ms |
| The menu's BENCHMARK, all of demo3 (534 frames) | f121 | FPS 0.912 (*) (**) | **FPS 3.302** (5,659 realtics, 303 ms a frame; first read 3.318, (**)) | |
| | fastpath | FPS 1.177 (*) (**) | **FPS 3.732** (5,008 realtics; first read 3.842, (**)) | |

(*) Measured on the owner's build plus part bench alone (the benchmark did not exist before; part bench's +4 B of core and larger brain group make still 182.5 ms there against 180.7).

(**) The integration first read the benchmark with a2vm stopped as soon as `G_TimeDemoEnd` began writing `DL_BRT` (`--stop-word`). It writes the high bytes first, so the low byte was still 0: 20,480 = `$5000`, 5,632 = `$1600`, 4,864 = `$1300` realtics, and each FPS too high. Read again on 2026-10-02 with the page up (`playtime.py --scene bench`, below): 3.302 (f121) and 3.732 (fastpath) for this build. The "before" figures were not measured again (20,480 to 20,735 realtics: FPS 0.901 to 0.912).

- **Still, f121, by step (ms a frame):** K_TIC 24.36, K_WLOAD 4.95, nr_frame 25.94, K_MLOAD 2.62, nm_masked 3.89, nm_bkload 0.21, nb_frame 22.19, P2DW 1.97, s2_frame 1.82. The render and the image loads are now 72% of the frame.
- **demo3, f121, by step:** K_TIC 188.37, K_WLOAD 4.96, nr_frame 21.92, K_MLOAD 2.62, nm_masked 7.70, nm_bkload 0.21, nb_frame 40.25, P2DW 1.98, s2_frame 3.54. The tic phase is still 69% of the frame: the object API's far traffic and the remaining group copy (63.5 loads a tic) are wave 2's.
- **Render alone** (`frame8.py --timing`, f121, the integrated renderer): still-1 59.36 ms, demo3-325 (median) 67.87, demo3-036 (heaviest) 151.14: part bucket's figures exactly.
- **Better than expected:** still 87.9 against about 96 ms, demo3 272 against 290-300 ms. The retrained placement (part place's model, trained for the lazy restore) gave more than the 0 to −30 ms estimated.
- **Commands:** `python3 tools/native/playtime.py --scene still|demo3 --profile f121|fastpath`; the benchmark: `python3 tools/native/playtime.py --scene bench [--profile fastpath]` (OPTIONS, BENCHMARK from the title page, `test_play_bench.to_benchmark(7)`'s keys, on the whole demo; the run goes on with the page up and its FPS, realtics and rows are read from the last snapshot; not with a `--stop-word` on `DL_BRT`, (**)).

**The benchmark's rows** (2026-10-02, `PLAY.md` 15): the result page now also shows each phase's mean a frame, timed on the machine by the Phasor's VIA-A timer 1. The owner's card shows 2.897 FPS (PAL //e, 50 Hz); its rows against these show which phase a2vm models as too fast. a2vm, `build/native/DOOM.hdv` of 2026-10-02 (SHA-1 `90635ac1…`), the whole benchmark (534 frames), ms a frame:

| Row of the page | What it times | f121, the page | f121, `playtime.py`'s kernel steps (same run) | fastpath, `playtime.py` (the build without the timing) |
| --- | --- | ---: | ---: | ---: |
| TIC | `K_TIC`: the tic image back, the brain, the 4 tics (paging, far windows), the list | **225.2** | 225.5 | 186.9 |
| 3D | `K_WLOAD`, `nr_frame` | **23.2** | 23.1 | 19.8 |
| MASK | `K_MLOAD`, `nm_masked`, `nm_bkload`, `nb_frame`'s bucket pass | **14.2** | 14.2 | 12.5 |
| DRAW | `nb_frame`'s replays (`nat_replay`, the SHR drain included) | **35.7** | 35.8 | 29.7 |
| REST | `PALW`, `P2DW`'s load, `s2_frame` | **5.6** | 5.4 (+ 0.12 of the list's reads) | 23.2 (fastpath moves the SHR flush into `s2_frame`) |
| N, FPS | frames, the page's FPS | **534, 3.294** | | 534, 3.732 (5,008 realtics) |

The timing itself costs 0.8 ms a frame on f121 (0.26%: FPS 3.302 without it, 3.294 with it; about 40 µs a boundary, 6 to 8 boundaries a frame, and two glue groups a few pages longer), and its rows agree with the kernel steps within 0.3 ms a frame (`PLAY.md` 15). On the card, 345 ms a frame (2.897 FPS) against a2vm's 304: the rows will show where the 41 ms are.

**The card's rows** (the owner, 2026-10-03, PAL //e, the same disk): `TIC 260  3D 26.1` / `MASK 16.4  DRAW 37.7` / `REST 6.2  N 534  OVF 1`.

| Row | Card | a2vm f121 | Card slower by |
| --- | ---: | ---: | ---: |
| TIC | 260.0 | 225.2 | +34.8 (15.5%) |
| 3D | 26.1 | 23.2 | +2.9 (12.5%) |
| MASK | 16.4 | 14.2 | +2.2 (15.5%) |
| DRAW | 37.7 | 35.7 | +2.0 (5.6%) |
| REST | 6.2 | 5.6 | +0.6 (11%) |
| Frame | 346.4 | 303.9 | +42.5 (14%) |

Reading: no single phase is wrong; every phase that computes and reaches RamWorks runs 12-15% slower on the card than a2vm's f121 model, while DRAW, bound by the SHR drain that a2vm models from the card's own measurements, is 5.6% slower. Scale a2vm's estimates of TIC, 3D and MASK by about 1.14 for the card. TIC is 75% of the card's frame and 35 of its 42.5 extra ms, so the game's tic phase is where the speed is (waves 2 and 3: the object API, the tic loads, the glue, TIC_LC2, lazy `$C073`). OVF 1: in one frame the timing could not place two intervals of 3 VBLs or more (`PLAY.md` 15); the totals and the FPS are unaffected.

**The card after wave 2** (the owner, 2026-10-03, disk SHA-1 `f92c81ae…`): FPS **3.015**, `TIC 250.4  3D 25.8` / `MASK 16.3  DRAW 33.2` / `REST 6.3  N 534`.

| Row | Card, wave 1 | Card, wave 2 | Card's change | a2vm's predicted change |
| --- | ---: | ---: | ---: | ---: |
| TIC | 260.0 | 250.4 | -9.6 | -24.1 |
| 3D | 26.1 | 25.8 | -0.3 | -0.3 |
| MASK | 16.4 | 16.3 | -0.1 | 0 |
| DRAW | 37.7 | 33.2 | -4.5 | -3.8 |
| REST | 6.2 | 6.3 | +0.1 | 0 |
| Frame | 346.4 (2.897 FPS) | 331.9 (3.015 FPS) | -14.5 | -28.3 |

The renderer's and the replay's gains held on the card; the tic phase's did not (40% of the predicted gain). The card's TIC is now 25% above a2vm's (15% after wave 1): a2vm underestimates the tic phase's RamWorks work (far windows, small fetches, group copies). Next: `CALIB.hdv` measures those operations on the card to correct a2vm's cost model (`docs/results/calib.md`) before wave 3.

**a2vm corrected by the card** (2026-10-03, `docs/results/calib.md`; `tools/a2vm/README.md`, "Calibration on the card"). `CALIB.hdv`'s 44 lines showed the cause: not the RamWorks work as such, but the CPU. The owner's card has its virtual Disk II active in slot 6, and the Disk II replays, one a fabric clock, the 65C02 cycles each TURBO step stands for, holding the next step until it has (`disk2_card.sv:374-412`): every dummy read the TURBO core omits still costs 2 clocks, so code runs at 66.7 MHz of 65C02 cycles where a2vm had 110. Bus-bound work (line misses, the SHR drain, single switches) was already right. One new parameter (`d2_replay`) and five corrected readings of the RTL's bus, pacing and PSRAM taps bring every CALIB line within 0.6% of the card. The benchmark on the corrected model (`playtime.py --scene bench`, ms a frame), both waves' disks (wave 1's rebuilt byte for byte from `b894fb5c` in a scratch tree, with its own placement `gplace-wave1-lazy.json`):

| Row | Card, wave 1 | a2vm, wave 1 | Card, wave 2 | a2vm, wave 2 | a2vm before, wave 2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| FPS | 2.897 | **2.887** (-0.3%) | 3.015 | **3.004** (-0.4%) | 3.631 |
| TIC | 260.0 | 260.2 (+0.1%) | 250.4 | 251.7 (+0.5%) | 201.1 |
| 3D | 26.1 | 26.1 | 25.8 | 25.8 | 22.9 |
| MASK | 16.4 | 16.4 | 16.3 | 16.3 | 14.2 |
| DRAW | 37.7 | 37.7 | 33.2 | 33.2 | 31.9 |
| REST | 6.2 | 6.2 | 6.3 | 6.2 (-1.6%) | 5.6 |
| N, OVF | 534, 1 | 534, 2 | 534 | 534, 0 | 534 |

Wave 2's change on the corrected model: TIC -8.5 ms (the card -9.6, the model before -24.1), DRAW -4.5 (-4.5), the frame -13.4 (-14.5): the corrected model reproduces the card's smaller gain of the tic phase. Wave 2 on the corrected model, the other scenes: still 96.2 ms (median 93.9, max 118.2), **10.40 FPS**, K_TIC 26.99; demo3 (gametics 1052-1796) 297.0 ms (median 297.3, max 736.8), **3.37 FPS**, K_TIC 210.30; fastpath's benchmark 3.489 FPS. The figures of sections 2-4 and 6 and the rows above this one are the model before the correction (`playtime.py --profile f121-precal` gives them again), about the card with no active Disk II.

**The setting it suggests.** With the virtual Disk II inactive (`disk2.slot6.enabled=off`, the firmware's default, or `vtw.disk2.acceleration.disabled=on`, in the DOOM profile; the cost variant `nod2`, `playtime.py --profile f121-nod2`), the omitted dummy reads take no time: wave 2's benchmark 3.609 FPS on a2vm (`TIC 202.7  3D 23.0  MASK 14.2  DRAW 32.0  REST 5.6`), **+20%** over 3.004 as the card is set, with no code change. A prediction, from the RTL: a run of the benchmark (and of `CALIB.hdv`, whose header should then read about 110 MHz) with that profile key checks it. Wave 3's estimates (the table above) are to be remade on the corrected model.

**The card with that setting, then on F1.2.2** (the owner, 2026-10-03, PAL, the same wave 2 disk `f92c81ae…`, `vtw.disk2.acceleration.disabled=on`). Firmware F1.2.2 (appletini-one `3101934`) admits PSRAM requests as soon as the service can while vTW owns the bus and runs the memory API's copies on an FPGA engine; a2vm's profile `f122` models both (`tools/a2vm/README.md`, "F1.2.2: the profile `f122`"; `CALIB.hdv` on F1.2.2: `docs/results/calib.md`, "The card on F1.2.2"):

| | Card F1.2.1, Disk II on | Card F1.2.1, Disk II off | a2vm `f121-nod2` | Card F1.2.2, Disk II off | a2vm `f122-nod2` |
| --- | ---: | ---: | ---: | ---: | ---: |
| FPS | 3.015 | 3.610 | 3.609 | 3.830 | 3.829 |
| TIC | 250.4 | 202.6 | 202.7 | 189.4 | 189.5 |
| 3D | 25.8 | 23.0 | 23.0 | 21.9 | 21.9 |
| MASK | 16.3 | 14.2 | 14.2 | 13.8 | 13.8 |
| DRAW | 33.2 | 31.9 | 32.0 | 31.4 | 31.4 |
| REST | 6.3 | 5.6 | 5.6 | 4.9 | 4.9 |
| N | 534 | 534 | 534 | 535 | 535 |

The owner's card runs this way from now on: `playtime.py --profile f122-nod2` is the card-equivalent figure.

**Integration** (2026-10-02). What the integrator changed beyond the parts' own files, and why:

- The parts' requests: `playlayout.py` `DLM_FIELDS` names `DL_BENCH`, `DL_BVIEW`, `DL_BRT` (DLM 82 of 128 B; `dl.inc`'s fallback places removed); `s2_menu.s`'s bmStop comment; `play.mk`'s tic stamp depends on `placement.json`; `s2ovl.py` `ovlw_allowed()` lets OVLW's `mrec_room` write MCNT; `testpar.py` and `tests/README.md`: `build/native/play` written by `test_play_runs` and `test_play_bench`, read by `test_playtime`, and `playdisk.make` a guarded writer call; the docs each part named.
- The placement: `gplace.py --placement tools/native/gplace-wave1-lazy.json --no-search --write` (core 3,215 of 3,223 B against gprof's fixed 10,073 B; the play core 13,007 of 13,312 B).
- Three checks that the first suite run failed, each a test's assumption that wave 1 changed, not a game difference:
  1. `test_play_runs.Level.test_keys_move_turn_and_strafe` assumed the player faced about 130° after holding the left arrow for 1 s of model time; at the new frame rate it turns to 190°, so strafing left no longer goes west. The check now takes the strafe direction from the measured angle (angle + 90°): 204 units along it.
  2. `test_m11_s2ovl`'s `w_untouched` required W outside OVLW's room unchanged in OVLW's phase, but OVLW's `mrec_room` now adds its records to MCNT (`$6600-$669F`, `$6700-$679F`), by part bucket's design. Those two ranges are now excepted, like `BATCH`.
  3. `test_native_frame8`'s plant "a record lost at the bucket (walk 2 skips column 80's fills)" is still caught in both of its frames, but in demo3-053 no longer as a batch difference: with the producers' counts a lost record leaves a gap of stale bytes, and the fuzz marks' walk loops on it before batch 0 reaches the replay (the run ends on the write log's bound). `frame8.py` now names such a run "in the bucket pass" (and gives it the bucket check, as after a stop), and the plant accepts that besides `batch `.
- **A stale load image found:** `playdisk.py` reads milestone 9's `lcard` (LCODE) from `build/native/levels/obj` without rebuilding it, and LCODE links the runtime's state, which part paging's `SLOT_NEED` moved by 2 B. The first DOOM.hdv of the integration held the old LCODE (19 bytes differ); the suite's prebuild remade `level.mk`, and the disk was rebuilt and measured again (every figure above is the rebuilt disk's; they equal the first's but for fastpath demo3, 243.9 → 243.8 ms). Section 7 step 2 now names `level.mk`.

**Wave 2 as integrated** (2026-10-03): parts objapi, ticloads (with its request 3), glue, replay and frontend together, `build/native/DOOM.hdv` (SHA-1 `f92c81ae…`), a2vm card-equivalent (the exact idle). "Before" is HEAD's disk rebuilt byte for byte (SHA-1 `90635ac1…`, the owner's disk of wave 1 with the benchmark's timing) and measured again with the same a2vm binary:

| Scene | Profile | Before (wave 1 + the timing) | After wave 2 | Change |
| --- | --- | ---: | ---: | ---: |
| E1M1 start, standing still, 15-25 s | f121 | 88.4 ms (median 87.4), 11.32 FPS; K_TIC 24.78; 11.47 loads a tic | **80.3 ms (median 80.3, max 100.2), 12.45 FPS**; K_TIC 19.03; 11.92 loads a tic | −8.1 ms |
| | fastpath | 84.7 ms, 11.81 FPS | **78.6 ms, 12.72 FPS** | −6.1 ms |
| demo3, gametics 1052-1796, 186 frames | f121 | 272.1 ms (median 271.8, max 634.5), 3.67 FPS; K_TIC 188.90; 63.5 loads a tic | **247.2 ms (median 245.8, max 646.5), 4.04 FPS**; K_TIC 168.39; 62.8 loads a tic | −24.9 ms |
| | fastpath | 244.6 ms, 4.09 FPS | **226.9 ms, 4.41 FPS** | −17.7 ms |
| The menu's BENCHMARK, all of demo3 (534 frames) | f121 | FPS **3.294** (5,673 realtics, 304.1 ms a frame) | FPS **3.631** (5,146 realtics, 275.8 ms) | −28.3 ms |
| | fastpath | FPS 3.717 (5,028 realtics) | FPS 4.026 (4,651 realtics; N 535) | −24.0 ms |

- **The benchmark's rows, a2vm f121:** before `TIC 225.2  3D 23.2  MASK 14.2  DRAW 35.7  REST 5.6`; after `TIC 201.1  3D 22.9  MASK 14.2  DRAW 31.9  REST 5.6`. On the card, with the factors of the card's rows above (TIC 1.155, 3D 1.125, MASK 1.155, DRAW 1.056, REST 1.11), that is about TIC 232, 3D 25.8, MASK 16.4, DRAW 33.7, REST 6.2: about 314 ms a frame, **about 3.18 FPS** against the card's 2.897. An estimate; the owner's card gives the figure.
- **By step, f121, ms a frame (before → after).** Still: K_TIC 24.78 → 19.03, K_WLOAD 4.95 → 4.70, nr_frame 25.94 → 24.39, nm_masked 3.89 → 3.80, nb_frame 22.18 → 21.84 (replays 17.52 → 17.14), s2_frame 1.82 → 1.76. demo3: K_TIC 188.90 → 168.39, K_WLOAD 4.96 → 4.71, nr_frame 21.92 → 21.83, nm_masked 7.70 → 7.55, nb_frame 40.28 → 36.47 (replays 35.25 → 31.41).
- **Against the parts' sums.** The parts measured alone −0.8, −3.4, −1.3, −0.4 (replay, derived) and −2.4 ms still (−8.3) and −13.4, −5.0, −1.65, −3.7, −0.4 in demo3 (−24.2), plus about −1.2 for ticloads' request 3: the integrated −8.1 and −24.9 are their sum. Against the plan's wave-2 estimate (about 85 ms still, 230-250 ms demo3): still better, demo3 at its slow end, because the object API (−13 against −20 to −35) and the last page (−3.6 against −10 to −16) gave less than estimated (each part's note says why).
- **demo3's cut** ends at gametic 1795 in the new build, 1796 before: the faster frames group the demo's tics differently from its load on (4 a frame throughout), so the frames' maximum is not like for like. The game's tics are the same (the lockstep run below).
- **Render alone** (`frame8.py --timing`, f121, the integrated renderer): still-1 59.36 → 58.91 ms, still-2 59.31 → 58.48, demo3-036 (heaviest) 151.14 → 136.75, demo3-114 136.96 → 110.49.
- **Commands:** `python3 tools/native/playtime.py --scene still|demo3|bench --profile f121|fastpath` (the before disk measured from a scratch clone of HEAD with its own tools: `playtime.py` checks a disk against its tree's links).

**Integration of wave 2** (2026-10-03). What the integrator changed beyond the parts' own files, and why:

- The parts' requests, each checked: `play.mk`'s `TICFLAGS` gets `-D PLAY_TIC` (glue 1); the kernel's `k_wload` calls `XS_far_wloadt` and `playlink.py`'s `RCARD_SYMS` names it (frontend 1; `$6000-$64FF` hold MATHW at every K_WLOAD: K_WLOAD follows K_TIC in the same list, and `playdisk.shared_w_problems` asserts the bytes); `test_native_replay`'s fill check reads `$DBF9` instead of `$DBD1`, which now holds `p1_image` (replay 8: the same check on the slack's first free byte); `bucket.cfg`'s header (replay 2); gplace.py's `MAXGRP` comment (ticloads 2); `testpar.py` and `tests/README.md`: `test_ticloads` reads `build/native/play` and the render objects, `test_play_glue` the play links, `test_objapi` the skeleton's gen (ticloads 1, objapi 4); the docs each part named (`MEMORY_MAP.md` 2, 4, 13, 17; `GAME.md` 1.3, 3.4, 4.5; `RENDER-MASKED.md` 6.2; `src/native/README.md`; `PLAY.md` 1, 3, 4, 5, 8, 16).
- **Ticloads' optional request 3, taken:** one `far_gcopy` call a group. `gr_load` sets FA_N to the whole pages + 1 from the page before the group, low byte `grp_tail`, Y = 256 − `grp_tail`, so the copy's first page is the group's first `grp_tail` bytes; `gdriver.s`'s `far_gcopy` now starts at byte Y (its `gc_add`), as the kernel's already did. `grun.group_entry` still copies a group under a page whole (a `grp_pages` of 0 is `gr_load`'s "group not held" stop). The lockstep run covers the driver's copy and `gr_load`; the kernel's loop copies the same addresses.
- **The placement:** `gplace.py --write` from wave 1's (the core grew: objapi +37 B, +64 in the test builds; ticloads +15; the gprof build overflowed by 46 B). `gplace.py` measured the overflowing links' maps (ld65 writes the map of a link it refuses), repaired the start (`P_UpdateSpecials` out of the core) and searched: `P_UpdateSpecials` and `P_RemoveThinker` now share group 1, five small `p_map65.s` helpers (`baseFloor`, `baseFloorL`, `baseLite`, `pointSector`, `sectorFloor`) moved into the core, `checkMissile` joined `P_CheckPosition`'s group, and the other groups were renumbered. Model cost: demo3 21.339 → 21.390 ms a tic, still 3.169 → 3.296 (one load a tic more), as part objapi found. The core holds 3,151 of 3,153 B of table routines (fixed core code: play 9,980 B, game 10,133, gprof 10,143). A second search on the new links returns the same placement. Kept as `tools/native/gplace-wave2.json` (`gplace.py --placement tools/native/gplace-wave2.json --no-search --write` restores it).
- **Four checks the first suite run failed, each a harness that did not know a part's change, not a game difference** (the game's frames and state are the lockstep's and frame8's, above):
  1. The load's stray-write check (`lrun.stray`, used by `test_native_level_setup` and `test_native_game_skeleton`'s S1) named every write of the object API's page-1 window (`pc $0127`) a stray: `lrun.code_ranges` now counts `pw_go` .. `pw_code_end` (labels of the build) as the load's code. Its allowed places are unchanged.
  2. `test_native_level_load` and `test_native_level_setup` expected the phase loader `RLOAD` to end at `$DE8E`; part frontend's `far_wloadt` makes it `$DE97`.
  3. `test_native_render_frame`'s plant "the phase loader without the per-level tables" matched `far.s`'s list line, which `wl_tic` now repeats: the plant is anchored to `wl_front`'s list (the same edit, the same bug) and is still caught.
  4. `test_play_cardprof` found the benchmark's span in the PC log by `bt_start`'s and `bt_stop`'s addresses with `DLG_D` in slot 1; part frontend's longer front end now reaches `bt_stop`'s `$A400` while `SLOT_GRP` still names the tic phase's last group, so a front-end instruction was taken for `bt_stop`. The span now counts only visits in the tic phase (`K_TIC`): the machine's rows and the kernel steps agree again (TIC 2,972.3 / 2,972.7 ms).
  And one real defect of the integration, in the test driver: ticloads' request 3 made `gdriver.s` 40 B longer, and in part xymove's image `dg_planes` landed at `$EAFF`, across a page; `far_pload` steps a list's low byte only, so the planes' copy read a wrong count and ran into the soft switches (`test_native_game_xymove`: "halt at $A5A7"). The driver's three page lists now come first in its descriptor, with a link-time assert that none crosses a page.
- **Glue's figure in PLAY.md 4** is the integrated one: the play core `$6600-$993D`, 13,118 of 13,312 B; `DLG_H` 1,775 B; the kernel 248 of 250 B.

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

1. **The placement.** `python3 tools/native/gplace.py --write` starts from the current `placement.json` (code sizes change with every wave; when the builds no longer link, `make -k ... game gprof` first: the search reads the overflowing links' maps, whose labels must be of the same placement); give `--placement FILE` to start from a part's file, `--no-search` to take it as it is (wave 1: `--placement tools/native/gplace-wave1-lazy.json --no-search --write`). A part that changes which routines call which needs `python3 tools/native/gplacerec.py still walk fight demo3 demo3b lock3a lock3b --jobs 2` first (about 8 minutes).
2. **Build**, with no warnings: `make -s -C src/native -f game.mk shared game gprof release skel ROOT=$PWD`; the load image `make -s -C src/native -f level.mk ROOT=$PWD` (LCODE links the runtime's state; since 2026-10-02 `play.mk`, and so `playdisk.py`, runs this make first, so the disk can no longer take a stale one; `playdisk.py --no-build` still skips it); the renderer `make -s -C src/native -f render.mk ROOT=$PWD` and milestone 11's images `make -s -C src/native -f m11.mk images ROOT=$PWD` (OVLW carries its own copy of the bucket pass and `mrec_room`: rebuild it with the renderer; `s2ovl.image_problems()` must be `[]`); then `python3 tools/native/playdisk.py` (`play.mk`'s tic stamp now follows `placement.json`).
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

## 9. The frame slots (2026-10-03)

**Why.** A hot-set analysis (2026-10-03, the workflow `doom-gs-frame-slots`) found the tic phase's code paging about 138 ms of the card's 332 ms benchmark frame, and its cause: the core's 13,312 B are mostly fixed code (the play build's 9,980 B, the profiling build's 10,143), so 3.1 KB are left for the 51 KB of placeable routines, W cannot grow, and every other fast byte is taken. Main `$2000-$5FFF`, colormaps A and B of light levels 0-31, is read by the replay alone. It became 64 pages of code room for the tic phase: the **frame slots**.

**What was built.**

1. **The region and its slots** (`glayout.py`: `FRAME_REGION`, `frame_slots`, `FS_MAX` 16; `gen/gplace.inc`: `FSLOTS` and each slot's `FSLOTn_PAGE`, `FSLOTn_SRC`, `FSLOTn_GRP`). A group of the placement in slot 3 or up is pinned: one group a frame slot, its bytes and 96 B rounded up to pages, packed largest first into `$2000-$3FFF` and `$4000-$5FFF` (none across `$4000`, so that each slot restores from one of `LVC`'s two colormaps), 64 pages at most. `game.cfg` links the group to run there; `playdisk.py` and `grun.py` store it in `GCODE0-1` with the others.
2. **The load** (`gcall.s` `gr_load` → `fs_load`, `fs_copy`, `fs_send`): a frame slot's group comes by one memory-API COPY with PRIVATE (a CPU store there would be a video write: `MEMORY_MAP.md` rule 3), its length (at most 2,048 B) from its bank to main, the 36-byte request streamed through slot 7's FIFO from a 23-byte head in the core and the far layer's zero page, interrupts masked for that request only. A refused request stops (`GS_AMEM`, the result in `GS_ARG`). `SLOT_GRP`, `SLOT_NEED` and FCALL treat the slot as any other: the group stays until `K_TIC`, so a frame loads it at its first call.
3. **The restore** (`gcall.s` `fs_restore`): every frame slot that holds a group gets its colormap bytes back from the level's copy in `LVC` (`LVC_CMAPA` `$0200`, `LVC_CMAPB` `$2400`: what `lg_cmaps` made and the load's PRIVATE request put in main), one request a slot (at most 2,048 B, interrupts masked for one), then the slot empty and `FS_DIRTY` set (`FS_DIRTY` bit 7 clear means a frame slot was loaded). In the play build it is the brain's last step (`dl_brain.s`, before `bt_close`): every way from the tic phase to a replay passes there, the frame's, a load's, the menu's, the intermission's, the benchmark's, as the kernel runs a list only after the brain returns and no list calls into the tic image. The test drivers restore before a frame and before a load (`gdriver.s`).
4. **The state**: `SLOT_GRP` 19 B (slots 0-2 and 16 frame slots), `SLOT_NEED` 18 B, `FS_DIRTY`: the runtime's state 163 of 256 B. The kernel's `K_TIC` and the drivers' `core_in` set the `SLOT_CLR` = 38 bytes to `$FF` (the renderer overwrites the runtime's state each frame).
5. **The core's room**: `gspec.s` (618 B, the load's SPECIALS step: no tic image calls it; the load image keeps it) left every tic image, and part flow's `g_resume` (163 B, run once a load) left the core: the play build's brain group `DLG_B` (1,263 of 2,048 B), the test builds' driver area in the card. The transport and the restore took about 260 B. Fixed core code: play 9,980 → 9,429 B, gprof 10,143 → 9,592.
6. **The placement** (`gplace.py`, `tools/gplace/gsim.c`, `gplacesim.py`): the cost is the W slots' pages × 80 µs (the card's `far_gcopy`), the frame slots' PRIVATE pages in and back × 85 µs and 10 µs a request (a2vm's model of the memory API, `--fpage-us`, `--request-us`), and 5 µs a call through `fc_call`. `gsim` replays a frame slot as a slot of its own, loaded at its first call in a phase and restored at the phase's end; the search moves groups into frame slots as into W slots. New rules: the frame slots fit (`glayout.frame_slots`), the core's 2 B a frame slot, and no frame slot for a routine the tic code stores into (the play link's debug file, `playdisk.dbg_stores`: every source line that is a store instruction, so a table's bytes are not taken for code; and `NO_PIN`'s `recursiveSound`, whose work stack is written through a pointer). `GROUP_MARGIN` rose from 64 to 96 B: the search packed `P_DamageMobj`'s group to 1,973 B, and part damage's plant `thrust-divided-first` adds 83 B there. `gplacesim.py --check` stays exact on the old recordings (2 slots) and on new ones of this build (`gtrace.c` and `gplacerec.py` map the frame slots: still 1,468 loads, lock3b 861, recorded and modelled alike). The integrated placement is `tools/native/gplace-frameslots.json`: 43 groups, 12 of them in frame slots (64 pages), among them P_RunThinkers with P_SetMobjState and G_Ticker, the position check with lineBlocks, A_Chase with pMove, A_Look, the line opening and the puffs. The model (ms a tic, its scenes): demo3 26.71 → 6.19, demo3b 29.27 → 6.62, still 4.11 → 2.89, walk 8.98 → 4.35, fight 10.47 → 4.94, lock3a 43.89 → 4.70, lock3b 48.70 → 6.33.
7. **The harness.** a2vm's `--stop-pc` names an address, and DOOM.SYSTEM's `bt_halt` (`$267D`) lies in the frame slots, where pinned code now runs: `playdisk.run` and `gplacerec.py` no longer stop there, and `playdisk.boot_halted` names a boot that stopped (the PC at `bt_halt`, interrupts masked, its `bra` in the final snapshot) after the run. `playdisk.py` checks the tic link's absolute stores (`frame_slot_problems`: none into `$2000-$5FFF`) and that each pinned group stays in its slot. `playtime.py` reports the PRIVATE requests, pages and time a frame (`fs_load`, `fs_send` with A the pages, to `fs_sent`, counted in `K_TIC` only).

**Measured** (a2vm f121 card-equivalent, the model corrected by the card, both columns on the same a2vm binary and cost profile, copied at the work's start while `tools/a2vm` changed; `playtime.py`):

| Scene | Before (wave 2, `f92c81ae`) | After the frame slots | Change |
| --- | ---: | ---: | ---: |
| E1M1 start, standing still, 15-25 s | 96.2 ms (median 93.9, max 118.2), 10.40 FPS; K_TIC 26.99; 11.69 loads a tic | **90.8 ms** (median 89.7, max 108.8), **11.02 FPS**; K_TIC 21.62; 4.21 loads a tic | −5.4 ms |
| demo3, gametics 1052-1796, 186 frames | 297.0 ms (median 297.3, max 736.8), 3.37 FPS; K_TIC 210.30; 62.75 loads a tic | **203.7 ms** (median 205.8, max 370.0), **4.91 FPS**; K_TIC 117.04; 10.64 loads a tic | −93.3 ms |
| The menu's BENCHMARK, all of demo3 (534 frames) | **3.004 FPS** (6,221 realtics, 333.5 ms a frame); `TIC 251.7  3D 25.8  MASK 16.3  DRAW 33.2  REST 6.2` | **4.641 FPS** (4,027 realtics, 215.7 ms a frame); `TIC 134.0  3D 25.8  MASK 16.3  DRAW 33.4  REST 6.2` | −117.8 ms |

The PRIVATE copies, as a2vm models them (83.3 µs a page: 0.33 µs a byte, the memory API's DMA read of RamWorks and its shadow write of main, plus a few µs a request):

| Scene | Requests a frame (loads + restores) | Pages a frame | ms a frame |
| --- | ---: | ---: | ---: |
| standing still | 4.00 (2.00 + 2.00) | 30.0 | 2.50 |
| demo3 1052-1796 | 15.10 (7.55 + 7.55) | 89.3 | 7.43 |
| the benchmark | 15.08 (7.54 + 7.54) | 89.3 | 7.44 |

(The loads a tic above count `gr_load`'s calls, the frame slots' among them: the benchmark's W slots load 10.4 groups a tic, against 77.7 before.)

On the card: the corrected model reproduced the card's wave-2 benchmark within 0.4% (section 5), so the card as it was set (F1.2.1, Disk II on) would read about 4.6 FPS. The card now runs F1.2.2 with the Disk II's acceleration off, and there `CALIB.hdv`'s page 2 measured a PRIVATE request at about 46 µs plus 0.038 µs a byte (`docs/results/calib.md`, "The card on F1.2.2"): a fifth of what f121 models. On `f122-nod2` (the same disk, `2b0fa3a6`, `playtime.py --scene bench --profile f122-nod2`):

| | Wave 2, card F1.2.2 | Frame slots, `f122-nod2` | Frame slots, card F1.2.2 (2026-10-03) |
| --- | ---: | ---: | ---: |
| FPS | 3.830 | **5.677** (539 frames, 3,323 realtics) | **5.648** |
| TIC | 189.4 | 104.5 | 105.4 |
| 3D | 21.9 | 21.8 | 21.8 |
| MASK | 13.8 | 13.8 | 13.7 |
| DRAW | 31.4 | 31.4 | 31.4 |
| REST | 4.9 | 4.9 | 4.9 |
| N | 535 | 539 | 539 |

The card (the owner, PAL, Disk II acceleration off, this disk `2b0fa3a6`) is within 0.5% of the model's FPS and 0.9 ms of its TIC: +47% over wave 2.

The PRIVATE copies there: 15.04 requests a frame (7.52 loads, 7.52 restores), 89.1 pages, **1.46 ms** a frame (97 µs a request); `gr_load` 12.32 calls a tic. The memory API holds the CPU for a request and invalidates its caches (appletini-one `README_TURBO.md`, "F1.2.2 extended-memory transfers"), so no stale byte of `$2000-$5FFF` survives a load or a restore.

**Checks** (the owner's rule: what changed, once each):

- the game code, the placement and the paging: `python3 tools/native/ticrun.py --run demo3 --frames front --fills a5 --jobs 2` on the final placement: 2,134 tics compared, 0 failures, the same-pair hits equal (1,009);
- the restore: `python3 -m unittest test_play_bench` (the BENCHMARK played from the menu): its run now takes a snapshot at every entry of the replay (`nat_replay`, a2vm's `pc …@*` event) and requires main `$2000-$5FFF` equal to `LVC`'s colormaps at each: 43 replays, all equal. A planted bug, the restore skipped once (`fs_restore` returning at the timed demo's gametic 60-63, built in a scratch copy of `play.mk`), is caught: 1 of 43 replays wrong (5 of 42 on an earlier placement);
- `playdisk.py`'s link checks (no absolute store into `$2000-$5FFF`, each pinned group in its slot) on every disk build;
- then the fast full suite once (`python3 tools/testpar.py --jobs 4`, 131 modules, 829 s): 130 passed; `test_gplace_model` failed on `gsim`'s new answer (9 figures a scene, not 5) and on its fake builds, which have no frame slots. Its twin of `gsim` now models the frame slots (half its random placements use them), and new cases check the frame slots' rules, room and `gtrace`'s frame-slot loads; the module passes.

The disk: `build/native/DOOM.hdv`, 4,029,952 bytes, SHA-1 `2b0fa3a6df5526364f7d27a9d039852e84bb8a26`.

**Commands:** `python3 tools/native/gplace.py --placement tools/native/gplace-frameslots.json --no-search --write` restores the placement; `python3 tools/native/gplace.py` searches again (about a minute; `--no-frame-slots` keeps every group in W); `python3 tools/native/glayout.py --report` lists the frame slots; `python3 tools/native/playtime.py --scene still|demo3|bench`.

**Open problems.**

- The placement still prices a W page at 80 µs and a PRIVATE page at 85 µs, the F1.2.1 figures; on F1.2.2 a CPU page copy is about 60 µs and a PRIVATE request about 46 µs plus 9.7 µs a page. The W slots' loads could also go by PRIVATE request (2 KB in about 125 µs against 480 by the CPU). Both are the next step. *Done in section 10.*
- The frame slots are full (64 of 64 pages, 12 slots of 16): more pinned code needs smaller groups or more room.
- Every loaded slot is restored whole, so half of the PRIVATE pages are restores (about 45 of the benchmark's 89 a frame); a group pays its pages twice a frame, and pinning pays only for a group that a frame would otherwise load about twice or more.
- Indirect stores are not checked statically: a routine that writes its own bytes through a pointer (as `recursiveSound` does) must be named in `gplace.NO_PIN`; the benchmark run's colormap check catches one that the demo reaches.
- `GROUP_MARGIN` 96 costs the model about 0.1 ms a tic in demo3 (6.07 → 6.19).

## 10. The frame's bulk copies by the copy engine (2026-10-03)

**Why.** On F1.2.2 the memory API's copies run on the FPGA's copy engine: `CALIB.hdv`'s page 2 measured a PRIVATE request at about 46 µs plus 0.038 µs a byte, where the CPU's copy from RamWorks into main (`far_gcopy`, `far_pload`) costs about 7.8 µs plus 0.231 µs a byte (`docs/results/calib.md`, "The card on F1.2.2"). A request wins above about 220 B, and every bulk copy of a frame is far above that.

**The inventory** (the frame slots' disk `2b0fa3a6`, rebuilt byte for byte from HEAD `7e949ff6` in a scratch clone; the benchmark, a2vm `f122-nod2`, 538 frames; each copy timed from its entry to its window's end by a PC log, `playtime.py`'s steps for the rest). PRIVATE: whether a request may write the destination (never a page the screen shows, never the card or `$C000-$CFFF`):

| Copy | Source → destination | Bytes | Calls a frame | ms a frame before | PRIVATE | Now |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `gr_load` into a W slot (the kernel's `far_gcopy`) | `GCODE0-1` (banks 72-73) → main `$9E00-$A5FF`, `$A600-$ADFF` | a group's length, 147-1,921 (1,369 on average) | 41.34 (10.4 a tic) | **13.40** (324 µs a call) | yes: W is never shown | a request (`am_one`): 38.39 a frame, **3.91 ms** (102 µs) |
| `gr_load` into a frame slot (already a request) | `GCODE0-1` → main `$2000-$5FFF` | a group's length | 7.52 | 0.77 | yes (section 9) | the same request (`am_one`): 6.95, 0.75 ms |
| `fs_restore` (already requests) | `LVC` → main `$2000-$5FFF` | each loaded group's length | 7.52 requests | 0.69 | yes | **one** request, a descriptor a slot: 1 (6.95 descriptors), 0.52 ms |
| `K_TIC`: the tic image's W and core (`far_pload`) | `GCODE0` → main `$6000`/`$6600-$99FF` | 52-58 pages | 1 | **3.12** | yes | a request (`am_runs`): **0.57 ms** |
| `K_TIC`: the walk's planes (`far_pload`) | `MOBJP` (bank 74) → main `$B400-$BFFF` | 4 runs of 1-3 pages | 1 | 0.49 | yes | a request, 4 descriptors: 0.15 ms |
| `planes_out` (the brain's `RAMWRT` window) | main `$B400-$BFFF` → `MOBJP` | 4 runs of 1-3 pages | 1 | 0.58 | a RamWorks destination (PRIVATE accepted) | a request, 4 descriptors: 0.14 ms |
| `K_WLOAD` (`far_wloadt`) | `WCODE` (112) → main `$6500-$A4FF`, `$AF00-$B8FF` | 74 pages, 18,944 | 1 | **4.43** | yes | the brain's `K_LOAD img_wload`, a request of 2 descriptors: **0.79 ms** |
| `K_MLOAD` (`far_mload`) | `MCODE` (113) → main `$6800-$8EFF`, `$B200-$B3FF` | 41 pages, 10,496 | 1 | **2.46** | yes | `K_LOAD img_mload`, 2 descriptors: **0.46 ms** |
| `K_LOAD P2DW` (`far_pload`) | bank 107 → main `$6000-$7EFF` | 31 pages, 7,936 | 1 | **1.86** | yes | a request: **0.36 ms** |
| Every other `K_LOAD` (`OVLW` 25 pages with the automap's overlay, `PALW` 10 at a level's first frame, the menu's, the intermission's, the finale's, the load's, `DLINIT`) | their banks → W | 2-52 pages | 0 in the benchmark | | yes | the same path: a request each |
| `nm_bkload` (the masked image, in W) | main `$8A73`, `$8D2E` → main `$0C00-$0EFF`, aux 0 `$0200-$02FF` | 4 pages (932 B used) | 1 | 0.21 | yes: neither is shown | **kept** (below) |
| The bucket pass's `park` and `back` (`BKNEAR`, the card) | W ↔ `RECW` | about 1.8 KB | 0.13 each | 0.11 both | yes | **kept** (below) |
| The replay's drain, `s2_frame`'s status bar and HUD | → aux 0 `$2000-$9FFF` | | | | **no**: shown (rule 4) | CPU |
| The replay's texel gather, the bucket pass's record chunks, the object API's `far_get`/`far_put` | RamWorks, aux 0 ↔ W | under 256 B a copy, or a reordering | many | | | CPU: under a request's break-even, or no run of bytes a descriptor can carry |

Before: 25.5 ms a frame of bulk copies by the CPU on the benchmark (13.40 + 3.12 + 0.49 + 0.58 + 4.43 + 2.46 + 1.86 + 0.21 + 0.11) and 1.46 ms of requests.

**Kept on the CPU, and why.** `nm_bkload` (0.21 ms) is code of the masked image, milestone 8's render build, which the renderer's own drivers (`frame8.py`, `mtest`) run without the memory API and whose card has no transport (`AMEMLC` is the tic image's); a request would save about 0.1 ms a frame. The bucket pass's `park`/`back` (0.11 ms in all, one frame in eight) is the renderer's card code (`BKNEAR`) in the same build. `far_gcopy` stays in the kernel at `KERN_GCOPY` for `CALIB.hdv`'s GC lines (`calibdisk.py` times the play build's own), but no game code calls it.

**What was built.**

1. **The transport in the card** (`gcall.s`, segment `AMEMLC`, main card bank 1 `$DB5C-$DBFF`, after `MATHLC`: 164 of 164 B; `glayout.AMEM_LC`, `game.cfg`). The kernel's loads replace W and the core, and the code that waits for a request's result must survive the request: so the card, which `fs_send` in the core could not be. `am_req` is the request's head (the SmartPort CONTROL, the list's head) and one descriptor, a template the callers patch (the source's bank and page, the destination's page, the count; COPY, PRIVATE, from AUX to MAIN); `am_begin` (A descriptors, 1-15) streams the head through slot 7's FIFO, `am_push` a descriptor, `am_fin` executes, waits (64 K polls at most: `FS_TIMEOUT`), releases C8 and stops on a refusal (`GS_AMEM`, `GS_ARG` the result, BRK: as `fs_send` did), then `plp`: interrupts are masked from the caller's `php`, `sei` to the request's end, one request at a time. `am_runs` (the kernel's) turns a list of page runs (`far_pload`'s format) into one request, a descriptor a run. The play disk's card takes `AMEMLC` from the tic image (`playdisk.card_main`, `pldisk.area_problems` compares it), the test images from their own (`lrun.card_records`): the lockstep and test builds run with the memory API (`grun.py` passes `--amem`), so they need no fallback.
2. **The core** keeps a request's build: `am_one` (a group's length from its directory entry, from its bank's page to a slot's page) for `gr_load`, into a W slot as into a frame slot, and `fs_restore`, now one request for every loaded frame slot (at most 15 descriptors: `glayout.AM_MAX`, which `frame_slots` enforces). `fs_send`, `fs_head`, `fs_load`, `fs_copy` and `gr_load`'s `far_gcopy` set-up left it, and `fc_ret` no longer keeps `FC_PS` around a load (only the test driver's `far_gcopy` changed it): the fixed core code is **111 B smaller** (play 9,429 → 9,318 B, game 9,582 → 9,471, gprof 9,592 → 9,481), which the placement gave to routines. `gdriver.s`'s `far_gcopy` (the test builds' page-at-a-time copy) and `game.cfg`'s weak `far_gcopy` are gone.
3. **The kernel** (`dl_kern.s`): `K_TIC`'s two lists and every `K_LOAD` go through `am_runs`; `K_WLOAD` and `K_MLOAD` are gone (16 B: a stop if a list ever names them), the brain writes `K_LOAD img_wload` and `K_LOAD img_mload` instead (`playlink.py` takes their runs from rcard's own `wl_tic` and `wl_mask`, so they copy exactly `far_wloadt`'s and `far_mload`'s pages). `playtime.py` still names those steps `K_WLOAD` and `K_MLOAD` (by the bank).
4. **The brain** (`dl_disp.s`, `DLG_D` 1,937 → 1,967 B): `planes_out` sends the four planes back to `MOBJP` by one request, the template's spaces turned round (from MAIN to AUX) and put back.
5. **`playtime.py`** reports every request by kind (W slot, frame slot, restore, planes out, `K_TIC` core and planes, `K_LOAD`): requests, descriptors, pages and ms a frame, each timed from its caller to its return (the transport's own PCs are in bank 1, where bank 2's texture rows run during the replay, so they are not logged).

**The placement priced for F1.2.2** (`gplacesim.amem_prices`, from a2vm's profile `f122+nod2`, `tools/a2vm/costs/appletini.json`): a byte 0.03844 µs (the copy engine's aligned 8-byte line from a PSRAM bank to the shadow: two 4-byte steps of five states, the line's read `copy_read_wait` 30 clocks and SOURCE again, 41 clocks at `fabric_mhz` 133.33; a2vm's own CALIB lines PR2 256 and PR2 2K, 56.123 and 125.046 µs on `f122+nod2`, give 0.03846), so 9.84 µs a page; a request 46.3 µs (PR2 256 less its bytes: the PS's `ps_dispatch_us` 25.9 and AXI accesses, the CPU's FIFO, the hold, the caches refilled); each further descriptor 3.5 µs (`hw_transfer`'s `amem_copy_setup_axi` 12, `amem_copy_poll_axi` 5, `amem_copy_end_axi` 1 and the request's 4 words at `axi_us` 0.135, `amem_copy_start_axi` 4 at `axi_write_us`). `gsim.c` now counts the restores' requests (one a phase that loaded a frame slot, a tenth figure); `gplacesim.cost_of` charges a W slot's load `--load-us` and its pages `--page-us`, a frame slot's load `--request-us` and its pages `--fpage-us`, a phase's restores one request and `--desc-us` each further one; `gplace.py` passes the five prices through (`--page-us 80 --load-us 0 --fpage-us 85 --request-us 10 --desc-us 10` was the model of section 9). `gplacesim.py --check` stays exact on the recordings (demo3 63,142 loads, demo3b 75,458, fight 17,642, lock3a 49,610, lock3b 22,400, still 11,068, walk 13,042) and on two new ones of this build (scratch: still 1,458, lock3b 753); `test_gplace_model`'s twin of gsim counts the restores' requests too.

The search with these prices (`python3 tools/native/gplace.py`, about 45 s) keeps the frame slots: without them (`--no-frame-slots` from the same groups in W) demo3's model cost is 10.9 ms a tic against 1.5. The placement: **`tools/native/gplace-f122.json`**, 42 groups, 11 in frame slots (64 of 64 pages), the core 3,776 of 3,793 B of table routines. The model (ms a tic, the frame slots' placement → this one): still 0.643 → 0.643, walk 0.981 → 0.984, demo3 1.579 → 1.514, lock3a 1.411 → 1.341; held out fight 1.148 → 1.097, demo3b 1.713 → 1.656, lock3b 1.835 → 1.754 (the frame slots' placement under section 9's prices: demo3 6.19). On the benchmark the re-placement gave 6.494 → 6.519 FPS (the requests on the frame slots' placement, then on this one): the requests had taken most of what placement could.

**Measured** (a2vm `f122-nod2`, the card's setting, both columns on the same a2vm binary, SHA-1 `89e448fc`; before: HEAD's disk `2b0fa3a6`; after: `fd3ce9fd`; `playtime.py --scene bench|still|demo3 --profile f122-nod2`):

| Scene | Before | After | Change |
| --- | ---: | ---: | ---: |
| The menu's BENCHMARK, all of demo3 | **5.677 FPS** (539 frames, 3,323 realtics; 176.4 ms a frame) | **6.519 FPS** (551 frames, 2,958 realtics; 153.6 ms) | −22.8 ms, +14.8% |
| E1M1 start, standing still, 15-25 s | 72.7 ms (median 72.9, max 98.2), 13.75 FPS | **58.9 ms** (median 58.2, max 78.0), **16.97 FPS** | −13.8 ms |
| demo3, gametics 1052-1796 | 166.5 ms (median 168.0, max 301.6), 6.01 FPS | **143.7 ms** (median 149.4, max 259.4), **6.96 FPS** | −22.8 ms |

The benchmark's rows (the page, ms a frame): before `TIC 104.5  3D 21.8  MASK 13.8  DRAW 31.4  REST 4.9`; after **`TIC 89.4  3D 18.0  MASK 11.6  DRAW 31.3  REST 3.3`**. By step: `K_TIC` 104.60 → 89.47, `K_WLOAD` 4.43 → 0.79, `K_MLOAD` 2.46 → 0.46, `K_LOAD P2DW` 1.86 → 0.36; `nr_frame`, `nm_masked`, `nm_bkload`, `nb_frame`, `s2_frame` unchanged (17.38 → 17.15, 6.77 → 6.71, 0.21, 35.71 → 35.52, 2.88 → 2.82). `gr_load` calls a tic: 12.32 → 11.7 (benchmark), 4.76 → 5.39 (still), 10.67 → 9.98 (demo3).

The requests a frame, after (requests, descriptors, pages, ms):

| Kind | Benchmark | Still | demo3 |
| --- | --- | --- | --- |
| W slot | 38.39, 38.39, 212.6, 3.91 | 9.13, 9.13, 56.8, 0.99 | 30.75, 30.75, 171.3, 3.14 |
| frame slot | 6.95, 6.95, 42.7, 0.75 | 2.00, 2.00, 14.2, 0.23 | 7.03, 7.03, 42.8, 0.77 |
| restore | 1, 6.95, 42.7, 0.52 | 1, 2.00, 14.2, 0.20 | 1, 7.03, 42.8, 0.52 |
| planes out | 1, 4, 8.0, 0.14 | 1, 4, 4.0, 0.11 | 1, 4, 8.0, 0.14 |
| `K_TIC` core | 1, 1, 52.0, 0.57 | 1, 1, 52.0, 0.56 | 1, 1, 52.0, 0.57 |
| `K_TIC` planes | 1, 4, 8.0, 0.15 | 1, 4, 4.0, 0.11 | 1, 4, 8.0, 0.15 |
| `K_LOAD` (front end, masked image, P2DW) | 3, 5, 146.0, 1.61 | 3, 5, 146.0, 1.60 | 3, 5, 146.0, 1.61 |
| **All** | **52.34, 66.30, 512.1, 7.65** | 18.13, 27.13, 291.1, 3.80 | 44.78, 58.80, 471.0, 6.90 |

Before: 15.04 requests a frame (the frame slots' 7.52 loads and 7.52 restores), 89.1 pages, 1.46 ms on the benchmark; 4.00, 30.0, 0.45 standing still; 14.99, 88.7, 1.46 in demo3. A W slot's request costs 102 µs (5.5 pages on average) where `far_gcopy` took 324. Bulk copies by the CPU a frame on the benchmark: 25.5 ms before, 0.32 after (`nm_bkload`, `park`/`back`); requests 1.46 ms before, 7.65 after.

**Interrupts.** Each request masks them from its build to its end, one request at a time; the longest are `K_WLOAD`'s (18.9 KB, 0.79 ms) and the restores' (up to 64 pages, about 0.7 ms), far under a VBL's 20 ms: an interrupt waits, none is lost (VBL interrupts a frame 8.8 → 7.7 on the benchmark: the frame is shorter).

**On the card.** a2vm's `f122-nod2` gave wave 2's benchmark within 0.001 FPS of the card (3.829 against 3.830) and the frame slots' within 0.03 (5.677 against 5.648): the card should show about **6.5 FPS**, `TIC` about 89, `3D` 18, `MASK` 11.6, `REST` 3.3. The requests' cost on the card is CALIB's (46 µs plus 0.038 µs a byte, page 2's lines within 4-9 µs a request).

**The card's run** (the owner, 2026-10-03, F1.2.2, PAL, Disk II acceleration off, this disk `fd3ce9fd`; level loads and intermissions played without a problem): FPS **6.343**, `TIC 93.1  3D 18.1  MASK 11.7  DRAW 31.3  REST 3.5`, N 547. Against the model's 6.519 (`TIC 89.4  3D 18.0  MASK 11.6  DRAW 31.3  REST 3.3`, N 551) that is −2.7%, nearly all in TIC (+3.7 ms). Up from the frame slots' 5.648 on the card: +12.3%.

The model's error grew with the requests: +0.90 ms a frame on the frame slots' disk (15.04 requests, 22.8 KB a frame) and +4.26 ms on this one (52.34 requests, 131.1 KB). Two disks give two unknowns: about **+27 µs a request and +0.022 µs a byte** beyond `f122`'s 46 µs and 0.038 µs. That is a fit through two points, not a measurement. Both terms are plausible. In the game a request arrives while the ARM is busy with other work (its compositor slices, USB); `CALIB.hdv`'s requests come back to back, with the ARM waiting for them. `CALIB.hdv`'s 16 KB lines also ran slower than the model (PR2 0.048, PR6 0.069 µs a byte against 0.041). A page of `CALIB.hdv` lines with requests spaced by CPU work, at the game's sizes (1.4 KB, 8-19 KB) and with large n, would separate the two terms.

**Checks** (the owner's rule: what changed, once each):

- the game code, the placement and the paging (`gr_load`'s request, the restore's one request): `python3 tools/native/ticrun.py --run demo3 --frames front --fills a5 --jobs 2` on the final placement: 2,134 tics compared, 0 failures, the same-pair hits equal (1,009);
- the kernel's loads and the restores: `python3 -m unittest test_play_bench` (the BENCHMARK played from the menu): the colormaps right at all 43 replays, and a new check, a snapshot at every `K_CALL` of the kernel: at each call of `nr_frame`, `nm_masked` and `s2_frame` W must hold the image the list loaded just before (`img_wload`, `img_mload`, `img_p2dw`) on each of its runs byte for byte as its bank does: 129 loads, all right;
- two planted bugs, in a scratch copy each time: the front end's load a page short (`img_wload` 63 pages from `$65`) is caught by `test_play_bench` (the run shows no replay at all: 0 of more than 20); a group's load without its tail bytes (`am_one`'s count low byte 0) is caught by the lockstep run (a crash at the first tic, 2,134 failures);
- the renderer's frame check (`frame8.py`) was not run: no renderer image changed (render.mk was not rebuilt, rcard is byte for byte as before) and its drivers load W with their own `far_wload`/`far_mload`, so it cannot see the kernel's requests; `test_play_bench`'s image check is the check of those loads;
- `playdisk.py`'s link checks on every disk build (the tic image's `AMEMLC` against the card's, the frame slots);
- then the fast full suite (`python3 tools/testpar.py --jobs 5`). Its first run failed 18 modules, each a harness that did not know the change, not a game difference: the parts' stray-write checks (16 `test_native_game_*` modules) named `am_one`'s patches of the request's template in the card (`lc1 $DBF3`...) strays: `am_req` now sits first in `AMEMLC` at `glayout.AM_REQ` (`$DB5C-$DB7F`, asserted in `gcall.s`) and the parts' write logs leave those 36 bytes out (`glayout.LC1_LOG` in `mobjstate.LOG_RANGES` and `flowcheck.WRITE_RANGES`), the rest of bank 1 still logged; `gselftest.py`'s three `fc_ret` plants named the `FC_PS` save that left `fc_ret` (the same bugs planted on the new text; `fcall-flags-lost` is now a load that writes `FC_PS`, as the test driver's `far_gcopy` did); `calibdisk.py` compared `far_gcopy` with the tic image's label, which `game.cfg` no longer defines; `test_play_cardprof` named the steps by `far_pload`'s bank (now `k_lrun`'s). The final disk (`am_req` moved) was measured and the lockstep run made again on it (2,134 tics, 0 failures, same-pair hits 1,009); the second suite run: 131 modules, 2,116 tests, 0 failures, 0 errors, 27 skipped (737 s at 5 jobs). The planted bugs were run on the build before `am_req` moved (the same code).

**The disk:** `build/native/DOOM.hdv`, 4,029,952 bytes, SHA-1 `fd3ce9fd7e44c4e642dcd76101870609d2f01382`.

**Commands:** `python3 tools/native/gplace.py --placement tools/native/gplace-f122.json --no-search --write` restores the placement; `python3 tools/native/gplacesim.py --eval FILE` prices a placement (the five `--*-us` options); `python3 tools/native/playtime.py --scene bench|still|demo3 --profile f122-nod2` gives the requests by kind.

**Open problems.**

- `K_TIC` makes two requests (the core from `GCODE0`, the planes from `MOBJP`): one request with both banks' runs would save about 46 µs a frame; `am_runs` takes one bank a list and the card has no byte left (`AMEMLC` 164 of 164 B).
- `nm_bkload` (0.21 ms) and the bucket pass's `park`/`back` (0.11 ms) stay CPU copies: they are the renderer's build's code; converting them needs the transport at a fixed place the render images can import and a CPU fallback for the renderer's drivers, for about 0.2 ms a frame.
- The group directory still rounds a tail to an even count and copies a tail over 224 B as a whole page (`grun.group_entry`, `far_gcopy`'s two bytes a turn): with a request that is at most 10 µs a load.
- The placement's training scenes are still the recordings of the two-slot builds (call traffic does not depend on the placement; the model is exact on them and on this build's new still and lock3b); its `still` scene predicts no change while the measured still frame makes 5.39 loads a tic against 4.76.
- `far_gcopy` (35 B of the kernel) is dead code kept for `CALIB.hdv`.
