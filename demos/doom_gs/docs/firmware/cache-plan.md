# Option 1: a real cache in front of extended (RamWorks) memory, and the choice of backing store (plan)

# Option 1: multi-line cache for RamWorks memory, and the backing store

All paths are under `appletini-one-main/`. **V** = verified in the RTL or source (file:line). **A** = my assumption or estimate.

## 1. Conclusion

- Recommend backing store (a): keep PSRAM, relax admission while the vTW owns the bus, and replace the single line with a direct-mapped BRAM cache.
- A sustained random miss falls from about 131 fabric clocks to about 35–37 (derived from the RTL, not simulated).
- Hits stay at 5 clocks in TURBO in the conservative pipeline; a 4-clock variant is a separate timing trial.
- Keep (b), DDR over AXI HP, as a later stage. Its miss latency is probably only 1.3–2 times better than relaxed PSRAM, and it splits RamWorks storage across two devices.
- This option does not reduce the cost of a `$C071/$C073` write (a real bus cycle plus TURBO invalidation plus video exposure flush). With frequent bank changes that cost will dominate once misses are cheap.

## 2. What exists today (verified)

| Fact | Evidence |
|---|---|
| Single line: `rwc_valid_q`, `rwc_dirty_q`, `rwc_line_q[20:0]`, `rwc_data_q[63:0]` | `vtw_core_top.sv:1045-1048` |
| Hit test is `rwc_line_q == xl_decoded[23:3]`: physically tagged, bank included | `:1058-1060` |
| States `X_RW_LOOKUP`, `X_RW_FLUSH`, `X_RW_FILL`, `X_RW_DONE` | `:1001-1004`, `:2045-2103` |
| The line is not cleared by `turbo_invalidate`; only by `!enable` when clean, or by an ARM flush | `:1793-1795`, `:1814`, `:1821` |
| RamWorks pages never enter the TURBO caches (`turbo_map_fill` and `turbo_byte_fill` need `xl_shadow_valid`) | `:1212-1215` |
| TURBO path for a RamWorks access: `X_CAPTURE → X_TURBO_DONE → X_ROUTE → X_RW_LOOKUP → X_RW_DONE` | `:1952-1953`, `:1970-1971`, `:2027-2028` |
| Dirty write-back when the core is in reset | `:1783-1792` |
| ARM flush and hold: `arm_rw_flush_req`, `rw_hold_q` gates `core_en`, `rw_flush_unsafe` lists unsafe states | `:1523`, `:1604-1611`, `:1723-1843` |
| One background admission per Apple cycle: armed at `addr_en`+3, 40-tap window, cleared on use | `psram_simple.sv:239`, `:313-329`, `:437`, `:461` |
| Background priority: parked RMW leg > write queue > vTW > PS DMA | `psram_simple.sv:439-486` |
| Serve reads are suppressed while `vtw_bus_owned`; write capture stays live | `psram_simple.sv:134-136` |
| Driver: one CE, one clock, two 4-bit chips; chip A carries `wdata[31:0]`, chip B `wdata[63:32]` at the same address | `psram_driver.sv:38-39`, `:456-457` |
| A timing path "vTW cycle address to RamWorks cache-data enable" already sits at +0.169 ns, 10 levels | `docs/FABRIC_TIMING_MARGIN_PLAN.md:854` |

### PSRAM operation timing, counted from the driver tapes

Let E0 be the edge where the driver accepts `valid && ready`.

| Event | Read (`QPIR_*`, `:228-233`) | Write (`QPIW_*`, `:222-225`) |
|---|---|---|
| Driver `rvalid` registered | E26 | E18 |
| Driver `ready` again (`ce_rest_cycles` = 4, `:154`) | after E30 | after E23 |
| Back-to-back period | 31 clocks | 24 clocks |

From the `X_RW_LOOKUP` edge that sets `rw_req_valid_q` to core completion is 31 clocks for a read, if admission is immediate.

### Current access cost

