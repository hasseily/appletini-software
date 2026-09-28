# Design proposal: incremental port of Webifi IIgs DOOM to the Appletini 65C02

Path legend: `[UP]` = `<upstream>`, `[SW]` = `<appletini-software>/demos/doom`, `[FW]` = `.../scratchpad/appletini-one-main`, `[REL]` = `.../scratchpad/release/doom-hd.hdv`.
"Verified" means I ran the grep or parse in this session. "Per report" means the cite comes from a research report. No files were created or modified.

## 1. Architecture summary

The port is a small virtual 65816 machine ("V816") hosted by our existing kernel. It has three execution tiers that share one register file, one soft stack and one far-memory layer.

- **Tier 0, interpreter.** A 65816 interpreter in the main language card runs upstream code assembled at build time, by our own assembler, from the pinned clone. It stands in for everything not yet native, so the whole game runs early and slowly.
- **Tier 1, translated native code.** The same front end emits 65C02 for functions a profile marks hot. Substitution is by virtual entry address.
- **Tier 2, hand-written 65C02.** Record replay and presentation, multiply/divide, B1 decoder, memory moves, input, clock, disk block I/O, AY sound and music.

Far data keeps upstream's 24-bit addresses. A 128-entry table maps each virtual 32 KB half-bank to a RamWorks bank at `$4000-$BFFF`; banks `$00`, `$01`, `$02` use page tables. Virtual bank `$01` is base aux, so upstream 2D code draws straight to SHR.

The replay keeps upstream's column records, row blocks, fill spans and dither colormaps. It runs in three passes per column because RAMRD and RAMWRT share `$C073`.

Reused: ProDOS loader, A2DM bank files, `far.s`, `amem.s`, `input.s`, VBL clock, profiling mailbox, disk builder, harness. Retired: the cc65 game, our renderer, `wad2a2.py`, the phase swap.

Expected speed on today's firmware: about 0.8 FPS interpreted, 3.5 to 4 FPS after native translation and a software page cache. All instruction counts behind that are assumptions until milestone M1 measures them.

## 2. Translator design

### 2.1 Front end (shared by assembler, interpreter image and native emitter)

| Stage | Design |
|---|---|
| Preprocessor | Own Python implementation of `#include/#define/#undef/#if`. A system `cpp` is unsafe because `##` is the 16-bit immediate prefix and would be read as token paste. |
| Macros | Calypsi `.macro/.endm` with `\a` parameters. I count 131 `.macro` lines (verified; the brief counts 105 macros). |
| Labels | `N$` locals scoped between non-local labels. 4,311 labels (verified by script). |
| Sections | Names kept; 44 text section names (verified). Placement is ours, not Calypsi's. |
| Expressions | `.byte0/1/2`, `.word0/2`, `.tiny`, `.near`, `.kbank`, `.sectionStart/End/Size`. |
| Output | One IR record per instruction: mnemonic, operand, mode, section, and inferred M, X, D, DBR. |

**Front-end check.** A 65816 encoder assembles every fragment and matches it against the release image, with operand bytes as wildcards. The release stores program segments uncompressed, for example `$03:0000` for 89,600 bytes and `$02:0000` for 30,208 bytes (verified by parsing block 1 of `[REL]`). A match gives each fragment's upstream address and the wildcards give the address of every referenced symbol. This recovers the upstream link map without Calypsi. Assumption: the v1.0 release was built from commit `8ea2eac` with default options.

### 2.2 M/X, direct page and data bank inference

- **M/X.** Forward data-flow from `rep/sep` (1,107 sites), entry default M=0, X=0 (`[UP]src/iigs/crt0.s:37` per report). Every immediate is ground truth (`#` 8-bit, `##` 16-bit); a disagreement is a build error.
- **D.** Static, from the `tcd/tdc` sites (25, verified) and `phd/pld`. Functions reached under D=`$0A00` get a WPAGE variant.
- **DBR.** Static from `phb/plb/pea` patterns. Where it is computed (`P_RunThinkers`, `[UP]src/iigs/p_tick65.s:106-227` per report) `abs,x` becomes a far access with the bank in `rDBR`.
- **Dynamic cross-check.** The interpreter, run in the host emulator over demo playback, logs (virtual PC, M, X, D, DBR). Static inference must agree with every logged fact. Sites never executed are listed and stay interpreted.

