# Review: FW-S1, Phasor port writes that do not open the slot-4 slowdown window

This reviews `fws1-spec.md` against the F1.2.1 snapshot of `<appletini-one>`. Paths are relative to the snapshot root; `core_top` is `hdl/apple/vtw_core_top.sv`. **V** means I read it at the cited line. **A** means an assumption or a claim about software whose source I did not read. **S** means I simulated it.

What I ran: the spec's RTL change (section 3.2, verbatim) applied to a scratch copy of `core_top`, and three scratch benches built with Verilator 5.050 by the recipe of the firmware-simulation note. They are not in either repository, and no firmware file was changed. The benches are:
- `tb_fws1`: the `tb_vtw_slowdown` harness with a variable speed mode;
- `tb_fws1_irq`: the same harness with the real `mockingboard.sv` on the bus, its `assert_irq` routed to both the IRQ pin and `irq_assert_in`, as `apple_top.sv:2163` does;
- `tb_phasor_burst`: `mockingboard.sv` alone, with the strobes applied directly.

The appendix gives the programs and the results. Nothing here was built for timing.

**Verdict: one blocker.** The spec's RTL is correct for what it decodes. In both speed modes, and with the TURBO path included, every access class behaves as the spec says (S). But the exempt set is wrong:
- Writes to IFR and IER, and ORA writes, can release the card's IRQ. Released by an exempt write in TURBO, the vTW core still sees the IRQ line low for up to one Apple cycle, and it takes the same interrupt a second time.
- A plain Mockingboard handler that acknowledges with `STA IFR` gets two interrupts per timer interrupt with FW-S1 on: 20 entries for 10 interrupts at both window 512 and window 32. With FW-S1 off it gets 10 (S).
- So FW-S1 as specified changes results, not only speed.

Narrowing the set to ORB and ORA without handshake (registers 0 and F) fixes it, 10 of 10 in every case (S). It costs Doom nothing, since its bursts write only those two registers. Four major and seven minor corrections follow.

## Findings

| # | Sev | Finding |
|---|---|---|
| 1 | Blocker | IFR, IER and ORA writes release the IRQ. Exempted, they cause a second, spurious interrupt on //e and II+ hosts |
| 2 | Major | The underlying stale-IRQ window exists without FW-S1, for any virtual card acknowledged at TURBO speed |
| 3 | Major | The slowdown bench runs only at speed mode 0; the TURBO path the spec's argument relies on is never exercised |
| 4 | Major | The monitor of section 6.1 fails by construction in phase 20 (the live kill switch) |
| 5 | Major | No test covers interrupts or the card itself: the test plan never instantiates the Phasor |
| 6 | Minor | The "no minimum spacing" argument (2.1) skips the native-mode chip-select flops; the conclusion holds |
| 7 | Minor | Section 2.2 overstates: a known detection does time an interval that starts with an IER write |
| 8 | Minor | The PS section skips the `config_menu` platform-callback layer |
| 9 | Minor | RTL hardening: gate bit 9 with the Phasor's own enable; clear the flop like `cycle_d2_native_q` |
| 10 | Minor | Host table and profile scope are incomplete |
| 11 | Minor | Contract details: STZ abs,X, the RMW write, and `$C074` |
| 12 | Minor | Verilator can run the slowdown bench after a two-line change; two existing phases then fail only because the simulator initialises their counter variable once |

