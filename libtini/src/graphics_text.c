#include "internal.h"
#include "libtini/graphics.h"
#include "graphics_internal.h"

/* target/text.s draws each pixel row of a line with one read and one write
 * of the bytes the line covers, once these checks have passed. */
extern ti_surface *ti_text_surface;
extern int16_t ti_text_x, ti_text_y;
extern const char *ti_text_string;
extern uint8_t ti_text_ink, ti_text_paper, ti_text_opaque;
ti_error ti_text_draw(void);

static ti_error draw(ti_surface *s, int16_t x, int16_t y, const char *text, uint8_t color, uint8_t background)
{
    ti_error e = ti_gfx_surface_valid(s);
    if (e) return e;
    if (color > 15 || background > 15 || !text) return TI_E_ARGUMENT;
    if (x < -1024 || x > 1024 || y < -1024 || y > 1024) return TI_E_RANGE;
    ti_text_surface = s; ti_text_x = x; ti_text_y = y; ti_text_string = text;
    ti_text_ink = (uint8_t)(color | color << 4);
    ti_text_paper = (uint8_t)(background | background << 4);
    ti_gfx_rows_begin(s);
    e = ti_text_draw();
    ti_time_note_gap();
    return e;
}

ti_error ti_gfx_text(ti_surface *s, int16_t x, int16_t y, const char *text, uint8_t color)
{
    ti_text_opaque = 0;
    return draw(s, x, y, text, color, 0);
}

ti_error ti_gfx_text_opaque(ti_surface *s, int16_t x, int16_t y, const char *text,
                            uint8_t color, uint8_t background)
{
    ti_text_opaque = 0x40;
    return draw(s, x, y, text, color, background);
}
