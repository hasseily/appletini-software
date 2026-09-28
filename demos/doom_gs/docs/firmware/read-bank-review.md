# Private read-bank register at $C069 (review)

# Adversarial review: private read-bank register at $C069

Everything below was read in the F1.2.1 snapshot; nothing was simulated or built. Paths are relative to `<appletini-one>`.

**Verdict:** no blocker found. The core mechanism is sound, but six major corrections are needed before the text goes into the design document.

## Findings

| # | Severity | Finding |
|---|---|---|
| 1 | Major | The II+ assumption is false: RamWorks is on for an accelerated II+ |
| 2 | Major | An existing bench fails, and a documented contract changes |
| 3 | Major | R is placed in the wrong module; a simpler placement gives the same result |
| 4 | Major | A core reset without RES# leaves R split |
| 5 | Major | Timing risk is understated; "bit-identical" is not a valid expectation |
| 6 | Major | No arming: any stray `$C069` write remaps reads persistently |
| 7 | Minor | Gating is stated two ways |
| 8 | Minor | Follow-mode pseudo-code overrides the load with the old bank |
| 9 | Minor | "The bank then stays 0" is not guaranteed |
| 10 | Minor | The D3 hole is larger than stated |
| 11 | Minor | "131 clocks per byte" is a lower bound, not a figure |
| 12 | Minor | Test plan gaps |

### 1. Major: II+ hosts are not inert

- Spec 2.3 cites `README_VIRTUAL_TRANSWARP.md:366-367` to say the PS keeps RamWorks off on a II+. That README text is stale.
- `ps_sources/frontend/boot_menu_service.c:321-335`: `vtw_owns_aux` sets `rw_want` in any vTW session without a physical aux card. The comment says "an accelerated II+ gets the same 8 MB".
- `vtw_core_top.sv:1915-1918` confirms the full //e MMU model applies on a II+ host.
- Consequence: the register is live on II+. The private serve is the better behaviour there, because it removes a `$C06x` write strobe from the II+ bus.
- Correction: state that the feature is live on II+. Never let R load from a cycle that also goes to the bus (see finding 7).

### 2. Major: `tb_vtw_usb_joystick.sv` fails

- The bench ties `ramworks_en` to 1 (`:139`), writes `$A5` to all of `$C060-$C06F` (`:306`), and checks each write reached the physical bus: "C06x write was swallowed" (`:323`). It does this for every kind, including II+ and ONE//e.
- With the feature armed, `$C069` fails that check. The spec's test table only mentions `alias_case`.
- The contract is also written down at `vtw_core_top.sv:595` and `README_USB_JOYSTICK.md:302-304` ("writes ... take their normal physical path").
- Correction: run that bench with the feature off (must pass unchanged) and armed (expect 0 physical writes at index 9 only). Amend both texts.

### 3. Major: keep R out of `soft_switch_manager` and `SoftSwitchState`

- The spec adds three fields to `SoftSwitchState` (44 references in `hdl/`), a parameter and a port on `soft_switch_manager`, which has three synthesised instances (`apple_top.sv:348`, `vtw_core_top.sv:427,440`) and five bench instances.
- "Keep the new port inside the parameter" is not legal SystemVerilog. A port cannot depend on a parameter.
- Only `vtw_core_top` consumes R. It calls `translate_state_from_sss(vsss)` at exactly three places (`:512`, `:1185`, `:1919`).
- Correction:
  - Hold `rd_full_q[7:0]` and `rd_is_base_q` in `vtw_core_top`.
  - Load them at the `X_ROUTE` edge from `cycle_addr_q`, `cycle_wdata_q`, `cycle_rw_q`, qualified by `core_active`. This is the same edge `vtw_ssm` uses (`ssm_apply_pulse`, `:1254`).
  - `TranslateState` gains `sw_rdbank_valid` and `sw_rdbank_full`. `translate_state_from_sss` sets both to 0.
  - One local function in `vtw_core_top` overrides them and replaces the three calls.
  - `soft_switch_manager.sv`, `SoftSwitchState`, `apple_top.sv:348` and the ONE//e benches are not edited.

### 4. Major: core reset without RES#

- `core_res_n = enable && core_run && ab_read.res` (`vtw_core_top.sv:352`). The private tracker resets only on `core_ab.res` (`:418`).
- The PS holds the core with no RES# in every non-RUN, non-RES_HOLD state (`vtw_service.c:243-244`).
- The core then restarts from the reset vector with R still split. The ROM rewrites RAMRD, but nothing ever rewrites `$C069`.
- The bank has the same exposure today, but software that uses RamWorks writes `$C073`. No existing software writes `$C069`.
- Correction: force R to follow the bank whenever `core_res_n` is low. `turbo_invalidate` already fires on `!core_res_n` (`:1206`), so no cache work is needed.

### 5. Major: timing

