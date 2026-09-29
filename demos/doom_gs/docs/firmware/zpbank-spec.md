# Zero-page bank pair ($C069 enable), specification

This replaces the private read-bank register at `$C069`. Line numbers refer to the F1.2.1 snapshot of `<appletini-one>`. The review in `zpbank-review.md` corrects this text; where they differ, the review and the design document win. **V** means I read it at the cited line. **A** means an assumption. LUT and FF figures are my estimates. Nothing was built or simulated, and no file was changed.

## 0. Summary and the owner's question

**Your example works.** `ldx #$08 / stx zp_rd` reads from `$C073` bank 8, which is physical bank 9. Two corrections:

- **Enable the pair once first.** For example: `lda #$06 / sta $C069 / stz $06 / stz $07`.
- **Don't zero `zp_rd` after every access.** Code fetches, zero page, the stack, `$C000-$FFFF` and indirect-jump pointers are never redirected, so the code keeps running from main. Zero `zp_rd` only before you need main data in `$0200-$BFFF` or call firmware. `stz zp_rd` replaces `ldx #0 / stx zp_rd`.

```
        lda #$06          ; once: the pair is $06 (read) / $07 (write)
        sta $C069         ; both registers start at 0 (follow the soft switches)
        stz $06
        stz $07
        ...
        lda #$08          ; texture bank ($C073 numbering)
        sta $06           ; from here on, data reads of $0200-$BFFF come from bank 8
col:    lda (tex),y       ; bank 8
        sta (dst),y       ; zp_wr = 0: normal RAMWRT path (e.g. aux SHR, posted)
        ...               ; loop freely; code keeps running from main
        stz $06           ; only before reading main $0200-$BFFF data or calling ROM/ProDOS
```

| Item | Decision |
|---|---|
| Enable | Write to `$C069`: the value is `zp_rd`, and `zp_wr = (zp_rd+1) & $FF`. Writing 0 disables. Both registers clear on every `$C069` write. The write still goes out as a real bus cycle (no private serve). Reads of `$C069` keep today's meaning. |
| Values | 0 means follow RAMRD, RAMWRT, 80STORE, PAGE2 and `$C073` as today. 1-127 means physical bank value+1. `$80-$FF` are reserved and treated as 0. |
| Scope | Data accesses to `$0200-$BFFF` only. Never code-space cycles, zero page, the stack, `$C000-$FFFF` or the language card. |
| State | In `vtw_core_top`, per read-bank-review finding 3. `soft_switch_manager` gains only constant-0 field assignments. |
| Core change | New `vpa` output on `w65c02_core`, computed from `state_q` only. |
| TURBO caches | Never invalidated by the pair. A registered `cycle_zpb_redirect_q` vetoes hits. |
| Cost | About 60-90 LUTs, about 40 FFs, 0 BRAM. |
| Kill switch | Compile-time `ZPB_ENABLE`, plus runtime `vtw_ctrl_q[9]` gated with `ramworks_en`. |

**Fixed bytes versus a programmable address.** I found no strong reason for fixed bytes. They save about 17 FFs and 4 LUTs. A fixed pair would collide with existing zero-page users, for example the Monitor's IRQ save at `$45` (A). No agent outside the core needs the address. Keep the programmable pair.

## 1. Core change: code-space flag (`vpa`)

### 1.1 Current core (V)

- `sync` exists at `w65c02_core.sv:33` but is high only in `ST_FETCH` (`:998-1001`). It does not cover operand bytes, so it cannot serve as VPA.
- The address is a pure function of `state_q` plus registers (`:979-1157`). `state_q` is one-hot (`:205-206`). It changes only on `enable && ready` (`:1234`), so every output stays stable while stalled (`:7-9`).
- `rwb` is also a function of `state_q` alone (`:982`, `:1057`, `:1067`, `:1078`, ...).

### 1.2 New port

After `:33`, add `output logic vpa`. It is 1 when the cycle's address comes from PC, a vector or a JMP-indirect pointer. The name follows the 65816 pin, but the definition is wider. Build it in the existing `always_comb` at `:979`, or in a sibling block, from `state_q`:

