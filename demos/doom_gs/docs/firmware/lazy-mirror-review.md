# Lazy mirror class for Super Hi-Res writes (review)

# Adversarial review: Lazy mirror class for Super Hi-Res writes

Nothing was simulated or built; every finding comes from reading the F1.2.1 snapshot. Paths are relative to `<appletini-one>/`. `core_top` = `hdl/apple/vtw_core_top.sv`, `coalescer` = `hdl/apple/vtw_video_coalescer.sv`. **V** = verified in the RTL or source, **A** = my inference.

## 0. Bottom line

- The idea is sound: the renderer never depends on the mirror, and the flag plumbing in `core_top` is mostly right.
- The spec's RTL citations are accurate, with two off-by-one line ranges. The errors are in the new design.
- One blocker: the 2 KB group bitmap loses bytes.
- Six major gaps: a flush can now run inside an ARM hold, PS timeouts, the port A change, the understated admission timing risk, unflushed resets of `shr_selected_q`, and a simpler coalescer design that was not considered.
- A smaller design gives the same benefit with no new coalescer state, no new FSM states and no logic on the shadow BRAM address.

## 1. Findings

| # | Sev | Finding | Evidence | Correction |
|---|---|---|---|---|
| F1 | **Blocker** | The group bitmap loses bytes. `next_page_q` free-runs in `SELECT_PAGE`, so a flush can enter a group at page 3. The spec clears the group bit when page 7 is selected, so pages 0-2 are never scanned. Their `dirty_mem` bits stay set, `lazy_drained` reports true, and the bytes never reach the motherboard. | V `coalescer:119-124` (increment every clock), `:45-48`, `:102-105` | Drop the group bitmap and use F2. If it is kept, clear a group only after a pass that selected its page 0. |
| F2 | **Major** | A simpler coalescer was not considered. Lazy pushes can use the existing inactive path (`write_active=0`, sets `page_dirty_q` only). The lazy range is fixed (pages `$20-$9F` of bank 1, plus bank 0 in paged mode), so a static range mask separates lazy from non-lazy pages. | V `coalescer:106-110`, `:54-64`; `vtw_video_policy.sv:25-31` | Two level inputs, `lazy_mask_en` and `lazy_main`. Mask the range out of `drained`, `bank_drained` and flush-mode `select_page` while `lazy_mask_en`. No new bitmap, no `write_lazy`, no new states. About 15 LUTs, 2 FFs. Mixed pages become harmless, so the single-class invariant is not needed. |
| F3 | **Major** | A flush can now run inside an ARM hold. Today the hold completes only after the mirror is empty, and ARM posts are refused while it is not, so no flush ever overlaps a hold. With lazy bytes left pending, an ARM-side trigger (speed change, overlay arm, `ramworks_en`, `0x35` write) starts a flush while CPU0 owns memory. The spec also drops `arm_post_ready` on `video_lazy_req_q`, so a SmartPort post span in progress fails its accept count. | V `core_top:1604-1611`, `:1481-1482`, `:1408-1413`; `smartport_service.c:709-721` (64 polls) | Gate promotion and the `arm_post_ready` block on `!rw_hold_q`. `!enable` needs no exception: it clears `rw_hold_q` (V `core_top:1834-1835`). |
| F4 | **Major** | Shadow read on port A puts new logic on the core's memory path, which the brief names as the risk area. It also adds two FSM states, a port B collision comparator and a 17-bit address register. | V `core_top:1312-1319`; `vtw_shadow.sv:121-138` (36 RAMB36 behind this address) | Replace with a `KEEP_LAZY` bit in the hold request (`CARD_CTRL_VTW_RW_FLUSH_REG`). The ARM sets it only when no destination span lies in a base-bank lazy range; it already knows every span. Bit clear means flush as today, so old PS code fails safe. `data_mem` stays the flush source. Keep the shadow read as a later option if measurement shows holds that overlap SHR memory are frequent. |
| F5 | **Major** | PS timeouts are not sized for a full-frame flush. The SmartPort hold wait is a poll count (16384), the post drain wait is 2 ms, and the memory API hold is 100 ms. A paged flush is 64 ms plus steering. With lazy, a full dirty frame is the normal state, so any hold that must flush will routinely time out SmartPort and fall back to the byte loop. | V `smartport_service.c:81-85`, `:446`; `memory_api_hw.c:17` | Make the SmartPort flush wait time-based, at least 150 ms. Raise `MEM_HOLD_TIMEOUT_US` to 200 ms. |
| F6 | **Major** | Timing risk is understated. `core_post_accept`, `core_post_blocked` and `arm_post_ready` are the admission family that the September work had to rework to reach +0.205 ns. The spec adds a second flop input to each. The new barrier term is a combinational 16-bit address decode plus `cycle_wdata_q[7:6]` into `video_barrier`, which feeds the `X_CAPTURE` hold and `eng_req_valid`. | V `README_TURBO.md:231-237`; `core_top:1374-1378`, `:1414-1415`, `:765-768` | Add one flop `video_post_block_q` (next-state OR of `video_mirror_mode_q` and the gated lazy request) and substitute it in the three admission expressions, so the input count is unchanged. For the barrier, hold the first `X_VIDEO_WAIT` clock unconditionally while lazy is pending, and register `lazy_exposure_q` in that clock. Cost: one fabric clock per `$Cxxx` access. |
| F7 | **Major** | `shr_selected_q` resets are not all flush events. `!fake_shr_allowed` clears it without a flush. | Spec §1; `apple_top.sv:997` | Register `fake_shr_allowed` and add its change, and the `lazy_en` change, to `video_external_policy_change` with `turbo_*_q`-style delay flops (V pattern at `core_top:1186-1200`). With F2 a missed case is no longer a correctness problem. |
| F8 | Minor | Two flushes where one would do. `video_full_flush` rises with `video_lazy_req_q` before promotion, so bank sync can start a non-lazy flush, then a second one after promotion. Each saves and restores RAMWRT/PAGE2. | V `core_top:1433`; `vtw_video_bank_sync.sv:89-98` | Gate `start` with `!(video_lazy_req_q && !video_lazy_flush_q)`. |
| F9 | Minor | Writing aux `$9DF8` with 0 or 1/2 changes `post_main_wide_eff`, which is a policy change. It will flush the whole pending frame (up to 32 ms). Software that toggles it per frame loses the benefit. | V `core_top:1877-1882`, `:1404-1407` | Document. Measure with a paged demo before promising a gain there. |
| F10 | Minor | Cost numbers disagree. The summary says 90 FFs; the table sums to 139 (75 without counters), and 156 LUTs. All eight `perf_count` slots are taken, so the two counters need new registers and a new readback address. | V `core_top:1622-1641` | Use the numbers in section 3. |
| F11 | Minor | Citation drift. The fake-SHR comment is at `soft_switch_manager.sv:75-77`, not 74-76. The PSRAM serve gating is `psram_simple.sv:133-136` with the `vtw_bus_owned` term on 135. | V | Fix in the doc. |
| F12 | Minor | The contract text changes and the spec lists only one. `README_TURBO.md:120-121` says ARM holds drain the deferred banks first. `README_MEMORY_API.md:189-191` says the hold drains pending mirror work. | V | Both must be rewritten. With `KEEP_LAZY` the memory API statement stays true for any destination in a lazy range. |
| F13 | Minor | "Eventual" has no bound. A program that stays in SHR and never triggers a flush never updates the motherboard. Apple reset discards a full frame. | V `core_top:1448`, `:1459` | Author decision; see questions. |
| F14 | Minor | ONE//e is unverified in the spec and I did not verify it either. | — | Keep `lazy_en` off in ONE//e profiles until tested. |

