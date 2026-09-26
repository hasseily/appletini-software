# Doom port status

Updated 2026-09-25. **The complete banked game links, boots and runs on the
physical Appletini.** The former contiguous-RAM link failure is resolved by
the default `BANKED=1` build. Hardware E1M1 profiling is underway in TURBO;
the broader gameplay tests currently run in the memory-map emulator.

## Memory layout

Game code is loaded once into seven auxiliary language-card banks, each
linked at `$D000-$FFF9`, with vectors at `$FFFA-$FFFF`:

| Bank | Main code group |
| --- | --- |
| 96 | Collision and map traversal |
| 97 | Actors |
| 98 | AI and sight |
| 99 | Specials and movers |
| 0 (base auxiliary LC) | Game control, packet construction, damage and pickups |
| 101 | Level setup and spawning |
| 102 | Player and weapons |

During game execution, RAMRD/RAMWRT are off: ordinary data and pointers use
main RAM. ALTZP selects the code bank's zero page, hardware stack and language
card. Main-memory gateways support nested calls and callbacks, preserve
registers and 54 logical zero-page bytes, and restore suspended hardware
stacks. IRQ handling borrows the main context. NMI sources must remain disabled.

The renderer also needs main RAM. `space.s` saves and restores the two phases'
contents; all due tics and packet construction share one game phase per
rendered frame. Only mutable regions are saved each time, including renderer
self-modified code. Read-only regions come from their initial backing images;
the view buffer is cleared and the inactive C-stack contents are discarded.

| Storage | Owner |
| --- | --- |
| Main RAM during game phase | Shared helpers, mutable game/level data and actors |
| Main `$B380-$B7FF` during game phase | 1,152-byte shared path/view/debug scratch, outside posted video windows |
| Main `$B800-$BFFF` during game phase | Full 2,048-byte C software stack |
| Bank 125 | Game phase backing storage |
| Bank 122 | Renderer phase backing storage |
| Bank 124, `$0200` | 2,600-byte packet: header and up to 128 things |
| Bank 127, from `$0200` | Game math tables and far game workspace |
| Bank 1, `$0200-$1FFF` | Far blockmap thing-chain heads |
| Bank 1, from `$6000` | Immutable object metadata (`GAME.INFO`, 3,060 bytes) |
| Bank 126 | Specials journal and initial sector snapshots |
| Banks 2–95 | Converted Freedoom episode 1 data |
| Bank 0 lower RAM | SHR screen, palette and profiling mailbox |
| Bank 0 ZP/stack/LC | Control-bank execution context, code and render packet |

Snapshot rollover skips banks 125, 124 and 122. It can use lower RAM in code
banks after their LC images have been installed, but stops above the converted
data and renderer-cache bank. Code and lower data RAM are independent storage.

Additional space comes from smaller correctness-preserving level caches,
selected code/state-table duplication, far blocklink heads and object metadata,
and reuse of path-intercept scratch during packet preparation. The packet is
built in spare control-bank LC RAM and published to bank 124 through main
scratch. Statics and actors retain near pointers. The existing **160 actors**
at 64 bytes each and **128 visible packet things** are retained; no actor-limit
reduction or thinker reordering was used to make the new layout fit.

`tools/build_banked.py`, `tools/bank_game.py`, and `tools/check_link.py` generate
and verify the final link, code images, preloads, stack and conservative level
budget. With the debug readout, the integrated link leaves a 31,780-byte main
arena and a 1,176-byte margin over its conservative level-plus-160-actor requirement.
The profiling build has 31,574 arena bytes and a 970-byte conservative margin.
The largest occupied LC bank is the control bank: 11,963 of 12,282 non-vector
bytes, including packet storage. Consult generated `link-report.json` after
changes; these are layout checks, not a guarantee that every larger WAD fits.

## Implemented gameplay and rendering

The 65C02 renderer draws the BSP, textured walls/floors/ceilings, sky, masked
middles, sprites, spectres, weapon layers, animation and lighting. Its separate
reference tests compare complete frames with `tools/refrender.py`.

The game implements player movement and weapons, collision/blockmap traversal,
actor states, sight, monster AI, damage, pickups, line/sector specials, movers,
lights, switches, buttons and scrolling walls. Level flow includes exits,
secret exits, intermission/finale states, restart and restoration of changed
map data. The C implementation remains the gameplay reference.