| `vpa` | States (address source, V) |
|---|---|
| **1** (code space, never redirected) | `ST_FETCH` (`:998`). `ST_OPERAND`, `ST_ABS_HI`, `ST_IMPLIED`, `ST_BRANCH_DUMMY`, `ST_BIT_BRANCH_OFFSET/DUMMY/CROSS`, `ST_PUSH_DUMMY`, `ST_PULL_DUMMY_PC`, `ST_JSR_LOW`, `ST_RTS_DUMMY_PC`, `ST_RTI_DUMMY_PC`, `ST_BRK_SIGNATURE`, `ST_INT_DUMMY`, `ST_WAI_DUMMY`, `ST_STP_DUMMY` (all `pc_q`, `:1003-1019`). `ST_BRANCH_CROSS` (`:1021`). `ST_NOP_ABS_DUMMY` (`pc-1`, `:1041`). `ST_JSR_HIGH` and `ST_RTS_FINAL` (`:1106-1110`). `ST_JMP_X_DUMMY` (`pc-2`, `:1137`). **`ST_JMP_IND_LO/HI/LAST` and `ST_JMP_X_LO/HI` (pointer, `:1131-1142`, decision D1).** `ST_RESET_VECTOR_*` and `ST_INT_VECTOR_*` (`:995-996`, `:1128-1129`). `ST_WAIT`, `ST_STOP` (`:1144`). `ST_RESET_0/1` (default `pc_q`). |
| **0** (data) | `ST_MEM_READ`, `ST_DECIMAL_EXTRA`, `ST_RMW_READ` (`:1049-1052`). `ST_MEM_WRITE` (`:1054`). `ST_RMW_MODIFY`, `ST_RMW_WRITE` (`:1060-1069`). `ST_ZP_INDEX`, `ST_INDX_DUMMY`, `ST_PTR_LO/HI`, `ST_BIT_BRANCH_READ/REPEAT` (zero page). All stack states (`:990-993`, `:1075-1127`). |
| `ST_INDEX_DUMMY` | 0 when the address is `ea_q`: `op_q==OP_STA && mode_q∈{ABSX,ABSY} && !page_cross_q`, the same test as `:1033-1035`. Otherwise 1 (the address is `pc-1`, `:1038`). |

- **D1 (recommended): JMP `(abs)` and `(abs,X)` pointer reads are code space.** The 65816 also takes those pointers from bank 0 or K, never from DBR. Two reasons:
  - The //e ROM IRQ path ends with `JMP ($03FE)`, and BRK uses `$03F0` (A). A redirected pointer read would take the vector from bank N and crash.
  - Program jump tables in main keep working while the pair is set.
- Vectors (`$FFFA-$FFFF`) and RTS/RTI pulls (`$01xx`) are never in `$0200-$BFFF`, so their flag value does not matter. They are listed for completeness.
- Depth: an OR of about 25 one-hot bits plus one registered 3-input term, about 2 LUT levels from flops. That is earlier than `addr`, which goes through the `pc_q±k`, `ea_q+1` and `ptr_q+1` adders. It is the same class as `rwb`.

### 1.3 TURBO paths (V)

| Path | Effect on classification |
|---|---|
| `turbo_fetch_skip_pc` (`:903-905`, `:1276-1309`) | Removes PC dummy reads (implied, push, pull, RTS, RTI). No bus cycle occurs, so no flag is needed. |
| ZP,X / (zp,X) index skip (`:1358-1390`) | The removed read is in zero page. The data access that follows is its own cycle with `vpa=0`. |
| Taken-branch skip (`:1404-1411`) | Removes PC reads only. |
| `turbo_skip_abs_dummy` (`:912-914`, `:1462`) | Removes the `pc-1` read, or the same-page STA `ea` false read when the base is not `$Cxxx`. Nothing is read. |
| `turbo_skip_indy_dummy` (`:916`, `:1503`) | Removes a `pc-1` read. |
| `turbo_skip_rmw_dummy` (`:917`, `:1561`) | Removes the `ST_RMW_MODIFY` re-read. |
| RTS final and JSR stack dummy (`:918`, `:1655`, `:1675`) | Removes PC or stack reads. |

No TURBO path removes or merges a real operand fetch or a real data access. `cycle_ticks` (`:923-970`) is unaffected.

### 1.4 Dummy reads

| Dummy | Class | Does it matter? |
|---|---|---|
| Page-cross and indexed dummy at `pc-1` | code | No. It stays on main, which is also the faster TURBO path. |
| Same-page `STA abs,X/Y` false read of `ea` | data, **read** mapping (`zp_rd`) | Performance only. It is never I/O, since `$Cxxx` is never redirected. In classic modes with `zp_rd≠zp_wr` it can evict or flush the single RamWorks line before the write. TURBO skips it. |
| `ST_RMW_MODIFY` re-read | data, same bank as the real read | No |
| Decimal extra cycle | data (non-IMM, `ea`) or zero page (IMM, `:1154-1156`) | No |
| TURBO-skipped cycles | none | No |

### 1.5 Registering in `vtw_core_top` (V for existing lines)

- Connect `.vpa(core_vpa)` at the instance (`vtw_core_top.sv:361-394`).
- `core_vpa` is consumed in `X_CAPTURE` together with `core_addr` and `core_rwb`: it enters the translation (`:511-515`) through the per-cycle `TranslateState` (section 3).
- Its effect is registered at the `X_CAPTURE` edge (`:1912-1921`) in three places:
  - `cycle_xl_decoded_q` (the bank);
  - `cycle_translate_state_q` (the gated enable bits, so the `tb_vtw_system.sv:371-395` monitor recomputes the same tuple);
  - a new `cycle_zpb_redirect_q`.
- Optional: `cycle_vpa_q` (1 FF) for benches and traces.

## 2. Registers and write detection

### 2.1 State (all in `vtw_core_top`)

