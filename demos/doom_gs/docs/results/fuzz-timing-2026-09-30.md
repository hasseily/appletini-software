# Fuzz frames on the card: the coalescer's page scan

Two documents from 2026-09-30: the investigation, then an independent adversarial check that confirmed it and corrected two points (section "Adversarial check" at the end). Their scratch files (Verilator benches, the a2vm patch, the deferred-fuzz variant and its disk) are in `build/fuzz-timing/` and the session scratchpad, which git ignores.

Date: 2026-09-30. Scope: milestone 5's native replay on the owner's card (F1.2.x, TURBO, PAL) against a2vm's f121 model.

How each claim is labelled:

- **[RTL]**: measured in a Verilator 5.050 simulation of appletini-one `be2ea4f` (F1.2.1).
- **[a2vm]**: measured on a2vm.
- **[card]**: the owner's run of `REPLAY.hdv`.
- **[read f:l]**: read in a source file at that line.
- **[assumed]**: not verified.

In appletini-one, `core_top` means `hdl/apple/vtw_core_top.sv` and `coalescer` means `hdl/apple/vtw_video_coalescer.sv`.

## Answer

The cause is the firmware's video coalescer. Its page scan makes a drain of scattered screen bytes about 4 times slower than a2vm assumes. The replay's RAMRD toggles around each fuzz record force two such drains per record.

1. **Every TURBO video write goes through the coalescer.**
   - `video_record_enable` is tied to 1 [read `apple_top.sv:2189`], so every TURBO write to aux `$2000-$9FFF` goes through the coalescer [read `core_top:1352-1353`, `:1370-1379`].
   - These bytes are always "active" [read `vtw_video_policy.sv:31`].
2. **How the scan works.**
   - The scanner visits dirty pages in address order, one page index a clock [read `coalescer:119-128`].
   - It then reads all 256 bytes of a selected page, 2 clocks each, dirty or not [read `coalescer:129-149`].
   - A page therefore costs at least 513 clocks (3.9 Apple cycles), however few of its bytes are dirty.
   - The CPU never waits on the write itself [read `coalescer:47`].
3. **Why a column is slow to drain.** A column of the 3D view puts one byte per 160-byte row, about 1.6 dirty bytes a page. Its drain is set by the scan (about 4 Apple cycles a byte), not by the bus (one byte an Apple cycle).
   - A 168-row column drained in 41,854 clocks after its writes [RTL].
   - a2vm predicts 9,690 [a2vm].
4. **Where the replay waits for a drain.**
   - Any `$Cxxx` access waits while `video_active_pending_q` is set [read `core_top:1414-1415`, `:1907`].
   - That flag clears only when every active page is clean, the scanner is between pages and the posted queue is empty [read `coalescer:56-57`, `core_top:1466-1471`].
   - `fuzz_or_overlay` writes `RDAUX` before each fuzz record [read `src/native/replay.s:715`]. That write waits for the scattered column bytes drawn since the previous wait.
   - It writes `RDMAIN` after the record [read `replay.s:720`]. That write waits for the fuzz column itself, which is scattered too.
5. **What a2vm assumes instead.** It drains active bytes in write order, one an Apple cycle [read `tools/a2vm/cost.c:233-280`]. Its README says so: "The coalescer's page scan is taken as free" [read `tools/a2vm/README.md:891-892`].
6. **What the model change recovers.** With the scan modelled (`a2vm-coalescer.patch`), a2vm reproduces the RTL within 1% on every micro-benchmark. It also reproduces the replay's draw phase within 0.4 ms (1%) on all 13 captured frames, run on the RTL itself with the correct pixels. It recovers:

   | Frame | Card excess over a2vm (ms) | Recovered by the model change (ms) | Share |
   | --- | ---: | ---: | ---: |
   | demo-10 | 13.8 | 11.7 | 85% |
   | demo-11 | 14.2 | 12.6 | 88% |
   | demo-09 | 3.6 | 2.4 | 68% |
   | demo-08 | 2.9 | 1.4 | 48% |

7. **What stays unexplained.** 0.0-2.1 ms a frame remains (harness mean 1.0 ms) on every frame, with or without fuzz.
   - It correlates with the texel-copy phase (r = 0.85) [a2vm, card].
   - The RTL bench cannot check that phase, because its PSRAM is a stub.
8. **Things that are not the cause:**
   - The fuzz pixel reads: they are plain TURBO reads [RTL].
   - The second batch [a2vm].
   - The strip count [a2vm].
9. **Replay fix.** Queue the fuzz records and draw them after each strip's columns, in one RAMRD window. A fuzz record that a later record of its column overlaps is drawn at once.
   - demo-10: 45.4 to 32.6 ms [RTL]; 46.0 to 33.3 ms [a2vm, patched model].
   - demo-11: 47.1 to 33.4 ms [RTL].
   - Every frame keeps upstream's pixels [RTL, a2vm].
   - A card disk of the fix is ready: `build/fuzz-timing/REPLAY-defer.hdv`.

