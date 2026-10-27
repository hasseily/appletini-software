#include "memory_internal.h"

/* All mapped accesses execute in target/memory.s, never in these C routines. */
uint8_t ti_io_bank, ti_io_len;
uint16_t ti_io_addr;
uint8_t *ti_io_near;
extern uint8_t ti_writable_start, ti_readable_start, ti_memory_end;
extern uint8_t ti_readable_low_start, ti_readable_low_end;
extern uint8_t ti_stack_bottom, ti_stack_top, ti_near_start, ti_near_end, ti_transfer_start;
#define STAGE (&ti_transfer_start)

static ti_memory_resource slots[TI_RESOURCE_SLOTS];
static uint8_t active, first, count;
static uint32_t capacity;
static uint8_t saved[128];
static uint8_t probe_byte;
/* Logical window cache: narrow graphics rows usually stay in one bank.
 * No mapped pointer or hardware selection is retained between calls. */
static uint32_t cpu_window_base;
static uint8_t cpu_window_bank;
/* Non-zero while the diagnostic video backup is held; graphics_rows.c
 * checks it once per rectangle, as ti_diag_video_write does per write. */
ti_handle ti_video_backup;
#define video_backup ti_video_backup
static ti_handle storage_screen;
void (*ti_graphics_cleanup_hook)(void);
ti_error (*ti_audio_cleanup_hook)(void);
void (*ti_storage_pause_hook)(void);
void (*ti_storage_resume_hook)(void);
ti_accel_rw ti_accel_rw_hook;
ti_accel_fill ti_accel_fill_hook;
ti_accel_copy ti_accel_copy_hook;

uint8_t ti_near_valid(const void *pointer, uint16_t length, uint8_t write)
{
    uint16_t p = (uint16_t)pointer;
    uint16_t begin = write ? (uint16_t)&ti_writable_start : (uint16_t)&ti_readable_start;
    if (!length) return 1;
    if (p >= begin && p < (uint16_t)&ti_memory_end)
        return length <= (uint16_t)((uint16_t)&ti_memory_end - p);
    if (p >= (uint16_t)&ti_stack_bottom && p < (uint16_t)&ti_stack_top)
        return length <= (uint16_t)((uint16_t)&ti_stack_top - p);
    if (p >= (uint16_t)&ti_near_start && p < (uint16_t)&ti_near_end)
        return length <= (uint16_t)((uint16_t)&ti_near_end - p);
    if (!write && p >= (uint16_t)&ti_readable_low_start && p < (uint16_t)&ti_readable_low_end)
        return length <= (uint16_t)((uint16_t)&ti_readable_low_end - p);
    return 0;
}

static void physical(uint8_t bank, uint16_t addr, uint8_t *near_buffer,
                     uint8_t length, uint8_t write)
{
    ti_io_bank = bank;
    ti_io_addr = addr;
    ti_io_near = near_buffer;
    ti_io_len = length;
    if (write) ti_cpu_write(); else ti_cpu_read();
}

static uint8_t probe(void)
{
    uint8_t i, okay = 1;
    /* Save every original before any writes, so aliases restore correctly. */
    physical(0, 0xA000, &saved[0], 1, 0);
    for (i = 0; i < count; ++i)
        physical((uint8_t)(first + i), 0xA000, &saved[i + 1], 1, 0);
    probe_byte = 0x5A;
    physical(0, 0xA000, &probe_byte, 1, 1);
    for (i = 0; i < count; ++i) {
        probe_byte = (uint8_t)(i ^ 0x80);
        physical((uint8_t)(first + i), 0xA000, &probe_byte, 1, 1);
    }
    physical(0, 0xA000, &probe_byte, 1, 0);
    if (probe_byte != 0x5A) okay = 0;
    for (i = 0; i < count; ++i) {
        physical((uint8_t)(first + i), 0xA000, &probe_byte, 1, 0);
        if (probe_byte != (uint8_t)(i ^ 0x80)) okay = 0;
    }
    physical(0, 0xA000, &saved[0], 1, 1);
    for (i = 0; i < count; ++i)
        physical((uint8_t)(first + i), 0xA000, &saved[i + 1], 1, 1);
    return okay;
}

