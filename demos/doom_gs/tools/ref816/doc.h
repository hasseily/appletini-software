/*
 * The Ensoniq 5503 DOC of the Apple IIgs and the sound GLU in front of it.
 *
 * The game uses the DOC as its only clock: oscillator 31 runs free over
 * a ramp in DOC RAM and I_GetTime reads its data register; oscillator 30
 * runs once over the same ramp with its interrupt enabled and wakes the
 * music. The sound code starts one-shot oscillators and reads their halt
 * bits. So this model steps every enabled oscillator at the chip's sample
 * rate, with the table addressing, halts and interrupts of the chip, but
 * makes no audio.
 *
 * Time is counted in master clocks of the IIgs (14.31818 MHz). The DOC
 * runs at half that rate and spends 8 of its clocks on each enabled
 * oscillator and on 2 more slots of refresh per sample, so with all 32
 * oscillators enabled a sample takes (32 + 2) * 8 * 2 = 544 master clocks
 * (26,320 samples per second).
 */
#ifndef DOC_H
#define DOC_H

#include <stdint.h>

enum {
    DOC_OSCILLATORS = 32,
    DOC_RAM_SIZE = 0x10000,
    DOC_MASTER_CLOCKS_PER_SLOT = 16     /* 8 DOC clocks of 2 master clocks */
};

/* The GLU control register ($C03C): bit 7 busy (always 0 here), bit 6
   DOC RAM rather than registers, bit 5 address auto-increment, bits 0-3
   the volume. */
enum { GLU_BUSY = 0x80, GLU_RAM = 0x40, GLU_INCREMENT = 0x20 };

/* Oscillator control register ($A0-$BF): bit 0 halt, bits 1-2 the mode,
   bit 3 interrupt enable, bits 4-7 the output channel. */
enum { DOC_HALT = 0x01, DOC_IRQ_ENABLE = 0x08 };
enum { DOC_FREE_RUN, DOC_ONE_SHOT, DOC_SYNC, DOC_SWAP };

typedef struct {
    uint16_t frequency;
    uint8_t volume;
    uint8_t data;               /* the last byte read from the table */
    uint8_t pointer;            /* table address, bits 8-15 */
    uint8_t control;
    uint8_t size;               /* bits 3-5 table size, bits 0-2 resolution */
    uint32_t accumulator;       /* 24 bits */
    uint8_t irq_pending;
} doc_oscillator;

typedef struct {
    doc_oscillator osc[DOC_OSCILLATORS];
    uint8_t enable;             /* register $E1: (oscillators - 1) * 2 */
    uint8_t last_irq;           /* register $E0 as last read */
    uint8_t ram[DOC_RAM_SIZE];

    uint8_t glu_control;
    uint16_t glu_address;
    uint8_t glu_latch;          /* what the next read of $C03D returns */

    uint64_t next_sample;       /* master clock of the next sample */
    uint64_t samples;           /* samples since doc_init */
} doc;

/* Power-on state at master clock `now`: every oscillator halted, one
   enabled, RAM clear. */
void doc_init(doc *d, uint64_t now);

/* Run every sample due at or before master clock `now`. */
void doc_run(doc *d, uint64_t now);

/* The sound GLU registers $C03C-$C03F (reg 0-3). Both bring the DOC up
   to `now` first. */
uint8_t doc_glu_read(doc *d, unsigned reg, uint64_t now);
void doc_glu_write(doc *d, unsigned reg, uint8_t value, uint64_t now);

/* The DOC's interrupt line: an oscillator with its interrupt pending. */
int doc_irq(const doc *d);

/* Master clocks per sample with the oscillators enabled now. */
uint64_t doc_sample_clocks(const doc *d);

#endif