- `README_TURBO.md:231-236`: the clean full build reached +0.192 ns and missed the gate. +0.205 ns needed an extra `AggressiveExplore` post-route pass.
- Stage 0 changes `TranslateState` width and two registers (`cycle_translate_state_q`, `turbo_mapping_q`). Expect functional equivalence. Do not promise a bit-identical result.
- The translate edit adds `core_rwb` as a select between two bank sources on each of `cycle_xl_decoded_q[23:16]`. `core_rwb` is a late core output. I rate this medium, not low to medium.
- D4 step 1 edits the enable of the widest capture in the FSM (`:1907-1945`). It removes a term, which should help, but it must be its own build.
- Correction: one full build per stage, and a stated fallback (drop D4, keep the private serve) if a stage misses +0.200 ns.

### 6. Major: no arming

- Today a `$C069` write is a harmless bus cycle. After the change, any stray write remaps `$0200-$BFFF` reads until the next `$C073` write or reset.
- The spec does not say who sets `vtw_ctrl_q[9]` or its default. Two PS builders must be edited: `vtw_ctrl_value` (`vtw_service.c:158`) and `vtw_onee_ctrl_value` (`:191`). `vtw_apply_ctrl_live` compares the full read-back (`:249-250`).
- Correction: the design document must state the default and the owner of the bit. See the questions.

### 7. Minor: gating stated two ways

- Section 2.3 says `$C069` writes are ignored when not armed. Section 3.4 says "with the serve off, the register still loads and the write is a bus cycle".
- Correction: one signal, `rdbank_armed = rdbank_en && ramworks_en` (plus `!virtual_motherboard` if the author chooses), gates both the load and the serve.

### 8. Minor: follow-mode ordering

- In the 3.2 pseudo-code the "follow" statement comes after the load and reads the registered bank. On the `$C073` edge it overrides the load with the old bank. R is one clock late.
- It is harmless today because a `$C073` write is a bus cycle, so the next capture is many clocks later.
- Correction: make follow and load mutually exclusive (`if (!armed) follow; else if (load) ...`).

### 9. Minor: bank is not cleared when `ramworks_en` falls

- `soft_switch_manager.sv:141-144` gates only the load. The bank keeps its last value.
- `ramworks_en` changes at session start and end (`boot_menu_service.c:332-344`).
- The follow rule covers R. The assumption in 2.3 should be deleted.

### 10. Minor: D3 hole

- The display window is `$0400-$07FF` always, plus `$2000-$3FFF` when HIRES is on (`globals.sv:249-250`).
- With 80STORE on, `$0400-$07FF` is also a hole in the R bank. The spec lists only `$2000-$3FFF`.

### 11. Minor: drain time

- One mirrored byte needs one posted bus cycle, so 131 clocks is the minimum. The coalescer also scans pages (`vtw_video_coalescer.sv:40-47`). Write "at least 131 clocks per byte".

### 12. Minor: test gaps

Add: IRQ taken while split; core re-hold while split (finding 4); `ramworks_en` falling while split; `pause` during `X_DEAD`; II+ host kind; ONE//e kind; kill switch toggled while split.

## (1) Claims confirmed

| Claim | Evidence |
|---|---|
| `TranslateState` is 19 bits; `turbo_mapping` hard-codes it | `globals.sv:181-195`, `vtw_core_top.sv:1185,1199` |
| Appending fields makes line 1185 drop the nine named switch bits | packed struct, first field is the MSB |
| No RTL decode claims `$C069` writes | `vtw_core_top.sv:587-603,1101-1112,1394-1400`, `vtw_bus_engine.sv:70-74`, `soft_switch_manager.sv:174-190` |
| `$C069` read is USB button 0, ORed or replaced | `vtw_core_top.sv:596-611,2009-2016,2132-2139` |
| ONE//e has no `$C06x` write side effect | `onee_motherboard_io.sv:255-277` |
| `X_DEAD` completes with no side effect for this address | `:1521,1534,1101-1103,2197-2201` |
| 3 clocks, or 4 with a pending mirror | `:1949-1953,1960-1961` |
| Fast invalidate after a private write is safe by reading | `:1199,1211`, `vtw_turbo_cache.sv:128-131` |
| Caches fill only from shadow-valid accesses, banks 0 and 1 | `:1212-1215`, `vtw_shadow.sv:47-58` |
| The is-base compare is sufficient | follows from the row above |
| `video_active_pending_q` implies `video_mirror_mode_q` | `vtw_video_coalescer.sv:54-57,102-110`, `vtw_core_top.sv:1464-1471` |
| Aux `$2000-$9FFF` writes are always active mirror pages | `vtw_video_policy.sv:31` |
| Line-cache hit test is physical | `vtw_core_top.sv:1058-1060` |
| Snapshot is 22 bits, latched at the CTRL write | `smartport_card.sv:155-173,502-503,625` |
| SmartPort write source uses the read mapping | `smartport_service.c:350-387,948-957` |
| Memory API endpoints carry an explicit bank | `memory_api.c:38-55` |
| INH read serving is off while vTW owns the bus | `psram_simple.sv:134-135` |
| `vtw_ctrl_q[15:9]` and register `8'hAD` are free | `apple_top.sv:2118-2128,515-517`, `card_control_regs.h:333-353` |
| Bench anchors exist at the cited lines | `tb_vtw_turbo.sv:646,835,1118,1233`, `tb_vtw_system.sv:424,760`, `tb_vtw_usb_joystick.sv:354`, `tb_onee_motherboard_io.sv:326-327` |
| IIgs blocks RamWorks and vTW | `README_IIGS_SAFETY.md:68-71` |

