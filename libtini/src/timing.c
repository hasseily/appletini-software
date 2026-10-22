#include "internal.h"
static ti_tick_source clock_source;
static uint32_t origin, edges;
static uint8_t previous;

ti_error ti_time_begin(ti_tick_source source, uint16_t ticks_per_second)
{
    if ((!source && ticks_per_second) || (source && !ticks_per_second)) return TI_E_ARGUMENT;
    clock_source = source;
    origin = source ? source() : 0;
    edges = 0;
    ti_time_flags = source ? TI_TIME_ELAPSED_VALID : 0;
    previous = ti_display_level();
    return TI_OK;
}

ti_error ti_time_poll(ti_time_sample *sample)
{
    uint8_t current;
    if (!sample || !ti_near_valid(sample, sizeof(*sample), 1)) return TI_E_ARGUMENT;
    current = ti_display_level();
    if (current && !previous) ++edges;
    previous = current;
    sample->display_edges = edges;
    sample->elapsed_ticks = clock_source ? clock_source() - origin : 0;
    sample->flags = ti_time_flags;
    return clock_source ? TI_OK : TI_E_UNAVAILABLE;
}
