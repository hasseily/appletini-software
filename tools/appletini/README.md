# Appletini development runner

`./emulator/appletini` runs Apple II programs through a native C machine core, with a
browser viewer, a command line for short runs, and a persistent JSONL debugger
for tools and AI agents. Its default target is the Appletini **13 MHz
UltraWarp** preset with **8 MiB AUX RAM and Phasor**. TURBO is optional.

The runner reuses the repository's
[a2vm core](../../demos/doom_gs/tools/a2vm/README.md), with a small C bridge and a
Python 3 standard-library front end. Raw programs and supported ProDOS SYSTEM
launches need no SDL, graphical session, or Apple ROM image. Programs that call
Apple ROM routines still need those routines to be available.

## Platforms

- **macOS:** built and tested, including browser play, audio and speech.
- **Linux:** the build supports a shared `.so` library with GCC or Clang;
  Linux execution has not yet been validated by this project's tests.
- **Windows:** native Windows is not supported yet. The main build and launcher
  still expect a Unix toolchain and `.so`/`.dylib` libraries, not a Windows DLL.
  WSL is the intended Linux route, but has not yet been tested. Use `--no-open`
  and open the printed local URL manually if browser launching is unavailable.

Source builds require Python 3, `make`, a C11 compiler, and a C++17 compiler
for speech. The viewer uses the browser's Canvas and Web Audio APIs. Keep the
repository together: `emulator/appletini` is the launcher; the implementation
remains in `tools/appletini` and reuses the core under `demos/doom_gs`.

## Run a program

Run these commands from the repository root. `make`, a C11 compiler and Python
3 are required; the native library is built on first use. Speech playback also
uses a C++17 compiler to build its separate persistent worker on first use.

```sh
./emulator/appletini profiles

# LDA #$41; STA $0300; STP: a complete test with no external files.
./emulator/appletini run --hex a9418d0003db --steps 10 \
  --expect 'main:0x300=41' --require-stop

./emulator/appletini run --binary program.bin \
  --load-address 0x2000 --entry 0x2000 --steps 1000000

./emulator/appletini run --binary program.bin \
  --load-address 0x2000 --entry 0x2000 --breakpoint 0x2040 \
  --expect 'main:0x300=41424344' \
  --dump 'main:0x300:16:output.bin'

./emulator/appletini run --disk IMAGE.hdv --system BOSCO.SYSTEM

# A standard SHR preview after a bounded run.
./emulator/appletini run --disk IMAGE.hdv --system BOSCO.SYSTEM \
  --frames 120 --screenshot frame.png
```

The disk command reads root-directory files from a raw ProDOS-order `.po` or
`.hdv` image, loads the chosen SYSTEM file, and supplies the core's ProDOS MLI
stand-in. Subdirectories and extended/resource-fork files are unsupported.
The source image is not modified. This direct launch uses a small MLI stand-in;
use `--boot` when testing real ProDOS behavior:

```sh
./emulator/appletini play --boot \
  --disk demos/appletini_bosconian/Appletini-Bosconian.hdv \
  --rom ../appletini-one/Assets/ROMs/Apple2e_Enhanced.rom
```

`--boot` starts at the supplied 16 KiB Apple ROM's reset vector and executes
the real slot-7 firmware and disk operating system. It requires `--disk` and
`--rom`, and excludes `--system` and injected entry/register settings. It loads
the C700 and C800 SmartPort ROMs from the neighboring `appletini-one` checkout
by default; use `--slot7-rom PATH` and `--slot7-c8-rom PATH` to supply 256-byte
and 2048-byte firmware files (`.mem` or binary). No Apple ROM is bundled.
Reported metadata includes the slot firmware paths and hashes. Boot mode does
not attach the MLI stand-in or trap the SmartPort firmware entry points.
Filesystem operations therefore use the mounted disk's session copy directly.
Guest writes still do not change the source image. This is SmartPort boot,
not a Disk II flux/controller implementation.

