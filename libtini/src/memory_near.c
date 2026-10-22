#include "internal.h"

ti_error ti_near_move(void *dst, const void *src, uint16_t length)
{
    uint8_t *d = (uint8_t *)dst;
    const uint8_t *s = (const uint8_t *)src;
    if (!ti_near_valid(dst, length, 1) || !ti_near_valid(src, length, 0)) return TI_E_RANGE;
    if ((uint16_t)d > (uint16_t)s) {
        while (length) { --length; d[length] = s[length]; }
    } else {
        while (length) { *d++ = *s++; --length; }
    }
    ti_time_note_gap();
    return TI_OK;
}

ti_error ti_near_fill(void *dst, uint8_t value, uint16_t length)
{
    uint8_t *d = (uint8_t *)dst;
    if (!ti_near_valid(dst, length, 1)) return TI_E_RANGE;
    while (length) { *d++ = value; --length; }
    ti_time_note_gap();
    return TI_OK;
}
