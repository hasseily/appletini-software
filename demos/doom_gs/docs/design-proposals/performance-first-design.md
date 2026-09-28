# Design proposal: IIgs DOOM on the Appletini 65C02, optimised for frame rate

Path legend: `[U]` = `<upstream>`, `[F]` = `.../scratchpad/appletini-one-main`, `[R]` = `.../scratchpad/research`, `[SW]` = `<appletini-software>/demos/doom`.

Nothing was assembled, run or measured here, and no file was changed. Every timing is an estimate from the cost model below. Items marked **(A)** are assumptions.

## Cost model used throughout

| Item | Value | Basis |
|---|---|---|
| BRAM code, per classic 65C02 cycle | 16 ns (range 13-20) **(A)** | 436 fabric clocks for a 16-iteration copy loop (`[F]README_TURBO.md`, benchmark table); the existing port runs about 10 M model cycles in about 184 ms outside blit and copies (`[R]existing-port.md` §5) |
| PSRAM access, same 8-byte line | about 30 ns **(A)** | one line, write-allocate (`[F]hdl/apple/vtw_core_top.sv:1032-1040`) |
| PSRAM miss, clean / dirty line | 1 us / 2 us | one op per admission window (`vtw_core_top.sv:183-186`, `psram_simple.sv:28-33`); a dirty miss flushes then fills (`vtw_core_top.sv:2045-2095`) |
| Code fetched from PSRAM | about 0.42 us per byte | v6 to v7: 25.7 ms saved for about 60.7 K fewer accesses (`[SW]docs/STATUS.md:204-227`) |
| Any `$Cxxx` access | 1.5 us (1-2) | brief; it also waits for pending SHR mirror bytes (`vtw_core_top.sv:1330-1430`, `video_barrier`) |
| SHR byte written | 0.9 us, deferred to the next `$Cxxx` access | 24 ms for 26,880 bytes (`[R]existing-port.md` §5) |
| amem copy | 0.33 us per byte plus 0.3 ms per request **(A)** | 40.5 ms for about 120 KB in v12 |

Two consequences drive the design:

- An isolated far read from code in main RAM costs about 4.5 us, the same as about 280 BRAM cycles.
- Code must never execute from extended memory.

## 1. Architecture summary

- **Translator.** A build-time Python translator converts the pinned upstream clone to ca65 source. It is whole-program and profile-guided: a reference run supplies function heat, far-access counts, index ranges and stack depth.
- **Physical far pointers.** The 24-bit space is not kept virtual. Data is relinked so every object lies in `$0200-$BFFF` of a RamWorks bank. A pointer's bank byte is the `$C073` value, so a dereference needs no address translation.
- **Three code classes.**
  - M-code: translated code in main `$0200-$BFFF`, reading far data through kernel calls.
  - X-code: far-dense hot routines in the main language card, run with RAMRD and RAMWRT held on.
  - Hand-written machines: replay, row blocks, texel gather, seg column loops, multiply, 2D patch drawing, platform.
- **Fast memory is a managed cache.** Hot code and data stay resident. One 12 KB window is reloaded per frame with amem. Cold code arrives as overlays on demand.
- **Replay in two passes.** RAMRD and RAMWRT share one bank register, so texels are first gathered from PSRAM into main RAM in batches, then shaded and stored to SHR with no `$Cxxx` access inside the loop.
- **Tables.** The 512 KB quarter-square tables are deleted and replaced by an exact multiply on 2 KB of tables. Other large tables stay in PSRAM, grouped by bank.
- **Estimate.** E1M1 idle is about 114 ms per frame (8.8 FPS), with a range of 5 to 12 FPS.

## 2. Translator design

### Front end

- Run the C preprocessor first (152 `#include`, 127 `#if`; `[R]iigs-platform.md` §6), then expand the 105 macros, then resolve `N$` local labels per non-local label.
- Run `tools/gendraw.py` and parse its output only for reference. The row blocks themselves are hand-written.
- Evaluate expressions symbolically so `MM_*` constants can be replaced by our memory map.
- Drop the 118 cache-layout `.space` padding lines in code sections.
- The same front end feeds a 65816 assembler back end (section 7), which proves the parse against the release image.

### M/X and direct-page inference

