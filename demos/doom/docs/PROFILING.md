# Profiling Doom on Appletini

Use the hardware sampler to find the expensive parts on your machine. Use the
instruction profiler to explain the work inside those parts. Hardware TURBO
batches video writes; the Python model does not reproduce its batching,
synchronization, cache or PSRAM costs. Its cycle totals are useful for comparing
code paths, not for predicting hardware frame rates.

## 1. Build and boot the profiling disk

From `demos/doom`:

```sh
make profile
```

This creates a matched pair:

- `dist/Appletini-DOOM-profile.hdv` — bootable instrumented disk.
- `dist/Appletini-DOOM-profile.json` — addresses, field layout and build identity.

Keep them together. The capture tool rejects a disk whose embedded build ID
does not match the metadata. `build/profile` also contains the linked binaries
and metadata for this build. An ordinary/debug disk has the FPS/TPS display,
but does not publish these profiling counters.

Boot with 8 MB RamWorks and your selected hardware speed mode. For the target
performance measurement select **TURBO**. Press **V** until the readout matches
the machine: **60HZ for NTSC**, **50HZ for PAL**. This selects both the game
clock and measurement calibration. `make VIDEO_HZ=50 profile` starts at PAL;
the normal default is NTSC. Both rates target 35 simulation tics per second
when the machine can keep up. The current four-tic frame limit drops excess
due tics without a backlog, deliberately slowing game time at low FPS.

## 2. Capture a hardware run

Connect the Appletini UART to the host. Close any terminal or MCP server that
already owns that serial port. The frontend console runs at **921600 baud, 8N1, no flow control**.
The capture tool defaults to 921600; `--baud` can override it for older firmware.

Create an isolated environment, install the one live-capture dependency, and
find the port (macOS/Linux):

```sh
python3 -m venv build/profile-venv
build/profile-venv/bin/pip install pyserial
build/profile-venv/bin/python tools/profile_hardware.py --list-ports
```

To test the console interactively, replace the port below with your listed device:

```sh
build/profile-venv/bin/python -m serial.tools.miniterm /dev/cu.usbserial-EXAMPLE 921600 --eol CR
```

Type `:vtw status` and press Return; exit with **Ctrl-]** before starting a
capture. The macOS bundled `screen` silently ignored 921600 in a local PTY
test and retained 9600, so use this terminal for the Appletini connection.
Each firmware command needs a leading colon; it returns to navigation mode
after the command. The capture tool handles this handshake automatically.

Let the level finish loading, then keep a repeatable scene or movement pattern
running during a capture. For example, on macOS replace the device name below
with the one reported by `--list-ports`:

```sh
build/profile-venv/bin/python tools/profile_hardware.py \
  --metadata dist/Appletini-DOOM-profile.json \
  --port /dev/cu.usbserial-EXAMPLE \
  --seconds 60 --mode turbo --label 'E1M1 start, stationary, NTSC' \
  --out build/profiles/e1m1-idle-turbo.json
```

Windows can use `--port COM5` and `build/profile-venv/Scripts/python.exe`;
Linux commonly uses `/dev/ttyUSB0`.
`APPLETINI_PORT` and `APPLETINI_BAUD` are also supported. `--mode` records your
selection; it does not change the hardware's speed. Without `--metadata`, the
tool uses `build/profile/profile.json`; `--build` selects another build folder.

The tool samples every two seconds and writes both **JSON** and **CSV** as it
goes. Ctrl-C saves the samples already collected. The JSON keeps raw bytes,
clock values, timestamps, build image hashes, the console's initial and final `vtw status`,
retry counts, and excluded intervals. Keep this JSON when sharing a result.
The CSV has one row per measurement interval, with rates and phase shares.

The only console commands are `vtw status` and `vtw dump`. They read live VTW
BRAM without requesting a CPU pause, speed change, or game-memory write. The
capture uses neither the DDR write mirror nor ordinary memory peek commands.
It still adds UART/BRAM-port traffic, so compare a capture with the on-screen
FPS/TPS observed before and after it.

A saved capture can be reprocessed without pyserial or hardware:

```sh
python3 tools/profile_hardware.py --report build/profiles/e1m1-idle-turbo.json \
  --out build/profiles/e1m1-idle-turbo-reported.json
```