### Hazards checked and found acceptable

| Hazard | Result |
|---|---|
| Renderer recovery after a capture gap | Resync does not reload from motherboard or PSRAM memory. `g_aux_bank` is written only by egress records (V `apple_cycle_egress.c:270-280`; grep found no other writer). |
| Apple reset | `shr_capture_active_q` clears on `soft_reset = !ab_read.res` (V `apple_cycle_capture.sv:162`, `apple_top.sv:990`), so core and capture agree after reset. |
| False "not selected" | Safe direction: writes become active, which is today's behaviour. |
| Interrupts | No new hazard. With only lazy bytes pending, a handler's `$C0xx` access is never held by the barrier. |
| Session disable | `engine_enable` and `post_clear` follow the pending flag (V `core_top:732`, `vtw_bus_engine.sv:324-330`, `:811-831`), so substituting `video_any_pending_q` keeps the bus owned. |
| A2Li holes | In-band renderer signal, read from the renderer's shadow (V `apple_cycle_renderer.c:2283-2284`). With F2 the holes can stay active at no cost. |
| Deadlock: `X_POST_STALL` when TURBO is left | Counted as idle when `!video_selected` (V `core_top:1428`). No deadlock. |
| Deadlock: renderer backpressure at trigger | Core waits in `X_POST_STALL` for `video_record_ready`, flush waits for the core. Same as today's full flush. |
| RamWorks bank | Lazy bytes accumulate only under bank 0, because aux writes under bank N route to RamWorks, not the posted path (V `core_top:565-569`). The `$C071/$C073` flush is required and sufficient. |
| `$C069` | Not in `video_exposure_access` (V `core_top:1390-1401`). No flush. |

