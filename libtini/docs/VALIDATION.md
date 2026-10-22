# SDK and STARFALL validation

Date: 2026-10-21. Library starting point: clean `main` at
`e2a5c6ed916fcb261d3bcccca6d563840e85a183`. Checkpoints one through five now
have software implementations. Physical board acceptance remains pending. Networking and further video/3D
modules remain outside this release.

## STARFALL example

STARFALL builds as an independent `starfall.system` and 800 KiB `starfall.po`
in the normal output directory. Its manifest leaves it out of the
optional-AMEM build; records below for that build are history. The disk boots
`STARFALL.SYSTEM`; sprites and phrase data are compiled into that SYS.
The original Kenney CC0 sprite archive, license and exact hashes are vendored
under `assets/starfall/`. Normal builds convert it offline.

```powershell
python tests/test_starfall.py --cc C:/msys64/ucrt64/bin/gcc.exe
python -m unittest discover -s tests -p test_starfall_assets.py -v
python tests/scene_validate.py --cc65-home D:/Repos/cc65
python tests/audio_validate.py
python tests/starfall_native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe
python tests/starfall_native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe --phasor
```

The last two commands require the explicitly installed repo-local ROM inputs
documented in `tools/DEPENDENCIES.md`. The check runner includes host/core/art
and renderer tests normally, and ROM boots with `--rom-boot`.

- Host C checks exercise movement, collisions, ramming, four weapon levels,
  wingmen, bullet blocking, overdrive power, piercing and double points,
  every enemy behaviour and bullet style, damage, chain scoring, shields, four
  pickups and their drift, bombs, restart and the 24-second sectors of two
  levels each. Hundreds of triggered waves per level show each enemy type
  first appearing at its level with its hit points, gunships 6 and heavies
  15, and heavies never above their cap. A paired 20,000-tick run is
  deterministic and bounded; it reaches the last level, peaks at 14 enemies
  and 36 hostile shots, and sees wingmen and overdrive. It finds the first
  heavy at 50 s and no fan shot before heavies may arrive at 48 s. Eight
  unattended host runs last 62 s at least and 105 s on average.
- A host player model dodges with an eight-tick (267 ms) view delay and a
  decision every fourth tick. Over sixteen runs it lasts 162 s at least and
  198 s on average, taking 2.85 hits a minute and 6.25 in the first three
  minutes. With one level a sector and gunships and heavies at 4 and 10 hit
  points it lasted 323 s at least and 399 s on average, with 1.56 early hits;
  against thirty-second sectors before that, 596 s with 0.75. The model
  measures relative pressure, not human difficulty.
- Seven offline asset/speech tests check the original license/source hashes,
  deterministic packed cells, the hand-authored atlas against its generated
  scene images, PNG validation and the requested voice phrases.
- The library scene renderer runs on the 65C02 instruction model through 59
  draws on three areas, the last one the full screen width. After every draw
  the area equals an independent rendering of the sprite list read from
  memory, 782,688 pixels in all, and no SHR byte outside the areas changes.
  Random sprites are placed from 48 pixels before each edge to 48 past it.
  An unchanged list publishes no bytes. 653 target checks cover
  rejected areas, colours, images and configurations, a full list, an
  unknown image, the service call after every fourth band, and `forget` and
  `invalidate` after another drawer. This is instruction-level evidence of
  the output, not of timing.
- The actual linked joystick code reads model paddles timed at 54 and 154
  inside 41-69 and 136-174 through VIA timer 2 and through the T1C-H
  fallback, with CPU and device clocks equal and at four CPU cycles per
  device clock. A y paddle that never finishes returns TI_E_TIMING with y at
  255 and x still in range, and the next read recovers. The device tick
  count stays within one period of the model's enabled interrupts, counted
  from the last audio initialization.
