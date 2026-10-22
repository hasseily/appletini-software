/* Text, rectangles, publication, digits and the kept error, on the native
 * machine. Every drawing call is compared with a pixel-at-a-time rendering
 * of the same call from the frozen font, over the whole surface, its padding
 * included. Every publication is compared over the whole screen. */
#include <string.h>
#include "internal.h"
#include "font_reference.h"

volatile uint16_t gfx_checks, gfx_failed;
static ti_handle prefix;
static ti_surface t;
static uint8_t expected_pixels[800], observed[160];
static char number[12], expected[12], long_text[1026];
static uint16_t seed = 12345;
static const char *const samples[8] = {
    "A", "SCORE 0012345", "x:y?\001\177\200\377", "AB\nCD", "\n\nZ", "0123456789", "  ", "WIDE  +2"};
static const char wide[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqr";

static void check(uint8_t ok, uint16_t id)
{ ++gfx_checks; if (!ok && !gfx_failed) gfx_failed = id; }
static uint16_t next_random(uint16_t range)
{ seed = seed * 25173U + 13849U; return (seed >> 4) % range; }
static void pixel(int16_t x, int16_t y, uint8_t color)
{
    uint16_t p;
    if (x < 0 || y < 0 || x >= (int16_t)t.width || y >= (int16_t)t.height) return;
    p = (uint16_t)y * t.stride + (uint16_t)x / 2;
    if (x & 1) expected_pixels[p] = (uint8_t)((expected_pixels[p] & 0xF0) | color);
    else expected_pixels[p] = (uint8_t)((expected_pixels[p] & 15) | (color << 4));
}
/* Lit pixels of each 6x8 cell, and with a background below 16 every other
 * pixel of the cell too. At most 1024 characters, newlines included. */
static void reference_text(int16_t x, int16_t y, const char *s, uint8_t color, uint8_t background)
{
    int16_t cx = x;
    uint16_t left = 1024;
    uint8_t row, col, glyph;
    for (; left && *s; ++s, --left) {
        if (*s == '\n') { cx = x; y += 8; continue; }
        for (row = 0; row < 8; ++row) {
            glyph = row < 7 ? ti_font_reference_row((uint8_t)*s, row) : 0;
            for (col = 0; col < 6; ++col)
                if (col < 5 && (glyph & (16 >> col))) pixel(cx + col, y + row, color);
                else if (background < 16) pixel(cx + col, y + row, background);
        }
        cx += 6;
    }
}
static void reference_rect(int16_t x, int16_t y, uint16_t w, uint16_t h, uint8_t color)
{
    uint16_t a, b;
    for (b = 0; b < h; ++b) for (a = 0; a < w; ++a) pixel(x + (int16_t)a, y + (int16_t)b, color);
}
/* A byte pattern in the surface and the reference, padding included. */
static void fill(void)
{
    uint16_t at, total = t.stride * t.height;
    for (at = 0; at < total; ++at) expected_pixels[at] = (uint8_t)(at * 37 + 11);
    for (at = 0; at < total; at += 160)
        check(ti_res_write(t.pixels, at, expected_pixels + at, total - at > 160 ? 160 : total - at) == TI_OK, 10);
}
static void compare(uint16_t id)
{
    uint16_t at, k, n, total = t.stride * t.height;
    uint8_t same = 1;
    for (at = 0; at < total; at += n) {
        n = total - at > 160 ? 160 : total - at;
        check(ti_res_read(t.pixels, at, observed, n) == TI_OK, id);
        for (k = 0; k < n; ++k) if (observed[k] != expected_pixels[at + k]) same = 0;
    }
    check(same, id + 1);
}
static void screen(uint8_t write, uint16_t address, uint8_t *near, uint8_t length)
{
    ti_io_bank = 0; ti_io_addr = address; ti_io_near = near; ti_io_len = length;
    if (write) ti_cpu_write(); else ti_cpu_read();
}
/* A byte for every surface position; neighbouring rows and banks differ. */
static uint8_t pattern(uint8_t row, uint8_t column) { return (uint8_t)(row * 7 + column * 3 + 1); }

/* A surface whose second bank starts at byte split, published in eight
 * rectangles. Checks id to id + 15 and 110-126. */
static void test_publication(uint16_t split, uint16_t id)
{
    static const uint16_t palette[16] = {0, 0xFFF};
    /* x, y, width, height: whole, odd edges, corners, rows of more than 128
     * bytes and exactly 128, rows across byte 98 * 160 + 70, rows far down
     * and clipping. */
    static const ti_rect rects[8] = {{0,0,320,200},{1,3,7,2},{0,0,1,1},{319,199,1,1},
        {3,96,317,5},{40,95,256,10},{0,150,320,4},{-5,-5,30,12}};
    static const uint8_t lefts[8] = {0,0,0,159,1,20,0,0}, widths[8] = {160,4,1,1,159,128,160,13};
    static const uint8_t tops[8] = {0,3,0,199,96,95,150,0}, heights[8] = {200,2,1,1,5,10,4,7};
    ti_gfx_stats stats;
    uint8_t k, row, column, same;
    check(ti_res_alloc(TI_BANK_BYTES - split, &prefix) == TI_OK, 110);
    t.pixels = 0;
    check(ti_gfx_surface_create(&t, 320, 200) == TI_OK, 111);
    for (row = 0; row < 200; ++row) {
        for (column = 0; column < 160; ++column) observed[column] = pattern(row, column);
        check(ti_res_write(t.pixels, (uint32_t)row * 160, observed, 160) == TI_OK, 112);
    }
    check(ti_gfx_begin(palette) == TI_OK, 113);
    ti_gfx_budget(0, 0, 0);
    for (k = 0; k < 8; ++k) {
        memset(observed, 0xA5, 160);
        for (row = 0; row < 200; ++row) { screen(1, 0x2000 + row * 160, observed, 80); screen(1, 0x2050 + row * 160, observed, 80); }
        check(ti_gfx_present(&t, &rects[k], &stats) == TI_OK, id + k);
        check(stats.bytes == (uint32_t)widths[k] * heights[k], id + 8 + k);
        same = 1;
        for (row = 0; row < 200; ++row) {
            screen(0, 0x2000 + row * 160, observed, 80); screen(0, 0x2050 + row * 160, observed + 80, 80);
            for (column = 0; column < 160; ++column)
                if (observed[column] != (row >= tops[k] && row < tops[k] + heights[k] && column >= lefts[k] &&
                                         column < lefts[k] + widths[k] ? pattern(row, column) : 0xA5)) same = 0;
        }
        check(same, 116 + k);
    }
    check(ti_gfx_end() == TI_OK, 124);
    check(ti_gfx_surface_free(&t) == TI_OK, 125);
    check(ti_res_free(prefix) == TI_OK, 126);
}

static void reference_digits(uint32_t value, uint8_t count)
{
    expected[count] = 0;
    while (count) { expected[--count] = (char)('0' + value % 10); value /= 10; }
}

static void test_drawing(void)
{
    static const int16_t wide_x[4] = {0, 1, -3, -1};
    uint16_t k, w, h;
    int16_t x, y;
    uint8_t color, background;
    /* 61x24: an odd width, and the second bank starts in row 9. */
    check(ti_res_alloc(TI_BANK_BYTES - 300, &prefix) == TI_OK, 1);
    check(ti_gfx_surface_create(&t, 61, 24) == TI_OK, 2);
    fill();
    for (k = 0; k < 64; ++k) {
        x = (int16_t)next_random(84) - 16;
        y = (int16_t)next_random(40) - 11;
        color = (uint8_t)(k % 16);
        background = k & 1 ? 16 : (uint8_t)(k * 7 % 16);
        if (background > 15) check(ti_gfx_text(&t, x, y, samples[k & 7], color) == TI_OK, 20);
        else check(ti_gfx_text_opaque(&t, x, y, samples[k & 7], color, background) == TI_OK, 21);
        reference_text(x, y, samples[k & 7], color, background);
        compare(22);
    }
    for (k = 0; k < 32; ++k) {
        x = (int16_t)next_random(76) - 8; y = (int16_t)next_random(32) - 4;
        w = next_random(40); h = next_random(14); color = (uint8_t)(k % 16);
        check(ti_gfx_rect(&t, x, y, w, h, color) == TI_OK, 30);
        reference_rect(x, y, w, h, color);
        compare(31);
    }
    /* The 1024th character is the B; then a B after the limit. */
    memset(long_text, ' ', 1022); long_text[1022] = '\n'; long_text[1023] = 'B'; long_text[1024] = 0;
    check(ti_gfx_text(&t, 3, 2, long_text, 9) == TI_OK, 40);
    reference_text(3, 2, long_text, 9, 16);
    compare(41);
    long_text[1022] = ' '; long_text[1023] = '\n'; long_text[1024] = 'B'; long_text[1025] = 0;
    check(ti_gfx_text_opaque(&t, 9, 4, long_text, 10, 2) == TI_OK, 43);
    reference_text(9, 4, long_text, 10, 2);
    compare(44);
    check(ti_gfx_text_opaque(&t, 0, 0, "A", 16, 0) == TI_E_ARGUMENT, 50);
    check(ti_gfx_text_opaque(&t, 0, 0, "A", 1, 16) == TI_E_ARGUMENT, 51);
    check(ti_gfx_text_opaque(&t, 0, 0, 0, 1, 2) == TI_E_ARGUMENT, 52);
    check(ti_gfx_text_opaque(0, 0, 0, "A", 1, 2) == TI_E_ARGUMENT, 53);
    check(ti_gfx_text_opaque(&t, 1025, 0, "A", 1, 2) == TI_E_RANGE, 54);
    check(ti_gfx_text(&t, 0, -1025, "A", 1) == TI_E_RANGE, 55);
    check(ti_gfx_text(&t, 0, 0, (const char *)0xA800, 1) == TI_E_RANGE, 56);
    check(ti_gfx_rect(&t, 0, 0, 1, 1, 16) == TI_E_ARGUMENT, 57);
    compare(58);
    check(ti_gfx_surface_free(&t) == TI_OK, 60);
    /* Full 160-byte rows: a clipped last cell reaches the guard bytes. */
    check(ti_gfx_surface_create(&t, 320, 5) == TI_OK, 61);
    fill();
    for (k = 0; k < 8; ++k) {
        x = wide_x[k & 3]; y = k & 4 ? -2 : 0;
        if (k & 1) check(ti_gfx_text(&t, x, y, wide, 5) == TI_OK, 62);
        else check(ti_gfx_text_opaque(&t, x, y, wide, 6, 1) == TI_OK, 63);
        reference_text(x, y, wide, k & 1 ? 5 : 6, k & 1 ? 16 : 1);
        compare(64);
    }
    check(ti_gfx_rect(&t, -1, 1, 322, 3, 7) == TI_OK, 66);
    reference_rect(-1, 1, 322, 3, 7);
    compare(67);
    check(ti_gfx_surface_free(&t) == TI_OK, 69);
    check(ti_res_free(prefix) == TI_OK, 70);
}

static void test_digits_and_errors(void)
{
    uint16_t k;
    uint32_t value;
    uint8_t count;
    /* Against repeated division, with the byte after the NUL kept. */
    for (k = 0; k < 120; ++k) {
        value = (uint32_t)next_random(65535U) << (k % 17) ^ next_random(9999);
        if (k == 1) value = 0;
        if (k == 2) value = 4294967295UL;
        count = (uint8_t)(1 + k % 10);
        memset(number, '#', sizeof(number));
        reference_digits(value, count);
        check(ti_digits(number, value, count) == number && !strcmp(number, expected) &&
              number[count + 1] == '#', 80);
    }
    check(!ti_digits(number, 5, 0) && !ti_digits(number, 5, 11), 81);
    check(!ti_digits(0, 5, 2) && !ti_digits((char *)0xA800, 5, 2), 82);
    /* The last two bytes of the near arena, and one past it. */
    check(ti_digits((char *)0xAEFE, 7, 1) == (char *)0xAEFE && *(char *)0xAEFE == '7' &&
          !*(char *)0xAEFF && !ti_digits((char *)0xAEFF, 7, 1), 83);
    /* The first kept error stays until cleared. */
    check(ti_error_first() == TI_OK && ti_error_keep(TI_OK) == TI_OK && ti_error_first() == TI_OK, 90);
    check(ti_error_keep(TI_E_RANGE) == TI_E_RANGE && ti_error_keep(TI_E_BUSY) == TI_E_BUSY &&
          ti_error_first() == TI_E_RANGE, 91);
    ti_error_clear();
    check(ti_error_first() == TI_OK, 92);
}

int main(void)
{
    check(ti_init(1, 6) == TI_OK, 100);
    test_drawing();
    /* Mid-row in the middle of the surface, then in its first row, so later
     * rows lie past address $FFFF of the first bank's window. */
    test_publication(98 * 160 + 70, 130);
    test_publication(100, 150);
    test_digits_and_errors();
    check(ti_shutdown() == TI_OK, 101);
    return 0;
}
