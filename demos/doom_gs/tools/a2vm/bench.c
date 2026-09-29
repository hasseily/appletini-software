/*
 * How fast cpu65c02 runs on the host, in 65C02 instructions a second.
 *
 * usage: bench [MILLIONS_OF_CYCLES]      (default 1000)
 *
 * The same program runs on three buses:
 *   inline    the core included with its bus inlined (cpu65c02_core.h),
 *             on a flat 64 KB RAM: the speed a machine gets by building
 *             the core into itself
 *   callback  cpu65c02.c through its function pointers, flat RAM
 *   mapped    function pointers to a bus shaped like a machine's: a page
 *             table for reads and writes, a trap for $C000-$CFFF, and a
 *             count of accesses by kind, as a cost model will keep
 *
 * The program is a loop with the usual mix of a 65C02 inner loop: indexed
 * loads and stores, zero page, (zp),Y, arithmetic, branches, JSR and RTS
 * with pushes and pulls. The three runs must end in the same registers
 * and memory; the bench fails otherwise. Times are host CPU time from
 * clock(); nothing emulated depends on them.
 */
#include "cpu65c02.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static const uint8_t program[] = {
    /* $0800 */ 0xa2, 0x00,             /* start: LDX #$00          */
    /* $0802 */ 0xbd, 0x00, 0x10,       /* loop1: LDA $1000,X       */
    /* $0805 */ 0x9d, 0x00, 0x20,       /*        STA $2000,X       */
    /* $0808 */ 0x65, 0x30,             /*        ADC $30           */
    /* $080A */ 0x85, 0x31,             /*        STA $31           */
    /* $080C */ 0xe8,                   /*        INX               */
    /* $080D */ 0xd0, 0xf3,             /*        BNE loop1         */
    /* $080F */ 0x20, 0x23, 0x08,       /*        JSR sub           */
    /* $0812 */ 0xa0, 0x00,             /*        LDY #$00          */
    /* $0814 */ 0xb1, 0x40,             /* loop2: LDA ($40),Y       */
    /* $0816 */ 0x49, 0x55,             /*        EOR #$55          */
    /* $0818 */ 0x91, 0x42,             /*        STA ($42),Y       */
    /* $081A */ 0xc8,                   /*        INY               */
    /* $081B */ 0xd0, 0xf7,             /*        BNE loop2         */
    /* $081D */ 0xe6, 0x50,             /*        INC $50           */
    /* $081F */ 0x4c, 0x00, 0x08,       /*        JMP start         */
    /* $0822 */ 0xea,
    /* $0823 */ 0x48,                   /* sub:   PHA               */
    /* $0824 */ 0x8a,                   /*        TXA               */
    /* $0825 */ 0x48,                   /*        PHA               */
    /* $0826 */ 0x68,                   /*        PLA               */
    /* $0827 */ 0xaa,                   /*        TAX               */
    /* $0828 */ 0x68,                   /*        PLA               */
    /* $0829 */ 0x60,                   /*        RTS               */
};

static void load(uint8_t *ram)
{
    memset(ram, 0, 65536);
    memcpy(&ram[0x0800], program, sizeof program);
    for (unsigned i = 0; i < 256; i++)
        ram[0x1000 + i] = (uint8_t)(i * 7);
    ram[0x40] = 0x00;
    ram[0x41] = 0x30;
    ram[0x42] = 0x00;
    ram[0x43] = 0x40;
    ram[0xfffc] = 0x00;
    ram[0xfffd] = 0x08;
}

/* ---- inline: the core built into this file ---- */

static uint8_t flat_ram[65536];

#define C02_PREFIX inline_
#define C02_LINKAGE static
#define C02_READ(cpu, address, kind) \
    ((void)(cpu), (void)(kind), flat_ram[address])
#define C02_WRITE(cpu, address, value, kind) \
    ((void)(cpu), (void)(kind), flat_ram[address] = (value))
#include "cpu65c02_core.h"

/* ---- callback: flat RAM through the function pointers ---- */

static uint8_t callback_ram[65536];

static uint8_t callback_read(void *context, uint16_t address,
                             cpu65c02_kind kind)
{
    (void)context;
    (void)kind;
    return callback_ram[address];
}

static void callback_write(void *context, uint16_t address, uint8_t value,
                           cpu65c02_kind kind)
{
    (void)context;
    (void)kind;
    callback_ram[address] = value;
}

/* ---- mapped: a page table, an I/O trap, counts by kind ---- */

typedef struct {
    uint8_t *read_page[256], *write_page[256];
    uint8_t ram[65536];
    uint64_t by_kind[4];
    uint64_t io;
} machine;

