# Focused SDK and game checks

The complete runner is `python tools/check.py --cc65-home D:/Repos/cc65
--cc C:/msys64/ucrt64/bin/gcc.exe`. Add `--rom-boot` with the separately
installed repo-local ROM inputs for real ProDOS audio/game integration.
Commands, evidence classes, counts and board gates are maintained in
[docs/VALIDATION.md](../docs/VALIDATION.md). The foundation harness below
is one part of that suite, not a substitute for device/game tests.

Run from the repository root with installed cc65 2.19, Python 3.10 or newer,
and `py65==1.2.0`:

```powershell
python tools/test.py
```

This builds the diagnostic and a separate test SYS using the same C memory
implementation, assembly backend, startup, linker layout and installed cc65
runtime. `python tools/test.py --no-build` reuses existing output.

The host checks cover ProDOS seedling/sapling size boundaries, exact packaged
payloads, deterministic image generation, corrupt directory/allocation/bitmap
rejection, the restricted ca65 informational timestamp normalization, and
`tools/profiler.py`'s map, listing and call-path accounting.

The 65C02 checks execute actual linked target instructions on py65, with
independent main and auxiliary memory storage and standard Apple //e switch
effects. They exercise near moves/fills, both overlap directions, crossing a
logical bank boundary, resource copies/fills, reserved addresses, invalid
ranges, full capacity, full handle table, generation exhaustion, stale handles,
shutdown and reinitialization. A direct assembly helper verifies processor
status preservation with interrupts initially enabled and disabled.

Further runs check alias-bank rejection, different initial display-switch
states, observed display edges versus elapsed time, missing time sources,
elapsed counter wrap and a long service gap. Startup/exit checks compare zero
page, the page-one trampoline, main OS workspace and all AUX0 bytes with their
initial contents, then require ProDOS MLI QUIT with the original IRQ policy.
The model provides no private SmartPort services and rejects slot-7 I/O.
Execution checks require AUX instruction fetches to stay in the page-one
trampoline and IRQs to remain masked whenever transfer mappings are active.
They track hardware stack depth on every instruction, require ProDOS's lower
page-one workspace to remain untouched, and check the C software stack at
call/return boundaries (its bytewise updates have temporary intermediate
values). A separate launch starts with decimal mode, IRQ-disable and carry
set, and requires the saved processor flags back at QUIT.

The actual diagnostic is also executed to its keyboard wait. The test samples
the CPU-written AUX0 framebuffer, checks all five PASS rows and injects a key.
It requires clean exit and restored AUX0/ZP. The sampled memory is rendered to
`build/diagnostic-emulated.png` using the real SCBs and palette bytes.

These checks do not boot ProDOS: the runner loads the SYS as ProDOS would and
traps the documented QUIT MLI. They model memory switching and sample display
levels; they do not emulate Appletini video capture, display timing, bus
contention, physical interrupts, 33 MHz or TURBO. The PNG is an emulated memory
render, not a board screenshot. Board results and full boot tests are recorded
separately in the project validation documentation.
