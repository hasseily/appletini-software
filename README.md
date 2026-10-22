# Appletini Software

Apple II software and hardware demonstrations built to exercise Appletini.

## Development emulator

[`appletini`](tools/appletini/README.md) runs the native W65C02S model without
a GUI, with bounded execution, JSON results, memory assertions and a persistent
debug protocol. It defaults to the nominal 13 MHz UltraWarp preset and 8 MB
RamWorks. A local browser viewer provides Apple/SHR/SuperSprite previews,
laptop controls, stereo Phasor audio and SSI-263 speech. `--wav` captures sound
for automated tests; `--boot` executes supplied Apple and SmartPort ROMs.

```sh
./emulator/appletini run --disk demos/appletini_bosconian/Appletini-Bosconian.hdv \
  --system BOSCO.SYSTEM --frames 60 --expect 'main:0x300=4131334201'
./emulator/appletini play --disk demos/appletini_bosconian/Appletini-Bosconian.hdv \
  --system BOSCO.SYSTEM
```

Python 3, `make` and a C11 compiler build the native library on first use;
speech playback also requires a C++17 compiler. Fixed-speed timing counts CPU cycles without
hardware wait states. Use it for functional tests; board frame-rate estimates
still need hardware validation. macOS is tested; Linux builds are supported but
runtime validation is pending. Native Windows is unsupported; WSL is untested.
See the tool's README for device coverage. libtini's
[`native_emulator.py`](libtini/tools/native_emulator.py) builds the same
machine as a native Windows DLL with MSYS2 GCC. The runner, its machine
library, speech worker and a2vm are licensed GPL-3.0-only.

## libtini

[libtini](libtini/README.md) is a C game SDK for an enhanced Apple //e with
an Appletini. It uses cc65, and the MIT License applies to it. It supplies
Super Hi-Res graphics with a sprite renderer, banked RamWorks resources,
Mockingboard and Phasor music and effects, SSI-263 speech, input and ProDOS
files. Host tools convert assets, music and speech.

Its [browser player](libtini/design/WEB.md) compiles the emulator of this
repository to WebAssembly and runs the disk of a game in a web page. STARFALL,
below, is the example game. The developer documentation is a set of web
pages: open `libtini/docs/index.html` in a browser.

## Demos

- [Appletini Demos](demos/appletini_demos/README.md): the bootable 32 MB
  ProDOS showcase disk, with its HGR launcher, video and speed demos,
  network apps, SuperSprite demo, AD8088 MS-DOS HGR cube, and a Phasor
  performance of House of the Rising Sun with SSI-263 singing.
- [FATDOG MAGIC](demos/fatdog_magic/README.md): a bootable 32 MB
  ProDOS gallery with an HGR folder menu and 32 images converted by FATDOG
  in Standard HGR and 20 in Brooks SHR-3200, plus the Appletini demo image formats. Use phosphor blur
  and glow, combined with composite or TV output, for best results.
- [Glyph Lab](demos/glyph_lab/README.md): a bootable 800 KiB ProDOS demo that
  animates three scenes in 40-column text mode with custom 4 KiB fonts uploaded
  through SmartPort. Requires Appletini firmware with the AGLY v1 character-ROM
  API and an active ARM video renderer. Includes model previews and host tests;
  the demo was also successfully validated on hardware by the user.
- [Appletini Invasion](demos/appletini_invasion/README.md) — an enhanced
  Apple //e fixed shooter using 33.3 MHz acceleration, DHGRi, Video-7 MIX,
  SmartPort, Mockingboard music and speech, and 8 MB RamWorks.
- [The Bilestoad, SHR port](demos/bilestoad/README.md): the 1982 game with
  its original logic, shown in SHR with 64-angle sprites and motion
  interpolated to the video rate, 12-voice Phasor sound, and sprites in
  RamWorks. The build converts the upstream game from a local clone; the game
  source itself is not in this repository; the converted disk is included.
- [Appletini Bosconian](demos/appletini_bosconian/README.md) — an original
  Bosconian-style multidirectional shooter for an enhanced Apple //e in
  320x200 Super Hi-Res at 60 frames per second, using the virtual TransWarp
  (33 MHz or TURBO), the virtual Phasor for music, effects and SSI-263 speech,
  and a RamWorks probe.
- [DOOM GS](demos/doom_gs/README.md): Webifi's Apple IIgs DOOM rewritten
  in native 65C02 for an enhanced Apple //e with the Appletini in TURBO,
  8 MB RamWorks and the Phasor: Super Hi-Res, episode 1, the menus, the
  automap, music and effects. The v1.5-based rebuild passed model checks
  and was successfully tested on hardware by the user.
  The build fetches upstream and converts it; the upstream source is not in
  this repository.
- [STARFALL](libtini/examples/starfall/README.md): libtini's example game, a
  vertical scrolling survival shooter in Super Hi-Res with five enemy types,
  four weapon levels, wingmen, bombs, an eight-track arrangement of a
  doranarasi MIDI demo (all eight on a Phasor, three on a Mockingboard),
  SSI-263 callouts and joystick or keyboard control, at 33 MHz or TURBO.
  Written in C with cc65.
- [Pinball Construction Set](demos/pinball_construction_set/README.md):
  Bill Budge's editor and game ported to SHR, mouse input and Phasor sound.
  The downloadable build passes model tests, but a reported hardware sprite
  smear remains unresolved; see the project's investigation notes.

## Disk images

Download the linked file using GitHub's **Download raw file** button. Extract
ZIP downloads first. Mount large ProDOS volumes as SmartPort hard disks
(in GSSquared, `-ds7d1=<image>`). Use Disk II for 140 KB floppy images
(GSSquared slot 6); `.po` describes sector order, not necessarily a hard disk.
See each project's README for the required machine, card configuration and controls.
DOOM GS uses the pinned upstream v1.5 reference image for its build.

