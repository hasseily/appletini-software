#include "internal.h"
#include "libtini/audio.h"
#include "libtini/input.h"
#define IO(a) (*(volatile uint8_t *)(a))
/* Counted by the audio clock IRQ; its low byte changes once per interrupt. */
extern volatile uint8_t ti_clock_counter[4];
static volatile uint8_t io_sink;
static uint8_t t2_mode; /* 0 untested, 1 T2 counts, 2 T2 absent: use T1C-H */
/* Measurement state is static: this foreground routine is not reentrant, and
 * absolute operands keep each poll short on an unaccelerated CPU. Paddle
 * times are device clocks; 0xFFFF marks a paddle still running at the limit. */
static uint8_t high, low, last, first, steps, pending, x_low, y_low, tries, stamp;
static uint16_t polls, x_poll, y_poll, x, y, elapsed, limit, scale;
static uint32_t rate;
static ti_error result;
static uint16_t timer(void)
{
    tries = 8;
    do { high = IO(0xC489); low = IO(0xC488); } while (--tries && high != IO(0xC489));
    return ((uint16_t)high << 8) | low;
}
/* Any //e access to $C070-$C07F strobes the paddle timers, including the
 * RamWorks selector writes at $C073 that banked CPU transfers make, and a 558
 * timer still running ignores a new strobe. Such a paddle would read short,
 * so wait up to the limit for both to finish. T1C-H changes every 256 clocks. */
static void settle(void)
{
    steps = (uint8_t)(limit >> 8) + 1; polls = 0;
    last = IO(0xC485);
    while ((IO(0xC064) | IO(0xC065)) & 128) {
        if (IO(0xC485) != last) { last = IO(0xC485); if (!--steps) return; }
        if (!++polls) return;
    }
}
/* T2 counts down from $FFFF from the paddle trigger. A clock interrupt
 * during the polls delays detection, so a finished measurement that saw one
 * is taken again, up to three times. A measurement that reached the limit is
 * not repeated: that axis is absent or beyond the range. */
static ti_error t2_paddles(void)
{
    static uint8_t attempts;
    attempts = 3;
    do {
        settle();
        x = y = 0xFFFF; polls = 0; stamp = ti_clock_counter[0];
        IO(0xC488) = 255; IO(0xC489) = 255;
        io_sink = IO(0xC070);
        do {
            elapsed = ~timer();
            if (x == 0xFFFF && !(IO(0xC064) & 128)) x = elapsed;
            if (y == 0xFFFF && !(IO(0xC065) & 128)) y = elapsed;
            if (x != 0xFFFF && y != 0xFFFF) break;
        } while (elapsed < limit && ++polls != 8192);
        if (x == 0xFFFF || y == 0xFFFF || stamp == ti_clock_counter[0]) return TI_OK;
    } while (--attempts);
    return TI_E_BUSY;
}
/* Interpolate a paddle at the middle of the poll that saw it finish. */
static uint16_t t1_time(uint8_t bit, uint16_t poll)
{
    if (pending & bit) return 0xFFFF;
    return poll ? (uint16_t)(((uint32_t)poll * 2 - 1) * elapsed / ((uint32_t)polls * 2)) : 0;
}
/* Fallback for a VIA without a counting T2. T1 is the running free-run clock;
 * only T1C-H is read because reading T1C-L would clear the clock IRQ flag.
 * A window starts and ends where T1C-H steps down by one, so its length is a
 * whole number of 256-clock steps, exact to one poll. Every poll reads both
 * paddles so poll durations stay uniform. Any other change of T1C-H means a
 * stall of at least one step, such as an interrupt, or the T1 reload and its
 * clock IRQ. That would inflate the time per poll, so the window is measured
 * again, up to three times. */
static ti_error t1_paddles(void)
{
    static uint8_t most;
    most = (uint8_t)(limit >> 8) + 1; tries = 3;
    for (;;) {
        settle();
        polls = 0; steps = 0; pending = 3;
        last = IO(0xC485);
        for (;;) {
            high = IO(0xC485);
            if (!++polls) return TI_E_BUSY;
            if (high == last) continue;
            if (high == (uint8_t)(last - 1)) break;
            last = high;
        }
        io_sink = IO(0xC070);
        first = last = high; polls = 0;
        do {
            x_low = IO(0xC064); y_low = IO(0xC065);
            if (!(x_low & 128) && (pending & 1)) { x_poll = polls; pending &= 2; }
            if (!(y_low & 128) && (pending & 2)) { y_poll = polls; pending &= 1; }
            if (!++polls) return TI_E_BUSY;
            high = IO(0xC485);
            if (high == last) continue;
            if (high != (uint8_t)(last - 1)) break;
            last = high;
            if (!pending || ++steps >= most) break;
        } while (1);
        if (high == last) break;
        if (!--tries) return TI_E_BUSY;
    }
    elapsed = (uint16_t)(first - high) << 8;
    x = t1_time(1, x_poll); y = t1_time(2, y_poll);
    return TI_OK;
}
/* T2 is probed once: a counting VIA moves it within 256 bounded reads. */
static uint8_t t2_counts(void)
{
    uint8_t i = 0;
    IO(0xC488) = 255; IO(0xC489) = 255;
    do if (timer() != 0xFFFF) return 1; while (++i);
    return 0;
}
static uint8_t units(uint16_t time)
{
    time /= scale;
    return time > 255 ? 255 : (uint8_t)time;
}
ti_error ti_joystick_read(ti_joystick *out)
{
    if (!out || !ti_near_valid(out, sizeof(*out), 1)) return TI_E_ARGUMENT;
    if (!ti_audio_voices()) return TI_E_UNAVAILABLE;
    if (rate != ti_audio_source_hz()) {
        rate = ti_audio_source_hz();
        limit = (uint16_t)(rate / 250);
        scale = (uint16_t)(rate * 11UL / 1000000UL);
        if (!scale) scale = 1;
    }
    if (!t2_mode) t2_mode = t2_counts() ? 1 : 2;
    result = t2_mode == 2 ? t1_paddles() : t2_paddles();
    if (result) return result;
    out->x = units(x); out->y = units(y);
    out->buttons = ti_input_buttons();
    return x == 0xFFFF || y == 0xFFFF ? TI_E_TIMING : TI_OK;
}
