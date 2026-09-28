# Design proposal: correctness-first port of IIgs DOOM to the Appletini 65C02

**Path legend.** `U/` = `<upstream>/`. `F/` = `.../scratchpad/appletini-one-main/`. `R/` = `.../scratchpad/research/`. `K/` = `<appletini-software>/demos/doom/`.

**Evidence labels.** "Measured" means I ran an in-memory prototype (clang preprocessor, macro expander, parser) over the 60 game sources plus the generated drawers; `boot.s`, `loader.s` and `cal_integer.s` were excluded. "Assumption" marks everything not verified.

**Disclosure.** One mistyped redirect created an empty file, `/tmp/null_err_38209`. I left it in place. Nothing else was created, modified or deleted.

## 1. Architecture summary

The port is a virtual 65816 machine (VM) on the 65C02, with two engines sharing one state.

- **State.** A, X, Y, S, D, DBR and flags live in host zero page. The 24-bit address space is kept as a virtual space, so pointers, structs, the WAD and the level store stay byte-identical to upstream. The 16-bit stack is fully software, at its original virtual addresses.
- **Interpreter engine.** A 65816 interpreter in 65C02 runs original machine code, which our own assembler produces from the local upstream clone at build time. It handles self-modifying code, run-time generated code and cold code with no special cases.
- **Translator engine.** Functions that pass static checks and have been executed under lockstep testing are translated by rule to inline 65C02. They run from fast memory.
- **Reference.** The release image decodes cleanly, and upstream states that a clean tree rebuilds it byte for byte (`U/Makefile:151-153`). Our assembler must reproduce its code bytes. That proves the front end and recovers the link map without Calypsi.
- **Order of work.** The whole game first runs interpreted, which is slow but needs no translator. Translation, then hand-written renderer kernels, replace interpretation function by function. Each replacement is checked in lockstep against a host 65816 core running the original bytes.
- **Platform.** Boot, disk, input, clock and sound are hand-written, reusing our kernel.

Estimated E1M1 idle speed: 0.35 FPS interpreted, about 1 FPS translated, about 2.7 FPS with native kernels, about 4.5 FPS with the three firmware changes.

## 2. Translator design

### Front end

| Stage | Design | Evidence |
|---|---|---|
| Preprocessor | `clang -E -P -x assembler-with-cpp` with `-D TICSTEP=1 -D MUSIC_MENU=1`; a pure-Python cpp is the fallback | Measured: 60 files, no errors |
| Macros | Expand `.macro/.endm` with `\arg` substitution, longest name first; rename `N$` labels per expansion (`R/calypsi-assembler-chapter.txt:503-512`) | Measured: 104 macros |
| Instructions | 67,235 instances after macro and include expansion, including 6,285 from `tools/gendraw.py` | Measured |
| Expressions | C precedence, `.byte0-2`, `.word0/2`, `.tiny`, `.near`, `.kbank`, `.sectionStart/End/Size` | Syntax chapter, sections 21.5 and 21.10 |
| Sections | Data sections keep upstream addresses from `U/src/iigs/iigs.scm` and `memmap.inc`; translated code has no virtual address | |
| Proof | Assemble each section fragment, locate it in the release image with relocation wildcards, then re-assemble with solved addresses and compare every byte | Release decode verified, see section 7 |

### M/X inference

- The only `rep`/`sep` operands are `#0x20` (992), `#0x30` (32), `#0x10` (32), `rep #0x21` (10), `sep #0x40` (3) and `rep #0x38` (1). All are constants (measured).
- Method: forward dataflow per flag over the control-flow graph, with lattice {8, 16, either}. Immediates (`#` or `##`) are hard evidence. Call sites unify with callee entry and return states. `php`/`plp` pairs are matched.
- "Either" is legal only until the next `rep`/`sep`. A width-dependent instruction that sees "either" is a build error.
- Prototype result, using strict unification:

| Measure | Result |
|---|---|
| M known | 64,965 of 67,235 instructions |
| X known | 57,969 of 67,235 |
| Width-dependent instructions with M unknown | 1,718 (980 in generated drawers, 528 in `i_snd65.s`, 210 elsewhere) |
| Function entries | 1,244 at 16/16, 49 with 8-bit A, 13 undetermined |
| Conflicts | 68, mostly joins that start with a normalising `rep`/`sep`, plus hand-assembled jumps |