### 2.3 Register model and flags

| 65816 | 65C02 home |
|---|---|
| A (M=0) | `rA`, `rB` in zero page; hardware A is scratch, and the emitter tracks which byte it holds |
| A (M=1) | hardware A; B stays in `rB` |
| X, Y (X=0) | `rX/rXh`, `rY/rYh` in zero page; hardware X/Y are scratch and index carriers |
| X, Y (X=1) | hardware X/Y (13 `sep #$10` sites, nearly all in the replay, which is hand-written) |
| S | `rS`, a physical pointer into the soft stack |
| D, DBR | static in native code; `rD`, `rDBR` for the interpreter |

C and V live in hardware P. The high byte is always processed last, so C, V and N are right after a 16-bit operation. Z reflects only the high byte, so a flag liveness pass adds a fix only where Z is live: `ora rA` (2 bytes, 3 cycles). Equality tests become a short-circuit low/high compare. Decimal mode is never used.

### 2.4 Addressing modes and emitted code (M=0, `lda` as the example)

| Mode (static sites) | Emitted 65C02 | Bytes | Cycles | 65816 bytes/cycles |
|---|---|---:|---:|---|
| 16-bit immediate (8,151) | `lda #>v / sta rB / lda #<v / sta rA` | 8 | 10 | 3 / 3 |
| 8-bit immediate (2,197) | `lda #v` | 2 | 2 | 2 / 2 |
| direct page (6,279) | `lda z+1 / sta rB / lda z / sta rA` | 8 | 12 | 2 / 4 |
| `.near` / abs, fast home (8,314) | same with absolute operands | 10 | 14 | 3 / 5 |
| `.near,x` (317), `long,x` (1,610), fast home | 16-bit add into `fp`, then `(fp),y` twice | 23 | about 40 | 4 / 6 |
| `long:` static, far home (3,068) | `jsr fs_rd16` + 3-byte address | 6 | far cost, section 3 | 4 / 6 |
| `[dp],y` (2,620), `[dp]` (252) | `jsr fp_rd16y` + pointer byte | 4 | far cost | 2 / 7 |
| stack relative (316) | `ldy #n+1 / lda (rS),y / sta rB / dey / lda (rS),y / sta rA` | 11 | 19 | 2 / 5 |
| implied (14,775) | `asl rA / rol rB`; `inc rX / bne / inc rXh`; `tax` as four moves | 4 to 8 | 7 to 12 | 1 / 2 |
| `xba` (620) | M=1: `ldy rB / sta rB / tya` | 5 | 8 | 1 / 3 |
| `rep/sep` (1,107) | nothing, unless other P bits change | 0 | 0 | 2 / 3 |

Weighted by the static mix, native code is about 7.2 bytes and 18 to 22 cycles per source instruction (my estimate). The release holds about 186 KB of program bytes in banks `$00` and `$03-$05`, block-rounded, including padding and some bank-0 data (verified from the header). A fully native build would be about 350 to 420 KB. That cannot fit in fast memory, which is why tier 0 exists.

### 2.5 Calls, returns and the stack

Upstream reads its own frames as bank-0 memory: `tsc / tax / lda long:TT,x` (`[UP]src/iigs/p_map65.s:343-346`, also `461-465`, `941-947`, verified). So S must remain a real address and frame offsets must not move.