## 2. Claims confirmed

- Every `core_top` line citation in spec sections 1, 2, 3.2 and 5 matches the snapshot.
- `$C029` is an exposure access only on write (`:1398`). `$C074` is decoded at `X_CAPTURE` from live outputs (`:1253`, `:1866`). `$9DF8` is tracked at `X_ROUTE` (`:1877-1882`).
- `cycle_video_force_active_q` covers overlay and II/II+ (`:1931-1932`) and feeds `overlay_match` (`:507`).
- `video_direct_active` suppresses capture only during mirrored posted cycles (`:1384`; `apple_cycle_capture.sv:101,110`).
- Six fabric clocks per SHR write in TURBO: `X_CAPTURE`, `X_TURBO_DONE`, `X_ROUTE`, `X_POST_STALL`, `X_MEM_CAPTURE`, `X_MEM_DONE`.
- Capture FIFO depth 4096 with direct accept below 4064 and never on `data_en` (`apple_cycle_capture.sv:56, 298-301`).
- `CARD_CTRL 0x35` holds only bit 0 today (`apple_top.sv:2691, 2831`); bit 1 is free.
- Egress counters at `0x27` and `0x2A` exist (`apple_top.sv:2816, 2819`).
- Bank sync never touches 80STORE or the RamWorks bank (`vtw_video_bank_sync.sv:5-7`, state list `:31-36`).
- Handback is by Ctrl-Reset with the vTW disabled (`README_VIRTUAL_TRANSWARP.md:109, 116`).
- 0 BRAM is correct for both the spec and the corrected design.
- Worst-case flush arithmetic: 32,768 bytes at 131 clocks is 32 ms.

Not checked: `apple_cycle_egress.sv` burst structure, the DDR ring size, the AXI figures, and all throughput estimates marked A in the spec.

## 3. Corrected specification

**Class.** A write is lazy when `lazy_en && shr_selected && !force_active && graphics_range && (is_aux || post_main_wide) && !legacy_metadata`. `mirror_active` is the existing expression AND NOT lazy. Register `cycle_video_lazy_q` at `X_ROUTE` beside `core_top:1976`.

**`shr_selected_q` (`core_top`).** Written at `X_ROUTE` when `core_active && xl_is_bus && !cycle_rw_q && cycle_addr_q==16'hC029`; value `cycle_wdata_q[7:6]==2'b11`. Cleared on `!rstn`, `!ab_read.res`, `!core_res_n`. Effective value is ANDed with registered `fake_shr_allowed_q`.

**Coalescer.** Lazy pushes use the existing inactive path. New inputs `lazy_mask_en`, `lazy_main`. While `lazy_mask_en`, pages `$20-$9F` of bank 1 (and bank 0 when `lazy_main`) are excluded from `drained`, `bank_drained` and flush-mode `select_page`. New output `lazy_range_empty`. Pre-register the range test beside `next_page_q`. No new states or memories.

**Flags (`core_top:1458-1477`, reset on `!rstn || !ab_read.res`).**

