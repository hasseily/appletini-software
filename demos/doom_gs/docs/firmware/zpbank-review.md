**Review: zero-page bank pair (`$C069` enable)**

I read all of this in the F1.2.1 snapshot. I did not build or simulate anything, and I did not modify any file. Paths are relative to the snapshot root.

**Verdict:** there is no blocker. The state-based classification in section 1.2 covers all 70 core states correctly, and the race proof in section 2.4 holds. Six major corrections are needed before this goes into the design document.

## Findings

| # | Sev | Finding |
|---|---|---|
| 1 | Major | Value 127 selects physical bank 128, which is outside the 8 MB PSRAM |
| 2 | Major | The D4 watch on logical `$00xx` breaks the byte/register invariant and lets aux-zero-page code load the pair |
| 3 | Major | The D5 reasoning is wrong: a stray `$C069` write almost always has an effect |
| 4 | Major | The IRQ contract has holes: the ROM exit path and slot-firmware screen holes |
| 5 | Major | The pair outlives the program that armed it |
| 6 | Major | A static regression check fails, and the test plan omits it |
| 7 | Minor | Invert the flag: list the 6 data states, not the ~45 code states |
| 8 | Minor | Leave the same-page `STA abs,X` false read unredirected |
| 9 | Minor | `zp_rd = $FF` makes `$00` the write byte |
| 10 | Minor | The TURBO veto can remove an input from `turbo_hit` instead of adding one |
| 11 | Minor | Small inaccuracies and missing documents |

**1. Major: bank 127.**
- Evidence:
  - `psram_simple.sv:35-37` says bank 128 "would cross the 8 MB boundary and is not served".
  - `MEMORY_API_MAX_AUX_BANK 126U` (`memory_api.h:13`).
  - `sp_vtw_memory_phys` rejects bank 128 (`smartport_service.c:383-385`).
  - `psram_driver.sv:16,456` sends a 24-bit address to one 8 MB chip. The alias target is an assumption (A): most likely `0x00xxxx`.
- The spec's "as `$C073`=127 already produces" is true, but it is an existing hole, not a precedent.
- Correction: the valid range is 1-126. Values 127-255 mean "follow".

**2. Major: D4.**
- Evidence: with ALTZP on, `translate_apple_addr` sends `$00xx` to the aux bank (`globals.sv:255-257`). A logical watch therefore latches writes that never reach main `$06`.
- Consequences:
  - Code that runs with ALTZP on (ProDOS `/RAM`, AUXMOVE-style code, 128K applications) can set the pair nonzero after the program zeroed it.
  - An IRQ handler that saves main `$06` then saves the wrong value.
- Correction:
  - Load only on writes whose captured decode is main zero page, `cycle_xl_decoded_q[23:8]==0`. Every operand is registered.
  - The register then always equals main `zp_rd`/`zp_wr` for CPU writes.
- Cost: code with ALTZP on cannot change the pair. That needs the ROM IRQ entry to switch to main zero page before `JMP ($03FE)` (question Q3).

**3. Major: D5 and stray writes.**
- An effect needs a `$C069` write and then any nonzero store to byte V or V+1. Zero page is written constantly, so the second condition is near certain.
- `tb_vtw_usb_joystick.sv:306` itself writes `$A5` to `$C069`.
- The read-bank review (finding 6) raised the same issue.
- Correction: default the kill switch off, and turn it on by a PS profile key. Alternatively, require an unlock (Q1).

**4. Major: interrupts.**
- The spec's assumption (A) that "the //e ROM IRQ entry makes no other data access to `$0200-$BFFF`" is unverified.
- The user handler's RTI returns into ROM code that restores the memory state. That code runs after the handler has restored the pair to nonzero.
- Slot firmware (SSC, mouse, clock) keeps its state in screen holes `$0478-$07FF`, which are redirected. The SSC ROM in this repository uses `$0478`/`$04F8`/`$0578`/`$05F8`.
- Correction:
  - Contract: hold SEI while either byte is nonzero, or own `$FFFE` in language-card RAM and zero the pair before chaining.
  - The author should check the shadow ROM that `vtw_service` loads (Q3).

**5. Major: persistence.**
- Ctrl-Reset and a CORE_RUN drop clear the pair (`vtw_core_top.sv:352`). ProDOS QUIT, `-FILE`, or a BRK into the Monitor do not.
- The next program's writes to `$06`/`$07` then remap its data.
- Correction: the contract requires `$C069`=0 before exit. `vtw status` and the debug register must show the armed pair.

**6. Major: tests.**
- `scripts/test_vtw.py:318` and `:492` require the literal text `translate_apple_addr(translate_state_from_sss(vsss),`. Section 3.2 replaces it, so the script fails.
- Correction: amend `test_vtw.py` in stage 0, and list it.

