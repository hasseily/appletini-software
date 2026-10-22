#include "internal.h"
#include "libtini/audio.h"
#include "libtini/input.h"
/* Separate archive member for digital stick use. The rest position per axis
 * and the furthest reading seen on each side of it: left, right, up, down.
 * Real Apple joysticks rarely rest at 128 or travel equally both ways.
 * State is static: this foreground call is not reentrant. */
static uint8_t rest[2] = {128, 128}, reach[4], held, seen, pending = 1, misses, waiting;
static uint8_t a, v, c, d, t, s, bits;
static uint16_t retry_at;
static ti_joystick raw;
static const uint8_t side[4] = {TI_STICK_LEFT, TI_STICK_RIGHT, TI_STICK_UP, TI_STICK_DOWN};
void ti_stick_recalibrate(void) { pending = 1; waiting = misses = 0; }
uint8_t ti_stick_read(ti_joystick *state)
{
    if (state && !ti_near_valid(state, sizeof(*state), 1)) return TI_STICK_ABSENT;
    if (waiting) {
        if ((int16_t)((uint16_t)ti_audio_ticks() - retry_at) < 0) return TI_STICK_ABSENT;
        waiting = 0;
    }
    a = ti_joystick_read(&raw);
    if (state) *state = raw;
    /* An interrupted measurement keeps the last directions. */
    if (a == TI_E_BUSY) return seen ? held : TI_STICK_ABSENT;
    /* A paddle still running at the limit reads 255, full deflection, once a
     * stick has answered. Both unfinished before that means no stick. After
     * four misses in a row, wait three seconds before measuring again. */
    if (a && (a != TI_E_TIMING || (!seen && (raw.x & raw.y) == 255))) {
        if (++misses == 4) {
            misses = 0; waiting = 1;
            retry_at = (uint16_t)ti_audio_ticks() + 3 * TI_AUDIO_TICKS_PER_SECOND;
        }
        return TI_STICK_ABSENT;
    }
    seen = 1; misses = 0;
    /* Calibrate from the first reading that looks like a resting stick. */
    if (pending && (uint8_t)(raw.x - 48) < 160 && (uint8_t)(raw.y - 48) < 160) {
        pending = 0; rest[0] = raw.x; rest[1] = raw.y;
        reach[0] = reach[1] = reach[2] = reach[3] = 60;
    }
    for (a = bits = 0; a < 2; ++a) {
        v = a ? raw.y : raw.x; c = rest[a]; s = a * 2;
        if (v > c) { ++s; d = v - c; } else d = c - v;
        if (d > reach[s]) reach[s] = d;
        /* Engage beyond a third of the furthest travel seen that way, at
         * least 16 units; a held direction lets go at three quarters of it. */
        t = reach[s] / 3; if (t < 16) t = 16;
        if (held & side[s]) t -= t >> 2;
        if (d > t) bits |= side[s];
    }
    return held = bits;
}
