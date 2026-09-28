# Private read-bank register at $C069 (spec)

# Private read-bank register at $C069 (design section)

Line numbers refer to the F1.2.1 snapshot. Nothing was simulated or built, and no file was modified. **V** means I read it in the RTL or source at the cited line. **A** means assumption. All LUT/FF figures are my estimates.

## 0. Summary

| Item | Decision |
|---|---|
| Address | `$C069`, write-only. Reads keep today's meaning on every host. |
| State | One register in the private tracker `vtw_ssm`: effective read bank + 1 (8 bits) and an "is base" flag. No enable flip-flop. |
| `$C071/$C073` | Unchanged real bus cycle. Still the bank for writes, ZP, stack and LC. Each accepted write also reloads R. |
| `$C069` write, bit 7 = 0 | R = data[6:0]. |
| `$C069` write, bit 7 = 1 | R = current `$C073` bank (private resync, no bus cycle). |
| Scope of R | Reads of `$0200-$BFFF` with RAMRD on. Not display windows under 80STORE. |
| Motherboard side | No functional change. New struct fields are constants there and fold away. |
| Cost | About 40-70 LUTs, 30-40 FFs, 0 BRAM. |
| Kill switch | `vtw_ctrl_q[9]` (free today) plus a compile-time parameter. Off means F1.2.1 behaviour. |

Four decisions need your ruling: D1 (section 2.2), D2 (section 3.4), D3 (section 3.1) and D4 (section 3.5).

## 1. What decodes `$C06x` today

### 1.1 Decoders (V unless marked)

| Place | Decode | Covers `$C069`? |
|---|---|---|
| `vtw_core_top.sv:587-590` `xl_btn_rd` | Reads of `$C061-$C063` only (`[15:2] == 14'h3018`), needs `iiplus_buttons_zero`, `!virtual_motherboard` | No. The A3 alias is not covered. |
| `vtw_core_top.sv:594-601` `xl_usb_status_rd` | Reads of `$C06x` with `[2:0] != 0`, needs `usb_joystick_enabled` | Yes, reads only. `$C069` is USB button 0. |
| `vtw_core_top.sv:602-603` `xl_usb_trigger` | `$C070` only | No |
| `vtw_core_top.sv:1533-1537` paddle trigger alias | `$C071-$C07F` | No |
| `vtw_core_top.sv:1101-1103` `sd_paddle` | `$C064-$C067`, `$C070` | No |
| `vtw_core_top.sv:1109-1112` `sd_floating_io` | `$C030-$C05F`, `$C019` | No |
| `vtw_core_top.sv:1277-1281` | ONE//e reads of `$C06x`: bit 7 from the bus, bits 6:0 from the scanner | Reads only |
| `vtw_core_top.sv:1390-1401` `video_exposure_access` | `$C080-$CFFF`, `$C05x`, listed writes | No |
| `vtw_bus_engine.sv:70-74` `vtw_is_bank_steer` | `$C000-$C007` writes, `$C054-$C057` | No |
| `soft_switch_manager.sv:174-190` | `addr[7:1]` of `$00-$07`, `$28-$2B`, `$2F` | No (`$C069` gives `7'h34`) |
| `onee_motherboard_io.sv:152-169` | Reads of `$C060-$C06F`, A3 ignored | Reads only. No write side effect (`:255-277`). |
| `apple_cycle_capture.sv` VidHD and AN3 rules | `$C022/29/34/35`, `$C05E/F` | No |
| `boot_menu_card.sv:77,581` | Snoops `$C061` reads after reset | No |
| Other cards in `hdl/apple` | My grep found no `$C06x` claim | No |

IIgs: RamWorks and vTW stay off on an identified IIgs (`README_IIGS_SAFETY.md:70`, `README_VIRTUAL_TRANSWARP.md:109`). The register cannot exist there.

### 1.2 Behaviour of `$C069` today