## 3. Read the results

The summary reports hardware elapsed time, rendered FPS, simulation TPS, and
the number/share of VBL samples in each phase. **35 TPS means normal Doom
simulation speed.** FPS and TPS are calculated from hardware clock increments,
not a configured CPU MHz value or the host's serial polling interval.
With the four-tic limit, TPS cannot exceed four times FPS; reaching 35 TPS
requires at least 8.75 rendered FPS. Dropped tics account for game time that
was deliberately skipped, not an error in PAL/NTSC measurement.

| Phase | Work being sampled |
|---|---|
| `idle` | Frame-loop idle work |
| `game_copy` | Save renderer state and load game state |
| `game_tics` | Simulation updates, including nested bank calls |
| `packet` | Build the renderer's view packet |
| `debug` | FPS/TPS readout and profile publication |
| `render_copy` | Save game state and restore renderer state |
| `render_setup` | Renderer setup |
| `walls` | BSP/wall rendering |
| `planes` | Floor and ceiling rendering |
| `things` | Things and sprites |
| `masked` | Masked surfaces |
| `present_wait` | Wait before presenting |
| `blit` | Copy the completed view to video memory |

### What a phase share means

At each existing mouse-card VBL interrupt, the profiler increments the counter
for the phase active when the IRQ is delivered. The handler checks the mouse
card's VBL cause bit before counting, so a repeated IRQ after acknowledgement
or another mouse event cannot become a second clock tick. Sampling adds no
separate timer reads. A phase receiving
60% of the samples is a strong candidate for investigation in a long run.

These are **periodic samples, not exact phase timings**. A short phase can fall
between samples. A repeating workload can also align with the 50/60 Hz clock
and bias a share. Zero samples do not establish that a phase is free. Use a
60-second capture, repeat it, and compare both a stationary scene and active
movement. Investigate small differences with the instruction profiler instead
of treating sample percentages as precise microsecond measurements.

The extra markers, interrupt increments and snapshot publication have some
cost. Compare the profiling disk's on-screen FPS/TPS with the ordinary debug
disk in the same scene to estimate that cost on your firmware. The readout and
publication are explicitly attributed to the `debug` phase.

### Consistency and wrap handling

A separate snapshot is published at a frame boundary, at most once every
60 VBLs. This leaves enough time for a UART dump even after the game becomes
faster. The host reads a 16-bit sequence before and after the block and accepts
only an unchanged, even sequence that also matches the block's own sequence.
A publication during the dump causes a retry.

Counters are 16-bit. The tool handles a wrap between samples, checks that phase
samples sum to the VBL increment, and excludes stale snapshots, implausible
counter resets, clock-calibration changes and gaps as long as a full VBL wrap
(about 18.2 minutes at 60 Hz, 21.8 minutes at 50 Hz). Boot a new game or change
the video calibration before starting a fresh capture whenever possible.
Excluded intervals and their reasons remain in the report.

### Independent clock check

For captures spanning at least 20 host seconds, the tool compares VBL-calibrated
elapsed time with the Mac's monotonic clock. A difference greater than the larger
of three seconds or 10% raises **CLOCK MISMATCH**. This allows for publication
latency at the endpoints while detecting a wrong calibration or IRQ count.

When that check fails, the displayed FPS/TPS and CSV rates use the **host window**
and are explicitly approximate. JSON retains `counter_seconds`, `counter_fps`
and `counter_tps`, the observed interrupt frequency and the clock-check result.
Phase shares are marked provisional because incorrect IRQ sampling can bias
those too. Unchanged polls remain part of elapsed host time.

The first physical capture exposed this issue: 4,583 interrupt counts in 59.7
Mac seconds, despite a 50 Hz machine. Its original 91.7-second/1.29-FPS report
was therefore unreliable; the frame-count change gives approximately 1.98 FPS
and 7.91 TPS over the host window. The second capture (build `efd1f27f`) confirms
the source-qualified IRQ fix: 2,957 VBL counts in 60.0 Mac seconds, consistent
with 50 Hz allowing for snapshot publication latency. Its 135 frames give
2.28 VBL-calibrated FPS or 2.25 FPS over the host window. Comparing both runs
on the host clock gives about a 14% gain; the clock fix and packet flag-table
optimization were delivered together, so their individual gains are unknown.
Keep the original JSON when reprocessing an older capture.

