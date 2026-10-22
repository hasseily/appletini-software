/* Compiled unchanged by cc65 and run on a 65C02. No host reference memory
 * implementation is substituted for the actual src/memory.c and backend. */
#include "libtini.h"
#include "internal.h"

volatile uint16_t test_checks, test_failed;
volatile uint8_t test_mode;
extern uint8_t test_flags_failure;
extern void test_backend_flags(void);
extern uint8_t ti_osstate_start;
static uint8_t source[640], result[640], expected[640];
static ti_handle handles[TI_RESOURCE_SLOTS], resource, other, stale, scratch;
static uint16_t i, j;
static uint32_t fake_ticks;
static ti_time_sample sample;

static void check(uint8_t condition, uint16_t id)
{
    ++test_checks;
    if (!condition && !test_failed) test_failed = id;
}

static uint8_t equal(const uint8_t *a, const uint8_t *b, uint16_t length)
{
    while (length--) if (*a++ != *b++) return 0;
    return 1;
}

static uint32_t fake_clock(void) { return fake_ticks; }

int main(void)
{
    if (test_mode == 3) {
        fake_ticks = 0;
        check(ti_time_begin(fake_clock, 1000) == TI_OK, 5);
        check(ti_time_poll(&sample) == TI_OK && sample.display_edges == 1, 6);
        check(ti_time_poll(&sample) == TI_OK && sample.display_edges == 1, 7);
        check(ti_time_poll(&sample) == TI_OK && sample.display_edges == 1, 8);
        fake_ticks = 10000UL;
        ti_time_note_gap();
        check(ti_time_poll(&sample) == TI_OK && sample.display_edges == 2 &&
              sample.elapsed_ticks == 10000UL && (sample.flags & TI_TIME_GAP), 9);
        fake_ticks = 100000UL;
        check(ti_time_poll(&sample) == TI_OK && sample.display_edges == 2 &&
              sample.elapsed_ticks == 100000UL, 130);
        return 0;
    }
    if (test_mode == 2) {
        check(ti_init(1, 3) == TI_OK, 3);
        check(ti_shutdown() == TI_OK, 4);
        return 0;
    }
    if (test_mode == 1) {
        check(ti_init(1, 3) == TI_E_UNAVAILABLE, 1);
        check(ti_res_alloc(1, &resource) == TI_E_STATE, 2);
        return 0;
    }
    check(ti_res_alloc(1, &resource) == TI_E_STATE, 10);
    check(resource == TI_INVALID_HANDLE, 11);
    check(ti_init(0, 1) == TI_E_ARGUMENT, 12);
    check(ti_init(1, 0) == TI_E_ARGUMENT, 13);
    check(ti_init(127, 2) == TI_E_ARGUMENT, 14);
    check(ti_init(127, 1) == TI_E_ARGUMENT, 131);
    check(ti_init(126, 2) == TI_E_ARGUMENT, 132);
    check(ti_init(1, 3) == TI_OK, 15);
    check(ti_init(1, 3) == TI_E_STATE, 16);

    for (i = 0; i < sizeof(source); ++i) source[i] = (uint8_t)(i * 29U + 7U);
    check(ti_near_fill(result, 0x33, sizeof(result)) == TI_OK, 20);
    check(result[0] == 0x33 && result[639] == 0x33, 21);
    check(ti_near_move(result, source, sizeof(source)) == TI_OK, 22);
    check(equal(result, source, sizeof(source)), 23);
    for (i = 0; i < sizeof(source); ++i) expected[i] = source[i];
    for (i = 500; i; --i) expected[i + 16] = expected[i - 1];
    check(ti_near_move(result + 17, result, 500) == TI_OK, 24);
    check(equal(result, expected, sizeof(result)), 25);
    for (i = 0; i < 500; ++i) expected[i] = expected[i + 17];
    check(ti_near_move(result, result + 17, 500) == TI_OK, 26);
    check(equal(result, expected, sizeof(result)), 27);
    check(ti_near_fill((void *)0x0080, 0, 1) == TI_E_RANGE, 28);
    check(ti_near_fill((void *)0x2000, 0, 1) == TI_E_RANGE, 29);
    check(ti_near_fill((void *)0xA800, 0, 1) == TI_E_RANGE, 30);
    check(ti_near_fill((void *)0xAF00, 0, 1) == TI_E_RANGE, 31);
    check(ti_near_fill((void *)0xBFFF, 0, 2) == TI_E_RANGE, 32);
    check(ti_near_fill((void *)0xFFFF, 0, 2) == TI_E_RANGE, 33);
    check(ti_near_move(result, (void *)0xC000, 1) == TI_E_RANGE, 34);
    check(ti_near_fill((void *)0, 0, 0) == TI_OK, 35);
    check(ti_near_fill((void *)0xA900, 0x31, 0x600) == TI_OK, 36);
    check(*(uint8_t *)0xA900 == 0x31 && *(uint8_t *)0xAEFF == 0x31, 37);
    check(ti_near_fill((void *)0xAEFF, 0, 2) == TI_E_RANGE, 38);
    check(ti_near_fill(&ti_osstate_start, 0, 1) == TI_E_RANGE, 39);

    check(ti_res_alloc(0, &resource) == TI_E_ARGUMENT, 40);
    check(ti_res_alloc(0xFFFFFFFFUL, &resource) == TI_E_NOMEM, 41);
    check(ti_res_alloc(1, (ti_handle *)0x2000) == TI_E_ARGUMENT, 42);
    check(ti_res_alloc(50000UL, &resource) == TI_OK, 43);
    check(ti_res_write(resource, TI_BANK_BYTES - 160, source, 640) == TI_OK, 44);
    check(ti_res_read(resource, TI_BANK_BYTES - 160, result, 640) == TI_OK, 45);
    check(equal(result, source, 640), 46);
    check(ti_res_fill(resource, TI_BANK_BYTES - 11, 0x5C, 300) == TI_OK, 47);
    for (i = 0; i < 640; ++i) expected[i] = source[i];
    for (i = 149; i < 449; ++i) expected[i] = 0x5C;
    check(ti_res_read(resource, TI_BANK_BYTES - 160, result, 640) == TI_OK, 48);
    check(equal(result, expected, 640), 49);
    check(ti_res_write(resource, 1000, source, 640) == TI_OK, 50);
    check(ti_res_copy(resource, 1017, resource, 1000, 500) == TI_OK, 51);
    for (i = 0; i < 640; ++i) expected[i] = source[i];
    for (i = 500; i; --i) expected[i + 16] = expected[i - 1];
    check(ti_res_read(resource, 1000, result, 640) == TI_OK, 52);
    check(equal(result, expected, 640), 53);
    check(ti_res_copy(resource, 1000, resource, 1017, 500) == TI_OK, 54);
    for (i = 0; i < 500; ++i) expected[i] = expected[i + 17];
    check(ti_res_read(resource, 1000, result, 640) == TI_OK, 55);
    check(equal(result, expected, 640), 56);
    check(ti_res_read(resource, 49999UL, result, 2) == TI_E_RANGE, 57);
    check(ti_res_write(resource, 0xFFFFFFFFUL, source, 1) == TI_E_RANGE, 58);
    check(ti_res_fill(resource, 1, 1, 0xFFFFFFFFUL) == TI_E_RANGE, 59);
    check(ti_res_read(resource, 0, (void *)0xA800, 1) == TI_E_RANGE, 60);
    check(ti_res_write(resource, 0, (void *)0xBFFF, 1) == TI_E_RANGE, 61);
    check(ti_res_read(resource, 50000UL, (void *)0, 0) == TI_OK, 62);
    check(ti_res_read(resource, 50001UL, (void *)0, 0) == TI_E_RANGE, 63);
    check(ti_res_alloc(700UL, &other) == TI_OK, 64);
    check(ti_res_copy(other, 0, resource, 1000, 640) == TI_OK, 65);
    check(ti_res_read(other, 0, result, 640) == TI_OK, 66);
    check(equal(result, expected, 640), 67);
    check(ti_res_free(other) == TI_OK, 68);
    check(ti_res_alloc(3UL * TI_BANK_BYTES - 50000UL, &other) == TI_OK, 69);
    check(ti_res_alloc(1, &scratch) == TI_E_NOMEM, 70);
    check(scratch == TI_INVALID_HANDLE, 71);
    check(ti_res_free(other) == TI_OK, 72);
    stale = resource;
    check(ti_res_free(resource) == TI_OK, 73);
    check(ti_res_free(stale) == TI_E_HANDLE, 74);
    check(ti_res_read(stale, 0, result, 1) == TI_E_HANDLE, 75);

    for (i = 0; i < TI_RESOURCE_SLOTS; ++i)
        check(ti_res_alloc(1, &handles[i]) == TI_OK, 80);
    check(ti_res_alloc(1, &scratch) == TI_E_NOMEM, 81);
    for (i = 0; i < TI_RESOURCE_SLOTS; ++i)
        check(ti_res_free(handles[i]) == TI_OK, 82);
    /* Run through the 12-bit generation boundary. A retired slot must not
     * resurrect a handle held by the caller, including after re-init. */
    for (j = 0; j < 4096; ++j) {
        check(ti_res_alloc(1, &scratch) == TI_OK, 83);
        check(ti_res_read(stale, 0, result, 1) == TI_E_HANDLE, 84);
        check(ti_res_free(scratch) == TI_OK, 85);
    }

    ti_io_bank = 3;
    ti_io_addr = 0xBF80;
    ti_io_near = source;
    ti_io_len = 128;
    test_backend_flags();
    check(test_flags_failure == 0, 90);

    check(ti_time_begin(0, 60) == TI_E_ARGUMENT, 100);
    check(ti_time_begin(fake_clock, 0) == TI_E_ARGUMENT, 101);
    check(ti_time_begin(0, 0) == TI_OK, 102);
    check(ti_time_poll(&sample) == TI_E_UNAVAILABLE, 103);
    check(!(sample.flags & TI_TIME_ELAPSED_VALID) && sample.elapsed_ticks == 0, 104);
    fake_ticks = 0xFFFFFFF0UL;
    check(ti_time_begin(fake_clock, 1000) == TI_OK, 105);
    fake_ticks = 0x20;
    check(ti_time_poll(&sample) == TI_OK, 106);
    check(sample.elapsed_ticks == 48 && sample.flags == TI_TIME_ELAPSED_VALID, 107);
    ti_time_note_gap();
    fake_ticks = 0xC00020UL;
    check(ti_time_poll(&sample) == TI_OK, 108);
    check(sample.elapsed_ticks == 0xC00030UL && (sample.flags & TI_TIME_GAP), 109);
    check(ti_time_poll((ti_time_sample *)0x2000) == TI_E_ARGUMENT, 110);

    check(ti_diag_video_begin() == TI_OK, 120);
    check(ti_diag_video_begin() == TI_E_STATE, 121);
    ti_diag_video_write(0x2000, source, 128);
    ti_diag_video_write(0x9F80, source, 128);
    /* Intentionally leave video active: ti_shutdown/startup must restore it. */
    check(ti_shutdown() == TI_OK, 122);
    check(ti_res_alloc(1, &resource) == TI_E_STATE, 123);
    check(ti_init(1, 3) == TI_OK, 124);
    check(ti_res_read(stale, 0, result, 1) == TI_E_HANDLE, 125);
    check(ti_res_alloc(1, &resource) == TI_OK, 126);
    check(ti_shutdown() == TI_OK, 127);
    check(ti_res_free(resource) == TI_E_HANDLE, 128);
    return 0;
}