Still unfinished:

- HUD/status bar, title/menu UI, and intermission/finale presentation. Their
  assets and game state exist; screens and menu interaction do not. Esc only
  sets an input flag.
- Audible effects and music. `S_StartSound` records effect IDs in the existing
  eight-entry event history and increments a counter; no Phasor playback
  backend consumes it yet.
- Prolonged physical play across all nine maps and broader TURBO profiling.

## Verification

The new tests complement the existing host C, flat 65C02, renderer, converter,
platform and disk suites:

| Suite | Checked behavior |
| --- | --- |
| `test_game_banks.py` | Actual memory mapping; nested A→B→A and main-kernel calls; 54-byte context; IRQ injection at instruction boundaries |
| `test_game_banked.py` | All nine converted maps at Nightmare with 160 actor slots and an intact stack guard; E1M1/E1M8 differential movement, weapons, monsters, RNG, inventory and packets |
| `test_game_far_data.py` | Existing gameplay-equivalence sessions with far heads/metadata and smaller caches; flat-harness fetch-alias regression |
| `test_game_snapshots_banked.py` | Snapshot rollover, reserved-bank preservation, sector roundtrip and allocation-floor failure |
| `test_banked_link.py` | Bank capacities, image/preload consistency, layout budgets and partition regressions |
| `test_doom_banked_platform.py` | Assembled ProDOS loader through FakeProDOS; exact LC/table/metadata installation; real kernel copies and phase changes; four nonblank, changing SHR frames driven by keyboard/mouse input |

Observed stack writes in the banked gameplay samples used 64 bytes of the
2 KiB software stack and at most 41 bytes of any hardware stack. These are
sample maxima, not proofs for every gameplay path. The full reservations remain.

The flat harness still uses synthetic instruction windows. The legacy
single-bank layout remains too small for the complete game; current capacity
tests check the real banked layout. The banked tests use the same mapping for
instruction and data fetches. The standalone banked game harness
traps far transport; the complete platform test also executes the real kernel
transport and loader.

## Performance status

The first serial capture contains 118 completed frames in about 59.7 host
seconds: approximately **1.98 FPS**. The earlier visual estimate was about
3 FPS. That capture exposed an IRQ-counting defect: 4,583 purported VBLs on
a 50 Hz machine inflated elapsed time to 91.7 seconds and understated rates.
Both IRQ routes now qualify the mouse-card VBL cause before advancing the
clock; the host report also checks its elapsed time against the Mac clock.
The second capture (build `efd1f27f`) has 2,957 VBL counts in 60.0 host seconds,
consistent with 50 Hz. It reports 135 frames and 540 tics: **2.28 FPS / 9.13 TPS**
using VBL time, or **2.25 FPS / 9.00 TPS** over the host window. The latter is
about 14% faster than the first capture on the same timing basis. The IRQ fix
and first packet optimization were combined, so this does not isolate their
individual gains. Packet construction still receives 29.7% of samples, walls
19.7%, game tics 13.6%, and the two phase copies together 17.7%.

The first packet optimization replaces two per-static-object metadata fetches
with a generated 90-byte flag table in code bank 100. Across the same three
steady model frames, metadata reads fell from 579 to zero, packet cycles
from 3,661,545 to 1,255,769 (**65.7% less**), and total CPU cycles from
31,112,724 to 28,707,896 (**7.7% less**). It uses 84 additional code-bank bytes
and no additional main RAM. These are model measurements, not hardware gains.

Profiling build `61904a52` moves the shared path/view/debug scratch from main HGR
addresses to `$B380-$B7FF`. An E1M1 trace counted 8,306 scratch writes per frame,
91% of packet construction's writes into main posted video windows. The local
TURBO implementation batches these writes, then drains the queue at bank
steering operations. Moving scratch avoids that traffic without changing the
level arena capacity or stack reservation. These write counts describe traffic;
PSRAM/cache costs and periodic sampling also affect the phase shares.

