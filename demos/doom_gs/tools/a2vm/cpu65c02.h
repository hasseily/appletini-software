/*
 * A W65C02S core for a2vm, the model of the Appletini target of the DOOM
 * GS port.
 *
 * The core executes whole instructions but makes every bus cycle of the
 * chip, one at a time, in the order and with the addresses of the chip:
 * on the 65C02 every cycle is a read or a write, the internal ones
 * included, so every cycle reaches a callback. Each call carries the kind
 * of the cycle (cpu65c02_kind), which a machine uses to class its cost,
 * and adds one to `cycles` before the callback runs.
 *
 * What it follows, in order of authority:
 *   1. the Appletini's own W65C02S core (hdl/apple/w65c02_core.sv in
 *      hasseily/appletini-one), the chip this models, which passes the
 *      SingleStepTests WDC 65C02 set cycle for cycle;
 *   2. the WDC W65C02S datasheet (tables 4-1, 5-2, 6-4 and 7-1);
 *   3. the SingleStepTests set itself.
 * Where they disagree, tools/a2vm/README.md says so and why; the vector
 * harness lists each such case with its evidence.
 *
 * Two builds of the same code (cpu65c02_core.h):
 *   - cpu65c02.c connects the bus through the `read` and `write`
 *     function pointers below;
 *   - a machine that needs more speed includes cpu65c02_core.h itself
 *     with its own bus macros, so its accesses are inlined (the header
 *     says how).
 *
 * The core is deterministic: it has no state beyond this structure and
 * reads nothing but the bus.
 */
#ifndef CPU65C02_H
#define CPU65C02_H

#include <stdint.h>

/* Status register bits. Bit 5 always reads 1 and bit 4 (B) always 0 in
   the register; B exists only in the copy BRK and PHP push. */
enum {
    CPU65C02_C = 0x01, CPU65C02_Z = 0x02, CPU65C02_I = 0x04,
    CPU65C02_D = 0x08, CPU65C02_B = 0x10, CPU65C02_U = 0x20,
    CPU65C02_V = 0x40, CPU65C02_N = 0x80
};

/* What a bus cycle is for.
 *   OPCODE   the fetch of an opcode (SYNC high on the chip)
 *   OPERAND  a later byte of the instruction, BRK's signature byte
 *            included
 *   DATA     an access whose value the instruction uses: operands,
 *            pointers, stack pushes and pulls, interrupt vectors
 *   DUMMY    a cycle whose read value the chip ignores: the extra cycles
 *            of implied, indexed, read-modify-write, stack, branch and
 *            decimal instructions, the discarded fetch of interrupt
 *            entry, and the cycles of WAI and STP. Every dummy cycle is a
 *            read: the 65C02 has no dummy writes.
 *
 * The flag EA marks the cycles of the Appletini core's six "data_ea"
 * states (w65c02_core.sv:1049-1069; docs/firmware/zpbank-review.md,
 * finding 7), the only cycles whose address is an instruction's
 * effective address in memory:
 *   DATA_EA   ST_MEM_READ, ST_RMW_READ (reads) and ST_MEM_WRITE,
 *             ST_RMW_WRITE (writes)
 *   DUMMY_EA  ST_RMW_MODIFY (the read-modify-write's second read) and
 *             ST_DECIMAL_EXTRA (the decimal cycle of ADC and SBC)
 * Every other cycle is not EA: opcode and operand fetches, dummy reads
 * of PC, the same-page STA a,X / a,Y false read of its target
 * (ST_INDEX_DUMMY), zero-page pointers, the zero-page reads of BBR and
 * BBS, JMP (a) and (a,X) pointers, stack cycles and vectors. The
 * zero-page bank pair (a2vm.h) redirects only EA cycles.
 * CPU65C02_BASE_KIND gives the kind without the flag. */
typedef enum {
    CPU65C02_OPCODE, CPU65C02_OPERAND, CPU65C02_DATA, CPU65C02_DUMMY,
    CPU65C02_EA = 4,
    CPU65C02_DATA_EA = CPU65C02_DATA | CPU65C02_EA,
    CPU65C02_DUMMY_EA = CPU65C02_DUMMY | CPU65C02_EA
} cpu65c02_kind;

#define CPU65C02_BASE_KIND(kind) ((kind) & 3)

typedef enum {
    CPU65C02_RUNNING,
    CPU65C02_WAITING,   /* after WAI, until IRQ is active or an NMI comes */
    CPU65C02_STOPPED    /* after STP, until reset */
} cpu65c02_state;

typedef uint8_t (*cpu65c02_read_fn)(void *context, uint16_t address,
                                    cpu65c02_kind kind);
typedef void (*cpu65c02_write_fn)(void *context, uint16_t address,
                                  uint8_t value, cpu65c02_kind kind);

typedef struct cpu65c02 {
    uint16_t pc;
    uint8_t a, x, y, s, p;
    uint8_t state;              /* a cpu65c02_state */
    uint8_t nmi_pending;        /* edge seen and not yet taken */
    uint32_t irq_sources;       /* level: one bit per source, set = active */

    uint64_t cycles;            /* every cycle since cpu65c02_init */
    /* cpu65c02_run returns once `cycles` reaches this. A callback may
       lower it to end the run after the current instruction. */
    uint64_t until;

    cpu65c02_read_fn read;
    cpu65c02_write_fn write;
    void *context;
} cpu65c02;

/* Clear the structure and connect the bus. The state is not that of a
   reset; call cpu65c02_reset or set the registers (with P bit 5 set and
   bit 4 clear, as cpu65c02_normalise leaves them). */
void cpu65c02_init(cpu65c02 *cpu, cpu65c02_read_fn read,
                   cpu65c02_write_fn write, void *context);

/* The RESET sequence of 7 cycles: two reads at PC, three stack reads
   that move S down by 3, then PC from $FFFC. I is set and D cleared; A,
   X, Y and the other flags keep their values. Leaves WAI and STP. */
void cpu65c02_reset(cpu65c02 *cpu);

/* Execute one instruction, or take a pending interrupt (7 cycles), or,
   while waiting or stopped, let one cycle pass. Returns the cycles used. */
unsigned cpu65c02_step(cpu65c02 *cpu);

/* Step until `cycles` reaches `until` (the field, set from the argument;
   a callback may lower it). Returns the number of instructions executed,
   an interrupt entry and a waiting or stopped cycle counting as one. */
uint64_t cpu65c02_run(cpu65c02 *cpu, uint64_t until);

/* Assert or release interrupt source bits on the level-sensitive IRQ
   line. The line is active while any bit is set. */
void cpu65c02_set_irq(cpu65c02 *cpu, uint32_t sources, int active);

/* A falling edge on NMI. */
void cpu65c02_nmi(cpu65c02 *cpu);

/* Force P bit 5 on and bit 4 off, after a machine or a test wrote P. */
void cpu65c02_normalise(cpu65c02 *cpu);

/* The number of bytes of each instruction, for disassemblers and traces:
   BRK counts its signature byte. */
extern const uint8_t cpu65c02_length[256];

#endif