- Data-flow over the control-flow graph from `rep`/`sep` sites (580 and 530 by my grep). Immediates (`#` and `##`) are width checkpoints.
- Function entry widths come from call sites. A conflict is a build error resolved by an annotation.
- The reference run checks the inferred width against the live P register at every executed instruction.
- D is tracked the same way through `tcd` (23), `phd` (15) and `pld` (19).
- DBR is tracked through `phb` (70) and `plb` (205). Where it is dynamic, as in the thinker walk (`[U]src/iigs/p_tick65.s:106-170`), it becomes the kernel's `curbank`.

### Register model

| 65816 | 65C02 home |
|---|---|
| A in 8-bit windows | real A; B in zero page `rAH` |
| C in 16-bit regions | zero page `rAL`/`rAH`; real A is scratch |
| X, Y | zero page `rX`, `rY`; real X/Y cache the low byte |
| D = `$0900` | main zero page (20 `registers` + 191 `ztiny` bytes by summing literal `.space`; a lower bound) |
| D = `$0A00` (WPAGE) | an absolute page; its hottest bytes overlay zero-page slots that are unused in that phase |
| DBR | `curbank` for far banks; nothing for near data |
| S | hardware stack |

Flags are computed lazily. Liveness decides whether N and Z of a 16-bit result are needed, and Z over both bytes is emitted only when it is consumed.

### Emitted sequences

Classic cycle counts, direct page low byte zero.

| Upstream form | 65816 cycles | Emitted 65C02 | Cycles | Bytes |
|---|---|---|---|---|
| `lda dp`, 8-bit | 3 | `lda zp` | 3 | 2 |
| `lda dp`, 16-bit | 4 | `lda zp / sta rAL / lda zp+1 / sta rAH` | 12 | 8 |
| `lda .near v`, 16-bit | 5 | same with absolute | 14 | 10 |
| `adc ##k` | 3 | `lda rAL / adc #lo / sta rAL / lda rAH / adc #hi / sta rAH` | 16 | 12 |
| `lda a / clc / adc b / sta c`, fused | 17 | `clc`, then a low-byte pass and a high-byte pass | 26 | 19 |
| `asl a`, 16-bit | 2 | `asl rAL / rol rAH` | 10 | 4 |
| `inx`, 16-bit | 2 | `inc rXL / bne / inc rXH` | 8 | 6 |
| `xba` | 3 | `ldx rAH / sta rAH / txa` | 8 | 5 |
| `lda abs,x`, index proven below 256 | 5 | `ldx rXL / lda abs,x` | 7 | 5 |
| `lda ofs,x`, X is a pointer, ofs below 256 | 5 | `ldy #ofs / lda (rX),y` | 7 | 4 |
| `lda abs,x`, general | 5 | 16-bit add into a pointer, then `lda (ptr)` | 23 | 15 |
| `lda n,s`, 16-bit | 5 | `tsx / lda $101+n,x / sta rAH / lda $100+n,x / sta rAL` | 16 | 11 |
| `pha`, 16-bit | 4 | `lda rAH / pha / lda rAL / pha` | 12 | 6 |
| `jsl` + `rtl` | 14 | `jsr` + `rts` | 12 | 3 |
| `rep` / `sep` | 3 | nothing, or one `lda`/`sta rAL` | 0-3 | 0-2 |
| 16x16 to 32 multiply | about 70 plus table reads | four 8x8 quarter-square products | about 200 | call |

Expected dynamic expansion **(A)**: 1.0-1.3x for 8-bit code, 1.5x for fused 16-bit chains, 3x for unfused 16-bit code, about 2.2x overall.

### Far access

| Case | CPU cycles | `$Cxxx` accesses | PSRAM | Total |
|---|---|---|---|---|
| X-code `lda (zp),y`, bank already selected | 8 | 0 | hit or 1 miss | 0.15 us or 1.1 us |
| X-code, bank change | 22 | 1 | 1 miss | 2.9 us |
| M-code read: `ldy #n / jsr far_rd_slot` (bank compare, `stz $C003`, `lda (slot),y`, `stz $C002`, `rts`) | 33 | 2 | 1 miss | 4.5 us |
| M-code read with bank change | 45 | 3 | 1 miss | 6.2 us |
| M-code write (RAMWRT pair) | 33 | 2 | fill now, flush later | 4.5 us + 1 us |

An M-code site is 5 bytes. The kernel has one stub per long-pointer slot.

### Calls, returns and stack

