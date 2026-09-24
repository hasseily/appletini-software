# Pinball Construction Set for the Appletini

Bill Budge's Pinball Construction Set (Apple II, 1982) on an enhanced
Apple //e with an Appletini ONE card: Super Hi-Res 320x200 in 16 colours at
60 frames per second, the mouse in the hand, sound on the Phasor. The port
is built from the MIT-licensed Merlin sources Bill Budge published at
<https://github.com/billbudge/PCS_AppleII>: the editor, the polygon database
and scan converter, the physics, the 43 parts and their behaviours, the
wiring kit and the play shells are his code, converted to ca65 at build time
and assembled byte for byte as they were; what the port writes anew is
everything that touched the Apple II hardware (the HGR drawing library, the
joystick cursor, the speaker click sequencer, DOS 3.3 and the HGR pixel
magnifier). `docs/DESIGN.md` is the contract; this file says what is there
and how to build, run and test it.

Status: builds, passes its unit tests (`make test`, 222 tests), builds the
disk image, and runs in the project's py65 test machine: the title, the
editor with its tools, the parts kit, the wiring kit, the world settings,
test play, the magnifier, the disk menu (load, save, catalog) under a
modelled ProDOS, and the game shell. It is **not yet tested on hardware**
or under ProDOS in an emulator (see "Not done" below).

## What the port keeps and what it replaces

| Upstream module | In the port |
|---|---|
| `EDIT.S` (the editor: tools, kit, drags, world screen) | kept; a few lines patched (`src/patches.json`, `tools/layout.py`) |
| `PPAK.S` (polygon database, scan converter) | kept; the span painter and the vertex dots are render hooks |
| `WIRE.S` (the wiring kit) | kept; wires and the "hide polygons" flag are render items |
| `RUN.S` (physics, part behaviours, test play) | kept; the tick loop is paced by the frame, draws become dirty marks |
| `RUN2.S` (the game shell: players, balls, sleepers) | kept; reached from the disk menu's PLAY GAME, the player prompt is the port's |
| `CDRAW.S` (HGR library, cursor, text, menus) | replaced by `src/cdraw.s` + `src/render.s` + `src/video.s` with the same entry points |
| `BOOT2.S`, `SWAP.S`, `DISK.S` (DOS 3.3) | replaced by `src/crt0.s`, `src/loader.s`, `src/files.s` under ProDOS |
| the magnifier in `EDIT.S` | dropped; `src/magnify.s` edits a 16-colour overlay layer |

`tools/merlin2ca65.py` converts the nine modules. In its baseline layout
the output assembles to the nine upstream binaries byte for byte
(`tests/test_convert.py` checks the sizes and MD5s); in the port layout the
hard-coded address chains become imports, `src/drops.json` removes the
routines the port re-implements and `src/patches.json` rewrites single
lines, each of which names the upstream line it expects so drift is caught.
`build/port/*.s` after a build is exactly the code the port runs.

The database keeps the original's units (table x 0..153, y 0..191, one
polygon unit = one SHR pixel), so the physics and every table are
unchanged, and what is drawn is exactly what the ball hits: the renderer
paints the span records the collision code uses.

## Hardware

An enhanced //e with the Appletini ONE: the virtual TransWarp at 33 MHz,
SHR 320x200 (one palette), the mouse card in slot 2, the Phasor in slot 4,
RamWorks memory (bank 1 holds the overlay layer and the logo picture). The
program is a ProDOS 8 system file on an 800 KB image. Without a mouse card
the paddles move the cursor as a rate controller and the keyboard does the
rest.

## Screen

| Region | x | Content |
|---|---|---|
| table | 0-153 | the playfield, 1:1 with the original's 154x192 units |
| parts menu | 160-265 | the 43 part icons at their original template positions |
| tool strip | 264-319 | two columns of tool icons and the eight paint cans |
| logo band | 160-319, rows 0-63 | replaces the parts menu in play, magnifier and disk modes |

Palette 0 (`docs/DESIGN.md` section 3): black, three greys, the eight
paint colours (white, red, orange, yellow, green, blue, cyan, violet) and
four shading colours (dark red, dark green, navy, brown) for steel, rubber,
wood and plastics. Painting an object with its own colour makes it black
(invisible, vertices shown), as in the original.

## Modes

