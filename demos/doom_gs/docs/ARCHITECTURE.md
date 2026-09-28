# Architecture: IIgs DOOM on the Appletini 65C02 ("V816")

**Path legend.** `U/` = `<upstream>/`. `F/` = `.../scratchpad/appletini-one-main/`. `R/` = `.../scratchpad/research/`. `REL` = `.../scratchpad/release/doom-hd.hdv`. `K/` = `<appletini-software>/demos/doom/`.

**Evidence labels.** "Verified" means I opened the line or ran the grep or parse in this session. "Reported" means a proposal or critic measured it and I did not repeat it. "Assumption" is unverified. Nothing was assembled or run on hardware. No file was created, modified or deleted.

**Base.** I start from the correctness-first proposal (virtual 65816 machine, interpreter first, lockstep). It is the only one whose blockers are all repairable without changing its premise. I graft the incremental proposal's build pipeline, overrides and early hardware replay, and the performance proposal's cost discipline, exact multiply, batched replay and hardware microbenchmarks.

## 0. Facts settled from the source

| Disputed point | Result | Evidence (verified) |
|---|---|---|
| Macro count: 104, 105 or 131 | 131 `.macro` lines in 31 files. The lower figures probably exclude `.inc` files or variants. The image match decides. | grep over `U/src/iigs/*.s *.inc` |
| Is a system `cpp` safe with `##`? | Token paste is used once, in a `#define` body. `##` operands elsewhere must be left alone. Our own preprocessor is primary; `clang -E` is a cross-check. | `U/src/iigs/r_seg65.s:602` |
| Return-frame edits: 1 or 3 | Four sites: three discards and one return-address rewrite. | `p_path65.s:1089-1092`, `w_level65.s:1444-1448`, `m_menu65.s:2454-2457`, `r_bsp65.s:1309-1311` (called at `:264`) |
| Private tic stack: droppable? | It is a nested switch, not a coroutine, and exists for cache-slot reasons. `LOGIC_SP` can be moved; it cannot be deleted, because S is read as data. | `p_think65.s:177-183, 193-212, 293-301`; `p_map65.s:342-346` |
| `sep #0x10` sites | 11 source lines: 4 in `loader.s`, 7 in `r_list65.s`. | grep |
| `rep`/`sep` operands | Constants only: `#0x20`, `#0x30`, `#0x10`, `#0x21` (7), `#0x40` (2), `#0x38` (1). No `sed`, `wai`, `mvp` mnemonic. | grep, comments stripped |
| `tcd` / `tdc` / `tcs` / `tsc` | 23 / 3 / 23 / 31 source lines, including `cal_integer.s` and the loader. 9 `tcd`/`tdc` lines are in `p_trace65.s`. | grep |
| D as a data register | Confirmed. | `p_trace65.s:430-431, 500-502` |
| Hand-assembled opcodes | `.byte` lines starting `0x54` 33, `0x44` 2, `0x5c` 31, `0x6c` 8, `0xdc` 8, `0x82` 41, `0x80` 11, `0x4c` 53, `0x20` 15, `0x22` 2, `0x60` 2. Many are patch payloads, not instructions. | grep |
| Patched branch displacement | Confirmed: `ptT1: .byte 0x80, 6, …` and the patcher. | `p_trace65.s:1681, 1847-1866` |
| Opcode select per seg | Confirmed: `c17Return .equ .` then `.byte 0x60, 0, .byte1 (drawMid+7)`. The site is an equate, not a label. | `r_seg65.s:1936-1939` |
| Computed opcode | Confirmed: `and #0x20 / ora #0x10` stored to four branch sites. | `r_thing65.s:1307-1319` |
| Code templates indexed by byte size | Confirmed: `6 * (GB.hi + 2)` indexes `k3Tpl`. | `r_thing65.s:1105-1121` |
| Pointer patcher | Confirmed: `sta [.tiny (_Dp+4)],y` with the site from `ssSites`. | `r_seg65.s:1035-1052` |
| 16-bit `dex / bpl` | Confirmed at `fsFill`. N must come from the high byte. | `r_list65.s:189-192` |
| Carry live across a far read | Confirmed. | `p_inter65.s:118-122` |
| `qmulh` is not the exact high word | Confirmed: "the high word … or 1 more". | `r_wall65.s:1781-1785` |
| Level window size | `MM_WINDOW $2A` to `MM_WINDOW_END $40` is 22 banks. E1M3 needs 22.97 to 23.48, so `$0E-$0F` must be mapped too. | `memmap.inc:131-132`; `iigs.scm:22`; `w_level65.s:527-529` |
| "Byte for byte" rebuild | The comment is at `U/Makefile:153-154`. | read |
| Release image | 28 segments, entry `$03:0000`. Code segments total 187,904 bytes (17,920 in bank `$00`, 169,984 in `$03-$05`). Near initialised data is 30,208 bytes. Level store is 1,821,696 bytes at `$40:0000`. | header parse of `REL` block 1 |
| PSRAM line hit in TURBO | 5 fabric clocks, not 4. | `R/firmware/cache-plan.md` section 2; `F/hdl/apple/vtw_core_top.sv:2045-2052` |
| `$C073` write | It is an exposure access and forces a full mirror flush. RAMRD/RAMWRT writes are not, but still wait on pending SHR bytes. | `vtw_core_top.sv:1390-1401, 1414-1415` |
| TURBO invalidation | Any mapping change clears both caches. | `vtw_core_top.sv:1206-1211` |
| amem limits | 1 to 16 descriptors; endpoints `$0200` to `$C000`; overlap rejected; SmartPort ROM entry writes `$07F8`. | `F/README_MEMORY_API.md:68-73, 107-112, 159-169` |

Counts of `php`/`plp` differ between greps (23 to 66 `php`). The front end will give the authoritative number.

## 1. Architecture summary

The port is a virtual 65816 machine on the 65C02. The 24-bit address space, the 16-bit stack, D, DBR and every code address keep their upstream values. Only physical placement is ours.

