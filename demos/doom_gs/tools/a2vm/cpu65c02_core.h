/*
 * The W65C02S core itself: see cpu65c02.h for what it models.
 *
 * This is not an ordinary header. It holds the whole core and is
 * included once for each bus it is connected to, so that a machine can
 * have its memory accesses inlined into the core. Before including it,
 * define:
 *
 *   C02_PREFIX    the prefix of the functions it defines: C02_PREFIX
 *                 followed by step, run and reset, with the signatures of
 *                 cpu65c02_step, cpu65c02_run and cpu65c02_reset
 *   C02_LINKAGE   the storage class of those three: empty, or static
 *   C02_READ(cpu, address, kind)          a uint8_t expression
 *   C02_WRITE(cpu, address, value, kind)  a statement
 *
 * `address` is a uint16_t, `value` a uint8_t and `kind` a cpu65c02_kind
 * constant, so an inlined bus can test it at no cost. `cpu->cycles` has
 * already been advanced past the cycle when the macro runs. Everything
 * the file defines besides those three functions is static and carries
 * the prefix, and every macro is undefined at the end, so a translation
 * unit may include it more than once with different prefixes.
 *
 * Each instruction is a sequence of reads and writes in the order of
 * the chip's cycles; the cycle count of an instruction is the number of
 * those calls. The dummy cycles read the addresses the Appletini core
 * puts on the bus (hdl/apple/w65c02_core.sv, its "addr" block): mostly
 * the last instruction byte or the next one, as the datasheet's table
 * 7-1 says of the W65C02S.
 */
#include "cpu65c02.h"

#if !defined(C02_PREFIX) || !defined(C02_LINKAGE) || !defined(C02_READ) || \
    !defined(C02_WRITE)
#error "define C02_PREFIX, C02_LINKAGE, C02_READ and C02_WRITE first"
#endif

#define C02_CAT2(a, b) a##b
#define C02_CAT(a, b) C02_CAT2(a, b)
#define C02_F(name) C02_CAT(C02_PREFIX, name)

/* ---- bus cycles ---- */

static inline uint8_t C02_F(rd_)(cpu65c02 *cpu, uint16_t address,
                                 cpu65c02_kind kind)
{
    cpu->cycles++;
    return C02_READ(cpu, address, kind);
}

static inline void C02_F(wr_)(cpu65c02 *cpu, uint16_t address, uint8_t value,
                              cpu65c02_kind kind)
{
    cpu->cycles++;
    C02_WRITE(cpu, address, value, kind);
}

#define RD(address, kind) C02_F(rd_)(cpu, (uint16_t)(address), kind)
#define WR(address, value, kind) \
    C02_F(wr_)(cpu, (uint16_t)(address), (uint8_t)(value), kind)
#define DUMMY(address) ((void)RD(address, CPU65C02_DUMMY))
#define DATA CPU65C02_DATA
/* The cycles of the core's data_ea states (cpu65c02.h): an access at the
   instruction's effective address, and the dummy re-reads of it. */
#define EA CPU65C02_DATA_EA
#define DUMMY_EA(address) ((void)RD(address, CPU65C02_DUMMY_EA))

/* The next byte of the instruction. */
static inline uint8_t C02_F(operand_)(cpu65c02 *cpu)
{
    uint8_t value = RD(cpu->pc, CPU65C02_OPERAND);
    cpu->pc++;
    return value;
}

#define OPERAND() C02_F(operand_)(cpu)

/* ---- flags ---- */

#define SET_NZ(value) \
    (cpu->p = (uint8_t)((cpu->p & ~(CPU65C02_N | CPU65C02_Z)) | \
                        ((value) & 0x80) | ((value) ? 0 : CPU65C02_Z)))
#define SET_FLAG(flag, on) \
    (cpu->p = (uint8_t)((on) ? cpu->p | (flag) : cpu->p & ~(flag)))

/* ---- addressing modes: each returns the effective address ---- */

/* zp,X and zp,Y: the extra cycle reads the unindexed zero-page address. */
static inline uint16_t C02_F(zp_indexed_)(cpu65c02 *cpu, uint8_t index)
{
    uint8_t base = OPERAND();
    DUMMY(base);
    return (uint8_t)(base + index);
}

static inline uint16_t C02_F(absolute_)(cpu65c02 *cpu)
{
    uint16_t low = OPERAND();
    return (uint16_t)(low | OPERAND() << 8);
}

/* a,X and a,Y. Reads spend the extra cycle only when the index crosses a
   page; `always` is set for writes and for INC and DEC, which spend it
   every time (table 4-1 note 1, table 7-1). The cycle reads the last
   instruction byte, except that STA on the same page reads its own
   target, as the NMOS chip does: `sta` selects that. That false read is
   the core's ST_INDEX_DUMMY, not data_ea: a plain
   DUMMY. */
static inline uint16_t C02_F(abs_indexed_)(cpu65c02 *cpu, uint8_t index,
                                           int always, int sta)
{
    uint16_t base = C02_F(absolute_)(cpu);
    uint16_t address = (uint16_t)(base + index);
    int crossed = (base ^ address) & 0xff00;
    if (crossed || always)
        DUMMY(sta && !crossed ? address : (uint16_t)(cpu->pc - 1));
    return address;
}