Memory expectations compare exact bytes, written as hexadecimal pairs. Dumps
write raw bytes. Spaces are `main`, `aux`/`aux0` through `aux127`, `lc` and
`lc1`; the default 128 AUX banks provide 8 MiB of AUX storage.

Use `--steps`, `--cycles` or `--frames` to bound a run. `--cycles` counts the
machine's clock ticks: initial CPU-rate ticks for fixed speeds, fabric clocks
for TURBO. Live acceleration changes keep this clock and all device deadlines
stable; `state.cycles` remains the raw CPU-cycle counter, while `state.ticks`
and cycle budgets use the original clock. `machine.clock_profile` identifies
that original profile and `nominal_cpu_hz` reports the current CPU rate.
`--frames` counts video-frame durations, not rendered output frames.
With no budget, a batch run stops after 60 frame durations. A whole instruction
may cross a cycle budget. `--timeout` caps host run time (default 30 seconds).
Breakpoints stop before the chosen instruction, including the initial PC.

Batch output is JSON with schema `appletini-cli-1`, the profile and program
hash, stop reason, registers, counters, assertions and host throughput. Exit
status 0 means the requested run/assertions succeeded, 1 means an assertion or
guest halt failed, 2 means a request/setup error, and 3 means a timeout or an
unreached required stop. Use `--require-stop` to fail when a budget runs out
before STP or a breakpoint; specifying a breakpoint also requires a stop.

## Play in the browser

```sh
./emulator/appletini play --disk IMAGE.hdv --system BOSCO.SYSTEM
./emulator/appletini play --disk IMAGE.hdv --system BOSCO.SYSTEM --slot2 4play
```

`play` opens a local browser viewer connected to the same C machine. It binds
only to `127.0.0.1`, chooses an available port and prints the session URL. Use
`--no-open` to open that URL yourself or `--port NUMBER` to choose a port.
The page offers pause, frame step, stop, and joystick, keyboard and mouse input
modes. It advances bounded guest-frame batches at the selected video cadence.
The **Acceleration** selector changes between 1, 13, 26 and 33 MHz while
preserving the running program, video timing and audio pitch. A paused program
stays paused. Switching to or from the historical TURBO model shows an explicit
restart button because that model uses a different clock and accounting system.
Subsequent restarts retain the selected acceleration.

The viewer supports Apple text, lores, HGR, double lores, DHGR, standard SHR
and SuperSprite memory previews. Click **Enable sound** to start browser audio;
**Mute sound** and the volume slider control playback. Pausing or leaving the
window clears queued sound so it cannot resume with stale audio. The **Apple Return** button sends
Return to a startup prompt while Enter remains the controller's Start button.
Left/Right Option drive the Open/Closed Apple keys.

The default **4:3** view keeps the same screen proportions across video modes.
Choose **Appletini native** under Aspect for the current firmware's layout:
560×384 for Apple/SuperSprite and 640×400 for SHR. Display dimensions are
separate from raw framebuffer dimensions, so 80-column or 640-pixel modes do
not make the display twice as wide. PNG captures retain their raw resolution.

When a directly launched program calls ProDOS QUIT, the viewer shows
**Program exited** with **Restart program**. Restart creates a fresh machine
with the original launch options, releases controls, and clears queued sound.
With `--wav`, each restarted run gets a separate recording. There is no ProDOS
desktop in direct-launch mode; `--boot` continues into the actual disk OS.

Pause retains the last image and machine state. **Step frame** advances one
guest-frame duration while leaving the viewer paused. Closing the browser
does not stop its local server; use **Stop session** or interrupt the command.

## Audio and speech captures

Browser play enables sound synthesis by default. Use `--no-audio` for a silent,
faster viewer, or `--no-speech` to omit only SSI-263 synthesis. Browser policy
requires clicking **Enable sound** before playback can begin. The same guest
sound can be captured without a browser:

