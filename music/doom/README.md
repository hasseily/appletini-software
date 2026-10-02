# DOOM music on the Phasor

`MUSIC.hdv` is a bootable ProDOS disk that plays DOOM's 13 songs on the
four AY chips of the Phasor, on an enhanced Apple //e with an Appletini.

## Hardware

- An enhanced Apple //e (65C02) with an Appletini.
- The Phasor in slot 4, in native mode: in the Appletini menu, the Phasor
  on and its Mockingboard only option off. A card that stays in
  Mockingboard mode has two AY chips; the program then says it has no
  music.
- The mouse card in slot 2: its VBL interrupt is the music's clock.
- RamWorks with banks 1 to 14 (one song in each of banks 1 to 13, ProDOS's
  language card saved in bank 14).

PAL and NTSC are detected at boot.

## Build

Requirements:

- cc65 2.18 or later (`ca65` and `ld65`)
- Python 3 (standard library only)
- make

Then:

    make

This assembles `src/`, links `build/MUSIC.SYSTEM` and writes `MUSIC.hdv`
with the songs from `songs/`, `PROFILE.TXT`, and the boot blocks and
ProDOS 2.4.3 from `assets/ProDOS_2_4_3.po`. `make clean` removes `build/`
and `MUSIC.hdv`. The tool paths can be set with `CA65`, `LD65` and
`PYTHON`, for example `make CA65=/opt/cc65/bin/ca65`.

## Run

Put `MUSIC.hdv` on the Appletini's SD card, mount it as a SmartPort drive
and boot it. The first song starts playing.

## Keys

| Key | Action |
| --- | --- |
| A to M | play a song |
| SPACE | stop |
| N or right arrow | next song |
| P or left arrow | previous song |
| R | loop the song, or play all the songs once in turn |
| V | switch between the PAL and NTSC tables |
| T | AY timing test |
| Q or ESC | quit to ProDOS |

## The profile

The music plays without any profile. `PROFILE.TXT` (also on the disk)
explains an optional Appletini configuration profile, named DOOM, that
sets:

- `vtw.slowdown.cycles=32`: after an access to slot 4 the CPU runs at
  1 MHz for 32 cycles instead of the default 512, which cuts the
  music's CPU cost.
- `phasor.pan.10=5`, `phasor.pan.11=11`, `phasor.pan.12=8`: the pans of
  the fourth AY chip, with its voice C centred. The music itself plays on
  the first three chips.

To use it, save a full profile named DOOM from the menu's Profiles tab,
edit the `vtw.slowdown.cycles` line of its `appletini_cfg.txt` on the SD
card, then choose the profile; `PROFILE.TXT` has the steps. Press T on
the disk to check: the test reports "THE WINDOW IS 32: THE DOOM PROFILE"
with the profile and "THE WINDOW IS 512: THE DEFAULT" without it.

## Rights

The songs are converted from the music of the shareware DOOM; their
rights are id Software's.
