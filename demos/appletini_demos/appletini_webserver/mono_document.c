/* SPDX-License-Identifier: MIT */
#include "mono_document.h"
#include "mono_gfx.h"
#ifdef __CC65__
#pragma code-name ("CODE")
#pragma rodata-name ("RODATA")
#endif

uint16_t mono_document_length, mono_document_capacity;
uint8_t mono_document_pending;
static uint8_t large_document;

void mono_document_reset(void) { mono_document_length = 0; }

void mono_document_init(void)
{
    uint8_t saved[6], i, good = 1;
    /* Save every logical bank before modifying any bank. Aliased selectors
     * then have identical saved values, so restoring all selectors is safe. */
    for (i = 0; i != 6; ++i) saved[i] = mono_bank_get(i,0xBFFE);
    for (i = 0; i != 6; ++i) mono_bank_set(i,0xBFFE,(uint8_t)(0xB4U+i));
    for (i = 0; i != 6; ++i)
        if (mono_bank_get(i,0xBFFE) != (uint8_t)(0xB4U+i)) good = 0;
    for (i = 0; i != 6; ++i) mono_bank_set(i,0xBFFE,saved[i]);
    large_document = good;
    mono_document_capacity = good ? 65535U : 8192U;
    mono_document_reset();
}

static uint8_t valid_buffer(const void *buffer, uint16_t length)
{
    if (!buffer) return 0;
#ifdef __CC65__
    {
        uint16_t p = (uint16_t)buffer;
        if (p < 0x0200U || p >= 0xC000U || length > 0xC000U-p) return 0;
    }
#else
    (void)length;
#endif
    return 1;
}

static void transfer(uint16_t at, uint8_t *data, uint16_t length, uint8_t write)
{
    uint16_t offset, n, address;
    uint8_t bank;
    while (length) {
        if (large_document) {
            bank = at < 40960U ? 4 : 5;
            offset = at < 40960U ? at : at-40960U;
            n = 40960U-offset;
            address = 0x2000U+offset;
        } else {
            bank = 0;
            n = length;
            address = 0xA000U+at;
        }
        if (n > length) n = length;
        if (write) mono_bank_write(bank,address,data,n);
        else mono_bank_read(bank,address,data,n);
        at += n; data += n; length -= n;
    }
}

uint8_t mono_document_append(const uint8_t *data, uint16_t length)
{
    uint16_t n;
    if(mono_document_pending) {mono_document_reset();mono_document_pending=0;}
    n = mono_document_capacity-mono_document_length;
    if (n > length) n = length;
    if (n && !valid_buffer(data,n)) return 2;
    if (n) transfer(mono_document_length,(uint8_t*)data,n,1);
    mono_document_length += n;
    return n == length ? 0 : 2;
}

void mono_document_read(uint16_t offset, void *destination, uint16_t length)
{
    if (offset >= mono_document_length) return;
    if (length > mono_document_length-offset) length = mono_document_length-offset;
    if (length && valid_buffer(destination,length))
        transfer(offset,(uint8_t*)destination,length,0);
}