**1. Blocker: exempt writes that release the IRQ.**
- Evidence:
  - Which writes release the IRQ:
    - A VIA's IRQ is `|(ifr & ier)`, registered (V `via6522.v:539-550`).
    - An IFR write clears the flags whose bits are set (V `:200-203`, `:238-241`, `:382-385`, `:452-454`, `:492-493`).
    - An IER write with bit 7 clear disables sources (V `:113-117`).
    - Any access to ORA (register 1), a write included, clears CA1 and CA2 (V `:200-203`). CA1 is the SSI-263's A/R flag in Mockingboard mode (V `ssi263_bus_wrapper.sv:206-208`).
    - ORB writes clear CB1 and CB2 (V `via6522.v:238-241`), but nothing sets them on this card: `cb1_in` and `cb2_in` are tied to 0 (V `mockingboard.sv:600-601`), and the only external CB1 source is the Votrax (V `ssi263_bus_wrapper.sv:219-221`), whose strobe is tied off (V `mockingboard.sv:673`, `:699`).
    - DDRA, DDRB and ORA without handshake touch no interrupt state (V `via6522.v:146-178`).
  - How the core sees the release:
    - On a //e or II+, the card's `assert_irq` drives the real IRQ pin (V `apple_bus_wrapper.sv:498-502`) and reaches the core directly (V `core_top:356-359`: `core_irq_n = ab_read.irq & ~irq_assert_in`).
    - `ab_read.irq` is the pin sampled once per Apple cycle, at the data snap (V `apple_bus_wrapper.sv:657-676`).
    - The acknowledging write takes effect at that same data strobe (V `mockingboard.sv:98-99`), so the previous low sample stands until the next cycle's snap, about 1 µs later.
    - At 1 MHz, RTI takes 6 µs and never sees the stale low. In TURBO it completes well inside that microsecond and the core takes the interrupt again.
  - Today the slot-4 window hides this: the acknowledging write is a hit, so the handler's tail and RTI run at 1 MHz. FW-S1 removes the hit.
  - Simulated (S, `tb_fws1_irq`, TURBO). T1 runs free every 2,000 cycles and the main loop is pure CPU. The handler is `PHA / LDA #$40 / <ack> / PLA / RTI` at `$F100`. "Entries" counts fetches of `$F100` in 20 ms:

| Handler | Window | Spec's set | F1.2.1 (bit 9 = 0) | Set {0, F} |
|---|---:|---:|---:|---:|
| `STA $C41D` (IFR) | 512 | **20** / 10 | 10 / 10 | 10 / 10 |
| `STA $C41D` (IFR) | 32 | **20** / 10 | 10 / 10 | 10 / 10 |
| `LDA $C41D`, 40 NOPs, `STA $C41D` | 32 (the Doom profile) | **20** / 10 | 10 / 10 | 10 / 10 |
| `LDA $C41D`, 40 NOPs, `STA $C41D` | 512 | 10 / 10 | – | 10 / 10 |
| `STA $C41E` (IER, disable T1) | 32 | **2** entries | – | 1 |
| `LDA $C414` (T1CL read) | 32 | 10 / 10 | – | 10 / 10 |

- Consequences:
  - Mockingboard handlers commonly acknowledge by writing IFR. Such a handler that counts ticks without checking IFR runs its music at double tempo and double-counts its clock.
  - One that checks IFR pays a second pass through the handler.
  - Speech drivers that acknowledge the SSI with an ORA write are exposed the same way (by reading; not simulated).
  - This is the "IFR/IER semantics" risk. The spec's statement that these writes touch "port and interrupt state only" (2.3), and its promise that "FW-S1 changes speed, never results" (section 7), are both wrong for this set.
- Doom is not affected either way: it disables both VIAs' interrupts at `snd_init` and never acknowledges the Phasor (V `src/sound/player.s:851-853`). But the Doom profile leaves FW-S1 on for everything run under it (finding 10).
- Correction:
  - **D1 becomes {ORB, ORA without handshake}: register 0 or F, address bits 6-5 clear.**
  - Decode `(cycle_addr_q[3:0] == 4'h0) || (cycle_addr_q[3:0] == 4'hF)`, at the same cost.
  - Doom's gain is unchanged, because every burst store is to `$C410`, `$C41F`, `$C480` or `$C48F` (V `src/sound/player.s:809-836`). Only `snd_init`'s one-time IER and DDR writes become hits again.
  - DDRA and DDRB (2, 3) are equally safe by the RTL, but nothing gains from them; leave them out.
  - The narrower set also shrinks the timed-sample-player risk class. Conventional drivers write AY data through ORA with handshake (`$Cn01`, e.g. `dos33fsprogs/music/pt3_lib` `MOCK_6522_ORA1 = $C401`), which stays a hit.
  - a2vm's model (`tools/a2vm/cost.c:808-812`) and `tests/test_sound_player65.py:947-959` must follow. That is a specification change, not a weakening.

