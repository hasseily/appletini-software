# a2vm: the model of the Appletini target

`a2vm` is a fast model of the port's target, an enhanced Apple //e with
an Appletini card, to run port code on the host (milestone 3.1 of
[`docs/MILESTONES.md`](../../docs/MILESTONES.md)). Stage 3.1a built its
W65C02S core, checked against a public per-opcode vector set; stage 3.1b
the machine around it: the //e memory map with 128 RamWorks banks, the
devices, a trap of the ProDOS MLI, and a compatibility mode in which a run
matches the existing Doom port's model, `demos/doom/tools/a2sim.py`,
cycle for cycle; stage 3.1c its cost model, the time a run takes on the
card, access by access, under the firmware as it is (F1.2.1) and with
the changes of the firmware design (below, "The cost model"). Milestone 6
added what routine tests need (a write log, the lowest S, snapshots of
chosen ranges, events at the Nth visit of a PC) and the firmware
design's zero-page bank pair with two profiles, `f121zp` and `fastzp`
(below, "Milestone 6 additions"). All of it is opt-in: without the new
options every run is what it was, byte for byte.

| File | What it is |
| --- | --- |
| `cpu65c02.h` | The W65C02S core's interface: registers, bus callbacks, cycle kinds |
| `cpu65c02_core.h` | The core itself, included once per bus |
| `cpu65c02.c` | The core connected through function pointers, and the parts without bus cycles |
| `py65core.h` | The compatibility core: py65's 65C02, the core `a2sim.py` runs on |
| `a2vm.h`, `a2vm.c` | The machine: memory map, soft switches, keyboard, game port, mouse card, Phasor, memory API, `a2sim.py`'s timing, interrupt delivery and idle skipping |
| `prodos.h`, `prodos.c` | The MLI stand-in, `a2sim.py`'s `FakeProDOS` |
| `cost.h`, `cost.c` | The cost model: every bus access charged in fabric clocks of the Appletini, with its TURBO caches, RamWorks line cache, PSRAM admission, bus cycles, video mirror and memory API |
| `costs/appletini.json` | The cost parameters, each with its source in the firmware or `docs/firmware/`, and the profiles `f121` and `fastpath`, and `f121zp` and `fastzp` with the zero-page pair |
| `costs.py` | A profile as the "name value" lines `--cost` reads; `PROFILE+VARIANT` adds the variants (the slot-4 slowdown, NTSC) |
| `cost_report.py` | The report on the existing port: frame and phase times under both profiles, against the hardware measurement |
| `main.c` | The command line: start-up, runs, input events, snapshots, screen dumps, bus scripts |
| `shot.py` | A screen dump or snapshot to a PNG (standard SHR and PAL256), with zlib only |
| `doom.py` | Runs the existing Doom port (`demos/doom`) on a2vm, started as its `run_doom.py` starts it |
| `compare_a2sim.py` | Runs the existing port on a2vm and on `a2sim.py` and compares them (needs `build/venv`) |
| `py65_diff.py` | Compares the compatibility core with py65 on random cases (needs `build/venv`) |
| `py65check.c` | The compatibility core on a flat memory, for `py65_diff.py` |
| `fetch_vectors.py` | Fetches the SingleStepTests WDC 65C02 vectors into `build/vectors/` |
| `vectors.c` | Runs the vectors and compares state, cycle counts and the bus |
| `selftest.c` | What the vectors do not cover: IRQ, NMI, BRK, WAI, STP, reset, cycle kinds, the data_ea classification of every opcode against the Appletini core's states, `cpu65c02_run`, lengths, datasheet cycles, exhaustive decimal mode |
| `bench.c` | Instructions per second of the core on the host |
| `vm816.c` | The checks of the 65816 interpreter of `src/vm` on a2vm: the SingleStepTests 65816 vectors, a lockstep with `tools/ref816`'s core on random programs, and a self test ([`src/vm/README.md`](../../src/vm/README.md)); with `--cost`, the cost of each case under a cost profile |
| `game816.c` | The interpreter on upstream's game, with the game's map: the first contact (the release image from its entry point, in lockstep with `tools/ref816`'s IIgs up to the first I/O access), the game's own instructions sampled by `ref816` run one by one and measured, and the cost of a change of code page |
| `interpreter_report.py`, `interpreter_template.md` | Make those measurements and write [`docs/INTERPRETER.md`](../../docs/INTERPRETER.md) |
| `Makefile` | `all`, `selftest`, `vectors`, `sample`, `bench`, `compare`, `costreport`, `vmsample`, `vmvectors`, `vmselftest`, `contact`, `interpreter`, `clean`; builds into `build/a2vm` |

Build and check:

    python3 tools/a2vm/fetch_vectors.py
    make -C tools/a2vm clean all vectors selftest bench
    python3 -m unittest discover -s tests

Run the existing port (its build in `demos/doom/build/hardware-20260926-textured-pal`,
its data in `demos/doom/build/data`, the ROM from appletini-one):

    python3 tools/a2vm/doom.py --frames 20 --shot         # fast install
    python3 tools/a2vm/doom.py --frames 1 --prodos        # through the loader

The interpreter on the game (`game816`, with the memory image of
`tools/ref816/make_image.py`) and its cost report:

    make -C tools/a2vm contact           # the first contact, as JSON
    python3 tools/a2vm/interpreter_report.py [--run]   # docs/INTERPRETER.md

`tests/test_a2vm.py` tests the core and its harness; `tests/test_a2vm_machine.py`
the machine (below); `tests/test_a2vm_cost.py` the cost model;
`tests/test_a2vm_harness.py` the write log, the lowest S, range snapshots
and visit events; `tests/test_a2vm_zpbank.py` the zero-page pair;
`tests/test_interpreter.py` the cost measurements, `game816` and the
report. They build everything from scratch.

### The comparison environment

The comparisons with `a2sim.py` need its Python packages, py65 and
Pillow, which the port's own tools never import. They live in a virtual
environment under `build/`:

    python3 -m venv build/venv && build/venv/bin/pip install py65 Pillow
    make -C tools/a2vm compare           # 20 frames, the loader boot, then
                                         # 20 frames with the memory API and
                                         # the cost model on
    build/venv/bin/python tools/a2vm/py65_diff.py

Without `build/venv` the tests that need it skip with a message; the rest
of the tests run on the standard library alone.

## The W65C02S core

The core executes one instruction per call but makes every bus cycle of
the chip, one at a time, in the chip's order and at the chip's addresses.
On the 65C02 every cycle is a read or a write, the internal ones
included, so every cycle reaches a callback and adds one to `cycles`
first. Each callback gets the kind of its cycle:

| Kind | Cycles |
| --- | --- |
| `CPU65C02_OPCODE` | The fetch of an opcode (SYNC on the chip) |
| `CPU65C02_OPERAND` | The later bytes of the instruction, BRK's signature byte included |
| `CPU65C02_DATA` | Accesses whose value the instruction uses: operands, pointers, stack pushes and pulls, vectors |
| `CPU65C02_DUMMY` | Reads whose value the chip ignores: the extra cycles of implied, indexed, read-modify-write, stack, branch and decimal instructions, the discarded fetch of an interrupt entry, and the cycles of WAI and STP |

A flag, `CPU65C02_EA`, marks the cycles of the Appletini core's six
"data_ea" states (`w65c02_core.sv:1049-1069`), those at an instruction's
effective address: `CPU65C02_DATA_EA` for `ST_MEM_READ`, `ST_RMW_READ`,
`ST_MEM_WRITE` and `ST_RMW_WRITE`, `CPU65C02_DUMMY_EA` for `ST_RMW_MODIFY`
(the read-modify-write's second read) and `ST_DECIMAL_EXTRA` (the decimal
cycle of ADC and SBC, at `$007F` or `$0000` for their immediate forms).
Nothing else is EA: opcodes, operands, dummy reads of PC, the same-page
`STA a,X` false read of its target (`ST_INDEX_DUMMY`), zero-page
pointers, the zero-page reads of BBR and BBS, JMP `(a)` and `(a,X)`
pointers, the stack and the vectors. `CPU65C02_BASE_KIND(kind)` gives the
kind without the flag. The zero-page bank pair redirects only EA cycles;
`selftest.c` checks the flag on every opcode in both decimal modes
against a table of the core's decode and states.

The 65C02 makes no dummy writes. The kinds are what the cost model of a
later stage classes: the Appletini's core, in its TURBO mode, drops dummy
reads outside `$C000-$CFFF` (`README_TURBO.md` in appletini-one), and a
dummy read of a soft switch still switches it.

`cpu65c02_step` runs one instruction, an interrupt entry, or one cycle of
waiting or of being stopped. `cpu65c02_run(cpu, until)` steps until
`cycles` reaches `until`; a callback may lower `cpu->until` to end the run
after the current instruction. IRQ is a level with one bit per source
(`cpu65c02_set_irq`); NMI is an edge (`cpu65c02_nmi`).

**Two builds.** `cpu65c02_core.h` holds the whole core and is included
once per bus, with four macros: `C02_PREFIX`, `C02_LINKAGE`,
`C02_READ(cpu, address, kind)` and `C02_WRITE(cpu, address, value, kind)`.
`cpu65c02.c` includes it with the function pointers of `cpu65c02.h`; a
machine can include it with its own inline bus, and the kind is then a
constant the compiler folds. `bench.c` does both.

### What it follows

In order of authority:

1. **The Appletini's own core**, `hdl/apple/w65c02_core.sv` in
   [hasseily/appletini-one](https://github.com/hasseily/appletini-one)
   (`origin/main`, F1.2.1). It is the chip this models. Its README says it
   passes all 2,540,000 cases of the vector set below, bus cycles
   included, with one correction (below), and Klaus Dormann's functional,
   extended-opcode and exhaustive CMOS decimal tests.
2. **The WDC W65C02S datasheet** (westerndesigncenter.com), tables 4-1,
   5-2, 6-4 and 7-1.
3. **The [SingleStepTests 65x02](https://github.com/SingleStepTests/65x02)
   vectors**, directory `wdc65c02/v1`, at commit `2f6980a` (2025-05-10),
   the revision the Appletini core was checked against.

Where they differ:

| Case | Datasheet | Vector set | Appletini core | This core |
| --- | --- | --- | --- | --- |
| `$5C`, reserved NOP | 3 bytes, **8 cycles** (table 7-1) | 3 bytes, 4 cycles: two operand reads, then the last byte again | as the set | as the set and the Appletini core. The self test names the difference. |
| `STA a,X` and `STA a,Y`, index on the same page: the fourth cycle | not stated; table 7-1 says a page crossing reads the last instruction byte | reads the last instruction byte | reads the **target address**, the NMOS false read (`ST_INDEX_DUMMY`); its harness corrects these cases of the set (`scripts/test_w65c02_core.py`, `normalize_known_cycle_quirks`) | as the Appletini core. The harness lists the 10,029 cases as a known issue. |
| Decimal `ADC #` and `SBC #`: the extra cycle | one more cycle, address not stated | reads `$007F` (ADC) or `$0000` (SBC) | as the set | as the set |
| Decimal ADC and SBC on memory: the extra cycle | one more cycle, address not stated | reads the operand's address again | as the set | as the set |

Other behaviour the vectors do not reach, taken from the Appletini core
and checked by `selftest.c`:

- **Interrupts** are sampled at each opcode fetch with the flags the
  previous instruction left: an IRQ pending across `CLI` is taken right
  after it, with no one-instruction delay. The entry takes 7 cycles: the
  discarded fetch, a read of PC, three pushes (P with B clear), the two
  vector bytes; I is set and D cleared. NMI wins over IRQ.
- **BRK** reads its signature byte, pushes PC + 2 and P with B set, and
  takes the IRQ vector; D is cleared.
- **WAI** is the opcode fetch and a read of the next byte, then one cycle
  a step reading PC while waiting (3 cycles with the first waiting one, as
  the datasheet counts). An active IRQ or an NMI ends the wait at the end
  of a waiting cycle; with I set an IRQ resumes at the next instruction
  without being taken, otherwise the interrupt is entered in 6 more
  cycles.
- **STP** is the same two cycles, then one cycle a step until reset.
- **Reset** is 7 cycles: two reads at PC, three stack reads moving S down
  by 3, the vector at `$FFFC`. I is set, D cleared; A, X, Y and the other
  flags are kept. It leaves WAI and STP and forgets a pending NMI.
- **P** has bit 5 set and bit 4 clear in the register. PHP and BRK push
  bit 4 set, interrupts clear. The set gives bit 4 set in the initial P of
  some cases and expects it carried through; the core keeps any bit it is
  given, and PLP and RTI clear it.

Not modelled: the SO pin (not connected on the Apple //e), RDY and bus
stalls (the cost model will charge them), and the TURBO shortcuts of the
Appletini core (the cost model will charge them from the cycle kinds).

### Results of the core

On an Apple M3 Pro with Apple clang 21, `-O2`:

| Check | Result |
| --- | --- |
| Build | No warnings with `-std=c11 -Wall -Wextra -pedantic` |
| Vectors (`make vectors`) | 256 files (the 2 of WAI and STP are empty in the set), 2,540,000 cases: 0 state failures, 0 cycle-count failures, 0 bus failures; 10,029 known issues, all `STA a,X`/`STA a,Y` on the same page (5,022 and 5,007), where only the address of the dummy read differs; 0.2 s |
| Self test (`make selftest`) | All checks pass, including 262,144 decimal ADC and SBC cases against the Appletini core's formulation, and every opcode's base cycle count against the datasheet with `$5C` the only difference |
| Speed (`make bench`, 10<sup>9</sup> cycles) | Inlined bus: 217 to 220 million instructions a second (750 MHz of 65C02 cycles). Function pointers: 185 to 188 million, flat RAM or a machine-shaped bus with a page table, an I/O trap and counts by kind. The three runs end in the same state. |

The mix of the bench program is 3.45 cycles an instruction; per cycle,
29% opcode fetches, 29% operand reads, 26% data accesses, 16% dummy
reads.

## The machine

Everything follows `demos/doom/tools/a2sim.py` (its module doc and its
`Machine`, `MouseCard`, `Phasor`, `FakeProDOS` and `FakeSmartPortMemory`
classes), rule for rule, so that the two can be compared. Where
`a2sim.py` departs from the hardware, a2vm departs the same way; the
departures are listed below.

### Memory

| Area | Model |
| --- | --- |
| Main | 64 KB. `$0000-$01FF` from the selected aux bank with ALTZP; `$0200-$BFFF` reads from aux with RAMRD and writes to aux with RAMWRT, except that with 80STORE `$0400-$07FF` (and `$2000-$3FFF` with HIRES) follow PAGE2 |
| RamWorks | 128 banks of 64 KB (`--banks` 1-128), selected by writes to `$C071` or `$C073`: bank = (value & `$7F`) modulo the bank count. Bank 0 is the base aux memory. All 128 banks exist whatever `--banks` says, as `a2sim.py` creates any bank it is given data for |
| Language card | `$C080-$C08F`: bit 3 selects bank 1, `(low & 3) in (0, 3)` enables reads, write enable needs two reads of an odd address (a write resets the pre-write). With ALTZP off, main's card: 16 KB for `$C000-$FFFF` (bank 2 at `$D000`) plus 4 KB of bank 1. With ALTZP on, the selected aux bank's own `$C000-$FFFF`, bank 1 `$D000-$DFFF` at its physical `$C000-$CFFF` |
| ROM | 16 KB for `$C000-$FFFF` (`--rom`, the Apple //e enhanced ROM of appletini-one's `docs/`) |

A test harness may set `write_hook`, an observer of every CPU write (the
address, the storage byte it reaches, the value); it changes nothing, and
is NULL in every other run. `vm816.c` uses it to see each write the
interpreter makes, and `--write-log` to write its log.

Reads and writes go through page tables rebuilt whenever a switch that
moves memory changes; `$C000-$CFFF` and write-protected language-card
pages take a slow path. Writes are counted as `a2sim.py` counts them
(video writes to `$0400-$0BFF` and `$2000-$5FFF` of main, and to
`$0400-$0BFF` and `$2000-$9FFF` of aux bank 0; SHR writes the latter
above `$2000`).

### Devices

| Address | Model |
| --- | --- |
| `$C000`, `$C010` | Keyboard: a queue of taps, each due at a cycle (`key`), and a held key (`hold`, `release`) whose "any key down" bit shows in `$C010` |
| `$C000-$C00F` writes | 80STORE, RAMRD, RAMWRT, INTCXROM, ALTZP, SLOTC3ROM, 80COL, ALTCHARSET |
| `$C013-$C01F` | The status of the switches in bit 7, the keyboard latch in bits 0-6 |
| `$C019` | 0 in vertical blanking (the last 70 of 262 lines of a frame), `$80` otherwise |
| `$C029` | NEWVIDEO, read and write |
| `$C030` | Speaker, counted |
| `$C050-$C057` | TEXT, MIXED, PAGE2, HIRES |
| `$C061-$C063` | Buttons: Open Apple, Solid Apple, button 2 |
| `$C064-$C067`, `$C070` | Paddles: 1,400 cycles of the 1 MHz bus clock from the trigger |
| `$C0A0-$C0AF`, `$C200-$C2FF` | The Appletini mouse card in slot 2 (`mouse_card.sv`): status, position, buttons, sequence, clamps, commands, mode, acknowledge, its slot ROM. A VBL interrupt (mode bit 3) is raised at the start of each vertical blanking and delivered while I is clear, until the program acknowledges it |
| `$C0C0-$C0CF`, `$C400-$C4FF` | The Phasor in slot 4: mode switch, two 6522 VIAs (ports, directions, timer 1 as a free-running counter), four AY chips' registers through the VIA port protocol in Mockingboard and native modes, the SSI-263's phoneme timer. No sound, no timer interrupts |
| `$C700-$C7FF`, `$CFF0-$CFF2`, `$CFFF` | With `--amem`, the memory API of appletini-one's `README_MEMORY_API.md`, version 1, behind its raw FIFO transport, as `FakeSmartPortMemory` models it: the slot-7 ROM ID bytes, C8 selection and release, STATUS with the 32-byte capability block, CONTROL with COPY, FILL and PRIVATE, and every validation error: `$21` (unsupported selector, command or firmware), `$60` (unavailable), `$61` (header), `$62` (descriptor), `$63` (range), `$64` (overlap), `$65` (PRIVATE required). All descriptors are checked before any is executed. `--amem-unsupported` and `--amem-unavailable` select the two failing firmware answers |

### Time and interrupts

A frame is 1,250,000 cycles with `--speed turbo` (the default, `a2sim.py`'s
"historical synthetic budget") or 17,030 × N with `--speed N`. Line 0
starts a frame; vertical blanking starts at line 192. With `turbo` each
access to `$C000-$CFFF` adds 73 cycles (`--io-cycles` changes it), added
at the access, so a read of `$C019` sees them.

Each step does what `a2sim.Machine.step` does: the VBL event when its
cycle has come, then the mouse card's interrupt when it is pending and I
is clear, then the idle skip, then one instruction. `--idle PC:KIND`
declares an idle loop: when the CPU reaches PC and the conditions hold,
the clock moves to the next VBL (`vbl`) or the next line 0 (`line0`)
instead of the loop running, and the skipped cycles are counted.

### The two cores

`--core py65` (the default) is the compatibility core, `py65core.h`: it
does what py65 1.2.0's `MPU65C02` does, access for access and cycle for
cycle. `py65_diff.py` checks it against py65 itself on 5,120 single steps
(20 of each opcode) and 60 runs of 200 steps, comparing registers,
cycles, and every memory access with its address and value, in order.

`--core w65c02s` is the exact core of `cpu65c02_core.h`, one cycle a bus
access, dummy reads included. The machine is the same; the MLI trap is
taken at the step boundary (with the JSR's 6 cycles), and the mouse
card's interrupt goes to the core's IRQ line. It runs the existing port
(`doom.py --core w65c02s`) but is not compared with `a2sim.py`, which has
no such core.

### Where a2sim.py (and so compatibility mode) departs from the hardware

These are properties of the model the existing port was developed on.
a2vm reproduces them in compatibility mode; the cost model of a later
stage will not.

- **py65's cycle counts.** `DEC abs` takes 3 cycles, the read-modify-write
  `a,X` forms always 7, `BRA` 2 (3 across a page), `BIT a,X` no page
  penalty; decimal ADC and SBC take no extra cycle. The 62 opcodes py65
  leaves out (`BBR`, `BBS`, `STP` and the reserved NOPs) are two-byte
  NOPs of 0 cycles.
- **py65's accesses.** No dummy cycles at all (the W65C02S reads its
  operand's address again in read-modify-write instructions, so
  `INC $C083` enables language-card writes on the chip but not in
  py65); JSR pushes before it reads its operand's high byte; `(zp)` at
  `$FF` reads its high byte from `$0100`.
- **py65's flags.** Decimal ADC and SBC set N, Z and V from the binary
  sum, as the NMOS 6502 does; P keeps bit 4 (set by reset, PLP and RTI,
  cleared by an interrupt).
- **The I/O surcharge.** 73 cycles an access to `$C000-$CFFF` in `turbo`,
  instruction fetches from slot ROM included; none at numeric speeds.
- **Slot decoding.** `$C100-$CFFF` reads fall to the internal ROM unless
  the mouse card, the Phasor or the memory API answers; the Phasor
  answers at any address whose bits 8-10 are 4, `$CC00-$CCFF` included.
- **The VIAs' register 15.** A write to ORA without handshake (`$Cn0F`,
  `$Cn1F`, `$Cn8F`) changes nothing in `a2sim.Phasor`; the card's 6522
  sets ORA (`hdl/apple/via6522.v:149`), and the drivers send AY data that
  way. `--via-ora-nh` (off by default) follows the card.
- **The memory API.** `FakeSmartPortMemory` leaves the result fields of
  the capability block (offsets 16-31 but 20-21) at zero, keeps the ready
  bit set after the first request, and rejects with an assertion a
  request the README leaves undefined or tolerates: another command
  byte family than 2, nonzero parameter padding (the firmware ignores
  it), a STATUS with trailing bytes, a CONTROL whose length word differs
  from the bytes sent, a pop of an empty reply. a2vm ends the run there
  ("halt", reason `amem-malformed: ...`).
- **ProDOS.** `FakeProDOS` services `JSR $BF00` itself: the call's bytes
  and parameter block are read from main memory whatever the soft
  switches say, the call is taken during the JSR's operand fetch, and
  files live in the volume directory only.

### Where a2vm departs from a2sim.py

Only where `a2sim.py` would stop with a Python exception: a word read at
`$FFFF` (py65 indexes `$10000`; a2vm wraps), an MLI call whose buffer runs
past `$FFFF` (Python's bytearray would grow; a2vm halts with
`prodos-fault`), a volume `build_disk` cannot build (it raises; a2vm
halts). Files a program writes stay in memory (`FakeProDOS` can mirror
them to a host directory; a2vm cannot). `a2sim.py`'s logs of mouse and
AY accesses are counted, not kept. The text and HGR screens are not
rendered.

## Running it

    build/a2vm/a2vm --rom ROM [options]

`main.c` lists every option. The main ones:

| Option | What it does |
| --- | --- |
| `--image FILE` | Memory records, `A2VMIMG1` then records of kind (1 byte: 0 main, 1 aux bank, 2 main LC with `$C000-$FFFF` addresses, 3 main LC bank 1 with `$D000-$DFFF` addresses), bank (1), address (2), length (4) and the bytes, all little endian |
| `--load ADDR:FILE`, `--load-aux BANK:ADDR:FILE` | A binary into main memory or an aux bank |
| `--reg pc=HEX` (and `a x y s p`), `--switch NAME=N` | Registers; switches, language-card state, `bank`, `newvideo` |
| `--prodos FILE` | The MLI trap, with the files of FILE, one a line: `NAME TYPE AUX PATH` (hex type and aux), in the order of the volume directory |
| `--idle PC:vbl` or `PC:line0`, with `:main`, `:invbl`, `:eq=A,B` | An idle loop to skip, and when (ALTZP off; in vertical blanking; the main words at A and B equal) |
| `--boundary ADDR`, `--boundaries N` | A frame boundary (the CPU at ADDR after a step, ALTZP off), and how many to run |
| `--cycles N`, `--stop-pc ADDR[:main]` | Other ends of the run. Without `--cycles` a run stops at 20,000,000,000 cycles (about two minutes on the host) with end `cycle-cap` and exit status 3, so that a run whose boundary never comes (a bug) ends; `--cycles none` runs with no limit |
| `--every-limit N` | At most N snapshots or shots of each `pc ADDR@*` event (default 100, 840 MB of whole-RAM snapshots); the visit after them ends the run with an error (status 2) |
| `--input FILE` | Input events, below |
| `--snapshot-dir DIR`, `--snapshot-boundaries`, `--final-snapshot` | Snapshots: `NAME.json` (the state) and `NAME.ram` (main 64 KB, main LC 16 KB, main LC bank 1 4 KB, then the 128 aux banks) |
| `--state FILE` | The final state, as JSON, with the reason the run ended and its host time |
| `--bus-script FILE` | Run bus commands instead of the CPU (below) |
| `--ay-log FILE` | The AY log (below): each AY register write that reaches a chip, each chip reset, each interrupt and each RTI, with the time |
| `--via-ora-nh` | A write to a Phasor VIA's register 15, ORA without handshake, sets ORA, as the card's 6522 does (`hdl/apple/via6522.v:149`). Off by default: `a2sim.py` ignores the register, and the comparison with it must stay exact |
| `--phasor-mb-only` | The Phasor locked to Mockingboard mode, as the card's `audio_control` bit 26 does (`hdl/apple/mockingboard.sv:38-41`): accesses to `$C0C0-$C0CF` do not change its mode, so it keeps one AY behind each VIA. Off by default |
| `--irq-bounds LO-HI[,LO-HI...]` | Interrupt bounds (below): the address ranges (hex, at most 8) an interrupt handler may read or write; any other access halts the run |

**Input events**, one a line, `WHEN ACTION`. `WHEN` is `start`,
`boundary N` (after the Nth boundary's snapshot), `cycle N` (after the
first step that reaches cycle N) or `pc ADDR[:main][@N|@*]` (the CPU is at
ADDR after a step, with ALTZP off for `:main`: the first such visit, the
Nth with `@N`, every one with `@*`). Each event fires once (an `@*` event
at every visit), in the file's order among those due; several events at
one PC all fire at their visits, so a routine called K times needs one
call site, not K (`pc CALL@1 snapshot before1`, `pc CALL@2 snapshot
before2`, or `pc CALL@* snapshot before`). An `@*` event's snapshots and
shots are named `NAME-0001`, `NAME-0002`, by visit. Actions: `key K` (a tap, due now), `hold K`, `release`,
`mouse DX DY` (the PS's delta path), `mouse-to X Y`, `buttons L R`,
`oa 0|1`, `ca 0|1` (Open and Solid Apple), `snapshot NAME`, `shot NAME`
(a screen dump for `shot.py`: `A2VMSHR1`, NEWVIDEO, aux bank 0 then main
`$2000-$9FFF`), `stop`. K is a character or a number.

**Bus scripts**, for the tests: `read ADDR`, `write ADDR VALUE` (the CPU
bus, with every side effect), `peek KIND BANK ADDR`, `poke KIND BANK ADDR
VALUE` (storage without side effects; kinds `main`, `aux`, `lc`, `lc1`),
`map` (the page tables: what reads and writes of each page reach), `lc`,
`counts`, `clock N`, `run STEPS`, `reg NAME=HEX`, `press KEY CYCLE`,
`hold KEY`, `release`, `mouse DX DY`, `mouse-to X Y`, `buttons L R`,
`button N VALUE`, `dump FILE` (the RAM, as a snapshot's), `state`,
`cost` (the model's clock and counters; with the slot-4 slowdown on, also
`slow_hits`, `slow_cycles`, `slow_clocks` and `slow_left`); and for the
zero-page pair `read-ea ADDR` and `write-ea ADDR VALUE` (a data access at
an effective address, as the core's `ST_MEM_READ` and `ST_MEM_WRITE`
make it, which the pair redirects), `zpbank` (its state and counters),
`zpbank-arm 0|1`, `reset` (the CPU's RESET sequence, which turns the
pair off; the //e's switches are not reset, as `a2sim.py` has no RES#).

### The AY log

`--ay-log FILE` (milestone S2, for the music player of `src/sound`)
writes one line for each event below, in the order the machine makes
them. It only observes; without it nothing is written or changed.

    # a2vm ay-log 1 (tools/a2vm/README.md, "The AY log")
    # w CPU_CYCLES APPLE_CYCLE CLOCK CHIP REG VALUE
    # reset CPU_CYCLES APPLE_CYCLE CLOCK CHIP
    # irq N CPU_CYCLES APPLE_CYCLE CLOCK
    # rti CPU_CYCLES APPLE_CYCLE CLOCK
    # clock fabric 133.333333 MHz, apple cycle 131.2821 clocks
    reset 111 44 5903 0
    w 26649 1075 141255 0 0 0
    irq 1 1234567 12345 1620111
    rti 1236001 12400 1627811

| Line | When |
| --- | --- |
| `w` | An AY register write reaches a chip: a VIA's ORB write with function 6 (write) on a chip that is selected, as `a2sim.Phasor` decides it. `CHIP` is 0-3 (0 and 1 behind VIA-A, 2 and 3 behind VIA-B, the drivers' numbering), `REG` the chip's latched register (0-15), `VALUE` the byte (decimal) |
| `reset` | A VIA's ORB goes to reset (bit 2 low): both chips behind it are cleared; one line a chip |
| `irq` | The machine delivers an interrupt; `N` counts them from 1 (the state's `irqs`) |
| `rti` | An RTI instruction ran (logged after it) |

The time fields: `CPU_CYCLES`, the core's cycle count; `APPLE_CYCLE`, the
machine's 1 MHz bus clock (`a2vm_bus_clock`); `CLOCK`, the cost model's
clock in fabric clocks (133.333 MHz) when `--cost` is on, else `-`. With
`--cost-timed` the machine runs on that clock, so it is the time on the
card. The writes of an interrupt are the `w` lines between its `irq` and
the next `rti`; `tools/sound/run65.py` groups them so.

### Interrupt bounds

`--irq-bounds RANGES` (milestone S2) checks an interrupt contract such as
the music player's (`docs/research/native-sound.md` 4.3: the interrupt
touches only the zero page, the stack, the language card and I/O, so
RAMRD, RAMWRT and `$C073` may be anything when it comes). From the first
instruction of a handler to the end of its RTI, every bus access of the
CPU (opcode, operand, data, stack, dummy) must fall in one of the
ranges; the first that does not halts the run with `irq-bounds: read
$0843 in an interrupt, pc $E123` (state `end` "halt", exit status 1).
The interrupt entry's own cycles (its two reads of the interrupted
program's PC, the pushes, the vector) are not checked, nor is anything
outside handlers. It only observes: a run that stays inside is unchanged.
`tools/sound/run65.py` passes `0000-01FF,C0A0-C0AF,C400-C4FF,D000-FFFF`
(the zero page and stack, the mouse card, the Phasor, the card), which
also refuses a mapping switch in the handler.

## Milestone 6 additions

Each is opt-in; a run without the option writes the same state, the same
snapshots and the same cost report as before (`tests/test_a2vm_cost.py`
checks the existing port under every profile).

### Ranges

`--write-log` and `--snapshot-ranges` take RANGES: items separated by
commas, each `WHERE[:LO[-HI]]` with hex addresses (the whole of WHERE
without them), at most 256.

| WHERE | Storage | Addresses |
| --- | --- | --- |
| `main` | Main memory | `0000-FFFF` (`C000-FFFF` is never written) |
| `auxN`, `auxN-M` | RamWorks banks N to M (0-127; 0 is the base aux memory) | `0000-FFFF`; an aux bank's language card is its `C000-FFFF` (bank 2 at `D000`, bank 1 at `C000-CFFF`) |
| `lc` | Main language card: `$C000-$FFFF` as a2sim's `lc[False]`, bank 2 at `$D000` | `C000-FFFF` |
| `lc1` | Main language card bank 1 | `D000-DFFF` |
| `cpu` | The CPU's address, whatever it reaches (I/O, a write-protected card): write log only | `0000-FFFF` |

A storage range holds a write by the byte it reaches (so a write the
zero-page pair redirects is in `aux5`, not `main`); a `cpu` range by its
address.

### The write log

`--write-log RANGES` writes a line for every CPU write that reaches the
ranges, to `--write-log-file FILE` (default `writes.log` in the
`--snapshot-dir`). It only observes; the state gets `write_logged`, the
number of lines. `--write-log-limit N` bounds the log at N lines (default
10,000,000, about 500 MB): the write that would be line N + 1 halts the
run (end `halt`, exit status 1, the halt naming the limit).

    # a2vm write-log 1 (tools/a2vm/README.md, "The write log")
    # ranges main:4000-40FF,aux0:4000,cpu:C004-C005
    # w CLOCK CPU_CYCLES PC ADDRESS STORAGE BANK OFFSET OLD NEW
    w 12 12 0805 4000 main 0 4000 11 11
    w 16 16 0808 C005 io - - - 11
    w 20 20 080B 4000 aux 0 4000 00 11

(The first line is a store of the value already there.) `CLOCK` is the
machine's clock (the state's `cycles`; with `--cost-timed`
the cost model's clock, in fabric clocks) before the write, `CPU_CYCLES`
the core's cycle count, `PC` the instruction's (an interrupt entry's
pushes carry the interrupted PC), `ADDRESS` the CPU's; then the storage
the byte is in (`main`, `aux`, `lc`, `lc1`, or `io` for a write that
reaches none), its bank and offset in that storage (decimal bank, hex
offset), the value it held and the value written, in hex. Every write is
logged, the stores of the value already there included: that is what a
comparison of snapshots cannot see. Bus-script `write` and `write-ea` are
CPU writes; `poke` and the memory API are not.

`tools/native/replay_check.py` logs the ranges its replay may not write
(`tools/native/a2run.py` `stray_ranges`) and fails on any line inside a
call.

### The lowest S

`--lowest-s` adds to the final state (and the final snapshot) the lowest
S the run reached, the PC of the step that reached it (the instruction,
or the interrupt entry, that started there), its clock and the number of
steps; the start's S counts. `--lowest-s-in LO-HI[,LO-HI...]` (hex, at
most 16) also gives, for each PC range, the lowest S seen before or
after a step that started inside it: a routine's stack depth, with the
entry of an interrupt that lands inside it but not the handler's own
instructions (give the handler's range too).

    "lowest_s": {"s": 248, "pc": 2081, "cycles": 45, "steps": 10,
                 "ranges": [{"low": 2064, "high": 2069, "s": 250, "pc": 2065,
                             "cycles": 20, "steps": 4}]},

`s` is `null` for a range never entered.

### Range snapshots

`--snapshot-ranges RANGES` makes every snapshot (at boundaries, at events,
the final one) `NAME.json` and `NAME.img` in place of `NAME.ram`:
`NAME.img` is an `A2VMIMG1` image (the format of `--image`) with one
record for each range and bank, so `--image` loads it back. A full
snapshot is 8.4 MB; a tic's game state is a few hundred KB.

### The zero-page bank pair

The firmware design's pair (`docs/firmware/zpbank-spec.md` as corrected
by `zpbank-review.md`; the design document's change 5; `NATIVE.md` 4.5
and 15.1, main zero page only). It is not in F1.2.1. `--zpbank` arms it
(the firmware's kill switch on, which a PS profile key does on the
card); so do the cost profiles `f121zp` and `fastzp`. It needs the exact
core (`--core w65c02s`: the compatibility core does not class its
cycles) and 128 RamWorks banks. Armed, nothing changes until a program
writes `$C069`:

| Rule | Model | Source |
| --- | --- | --- |
| Enable | A CPU write of V to `$C069`: `$00` or `$FF` turn the pair off, `$01-$FE` make V the pair's first byte (`zp_rd`) and V+1 its second (`zp_wr`); every such write clears both registers. The write stays an ordinary I/O write (a bus cycle in the cost model); reads of `$C069` are unchanged | review section 2, findings 9; spec 2.2 |
| Watch | While the pair is on, a CPU write whose byte is main zero page (ALTZP off) to `zp_rd` or `zp_wr` loads that register; a write to aux zero page (ALTZP on, any `$C073` bank) does not; pokes and the memory API never do. The value applies at once (the RTL applies it one edge later; the first data access it can affect is 4 cycles after the write) | review finding 2 (D4 corrected); spec 2.3, 2.4 |
| Values | 1-126: the `$C073` bank of that number (physical bank value+1); 0 and 127-255 follow the switches | review finding 1 |
| Redirect | A data_ea cycle (the core's `ST_MEM_READ`, `ST_DECIMAL_EXTRA`, `ST_RMW_READ`, `ST_RMW_MODIFY` for reads, `ST_MEM_WRITE`, `ST_RMW_WRITE` for writes; `CPU65C02_EA` above) to `$0200-$BFFF` goes to the bank of `zp_rd` (reads) or `zp_wr` (writes) when that register is not 0, whatever RAMRD, RAMWRT, 80STORE and PAGE2 say. Never opcodes, operands, dummy PC reads, the same-page `STA a,X` false read, JMP `(a)` and `(a,X)` pointers, vectors, the stack, zero page, `$C000-$FFFF`. A redirected write is never a video write (its bank is PSRAM) | review section 2, findings 7, 8; spec 1.2 (D1), 3.1, 3.4 (D2); `globals.sv:263-269` |
| `$C071`, `$C073` | Leave the pair alone; a zero direction follows them | spec 3.4 |
| Reset | Off at power-on, at the CPU's RESET (`reset` bus verb) and when disarmed; kept across everything else (holds, speed changes) | spec section 4, review section 2 |

Counters in the state (`"zpbank"`, only with the pair armed) and in the
cost report (`zpb_*`): `$C069` writes, register loads, redirected reads
and writes (bus cycles, the RMW's second read and the decimal cycle
included), redirected accesses made with the PC in `$C100-$CFFF` or in
the ROM (a breach of the software contract: firmware running with the
pair set), and memory API requests made with a register nonzero.

**Cost.** A redirected access is charged as a RamWorks access of its bank
(5 clocks on a line hit, the path CAPTURE, TURBO_DONE, ROUTE, RW_LOOKUP,
RW_DONE of spec section 6), never a TURBO cache hit or fill; the pair is
not part of the translation state, so it never invalidates the TURBO
caches; the `$C069` write is an ordinary bus cycle (no private serve, no
barrier exemption: spec 2.2). The profiles:

| Profile | What it is |
| --- | --- |
| `f121zp` | F1.2.1 with the pair alone: every parameter f121's, plus `zp_pair` 1. One RamWorks line, so a copy between two banks misses on every byte |
| `fastzp` | The firmware design with the pair in place of the read bank: fastpath's parameters with `read_bank` 0 and `zp_pair` 1. NATIVE.md's "Design + pair" |

`zp_pair` is the one cost parameter that describes the machine as well
as its costs: a profile with it arms the pair, and `--zpbank` with a
profile without it is refused. `cost_report.py` runs `f121` and
`fastpath` only: the existing port never writes `$C069`, so the pair
profiles give the same run there (`tests/test_a2vm_cost.py`).

The pair is checked by `tests/test_a2vm_zpbank.py`: the enable, the
watch, the values, the scope and priority, the reset rules; the review's
cases (an aux zero-page write does not load the pair, `$FF` disables,
127-255 follow); the spec's detection probe as a program (present when
armed, absent otherwise); each of the 74 opcodes that address
`$0200-$BFFF` through a mode the pair can redirect, reading bank 5 and
writing bank 9 exactly as the core's data_ea table says; the same-page
`STA a,X` false read, JMP `(a)` and `(a,X)`, BRK and a read-modify-write
across two banks; and the cost rules. Not modelled: the RTL's one-edge
delay of a load (no instruction can see it), a SmartPort call's fallback
(a2vm's memory API reaches no zero page and ignores the pair, as the
card's does), the debug register and the feature bit.

## The comparison with a2sim.py

`compare_a2sim.py` starts the existing port's banked hardware build on
both machines as `run_doom.py` does: "fast" puts the data files, the code
banks and the images in place and starts at `kernel_start`
(`doom.Build.image` writes exactly what `run_doom.Doom.install_fast`
does, and the first comparison checks it); "prodos" boots `DOOM.SYSTEM`
through the MLI trap and the port's own loader. `a2sim.py` runs through
`run_doom.Doom` (its machine, fake ProDOS and idle hooks). Both get the
same input at the same frame boundaries (W held, mouse turns, the fire
button, Open Apple, a space tap, S held).

At the start, at every frame boundary (the CPU at `present_done` with
ALTZP off, the end of a rendered frame), optionally every N cycles, and
at the end, it compares the RAM of main memory, the main language card
and every RamWorks bank, byte for byte; every soft switch and the
language-card state; the registers; the cycle count; the time
bookkeeping (next VBL, idle cycles, interrupts, I/O accesses, video and
SHR writes); keyboard, buttons, paddles; every field of the mouse card,
the Phasor and the memory API; and the fake ProDOS (prefix, open files
and marks, the calls and their errors, every file's length and CRC). At
the last boundary it compares the screen `shot.py` renders from a2vm with
`a2sim.py`'s `shr_image()`, pixel for pixel. Then it runs a2vm again
without snapshots, checks it ends on the same cycle, and times it.

### Results

On an Apple M3 Pro, Apple clang 21, Python 3.14, py65 1.2.0, the existing
port's build `hardware-20260926-textured-pal` (build id `e2676d7e`):

| Run | Frames | Cycles | Comparisons | Result | a2sim.py | a2vm | Ratio |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| Fast install, `turbo` | 20 | 251,486,113 | 22 | match | 56.4 s | 0.815 s | 69x |
| Fast install, `turbo`, memory API | 20 | 217,367,454 | 22 | match | 49.3 s | 0.734 s | 67x |
| Fast install, `--speed 33` | 20 | 237,395,601 | 22 | match | 57.2 s | 0.890 s | 64x |
| ProDOS loader boot to the first frame, `turbo`, every 5 M cycles | 1 | 124,032,560 | 28 | match | 32.5 s | 0.418 s | 78x |
| Stage 3.1c build, fast install, `turbo` (the cost hooks compiled in, off) | 20 | 251,486,113 | 22 | match | 56.7 s | 0.958 s | 59x |
| Stage 3.1c build, fast install, `turbo`, memory API, cost model `f121` on (observing) | 20 | 217,367,454 | 22 | match | 49.0 s | 1.480 s | 33x |

The a2sim.py times exclude the comparisons; they run under the
comparison's loop, which checks for the boundary and the events after
each step as `run_doom.py`'s loop does (about 4.5 million cycles a
second). The a2vm times are its run loop alone (`host_seconds`); with
start-up and loading they are 1% to 4% longer. The loader boot makes 778
MLI calls; the memory-API run makes five requests at start-up (the probe
and the first phase swaps) and three a frame.

`py65_diff.py`: 5,180 cases, 44,815 accesses compared, 0 failures.

### The tests

`tests/test_a2vm_machine.py`:

- **Memory map**: all 64 combinations of 80STORE, RAMRD, RAMWRT, ALTZP,
  PAGE2 and HIRES, with each of the 8 language-card states (bank, read,
  write, set through `$C08x` reads) and 4 bank values (with 128 banks,
  and aliasing with 3), against a Python model written from `a2sim.py`'s
  rules: the page tables, then a read and a write of 23 addresses a
  combination through the bus, checked in the storage the model names,
  and the video and SHR write counts. The language card's switch
  sequence on 600 random accesses.
- **Devices**: switch status reads, `$C019` at the edges of vertical
  blanking with the surcharge counted first, keyboard taps and holds,
  buttons and paddles, the mouse card (ID bytes, moves, clamps, status,
  acknowledge), its VBL interrupt reaching a program.
- **Memory API**: each validation error, COPY and FILL, nothing written
  before every descriptor is checked, the FIFO transport, and the
  requests that end the run.
- **ProDOS**: a program making 42 MLI calls with hand-made expectations
  (errors, carry, data, marks, info, prefix, on-line, destroy, too many
  files, QUIT), and the volume directory against the existing port's
  `tools/build_disk.py` before and after the program changes the files.
- **Screens**: `shot.py` on hand-made standard and PAL256 screens.
- **With build/venv**, against `a2sim.py` itself: random programs of 1,200
  loads, stores and read-modify-writes over every soft switch, the slots
  and memory, with keyboard, mouse and button input between them, at
  three speeds (the whole state and RAM must match); the ProDOS program;
  60 random memory API requests; `py65_diff.py`; and short runs of the
  existing port (3 million cycles fast and through the loader, and one
  where a2vm is given a different I/O surcharge, which must be seen).

## The cost model

`cost.h` and `cost.c` charge every bus access of a run with what it costs
on the Appletini in TURBO mode, in fabric clocks (133.333 MHz), as the
vTW core routes it (`hdl/apple/vtw_core_top.sv` of appletini-one,
`origin/main`, F1.2.1). The parameters come from
`costs/appletini.json`; each cites the RTL line or the document in
`docs/firmware/` it comes from. **None has been measured on the card:**
they are derived from the RTL and the firmware documents, until
milestone 0 measures them.

| Access | What the model does | Clocks (F1.2.1) |
| --- | --- | --- |
| Fast memory (main, base aux, ROM) | The TURBO caches of `vtw_turbo_cache.sv`: a 32-word read cache indexed as the RTL folds the address, a 32-entry write page table; a video write never takes a fast entry | read hit 2, read miss 4, write hit 2, write miss 5, video write 6 |
| A dummy read | Omitted outside `$C000-$CFFF` (the TURBO core's shortcuts, `w65c02_core.sv:903-967`); kept, as a real access, in I/O | 0 |
| Extended memory (RamWorks banks 1-127) | The 8-byte write-allocate line (or 16 lines, fastpath), write-back; a miss is a PSRAM operation admitted once an Apple cycle inside a 40-clock window (`psram_simple.sv`), a dirty victim two | hit 5, clean miss 35 with the window open, about 131 sustained, dirty about 260 |
| `$Cxxx` | A real bus cycle launched at the next `drive_en`, answered at `data_en`; or a private shortcut: `$C011-$C01F` reads, the slot-7 SmartPort window, internal ROM | 122-253; private 3 to 6 |
| The video mirror | Each video write leaves a byte for the motherboard, "active" or deferred as `vtw_video_policy.sv` decides, coalesced while it waits. Active bytes go through the coalescer (`vtw_video_coalescer.sv`, every firmware since F1.1.0; `coalescer` 1): its scanner selects the dirty pages in address order, one page a clock, takes every byte of a selected page, dirty or not, in two clocks, and queues the dirty ones for the bus (508 entries before it reports full), which takes one an Apple cycle; the next `$Cxxx` access waits until the scan is done and the queue empty. An exposure access flushes every pending byte | 131.3 a byte when a page has 4 or more dirty bytes; at least 513 a page scanned below that, so a column of the 3D view (one byte a 160-byte row, 1.6 a page) drains at about 4 Apple cycles a byte |
| A mapping change | Clears both TURBO caches (and every ARM write to the shadow counts as one, as the card's counter does) | the misses that follow |
| A memory API request | The hold (the mirror and the line flushed first), then the ARM's work as `memory_api_hw.c` does it: AXI register accesses per 4 bytes of fast memory, one PSRAM line an Apple cycle by DMA, in 504-byte chunks | 0.135 us an AXI access, fitted to the hardware (below) |

The model **only observes**: it never changes what the machine does (the
one exception, `zp_pair` of the pair profiles, arms the zero-page pair:
"Milestone 6 additions" below). With
`--cost-timed` its clock becomes the machine's (the PAL video frame,
`$C019`, the mouse card's VBL interrupt and the idle skips follow it);
without it the model runs beside a2sim.py's timeline, and
`make compare` checks that a run with the model on still matches
a2sim.py byte for byte. Phases are the values the port's profiling build
writes to its `profile_stage` byte (`--cost-phase`).

    python3 tools/a2vm/doom.py --frames 21 --core w65c02s --amem --cost f121 --timed
    python3 tools/a2vm/cost_report.py          # both profiles, the tables below

### The two profiles

`f121` is F1.2.1 as it is. `fastpath` is F1.2.1 with the seven changes of
the firmware design. The design document ("vTW Memory Fast Path: Design")
was not read for this model; the seven changes and their effects are taken
from the corrected summaries of the reviews in `docs/firmware/`:

1. relaxed PSRAM admission while the vTW owns the bus (a miss 35 clocks);
2. a 16-line fully associative RamWorks line cache;
3. TURBO caches that survive mapping changes (checked against the
   physical page);
4. quiet RAMRD, ALTZP, `$C08x` and `$C071/$C073` (3 clocks), with a
   reconciler that replays them before any other bus access and flushes
   the aux mirror bytes before a bank replay (rules O1, O2, O4);
5. a lazy mirror class for SHR writes, flushed only by leaving SHR, a
   physical bank write or a hold whose destination is in the SHR range;
6. the private read bank `$C069` (the existing port never writes it);
7. `$C071/$C073` in `vtw_is_bank_steer` (no cost in TURBO).

### Results: the existing port, E1M1 standing still

The build `hardware-20260926-textured-pal` (`e2676d7e`, the v12 build
measured on hardware), fast install, memory API on, no input, the exact
W65C02S core, on the model's clock (`--cost-timed`). The first frame loads
the level; the 20 frames after it are reported. Each run takes 1.6 s on an
Apple M3 Pro.

| Profile | Mean ms a frame | Median | Range | Frames a second | Against 248 ms measured |
| --- | ---: | ---: | --- | ---: | ---: |
| f121 | 248.6 | 241.2 | 236.9-275.3 | 4.02 | +0.2% |
| fastpath | 188.6 | 188.9 | 184.3-194.5 | 5.30 | -23.9% |

**The f121 total is fitted, not predicted.** One parameter, `axi_us`, the
latency of the ARM's AXI register accesses, is set so that this frame
matches the 248 ms measured by host time. The copy phases rest on it: they
are almost all memory API requests (120,192 bytes a frame in three
requests), and the model charges them as `memory_api_hw.c` runs them, 6
register accesses per 4 bytes written to fast memory and 12 per 4 bytes
read. The only figure the firmware documents give, a code review's "~16K
added register reads add ~5-16ms" (0.305 to 0.98 us a read), does not fit
the capture:

| axi_us | f121 ms a frame | game_copy + render_copy ms |
| ---: | ---: | ---: |
| 0.100 | 238.6 | 38.3 |
| 0.120 | 243.6 | 43.3 |
| **0.135 (fitted)** | **248.6** | **47.0** |
| 0.140 | 249.6 | 48.2 |
| 0.160 | 253.1 | 53.2 |
| 0.200 | 263.6 | 63.1 |
| 0.305 | 289.8 | 89.1 |
| 0.980 | 457.3 | 256.4 |

Two routes give the same value. The frame matches 248.0 ms at 0.133 us.
The copy phases match the hardware's at 0.137 us: its VBL-sampled 40.5 ms
plus the 6.9 ms a frame that sampling loses, because the ARM's holds merge
VBL interrupts (its VBL counter lost 1.7 s of 60). Milestone 0 measures
`axi_us` directly.

What stays an independent check is every phase that does not copy, and
the card's counters. The per-phase comparison, against the VBL-sampled
phases of the same hardware capture (`docs/research/existing-port.md`
section 5):

| Phase | Hardware ms (v12, sampled) | f121 ms | f121 / hardware | fastpath ms |
| --- | ---: | ---: | ---: | ---: |
| walls | 78.6 | 78.9 | 1.00 | 61.8 |
| planes | 33.6 | 33.0 | 0.98 | 27.6 |
| game_tics | 32.5 | 31.3 | 0.96 | 7.3 |
| blit | 24.0 | 26.5 | 1.10 | 4.3 |
| render_copy | 22.3 | 27.3 | 1.22 | 22.1 |
| game_copy | 18.2 | 19.7 | 1.08 | 41.6 |
| masked | 16.3 | 16.6 | 1.02 | 12.7 |
| packet | 9.4 | 7.4 | 0.79 | 6.6 |
| things | 4.0 | 3.6 | 0.90 | 3.1 |
| debug | 1.5 | 1.5 | 0.97 | 0.2 |
| setup | 0.7 | 0.3 | 0.48 | 0.3 |
| idle | 0.0 | 0.0 | - | 0.0 |
| present_wait | 0.0 | 2.5 | - | 1.0 |
| **total** | **241.1** (248.0 by host time) | **248.6** | 1.00 | **188.6** |

Every phase the CPU runs comes within 11% of the hardware, except the two
short ones (packet, setup). Those phases do not depend on `axi_us`.
present_wait and idle cannot be seen by the hardware's sampling: they only
run between the VBL interrupt and line 0.

The event counts, against the card's own `vtw status` counters before and
after the same capture (in its profile JSON; per frame of 248 ms):

| Counter a frame | Hardware (`vtw status`) | f121 | f121 / hardware | fastpath |
| --- | ---: | ---: | ---: | ---: |
| steps (core cycles) | 6634040 | 6431431 | 0.97 | 6426674 |
| read_hits | 4690791 | 4531640 | 0.97 | 4538899 |
| misses | 1384441 | 1366474 | 0.99 | 1338967 |
| invalidations | 25680 | 25354 | 0.99 | 20003 |
| video_wait (clocks) | 4396035 | 4267487 | 0.97 | 133520 |
| bus_cycles | 5597 | 5630 | 1.01 | 324 |
| posted | 36970 | 36452 | 0.99 | 27701 |

That capture ran on F1.1.4 (its timing candidate), not F1.2.1; the
counters agreeing within 3% suggests the paths the model follows are the
same.

**The coalescer's page scan (modelled since 2026-09-30) leaves this
calibration where it was:** 248.6 ms f121 and 188.6 ms fastpath with the
scan and without it (`coalescer` 0), the fits at 0.133 and 0.137 us, and
every phase within 0.1 ms; the video waits grow by 3,433 clocks a frame
(0.08%), the sweep by at most 0.6 ms. The port writes its frame a
whole row at a time, so its pages are full when the scanner takes them;
the scan costs only scattered writes, such as the native replay's fuzz
columns (`src/native/README.md`). So `axi_us` was not fitted again. The
tables above are the run with the scan.

**Fastpath against the F1.2.1 profile: +31.8% frames a second**
(248.6 to 188.6 ms), a little above MILESTONES.md's estimate of +20% to
+30% from firmware alone. Where it comes from: the game tics (code and zero
page in RamWorks banks: 31.3 to 7.3 ms, from the 16-line cache and the
relaxed admission), the blit (26.5 to 4.3 ms: no drain), walls, planes and
masked (fewer and cheaper misses, no bank-switch bus cycles or
invalidations), and the copies (the memory API's hold no longer waits for
the drain). What it loses: **one lazy flush a frame, 27.3 ms**, in
game_copy. The port's memory API helper selects bank 122 with `$C073` (now
quiet) to reach its overlay page, and its next `bit $CFFF`, a real bus
cycle, makes the reconciler replay that bank, which must first flush the
whole pending SHR frame (rule O4). Without that flush, by restoring `$C073`
to 0 before the exchange in the port, or by exempting slot 7 from the
reconciler in the firmware, the frame would be about 161 ms (+54%; the
flush subtracted, not run).

The compatibility core with the model only observing (a2sim.py's timeline,
py65's accesses without dummy reads, idle skips not charged) gives 243.9 ms
a frame for the same frames.

### The slot-4 slowdown

Milestone S2 adds the firmware's slowdown of slot 4, **off unless a run
asks for it**: f121 and fastpath keep `slowdown_slot4 0`, the firmware's
default (the virtual Phasor is off by default, `config_menu.c:93`), so
every run and every check above is unchanged. The variants of
`costs/appletini.json` turn it on (`costs.py f121+phasor`, and
`+window32`, `+fws1`; `+ntsc` is an NTSC //e).

What the firmware does, from its source (appletini-one F1.2.1):

- With the virtual Phasor enabled, `config_menu_apply_vtw_slowdown` puts
  slot 4 into the slowdown mask "regardless of the per-slot config", with
  the window `vtw_slowdown_cycles`, 512 by default (`ps_sources/frontend/
  config_menu.c:4660-4692`, `:76`). A window of 0 then becomes 512
  (`:4681-4683`); the profile key `vtw.slowdown.cycles` sets 1-65,535
  (`:3550-3552`).
- A **hit** is any access to `$C400-$C4FF` (`sd_iosel`: `$Cn00-$CnFF` of
  slot n, whatever INTCXROM says) or `$C0C0-$C0CF` (`sd_slot_io`), read
  or write, that the core completes (`vtw_core_top.sv:1119-1144`). A hit
  loads `slow_cnt_q` with the window; every other completed CPU cycle
  takes one off (`:1884-1898`). While it is not zero the effective speed
  is 1 MHz (`:1153-1171`).
- At 1 MHz a cycle completes only after an Apple data strobe that came
  after the previous cycle ended (`pace_tick_pending_q`, `:1849-1856`;
  `pace_ok`, `:1159-1162`), so each cycle is one Apple cycle, 0.985 us on
  PAL. The core does not take its TURBO shortcuts: an instruction whose
  opcode fetch ran slow keeps all its dummy cycles to its end, even when
  the window closes inside it (`instruction_turbo_q`, `w65c02_core.sv:
  1250`, `:903-967`). The TURBO caches are still filled on the way
  (`turbo_map_fill`, `turbo_byte_fill`, `:1212-1215`).

The model: `slow_left` is `slow_cnt_q`. With the window open, every cycle
(dummy reads included) is charged its normal path, then paced to the
first data strobe after the previous cycle's end plus `slow_done` (1
clock); I/O keeps its bus-cycle timing, which already ends at a strobe.
A hit reloads the window after its own cycle. An idle skip (`--idle`)
uses the window up as the skipped cycles would have. **FW-S1**
(`slowdown_via_exempt`, a proposal, `docs/firmware/fws1-spec.md` as
`fws1-review.md` corrects it): writes to a VIA's ORB and ORA without
handshake (registers 0 and F) open no window; reads, writes to every other
register (the review found that exempt IFR, IER and ORA writes cause a
second interrupt in TURBO), writes with address bit 5 or 6 set (they also
reach the SSI-263, `mockingboard.sv:100-103`) and the mode switch still
do. `tests/test_sound_player65.py` checks the
window at its edges (exactly 512 or 32 slow cycles, then TURBO; a hit
inside the window reloads it), the regions, FW-S1's exemptions, and that
f121 and fastpath have no window.

Against `docs/research/native-sound.md` 2.3, the RTL agrees on the regions,
the window and its length in CPU cycles (each an Apple cycle at 1 MHz), and
on what FW-S1 would exempt. It adds what the design did not say: a hit's
own cycle runs at the speed it had, the reload does not count down in the
hit's cycle, a slow instruction keeps its dummy cycles, a window of 0
cannot be set while the Phasor is on, and some `$C4xx` addresses also
write the SSI-263.

### Checks

`tests/test_a2vm_cost.py`:

- the parameter file: every value has a source, every profile sets the
  same parameters, a2vm rejects a missing, unknown or malformed one;
- the TURBO path against the firmware's benchmark
  (`hdl/sim/tb_vtw_turbo.sv:717-747`, `README_TURBO.md:32-35`): the
  16-byte copy loop, 218 accesses a pass, takes **436 clocks a warm pass,
  as the RTL simulation measured**; its cold pass, 462 clocks, is
  explained miss by miss (the RTL's 474 also counts the core's reset);
- micro-cases through bus scripts: cache hits and misses and their
  invalidation; a `$C073` write at every phase, 122 to 253 clocks; a
  RamWorks miss, a sustained miss, a dirty victim, under both profiles;
  the mirror's barrier, coalescing, deferred bytes and exposure flushes;
  the coalescer's page scan (a 168-row column drains in 53,760-55,760
  clocks with its writes, as the RTL's 54,745; 168 contiguous bytes in
  168 Apple cycles; with `coalescer` 0 the column drains as 168
  contiguous bytes do);
  the quiet switches, the reconciler, the lazy class; the memory API's
  cost per chunk, and its hold flushing the mirror;
- with the existing port: a run with the model observing matches a run
  without it (state and all RAM), and under the pair profiles a run of
  the exact core matches the plain one but for the pair's state, all
  zero; timed runs are deterministic; the 20 frames meet MILESTONES.md
  3.1 item 4 and the counters stay within 10% of the card's.

### What the model does not do

- It assumes the renderer's capture stream always accepts a video write
  (the ARM consumer is not modelled; lazy-mirror-spec.md section 6).
- The coalescer's page scan is modelled for active bytes only
  (`coalescer` 1): deferred and lazy bytes keep the flush model, one byte
  an Apple cycle, without the scan (a flush drains whole screens, whose
  pages are full: assumed, not checked). The snapshot collision (a write
  to the byte being fetched is retried, `vtw_video_coalescer.sv:76-81`)
  and the bitmap clear after a reset (131,072 clocks) are not modelled.
  Until 2026-09-30 the model took the scan as free, one byte an Apple
  cycle ("at least 131 clocks a byte", read-bank-review.md 11), which
  made the native replay's frames with fuzz 11-40% faster than the card
  (demo-10: 34.3 ms against 48.1). With the scan, a Verilator run of the
  RTL (`vtw_core_top` in a copy of `tb_vtw_turbo`'s harness) and the
  model agree within 1% on micro-benchmarks and on the replay's draw
  phase on all 13 captured frames
  (`docs/results/fuzz-timing-2026-09-30.md`).
- The PS's latency to take a SmartPort request is 0 plus its AXI reads
  (bounded by the v12 batching result, well under 1 ms a request); AXI
  writes cost what reads do.
- Slow regions other than slot 4, the Disk II, the USB joystick: off, as
  in the measured setup (the port touches none of them in a frame). The
  slot-4 slowdown of the virtual Phasor is modelled (above) but off in
  f121, fastpath, f121zp and fastzp.
- The first access after a mapping change (`turbo_invalidate` still high
  at X_CAPTURE) is charged as a normal miss.
- Refresh, PHI0 stretching and the long Apple cycle are not modelled: an
  Apple cycle is 131.28 fabric clocks (PAL, 64 us a line of 65 cycles).