| Case | TURBO | 33 MHz mode |
|---|---|---|
| Hit (read or write) | 5 clocks | 4 clocks |
| Miss, clean, window open | about 35 | about 34 |
| Miss, sustained random | one per Apple cycle, about 131 clocks | same |
| Miss with dirty victim | two admissions, about 261 clocks | same |

One inconsistency: `psram_simple.sv:238` refers to "T157", but 133.333 MHz over 1.0205 MHz is about 131 clocks, and `tb_psram_simple.sv:134` uses 130. I used 131.

## 3. What the admission rule protects, and relaxing it

The rule protects three things.

1. **Serve-read deadline.** A motherboard aux read launches its PSRAM read at `sss_en` only if the FSM is in `S_IDLE` or `S_RMW_WRITE_ISSUE` (`psram_simple.sv:347-363`). Otherwise it counts a deadline miss and returns stale data (`:365-372`). The bounded window guarantees idle by the next `sss_en`.
2. **Write-queue drain rate.** One full RMW per cycle matches the maximum push rate of one captured write per cycle, with depth 8 (`:145`).
3. **Order between clients**, by fixed priority.

While `vtw_bus_owned` is high, item 1 does not apply, because `serve_read_start` is gated off (V, `:134-135`). No other PSRAM operation has a deadline. So the rule can be relaxed safely, subject to three conditions.

| Condition | Change |
|---|---|
| Write queue must still drain | Keep the priority order in `S_IDLE`. RMW is 55 clocks, so it still fits once per Apple cycle. |
| Ownership boundary | Add `relax_tail_q`: keep `serve_read_start` suppressed after `vtw_bus_owned` falls until the FSM is back in `S_IDLE` (at most 31 clocks). |
| Windowed rule returns at once when ownership ends | Gate the relaxed path on a registered copy of `vtw_bus_owned`. |

The boundary is safe because the engine holds /DMA for one full Apple cycle after it stops driving (V, `vtw_bus_engine.sv` `S_RELEASE`, about `:924-939`), so no CPU consumes a serve in that tail.

**Exact edit** in `psram_simple.sv:437`: replace the condition with

`(relax_q || (admit_armed_q && admit_window_q != 0)) && !serve_read_start`

where `relax_q <= vtw_bus_owned && relax_en`. `relax_en` is a new card-control bit so the change can be switched off in the field. Cost is about 10 LUTs and 3 flip-flops (A).

**Write capture and RMW under load.** Posted SHR writes are captured and drained by RMW (V, `:136`, `:382-390`). During a blit each Apple cycle carries one 55-clock RMW, which leaves about 75 clocks: two line fills per Apple cycle instead of one.

**Assumption to assert in simulation:** captured writes during a session only land in bank 1. The core posts only when its private decode is bank 0 or 1 (V, `vtw_core_top.sv:565-569`). The capture side decodes with the motherboard-tracking bank register, so this relies on the existing ordering of `$C071/$C073` against posted writes. Add `assert !(vtw_bus_owned && wq_push_now && write_pending_addr_q[23:16] > 8'd1)`.

**Side benefit:** PS DMA is admitted back to back as well, so a 504-byte memory API chunk drops from about 63 Apple cycles to about 63 × 31 clocks, roughly 15 µs (A).

## 4. Cache design

New module `hdl/apple/vtw_rw_cache.sv`. It replaces `rwc_valid_q`, `rwc_dirty_q`, `rwc_line_q` and `rwc_data_q`. The line port to `psram_simple` is unchanged for (a).

### Geometry