The third hardware capture tested that relocation: **2.30 FPS / 9.20 TPS**
over 60.0 VBL-calibrated seconds (138 frames), with packet construction still
at 28.9%. The less-than-1% FPS difference from the second run does not establish
a useful gain. TURBO was already handling that posted traffic efficiently
enough that removing it did not improve this workload meaningfully.

Build `afed1603` moves the control/packet LC bank from extended bank 100 to base
auxiliary bank 0, preserving the code and algorithm. In the local HDL, base
auxiliary code/ZP/stack use BRAM while extended-bank accesses compete through
a shared eight-byte PSRAM cache. This targets the memory behavior missing
from instruction-cycle profiling. Bank 100 remains its boot staging area;
an explicit loader table installs the image after ProDOS finishes without
overwriting the staged renderer or display. A separate `CONTROL_BANK=100`
build remains available for comparison. The target firmware is newer than the
local checkout; its exact cache geometry remains unverified.

The fourth hardware capture confirms a substantial benefit: **3.22 FPS /
12.87 TPS**, 192 frames in 59.68 VBL-calibrated seconds, or 3.20 FPS over the
60.0-second Mac window. Both clocks show about **40% more FPS** than v3.
Dividing periodic samples by frame count gives the following coarse costs:

| Phase | v3 sampled ms/frame | v4 sampled ms/frame |
| --- | ---: | ---: |
| Packet | 125.8 | 7.0 |
| Walls | 89.0 | 85.3 |
| Game tics | 59.3 | 58.9 |
| Both phase copies | 75.8 | 76.1 |
| Planes | 35.8 | 35.6 |

These are sampled estimates, not exact timers. Other work is broadly steady;
its larger percentage reflects the packet time removed. The result strongly
supports extended-bank memory access as the former packet bottleneck.

Build `5ec12366` saves/restores only through the allocator's
page-rounded live endpoint, instead of copying unused space up to `$B800`.
E1M1 leaves roughly 16 KiB unused, avoiding that traffic in each direction.
The first load remains complete, and new allocations extend the next saved
range automatically. An eight-byte unrolled loop also reduces per-byte CPU
overhead. The model shows 33.2% less copy-phase instruction work and 8.2% less
total CPU work across three steady E1M1 frames. The v5 hardware capture measures
**3.32 FPS / 13.28 TPS**, 199 frames in 59.96 VBL-calibrated seconds (3.32 FPS
over the 60.00-second Mac window). This is a modest 3.2% VBL-calibrated gain
over v4; the two copies together fall from about 76.1 to 66.9 sampled ms/frame.
The instruction model overstates the improvement on this workload. Tests cover exact
page boundaries, growth/shrinkage, skipped-tail canaries and stack preservation.

Build `d18e857a` changes textured wall/sky column drawing to two passes: fetch
the column's raw texels into the existing main-LC `kbuf`, then apply its
colormap and write the pixels. Previously every pixel alternated texture and
colormap reads through the shared PSRAM cache. Main BRAM writes do not evict
that cache in the local HDL, so the buffer stores preserve texture locality.
No additional RAM is allocated; code grows by nine bytes. The model executes
about 1.0% more CPU cycles overall. The v6 hardware capture measures **3.41 FPS /
13.66 TPS**, 204 frames in 59.74 VBL-calibrated seconds (3.38 FPS over the
60.33-second Mac window). This is 2.9% faster by VBL time and 2.0% by Mac time
than v5. Walls fall from 86.8 to 79.0 sampled ms/frame, consistent with a
modest locality benefit; periodic sampling is not an exact timer.
Thirteen complete reference frames match
exactly, including masked walls, sprites and different lighting. Direct queue
tests cover bounds, wraparound, bank changes, overlapping pieces and VBL IRQs
during both passes; all five profiling runtime tests also pass.