- In the same runs `ti_stick_read` reports no stick for four reads with both
  axes open, then makes no paddle access during its wait. After
  recalibration it reads a model stick at 128 as rest (127-131) and reports
  each direction and a diagonal. An axis left unfinished after an answer
  reads as full deflection. `ti_input_held` reports a held key, a pending
  key without losing it, and a key that arrives between its two reads, which
  it queues. `ti_steps_due` gives the expected steps from a scripted clock,
  including the cap and a gap over a second. A two-voice request rounds to
  three, and its updates write only AY chip 0.
- Host checks compile the stick and step code with GCC. They check the
  engage and release thresholds, travel adaptation per side, calibration only
  from a reading within 48-207, the three-second no-stick wait and 20,000
  random step frames against reference accounting, including the 16-bit
  clock wrap.
- The paddle model strobes on any $C070-$C07F access and ignores a strobe
  while a timer runs, as the //e and its 558 do. A $C073 selector write,
  followed by a read once x has finished, still reads both axes in range in
  every mode. With the wait for running timers removed, the same check reads
  y short and fails.
- Near-row publication is covered by the 4,047-check native graphics suite in
  both profiles, including rejected ranges/budgets, striding, byte results,
  timing/wrap reporting and full AUX restoration.
- Four real ProDOS boots verify every SYS load byte, keys that move the ship
  while held and stop on release, a tap that moves it once, autofire, a
  bomb, joystick movement, centring and a joystick-button bomb,
  pause with a live clock, restart, natural gameover, retry, ProDOS return and
  interrupt removal. The development machine has no counting VIA timer 2, so
  these joystick reads use the T1C-H fallback. A restart with paddles resting
  at 165/95 calibrates to that rest without moving the ship. Deflections to
  105 and 150 then move it left and down; the earlier fixed 80/175
  thresholds ignored both. The unattended runs keep that off-centre rest:
  the stick read 165-173/97-105 and the ship never moved. The development
  machine restarts its paddle timers on every $C07x access, so these runs
  cannot show short reads after $C073 writes. Both
  Mockingboard and Phasor runs show all five enemy types and the same
  unattended outcome in both profiles: tick 2562, sector 3, score 2790.
  Before the second restart, each boot checks two sf_state offsets against
  telemetry and writes overdrive and a fourteen-kill chain; the next bomb
  reaches x8 and shows GREAT SHOT. The unattended run's repair kit shows
  EXCELLENT. Complete SSI register streams match GREAT SHOT, EXCELLENT and
  GAME OVER. Captions 0-7, the sector banner and the shield and bomb captions
  were observed; the shorter run reaches no wingman caption.
  During unattended play,
  106 to 108 sampled playfields in each profile, with each card and the
  backdrop on, equal an independent rendering of the sprite list read from
  memory.
- During play the boots read the card's AY registers after every model run.
  With the Phasor, voices 0-7 each played only the periods of their own
  song track and effects were heard on voices 8-11. With the Mockingboard,
  voices 0-1 played the lead and bass and effects were heard on voices 2-5.
  A read can fall between the two register writes of a period change; such
  reads, the new low byte with the old high byte, are accepted when rare.
  Each boot writes the first 90 seconds of the model's 8 kHz audio to
  `build/starfall/native-ui*/audio-PROFILE.wav`. The model renders the AYs;
  how the song sounds on a board is unchecked.

The final eight-second model windows measured:

| Build / audio | vtw33 simulation / drawing | turbo-f122 simulation / drawing |
| --- | --- | --- |
| CPU / Mockingboard, 6 voices | 30.50 updates/s; 30.50 frames/s | 30.54 updates/s; 30.54 frames/s |
| CPU / Phasor, 12 voices | 30.51 updates/s; 30.51 frames/s | 30.55 updates/s; 30.55 frames/s |