/* (zp,X): the extra cycle reads the unindexed zero-page address; the
   pointer wraps in page zero. */
static inline uint16_t C02_F(indexed_indirect_)(cpu65c02 *cpu)
{
    uint8_t pointer = OPERAND();
    uint16_t low;
    DUMMY(pointer);
    pointer = (uint8_t)(pointer + cpu->x);
    low = RD(pointer, DATA);
    return (uint16_t)(low | RD((uint8_t)(pointer + 1), DATA) << 8);
}

/* (zp),Y: the extra cycle, on a page crossing or for a write, reads the
   last instruction byte. */
static inline uint16_t C02_F(indirect_indexed_)(cpu65c02 *cpu, int always)
{
    uint8_t pointer = OPERAND();
    uint16_t low = RD(pointer, DATA);
    uint16_t base = (uint16_t)(low | RD((uint8_t)(pointer + 1), DATA) << 8);
    uint16_t address = (uint16_t)(base + cpu->y);
    if (always || ((base ^ address) & 0xff00))
        DUMMY(cpu->pc - 1);
    return address;
}

/* (zp) */
static inline uint16_t C02_F(indirect_)(cpu65c02 *cpu)
{
    uint8_t pointer = OPERAND();
    uint16_t low = RD(pointer, DATA);
    return (uint16_t)(low | RD((uint8_t)(pointer + 1), DATA) << 8);
}

#define ZP() ((uint16_t)OPERAND())
#define ZPX() C02_F(zp_indexed_)(cpu, cpu->x)
#define ZPY() C02_F(zp_indexed_)(cpu, cpu->y)
#define ABS() C02_F(absolute_)(cpu)
#define ABSX_R() C02_F(abs_indexed_)(cpu, cpu->x, 0, 0)
#define ABSY_R() C02_F(abs_indexed_)(cpu, cpu->y, 0, 0)
#define INDX() C02_F(indexed_indirect_)(cpu)
#define INDY_R() C02_F(indirect_indexed_)(cpu, 0)
#define IND() C02_F(indirect_)(cpu)

/* ---- arithmetic ---- */

/* ADC. In decimal mode the W65C02S gives a valid N, Z and C for any
   operands, BCD or not, and takes one more cycle (table 7-1). The
   decimal result follows Bruce Clark, "Decimal Mode" (6502.org, 2004),
   appendix A, sequence 1 for A and C; V follows his sequence 2, which
   the 65C02 shares with the 6502: the signed sum of the high digits
   after the low digit is corrected, before the high digit is. */
static inline void C02_F(adc_)(cpu65c02 *cpu, uint8_t m)
{
    unsigned a = cpu->a, carry = cpu->p & CPU65C02_C, result;
    int overflow;

    if (!(cpu->p & CPU65C02_D)) {
        result = a + m + carry;
        overflow = (~(a ^ m) & (a ^ result) & 0x80) != 0;
        SET_FLAG(CPU65C02_C, result > 0xff);
    } else {
        unsigned low = (a & 0x0f) + (m & 0x0f) + carry;
        int sum;
        if (low >= 0x0a)
            low = ((low + 0x06) & 0x0f) + 0x10;
        result = (a & 0xf0) + (m & 0xf0) + low;
        sum = (int)(int8_t)(a & 0xf0) + (int)(int8_t)(m & 0xf0) + (int)low;
        overflow = sum < -128 || sum > 127;
        if (result >= 0xa0)
            result += 0x60;
        SET_FLAG(CPU65C02_C, result >= 0x100);
    }
    SET_FLAG(CPU65C02_V, overflow);
    cpu->a = (uint8_t)result;
    SET_NZ(cpu->a);
}

/* SBC. C and V are those of the binary subtraction in both modes; the
   decimal result is Clark's sequence 4 for the 65C02. */
static inline void C02_F(sbc_)(cpu65c02 *cpu, uint8_t m)
{
    unsigned a = cpu->a, borrow = !(cpu->p & CPU65C02_C);
    unsigned result = a - m - borrow;

    SET_FLAG(CPU65C02_V, ((a ^ m) & (a ^ result) & 0x80) != 0);
    SET_FLAG(CPU65C02_C, result < 0x100);
    if (cpu->p & CPU65C02_D) {
        int low = (int)(a & 0x0f) - (int)(m & 0x0f) - (int)borrow;
        int decimal = (int)a - (int)m - (int)borrow;
        if (decimal < 0)
            decimal -= 0x60;
        if (low < 0)
            decimal -= 0x06;
        result = (unsigned)decimal;
    }
    cpu->a = (uint8_t)result;
    SET_NZ(cpu->a);
}

static inline void C02_F(compare_)(cpu65c02 *cpu, uint8_t reg, uint8_t m)
{
    uint8_t difference = (uint8_t)(reg - m);
    SET_FLAG(CPU65C02_C, reg >= m);
    SET_NZ(difference);
}