| Host | READ | WRITE |
|---|---|---|
| //e, vTW | Bus cycle. Motherboard returns the `$C061` alias in bit 7. With a USB joystick, bit 7 is ORed with or replaced by USB button 0 (`:2009-2016`, `:2132-2139`). | Goes to `X_BUS` (`:2023-2025`): a real write cycle. No fabric state changes. Waits on the video barrier like any `$Cxxx` access (`:1414-1415`, `:1907`). |
| II+, vTW | Same path. `xl_btn_rd` does not match, so the read reaches the bus. | Same. A: the II+ `$C06x` strobe enables the button multiplexer on D7 regardless of R/W, so a write causes a one-cycle D7 conflict. |
| ONE//e | Claimed by `onee_motherboard_io`, returns `pushbuttons[0]` in bit 7. Covered by `tb_onee_motherboard_io.sv:326-327`. | Virtual bus cycle, no effect. |

A: a `$C069` write has no effect on a physical //e motherboard. I could not check this in the RTL.

### 1.3 What may change

- **May change:** a `$C069` write, when the feature is armed.
- **Must not change:** every `$C069` read, every other `$C06x` access, and `$C069` writes when the feature is not armed.

### 1.4 Is write-only necessary? Confirmed.

- A readback would collide with the USB status serve, which already owns `$C069` reads.
- It would break the ONE//e alias that a bench checks.
- It would add an input to the `core_data_in_q` mux.
- Consequence: software keeps its own copy of R. Interrupt handlers cannot save it.

Moving from `$C078/$C07B` to `$C069` also removes two problems from the earlier review: the USB paddle-trigger alias and the ONE//e paddle trigger fire only on `$C07x`.

## 2. Encoding

### 2.1 Options

| Option | Verdict |
|---|---|
| Single write-only register, bit 7 as "follow" | **Chosen** |
| Separate enable address | Rejected. Uses a second alias address and adds decode for no gain. |
| Enable through the memory API | Not for v1. It needs SmartPort in slot 7 and PS involvement after every reset. It remains possible later by letting the PS drive the kill-switch bit. |

### 2.2 D1: what a `$C073` write does to R

| Model | `$C069`=5 then `$C073`=2 | Extra state |
|---|---|---|
| **Reload (recommended)** | R = 2 | none |
| Sticky (the encoding as literally stated) | R = 5 until `$C069` = `$80` | 1 FF, one mux |

- The two models differ only in that sequence.
- Reload keeps RamWorks-aware software working: it writes `$C073` and then reads.
- Reload costs Doom nothing. Doom holds `$C073` at 0.
- Under reload, "split enabled" just means R differs from the bank.

### 2.3 Reset and gating

| Event | R afterwards | Evidence |
|---|---|---|
| Fabric reset (`!rstn`) | 0 | same place as `soft_switch_manager.sv:129` |
| Apple RES# low: power-on, Ctrl-Reset, takeover pulse | 0 | same place as `:284` |
| Session disabled and mirror drained | 0 | `core_ab.res`, `vtw_core_top.sv:418` |
| Session start | 0 | `enable` must rise before reset release (`:44-46`) |
| ARM re-hold (`core_run` low), pause, speed change | kept, like the bank | V: `vsss` is not reset by these |
| `ramworks_en` low | forced to follow the bank; `$C069` writes ignored | new |
| Kill switch low | same | new |
| Accepted `$C071/$C073` write | data[6:0] | new (D1) |

- A: with a physical aux card or the RAM tab off, the PS keeps `ramworks_en` low (`README_VIRTUAL_TRANSWARP.md:113`). The bank then stays 0 and so does R.
- A: on a II+ host the PS keeps RamWorks off (`README_VIRTUAL_TRANSWARP.md:366-367`), so the feature is inert there.

## 3. RTL

### 3.1 `hdl/globals.sv`

| Line | Edit |
|---|---|
| after 172 (`SoftSwitchState`) | add `sw_rdbank_valid`, `sw_rdbank_full[7:0]`, `sw_rdbank_is_base` |
| after 194 (`TranslateState`) | add `sw_rdbank_valid`, `sw_rdbank_full[7:0]`. Width goes from 19 to 28. |
| after 213 | copy both fields |
| after 235 | declare `logic [7:0] q_rd_bank_full;` |
| after 251 | `q_rd_bank_full = st.sw_rdbank_valid ? st.sw_rdbank_full : q_aux_bank_full;` |
| 264-265 | replace, see below |
| 266-268 | **unchanged** |