| Parameter | (a) PSRAM | (b) DDR |
|---|---|---|
| Line size | 8 bytes, one PSRAM op | 32 bytes, one 4-beat AXI burst |
| Default size | 32 KB, 4096 lines | 32 KB, 1024 lines |
| Larger trial | 64 KB, 8192 lines | 64 KB, 2048 lines |
| Associativity | direct-mapped | direct-mapped |
| Index | `offset[14:3] ^ hash(bank_sel)` | `offset[14:5] ^ hash(bank_sel)` |
| Stored tag | `bank_sel[7:0]` + `offset[15]` + V + D = 11 bits | 8 + 1 + V + 4 per-word dirty = 14 bits |
| Data RAM | simple dual port, 64 bits, 8 byte enables | same |
| BRAM tiles, 32 KB | 8 data + 2 tag = 10 (120 of 140) | 8 + 1 = 9 |
| BRAM tiles, 64 KB | 16 + 3 = 19 (129 of 140) | 16 + 1 = 17 |
| LUTs / flip-flops (A) | about 400–500 / 400 | add about 300 / 350 for AXI master and arbiters |

- The index is a function of the physical line, and the victim's address is rebuilt from index and tag. Each physical line has exactly one logical address (V from `globals.sv:271-277`: LC bank-1 `$Dxxx` is the only user of offset `$Cxxx`), so there is no aliasing.
- Start at 32 KB. The build that added 18 tiles first came in at −0.063 ns (V, `README_TURBO.md:149-152`).
- Two-way associativity is a later parameter, not stage 1.
- Invalidate-all is a sweep of the tag RAM: 4096 clocks, about 31 µs. Run it at session start and after an ARM flush, while the core is held.

### Pipeline, built to avoid the existing critical path

| Stage | State | Action |
|---|---|---|
| A | `X_TURBO_DONE` (TURBO) or `X_ROUTE` (classic) | Present the index to tag and data RAM. Address comes from registered `cycle_xl_decoded_q`; enable comes from a one-hot state bit. |
| B | `X_RW_LOOKUP` | Capture RAM outputs in `rwc_tag_rd_q` and `rwc_word_q` (or use the BRAM output register). |
| C | `X_RW_CHECK` (new) | Compare registered tag, register `rwc_hit_q`, load `core_data_in_q` from the lane mux. On a write hit, issue the byte-enabled BRAM write and set dirty. |
| D | `X_RW_DONE` | `core_en`. |

Rules:
- No BRAM control input may depend on the core's live outputs or on the hit compare in the same clock.
- In TURBO, go from `X_TURBO_DONE` straight to `X_RW_LOOKUP`. Skipping `X_ROUTE` is already done for TURBO hits and TURBO shadow misses (V, `:1968-1971`).
- The 64-bit `rwc_data_q` register with its lane-decoded enable goes away, and with it the +0.169 ns path.
- Register `rw_resp_rline` before writing it to the BRAM.
- Add every new state to `rw_flush_unsafe` (`:1604-1611`). Keep `X_RW_DONE` in `video_sync_core_idle` (`:1421-1428`).

### Write policy and miss handling

- Write-back with write-allocate, as now. Write-through would cost a 24-clock PSRAM write per store and gains nothing, because flush and hold already provide coherence.
- One-entry victim buffer (`vb_valid_q`, `vb_addr_q[20:0]`, `vb_data_q[63:0]`). On a dirty eviction, fill first and write the victim back in the background. A miss that matches `vb_addr_q` waits for the write-back.
- Idle cleaner (stage 3): write dirty lines back when the PSRAM is idle, so flush points stay short.

### Latency in fabric clocks (TURBO)

| Case | Today | (a) relaxed PSRAM | (b) DDR over AXI HP |
|---|---|---|---|
| Read hit | 5 | 5 (4 in the fast variant) | same |
| Write hit | 5 | 5 | same |
| Read miss, clean victim | 35 best, 131 sustained | about 35–37 | about 18–30 (A, must be measured) |
| Read miss, dirty victim | about 261 | about 37 with victim buffer; next miss may wait up to 24 | about 20–32 |
| Write miss | as read miss | as read miss | as read miss |

- In the 33 MHz mode the hit goes from 4 to 5 clocks. That is a regression of one clock.
- The fast variant compares on the raw BRAM output in stage B. Try it only after stage 2 closes timing.
- (b) numbers assume 10–20 clocks from AR to the first R beat plus 3 more beats. Nothing in the repo measures this. Add a counter.

