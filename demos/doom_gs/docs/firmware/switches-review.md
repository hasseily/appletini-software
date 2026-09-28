# Option 2: bank and memory-mapping soft switches that do not touch the bus, flush the video mirror, or invalidate the TURBO caches (review)

# Adversarial review: Option 2 (quiet mapping switches + mapping-tolerant TURBO caches)

All paths are relative to `<appletini-one>`. Nothing was simulated or synthesised; every finding comes from reading the RTL.

## 0. Bottom line

- **Part B (caches survive mapping changes)** is sound. I found no correctness hole. It saves only about 7% of the sequence on its own.
- **Part A (quiet switches + reconciler)** has one blocker (a deadlock in O2) and five major gaps. All are fixable.
- The plan's RTL citations are accurate. The errors are in the new design, not in the reading of the existing code.
- A smaller design gets most of the benefit: keep RAMWRT on the bus, and stop treating physical RAMRD/ALTZP/LC as state that must be replayed.

## 1. Findings

| # | Severity | Finding | Evidence | Correction |
|---|---|---|---|---|
| F1 | **Blocker** | O2 deadlocks in TURBO direct video. The plan stalls the core in `X_POST_STALL` until the reconciler fixes the steer, and starts the reconciler on `video_sync_bus_idle`. That signal counts `X_POST_STALL` as idle only when `!video_selected`. With direct video on, the reconciler never starts. | `vtw_core_top.sv:1421-1430`; `video_fast_req` at `:1370-1371` | Give the reconciler its own idle term that accepts `X_POST_STALL` unconditionally. The shadow write is already committed at `X_ROUTE` and the staged tuple is in no queue. Keep `!video_active_pending_q`, `video_post_idle`, `!req_inflight_q`. |
| F2 | **Major** | O1 covers only `$Cxxx`, but there is a non-`$Cxxx` bus route. A write to `$D000-$FFFF` with private LC write-protect goes to `APPLE_ROUTE_BUS` and then `X_BUS`. If physical LC is stale (write-enabled) and physical ALTZP is 1, `psram_simple` captures that write into PSRAM bank `phys_bank+1`; write capture is not gated by `vtw_bus_owned`. This corrupts RamWorks data. It also contradicts the plan's claim that physical ALTZP/LC "steer no data anyone consumes". | `globals.sv:330-334`; `vtw_core_top.sv:1977, 2023-2025`; `psram_simple.sv:136` | When `quiet_en`, complete these writes privately in `X_DEAD` (a write to protected LC is a no-op). Otherwise extend O1 to every `xl_is_bus` cycle. |
| F3 | **Major** | Session disable is not covered. `vsss` is held in reset and the engine is disabled when `!enable && !video_mirror_pending`. If `enable` drops with `sw_dirty_q` set, the private state is wiped before replay and the engine cannot issue cycles. | `vtw_core_top.sv:418, 732`; `vtw_bus_engine.sv:811-831` | Add `sw_dirty_q \|\| sw_sync_active` to `core_ab.res` and `engine_enable`, exactly as `video_mirror_pending` is. Add `!enable` handling to the reconciler clear. |
| F4 | **Major** | Two FSMs share one request mux with no mutual exclusion. `vtw_video_bank_sync` saves and restores *physical* RAMWRT/PAGE2. The plan's O4 needs the reconciler to trigger a bank flush and then wait, but no handshake is specified. `capture_sss` is overridden only on `vtw_video_sync_active`. | `vtw_video_bank_sync.sv:89-98, 143-166`; `vtw_core_top.sv:765-775`; `apple_top.sv:981-987` | Reconciler start requires `!video_sync_active`. Bank-sync `start` requires `!sw_sync_active`. The reconciler sits in a `WAIT_FLUSH` state, not on the bus, while the flush runs. Add that state to the list. |
| F5 | **Major** | Timing risk of stage 4 is understated. O2 ANDs a new term into `video_start_ready`, `core_post_accept` and `arm_post_ready`. That is the "TURBO video admission" path family that produced -0.063 ns and needed the September rework to reach +0.205 ns. | `README_TURBO.md:149-151, 159-166, 231-237`; `vtw_core_top.sv:1365-1379` | Compute `video_steer_ok` in `X_ROUTE` from registered bits (`xl_decoded[16]`, private and physical RAMWRT, `bank_phys_zero_q`) and register it for use in `X_POST_STALL`. Better: drop the RAMWRT half entirely (see section 4). |
| F6 | **Major** | `quiet_en` depends on `eff_mode`, which changes per cycle (`slow_active`, `cycle_usb_native_q`, `cycle_d2_native_q`, `c074_q`). The quiet decision would flap inside one program. The plan classifies in both `X_VIDEO_WAIT` and `X_ROUTE`; they can disagree. The dependency is unnecessary: `X_DEAD` already honours `pace_ok`. | `vtw_core_top.sv:1153-1162, 1521` | `quiet_en = cfg && (speed_mode == SPEED_TURBO) && !host_is_iiplus`. Classify once and register `cycle_quiet_q`. Keeps the `eff_mode` cone out of the `X_ROUTE` next-state logic. |
| F7 | Minor | "Reuse `floating_scan_issue` … +2 clocks" is not derivable. That signal and its latch are keyed to `ab_read.serve_en`/`data_en` of a real cycle in `X_BUS`. | `vtw_core_top.sv:1296-1304, 1329-1334` | A new latch is needed. `floating_scan_addr` is combinational from `video_line/video_cycle`, so roughly 3 clocks is achievable, but it is new logic. |
| F8 | Minor | Each quiet access is 4 clocks, not 3, whenever `video_mirror_pending` or `sw_dirty_q` is set. That is the normal case while rendering. | `vtw_core_top.sv:1949-1950` | Whole-sequence estimate rises by about 3 clocks. Immaterial. |
| F9 | Minor | Reconciler size omits un-trimming `video_physical_ssm`. Today only three of its outputs are consumed. | `vtw_core_top.sv:438` | Add about 15 FFs and 20-30 LUTs. Total Part A is closer to 250 LUTs, 100 FFs. Still 0 BRAM. |
| F10 | Minor | The `$C08x` "constant" differs from ONE//e, where unclaimed `X_BUS` reads return the scanner byte. | `vtw_core_top.sv:2140-2142` | Document, or do F7. |
| F11 | Minor | Part B removes invalidation but not conflict misses. The word cache is direct-mapped on logical address (32 words) and the map has one entry per logical page per direction. Code alternating main/aux at the same logical address will thrash. | `vtw_turbo_cache.sv:56-67` | None needed for the Doom loop. State it in the docs. |
| F12 | Minor | The back-to-back `STA $C003` case probably misses the 15-clock window: `X_BUS_DONE`, three refetches after invalidation (4 clocks on the first miss), `CAPTURE`, `ROUTE`, engine latch. | `vtw_core_top.sv:1964-1972, 2114-2123` | Treat 262 clocks as the typical figure. "Cost today" is nearer 750 clocks. This strengthens the case. |
| F13 | Minor | Capture record fields: only the accessor definitions exist in the PS frontend headers. I found no `.c` consumer of `ace_sw_ramrd/ramwrt/altzp` apart from `vtw_service.c` status printing. | `ps_sources/frontend/apple_cycle_egress.h:193-195` | Plan's assumption looks right. Not exhaustively verified. |
| F14 | Minor | The brief's "157 taps" is a stale comment. The real figure is 131 fabric clocks per Apple cycle. | `psram_simple.sv:238`; `README_VIRTUAL_TRANSWARP.md:211-212`; `apple_bus_wrapper.sv:120, 136` | Plan's 131 is correct. Do not scale by 1.2. |

