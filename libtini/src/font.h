#ifndef TI_FONT_H
#define TI_FONT_H
#include <stdint.h>
/* The built-in 5x7 glyphs, defined in font.c; target/text.s reads them too.
 * Rows use bits 4..0 and must be 0..6. */
extern const uint8_t ti_font[56][7];
extern const uint8_t ti_font_index[64];
static uint8_t ti_font_row(uint8_t ch, uint8_t row)
{
    if (ch >= 'a' && ch <= 'z') ch -= 32;
    if (ch < ' ' || ch > '_') ch = '?';
    return ti_font[ti_font_index[(uint8_t)(ch - ' ')]][row];
}
#endif