- **Two builds from one front end.** Our assembler builds the pristine upstream image, which must equal the release bytes. It also builds the port image, with overrides applied.
- **Tier 0, interpreter.** A 65816 interpreter in the main language card runs the port image. It fetches code through a fast-RAM code-page cache. It handles cold code and anything with unclassified self-modification.
- **Tier 1, translated regions.** Basic-block regions with registered entries become 65C02 code. Every emitted assumption is statically proven or guarded. Profiles choose only what to translate and where to place it.
- **Tier 2, hand-written kernels.** Record replay, multiply and divide, MVN, B1 decoder, patch drawer and platform code. Seg column loops and thinker walk follow later.
- **Code runs only from BRAM.** Main memory rotates by phase (tics, render, replay, UI). Immutable code and tables are loaded with amem.
- **Far layer.** One API, three paths: direct access, fused sessions, and a software line cache for structured data.
- **Verification.** A host 65816 core runs the same image in lockstep with a host model of the Appletini.

Expected E1M1 idle speed on today's firmware is 2.4 FPS nominal, with a range of 1.4 to 4.2. About 3 FPS is likely after the later kernels.

## 2. Translator design

### 2.1 Front end

| Stage | Design |
|---|---|
| Fetch | Clone upstream at `8ea2eac` into `build/upstream`, following `K/../bilestoad/build.py`. Nothing from upstream is committed. |
| Preprocessor | Own Python implementation of `#include`, `#define`, `#undef`, `#if`, with token paste inside `#define` bodies only. Flags `-D TICSTEP=1 -D MUSIC_MENU=1` (`U/Makefile:23, 82`). |
| Macros | `.macro/.endm` with `\arg` substitution. Each expansion has its own `N$` scope (`R/calypsi-assembler-chapter.txt`, section 21.11.2). |
| Labels | `N$` locals reset at each non-local label. `X .equ .` is a code position and is tracked as one. |
| Expressions | `.byte0-2`, `.word0/2`, `.tiny`, `.near`, `.kbank`, `.sectionStart/End/Size`. |
| `.byte` in text | Runs are disassembled. A run is an instruction only if the decode is consistent and the site is reached by control flow. The rest is data or patch payload. |
| Sections | Placement read from `U/src/iigs/iigs.scm`. The port build uses our placement for bank `$02` (section 3.3). |
| Overrides | `port/overrides.json`: label range or macro, content hash, replacement, register and memory contract. The hash makes an upstream change a build error. |
| Proof | The pristine build must equal the release code and data segments. Fragment matching with operand wildcards isolates mismatches and recovers the link map. |

### 2.2 M/X, D and DBR inference

- **M and X.** Forward data-flow over the control-flow graph, interprocedural, with lattice {8, 16, either}. Immediates are ground truth. `php`/`plp` pairs are matched on all paths. "Either" at a width-dependent instruction is a build error for that region, which then stays interpreted.
- **Reported prototype result.** 64,965 of 67,235 expanded instructions have M known; 68 conflicts. Expect 50 to 100 annotations.
- **D.** Same lattice, with values `$0900`, `$0A00`, `$0000`, `$8D00` and "data". A function with dp operands reached under two D values is cloned (`r_list65.s:272-276` documents `newPage` as "any direct page"). A dp operand while D is "data" or "either" is a build error.
- **DBR.** A live virtual register, `vDBR`. A constant bank is used only where data-flow proves it. About 29 sites set DBR dynamically (reported).
- **Transfers.** `tsc`, `tcs`, `tcd` and `tdc` always move 16 bits. `tax`/`tay` with X=0 copy all 16 bits of B:A even when M=1.
- **Cross-checks.** Static results are compared with the values observed per PC in the reference run. Checked builds assert them at run time.

### 2.3 Register and flag model

| 65816 | 65C02 home |
|---|---|
| A and B | Zero-page word `vA`. Inside a block with M=1, the emitter may cache A in host A and write it back at block end. |
| X, Y | Zero-page words `vX`, `vY`. Host X and Y are scratch and index carriers. |
| S | `vS`, a physical pointer into the soft stack. |
| D, DBR | `vD` (word), `vDBR` (byte). Static where proven. |
| PBR | Static per site. |
| C, V, N, Z, I | Host P at every registered entry, call, return and helper boundary. |
| M, X flags | Static. Entry records carry them. `php` composes the pushed byte from host flags and static M/X; `plp` restores all of it. |

Flag rules inside a region:

- The high byte is processed last for add, subtract and compare, so C, V and N are right. Right shifts process the high byte first and take N from it explicitly.
- Z over 16 bits is materialised only where liveness needs it. When N and Z are both live the sequence is `lda hi / bne + / lda lo / beq + / lda #1`.
- 16-bit `inc`, `dec`, `inx`, `dex` and the like emit full N and Z whenever either is live.
- `cmp` is built from `cmp` (low) and `sbc` (high), with V saved around it when V is live. 65816 `cmp` does not change V.
- Address arithmetic never uses `adc` without saving C. It uses `inc`-based or table-based formation, or `php`/`plp`.
- Stores, pushes and far helpers preserve N, Z, C and V. Far reads return N and Z of the full value.
- `rep #0x21` emits `clc`. `sep #0x40` emits `bit` on a constant `$40` byte. `sep #0x10` zeroes the high bytes of X and Y.
- All flags are live at every `rts`, `rtl` and registered entry unless all callers are known. C and V are return values upstream (`p_floor65.s:789-792`, reported).
- Virtual `sei`, `cli` and the I bit of `plp` map to the host I flag.

### 2.4 Addressing modes and emitted code

M=0, `lda` as the example. Cycles are 65C02 table values. The flag tail is extra where live.

| Mode (static sites, from the brief) | Emitted 65C02 | Bytes | Cycles |
|---|---|---:|---:|
| 16-bit immediate (8,151) | `lda #lo / sta vA / lda #hi / sta vA+1` | 8 | 10 |
| 8-bit immediate (2,197) | `lda #v` | 2 | 2 |
| Direct page, D known (6,279) | `lda abs / sta vA / lda abs+1 / sta vA+1` | 10 | 14 |
| `.near`, object in the resident extent (part of 8,314) | same | 10 | 14 |
| `.near`, object in the cold extent | `jsr fs_rd16` + 3 address bytes | 6 | far cost |
| `.near,x` / `long,x` / `abs,x`, base proven inside one resident object | 16-bit add into `fp` under saved C, then `(fp)` and `(fp),y` | 23 | about 40 |
| Any other indexed operand | `jsr fx_rd16` with run-time translation | 5 | 60 to far cost |
| `long:` static, far home (3,068) | `jsr fs_rd16` + 3 address bytes | 6 | far cost |
| `[dp],y` (2,620), `[dp]` (252) | `jsr fp_rd16y` + cell byte; full 16-bit Y added | 4 | far cost |
| Stack relative (316) | `ldy #n / lda (vS),y / sta vA / iny / lda (vS),y / sta vA+1` | 12 | 20 |
| Implied (14,775) | `asl vA / rol vA+1`; `inc vX / bne / inc vX+1` | 4 to 8 | 7 to 12 |
| `xba` (620) | swap `vA` and `vA+1` | 8 | 12 |
| `rep`/`sep` | nothing, or the flag effect | 0 to 3 | 0 to 3 |
| Short branch out of range | relaxed to `b?? +3 / jmp`; patched branches are exempt and pinned | 5 | 3 to 6 |

