# Pinball Construction Set for the Appletini: design

This is the interface contract of the port. It records the decisions; the
reasons are in the source comments and in the README.

## 1. What is ported

Bill Budge's Pinball Construction Set (Apple II, 1982, MIT licence, source at
<https://github.com/billbudge/PCS_AppleII>): nine Merlin-syntax 6502 modules.
The port keeps the original logic — the editor's tools and state machines
(EDIT.S), the polygon database and scan converter (PPAK.S), the wiring kit
(WIRE.S), the physics, part behaviours and both play shells (RUN.S, RUN2.S) —
and replaces everything that touches the Apple II hardware: the HGR drawing
library (CDRAW.S), the joystick cursor, the speaker click sequencer, DOS 3.3
(BOOT2.S, SWAP.S, DISK.S), and the HGR-specific pixel editor (the magnifier
in EDIT.S).

Target: an enhanced Apple //e with an Appletini ONE card, the virtual
TransWarp at 33 MHz, Super Hi-Res 320x200 at 60 frames per second, the
mouse card in slot 2, the Phasor in slot 4, RamWorks memory. Booted from an
800 KB ProDOS image.

## 2. Hardware facts (verified in appletini-one, see the Bosconian design)

1. SHR framebuffer at AUX `$2000 + 160*y`, byte `x/2`, high nibble = left
   pixel; SCBs at AUX `$9D00-$9DC7` (bits 3:0 = palette); palettes at AUX
   `$9E00 + 32*p`, entries little-endian `$0RGB`; AUX `$9DF8-$9DFF` must be 0.
   Enable with `STA $C000` (80STORE off) then `$C1 -> $C029`; disable with
   `$01`. RAMWRT (`$C005`) routes writes to AUX; reads stay in main.
2. Every write to AUX `$2000-$9FFF` and to main `$0400-$0BFF`, `$2000-$5FFF`
   is posted to the 1 MHz bus (512-deep queue, back-pressure). About 16,000
   posted bytes fit in one frame. A write to `$C000-$C007` or an access to
   `$C054-$C057` drains the queue first: RAMRD/RAMWRT/80STORE toggles are
   expensive, ALTZP (`$C008/9`) and the language card switches are not.
3. `$C019` bit 7 = 1 during display, 0 in blank, synthesized without a bus
   cycle. The Appletini publishes the SHR shadow at line 0. The frame's
   writes must finish before the next line 0.
4. Any slot 4 access slows the vTW to 1 MHz for 512 cycles: sound traffic
   happens in one burst per frame.
5. Mouse card in slot 2: `$C0AE` mode (bit 0 enable), `$C0A1-$C0A4` X/Y,
   `$C0A5` buttons (bit 0 left, bit 1 right), `$C0A7-$C0AC` clamps, `$C0AF`
   ACK. Five reads per frame. Slot ROM ID at `$C205=$38 $C207=$18 $C20B=$01
   $C20C=$20`.
6. RamWorks bank select `$C073` (0 = base aux). Under the vTW the machine
   always has 8 MB.
7. The speaker at `$C030` works but is not captured by the card and runs at
   the wrong pitch at 33 MHz: all sound goes to the Phasor.
8. `$C074 = 0` at start releases a 1 MHz lock; never write 3.

## 3. Screen layout and palette

SHR 320x200, 320 mode, one palette for every line.

| Region | x | y | Content |
|---|---|---|---|
| table | 0-153 | 0-191 | the playfield, 1:1 with the original's 154x192 polygon units |
| table border | 154-157, rows 192-199 | | frame colour |
| parts menu | 160-255 | 0-191 | part icons at their template positions (x <= 255 because template x is a byte) |
| tool strip | 258-319 | 0-191 | tool, colour and mode icons |
| logo band | 160-319 | 0-63 | shown instead of the parts menu in play, magnifier and disk modes |

The database keeps the original units (x 0..255, y 0..191, table 0..153),
so the physics and every saved table are unchanged. One polygon unit is one
SHR pixel.

