# Option 1: a real cache in front of extended (RamWorks) memory, and the choice of backing store (review)

# Adversarial review: Option 1 (multi-line RamWorks cache, backing store)

All paths are under `appletini-one-main/`. **V** = I opened the file and checked. **A** = my inference. Nothing was simulated or built.

## Findings

| # | Sev | Finding | Evidence | Correction |
|---|---|---|---|---|
| 1 | Blocker | Handback coherence is staged wrongly and gated in the wrong place. The cache ships in stage 2, the /DMA gate in stage 3. After `enable` falls the engine leaves `S_RUN` at the next `drive_en` and releases /DMA one cycle later, so up to 4096 dirty lines are still in BRAM when the motherboard CPU resumes. | V `vtw_bus_engine.sv:811-831`, `:923-937`; `vtw_core_top.sv:352`, `:1783-1795` | Put the gate in stage 2, and gate the exit from `S_RUN` (`:811`) on `rwc_flush_busy`, not `S_RELEASE`. |
| 2 | Blocker (same fix) | Holding in `S_RELEASE` defeats the plan's own flush numbers. `bus_owned = wr_addr_rw_en_q`, which is 0 there, so relaxed admission is off (about 4 ms, not 0.74 ms) and serve reads are re-enabled on an undriven address bus. Each spurious serve clears `admit_armed_q`. | V `vtw_bus_engine.sv:480`, `:929`; `psram_simple.sv:134-135`, `:337` | Stay parked in `S_RUN` while flushing. Flush only on `!enable`. On //e RES# keep the cache valid, since the bank register resets to 0 and the 80-cycle stock run touches main only. |
| 3 | Major | Every ARM operation would cold-start the cache. SmartPort block read and write, and every memory API `hw_begin` (whether or not `needs_ramworks` is set), raise the flush request, which also invalidates. With 4096 lines that is a scan, a 31 µs sweep and a refill per call. | V `smartport_service.c:445`, `:508`, `:917`; `memory_api_hw.c:127`; `vtw_core_top.sv:1814`, `:1821` | Split clean from invalidate. Invalidate only the DMA target range (64 lines per 512 bytes), and skip it for shadow-only calls. |
| 4 | Major | Stage C breaks the plan's own rule: tag compare and BRAM byte write enable in the same clock. The dirty bit in the tag RAM also needs a tag write on every write hit. | Plan §4 | Register `rwc_hit_q` and a one-hot lane in `X_RW_CHECK`; write data and tag on the first clock of `X_RW_DONE`. Still 5 clocks. |
| 5 | Major | Timing evidence is stale and risk understated. The +0.169 ns row is from a build that was not promoted, judged against a +0.300 ns gate. Its 74% route share points to placement, which 10 more RAMB36 worsen. The −0.063 ns build is attributed to capture-enable paths, not BRAM count. | V `FABRIC_TIMING_MARGIN_PLAN.md:854-858`; `README_TURBO.md:149-152` | Budget a 6-clock hit with BRAM output registers on as the baseline; treat 5 as the trial. |
| 6 | Major | Software model gap. With RAMRD on and bank N selected, all reads in `$0200-$BFFF` come from bank N+1, opcode fetches included. With ALTZP, zero page, stack and LC do too. "Keep hot code in main" only works from `$D000-$FFFF` or ZP/stack with ALTZP off. | V `globals.sv:251-270` | State this in the plan. The assumed 40% hit rate today is optimistic when code and data share a bank. |
| 7 | Major | A much smaller design is not considered: 8–16 fully associative lines in distributed RAM. Worst flush is 16 × 32 clocks (about 4 µs), invalidate is one clock, no BRAM, no scanner, and no /DMA gating beyond today's. | A: about 50 LUTs of LUT-RAM, 350 flip-flops, 150 LUTs | Make this stage 2. Build BRAM only if counters show it is not enough. |
| 8 | Minor | Read back-to-back period is 32, not 31. `QPIR_CE_N_TAPE` is a 31-bit literal zero-extended to 32, giving 25 CE-low slots; ready returns after E31. | V `psram_driver.sv:228`, `:143-158` | Use 32. Widen the literal deliberately. |
| 9 | Minor | "Sustained miss 131 clocks" understates today's blit case. The write queue outranks vTW and each admission clears the arm, so with one posted write per Apple cycle the vTW op waits until the queue is empty. | V `psram_simple.sv:447-467` (A for the traffic pattern) | Strengthens stage 1. Measure it in stage 0. |
| 10 | Minor | "(a) needs no ARM change" holds only for banks up to `$7E`. The core maps bank `$7F` to `0x80xxxx`; the memory API rejects `physical >= 0x800000`. | V `memory_api_hw.c:149-152`; `psram_simple.sv:124-125` (header `:35-37` is stale) | Existing gap; note it. |
| 11 | Minor | SmartPort flush timeout is a poll count (16384), not a time. A full flush at the windowed rate (about 4 ms) may exceed it. | V `smartport_service.c:84`, `:446` | Make it time-based, or bound dirty lines. |
| 12 | Minor | "Register `rw_resp_rline`" is redundant; `vtw_rline` is already a register. | V `psram_simple.sv:546` | Add one only for placement. |
| 13 | Minor | "T157" is a stale comment. FCLK0 is requested at 133 MHz and the bench uses 130 clocks per cycle. | V `create_project.tcl:155`; `tb_psram_simple.sv:91` | 131 is right. |
| 14 | Minor | PS DMA "about 15 µs per chunk" ignores `apple_dma_engine` state and AXI time. | Not derivable from the RTL | Drop the figure until measured. |

