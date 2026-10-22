#ifndef LIBTINI_INPUT_H
#define LIBTINI_INPUT_H
#include "types.h"
typedef struct ti_joystick { uint8_t x, y, buttons; } ti_joystick;
ti_error ti_input_poll(void);
ti_error ti_input_key(uint8_t *character);
uint8_t ti_input_buttons(void);
/* The most recent key while any key is still down, or 0. The //e reports
 * only that one key: hold A, tap Space and A held reads Space until every
 * key is up. A pending key event counts as held and stays queued. */
uint8_t ti_input_held(void);
/* Paddle timing uses the owned 1 MHz VIA-B T2, never CPU delay loops. Where
 * T2 does not count, it interpolates inside exact windows of the running T1
 * clock, reading only T1C-H. Requires initialized audio. Any access to
 * $C070-$C07F, including RamWorks selector writes by banked CPU transfers,
 * starts the paddle timers, and a timer still running ignores the next
 * trigger. The read therefore first waits up to 4 ms for both timers to
 * finish. A paddle still running after 4 ms reads 255 and the call returns
 * TI_E_TIMING; the other axis remains a valid reading. TI_E_BUSY means
 * interrupts disturbed every attempt; *state is unchanged and a later read
 * can succeed. */
ti_error ti_joystick_read(ti_joystick *state);
/* Digital directions from the same stick, as TI_STICK bits. Each axis is
 * measured against the stick's own rest position. A direction engages
 * beyond a third of the furthest travel seen on that side, at least 16
 * units, and releases at three quarters of that, so a stick near the
 * threshold does not flicker. The rest is the first reading within 48..207
 * on both axes after startup or ti_stick_recalibrate; call that while the
 * stick should be untouched. A disturbed read keeps the last directions.
 * TI_STICK_ABSENT means no stick answered; after four such reads the next
 * three seconds return it at once without measuring. *state, if not NULL,
 * gets the raw reading; an invalid state pointer also returns ABSENT. */
#define TI_STICK_UP     1
#define TI_STICK_DOWN   2
#define TI_STICK_LEFT   4
#define TI_STICK_RIGHT  8
#define TI_STICK_ABSENT 128
uint8_t ti_stick_read(ti_joystick *state);
void ti_stick_recalibrate(void);
ti_error ti_mouse_read(void *state); /* optional hardware unavailable */
void ti_input_reset(void);
#endif
