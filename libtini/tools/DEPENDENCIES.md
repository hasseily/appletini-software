# Installed build inputs

The build uses Python 3.10+ (reference build: CPython 3.12.0) and an installed
cc65 SDK **2.19**. The compiler, assembler, linker, archiver, `include/`,
`asminc/`, and `lib/none.lib` must belong to that SDK. Install cc65 separately
from <https://github.com/cc65/cc65/releases/tag/V2.19>. The cc65 package uses the
zlib-style license in its `LICENSE`; linked runtime code is allowed in products.
No cc65 source or binary is copied into this repository. The reference Windows
installation is `D:/Repos/cc65`; it is used only as an installed SDK. The
build does not compile or inspect its source tree, and no installation path
is encoded as a project requirement.

For example, from the libtini root:

```powershell
python tools/setup_inputs.py
python tools/build.py --cc65-home D:/Repos/cc65 --test-target
```

Alternatively put that SDK's `bin/` on `PATH`, or set `CC65_HOME`, then omit
`--cc65-home`. `python tools/build.py --no-disk` does not need an OS image.
Default compilation defines `TI_PRIVATE_TRANSPORT=0` and omits private
transport. `--private --build-dir build/private` separately builds the optional
probed AMEM backend; CPU video publication remains mandatory in both builds.

The build invokes `cc65 -t none --cpu 65c02 --standard c99 -O`, `ca65 -t none
--cpu 65c02`, `ar65 r`, and `ld65 -C cfg/libtini.cfg`, or the layout a game's manifest
names, such as the static full-game `cfg/game.cfg` or STARFALL's
`examples/starfall/starfall.cfg`. It deliberately uses
the `none` runtime, the project's startup, and a raw ProDOS SYS binary loaded at
`$2000`, with no BASIC executable header. The public C interface uses the cc65
calling convention and the supported cc65 C subset; the option does not imply
complete ISO C99 conformance. `build/manifest.json` records source/input and
tool SHA-256 hashes; `build/layout.json`, `.map`, `.lbl`, and `.dbg` describe the
linked result. There is no build timestamp or network request in the build.

STARFALL's foreground-only, nonrecursive C additionally uses
`--static-locals` to reduce software-stack traffic. Its playfield uses the
library sprite scene, whose renderer is project-authored 65C02 assembly. The
audio interrupt receiver does not call this game code or the scene; those
local variables and the scene's scratch state are not reentrant.

Source-level debug information is omitted because cc65/ca65 embed file
timestamps in it; exported labels and linker maps remain available. Generated
object mtimes are fixed before archiving because ar65 stores them in `.lib`.
ca65 2.19 also writes the current translation time into its informational
object options. `normalize_object` validates the version-17 object format and
replaces only `OPT_DATETIME` with the same fixed epoch, before archiving or
linking. No code, data, symbol, or relocation section is changed.
The assembler reads ordinary staged copies under `build/asm/` with fixed
timestamps because ca65 records the primary source's timestamp even without
line debug information. These files are derived from the repository sources;
they are not independent build inputs and are never linked into the project.

## ProDOS disk input

The disk packager uses the official **ProDOS 8 2.4.3** 143K `.po` release:

- Release: <https://prodos8.com/releases/prodos-243/>
- Input and SHA-256 lock: [prodos-input.json](prodos-input.json)
- Upstream hashes: <https://raw.githubusercontent.com/ProDOS-8/ProDOS8-Releases/master/SHA256SUM>
- Expected image SHA-256: `398d333cb2ab92df9f8bb2cf64b946f2567116910eb8359cf4bdee5d4194f0fa`

The official release repository and release page were checked for licensing.
They supply the operating system for download but do not supply an explicit
redistribution license. **This repository does not redistribute the ProDOS
image or claim that it is open source.** `setup_inputs.py` installs the exact
official input into ignored, ordinary `build-inputs/prodos/` files for the
user's local build. It verifies the pinned hash before writing. Once installed,
builds are offline and read only the repo-local input, never a sibling project.
Do not distribute the resulting boot disk without checking the applicable
ProDOS distribution terms. The application-only `.system` and `.lib` artifacts
can be built without the OS with `--no-disk`.

An existing separately installed exact image can be passed explicitly using
`--prodos-image path/to/ProDOS_2_4_3.po`; it must match the same hash. Do not point
this option at a sibling checkout, volatile directory or linked build output.

`tools/disk.py` is project-authored Python using only the standard library.
It creates deterministic disks: 280-block diagnostic and audio demo disks
and one per game manifest, 1600 blocks unless the manifest says otherwise.
Each copies the release's two boot blocks and unmodified `PRODOS` kernel and
writes its program as the first `.SYSTEM` application, file type `$FF`,
auxiliary type `$2000`.
The ProDOS kernel includes the Bitsy Bye launcher used by MLI QUIT. Other
release-disk utilities are omitted. Directory links, lengths, parent fields,
block ownership, allocation bitmap and exact packaged payload are checked.
A program linked with `cfg/game.cfg` has a load image that can extend
through `$BEFF`; static low segments relocate before BSS/software-stack use.
The speech and music compilers and the MIDI arranger use Python's standard
library only. No build reads a MIDI file: STARFALL compiles its committed
arranged song; see [its music notes](../assets/starfall/music/README.md).