## 1. The runner on a2vm against the card

I built the disk again from the same sources. It is identical to `build/native/REPLAY.hdv` (`cmp`) [a2vm].

I ran `disk.py --check`'s procedure on a scratch a2vm built from a copy of `tools/a2vm`: 32 runs, VBL-timed, with the replay's time minus the time without it (`base/diskcheck.json`) [a2vm]. The card figures are the table's [card]. One VBL over 32 runs is 0.625 ms, so each value is ±0.6 ms.

| Frame | Card ms | Runner, a2vm now | Card − now | Runner, patched model | Card − patched |
| --- | ---: | ---: | ---: | ---: | ---: |
| demo-01 | 34.3 | 32.50 | +1.9 | 33.75 | +0.6 |
| demo-02 | 33.7 | 32.50 | +1.2 | 32.50 | +1.2 |
| demo-03 | 30.0 | 29.38 | +0.6 | 28.75 | +1.2 |
| demo-04 | 27.5 | 26.88 | +0.6 | 26.88 | +0.6 |
| demo-05 | 29.3 | 28.75 | +0.6 | 29.38 | 0.0 |
| demo-06 | 31.8 | 31.25 | +0.6 | 31.88 | 0.0 |
| demo-07 | 32.5 | 31.25 | +1.2 | 31.25 | +1.2 |
| demo-08 | 29.3 | 25.62 | +3.7 | 28.12 | +1.2 |
| demo-09 | 25.0 | 21.88 | +3.1 | 23.12 | +1.9 |
| demo-10 | 48.1 | 34.38 | +13.8 | 45.62 | +2.5 |
| demo-11 | 49.3 | 35.00 | +14.3 | 47.50 | +1.9 |
| e1m3-1 | 30.0 | 28.75 | +1.2 | 28.12 | +1.9 |
| still-1..3 | 18.1 | 16.25 | +1.9 | 16.25 | +1.9 |

- All CRCs are equal to the reference in both runs [a2vm].
- The runner's time differs from the harness's (`check.json` `ms_f121`) by -0.6 to +0.5 ms. This is VBL quantisation plus the runner's own interrupts, and matches the README's "within a VBL" [a2vm].

## 2. a2vm experiments on the captured frames

Method (`exp.py`):

- The replay variants are scratch copies of `src/native`, built into `var/`.
- Filters on the loader's records select what each frame keeps.
- Times are the harness's phase 1 (the replay calls) [a2vm].
- "now" is the current f121 model. "patched" is f121 with the coalescer scan (section 5a).
- All times are in ms.

| Frame | Model | base | no fuzz | fuzz empty | RAMRD free | 8 KB stage | 4 KB batches | batch 1 only | deferred (safe) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| demo-08 | now | 26.38 | 26.13 | 26.24 | 26.07 | 26.42 | 26.38 | | 26.35 |
| demo-08 | patched | 27.78 | 26.22 | 27.47 | 26.16 | 27.89 | 27.78 | | 26.47 |
| demo-09 | now | 21.45 | 20.50 | 21.12 | 20.44 | 21.59 | 21.45 | | 21.26 |
| demo-09 | patched | 23.87 | 20.65 | 23.13 | 20.64 | 23.97 | 23.91 | | 21.86 |
| demo-10 | now | 34.34 | 27.75 | 29.42 | 32.57 | 34.43 | 34.25 | 29.19 | 32.87 |
| demo-10 | patched | 46.04 | 28.03 | 36.42 | 32.86 | 46.33 | 45.88 | 40.80 | 33.27 |
| demo-11 | now | 35.09 | 29.15 | 30.91 | 32.90 | 35.12 | 35.02 | 33.01 | 33.67 |
| demo-11 | patched | 47.66 | 29.42 | 39.25 | 33.20 | 47.80 | 47.52 | 45.52 | 34.08 |
| still-1 | now | 16.90 | 16.90 | 16.90 | 16.81 | 16.92 | 16.94 | | 17.01 |
| still-1 | patched | 16.96 | 16.96 | 16.95 | 16.87 | 17.02 | 17.16 | | 17.07 |

What each column is:

- **fuzz empty**: `RDAUX`/`RDMAIN` kept, no pixels drawn.
- **RAMRD free**: an experiment-only model switch. `$C002`/`$C003` writes cost a quiet switch and skip the barrier. This is not a real firmware.
- **8 KB stage**: more strips (`#>STAGE_END` lowered by `$2000`).
- **4 KB batches**: splits still-1 and demo-07 to -09 into 2 batches, and demo-10/11 into 3.
- **batch 1 only**: the columns of batch 2 removed.
- **deferred (safe)**: the proposal in section 5b.

The nine fuzz-free frames do not change in any fuzz-related variant. Their full table is in the `res-*.json` files.

What this separates (demo-10, patched − now) [a2vm]:

