/*
 * 65816 core: see cpu816.h.
 *
 * Each instruction is a sequence of calls to bus_read, bus_write and
 * internal() in the order of the cycle table of the W65C816S datasheet,
 * so the cycle count of an instruction is the number of those calls and
 * the extra cycles of the table (16-bit data, DL not zero, an index
 * crossing a page, a taken branch) appear where the chip spends them.
 */
#include "cpu816.h"

#include <string.h>

enum { NATIVE_COP = 0xffe4, NATIVE_BRK = 0xffe6, NATIVE_NMI = 0xffea,
       NATIVE_IRQ = 0xffee, EMULATION_COP = 0xfff4, EMULATION_NMI = 0xfffa,
       RESET_VECTOR = 0xfffc, EMULATION_IRQ = 0xfffe };

/* How an addressing mode is used: the index penalty cycle of a,x, a,y and
   (d),y is always spent for a write or a read-modify-write. */
typedef enum { ACCESS_READ, ACCESS_WRITE, ACCESS_MODIFY } access;

typedef enum {
    MODE_IMM, MODE_DP, MODE_DPX, MODE_DPY, MODE_DPI, MODE_DPIX, MODE_DPIY,
    MODE_DPIL, MODE_DPILY, MODE_ABS, MODE_ABSX, MODE_ABSY, MODE_LONG,
    MODE_LONGX, MODE_SR, MODE_SRIY
} mode;

/*
 * An effective address: byte i of the operand is at
 * base + ((offset + i) & mask). Data addresses are 24-bit and carry into
 * the next bank; direct page and stack addresses wrap in bank 0; in
 * emulation mode with DL = 0 direct page addresses wrap in the page.
 * `space` is the cpu816_space of its accesses.
 */
typedef struct {
    uint32_t base, offset, mask;
    uint8_t space;
} address;

static uint32_t byte_at(address ea, unsigned i)
{
    return (ea.base + ((ea.offset + i) & ea.mask)) & 0xffffff;
}

static address linear(uint32_t a)
{
    address ea = { 0, a & 0xffffff, 0xffffff, CPU816_DATA };
    return ea;
}

/* A 16-bit address in bank 0 (or in the bank `base`) that wraps there. */
static address in_bank(uint32_t base, uint32_t a, cpu816_space space)
{
    address ea = { base, a & 0xffff, 0xffff, (uint8_t)space };
    return ea;
}

static address bank0(uint32_t a)
{
    return in_bank(0, a, CPU816_DATA);
}

/* Direct page address D + offset, with the page wrap of emulation mode
   when DL is zero. The new addressing modes of the 65816 use direct_long,
   which never wraps in the page. */
static address direct(const cpu816 *cpu, uint32_t offset)
{
    if (cpu->e && !(cpu->d & 0xff)) {
        address ea = { cpu->d & 0xff00u, offset & 0xff, 0xff, CPU816_DIRECT };
        return ea;
    }
    return in_bank(0, cpu->d + offset, CPU816_DIRECT);
}

static address direct_long(const cpu816 *cpu, uint32_t offset)
{
    return in_bank(0, cpu->d + offset, CPU816_DIRECT);
}

static int wide_m(const cpu816 *cpu) { return !(cpu->p & CPU816_M); }
static int wide_x(const cpu816 *cpu) { return !(cpu->p & CPU816_X); }

/* ---- bus cycles ---- */

static uint8_t bus_read(cpu816 *cpu, uint32_t a, uint8_t pins,
                        uint8_t space)
{
    cpu->bus = pins;
    cpu->space = space;
    cpu->cycles++;
    return cpu->read(cpu->context, a & 0xffffff);
}

static void bus_write(cpu816 *cpu, uint32_t a, uint8_t value, uint8_t pins,
                      uint8_t space)
{
    cpu->bus = pins;
    cpu->space = space;
    cpu->cycles++;
    cpu->write(cpu->context, a & 0xffffff, value);
}

/* An internal operation: neither VDA nor VPA, so no access. */
static void internal(cpu816 *cpu)
{
    cpu->bus = 0;
    cpu->cycles++;
}

static uint8_t fetch(cpu816 *cpu)
{
    uint8_t value = bus_read(cpu, (uint32_t)cpu->pbr << 16 | cpu->pc,
                             CPU816_VPA, CPU816_PROGRAM);
    cpu->pc++;
    return value;
}

static uint16_t fetch16(cpu816 *cpu)
{
    uint16_t low = fetch(cpu);
    return (uint16_t)(low | fetch(cpu) << 8);
}

static uint32_t fetch24(cpu816 *cpu)
{
    uint32_t low = fetch16(cpu);
    return low | (uint32_t)fetch(cpu) << 16;
}

static uint16_t read_at(cpu816 *cpu, address ea, int wide, uint8_t pins)
{
    uint16_t value = bus_read(cpu, byte_at(ea, 0), pins, ea.space);
    if (wide)
        value |= (uint16_t)(bus_read(cpu, byte_at(ea, 1), pins, ea.space)
                            << 8);
    return value;
}

static uint32_t read24_at(cpu816 *cpu, address ea)
{
    uint32_t low = read_at(cpu, ea, 1, CPU816_VDA);
    return low | (uint32_t)bus_read(cpu, byte_at(ea, 2), CPU816_VDA,
                                    ea.space) << 16;
}

/* Stores write the low byte first. */
static void write_at(cpu816 *cpu, address ea, uint16_t value, int wide)
{
    bus_write(cpu, byte_at(ea, 0), (uint8_t)value, CPU816_VDA, ea.space);
    if (wide)
        bus_write(cpu, byte_at(ea, 1), (uint8_t)(value >> 8), CPU816_VDA,
                  ea.space);
}