- **Editor** (`EDIT.S`): the hand drags a part out of the kit onto the
  table or moves one that is there (a part dropped back on the panel is
  deleted); the pointer drags a polygon vertex; the scissors cut a vertex
  and the hammer pastes one; the brush paints an object with the selected
  can. Drags accept up to 63 pixels of cursor movement per frame (the
  original's 15 suited a joystick).
- **Test play** (the Play tool, `RUN.S` `PLAY`): the logo band replaces the
  kit and the score lines print in the panel; Esc returns to the editor
  with the table as it was.
- **Wiring kit** (`WIRE.S`): six AND gates, seven sound notes, score and
  bonus boxes, the hand, pliers and screwdriver; the table is shown with its
  polygons hidden while wiring. QUIT returns to the editor.
- **World settings**: the gravity, speed, kick and elasticity sliders
  (`WSET`) and QUIT. The speed slider sets the ticks per frame (section 8
  of the design: 1.5, 2, 2.5, 3, 4, 5, 6, 8 for positions 0 to 7, a new
  table starts at 4).
- **Magnifier** (`src/magnify.s`, design section 14): a 16-colour pixel
  editor of the overlay layer (4 bits per pixel in RamWorks bank 1, drawn
  over the polygons and under the parts; a tile map keeps untouched rows
  free). Below the logo band: a 32x24-pixel window of the table at 4x, the
  sixteen colours (0 erases), QUIT and a grid toggle. Press on the table to
  centre the window there (a drag pans), press in the window to paint, on a
  palette box to pick; `0`-`9`/`A`-`F` pick, `G` toggles the grid, Esc
  leaves. The table shows every stroke in the same frame.
- **Disk** (`src/files.s`): LOAD, SAVE, EDIT, QUIT and PLAY GAME under
  ProDOS, with the catalog of the prefix directory's `.PCS` files (up to
  11). SAVE asks for a name (letters, digits, periods; Return or Esc); a
  corrupt file is refused with NOT A TABLE and the table kept; QUIT asks
  twice, then exits to ProDOS. Keys `L`, `S`, `E`, `Q`, `P`, Esc.
- **Game shell** (`RUN2.S`, PLAY GAME): one to four players (a prompt with
  four digit boxes, or the keys `1`-`4`), five balls each, balls left in the
  panel, captured balls (sleepers), the speech phrases; Esc ends the game
  and returns to the disk menu.

## Controls

Editor: the mouse, its left button as the button. The arrow keys move the
cursor one pixel per frame (four once a key has been held for more than
15 frames) and Space is the button, so the editor works from the keyboard
alone; without a mouse card the paddles move the cursor.

Play: Open Apple, `Z` or the left mouse button is the left flipper; Closed
Apple, `/` or the right mouse button the right one. Space (or the down
arrow) held pulls the plunger (the charge grows 4 a frame to 255);
released, it launches at the charged strength. Esc quits play, Ctrl-S
toggles the sound, `1`-`4` choose the players in the game shell.

## Video

- SHR 320x200, 16 colours, framebuffer in AUX `$2000-$9FFF`, one palette.
- The screen is a function of the state (`docs/DESIGN.md` section 4). The
  original drew by XOR and erased by drawing again; the port's draw calls
  mark rectangles dirty, and once per frame the dirty rectangles (up to 32,
  merged when they touch) are rendered into a 1,001-byte arena in main
  memory and copied to AUX in one burst with RAMWRT on. A table row is the
  border colour outside the border polygon's spans, black inside, then the
  span records in object order, then the overlay row if its tiles hold
  edits, then the parts' sprites, the vertex dots, the floating object
  being dragged, the wires and the highlight frames. The cursor is drawn
  last with save-under.
