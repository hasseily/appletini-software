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