| Register | Width | Meaning |
|---|---|---|
| `zpb_armed_q` | 1 | `ZPB_ENABLE && vtw_ctrl_zpb && ramworks_en`, registered |
| `zpb_on_q` | 1 | Pair address is nonzero |
| `zpb_rd_addr_q`, `zpb_wr_addr_q` | 8+8 | `zp_rd`, `zp_rd+1` (the +1 is precomputed on the `$C069` write) |
| `zpb_rd_en_q`, `zpb_rd_full_q` | 1+8 | Value nonzero and valid; value+1 (2..128) |
| `zpb_wr_en_q`, `zpb_wr_full_q` | 1+8 | The same for writes |
| `zpb_pend_q` | 1 | A committed CPU write to page 0 is waiting to apply |
| `cycle_zpb_redirect_q` | 1 | Tuple bit, used for the TURBO veto |

Decoding a stored byte `v`: `en = (v != 0) && !v[7]` and `full = en ? {1'b0, v[6:0]} + 1 : 0`. The adder has registered operands and sits off the critical path.

### 2.2 `$C069` enable

- Condition: `zpb_c069_wr = zpb_armed_q && core_active && xstate_q==X_ROUTE && xl_is_bus && xl_is_write && cycle_addr_q==16'hC069`. Every operand is registered. It fires on the same `X_ROUTE` edge that `vsss` uses (`ssm_apply_pulse`, `:1254`).
- Action:
  - `zpb_on_q <= (wdata != 0)`
  - `rd_addr <= wdata`
  - `wr_addr <= wdata + 1`
  - both en/full pairs `<= 0`
- The `X_ROUTE` branch is **not** changed. The write still takes the `X_BUS` default (`:2023-2025`). Consequences:
  - no new FSM branch;
  - no barrier exemption;
  - `tb_vtw_usb_joystick.sv:306/323` ("C06x write was swallowed") still passes;
  - `README_USB_JOYSTICK.md:307` stays true.
- Cost: one bus cycle, plus the active-mirror barrier wait (`:1414-1415`), once per enable.
- `$C069` is not an exposure access (`:1390-1401`), so it never forces a mirror flush.
- If the bus half is aborted by a re-hold, the latch was already applied. That is harmless: no motherboard state depends on it, and the re-hold clears the pair anyway (section 4).
- Nothing else decodes `$C069` writes. The read-bank review confirmed this against `:587-603`, `:1101-1112`, `:1394-1400`, `vtw_bus_engine.sv:70-74` and `soft_switch_manager.sv:174-190`. `onee_motherboard_io.sv:250-277` has no `$C06x` write effect (V).

### 2.3 Detecting writes to `zp_rd` and `zp_wr`

The watch is on **logical** `$00xx` for any CPU write, whatever ALTZP or the `$C073` bank say (decision D4).

```
// Commit edge: the edge that commits the CPU write
zpb_pend_q <= zpb_on_q && core_active && !cycle_rw_q && cycle_addr_q[15:8] == 8'h00 &&
              ((xstate_q == X_ROUTE) || turbo_shadow_write);
// Apply edge: the next edge (tuple still holds the write, see 2.4)
if (zpb_pend_q) begin
  if (cycle_addr_q[7:0] == zpb_rd_addr_q) {zpb_rd_en_q, zpb_rd_full_q} <= dec(cycle_wdata_q);
  if (cycle_addr_q[7:0] == zpb_wr_addr_q) {zpb_wr_en_q, zpb_wr_full_q} <= dec(cycle_wdata_q);
end
```

**Why this covers every write path (V):**

- **Every write to `$00xx` is the last cycle of its instruction.** `ST_MEM_WRITE → ST_FETCH` (`:1553-1556`) and `ST_RMW_WRITE → ST_FETCH` (`:1564-1567`). Stack, JSR and interrupt pushes address `$01xx` (`:1075-1127`).
- **Normal and TURBO-miss writes pass `X_ROUTE`** exactly once per access. The state always leaves after one clock (`:1974-2043`). This holds for:
  - main zero page: shadow write, `:1307-1308`, `:1320`;
  - ALTZP with `$C073` bank 0: aux shadow;
  - ALTZP with bank N: `X_RW_LOOKUP`, `:2027-2028`.
- **TURBO fast writes skip `X_ROUTE`.** `X_CAPTURE → X_TURBO_DONE` (`:1952-1953`), committed by `turbo_shadow_write = X_TURBO_DONE && core_en && !cycle_rw_q` (`:1245-1246`). A reissue after `turbo_invalidate` (`:1968-1969`) commits nothing because `core_en` stays low, so `zpb_pend_q` is not set.
- **Indexed and indirect writes** (`zp,X` wraps within page 0 at `:1363-1365`, `:1476-1478`; `abs`, `abs,X/Y`, `(zp),Y`, `(zp,X)`, `(zp)`) are detected by the final `cycle_addr_q`.
- **RMW, TSB/TRB, RMB/SMB and `INC zp_rd`** load the result byte.
- **Reads of the pair bytes change nothing.**

