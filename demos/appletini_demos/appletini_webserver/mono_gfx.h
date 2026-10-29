/* SPDX-License-Identifier: MIT */
#ifndef MONO_GFX_H
#define MONO_GFX_H
#include <stdint.h>

#define MONO_WIDTH 560U
#define MONO_HEIGHT 384U
#define MONO_COLUMNS 80U
#define MONO_ROWS 48U

/* Graphics code/font use MAIN language-card bank 2, $D400-$DFFF. Startup
 * loads this region. The remaining program runs from MAIN $6000+.
 * Display owns MAIN+AUX $2000-$5FFF.
 * Init selects Video-7 MONO560 and begins a held update. Commit publishes
 * the complete pair. Begin holds the last complete frame during a redraw.
 * End selects normal 80-column text and clears private display markers. */
void mono_gfx_init(void);
void mono_gfx_begin(void);
void mono_gfx_commit(void);
void mono_gfx_end(void);
/* white=1 fills white; white=0 fills black. */
void mono_gfx_clear(uint8_t white);
/* 7x8 cells. inverse=0 draws black glyphs on white; 1 reverses the cell. */
void mono_gfx_text(uint8_t column, uint8_t row, const char *text,
                   uint8_t inverse);
void mono_gfx_invert(uint8_t column, uint8_t row, uint8_t count);
/* Packed row: seven pixels per byte, bit 0 leftmost; 1=white, 0=black.
 * column/count refer to packed bytes, 0..79, not pixels. */
void mono_gfx_row(uint16_t y, uint8_t column, const uint8_t *packed7,
                  uint8_t count);
/* This drawing argument is BLACK, unlike the clear argument WHITE. */
void mono_gfx_pixel(uint16_t x, uint16_t y, uint8_t black);
/* Pixel-only vertical clip, bottom exclusive. Text and packed rows keep
 * their full-screen bounds so browser controls can draw outside content. */
void mono_gfx_clip(uint16_t top, uint16_t bottom);

/* AUX scratch is $6000-$BFFF, outside both displayed page pairs. The
 * accessors preserve interrupt policy and keep instruction fetches in MAIN.
 * Invalid gets return 0; invalid sets/blocks leave memory unchanged. */
uint8_t mono_aux_get(uint16_t address);
void mono_aux_set(uint16_t address, uint8_t value);
void mono_aux_read(uint16_t address, void *destination, uint16_t length);
void mono_aux_write(uint16_t address, const void *source, uint16_t length);
/* RamWorks expansion scratch. Bank 0 remains the display/HTML/GIF bank.
 * Banks 1+ allow $2000-$BFFF. Each operation restores selector 0. The SYS
 * owns C073 while active; its launch contract requires selector 0. */
uint8_t mono_bank_get(uint8_t bank, uint16_t address);
void mono_bank_set(uint8_t bank, uint16_t address, uint8_t value);
void mono_bank_read(uint8_t bank, uint16_t address, void *destination,
                   uint16_t length);
void mono_bank_write(uint8_t bank, uint16_t address, const void *source,
                    uint16_t length);

#endif
