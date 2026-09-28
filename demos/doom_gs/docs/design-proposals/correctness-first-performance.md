# Performance and hardware review: correctness-first proposal

**Path legend.** `F/` = `.../scratchpad/appletini-one-main/`, `U/` = `.../scratchpad/iigs-doom/`, `R/` = `.../scratchpad/research/`, all under `<scratch>`. Nothing was modified, simulated or run on hardware. My cycle counts are from 65C02 tables.

## 1. Verdict

The proposal's tier-2 figure of 0.37 s (2.7 FPS) is optimistic by about 25 to 60 percent. My estimate for E1M1 idle on current firmware is **about 0.47 s, 2.1 FPS** (range 0.42 to 0.60 s). Tier 0 is nearer 5 s than 2.8 s, and tier 1 nearer 1.4 s than 1.0 s.

Three things cause this:

- A far access costs about 7 µs, not 3.5 µs.
- The fast-memory map is over-subscribed and partly contradicts itself.
- The interpreter pays two soft-switch bus cycles per instruction fetch, which the proposal does not count.

## 2. Hardware costs recomputed

| Item | Proposal | Corrected | Source |
|---|---|---|---|
| One soft-switch or `$C073` access | 1.5 µs | about 1.4 µs; `STA $C073 / STA $C003 / read / STA $C002` is about 580 fabric clocks, 4.3 µs | `R/firmware/switches-plan.md` summary; `F/README_VIRTUAL_TRANSWARP.md:110,185` (cited in `R/appletini-hardware.md`) |
| TURBO cache re-warm after a mapping change | not costed | about 40 clocks, 0.3 µs, per change | same; invalidation at `F/hdl/apple/vtw_core_top.sv:1206-1211` |
| PSRAM line miss | 1 µs (A6) | about 131 clocks, 1.0 µs, clean line | `R/firmware/cache-plan.md` section 1 |
| PSRAM miss on a dirty line | not costed | write-back then fill, two admission windows, about 2 µs | `F/hdl/apple/vtw_core_top.sv:2054-2080`; one admission per Apple cycle, `F/hdl/apple/psram_simple.sv:28-33` |
| PSRAM line hit | not costed | 5 clocks, against 2 for BRAM | `R/firmware/cache-plan.md` section 1 |
| `$C073` write | 6 cycles, "0 or 1" accesses | a bus cycle, an exposure access (full mirror flush) and a cache invalidation | `vtw_core_top.sv:1390-1401` |
| RAMRD/RAMWRT writes | bus access | bus cycle; not an exposure access, but waits for active SHR bytes and flushes the posted queue | `vtw_core_top.sv:1414-1415`; `F/hdl/apple/vtw_bus_engine.sv:70-73` |
| CPU rate (A4) | 50 M cycles/s | 42 M measured on our port; I use 45 M | `R/existing-port.md` section 5 |

### One far access

| Step | Time |
|---|---:|
| Helper CPU work, about 100 to 120 cycles at 45 M/s | 2.2 to 2.7 µs |
| RAMRD or RAMWRT on and off, 2 bus cycles | 2.9 µs |
| `$C073` write when the bank changed | 1.4 µs |
| Cache re-warm | 0.3 µs |
| Line miss (a 16-bit read straddles two lines one time in eight) | 1.0 to 1.1 µs |
| **PSRAM, bank changed** | **about 7.8 µs** |
| **PSRAM, same bank** | **about 6.4 µs** |
| **Base aux (BRAM)** | **about 5.4 µs** |

The proposal's own table gives 120 cycles plus 2 to 3 accesses, which is already 5.4 to 6.9 µs before the miss. A5 (3.5 µs) contradicts it. The wish list calls 2 µs of it "CPU work", so A5 counts roughly one bus access.

## 3. Problems