- Expect about 50 to 100 one-line annotations. Functions that stay unresolved remain interpreted.
- Static results are checked three ways: against M/X observed per PC in the reference run, by run-time asserts in checked builds, and by lockstep.

### Direct page and data bank

- D is inferred the same way from `lda ##const / tcd` and `phd`/`pld`. Values in use are `$0900`, `$0A00` (WPAGE), `$0000` (firmware wrappers) and `B1DP` (`U/src/iigs/w_level65.s:1296`).
- `fixedDiv` uses D as a shift register: `lda ##1 / tcd`, then `tdc / rol a / tcd` (`U/src/iigs/p_trace65.s:430-431, 502-504`). This is mechanical because D is a real virtual register. The translator asserts that no dp operand occurs while D holds data.
- Each dp operand becomes a static physical address. The direct page is full: `ztiny` 235 bytes plus `registers` 20 (measured). It therefore cannot share host zero page with the VM registers. It maps to an absolute fast page, and profiling promotes hot cells into host zero page.
- `.near` operands mean bank `$02`; checked builds assert DBR. `abs:` operands use the run-time DBR, which is dynamic in `P_RunThinkers` (`U/src/iigs/p_tick65.s:106-117`).

### Register and flag model

| Item | Home |
|---|---|
| A and B, X, Y | Zero-page words `vA`, `vX`, `vY`; host A, X, Y are scratch |
| S | `vSP`, the physical address of virtual S |
| D, DBR | `vD` (word), `vDBR` (byte) |
| C | Host carry at every instruction boundary; address arithmetic wraps in `php`/`plp` |
| V | Host V directly after ADC/SBC; saved to a cell when liveness shows a later consumer (267 `bvc`/`bvs` sites, measured) |
| N, Z | Cells `vZl`, `vZh`, `vN`. Separate cells are needed because BIT and PLP can set N and Z together |
| M, X | Static. Checked builds also keep a byte |

Rules with traps: CMP leaves V alone; INC and DEC leave C alone; XBA sets flags from the new low byte; transfers use the destination width; `sep #$10` zeroes the high bytes of X and Y. Decimal mode is never set (no `sed` in the census).

### Addressing modes (16-bit A, flags live; cycles are 65C02 table values)

| Mode | Sites | Emitted 65C02 | Bytes | Cycles |
|---|---:|---|---:|---:|
| `##imm` | 8,247 | `lda #lo / sta vA / lda #hi / sta vA+1` | 8 | 10 |
| dp, `.near`, `long:` on a resident page | about 20,000 | `lda abs / sta vA / lda abs+1 / sta vA+1` | 10 | 14 |
| `adc` on a resident operand | | two-byte ADC chain; C and V native | 16 | 20 |
| `cmp ##k` | | `sec / sbc` chain into the flag cells | 15 | 21 |
| `long,x`, `abs,x/y`, `near,x/y`, resident | 4,773 | `php / clc` 16-bit add into `T0` `/ plp`, then `(T0)` and `(T0),y` | 26 | 43 |
| `[dp],y`, `[dp]`, and any non-resident operand | 3,775 plus | `ldx #cell / jsr rd16_ily` | 5 | about 120, plus 2-3 `$Cxxx` accesses |
| `n,s` | 225 | `ldy #n / lda (vSP),y / sta vA / iny / lda (vSP),y / sta vA+1` | 12 | 20 |
| Push or pull | 2,309 | `jsr push16` or `jsr pull16` | 3 | about 45 |
| `beq`/`bne` | | `lda vZl / ora vZh / beq` | 6 | 8 |
| `bcc`/`bcs`/`bvc`/`bvs` | | native, or `b?? +3 / jmp` when out of range | 2-5 | 3-6 |
| `xba` | 1,728 | swap `vA` and `vA+1` through A and X | 8 | 12 |

The NZ flag tail adds 6 bytes and 9 cycles, and is dropped where liveness proves it dead. The weighted average without that elision is about 9.9 bytes and 25 cycles per instruction (assumption, from the census weights).

### Calls, returns and the stack

