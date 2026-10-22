# Installed build inputs

The build uses Python 3.10 or newer (the reference is CPython 3.12.0) and an
installed cc65 SDK **2.19**. The compiler, assembler, linker, archiver,
`include/`, `asminc/` and `lib/none.lib` must come from that SDK. Install cc65
separately from <https://github.com/cc65/cc65/releases/tag/V2.19>. The cc65
package uses the zlib-style license in its `LICENSE`, which permits linked
runtime code in products.

This repository contains no cc65 source or binary. The reference Windows
installation is `D:/Repos/cc65`, and the build uses it only as an installed
SDK. The build does not compile or read its source tree. No installation path
is a project requirement.

For example, from the libtini folder:

```powershell
python tools/setup_inputs.py
python tools/build.py --cc65-home D:/Repos/cc65 --test-target
```

You can also put the `bin/` folder of the SDK on `PATH`, or set `CC65_HOME`,
and omit `--cc65-home`. `python tools/build.py --no-disk` does not need an OS
image. The default compilation defines `TI_PRIVATE_TRANSPORT=0` and omits the
private transport. `--private --build-dir build/private` builds the optional
AMEM backend separately. Both builds publish video with CPU writes.

## Compiler and linker commands

The build calls `cc65 -t none --cpu 65c02 --standard c99 -O`, `ca65 -t none
--cpu 65c02`, `ar65 r` and `ld65 -C cfg/libtini.cfg`, or the layout that a game
manifest names. Examples are the static full-game `cfg/game.cfg` and the
STARFALL layout `examples/starfall/starfall.cfg`.

The build uses the `none` runtime, the project startup and a raw ProDOS SYS
binary that loads at `$2000`, with no BASIC header. The public C interface uses
the cc65 calling convention and the cc65 C subset. The `--standard c99` option
does not mean full ISO C99 conformance.

`build/manifest.json` records the SHA-256 hashes of sources, inputs and tools.
`build/layout.json`, `.map`, `.lbl` and `.dbg` describe the linked result. The
build writes no build timestamp and makes no network request.

STARFALL is foreground-only, nonrecursive C, and it also uses `--static-locals`
to decrease software-stack traffic. Its playfield uses the library sprite
scene, which has a 65C02 assembly renderer. The audio interrupt receiver does
not call the game code or the scene. The local variables of the game and the
scratch state of the scene are not reentrant.

## Deterministic objects

The build omits source-level debug information, because cc65 and ca65 put
file timestamps in it. Exported labels and linker maps are available. The
build sets fixed modification times on the objects before it archives them,
because ar65 stores these times in `.lib`.

ca65 2.19 also writes the translation time into its informational object
options. `normalize_object` validates the version-17 object format and
replaces only `OPT_DATETIME` with the same fixed epoch, before the build
archives or links the object. No code, data, symbol or relocation section
changes.

The assembler reads ordinary staged copies in `build/asm/` with fixed
timestamps, because ca65 records the timestamp of the primary source. These
files come from the repository sources. They are not separate build inputs,
and the build does not link them into the project.

## ProDOS disk input

The disk packager uses the official **ProDOS 8 2.4.3** 143K `.po` release:

- Release: <https://prodos8.com/releases/prodos-243/>
- Input and SHA-256 lock: [prodos-input.json](prodos-input.json)
- Upstream hashes: <https://raw.githubusercontent.com/ProDOS-8/ProDOS8-Releases/master/SHA256SUM>
- Expected image SHA-256: `398d333cb2ab92df9f8bb2cf64b946f2567116910eb8359cf4bdee5d4194f0fa`

The official release repository and release page supply the operating system
for download. They do not supply an explicit redistribution license. **This
repository does not redistribute the ProDOS image and does not say that it is
open source.**

`setup_inputs.py` installs the exact official input as ordinary, ignored files
in `build-inputs/prodos/` for the local build. It checks the pinned hash
before it writes the file. After installation, builds operate offline and read
only this local input, never a sibling project. Do not distribute a boot disk
without the applicable ProDOS distribution terms. The `--no-disk` option
builds the `.system` and `.lib` artifacts without the OS.

To use a separately installed exact image, pass
`--prodos-image path/to/ProDOS_2_4_3.po`. It must have the same hash. Do not
point this option at a sibling checkout, a temporary folder or a linked build
output.

## Disk packager

`tools/disk.py` is project Python that uses only the standard library. It
makes deterministic disks: 280-block diagnostic and audio demo disks, and one
disk for each game manifest, with 1600 blocks if the manifest does not give a
different number. Each disk contains the two boot blocks of the release and
its unmodified `PRODOS` kernel. The program is the first `.SYSTEM` application,
with file type `$FF` and auxiliary type `$2000`.

The ProDOS kernel contains the Bitsy Bye launcher that MLI QUIT uses. The
disks do not contain the other utilities of the release disk. The packager
checks directory links, lengths, parent fields, block ownership, the
allocation bitmap and each packaged payload.

