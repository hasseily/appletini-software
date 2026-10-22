# Optional private memory acceleration

The normal build contains the standard CPU implementation and does not link
the private FIFO transport. `python tools/build.py --cc65-home D:/Repos/cc65
--private --build-dir build/private` creates the explicit optional build.
Private and CPU builds use the same public resource API and retain the CPU
reference implementation. Video publication always uses ordinary CPU writes;
AMEM is never a framebuffer blitter.

Include `libtini/amem.h`. Call `ti_amem_enable` explicitly after `ti_init`.
It takes temporary slot-7 C8 ownership with IRQs masked, saves/restores
INTCXROM and checks the controller ROM signature, shared by F1.3.1 and F1.3.2, and
CRC-16/CCITT-FALSE `$95D9` over C700's 256 bytes. An unidentified controller
receives no private FIFO command. This is an interface compatibility check,
not a generic SmartPort-driver discovery mechanism.

For a matching controller, STATUS selector `$80` must report the `AMEM`
signature, supported major version, descriptor size, required copy/fill
capabilities, the expected `$0200-$BFFF` windows and PRIVATE support. Each
operation probes availability/capabilities again before submission and checks
the reported maximum bank selector. The raw FIFO is `$CFF0/$CFF1/$CFF2`; the
driver sends the existing STATUS/CONTROL packets and does not install new
firmware services or change slot assignments.

## Selection and failure rules

Eligible resource reads/writes/fills of at least 256 bytes can accelerate.
Distinct-handle resource copies can accelerate; same-handle copies, including
overlapping moves, use the CPU path. Small operations use the CPU path. Large
operations split at each logical bank boundary, with the same checked ranges
and buffer lifetime as the CPU reference. No banked pointer escapes. Resource
bank zero is reserved and cannot become a private working destination.

Unsupported or unavailable service **before a transfer's first CONTROL**
selects the CPU implementation. Once a piece has succeeded, a later bank's
unavailability returns `TI_E_IO`, because earlier pieces already changed data.
A CONTROL error or response timeout also returns `TI_E_IO` immediately.
Neither situation silently repeats a partially executed operation through CPU
copies. Callers must treat the destination as potentially partial and abort
or recover at their own transaction boundary.

A response wait ends after 240 changes of the //e vertical-blank flag at
$C019, 2 s at 60 Hz and 2.4 s at 50 Hz, whatever the CPU speed. The slot-7
ROM itself waits without a limit. Time while the controller holds the CPU
does not count. A 65536-poll bound used before could expire after tens of
milliseconds at 33 MHz. Malformed responses and uncertain
CONTROL execution poison the private driver for the rest of the program.
Further enables/transfers report I/O failure without submitting another
CONTROL. `ti_amem_disable` removes acceleration hooks; it does not clear that
poison or restore partially changed data. Do not use disable-and-retry as an
automatic recovery policy after uncertain execution.

`ti_amem_available` reports the enabled, unpoisoned hook state. Disable and
runtime shutdown make it false; a later initialization requires an explicit
enable. `ti_amem_last_error` retains the controller/error byte. In a CPU-only
build, enable returns `TI_E_UNAVAILABLE`, available is false, and the private
transport is absent.

The shared driver's pause/resume hooks surround private transactions. No
other foreground component or NMI handler may claim C8 or the FIFO while the
driver owns it. The transport restores the caller's IRQ policy and INTCXROM,
then deselects C8; a previously selected expansion ROM is not preserved.
Long operations mark a timing gap. Only board measurements establish the
latency and interrupt/audio impact at 33 MHz or TURBO.

## Reproduce focused checks

```powershell
python tests/amem_validate.py --cc65-home D:/Repos/cc65
```

The script builds the actual optional C code, memory API and ca65 transport
independently under `build/amem/`, with `TI_PRIVATE_TRANSPORT=1`. It does not
overwrite the CPU-only archive. The focused 65C02/controller model passes
7282 checks across eleven runs:

- CPU/private equality for cross-bank reads, writes, fills and distinct-handle
  copies; twelve successful CONTROL requests in the normal scenario.
- Small and same-handle overlapping operations stay on the CPU path.
- Wrong signatures and a valid signature with the wrong ROM CRC cause zero
  raw FIFO writes and zero STATUS/CONTROL submissions.
- Unsupported status and unavailable service select CPU before submission.
- A partly applied CONTROL failure and a response timeout produce one
  CONTROL, no CPU replay, and a poisoned driver.
- Availability lost after the first bank, or a second bank beyond the
  reported maximum, returns an error without replaying the completed part.
- Malformed response length, shutdown availability, C8/INTCXROM restoration,
  IRQ masking and AUX0 preservation are checked.

`build/amem/validation.json` records requests and results. The fixture uses an
original synthetic 256-byte ROM constructed to satisfy the documented CRC
check, plus an independent raw FIFO/memory service. No controller ROM is
redistributed or executed by that fixture. This establishes compiled transport
and fallback behavior against the modeled protocol, not execution on the
selected firmware. Real-board comparisons with private services enabled,
unavailable and disabled remain required, along with speed-mode measurements.
