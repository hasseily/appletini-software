# Building a game

A game is a directory under `games/` or `examples/`. It holds a `game.json`
manifest next to its sources. `tools/build.py` reads every manifest, so a new
game needs no change to the build script of the SDK.
[`examples/starter`](../examples/starter/README.md) is a small game to copy.
[`examples/starfall`](../examples/starfall/README.md) is a complete game.

## Manifest

```json
{
  "name": "starfall",
  "title": "STARFALL",
  "sources": ["main.c", "game.c", "boss.c"],
  "config": "examples/starfall/starfall.cfg",
  "private": false,
  "cflags": ["--static-locals"],
  "generate": [
    {
      "command": ["{root}/tools/speech.py", "{game}/speech.json", "--output", "{build}/starfall_speech.h",
                  "--symbol", "sf_speech", "--no-numbers"],
      "inputs": ["{root}/tools/speech.py", "speech.json"],
      "outputs": ["{build}/starfall_speech.h"]
    }
  ],
  "package": [
    {
      "command": ["{root}/tools/starfall_pack.py", "--labels", "{build}/starfall.lbl",
                  "--output", "{build}/starfall.pak", "TITLE={build}/starfall.system.tit"],
      "inputs": ["{root}/tools/starfall_pack.py", "{root}/tools/assets.py"],
      "outputs": ["{build}/starfall.pak"]
    }
  ],
  "disk": {"volume": "STARFALL", "system": "STARFALL.SYSTEM", "blocks": 1600,
           "files": [{"name": "STARFALL.PAK", "path": "{build}/starfall.pak"}]}
}
```

| Key | Meaning |
| --- | --- |
| `name` | Required. 1-15 lowercase letters, digits or `_`. The outputs are `build/<name>.system`, `.po`, `.map`, `.lbl` and `.dbg` |
| `title` | The name in the build summary. The default is the name |
| `sources` | Required. C files, relative to the manifest. The first file defines `main` |
| `assembly` | ca65 files, relative to the manifest |
| `config` | The linker layout, relative to the libtini folder. The default is `cfg/libtini.cfg` |
| `cflags` | More cc65 options, for example `--static-locals` for foreground-only code |
| `private` | `false` removes the game from `--private` builds, which add the optional AMEM transport. The default is `true` |
| `generate` | Commands that run before compilation, in order. A command that ends in `.py` runs with the Python of the build. The build records the hashes of the `inputs` in `build/manifest.json`; a directory counts every file under it. The build records the `outputs` as build outputs |
| `package` | Commands that run after the link and before the disk, in order, with the same keys as `generate`. They can use the program, its label file and the overlay files of its layout |
| `disk` | A bootable ProDOS image: `volume`, the `system` file name (default `NAME.SYSTEM`), `blocks` (default 1600) and `files` |

In `generate` and `package`, `{root}`, `{game}` and `{build}` expand to the libtini folder,
the directory of the manifest and the build directory. Other relative paths
in `inputs`, `outputs` and disk files are relative to the manifest. The build
directory and the game directory are on the include path.

Each entry in `disk.files` has a `name` and at most one source. `path` copies
a file. `program` adds another linked SDK or game program, for example
`libtini`. An entry without a source makes an empty file. Files have the
ProDOS type $06 by default. Programs have the type $FF and the aux type
$2000. `type` and `aux` override these values.

## Building one game

```powershell
python tools/build.py --cc65-home D:/Repos/cc65 --game starter
```

`--game NAME` builds the library, the diagnostic, that game and all programs
that its disk lists. Each build ends with one memory line for each game:

```text
starfall memory: LOW $0800-$1FFF 8 free; IMAGE $2000-$AC2F 5646 free; BOSS $9622-$AC2F 3013 free; FILES $9622-$AC2F 2741 free; PANELS $9622-$AC2F 4762 free; PLAY $9622-$AC2F 4821 free; TITLE $9622-$AC2F 2564 free; TAIL $A17B-$BEFF 1193 free; WORK $AC30-$BA7F 10 free; NEAR $BB00-$BDFF 9 free
```

Each entry is a linker memory area. `build/memory.json` holds the same
figures, with the used bytes, for every linked program. When a segment does
not fit, the build stops and shows the shortfall, for example
`starfall does not fit: segment BSS needs 50 more bytes in memory area WORK`.

## Layouts

| | `cfg/libtini.cfg` | `cfg/game.cfg` |
| --- | --- | --- |
| Code, data and BSS | MAIN $2000-$9FFF | IMAGE from $2000; BSS in WORK, up to $AEFF |
| Constants | With the code | RODATA, AMEMCODE and LOWCODE run in LOW, $0800-$1FFF |
| C stack | $A000-$A7FF | $B700-$BEFF |
| Near arena (`NEARBSS`) | NEAR $A900-$AEFF, 1536 bytes | NEAR $B480-$B6FF, 640 bytes |

`cfg/game.cfg` gives a larger game more main memory. Its startup copies the
low segments into place once. The entry code that runs once is in ONCE, and
this layout puts ONCE where BSS starts. Thus the BSS clear gets those bytes
back. See [MEMORY_MAP.md](MEMORY_MAP.md).

