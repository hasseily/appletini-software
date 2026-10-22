# STARFALL

STARFALL is a vertical scrolling survival shooter for libtini. One endless
level fills a moving starfield with aircraft, shots, explosions and pickups.
There is no boss or finish line: keep your ship alive and improve your score.
Every 24 seconds a new sector begins. Each sector raises the difficulty two
levels, and the last increase arrives at 3:12, in the ninth sector.

## Build and run

A ready-built disk, [STARFALL.po](STARFALL.po), is committed beside this file;
it is a copy of the build output below. To build it, from the `libtini/`
folder, use the same installed Python 3.10+ and complete cc65 2.19 SDK as the
other examples:

```powershell
python tools/setup_inputs.py
python tools/build.py --cc65-home D:/Repos/cc65
```

The setup command installs the pinned ProDOS input once. Later builds use
local inputs, including the vendored sprite archive, and work offline.
Boot `build/starfall.po`, an 800 KiB ProDOS disk that starts
`STARFALL.SYSTEM`. The executable is also available as
`build/starfall.system`; its art and prepared speech are compiled into it.
Use `--no-disk` when only executable and library outputs are needed.

STARFALL has only this CPU build. Its manifest sets `"private": false`, so
the SDK's optional-AMEM build in `build/private` leaves it out. It publishes
SHR video through normal CPU writes and requires no firmware or FPGA changes,
additional graphics services or slot swapping.

