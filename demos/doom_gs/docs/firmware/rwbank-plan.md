# Option 3: separate read and write bank selection for extended memory (plan)

# Option 3: separate read/write bank selection for extended memory

All paths are under `<appletini-one>`. Nothing was modified and nothing was simulated or built. "VERIFIED" means read in the RTL at the cited lines; all LUT/FF figures are my estimates.

## 1. Recommendation

Build Option 3 in a reduced form:

- Three bank registers: R (reads of $0200-$BFFF), W (writes), Z (ALTZP: ZP, stack, LC).
- `$C071/$C073` keep working and set all three.
- Under vTW, R and Z are served privately: no bus cycle, no video flush, no barrier stall. W stays a real bus cycle, handled exactly like `$C073` today.
- Two supporting changes are required for it to be fast: a video-barrier exemption for the private registers, and a narrower TURBO invalidation compare.
- Cost: about 250-300 LUTs, about 150 FFs, 0 BRAM, no new logic on the capture enable.

The far-memory port is a sound second feature but I would not build it first (section 9).

## 2. What the RTL does today (VERIFIED)

| Fact | Where |
|---|---|
| One 7-bit bank register, written by `$C071/$C073` with data bit 7 = 0, captured at `data_en`, gated by `ramworks_en` | `hdl/apple/soft_switch_manager.sv:53,141-144` |
| Bank resets to 0 on hard reset and on Apple RES | `soft_switch_manager.sv:129,284` |
| Translation computes `q_aux_bank_full = bank + 1` and uses it for ZP/stack, high RAM and $0200-$BFFF alike | `hdl/globals.sv:251,254-269` |
| RAMRD vs RAMWRT is selected by `rw_in`; 80STORE+PAGE2 overrides for display windows | `globals.sv:264-268` |
| `TranslateState` is 19 bits and carries `sw_ramworks_bank` | `globals.sv:181-195` |
| Three `soft_switch_manager` instances: private `vtw_ssm`, `video_physical_ssm`, and the motherboard one | `vtw_core_top.sv:427-433,439-443`; `apple_top.sv:348` |
| Private switches apply at X_ROUTE from the registered tuple (`serve_en` = `data_en` = `ssm_apply_pulse`) | `vtw_core_top.sv:416-425,1254` |
| Translation is combinational from `core_addr`/`core_rwb` and registered at the X_CAPTURE edge | `vtw_core_top.sv:511-515,1920-1921` |
| Only decoded banks 0 and 1 are BRAM-backed | `hdl/apple/vtw_shadow.sv:47-58` |
| RamWorks path = CACHE route, not shadow-valid, `ramworks_en` | `vtw_core_top.sv:643-644` |
| Line cache: one line (valid, dirty, 21-bit line, 64-bit data) | `vtw_core_top.sv:1045-1060` |
| Posted writes are only ever bank 0 or 1, and carry only the 16-bit Apple address; the motherboard's own switches steer them | `vtw_core_top.sv:549-569,1506-1507` |
| TURBO invalidates on any change of the 19-bit mapping, bank included | `vtw_core_top.sv:1184-1185,1199,1206-1211` |
| TURBO caches fill only from shadow-valid, non-$Cxxx accesses | `vtw_core_top.sv:1212-1215` |
| Writes to `$C071/$C073` are exposure accesses; all of `$C080-$CFFF` is too | `vtw_core_top.sv:1390-1401` |
| Any $Cxxx access is held in X_CAPTURE while active-page mirror bytes are pending | `vtw_core_top.sv:1414-1415,1907` |
| Motherboard serve path keys off `sss.addr_decode` (early translate with `rw_early`); INH reads are suppressed while vTW owns the bus; write capture stays live | `psram_simple.sv:123-136`; `soft_switch_manager.sv:155-164` |
| Video capture uses the late decode and accepts only banks 0 and 1 | `apple_cycle_capture.sv:67-72,93-94` |
| SmartPort snapshot is 22 bits, bank in [20:14], exported in a 32-bit register | `vtw_core_top.sv:531-548`; `smartport_card.sv:155-173,625` |
| PS maps SmartPort buffers with one `aux_bank` for all access types | `ps_sources/frontend/smartport_service.c:72-73,351-387` |
| Memory API endpoints carry an explicit bank; they never read the bank register | `ps_sources/frontend/memory_api.c:38-55` |