```
q_bank_sel = rw_in ? (st.sw_auxread  ? q_rd_bank_full  : 8'd0)
                   : (st.sw_auxwrite ? q_aux_bank_full : 8'd0);
```

**D3: display-window reads use the `$C073` bank, not R.** This differs from the review's summary. Reasons:

- Under 80STORE the window follows PAGE2, not RAMRD, so your stated semantics do not reach it.
- Read-modify-write on display memory stays coherent.
- A: the 80-column firmware reads aux text through 80STORE and PAGE2. It keeps working while R differs.
- The override lines stay untouched.

Consequence: with 80STORE and HIRES on, `$2000-$3FFF` is a hole in the R bank.

### 3.2 `soft_switch_manager.sv`

- Add `parameter bit RDBANK = 1'b0` and an input `rdbank_en`.
- Lines 83-96: drive the two new `xlate_st` fields.
- `RDBANK = 0` (motherboard `apple_top.sv:348`, `video_physical_ssm` `vtw_core_top.sv:440`): the three fields are constant 0. `q_rd_bank_full` reduces to `q_aux_bank_full` by constant propagation, and the read/write mux has two identical inputs. No reliance on adder merging.
- `RDBANK = 1` (`vtw_ssm`, `vtw_core_top.sv:427`): `sw_rdbank_valid` is constant 1. Registers, in their own `always_ff`:

```
load73 = existing condition at :141-143
load69 = rdbank_en && ramworks_en && data_en && !rw && is_c0xx && addr[7:0]==8'h69
src    = (load69 && data[7]) ? ss_ramworks_bank : data[6:0]
if (load73 || load69) { rd_full_q <= {1'b0,src}+1; rd_is_base_q <= (src==0); }
if (!rdbank_en || !ramworks_en) follow ss_ramworks_bank
if (!ab_read.res) reset to 1 / 1
```

- No new code is needed to apply the write. `ssm_apply_pulse` fires on every `X_ROUTE` (`vtw_core_top.sv:1254`) from the registered tuple (`:419-424`).
- Five ONE//e benches instantiate this module. Keep the new port inside the parameter so they compile unchanged.

### 3.3 Mandatory fix at `vtw_core_top.sv:1185`

- `wire [18:0] turbo_mapping` hard-codes the old struct width.
- After the widening it would silently drop nine bits. With the new fields appended at the end, those are 80STORE, RAMRD, RAMWRT, ALTZP, PAGE2, HIRES, INTCXROM, SLOTC3ROM and INTC8ROM.
- Replace it with an explicit compare vector (section 3.6).

### 3.4 Private serve

```
wire xl_rdbank_wr = rdbank_en && ramworks_en && xl_is_bus && xl_is_write &&
                    (cycle_addr_q == 16'hC069);
```

- Add `else if (xl_rdbank_wr) xstate_q <= X_DEAD;` as the last branch before the `X_BUS` default at `:2023`.
- All operands are registered. `X_DEAD` already completes private accesses (`:2197-2201`) and is in `video_sync_core_idle` (`:1425`).
- No side effect fires in `X_DEAD`: `cycle_usb_trigger_q` is 0, `sd_hit` is 0, `cnt_invalid_q` is untouched.
- The write no longer appears in `dbg_last_sync` or the I/O trace.

| Case | Latency of the write cycle |
|---|---|
| TURBO or full speed, no mirror | `X_CAPTURE`, `X_ROUTE`, `X_DEAD`: 3 clocks (22.5 ns) |
| Mirror pending, no active bytes | adds `X_VIDEO_WAIT` (`:1949-1950`): 4 clocks |
| Active mirror bytes pending, no exemption | held in `X_CAPTURE` (`:1907`) until they drain, 131 clocks per byte |
| Same, with the exemption in 3.5 | 4 clocks |
| 1 MHz or divided mode | `X_DEAD` waits for `pace_ok`. Cycle timing is unchanged. |

