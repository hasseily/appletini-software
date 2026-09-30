# FW-S1: Phasor port writes that do not open the slot-4 slowdown window (specification)

This is a further change for the design document "vTW Memory Fast Path: Design". It turns the request FW-S1 of `docs/research/native-sound.md` 4.4 into an RTL and PS change. The owner decided on 2026-09-30 to ship a Doom profile with `vtw.slowdown.cycles=32` now and to do FW-S1 later with the other firmware changes.

Line numbers refer to the F1.2.1 snapshot of `<appletini-one>`. `gssquared/...` is a local emulator checkout beside this repository (`~/Documents/Repos/gssquared`), cited only for its notes on mb-audit and Skyfox. `core_top` means `hdl/apple/vtw_core_top.sv`. **V** means I read it at the cited line. **A** means an assumption, an estimate, or a claim about software whose source I did not read. LUT and FF figures are estimates. **Nothing was built or simulated, and no firmware file was changed.**

## 0. Summary

| Item | Decision (recommended) |
|---|---|
| What changes | A CPU **write** to `$C400-$C4FF` whose address has bits 6 and 5 clear and whose low nibble is 0, 1, 2, 3, D, E or F (ORB, ORA, DDRB, DDRA, IFR, IER, ORA without handshake) no longer reloads the slowdown counter. |
| What does not change | Every read. Every read-modify-write (its read cycle hits). Writes to T1, T2, SR, ACR, PCR. Writes that also reach the SSI-263 (address bit 5 or 6 set). The mode switch `$C0C0-$C0CF`. Every other slot and region. The bus cycle itself: an exempt write is still a real 1 MHz bus cycle. |
| Scope | Slot 4 only, the virtual Phasor's fixed slot (V `apple_top.sv:1396`). |
| Where | `core_top`: one flop `cycle_via_quiet_q`, loaded in `X_ROUTE` from registered bits, and one AND term in the I/O-select leg of `sd_hit`. Nothing on the `X_CAPTURE` path. |
| Control | Register `0x6B` bit 9, today reserved in the RTL and never written by the PS. 0 gives F1.2.1 behaviour exactly. The PS sets it only when the virtual Phasor is on and a new profile key asks for it. |
| Default | Off. On in the Doom profile. Reconsider after the hardware checks of section 6. |
| Cost | About 3-6 LUTs and 1 FF. 0 BRAM. |
| Gain (a2vm model, not hardware) | Doom music 13.0-29.6 ms a second at window 512, 4.4-9.8 at window 32, 2.7-4.3 with FW-S1 at window 512 (V `src/sound/README.md`, cost table). |

## 1. What opens the window today

### 1.1 Configuration path (V)

| Step | Where |
|---|---|
| Menu defaults: mask 0 ("all regions full speed"), window 512 | `ps_sources/frontend/config_menu.c:75-76` |
| Mask bits: slots 1-7 in bits 0-6, floating bus bit 7, paddle bit 8, bit 9 retired ("legacy video", config 104) | `config_menu.c:77-82`, `:2488-2501` |
| Presets 256, 512, 1024, ..., 65535 | `config_menu.c:84-86` |
| Profile keys `vtw.slowdown.mask` (masked to `0x3FF`) and `vtw.slowdown.cycles` (0-65535, clamped) | `config_menu.c:3547-3552` |
| The load paths strip bit 9 from the stored mask | `config_menu.c:2501`, called at `:3987`, `:4343` |
| **Forced slot 4:** when `mockingboard_slot4_enabled`, OR in slot 4, and **a window of 0 becomes 512** | `config_menu.c:4660-4692` (the rule at `:4679-4684`) |
| The slot-4 checkbox cannot be cleared while the Phasor is on | `config_menu.c:4745-4750`; drawn dimmed, `config_menu_device_tabs.c:699-717` |
| Toggling the Phasor re-applies the mask | `config_menu_phasor.c:384-390` |
| Push to the PL: `mask & 0x1FF` in `[8:0]`, window in `[31:16]` of register `0x6B`. Bit 9 is therefore always 0. | `vtw_service.c:716-727`, `card_control_regs.h:336-343` |
| Register: 32-bit `vtw_slowdown_q`, reset 0, full AXI write and readback | `apple_top.sv:1915`, `:2482`, `:2748-2751`, `:2947` |
| Wiring: `slow_region_en = [9:0]`, `slow_duration = [31:16]` | `apple_top.sv:2171-2172` |
| Port comment: `[6:0]` slots 1-7, `[7]` floating bus, `[8]` paddle, **`[9]` reserved**, duration 0 disables | `core_top:78-85` |

The virtual Phasor is off by default (V `config_menu.c:93`).

### 1.2 Region decode (V `core_top:1097-1144`)