### Two findings outside the assignment

**A. Possible ordering hole in classic (non-TURBO) modes.**
- `vtw_is_bank_steer` covers only `$C000-$C007` writes and `$C054-$C057` (`vtw_bus_engine.sv:70-74`).
- A pending sync request runs ahead of the posted queue unless `sync_flush_wait` is set (`vtw_bus_engine.sv:455-458,848-861`).
- So a `$C073` write can overtake queued base-aux posted writes. Those writes then drain while the motherboard-side tracker holds the new bank.
- Consequence (my inference, not simulated): the late decode is no longer bank 1, so capture skips the byte, and `psram_simple` write capture stores it in the wrong PSRAM bank.
- TURBO is covered by the exposure flush. Fix: add `$C071/$C073` (and the new `$C079`) to `vtw_is_bank_steer`.

**B. The barrier is the real cost of bank switching during SHR drawing.**
- Aux graphics are always "active" mirror pages, so `video_active_pending_q` is set almost continuously while Doom draws.
- Every `$C073` write then waits in X_CAPTURE until the mirror has drained at one byte per Apple cycle.
- Any new register in $Cxxx inherits this unless exempted.

## 3. Software-visible interface

### Address choice

| Candidate | Verdict | Reason |
|---|---|---|
| `$C078-$C07B` | **Chosen** | No fabric decode uses `$C075-$C07F` except ONE//e paddle aliases (`onee_motherboard_io.sv:42-50,271`). Visible on the physical bus, so it also works with vTW off. Avoids `$C075/$C077`, which some RamWorks clones alias to the bank register (ASSUMED from memory, not checked). |
| Slot-7 DEVSEL `$C0F0-$C0FF` | Rejected | Fully used by LINTXT (`linear_text_overlay_card.sv:200-211`) and shared with SuperSprite (`boot_menu_card.sv:570`). All of it is an exposure access, and the bus engine drains posted writes first (`vtw_bus_engine.sv:454-458`). |
| Slot-7 `$C800` space | Rejected | Needs `sp_active` and the slot-7 C8 claim (`vtw_core_top.sv:678-685`). Goes through the SmartPort card handshake. Disappears when SuperSprite replaces SmartPort. |
| Aux `$9DF8-$9DFF` control area | Rejected | All 8 bytes are taken. Only reachable when writes already go to base aux. It is inside the posted video window, so every write costs a mirror byte. |

### Register map

Active only when `ramworks_en` = 1 and SPLIT is enabled.

| Address | Write | Read under vTW | Bus cycle under vTW |
|---|---|---|---|
| `$C071/$C073` | bit 7 = 0: R = W = Z = data[6:0] | unchanged | yes, exposure (unchanged) |
| `$C078` RDBANK | R = data[6:0] | `{0, R}` | no, private |
| `$C079` WRBANK | W = data[6:0] | `{0, W}` | write: yes, exposure + bank steer. Read: private |
| `$C07A` ZPBANK | Z = data[6:0] | `{0, Z}` | no, private |
| `$C07B` CTRL/ID | `$A5` enables SPLIT, `$A4` disables | `{4'hA, 2'b00, vtw_private, split_en}` | no, private |

Rules:
- Values with bit 7 set are ignored, as for `$C073`.
- Writes to `$C078-$C07A` are ignored while SPLIT is off. This protects software that pokes `$C07x` blindly.
- A `$C073` write does not clear SPLIT. It only reloads all three registers.
- 80STORE+PAGE2 display windows: reads use R, writes use W. The override chooses main vs aux only, never which aux bank.

### Reset state

Hard reset and Apple RES: R = W = Z = 0, SPLIT off. Same place as the current bank reset.

### Detection