ti_error ti_init(uint8_t first_bank, uint8_t bank_count)
{
    if (active) return TI_E_STATE;
    /* Baseline's first 8 MiB PSRAM serves selectors 0..126, not 127. */
    if (!first_bank || !bank_count || first_bank > 126 ||
        bank_count > (uint8_t)(127 - first_bank)) return TI_E_ARGUMENT;
    first = first_bank;
    count = bank_count;
    if (!probe()) return TI_E_UNAVAILABLE;
    capacity = (uint32_t)count * TI_BANK_BYTES;
    active = 1;
    ti_time_note_gap();
    return TI_OK;
}

static void release_slot(ti_memory_resource *r)
{
    r->used = 0;
    if (r->generation == 4095) r->retired = 1;
    else ++r->generation;
}

ti_error ti_shutdown(void)
{
    uint8_t i;
    ti_error error;
    if (ti_audio_cleanup_hook) {
        error = ti_audio_cleanup_hook();
        if (error) return error; /* A registered OS callback still owns code. */
    }
    ti_audio_cleanup_hook = 0;
    if (ti_graphics_cleanup_hook) ti_graphics_cleanup_hook();
    ti_graphics_cleanup_hook = 0;
    ti_diag_video_end();
    ti_accel_rw_hook = 0; ti_accel_fill_hook = 0; ti_accel_copy_hook = 0;
    for (i = 0; i < TI_RESOURCE_SLOTS; ++i)
        if (slots[i].used) release_slot(&slots[i]);
    active = 0;
    return TI_OK;
}

ti_memory_resource *ti_memory_lookup(ti_handle handle)
{
    uint8_t i = (uint8_t)(handle & 15);
    ti_memory_resource *r;
    if (!active || !i || i > TI_RESOURCE_SLOTS) return 0;
    r = &slots[i - 1];
    if (!r->used || r->generation != (handle >> 4)) return 0;
    return r;
}

ti_error ti_res_alloc(uint32_t size, ti_handle *out)
{
    uint8_t i, slot = TI_RESOURCE_SLOTS, retry;
    uint32_t base = 0;
    if (!out || !ti_near_valid(out, sizeof(*out), 1)) return TI_E_ARGUMENT;
    *out = TI_INVALID_HANDLE;
    if (!active) return TI_E_STATE;
    if (!size) return TI_E_ARGUMENT;
    for (i = 0; i < TI_RESOURCE_SLOTS; ++i)
        if (!slots[i].used && !slots[i].retired) { slot = i; break; }
    if (slot == TI_RESOURCE_SLOTS) return TI_E_NOMEM;
    do {
        if (base > capacity || size > capacity - base) return TI_E_NOMEM;
        retry = 0;
        for (i = 0; i < TI_RESOURCE_SLOTS; ++i) {
            if (slots[i].used && slots[i].base < base + size &&
                slots[i].base + slots[i].size > base) {
                base = slots[i].base + slots[i].size;
                retry = 1;
                break;
            }
        }
    } while (retry);
    slots[slot].base = base;
    slots[slot].size = size;
    if (!slots[slot].generation) slots[slot].generation = 1;
    slots[slot].used = 1;
    *out = (ti_handle)((slots[slot].generation << 4) | (slot + 1));
    return TI_OK;
}

ti_error ti_res_free(ti_handle handle)
{
    ti_memory_resource *r = ti_memory_lookup(handle);
    if (!r) return TI_E_HANDLE;
    /* A live video snapshot is internal, and cannot escape to a caller. */
    release_slot(r);
    return TI_OK;
}

uint8_t ti_memory_in_range(ti_memory_resource *r, uint32_t offset, uint32_t length)
{
    return offset <= r->size && length <= r->size - offset;
}

uint16_t ti_memory_address(ti_memory_resource *r, uint32_t offset, uint8_t *bank)
{
    uint32_t position = r->base + offset;
    if (position < cpu_window_base || position - cpu_window_base >= TI_BANK_BYTES) {
        cpu_window_bank = (uint8_t)(position / TI_BANK_BYTES);
        cpu_window_base = (uint32_t)cpu_window_bank * TI_BANK_BYTES;
    }
    *bank = (uint8_t)(first + cpu_window_bank);
    return (uint16_t)(0x0200 + (uint16_t)(position - cpu_window_base));
}

