# Design brief: porting Webifi's IIgs DOOM to the Appletini 65C02

## Goal (from the project owner)

Port https://github.com/Webifi/iigs-doom to "our Appletini-enhanced 65C02".
"Maybe you start with their code, or start with ours and implement their
changes, but ultimately I want their whole game to run on 65c02 and the
Appletini with the SHR techniques they use." The owner also asked that the
ARM memory copy/fill API (amem) be used to move code and data between banks.

The owner writes the Appletini firmware and is open to firmware changes
(they have asked about a visible-SHR amem copy and about moving extended RAM
from PSRAM to DDR), but **the port must work on today's firmware** (F1.2.x on `origin/main`;
the research reports were written against F1.1.4, and the accelerator,
memory and amem behaviour they describe is unchanged apart from one extra
fabric clock on direct TURBO video writes). Three firmware changes are under
discussion with the owner and are NOT available yet: (1) a multi-line cache
in front of extended memory, possibly with DDR instead of PSRAM behind it;
(2) bank and soft-switch changes that no longer touch the bus or flush the
TURBO caches; (3) separate read and write bank registers. State how your
design would change if each of them existed.

## Where things are (all absolute paths)

- Upstream source, read-only clone:
  `<upstream>`
  (`src/iigs/*.s`, `*.inc`, `iigs.scm`, `memmap.inc`, `tools/*.py`, `Makefile`)
- Research reports (read these first, they cite file:line):
  `<research>/`
  - `appletini-hardware.md`: CPU, memory speed, TURBO, video mirror, amem
  - `iigs-renderer.md`: their frame pipeline and SHR techniques
  - `iigs-platform.md`: boot, platform layer, conventions, statistics
  - `existing-port.md`: our current cc65 Doom port, kernel, harness, measurements
  - `calypsi-assembler-chapter.txt`: the assembler's syntax reference
- Our repo: `<appletini-software>` (branch
  `claude/iigs-doom-port`); existing port in `demos/doom`.
- Hardware/firmware snapshot of `origin/main` (F1.2.1), read-only:
  `<appletini-one>`
  (`README_MEMORY_API.md`, `README_TURBO.md`, `README_VIRTUAL_TRANSWARP.md`, `hdl/`).
  Do not use the checkout at `<appletini-one>`; it is on an older branch.
- Python with py65 and Pillow:
  `<scratch>/venv/bin/python`
- cc65 2.18 (`ca65`, `ld65`) is installed. The Calypsi assembler is NOT
  runnable here (x86-only binary, no Rosetta), so the original cannot be
  assembled locally. The v1.0 release disk image is at
  `.../scratchpad/release/doom-hd.hdv`.

## Hard facts that constrain the design

Upstream:
- 82,470 lines, 58,645 instruction lines of 65816 assembly, no C. 105 macros,
  C preprocessor, generated unrolled drawers (`tools/gendraw.py`).
- 16-bit A/X/Y by default; 8-bit windows via `sep/rep` (1,107 sites). The
  assembler does not track M/X: only immediates show width (`#` 8-bit,
  `##` 16-bit).
- Addressing-mode counts over the source: implied/acc 14,775; `.near`
  (DBR=$02 absolute) 8,314 (+317 indexed); 16-bit immediate 8,151; direct
  page 6,279; `long:` 3,068 (+1,610 `long,x`); `[dp],y` 2,620; `[dp]` 252;
  8-bit immediate 2,197; stack-relative 316; `jsl` 1,120; `jsr` 2,242;
  `rtl` 694; `rts` 1,169; `xba` 620; `pei` 151; `plb` 205; MVN 33 (as `.byte $54`).
- Pointers in structs are 4 bytes (24-bit + pad). Lumps and zone blocks never
  cross a 64K bank, so pointer arithmetic is 16-bit within a bank.
- Needs at least 4 MB: every bank $00-$3F has an assigned use. About 830 KB
  is pure speed-for-space tables (quarter squares 512 KB, FSTEP 128 KB,
  reciprocal/log/sine 192 KB). The level window needs about 1.5 MB per map.
- 65816 stack is 13.5 KB at $0B00-$3FFF, with stack frames built by
  TSC/SBC/TCS, 316 stack-relative operands, a private per-tic stack, and at
  least one routine that discards its caller's frame.
- Direct page is relocated: $0900 normally, $0A00 (WPAGE) in the wall loop,
  $0000 for firmware calls.
- Self-modifying code is common in the renderer: opcode patching of row
  blocks (`$6C`, `$60`), operand patching, MVN bank operands, run-time
  compiled HUD text code, kernels installed by MVN.
- `src/iigs/cal_integer.s` is a copy of Calypsi's runtime whose licence
  permits use only with the Calypsi toolchain. It must be replaced by our own
  routines, not translated or redistributed.
- The game is GPL-2. Our repo's precedent (demos/bilestoad) is to keep
  upstream out of the repository and convert it from a local clone at build
  time.
- Sound and the game clock use the Ensoniq DOC; input uses raw ADB. Neither
  exists on the Appletini.

