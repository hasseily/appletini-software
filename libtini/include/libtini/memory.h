#ifndef LIBTINI_MEMORY_H
#define LIBTINI_MEMORY_H
#include "types.h"

#define TI_RESOURCE_SLOTS 8
#define TI_BANK_BYTES 48640UL /* $0200..$BFFF, never a C address space */
#define TI_TRANSFER_BYTES 128

/* Explicit grant of exclusive banks; bank zero is never allocatable.
 * Init probes aliasing without retaining changes. CPU path is always present;
 * the optional AMEM module must be explicitly enabled after initialization.
 * Foreground only, non-reentrant. See docs/reference/machine.html before
 * using an IRQ. */
ti_error ti_init(uint8_t first_bank, uint8_t bank_count);
ti_error ti_shutdown(void);
ti_error ti_near_move(void *dst, const void *src, uint16_t length);
ti_error ti_near_fill(void *dst, uint8_t value, uint16_t length);

/* Allocation is uninitialized, contiguous in the logical bank window stream.
 * No mapped pointer escapes. Free and shutdown invalidate all copies of a handle.
 * Read/write borrow near buffers only until the synchronous call returns.
 * Copy has memmove overlap semantics, including same-handle copies. */
ti_error ti_res_alloc(uint32_t size, ti_handle *out);
ti_error ti_res_free(ti_handle handle);
ti_error ti_res_read(ti_handle handle, uint32_t offset, void *dst, uint16_t length);
ti_error ti_res_write(ti_handle handle, uint32_t offset, const void *src, uint16_t length);
ti_error ti_res_fill(ti_handle handle, uint32_t offset, uint8_t value, uint32_t length);
ti_error ti_res_copy(ti_handle dst, uint32_t dst_offset,
                     ti_handle src, uint32_t src_offset, uint32_t length);
#endif