Palette 0 (index: colour, use):

| 0 | black | table background, transparent in sprites |
| 1 | dark grey `$333` | panel background, sprite outlines |
| 2 | grey `$777` | steel, shading |
| 3 | light grey `$BBB` | steel highlight |
| 4 | white `$FFF` | paint, text, ball highlight |
| 5 | dark red `$900` | rubber shadow, wood |
| 6 | red `$F33` | paint, flipper rubber |
| 7 | orange `$F80` | paint, lit bumpers |
| 8 | yellow `$FF3` | paint, lit targets |
| 9 | dark green `$063` | shading |
| 10 | green `$3C3` | paint |
| 11 | navy `$124` | shading, default table border |
| 12 | blue `$39F` | paint, plastics |
| 13 | cyan `$6EF` | paint |
| 14 | violet `$93E` | paint |
| 15 | brown `$963` | wood, launcher spring |

The brush offers eight paint colours: white, red, orange, yellow, green,
blue, cyan, violet; painting an object with its own colour makes it black
(invisible, vertices shown), as in the original.

## 4. Rendering model

The original draws by XOR into HGR and erases by drawing again. The port is
retained: the screen is a function of the state, and the original's draw
calls become state changes that mark rectangles dirty. Once per frame the
dirty rectangles are rendered into a main-memory arena and copied to SHR
memory in one burst with RAMWRT on.

Layers of the table region, back to front:

1. Background: for each row, fill with the border object's colour outside
   the border polygon's spans (the original's complement fill, limit 153),
   black inside, then every span record of the row in order (painter's
   order = object order) with the object's colour. Colours 0 (black) and
   `$10` (inviso, the parts' collision polygons) paint nothing. The span
   database is the original's (`PBTBL`-style per-row records `XL, OBJ, XR,
   codes`), so what is drawn is exactly what the ball hits.
2. Overlay: the magnifier's pixel edits, 4 bits per pixel, 77 bytes per row
   for 192 rows in RamWorks bank 1 at `$2000 + 160*y` (same addresses as the
   SHR row, only bytes 0..76 used). Nibble 0 = no edit. A 60-byte tile map
   (20x24 tiles of 8x8) says which tiles hold edits so untouched rows cost
   nothing; edited rows are fetched through the stack-page routine
   `aux_fetch` (RAMRD on for the copy).
3. Sprites: every library object in the database, drawn opaque with
   per-pixel transparency (nibble 0) at its L-record position and frame.
4. Editor overlays: vertex dots (points mode, or black polygons), the
   floating object being dragged (its spans painted from a fresh scan
   conversion), wires (wiring kit, horizontal and vertical segments), the
   magnifier's viewer frame.
5. Cursor: drawn last, over everything, with save-under. The bytes under
   the cursor are read from AUX by `aux_fetch` (one RAMRD toggle pair per
   frame), and restored before anything else is drawn.

The panel is drawn in immediate mode with the same primitives (sprite,
text, rectangle fill, rectangle frame), because nothing there is ever
erased except by redrawing a rectangle of panel colour or by the cursor
save-under. Menu highlights are frames in the highlight colour, removed by
redrawing them in panel colour; the boxes in the layout tables leave a
2-pixel margin around their icons so a frame never touches an icon.

Dirty rectangles: up to 32 per frame, clipped, merged when they overlap.
The renderer draws each rectangle into the arena (77x40 bytes), rendering
rows in bands when a rectangle is taller. In play the only dirty
rectangles are the balls' old and new boxes and the parts that changed
frame, well under 2,000 posted bytes per frame. In the editor a full table
redraw is 14,784 bytes: drags re-render only the union of the old and new
bounding boxes.

Sprite blit: pre-shifted even and odd variants (Bosconian's run format:
height, width in bytes, per row runs of `offset|MORE, len, bytes`), with
the arena updated through a 256-entry keep-mask table so nibble 0 is
transparent per pixel (Bilestoad's inner loop). Sprites live in the
auxiliary language card (`$D000-$FFEF` bank 2 and `$D000-$DFFF` bank 1,
loaded from `PCS.SPR` by the loader); the blitter switches ALTZP on for the
whole sprite pass and reads its inputs from absolute main memory.

## 5. What is kept, what is replaced

Every module is converted by `tools/merlin2ca65.py`. `src/drops.json`
names the label ranges that are dropped and re-implemented in the port;
`src/patches.json` names single lines that are rewritten. Everything else
is byte for byte the original code, assembled with real symbols instead of
the hard-coded `EQU` chains (the converter asserts the original layout in
baseline mode: the nine modules assemble to the sizes and checksums in
`tests/test_convert.py`).

CDRAW.S: dropped entirely except the 16-bit pointer helpers (`ADDIYX`,
`ADDYX`, `SUBIYX`, `SUBYX`, `CMPYX`), `MOVEUP`/`MOVEDOWN`, `INRECT`,
`DOMENU`/`SELECT` (rect format changed) and the text routines' interface.
`src/cdraw.s` provides every entry point with the same register interface:

| Entry | Port semantics |
|---|---|
| `SETMODE` | records the pen mode (only GRAB/STORE matter: `SAVELOGO`/`DRAWLOGO`) |
| `DRAWBITS`, `XOFFDRAW` | draw the 7-byte bitmap record as a sprite: icons in the panel are drawn at once; L-records of library objects mark the object dirty (the renderer draws them) |
| `HLINE`, `VLINE` | wiring-kit segments: add or remove a wire item |
| `FRAMERECT`, `DRAWRECT` | frame or fill a rectangle in the pen colour; in pen mode CLR the panel colour |
| `INRECT`, `CRSRINRECT` | hit tests with 16-bit x |
| `GETBUTNS` | mouse button or Open/Closed Apple |
| `INITCRSR`, `XDRAWCRSR`, `UPDATECRSR`, `DOCRSRX`, `DOCRSRY`, `GETCURSORX`, `JSCTRL` | cursor shape, hide/show, mouse read, frame pacing |
| `DOMENU`, `SELECT` | as the original with frame highlights |
| `INIT` | clear the table region and the panel |
| `CHARTO`, `PRCHAR`, `PRINT`, `CHAR` | text in the 5x7 font, 16-bit x |

Rectangle records become `top, x lo, x hi, height-1, width lo, width hi`
(6 bytes, same size, generated by `tools/layout.py` from a layout table).
Bitmap records keep 7 bytes: `ptr, y, x lo, x hi, height, width`.

PPAK.S: kept. `DOBAR` (the span painter) is replaced by `span_paint`
(opaque nibble fill into the arena or, in no-merge mode, the floating
object's paint list); `POLYPOINTS` marks the object dirty (dots are a
render-time overlay); `SETCOLOR` records the colour index.

EDIT.S: kept. Patches: L-record x is one byte (`+3`) and `+4` is unused;
`DRAGOBJ2`'s cursor snap uses the pixel x; `PAINTOBJ` sets the new colour
and calls `obj_repaint` instead of XOR-drawing the pattern difference;
`POINTSON`/`POINTSOFF` set the points flag; `SAVELOGO`/`DRAWLOGO` show and
hide the logo; `CLEARKIT` fills the panel; the magnifier (`MAGSTART` to
`MBAR4`) is dropped and rewritten in `src/magnify.s`; the world screen
keeps its logic with generated rectangles.

WIRE.S: kept. `DRAWWIRE` adds or removes a wire item; `DRAWPOLYS` toggles
the "hide polygons" render flag.

RUN.S: kept. `XOFFDRAW` calls from `ADVANCE`/`RETREAT`/`DRAWTARG`/ball
moves become dirty marks (the renderer draws the current frame). The
flipper frame tables become uniform (`FXDVERT` 0, `FXHEIGHT` constant,
`FXLEN` = frame stride) and `FDDVERT` is re-based to the union box
(`0,0,0,0,0,0,-2,-4` and `0,2,1,0,0,0,-2,-3`). The `PLAY7` loop is replaced
by a frame loop: wait for line 0, read input, run N ticks of the original
tick body (`tick_body`, the loop without WAIT and paddle reads), render,
sound. `PUTSP` masks the noise nibble with `$70`. `LAUNCHHIT` reads the
port's launch button; `PDL1` is the plunger charge.

RUN2.S: kept. Player state pages and sleepers move to BSS (sleeper pitch
23, at most 8 sleepers); the frame loop is the port's; `RELOAD` becomes a
return; `MBALL`/`MAKEBALL` draw the balls-left icons through the panel
primitives; the player prompt uses the port's text.

DISK.S, SWAP.S, BOOT2.S: dropped; `src/files.s` is the ProDOS file UI.

## 6. Data structures

The object database is the original's, at its original addresses relative
to `PBBASE`: `LOGIC` (24), `WSET` (4), `PBDATA` (count, sizes, records),
the span gap buffer, `PBDX` (192) at `$BA40`. `PBBASE` is a link
symbol; the port places the database at `$9200-$C0FF`... no: at
`DB_START` in main memory outside the mirrored ranges (see section 8).

L-record (library object, at `OBJ + 3 + 2*vertices`):

| +0,1 | sprite pointer of the current frame (`ADVANCE`/`RETREAT` add `+7`) |
| +2 | y |
| +3 | x (pixel, 0..255) |
| +4 | 0 |
| +5 | height (rows) |
| +6 | width (pixels) |
| +7 | frame stride (bytes per frame, constant per part) |
| +8 | TIME mask at rest, frame/state in play (unchanged) |
| +9 | score, noise, not-wireable (unchanged) |
| +10..15 | RUN, INIT, HIT vectors (unchanged) |
| +16.. | per-part state (unchanged) |

The sprite pointer selects a record in the sprite directory
(`spr_dir`), not raw pixel data: `ptr = spr_dir + 4*id` where the directory
holds even/odd variant addresses. `+7` is therefore 4 for every part, and
frames are consecutive directory entries.

FILLCOLOR: 0 = black (invisible, vertices shown), 1..15 = palette index,
`$10` = inviso (library objects). The original even codes are translated on
import: 2 green -> 10, 4 violet -> 14, 6 white -> 4, 8 -> 0, 10 red -> 6,
12 blue -> 12, 14 -> 4.

Part kinds: the 43 templates of RUN.S in EDIT's order (`OBJLEN`), kind 0
being the plain polygon. `kind_table` gives per kind: frame-0 sprite id,
frames, stride, height, width, vectors. A saved file stores `kind` and
`frame` in L-record bytes +0/+1 and restores the pointer, +5..+7 and
+10..+15 from the table on load, so files do not depend on the build.

## 7. Memory map

| Range | Use |
|---|---|
| main `$0000-$00FF` | the original's zero page (`$00-$26`, `$80-$E4`), port scratch `$E5-$FF` |
| main `$0110-$017F` | `aux_fetch` (stack page: RAMRD does not move pages 0 and 1); the stack runs down from `$01FF` |
| main `$0300-$0328` | debug mailbox |
| main `$0C00-$1FFF` | BSS: variables, `PBTBL`/`V`/`RCN`/`TIME`, player state, sleepers, dirty list, arena (3,080 bytes) |
| main `$2000-$97FF` | `PCS.SYSTEM`: code and read-only tables (never written, so the mirror costs nothing) |
| main `$9C00-$BAFF` | the object database: `PBBASE = $9C00` (`LOGIC`, `WSET`, `PBDATA` at `+$1C`), the span gap buffer (7.7 KB in all, twice the original's), `PBDX` at `$BA40-$BAFF` |
| main `$BB00-$BEFF` | ProDOS file buffer while loading or saving |
| aux `$2000-$9FFF` | SHR pixels, SCBs, palette |
| aux language card | sprites and icons (`PCS.SPR`) |
| RamWorks bank 1 `$2000-$9FFF` | overlay layer (pixel edits) |
| RamWorks bank 1 `$A000-$BFFF` | raw-row pictures (the 160x60 logo), fetched row by row |

The exact addresses are in `src/pcs.cfg`; `tools/build_system.py` refuses
an image that reaches `PBBASE`.

## 8. Timing

The original runs its tick loop as fast as the CPU allows (1.5 to 11 ticks
per frame at 1 MHz depending on the speed slider and the load). The port
runs a fixed number of ticks per frame from the speed slider (`WSET+1`):

| speed | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| ticks per frame | 1.5 | 2 | 2.5 | 3 | 4 | 5 | 6 | 8 |

as a 4.4 fixed-point accumulator. `PTM1` keeps its exact wrap semantics;
every part's TIME mask, gravity, wiring and sound cadence hang off it. The
default of a new table is speed 4.

## 9. Input

Editor: the mouse (absolute; the card is clamped to the screen minus the
cursor size) with the left button as the button; the arrow keys move the
cursor by 1 pixel (4 with shift) and Space is the button for keyboard-only
use; paddles are read as a rate controller if no mouse card is present.
Play: Open Apple / `Z` / left mouse button = left flipper, Closed Apple /
`/` / right mouse button = right flipper, Space held = pull the plunger,
released = launch; Esc = quit, Ctrl-S = sound toggle, `1`-`4` players.

## 10. Sound

The Phasor driver from the Bilestoad port (VIA timer 1 as the clock, no
interrupts) with an effect engine: `DOSND(A)` (RUN.S, RUN2.S, WIRE.S) takes
the original EFFECTS offset (0, 4, 12, 20, 36, 56, 76 for noise 1..7) and
starts the matching AY effect with the original's priority rule (a new
effect replaces the current one only if its code is not lower). The seven
effects follow the original contours: 1 = two-tone tick, 2 = falling
sweep, 3 = rising sweep, 4 = alternating then sweep, 5-7 = arpeggios. The
SSI-263 speaks "PLAYER ONE".."PLAYER FOUR", "GAME OVER", "MULTIBALL" and
"BONUS" in the game shell. `STGL` (Ctrl-S) mutes everything.

## 11. Files

`PCS.SYSTEM` (the program), `PCS.SPR` (sprites, loaded into the aux
language card), `PCS.TITLE` (32 KB SHR picture), tables `*.PCS`.

Table file: `"PCS1"`, 4 bytes; WSET (4); LOGIC (24); object count and
sizes and records as in memory (L-record bytes +0/+1 = kind, frame);
then the overlay: `"OVL1"`, 60-byte tile map, RLE of the edited tiles
(`01 nn` = nn zero bytes, `01 01` = end, `nn` = nn literal bytes, as the
original's picture RLE). `tools/pb2pcs.py` converts an original `.PB`
file (DOS 3.3 binary) into this format: kinds from the original vectors,
colours translated, the HGR picture ignored.

## 12. Fidelity policy

Kept as the original: the CATCH1 capture semantics, score x10 and bonus
x1000 display, the slope code 16 truncation, ball-ball pass-through, the
XOR cursor parity rules (as hide/show pairs). Fixed: `PUTSP`'s unmasked
noise nibble, the sleeper pitch (23), `PBTBL[0]` initialised, `MOVEDOWN`
exact.

## 13. Build and test

`make` converts the upstream sources (a local clone of the MIT-licensed
repository, or `upstream/` in the tree), generates the assets and tables,
assembles with ca65, links with ld65, and writes `dist/Appletini-PCS.hdv`.
`make test` runs the py65 unit tests; `make run` renders screenshots of
the editor and of a play session in the test machine and prints per-frame
cycle and bus-byte statistics.
