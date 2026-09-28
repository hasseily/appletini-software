# Correctness review: incremental-hybrid proposal (V816)

All upstream paths are relative to `<upstream>/src/iigs/`. I opened every cited line in this session. Counts marked "heuristic" come from line-based scripts that do not expand macros; treat them as lower bounds. No files were created or modified.

## Verdict

Tier 0 (interpreter) is sound. It sidesteps almost every idiom below because it keeps real return addresses, real code bytes and dynamic D/DBR/P.

Tier 1 (native) as specified would produce wrong control flow and wrong arithmetic in the BSP walk, the seg loop, path traversal, sight checks and the thinker walk. Those are the functions the profile will pick first. The main causes are the stack-hole model, an incomplete flag model, and a self-modifying-code model that only knows operand patches.

## Claims checked against source

| Proposal claim | Result |
|---|---|
| Return-frame discard: 1 site (`m_menu65.s:2439-2457`) | Wrong. 3 discards plus 1 return-address rewrite (B1) |
| `p_trace65.s:1852, 1865` and `p_path65.s:1107, 1115` are operand patches | Half wrong. The `p_trace65.s` stores patch branch displacements of hand-encoded `BRA` (B3). `p_path65.s:1107/1115` patch the address operands of `wRdX`/`wRdY`, which are also read back as data at `p_path65.s:1128` |
| D is static from `tcd/tdc` | Wrong. D is used as a data register in `p_trace65.s` (M4) |
| DBR is computed only in `P_RunThinkers` | Wrong. 29 dynamic `pha/plb` sites (heuristic), 17 in `p_map65.s` (M3) |
| "High byte is always processed last, so C, V and N are right" | Wrong for inc/dec, right shifts, compares and any load or store (B2) |
| Decimal mode never used | Confirmed: no `sed`; also no `wai/stp/brk/cop/mvp` |
| `sep #$10`: 13 sites, nearly all in the replay | 14 found: 7 in `loader.s`, 7 in `r_list65.s`. Harmless |
| `IIGS_TextCode` stub falls back to `IIGS_DrawPatch` | Only if `I_DrawCachedText` is also overridden (m4) |
| Private tic stack "works unchanged" | Control flow yes, memory budget no (M6) |
| `N$` labels scoped between non-local labels | Incomplete: each macro expansion has its own scope (m1) |

## Blockers

### B1. The hole model breaks every routine that edits return addresses

With return addresses on the hardware stack, code that moves S past a return address, or stores into one, changes only the hole.

| Site | Idiom | Native result |
|---|---|---|
| `r_bsp65.s:1309-1311` | `lda ##.word0 (c14SideDone-1) / sta 1,s / rtl`; called by `jsl c14Bounds` at `r_bsp65.s:264` | Store lands in the hole; returns to line 265, not `c14SideDone` (`:289`) |
| `p_path65.s:1089-1092` | `gWalk1: tsc / clc / adc ##3 / tcs` drops the frame of `jsl gBlockW` (`:991`) | Stale hardware return address; the next `rts` returns into `gRun` |
| `w_level65.s:1443-1448` | `titleWipe` drops its JSL frame, then `rtl` to the caller of `D_Wipe` | Returns one level too shallow |
| `m_menu65.s:2453-2457` | `bmDone`: `tsc / adc ##19 / tcs` | The one site the proposal lists |

The first is in the BSP side test, run for every node, every frame.

Fix: a static pass that flags any function containing `sta n,s` where `n` falls inside the return address, or a `tcs` whose delta is not matched within the function. Flagged functions and their direct callers use real virtual return addresses on the soft stack, or stay interpreted. Make the build fail on an unclassified `tcs`.

### B2. The flag model is incomplete

The 65816 leaves flags alone on stores, pushes and effective-address calculation. The proposed sequences do not.