/* The decimal cycle of ADC and SBC reads the effective address again;
   for the immediate forms it reads $007F (ADC) or $0000 (SBC), as the
   Appletini core and the SingleStepTests set do. It is the core's
   ST_DECIMAL_EXTRA, a data_ea state in both forms (w65c02_core.sv:1049-1052,
   :1154-1156). */
#define DECIMAL_CYCLE(address) \
    do { if (cpu->p & CPU65C02_D) DUMMY_EA(address); } while (0)

/* ---- read-modify-write ---- */

static inline uint8_t C02_F(asl_)(cpu65c02 *cpu, uint8_t m)
{
    SET_FLAG(CPU65C02_C, m & 0x80);
    m = (uint8_t)(m << 1);
    SET_NZ(m);
    return m;
}

static inline uint8_t C02_F(lsr_)(cpu65c02 *cpu, uint8_t m)
{
    SET_FLAG(CPU65C02_C, m & 0x01);
    m = (uint8_t)(m >> 1);
    SET_NZ(m);
    return m;
}

static inline uint8_t C02_F(rol_)(cpu65c02 *cpu, uint8_t m)
{
    uint8_t carry = cpu->p & CPU65C02_C;
    SET_FLAG(CPU65C02_C, m & 0x80);
    m = (uint8_t)(m << 1 | carry);
    SET_NZ(m);
    return m;
}

static inline uint8_t C02_F(ror_)(cpu65c02 *cpu, uint8_t m)
{
    uint8_t carry = cpu->p & CPU65C02_C;
    SET_FLAG(CPU65C02_C, m & 0x01);
    m = (uint8_t)(m >> 1 | carry << 7);
    SET_NZ(m);
    return m;
}

static inline uint8_t C02_F(inc_)(cpu65c02 *cpu, uint8_t m)
{
    m++;
    SET_NZ(m);
    return m;
}

static inline uint8_t C02_F(dec_)(cpu65c02 *cpu, uint8_t m)
{
    m--;
    SET_NZ(m);
    return m;
}

static inline uint8_t C02_F(tsb_)(cpu65c02 *cpu, uint8_t m)
{
    SET_FLAG(CPU65C02_Z, !(m & cpu->a));
    return (uint8_t)(m | cpu->a);
}

static inline uint8_t C02_F(trb_)(cpu65c02 *cpu, uint8_t m)
{
    SET_FLAG(CPU65C02_Z, !(m & cpu->a));
    return (uint8_t)(m & ~cpu->a);
}

/* Read, read again (the 65C02 does not write the old value back), then
   write: three cycles at the effective address, the core's ST_RMW_READ,
   ST_RMW_MODIFY and ST_RMW_WRITE. */
#define RMW(address_expression, operation) \
    do { \
        uint16_t ea_ = address_expression; \
        uint8_t m_ = RD(ea_, EA); \
        DUMMY_EA(ea_); \
        m_ = C02_F(operation)(cpu, m_); \
        WR(ea_, m_, EA); \
    } while (0)

/* RMB and SMB: the same cycles as the other zero-page read-modify-writes. */
#define BIT_RMW(set, bit) \
    do { \
        uint16_t ea_ = ZP(); \
        uint8_t m_ = RD(ea_, EA); \
        DUMMY_EA(ea_); \
        m_ = (uint8_t)((set) ? m_ | 1u << (bit) : m_ & ~(1u << (bit))); \
        WR(ea_, m_, EA); \
    } while (0)

/* ---- branches ---- */

/* A taken branch reads the next instruction's address; a page crossing
   adds a read of the target's low byte in the old page. */
static inline void C02_F(branch_to_)(cpu65c02 *cpu, uint8_t offset)
{
    uint16_t target = (uint16_t)(cpu->pc + (int8_t)offset);
    DUMMY(cpu->pc);
    if ((target ^ cpu->pc) & 0xff00)
        DUMMY((cpu->pc & 0xff00) | (target & 0x00ff));
    cpu->pc = target;
}

#define BRANCH(condition) \
    do { \
        uint8_t offset_ = OPERAND(); \
        if (condition) \
            C02_F(branch_to_)(cpu, offset_); \
    } while (0)

/* BBR and BBS: the zero-page byte is read twice, then the offset. When
   the branch is taken, the extra cycle and the page-crossing one both
   read the next instruction's address. The zero-page reads are the
   core's ST_BIT_BRANCH_READ and ST_BIT_BRANCH_REPEAT, not data_ea. */
#define BIT_BRANCH(set, bit) \
    do { \
        uint16_t ea_ = ZP(); \
        uint8_t m_ = RD(ea_, DATA), offset_; \
        DUMMY(ea_); \
        offset_ = OPERAND(); \
        if (((m_ >> (bit)) & 1) == (set)) { \
            uint16_t target_ = (uint16_t)(cpu->pc + (int8_t)offset_); \
            DUMMY(cpu->pc); \
            if ((target_ ^ cpu->pc) & 0xff00) \
                DUMMY(cpu->pc); \
            cpu->pc = target_; \
        } \
    } while (0)

/* ---- stack ---- */

