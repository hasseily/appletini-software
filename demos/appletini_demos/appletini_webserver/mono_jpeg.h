/* SPDX-License-Identifier: MIT */
#ifndef MONO_JPEG_H
#define MONO_JPEG_H
#include <stdint.h>
/* Decode cached baseline JPEG bytes on the Apple CPU. The encoded source
 * is supplied by the resident mono_source_get(offset). Native Y samples
 * are scaled to fit the box and ordered-dithered into mono DHGRi. */
uint8_t mono_jpeg_decode(int16_t x, int16_t y, uint16_t max_width,
                        uint16_t max_height, uint16_t encoded_length);
const char *mono_jpeg_error(void);
#endif