Every update is now drawn. These windows cover the first sector, which
holds only scouts, so they do not measure busy scenes. Before HUD values
were drawn a row at a time as opaque text, publishing only their cells, the
records were 27.84 and 29.42 frames/s with the Mockingboard and 27.84 and
29.40 with the Phasor. With the 50-event score on two voices and six
driver voices on both cards, the turbo-f122 records were 29.68 and 29.66
frames/s and the vtw33 records were the same as now. Before praise lines were limited to the x8 chain
and repair kits, the records were 27.59 and 29.55 frames/s. Before STARFALL drew its playfield with the
library sprite scene, the records were 27.46 and 29.03 frames/s for the CPU
build and 27.33 and 29.01 for the optional AMEM build. The scene takes about
8 ms less per frame, but the loop draws only when an update is due, so the
freed time was spent waiting, and frames that redrew HUD text still took
longer than one update. Before that, the records were 24.69 and 28.89 frames/s
for the CPU build and 24.68 and 28.87 for the optional AMEM build, before
`ti_gfx_present_rows` wrote every row in one assembly call with 16-bit
checks. The turbo-f122 rate sits near the 30 updates/s cap, so it barely
moves. Earlier still, the records were 20.69 and 27.07 frames/s for the CPU
build and 17.78 and 25.17 for the optional AMEM build. Three changes then
landed together, so those runs do not separate them: the audio flush
indexes its registers as one flat array, STARFALL asks for six voices so a
Phasor updates two of its four chips, and bank 0 transfers no longer write
$C073. Before them, runs with the personalities swapped had shown
AMEM changing the rate by under 1% and twelve Phasor voices costing 14% at
vtw33 and 7% at turbo-f122. With six voices the two rows then matched
within 0.1%. The Phasor row now uses all twelve voices; `ti_audio_update`
writes the AYs only when a device tick has passed or a tone, speech or SSI
change asks for it, and the two rows still match within 0.1%. Observed peaks in the sampled runs were 13 enemies and 23 total
shots. The shared VIA clock advances
the simulation independently of render count. `vtw33` omits hardware waits;
`turbo-f122` is a historical cost model. These results establish neither
physical frame rate nor audible SSI quality on F1.3.1. On 2026-10-21 the
user played STARFALL on an Appletini board with a physical Apple joystick.
Before the wait for running paddle timers, the pause readout jumped back
while the stick moved right or down; with it, the jumps were gone. That is
an observation by eye, not a recorded board test. Which paddle path ran,
its interrupt retry and the calibration thresholds remain unmeasured on
the board. On 2026-10-22 the user played a build from the faster text and
publication work on the board and saw no visible difference in play between
TURBO, 33 MHz and 26 MHz; the game stayed playable at the ultrawarp speed.
That too is an observation by eye: no frame rate, update rate or audio
timing was recorded. Recorded board checks at 33 MHz and TURBO remain open.

The boot runs launch with the parallax backdrop on, its default. In the
profile [benchmarks](BENCHMARKS.md) records, it adds about 6 ms to a drawn
frame at vtw33 and 5.5 ms at turbo-f122, to 19.8-20.3 and 19.6-19.7 ms, and
every game step was still drawn.

A breakpoint profile of whole frames in both models measured the time per
drawn frame spent in each routine, at tick 200 (40 frames) and tick 3000
(100 frames). With one call per row, publication took 17.3 ms at vtw33 and
17.6 ms at turbo-f122, of which the byte copy was 5.4 and 11.1 ms. With one
assembly call per rectangle and 16-bit checks it took 7.9 and 12.9 ms; the
copy was unchanged. A write loop with patched absolute operands, run in
place of the page-one `(zp),Y` loop, cut the vtw33 copy to 4.3 ms but left
turbo-f122's at 11.7 ms and its full-screen benchmark 3.5% slower, at a
cost of 61 bytes; it was reverted. STARFALL's own renderer then spent, at
vtw33, 7.9 ms publishing, 5.2 ms clearing its strip, 4.5-5.2 ms building
its list and 1.8-1.9 ms compositing: 22.5-23.6 ms a frame, or 20.7-21.7 ms at
turbo-f122. The library scene, which tracks 16x8-pixel blocks, takes
14.4-15.8 and 13.6-15.2 ms. At vtw33 it spends 4.5-4.8 ms publishing,
1.8-1.9 ms clearing, 3.5-4.2 ms listing and 3.2-3.5 ms composing; at
turbo-f122, publication falls from 12.9 to 8.3-8.9 ms because only changed
blocks are written. HUD text on the banked canvas took about 21 ms per
string at vtw33, drawn a pixel at a time, so frames that redrew it overran an
update. Drawn a row at a time as opaque text, a HUD value now takes 1.0 ms
to draw and 1.9 ms with its publication, or 0.6 and 1.5 ms at turbo-f122;
`tools/profiler.py` measured both, as [benchmarks](BENCHMARKS.md) records.