static inline void C02_F(push_)(cpu65c02 *cpu, uint8_t value)
{
    WR(0x0100 | cpu->s, value, DATA);
    cpu->s--;
}

static inline uint8_t C02_F(pull_)(cpu65c02 *cpu)
{
    cpu->s++;
    return RD(0x0100 | cpu->s, DATA);
}

#define PUSH(value) C02_F(push_)(cpu, (uint8_t)(value))
#define PULL() C02_F(pull_)(cpu)

/* PHA and the like: a read of the next byte, then the push. */
#define PUSH_OP(value) do { DUMMY(cpu->pc); PUSH(value); } while (0)
/* PLA and the like: reads of the next byte and of the stack top, then
   the pull. */
#define PULL_OP(target) \
    do { DUMMY(cpu->pc); DUMMY(0x0100 | cpu->s); target = PULL(); } while (0)

/* ---- interrupts ---- */

/* Push PC and P, then load PC from `vector`; I is set and D cleared
   (table 7-1). Five cycles. */
static inline void C02_F(enter_)(cpu65c02 *cpu, uint8_t pushed_p,
                                 uint16_t vector)
{
    uint16_t low;
    PUSH(cpu->pc >> 8);
    PUSH(cpu->pc);
    PUSH(pushed_p);
    cpu->p = (uint8_t)((cpu->p | CPU65C02_I) & ~CPU65C02_D);
    low = RD(vector, DATA);
    cpu->pc = (uint16_t)(low | RD((uint16_t)(vector + 1), DATA) << 8);
}

/* IRQ or NMI: the cycle after the discarded opcode fetch also reads PC,
   then the five of enter_. An NMI wins over an IRQ. */
static inline void C02_F(interrupt_)(cpu65c02 *cpu)
{
    uint16_t vector = cpu->nmi_pending ? 0xfffa : 0xfffe;
    cpu->nmi_pending = 0;
    DUMMY(cpu->pc);
    C02_F(enter_)(cpu, (uint8_t)((cpu->p | CPU65C02_U) & ~CPU65C02_B),
                  vector);
}

static inline int C02_F(interrupt_due_)(const cpu65c02 *cpu)
{
    return cpu->nmi_pending ||
           (cpu->irq_sources && !(cpu->p & CPU65C02_I));
}

/* ---- one instruction ---- */

/* Everything but the waiting and stopped states. The interrupt lines
   are sampled at the opcode fetch with the flags as the previous
   instruction left them, as the Appletini core does. */
