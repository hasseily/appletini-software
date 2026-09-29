/*
 * DOC and sound GLU: see doc.h.
 *
 * One sample of an oscillator, as the 5503 data sheet describes it: the
 * table index is the accumulator shifted right by 9 + resolution - size
 * code; an index past the end of the table ends a one-shot or swap pass
 * (halt) and wraps a free-running one with its phase kept; a table byte
 * of zero halts the oscillator in any mode; otherwise the byte becomes
 * the data register and the frequency is added to the 24-bit
 * accumulator. A halt raises the oscillator's interrupt when its enable
 * bit is set, and in swap mode starts the partner oscillator (number
 * xor 1). Sync mode is run as free-running: nothing in the game uses it.
 */
#include "doc.h"

#include <string.h>

enum {
    REG_FREQUENCY_LOW = 0x00, REG_FREQUENCY_HIGH = 0x20, REG_VOLUME = 0x40,
    REG_DATA = 0x60, REG_POINTER = 0x80, REG_CONTROL = 0xa0,
    REG_SIZE = 0xc0, REG_IRQ = 0xe0, REG_ENABLE = 0xe1, REG_ANALOG = 0xe2
};

static unsigned enabled(const doc *d)
{
    return ((d->enable >> 1) & 0x1f) + 1u;
}

uint64_t doc_sample_clocks(const doc *d)
{
    return (uint64_t)(enabled(d) + 2) * DOC_MASTER_CLOCKS_PER_SLOT;
}

void doc_init(doc *d, uint64_t now)
{
    memset(d, 0, sizeof *d);
    for (int i = 0; i < DOC_OSCILLATORS; i++)
        d->osc[i].control = DOC_HALT;
    d->last_irq = 0xff;
    d->next_sample = now + doc_sample_clocks(d);
}

static int mode_of(const doc_oscillator *o)
{
    return (o->control >> 1) & 3;
}

static void halt(doc *d, int number)
{
    doc_oscillator *o = &d->osc[number];
    o->control |= DOC_HALT;
    if (o->control & DOC_IRQ_ENABLE)
        o->irq_pending = 1;
    if (mode_of(o) == DOC_SWAP) {
        doc_oscillator *partner = &d->osc[number ^ 1];
        partner->control &= (uint8_t)~DOC_HALT;
        partner->accumulator = 0;
    }
}

static void step(doc *d, int number)
{
    doc_oscillator *o = &d->osc[number];
    unsigned size = (o->size >> 3) & 7, resolution = o->size & 7;
    uint32_t length = 256u << size;
    unsigned shift = 9 + resolution - size;
    uint32_t index = o->accumulator >> shift;

    if (index >= length) {
        int mode = mode_of(o);
        if (mode == DOC_ONE_SHOT || mode == DOC_SWAP) {
            halt(d, number);
            return;
        }
        o->accumulator -= length << shift;
        index -= length;
    }
    uint32_t base = ((uint32_t)o->pointer << 8) & ~(length - 1);
    uint8_t byte = d->ram[(base + index) & (DOC_RAM_SIZE - 1)];
    if (byte == 0) {
        halt(d, number);
        return;
    }
    o->data = byte;
    o->accumulator = (o->accumulator + o->frequency) & 0xffffff;
}

void doc_run(doc *d, uint64_t now)
{
    while (d->next_sample <= now) {
        unsigned count = enabled(d);
        for (unsigned i = 0; i < count; i++)
            if (!(d->osc[i].control & DOC_HALT))
                step(d, (int)i);
        d->samples++;
        d->next_sample += doc_sample_clocks(d);
    }
}

int doc_irq(const doc *d)
{
    for (int i = 0; i < DOC_OSCILLATORS; i++)
        if (d->osc[i].irq_pending)
            return 1;
    return 0;
}

/* Register $E0: bit 7 clear while an interrupt is pending, bits 1-5 the
   oscillator. A read acknowledges the lowest pending oscillator; the
   line stays active while another one is pending. */
static uint8_t read_irq(doc *d)
{
    for (int i = 0; i < DOC_OSCILLATORS; i++) {
        if (d->osc[i].irq_pending) {
            d->osc[i].irq_pending = 0;
            d->last_irq = (uint8_t)(i << 1 | 0x80);
            return (uint8_t)(i << 1 | 0x41);
        }
    }
    return (uint8_t)(d->last_irq | 0x41);
}

static uint8_t read_register(doc *d, uint8_t reg)
{
    doc_oscillator *o = &d->osc[reg & 0x1f];
    switch (reg & 0xe0) {
    case REG_FREQUENCY_LOW: return (uint8_t)o->frequency;
    case REG_FREQUENCY_HIGH: return (uint8_t)(o->frequency >> 8);
    case REG_VOLUME: return o->volume;
    case REG_DATA: return o->data;
    case REG_POINTER: return o->pointer;
    case REG_CONTROL: return o->control;
    case REG_SIZE: return o->size;
    default: break;
    }
    if (reg == REG_IRQ)
        return read_irq(d);
    if (reg == REG_ENABLE)
        return d->enable;
    if (reg == REG_ANALOG)
        return 0x80;            /* the analog input, at rest */
    return 0;
}

static void write_register(doc *d, uint8_t reg, uint8_t value)
{
    doc_oscillator *o = &d->osc[reg & 0x1f];
    switch (reg & 0xe0) {
    case REG_FREQUENCY_LOW:
        o->frequency = (uint16_t)((o->frequency & 0xff00) | value);
        return;
    case REG_FREQUENCY_HIGH:
        o->frequency = (uint16_t)((o->frequency & 0x00ff) | value << 8);
        return;
    case REG_VOLUME: o->volume = value; return;
    case REG_DATA: return;      /* read only */
    case REG_POINTER: o->pointer = value; return;
    case REG_CONTROL:
        /* A halted oscillator that starts begins at the top of its
           table. */
        if ((o->control & DOC_HALT) && !(value & DOC_HALT))
            o->accumulator = 0;
        o->control = value;
        return;
    case REG_SIZE: o->size = value; return;
    default: break;
    }
    if (reg == REG_ENABLE)
        d->enable = value;
}

uint8_t doc_glu_read(doc *d, unsigned reg, uint64_t now)
{
    doc_run(d, now);
    switch (reg & 3) {
    case 0:
        return d->glu_control & (uint8_t)~GLU_BUSY;
    case 1: {
        /* A read returns the byte of the access before and starts the
           next one, so software reads twice. */
        uint8_t value = d->glu_latch;
        d->glu_latch = (d->glu_control & GLU_RAM)
            ? d->ram[d->glu_address]
            : read_register(d, (uint8_t)d->glu_address);
        if (d->glu_control & GLU_INCREMENT)
            d->glu_address++;
        return value;
    }
    case 2:
        return (uint8_t)d->glu_address;
    default:
        return (uint8_t)(d->glu_address >> 8);
    }
}

void doc_glu_write(doc *d, unsigned reg, uint8_t value, uint64_t now)
{
    doc_run(d, now);
    switch (reg & 3) {
    case 0:
        d->glu_control = value & (uint8_t)~GLU_BUSY;
        return;
    case 1:
        if (d->glu_control & GLU_RAM)
            d->ram[d->glu_address] = value;
        else
            write_register(d, (uint8_t)d->glu_address, value);
        if (d->glu_control & GLU_INCREMENT)
            d->glu_address++;
        return;
    case 2:
        d->glu_address = (uint16_t)((d->glu_address & 0xff00) | value);
        return;
    default:
        d->glu_address = (uint16_t)((d->glu_address & 0x00ff) | value << 8);
        return;
    }
}