- **Fuzz records.** The whole 11.7 ms gap goes with them: without fuzz records the gap is 0.28 ms.
- **The RAMRD waits.** With the toggles made free the gap is 0.29 ms, so at least 97% of it needs the barrier at the RAMRD writes. It splits into:
  - 6.7 ms from the toggles alone ("fuzz empty": the drains they force of the texture columns between fuzz records);
  - 4.7 ms from the fuzz columns' own scattered bytes, drained at each `RDMAIN`.
- **Not the batches:**
  - "batch 1 only" keeps 11.6 of the 11.7 ms gap: the fuzz is in batch 1.
  - Splitting frames into more batches costs 0.0-0.2 ms in either model.
- **Not the strips:** forcing more strips costs 0.03-0.3 ms.
- **The per-record rate.** The gap is 0.09-0.20 ms per fuzz record: demo-09 0.093, demo-08 0.117, demo-11 0.138, demo-10 0.198. The rate grows with the rows per record: 8.5 to 66.6 rows on average [a2vm].

## 3. The RTL simulation

### The benches

Both benches are in `rtl/`. Each is the top of `hdl/sim/tb_vtw_turbo.sv` (lines 1-276: the production `apple_bus_wrapper`, `vtw_core_top`, the motherboard model and the RamWorks model) with its own loader and logging. Built with the memory note's recipe; each builds in 4 s.

Settings:

- PHI0 is PAL: 492.3 ns a half cycle, 131.3 clocks a cycle.
- TURBO: `speed_mode` 3.
- `video_record_enable` 1, as `apple_top.sv:2189` has it.
- The CPU starts after the coalescer's bitmap clear, 131,072 clocks.

The two benches:

- **`tb_fuzz_timing.sv`** runs `gen_prog.py`'s program from ROM `$D000`:
  - the replay's own texture row code (`rows.s`, 168 rows);
  - `aux_fuzz` exactly as the card runs it: the `card.aux0200` bytes at aux `$0200`, entered with RAMRD on;
  - the tables from `card.aux0800`.

  a2vm runs the same ROM and images with a cost-report boundary at each test point (`compare.py`).
- **`tb_replay_rtl.sv`** runs the real replay: the profiling or test build with its driver, on a frame's a2vm image (`replay_img.py`).
  - Main memory is laid out as `translate_apple_addr` maps it: card bank 1 at `$C000` [read `globals.sv:271-277`].
  - RamWorks bank k goes at PSRAM (k+1)<<16 [read `globals.sv:251`].
  - The bench logs each `PHASE` write and dumps the screen at the end.

### Micro-benchmarks

Fabric clocks [RTL, a2vm]:

