#include "internal.h"
#include "libtini/graphics.h"
#include "graphics_internal.h"

ti_error ti_gfx_line(ti_surface *s, int16_t x0, int16_t y0, int16_t x1, int16_t y1, uint8_t color)
{
    int16_t dx, dy, sx, sy, err, twice;
    ti_error e = ti_gfx_surface_valid(s);
    if (e) return e;
    if (color > 15) return TI_E_ARGUMENT;
    /* Bound execution and signed Bresenham arithmetic, even for bad assets. */
    if (x0 < -1024 || x0 > 1024 || y0 < -1024 || y0 > 1024 ||
        x1 < -1024 || x1 > 1024 || y1 < -1024 || y1 > 1024) return TI_E_RANGE;
    dx = x1 > x0 ? x1 - x0 : x0 - x1;
    dy = y1 > y0 ? y1 - y0 : y0 - y1;
    sx = x0 < x1 ? 1 : -1; sy = y0 < y1 ? 1 : -1; err = dx - dy;
    while (1) {
        e = ti_gfx_dot(s, x0, y0, color); if (e) break;
        if (x0 == x1 && y0 == y1) break;
        twice = err * 2;
        if (twice > -dy) { err -= dy; x0 += sx; }
        if (twice < dx) { err += dx; y0 += sy; }
    }
    if (e) { ti_gfx_cache_flush(); return e; }
    return ti_gfx_cache_flush();
}
