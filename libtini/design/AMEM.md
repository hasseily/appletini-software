# Optional private memory acceleration

The normal build contains the standard CPU implementation and does not link
the private FIFO transport. This command makes the optional build:

```powershell
python tools/build.py --cc65-home D:/Repos/cc65 --private --build-dir build/private
```

The private and CPU builds use the same public resource API, and the two keep
the CPU reference implementation. Video publication always uses ordinary CPU
writes. AMEM is never a framebuffer blitter.

Include `libtini/amem.h`. Call `ti_amem_enable` explicitly after `ti_init`.
The call takes temporary slot-7 C8 ownership with IRQs masked, and it saves
and restores INTCXROM. It checks the controller ROM signature of F1.3.2 and a
CRC-16/CCITT-FALSE of `$95D9` over the 256 bytes of C700.

An unidentified controller receives no private FIFO command. This is an
interface compatibility check. It is not a general SmartPort-driver discovery
mechanism.

For a matching controller, STATUS selector `$80` must report the `AMEM`
signature, a supported major version, the descriptor size, the copy and fill
capabilities, the `$0200-$BFFF` windows and PRIVATE support.

Each operation probes the availability and capabilities again before
submission, and checks the reported maximum bank selector. The raw FIFO is
`$CFF0/$CFF1/$CFF2`. The driver sends the existing STATUS and CONTROL packets.
It installs no new firmware services and changes no slot assignments.

## Selection and failure rules

Eligible resource reads, writes and fills of at least 256 bytes use AMEM.
Resource copies between different handles use AMEM. Same-handle copies,
overlapping moves included, use the CPU path. Small operations use the CPU
path.

Large operations split at each logical bank boundary, with the same checked
ranges and buffer lifetime as the CPU reference. No banked pointer leaves the
library. Resource bank zero is reserved and cannot be a private working
destination.

When the service is unsupported or unavailable **before the first CONTROL of
a transfer**, the library uses the CPU implementation. After one piece
succeeds, an unavailable later bank returns `TI_E_IO`, because the earlier
pieces changed data. A CONTROL error or a response timeout also returns
`TI_E_IO` immediately.

In neither case does the library repeat a partly executed operation through
CPU copies. Callers must treat the destination as possibly partial, and stop
or recover at their own transaction boundary.

A response wait ends after 240 changes of the //e vertical-blank flag at
$C019. This is 2 s at 60 Hz and 2.4 s at 50 Hz, at any CPU speed. The slot-7
ROM itself waits without a limit. Time while the controller holds the CPU does
not count.

Malformed responses and uncertain CONTROL execution stop the private driver
for the rest of the program. After that, enables and transfers report an I/O
failure without another CONTROL. `ti_amem_disable` removes the acceleration
hooks. It does not clear this stopped state or restore partly changed data.
Do not use disable and retry as an automatic recovery after uncertain
execution.

`ti_amem_available` reports whether the hooks are enabled and the driver is
not stopped. Disable and runtime shutdown make it false. A later
initialization needs an explicit enable. `ti_amem_last_error` keeps the
controller error byte.

In a CPU-only build, enable returns `TI_E_UNAVAILABLE`, available is false,
and the private transport is absent.

The pause and resume hooks of the shared driver surround private
transactions. No other foreground component or NMI handler can claim C8 or
the FIFO while the driver owns it.

The transport restores the IRQ policy of the caller and INTCXROM, then
deselects C8. It does not select again an expansion ROM that was selected
before the call. Long operations mark a timing gap.

## Focused checks

```powershell
python tests/amem_validate.py --cc65-home D:/Repos/cc65
```

The script builds the optional C code, the memory API and the ca65 transport
independently under `build/amem/`, with `TI_PRIVATE_TRANSPORT=1`. It does not
overwrite the CPU-only archive. The focused 65C02 and controller model passes
7282 checks over eleven runs:

- CPU and private results are equal for cross-bank reads, writes, fills and
  copies between different handles. The normal scenario makes twelve
  successful CONTROL requests.
- Small operations and same-handle overlapping operations stay on the CPU
  path.
- Wrong signatures, and a valid signature with the wrong ROM CRC, cause zero
  raw FIFO writes and zero STATUS or CONTROL submissions.
- An unsupported status or an unavailable service selects the CPU before
  submission.
- A partly applied CONTROL failure and a response timeout give one CONTROL,
  no CPU replay and a stopped driver.
- Availability lost after the first bank, or a second bank beyond the
  reported maximum, returns an error and does not replay the completed part.
- The malformed response length, availability after shutdown, C8 and
  INTCXROM restoration, IRQ masking and AUX0 preservation are checked.

`build/amem/validation.json` records the requests and results. The fixture
uses a synthetic 256-byte ROM made to satisfy the CRC check, and an
independent raw FIFO and memory service. The fixture contains and runs no
controller ROM.