## 4. Repeatable hardware comparisons

For a useful baseline, capture at least these workloads:

1. **E1M1 start, stationary:** reboot, wait for loading, then leave input alone.
2. **A fixed view with more geometry:** reach a chosen location and face the
   same direction; record a screenshot or a description with `--label`.
3. **Active play:** follow the same short route and use the same controls.

Record firmware version, TURBO/standard mode, NTSC/PAL, map, scene, and any
changes to code or assets. Capture at least twice before and after an
optimization. Keep gameplay state comparable: monsters, doors, projectiles
and visible sprites affect both simulation and rendering work.

Compare hardware **TURBO** to hardware **standard** explicitly if useful; do
not substitute the model's historical `turbo` setting for the physical mode.
Keep the build metadata with every capture so a later profile can be traced to
its exact linked images.

### Scratch relocation comparison

The second E1M1 capture still sampled packet construction at 29.7%, followed
by walls at 19.7%. A one-frame instruction trace found 8,306 writes to the
shared path/view scratch buffer at main `$2BE0`, inside a posted video window.
This includes the 2,600-byte packet bounce copy. Local TURBO HDL batches these
writes and drains pending writes before bank-steering softswitch accesses;
the packet's three publication chunks each change RAMWRT.

Build `61904a52` relocates the existing 1,152-byte buffer to `$B380-$B7FF`.
Both arena boundaries move down by the same amount, preserving its capacity
and the full 2 KiB stack. This is a targeted reduction of unnecessary posted
writes; the emulator does not predict its hardware gain. The target firmware
is newer than the local HDL checkout, so verify the effect with another
stationary TURBO capture, keeping the `efd1f27f` report as the comparison.
Use a distinct filename such as `e1m1-idle-turbo-v3.json` to retain both runs.

The v3 capture measured 2.30 FPS against v2's 2.28, with packet share still
28.9%: no useful gain established. Build `afed1603` moves control code,
packet LC data, zero page and hardware stack from extended bank 100 to base
auxiliary bank 0. The local HDL puts the latter in BRAM and the former behind
the PSRAM cache. The model verifies memory mapping and gameplay, but cannot
predict the gain on the newer target firmware. Keep the v3 capture and use
`e1m1-idle-turbo-v4.json` for the next run.

For a fresh comparison with identical source, `CONTROL_BANK=100` selects the
extended placement; default `CONTROL_BANK=0` selects base auxiliary. Use a
different `BUILD` directory and disk filename for each. Each serial capture
must use the matching build's `profile.json`, since the bank placement changes
the linked images and build identifier.

The v4 capture confirmed 3.22 VBL-calibrated FPS (3.20 over Mac time), about
40% above v3. Packet samples per completed frame fell from roughly 126 ms to
7 ms, while game tics and copies stayed nearly constant. Compare absolute
sampled cost per frame as well as phase percentages: a successful optimization
raises other phases' percentage without making them slower.

For these 50 Hz captures, `sampled_ms_per_frame = samples * 20 / frames`.
This remains a periodic-sampling estimate, subject to the same aliasing caveat.
`build/profiles/baseaux-hardware-comparison.json` records the v3/v4 comparison.
Build `5ec12366` limits game copies to allocated memory and unrolls the transfer
loop. The v5 capture measures 3.32 FPS (both clocks), about 3% above v4. The
copies together receive about 66.9 sampled ms/frame, down from 76.1.
`build/profiles/copy-hardware-comparison.json` records this comparison.

### v6 wall reads

Build `d18e857a` fetches each textured wall/sky column into existing main-LC
scratch before applying its colormap. This separates the two PSRAM read streams
that previously alternated for every pixel. The model shows about 1% more CPU
work; hardware cache locality must repay that cost. The local HDL supports
this premise, but the newer target firmware's exact cache behavior is unknown.
The v6 capture measures 3.41 VBL-calibrated FPS (3.38 over Mac time), up 2.9%
and 2.0% respectively from v5. Wall samples per frame fall from 86.8 to
79.0 ms. `build/profiles/wall-hardware-comparison.json` preserves the comparison.

