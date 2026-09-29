# DOOM GS milestones: handoff brief

This file lets any engineer, or any AI agent, continue the port without the
conversation that started it. It states what is done, what is in progress,
and the exact specification and acceptance tests of the next steps.

Status as of 2026-09-29.

## Read first

1. [`README.md`](../README.md): what the port is, and the licensing rules.
2. [`ARCHITECTURE.md`](ARCHITECTURE.md): the draft design. Sections 0 (facts
   settled from the source), 1 (summary), 7 (verification), 8 (milestones)
   and 13 (open questions). **The project owner has not reviewed it yet.**
3. [`research/iigs-platform.md`](research/iigs-platform.md) and
   [`research/iigs-renderer.md`](research/iigs-renderer.md): how upstream
   works, with file and line references.
4. [`research/appletini-hardware.md`](research/appletini-hardware.md): what
   the target is fast and slow at.

## Goal

Port [Webifi's Apple IIgs DOOM](https://github.com/Webifi/iigs-doom) (GPL-2,
about 82,000 lines of 65816 assembly for the Calypsi assembler) to an
enhanced Apple //e with an Appletini card. The owner wants "their whole game
to run on 65c02 and the Appletini with the SHR techniques they use". The
Appletini's accelerator is a W65C02S soft core, so no 65816 code runs as is.

The chosen approach (ARCHITECTURE.md section 1) is a virtual 65816 machine:
an interpreter for cold code, translated regions for warm code, and
hand-written 65C02 kernels for the hot loops. Every step is checked against a
reference that runs the original release.

## Ground rules

These are firm. Breaking one is a defect even if the tests pass.

| Rule | Why |
| --- | --- |
| Never commit upstream source, upstream's generated code, the release image, ROM images or third-party test vectors. Fetch them into `build/`, which is ignored. | Upstream is GPL-2; this repository follows [The Bilestoad](../../bilestoad/README.md) in keeping upstream out. |
| Nothing of upstream's `src/iigs/cal_integer.s` may leave `build/`: no copies, excerpts or translations of its code, and no routine written from reading it. The port's replacements are written from the call sites and the documented behaviour only. Facts about the file, such as its length or a `file:line` reference, are fine. | It is a copy of the Calypsi vendor runtime, licensed for that toolchain only. |
| The Calypsi manual extract stays in `build/reference/`. | Vendor copyright. |
| Emulated machines are deterministic: the same inputs give the same run, byte for byte. No host time, no randomness. | Lockstep comparison depends on it. |
| Python tools use the standard library only and run on Python 3.9 to 3.14. C tools are C11, standard library only, built by a `Makefile` with `-Wall -Wextra` and no warnings. | Reproducible builds on the owner's Mac. |
| Unit tests live in `tests/` and run with `python3 -m unittest discover -s tests` from this directory. Tests that need `build/` skip with a clear message when it is missing. | One command checks everything. |
| Do not weaken a test, and do not special-case game addresses or file names to force a result. Report what does not work. | Earlier stages were independently reviewed for exactly this. |
| Work on branch `claude/iigs-doom-port`. Commit only finished, tested milestones or documents. | The owner approved commits and pushes on this branch. |

## Setting up

From `demos/doom_gs`:

```
python3 tools/fetch_upstream.py            # clone at 8ea2eac, release image, into build/
python3 tools/v816/imgmatch.py             # assemble, link, compare with the release
python3 -m unittest discover -s tests      # all unit tests
```

The reference machine of milestone 2 (about 10 minutes for everything):

```
python3 tools/ref816/fetch_vectors.py      # 65816 test vectors into build/vectors/
make -C tools/ref816 vectors selftest machinetest
python3 tools/ref816/title.py              # boots the release to its title screen
python3 tools/ref816/run_script.py title newgame viewsize tour --twice
python3 tools/ref816/profile816.py --run   # traces, then docs/PROFILE.md
```

