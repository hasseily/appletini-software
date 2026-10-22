# STARFALL

STARFALL is a vertical shooter for libtini. It has one endless level: a moving
starfield with aircraft, shots, explosions and pickups. There is no boss and
no finish line. Keep your ship alive and increase your score.

A new sector starts each 24 seconds. Each sector increases the difficulty by
two levels. The last increase comes at 3:12, in the ninth sector.

## Build and run

A built disk, [STARFALL.po](STARFALL.po), is in this folder. It is a copy of
the build output below. To build it, use the same installed Python 3.10 or
newer and complete cc65 2.19 SDK as the other examples. From the `libtini/`
folder:

```powershell
python tools/setup_inputs.py
python tools/build.py --cc65-home D:/Repos/cc65
```

The setup command installs the pinned ProDOS input one time. Later builds use
local inputs, which include the vendored sprite archive, and operate offline.

Boot `build/starfall.po`, an 800 KiB ProDOS disk that starts
`STARFALL.SYSTEM`. The program is also in `build/starfall.system`, with its
art and prepared speech compiled in. Use `--no-disk` to build only the program
and library outputs.

STARFALL has only a CPU build. Its manifest sets `"private": false`, thus the
optional-AMEM build in `build/private` does not contain it. STARFALL writes
SHR video with normal CPU writes. It needs no firmware or FPGA change, no
added graphics service and no slot change.

