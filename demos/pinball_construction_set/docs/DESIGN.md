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
| parts menu | 160-265 | 0-191 | part icons at their original template positions (`tools/layout.py` keeps them) |
| tool strip | 264-319 | 0-191 | two columns of 24x14 tool icons at x 266 and 294 (pitch 17 rows), the eight paint cans (12x8) below them at x 270 and 298; every icon sits at an even x, so these sprites store no odd variant |
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
   SHR row, only bytes 0..76 used). Nibble 0 = no edit. A 72-byte tile map
   (`ov_tiles`: 24 tile rows x 3 bytes, 20 tiles of 8x8 per row) says which
   tiles hold edits so untouched rows cost nothing; edited rows are fetched through the stack-page routine
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

Dirty rectangles: up to 32 per frame, clipped, merged when they overlap or
touch. The renderer draws each rectangle into the arena (`$BB00`, 1,001
bytes: 13 rows of 77), rendering rows in bands when a rectangle is taller.
A bitmap record marks the box its own height and width bytes describe
(RUN's `HBALL`/`VBALL` records are 6 wide or 6 tall: they cover the ball's
old and new position, as the original's XOR delta bitmaps did). In play the only dirty
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
| `DOMENU`, `SELECT` | as the original with frame highlights; the list ends with a zero word (the original's single-byte terminators are patched) |
| `INIT` | clear the table region and the panel |
| `CHARTO`, `PRCHAR`, `PRINT`, `CHAR` | text in the original 7-row font, 16-bit x (`CHAR` is the text position record `CHARBITS`: +2 y, +3 column of 7 pixels, +4 offset, which RUN's score printer edits directly) |

Rectangle records become `top, x lo, x hi, height-1, width lo, width hi`
(6 bytes, same size, generated by `tools/layout.py` from a layout table).
Bitmap records keep 7 bytes: `ptr, y, x lo, x hi, height, width`.

PPAK.S: kept. `DOBAR` (the span painter) is replaced by `span_paint`
(opaque nibble fill into the arena or, in no-merge mode, the floating
object's paint list); `POLYPOINTS` marks the object dirty (dots are a
render-time overlay); `SETCOLOR` records the colour index.

EDIT.S: kept. Patches: L-record x is one byte (`+3`) and `+4` is unused;
`DRAGOBJ2`'s cursor snap uses the pixel x; `DRAGO6` accepts the full clamped
mouse delta even across the kit and table in one frame; `PAINTOBJ` sets the
new colour and calls `OBJREPAINT`
instead of XOR-drawing the pattern difference; `POINTSON`/`POINTSOFF` set
the points flag; `SAVELOGO`/`DRAWLOGO` show and hide the logo; `CLEARKIT`
fills the panel; `PLAYSTART` is the port's `PORT_PLAY` (`play_begin`, RUN's
`PLAY`, `play_end`); `INITSLIDE` ends with `JMP MOVESLIDE` (the original
fell through into the dropped routine); `WCMDMENU` ends with a zero word;
the kit's polygon-only templates get palette fills (`tools/kinds.py`
translates their HGR colour codes); the magnifier (`MAGSTART` to `MBAR4`)
is dropped and rewritten in `src/magnify.s`; the world screen keeps its
logic with generated rectangles and the port's `MOVESLIDE` (scale and knob
sprites composited in the arena).

WIRE.S: kept. `DRAWWIRE` adds or removes a wire item; `DRAWPOLYS` toggles
the "hide polygons" render flag; `CMDMENU` ends with a zero word.

RUN.S: kept. `XOFFDRAW` calls from `ADVANCE`/`RETREAT`/`DRAWTARG`/ball
moves become dirty marks (the renderer draws the current frame). The
flipper frame tables become uniform (`FXDVERT` 0, `FXHEIGHT` constant,
`FXLEN` = frame stride) and `FDDVERT` is re-based to the union box
(`0,0,0,0,0,0,-2,-4` and `0,2,1,0,0,0,-2,-3`). The `PLAY7` loop is replaced
by a frame loop: wait for line 0, read input, run N ticks of the original
tick body (`tick_body`, the loop without WAIT and paddle reads), render,
sound. `PUTSP` masks the noise nibble with `$70`. The launcher keeps its
paddle logic: `PDL1` is the plunger charge and `LBTN` the pull; the port
holds `LBTN` down while the key charges (the plunger retreats), releases it
with the charge held for a moment (the plunger springs forward), then lets
the charge decay (section 9). The keyboard control holds a ball that lands
on the launcher during charging and gives the original `PDL1/4` kick only
after release. Both RUN and RUN2 elasticity tables use linked addresses
for the original coefficient arrays; the upstream hard-coded addresses
would point outside those arrays after relocation.