- Sprites are pre-shifted even and odd variants of run-encoded rows
  (Bosconian's format) drawn with a keep-mask table so a zero nibble is
  transparent (the Bilestoad blitter). They live in the auxiliary language
  card, loaded from `PCS.SPR`; the blitter keeps ALTZP on for the whole
  sprite pass.
- The panel is drawn in immediate mode with the same primitives (sprite,
  7-row text, rectangle fill, frame); nothing there is erased except by
  drawing the panel colour over it.
- Under the vTW every write to AUX `$2000-$9FFF` (and to main
  `$0400-$0BFF`, `$2000-$5FFF`) is posted to the 1 MHz bus, about 16,000
  per frame; a soft-switch access drains the queue first. So the variables
  live in `$0C00-$1FFF`, the database at `$A000`, the code is never
  written, and RAMWRT is switched once per copy.

## Sound

The Phasor driver of the Bilestoad port (VIA timer 1 as the clock, no
interrupts) with an effect engine: `DOSND` in `RUN.S`, `RUN2.S` and
`WIRE.S` keeps the original's priority rule and starts the AY effect that
follows the contour of the original's seven click sequences (two-tone tick,
falling and rising sweeps, an alternating sweep, three arpeggios). The
SSI-263 speaks PLAYER ONE to PLAYER FOUR, GAME OVER, MULTIBALL and BONUS
in the game shell. All slot 4 accesses happen in one burst per frame; a
quiet frame costs none. Ctrl-S (`STGL`) mutes everything.

## Memory

| Range | Use |
|---|---|
| main `$0000-$00FF` | the original's zero page (`$00-$26`, `$3E`, `$80-$E4`); the port's variables at `$40-$7F` |
| main `$0110-$017F` | `aux_fetch` and `aux_store` in the stack page (RAMRD/RAMWRT do not move pages 0 and 1) |
| main `$0300-$0313` | debug mailbox (`PCS1`, state, frame, bytes written, cursor, input, ticks, mouse, RamWorks, sound) |
| main `$0C00-$1FFF` | BSS: the original's fixed tables (`PBTBL`, `V`, `RCN`, `TIME`), player state, sleepers, dirty lists, cursor save-under |
| main `$2000-$9FFF` | `PCS.SYSTEM`: entry code, read-only tables, code |
| main `$A000-$BAFF` | the object database: `LOGIC`, `WSET`, `PBDATA`, the span gap buffer, `PBDX` at `$BA40` |
| main `$BB00-$BEFF` | the render arena; the ProDOS file buffer while a file is open |
| aux `$2000-$9FFF` | SHR pixels, SCBs, palette |
| aux language card | sprites and icons (`PCS.SPR`) |
| RamWorks bank 1 | `$2000-$9FFF` the overlay layer, `$A000-$BFFF` the logo rows |

`build/PCS.map` has the sizes; `tools/build_system.py` refuses an image that
reaches `$A000`.

## Build

```sh
make            # build/PCS.SYSTEM and build/PCS.SPR (+ PCS.lbl, PCS.map, the seed tables)
make test       # the unit tests in tests/ (py65; about two minutes)
make baseline   # the upstream modules converted and assembled unchanged, in build/baseline
make disk       # dist/Appletini-PCS.hdv, an 800 KB ProDOS image
```

Needs cc65 (`ca65`, `ld65`), Python 3 with py65 (the tests and the run
scripts) and Pillow (screenshots and the sprite preview), and a clone of
<https://github.com/billbudge/PCS_AppleII>: `upstream/` in this directory,
or `/home/user/billbudge/pcs_appleii`, or `make UPSTREAM=/path`. The
enhanced //e ROM for the test machine and the ProDOS master image come from
the appletini-one checkout: `APPLETINI_ROOT=/path/to/appletini-one` (the
default is `../../../appletini-one`; the ROM is `docs/Apple2e_Enhanced.rom`
there and the master image `software/ProDOS_2_4_3.po`). The tests fall
back to a blank ROM when the file is missing, because the port never reads
the //e ROM in the test machine.

The build converts the upstream sources (`build/port/*.s`), generates the
sprites from the text art in `assets/` (`tools/gen_assets.py`, with the
part shapes read from the upstream `RUN.S` by `tools/parts.py`), the kit
and tool layout patches (`tools/layout.py`), the kind table and template
patches (`tools/kinds.py`), the seed tables (`tools/make_tables.py`),
assembles everything with ca65 and links with ld65 (`src/pcs.cfg`).

`make disk` (`tools/build_disk.py`) writes an 800 KB ProDOS volume
`A13PCS` with `PRODOS`, `PCS.SYSTEM`, `PCS.SPR` and the seed tables from
`build/tables/`; `appletini-pcs.gs2` is a GSSquared configuration for it
(mouse in slot 2, Mockingboard/Phasor in slot 4, the Appletini in slot 7).

## Test

`tools/a2sim.py` is the Bilestoad and Bosconian ports' //e model on py65
(auxiliary memory and RamWorks, the language card, VBL, keyboard, paddles,
the Phasor, and for this port the Appletini mouse card in slot 2), with
SHR rendering to PNG.