Weighted cost is 15 to 24 cycles and about 7.5 to 10 bytes per source instruction (assumption, from the three proposals' tables and the critics' corrections). I use 18 cycles and 8.5 bytes as nominal.

A **compact emission mode** serves warm code: 16-bit operations become helper calls, at about 4 bytes and 40 cycles per instruction. It is five times faster than the interpreter at about 1.5 times the 65816 size. The planner picks the mode per region.

### 2.5 Stack, calls and returns

- **Soft stack.** `vS` tracks S byte for byte. Frame sizes, `n,s` offsets and `tsc`/`adc`/`tcs` arithmetic are unchanged, including the constants that hard-code 3-byte JSL frames (`p_map65.s:105`, reported).
- **Code addresses are original addresses.** Return addresses, function pointers, jump tables and vectors hold the upstream 24-bit or 16-bit value. There are no tokens.
- **Entry table.** One table maps original address to native entry, with M, X, D and DBR expectations. `vm_dispatch`, `vm_ret` and the interpreter share it. A miss, or a mismatch of dynamic M/X/D, continues in the interpreter.

Two call disciplines, chosen per function by static analysis:

| Discipline | Used for | Mechanism | Cost |
|---|---|---|---|
| H (host) | Default | Lower `vS` by 2 or 3, host `jsr`. The return raises `vS`, host `rts`. Checked builds write the real return address into the hole so memory equals the reference. | about 17 cycles per call and per return |
| S (soft) | Functions that discard or rewrite a return address, their affected callers, every recursive call-graph cycle, every target reached from the interpreter | Push the real original return address. Return through `vm_ret` and the entry table. | 100 to 150 cycles |

- The four sites in section 0 force S. So do `bspNode` and `recursiveSound` (`p_pspr65.s:451`), which recurse.
- The build fails on any `tcs`, or any `sta n,s` that reaches a return slot, that is not classified.
- Host stack use is bounded by the static call graph of H functions. Checked builds guard it.

**Tier boundary thunks.** One entry thunk and one exit thunk. They write `vD`, `vDBR`, P and the canonical register homes. A native caller of an interpreted callee pushes the real return address, which is a registered entry. The interpreter is re-entrant to a capped depth.

### 2.6 Function pointers, jump tables, MVN

| Construct | Sites | Handling |
|---|---:|---|
| `JML [dp]` as `.byte 0xdc` | 8 | `vm_dispatch` on the stored original address |
| `jmp (abs)` | 15 lines, 14 of them `jmp (abs:SVEC)` in `p_sight65.s` | Vector read from bank 0, which reaches the direct page. Targets are the `##.word0 label` immediates; each is a registered entry |
| `jmp (abs,x)` / `jsr (abs,x)` | 16 / 12 lines | Vector read from the site's static program bank. Table kept in original addresses; dispatch through the entry table, or a native table when all targets are native |
| MVN | 33 `.byte 0x54` lines, 2 `0x44` | `vmvn` helper with the full contract: final X, Y, A = `$FFFF`, DBR = destination. Forward byte order for overlap. Splits at mapping boundaries. Uses amem COPY above about 1 KB between legal, non-overlapping endpoints outside visible SHR |
| Label plus offset targets | `drawMid+7` and similar | Registered entries at the exact byte address |

### 2.7 Self-modifying code

Rule: the 65816 image is real memory. Patchers write to it. The interpreter therefore always sees correct code.

**Patch catalogue**, built from three sources:

1. Static stores whose operand resolves into a text section, including `.equ .` sites.
2. Patch tables parsed at build time (`ssSites`, the one-view table, `hvT`, `c17Next`, `ptPatch` sources).
3. The reference run's log of every write to a byte that is later executed, over scripts that change view size, detail and start the benchmark.

| Class | Example | Native handling |
|---|---|---|
| Operand cell | `c26Lookup+1`; `wRdY+1`, also read back at `p_path65.s:1128` | Operand becomes a data cell. Every reader and writer is rewritten |
| Branch select | `ptT1` (`p_trace65.s:1681`) | Cell plus dispatch over the values listed in the source table |
| Opcode select | `c17Return`; `c12Signs` (`$10` or `$30`) | Cell plus dispatch over the enumerated opcodes |
| Template or code install | `k3Tpl`, `c16Mode`, `hvSet`, MVN-installed kernels | Interpreted first. Later a selector over pre-translated variants |
| Generated code | `IIGS_TextCode` (`patch65.s:279-381`) | Overridden: `I_DrawCachedText` always reports no cache, so text is drawn by the patch drawer |
| Row blocks and replay | `r_list65.s`, `gendraw.py` output | Hand-written replacement (section 4) |

**Fail closed.** A region with an uncatalogued patch site is not translated. A write-watch bitmap covers the code image. Any far write into a watched page updates the matching cell, or removes the region's entries so execution falls back to the interpreter.

### 2.8 Constructs that are not mechanical

| Construct | Sites | Replacement |
|---|---:|---|
| `xce` firmware wrappers | 12 lines | Kernel disk code |
| IIgs I/O registers | 206 uses of 27 addresses outside boot and loader (reported) | Platform overrides |
| Quarter-square multiplies | 94 to 112 references (reported) | Intrinsics; macro-level override, routine-level where carry chains cross the macro (`am_map65.s:2305-2309`, reported) |
| `qmulh` | 14 references (reported) | Intrinsic returning high(P) plus the carry of low(sq(d)) + low(P) |
| `cal_integer.s` | about 46 to 50 call sites | Our own routines. The file is never assembled or shipped |
| ZipGS and TransWarp GS code | `m_menu65.s`, `iigs_asm.s` | Stubbed |
| Boot, loader, crt0, IRQ, DOC, ADB | about 5,000 instruction lines | Platform layer |

## 3. Memory model

### 3.1 Principles

