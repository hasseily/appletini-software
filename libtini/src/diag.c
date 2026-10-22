#include "internal.h"

static uint8_t buffer[256], compare[256], row[128];
/* Executable-only diagnostic observations, exported for emulator inspection. */
uint8_t results[5];
/* Original 5x7 diagnostic alphabet, rows from top to bottom. */
static const uint8_t glyphs[][7] = {
 {14,17,19,21,25,17,14},{4,12,4,4,4,4,14},{14,17,1,2,4,8,31},
 {30,1,1,14,1,1,30},{2,6,10,18,31,2,2},{31,16,16,30,1,1,30},
 {14,16,16,30,17,17,14},{31,1,2,4,8,8,8},{14,17,17,14,17,17,14},
 {14,17,17,15,1,1,14},
 {14,17,17,31,17,17,17},{30,17,17,30,17,17,30},{15,16,16,16,16,16,15},
 {30,17,17,17,17,17,30},{31,16,16,30,16,16,31},{31,16,16,30,16,16,16},
 {15,16,16,19,17,17,15},{17,17,17,31,17,17,17},{14,4,4,4,4,4,14},
 {7,2,2,2,18,18,12},{17,18,20,24,20,18,17},{16,16,16,16,16,16,31},
 {17,27,21,21,17,17,17},{17,25,21,19,17,17,17},{14,17,17,17,17,17,14},
 {30,17,17,30,16,16,16},{14,17,17,17,21,18,13},{30,17,17,30,20,18,17},
 {15,16,16,14,1,1,30},{31,4,4,4,4,4,4},{17,17,17,17,17,17,14},
 {17,17,17,17,17,10,4},{17,17,17,21,21,27,17},{17,17,10,4,10,17,17},
 {17,17,10,4,4,4,4},{31,1,2,4,8,16,31}
};

static void text(uint8_t y, const char *message, uint8_t color)
{
    uint8_t x = 8, ch, gy, gx, bits, pixel;
    while ((ch = (uint8_t)*message++) != 0 && x < 152) {
        for (gy = 0; gy < 7; ++gy) {
            bits = 0;
            if (ch >= '0' && ch <= '9') bits = glyphs[ch - '0'][gy];
            if (ch >= 'A' && ch <= 'Z') bits = glyphs[ch - 'A' + 10][gy];
            for (gx = 0; gx < 4; ++gx) {
                pixel = (bits & (uint8_t)(16 >> (gx * 2))) ? (uint8_t)(color << 4) : 0;
                if (gx < 2 && (bits & (uint8_t)(8 >> (gx * 2)))) pixel |= color;
                row[gx] = pixel;
            }
            ti_diag_video_write((uint16_t)(0x2000 + (uint16_t)(y + gy) * 160 + x), row, 4);
        }
        x += 4;
    }
}

static void tests(void)
{
    uint16_t i;
    ti_handle h, old, other;
    results[0] = ti_near_fill(buffer, 0x39, sizeof(buffer)) == TI_OK;
    results[0] &= ti_near_move(buffer + 1, buffer, 255) == TI_OK && buffer[255] == 0x39;
    results[1] = ti_res_alloc(TI_BANK_BYTES + 256, &h) == TI_OK;
    if (results[1]) {
        for (i = 0; i < 256; ++i) buffer[i] = (uint8_t)(i ^ 0xA5);
        results[1] &= ti_res_write(h, TI_BANK_BYTES - 128, buffer, 256) == TI_OK;
        results[1] &= ti_res_read(h, TI_BANK_BYTES - 128, compare, 256) == TI_OK;
        for (i = 0; i < 256; ++i) if (buffer[i] != compare[i]) results[1] = 0;
        results[2] = ti_res_fill(h, 0, 0x6D, 256) == TI_OK;
        results[2] &= ti_res_read(h, 0, compare, 256) == TI_OK;
        for (i = 0; i < 256; ++i) if (compare[i] != 0x6D) results[2] = 0;
        results[2] &= ti_res_write(h, 0, buffer, 256) == TI_OK;
        results[2] &= ti_res_copy(h, 1, h, 0, 255) == TI_OK;
        results[2] &= ti_res_read(h, 0, compare, 256) == TI_OK;
        if (compare[0] != buffer[0]) results[2] = 0;
        for (i = 1; i < 256; ++i) if (compare[i] != buffer[i - 1]) results[2] = 0;
        results[3] = ti_res_read(h, TI_BANK_BYTES + 255, compare, 2) == TI_E_RANGE;
        results[3] &= ti_res_read(h, 0, (void *)0xBF00, 1) == TI_E_RANGE;
        results[3] &= ti_near_fill((void *)0x0400, 0, 1) == TI_E_RANGE;
        old = h;
        ti_res_free(h);
        results[4] = ti_res_read(old, 0, compare, 1) == TI_E_HANDLE;
        results[4] &= ti_res_alloc(0xFFFFFFFFUL, &other) == TI_E_NOMEM;
        results[4] &= ti_res_alloc(32, &other) == TI_OK;
        results[4] &= old != other;
        ti_res_free(other);
    }
}

static void screen(void)
{
    uint16_t address;
    uint8_t i;
    static const uint8_t palette[32] = {
        0,0, 0xFF,0x0F, 0x60,0x0F, 0xE5,0x02,
        0x3F,0x00, 0xFF,0x00, 0x0F,0x0F, 0xAF,0x0A,
        0x88,0x08, 0x44,0x04, 0,0,0,0,0,0,0,0,0,0,0,0
    };
    for (i = 0; i < 128; ++i) row[i] = 0;
    for (address = 0x2000; address < 0xA000; address += 128)
        ti_diag_video_write(address, row, 128);
    ti_diag_video_write(0x9E00, palette, 32);
    text(16, "LIBTINI FOUNDATION", 1);
    text(32, "CPU ONLY  CHECKPOINT 1", 2);
    text(56, "NEAR MOVE AND FILL", 1);
    text(72, "CROSS BANK TRANSFER", 1);
    text(88, "BANK FILL AND OVERLAP", 1);
    text(104, "RESERVED RANGE GUARDS", 1);
    text(120, "ALLOCATION AND LIFETIME", 1);
    for (i = 0; i < 5; ++i)
        text((uint8_t)(64 + i * 16), results[i] ? "PASS" : "FAIL", results[i] ? 3 : 4);
    text(152, "FRAMES ARE OBSERVED EDGES", 2);
    text(168, "ELAPSED CLOCK UNAVAILABLE", 2);
    text(184, "PRESS A KEY TO QUIT", 1);
}

int main(void)
{
    uint8_t i;
    const char *failure = "LIBTINI NEEDS RAMWORKS BANKS 1 AND 2";
    ti_time_sample sample;
    ti_time_begin(0, 0);
    if (ti_init(1, 2) != TI_OK) {
        for (i = 0; failure[i] && i < 40; ++i)
            ((uint8_t *)0x0400)[i] = (uint8_t)(failure[i] | 0x80);
        ti_key_clear();
        while (!ti_key_pending()) { }
        ti_key_clear();
        return 1;
    }
    tests();
    if (ti_diag_video_begin() != TI_OK) { ti_shutdown(); return 1; }
    screen();
    ti_key_clear();
    while (!ti_key_pending()) ti_time_poll(&sample);
    ti_key_clear();
    ti_diag_video_end();
    ti_shutdown();
    return 0;
}