**2. Major: the stale-IRQ window exists without FW-S1.**
- Evidence:
  - With no slowdown at all (mask 0), the `STA IFR` handler also gets 20 entries for 10 interrupts (S). Any virtual card acknowledged while the core runs in TURBO is subject to it.
  - The Doom VBL handler acknowledges the mouse card in slot 2, which is not slowed. It reads `$C0A0` first and counts only VBL causes (V `src/sound/irq.s:32-37`), and its `snd_tick` runs long after the acknowledge, so a spurious entry, if any, costs time but not correctness (A: not simulated for the mouse card).
  - ONE//e does not have the window: the virtual bus presents a live, combinational IRQ level (V `apple_virtual_bus.sv:84`, `:129`; `apple_top.sv:347`).
- Correction:
  - Outside FW-S1's scope. Record it as a question for the firmware author (Q2 below).
  - A core-side mask would remove it, and would then allow IFR and IER back into the FW-S1 set: ignore the sampled physical level for the rest of the Apple cycle in which `irq_assert_in` fell.
  - Until then, FW-S1 must not exempt any write that can release an IRQ.

**3. Major: the bench never runs TURBO.**
- Evidence:
  - `tb_vtw_slowdown` ties `.speed_mode(2'd0)`, which is FULL (V `hdl/sim/tb_vtw_slowdown.sv:117`; `core_top:70`).
  - Section 3.2's argument that the registered bit is always current rests on the TURBO path: `X_TURBO_DONE` completions with a stale bit (V `core_top:1947-1953`, `:1237`). Phases 11-20 as written would not exercise it.
- Result:
  - Run at speed modes 0 and 3, every phase-11-to-20 case behaves as the spec expects (S, `tb_fws1`).
  - Exempt stores run fast (FULL 3,069 and TURBO 1,881 core cycles per 200 Apple cycles, against 198 with bit 9 = 0), with exactly one bus cycle per loop.
  - Timer, SR, ACR and PCR writes, reads, SSI aliases, the mode switch, RMW, and `STA abs,X`/`abs,Y` pace at 1 MHz.
  - Slot 5 is unaffected. With slot 4 off the gate is unchanged.
  - The exact count holds: after `LDA $C404`, `slow_cnt_q` loads 64 once and reaches 0 after exactly 64 completions in both modes.
  - The existing benches pass unchanged on the patched RTL: `tb_vtw_turbo`, `tb_vtw_usb_joystick`, `tb_vtw_video`. `tb_vtw_slowdown` gives the same result as on the baseline RTL (finding 12). All S.
- Correction: make `speed_mode` a bench variable and run phases 11-20 at speed modes 0 and 3.

**4. Major: the monitor fails in phase 20.**
- Evidence:
  - Section 6.1 asks that `cycle_via_quiet_q` equal "the combinational decode of that tuple" at every `core_en` in `$C4xx`.
  - The flop is loaded at `X_ROUTE`, with the value bit 9 had then. When bit 9 is cleared live, the access in flight completes with the old decision.
  - My monitor, written as specified, reported one mismatch per live flip (S). The behaviour itself is right; section 4 says "a flip takes effect at the next slot-4 access".
- Correction: compare against `slow_region_en[9]` as sampled at that access's `X_ROUTE`, with a bench-side flop loaded when `xstate_q == X_ROUTE`. With that change the monitor passes over every phase (S).

**5. Major: no interrupt or card-level test.**
- Evidence: every bench in 6.1 uses the `$EE` motherboard model (V `tb_vtw_slowdown.sv:175-183`). None places the Phasor on the bus, so neither finding 1 nor the AY protocol at TURBO spacing can show up.
- Correction: add a bench that instantiates `mockingboard` beside `vtw_core_top`, with a two-client arbiter and `irq_assert_in` wired as `apple_top.sv:2163` does. Use it for:
  - the finding-1 table, as a regression that must stay at one entry per interrupt with bit 9 on;
  - a TURBO AY burst whose register values are checked in all four `YM2149` instances.

  In hardware checks, add a handler that acknowledges by `STA IFR` and counts its interrupts (6.2).

