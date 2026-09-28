# Performance and hardware critique: incremental-hybrid V816 proposal

Path legend: `[FW]` = `.../scratchpad/appletini-one-main`, `[UP]` = `.../scratchpad/iigs-doom`, `[SW]` = `<appletini-software>/demos/doom`, `[R]` = `.../scratchpad/research`, where `...` is `<scratch>`.

"Verified" means I read the line in this session. Nothing was created or modified. All timings are computed, not measured.

## 1. Verdict

The proposal's 3.5 to 4.1 FPS is not reachable on today's firmware. My estimate for E1M1 idle is about 1,300 ms (0.8 FPS) as specified, and about 700 ms (1.4 FPS) with the fixes in section 8.

Three errors account for most of the gap:

- **Native code does not fit.** 8 KB of fast memory holds about 1,100 translated source instructions. Upstream's own per-frame hot sections are about 58 KB of 65816 code.
- **The interpreter is under-costed.** Its instruction fetch is a PSRAM read, and its main-memory reads need RAMRD toggles.
- **Replay is drain-bound and serialised.** It costs about 31 ms idle, not 15 ms.

## 2. Hardware facts used (verified in the snapshot)

| Fact | Value | Source |
|---|---|---|
| Extended memory cache | One line: `rwc_line_q`, 64 bits of data | `[FW]hdl/apple/vtw_core_top.sv:1045-1048` |
| PSRAM hit path | CAPTURE, ROUTE, RW_LOOKUP, RW_DONE: 4 fabric clocks, never in the TURBO cache | `vtw_core_top.sv:2028, 2045-2052`; `[FW]README_TURBO.md:72` |
| PSRAM miss | Dirty line: flush, then fill (two operations). Clean: one fill | `vtw_core_top.sv:2054-2095` |
| PSRAM admission | At most one background operation per Apple bus cycle | `[FW]hdl/apple/psram_simple.sv:28-33, 232-239` |
| TURBO invalidation | Any change of translation state clears both caches | `vtw_core_top.sv:1206-1211` |
| TURBO cache size | 32+32 page mappings, 128-byte word cache, hit = 2 clocks | `README_TURBO.md:49-61` |
| SHR stall | Any `$Cxxx` access waits while active mirror bytes are pending | `vtw_core_top.sv:1414-1415, 1957-1962` |
| Active mirror range | All of aux `$2000-$9FFF` | `[FW]hdl/apple/vtw_video_policy.sv:25-31` |
| Exposure accesses | `$C080-$CFFF`, `$C05x`, writes to `$C071/$C073` and others force a full flush | `vtw_core_top.sv:1390-1402` |
| Direct video write | One extra fabric clock for admission | `README_TURBO.md:159-166` |
| amem | 1 to 16 descriptors, endpoints `$0200` to below `$C000`, PRIVATE emits no renderer records | `[FW]README_MEMORY_API.md:110-111, 159-163, 173-188` |
| Slot-4 window | 512 Apple cycles per access by default | `[FW]ps_sources/frontend/config_menu.c:76` |

Derived costs (my arithmetic):

| Item | Cost |
|---|---|
| PSRAM clean miss | about 0.7 to 1.0 µs |
| PSRAM dirty miss | about 2 µs |
| Sequential PSRAM read | at most 8 bytes/µs |
| Sequential PSRAM write | at most 4 bytes/µs (fill plus flush per line) |
| PSRAM hit | 30 ns, against 15 ns for a BRAM cache hit |
| Bus access | 1.5 µs average |

## 3. Findings, ranked

### 3.1 Critical

**C1. Native code budget is about 20 times too small.**

