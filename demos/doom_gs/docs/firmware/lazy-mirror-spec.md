# Lazy mirror class for Super Hi-Res writes (spec)

# Lazy mirror class for Super Hi-Res writes (design section)

Nothing here was simulated or built; every finding comes from reading the F1.2.1 snapshot. **V** = verified in the RTL or source (file:line). **A** = assumption or estimate. Paths are relative to `appletini-one-main/`; `core_top` means `hdl/apple/vtw_core_top.sv`.

## 0. Summary

- Add a third class, **lazy**, for writes to the SHR range while SHR is selected.
- Lazy bytes do not set `video_active_pending_q` or `video_mirror_mode_q`, so they cause no `$Cxxx` stall and ARM holds do not wait for them.
- A lazy flush is a normal bank-sync flush, started by a short list of events. The byte value is read from the shadow at flush time.
- Cost: about 150 LUTs, 90 FFs, 0 BRAM. Kill switch: `CARD_CTRL 0x35` bit 1, reset value 0.
- Two exposure accesses must still flush lazy bytes: a `$C029` write that leaves SHR, and any `$C071/$C073` write. Every other exposure access and every ARM hold leaves them pending.

## 1. How the core learns that SHR is selected

| Fact | Status |
|---|---|
| `$C029` is not in `soft_switch_manager`; fake SHR is "selected only by C029" | V `soft_switch_manager.sv:74-76` |
| Motherboard-side tracking exists only in capture: `shr_capture_active_q`, set when `data[7:6]==2'b11`, gated by `fake_shr_allowed` | V `apple_cycle_capture.sv:144-171` |
| Renderer uses the same test, `(newvideo & 0xC0)==0xC0` | V `apple_cycle_renderer.c:422-424` |
| `$C029` write is already an exposure access | V `core_top:1398` |
| `$C074` is decoded from live core outputs at `X_CAPTURE` | V `core_top:1863-1869` |
| `$9DF8` is tracked from the registered tuple at `X_ROUTE` | V `core_top:1874-1882` |

**New register `shr_selected_q` in `core_top`.**

- Decode from the registered tuple, like `$9DF8`, not like `$C074`. This keeps load off `core_addr` and `core_data_out`.
- Set or clear when `xstate_q==X_ROUTE && core_active && xl_is_bus && !cycle_rw_q && cycle_addr_q==16'hC029`. Value: `cycle_wdata_q[7:6]==2'b11`.
- Reset on `!rstn`, `!ab_read.res`, `!core_res_n` (covers `!enable` and `!core_run`), and `!fake_shr_allowed`.
- New input `fake_shr_allowed`, wired in `apple_top.sv` with the expression at `:997`.
- Snapshot `cycle_video_shr_q <= shr_selected_q` in `X_CAPTURE` beside `core_top:1922-1932`.

**Policy (`vtw_video_policy.sv`).** New inputs `shr_selected`, `lazy_en`; new output `mirror_lazy`.

```
mirror_lazy   = lazy_en && shr_selected && !overlay_match &&
                graphics_range && (is_aux || post_main_wide);
mirror_active = <existing expression> && !mirror_lazy;
```

Register it as `cycle_video_lazy_q` in `X_ROUTE` beside `core_top:1976`.

| Case | Behaviour |
|---|---|
| `$C029` write keeping SHR on (for example the B&W bit) | No lazy flush. Still flushes inactive pages as today. |
| `$C029` write leaving SHR, lazy pending | Detected in `X_VIDEO_WAIT` from `cycle_wdata_q`. Lazy flush runs first, then the bus cycle, then `shr_selected_q` clears at `X_ROUTE`. |
| `$C029` write entering SHR | No lazy bytes can exist. Active bytes drain through the existing barrier; inactive pages flush through the existing exposure. |
| Control area aux `$9DF8-$9DFF`, SHR4 / SHR-3200 magic at `$9DFC` | Lazy. The renderer reads them from its own shadow (V `apple_cycle_renderer.c:1504-1515`, `apple_cycle_egress.c:274-276`). The core tracks `$9DF8` privately. No PL consumer found (A, grep only). |
| Paging modes 1 and 2 | `post_main_wide_eff` makes MAIN `$2000-$9FFF` lazy too. The change of `post_main_wide_eff` is already a policy change (V `core_top:1404-1407`) and will flush lazy bytes. |
| MAIN `$4078-$407F` (A2Li hole) in paged SHR | Lazy wins. This keeps every page single-class. The hole reaches the motherboard when SHR is left. |
| Overlay armed, or II/II+ host | `cycle_video_force_active_q` forces `overlay_match` for every address (V `core_top:1931-1932`), so lazy is off. Arming is a policy change and flushes. |