- `jsl`/`rtl` become `jsr`/`rts` inside one overlay or into resident code. Other calls go through a 6-byte gate that loads the target overlay.
- One hardware stack holds return addresses and data in the upstream layout. Stack-relative offsets that cross a `jsl` frame are reduced by one; this is static because each routine ends in `rtl` or `rts`.
- The per-tic private stack exists only for cache slots (`[U]src/iigs/p_think65.s:170-177`) and is dropped.
- BSP recursion (`[U]src/iigs/r_bsp65.s:154-240`) gets an explicit stack.
- Routines that build frames with `tsc`/`sbc`/`tcs` move their frame to a software frame stack if the reference run shows total depth above about 200 bytes.

### MVN, function pointers, jump tables

- **MVN** becomes a kernel block move taking banks from operands or variables. Short moves run on the CPU; moves above about 512 bytes **(A)** use amem.
- **`JML [dp]`.** A code pointer is a 16-bit address plus an overlay id in the bank byte. The site becomes a gate call. Comparisons against `.word0`/`.word2` of a function keep working because both halves are emitted consistently.
- **`jmp (abs,x)`** is native. **`jsr (abs,x)`** becomes a push of the return address and a jump.

### Self-modifying code

- Detection: any store whose operand resolves to a label in a text section.
- Opcode and operand patches are kept as patches in writable fast memory. They are never placed in the mirrored windows and never in read-only overlays.
- Indirect patches through pointers occur in the replay and installers, which are hand-written.

### Constructs that cannot be translated mechanically

Counts are my grep over `[U]src/iigs/*.s` and `*.inc` with comments stripped.

| Construct | Sites | Handling |
|---|---|---|
| MVN as `.byte 0x54` | 33 | kernel move; patched bank operands become variables |
| `JML [dp]` as `.byte 0xdc` | 8 | gate |
| Hand-assembled `.byte 0x6c` jumps | 8 | replay, hand-written |
| `tcs` / `tsc` | 23 / 25 | classify as frame, stack switch or discard; by hand |
| `tcd` / `phd` / `pld` / `tdc` | 23 / 15 / 19 / 2 | direct-page tracking |
| `phb` / `plb` / `phk` | 70 / 205 / 8 | DBR tracking |
| `xce` | 12 | firmware wrappers, replaced |
| Stack-relative operands | 316 | frame analysis |
| `pea` / `pei` | 27 / 124 | mechanical once frames are known |
| Stores onto labels in text sections | 203 sites, 76 labels (upper bound; includes variables kept in text) | patch classes above |
| `lda #opcode` immediates (`$60`, `$6C`, `$EB` and similar) | 35 | replay and installers |
| `jmp (abs,x)` / `jsr (abs,x)` / `jmp (abs)` | 18 / 14 / 23 | tables re-emitted |
| `rti` | 3 | kernel |
| Address arithmetic that assumes 64 KB banks | not counted | four-way bank selects in `SQPARTR` (`[U]src/iigs/m_fixed65.s:45-93`), FSTEP carry select (`[U]src/iigs/r_seg65.s:1920-1945`), zone links, WAD `filepos`; each is a named rule or a hand-written routine |
| `cal_integer.s` | 938 lines | replaced by our own routines; call sites by grep: `IIGS_MulLo16` 48, `_Mul32` 16, `_UDivMod32` 14, `_UDivMod16` 10, `_Div32` 8, `_Div16` 7, `_Mod16` 6, `_Mul16` 2 |
| Boot, loader, crt0, IRQ, DOC, ADB | about 5,000 instruction lines | platform layer |

## 3. Memory model

### Why physical pointers

I reject the virtual 24-bit space of the preliminary analysis.

- RAMRD and RAMWRT reach only `$0200-$BFFF`, so a 64 KB virtual bank needs two physical banks. The 64 banks upstream requires would need 128, and only 126 are reachable by amem.
- Every dereference would pay a table lookup and an offset fix.
- The packers must change anyway so objects do not straddle the split. They hard-code 64 KB at `[U]tools/levelimg.py:66`, `[U]tools/wadtool.py:94` and `[U]tools/levelset.py:307`.
- The build applies a small patch to the local clone at build time and supplies its own `memmap.inc`.
- All PSRAM structures are aligned to 8 bytes, so a 120-byte mobj is exactly 15 cache lines.

### What is visible together