/* ---- stack ---- */

/* Instructions the 6502 has keep S in page 1 in emulation mode. */
static void push(cpu816 *cpu, uint8_t value)
{
    bus_write(cpu, cpu->s, value, CPU816_VDA, CPU816_STACK);
    if (cpu->e)
        cpu->s = 0x0100 | ((cpu->s - 1) & 0xff);
    else
        cpu->s--;
}

static uint8_t pull(cpu816 *cpu)
{
    if (cpu->e)
        cpu->s = 0x0100 | ((cpu->s + 1) & 0xff);
    else
        cpu->s++;
    return bus_read(cpu, cpu->s, CPU816_VDA, CPU816_STACK);
}

/* The 65816's own stack instructions move S as 16 bits even in emulation
   mode, so they can reach pages 0 and 2; page_one() then puts S back in
   page 1, as the chip does at the end of the instruction. */
static void push_long(cpu816 *cpu, uint8_t value)
{
    bus_write(cpu, cpu->s, value, CPU816_VDA, CPU816_STACK);
    cpu->s--;
}

static uint8_t pull_long(cpu816 *cpu)
{
    cpu->s++;
    return bus_read(cpu, cpu->s, CPU816_VDA, CPU816_STACK);
}

static void page_one(cpu816 *cpu)
{
    if (cpu->e)
        cpu->s = 0x0100 | (cpu->s & 0xff);
}

/* ---- flags ---- */

static void set_flag(cpu816 *cpu, uint8_t flag, int on)
{
    if (on)
        cpu->p |= flag;
    else
        cpu->p &= (uint8_t)~flag;
}

static void set_nz(cpu816 *cpu, uint16_t value, int wide)
{
    uint16_t sign = wide ? 0x8000 : 0x80;
    uint16_t mask = wide ? 0xffff : 0xff;
    set_flag(cpu, CPU816_Z, !(value & mask));
    set_flag(cpu, CPU816_N, value & sign);
}

void cpu816_normalise(cpu816 *cpu)
{
    if (cpu->e) {
        cpu->p |= CPU816_M | CPU816_X;
        cpu->s = 0x0100 | (cpu->s & 0xff);
    }
    if (cpu->p & CPU816_X) {
        cpu->x &= 0xff;
        cpu->y &= 0xff;
    }
}

/* Write P, as PLP, RTI and REP/SEP do. */
static void set_p(cpu816 *cpu, uint8_t p)
{
    cpu->p = p;
    cpu816_normalise(cpu);
}

/* Replace the low byte of A only, or all of it. */
static void set_a(cpu816 *cpu, uint16_t value, int wide)
{
    cpu->a = wide ? value : (uint16_t)((cpu->a & 0xff00) | (value & 0xff));
}

static uint16_t index_value(uint16_t value, int wide)
{
    return wide ? value : (uint16_t)(value & 0xff);
}

/* ---- addressing modes ---- */

static void direct_penalty(cpu816 *cpu)
{
    if (cpu->d & 0xff)
        internal(cpu);
}

static void index_penalty(cpu816 *cpu, uint16_t base, uint16_t index,
                          access use)
{
    if (use != ACCESS_READ || wide_x(cpu) ||
        ((base + index) & 0xff00) != (base & 0xff00))
        internal(cpu);
}

static uint32_t data_bank(const cpu816 *cpu)
{
    return (uint32_t)cpu->dbr << 16;
}

/* The effective address of `m` (not MODE_IMM), with the cycles that
   compute it. */
static address effective(cpu816 *cpu, mode m, access use)
{
    uint8_t operand;
    uint16_t base;
    uint32_t pointer;

    switch (m) {
    case MODE_DP:
        operand = fetch(cpu);
        direct_penalty(cpu);
        return direct(cpu, operand);
    case MODE_DPX:
    case MODE_DPY:
        operand = fetch(cpu);
        direct_penalty(cpu);
        internal(cpu);
        return direct(cpu, operand + (m == MODE_DPX ? cpu->x : cpu->y));
    case MODE_DPI:
        operand = fetch(cpu);
        direct_penalty(cpu);
        base = read_at(cpu, direct(cpu, operand), 1, CPU816_VDA);
        return linear(data_bank(cpu) + base);
    case MODE_DPIX:
        operand = fetch(cpu);
        direct_penalty(cpu);
        internal(cpu);
        base = read_at(cpu, direct(cpu, operand + cpu->x), 1, CPU816_VDA);
        return linear(data_bank(cpu) + base);
    case MODE_DPIY:
        operand = fetch(cpu);
        direct_penalty(cpu);
        base = read_at(cpu, direct(cpu, operand), 1, CPU816_VDA);
        index_penalty(cpu, base, cpu->y, use);
        return linear(data_bank(cpu) + base + cpu->y);
    case MODE_DPIL:
    case MODE_DPILY:
        operand = fetch(cpu);
        direct_penalty(cpu);
        pointer = read24_at(cpu, direct_long(cpu, operand));
        return linear(pointer + (m == MODE_DPILY ? cpu->y : 0));
    case MODE_ABS:
        return linear(data_bank(cpu) + fetch16(cpu));
    case MODE_ABSX:
    case MODE_ABSY: {
        uint16_t index = m == MODE_ABSX ? cpu->x : cpu->y;
        base = fetch16(cpu);
        index_penalty(cpu, base, index, use);
        return linear(data_bank(cpu) + base + index);
    }
    case MODE_LONG:
        return linear(fetch24(cpu));
    case MODE_LONGX:
        pointer = fetch24(cpu);
        return linear(pointer + cpu->x);
    case MODE_SR:
        operand = fetch(cpu);
        internal(cpu);
        return in_bank(0, cpu->s + operand, CPU816_STACK);
    case MODE_SRIY:
        operand = fetch(cpu);
        internal(cpu);
        base = read_at(cpu, in_bank(0, cpu->s + operand, CPU816_STACK), 1,
                       CPU816_VDA);
        internal(cpu);
        return linear(data_bank(cpu) + base + cpu->y);
    case MODE_IMM:
        break;
    }
    return linear(0);   /* not reached: callers handle MODE_IMM */
}

