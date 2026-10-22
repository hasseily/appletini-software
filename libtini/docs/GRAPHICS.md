# Graphics and resource assets

The graphics backend draws packed 4-bit pixels into banked software surfaces
and publishes them with ordinary CPU writes to the existing Appletini SHR
interface. It uses no firmware drawing commands, private video transfers,
SuperSprite or slot changes. Include `libtini/graphics.h`.

## Surface ownership and layout

`ti_gfx_surface_create` allocates one resource for an initially uninitialized
surface, up to 320x200. Zero-initialize the structure before creating it.
`stride=(width+1)/2`; the left pixel is the high nibble. An odd-width row has
one unused low nibble. Clear the surface before presenting uninitialized
pixels. `ti_gfx_surface_free` invalidates its resource and clears the owning
structure; freeing it twice returns `TI_E_HANDLE`.

The surface stores a resource handle and an explicit byte offset, never a
mapped C pointer. A copied structure, tile image, sprite image or asset view
borrows its resource. Free the owner once, after every view is finished.
Do not free borrowed views independently. Free/shutdown invalidates all of
them. Dimensions and offsets are checked against the resource's actual
extent, including bank boundaries. Ordinary near pointers remain separate.

There are eight resource slots. One full backbuffer needs 32000 bytes and one
slot. Beginning video needs another slot and 32768 bytes to preserve the
entire original AUX0 screen, control bytes, palettes and padding. Sprites and
font/tile views can share one asset resource through explicit offsets. This
does not make auxiliary RAM a flat C heap.

## Drawing

All drawing is synchronous, foreground-only and non-reentrant. Near strings,
descriptors and output structures need to remain valid only until a call
returns. Calls use bounded 128-byte bank transfers and restore canonical
mapping after every burst. No interrupt handler may call the renderer or
change its mappings. The common audio interrupt driver may run between CPU
bursts under its separate ownership contract.

- `ti_gfx_clear` fills a complete surface, including unused padding nibbles.
- `ti_gfx_rect` clips signed positions and unsigned extents to the surface;
  partially covered packed bytes retain their other visible pixel. It builds
  one row and writes it to every line; a rectangle with an odd edge reads
  each line first.
- `ti_gfx_line` uses clipped Bresenham pixels. Endpoints must be in
  `[-1024,1024]`, which bounds both work and signed arithmetic. More distant
  endpoints return `TI_E_RANGE`.
- `ti_gfx_text` draws the original 5x7 font in 6x8 cells, accepts lowercase
  through uppercase glyphs, and supports newline. Text positions have the
  same `[-1024,1024]` bound. It processes at most 1024 source characters per
  call, newlines included. Each pixel row of a line is one read and one
  write of the bytes the line covers; unlit pixels keep their colours.
- `ti_gfx_text_opaque` draws the same text and fills the rest of each 6x8
  cell, its gap column and eighth row included, with `background`. A value
  then replaces an older one of the same length without a rectangle. It
  writes rows without reading them unless an edge of the line splits a
  packed byte.
- `ti_digits(text, value, count)` writes `count` decimal digits of a 32-bit
  value, zero padded, and a NUL; a value with more digits keeps its last
  `count`. `count` is 1..10, and `text` needs `count+1` writable near bytes.
  It returns `text`, or NULL for a bad argument, which both text functions
  reject with `TI_E_ARGUMENT`.
- `ti_gfx_text_font` reads a caller-supplied bitmap font from a resource,
  one byte per glyph row, high bit at the left. Glyphs are at most 8x16;
  unsupported character codes leave a blank advance.
- `ti_gfx_blit` clips destination edges and supports odd source/destination
  pixel positions. A source rectangle must lie wholly inside its source.
  Color keys 0..15 are transparent; `TI_GFX_OPAQUE` copies every pixel.
