# Doom code banking assessment and implementation

Assessed and implemented 2026-09-24. The default real-game build now uses the
first layout below: shared main-memory game data and permanently loaded
auxiliary language-card code, with phase snapshots for renderer coexistence.
The original assessment is retained after this implementation note.

## Implemented layout

`make` defaults to `BANKED=1`. `tools/bank_game.py` generates seven LC banks:
96 collision, 97 actors, 98 AI/sight, 99 specials/movers, 0 control/view/damage,
101 setup/spawn, and 102 player/weapons. Small common helpers, level accessors
and state tables are shared or selectively duplicated. Stable main-memory
gates preserve function pointers and nested callback behavior.
Control uses base auxiliary LC for fast code, zero page and stack; bank 100
stages its image during loading. `CONTROL_BANK=100` selects the former extended
placement for hardware comparisons. The lower RAM of bank 0 still holds SHR.

RAMRD/RAMWRT remain off for ordinary game accesses; ALTZP selects the executing
bank's LC, zero page and hardware stack. `gamebanks.s` preserves 54 logical ZP
bytes, registers, the updated shared C-stack pointer, and suspended per-bank
hardware stacks. It routes IRQ service through the main context. NMI sources
must remain disabled. The emulator now models per-RamWorks-bank auxiliary LC;
its instruction fetches use the same mapping as its data accesses.

The complete linked implementation resolves the data/renderer problem:

- Main game data and the 2 KiB C stack coexist with permanently banked code.
  The renderer uses the same main RAM in its own phase. Game/renderer backing
  storage is in banks 125/122; all due tics and packet preparation share one
  game phase. Only mutable regions are saved on each handoff; read-only data
  is restored from its initial backing image, the view is cleared, and inactive
  C-stack contents are not copied.
- Bank 1 holds far blocklink heads at `$0200` and 3,060 bytes of object metadata
  at `$6000`. Math tables and far workspace use bank 127.
- The complete 2,600-byte view packet is built in spare control-bank LC RAM and
  copied through main scratch into bank 124. Path-intercept scratch is reused
  during packet preparation. Smaller level caches retain their correctness.
- Actor capacity remains 160 × 64 bytes; statics keep near pointers; the packet
  retains 128 things and the C stack retains all 2,048 bytes. No thinker
  reordering or actor-cap reduction was used to fit the build.
- Bank 126 holds the specials journal and initial snapshots. Rollover skips
  banks 125, 124 and 122 and stops above the map data/renderer-cache allocation.
- `DOOM.BANKS` supplies code/table/metadata preloads. The loader installs all
  auxiliary LC images after its last ProDOS call. `check_link.py` validates
  final images, preloads, bank sizes and the conservative level/actor budget.

The hot static-object loop now uses 275 bytes of main game code, retaining
actor bank 97's context through a three-byte jump wrapper. Its instruction
fetches use main RAM; local helper calls keep their existing bank bindings.

With the debug readout, the link has a 31,780-byte shared main arena and a 1,176-byte margin over
its conservative level-plus-160-actor requirement. The control LC bank uses
11,963 of its 12,282 non-vector bytes, including packet storage. These current
figures are checked by `link-report.json`; earlier estimates below are historical.

Tests now cover all nine converted maps at Nightmare, the full actor pool and
stack guards, differential E1M1/E1M8 gameplay, nested bank calls and IRQ
boundaries, far data, snapshot rollover, and complete model boot plus live
input-driven game/render frames. This replaces the assessment's unimplemented
checklist. See [STATUS.md](STATUS.md) for scope and remaining UI/audio work,
and [../README.md](../README.md) for build/run commands.

The first integrated profile, before phase-copy and packet optimizations, was
about 12 M model cycles per rendered frame. Gateway overhead was substantial,
but the renderer and phase copying were larger total-frame costs. Subsequent
optimization measurements are recorded in STATUS.md. These are Python harness
cycle counts, not physical TURBO FPS: the mode named `turbo` uses a nominal
75 MHz budget and fixed I/O surcharge, without the actual PSRAM/cache and
batched-video timing. A conventional 33 MHz emulator run is separate again.
TURBO batches video writes; target firmware behavior still needs measurement.

## Original assessment (before the implementation above)

The figures and candidate comparisons below record the initial overflowing
layout and the first standalone proof. Its proposed work has since been
implemented as described above; it is not a list of current blockers.

## Recommendation

Pursue permanently loaded code banks with selective duplication of small
helpers. Reserve copied overlays for infrequent work such as level setup.
The earlier rejection of banked code in `STATUS.md` was too broad: the whole
engine does not need to be duplicated into every bank.

Two layouts deserve consideration:

1. **Main-memory game data, auxiliary language-card code.** This cleanly preserves
   ordinary data pointers across code switches. A standalone executable proof
   validates nested calls with bank-local zero page and hardware stacks. It
   requires a solution for sharing main memory with the renderer.