**D2: gating.**

| Gate | Recommendation |
|---|---|
| `ramworks_en` | Yes |
| Kill switch | Yes |
| Speed mode | No. Pacing is still applied in `X_DEAD`. |
| `virtual_motherboard` | No. ONE//e has no write side effect at `$C06x`. The conservative choice is to gate it for the first release. |

With the serve off, the register still loads and the write is a bus cycle.

### 3.5 D4: barrier exemption (needed for the gain)

Aux SHR pages are active mirror pages, so `video_active_pending_q` is set almost continuously while drawing. Without an exemption every R change waits for the drain.

1. Line 1907: use `video_sync_active || video_full_flush` in place of `video_barrier`. This removes logic from the capture enable.
2. Line 1949 stays. A `$Cxxx` access with a pending mirror goes to `X_VIDEO_WAIT`.
3. Line 1960: leave when `!video_barrier || (xl_rdbank_wr && !video_full_flush && !video_sync_active)`.

- `$C069` is not an exposure access, so it never forces a full flush.
- Safe because the write has no bus side effect and does not change the write mapping.
- A, to be proven by an assertion: `video_active_pending_q` implies `video_mirror_mode_q`. Both are set by `video_fast_accept` (`:1464-1469`).
- This step changes where every `$Cxxx` access waits. It overlaps the "quiet switches" change and should be built once.

### 3.6 TURBO caches

**Without "caches survive mapping changes":**

- Compare vector: the 12 switch bits, the 7-bit bank as today, plus `vsss.sw_rdbank_is_base`.
- R changes between nonzero banks do not invalidate. R changes between 0 and nonzero do.
- Correct because the caches fill only from shadow-valid accesses (`:1212-1215`), and shadow-valid means decoded bank 0 or 1 (`vtw_shadow.sv:47-58`).
- Fast invalidate is a new case. By reading it is safe: `vsss` changes at the `X_ROUTE` edge, the invalidate is high during `X_DEAD`, and the valid bits clear (`vtw_turbo_cache.sv:128-131`) on the edge that enters `X_CAPTURE`.

**With it:**

- The mapping term is gone, so correctness rests on `cycle_cacheable_q`.
- It must come from the R-aware translation. For reads of `$0200-$BFFF` with RAMRD on it must use `rd_is_base`, not the bank's flag.
- Otherwise a read from bank 6 has `decoded[16] = 0`, matches the "main" space of a surviving entry, and returns wrong data.

### 3.7 RamWorks line cache

- The hit test is physical: `rwc_line_q == xl_decoded[23:3]` (`:1058-1060`). R only changes the decoded address.
- No flush or invalidate is needed on an R change.
- Doom's case (bank 0 for writes) sends writes to BRAM. The line sees reads only.
- R and W both extended and different thrashes the single line. That is unchanged and out of scope.
- A line hit in TURBO stays at 5 clocks.

### 3.8 Aborted access

The re-hold hazard documented at `vtw_core_top.sv:435-438` does not apply. A private write has no bus half to lose.

## 4. Consumers outside the core

| Consumer | Uses the caller's mapping? | Change |
|---|---|---|
| SmartPort ROM byte path | Yes, through the core itself | None. It is R-aware automatically. |
| SmartPort direct block WRITE source | Yes, read mapping (`smartport_service.c:948-957`, `write_access = 0`) | **Required**, below |
| SmartPort block READ destination | Write mapping | None |
| Memory API endpoints | No, explicit bank (`memory_api.c:38-55`) | Feature bit only |
| Disk II private reads | No (`vtw_core_top.sv:704-709`) | None |
| ARM shadow host port | No, 18-bit physical (`:219-226`) | None |
| `vtw status` | Prints 11 switch bits (`vtw_service.c:1246-1263`) | Add R |

### Snapshot fields

| Bits | Content |
|---|---|
| 21:0 | unchanged |
| 29:22 | `vsss.sw_rdbank_full` (1..128) |
| 30 | constant 1: read-bank field valid |

