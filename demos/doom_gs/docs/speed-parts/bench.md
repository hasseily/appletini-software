# Speed plan, wave 1, part `bench`: the menu benchmark

Written 2026-10-02 for the integrator (SPEED.md section 7). This part covers the owner's first finding: "When I select Options in the menu and select Benchmark nothing really happens."

## What it does

OPTIONS, BENCHMARK (`REQ_BENCH`) now runs the benchmark the way upstream's `m_menu65.s` does (bmStart, bmStop, bmDone). The code was written from the call sites and the documented behaviour; no upstream file was copied.

- **Start (`dl_brain.s` `b_bench`, from `b_menu`).** The menu has already closed itself (`s2_menu.s` `r_vwitem`). The brain then:
  - sets `G_TIMINGDEMO` = 1 and `DL_BENCH` = 1;
  - records `DL_VIEWS`, the level views `dl_disp.s` counts, in `DL_BVIEW`;
  - starts demo3 with `G_DeferedPlayDemo`, using `dl_snd.s`'s reference to the name. demo3 plays at the normal tic rate.

  `starttime` comes from doPlayDemo's `I_GetTime` after the load, as upstream's timedemo path does.
- **Frames.** A frame is one level view drawn: `DL_VIEWS` − `DL_BVIEW`, one for each level frame list that draws a view. This is what upstream counts in vwFrame.
- **End (`G_CheckDemoStatus`'s timingdemo branch, `gflow.s`).** The branch still computes realtics (`FL_U`, exported as `fl_realtics`) and its own gametic rate. Its last instruction used to be `jmp g_stop`; it is now `jmp G_TimeDemoEnd`, with A = `GS_DEMOEND`.
  - **Lockstep and test builds (`ghook.s`).** `G_TimeDemoEnd` is a label on `I_Error`'s `jmp g_stop`, so those builds stop exactly as before and their core is the same size.
  - **Play build (`dl_hook.s`).** The core entry is `ldy #HK_BENCH` / `bra hook`, 4 B in the core. The body, `hk_bench`, runs in group DLG_HOOK:
    1. It stores the frames in `DL_BVIEW` and the realtics in `DL_BRT`.
    2. It computes FPS = 35000 × frames / realtics, 32-bit. A realtics of 0 is taken as 1, and the result is capped at 999.999.
    3. It writes the FPS as `x.xxx`, 0-terminated, with `far_put` to `S2STATE` `SS_MENUW + M_BFPS − MENUW_STATE`.
    4. It clears `G_TIMINGDEMO`.
    5. It sets MENUW's message: `M_MSGPRINT` 1, `M_MSGKIND` `MSG_BENCH`, `M_MSGLAST` 0, `M_MENUVER` + 1. It sets `G_MENUACTIVE` to 1 and `DL_BENCH` to `$80`.
- **Showing the result (`dl_brain.s` `b_run`).** When `DL_BENCH` has bit 7 set, the brain clears it and writes `c_menulist` before the frame's other tics, so MENUW's `m2_bench` draws the BENCHMARK page.
  - Any key closes the page.
  - The demo pointer was not advanced, so the next tic reads the end marker again. `G_CheckDemoStatus`, now without timingdemo, ends the demo with `D_AdvanceDemo`, and the title loop continues.
- **ESC while it runs (`ev_route`, `b_bstop`).** This is bmStop:
  - `DL_BENCH` and `G_TIMINGDEMO` are set to 0 and nothing is shown;
  - `G_CheckDemoStatus` ends the demo;
  - then the main menu opens, as for any ESC.

## Files changed (this part's own)

- `src/native/dl_brain.s`: REQ_BENCH, `b_bench`, `b_bstop`, `b_bres`, the ESC stop, and the `b_run` check. `bra b_run` in `b_resume` became `jmp`, because of branch range.
- `src/native/dl_hook.s`: `G_TimeDemoEnd`, `HK_BENCH`, and `hk_bench` with its buffers `hb_txt` and `hb_msg`.
- `src/native/ghook.s`: the `G_TimeDemoEnd` label, which adds 0 B.
- `src/native/game/flow/gflow.s`: only the branch's `jmp`, the import and export, and comments.
- `src/native/dl.inc`: the DLM bytes below and `MSG_BENCH`.
- `tests/test_play_bench.py`: new.

Sizes in the play link (today's placement):

| Segment | Before | After |
| --- | ---: | ---: |
| LOADW (core) | `$20EB` | `$20EF` |
| DLGB | `$3BC` | `$419` |
| DLGH | `$EA` | `$21E` |

`dl_bwait` stays at `$A66C`. Lockstep and test images: the same sizes.

## Changes for the integrator (files this part does not own)

1. **`tools/native/playlayout.py` `DLM_FIELDS`.** Until then, `dl.inc` places the benchmark's three fields in the last 7 B of DLM (`DLM_END − 7` … `− 1`) under `.ifndef DL_BENCH`. Name them in `DLM_FIELDS` by appending after `('DL_VIEWS', 2)`:
   ```
       ('DL_BENCH', 1),            # the menu benchmark: 0 none, 1 runs, $80 its result to show
       ('DL_BVIEW', 2),            #   DL_VIEWS at its start; at its end the frames
       ('DL_BRT', 4),              #   at its end the realtics
   ```
   - `dl.inc`'s `.ifndef` block then takes play.inc's places with no other change.
   - The test reads play.inc's symbols first and the tic label file second. `dl_brain.s` exports the three names so they appear in `tic.lbl`.
   - DLM becomes 82 of 128 B, so update PLAY.md 3's "75 of 128 B".
2. **`src/native/s2_menu.s:553`, a comment only.** "(bmStop: no benchmark runs natively)" becomes "(bmStop: the brain's, dl_brain.s ev_route, before the menu opens)".
3. **docs/PLAY.md:**
   - Section 3, E_MENU: "(new game, end game, quit, save)" becomes "(new game, end game, quit, save, the benchmark)".
   - Section 12.2: add the line "**Benchmark**: OPTIONS, BENCHMARK plays demo3 at the normal tic rate and shows FPS = 35000 × frames drawn / realtics; ESC stops it with no result."
   - Section 10: add `python3 -m unittest test_play_bench` (from `tests/`).
4. **SPEED.md section 4, row "The benchmark itself":** built. Section 0 item 1: done. Each wave's on-card FPS figure is the result page's FPS (below).
5. **testpar:** `test_play_bench` makes the play links exactly as `test_play_runs` does (`playdisk.make()`, then its own disk in a `build/tmp-bench-test-*` directory). Give it whatever grouping `test_play_runs` has; today that is none.
6. **The core budget for part `place`:** the benchmark adds 4 B to the play core (`G_TimeDemoEnd`).

## The check (the owner's rule: only the benchmark)

- `python3 -m unittest test_play_bench -v` (from `tests/`): 2 tests, both pass, 33 s.
  - **The menu path.** ESC, DOWN, RETURN, DOWN ×3, RETURN starts demo3 on E1M7 with timingdemo set, and the run reaches the result page:
    - `M_MSGKIND` is 16;
    - `M_BFPS` equals the host's formula from the run's own frames (`DL_VIEWS` difference since the menu) and `DL_BRT`;
    - after a key, the page closes, timingdemo is 0 and the title loop's next step (`DL_DEMOSEQ` 1) runs.
  - **ESC.** It stops the benchmark (timingdemo 0, the demo ended, `DL_ADVDEMO` 1, main menu open, no message). ESC closes the menu, and no result appears 35 s later (`DL_BRT` 0).
  - The disk is DOOM.hdv's with demo3 cut after 120 tics, through a test-only `demob_segments` wrapper (the CRCs are the build's). a2vm's input events cannot poke memory, so this replaces moving the demo pointer.
- **Planted bug: FPS from gametics instead of frames** (hk_bench's multiplicand loaded from `G_GAMETIC`). It is caught: `'10.073' != '1.937'` for (30 frames, 542 realtics).
- **Lockstep, because gflow.s changed:** `python3 tools/native/ticrun.py --run demo3 --frames front --fills a5 --jobs 2`. Result `ok: true`: 2,134 tics compared, 0 failures, same-pair hits 1,009 = 1,009 (174 s).
- **A bug found by the full run and fixed:** an FPS below 1 lost its units digit (`.900`). The loop's test is now `cpx #HB_TXT - 5`. The full run below shows `0.900`, and both tests pass again.

## The benchmark on today's build (a2vm f121, HEAD's placement plus this part)

The whole of demo3 from the menu: 534 frames, 20,750 realtics, so the page shows **FPS 0.900**, a mean of 1,111 ms a frame.

- **How it was run.** `playdisk.run` on the unshortened disk with `test_play_bench.to_benchmark(7)` as the script, 728 s of model time, with a snapshot at the RETURN + 600 s. It took 288 s of wall time.
- **The figure is consistent:** 35000 × 534 / 20750 = 900.7, which truncates to 0.900.
- **It includes the a2vm idle artifact of SPEED.md 1.** `playdisk.run`'s `--idle dl_bwait:vbl` is still present, so on the card the figure should be a little higher.
- **How it compares with SPEED.md's 1.15 FPS.** That figure covers gametics 1052-1796 only. This one is the whole demo, including its load and the heavier late fights.

**On the card after each wave:** OPTIONS, BENCHMARK, wait about 10 minutes for demo3 to end, and read FPS.

All runs were made in an APFS clone of HEAD plus this part's files only, because other parts were editing the tree at the same time. The clone has been deleted.