```sh
make test                                   # tests/test_*.py, each also runs on its own
python3 tests/test_render.py TestBlitSprite # one class
```

| Test file | Checks |
|---|---|
| `test_convert.py` | the converter reproduces the nine upstream binaries (sizes, MD5); the port layout converts and assembles; every patch's `expect` line still matches the upstream; drops and exports name real labels |
| `test_assets.py` | the sprite generator: encoding, ids, regions, `PCS.SPR`, font, palette, against a fixture and the real art |
| `test_render.py` | the renderer in the linked build through `tools/pcsdbg.py`: `fill_span` ends and clipping, `render_row`, `blit_sprite` clipping on four sides and odd x against the decoded sprite, `rd_mark` clamping, `merge_rects`, the cursor save-under round trip, `panel_fill` at odd edges, record ids, `DOMENU`, `CHARTO`/`PRINT` |
| `test_tables.py` | `tools/make_tables.py` writes a valid table (records, downward first edges, parts on the table, the `PCS1`/`OVL1` chunks) and `table_normalise` resolves every L-record against `build/assets.inc` and the `RUN.S` templates |
| `test_input.py` | the mouse card detection and set-up, clamps, arrow keys, buttons, flippers, the plunger, paddles, the `$C0xx` budget |
| `test_sound.py` | the Phasor driver: probe, effects, priorities, speech, mute |
| `test_editor.py` | end to end through `tools/run_editor.py`: boot to the editor, a part dragged from the kit onto the table (and one dropped back deleted), the Play tool, the plunger launch, a flipper key, Esc back to the editor, the frame budget, the screenshots |
| `test_magnify.py` | the magnifier: entry and exit, the window and its recentring, painting and erasing pixels in bank 1 and the tile map, the grid, edits surviving a part dragged over them |
| `test_files.py` | the disk menu with the fake ProDOS: the table file format (RLE, overlay chunk), catalog, select and load, save with a typed name, an overlay round trip, corrupt files refused, PLAY GAME and Esc, QUIT's confirmation, the title |
| `test_disk.py` | `tools/build_disk.py`: the volume, directory, bitmap and every file read back |

`tools/run_editor.py` boots `build/PCS.SYSTEM` in the machine, drives it
with the mouse and keyboard, and saves screenshots to `build/run/`. Without
`--prodos DIR` there is no ProDOS (the script fills the auxiliary language
card from `build/PCS.SPR` itself and the disk menu reports NO PRODOS); with
it, `tools/a2sim.py`'s fake ProDOS serves the files of `DIR` as the volume
and the program loads `PCS.SPR` through the MLI as on the real disk. The
title screen waits for a click or key; `--skip-title` (a mailbox hook,
`MB_NOTITLE`) starts in the editor, as the tests and `tools/pcsdbg.py` do.
The idle wait for line 0 is skipped, so a run costs the frames' work only:

```sh
python3 tools/run_editor.py --frames 300 \
    --do "3:move 174 56" --do "5:down" --do "8:drag 120 50" --do "11:drag 60 40" --do "14:up" \
    --do "40:click 306 43" --do "70:hold 32" --do "95:release" --do "280:key 27" \
    --shot 30 --shot 130 --stats build/run/stats.json
```

Actions are `FRAME:move X Y`, `down`, `up`, `click X Y`, `drag X Y`, `key K`,
`hold K`, `release`, `shot NAME`. Every frame prints the mailbox state, the
CPU cycles of work, the bytes that would use the 1 MHz bus, the `$Cxxx`
accesses, the SHR bytes written and the cursor; a screen is saved whenever
the state changes and at the end (`final.png`). `--stats FILE` writes the
same numbers as JSON with the median, 99th percentile and maximum, and
`--trace LABEL` prints the registers whenever a routine is entered.
`tools/pcsdbg.py` boots the same machine from a Python script and calls any
labelled routine with registers and variables set (`build/PCS.lbl` holds
every label), which is how `tests/test_render.py` works.

### Measurements

Modelled 33 MHz (one frame = 561,990 CPU cycles and about 16,000 bytes on
the 1 MHz bus), over a 420-frame scripted session in the test machine: a
bumper dragged from the kit to the table, the Play tool, a plunger launch,
both flippers, a second launch, Esc.