| # | Severity | Problem | Corrected fact | Fix |
|---|---|---|---|---|
| 1 | High | A5 understates far access | 6.4 to 7.8 µs; section 6 far columns roughly double | Fuse sessions (one RAMRD window per thinker, node or record), cache the current bank, keep hot structures resident |
| 2 | High | Interpreter fetch is costed at a line miss only (0.6 s) | Code is in PSRAM and the virtual DP, stack and near data are in main, so each instruction toggles RAMRD: 2.9 µs plus about one miss, since data accesses evict the single line. Tier 0 is about 600,000 × 7 µs = 4.2 s plus 0.8 s far, 0.2 FPS | Software code-page cache: copy 256-byte code pages into fast RAM and interpret from there. The interpreter can then live in main RAM |
| 3 | High | Overlays do not fit their window | "Phase overlays of 40 KB or less" against a 16 KB code region (`$2000-$5FFF`); `$6000-$BFFF` (24 KB) is already given to data | Cut overlays to 16 KB or less, or give code `$2000-$7FFF` and move data to base aux |
| 4 | High | Render-phase data exceeds fast memory | Colormaps 17,408 bytes plus record home pages, 160 pages = 40,960 bytes (`U/src/iigs/lists.inc:1-13` via `R/iigs-renderer.md` 2.7), plus near pages and stack, against 24 KB | Leave records in PSRAM and write or read each in one session; keep only the colormaps resident |
| 5 | High | Near bank assumed resident | Bank `$02` is laid out over the full 64 KB: data `$0000-$7AFF`, BSS `$7B00-$FFFF` (`U/src/iigs/iigs.scm:87-90`). "About 20,000 sites at 14 cycles" holds only for hot pages. A non-resident static operand costs about 5 µs, equal to about 230 cycles. Assumption: used size is 40 to 60 KB; the link map will settle it | Report the resident fraction from the page-heat profile before quoting tier-1 numbers; relocate hot near variables into one contiguous resident block |
| 6 | High | Indexed modes costed as static | `abs,x` and `long,x` with 16-bit X cannot be resolved at build time through a per-page table. The 43-cycle sequence is valid only when the whole indexed object is contiguous and resident | Map objects, not pages; emit the fast form only for objects the planner pins; everything else uses the helper |
| 7 | High | Quarter-square multiplies are far accesses | `MULHI16` does four 16-bit `long:SQL/SQH,x` reads across banks `$13-$1A` (`U/src/iigs/r_seg65.s:191-238`): about 30 µs unfused, about 16 µs fused. A native 16×16 multiply with 8-bit tables in main is about 300 cycles, 6 to 7 µs, with no bus access. I counted 94 `SQL`/`SQH` operand lines in five files | Move intrinsic multiply and reciprocal from milestone 8 to the first translated build. Drop the 512 KB tables; the "prebuilt tables" item contradicts the intrinsics item |
| 8 | Medium | Main LC budget | Listed contents: interpreter (6 KB assumed; 8 to 10 KB is likelier for 256 opcodes with width variants), far layer, dispatcher, MVN helper, IRQ, drivers, amem transport, B1 decoder, gather kernel (about 1.8 KB). My sum is about 17 KB against 16 KB. Our current port has 16, 3 and 82 bytes free (`R/existing-port.md` section 2) | Only code that runs with RAMRD on needs LC. Fix 2 moves the interpreter out. Shade and fill blocks can run from main |
| 9 | Medium | Tables missing from the map | Return-site table 3,300 × 3 = 9.9 KB; page tables 6 × 512 = 3 KB; bank base table; host-PC map for checked builds | Place them explicitly. The return table must be readable with RAMRD off |
| 10 | Medium | Stack model contradicts paging | `(vSP),y` and "TCS adds a constant" need one contiguous block. "Virtual stack pages in use" implies page mapping. The stack section is 13.5 KB (`iigs.scm:32-33`) and the tic stack starts at `$1B6F` | Reserve one contiguous block sized from the measured depth, with a guard check in checked builds |
| 11 | Medium | Half-bank split at offset `$8000` | Lumps avoid 64 KB bank edges, not 32 KB edges. A texel column with up to 127 bytes of overread (`U/tools/levelimg.py:23-26`) can straddle two physical banks; so can a 16-bit read at `$7FFF` | Per-record boundary test in the gather kernel with a slow path; same test in `rd16` |
| 12 | Medium | amem descriptor limit | 16 descriptors per request (`F/README_MEMORY_API.md:107-111`). Page-granular residency gives many short runs. Every hold drains the mirror and invalidates caches (`README_MEMORY_API.md:190-192`) | Planner must produce 16 or fewer contiguous runs per phase |
| 13 | Medium | Swap volume | 30 ms implies about 80 KB per frame at the measured 2.7 MB/s (107 KB in 40 ms). Two code overlays plus dirty data out and in is nearer 120 to 150 KB, 45 to 55 ms | Keep read-only code resident across phases where possible; save only dirty ranges |
| 14 | Medium | Row-block switches per record | 6 bus accesses, about 8.6 µs, per record, and each `$C073` write forces a full flush | Batch gathers by texel bank across columns, as our port's 32-entry queue does (`K/src/render/rlc.s:63-88`) |
| 15 | Low | B1 decode and MVN | amem COPY rejects overlap (`README_MEMORY_API.md:165-167`); LZ matches often overlap, and offsets up to 32,768 cross half-banks | CPU loop with a bounce buffer; level load only, about 1 to 2 s |
| 16 | Low | Base aux BRAM left idle | Aux `$0200-$1E40` (7 KB), `$B600-$BFFF` (2.5 KB) and aux LC (16 KB) are unused or "reserved" | Use the low aux areas for read-mostly tables. Note aux `$0400-$0BFF` is a posted window (`vtw_bus_engine.sv:48-61`) |
| 17 | Low | IRQ during a far session | A handler touching main `$0200-$BFFF` with RAMRD or RAMWRT on hits the wrong bank | Keep IRQ state in ZP or LC, or save switches through `$C013/$C014`, which are served internally (`R/appletini-hardware.md` section 1) |
| 18 | Low | Direct 2D drawing adds SHR writes | The replay overwrites menu and overlay areas each frame and 2D redraws them; each byte costs about 1 µs of drain | Count these bytes in the profile; private buffer for menus |

