#include "internal.h"
#include "libtini/graphics.h"
#include "graphics_internal.h"

/* Single pixels for lines and bitmap fonts. A separate archive member, so
 * programs that only fill rectangles and draw the built-in font skip it. */
static uint8_t pixels[128];
static ti_handle cached;
static uint32_t cache_offset;
static uint8_t cache_length, cache_dirty;

ti_error ti_gfx_cache_flush(void)
{
    ti_error e = TI_OK;
    if (cache_dirty) e = ti_res_write(cached, cache_offset, pixels, cache_length);
    cache_dirty = 0;
    cached = 0;
    return e;
}

ti_error ti_gfx_dot(ti_surface *s, int16_t x, int16_t y, uint8_t color)
{
    uint32_t offset, block, remain;
    uint8_t index;
    ti_error e;
    if (x < 0 || y < 0 || x >= (int16_t)s->width || y >= (int16_t)s->height) return TI_OK;
    offset = s->offset + (uint32_t)(uint16_t)y * s->stride + ((uint16_t)x >> 1);
    block = offset & 0xFFFFFF80UL;
    if (cached != s->pixels || cache_offset != block) {
        e = ti_gfx_cache_flush(); if (e) return e;
        remain = s->offset + (uint32_t)s->stride * s->height - block;
        cache_length = remain > 128 ? 128 : (uint8_t)remain;
        e = ti_res_read(s->pixels, block, pixels, cache_length); if (e) return e;
        cached = s->pixels;
        cache_offset = block;
    }
    index = (uint8_t)(offset - block);
    if (x & 1) pixels[index] = (uint8_t)((pixels[index] & 0xF0) | color);
    else pixels[index] = (uint8_t)((pixels[index] & 15) | (color << 4));
    cache_dirty = 1;
    return TI_OK;
}
