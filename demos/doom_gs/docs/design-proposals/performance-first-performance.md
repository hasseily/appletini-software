# Performance and hardware critique: "IIgs DOOM on the Appletini 65C02, optimised for frame rate"

Path legend: `[F]` = `<appletini-one>`, `[U]` = `.../scratchpad/iigs-doom`, `[R]` = `.../scratchpad/research`.

Nothing was assembled, run or simulated, and no repository or snapshot file was changed. Timings are recomputed from the RTL state machine and the READMEs. Items marked **(A)** are my assumptions.

## Verdict

- The unit costs in the proposal are mostly close to the hardware, within about 20%.
- The frame estimate is low because the counts are low, and because fast memory is given about 1.6 times more content than it can hold.
- Several items sit where the code that needs them cannot see them.
- My estimate for E1M1 idle is about 157 ms (6.4 FPS), with a range of 128 to 225 ms.

## 1. Unit costs recomputed from the RTL

One fabric clock is 7.5 ns (133.333 MHz). State sequences are my reading of `[F]hdl/apple/vtw_core_top.sv:1905-2123`.

| Item | Proposal | Recomputed | Basis |
|---|---|---|---|
| BRAM access, cache hit | not stated | 2 clocks, 15 ns | `X_CAPTURE`, `X_TURBO_DONE`; `[F]README_TURBO.md:59` |
| BRAM read, cache miss | not stated | 4 clocks, 30 ns | adds `X_MEM_CAPTURE`, `X_MEM_DONE` (`vtw_core_top.sv:1964-1972`, `:2114-2123`) |
| Classic cycle, loop inside the cache | 13 ns (low end) | 12.3 ns | 436 clocks for 266 classic cycles (1,064 / 4) (`README_TURBO.md:28-35`) |
| Classic cycle, translated straight-line code | 16 ns | 17-18 ns **(A)** | the word cache holds 32 words (`README_TURBO.md:53`); sequential code misses once per 4 bytes, so a fetched byte averages 2.5 clocks |
| PSRAM access, same line | 30 ns | 37.5 ns | 5 states: `X_CAPTURE`, `X_TURBO_DONE`, `X_ROUTE`, `X_RW_LOOKUP`, `X_RW_DONE` (`:2045-2053`) |
| PSRAM miss, clean / dirty | 1 / 2 us | 1 / 2 us | confirmed: one admission per bus cycle (`[F]hdl/apple/psram_simple.sv:232-239`); flush then fill (`vtw_core_top.sv:2054-2080`) |
| SHR store (`sta row,x`), CPU side | folded into cycles | 3 fetches plus 6 clocks (45 ns) | posted writes never take the fast-write path (`:1227-1228`); they go through `X_ROUTE` and `X_POST_STALL` |
| Soft-switch write that changes the mapping | 1.5 us | 1.5 us plus 0.3-0.5 us refill **(A)** | the change clears both caches (`:1206-1212`) |
| M-code far read | 4.5 us | about 5.2 us | two bus cycles, one miss, two cache clears |
| M-code far read with bank change | 6.2 us | about 7 us | `$C073` is also an exposure access that forces a full mirror flush (`:1390-1401`) |
| SHR drain | 0.9 us per byte | 0.9-1.0 us | one byte per Apple cycle (0.98 us); the 0.9 figure comes from coarse VBL samples (`[R]existing-port.md` §5) |
| amem | 0.33 us per byte | accepted | each hold first drains the pending mirror (`[F]README_MEMORY_API.md:190`), so a request issued after SHR writes also pays the drain |

Two facts the proposal does not use:

- A write of the same value to a soft switch does not clear the caches, because only a mapping change does. It still costs the bus cycle.
- `$C002-$C009` are not exposure accesses, but any `$Cxxx` access stalls while SHR bytes are pending (`vtw_core_top.sv:1414-1415`).

## 2. Problems

### 2.1 Fast memory is oversubscribed (critical)

Upstream's own linker script gives the size of the hot code, in 65816 bytes (`[U]src/iigs/iigs.scm`). These are region sizes, so they are upper bounds.

| Upstream hot region | Size |
|---|---|
| `segcode` `$032000-$033DFF` plus `segwalls` | 7.5 + 2.4 KB |
| `bspcode` `$034000-$035FFF` | 8 KB |
| `maskcode`, `core14`, `core16rows` | about 4 KB |
| Renderer record production, total | about 22 KB |
| Bank 0 `code` `$4000-$5FFF` (P_TryMove, P_CheckSight, P_RunThinkers) | 8 KB |
| `logiccode`, four regions | 23.5 KB |
| Game logic, total | about 31.5 KB |

The proposal's own size estimate implies a byte expansion of 1.7 to 2.0 (250-308 KB from about 150 KB).