| Problem | Evidence | Sites (heuristic) |
|---|---|---:|
| 16-bit `dex/dey/inc/dec` with a skip-style sequence leaves N from the low byte | `r_list65.s:188-191`: `ldx ##319 / sta long:FS_STAMP,x / dex / bpl`. Exits at X=`$00FF`, leaving 256 stamps unwritten | 127 |
| Carry live across a far read or write | `p_inter65.s:118-122`: `cmp .near IN_T / ldy ## / lda [_Dp+4],y / sbc`. Also `p_floor65.s:796-802`, `am_map65.s:2306-2309` | 360 |
| Carry live across an indexed address calculation (the "16-bit add into `fp`") | `am_map65.s:877-880` `less32`: `cmp abs:0,x / lda abs:2,y / sbc abs:2,x` | 318 |
| N/Z consumed after a store | `d_main65.s:283-287`: `sbc / sta .near TR_RUN / beq / bpl`. `p_doors65.s:76-79`: `sta [_Dp],y / beq / bpl` | 82, of which 23 far or stack |
| V must survive to `bvc/bvs` | 183 `bvc/bvs` lines, e.g. `actor.inc:47-51`; a 16-bit `cmp` built from `cmp/sbc` clobbers V | 183 |
| `ror`/`lsr` process the high byte first, so N comes from the low byte | `i_viigs65.s:1648` | 1 |
| Z fix `ora rA` destroys N and the A scratch | 78 `bmi/bpl` after compare, 38 after `txa` | — |

Fix: define flag contracts per emitted sequence and per helper, then run liveness over N, Z, C and V.
- Far helpers preserve C and V and return N/Z of the full 16-bit value. Stores preserve all four.
- Index arithmetic must not use `adc`. Use table-based or `inc`-based address formation, or `php/plp`.
- 16-bit inc/dec emit full N and Z whenever either is live.

Re-cost §2.4 afterwards. The 18 to 22 cycle average will rise.

### B3. Self-modifying code outside the replay is more than operand patches

| Class | Evidence | Why a named cell fails |
|---|---|---|
| Patched branch displacement | `p_trace65.s:1681`: `ptT1: .byte 0x80, 6, gtLines-(ptT1+2), 6`, patched by `ptPatch` (`:1847-1866`) by copying byte +2 or +3 into +1. Same at `p_trace65.s:1762` and `p_path65.s:330, 337, 371, 684, 731` | The instruction is `.byte` data. The value is a relative offset in 65816 bytes |
| Patched opcode in the seg loop | `r_seg65.s:1938-1939`: `c17Return: .byte 0x60, 0, .byte1 (drawMid+7)`. Written per seg by `c17Setup` (`:5178-5180`) from `c17Next` (`:5181+`), and by `c17Slow` (`:520-528`) | Switches between `RTS` and `JMP abs` |
| Raw instruction bytes stored over code | `r_seg65.s:4233-4249` `c16Mode` writes 8 bytes to `tierDraw` and 4 to `drawMid+31`, `drawTop+31`, `drawBot+31` from byte tables (`:4251-4262`) | Code installed by `sta`, not MVN |
| Entry at label plus byte offset | `drawMid+7`, `drawTop+7`, `drawBot+7` (`r_seg65.s:5183-5210`); comment `:4255-4256` "Each TIER remains 39 bytes" | Depends on 65816 instruction sizes |
| Patched address operand, also read back | `r_seg65.s:2621-2627` `c26Lookup+1`; `p_path65.s:1128` `adc long:(wRdY+1)` | Every reader must be rewritten too |

The static detector keys on stores onto instruction labels. It cannot see that the target is a hand-encoded instruction, and 7 of these sites are game logic run every tic.

There is also a cross-tier hole. If the patcher is interpreted and the target is native, the write lands in the 65816 image and the native cell never changes. `c17Setup` is in section `core5cold`; the seg loop it patches is hot.

Fix:
- Parse `.byte` runs in text sections as instructions where a disassembly is consistent; list the rest for hand review.
- Add classes "branch select", "opcode select" and "code image install". Emit a cell plus a dispatch over the enumerated values, which are all present in the source tables.
- Register every cell's virtual address in a write-watch table used by the interpreter and the far-write path.
- A function with any unclassified patch site stays interpreted, enforced by the build.