static inline void C02_F(execute_)(cpu65c02 *cpu)
{
    uint8_t opcode;

    if (C02_F(interrupt_due_)(cpu)) {
        DUMMY(cpu->pc);                 /* the fetch, discarded */
        C02_F(interrupt_)(cpu);
        return;
    }
    opcode = RD(cpu->pc, CPU65C02_OPCODE);
    cpu->pc++;

    switch (opcode) {
    /* loads */
    case 0xa9: cpu->a = OPERAND(); SET_NZ(cpu->a); break;
    case 0xa5: cpu->a = RD(ZP(), EA); SET_NZ(cpu->a); break;
    case 0xb5: cpu->a = RD(ZPX(), EA); SET_NZ(cpu->a); break;
    case 0xad: cpu->a = RD(ABS(), EA); SET_NZ(cpu->a); break;
    case 0xbd: cpu->a = RD(ABSX_R(), EA); SET_NZ(cpu->a); break;
    case 0xb9: cpu->a = RD(ABSY_R(), EA); SET_NZ(cpu->a); break;
    case 0xa1: cpu->a = RD(INDX(), EA); SET_NZ(cpu->a); break;
    case 0xb1: cpu->a = RD(INDY_R(), EA); SET_NZ(cpu->a); break;
    case 0xb2: cpu->a = RD(IND(), EA); SET_NZ(cpu->a); break;
    case 0xa2: cpu->x = OPERAND(); SET_NZ(cpu->x); break;
    case 0xa6: cpu->x = RD(ZP(), EA); SET_NZ(cpu->x); break;
    case 0xb6: cpu->x = RD(ZPY(), EA); SET_NZ(cpu->x); break;
    case 0xae: cpu->x = RD(ABS(), EA); SET_NZ(cpu->x); break;
    case 0xbe: cpu->x = RD(ABSY_R(), EA); SET_NZ(cpu->x); break;
    case 0xa0: cpu->y = OPERAND(); SET_NZ(cpu->y); break;
    case 0xa4: cpu->y = RD(ZP(), EA); SET_NZ(cpu->y); break;
    case 0xb4: cpu->y = RD(ZPX(), EA); SET_NZ(cpu->y); break;
    case 0xac: cpu->y = RD(ABS(), EA); SET_NZ(cpu->y); break;
    case 0xbc: cpu->y = RD(ABSX_R(), EA); SET_NZ(cpu->y); break;

    /* stores */
    case 0x85: WR(ZP(), cpu->a, EA); break;
    case 0x95: WR(ZPX(), cpu->a, EA); break;
    case 0x8d: WR(ABS(), cpu->a, EA); break;
    case 0x9d: WR(C02_F(abs_indexed_)(cpu, cpu->x, 1, 1), cpu->a, EA); break;
    case 0x99: WR(C02_F(abs_indexed_)(cpu, cpu->y, 1, 1), cpu->a, EA); break;
    case 0x81: WR(INDX(), cpu->a, EA); break;
    case 0x91: WR(C02_F(indirect_indexed_)(cpu, 1), cpu->a, EA); break;
    case 0x92: WR(IND(), cpu->a, EA); break;
    case 0x86: WR(ZP(), cpu->x, EA); break;
    case 0x96: WR(ZPY(), cpu->x, EA); break;
    case 0x8e: WR(ABS(), cpu->x, EA); break;
    case 0x84: WR(ZP(), cpu->y, EA); break;
    case 0x94: WR(ZPX(), cpu->y, EA); break;
    case 0x8c: WR(ABS(), cpu->y, EA); break;
    case 0x64: WR(ZP(), 0, EA); break;
    case 0x74: WR(ZPX(), 0, EA); break;
    case 0x9c: WR(ABS(), 0, EA); break;
    case 0x9e: WR(C02_F(abs_indexed_)(cpu, cpu->x, 1, 0), 0, EA); break;

    /* logic */
#define LOGIC(base, op) \
    case base + 0x08: cpu->a op OPERAND(); SET_NZ(cpu->a); break; \
    case base + 0x04: cpu->a op RD(ZP(), EA); SET_NZ(cpu->a); break; \
    case base + 0x14: cpu->a op RD(ZPX(), EA); SET_NZ(cpu->a); break; \
    case base + 0x0c: cpu->a op RD(ABS(), EA); SET_NZ(cpu->a); break; \
    case base + 0x1c: cpu->a op RD(ABSX_R(), EA); SET_NZ(cpu->a); break; \
    case base + 0x18: cpu->a op RD(ABSY_R(), EA); SET_NZ(cpu->a); break; \
    case base + 0x00: cpu->a op RD(INDX(), EA); SET_NZ(cpu->a); break; \
    case base + 0x10: cpu->a op RD(INDY_R(), EA); SET_NZ(cpu->a); break; \
    case base + 0x11: cpu->a op RD(IND(), EA); SET_NZ(cpu->a); break;
    LOGIC(0x01, |=)
    LOGIC(0x21, &=)
    LOGIC(0x41, ^=)
#undef LOGIC

    /* arithmetic */
#define ARITH(base, fn, immediate_cycle) \
    case base + 0x08: C02_F(fn)(cpu, OPERAND()); \
        DECIMAL_CYCLE(immediate_cycle); break; \
    case base + 0x04: { uint16_t ea = ZP(); C02_F(fn)(cpu, RD(ea, EA)); \
        DECIMAL_CYCLE(ea); break; } \
    case base + 0x14: { uint16_t ea = ZPX(); C02_F(fn)(cpu, RD(ea, EA)); \
        DECIMAL_CYCLE(ea); break; } \
    case base + 0x0c: { uint16_t ea = ABS(); C02_F(fn)(cpu, RD(ea, EA)); \
        DECIMAL_CYCLE(ea); break; } \
    case base + 0x1c: { uint16_t ea = ABSX_R(); \
        C02_F(fn)(cpu, RD(ea, EA)); DECIMAL_CYCLE(ea); break; } \
    case base + 0x18: { uint16_t ea = ABSY_R(); \
        C02_F(fn)(cpu, RD(ea, EA)); DECIMAL_CYCLE(ea); break; } \
    case base + 0x00: { uint16_t ea = INDX(); C02_F(fn)(cpu, RD(ea, EA)); \
        DECIMAL_CYCLE(ea); break; } \
    case base + 0x10: { uint16_t ea = INDY_R(); \
        C02_F(fn)(cpu, RD(ea, EA)); DECIMAL_CYCLE(ea); break; } \
    case base + 0x11: { uint16_t ea = IND(); C02_F(fn)(cpu, RD(ea, EA)); \
        DECIMAL_CYCLE(ea); break; }
    ARITH(0x61, adc_, 0x007f)
    ARITH(0xe1, sbc_, 0x0000)
#undef ARITH

    /* compares */
    case 0xc9: C02_F(compare_)(cpu, cpu->a, OPERAND()); break;
    case 0xc5: C02_F(compare_)(cpu, cpu->a, RD(ZP(), EA)); break;
    case 0xd5: C02_F(compare_)(cpu, cpu->a, RD(ZPX(), EA)); break;
    case 0xcd: C02_F(compare_)(cpu, cpu->a, RD(ABS(), EA)); break;
    case 0xdd: C02_F(compare_)(cpu, cpu->a, RD(ABSX_R(), EA)); break;
    case 0xd9: C02_F(compare_)(cpu, cpu->a, RD(ABSY_R(), EA)); break;
    case 0xc1: C02_F(compare_)(cpu, cpu->a, RD(INDX(), EA)); break;
    case 0xd1: C02_F(compare_)(cpu, cpu->a, RD(INDY_R(), EA)); break;
    case 0xd2: C02_F(compare_)(cpu, cpu->a, RD(IND(), EA)); break;
    case 0xe0: C02_F(compare_)(cpu, cpu->x, OPERAND()); break;
    case 0xe4: C02_F(compare_)(cpu, cpu->x, RD(ZP(), EA)); break;
    case 0xec: C02_F(compare_)(cpu, cpu->x, RD(ABS(), EA)); break;
    case 0xc0: C02_F(compare_)(cpu, cpu->y, OPERAND()); break;
    case 0xc4: C02_F(compare_)(cpu, cpu->y, RD(ZP(), EA)); break;
    case 0xcc: C02_F(compare_)(cpu, cpu->y, RD(ABS(), EA)); break;

    /* BIT: the immediate form changes only Z */
    case 0x89: SET_FLAG(CPU65C02_Z, !(cpu->a & OPERAND())); break;
#define BIT(expression) \
    do { \
        uint8_t m_ = RD(expression, EA); \
        cpu->p = (uint8_t)((cpu->p & ~(CPU65C02_N | CPU65C02_V | \
                                       CPU65C02_Z)) | \
                           (m_ & (CPU65C02_N | CPU65C02_V)) | \
                           ((m_ & cpu->a) ? 0 : CPU65C02_Z)); \
    } while (0)
    case 0x24: BIT(ZP()); break;
    case 0x34: BIT(ZPX()); break;
    case 0x2c: BIT(ABS()); break;
    case 0x3c: BIT(ABSX_R()); break;
#undef BIT

    /* shifts and rotates */
#define SHIFT(base, fn) \
    case base + 0x04: cpu->a = C02_F(fn)(cpu, cpu->a); DUMMY(cpu->pc); break; \
    case base + 0x00: RMW(ZP(), fn); break; \
    case base + 0x10: RMW(ZPX(), fn); break; \
    case base + 0x08: RMW(ABS(), fn); break; \
    case base + 0x18: RMW(C02_F(abs_indexed_)(cpu, cpu->x, 0, 0), fn); break;
    SHIFT(0x06, asl_)
    SHIFT(0x26, rol_)
    SHIFT(0x46, lsr_)
    SHIFT(0x66, ror_)
#undef SHIFT

    /* increments and decrements */
    case 0x1a: cpu->a++; SET_NZ(cpu->a); DUMMY(cpu->pc); break;
    case 0x3a: cpu->a--; SET_NZ(cpu->a); DUMMY(cpu->pc); break;
    case 0xe6: RMW(ZP(), inc_); break;
    case 0xf6: RMW(ZPX(), inc_); break;
    case 0xee: RMW(ABS(), inc_); break;
    case 0xfe: RMW(C02_F(abs_indexed_)(cpu, cpu->x, 1, 0), inc_); break;
    case 0xc6: RMW(ZP(), dec_); break;
    case 0xd6: RMW(ZPX(), dec_); break;
    case 0xce: RMW(ABS(), dec_); break;
    case 0xde: RMW(C02_F(abs_indexed_)(cpu, cpu->x, 1, 0), dec_); break;
    case 0xe8: cpu->x++; SET_NZ(cpu->x); DUMMY(cpu->pc); break;
    case 0xca: cpu->x--; SET_NZ(cpu->x); DUMMY(cpu->pc); break;
    case 0xc8: cpu->y++; SET_NZ(cpu->y); DUMMY(cpu->pc); break;
    case 0x88: cpu->y--; SET_NZ(cpu->y); DUMMY(cpu->pc); break;

    /* TSB, TRB, RMB, SMB */
    case 0x04: RMW(ZP(), tsb_); break;
    case 0x0c: RMW(ABS(), tsb_); break;
    case 0x14: RMW(ZP(), trb_); break;
    case 0x1c: RMW(ABS(), trb_); break;
    case 0x07: BIT_RMW(0, 0); break;
    case 0x17: BIT_RMW(0, 1); break;
    case 0x27: BIT_RMW(0, 2); break;
    case 0x37: BIT_RMW(0, 3); break;
    case 0x47: BIT_RMW(0, 4); break;
    case 0x57: BIT_RMW(0, 5); break;
    case 0x67: BIT_RMW(0, 6); break;
    case 0x77: BIT_RMW(0, 7); break;
    case 0x87: BIT_RMW(1, 0); break;
    case 0x97: BIT_RMW(1, 1); break;
    case 0xa7: BIT_RMW(1, 2); break;
    case 0xb7: BIT_RMW(1, 3); break;
    case 0xc7: BIT_RMW(1, 4); break;
    case 0xd7: BIT_RMW(1, 5); break;
    case 0xe7: BIT_RMW(1, 6); break;
    case 0xf7: BIT_RMW(1, 7); break;

    /* branches */
    case 0x10: BRANCH(!(cpu->p & CPU65C02_N)); break;
    case 0x30: BRANCH(cpu->p & CPU65C02_N); break;
    case 0x50: BRANCH(!(cpu->p & CPU65C02_V)); break;
    case 0x70: BRANCH(cpu->p & CPU65C02_V); break;
    case 0x90: BRANCH(!(cpu->p & CPU65C02_C)); break;
    case 0xb0: BRANCH(cpu->p & CPU65C02_C); break;
    case 0xd0: BRANCH(!(cpu->p & CPU65C02_Z)); break;
    case 0xf0: BRANCH(cpu->p & CPU65C02_Z); break;
    case 0x80: BRANCH(1); break;
    case 0x0f: BIT_BRANCH(0, 0); break;
    case 0x1f: BIT_BRANCH(0, 1); break;
    case 0x2f: BIT_BRANCH(0, 2); break;
    case 0x3f: BIT_BRANCH(0, 3); break;
    case 0x4f: BIT_BRANCH(0, 4); break;
    case 0x5f: BIT_BRANCH(0, 5); break;
    case 0x6f: BIT_BRANCH(0, 6); break;
    case 0x7f: BIT_BRANCH(0, 7); break;
    case 0x8f: BIT_BRANCH(1, 0); break;
    case 0x9f: BIT_BRANCH(1, 1); break;
    case 0xaf: BIT_BRANCH(1, 2); break;
    case 0xbf: BIT_BRANCH(1, 3); break;
    case 0xcf: BIT_BRANCH(1, 4); break;
    case 0xdf: BIT_BRANCH(1, 5); break;
    case 0xef: BIT_BRANCH(1, 6); break;
    case 0xff: BIT_BRANCH(1, 7); break;

    /* jumps */
    case 0x4c: cpu->pc = ABS(); break;
    case 0x6c: {
        /* JMP (a): the pointer's high byte comes from the next address,
           after a read of the address the NMOS chip would use (the
           pointer's page with the low byte incremented): one more cycle
           than the 6502 (table 7-1). The pointer reads are code space
           for the zero-page pair: DATA, not EA. */
        uint16_t pointer = ABS(), low;
        low = RD(pointer, DATA);
        DUMMY((pointer & 0xff00) | ((pointer + 1) & 0x00ff));
        cpu->pc = (uint16_t)(low | RD((uint16_t)(pointer + 1), DATA) << 8);
        break;
    }
    case 0x7c: {
        /* JMP (a,X): the extra cycle reads the operand's first byte. */
        uint16_t pointer = ABS(), low;
        DUMMY(cpu->pc - 2);
        pointer = (uint16_t)(pointer + cpu->x);
        low = RD(pointer, DATA);
        cpu->pc = (uint16_t)(low | RD((uint16_t)(pointer + 1), DATA) << 8);
        break;
    }
    case 0x20: {
        /* JSR: the high byte of the target is read last, after the
           pushes of the address of that byte. */
        uint16_t low = OPERAND();
        DUMMY(0x0100 | cpu->s);
        PUSH(cpu->pc >> 8);
        PUSH(cpu->pc);
        cpu->pc = (uint16_t)(low | RD(cpu->pc, CPU65C02_OPERAND) << 8);
        break;
    }
    case 0x60: {
        uint16_t low;
        DUMMY(cpu->pc);
        DUMMY(0x0100 | cpu->s);
        low = PULL();
        cpu->pc = (uint16_t)(low | PULL() << 8);
        DUMMY(cpu->pc);
        cpu->pc++;
        break;
    }
    case 0x40: {
        uint16_t low;
        DUMMY(cpu->pc);
        DUMMY(0x0100 | cpu->s);
        cpu->p = (uint8_t)((PULL() | CPU65C02_U) & ~CPU65C02_B);
        low = PULL();
        cpu->pc = (uint16_t)(low | PULL() << 8);
        break;
    }
    case 0x00:
        /* BRK: the signature byte is read and skipped. */
        (void)OPERAND();
        C02_F(enter_)(cpu, (uint8_t)(cpu->p | CPU65C02_U | CPU65C02_B),
                      0xfffe);
        break;

    /* stack */
    case 0x48: PUSH_OP(cpu->a); break;
    case 0xda: PUSH_OP(cpu->x); break;
    case 0x5a: PUSH_OP(cpu->y); break;
    case 0x08: PUSH_OP(cpu->p | CPU65C02_U | CPU65C02_B); break;
    case 0x68: PULL_OP(cpu->a); SET_NZ(cpu->a); break;
    case 0xfa: PULL_OP(cpu->x); SET_NZ(cpu->x); break;
    case 0x7a: PULL_OP(cpu->y); SET_NZ(cpu->y); break;
    case 0x28: {
        uint8_t p;
        PULL_OP(p);
        cpu->p = (uint8_t)((p | CPU65C02_U) & ~CPU65C02_B);
        break;
    }

    /* transfers and flags */
    case 0xaa: cpu->x = cpu->a; SET_NZ(cpu->x); DUMMY(cpu->pc); break;
    case 0x8a: cpu->a = cpu->x; SET_NZ(cpu->a); DUMMY(cpu->pc); break;
    case 0xa8: cpu->y = cpu->a; SET_NZ(cpu->y); DUMMY(cpu->pc); break;
    case 0x98: cpu->a = cpu->y; SET_NZ(cpu->a); DUMMY(cpu->pc); break;
    case 0xba: cpu->x = cpu->s; SET_NZ(cpu->x); DUMMY(cpu->pc); break;
    case 0x9a: cpu->s = cpu->x; DUMMY(cpu->pc); break;
    case 0x18: cpu->p &= (uint8_t)~CPU65C02_C; DUMMY(cpu->pc); break;
    case 0x38: cpu->p |= CPU65C02_C; DUMMY(cpu->pc); break;
    case 0x58: cpu->p &= (uint8_t)~CPU65C02_I; DUMMY(cpu->pc); break;
    case 0x78: cpu->p |= CPU65C02_I; DUMMY(cpu->pc); break;
    case 0xb8: cpu->p &= (uint8_t)~CPU65C02_V; DUMMY(cpu->pc); break;
    case 0xd8: cpu->p &= (uint8_t)~CPU65C02_D; DUMMY(cpu->pc); break;
    case 0xf8: cpu->p |= CPU65C02_D; DUMMY(cpu->pc); break;
    case 0xea: DUMMY(cpu->pc); break;

    /* WAI and STP: a read of the next byte, then the state; the waiting
       and stopped cycles are made by step. */
    case 0xcb: DUMMY(cpu->pc); cpu->state = CPU65C02_WAITING; break;
    case 0xdb: DUMMY(cpu->pc); cpu->state = CPU65C02_STOPPED; break;

    /* The reserved opcodes are NOPs (table 7-1). Column 2 takes an
       operand byte in 2 cycles; $44 reads zero page in 3; $54, $D4 and
       $F4 read zp,X in 4; $5C, $DC and $FC take two operand bytes and
       read the last one again, in 4. Columns 3 and B, WAI and STP apart,
       are 1 byte and 1 cycle. */
    case 0x02: case 0x22: case 0x42: case 0x62:
    case 0x82: case 0xc2: case 0xe2:
        (void)OPERAND();
        break;
    case 0x44: (void)RD(ZP(), EA); break;
    case 0x54: case 0xd4: case 0xf4: (void)RD(ZPX(), EA); break;
    case 0x5c: case 0xdc: case 0xfc:
        (void)ABS();
        DUMMY(cpu->pc - 1);
        break;
    default:            /* $x3 and $xB */
        break;
    }
}