Invariant: a page never holds lazy and non-lazy dirty bytes together, because every class-changing event flushes first.

## 2. Flush events

Worst-case flush: 32,768 bytes x 131 clocks = about 32 ms (one bank), 64 ms in paged modes (A, arithmetic).

| Event | Flush lazy? | Why | Who could see a stale byte |
|---|---|---|---|
| Session end (`!enable`) | Yes | Eventual consistency. Bus stays owned until drained. | Physical aux card or PSRAM bank 1 after handback. |
| Apple reset | No, discard | Matches today: `clear(!ab_read.res)` (V `core_top:1448`, README_TURBO "discarding queued mirror data"). | Motherboard aux RAM stays stale. **Open question for the author**: up to a full frame is now discarded. |
| Ctrl-Reset handback | No, discard | It is an Apple reset. Machine returns cold (V README_VIRTUAL_TRANSWARP.md:109,116). | Same as above. |
| `$C029` leaving SHR | Yes | Aux `$2000-$5FFF` becomes DHGR-visible; keeps the single-class invariant. | Motherboard video, aux RAM. Not covered by the author's statement once SHR is off. |
| `$C071/$C073` write | Yes | `vtw_video_bank_sync` never steers the RamWorks bank (V `:5-7`). A later flush under bank N would write into PSRAM bank N+1. | RamWorks data corruption. |
| `$C069` read-bank write | No | Does not change write steering. | None. |
| ARM hold, memory API | No | API reads and writes base banks in the shadow (V README_MEMORY_API.md:151-152). | None; see section 4. |
| ARM hold, SmartPort | No | Source and destination are the shadow (V `smartport_service.c:848-895`, `:796`). | None; see section 4. |
| `rw_flush_pending_q` | No | Set only by `arm_rw_flush_req` (V `core_top:1723-1727`). | None. |
| `video_selected` falls | Yes | Classic posting resumes; lazy must not outlive the direct stream. | Renderer ordering, motherboard RAM. |
| `!core_run` | Yes | Core resets, `shr_selected_q` clears. | Class invariant. |
| Policy change (`post_main_wide_eff`, overlay armed, `ramworks_en`, `lazy_en`) | Yes | Class or translation changes. | Overlay and RamWorks consumers. |
| Other exposure accesses (`$C080-$CFFF`, `$C05x`, `$C000/1`, `$C00C-F`, `$C022`, `$C034/5`) | No | Bytes carry their bank in bit 16; bank sync steers RAMWRT/PAGE2 at flush. | Bus cards reading SHR memory: covered by the author's statement. |

Consumers, for reference:

- **Physical aux card**: receives posted writes steered by motherboard RAMWRT/PAGE2.
- **PSRAM bank 1**: `psram_simple` captures writes even while `vtw_bus_owned` (V `psram_simple.sv:133-136`). Read serving is off during a session.
- **Renderer**: unaffected, see section 5.
- **Motherboard video**: a //e cannot show SHR; it shows stale aux pages. Covered.

A: no physical DMA card writes aux `$2000-$9FFF` during an SHR session. A later flush would overwrite it with the shadow value.

## 3. Coalescer and `core_top` changes

### 3.1 `vtw_video_coalescer.sv`

Byte-level `dirty_mem` and `data_mem` stay shared and unchanged. Lazy writes still push both.