```sh
./emulator/appletini run --disk demos/appletini_bosconian/Appletini-Bosconian.hdv \
  --system BOSCO.SYSTEM --frames 180 --wav title.wav

# Includes gameplay music, effects, and the game's speech register writes.
./emulator/appletini debug --disk demos/appletini_bosconian/Appletini-Bosconian.hdv \
  --system BOSCO.SYSTEM --script tools/appletini/examples/bosconian.jsonl \
  --wav gameplay.wav
```

`--wav PATH` streams 48 kHz, signed 16-bit stereo PCM into a WAV file and
finalizes its header when the session exits. `--audio` synthesizes without
writing a file, useful for inspecting a repeatable PCM digest. JSON state
reports sample count, duration, peak, SHA-256, and overflow status. Ordinary
`run` and `debug` sessions skip synthesis unless requested; guest SSI status
and IRQ behavior still work. Debugger pauses do not insert wall-clock silence.

Sound writes are timestamped in guest time, so multiple changes within a
video frame remain audible. Native buffers are bounded; the runner drains and
resumes when they fill. PCM uses the selected clock rounded to the nearest Hz
(less than 0.03 ppm difference for these profiles). The initial audio model
includes four Phasor AY chips, the SuperSprite YM voice channels, the Apple
speaker, and two SSI-263 sockets. It uses the target's default Phasor pan and
host DC filtering; configurable board EQ, analog amplifier behavior, and
bit-identical FPGA PSG output are not claimed.

Speech uses a separate persistent executable built from the Appletini target's
native SSI reference engine, with timestamped register events and batched PCM
transport. It does not use operating-system text-to-speech or prerecorded
phrases. See [speech provenance and protocol](speech/README.md). Its GPL-3.0
sources are built separately from the GPL-2.0-only machine library.

## Cards and inputs

Defaults are slot-2 Mouse, slot-4 Phasor, and slot-7 SmartPort. Use
`--slot2 off|mouse|4play|snes` to choose one slot-2 device for `run`, `debug` or
`play`. `snes` selects the SNES MAX serial interface. Keyboard and Apple
joystick/paddle inputs remain available alongside the selected card.

`--slot7 supersprite` selects SuperSprite after loading the program. During a
debug session, `{"cmd":"configure","slot7":"supersprite"}` switches at the
point the game needs it; `"slot7":"smartport"` switches back. The two devices
share the slot and cannot both answer at once. SuperSprite's register/VRAM
model is inspectable, and the viewer can decode its current image and sprites.
`{"cmd":"configure","slot2":"snes"}` changes slot 2.

SmartPort models controller/unit status, block reads and writes, and the FIFO
transport. Direct launch traps its service entry points; `--boot` executes
the supplied card firmware. Guest block writes stay in the session. In direct
launch they do not update the separate MLI file view; boot mode has a single
disk view because real ProDOS handles file access. SuperSprite models VRAM, control and AY
registers, VBlank/IRQ, and sprite collision/fifth-sprite flags. Sprite flags
update at virtual VBlank rather than through the board's asynchronous ARM
renderer. Phasor and SuperSprite AY voices, the Apple speaker, and both SSI-263 speech
sockets synthesize stereo audio. Exact card timing is not yet hardware validated.

The `input` command uses `kind`, `x` and `y`. `paddle` sets axis `x` (0–3) to
position `y` (0–255); `button` sets Apple button `x` (0–2) to `y` (0/1).
`pad` sets player `x` (0–3) to a 12-bit SNES button word in `y`, or disconnects
it with `y:-1`. Bit order is B, Y, Select, Start, Up, Down, Left, Right, A, X,
L, R. `key`, `hold`, `release`, `mouse`, `mouse-to`, and `buttons` provide the
keyboard and mouse inputs.

## Keep a debugger session open

