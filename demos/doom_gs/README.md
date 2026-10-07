# DOOM GS: the Apple IIgs DOOM on the Appletini 65C02

This is a port of [Webifi's Apple IIgs DOOM](https://github.com/Webifi/iigs-doom)
to an enhanced Apple //e with an Appletini card. Upstream is a complete game,
about 82,000 lines of 65816 assembly. The Appletini's accelerator is a
W65C02S, so the game is rewritten in native 65C02 code. It keeps upstream's
Super Hi-Res renderer techniques and game logic, and plays the WAD's MUS
music on the Phasor.

`build/native/DOOM.hdv` is the whole game on one 4 MB ProDOS volume: the
title loop with its music and demo, the menus, episode 1 from E1M1 with the
keyboard and the mouse, the status bar, the HUD, the automap, the
intermission, the music and the sound effects. It has been played on the
card.

## The machine

- An enhanced Apple //e (PAL or NTSC) with 8 MB of RamWorks.
- The Appletini in TURBO mode.
- The Phasor in slot 4, in native mode (not "Mockingboard only"), for the
  music and the effects. Without it the game plays silent.
- In slot 2, the Appletini's mouse card or a standard AppleMouse II. The
  mouse card is optional: with none, the clock is the Phasor's timer and the
  game is played from the keyboard.
- The memory API (the Appletini in slot 7) is optional. Without it the CPU
  makes the same copies, more slowly.
- A VidHD also works (`docs/PLAY.md`, "With a VidHD").

Load the Doom profile: the working setup saved as a profile `DOOM`, with
`vtw.slowdown.cycles=32` in its `appletini_cfg.txt` (and
`phasor.slot4.enabled=ON`, `phasor.mockingboard.only=OFF`,
`slot2.card=MOUSE`, `vtw.turbo.enabled=ON`, `phasor.pan.10=5`,
`phasor.pan.11=11`, `phasor.pan.12=8`). How to make it is in
[`tools/sound/README.md`](tools/sound/README.md), "The Doom configuration
profile". For speed, add `vtw.disk2.acceleration.disabled=on`: with the
virtual Disk II active, every TURBO cycle is replayed to it and the CPU
runs at about 67 MHz instead of 110.

Copy `DOOM.hdv` to the card's SD volume and boot it as the boot volume.
`DOOM.SYSTEM` loads everything into RamWorks and the card, checks every
CRC and starts the title loop.

## Playing

| Key | Does |
| --- | --- |
| Up, down arrows, `W` `S` | forward, back |
| Left, right arrows | turn |
| `A` `D`, `,` `.` | strafe |
| Open Apple, mouse button | fire |
| `E`, `SPACE`, `RETURN`, Solid Apple | use: doors, switches, lifts (`RETURN` also selects in the menus) |
| mouse left and right | turn |
| `1`-`7` | weapons |
| `TAB` | the automap, then its overlay, then off; `-` `=` zoom |
| `ESC` | the menu |

Run is the menu's OPTIONS, CONTROLS, ALWAYS RUN (the //e cannot see Shift
alone). KEY SETUP changes the keys. OPTIONS, BENCHMARK plays demo3 timed
and shows its frame rate. The cheats are upstream's IIgs set (`iddqd`,
`idkfa`, `idclev`, ...). OPTIONS, SAVE SETTINGS writes the settings
(the keys, the mouse, gamma, the volumes, always run, messages) to the
disk's `DOOM.SETTINGS`, and the next boot starts with them; saving and
loading games say "not in this version". QUIT GAME ends on a text screen.

## Building

    ./build.sh

writes `build/native/DOOM.hdv` from nothing in about a minute. It needs
`python3` (standard library only), `cc`, `make`, cc65 (`ca65`, `ld65`), the
network once (to fetch upstream), and appletini-one's
`software/ProDOS_2_4_3.po` beside this repository (or set `APPLETINI_ROOT`
to the appletini-one checkout). The steps:

1. `tools/fetch_upstream.py` puts a pinned clone of upstream and its v1.0
   release image in `build/` and checks them. The WAD is the shareware
   `DOOM1.WAD` in that clone.
2. `tools/v816/imgmatch.py` assembles upstream's sources and links them to
   match the release byte for byte, and writes `build/linkmap.json`: the
   address of every symbol of the release.
3. `tools/ref816` is the reference machine, a 65816 core and a minimal IIgs.
   `tools/native/rendercap.py` runs the release on it under script, and
   `tools/native/rtables.py` takes the renderer's constant tables from its
   memory and checks them against their formulas.
4. `make` builds the native code in `src/native` (ca65 and ld65): the
   renderer (`render.mk`), the level load (`level.mk`, with
   `tools/native/wadconv.py`, which converts the WAD's levels, textures and
   sprites), the 2D screens and the effects (`m11.mk`), and the music
   player (`src/sound`).
5. `tools/native/playdisk.py` links the main loop and the game logic
   (`play.mk`, the parts in `src/native/game`, placed by
   `tools/native/gplace-f122.json`) and writes the disk.

A clean build gives the disk that was tested on the card, byte for byte.

`python3 tools/native/playdisk.py --run SCRIPT` plays the disk on `a2vm`
(`tools/a2vm`), the model of the //e with the Appletini, under scripted
input; the script format is in [`tools/a2vm/README.md`](tools/a2vm/README.md),
"Input events".

## What is here

| Path | Contents |
| --- | --- |
| `src/native/` | The game in 65C02 assembly: the renderer, the level load, the game logic (`game/`), the 2D screens, the effects, the main loop and the boot |
| `src/sound/` | The music player for the Phasor |
| `tools/native/` | The host tools that generate the layouts and tables, convert the WAD, and link and write the disk |
| `tools/sound/` | MUS to AY song conversion and the sound effects' conversion |
| `tools/v816/` | Assembler and linker for upstream's 65816 sources |
| `tools/ref816/` | The reference machine that runs upstream's release |
| `tools/bridge/` | Upstream's data structures and symbols, for the tools |
| `tools/a2vm/` | The model of the target machine, to run the disk on the host |
| `coverage/` | The input scripts of the reference machine's runs |
| `docs/` | The design as built: `PLAY.md` (the main loop, the boot disk, the machine), `MEMORY_MAP.md`, `RENDER.md` and `RENDER-MASKED.md` (the renderer), `LEVELS.md` (the level load), `GAME.md` (the game logic), `SCREENS.md` (the 2D screens, the platform, the effects), `SPEED.md` (the speed work) |

## Licence

Everything in this directory is licensed under the GNU General Public
License, version 2 ([`LICENSE`](LICENSE)), as upstream is. The native port is
rewritten from upstream's source, so it is a derivative of it. The owner
chose this licence on 2026-09-30.

`tools/a2vm/py65core.h` holds tables from py65 under their own BSD licence,
which the header reproduces.

## What stays out of the repository

The build fetches upstream and its release image into `build/`, which git
ignores, and converts them there. Upstream's own files, the release image,
the shareware `DOOM1.WAD` (id Software's licence) and ROM images are never
committed.

- `src/iigs/cal_integer.s` in upstream is a copy of the Calypsi vendor
  runtime. Its licence restricts it to that toolchain, so the port uses its
  own routines and keeps nothing derived from that file.