**7. Minor: flag polarity.**
- Only `ST_MEM_READ`, `ST_DECIMAL_EXTRA`, `ST_RMW_READ`, `ST_RMW_MODIFY`, `ST_RMW_WRITE` and `ST_MEM_WRITE` can put a data address in `$0200-$BFFF` (`w65c02_core.sv:1049-1069`).
- A positive `data_ea` flag is one LUT, and D1 follows automatically.
- A missed state then fails toward "follow the switches", never toward fetching code from bank N.
- The table in 1.2 is correct, but it takes 45 entries to verify.

**8. Minor: `STA abs,X` false read.**
- It has no side effect in `$0200-$BFFF`. Classing it as data only evicts the line (as the spec itself notes).
- Correction: do not redirect it.

**9. Minor: `zp_rd = $FF`.**
- The write byte wraps to `$00`, which slot firmware uses (the SSC ROM's `LOC0`).
- Correction: treat `$FF` like 0, which disables the pair.

**10. Minor: veto placement.**
- `turbo_hit` already decodes `cycle_addr_q[15:12]!=C` (`:1237`).
- Correction: register one bit at capture, `cycle_turbo_ok_q = core_addr[15:12]!=C && !redirect_d`, and use it in place of that 4-bit term. This lowers the fan-in on the `core_en` path.

**11. Minor: small fixes.**
- The low 19 bits of the widened struct are the 18 new bits plus bank bit 0, not only the new fields.
- `$C073` ignores bit-7 values (`soft_switch_manager.sv:141-144`). The pair maps them to "follow". That is acceptable, but say so.
- Also amend `README_W65C02_CORE.md` (new port) and `README_MEMORY_API.md` (feature bit).
- The detection probe overwrites a byte of physical bank 2. Save and restore it.

## (1) Confirmed

| Claim | Evidence |
|---|---|
| `sync` covers only `ST_FETCH` | `w65c02_core.sv:998-1001` |
| The address and `rwb` depend only on `state_q` and registers; the state is one-hot | `:979-1157`, `:205-206` |
| The 1.2 classification is complete and correct | all states, `:118-195` |
| Every write to `$00xx` ends its instruction | `:1553-1567` |
| No TURBO skip removes a real operand or data access | `:1276-1680` |
| Writes pass `X_ROUTE` exactly once, or commit in `X_TURBO_DONE` with `core_en` | `vtw_core_top.sv:1245,1307,1949-1971` |
| The visibility margin (W+4, and W+2 after TURBO E5) | `:1912-1953` |
| Only banks 0 and 1 are posted, overlaid or tracked at `$9DF8` | `:552-569,1876-1882` |
| The read hit compares only the logical tag; fills need `xl_shadow_valid` | `:1212-1239`, `vtw_turbo_cache.sv:64-81` |
| `wire [18:0] turbo_mapping` | `:1185` |
| Redirected TURBO path: CAPTURE, TURBO_DONE, ROUTE, RW_LOOKUP, RW_DONE | `:1949-2028` |
| `$C069` is not an exposure access and is decoded nowhere | `:1390-1401`, `onee_motherboard_io.sv:250-277` |
| `core_res_n` includes `core_run`; RES_HOLD and non-RUN drop it | `:352`, `vtw_service.c:236-245` |
| `pause` and `rw_hold_q` gate only `core_en` | `:1523` |
| RamWorks is on for II+ and ONE//e sessions | `boot_menu_service.c:320-335` |
| The monitor recomputes the translation from `cycle_translate_state_q` | `tb_vtw_system.sv:371-395` |
| The snapshot is 22 bits, latched at the CTRL write; `SP_REG` 7 is free | `smartport_card.sv:155-173,295-301,502-503,625` |
| `vtw_ctrl_q[9]` is unused | `apple_top.sv:2006-2167` |
| README's "no new soft switches" is at 278-281 | `README_VIRTUAL_TRANSWARP.md` |

## (2) Corrected specification

**Enable.** A write to `$C069` sets the pair and clears both registers.

| Value A | Effect |
|---|---|
| `$00` or `$FF` | Pair off |
| `$01-$FE` | `zp_rd = A`, `zp_wr = A+1` |

- The write still goes to the bus. Reads of `$C069` are unchanged.
- The pair is armed only when `ZPB_ENABLE && vtw_ctrl_q[9] && ramworks_en` holds.
- Kill-switch default: off. A PS profile key turns it on.

**Loading.**
- While the pair is on, a committed CPU write whose captured decode is main zero page loads the register named by its address.
- The commit is at `X_ROUTE`, or at `X_TURBO_DONE` with `core_en`.
- The value applies on the next edge.
- Writes to aux zero page (ALTZP) are ignored.

| Stored value v | Meaning |
|---|---|
| 0, or 127-255 | Follow RAMRD, RAMWRT, 80STORE, PAGE2 and `$C073` |
| 1-126 | Physical bank v+1 (`$C073` numbering) |

**Scope.** A redirect applies when all three hold:
- `data_ea` = 1;
- the address is in `$0200-$BFFF`;
- the register for the cycle's direction is nonzero.

A redirect beats RAMRD, RAMWRT, 80STORE and PAGE2.

| Cycle | Redirected |
|---|---|
| `ST_MEM_READ`, `ST_DECIMAL_EXTRA`, `ST_RMW_READ/MODIFY` | By `zp_rd` |
| `ST_MEM_WRITE`, `ST_RMW_WRITE` | By `zp_wr` |
| Opcode, operand, dummy PC, `STA abs,X` false read, JMP pointer, vector, stack, zero-page pointer | Never |

**RTL.**
- **Core:** add output `data_ea`, the OR of the six one-hot state bits.
- **`globals.sv`:**
  - `TranslateState` gains `sw_zpb_rd_en`, `sw_zpb_wr_en`, `sw_zpb_rd_bank[6:0]`, `sw_zpb_wr_bank[6:0]`.
  - `translate_state_from_sss` sets them to 0.
  - After the 80STORE block in the `$0200-$BFFF` branch, the direction's enable selects `{1'b0,bank}+1`.
- **`soft_switch_manager`:** gets constant-0 assignments only.
- **`vtw_core_top`:**
  - A local function gates the enables with `data_ea` and is used at `:512` and `:1919`.
  - `:1185` becomes `TranslateState turbo_mapping = translate_state_from_sss(vsss)`.
  - Registered `cycle_turbo_ok_q` replaces the `[15:12]!=C` term in `turbo_hit`.
- **Posting:** redirected banks are 2-127, so they are never posted or shadowed.

**Reset.**

| Event | Pair |
|---|---|
| `!rstn`, `!core_res_n` (RES#, Ctrl-Reset, CORE_RUN drop, session end) | Off |
| Armed signal falls | Off |
| `pause`, SmartPort or memory-API hold, speed change | Kept |
| Program exit without `$C069`=0 | **Kept**: software's duty |

**Consumers.**
- SmartPort snapshot bits 22 and 23 hold `{wr_en, rd_en}`.
- `sp_vtw_memory_phys` returns -1 for the active direction, so the byte path is used.
- A new read-only register `8'hB0` exposes the pair.
- `vtw status` prints the pair.
- Memory API feature bit 8 is added.