- Code executes only from BRAM: main RAM, main LC, or aux LC.
- The mirrored windows main `$0400-$0BFF` and `$2000-$5FFF` hold immutable content only.
- Every virtual region has one linear mapping per extent. No object is split across extents.
- The interrupt handler touches only the language card and its own cells.

### 3.2 Fast memory map (initial; the planner fixes addresses at milestone 5)

| Region | Size | Contents |
|---|---:|---|
| Main `$00-$FF` | 256 B | VM registers 16, far pointers 12, interpreter scratch 16, kernel and IRQ 16, replay state 48. `$42-$47` free for the block driver |
| Main `$0100-$01FF` | 256 B | Host stack |
| Main `$0200-$03FF` | 512 B | amem request buffer (266 B), kernel variables |
| Main `$0400-$0BFF` | 2 KB | Immutable: row-address tables, colormap page-address table, entry-table index. `$07F8` left unused |
| Main `$0C00-$13FF` | 2 KB | 8-bit quarter-square tables for the multiply intrinsics |
| Main `$1400-$15FF` | 512 B | Virtual `$00:0900` and WPAGE `$00:0A00`, as whole linear pages |
| Main `$1600-$1FFF` | 2.5 KB | Patch cells, write-watch bitmap, line-cache tags, near core part 1 |
| Main `$2000-$5FFF` | 16 KB | Phase window 1, immutable, loaded with amem PRIVATE |
| Main `$6000-$6FFF` | 4 KB | Soft stack, virtual `$00:3000-$3FFF`; `LOGIC_SP` overridden to `$37FF` (assumption on depth; measured at milestone 2) |
| Main `$7000-$7FFF` | 4 KB | Software line cache: 64 lines of 64 bytes |
| Main `$8000-$87FF` | 2 KB | Near core part 2: always-resident writable near data |
| Main `$8800-$BFFF` | 14 KB | Phase window 2 |
| Main LC `$E000-$FFFF` | 8 KB | Far layer 1.2, dispatcher and thunks 1.0, IRQ, clock, input 0.8, amem transport 0.5, `vmvn` 0.5, interpreter core 4.0 |
| Main LC `$D000` bank 1 | 4 KB | Interpreter opcode handlers |
| Main LC `$D000` bank 2 | 4 KB | Replay record reader and gather kernel 2.5, B1 decoder, disk, crash screen 1.5 |
| Aux `$0200-$03FF`, `$0C00-$1E40` | 5 KB | `TEXLO/TEXHI` equivalents, patch staging. Aux `$0400-$0BFF` is a posted window and holds write-once data only |
| Aux `$2000-$9FFF` | 32 KB | SHR pixels, SCBs, palettes. This is virtual bank `$01` and `$E1` |
| Aux `$A000-$B5FF` | 5.5 KB | `FUZZ_DARKEN`, `FUZZ_DIR`, `STCACHE`, at their upstream addresses |
| Aux `$B600-$BFFF` | 2.5 KB | Profiling mailbox (moved from `$A000`), spare |
| Aux LC, 12 KB visible | 7.5 KB used | Shade and fill row blocks 2.0, fuzz blocks 1.7, shade walker 2.0, patch drawer 1.5, IRQ mirror 0.3 |

Phase windows:

| Phase | Window 1 (16 KB, immutable) | Window 2 (14 KB) | amem load |
|---|---|---|---:|
| Tics | Tic code | States and mobjinfo (8 KB, immutable), more tic code | about 30 KB, 10 ms |
| Render | BSP, wall and sprite code | Render scratch: drawsegs 5,376, openings 5,120, vissprites 3,360, clips 640. Rebuilt each frame, so never loaded or saved | 16 KB, 5.3 ms |
| Replay | 64 colormap pages | 4 colormap pages, texel stage 4 KB, worklist 8 KB | 17.4 KB, 5.7 ms |
| UI and 2D | Status bar, HUD, menu code | More UI code | up to 30 KB, only when UI runs |

Each phase load is one amem request with at most 16 descriptors. All loaded content is immutable, so nothing is saved. State stored in text is forbidden in rotated code and checked at build.

### 3.3 Virtual to physical

| Virtual | Physical |
|---|---|
| `$00:0900-$0AFF` | Main `$1400-$15FF`, constant offset |
| `$00:3000-$3FFF` | Main `$6000-$6FFF`, constant offset. Below `$3000` traps |
| `$00` other | Code image and variables, in RamWorks |
| `$01` and `$E1` | Base aux, identity. `$E0` traps |
| `$02` hot extent `[0, H)` | Near core, always resident |
| `$02` render extent | Window 2 during render; far-mapped in other phases; poisoned in checked builds |
| `$02` table extent | States and mobjinfo; window 2 during tics, far otherwise |
| `$02` cold extent | Two RamWorks banks |
| `$03-$05` | 65816 image, 6 granules |
| `$06-$0D` | Zone, tables, far BSS, 16 granules |
| `$0E-$0F`, `$2A-$3F` | Level window, 48 granules |
| `$10-$12` | Resident WAD, 6 |
| `$13-$1A`, `$27-$29` | Not mapped (quarter squares, DOC sound) |
| `$1B-$26` | Step, records, reciprocal, log, sine, misc, 24 |

- **Granule rule.** One virtual 32 KB half-bank maps to `$4000-$BFFF` of one RamWorks bank. `phys_bank = MAP[2*vbank + bit15]`, `phys_hi = (hi & $7F) + $40`.
- **Bank count.** About 104 banks of 126 usable by amem. The 22 spare banks plus 104 annexes (`$0200-$3FFF`, 15,872 bytes each) give about 2.7 MB. They hold the level store (1.82 MB) and the translated code images (assumption: 0.4 to 0.5 MB).
- **Near bank.** The port build lays out bank `$02` itself: hot fragments first, then render scratch, then tables, then cold. Source order inside a fragment is kept. Run-time translation of a bank `$02` address is a range compare.
- **Straddles.** A 16-bit access whose low address byte is `$FF` takes a per-byte path. The host model asserts that no far helper touches `$C000-$CFFF`.
- **Texel over-read.** The gather kernel tests whether a column's base lies within 128 bytes of a granule end and uses a slow path there.

### 3.4 Far access