/* The operand of a read instruction of width `wide`. */
static uint16_t operand_value(cpu816 *cpu, mode m, int wide)
{
    if (m == MODE_IMM)
        return wide ? fetch16(cpu) : fetch(cpu);
    return read_at(cpu, effective(cpu, m, ACCESS_READ), wide, CPU816_VDA);
}

/* ---- arithmetic ---- */

/* Binary or decimal addition of `data` and the carry to A. SBC passes
   the complement of its operand. Decimal mode works one digit at a time
   with the chip's corrections, so invalid BCD digits give the chip's
   results; V comes from the binary sum of the top digit before its
   correction. The intermediate values are signed because SBC's
   corrections can take a digit below zero. */
static void add(cpu816 *cpu, uint16_t data, int wide, int subtract)
{
    int32_t a = wide ? cpu->a : (cpu->a & 0xff);
    int32_t carry = cpu->p & CPU816_C;
    int32_t result;
    int32_t top = wide ? 0x8000 : 0x80;
    int32_t limit = wide ? 0xffff : 0xff;
    int32_t last = wide ? 12 : 4;       /* shift of the top digit */

    data &= (uint16_t)limit;
    if (!(cpu->p & CPU816_D)) {
        result = a + data + carry;
    } else {
        /* From the lowest digit up; before each digit, `result` holds
           the corrected digits below it and the carry out of them. */
        result = carry;
        for (int32_t shift = 0;; shift += 4) {
            /* this digit and those below it */
            int32_t through = (0x10 << shift) - 1;
            result += (a & (0xf << shift)) + (data & (0xf << shift));
            if (shift == last)
                break;
            if (subtract && result <= through)
                result -= 6 << shift;
            else if (!subtract && result > (0xa << shift) - 1)
                result += 6 << shift;
            result = (result > through ? 0x10 << shift : 0) +
                     (result & through);
        }
    }
    set_flag(cpu, CPU816_V, ~(a ^ data) & (a ^ result) & top);
    if (cpu->p & CPU816_D) {
        int32_t six = 6 << last;
        if (subtract && result <= limit)
            result -= six;
        else if (!subtract && result > (0xa << last) - 1)
            result += six;
    }
    set_flag(cpu, CPU816_C, result > limit);
    set_nz(cpu, (uint16_t)result, wide);
    set_a(cpu, (uint16_t)result, wide);
}

static void compare(cpu816 *cpu, uint16_t reg, uint16_t data, int wide)
{
    uint16_t mask = wide ? 0xffff : 0xff;
    reg &= mask;
    data &= mask;
    set_flag(cpu, CPU816_C, reg >= data);
    set_nz(cpu, (uint16_t)(reg - data), wide);
}

typedef enum {
    OP_ORA, OP_AND, OP_EOR, OP_ADC, OP_STA, OP_LDA, OP_CMP, OP_SBC
} group_op;

/* The eight accumulator operations of the regular opcode columns. */
static void accumulator_op(cpu816 *cpu, group_op op, mode m)
{
    int wide = wide_m(cpu);
    uint16_t value;

    if (op == OP_STA) {
        write_at(cpu, effective(cpu, m, ACCESS_WRITE), cpu->a, wide);
        return;
    }
    value = operand_value(cpu, m, wide);
    switch (op) {
    case OP_ORA: value |= cpu->a; break;
    case OP_AND: value &= cpu->a; break;
    case OP_EOR: value ^= cpu->a; break;
    case OP_ADC: add(cpu, value, wide, 0); return;
    case OP_SBC: add(cpu, (uint16_t)~value, wide, 1); return;
    case OP_CMP: compare(cpu, cpu->a, value, wide); return;
    case OP_LDA: case OP_STA: break;
    }
    set_a(cpu, value, wide);
    set_nz(cpu, value, wide);
}

static void bit_op(cpu816 *cpu, mode m)
{
    int wide = wide_m(cpu);
    uint16_t value = operand_value(cpu, m, wide);
    set_flag(cpu, CPU816_Z, !(value & cpu->a & (wide ? 0xffff : 0xff)));
    if (m != MODE_IMM) {
        set_flag(cpu, CPU816_N, value & (wide ? 0x8000 : 0x80));
        set_flag(cpu, CPU816_V, value & (wide ? 0x4000 : 0x40));
    }
}

typedef enum {
    RMW_ASL, RMW_ROL, RMW_LSR, RMW_ROR, RMW_INC, RMW_DEC, RMW_TSB, RMW_TRB
} rmw_op;