| Item | Change |
|---|---|
| New input `write_lazy` | Exclusive with `write_active`. |
| New input `flush_lazy` | Level; include lazy groups in flush scans and in `drained` / `bank_drained`. |
| New bitmap `lazy_grp_dirty_q[31:0]` | 16 groups of 2 KB per bank. Index `{addr[16], addr[15:11]-5'd4}`. |
| Push (`:106-110`) | Lazy: set only `lazy_grp_dirty_q`. Others: unchanged. |
| `select_page` (`:45-48`) | In flush mode, also select a page when `flush_lazy` and its group bit is set. Clear the group bit when the last page of the group (`page[2:0]==7`) is selected. Latch `scan_lazy_q`. |
| Active scan | Unchanged; never looks at lazy groups. |
| `active_drained` | Unchanged. |
| `drained` | Existing expression AND `(!flush_lazy || lazy_grp_dirty_q==0)`. |
| `bank_drained[b]` | Existing expression AND `(!flush_lazy || lazy_grp_dirty_q[16*b +: 16]==0)`. |
| New output `lazy_drained` | `state_q==SELECT_PAGE && lazy_grp_dirty_q==0 && !(push && write_lazy)`. |
| New states `LAZY_READ`, `LAZY_CAPTURE` | From `CHECK_BYTE` when `scan_dirty_q && scan_lazy_q`. `state_t` stays 3 bits (7 states). |
| New register `scan_shadow_q[7:0]` | `mirror_data = scan_lazy_q ? scan_shadow_q : scan_data_q`. |
| Reset / `clear` | `lazy_grp_dirty_q <= 0`; `CLEAR_BITMAP` as today. |

### 3.2 `core_top` flags

All in the block at `:1458-1477`, reset on `!rstn || !ab_read.res`.

| Register | Set | Clear |
|---|---|---|
| `video_lazy_pending_q` | `video_fast_accept && cycle_video_lazy_q` | `lazy_drained && video_post_idle && !video_sync_active` |
| `video_lazy_req_q` (sticky) | `video_lazy_pending_q && lazy_trigger` | with `video_lazy_pending_q` |
| `video_lazy_flush_q` (promoted) | `video_lazy_req_q && video_post_idle && !video_sync_active` | with `video_lazy_pending_q` |
| `video_any_pending_q` | next-state OR of `video_mirror_mode_q` and `video_lazy_pending_q` | same |

```
lazy_trigger = !video_selected || !enable || !core_run ||
               video_policy_flush_q || video_external_policy_change ||
               ((xstate_q==X_VIDEO_WAIT) && lazy_exposure);
lazy_exposure = !cycle_rw_q && (cycle_addr_q==16'hC071 || cycle_addr_q==16'hC073 ||
                (cycle_addr_q==16'hC029 && cycle_wdata_q[7:6]!=2'b11));
```

| Line | Change |
|---|---|
| `:1464` | `video_mirror_mode_q` set on `video_fast_accept && !cycle_video_lazy_q`, or on promotion. |
| `:1408` | `video_full_flush = (existing) || video_lazy_req_q`. |
| `:1414` | `video_barrier` adds the combinational term `video_lazy_pending_q && (xstate_q==X_VIDEO_WAIT) && lazy_exposure`, so the first wait clock holds. |
| `:1949` | Use `video_any_pending_q` in place of `video_mirror_pending`. |
| `:418`, `:732` | `core_ab.res` and `engine_enable` use `video_any_pending_q`. |
| `:1374-1378`, `:1481` | `core_post_accept`, `core_post_blocked` (classic branch) and `arm_post_ready` add `!video_lazy_req_q`. |
| `:1604-1611` | `rw_flush_unsafe` adds `video_lazy_req_q` beside `video_mirror_pending`. Not `video_lazy_pending_q`. |
| `:1472` | `video_policy_flush_q` set uses `video_any_pending_q`. |
| `:1404` | `video_external_policy_change` adds `lazy_en != lazy_en_q`. |
| `:1365`, `:1384` | `video_start_ready` and `video_direct_active` unchanged. |

**Behaviour with only lazy bytes pending.**

- `$Cxxx` access: `X_CAPTURE`, one clock of `X_VIDEO_WAIT`, `X_ROUTE`. `video_barrier` is low unless the access is a lazy exposure.
- ARM hold: completes without any mirror traffic.
- ARM posts (SmartPort video spans) are accepted, because `video_mirror_mode_q` is 0.
- Teardown: `!enable` is a trigger, so the flush always starts and is bounded. `video_any_pending_q` keeps the engine alive for the clock before promotion. Apple reset clears everything.

