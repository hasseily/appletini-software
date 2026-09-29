/*
 * Tests of the parts of cpu65c02 that the SingleStepTests vectors do not
 * reach: reset, IRQ and NMI entry, BRK and RTI around them, WAI, STP,
 * the kind given to each bus cycle, cpu65c02_run and its early end,
 * the instruction lengths, the base cycle count of every opcode
 * against the datasheet, and decimal ADC and SBC for every input.
 *
 * usage: selftest     (prints each failed check; exit status 1 if any)
 */
#include "cpu65c02.h"

#include <stdio.h>
#include <string.h>

static uint8_t memory[1 << 16];
static int failures;

/* The bus log of the current test. */
typedef struct {
    uint16_t address;
    uint8_t value, write, kind;
} access;

static access bus_log[64];
static unsigned bus_count;
static uint64_t stop_at_write;      /* see test_run */

static void log_access(uint16_t address, uint8_t value, int write,
                       cpu65c02_kind kind)
{
    if (bus_count < sizeof bus_log / sizeof bus_log[0]) {
        bus_log[bus_count].address = address;
        bus_log[bus_count].value = value;
        bus_log[bus_count].write = (uint8_t)write;
        bus_log[bus_count].kind = (uint8_t)kind;
    }
    bus_count++;
}

static uint8_t bus_read(void *context, uint16_t address, cpu65c02_kind kind)
{
    (void)context;
    log_access(address, memory[address], 0, kind);
    return memory[address];
}

static void bus_write(void *context, uint16_t address, uint8_t value,
                      cpu65c02_kind kind)
{
    cpu65c02 *cpu = context;
    memory[address] = value;
    log_access(address, value, 1, kind);
    if (stop_at_write && address == stop_at_write)
        cpu->until = 0;
}