- `ti_gfx_sprite` accepts a separate one-bit opacity mask, high bit first,
  with row stride `(width+7)/8`. A mask bit of one copies the pixel, including
  color zero. Without a mask, color zero is transparent. Mask and image may
  share an asset resource with distinct offsets.

Rectangles, text and publication check the surface once, in 16-bit
arithmetic since a surface holds at most 32000 bytes. Then one assembly
routine moves whole rows between the surface's bank and a near row buffer,
in bursts of at most 128 bytes split where the surface crosses into the next
bank, without a resource call per row. Lines and bitmap fonts plot single
pixels through a separate cache; blits, sprites and maps use the resource
calls. A program that draws only rectangles and the built-in font does not
link the pixel cache.

In a STARFALL profile on the native emulator, replacing a HUD value of two
to eight characters, opaque text and then publishing its cells, took 1.9 ms
on average at the 33 MHz `vtw33` model and 1.5 ms at historical TURBO costs:
1.0 and 0.6 ms of text, 0.8 and 0.9 ms of publication. A rectangle,
pixel-by-pixel text and a publication that read and wrote each row through
the resource calls took 30.7 and 17.8 ms. These are model figures, not board
timing; see [benchmarks](BENCHMARKS.md).

Blits use 240-pixel pieces with near source/destination row buffers. Source
and destination must have distinct handles; a mask also must not share the
destination handle. In-place drawing copies are rejected before changing
pixels. Use separate background and sprite resources. A backend/resource
error can leave an already started software draw partially changed; callers
must stop/recover instead of assuming transactional drawing.

`ti_gfx_map` draws a row-major byte tile map into a clipped viewport, with a
pixel camera offset for scrolling. Tile IDs are checked against the atlas;
the atlas describes tile dimensions, columns and count. Maps have up to
256x256 cells and at most 256 tile IDs. Pixels beyond the map are color zero;
camera arithmetic that would wrap 16 bits returns `TI_E_RANGE`. The source
atlas and map remain borrowed resources. `ti_gfx_animation_frame` computes
`first+(elapsed_ticks/ticks_per_frame)%count`; supply elapsed device ticks,
not an observed display-frame count. Invalid descriptors return frame zero.

## Display lifecycle and budgets

`ti_gfx_begin(palette)` validates sixteen 0RGB words, reserves the AUX backup,
saves all original AUX0 bytes at `$2000-$9FFF`, selects standard 320-pixel SHR,
and installs one shared palette. It leaves other slot and speed selections
alone. `ti_gfx_palette` replaces those sixteen shared colors during an active
session through normal CPU writes. `ti_gfx_end` restores every saved byte and disables SHR. Shutdown also
invokes this cleanup, and repeated end calls succeed. Allocation failure
returns an explicit error before taking display ownership.

`ti_gfx_present` requires a 320x200 surface. A null rectangle publishes the
whole screen; otherwise only its clipped rows are copied. After the checks,
one assembly routine copies every row: it reads the row into a near buffer
in bursts of at most 128 bytes, split where the surface crosses into the next
bank, then writes it to SHR the same way. Dirty x edges
expand to whole packed bytes, so the neighboring pixel in a boundary byte
comes from the same software surface. Keep the software surface authoritative.
The result reports bytes actually published and optional elapsed ticks.

`ti_gfx_present_rows(x, y, width, height, pixels, stride, stats)` publishes a
borrowed near buffer directly during the same active video session. Use this
for small row-composed scenes when a banked software canvas is unnecessary.
The first source byte supplies the two leftmost destination pixels, high nibble
first. `stride` is the byte distance between source rows and may include padding;
only `width/2` bytes per row are written. Even a padded or odd byte stride is
valid. The call performs ordinary CPU video writes in pieces of at most 128
bytes and requires no additional resource handle. After checking the whole
rectangle once in C, a single assembly routine writes every row: each row is
one IRQ-masked burst, or two when it exceeds 128 bytes. Earlier versions made
a C call per row; in a STARFALL profile at 33 MHz that per-row overhead was
about 12 of the 17 ms per frame spent publishing, and the call now takes
about 8 ms, of which 5.4 ms is the byte copy.