2. **Larger auxiliary code banks with invariant main-memory apertures.** Use
   80STORE plus the main language card for shared state and gateways, keeping
   zero page and the hardware stack in main memory. This avoids banked stack
   context transfers, but requires more far-data work and careful placement.

At this stage neither layout had a complete linked Doom memory budget. Banking
addressed code capacity; shared mutable data and renderer coexistence were
separate requirements, subsequently resolved by the implementation above.

## Pre-banking footprint

The existing GAME region is `$0200-$B7FF`: 46,592 bytes. Its 2,048-byte software
stack occupies `$B800-$BFFF`.

| Current game segments | Bytes |
| --- | ---: |
| CODE, including linked cc65 support | 51,040 |
| RODATA | 6,919 |
| BSS | 13,322 |
| STARTUP and DATA | 16 |
| **Resident total before dynamic level/actor allocation** | **71,297** |
| GFAR, moved out after loading | 8,194 |
| GOVL, setup overlay | 5,347 |

The smaller code total in the old `STATUS.md` excluded some runtime support.
The map measured here described an overflowing link; its segment sizes were
useful measurements, but its overflowing addresses were not a runnable layout.

Raw code naturally groups as follows:

| Candidate group | Modules | Code bytes |
| --- | --- | ---: |
| Collision | a_map, a_maputl | 9,953 |
| Actors and player | a_mobj, a_user | 9,091 |
| AI, sight, damage | a_enemy, a_sight, a_inter | 10,133 |
| Specials and movers | a_spec, a_movers | 8,417 |

These are starting partitions, not final bank images. Constants, gates, runtime
support and duplicated helpers must also fit; some groups will need splitting.
The auxiliary LC gives **12 KiB simultaneously visible**, not 16 KiB. Its other
4 KiB physical half shares `$D000-$DFFF` and needs its own switching discipline.

## What the machine can map

RAMRD selects both instruction fetches and ordinary data reads. Setting RAMRD
to auxiliary and RAMWRT to main does not provide general auxiliary code with
main data: data reads still come from auxiliary memory.

The local hardware mapper supports the useful alternative:

- RAMRD and RAMWRT OFF: `$0200-$BFFF` reads/writes use main RAM.
- ALTZP ON: zero page, page 1, and the language card use the auxiliary bank
  selected by `$C073`.
- Code executes at `$D000-$FFFF`; an invariant main-memory gateway changes
  `$C073`, then enters the target routine.

Thus actor pointers, thinker links, the software stack and mutable game data
can retain their addresses while code banks change. Load code into its banks
once, then switch mappings during gameplay.

The second layout uses 80STORE ON, PAGE2 OFF, and HIRES ON. This leaves main
`$0400-$07FF` and `$2000-$3FFF` visible while the remaining lower memory selects
auxiliary RAM. Together these apertures provide 9 KiB of invariant storage.
With ALTZP OFF, main zero page, the hardware stack and main LC also remain
invariant. The apertures replace auxiliary memory at those addresses; they do
not add 9 KiB to the CPU's visible address space. Display/presentation routines
must preserve or deliberately restore these switch settings.

## Nested calls are necessary and mechanically possible

The engine cannot simply run one whole subsystem, switch, and run the next.
Examples include movement -> collision -> damage -> state action -> movement,
and sector movers calling actor logic which can trigger more sector actions.
Reordering thinkers to make bank batches would change gameplay and random
number consumption.

A standalone proof in `/private/tmp/doom-bank-proof` executes actual 65C02
instructions with distinct auxiliary LC, zero-page and stack images:

- A -> B -> A callback, then returns to B and the original A.
- Per-bank saved hardware stack pointers, including reentry into a suspended
  bank; the hardware stack contents are not copied on every switch.
- A shared main-memory software stack.
- Transfer of all 34 logical zero-page bytes: 8 game pointer bytes plus 26 cc65
  bytes. The callee's updated software-stack pointer returns to the caller.
- Register/carry results and shared data checks.
- 2,383 independent IRQ injection positions, including pending IRQ requests
  during masked transitions.

All cases passed. This establishes the mechanism, not Doom integration or
performance. The integration checklist at that point was:

- Stable gateway addresses in action tables, thinker function pointers and
  callback comparisons; direct private calls can remain within a bank.
- Stack guards and measured stack depth for each bank.
- Keeping `w_ldi` resident or duplicated without a switch on entry: it reads
  inline bytes through the caller's return address.
- A kernel bridge for far-data access. The current helpers assume game bank 1;
  they must restore the actual code bank and the appropriate stack/ZP context.
- IRQ routing for both GAME and kernel far-copy mappings, a common VBL counter,
  and NMI/vector handling. A main-low IRQ handler is not invariant while RAMRD
  selects auxiliary memory.
- Correcting `a2sim.py`: its current LC model distinguishes main/aux but does
  not select auxiliary LC by the RamWorks bank as the hardware mapper does.

## Partition profile

An instrumented flat host harness ran 174 game tics, including a 30-tic sample
with 29 monsters awake. The profiler classified executed instructions by the
candidate groups above. Arithmetic/runtime helpers were treated as common.