**6. Minor: AY spacing.**
- Evidence:
  - Section 2.1 rests "no minimum spacing" on `YM2149.sv:80-100`. In native mode the chip-select state lives in four flops clocked by `psg_clock = via_bus_clock || psg_ce_extra_q` (V `mockingboard.sv:262`, `:548`, `:552-587`).
  - It still works: an ORB write updates `portb_out` at its data strobe, and `psg_ce_extra_q`, one clock later, samples the new value in the same Apple cycle.
  - FW-S1 creates a spacing no 1 MHz program can produce: writes 1 to 2 Apple cycles apart. With the virtual Phasor on, slot 4 has always been slowed, so the card has never seen them.
  - Simulated with the strobe order of `apple_bus_wrapper.sv:100-120` (S, `tb_phasor_burst`): all 14 registers of all four chips, in native mode, with 0 and with 1 idle Apple cycles between stores (56 writes each), then the probe's read-back of chip 0. All correct.
  - In the vTW bench, a Doom-shaped burst in TURBO ran 1.68 Apple cycles per store with FW-S1, and 6.90 with FW-S1 off at window 32 (S).
- Correction: cite the flops and keep contract item 4, with "at one store per Apple cycle, the fastest the bus allows".

**7. Minor: a detection that starts from an IER write.**
- Evidence: `dos33fsprogs/demos/wargames/ssi263_detect.s:53-71` writes IER, then spins up to 65,536 iterations waiting for the SSI-263 interrupt.
- It is unaffected: its store is `STA $C000,X`, whose same-page false read of the target is a hit (V `w65c02_core.sv:1028-1038`), and the loop is far longer than any window.
- Correction: restate as "no known detection *depends on* an interval that starts with a port write". With finding 1's set, IER is a hit anyway.

**8. Minor: PS layering.**
- Evidence: `config_menu_apply_vtw_slowdown` reaches the PL only through `menu->platform.set_vtw_slowdown(ctx, mask, cycles)` (V `config_menu.c:4685-4688`; `config_menu.h:146`; `main.c:1845-1850`, `:3612`). `config_menu.c` does not call `vtw_service` directly.
- Correction: add a platform callback `set_vtw_phasor_quiet(ctx, on)` wired in `main.c`, or extend `set_vtw_slowdown` with a flags argument, and update the host-test stubs that fill the platform table.

**9. Minor: RTL hardening.**
- The spec keeps FW-S1 off the physical bus only through the PS rule "arm only when the virtual Phasor is on". The RTL can enforce it at no port cost: wire `.slow_region_en({vtw_slowdown_q[9] & card_slot4_bus_enable, vtw_slowdown_q[8:0]})` (V `apple_top.sv:709-710`, `:2171`). A physical card in slot 4 then never sees FW-S1, whatever the PS does. No bench edits are needed.
- The precedent `cycle_d2_native_q` is cleared in `X_CAPTURE` and on `!core_res_n` (V `core_top:1906`, `:2224`). Do the same for `cycle_via_quiet_q`. The bit is then 1 only while a quiet write is in flight, which simplifies the monitor and removes the stale-bit argument.

**10. Minor: hosts and scope.**
- IIgs: vTW is blocked (V `README_IIGS_SAFETY.md:69-71`), so FW-S1 is moot there.
- ONE//e differs in finding 2: its IRQ level is live, so it never double-interrupts (V `apple_virtual_bus.sv:84`, `:129`).
- II+ samples like the //e (V `apple_bus_wrapper.sv:657-676`).
- A loaded profile becomes the active configuration (V `config_menu.c:4377-4408`). FW-S1 set by the Doom profile stays on for any software run afterwards, until another profile is loaded. Say so in the menu help.