- **Soft stack.** `rS` tracks the 65816 S byte for byte. Virtual `$00:0B00-$3FFF` maps at a constant offset to fast main memory. `tsc` and `tcs` convert; they are rare.
- **Native calls use holes.** `jsr` lowers `rS` by 2 (`jsl` by 3) and then does a hardware `jsr`. The return address sits on the hardware stack and the soft stack keeps an unused hole of the right size. Every `n,s` offset and frame size is unchanged. Cost is about 14 bytes and 17 cycles per call and per return.
- **Flags across returns.** The adjust uses `ldy/dey/sty`, which leaves C and V alone. `php/plp` is added only where a caller tests N or Z after the call.
- **Release option.** Holes are elided for callees proven not to read above their entry S. Verification builds keep them so S stays bit-identical.
- **Interpreted code** pushes real virtual return addresses, exactly as a 65816.
- **Private tic stack** (`[UP]src/iigs/p_think65.s`, `LOGIC_SP .equ 0x1b6f`, verified) works unchanged because only `rS` moves.
- **Hardware stack depth** is 256 bytes. BSP recursion uses 2 bytes per level. The high-water mark is measured at M3.

### 2.6 Function pointers, jump tables, MVN

| Construct | Sites | Handling |
|---|---:|---|
| `JML [dp]` as `.byte 0xdc` | 8 (verified: `p_path65.s:816`, `p_map65.s:2786, 2869`, `p_pspr65.s:118`, `p_tick65.s:533`, `patch65.s:381`, `r_sprite65.s:398, 1787`) | Pointers stay virtual. `vcall_ind` looks the target up in the native entry table, else enters the interpreter. |
| `jmp (abs,x)` / `jsr (abs,x)` | 18 / 14 (per report) | Table re-emitted with native addresses when all targets are native, else virtual dispatch. |
| MVN as `.byte 0x54` | 33 (verified: `r_list65.s` 14, `loader.s` 5, `m_menu65.s` 4, `s_sound65.s` 3, `w_level65.s` 3, five files with 1) | `jsr vmvn` + two bank bytes. Splits at 32 KB granules. Uses amem COPY for 1 KB or more between legal endpoints, amem FILL for the overlapping-fill idiom, else `far_copy`. |

### 2.7 Self-modifying code

Detection has two sources. Static: my script finds 85 stores onto 31 instruction labels in text sections, and 115 more onto data kept inside text sections (rough; local labels not resolved). Dynamic: the interpreter flags every write into a code section with writer PC and target.

| Class | Examples | Handling |
|---|---|---|
| Operand patch | `sta long:(ssUpStart+1)` `r_seg65.s:967-971`; `p_path65.s:1107, 1115`; `p_trace65.s:1852, 1865` (verified) | Native: the operand becomes a named cell and the store is rewritten. Interpreted: works as is. |
| Opcode patch | row-block exits `$6C/$60/$EB` (`r_list65.s:737-748`, verified) | Hand-written replay. |
| Code installed by MVN | `pairMake`, `c16Mode`, `c19Install`, view-size images | Hand-written or not shipped; full view first. |
| Run-time generated code | `IIGS_TextCode` (`patch65.s:279-383` per report) | Stubbed so text is drawn by `IIGS_DrawPatch`. Assumption: that fallback path exists. |

### 2.8 Constructs that cannot be translated mechanically

| Construct | Sites | Replacement |
|---|---:|---|
| `xce` and emulation-mode firmware calls | 12 (verified: `loader.s` 5, `m_config65.s` 3, `w_level65.s` 3, `crt0.s` 1) | Kernel disk and boot code |
| `tsc/tcs` | 39 outside `cal_integer.s` by my line-start grep (brief: 54 in total) | Classified as frame, stack switch or return discard; reviewed by hand |
| Return-frame discard | 1 (`m_menu65.s:2439-2457`, verified) | Hand patch in native form; exact when interpreted |
| IIgs hardware registers | 206 uses of 27 addresses outside boot and loader (verified); `irq65.s` 63, `i_doc65.s` 39, `iigs_asm.s` 24 | Platform overrides |
| Quarter-square tables | 112 references (verified) | Macro-level override calling a hand-written multiply; the 512 KB of tables are dropped |
| `cal_integer.s` | 46 call sites to 5 routines: `_Div16`, `_Div32`, `_UDivMod32`, `_UDivMod16`, `_Mod16` (verified) | Our own routines; the file is never assembled or shipped |
| ZipGS / TransWarp GS code | in `m_menu65.s`, `iigs_asm.s` | Stubbed |

