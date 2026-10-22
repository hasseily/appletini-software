# Graphics and resource assets

The graphics backend draws packed 4-bit pixels into banked software surfaces.
It publishes them with ordinary CPU writes to the existing Appletini SHR
interface. It uses no firmware drawing commands, no private video transfers,
no SuperSprite and no slot changes. Include `libtini/graphics.h`.

## Surface ownership and layout

`ti_gfx_surface_create` allocates one resource for a surface of up to 320x200
pixels. The pixels are not initialized. Zero-initialize the structure before
the call. The stride is `(width+1)/2`, and the left pixel is the high nibble.
An odd-width row has one unused low nibble.

Clear the surface before you publish it. `ti_gfx_surface_free` frees the
resource and clears the structure. A second free returns `TI_E_HANDLE`.

A surface holds a resource handle and an explicit byte offset, never a mapped
C pointer. A copied structure, a tile image, a sprite image or an asset view
borrows its resource. Free the owning surface once, after all views are finished. Do
not free borrowed views.

Free and shutdown make all views invalid. Each call checks dimensions and
offsets against the real extent of the resource, bank boundaries included.
Ordinary near pointers are separate.

There are eight resource slots. One full backbuffer needs 32000 bytes and one
slot. A video session needs one more slot and 32768 bytes to keep the
complete original AUX0 screen, control bytes, palettes and padding.

Sprites and font or tile views can share one asset resource through explicit
offsets. Auxiliary RAM is not a flat C heap.

## Drawing

All drawing is synchronous, foreground-only and not reentrant. Near strings,
descriptors and output structures must stay valid only until the call
returns. Calls use bounded 128-byte bank transfers and restore the canonical
mapping after each burst.

No interrupt handler can call the renderer or change its mappings. The audio
interrupt driver can run between CPU bursts, under its own ownership rules.

- `ti_gfx_clear` fills a complete surface, unused padding nibbles included.
- `ti_gfx_rect` clips signed positions and unsigned extents to the surface. A
  packed byte that the rectangle covers in part keeps its other pixel. The
  call makes one row and writes it to each line. When an edge splits a byte,
  it reads each line first.
- `ti_gfx_line` plots clipped Bresenham pixels. Endpoints must be in
  `[-1024,1024]`, which limits the work and the signed arithmetic. Endpoints
  outside this range return `TI_E_RANGE`.
- `ti_gfx_text` draws the 5x7 built-in font in 6x8 cells. It draws lowercase
  letters as capitals and supports the newline. Text positions have the same
  `[-1024,1024]` limit. A call reads at most 1024 characters, newlines
  included.
- For each pixel row of a line of text, `ti_gfx_text` does one read and one
  write of the bytes that the line covers. Pixels that are not lit keep their
  colors.
- `ti_gfx_text_opaque` draws the same text. It fills the rest of each 6x8
  cell with `background`, the gap column and the eighth row included. A new
  value then replaces an old value of the same length without a rectangle.
  It writes rows without a read, unless an edge of the line splits a byte.
- `ti_digits(text, value, count)` writes `count` decimal digits of a 32-bit
  value, with leading zeros, and a NUL. A value with more digits keeps its
  last `count` digits. `count` is 1..10, and `text` needs `count+1` writable
  near bytes.
- `ti_digits` returns `text`, or NULL for a bad argument. The two text
  functions reject NULL with `TI_E_ARGUMENT`.
- `ti_gfx_text_font` reads a bitmap font from a resource: one byte per glyph
  row, with the high bit at the left. Glyphs are at most 8x16. A character
  code outside the font gives a blank advance.
- `ti_gfx_blit` clips at the destination edges and supports odd source and
  destination pixel positions. A source rectangle must be fully inside its
  source. Color keys 0..15 are transparent. `TI_GFX_OPAQUE` copies all pixels.
- `ti_gfx_sprite` accepts a separate one-bit opacity mask, high bit first,
  with a row stride of `(width+7)/8`. A mask bit of 1 copies the pixel, color
  zero included. Without a mask, color zero is transparent. Mask and image
  can share an asset resource at different offsets.

Rectangles, text and publication check the surface once, in 16-bit
arithmetic, because a surface holds at most 32000 bytes. Then one assembly
routine moves whole rows between the bank of the surface and a near row
buffer, without a resource call for each row.

The routine uses bursts of at most 128 bytes and splits a burst where the
surface crosses into the next bank. Lines and bitmap fonts plot single pixels
through a separate cache. Blits, sprites and maps use the resource calls. A
program that draws only rectangles and the built-in font does not link the
pixel cache.

