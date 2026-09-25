# Doom for the Appletini

A 65C02 port using Freedoom Phase 1 episode 1, SHR4 PAL256 video, the
Appletini mouse card, **TURBO**, and **8 MB RamWorks**. The complete loader,
game and renderer now link and run together in the Apple memory-map emulator.
The game runs on physical Appletini; the v8 E1M1 TURBO capture measures 3.73 FPS.
Profiling and performance optimization are now the priority.
The v10 PAL candidate restores the four-tic frame limit after hardware testing
rejected v9's longer catch-up batches for poor controls and lower rendered FPS.
The v11 candidate keeps that limit and adds optional ARM copy/fill calls for
phase snapshots and the internal view-buffer clear. It probes at startup and
uses CPU copies on stock firmware. API firmware and v11 hardware performance
still need testing on the PC/hardware.

The default build uses permanently loaded game code in seven auxiliary
language-card banks. Ordinary game pointers address shared main RAM; phase
snapshots let the renderer use that same RAM between groups of game tics.
The control/packet bank uses base auxiliary LC, whose code, zero page and
hardware stack reside in the accelerator's internal RAM rather than PSRAM.
All nine converted maps load with the existing 160-actor pool and the full
2 KiB C stack. The 3D renderer, movement, weapons, monsters, specials and
level flow work in tests. The status bar, title/menu/intermission artwork,
and audible sound/music remain unfinished.

## Build and run

Requires cc65 (`cc65`, `ca65`, `ld65`), Python 3, and Python packages `py65`
and `Pillow` for the emulator/tests. The sibling `appletini-one` checkout
supplies `docs/Apple2e_Enhanced.rom` and `software/ProDOS_2_4_3.po`; set
`APPLETINI_ROOT` when it is elsewhere. The build fetches the checked Freedoom
WAD when needed, or accepts `FREEDOOM=/path/to/freedoom1.wad`.

From this directory:

```sh
make                         # BANKED=1 by default for the real game
make disk                    # dist/Appletini-DOOM.hdv
python3 tools/run_doom.py --build build --data build/data --speed 33 --frames 180 --out build/run
make test
```

`run_doom.py` normally runs the assembled loader through its simulated ProDOS
service. Add `--fast` to install the same images directly and skip loader work.
`--frames` counts emulated 60 Hz intervals, not completed rendered frames.
For example, add `--do '12:hold W' --do '24:mouse 40' --stats build/run/stats.json`
to drive input and record model cycle counts. Build/test Python can be selected
with `make PYTHON=/path/to/python`.

`CONTROL_BANK=0` is the default. For a hardware comparison with the former
extended-bank placement, build into a separate directory with
`make PROFILE=1 CONTROL_BANK=100 BUILD=build/control-psram disk DISK=dist/Appletini-DOOM-control-psram.hdv`.
Use that build's `profile.json` for its serial captures.

The disk includes `DOOM.SYSTEM`, `RENDER.BIN`, `LC.BIN`, `GAME.BIN`, converted
data, and `DOOM.BANKS` containing code and far-table preloads. Generated
`banked.json`, `doom.map`, and `link-report.json` describe the final layout.

## Controls and current limits

W/S or up/down move; left/right turn; A/D or comma/period strafe. Mouse X turns,
left mouse/Open Apple fires, and right mouse/Closed Apple uses doors and
switches. Tab toggles running; 1–7 select available weapons. The game starts
at E1M1 on Hurt Me Plenty. Esc is captured by input but has no menu yet.
Intermission/finale state and fire/use progression exist; their screens do not.

## Hardware performance readout

The banked build shows **FPS**, **TPS**, and the selected **50HZ/60HZ** clock
calibration in the bottom strip. After loading, allow about two seconds for
the first numbers; subsequent measurements update about every two seconds.
FPS counts completed game frames. TPS counts simulation tics; normal Doom
speed is 35 tics per second.