**Why promotion waits for `video_post_idle`.** `video_direct_active` suppresses capture of every posted cycle while `video_mirror_mode_q` is set (V `core_top:1384`, `apple_cycle_capture.sv:101,110`). An ARM or classic post accepted just before the trigger must reach the bus unsuppressed, or the renderer loses it.

## 4. Staleness: read from the shadow at flush time

**Decision: shadow read.** Keeping the coalescer copy fails in one real case: SmartPort writes V2 to the shadow and posts V2, then a later lazy flush posts the older V1 from `data_mem`.

**Port: A, through the floating-scan leg.**

- Widen `floating_scan_addr_q` (`core_top:1295`) to 17 bits and rename it `aux_rd_addr_q`.
- Load: `floating_scan_addr_latch` as today; else, when `video_flush_valid`, load `video_mirror_addr`.
- `shadow_a_en` (`:1312`) adds `lazy_rd_issue` (coalescer in `LAZY_READ`).
- `shadow_a_addr` (`:1317`) selects the same leg on `floating_scan_issue || lazy_rd_issue`. No new mux leg in front of the BRAM.
- `LAZY_CAPTURE` registers `shadow_a_rdata` into `scan_shadow_q`.

**Arbitration.**

- Core: the flush runs only under `video_sync_active`, which needs `video_sync_core_idle` (V `:1421-1430`). None of those states uses port A (V `:1307-1313`), and `X_CAPTURE` is held by the barrier (V `:1907`).
- ARM port B has no backpressure (V `vtw_shadow_host_port.sv:83-89`). Detect `sh_en && sh_we && !sh_addr[17] && sh_addr[16:2]==scan_addr_q[16:2]` in `LAZY_READ`; on a hit, `LAZY_CAPTURE` returns to `LAZY_READ`. The pointer advances each write, so one retry is enough.

**Contract change to document.** A PRIVATE memory-API write to a lazy-dirty address will reach the motherboard at the next flush. The renderer still gets no record (V README_MEMORY_API.md:176-178).

Fallback if port A fails timing: mux into port B and add a stall input to `vtw_shadow_host_port`. More functional risk, less timing risk.

## 5. Renderer

| Claim | Status |
|---|---|
| Direct records come from `video_record_*` into the capture FIFO | V `core_top:1379-1381`, `apple_cycle_capture.sv:277-302` |
| Mirror cycles are suppressed from capture in TURBO | V `core_top:1384`, `apple_cycle_capture.sv:101,110` |
| Renderer shadows `g_aux_bank` / `g_main_bank` are fed only by records with `addr_decode_en` | V `apple_cycle_egress.c:270-294` |
| In SHR, capture emits one frame marker per frame, independent of writes | V `apple_cycle_capture.sv:153-159` |
| SHR frame rebuild is keyed on `g_video_shadow_generation` | V `apple_cycle_renderer.c:3062-3090` |
| `$C029` reaches the renderer as an I/O record from the real bus cycle | V `apple_cycle_capture.sv:114-119` |

So in TURBO the SHR picture depends only on the direct stream and the `$C029` bus cycle.

At non-TURBO speeds `video_selected` is false (V `core_top:1352-1353`). Writes use the classic posted queue and the renderer sees them only as bus cycles. **Lazy must not apply there.** It is reachable only through `video_fast_accept`, and leaving TURBO flushes it.

## 6. Throughput

**Fabric clocks per SHR write cycle: 6** (V by reading; `X_CAPTURE`, `X_TURBO_DONE`, `X_ROUTE`, `X_POST_STALL`, `X_MEM_CAPTURE`, `X_MEM_DONE`; `core_top:1952-1953, 1971, 2037-2038, 2109-2122`). Lazy does not change this. It removes the drain stall: today 1,000 pending active bytes hold the next `$Cxxx` access for about 131,000 clocks.

