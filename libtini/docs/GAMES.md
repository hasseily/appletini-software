# Building a game

A game is a directory under `games/` or `examples/` that holds a
`game.json` manifest beside its sources. `tools/build.py` reads every
manifest, so adding a game needs no change to the SDK's build script.
[`examples/starter`](../examples/starter/README.md) is a small one to copy;
[`examples/starfall`](../examples/starfall/README.md) is a complete one.

## Manifest

```json
{
  "name": "starfall",
  "title": "STARFALL",
  "sources": ["main.c", "game.c"],
  "config": "cfg/game.cfg",
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
  "disk": {"volume": "STARFALL", "system": "STARFALL.SYSTEM", "blocks": 1600}
}
```

| Key | Meaning |
| --- | --- |
| `name` | Required. 1-15 lowercase letters, digits or `_`; outputs are `build/<name>.system`, `.po`, `.map`, `.lbl` and `.dbg` |
| `title` | Shown in the build summary; defaults to the name |
| `sources` | Required. C files relative to the manifest; the first defines `main` |
| `assembly` | ca65 files relative to the manifest |
| `config` | Linker layout relative to the repository; default `cfg/libtini.cfg` |
| `cflags` | Extra cc65 options, such as `--static-locals` for foreground-only code |
| `private` | `false` leaves the game out of `--private` builds, which add the optional AMEM transport; default `true` |
| `generate` | Commands run before compiling, in order. A command ending in `.py` runs with the build's Python. `inputs` are hashed into `build/manifest.json`; a directory counts every file under it. `outputs` are recorded as build outputs |
| `disk` | A bootable ProDOS image: `volume`, `system` file name (default `NAME.SYSTEM`), `blocks` (default 1600) and `files` |

In `generate`, `{root}`, `{game}` and `{build}` expand to the repository,
the manifest's directory and the build directory. Other relative paths in
`inputs`, `outputs` and disk files are relative to the manifest. The build
directory and the game's own directory are on the include path.

Each entry in `disk.files` has a `name` and at most one source. `path` copies
a file, `program` adds another linked SDK or game program such as
`libtini`, and neither makes an empty file. Files default to ProDOS type
$06, programs to $FF with aux type $2000; `type` and `aux` override them.

## Building one game

```powershell
python tools/build.py --cc65-home D:/Repos/cc65 --game starter
```

`--game NAME` builds the library, the diagnostic, that game and any program
its disk lists. Every build ends with one memory line per game:

```text
starfall memory: LOW $0800-$1FFF 88 free; IMAGE $2000-$BEFF 1032 free; WORK $A26C-$B3FF 1110 free; NEAR $B480-$B6FF 1 free
```

Each entry is a linker memory area. `build/memory.json` holds the same
figures, with used bytes, for every linked program. When a segment does not
fit, the build stops with the shortfall, for example
`starfall does not fit: segment BSS needs 50 more bytes in memory area WORK`.

## Layouts

| | `cfg/libtini.cfg` | `cfg/game.cfg` |
| --- | --- | --- |
| Code, data and BSS | MAIN $2000-$9FFF | IMAGE from $2000; BSS in WORK, up to $AEFF |
| Constants | With the code | RODATA, AMEMCODE and LOWCODE run in LOW, $0800-$1FFF |
| C stack | $A000-$A7FF | $B700-$BEFF |
| Near arena (`NEARBSS`) | NEAR $A900-$AEFF, 1536 bytes | NEAR $B480-$B6FF, 640 bytes |

`cfg/game.cfg` gives a larger game more main memory. Its startup copies the
low segments into place once. Entry code that runs once sits in ONCE, which
that layout places under BSS, so clearing BSS reclaims those bytes. See the
[memory map](MEMORY_MAP.md).

A game can bring its own layout, a copy of either one, and give itself what
it does not use from the library. File calls need the 1 KiB ProDOS buffer at
`_ti_file_buffer`, $B000 in both shared layouts. STARFALL makes no file
calls, so [`examples/starfall/starfall.cfg`](../examples/starfall/starfall.cfg)
leaves the symbol out and moves the end of WORK and of public near memory,
`_ti_memory_end`, from $AF00 to $B400: the guard page and the buffer become
1,280 bytes of the game's own. Linking a file call with that layout then
fails on the missing symbol instead of letting ProDOS write over the game.

Variables declared in the `NEARBSS` segment live in the caller near arena,
outside main memory:

```c
#pragma bss-name (push, "NEARBSS")
static uint8_t level[512];
#pragma bss-name (pop)
```

Startup zeroes them like BSS, and the linker rejects more than the arena
holds. Near APIs accept pointers into it. Nothing else in libtini uses the
arena.

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

- `ti_steps_due` returns the updates due since the last call, at most the
  maximum given to `ti_steps_begin`; the rest of a step carries over. More
  than a second between calls returns `TI_STEPS_GAP` and restarts timing.
  It keeps the clock's low 16 bits, so call `ti_steps_reset` after a pause
  that may exceed 65535 ticks.
- `ti_input_held` returns the newest key while any key is down, or 0. The
  //e reports only that one key.
- `ti_stick_read` returns `TI_STICK_UP`, `DOWN`, `LEFT` and `RIGHT` bits,
  calibrated to the stick's own rest, or `TI_STICK_ABSENT`. Call
  `ti_stick_recalibrate` when the stick should be untouched, such as at a
  new run.
- `voices` in `ti_audio_config` limits the driver to the voices a game
  uses, rounded up to whole AY chips of three. Each update then serves only
  those chips. 0 uses all six Mockingboard or twelve Phasor voices.
- `draw` can list the frame's sprites in a
  [sprite scene](GRAPHICS.md#sprite-scenes), which redraws only the blocks
  that changed. Its `service` function can call `ti_audio_update` so a long
  draw does not starve the music.

[Audio and input](AUDIO.md) has the details and limits of each call.

## Status text, effects, errors and timing

- `ti_gfx_text_opaque` replaces a HUD value in place. It fills each 6x8 cell
  with the background, so a value of the same length covers the old one.
  Publish only its cells, `6 * length` by 8 pixels. `ti_digits` writes a
  fixed number of zero-padded digits for it.
- `ti_audio_effect_voice(n)` returns the nth voice the music reservation
  leaves, so one effect table suits six Mockingboard and twelve Phasor
  voices.
- Wrap calls in `ti_error_keep` and test `ti_error_first` once a frame
  instead of after each call.
- `tools/profiler.py --game NAME` times named functions, static ones too,
  while the game runs on the native machine; see
  [benchmarks](BENCHMARKS.md#profiling-a-game).