| Upstream hot region | 65816 bytes | Source |
|---|---:|---|
| LowCode (P_TryMove, P_CheckSight, P_RunThinkers) | 8,192 | `[UP]src/iigs/iigs.scm:34` |
| SegCode | 7,680 | `iigs.scm:114` |
| BspCode | 8,192 | `iigs.scm:118` |
| SegWalls | 2,366 | `iigs.scm:127` |
| logiccode, 4 regions | about 24,000 | `iigs.scm:132, 142, 161, 179` |
| MaskCode, HotMul | 3,840 | `iigs.scm:166, 191` |
| Core14, Core16 rows | about 2,100 | `iigs.scm` (read in full) |
| **Total, excluding drawers and replay** | **about 58 KB** | |

- The 58 KB assumes the regions are full. That is an assumption.
- At the proposal's 7.2 bytes per instruction and about 2.7 bytes per 65816 instruction (assumption), expansion is 2.7 times. That gives about 155 KB of native code.
- The map allots 8 KB. That is about 5 percent of it.
- "97% native" (T2) and "90% native" (T1) therefore have no memory behind them.
- Overlays do not rescue it. 155 KB is 19 groups of 8 KB. Seg code calls the multiplies and tic code calls map utilities, so groups would thrash at about 3 ms per swap.

Fix: see section 8, change 1.

**C2. Interpreter cost per instruction is about 3.9 µs, not 2.5 µs.**

| Component | Cost | Reason |
|---|---:|---|
| Dispatch and execute, 150 cycles at 50 M/s | 3.0 µs | Proposal's count; my clock rate |
| Code fetch line misses | 0.45 µs | The image is in PSRAM. A line holds about 3 instructions, and any other PSRAM access evicts it |
| RAMRD toggle pairs | 0.45 µs | About 13 percent of instructions read main `$0200-$BFFF` (pulls, returns, hot near data). Each pair is 2 bus accesses plus 2 invalidations, about 3.5 µs |

Fix: fetch through a code page cache in the language card, so RAMRD stays off during execution. Code has good locality, so this is where a page cache pays.

**C3. Replay is 31 ms idle and about 50 ms moving, not 15 ms.**

The write pass ends with a RAMWRT-off access. That access stalls until the column's bytes have drained. So drain time adds to CPU time instead of overlapping it.

| Item | Idle (13,000 rows) | Moving (26,880 bytes) |
|---|---:|---:|
| Mirror drain, about 0.98 µs per byte | 12.7 ms | 26.3 ms |
| Gather and shade, 35.5 cycles per row at 50 M/s | 9.2 | 14 |
| Write pass | overlaps drain | overlaps drain |
| Record walker, 900 records at about 250 cycles | 4.5 | 5 |
| Switches: 6 per column, 2 per record, about 2,200 | 3.3 | 3.5 |
| PSRAM misses: records and texels, about 3,500 | 3 | 4 |
| **Total** | **about 31 ms** | **about 50 ms** |

- The proposal counts 3 switches per column. I count 6: RAMRD on, RAMRD off, `$C073`=0, RAMWRT on, RAMWRT off, `$C073`=record bank.
- The proposal's own section 4 says 13 to 27 ms. Its section 6 table says 15.
- The tearing claim is also wrong. A 31 ms replay spans two PAL fields, so the seam appears in two or three published frames.

Fix: merge shade and write (RAMRD off, RAMWRT on, `$C073`=0: `ldy TEX+r / lda (CM),y / sta row,x`, 14 cycles). Skip unchanged bytes by comparing against the screen itself, which is readable BRAM. In an idle scene that removes most of the drain.

**C4. Record production through the far layer costs 60 to 70 ms per frame.**

- A `K_TEX` record is 11 byte stores (`[UP]src/iigs/lists.inc:34-52`, verified). A fill record is 5.
- Upstream stores them one byte at a time with DBR set to the record bank.
- Translated, each store is a far write at about 8 µs.
- 600 texture records and 1,600 fill records give about 14,600 stores plus `COLW` updates, so about 120 ms untreated. With record-level batching it is still about 25 to 30 ms.
- The page cache makes it worse. Each column has its own 256-byte page, so a seg that spans 40 columns takes 40 dirty misses at about 240 µs each.