### 2.9 Build pipeline and substitution

1. Clone upstream at pinned `8ea2eac` into `build/upstream`, as `[SW]/../bilestoad/build.py` does.
2. Run upstream's Python data tools from the clone to make the resident WAD, level store and tables. Check them against the release segments at `$10:0000`, `$1F:0000` and `$40:0000`.
3. Front end to IR.
4. Apply `port/overrides.json`. Each entry names an upstream label range or macro, a content hash, the replacement symbol and its register and memory contract. This follows `bilestoad/src/drops.json`.
5. Emit the 65816 image, the ca65 source for native functions, the native entry table and the map table.
6. Assemble hand-written sources with ca65/ld65; build the disk.

Nothing from upstream, and nothing generated from it, is committed.

## 3. Memory model

### 3.1 Fast memory

| Range | Size | Use |
|---|---:|---|
| main `$00-$FF` | 256 | V816 registers (16), virtual direct page `$0900` (211 bytes of `registers` + `ztiny`, verified), kernel (24). `$42-$47` saved around block-driver calls. |
| main `$0100-$01FF` | 256 | hardware stack |
| main `$0200-$03FF` | 512 | kernel variables; WPAGE variables that are not pointers |
| main `$0400-$0BFF` | 2 KB | immutable tables and code (mirrored window) |
| main `$0C00-$1BFF` | 4 KB | replay TEX/OUT buffers, clip arrays, fill-span and covered tables |
| main `$1C00-$5FFF` | 17,408 | SHR colormaps A and B, 34 pages each; written once per level |
| main `$6000-$BFFF` | 24 KB | hot near-data pages 10 KB, native code 8 KB, page cache 4 KB, soft stack 2 KB (initial split; profile-driven) |
| main LC bank 1 `$D000` | 4 KB | replay gather blocks, record walker, fuzz |
| main LC bank 2 `$D000` | 4 KB | interpreter part B, disk I/O, crash screen |
| main LC `$E000-$FFFF` | 8 KB | far layer, interpreter core, trampolines, IRQ, AY driver |
| aux `$0200-$1FFF`, `$A000-$BFFF` | 15.5 KB | virtual bank `$01` data: fuzz tables, status bar cache; profiling mailbox at `$A000` |
| aux `$2000-$9FFF` | 32 KB | SHR pixels, SCBs, palettes |
| aux LC | 16 KB | reserve |

Direct-page variables used as pointer bases get real zero page first; WPAGE overflow becomes absolute.

### 3.2 Virtual to physical

| Virtual | Physical |
|---|---|
| `$00` | page table: stack to soft stack, direct pages to zero page, code to the image banks |
| `$01` | base aux, identity addresses (the back buffer is the screen) |
| `$02` near data | upstream addresses kept; 256-entry page table; hot pages in main, the rest in one RamWorks bank |
| `$03-$05` | 65816 image, 6 half-banks |
| `$06-$0D` | zone, tables, far BSS: 16 half-banks |
| `$10-$12` | resident WAD, 6 |
| `$13-$1A` | not mapped |
| `$1B-$26` | step, records, reciprocal, log, sine, misc: 24 |
| `$27-$29` | not mapped (DOC sound) |
| `$2A-$3F` | level window, 44 |

That is about 97 RamWorks banks. Each also has a 15.5 KB annex at `$0200-$3FFF`. The annexes plus 29 spare banks hold the 1.82 MB compressed level store (verified size) and the native images. Banks 1-126 only, because amem excludes 127.

