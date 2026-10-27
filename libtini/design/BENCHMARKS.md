# Reproducible native benchmarks

`tools/benchmark.py` builds a separate SYS file and disk from
`examples/benchmark.c`. It does not change the code, layout or resource
budget of any game. The measurements run the linked C and 65C02 routines on
the unchanged native Appletini machine. They are not host reference copies or
Python timing estimates.

With the installed tools and the local ProDOS input:

```powershell
python tools/benchmark.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe
```

The default boots ProDOS with the bundled ROMs in `build-inputs/native-roms/`.
Use `--boot-roms DIR` to override that directory. Use `--direct-launch` for
a direct SYS launch with the MLI stand-in. `--private` also builds a separate
optional binary. If its
controller is unidentified or unavailable, the report says that acceleration
is inactive and measures the CPU fallback. The tool never overwrites the
compiled CPU archive.

For the optional service on a real ROM and ProDOS boot, use the bundled
inputs that [DEPENDENCIES.md](../tools/DEPENDENCIES.md) describes:

```powershell
python tools/benchmark.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe --private --repeat 2
```

The benchmark checks the source snapshot hashes, records the target, tool and
header hashes, checks the operation results and needs a normal cleanup and
ProDOS QUIT. Repeated runs must give identical guest-counter differences.
`--output` selects a JSON result path in the repository.

The artifacts are in `build/benchmark/cpu/`, `build/benchmark/private/` and
`build/benchmark/results.json`. Separate `build.json` manifests describe each
binary and disk. No build reads a sibling checkout or downloads a tool or
ROM.

## What is measured

Exported phase markers surround these operations: resource writes and reads
of 512 bytes, fills and copies between different handles of 1024 bytes, a
full 32000-byte SHR publication, and the draw and publication of a changed
65x17 rectangle at the odd x position 11.

All memory workloads cross a physical bank boundary, and the copy crosses
the source and destination boundaries. The changed rectangle touches 33
packed bytes per row, 561 bytes in total. Copy sizes count the requested
result bytes, not the combined read and write traffic.

The runner records raw CPU cycles, profile clock ticks, instruction and I/O
counts, the SHR bytes written and the modeled elapsed seconds. It checks the
memory and pixel results through independent raw storage reads while the
guest is paused.

Publication uses normal CPU writes in the two binaries. When the optional
service is active, the `turbo-f122` cost counters show eight AMEM operations
with 3072 requested bytes in total. Video adds no AMEM operation.

The counter differences include the small overhead of the markers and the
result store. A no-op phase shows that overhead, 31 CPU cycles in this run.
The tool does not subtract an estimated overhead. Setup, allocation, the
first clear, the OS backup and the final restoration are outside the
operation measurements.

## Emulator results

A local full-ROM run of the current build, repeated two times with identical
counters, gives:

| Operation | Bytes | CPU vtw33 modeled ms | CPU turbo-f122 modeled ms | AMEM vtw33 modeled ms | AMEM turbo-f122 modeled ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Cross-bank resource write | 512 | 0.728 | 0.567 | 1.293 | 0.972 |
| Cross-bank resource read | 512 | 0.728 | 0.939 | 1.293 | 0.959 |
| Cross-bank resource fill | 1024 | 1.838 | 1.024 | 1.248 | 0.933 |
| Cross-bank resource copy | 1024 | 4.991 | 2.677 | 1.731 | 1.182 |
| Full CPU SHR publication | 32000 | 40.805 | 85.149 | 41.046 | 85.153 |
| Changed rectangle draw | 561 | 1.576 | 2.564 | 1.581 | 2.562 |
| Changed rectangle CPU SHR publication | 561 | 1.347 | 2.132 | 1.351 | 2.122 |

The rectangle draw makes one row, checks the surface in 16-bit arithmetic and
writes the row to every line with one assembly routine. Publication copies
all its rows with the same routine. The resource transfers use the same
bank-window lookup as the row routine.

