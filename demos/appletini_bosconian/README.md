# Appletini Bosconian

Appletini Bosconian is an original Bosconian-style shooter for an enhanced
Apple //e with an Appletini ONE card. The code is original C and 65C02
assembly (cc65/ca65) and uses no Namco code, ROM data or art.

The game runs at a locked 60 frames per second: one full logic and render
pass per vertical blank, at the virtual TransWarp 33 MHz preset or in
TURBO mode.

## Hardware used

- **Super Hi-Res video** (Appletini "VidHD-style" SHR, 320x200, 16 colors
  per line). The framebuffer lives in AUX `$2000-$9FFF`; it is enabled by
  writing `$C1` to `$C029`. The playfield is the left 256 pixels; the
  right 64 pixels are the side panel (scores, condition lamp, radar,
  round, lives, bases and diagnostics).
- **Virtual TransWarp** at the 33 MHz preset or TURBO. The game writes 0
  to `$C074` at start to release any 1 MHz lock.
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
the builder takes the boot blocks and the `PRODOS` file from it. The disk builder
is pure Python (no Java, no AppleCommander) and verifies its own image by
reading it back.

`tools/gen_assets.py` turns the text art in `assets/` into
`build/assets.s` (pre-shifted sprites, the 8x8 font and the palette) and
`build/assets.h` (sprite ids).

The linked program is the SYS file: `bosconian.cfg` links it at `$2000`
and `crt0.s` is its first byte. ProDOS loads `BOSCO.SYSTEM` at `$2000`
and jumps there. `crt0` copies the `DATA` segment to `$0C00`, clears
`BSS`, sets the cc65 software stack to `$BF00` (growing down to `$B700`,
just below the ProDOS global page; nothing else uses that space because
there is no BASIC.SYSTEM and the game opens no files) and calls `main()`.
When `main()` returns, `crt0` restores text mode and does a ProDOS `QUIT`.

Sizes from `build/BOSCO.map` (cc65 2.19, `-Oirs`): code `$2033-$82C8`
(25,238 bytes), read-only tables `$82C9-$B26A` (12,194 bytes, of which
the sprites, font and palette are 10,764), `DATA` 2 bytes and `BSS`
3,275 bytes at `$0C00-$18CC`. The SYS file is 37,485 bytes and ends at
`$B26C`; the link area ends at `$B6FF`, so about 1,170 bytes are free.
`tools/build_system.py` and `tools/build_disk.py` refuse an image that
reaches `$B700`.

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
- Joystick: push past 35% of the calibrated center to set the heading,
  diagonals included (the game calibrates on the title screen; hold the
  stick centered there)
- Space, Open Apple, Closed Apple, game buttons: fire (hold for autofire;
  two shots at once, forward and backward)
- Return (or fire): start a game from the title
- Esc, `P` or `Q`: pause during play (any of them, or Return, resumes);
  at the title Esc or `Q` quits to ProDOS and `P` does nothing

Keys are read from `$C000`; a held key keeps its direction and fire bits
active through the //e "any key down" flag at `$C010`, so holding Space
is autofire and a held direction keeps steering. The //e cannot say which
key is still down, so a held fire also survives a direction tap: you can
steer while holding Space, and firing stops once every key is up. Start,
pause and quit act once per key press.

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
active, 35 last event, 36-37 dropped frames, 38 star count, 39 joystick
status (bit 0 X axis usable, bit 1 Y axis usable). The full
layout is in `docs/DESIGN.md` section 8 and `struct Mailbox` in `bosco.h`.

## Smoke test results

`make smoke` on the reference host (GSSquared under `xvfb-run`, 33 MHz
preset): 556,272 emulated cycles per frame = 59.9 fps emulated (the wall
clock rate is lower because the host runs the emulator below real time),
RamWorks 128 banks, speed probe 37,027 iterations, both joystick axes
calibrated at the title (GSSquared reports a centered stick without a
game controller), title -> play on Return, heading changes on `L`, held
Space fires, no frame over the budget. The wall-clock rate depends on the
host: the test needs about 20 frames per second of wall time for its
6-second cadence window. A longer unattended run goes through play, dying, game over and
back to the title. The screenshots are `build/smoke_title.png` and
`build/smoke_play.png`. `tools/cheat_test.py OUT_DIR` goes further: it
marks all bases but one dead through the debug protocol, moves the ship
next to the last base and shoots its open core. On the reference host that
run reached base destroyed (+1500), ROUND CLEAR (+1000 bonus), round 2,
game over and the title with the high score kept, with at most 2,092
framebuffer bytes in any frame.

## Known limits

- Not yet run on real hardware; all timing numbers come from GSSquared.
- Joystick: the delay between paddle polls comes from the speed probe
  (`input_joy_set_delay(2*MHz+3)`, about 11 us per poll), so the 400-poll
  cap covers the full 558 timer range at 33 MHz and in TURBO. On hardware
  each `$C064/$C065` read adds a 1 MHz bus cycle to the poll, which makes
  the count smaller, not larger; the calibration still works because it
  measures the same loop. A count at the cap at calibration time marks
  the axis unusable (no paddle connected); mailbox byte 39 shows it.
- Sound writes AY data through the no-handshake port (`$C40F`/`$C48F`)
  so the SSI-263 CA1 flag is not cleared by AY traffic; phonemes advance
  on CA1 from either VIA or on a 12-frame timeout. Speech was verified
  only by the register-level unit test, not by ear.
- Speech queues up to three phrases behind the one playing; a fourth
  request while the queue is full is dropped.
- `video_set_panel_color()` only affects `panel_*` calls whose color
  argument is `$FF`; the game passes explicit colors everywhere.
- Field text is limited to 32 characters (256 px). `panel_text_small`
  (every other glyph row) is still in the video API but the game no
  longer uses it: the diagnostics corner uses the normal 8x8 font.
- Sprites wider than 32 pixels are not supported by the blitter's
  unrolled copy; the largest sprite is the 32x32 explosion.
- About 1,170 bytes of program space remain (see Build).