## Major

### M1. Indirect jumps through RAM vectors are missing from §2.6

- `jmp (abs:SVEC)` occurs 14 times in `p_sight65.s` (`:662` to `:895`). `SVEC` is a direct-page word loaded with mid-function labels (`p_sight65.s:317-318, 400-401, 519-520`).
- `jmp (abs:PVEC)` at `p_map65.s:2199, 2201`. `jmp (RL_FENT)` at `r_list65.s:2693, 3698`.

Fix: treat `##.word0 <code label>` immediates as code references, give each target a native entry with its M/X/D/DBR state, and lower `jmp (abs)` to a dispatch over the stored set.

### M2. No state contract at tier boundaries

Native code holds D and DBR statically, M/X implicitly and Z lazily. The interpreter needs `rD`, `rDBR` and P. The proposal does not say when they are materialised.

- A native caller that set DBR with `pea / plb / plb` (`r_seg65.s:500`) and then reaches interpreted code leaves `rDBR` stale.
- Native-to-interpreted calls leave garbage in the hole; the interpreter's `rts`/`rtl` needs a sentinel.
- The interpreter must be re-entrant, with scratch saved across nesting.

Fix: one documented entry/exit thunk pair that writes `rD`, `rDBR`, P and canonical A/X/Y homes, and a sentinel return address.

### M3. DBR is dynamic far more often than stated

29 dynamic sites (heuristic): `p_map65.s` 17, `p_tick65.s` 5, `p_trace65.s` 4, and one each in `p_attack65.s`, `p_pspr65.s`, `p_sight65.s`. Example: `p_pspr65.s:429-437` sets DBR from `_g_sectors+2`, then `recursiveSound` uses `abs:OFS_SEC_VALIDCOUNT,x` (`:453`).

Fix: keep `rDBR` live in native code. Use a constant bank only where data-flow proves it.

### M4. D is used as a data register

`p_trace65.s:430-431` and `:489-490` do `lda ##1 / tcd`. The loop at `:503-505` does `tdc / rol a / tcd`. D is restored at `:512-513`.

Fix: `tcd`/`tdc` always move through `rD`. If D is not a known constant at a `dp` operand, fail the build for that function.

### M5. Splitting WPAGE by variable breaks aliasing

WPAGE is reached three ways: `dp:` under D=`$0A00`, `long:(WPAGE+W_x)` (heuristic: 34 lines in `r_seg65.s`, 47 in `r_wall65.s`, 16 in `r_frame65.s`, 15 in `r_list65.s`, 5 in `d_main65.s`), and indexed loops such as `r_list65.s:307-309` (`lda dp:0,x`). A 256-entry page table for bank `$00` cannot express a per-variable split.

Also, zero page holds 16 + 211 + 24 = 251 bytes by the proposal's own numbers, so WPAGE pointer bases do not fit.

Fix: give each virtual direct page one contiguous physical home. Put WPAGE in one main page and lower its `[dp],y` through a helper that takes an absolute pointer address.

### M6. The soft stack is too small for a constant offset

`LOGIC_SP` is `$1B6F` (`p_think65.s:183`) and the frame stack starts at `$3FFF` (`iigs.scm:32-33`). That is 9.3 KB apart; the budget is 2 KB.

Fix: map all 13.5 KB, or use two windows and translate `tsc`-derived pointers through the bank-0 page table. Measure both high-water marks at M2.

### M7. Hardware stack overflow in recursion

`recursiveSound` (`p_pspr65.s:451-506`) recurses by `jsr` per flooded sector, and maps allow 256 sectors. Natively that is 2 bytes per level plus tier thunks, IRQ frames and nested interpreter frames, in 256 bytes.

Fix: mark recursive call-graph cycles at build time. Those use soft-stack return addresses or stay interpreted.

### M8. Word access across the `$7FFF/$8000` granule edge

Zone blocks sit anywhere in a bank, so words at `$xx:7FFF` will occur. If a helper resolves the low byte and reads the second byte with `(fp),y`, it touches physical `$C000`. A write to `$C001` turns 80STORE on.