static uint16_t modify(cpu816 *cpu, rmw_op op, uint16_t value, int wide)
{
    uint16_t top = wide ? 0x8000 : 0x80;
    uint16_t mask = wide ? 0xffff : 0xff;
    int carry_in = cpu->p & CPU816_C;

    value &= mask;
    switch (op) {
    case RMW_ASL:
    case RMW_ROL:
        set_flag(cpu, CPU816_C, value & top);
        value = (uint16_t)(value << 1 | (op == RMW_ROL && carry_in));
        break;
    case RMW_LSR:
    case RMW_ROR:
        set_flag(cpu, CPU816_C, value & 1);
        value = (uint16_t)(value >> 1 | (op == RMW_ROR && carry_in ? top : 0));
        break;
    case RMW_INC: value++; break;
    case RMW_DEC: value--; break;
    case RMW_TSB:
    case RMW_TRB:
        set_flag(cpu, CPU816_Z, !(value & cpu->a & mask));
        value = op == RMW_TSB ? (value | cpu->a) : (value & ~cpu->a);
        return value & mask;
    }
    value &= mask;
    set_nz(cpu, value, wide);
    return value;
}

/* Read, modify and write back memory, the result high byte first. MLB is
   low on all of these cycles. In emulation mode the chip drives RWB low
   on the modify cycle, as the 6502 writes the unmodified value there, but
   VDA and VPA stay low, so memory sees no access: it is internal here in
   both modes. */
static void memory_modify(cpu816 *cpu, rmw_op op, mode m)
{
    int wide = wide_m(cpu);
    const uint8_t pins = CPU816_VDA | CPU816_MLB;
    address ea = effective(cpu, m, ACCESS_MODIFY);
    uint16_t value = read_at(cpu, ea, wide, pins);

    internal(cpu);
    value = modify(cpu, op, value, wide);
    if (wide)
        bus_write(cpu, byte_at(ea, 1), (uint8_t)(value >> 8), pins,
                  ea.space);
    bus_write(cpu, byte_at(ea, 0), (uint8_t)value, pins, ea.space);
}

static void accumulator_modify(cpu816 *cpu, rmw_op op)
{
    int wide = wide_m(cpu);
    internal(cpu);
    set_a(cpu, modify(cpu, op, cpu->a, wide), wide);
}

/* ---- index registers ---- */

static void load_index(cpu816 *cpu, uint16_t *reg, mode m)
{
    int wide = wide_x(cpu);
    *reg = operand_value(cpu, m, wide);
    set_nz(cpu, *reg, wide);
}

static void compare_index(cpu816 *cpu, uint16_t reg, mode m)
{
    int wide = wide_x(cpu);
    compare(cpu, reg, operand_value(cpu, m, wide), wide);
}

static void store(cpu816 *cpu, uint16_t value, int wide, mode m)
{
    write_at(cpu, effective(cpu, m, ACCESS_WRITE), value, wide);
}

static void step_index(cpu816 *cpu, uint16_t *reg, int delta)
{
    int wide = wide_x(cpu);
    internal(cpu);
    *reg = index_value((uint16_t)(*reg + delta), wide);
    set_nz(cpu, *reg, wide);
}

/* TAX, TXY and the like: the destination's width decides. */
static void transfer_index(cpu816 *cpu, uint16_t *to, uint16_t from)
{
    int wide = wide_x(cpu);
    internal(cpu);
    *to = index_value(from, wide);
    set_nz(cpu, *to, wide);
}

static void transfer_to_a(cpu816 *cpu, uint16_t from)
{
    int wide = wide_m(cpu);
    internal(cpu);
    set_a(cpu, from, wide);
    set_nz(cpu, from, wide);
}

/* ---- control flow ---- */

static void branch(cpu816 *cpu, int taken)
{
    int8_t offset = (int8_t)fetch(cpu);
    uint16_t target;

    if (!taken)
        return;
    target = (uint16_t)(cpu->pc + offset);
    /* Only emulation mode spends a cycle when the branch crosses a page. */
    if (cpu->e && (target & 0xff00) != (cpu->pc & 0xff00))
        internal(cpu);
    internal(cpu);
    cpu->pc = target;
}

static void push_registers_and_vector(cpu816 *cpu, uint8_t pushed_p,
                                      uint16_t vector)
{
    if (!cpu->e)
        push(cpu, cpu->pbr);
    push(cpu, (uint8_t)(cpu->pc >> 8));
    push(cpu, (uint8_t)cpu->pc);
    push(cpu, pushed_p);
    cpu->p = (uint8_t)((cpu->p | CPU816_I) & ~CPU816_D);
    cpu->pbr = 0;
    cpu->pc = bus_read(cpu, vector, CPU816_VDA | CPU816_VPB, CPU816_VECTOR);
    cpu->pc |= (uint16_t)(bus_read(cpu, vector + 1u, CPU816_VDA | CPU816_VPB,
                                   CPU816_VECTOR) << 8);
}

/* BRK and COP: the signature byte is fetched and skipped. In emulation
   mode P is pushed with the break bit set, which the register already
   holds there. */
static void software_interrupt(cpu816 *cpu, uint16_t native,
                               uint16_t emulation)
{
    fetch(cpu);
    push_registers_and_vector(cpu, cpu->p, cpu->e ? emulation : native);
}

/* IRQ and NMI between instructions. The chip spends two cycles on the
   opcode it discards; they are internal here, so that an interrupt
   reads nothing a machine could see. */
static void hardware_interrupt(cpu816 *cpu, uint16_t native,
                               uint16_t emulation)
{
    internal(cpu);
    internal(cpu);
    push_registers_and_vector(
        cpu, cpu->e ? (uint8_t)(cpu->p & ~CPU816_X) : cpu->p,
        cpu->e ? emulation : native);
}

/* One step of MVN (step +1) or MVP (step -1): one byte moves from
   source bank:X to destination bank:Y, and the instruction repeats
   itself by moving PC back until A, counting down, passes zero. So an
   interrupt can come between any two bytes. */
