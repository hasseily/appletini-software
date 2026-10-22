#ifndef LIBTINI_SCENE_H
#define LIBTINI_SCENE_H
#include "types.h"

/* A band renderer for sprite games. Each frame the game lists its sprites;
 * ti_scene_draw then rebuilds only the parts of a screen rectangle that
 * changed since the last draw. Changes are tracked in blocks of 16 pixels by
 * 8 lines. Each changed band is composed in a near strip and published with
 * ordinary CPU video writes, during an active ti_gfx_begin session.
 *
 * Images are packed 4-bit pixels, two per byte, high nibble first; colour 0
 * is transparent. row_bytes is the width in bytes, rows the height, and
 * stride the byte distance between rows, so an image can sit inside a
 * larger sheet. pixels NULL makes a solid rectangle in the sprite's colour.
 * Sprites sit on even x; an odd x is rounded down. */
typedef struct ti_image { const uint8_t *pixels; uint8_t row_bytes, rows, stride; } ti_image;
typedef struct ti_scene_config {
    uint16_t x, y, width, height;  /* screen pixels: x and width even, height a multiple of 8 */
    const ti_image *images;        /* near, borrowed until the next begin */
    uint8_t image_count;
    uint8_t background;            /* colour 0..15 under every sprite */
    void (*service)(void);         /* called after every fourth band while drawing, or NULL;
                                    * it must not call scene functions */
} ti_scene_config;

/* The sprite list and strip, defined once by the game in near memory, such
 * as BSS or NEARBSS: at most `sprites` (1..255) per frame and an area up to
 * `row_bytes` bytes (two pixels each) wide. It costs 8 bytes a sprite plus
 * 8 * row_bytes. */
#define TI_SCENE_STORAGE(sprites, row_bytes) \
    uint8_t ti_scene_x_lo[sprites], ti_scene_x_hi[sprites], ti_scene_y_lo[sprites], \
        ti_scene_y_hi[sprites], ti_scene_image[sprites], ti_scene_color[sprites], \
        ti_scene_top[sprites], ti_scene_bottom[sprites], ti_scene_strip[(row_bytes) * 8]; \
    const uint8_t ti_scene_capacity = (sprites), ti_scene_strip_width = (row_bytes)

/* Start a scene on a screen rectangle, which is taken to show only the
 * background; call ti_scene_invalidate when it does not. Images are checked
 * once here. TI_E_ARGUMENT for a missing or unreadable configuration or
 * image table, TI_E_RANGE for a bad area, colour or image. */
ti_error ti_scene_begin(const ti_scene_config *config);
/* Start the next frame's list. The last drawn list is kept, so sprites that
 * moved, changed or went away are erased, and unchanged ones cost nothing. */
void ti_scene_frame(void);
/* Append a sprite in draw order: later sprites cover earlier ones. Returns
 * TI_E_FULL when the list is full, TI_E_RANGE for an unknown image and
 * TI_E_STATE before ti_scene_begin. */
ti_error ti_scene_add(int16_t x, int16_t y, uint8_t image, uint8_t color);
/* Something else drew over the area, such as a full canvas publication:
 * nothing of the last list is on screen any more. */
void ti_scene_forget(void);
/* Redraw the whole area, background included, at the next draw. */
void ti_scene_invalidate(void);
/* Compose and publish every changed block. TI_E_STATE without an active
 * scene and video session. */
ti_error ti_scene_draw(void);
#endif