- The stack is fully virtual. Three sites discard return frames: `U/src/iigs/p_path65.s:1089-1092`, `w_level65.s:1444-1447` and `m_menu65.s:2454-2457`. The tic runs on a private stack (`p_think65.s:194-197`). A split stack would break on all of these.
- A call pushes a return token of the original size, 2 bytes for JSR and 3 for JSL. The token indexes a table of about 3,300 return sites (3,241 resolved call sites, measured), 3 bytes each.
- `rts`/`rtl` become `jmp vm_ret`: pop, bounds-check, look up, then jump, load an overlay, or resume the interpreter.
- Stack-relative offsets are unchanged, because `vSP` tracks S one to one. TSC and TCS add or subtract a constant.
- The reference run taints pushed return bytes and reports any read that is not an RTS or RTL. That finds code which inspects return addresses.

### Function pointers, jump tables and MVN

- A code label whose address is taken gets a token `$C0:id`. Comparisons such as `cmp ##.word0 P_MobjThinker` (`U/src/iigs/p_tick65.s:250`) stay consistent.
- `JML [dp]` (8 sites), `jmp (abs,x)` (18), `jsr (abs,x)` (14) and `jmp (abs)` (20) load the token and call `vm_dispatch`.
- MVN calls a helper with the full contract: count, final X and Y, A = `$FFFF`, DBR = destination. It splits at mapping boundaries. It uses amem COPY for long runs outside visible SHR, and a CPU loop for short, overlapping or SHR-visible runs.

### Self-modifying code

Rule: code that is written at run time is data, and data is interpreted.

- **Detection, static.** Stores whose operand resolves to a label in a text section; MVN into text sections; `sta [dp]` sites reviewed by hand.
- **Detection, dynamic.** The reference core logs every write to a byte that is later executed.
- **Tier 0.** Any function holding a patched label is interpreted.
- **Tier 1.** A patched operand becomes a data cell and the instruction reads it. Patched opcodes stay interpreted.
- **Tier 2.** Row blocks, fills and replay become hand-written native kernels.

### Constructs that are not mechanical

| Construct | Sites (measured unless noted) | Handling |
|---|---:|---|
| Direct stores onto code labels | about 180 on 48 labels; `r_thing65.s` 63, `r_list65.s` 60, `r_seg65.s` 22 | Interpret, then cells or native |
| Hand-assembled MVN and MVP | 35 (33 `$54`, 2 `$44`) | Helper |
| Hand-assembled JML abs `$5C` | 28 | Parsed as an instruction |
| Hand-assembled JMP (abs) `$6C` | 8 | Dispatch |
| Hand-assembled JML [dp] `$DC` | 8 | Dispatch |
| Hand-assembled BRL `$82` and patched BRA `$80` | 16 and 7 | Interpret |
| Code images as `.byte` and generated image sections | about 60 lines in `r_seg65.s:1063-1151, 3186-3278`; `detailimg`, `thirdimg`, `fourimg` 4,925 instructions | Assembled as data; interpreted when executed |
| Run-time code generator | 1 (`patch65.s:279-381`, from `R/iigs-renderer.md`) | Interpret, later native |
| D used as data | 6 `tcd`/`tdc` in `p_trace65.s` | Mechanical with virtual D |
| Frame discards and stack switches | 3 and 4 | Mechanical with virtual stack |
| `xce` firmware wrappers | 7 outside the loader | Hand-written platform code |
| IIgs I/O register references | 216 lines in 12 files | Static hooks |
| Calypsi runtime calls | about 50 sites (`_Div16`, `_Mod16`, `_UDivMod16`, `_Div32`, `_UDivMod32`) | Our own routines; `cal_integer.s` is never assembled |

## 3. Memory model

### Physical map (initial; a planner driven by reference-run page heat adjusts it)