```sh
./emulator/appletini debug --binary program.bin --load-address 0x2000 --entry 0x2000
```

The debugger accepts one JSON object per input line and replies with one JSON
object, echoing the optional `id`. It keeps the machine in memory between
requests. This complete session steps an instruction, runs to a breakpoint,
and checks the written byte:

```sh
./emulator/appletini debug --hex a9418d0003db <<'JSONL'
{"id":1,"cmd":"state"}
{"id":2,"cmd":"step"}
{"id":3,"cmd":"run","steps":10,"breakpoints":["0x2005"]}
{"id":4,"cmd":"read","space":"main","address":"0x300","length":1}
{"id":5,"cmd":"assert","space":"main","address":"0x300","data":"41"}
{"id":6,"cmd":"quit"}
JSONL
```

Other requests include `{"cmd":"registers","values":{"a":65}}`,
`{"cmd":"write","space":"main","address":"0x300","data":"4142"}`,
and `{"cmd":"input","kind":"key","x":65}`. `read` and `write` access raw
storage without I/O effects; `bus-read` and `bus-write` take an `address` and
deliberately trigger the CPU mapping and soft switches (`bus-write` also takes
`value`). Register and memory bounds are checked before mutation. Use
`--script commands.jsonl` to read requests from a file. An invalid request
returns `ok:false`; later valid requests can still use the session.

The included Bosconian script waits for its title state, starts a game, holds
right and fire for 30 frames, releases the controls, and writes
`build/bosconian-play.png`:

```sh
./emulator/appletini debug \
  --disk demos/appletini_bosconian/Appletini-Bosconian.hdv \
  --system BOSCO.SYSTEM --script tools/appletini/examples/bosconian.jsonl
```

## Keyboard controller mapping

The debugger's `{"cmd":"keyboard-state","codes":["KeyQ","Space"]}` request
uses the same mapping as browser play. Send `"codes":[]` to release it.
The shared `controls.events(codes)` function maps held physical key codes to
paddles, Apple buttons, and player 1's gamepad. It emits the full state on every
call so key releases cannot leave a direction or button held.

```text
Q ↖   W ↑   E ↗
A ←   S ·   D →
Z ↙   X ↓   C ↘
```

`S` centers both axes and opposite directions cancel. Center is 128; the ends
are 0 and 255. The same directions drive the digital gamepad.

| Key | SNES MAX | 4Play / Apple joystick |
| --- | --- | --- |
| Space | B | Trigger 1 / button 0 |
| J | A | Trigger 2 / button 1 |
| K | Y | Trigger 3 / button 2 |
| Enter | Start | — |
| Tab | Select | — |
| U | X | — |
| I / O | L / R | — |

These keys belong to the controller while joystick input has focus. Guest
keyboard input is a separate mode so a movement key does not also type into
the game.

## Timing profiles

| Profile | Meaning | Appropriate use |
| --- | --- | --- |
| `mhz1` | Functional execution at nominal 1 MHz | Slow-machine behavior and debugging; not cycle-exact motherboard timing |
| `ultrawarp` (default) | W65C02 functional execution with classic CPU cycles at a nominal 13.333333 MHz | Program behavior, bounded execution, memory assertions and repeatable input tests |
| `vtw26` / `vtw33` | The same functional model at nominal 26.666667 / 33.333333 MHz | Testing software at the other fixed CPU rates |
| `turbo-f122` | a2vm's historical `f122+nod2+phasor` cost model: virtual Disk II replay off, Phasor slot-4 slowdown on | Comparing code paths under that explicitly selected historical model |

The firmware calls its divider-10 preset **13 MHz (UltraWarp)**. Its fabric is
about 133.333 MHz. The default runner uses that nominal CPU rate but does not
yet reproduce all fixed-speed motherboard waits, posted-write stalls, device
slowdowns, or extended-memory costs. It is not a validated prediction of
physical-board frame rate.