| Flop | Set | Clear |
|---|---|---|
| `video_lazy_pending_q` | `video_fast_accept && cycle_video_lazy_q` | `lazy_range_empty && video_post_idle && !video_sync_active` |
| `video_lazy_req_q` | pending and trigger | with pending |
| `video_lazy_flush_q` | `req && video_post_idle && !video_sync_active && !rw_hold_q` | with pending |
| `video_any_pending_q` | next-state OR of mirror mode and lazy pending | same |
| `video_post_block_q` | next-state OR of mirror mode and (`req && !rw_hold_q`) | same |
| `lazy_exposure_q` | decode of the registered tuple in the first `X_VIDEO_WAIT` clock | next `X_CAPTURE` |

`lazy_mask_en = video_lazy_pending_q && !video_lazy_flush_q`. Promotion also sets `video_mirror_mode_q`; set wins over clear.

**Triggers.** `!video_selected`, `!enable`, `!core_run`, policy change (`post_main_wide_eff`, overlay armed, `ramworks_en`, `lazy_en`, `fake_shr_allowed`), a hold request without `KEEP_LAZY`, and `lazy_exposure_q`: a write to `$C071` or `$C073`, or a `$C029` write with bits 7:6 not `11`.

**Line changes.** `:1949`, `:418`, `:732`, `:1472` use `video_any_pending_q`. `:1374-1378` and `:1481` use `video_post_block_q`. `:1408` ORs `video_lazy_req_q`. `:1414` adds `video_lazy_pending_q && first_wait_clock`. `:1433` start is gated by `!(req && !flush)`. `:1604-1611` adds `video_lazy_req_q`. `:1365` and `:1384` are unchanged.

**Discard events.** Apple reset and `!rstn` clear every flop above and the coalescer.

**PS.** `KEEP_LAZY` bit in the hold request. Time-based SmartPort flush wait of 150 ms; memory API hold timeout 200 ms. `CARD_CTRL 0x35` bit 1 is `lazy_en`, reset 0.

**Cost (A).** About 70 LUTs, 12 FFs, 0 BRAM, plus 64 FFs if two counters are added.

| Path | Risk |
|---|---|
| Admission expressions | Low: same input count |
| `video_barrier` | Low to medium: two flop terms |
| Coalescer reductions and `select_page` | Medium: the scan path was part of the September rework |
| Shadow port A | Untouched |

**Stages.** Each needs a full build against +0.200 ns.
1. `shr_selected_q`, class, `0x35` bit 1; class computed, unused.
2. Mask, flags, `KEEP_LAZY`, timeouts; switch off; regression must match today.
3. Enable by profile key; test Doom and a paged SHR4 demo on a //e.

**Tests.** The spec's list, plus: flush starting with `next_page_q` mid-range; trigger during an ARM hold; hold with and without `KEEP_LAZY`; `$9DF8` toggle; `fake_shr_allowed` change with bytes pending; exactly two wait clocks per `$Cxxx` access.

## 4. Questions for the firmware author

1. Is a user ever watching the motherboard's own video output during a vTW SHR session? If not, the `$C029` leave-SHR flush could be dropped and the bytes left for the next trigger.
2. Does "eventual" need a bound? Options: none, flush at SHR exit and session end only (this design), or a background flush after N idle frames.
3. Apple reset now discards up to a full frame instead of a short backlog. Is stale aux RAM after an in-session Ctrl-Reset acceptable?
4. Can `enable` fall without an Apple reset (menu disable, activity kill, isolation)? If so the `!enable` flush holds the bus for up to 64 ms before release. Is that acceptable to the session logic in `vtw_service.c`?
5. Do any memory API or SmartPort callers write base aux `$2000-$9FFF` often during SHR display (for example loading pictures straight into SHR memory)? If yes, `KEEP_LAZY` will rarely apply and the shadow read should be built instead.
6. Does Doom write `$C071/$C073` inside its frame loop once `$C069` exists? Each such write flushes the pending frame.
7. On ONE//e, what consumes posted mirror writes besides PSRAM bank 1? If nothing, lazy bytes could be discarded there instead of flushed.
8. Is a PS firmware change to the hold request register acceptable in the same release as the RTL change?