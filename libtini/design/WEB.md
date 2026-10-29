# Browser player

A libtini game can run in a web browser on the Appletini development
machine, compiled to WebAssembly. The page runs the 65C02 program of the game
from its disk. It is not a port of the library, so every game can use it
without changes. The timing is the timing of the emulator models.

## Build and play on this computer

Install Emscripten 6.0.13 with emsdk (see
[DEPENDENCIES.md](../tools/DEPENDENCIES.md)), and build the disk of the game
with `tools/build.py`. Then:

~~~powershell
python tools/web.py --emsdk D:/Repos/emsdk --game starfall --serve 8642
~~~

Open <http://localhost:8642/>, select a speed and press Play. The output is
`build/web/starfall/`, a directory of static files.

Serve the pages over `http://localhost` or HTTPS, because browsers permit
audio worklets and module workers only there. `--serve` serves the pages only
to this computer and sends the MIME types that browsers need.

## Launch

- By default, the player boots the whole game disk through the bundled
  enhanced //e ROM and slot-7 SmartPort firmware in `build-inputs/native-roms/`.
  Use `--boot-roms DIR` to select another directory inside libtini.
  The default path is relative to libtini, regardless of the working directory.
  Boot works as the `--boot` option of the runner does.
  The output then holds the Apple ROM and the
  ProDOS of the disk.
- With `--direct-launch`, the player loads the files of the disk, except
  PRODOS, through the ProDOS MLI stand-in of the machine and a zero-filled
  ROM, as `--disk --system` does in the runner. That output holds only the
  game.
- The MLI stand-in does not implement `ALLOC_INTERRUPT` ($40), which
  `ti_audio_init` needs. Thus STARFALL cannot start its sound there, and it
  shows "SLOT 4 AUDIO REQUIRED". Support for that call in the stand-in is a
  change to `appletini-software`.
- `--download-disk` also offers the whole game disk, with its ProDOS, as
  `<game>.po` next to the page. A boot then reads that same file.

## Publishing

STARFALL is at <https://appletini.org/demo/starfall>. The page comes from
`public/demo/starfall/` in the private `appletini-one-website` repository,
which is a copy of a `--download-disk` build. The published
package includes the Apple ROM and ProDOS.

To update the page, build again, replace that folder with
`build/web/starfall/` and run `npx wrangler deploy` in that repository, as
its README describes.

The site serves `/demo/starfall` without a trailing slash and redirects the
form with a slash. A small script at the top of the page sets its base URL to
its own directory. Thus the same files work there, on localhost and on other
hosts.

Every package contains `COPYING.txt` and `source.zip`, the Corresponding
Source of the player with its build record, which the GPL-3.0 requires.

For itch.io, add `--itch` to the build command. The tool makes
`dist/STARFALL-itch.zip` with `index.html` at its root. It includes only the
player's runtime files, boot inputs, notices and source archive. It checks
the itch.io file count, path length and extracted-size limits. Add
`--download-disk` to include the disk download too. The STARFALL ranking URL
is `https://appletini.org/leaderboards/starfall` in this package. The ranking
service must permit cross-origin GET and JSON POST requests from itch.io.
The itch.io package sets `profile` to `turbo-f122` in `game.json`. The page
selects TURBO and hides the speed selector. The Play button starts sound
through the browser's required user gesture.

## How it works

- `tools/web/player.cpp` wraps the development machine. It runs whole NTSC
  video frames (262 lines of 63.695 us, 16.688 ms) at `vtw33` (33.33 MHz) or
  at `turbo-f122`, the TURBO cost model.
- The page runs frames to keep 100 ms of audio in the queue, or by the wall
  clock without audio, at most four frames per display refresh.
- A second instance of the module mixes SSI-263 speech in a Web Worker, in
  the same way as the speech client and worker of the runner. The page
  doubles the speech output before the mix, because the hardware speech is
  louder than the speech of the reference model.
- The page mixes speech also while the sound is off, so the speech timeline
  stays complete. Samples go to the audio worklet only while the audio
  context runs.
- The audio context runs at the rate of the device, and the worklet
  interpolates from 48 kHz.
- For iOS, the page creates and resumes the audio context in the Play tap. It
  sets `navigator.audioSession.type` to `playback` where Safari has it, so
  sound plays with the silent switch on. It resumes a suspended or
  interrupted context at the next tap or key. The status line shows "tap for
  sound" while the sound is off.
- After each frame, the page decodes SHR from AUX $2000-$9FFF with the
  preview rules of the runner. It draws the screen at 640x400, the 16:10
  square-pixel shape of the Appletini. It does not model the production
  capture stream. Other video modes show black.
- Keys go to the Apple //e as a held key with any-key-down. A gamepad
  controls paddles 0 and 1 and buttons 0-2.
- Touch devices get a virtual stick (paddles 0 and 1), A and B (buttons 0 and
  1), Return and Esc keys and a Keyboard button.
- The Keyboard button focuses a hidden text field, which opens the keyboard
  of the device. Typed characters go to the Apple //e as key presses, in
  uppercase. Return and Backspace send Return and DELETE. The page sends
  composed words when the composition ends.
- The touch controls appear on a coarse pointer or at the first touch. A
  button or `?touch=1` and `?touch=0` override that. The stick overrides the
  gamepad axes while it is held, and the buttons combine.
- On a phone held upright, the controls are below the screen. On a phone
  held sideways, the screen fills the height between two columns of
  controls. The worklet conversion works at 48 kHz and at 44.1 kHz.

The player has the GPL-3.0 license, because it links the GPL-3.0 machine and
speech sources of the repository. A published copy must offer its source.

## Evidence

`tests/web_validate.py` runs a 1,100-frame STARFALL script in the player
under Node, and in the native DLL with the separate native speech worker.
The script boots, starts with the Mockingboard, moves, drops a bomb and uses
the joystick.

Every checkpoint (ticks, PC, AUX $2000-$9FFF and the decoded frame) and the
digest of the mixed PCM must match. Speech is compared at the reference gain.

~~~powershell
python tests/web_validate.py --emsdk D:/Repos/emsdk --cc C:/msys64/ucrt64/bin/gcc.exe
~~~

With the ROM boot, the two profiles match at all 9 checkpoints:

| Profile | Guest time | PCM frames | Node speed | Native harness speed |
| --- | --- | --- | --- | --- |
| `vtw33` | 18.36 s | 881,134 | 2.08x real time | 2.18x |
| `turbo-f122` | 21.96 s | 1,054,310 | 1.33x real time | 1.33x |

TURBO has little margin on a slower computer, and the page shows the live
speed. About one third of the machine time goes to the event service for
each instruction, the speech register hook included, which is machine code
from the emulator. The results are in `build/web/validation.json`.

## STARFALL leaderboard

The STARFALL manifest includes the final-state, mode and stage addresses
from its label file, the game version and the leaderboard endpoint.
`leaderboard.js` reads the final game-over state through `tw_read`. It does
not depend on the emulated ARM network service. Browser fetch uses HTTPS
at the site's origin and always submits platform `web`.

The page freezes one POST body after it gets a server run ID. A failed
reply can be retried with that same body. Starting a new game clears the
pending submission. Other games have no leaderboard metadata or panel.
After game over, N opens the browser rankings. The page waits for fullscreen
to close and for the next layout frame before it scrolls to the panel and
focuses the name field. A reset cancels a pending focus change.
Run `node tests/web_leaderboard.test.mjs` for the platform, name, snapshot
and retry checks.