| State | Visible for reads | Use |
|---|---|---|
| RAMRD off, ALTZP off | main 48 KB, main LC, main zero page and stack | M-code |
| RAMRD on, bank b | PSRAM bank b, main LC, main zero page and stack | X-code, gather |
| RAMRD off, ALTZP on, bank 0 | main 48 KB, base-aux LC, aux zero page and stack | replay shade |
| RAMRD on, ALTZP on, bank 0 | base-aux `$0200-$BFFF` with SHR, base-aux LC | 2D machine |

Writes follow RAMWRT independently.

### Fast memory map

| Region | Size | Contents |
|---|---|---|
| Main `$00-$FF` | 256 B | direct page image, virtual registers, kernel temporaries |
| Main `$0100-$01FF` | 256 B | hardware stack |
| Main `$0200-$03FF` | 512 B | kernel data, amem request buffer (266 B), overlay table |
| Main `$0400-$0BFF` (mirrored, read-only use) | 2 KB | 8x8 quarter-square tables |
| Main `$0C00-$1FFF` | 5 KB | clip arrays, COLW, FS/CV/WCLIP as byte-planar arrays indexed by column; WPAGE and BSPDP pages; frame stack |
| Main `$2000-$5FFF` (mirrored, read-only use) | 16 KB | resident renderer code without patches, loaded with amem PRIVATE |
| Main `$6000-$7FFF` | 8 KB | hot near data |
| Main `$8000-$8FFF` | 4 KB | patched renderer code, seg column loops |
| Main `$9000-$BFFF` | 12 KB | window W: records (8 KB) and texel stage (4 KB) while rendering; tic code while ticking |
| Main LC `$E000-$FFFF` | 8 KB | kernel (far stubs, gates, amem transport, IRQ, input, clock), multiply, reciprocal, gather loop |
| Main LC `$D000` bank 1 | 4 KB | renderer X-code: node and seg fetchers, sprite fetch |
| Main LC `$D000` bank 2 | 4 KB | tic X-code: thinker walk, hot map queries chosen by profile |
| Aux zero page and stack | 512 B | drawer direct page |
| Aux `$0200-$1FFF` | 7.5 KB | status-bar background (5,120 B), fuzz tables, patch staging |
| Aux `$2000-$9FFF` | 32 KB | SHR |
| Aux `$A000-$BFFF` | 8 KB | nibble tables for the 8 palettes in use |
| Aux LC | 16 KB | replay, texture, fill and fuzz row blocks (about 8 KB), colormap page cache (8 KB) |

Colormaps are 17,408 bytes upstream. The cache holds 16 light levels for both row parities. A frame that needs more splits its replay into two batches.

Fallback: keep `fullcolormap` (8.7 KB) plus two 256-byte tables and pay one more indirect per pixel, about 1.3 ms per frame.

### Translated code size

Estimated from the addressing-mode counts in the brief.

| Class | Sites | Bytes each **(A)** | KB |
|---|---|---|---|
| Implied and accumulator | 14,775 | 3.5 | 52 |
| Near absolute | 8,631 | 9 | 78 |
| 16-bit immediate | 8,151 | 7 | 57 |
| Direct page | 6,279 | 6 | 38 |
| Long | 4,678 | 7 | 33 |
| `[dp]`, `[dp],y` | 2,872 | 6 | 17 |
| Other | about 13,000 | 2.5 | 33 |
| Total, naive | | | about 308 |

Fusion should bring this to about 250 KB. Only the hot set is resident. The rest lives in six PSRAM banks and is loaded as overlays.

### Extended banks (`$C073` values)

| Banks | Contents |
|---|---|
| 0 | base aux |
| 1-6 | code overlay store |
| 7-8 | cold near data, far BSS, weapon profiles |
| 9-14 | zone (256 KB) |
| 15-19 | resident WAD |
| 20-24 | RECIP, LOGTAB, SINE |
| 25-27 | FSTEP |
| 28-33 | sprite scale tables, sight and move tables, vertex-angle cache, COLDIR |
| 34-37 | sound and music data |
| 38-69 | level window (about 1.5 MB) |
| 70-126 | level store cache for the current and next map |
| 127 | unused (not an amem endpoint) |

### Tables