1. Authoritative: a new feature bit in the AMEM STATUS block at offset 8 (`memory_api.c:75-76`), for example `MEMORY_API_FEATURE_SPLITBANK`. AMEM needs an active vTW.
2. Under vTW: read `$C07B` and check the `$Ax` signature, write `$A5`, read again, check bit 0. Then write two different values to `$C078` and read each back. A floating bus will not echo both.
3. With vTW off, readback is not available (the card does not drive `$C07x` reads). Use a functional probe from code outside $0200-$BFFF.

### Software constraint to state plainly

With RAMRD = 1, opcode fetches in $0200-$BFFF also come from bank R. Code that reads bank R while writing SHR must run from ZP/stack or the language card. Z makes this practical: ALTZP = 1 with Z = 0 puts ZP, stack and 16K of LC in base aux, which is BRAM and TURBO-cacheable.

## 4. Translation changes

### `hdl/globals.sv`

- `SoftSwitchState` (line 172) and `TranslateState` (line 194): replace `sw_ramworks_bank` with three 8-bit fields holding bank + 1, `sw_rd_bank_p1`, `sw_wr_bank_p1`, `sw_zp_bank_p1`. Keep a 7-bit `sw_ramworks_bank` alias equal to W for debug readers such as `current_softswitch_state` (`apple_top.sv:847-848`).
- `translate_state_from_sss` (197-215): copy the three fields.
- `translate_apple_addr`:
  - Delete line 251 (the adder).
  - Lines 258 and 261: use `st.sw_zp_bank_p1`.
  - Lines 264-268: `q_aux = rw_in ? st.sw_rd_bank_p1 : st.sw_wr_bank_p1`, used in both the RAMRD/RAMWRT term and the 80STORE term.
- Nothing else changes: route classification, LC remap, ROM cases.

Depth: today each bank bit is "condition AND (bank + 1)". After the change each bit is a function of Z, R, W, select-ZP, select-aux and `rw`: six inputs, one LUT6. Moving the +1 into the register removes a 7-bit carry chain from the `core_addr` to `cycle_xl_decoded_q` path and from the motherboard early decode. Net depth should be equal or one level better (estimate).

### `hdl/apple/soft_switch_manager.sv`

- Replace `ss_ramworks_bank` (line 53) with `ss_rd_bank_p1_q`, `ss_wr_bank_p1_q`, `ss_zp_bank_p1_q` (8 bits each), `ss_split_en_q`, and three flags `ss_*_is_base_q` (bank == 0).
- Extend the block at 141-144. Same qualifiers (`ramworks_en`, `data_en`, write, `is_c0xx`):
  - `$71/$73`: load all three.
  - `$78/$79/$7A` with `ss_split_en_q`: load one.
  - `$7B`: set or clear SPLIT on the magic values.
- Resets at 129 and 284: p1 = 1, flags = 1, SPLIT = 0.
- Lines 95 and 330: drive the new fields.

Because this module is shared, the private tracker and the motherboard tracker both gain the feature from the same edit.

## 5. vTW changes (`hdl/apple/vtw_core_top.sv`)

### 5.1 Private serve

Add in the X_ROUTE bus branch, ahead of `d2_fast_hit` (line 1992):

```
wire xl_bankreg = ramworks_en && (cycle_addr_q[15:2] == 14'h301E);   // $C078-$C07B
wire xl_bankreg_private = xl_bankreg && !(xl_is_write && cycle_addr_q[1:0] == 2'd1);
...
else if (xl_bankreg_private) begin
    core_data_in_q <= bankreg_rdata;   // 4:1 mux of registered values
    xstate_q       <= X_DEAD;
end
```

- X_DEAD is already the completion state for private reads (lines 2009-2022).
- The register update itself needs no new code: `vtw_ssm` applies it at the X_ROUTE edge.
- All inputs are registered (`cycle_addr_q`, `cycle_wdata_q`, `vsss`). This is the same class of path as `xl_c01x_rd` (577-580).
- Cost per private access: X_CAPTURE, X_ROUTE, X_DEAD = 3 fabric clocks plus instruction fetches, against 1-2 µs today.
- Side effect: private accesses do not reach X_BUS, so the USB paddle-trigger alias (1533-1537) does not fire for `$C078-$C07B`.