| Region | Contents |
|---|---|
| Main `$00-$FF` | VM registers and temps (about 40 bytes), promoted direct-page cells |
| Main `$0100-$01FF` | Host stack, for runtime helpers and IRQ only |
| Main `$0200-$03FF` | amem request blocks, SmartPort buffers |
| Main `$0400-$0BFF` | Read-only tables (mirrored window) |
| Main `$0C00-$1FFF` | Virtual DP `$00:0900`, WPAGE `$00:0A00`, hot near pages |
| Main `$2000-$5FFF` | Resident translated code, immutable (mirrored window) |
| Main `$6000-$BFFF` | Virtual stack pages in use, hot near and BSS pages, phase-resident data |
| Main LC, 16 KB | Far layer, dispatcher, interpreter (about 6 KB, assumption), IRQ, drivers, native kernels |
| Base aux `$0200-$BFFF` | Virtual bank `$01` by identity: `TEXLO/TEXHI` `$1E41`, SHR `$2000-$9FFF`, fuzz tables `$A000`, `STCACHE` `$A200` |
| Aux LC, aux ZP | Reserved |
| RamWorks 1-116, `$4000-$BFFF` | Virtual banks `$06-$3F`, one half-bank per physical bank |
| RamWorks 1-116, `$0200-$3FFF` | Original code image, overlay images, cold pages of banks `$00`, `$02`-`$05`, `$0D` |
| RamWorks 117-126 | Spare |
| RamWorks 127 | Unused; amem excludes it |

### Virtual to physical

- Banks `$06-$3F`: physical bank = `base[bank] + (offset >> 15)`, address = `$4000 + (offset & $7FFF)`. This needs 116 banks.
- Banks `$00`, `$02`-`$05` and `$0D`: one page table, 256 entries of 2 bytes per bank. The translator resolves static operands through the same table at build time.
- Bank `$01` and `$E1`: base aux. See section 4 for shadowing.

### Cost of one far access on current firmware

| Step | CPU cycles | `$Cxxx` accesses |
|---|---:|---:|
| Form the address and look up the bank | about 60 | 0 |
| Select the bank if it changed (`$C073`) | 6 | 0 or 1 |
| RAMRD or RAMWRT on, access one or two bytes, off | about 30 | 2 |
| Return | about 20 | 0 |
| **Total** | about 120 | 2 to 3 |

At 1.5 µs per bus access (`R/appletini-hardware.md`, section 1) this is 3.0 to 4.5 µs. Each mapping change also empties the TURBO caches (`F/README_TURBO.md:62-66`).

### Translated code size and placement

- About 57,000 instructions are candidates, after removing platform files and generated images. At 9.9 bytes each that is about 560 KB, or about 430 KB with flag elision (assumption).
- That cannot be resident, and code running from PSRAM pays about one line miss per instruction. So only hot, lockstep-covered functions are translated. I assume 20 to 25 percent of the code, about 110 KB.
- Translated code is grouped into phase overlays of 40 KB or less (tics, render, UI, level load). Everything else stays interpreted from the original image, which is about 190 KB.

### Fast memory and amem

- Kept fast: VM state, direct pages, the used part of the stack, hot near pages, the dither colormaps (17,408 bytes) and column records during rendering, and hot zone pages during tics.
- amem is used for overlay loads at phase changes, swaps of phase-resident data, MVN, and level loading between banks.
- Measured on our port: about 107 KB moved in about 40 ms (`R/existing-port.md`, section 5).

## 4. Renderer and presentation

- **Record lists, fill spans, covered ranges, weapon skip.** These are data structures of translated code at their upstream addresses (`MM_RECBASE $1D:0000`, `MM_FS $23:EF00`, `U/src/iigs/memmap.inc`). They need no redesign. The record bank is phase-resident while rendering.
- **Screen.** Virtual `$01:2000-$9CFF` is aux SHR memory. A write with shadowing on (`$C035` bit 3 clear) is one SHR write. The 2D path draws straight to SHR and `showDirty` becomes a no-op.
- **Deviation.** 2D drawing appears progressively instead of at `I_FinishUpdate`. Final pixels are the same. The check compares SHR at frame end with reference `$E1`. If a case needs the old content, that path gets a private buffer.
- **Row blocks, tier 0 and 1.** The upstream blocks are interpreted unchanged. The texel read `lda [SRC],y` and the colormap read `lda [CMA]` go through the far layer.
- **Row blocks, tier 2.** Native and two-pass per record, because RAMRD and RAMWRT share `$C073`:
  1. Select the texel bank, RAMRD on, gather up to 128 texels into a main-LC buffer.
  2. Select bank 0, RAMWRT on, look up the colormap in main RAM and store to `$2000+160r,x`.
  
  Entry is computed per row and exit is a patched opcode, as upstream does. The cost is about 6 bus accesses per record.
- **Bytes written to SHR per frame.**