/* ---- the entry points ---- */

C02_LINKAGE unsigned C02_F(step)(cpu65c02 *cpu)
{
    uint64_t start = cpu->cycles;

    if (cpu->state == CPU65C02_RUNNING) {
        C02_F(execute_)(cpu);
    } else if (cpu->state == CPU65C02_WAITING) {
        /* One cycle reading PC; at its end an active IRQ or a pending NMI
           ends the wait. With I set an IRQ resumes at the next
           instruction without being taken. */
        DUMMY(cpu->pc);
        if (cpu->nmi_pending || cpu->irq_sources) {
            cpu->state = CPU65C02_RUNNING;
            if (C02_F(interrupt_due_)(cpu))
                C02_F(interrupt_)(cpu);
        }
    } else {
        DUMMY(cpu->pc);
    }
    return (unsigned)(cpu->cycles - start);
}

C02_LINKAGE uint64_t C02_F(run)(cpu65c02 *cpu, uint64_t until)
{
    uint64_t count = 0;

    cpu->until = until;
    while (cpu->cycles < cpu->until) {
        if (cpu->state == CPU65C02_RUNNING)
            C02_F(execute_)(cpu);
        else
            (void)C02_F(step)(cpu);
        count++;
    }
    return count;
}

C02_LINKAGE void C02_F(reset)(cpu65c02 *cpu)
{
    uint16_t low;

    DUMMY(cpu->pc);
    DUMMY(cpu->pc);
    DUMMY(0x0100 | cpu->s);
    cpu->s--;
    DUMMY(0x0100 | cpu->s);
    cpu->s--;
    DUMMY(0x0100 | cpu->s);
    cpu->s--;
    cpu->p = (uint8_t)(((cpu->p | CPU65C02_I | CPU65C02_U) & ~CPU65C02_D) &
                       ~CPU65C02_B);
    cpu->state = CPU65C02_RUNNING;
    cpu->nmi_pending = 0;
    low = RD(0xfffc, DATA);
    cpu->pc = (uint16_t)(low | RD(0xfffd, DATA) << 8);
}

#undef C02_CAT2
#undef C02_CAT
#undef C02_F
#undef RD
#undef WR
#undef DUMMY
#undef DATA
#undef EA
#undef DUMMY_EA
#undef OPERAND
#undef SET_NZ
#undef SET_FLAG
#undef ZP
#undef ZPX
#undef ZPY
#undef ABS
#undef ABSX_R
#undef ABSY_R
#undef INDX
#undef INDY_R
#undef IND
#undef DECIMAL_CYCLE
#undef RMW
#undef BIT_RMW
#undef BRANCH
#undef BIT_BRANCH
#undef PUSH
#undef PULL
#undef PUSH_OP
#undef PULL_OP
