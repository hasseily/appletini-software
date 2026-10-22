#ifndef LIBTINI_TIMING_H
#define LIBTINI_TIMING_H
#include "types.h"

/* A source must be a real monotonic device clock, independent of CPU speed,
 * modulo 2^32. NULL explicitly means there is no elapsed-time source.
 * This module claims no device; the shared audio driver can supply its clock. */
typedef uint32_t (*ti_tick_source)(void);
#define TI_TIME_ELAPSED_VALID 1
#define TI_TIME_GAP           2
typedef struct ti_time_sample {
    uint32_t display_edges; /* observed 0->1 $C019 edges, a lower bound */
    uint32_t elapsed_ticks; /* modulo difference since ti_time_begin */
    uint8_t flags;
} ti_time_sample;
ti_error ti_time_begin(ti_tick_source source, uint16_t ticks_per_second);
ti_error ti_time_poll(ti_time_sample *sample);
void ti_time_note_gap(void); /* sticky until next begin; long calls use this */

/* Fixed-rate game updates, for example ti_steps_begin(ti_audio_ticks,
 * TI_AUDIO_TICKS_PER_SECOND, 30, 30) for 30 updates a second. Needs
 * ticks_per_second * (steps_per_second + 1) <= 65535 and max_steps < 255. */
#define TI_STEPS_GAP 255
ti_error ti_steps_begin(ti_tick_source source, uint16_t ticks_per_second,
                        uint8_t steps_per_second, uint8_t max_steps);
/* Restart from now and drop any backlog, for example after a pause. */
void ti_steps_reset(void);
/* The updates due since the last call, at most max_steps; part of a step
 * carries over. TI_STEPS_GAP reports more than a second between calls;
 * timing then restarts from now. 0 before begin. A paused audio clock
 * stops advancing, so a storage pause is not a gap.
 * Only the clock's low 16 bits are kept: after a pause that may exceed
 * 65535 ticks, call ti_steps_reset first. */
uint8_t ti_steps_due(void);
#endif