**Agents outside the core cannot load the pair.** Only core cycles are watched, and none of the other agents writes zero page during a session:

| Agent | Can it write zero page? | Evidence |
|---|---|---|
| Memory API | No. Minimum address `$0200`. | V `memory_api.h:13`, `memory_api.c:47-50` |
| SmartPort direct spans | No. Rejects `< $0200`. | V `smartport_service.c:559-561`, `:761-762` |
| CPU0 posted injection | Video windows only | V `vtw_core_top.sv:238-245` |
| `vtw_service` shadow writes | No. Writes `$03F3/$03F4` and ROM. | V `vtw_service.c:331-367` |
| Raw port B | Physically yes: an 18-bit physical address (`vtw_core_top.sv:219-226`) covers main `$00xx`. | A: no caller does it during a session. If one did, the byte and the register would disagree, and the register stays authoritative. |

### 2.4 Visibility proof: `stx zp_rd` followed by a redirected access

- **The earliest data access to `$0200-$BFFF` after a zero-page write W is W+4.** W+1 is always `ST_FETCH` (`vpa=1`), including interrupt recognition (`:1256-1261`). An absolute read is W+1 fetch, W+2 low byte, W+3 high byte, W+4 read. `(zp),Y` is W+5. An interrupt entry is later still.
- **`cycle_addr_q` and `cycle_wdata_q` still hold W's tuple at the apply edge.** They change only in `X_CAPTURE` (`:1912-1914`), and a register sampled on the same edge that overwrites them sees the old value.

| Mode | Edges | First translation that sees the new value |
|---|---|---|
| TURBO fast write | E1: `X_CAPTURE` of W. E2: `X_TURBO_DONE` completes (`core_en`), `zpb_pend_q←1`. E3: apply, and W+1 (`ST_FETCH`) is captured with the old value, which does not matter because it is code. | W+2 capture, at or after E5. Margin: 2 core cycles before W+4. |
| TURBO write that misses the map | E1 → `X_TURBO_DONE` → E2 → `X_ROUTE` → E3 commit → E4 apply (in `X_MEM_CAPTURE`) → `X_MEM_DONE`, which completes at E5 at the earliest | W+1 capture |
| Full, divided, 1 MHz, slowdown (`eff_mode`, `:1153-1162`), 33 MHz | `X_CAPTURE`, `X_ROUTE` (commit), `X_MEM_CAPTURE` (apply), `X_MEM_DONE` waits for `pace_ok` (`:1514`, `:2119-2123`) | W+1 capture |
| ALTZP to a RamWorks bank | `X_ROUTE` (commit), then `X_RW_LOOKUP` (apply) ... `X_RW_DONE` | W+1 capture |
| `pause` or a SmartPort hold | They gate only `core_en` (`:1523`). The commit and apply edges are not gated. | unchanged |

The deferred apply keeps `core_en` off the value registers' clock enables. Only the 1-bit `zpb_pend_q` sees it, with the same precedent as `slow_update_valid_q <= core_en` at `:1888`. Commits are at least 4 edges apart (at least 3 core cycles of at least 2 clocks each), so one pending bit is enough.

## 3. Translation

### 3.1 `globals.sv` (V for the current lines)

**`TranslateState` (`:181-195`).** Append after `sw_ramworks_bank` (`:194`):

```
logic       sw_zpb_rd_en;
logic [7:0] sw_zpb_rd_full;
logic       sw_zpb_wr_en;
logic [7:0] sw_zpb_wr_full;
```

The width grows from 19 to 37 bits.

**`translate_state_from_sss` (`:197-215`).** Set all four fields to 0.

**`translate_apple_addr`, else-branch (`:263-269`).** This branch is exactly `$0200-$BFFF`: `$Cxxx`, `$0000-$01FF` and `$C000-$FFFF` are handled at `:254-262`. Lines 264-268 stay as they are. Append:

```
            // Zero-page bank pair (vTW private state only; 0 = follow).
            if (rw_in ? st.sw_zpb_rd_en : st.sw_zpb_wr_en)
                q_bank_sel = rw_in ? st.sw_zpb_rd_full : st.sw_zpb_wr_full;
```

- The route stays `APPLE_ROUTE_CACHE` (`:336-341`).
- With a bank of 2 or more, `vtw_shadow_map` returns invalid (`vtw_shadow.sv:47-58`), so the access becomes `xl_is_ramworks` (`vtw_core_top.sv:643-644`) and is served from PSRAM through the line cache.
- Physical bank 128 is `0x80xxxx`, as `$C073`=127 already produces (`soft_switch_manager.sv:145-146`).

### 3.2 How the code-space flag selects

In `vtw_core_top`, add one local function used at `:512` and `:1919`:

```
st = translate_state_from_sss(vsss);
st.sw_zpb_rd_en   = zpb_rd_en_q && !core_vpa;   st.sw_zpb_rd_full = zpb_rd_full_q;
st.sw_zpb_wr_en   = zpb_wr_en_q && !core_vpa;   st.sw_zpb_wr_full = zpb_wr_full_q;
```