Press **V** to match the machine's video clock: **60HZ for NTSC**, **50HZ for
PAL**. This selects both the game clock and the readout, targeting 35 TPS
on either standard when the machine can keep up. Changing it starts a fresh
measurement window. The normal build defaults to 60HZ; build with
`VIDEO_HZ=50` for a PAL default.
The scheduler runs at most **four tics per rendered frame**. It counts and
drops excess due tics without carrying a backlog into later frames. At low
FPS this deliberately slows game time so each frame does less catch-up work;
35 TPS requires at least 8.75 rendered FPS with this limit. The 16-bit elapsed
VBL clock retains PAL/NTSC calibration. With the ARM memory API enabled,
long CPU holds can merge VBL IRQs; use the serial capture's host-window rates
for performance comparisons instead of the on-screen rates.

Rates come from the mouse-card VBL interrupt clock and include elapsed time
spent in game logic, bank switching, rendering, presentation and the readout.
They do not assume a CPU MHz value. Seven text rows are redrawn per update;
the 3D view is untouched. To compare hardware modes, use the same scene and
record several consecutive readings, along with the firmware and speed mode.

An explicitly named hardware-test image can be built with:

```sh
make disk DISK=dist/Appletini-DOOM-debug.hdv
```

TURBO batches video writes. The Python harness's mode named `turbo` assumes a
nominal 75 MHz budget and fixed I/O surcharge; it does not emulate the target's
full PSRAM/cache, batching and synchronization costs. Its cycle reports are not
measured hardware frame rates. A conventional 33 MHz emulator run is also
separate from testing hardware TURBO.

## Profiling hardware and emulator runs

`make profile` builds **dist/Appletini-DOOM-profile.hdv** and matching
**dist/Appletini-DOOM-profile.json**. The FPS/TPS display remains available.
The profiling image counts VBL samples across game logic, memory copies,
rendering stages, presentation and debug work. A separate snapshot is readable
through the Appletini serial console without stopping the game.

The current PAL hardware-test pair is
`dist/Appletini-DOOM-profile-v11-amem-pal.hdv` and
`dist/Appletini-DOOM-profile-v11-amem-pal.json`. It starts at **50HZ** and uses
the four-tic limit. Use its matching metadata for captures. The serial report
shows whether the memory API is enabled; this build uses host elapsed time
for FPS/TPS because ARM transfers can merge VBL interrupts during CPU holds.

The exact firmware API is documented in the sibling `appletini-one` branch
`codex/memory-copy-fill-api` (F1.1.2), in `README_MEMORY_API.md`. The previous v10 disk
remains available as a control for the helper's CPU-fallback overhead.

See [profiling instructions](docs/PROFILING.md) for serial capture, repeatable
hardware runs, and bank-aware emulator instruction/cycle reports. The hardware
sampler uses no additional timer I/O; its phase shares are coarse samples,
not precise durations. Real hardware TURBO measurements are the reference.

## Tests and reference builds

- `tests/test_doom_banked_platform.py` boots the complete program and checks
  live input, advancing game packets, and changing nonblank SHR frames.
- `tests/test_game_banked.py` runs all nine maps on the actual memory mapper
  and compares selected game sessions with the established flat reference.
- `tests/test_game_banks.py` exercises nested bank calls and IRQ boundaries;
  `tests/test_game_snapshots_banked.py` checks snapshot bank ownership.
- `tests/test_debug_readout.py` checks rates, 50/60 Hz calibration, counter
  wrapping, refresh intervals and screen bounds. The platform test also checks
  the real IRQ clock and kernel drawing path.
- `make STANDIN=1` builds the separate platform test pattern in `build/standin`.
  Run it with `--build build/standin --data build/standin/data`. It is not Doom
  gameplay. `BANKED=0` retains the older layout for reference and stand-in work;
  the complete real game still exceeds that layout.
- The flat game harness uses synthetic instruction windows for differential
  tests. Passing it alone does not prove an Apple memory layout fits.

See [status](docs/STATUS.md), [design](docs/DESIGN.md),
[banking assessment and implementation](docs/BANKING_OPTIONS.md), and the
[TURBO mirroring and fast-memory study](docs/TURBO_MEMORY_STUDY.md).