The rectangle must be nonempty, fit wholly within 320x200, and have even `x`
and `width`. This API does not clip or expand packed edges. Zero area or a null
source returns `TI_E_ARGUMENT`; odd pixel edges, offscreen rectangles, too-small
stride, or an invalid/overflowing near span return `TI_E_RANGE`. An invalid
writable stats pointer returns `TI_E_ARGUMENT`. The complete source span is
`(height-1)*stride+width/2`, including gaps between rows but excluding padding
after the last row. It must fit one readable near region without 16-bit wrap.
All validation and the byte-budget check finish before any screen write;
rejected calls leave stats unchanged. Source bytes need remain valid only until
return. The caller owns composition and any authoritative image for later
redraws; this call does not update a banked surface.

Use `ti_gfx_budget(bytes, clock, ticks)` to limit a publication. A zero byte
budget selects 32000. Exceeding the byte budget returns `TI_E_TIMING` before
any screen writes. An optional caller-owned, monotonic, CPU-independent clock
measures the synchronous operation; an exceeded nonzero tick budget sets
`TI_GFX_OVERRUN` and returns `TI_E_TIMING` after the writes have finished.
Without that clock, elapsed time is explicitly unavailable. Tick differences
are modulo 2^32 and the operation must fit within one wrap interval.

Both publication APIs use these budget and statistics rules. Calling either
without an active video session returns `TI_E_STATE`.

Returning from present means its CPU writes finished. It does not mean an
atomic page swap, a newly composed HDMI frame, or a guaranteed display
deadline. Appletini samples its captured SHR shadow at the existing frame
boundary. `TI_GFX_EDGE_GAP` marks that foreground work can hide display edges;
there is no invented count of missed frames. Draw the static room once, then
restore/redraw dirty actor, machine and UI rectangles. Measure real costs at
33 MHz and TURBO before selecting gameplay publication budgets.

## Sprite scenes

`libtini/scene.h` is a band renderer for games that move many small sprites
over a plain background. It needs an active `ti_gfx_begin` session and no
banked surface. Each frame the game lists its sprites, and `ti_scene_draw`
rebuilds only the parts of one screen rectangle that changed since the last
draw, publishing them with ordinary CPU writes.

```c
TI_SCENE_STORAGE(64, 120);          /* 64 sprites a frame, an area up to 240 pixels wide */
static const ti_image images[] = {
    {ship, 8, 16, 8},               /* 16x16 */
    {sheet + 4, 2, 4, 16},          /* 4x4 inside a 32-pixel-wide sheet */
    {0, 1, 2, 0},                   /* a 2x2 rectangle in the sprite's colour */
};
static const ti_scene_config scene = {0, 16, 240, 184, images, 3, 0, audio_service};

ti_scene_begin(&scene);
for (;;) {
    ti_scene_frame();
    ti_scene_add(ship_x, ship_y, 0, 0);
    for (i = 0; i < shots; ++i) ti_scene_add(shot_x[i], shot_y[i], 2, 15);
    ti_scene_draw();
}
```

- `TI_SCENE_STORAGE(sprites, row_bytes)` defines the sprite list and an
  eight-line composition strip in the game's near memory, such as BSS or
  `NEARBSS`: 8 bytes a sprite plus `8*row_bytes`. Use it once per program.
  A list holds 1..255 sprites.
- The area's `x` and `width` are even, its height a nonzero multiple of 8,
  and it lies within 320x200. Its width is at most `2*row_bytes`.
  `ti_scene_begin` checks the area and every image once. An image needs
  nonzero `row_bytes` and `rows`, `stride` at least `row_bytes`, and
  `(rows-1)*stride+row_bytes` readable near bytes. A missing or unreadable
  configuration or image table returns `TI_E_ARGUMENT`; anything else out of
  range returns `TI_E_RANGE`. After either error no scene is active.