| File | Edit |
|---|---|
| `vtw_core_top.sv:216`, `:531-548` | port to `[30:0]`, prepend the two fields |
| `apple_top.sv:1711` | width |
| `smartport_card.sv:101,155,461` | width |
| `smartport_card.sv:156-173` | bus-path snapshot: upper 9 bits zero |
| `smartport_card.sv:625` | `{1'b0, sss_snapshot_q}` |
| `smartport_service.c:72-74` | `SP_SSS_RDBANK_SHIFT 22U`, `SP_SSS_RDBANK_MASK 0xFFUL`, `SP_SSS_RDBANK_VALID_BIT (1UL << 30)` |
| `smartport_service.c:351-387` | read bank = valid ? field : `aux_bank`. Use it only in the RAMRD term for read access. The 80STORE branch keeps `aux_bank`. |

### Debug

- New read-only register `CARD_CTRL_REG_VTW_RDBANK = 8'hAD` (free). The status register at `8'h75` is full.
- Layout: `[6:0]` private bank, `[15:8]` R + 1, `[16]` R differs, `[17]` armed, `[31]` constant 1.
- `vtw_service.c`: one more line after 1263.

## 5. Video

- Only writes reach the posted queue, the renderer record and the coalescer. `xl_is_posted` requires `xl_is_write` (`:565`), and `video_fast_req` is reached only through it.
- Capture accepts writes only (`cap_rw == 0`).
- R enters the translation only when `rw_in` is 1.
- A posted aux write uses the `$C073` bank. With bank 0 it decodes to `0x01xxxx` privately. The bus cycle carries 16 bits (`:1506-1507`), and the unchanged motherboard tracker decodes it with its own bank 0.
- Parked read cycles are translated with the motherboard's bank. Read serving is suppressed while the vTW owns the bus (`psram_simple.sv:134-135`).

**Proving test** (new task `rdbank_video_case` in `tb_vtw_turbo.sv`, beside `direct_video_banks` at `:1118`). Code runs from the stack page. Sequence: `$C073`=0, RAMWRT on, RAMRD on, `$C069`=5, `LDA $4000`, `STA $2000`.

| Check | Expected |
|---|---|
| Read value | the PSRAM model's bank 6 byte |
| `cycle_xl_decoded_q` at the write | `24'h012000` |
| `video_record_addr` | `17'h12000` |
| `dut.video_physical_sss.addr_decode_late` at the mirrored cycle's `data_en` | `24'h012000`, enable set |
| During the read | no record, no coalescer write, no posted entry, no bus cycle |

## 6. Software contract

**Where code may run while RAMRD is on and R differs:**

| Region | Allowed |
|---|---|
| `$0000-$01FF` | Yes |
| `$D000-$FFFF` | Yes |
| `$C100-$CFFF` firmware | Yes |
| `$0200-$BFFF` | No. Opcode fetches come from bank R. |

- Main data in `$0200-$BFFF` is not reachable without a RAMRD toggle, which is a bus cycle.
- Keep 80STORE off while reading textures.

**Interrupts.**

- Vector fetch and stack pushes follow ALTZP and the `$C073` bank. R does not affect them (V, `globals.sv:257-262`).
- A: the //e ROM interrupt entry saves the memory state, selects main and restores on exit. R survives it.
- R matters only to a handler that turns RAMRD on and reads `$0200-$BFFF`.
- Rule: hold SEI while R differs, or make sure no installed handler reads aux through RAMRD.

**Before any ProDOS or firmware call:** `LDA #$80 / STA $C069`, which costs 3 clocks. Then set RAMRD as that call requires.

| Routine | Effect if R differs |
|---|---|
| /RAM driver, AUXMOVE aux to main | reads the wrong bank (A) |
| XFER to aux | executes from bank R (A) |
| 80-column firmware | unaffected under D3 (A) |
| SmartPort block write | correct after section 4 |

**Detection.**

1. `MEMORY_API_FEATURE_RDBANK 8U` in `memory_api.h`, reported at STATUS offset 8. It needs a backend hook, for example `uint16_t (*features)(void *ctx)`, that reads bits 31 and 17 of the new register.
2. Without SmartPort, from code in ZP, stack or LC:
   - Put different bytes at one address in banks A and B using `$C073`.
   - Select A, turn RAMRD on, write B to `$C069`, read the address.
   - B's byte means the feature is present. Finish with `$C069` = `$80`.