| Frames | CPU work (cycles) median / 99 % / max | Bus bytes median / max | `$Cxxx` accesses median / max |
|---|---:|---:|---:|
| editor, idle (cursor only) | 17,330 / 17,331 / 17,331 | 192 / 192 | 62 / 62 |
| editor, dragging a bumper | 82,200 / 125,164 / 125,164 | 346 / 788 | 72 / 129 |
| test play (353 frames after the switch) | 30,996 / 151,085 / 157,746 | 24 / 648 | 12 / 52 |
| mode switch, editor to play (2 frames) | 652,792 and 1,222,596 | 21,052 and 15,764 | 356 |
| mode switch, play to editor (2 frames) | 980,859 and 1,058,713 | 21,487 and 14,952 | 419 |
| boot (2 frames) | 2,503,267 and 1,039,290 | 70,863 and 14,976 | 468 |

No play or editor frame went over the budget; the switches cost two frames
each (a full table render is 14,784 bytes, the kit redraw 57 panel sprites)
and the boot two (the SHR clear, the palette, the table, the kit). In play
the only SHR writes are the balls' old and new boxes and the parts that
changed frame (at most 817 bytes in a frame of that session), the `$Cxxx`
count is the mouse and keyboard reads, one RAMWRT pair per copied
rectangle, ALTZP around the sprite pass, and the sound burst on frames that
change a register. `tests/test_editor.py` checks the budget on every run.

## Files

`PCS.SYSTEM` (the program), `PCS.SPR` (the sprites, loaded into the
auxiliary language card and RamWorks bank 1 by `src/loader.s` through the
ProDOS MLI), and tables `*.PCS` (BIN files).

A table file is `"PCS1"`, then the database as in memory (`LOGIC`, `WSET`,
the object count, sizes and records), then `"OVL1"`, the 72-byte overlay
tile map (24 rows x 3 bytes, one bit per 8x8 tile) and the set tiles' 32
bytes each, in tile order, run-length coded: `nn` (1..127) = `nn` literal
bytes, `$80|nn` = the next byte `nn` times, `00` = the end. In a file and
in the built-in table every library object's L-record holds `kind, frame`
in its first two bytes; `table_normalise` (`src/main.s`) turns them into
the sprite pointer and copies the box, stride and vectors from the kind's
template on load (SAVE does the reverse), so files do not depend on the
build. `tools/make_tables.py` writes the seed tables in this format and
holds the Python encoder and decoder the tests use; a converter for
original `.PB` files (`tools/pb2pcs.py` in the design) is not written.

## Design pointers

`docs/DESIGN.md`: 1 what is ported, 2 hardware facts, 3 screen and
palette, 4 the rendering model, 5 what each module keeps and what is
patched, 6 data structures (the L-record, `FILLCOLOR`, part kinds), 7 the
memory map, 8 timing (ticks per frame), 9 input, 10 sound, 11 files and
the disk menu, 12 the fidelity policy (what quirks of the original are
kept), 13 build and test, 14 the magnifier. The source headers say why:
`src/render.s` (the renderer), `src/video.s` (the SHR primitives and the
blitter), `src/cdraw.s` (the CDRAW.S entry points), `src/input.s`,
`src/sound.s`, `src/play.s` (the tick pacing and the launcher),
`src/main.s` (the kits, the logo, `table_normalise`), `src/files.s` (the
title, the disk menu, the game shell entry), `src/magnify.s`,
`src/loader.s`, `src/tables.s` (the relocated fixed tables).

## Not done

- Hardware test on a //e with the Appletini, and a run of the disk image in
  GSSquared: every number above comes from the py65 model, and the mouse
  card, the Phasor and RamWorks bank 1 are the model's.
- The disk catalog shows at most 11 files, in directory order.
- The magnifier paints one pixel per frame while dragging (no line between
  two frames' positions).
- Speech is exercised by the sound driver's unit tests only.
- A converter for original `.PB` table files.

## Credits

Pinball Construction Set is Copyright (C) 1982 Bill Budge, released under
the MIT licence at <https://github.com/billbudge/PCS_AppleII>; the game
logic in this port is his, unchanged. The SHR blitter, the //e model, the
Phasor driver and the disk builder come from the Bilestoad and Bosconian
ports in this repository. The part sprites, icons, logo and palette are
new drawings in `assets/`.