**11. Minor: contract details.**
- `STZ abs,X` is a plain store: its dummy read is the last instruction byte, not the target (V `w65c02_core.sv:1033-1038`, only `OP_STA` false-reads the target; S: runs fast). So are `STA (zp),Y`, `STA (zp)`, `STA (zp,X)`, and `STA abs,X` across a page (S).
- In a read-modify-write, the write cycle of an exempt register is exempt. The window restarts at the modify read, one cycle before the write (S: `INC $C410` gives 2 hits and 1 quiet completion). This is harmless; state it.
- Contract item 6 "or write `$C074`":
  - 1 forces stock speed until another value is written;
  - 3 latches until Apple reset;
  - both are ignored when `vtw.c074.ignore` is on (V `core_top:1863-1869`).

  Prefer the `BIT $C48B` form, which is correct as stated (V `via6522.v:560-584`; `mockingboard.sv:77-81`, `:104-108`).

**12. Minor: running the slowdown bench here.**
- `tb_vtw_slowdown` compiles under Verilator once `force dut.ab_read.res` and `release dut.ab_read.res` (V `:344`, `:351`) name the bench's own `ab_read`.
- It then fails phases 2 and 3 on both the baseline and the patched RTL. `int a = int'(cnt_core_cycles);` sits in a static `initial` block (V `:433`, `:450`, `:470`), and Verilator initialises it once, so those measurements are cumulative since reboot.
  - The numbers show it: 3,359 − 3,079 = 280 = 80 + 200 Apple cycles at 1 MHz.
  - A direct count shows phase 2 does pace at 1 MHz: 199 completions in 26,000 clocks (S).
  - Whether XSim re-evaluates the initialiser is not known here (A).
- Correction: the new phases assign their counters explicitly. The same one-line change to the existing phases would change what they measure under Verilator only; leave that to the owner.

## (1) Confirmed

| Claim | Evidence |
|---|---|
| Region decode uses the registered tuple, reads and writes alike | V `core_top:1097-1144` |
| Counter reload, count, staging, RES# clear | V `core_top:1884-1902`; S exact count 64 |
| `$Cxxx` never completes through `X_TURBO_DONE`; every `$C4xx` access passes `X_ROUTE` | V `core_top:1947-1953`, `:1237` |
| `sd_hit` feeds only `slow_update_hit_q` | V `core_top:1890` (only use) |
| The 3.2 RTL decodes exactly the intended set in FULL and TURBO | S `tb_fws1`, both modes, monitor corrected |
| An exempt write is still one real bus cycle | S: bus cycles equal loop count (99 per 200 Apple cycles) |
| Same-page `STA abs,X` and `STA abs,Y` false-read the target; the page-crossing form reads the last instruction byte | V `w65c02_core.sv:1028-1038`; S |
| RMW reads twice, then writes | V `w65c02_core.sv:1049-1069`; S |
| The mode switch is any access to `$C0C0-$C0CF`, and stays a hit | V `mockingboard.sv:66-69`, `:531-539`; S |
| SSI writes need `addr[6]` or `addr[5]`, in Mockingboard and native modes | V `mockingboard.sv:100-103` |
| Register index is `addr[3:0]` for both VIAs in every mode | V `mockingboard.sv:605`, `:635` |
| T2 pulse counting cannot see ORB: `portb_in` is tied to `$FF` | V `mockingboard.sv:595`, `:625`; `via6522.v:403-408`, `:425` |
| Bit 9 is unread by F1.2.1 (slot indices reach 6 at most) | V `core_top:1143-1144` |
| PS strips bit 9 before the PL | V `config_menu.c:2491-2501`, `vtw_service.c:719`, `card_control_regs.h:338` |
| Phasor fixed in slot 4 | V `apple_top.sv:1396`, `:1402` |
| The other benches with bit 9 at 0 pass unchanged | S `tb_vtw_turbo`, `tb_vtw_usb_joystick`, `tb_vtw_video` |
| FW-S2's fallback-index trap | V `config_menu.c:4694-4704` |
| Doom's bursts write only ORB and ORA without handshake | V `src/sound/player.s:809-836`, `sound.inc:9-19` |

## (2) Corrected specification

**Summary.**

