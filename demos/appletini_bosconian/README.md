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

Sizes from `build/BOSCO.map` (cc65 2.19, `-Oirs`): code `$2033-$7F51`
(24,351 bytes), read-only tables `$7F52-$AEA9` (12,120 bytes, of which
the sprites, font and palette are 10,690), `DATA` 2 bytes and `BSS`
2,668 bytes at `$0C00-$166D`. The SYS file is 36,524 bytes and ends at
`$AEAB`; the link area ends at `$AFFF`, so about 340 bytes are free.
Any growth must come out of the sprite art or the C code (the software
stack at `$B000-$B7FF` and ProDOS above it stay where they are).

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
- Return (or fire): start a game from the title
- Esc, `P` or `Q`: pause during play (any of them, or Return, resumes);
  at the title all three quit to ProDOS

Keys are read from `$C000`; a held key keeps its direction and fire bits
active through the //e "any key down" flag at `$C010`, so holding Space
is autofire and a held direction keeps steering. Start, pause and quit
act once per key press.

## The write budget

At the 33 MHz preset every write to AUX `$2000-$9FFF` (the framebuffer)
is a posted 1 MHz bus write. The posted queue is 512 deep and stalls the
CPU when it is full, and one NTSC frame has about 17,000 bus cycles. The
game therefore never redraws the whole screen during play: `video_render`
erases the previous frame's sprites and stars with zeros and draws the new
ones, and every sprite row is one run of bytes written with `STA` only.
The hard budget is 10,000 AUX bytes per frame. Measured in GSSquared:
the title screen writes about 210 bytes per frame, a busy play frame
300-1,000, and the largest frame seen in a 3,000-frame session (deaths
and explosions included) was 2,350. The count for the last frame and the
largest count seen are in the mailbox (`frame_writes`,
`max_frame_writes`) and the smoke test fails when either goes over
10,000. `dropped_frames` in the mailbox counts frames over the budget
(there is no timer to detect real VBL overruns). Full clears happen only
on state changes (title, round start, game over).

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

## Smoke test results

`make smoke` on the reference host (GSSquared under `xvfb-run`, 33 MHz
preset): 556,272 emulated cycles per frame = 59.9 fps emulated (the wall
clock rate is lower because the host runs the emulator below real time),
RamWorks 128 banks, speed probe 37,027 iterations, title -> play on
Return, heading changes on `L`, held Space fires, no frame over the
budget. A longer unattended run goes through play, dying, game over and
back to the title. The screenshots are `build/smoke_title.png` and
`build/smoke_play.png`.

## Known limits

- Not yet run on real hardware; all timing numbers come from GSSquared.
- Joystick: at the 33 MHz preset with the virtual TransWarp "slow
  paddles" option off, the 400-poll cap in `input.s` can be shorter than
  a centered stick's timer. The driver then marks that axis unusable
  (keyboard still works). Raise `JOY_DELAY` in `input.s` or turn on the
  paddle slowdown if joystick play on hardware matters.
- Sound writes AY data through the no-handshake port (`$C40F`/`$C48F`)
  so the SSI-263 CA1 flag is not cleared by AY traffic; phonemes advance
  on CA1 from either VIA or on a 12-frame timeout. Speech was verified
  only by the register-level unit test, not by ear.
- The sound module switches BLAST OFF to the ambient track on its own
  after 90 frames; `main.c` also asks for it at 150 frames, which is
  harmless.
- `video_set_panel_color()` only affects `panel_*` calls whose color
  argument is `$FF`; the game passes explicit colors everywhere.
- Field text is limited to 32 characters (256 px); the small panel text
  (`panel_text_small`) draws every other glyph row and is meant for the
  diagnostics corner only.
- Sprites wider than 32 pixels are not supported by the blitter's
  unrolled copy; the largest sprite is the 32x32 explosion.
- About 340 bytes of program space remain (see Build).