## 5. Backing store (b): AXI HP ports

All four ports are enabled and clocked by FCLK0 (V, `scripts/create_project.tcl:166-169`, `:644-649`).

| Port | Read | Write |
|---|---|---|
| HP0 | framebuffer reader (`appletini_yarz_top.sv:869`) | `apple_cycle_egress` (`apple_top.sv:1038`) |
| HP1 | `apple_dma_engine` (`apple_top.sv:1811-1812`) | same |
| HP2 | Disk II audio samples (`apple_top.sv:1684-1694`) | SDD egress (`apple_top.sv:1127`) |
| HP3 | `disk2_ddr_bridge`, single beat (`apple_top.sv:1308-1320`) | same |

- No port is free in both directions.
- `axi3_read_arbiter_2` exists but is not instantiated (V: only `hdl/hdl_sources.txt:12` and a string check in `scripts/test_phasor_card.py:502`). There is no write arbiter; a new `axi3_write_arbiter_2` is needed.
- Share HP3 with `disk2_ddr_bridge`, cache on `in0`. `disk2_ddr_bridge.sv` is the precedent for line-granular DDR access with `WSTRB`.
- A (from the Zynq manual, not the repo): HP0/HP1 share one DDR controller port and HP2/HP3 share another. HP3 avoids the framebuffer reader's traffic. HP1 is the alternative.
- DDR region: 8 or 16 MB, mapped non-cacheable. `0x32000000–0x3BFFFFFF` looks free from `smartport_service.c:106-116` and `compositor_layout.h:31-56`, but I did not check the linker script (A).
- Timing: put register slices on AR, AW, W and R.

## 6. Flush points and coherence