| Need | Demand **(A)** | Space given |
|---|---|---|
| Renderer record-production code | about 35 KB | 24 KB (16 + 4 + 4 KB of X-code) |
| Seg column loops alone | about 12 KB | share of the 4 KB at `$8000` |
| Hot tic code | 12 KB idle, 40-60 KB in combat | 12 KB window plus 4 KB of X-code |
| Hot renderer data | about 20 KB | 13 KB, shared with game data |
| Hot game near data (states, mobjinfo, player, globals) | about 10 KB | the same 13 KB |

Renderer data, verified sizes:

- drawsegs are 128 x 42 = 5,376 bytes and openings are 2,560 x 2 = 5,120 bytes (`[U]src/iigs/r_state65.s:33-34`, `offsets.inc:38`, `:1008-1009`).
- vissprites are 3,360 bytes.
- FS and CV tables take 3 KB (`[U]src/iigs/memmap.inc`, `MM_FS`; `lists.inc`).
- Near data in total is about 53 KB by my count of data directives (cnear about 24.5 KB, znear about 28.7 KB). The count is rough.

Consequences:

- The translator table treats all 8,631 near operands as plain absolute accesses. Any near symbol placed in banks 7-8 becomes a 5 us far access instead.
- There is no region for overlays. Main `$0200-$BFFF` is fully allocated, so an overlay can only load into window W, which holds the records while rendering. Cold renderer code therefore cannot be loaded during a frame.
- The proposal does not say what happens on return into an overlay that has been replaced. A call from overlay A into overlay B and back costs two loads (about 1.6 ms each for 4 KB). Inside a per-thinker loop this is tens of ms per tic.

Fix: rotate main memory by phase (tics, BSP and walls, masked, replay), with records and stage outside the rotating region. Size each phase from a measured hot set, and count every rotation at 0.33 us per byte.

### 2.2 Items placed where the code cannot reach them

| Item | Problem | Severity | Fix |
|---|---|---|---|
| Quarter-square tables in main `$0400-$0BFF` | The SmartPort ROM entry writes `$07F8` under the caller's mapping (`README_MEMORY_API.md:68-72`). The runtime disk plan uses SmartPort block reads, so one table byte is corrupted at the first level load | High | Use the raw FIFO transport for block I/O, or keep the screen holes out of the tables |
| Multiply and reciprocal in LC, tables in main | With RAMRD on, main `$0400` is not visible. The reciprocal routine cannot read RECIP from PSRAM and the multiply tables in the same state | High | Read the table word into zero page, turn RAMRD off, then multiply; or put the 2 KB tables in the language card |
| Gather loop | It runs with RAMRD on, but the records it must read are in main window W | High | Build a gather list in zero page or LC during record production. Toggling per record costs 420 x 3 us = 1.3 ms |
| Replay shade with RAMWRT on | Any store to `$0200-$BFFF` lands in aux. Upstream's replay empties the lists and resets CV as it goes (`[R]iigs-renderer.md` §1 step 11, §2.8) | High | No main-memory stores in the shade pass; reset lists afterwards |
| Fuzz and overlay records | They read screen bytes back, which needs RAMRD on with bank 0, where records and stage are invisible | Medium | Replay them in the 2D machine state, in a separate pass |
| Colormap page fills by amem | The cache is in the aux language card, which is not an amem endpoint (`README_MEMORY_API.md:159-163`). The proposal lists both statements | Medium | CPU copy through a main bounce buffer, about 0.2 ms per page **(A)** |
| Patch staging in aux `$0200-$1FFF` | Aux `$0400-$0BFF` is a posted video window (`[F]hdl/apple/vtw_bus_engine.sv:55-56`). Writes there take the slow path and are flushed at the next `$C073` or `$C08x` access | Medium | Keep only write-once data (status-bar background) in aux `$0400-$0BFF` |
| Compiled HUD text code in aux LC | Upstream reserves 2 slots of 16 KB (`memmap.inc`, `MM_TEXTCODE`; `[U]src/iigs/patch65.s:280`) at 10 bytes per screen byte | Medium | Keep it in PSRAM and copy a slot in on use, or draw text with the patch drawer |
| Aux LC, 16 KB | Only 12 KB is visible at once; the `$D000` banks switch through `$C08x`, an exposure access. Row blocks, replay, fuzz, fills and 8 KB of colormaps do not fit one view | Medium | Put colormaps at `$E000` and split the `$D000` banks by record kind |
| Main LC kernel, 8 KB | It must hold stubs, gates, amem, IRQ, input, clock, multiply, reciprocal, gather, disk and sound. The existing, simpler kernel has 16, 3 and 82 bytes free (`[R]existing-port.md` §2) | Medium | Budget it line by line before freezing the map |
| Banks 20-24 | Three 64 KB tables split in halves need 6 banks of 48,640 bytes; 5 are given | Low | Split unevenly (48.6 + 15.4 KB) and select by compare, or add a bank |
| Window W reload | Tic code loaded from PSRAM every frame loses any variable stored in text. The proposal counts 203 such stores | Medium | Forbid text-resident state in rotated code; check at build |
| Records capped at 8 KB | Upstream allows 53,760 bytes. 420 texture records are already 4.6 KB; sprites and fills in combat will force early flushes | Medium | Give records 12-16 KB outside the rotating window |