Boot `dist/Appletini-DOOM-profile-v6.hdv`, select 50 Hz with **V**, and repeat
the stationary E1M1 view in TURBO. Close the serial terminal before capture:

```sh
build/profile-venv/bin/python tools/profile_hardware.py \
  --metadata dist/Appletini-DOOM-profile-v6.json \
  --port /dev/cu.usbserial-01F164161 --baud 921600 \
  --seconds 60 --mode turbo --label "E1M1 stationary v6" \
  --out build/profiles/e1m1-idle-turbo-v6.json
```

Keep the v5 image and report for comparison. Check total FPS and wall samples
per completed frame; a changed share alone does not establish a speedup.

### v7 static-object updates

Build `bbc57588` moves the hot static-object loop's instructions to main RAM,
retaining actor bank 97 for its helpers, zero page and stack. It also inlines
four small pointer refreshes. The model observes 56,696 fewer actor-LC reads
and 3,988 fewer actor-stack accesses per stationary frame.
`build/profiles/static-v7-comparison.json` records the access counts.
The v7 capture measures 3.71 VBL-calibrated FPS (3.67 over Mac time), up 8.7%
and 8.4% respectively from v6. Game tics fall from 54.9 to 29.2 sampled
ms/frame. `build/profiles/static-hardware-comparison.json` records the result.

Boot `dist/Appletini-DOOM-profile-v7.hdv`, select **50 Hz**, and use the same
stationary E1M1 view in **TURBO**, with the serial terminal closed:

```sh
build/profile-venv/bin/python tools/profile_hardware.py \
  --metadata dist/Appletini-DOOM-profile-v7.json \
  --port /dev/cu.usbserial-01F164161 --baud 921600 \
  --seconds 60 --mode turbo --label "E1M1 stationary v7" \
  --out build/profiles/e1m1-idle-turbo-v7.json
```

Keep the v6 image and capture as the baseline. Compare total FPS and the
absolute sampled `game_tics` cost per frame.

### Hardware comparison: v8 plane reads

Build `7aafbe11` separates flat-texel and colormap reads for floor/ceiling spans,
using the existing scratch buffer. Its instruction cost rises about 1.9%
overall, so reduced PSRAM stalls must repay that cost. The hardware capture
measured 3.73 FPS versus v7's 3.71 FPS: no useful improvement established.

Boot `dist/Appletini-DOOM-profile-v8.hdv`, select **50 Hz**, and repeat the same
stationary E1M1 view in **TURBO**, with the serial terminal closed:

```sh
build/profile-venv/bin/python tools/profile_hardware.py \
  --metadata dist/Appletini-DOOM-profile-v8.json \
  --port /dev/cu.usbserial-01F164161 --baud 921600 \
  --seconds 60 --mode turbo --label "E1M1 stationary v8" \
  --out build/profiles/e1m1-idle-turbo-v8.json
```

Compare total FPS and absolute plane samples per completed frame.

### v9: PAL game clock trial, rejected on hardware

`dist/Appletini-DOOM-profile-v9-pal.hdv` starts at **50HZ**. Its matching
metadata is `dist/Appletini-DOOM-profile-v9-pal.json`. This version changed
the V key to select the game scheduler as well as the readout. It used 7/10 on
PAL and 7/12 on NTSC, a 16-bit elapsed clock, and up to 16 tics per rendered
frame, replacing the previous four-tic limit and 12-VBL elapsed clamp.

Hardware testing rejected this catch-up policy: the user reported much worse
controls and lower rendered FPS. Keep v9 as a historical timing trial. Its
larger game-tic batches make its phase shares a different workload from the
four-tic builds.

```sh
build/profile-venv/bin/python tools/profile_hardware.py \
  --metadata dist/Appletini-DOOM-profile-v9-pal.json \
  --port /dev/cu.usbserial-01F164161 --baud 921600 \
  --seconds 60 --mode turbo --label "E1M1 stationary v9 PAL clock" \
  --out build/profiles/e1m1-idle-turbo-v9-pal.json
```

### v10: PAL clock with four tics per frame