| Path | Used for | CPU cycles | `$Cxxx` accesses | Time |
|---|---|---:|---:|---|
| F0 direct | Random table reads, texel pointers | 70 (static) to 135 (`[dp],y`) | 2, plus 1 on bank change | 5.4 µs base aux, 6.4 µs same bank, 7.8 µs bank change |
| F1 fused session | Runs of stores or loads to one bank in one block; record writes | about 15 per access | 3 per session | 4.3 µs per session plus about 1 µs per line touched |
| F2 line cache, hit | Zone, nodes, segs, sectors, lines | about 50 | 0 | about 1.1 µs |
| F2 miss | | about 900 | 3 | 25 to 35 µs; up to 60 µs with a dirty victim |

- Order of bank updates: write the shadow, then `$C073`. The IRQ handler restores from the shadow.
- F1 write sessions run from main RAM with RAMWRT on. They may write only zero page. Read sessions run only in language-card kernels.
- F2 coherence: dirty lines of a bank are flushed before the replay, `vmvn`, amem, or any hand-written kernel touches that bank. Records and texel banks never use F2.
- F2 breaks even at about five accesses per line visit. It is built only if the milestone 3 cost model shows a gain.

### 3.5 Translated code size and placement

- 187,904 bytes of 65816 program (verified). At about 2.7 bytes per 65816 instruction and 8.5 bytes emitted, a full native build is about 590 KB (assumption). It cannot be resident.
- Upstream hot regions total about 58 KB if full (`iigs.scm:34, 114, 118, 127, 132, 142, 161, 166, 179, 191`, verified as region sizes). Translated, that is up to 155 KB.
- The windows hold about 30 KB per phase, which is about 3,500 source instructions.
- Placement classes: **resident** in the phase window; **warm**, a 4 KB on-demand overlay in window 2 with a gate, about 1.6 ms per load; **cold**, interpreted.
- The share of executed instructions covered by resident code is the main unknown. I assume 97 percent on E1M1 idle. Milestone 2 measures it.

### 3.6 amem use

| Use | When |
|---|---|
| Phase window loads | 3 per frame, 4 with UI |
| Warm overlay loads | On demand |
| Colormap install per level | Level start, PRIVATE |
| `vmvn` above about 1 KB, view save for the menu | As needed |
| Level load copies, boot install of main images | Level start, boot |
| Never | Visible SHR, zero page, stack, language card, bank 127 |

## 4. Renderer and presentation

**Kept from upstream.** Record kinds and layout in virtual bank `$1D` (`lists.inc:1-60`, verified), fill spans, covered ranges, weapon skip, the two 34-page colormaps, per-row blocks with computed entry and patched exit, and even/odd row pairing.

**Record production.** Translated code at first. Each record is built and written in one F1 session. Later the 13 seg column loops (`segvar.inc`) are hand-written.

**Replay, per batch of columns:**

| Pass | Switch state | Code | Work |
|---|---|---|---|
| R, read | RAMRD on, `$C073` = record bank | Main LC | Copy the used bytes of each column's list into the fast worklist. Writes go to main because RAMWRT is off |
| G, gather | RAMRD on, `$C073` = texel bank | Main LC | For each texture record, step and copy its texels into a slice of the stage. Grouped by bank; order is free because nothing is painted |
| S, shade and store | ALTZP on, RAMWRT on, `$C073` = 0 | Aux LC | In list order: fills `sta row,x`; texture rows `ldy #r / lda (TS),y / tay / lda (CM),y / sta row,x`, about 19 cycles |
| F, fuzz and overlay | RAMRD and RAMWRT on, `$C073` = 0 | Aux LC | Parameters copied to aux zero page first; reads the screen |

- A batch ends when the stage or worklist is full. E1M1 idle needs about 4 batches (assumption).
- Paint order and covered ranges are respected in pass S only.
- Pass S stores nothing to main memory. List resets happen afterwards.
- The list-reset and `COLW` bookkeeping in bank `$1D` is done in one session after the last batch.

**SHR bytes per frame.**

| Case | Bytes | Drain at about 0.98 µs per byte |
|---|---:|---:|
| Worst case view | 26,880 | 26 ms |
| E1M1 idle (assumption: fills reused) | 12,000 to 13,000 | 12 to 13 ms |
| SCBs and one tint row | 584 | 0.6 ms |
| Status bar, HUD | dirty bytes only | under 1 ms |

The replay costs 28 to 35 ms idle and 45 to 55 ms moving. Drain and CPU work overlap only inside pass S.

**2D.** Virtual bank `$01` is the screen. `markRect` and `showDirty` become empty overrides. `IIGS_DrawPatch` is replaced by a hand-written drawer that stages patch data into a language-card buffer, then does the read-mask-write in one aux session per patch. Menus and overlays that overlap the view get a private buffer if the frame-end comparison or a visual check shows flicker. Full-screen pictures black the palette before drawing, as upstream does (`i_viigs65.s:306-345`, reported).

**Tearing.** The replay is not synchronised, as upstream. A 30 ms replay spans two PAL fields, so a seam shows for two or three displayed frames. No wait is inserted by default.

**To confirm at milestone 0.** Standard 320 mode with per-row SCB palettes. Our Doom port uses PAL256 only.

## 5. Platform layer

| Area | Plan |
|---|---|
| Boot | ProDOS `DOOM.SYSTEM` from `K/src/kernel/loader.s`. Loads A2DM bank files, installs LC images by CPU copy, then leaves ProDOS |
| Disk | `K/tools/build_disk.py`. Data made by upstream's own Python tools run from the clone. Outputs are checked against the release segments at `$10:0000`, `$1F:0000` and `$40:0000` |
| Level store | Kept in RAM as a chain of extents. The B1 decoder is hand-written, with a CPU loop and bounce buffer for matches. Estimate 4 to 6 s per map |
| Input | `K/src/kernel/input.s`. Keys become synthetic codes in the 32-byte ring that `I_StartTic` reads. The //e keyboard reports one key at a time; mouse and Apple keys cover turning, fire and strafe |
| Clock | Mouse-card VBL IRQ scaled to 35 Hz (`K/src/kernel/frame.s`). `I_GetTime` re-reads the count until two reads agree |
| IRQ | Handler in main LC, mirrored in aux LC. It reads `$C013/$C014/$C016`, which are served internally, and restores switch state and `$C073` from the shadow |
| Sound | Stage 1: DOC driver stubbed; `s_sound65.s` logic runs. Stage 2: AY effects. Stage 3: music converted at build time from the clone's `.mus` files. One register burst every second VBL |
| Saves | `DOOM.SETTINGS`, one block. Written through the slot-7 block driver with `$42-$47` and `$07F8` kept clear |
| Reused | `far.s` (becomes F0), `amem.s`, `profile.s`, `gamebanks.s` IRQ pattern, `a2sim.py` API, `run_doom.py` pattern |
| Retired | cc65 game, our renderer, `wad2a2.py`, `space.s` phase swap |