- Images are packed pixels, high nibble first, with colour 0 transparent.
  NULL `pixels` makes a solid rectangle, `2*row_bytes` by `rows`, in the
  sprite's colour; the colour is ignored for other images. Positions are
  signed and sprites are clipped to the area. An odd `x` is rounded down.
  Later sprites cover earlier ones, and the `background` colour lies under
  them all.
- `ti_scene_add` compares each sprite with the one at the same list index in
  the last list. An equal position, image and colour costs nothing. A
  change marks the old and new places, and sprites beyond the new count are
  erased. Changes are tracked in blocks of 16 pixels by 8 lines, so an
  unchanged list publishes nothing. Pixels changed in place inside an image
  are not noticed; use another image index, or `ti_scene_invalidate`.
  `ti_scene_add` returns `TI_E_FULL` when the list is full and `TI_E_RANGE`
  for an unknown image.
- For each 8-line band holding changed blocks, `ti_scene_draw` fills those
  blocks in the strip with the background, draws every listed sprite that
  reaches the band, and publishes each run of adjacent changed blocks with one
  call of the row writer. It calls the optional `service` function after
  every fourth band, which lets audio keep up during long draws. That
  function must not call scene functions or draw in the area. Draws do not
  use `ti_gfx_budget` or statistics; the list capacity and area bound the
  work. Without an active scene or video session, draw returns `TI_E_STATE`
  before writing.
- When something else draws over the area, tell the scene. If the area now
  shows only the background, such as after publishing a cleared canvas, call
  `ti_scene_forget`: the next draw draws every listed sprite and erases
  nothing. If it shows anything else, call `ti_scene_invalidate`: the next
  draw redraws the whole area.

All scene calls are foreground-only. The scene keeps no banked resource and
borrows the image table and pixels until the next `ti_scene_begin`. It adds
2,042 bytes of code and constants and 197 bytes of state to a program,
besides the game's storage.

STARFALL's 240x184 playfield moved to this renderer from its own. In a
frame profile on the native emulator, listing and drawing the playfield took
14.4-15.8 ms a frame at the 33 MHz `vtw33` model and 13.6-15.2 ms at
historical TURBO costs, against 22.5-23.6 and 20.7-21.7 ms before. These are
model figures, not board timing; see [validation](VALIDATION.md).

## Offline assets and packs

`tools/assets.py` uses Python's standard library. It accepts P3/P6 PPM with
8-bit channels or indexed JSON, quantizes against a supplied shared palette,
and emits native packed pixels, palettes and optional masks. JSON font and
tile-map inputs are validated before output. Outputs contain no timestamp.

```powershell
python tools/assets.py image art.ppm art.ti4 --palette palette.json --palette-output palette.bin --masked --report art-layout.json
python tools/assets.py indexed art.json art.ti4
python tools/assets.py font font.json font.tif
python tools/assets.py map map.json map.tim
python tools/assets.py pack pack.json RESOURCES.TPK --report resources-layout.json
```

Palette JSON is a list of up to sixteen `0RGB` integers or `#RRGGBB` strings.
Unused colors are zero. Quantization uses the firmware's nibble-times-16
component scale. Indexed JSON has `width`, `height`, row-major `pixels` and
optional `masked:true`. The appended mask treats index zero as transparent.
Font JSON has `width`, `height`, `first` and `glyphs`; each glyph is an array
of `height` strings containing exactly `width` `.`/`#` pixels. Map JSON has
rectangular `rows` and optional `tile_count`.