Rule: `phys_bank = MAP[2*vbank + bit15]`, `phys_hi = (hi & $7F) + $40`. Every access computes its own effective address, so an object that straddles `$8000` is still correct. Assumption, from upstream's own rule: no pointer-plus-index crosses a 64 KB bank.

### 3.3 Far access cost

| Implementation | CPU cycles | `$Cxxx` accesses | Time per access |
|---|---:|---:|---|
| F0 toggled, reusing the `far.s` pattern | about 95 | 2, plus 1 on bank change | about 6 µs |
| F2 software page cache, hit | about 55 | 0 | about 0.9 µs |
| F2 miss, clean page | about 3,400 | 3 | about 90 to 120 µs |

Inputs: 60 M cycles/s, 1.5 µs per bus access (`[FW]README_VIRTUAL_TRANSWARP.md:110`), 1 µs per line miss. F2 is per bank: structured data is cached, random-access tables stay on F0. Both sit behind one API.

### 3.4 amem use

- Boot: install native images.
- `vmvn` and `IIGS_CopyHuge`: level loading, view save for the greyed menu.
- Page-cache flush and preload at level start.
- Optional: swap 8 KB native overlay groups by phase. v12 measured about 2.6 MB/s, so about 3 ms per swap.
- Never for visible SHR, because PRIVATE writes are invisible to the display (`[FW]README_MEMORY_API.md:173-188`).

## 4. Renderer and presentation

**Kept from upstream.** Record kinds and layout in virtual bank `$1D` (`[UP]src/iigs/lists.inc:1-30`, verified), fill spans, covered ranges, weapon skip, the two 34-page colormaps, per-row unrolled blocks with patched exits, and even/odd row pairing.

**Per-column replay, three passes.**

| Pass | Switch state | Work | Cycles per row |
|---|---|---|---:|
| Gather | RAMRD on, `$C073` = texel bank, code in LC | step, `lda (SRC),y`, `sta TEX+r` | 18 even, 27 odd |
| Shade | all off, main | `ldy TEX+r / lda (CM),y / sta OUT+r` | 13 |
| Write | RAMWRT on, `$C073`=0 | fills `sta row,x`; then `lda OUT+r / sta row,x` | 5 fill, 9 texture |

- A textured row costs about 45 cycles. Upstream's is about 33.5 65816 cycles (per report).
- Overdraw happens in OUT, so each screen byte is written once per frame.
- Fills use two chains, even and odd rows, because the 65C02 has no `sty abs,x`.
- Fuzz preloads OUT from the screen for its rows.
- Bus accesses: about 3 per column and 2.3 per texture record, so about 1,900 per frame, about 3 ms.

**SHR bytes per frame.** At most 26,880. Assumption for idle E1M1: about 13,000, since fills are reused. At about 1 µs per byte of mirror drain, the replay takes 13 to 27 ms and is drain-bound.

**Tearing.** Upstream does not sync. A line-0 snapshot taken mid-replay shows one vertical seam for one field. Option: start after line 0, as `present` does now (`[SW]src/kernel/video.s:189-267` per report). That costs about 8 ms average wait and is only tear-free under about 15,000 bytes.

**2D.** Upstream code draws into virtual bank `$01`, which is the screen. `markRect` and `showDirty` become empty overrides.

**To confirm at M0.** Standard 320-mode with per-row SCB palettes on the Appletini. Our Doom port uses PAL256 only; Bilestoad uses 320 mode.

## 5. Platform layer

| Existing piece | Decision |
|---|---|
| `loader.s`, A2DM files, `build_disk.py`, `build_banked.py` | Reused; about 22 files against a 51-entry directory |
| `far.s`, `amem.s` | Reused; `far.s` becomes F0 |
| `input.s`, `frame.s`, `kstart.s` IRQ | Reused |
| `profile.s`, `profile_hardware.py` | Reused, with upstream PHASE numbers |
| `a2sim.py`, `run_doom.py`, tests | Reused; API kept over a C core |
| `gamebanks.s`, `space.s` | Retired |
| `video.s` | Replaced by standard-SHR init and the replay |
| `src/game`, `src/render`, `wad2a2.py`, `refrender.py` | Retired |