In a STARFALL profile on the native emulator, a HUD value of two to eight
characters takes 1.9 ms at the `vtw33` model and 1.5 ms at the `turbo-f122`
model. This is opaque text and the publication of its cells: 1.0 and 0.6 ms
of text, 0.8 and 0.9 ms of publication. See [BENCHMARKS.md](BENCHMARKS.md).

Blits use 240-pixel pieces with near source and destination row buffers.
Source and destination must have different handles. A mask must not use the
destination handle either. The call rejects a copy inside one resource before
it changes pixels. Use separate background and sprite resources.

A backend or resource error can leave a software draw partly done. Drawing is
not transactional, so stop or recover after an error.

`ti_gfx_map` draws a row-major byte tile map into a clipped viewport, with a
pixel camera offset for scrolls. Each tile ID is checked against the atlas.
The atlas gives the tile dimensions, the columns and the count.

Maps have up to 256x256 cells and at most 256 tile IDs. Pixels beyond the map
are color zero. Camera arithmetic that wraps 16 bits returns `TI_E_RANGE`.
The source atlas and the map stay borrowed resources.

`ti_gfx_animation_frame` calculates `first+(elapsed_ticks/ticks_per_frame)%count`.
Give it elapsed device ticks, not a count of display frames. Invalid
descriptors return frame zero.

## Display lifecycle and budgets

`ti_gfx_begin(palette)` checks sixteen 0RGB words and reserves the AUX
backup. It saves all original AUX0 bytes at `$2000-$9FFF`, selects standard
320-pixel SHR and installs one shared palette. It does not change other slot
or speed settings.

`ti_gfx_palette` replaces the sixteen shared colors during an active session,
with normal CPU writes. `ti_gfx_end` restores every saved byte and disables
SHR. Shutdown also does this cleanup, and repeated `ti_gfx_end` calls
succeed. An allocation failure returns an explicit error before the call
takes the display.

`ti_gfx_present` needs a 320x200 surface. A NULL rectangle publishes the
whole screen. Otherwise the call copies only the clipped rows of the
rectangle. After the checks, one assembly routine copies every row.

The routine reads each row into a near buffer in bursts of at most 128 bytes,
split at the bank boundary. Then it writes the row to SHR in the same way.
The changed x edges expand to whole packed bytes, so the neighbor pixel of a
boundary byte comes from the same software surface. Keep the software surface
authoritative. The result gives the published bytes and, optionally, the
elapsed ticks.

`ti_gfx_present_rows(x, y, width, height, pixels, stride, stats)` publishes a
borrowed near buffer during the same active video session. Use it for small
row-composed scenes that need no banked canvas. The first source byte gives
the two leftmost destination pixels, high nibble first.

`stride` is the byte distance between source rows, and it can include
padding. The call writes only `width/2` bytes of each row. A padded or odd
byte stride is valid. The call does ordinary CPU video writes in pieces of
at most 128 bytes and needs no other resource handle.

The C code checks the complete rectangle once. Then one assembly routine
writes every row. Each row is one IRQ-masked burst, or two bursts when the
row is longer than 128 bytes.

The rectangle must not be empty, must fit fully in 320x200 and must have an
even `x` and `width`. This API does not clip or expand packed edges. A zero
area or a NULL source returns `TI_E_ARGUMENT`. Odd pixel edges, rectangles
off the screen, a stride that is too small, or an invalid or overflowing near
span return `TI_E_RANGE`. An invalid writable stats pointer returns
`TI_E_ARGUMENT`.

The complete source span is `(height-1)*stride+width/2`. It includes the gaps
between rows, but not the padding after the last row. It must fit in one
readable near region without 16-bit wrap.

All checks, the byte-budget check included, finish before any screen write.
A rejected call does not change the statistics. The source bytes must stay
valid only until the call returns. The caller owns the composition and any
authoritative image for later redraws. This call changes no banked surface.

Use `ti_gfx_budget(bytes, clock, ticks)` to limit a publication. A zero byte
budget selects 32000. A publication over the byte budget returns
`TI_E_TIMING` before any screen write.

An optional monotonic clock that the caller owns, independent of the CPU,
measures the synchronous operation. When the time is more than a nonzero tick
budget, the call sets `TI_GFX_OVERRUN` and returns `TI_E_TIMING` after the
writes. Without that clock, elapsed time is explicitly unavailable. Tick
differences are modulo 2^32, and the operation must fit in one wrap interval.

The two publication APIs use the same budget and statistics rules. A call
without an active video session returns `TI_E_STATE`.