Fix: build each record in zero page and write it in one RAMWRT session. Better, move records to fast memory (section 8, change 2).

### 3.2 High

**H1. F0 far access is about 7.5 µs, not 6 µs.**

| Component | `[dp],y` read |
|---|---:|
| CPU: inline fetch, 16-bit effective address, bank lookup, remap, straddle check, flag save, return; about 135 cycles | 2.7 µs |
| Two bus accesses | 3.0 |
| PSRAM miss (near certain, one line) | 0.9 |
| Two cache invalidations, refill | 0.4 |
| Bank change, about half the time | 0.75 |
| **Total** | **about 7.7 µs** |

- The proposal's 95 cycles omits the effective-address add, the straddle check and flag preservation.
- Static `long:` is cheaper, about 70 cycles, so about 6.5 µs.
- A far write is about 8.5 µs, because the dirty line costs a second operation.

**H2. A 16-bit access at offset `$7FFF` reads `$C000`.**

- Under the mapping rule, the low byte lands at physical `$BFFF` and the high byte at `$C000`. That is the keyboard register.
- Upstream guarantees no crossing of 64 KB banks. It does not guarantee anything about `$8000`.
- The straddle check is mandatory on every multi-byte access. It costs about 6 cycles and is included in H1.
- `[dp],y` with a 16-bit Y also needs the full add before the bank lookup.

**H3. Page cache at 99 percent hits is not credible with 16 pages.**

- Dirty miss is about 240 µs (clean load 105, write-back 135). The proposal lists only the clean case.
- Thinkers walk every mobj each tic. A mobj is 120 bytes, so about two per page. E1M1 has over 100 things, which is over 50 pages per tic and over 200 dirty misses per 4-tic frame (assumption on the mobj count).
- Break-even against F0 is 14 to 32 accesses per page visit.
- Expected result: F2 averages 4 to 5 µs per access on scattered data. That is a gain of about a third, not the sixfold the table assumes.

Fix: cache by object instead of by page. Copy the mobj, sector or node into a fixed fast buffer on entry and write it back if dirty.

**H4. Soft stack cannot be 2 KB at a constant offset.**

- The frame stack starts at `$3FFF` (`iigs.scm:32, 228`). The tic stack starts at `$1B6F` (`[UP]src/iigs/p_think65.s:182, 196`, verified).
- They are 9,360 bytes apart. A constant-offset mapping needs about 10 KB of fast memory.
- The tic stack is a plain nested switch, not a coroutine (`p_think65.s:193-212`, verified). So the hole model itself is safe.

Fix: override `LOGIC_SP` to sit about 1 KB below the frame stack top. Measure real depth before fixing the size.

**H5. Row blocks do not fit where they are placed.**

| Block set | Size (168 rows) | Must live in |
|---|---:|---|
| Gather, even and odd | about 2.4 KB | language card (RAMRD is on) |
| Shade | about 1.3 KB | main, not a mirrored window |
| Write, texture | about 1.0 KB | main, not a mirrored window |
| Write, fills, two chains | about 1.0 KB | main, not a mirrored window |
| Fuzz | about 1.7 KB | language card |
| Record walker | 2 to 4 KB (assumption) | language card |

- LC bank 1 gets 6 to 8 KB against 4 KB available.
- About 3.3 KB of patched main blocks have no home in the map. They cannot go in main `$0400-$0BFF`, because patched exits are writes into a posted window.

Fix: merging shade and write (C3) removes one set. Exit by a preloaded count instead of patching, so blocks can sit in immutable space.

### 3.3 Medium

