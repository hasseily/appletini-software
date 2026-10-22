#include "memory_internal.h"

#define STAGE (&ti_transfer_start)

#if TI_PRIVATE_TRANSPORT
#pragma code-name ("AMEMCODE")
static ti_error accelerated_copy(ti_memory_resource *d, uint32_t dp, ti_memory_resource *s, uint32_t sp, uint32_t length)
{
    uint8_t db, sb, submitted = 0;
    uint16_t da, sa, piece, other;
    ti_error error;
    if (length < 256 || !ti_accel_copy_hook || d == s) return TI_E_UNAVAILABLE;
    while (length) {
        piece = ti_memory_locate(d->base + dp, &db, &da);
        other = ti_memory_locate(s->base + sp, &sb, &sa);
        if (other < piece) piece = other;
        if (length < piece) piece = (uint16_t)length;
        error = ti_accel_copy_hook(db, da, sb, sa, piece);
        if (error) return submitted && error == TI_E_UNAVAILABLE ? TI_E_IO : error;
        submitted = 1; length -= piece; dp += piece; sp += piece;
    }
    return TI_OK;
}
#pragma code-name ("CODE")
#endif

ti_error ti_res_copy(ti_handle dst, uint32_t dst_offset,
                     ti_handle src, uint32_t src_offset, uint32_t length)
{
    ti_memory_resource *d = ti_memory_lookup(dst), *s = ti_memory_lookup(src);
    uint8_t piece, backward;
#if TI_PRIVATE_TRANSPORT
    ti_error fast;
#endif
    if (!d || !s) return TI_E_HANDLE;
    if (!ti_memory_in_range(d, dst_offset, length) || !ti_memory_in_range(s, src_offset, length)) return TI_E_RANGE;
#if TI_PRIVATE_TRANSPORT
    fast = accelerated_copy(d, dst_offset, s, src_offset, length);
    if (fast != TI_E_UNAVAILABLE) return fast;
#endif
    backward = dst == src && dst_offset > src_offset;
    while (length) {
        piece = length > TI_TRANSFER_BYTES ? TI_TRANSFER_BYTES : (uint8_t)length;
        if (backward) {
            ti_memory_transfer(s, src_offset + length - piece, STAGE, piece, 0);
            ti_memory_transfer(d, dst_offset + length - piece, STAGE, piece, 1);
        } else {
            ti_memory_transfer(s, src_offset, STAGE, piece, 0);
            ti_memory_transfer(d, dst_offset, STAGE, piece, 1);
            src_offset += piece;
            dst_offset += piece;
        }
        length -= piece;
    }
    ti_time_note_gap();
    return TI_OK;
}
