# Option 2: bank and memory-mapping soft switches that do not touch the bus, flush the video mirror, or invalidate the TURBO caches (plan)

# Option 2: fabric-only mapping switches and mapping-tolerant TURBO caches

All line numbers refer to the F1.2.1 snapshot. Nothing was modified, simulated or synthesised; every cost figure is derived from reading the RTL.

## 0. Summary

- **Cost today:** the sequence `STA $C073 / STA $C003 / read / STA $C002` takes about 580 fabric clocks (4.3 µs) in three PHI0-synchronised bus cycles, plus about 40 clocks of cache re-warm. With dirty SHR bytes pending, each `$Cxxx` access also waits one Apple cycle per pending byte.
- **Cost after:** each switch access takes 3 fabric clocks (22.5 ns) and the caches survive. The whole sequence is about 40 clocks (0.30 µs) on a RamWorks line hit and about 135 clocks (1.0 µs) on a line miss.
- **Cache change:** no mapping generation or per-mapping page table is needed. Both caches already store the physical page; comparing 3 of those bits plus a "cacheable" bit replaces the mapping invalidate, with zero new storage.
- **Switch change:** the private tracker stays authoritative. The motherboard is updated lazily by a small reconciler, coalesced to the latest value, before any event where physical state is observable.
- **Size:** about 150–200 LUTs, 80 FFs, 0 BRAM.
- **Main timing risk:** the `turbo_hit → turbo_complete → core_en` cone.

## 1. What the RTL does today (VERIFIED)

### 1.1 Which accesses go to the physical bus, and why

| Fact | Where |
|---|---|
| Every `$C0xx` address routes to `APPLE_ROUTE_BUS`, regardless of switch state | `globals.sv:300-304` |
| `X_ROUTE` sends `xl_is_bus` cycles to `X_BUS` unless one of six shortcuts matches: `sp_boot_suppress_hit`, `d2_fast_hit`, `sp_hit`, `xl_c01x_rd`, USB, `xl_btn_rd` | `vtw_core_top.sv:1977-2026` |
| None of those shortcuts covers `$C002-$C009` writes, `$C071/$C073` writes or `$C080-$C08F`, so all are real sync cycles | same |
| The private tracker `vtw_ssm` is updated at `X_ROUTE`, before the bus cycle starts (`ssm_apply_pulse` drives both `serve_en` and `data_en`) | `vtw_core_top.sv:416-433, 1254` |
| A second tracker, `video_physical_ssm`, follows the real bus (`ab_read`) | `vtw_core_top.sv:439-443` |
| `$C011-$C01F` reads are already served from private state on physical hosts, but not on ONE//e (`!virtual_motherboard`) | `vtw_core_top.sv:577-580` |
| Sync cycle launches at `drive_en` (fall + tap 8) and completes at `data_en` (rise + tap 59) | `vtw_bus_engine.sv:810-858, 726-800`; `apple_bus_wrapper.sv:120,136` |

Memory translation never needs the bus cycle; the private state is already authoritative. The bus cycle exists because the motherboard's own switch state steers posted video writes, which carry only a 16-bit address (`vtw_core_top.sv:549-558`, README_VIRTUAL_TRANSWARP §2). Three physical-side consumers depend on it:

| Consumer | Fields that matter in a session | Where |
|---|---|---|
| Motherboard MMU (posted video writes into main/aux RAM) | RAMWRT, 80STORE, PAGE2, HIRES | README §2 |
| `psram_simple` write capture (INH read serving is off while `vtw_bus_owned`) | `sss.addr_decode[23:16]`, so RAMWRT, 80STORE/PAGE2 and RamWorks bank | `psram_simple.sv:123-136` |
| `apple_cycle_capture` | `addr_decode_late`; record fields `sw_ramrd/ramwrt/altzp` | `apple_cycle_capture.sv:93, 188-191` |