A game can use its own layout, a copy of one of the two, and keep the memory
that it does not use from the library. File calls need the 1 KiB ProDOS
buffer at `_ti_file_buffer`, which is $B000 in the two shared layouts. A
layout that leaves the symbol out gets that memory, and a file call does not
link.

Two library segments hold code that most games use only while they start:

| Segment | Contents |
| --- | --- |
| `TISETUP` | `ti_gfx_surface_create`, `ti_gfx_begin` and its AUX0 backup, `ti_audio_init`, `ti_speech_bind` and `ti_steps_begin` |
| `TIFILES` | All file and pack calls, and the MLI adapter |

The two shared layouts put them with the code. A game layout can put them in
an overlay window instead, if the game does not call them after that window
holds other code. `ti_init` is not in `TISETUP`: a game calls it before it
can load anything.

### Overlays

The 65C02 cannot run code from a RamWorks bank. With RAMRD on, all reads in
$0200-$BFFF come from the bank, also the C stack and the game's variables.
Thus a game that keeps code in banks copies it to a main-memory window and
runs it there. In an ld65 layout, each overlay is a memory area at the window
address with a file of its own, `file = "%O.ext"`. The build writes these
files next to the program, and a `package` step can put them in a resource
pack. The game loads the pack into a bank with `ti_pack_load` and copies an
overlay to the window with `ti_res_read` before it calls the overlay's code.

The window must be in public near memory, after `_ti_writable_start`.
Variables of overlay code with `--static-locals` can be in a BSS segment of
the overlay's memory area. They do not start at zero.

STARFALL uses this design. Its layout,
[`examples/starfall/starfall.cfg`](../examples/starfall/starfall.cfg), has a
window after the resident code and five overlays: the title screen and launch
with `TISETUP`, the pause and game-over panels, the wave code of normal
sectors, and the boss code with the art of one boss. At load time the window
holds `TIFILES` and the loader. Its file buffer is the scene storage, which
is idle until `ti_scene_begin`. See
[MEMORY_MAP.md](MEMORY_MAP.md#starfall).

Variables in the `NEARBSS` segment are in the caller near arena, outside the
main memory area:

```c
#pragma bss-name (push, "NEARBSS")
static uint8_t level[512];
#pragma bss-name (pop)
```

Startup zeroes them like BSS, and the linker rejects more than the arena
holds. Near APIs accept pointers into the arena. No other part of libtini
uses the arena.

## A fixed-rate loop

```c
ti_audio_config audio = {TI_AUDIO_MOCKINGBOARD, 0, 0, 0, 3};
ti_audio_init(&audio);
ti_steps_begin(ti_audio_ticks, TI_AUDIO_TICKS_PER_SECOND, 30, 30);
for (;;) {
    ti_audio_update();
    ti_input_poll();
    steps = ti_steps_due();
    if (steps == TI_STEPS_GAP) { /* pause, then ti_steps_reset() */ continue; }
    if (!steps) continue;
    directions = ti_stick_read(0);
    key = ti_input_held();
    while (steps--) update_game(directions, key);
    draw();
}
```

- `ti_steps_due` returns the updates that are due since the last call, at
  most the maximum given to `ti_steps_begin`. The rest of a step stays for
  the next call. More than one second between calls returns `TI_STEPS_GAP`
  and starts the timing again. The call keeps only the low 16 bits of the
  clock. Call `ti_steps_reset` after a pause that can be longer than 65535
  ticks.
- `ti_input_held` returns the newest key while any key is down, or 0. The
  //e reports only that one key.
- `ti_stick_read` returns the `TI_STICK_UP`, `DOWN`, `LEFT` and `RIGHT` bits,
  calibrated to the rest position of the stick, or `TI_STICK_ABSENT`. Call
  `ti_stick_recalibrate` when nobody touches the stick, for example at the
  start of a run.
- `voices` in `ti_audio_config` limits the driver to the voices of the game,
  rounded up to whole AY chips of three. Each update then writes only those
  chips. 0 uses all six Mockingboard voices or all twelve Phasor voices.
- `draw` can list the sprites of the frame in a
  [sprite scene](GRAPHICS.md#sprite-scenes), which draws again only the
  changed blocks. Its `service` function can call `ti_audio_update`, so
  the music continues during a long draw.

[AUDIO.md](AUDIO.md) gives the details and limits of each call.

## Status text, effects, errors and timing

- `ti_gfx_text_opaque` replaces a HUD value in place. It fills each 6x8 cell
  with the background, so a value of the same length covers the old value.
  Publish only its cells, `6 * length` by 8 pixels. `ti_digits` writes a
  fixed number of zero-padded digits for it.
- `ti_audio_effect_voice(n)` returns the voice number of the nth voice that
  the music reservation leaves. Thus one effect table works with six
  Mockingboard voices and with twelve Phasor voices.
- Wrap calls in `ti_error_keep` and test `ti_error_first` once a frame. Then
  it is not necessary to test each call.
- `tools/profiler.py --game NAME` measures named functions, static functions
  included, while the game runs on the native machine. See
  [BENCHMARKS.md](BENCHMARKS.md#profiling-a-game).