## 6. Performance estimate, E1M1 idle, today's firmware

**Assumptions.**

| # | Assumption | Nominal | Range |
|---|---|---:|---|
| P1 | CPU rate in BRAM | 45 M cycles/s | 42 to 55 |
| P2 | Upstream instructions per frame outside the replay | 450,000 | 300,000 to 600,000 |
| P3 | Native cost per instruction, calls included | 18 cycles | 15 to 24 |
| P4 | Share of executed instructions that are native | 97 percent | 90 to 99 |
| P5 | Interpreter cost with the code-page cache | 3.2 µs | 3.0 to 3.9 |
| P6 | Far accesses | 54,000 (12 percent) | |
| P7 | Far mix: 35,000 through F2 with 2,000 misses; 8,000 direct; the rest fused | | |
| P8 | SHR bytes | 13,000 | |

P2 derives from upstream's "~4 FPS" at 12 MHz (`U/README.md:15`), which includes bus stalls, so 600,000 is an upper bound.

| Phase | Instructions | CPU | Far and stalls | Total |
|---|---:|---:|---:|---:|
| 4 game tics | 110,000 | 53 ms | 45 ms | 98 ms |
| Setup, BSP, wall setup | 190,000 | 92 ms | 60 ms | 152 ms |
| Seg loops and records | 90,000 | 44 ms | 25 ms | 69 ms |
| Sprites, masked, weapon | 40,000 | 19 ms | 15 ms | 34 ms |
| 2D and finish | 20,000 | 10 ms | 5 ms | 15 ms |
| Replay | hand-written | | | 32 ms |
| Phase loads | | | | 21 ms |
| IRQ, input | | | | 3 ms |
| **Total** | 450,000 | 218 ms | 150 ms | **about 424 ms, 2.4 FPS** |

CPU includes 3 percent interpreted (43 ms in total).

| Case | Frame | FPS |
|---|---:|---:|
| Tier 0, all interpreted | about 1.9 s | 0.5 (0.3 to 0.8) |
| Optimistic: 300,000 instructions, 15 cycles, 55 M/s | about 240 ms | 4.2 |
| Nominal | about 424 ms | 2.4 |
| Pessimistic: 600,000, 24 cycles, 42 M/s, 90 percent native | about 710 ms | 1.4 |
| Nominal plus hand-written seg loops, node fetch and thinker walk | about 340 ms | 2.9 |

Below 8.75 FPS the 4-tic cap slows game time, as upstream does (`d_main65.s:320-370`, reported).

**Measurements that narrow the range.**

| Measurement | Milestone | Narrows |
|---|---|---|
| Per-phase instruction counts from the reference run | 2 | P2 |
| Hot code size per phase and page heat | 2 | P4, the window budget |
| Far accesses per phase, by bank and by object | 2 | P6, P7 |
| Hardware microbenchmarks: straight-line BRAM code, far sequence, PSRAM miss, drain, amem per byte and per request | 0 | P1, far costs, phase loads |
| Replay on hardware | 4 | Replay, P8 |

## 7. Verification strategy

| Layer | Check | Tool |
|---|---|---|
| 1. Front end | Pristine build equals the release bytes | `asm816`, `imgmatch` |
| 2. Reference | `ref816` running the release image agrees with GSSquared at fixed tics | debug socket, `READMEM` |
| 3. Port image | `ref816` running the port image agrees with the pristine run on game state, by symbol | `ref816`, symbol map |
| 4. Inference | Static M, X, D, DBR equal the observed values per PC | reference trace |
| 5. Cores | Interpreter and `ref816` pass per-opcode vectors | SingleStepTests 65816 (assumption: must be downloaded) |
| 6. Templates | Each emitted sequence against the core on random states, flags included | template tester |
| 7. Lockstep | Registers and memory writes compared at every translated instruction | `a2vm` + `ref816` |
| 8. Kernels | Record lists before replay; SHR bytes at frame end | data compare |
| 9. Hardware | Per-phase times; microbenchmarks calibrate the cost model | mailbox, ARM microsecond counter |

- **`ref816`.** A C 65816 core with a minimal IIgs: RAM, shadow register, DOC timer, ADB and block-device traps. Deterministic. It logs writes to executed bytes and taints pushed return addresses.
- **`a2vm`.** A C 65C02 core with the Appletini map, amem, and a cost model for PSRAM misses, bus accesses, cache invalidation and mirror drain. It is validated against `K/tools/a2sim.py` on our existing port.
- **Lockstep without instrumentation.** The translator emits a map from host PC to original PC, widths and live flags. The tested binary is the shipped binary.
- **Coverage scripts.** demo3, timedemo builds of demo1 and demo2, `idclev` tours of nine maps, menu scripts, every view size, detail change, benchmark start.
- A region is translated only after lockstep has executed it.

## 8. Milestones

| # | Deliverable | Test |
|---|---|---|
| 0 | Hardware microbenchmarks and standard SHR check | Cost table measured; 320-mode picture with per-row palettes correct |
| 1 | Front end, 65816 assembler, image match | Pristine build equals the release segments |
| 2 | `ref816` plays demo3 from the release image; profiles | GSSquared checkpoints agree; phase counts, heat and stack depth produced |
| 3 | `a2vm` with cost model; interpreter | Existing port's tests pass in `a2vm`; opcode vectors pass |
| 4 | Hand-written replay on hardware from dumped records | Screen equals the reference; replay time and bytes measured |
| 5 | Whole game interpreted in `a2vm`, lockstep through demo3; platform layer; first hardware run | Per-tic state equality; slideshow on hardware |
| 6 | Translator with template tests; intrinsics; first modules | Lockstep on `m_random65`, `string65`, `z_zone65`, `w_wad65` |
| 7 | Hot regions translated; planner and phase windows; F2 decision | Lockstep through all scripts; hardware profile |
| 8 | Hand-written seg loops, node fetch, thinker walk | Record lists equal; FPS measured |
| 9 | Status bar, HUD, menus, automap, intermission | Screen compares |
| 10 | Sound effects, then music | Register-stream tests; listening |
| 11 | Settings and saves, nine-map soak, release | Hardware soak |

Section 12 breaks down milestones 0 to 2.

## 9. Risks