## (1) Confirmed claims

- Single line registers, hit test, the four `X_RW_*` states, and the line surviving `turbo_invalidate` (`vtw_core_top.sv:1045-1060`, `:1206-1211`, `:1793-1795`).
- Hit is 5 clocks in TURBO and 4 in 33 MHz mode; request to completion is 31 clocks; clean miss about 35.
- RamWorks pages never enter the TURBO caches (`:1212-1215`); skipping `X_ROUTE` has precedent (`:1249-1251`, `:1971`).
- Flush and hold logic, `rw_flush_unsafe`, and all eight perf slots taken (`:1604-1611`, `:1630-1641`, `:1723-1843`).
- One admission per cycle, the priority order, serve gating and live write capture (`psram_simple.sv:134-136`, `:239`, `:313-329`, `:437-486`).
- Relaxing admission while `vtw_bus_owned` is sound, since no deadline client exists then. The tail guard is needed and sufficient.
- The posted-write bank 0/1 rule (`:565-569`) and the proposed assertion.
- Driver layout, read `rvalid` at E26, write `rvalid` at E18, write period 24.
- No physical aliasing (`globals.sv:271-277`); 7-bit bank with bit 7 ignored (`soft_switch_manager.sv:141-144`).
- BRAM arithmetic: 10 tiles at 32 KB, 19 at 64 KB.
- HP port allocation; `axi3_read_arbiter_2` is not instantiated.
- 100 ms hold timeout (`memory_api_hw.c:17`); 2 × 8 MB chips (`AGENTS.md`).

Not checked: `tb_vtw_turbo.sv:550-619`, `disk2_service.c:167`, the DDR region, and whether the chips ignore address bit 23.

## (2) Corrected summary

1. **Stage 0:** counters for hits, misses, miss wait, and separately `$C071/$C073` writes and the video-flush clocks they cause.
2. **Stage 1:** relaxed admission in `psram_simple.sv:437` with `relax_q`, `relax_tail_q` and the bank assertion. About 15 LUTs. Sustained miss drops from 131 or more clocks to about 36. Ship this alone.
3. **Stage 2:** an 8–16 line fully associative cache in distributed RAM, physically tagged, write-back. Hit compare is registered and the write is applied in `X_RW_DONE`. Flush is at most 16 line writes, so the existing reset and ARM flush sequencers generalise with a 4-bit counter. Split ARM "clean" from "invalidate" and invalidate by range.
4. **Stage 3, only if stage 0 data justifies it:** the 32 KB direct-mapped BRAM cache, 10 tiles. It needs the `S_RUN` exit gate, flush on `!enable` only, a dirty summary, a 6-clock hit baseline, and the full +0.200 ns procedure.
5. **Deferred:** DDR backing and 16 MB. The plan's reasoning there holds.

Every bank change stays a real bus cycle plus TURBO invalidation plus, while SHR writes are pending, a video mirror flush at one byte per Apple cycle (`vtw_core_top.sv:1400`, `:1408-1413`). The shared RAMRD/RAMWRT bank is also untouched. For a renderer that reads texels from extended memory and writes SHR, these dominate once misses cost 36 clocks.

## (3) Verdict

- **Stage 1:** build it now. It is small, verified against the RTL, and removes most of the miss cost.
- **BRAM cache as written:** do not build yet. It has a handback blocker, it is flushed wholesale by every ARM call, it spends 10 of the 30 free tiles on the tightest part of the design, and its benefit rests on assumed hit rates.
- **Order:** the small associative cache and a cheaper bank switch come first; revisit the BRAM cache with stage 0 numbers.