### 2.3 Counts that are too low

| Item | Proposal | Corrected **(A)** | Reason |
|---|---|---|---|
| Expansion factor, 16-bit code | 2.2 | 2.5-3.0 | The proposal's own table gives 3x to 5x for `adc ##k`, `asl a`, `inx`, 16-bit transfers and general `abs,x`. X and Y are 16-bit almost everywhere (13 `sep #$10` sites) |
| Table reads | 1,500 at 2.5 us | 1,500 at 5.5-6 us | Each is a random word in another bank, read from M-code. The proposal's own far table gives 6.2 us |
| Node and seg fetches | 3.2 ms | about 7 ms | A seg also needs its side, line and two sectors (58 bytes each) in other banks |
| Column-pointer and FSTEP reads | 260 | about 520 | One column-table entry and one FSTEP word per textured column, in different banks |
| Thinker walk | 0.8 ms | 1.6 ms | Each visit touches about three lines and dirties one (`[U]src/iigs/p_tick65.s:143-170`) |
| 16-bit far loads | one visit | one visit, two bytes | The stub must read a word per session, or the cost doubles |
| Gather batches | 3 | 4 | 1,900 misses imply about 15 KB of texels against a 4 KB stage |
| Sound at under 3% | under 3% | 5-7% at 60 Hz | Each slot-4 access re-arms a 512-cycle 1 MHz window (`[R]appletini-hardware.md` §1) |

The 3.0 M cycle figure is not in the brief. It appears to be 250 ms at 12 MHz from the upstream README ("~4 FPS", `[U]README.md`). I kept it as an upper bound, since that frame time includes store stalls.

### 2.4 Stack

- The 256-byte stack holds return addresses and 16-bit data. Upstream callees save up to 12 bytes of `_Dp[8-19]` per level.
- A profile from demo input does not bound combat depth, and overflow wraps silently.
- Fix: a guard check in debug builds at every gate, and software frames for the whole play group rather than by profile.

### 2.5 Shade and drain

- The shade CPU cost per pixel is about 0.45 us, about half the drain rate, so the pass is bound by the drain. The proposal's 11.5 ms is consistent.
- Each batch boundary touches soft switches, so the CPU waits there for the rest of the drain. Gather time cannot overlap the drain.

## 3. Frame-time estimate, E1M1 idle

Assumptions: 3.0 M upstream cycles with the proposal's split; factor 2.7 for translated code; 17.5 ns per cycle for translated code and 16 ns for hand-written loops; 4 tics; 12,000 SHR bytes; hot data resident after the fix in 2.1.

| Phase | Proposal ms | My estimate ms | Main difference |
|---|---|---|---|
| Tics x4 | 24.6 | 37.4 | CPU 18.9; walk 1.6; far 6.2; window 4.3; overlay reloads 6.4 |
| Frame setup, BSP, wall setup | 39.0 | 58.0 | CPU 42.5; map fetches 7; tables 8.6 |
| Seg loops and records | 13.7 | 16.6 | CPU 13.4; far 3.2 |
| Sprites, masked, weapon | 11.0 | 14.7 | CPU 13.1; far 1.6 |
| Gather | 5.1 | 7.7 | CPU 4.1; misses 2.3; record access 1.0; line hits 0.3 |
| Shade and store | 11.5 | 12.0 | drain-bound |
| 2D, colours, finish | 5.3 | 7.8 | CPU 7.1; SHR 0.7 |
| IRQ, input, sound (silent) | 3.5 | 2.5 | |
| **Total** | **114** | **about 157 (6.4 FPS)** | |

| Case | Frame | FPS |
|---|---|---|
| Factor 2.2, 16 ns, no overlay reloads | about 128 ms | 7.8 |
| Nominal | about 157 ms | 6.4 |
| Factor 3.0, 20 ns, part of near data in PSRAM, one extra rotation | about 225 ms | 4.4 |

Above 114 ms the 4-tic cap is saturated, so game time runs slow in all three cases.

## 4. The three most important changes

1. **Redo the fast-memory budget as a phase rotation.** Measure the hot code and data of each phase, give drawsegs, openings, vissprites, states and mobjinfo explicit fast homes, move records and stage out of the rotating region, and define overlay return. Count every rotation in the frame estimate.
2. **Replace per-access far reads with object copies and fix the visibility conflicts.** Copy a whole node, seg, sector or mobj into a fast buffer in one RAMRD session and write back if dirty; this breaks even at about six accesses. Resolve the items in 2.2 (multiply tables, gather list, replay stores, `$07F8`) before any code is written.
3. **Measure before freezing, and plan on factor 2.7.** Take per-phase cycle counts from the release image in GSSquared instead of the 3.0 M assumption. Extend milestone 0 to measure translated-style code that overflows the 32-word cache, the PSRAM line hit, and the far-read sequence. Hand-port the 8 KB of `bspcode` hot paths if the measured factor exceeds 2.5.