| Item | Decision |
|---|---|
| What changes | A CPU write to `$C400-$C4FF` with address bits 6-5 clear and register 0 (ORB) or F (ORA without handshake) no longer reloads the slowdown counter. |
| What does not change | Every read and every read cycle of an RMW. Writes to DDRB, DDRA, T1, T2, SR, ACR, PCR, IFR, IER and ORA with handshake. SSI-aliased writes. The mode switch `$C0C0-$C0CF`. Other slots and regions. The bus cycle itself. |
| Why only 0 and F | Writes to IFR, IER and ORA can release the card's IRQ. Released in TURBO, the core takes the interrupt twice on //e and II+ hosts (finding 1). ORB and ORA-NH cannot: CB1 and CB2 are never set on this card. |
| Where | `core_top`: one flop, loaded in `X_ROUTE`, cleared in `X_CAPTURE` and on `!core_res_n`; one AND term in the I/O-select leg of `sd_hit`. `apple_top`: bit 9 ANDed with `card_slot4_bus_enable` at the port. |
| Control | Register `0x6B` bit 9. 0 is F1.2.1 exactly. |
| Default | Off. On only through the profile key; the Doom profile sets it. |
| Cost | About 3-6 LUTs and 1 FF; 0 BRAM. |

**RTL.**

```
// core_top, beside :1139
localparam logic [2:0] SLOW_VIA_SLOT = 3'd4;          // = MB1_SLOT_ASSIGN
logic cycle_via_quiet_q;
wire sd_via_quiet_d =
    slow_region_en[9] && !cycle_rw_q &&
    (cycle_addr_q[15:8] == {5'b11000, SLOW_VIA_SLOT}) &&
    (cycle_addr_q[6:5] == 2'b00) &&
    ((cycle_addr_q[3:0] == 4'h0) ||                    // ORB
     (cycle_addr_q[3:0] == 4'hF));                     // ORA, no handshake

// :1141-1144
wire sd_hit = ... ||
    (sd_iosel && slow_region_en[sd_iosel_slot - 3'd1] && !cycle_via_quiet_q);

// !rstn block, X_CAPTURE (beside :1906) and !core_res_n (beside :2224)
cycle_via_quiet_q <= 1'b0;
// X_ROUTE (beside :1975)
cycle_via_quiet_q <= sd_via_quiet_d;

// apple_top.sv:2171
.slow_region_en({vtw_slowdown_q[9] & card_slot4_bus_enable, vtw_slowdown_q[8:0]}),
```

- Nothing changes on `X_CAPTURE`'s wide enable except the constant clear. `core_addr` gains no load.
- `slow_update_hit_q` gains one flop-driven AND input. `cycle_addr_q` gains about 12 loads; check the "cycle address to RamWorks cache-data enable" class in the build report.

**PS.**
- `card_control_regs.h`: add `CARD_CTRL_VTW_SLOWDOWN_VIA_QUIET_BIT (1UL << 9)`, and keep `MASK_MASK` at `0x1FF`.
- `vtw_service.c`: add `g_slowdown_via_quiet` and a setter. `vtw_service_set_slowdown` keeps its signature and ORs the stored bit in. The status line appends `phasorquiet=0/1`.
- `config_menu`:
  - a new field and the key `vtw.slowdown.phasor_quiet` (bool, default 0), saved and reset beside the other slowdown keys;
  - a new platform callback, wired in `main.c:3612`;
  - `config_menu_apply_vtw_slowdown` arms the bit only when `mockingboard_slot4_enabled && vtw_phasor_quiet_writes`.
- Menu: a checkbox on the Phasor tab. Its help says that port writes no longer slow the machine, that timed sample players writing ORA-NH may run fast, and that the setting stays on while the profile is active.

**Kill switch.** Bit 9 is the feature's only control, and it takes effect live at the next slot-4 access. Mixed versions are safe in both directions: an old PS writes 0, and an old bitstream ignores bit 9. The PS cannot detect support from the readback. Optionally, add a capability bit so the status line does not claim `phasorquiet=1` on an old bitstream.

**Tests.**
- `tb_vtw_slowdown`:
  - `speed_mode` becomes a variable. Phases 0-10 stay at mode 0 with bit 9 = 0.
  - New phases run at modes 0 and 3, and use counters assigned explicitly, not declaration initialisers:

| # | Program | Expect |
|---|---|---|
| 11 | `STA` to `$C400`, `$C40F`, `$C410`, `$C41F`, `$C480`, `$C48F`, `$C490`, `$C49F`; also `STZ` abs and abs,X, `STA (zp),Y`, `(zp)`, `(zp,X)`, and `STA $C3F0,X` with X=$20 | Fast; one bus cycle per loop |
| 12 | `STA` to offsets 1-E at `$C400` and `$C480` | About 1 MHz |
| 13 | `LDA` from all 16 offsets | About 1 MHz |
| 14 | `STA $C440`, `$C420`, `$C460`, `$C4C0`, `$C45F`, `$C470`, `$C42F` | About 1 MHz |
| 15 | `STA $C0C5`, `LDA $C0C8` | About 1 MHz |
| 16 | `INC $C410`, `TSB $C410` | About 1 MHz; 2 hits and 1 quiet completion per instruction |
| 17 | `STA $C410,X` and `STA $C410,Y` in the same page | About 1 MHz |
| 18 | Bit 9 on, slot 4 off, `STA $C410`; bit 9 on, slot 5 on, `STA $C500` | Fast; then about 1 MHz |
| 19 | `LDA $C404`, then `STA $C410` and NOPs | Counter loads the window once and reaches 0 after exactly that many completions |
| 20 | Phase 11's program, then clear bit 9 live, then set it live | 1 MHz, then fast |

- Monitor: at every `core_en` in `$C4xx`, `cycle_via_quiet_q` equals the decode of the tuple, with bit 9 as sampled at that access's `X_ROUTE`. With the `X_CAPTURE` clear, it is also 0 at every completion outside `$C4xx`.
- New bench `tb_vtw_phasor_quiet`: `vtw_core_top` plus `mockingboard`, a two-client arbiter, and `irq_assert_in` from the card.
  - T1 free-running, handlers acknowledging by `STA IFR`, `STA IER` and `LDA T1CL`, at windows 32 and 512, with bit 9 on and off. Expect exactly one handler entry per T1 interrupt in every case.
  - A TURBO AY burst of all 14 registers into all four chips, checked in the `YM2149` instances.
- Static and host tests: `scripts/test_vtw.py` requirements for the flop, its `X_ROUTE` load, its clears, `SLOW_VIA_SLOT == MB1_SLOT_ASSIGN` and the `apple_top` AND; `test_config_profiles.py` key round trip; `test_onee_vtw_runtime.py` for the new setter.
- a2vm: `slowdown_hit` exempts only registers 0 and F; update `tests/test_sound_player65.py:947-959` to match. Doom's `+fws1` column should not move.
- Hardware, each run three ways (FW-S1 off at 512, off at 32, on at 512): the spec's 6.2 list, plus a Mockingboard program whose handler acknowledges by `STA IFR` and counts ticks. Its tempo must not change.

**Software contract.**
1. With FW-S1 armed, CPU stores to `$C400`, `$C40F`, `$C410`, `$C41F`, `$C480`, `$C48F`, `$C490` and `$C49F` (register 0 or F, address bits 6-5 clear) do not start or extend the 1 MHz window. Inside an open window each counts as one cycle.
2. Use a plain store: `STA`/`STX`/`STY`/`STZ` absolute, `STZ abs,X`, `STA (zp),Y`, `(zp)`, `(zp,X)`. Same-page `STA abs,X`/`abs,Y` and RMW instructions read the target first, which is a hit.
3. Each store is still a real bus cycle, and still waits for pending SHR mirror bytes.
4. The AY protocol is correct at one store per Apple cycle, the fastest the bus allows.
5. Everything else keeps today's rule: reads; writes to DDR, timer, SR, ACR, PCR, IFR, IER and ORA with handshake; SSI addresses; the mode switch.
6. For 1 MHz timing after port stores, read a register without side effects inside each window, for example `BIT $C48B`.
7. Slot 4 and the virtual Phasor only. A program must be correct with FW-S1 on or off; with this set, FW-S1 changes only speed.

