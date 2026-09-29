/*
 * Tests of the parts of cpu816 that the SingleStepTests vectors do not
 * reach: reset, IRQ and NMI entry, WAI, STP, and an interrupt between
 * the byte moves of MVN, and direct page pointers at the end of the page
 * in emulation mode.
 *
 * usage: selftest     (prints each failed check; exit status 1 if any)
 */
#include "cpu816.h"

#include <stdio.h>
#include <string.h>

static uint8_t memory[1 << 24];
static int failures;

static uint8_t bus_read(void *context, uint32_t address)
{
    (void)context;
    return memory[address];
}

static void bus_write(void *context, uint32_t address, uint8_t value)
{
    (void)context;
    memory[address] = value;
}

#define CHECK(test, condition) \
    do { \
        if (!(condition)) { \
            printf("%s: failed: %s (line %d)\n", test, #condition, __LINE__); \
            failures++; \
        } \
    } while (0)

static void poke16(uint32_t address, uint16_t value)
{
    memory[address] = (uint8_t)value;
    memory[address + 1] = (uint8_t)(value >> 8);
}

/* A CPU in native mode at $12:3456 with S = $1FF0, I clear, 16-bit
   registers, and memory cleared except for the vectors. */
static void native(cpu816 *cpu)
{
    memset(memory, 0, sizeof memory);
    poke16(0xffea, 0x9000);     /* NMI */
    poke16(0xffee, 0x9100);     /* IRQ */
    poke16(0xfffa, 0xa000);     /* emulation NMI */
    poke16(0xfffc, 0xa100);     /* RESET */
    poke16(0xfffe, 0xa200);     /* emulation IRQ and BRK */
    cpu816_init(cpu, bus_read, bus_write, NULL);
    cpu->e = 0;
    cpu->p = CPU816_D | CPU816_C;
    cpu->pbr = 0x12;
    cpu->pc = 0x3456;
    cpu->s = 0x1ff0;
    cpu816_normalise(cpu);
}

static void test_reset(void)
{
    cpu816 cpu;
    native(&cpu);
    cpu.d = 0x1234;
    cpu.dbr = 0x56;
    CHECK("reset", (cpu816_reset(&cpu), cpu.cycles == 7));
    CHECK("reset", cpu.e == 1 && cpu.pbr == 0 && cpu.pc == 0xa100);
    CHECK("reset", cpu.d == 0 && cpu.dbr == 0 && (cpu.s >> 8) == 1);
    CHECK("reset", (cpu.p & (CPU816_I | CPU816_D | CPU816_M | CPU816_X)) ==
                   (CPU816_I | CPU816_M | CPU816_X));
}

static void test_native_irq(void)
{
    cpu816 cpu;
    native(&cpu);
    memory[0x123456] = 0xea;                    /* NOP, not executed */
    cpu816_set_irq(&cpu, 4, 1);
    CHECK("native IRQ", cpu816_step(&cpu) == 8);
    CHECK("native IRQ", cpu.pbr == 0 && cpu.pc == 0x9100);
    CHECK("native IRQ", cpu.s == 0x1fec);
    CHECK("native IRQ", memory[0x1ff0] == 0x12 && memory[0x1fef] == 0x34 &&
                        memory[0x1fee] == 0x56 &&
                        memory[0x1fed] == (CPU816_D | CPU816_C));
    CHECK("native IRQ", (cpu.p & (CPU816_I | CPU816_D)) == CPU816_I);
    /* The line is a level: I now masks it, and the NOP at the vector
       runs. */
    memory[0x009100] = 0xea;
    CHECK("native IRQ", cpu816_step(&cpu) == 2 && cpu.pc == 0x9101);
    /* Released by its source, it stays released when I is cleared. */
    cpu816_set_irq(&cpu, 4, 0);
    cpu.p &= (uint8_t)~CPU816_I;
    memory[0x009101] = 0xea;
    CHECK("native IRQ", cpu816_step(&cpu) == 2 && cpu.pc == 0x9102);
}

static void test_emulation_irq(void)
{
    cpu816 cpu;
    native(&cpu);
    cpu.e = 1;
    cpu.s = 0x01f0;
    cpu.p = CPU816_C;
    cpu816_normalise(&cpu);
    cpu816_set_irq(&cpu, 1, 1);
    CHECK("emulation IRQ", cpu816_step(&cpu) == 7);
    CHECK("emulation IRQ", cpu.pbr == 0 && cpu.pc == 0xa200);
    CHECK("emulation IRQ", cpu.s == 0x01ed);
    CHECK("emulation IRQ", memory[0x01f0] == 0x34 && memory[0x01ef] == 0x56);
    /* The break bit is clear in the pushed P of a hardware interrupt. */
    CHECK("emulation IRQ",
          memory[0x01ee] == (CPU816_M | CPU816_C));
}

static void test_irq_masked(void)
{
    cpu816 cpu;
    native(&cpu);
    cpu.p |= CPU816_I;
    memory[0x123456] = 0xea;
    cpu816_set_irq(&cpu, 1, 1);
    CHECK("masked IRQ", cpu816_step(&cpu) == 2 && cpu.pc == 0x3457);
}

static void test_nmi(void)
{
    cpu816 cpu;
    native(&cpu);
    cpu.p |= CPU816_I;
    memory[0x009000] = 0xea;
    cpu816_nmi(&cpu);
    CHECK("NMI", cpu816_step(&cpu) == 8 && cpu.pc == 0x9000);
    /* An edge is taken once. */
    CHECK("NMI", cpu816_step(&cpu) == 2 && cpu.pc == 0x9001);
}

static void test_wai(void)
{
    cpu816 cpu;
    native(&cpu);
    memory[0x123456] = 0xcb;                    /* WAI */
    memory[0x123457] = 0xea;
    CHECK("WAI", cpu816_step(&cpu) == 3 && cpu.state == CPU816_WAITING);
    CHECK("WAI", cpu816_step(&cpu) == 1 && cpu.pc == 0x3457);
    cpu816_set_irq(&cpu, 2, 1);
    CHECK("WAI", cpu816_step(&cpu) == 8 && cpu.pc == 0x9100);
    /* The pushed return address is the instruction after the WAI. */
    CHECK("WAI", memory[0x1fef] == 0x34 && memory[0x1fee] == 0x57);

    /* With I set the WAI ends and execution goes on after it. */
    native(&cpu);
    cpu.p |= CPU816_I;
    memory[0x123456] = 0xcb;
    memory[0x123457] = 0xea;
    cpu816_step(&cpu);
    cpu816_set_irq(&cpu, 2, 1);
    CHECK("WAI", cpu816_step(&cpu) == 2 && cpu.pc == 0x3458);
    CHECK("WAI", cpu.state == CPU816_RUNNING);
}

static void test_stp(void)
{
    cpu816 cpu;
    native(&cpu);
    memory[0x123456] = 0xdb;                    /* STP */
    CHECK("STP", cpu816_step(&cpu) == 3 && cpu.state == CPU816_STOPPED);
    cpu816_set_irq(&cpu, 1, 1);
    cpu816_nmi(&cpu);
    CHECK("STP", cpu816_step(&cpu) == 1 && cpu.pc == 0x3457);
    cpu816_reset(&cpu);
    CHECK("STP", cpu.state == CPU816_RUNNING && cpu.pc == 0xa100);
}

/* An IRQ taken between two byte moves returns to the MVN, which goes on
   with the next byte. */
static void test_mvn_interrupted(void)
{
    cpu816 cpu;
    native(&cpu);
    memory[0x123456] = 0x54;                    /* MVN $07,$05 */
    memory[0x123457] = 0x07;
    memory[0x123458] = 0x05;
    memory[0x009100] = 0x40;                    /* RTI */
    memcpy(&memory[0x051000], "abc", 3);
    cpu.a = 2;
    cpu.x = 0x1000;
    cpu.y = 0x2000;
    CHECK("MVN", cpu816_step(&cpu) == 7 && cpu.pc == 0x3456);
    CHECK("MVN", memory[0x072000] == 'a' && cpu.a == 1 && cpu.dbr == 7);
    cpu816_set_irq(&cpu, 1, 1);
    CHECK("MVN", cpu816_step(&cpu) == 8 && cpu.pc == 0x9100);
    CHECK("MVN", memory[0x1fef] == 0x34 && memory[0x1fee] == 0x56);
    cpu816_set_irq(&cpu, 1, 0);
    CHECK("MVN", cpu816_step(&cpu) == 7 && cpu.pbr == 0x12 &&
                 cpu.pc == 0x3456);
    cpu816_step(&cpu);
    cpu816_step(&cpu);
    CHECK("MVN", !memcmp(&memory[0x072000], "abc", 3));
    CHECK("MVN", cpu.a == 0xffff && cpu.pc == 0x3459 && cpu.x == 0x1003 &&
                 cpu.y == 0x2003);
}

/* In emulation mode with DL = 0 the pointers of the 6502's addressing
   modes wrap in the direct page; [d], new on the 65816, does not. The
   vectors have no such case that is right (see known_issues in
   vectors.c). */
static void test_emulation_direct_wrap(void)
{
    static const uint8_t code[] = {
        0xb2, 0xff,         /* LDA ($FF) */
        0xa1, 0xfe,         /* LDA ($FE,X) with X = 1 */
        0xa7, 0xff,         /* LDA [$FF] */
    };
    cpu816 cpu;
    native(&cpu);
    cpu.e = 1;
    cpu.pbr = 0;
    cpu.pc = 0x1000;
    cpu.d = 0x2300;
    cpu.dbr = 0x04;
    cpu.x = 1;
    cpu816_normalise(&cpu);
    memcpy(&memory[0x1000], code, sizeof code);
    memory[0x23ff] = 0x34;
    memory[0x2300] = 0x12;      /* high byte, wrapped */
    memory[0x2400] = 0x56;      /* high byte, not wrapped */
    memory[0x2401] = 0x07;      /* bank of the long pointer */
    memory[0x041234] = 0xaa;
    memory[0x045634] = 0xbb;
    memory[0x075634] = 0xcc;
    CHECK("direct wrap", cpu816_step(&cpu) == 5 && (cpu.a & 0xff) == 0xaa);
    CHECK("direct wrap", cpu816_step(&cpu) == 6 && (cpu.a & 0xff) == 0xaa);
    CHECK("direct wrap", cpu816_step(&cpu) == 6 && (cpu.a & 0xff) == 0xcc);
}

int main(void)
{
    test_reset();
    test_native_irq();
    test_emulation_irq();
    test_irq_masked();
    test_nmi();
    test_wai();
    test_stp();
    test_mvn_interrupted();
    test_emulation_direct_wrap();
    if (failures)
        printf("%d checks failed\n", failures);
    else
        printf("selftest: all checks passed\n");
    return failures ? 1 : 0;
}