- `:1185` must change to `TranslateState turbo_mapping = translate_state_from_sss(vsss);`. **This fix is mandatory:** `wire [18:0]` would silently keep only the low 19 bits of the widened struct, which are the new fields. The pair fields in this compare are constant 0, so a pair change never invalidates the TURBO caches.
- `cycle_translate_state_q` widens. Synthesis prunes all of it except `sw_intcxrom` (`:668`).

### 3.3 Motherboard side

- `soft_switch_manager.sv:81-96`: add four constant assignments. Without them the `always_comb` would infer latches for the new fields. The calls at `:158` and `:247` are unchanged, and the added `if` folds away.
- The instances at `apple_top.sv:348` and `vtw_core_top.sv:440` are functionally unchanged. Stage 0 checks that their LUT counts do not move.
- `tb_vtw_system.sv:378` compiles unchanged.

### 3.4 80STORE/PAGE2 and `$C073` while the pair is set

- **D2 (recommended): a nonzero value wins over the 80STORE display windows.** This departs from read-bank D3. The whole of `$0400-$07FF` and `$2000-$3FFF` in bank N is reachable, and read-modify-write stays coherent when `rd==wr`. A window access with a zero direction keeps today's 80STORE/PAGE2 rule. The pair is explicit, and the software contract zeroes it before any firmware call, so the 80-column firmware is never affected.
- **`$C071/$C073` writes never touch the pair.** The pair's only load sources are those in 2.2, 2.3 and section 4. `$C073` updates only `vsss` (`soft_switch_manager.sv:141-144`). A nonzero direction ignores `$C073` completely, because its bank is absolute. A zero direction follows it as today.
- `$C073` still steers:
  - zero page, the stack and the language card under ALTZP;
  - RAMRD/RAMWRT accesses with a zero direction;
  - and it remains an exposure access that flushes the mirror (`:1400`).

## 4. Reset and state

Priority, highest first: `!rstn`, then `!core_res_n`, then `!zpb_armed_q`, then the `$C069` write, then the zero-page apply.

| Event | Pair afterwards | Mechanism |
|---|---|---|
| Power-on, fabric reset | Off, 0/0 | `!rstn` |
| Apple RES# (power-on, Ctrl-Reset, takeover pulse) | Off | `core_res_n = enable && core_run && ab_read.res` (V `:352`) |
| Session start | Off | `enable` rises before reset release (V `:44-46`), so `core_res_n` was low |
| Session end | Off | `!enable` gives `!core_res_n` |
| PS drops CORE_RUN without RES# (core restarts from the reset vector) | Off | Same term. The PS does this in every state except RUN and RES_HOLD (V `vtw_service.c:243-246`). This fixes read-bank-review finding 4. |
| `pause`, SmartPort or memory API flush+hold (`rw_hold_q`) | Kept | They gate only `core_en` (V `:1523`) |
| Speed change, `$C074` | Kept | Invalidates only the TURBO caches (V `:1208`), which the pair does not use |
| `ramworks_en` falls | Off | `zpb_armed_q` clears on the next edge. A: `ramworks_en` changes only at session edges while the core is held (V `boot_menu_service.c:332-344`). If it ever changes live, at worst one access in that clock is served `$FF` and counted in `cnt_invalid_q` (`:2030-2035`). |
| Kill switch falls | Off | Same |
| ONE//e | Live | Internal to the core. `$C06x` writes have no ONE//e effect (V `onee_motherboard_io.sv:250-277`). A: `ramworks_en` is set there when the RAM tab is on. |
| II+ host | Live | RamWorks is on for an accelerated II+ (V `boot_menu_service.c:321-335`). A: the enable write reaches the II+ `$C06x` strobe for one cycle, which may cause a harmless D7 conflict. |

**Registers versus memory bytes:**

- Enabling clears both registers. It does not read or write memory.
- A read of `zp_rd` before the first write is an ordinary zero-page read. It returns whatever byte is in RAM, and the hardware ignores it. A stale byte of `$05` can therefore sit next to a register of 0.
- The byte mirrors the register only while all writes to it come from the CPU and ALTZP is not changed with the pair in use.
- Software should write both bytes right after the `$C069` write.

## 5. Consumers outside the core

| Consumer | Uses the mapping? | Change |
|---|---|---|
| SmartPort ROM byte path | Yes, through the core | None. It is pair-aware automatically. |
| SmartPort direct block WRITE source | Read mapping (V `smartport_service.c:947-957`, `write_access=0`) | **Required**, below |
| SmartPort direct block READ destination | Write mapping (V `:750-772`, `write_access=1`) | **Required**, below |
| Memory API | No. Explicit bank, minimum `$0200`. | V `memory_api.c:38-55`. Feature bit only. |
| Disk II private reads | No. I/O `$C0Ex` only. | None (V `vtw_core_top.sv:704-709`) |
| Posted video, capture, renderer | Only banks 0 and 1 are posted | None (V `:565-569`) |
| `vtw status` | Prints 11 switch bits | Add one line (V `vtw_service.c:1246-1263`) |

