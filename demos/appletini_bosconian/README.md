# Appletini Bosconian

An original Bosconian-style shooter for an enhanced Apple //e with an
Appletini ONE card, in Super Hi-Res at 60 frames per second. It needs the
vTW accelerator (33 MHz or TURBO) and the Phasor in slot 4; RamWorks memory
is probed and reported but not needed. The code is original C and 65C02
assembly (cc65/ca65) and uses no Namco code, ROM data or art.

Status: builds, passes its unit tests, and plays in GSSquared and in the
project's py65 test machine. It is **not yet tested on hardware**.

## What the game does

You fly a ship that never stops, fire forward and backward at once, and
clear a 1536x1536 wrapping map of six to eight enemy bases (six cannon pods
around a core that opens and fires homing missiles). Asteroids and mines
litter the field; interceptors and formations home in on you; a spy ship
escalates the condition from GREEN to YELLOW to RED. The side panel shows
the scores, the condition lamp, a radar, the round, lives and the bases
left. The rules are in `docs/DESIGN.md` section 10.

## Video

- SHR 320x200, 16 colours, 4 bits for each pixel, framebuffer in AUX
  `$2000-$9FFF`, selected with `$C1` at `$C029`. Playfield 256x200 on the
  left, 64-pixel panel on the right.
- Every sprite is stored twice (even and odd pixel phase) as one run of
  bytes per row, so a row is drawn with `STA` only: AUX cannot be read while
  code runs from main memory. `tools/gen_assets.py` makes them from the text
  art in `assets/`.
- Each frame erases the previous frame's sprites and stars with zeros and
  draws the new ones. Nothing is cleared during play. A typical frame
  writes 300-1,000 bytes; the largest frame seen in scripted play wrote
  2,350.

### Video timing

The Appletini publishes the SHR shadow at line 0. `video_wait_vbl` returns
right after that line, and the whole frame (input, logic, the render burst,
the panel, the sound I/O) runs before the next line 0, so a published frame
is always complete. This is the timing of the Bilestoad SHR port
(`demos/bilestoad`, branch `bilestoad-shr-port`).

Under the vTW at 33 MHz, every write to AUX `$2000-$9FFF` (and to main
`$0400-$0BFF` and `$2000-$5FFF`) is a posted 1 MHz bus write; one frame
holds about 16,000 of them and the 512-deep queue stalls the CPU when it is
full. So the game keeps its variables out of those main ranges (`DATA` and
`BSS` run at `$0C00-$1FFF`) and its framebuffer traffic small. The mailbox
reports the bytes written by the last frame and the largest count seen.

## Sound

The Phasor is switched to its native mode (four AY chips, 12 voices) with a
probe for the second chip behind each VIA; a Mockingboard, or the card
locked to Mockingboard mode, gives two chips. The rules come from
`appletini-one/hdl/apple/mockingboard.sv` and the Bilestoad driver: VIA-A
at `$C41x`, VIA-B at `$C48x`, ORB bits 4 and 3 select the chips, and the
PSG clock is doubled in native mode (every period is doubled).

- Chips 2 and 3: music. Title loop, blast-off fanfare, the engine pulse
  that follows the condition, round clear, death and game over; the second
  chip adds a detuned lead, the chord root and a noise hit on every step.
- Chips 0 and 1: up to six sound effects with priorities.
- SSI-263 speech: BLAST OFF, ALERT ALERT, SPY SHIP SIGHTED, CONDITION RED,
  BATTLE STATIONS, GAME OVER. Up to three phrases queue.

All slot 4 accesses happen in one burst per frame (`sound_update`),
because any access to that slot slows the vTW to 1 MHz for a while.
Registers go through shadows, so a quiet frame costs no bus cycles.

## Memory

| Range | Use |
|---|---|
| main `$0020-$007F` | asm zero page (video, sound, input) |
| main `$0080-$009F` | cc65 zero page |
| main `$0300-$0328` | debug mailbox |
| main `$0C00-$1FFF` | `DATA` and `BSS` (not mirrored to the bus) |
| main `$2000-$BAFF` | `BOSCO.SYSTEM`: code, sprites, font, tables |
| main `$BB00-$BEFF` | cc65 software stack |
| aux `$2000-$9FFF` | SHR pixels, SCBs, palette |

`crt0.s` is the first byte of the SYS file: it clears `$03F4` (so
CTRL-RESET restarts the machine), copies `DATA`, clears `BSS`, sets the
stack and calls `main()`. Sizes are in `build/BOSCO.map`;
`tools/build_system.py` and `tools/build_disk.py` refuse an image that
reaches `$BB00`.

## Build