During a session, physical RAMRD, ALTZP and language-card state steer no data that anyone consumes. Parked cycles are reads of `$FFFF` or replayed memory (`vtw_bus_engine.sv:872-880`). Only RAMWRT and the RamWorks bank must be right, and only when a video write reaches the bus.

### 1.2 Video barrier and exposure flush

`video_exposure_access` (`vtw_core_top.sv:1390-1401`) is true for:

- any access to `$C080-$CFFF` (`addr[11:7] != 0`), which includes the language-card switches;
- any access to `$C05x`;
- writes to `$C000/1`, `$C00C-$C00F`, `$C022`, `$C029`, `$C034`, `$C035`, `$C071`, `$C073`.

Writes to `$C002-$C00B` are not exposure accesses.

| Mechanism | Trigger | What it protects | Where |
|---|---|---|---|
| Active-pending barrier | Any `$Cxxx` address while `video_active_pending_q`; core held in `X_CAPTURE` | Active mirror bytes drain under the current motherboard mapping, so that mapping must not change until they are out | `:1414-1415, 1907`; `vtw_video_coalescer.sv:3-6` |
| `X_VIDEO_WAIT` | Any `$Cxxx` while `video_mirror_pending` | One wait state so exposure can be decoded from registered `cycle_addr_q` | `:1949-1950, 1957-1962` |
| Full flush (`video_full_flush`) | Exposure access in `X_VIDEO_WAIT`, plus hold/handback/policy changes | Deferred bytes carry a 1-bit main/aux tag; `vtw_video_bank_sync` steers only RAMWRT/PAGE2 and never the RamWorks bank | `:1408-1413`; `vtw_video_bank_sync.sv:3-7` |
| Engine bank-steer wait | Sync write to `$C000-$C007`, or any `$C054-$C057`, with posted queue non-empty | Queued writes retire under the regime they were issued in | `vtw_bus_engine.sv:70-74, 455-458, 848` |

`$C071/$C073` is an exposure access because a deferred aux byte must reach the bus while the physical bank is 0; otherwise `psram_simple` would capture it into bank N+1.

ASSUMED: `$C080-$C08F` is caught only as a side effect of the coarse `addr[11:7] != 0` decode. The comment at `:1392-1393` is about card ROM/DEVSEL entry.

### 1.3 Cache invalidation

`turbo_invalidate` (`vtw_core_top.sv:1206-1211`) includes `turbo_mapping != turbo_mapping_q`. That is a one-clock pulse on any change of the 19-bit `TranslateState`: 80STORE, RAMRD, RAMWRT, ALTZP, PAGE2, HIRES, INTCXROM, SLOTC3ROM, INTC8ROM, the three LC bits and the 7-bit bank. It clears all 64 `map_valid_q` and all 32 `word_valid_q` bits (`vtw_turbo_cache.sv:120-124`).

Three facts make this easy to relax:

- The word cache already stores `{logical tag[15:7], phys page[17:8]}` (`vtw_turbo_cache.sv:48, 99`), but the read hit compares only the logical tag (`:76`; `vtw_core_top.sv:1238-1239`).
- The map entry already stores `phys[17:8]` (`vtw_turbo_cache.sv:96`), registered as `turbo_write_phys_q`.
- Only shadow-backed pages outside `$Cxxx` are ever filled (`vtw_core_top.sv:1212-1215`). RamWorks banks above 1 are never cached, so the bank value matters only as "is it zero".

Side observation: the 32 read-side map entries (`map_index = {rw, …}`) are filled but never consulted, because the read hit uses only the word cache.

## 2. Cost today

ASSUMED: one Apple cycle is about 131 fabric clocks. README_VIRTUAL_TRANSWARP line 213 gives 8513 clocks per 65-cycle line. The task brief and `psram_simple.sv:238` say "T157"; if that is the real figure, scale bus-bound numbers by 1.2.