The return of a publication means that its CPU writes are complete. It does
not mean an atomic page swap, a new HDMI frame or a display deadline.
Appletini samples its captured SHR shadow at the frame boundary.

`TI_GFX_EDGE_GAP` shows that foreground work can hide display edges. The
library does not invent a count of missed frames. Draw the static room once.
Then restore and draw again only the changed actor, machine and UI
rectangles. Measure the costs at 33 MHz and in TURBO to select the
publication budgets of a game.

## Sprite scenes

`libtini/scene.h` is a band renderer for games that move many small sprites
over a plain background. It needs an active `ti_gfx_begin` session and no
banked surface. Each frame, the game lists its sprites. `ti_scene_draw` then
builds again only the parts of one screen rectangle that changed since the
last draw, and publishes them with ordinary CPU writes.

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
  eight-line composition strip in near memory, for example BSS or
  `NEARBSS`. It costs 8 bytes for each sprite plus `8*row_bytes`. Use it
  once in a program. A list holds 1..255 sprites.
- The `x` and `width` of the area are even. Its height is a nonzero multiple
  of 8, and the area is inside 320x200. Its width is at most `2*row_bytes`.
- `ti_scene_begin` checks the area and every image once. An image needs a
  nonzero `row_bytes` and `rows`, a `stride` of at least `row_bytes`, and
  `(rows-1)*stride+row_bytes` readable near bytes.
- A missing or unreadable configuration or image table returns
  `TI_E_ARGUMENT`. Any other value outside its range returns `TI_E_RANGE`.
  After an error, no scene is active.
- Images are packed pixels, high nibble first, and color 0 is transparent. A
  NULL `pixels` pointer makes a solid rectangle of `2*row_bytes` by `rows`
  in the color of the sprite. Other images ignore the color.
- Positions are signed, and the scene clips sprites to the area. An odd `x`
  is rounded down. Later sprites cover earlier sprites, and the `background`
  color is under all of them.
- `ti_scene_add` compares each sprite with the sprite at the same list index
  in the last list. An equal position, image and color costs nothing. A
  change marks the old and the new place. The next draw erases sprites past
  the new count.
- The scene tracks changes in blocks of 16 pixels by 8 lines, so an unchanged
  list publishes nothing. The scene does not see pixels that change inside an
  image. Use another image index, or call `ti_scene_invalidate`.
- `ti_scene_add` returns `TI_E_FULL` when the list is full and `TI_E_RANGE`
  for an unknown image.
- For each 8-line band with changed blocks, `ti_scene_draw` fills those
  blocks of the strip with the background. It draws every listed sprite that
  reaches the band. It publishes each run of adjacent changed blocks with one
  call of the row writer.
- The draw calls the optional `service` function after every fourth band, so
  audio continues during long draws. That function must not call scene
  functions or draw in the area.
- Draws do not use `ti_gfx_budget` or statistics. The list capacity and the
  area limit the work. Without an active scene or video session, the draw
  returns `TI_E_STATE` before any write.
- When other code draws over the area, tell the scene. If the area shows only
  the background, for example after the publication of a cleared canvas, call
  `ti_scene_forget`. The next draw draws every listed sprite and erases
  nothing.
- If the area shows something else, call `ti_scene_invalidate`. The next draw
  draws the whole area again.

All scene calls are foreground-only. The scene keeps no banked resource. It
borrows the image table and the pixels until the next `ti_scene_begin`. It
adds 2,042 bytes of code and constants and 197 bytes of state to a program,
plus the storage of the game.

STARFALL draws its 240x184 playfield with this renderer. In a frame profile
on the native emulator, about 40 seconds into play with the parallax backdrop
on, the scene draw takes 15.3 ms a frame at `vtw33` and 17.0 ms at
`turbo-f122`. The sprite list takes 4.7 and 2.5 ms. See
[BENCHMARKS.md](BENCHMARKS.md).

## Offline assets and packs

`tools/assets.py` uses the Python standard library. It accepts P3 or P6 PPM
files with 8-bit channels, or indexed JSON. It quantizes against a shared
palette and writes native packed pixels, palettes and optional masks. It
checks JSON font and tile-map inputs before output. The outputs contain no
timestamp.

```powershell
python tools/assets.py image art.ppm art.ti4 --palette palette.json --palette-output palette.bin --masked --report art-layout.json
python tools/assets.py indexed art.json art.ti4
python tools/assets.py font font.json font.tif
python tools/assets.py map map.json map.tim
python tools/assets.py pack pack.json RESOURCES.TPK --report resources-layout.json
```

