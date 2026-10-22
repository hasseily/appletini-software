# Starter game

A small game to copy: a square that held WASD or arrow keys, or a
joystick, move at a fixed thirty updates a second. A joystick button plays
a tone and Q returns to ProDOS. It shows the calls a game needs first:

| Call | Purpose |
| --- | --- |
| `ti_steps_begin`, `ti_steps_due` | Fixed-rate updates from the audio driver's 100 Hz clock |
| `ti_input_held` | The key held down, for hold-to-move |
| `ti_stick_read` | Joystick directions, calibrated to the stick's own rest |
| `ti_audio_init` with `voices` 3 | The least audio work per update |
| `#pragma bss-name (push, "NEARBSS")` | State in the caller near arena, outside main memory |

It needs a Mockingboard or Phasor personality in slot 4, which supplies the
clock, and RamWorks selectors 1-3 for the canvas, display backup and the
audio driver's temporary storage loan.

## Inside this repository

[`game.json`](game.json) is its build manifest; see
[game manifests](../../docs/GAMES.md). Build the library and this game only:

```powershell
python tools/build.py --cc65-home D:/Repos/cc65 --game starter
```

Outputs are `build/starter.system` and the 140 KiB `build/starter.po`,
which boots `STARTER.SYSTEM`. The build prints the free bytes in each
memory area. To start a new game here, copy this directory under `games/`
or `examples/`, rename it in `game.json` and edit `main.c`.

## As a separate project

Materialize a new project with ordinary copies:

```powershell
python examples/starter/create.py C:/Projects/MyGame
```

The destination must not already exist. The command copies runtime source,
public headers, linker configuration and local packaging tools into that
project. `SDK_INPUTS.json` records their hashes. It copies no object files,
compiler executables, ProDOS image, sibling checkout or linked directory.
The new project remains buildable after the originating checkout is moved.
Install the documented cc65 SDK2.19 and Python, run its README commands and
edit `main.c`.

Runtime source is maintained in the main libtini source tree. Recreate a
starter to pick up SDK changes; do not patch generated copies as a substitute
for updating the SDK source.

`tests/starter_native_validate.py` boots the repository build in both
emulator profiles. It holds keys, moves the stick, checks that release
stops the square, and returns to ProDOS. Board runs remain pending.