| Item | Bytes |
|---|---:|
| View, worst case | 26,880 |
| View, E1M1 idle (assumption: walls cover 40 percent, static fills reused) | about 11,000 |
| SCBs and one tint row | 584 |
| Status bar | dirty bytes only |

  The mirror drains at about 1 byte per µs, so the idle view costs about 11 ms of stall.
- **Tearing.** The replay runs left to right across more than one video frame, so a seam is visible, as on the IIgs (`R/iigs-renderer.md`, section 1). A later option gathers columns and releases them in two bursts timed after VBL, which fixes the seam position.

## 5. Platform layer

| Area | Plan |
|---|---|
| Boot | ProDOS `DOOM.SYSTEM`, from `K/src/kernel/loader.s`, loads the runtime to LC and images to RamWorks in `A2DM` format, then leaves ProDOS |
| Disk | `K/tools/build_disk.py`; data produced by upstream's own Python tools run unmodified from the local clone; upstream code and data stay out of our repository |
| Level store | 1,821,696 bytes raw on disk; read at level start by SmartPort block calls from block numbers in a header, as upstream does; B1 decoder hand-written |
| Input | `K/src/kernel/input.s`; ASCII keys become synthetic ADB codes in the 32-byte ring, with key-up inferred from the any-key flag; mouse card deltas feed the mouse path |
| Clock | Mouse-card VBL IRQ scaled to 35 Hz (`K/src/kernel/frame.s`) replaces the DOC oscillator in `I_GetTime` |
| Sound | Stage 1: DOC driver stubbed; `s_sound65.s` logic still runs. Stage 2: AY effects and converted music on the Phasor, register writes batched once per VBL (slot 4 forces 1 MHz for 512 cycles) |
| Saves | `DOOM.SETTINGS`, one block, written through SmartPort |
| Startup tables | Quarter squares (512 KB) are computed at boot; tier 2 loads them prebuilt |

## 6. Performance estimate, E1M1 idle

**Assumptions.**

- A1: 600,000 original instructions per frame. Derived from upstream's 4 FPS at 12 MHz (`U/README.md:15`) at about 5 cycles per instruction.
- A2: phase split as in the table.
- A3: 17 percent of instructions make a far access (the static share of far modes).
- A4: 50 M host cycles per second in fast memory. A cache hit takes two fabric clocks, so 66 M is the ceiling. Our port measured about 42 M overall.
- A5: 3.5 µs per far access.
- A6: about 1 µs per PSRAM line miss.
- A7: interpreter 150 host cycles per instruction.
- A8: translated code 20 cycles with elision.

| Phase | Instructions | Tier 2 time |
|---|---:|---:|
| 4 game tics | 150,000 | 60 ms CPU + 40-77 ms far |
| BSP and wall setup | 130,000 | 52 ms + 45 ms far |
| Seg loop | 120,000 | 48 ms + 5 ms |
| Sprites, masked, weapon | 40,000 | 16 ms + 14 ms |
| Replay, native | 130,000 | 27 ms, including 11 ms SHR drain |
| 2D and finish | 30,000 | 13 ms |
| Overlay and data swaps | | 30 ms |
| **Total** | 600,000 | about 370 ms, 2.7 FPS |

| Tier | Frame time | FPS |
|---|---:|---:|
| 0, all interpreted | 1.8 s + 0.35 s far + 0.6 s fetch = 2.8 s | 0.35 |
| 1, translated; self-modifying code interpreted | about 1.0 s | 1.0 |
| 2, native kernels and intrinsics | about 0.37 s | 2.7 |
| 2 with all three firmware changes | about 0.22 s | 4.5 |

These numbers are estimates. Milestone 2 replaces A1 to A3 with measured counts.

## 7. Verification strategy

| Layer | Check | Tool |
|---|---|---|
| 1. Front end | Assembler output equals the release code bytes | `cas65816.py` |
| 2. Inference | Static M, X, D, DBR equal the values observed per PC | reference trace |
| 3. Cores | 65816 core and on-target interpreter pass per-opcode vectors | SingleStepTests 65816 (assumption: must be downloaded) |
| 4. Templates | Each template against the core on random states | about 500 templates |
| 5. Lockstep | Registers and memory writes compared at every translated instruction | `a2vm` + `ref816` |
| 6. Oracle | Reference checked against the release image in GSSquared at fixed tics | debug socket (`READMEM`, breakpoints) |