Boot **`dist/Appletini-DOOM-profile-v10-pal.hdv`**, using its matching
**`dist/Appletini-DOOM-profile-v10-pal.json`** for the capture. It starts at
**50HZ** (build `ade36695`), retains the corrected PAL/NTSC scheduler and
16-bit elapsed VBL clock, and restores a maximum of **four tics per rendered
frame**. Excess due
tics are counted and dropped; no backlog accumulates for later frames.
This intentionally slows simulation when rendering cannot support 35 TPS.

The aim is to reduce game work between input polls and rendered frames after
v9's poor hardware control feel. v10 hardware performance has not yet been
measured. Check movement, turning and firing as well as stationary FPS/TPS;
record the same scene and firmware when comparing captures.
Ten candidate clock tests and the stand-in clock test pass. The assembled
loader completes six model frames with 21 tics and movement without a crash;
this is a functional check, not hardware validation.

```sh
build/profile-venv/bin/python tools/profile_hardware.py \
  --metadata dist/Appletini-DOOM-profile-v10-pal.json \
  --port /dev/cu.usbserial-01F164161 --baud 921600 \
  --seconds 60 --mode turbo --label "E1M1 stationary v10 PAL four-tic limit" \
  --out build/profiles/e1m1-idle-turbo-v10-pal.json
```

### v11: optional ARM copy/fill service

Use **`dist/Appletini-DOOM-profile-v11-amem-pal.hdv`** and matching
**`dist/Appletini-DOOM-profile-v11-amem-pal.json`**. This retains the PAL default
and four-tic cap (build `ac9e0e63`). At startup it probes Appletini SmartPort selector `$80` and
uses the new API for GAME/RENDER phase copies and the internal view-buffer
clear. On stock F1.1.1 it uses CPU loops; the visible SHR blit is unchanged.

The original F1.1.2 API prototype is on `appletini-one` branch `codex/memory-copy-fill-api`
(commit `86b9922`).
Use F1.1.4 or later for the hardware test, including its rebuilt FPGA image.
F1.1.3 fixed a timer-conversion bug, but the same startup crash `$67` persisted.
The FPGA could discard DMA completion during unrelated reads or idle cycles,
before the ARM service saw it. F1.1.4 keeps completion until the next command;
a regression reproduces the old failure through the real AXI wrapper. The
request format is unchanged. On 2026-09-25, the user confirmed that the same
Doom v11 disk starts and runs with F1.1.4, without the `$67` crash. The saved
v11/v12 captures below establish throughput and the lack of a measured gain
from batching; they do not isolate the API's gain over CPU copies.
See the sibling repository's `README_MEMORY_API.md` for the FPGA and firmware
build steps; the old F1.1.1 bitstream lacks this fix.
The v12 work below verifies F1.1.4 source at `6335a98`; the older
prototype alone was insufficient to establish the target's behavior.

```sh
build/profile-venv/bin/python tools/profile_hardware.py \
  --metadata dist/Appletini-DOOM-profile-v11-amem-pal.json \
  --port /dev/cu.usbserial-01F164161 --baud 921600 \
  --seconds 60 --mode turbo --label "E1M1 stationary v11 AMEM PAL" \
  --out build/profiles/e1m1-idle-turbo-v11-amem-pal.json
```

