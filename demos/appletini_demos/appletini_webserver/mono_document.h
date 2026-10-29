/* SPDX-License-Identifier: MIT */
#ifndef MONO_DOCUMENT_H
#define MONO_DOCUMENT_H
#include <stdint.h>
/* Call init once before loading HTML. It probes six RamWorks banks without
 * retaining any probe writes. Capacity is 65535 bytes with six distinct
 * banks, or 8192 bytes in base AUX otherwise. Reset discards the document
 * without probing or clearing the backing RAM. All code belongs to MONO.WEB. */
void mono_document_init(void);
void mono_document_reset(void);
/* Append accepts a borrowed MAIN buffer. It returns 0 if all bytes fit,
 * or 2 after storing the available prefix when input exceeds capacity.
 * A null/invalid buffer is rejected with 2 and changes no document bytes.
 * Read clips to the current document length. MAIN buffers must not wrap. */
uint8_t mono_document_append(const uint8_t *data, uint16_t length);
void mono_document_read(uint16_t offset, void *destination, uint16_t length);
extern uint16_t mono_document_length, mono_document_capacity;
/* Defer replacement until the first ordinary response body reaches append. */
extern uint8_t mono_document_pending;
#endif