Machine/source hashes, input traces, ordered SSI writes, timing samples and
screenshots are in `build/starfall/native-ui/validation.json` and, for the
Phasor runs, `build/starfall/native-ui-phasor/validation.json`. Each records
`board_evidence: false`. The local release includes these records and previews.

## Starter

`examples/starter` builds from its manifest as `build/starter.system` and a
280-block `build/starter.po`. `python tests/starter_native_validate.py --cc
C:/msys64/ucrt64/bin/gcc.exe` boots it in both profiles and verifies every
SYS load byte. Held D and W move the square and release stops it, the
calibrated stick moves it left and centring stops it, and Q returns to
ProDOS with the interrupt removed. `build/starter/native-ui/validation.json`
records the traces with `board_evidence: false`.

## Reproduce

```powershell
python tools/setup_inputs.py
python tools/build.py --cc65-home D:/Repos/cc65 --test-target
python tools/check.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe
```

Reference installed tools: Python 3.12.0, cc65/ca65/ld65/ar65 V2.19 and py65
1.2.0. The SDK location is an installed dependency selected on the command
line. Sources, linker configuration, disk tooling and installed ProDOS input
are all ordinary files inside this project. No build reads a sibling checkout.
The setup command downloads only the locked OS image; normal builds are
offline. [Dependency and licensing details](../tools/DEPENDENCIES.md) include
exact input hashes and the deterministic object-metadata normalization.

## Complete release suite

The aggregate command builds CPU-only and optional-AMEM variants and writes
per-command logs and exit results under `build/checks/`. Focused commands:

```powershell
python tools/test.py --no-build
python tests/native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe
python tests/graphics_validate.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe
python tests/scene_validate.py --cc65-home D:/Repos/cc65
$env:CC65_HOME='D:/Repos/cc65'
python tests/audio_validate.py
python tests/storage_validate.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe
python tests/amem_validate.py --cc65-home D:/Repos/cc65
python tests/test_input.py --cc C:/msys64/ucrt64/bin/gcc.exe
python tools/benchmark.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe
```

| Area | Evidence and limits |
| --- | --- |
| CPU memory/startup/exit | 12401 target assertions across four instruction-model modes; 12391 in the main suite, also run in both native profiles |
| Graphics | Nine host asset tests; 4047 compiled checks per native profile, including all 256 glyph codes across seven rows, masks, clipping, font/map banks, near-row publication, CPU publication and AUX restoration; 1367 more in the text suite, which compares both text functions at random positions, random rectangles, the 1024-character limit and full 160-byte rows with a pixel-by-pixel rendering, eight publications each of two surfaces that cross a bank with the whole screen, and checks `ti_digits` and `ti_error_keep` |
| Sprite scenes | 653 instruction-model checks; 59 draws on three areas compared with an independent rendering, no byte outside the areas changed, nothing published for an unchanged list |
| Speech tooling | Six host tests, all numbers 0..9999, authored overrides, phrase-only banks, repeated phones and invalid inputs |
| Music tooling | Nine host tests: deterministic event scores, target limits and bounded simultaneous events; the byte layout the song player reads, rows over 64, thirteen rejected songs and the STARFALL song; MIDI chord slots, rests, holds across a bar line, ignored drums and five rejected files |
| Audio/input target | 1,418 actual 65C02 VIA/AY/SSI/ProDOS fixture checks across eleven runs, including missing devices, queues/priorities, envelopes, voice ownership, effect voices and voice limits, pattern songs, frozen gap clocks, cleanup-error retry, held keys, stick directions and fixed steps |
| Storage | 1666 target-model checks across twelve success/fault modes; 1451 per native profile; real MLI parameter construction, AUX OS loans, cleanup and short-write failures |
| AMEM | 7282 actual-target/controller-fixture checks across eleven modes: identity, CPU equality, bank boundaries, unavailable fallback, partial failure, poison and mapping/IRQ restoration |
| Disk tooling | Seven foundation host tests plus three release-volume tests, including 32 files and multi-block bitmaps |
| Profiler | Four host tests: map and listing parsing, names checked against the label file, and call paths through jumps, loops back to an entry and recursion |
| Stick and steps host | Exact thresholds, hysteresis, travel adaptation, no-stick wait and 20,000 random step frames against reference accounting |
| Starter | In-repository manifest build and two ROM boots; ordinary copied runtime sources, independent SYS/disk build and hash audit |