- **Boot.** `DOOM.SYSTEM` loads all banks, installs the LC and main images, then starts the kernel. Reciprocal and step tables are generated at build time and checked against a GSSquared dump. The level store stays in RAM, so there is no disk read at level change. The hand-written B1 decoder should load a map in about 2 to 3 s (estimate).
- **Input.** Our keyboard, Open/Closed Apple and mouse code synthesises the key codes that `I_StartTic` reads from its ring (`[UP]src/iigs/i_iigs65.s:98-237` per report). The //e reports one key at a time. USB paddles are a later option.
- **Clock.** `I_GetTime` returns the 35 Hz count from the mouse-card VBL IRQ.
- **Sound.** All DOC code is overridden. Effects become short AY envelopes built at build time from the WAD samples. Music is converted at build time from the clone's `data/music/*.mus`. One burst of changed registers per VBL. Each burst triggers the slot-4 1 MHz window of 512 Apple cycles (per hardware report), so about 0.6 to 1 ms per tick, 3 to 6 percent of CPU at 60 Hz.
- **Saves.** Upstream saves are level-start snapshots in one settings block. The loader reads it; at run time the kernel writes it through the slot-7 block driver, using a block number recorded by the disk builder. Assumption: the driver is callable from our context; its `$07F8` write is harmless.

## 6. Performance estimate, E1M1 idle

Assumptions:

- A1: 60 M cycles/s for code in BRAM. Measured mix is about 42 M/s; nominal is 75 M/s.
- A2: far costs as in 3.3.
- A3: **unmeasured** upstream instructions per frame: 4 tics 120K, setup/BSP/walls/segs 200K, sprites and masked 50K, 2D 30K.
- A4: 12 percent of those are far accesses (static share is 12.9 percent).
- A5: native 20 cycles per instruction, interpreter 150.
- A6: about 13,000 texture rows, about 600 records.

| Phase | T0 interpreter, F0 | T1 90% native, F0 | T2 97% native, F2 at 99% hits |
|---|---:|---:|---:|
| Game tics | 386 ms | 152 | 78 |
| Setup, BSP, walls, segs | 644 | 254 | 130 |
| Sprites, masked, weapon | 161 | 64 | 33 |
| 2D, finish | 97 | 38 | 20 |
| Replay | 15 | 15 | 15 |
| IRQ, sound | 8 | 8 | 8 |
| **Total** | **about 1,310 ms, 0.8 FPS** | **531 ms, 1.9 FPS** | **284 ms, 3.5 FPS** |

Hand-written seg loops and thinker loop should remove about 40 ms more: about 245 ms, 4.1 FPS. The error band is wide, mainly because A3 is a guess. Below 8.75 FPS the 4-tic cap slows game time, as it does upstream and in our current port.

## 7. Verification strategy

| Tool | Purpose |
|---|---|
| 65816 encoder plus image match | Proves the front end; recovers the upstream symbol map |
| SingleStepTests 65816 vectors | Per-opcode tests for the interpreter and for each emitted sequence (assumption: downloadable at test time) |
| C emulator with `a2sim.Machine` API | Whole-game runs. Validated in lockstep against py65 on the existing port. Adds PSRAM line, bus-cycle and mirror-drain timing, calibrated to the v12 phase table. |
| GSSquared running `[REL]` | Reference dumps by debug socket at recovered addresses |
| Interpreter against native, in place | Same entry state, run both, compare registers and touched memory |
| Hardware mailbox | Per-phase times after each milestone |

Reference comparisons, in order: tables after init; zone, level window and near data after `P_SetupLevel`; game state per tic in demo playback; record bank before replay; screen bytes after a frame. Far pointers and near addresses are identical to upstream, so most are plain byte compares.