The saved F1.1.4 run records **4.03 FPS / 16.13 TPS** (242 frames / 968 tics
over 60.005 host seconds), with the API enabled and status `$00` at both ends.
This is 7.6% above v8's **host-window** 3.75 FPS, not a controlled API-only gain.
See [the recorded result](STATUS.md#v11-hardware-result-f114). For the next
control, run the v10 command above on the **same F1.1.4 firmware**, scene and
TURBO settings, retaining the firmware version in the label. v10 uses CPU
copies; comparing it with v11 includes the latter's helper overhead.

Run the **same v11 disk** on stock and new firmware, using the same scene and
TURBO settings. The report reads the resident probe state at both ends and
prints `Memory API: enabled; last status=$00` for the working service.
Stock firmware reports CPU fallback, commonly status `$21`; `$FF` means no
matching accelerated slot transport. Code `$60` disables the API safely before
a transfer. Other execution errors stop the game rather than re-copy partially
changed memory. Doom's own polling timeout is `$6F`.

Use **host-window FPS/TPS** for this comparison. CPU holds can merge VBL IRQs,
so the on-screen VBL readout and counter-derived rates can overstate speed.
The capture tool always uses host elapsed time for API-capable builds, even
when clock disagreement is under 10%. Phase samples underrepresent held time:
do not interpret reduced copy percentages as a measured transfer speedup.
ARM STATUS also exposes per-command microseconds for dedicated benchmarks.

Check movement, turning, firing and a map change after the stationary run.
Then compare stock-firmware v11 with v10 to quantify helper reload overhead.
The model tests validate memory, transport and fallbacks; they do not model
ARM/DMA throughput and cannot predict the hardware FPS gain.

### v12: ordered phase-copy batches

Boot **`dist/Appletini-DOOM-profile-v12-amem-batch-pal.hdv`**, build `e2676d7e`,
on F1.1.4 and use its matching metadata. It retains PAL 50 Hz and the four-tic
cap, grouping six phase copies into two ordered requests. FILL remains a third
request after renderer zero-page recovery. The probe requires capacity for
four descriptors; unsupported firmware continues to use CPU copies.

```sh
build/profile-venv/bin/python tools/profile_hardware.py \
  --metadata dist/Appletini-DOOM-profile-v12-amem-batch-pal.json \
  --port /dev/cu.usbserial-01F164161 --baud 921600 \
  --seconds 60 --mode turbo --label "E1M1 stationary v12 batch F1.1.4" \
  --out build/profiles/e1m1-idle-turbo-v12-amem-batch-pal.json
```

Compare with v11 on the **same F1.1.4 firmware**, stationary view and TURBO
settings. The saved v11 reference is 4.03 FPS / 16.13 TPS; repeat both runs if
the scene or setup differs. Keep using host-window FPS/TPS: batching reduces
request overhead but lengthens individual holds, which can merge VBL IRQs.
Do not infer a speedup from lower copy sample percentages or model cycles.
Also check movement, turning, firing and a map change.

The first saved v12 capture records **242 frames / 968 tics in 60.007 host
seconds**, matching v11's counts and **4.03 FPS / 16.13 TPS**. API status stays
enabled/`$00`. No throughput gain is established by batching. Combined copy
sample share falls from 18.05% to 16.80%, but this is not a transfer-speed
measurement. See [the recorded comparison](STATUS.md#v12-hardware-result-no-measured-batching-gain).
To resolve smaller differences, alternate 180–300-second captures of both
builds with the same setup; snapshot publication makes short windows noisy.

## 5. Instruction and cycle profiling in the Python model

The model profiler counts executed instructions with the active physical
bank, language-card half and execution context. This prevents auxiliary code
at `$D000` from being attributed to an unrelated main-language-card routine
at the same CPU address.

Build the ordinary banked game, then run:

```sh
make
python3 tools/profile_doom.py --build build --data build/data --fast \
  --speed 33 --warmup 2 --frames 10 \
  --json build/profiles/e1m1-model.json
```

`--warmup` and `--frames` count **completed rendered frames**. The default clock
is 33 MHz. `--fast` skips the ProDOS file-loading path; normal game
initialization still runs. Omit it when investigating boot/loader behavior.
`--map 1` through `--map 9` select a map. `--do 'VBL:hold W'` and other
`run_doom.py` input events can define a repeated model workload; see
`python3 tools/profile_doom.py --help` for options.

The JSON report contains:

- Per-frame and per-phase instruction cycles, separately from synthetic I/O
  surcharges and skipped idle time.
- Physical-bank-aware PC, procedure/assembly-label and module attribution.
  Procedure and module rows are exclusive execution totals, not inclusive
  call-stack timings; assembly code uses its nearest named label.
- Bank-gateway callers/targets and call counts.
- Far-memory read/write/copy operations, bytes, and bank selections.
- Build image hashes to identify the measured binaries.

Use these reports to identify expensive routines, excessive gateway calls,
large copies and repeated far-memory accesses. Change one cause, repeat the
same model workload, then confirm the gain with a hardware capture. The
model's synthetic `--speed turbo` option does **not** model hardware TURBO's
real batched video writes or synchronization, and the tool does not convert
model totals into a claimed hardware FPS figure.