All terms use the registered tuple `cycle_addr_q` (loaded in `X_CAPTURE`, `:1912`). **None looks at `cycle_rw_q`: reads and writes hit alike.**

| Term | Addresses | Lines |
|---|---|---|
| `sd_paddle` | `$C064-$C067`, `$C070` | `:1101-1103` |
| `sd_floating_io` | `$C019`, `$C030-$C05F` | `:1109-1112` |
| `sd_slot_io`, `sd_slot_num` | `$C090-$C0FF`, slot = `addr[6:4]`. For slot 4 that is `$C0C0-$C0CF`, the Phasor mode switch. | `:1114-1116` |
| `sd_iosel`, `sd_iosel_slot` | `$C100-$C7FF`, slot = `addr[10:8]`. For slot 4, `$C400-$C4FF`. INTCXROM and card presence are ignored. | `:1125-1128` (comment `:1118-1124`) |
| `sd_hit` | `(floating && en[7]) \|\| (paddle && en[8]) \|\| (slot_io && en[slot-1]) \|\| (iosel && en[slot-1])` | `:1141-1144` |

Disk II native accesses (`sd_disk2_native`, `:1134-1136`) force 1 MHz through `cycle_d2_native_q`, independently of the mask.

### 1.3 Counter, reload rule, effect (V)

```
// core_top:1884-1902, in the main always_ff
slow_update_valid_q <= core_en;                       // one per completed CPU cycle
if (core_en) begin
    slow_update_hit_q      <= !turbo_complete && sd_hit;
    slow_update_duration_q <= slow_duration;          // window sampled with the hit
end
if (slow_update_valid_q && slow_update_hit_q)       slow_cnt_q <= slow_update_duration_q;   // reload
else if (slow_update_valid_q && slow_cnt_q != 0)    slow_cnt_q <= slow_cnt_q - 1;           // count
if (!ab_read.res) begin slow_cnt_q <= 0; slow_update_valid_q <= 0; end
```

- **Reload, not extend.** Every hit loads the full window again (`:1893-1894`). A hit inside an open window restarts it.
- **Counting.** Every other completed CPU cycle takes one off (`:1896-1897`), whatever its address.
- **Reset.** `!rstn` clears all four registers (`:1710-1713`). Apple RES# clears the counter and the pending update (`:1899-1902`). Session start and end do not clear it (A: harmless, since RES# is asserted around both).
- **The update is staged one fabric clock after the completion** (`:1088-1094`, `:1884-1887`). `turbo_execute` is held low while a staged hit waits (`:1168-1171`), so the next cycle cannot start in TURBO before the counter is loaded.
- **Effect.** `slow_active = slow_cnt_q != 0` (`:1095`) forces `eff_mode` to `SPEED_1MHZ` (`:1153-1157`). That drives four things only:
  - `pace_ok`: a cycle completes only after an Apple data strobe since the last completion (`:1159-1162`, `:1849-1860`);
  - `turbo_execute`: the core's TURBO shortcuts (`:1170-1171`, `:366`) and the `X_TURBO_DONE` route (`:1952-1953`);
  - the status bit `video_phase_1mhz` (`:1751-1752`), read by CPU1 in `APPLE_RESET_STATUS` (`apple_top.sv:2806-2814`);
  - the `$C019` sampling phase (`:2003-2005`).
- `video_selected` (`:1352-1353`) and the TURBO invalidation (`:1206-1211`) use `speed_mode`, not `eff_mode`, so the window never changes the mirror policy or clears the caches (V).