| Table | Upstream | Decision |
|---|---|---|
| SQL/SQH | 512 KB | deleted; exact 16x16 from 8x8 quarter squares, 2 KB fast, about 200 cycles; results identical because both are exact |
| T (byte products) | 1.5 KB | merged into the same 2 KB |
| FSTEP | 128 KB | PSRAM; read once per textured column (`[U]src/iigs/r_seg65.s:1920-1945`) |
| RECIP, LOGTAB, SINE | 64 KB each | PSRAM, each split over two banks; a helper picks the bank from the index |
| tantoangle, finetangent | about 14 KB | PSRAM, in the same bank as RECIP's first half |
| Sprite scale tables | 32 KB | PSRAM |
| Colormaps | 17.4 KB | fast, page cache |
| Nibble tables | 16 KB | fast, palettes in use only |
| Records | up to 53,760 B | fast, packed lists capped at 8 KB; overflow triggers the existing early flush |
| Fill spans, covered ranges | 3 KB | fast |

### amem use

- **Per frame:** one request loads 12 KB of tic code into window W, about 4.3 ms. Records and stage are regenerated each frame, so they are never saved.
- **On demand:** overlay loads of 4 to 12 KB, colormap page fills, level load, large block moves.
- **Never:** SHR updates (PRIVATE writes are invisible to the display), zero page, stack or language card (not valid endpoints).

## 4. Renderer and presentation

### Record production

- The 13 seg column loops (`[U]src/iigs/segvar.inc:27-80`) already run with 8-bit A. They are hand-ported with the column in real X and byte-planar clip arrays.
- A record is addressed through a zero-page pointer with `ldy #field / sta (rec),y`.
- The record keeps the upstream fields (`[U]src/iigs/r_seg65.s:1596-1650`), so record lists can be compared with the reference.

### Texel gather

- State: RAMRD on, RAMWRT off, code in main LC.
- Records are grouped by texel bank. For each record, only the texels it will step through are copied into the stage, and the record's source pointer is redirected to the stage.
- A batch ends when the 4 KB stage is full. E1M1 idle needs about three batches **(A)**.

### Shade and store

- State: RAMRD off, RAMWRT on, bank 0, ALTZP on, code in aux LC.
- Texture row, even: `tya / adc SI+1 / and #$7F / tay / lda (SRC),y / sta CMA / lda (CMA) / sta row,x`, 27 cycles.
- Texture row, odd: adds `lda TF / adc SF2 / sta TF`, 36 cycles.
- This matches the upstream cost, because the row blocks are already 8-bit (`[U]tools/gendraw.py:66-79`).
- Fill rows hold the two bytes in A and Y: `sta row,x / sty row+160,x`, 5 cycles per row and 3 bytes per row.
- Entry is a computed jump. Exit is the upstream opcode patch; the blocks are in the write-enabled aux LC, so RAMWRT does not redirect the patch.
- No `$Cxxx` access occurs inside a batch, so the mirror drains while the CPU shades.

### Fill spans, covered ranges, weapon skip

Kept exactly. They cut SHR bytes, which are the hard floor on this hardware.

### 2D

- There is no back buffer. Patches are drawn straight into SHR by a hand-written drawer with RAMRD on and bank 0, so the read-modify-write sees the screen.
- Patch data is staged into aux `$0200`. The status-bar background is copied aux to aux.
- The compiled HUD text code is kept as generated code in aux LC.

### SHR bytes per frame **(A)**

| Case | Bytes | Drain |
|---|---|---|
| E1M1 idle, same weapon, fills reused | 12,000 | 10.8 ms |
| Moving or turning | 18,000-22,000 | 16-20 ms |
| Status bar or HUD change | 200-600 | under 1 ms |
| Full redraw | 32,000 | 29 ms |

### Tearing

- The display publishes a frame at line 0 from its capture. A replay in progress shows a vertical seam between new and old columns for one displayed frame.
- Default: no wait, for frame rate.
- Option: start the replay at line 0. This costs 8 ms on average and is seam-free only while the replay fits one field.

## 5. Platform layer

