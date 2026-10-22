#ifndef LIBTINI_GRAPHICS_H
#define LIBTINI_GRAPHICS_H
#include "memory.h"
#include "timing.h"

#define TI_GFX_WIDTH 320
#define TI_GFX_HEIGHT 200
#define TI_GFX_OPAQUE 255
#define TI_GFX_CLOCK_VALID 1
#define TI_GFX_OVERRUN 2
#define TI_GFX_EDGE_GAP 4

/* Zero-initialize before create. A surface owns its resource; structure copies
 * borrow it and must not be freed independently. Pixels: high nibble first. */
typedef struct ti_surface {
    ti_handle pixels;
    uint32_t offset; /* permits a borrowed view into one resource pack */
    uint16_t width, height, stride;
} ti_surface;
typedef struct ti_rect {
    int16_t x, y;
    uint16_t width, height;
} ti_rect;
typedef struct ti_gfx_stats {
    uint32_t bytes, elapsed_ticks;
    uint8_t flags;
} ti_gfx_stats;
/* Optional mask: one bit/pixel, MSB first, 1=opaque, row stride ceil(w/8).
 * mask=0 uses transparent pixel color zero instead. Image/mask are borrowed. */
typedef struct ti_sprite { ti_surface image; ti_handle mask; uint32_t mask_offset; } ti_sprite;
typedef struct ti_tileset {
    ti_surface image;
    uint8_t tile_width, tile_height, columns;
    uint16_t count;
} ti_tileset;
typedef struct ti_tilemap {
    ti_handle cells; /* row-major uint8 tile IDs */
    uint32_t offset;
    uint16_t columns, rows;
} ti_tilemap;
typedef struct ti_animation {
    uint16_t first, count, ticks_per_frame;
} ti_animation;
typedef struct ti_bitmap_font {
    ti_handle glyphs;
    uint32_t offset;
    uint8_t width, height, first, count; /* one byte per glyph row, MSB first */
} ti_bitmap_font;

ti_error ti_gfx_surface_create(ti_surface *surface, uint16_t width, uint16_t height);
ti_error ti_gfx_surface_free(ti_surface *surface);
ti_error ti_gfx_clear(ti_surface *surface, uint8_t color);
ti_error ti_gfx_rect(ti_surface *surface, int16_t x, int16_t y,
                     uint16_t width, uint16_t height, uint8_t color);
ti_error ti_gfx_line(ti_surface *surface, int16_t x0, int16_t y0,
                     int16_t x1, int16_t y1, uint8_t color);
ti_error ti_gfx_text(ti_surface *surface, int16_t x, int16_t y,
                     const char *text, uint8_t color);
/* Fills each whole 6x8 character cell with background before drawing it, so
 * a value can replace an older one of the same length without a rectangle. */
ti_error ti_gfx_text_opaque(ti_surface *surface, int16_t x, int16_t y,
                            const char *text, uint8_t color, uint8_t background);
/* Writes count decimal digits of value, zero padded, and a NUL to text.
 * A value with more digits keeps its last count. count is 1..10; text needs
 * count+1 writable near bytes. Returns text, or NULL for a bad argument,
 * which the text functions reject. */
char *ti_digits(char *text, uint32_t value, uint8_t count);
ti_error ti_gfx_text_font(ti_surface *surface, int16_t x, int16_t y,
                          const char *text, uint8_t color, const ti_bitmap_font *font);
/* Source rectangle NULL selects the entire source. key=255 is opaque.
 * Source and destination must use distinct resource handles. */
ti_error ti_gfx_blit(ti_surface *destination, int16_t x, int16_t y,
                     const ti_surface *source, const ti_rect *source_rectangle,
                     uint8_t transparent_color);
ti_error ti_gfx_sprite(ti_surface *destination, int16_t x, int16_t y,
                       const ti_sprite *sprite);
ti_error ti_gfx_map(ti_surface *destination, const ti_rect *viewport,
                    const ti_tileset *tiles, const ti_tilemap *map,
                    uint16_t camera_x, uint16_t camera_y);
uint16_t ti_gfx_animation_frame(const ti_animation *animation, uint32_t elapsed_ticks);

/* Existing CPU SHR publication only. Palette entries are 0RGB, 0..0x0FFF.
 * Begin reserves/saves all AUX0 screen bytes; end restores them. */
ti_error ti_gfx_begin(const uint16_t *palette);
ti_error ti_gfx_palette(const uint16_t *palette);
ti_error ti_gfx_end(void);
/* byte_budget=0 means 32000. Optional monotonic clock is caller-owned;
 * tick_budget=0 disables elapsed deadline. A rejected byte budget writes none. */
void ti_gfx_budget(uint16_t byte_budget, ti_tick_source clock, uint32_t tick_budget);
/* Requires a 320x200 surface. NULL rectangle publishes all. Dirty x edges
 * expand to whole packed bytes. Return means CPU writes finished, never an
 * atomic display swap. A measured late publication returns TI_E_TIMING. */
ti_error ti_gfx_present(const ti_surface *surface, const ti_rect *rectangle,
                       ti_gfx_stats *stats);
/* Publish packed near rows during an active video session, without a surface.
 * x and width must be even; the nonempty rectangle must fit wholly onscreen.
 * stride is bytes between source rows, at least width/2; padding is not drawn.
 * The complete near span, stats and byte budget are checked before any write.
 * Source pixels are borrowed until return. Timing/statistics match present. */
ti_error ti_gfx_present_rows(uint16_t x, uint16_t y, uint16_t width,
                            uint16_t height, const uint8_t *pixels,
                            uint16_t stride, ti_gfx_stats *stats);
#endif