## (2) Corrected specification

**Interface.** `$C069` is write-only. Bit 7 = 0 sets R = data[6:0]. Bit 7 = 1 sets R = the current `$C073` bank. `$C071/$C073` are unchanged bus cycles and also reload R. Reads of `$C069` are unchanged on every host. R applies to reads of `$0200-$BFFF` with RAMRD on. Display windows under 80STORE (`$0400-$07FF`, and `$2000-$3FFF` with HIRES) keep the `$C073` bank.

**Hosts.** Live on //e and on an accelerated II+. ONE//e is gated off in the first release. Not present on a IIgs.

**State.** In `vtw_core_top`: `rd_full_q[7:0]` (bank + 1) and `rd_is_base_q`. One gate, `rdbank_armed = vtw_ctrl_q[9] && ramworks_en && !virtual_motherboard`, controls both load and serve.

| Event | R |
|---|---|
| `!rstn` | base |
| `core_ab.res` low (RES#, or session disabled and mirror drained) | base |
| `core_res_n` low (ARM hold, session end) | follows bank |
| `rdbank_armed` low | follows bank |
| Accepted `$C071/$C073` write, armed | data[6:0] |
| `$C069` write, armed | data[6:0], or the bank if bit 7 |

**RTL.**
- `globals.sv`: `TranslateState` gains `sw_rdbank_valid` and `sw_rdbank_full[7:0]`, both 0 from `translate_state_from_sss`. Lines 264-265 select the read bank when `rw_in` is 1. Lines 266-268 are unchanged.
- `vtw_core_top.sv`: a local function fills the two fields and replaces the calls at 512, 1185 and 1919. Line 1185 becomes an explicit compare vector: 12 switch bits, the 7-bit bank, `rd_is_base_q`.
- Private serve: `X_ROUTE` branch to `X_DEAD`, last before the `X_BUS` default, all operands registered.
- Barrier exemption (separate stage): line 1907 holds on `video_sync_active || video_full_flush`. `X_VIDEO_WAIT` releases a `$C069` write when neither is set. Add the assertion that active-pending implies mirror mode.
- `soft_switch_manager.sv`, `SoftSwitchState` and `apple_top.sv:348` are not edited.

**Consumers.** SmartPort snapshot grows to 31 bits: R + 1 in [29:22], valid in [30]. `sp_vtw_memory_phys` uses R only in the RAMRD term for read access. `vtw status` prints R from new read-only register `8'hAD`.

**Flush rules.** TURBO caches invalidate when `rd_is_base_q` changes. The RamWorks line cache needs nothing.

**Software contract.** While R differs, code runs from `$0000-$01FF`, `$C100-$FFFF`. Write `$80` to `$C069` before any ProDOS or firmware call. Hold SEI, or install no handler that reads aux through RAMRD. Software keeps its own copy of R. Ctrl-Reset clears R.

**Cost (estimate).** 50-90 LUTs, 30-40 FFs, 0 BRAM.

**Stages, one full build each against +0.200 ns.**

| Stage | Content |
|---|---|
| 0 | Struct fields, translate edit, line 1185 fix, valid = 0 everywhere |
| 1 | R register, compare, snapshot, PS mapping, debug register |
| 2 | Private serve |
| 3 | Barrier exemption; dropped if it misses the gate |
| 4 | Feature bit and README amendments |

**Tests.** The spec's benches, plus `tb_vtw_usb_joystick` status case in both modes, and the cases in finding 12.

**Documents to amend.** `README_VIRTUAL_TRANSWARP.md:278-281` and `:366-367`, `README_USB_JOYSTICK.md:302-304`, the comment at `vtw_core_top.sv:595`.

## (3) Questions for the firmware author

1. **Arming.** Should `vtw_ctrl_q[9]` default on, or follow a config-menu setting? Do you want a software unlock as well, given that a stray `$C069` write now has a lasting effect?
2. **II+ hosts.** RamWorks is on for an accelerated II+ today. Should the register be live there?
3. **ONE//e.** Gate it off for the first release, or enable it from the start?
4. **D1.** Do you accept that every `$C073` write reloads R?
5. **D3.** Do you accept that display windows under 80STORE use the `$C073` bank, not R?
6. **Core hold without RES#.** Should R follow the bank, as I recommend, or persist like the bank does?
7. **`$C06x` write on a physical //e.** Is it electrically harmless? This only matters for old firmware and for the feature being off.
8. **Doom's write path.** Does Doom write aux SHR directly while it reads textures? If it draws to a back buffer outside `$2000-$9FFF`, the barrier exemption (stage 3) gives little and can be dropped.
9. **Debug register.** Is `8'hAD` acceptable, or do you prefer to fold R into an existing diagnostic word?