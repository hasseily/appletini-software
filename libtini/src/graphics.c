#include <string.h>
#include "memory_internal.h"
#include "libtini/graphics.h"
#include "graphics_internal.h"

/* The widest surface row, with guard bytes for text: see target/text.s. */
uint8_t ti_gfx_rows[3 + 160 + 2];

ti_error ti_gfx_surface_valid(const ti_surface *s)
{
    ti_memory_resource *r;
    uint16_t size;
    if (!s || !ti_near_valid(s, sizeof(*s), 0)) return TI_E_ARGUMENT;
    if (!s->width || s->width > 320 || !s->height || s->height > 200 ||
        s->stride != (s->width + 1) / 2) return TI_E_ARGUMENT;
    /* At most 160 bytes by 200 rows: the size fits 16 bits. */
    size = s->stride * s->height;
    if (s->offset > 0xFFFFFFFFUL - size) return TI_E_RANGE;
    if (!(r = ti_memory_lookup(s->pixels))) return TI_E_HANDLE;
    return ti_memory_in_range(r, s->offset, size) ? TI_OK : TI_E_RANGE;
}

void ti_gfx_rows_begin(const ti_surface *s)
{
    ti_row_base_addr = ti_memory_address(ti_memory_lookup(s->pixels), s->offset, &ti_row_base_bank);
    ti_row_stride = s->stride;
}

/* One axis in 16 bits: a start before 0 shortens the extent first. */
static uint8_t clip_axis(int16_t *at, uint16_t *extent, uint16_t limit)
{
    uint16_t before;
    if (*at < 0) {
        before = (uint16_t)0 - (uint16_t)*at;
        if (*extent <= before) return 0;
        *extent -= before; *at = 0;
    }
    if ((uint16_t)*at >= limit) return 0;
    if (*extent > limit - (uint16_t)*at) *extent = limit - (uint16_t)*at;
    return *extent != 0;
}

uint8_t ti_gfx_clip(const ti_surface *s, ti_rect *r)
{
    return clip_axis(&r->x, &r->width, s->width) && clip_axis(&r->y, &r->height, s->height);
}

#pragma code-name (push, "TISETUP")
ti_error ti_gfx_surface_create(ti_surface *s, uint16_t width, uint16_t height)
{
    ti_error e;
    if (!s || !ti_near_valid(s, sizeof(*s), 1)) return TI_E_ARGUMENT;
    if (s->pixels) return TI_E_STATE;
    if (!width || width > 320 || !height || height > 200) return TI_E_RANGE;
    s->offset = 0; s->width = width; s->height = height; s->stride = (width + 1) / 2;
    e = ti_res_alloc((uint32_t)s->stride * height, &s->pixels);
    if (e) s->width = s->height = s->stride = 0;
    return e;
}
#pragma code-name (pop)

ti_error ti_gfx_surface_free(ti_surface *s)
{
    ti_error e;
    if (!s || !ti_near_valid(s, sizeof(*s), 1)) return TI_E_ARGUMENT;
    e = ti_res_free(s->pixels);
    if (!e) { s->pixels = s->width = s->height = s->stride = 0; s->offset = 0; }
    return e;
}

ti_error ti_gfx_clear(ti_surface *s, uint8_t color)
{
    ti_error e = ti_gfx_surface_valid(s);
    if (e) return e;
    if (color > 15) return TI_E_ARGUMENT;
    return ti_res_fill(s->pixels, s->offset, (uint8_t)(color | (color << 4)), (uint32_t)s->stride * s->height);
}

/* The row of bytes is built once and written to every line. A rectangle
 * with an odd edge reads each line first to keep the outside nibble. */
ti_error ti_gfx_rect(ti_surface *s, int16_t x, int16_t y, uint16_t width, uint16_t height, uint8_t color)
{
    ti_rect r;
    uint8_t n, fill, first, last, edges;
    ti_error e = ti_gfx_surface_valid(s);
    if (e) return e;
    if (color > 15) return TI_E_ARGUMENT;
    r.x = x; r.y = y; r.width = width; r.height = height;
    if (!ti_gfx_clip(s, &r)) return TI_OK;
    n = (uint8_t)(((uint16_t)r.x % 2 + r.width + 1) / 2);
    fill = (uint8_t)(color | (color << 4));
    edges = (uint8_t)((r.x & 1) | ((r.x + r.width) & 1) << 1);
    ti_gfx_rows_begin(s);
    ti_row_bytes = n;
    /* At most 199 rows of 160 bytes: the offset fits 16 bits. */
    ti_row_seek((uint16_t)r.y * s->stride + (uint16_t)r.x / 2);
    memset(ti_gfx_row, fill, n);
    do {
        if (edges) {
            ti_row_read();
            first = ti_gfx_row[0]; last = ti_gfx_row[n - 1];
            memset(ti_gfx_row, fill, n);
            if (edges & 1) ti_gfx_row[0] = (uint8_t)((first & 0xF0) | color);
            if (edges & 2) ti_gfx_row[n - 1] = (uint8_t)((last & 15) | (fill & 0xF0));
        }
        ti_row_write();
        ti_row_next();
    } while (--r.height);
    ti_time_note_gap();
    return TI_OK;
}
