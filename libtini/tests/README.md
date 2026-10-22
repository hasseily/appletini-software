# Focused SDK and game checks

The full runner is `python tools/check.py --cc65-home D:/Repos/cc65
--cc C:/msys64/ucrt64/bin/gcc.exe`. Add `--rom-boot` with the installed
local ROM inputs to boot the audio demo and the games in ProDOS.
[Checks](../docs/reference/testing.html) gives each check, the script that it
runs and the type of evidence. Each `*_validate.py` and `test_*.py` script in
this folder can also run alone. The foundation harness below is one part of
the full suite.

Run it from the `libtini/` folder with cc65 2.19, Python 3.10 or newer and
`py65==1.2.0` installed:

```powershell
python tools/test.py
```

This command builds the diagnostic and a separate test SYS. Both use the same
C memory implementation, assembly backend, startup, linker layout and
installed cc65 runtime. `python tools/test.py --no-build` uses the existing
output.

The host checks cover:

- The ProDOS seedling and sapling size limits and the exact packaged payloads.
- Deterministic image generation.
- The rejection of a corrupt directory, allocation or bitmap.
- The normalization of the ca65 informational timestamp.
- The map, listing and call-path accounting of `tools/profiler.py`.

The 65C02 checks run the linked target instructions on py65, with separate
main and auxiliary memory and the standard Apple //e switch effects. They
check near moves and fills, the two overlap directions, transfers across a
logical bank boundary, resource copies and fills, and reserved addresses.
They also check invalid ranges, full capacity, a full handle table,
generation exhaustion, stale handles, shutdown and a second initialization.
An assembly helper checks that the processor status stays the same, with
interrupts enabled and disabled at entry.

More runs check:

- The rejection of aliased banks and different display switches at entry.
- Observed display edges against elapsed time, a missing time source, the
  wrap of the elapsed counter and a long service gap.
- That startup and exit restore the zero page, the page-one trampoline, the
  main OS workspace and all AUX0 bytes, then call ProDOS MLI QUIT with the
  original IRQ policy.

The model has no private SmartPort services and rejects slot-7 I/O. The
checks require that AUX instruction fetches stay in the page-one trampoline,
and that IRQs stay masked while transfer mappings are active. They measure
the hardware stack depth at each instruction. They require that the lower
page-one workspace of ProDOS does not change. They check the C software stack
at each call and return, because its bytewise updates have temporary
intermediate values. A separate launch starts with decimal mode, IRQ-disable
and carry set, and requires the saved processor flags at QUIT.

The test also runs the diagnostic program until it waits for a key. It reads
the AUX0 framebuffer that the CPU wrote, checks all five PASS rows and sends a
key. Then it requires a clean exit and restored AUX0 and zero page bytes. It
writes the memory image to `build/diagnostic-emulated.png` with the real SCBs
and palette bytes.

These checks do not boot ProDOS. The runner loads the SYS as ProDOS does and
traps the QUIT MLI call. They model memory switches and sample display
levels. They do not model Appletini video capture, display timing, bus
contention, physical interrupts, 33 MHz or TURBO. The `--rom-boot` checks
boot ProDOS.