## 8. Milestones

| # | Deliverable | Test | Effort (estimate) |
|---|---|---|---|
| M0 | Hand-written replay on hardware, drawing one E1M1 frame from records, colormaps and texels dumped from GSSquared | Screen equals the GSSquared screen dump; replay ms and SHR bytes measured | days |
| M1 | Front end, 65816 encoder, image match, C emulator | Match rate; lockstep traces; real per-phase instruction counts replace A3 | 2 weeks |
| M2 | V816 kernel: registers, soft stack, F0, interpreter, platform stubs. Runs init to the title picture | Opcode vectors; table dumps equal | 2 weeks |
| M3 | Level load and first rendered frame, interpreted, shown by the M0 replay | Level memory and record bank equal the reference; static view on hardware | 1 to 2 weeks |
| M4 | Tics, input, clock; playable slowly | Per-tic state equality in demo playback | 1 to 2 weeks |
| M5 | Native emitter for the top functions; F2 page cache | In-place differential; 2 FPS, then 3.5 | 3 to 4 weeks |
| M6 | Status bar, HUD, menus, automap, intermission, tints checked | Screen compares | 1 week |
| M7 | AY effects and music | Register-stream tests; listening on hardware | 2 weeks |
| M8 | Settings and saves, nine-map soak, disk image | Hardware soak | 1 week |

The M0 fallback, if the capture is awkward, is a synthetic record set generated in Python.

## 9. Risks, ranked

| # | Risk | Mitigation |
|---|---|---|
| 1 | Speed falls short: far cost, or hot code does not fit 8 to 12 KB | Measure at M1 and M3; F2; overlays; hand tuning; firmware items |
| 2 | A3 is wrong by 2x | M1 measures it before any native work |
| 3 | Interpreter or emitter semantic errors | Opcode vectors; in-place differential |
| 4 | Release image does not match the source, so no symbol map | Build upstream once on any x86 machine for a listing; or compare by structure |
| 5 | Fast memory budget overflows | Profile-driven placement; colormaps already use the mirrored window |
| 6 | Hardware stack overflow | Measure at M3; spill deep recursion to the soft stack |
| 7 | Timing model mispredicts, as v5 and v6 did | Recalibrate against hardware at every milestone |
| 8 | Standard SHR with SCB palettes behaves differently | M0 tests it first |
| 9 | AY sound quality; slot-4 slowdown | One burst per tick; sound can be switched off |
| 10 | One key at a time on the //e | Mouse plus Apple keys; USB paddles later |
| 11 | Licence | `cal_integer.s` never shipped; disk images are GPL-2 derived works and need a source offer |

## 10. Firmware wish list

| Rank | Change | Effect on this design |
|---:|---|---|
| 1 | Bank and soft-switch changes that do not touch the bus or flush caches (item 2) | F0 drops from about 6 µs to about 2.6 µs. The page cache becomes optional. Replay switch cost disappears. T1 goes from about 1.9 to about 3 FPS. |
| 2 | Multi-line cache, or DDR, for extended memory (item 1) | Code can run from extended banks near BRAM speed. All code goes native; the interpreter leaves the frame path; no overlays or hot/cold near split. Estimate 6 FPS or more. |
| 3 | Separate read and write bank registers (item 3) | Replay becomes one pass, texel bank to aux 0, once the colormaps are reachable in that state. `far_copy` loses its bounce buffer. |
| 4 | amem copy that is visible to the display | Render the view into a private buffer and publish it in one hold: no tearing, no drain-bound replay. |
| 5 | amem endpoints in `$D000-$FFFF` and bank 127 | LC images installed by amem; one more bank. |
| 6 | Shorter or optional slot-4 slowdown window | Sound cost falls below 1 percent. |
| 7 | Memory-mapped microsecond counter | Exact hardware phase timing. |
| 8 | USB keyboard key-state register | Several keys held at once. |