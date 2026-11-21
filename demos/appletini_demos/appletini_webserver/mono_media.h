/* SPDX-License-Identifier: MIT */
#ifndef MONO_MEDIA_H
#define MONO_MEDIA_H
#include <stdint.h>
uint8_t mono_overlay(const char *name);
void mono_media_init(void);
extern char mono_media_message[80];
extern uint8_t mono_memory_ready;
/* Pictures that the card converted stay in banked RAM until the next page
 * load, so a scroll draws them again without the network. */
#define MONO_PICTURE_MAX 12U
void mono_picture_reset(void);
/* Text rows that image `index` takes in the layout. */
uint8_t mono_picture_rows(uint8_t index, uint8_t enabled);
/* Text columns that image `index` takes in the layout. */
uint8_t mono_picture_cols(uint8_t index, uint8_t enabled);
/* 0: not loaded yet. 1: drawn at text column `column` and pixel row y,
 * clipped to the content area. 2: load failed. */
uint8_t mono_picture_show(uint8_t index, uint8_t column, int16_t y);
/* Fetch through the card. A zero URL marks the picture as failed. width
 * and height are the display size from the page, 0 when not given; the
 * picture is never larger than 546 x 240. */
uint8_t mono_picture_load(uint8_t index, char *url, uint16_t width, uint16_t height);
#endif
