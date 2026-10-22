#include "internal.h"
#include "libtini/amem.h"
#ifndef TI_PRIVATE_TRANSPORT
#define TI_PRIVATE_TRANSPORT 0
#endif

#if TI_PRIVATE_TRANSPORT
#pragma code-name ("AMEMCODE")
#define FIFO (*(volatile uint8_t *)0xCFF0)
#define CONTROL (*(volatile uint8_t *)0xCFF1)
#define POP (*(volatile uint8_t *)0xCFF2)
#define VBL (*(volatile uint8_t *)0xC019)
uint8_t ti_amem_saved_p, ti_amem_saved_cx;
void ti_amem_lock(void);
void ti_amem_unlock(void);
static uint8_t status[32], packet[26], active, poisoned, last_error;

static uint8_t receive(void) { uint8_t v = FIFO; POP = 0; return v; }
/* The slot-7 ROM waits for the controller without a limit; the ARM answers
 * from its service loop. Bound the wait in display time, not CPU speed:
 * RDVBLBAR changes twice a frame, so 240 changes take 2 s at 60 Hz. */
static uint8_t wait_response(void)
{
    uint8_t changes = 0, level = VBL & 128;
    while (!(CONTROL & 128)) {
        if ((VBL & 128) == level) continue;
        level ^= 128;
        if (++changes == 240) { poisoned = 1; last_error = 0x67; return 0; }
    }
    return 1;
}
static void parameters(uint8_t command)
{
    uint8_t i;
    FIFO = command;
    FIFO = 3; FIFO = 0; FIFO = 0; FIFO = 0; FIFO = 0x80;
    for (i = 0; i < 4; ++i) FIFO = 0;
}
static ti_error probe_status(void)
{
    uint8_t i, low, high;
    parameters(0); CONTROL = 2;
    if (!wait_response()) return TI_E_IO;
    last_error = receive();
    if (last_error) {
        if (last_error == 0x21 || last_error == 0x60 || last_error == 0x66)
            return TI_E_UNAVAILABLE;
        poisoned = 1; return TI_E_IO;
    }
    low = receive(); high = receive();
    if (low != 32 || high) { poisoned = 1; last_error = 0x61; return TI_E_IO; }
    for (i = 0; i < 32; ++i) status[i] = receive();
    if (status[0] != 'A' || status[1] != 'M' || status[2] != 'E' || status[3] != 'M' ||
        status[4] != 1 || status[6] != 16 || !status[7] || (status[8] & 7) != 7 ||
        status[10] || status[11] != 2 || status[12] || status[13] != 0xC0 ||
        !(status[15] & 1)) return TI_E_UNAVAILABLE;
    return TI_OK;
}
static uint8_t identify(void)
{
    const volatile uint8_t *rom = (const volatile uint8_t *)0xC700;
    uint16_t crc = 0xFFFF, i;
    uint8_t bit;
    if (rom[0] != 0xC9 || rom[1] != 0x20 || rom[3] || rom[5] != 3 || rom[7]) return 0;
    for (i = 0; i < 256; ++i) {
        crc ^= (uint16_t)rom[i] << 8;
        for (bit = 0; bit < 8; ++bit) crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
    }
    /* F1.3.1 slot-7 ROM, CRC-16/CCITT-FALSE of 256 bytes. This identifies
     * the read-only interface; no third-party ROM bytes are redistributed. */
    return crc == 0x95D9;
}
static void put16(uint8_t *p, uint16_t n) { p[0] = (uint8_t)n; p[1] = (uint8_t)(n >> 8); }
static ti_error execute(uint8_t op, uint8_t db, uint16_t da, uint8_t sb,
                         uint16_t sa, uint16_t length, uint8_t value)
{
    uint8_t i;
    ti_error error;
    if (poisoned) return TI_E_IO;
    if (!active) return TI_E_UNAVAILABLE;
    if (ti_storage_pause_hook) ti_storage_pause_hook();
    ti_amem_lock();
    error = probe_status();
    if (!error && ((db != 255 && db > status[14]) || (op == 1 && sb != 255 && sb > status[14])))
        error = TI_E_UNAVAILABLE;
    if (!error) {
        for (i = 0; i < 26; ++i) packet[i] = 0;
        packet[0] = 24;
        packet[2] = 'A'; packet[3] = 'M'; packet[4] = 'E'; packet[5] = 'M';
        packet[6] = 1; packet[7] = 1;
        packet[10] = op; packet[11] = 1; /* PRIVATE working destinations only */
        if (op == 1) {
            packet[12] = sb == 255 ? 0 : 1; packet[13] = sb == 255 ? 0 : sb;
            put16(packet + 14, sa);
        }
        packet[16] = db == 255 ? 0 : 1; packet[17] = db == 255 ? 0 : db;
        put16(packet + 18, da); put16(packet + 20, length); packet[22] = value;
        parameters(4);
        for (i = 0; i < 26; ++i) FIFO = packet[i];
        CONTROL = 2;
        if (!wait_response()) error = TI_E_IO;
        else {
            last_error = receive();
            if (last_error) { poisoned = 1; error = TI_E_IO; }
        }
    }
    ti_amem_unlock();
    if (ti_storage_resume_hook) ti_storage_resume_hook();
    ti_time_note_gap();
    return error;
}
static ti_error fast_rw(uint8_t bank, uint16_t address, uint8_t *near_buffer,
                         uint16_t length, uint8_t write)
{
    return write ? execute(1, bank, address, 255, (uint16_t)near_buffer, length, 0) :
                   execute(1, 255, (uint16_t)near_buffer, bank, address, length, 0);
}
static ti_error fast_fill(uint8_t bank, uint16_t address, uint8_t value, uint16_t length)
{ return execute(2, bank, address, 0, 0, length, value); }
static ti_error fast_copy(uint8_t db, uint16_t da, uint8_t sb, uint16_t sa, uint16_t length)
{ return execute(1, db, da, sb, sa, length, 0); }

ti_error ti_amem_enable(void)
{
    ti_error error;
    if (poisoned) return TI_E_IO;
    if (ti_storage_pause_hook) ti_storage_pause_hook();
    ti_amem_lock();
    error = identify() ? probe_status() : TI_E_UNAVAILABLE;
    ti_amem_unlock();
    if (ti_storage_resume_hook) ti_storage_resume_hook();
    active = error == TI_OK;
    if (active) {
        ti_accel_rw_hook = fast_rw; ti_accel_fill_hook = fast_fill; ti_accel_copy_hook = fast_copy;
    } else ti_amem_disable();
    return error;
}
uint8_t ti_amem_available(void) { return active && !poisoned && ti_accel_rw_hook != 0; }
uint8_t ti_amem_last_error(void) { return last_error; }
void ti_amem_disable(void)
{
    active = 0;
    ti_accel_rw_hook = 0; ti_accel_fill_hook = 0; ti_accel_copy_hook = 0;
}
#else
ti_error ti_amem_enable(void) { return TI_E_UNAVAILABLE; }
void ti_amem_disable(void) { }
uint8_t ti_amem_available(void) { return 0; }
uint8_t ti_amem_last_error(void) { return 0x21; }
#endif