Appletini (current firmware):
- W65C02S soft core. TURBO has no fixed MHz; one simulated benchmark shows
  2.28-2.44x the 33 MHz preset for a copy loop.
- Fast memory is main 64K plus base aux 64K (BRAM). SHR occupies base aux
  $2000-$9FFF. RamWorks banks 1-127 are PSRAM behind ONE 8-byte
  write-allocate line; a miss waits for an admission window that opens once
  per Apple bus cycle (about 1 us).
- Every $C000-$CFFF access is a real bus cycle (1-2 us). Any mapping change
  invalidates the TURBO caches. `$C071/$C073`, `$C080-$CFFF` and some others
  also force a video-mirror flush.
- RAMRD and RAMWRT share the one bank register `$C073`. ALTZP moves zero
  page, stack and the language card to the selected bank.
- SHR writes are captured at fabric speed, but the CPU stalls on its next
  `$Cxxx` access until the motherboard mirror has drained at about one byte
  per Apple cycle. Main `$0400-$0BFF` and `$2000-$5FFF` are also mirrored
  video windows; writable data should avoid them.
- amem: up to 16 COPY/FILL descriptors per request, endpoints within
  `$0200-$BFFF`, banks MAIN 0, AUX 0-126, PRIVATE required for MAIN/base-AUX
  destinations and invisible to the display.
- Sound: Phasor/Mockingboard (AY chips, SSI-263) in slot 4; its accesses force
  1 MHz for a window. Mouse card in slot 2 provides a VBL IRQ.
- Measured on hardware with our existing port: about 4 FPS, roughly 10-11 M
  py65 model cycles per 248 ms frame; moving control code from an extended
  bank to base aux gave +40%.

Test infrastructure:
- `demos/doom/tools/a2sim.py` models the Appletini memory map on py65 at
  about 3.5 M model cycles per host second. It does not model PSRAM latency,
  TURBO caches or mirror stalls.
- GSSquared (`<gssquared>`, built, GUI, debug
  socket with READMEM/breakpoints) can run the original release image as a
  IIgs.

## Preliminary analysis to challenge, not to accept

1. A hand port of 58K instructions is not credible; a source-to-source
   translator (Python, run at build time against a pinned upstream clone)
   is the only route to "their whole game".
2. Keep the original 24-bit address space as a *virtual* address space so
   that pointers, data layout and the converted WAD/level store stay
   byte-identical to upstream, and map virtual bank:offset to a physical
   (Appletini bank, address) in a far-memory layer.
3. The 65C02 hardware stack (256 bytes) cannot hold the 65816 stack. Either
   emulate the whole 16-bit stack in software, or split: return addresses on
   the hardware stack, data on a software stack, with static adjustment of
   stack-relative offsets.
4. Hot renderer loops (row blocks, fills, record replay, presentation)
   should be hand-written 65C02, because they are byte-oriented, heavily
   self-modifying and dominate frame time. Everything else is translated.
5. Reuse our kernel where it fits: ProDOS loader, amem transport, banking
   helpers, input, VBL clock, disk builder, emulator harness.
6. Verification needs a reference for the original semantics. Without the
   Calypsi assembler, candidates are: an interpreter over the parsed 65816
   source (same front end as the translator), or the original release image
   running in GSSquared, or our own 65816 assembler checked against the
   release image bytes.
7. py65 at 3.5 M cycles/s is probably too slow for differential testing of a
   whole game; a small C emulator of the 65C02 plus the Appletini memory map
   may be worth building.

## What a design proposal must contain

1. **Architecture summary** in under 300 words.
2. **Translator design**: front end (preprocessor, macros, sections,
   expressions, local labels), M/X and direct-page inference, register
   model on the 65C02 (where the high bytes of A/X/Y live), flag semantics,
   handling of each addressing mode with the emitted 65C02 sequence and its
   cycle and byte cost, calls/returns, stack model, MVN, function pointers
   (`JML [dp]`), jump tables, and how self-modifying sites are detected and
   handled. Name the upstream constructs that cannot be translated
   mechanically and how many sites each has (verify by grep).
3. **Memory model**: a complete map. Where translated code lives (size
   estimate with justification), what occupies main RAM, main LC, base aux,
   and which RamWorks banks; how virtual addresses map to physical; how a
   far read/write is performed and what it costs in CPU cycles and in
   `$Cxxx` accesses; what is kept in fast memory and why; how amem is used.
4. **Renderer and presentation**: how their record lists, row blocks,
   fill spans, covered ranges and dither colormaps are realised given that
   RAMRD and RAMWRT share one bank register; bytes written to SHR per frame;
   tearing.
5. **Platform layer**: boot and disk layout, input, clock, sound/music
   backend plan, save games.
6. **Performance estimate** for E1M1 idle, broken down by phase, stating
   every assumption. Estimates must use the hardware facts above.
7. **Verification strategy** and what tooling it needs.
8. **Milestones**: an ordered list where each milestone produces something
   testable, with the first one achievable in days.
9. **Risks**, ranked, each with a mitigation.
10. **Firmware wish list** (optional), ranked by benefit to this port.

Be concrete and quantitative. Read the upstream source to check your
assumptions; cite file:line. Do not modify any files.