`fetch_upstream.py` pins upstream commit
`8ea2eac8b650daf2cf66127c4be6d3f8654dd335` and the release image
`doom-hd.hdv` with SHA-256
`2716166dda1d87faf3bdec572ddcf652379a54da78f1dcccdd0897e00b23bd0d`. It also
accepts `--from-local-clone DIR` and `--from-local-image FILE`.

Host tools used so far: Python 3.14 from Homebrew, Apple clang, cc65 2.18,
Verilator 5.050. The Calypsi assembler itself is not needed: it is an x86-64
binary and the owner's Mac has no Rosetta.

## Status

| # | Milestone | State |
| --- | --- | --- |
| 0 | Hardware microbenchmarks on the Appletini | Not started. Needs the physical card and the owner. |
| 1 | Front end, 65816 assembler and linker, image match | **Done**, commit `89bb480f`. |
| 2 | Reference machine runs the release; measured profiles | **Done**, see the results below. |
| 3 | Target machine model with cost model; 65816 interpreter | Next. Specified below. |
| 4 | Hand-written record replay on hardware | Not started |
| 5 | Whole game interpreted, lockstep through demo3; first hardware run | Not started |
| 6 | Translator with template tests; first modules | Not started |
| 7 | Hot regions translated; phase windows | Not started |
| 8 | Hand-written seg loops, node fetch, thinker walk | Not started |
| 9 | Status bar, HUD, menus, automap, intermission | Not started |
| 10 | Sound effects, then music, on the Phasor | Not started |
| 11 | Settings and saves, nine-map soak, release | Not started |

## Milestone 1: done

Our own tools assemble and link upstream's sources and rebuild the v1.0
release with **0 differing bytes of 221,696**: the game (218,112 bytes), the
boot block (512) and the loader (3,072).

| Part | Files |
| --- | --- |
| Fetch and release reader | `tools/fetch_upstream.py`, `tools/v816/prodos.py`, `hdv.py`, `b1.py`, `memimage.py`, `tools/list_segments.py` |
| Front end | `tools/v816/cpp.py`, `lexer.py`, `expr.py`, `macro.py`, `parse.py`, `ir.py`, `frontend.py` |
| Back end | `tools/v816/opcodes.py`, `asm816.py`, `linear.py`, `objfile.py`, `scm.py`, `link.py`, `sections.py` |
| Layout recovery and report | `tools/v816/place.py`, `release.py`, `imgmatch.py`, `linkmap.py`, `report.py`, `stats.py` |
| Statistics | [`FRONTEND_STATS.md`](FRONTEND_STATS.md), regenerated by `frontend.py --stats` |

Outputs in `build/`: `linkmap.json` (address of every section fragment and
value of every symbol) and `match-report.json`.

The Calypsi linker may place section fragments in any order, so the layout
is **recovered** from the release image, not predicted. A build of modified
sources will need its own placement.

An independent review found no cheating and two medium weaknesses; they are
step 2.0 below.

## Milestone 2: reference machine and measured profiles

### Results

Done on 2026-09-29, independently reviewed, with the review's findings fixed
and verified.

| Check | Result |
| --- | --- |
| 65816 core against SingleStepTests (commit `db6b104`) | 5,120,000 cases: 0 register, memory, cycle-count or bus failures; 44 known issues in two narrow rules, each citing the published errata of the vector set |
| Title screen | Reached from the release image; the colour DOOM title picture |
| Game clock | 34.955 tics per emulated second, as the DOC settings predict |
| Scripts | `title`, `newgame`, `viewsize` and `tour` run to their end at 2.86 MHz and 12 MHz, twice each with identical RAM hashes; all nine maps visited |
| Unit tests | 735, none skipped |

Frame cost on an ideal 65816 with no wait states, 4 tics per frame:

| Scene | Instructions a frame | Cycles a frame | Frames a second at 2.86 MHz | at 12 MHz |
| --- | ---: | ---: | ---: | ---: |
| Standing still in E1M1 | 331,325 | 1,123,634 | 2.50 | 10.79 |
| Title demo, E1M3 | 461,187 | 1,604,459 | 1.64 | 6.19 |

