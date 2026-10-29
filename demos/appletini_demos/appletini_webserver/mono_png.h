#ifndef MONO_PNG_H
#define MONO_PNG_H
#include <stdint.h>
/* Native PNG decoder. Reads completed input through mono_source_get(offset).
 * Uses expansion AUX bank 1 $2000-$9FFF for DEFLATE history and $A000-$BFFF
 * for a previous scanline. The renderer and input cache use other banks.
 * Supports noninterlaced 1/2/4/8-bit grayscale/indexed, 8-bit RGB/GA/RGBA.
 * Images shrink to fit the box; they never grow. Transparent pixels keep the
 * page background. Partial alpha composites against white. Returns 1 on
 * success and 0 on a format, bounds, checksum or truncation error. */
uint8_t mono_png_decode(int16_t x, int16_t y, uint16_t width,
                        uint16_t height, uint16_t encoded_length);
const char *mono_png_error(void);
uint16_t mono_png_width(void);
uint16_t mono_png_height(void);
#endif
