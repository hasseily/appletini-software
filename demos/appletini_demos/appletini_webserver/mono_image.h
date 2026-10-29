#ifndef MONO_IMAGE_H
#define MONO_IMAGE_H
#include <stdint.h>

#define MONO_IMAGE_MORE 0
#define MONO_IMAGE_DONE 1
#define MONO_IMAGE_ERROR 2

/* Streaming, first-frame GIF87a/GIF89a decoder. HTTP headers are excluded.
 * Destination coordinates may be negative; drawing clips to the display.
 * Logical GIF dimensions must fit 4096x4096 and four megapixels. It shrinks to
 * the supplied
 * max_width/max_height box while preserving proportions; it never grows.
 * Transparent pixels leave the destination unchanged. The caller clears the
 * image rectangle and holds/commits video around a complete page redraw.
 * Owns AUX $6000-$9FFF until completion; no pointers into it may be retained.
 * Input is borrowed only until feed returns. A decoder instance is global. */
void mono_image_begin(int16_t x, int16_t y,
                      uint16_t max_width, uint16_t max_height);
uint8_t mono_image_feed(const uint8_t *data, uint16_t length);
/* Mark the input complete. A partial first frame becomes an error. */
uint8_t mono_image_finish(void);
uint8_t mono_image_status(void);
const char *mono_image_error(void);
uint16_t mono_image_width(void);  /* scaled display dimensions */
uint16_t mono_image_height(void);
#endif