### 5.2 Barrier exemption, without touching the capture enable

The X_CAPTURE hold uses only a 4-bit compare of `core_addr` on purpose. README_TURBO records that the first banked-mirror build failed at -0.063 ns on capture-enable paths. Do not add address bits there. Instead:

1. Add `video_barrier_capture = video_sync_active || video_full_flush` and use it at line 1907 instead of `video_barrier`.
2. Leave line 1949 as is: a $Cxxx access with `video_mirror_pending` goes to X_VIDEO_WAIT.
3. In X_VIDEO_WAIT (1957-1962): leave when `!video_barrier || (xl_bankreg_private && !video_full_flush && !video_sync_active)`. This decode uses registered `cycle_addr_q`, like `video_exposure_access` already does at line 1413.
4. Add `addr == 16'hC079` to the write list in `video_exposure_access` (1396-1400).
5. Add `$C071/$C073/$C079` to `vtw_is_bank_steer` (finding A).

ASSUMED, must be proven by an assertion: `video_active_pending_q` implies `video_mirror_mode_q`. Both are set by `video_fast_accept` (1464-1469). If the implication fails, step 1 would let a $Cxxx access through early. Waiting in X_VIDEO_WAIT instead of X_CAPTURE is otherwise equivalent: both states are already in `rw_flush_unsafe` (1606-1607) and `video_sync_core_idle` (1421-1422).

### 5.3 TURBO invalidation

Replace the 19-bit compare with a 15-bit one: the 12 non-bank switch bits plus the three `is_base` flags. Line 1185 hard-codes `[18:0]` and line 1199 casts to `TranslateState`; both need a dedicated packed struct.

Why this is safe:
- The caches hold only shadow-backed pages (1212-1215).
- A translation lands in the shadow only when the decoded bank is 0 or 1 (`vtw_shadow.sv:47-58`).
- So a bank number affects cached translations only through "bank == 0". A change between two nonzero banks alters no cached mapping.

Effect: R changes between extended banks no longer flush the caches. This also helps existing `$C073` software. It reduces logic on `turbo_invalidate`.

### 5.4 Video capture, mirror and bank tagging

- No tag is needed on posted writes. `xl_is_posted` already requires translated bank 0 or 1, and the translated address now uses W. With W nonzero, aux writes go to the line cache and are never posted.
- The direct renderer record and the coalescer use `xl_decoded[16:0]` (1380, 1449), the translated write address. Correct without change.
- Required invariant, unchanged from today: motherboard-side W equals private W whenever a posted or mirrored aux byte reaches the bus. It holds because `$C073` and `$C079` writes are real bus cycles preceded by the exposure flush and the bank-steer drain.
- R and Z on the motherboard side go stale during a session. That is harmless: INH reads are suppressed while vTW owns the bus, ZP/stack/LC writes are never posted (`vtw_bus_engine.sv:48-61`), and handback is a Ctrl-Reset, which clears all three.
- `vtw_video_bank_sync` needs no change. It steers only RAMWRT and PAGE2.

ASSUMED: ONE//e (`virtual_motherboard`) behaves the same. I did not trace that path.

## 6. RamWorks line cache

**Doom's case needs nothing.** R extended with W = 0 means writes go to BRAM and never touch the line cache. The cache sees reads only.

**It thrashes when R and W are both extended and different.** Each copied byte then costs a dirty write-back, a source fill and a destination fill. That is three PSRAM operations at one admission per Apple cycle (`psram_simple.sv:232-240`), so about 3 µs per byte (estimate).