With level access and random-number support common, the monster sample still
needed about 630 inferred code-bank selections per tic. Making another **522
bytes** of `a_maputl` helpers common reduced this to about **35**:

- 332 bytes from `call_ax` up to `_P_PointOnLineSide`, including small arithmetic
  and object-access helpers.
- 190 bytes from `_P_NewValidcount` up to `pit_add_line`.

| Sample | Mean inferred selections/tic | Maximum |
| --- | ---: | ---: |
| Idle | 8.2 | 21 |
| Walking | 7.5 | 13 |
| Firing | 10.4 | 29 |
| 29 monsters awake | 35.0 | 63 |

Render-packet preparation similarly dropped from 2,469 inferred selections to
one. `_P_SetSectorLight`, currently in the setup module, must remain available
during gameplay.

These are **control-flow estimates**, not measured bank operations. The profiler
keeps the selected bank through common code and changes it when execution next
requires another bank. A gateway that always restores the caller's bank can
perform additional switches when returning through common code. Far-data bank
switches, context-copy costs and hardware/cache delays are not included.

The common support assumed here is not free: fixed math, gwork, level access,
random, the 522-byte helper set and cc65 runtime total about 8 KiB of code,
before game control and gateway code. Some must be shared; some can be duplicated
at suitable addresses in multiple code banks. The eventual linker layout must
account for every byte. Artifacts are in `/private/tmp/doom-bank-profile`.

## The original data and renderer problem

Moving executable code out does not by itself make the game fit:

| Main-data requirement for LC code banks | Bytes |
| --- | ---: |
| Current BSS | 13,322 |
| Largest measured non-actor level allocation | 23,936 |
| Existing limit of 160 actors at 64 bytes each | 10,240 |
| **Subtotal** | **47,498** |
| Main `$0200-$BFFF` capacity | **48,640** |

That leaves only 1,142 bytes before the software stack, common helpers, gates
and any resident constants.

The 2,600-byte render packet is a good first relocation candidate: write it to
a dedicated auxiliary handoff area. Currently the renderer copies only its
40-byte header and reads thing records from game bank 1 later; there is no
second complete near packet to simply delete. Its readers and the packet
builder must change. Removing this packet from near BSS and adding the existing
2,048-byte stack leaves just 1,694 bytes, so additional relocation is essential.

Candidates include static things, blocklink heads, immutable object/state
tables, and revised level caches. Each needs an accessor/handle design or
careful ownership; moving pointer-bearing objects far is not a linker-only edit.
Prefer this work before reducing actor limits or changing thinker semantics.

Main RAM is currently occupied by the renderer. The LC-code proposal therefore
also needs one of:

- Phase sharing: preserve game state in backing banks while rendering, restore
  it for one or more game tics, then restore required renderer contents. Discard
  frame scratch that will be regenerated; preserve persistent renderer state.
- A renderer layout that also uses banked code/data, reducing the overlap.
- The 80STORE aperture design, limiting the shared main area and accepting more
  far-data access in the game.

The renderer has roughly 20 KiB of lower-main buffers including its 13,440-byte
view buffer. Borrowing some of that scratch is less expensive than replacing
all main memory, but does not alone accommodate the whole game. Full phase
replacement can require roughly 100 KiB or more of movement per frame, depending
on placement and persistence. At the current direct-copy loop's approximate
16 CPU cycles/byte that is around 1.6 million CPU cycles, before target-specific
memory and synchronization effects. This is a material cost, not a demonstrated
frame-rate result. A concrete overlap map must precede any claim of viability.

## Where copied overlays help

Cold setup/intermission code can reuse one execution window. Repeatedly copying
large hot modules is unattractive with the current call graph: loading the
9,953-byte collision group and restoring the 9,091-byte actor/player group moves
19,044 bytes for one excursion. At 29 such excursions per tic that would be
552,276 bytes. This illustrates the risk; the profile does not establish that
every actor takes that exact path every tic.

Prefer code loaded once into several banks, then switched on demand. Duplicate
small heavily shared routines to reduce switching. Keep genuinely cold overlays
as an additional capacity tool.

## Original implementation milestones

The LC layout and mapped integration are now implemented. The alternate
80STORE design was not needed; target performance measurement remains open.

1. Produce a complete linker budget for both the LC-code and 80STORE layouts,
   including common helpers, constants, stacks, gates, worst measured level,
   actor capacity, handoff storage and renderer overlap.
2. Correct the emulator mapping and integrate a representative nested chain
   through actors, collision and AI, preserving the flat harness's game results.
3. Benchmark code/ZP/stack access, far-data calls and phase handoff on the
   **actual target TURBO implementation** before choosing the final layout.

TURBO batches video writes. No conclusion here assumes each video write waits
for a synchronous 1 MHz motherboard transaction. The sibling hardware checkout
and older port notes do not establish the user's current TURBO batching or
synchronization behavior. Its address mapping informs the design, while its
small RamWorks cache makes actual target measurements especially important for
auxiliary LC instruction fetches and bank-local zero-page/stack traffic.
