# Option 3: separate read and write bank selection for extended memory (review)

# Adversarial review: Option 3 (split read/write bank)

Everything below was checked by reading the RTL in the snapshot. Nothing was simulated or built. The `linear_text_overlay_card.sv` and `boot_menu_card.sv` citations and the testbench line numbers were not checked.

## Findings

| # | Severity | Finding |
|---|---|---|
| 1 | Blocker | Motherboard tracker never learns SPLIT, so it ignores `$C079` |
| 2 | Major | W and Z as separate bus-visible registers are unnecessary; a much smaller design gives the same Doom benefit |
| 3 | Major | Benefit is not quantified; line-cache misses and RAMRD toggles dominate |
| 4 | Major | Interrupt and OS-call contract is missing |
| 5 | Major | Aborted `$C079` bus write leaves fabric and motherboard W different |
| 6 | Minor | Timing argument for moving the +1 is wrong |
| 7 | Minor | Timing evidence cited is stale and the path claim is false |
| 8 | Minor | Private access latency is 4 clocks, not 3, when a mirror is pending |
| 9 | Minor | ONE//e is not gated |
| 10 | Minor | TURBO invalidate after a private write is a new fastest case |

### 1. Blocker: motherboard SPLIT never set

- The plan makes `$C07B` writes private (section 3 table; `xl_bankreg_private` excludes only the `$C079` write).
- The plan also says `$C078-$C07A` writes are ignored while SPLIT is off, and that the shared `soft_switch_manager` gives both trackers the same behaviour.
- The motherboard instance (`apple_top.sv:348`) only sees real bus cycles. It never sees the `$C07B` enable, so its SPLIT stays 0 and it drops every `$C079` write.
- Sequence: `$C073`=5 (both sides 5), then `$C079`=0. Private W = 0, motherboard W = 5.
- Aux SHR writes are then posted (`vtw_core_top.sv:565-569`, decoded bank 1) and carry only the 16-bit address (`1506-1507`). The motherboard translates them to bank 6.
- Result: `apple_cycle_capture.sv:67-72` rejects the byte, and `psram_simple.sv:136,377,386` queues it into PSRAM bank 6. That is silent data corruption plus a blank screen.
- Correction: make `$C07B` writes real bus cycles with exposure and bank steer, or adopt finding 2, which removes the problem.

### 2. Major: simpler design

- Under vTW the motherboard-side bank only matters for writes. INH read serving is off while vTW owns the bus (`psram_simple.sv:134-135`).
- Doom needs W = Z = 0 and R = N. Z different from W is never used.
- Reduced design:
  - Keep `$C071/$C073` exactly as today. It is W and Z.
  - Add one private read-bank register R and one private enable bit, held in `vtw_core_top` or behind a parameter in `vtw_ssm`.
  - With the enable off, R follows `$C073`.
  - The motherboard and `video_physical_ssm` instances tie R to the bank register, so synthesis folds the mux and their timing is unchanged.
- This removes `$C079`, Z, the stale motherboard R/Z state, the SPLIT tracking problem, and the non-vTW SmartPort snapshot path (`smartport_card.sv:156-158`).
- Cost: the feature does not exist with vTW off. Doom cannot run usefully at 1 MHz anyway.
- If a separate W address is still wanted, issue the `$C079` write on the bus as `$C073` by remapping `eng_req_addr` (`vtw_core_top.sv:770`). The motherboard tracker then stays unmodified.

### 3. Major: benefit not quantified

- A line miss costs at least one admission per Apple cycle (`psram_simple.sv:229-240`), about 1 µs. A 100-texel column touches roughly 12 or more lines (my estimate).
- A bounce buffer costs two `$C073` writes per column. So bank switching is already the smaller cost per column.
- The real gain of a private R is avoiding `video_full_flush` (`vtw_core_top.sv:1408-1413`), which serialises the whole mirror at each switch.
- Code must run outside `$0200-$BFFF` while RAMRD = 1. Reaching main data needs `$C002/$C003`, which is a bus cycle, a barrier wait, a bank-steer drain (`vtw_bus_engine.sv:72`) and a TURBO invalidate. The plan does not address this.
- R changing between 0 and nonzero still invalidates both caches under 5.3.
- Correction: state these limits, and measure with `vtw status` counters before committing to stages 2 and later.

### 4. Major: interrupts and OS calls

- IRQ and NMI reach the core (`vtw_core_top.sv:359,368-369`).
- Any handler or OS code that sets RAMRD and RAMWRT and expects to read back what it wrote breaks when R differs from W. Examples are /RAM and AUXMOVE-style code.
- Readback for save and restore exists only under vTW.
- Correction: the contract must say R is restored to W (one `$C073` write) before any OS call and with interrupts enabled, or SEI is held while split.

### 5. Major: aborted `$C079` write

- `vtw_core_top.sv:435-438` documents that a re-hold can abort a switch access after the private tracker applied it.
- The replay logic restores only RAMWRT, PAGE2 and 80STORE (`1435-1438`).
- This hazard already exists for `$C073`. The plan adds a second register with the same exposure and does not mention it.
- Correction: finding 2 avoids adding it. Otherwise extend the bank-sync replay to W.

### 6. Minor: the +1 adder

- The adder at `globals.sv:251` is fed by a registered bank. It sits in parallel with the `core_addr` cone, not in series.
- Removing it does not shorten the `core_addr` to `cycle_xl_decoded_q` path. Expect equal depth, not one level better.
- Storing bank + 1 is still harmless.

### 7. Minor: timing evidence