The full measurements are in [`PROFILE.md`](PROFILE.md). What they change:

- **Register widths.** Only 70 of 38,793 executed addresses run with more
  than one accumulator and index width, so static width inference works
  almost everywhere. `build/ref816/widths.json` lists every exception.
- **Stack.** At most 86 bytes on the frame stack and 228 on the tic stack,
  far below the 4 KB the architecture reserved.
- **Where the time goes.** The record replay is 34% of the cycles standing
  still and 42% in the demo; the seg loops are 32% standing still. Both are
  planned as hand-written code.
- **Screen.** Standing still, only 152 of the 8,519 screen bytes written a
  frame change the stored value; in the demo 15,262 of 21,881.
- **The assumptions of ARCHITECTURE.md section 6.** Instructions outside the
  replay are about half the assumed 450,000; far accesses outside the replay
  are 30,000 to 47,000, fewer than assumed but a larger share of the
  instructions. Section 8 of `PROFILE.md` gives each.

Known limits: the machine has no wait states, so its times are those of an
ideal CPU; counts per frame do not depend on that. It has not been compared
with GSSquared or a real IIgs. `$C039` (serial) is the only register the game
touches that it does not model.

### Specification


A 65816 machine on the host that runs upstream's release, plays it under
script, and measures what the port needs to know. It replaces the assumed
figures in ARCHITECTURE.md section 6 with measured ones and produces the
register-width map the translator needs.

Everything new goes in `tools/ref816/`, `coverage/` and `docs/PROFILE.md`.

### 2.0 Fix the milestone 1 review findings

Each fix gets a unit test. The image match must stay at 0 differing bytes.

| # | Where | Fix |
| --- | --- | --- |
| 1 | `place.py`, `sections.py` | An address resting on one reference has no independent check. List such atoms as `single_evidence` in `match-report.json`, and add a `support` count per fragment to `linkmap.json`. |
| 2 | `place.py`, `imgmatch.py` | A reachable fragment without bytes that nothing refers to is silently dropped. Report every reachable unplaced fragment of size above 0 as unplaced, and require placed == part of the program in `clean()`. |
| 3 | `sections.py` | `data_init_table` is reconstructed from one image. Say so in the report, and add a test that fails on a copy entry or a different order. |
| 4 | `hdv.py`, `release.py` | Linked segments are chosen by hard-coded bank numbers. Derive them from the rules file's memories that accept initialised sections. |
| 5 | `place.py` | The docstring of `solve()` is wrong about the minimum hole width. |
| 6 | `objfile.py` | A `.section NAME` without a kind is taken as text. Document it, and report an error when fragments of one section differ in kind. |
| 7 | `sections.py` | Report a problem when a fixed-address section does not start at its fixed address. |
| 8 | `memimage.py` | Region owners are signed 16-bit. Widen, or fail clearly at the limit. |

### 2.1 The 65816 core

`tools/ref816/cpu816.c`, `cpu816.h`. Exact registers, flags and memory
effects for every opcode in native and emulation modes, including:

- decimal mode, 8- and 16-bit accumulator and index, and truncation of X and
  Y when the index flag is set;
- direct-page relocation with the emulation-mode page-wrap rules;
- stack-relative modes;
- MVN and MVP one byte per step, so an interrupt can fall between steps;
- BRK, COP, RTI, WAI, STP, and IRQ and NMI entry in both modes;
- cycle counts from the manufacturer's table, including 16-bit modes, a
  nonzero direct-page low byte, page crossings and taken branches.

The bus is two callbacks, `read(addr24)` and `write(addr24, value)`, plus IRQ
set and clear.