Build `bbc57588` targets the next gameplay bottleneck. The static-object update
loop moves 275 code bytes from actor LC bank 97 into main game RAM. A three-byte
LC jump preserves its existing bank context, local helper calls and public
gateways. Four cursor-refresh calls are inlined. On one stationary E1M1 model
frame (four tics after two warmup frames), actor-LC byte reads fall from 70,906
to 14,210 and actor-stack accesses from 5,988 to 2,000. These include instruction
fetches; they are access counts, not hardware timings. Gameplay CPU cycles fall
from 301,547 to 289,606. The profiling build retains 970 bytes of conservative
arena margin and all 160 actor slots. All nine maps load at Nightmare; two-map
gameplay differential tests, complete loader/frame-handoff tests, all five
profiling runtime tests and 22 link/partition tests pass. The v7 hardware capture
measures **3.71 FPS / 14.85 TPS**, 220 frames in 59.26 VBL-calibrated seconds
(3.67 FPS over the 60.00-second Mac window). This is an 8.7% gain by VBL time
and 8.4% by Mac time. Game tics fall from 54.9 to 29.2 sampled ms/frame; walls
remain about 80 ms/frame. The larger wall and copy shares mainly reflect the
gameplay time removed, not equivalent increases in their absolute costs.

Build `7aafbe11` applies the two-pass read ordering to floor/ceiling spans:
gather raw flat texels into existing `kbuf`, then shade and write with the
84-byte stride. The loop grows 21 bytes; moving the immutable 28-byte
`span_setrow` helper to text RAM leaves nine bytes free in LC1 and 20 in RTEXT.
No RAM buffer is added. Thirteen full-frame reference comparisons, 16 direct
span executions (including wrapping, boundary checks and IRQs in both passes),
and five profiling runtime tests pass. The instruction model adds 1.9% total
CPU work. The v8 hardware capture measured **3.73 FPS / 14.92 TPS**: no useful
gain over v7 established.

Build `0355b9eb`, `dist/Appletini-DOOM-profile-v9-pal.hdv`, introduced the PAL
game-clock correction. It starts at 50 Hz; V selects 50/60 Hz for both gameplay
and measurement. Its scheduler targeted 35 TPS, permitted 16 catch-up tics per
frame, and accounted for
elapsed time with an atomic 16-bit VBL snapshot. Nine clock regression tests,
the legacy clock test, six readout tests, link checks, disk-file hash checks
and a loader/gameplay smoke run passed. The smoke run rendered six frames
and executed 66 tics with movement. Its emulator uses a 60 Hz clock and does
not validate hardware PAL or TURBO performance. Subsequent hardware testing
rejected v9: the user reported much worse controls and lower rendered FPS
with the longer catch-up batches.

The v10 candidate, build `ade36695`, is
`dist/Appletini-DOOM-profile-v10-pal.hdv` with matching
`dist/Appletini-DOOM-profile-v10-pal.json`. It restores at most **four game
tics per rendered frame**. Excess due tics are counted and dropped without a
backlog. Game time therefore deliberately slows at low FPS. The 50 Hz default,
16-bit elapsed VBL clock, accurate readout and exact dropped-tic accounting
remain; the scheduler reaches 35 TPS when the machine is fast enough.
Ten candidate clock tests and the stand-in clock test pass. An assembled-loader
33 MHz model run with W held boots and completes six frames with 21 tics
(`1, 4, 4, 4, 4, 4`) without a crash. One frame crosses line 0, an existing
model presentation-timing artifact; the run does not establish hardware
performance or presentation quality.
v10 hardware performance and control feel still need testing.

### v11: optional ARM copy/fill API

Build `ac9e0e63` is `dist/Appletini-DOOM-profile-v11-amem-pal.hdv`, with matching
`.json` metadata. Image size is 4,472,832 bytes; SHA-256:
`a50a75cb7153ecdb1cc9bfe4950d2b6034966ddc34e029982c0ddc148bba2c61`.

It retains PAL 50 Hz and the four-tic limit. At startup, the resident helper
probes the Appletini SmartPort memory API. Supported firmware executes phase
copies and the internal view-buffer clear on ARM. Stock firmware uses the
existing CPU loops. Pre-execution `$60` can also disable the API safely;
other execution failures stop without retrying partially changed memory.

Three 256-byte overlays reuse the existing LC `kbuf`. Their immutable source
is in renderer bank 122 at `$B800–$BAFF`, outside the saved renderer extent.
The existing main arena stays at 31,551 bytes. Resident free space is 29 bytes
in LC1, 17 in LCHI, 82 in LC2. The visible SHR blit still uses the existing
display path; all new MAIN writes explicitly opt into PRIVATE working memory.