Feature evidence and exact limitations are in [graphics](GRAPHICS.md),
[audio](AUDIO.md), [storage](STORAGE.md) and [AMEM](AMEM.md).

With the explicitly installed local ROM inputs described below, use:

```powershell
python tests/audio_native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe
python tests/starter_native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe
```

Audio full-ROM tests use real ProDOS interrupt allocation/deallocation and
both true native Phasor and Mockingboard personalities at both speed profiles.
Default source assumption gives 102 ticks per 1.00129 modeled seconds;
explicit 1020484 Hz emulator calibration gives 100. The source assumption is
never selected silently from CPU mode. Each run advances 35 speech phonemes,
then silences AY/SSI, removes IRQ ownership and returns to the real Bitsy Bye
launcher. These are register/device-model checks, not audible speech or board
clock calibration. `build/audio_native/validation.json` records eight runs.

The aggregate runner's `--only` option reruns named checks while retaining
the recorded results of the others. Final command results and current
build-manifest hashes are in `build/checks/validation.json`.

Build/isolation and archive commands:

```powershell
python tools/build.py --cc65-home D:/Repos/cc65 --test-target
python tools/build.py --cc65-home D:/Repos/cc65 --test-target --private --build-dir build/private
python tools/release.py --cc65-home D:/Repos/cc65 --verify-isolation
```

The release tool copies sources into an ordinary project-local export, copies
only the pinned installed ProDOS input and compares complete manifests and
artifact hashes after rebuilding both variants. The source archive excludes
OS/ROM/compiler binaries; the local release archive contains locally built
boot disks and evidence. Inspect `dist/manifest.json` and
`build/selfcontained-check.json` for exact hashes/counts.

## Host and instruction-level checks

Seven host checks pass. They check disk payload sizes around seedling/sapling
boundaries, exact linked payload extraction, deterministic image construction,
directory/allocation/bitmap corruption rejection and restricted object
timestamp normalization. These are packaging/tool evidence.

The compiled target tests pass on py65's actual 65C02 interpreter with a
project-authored Apple memory/softswitch model:

| Run | Checks | Instructions |
| --- | ---: | ---: |
| CPU memory, bounds, overlap, allocation, generation exhaustion and lifecycle | 12391 | 14937024 |
| Missing/aliased auxiliary banks | 2 | 11807 |
| Alternate initial display and processor flags | 2 | 12896 |
| Explicit missed-edge/elapsed-time gap | 6 | 12209 |
| Actual diagnostic, five PASS rows, key exit and AUX restoration | five visible results | 3022909 |

The runs use the same C/assembly implementation and linker configuration as
the shipped SYS. They check bank boundaries, both memmove overlap directions,
resource and near fills/copies, reserved areas, failed allocations, all eight
handle slots, generation retirement, stale handles after free/shutdown/re-init,
mapping restoration and processor flags with IRQs enabled and disabled. They
compare MAIN OS workspace, saved zero page, trampoline and AUX0 with original
bytes, and require the documented ProDOS QUIT call. Per-instruction assertions
check safe instruction fetches while AUX is selected, IRQ masking and the
hardware stack boundary; call/return boundaries check the software stack.
The diagnostic reached minimum hardware SP `$EF` and software stack `$A7B8`,
inside their reservations. A synthetic device clock
checks modular rollover and a long gap without manufacturing missing frames.

