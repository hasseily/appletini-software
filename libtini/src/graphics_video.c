#include "memory_internal.h"
#include "libtini/graphics.h"
#include "graphics_internal.h"
#pragma code-name ("LOWCODE")

extern void (*ti_graphics_cleanup_hook)(void);
/* target/publish.s copies the rows of a rectangle once these checks pass. */
extern uint8_t ti_pub_rows;
extern uint16_t ti_pub_to;
void ti_cpu_publish_rows(void);
uint8_t ti_gfx_video_active;
uint16_t ti_gfx_publish_budget = 32000;
uint32_t ti_gfx_publish_ticks;
ti_tick_source ti_gfx_publish_clock;
#define video_active ti_gfx_video_active
#define publish_budget ti_gfx_publish_budget
#define publish_ticks ti_gfx_publish_ticks
#define publish_clock ti_gfx_publish_clock

static void cleanup(void) { ti_gfx_end(); }

#pragma code-name (push, "TISETUP")
ti_error ti_gfx_begin(const uint16_t *palette)
{
    uint16_t offset;
    uint8_t i;
    ti_error e;
    if (video_active) return TI_E_STATE;
    if (!palette || !ti_near_valid(palette, 32, 0)) return TI_E_ARGUMENT;
    for (i = 0; i < 16; ++i) if (palette[i] > 4095) return TI_E_RANGE;
    e = ti_diag_video_begin(); if (e) return e;
    video_active = 1;
    ti_graphics_cleanup_hook = cleanup;
    for (i = 0; i < 128; ++i) ti_gfx_row[i] = 0;
    for (offset = 0x9D00; offset < 0x9E00; offset += 128) ti_diag_video_write(offset, ti_gfx_row, 128);
    return ti_gfx_palette(palette);
}
#pragma code-name (pop)

ti_error ti_gfx_palette(const uint16_t *palette)
{
    uint8_t i;
    if (!video_active) return TI_E_STATE;
    if (!palette || !ti_near_valid(palette, 32, 0)) return TI_E_ARGUMENT;
    for (i = 0; i < 16; ++i) if (palette[i] > 4095) return TI_E_RANGE;
    for (i = 0; i < 16; ++i) {
        ti_gfx_row[i * 2] = (uint8_t)palette[i];
        ti_gfx_row[i * 2 + 1] = (uint8_t)(palette[i] >> 8);
    }
    ti_diag_video_write(0x9E00, ti_gfx_row, 32);
    return TI_OK;
}

ti_error ti_gfx_end(void)
{
    ti_error e;
    if (!video_active) return TI_OK;
    e = ti_diag_video_end();
    if (!e) { video_active = 0; ti_graphics_cleanup_hook = 0; }
    return e;
}

void ti_gfx_budget(uint16_t bytes, ti_tick_source clock, uint32_t ticks)
{ publish_budget = bytes ? bytes : 32000; publish_clock = clock; publish_ticks = ticks; }

ti_error ti_gfx_present(const ti_surface *s, const ti_rect *rectangle, ti_gfx_stats *stats)
{
    ti_rect r;
    ti_gfx_stats report;
    uint16_t left, bytes, first;
    uint32_t start;
    ti_error e = ti_gfx_surface_valid(s);
    if (e) return e;
    if (!video_active) return TI_E_STATE;
    if (s->width != 320 || s->height != 200) return TI_E_RANGE;
    if (stats && !ti_near_valid(stats, sizeof(*stats), 1)) return TI_E_ARGUMENT;
    r.x = r.y = 0; r.width = 320; r.height = 200;
    if (rectangle) { if (!ti_near_valid(rectangle, sizeof(*rectangle), 0)) return TI_E_ARGUMENT; r = *rectangle; }
    report.bytes = report.elapsed_ticks = 0; report.flags = TI_GFX_EDGE_GAP;
    if (!ti_gfx_clip(s, &r)) { if (stats) *stats = report; return TI_OK; }
    left = (uint16_t)r.x / 2;
    bytes = ((uint16_t)r.x % 2 + r.width + 1) / 2;
    if ((uint32_t)bytes * r.height > publish_budget) return TI_E_TIMING;
    start = publish_clock ? publish_clock() : 0;
    /* The surface check covered every row. At most 199 rows of 160 bytes:
     * the offset fits 16 bits. */
    first = (uint16_t)r.y * 160 + left;
    if (ti_video_backup) {
        ti_gfx_rows_begin(s);
        ti_row_bytes = (uint8_t)bytes;
        ti_row_seek(first);
        ti_pub_to = 0x2000 + first;
        ti_pub_rows = (uint8_t)r.height;
        ti_cpu_publish_rows();
    }
    ti_time_note_gap();
    report.bytes = (uint32_t)bytes * r.height;
    if (publish_clock) {
        report.flags |= TI_GFX_CLOCK_VALID;
        report.elapsed_ticks = publish_clock() - start;
        if (publish_ticks && report.elapsed_ticks > publish_ticks) report.flags |= TI_GFX_OVERRUN;
    }
    if (stats) *stats = report;
    return report.flags & TI_GFX_OVERRUN ? TI_E_TIMING : TI_OK;
}