From `drive_en` to `data_en` is about 116 clocks. The wait for `drive_en` is 0–131 clocks.

| Step | Path | Clocks | µs |
|---|---|---:|---:|
| `STA $C073`, random phase | CAPTURE, ROUTE, wait for `drive_en`, cycle, response, BUS_DONE | 120–251, avg 185 | 0.9–1.9, avg 1.39 |
| `STA $C003`, back to back | Next `drive_en` is 15 clocks after the previous `data_en`; the refetch after invalidation takes 13–15 clocks, so it is marginal | 131, or 262 if missed | 0.98 or 1.97 |
| Far read, RamWorks line miss | `X_RW_LOOKUP`, `X_RW_FILL`; admission window opens just after the fall | about 50 | 0.38 |
| `STA $C002` | Request lands mid-cycle and waits for the next `drive_en` | about 212 | 1.59 |
| **Read plus `$C002`** | | **262** | **1.97** |
| Cache re-warm (3 invalidations) | +2 clocks per word miss, +3 per write-page miss | 35–45 | 0.3 |
| **Total** | | **about 620 (510–900)** | **about 4.6 (3.8–6.8)** |

With TURBO direct video, add 131 clocks per dirty active byte before each `$Cxxx` access proceeds. A `$C073` write additionally drains all deferred pages of both banks. For a renderer that alternates texel reads and SHR writes, this caps pixel output at the 1 MHz bus rate.

## 3. Design

### 3.1 Part B: caches that survive mapping changes

A cached translation is valid if the current mapping sends that logical page to the same physical page. Each shadow byte has exactly one logical address (VERIFIED from `translate_apple_addr` and `vtw_shadow_map`). Given a logical tag match, the physical page is fully identified by three bits:

`space = {phys[17] (ROM), phys[16] (aux), phys[12] (LC bank-1 remap)}`

Changes:

1. `vtw_turbo_cache.sv`: add output `read_space[2:0]` taken from the stored word tag's `phys[17], phys[16], phys[12]`. No RAM widening.
2. `vtw_core_top.sv` X_CAPTURE block (`:1939-1945`): register `turbo_read_space_q` with the other raw cache outputs. The write side uses `turbo_write_phys_q[17], [16], [12]`, already registered.
3. Register at X_CAPTURE, beside `cycle_xl_decoded_q` (`:1920`):
   - `cycle_space_q = {route == ROM, decoded[16], decoded[12]}`
   - `cycle_cacheable_q = ROM || (CACHE && bank[7:1] == 0)`
4. `turbo_hit` (`:1237-1242`): AND both arms with `cycle_cacheable_q` and the space compare.
5. `turbo_invalidate` (`:1206-1211`): delete the `turbo_mapping != turbo_mapping_q` term. Keep every other term.

Why this is correct:

- The snoop already matches on `{logical tag, phys page}` (`vtw_turbo_cache.sv:88-89`), so a write through another mapping leaves the entry alone.
- Region boundaries are page-aligned and words are 4-byte aligned, so a filled word never straddles mappings.
- `fast_write` is a function of logical page and space; the wide-main and overlay policies keep their own invalidates.
- INTCXROM, SLOTC3ROM and INTC8ROM affect only `$Cxxx`, which is never cached.
- A mapping can change only through the core's own `$Cxxx` cycle, so a parked `X_TURBO_DONE` response cannot go stale.

Cost: about 8 FFs and 15 LUTs, 0 BRAM. `perf_count[5]` (invalidations) should fall to near zero.

Timing risk: medium, on `turbo_hit → turbo_complete → core_en`. The compare grows from 9 to 12 bits plus two qualifiers, which still fits two LUT6 levels if all operands are registered. Do not derive `cacheable` from `xl_shadow_valid` inside `X_TURBO_DONE`. Compute it at capture in parallel with the translate, from a pre-registered `bank_zero_q`. If slack drops, mark the new registers `DONT_TOUCH`, as `turbo_read_tag_q` already is.

