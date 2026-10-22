#ifndef LIBTINI_STORAGE_H
#define LIBTINI_STORAGE_H
#include "types.h"

/* Synchronous, foreground-only, one file at a time. Upper-case relative
 * ProDOS names (1..15 characters). Never retains the caller's near buffer.
 * Audio/game time pauses while storage owns the OS; active SHR is preserved.
 * A failed write can leave a partial file: use two validated save slots. */
ti_error ti_file_read(const char *name, void *dst, uint16_t capacity, uint16_t *length);
ti_error ti_file_write(const char *name, const void *src, uint16_t length);
uint8_t ti_file_last_error(void); /* Original ProDOS error, zero after success. */

/* TPK1 directory is validated in full before allocating/copying an entry.
 * Success transfers ownership of a resource handle to the caller. On error
 * closes the file and frees a partially loaded resource; outputs are zero. */
ti_error ti_pack_load(const char *name, const char *entry,
                      ti_handle *out, uint32_t *size);
#endif