**Old firmware.** The write is a bus cycle of 1-2 µs plus the barrier wait, with no state change. The probe reads A's byte.

**Reset.** Ctrl-Reset clears R. Software must set it again.

## 7. Cost, timing, plan, tests

### Cost

| Item | FF | LUT |
|---|---:|---:|
| R register, flag, load logic | 9 | 15-20 |
| Translate mux, vTW instance only | 0 | 8-12 |
| Private serve and exemption | 0 | 6-10 |
| TURBO compare | 1 | 1-2 |
| Snapshot | 9 | 0-5 |
| Debug register | 0 | 10-15 |
| Registered copies of the wider struct | up to 18, mostly pruned | 0 |
| **Total** | **about 30-40** | **about 40-70** |

0 BRAM.

### Timing

| Path | Change | Risk |
|---|---|---|
| `core_addr`/`core_rwb` to `cycle_xl_decoded_q[23:16]` (`:511-515`, `:1920`) | one more registered data input per bank bit | Low to medium. The only sensitive path. |
| Motherboard early and late decode | none after constant folding | Check that the LUT counts of both instances are unchanged |
| `X_ROUTE` priority chain | one term | Low |
| Capture hold (`:1907`) | term removed | Medium: changes where accesses wait |
| `turbo_invalidate` to `core_en` | one more bit | Low |

### Stages

| Stage | Content | Expected |
|---|---|---|
| 0 | Struct fields, translate edit, line 1185 fix, `RDBANK = 0` everywhere | Bit-identical. The build proves nothing moved. |
| 1 | `vtw_ssm` with `RDBANK = 1`, kill switch, TURBO compare, snapshot, PS mapping, debug register | Complete but slow |
| 2 | Private serve | 3-clock writes |
| 3 | Barrier exemption | Bounded latency while drawing |
| 4 | Feature bit, README updates | Release |

- Full build after stages 0, 1, 2 and 3, against the +0.200 ns gate.
- `README_VIRTUAL_TRANSWARP.md:278-281` says "No new soft switches, ever". It must be amended.

### Tests

| Bench | Extension |
|---|---|
| New `tb_translate_rdbank.sv` | With valid = 0, the new function equals a copy of the old one over all switch bits, address classes, `rw` and banks 0, 1, 127. With valid = 1, only RAMRD reads of `$0200-$BFFF` use R. |
| `tb_vtw_system.sv` | Extend the phase checker at `:424-494` to `$C069`. Extend `load_program` (`:760`): bit 7 resync, `$C073` reload, RES clears, ignored when not armed. |
| `tb_vtw_turbo.sv` | New `rdbank_program` beside `bank_program` (`:835`): no invalidate on 5 to 6, invalidate on 0 to 5, no stale byte after 0, 5, 0. New `rdbank_fast_invalidate`. New `rdbank_video_case`. New barrier case beside `deferred_video_case` (`:1233`). Hold during `X_DEAD` using `freeze_core` (`:646`). |
| `tb_vtw_usb_joystick.sv` | `alias_case` (`:354`): a `$C069` read still returns USB button 0 when armed. A write does not trigger the paddles. |
| `tb_onee_motherboard_io.sv` | Unchanged. `:326-327` must pass. |
| `tb_smartport_shortcut.sv` | Snapshot width at `:33` and `:325`. Native snapshot has upper bits zero (`:436-447`). |
| PS host test | Table test of `sp_vtw_memory_phys`. I found no existing harness for this file. |
| Regression | Every script in `README_TURBO.md` "Validation and build" |

## 8. Not verified

- The Apple ROM and ProDOS behaviour listed as A in section 6.
- The motherboard's electrical response to a `$C06x` write.
- The PS code that sets `ramworks_en` (register `0x62`) for a physical aux card or a II+ host.
- Whether Vivado keeps both motherboard-side instances at identical LUT counts. Stage 0 measures it.