#define CHECK(test, condition) \
    do { \
        if (!(condition)) { \
            printf("%s: failed: %s (line %d)\n", test, #condition, __LINE__); \
            failures++; \
        } \
    } while (0)

enum { O = CPU65C02_OPCODE, P = CPU65C02_OPERAND, D = CPU65C02_DATA,
       X = CPU65C02_DUMMY };

/* True when the log is exactly the accesses listed: address, value,
   write flag and kind of each. */
static int log_is(const access *expected, unsigned count)
{
    if (bus_count != count)
        return 0;
    for (unsigned i = 0; i < count; i++)
        if (bus_log[i].address != expected[i].address ||
            bus_log[i].value != expected[i].value ||
            bus_log[i].write != expected[i].write ||
            bus_log[i].kind != expected[i].kind)
            return 0;
    return 1;
}

#define LOG_IS(...) \
    log_is((const access[]){ __VA_ARGS__ }, \
           sizeof((const access[]){ __VA_ARGS__ }) / sizeof(access))

static void poke16(uint16_t address, uint16_t value)
{
    memory[address] = (uint8_t)value;
    memory[(uint16_t)(address + 1)] = (uint8_t)(value >> 8);
}

/* A CPU at $1000 with S = $F0, I clear, D and C set, and memory cleared
   except for the vectors. */
static void start(cpu65c02 *cpu)
{
    memset(memory, 0, sizeof memory);
    poke16(0xfffa, 0x9000);     /* NMI */
    poke16(0xfffc, 0xa000);     /* RESET */
    poke16(0xfffe, 0xb000);     /* IRQ and BRK */
    cpu65c02_init(cpu, bus_read, bus_write, cpu);
    cpu->pc = 0x1000;
    cpu->s = 0xf0;
    cpu->p = CPU65C02_U | CPU65C02_D | CPU65C02_C;
    bus_count = 0;
    stop_at_write = 0;
}

static void test_reset(void)
{
    cpu65c02 cpu;
    start(&cpu);
    cpu.a = 0x12;
    cpu.state = CPU65C02_STOPPED;
    cpu65c02_reset(&cpu);
    CHECK("reset", cpu.cycles == 7 && cpu.pc == 0xa000 && cpu.s == 0xed);
    CHECK("reset", cpu.state == CPU65C02_RUNNING && cpu.a == 0x12);
    CHECK("reset", cpu.p == (CPU65C02_U | CPU65C02_I | CPU65C02_C));
    CHECK("reset", LOG_IS({0x1000, 0, 0, X}, {0x1000, 0, 0, X},
                          {0x01f0, 0, 0, X}, {0x01ef, 0, 0, X},
                          {0x01ee, 0, 0, X}, {0xfffc, 0x00, 0, D},
                          {0xfffd, 0xa0, 0, D}));
}

static void test_irq(void)
{
    cpu65c02 cpu;
    start(&cpu);
    memory[0x1000] = 0xea;              /* NOP, not executed yet */
    cpu65c02_set_irq(&cpu, 4, 1);
    CHECK("irq", cpu65c02_step(&cpu) == 7);
    CHECK("irq", cpu.pc == 0xb000 && cpu.s == 0xed);
    CHECK("irq", cpu.p == (CPU65C02_U | CPU65C02_I | CPU65C02_C));
    /* The pushed P has B clear and D as it was. */
    CHECK("irq", LOG_IS({0x1000, 0xea, 0, X}, {0x1000, 0xea, 0, X},
                        {0x01f0, 0x10, 1, D}, {0x01ef, 0x00, 1, D},
                        {0x01ee, 0x29, 1, D}, {0xfffe, 0x00, 0, D},
                        {0xffff, 0xb0, 0, D}));
    /* Masked now: the handler's RTI runs, and restores P and PC; the
       line is still active and I is clear again, so the IRQ is taken
       at once. */
    memory[0xb000] = 0x40;
    CHECK("irq", cpu65c02_step(&cpu) == 6 && cpu.pc == 0x1000);
    CHECK("irq", cpu.p == (CPU65C02_U | CPU65C02_D | CPU65C02_C));
    CHECK("irq", cpu65c02_step(&cpu) == 7 && cpu.pc == 0xb000);
    cpu65c02_set_irq(&cpu, 4, 0);
    CHECK("irq", cpu65c02_step(&cpu) == 6 && cpu.pc == 0x1000);
    CHECK("irq", cpu65c02_step(&cpu) == 2 && cpu.pc == 0x1001);
}

static void test_irq_masked(void)
{
    cpu65c02 cpu;
    start(&cpu);
    cpu.p |= CPU65C02_I;
    memory[0x1000] = 0x58;              /* CLI */
    memory[0x1001] = 0xea;
    cpu65c02_set_irq(&cpu, 1, 1);
    CHECK("irq masked", cpu65c02_step(&cpu) == 2 && cpu.pc == 0x1001);
    /* The Appletini core samples the line at each opcode fetch with the
       flags the previous instruction left: the IRQ is taken right after
       CLI. */
    CHECK("irq masked", cpu65c02_step(&cpu) == 7 && cpu.pc == 0xb000);
    CHECK("irq masked", memory[0x01f0] == 0x10 && memory[0x01ef] == 0x01);
}

static void test_nmi(void)
{
    cpu65c02 cpu;
    start(&cpu);
    cpu.p |= CPU65C02_I;
    cpu65c02_set_irq(&cpu, 1, 1);
    cpu65c02_nmi(&cpu);
    CHECK("nmi", cpu65c02_step(&cpu) == 7 && cpu.pc == 0x9000);
    CHECK("nmi", !cpu.nmi_pending && !(cpu.p & CPU65C02_D));
    /* One edge, one interrupt; the IRQ stays masked. */
    memory[0x9000] = 0xea;
    CHECK("nmi", cpu65c02_step(&cpu) == 2 && cpu.pc == 0x9001);
    /* NMI wins over an unmasked IRQ. */
    start(&cpu);
    cpu65c02_set_irq(&cpu, 1, 1);
    cpu65c02_nmi(&cpu);
    CHECK("nmi", cpu65c02_step(&cpu) == 7 && cpu.pc == 0x9000);
    /* The IRQ comes next, once I is clear again. */
    memory[0x9000] = 0x40;              /* RTI */
    CHECK("nmi", cpu65c02_step(&cpu) == 6 && cpu.pc == 0x1000);
    CHECK("nmi", cpu65c02_step(&cpu) == 7 && cpu.pc == 0xb000);
}

static void test_brk(void)
{
    cpu65c02 cpu;
    start(&cpu);
    memory[0x1000] = 0x00;
    memory[0x1001] = 0x77;              /* signature */
    CHECK("brk", cpu65c02_step(&cpu) == 7 && cpu.pc == 0xb000);
    CHECK("brk", cpu.p == (CPU65C02_U | CPU65C02_I | CPU65C02_C));
    CHECK("brk", LOG_IS({0x1000, 0x00, 0, O}, {0x1001, 0x77, 0, P},
                        {0x01f0, 0x10, 1, D}, {0x01ef, 0x02, 1, D},
                        {0x01ee, 0x39, 1, D}, {0xfffe, 0x00, 0, D},
                        {0xffff, 0xb0, 0, D}));
    memory[0xb000] = 0x40;
    CHECK("brk", cpu65c02_step(&cpu) == 6 && cpu.pc == 0x1002);
    /* PLP and RTI never leave B set in the register. */
    CHECK("brk", cpu.p == (CPU65C02_U | CPU65C02_D | CPU65C02_C));
}

static void test_wai(void)
{
    cpu65c02 cpu;
    start(&cpu);
    memory[0x1000] = 0xcb;              /* WAI */
    memory[0x1001] = 0xea;
    CHECK("wai", cpu65c02_step(&cpu) == 2);
    CHECK("wai", cpu.state == CPU65C02_WAITING && cpu.pc == 0x1001);
    CHECK("wai", LOG_IS({0x1000, 0xcb, 0, O}, {0x1001, 0xea, 0, X}));
    for (int i = 0; i < 5; i++)
        CHECK("wai", cpu65c02_step(&cpu) == 1 && cpu.pc == 0x1001);
    CHECK("wai", cpu.cycles == 7);
    /* An IRQ with I clear: the waiting cycle that sees it, then the
       six cycles of the entry. */
    cpu65c02_set_irq(&cpu, 2, 1);
    CHECK("wai", cpu65c02_step(&cpu) == 7 && cpu.pc == 0xb000);
    CHECK("wai", cpu.state == CPU65C02_RUNNING);
    CHECK("wai", memory[0x01f0] == 0x10 && memory[0x01ef] == 0x01);

    /* With I set the IRQ ends the wait and is not taken. */
    start(&cpu);
    cpu.p |= CPU65C02_I;
    memory[0x1000] = 0xcb;
    memory[0x1001] = 0xea;
    CHECK("wai masked", cpu65c02_step(&cpu) == 2);
    cpu65c02_set_irq(&cpu, 2, 1);
    CHECK("wai masked", cpu65c02_step(&cpu) == 1);
    CHECK("wai masked", cpu.state == CPU65C02_RUNNING && cpu.pc == 0x1001);
    CHECK("wai masked", cpu65c02_step(&cpu) == 2 && cpu.pc == 0x1002);

    /* NMI ends it too, even with I set. */
    start(&cpu);
    cpu.p |= CPU65C02_I;
    memory[0x1000] = 0xcb;
    CHECK("wai nmi", cpu65c02_step(&cpu) == 2);
    cpu65c02_nmi(&cpu);
    CHECK("wai nmi", cpu65c02_step(&cpu) == 7 && cpu.pc == 0x9000);
}

static void test_stp(void)
{
    cpu65c02 cpu;
    start(&cpu);
    memory[0x1000] = 0xdb;              /* STP */
    CHECK("stp", cpu65c02_step(&cpu) == 2 && cpu.state == CPU65C02_STOPPED);
    cpu65c02_set_irq(&cpu, 1, 1);
    cpu65c02_nmi(&cpu);
    for (int i = 0; i < 4; i++)
        CHECK("stp", cpu65c02_step(&cpu) == 1 && cpu.pc == 0x1001);
    cpu65c02_reset(&cpu);
    CHECK("stp", cpu.state == CPU65C02_RUNNING && cpu.pc == 0xa000);
    /* Reset forgets the NMI edge; the IRQ line is still active, but
       reset set I. */
    CHECK("stp", !cpu.nmi_pending && (cpu.p & CPU65C02_I));
}

static void test_kinds(void)
{
    cpu65c02 cpu;
    /* LDA a,X across a page: opcode, two operands, the dummy read of
       the last instruction byte, then the data. */
    start(&cpu);
    cpu.x = 0x20;
    memcpy(&memory[0x1000], "\xbd\xf0\x20", 3);
    memory[0x2110] = 0x5a;
    CHECK("kinds", cpu65c02_step(&cpu) == 5 && cpu.a == 0x5a);
    CHECK("kinds", LOG_IS({0x1000, 0xbd, 0, O}, {0x1001, 0xf0, 0, P},
                          {0x1002, 0x20, 0, P}, {0x1002, 0x20, 0, X},
                          {0x2110, 0x5a, 0, D}));
    /* INC zp: read, read again, write. */
    start(&cpu);
    memcpy(&memory[0x1000], "\xe6\x80", 2);
    memory[0x80] = 0x41;
    CHECK("kinds", cpu65c02_step(&cpu) == 5 && memory[0x80] == 0x42);
    CHECK("kinds", LOG_IS({0x1000, 0xe6, 0, O}, {0x1001, 0x80, 0, P},
                          {0x0080, 0x41, 0, D}, {0x0080, 0x41, 0, X},
                          {0x0080, 0x42, 1, D}));
    /* JSR: the high byte of the target is an operand read last. */
    start(&cpu);
    memcpy(&memory[0x1000], "\x20\x34\x12", 3);
    CHECK("kinds", cpu65c02_step(&cpu) == 6 && cpu.pc == 0x1234);
    CHECK("kinds", LOG_IS({0x1000, 0x20, 0, O}, {0x1001, 0x34, 0, P},
                          {0x01f0, 0x00, 0, X}, {0x01f0, 0x10, 1, D},
                          {0x01ef, 0x02, 1, D}, {0x1002, 0x12, 0, P}));
    /* STA a,X on the same page reads its target first. */
    start(&cpu);
    cpu.x = 0x01;
    cpu.a = 0x99;
    memcpy(&memory[0x1000], "\x9d\x10\x20", 3);
    CHECK("kinds", cpu65c02_step(&cpu) == 5 && memory[0x2011] == 0x99);
    CHECK("kinds", LOG_IS({0x1000, 0x9d, 0, O}, {0x1001, 0x10, 0, P},
                          {0x1002, 0x20, 0, P}, {0x2011, 0x00, 0, X},
                          {0x2011, 0x99, 1, D}));
    /* Decimal ADC: the extra cycle reads the operand again. */
    start(&cpu);
    cpu.a = 0x99;
    cpu.p = CPU65C02_U | CPU65C02_D;
    memcpy(&memory[0x1000], "\x65\x10", 2);
    memory[0x10] = 0x01;
    CHECK("kinds", cpu65c02_step(&cpu) == 4 && cpu.a == 0x00);
    CHECK("kinds", cpu.p == (CPU65C02_U | CPU65C02_D | CPU65C02_Z |
                             CPU65C02_C));
    CHECK("kinds", LOG_IS({0x1000, 0x65, 0, O}, {0x1001, 0x10, 0, P},
                          {0x0010, 0x01, 0, D}, {0x0010, 0x01, 0, X}));
}

/* cpu65c02_run stops at the limit, and a callback that lowers `until`
   ends it after the current instruction. */
static void test_run(void)
{
    cpu65c02 cpu;
    uint64_t count;
    start(&cpu);
    /* loop: INC $80 ; STA $4000 ; JMP loop */
    memcpy(&memory[0x1000], "\xe6\x80\x8d\x00\x40\x4c\x00\x10", 8);
    count = cpu65c02_run(&cpu, 1000);
    CHECK("run", cpu.cycles >= 1000 && cpu.cycles < 1005);
    /* 12 cycles a pass: 83 passes and part of the 84th. */
    CHECK("run", memory[0x80] == 84 && count == 250);
    stop_at_write = 0x4000;
    count = cpu65c02_run(&cpu, 1000000);
    CHECK("run", count == 1 && cpu.pc == 0x1005 && cpu.until == 0);
}

/* Every instruction but those that change PC otherwise advances PC by
   its length. */
static void test_lengths(void)
{
    cpu65c02 cpu;
    for (int opcode = 0; opcode < 256; opcode++) {
        switch (opcode) {
        case 0x00: case 0x20: case 0x40: case 0x4c: case 0x60: case 0x6c:
        case 0x7c: case 0x80:
            continue;
        }
        start(&cpu);
        cpu.p = CPU65C02_U | CPU65C02_I;
        memory[0x1000] = (uint8_t)opcode;
        /* Operands of 0: branches with an offset of 0 land on the next
           instruction whether taken or not. */
        cpu65c02_step(&cpu);
        if (cpu.pc != 0x1000 + cpu65c02_length[opcode]) {
            printf("lengths: opcode %02x advanced PC by %d, table says %d\n",
                   opcode, cpu.pc - 0x1000, cpu65c02_length[opcode]);
            failures++;
        }
    }
}

/* Base cycles of every opcode from the WDC W65C02S datasheet (tables 4-1,
   6-4 and 7-1): no page crossing, branch not taken, binary mode. WAI and
   STP count their first waiting cycle, as the datasheet's 3 does. */
static const uint8_t datasheet_cycles[256] = {
/*        0  1  2  3  4  5  6  7  8  9  A  B  C  D  E  F */
/* 0 */   7, 6, 2, 1, 5, 3, 5, 5, 3, 2, 2, 1, 6, 4, 6, 5,
/* 1 */   2, 5, 5, 1, 5, 4, 6, 5, 2, 4, 2, 1, 6, 4, 6, 5,
/* 2 */   6, 6, 2, 1, 3, 3, 5, 5, 4, 2, 2, 1, 4, 4, 6, 5,
/* 3 */   2, 5, 5, 1, 4, 4, 6, 5, 2, 4, 2, 1, 4, 4, 6, 5,
/* 4 */   6, 6, 2, 1, 3, 3, 5, 5, 3, 2, 2, 1, 3, 4, 6, 5,
/* 5 */   2, 5, 5, 1, 4, 4, 6, 5, 2, 4, 3, 1, 8, 4, 6, 5,
/* 6 */   6, 6, 2, 1, 3, 3, 5, 5, 4, 2, 2, 1, 6, 4, 6, 5,
/* 7 */   2, 5, 5, 1, 4, 4, 6, 5, 2, 4, 4, 1, 6, 4, 6, 5,
/* 8 */   3, 6, 2, 1, 3, 3, 3, 5, 2, 2, 2, 1, 4, 4, 4, 5,
/* 9 */   2, 6, 5, 1, 4, 4, 4, 5, 2, 5, 2, 1, 4, 5, 5, 5,
/* A */   2, 6, 2, 1, 3, 3, 3, 5, 2, 2, 2, 1, 4, 4, 4, 5,
/* B */   2, 5, 5, 1, 4, 4, 4, 5, 2, 4, 2, 1, 4, 4, 4, 5,
/* C */   2, 6, 2, 1, 3, 3, 5, 5, 2, 2, 2, 3, 4, 4, 6, 5,
/* D */   2, 5, 5, 1, 4, 4, 6, 5, 2, 4, 3, 3, 4, 4, 7, 5,
/* E */   2, 6, 2, 1, 3, 3, 5, 5, 2, 2, 2, 1, 4, 4, 6, 5,
/* F */   2, 5, 5, 1, 4, 4, 6, 5, 2, 4, 4, 1, 4, 4, 7, 5,
};

/* The fewest cycles the core takes for `opcode` over a few settings of
   the flags and of memory, so that one of them leaves each branch not
   taken; X = Y = 0, so no index crosses a page, and D is clear. */
static unsigned base_cycles(int opcode)
{
    static const uint8_t flags[] = { CPU65C02_U | CPU65C02_I,
                                     0xff & ~CPU65C02_D & ~CPU65C02_B };
    static const uint8_t fills[] = { 0x00, 0xff };
    unsigned best = 99;
    for (unsigned f = 0; f < 2; f++)
        for (unsigned m = 0; m < 2; m++) {
            cpu65c02 cpu;
            unsigned cycles;
            start(&cpu);
            memset(memory, fills[m], sizeof memory);
            cpu.p = flags[f];
            cpu.pc = 0x1000;
            memory[0x1000] = (uint8_t)opcode;
            memory[0x1001] = 0x10;
            memory[0x1002] = 0x20;
            cycles = cpu65c02_step(&cpu);
            if (cpu.state != CPU65C02_RUNNING)
                cycles += cpu65c02_step(&cpu);
            if (cycles < best)
                best = cycles;
        }
    return best;
}

/* The one opcode where the core and the datasheet differ is $5C: the
   datasheet says 8 cycles, the Appletini core and the SingleStepTests
   set take 4 (tools/a2vm/README.md). Any other difference fails. */
static void test_cycles(void)
{
    for (int opcode = 0; opcode < 256; opcode++) {
        unsigned have = base_cycles(opcode);
        if (have == datasheet_cycles[opcode])
            continue;
        if (opcode == 0x5c && have == 4) {
            printf("cycles: opcode 5c takes 4 cycles, as the Appletini "
                   "core and the vector set do; the datasheet says 8\n");
            continue;
        }
        printf("cycles: opcode %02x takes %u cycles, the datasheet says %u\n",
               opcode, have, datasheet_cycles[opcode]);
        failures++;
    }
}

/* Decimal ADC and SBC for every accumulator, operand and carry, against
   a second formulation: the one of the Appletini core's adc_result and
   sbc_result (hdl/apple/w65c02_core.sv), which digit-corrects instead of
   following Clark's sequences and which passed Klaus Dormann's
   exhaustive CMOS decimal test, invalid BCD included
   (README_W65C02_CORE.md). The vectors cover only random samples. */
static uint16_t reference_adc(unsigned a, unsigned m, unsigned c)
{
    unsigned low = (a & 15) + (m & 15) + c, high, carry, overflow, result;
    unsigned low_carry = low > 9;
    if (low_carry)
        low += 6;
    high = (a >> 4) + (m >> 4) + low_carry;
    overflow = !((a ^ m) & 0x80) && ((a ^ (high << 4)) & 0x80);
    carry = high > 9;
    if (carry)
        high += 6;
    result = (high & 15) << 4 | (low & 15);
    return (uint16_t)(result | carry << 8 | overflow << 9);
}

static uint16_t reference_sbc(unsigned a, unsigned m, unsigned c)
{
    int binary = (int)a - (int)m - (int)!c;
    int low = (int)(a & 15) - (int)(m & 15) - (int)!c;
    int stage;
    unsigned result, overflow;
    if (low < 0)
        stage = (int)((a & 0xf0) | (low & 15)) - (int)((m & 0xf0) | 15) - 1;
    else
        stage = (int)((a & 0xf0) | (low & 15)) - (int)(m & 0xf0);
    result = (unsigned)stage & 0xff;
    if (stage < 0)
        result = (result - 0x60) & 0xff;
    if (low < 0)
        result = (result - 0x06) & 0xff;
    overflow = ((a ^ m) & (a ^ (unsigned)binary) & 0x80) != 0;
    return (uint16_t)(result | (binary >= 0) << 8 | overflow << 9);
}

static void test_decimal(void)
{
    cpu65c02 cpu;
    unsigned wrong = 0;
    start(&cpu);
    for (unsigned op = 0; op < 2; op++)
        for (unsigned a = 0; a < 256; a++)
            for (unsigned m = 0; m < 256; m++)
                for (unsigned c = 0; c < 2; c++) {
                    uint16_t want = op ? reference_sbc(a, m, c)
                                       : reference_adc(a, m, c);
                    uint8_t result = (uint8_t)want, p;
                    cpu.pc = 0x1000;
                    memory[0x1000] = op ? 0xe9 : 0x69;
                    memory[0x1001] = (uint8_t)m;
                    cpu.a = (uint8_t)a;
                    cpu.p = (uint8_t)(CPU65C02_U | CPU65C02_D | c);
                    p = (uint8_t)(CPU65C02_U | CPU65C02_D |
                                  (want >> 8 & 1) |
                                  (want & 0x200 ? CPU65C02_V : 0) |
                                  (result & 0x80) |
                                  (result ? 0 : CPU65C02_Z));
                    bus_count = 0;
                    if (cpu65c02_step(&cpu) != 3 || cpu.a != result ||
                        cpu.p != p) {
                        if (wrong++ < 5)
                            printf("decimal: %s %02x %02x C=%u gives A=%02x "
                                   "P=%02x, expected A=%02x P=%02x\n",
                                   op ? "SBC" : "ADC", a, m, c, cpu.a,
                                   cpu.p, result, p);
                    }
                }
    CHECK("decimal", wrong == 0);
}

int main(void)
{
    test_reset();
    test_irq();
    test_irq_masked();
    test_nmi();
    test_brk();
    test_wai();
    test_stp();
    test_kinds();
    test_run();
    test_lengths();
    test_cycles();
    test_decimal();
    if (failures)
        printf("%d checks failed\n", failures);
    else
        printf("selftest: all checks passed\n");
    return failures ? 1 : 0;
}