### 3.2 Part A: quiet switches

Classification in `X_ROUTE`, from registered `cycle_addr_q`:

```
xl_quiet_sw = quiet_en && xl_is_bus && (cycle_addr_q[15:8] == 8'hC0) &&
  ( (!cycle_rw_q && cycle_addr_q[7:0] inside {8'h02,8'h03,8'h04,8'h05,8'h08,8'h09})
 || (!cycle_rw_q && ramworks_en && (cycle_addr_q[7:0] == 8'h71 || cycle_addr_q[7:0] == 8'h73))
 || (cycle_addr_q[7:4] == 4'h8) );
quiet_en = cfg_quiet_switches && (eff_mode == SPEED_TURBO) && !host_is_iiplus;
```

| Item | Decision |
|---|---|
| Completion | New branch in the `:1983-2025` chain, to `X_DEAD`. Cost: CAPTURE, ROUTE, DEAD, 3 clocks |
| Private tracker | Unchanged; already applied at `X_ROUTE` |
| Stays on the bus | 80STORE, PAGE2, HIRES, all `$C05x`, INTCXROM, SLOTC3ROM, 80COL, ALTCHARSET, `$C000/$C010` reads, all slot I/O |
| `$C08x` read data | Stage 1 returns a constant. Optional later: the scanner byte, by reusing `floating_scan_issue` (`:1304`) with a new `X_SW_SCAN` state, +2 clocks |
| Default | Off; new persisted bit such as `vtw.turbo.quiet_switches` |

### 3.3 Reconciler: new module `vtw_switch_sync`

Modelled on `vtw_video_bank_sync`. It compares the private state with `video_physical_sss` and issues sync writes until they match. Coalescing is implicit: only the latest private value is ever replayed.

- **Compare:** `sw_dirty_q <= ({ramrd, ramwrt, altzp, bank[6:0], lc_bank2, lc_read, lc_write}` private `!=` physical`)`. 13 bits, registered.
- **States:** `IDLE, PICK, REQ, WAIT, LC2_REQ, LC2_WAIT, FINISH`.
- **Priority in PICK:** bank (`$C073` write, data `{0, bank}`), RAMRD, RAMWRT, ALTZP, then LC.
- **Language-card replay** (read cycles, `addr[3] = !bank2`):

| Target read / write | Cycles |
|---|---|
| read 1, write 0 | `$C080` once |
| read 0, write 1 | `$C081` twice |
| read 0, write 0 | `$C082` once |
| read 1, write 1 | `$C083` twice |

- **Request path:** add `sw_sync_active` next to `video_sync_active` in the `eng_req_*` mux (`:765-775`), in the `X_BUS` response qualifier (`:2126`) and the ARM response qualifier (`:948`). Register the module's address and data outputs.
- **Start condition:** reuse `video_sync_bus_idle` (`:1429`).
- **Clear:** `!ab_read.res`.
- **Size:** about 45 FFs and 100–150 LUTs.

### 3.4 Ordering guarantees

| # | Rule | Implementation |
|---|---|---|
| O1 | Before any non-quiet `$Cxxx` access (physical or private-served, except `$C01x` status on physical hosts), physical equals private | Line 1949 becomes `(video_mirror_pending \|\| sw_dirty_q) && core_addr[15:12] == 4'hC`. `X_VIDEO_WAIT` exits only when `!(sw_dirty_q && !cycle_quiet)` |
| O2 | A video write is admitted only if the physical write steer matches | `video_steer_ok_q = (ramwrt_priv == ramwrt_phys) && (!aux_target \|\| bank_phys == 0)`, ANDed into `video_start_ready` (`:1365`), `core_post_accept` (`:1374`) and `arm_post_ready` (`:1481`). If false, start the reconciler; the core waits in `X_POST_STALL` |
| O3 | Physical RAMWRT and bank never change while active bytes are pending | Guaranteed by the reconciler start condition |
| O4 | A physical bank change is preceded by a full flush of aux deferred bytes | Add "bank replay pending and `!video_bank_drained[1]`" to `video_full_flush` (`:1408`) |
| O5 | Quiet accesses bypass the active-pending barrier and the exposure flush | Remove the third term of `video_barrier` from the `X_CAPTURE` hold and re-apply it in `X_VIDEO_WAIT` as `video_active_pending_q && !cycle_quiet`. Exclude quiet accesses from `video_exposure_access` |
| O6 | Hold, handback and mode change reconcile first | Trigger on `sw_dirty_q && (!core_run \|\| arm_rw_flush_req \|\| !quiet_en)`. Gate the ARM request as `:768` does. Add `sw_sync_active` to `rw_flush_unsafe` (`:1604`) |