**What Option 3 needs from the cache: two lines, fully associative.**
- Arrays of 2 for `rwc_valid_q`, `rwc_dirty_q`, `rwc_line_q`, `rwc_data_q`, plus a 1-bit LRU.
- Either entry serves reads or writes. Do not build a "read line" and a "write line": two copies of one PSRAM line would need coherence logic.
- Timing: compute both 21-bit hit compares during X_ROUTE from `cycle_xl_decoded_q` and register them as `rwc_hit_q[1:0]`. X_RW_LOOKUP then starts from registered hits. X_ROUTE already exists, so no latency is added.
- Register the write line into a new `rw_req_wline_q` when the request is issued (2057-2061), replacing the direct assign at 1065.
- Both flush sequencers must loop over entries: the held-core write-back (1783-1795) and the ARM flush (1804-1828). `arm_rw_flush_done` fires only when both entries are clean and invalid.
- No new X state is needed. Cost: about 90 FFs + 64 for `rw_req_wline_q`, 120-150 LUTs.

## 7. Memory API, SmartPort, vTW off

| Area | Change |
|---|---|
| Memory API | None to the data path. Add the feature bit. The hold/flush (`memory_api_hw.c:109-140`) relies on the RTL sequencer, which must flush both lines. |
| SmartPort snapshot | Widen from 22 to 29 bits: keep [20:14] = W, add R in [28:22]. Put Z in a second register, because 36 bits do not fit (`smartport_card.sv:625`). Edit `vtw_core_top.sv:531-548`, `smartport_card.sv:101,155-173,461,502-503`, `apple_top.sv:1711`. |
| SmartPort PS code | `sp_vtw_memory_phys` (`smartport_service.c:351-387`): pick Z below $0200, W for write access, R for read access, in both the plain and the 80STORE branch. |
| SmartPort DMA flush/hold | Protocol unchanged. |
| vTW off | The feature works. `$C078-$C07A` writes are ordinary bus cycles; the motherboard tracker decodes them; the early translate picks R or W with `rw_early`. Read forwarding compares the full 24-bit address (`psram_simple.sv:167-170`), so R different from W stays coherent. `psram_simple.sv` needs no edit. |

ASSUMED: PS firmware and bitstream always ship together, so the snapshot format can change freely.

## 8. Cost and timing risk

| Item | FF | LUT (est.) | Risk | Mitigation |
|---|---:|---:|---|---|
| Bank registers, flags, SPLIT (2 live trackers) | ~60 | ~30 | Low | Registered inputs only |
| Translate mux (3 live instances) | 0 | +25, minus 3 adders | Low-medium: on the capture path and the motherboard early decode | Store bank + 1 in registers |
| Private serve + readback | 0 | ~30 | Low | Registered decode |
| Barrier restructure | 0 | ~10 | Medium: changes where accesses wait | Assertion + existing video benches |
| TURBO compare 19 to 15 bits | -4 | -5 | Low | None needed |
| Second cache line | ~155 | ~150 | Medium: 64-bit muxes | Registered hits and write line |
| SmartPort snapshot | ~14 | ~10 | Low | AXI read path only |
| **Total** | **~285** | **~250-300** | | 0 BRAM |

The documented worst paths start at `ab_read_r.addr[11]` into the capture FIFO (`docs/FABRIC_TIMING_MARGIN_PLAN.md:49-52`). Option 3 adds no logic between the bus address and that FIFO except the translate mux, which is why the +1 must move into the registers.

## 9. Alternative: linear far-memory port

**Design.**
- Registers in `$C078-$C07F`: two ports, each with ADDR_LO, ADDR_MID, ADDR_HI and DATA. DATA auto-increments.
- Far address 0 maps to PSRAM `0x020000` (RamWorks bank 1), so the port covers only PSRAM-backed banks.
- Under vTW: a DATA access in X_ROUTE loads `cycle_xl_decoded_q` with the far address, sets the route to CACHE, and enters one new state that repeats the memory branch of X_ROUTE into X_RW_LOOKUP. It uses the same line cache, so it stays coherent with MMU access.
- With vTW off: a new serve source in `psram_simple` keyed at `sss_en`.
- Cost: about 60 FFs, 150-200 LUTs, one X state. It needs the same barrier exemption (5.2) and the same second cache line.

**Comparison.**