- **Verified facts.**
  - `doom-hd.hdv` has SHA-256 `2716166d…`, which matches `SHA256SUMS`.
  - Its header lists 28 segments and entry `$03:0000`.
  - The bytes there are `78 18 FB C2 38 A2 FF 3F 9A`, which match `U/src/iigs/crt0.s:33-39`.
  - Code segments are stored raw.
- **`ref816`.** A C 65816 core with a minimal IIgs: RAM, shadow register, DOC timer, ADB and block-device traps. It is deterministic. GSSquared's `cpu_65816.cpp` is a candidate core, subject to a licence check.
- **`a2vm`.** A C 65C02 core with the Appletini map and an amem model. It is checked against `K/tools/a2sim.py` on our existing port. An optional cost model covers PSRAM misses, bus accesses and mirror drain.
- **Lockstep without instrumentation.** The translator emits a map from host PC to original PC, widths and live flags. The harness steps the reference one instruction and compares, so the tested binary is the shipped binary.
- **Replaced code.** Platform routines, intrinsics and native kernels are compared at their contracts. The reference is master for clock and input values.
- **Speed.** At an assumed 200 M cycles per second, a tier-2 frame takes about 0.08 s of host time. Demo3 is about 525 frames, so about 40 s.
- **Coverage.** Runs use demo3, the timedemo builds of demo1 and demo2 (built by our assembler), `idclev` tours of nine maps and menu scripts. A function is translated only after lockstep has executed it. Uncovered code stays interpreted.

## 8. Milestones

1. **Days 1-4.** Front end parses everything and reproduces the release code bytes; link map recovered.
2. **Week 2.** `ref816` plays demo3 from the release image; GSSquared checkpoints agree; profiles produced (phase counts, page heat, stack depth, taint report).
3. **Week 3.** `a2vm` passes our port's tests; interpreter passes opcode vectors.
4. **Week 4-5.** Whole game interpreted in `a2vm` in lockstep through demo3; first hardware run, as a slideshow.
5. Platform layer complete: input, clock, level store, settings.
6. Translator with template tests; first modules translated (`m_random65`, `string65`, `z_zone65`, `w_wad65`).
7. All hot covered functions translated; overlays and residency planner; hardware profile.
8. Operand cells, intrinsic multiplies and divides, native row blocks, fills and replay.
9. Sound and music.
10. Nine-map soak on hardware; release.

## 9. Risks

| Rank | Risk | Mitigation |
|---:|---|---|
| 1 | Far-access cost keeps speed under 3 FPS | Phase-resident data, fused sessions, intrinsics, firmware items 1-3 |
| 2 | Fast memory is over-subscribed (near bank, stack, colormaps, records, code) | Page-heat planner; interpret cold code; measure before fixing the map |
| 3 | Front end cannot reproduce every byte | Fragment matching isolates mismatches; the image is ground truth |
| 4 | Inference wrong on unexecuted paths | Translate only covered functions; run-time asserts |
| 5 | Direct 2D drawing changes visible behaviour | Frame-end comparison; private buffer per failing path |
| 6 | Hardware differs from `a2vm` (PSRAM, flushes, amem holds) | Early slideshow run; profile mailbox; host-time capture |
| 7 | Assumptions A1-A3 are off by a factor of two | Measured at milestone 2 |
| 8 | Sound quality on AY chips | Staged; the game is complete without it |
| 9 | Boot time for computed tables | Prebuilt tables |

## 10. Firmware wish list

| Rank | Change | Effect on this design |
|---:|---|---|
| 1 | Bank and soft-switch changes that neither touch the bus nor flush caches | Far access falls from about 3.5 µs to about 2 µs of CPU work; tier 1 approaches tier 2; session fusion becomes optional |
| 2 | Multi-line cache, or DDR behind extended memory | Code can run from extended banks, so all covered code can be translated and overlays disappear; the planner matters less |
| 3 | Separate read and write bank registers | Native row blocks become single-pass; bank-to-bank copies need no bounce buffer; the far layer caches two banks |
| 4 | amem copy visible to SHR | Burst presentation and `showDirty` without CPU loops |
| 5 | Readable microsecond counter at a cheap address | Hardware profiling and a clock without the mouse card |