The original firmware implementation was pushed to `appletini-one` on branch
`codex/memory-copy-fill-api`: API commit `d87c8c4`, followed by the F1.1.2
version bump in `86b9922`, based on `b9fcdef` (F1.1.1 code plus subsequent
shipping documentation). `README_MEMORY_API.md` specifies
the wire format, safety/visibility contract, examples and PC build commands.
No RTL change or firmware binary was produced at that stage. The broad flush
work was deferred. The hardware result below uses the user's newer F1.1.4;
the initial review still had F1.1.2 source. The v12 work below subsequently
verified the updated F1.1.4 checkout.

Checks passed: eight assembled API tests, 24 link guards, ten clock tests,
five profiling runtime tests, and 21 serial/profiling tests. The firmware's
actual C parser passes eight native test groups; its hardware backend passes
576 fake-MMIO alignment/direction cases, plus edge/failure checks. Native
syntax checks include SmartPort dispatch and the DMA helper. Both firmware
suites run with ASan/UBSan; these do not replace a Vitis build or FPGA tests.

The release's actual assembled loader boots through the model's ProDOS shim
with unsupported and supported SmartPort firmware. Both complete four moving
frames, producing identical game packets and image hashes, with tics
`1, 5, 9, 13`. The API path makes 37 requests and finishes at status `$00`;
the fallback probes once and reports `$21`. Overlay bytes remain intact and
all five program-file hashes inside the HDV match the release metadata.
Reports are in `build/profile-v11-amem-pal/acceptance-*.json` and
`release-verification.json`. These runs prove function, not hardware speed.

CPU holds can merge VBL IRQs, so serial captures of API-capable builds use
host elapsed time for FPS/TPS and report resident API availability/status.
VBL phase shares may undercount transfer time; the on-screen rates are not
authoritative during long holds. Use the same v11 disk on both firmwares for
the A/B measurement, then compare v10 versus stock-firmware v11 for reload cost.

### v11 hardware result: F1.1.4

The 2026-09-25 stationary E1M1 capture on user-reported firmware **F1.1.4**
is `build/profiles/e1m1-idle-turbo-v11-amem-pal.json` (and `.csv`). Its metadata
matches build `ac9e0e63`. TURBO is confirmed in both firmware status snapshots;
the memory API is enabled with last status `$00` at both ends. All 30 capture
intervals are valid. Over **60.005 host seconds**, it records **242 frames /
968 tics**, or **4.03 FPS / 16.13 TPS**.

Use host time for both sides of the historical comparison:

| Capture | Host FPS | Host TPS | Host ms/frame |
| --- | ---: | ---: | ---: |
| v8, earlier firmware | 3.75 | 15.00 | 266.7 |
| v11, F1.1.4 | 4.03 | 16.13 | 248.0 |

That is **7.6% more throughput**, saving about **18.7 ms/frame**. It is not an
isolated measurement of the copy API: firmware and the PAL scheduler changed
since v8, although both captures average exactly four tics per frame. There
is no saved v10 hardware capture. Run v10 on the same F1.1.4
and scene to compare the CPU-copy and API builds while holding firmware fixed.
This includes v11's helper overhead; an explicit fallback switch in v11 would
allow a closer API/fallback comparison on the same firmware.

Walls remain the largest sampled phase (**32.75%**), followed by planes
(13.37%) and game tics (13.14%). The two copy phases total **18.05%**, versus
26.99% in v8. These are sample shares, not measured durations or an API speedup.
Wall samples per completed frame are nearly unchanged (4.02 in v8, 3.97 in
v11), so the larger wall percentage does not demonstrate slower wall drawing.
The visible SHR blit remains on the existing TURBO display path (9.76% of
samples), which batches video writes.

The VBL counter covers 58.62 calibrated seconds versus 60.005 host seconds
(48.85 observed IRQs/second). CPU holds and snapshot publication timing can
affect this difference; it is not a measurement of total transfer hold time.
Keep using host FPS/TPS and obtain command timings before attributing the
remaining copy cost. The **four-tic cap is saturated** (968 / 242 = 4): current
simulation speed is about 46% of 35 TPS, and 35 TPS with this cap requires
8.75 FPS. Movement, combat and map-change validation remain to be reported.