**SmartPort, v1: fall back when the pair is active.**

- The snapshot is latched at the CTRL write while the core waits (V `smartport_card.sv:502-503`), so the pair cannot change under it.
- `vtw_core_top.sv:216` and `:531-548`: widen to `[23:0]` by prepending `{zpb_wr_en_q, zpb_rd_en_q}`.
- `apple_top.sv:1747`: width.
- `smartport_card.sv`:
  - `:101`, `:155`: width;
  - `:156-173` (bus-path snapshot): the two new bits are 0;
  - `:461`: reset value;
  - `:625`: return `{8'h0, sss_snapshot_q}`.
- `smartport_service.c:65-74`: add `SP_SSS_ZPB_RD_BIT (1UL<<22)` and `SP_SSS_ZPB_WR_BIT (1UL<<23)`.
- `sp_vtw_memory_phys` (`:350-387`): for `$0200-$BFFF`, return -1 when the bit for this direction is set. Span building then fails (`:567-569`), and the byte path, which is correct, takes over.

**v2 (optional): exact direct mapping.** `SP_REG` index 7 is free (V `smartport_card.sv:295-301`). It would carry `{wr_full, rd_full}`. The mapping would use `full` as the bank for that direction and keep the existing `bank > 127` rejection (`:383-385`).

**Debug register and features:**

- New read-only card-control register `8'hB0`. A: it is free; it is absent from `apple_top.sv` localparams and `card_control_regs.h`, and `8'hAD` is now `SLOT2_CONTROL` (V `apple_top.sv:530`). Layout:
  - `[7:0]` pair address;
  - `[14:8]` rd value, `[15]` rd enabled;
  - `[22:16]` wr value, `[23]` wr enabled;
  - `[24]` armed, `[25]` kill-switch bit;
  - `[31]` = 1 (implemented).
- `vtw_service.c` prints `vtw: zpb pair=$06 rd=08 wr=-- armed=1`.
- `memory_api.h:25`: add `MEMORY_API_FEATURE_ZPBANK 8U`, reported at `memory_api.c:74-75` when bits 31 and 24 are set. This needs a backend `features()` hook. Bump the minor version.

**Kill-switch bit.** `vtw_ctrl_q[9]` is free (V `apple_top.sv:2006-2068`, `:2157-2167`). Both `vtw_ctrl_value` (`vtw_service.c:158`) and `vtw_onee_ctrl_value` (`:191`) must set it, because `vtw_apply_ctrl_live` compares the full readback (`:249-250`).

## 6. Interactions

**TURBO caches, without change 4.**

- The pair never invalidates the caches, because its fields are 0 in `turbo_mapping` (section 3.2).
- Correctness then needs a veto. The read hit compares only the logical tag (V `vtw_core_top.sv:1237-1239`), and a write hit uses a logical-page map entry that holds a shadow physical address (`vtw_turbo_cache.sv:64`, `:77-81`). A redirected access to `$4000` would otherwise hit main and write the main shadow.
- Veto: `zpb_redirect_d = !core_vpa && (core_rwb ? zpb_rd_en_q : zpb_wr_en_q) && core_addr[15:9]!=0 && core_addr[15:14]!=2'b11`, registered as `cycle_zpb_redirect_q` at `:1912`. Then `turbo_hit = !cycle_zpb_redirect_q && ...` (`:1237`).
- Redirected cycles never fill or snoop:
  - fills need `xl_shadow_valid` (V `:1212-1215`);
  - the snoop needs a shadow write (V `:1232`).
- Path of a redirected access in TURBO: `X_CAPTURE`, `X_TURBO_DONE` (miss), `X_ROUTE`, `X_RW_LOOKUP`, `X_RW_DONE`. That is 5 clocks on a line hit.
- **With change 4:** `cycle_cacheable_q` must come from the pair-aware translation (`capture_xl_decoded_d`). Banks of 2 or more are then never cacheable and the veto is redundant. Keep one of the two.

**RamWorks line cache.** The tag is physical (V `:1058-1060`), so there is no flush on a pair change. The single line thrashes when `zp_rd≠zp_wr` both hit PSRAM, or when pair and `$C073` accesses are mixed. This is not new, but it now appears in a natural copy loop (section 7).

**Lazy SHR mirror (change 3).** Redirected writes never enter the mirror or the posted queue (V `:565-566`), and zero-page stores are not exposure accesses. The pair gives the renderer far reads with no `$Cxxx` access at all.

**Quiet switches (change 7).** Plainly: for far accesses to `$C073` banks 1-127, this design makes change 7 unnecessary. Change 7 would still buy four things:

- quiet access to **base aux** data (the pair cannot name it);
- quiet ALTZP and language-card switching;
- quiet `$C073` changes for zero page, the stack and the language card;
- speed for unmodified software that uses RAMRD/RAMWRT/`$C073`.