void ti_memory_transfer(ti_memory_resource *r, uint32_t offset, uint8_t *near_buffer,
                     uint16_t length, uint8_t write)
{
    uint16_t within, available;
    uint8_t piece, bank;
    within = ti_memory_address(r, offset, &bank) - 0x0200;
    while (length) {
        available = (uint16_t)(TI_BANK_BYTES - within);
        piece = length > TI_TRANSFER_BYTES ? TI_TRANSFER_BYTES : (uint8_t)length;
        if (available < piece) piece = (uint8_t)available;
        physical(bank, (uint16_t)(0x0200 + within), near_buffer, piece, write);
        within += piece;
        if (within == TI_BANK_BYTES) {
            within = 0; ++bank; ++cpu_window_bank;
            cpu_window_base += TI_BANK_BYTES;
        }
        near_buffer += piece;
        length -= piece;
    }
}

#if TI_PRIVATE_TRANSPORT
#pragma code-name ("AMEMCODE")
uint16_t ti_memory_locate(uint32_t position, uint8_t *bank, uint16_t *address)
{
    uint16_t within = (uint16_t)(position % TI_BANK_BYTES);
    *bank = (uint8_t)(first + (uint8_t)(position / TI_BANK_BYTES));
    *address = (uint16_t)(0x0200 + within);
    return (uint16_t)(TI_BANK_BYTES - within);
}
static ti_error accelerated(ti_memory_resource *r, uint32_t offset, uint8_t *buffer,
                             uint32_t length, uint8_t mode, uint8_t value)
{
    uint8_t bank, submitted = 0;
    uint16_t address, piece;
    ti_error error;
    if (length < 256 || (mode < 2 ? !ti_accel_rw_hook : !ti_accel_fill_hook)) return TI_E_UNAVAILABLE;
    while (length) {
        piece = ti_memory_locate(r->base + offset, &bank, &address);
        if (length < piece) piece = (uint16_t)length;
        error = mode == 2 ? ti_accel_fill_hook(bank, address, value, piece) :
                           ti_accel_rw_hook(bank, address, buffer, piece, mode);
        if (error) return submitted && error == TI_E_UNAVAILABLE ? TI_E_IO : error;
        submitted = 1; length -= piece; offset += piece;
        if (mode < 2) buffer += piece;
    }
    return TI_OK;
}

#pragma code-name ("CODE")
#endif

ti_error ti_res_read(ti_handle handle, uint32_t offset, void *dst, uint16_t length)
{
    ti_memory_resource *r = ti_memory_lookup(handle);
#if TI_PRIVATE_TRANSPORT
    ti_error fast;
#endif
    if (!r) return TI_E_HANDLE;
    if (!ti_memory_in_range(r, offset, length) || !ti_near_valid(dst, length, 1)) return TI_E_RANGE;
#if TI_PRIVATE_TRANSPORT
    fast = accelerated(r, offset, (uint8_t *)dst, length, 0, 0);
    if (fast != TI_E_UNAVAILABLE) return fast;
#endif
    ti_memory_transfer(r, offset, (uint8_t *)dst, length, 0);
    ti_time_note_gap();
    return TI_OK;
}

ti_error ti_res_write(ti_handle handle, uint32_t offset, const void *src, uint16_t length)
{
    ti_memory_resource *r = ti_memory_lookup(handle);
#if TI_PRIVATE_TRANSPORT
    ti_error fast;
#endif
    if (!r) return TI_E_HANDLE;
    if (!ti_memory_in_range(r, offset, length) || !ti_near_valid(src, length, 0)) return TI_E_RANGE;
#if TI_PRIVATE_TRANSPORT
    fast = accelerated(r, offset, (uint8_t *)src, length, 1, 0);
    if (fast != TI_E_UNAVAILABLE) return fast;
#endif
    ti_memory_transfer(r, offset, (uint8_t *)src, length, 1);
    ti_time_note_gap();
    return TI_OK;
}

ti_error ti_res_fill(ti_handle handle, uint32_t offset, uint8_t value, uint32_t length)
{
    ti_memory_resource *r = ti_memory_lookup(handle);
    uint8_t i, piece;
#if TI_PRIVATE_TRANSPORT
    ti_error fast;
#endif
    if (!r) return TI_E_HANDLE;
    if (!ti_memory_in_range(r, offset, length)) return TI_E_RANGE;
#if TI_PRIVATE_TRANSPORT
    fast = accelerated(r, offset, 0, length, 2, value);
    if (fast != TI_E_UNAVAILABLE) return fast;
#endif
    for (i = 0; i < TI_TRANSFER_BYTES; ++i) STAGE[i] = value;
    while (length) {
        piece = length > TI_TRANSFER_BYTES ? TI_TRANSFER_BYTES : (uint8_t)length;
        ti_memory_transfer(r, offset, STAGE, piece, 1);
        offset += piece;
        length -= piece;
    }
    ti_time_note_gap();
    return TI_OK;
}

