# Appletini Bosconian

Appletini Bosconian is an original Bosconian-style shooter for an enhanced
Apple //e with an Appletini ONE card. It is written from scratch in C and
65C02 assembly (cc65/ca65). No Namco code, ROM data or art is used.

The game runs at a locked 60 frames per second: one full logic and render
pass per vertical blank, at the virtual TransWarp 33 MHz preset or in
TURBO mode.

## Hardware used

- **Super Hi-Res video** (Appletini "VidHD-style" SHR, 320x200, 16 colors
  per line). The framebuffer lives in AUX `$2000-$9FFF`; it is enabled by
  writing `$C1` to `$C029`. The playfield is the left 256 pixels; the
  right 64 pixels are the side panel (scores, condition lamp, radar,
  round, lives, bases and diagnostics).
- **Virtual TransWarp** at the 33 MHz preset or TURBO. `$C074` is written
  with 0 at start to release any 1 MHz lock.
- **Virtual Phasor** in its default Mockingboard-compatible mode in slot 4:
  AY-B (`$C480`) plays the music, AY-A (`$C400`) the sound effects, and
  the SSI-263 (`$C440`) speaks the alerts ("BLAST OFF", "ALERT", "SPY SHIP
  SIGHTED", "CONDITION RED", "BATTLE STATIONS", "GAME OVER"). All sound
  chip writes happen in one burst per frame because any slot 4 access
  slows the TransWarp to 1 MHz for a while.
- **RamWorks**: probed at startup; the bank count is shown on the title
  screen and in the mailbox. It is not needed for play.
- Keyboard, Open/Closed Apple keys, game buttons and the joystick.

## Build

From this directory:

```sh
make          # build/BOSCO.SYSTEM
make disk     # dist/Appletini-Bosconian.hdv (800 KB ProDOS SmartPort image)
make test     # python unit tests in tests/ (py65 for the asm, pure python tools)
make smoke    # boot the disk in GSSquared and check it runs
```

The build needs cc65 (`cl65`, `ca65`, `ld65`) and python3. `make disk`
needs the canonical Appletini checkout at `../../../appletini-one` (or
`APPLETINI_ROOT=/path/to/appletini-one`) for `software/ProDOS_2_4_3.po`:
the boot blocks and the `PRODOS` file are taken from it. The disk builder
is pure Python (no Java, no AppleCommander) and verifies its own image by
reading it back.

`tools/gen_assets.py` turns the text art in `assets/` into
`build/assets.s` (pre-shifted sprites, the 8x8 font and the palette) and
`build/assets.h` (sprite ids).

The linked program is the SYS file: `bosconian.cfg` links it at `$2000`
and `crt0.s` is its first byte. ProDOS loads `BOSCO.SYSTEM` at `$2000`
and jumps there. `crt0` copies the `DATA` segment to `$0C00`, clears
`BSS`, sets the cc65 software stack to `$B800` (growing down to `$B000`,
below ProDOS) and calls `main()`. When `main()` returns, `crt0` restores
text mode and does a ProDOS `QUIT`.

## Run in GSSquared

```sh
GSSQUARED_ROOT="${GSSQUARED_ROOT:-../../../gssquared}"
"$GSSQUARED_ROOT/build/GSSquared" appletini-bosconian.gs2 \
  -ds7d1=dist/Appletini-Bosconian.hdv
```

`appletini-bosconian.gs2` is an enhanced //e with the Appletini card in
slot 7 (33 MHz accelerator, RamWorks) and a Mockingboard in slot 4. The
`codex/appletini-108-postprocessing` branch of GSSquared has the card.
`make smoke` starts the same command with `--debug` and drives it through
the `gs2debug` python client (`clients/python/src` in the GSSquared
checkout); on Linux without a display it runs under `xvfb-run -a` with
`SDL_AUDIODRIVER=dummy`. The smoke test writes `build/smoke_title.png`
and `build/smoke_play.png`, decoded from the AUX framebuffer by
`tools/shr2png.py`.

## Controls

The ship never stops. A direction key sets the new heading; the last
heading persists.

- Arrows or `I` `J` `K` `L`: up, left, down, right
- `U` `O` `M` `,` (or `.`): diagonals
- Joystick: push past 35% of the calibrated center to set the heading
  (calibrate on the title screen with the stick centered)
- Space, Open Apple, Closed Apple, game buttons: fire (hold for autofire;
  two shots at once, forward and backward)
- Return: start
- Esc: pause during play, quit to ProDOS at the title (`P` and `Q` do
  the same, one each)

## The write budget

At the 33 MHz preset every write to AUX `$2000-$9FFF` (the framebuffer)
is a posted 1 MHz bus write. The posted queue is 512 deep and stalls the
CPU when it is full, and one NTSC frame has about 17,000 bus cycles. The
game therefore never redraws the whole screen during play: `video_render`
erases the previous frame's sprites and stars with zeros and draws the new
ones, and every sprite row is one run of bytes written with `STA` only.
The hard budget is 10,000 AUX bytes per frame, typical frames are under
6,000. The count for the last frame and the largest count seen are in the
mailbox (`frame_writes`, `max_frame_writes`) and the smoke test fails
when either goes over 10,000. Full clears happen only on state changes
(title, round start, game over).

The same rule keeps all writable game data out of main `$0400-$0BFF` and
`$2000-$5FFF` (also posted regions): `DATA` and `BSS` run at
`$0C00-$1FFF`, code and read-only tables sit at `$2000-$AFFF` and are
never written.

While RAMWRT is on (writing AUX), no code may write main RAM above
`$01FF`: the asm video routines keep their state in zero page until
RAMWRT is off again, and C code never runs with RAMWRT on.

## Debug mailbox

The game writes a 41-byte mailbox at `$0300` once per frame. It begins
with `A13B` and exposes (offsets): 4 state, 5-6 frame counter, 7-10
score, 11 round, 12 lives, 13 condition, 14-17 player world position,
18 heading, 19 bases left, 20 enemies alive, 21 display-list count,
22-23 AUX bytes written by the last frame, 24-25 largest count this
session, 26 RamWorks banks, 27-28 speed probe, 29 current SFX, 30 music
track, 31 speech phrase, 32 input mask, 33 formation active, 34 spy
active, 35 last event, 36-37 dropped frames, 38 star count. The full
layout is in `docs/DESIGN.md` section 8 and `struct Mailbox` in `bosco.h`.