| Rank | Risk | Mitigation |
|---:|---|---|
| 1 | Hot code does not fit the phase windows, so more is interpreted | Measure at milestone 2; compact emission; warm overlays; hand-written kernels; firmware change 1 |
| 2 | Far cost keeps speed under 2 FPS | F1 sessions, F2 cache, intrinsics from the first translated build; firmware change 2 |
| 3 | Hot near data exceeds the near core and window 2 | Planner by fragment and by annotated object; phase-mapped extents |
| 4 | Front end cannot reproduce every byte, or the release was not built from `8ea2eac` with defaults | Fragment matching; the image is ground truth |
| 5 | Inference or flag error on a rarely run path | Translate only covered regions; checked builds; template tests with flags |
| 6 | Uncatalogued self-modification | Patch-table parse, dynamic log, write-watch, fail closed |
| 7 | Re-laid near bank breaks a hidden adjacency between modules | Pristine against port comparison in `ref816`; fragments keep source order |
| 8 | Hardware differs from `a2vm` | Milestone 0; recalibrate at each hardware milestone |
| 9 | Host stack overflow | Static bound; S discipline for recursion; guard in checked builds |
| 10 | Direct 2D drawing flickers | Private buffer per failing path |
| 11 | One key at a time | Mouse and Apple keys; owner question 7 |
| 12 | Sound cost: one slot-4 access forces 1 MHz for 512 cycles (`F/ps_sources/frontend/config_menu.c:76`, reported) | One burst every second VBL; sound off option |
| 13 | RAM: 104 banks plus store plus code images is close to the limit | Compute reciprocal or step tables instead of storing; level store from disk |
| 14 | Licence | `cal_integer.s` never assembled; upstream not committed; owner question 3 |

## 10. Firmware wish list

**Effect of the three changes under discussion.**

| Change | Effect on this design | Estimated frame |
|---|---|---:|
| (1) Multi-line cache, possibly DDR | Code can run from extended memory. Phase windows, warm overlays and the interpreter leave the frame path. F2 is unnecessary | about 330 ms |
| (2) Switch and bank writes without bus cycle or cache flush | F0 drops from about 6.5 µs to under 2 µs. F1 and F2 become optional. Replay switch cost disappears | about 300 ms; about 240 ms with kernels |
| (1) and (2) together | | about 190 ms, 5 FPS |
| (3) Separate read and write banks | Replay passes G and S merge once colormaps are reachable. `vmvn` and B1 lose the bounce buffer | 5 to 10 ms less |

**Ranked wishes.**

| Rank | Wish | Benefit |
|---:|---|---|
| 1 | Change (2) | Largest single gain; simpler translator |
| 2 | Change (1) | Removes the code-placement risk |
| 3 | Deferred SHR mirror, flushed at handback | 12 to 26 ms per frame |
| 4 | Change (3) | Single-pass replay |
| 5 | amem copy visible to the display | Tear-free presentation from a private buffer |
| 6 | Microsecond counter at a fabric-served address | Cheap profiling |
| 7 | Key-state register for the USB keyboard | Several keys held |
| 8 | amem endpoints in the language card and bank 127 | Simpler installs |
| 9 | Shorter slot-4 slow window | Lower sound cost |

## 11. Decision log

| # | Decision | Alternatives rejected | Why |
|---|---|---|---|
| D1 | Keep the 24-bit space virtual | Physical far pointers with relinked data | Upstream stores and computes on addresses, instruction sizes and frame sizes. Relinking breaks byte comparison and needs patched packers |
| D2 | Original addresses for all code pointers | `$C0:id` tokens | Tokens break address arithmetic, tables and the interpreter (`r_seg65.s:998-1004`, verified) |
| D3 | Interpreter first | Translator first | Whole game runs early; every hard idiom is correct by construction |
| D4 | Translation unit is a region with registered entries | Functions | Control enters mid-function (`r_list65.s:566-570`, verified) |
| D5 | Two call disciplines | Universal hole model; universal `vm_ret` | Holes break four sites and recursion. Universal `vm_ret` costs about 100 ms per frame |
| D6 | Flags in host P at boundaries, liveness inside | N and Z cells everywhere; lazy flags without a contract | Cells cost 9 cycles per instruction; no contract is unsound |
| D7 | Whole direct pages at fixed addresses | Promoting cells to zero page | The pages are reached by `dp`, `abs`, `long` and indexed modes |
| D8 | Re-laid near bank in the port build | Upstream addresses with a page table; three homes | Hot and cold objects interleave; a page table cannot serve 16-bit indexes |
| D9 | Code only from BRAM | Native code run from RamWorks banks | With RAMRD on, main data is unreadable; with ALTZP, registers fall into PSRAM. Kept as a milestone 0 experiment |
| D10 | Phase windows loaded by amem, immutable content | One resident map; save and restore swaps | 48 KB cannot hold all phases; immutable loads need no save |
| D11 | Exact multiply intrinsics; tables dropped | 512 KB quarter squares | Four far reads per product, about 30 µs |
| D12 | Records stay in RamWorks, accessed by session | Records in fast memory | 160 home pages are 40 KB |
| D13 | Replay in passes R, G, S, F | Per-record switching; single pass | Shared bank register; each `$C073` write forces a flush |
| D14 | Level store in RAM | SmartPort reads at level start | No run-time disk code; `$07F8` hazard avoided |
| D15 | Own Python preprocessor | `clang -E` as primary | Token paste and `##` operands coexist; build must not depend on the host compiler |
| D16 | Profiles choose placement only | Profile-derived facts in emitted code | Unsound |
| D17 | `LOGIC_SP` overridden | 13.5 KB resident stack | The two stacks are 9.3 KB apart |
| D18 | F2 by 64-byte lines, per-bank policy, built only if the model shows a gain | 256-byte pages; always on | Dirty page misses cost about 240 µs |
| D19 | `ref816` as our own core | GSSquared only | Determinism, speed, tracing. GSSquared remains the oracle |

## 12. First three milestones in detail

Assumed location: a new directory `demos/iigs-doom/` (owner question 1). Paths below are relative to it.

### Milestone 0: hardware costs (days)