Check it against the public
[SingleStepTests](https://github.com/SingleStepTests) 65816 vectors, fetched
into `build/vectors/` by `tools/ref816/fetch_vectors.py`, which pins the
commit. Compare registers and memory for every case; report cycle mismatches
separately. Known-unreliable cases are listed by opcode with the reason, never
silently skipped.

**Acceptance:** builds with no warnings; every opcode passes in both modes, or
each exception is listed with evidence; a unit test runs a sample of the
vectors, and a `make` target runs all of them.

### 2.2 The machine around the core

`tools/ref816/iigs.c`, `iigs.h`, `main.c`. Only as much IIgs as the game needs.
The register list is in `research/iigs-platform.md` section 2.7.

| Area | What to model |
| --- | --- |
| Memory | 8 MB in banks `$00-$7F`, plus `$E0` and `$E1`. Shadow register `$C035`: bit 3 gates SHR shadowing of bank `$01` `$2000-$9FFF` into `$E1`; bit 6 turns banks `$00/$01` I/O and language card into RAM, where the game puts its vectors at `$00:FFE0`. Speed `$C036`, new-video `$C029`, border `$C034`, VBL flag `$C019` from emulated time. Interrupt registers `$C023`, `$C032`, `$C041`, `$C047`, `$C027`. |
| Accelerators | ZipGS `$C059-$C05F` and the TransWarp GS signature in bank `$BC` read as absent, unless the game will not start without one. If so, model the minimum and say so. |
| Clock and sound | The game's only clock is the Ensoniq DOC through the sound GLU at `$C03C-$C03F`: oscillator 31 free-running as the tic clock, oscillator 30 as a one-shot alarm raising IRQ. Model enough that `I_GetTime` runs at the right rate against emulated cycles and the music interrupt fires. No audio output. |
| Input | ADB microcontroller at `$C026/$C027` (the game polls it directly), mouse at `$C024`. Scripted key presses, releases and mouse motion must reach the game. |
| Start-up | `tools/ref816/make_image.py` writes `build/ref816/memory.img` from the release (segments at their addresses, level store at `$40:0000` as in 8 MB mode) and the BOOTINFO block the loader leaves (layout in `loader.s` and `m_config65.s`). Start at the entry point in native mode with the state `crt0.s` expects. |
| Disk | Trap the slot-firmware calls the game makes to save settings and, in 4 MB mode, load levels. Serve them from a copy of the disk in `build/`, never from `build/release`. |
| Screenshots | `tools/ref816/shot.py` turns a dump of `$E1:2000-$9FFF` into a PNG using only `zlib`: 320 mode, per-line palettes, border. |
| Command line | Run N cycles or N video frames, with optional screen dumps and a final state dump: registers and a hash of all RAM. |

**Acceptance:**

1. `make` builds with no warnings; all tests pass.
2. The game reaches its title screen, and a PNG of it is written to
   `build/ref816/shots/`. The image is 320x200 or 640x400, has more than 8
   colours, and shows the DOOM title picture.
3. Two runs with the same arguments give the same final RAM hash.
4. The game clock runs at about 35 tics per emulated second.

List every approximated or stubbed hardware behaviour, with its address.

### 2.3 Playing under script

- An input script format documented in `tools/ref816/README.md`, with lines
  such as `at <tic> key down <name>`, `key up <name>`, `mouse <dx> <dy>`,
  `button down|up`, `shot <name>`, `stop`. Default bindings are in
  `i_iigs65.s` (`keyTable`) and `m_config65.s`.
- `tools/ref816/run_script.py` runs a script and writes its shots to
  `build/ref816/shots/<script>/`.
- Four scripts in `coverage/`:

| Script | Content |
| --- | --- |
| `title.script` | The title loop until demo3 has played at least 20 emulated seconds, a shot every 5 s |
| `newgame.script` | New game on the default skill through the menus; stand still in E1M1 for 10 s; walk, turn, fire, open the first door |
| `viewsize.script` | Every view size through the options menu, a shot at each |
| `tour.script` | Each of the nine maps through the `idclev` cheat (`m_cheat65.s`), 5 s and a shot each |

**Acceptance:**

1. All four scripts run to the end without an unimplemented register, an
   illegal opcode, the game's error screen (`I_Error`) or a stuck loop.
2. E1M1 shots show a 3D view.
3. Each script is deterministic.
4. Report rendered frames per emulated second, and 65816 instructions and
   cycles per rendered frame (median over at least 20 frames), for the title
   demo and for standing still in E1M1, on an ideal 65816 with uniform
   memory. Report cycles, not wall time.

### 2.4 Measured profiles

Tracing in `tools/ref816/trace.c`, enabled by options so an untraced run
stays fast, and a report tool `tools/ref816/profile816.py` that maps
addresses to symbols through `build/linkmap.json`. `docs/PROFILE.md` folds the
code of `cal_integer.s` into its "others" rows and never shows it on its own;
its separate figures go to `build/ref816/profile-withheld.json`.

Measure per rendered frame, median and range over at least 20 frames, for
standing still in E1M1 and for the title demo:

1. Instructions and cycles by phase: game tics (`P_Ticker` and callees), frame
   setup, BSP walk, wall setup (`R_StoreWallRange`), seg loops
   (`R_RenderSegLoop`), sprite projection, masked drawing, record replay
   (`R_DrawLists`), status bar and HUD, menu, finish (`I_FinishUpdate`),
   interrupts, other. Say how each boundary was detected; upstream marks
   phases only in a `PHASES` build.
2. Memory accesses by kind: direct page, stack, bank `$02` near data, and far
   data by bank, reads and writes apart. For far data also the distinct
   8-byte lines, 64-byte lines and 256-byte pages touched per bank per frame,
   and the number of bank changes between consecutive far accesses.
3. Code heat: bytes executed at least once per frame, and the bytes covering
   90%, 99% and 99.9% of executed instructions, by section and source file.
4. Register-width map: for each executed address, the values of the M and X
   flags, the direct-page register and the data-bank register it ran with.
   Write `build/ref816/widths.json` and count the addresses seen with more
   than one value of each.
5. Self-modification: every write to a byte later executed, grouped by the
   writing instruction and the target symbol, with counts per frame.
6. Stack: the lowest stack pointer per frame, for the main and tic stacks.
7. Screen: bytes written to `$E1:2000-$9CFF` per frame, and how many changed
   the stored value.

Write the results to `docs/PROFILE.md` as tables, each with a short paragraph
on what it implies for the target. The target has about 90 KB of fast memory,
slow extended memory behind a small cache, bus cycles of about 1 µs for bank
switches, and about 1 µs per screen byte written. Replace assumptions P2, P4,
P6 and P8 of ARCHITECTURE.md section 6 with measured values in a section of
`PROFILE.md`; do not edit ARCHITECTURE.md.

**Acceptance:** `profile816.py` regenerates `PROFILE.md` deterministically
from trace files; a unit test checks it on a small synthetic trace; the
numbers in `PROFILE.md` are the ones the tool printed.

### 2.5 Independent review

Someone who did not write the code checks it. Review; do not rewrite.

1. Build from clean, run all tests, the full vector run, and at least the
   title and newgame scripts. Report the real numbers.
2. Check determinism.
3. Look for anything that makes the measurements untrustworthy. Examples: a
   game address special-cased to get past a problem; a stub that changes game
   behaviour, such as a clock at the wrong rate, which would change tics per
   frame and every per-frame count; wrongly attributed phases; counts that
   include the emulator's own traps.
4. Check the ground rules: nothing from upstream, the release, ROMs or the
   vectors outside `build/`.
5. Look at three screenshots and say what they show.
6. List real defects with file and line, most serious first. Fix only trivial
   ones.

Commit milestone 2 only after the review passes.

## Milestone 3: target machine model and 65816 interpreter

Two pieces every later milestone needs, whatever the firmware decisions:

- `a2vm`, a fast model of the Appletini target, to run port code on the host.
- A 65816 interpreter written in 65C02 assembly. It is tier 0 of the
  architecture: it runs cold code, code with unclassified self-modification,
  and anything the translator refuses.

New code goes in `tools/a2vm/` (host tool) and `src/vm/` (port code that runs
on the Apple, assembled with ca65 from cc65 2.18).

### 3.1 `a2vm`, the target model

A C11 program with the same build rules as `tools/ref816`.

| Part | What to model |
| --- | --- |
| CPU | W65C02S, including RMB, SMB, BBR, BBS, WAI and STP, exact in registers, flags and memory effects, with the datasheet's cycle counts. Check it against a public per-opcode vector set for the WDC 65C02 fetched into `build/vectors/` (the SingleStepTests organisation has one); list any unreliable cases by opcode with the reason. |
| Memory | Enhanced //e main 64 KB and 128 RamWorks banks selected by `$C071/$C073`, with RAMRD, RAMWRT, ALTZP, 80STORE, PAGE2, HIRES and both language cards per bank, exactly as [`demos/doom/tools/a2sim.py`](../../doom/tools/a2sim.py) models them. |
| Devices | `$C019`, keyboard `$C000/$C010`, Open and Solid Apple, the mouse card in slot 2 with its VBL interrupt, the memory API FIFO at `$CFF0-$CFF2` in slot 7 with the version 1 rules of `README_MEMORY_API.md` in appletini-one (COPY, FILL, PRIVATE, every validation error), and screen dumps of standard SHR and the PAL256 extension from aux bank 0 `$2000-$9FFF`. |
| Start-up | Load ca65 binaries at given addresses and banks, or run a ProDOS system file through a trap of the MLI entry, as `a2sim.py`'s `FakeProDOS` does. |
| Cost model | Every access classed as fast memory (main or base aux), extended memory through the one-line cache (hit, clean miss, dirty miss), a `$Cxxx` bus cycle, an SHR write that leaves bytes pending in the mirror, a mapping change that clears the TURBO caches, or a memory API request. Costs come from a parameter file with two profiles: F1.2.1 today, and F1.2.1 with the changes of the firmware design doc. Report time per frame and per phase in both. |

The parameters are derived from the RTL, as `docs/firmware/` explains, until
milestone 0 measures them. Say so in the output.

**Validation against `a2sim.py`.** `a2vm` has a compatibility mode that
counts cycles the way `a2sim.py` does. In that mode it runs the existing
Doom port's banked build for 20 rendered frames and must match `a2sim.py`
at every frame boundary: RAM of every bank, the screen, registers and cycle
count. The existing port and its tools are in [`demos/doom`](../../doom/README.md);
its README explains how to build it and run it with `tools/run_doom.py`.

**Acceptance for 3.1:**

1. Builds with no warnings; the 65C02 vectors pass, or each exception is
   listed with evidence.
2. The 20-frame comparison with `a2sim.py` matches exactly.
3. `a2vm` runs those frames at least 20 times faster than `a2sim.py`.
4. For the same 20 frames it reports frame time under both cost profiles.
   Today's profile must come within 25% of the 248 ms per frame measured on
   hardware, or the report must say which parameter is suspected.

### 3.2 The interpreter

`src/vm/`: a 65816 interpreter in 65C02 assembly that runs on `a2vm`.

- The virtual 65816 state lives in main zero page: A, B, X, Y, S, D, DBR,
  PBR, P, and the M, X and E flags.
- The virtual 24-bit address space maps onto the Appletini as
  ARCHITECTURE.md section 3.3 describes: a table from each virtual 32 KB
  half-bank to `$4000-$BFFF` of one RamWorks bank, with the special cases for
  virtual banks `$00`, `$01`, `$02` and `$E1`. For this milestone the table
  may be simpler, but it must keep far reads and writes behind one interface
  so the planner of milestone 7 can change it.
- Code is fetched through a cache of 256-byte pages in fast memory. A write
  to a cached page invalidates it, so self-modifying code stays correct.
- Every 65816 opcode in native and emulation mode, including decimal mode,
  MVN and MVP a byte at a time, WAI, STP, BRK, COP, RTI and interrupt entry.
- The interpreter's own code fits the budget of ARCHITECTURE.md section 3.2:
  4 KB of core in main language card `$E000-$FFFF` plus 4 KB of handlers in
  language card bank 1. If it cannot fit, say what it needs.

**Acceptance for 3.2:**

1. Correctness: the SingleStepTests 65816 vectors of milestone 2, run through
   the interpreter on `a2vm`, pass in registers and memory for every opcode
   in both modes. Cycle and bus records are not compared. Exceptions are
   listed with evidence, and the 44 known issues of milestone 2 are handled
   the same way.
2. Cost: the median and the range of 65C02 cycles per interpreted 65816
   instruction, by opcode and weighted by the instruction mix of
   `docs/PROFILE.md`, under both cost profiles. This replaces assumption P5
   of ARCHITECTURE.md section 6.
3. First contact with the game: the interpreter runs upstream's image, from
   the entry point, in lockstep with `ref816`. The comparison is of the
   virtual registers after every instruction and of every memory write, up
   to the first access to the IIgs I/O space. Report how far it got.
4. A unit test in `tests/` runs a sample of the vectors through the
   interpreter, and a `make` target runs all of them.

### 3.3 Independent review

As in 2.5: build from clean, rerun every acceptance test, look for shortcuts
that make a result untrustworthy, check the ground rules, and list real
defects most serious first.

## Milestone 0: hardware costs

This needs the physical Appletini and the owner, so it can run in parallel
with milestones 2 and 3. ARCHITECTURE.md section 12 has the file list.

- Timed loops: straight-line code in fast memory; a far read in the same bank
  and after a bank change; sequential and random extended-memory reads and
  writes; an SHR store burst followed by one `$Cxxx` access; memory API
  copies of 1 KB, 16 KB and 48 KB; code run from an extended bank.
- Each loop reports microseconds from the memory API's STATUS counter, and
  repeats within 5%.
- A standard 320-mode SHR picture with per-row palettes. Upstream uses
  standard SHR; the existing Doom port uses only the PAL256 extension.

## Milestones 4 to 11

ARCHITECTURE.md section 8 defines deliverable and test for each. Two points
decided since it was written:

- `PROFILE.md` measures what the architecture assumed. Recompute the phase
  windows and the frame budget from it before milestone 7.
- Milestone 4 and later should design the frame around the firmware
  proposals below: keep `$C073` fixed inside a frame, and read extended
  memory through the `$C069` read bank if it is built.

## Related work outside this directory

| Item | Where | State |
| --- | --- | --- |
| Firmware design for faster extended memory and SHR (`$C069` read bank, lazy SHR mirror, relaxed PSRAM admission, and four more) | A Claude Doc in the owner's account, "vTW Memory Fast Path: Design". Its source material is [`firmware/`](firmware/). | Awaiting the owner's review. Nothing implemented. |
| Estimated effect of those changes on the existing port | Measured event counts in the model, costs derived from the RTL | +20% to +30% from firmware alone; up to about +50% with software changes |
| Firmware source | [hasseily/appletini-one](https://github.com/hasseily/appletini-one), `origin/main` at F1.2.1 | 21 of its 30 testbenches run under Verilator without Vivado, with a behavioural `LUT6` model |
| Existing Doom port | [`demos/doom`](../../doom/README.md), branch `claude/iigs-doom-port` | 4.03 FPS measured on hardware, E1M1 idle, TURBO |

## If a run was interrupted

Each milestone is built by a sequence of agents that do not commit. If the
work stopped partway:

1. `git status` in the repository. Uncommitted files belong to the milestone
   marked "Next" in the status table; its specification says which step
   writes which directory.
2. Run the unit tests and `tools/v816/imgmatch.py`. Earlier milestones must
   still pass: 0 differing bytes, and all tests green.
3. Treat every uncommitted file as unreviewed. Rebuild it and check it
   against the acceptance tests of its step before building on it.
4. `build/` can always be recreated with `tools/fetch_upstream.py` and
   `tools/ref816/fetch_vectors.py`.
