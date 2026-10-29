/* SPDX-License-Identifier: MIT */
#pragma code-name ("LC")
#pragma rodata-name ("LC")
#include "mono_gfx.h"
#include "mono_font.h"

/* Shared assembler parameters stay in MAIN. Code/font use MAIN LC bank 2;
 * only explicit access helpers select AUX memory. */
uint16_t mono_address;
const uint8_t *mono_source;
uint8_t *mono_destination;
uint16_t mono_length;
uint8_t mono_value, mono_count, mono_parity, mono_bank;
static uint8_t text_pixels[80];
static uint16_t clip_top, clip_bottom;
static const uint8_t masks[7] = {1,2,4,8,16,32,64};
void mono_hw_init(void);
void mono_hw_begin(void);
void mono_hw_commit(void);
void mono_hw_end(void);
void mono_hw_clear(void);
void mono_hw_row(void);
uint8_t mono_hw_read(void);
void mono_hw_write(void);
void mono_hw_read_block(void);
void mono_hw_write_block(void);

static uint16_t row_address(uint16_t y)
{
    uint8_t line = (uint8_t)(y >> 1);
    return (y & 1U ? 0x4000U : 0x2000U) +
           ((uint16_t)(line & 7U) << 10) +
           ((uint16_t)(line & 0x38U) << 4) +
           (uint16_t)(line >> 6) * 40U;
}

void mono_gfx_init(void)
{
    clip_top = 0;
    clip_bottom = MONO_HEIGHT;
    mono_hw_init();
}
void mono_gfx_clip(uint16_t top, uint16_t bottom)
{
    clip_top = top;
    clip_bottom = bottom;
}
void mono_gfx_begin(void) { mono_hw_begin(); }
void mono_gfx_commit(void) { mono_hw_commit(); }
void mono_gfx_end(void) { mono_hw_end(); }
void mono_gfx_clear(uint8_t white)
{
    mono_value = white ? 0x7F : 0;
    mono_hw_clear();
}

void mono_gfx_row(uint16_t y, uint8_t column, const uint8_t *pixels,
                  uint8_t count)
{
    if (y >= MONO_HEIGHT || column >= MONO_COLUMNS || !pixels) return;
    if (count > MONO_COLUMNS-column) count = (uint8_t)(MONO_COLUMNS-column);
    if (!count) return;
    mono_address = row_address(y) + (column >> 1);
    mono_parity = column & 1U;
    mono_source = pixels;
    mono_count = count;
    mono_hw_row();
}

void mono_gfx_text(uint8_t column, uint8_t row, const char *text,
                   uint8_t inverse)
{
    uint8_t n, i, gy, c;
    if (column >= MONO_COLUMNS || row >= MONO_ROWS || !text) return;
    n = 0;
    while (n < MONO_COLUMNS-column && text[n]) ++n;
    for (gy = 0; gy != 8; ++gy) {
        for (i = 0; i != n; ++i) {
            c = (uint8_t)text[i];
            if (c < 32 || c > 127) c = '?';
            text_pixels[i] = mono_font[(uint16_t)(c-32U)*8U+gy];
            if (!inverse) text_pixels[i] ^= 0x7F;
        }
        mono_gfx_row((uint16_t)row*8U+gy, column, text_pixels, n);
    }
}

void mono_gfx_invert(uint8_t column, uint8_t row, uint8_t count)
{
    uint8_t gy, i;
    if (column >= MONO_COLUMNS || row >= MONO_ROWS) return;
    if (count > MONO_COLUMNS-column) count = (uint8_t)(MONO_COLUMNS-column);
    mono_bank = 0;
    for (gy = 0; gy != 8; ++gy) {
        for (i = 0; i != count; ++i) {
            mono_address = row_address((uint16_t)row*8U+gy) +
                           ((uint8_t)(column+i) >> 1);
            if ((column+i) & 1U) {
                *(uint8_t*)mono_address ^= 0x7F;
            } else {
                mono_value = mono_hw_read() ^ 0x7F;
                mono_hw_write();
            }
        }
    }
}

void mono_gfx_pixel(uint16_t x, uint16_t y, uint8_t black)
{
    uint8_t column, mask;
    if (x >= MONO_WIDTH || y >= MONO_HEIGHT ||
        y < clip_top || y >= clip_bottom) return;
    column = (uint8_t)(x / 7U);
    mask = masks[(uint8_t)(x % 7U)];
    mono_address = row_address(y) + (column >> 1);
    mono_bank = 0;
    if (column & 1U) mono_value = *(uint8_t*)mono_address;
    else mono_value = mono_hw_read();
    if (black) mono_value &= (uint8_t)~mask;
    else mono_value |= mask;
    if (column & 1U) *(uint8_t*)mono_address = mono_value;
    else mono_hw_write();
}

uint8_t mono_bank_get(uint8_t bank, uint16_t address)
{
    if (address < 0x2000U || address >= 0xC000U ||
        (!bank && address < 0x6000U)) return 0;
    mono_bank = bank;
    mono_address = address;
    return mono_hw_read();
}
void mono_bank_set(uint8_t bank, uint16_t address, uint8_t value)
{
    if (address < 0x2000U || address >= 0xC000U ||
        (!bank && address < 0x6000U)) return;
    mono_bank = bank;
    mono_address = address;
    mono_value = value;
    mono_hw_write();
}
uint8_t mono_aux_get(uint16_t address) { return mono_bank_get(0,address); }
void mono_aux_set(uint16_t address, uint8_t value)
{
    mono_bank_set(0,address,value);
}
void mono_aux_read(uint16_t address, void *destination, uint16_t length)
{
    mono_bank_read(0,address,destination,length);
}
void mono_aux_write(uint16_t address, const void *source, uint16_t length)
{
    mono_bank_write(0,address,source,length);
}
static uint8_t block_valid(uint8_t bank, uint16_t address, const void *buffer,
                           uint16_t length)
{
    uint16_t p = (uint16_t)buffer;
    return length && address >= (bank ? 0x2000U : 0x6000U) &&
           address < 0xC000U && length <= 0xC000U-address &&
           p >= 0x0200U && p < 0xC000U && length <= 0xC000U-p;
}
void mono_bank_read(uint8_t bank, uint16_t address, void *destination,
                   uint16_t length)
{
    if (!block_valid(bank,address,destination,length)) return;
    mono_bank = bank;
    mono_address = address;
    mono_destination = (uint8_t*)destination;
    mono_length = length;
    mono_hw_read_block();
}
void mono_bank_write(uint8_t bank, uint16_t address, const void *source,
                    uint16_t length)
{
    if (!block_valid(bank,address,source,length)) return;
    mono_bank = bank;
    mono_address = address;
    mono_source = (const uint8_t*)source;
    mono_length = length;
    mono_hw_write_block();
}