| File | Purpose | Acceptance test |
|---|---|---|
| `bench/bench.s` | Timed loops: straight-line BRAM code over 128 bytes; F0 sequence, same bank and bank change; sequential and random PSRAM reads and writes; SHR store burst followed by one `$Cxxx` access; amem 1 KB, 16 KB, 48 KB; code run from a RamWorks bank | Each loop reports microseconds from the amem STATUS counter; results repeat within 5 percent |
| `bench/shr320.s` | Standard 320 mode, 200 SCBs, 16 palettes, test picture | Photo or capture equals the expected picture |
| `bench/bench.cfg`, `bench/Makefile` | Build with ca65 and ld65 | Builds with cc65 2.18 |
| `tools/bench_capture.py` | Read results over the UART mailbox | Writes `build/bench.json` |
| `docs/HW_COSTS.md` | Measured cost table | Every row of section 6 has a measured value or a stated reason why not |

### Milestone 1: front end and image match (about 2 weeks)

| File | Purpose | Acceptance test |
|---|---|---|
| `tools/fetch_upstream.py` | Pinned clone into `build/upstream` | Commit equals `8ea2eac` |
| `tools/v816/cpp.py` | Preprocessor | Output equals `clang -E` on all files, apart from whitespace |
| `tools/v816/lexer.py`, `expr.py` | Tokens and expressions | Unit tests for every operator in the syntax chapter |
| `tools/v816/macro.py` | Macro expansion and local scopes | 131 macro definitions parsed; `WALKBANK` expands with its own `1$` |
| `tools/v816/parse.py` | IR: one record per instruction or datum | All 60 game sources plus `gendraw.py` output parse with no error |
| `tools/v816/scm.py` | Read `iigs.scm` placement | 60 memory regions read |
| `tools/v816/asm816.py` | 65816 encoder | Per-opcode round trip against a table |
| `tools/v816/link.py` | Section placement and symbol resolution | Entry symbol at `$03:0000` |
| `tools/v816/hdv.py` | Release image reader | 28 segments; SHA-256 equals `SHA256SUMS` |
| `tools/v816/imgmatch.py` | Fragment match, then full compare | Every byte of segments 1 to 20 equal; mismatches listed by file and line |
| `tests/test_frontend.py` | Runs all of the above | Passes from a clean tree |

### Milestone 2: reference run and profiles (about 2 weeks)

| File | Purpose | Acceptance test |
|---|---|---|
| `tools/ref816/cpu816.c` | 65816 core | SingleStepTests vectors pass |
| `tools/ref816/iigs.c` | RAM, shadow register, DOC timer, ADB ring, block-device traps | Release image boots to the title |
| `tools/ref816/trace.c` | Per-PC M, X, D, DBR; write-to-code log; return-address taint; stack depth; page heat; far accesses by bank | Trace files produced for demo3 |
| `tools/ref816/main.c`, `Makefile` | Driver with scripted input | demo3 runs to its end; 35 tics per second of game time |
| `tools/gs2_oracle.py` | GSSquared checkpoints by debug socket | Memory at 10 fixed tics equals `ref816` |
| `tools/profile816.py` | Reports | Instructions per phase, hot code bytes per phase, near heat by fragment, stack high-water marks |
| `coverage/*.script` | Input scripts | View sizes, detail, benchmark, nine maps executed |
| `docs/PROFILE.md` | Results | P2, P4 and P6 of section 6 replaced by measured values |

## 13. Open questions for the project owner

1. **Repository.** New directory beside `demos/doom`, or replace it? Is the cc65 port kept?
2. **Acceptable speed.** Is 2 to 3 FPS on today's firmware acceptable for a first release, given that game time runs slow below 8.75 FPS?
3. **Distribution.** The game is GPL-2 and the data is the shareware `DOOM1.WAD`. May we publish disk images, and with what source offer? Or do users build from their own clone?
4. **Firmware order.** Which of changes (1), (2), (3) is likely first, and when? Change (2) helps this design most.
5. **Overrides.** Are changes to upstream behaviour acceptable where results are identical: moved `LOGIC_SP`, re-laid near bank, no text-code cache, intrinsic multiplies?
6. **View sizes and benchmark menu.** Required in the first release, or may they run interpreted and slow?
7. **Input.** Does the Appletini expose USB keyboard key state or a joystick beyond the paddle ports? Is the mouse card a fixed requirement?
8. **Memory.** May the port require 8 MB RamWorks with 126 banks? Is bank 127 usable outside amem?
9. **Video.** PAL, NTSC or both as the default?
10. **Sound.** Priority of effects and music against speed; is a silent first release acceptable?
11. **Level store.** Is a longer boot acceptable to keep the store in RAM, or should levels load from disk?
12. **Tools.** May the build download SingleStepTests vectors? May `ref816` reuse GSSquared's core under its licence?

## Appendix: critic findings and their resolution

| Source | Finding | Resolution |
|---|---|---|
| Correctness-first, correctness | B1 tokens | D2, section 2.5 |
| | B2 static residency | Extents and run-time translation, sections 2.4, 3.3 |
| | B3 units | D4 |
| | B4 pointer patchers | Section 2.7 |
| | M1 to M7 | Sections 2.2, 2.3, 2.6, 3.3, 3.4, 5 |
| Correctness-first, performance | 1 far cost; 2 interpreter fetch | Sections 3.4, 6; code-page cache |
| | 3, 4, 5, 6 map | Sections 3.2, 3.3, D12 |
| | 7 multiplies | D11 |
| | 8 to 18 | Sections 3.2, 3.6, 4, 5. Item 13 swap volume remains risk 1 |
| Performance-first, correctness | B1 to B4 | Image kept real; soft stack; host stack separate |
| | B5 near bank | One virtual bank, D8 |
| | B6 aux LC | 12 KB budget, section 3.2 |
| | M1 to M15 | Sections 2.2, 2.3, 2.6, 2.8, 3.3, 4, D16 |
| Performance-first, performance | Oversubscription, visibility conflicts, low counts | Phase windows; multiplies never run with RAMRD on; factor 18 cycles; risk 1 |
| Incremental, correctness | B1 hole model | D5 |
| | B2 flags | Section 2.3 |
| | B3 self-modification | Section 2.7 |
| | M1 to M11, m1 to m7 | Sections 2.1, 2.2, 2.5, 2.6, 3.2, 3.3, 3.4, 5 |
| Incremental, performance | C1 code budget | Section 3.5; open as risk 1 |
| | C2 interpreter | Code-page cache |
| | C3, C4 replay and records | Section 4 |
| | H1 to H5, M1 to M8, L1 to L6 | Sections 3.2, 3.3, 3.4, 4, 5 |

**Open after this design:** hot-set fit (risk 1), near hot-set size (risk 3), F2 benefit (D18), 2D flicker (risk 10), RAM headroom (risk 13).