### Hazards checked and found acceptable

- **Reset:** both trackers reset on `!ab_read.res` to the same values, RamWorks bank to 0 (`soft_switch_manager.sv:255-285`).
- **Handback:** it is only via Ctrl-RESET with vTW disabled (`README_VIRTUAL_TRANSWARP.md:109, 116`), so there is no mid-flight handback to reconcile.
- **IRQ:** `$C011-$C01F` reads are served from `vsss` on physical hosts (`vtw_core_top.sv:577-580, 631-639`).
- **SmartPort:** the fast port latches the private snapshot (`smartport_card.sv:502-503`).
- **LC replay table:** matches the tracker equations (`soft_switch_manager.sv:193-204`).

## 2. Claims confirmed

- Every line citation in plan sections 1.1, 1.2 and 1.3 matches the snapshot.
- `$C0xx` always routes to the bus; none of the six `X_ROUTE` shortcuts covers the switch writes.
- The private tracker applies at `X_ROUTE`, before the bus cycle.
- `video_exposure_access` decode is as described; `$C002-$C00B` writes are not exposure accesses.
- `TranslateState` is 19 bits; any change clears all 64 map and 32 word valid bits.
- The word tag already stores `phys[17:8]`; the read hit compares only the logical tag; the snoop compares both.
- The 32 read-side map entries are filled but never consulted.
- Shadow layout makes `{phys[17], phys[16], phys[12]}` sufficient to identify the physical page given the logical page (`vtw_shadow.sv:30-66`, `globals.sv:273-277`).
- `fast_write` depends only on logical page, aux bit and policies that keep their own invalidate terms.
- `psram_simple` suppresses read serving but not write capture while `vtw_bus_owned`.
- `drive_en` to `data_en` is about 116 clocks.
- `perf_count[5]` counts invalidations.
- All named testbench tasks exist in `hdl/sim/tb_vtw_turbo.sv`.
- `$C08x` is outside `sd_slot_io`.