| | Option 3 | Far port |
|---|---|---|
| Random read, bank unchanged | one `LDA (zp),Y` | 2-4 I/O instructions |
| Addressing modes | all | absolute on DATA only |
| Code placement | must be outside $0200-$BFFF while RAMRD = 1 | anywhere |
| Usable bytes per bank | 48,640 ($0200-$BFFF) | 65,536 |
| Touches shared translate | yes | no |
| Writes to SHR | native, mirrored | not possible without a bank tag in the 16-bit posted queue |
| TURBO interaction | needs 5.3 | none |

**Choice: Option 3.**
- It is the smaller change and the faster per access.
- It removes the bounce buffer in exactly the renderer case: read extended, write SHR.
- It works with vTW off at no extra cost.
- It fits software already built around a bank register.

I would add the far port afterwards if engine code that cannot move to the language card needs far reads. It reuses 5.1, 5.2 and section 6.

Neither option reduces the cost of a line-cache miss (one admission per Apple cycle). That dominates truly random access and belongs to the cache and admission options.

## 10. Staged plan

| Stage | Content | Ships alone? |
|---|---|---|
| 0 | Add `$C071/$C073` to `vtw_is_bank_steer`. TURBO compare on `is_base` flags (5.3, single bank for now). | Yes; speeds up existing `$C073` software |
| 1 | `globals.sv` and `soft_switch_manager.sv` changes. All four registers as plain bus cycles. `$C079` added to exposure and bank steer. | Yes; functionally complete, slow |
| 2 | Private serve (5.1) and barrier restructure (5.2) | Yes; this is the performance stage |
| 3 | SmartPort snapshot + PS mapping. AMEM feature bit. | Required before release |
| 4 | Two-entry line cache and looped flush sequencers | Optional for Doom |
| 5 | Far port | Optional |

Run a full build after stages 1, 2 and 4, against the +0.200 ns gate.

## 11. Testbench plan

| Bench | Checks |
|---|---|
| New `tb_translate_split.sv` | Exhaustive over switch bits, address class, `rw`, and 3 values per bank (0, 1, 127). Compare against a reference model. With R = W = Z it must equal the old function bit for bit. |
| `tb_vtw_system.sv` (extend the phase checks at 424-494) | Old value held through X_CAPTURE, applied at X_ROUTE, visible to the next access, for `$C078/$C079/$C07A/$C07B`. `$C073` reloads all three. Writes ignored with SPLIT off. RES clears everything. |
| `tb_vtw_system.sv`, new program | Code in LC, RAMRD = RAMWRT = 1, R = 5, W = 0. Read bank 6 from the PSRAM model, write aux `$2000`. Check shadow aux content, renderer record address `0x012000`, and posted cycle. |
| `tb_vtw_turbo.sv` (RamWorks model at 155-198) | No invalidation on R 5 to 6. Invalidation on R 0 to 5 and 5 to 0. No stale byte after R 0 to 5 to 0. |
| `tb_vtw_video.sv`, `tb_vtw_video_policy.sv` | With active mirror bytes pending: `$C078` write completes in a bounded number of fabric clocks; `$C079` and `$C073` writes wait for the drain. Assertion: `video_active_pending_q` implies `video_mirror_mode_q`. |
| `tb_vtw_engine_unit.sv` | Queue a posted aux write, then issue a `$C073` sync write. The posted cycle must reach the bus first. This should fail before stage 0. |
| `tb_psram_simple.sv` | vTW off, R = 3, W = 4: write then read the same Apple address hits different PSRAM lines; forwarding only on a full address match. |
| `tb_vtw_system.sv`, cache | R = 5, W = 9 copy loop: PSRAM operation count near 2 per 8 bytes. R = W same line: read-after-write coherent. ARM flush with both lines dirty: two write-backs, then one `arm_rw_flush_done`. Core reset with both dirty: both written. |
| `tb_smartport_shortcut.sv` + PS host test | Snapshot carries R, W, Z. Block read lands in bank W, block write sources bank R, ZP buffer uses Z. |
| Regression | Every script listed in README_TURBO "Validation and build", plus the RamWorks 8 MB contract test. |