- `docs/FABRIC_TIMING_MARGIN_PLAN.md:49-52` describes a +0.012 ns build with 74 BRAM tiles. It is not the current build.
- README_TURBO.md:236 names the current limit as ONE//e selection to a Disk II bit-offset enable.
- The translate output is registered at `soft_switch_manager.sv:249-250` before capture uses it (`apple_cycle_capture.sv:93-94`). The translate mux is not on the `ab_read_r.addr[11]` to FIFO path.
- The real risk is the `core_addr`/`core_rwb` to `cycle_xl_decoded_q` path (`vtw_core_top.sv:511-515,1920`). The plan's "low-medium" is fair for that path, provided the motherboard instances are left alone.

### 8. Minor: latency

- With a mirror pending the sequence is X_CAPTURE, X_VIDEO_WAIT, X_ROUTE, X_DEAD (`1949-1950`).
- A RamWorks read that hits the line in TURBO takes 5 clocks: X_CAPTURE, X_TURBO_DONE, X_ROUTE, X_RW_LOOKUP, X_RW_DONE (`1952-1953,1970-1971,2027-2028`).

### 9. Minor: ONE//e

- Existing private shortcuts are gated by `!virtual_motherboard` (`vtw_core_top.sv:577,587,593`). `xl_bankreg_private` is not.
- `onee_motherboard_io.sv:271` triggers paddles on every `$C07x` access, which a private serve would skip.
- Correction: gate it, or state the behaviour change.

### 10. Minor: invalidate timing

- Every mapping change today passes through X_BUS. A private write is the first case where the next X_CAPTURE follows within two clocks.
- By reading, it is safe: `vsss` changes at the X_ROUTE edge, `turbo_invalidate` is high during X_DEAD (`1199,1211`), and the valid bits clear before the next capture (`vtw_turbo_cache.sv:128-131`).
- Correction: add a directed test for it.

## (1) Claims confirmed

- Every row of the section 2 table that I opened matches, including the line numbers for `vtw_core_top.sv`, `globals.sv`, `soft_switch_manager.sv`, `vtw_shadow.sv`, `psram_simple.sv`, `apple_cycle_capture.sv`, `smartport_service.c` and `memory_api.c`.
- The snapshot is 22 bits with bit 21 as the wide flag, exported as `{10'h0, snapshot}` (`smartport_card.sv:625`).
- Finding A is real by reading: `$C073` is not in `vtw_is_bank_steer` (`vtw_bus_engine.sv:70-74`), so `sync_flush_wait` is not set (`455-458`) and the sync write can overtake posted writes (`848`). Fix it regardless of Option 3.
- Finding B is right: the barrier holds any `$Cxxx` access (`1414-1415,1907`) and `$C073` forces a full flush.
- The 5.2 restructure is sound. X_VIDEO_WAIT already applies the same barrier term because the core is stalled with `core_addr` stable, and both states are in `rw_flush_unsafe` and `video_sync_core_idle`.
- The 5.3 reasoning is sound: caches fill only from shadow-valid accesses, and shadow-valid means decoded bank 0 or 1.
- Private updates need no new code, because `ssm_apply_pulse` fires on every X_ROUTE (`1254`).
- Handback is by Ctrl-Reset (README_VIRTUAL_TRANSWARP.md:109), and the private tracker resets whenever the session is disabled (`vtw_core_top.sv:418`).
- The two-line cache needs no new X state, and its FF count is derivable (87 per line plus 64 for the write line).
- 0 BRAM is correct.

## (2) Corrected summary

Build a reduced Option 3 that exists only inside vTW.

**Interface.** `$C071/$C073` stay unchanged and remain the write and ZP/LC bank, as a real bus cycle with exposure. Add a private register R at `$C078` and a private control/ID at `$C07B`. With the enable off, R follows `$C073`. With it on, reads of `$0200-$BFFF` under RAMRD, and display-window reads under 80STORE+PAGE2, use R. Both reset on hard reset and RES. There is no `$C079` and no Z.

**RTL.**
- `TranslateState` gains one 8-bit read-bank field. `translate_apple_addr` selects it when `rw_in` = 1 in the non-ZP, non-high-RAM branch.
- The motherboard and `video_physical_ssm` instances tie it to the existing bank, so their logic is unchanged.
- `vtw_core_top`: private serve in X_ROUTE ahead of `d2_fast_hit`, gated by `ramworks_en` and `!virtual_motherboard`. X_VIDEO_WAIT exemption as in plan 5.2. TURBO compare on the 12 switch bits plus two base flags.
- SmartPort snapshot: add R in [28:22]. The PS mapping uses R for read access.

**Independent fix, ship first.** Add `$C071/$C073` to `vtw_is_bank_steer`.

**Software contract.** Code runs from ZP, stack or LC while split. Restore R = W before OS calls and before enabling interrupts. Detect through the AMEM feature bit.

**Deferred.** The two-line cache and the far port. Neither helps Doom's read-only extended access.

**Cost (my estimate).** About 100-150 LUTs, about 40 FFs, 0 BRAM. The only sensitive path is `core_addr` to `cycle_xl_decoded_q`, with one extra mux input per bank bit. Run a full build after the translate change, against the +0.200 ns gate.

**Tests.** The plan's translate, TURBO and barrier benches, plus the fast invalidate case and a posted aux write with R nonzero, checking the motherboard-side decode is `0x01xxxx`.

## (3) Verdict

Do not build the plan as written. It corrupts PSRAM (finding 1) and carries W/Z complexity that Doom does not use.

The reduced form is worth building. It is small, stays off the motherboard-side paths, and removes the full mirror flush from the renderer's bank switching.

Expect a moderate gain, not a large one. Line-cache miss admission at about 1 µs stays the dominant cost for random 4 MB access, so the cache and admission work should rank above this. Fix finding A now in either case.