**Relaxed PSRAM admission (change 2).** Redirected accesses are ordinary line-port traffic with banks of 2 or more, so they are consistent with the change's bank assertion (A, change 2 is not built). Change 2 and a multi-line cache decide the miss cost, which dominates random texel reads.

**Interrupts.**

- The vector fetch (`$FFFx`) and the stack pushes (`$01xx`) are never redirected, by address.
- The handler's code fetches and a `JMP ($03FE)` pointer are not redirected (D1).
- The handler's data accesses to `$0200-$BFFF` **are** redirected.
- A: the //e ROM IRQ entry makes no other data access to `$0200-$BFFF`.
- A: the ProDOS interrupt dispatcher does make such accesses.

## 7. Software contract

**Enabling:**

1. `lda #PAIR / sta $C069`, then `stz PAIR / stz PAIR+1`.
2. The pair must not overlap zero page used by anything that runs while it is set, including the ROM IRQ entry (`$45`, A) and ProDOS (`$40-$4E` during MLI calls, A).
3. Suggested: `$06/$07` (A: documented as free for user programs).
4. Keep ALTZP off while the pair is in use.

**Detection.** Run with SEI, with RAMRD, RAMWRT and 80STORE off, and with `PROBE` outside the probe's own code. The probe cannot report a false positive: without the feature, both stores land in main, so main reads `$5A` and the `$A5` test fails. That also covers RamWorks off (feature disarmed) and aliasing (redirected banks are PSRAM banks of 2 or more and cannot alias main).

```
        lda #$06 : sta $C069 : stz $06 : stz $07
        lda #$A5 : sta PROBE        ; main
        lda #1   : sta $07          ; writes -> $C073 bank 1 (physical 2)
        lda #$5A : sta PROBE
        stz $07
        lda #1   : sta $06
        ldx PROBE                   ; $5A if present
        stz $06
        lda PROBE                   ; main: $A5 if present, $5A if absent
        cmp #$A5 : bne absent
        cpx #$5A : bne absent       ; present
absent: lda #0 : sta $C069
```

With SmartPort present, check `MEMORY_API_FEATURE_ZPBANK` first.

**Bank-to-bank copy (both banks nonzero):**

```
        lda #SRC : sta $06
        lda #DST : sta $07
        ldy #0
loop:   lda (src),y       ; bank SRC
        sta (dst),y       ; bank DST
        iny
        bne loop
        stz $06 : stz $07
```

This is correct, but with today's single-line cache every byte alternates lines, costing a dirty flush plus a fill. For bulk copies, bounce 32-64 bytes through zero page or language-card RAM (read phase, then write phase), or use memory API COPY.

**Interrupt handler** (own `$03FE` vector; ALTZP off):

```
irq:    lda $06 : pha : lda $07 : pha
        stz $06 : stz $07          ; standard rules from here on
        ...                        ; handler body
        pla : sta $07 : pla : sta $06
        ...                        ; restore A per your ROM path
        rti
```

Under ProDOS's own dispatcher, hold SEI while either byte is nonzero.

**Before any ProDOS, ROM or 80-column firmware call:** `stz $06 / stz $07`, which costs 6 cycles. Hot tables used in the inner loop belong in zero page, the stack page or language-card RAM, or can be duplicated at the same address in the data bank.

## 8. Cost, timing, stages, tests

### Cost

| Item | FF | LUT |
|---|---:|---:|
| Core `vpa` | 0 | 3-6 |
| Pair registers, `$C069` latch, detection, apply | 38 | 25-30 |
| Translate override (vTW instance only) | 0 | 8-12 |
| Redirect bit and veto | 1 | 2-4 |
| `cycle_translate_state_q` widening | pruned | 0 |
| Snapshot bits (v1) | 2 | 0-2 |
| Debug register read mux | 0 | 10-15 |
| **Total** | **about 40** | **about 60-90** |

0 BRAM, against the budget of 110 of 140 tiles and 34,888 of 53,200 LUTs.

### Timing (all new operands registered, except `core_vpa`, which is in the same class as `core_rwb`)

| Path | Change | Risk |
|---|---|---|
| `core_addr[15:9]`/`core_rwb`/`core_vpa` to `cycle_xl_decoded_q[23:16]` (`:511-515`, `:1920`) | One final select per bank bit. Its select and data are early; only the region decode is late. | Medium. The only sensitive path. |
| `turbo_hit` to `turbo_complete` to `core_en` (`:1237-1244`) | One registered AND input | Low to medium. Fallback: fold the veto into the `turbo_*_valid_q` capture (`:1943-1944`). |
| `core_en` to `zpb_pend_q` | One flop D input | Low |
| `$C069` latch, apply | Registered tuple, `X_ROUTE` state bit | Low |
| Motherboard decodes | Constant-folded | Check that LUT counts are unchanged |

### Compared with the `$C069` read-bank design