STARFALL's artwork is the vendored Kenney Pixel Shmup 1.1 pack, dedicated to
the public domain under CC0. The original archive, publisher license and
hashes live in `assets/starfall/`; `tools/starfall_assets.py` verifies and
converts it offline using the standard library. Its independent 800 KiB disk
boots `STARFALL.SYSTEM` and contains no external game-resource requirement.

Instruction tests use installed `py65==1.2.0` (BSD-3-Clause). Host game and
input checks compile original C with installed GCC; the native runner,
benchmarks and `tools/profiler.py` use the GCC version below. The profiler
also assembles listings with the installed ca65 and boots with the same
installed ROM inputs as the boot checks.

The reference cc65 2.19 Windows input hashes are:

| Input | SHA-256 |
| --- | --- |
| `cc65.exe` | `410771f53529c07e5247cc781b6c145127512cfe7f46b18d15e78c4259f4c4bd` |
| `ca65.exe` | `9f0d1248dd88196750d086b6b11222f3f711470b965105903fbfcc23aa61773c` |
| `ld65.exe` | `e2841393d793a1c3a790e66b7ef9f4b69d86f388e37cbacd22e2dbfed2c3e982` |
| `ar65.exe` | `94b0532188ef549ddd5c11b7e618790a05d2073eec2672838c186f0fb40f1815` |
| `none.lib` | `5f63a1aad2f9876a9f5e2f875f904ae2e9fb44f332e54f422ffd9bf34daaa38b` |

Reproducibility means identical selected sources, flags, installed SDK inputs
and OS input produce identical application/library/disk bytes. A version label
alone cannot guarantee identical compiler binaries; compare the manifest.

## Native Appletini development runner

The optional native validation tool is the repository's own development
emulator: the runner in `../tools/appletini`, with its SSI-263 speech worker,
and a2vm in `../demos/doom_gs/tools/a2vm`, all GPL-3.0-only. Until libtini
moved into appletini-software on 2026-10-22 it carried a hash-locked copy of
revision `65b3a1e9bae950c54f604261e82db02b6f5968fc` with the same files.
Evidence files now record the repository commit of those sources, marked when
they have local changes. This host tool is a separate executable dependency
and its code is not linked into libtini's target library or SYS.

Reference native compiler: MSYS2 UCRT64 **GCC 15.1.0 (Rev5)**, selected as an
installed dependency with `--cc`. Python 3.12.0 builds the original eight C
translation units as `build/native/libappletini.dll`. The wrapper changes
only the Unix build invocation; CPU, machine, device, cost and preview code
are unchanged. `build/native/build.json` records all C/header/compiler hashes,
the exact compiler command and DLL hash. All sources and outputs reside in
the repository. No SDL, browser, Apple ROM or sibling checkout is needed for
the normal direct-launch tests:

```powershell
python tools/native_emulator.py --cc C:/msys64/ucrt64/bin/gcc.exe build
python tests/native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe
python tools/native_emulator.py --cc C:/msys64/ucrt64/bin/gcc.exe run --disk build/libtini.po --system LIBTINI.SYSTEM --profile vtw33 --frames 120 --screenshot build/native/diagnostic-vtw33.png
python tools/native_emulator.py --cc C:/msys64/ucrt64/bin/gcc.exe run --disk build/libtini.po --system LIBTINI.SYSTEM --profile turbo-f122 --frames 120 --screenshot build/native/diagnostic-turbo-f122.png
```

## Browser player

`tools/web.py` compiles the same machine and speech sources to WebAssembly
with an installed **Emscripten 6.0.13** (emsdk, release
`e13ee988ce3d87a738dd8f3661d02223308c412a`); it refuses other versions.
`build/web/player/build.json` records the input hashes, commands and output
hashes. `tests/web_validate.py` runs the player under the emsdk's Node 24.19.0.
The player links GPL-3.0 code, so any copy of it must offer its source. See
[the browser player](../docs/reference/browser.html).

The `vtw33` profile is functional execution at nominal 33.333333 MHz without
all hardware waits. `turbo-f122` is a historical F1.2.2 cost model, not a model
of the selected F1.3.2 firmware's complete timing. Both provide program and
memory evidence; neither establishes board speed or capture-stream behavior.
Direct launch loads the packaged SYS and uses a ProDOS MLI stand-in. The
native test injects a key and requires that stand-in to observe QUIT.

Optional full ROM boot requires separately supplied, repo-local installed
inputs under ignored `build-inputs/native-roms/`: the enhanced //e 16 KiB
system ROM, 256-byte C700 and 2048-byte C800 SmartPort firmware, and optionally
a 4096-byte video character ROM for text previews. These files are not
redistributed. The wrapper requires explicit `--rom`, `--slot7-rom` and
`--slot7-c8-rom`; it never uses the upstream helper's sibling defaults.
Text previews require `--video-rom` because the upstream fallback font asset
outside the machine's licensed snapshot is not bundled. SHR previews do not
require a character ROM. The validation run's local ROM hashes are recorded
in `build-inputs/native-roms/provenance.json` and the boot transcript.