| Format | Header | Payload/view |
| --- | --- | --- |
| TI4 | `TI4\0`, LE16 width, LE16 height | Packed rows at offset 8; optional opacity mask follows pixel bytes |
| TIF | `TIF1`, first, count, width, height | Glyph bytes at offset 8, one MSB-first byte per row |
| TIM | `TIM1`, LE16 columns, LE16 rows | Row-major byte tile IDs at offset 8 |
| TPK | `TPK1`, LE16 count, LE16 zero | Sorted 24-byte entries, then exact resource bytes |

A pack manifest is `{"entries":[{"name":"SCENE","path":"art.ti4"}]}`.
It permits 1..16 unique uppercase names of 1..15 bytes and nonempty resources
up to 4 MiB each. Paths must remain ordinary files under the manifest folder;
linked files/directories and paths outside it are rejected. A TPK entry is a
16-byte NUL-padded name, LE32 absolute offset and LE32 size. Entries and data
are sorted, contiguous and non-overlapping; the complete file must fit the
24-bit ProDOS EOF limit. `ti_pack_load` loads an entry through standard ProDOS
into one banked resource. Set the relevant view offset to 8 after validating
the TI4/TIF/TIM header. Keep the pack handle alive until every view is done.

The report names the 48640-byte allocatable bank-window size, output bytes
and minimum bank count. It does not count AUX0/video backup or promise all
configured RAM is free. Required inputs are ordinary project files; the tool
does not read sibling checkouts or fetch network inputs.

## Focused evidence

```powershell
python -m unittest discover -s tests -p test_graphics_tools.py -v
python tests/graphics_validate.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe
python tests/scene_validate.py --cc65-home D:/Repos/cc65
```

Nine host asset tests pass. The compiled C/65C02 graphics suite passes 4047
checks on both native `vtw33` and historical `turbo-f122` profiles. These include
all 1792 combinations of character byte and glyph row against the frozen original
font renderer, including lowercase, punctuation and unknown-character fallback. It compares
actual banked pixels with independent near-buffer expectations for clipping,
odd nibble preservation, bank crossings, lines, text, masks, keyed/opaque
blits, wide 240-pixel chunks, scrolling tiles and banked font glyphs. It also
checks a 32000-byte full publication, dirty-byte and elapsed budgets, complete
AUX0 restoration, handle lifecycle and shutdown/re-init cleanup. Near-row
checks compare actual AUX bytes for full-width chunked rows, 129-byte rows
split into a full burst and one byte, untouched neighbours, padded odd
strides, exact screen/near-region endpoints, validation and byte-budget rejection
before publication, elapsed overruns and clock wrap.

A second program, `tests/text_target.c`, passes 1137 checks on both
profiles. It draws both text functions at 64 random positions, 32 random
rectangles, the 1024-character limit both ways and full 160-byte rows on a
320-pixel surface. After each call it compares the whole surface, padding
included, with a pixel-by-pixel rendering from the frozen original font.
Its 61x24 surface has an odd width and crosses a bank in row 9. It publishes
eight rectangles of two 320x200 surfaces, whose second banks start inside
row 98 and inside row 0: the whole screen, odd edges, both corners, rows of
128 and 159 bytes, rows across the bank, rows far into the second bank and
a clipped one. After each, the whole screen must hold the surface's bytes
inside the rectangle's packed bytes and a marker everywhere else. It also
checks 120 `ti_digits` results against repeated division, its argument and
near-buffer limits, and `ti_error_keep`. Evidence is in
`build/graphics/validation.json`; this is emulator evidence. Physical
publication, performance and timing at 33 MHz and TURBO remain board gates.

The scene check runs the renderer on the 65C02 instruction model through 59
draws on three areas, with random sprites placed from 48 pixels before each
edge to 48 past it. After every draw the area must equal an independent
rendering of the sprite list in memory, and every SHR byte outside the areas
must keep its earlier value. An unchanged list must publish nothing. It also
checks rejected configurations, a full list, the service calls and redraws
after another drawer. STARFALL's ROM-boot validation compares its own
playfield with the same reference at sampled frames.