static uint8_t io_read(machine *m, uint16_t address)
{
    m->io++;
    return (uint8_t)address;
}

static uint8_t mapped_read(void *context, uint16_t address,
                           cpu65c02_kind kind)
{
    machine *m = context;
    uint8_t *page = m->read_page[address >> 8];
    m->by_kind[kind]++;
    return page ? page[address & 0xff] : io_read(m, address);
}

static void mapped_write(void *context, uint16_t address, uint8_t value,
                         cpu65c02_kind kind)
{
    machine *m = context;
    uint8_t *page = m->write_page[address >> 8];
    m->by_kind[kind]++;
    if (page)
        page[address & 0xff] = value;
    else
        m->io++;
}

/* ---- the runs ---- */

typedef struct {
    const char *name;
    uint64_t instructions, cycles;
    double seconds;
} result;

static result timed(const char *name, cpu65c02 *cpu, uint64_t cycles,
                    uint64_t (*run)(cpu65c02 *, uint64_t))
{
    result r;
    clock_t start = clock();
    r.name = name;
    r.instructions = run(cpu, cycles);
    r.seconds = (double)(clock() - start) / CLOCKS_PER_SEC;
    r.cycles = cpu->cycles;
    return r;
}

static void report(const result *r)
{
    printf("%-9s %12llu instructions %12llu cycles %7.3f s  %7.1f million "
           "instructions/s  %7.1f MHz\n", r->name,
           (unsigned long long)r->instructions,
           (unsigned long long)r->cycles, r->seconds,
           r->seconds > 0 ? r->instructions / r->seconds / 1e6 : 0.0,
           r->seconds > 0 ? r->cycles / r->seconds / 1e6 : 0.0);
}

static int same(const cpu65c02 *a, const cpu65c02 *b, const uint8_t *ram_a,
                const uint8_t *ram_b)
{
    return a->pc == b->pc && a->a == b->a && a->x == b->x && a->y == b->y &&
           a->s == b->s && a->p == b->p && a->cycles == b->cycles &&
           !memcmp(ram_a, ram_b, 65536);
}

int main(int argc, char **argv)
{
    uint64_t cycles = 1000;
    cpu65c02 inline_cpu, callback_cpu, mapped_cpu;
    static machine m;
    result results[3];
    int ok;

    if (argc > 1)
        cycles = strtoull(argv[1], NULL, 10);
    cycles *= 1000000;

    load(flat_ram);
    cpu65c02_init(&inline_cpu, NULL, NULL, NULL);
    inline_reset(&inline_cpu);
    (void)inline_step(&inline_cpu);
    results[0] = timed("inline", &inline_cpu, cycles, inline_run);

    load(callback_ram);
    cpu65c02_init(&callback_cpu, callback_read, callback_write, NULL);
    cpu65c02_reset(&callback_cpu);
    (void)cpu65c02_step(&callback_cpu);
    results[1] = timed("callback", &callback_cpu, cycles, cpu65c02_run);

    load(m.ram);
    for (unsigned page = 0; page < 256; page++) {
        int io = page >= 0xc0 && page < 0xd0;
        m.read_page[page] = io ? NULL : &m.ram[page << 8];
        m.write_page[page] = io ? NULL : &m.ram[page << 8];
    }
    cpu65c02_init(&mapped_cpu, mapped_read, mapped_write, &m);
    cpu65c02_reset(&mapped_cpu);
    (void)cpu65c02_step(&mapped_cpu);
    results[2] = timed("mapped", &mapped_cpu, cycles, cpu65c02_run);

    for (int i = 0; i < 3; i++)
        report(&results[i]);
    printf("mapped: %llu opcode, %llu operand, %llu data, %llu dummy "
           "cycles\n", (unsigned long long)m.by_kind[CPU65C02_OPCODE],
           (unsigned long long)m.by_kind[CPU65C02_OPERAND],
           (unsigned long long)m.by_kind[CPU65C02_DATA],
           (unsigned long long)m.by_kind[CPU65C02_DUMMY]);
    ok = same(&inline_cpu, &callback_cpu, flat_ram, callback_ram) &&
         same(&inline_cpu, &mapped_cpu, flat_ram, m.ram) &&
         m.by_kind[0] + m.by_kind[1] + m.by_kind[2] + m.by_kind[3] ==
         mapped_cpu.cycles &&
         results[0].instructions == results[1].instructions &&
         results[0].instructions == results[2].instructions;
    printf("bench: the three runs %s\n", ok ? "end in the same state"
                                             : "DIFFER");
    return ok ? 0 : 1;
}