| Project | Image | Size | Boots |
|---|---|---|---|
| Appletini Demos | [Appletini_Demos.zip](demos/appletini_demos/Appletini_Demos.zip) | 32 MB extracted | BASIC.SYSTEM, STARTUP launcher |
| FATDOG MAGIC | [FATDOG_MAGIC.po](demos/fatdog_magic/FATDOG_MAGIC.po) | 32 MB | MAGIC.SYSTEM |
| Glyph Lab | [Glyph-Lab.hdv](demos/glyph_lab/Glyph-Lab.hdv) | 800 KiB | GLYPH.SYSTEM |
| Appletini Invasion | [Appletini-Invasion.hdv](demos/appletini_invasion/Appletini-Invasion.hdv) | 800 KB | INVASION.SYSTEM |
| The Bilestoad, SHR port | [Bilestoad.po](demos/bilestoad/Bilestoad.po) | 800 KB | TOAD.SYSTEM |
| Appletini Bosconian | [Appletini-Bosconian.hdv](demos/appletini_bosconian/Appletini-Bosconian.hdv) | 800 KB | BOSCO.SYSTEM |
| DOOM GS | [DOOM.hdv](demos/doom_gs/DOOM.hdv) | 3.85 MB | DOOM.SYSTEM |
| Pinball Construction Set | [Appletini-PCS.hdv](demos/pinball_construction_set/dist/Appletini-PCS.hdv) | 800 KB | PCS.SYSTEM |
| STARFALL | [STARFALL.po](libtini/examples/starfall/STARFALL.po) | 800 KB | STARFALL.SYSTEM |
| DOOM music | [MUSIC.hdv](music/doom/MUSIC.hdv) | 215.5 KB | MUSIC.SYSTEM |
| House of the Rising Sun | [RISING.SUN.hdv](music/house_of_the_rising_sun/RISING.SUN.hdv) | 140 KB | SUN.SYSTEM |
| Mockingboard demos | [Mockingboard_IIplus_IIe.po](music/mockingboard/Mockingboard_IIplus_IIe.po) | 140 KB | BASIC.SYSTEM, STARTUP menu |
| AUX memory tools | [AUXTOOLS.po](diagnostics/aux_memory/AUXTOOLS.po) / [AUXSTRESS.dsk](diagnostics/aux_memory/AUXSTRESS.dsk) | 140 KB each | ProDOS / DOS 3.3 diagnostics |
| AD8088 tests | [AD8088_Test.po](diagnostics/ad8088/AD8088_Test.po) / [AD8088_Test.dsk](diagnostics/ad8088/AD8088_Test.dsk) | 800 KB / 140 KB | ProDOS / DOS 3.3 diagnostics |

Appli-Card CP/M boot, utility and demo media are listed in its
[README](diagnostics/applicard/README.md). [SHA256SUMS](SHA256SUMS) records the
download bytes; [download build notes](DISK_DOWNLOADS.md) record this build's checks.

Build outputs are copied or packaged at the download paths above; working
build directories are ignored. The Bilestoad image contains the converted upstream game, which has
no licence: check its rights before you redistribute that image.

## Music

- [DOOM music](music/doom/README.md): thirteen songs on the Phasor's AY chips.
- [Mockingboard demos](music/mockingboard/README.md): the 1982 sound and
  speech demonstrations on native ProDOS for a 64 KB II+ or Apple //e,
  with slot-4 sound hardware, interrupt and speech-wait fixes. The patched
  image was validated on hardware by the user; see its validation notes.
- [House of the Rising Sun](music/house_of_the_rising_sun/README.md): a
  standalone Phasor/SSI-263 performance with PAL and NTSC streams.
- [Song to Phasor](music/song_to_phasor/README.md): a vocal-first song conversion
  framework for the Phasor on Appletini F1.2.5 or a real card, with SSI-263 pitch
  and phoneme control and a native Phasor stream player. Its first song is
  [House of the Rising Sun](music/house_of_the_rising_sun/README.md).

## Diagnostics and examples

- [AUXSTRESS / AUXTOOLS](diagnostics/aux_memory/README.md): auxiliary-memory
  and RamWorks diagnostics, with DOS 3.3 and ProDOS disks.
- [AD8088 tests](diagnostics/ad8088/README.md): mailbox, monitor, memory,
  and 8088 execution diagnostics.
- [Appli-Card CP/M](diagnostics/applicard/README.md): banking and CPU tests,
  CP/M media, and disk tools.
- [Appletini detection](examples/detect_appletini/README.md): a standalone
  6502 SmartPort GETDIB example.

## Development layout

Graphics performance depends on the accelerator mode and firmware revision.
Evaluate both the intended classic preset and TURBO: TURBO batches video
writes, captures renderer writes directly and synchronizes its motherboard
mirror at mode-dependent boundaries. A count of video writes multiplied by
one microsecond is not a general TURBO frame-time estimate. See the
[firmware timing reference](https://github.com/hasseily/appletini-one/blob/886ea50e7c5a98c28c7e37b5eff7548a8ea416ce/README_TURBO.md#video-writes).
That source revision is a reference, not a claim about the firmware flashed
on a user's card; verify the target version before drawing performance conclusions.

Appletini Demos builds from its bundled inputs. Some other build and
hardware-validation tools use sibling checkouts by default:

```text
Repos/
├── appletini-one/
├── appletini-software/
└── gssquared/
```

Build and test Appletini Invasion with:

```sh
cd demos/appletini_invasion
make disk
make smoke
```

Set `APPLETINI_ROOT` or `GSSQUARED_ROOT` when those repositories are located
elsewhere. See the demo README for toolchain and runtime details.