RUN2.S: kept. Player state pages and sleepers move to BSS (sleeper pitch
23, at most 8 sleepers); `PBASES` uses the linked low and high bytes of
each player page because those pages are no longer page-aligned. The frame
loop is the port's; `RELOAD` becomes a
return; `MBALL`/`MAKEBALL` draw the balls-left icons through the panel
primitives; the player prompt uses the port's text.

DISK.S, SWAP.S, BOOT2.S: dropped; `src/files.s` is the ProDOS file UI.

## 6. Data structures

The object database is the original's, at its original addresses relative
to `PBBASE`: `LOGIC` (24), `WSET` (4), `PBDATA` (count, sizes, records),
the span gap buffer, `PBDX` (192) at `$BA40`. `PBBASE` is a link symbol
(`src/pcs.cfg`); the port places the database at `$A000`, outside the
mirrored ranges (section 7).

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
`$10` = inviso (library objects). The brush handlers of EDIT.S are patched
to palette indices (white 4, red 6, orange 7, yellow 8, green 10, blue 12,
cyan 13, violet 14) and the HGR colour codes of the kit's polygon templates
are translated by `tools/kinds.py` (0/4 black -> 0, 1 green -> 10, 2 violet
-> 14, 3/7 white -> 4, 5 orange -> 7, 6 blue -> 12).

Part kinds: the 43 templates of RUN.S in EDIT's order (`OBJLEN`), kind 0
being the plain polygon. `kind_table` gives per kind: frame-0 sprite id,
frames, stride, height, width, vectors. A saved file stores `kind` and
`frame` in L-record bytes +0/+1 and restores the pointer, +5..+7 and
+10..+15 from the table on load, so files do not depend on the build.

## 7. Memory map