| Area | Plan |
|---|---|
| Boot | ProDOS `DOOM.SYSTEM`, reusing the loader, bank sizing and installer in `[SW]src/kernel/loader.s` |
| Disk layout | ProDOS `.hdv` built by `[SW]tools/build_disk.py`; bank images as A2DM files; the level store is one contiguous file |
| Runtime disk | the loader records the store's first block and the settings block, then ProDOS is abandoned; level loads use SmartPort block reads into main RAM, then amem into PSRAM |
| Input | `$C000`/`$C010` keyboard, Open and Closed Apple, mouse card in slot 2 for turning and fire, USB joystick through the paddle ports; polled once per tic; `keyTable` rebinding kept |
| Clock | mouse-card VBL IRQ with the 7/10/12 accumulator from `[SW]src/kernel/frame.s`; the amem STATUS microsecond counter is used for profiling only |
| Sound | stage 1 silent stubs behind the upstream sound API; stage 2 effects as AY tone and noise envelopes; stage 3 music converted offline from MUS to AY register streams |
| Sound timing | all slot-4 writes go in one burst per VBL, because each access forces 1 MHz for a window |
| Saves | upstream level-start snapshots in one settings block, written with a SmartPort block write |
| IRQ | vectors in both main and aux LC; the handler reads `$C013`/`$C014`/`$C016` and restores switch state |

## 6. Performance estimate, E1M1 idle

Assumptions:

- The cost model above.
- Upstream executes 3.0 M 65816 cycles per frame (brief). The split by phase is my assumption.
- 4 tics per frame.
- 420 texture records and 12,000 texture pixels per frame.
- 120 BSP nodes and 150 segs visited.
- About 100 thinkers.

The 3.0 M figure includes ZipGS write stalls, so treating it as executed cycles is conservative.

| Phase | Upstream cycles | Factor | 65C02 cycles | CPU ms | Memory and I/O ms | Total ms |
|---|---|---|---|---|---|---|
| Tics x4 | 400 K | 2.2 | 880 K | 14.1 | thinker walk 0.8; 1,200 M-code far visits 5.4; window load 4.3 | 24.6 |
| Frame setup, BSP, wall setup | 900 K | 2.2 | 2.0 M | 32.0 | 270 node/seg fetches at 12 us, 3.2; 1,500 table reads at 2.5 us, 3.8 | 39.0 |
| Seg loops and records | 600 K | 1.3 | 780 K | 12.5 | 260 column-pointer and FSTEP reads, 1.2 | 13.7 |
| Sprites, masked, weapon | 300 K | 2.0 | 600 K | 9.6 | 300 far visits, 1.4 | 11.0 |
| Gather | none | | 195 K | 3.1 | 1,900 line misses 1.9; switches 0.1 | 5.1 |
| Shade and store | 600 K | 0.95 | 570 K | 9.1 | drain floor 10.8, overlapping the CPU | 11.5 |
| 2D, colours, finish | 150 K | 2.0 | 300 K | 4.8 | 0.5 | 5.3 |
| IRQ, input, sound | | | | 3.0 | 0.5 | 3.5 |
| **Total** | 2.95 M | | 5.3 M | 88 | 26 | **about 114 (8.8 FPS)** |

Sensitivity:

| Case | Frame | FPS |
|---|---|---|
| Nominal | 114 ms | 8.8 |
| 20 ns per cycle, factor 3.0 (no fusion), far visits doubled | about 205 ms | 4.9 |
| Translated only: no X-code, no hand-written loops, per-record bank switching | about 350 ms | about 3 |
| 13 ns per cycle, SHR stall removed by firmware | about 85 ms | 11.8 |
| Combat, 2,000 far visits per tic left in M-code | +36 ms | 6.7 |

## 7. Verification strategy

| Tool | Purpose |
|---|---|
| Our 65816 assembler back end | reproduce the release image bytes in `.../scratchpad/release/doom-hd.hdv`; proves the front end |
| `ref816`, a small C 65816 emulator with configurable layout | reference semantics; runs the original layout and the relinked layout |
| GSSquared | cross-check `ref816` against the release image: screenshots and READMEM at breakpoints |
| `a2fast`, a C 65C02 emulator with the Appletini map | differential testing at speed |
| `a2fast` timing mode | models the line cache, `$Cxxx` cost, mirror drain and amem; predicts ms per frame |
| `[SW]tools/a2sim.py` | kept for kernel tests and screenshots |

Method:

- The translator emits sync labels at function entries and loop heads. Both emulators run the same demo input; registers and a memory digest are compared at each label.
- Hand-written parts are compared at data level: record lists per frame, and SHR bytes against the reference bank `$01` buffer.
- In the relinked layout, `$0000-$01FF` and `$C000-$FFFF` of every data bank trap in `ref816`. This finds hidden 64 KB assumptions.
- Debug builds assert the profile-derived facts: index below 256, stack depth, M/X at entry.
- Hardware: microbenchmarks calibrate the timing model; per-phase timing uses the ARM microsecond counter.

## 8. Milestones