| Test | RTL | a2vm now | a2vm patched |
| --- | ---: | ---: | ---: |
| (a) 32 texture columns × 168 rows, then `WRMAIN`: per screen byte | 133 | 131 | 133 |
| (a) the CPU part of it (75 clocks a row) | 403,953 | 403,928 | 403,928 |
| (a') 1 column × 168 rows: the `WRMAIN` wait after the writes | 41,854 | 9,690 | 42,116 |
| (a'') 160 contiguous bytes: per byte, drain included | 137 | 134 | 137 |
| (b) `RDAUX`, `aux_fuzz` 100 rows, `RDMAIN`, nothing pending before: per record | 33,378 | 17,329 | 33,370 |
| (b+c) a texture column, then `RDAUX`, fuzz 100 rows, `RDMAIN`: per column | 87,688 | 39,278 | 87,499 |
| (c) a texture column, then `RDAUX`/`RDMAIN` only: per column | 54,949 | 22,514 | 54,957 |
| control: a texture column plus 100 texture rows, no toggles, drain included: per column | 25,993 | 22,892 | 25,985 |
| 16 texture columns, then 16 fuzz records in one RAMRD window | 663,106 | 621,096 | 663,237 |
| 16 texture columns, `WRMAIN` drain, then the 16 fuzz records | 663,500 | 621,490 | 663,499 |

What the table shows:

- **Plain drawing is right in a2vm.** The CPU writes faster than the bus drains, so the backlog grows and the pages fill. The scan keeps ahead and the rate is the bus's (a) [RTL].
- **The cost appears only at a wait on scattered bytes.** A column is 168 bytes on 105 pages; 105 × 513 = 53,900 clocks from its first write, against the 54,745 measured (12,891 CPU + 41,854 wait) [RTL].
- **The fuzz loop is CPU-bound in a2vm but scan-bound on the RTL.**
  - a2vm: about 173 clocks a pixel, bus included.
  - RTL: 334 clocks a pixel, because its 100 bytes sit on 63 pages.
  - The difference is +160 clocks, 1.2 µs, a pixel. This is the owner's "about 1 µs a fuzz pixel" [RTL, a2vm].
- **One RAMRD pair after a full column costs +0.24 ms** on the RTL over a2vm ((c): 32,435 clocks). Drawing the same fuzz records inside one window, or after the drain, takes the RTL 663k clocks against 1,403k (16 × (b+c)): 2.1 times faster [RTL].
- **The fuzz pixel reads cost nothing extra.** In the last row of the table, the fuzz is drawn from a drained screen: the patched model, which charges those reads as ordinary TURBO reads, matches the RTL to the clock (663,499 against 663,500) [RTL, a2vm]. No read path waits on the coalescer or the mirror.

### The replay on the RTL

All 13 captured frames ran through the profiling build [RTL, a2vm]. Every frame's screen after the run equals upstream's `screen-after.bin` [RTL]. The copy phase is not comparable: the bench's RamWorks has a 16-44 clock stub latency [read `tb_vtw_turbo.sv:171-199`].

| Frame | Draw, RTL (ms) | Draw, a2vm now | Draw, a2vm patched | Walk, RTL = a2vm | Switches, RTL / a2vm |
| --- | ---: | ---: | ---: | ---: | ---: |
| demo-01 | 25.135 | 24.958 | 25.137 | 2.240 | 0.134 / 0.132 |
| demo-02 | 22.243 | 22.029 | 22.244 | 2.340 | 0.151 / 0.152 |
| demo-03 | 22.627 | 22.452 | 22.624 | 2.134 | 0.133 / 0.128 |
| demo-04 | 20.515 | 20.354 | 20.513 | 1.967 | 0.111 / 0.111 |
| demo-05 | 24.603 | 24.510 | 24.604 | 1.858 | 0.105 / 0.101 |
| demo-06 | 25.287 | 24.961 | 25.286 | 1.971 | 0.111 / 0.106 |
| demo-07 | 21.615 | 21.426 | 21.613 | 2.714 | 0.220 / 0.215 |
| demo-08 | 17.908 | 16.495 | 17.887 | 2.902 | 0.231 / 0.229 |
| demo-09 | 14.505 | 12.112 | 14.490 | 2.952 | 0.229 / 0.230 |
| demo-10 | 33.144 | 21.478 | 33.150 | 3.923 | 0.341 / 0.335 |
| demo-11 | 34.840 | 22.202 | 34.825 | 3.992 | 0.329 / 0.321 |
| e1m3-1 | 20.056 | 19.901 | 20.055 | 2.162 | 0.122 / 0.126 |
| still-1 | 8.751 | 8.656 | 8.708 | 2.986 | 0.272 / 0.269 |

- On the test build (no profiling marks), the RTL takes 45.41 ms on demo-10 and 47.09 on demo-11 [RTL]. The card takes 48.1 and 49.3 [card].
- The walk matches to 0.001 ms and the switches phase to 5%, on every frame [RTL, a2vm].

### RTL lines that make the difference

In the order a fuzz record meets them:

1. `apple_top.sv:2189` `.video_record_enable(1'b1)` and `core_top:1352-1353`: in TURBO every video write takes the coalescer path, never the old write-ordered posted queue (`core_post_accept` needs `!video_selected`, `core_top:1374-1375`).
2. `vtw_video_policy.sv:31`: aux `$2000-$9FFF` is always `extended_graphics`, so always active.
3. `coalescer:88-92`, `:104-107`: a write only sets the byte's and page's dirty bits. `write_ready` is high outside the bitmap clear (`:47`), so the CPU never waits here, and the draw runs ahead.
4. `coalescer:119-128`: `SELECT_PAGE` moves `next_page_q` by one page a clock through all 512 pages.
5. `coalescer:102-105`: the page bit clears on selection, so a write during the scan schedules another whole pass.
6. `coalescer:129-139`: `FETCH_BYTE` then `CHECK_BYTE`, 2 clocks, for each of the page's 256 bytes, dirty or not. **This is the cost: at least 513 clocks a page.**
7. `coalescer:140-149` with `core_top:1446`: a dirty byte waits in `SEND_BYTE` while the engine's queue reports full. The queue holds 512 entries, full at 508 [read `vtw_bus_engine.sv:177`, `:180`, `:369-370`].
8. `coalescer:56-57` (`active_drained`) with `core_top:1466-1471`: `video_active_pending_q` falls only when the scan is idle on clean pages and the queue is empty.
9. `core_top:1414-1415` and `:1907`: `video_barrier` holds `X_CAPTURE` for any `$Cxxx` access while it is pending. The replay's `STA $C003` and `STA $C002` are such accesses. `core_top:767` also keeps any bus request waiting.

History: the scan was introduced with the coalescer in `2a73c9f` (2026-09-12), which F1.1.0 and every later tag contain [read `git tag --contains`]. The existing port's E1M1 frame, on which a2vm was calibrated, gives 248.6 ms with and without the scan model (below), so that calibration could not have shown it [a2vm]. My reading of why: the port's writes are whole rows [assumed].

## 4. Does it explain the card's excess?

Per-frame numbers, in ms:

- **Card**: the owner's values [card].
- **Now, Patched**: the harness's phase 1 [a2vm].
- **Explained**: (patched − now) / (card − now).
- **Residual**: card − patched.

| Frame | Card | Now | Patched | Card − now | Patched − now | Explained | Residual | Copy phase |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| demo-01 | 34.3 | 33.24 | 33.41 | 1.06 | 0.17 | 16% | 0.88 | 6.07 |
| demo-02 | 33.7 | 32.28 | 32.50 | 1.42 | 0.22 | 16% | 1.20 | 7.93 |
| demo-03 | 30.0 | 29.27 | 29.44 | 0.73 | 0.17 | 24% | 0.56 | 4.70 |
| demo-04 | 27.5 | 26.82 | 26.98 | 0.68 | 0.16 | 23% | 0.52 | 4.52 |
| demo-05 | 29.3 | 29.17 | 29.27 | 0.13 | 0.10 | 75% | 0.03 | 2.79 |
| demo-06 | 31.8 | 31.30 | 31.62 | 0.50 | 0.33 | 65% | 0.18 | 4.39 |
| demo-07 | 32.5 | 31.55 | 31.73 | 0.95 | 0.19 | 20% | 0.77 | 7.34 |
| **demo-08** | 29.3 | 26.38 | 27.78 | **2.92** | 1.40 | 48% | 1.52 | 6.91 |
| **demo-09** | 25.0 | 21.45 | 23.87 | **3.55** | 2.41 | 68% | 1.13 | 6.37 |
| **demo-10** | 48.1 | 34.34 | 46.04 | **13.76** | 11.70 | 85% | 2.06 | 8.89 |
| **demo-11** | 49.3 | 35.09 | 47.66 | **14.21** | 12.57 | 88% | 1.64 | 8.84 |
| e1m3-1 | 30.0 | 28.25 | 28.41 | 1.75 | 0.15 | 9% | 1.59 | 6.26 |
| still-1 | 18.1 | 16.90 | 16.96 | 1.20 | 0.06 | 5% | 1.14 | 5.19 |

- **The mechanism explains the fuzz excess.** What is left on the four fuzz frames (1.1-2.1 ms) is the size of the residual on frames with no fuzz at all:
  - e1m3-1: 1.6 ms;
  - still-1: 1.1 ms;
  - demo-02: 1.2 ms.
- **What is left is not fuzz.** The residual across all 13 frames:
  - mean 1.02 ms, s.d. 0.60 (harness); 1.25 ms, s.d. 0.77, against the runner [a2vm, card];
  - it correlates with the texel-copy phase: r = 0.85, slope 0.28 ms per ms of modelled copy, intercept -0.71 ms;
  - the regression predicts 1.44, 1.28, 2.04 and 2.02 ms for demo-08, -09, -10 and -11. The card shows 1.52, 1.13, 2.06 and 1.64.
- **So the card's "+4-7% elsewhere" is mostly not this mechanism.** The scan model accounts for only 0.06-0.33 ms on the fuzz-free frames. Their remaining 0.0-1.6 ms (0-5.6%) is **unexplained**.
- **What I suspect for the residual** [assumed, not verified]: the copies' RamWorks line misses (PSRAM admission) cost about 25-30% more on the card than the model charges. This is the only phase the RTL bench cannot check, because its RamWorks is a stub. Walk and switches were checked [RTL].
- **How to settle it.** A card run of a disk that skips the draw (walk and copies only) would show it [assumed]. Precision limits: the card numbers are VBL-quantised (0.625 ms over 32 runs) and printed truncated to 0.1 ms.

## 5. Proposals (not applied)

### 5a. The a2vm model: `a2vm-coalescer.patch`

The patch is a unified diff against the working tree of `tools/a2vm` as copied at 09:06 today. It also touches `tests/test_a2vm_cost.py`. `git apply --check` passes on the current tree.

What it changes:

- **`cost.c`**: `cz_push`, `cz_advance`, `cz_send`, `active_end_now` and `active_pending`.
  - An active mirror byte sets its dirty byte and page.
  - A lazy scanner follows `coalescer:119-149` clock for clock: one page index a clock, 2 clocks a byte of a selected page, `SEND_BYTE` waiting on a 508-entry queue, the bus one byte an Apple cycle (the existing `drive_cycle`).
  - The barrier (`io_access`) and the memory API's hold wait until the scan is idle on clean pages and the queue's last cycle is done.
  - RamWorks accesses first advance the scanner, so `aux_drain_end` (PSRAM admission) sees the bus cycles up to now.
  - Deferred and lazy bytes keep the existing flush model.
- **`cost.h`**: new parameters and state; `scan_pages` counter.
- **`costs/appletini.json`**: three new "common" parameters, each with its source lines:
  - `coalescer` 1;
  - `scan_byte` 2 (`coalescer:129-139`);
  - `post_depth` 508 (`vtw_bus_engine.sv:177`, `:180`, `:369-370`).
- **`README.md`**: the mirror row of the cost table, and the "does not do" bullet, which now describes the model and its RTL check.
- **`tests/test_a2vm_cost.py`**:
  - two assertions that counted posted bytes before the barrier now count them after it;
  - new `test_sparse_column_drains_by_the_page`: a 168-row column must drain in 53,760-55,760 clocks and 168 contiguous bytes in 168 Apple cycles plus 1,200 clocks.

  The new test fails on the current model (22,186 clocks) and passes on the patched one [a2vm].

Checks [a2vm]:

- **The bus-script classes of `test_a2vm_cost.py`** (15 tests, run by `run_cost_tests.py` against the scratch binaries and costs, without building `tools/a2vm`):
  - all pass on the patched copy;
  - the unpatched copy passes the old tests and fails the new one.
- **`coalescer 0` gives the old timings exactly:** every boundary of the micro-benchmark is the same.
- **The calibration frame does not move.** The existing port's E1M1, `cost_report.run` for 20 frames:

  | Profile | Current model | Patched model |
  | --- | ---: | ---: |
  | f121 | 248.6 ms | 248.6 ms |
  | fastpath | 188.6 ms | 188.6 ms |

- **The replay's fastpath numbers do not change** (15.86-29.96 ms): lazy SHR has no barrier.
- **Against the RTL:** the micro-benchmarks and the replay's draw phase on all 13 frames agree within 1% [RTL, a2vm].

Not in the patch:

- The flush of deferred and lazy bytes (exposures, bank writes, holds) still ignores the scan. Those flushes drain whole screens, whose pages are full [assumed].
- The patch does not model `CLEAR_BITMAP` after a reset.

Other files will change their numbers once the patch lands (f121 only): NATIVE.md's F1.2.1 replay figures, `src/native/README.md` Results and `check.json`.

### 5b. The replay: draw fuzz records after the strip's columns

The variant is `defersafe` in `exp.py`, built in `var/defersafe/`.

**How it works:**

- `fuzz_or_overlay` queues each K_FUZZ record instead of drawing it: its column, row, count and position, 4 bytes, at most 72.
- `draw_strip` draws the queue after the strip's last column, before `WRMAIN`: one `RDAUX`, `aux_fuzz` for each record in order, one `RDMAIN`.
- The `RDAUX` then waits for the strip's dense backlog, which is fast. The fuzz columns' own scattered drain happens once, at `WRMAIN`.
- A full queue draws the record at once, as before.

**When a record must not be deferred.** A fuzz record reads the rows above and below its own, in its own column. It must be drawn in place when a later record of the same column paints any row from `row-1` to `row+count`.

- In the captures this happens to 3 of 188 fuzz records, all in demo-09 [a2vm].
- Deferring those too changes 1 byte of demo-09 [a2vm].
- The variant has the loader mark such records with kind 12, an unused kind since K_NEXT is dropped. The replay draws kind 12 at once. The gather and the dispatcher accept it.
- In the game, the producer (milestone 7) would set that mark [assumed].

**Results** (ms; RTL on the test build with the stub PSRAM; a2vm with the patched model):

| Frame | Now, RTL | Deferred, RTL | Now, a2vm patched | Deferred, a2vm patched | Card now | Card expected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| demo-08 | 27.27 | 25.96 | 27.78 | 26.47 | 29.3 | about 28.0 |
| demo-09 | 23.48 | 21.49 | 23.87 | 21.86 | 25.0 | about 23.0 |
| demo-10 | 45.41 | 32.64 | 46.04 | 33.27 | 48.1 | about 35.3 |
| demo-11 | 47.09 | 33.42 | 47.66 | 34.08 | 49.3 | about 35.7 |
| fuzz-free frames | | | | +0.03-0.11 | | |
| fastpath, all | | | | +0.0-0.2 | | |

- "Card expected" is the card now minus the RTL saving [assumed: the residual stays].
- Pixels equal upstream's on all 13 frames, on the RTL (4 fuzz frames) and on a2vm (13 frames, both models).

**The card disk.** `REPLAY-defer.hdv` (`diskdefer.py`) is the runner with this variant. On a2vm with the patched model, every CRC is OK and the times are:

- demo-10 33.1 ms, demo-11 33.8 ms;
- demo-08 25.6 ms, demo-09 21.2 ms;
- other frames unchanged within a VBL [a2vm].

Booting it on the card tests both the diagnosis and the fix.

**What adopting it needs:**

- **Where the queue lives.** The variant puts it in the card's `$F900-$FEFF` part. RCODE grows from 1,079 to 1,462 of 1,536 bytes [read `var/defersafe/obj/test.map`].
  - The alternative is aux 0 `$0280-$03FF`, beside `aux_fuzz`. That space is unused (113 of 512 bytes taken [read `src/native/README.md` Memory]), writable with RAMWRT on and readable with RAMRD on, and not a video window [read `vtw_bus_engine.sv:48-60`].
  - Either way `layout.py`'s allowed ranges and MEMORY_MAP section 8 must name it, or `replay_check.py` reports stray writes [assumed].
- **The deferral rule.** It needs the producer or loader to mark non-deferrable fuzz records. It also needs a test (a synthetic stream with a later record over a fuzz column's neighbour rows).

**Alternatives considered:**

- *Fuzz source pixels from a copy in main memory, no RAMRD.* Not practical.
  - A copy of the whole view has no room: main `$2000-$5FFF` is itself a posted video window, and `$6000-$BFFF` is W [read MEMORY_MAP section 8].
  - Copying only the neighbour rows before each fuzz record needs RAMRD anyway, and so waits for the same barrier.
- *One RAMRD window per column, or batching the toggles by other means.* No `$Cxxx` access can happen while scattered bytes are pending without paying their scan. Only moving the fuzz after a dense drain helps [RTL].
- *Firmware.*
  - The fast-path design's quiet RAMRD and lazy SHR class remove the wait entirely: fastpath times are unchanged by the patch [a2vm].
  - A coalescer that skips clean bytes (for example, a per-page summary of dirty 32-byte blocks) would make the scan cost negligible [assumed]. The current model's numbers are the ideal for that case: demo-10 34.3 ms.

## Files

All in `/Users/henri/Documents/Repos/appletini-software/demos/doom_gs/build/fuzz-timing/`. Nothing in `tools/a2vm`, `tools/ref816` or `src/` was changed.

| File | What it is |
| --- | --- |
| `a2vm-coalescer.patch` | The proposed model change and tests (5a) |
| `a2vm-orig/`, `a2vm-bin/` | Copy of `tools/a2vm` at 09:06 and its build (the "now" model) |
| `a2vm-src/`, `a2vm-cz/` | The patched copy plus the experiment-only `exp_ramrd_quiet` switch, and its build |
| `prop/`, `prop-bin/` | The patch applied to a clean copy (and the edited test), and its build |
| `f121q*.cost`, `f121cz*.cost`, `prop-*.cost` | Cost files: f121 now, f121 with the scan, each also with RAMRD free; the patched package's profiles |
| `diskcheck.py`, `base/`, `cz/` | The runner on a2vm, now and patched (`diskcheck.json`) |
| `exp.py`, `var/`, `runs/`, `res-*.json` | The replay variants and record filters, and their results |
| `rtl/tb_fuzz_timing.sv`, `rtl/gen_prog.py`, `rtl/compare.py`, `rtl/sim.log` | The micro-benchmark bench, its program and results |
| `rtl/tb_replay_rtl.sv`, `rtl/replay_img.py`, `rtl/replay/`, `rtl/replay_*.jsonl` | The whole replay on the RTL, per frame |
| `run_cost_tests.py` | `test_a2vm_cost.py`'s bus-script classes against the scratch builds |
| `e1m1.py`, `e1m1/` | The calibration frame, now and patched |
| `diskdefer.py`, `REPLAY-defer.hdv`, `defer-disk/` | The card disk of 5b and its a2vm check |

Batch runs used at most 2 jobs under `nice -n 10`.

## Adversarial check

**Verdict: confirmed.** The fuzz-frame slowdown comes from the firmware coalescer's page scan. I could not refute it: the RTL runs, the a2vm runs and the cited source lines all reproduce. I found two errors in the report, and its explanation of the remaining ~1 ms a frame is not established.

**What I re-ran** (all scratch, at most 2 jobs, under `nice -n 10`; `tools/a2vm` untouched):
- **Micro-benchmark bench:** I rebuilt `tb_fuzz_timing` from the RTL snapshot. Its log is identical to theirs at every mark.
- **Micro-benchmarks on a2vm:** I built the current a2vm and a copy with `a2vm-coalescer.patch` applied (it applies cleanly and matches their `prop/a2vm`). The patched model matches the RTL within 1% on every test. Two examples, in fabric clocks:
  - One 168-row column, the wait after its writes: RTL 41,854, patched 42,116, current model 9,690.
  - `RDAUX` + 100 fuzz rows + `RDMAIN`: RTL 33,378, patched 33,370, current 17,329.
- **Full replay on the RTL:** I rebuilt `tb_replay_rtl` and ran demo-10 and still-1. Totals are 45.915 and 16.902 ms, identical to theirs, and the screens are correct.
- **Harness on all 15 frames:** current model identical to `check.json`; patched model gives demo-10 46.04, demo-11 47.66, demo-09 23.87, demo-08 27.78. Every screen is correct, and the patch's own a2vm cost tests pass.
- **Runner check:** the rebuilt disk is identical to `build/native/REPLAY.hdv`. At 32 runs a frame I get the report's section 1 figures exactly. I also ran it at 200 runs a frame, which cuts the model's rounding from 0.625 ms to 0.1 ms.
- **Cited lines:** all correct except one. The coalescer's `write_ready` is at line 50, not 47.

**Errors in the report:**
1. **"Within 10% on all frames" fails in their own 32-run table.** still-1..3 is 16.25 ms against the card's 18.125, so the card is 11.5% above the model. That is rounding in the model's 32-run count; at 200 runs the model gives 17.1 ms and the error is 6%. The harness and the 200-run runner are within 10% on all 15 frames.
2. **The leftover gap is not shown to come from the texel copy phase.** After the patch, the card is still 0.1-2.0 ms (mean 1.0) above the model on every frame. That gap tracks three things about equally, and they track each other (r = 0.75 between two of them):
   - the copy phase: r = 0.84;
   - the size of the frame's records: r = 0.76;
   - the time of the runner's own loop without the replay, which it subtracts: r = 0.79.

   The card's figures also match the patched model's loop *with* the replay alone, before subtracting anything, within ±0.83 ms on all 13 distinct frames (mean −0.3). That would mean the card's loop without the replay takes about zero time, which is implausible: a2vm puts it at 0.7-2.5 ms a run.

   The gap does not follow the number of screen stores (r = −0.37). That rules out the unmodelled backpressure from the renderer's capture stream (`apple_cycle_capture.sv:298-301`). a2vm assumes that stream always accepts, and the bench ties it to 1.

   **The test that settles it:** have the runner print the two loop counts (with and without the replay) separately instead of their difference.

**Other explanations I ruled out:**
- `$C002`/`$C003` (the RAMRD toggles) do not force a full flush of the mirror (`vtw_core_top.sv:1390-1400`). `$C073` does, but only while mirror bytes are pending.
- Mirroring of main `$2000-$9FFF` would need aux `$9DF8` set to 1 or 2 (`vtw_core_top.sv:1877-1881`); it is 0 in every capture.
- After the patch, the fuzz frames' remaining gap (1.0-2.0 ms) is the same size as on the frames without fuzz. The second batch and the extra strips add 0.0-0.3 ms.

**Corrected explanation:** as the report says for the fuzz frames. Draws that leave a few dirty bytes per 256-byte page cost at least 513 fabric clocks a page, about 4 Apple bus cycles. The `RDAUX`/`RDMAIN` writes around each fuzz record wait for two such drains. The patched model covers 85-88% of demo-10/11's excess. What remains (about 1 ms a frame, every frame) has no established cause.

**Card against the patched model** (card ms = VBL count × 0.625; "shown" is the card's truncated display):

| frame | card shown | card ms | a2vm now | patched harness | card/patched | patched runner, 32 runs | card/that | patched runner, 200 runs | card/that |
|---|---|---|---|---|---|---|---|---|---|
| demo-01 | 34.3 | 34.375 | 33.24 | 33.41 | 1.029 | 33.75 | 1.019 | 33.4 | 1.029 |
| demo-02 | 33.7 | 33.75 | 32.28 | 32.50 | 1.039 | 32.50 | 1.038 | 32.5 | 1.038 |
| demo-03 | 30.0 | 30.0 | 29.27 | 29.44 | 1.019 | 28.75 | 1.043 | 29.5 | 1.017 |
| demo-04 | 27.5 | 27.5 | 26.82 | 26.98 | 1.019 | 26.88 | 1.023 | 27.1 | 1.015 |
| demo-05 | 29.3 | 29.375 | 29.17 | 29.27 | 1.004 | 29.38 | 1.000 | 29.3 | 1.003 |
| demo-06 | 31.8 | 31.875 | 31.30 | 31.62 | 1.008 | 31.88 | 1.000 | 31.8 | 1.002 |
| demo-07 | 32.5 | 32.5 | 31.55 | 31.73 | 1.024 | 31.25 | 1.040 | 31.8 | 1.022 |
| demo-08 | 29.3 | 29.375 | 26.38 | 27.78 | 1.058 | 28.12 | 1.044 | 27.8 | 1.057 |
| demo-09 | 25.0 | 25.0 | 21.45 | 23.87 | 1.047 | 23.12 | 1.081 | 24.0 | 1.042 |
| demo-10 | 48.1 | 48.125 | 34.34 | 46.04 | 1.045 | 45.62 | 1.055 | 46.1 | 1.044 |
| demo-11 | 49.3 | 49.375 | 35.09 | 47.66 | 1.036 | 47.50 | 1.039 | 47.8 | 1.033 |
| e1m3-1 | 30.0 | 30.0 | 28.25 | 28.41 | 1.056 | 28.12 | 1.067 | 28.4 | 1.056 |
| still-1/2/3 | 18.1 | 18.125 | 16.90 | 16.96 | 1.069 | 16.25 | 1.115 | 17.1 | 1.060 |

Files are in <scratchpad>/adv:
- `a2vm/` and `bin-cz/a2vm`: the patched copy and its binary
- `bin-now/a2vm`: the current model
- `f121-now.cost`, `f121-cz.cost`: the two cost files
- `res-now.json`, `res-cz.json`: harness results with phase breakdowns
- `dc-now/`, `dc-cz/`: runner check at 32 runs; `dc200-now/`, `dc200-cz/`: at 200 runs
- `rtl/sim.log`, `rtl/cmp-now.txt`, `rtl/cmp-cz.txt`: micro-benchmark runs and comparisons
- `rtl/replay/`: the RTL replay runs