Fix: per-byte resolution when the low address byte is `$FF` at a granule edge, plus an emulator assertion that no far helper touches `$C000-$CFFF`.

### M9. Page cache coherence

F2 caches pages in fast memory, but the hand-written replay, `vmvn`, amem COPY and `far_copy` read the RamWorks banks directly. Records written by a native seg loop through F2 may not be in bank `$1D` when the replay starts. §3.4 flushes only at level start.

Fix: keep the record bank and texel banks on F0, or flush dirty pages before replay and before any amem or MVN that touches a cached bank.

### M10. Interrupts versus mapping state

The present handler is safe because it touches no mapping (`[SW]src/kernel/kstart.s:268-285`). The proposal adds AY music to the VBL path. An IRQ during the gather pass or inside a far helper runs with RAMRD on and `$C073` on another bank.

Fix: the handler and all its data live in main LC `$E000-$FFFF` or zero page. Otherwise it saves and restores RAMRD, RAMWRT and a `$C073` shadow that is written before the register. Native `I_GetTime` must read the tick count with a re-read loop.

### M11. M/X inference must be interprocedural

Heuristic scan: 80 of 3,277 calls are made with M=1 or X=1, and 29 routines return in 8-bit mode (for example `r_seg65.s:1643`, `p_map65.s:938`, `p_tick65.s:895`). There are 56 `plp` lines against 23 `php` lines (raw grep), and some `plp` sit on labels reached from several paths (`p_sight65.s:756`).

Also, under M=1 with X=0, `tax`/`tay` copy all 16 bits of B:A. Upstream relies on it (`p_tick65.s:160-163`).

Fix: propagate entry state per call site, emit variants or fail on conflict, and pair every `plp` with its `php` on all paths.

## Minor

| # | Problem | Evidence | Fix |
|---|---|---|---|
| m1 | Macro expansions need their own local-label scope | Calypsi guide §21.11.2; `WALKBANK` defines `1$` (`p_tick65.s:96-102`) | Implement it; the image match will confirm |
| m2 | Banks `$E0/$E1` fall outside the 128-entry map | `w_level65.s:1417-1442` MVN to `$E1:2000`; 16 references in `i_viigs65.s` | Alias `$E1` to base aux, trap `$E0`, never use amem for these |
| m3 | Profiling mailbox at aux `$A000` collides with `FUZZ_DARKEN` at `$01:A000` | renderer report §2.1 | Move the mailbox |
| m4 | Stubbing only `IIGS_TextCode` leaves `textValid` set, so the next call runs absent code | `i_viigs65.s:1822-1830, 1858-1864` | Override `I_DrawCachedText` to always return 0 |
| m5 | Near bank: 54 KB cold remainder exceeds one RamWorks bank's 48.6 KB | §3.1, §3.2 | Two banks |
| m6 | Quarter-square override is not purely macro-level | `am_map65.s:2305-2309` chains carry across `AM_SQL` and `AM_SQH` | Override at the enclosing routine for inline sites |
| m7 | Native `php` pushes 65C02 bits 4 and 5, not virtual M/X | `r_list65.s:194-202` | Compose the pushed byte from static M/X |

## The three most important changes

1. **Replace the universal hole model with a per-function stack discipline chosen by static analysis.** Functions that rewrite or discard return addresses, switch stacks, or recurse get real virtual return addresses on the soft stack. Size the soft stack for both `$3FFF` and `$1B6F`.

2. **Write a complete flag and register contract before any emitter work.** Cover N, Z, C and V for every emitted sequence and helper, make D and DBR live registers in native code, and define one tier-boundary thunk. Test each sequence against the 65816 opcode vectors including flags.

3. **Widen the self-modifying and indirect-control model and make it fail closed.** Parse `.byte`-encoded instructions, add the branch-displacement, opcode-select, code-install and label-plus-offset classes, handle `jmp (abs)` through RAM vectors, and add a write-watch so interpreted patchers reach native cells. Any function with an unclassified site stays interpreted.