```sh
make          # build/BOSCO.SYSTEM
make disk     # dist/Appletini-Bosconian.hdv, an 800 KB ProDOS image
make test     # unit tests in tests/ (py65 for the asm and the sound driver)
```

Needs cc65 (`cl65`, `ca65`, `ld65`) and Python 3 (Pillow only for the
sprite preview and the test-machine screenshots). `PRODOS` and the boot
blocks come from `../../../appletini-one/software/ProDOS_2_4_3.po`
(`APPLETINI_ROOT` to point elsewhere). The image writer is Python; no Java.

## Test

`tools/a2sim.py` is the Bilestoad port's small //e model on py65 (auxiliary
memory, RamWorks, VBL, keyboard, buttons and paddles, a Phasor that follows
the HDL's select rules, SHR rendering). Two scripts use it:

```sh
make measure   # tools/measure_frames.py: CPU cycles and bus bytes per frame
make profile   # the same with a -g build: cycles charged to routines
```

`measure_frames.py` skips the ProDOS loader and the idle time in the VBL
wait, starts a game, leaves one base alive, moves the ship next to it and
shoots the open core, and reports for each frame the CPU cycles of work,
the bytes that would use the 1 MHz bus and the `$Cxxx` accesses.

Measured at a modelled 33 MHz (one frame = 561,990 CPU cycles and about
16,000 bytes on the 1 MHz bus), over the play frames of that script:

| | median | 99 % | maximum |
|---|---:|---:|---:|
| CPU work for each frame (cycles) | 173,305 | 351,522 | 1,158,154 |
| Bytes on the 1 MHz bus for each frame | 336 | 2,114 | 27,594 |
| `$Cxxx` accesses for each frame | 14 | 141 | 169 |

568 play frames of a 900-frame run that reached a base kill, ROUND CLEAR
and round 2. Two frames went over the budget, both state changes: the
round start (world layout plus the 25,600-byte playfield clear) and the
round clear screen. They cost one or two extra video frames each. No play
frame did. The profile (`make profile`) charges the play frames mostly to
cc65's argument passing (`pushax` and friends, about a quarter), the
joystick poll (`@wait`, 11k cycles per frame with one axis every fourth
frame), the field-object pass, the stars, the display-list sort and the
sound register flush; the SHR blitter itself is under 25k cycles. In TURBO
the bus column is free and only the CPU column counts.

`make smoke` boots the disk in GSSquared through its debug protocol and
checks the frame cadence, the state changes, keys, the write budget and
the joystick calibration; it writes `build/smoke_title.png` and
`build/smoke_play.png`. `tools/cheat_test.py OUT_DIR` does the base-kill
script in GSSquared and reached base destroyed (+1500), ROUND CLEAR
(+1000), round 2 and game over.

## Run in GSSquared

```sh
GSSQUARED_ROOT="${GSSQUARED_ROOT:-../../../gssquared}"
"$GSSQUARED_ROOT/build/GSSquared" appletini-bosconian.gs2 \
  -ds7d1=dist/Appletini-Bosconian.hdv
```

`appletini-bosconian.gs2` is an enhanced //e with the Appletini card in
slot 7 (33 MHz accelerator, RamWorks) and a Mockingboard in slot 4; use a
GSSquared build with the `appletini` card (branch
`codex/appletini-108-postprocessing`). GSSquared has no Phasor native mode,
so the driver finds a Mockingboard there and plays on two chips.

## Controls

The ship never stops; a direction key sets the new heading.

- Arrows or `I` `J` `K` `L`: up, left, down, right; `U` `O` `M` `,`: diagonals
- Joystick: push past 35% of the calibrated centre (calibrated on the title
  screen, stick centred); one axis is read every fourth frame
- Space, Open Apple, Closed Apple, game buttons: fire (hold for autofire)
- Return or fire: start; Esc, `P` or `Q`: pause (any of them resumes);
  at the title Esc or `Q` quits to ProDOS

A held key keeps its bits through the //e "any key down" flag, and a held
fire survives a direction tap (the //e cannot say which key is still
down), so you can steer while holding Space.

## Debug mailbox

41 bytes at `$0300`, written once per frame, starting with `A13B`:
state, frame counter, score, round, lives, condition, position, heading,
bases and enemies left, display-list size, framebuffer bytes written (last
and largest), RamWorks banks, speed probe, sound and speech state, input,
events, budget overruns, joystick status and sound chips (4 or 2). The
layout is `struct Mailbox` in `bosco.h` and `docs/DESIGN.md` section 8.

## Not done yet

- Hardware test on a //e with the Appletini: every timing number comes
  from GSSquared or the py65 model. The paddle timing, the slot 4 slowdown
  window and TURBO are only modelled.
- Difficulty has not been tuned by a human player.
- Speech was checked at the register level, not by ear.