## 3. Assumptions I could not verify

- Whether the PSRAM copy of base aux video bytes (written by capture of posted writes) has any consumer during or after a session. If not, the bank half of O2 can be replaced by gating.
- Whether real bus-snooping cards care about physical RAMRD/ALTZP/LC. I believe they track only RAMWRT/80STORE/PAGE2.
- The Doom code must run from main LC or main ZP/stack. With RAMRD on and bank N selected, code in `$0200-$BFFF` is fetched from bank N. The plan's four-instruction sequence only works under that constraint.

## 4. Corrected plan summary

**Stage 1, Part B as written.** Add a 3-bit space compare and a registered `cycle_cacheable_q` to `turbo_hit` and delete the mapping term from `turbo_invalidate`. About 8 FFs, 15 LUTs. Medium timing risk on `turbo_hit → turbo_complete → core_en`; all operands registered; mark new registers `DONT_TOUCH`.

**Stage 2, quiet switches, reduced scope.**

- Quiet set: RAMRD (`$C002/3`), ALTZP (`$C008/9`), `$C08x`, and `$C071/$C073` when `ramworks_en`.
- RAMWRT stays on the bus. The Doom loop holds it constant, and this removes the RAMWRT half of O2, O3 and most of stage 4.
- `quiet_en` uses `speed_mode`, not `eff_mode`. Register `cycle_quiet_q` once.
- Complete LC-protected `$D000-$FFFF` writes privately (F2).
- Quiet accesses bypass the active-pending barrier and the exposure flush (plan O5, unchanged).

**Stage 3, minimal reconciler.**

- Fields: bank, RAMRD, ALTZP, LC. States: `IDLE, PICK, WAIT_FLUSH, REQ, WAIT, LC2_REQ, LC2_WAIT, FINISH`.
- Own idle term that accepts `X_POST_STALL` (F1).
- Mutual exclusion with `vtw_video_bank_sync` (F4).
- `sw_dirty_q` keeps `engine_enable` and `core_ab.res` alive (F3).
- Triggers: before any non-quiet bus cycle; before an aux posted write if `bank_phys != 0`; on `!core_run`, `arm_rw_flush_req`, `!quiet_en`, `!enable`.
- The aux-write gate is one registered bit, computed in `X_ROUTE`.

**Size:** about 250 LUTs, 100 FFs, 0 BRAM.

**Expected result:** far access about 40 clocks on a RamWorks line hit and about 135 on a miss, against roughly 620-750 today. After this, the PSRAM admission limit of one operation per Apple cycle dominates.

**Alternative to weigh first:** a separate read-bank register, so RAMRD and RAMWRT use different banks. The switch write stays a real bus cycle, so both trackers follow it and nothing diverges. It removes all switch accesses from the inner loop and needs no reconciler. The cost is one extra mux level on seven bits inside `translate_apple_addr`, on the capture path.

## 5. Verdict

Build stage 1 now; it is low-risk and a prerequisite for everything else.

Do not build Part A as written. Build the reduced version in section 4 only after comparing it with the split read-bank register, which I think is the better first step for Doom. Either way, random far reads will still cost about 1 µs each until the single-line RamWorks cache is replaced, so that option deserves equal priority.