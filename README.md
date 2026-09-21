# Appletini Software

Apple II software and hardware demonstrations built to exercise Appletini.

## Demos

- [Appletini Demos](demos/appletini_demos/README.md): the bootable 32 MB
  ProDOS showcase disk, with its HGR launcher, video and speed demos,
  network apps, SuperSprite demo, and AD8088 MS-DOS HGR cube.
- [FATDOG MAGIC](demos/fatdog_magic/README.md): a bootable 32 MB
  ProDOS gallery with an HGR folder menu and 32 images converted by FATDOG
  in Standard HGR and 20 in Brooks SHR-3200, plus the Appletini demo image formats. Use phosphor blur
  and glow, combined with composite or TV output, for best results.
- [Appletini Invasion](demos/appletini_invasion/README.md) — an enhanced
  Apple //e fixed shooter using 33.3 MHz acceleration, DHGRi, Video-7 MIX,
  SmartPort, Mockingboard music and speech, and 8 MB RamWorks.
- [The Bilestoad, SHR port](demos/bilestoad/README.md): the 1982 game with
  its original logic, shown in SHR with 64-angle sprites and motion
  interpolated to the video rate, 12-voice Phasor sound, and sprites in
  RamWorks. The build converts the upstream game from a local clone; the game
  itself is not in this repository. Not yet tested on hardware.
- [Appletini Bosconian](demos/appletini_bosconian/README.md) — an original
  Bosconian-style multidirectional shooter for an enhanced Apple //e in
  320x200 Super Hi-Res at 60 frames per second, using the virtual TransWarp
  (33 MHz or TURBO), the virtual Phasor for music, effects and SSI-263 speech,
  and a RamWorks probe.

## Disk images

Each demo's bootable image is tracked next to its README. Mount one on an
Appletini SmartPort drive (in GSSquared, `-ds7d1=<image>`) and boot it.

| Project | Image | Size | Boots |
|---|---|---|---|
| Appletini Demos | [Appletini_Demos.po](demos/appletini_demos/Appletini_Demos.po) | 32 MB | BASIC.SYSTEM, STARTUP launcher |
| FATDOG MAGIC | [FATDOG_MAGIC.po](demos/fatdog_magic/FATDOG_MAGIC.po) | 32 MB | MAGIC.SYSTEM |
| Appletini Invasion | [Appletini-Invasion.hdv](demos/appletini_invasion/Appletini-Invasion.hdv) | 800 KB | INVASION.SYSTEM |
| The Bilestoad, SHR port | [Bilestoad.po](demos/bilestoad/Bilestoad.po) | 800 KB | TOAD.SYSTEM |
| Appletini Bosconian | [Appletini-Bosconian.hdv](demos/appletini_bosconian/Appletini-Bosconian.hdv) | 800 KB | BOSCO.SYSTEM |

Each image is the `dist/` output of its project's build, copied next to the
README at the commit that built it; the build directories themselves are not
tracked. The Bilestoad image contains the converted upstream game, which has
no licence: check its rights before you redistribute that image.

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