**Consequence (A, derived from the lines above; the bench's phase 0 checks the one-edge staging, `tb_vtw_slowdown.sv:287-353`, run at `:418`).** After a hit completes, the next N completed CPU cycles run at 1 MHz, where N is the window. The hit's own cycle is a bus cycle, synced to PHI0 whatever the speed. An instruction whose opcode fetch ran slow keeps its dummy cycles (V `w65c02_core.sv:210-214`, `:1250`).

### 1.4 Every `$C4xx` access passes `X_ROUTE` (V)

- A capture with `core_addr[15:12] == 4'hC` never goes to `X_TURBO_DONE` (`:1947-1953`). `turbo_hit` also excludes `$Cxxx` (`:1237`). So `!turbo_complete` is always true for a slot-4 hit.
- The path is `X_CAPTURE`, optionally `X_VIDEO_WAIT` (`:1956-1961`), then `X_ROUTE` (`:1974`), then `X_BUS` (`:2023-2024`) and `X_BUS_DONE`. The completion (`core_en`, `:1523-1527`) is at least two edges after `X_ROUTE`.
- Section 3 relies on this.

## 2. What needs the window, and so what must keep opening it

### 2.1 How the card counts time (V)

- The VIA timers count on `via_timer_clock = ab_read.sss_en`, one tick per Apple cycle (`mockingboard.sv:86`, `via6522.v:103-107`). A fast CPU sees fewer counts between two of its own events. That is what the window repairs.
- In Phasor native mode a read of T1CL or T2CL adds one tick (`mockingboard.sv:87-97`, `via6522.v:103-107`).
- The register index is `addr[3:0]` for both VIAs in every mode (`mockingboard.sv:605`, `:635`). The VIA decode depends on the mode (`:73-81`): Mockingboard mode, VIA-A = `!addr[7]` and VIA-B = `addr[7]`; native mode, VIA-A = `addr[4]` and VIA-B = `addr[7]`; Echo+, VIA-B everywhere.
- The SSI-263 sees every slot-4 write with `addr[6]` (primary) or `addr[5]` (secondary) in Mockingboard and native modes, **in addition to** any VIA write at that address (`:100-103`). Native-mode SSI reads need `addr[4]` and `addr[7]` clear (`:104-108`).
- The mode switch is any access to `$C0C0-$C0CF` (`:66-69`, `:531-539`). It changes the VIA decode and the timer-read tick.
- The PSG bus is sampled on every fabric clock, not on the PSG clock enable (`YM2149.sv:80-100`; `mockingboard.sv:710-717`), and a PSG read is combinational (`YM2149.sv:103-107`). **The AY latch, write and read protocol therefore has no minimum spacing.** Back-to-back port writes at TURBO speed are correct (V).

### 2.2 Known detection methods and drivers

| Software | What it times | Accesses in the timed interval | Needs |
|---|---|---|---|
| A2Desktop `detect_mockingboard` / `detect_phasor` | Two T1 reads at `$Cs04`/`$Cs14`, eight cycles apart | Reads only | Reads open the window. V as the firmware's own comment (`core_top:1119-1124`); A2Desktop source not read (A). |
| Skyfox discovery probe, mb-audit T6522_C | Back-to-back T1C-L reads, expecting a delta of `$05` | Reads only | Reads. V `mockingboard.sv:87-96` (comment). |
| Skyfox, Quarx auto-detect | T1 counting after power-on | Reads | Reads. V `gssquared/src/devices/mockingboard/MB.md:317` (emulator notes). |
| mb-audit `DetectMegaAudioCard` | `STA T1CH`, then 2- and 3-cycle instructions with no I/O; which instruction the IRQ lands after | **A timer write**, then pure CPU cycles | **Timer writes must open the window.** V quoted in `gssquared/src/devices/mockingboard/MB.md:217-232`. |
| mb-audit T6522_3, T6522_F/10/11 | Timer and IFR read timing | Reads | Reads. V `via6522.v:319-323`, `:575-580` (comments). |
| Bilestoad (`demos/bilestoad/src/sound.s`) | Probe by AY read-back (`:87-115`), no timing. T1 read pair once a frame (`:117-120`, `:230-237`) | Writes, then an ORA read | Nothing timed after a write (V). |
| Bosconian (`demos/appletini_bosconian/sound_io.s`, `sound.c`) | Probe by AY read-back (`sound_io.s:44-95`). SSI-263 writes at `$C440-$C444` (`:146-156`, `bosco.inc:44-48`). Speech end by reading `$C440` D7 or the IFR (`sound.c:819-822`). | Writes, SSI-aliased writes, reads | SSI writes have `addr[6]` set and stay hits. Nothing timed after a port write (V). |
| Doom S2 driver (`src/sound/`) | Probe: mode switch, port writes, one ORA read (`sound.inc:8-21`). Bursts: ORB and ORA-NH writes only. | Writes | Nothing timed (V); FW-S1 is what it is for. |

**No known detection times an interval that starts with a port, DDR, IFR or IER write and contains no slot-4 read.** Each starts from a read, a timer write or the mode switch.

### 2.3 Which accesses must keep opening the window

| Access | Keeps opening? | Why |
|---|---|---|
| Any read, any register | Yes | Every detection times reads (2.2). A read also has side effects that some timing depends on: T1CL and T2CL clear their flags, ORA and ORB clear CA/CB flags (`via6522.v:200-241`, `:382-385`, `:452-453`). |
| Read-modify-write on any register | Yes | Its read cycle is a read. |
| Write to T1CL, T1CH, T1LL, T1LH, T2CL, T2CH (4-9) | Yes | Starts or reloads a timer (`via6522.v:340-392`); `DetectMegaAudioCard` times from it. |
| Write to SR (`$xA`) | Yes | Shift timing follows T2 or the clock (A). |
| Write to ACR (`$xB`), PCR (`$xC`) | Yes | ACR sets the timer modes and PB7 (`via6522.v:136`, `:166-171`, `:372-400`). PCR sets CA/CB edges and SSI behaviour (`:126`, `:252-285`; `mockingboard.sv:675`). |
| Any access to `$C0C0-$C0CF` | Yes | The mode switch changes the decode and the timer-read tick (2.1). |
| Write with `addr[6]` or `addr[5]` set | Yes | It reaches an SSI-263 in Mockingboard and native modes (`mockingboard.sv:100-103`). Speech drivers are not surveyed (A); the Doom player never writes there. |
| Write to ORB, ORA, DDRB, DDRA, IFR, IER, ORA-NH (0-3, D-F), bits 6-5 clear | **No (FW-S1)** | Port and interrupt state only; no timer is touched (`via6522.v:110-177`, `:200-241`). |

**The risk class.** A program that plays samples by writing AY registers from a cycle-counted delay loop, with no slot-4 read inside the loop, runs correctly today when each gap is shorter than the window, and would run at TURBO speed with FW-S1 (A: I found no such title in the local sources; they are known to exist on the Apple II). This is why the default is off (section 4).

## 3. The change

### 3.1 Exempt set

```
quiet write = CPU write cycle (!cycle_rw_q)
            && cycle_addr_q[15:8] == 8'hC4              // slot 4 I/O select
            && cycle_addr_q[6:5]  == 2'b00               // not an SSI-263 address
            && cycle_addr_q[3:0] in {0,1,2,3,D,E,F}     // ORB ORA DDRB DDRA IFR IER ORA-NH
            && slow_region_en[9]                          // FW-S1 armed
```

- The test is on the address only. The Phasor's mode lives in `mockingboard.sv` and is not visible to the core. It does not need to be: the register index is `addr[3:0]` in every mode (2.1). Where an address selects no VIA (native mode, `addr[4]` and `addr[7]` clear, for example `$C400-$C40F`), the write touches nothing and exempting it is harmless.
- `addr[7]` and `addr[4]` are free. `$C400`, `$C410`, `$C41F`, `$C480`, `$C48F` and `$C490` all qualify.
- The same decode as a2vm's model (V `tools/a2vm/cost.c:804-815`: `reg <= 3 || reg >= 13`, `!(a & 0x60)`), so the measured gain applies.
- The exempt write still passes `X_ROUTE` and `X_BUS` as a real bus cycle, still waits for the video barrier like any `$Cxxx` access (V `:1414-1415`, `:1947-1949`), and still counts as one cycle of an open window. It only does not reload the counter.

### 3.2 Where the decode is made

**Recommended: registered in `X_ROUTE`, like `cycle_d2_native_q`.**

`cycle_d2_native_q <= sd_disk2_native` in `X_ROUTE` (V `:1974-1975`) is the precedent: "Hold the native/private decision made in X_ROUTE through completion. This also keeps live ownership decode off the Disk II tick/CPU path" (V `:1137-1139`).

```
// core_top, beside :1139
localparam logic [2:0] SLOW_VIA_SLOT = 3'd4;   // = MB1_SLOT_ASSIGN, apple_top.sv:1396
logic cycle_via_quiet_q;                        // this routed cycle is an FW-S1 quiet write

wire sd_via_quiet_d =
    slow_region_en[9] && !cycle_rw_q &&
    (cycle_addr_q[15:8] == {5'b11000, SLOW_VIA_SLOT}) &&
    (cycle_addr_q[6:5] == 2'b00) &&
    ((cycle_addr_q[3:2] == 2'b00) ||            // 0-3: ORB ORA DDRB DDRA
     (cycle_addr_q[3:0] == 4'hD) ||             // IFR
     (cycle_addr_q[3:1] == 3'b111));            // E-F: IER, ORA no handshake

// :1141-1144, the I/O-select leg only
wire sd_hit = (sd_floating_io && slow_region_en[7]) ||
              (sd_paddle      && slow_region_en[8]) ||
              (sd_slot_io && slow_region_en[sd_slot_num  - 3'd1]) ||
              (sd_iosel   && slow_region_en[sd_iosel_slot - 3'd1] && !cycle_via_quiet_q);

// reset block, beside :1706
cycle_via_quiet_q <= 1'b0;

// X_ROUTE, beside :1975
cycle_via_quiet_q <= sd_via_quiet_d;
```

**Why the registered bit is always current (V, section 1.4).**

- Every slot-4 I/O-select access passes `X_ROUTE` at least two edges before its `core_en`. At that edge `cycle_via_quiet_q` describes this access.
- A cycle that completes through TURBO did not pass `X_ROUTE`, so the bit may be stale. But such a cycle is never `$Cxxx`, so `sd_iosel` is 0 and the stale bit is masked.
- Every other region leg is untouched, including `$C0C0-$C0CF`.

**Timing.**

- Nothing changes in `X_CAPTURE` or on its wide enable (the comment at `:1947-1948` asks to keep I/O decode off it). `core_addr` feeds nothing new. The capture path the baseline passed by 0.005 ns is not touched.
- The new flop's D input comes from flops (`cycle_addr_q`, `cycle_rw_q`, `vtw_slowdown_q[9]`) through about two LUT levels, qualified by the `X_ROUTE` state bit. That is the same class as `cycle_d2_native_q`.
- The D input of `slow_update_hit_q` gains one flop-driven AND input on the `sd_iosel` leg. The late inputs of that register are `turbo_complete` (its D side) and `core_en` (its enable), neither changed. The staging at `:1088-1094` was added to keep this cone small; the change respects it.
- `vtw_slowdown_q[9]` gains one load inside the core. The earlier class "PS AXI interface to vTW slowdown state" (+0.165 ns, route-dominated, 0 levels; V `docs/FABRIC_TIMING_MARGIN_PLAN.md:853`, an earlier build) ends at the register itself, not at this new load.
- `cycle_addr_q` gains about 14 loads. Its fanout is already large; the "vTW cycle address to RamWorks cache-data enable" class (+0.169 ns in the same earlier build, V `:854`) must be checked in the build report (A: low risk).

**Alternative (0 FF):** use `sd_via_quiet_d` directly in `sd_hit`. It is correct, since `cycle_addr_q` is stable from capture to completion (V `:1912-1914`), but it adds about two LUT levels to the D path of `slow_update_hit_q` instead of one input. Use it only if the flop is unwanted.

### 3.3 SSI-263 addresses (decision D2)

- Recommended: writes with `addr[6]` or `addr[5]` set stay hits in every mode. In Mockingboard mode such a write reaches both a VIA register and the speech chip (`mockingboard.sv:100-103`). In Echo+ mode it reaches no SSI (`:53`), and keeping the hit only costs time.
- This is what native-sound.md 4.4 and the a2vm model assume. It costs the Doom player nothing, because its addresses (`$C410`, `$C41F`, `$C480`, `$C48F`, V `src/sound/sound.inc:9-19`) have bits 6-5 clear.

### 3.4 The mode switch

`$C0C0-$C0CF` stays a hit for reads and writes (it is `sd_slot_io`, not `sd_iosel`, and is not edited). A program that switches modes and then times reads keeps working.

### 3.5 Host kinds and ONE//e

| Host | Behaviour | Evidence |
|---|---|---|
| Enhanced //e | As above | — |
| II/II+ | Identical. The region decode and the counter have no host term; `host_is_iiplus` is used only elsewhere (`core_top:787`, `:1932`). The PS apply path has no host test. | V `core_top:1097-1144`, `:1884-1902`; `config_menu.c:4669-4692` |
| ONE//e | Identical in the core; `virtual_motherboard` is not used by the slowdown. The Phasor is mapped on ONE//e through `onee_enable_effective`. | V `core_top:577-593`, `:1276-1278`, `:1336`, `:2140-2143` (every `virtual_motherboard` use); `apple_top.sv:709-710` |
| INTCXROM on | `sd_iosel` ignores it (today and after), so a `$C4xx` write that the internal ROM swallows is exempted the same way. Harmless. | V `core_top:1125-1127`; `soft_switch_manager.sv:304-309` |
| 1 MHz speed mode, `$C074` = 1 or 3 | No effect: `eff_mode` is already 1 MHz. | V `core_top:1153-1157` |

### 3.6 PS side

- `card_control_regs.h:336-343`: add `CARD_CTRL_VTW_SLOWDOWN_VIA_QUIET_BIT (1UL << 9)`. Keep `CARD_CTRL_VTW_SLOWDOWN_MASK_MASK` at `0x1FF`, so the retired menu bit 9 can never reach the PL.
- `vtw_service.c`: a new `g_slowdown_via_quiet` and `vtw_service_set_slowdown_via_quiet(uint8_t on)`, which rewrites `0x6B` with the stored mask, window and this bit. `vtw_service_set_slowdown` keeps its signature (the host test calls it, V `scripts/test_onee_vtw_runtime.py:849`) and ORs the stored bit in. Status line (`:1177-1182`): append `phasorquiet=0/1`.
- `config_menu.h:242`: `uint8_t vtw_phasor_quiet_writes;`. `config_menu.c`: default 0 (with `:75-76`); key `vtw.slowdown.phasor_quiet` (bool, beside `:3550`); save beside `:3797`/`:3812`; reset beside `:4241` and `:7397`.
- `config_menu_apply_vtw_slowdown` (`:4669-4692`): arm only when `mockingboard_slot4_enabled && vtw_phasor_quiet_writes`. With the Phasor off the bit is always 0, so no other slot-4 card is ever affected.
- Menu: one checkbox on the Phasor tab under "Enable in Slot 4" (`config_menu_phasor.c:529`), for example "Fast port writes". Help text: keep the sentence `test_config_profiles.py:651-653` requires, and add one line saying that port writes no longer slow the machine and that timed sample players may then play too fast.

## 4. Kill switch

**Yes, at run time, and it is the feature's only control.**

- `0x6B` bit 9 = 0 is F1.2.1 exactly: `cycle_via_quiet_q` stays 0 and `sd_hit` is unchanged.
- It is safe on mixed versions. An old PS on a new bitstream writes bit 9 as 0 (V `vtw_service.c:719`). A new PS on an old bitstream sets a bit that nothing reads. Both registers read back the full word (V `apple_top.sv:2947`), so the PS cannot detect support from the readback; it does not need to.
- It changes live. The bit is sampled at each `X_ROUTE`; a flip takes effect at the next slot-4 access, with no reboot and no cache invalidation.
- No compile-time switch is needed at this size. Optionally, a `localparam bit FWS1_ENABLE` that ANDs into `sd_via_quiet_d`, for an A/B build.
- **D5 (default):** off. On in the Doom profile. Revisit after the checks in section 6.2.

## 5. Cost

| Item | FF | LUT |
|---|---:|---:|
| `sd_via_quiet_d` decode (`addr[15:8]`, `[6:5]`, `[3:0]`, `rw`, enable) | 0 | 2-4 |
| `cycle_via_quiet_q` | 1 | 0-1 (the state-bit enable may merge) |
| `sd_hit` I/O-select leg, one more input | 0 | 0-1 |
| Register bit 9 | 0 (the flop exists and is read back) | 0 |
| **Total** | **1** | **about 3-6** |

0 BRAM. PS: a few hundred bytes of code and one config key. The baseline is 34,888 of 53,200 LUTs (from the design document).

## 6. Tests

Nothing here was run.

### 6.1 Benches and host tests

**`tb_vtw_slowdown.sv`.** The existing phases 0-10 stay as they are and run with bit 9 = 0. They are the F1.2.1 regression.
- Phase 4 is `STA $C400` with slot 4 armed and must still pace at about 1 MHz (`:479-491`). With FW-S1 armed it would not, and that is the point: do not change phase 4, add phases.
- The bench's 10-bit `sd_region_en` already reaches bit 9 (`:82`).

New phases (FW-S1 armed = bit 9 and bit 3 set, window 64, the existing `reboot_with`/`reboot_op_with` loops, `:232-259`):

| # | Program | Expect |
|---|---|---|
| 11 | `STA` to each of `$C400`, `$C401`, `$C402`, `$C403`, `$C40D`, `$C40E`, `$C40F`, and the same offsets at `$C410` and `$C480`, `$C48F` | Warp (`> 2*WINDOW`). `cnt_bus_cycles` rises by exactly one per loop, as with bit 9 = 0 (the bus cycle is not removed). |
| 12 | `STA` to offsets 4-C at `$C400` and `$C480` | About 1 MHz |
| 13 | `LDA` from all 16 offsets | About 1 MHz |
| 14 | `STA $C440`, `$C420`, `$C460`, `$C4C0`, `$C45F` (SSI aliases) | About 1 MHz |
| 15 | `STA $C0C5` and `LDA $C0C8` (mode switch) | About 1 MHz |
| 16 | `INC $C410` (read-modify-write) | About 1 MHz |
| 17 | `STA $C400,X` (never crosses a page, whatever X) | About 1 MHz: the same-page false read of the target is a read (V `w65c02_core.sv:1028-1038`, `:908-913`) |
| 18 | Bit 9 set, slot 4 off: `STA $C410`. Then bit 9 set, slot 5 on: `STA $C500`. | Warp (the gate is unchanged). Then about 1 MHz (the exemption is slot 4 only). |
| 19 | Exact count: `LDA $C404`, then a loop of `STA $C410` and NOPs | `slow_cnt_q` loads 64 once, then only falls, and reaches 0 exactly 64 completions after the read. `pipeline_accept_count` (`:273-285`, the watch at `:278`) does not rise for the writes. |
| 20 | Live kill switch: phase 11 program, clear bit 9 without reboot | About 1 MHz from the next access on |

Add a monitor: at every `core_en` whose tuple is in `$C400-$C4FF`, `cycle_via_quiet_q` equals the combinational decode of that tuple. It covers every phase, including the existing ones, where it must stay 0.

Verilator here could not compile this bench (it assigns to an input; memory of 2026-09-28). The owner's XSim flow runs it through `scripts/test_vtw.py:58`, `:93`.

**Other benches.** These instantiate `vtw_core_top` with bit 9 tied to 0 and must pass unchanged:
- `tb_vtw_system.sv` (9-bit `sd_region_en`, `:122`, `:232`, zero-extended);
- `tb_vtw_usb_joystick.sv` (`:82`, `:129`);
- `tb_vtw_turbo.sv` (`:217`);
- the ONE//e and video benches with `10'd0` (`tb_onee_joined_bus.sv:333`, `tb_onee_rom_cold_boot.sv:208`, `tb_onee_disk2_boot.sv:235`, `tb_onee_video_path.sv:192`, `tb_vtw_video.sv:120`, `tb_vtw_pc_event_pipeline.sv:38`, `tb_vtw_disk2_speed_matrix.sv:164`, `tb_vtw_disk2_woz_e2e.sv:197`).

No port changes, so no instantiation edits.

**Static and host tests.**
- `scripts/test_vtw.py:332-356`, `:422-429`: add requirements for `cycle_via_quiet_q`, the `X_ROUTE` assignment, `slow_region_en[9]`, and `SLOW_VIA_SLOT` equal to `MB1_SLOT_ASSIGN`. The existing strings stay true.
- `scripts/test_config_profiles.py`: key round trip. Bit set only with the Phasor on; with the Phasor off and the key on, bit 9 = 0. The migration test (`:655-662`) is unchanged.
- `scripts/test_onee_vtw_runtime.py:849-861`: unchanged call; add one for the new setter.

**a2vm (this repository).** `tests/test_sound_player65.py` already checks the model's FW-S1 exemptions. After the build, compare its `+fws1` cost table with hardware (6.2).

### 6.2 Hardware checks

Run each check three ways: FW-S1 off at window 512, off at 32, and on at 512. Everything must match the first run except speed.

| Software | Check |
|---|---|
| mb-audit (Mockingboard audit) | Every 6522 and SSI-263 test, including T6522_C and the IRQ timing tests. Record the F1.2.1 result first; some IRQ-latency tests may already differ at 512 (A). |
| A2Desktop | Its system information lists a Mockingboard in slot 4, and a Phasor after the native-mode switch (A: where it shows this). |
| Skyfox | Auto-detects the card and plays |
| Ultima IV, Ultima V, Nox Archaist demo | Music plays at the right tempo. This is the suite in `gssquared/Docs/Mockingboard.md:504-505`. |
| Bilestoad, Bosconian (speech included), Pinball Construction Set | Probe reports 4 chips in native mode; music and speech are correct |
| Doom S2 driver, counting loop | `snd_probe` finds the layout. The cost falls toward a2vm's `+fws1` column (for example D_E1M1 native12: 25.76 → 4.03 ms a second, `src/sound/README.md`). |
| A timed AY sample player, if the owner has one | Expect it to play fast with FW-S1 on, and correctly after `phasor_quiet=off`. This confirms the kill switch and documents the risk class. |

## 7. Software contract

A program may rely on the following. All of it applies only while the firmware has FW-S1 armed (the virtual Phasor on, and the profile key on). A program cannot read that setting and must be correct with it on or off: FW-S1 changes speed, never results.

1. **Exempt writes:** CPU writes to `$C400-$C4FF` with address bits 6 and 5 clear and register 0, 1, 2, 3, D, E or F. They do not start or extend the 1 MHz window. Inside a window opened by something else, each counts as one of its cycles.
2. **Use a plain store:** `STA`, `STX`, `STY` or `STZ` absolute, or `STA (zp)`, `(zp),Y` or `(zp,X)`. `STA abs,X` and `STA abs,Y` within a page first read the target (V `w65c02_core.sv:1028-1038`). That read opens the window and has the read's side effects on the VIA. RMW instructions read first too.
3. **Each write is still a real bus cycle**, about 1-2 µs (V `docs/research/native-sound.md` 2.3), and still waits for pending active SHR mirror bytes like any `$Cxxx` access (V `core_top:1414-1415`).
4. **The AY protocol needs no delay.** The six-store sequence (ORA-NH = register, ORB = latch, ORB = idle, ORA-NH = value, ORB = write, ORB = idle) is correct at any spacing (2.1).
5. **Everything else keeps today's rule.** Reads, timer, SR, ACR and PCR writes, SSI addresses and the mode switch open the window for `vtw.slowdown.cycles` CPU cycles (512 by default; 0 becomes 512 while the Phasor is on).
6. **To get 1 MHz timing after port writes** (for example a timed sample loop), read a register without side effects inside each window. `BIT $C48B` reads VIA-B's ACR in both modes and is not an SSI address (V `via6522.v:561-584`, `mockingboard.sv:77-81`, `:104-108`). Or write `$C074`.
7. **Slot 4 only.** A physical Mockingboard in another slot, under that slot's slowdown bit, keeps today's rule.

For Doom: once FW-S1 ships, the profile adds `vtw.slowdown.phasor_quiet=on`. The window can stay at 32; it only matters at `snd_probe`.

## 8. Interaction with the seven changes

The slowdown state feeds only `pace_ok`, `turbo_execute`, `video_phase_1mhz` and the `$C019` phase (1.3). FW-S1 only removes some reloads of `slow_cnt_q`: more cycles run in TURBO and fewer at 1 MHz. It creates no new state, and none of the seven changes keys on `eff_mode`.

| Change | Interaction |
|---|---|
| 0, counters | None required. The eight new slots are taken (design, Step 0). A "cycles completed while `slow_active`" counter would measure FW-S1 directly, if a slot frees up. |
| 1, `$C071/$C073` on the bank-steer list | None. The gap needs a classic speed; in TURBO the bank write is an exposure access, and the mirror policy follows `speed_mode` (V `core_top:1352-1353`), not the window. |
| 2, relaxed PSRAM admission | None. Keyed on bus ownership. |
| 3, lazy SHR mirror | Complementary. An exempt write is still a `$Cxxx` exposure access (V `:1390-1394`: `$C080-$CFFF`). Today it flushes deferred pages and waits for active bytes. Under change 3 lazy bytes neither stall it nor are flushed by it (design, "What does not flush them"). The Doom IRQ pays any drain at its `$C0AF` acknowledge first (native-sound.md 2.3). |
| 4, TURBO caches survive mapping changes | None. The invalidation uses `speed_mode` (V `:1206-1211`); fills happen in slow cycles too (V `:1212-1215`). |
| 5, zero-page bank pair | None. `$Cxxx` is never redirected, and the pair's apply edges hold in both TURBO and 1 MHz paths (zpbank-spec 2.4). A: the Doom IRQ zeroes the pair before its AY bursts anyway (zpbank-spec section 7). |
| 6, associative line cache | None |
| 7, quiet mapping switches | None in the decode: `quiet_en` uses `speed_mode`, not `eff_mode` (design, "Classification"). A `$C4xx` access is non-quiet, so it may trigger a pending reconciler replay, like any other `$Cxxx` access; in the Doom IRQ, `$C0AF` comes first. |

**`video_phase_1mhz`.** With FW-S1, the 1 MHz spans after Phasor bursts disappear, so CPU1's renderer sees fewer and shorter 1 MHz reports (V `apple_top.sv:2806-2814`). A: that gate is frame-level and tolerates it; it already sees 32-cycle spans with the Doom profile.

## 9. Optional FW-S2: 16, 32 and 64 in the window presets

- Change `k_vtw_slowdown_cycle_presets` (`config_menu.c:84-86`) to `{16, 32, 64, 256, 512, ..., 65535}`.
- **Also change the fallback index.** `config_menu_vtw_slowdown_cycle_index` returns 1 as "default 512" when the value is not a preset (`:4694-4704`). With three entries in front, index 1 is 32. It must return the index of `CONFIG_DEFAULT_VTW_SLOWDOWN_CYCLES`.
- `scripts/test_config_profiles.py:676-680` requires the exact preset list and must change with it. That is a deliberate specification change, not a weakening.
- Help text (`config_menu_help.c:566`): mention the new minimum.
- A window of 16 still covers the known detection loops, which read timers 5-8 cycles apart and reopen the window at each read (2.2). mb-audit tests with longer silent gaps may fail at 16 (A).
- With FW-S1 on, the window hardly matters to Doom: its bursts contain no hits. FW-S2 helps programs that read the card often and firmware without FW-S1. It costs no RTL.

## 10. Stages and decisions

| Stage | Content | Expected |
|---|---|---|
| 1 | RTL: section 3.2, comments at `core_top:78-85` and `apple_top.sv:539`, `:1915`; bench phases 11-20 and the monitor | With bit 9 = 0, all benches unchanged. One full build against +0.200 ns. |
| 2 | PS: section 3.6, status line, help, `README_VIRTUAL_TRANSWARP.md:342-356` (item 5 says slot 4 is "always slowed") | Host tests pass |
| 3 | Hardware checks, section 6.2. Then decide D5. | — |

**Decisions for the owner:**

- **D1:** the exempt set. Recommended: the seven registers of FW-S1. Narrower option: ORB, ORA and ORA-NH only, which is all the Doom bursts use; it costs the same and leaves IFR, IER and DDR writes as hits.
- **D2:** SSI-aliased writes stay hits. Recommended.
- **D3:** slot 4 only, fixed. Recommended.
- **D4:** control in `0x6B` bit 9, with no new port. Recommended. The alternative is bit 10 and a new port, which needs 13 bench edits.
- **D5:** default off; on in the Doom profile. Recommended.
- **D6:** the decode registered in `X_ROUTE` (1 FF). Recommended over the combinational form.

**Not verified:**

- A2Desktop's detection code, and which titles play samples through timed AY writes.
- Speech-driver timing on SSI writes.
- The CPU1 renderer's use of `video_phase_1mhz`.
- The timing of the new flop and of `cycle_addr_q`'s extra loads (needs a Vivado build).
- mb-audit's F1.2.1 baseline at window 512.
