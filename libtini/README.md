# libtini

libtini is part of [appletini-software](../README.md). Run its commands from
this `libtini/` folder. The [MIT License](LICENSE) applies to libtini.

libtini is a self-contained C game SDK for an enhanced Apple //e with an
Appletini. It uses the interfaces of the Appletini firmware: CPU SHR graphics
with a sprite renderer, banked resources, Mockingboard and Phasor music and
effects, SSI-263 speech, input and ProDOS files.

**Documentation:** open [docs/index.html](docs/index.html) in a browser. It
contains a guide to start, guides with sample code, the full API reference,
the build and manifest reference, tool options, data formats and the machine
contract. The [design/](design/) folder contains the development plan, the
design notes and the measurements as Markdown.

[STARFALL](examples/starfall/README.md) is the example game. It is a vertical
shooter with one endless level, five enemy types, five bosses, automatic fire,
four weapon levels, wingmen, overdrive, chain scores, shields, repairs, bombs,
music and spoken callouts. It uses public-domain Kenney sprites, original boss
art and an eight-voice arrangement of a free doranarasi MIDI demo. It keeps
its title screen, panels, wave code, boss code and boss art in RamWorks and
copies each part to an overlay window when it needs it.

Boot `build/starfall.po`. Push Return or a joystick button to start with the
Mockingboard, or push P to select the Phasor. Hold WASD or the arrow keys to
move. Space drops a bomb and Q exits. A joystick operates without setup: each
start measures its rest position, and J turns it off.

[The starter](examples/starter/README.md) is a small game to copy for a new
game. A game can also operate in a web browser on the development machine
model; see [the browser player](docs/reference/browser.html). Networking,
more video backends and 3D are not part of libtini at this time.

# Build

Install Python 3.10 or newer and a complete **cc65 SDK 2.19**. The reference
tools are CPython 3.12.0 and cc65, ca65, ld65 and ar65 V2.19. In PowerShell,
from this folder:

~~~powershell
python tools/setup_inputs.py
python tools/build.py --cc65-home D:/Repos/cc65 --test-target
python tools/build.py --cc65-home D:/Repos/cc65 --private --test-target --build-dir build/private
~~~

The first command installs the official ProDOS 8 2.4.3 image, with a pinned
hash, as ignored files in `build-inputs/prodos/`. Builds then operate offline.
Use `--no-disk` to build the programs and the library without an OS image.
To omit `--cc65-home`, put the bin folder of the SDK on PATH or set
CC65_HOME.

Each game is a `game.json` manifest in `games/` or `examples/`. The option
`--game NAME` builds the library and that game only. Each build shows the free
bytes of each memory area of each game. When a segment does not fit, the build
stops and shows the number of bytes that are missing.
[Dependencies and licenses](tools/DEPENDENCIES.md) gives the exact versions,
the input hashes, the deterministic object metadata and the local ROM
installation.

The default build does not contain the private SmartPort transport. The
optional build identifies the controller and uses AMEM only for applicable
working-memory operations. When AMEM is not available before a transfer
starts, the CPU does the transfer. Video always uses CPU writes.

| Artifact | Purpose |
| --- | --- |
| build/libtini.po, libtini.system | Memory and SHR diagnostic disk and SYS |
| build/audio_demo.po, audio_demo.system | Music, speech and number demo; the disk boots AUDIO.SYSTEM |
| build/starfall.po, starfall.system | STARFALL shooter; the disk boots STARFALL.SYSTEM |
| build/starter.po, starter.system | Starter game; the disk boots STARTER.SYSTEM |
| build/speech_check.po, speech_check.system | SSI-263 check; the disk boots SPEECH.SYSTEM |
| build/libtini.lib | cc65 library, with the project startup and linker configuration |
| build/*.map, *.lbl, *.dbg, layout.json, memory.json | Checked static layout, symbols and free bytes |
| build/manifest.json | Hashes of sources, tools, the installed OS and outputs |
| build/private/ | The optional-AMEM build of the library and the other programs; STARFALL has no AMEM build |
| dist/libtini-source.zip | Source, starter, tests, tools, documentation and design notes |
| dist/libtini-local-release.zip | Local programs and disks, source and check records |

The ProDOS kernel is a separately installed input. The source archives include
the enhanced //e and slot-7 boot ROMs in `build-inputs/native-roms/`, with their notices. They
do not contain ProDOS bytes. The local boot disks contain ProDOS.
Read the ProDOS distribution terms before you share these disks. The source
archive does not contain FPGA/ARM firmware or host compiler binaries.

# Run

Core graphics, audio and offline games run on **Appletini F1.3.2**.
The optional HTTP/S and JSON API and STARFALL leaderboard require
**F1.3.3** and its per-board HTTPS setup. Keep the same slot assignments.

Enable RamWorks. Give selectors **1-3** to STARFALL and the starter, and
selectors 1-2 to the diagnostic. No RAM disk or driver can use these banks.
Keep SmartPort in slot 7 and a Mockingboard or Phasor personality in slot 4.

Boot `build/libtini.po` to see five memory-test results on one SHR screen.
Push a key to restore AUX0 and go back to ProDOS. If granted banks are missing
or aliased, the diagnostic shows the requirement in text and then exits
normally.

Boot `build/audio_demo.po` for music and speech. Push 1 to hear READY, 2 to
hear 1984, S to stop speech and Q to exit. The VIA timing does not change with
the CPU speed.

# Tests and tools

Install py65==1.2.0 for the instruction-level tests. The native tests and
the host game logic need an installed C compiler. The reference compiler is
MSYS2 UCRT64 GCC 15.1.0:

~~~powershell
python -m pip install py65==1.2.0
python tools/check.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe
~~~

The full check builds the two variants and checks the asset, disk, speech and
music tools and the host game and input logic. Then it runs the compiled
memory, graphics, audio, storage and AMEM routines. Add `--rom-boot` to boot
the audio demo, the starter and STARFALL in ProDOS with the bundled boot
ROM inputs. Text previews also need the optional video ROM. See
[ROM inputs](build-inputs/native-roms/README.md).

[Checks](docs/reference/testing.html) gives each check and what it covers.
[tests/README.md](tests/README.md) describes the foundation harness.

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

The starter copies its runtime as ordinary source files. It does not need a
sibling checkout or an SDK build folder. The release command builds a new
source export with only the installed tools and the copied, pinned OS input.
Then it makes deterministic local archives.

Ordinary C pointers are near pointers. RamWorks resources use handles and
explicit offsets. Configured memory is never a flat 8 MB heap.

# License

The [MIT License](LICENSE) applies to libtini, thus games that you build with
it can use any terms. The browser player in `tools/web/` is GPL-3.0-only,
because it links the GPL-3.0 development emulator of this repository. Its
files contain SPDX notices. The bundled assets and the installed tools keep
their own terms: see [dependencies and licenses](tools/DEPENDENCIES.md) and
each asset folder.

The optional [HTTP/S and JSON API](docs/api/net.html) probes the new ARM
network service. The core SDK and offline games keep their existing-firmware
paths. Build `net_check` for a repeated POST, stream and JSON example.
STARFALL uses the service only from its game-over rankings panel.