static void block_move(cpu816 *cpu, int step)
{
    uint8_t destination = fetch(cpu);
    uint8_t source = fetch(cpu);
    uint8_t value;
    int wide = wide_x(cpu);

    cpu->dbr = destination;
    value = bus_read(cpu, (uint32_t)source << 16 | cpu->x, CPU816_VDA,
                     CPU816_DATA);
    bus_write(cpu, (uint32_t)destination << 16 | cpu->y, value, CPU816_VDA,
              CPU816_DATA);
    internal(cpu);
    internal(cpu);
    cpu->x = index_value((uint16_t)(cpu->x + step), wide);
    cpu->y = index_value((uint16_t)(cpu->y + step), wide);
    if (cpu->a-- != 0)
        cpu->pc -= 3;
}

static void exchange_carry_emulation(cpu816 *cpu)
{
    uint8_t carry = cpu->p & CPU816_C;
    internal(cpu);
    set_flag(cpu, CPU816_C, cpu->e);
    cpu->e = carry;
    cpu816_normalise(cpu);
}

static void change_flags(cpu816 *cpu, int set)
{
    uint8_t mask = fetch(cpu);
    internal(cpu);
    set_p(cpu, set ? (uint8_t)(cpu->p | mask) : (uint8_t)(cpu->p & ~mask));
}

static void clear_or_set(cpu816 *cpu, uint8_t flag, int on)
{
    internal(cpu);
    set_flag(cpu, flag, on);
}

/* ---- the opcode map ---- */

/* The eight accumulator operations (ORA AND EOR ADC STA LDA CMP SBC,
   by the top three bits of the opcode) share the addressing mode of each
   column, the low five bits. Sets *m and returns 1 for those columns. */
static int group_column(uint8_t opcode, mode *m)
{
    switch (opcode & 0x1f) {
    case 0x01: *m = MODE_DPIX; return 1;
    case 0x03: *m = MODE_SR; return 1;
    case 0x05: *m = MODE_DP; return 1;
    case 0x07: *m = MODE_DPIL; return 1;
    case 0x09: *m = MODE_IMM; return opcode != 0x89;    /* 0x89 is BIT # */
    case 0x0d: *m = MODE_ABS; return 1;
    case 0x0f: *m = MODE_LONG; return 1;
    case 0x11: *m = MODE_DPIY; return 1;
    case 0x12: *m = MODE_DPI; return 1;
    case 0x13: *m = MODE_SRIY; return 1;
    case 0x15: *m = MODE_DPX; return 1;
    case 0x17: *m = MODE_DPILY; return 1;
    case 0x19: *m = MODE_ABSY; return 1;
    case 0x1d: *m = MODE_ABSX; return 1;
    case 0x1f: *m = MODE_LONGX; return 1;
    }
    return 0;
}