AMEM is enabled in the two optional profiles. Its request and setup overhead
can cost more than a CPU loop for small transfers. The CPU video times of the
two separately linked binaries are different, because the code layout, the
hook checks and the cache state of the `turbo-f122` model are different.
These differences do not come from private video acceleration. The JSON
records the exact raw cycle and tick counts.

`vtw33` is functional execution at a nominal 33.333333 MHz without all
motherboard and device waits. `turbo-f122` is the TURBO cost model of the
emulator. The two models do not include the production capture stream, HDMI
presentation or physical interrupt and audio latency.

## Profiling a game

`tools/profiler.py` measures named functions of a game that `tools/build.py`
built. It boots the disk of the game on the native machine from the
installed ROM inputs, waits for `main`, sends the given keys and then
measures a window of model frames:

```powershell
python tools/profiler.py --game starfall --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe --key 13 --skip 360 --frames 1200 --count _sf_frames:4 _render _hud _field _ti_gfx_text_opaque _ti_gfx_present
```

The time of each function includes the functions that it calls and any
interrupt that arrives during the call. The report lists the time for each
call path, for example `_hud/_field/_ti_gfx_text_opaque`, with the calls, the
milliseconds for each call and the share of the window. `--count LABEL:BYTES`
reports how much a variable changed, here the frames drawn.

Exported names come from the label file. Static C functions and other
assembler labels come from listings of the sources that the build staged in
`build/asm`. The tool stops when a listing does not agree with the linked
label file. For a name that several modules define, give `module:name`.

A function that already runs when the window opens counts only from its next
call. The JSON report goes to `build/profile/`.

These are the STARFALL HUD figures over 20 model seconds of play on a
Mockingboard:

| Each update | vtw33 | turbo-f122 |
| --- | ---: | ---: |
| HUD value of 2-8 characters | 1.9 ms | 1.5 ms |
| Its text | 1.0 ms | 0.6 ms |
| Its publication | 0.8 ms | 0.9 ms |
| Gauge bar | 1.6 ms | 1.2 ms |
| Caption bar | 5.2 ms | 5.6 ms |
| Game steps not drawn | 0 of 614 | 0 of 614 |

A HUD value is opaque text, and the game publishes only its cells. Text,
rectangles and publication move whole rows with one assembly routine. The
surface check and the clip use 16-bit arithmetic. A step of 33.3 ms has room
for the 14.3-14.4 ms playfield and any one HUD change.

At `vtw33`, a text row costs 0.017 ms. The surface check takes 0.13 ms a
call, the clip 0.06 ms and the location of the first byte of the surface
0.08 ms. The copy of the rows of a published value takes 0.28 ms.

The parallax backdrop of STARFALL puts 24 distant aircraft under the
playfield. These are the milliseconds per drawn frame over 20 model seconds,
in the first sector and about 40 seconds into play, with the backdrop off and
on. The game draws every step in all eight runs.

| Frame part | vtw33 off | vtw33 on | turbo-f122 off | turbo-f122 on |
| --- | ---: | ---: | ---: | ---: |
| Whole frame, first sector | 13.7 | 19.8 | 14.0 | 19.6 |
| Whole frame, 40 s in | 14.1 | 20.3 | 14.0 | 19.7 |
| Scene draw, 40 s in | 10.3 | 15.3 | 12.0 | 17.0 |
| Sprite list, 40 s in | 3.6 | 4.7 | 1.9 | 2.5 |

The backdrop costs about 6 ms a frame at `vtw33` and 5.5 ms at `turbo-f122`.
Its list costs about 1,600 cycles for each aircraft, mostly in
`ti_scene_add`, which marks the blocks that a moved sprite leaves and
enters.

The game lists its stars and aircraft with running positions. The stars of
one speed, and the aircraft of one image, are each a fixed step below the
previous one. Thus a frame does 10 divisions, not 112. This costs 230 bytes
of game memory, which the STARFALL layout has.

In the draw, nearly every 8-line band holds a changed block in each frame.
The composition, clear and publication of those blocks increase with the
number of moving sprites. The library gives priority to memory over small
speed gains, because every game that links it pays for its bytes.
