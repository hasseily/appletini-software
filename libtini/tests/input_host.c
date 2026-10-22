/* Host checks for the calibrated stick and the fixed-step clock. The same
 * library C runs here against a scripted joystick and clock. */
#include <stdio.h>
#include "internal.h"

static uint32_t ticks;
static ti_joystick scripted;
static ti_error scripted_error;
static unsigned reads, failures;
uint32_t ti_audio_ticks(void) { return ticks; }
ti_error ti_joystick_read(ti_joystick *out)
{
    ++reads;
    if (scripted_error != TI_E_BUSY) *out = scripted;
    return scripted_error;
}
uint8_t ti_near_valid(const void *pointer, uint16_t length, uint8_t write)
{
    (void)length; (void)write;
    return pointer != NULL;
}
static uint32_t clock_ticks(void) { return ticks; }

#define CHECK(condition) do { if (!(condition)) { \
    printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #condition); ++failures; } } while (0)

static uint8_t at(uint8_t x, uint8_t y)
{
    scripted.x = x; scripted.y = y; scripted_error = TI_OK;
    return ti_stick_read(NULL);
}

static void stick(void)
{
    unsigned before, i;
    ti_joystick raw;
    /* No stick: four misses, then three seconds without measuring. */
    scripted.x = scripted.y = 255; scripted_error = TI_E_TIMING; ticks = 0;
    for (i = 0; i < 4; ++i) CHECK(ti_stick_read(NULL) == TI_STICK_ABSENT);
    CHECK(reads == 4);
    ticks = 299;
    CHECK(ti_stick_read(NULL) == TI_STICK_ABSENT && reads == 4);
    ticks = 300;
    CHECK(ti_stick_read(NULL) == TI_STICK_ABSENT && reads == 5);
    /* A disturbed read before any answer is no stick either. */
    scripted_error = TI_E_BUSY;
    CHECK(ti_stick_read(NULL) == TI_STICK_ABSENT && reads == 6);
    /* Recalibration ends the wait. The rest is the first reading within
     * 48..207 on both axes. */
    ti_stick_recalibrate();
    CHECK(at(250, 100) != TI_STICK_ABSENT);
    CHECK(at(150, 100) == 0);
    /* Default reach 60: engage beyond 20, release at 15 once held. */
    CHECK(at(170, 100) == 0);
    CHECK(at(171, 100) == TI_STICK_RIGHT);
    CHECK(at(166, 100) == TI_STICK_RIGHT);
    CHECK(at(165, 100) == 0);
    /* Wider travel raises that side's threshold: reach 105 engages beyond
     * 35 and releases at 27. The other sides keep theirs. */
    CHECK(at(255, 100) == TI_STICK_RIGHT);
    CHECK(at(150, 100) == 0);
    CHECK(at(185, 100) == 0);
    CHECK(at(186, 100) == TI_STICK_RIGHT);
    CHECK(at(178, 100) == TI_STICK_RIGHT);
    CHECK(at(177, 100) == 0);
    CHECK(at(129, 100) == TI_STICK_LEFT);
    CHECK(at(150, 79) == TI_STICK_UP);
    CHECK(at(150, 121) == TI_STICK_DOWN);
    CHECK(at(255, 0) == (TI_STICK_RIGHT | TI_STICK_UP));
    /* A deflected stick does not become the rest. */
    ti_stick_recalibrate();
    CHECK(at(250, 100) == TI_STICK_RIGHT);
    CHECK(at(120, 110) == 0);
    CHECK(at(141, 110) == TI_STICK_RIGHT);
    /* Disturbed reads keep the last directions; an unfinished axis after an
     * answer is full deflection; other errors are misses. */
    scripted_error = TI_E_BUSY; before = reads;
    CHECK(ti_stick_read(&raw) == TI_STICK_RIGHT && reads == before + 1 && raw.x == 141);
    scripted.x = 255; scripted.y = 110; scripted_error = TI_E_TIMING;
    CHECK(ti_stick_read(&raw) == TI_STICK_RIGHT && raw.x == 255 && raw.y == 110);
    scripted_error = TI_E_UNAVAILABLE;
    CHECK(ti_stick_read(NULL) == TI_STICK_ABSENT);
    CHECK(at(120, 110) == 0);
}

/* Reference accounting for one call: ticks times rate, one step per
 * ticks_per_second, at most max_steps, excess kept below one step. */
static uint8_t expected_steps(uint32_t *accumulator, uint16_t elapsed, uint16_t per_second,
                              uint8_t rate, uint8_t most)
{
    uint8_t n = 0;
    *accumulator += (uint32_t)elapsed * rate;
    while (*accumulator >= per_second) {
        if (n == most) { *accumulator = per_second - 1; break; }
        *accumulator -= per_second; ++n;
    }
    return n;
}

static void steps(void)
{
    uint32_t accumulator = 0, seed = 12345;
    unsigned i;
    uint8_t most = 30, rate = 30;
    uint16_t elapsed;
    CHECK(ti_steps_due() == 0);
    CHECK(ti_steps_begin(NULL, 100, 30, 30) == TI_E_ARGUMENT);
    CHECK(ti_steps_begin(clock_ticks, 100, 30, TI_STEPS_GAP) == TI_E_ARGUMENT);
    CHECK(ti_steps_begin(clock_ticks, 649, 100, 30) == TI_E_RANGE);
    CHECK(ti_steps_begin(clock_ticks, 648, 100, 30) == TI_OK);
    /* Across the 16-bit wrap of the kept clock. */
    ticks = 65530;
    CHECK(ti_steps_begin(clock_ticks, 100, 30, 30) == TI_OK);
    ticks += 10; CHECK(ti_steps_due() == 3);
    ticks += 100; CHECK(ti_steps_due() == 30);
    ticks += 101; CHECK(ti_steps_due() == TI_STEPS_GAP);
    ticks += 4; CHECK(ti_steps_due() == 1);
    ti_time_note_gap(); CHECK(ti_steps_due() == 0);
    ticks += 4; CHECK(ti_steps_due() == 1);
    ti_steps_reset(); CHECK(ti_steps_due() == 0);
    /* Random rates, caps and frame lengths against the reference. */
    for (i = 0; i < 20000; ++i) {
        if (!(i % 500)) {
            seed = seed * 1103515245UL + 12345UL;
            rate = (uint8_t)(10 + (seed >> 16) % 60);
            most = (uint8_t)(1 + (seed >> 8) % 40);
            CHECK(ti_steps_begin(clock_ticks, 100, rate, most) == TI_OK);
            accumulator = 0;
        }
        seed = seed * 1103515245UL + 12345UL;
        elapsed = (uint16_t)((seed >> 16) % 101);
        ticks += elapsed;
        CHECK(ti_steps_due() == expected_steps(&accumulator, elapsed, 100, rate, most));
    }
}

int main(void)
{
    stick();
    steps();
    if (failures) { printf("%u input/steps host checks failed\n", failures); return 1; }
    printf("libtini stick and steps: all host checks passed\n");
    return 0;
}