`build/diagnostic-emulated.png` renders actual CPU-written AUX bytes and
palettes; it is an emulated memory preview. The harness loads the SYS and
traps MLI QUIT. It does not boot a real operating system, model physical
interrupt delivery, capture/display publication or establish target timing.
See [tests/README.md](../tests/README.md).

Repeated complete builds produce byte-identical SYS, library, disk, map,
labels, debug metadata and manifest with the same inputs. A separate source
export under `build/selfcontained-release*`, using ordinary copied files and the
installed SDK, also produced identical artifacts after changing source
timestamps. `build/selfcontained-check.json` records that comparison. Required
project files are not symlinks, junctions or links into build/session folders.

## Full ProDOS boot

During checkpoint one, GSSquared enhanced //e booted the then-built diagnostic through real
ProDOS 8 2.4.3. Its stock memory model lacks the requested RamWorks banks;
the application displayed the memory requirement in text mode. After Return,
an execution breakpoint at `$BF00` observed command `$65` from the application,
then execution continued into the disk's Bitsy Bye launcher. The source disk
was mounted as the packaged image; its application payload matches the linked
SYS exactly for the hashes in that historical record. This proves boot/launch and the unavailable-memory exit path on
that emulator, not SHR or Appletini timing. `build/gssquared-boot.json` records
the checkpoint-one disk/SYS hashes, breakpoint and returned launcher text.
The current candidate has separately recorded native-machine boot evidence;
the older GSSquared record is not a claim about the new artifact hashes.

## Native Appletini machine

The repo-local native development runner executes the unchanged a2vm W65C02S
core, RamWorks banking and standard SHR preview. These results were recorded
on a hash-checked copy of `appletini-software` revision
`65b3a1e9bae950c54f604261e82db02b6f5968fc`, relicensed to GPL-3.0-only with
notice-only changes. libtini now uses the repository's own copy of the same
sources, and evidence files record its commit. Its Windows wrapper builds
the original C sources with installed MSYS2 UCRT64 GCC 15.1.0, changing only
the upstream Unix build invocation. See [dependencies](../tools/DEPENDENCIES.md)
for licensing and installed tool requirements.

```powershell
python tests/native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe
```

Both `vtw33` and `turbo-f122` passed the actual diagnostic's five numeric
results, rendered identical 320x200 SHR previews, accepted an injected key,
and reached the MLI QUIT stand-in. Each also passed all 12391 compiled target
checks. Independent sentinels verified restoration of all 65536 AUX0 bytes,
26 zero-page bytes, 64 trampoline bytes, the three-byte RESET vector and
non-default readable video flags. The lower 64 bytes of the hardware stack
were unchanged. The runner reads the SYS from the packaged disk; no private
SmartPort service is needed.

Artifacts are `build/native/validation.json`, `build/native/build.json`,
`build/native/diagnostic-vtw33.png` and
`build/native/diagnostic-turbo-f122.png`. The first profile represents
functional 33.333333 MHz execution without all hardware waits. The second
uses historical F1.2.2 costs (`3101934`); it does not establish current F1.3.1
TURBO timing. Previews decode current AUX bytes and omit the production
capture stream and deferred display publication.

An additional native `vtw33` run booted this disk from a user-local Apple ROM
and the supplied slot-7 firmware, with ProDOS MLI trapping disabled. It reached
the full SHR diagnostic, then returned to the real ProDOS Bitsy Bye launcher
after a key. `build/native/boot-exit-vtw33.jsonl` records firmware hashes and
`prodos_mli_traps:false`; `boot-diagnostic-vtw33.png` and
`boot-return-vtw33.png` show the two states. These ignored ROM inputs were
copied locally and are not project dependencies or redistributed assets.

