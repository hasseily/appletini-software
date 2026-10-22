# Reproducible native benchmarks

`tools/benchmark.py` builds a separate `examples/benchmark.c` SYS and disk. It
does not change any game's code, layout or resource budget. Measurements run
the actual linked C/65C02 routines on the unchanged native Appletini machine;
they are not host reference copies or Python timing estimates.

With the installed tools and local ProDOS input:

```powershell
python tools/benchmark.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe
```

This default uses direct SYS launch and its MLI stand-in, requiring no Apple
ROM. `--private` also builds a distinct optional binary. If its controller is
unidentified or unavailable, the report explicitly says acceleration is
inactive and measures the CPU fallback. The compiled CPU archive is never
overwritten.

For the optional service on a real ROM/ProDOS boot, supply the independently
installed, ignored inputs described in [DEPENDENCIES.md](../tools/DEPENDENCIES.md):

```powershell
python tools/benchmark.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe --private --boot-roms build-inputs/native-roms --repeat 2
```

The benchmark checks the source snapshot hashes, records target/tool/header
hashes, validates operation results, and requires normal cleanup and ProDOS
QUIT. Repeated runs must produce identical guest-counter differences.
`--output` selects a repo-local JSON result path. Artifacts are under
`build/benchmark/cpu/`, `build/benchmark/private/` and
`build/benchmark/results.json`; separate `build.json` manifests describe each
binary and disk. No build reads a sibling checkout or downloads a tool/ROM.

## What is measured

Exported phase markers bracket resource writes/reads of 512 bytes, fills and
distinct-handle copies of 1024 bytes, full 32000-byte SHR publication, and
drawing/publishing a dirty 65x17 rectangle at odd x=11. All memory workloads
cross a physical bank boundary; the copy crosses both source and destination
boundaries. The dirty rectangle touches 33 packed bytes per row, or 561 bytes.
Copy sizes count requested result bytes, not combined read-plus-write traffic.

The runner records raw CPU cycles, profile clock ticks, instruction and I/O
counts, actual SHR bytes written and modeled elapsed seconds. It validates
memory/pixel results through independent raw storage reads while the guest is
paused. Publication remains normal CPU writes in both binaries. Historical
TURBO cost counters confirm eight AMEM operations totaling 3072 requested
bytes when the optional service is active; video adds no AMEM operation.

Counter differences include the small marker/result-store overhead. A no-op
phase reports that reference (31 CPU cycles in this run); the tool does not
silently subtract an approximate overhead. Setup, allocation, initial clear,
OS backup and final restoration lie outside the operation measurements.

## Recorded emulator results

The local full-ROM run of the current build, repeated twice with identical
counters, produced:

| Operation | Bytes | CPU vtw33 modeled ms | CPU historical TURBO modeled ms | AMEM vtw33 modeled ms | AMEM historical TURBO modeled ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Cross-bank resource write | 512 | 0.728 | 0.567 | 1.293 | 0.972 |
| Cross-bank resource read | 512 | 0.728 | 0.939 | 1.293 | 0.959 |
| Cross-bank resource fill | 1024 | 1.838 | 1.024 | 1.248 | 0.933 |
| Cross-bank resource copy | 1024 | 4.991 | 2.677 | 1.731 | 1.182 |
| Full CPU SHR publication | 32000 | 40.805 | 85.149 | 41.046 | 85.153 |
| Dirty rectangle draw | 561 | 1.576 | 2.564 | 1.581 | 2.562 |
| Dirty CPU SHR publication | 561 | 1.347 | 2.132 | 1.351 | 2.122 |

The rectangle builds one row, checks the surface in 16-bit arithmetic and
writes the row to every line with one assembly routine. It took 14.120,
8.420, 14.837 and 8.748 ms when it decided each byte in C and called
`ti_res_write` for each line. Publication copies all its rows with the same
routine; it took 159.641, 138.574, 167.804 and 143.720 ms for the full
screen and 6.583, 4.428, 6.944 and 4.638 ms for the dirty rectangle with a
resource read and a screen write for each row.

The resource transfers now share the bank-window lookup the row routine
uses. That saved 97 bytes and costs each call a little: against the record
before these changes, the CPU vtw33 fill and copy are 0.09 and 0.20 ms
slower and the reads and writes 0.01 ms. The optional binary's historical
TURBO transfers rose by 0.23-0.24 ms; that model's costs also depend on
code placement.

AMEM was enabled in both optional profiles. Its request/setup overhead can
cost more than a CPU loop for small transfers. CPU video timings differ
between the two separately linked binaries because code layout, hook checks
and the historical model's cache state differ; those differences do not
represent private video acceleration. The JSON records exact raw cycle/tick
counts rather than only these rounded figures.