**Decisions.**
- D1: {0, F}. This changes the spec.
- D2: SSI-aliased writes stay hits. Kept.
- D3: slot 4 only, now also enforced in the RTL. Kept.
- D4: bit 9 of `0x6B`. Kept.
- D5: default off, on in the Doom profile. Kept.
- D6: the registered decode, cleared like `cycle_d2_native_q`. Kept.

## (3) Questions for the firmware author

1. **Finding 1:** do you accept the narrower set {ORB, ORA-NH}? Or would you rather fix the stale IRQ sample (question 2), and then exempt IFR and IER too?
2. **Stale IRQ in TURBO:** on a //e or II+, `core_irq_n` keeps the physical sample for up to one Apple cycle after a virtual card releases `assert_irq`, and a fast RTI re-enters the handler (S: 20 entries per 10 interrupts with no slowdown). Is this known? Should the core ignore the sampled physical level for the rest of the Apple cycle in which `irq_assert_in` fell? This affects the mouse, the SSC and every other virtual card acknowledged at TURBO speed, not only FW-S1.
3. **XSim:** does XSim re-evaluate `int a = int'(cnt_core_cycles);` on each block entry (`tb_vtw_slowdown.sv:433`, `:450`, `:470`)? Under Verilator it is evaluated once, and phases 2 and 3 fail.
4. **Capability:** is there a free bit to advertise FW-S1 support, so that the PS reports the effective state rather than the requested one?

## Appendix: the simulations

Build: the snapshot's `hdl/` copied to the scratchpad, `vtw_core_top.sv` replaced by the patched copy, and the `SOURCES` list of `scripts/test_vtw.py` without its benches. `tb_fws1_irq` adds `via6522.v`, `YM2149.sv`, `ssi263_xck_ce.sv`, `sc01a_digital_core.sv`, `ssi263_voice.sv` and `mockingboard.sv`. A variant `vtw_core_top.sv` with the {0, F} decode provides the last column of finding 1. Each bench builds in about 7 s and runs in 0.2-9 s under `nice -n 10`.

`tb_fws1` (the program at `$F000`: one access, 12 NOPs, `JMP $F000`; window 64; 200 Apple cycles measured after 80 cycles of settling):

| Access, bit 9 on | Mode 0 core cycles | Mode 3 core cycles | Hits / quiet completions |
|---|---:|---:|---|
| `STA $C410`, bit 9 off | 198 | 198 | 7 / 0 |
| `STA` to `$C400`, `$C403`, `$C40D`, `$C410`, `$C48E`, `$C48F`; `STZ $C490` | 3,069 | 1,881 | 0 / 99 |
| `STA $C404`, `$C405`, `$C40A`, `$C40B`, `$C48C` | 198 | 198 | 7 / 0 |
| `LDA $C410`, `LDA $C40D` | 198 | 198 | 7 / 0 |
| `STA $C440`, `$C420`, `$C4C0` | 198 | 198 | 7 / 0 |
| `STA $C0C5`, `LDA $C0C8` | 198 | 198 | 7 / 0 |
| `INC $C410`, `TSB $C410` | 198 | 198 | 12 / 6 |
| `STA $C410,X`, `STA $C410,Y` | 198 | 198 | 7 / 7 |
| `STZ $C410,X` | 3,168 | 1,881 | 0 / 99 |
| `STA ($00),Y`, `($00)`, `($00,X)`; `STA $C3F0,X` crossing | 3,168-3,366 | 1,980-2,079 | 0 / 99 |
| `STA $C410`, slot 4 off | 3,069 | 1,881 | 0 / 99 |
| `STA $C500`, `$C510`, slot 5 on | 198 | 198 | 7 / 0 |

These rows use the spec's set, so offsets 1, 2, 3, D and E are quiet here. Rerun on the {0, F} variant, only the `$C403`, `$C40D` and `$C48E` rows change: they pace at 1 MHz as hits. Every other check passes (S).

`tb_phasor_burst`: 2 × 56 AY writes and 2 read-backs, all correct.

`tb_fws1_irq`: the table in finding 1.