| Stage | Bound | Status |
|---|---|---|
| CPU copy loop | About 31 clocks per byte, about 4.3 M bytes/s | A, from README_TURBO 436 clocks / 16 bytes plus 4 |
| Capture FIFO | 4096 deep; direct accepts below 4064 and not on `data_en` clocks | V `apple_cycle_capture.sv:56, 298-301` |
| Egress | About 28 clocks per 9-record burst plus notify, over 30 M records/s | V structure `apple_cycle_egress.sv:247-265, 396-520`; A for AXI latency |
| DDR ring | 1 MB, 131,072 records, lossless (`cfg_lossless=1`) | V `apple_cycle_egress.h:28`, `apple_top.sv:1028` |
| ARM consumer (CPU1) | Non-cacheable read plus dispatch per record; shares time with the frame render | A: 1 to 3 M records/s |

The ARM consumer is the limit. When the ring fills, egress stalls, the FIFO fills, `video_record_ready` drops and the core waits in `X_POST_STALL`. Nothing is lost. Doom at 35 fps needs 1.12 M bytes/s, inside the estimate but not proven.

**How to measure.**

1. `busdbg clear`, run a saturating SHR fill for a fixed time.
2. Bytes/s = change in egress records written (`0x27`) over time.
3. If full-stall cycles (`0x2A`) grow, the ARM is the bound.
4. `vtw status` video waits (`perf_count[7]`, V `core_top:1630-1633`) minus one per write and one per `$Cxxx` access gives the stall clocks.

## 7. Cost, timing, stages, tests

**Cost (A).**

| Block | LUT | FF | BRAM |
|---|---|---|---|
| Policy | 6 | 0 | 0 |
| `core_top` flags, decode, port A | 70 | 30 | 0 |
| Coalescer | 70 | 45 | 0 |
| Two optional counters | 10 | 64 | 0 |

**Timing risk.**

| Path | Risk | Mitigation |
|---|---|---|
| `core_post_accept`, `arm_post_ready`, `core_post_blocked` | Medium; this is the admission family | One registered flop each |
| `video_barrier` into `X_CAPTURE` hold and `eng_req_valid` | Medium | New terms are flops, plus one decode of the registered tuple |
| Shadow port A address | Low to medium | Reuses the floating leg; adds one registered select input |
| Coalescer `select_page` | Low to medium | 32:1 mux from `next_page_q`; pre-register the lookup if needed |
| `X_CAPTURE` next state | Neutral | One flop replaces another |

**Stages.** Each stage needs a full build against the +0.200 ns gate.

1. `shr_selected_q`, policy output, `0x35` bit 1. Class computed, not used. No behaviour change.
2. Coalescer groups, shadow read, flags. Kill switch off by default. Full regression with the switch off must match today.
3. Turn on through a profile key; hardware test with Doom and an SHR4 paged demo.

Changing `lazy_en` while bytes are pending flushes them, so the switch is safe at run time.

**Tests.**

| Bench | Additions |
|---|---|
| `tb_vtw_video_policy.sv` | New inputs; exhaustive check that lazy and active are exclusive; A2Li hole; overlay and II+ force active. |
| `tb_vtw_video_coalescer.sv` and reference model | Lazy pushes leave `drained`, `active_drained`, `bank_drained` unchanged; `flush_lazy` drains from a shadow model; port B collision retry; reset during a lazy flush. |
| `tb_vtw_video_bank_sync.sv` | Module unchanged; add a restart when `bank_pending` grows after promotion. |
| `tb_vtw_turbo.sv` | New tasks beside `deferred_video_case` and `deferred_async_hold`, listed below. |

New `tb_vtw_turbo.sv` cases:

- SHR fill, then `$C000`, `$C030`, `$C054`, `$C08x`: zero posted writes and exactly one wait clock each.
- `STA $C029` leaving SHR: flush, then motherboard model equals shadow.
- `$C073` write: flush first.
- ARM hold with lazy pending: completes with no posts.
- `sh_write` into a lazy-dirty byte, then flush: new value arrives.
- ARM post racing a trigger: the renderer still captures it.
- Disable with lazy pending: bus held until drained.
- Apple reset: discarded.
- Speed change, overlay arm, kill switch toggle.

Not verified: ONE//e behaviour of mirrored lazy bytes, AXI HP latency, and CPU1 per-record cost.