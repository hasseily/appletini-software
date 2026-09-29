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
| Nothing derived from upstream's `src/iigs/cal_integer.s` may leave `build/`: no copies, translations, counts or symbol values. | It is a copy of the Calypsi vendor runtime, licensed for that toolchain only. The port uses its own routines. |
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
| 2 | Reference machine runs the release; measured profiles | **In progress** since 2026-09-29. See "If a run was interrupted". |
| 3 | Target machine model with cost model; 65816 interpreter | Not started |
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
addresses to symbols through `build/linkmap.json`. Group `cal_integer.s` as
"vendor runtime" in anything written outside `build/`.

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

## Milestones 3 to 11

ARCHITECTURE.md section 8 defines deliverable and test for each. Two points
decided since it was written:

- The target model for milestone 3 can start from the existing port's
  `../doom/tools/a2sim.py`, which models the Appletini memory map on py65, at
  about 3.5 million cycles per second. The architecture proposes a C
  replacement called `a2vm` for speed.
- Milestone 4 and later should design the frame around the firmware
  proposals below: keep `$C073` fixed inside a frame, and read extended
  memory through the `$C069` read bank if it is built.

## Related work outside this directory

| Item | Where | State |
| --- | --- | --- |
| Firmware design for faster extended memory and SHR (`$C069` read bank, lazy SHR mirror, relaxed PSRAM admission, and four more) | A Claude Doc in the owner's account, "vTW Memory Fast Path: Design". Its source material is [`firmware/`](firmware/). | Awaiting the owner's review. Nothing implemented. |
| Estimated effect of those changes on the existing port | Measured event counts in the model, costs derived from the RTL | +20% to +30% from firmware alone; up to about +50% with software changes |
| Firmware source | [hasseily/appletini-one](https://github.com/hasseily/appletini-one), `origin/main` at F1.2.1 | 21 of its 30 testbenches run under Verilator without Vivado, with a behavioural `LUT6` model |
| Existing Doom port | [`../doom`](../doom/README.md), branch `claude/iigs-doom-port` | 4.03 FPS measured on hardware, E1M1 idle, TURBO |

## If a run was interrupted

Milestone 2 is built by a sequence of agents that do not commit. If the work
stopped partway:

1. `git status` in the repository. Uncommitted changes under `tools/v816/`,
   `tests/` and `README.md` are step 2.0. Anything under `tools/ref816/`,
   `coverage/` or `docs/PROFILE.md` is steps 2.1 to 2.4.
2. Run the unit tests and `tools/v816/imgmatch.py`. If the match is still 0
   differing bytes and the tests pass, step 2.0 may be complete; compare the
   code with the table in 2.0.
3. Treat anything under `tools/ref816/` as unreviewed. Rebuild it and check it
   against the acceptance tests of its step before building on it.
4. `build/` can always be recreated with `tools/fetch_upstream.py`.