A program linked with `cfg/game.cfg` has a load image that can extend to
`$BEFF`. Its static low segments go to their run addresses before the program
uses BSS or the software stack.

## Asset compilers and art

The speech and music compilers and the MIDI arranger use only the Python
standard library. No build reads a MIDI file: STARFALL compiles the arranged
song that is in the repository. See [its music notes](../assets/starfall/music/README.md).

The STARFALL art is the vendored Kenney Pixel Shmup 1.1 pack, which is in the
public domain under CC0. The original archive, the publisher license and the
hashes are in `assets/starfall/`. `tools/starfall_assets.py` checks and
converts the archive offline with the standard library. The 800 KiB STARFALL
disk boots `STARFALL.SYSTEM` and needs no external game resource.

## Test tools

The instruction tests use an installed `py65==1.2.0` (BSD-3-Clause). The host
game and input checks compile the C sources with an installed GCC. The native
runner, the benchmarks and `tools/profiler.py` use the GCC version below. The
profiler also assembles listings with the installed ca65 and boots with the
installed ROM inputs that the boot checks use.

The reference cc65 2.19 Windows input hashes are:

| Input | SHA-256 |
| --- | --- |
| `cc65.exe` | `410771f53529c07e5247cc781b6c145127512cfe7f46b18d15e78c4259f4c4bd` |
| `ca65.exe` | `9f0d1248dd88196750d086b6b11222f3f711470b965105903fbfcc23aa61773c` |
| `ld65.exe` | `e2841393d793a1c3a790e66b7ef9f4b69d86f388e37cbacd22e2dbfed2c3e982` |
| `ar65.exe` | `94b0532188ef549ddd5c11b7e618790a05d2073eec2672838c186f0fb40f1815` |
| `none.lib` | `5f63a1aad2f9876a9f5e2f875f904ae2e9fb44f332e54f422ffd9bf34daaa38b` |

The same selected sources, flags, installed SDK inputs and OS input give the
same program, library and disk bytes. A version label alone cannot make sure
that two compiler binaries are the same; compare the manifests.

## Native Appletini development runner

The optional native check tool is the development emulator of this
repository: the runner in `../tools/appletini`, with its SSI-263 speech worker,
and a2vm in `../demos/doom_gs/tools/a2vm`. The GPL-3.0-only license applies to
all of them. This host tool is a separate executable dependency. libtini does
not link its code into the target library or into a SYS file.

The reference native compiler is MSYS2 UCRT64 **GCC 15.1.0 (Rev5)**, which
you select with `--cc`. Python 3.12.0 builds the eight original C translation
units as `build/native/libappletini.dll`. The wrapper changes only the Unix
build command. It does not change the CPU, machine, device, cost or preview
code.

`build/native/build.json` records the hashes of all C files, headers and the
compiler, the exact compiler command and the DLL hash. All sources and outputs
are in the repository. The direct-launch tests need no SDL, browser, Apple ROM
or sibling checkout:

```powershell
python tools/native_emulator.py --cc C:/msys64/ucrt64/bin/gcc.exe build
python tests/native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe
python tools/native_emulator.py --cc C:/msys64/ucrt64/bin/gcc.exe run --disk build/libtini.po --system LIBTINI.SYSTEM --profile vtw33 --frames 120 --screenshot build/native/diagnostic-vtw33.png
python tools/native_emulator.py --cc C:/msys64/ucrt64/bin/gcc.exe run --disk build/libtini.po --system LIBTINI.SYSTEM --profile turbo-f122 --frames 120 --screenshot build/native/diagnostic-turbo-f122.png
```

## Browser player

`tools/web.py` compiles the same machine and speech sources to WebAssembly
with an installed **Emscripten 6.0.13** from emsdk. It refuses other versions.
`build/web/player/build.json` records the input hashes, the commands and the
output hashes. `tests/web_validate.py` runs the player in the Node 24.19.0 of
emsdk. The player links GPL-3.0 code, thus each copy of it must offer its
source. See [the browser player](../docs/reference/browser.html).

## Emulator profiles and ROM inputs

The `vtw33` profile runs at a nominal 33.333333 MHz without all hardware
waits. `turbo-f122` uses the F1.2.2 TURBO cost model. Both profiles give
program and memory results. A direct launch loads the packaged SYS and uses a
ProDOS MLI stand-in. The native test sends a key and requires that the
stand-in sees QUIT.

A full ROM boot needs separately supplied inputs in the ignored
`build-inputs/native-roms/` folder:

- The enhanced //e 16 KiB system ROM.
- The 256-byte C700 and 2048-byte C800 SmartPort firmware.
- Optionally, a 4096-byte video character ROM for text previews.

The repository does not redistribute these files. The wrapper requires
explicit `--rom`, `--slot7-rom` and `--slot7-c8-rom` options, and never uses
the sibling defaults of the upstream helper. Text previews need `--video-rom`,
because the repository does not bundle the upstream fallback font. SHR
previews do not need a character ROM. `build-inputs/native-roms/provenance.json`
and the boot transcript record the hashes of the local ROMs.
