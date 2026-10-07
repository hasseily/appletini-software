# a2vm: the model of the Appletini target

`a2vm` is a fast model of the port's target, an enhanced Apple //e with
an Appletini card, to run port code on the host. It has an exact
W65C02S core, the //e memory map with 128 RamWorks banks, the devices
DOOM uses (mouse card, Phasor, memory API, VidHD, a ProDOS block device),
a trap of the ProDOS MLI, and a cost model: the time a run takes on the card, access by
access, in TURBO mode. `tools/native/playdisk.py --run` plays `DOOM.hdv`
on it; `tools/native/lrun.py` runs the level load on it.

| File | What it is |
| --- | --- |
| `cpu65c02.h` | The W65C02S core's interface: registers, bus callbacks, cycle kinds |
| `cpu65c02_core.h` | The core itself, included once per bus |
| `cpu65c02.c` | The core connected through function pointers, and the parts without bus cycles |
| `py65core.h` | The compatibility core: py65's 65C02 (BSD licence, see the top-level README) |
| `a2vm.h`, `a2vm.c` | The machine: memory map, soft switches, keyboard, game port, mouse cards, Phasor, VidHD, memory API, the block device, timing, interrupt delivery and idle skipping |
| `prodos.h`, `prodos.c` | The MLI stand-in |
| `cost.h`, `cost.c` | The cost model: every bus access charged in fabric clocks of the Appletini, with its TURBO caches, RamWorks line cache, PSRAM admission, bus cycles, video mirror and memory API |
| `costs/appletini.json` | The cost parameters, each with its source in the firmware, and the profiles `f121`, `f122`, `fastpath`, `f121zp` and `fastzp` |
| `costs.py` | A profile as the "name value" lines `--cost` reads; `PROFILE+VARIANT` adds the variants |
| `main.c` | The command line: start-up, runs, input events, snapshots, screen dumps, logs, bus scripts |
| `Makefile` | `all` (the default) and `clean`; builds `build/a2vm/a2vm` |

Build:

    make -C tools/a2vm

(`build.sh` does it too.)

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
"data_ea" states (`w65c02_core.sv`), those at an instruction's
effective address: `CPU65C02_DATA_EA` for `ST_MEM_READ`, `ST_RMW_READ`,
`ST_MEM_WRITE` and `ST_RMW_WRITE`, `CPU65C02_DUMMY_EA` for `ST_RMW_MODIFY`
(the read-modify-write's second read) and `ST_DECIMAL_EXTRA` (the decimal
cycle of ADC and SBC, at `$007F` or `$0000` for their immediate forms).
Nothing else is EA: opcodes, operands, dummy reads of PC, the same-page
`STA a,X` false read of its target (`ST_INDEX_DUMMY`), zero-page
pointers, the zero-page reads of BBR and BBS, JMP `(a)` and `(a,X)`
pointers, the stack and the vectors. `CPU65C02_BASE_KIND(kind)` gives the
kind without the flag. The zero-page bank pair redirects only EA cycles.

The 65C02 makes no dummy writes. The cost model uses the kinds: the
Appletini's core, in TURBO mode, drops dummy reads outside
`$C000-$CFFF`, and a dummy read of a soft switch still switches it.

`cpu65c02_step` runs one instruction, an interrupt entry, or one cycle of
waiting or of being stopped. `cpu65c02_run(cpu, until)` steps until
`cycles` reaches `until`; a callback may lower `cpu->until` to end the run
after the current instruction. IRQ is a level with one bit per source
(`cpu65c02_set_irq`); NMI is an edge (`cpu65c02_nmi`).

`cpu65c02_core.h` holds the whole core and is included once per bus,
with four macros: `C02_PREFIX`, `C02_LINKAGE`, `C02_READ(cpu, address,
kind)` and `C02_WRITE(cpu, address, value, kind)`. `cpu65c02.c` includes
it with the function pointers of `cpu65c02.h`; a machine can include it
with its own inline bus, and the kind is then a constant the compiler
folds.

### What it follows

In order of authority:

1. **The Appletini's own core**, `hdl/apple/w65c02_core.sv` in
   [hasseily/appletini-one](https://github.com/hasseily/appletini-one).
   It is the chip this models.
2. **The WDC W65C02S datasheet**, tables 4-1, 5-2, 6-4 and 7-1.
3. **The [SingleStepTests 65x02](https://github.com/SingleStepTests/65x02)
   vectors**, directory `wdc65c02/v1`, at commit `2f6980a`, the revision
   the Appletini core was checked against.

Where they differ:

| Case | Datasheet | Vector set | Appletini core and this core |
| --- | --- | --- | --- |
| `$5C`, reserved NOP | 3 bytes, 8 cycles | 3 bytes, 4 cycles: two operand reads, then the last byte again | as the set |
| `STA a,X` and `STA a,Y`, index on the same page: the fourth cycle | not stated | reads the last instruction byte | reads the target address, the NMOS false read (`ST_INDEX_DUMMY`) |
| Decimal `ADC #` and `SBC #`: the extra cycle | not stated | reads `$007F` (ADC) or `$0000` (SBC) | as the set |
| Decimal ADC and SBC on memory: the extra cycle | not stated | reads the operand's address again | as the set |

Behaviour the vectors do not reach, taken from the Appletini core:

- **Interrupts** are sampled at each opcode fetch with the flags the
  previous instruction left: an IRQ pending across `CLI` is taken right
  after it. The entry takes 7 cycles: the discarded fetch, a read of PC,
  three pushes (P with B clear), the two vector bytes; I is set and D
  cleared. NMI wins over IRQ.
- **BRK** reads its signature byte, pushes PC + 2 and P with B set, and
  takes the IRQ vector; D is cleared.
- **WAI** is the opcode fetch and a read of the next byte, then one cycle
  a step reading PC while waiting. An active IRQ or an NMI ends the wait;
  with I set an IRQ resumes at the next instruction without being taken,
  otherwise the interrupt is entered in 6 more cycles.
- **STP** is the same two cycles, then one cycle a step until reset.
- **Reset** is 7 cycles: two reads at PC, three stack reads moving S down
  by 3, the vector at `$FFFC`. I is set, D cleared; A, X, Y and the other
  flags are kept. It leaves WAI and STP and forgets a pending NMI.
- **P** has bit 5 set and bit 4 clear in the register. PHP and BRK push
  bit 4 set, interrupts clear; PLP and RTI clear it.

Not modelled: the SO pin (not connected on the //e) and RDY. Bus stalls
and the TURBO shortcuts are the cost model's.

On an Apple M3 Pro the core runs about 185 million instructions a second
through function pointers, 217 million with an inlined bus.

## The machine

The machine's rules were first written to match `a2sim.py`, the Python
model of an earlier Doom port, so that the two could be compared cycle
for cycle. That model is no longer in this repository, but its rules
remain the defaults: `--core py65` and `--speed turbo` reproduce it, and
"Compatibility mode" below lists where it departs from the hardware. The
DOOM GS runs (`playdisk.py`) use the exact core and the cost model's
clock.

### Memory

| Area | Model |
| --- | --- |
| Main | 64 KB. `$0000-$01FF` from the selected aux bank with ALTZP; `$0200-$BFFF` reads from aux with RAMRD and writes to aux with RAMWRT, except that with 80STORE `$0400-$07FF` (and `$2000-$3FFF` with HIRES) follow PAGE2 |
| RamWorks | 128 banks of 64 KB (`--banks` 1-128), selected by writes to `$C071` or `$C073`: bank = (value & `$7F`) modulo the bank count. Bank 0 is the base aux memory |
| Language card | `$C080-$C08F`: bit 3 selects bank 1, `(low & 3) in (0, 3)` enables reads, write enable needs two reads of an odd address (a write resets the pre-write). With ALTZP off, main's card: 16 KB for `$C000-$FFFF` (bank 2 at `$D000`) plus 4 KB of bank 1. With ALTZP on, the selected aux bank's own `$C000-$FFFF`, bank 1 `$D000-$DFFF` at its physical `$C000-$CFFF` |
| ROM | 16 KB for `$C000-$FFFF` (`--rom`). `playdisk.py` gives an all-zero ROM |

Reads and writes go through page tables rebuilt whenever a switch that
moves memory changes; `$C000-$CFFF` and write-protected language-card
pages take a slow path. Video writes (to `$0400-$0BFF` and `$2000-$5FFF`
of main, and to `$0400-$0BFF` and `$2000-$9FFF` of aux bank 0) are
counted; SHR writes are the latter above `$2000`.

### Devices

| Address | Model |
| --- | --- |
| `$C000`, `$C010` | Keyboard: a queue of taps, each due at a cycle (`key`), and a held key (`hold`, `release`) whose "any key down" bit shows in `$C010` |
| `$C000-$C00F` writes | 80STORE, RAMRD, RAMWRT, INTCXROM, ALTZP, SLOTC3ROM, 80COL, ALTCHARSET |
| `$C013-$C01F` | The status of the switches in bit 7, the keyboard latch in bits 0-6 |
| `$C019` | 0 in vertical blanking, `$80` otherwise |
| `$C029` | NEWVIDEO, read and write |
| `$C030` | Speaker, counted |
| `$C050-$C057` | TEXT, MIXED, PAGE2, HIRES |
| `$C061-$C063` | Buttons: Open Apple, Solid Apple, button 2 |
| `$C064-$C067`, `$C070` | Paddles: 1,400 cycles of the 1 MHz bus clock from the trigger |
| `$C0A0-$C0AF`, `$C200-$C2FF` | The Appletini mouse card in slot 2 (`mouse_card.sv`): status, position, buttons, sequence, clamps, commands, mode, acknowledge, its slot ROM. A VBL interrupt (mode bit 3) is raised at the start of each vertical blanking and delivered while I is clear, until the program acknowledges it. `--no-mouse` leaves slot 2 empty; `--mouse-plain` gives it a ROM with the AppleMouse ID bytes and no registers |
| `$C200-$C2FF` with `--mouse-apple` or `--mouse-rom` | An AppleMouse II (below) |
| `$C0C0-$C0CF`, `$C400-$C4FF` | The Phasor in slot 4 (none with `--no-phasor`): mode switch, two 6522 VIAs (ports, directions, timer 1 as a free-running counter, or with `--via-timers` as the card's 6522 runs it), four AY chips' registers through the VIA port protocol in Mockingboard and native modes, the SSI-263's phoneme timer. No sound |
| `$C700-$C7FF`, `$CFF0-$CFF2`, `$CFFF` | With `--amem`, the memory API of appletini-one's `README_MEMORY_API.md`, version 1, behind its raw FIFO transport: the slot-7 ROM ID bytes, C8 selection and release, STATUS with the 32-byte capability block, CONTROL with COPY, FILL and PRIVATE, and every validation error (`$21`, `$60`-`$65`). All descriptors are checked before any is executed. `--amem-unsupported` and `--amem-unavailable` select the two failing firmware answers |
| `$Cn00-$CnFF` with `--vidhd SLOT` | A VidHD (below) |
| `$Cn00-$CnFF` with `--blockdev SLOT:FILE` | A ProDOS block device on an image file (below) |

### Time and interrupts

Without the cost model's clock (`--cost-timed`), a frame is 1,250,000
cycles with `--speed turbo` (the default) or 17,030 × N with `--speed N`.
Line 0 starts a frame; vertical blanking starts at line 192. With
`turbo` each access to `$C000-$CFFF` adds 73 cycles (`--io-cycles`
changes it). With `--cost-timed` the machine runs on the cost model's
clock instead: the PAL (or NTSC) frame, `$C019`, the VBL interrupt and
the idle skips follow it.

Each step delivers the VBL event when its cycle has come, then a pending
interrupt when I is clear, then the idle skip, then one instruction.
`--idle PC:KIND` declares an idle loop: when the CPU reaches PC and the
conditions hold, the clock moves to the next VBL (`vbl`) or the next
line 0 (`line0`) instead of the loop running, and the skipped cycles are
counted.

The conditions, each after a colon: `main` (ALTZP off), `invbl` (in
vertical blanking), `eq=A,B` (the 16-bit words at A and B equal; an
address is main memory, or the main language card's `$C000-$FFFE` written
`lc.ADDR`) and `byte=A,V` (the main byte at A holds V; at most four a
loop). A skip is exact only while the loop would spin until the next
interrupt: the conditions must say so. `playdisk.py` skips the kernel's
`dl_mwait` and the brain's `dl_bwait`, which spin while I_GetTime's low
word (`CLK_TICS`, in the main card) equals `DL_LASTM`; `dl_bwait` lives
in a paged slot, so it is skipped only while that slot's `SLOT_GRP` byte
names the brain's group:

    --idle BD0:vbl:main:eq=lc.E407,1F01
    --idle A66C:vbl:main:byte=19EE,1D:eq=lc.E407,1F01

(the addresses of one build; `playdisk.py` reads them from the link's
labels and symbols).

### The VIA timers

With `--via-timers` each of the Phasor's two VIAs has timer 1 as
appletini-one's `hdl/apple/via6522.v` runs it, stepped once an Apple bus
cycle:

- T1C-L and T1L-L write the low latch, T1L-H the high latch (and clear
  IFR bit 6), T1C-H the high latch, then loads the counter with the
  latch, clears IFR bit 6 and arms the one-shot.
- Loaded with N, the counter reads N, N-1 ... 0, $FFFF, then the latch L
  again: a time-out every L + 2 cycles. A read returns the counter before
  its step in that cycle.
- A time-out sets IFR bit 6 in free-run mode (ACR bit 6), and in one-shot
  mode the first one after the T1C-H write only. Reading T1C-L, writing
  T1C-H or T1L-H, or writing IFR with bit 6 set clears it; in Phasor
  native mode the T1C-L read also steps the counter once more.
- IFR reads bit 7 set when a flag is set whose IER bit is set; IER reads
  bit 7 set. The VIA's IRQ reaches the CPU like the mouse card's, and an
  idle skip ends at the next time-out when an IER bit 6 is set.
- Only timer 1 flags: timer 2, the shift register and CA1, CA2, CB1, CB2
  never set theirs; PB7 output is not modelled.

The state JSON then has `via_timers`: each VIA's latch, ACR, IFR, IER,
the one-shot's arming, and the counter's origin and next flag.

`--via-ora-nh` makes a write to a VIA's register 15 (ORA without
handshake) set ORA, as the card's 6522 does (the drivers send AY data
that way); without it the write is ignored. `--phasor-mb-only` locks the
Phasor to Mockingboard mode, as the card's `audio_control` bit 26 does.

### The AppleMouse II

`--mouse-apple` (needs `--core w65c02s`) puts in slot 2 an AppleMouse II
as a program sees it through its firmware, ROM 342-0270: the slot ROM
reads `BIT $FF58` at `$C200`, the ID bytes (`$C205` `$38`, `$C207` `$18`,
`$C20B` `$01`, `$C20C` `$20`, `$C2FB` `$D6`) and the entry table at
`$C212-$C219` with that ROM's offsets, an RTS at each entry. When the
core is about to run an entry (INTCXROM off), a2vm does the call at a
high level, through the CPU's bus and the firmware's screen holes (slot
n: X `$0478+n` and `$0578+n`, Y `$04F8+n` and `$05F8+n`, status
`$0778+n`, mode `$07F8+n`), then an RTS, C clear for success:

| Entry | What a2vm does |
| --- | --- |
| SETMOUSE | A < `$10`: the mode (bit 0 on, bit 3 the VBL interrupt), also into the mode hole; else C set |
| SERVEMOUSE | Zero page `$06` written `$60` and given back (the firmware's RTS there); the pending interrupt bits (VBL 3, button 2, move 1) into the status hole's bits 1-3; the interrupt released; C set when none was pending |
| READMOUSE | X, Y into their holes; the status hole: bit 7 button 0 down, bit 6 down at the last read, bit 5 moved since |
| POSMOUSE | X, Y from their holes, clamped |
| CLAMPMOUSE | A = 0 (X) or 1 (Y): the window from `$0478`/`$0578` (minimum) and `$04F8`/`$05F8` (maximum) |
| CLEARMOUSE, HOMEMOUSE, INITMOUSE | X, Y to 0 or the windows' minimum; INITMOUSE also the windows 0-1023 and the mode 0 |

The input events `mouse`, `mouse-to` and `buttons` move it, and a VBL
interrupt is raised at each vertical blanking while the mode's bit 3 is
on, until SERVEMOUSE releases it. The final state's `applemouse` gives
it with the count of calls to each entry. The firmware's own stack and
time are not modelled.

### The AppleMouse II's ROM

`--mouse-rom FILE` puts in slot 2 an AppleMouse II that runs Apple's own
firmware: FILE is the 2 KB ROM 342-0270-C, read from where it is (for
example GSSquared's `assets/roms/cards/applemouseiii/`); it is never
copied into this repository. The card follows GSSquared's
`applemouseiii` (`PIA6520.cpp`, `MouseController.cpp`):

- `$Cn00-$CnFF` shows the ROM's bank `(ORB & DDRB & $0E) >> 1`, from the
  next read after the PIA write that changes it;
- `$C0n0-$C0nF` is the 6520;
- the 6805 runs before and after each PIA read, after each PIA write and
  at each VBL, so it answers at once, with `MouseController.cpp`'s
  protocol and commands;
- at each vertical blanking, with the mode's bit 3 on, the VBL bit is
  set in its interrupt state; the slot's interrupt rises when a bit of
  VBL, button or movement appears in a state that had none, and falls at
  SERVEMOUSE and INITMOUSE.

The input events reach it as GSSquared's host mouse does. The firmware
needs the //e's ROM: INITMOUSE reads `$FBB3` and, when it is not `$06`,
takes the II+ path, which clears `$2000-$3FFF`. The final state's
`mouserom` gives its position, mode, interrupt state, bank, PIA
registers and counts. Both cores run it.

`--mouse-no-vbl` keeps a2vm's VBL from the controller, as GSSquared's
card behaves at 33.3 MHz (its event timer drops the VBL; `docs/PLAY.md`).

### The VidHD

`--vidhd SLOT` puts in a slot (1-7, not the Phasor's, the mouse's or the
memory API's) a VidHD as DOOM sees it on a //e with RamWorks: its slot
ROM reads `$24 $EA $4C` at `$Cn00-$Cn02` and 0 after (slot 3's only with
SLOTC3ROM on), and it keeps its own 32 KB copy of the SHR screen. Every
CPU write that reaches aux memory at `$2000-$9FFF`, whatever the RamWorks
bank (the card sees the bus, not `$C073`), goes into the copy when its
copy of the IIgs SHADOW register `$C035` (0 at power-on) lets it:
`$2000-$3FFF` when bit 3 is 0 or bits 1 and 4 are both 0, `$4000-$5FFF`
the same with bit 2, `$6000-$9FFF` when bit 3 is 0.

The final state's `vidhd` holds `c035_writes`, `shadow`, `fed` (writes
taken), `foreign` (taken from a bank other than 0: they corrupt the
picture) and `foreign_after` (those after the program's first `$C035`
write), `unshadowed` (aux 0's writes not taken: the picture goes stale),
`speaker`, `pairs`, `unpaired` and `pending` (accesses of `$C030-$C03F`,
paired when back to back); with `--vidhd-check PCS` (hex, commas, at
most 64), `checks` (each PC: its visits and those where the copy
differed from aux 0's `$2000-$9FFF`), `mismatches`, `between` and
`differ_now`. A final snapshot also writes the copy as `vidhd.shr`.

### The block device

`--blockdev SLOT:FILE[:ro]` (needs `--core w65c02s`) puts in a slot (1-7,
not the Phasor's, the mouse's or the VidHD's) a ProDOS block device with
one drive whose blocks are FILE's 512-byte blocks (a `.po` or `.hdv`
image). Its slot ROM has a ProDOS block device's ID bytes (`$Cn01` `$20`,
`$Cn03` `$00`, `$Cn05` `$03`, `$Cn07` `$01`: not a SmartPort) and its
driver's entry at `$Cn0A` (`$CnFF` `$0A`, an RTS there). In slot 7 with
`--amem` the memory API's ROM serves (`$C707` `$00`), as on the
Appletini, whose SmartPort firmware has the ProDOS entry `$C70A` beside
the API's FIFO. When the core is about to run the entry (INTCXROM off),
a2vm does the call with ProDOS's protocol, through the bus (so the //e's
switches apply to zero page and the buffer):

| Zero page | |
| --- | --- |
| `$42` | the command: 0 STATUS (X, Y the block count; `$2B` when write-protected), 1 READ, 2 WRITE, 3 FORMAT (nothing); else `$01` |
| `$43` | the unit, DSSS0000: another slot or drive 2 is `$28` (no device) |
| `$44-$45` | the 512-byte buffer |
| `$46-$47` | the block: past the image `$27` (I/O error) |

It writes MSLOT (`$07F8`) with `$Cn` as the Appletini's firmware does,
then returns as an RTS would: A the error, C set on one (`$2B` for a
WRITE with `:ro`). A WRITE goes to FILE at once (`fflush`), so the image
holds it when the run ends. In slot 7 with `--amem` the API's `$C800`
space stays selected after the call, as the firmware leaves it.

With `--prodos` it also writes ProDOS's global page as after a boot from
it, after the `--image` and `--load` options: `DEVNUM` (`$BF30`) its
slot's drive 1, its `DEVADR` entry (`$BF10` + 2n) `$Cn0A`. The MLI trap
still serves the `--prodos` files (not the image's): `playdisk.py --disk
IMAGE` gives it the image's own files (docs/PLAY.md, "The settings
file"). The final state then has `blockdev`: the slot, `read_only`, the
image's `blocks`, the `calls`, `statuses`, `reads`, `writes` and
`errors`, the `last` call (command, unit, block, error) and `written`
(the blocks written, the first 16). Without `--blockdev` nothing of this
exists and every run is as it was.

### Compatibility mode

`--core py65` (the default) is `py65core.h`: it does what py65 1.2.0's
`MPU65C02` does, access for access and cycle for cycle. `--core w65c02s`
is the exact core, one cycle a bus access, dummy reads included; the MLI
trap is then taken at the step boundary.

The compatibility core and the default timing keep these departures from
the hardware:

- **py65's cycle counts.** `DEC abs` takes 3 cycles, the read-modify-write
  `a,X` forms always 7, `BRA` 2 (3 across a page), `BIT a,X` no page
  penalty; decimal ADC and SBC take no extra cycle. `BBR`, `BBS`, `STP`
  and the reserved NOPs are two-byte NOPs of 0 cycles.
- **py65's accesses.** No dummy cycles at all (so `INC $C083` enables
  language-card writes on the chip but not here); JSR pushes before it
  reads its operand's high byte; `(zp)` at `$FF` reads its high byte from
  `$0100`.
- **py65's flags.** Decimal ADC and SBC set N, Z and V from the binary
  sum; P keeps bit 4.
- **The I/O surcharge.** 73 cycles an access to `$C000-$CFFF` in `turbo`.
- **Slot decoding.** `$C100-$CFFF` reads fall to the internal ROM unless
  a card answers; the Phasor answers at any address whose bits 8-10 are
  4, `$CC00-$CCFF` included.
- **The memory API** leaves the result fields of the capability block at
  zero, keeps the ready bit set after the first request, and ends the run
  ("halt", `amem-malformed: ...`) on a request the firmware's README
  leaves undefined or tolerates.
- **ProDOS.** The trap services `JSR $BF00` itself: the call's bytes and
  parameter block are read from main memory whatever the soft switches
  say, and files live in the volume directory only. Files a program
  writes stay in memory.

## Running it

    build/a2vm/a2vm --rom ROM [options]

The comment at the top of `main.c` lists every option. The main ones:

| Option | What it does |
| --- | --- |
| `--image FILE` | Memory records, `A2VMIMG1` then records of kind (1 byte: 0 main, 1 aux bank, 2 main LC with `$C000-$FFFF` addresses, 3 main LC bank 1 with `$D000-$DFFF` addresses), bank (1), address (2), length (4) and the bytes, all little endian |
| `--load ADDR:FILE`, `--load-aux BANK:ADDR:FILE` | A binary into main memory or an aux bank |
| `--reg pc=HEX` (and `a x y s p`), `--switch NAME=N` | Registers; switches, language-card state, `bank`, `newvideo` |
| `--prodos FILE` | The MLI trap, with the files of FILE, one a line: `NAME TYPE AUX PATH` (hex type and aux), in the order of the volume directory. `--volume NAME` and `--launched NAME` set the volume and the system file's name it reports |
| `--core py65\|w65c02s`, `--speed turbo\|N`, `--io-cycles N`, `--banks N` | The core and the timing (above) |
| `--idle SPEC` | An idle loop to skip (above) |
| `--boundary ADDR`, `--boundaries N` | A frame boundary (the CPU at ADDR after a step, ALTZP off), and how many to run |
| `--cycles N\|none`, `--stop-pc ADDR[:main]` | Other ends of the run. Without `--cycles` a run stops at 20,000,000,000 cycles with end `cycle-cap` and exit status 3; `none` runs with no limit. `--stop-pc` may be given more than once |
| `--stop-word ADDR:N` | Another end: the 32-bit little-endian main word at ADDR (hex), once it has been below N after a step, is at least N (end `stop-word`) |
| `--input FILE` | Input events, below |
| `--every-limit N` | At most N snapshots or shots of each `pc ADDR@*` event (default 100); the visit after them ends the run with exit status 2 |
| `--snapshot-dir DIR`, `--snapshot-boundaries`, `--final-snapshot` | Snapshots: `NAME.json` (the state) and `NAME.ram` (main 64 KB, main LC 16 KB, main LC bank 1 4 KB, then the 128 aux banks) |
| `--snapshot-ranges`, `--snapshot-stream`, `--snapshot-limit` | Snapshots of some ranges only, and a stream of them (below) |
| `--state FILE` | The final state, as JSON, with the reason the run ended and its host time (default: standard output) |
| `--bus-script FILE` | Run bus commands instead of the CPU (below) |
| `--amem`, `--amem-unsupported`, `--amem-unavailable` | The memory API in slot 7 |
| `--no-mouse`, `--mouse-plain`, `--mouse-apple`, `--mouse-rom FILE`, `--mouse-no-vbl` | Slot 2 (above) |
| `--no-phasor`, `--via-timers`, `--via-ora-nh`, `--phasor-mb-only` | Slot 4 (above) |
| `--vidhd SLOT`, `--vidhd-check PCS` | A VidHD (above) |
| `--blockdev SLOT:FILE[:ro]` | A ProDOS block device on FILE (above) |
| `--zpbank` | Arm the zero-page bank pair (below) |
| `--cost FILE`, `--cost-timed`, `--cost-phase ADDR`, `--cost-report FILE`, `--cost-pcmap FILE`, `--cost-pcmap-when N` | The cost model (below) |
| `--ay-log FILE`, `--pclog FILE`, `--write-log RANGES`, `--lowest-s` | Logs (below) |
| `--irq-bounds LO-HI[,LO-HI...]` | Interrupt bounds (below) |

Exit status: 0 for a run that ended normally, 1 for a halt, 2 for an
error (a bad option or file, a limit on snapshots), 3 for the cycle cap.

### Input events

`--input FILE` gives events, one a line, `WHEN ACTION`. `WHEN` is
`start`, `boundary N` (after the Nth boundary's snapshot), `cycle N`
(after the first step that reaches cycle N) or `pc ADDR[:main][@N|@*]`
(the CPU is at ADDR after a step, with ALTZP off for `:main`: the first
such visit, the Nth with `@N`, every one with `@*`). Each event fires
once (an `@*` event at every visit), in the file's order among those
due; several events at one PC all fire at their visits, so a routine
called K times needs one call site (`pc CALL@1 snapshot before1`,
`pc CALL@2 snapshot before2`, or `pc CALL@* snapshot before`). An `@*`
event's snapshots and shots are named `NAME-0001`, `NAME-0002`, by
visit.

Actions: `key K` (a tap, due now), `hold K`, `release`, `mouse DX DY` (a
move by a delta), `mouse-to X Y`, `buttons L R`, `oa 0|1`, `ca 0|1`
(Open and Solid Apple), `snapshot NAME`, `shot NAME` (a screen dump:
`A2VMSHR1`, NEWVIDEO, aux bank 0 then main `$2000-$9FFF`), `stop`. K is
a character or a number (one character is that character: `key 0x08` is
the left arrow, `key 8` the digit; a number is C's `strtoull` base 0).

`playdisk.py --run SCRIPT` takes a file of these events and lets a pc
event name a label of the play link: `pc @dl_halt ...`.

### Bus scripts

`--bus-script FILE` runs commands instead of the CPU and prints their
results: `read ADDR`, `write ADDR VALUE` (the CPU bus, with every side
effect), `peek KIND BANK ADDR`, `poke KIND BANK ADDR VALUE` (storage
without side effects; kinds `main`, `aux`, `lc`, `lc1`), `map` (what
reads and writes of each page reach), `lc`, `counts`, `clock N`,
`run STEPS`, `reg NAME=HEX`, `press KEY CYCLE`, `hold KEY`, `release`,
`mouse DX DY`, `mouse-to X Y`, `buttons L R`, `button N VALUE`,
`dump FILE` (the RAM, as a snapshot's), `state`, `cost` (the model's
clock and counters); and for the zero-page pair `read-ea ADDR` and
`write-ea ADDR VALUE` (a data access at an effective address, which the
pair redirects), `zpbank`, `zpbank-arm 0|1` and `reset` (the CPU's RESET
sequence, which turns the pair off; the //e's switches are not reset).

### Ranges

`--write-log` and `--snapshot-ranges` take RANGES: items separated by
commas, each `WHERE[:LO[-HI]]` with hex addresses (the whole of WHERE
without them), at most 256.

| WHERE | Storage | Addresses |
| --- | --- | --- |
| `main` | Main memory | `0000-FFFF` (`C000-FFFF` is never written) |
| `auxN`, `auxN-M` | RamWorks banks N to M (0-127; 0 is the base aux memory) | `0000-FFFF`; an aux bank's language card is its `C000-FFFF` (bank 2 at `D000`, bank 1 at `C000-CFFF`) |
| `lc` | Main language card, bank 2 at `$D000` | `C000-FFFF` |
| `lc1` | Main language card bank 1 | `D000-DFFF` |
| `cpu` | The CPU's address, whatever it reaches: write log only | `0000-FFFF` |

A storage range holds a write by the byte it reaches (so a write the
zero-page pair redirects is in `aux5`, not `main`); a `cpu` range by its
address.

### Range snapshots and the snapshot stream

`--snapshot-ranges RANGES` makes every snapshot `NAME.json` and
`NAME.img` in place of `NAME.ram`: `NAME.img` is an `A2VMIMG1` image (the
format of `--image`) with one record for each range and bank, so
`--image` loads it back. A full snapshot is 8.4 MB.

`--snapshot-stream FILE` (it needs `--snapshot-ranges`) writes every
snapshot into one stream instead of files, so a reader can digest each
as it comes; `-` is the standard output (with `--state FILE`). The
stream is a JSON line `{"format": "a2vm-snapshot-stream 1", "ranges":
"..."}`; for each snapshot a JSON line `{"snapshot": N, "name", "cycles",
"pc", "bytes": L}` followed by its L bytes, the `A2VMIMG1` image; and a
last line `{"end": REASON, "snapshots": N}`. `--snapshot-limit BYTES`
(default 1 GiB) bounds it: a snapshot that would pass the limit is not
written, the stream ends with `{"end": "snapshot-limit", ...}` and the
run with exit status 2.

### The AY log

`--ay-log FILE` writes one line for each event below, in the order the
machine makes them. It only observes.

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
| `w` | An AY register write reaches a chip: a VIA's ORB write with function 6 (write) on a selected chip. `CHIP` is 0-3 (0 and 1 behind VIA-A, 2 and 3 behind VIA-B), `REG` the chip's latched register (0-15), `VALUE` the byte (decimal) |
| `reset` | A VIA's ORB goes to reset (bit 2 low): both chips behind it are cleared; one line a chip |
| `irq` | The machine delivers an interrupt; `N` counts them from 1 |
| `rti` | An RTI instruction ran (logged after it) |

`CPU_CYCLES` is the core's cycle count; `APPLE_CYCLE` the machine's
1 MHz bus clock; `CLOCK` the cost model's clock in fabric clocks
(133.333 MHz) when `--cost` is on, else `-`. With `--cost-timed` it is
the time on the card. The writes of an interrupt are the `w` lines
between its `irq` and the next `rti`.

### The PC log

`--pclog FILE` writes a line before each instruction run at one of the
PCs of `--pclog-pcs LIST` (hex, commas, at most 64), after the idle
skip; not for an interrupt's entry, nor while the CPU waits or is
stopped. It only observes.

    # a2vm pclog 1 (tools/a2vm/README.md, "The PC log")
    # pcs FF52,FF7F,823A
    # bytes lc.FF9B,1DC0
    # clock fabric clocks (--cost-timed)
    # CLOCK PC A X Y S ALTZP BYTE...
    2004417163 FF52 00 01 05 FB 0 93 BC

`CLOCK` is the machine's clock in decimal (fabric clocks with
`--cost-timed`, else the core's cycles); `PC` to `S` are hex, the
registers before the instruction; `ALTZP` 0 or 1; then one hex byte for
each address of `--pclog-bytes LIST` (at most 16), read without side
effects from main memory, or from the main language card for `lc.ADDR`.
`--pclog-from N` starts the log at clock N. `--pclog-limit N` (default
1,000,000 lines) bounds it: the visit that would be line N + 1 halts the
run (exit status 1), so a log is complete or the run fails.

### The write log

`--write-log RANGES` writes a line for every CPU write that reaches the
ranges, to `--write-log-file FILE` (default `writes.log` in the
`--snapshot-dir`). It only observes; the state gets `write_logged`, the
number of lines. `--write-log-limit N` (default 10,000,000) bounds it:
the write that would be line N + 1 halts the run.

    # a2vm write-log 1 (tools/a2vm/README.md, "The write log")
    # ranges main:4000-40FF,aux0:4000,cpu:C004-C005
    # w CLOCK CPU_CYCLES PC ADDRESS STORAGE BANK OFFSET OLD NEW
    w 12 12 0805 4000 main 0 4000 11 11
    w 16 16 0808 C005 io - - - 11
    w 20 20 080B 4000 aux 0 4000 00 11

`CLOCK` is the machine's clock before the write, `CPU_CYCLES` the core's
cycle count, `PC` the instruction's (an interrupt entry's pushes carry
the interrupted PC), `ADDRESS` the CPU's; then the storage the byte is
in (`main`, `aux`, `lc`, `lc1`, or `io` for a write that reaches none),
its bank (decimal) and offset (hex), the value it held and the value
written. Stores of the value already there are logged too. Bus-script
`write` and `write-ea` are CPU writes; `poke` and the memory API are
not.

### The lowest S

`--lowest-s` adds to the final state the lowest S the run reached, the
PC of the step that reached it, its clock and the number of steps.
`--lowest-s-in LO-HI[,LO-HI...]` (hex, at most 16) also gives, for each
PC range, the lowest S seen before or after a step that started inside
it: a routine's stack depth, with the entry of an interrupt that lands
inside it but not the handler's own instructions.

    "lowest_s": {"s": 248, "pc": 2081, "cycles": 45, "steps": 10,
                 "ranges": [{"low": 2064, "high": 2069, "s": 250, "pc": 2065,
                             "cycles": 20, "steps": 4}]},

`s` is `null` for a range never entered.

### Interrupt bounds

`--irq-bounds RANGES` (hex `LO-HI`, commas, at most 24) checks an
interrupt contract: from the first instruction of a handler to the end
of its RTI, every bus access of the CPU (opcode, operand, data, stack,
dummy) must fall in one of the ranges; the first that does not halts the
run with `irq-bounds: read $0843 in an interrupt, pc $E123` (exit status
1). The interrupt entry's own cycles are not checked, nor is anything
outside handlers. `playdisk.py` passes the bounds of `docs/SCREENS.md`
2.3 (with an AppleMouse II, also its firmware's ranges and screen
holes).

### The zero-page bank pair

The pair is a proposed firmware feature, not in F1.2.1 or F1.2.2:
`$C069` makes a pair of zero-page bytes name the RamWorks banks that
data reads and writes at `$0200-$BFFF` go to. `--zpbank` arms it; so do
the cost profiles `f121zp` and `fastzp`. It needs `--core w65c02s` and
128 RamWorks banks. Armed, nothing changes until a program writes
`$C069`:

| Rule | Model |
| --- | --- |
| Enable | A CPU write of V to `$C069`: `$00` or `$FF` turn the pair off, `$01-$FE` make V the pair's first byte (`zp_rd`) and V+1 its second (`zp_wr`); every such write clears both registers. The write stays an ordinary I/O write; reads of `$C069` are unchanged |
| Watch | While the pair is on, a CPU write to main zero page (ALTZP off) at `zp_rd` or `zp_wr` loads that register; a write to aux zero page does not; pokes and the memory API never do. The value applies at once |
| Values | 1-126: the `$C073` bank of that number; 0 and 127-255 follow the switches |
| Redirect | A data_ea cycle (`CPU65C02_EA` above) to `$0200-$BFFF` goes to the bank of `zp_rd` (reads) or `zp_wr` (writes) when that register is not 0, whatever RAMRD, RAMWRT, 80STORE and PAGE2 say. Never opcodes, operands, dummy PC reads, the same-page `STA a,X` false read, JMP pointers, vectors, the stack, zero page, `$C000-$FFFF`. A redirected write is never a video write |
| `$C071`, `$C073` | Leave the pair alone; a zero register follows them |
| Reset | Off at power-on, at the CPU's RESET (`reset` bus verb) and when disarmed |

Counters in the state (`"zpbank"`, only with the pair armed) and in the
cost report (`zpb_*`): `$C069` writes, register loads, redirected reads
and writes, redirected accesses made with the PC in `$C100-$CFFF` or in
the ROM (firmware running with the pair set), and memory API requests
made with a register nonzero. A redirected access is charged as a
RamWorks access of its bank, never a TURBO cache hit or fill.

## The cost model

`cost.h` and `cost.c` charge every bus access of a run with what it costs
on the Appletini in TURBO mode, in fabric clocks (133.333 MHz), as the
vTW core routes it (`hdl/apple/vtw_core_top.sv` of appletini-one). TURBO
batches video writes through the mirror and its coalescer; the model
follows that batching, not a synchronous 1 MHz bus write for each byte.
The parameters come from `costs/appletini.json`; each cites the RTL line
it comes from.

| Access | What the model does | Clocks (F1.2.1) |
| --- | --- | --- |
| Fast memory (main, base aux, ROM) | The TURBO caches of `vtw_turbo_cache.sv`: a 32-word read cache indexed as the RTL folds the address, a 32-entry write page table; a video write never takes a fast entry | read hit 2, read miss 4, write hit 2, write miss 5, video write 6 |
| A dummy read | Omitted outside `$C000-$CFFF` (the TURBO core's shortcuts): no access; kept, as a real access, in I/O. With the virtual Disk II active (`d2_replay`), the step that stands for it waits while `disk2_card.sv` replays its cycles | 2, 1 for the second of a pair; 0 with the variant `nod2` |
| Extended memory (RamWorks banks 1-127) | The 8-byte write-allocate line (or 16 lines, fastpath), write-back; a miss is a PSRAM operation admitted once an Apple cycle inside a 37-clock window from tap 30 (`psram_simple.sv`), a dirty victim two | hit 5, clean miss 35 with the window open, about 131 sustained, dirty about 260 |
| `$Cxxx` | A real bus cycle launched at the next `drive_en` (tap 9), answered 4 clocks after the data snap; or a private shortcut: `$C011-$C01F` reads, the slot-7 SmartPort window, internal ROM | 123-254; private 3 to 6 |
| The video mirror | Each video write leaves a byte for the motherboard, "active" or deferred as `vtw_video_policy.sv` decides, coalesced while it waits. Active bytes go through the coalescer (`vtw_video_coalescer.sv`; `coalescer` 1): its scanner selects the dirty pages in address order, one page a clock, takes every byte of a selected page in two clocks, and queues the dirty ones for the bus (508 entries before it reports full), which takes one an Apple cycle; the next `$Cxxx` access waits until the scan is done and the queue empty. An exposure access flushes every pending byte | 131.3 a byte when a page has 4 or more dirty bytes; at least 513 a page scanned below that, so a column of the 3D view (one byte a 160-byte row) drains at about 4 Apple cycles a byte |
| A mapping change | Clears both TURBO caches | the misses that follow |
| A memory API request | The hold (the mirror and the line flushed first), then the ARM's work as `memory_api_hw.c` does it: AXI register accesses per 4 bytes of fast memory, one PSRAM line an Apple cycle by DMA, in 504-byte chunks; with `amem_engine` (f122) the FPGA copy engine | 0.135 us an AXI access |

The model **only observes**: it never changes what the machine does
(except `zp_pair` of the pair profiles, which arms the zero-page pair).
With `--cost-timed` its clock becomes the machine's. `--cost-report FILE`
writes a JSON line at every frame boundary: the model's clocks, by
phase, and its counters.

**Phases.** `--cost-phase ADDR` names a main-memory byte whose writes
(ALTZP off) mark phases: the phase is the value written / 2. There are
32 phases (0-31; a larger value counts in 31); the report's `phases`
lists have 32 entries, and with `--cost-phase` it also gives, by phase,
the core's cycles (`phase_cycles`) and the soft-switch accesses
(`phase_io`). The port's phase byte is `$0300` (`tools/native/layout.py`
`PHASE`); its numbering is in `docs/RENDER-MASKED.md` and
`tools/native/s2layout.py`.

**The PC map of phases.** `--cost-pcmap FILE` with `--cost-pcmap-when N`
(default 18): while the phase last written is N, each instruction's
phase is its PC's in the map, so a run is cut by the code that runs with
no marks in it. The file's lines are `LO HI PHASE` (hex addresses, a
decimal phase: code at a fixed place) or `LO HI PHASE SLOT GROUP` (code
paged into a window: it holds while main `SLOT` holds `GROUP`); a PC the
map lacks keeps the written phase; a write of any other phase turns the
map off until N is written again.

### The profiles

`costs.py` turns a profile into the lines `--cost` reads:

    python3 -c 'import sys; sys.path.insert(0, "tools"); from a2vm import costs; print(costs.text("f122+nod2"))'

| Profile | What it is |
| --- | --- |
| `f121` | Firmware F1.2.1 as it is |
| `f122` | F1.2.2 (below) |
| `fastpath` | F1.2.1 with the seven changes of the vTW fast-path firmware design (below) |
| `f121zp` | F1.2.1 with the zero-page pair: every parameter f121's, plus `zp_pair` 1 |
| `fastzp` | fastpath with the pair in place of the read bank: `read_bank` 0 and `zp_pair` 1 |

| Variant | What it sets |
| --- | --- |
| `phasor` | The virtual Phasor on: the slot-4 slowdown (below), window 512 |
| `window32` | The slowdown's window 32 cycles (`vtw.slowdown.cycles`) |
| `fws1` | FW-S1, a proposal: VIA ORB and ORA-without-handshake writes open no window |
| `nod2` | The card with its virtual Disk II inactive (no `d2_replay`) |
| `ntsc` | An NTSC //e: the frame of 262 lines |
| `precal` | The model before the card's calibration, for comparison |

`playdisk.py --profile` names the combinations it runs: `f121`
(`f121+phasor+window32`, the default), `fastpath`, `f121-precal`,
`f121-nod2`, `f122`, `f122-nod2` and `f122-nod2-ntsc`.

`zp_pair` is the one parameter that describes the machine as well as its
costs: a profile with it arms the pair, and `--zpbank` with a profile
without it is refused.

The fast-path design's seven changes, as `fastpath` models them:

1. relaxed PSRAM admission while the vTW owns the bus (a miss 35 clocks);
2. a 16-line fully associative RamWorks line cache;
3. TURBO caches that survive mapping changes (checked against the
   physical page);
4. quiet RAMRD, ALTZP, `$C08x` and `$C071/$C073` (3 clocks), with a
   reconciler that replays them before any other bus access and flushes
   the aux mirror bytes before a bank replay;
5. a lazy mirror class for SHR writes, flushed only by leaving SHR, a
   physical bank write or a hold whose destination is in the SHR range;
6. the private read bank `$C069`;
7. `$C071/$C073` in `vtw_is_bank_steer` (no cost in TURBO).

### Calibration on the card

The parameters are derived from the RTL. On 2026-10-03 a calibration
disk timed 44 operations on the owner's card (PAL //e): the CPU in fast
memory and in RamWorks banks, line misses, the switches, far windows and
copies, the SHR drain. Six parameters changed; every operation is now
within 0.6% of the card, and the menu's BENCHMARK within 0.4% of the
card's FPS (`docs/SPEED.md`):

| Parameter | Before | Now | What it is |
| --- | --: | --: | --- |
| `d2_replay` | (new) 0 | 1 | The virtual Disk II in slot 6 is active on the owner's card and replays, one a clock, the 65C02 cycles each TURBO step stands for, holding the next step until it has. A step that omitted k dummy reads delays the next one k + 1 clocks |
| `bus_drive_tap` | 8 | 9 | drive_en is registered (`apple_bus_wrapper.sv`) |
| `bus_done` | 2 | 4 | data_en and resp_valid_q are registered: two switch writes in a row take one Apple cycle more, as on the card |
| `admit_offset` | 6 | 30 | addr_en is tap 25, not tap 3 |
| `admit_window` | 40 | 37 | the window's 40 count from addr_en, not from the arming (`psram_simple.sv`) |
| `slow_done` | 1 | 3 | a cycle paced at 1 MHz ends on the third clock after the data snap |

The variant `precal` restores the values before; `nod2` is the card with
its virtual Disk II inactive (`disk2.slot6.enabled=off` or
`vtw.disk2.acceleration.disabled=on`).

One value is fitted, not derived: `axi_us`, the latency of the ARM's
AXI register accesses (0.135 us), set against a frame of an earlier port
timed on the card.

### F1.2.2: the profile `f122`

Firmware F1.2.2 (appletini-one `3101934`) changes two things on the
TURBO path:

1. `psram_simple.sv`: while the vTW owns the bus, every background op is
   admitted as soon as the driver is free, not once an Apple cycle in the
   window. A RamWorks line miss is then 35 clocks, back-to-back reads 32
   apart; a dirty victim's write 24 more (`relaxed_admission` 1). A
   captured aux write's RMW is admitted on the clock after its byte lands
   (`rmw_queue` 1);
2. the memory API's descriptors run on `vtw_copy_engine.sv`, one command
   each (`amem_engine` 1). The model runs the engine state by state
   (`copy_engine` in `cost.c`): an aligned copy from a RamWorks bank to
   main takes 41 clocks a line, 0.0384 us a byte, plus the ARM's register
   accesses before START and its polls (`amem_copy_*`).

One value is fitted: `ps_dispatch_us`, the ARM's own time a request
beyond the AXI accesses the model counts, 25.9 us. Checked on the card
on F1.2.2 with the virtual Disk II's acceleration off (`f122+nod2`):
the calibration disk's operations within 0.6% but two whole-Apple-cycle
phase cases (+1.5% and +1.2%), and the BENCHMARK's FPS and rows within
0.1 ms.

### The slot-4 slowdown

The firmware's slowdown of slot 4 is **off unless a profile asks for
it**: f121, f122 and fastpath keep `slowdown_slot4 0`, the firmware's
default (the virtual Phasor is off by default). The variant `phasor`
turns it on; DOOM's profiles all use `phasor+window32`.

What the firmware does (appletini-one, `config_menu.c` and
`vtw_core_top.sv`):

- With the virtual Phasor enabled, slot 4 is in the slowdown mask with
  the window `vtw_slowdown_cycles`, 512 by default; the profile key
  `vtw.slowdown.cycles` sets 1-65,535.
- A **hit** is any access to `$C400-$C4FF` or `$C0C0-$C0CF`, read or
  write, that the core completes. A hit loads the counter with the
  window; every other completed CPU cycle takes one off. While it is not
  zero the effective speed is 1 MHz.
- At 1 MHz each cycle is one Apple cycle, 0.985 us on PAL. The core does
  not take its TURBO shortcuts: an instruction whose opcode fetch ran
  slow keeps all its dummy cycles, even when the window closes inside
  it. The TURBO caches are still filled on the way.

The model: `slow_left` is the counter. With the window open, every cycle
(dummy reads included) is charged its normal path, then paced to the
first data strobe after the previous cycle's end plus `slow_done`; I/O
keeps its bus-cycle timing. A hit reloads the window after its own
cycle. An idle skip uses the window up as the skipped cycles would have.
**FW-S1** (`fws1`, a proposal): writes to a VIA's ORB and ORA without
handshake (registers 0 and F) open no window; reads, writes to every
other register, writes with address bit 5 or 6 set (they also reach the
SSI-263) and the mode switch still do. The bus script's `cost` gives
`slow_hits`, `slow_cycles`, `slow_clocks` and `slow_left`.

### What the model does not do

- It assumes the renderer's capture stream always accepts a video write
  (the ARM consumer is not modelled).
- The coalescer's page scan is modelled for active bytes only: deferred
  and lazy bytes keep the flush model, one byte an Apple cycle. The
  snapshot collision (a write to the byte being fetched is retried) and
  the bitmap clear after a reset are not modelled.
- The PS's latency to take a SmartPort request is 0 plus its AXI reads;
  AXI writes cost what reads do.
- Slow regions other than slot 4, and the USB joystick, are off.
- The first access after a mapping change is charged as a normal miss.
- The Disk II's replay assumes the drive stopped. The decimal cycle of
  ADC and SBC (a real step on the card) is taken as an omitted dummy
  read.
- Refresh, PHI0 stretching and the long Apple cycle are not modelled: an
  Apple cycle is 131.28 fabric clocks (PAL, 64 us a line of 65 cycles).
