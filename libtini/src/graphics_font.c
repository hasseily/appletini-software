#include "internal.h"
#include "libtini/graphics.h"
#include "graphics_internal.h"

ti_error ti_gfx_text_font(ti_surface *s, int16_t x, int16_t y, const char *text,
                          uint8_t color, const ti_bitmap_font *font)
{
    uint8_t glyph[16], row, col, ch;
    uint16_t remaining = 1024;
    int16_t left = x;
    uint32_t size;
    ti_error e = ti_gfx_surface_valid(s);
    if (e) return e;
    if (!font || !text || !ti_near_valid(font, sizeof(*font), 0) || color > 15 ||
        !font->width || font->width > 8 || !font->height || font->height > 16 ||
        !font->count || (uint16_t)font->first + font->count > 256) return TI_E_ARGUMENT;
    size = (uint32_t)font->count * font->height;
    if (font->offset > 0xFFFFFFFFUL - size) return TI_E_RANGE;
    e = ti_res_read(font->glyphs, font->offset + size, 0, 0); if (e) return e;
    while (remaining--) {
        if (!ti_near_valid(text, 1, 0)) { e = TI_E_RANGE; break; }
        ch = (uint8_t)*text++;
        if (!ch) break;
        if (ch == '\n') { x = left; if (y > 1008) break; y += font->height + 1; continue; }
        if (ch >= font->first && (uint16_t)ch < (uint16_t)font->first + font->count &&
            x >= -7 && x < 320 && y >= -15 && y < 200) {
            e = ti_res_read(font->glyphs, font->offset + (uint32_t)(ch - font->first) * font->height,
                            glyph, font->height);
            if (e) break;
            for (row = 0; row < font->height; ++row)
                for (col = 0; col < font->width; ++col) if (glyph[row] & (128 >> col)) {
                    e = ti_gfx_dot(s, x + col, y + row, color);
                    if (e) { ti_gfx_cache_flush(); return e; }
                }
        }
        if (x > 1015) break;
        x += font->width + 1;
    }
    if (e) { ti_gfx_cache_flush(); return e; }
    return ti_gfx_cache_flush();
}