These numbers describe the selected emulator models. `vtw33` uses functional
execution at nominal 33.333333 MHz without all motherboard/device waits.
`turbo-f122` uses historical F1.2.2 costs, not complete F1.3.2 board timing.
Neither measures the production capture stream, HDMI presentation or physical
interrupt/audio latency. Board measurements at 33 MHz and TURBO remain required
before claiming bandwidth, a visual deadline, or a game frame rate.

## Profiling a game

`tools/profiler.py` times named functions of a game that `tools/build.py` has
built. It boots the game's disk on the native machine from the installed ROM
inputs, waits for `main`, sends the given keys and then measures a window of
model frames:

```powershell
python tools/profiler.py --game starfall --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe --key 13 --skip 360 --frames 1200 --count _sf_frames:4 _render _hud _field _ti_gfx_text_opaque _ti_gfx_present
```

Each function's time includes the functions it calls and any interrupt that
arrives meanwhile. The report lists it per call path, such as
`_hud/_field/_ti_gfx_text_opaque`, with calls, milliseconds a call and its
share of the window. `--count LABEL:BYTES` reports how much a variable
changed, here the frames drawn. Exported names come from the label file.
Static C functions and other assembler labels come from listings of the
sources the build staged in `build/asm`; the tool stops when a listing
disagrees with the linked label file. Give a name that several modules
define as `module:name`. A function already running when the window opens
counts only from its next call. The JSON report goes to `build/profile/`.

STARFALL's HUD over 20 model seconds of play on a Mockingboard, before and
after the row-at-a-time text, opaque HUD values and the faster rectangles.
The earlier figures come from the same method on the previous build:

| Each update | vtw33 before | vtw33 now | TURBO before | TURBO now |
| --- | ---: | ---: | ---: | ---: |
| HUD value of 2-8 characters | 30.7 ms | 1.9 ms | 17.8 ms | 1.5 ms |
| Its clear and text | 26.3 ms | 1.0 ms | 14.2 ms | 0.6 ms |
| Its publication | 4.4 ms | 0.8 ms | 3.6 ms | 0.9 ms |
| Gauge bar | 4.6 ms | 1.6 ms | 2.7 ms | 1.2 ms |
| Caption bar | 50.7 ms | 5.2 ms | 31.1 ms | 5.6 ms |
| Game steps not drawn | 53 of 600 | 0 of 614 | 25 of 600 | 0 of 614 |

A value used to clear its box with a rectangle, draw text a pixel at a time
and publish a 72x10 area through a resource read and a screen write for
each row. It now draws opaque text and publishes only its own cells. Text,
rectangles and publication move whole rows with one assembly routine
instead of a resource call per row, and the surface check and clipping use
16-bit arithmetic. A step of 33.3 ms has room for the 14.3-14.4 ms playfield
and any one HUD change.

At vtw33 a text row now costs 0.017 ms, where `ti_res_write` took 0.19 ms
to move the same 21 bytes. The surface check takes 0.13 ms a call, against
0.31 ms in 32-bit arithmetic, clipping 0.06 ms against 0.11, and locating
the surface's first byte 0.08 ms. Copying a published value's rows takes
0.28 ms.

STARFALL's parallax backdrop, 24 distant aircraft under the playfield, on
and off: milliseconds per drawn frame over 20 model seconds, in the first
sector and about 40 seconds in. Every game step was drawn in all eight runs.

| Frame part | vtw33 off | vtw33 on | TURBO off | TURBO on |
| --- | ---: | ---: | ---: | ---: |
| Whole frame, first sector | 13.7 | 19.8 | 14.0 | 19.6 |
| Whole frame, 40 s in | 14.1 | 20.3 | 14.0 | 19.7 |
| Scene drawing, 40 s in | 10.3 | 15.3 | 12.0 | 17.0 |
| Listing the sprites, 40 s in | 3.6 | 4.7 | 1.9 | 2.5 |

The backdrop costs about 6 ms a frame at vtw33 and 5.5 ms at TURBO. Listing
it costs about 1,600 cycles an aircraft, mostly in `ti_scene_add` marking
the blocks a moved sprite leaves and enters. The game lists its stars and
aircraft with running positions: the stars of one speed, and the aircraft
of one image, are each a fixed step below the one before, so a frame
divides 10 times instead of 112. With the per-entry multiply and divide
the listing took 6.3 ms with the backdrop and 4.1 ms without at vtw33, and
3.1 and 2.1 ms at TURBO; the change costs 230 bytes of game memory, which
STARFALL's own layout has. In the drawing, nearly every 8-line band holds a
changed block each frame, and composing, clearing and publishing those
blocks grow with the moving sprites. Three library changes were measured and
not kept: the library favours memory, which every game that links it pays,
over small speed gains. They were a call listing a field of such sprites
(about 540 bytes), skipping sprites that touch no changed block of their
band (35 bytes, under 0.4 ms saved and slower with the backdrop off), and
several narrow rows to one publication burst (about 90 bytes for 1 ms).