Select profiles and video timing with `--profile turbo-f122` and `--video pal`
on `run`, `debug` or `play`; defaults are `ultrawarp` and `ntsc`.
The JSONL debugger can change fixed speeds without restarting:

```json
{"cmd":"configure","profile":"vtw26"}
{"cmd":"run","frames":60}
{"cmd":"configure","profile":"vtw33"}
```

The `configure` command rejects a switch to or from `turbo-f122`; launch a new
debugger process with that profile instead. Live fixed-speed changes preserve
RAM, registers, timer deadlines, video phase, sound-chip phase and any recording.

Headless runs execute as fast as the host permits. Host throughput and elapsed host
time describe the development tool; guest cycles and guest time describe the
selected model. Neither a fast host run nor a nominal guest clock proves a
port's performance on the card. PAL and NTSC timing can be selected; NTSC is
the default.

TURBO batches video writes: it sends accepted writes to the renderer and
maintains a separate coalescing motherboard mirror. The cost model already
accounts for the mirror, active and deferred pages, and synchronization
barriers. Do not charge each video byte as a blocking 1 MHz motherboard
transaction. Display changes, device entry and memory holds can still require
pending writes to drain.

Use `--cost-report costs.json` with `turbo-f122` to save the historical model's
detailed counters. The debugger also accepts `{"cmd":"cost-report","path":"costs.json"}`.

The optional profile derives from `appletini-one` commit `3101934` (F1.2.2).
The hardware checkout audited for this runner is
`1a3e8d38c57814471640c748879af28dbf16b266` (F1.2.5-d1). Their core TURBO batching
design is substantially shared, but that does not establish full model
coverage. For example, a2vm does not cover the current paged-MAIN SHR and armed
linear-overlay video policies. Calibration recorded for older workloads is
not validation of arbitrary new programs or the current installed firmware.

## Scope and next work

The underlying core covers W65C02 execution, Apple IIe memory switches and
RamWorks banking, plus the devices and ProDOS services used by the existing
Appletini Doom tools. Phasor registers, timers, speech handshakes and synthesized sound are modeled.
This front end adds a reusable launch and inspection interface.

`--screenshot`, the debugger's `screenshot` command, and browser play decode
the current memory into a full-screen preview. Legacy Apple modes use the
production RGB cell algorithms, including mixed mode and page selection. Text
uses the repository's readable launcher font by default; `--video-rom PATH`
loads a supplied 4 KiB enhanced //e character ROM for exact glyphs and MouseText.
The preview does not model composite color filtering. Standard 320/640 SHR uses AUX
memory, the production renderer's nibble-times-16 color scale, and NEWVIDEO's
monochrome flag. SHR4/3200 modes are rejected.

With SuperSprite selected, the preview supports Appletini's Graphics I,
Graphics II, text and multicolor modes, plus sprites, size and magnification.
It follows the current firmware's render paths rather than claiming general
TMS9918 accuracy. Mixed modes are rejected. This preview shows SuperSprite
alone, without its overlay/Apple-video composition switches; a blanked display
shows its backdrop rather than retaining a prior hardware frame.

These previews do not reproduce the production capture stream, raster timing,
display history, or deferred publication of video writes. Complete snapshot
restoration, Disk II media support, and a current-hardware timing model remain
future work. NES ports remain Apple-target programs; this is not an NES
console emulator.

The next milestones are to validate fixed 13 MHz timing against RTL and board
measurements, compare framebuffers with the production Appletini renderer,
and extend the human-facing display and debugger on the same machine API.
TURBO needs a separately versioned validation set.

The machine library and Python front end are licensed under GPL-2.0-only and
reuse the existing GPL-2.0 a2vm implementation. The separately built speech
worker and its reference sources have their own GPL-3.0 license and notices. See its [license](../../demos/doom_gs/LICENSE) and
[source notices](../../demos/doom_gs/README.md#licence).