| Event | (a) PSRAM | (b) DDR |
|---|---|---|
| Fabric reset | Tags invalid by sweep; nothing to write | same |
| Core into reset (RES#, ARM re-hold, session end) | Scanner writes all dirty lines; generalises `:1783-1792`. An abandoned fill must not set V. | same, as AXI write bursts |
| Handback to the motherboard CPU | Flush, then invalidate when clean (as `:1793-1795`). Hold /DMA in `S_RELEASE` until `rwc_flush_busy` is low. | Flush to DDR. PSRAM does not hold the data. |
| SmartPort DMA, memory API | Existing `arm_rw_flush_req`; `arm_rw_flush_done` only after all dirty lines are written and the tags are swept | same, then the ARM uses `memcpy` on the DDR region |

- Worst-case flush at 32 KB: 4096 lines × 24 clocks is about 0.74 ms relaxed, or about 4 ms at one line per Apple cycle. The ARM hold timeout is 100 ms (V, `memory_api_hw.c:17`). Add a dirty counter and a per-64-line summary so the scan skips clean groups.
- (a) needs no ARM software change. The PS DMA path, the 504-byte chunking and the `physical >= 0x800000` check (V, `memory_api_hw.c:149-174`) keep working.
- (b) needs a backing-store selector in `memory_api_hw.c`, `smartport_service.c:462-535` and `:910-943`, the UART DMA path and `psram_bench.c`.
- The ARM caches are only an issue for (b): map non-cacheable, as `disk2_service.c:167` does.

### vTW off

- (a): unchanged. The motherboard CPU reads aux and RamWorks through the PSRAM serve path, and PSRAM is the single store.
- (b): the serve path cannot use DDR safely, because it has a hard deadline (`SERVE_LATE_THRESHOLD` = 75, `psram_simple.sv:246`) and AXI latency is not bounded. Either copy 8 MB at session boundaries (about 0.25 s relaxed, about 1 s windowed; A) or state that RamWorks contents do not cross a vTW on/off change. Base aux already behaves that way, since only video-window writes reach PSRAM bank 1.

## 7. 16 MB and 8-bit bank numbers

- **Register side (V):** `sw_ramworks_bank` is 7 bits and writes with bit 7 set are ignored (`soft_switch_manager.sv:141-144`). `bank_sel = bank + 1` (`globals.sv:251`). `decoded_addr[31:24]` carries the region tag (`globals.sv:125-126`), so a 9-bit `bank_sel` collides with it. `addr_decode` is 24 bits (`globals.sv:137`), and `sp_sss_snapshot` packs 7 bank bits (`vtw_core_top.sv:531-548`).
- **PSRAM capacity:** each line uses 4 bytes per chip at an 8-aligned address, so half of each chip is unused (inferred from `psram_driver.sv:456-466`). 16 MB fits by putting `bank_sel[7]` on chip address bit 2.
- **Assumptions:** the chips are 8 MB each (`AGENTS.md:21`) and ignore address bit 23, which would explain why bank 128 works today (`psram_simple.sv:124-125`).
- **Cost on PSRAM:** 22-bit line addresses in `psram_simple`, `apple_dma_engine` (`dma_line_addr[20:0]`), `ps_dma_command` and the PS DMA library. It is a wide change.
- **Cost on DDR:** address arithmetic only.
- **Software-visible changes:** sizing probes find 255 extra banks; values `$80–$FF` select banks instead of being ignored; the SmartPort snapshot layout changes; the memory API bank range changes. Do it last.

## 8. Interaction with the TURBO caches

- Stage 1: no change. The new cache is physically tagged, so mapping changes do not invalidate it.
- A RamWorks hit is 5 clocks against 2 for a TURBO shadow hit. Hot code and tables should stay in main and base aux.
- Later option: let the word cache take read fills from the RamWorks cache. This needs the physical tag widened from `phys[17:8]` to `decoded[23:8]` and a snoop on RamWorks writes. It is only worth it if bank changes stop invalidating the TURBO caches.

## 9. Staged plan and tests

| Stage | Work | Tests |
|---|---|---|
| 0 | Counters: hits, misses, miss wait clocks, evictions. The eight `turbo_perf` slots are taken (`:1630-1641`); add a second vector. | Baseline on the Doom port |
| 1 | Relaxed admission and `relax_tail_q` in `psram_simple.sv` | Extend `tb_psram_simple.sv`: the MGTK pattern (`:296-330`) with ownership toggling at random phases, zero deadline misses, zero drops, bank-1 assertion |
| 2 | `vtw_rw_cache.sv`, new `X_RW_CHECK`, flush scanner, tag sweep | New `tb_vtw_rwcache.sv` with a reference-memory scoreboard, random line latency, reset during fill. Existing checks in `tb_vtw_turbo.sv:550-619` and `tb_vtw_system.sv` must pass. |
| 3 | Victim buffer, idle cleaner, /DMA release gated on flush | Re-access of the victim line, flush during write-back, `scripts/test_memory_api_hw.py` |
| 4 | Timing trials: 4-clock hit, 64 KB, two-way | Same benches; promote only at +0.200 ns or better |
| 5 | (b): AXI master, HP3 arbiters, PS selector | AXI slave model with random ready and latency; arbiter test against `disk2_ddr_bridge` |
| 6 | 16 MB | RamWorks contract test with 8-bit banks |

Stage 1 is useful on its own: with the present single line, sustained misses already fall from about 131 to about 35 clocks.

## 10. Expected effect on random-access code

These figures use hit rates I assumed, not measured. Stage 0 exists to replace them.

| Configuration | Assumed hit rate | Average clocks per extended access |
|---|---|---|
| Today, single 8-byte line | 40% | about 80 |
| Stage 1 only | 40% | about 23 |
| (a), 32 KB cache | 90–97% | about 6–8 |
| (b), 32-byte lines | 93–98% | about 5.5–7 |

- (a) gives roughly a tenfold gain on extended-memory accesses over today.
- (b) adds little on top for random access. Its advantage is sequential data, since a 32-byte fill costs about the same as an 8-byte one.
- Texel reads during an SHR blit compete with the RMW drain under (a) and do not under (b). If stage 0 shows that contention dominating, that is the case for stage 5.