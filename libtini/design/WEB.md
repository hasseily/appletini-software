# Browser player

A libtini game can run in a web browser on the Appletini development machine,
compiled to WebAssembly. The page runs the game's own 65C02 program from its
disk. It is not a port of the library, so every game gets it without changes.
This is an emulator: its timing is a model, and only board tests establish
real timing and output.

## Build and play on this computer

Install Emscripten 6.0.13 with emsdk (see [dependencies](../tools/DEPENDENCIES.md))
and build the game's disk with `tools/build.py`. Then:

~~~powershell
python tools/web.py --emsdk D:/Repos/emsdk --game starfall --boot-roms build-inputs/native-roms --serve 8642
~~~

Open <http://localhost:8642/>, choose a speed and press Play. The output is
`build/web/starfall/`, a directory of static files. Pages must be served over
`http://localhost` or HTTPS, because browsers allow audio worklets and module
workers only there. `--serve` serves only to this computer and sends the MIME
types browsers require.

## Launch

- With `--boot-roms`, the player boots the whole game disk through the
  installed enhanced //e ROM and slot-7 SmartPort firmware, as the runner's
  `--boot` does. The output then holds the Apple ROM and the disk's ProDOS.
- Without it, the player loads the disk's files, except PRODOS, through the
  machine's ProDOS MLI stand-in and a zero-filled ROM, as the runner's
  `--disk --system` does. That output holds only the game. STARFALL cannot
  start its sound there: `ti_audio_init` needs MLI `ALLOC_INTERRUPT` ($40),
  which the stand-in does not implement, so the game reports "SLOT 4 AUDIO
  REQUIRED". Supporting that call in the stand-in is a change to
  `appletini-software`.
- `--download-disk` also offers the whole game disk, with its ProDOS, as
  `<game>.po` beside the page; a boot then reads that same file.

## Publishing

STARFALL is published at <https://appletini.org/demo/starfall>, from the
private `appletini-one-website` repository's `public/demo/starfall/`, a copy
of a `--boot-roms --download-disk` build. The owner allowed publishing the
Apple ROM and ProDOS in this package on 2026-10-22. To update it, rebuild,
replace that folder with `build/web/starfall/` and run `npx wrangler deploy`
in that repository, as its README describes.

The site serves `/demo/starfall` without a trailing slash and redirects the
slashed form. A small script at the top of the page sets its base URL to its
own directory, so the same files work there, on localhost and on other hosts.
Every package carries `COPYING.txt` and `source.zip`, the player's
Corresponding Source with its build record, which the GPL-3.0 requires.

## How it works

- `tools/web/player.cpp` wraps the development machine. It runs whole NTSC video
  frames (262 lines of 63.695 us, 16.688 ms) at `vtw33` (33.33 MHz) or
  `turbo-f122` (the historical F1.2.2 TURBO cost model).
- The page runs frames to keep 100 ms of audio queued, or by the wall clock
  without audio, at most four frames per display refresh.
- A second instance of the module mixes SSI-263 speech in a Web Worker,
  following the runner's speech client and worker exactly. The page doubles
  the speech output before mixing, because the board's speech is louder than
  the reference model's. Speech is mixed even while sound is off, so its
  timeline stays whole; samples reach the audio worklet only while the audio
  context runs.
- The audio context runs at the device's rate, and the worklet interpolates
  from 48 kHz. For iOS, the page creates and resumes the context inside the
  Play tap, sets `navigator.audioSession.type` to `playback` where Safari
  offers it, so sound plays with the silent switch on, and resumes a
  suspended or interrupted context on the next tap or key. The status line
  shows "tap for sound" while sound is off.
- After each frame the page decodes SHR from AUX $2000-$9FFF with the runner's
  preview rules and draws it at 640x400, the Appletini's 16:10 square-pixel
  shape. It does not model the production capture stream. Other video modes
  show black.
- Keys go to the Apple //e as a held key with any-key-down. A gamepad drives
  paddles 0 and 1 and buttons 0-2.
- Touch devices get a virtual stick (paddles 0 and 1), A and B (buttons 0 and
  1), Return and Esc keys and a Keyboard button. Keyboard focuses a hidden
  text field, which opens the device's keyboard; typed characters reach the
  Apple //e as key presses, uppercase, and Return and Backspace send Return
  and DELETE. Composed words are sent when the composition ends. They appear on a coarse pointer or the first
  touch; a button or `?touch=1` / `?touch=0` overrides that. The stick
  overrides the gamepad axes while held, and buttons combine. Held upright, the
  controls sit under the screen; held sideways on a phone, the screen fills the
  height between two control columns. Headless Edge with phone emulation and
  touch events launched STARFALL with A, moved the ship with the stick and
  paused it by typing P at 360x780, 390x844 and 844x390, with sound running.
  The worklet's conversion was checked at 48 and 44.1 kHz outside a browser.
  On 2026-10-22 the owner reported that the published demo, with sound and
  these controls, works well on an iPhone.

The player is licensed GPL-3.0 because it links the repository's GPL-3.0 machine
and speech sources. A published copy must offer its source.

## Evidence

`tests/web_validate.py` runs a 1,100-frame STARFALL script in the player under
Node and in the native DLL with the separate native speech worker. The script
boots, launches with the Mockingboard, moves, drops a bomb and uses the
joystick. Every checkpoint (ticks, PC, AUX $2000-$9FFF, decoded frame) and the
mixed PCM digest must match; speech is compared at the reference gain.

~~~powershell
python tests/web_validate.py --emsdk D:/Repos/emsdk --cc C:/msys64/ucrt64/bin/gcc.exe --boot-roms build-inputs/native-roms
~~~

On 2026-10-22, with the ROM boot, both profiles matched at all 9 checkpoints:

| Profile | Guest time | PCM frames | Node speed | Native harness speed |
| --- | --- | --- | --- | --- |
| `vtw33` | 18.36 s | 881,134 | 2.08x real time | 2.18x |
| `turbo-f122` | 21.96 s | 1,054,310 | 1.33x real time | 1.33x |

The MLI stand-in launch also matched at both profiles before STARFALL's
volume change. Earlier TURBO runs reached 1.10-1.20x, so TURBO has little
margin on a slower computer; the page shows the live speed. About a third of
the machine's time goes to per-instruction event service, including the speech
register hook, which is upstream machine code. The results are in
`build/web/validation.json`. No browser or board timing is claimed.