**Software contract.**
1. Enable: `lda #PAIR / sta $C069 / stz PAIR / stz PAIR+1`. `$06`/`$07` is suggested.
2. Before any ROM, ProDOS, SmartPort or 80-column call, and before exit: zero both bytes. Before exit, also write 0 to `$C069`.
3. Hold SEI while either byte is nonzero, or own `$FFFE` in language-card RAM and zero the pair before chaining to any firmware handler.
4. Tables used in the hot loop go in zero page, the stack page or language-card RAM.
5. If `rd≠wr` and both are nonzero, the single line cache thrashes. Use a bounce buffer or memory API COPY.

**Tests.**
- The spec's bench list, plus `data_ea` against the six states for every opcode.
- An aux-zero-page write that must not load the pair.
- Values 127 and 255 mean follow.
- `$FF` disables.
- The amended `scripts/test_vtw.py`.

**Cost.** About 55-85 LUTs, about 36 FFs, 0 BRAM. The only medium-risk path is `core_addr` to `cycle_xl_decoded_q[23:16]`, which gains one final select. Run one full build per stage against +0.200 ns.

## (3) Questions for the firmware author

1. **Arming:** is the default off plus a profile key acceptable? Or do you want a software unlock, such as two `$C069` writes (A, then ~A)?
2. **Bank range:** confirm that physical bank 128 aliases PSRAM `0x00xxxx`, and whether anything lives there.
3. **Shadow //e ROM IRQ path:**
   - Does it switch to main zero page and stack before `JMP ($03FE)`?
   - Does its entry or exit read `$07F8` (MSLOT) or any other address in `$0200-$BFFF`?
4. **D4:** do you accept main-zero-page-only loading?
5. **Pointer-only option:** should redirection apply only to `(zp),Y`, `(zp)` and `(zp,X)` data? That keeps absolute tables in main, and it narrows the IRQ and ROM exposure.
6. **Main for reads:** should a value name main (bank 0) for reads? That is safe, because reads are never posted.
7. **Bus writes:** is a `$C069` write electrically safe on a II+ (D7 contention) and on a //e? Should `$C069` be served privately instead?
8. **Probe:** should the probe be gated by machine ID? A `$C069` write on a IIgs is undefined here.
9. **SmartPort:** is v1 (fallback bits) enough, or do you want v2 (the exact bank in `SP_REG` 7)?
10. **Save states:** does any PS save/restore or freeze path need to carry the pair registers?