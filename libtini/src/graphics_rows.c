#include "internal.h"
#include "libtini/graphics.h"
#include "graphics_internal.h"

/* Separate archive member: only near-row clients pay this code cost. CPU
 * mapping changes remain inside the existing low-memory video-write backend.
 * One assembly call writes every row, instead of one C call per row. */
ti_error ti_gfx_present_rows(uint16_t x, uint16_t y, uint16_t width,
                            uint16_t height, const uint8_t *source,
                            uint16_t stride, ti_gfx_stats *stats)
{
    ti_gfx_stats report;
    uint16_t bytes, total;
    uint32_t start;
    if (!ti_gfx_video_active) return TI_E_STATE;
    if (!width || !height || !source) return TI_E_ARGUMENT;
    if (stats && !ti_near_valid(stats, sizeof(*stats), 1)) return TI_E_ARGUMENT;
    if ((x & 1) || (width & 1) || x >= TI_GFX_WIDTH || y >= TI_GFX_HEIGHT ||
        width > TI_GFX_WIDTH - x || height > TI_GFX_HEIGHT - y) return TI_E_RANGE;
    /* At most 160 bytes a row and 200 rows, so 16-bit arithmetic suffices.
     * The source spans (height - 1) * stride + bytes, which must fit 16 bits;
     * every stride up to 327 does with 200 rows. */
    bytes = width / 2;
    if (stride < bytes || (stride > 327 && height > 1 &&
        stride > (uint16_t)(65535U - bytes) / (height - 1)) ||
        !ti_near_valid(source, (height - 1) * stride + bytes, 0)) return TI_E_RANGE;
    total = bytes * height;
    if (total > ti_gfx_publish_budget) return TI_E_TIMING;
    report.elapsed_ticks = 0;
    report.flags = TI_GFX_EDGE_GAP;
    start = ti_gfx_publish_clock ? ti_gfx_publish_clock() : 0;
    /* The checks above keep every row inside the SHR pixels. */
    if (ti_video_backup) {
        ti_io_addr = (uint16_t)(0x2000U + y * 160U + x / 2);
        ti_io_near = (uint8_t *)source;
        ti_io_width = (uint8_t)bytes; ti_io_rows = (uint8_t)height; ti_io_stride = stride;
        ti_cpu_write_rows();
    }
    ti_time_note_gap();
    report.bytes = total;
    if (ti_gfx_publish_clock) {
        report.flags |= TI_GFX_CLOCK_VALID;
        report.elapsed_ticks = ti_gfx_publish_clock() - start;
        if (ti_gfx_publish_ticks && report.elapsed_ticks > ti_gfx_publish_ticks) report.flags |= TI_GFX_OVERRUN;
    }
    if (stats) *stats = report;
    return report.flags & TI_GFX_OVERRUN ? TI_E_TIMING : TI_OK;
}