/* Setup-only routines are in TISETUP, which a game layout can overlay. ti_init
 * is not: a game calls it before it can load anything. */
#pragma code-name (push, "TISETUP")
/* Preserve all 32768 aux bytes including SCBs, palettes and unused padding. */
ti_error ti_diag_video_begin(void)
{
    uint16_t offset;
    ti_error error;
    ti_memory_resource *r;
    if (video_backup) return TI_E_STATE;
    error = ti_res_alloc(32768UL, &video_backup);
    if (error) return error;
    r = ti_memory_lookup(video_backup);
    for (offset = 0; offset < 32768U; offset += TI_TRANSFER_BYTES) {
        physical(0, (uint16_t)(0x2000 + offset), STAGE, TI_TRANSFER_BYTES, 0);
        ti_memory_transfer(r, offset, STAGE, TI_TRANSFER_BYTES, 1);
    }
    ti_video_on();
    ti_time_note_gap();
    return TI_OK;
}
#pragma code-name (pop)

ti_error ti_diag_video_end(void)
{
    uint16_t offset;
    ti_memory_resource *r;
    if (!video_backup) return TI_OK;
    if (storage_screen) ti_video_storage_end();
    ti_video_off();
    r = ti_memory_lookup(video_backup);
    if (!r) return TI_E_HANDLE;
    for (offset = 0; offset < 32768U; offset += TI_TRANSFER_BYTES) {
        ti_memory_transfer(r, offset, STAGE, TI_TRANSFER_BYTES, 0);
        physical(0, (uint16_t)(0x2000 + offset), STAGE, TI_TRANSFER_BYTES, 1);
    }
    ti_res_free(video_backup);
    video_backup = 0;
    return TI_OK;
}

void ti_diag_video_write(uint16_t address, const uint8_t *src, uint8_t length)
{
    if (video_backup && address >= 0x2000 && length && length <= TI_TRANSFER_BYTES &&
        address <= (uint16_t)(0xA000 - length))
        physical(0, address, (uint8_t *)src, length, 1);
    ti_time_note_gap();
}

/* Lend AUX0 back to ProDOS during a synchronous file transaction. Keep the
 * picture and OS image in separate resources, and capture any /RAM changes
 * before republishing. A mode write alone would not restore those bytes. */
ti_error ti_video_storage_begin(void)
{
    uint16_t offset;
    ti_error error;
    ti_memory_resource *picture, *os;
    if (storage_screen) return TI_E_BUSY;
    if (!video_backup) return TI_OK;
    error = ti_res_alloc(32768UL, &storage_screen);
    if (error) return error;
    picture = ti_memory_lookup(storage_screen);
    os = ti_memory_lookup(video_backup);
    for (offset = 0; offset < 32768U; offset += TI_TRANSFER_BYTES) {
        physical(0, (uint16_t)(0x2000 + offset), STAGE, TI_TRANSFER_BYTES, 0);
        ti_memory_transfer(picture, offset, STAGE, TI_TRANSFER_BYTES, 1);
    }
    ti_video_off();
    for (offset = 0; offset < 32768U; offset += TI_TRANSFER_BYTES) {
        ti_memory_transfer(os, offset, STAGE, TI_TRANSFER_BYTES, 0);
        physical(0, (uint16_t)(0x2000 + offset), STAGE, TI_TRANSFER_BYTES, 1);
    }
    return TI_OK;
}

ti_error ti_video_storage_end(void)
{
    uint16_t offset;
    ti_memory_resource *picture, *os;
    if (!storage_screen) return TI_OK;
    picture = ti_memory_lookup(storage_screen);
    os = ti_memory_lookup(video_backup);
    for (offset = 0; offset < 32768U; offset += TI_TRANSFER_BYTES) {
        physical(0, (uint16_t)(0x2000 + offset), STAGE, TI_TRANSFER_BYTES, 0);
        ti_memory_transfer(os, offset, STAGE, TI_TRANSFER_BYTES, 1);
        ti_memory_transfer(picture, offset, STAGE, TI_TRANSFER_BYTES, 0);
        physical(0, (uint16_t)(0x2000 + offset), STAGE, TI_TRANSFER_BYTES, 1);
    }
    ti_res_free(storage_screen);
    storage_screen = 0;
    ti_video_on();
    ti_time_note_gap();
    return TI_OK;
}