Items that hold up:

- Immutable code and tables in main `$0400-$0BFF` and `$2000-$5FFF` are correct, and PRIVATE amem loads into them create no mirror traffic.
- The 256-byte host stack is sufficient for helpers.
- 116 of the 126 amem-reachable banks is feasible.
- The 27 ms replay figure is reasonable for idle.
- A1 (600,000 instructions) is probably an upper bound, since upstream's 4 FPS includes slow-bus stalls (`U/README.md:13-15`).

## 4. Emitted-sequence check

| Sequence | Proposal | My count |
|---|---:|---:|
| 16-bit load, resident | 14 | 14, or 23 with the flag tail |
| 16-bit ADC, resident | 20 | 20, or 29 with flags; 14 bytes, not 16 |
| Indexed, resident | 43 | 43, or 52 with flags |
| Push or pull helper | about 45 | about 45 |
| Return through `vm_ret` | not given | about 100 to 150 |
| Static weighted average, no elision, far helper excluded | 25 | 24.6 |
| Same, far helper CPU included | | 28.7 |

The 25-cycle average is right only with far accesses excluded, so their CPU time must sit in the far cost, which A5 omits.

## 5. Frame-time estimate, E1M1 idle, tier 2, current firmware

Assumptions: 45 M cycles/s; 22 cycles per translated instruction; far share 12 to 13 percent (static share of `[dp]` and `long:` in play and renderer files, `R/iigs-platform.md` section 6); 7 µs per far access, halved by fusion; intrinsic multiplies.

| Phase | CPU | Far and stalls | Total |
|---|---:|---:|---:|
| 4 game tics | 74 ms | 63 to 126 ms | about 150 ms |
| BSP and wall setup | 64 ms | about 50 ms | about 115 ms |
| Seg loop | 59 ms | about 9 ms | about 68 ms |
| Sprites, masked, weapon | 20 ms | about 25 ms | about 45 ms |
| Replay, native | 12 ms | 4 ms misses, 3 ms switches, 11 ms drain | about 30 ms |
| 2D and finish | 15 ms | 3 ms | about 18 ms |
| Overlay and data swaps | | | about 45 ms |
| **Total** | | | **about 470 ms, 2.1 FPS** |

| Tier | Proposal | Mine |
|---|---:|---:|
| 0 | 2.8 s | about 5 s |
| 1 | 1.0 s | about 1.4 s |
| 2 | 0.37 s | 0.42 to 0.60 s |

A moving view rewrites up to 26,880 bytes, adding about 16 ms of drain. Below 8.75 FPS the 4-tic cap slows game time (`R/existing-port.md` section 5).

## 6. The three most important changes

1. **Re-cost and redesign the far layer.** Use 7 µs per access, make fused sessions and bank caching part of the base design, and put intrinsic multiply and reciprocal in the first translated build.
2. **Fix the memory map before building the planner.** Size overlays to the code window, keep records in PSRAM, reserve a contiguous stack, place the return and page tables, and map by object so indexed modes can be resolved. Measure near-bank use from the link map.
3. **Interpret from a fast-RAM code-page cache.** This removes two bus cycles per interpreted instruction, relieves the LC, and makes tier 0 usable for the lockstep runs the plan depends on.