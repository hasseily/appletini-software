#ifndef TI_GRAPHICS_INTERNAL_H
#define TI_GRAPHICS_INTERNAL_H
/* Shared by the drawing and publication modules. Near-row publication,
 * single pixels and text are separate archive members, so a program links
 * only what it calls. */
extern uint8_t ti_gfx_video_active;
extern uint16_t ti_gfx_publish_budget;
extern uint32_t ti_gfx_publish_ticks;
extern ti_tick_source ti_gfx_publish_clock;
ti_error ti_gfx_surface_valid(const ti_surface *surface);
uint8_t ti_gfx_clip(const ti_surface *surface, ti_rect *rectangle);
ti_error ti_gfx_dot(ti_surface *surface, int16_t x, int16_t y, uint8_t color);
ti_error ti_gfx_cache_flush(void);
/* One surface row, for rectangles and text, between guard bytes. */
extern uint8_t ti_gfx_rows[3 + 160 + 2];
#define ti_gfx_row (ti_gfx_rows + 3)
/* Rows of a checked surface, moved without per-row resource calls by
 * target/surface.s. ti_gfx_rows_begin locates the surface's first byte and
 * sets the stride; ti_row_seek takes a byte offset within the surface. */
extern uint8_t ti_row_base_bank, ti_row_bank, ti_row_bytes;
extern uint16_t ti_row_base_addr, ti_row_addr, ti_row_stride;
void ti_gfx_rows_begin(const ti_surface *surface);
void ti_row_seek(uint16_t offset);
void ti_row_next(void);
void ti_row_read(void);
void ti_row_write(void);
#endif