static void execute(cpu816 *cpu, uint8_t opcode)
{
    int wide;
    uint16_t value;
    uint32_t target;
    mode m;

    if (group_column(opcode, &m)) {
        accumulator_op(cpu, (group_op)(opcode >> 5), m);
        return;
    }
    switch (opcode) {
    /* shifts, rotates, increments and test-and-set on memory */
    case 0x06: memory_modify(cpu, RMW_ASL, MODE_DP); break;
    case 0x0e: memory_modify(cpu, RMW_ASL, MODE_ABS); break;
    case 0x16: memory_modify(cpu, RMW_ASL, MODE_DPX); break;
    case 0x1e: memory_modify(cpu, RMW_ASL, MODE_ABSX); break;
    case 0x26: memory_modify(cpu, RMW_ROL, MODE_DP); break;
    case 0x2e: memory_modify(cpu, RMW_ROL, MODE_ABS); break;
    case 0x36: memory_modify(cpu, RMW_ROL, MODE_DPX); break;
    case 0x3e: memory_modify(cpu, RMW_ROL, MODE_ABSX); break;
    case 0x46: memory_modify(cpu, RMW_LSR, MODE_DP); break;
    case 0x4e: memory_modify(cpu, RMW_LSR, MODE_ABS); break;
    case 0x56: memory_modify(cpu, RMW_LSR, MODE_DPX); break;
    case 0x5e: memory_modify(cpu, RMW_LSR, MODE_ABSX); break;
    case 0x66: memory_modify(cpu, RMW_ROR, MODE_DP); break;
    case 0x6e: memory_modify(cpu, RMW_ROR, MODE_ABS); break;
    case 0x76: memory_modify(cpu, RMW_ROR, MODE_DPX); break;
    case 0x7e: memory_modify(cpu, RMW_ROR, MODE_ABSX); break;
    case 0xc6: memory_modify(cpu, RMW_DEC, MODE_DP); break;
    case 0xce: memory_modify(cpu, RMW_DEC, MODE_ABS); break;
    case 0xd6: memory_modify(cpu, RMW_DEC, MODE_DPX); break;
    case 0xde: memory_modify(cpu, RMW_DEC, MODE_ABSX); break;
    case 0xe6: memory_modify(cpu, RMW_INC, MODE_DP); break;
    case 0xee: memory_modify(cpu, RMW_INC, MODE_ABS); break;
    case 0xf6: memory_modify(cpu, RMW_INC, MODE_DPX); break;
    case 0xfe: memory_modify(cpu, RMW_INC, MODE_ABSX); break;
    case 0x04: memory_modify(cpu, RMW_TSB, MODE_DP); break;
    case 0x0c: memory_modify(cpu, RMW_TSB, MODE_ABS); break;
    case 0x14: memory_modify(cpu, RMW_TRB, MODE_DP); break;
    case 0x1c: memory_modify(cpu, RMW_TRB, MODE_ABS); break;

    case 0x0a: accumulator_modify(cpu, RMW_ASL); break;
    case 0x2a: accumulator_modify(cpu, RMW_ROL); break;
    case 0x4a: accumulator_modify(cpu, RMW_LSR); break;
    case 0x6a: accumulator_modify(cpu, RMW_ROR); break;
    case 0x1a: accumulator_modify(cpu, RMW_INC); break;
    case 0x3a: accumulator_modify(cpu, RMW_DEC); break;

    case 0x24: bit_op(cpu, MODE_DP); break;
    case 0x2c: bit_op(cpu, MODE_ABS); break;
    case 0x34: bit_op(cpu, MODE_DPX); break;
    case 0x3c: bit_op(cpu, MODE_ABSX); break;
    case 0x89: bit_op(cpu, MODE_IMM); break;

    /* stores other than STA */
    case 0x64: store(cpu, 0, wide_m(cpu), MODE_DP); break;
    case 0x74: store(cpu, 0, wide_m(cpu), MODE_DPX); break;
    case 0x9c: store(cpu, 0, wide_m(cpu), MODE_ABS); break;
    case 0x9e: store(cpu, 0, wide_m(cpu), MODE_ABSX); break;
    case 0x86: store(cpu, cpu->x, wide_x(cpu), MODE_DP); break;
    case 0x8e: store(cpu, cpu->x, wide_x(cpu), MODE_ABS); break;
    case 0x96: store(cpu, cpu->x, wide_x(cpu), MODE_DPY); break;
    case 0x84: store(cpu, cpu->y, wide_x(cpu), MODE_DP); break;
    case 0x8c: store(cpu, cpu->y, wide_x(cpu), MODE_ABS); break;
    case 0x94: store(cpu, cpu->y, wide_x(cpu), MODE_DPX); break;

    /* index loads and compares */
    case 0xa2: load_index(cpu, &cpu->x, MODE_IMM); break;
    case 0xa6: load_index(cpu, &cpu->x, MODE_DP); break;
    case 0xae: load_index(cpu, &cpu->x, MODE_ABS); break;
    case 0xb6: load_index(cpu, &cpu->x, MODE_DPY); break;
    case 0xbe: load_index(cpu, &cpu->x, MODE_ABSY); break;
    case 0xa0: load_index(cpu, &cpu->y, MODE_IMM); break;
    case 0xa4: load_index(cpu, &cpu->y, MODE_DP); break;
    case 0xac: load_index(cpu, &cpu->y, MODE_ABS); break;
    case 0xb4: load_index(cpu, &cpu->y, MODE_DPX); break;
    case 0xbc: load_index(cpu, &cpu->y, MODE_ABSX); break;
    case 0xe0: compare_index(cpu, cpu->x, MODE_IMM); break;
    case 0xe4: compare_index(cpu, cpu->x, MODE_DP); break;
    case 0xec: compare_index(cpu, cpu->x, MODE_ABS); break;
    case 0xc0: compare_index(cpu, cpu->y, MODE_IMM); break;
    case 0xc4: compare_index(cpu, cpu->y, MODE_DP); break;
    case 0xcc: compare_index(cpu, cpu->y, MODE_ABS); break;

    case 0xe8: step_index(cpu, &cpu->x, 1); break;
    case 0xc8: step_index(cpu, &cpu->y, 1); break;
    case 0xca: step_index(cpu, &cpu->x, -1); break;
    case 0x88: step_index(cpu, &cpu->y, -1); break;

    /* transfers */
    case 0xaa: transfer_index(cpu, &cpu->x, cpu->a); break;
    case 0xa8: transfer_index(cpu, &cpu->y, cpu->a); break;
    case 0xba: transfer_index(cpu, &cpu->x, cpu->s); break;
    case 0x9b: transfer_index(cpu, &cpu->y, cpu->x); break;
    case 0xbb: transfer_index(cpu, &cpu->x, cpu->y); break;
    case 0x8a: transfer_to_a(cpu, cpu->x); break;
    case 0x98: transfer_to_a(cpu, cpu->y); break;
    case 0x9a:          /* TXS */
        internal(cpu);
        cpu->s = cpu->e ? (uint16_t)(0x0100 | (cpu->x & 0xff)) : cpu->x;
        break;
    case 0x1b:          /* TCS */
        internal(cpu);
        cpu->s = cpu->a;
        page_one(cpu);
        break;
    case 0x3b:          /* TSC: all 16 bits whatever M is */
        internal(cpu);
        cpu->a = cpu->s;
        set_nz(cpu, cpu->a, 1);
        break;
    case 0x5b:          /* TCD */
        internal(cpu);
        cpu->d = cpu->a;
        set_nz(cpu, cpu->d, 1);
        break;
    case 0x7b:          /* TDC */
        internal(cpu);
        cpu->a = cpu->d;
        set_nz(cpu, cpu->a, 1);
        break;
    case 0xeb:          /* XBA: flags from the new low byte */
        internal(cpu);
        internal(cpu);
        cpu->a = (uint16_t)(cpu->a >> 8 | cpu->a << 8);
        set_nz(cpu, cpu->a, 0);
        break;

    /* flags */
    case 0x18: clear_or_set(cpu, CPU816_C, 0); break;
    case 0x38: clear_or_set(cpu, CPU816_C, 1); break;
    case 0x58: clear_or_set(cpu, CPU816_I, 0); break;
    case 0x78: clear_or_set(cpu, CPU816_I, 1); break;
    case 0xb8: clear_or_set(cpu, CPU816_V, 0); break;
    case 0xd8: clear_or_set(cpu, CPU816_D, 0); break;
    case 0xf8: clear_or_set(cpu, CPU816_D, 1); break;
    case 0xc2: change_flags(cpu, 0); break;
    case 0xe2: change_flags(cpu, 1); break;
    case 0xfb: exchange_carry_emulation(cpu); break;

    /* stack */
    case 0x48:          /* PHA */
    case 0xda:          /* PHX */
    case 0x5a:          /* PHY */
        wide = opcode == 0x48 ? wide_m(cpu) : wide_x(cpu);
        value = opcode == 0x48 ? cpu->a : opcode == 0xda ? cpu->x : cpu->y;
        internal(cpu);
        if (wide)
            push(cpu, (uint8_t)(value >> 8));
        push(cpu, (uint8_t)value);
        break;
    case 0x68:          /* PLA */
    case 0xfa:          /* PLX */
    case 0x7a:          /* PLY */
        wide = opcode == 0x68 ? wide_m(cpu) : wide_x(cpu);
        internal(cpu);
        internal(cpu);
        value = pull(cpu);
        if (wide)
            value |= (uint16_t)(pull(cpu) << 8);
        set_nz(cpu, value, wide);
        if (opcode == 0x68)
            set_a(cpu, value, wide);
        else
            *(opcode == 0xfa ? &cpu->x : &cpu->y) = value;
        break;
    case 0x08: internal(cpu); push(cpu, cpu->p); break;           /* PHP */
    case 0x8b: internal(cpu); push(cpu, cpu->dbr); break;         /* PHB */
    case 0x4b: internal(cpu); push(cpu, cpu->pbr); break;         /* PHK */
    case 0x28:          /* PLP */
        internal(cpu);
        internal(cpu);
        set_p(cpu, pull(cpu));
        break;
    case 0xab:          /* PLB */
        internal(cpu);
        internal(cpu);
        cpu->dbr = pull_long(cpu);
        page_one(cpu);
        set_nz(cpu, cpu->dbr, 0);
        break;
    case 0x0b:          /* PHD */
        internal(cpu);
        push_long(cpu, (uint8_t)(cpu->d >> 8));
        push_long(cpu, (uint8_t)cpu->d);
        page_one(cpu);
        break;
    case 0x2b:          /* PLD */
        internal(cpu);
        internal(cpu);
        cpu->d = pull_long(cpu);
        cpu->d |= (uint16_t)(pull_long(cpu) << 8);
        page_one(cpu);
        set_nz(cpu, cpu->d, 1);
        break;
    case 0xf4:          /* PEA */
        value = fetch16(cpu);
        push_long(cpu, (uint8_t)(value >> 8));
        push_long(cpu, (uint8_t)value);
        page_one(cpu);
        break;
    case 0xd4: {        /* PEI */
        uint8_t operand = fetch(cpu);
        direct_penalty(cpu);
        value = read_at(cpu, direct_long(cpu, operand), 1, CPU816_VDA);
        push_long(cpu, (uint8_t)(value >> 8));
        push_long(cpu, (uint8_t)value);
        page_one(cpu);
        break;
    }
    case 0x62:          /* PER */
        value = fetch16(cpu);
        internal(cpu);
        value = (uint16_t)(value + cpu->pc);
        push_long(cpu, (uint8_t)(value >> 8));
        push_long(cpu, (uint8_t)value);
        page_one(cpu);
        break;

    /* branches */
    case 0x10: branch(cpu, !(cpu->p & CPU816_N)); break;
    case 0x30: branch(cpu, cpu->p & CPU816_N); break;
    case 0x50: branch(cpu, !(cpu->p & CPU816_V)); break;
    case 0x70: branch(cpu, cpu->p & CPU816_V); break;
    case 0x90: branch(cpu, !(cpu->p & CPU816_C)); break;
    case 0xb0: branch(cpu, cpu->p & CPU816_C); break;
    case 0xd0: branch(cpu, !(cpu->p & CPU816_Z)); break;
    case 0xf0: branch(cpu, cpu->p & CPU816_Z); break;
    case 0x80: branch(cpu, 1); break;
    case 0x82:          /* BRL */
        value = fetch16(cpu);
        internal(cpu);
        cpu->pc = (uint16_t)(cpu->pc + value);
        break;

    /* jumps, calls and returns */
    case 0x4c:          /* JMP a */
        cpu->pc = fetch16(cpu);
        break;
    case 0x5c:          /* JML al */
        target = fetch24(cpu);
        cpu->pc = (uint16_t)target;
        cpu->pbr = (uint8_t)(target >> 16);
        break;
    case 0x6c:          /* JMP (a) */
        cpu->pc = read_at(cpu, bank0(fetch16(cpu)), 1, CPU816_VDA);
        break;
    case 0x7c:          /* JMP (a,x) */
        value = fetch16(cpu);
        internal(cpu);
        cpu->pc = read_at(cpu, in_bank((uint32_t)cpu->pbr << 16,
                                       (uint32_t)value + cpu->x, CPU816_DATA),
                          1, CPU816_VDA);
        break;
    case 0xdc:          /* JML [a] */
        target = read24_at(cpu, bank0(fetch16(cpu)));
        cpu->pc = (uint16_t)target;
        cpu->pbr = (uint8_t)(target >> 16);
        break;
    case 0x20:          /* JSR a: pushes the address of its last byte */
        value = fetch16(cpu);
        internal(cpu);
        cpu->pc--;
        push(cpu, (uint8_t)(cpu->pc >> 8));
        push(cpu, (uint8_t)cpu->pc);
        cpu->pc = value;
        break;
    case 0x22:          /* JSL al */
        value = fetch16(cpu);
        push_long(cpu, cpu->pbr);
        internal(cpu);
        cpu->pbr = fetch(cpu);
        cpu->pc--;
        push_long(cpu, (uint8_t)(cpu->pc >> 8));
        push_long(cpu, (uint8_t)cpu->pc);
        page_one(cpu);
        cpu->pc = value;
        break;
    case 0xfc: {        /* JSR (a,x) */
        uint8_t low = fetch(cpu);
        push_long(cpu, (uint8_t)(cpu->pc >> 8));
        push_long(cpu, (uint8_t)cpu->pc);
        value = (uint16_t)(low | fetch(cpu) << 8);
        internal(cpu);
        cpu->pc = read_at(cpu, in_bank((uint32_t)cpu->pbr << 16,
                                       (uint32_t)value + cpu->x, CPU816_DATA),
                          1, CPU816_VDA);
        page_one(cpu);
        break;
    }
    case 0x60:          /* RTS */
        internal(cpu);
        internal(cpu);
        value = pull(cpu);
        value |= (uint16_t)(pull(cpu) << 8);
        internal(cpu);
        cpu->pc = (uint16_t)(value + 1);
        break;
    case 0x6b:          /* RTL */
        internal(cpu);
        internal(cpu);
        value = pull_long(cpu);
        value |= (uint16_t)(pull_long(cpu) << 8);
        cpu->pbr = pull_long(cpu);
        page_one(cpu);
        cpu->pc = (uint16_t)(value + 1);
        break;
    case 0x40:          /* RTI */
        internal(cpu);
        internal(cpu);
        set_p(cpu, pull(cpu));
        value = pull(cpu);
        value |= (uint16_t)(pull(cpu) << 8);
        cpu->pc = value;
        if (!cpu->e)
            cpu->pbr = pull(cpu);
        break;
    case 0x00: software_interrupt(cpu, NATIVE_BRK, EMULATION_IRQ); break;
    case 0x02: software_interrupt(cpu, NATIVE_COP, EMULATION_COP); break;

    case 0x54: block_move(cpu, 1); break;       /* MVN */
    case 0x44: block_move(cpu, -1); break;      /* MVP */

    case 0xea: internal(cpu); break;            /* NOP */
    case 0x42:          /* WDM: skips a byte without reading it */
        internal(cpu);
        cpu->pc++;
        break;
    case 0xcb:          /* WAI */
        internal(cpu);
        internal(cpu);
        cpu->state = CPU816_WAITING;
        break;
    case 0xdb:          /* STP */
        internal(cpu);
        internal(cpu);
        cpu->state = CPU816_STOPPED;
        break;
    }
}