O5 keeps low-address decode off the wide capture enable. That is the constraint that produced `X_VIDEO_WAIT` in the first place (README_TURBO lines 128-131, 150-151).

Under O1, every physical observer sees the same switch state at every real I/O cycle as today. Only intermediate values and the timing of the switch cycles differ.

For the Doom loop, RAMWRT stays on and the private bank toggles between N and 0. The physical bank stays 0 and physical RAMWRT stays 1. No reconcile cycle is issued until the next keyboard poll.

### 3.5 Cost after

| Step | Clocks | µs |
|---|---:|---:|
| Each quiet switch access | 3 | 0.0225 |
| `STA abs` to a quiet switch, including 3 warm fetches | 9 | 0.07 |
| Whole sequence, RamWorks line hit | about 40 | 0.30 |
| Whole sequence, clean line miss, random phase | about 135 | 1.0 |
| Whole sequence, dirty line miss | about 265 | 2.0 |
| Cache re-warm | 0 | 0 |
| Pending-video penalty | 0 | 0 |

After this change the PSRAM admission limit of one operation per Apple cycle is the dominant cost. That belongs to the line-cache option.

## 4. Correctness hazards

| Hazard | Analysis | Action |
|---|---|---|
| Physical slot cards and bus-snooping video cards | They see the correct state at every real I/O cycle (O1) and every video write (O2) | None |
| II/II+ host | The language card is a physical slot-0 card and need not reset on RESET | `quiet_en` excludes `host_is_iiplus` |
| ONE//e | `$C011-$C018` are answered from the physical `sss` | O1 covers it, because those reads are not exempt when `virtual_motherboard` |
| Physical RamWorks card in the aux slot | `ramworks_en = 0`, so `$C071/$C073` stay on the bus | None |
| Paddle trigger | Today every `$C07x` bus access triggers the timers (`:1533-1537`); a quiet `$C073` no longer does | Document. Optionally add an `X_DEAD` term to `usb_paddle_trigger` |
| Floating bus | Only `$C08x` reads are affected; `$C05x` and `$C03x` are unchanged | See 3.2 |
| IRQ between a quiet switch and its replay | Stack pushes and vector fetch use private state. The handler's first real I/O triggers O1 | None |
| Reset | Both trackers and the MMU reset to the same values (`soft_switch_manager.sv:255-285`); pending replay is dropped | Reconciler clear on `!ab_read.res` |
| LC double read | The private tracker sees every `$C08x` access in order. The physical pre-write latch is driven only by complete reconciler sequences. A mode switch in mid-sequence can leave physical write-enable differing | The reconciler runs in every speed mode whenever dirty |
| Disk II | `$C0Ex` is non-quiet and passes O1. `$C08x` is outside `sd_slot_io` (`:1114`). Quiet cycles still produce `d2_cycle_tick` | None |
| SmartPort | Uses the private snapshot (`sp_sss_snapshot`, `:531-548`). Its `arm_post` video bytes are steered physically | O2 on `arm_post_ready`; O1 on `$C7xx` entry |
| Capture record fields | `sw_ramrd/ramwrt/altzp` in records become stale. ASSUMED the PS renderer ignores them | Verify. If used, override `capture_sss` with private bits at `apple_top.sv:981-987` |
| PS status register `0x02` | Reads the physical `sss`; shows stale values | Documentation only |

