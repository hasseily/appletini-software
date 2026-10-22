# Starter game

The starter is a small game to copy. Held WASD or arrow keys, or a joystick,
move a square at thirty updates each second. A joystick button plays a tone,
and Q goes back to ProDOS. The starter shows the calls that a game needs
first:

| Call | Purpose |
| --- | --- |
| `ti_steps_begin`, `ti_steps_due` | Fixed-rate updates from the 100 Hz clock of the audio driver |
| `ti_input_held` | The key that is held, to move while the key is down |
| `ti_stick_read` | Joystick directions, calibrated to the rest position of the stick |
| `ti_audio_init` with `voices` 3 | The minimum audio work for each update |
| `#pragma bss-name (push, "NEARBSS")` | State in the caller near arena, outside main memory |

The starter needs a Mockingboard or Phasor personality in slot 4, which
supplies the clock. It also needs RamWorks selectors 1-3 for the canvas, the
display backup and the temporary storage loan of the audio driver.

## In this repository

[`game.json`](game.json) is the build manifest of the starter; see
[builds and game manifests](../../docs/reference/build.html). The
[examples page](../../docs/examples.html#starter) explains `main.c`. To build
the library and this game only:

```powershell
python tools/build.py --cc65-home D:/Repos/cc65 --game starter
```

The outputs are `build/starter.system` and the 140 KiB `build/starter.po`,
which boots `STARTER.SYSTEM`. The build shows the free bytes in each memory
area. To start a new game here, copy this folder to `games/` or `examples/`,
change the name in `game.json` and edit `main.c`.

## As a separate project

To make a new project with ordinary copies:

```powershell
python examples/starter/create.py C:/Projects/MyGame
```

The destination must not exist. The command copies the runtime source, the
public headers, the linker configuration and the local packaging tools into
the project. `SDK_INPUTS.json` records their hashes. The command copies no
object files, compiler executables, ProDOS image, sibling checkout or linked
folder. You can build the new project when the original checkout is at a
different location or is not available.

Install cc65 SDK 2.19 and Python, run the commands in the README of the
project and edit `main.c`.

The main libtini source tree contains the runtime source. To get SDK changes,
make a new starter. Do not change the copies instead of the SDK source.

`tests/starter_native_validate.py` boots the build in the two emulator
profiles. It holds keys, moves the stick, checks that the square stops when
the keys are released, and goes back to ProDOS.
