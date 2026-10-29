/* SPDX-License-Identifier: MIT */
#ifndef MONO_MOUSE_H
#define MONO_MOUSE_H
#include <stdint.h>
#define MONO_MOUSE_MOVED 1U
#define MONO_MOUSE_PRESSED 2U
#define MONO_MOUSE_RELEASED 4U
/* Optional standard AppleMouse card, found in slots 1..7. All routines run
 * from MONO.WEB. Poll only from the browser foreground, with MAIN reads and
 * writes, bank-0 AUX, and MAIN LC bank 2 readable. No IRQ handler is used.
 * Init returns 0 when absent; a keyboard-only browser can continue. */
uint8_t mono_mouse_init(void);
uint8_t mono_mouse_poll(void);
void mono_mouse_disable(void);
/* Coordinates are 7x8 character cells, x=0..79, y=0..47. Hardware tracks
 * individual 560x384 pixels. pressed is a one-poll left-button down edge;
 * down is the current held state, both 0 or 1. Poll also returns event bits. */
extern uint8_t mono_mouse_available, mono_mouse_x, mono_mouse_y;
extern uint8_t mono_mouse_down, mono_mouse_pressed;
#endif