Palette JSON is a list of up to sixteen `0RGB` integers or `#RRGGBB` strings.
Unused colors are zero. Quantization uses the nibble-times-16 component scale
of the firmware.

Indexed JSON has `width`, `height`, row-major `pixels` and an optional
`masked:true`. The appended mask makes index zero transparent. Font JSON has
`width`, `height`, `first` and `glyphs`. Each glyph is an array of `height`
strings with exactly `width` pixels of `.` or `#`. Map JSON has rectangular
`rows` and an optional `tile_count`.

| Format | Header | Payload and view |
| --- | --- | --- |
| TI4 | `TI4\0`, LE16 width, LE16 height | Packed rows at offset 8; an optional opacity mask follows the pixel bytes |
| TIF | `TIF1`, first, count, width, height | Glyph bytes at offset 8, one MSB-first byte per row |
| TIM | `TIM1`, LE16 columns, LE16 rows | Row-major byte tile IDs at offset 8 |
| TPK | `TPK1`, LE16 count, LE16 zero | Sorted 24-byte entries, then the exact resource bytes |

A pack manifest is `{"entries":[{"name":"SCENE","path":"art.ti4"}]}`. It
permits 1..16 unique uppercase names of 1..15 bytes, and resources of 1 byte
to 4 MiB. Paths must be ordinary files under the manifest folder. The tool
rejects linked files, linked directories and paths outside the folder.

A TPK entry is a 16-byte NUL-padded name, an LE32 absolute offset and an LE32
size. Entries and data are sorted, contiguous and do not overlap. The
complete file must fit the 24-bit ProDOS EOF limit.

`ti_pack_load` loads one entry through standard ProDOS into one banked
resource. Check the TI4, TIF or TIM header, then set the offset of the view
to 8. Keep the pack handle until every view is finished.

The report gives the 48640-byte bank-window size, the output bytes and the
minimum bank count. It does not count the AUX0 video backup, and it does not
promise that all configured RAM is free. All inputs are ordinary project
files. The tool reads no sibling checkout and fetches no network input.

## Focused evidence

```powershell
python -m unittest discover -s tests -p test_graphics_tools.py -v
python tests/graphics_validate.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe
python tests/scene_validate.py --cc65-home D:/Repos/cc65
```

Nine host asset tests pass. The compiled C/65C02 graphics suite passes 4047
checks on each of the native `vtw33` and `turbo-f122` profiles. These include
all 1792 combinations of character byte and glyph row against a reference
font renderer, with lowercase, punctuation and the fallback for unknown
characters.

The suite compares real banked pixels with independent near-buffer results
for clipping, odd nibbles, bank crossings, lines, text, masks, keyed and
opaque blits, wide 240-pixel pieces, scrolled tiles and banked font glyphs.
It also checks a 32000-byte full publication, the dirty-byte and elapsed
budgets, complete AUX0 restoration, handle lifetime and the cleanup at
shutdown and init.

The near-row checks compare real AUX bytes for full-width rows in pieces,
129-byte rows split into a full burst and one byte, neighbor bytes that must
not change, and padded odd strides. They also cover the exact screen and
near-region endpoints, the rejection of bad values and byte budgets before
publication, elapsed overruns and clock wrap.

A second program, `tests/text_target.c`, passes 1367 checks on each profile.
It draws the two text functions at 64 random positions, 32 random
rectangles, the 1024-character limit in the two modes and full 160-byte rows
on a 320-pixel surface. After each call, it compares the whole surface,
padding included, with a pixel-by-pixel rendering from the reference font.

Its 61x24 surface has an odd width and crosses a bank in row 9. It publishes
eight rectangles of two 320x200 surfaces, whose second banks start inside
row 98 and inside row 0. The rectangles are the whole screen, odd edges, the
two corners, rows of 128 and 159 bytes, rows across the bank, rows far into
the second bank and a clipped rectangle.

After each publication, the whole screen must hold the surface bytes inside
the packed bytes of the rectangle and a marker everywhere else. The program
also checks 120 `ti_digits` results against repeated division, the argument
and near-buffer limits of `ti_digits`, and `ti_error_keep`. The results are
in `build/graphics/validation.json`.

The scene check runs the renderer on the 65C02 instruction model. It passes
653 target checks over 59 draws on three areas, with random sprites from 48
pixels before each edge to 48 pixels past it. After every draw, the area must
equal an independent rendering of the sprite list in memory. Every SHR byte
outside the areas must keep its previous value.

An unchanged list must publish nothing. The check also covers rejected
configurations, a full list, the service calls and the redraw after another
drawer. The ROM-boot check of STARFALL compares its own playfield with the
same reference at sampled frames.
