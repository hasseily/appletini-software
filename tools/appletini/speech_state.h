/* SPDX-License-Identifier: GPL-2.0-only
 * Independent Apple-visible SSI-263AP protocol model. No synthesis code. */
#ifndef APPLETINI_SPEECH_STATE_H
#define APPLETINI_SPEECH_STATE_H
#include <stdint.h>
typedef struct ap_ssi_state ap_ssi_state;
/* Two sockets. xck_hz is effective Q3/2, normally 1015625 PAL. Timestamps
 * are absolute guest CPU ticks, monotonic, beginning at origin. */
ap_ssi_state *ap_ssi_new(uint64_t guest_hz, uint32_t xck_hz, uint64_t origin);
void ap_ssi_free(ap_ssi_state *state);
void ap_ssi_advance(ap_ssi_state *state, uint64_t tick);
void ap_ssi_write(ap_ssi_state *state, unsigned chip, unsigned reg,
                  uint8_t value, uint64_t tick);
void ap_ssi_reset(ap_ssi_state *state, unsigned chip, int cold, uint64_t tick);
uint8_t ap_ssi_read(ap_ssi_state *state, unsigned chip, uint64_t tick);
/* mode 0 Mockingboard, 5 Phasor; other modes disconnect IRQ routing.
 * PCR bit0 selects CA1 rising edge (1) or SSI falling edge (0). */
void ap_ssi_route(ap_ssi_state *state, unsigned mode, uint8_t pcr0,
                  uint8_t pcr1, uint64_t tick);
int ap_ssi_irq(const ap_ssi_state *state);
/* Returns 1 when CA1 must set VIA IFR bit1, then clears this pending pulse.
 * SSI acknowledgement never clears VIA IFR; the VIA owns that latch. */
int ap_ssi_take_ca1(ap_ssi_state *state, unsigned chip);
#endif