| # | Deliverable | Test | Time **(A)** |
|---|---|---|---|
| 0 | Hardware microbenchmarks: BRAM cycle, PSRAM miss, `$Cxxx`, SHR drain, amem per byte and per request | numbers replace the cost model | 3-5 days |
| 1 | Front end parses all files and macros | instruction counts match the brief | 1 week |
| 2 | Assembler back end | release image bytes match | 2 weeks |
| 3 | `ref816` runs boot to demo3 | frames match GSSquared; profile produced | 2 weeks |
| 4 | Replay machine on hardware, fed with record dumps from the reference | correct image; measured ms per frame | 2 weeks, parallel |
| 5 | Translator v1, all M-code; math, zone, WAD | differential tests pass in `a2fast` | 4 weeks |
| 6 | Game logic | demo3 state digests match for every tic | 4 weeks |
| 7 | Renderer record production | record lists and frames match | 4 weeks |
| 8 | First playable on hardware | measured FPS against section 6 | 1 week |
| 9 | Placement tuning, X-code, fusion | 8 FPS on E1M1 idle | 3 weeks |
| 10 | Menus, status bar, automap, intermission, saves, input | manual and scripted tests | 3 weeks |
| 11 | Sound effects, then music | listening tests; FPS cost under 3% | 3 weeks |
| 12 | All nine maps, soak | no crash over long play | 2 weeks |

## 9. Risks

| Rank | Risk | Mitigation |
|---|---|---|
| 1 | Hot code and data exceed fast memory, so more is swapped per frame | profile-guided placement; fusion; window W can rotate a second time at 4.3 ms; firmware item 3 |
| 2 | Cost model wrong (cycle time, amem overhead, admission wait) | milestone 0 before any design is frozen |
| 3 | Far visits in combat far above the idle estimate | promote map-query routines to X-code; 8-byte alignment; measure with `a2fast` |
| 4 | M/X, DBR or D inference error | run-time check of every executed instruction in `ref816` |
| 5 | Hidden 64 KB bank arithmetic | trapping layout in `ref816`; hand-written zone and WAD address code |
| 6 | 256-byte hardware stack overflow | stack profile; explicit BSP stack; software frames |
| 7 | X-code variables must live in the language card or zero page, and space runs out | constraint checked at build; the two `$D000` banks are split by phase |
| 8 | SHR drain worse than 0.9 us, or VBL IRQs stall on it | fewer bytes through upstream's reuse logic; firmware item 1 |
| 9 | Hand-written volume (about 5,000 lines) | data-level comparison with the reference for each piece |
| 10 | Sound's 1 MHz windows cost more than 3% | one burst per VBL; sound off option |
| 11 | amem failure mid-batch is not atomic | crash screen; never retry |
| 12 | Licence | `cal_integer.s` replaced, not translated; upstream is not stored in the repository |

## 10. Firmware wish list

### Effect of the three changes under discussion

| Change | Effect on this design |
|---|---|
| (1) Multi-line cache, possibly DDR | far misses become cheap; code can run from extended memory; overlays and the per-frame window load go away (about 4-10 ms); 8-byte alignment matters less |
| (2) Bank and soft-switch writes that skip the bus and keep the caches | an M-code far read drops from 4.5 us to under 1 us; the X-code class and batching by bank become unnecessary; about 10 ms saved idle, more in combat |
| (3) Separate read and write bank registers | the gather pass and stage disappear; the replay reads texels and writes SHR in one pass; saves about 5 ms and 4 KB; bank-to-bank copies need no bounce buffer |

### Ranked wishes

| Rank | Wish | Benefit |
|---|---|---|
| 1 | Option to defer the SHR motherboard mirror like hidden pages, flushing only at handback | removes 11-20 ms per frame |
| 2 | Change (2) | about 10 ms and a simpler translator |
| 3 | Change (1) | removes swaps and the code-placement risk |
| 4 | Change (3) | single-pass replay |
| 5 | Multiply register served inside the fabric (16x16 to 32) | multiply from about 200 cycles to about 30; several ms in BSP and wall setup |
| 6 | Visible-SHR amem copy | tear-free presentation from a private buffer |
| 7 | amem endpoints in zero page, stack, language card and bank 127 | simpler overlays |
| 8 | Microsecond counter readable at a fabric-served address | cheap profiling and clock |
| 9 | Shorter slot-4 slow window | lower sound cost |