The batching experiment implemented in v12 below follows from this capture.
v11 makes six COPY calls and one FILL call per normal frame,
reloading a 256-byte helper for each. The documented API supports ordered
descriptor lists: four copies on entry to GAME and two on entry to RENDER
could become two requests, leaving the FILL separate until the renderer's
zero page has been recovered from VIEWBUF. That would reduce seven requests
to three. Validate list support on F1.1.4 and measure the result; neither the
savings nor the older prototype's hold costs are established by this capture.

### v12: batched phase copies on F1.1.4

Build `e2676d7e` is `dist/Appletini-DOOM-profile-v12-amem-batch-pal.hdv`, with
matching `.json` metadata. Image size is 4,473,344 bytes; SHA-256:
`5497e2dce588a09c1047ce91dc0fa77e77d6c760e7684c1a6e89af1d5081f4f2`.
It retains the PAL default and four-tic cap. The
reviewed firmware is `appletini-one` F1.1.4, commit `6335a98`: descriptor lists
are validated before writes and execute in order under one CPU hold.

Entering GAME batches three renderer saves followed by the GAME load.
Returning batches the live GAME save followed by the renderer restore. The
view-buffer FILL stays separate until the renderer zero page has been recovered
from that buffer. The first GAME load still covers the full initial image;
later transfers use the page-rounded allocator endpoint.

Per normal frame, CONTROL requests and helper reloads fall from **seven to
three**. FIFO submission falls from 252 to 172 bytes, and four 256-byte helper
reloads disappear. The six COPY descriptors, FILL and transferred data volume
are unchanged. These are operation counts, not a predicted hardware speedup.

The startup probe now requires capacity for at least four descriptors. Firmware
without that capability uses CPU copies. A pre-execution `$60` disables the API
and runs the entire handoff through the existing CPU path; all other execution
errors stop without replaying a potentially partial batch.

Two additional immutable helper pages occupy bank 122 `$BB00–$BCFF`; all five
overlays reuse the same resident 256-byte `kbuf`. The main arena remains
31,551 bytes and the C stack remains 2 KiB. Resident free space is 16 bytes in
LC1, 3 in LCHI and 82 in LC2. Both profiling PAL and ordinary NTSC builds link.

Checks passed: 13 assembled memory-API tests, 24 link guards, three phase-copy
regressions, ten clock tests and five profiling runtime tests. They cover full
handoff contents, the 4/2/1 descriptor sequence, initial and changing live
extents, zero-page/register/IRQ preservation, capability limits, safe fallback
from either handoff and no retry after a partially executed batch.

The exact release boots through the assembled loader with supported and
unsupported SmartPort firmware. Both complete four moving frames with
identical packets and image hashes, also matching v11's recorded frames.
The API run makes 17 requests including the probe and initialization, versus
37 in v11, and finishes at status `$00`. All five immutable overlay pages
remain intact. The five program-file hashes extracted from the HDV match its
metadata. Reports and the reproducible verification script are in
`build/profile-v12-amem-batch-pal/acceptance-*.json`, `release-verification.json`
and `verify_release.py`. These checks validate function, not hardware timing.

### v12 hardware result: no measured batching gain

The 2026-09-25 stationary capture is
`build/profiles/e1m1-idle-turbo-v12-amem-batch-pal.json` (and `.csv`). Its
metadata matches build `e2676d7e`; all 30 intervals are valid. Both endpoint
snapshots confirm TURBO and an enabled memory API with status `$00`.

| F1.1.4 capture | Host seconds | Frames / tics | Host FPS / TPS |
| --- | ---: | ---: | ---: |
| v11, individual copies | 60.005 | 242 / 968 | 4.03 / 16.13 |
| v12, batched copies | 60.007 | 242 / 968 | 4.03 / 16.13 |

The identical counts establish **no measurable throughput improvement** in
this run. Both average about 248 ms/frame and remain at four tics/frame.
The result does not prove that batching saves zero time, but removing four
requests and helper reloads has not improved the observed frame rate.

Combined copy samples fall from 529 to 490 (18.05% to 16.80%). Total samples
also fall from 2,931 to 2,917, with observed IRQ rates of 48.85 and 48.61 Hz.
Longer CPU holds can merge IRQs; periodic sampling and publication timing also
affect the counts. These changes do not measure transfer time or establish
that the copy work became faster. Walls remain the largest sampled phase
(32.60%), followed by planes (13.95%) and game tics (13.47%).