| # | Problem | Corrected fact | Fix |
|---|---|---|---|
| M1 | Level window too small | Only `$2A-$3F` is mapped (22 banks). E1M3 needs 22.97 to 23.48 banks, and upstream's 4 MB window is 24 (`[UP]src/iigs/w_level65.s:521-532`, `iigs.scm:21`, verified) | Map `$0E-$0F`: 101 banks used, 25 spare |
| M2 | Sound and IRQ cost | 0.85 ms per VBL. At a 700 ms frame that is 42 VBLs, so 36 ms, not 8 | Update AY registers every second VBL; keep the burst short |
| M3 | 2D straight to the screen | `IIGS_DrawPatch` is read, mask, or, write per nibble. That is two far accesses, each followed by a drain stall: about 15 µs per pixel. A HUD line of 2,560 pixels is about 38 ms | Hand-written patch drawer that holds one aux session per patch column |
| M4 | Hardware stack | BSP at 2 bytes per level is correct (`[UP]src/iigs/r_bsp65.s:167, 209`, verified). Add far-layer nesting (4 to 6), interpreter re-entry (6 to 8 each), flag saves and the IRQ frame. A depth of 64 plus 30 call levels is about 190 to 220 bytes | Measure at M3 as planned; cap interpreter re-entry depth |
| M5 | Zero page | 211 + 16 + 24 = 251 bytes. 16 bytes cannot hold the registers, virtual PC, far pointers and interpreter scratch | Move cold `ztiny` variables to absolute |
| M6 | Multiply tables missing from the map | Dropping the quarter squares needs 8-bit tables, about 2 KB of fast memory | Add to the budget |
| M7 | Page tables and entry table missing | Three 256-entry page tables and the native entry table need 1 to 2 KB | Add to the budget |
| M8 | CPU rate | 60 M cycles/s is optimistic for straight-line code against a 128-byte word cache. Measured mix is 42 M/s | Use 50 M/s until M1 measures it |

### 3.4 Low

| # | Problem | Fix |
|---|---|---|
| L1 | Mailbox at aux `$A000` overlaps `FUZZ_DARKEN` at `$01:A000` (`[UP]src/iigs/i_viigs65.s:30`; `[SW]src/kernel/profile.s:3`, verified) | Move the mailbox above `$B600` |
| L2 | Aux `$0400-$0BFF` is a posted window (`vtw_core_top.sv:565-569`). Writable bank `$01` data there is flushed by bus cycles at the next `$C073` write | Keep only immutable data there |
| L3 | IRQ during a far access runs with RAMRD or RAMWRT on. Kernel variables at `$0200-$03FF` are then unreachable | Keep `vbl_count` and IRQ state in zero page or the language card |
| L4 | Level store units reach 47 KB. Annexes are 15.5 KB | Re-pack units to 15 KB, or stream the input through the far reader |
| L5 | B1 matches cross physical banks, so they go through the bounce buffer. 2 to 3 s per map is optimistic | Expect 4 to 6 s (estimate) |
| L6 | Colormaps in main `$2000-$5FFF` cost a one-off flush of about 16 ms per level if written by the CPU | Install them with amem PRIVATE |

## 4. Memory map check

| Region | Proposal | Status |
|---|---|---|
| Main zero page | 251 of 256 | Over-subscribed (M5) |
| Main `$0C00-$1BFF` | buffers and tables, 4 KB | Also needs 3.3 KB of row blocks (H5) |
| Main `$6000-$BFFF` | near 10, native 8, cache 4, stack 2 | Native needs about 155 KB (C1). Stack needs about 10 KB unless `LOGIC_SP` moves (H4). Tables of M6 and M7 unplaced |
| Main LC bank 1 | 4 KB | Needs 6 to 8 KB (H5) |
| Main LC `$E000` | far layer, interpreter core, IRQ, AY in 8 KB | Tight. A 65816 interpreter alone is 6 to 10 KB (assumption) |
| Aux `$A000` | fuzz tables and mailbox | Overlap (L1) |
| Aux LC, 16 KB | reserve | The only unused fast memory. Reachable only with ALTZP |
| RamWorks | 97 banks | 101 with `$0E-$0F` (M1). Usable space is 127 × 48,640 bytes = 6.2 MB, not 8 MB |

Reachability:

- Code in main `$6000-$BFFF` vanishes when RAMRD is on. Every far read must therefore run from the language card. The proposal respects this.
- Near-data reads from the interpreter are the case it misses (C2).

## 5. Emitted sequence check

| Mode | Proposal | Recomputed | Verdict |
|---|---:|---:|---|
| 16-bit immediate | 10 | 2+3+2+3 = 10 | Correct |
| Direct page | 12 | 3+3+3+3 = 12 | Correct |
| Absolute | 14 | 4+3+4+3 = 14 | Correct |
| Stack relative | 19 | 2+5+3+2+5+3 = 20 | Off by one |
| Indexed, fast home | about 40 | 38 | Correct |
| Gather row | 18 / 27 | 18 / 25 to 27 | Correct |
| Shade row | 13 | 4+5+4 = 13 | Correct |
| Write row | 9 | 4+5 = 9 | Correct |
| Far `[dp],y` | about 95 | about 135 | Low by 40 percent (H1) |

One omission: a far operand between `clc` and `adc` must preserve carry, since the far routine uses `adc` itself. That adds `php/plp`, 7 cycles and one stack byte.

## 6. amem check

| Use | Verdict |
|---|---|
| Install native images at boot | Valid for `$0200-$BFFF`. Language card images need CPU copies. The proposal knows this |
| `vmvn` of 1 KB or more | Valid. A request costs two exposure accesses, a hold and a cache clear. Do not use it below about 1 KB |
| View save for the menu | Valid: base aux source, extended destination |
| Page cache flush and preload | Valid. 16 pages fit one request of 16 descriptors |
| Overlay swaps | Valid but not sufficient (C1) |

## 7. Frame-time estimate, E1M1 idle

Assumptions:

- 400,000 source instructions per frame. This is the proposal's A3 and is unmeasured.
- Native 22 cycles at 50 M/s, so 0.44 µs. Interpreter 3.9 µs.
- 52,000 far accesses (13 percent).

| Phase | As specified: 8 KB native, about 50% of executed instructions | With section 8 fixes: about 90% native |
|---|---:|---:|
| Native instructions | 88 ms | 158 |
| Interpreted instructions | 780 | 120 (code page cache, 3.0 µs) |
| Far accesses | 312 (6 µs mixed) | 290 (5.5 µs) |
| Replay | 31 | 22 |
| Overlay swaps | 0 | 40 |
| IRQ and sound | 66 | 38 |
| **Total** | **about 1,280 ms, 0.8 FPS** | **about 670 ms, 1.5 FPS** |

- The range for the fixed design is 550 to 900 ms (1.1 to 1.8 FPS).
- The 50 percent coverage figure is my guess. M1's profile replaces it.
- The proposal's own columns, recomputed with the same costs: T0 about 2,080 ms (0.5 FPS), T1 about 770 ms (1.3 FPS).
- The existing port reaches 4 FPS because it is hand-batched. This design makes about 130,000 bus accesses per frame, which is about 195 ms on its own.

## 8. The three most important changes

1. **Put the native image in PSRAM banks and keep fast memory for the hottest 8 to 12 KB.** Native code run from a RamWorks bank costs about 1 to 2 µs per source instruction. That is slower than BRAM at 0.44 µs, and two to four times faster than the interpreter. It fits the 25 spare banks. The interpreter then leaves the frame path, which removes the largest line in the table. Give the interpreter a code page cache for what remains.

2. **Replace per-access far calls with sessions and object copies.** Copy each mobj, sector, node and seg into a fixed fast buffer once per visit. Build records in zero page and write each in one session. Move the record arena into the 16 KB aux language card, with the replay walker running under ALTZP. The target is fewer than 15,000 bus accesses per frame, down from 130,000.

3. **Rebuild the replay around the drain.** Merge shade and write. Skip bytes that already match the screen. Batch several columns per RAMWRT session. Budget 31 ms idle and 50 ms moving until M0 measures it. M0 should report bytes written, `$Cxxx` accesses and PSRAM misses, not only milliseconds.