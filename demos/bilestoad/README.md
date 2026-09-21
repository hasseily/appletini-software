# The Bilestoad, SHR port

This is a port of The Bilestoad (Datamost, 1982) to Super Hi-Res graphics for
an Apple //e with an Appletini card. It needs the vTW accelerator (33 MHz or
TURBO), 8 MB RamWorks memory, and the Phasor in slot 4.

Status: first version. It runs in the project's test machine (see Test) and
it boots and runs in GSSquared. It is **not yet tested on hardware**.

## What the port changes

The original draws the full screen for each logic tick, and one tick takes
530,000 to 670,000 CPU cycles. At 1 MHz that is about 1.7 frames for each
second. The speed of the game and the frame rate are the same thing.

The port keeps the original game logic, byte for byte, and replaces the
routines around it:

- **Display list.** The original draws all sprites through one routine
  (`DHD`). The port records each call (shape, x, y, call site) and does not
  draw.
- **Interpolation.** For each logic tick the engine shows 32 video frames.
  Each sprite moves from its position in the last tick to its position in
  this tick. The pace of the game stays near the original (about 1.9 ticks
  for each second).
- **64 angles.** The 16 original angles of each body part become 64. A host
  tool turns each original shape by at most 11.25 degrees about its hot spot.
- **SHR.** 320 mode, 16 colours, 4 bits for each pixel. The original shape
  rows use an 8-bit grid that the HGR blit squeezes to 7 pixels for each
  byte. SHR 320 has that same 8/7 ratio, so one source bit is one SHR pixel.
- **Phasor.** Music and effects use the four AY chips (12 voices). The
  upstream disks do not hold the game's note file, so the music is a new
  arrangement of "Fuer Elise" (Beethoven, public domain). On a Mockingboard
  the driver uses the two chips that exist.

## Video timing

The Appletini publishes the SHR shadow at line 0. The engine draws each
changed rectangle into an arena in main memory that the accelerator does not
mirror. Then it waits for the **end** of VBL and copies the rectangles to SHR
memory in one burst. The burst lies between two line-0 snapshots, so a frame
cannot tear.

The engine writes only the rectangles that change. A typical frame writes
less than 1,000 bytes. The draw path makes no `$Cxxx` access between two VBL
waits; this matters in TURBO mode, where such an access waits for the 1 MHz
mirror of video memory.

The sound clock is timer 1 of the Phasor's first VIA, which counts 1 MHz bus
cycles. The tempo does not change with the frame rate or the CPU speed.

Measured in the test machine at a modelled 33 MHz, over 1,600 SHR frames of
the intro and a fight (one 60 Hz frame = 561,990 CPU cycles, and about
16,000 bytes on the 1 MHz bus):

| | median | 99 % | maximum |
|---|---:|---:|---:|
| CPU work for each frame (cycles) | 38,844 | 540,955 | 917,495 |
| Bytes on the 1 MHz bus for each frame | 0 | 5,352 | 7,706 |

14 of the 1,600 frames go over the budget of one frame. Each of them costs
one more video frame (30 fps for that moment). They are frames in which the
view scrolls, so the grid lines and all sprites move at once. These numbers
come from a model; the hardware can differ.

## Memory

| Range | Use |
|---|---|
| main `$0C00-$1FFF` | engine variables (not mirrored to the bus) |
| main `$2000-$9BFF` | system file: game logic, engine, tables, music |
| main `$9C00-$BEFF` | render arena |
| language card RAM, bank 2 | 23 sprite slots of 512 bytes |
| aux bank 0 `$2000-$9FFF` | SHR pixels, SCBs, palette |
| RamWorks banks 1-4 | 448 rotating sprites, both x phases, at `$1000` |
| stack page `$0110` | fetch routine (RAMRD does not move pages 0 and 1) |

## Build

```sh
python build.py [--upstream DIR] [--master PRODOS_IMAGE]
```

Output: `dist/Bilestoad.po`, an 800 KB ProDOS image with `PRODOS`,
`TOAD.SYSTEM` and `BILESTOAD.SPR`.

Needs Python 3 with Pillow, and `ca65`/`ld65` from cc65. `PRODOS` and the
boot blocks come from `../../../appletini-one/software/ProDOS_2_4_3.po`.

**The upstream game is not in this repository.** Its source and shape data
come from <https://github.com/historicalsource/bilestoad-apple2>, which has
no licence. The build reads a local clone (it makes one in `build/upstream`
if you give none) and converts it:

| Tool | Work |
|---|---|
| `tools/lisa.py` | DOS 3.3 reader and LISA 2.5 detokenizer. `--self-test` decodes all upstream source files and compares them with the upstream text: 0 differences. |
| `tools/lisa2ca65.py` | LISA to ca65. Drops the routines in `src/drops.json`, numbers each `DHD` call site. |
| `tools/shapedata.py` | Assembles the upstream DATA disk; reads shapes and joint tables. |
| `tools/convert_sprites.py` | 64-angle, 4-bit sprites in RamWorks bank images. |
| `tools/make_music.py` | Music event table for the Phasor driver. |
| `tools/prodos.py` | ProDOS image writer (no Java, no AppleCommander). |

`build/` and `dist/` are not tracked. Check the rights to the game before you
distribute the disk image.

## Test

`tools/a2sim.py` is a small //e model on py65: auxiliary memory, RamWorks,
language card, VBL, keyboard, a Phasor that follows
`appletini-one/hdl/apple/mockingboard.sv`, and HGR/SHR rendering.

```sh
python tools/run_baseline.py UPSTREAM --rom ROM   # the unmodified game, HGR
python tools/run_port.py --rom ROM                # the port, SHR frames
```

`ROM` is a 16 KB enhanced //e ROM, for example
`appletini-one/docs/Apple2e_Enhanced.rom`. `run_port.py` skips the ProDOS
loader and reports the CPU cycles and the bus bytes of each frame.

## Run in GSSquared

`bilestoad.gs2` sets up an enhanced //e with the Appletini card in slot 7 and
a Mockingboard in slot 4. Use a GSSquared build that has the `appletini` card:

```sh
GSSquared bilestoad.gs2 -ds7d1=dist/Bilestoad.po
```

This run tests the parts that the py65 machine does not have: the ProDOS
boot, the loader (RamWorks test, prefix, reading the sprite file into the
banks) and the VBL wait. GSSquared has no Phasor native mode, so the driver
finds a Mockingboard there and plays on two chips.

## Controls

As the original. Player 1: `Q` `E` turn the torso, `A` `D` the shield arm,
`Z` `C` the axe arm, `W` `S` `X` stop each of these. Player 2: `I` `P`,
`K` `;`, `,` `/`, and `O` `L` `.`. `ESC` pauses, `CTRL-S` sets the sound on
and off, `CTRL-R` starts again.

## Not done yet

- Hardware test on a //e with the Appletini.
- The ProDOS loader (`src/boot.s`) is tested in GSSquared only.
- The sea areas in the three radar boxes.
- The page-flip dissolve between scenes (`DSOLVE`) is an empty routine.
- The title programs of the upstream disk (`OB`, `TWO`).