Further call-count reductions are a lower priority after this result. The
next useful investigations are wall-renderer work and actual bulk-transfer
timings. Batching leaves all copied bytes and the firmware's internal chunk
work unchanged. Measure those costs before changing the memory architecture;
the current phase samples cannot distinguish transfer execution from held
time reliably. Alternating 180–300-second v11/v12 captures can resolve smaller
changes than this single pair: snapshot publication is only about once per
five frames here, so 60-second endpoints have appreciable uncertainty.
Movement and combat remain separate workloads to validate.

### Profiling infrastructure

The opt-in
`make profile` image now samples 13 phases on the existing VBL IRQ and publishes
a versioned, coherent snapshot in base auxiliary RAM for the serial console.
`tools/profile_hardware.py` captures raw snapshots, FPS/TPS, phase sample shares,
firmware status, and JSON/CSV reports. Periodic samples can phase-lock; these
shares are coarse evidence, not high-resolution phase timings. The sampler
adds no timer peripheral reads. A VIA clock was deferred because the local
firmware's sound-card accesses trigger a CPU slowdown window.

`tools/profile_doom.py` attributes instruction/cycle costs to physical code
banks, functions and phases, and counts bank gateway edges and far transfers.
An execution-preservation test compares a profiled machine with an ordinary
runner, including all memory, registers, mappings and cycle totals. See
[profiling instructions](PROFILING.md) for a repeatable hardware/model workflow.


The hardware build now displays FPS and TPS in the bottom strip. It measures
completed frames and game tics over at least two seconds of mouse-card VBL
interrupts. **V** selects the **60HZ/50HZ** game clock and resets the
sample window; match the machine's NTSC/PAL clock. The readout uses no CPU-speed
estimate, adds 67 bytes of game BSS, and draws only seven rows per refresh.
The scheduler targets 35 TPS at either rate and permits up to four tics per
rendered frame, dropping excess due tics without a backlog. At lower frame
rates simulation deliberately slows. A PAL image can start at 50 Hz with
`VIDEO_HZ=50`.
See the README for hardware-test instructions.

A provisional profile of the first integrated build, before phase-copy and
packet optimizations, measured about **12 million model cycles per rendered
frame** in three steady E1M1 frames (four tics per frame). Approximately 55%
was rendering, 26% phase copying, 17% game/packet work and 2% presentation.
Bank gateway code accounted for roughly 63% of game time, or 11% of the frame.
These figures identify optimization targets and are not a current FPS promise.
Phase-copy and packet batching changes have since reduced a comparable idle
sample to about **10.8 M model cycles/frame**, with phase copies around
**2.38 M** (previously 3.13 M). The final integrated input-driven test measured
10.99–11.39 M model cycles/frame. A separate 33 MHz model run completed six
rendered frames over 180 model VBL intervals, including initialization, and
reported one blit crossing line 0. Presentation can therefore straddle a frame
publication in that preset. None of these is a hardware frame-rate result.

The Python harness's mode named `turbo` uses a nominal 75 MHz CPU budget and
a fixed I/O surcharge; it is not hardware TURBO emulation. A conventional
33 MHz emulator run is also separate from target TURBO. The harness does not reproduce the target's full PSRAM/cache, batching or synchronization
timing. **TURBO batches video writes**; treating each pixel write as a
synchronous 1 MHz bus transaction would give the wrong performance model.
The target firmware's actual behavior must be measured before claiming a
hardware frame rate.

## Build and next work

From `demos/doom`, run `make`, `make disk`, and `make test`. Run the integrated
model with `python3 tools/run_doom.py --build build --data build/data --speed 33 --frames 180`.
See [the README](../README.md) for dependencies and stand-in/reference builds.

Next work is to reduce measured phase/gateway/render cost, finish UI and audio,
and continue validating gameplay and performance on the user's TURBO target.
The earlier options analysis is retained in [BANKING_OPTIONS.md](BANKING_OPTIONS.md)
with an implementation update; the rejected general claim that code banking
cannot solve the fit problem no longer applies.
