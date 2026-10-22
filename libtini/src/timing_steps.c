#include "internal.h"
/* Fixed-rate updates from a device clock. The accumulator counts ticks times
 * steps per second; one step costs ticks_per_second. Only the clock's low 16
 * bits are kept, so calls must come less than 65536 ticks apart. State is
 * static: these foreground calls are not reentrant. */
static ti_tick_source source;
static uint16_t last, elapsed, per_second, accumulator;
static uint8_t rate, most, n;
ti_error ti_steps_begin(ti_tick_source clock, uint16_t ticks_per_second,
                        uint8_t steps_per_second, uint8_t max_steps)
{
    if (!clock || !ticks_per_second || !steps_per_second || !max_steps ||
        max_steps == TI_STEPS_GAP) return TI_E_ARGUMENT;
    if (ticks_per_second > 65535U / (steps_per_second + 1U)) return TI_E_RANGE;
    source = clock; per_second = ticks_per_second; rate = steps_per_second; most = max_steps;
    ti_steps_reset();
    return TI_OK;
}
void ti_steps_reset(void)
{
    if (source) last = (uint16_t)source();
    accumulator = 0;
}
uint8_t ti_steps_due(void)
{
    if (!source) return 0;
    elapsed = (uint16_t)source() - last;
    last += elapsed;
    if (elapsed > per_second) { ti_steps_reset(); return TI_STEPS_GAP; }
    accumulator += elapsed * rate;
    for (n = 0; accumulator >= per_second; ++n) {
        /* Time beyond max_steps is dropped: a slow frame slows play rather
         * than piling up updates. */
        if (n == most) { accumulator = per_second - 1; break; }
        accumulator -= per_second;
    }
    return n;
}