/* ---- public interface ---- */

void cpu816_init(cpu816 *cpu, cpu816_read_fn read, cpu816_write_fn write,
                 void *context)
{
    memset(cpu, 0, sizeof *cpu);
    cpu->read = read;
    cpu->write = write;
    cpu->context = context;
    cpu->e = 1;
    cpu816_normalise(cpu);
}

void cpu816_reset(cpu816 *cpu)
{
    for (int i = 0; i < 5; i++)
        internal(cpu);
    cpu->e = 1;
    cpu->d = 0;
    cpu->dbr = 0;
    cpu->pbr = 0;
    cpu->p = (uint8_t)((cpu->p | CPU816_I) & ~CPU816_D);
    cpu816_normalise(cpu);
    cpu->state = CPU816_RUNNING;
    cpu->nmi_pending = 0;
    cpu->pc = bus_read(cpu, RESET_VECTOR, CPU816_VDA | CPU816_VPB,
                       CPU816_VECTOR);
    cpu->pc |= (uint16_t)(bus_read(cpu, RESET_VECTOR + 1,
                                   CPU816_VDA | CPU816_VPB,
                                   CPU816_VECTOR) << 8);
}

unsigned cpu816_step(cpu816 *cpu)
{
    uint64_t start = cpu->cycles;

    if (cpu->state != CPU816_RUNNING) {
        /* WAI ends when an interrupt line is active, even with I set, in
           which case execution goes on after the WAI. */
        if (cpu->state == CPU816_STOPPED ||
            (!cpu->irq_sources && !cpu->nmi_pending)) {
            internal(cpu);
            return 1;
        }
        cpu->state = CPU816_RUNNING;
    }
    if (cpu->nmi_pending) {
        cpu->nmi_pending = 0;
        hardware_interrupt(cpu, NATIVE_NMI, EMULATION_NMI);
    } else if (cpu->irq_sources && !(cpu->p & CPU816_I)) {
        hardware_interrupt(cpu, NATIVE_IRQ, EMULATION_IRQ);
    } else {
        uint8_t opcode = bus_read(cpu, (uint32_t)cpu->pbr << 16 | cpu->pc,
                                  CPU816_VDA | CPU816_VPA, CPU816_PROGRAM);
        cpu->pc++;
        execute(cpu, opcode);
    }
    return (unsigned)(cpu->cycles - start);
}

void cpu816_set_irq(cpu816 *cpu, uint32_t sources, int active)
{
    if (active)
        cpu->irq_sources |= sources;
    else
        cpu->irq_sources &= ~sources;
}

void cpu816_nmi(cpu816 *cpu)
{
    cpu->nmi_pending = 1;
}