Enable RamWorks and grant expansion selectors 1-3 exclusively to this
application. Keep SmartPort in slot 7 and select a Mockingboard or Phasor
personality in slot 4. The slot 4 audio driver also supplies the simulation
clock, so the current example requires that audio configuration. The named
board baseline is existing Appletini F1.3.2; physical STARFALL acceptance on
that baseline remains pending. In standalone ONE//e mode, firmware before
F1.3.2 gives the speech chips no clock, so the game plays without speech or
its spoken captions (see [speech](../../docs/api/speech.html#hardware)).

## Controls

On the title screen, press **M** for Mockingboard, **P** for Phasor, or
**Enter** or a joystick button to launch with Mockingboard. **B** turns the
parallax backdrop of distant aircraft on or off before launch; it starts on.

| During play | Action |
| --- | --- |
| WASD or arrow keys | Move while held |
| Joystick | Move; diagonals work and the rest position stops |
| Space, B or a joystick button | Use one bomb |
| J | Turn joystick reading off or on |
| P or Escape | Pause or resume; the pause panel shows live joystick readings |
| Enter or a joystick button while paused | Resume |
| R | Start a fresh run |
| Enter or a joystick button after losing the ship | Start a fresh run |
| Q | Return to ProDOS |

If a libtini call fails, the game stops and the text screen shows
`ERROR ee STEP s` until a key is pressed, then returns to ProDOS. `ee` is the
libtini error code from `include/libtini/types.h`, the first one that
`ti_error_keep` kept. The step is the one the game was in, each checked
before the next starts: 1 memory setup, 2 the canvas, 3 video, 4 the scene,
5 the title or 6 play.

Keys move the ship while held. libtini's `ti_input_held` reads the newest
key from the //e keyboard latch while its any-key-down bit is set. A tap
shorter than a frame still moves the ship once. The //e reports only the
newest key, so holding a direction and tapping Space keeps the ship moving
that way until every key is up; diagonals need the joystick. The joystick
is read automatically; there is no mode to select.

Real Apple joysticks rarely rest at 128 or travel equally in every
direction, so STARFALL measures the stick instead of assuming a centre. It
uses libtini's calibrated reader, `ti_stick_read`. Each launch, retry and
resume takes the first reading between 48 and 207 on both axes as the rest
position; leave the stick alone while you press the key or button. A direction engages once the stick moves a third of the
furthest travel seen on that side, and at least 16 units, from rest. It
lets go at three quarters of that distance, so a stick held near the
threshold does not flicker. Pressing J twice measures the rest again. A
paddle that has not finished after 4 ms counts as fully deflected once the
stick has answered. A reading disturbed by interrupts keeps the last
direction instead of stopping the ship.

On the //e, any access to $C070-$C07F also starts the paddle timers,
including the RamWorks bank selector at $C073. Earlier builds wrote that
selector on every screen update and could then read a stick pushed right or
down as too short, so the ship jerked the other way while moving. libtini
now leaves the selector alone for bank 0 transfers and lets running paddle
timers finish before each reading.

A stick held away from rest overrides the keyboard. A stick at rest leaves
keyboard control in charge, so both can stay connected. After four reads
without an answer, the reader waits three seconds before measuring again,
instead of trying every frame. Press J to ignore a stick entirely.
The pause panel shows the live readings (`JOY x y`, 0-255) for checking a
stick. Either joystick button, or Open/Solid Apple, acts as fire. After the
ship is lost, a joystick button only retries after one second, so a held
bomb button cannot skip the results. Your guns fire automatically.

## Survive the rift

You begin with three hull points and three bombs. The bright dot at the
ship's centre marks its vulnerable core; the ship artwork is larger than
the collision area. Damage briefly makes the ship invulnerable and lowers
its weapon level. Ramming anything lighter than a heavy destroys it but
still costs a hull point. Losing the final hull point ends the run.

| Arrives | Enemy | Behaviour | Points |
| --- | --- | --- | --- |
| 0:00 | Scout | Weaves down in lines of three, five from 1:12; aims one shot from 1:12, two from 2:24 | 25 |
| 0:24 | Dart | Dives in pairs, threes from 1:36, steering briefly towards you | 40 |
| 0:24 | Gunship | Hovers and fires aimed shots; pairs with faster shots from 2:00 | 100 |
| 0:48 | Sweeper | Crosses the field firing straight down; pairs from 1:12 | 60 |
| 0:48 | Heavy | Needs sustained fire; three-shot fans, then five-shot fans and two scout escorts from 1:36 | 250 |

Hit points are 1 for a scout, 2 for a dart, 3 for a sweeper, 6 for a
gunship and 15 for a heavy; the last two have half again their earlier 4
and 10. A bomb does 7.

Waves arrive every 1.8 seconds at first and every 0.63 seconds from 2:48.
Fire rates rise two steps per sector. Heavies are rare: about one wave in
sixteen at first, rising to three in sixteen. No more than one heavy can be
on screen until 2:00, two until 2:48, and three after that. Each new sector
pauses arrivals for about 2.5 seconds and awards 100 points for each sector
already completed.

Sector 8 now plays like the earlier sector 15, and sector 9 reaches the top
level that sector 16 used to. The schedule is checked against a dodging
player model in the host checks. The model sees the game 267 ms late and
decides every 133 ms. Over sixteen runs it lasts 198 seconds on average,
against 399 with one level a sector and the earlier hit points, and takes
6.25 hits in the first three minutes instead of 1.56. These are simulation
measurements, not a measure of how hard a person finds the game.

Aimed shots are pulsing pink orbs, heavy fans are orange and sweeper shots
are red needles. A bomb clears hostile bullets, destroys lighter enemies and
damages surviving heavies; holding its button spends only one bomb.

Every fifth destroyed enemy drops a pickup, cycling through weapon, shield,
weapon and bomb. A destroyed heavy also leaves a repair kit, or a shield when
the hull is full. Gunships and sweepers sometimes drop shields. Pickups
drift downwards and are drawn towards the ship once it is within forty
pixels.

| Pickup | Effect |
| --- | --- |
| P | Next weapon step: single, twin, triple, wide, left wingman, right wingman, then overdrive |
| Shield | Absorbs one hit |
| Red cross | Restores one hull point |
| Rocket | Adds one bomb, up to five |

The weapon P keeps mattering after the widest gun:

- **Wingmen.** Each one trails the ship 20 pixels to one side and fires
  straight ahead with every volley. A wingman also stops an enemy bullet
  that touches it, and is lost doing so. The next P replaces a lost
  wingman. Wingmen fly through aircraft unharmed.
- **Overdrive.** A P collected with the wide weapon and both wingmen starts
  eight seconds of overdrive. Every shot gains one power and becomes a
  lance. A lance that destroys an aircraft carries on through it. Kill
  points double, so the chain multiplier runs from x2 to x8. Another P
  restarts the eight seconds. Taking damage ends overdrive at once.

Damage still lowers the weapon by one step but leaves the wingmen. A shield,
repair or bomb that cannot help, such as a repair at full hull, scores 200
extra points. Every pickup scores 50.

Survival earns one point per second. Kills that follow each other within
1.5 seconds build a chain. Five chained kills double their points, ten
triple them, and fifteen quadruple them. The chain resets when 1.5 seconds
pass without a kill, and on any hit. The HUD shows sector, sector progress,
time, score, best score, chain multiplier, hull, shield, bombs and weapon.
A suffix counts wingmen (`WIDE  +2`). In overdrive the weapon name pulses
and a gauge beneath it counts down. Each value keeps its length, so
`ti_gfx_text_opaque` draws a new value over the old one and only its cells
are published. The best score remains in memory until
you quit; this example does not save it to disk.

A looping eight-track song, prioritized effects and short SSI-263 phrases
share the libtini audio driver. On a Phasor STARFALL uses all twelve
voices: the song plays on voices 0-7 and effects on 8-11. On a Mockingboard,
or a Phasor that answers as one, it has six voices. There the song's first
two tracks, lead and bass, play on voices 0-1 and effects on 2-5. The effect
table counts voices from the first one the song leaves, through
`ti_audio_effect_voice`, so it suits both cards. Each
launch, retry and resume starts the song from its first bar. Spoken lines
and their on-screen captions:

| Line | When |
| --- | --- |
| READY | A run starts |
| POWER UP | A P raises the weapon step, unless another line is still playing |
| EXCELLENT | A repair kit is collected |
| GREAT SHOT | The multiplier reaches x8: in overdrive, with fifteen chained kills |
| ALL CLEAR | A bomb goes off |
| WARNING | The run's first heavy appears |
| GAME OVER | The ship is lost |

NEW RECORD follows GAME OVER when a run beats the best score, and the
results panel shows NEW BEST!. Sector changes, shields, bombs, wingmen and
overdrive show captions without speech. When the driver refuses speech, a
repair shows HULL REPAIRED instead. Overdrive starts with a
flash. Bombs and hits flash the background and shake the
field, as do heavy explosions. Shields and aimed shots pulse through palette
changes rather than extra drawing.

## Art, music and source

Aircraft, pickups and explosions come from Kenney's **Pixel Shmup 1.1**,
dedicated to the public domain under **CC0 1.0 Universal**. The original
archive, unchanged license and hashes are stored under
[`assets/starfall`](../../assets/starfall/README.md). Normal builds convert
that local archive to sixteen-colour sprites; they do not download art.
Bullets, engine flames, hit sparks and the wingman are small hand-drawn
sub-sprites in one 16x16 atlas cell made by the same tool. The backdrop's
distant aircraft are five of the pack's grey aircraft, cropped, reduced and
darkened by that tool into two more cells. Stars and interface graphics are
drawn by the example.

The song is an AY arrangement of `stg_bs001_88pro.mid`, a free demo file of
doranarasi's **SHMUP MIDI Pack**, Copyright (C) doranarasi 2024. Its terms
allow use and arrangement in games but not publishing the MIDI file as is;
[`assets/starfall/music`](../../assets/starfall/music/README.md) has the
terms, the arrangement and the conversion command. The repository holds
the arranged song, not the MIDI file. The song plays the loop of the
original, bars 26-49, at 152 bpm: about 38 seconds. Its eight tracks are
lead, bass, two guitar notes, two organ notes and two string notes; the
drums are left out. Compiled, it is 1,020 bytes of low MAIN constants.

The portable simulation lives in [`game.c`](game.c) and [`game.h`](game.h).
It keeps one state record whose pools are parallel byte arrays, which the
65C02 indexes with a single absolute,Y operand. On the 65C02 that record is
declared in the `NEARBSS` segment, so it lives in libtini's caller near
arena, $B480-$B6FF, outside main memory. Star columns, the animated palette
and two text buffers join it there, 639 of the arena's 640 bytes; the
linker checks the size. STARFALL links with its own layout,
[`starfall.cfg`](starfall.cfg): it makes no file calls, so the 1 KiB ProDOS
file buffer and the guard page before it are game memory, and a file call
would fail to link. [`main.c`](main.c) owns input, audio and the SHR
renderer. It takes thirty updates a second from `ti_steps_due`. Its fixed pools allow fourteen enemies,
twenty-eight player shots, thirty-six hostile shots, twelve effects, three
pickups and two wingmen. The 112-sprite list draws fewer stars in busy
scenes, then fewer backdrop aircraft, so every aircraft, shot and pickup
always fits. Effects come last, and a full list drops explosion frames
before anything that matters to play.

The backdrop is 24 aircraft in two layers under everything that plays:
sixteen 6-pixel far aircraft that move a pixel every four frames and eight
10-pixel ones that move one every two, each on its own frame, both slower and
darker than the near stars. Their positions follow the game tick, so the
backdrop keeps no state; turning it off frees its list entries for stars.
In the emulator it adds about 6 ms to each drawn frame at 33 MHz and 5.5 ms
at TURBO, about 20 ms in all, and every game step is still drawn; see
[benchmarks](../../design/BENCHMARKS.md).

The playfield, 240x184 pixels below the caption, is a libtini
[sprite scene](../../docs/api/scene.html). Each frame lists its
sprites in draw order, and the scene redraws only the 16x8-pixel blocks that
changed, composing them in a 120-byte-wide near strip. Atlas sub-sprites are
images inside the atlas cell with that cell's 8-byte stride. Stars, the
shield bubble and the ship's bright core are solid rectangles. A banked canvas holds the interface
and opaque panels, not a copy of the moving playfield. After the canvas is
published over the playfield, the game calls `ti_scene_forget`.

## Verification

```powershell
python tests/test_starfall.py --cc C:/msys64/ucrt64/bin/gcc.exe
python tests/scene_validate.py --cc65-home D:/Repos/cc65
python -m unittest discover -s tests -p test_starfall_assets.py -v
python tests/audio_validate.py
python tests/starfall_native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe
python tests/starfall_native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe --phasor
```

Host checks exercise movement bounds, the collision core, ramming, all four
weapon levels, shields, bombs, every enemy behaviour and bullet style, chain
scoring, all four pickups and the pickup drift. They cover wingmen, their
formation at the screen edges, bullet blocking and replacement. They cover
overdrive power, piercing, double points and its end on damage. They also
check the sector schedule of two levels a sector. Hundreds of triggered
waves per level show that each enemy type first appears at its level, with
its hit points, and that heavies never exceed their cap. A paired
20,000-tick run checks deterministic results and bounded pools. It reaches
the last level, finds no heavy before 0:48 and no fan shot before it, and
sees wingmen and overdrive. Eight unattended runs
record how long an idle ship lasts. Sixteen runs of the player model above
record how long an active player lasts. These checks use the same C
simulation as the target application.

The scene check runs the library renderer on the 65C02 model and compares
the screen after every draw with an independent rendering of the sprite
list; see [checks and status](../../docs/reference/testing.html). The ROM-boot
validation applies the same comparison to STARFALL's own playfield at
sampled frames of unattended play.

The audio validation also plays pattern songs through the actual linked
player: its notes, rests, holds, row timing, decay, loop position and
track-to-voice mapping, and its rejection of damaged songs. The ROM-boot
validation reads the card's AY registers during play. On a Phasor, voices
0-7 must play only their own track's notes and effects must be heard on
voices 8-11; on a Mockingboard the same holds for voices 0-1 and 2-5. It
saves the first 90 seconds of the modelled audio as `audio-PROFILE.wav`.

The audio validation runs the actual linked joystick code against register
models with and without a counting timer 2. The real VIA path and the T1
fallback must both read the model's paddles within a narrow range. An axis
that never finishes must saturate at 255 while the other stays valid. A
$C073 bank write just before a read must not shorten it. The calibrated
reader, held keys, fixed steps and voice count have their own checks; see
[checks and status](../../docs/reference/testing.html).

The ROM-boot validation also restarts with the stick resting off-centre at
165, 95. The rest must not move the ship, and deflections to 105 and 150,
which the old fixed 80/175 thresholds ignored, must move it left and down.

The ROM-boot validation drives the actual program through held and tapped
keys and joystick input in both model profiles; see
[checks and status](../../docs/reference/testing.html) for the commands
and their limits.

The simulation targets thirty updates per second from the audio driver's
100 Hz device clock. Long or invalid clock gaps pause the game for an
explicit resume. Display frame rate can vary with drawing load while the
simulation advances by elapsed device ticks. Emulator observations are
separate evidence; only board runs at **33 MHz and TURBO** can establish
physical timing, control response, video output and audible quality. Those
board checks remain pending.
