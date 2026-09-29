# src/vm: the 65816 interpreter

Tier 0 of the virtual 65816 machine ([`ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)
sections 1 to 3, [`MILESTONES.md`](../../docs/MILESTONES.md) 3.2): an
interpreter of the whole 65816 instruction set, written in 65C02 assembly
for ca65 (cc65 2.18), that runs on the Appletini's W65C02S. It runs cold
code, code with unclassified self-modification and anything the
translator of milestone 6 refuses.

| File | What it is |
| --- | --- |
| `vm.s` | The unit: the configuration, the zero page, the RAM, the interface; it includes the others |
| `core.s` | Entry points, the dispatch loop, events and interrupt entry, the code page cache, P in and out, the dispatch table |
| `modes.s` | Addressing modes, operand reads and writes by width, the stack |
| `far.s` | The far layer: the translation of virtual addresses and every access to virtual memory |
| `alu.s` | The operations (loads, stores, arithmetic in binary and decimal, compares, shifts, read-modify-write, transfers) |
| `handlers.s` | The 256 opcode handlers, `h00` to `hFF` |
| `vm.cfg` | ld65's configuration: where each part goes, and the budget of each |
| `Makefile` | Builds into `build/vm`; runs the checks below through `tools/a2vm` |

    make -C src/vm              # build/vm/vm.bin.{d000,e000,f000}, vm.lbl, vm.map, vm.lst
    make -C src/vm sizes        # each part against its budget
    make -C src/vm sample       # 20 cases of each vector file (10,240)
    make -C src/vm vectors      # all 5,120,000 SingleStepTests 65816 cases
    make -C src/vm selftest     # traps, vm_run, and the lockstep with ref816
    make -C src/vm contact      # the first contact with the game (below)

The vector targets need `python3 tools/ref816/fetch_vectors.py` first.
The checks run the interpreter on `a2vm` through `tools/a2vm/vm816.c`,
below.

## Results

On an Apple M3 Pro, Apple clang 21, cc65 2.18:

| Check | Result |
| --- | --- |
| Build | No warnings. Core 1,797 bytes of 4,096 (1,782 and a 15-byte cold path after it); far layer 227 of 1,228; handlers 3,604 of 4,096; 5,628 bytes in all |
| SingleStepTests 65816 (`make vectors`), registers and memory, every opcode in both modes | 512 files, 5,120,000 cases: **0 failures**; 44 known issues, the same 44 cases and the same two rules as `tools/ref816` (below). 7.81 billion 65C02 instructions on a2vm, 1,525 a case (most of it the copy of the code page into the cache, which every case starts cold); 119 s |
| Lockstep with `tools/ref816`'s core (`make selftest`) | 2,000 random programs on 2 RamWorks banks, 4,962,875 steps (25,891 interrupts taken): 0 failures; 2,000 on 124 banks, 4,818,362 steps (31,403 interrupts): 0 failures |
| Self test | Traps of an unmapped half-bank and of an unmapped page (read, write, fetch), the program counter after a fetch trap (a jump into the page, to its first byte, a fall-through and an operand running into it) and a `vm_run` after one without `vm_import`, handlers that return, `vm_run`: 0 failures |
| Unit tests (`tests/test_vm.py`) | 15 tests: build, budget, reproducible build, fixed entry points, a handler for every opcode, a vector sample (2,560 cases), lockstep, self test, and six deliberate bugs the checks must see |
| First contact with the game (`make contact`, `tools/a2vm/game816.c`) | Upstream's release image from its entry point, through the game's map, in lockstep with `tools/ref816`'s IIgs: 322,215 instructions identical in registers and writes (`crt0`'s clearing of the BSS, then `main`), up to the first access to the IIgs I/O space (a read of `$E0:C036`), where the interpreter traps at the same address |
| The game's own instructions (`tools/a2vm/game816.c`, samples) | 56,167 instructions sampled by `ref816` from E1M1 standing still and the title demo, run one by one with the game's map: 0 differences |
| Cost | [`docs/INTERPRETER.md`](../../docs/INTERPRETER.md): about 300 to 320 65C02 cycles an instruction of the game with the code cache, 5.3 to 5.7 µs under F1.2.1 and 4.4 to 4.6 µs with the firmware changes, 1.4 to 1.8 times assumption P5 |

**The known issues** are the two rules of `tools/ref816/vectors.c`, with
the same evidence: `JSR (a,x)` in emulation mode with S = `$0100` (43
cases: the set wraps the second push to `$01FF`, the chip pushes to
`$00FF`), and `SBC (d,x)` in emulation mode with DL = 0 and the pointer at
the page's last byte (1 case: the set reads the pointer's high byte from
the next page, the chip wraps). The interpreter does what the chip and
`ref816` do, and the harness counts the cases a rule picks as known only
when they differ from the set; each is run and listed.

Cycle and bus records are not compared: the interpreter makes the 65816's
accesses to memory, but not its cycles. Its cost, per opcode, on the
game's own instructions and under the two cost profiles, is in
[`docs/INTERPRETER.md`](../../docs/INTERPRETER.md), which
`tools/a2vm/interpreter_report.py` writes.

## The state

The virtual 65816 lives in main zero page (`$50-$AF`, 62 bytes used):

| Symbol | What |
| --- | --- |
| `vA`, `vX`, `vY`, `vS`, `vD` | 16-bit words, low byte first (`vA+1` is B). With the index flag set the high bytes of X and Y are zero; in emulation mode S is `$01xx` |
| `vDBR`, `vPBR`, `vE` | Bytes; E is 0 or 1 |
| `vm_p`, `vm_pc` | P and PC as the host sees them, read by `vm_import` and written by `vm_export` |
| `vpcl`, `vpch` | The program counter less one: the address of the last byte fetched |
| `vN`, `vV`, `vZ`, `vC`, `vMX`, `vP` | P in pieces: N is bit 7 of `vN`, V bit 6 of `vV`, Z is set when `vZ` is zero, C is `vC` (0 or 1), M and X are bits 7 and 6 of `vMX`, `vP` holds D and I |

P in pieces lets an 8-bit load set N and Z with two stores and lets a
branch test one byte; P is composed only by PHP, interrupts, REP, SEP and
`vm_export`. `vMX` puts M and X where `BIT` finds them (N and V), so a
handler picks its width with one `BIT vMX`.

**The program counter less one.** The dispatch loop and the handlers fetch
with `INY` then `LDA (cpg),Y`; a carry out of Y is the only place where a
fetch leaves its page, and the next page is loaded there, when the byte
is needed. A jump, branch or return only records that the page changed
(`EV_PAGE`); the page is looked up at the next opcode fetch. So the
interpreter never reads a byte the 65816 would not: a jump into memory
that is not mapped traps only if the code there runs, and the vector
harness, which maps only what each case lists, sees every stray access.

## The dispatch loop and events

    loop:  LDA vm_event / BNE service      ; 5 cycles when nothing is pending
           LDY vpcl / INY / (page) / LDA (cpg),Y
           ASL / TAX / BCS / JMP (optab,X) ; or optab+256

Each handler is entered with Y the low byte of the stored program counter,
fetches its operands with the same `INY` and `LDA (cpg),Y`, stores Y in
`vpcl`, and ends with `JMP loop`. The accumulator operations share one
addressing-mode routine a column and one routine an operation, so their
handlers are `JSR mode / JMP operation`.

`vm_event` gathers everything that is not the next instruction:

| Bit | Name | Set by | Meaning |
| --- | --- | --- | --- |
| 7 | `EV_STOP` | `vm_step` | Leave `vm_run` or `vm_step` |
| 6 | `EV_STEP` | `vm_step` | Stop after one instruction or interrupt entry |
| 5 | `EV_HALT` | WAI, STP | `vm_state` is 1 (waiting) or 2 (stopped) |
| 4 | `EV_PAGE` | jumps | Look up the code page before the next fetch |
| 1 | `EV_NMI` | the host | An NMI edge, cleared when it is taken |
| 0 | `EV_IRQ` | the host | The IRQ line: a level, set and cleared by the host |

The rules are those of `tools/ref816/cpu816.c`: WAI waits until an
interrupt line is active, even with I set (it then goes on without taking
the interrupt); STP stops for good; NMI wins over IRQ; an IRQ is taken
when I is clear; interrupt entry pushes PBR in native mode, then PC and P
(B clear in emulation mode for IRQ and NMI, set for BRK), sets I, clears
D, clears PBR and loads PC from `$00:FFxx`. The service routine changes
`vm_event` only with `TSB` and `TRB`, so a host interrupt handler can set
`EV_IRQ` at any time.

## The far layer and the map

Every access to virtual memory goes through `far.s`:

| Routine | Does |
| --- | --- |
| `far_rd` | A = the byte at `ea` (3 bytes: offset, page, bank) |
| `far_wr` | The byte A to `ea` |
| `ea_next` | `ea` to the next byte of an operand by `eawrap`: `$00` carries into the bank (data), `$80` wraps in the bank (direct page, stack, `JMP (a)`, `(a,x)` in the program bank), `$40` wraps in the page (the direct page in emulation mode with DL = 0) |
| `resolve` | The translation of one virtual page (the last one is kept) |

This is the one interface of MILESTONES.md 3.2; the planner of milestone 7
changes the tables and the paths behind it, never its callers.

**The map** has an entry a virtual half-bank of 32 KB, 512 in all, in
`map0` (banks `$00-$7F`) and `map1` (`$80-$FF`) at index
`(bank * 2 + page / 128) mod 256`:

| Entry | Meaning |
| --- | --- |
| `$00-$7F` | A flat granule: RamWorks bank n, virtual page p at `(p & $7F) + $40`, so the half-bank is `$4000-$BFFF` of the bank (ARCHITECTURE.md 3.3, "granule rule") |
| `$80 + t` | Page table t (`t < 6`) at `$1A00 + 256 t`: two bytes a page, the space and the physical page |
| `$FF` | Unmapped: every access traps |

A space is a RamWorks bank `$00-$7F` (reached with RAMRD or RAMWRT and
`$C073`, physical pages `$02-$BF`), `$80` main RAM (reached directly) or
`$FF` (the page traps). A read of a RamWorks bank is `STA $C003`,
`LDA (rptr),Y`, `STA $C002`, and `STA $C073` before it when the bank is not
the one in `curbank`, the shadow of `$C073` (written before the switch, as
ARCHITECTURE.md 3.4 requires). The interpreter itself runs in the language
card and zero page, which RAMRD and RAMWRT do not move.

**The game's map** (ARCHITECTURE.md 3.3), which the loader of milestone 5
will write on the Apple and which `tools/a2vm/game816.c` builds on the
host for the first contact and the samples, uses the page tables for the
special banks:

| Virtual | Entry |
| --- | --- |
| `$00:0000-$7FFF` | A page table: `$09-$0A` main `$14-$15`, `$30-$3F` main `$60-$6F`, pages below `$30` otherwise trap, the rest RamWorks |
| `$00:8000-$FFFF` | A page table: the code image and variables in RamWorks, `$C0-$CF` (IIgs I/O) trap to the platform layer |
| `$01`, `$E1` | One pair of page tables for both: `$0200-$BFFF` base aux, identity (SHR at `$2000-$9FFF`, the tables ARCHITECTURE.md 3.2 keeps at their upstream addresses above it); the rest trap. `$E0` traps |
| `$02` | Page tables: the hot extent in main RAM (near core), the other extents in RamWorks. Until the port lays out bank `$02` (milestone 5), `game816` maps it as two flat granules |
| `$03-$3F` | Flat granules, by ARCHITECTURE.md 3.3's table |

**Traps.** An access to an unmapped page jumps through `vm_trap_rd`
(returns the byte in A), `vm_trap_wr` (the byte in A) or `vm_trap_ex` (code
would run there; it must not return), with the address in `ea` (for
`vm_trap_ex`, the first byte of the page). After a fetch trap, `vm_export`
gives the program counter of the instruction that needed the page (for
`JSL` and `JSR (a,x)`, which push part of the return address before their
last operand byte as the 65816 does, `JSL` its bank and `JSR (a,x)` all of
it, the address of that byte, with those pushes done), and a later
`vm_run` looks the page up again. `vm_init` sets them to handlers that stop `vm_run` or `vm_step` with `vm_status` 1,
2 or 3; the platform layer will point the first two at its emulation of
the IIgs registers, and return.

## The code cache

Code is fetched from a copy of its 256-byte page in main RAM, `cpg`:

- **16 pages at `$8800-$97FF`**, tagged by physical page (space and page),
  so two virtual names of one page share one copy; replaced in turn.
- **Main RAM runs in place**: a page whose space is main is not copied.
- **Writes**: a count a physical page (`watch`, 256 bytes, by page XOR
  space) tells `far_wr` whether the page it wrote may be cached; if it is,
  the byte is written to the copy too. Write-through keeps the copy equal
  to memory, as an invalidation would, without fetching the page again:
  the game patches operand bytes of code it runs in loops (ARCHITECTURE.md
  2.7). Writes to main RAM need no check.
- **`vm_flush`** forgets every copy and translation; the host calls it
  after it changes the map or writes virtual memory itself.

## The host's interface

Entry points at fixed addresses (`JSR`):

| Address | Entry | Does |
| --- | --- | --- |
| `$E000` | `vm_init` | Once: empty cache, default traps, `$C073` = 0, RAMRD and RAMWRT off |
| `$E003` | `vm_flush` | After the host changed the map or memory |
| `$E006` | `vm_import` | `vm_p` and `vm_pc` into the interpreter, the mode's rules applied; clears WAI and STP |
| `$E009` | `vm_export` | P and PC back into `vm_p` and `vm_pc` |
| `$E00C` | `vm_run` | Run until an event or a trap handler stops it |
| `$E00F` | `vm_step` | One instruction, one interrupt entry, or one step of waiting |
| `$E012` | `vm_abort` | A = status: leave `vm_run` or `vm_step` now (for trap handlers) |

What the interpreter needs of the machine: ALTZP off, 80STORE off, RAMRD
and RAMWRT off when it is entered, the main language card readable with
bank 1 at `$D000`, and `$C073` equal to `curbank` (a host interrupt
handler that changes `$C073` restores it from `curbank`; one that runs
while the interpreter has RAMRD on must use only the language card and
zero page, as ARCHITECTURE.md 3.1 requires). 80STORE must be off because
the far layer reaches base aux memory with RAMRD and RAMWRT, and with
80STORE on those switches do not steer `$0400-$07FF` (nor `$2000-$3FFF`
with HIRES on), which PAGE2 then selects: the game's map puts virtual
`$01` and `$E1` `$0200-$BFFF` in base aux, so those pages would read and
write main memory.

## Memory used

| Where | What |
| --- | --- |
| Main LC `$E000-$E704` | Core, with the dispatch table (512 bytes) |
| Main LC `$F000-$F0E2` | Far layer |
| Main LC bank 1 `$D000-$DE13` | Handlers and operations |
| Main `$0050-$008D` | Zero page |
| Main `$1600-$17FF` | `map0`, `map1` (written by the host only) |
| Main `$1800-$1925` | Write watch, cache tags, trap vectors |
| Main `$1A00-$1FFF` | Page tables (6) |
| Main `$8800-$97FF` | Code cache (16 pages) |

These addresses are this milestone's choice, made so that the
interpreter runs on a2vm; they are not yet in ARCHITECTURE.md 3.2's map,
and two of them do not fit it:

- the 4 KB code cache at main `$8800-$97FF` lies inside phase window 2
  (`$8800-$BFFF`), which 3.2 gives to phase data;
- the 62 bytes of zero page exceed the 44 that 3.2 gives the interpreter
  (VM registers 16, far pointers 12, interpreter scratch 16).

The tables at `$1600-$1FFF` fall in 3.2's region for patch cells, the
write watch, line-cache tags and near core part 1, which 3.2 does not
divide further. The planner of milestone 5 must place all of them in the
map (`vm.s` and `vm.cfg`), and ARCHITECTURE.md 3.2 must then say where.

## The checks: `tools/a2vm/vm816.c`

`vm816` loads `build/vm` into a2vm's language card, and drives the
interpreter through stubs in main RAM (`JSR vm_flush`, `vm_import`,
`vm_step`, `vm_export`) on the exact W65C02S core. The interpreter it runs
is the one the game will run, byte for byte; only the map is the harness's.

- **Vectors.** For each case the harness maps the half-banks the case lists
  (four through page tables, as the game's special banks: `$00:0900-$0AFF`
  and `$00:3000-$3FFF` in main RAM, `$01` in base aux memory, identity;
  the others as flat granules) and leaves the rest unmapped, so a stray
  access traps. It writes the case's memory where the tables put it,
  runs one step (MVN and MVP: as many whole byte moves as the record holds,
  as `tools/ref816/vectors.c` does), and compares the registers, every
  byte the case lists, and every write: a2vm's write hook sees each CPU
  write, and one to virtual memory the case does not list, to the tables,
  to other main RAM, to the language card or to an I/O address other than
  RAMRD, RAMWRT and `$C073` fails the case.
- **Lockstep.** Random programs (random memory, so random instruction
  streams) on the interpreter and on `tools/ref816/cpu816.c`, compared
  after every step (registers and run state) and in all of memory at the
  end. Every half-bank is mapped onto a few RamWorks banks, so pages have
  several names and writes land in cached code often; the IRQ line and
  NMI are raised at random steps.
- **Self test.** Traps, handlers that return, and `vm_run`.

## Not done yet

- The game's map is built on the host only (`tools/a2vm/game816.c`); the
  loader of milestone 5 writes it on the Apple.
- No host interrupt handler yet: the host sets `EV_IRQ` and `EV_NMI`.
- Decimal mode is done a digit at a time in software (exact for invalid
  digits too) and is slow; upstream never sets D.