Enable RamWorks and give expansion selectors 1-3 to STARFALL only. Keep
SmartPort in slot 7 and select a Mockingboard or Phasor personality in slot 4.
The slot-4 audio driver also supplies the game clock, thus STARFALL needs that
audio card. The firmware is Appletini F1.3.2. In standalone ONE//e mode, speech
needs Appletini firmware F1.3.2 or later (see
[speech](../../docs/api/speech.html#hardware)).

## Controls

On the title screen, push **M** for the Mockingboard or **P** for the Phasor.
Push **Return** or a joystick button to start with the Mockingboard. On the
title screen, **B** turns the parallax backdrop of distant aircraft on or off.
The backdrop is on at startup.

| During play | Action |
| --- | --- |
| WASD or arrow keys | Move while you hold the key |
| Joystick | Move; diagonals operate, and the rest position stops the ship |
| Space, B or a joystick button | Use one bomb |
| J | Turn the joystick on or off |
| P or Escape | Pause or continue; the pause panel shows the live joystick values |
| Return or a joystick button during a pause | Continue |
| R | Start a new run |
| Return or a joystick button after the ship is lost | Start a new run |
| Q | Go back to ProDOS |

If a libtini call fails, the game stops. The text screen shows
`ERROR ee STEP s` until you push a key, and then the game goes back to ProDOS.
`ee` is the libtini error code from `include/libtini/types.h`: the first error
that `ti_error_keep` kept. `s` is the step in which the error occurred:

1. Memory setup.
2. The canvas.
3. Video.
4. The scene.
5. The title.
6. Play.

### Keyboard

The ship moves while you hold a key. The libtini function `ti_input_held`
reads the newest key from the //e keyboard latch while the any-key-down bit is
set. A tap that is shorter than one frame moves the ship one time. The //e
gives only the newest key. If you hold a direction and tap Space, the ship
continues in that direction until you release all keys. Diagonals need the
joystick.

### Joystick

STARFALL reads the joystick automatically; there is no mode to select. Apple
joysticks seldom rest at 128, and their travel is not the same in each
direction. Thus STARFALL measures the stick with the calibrated libtini reader,
`ti_stick_read`.

- At each start, new run and continue, the first value between 48 and 207 on
  the two axes becomes the rest position. Do not move the stick when you push
  the key or button.
- A direction engages when the stick moves from rest by one third of the
  largest travel on that side, and by a minimum of 16 units.
- The direction releases at three quarters of that distance. Thus a stick near
  the limit does not flicker.
- Push J two times to measure the rest position again.
- After the stick answers one time, a paddle that does not finish in 4 ms
  counts as full travel.
- If interrupts disturb a value, the ship keeps the last direction.

On the //e, each access to $C070-$C07F starts the paddle timers. This includes
the RamWorks bank selector at $C073. libtini does not write the selector for
bank 0 transfers, and it lets running paddle timers finish at each read.

A stick that is away from rest has priority over the keyboard. A stick at rest
gives control to the keyboard, thus you can connect the two. After four reads
without an answer, the reader waits three seconds and then measures again.
Push J to ignore a stick fully.

The pause panel shows the live values (`JOY x y`, 0-255) to check a stick. The
two joystick buttons, and Open Apple and Solid Apple, operate as fire. After
the ship is lost, a joystick button starts a new run only after one second.
Thus a held bomb button cannot skip the results. Your guns fire
automatically.

## Survive the rift

You start with three hull points and three bombs. The bright dot at the
center of the ship is its core, which enemies can hit. The ship art is larger
than the collision area. Damage makes the ship invulnerable for a short time
and decreases its weapon level. A collision destroys any enemy that is lighter
than a heavy, but it costs a hull point. When the last hull point is lost, the
run ends.

| Arrives | Enemy | Behaviour | Points |
| --- | --- | --- | --- |
| 0:00 | Scout | Moves down in lines of three, five from 1:12; aims one shot from 1:12, two from 2:24 | 25 |
| 0:24 | Dart | Dives in pairs, groups of three from 1:36, and turns briefly towards you | 40 |
| 0:24 | Gunship | Hovers and fires aimed shots; pairs with faster shots from 2:00 | 100 |
| 0:48 | Sweeper | Crosses the field and fires straight down; pairs from 1:12 | 60 |
| 0:48 | Heavy | Needs much fire; three-shot fans, then five-shot fans and two scout escorts from 1:36 | 250 |

The hit points are 1 for a scout, 2 for a dart, 3 for a sweeper, 6 for a
gunship and 15 for a heavy. A bomb does 7 points of damage.

At the start, a wave arrives each 1.8 seconds. From 2:48, a wave arrives each
0.63 seconds. Fire rates increase by two steps in each sector. Heavies are
rare: at the start, about one wave in sixteen, and at the end three in
sixteen. Only one heavy can be on the screen until 2:00, two until 2:48 and
three after that. At the start of each sector, no waves arrive for about 2.5
seconds. Each new sector gives 100 points for each completed sector.

Aimed shots are pink orbs that pulse. Heavy fans are orange and sweeper shots
are red needles. A bomb removes enemy bullets, destroys lighter enemies and
damages the heavies that stay. If you hold the bomb button, it uses only one
bomb.

Each fifth destroyed enemy drops a pickup, in this sequence: weapon, shield,
weapon and bomb. A destroyed heavy also drops a repair kit, or a shield when
the hull is full. Gunships and sweepers sometimes drop shields. Pickups move
down, and they move towards the ship when it is within forty pixels.

| Pickup | Effect |
| --- | --- |
| P | Next weapon step: single, twin, triple, wide, left wingman, right wingman, then overdrive |
| Shield | Stops one hit |
| Red cross | Adds one hull point |
| Rocket | Adds one bomb, to a maximum of five |

The weapon P has a function after the widest gun:

- **Wingmen.** Each wingman flies 20 pixels to one side of the ship and fires
  straight ahead with each volley. A wingman also stops an enemy bullet that
  touches it, and the wingman is then lost. The next P replaces a lost
  wingman. Wingmen fly through aircraft without damage.
- **Overdrive.** A P that you collect with the wide weapon and two wingmen
  starts eight seconds of overdrive. Each shot gets one more power point and
  becomes a lance. A lance continues through each aircraft that it destroys.
  Kill points double, thus the chain multiplier is x2 to x8. Another P starts
  the eight seconds again. Damage stops overdrive immediately.

Damage decreases the weapon by one step, but the wingmen stay. A shield,
repair or bomb that has no effect, for example a repair at full hull, gives
200 more points. Each pickup gives 50 points.

Each second of survival gives one point. Kills within 1.5 seconds of each
other make a chain. Five kills in a chain double their points, ten triple
them, and fifteen multiply them by four. The chain stops when 1.5 seconds go
by without a kill, and at each hit.

The HUD shows the sector, the sector progress, the time, the score, the best
score, the chain multiplier, the hull, the shield, the bombs and the weapon. A
suffix gives the number of wingmen (`WIDE  +2`). In overdrive, the weapon name
pulses and a gauge below it counts down. Each value keeps its length. Thus
`ti_gfx_text_opaque` draws a new value over the old value, and the game
publishes only its cells. The best score stays in memory until you quit.
STARFALL does not save it to disk.

### Sound and speech

A looped eight-track song, effects with priorities and short SSI-263 phrases
use the libtini audio driver together. On a Phasor, STARFALL uses all twelve
voices: the song plays on voices 0-7 and effects on 8-11. On a Mockingboard,
or a Phasor that answers as a Mockingboard, it has six voices. Then the first
two tracks of the song, lead and bass, play on voices 0-1, and effects play on
2-5. The effect table counts voices from the first voice that the song does
not use, through `ti_audio_effect_voice`. Thus the table is correct for the
two cards. Each start, new run and continue starts the song at its first bar.

The spoken lines and their captions:

| Line | When |
| --- | --- |
| READY | A run starts |
| POWER UP | A P increases the weapon step, if no other line plays |
| EXCELLENT | You collect a repair kit |
| GREAT SHOT | The multiplier gets to x8: in overdrive, with fifteen kills in a chain |
| ALL CLEAR | A bomb goes off |
| WARNING | The first heavy of the run comes |
| GAME OVER | The ship is lost |

NEW RECORD follows GAME OVER when a run has a better score than the best
score, and the results panel shows NEW BEST!. Sector changes, shields, bombs,
wingmen and overdrive show captions without speech. When the driver refuses
speech, a repair shows HULL REPAIRED. Overdrive starts with a flash. Bombs,
hits and heavy explosions flash the background and shake the field. Shields
and aimed shots pulse through palette changes, not through more drawing.

## Art, music and source

The aircraft, pickups and explosions come from Kenney's **Pixel Shmup 1.1**,
which is in the public domain under **CC0 1.0 Universal**. The original
archive, the unchanged license and the hashes are in
[`assets/starfall`](../../assets/starfall/README.md). Builds convert that local
archive to sixteen-color sprites; they do not download art.

The same tool makes one 16x16 atlas cell of small hand-drawn sub-sprites:
bullets, engine flames, hit sparks and the wingman. It also makes two cells
for the distant aircraft of the backdrop from five grey aircraft of the pack:
it crops, reduces and darkens them. The example draws the stars and the
interface graphics.

The song is an AY arrangement of `stg_bs001_88pro.mid`, a free demo file of
the doranarasi **SHMUP MIDI Pack**, Copyright (C) doranarasi 2024. Its terms
permit use and arrangement in games, but not the publication of the MIDI file
as it is. [`assets/starfall/music`](../../assets/starfall/music/README.md)
gives the terms, the arrangement and the conversion command. The repository
contains the arranged song, not the MIDI file.

The song plays the loop of the original, bars 26-49, at 152 bpm: about 38
seconds. Its eight tracks are lead, bass, two guitar notes, two organ notes
and two string notes. The song has no drums. Compiled, it is 1,020 bytes of
low MAIN constants.

### Simulation and memory

The portable simulation is in [`game.c`](game.c) and [`game.h`](game.h). It
keeps one state record. Its pools are parallel byte arrays, which the 65C02
indexes with one absolute,Y operand. On the 65C02, the `NEARBSS` segment
contains that record. Thus it is in the libtini caller near arena, $B480-$B6FF,
outside main memory. The star columns, the animated palette and two text
buffers are also there: 639 of the 640 bytes of the arena. The linker checks
the size.

STARFALL links with its own layout, [`starfall.cfg`](starfall.cfg). It makes
no file calls. Thus the 1 KiB ProDOS file buffer and the guard page that
precedes it are game memory, and a file call does not link.

[`main.c`](main.c) controls input, audio and the SHR renderer. It gets thirty
updates each second from `ti_steps_due`. Its fixed pools hold fourteen
enemies, twenty-eight player shots, thirty-six enemy shots, twelve effects,
three pickups and two wingmen. In busy scenes, the 112-sprite list draws fewer
stars, and then fewer backdrop aircraft. Thus each aircraft, shot and pickup
always fits. Effects come last. A full list drops explosion frames first, and
these frames have no effect on play.

### Backdrop and playfield

The backdrop is 24 aircraft in two layers below all items of play. Sixteen
6-pixel far aircraft move one pixel each four frames. Eight 10-pixel aircraft
move one pixel each two frames. Each aircraft has its own frame, and both
layers are slower and darker than the near stars. Their positions come from
the game tick, thus the backdrop keeps no state. When the backdrop is off, its
list entries are free for stars. On the development emulator, the backdrop
adds about 6 ms to each drawn frame at 33 MHz and 5.5 ms in TURBO. The game
draws each game step. See [benchmarks](../../design/BENCHMARKS.md).

The playfield, 240x184 pixels below the caption, is a libtini
[sprite scene](../../docs/api/scene.html). Each frame lists its sprites in draw
order. The scene draws again only the 16x8-pixel blocks that changed, and
composes them in a near strip that is 120 bytes wide. Atlas sub-sprites are
images inside the atlas cell, with the 8-byte stride of that cell. The stars,
the shield bubble and the bright core of the ship are solid rectangles.

A banked canvas holds the interface and the opaque panels. It does not hold a
copy of the moving playfield. After the game publishes the canvas over the
playfield, it calls `ti_scene_forget`.

The simulation does thirty updates each second from the 100 Hz device clock of
the audio driver. A long or invalid clock gap pauses the game until you
continue it. The display frame rate changes with the drawing load, but the
simulation advances by the elapsed device ticks.

## Checks

```powershell
python tests/test_starfall.py --cc C:/msys64/ucrt64/bin/gcc.exe
python tests/scene_validate.py --cc65-home D:/Repos/cc65
python -m unittest discover -s tests -p test_starfall_assets.py -v
python tests/audio_validate.py
python tests/starfall_native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe
python tests/starfall_native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe --phasor
```

| Command | Covers |
| --- | --- |
| `test_starfall.py` | The C simulation on the host: movement, collisions, weapons, wingmen, overdrive, pickups, bombs, enemies, chains, the sector schedule and deterministic long runs |
| `scene_validate.py` | Each draw of the library scene renderer against an independent rendering of the sprite list |
| `test_starfall_assets.py` | The archive hashes, the packed sprite cells and the phrases |
| `audio_validate.py` | Pattern songs, track-to-voice mapping, joystick reads with and without a counting timer 2, a $C073 write that precedes a read, held keys and fixed steps |
| `starfall_native_validate.py` | ProDOS boots with each card: held and tapped keys, joystick movement from an off-center rest, the playfield against the reference, and the AY voices of song and effects |

[Checks](../../docs/reference/testing.html) gives all libtini checks.
