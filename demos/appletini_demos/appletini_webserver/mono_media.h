/* SPDX-License-Identifier: MIT */
#ifndef MONO_MEDIA_H
#define MONO_MEDIA_H
#include <stdint.h>
uint8_t mono_overlay(const char *name);
void mono_media_init(void);
uint8_t mono_media(char *url, int16_t x, int16_t y, uint16_t w, uint16_t h);
uint8_t mono_source_get(uint16_t offset);
extern char mono_media_message[80];
extern uint8_t mono_memory_ready;
#endif
