# libtini

libtini is part of [appletini-software](../README.md); run its commands from
this `libtini/` folder. It is licensed under the [MIT License](LICENSE).

A self-contained C game SDK for an enhanced Apple //e with Appletini. It uses
existing firmware interfaces: CPU SHR graphics with a sprite renderer,
banked resources, shared Mockingboard/Phasor music and effects, SSI-263
speech, input and ProDOS files.

The five implementation checkpoints now have working source, applications and
host/emulator checks. Physical board acceptance remains pending. Networking,
additional video backends and experimental 3D are later work.

[STARFALL](examples/starfall/README.md) is the example game: a vertical
scrolling survival shooter with five enemy types that arrive sector by
sector, automatic fire, four weapon levels, wingmen, overdrive, chain
scoring, shields, repairs, bombs, music and spoken callouts. It uses
public-domain Kenney sprites and an eight-voice arrangement of a free
doranarasi MIDI demo, and runs one endless level. Boot
`build/starfall.po`; Enter or a joystick button launches with Mockingboard,
or P selects Phasor. Hold WASD/arrows to move, Space drops a bomb and Q
exits. A joystick works without setup: each launch measures where it rests.
J turns it off. [The starter](examples/starter/README.md) is a small game to
copy for a new one.

A game can also run in a web browser on the development machine model; see
[the browser player](docs/WEB.md).

Read [the plan](PLAN.md), [building a game](docs/GAMES.md),
[memory map](docs/MEMORY_MAP.md), [API contracts](docs/CONTRACTS.md) and
[validation evidence/gates](docs/VALIDATION.md).

# Build

Install Python 3.10+ and a complete **cc65 SDK 2.19**. Reference tools are
CPython 3.12.0 and cc65/ca65/ld65/ar65 V2.19. In PowerShell from this directory:

~~~powershell
python tools/setup_inputs.py
python tools/build.py --cc65-home D:/Repos/cc65 --test-target
python tools/build.py --cc65-home D:/Repos/cc65 --private --test-target --build-dir build/private
~~~

The first command installs hash-pinned official ProDOS 8 2.4.3 as ordinary,
ignored files under build-inputs/prodos/. Normal builds then work offline.
Use --no-disk to build application/library outputs without an OS image.
Put the installed SDK's bin on PATH or set CC65_HOME to omit --cc65-home.
Each game is a `game.json` manifest under games/ or examples/; `--game NAME`
builds the library and that game only. Every build prints each game's free
bytes per memory area and stops with the shortfall when a segment does not
fit; see [building a game](docs/GAMES.md).
[Dependencies and licenses](tools/DEPENDENCIES.md) document exact versions,
input hashes, deterministic object metadata and local ROM installation.

Default builds compile out private SmartPort transport. The optional build
probes the selected existing controller and uses AMEM only for eligible
working-memory operations. Absence selects CPU before submission. Video
always uses CPU writes. See [AMEM failure/identity rules](docs/AMEM.md).

| Artifact | Purpose |
| --- | --- |
| build/libtini.po, libtini.system | Memory/SHR diagnostic disk and SYS |
| build/audio_demo.po, audio_demo.system | Music/speech/number demo; disk boots AUDIO.SYSTEM |
| build/starfall.po, starfall.system | STARFALL survival shooter; disk boots STARFALL.SYSTEM |
| build/starter.po, starter.system | Starter game; disk boots STARTER.SYSTEM |
| build/libtini.lib | cc65 library, with project startup and linker configuration |
| build/*.map, *.lbl, *.dbg, layout.json, memory.json | Checked static layout, symbols and free bytes |
| build/manifest.json | Source, tool, installed OS and output hashes |
| build/private/ | Corresponding optional-AMEM build of the library and the other programs; STARFALL has none |
| dist/libtini-source.zip | Source, starter, tests, tools and reference docs |
| dist/libtini-local-release.zip | Local applications/disks, source and evidence |

The ProDOS kernel is a separately installed input. Source archives omit OS
and Apple ROM bytes. Local boot disks contain ProDOS; check its distribution
terms before sharing those disks. No firmware binaries, Apple ROMs or host
compiler binaries are bundled in the source archive.

# Run

Use existing **Appletini F1.3.1**, commit
8af06741f3b9454b6bc226b7d55f69cc09097ccf, as the named board baseline.
No firmware rebuild, flashing or slot change is required. That baseline is
selected for validation; the current package has not yet been tested on a
physical board.

Enable RamWorks. Grant selectors **1-3** exclusively for STARFALL and the
starter (1-2 for the diagnostic), with no RAM disk/driver occupying those
expansion banks. Keep SmartPort in slot 7 and a Mockingboard or Phasor
personality in slot 4.

Boot build/libtini.po for five memory-test results on one SHR screen; press a
key to restore AUX0 and return to ProDOS. If granted banks are missing or
aliased it reports the requirement in text and still exits normally.
Boot build/audio_demo.po for music and speech; 1 says READY, 2 speaks 1984,
S stops speech and Q exits. Configured VIA timing is independent of CPU speed;
physical clock calibration and audible quality remain board gates.

# Tests and tools

Install py65==1.2.0 for instruction-level tests. Native tests and host game
logic need an installed C compiler; reference is MSYS2 UCRT64 GCC 15.1.0:

~~~powershell
python -m pip install py65==1.2.0
python tools/check.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe
~~~

The full check command builds both variants, checks asset/disk/speech/music
tools and host game and input logic, then runs actual compiled memory,
graphics, audio, storage and AMEM routines. Add --rom-boot to include real
ProDOS audio, starter and STARFALL boots with explicitly installed
repo-local ROM inputs. See
[focused commands and evidence](docs/VALIDATION.md). Emulator previews sample
AUX/video/device models; only board execution proves physical output/timing.

~~~powershell
python tools/assets.py --help
python tools/speech.py assets/speech.json --preview
python tools/music.py assets/music.json --preview
python tools/music.py assets/starfall/music/song.json --preview
python tools/build.py --cc65-home D:/Repos/cc65 --game starter
python examples/starter/create.py build/my-game
python build/my-game/build.py --cc65-home D:/Repos/cc65 --no-disk
python tools/benchmark.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe
python tools/profiler.py --game starfall --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe --key 13 --skip 360 --frames 600 _render _hud
python tools/release.py --cc65-home D:/Repos/cc65 --verify-isolation
~~~

The starter copies its runtime as ordinary source files; it needs no sibling
checkout or SDK build directory. The release command checks a fresh source
export using only installed tools and the copied pinned OS input, then creates
deterministic local archives. Detailed APIs: [graphics](docs/GRAPHICS.md),
[audio/input/speech](docs/AUDIO.md), [storage](docs/STORAGE.md).
Ordinary C pointers remain near pointers. RamWorks resources use handles
and explicit offsets; configured memory is never a flat 8 MB heap.

# License

libtini is licensed under the [MIT License](LICENSE), so games built with it
can use any terms. The browser player in `tools/web/` is GPL-3.0-only because
it links the repository's GPL-3.0 development emulator; its files carry SPDX
notices. Bundled assets and installed tools keep their own terms: see
[dependencies and licenses](tools/DEPENDENCIES.md) and each asset folder.
