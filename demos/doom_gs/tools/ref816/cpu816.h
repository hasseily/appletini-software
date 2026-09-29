/*
 * A 65816 core for the reference machine of the DOOM GS port.
 *
 * The core executes whole instructions but makes the bus accesses of the
 * W65C816S one cycle at a time, in the order and with the addresses of
 * the manufacturer's cycle table, so that a machine with side effects on
 * reads sees what the chip would do. Only cycles with VDA or VPA high
 * reach the callbacks; the chip's internal cycles, with both low, access
 * nothing. Every cycle, internal ones included, adds one to `cycles`.
 *
 * The machine supplies two bus callbacks. During a callback, `bus` holds
 * the pins of that cycle (CPU816_VDA and so on), which a machine or a
 * trace can use to tell opcode fetches from data accesses, and `space`
 * what kind of address it is (cpu816_space).
 *
 * The core is deterministic: it has no state beyond this structure and
 * reads nothing but the bus.
 */
#ifndef CPU816_H
#define CPU816_H

#include <stdint.h>

/* Status register bits. In emulation mode bit 4 is the break flag, and
   the register itself always holds 1 there and in bit 5. */
enum {
    CPU816_C = 0x01, CPU816_Z = 0x02, CPU816_I = 0x04, CPU816_D = 0x08,
    CPU816_X = 0x10, CPU816_M = 0x20, CPU816_V = 0x40, CPU816_N = 0x80
};

/* Pins of the current bus cycle. VDA marks a data access, VPA a program
   fetch (both for an opcode), VPB a vector fetch, MLB the cycles of a
   read-modify-write. */
enum {
    CPU816_VDA = 0x01, CPU816_VPA = 0x02, CPU816_VPB = 0x04,
    CPU816_MLB = 0x08
};

/* What the address of the current bus cycle is made from, for a trace:
   the program counter (opcodes and operands), the direct page, the
   stack (pushes, pulls and stack-relative operands), data (through DBR,
   a long address, a pointer, MVN or MVP) or a vector. The chip has no
   such pins; the core knows it from the addressing mode. */
typedef enum {
    CPU816_PROGRAM, CPU816_DIRECT, CPU816_STACK, CPU816_DATA, CPU816_VECTOR
} cpu816_space;

typedef enum {
    CPU816_RUNNING,
    CPU816_WAITING,     /* after WAI, until an interrupt line is active */
    CPU816_STOPPED      /* after STP, until reset */
} cpu816_state;

typedef uint8_t (*cpu816_read_fn)(void *context, uint32_t address);
typedef void (*cpu816_write_fn)(void *context, uint32_t address,
                                uint8_t value);

typedef struct cpu816 {
    /* Registers. A and the index registers keep 16 bits; with the index
       flag set the high bytes of X and Y are zero, as on the chip. */
    uint16_t a, x, y, s, d, pc;
    uint8_t p, dbr, pbr;
    uint8_t e;                  /* 1 in emulation mode */

    cpu816_state state;
    uint64_t cycles;            /* every cycle since cpu816_init */
    uint8_t bus;                /* pins of the cycle in progress */
    uint8_t space;              /* its cpu816_space */

    uint32_t irq_sources;       /* level: one bit per source, set = active */
    uint8_t nmi_pending;        /* edge seen and not yet taken */

    cpu816_read_fn read;
    cpu816_write_fn write;
    void *context;
} cpu816;

/* Clear the structure and connect the bus. The state is not that of a
   reset; call cpu816_reset or set the registers. */
void cpu816_init(cpu816 *cpu, cpu816_read_fn read, cpu816_write_fn write,
                 void *context);

/* The RESET sequence: emulation mode, D = 0, DBR = PBR = 0, I set, D
   flag clear, S in page 1, PC from $00FFFC. Takes 7 cycles. */
void cpu816_reset(cpu816 *cpu);

/* Execute one instruction, or take a pending interrupt, or, while
   waiting or stopped, let one cycle pass. Returns the cycles used. */
unsigned cpu816_step(cpu816 *cpu);

/* Assert or release interrupt source bits on the level-sensitive IRQ
   line. The line is active while any bit is set. */
void cpu816_set_irq(cpu816 *cpu, uint32_t sources, int active);

/* A falling edge on NMI. */
void cpu816_nmi(cpu816 *cpu);

/* Make the registers consistent with E and the index flag after a
   machine or a test has written them directly: in emulation mode S is
   in page 1 and M and X are set; with X set the index high bytes are
   zero. */
void cpu816_normalise(cpu816 *cpu);

#endif