| | Read-bank (review-corrected) | Zero-page pair |
|---|---|---|
| Size | 50-90 LUTs, 30-40 FFs | 60-90 LUTs, about 40 FFs |
| FSM edits | Private-serve branch, plus the capture-enable barrier exemption | None |
| Core edit | None | `vpa` output |
| Direction | Reads only | Reads and writes |
| Where code may run while active | Zero page, stack, language card, ROM | Anywhere |
| Main data while active | RAMRD toggle, a bus cycle | One zero-page store |
| Read back / IRQ save | No (write-only register) | Yes (memory byte) |
| Cache invalidation | On base to non-base | Never |
| Benches broken | USB `$C06x` sweep | None |
| Documents to amend | Three | `README_VIRTUAL_TRANSWARP.md:278-281` only |
| New risk class | — | A misclassified core state |

### Stages, one full build each against +0.200 ns

The baseline passed at +0.205 ns only after an extra post-route pass.

| Stage | Content | Expected |
|---|---|---|
| 0 | Struct fields, translate edit, `:1185` fix, SSM constants, `vpa` port connected with all enables at 0 | Functionally equivalent. Motherboard instance LUT counts unchanged. |
| 1 | Registers, `$C069` latch, `vpa` gating, veto, kill switch (`vtw_ctrl_q[9]`, default per D5), snapshot bits, `8'hB0`, `vtw status` | Complete |
| 2 | PS: kill-switch owner and profile key, SmartPort fallback, memory API feature bit, README amendment | Release |
| 3 (optional) | Send redirected cycles from `X_CAPTURE` straight to `X_ROUTE` (4 clocks instead of 5) | Measure first |

- **Kill switch:** with `vtw_ctrl_q[9]` low, or `ZPB_ENABLE=0`, behaviour is F1.2.1 exactly.
- **Timing fallback:** a post-capture override keyed by `cycle_zpb_redirect_q`. It is not preferred, because every consumer of `xl_decoded` (`xl_is_aux`, `xl_is_posted`, `xl_shadow_valid`, the `$9DF8` tracker, the overlay) would have to learn about the pair.

### Tests

| Bench | Cases |
|---|---|
| `tb_w65c02_vectors.sv` and `tb_w65c02_turbo.sv` (`scripts/test_w65c02_core.py`, `test_w65c02_turbo.py`) | Check `vpa` against the state table for every opcode, classic and TURBO. It must be 1 exactly on PC-, vector- and JMP-pointer-sourced cycles. Include interrupt entry and WAI. |
| New `tb_translate_zpb.sv` | With the enables at 0, the result equals a copy of the old function for every switch combination, address class, direction and bank (0, 1, 127). With them set, only `$0200-$BFFF` in the matching direction changes, 80STORE windows included. |
| `tb_vtw_system.sv` | The monitor at `:371-395` must stay green. Enable, redirected read and write, `$C069` still seen on the bus (phase checker `:424-494`). Clearing on RES#, CORE_RUN drop, `ramworks_en` fall and kill switch. `$C073` write leaves the pair alone. |
| `tb_vtw_turbo.sv` | New `zpb_program` beside `bank_program` (`:835`). STX to the pair, then `LDA abs` and `LDA (zp),Y` at the minimum distance, in each `benchmark` mode (`:717`). No invalidate (perf slot 2). Warm main `$4000` read and page `$40` fast-write entries, then redirect: RamWorks is hit and main is unchanged (`sh_check`). `INC abs` with rd≠wr. Same-page `STA abs,X` classic. `JMP ($4000)` with the pair set. IRQ with the pair set. A redirected write to aux `$2000` under RAMWRT is not posted and not recorded. `freeze_core` (`:646`) and `pending_write_abort` (`:670`) around a pair write. ALTZP with bank N, the write going through `X_RW`. |
| `tb_vtw_usb_joystick.sv` | Status sweep (`:306-323`) with the kill switch off and on: both pass unchanged. |
| `tb_smartport_shortcut.sv` | Snapshot bits 22/23 (zero on the bus path). PS host test of the fallback. |
| `tb_onee_motherboard_io.sv` | Unchanged |
| Regression | Every script under `README_TURBO.md` "Validation and build" |

### Decisions for the owner

- **D1:** JMP-indirect pointer reads are code space.
- **D2:** a nonzero pair value overrides the 80STORE windows.
- **D3:** values `$80-$FF` are reserved and read as 0.
- **D4:** the watch is on the logical zero-page address, whatever ALTZP says.
- **D5:** the kill-switch default. I recommend on whenever RamWorks is on, because an effect needs both the `$C069` write and a later nonzero store.
- **D6:** SmartPort fallback bits (v1) or exact mapping (v2).
- **D7:** keep the `$C069` write on the bus on every host.

### Not verified

- The //e ROM IRQ, BRK and 80-column paths and the ProDOS dispatcher behaviour marked A.
- Which zero-page locations are free.
- That `8'hB0` is free across the whole decode.
- That `ramworks_en` changes only while the core is held.
- The II+ electrical effect of a `$C06x` write.
- The ordering relative to change 4.