With those installed local inputs, replay the boot/exit sequence:

```powershell
python tools/native_emulator.py --cc C:/msys64/ucrt64/bin/gcc.exe debug --boot --disk build/libtini.po --rom build-inputs/native-roms/Apple2e_Enhanced.rom --slot7-rom build-inputs/native-roms/smartport_a2retronet_style_c700.mem --slot7-c8-rom build-inputs/native-roms/smartport_a2retronet_style_c800.mem --video-rom build-inputs/native-roms/apple2e-video.bin --profile vtw33 --script tests/native_boot.jsonl
```

## Browser player

The [browser player](WEB.md) compiles the same machine and speech sources to
WebAssembly. On 2026-10-22 `tests/web_validate.py` ran a 1,100-frame STARFALL
script through a real ROM and ProDOS boot in the player under Node and in the
native DLL with the native speech worker. At `vtw33` and `turbo-f122`, all 9
checkpoints (ticks, PC, AUX $2000-$9FFF, decoded frame) and the mixed PCM
digest matched. This is emulator evidence, compared with the same model run
natively; it is not browser or board timing.

## Reference repository and firmware boundary

`appletini-one` was read only. Its starting state was `main`, commit/tag
`8af06741f3b9454b6bc226b7d55f69cc09097ccf` / F1.3.1, with these pre-existing
changes:

```text
 M AGENTS.md
?? .tmp_appleiimouse_reference/
?? README_GRAPHICS_API_DESIGN.md
```

The initial git status required `--ignore-submodules=all` because sandbox
permissions prevent Git from opening the nested CherryUSB git metadata. A
read-only content fingerprint separately records 1981 tracked/nonignored files
including accessible submodule worktrees, HEAD, index and the full nonignored
status in `build/appletini-start.json`. Ignored build outputs and `.git`
internals are outside that fingerprint. Recheck it without writing there:

```powershell
python tools/reference_guard.py C:/Users/hasse/source/repos/hasseily/appletini-one build/appletini-start.json --check
```

The final comparison passed: all 1981 recorded files, HEAD, index and status
match the starting fingerprint. No firmware/FPGA builds, flashing or slot
changes occurred. Optional AMEM was tested as a client of the existing
interface in emulators; no firmware implementation was changed.
The selected baseline is an interface/board-test selection, **not** a claim
that the package has already run on that firmware on a board.

## Remaining board gates

Serial discovery returned no ports, and no live board connection was available.
Using an already installed F1.3.1 baseline, without rebuilding or flashing:

- Boot the packaged disks with RamWorks enabled, diagnostic selectors 1-2
  and STARFALL/starter selectors 1-3 exclusively free.
- At 33 MHz, confirm the full SHR screen and five PASS results; press a key
  and verify the ProDOS launcher returns normally.
- Repeat in TURBO and compare results, display stability and clean exit.
- Put known files in standard `/RAM` before launch and verify their data after
  exit. The emulator tests compare the underlying AUX bytes, but this is the
  physical OS/data-preservation gate.
- Measure longest IRQ-masked burst, full memory-operation latency and CPU
  screen-publication cost in each speed mode. No bandwidth, frame deadline
  or elapsed-clock quality has been established on the board.
- Calibrate the VIA source, compare simulation/music/speech rates across both
  speed modes, listen to pronunciations/ducking and confirm AY pitch/envelopes.
- Play STARFALL with a physical keyboard and joystick: held keys, rest
  calibration, all four directions, the pause readout, game over, retry and
  a clean return to ProDOS.
- Compare CPU-only, optional service available and pre-submit unavailable
  configurations; keep video on normal CPU writes throughout.
- Confirm full and dirty SHR publication, visible gaps/overruns, smaller-memory
  failure messages, absent speech and ordinary disk-error recovery.

The next checkpoint is physical release acceptance on the selected existing
firmware. Software for all numbered implementation checkpoints is present;
source/build/model evidence does not close these hardware gates.