| Range | Use |
|---|---|
| main `$0000-$00FF` | the original's zero page (`$00-$26`, `$3E`, `$80-$E4`), the port's variables `$40-$7F`; RUN2's game variables (`PLAYER`..`GAMEMODE`) are moved from `$80-$8E` to `$27-$35` because the cursor record at `$80-$86` is written every frame, the game's included |
| main `$0110-$017F` | `aux_fetch` (`$0110`) and `aux_store` (`$0140`) in the stack page (RAMRD/RAMWRT do not move pages 0 and 1); the stack runs down from `$01FF` |
| main `$0300-$0328` | debug mailbox |
| main `$0C00-$1FFF` | BSS: variables, `PBTBL`/`V`/`RCN`/`TIME`, player state (also the loader's staging buffer), sleepers, dirty lists, cursor save-under (5,120 bytes, nearly full) |
| main `$2000-$9FFF` | `PCS.SYSTEM`: entry code, read-only tables, then code (never written, so the mirror costs nothing) |
| main `$A000-$BAFF` | the object database: `PBBASE = $A000` (`LOGIC`, `WSET`, `PBDATA` at `+$1C`), the span gap buffer (6.7 KB in all, 1.7 times the original's), `PBDX` at `$BA40-$BAFF` |
| main `$BB00-$BEFF` | the render arena (1,001 bytes); the ProDOS file buffer while loading or saving |
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
`/` / right mouse button = right flipper, Space (or the down arrow) held =
pull the plunger (the charge grows 4 a frame to 255), released = launch at
the charged strength; Esc = quit, Ctrl-S = sound toggle, `1`-`4` players.

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

## 11. Files, the disk menu and the game shell

The disk (`dist/Appletini-PCS.hdv`, 800 KB ProDOS, volume `A13PCS`,
`tools/build_disk.py`): `PRODOS`, `PCS.SYSTEM` (the program, SYS),
`PCS.SPR` (sprites, BIN aux `$D000`, loaded into the aux language card
by `src/loader.s`), tables `*.PCS` (BIN aux 0, from `build/tables`; the
seed `TABLE1.PCS` is `tools/make_tables.py`'s built-in table and the other
tables are converted from `assets/original_pb/*.PB`). The title
screen is drawn by the program (the logo band, three lines of text and
the default table), so there is no picture file.

Table file (`src/files.s`, `make_tables.pcs_file`): `"PCS1"`; LOGIC (24);
WSET (4); PBDATA as in memory: count, sizes, records, with L-record
bytes +0/+1 = (kind, frame) and bytes +5..+7, +10..+15 as the template's
(`table_normalise` rewrites them on load, `table_denorm` recovers the
kind from the sprite pointer on save: the kinds' sprite ranges are
disjoint); then the overlay: `"OVL1"`, the 72-byte tile map (`ov_tiles`:
byte `3*row + col/8`, bit `col%8`, 20x24 tiles of 8x8 pixels) and the
pixels of every set tile, 32 bytes each (8 rows of 4 bytes, the row's
bytes `4*col..4*col+3` of RamWorks bank 1 at `$2000 + 160*y`), in tile
order, run-length coded: `n` (1..127) = n literal bytes follow, `$80|n` =
the next byte n times, `0` = the end. The program writes a tile of one
value as a run and any other tile as 32 literals; the Python encoder
also finds runs inside tiles. Both decode alike. Tiles that are not set
are cleared on load; `ov_enabled` = any tile set.

The disk menu (`files_menu`, the editor's disk tool; `MB_STATE` =
`MB_ST_DISK`) keeps the logo band and draws in the panel below it: LOAD,
SAVE, EDIT, QUIT on one row, PLAY GAME on the next, then the catalog
(the BIN files named `*.PCS` of the ProDOS prefix directory, read as raw
directory blocks through OPEN/READ, up to 64 entries in directory
order, 11 per page) and a message line at the bottom. Mouse: DOMENU items with the
usual press/highlight/release protocol; a click on an entry selects it
(white), a second click on the selected entry loads it. PREV/NEXT or
keys B/N change page. Keys L, S, E, Q, P and Esc select the actions.
LOAD, EDIT and Esc return to the editor (`EDIT_REEDIT`);
SAVE prompts for a name on the message line (letters, digits, periods,
up to 11 characters, the selected entry's name as the default; left
arrow deletes, Return saves as `NAME.PCS`, Esc cancels), creating the
file or truncating an existing one; QUIT needs a second QUIT (click or
key) and calls `exit_to_prodos`. A LOAD checks the header, the count,
the sizes and the file's length (GET_EOF) before writing to the
database, so a file that is not a table leaves the current table alone
("NOT A TABLE"); a ProDOS error shows as "DISK ERROR nn" (hex). All the
menu's state lives in the player state pages (`P1STATE`, 2 KB), which
only the game shell uses; the MLI file buffer is `IOBUF` (`$BB00`, the
render arena), so nothing is drawn while a file is open. Without ProDOS
(no `JMP` at `$BF00`) the menu reports "NO PRODOS" and still offers
EDIT, PLAY GAME and QUIT.

PLAY GAME runs RUN2's shell (`RUN2_DISKPLAY`) between `play_begin`
(`$80`: sleepers on) and `play_end`, like the editor's Play tool. The
shell's player prompt `GETPLAYERCNT` (upstream: XOR text, Space cycles,
button confirms) is the port's (`src/files.s`): "HOW MANY PLAYERS" and
four digit boxes under the logo, a digit key or a click sets `PLAYERCNT`;
the click-release wait is capped at 12 frames so a stale mouse-button state
cannot prevent the first ball from starting;
Esc there leaves the shell the way the upstream's QUIT did (its callers'
returns dropped, `CLOSE2` restores the objects' rest state). During a
ball, Esc ends the game (RUN2's DOBALL); the menu is redrawn afterwards.
RUN2 builds its collision row pointers across the editor's split span
buffer: rows with index greater than `MIDY` start at `MIDTOP`, not at the
end of the lower rows. Treating the gap as collision data can turn its
bytes into an invalid object ID and jump through an invalid hit vector as
soon as a ball moves.

The editor's ADDOBJ capacity check reserves the new record, its size byte,
and 32 bytes of free span space. The polygon scanner checks both that a
row fits in the remaining gap and that its byte count does not overflow
before it updates PBDX or writes the row. These guards keep a rejected row
from overwriting the upper span data.

`tools/a2sim.py`'s `FakeProDOS` services the MLI in the test machine
(OPEN, READ, WRITE, CLOSE, CREATE, DESTROY, GET/SET_FILE_INFO,
GET/SET_PREFIX, ON_LINE, SET/GET_MARK, SET/GET_EOF, QUIT) over a dict of
files; the volume directory reads as the blocks `build_disk.py` writes.
`tools/run_editor.py --prodos DIR` mounts a directory's files (saved
tables land there). `tools/pb2pcs.py` converts original DOS 3.3 `.PB`
files into this format. It maps each saved bitmap pointer to its original
part and frame, translates polygon colours, and decompresses the saved
Hi-Res page into the playfield overlay. `tools/pb_art.py` accepts the
earlier BudgeCo zero-run stream and the later `DISK.S` stream; only the
left 154 pixels become overlay pixels, matching the port's playfield.

## 12. Fidelity policy

Kept as the original: the CATCH1 capture semantics, score x10 and bonus
x1000 display, the slope code 16 truncation, ball-ball pass-through, the
XOR cursor parity rules (as hide/show pairs). Fixed: `PUTSP`'s unmasked
noise nibble, the sleeper pitch (23), `PBTBL[0]` initialised, `MOVEDOWN`
exact.

## 13. Build and test

`make` converts the upstream sources (a local clone of the MIT-licensed
repository, or `upstream/` in the tree), generates the assets and tables,
assembles with ca65 and links with ld65; `make disk` writes
`dist/Appletini-PCS.hdv` (`appletini-pcs.gs2` is a GSSquared
configuration for it: enhanced //e, Appletini card in slot 7, mouse in
slot 2, Mockingboard/Phasor in slot 4). `make test` runs the py65 unit
tests (`tests/test_files.py` drives the disk menu with the fake ProDOS:
catalog, load, save, a corrupt file, the game shell, QUIT). `tools/run_editor.py` renders screenshots of the editor and of a play
session in the test machine and prints per-frame cycle and bus-byte
statistics.

## 14. The magnifier

The original's magnifier edited HGR bits of the table picture. The port's
(`src/magnify.s`, entered from EDIT's `MAGPAINT` through `MAGSTART`, which
returns on Esc or QUIT) edits the overlay layer of section 4 in sixteen
colours. `MB_STATE` is `MB_ST_MAG` while it runs.

Screen: the logo band stays; below it, x 154..319, y 64..191:

| Element | Where | What |
|---|---|---|
| window | x 174..301, y 66..161, 2-pixel grey frame around it | 32x24 table pixels at 4x; each pixel a 4x4 box, with the box's last column and row in the panel colour when the grid is on |
| palette | 16 boxes of 8x8 at y 168, x 158 + 10*i, each in a 1-pixel ring | the colours 0..15; colour 0 (the eraser) is a black/panel checker; the current colour's ring is `COL_HILITE`, the others' black |
| QUIT | x 172..199, y 180..191 | leaves |
| GRID | x 276..303, y 180..191, `SPR_MAG_GRID` | toggles the grid; framed while it is on |

The cursor is the brush. What the held button does is decided when it
is pressed: on the table (x < 154) the window follows the cursor (centred
on it, clamped to the table, x even) until the release, so a drag pans;
inside the window the table pixel under the cursor takes the current
colour every frame (colour 0 erases: nibble 0, the table shows through);
on the palette the colour is picked; QUIT and GRID are `DOMENU` items
(highlighted while pressed, acted on at the release). Keys: `0`-`9` and
`A`-`F` pick a colour, `G` toggles the grid, Esc leaves.

A painted pixel: its byte of the bank-1 row is fetched, the nibble
replaced and stored (`aux_fetch_rows`/`aux_store_rows`, one byte), the
tile's bit set in `ov_tiles` (byte `(y/8)*3 + x/64`, bit `(x/8) & 7`, as
`overlay_row` reads it), `ov_enabled` set, the pixel marked dirty: the
table shows it in the same frame. The window's box is redrawn after that
frame from the SHR screen (bank 0), so an erased pixel's box shows what
was beneath. The whole window is redrawn from the screen on every move
(the screen already holds polygons, parts and edits merged): three table
rows per arena pass, 6 KB of posted bytes and about 255K cycles, once per
recentre, pan frame or grid toggle. Parts are drawn over the edits (the
overlay is layer 2), so a part dragged over painted pixels hides them
while it sits there.

`overlay_clear` (exported) zeroes the tile map, `ov_enabled` and the 192
rows of the layer (from a zeroed row buffer, source pitch 0) and marks
the table: `main` calls it at start-up, since RamWorks memory is
undefined at power-on, and the file code calls it for a fresh table.
Buffers live in `P1STATE`; the window origin starts at the table's centre
(DATA); `BASE1`/`BASE2`, CDRAW's HGR pointers, serve as the arena
pointers while a window routine runs. `PRCHAR`'s column arithmetic is
8-bit (columns above 31 print nothing), which is why QUIT is the left box.
