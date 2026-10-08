/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef APPLETINI_CARDS_H
#define APPLETINI_CARDS_H

#include "a2vm.h"

typedef struct ap_cards ap_cards;

ap_cards *ap_cards_new(a2vm *vm);
void ap_cards_free(ap_cards *cards);
int ap_cards_mount(ap_cards *cards, const char *path, char *error, size_t size);
int ap_cards_mode(ap_cards *cards, const char *mode);
unsigned ap_cards_slot7(const ap_cards *cards); /* SmartPort=0, SuperSprite=1 */
int ap_cards_read(ap_cards *cards, const char *kind, unsigned offset,
                   void *buffer, size_t size);
/* Update virtual VBlank and IRQ before a core step. */
void ap_cards_tick(ap_cards *cards);
/* Functional ROM entry traps; returns 1 if a trap replaced this core step. */
int ap_cards_step(ap_cards *cards);
/* Enable supplied real slot-7 firmware. Validated before any mutation. */
int ap_cards_boot(ap_cards *cards, const void *slot_rom, size_t slot_size,
                   const void *c8_rom, size_t c8_size);

#endif
