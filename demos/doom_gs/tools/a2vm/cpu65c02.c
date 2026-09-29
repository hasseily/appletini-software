/*
 * The W65C02S core of cpu65c02.h connected through function pointers,
 * and the parts of the core that make no bus cycles.
 */
#include "cpu65c02.h"

#include <string.h>

#define C02_PREFIX cpu65c02_
#define C02_LINKAGE
#define C02_READ(cpu, address, kind) (cpu)->read((cpu)->context, address, kind)
#define C02_WRITE(cpu, address, value, kind) \
    (cpu)->write((cpu)->context, address, value, kind)
#include "cpu65c02_core.h"

void cpu65c02_init(cpu65c02 *cpu, cpu65c02_read_fn read,
                   cpu65c02_write_fn write, void *context)
{
    memset(cpu, 0, sizeof *cpu);
    cpu->p = CPU65C02_U | CPU65C02_I;
    cpu->s = 0xff;
    cpu->state = CPU65C02_RUNNING;
    cpu->read = read;
    cpu->write = write;
    cpu->context = context;
}

void cpu65c02_set_irq(cpu65c02 *cpu, uint32_t sources, int active)
{
    if (active)
        cpu->irq_sources |= sources;
    else
        cpu->irq_sources &= ~sources;
}

void cpu65c02_nmi(cpu65c02 *cpu)
{
    cpu->nmi_pending = 1;
}

void cpu65c02_normalise(cpu65c02 *cpu)
{
    cpu->p = (uint8_t)((cpu->p | CPU65C02_U) & ~CPU65C02_B);
}

/* Table 5-2 and table 7-1 of the datasheet. */
const uint8_t cpu65c02_length[256] = {
/*        0  1  2  3  4  5  6  7  8  9  A  B  C  D  E  F */
/* 0 */   2, 2, 2, 1, 2, 2, 2, 2, 1, 2, 1, 1, 3, 3, 3, 3,
/* 1 */   2, 2, 2, 1, 2, 2, 2, 2, 1, 3, 1, 1, 3, 3, 3, 3,
/* 2 */   3, 2, 2, 1, 2, 2, 2, 2, 1, 2, 1, 1, 3, 3, 3, 3,
/* 3 */   2, 2, 2, 1, 2, 2, 2, 2, 1, 3, 1, 1, 3, 3, 3, 3,
/* 4 */   1, 2, 2, 1, 2, 2, 2, 2, 1, 2, 1, 1, 3, 3, 3, 3,
/* 5 */   2, 2, 2, 1, 2, 2, 2, 2, 1, 3, 1, 1, 3, 3, 3, 3,
/* 6 */   1, 2, 2, 1, 2, 2, 2, 2, 1, 2, 1, 1, 3, 3, 3, 3,
/* 7 */   2, 2, 2, 1, 2, 2, 2, 2, 1, 3, 1, 1, 3, 3, 3, 3,
/* 8 */   2, 2, 2, 1, 2, 2, 2, 2, 1, 2, 1, 1, 3, 3, 3, 3,
/* 9 */   2, 2, 2, 1, 2, 2, 2, 2, 1, 3, 1, 1, 3, 3, 3, 3,
/* A */   2, 2, 2, 1, 2, 2, 2, 2, 1, 2, 1, 1, 3, 3, 3, 3,
/* B */   2, 2, 2, 1, 2, 2, 2, 2, 1, 3, 1, 1, 3, 3, 3, 3,
/* C */   2, 2, 2, 1, 2, 2, 2, 2, 1, 2, 1, 1, 3, 3, 3, 3,
/* D */   2, 2, 2, 1, 2, 2, 2, 2, 1, 3, 1, 1, 3, 3, 3, 3,
/* E */   2, 2, 2, 1, 2, 2, 2, 2, 1, 2, 1, 1, 3, 3, 3, 3,
/* F */   2, 2, 2, 1, 2, 2, 2, 2, 1, 3, 1, 1, 3, 3, 3, 3,
};