## 5. Staged plan

| Stage | Content | Risk | Gate |
|---|---|---|---|
| 1 | Part B only | Medium timing, low functional | Full `test_vtw*.py` suite; build at +0.200 ns or better |
| 2 | `vtw_switch_sync`, `sw_dirty_q`, O1 and O6, with `quiet_en` tied to 0 | Low | Regression unchanged; reconciler never fires |
| 3 | Quiet RAMRD, ALTZP and LC. No video interaction, since none of them steers writes | Low | Benches T3–T6 |
| 4 | Quiet RAMWRT and bank, with O2–O5 | Highest: video admission path | Benches T7–T10; hardware check of SHR and DHGR on the motherboard display |
| 5 | Optional: scanner byte for `$C08x`; relax O1 to status reads and session end only | Low | — |

Take a full build after each stage. Stage 1 alone removes the re-warm cost and is independently shippable.

## 6. Testbench plan

| # | Bench | Checks |
|---|---|---|
| T1 | `tb_vtw_turbo.sv`, new task `mapping_cache_survive` | Warm the cache, toggle RAMRD/ALTZP/LC/bank. `perf_count[5]` unchanged; every read matches a reference model built from `translate_apple_addr` |
| T2 | Same bench, global assertion | `turbo_complete && cycle_rw_q` implies `turbo_rdata_q` equals the reference byte. Run over the existing `coherency_program`, `bank_program` and `selfmod_program` |
| T3 | New `tb_vtw_switch_sync.sv`, modelled on `tb_vtw_video_bank_sync.sv` | Random private/physical pairs converge. All four LC targets, including the double read. Reset in the middle of a sequence |
| T4 | `quiet_far_access` | The four-instruction sequence issues zero sync cycles (`cnt_bus_cycles`), within a clock budget; the byte read comes from the right bank |
| T5 | `quiet_then_io` | Quiet switches followed by `$C000`. Scoreboard: at the `$C000` `data_en`, physical equals private. Replay count equals the number of differing switches |
| T6 | `quiet_irq` | IRQ between the quiet switch and the far read. Handler touches `$C40x`; stack bytes land in the correct bank |
| T7 | `quiet_video_steer` | SHR writes with private bank toggling between N and 0. Every mirror byte lands in aux bank 1; `dbg_aux_write_count` addresses never enter bank N+1 |
| T8 | `quiet_bank_replay_flush` | Deferred aux bytes pending, then a forced bank replay. The flush completes before the `$C073` cycle |
| T9 | Extend `deferred_video_case`, `direct_video_exit`, `direct_video_abort` | ARM hold, `core_run` drop, TURBO exit and Apple RESET, each with `sw_dirty_q` set |
| T10 | Randomised soak | Random mix of quiet switches, video writes, real I/O and IRQs against a classic-mode reference run. Compare final shadow, PSRAM model, motherboard RAM model and physical switch state |

Relevant files, all under `<appletini-one>`:

- `hdl/apple/vtw_core_top.sv`
- `hdl/apple/vtw_turbo_cache.sv`
- `hdl/apple/vtw_video_bank_sync.sv`
- `hdl/apple/vtw_video_coalescer.sv`
- `hdl/apple/vtw_bus_engine.sv`
- `hdl/apple/soft_switch_manager.sv`
- `hdl/globals.sv`
- `hdl/apple/psram_simple.sv`
- `hdl/apple/apple_cycle_capture.sv`
- `hdl/apple/apple_top.sv`
- `hdl/sim/tb_vtw_turbo.sv`
- `hdl/sim/tb_vtw_video_bank_sync.sv`