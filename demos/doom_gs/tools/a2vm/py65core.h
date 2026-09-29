/*
 * The compatibility core of a2vm: py65's 65C02 (py65 1.2.0,
 * py65/devices/mpu65c02.py and mpu6502.py), the core of the existing
 * port's model demos/doom/tools/a2sim.py.
 *
 * It is not the W65C02S (that is cpu65c02_core.h). It reproduces what
 * py65 does, so that a run on a2vm matches one on a2sim.py access for
 * access and cycle for cycle:
 *
 *   - the memory accesses py65 makes, in its order: no dummy cycles; a
 *     branch not taken does not read its offset; JSR pushes before it
 *     reads its operand; (zp) reads its pointer's high byte at zp + 1
 *     without wrapping in page zero; read-modify-write instructions read
 *     once and write once;
 *   - py65's cycle table (py65_cycles) plus its extra cycles: taken
 *     branches, page crossings of the instructions py65 marks, all added
 *     after the instruction, so an I/O access sees the clock of the
 *     instruction's start plus the surcharges already added;
 *   - py65's decimal mode (N, Z and V from the binary sum), its flags
 *     (bit 4 of P kept in the register), and the 62 opcodes it leaves
 *     out, two-byte NOPs of 0 cycles;
 *   - WAI waits one cycle a step until the machine delivers an IRQ; STP
 *     is one of the opcodes left out.
 *
 * Include it once in a file that defines, before including:
 *
 *   P65_RD(address)            the bus read (uint16_t address)
 *   P65_WR(address, value)     the bus write
 *
 *   P65_M                      the machine type: a structure with the
 *                              registers `r` (a2vm_py65_regs) and the
 *                              clock `py65_cycles` (uint64_t)
 *
 * It defines p65_step(P65_M *m), one instruction, and p65_irq(P65_M *m),
 * py65's MPU.irq.
 *
 * The two tables below are py65's data. py65's licence, as its LICENSE.txt
 * in the py65 1.2.0 package (py65-1.2.0.dist-info/LICENSE.txt) gives it:
 *
 * BSD 3-Clause License
 *
 * Copyright (c) 2008-2024, Mike Naberezny and contributors.
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * * Redistributions of source code must retain the above copyright notice, this
 *   list of conditions and the following disclaimer.
 *
 * * Redistributions in binary form must reproduce the above copyright notice,
 *   this list of conditions and the following disclaimer in the documentation
 *   and/or other materials provided with the distribution.
 *
 * * Neither the name of the copyright holder nor the names of its
 *   contributors may be used to endorse or promote products derived from
 *   this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 * DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
 * SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
 * CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/* MPU.cycletime of py65's 65C02, by opcode. */
static const uint8_t py65_cycles[256] = {
    7, 6, 0, 0, 5, 3, 5, 5, 3, 2, 2, 0, 6, 4, 6, 0,
    2, 5, 5, 0, 5, 4, 6, 5, 2, 4, 2, 0, 6, 4, 7, 0,
    6, 6, 0, 0, 3, 3, 5, 5, 4, 2, 2, 0, 4, 4, 6, 0,
    2, 5, 5, 0, 4, 4, 6, 5, 2, 4, 2, 0, 4, 4, 7, 0,
    6, 6, 0, 0, 0, 3, 5, 5, 3, 2, 2, 0, 3, 4, 6, 0,
    2, 5, 5, 0, 0, 4, 6, 5, 2, 4, 3, 0, 0, 4, 7, 0,
    6, 6, 0, 0, 3, 3, 5, 5, 4, 2, 2, 0, 6, 4, 6, 0,
    2, 5, 5, 0, 4, 4, 6, 5, 2, 4, 4, 0, 6, 4, 7, 0,
    1, 6, 0, 0, 3, 3, 3, 5, 2, 2, 2, 0, 4, 4, 4, 0,
    2, 6, 5, 0, 4, 4, 4, 5, 2, 5, 2, 0, 4, 5, 5, 0,
    2, 6, 2, 0, 3, 3, 3, 5, 2, 2, 2, 0, 4, 4, 4, 0,
    2, 5, 5, 0, 4, 4, 4, 5, 2, 4, 2, 0, 4, 4, 4, 0,
    2, 6, 0, 0, 3, 3, 5, 5, 2, 2, 2, 3, 4, 4, 3, 0,
    2, 5, 5, 0, 0, 4, 6, 5, 2, 4, 3, 0, 0, 4, 7, 0,
    2, 6, 0, 0, 3, 3, 5, 5, 2, 2, 2, 0, 4, 4, 6, 0,
    2, 5, 5, 0, 0, 4, 6, 5, 2, 4, 4, 0, 0, 4, 7, 0
};

/* MPU.extracycles: nonzero where py65 adds a cycle for a page crossing
   of a,X, a,Y or (zp),Y (the branches add theirs whatever it says). */
static const uint8_t py65_extra[256] = {
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    2, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    2, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    2, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    2, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    2, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 1, 1, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    2, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    2, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0
};

enum {
    P65_C = 0x01, P65_Z = 0x02, P65_I = 0x04, P65_D = 0x08,
    P65_B = 0x10, P65_U = 0x20, P65_V = 0x40, P65_N = 0x80
};

#define R (m->r)

static inline void p65_nz(P65_M *m, uint8_t value)
{
    R.p = (uint8_t)((R.p & ~(P65_N | P65_Z)) |
                    (value ? (value & P65_N) : P65_Z));
}

/* WordAt: two reads, the second at address + 1 (16 bits here; py65
   would index past its memory at $FFFF). */
static inline uint16_t p65_word(P65_M *m, uint16_t address)
{
    uint16_t low = P65_RD(address);
    uint16_t high = P65_RD((uint16_t)(address + 1));
    return (uint16_t)(low | high << 8);
}

/* WrapAt: the second read wraps within the page. */
static inline uint16_t p65_wrap(P65_M *m, uint16_t address)
{
    uint16_t low = P65_RD(address);
    uint16_t high = P65_RD((uint16_t)((address & 0xff00) |
                                      ((address + 1) & 0x00ff)));
    return (uint16_t)(low | high << 8);
}

static inline void p65_push(P65_M *m, uint8_t value)
{
    P65_WR((uint16_t)(0x100 + R.sp), value);
    R.sp--;
}

static inline uint8_t p65_pop(P65_M *m)
{
    R.sp++;
    return P65_RD((uint16_t)(0x100 + R.sp));
}

static inline void p65_push_word(P65_M *m, uint16_t value)
{
    p65_push(m, (uint8_t)(value >> 8));
    p65_push(m, (uint8_t)value);
}

static inline uint16_t p65_pop_word(P65_M *m)
{
    uint16_t low = p65_pop(m);
    uint16_t high = p65_pop(m);
    return (uint16_t)(low | high << 8);
}

/* AbsoluteXAddr and AbsoluteYAddr */
static inline uint16_t p65_abs_indexed(P65_M *m, uint8_t index, int add,
                                       unsigned *extra)
{
    uint16_t base = p65_word(m, R.pc);
    uint16_t address = (uint16_t)(base + index);
    if (add && ((base ^ address) & 0xff00))
        (*extra)++;
    return address;
}

/* IndirectYAddr */
static inline uint16_t p65_indirect_y(P65_M *m, int add, unsigned *extra)
{
    uint16_t base = p65_wrap(m, P65_RD(R.pc));
    uint16_t address = (uint16_t)(base + R.y);
    if (add && ((base ^ address) & 0xff00))
        (*extra)++;
    return address;
}

/* IndirectXAddr */
static inline uint16_t p65_indirect_x(P65_M *m)
{
    uint8_t pointer = (uint8_t)(P65_RD(R.pc) + R.x);
    return p65_wrap(m, pointer);
}

/* ZeroPageIndirectAddr: WordAt(zp), so $FF reads $FF and $100. */
static inline uint16_t p65_zp_indirect(P65_M *m)
{
    uint16_t pointer = P65_RD(R.pc);
    return p65_word(m, pointer);
}

/* BranchRelAddr */
static inline void p65_branch(P65_M *m, unsigned *extra)
{
    (*extra)++;
    uint8_t offset = P65_RD(R.pc);
    R.pc++;
    uint16_t target = (uint16_t)(R.pc + (int8_t)offset);
    if ((R.pc ^ target) & 0xff00)
        (*extra)++;
    R.pc = target;
}

static inline void p65_adc(P65_M *m, uint8_t data)
{
    unsigned a = R.a, carry = R.p & P65_C;
    if (R.p & P65_D) {
        unsigned half = 0, decimal = 0, adjust0 = 0, adjust1 = 0;
        unsigned nibble0 = (data & 0xf) + (a & 0xf) + carry;
        if (nibble0 > 9) {
            adjust0 = 6;
            half = 1;
        }
        unsigned nibble1 = ((data >> 4) & 0xf) + ((a >> 4) & 0xf) + half;
        if (nibble1 > 9) {
            adjust1 = 6;
            decimal = 1;
        }
        nibble0 &= 0xf;
        nibble1 &= 0xf;
        unsigned alu = (nibble1 << 4) + nibble0;
        nibble0 = (nibble0 + adjust0) & 0xf;
        nibble1 = (nibble1 + adjust1) & 0xf;
        R.p &= (uint8_t)~(P65_C | P65_V | P65_N | P65_Z);
        R.p |= alu == 0 ? P65_Z : (alu & P65_N);
        if (decimal)
            R.p |= P65_C;
        if ((~(a ^ data) & (a ^ alu)) & 0x80)
            R.p |= P65_V;
        R.a = (uint8_t)((nibble1 << 4) + nibble0);
    } else {
        unsigned result = data + a + carry;
        R.p &= (uint8_t)~(P65_C | P65_V | P65_N | P65_Z);
        if ((~(a ^ data) & (a ^ result)) & 0x80)
            R.p |= P65_V;
        if (result > 0xff)
            R.p |= P65_C;
        result &= 0xff;
        R.p |= result == 0 ? P65_Z : (result & P65_N);
        R.a = (uint8_t)result;
    }
}

static inline void p65_sbc(P65_M *m, uint8_t data)
{
    unsigned a = R.a, carry = R.p & P65_C;
    if (R.p & P65_D) {
        unsigned half = 1, decimal = 0, adjust0 = 0, adjust1 = 0;
        unsigned nibble0 = (a & 0xf) + (~data & 0xf) + carry;
        if (nibble0 <= 0xf) {
            half = 0;
            adjust0 = 10;
        }
        unsigned nibble1 = ((a >> 4) & 0xf) + ((~(unsigned)data >> 4) & 0xf) +
                           half;
        if (nibble1 <= 0xf)
            adjust1 = 10 << 4;
        unsigned alu = a + (~data & 0xffu) + carry;
        if (alu > 0xff)
            decimal = 1;
        alu &= 0xff;
        nibble0 = (alu + adjust0) & 0xf;
        nibble1 = ((alu + adjust1) >> 4) & 0xf;
        R.p &= (uint8_t)~(P65_C | P65_Z | P65_N | P65_V);
        R.p |= alu == 0 ? P65_Z : (alu & P65_N);
        if (decimal)
            R.p |= P65_C;
        if (((a ^ data) & (a ^ alu)) & 0x80)
            R.p |= P65_V;
        R.a = (uint8_t)((nibble1 << 4) + nibble0);
    } else {
        unsigned result = a + (~data & 0xffu) + carry;
        R.p &= (uint8_t)~(P65_C | P65_Z | P65_V | P65_N);
        if (((a ^ data) & (a ^ result)) & 0x80)
            R.p |= P65_V;
        unsigned value = result & 0xff;
        if (value == 0)
            R.p |= P65_Z;
        if (result > 0xff)
            R.p |= P65_C;
        R.p |= value & P65_N;
        R.a = (uint8_t)value;
    }
}

static inline void p65_compare(P65_M *m, uint8_t reg, uint8_t data)
{
    R.p &= (uint8_t)~(P65_C | P65_Z | P65_N);
    if (reg == data)
        R.p |= P65_C | P65_Z;
    else if (reg > data)
        R.p |= P65_C;
    R.p |= (uint8_t)(reg - data) & P65_N;
}

static inline void p65_bit(P65_M *m, uint8_t data)
{
    R.p &= (uint8_t)~(P65_Z | P65_N | P65_V);
    if ((R.a & data) == 0)
        R.p |= P65_Z;
    R.p |= data & (P65_N | P65_V);
}

static inline uint8_t p65_asl(P65_M *m, uint8_t t)
{
    R.p &= (uint8_t)~(P65_C | P65_N | P65_Z);
    if (t & 0x80)
        R.p |= P65_C;
    t = (uint8_t)(t << 1);
    R.p |= t ? (t & P65_N) : P65_Z;
    return t;
}

static inline uint8_t p65_lsr(P65_M *m, uint8_t t)
{
    R.p &= (uint8_t)~(P65_C | P65_N | P65_Z);
    R.p |= t & 1;
    t >>= 1;
    if (!t)
        R.p |= P65_Z;
    return t;
}

static inline uint8_t p65_rol(P65_M *m, uint8_t t)
{
    unsigned carry = R.p & P65_C;
    R.p = (uint8_t)((R.p & ~P65_C) | (t >> 7));
    t = (uint8_t)(t << 1 | carry);
    p65_nz(m, t);
    return t;
}

static inline uint8_t p65_ror(P65_M *m, uint8_t t)
{
    unsigned carry = R.p & P65_C;
    R.p = (uint8_t)((R.p & ~P65_C) | (t & 1));
    t = (uint8_t)(t >> 1 | carry << 7);
    p65_nz(m, t);
    return t;
}

static inline uint8_t p65_inc(P65_M *m, uint8_t t)
{
    t++;
    p65_nz(m, t);
    return t;
}

static inline uint8_t p65_dec(P65_M *m, uint8_t t)
{
    t--;
    p65_nz(m, t);
    return t;
}

/* MPU.irq, which the machine calls only with I clear; the machine then
   clears D (a2sim.Machine._interrupt). */
static void p65_irq(P65_M *m)
{
    if (R.p & P65_I)
        return;
    p65_push_word(m, R.pc);
    R.p &= (uint8_t)~P65_B;
    p65_push(m, R.p | P65_U);
    R.p |= P65_I;
    R.pc = p65_word(m, 0xfffe);
    m->py65_cycles += 7;
}

/* Addressing, as py65 computes the effective address from R.pc (the
   first operand byte). */
#define A_ZP()   ((uint16_t)P65_RD(R.pc))
#define A_ZPX()  ((uint16_t)((R.x + P65_RD(R.pc)) & 0xff))
#define A_ZPY()  ((uint16_t)((R.y + P65_RD(R.pc)) & 0xff))
#define A_ABS()  p65_word(m, R.pc)
#define A_ABSX() p65_abs_indexed(m, R.x, add, &extra)
#define A_ABSY() p65_abs_indexed(m, R.y, add, &extra)
#define A_INDX() p65_indirect_x(m)
#define A_INDY() p65_indirect_y(m, add, &extra)
#define A_ZPI()  p65_zp_indirect(m)
#define A_IMM()  (R.pc)

/* One operand read then the operation. `bytes` is what py65 adds to PC
   after the instruction (1 or 2). */
#define LOAD(reg, mode, bytes) \
    do { uint16_t ea_ = mode; uint8_t v_ = P65_RD(ea_); reg = v_; \
         p65_nz(m, v_); R.pc += bytes; } while (0)
#define LOGIC(op, mode, bytes) \
    do { uint16_t ea_ = mode; uint8_t v_ = P65_RD(ea_); \
         R.a = (uint8_t)(R.a op v_); p65_nz(m, R.a); R.pc += bytes; } while (0)
#define ARITH(fn, mode, bytes) \
    do { uint16_t ea_ = mode; uint8_t v_ = P65_RD(ea_); fn(m, v_); \
         R.pc += bytes; } while (0)
#define COMPARE(reg, mode, bytes) \
    do { uint16_t ea_ = mode; uint8_t v_ = P65_RD(ea_); \
         p65_compare(m, reg, v_); R.pc += bytes; } while (0)
#define BIT(mode, bytes) \
    do { uint16_t ea_ = mode; uint8_t v_ = P65_RD(ea_); p65_bit(m, v_); \
         R.pc += bytes; } while (0)
#define STORE(value, mode, bytes) \
    do { uint16_t ea_ = mode; P65_WR(ea_, value); R.pc += bytes; } while (0)
#define RMW(fn, mode, bytes) \
    do { uint16_t ea_ = mode; uint8_t v_ = P65_RD(ea_); v_ = fn(m, v_); \
         P65_WR(ea_, v_); R.pc += bytes; } while (0)
#define BITMOD(mask, set) \
    do { uint16_t ea_ = A_ZP(); uint8_t v_ = P65_RD(ea_); \
         v_ = (uint8_t)((set) ? v_ | (mask) : v_ & (mask)); \
         P65_WR(ea_, v_); R.pc += 1; } while (0)
#define TSB_TRB(mode, bytes, set) \
    do { uint16_t ea_ = mode; uint8_t v_ = P65_RD(ea_); \
         R.p &= (uint8_t)~P65_Z; if (!(v_ & R.a)) R.p |= P65_Z; \
         P65_WR(ea_, (set) ? (uint8_t)(v_ | R.a) : (uint8_t)(v_ & ~R.a)); \
         R.pc += bytes; } while (0)
#define BRANCH_IF(condition) \
    do { if (condition) p65_branch(m, &extra); else R.pc += 1; } while (0)

/* MPU65C02.step. Returns the opcode. */
static inline uint8_t p65_step(P65_M *m)
{
    if (R.waiting) {
        m->py65_cycles += 1;
        return 0xcb;
    }
    uint8_t opcode = P65_RD(R.pc);
    R.pc++;
    unsigned extra = 0;
    int add = py65_extra[opcode];

    switch (opcode) {
    case 0x00: {                        /* BRK, the 65C02 version */
        uint16_t pc = (uint16_t)(R.pc + 1);
        p65_push_word(m, pc);
        R.p |= P65_B;
        p65_push(m, R.p | P65_B | P65_U);
        R.p |= P65_I;
        R.pc = p65_word(m, 0xfffe);
        R.p &= (uint8_t)~P65_D;
        break;
    }
    case 0x01: LOGIC(|, A_INDX(), 1); break;
    case 0x04: TSB_TRB(A_ZP(), 1, 1); break;
    case 0x05: LOGIC(|, A_ZP(), 1); break;
    case 0x06: RMW(p65_asl, A_ZP(), 1); break;
    case 0x07: BITMOD(0xfe, 0); break;
    case 0x08: p65_push(m, R.p | P65_B | P65_U); break;
    case 0x09: LOGIC(|, A_IMM(), 1); break;
    case 0x0a: R.a = p65_asl(m, R.a); break;
    case 0x0c: TSB_TRB(A_ABS(), 2, 1); break;
    case 0x0d: LOGIC(|, A_ABS(), 2); break;
    case 0x0e: RMW(p65_asl, A_ABS(), 2); break;
    case 0x10: BRANCH_IF(!(R.p & P65_N)); break;
    case 0x11: LOGIC(|, A_INDY(), 1); break;
    case 0x12: LOGIC(|, A_ZPI(), 1); break;
    case 0x14: TSB_TRB(A_ZP(), 1, 0); break;
    case 0x15: LOGIC(|, A_ZPX(), 1); break;
    case 0x16: RMW(p65_asl, A_ZPX(), 1); break;
    case 0x17: BITMOD(0xfd, 0); break;
    case 0x18: R.p &= (uint8_t)~P65_C; break;
    case 0x19: LOGIC(|, A_ABSY(), 2); break;
    case 0x1a: R.a = p65_inc(m, R.a); break;
    case 0x1c: TSB_TRB(A_ABS(), 2, 0); break;
    case 0x1d: LOGIC(|, A_ABSX(), 2); break;
    case 0x1e: RMW(p65_asl, A_ABSX(), 2); break;
    case 0x20: {                        /* JSR: push, then read */
        p65_push_word(m, (uint16_t)(R.pc + 1));
        R.pc = p65_word(m, R.pc);
        break;
    }
    case 0x21: LOGIC(&, A_INDX(), 1); break;
    case 0x24: BIT(A_ZP(), 1); break;
    case 0x25: LOGIC(&, A_ZP(), 1); break;
    case 0x26: RMW(p65_rol, A_ZP(), 1); break;
    case 0x27: BITMOD(0xfb, 0); break;
    case 0x28: R.p = (uint8_t)(p65_pop(m) | P65_B | P65_U); break;
    case 0x29: LOGIC(&, A_IMM(), 1); break;
    case 0x2a: R.a = p65_rol(m, R.a); break;
    case 0x2c: BIT(A_ABS(), 2); break;
    case 0x2d: LOGIC(&, A_ABS(), 2); break;
    case 0x2e: RMW(p65_rol, A_ABS(), 2); break;
    case 0x30: BRANCH_IF(R.p & P65_N); break;
    case 0x31: LOGIC(&, A_INDY(), 1); break;
    case 0x32: LOGIC(&, A_ZPI(), 1); break;
    case 0x34: BIT(A_ZPX(), 1); break;
    case 0x35: LOGIC(&, A_ZPX(), 1); break;
    case 0x36: RMW(p65_rol, A_ZPX(), 1); break;
    case 0x37: BITMOD(0xf7, 0); break;
    case 0x38: R.p |= P65_C; break;
    case 0x39: LOGIC(&, A_ABSY(), 2); break;
    case 0x3a: R.a = p65_dec(m, R.a); break;
    case 0x3c: BIT(A_ABSX(), 2); break;
    case 0x3d: LOGIC(&, A_ABSX(), 2); break;
    case 0x3e: RMW(p65_rol, A_ABSX(), 2); break;
    case 0x40: {
        R.p = (uint8_t)(p65_pop(m) | P65_B | P65_U);
        R.pc = p65_pop_word(m);
        break;
    }
    case 0x41: LOGIC(^, A_INDX(), 1); break;
    case 0x45: LOGIC(^, A_ZP(), 1); break;
    case 0x46: RMW(p65_lsr, A_ZP(), 1); break;
    case 0x47: BITMOD(0xef, 0); break;
    case 0x48: p65_push(m, R.a); break;
    case 0x49: LOGIC(^, A_IMM(), 1); break;
    case 0x4a: R.a = p65_lsr(m, R.a); break;
    case 0x4c: R.pc = p65_word(m, R.pc); break;
    case 0x4d: LOGIC(^, A_ABS(), 2); break;
    case 0x4e: RMW(p65_lsr, A_ABS(), 2); break;
    case 0x50: BRANCH_IF(!(R.p & P65_V)); break;
    case 0x51: LOGIC(^, A_INDY(), 1); break;
    case 0x52: LOGIC(^, A_ZPI(), 1); break;
    case 0x55: LOGIC(^, A_ZPX(), 1); break;
    case 0x56: RMW(p65_lsr, A_ZPX(), 1); break;
    case 0x57: BITMOD(0xdf, 0); break;
    case 0x58: R.p &= (uint8_t)~P65_I; break;
    case 0x59: LOGIC(^, A_ABSY(), 2); break;
    case 0x5a: p65_push(m, R.y); break;
    case 0x5d: LOGIC(^, A_ABSX(), 2); break;
    case 0x5e: RMW(p65_lsr, A_ABSX(), 2); break;
    case 0x60: R.pc = (uint16_t)(p65_pop_word(m) + 1); break;
    case 0x61: ARITH(p65_adc, A_INDX(), 1); break;
    case 0x64: STORE(0, A_ZP(), 1); break;
    case 0x65: ARITH(p65_adc, A_ZP(), 1); break;
    case 0x66: RMW(p65_ror, A_ZP(), 1); break;
    case 0x67: BITMOD(0xbf, 0); break;
    case 0x68: R.a = p65_pop(m); p65_nz(m, R.a); break;
    case 0x69: ARITH(p65_adc, A_IMM(), 1); break;
    case 0x6a: R.a = p65_ror(m, R.a); break;
    case 0x6c: {                        /* JMP (a), the 65C02 version */
        uint16_t pointer = p65_word(m, R.pc);
        R.pc = p65_word(m, pointer);
        break;
    }
    case 0x6d: ARITH(p65_adc, A_ABS(), 2); break;
    case 0x6e: RMW(p65_ror, A_ABS(), 2); break;
    case 0x70: BRANCH_IF(R.p & P65_V); break;
    case 0x71: ARITH(p65_adc, A_INDY(), 1); break;
    case 0x72: ARITH(p65_adc, A_ZPI(), 1); break;
    case 0x74: STORE(0, A_ZPX(), 1); break;
    case 0x75: ARITH(p65_adc, A_ZPX(), 1); break;
    case 0x76: RMW(p65_ror, A_ZPX(), 1); break;
    case 0x77: BITMOD(0x7f, 0); break;
    case 0x78: R.p |= P65_I; break;
    case 0x79: ARITH(p65_adc, A_ABSY(), 2); break;
    case 0x7a: R.y = p65_pop(m); p65_nz(m, R.y); break;
    case 0x7c: {                        /* JMP (a,X) */
        uint16_t pointer = (uint16_t)(p65_word(m, R.pc) + R.x);
        R.pc = p65_word(m, pointer);
        break;
    }
    case 0x7d: ARITH(p65_adc, A_ABSX(), 2); break;
    case 0x7e: RMW(p65_ror, A_ABSX(), 2); break;
    case 0x80: p65_branch(m, &extra); break;
    case 0x81: STORE(R.a, A_INDX(), 1); break;
    case 0x84: STORE(R.y, A_ZP(), 1); break;
    case 0x85: STORE(R.a, A_ZP(), 1); break;
    case 0x86: STORE(R.x, A_ZP(), 1); break;
    case 0x87: BITMOD(0x01, 1); break;
    case 0x88: R.y--; p65_nz(m, R.y); break;
    case 0x89: {                        /* BIT #: Z only */
        uint8_t v = P65_RD(R.pc);
        R.p &= (uint8_t)~P65_Z;
        if (!(R.a & v))
            R.p |= P65_Z;
        R.pc += 1;
        break;
    }
    case 0x8a: R.a = R.x; p65_nz(m, R.a); break;
    case 0x8c: STORE(R.y, A_ABS(), 2); break;
    case 0x8d: STORE(R.a, A_ABS(), 2); break;
    case 0x8e: STORE(R.x, A_ABS(), 2); break;
    case 0x90: BRANCH_IF(!(R.p & P65_C)); break;
    case 0x91: STORE(R.a, A_INDY(), 1); break;
    case 0x92: STORE(R.a, A_ZPI(), 1); break;
    case 0x94: STORE(R.y, A_ZPX(), 1); break;
    case 0x95: STORE(R.a, A_ZPX(), 1); break;
    case 0x96: STORE(R.x, A_ZPY(), 1); break;
    case 0x97: BITMOD(0x02, 1); break;
    case 0x98: R.a = R.y; p65_nz(m, R.a); break;
    case 0x99: STORE(R.a, A_ABSY(), 2); break;
    case 0x9a: R.sp = R.x; break;
    case 0x9c: STORE(0, A_ABS(), 2); break;
    case 0x9d: STORE(R.a, A_ABSX(), 2); break;
    case 0x9e: STORE(0, A_ABSX(), 2); break;
    case 0xa0: LOAD(R.y, A_IMM(), 1); break;
    case 0xa1: LOAD(R.a, A_INDX(), 1); break;
    case 0xa2: LOAD(R.x, A_IMM(), 1); break;
    case 0xa4: LOAD(R.y, A_ZP(), 1); break;
    case 0xa5: LOAD(R.a, A_ZP(), 1); break;
    case 0xa6: LOAD(R.x, A_ZP(), 1); break;
    case 0xa7: BITMOD(0x04, 1); break;
    case 0xa8: R.y = R.a; p65_nz(m, R.y); break;
    case 0xa9: LOAD(R.a, A_IMM(), 1); break;
    case 0xaa: R.x = R.a; p65_nz(m, R.x); break;
    case 0xac: LOAD(R.y, A_ABS(), 2); break;
    case 0xad: LOAD(R.a, A_ABS(), 2); break;
    case 0xae: LOAD(R.x, A_ABS(), 2); break;
    case 0xb0: BRANCH_IF(R.p & P65_C); break;
    case 0xb1: LOAD(R.a, A_INDY(), 1); break;
    case 0xb2: LOAD(R.a, A_ZPI(), 1); break;
    case 0xb4: LOAD(R.y, A_ZPX(), 1); break;
    case 0xb5: LOAD(R.a, A_ZPX(), 1); break;
    case 0xb6: LOAD(R.x, A_ZPY(), 1); break;
    case 0xb7: BITMOD(0x08, 1); break;
    case 0xb8: R.p &= (uint8_t)~P65_V; break;
    case 0xb9: LOAD(R.a, A_ABSY(), 2); break;
    case 0xba: R.x = R.sp; p65_nz(m, R.x); break;
    case 0xbc: LOAD(R.y, A_ABSX(), 2); break;
    case 0xbd: LOAD(R.a, A_ABSX(), 2); break;
    case 0xbe: LOAD(R.x, A_ABSY(), 2); break;
    case 0xc0: COMPARE(R.y, A_IMM(), 1); break;
    case 0xc1: COMPARE(R.a, A_INDX(), 1); break;
    case 0xc4: COMPARE(R.y, A_ZP(), 1); break;
    case 0xc5: COMPARE(R.a, A_ZP(), 1); break;
    case 0xc6: RMW(p65_dec, A_ZP(), 1); break;
    case 0xc7: BITMOD(0x10, 1); break;
    case 0xc8: R.y++; p65_nz(m, R.y); break;
    case 0xc9: COMPARE(R.a, A_IMM(), 1); break;
    case 0xca: R.x--; p65_nz(m, R.x); break;
    case 0xcb: R.waiting = 1; break;
    case 0xcc: COMPARE(R.y, A_ABS(), 2); break;
    case 0xcd: COMPARE(R.a, A_ABS(), 2); break;
    case 0xce: RMW(p65_dec, A_ABS(), 2); break;
    case 0xd0: BRANCH_IF(!(R.p & P65_Z)); break;
    case 0xd1: COMPARE(R.a, A_INDY(), 1); break;
    case 0xd2: COMPARE(R.a, A_ZPI(), 1); break;
    case 0xd5: COMPARE(R.a, A_ZPX(), 1); break;
    case 0xd6: RMW(p65_dec, A_ZPX(), 1); break;
    case 0xd7: BITMOD(0x20, 1); break;
    case 0xd8: R.p &= (uint8_t)~P65_D; break;
    case 0xd9: COMPARE(R.a, A_ABSY(), 2); break;
    case 0xda: p65_push(m, R.x); break;
    case 0xdd: COMPARE(R.a, A_ABSX(), 2); break;
    case 0xde: RMW(p65_dec, A_ABSX(), 2); break;
    case 0xe0: COMPARE(R.x, A_IMM(), 1); break;
    case 0xe1: ARITH(p65_sbc, A_INDX(), 1); break;
    case 0xe4: COMPARE(R.x, A_ZP(), 1); break;
    case 0xe5: ARITH(p65_sbc, A_ZP(), 1); break;
    case 0xe6: RMW(p65_inc, A_ZP(), 1); break;
    case 0xe7: BITMOD(0x40, 1); break;
    case 0xe8: R.x++; p65_nz(m, R.x); break;
    case 0xe9: ARITH(p65_sbc, A_IMM(), 1); break;
    case 0xea: break;
    case 0xec: COMPARE(R.x, A_ABS(), 2); break;
    case 0xed: ARITH(p65_sbc, A_ABS(), 2); break;
    case 0xee: RMW(p65_inc, A_ABS(), 2); break;
    case 0xf0: BRANCH_IF(R.p & P65_Z); break;
    case 0xf1: ARITH(p65_sbc, A_INDY(), 1); break;
    case 0xf2: ARITH(p65_sbc, A_ZPI(), 1); break;
    case 0xf5: ARITH(p65_sbc, A_ZPX(), 1); break;
    case 0xf6: RMW(p65_inc, A_ZPX(), 1); break;
    case 0xf7: BITMOD(0x80, 1); break;
    case 0xf8: R.p |= P65_D; break;
    case 0xf9: ARITH(p65_sbc, A_ABSY(), 2); break;
    case 0xfa: R.x = p65_pop(m); p65_nz(m, R.x); break;
    case 0xfd: ARITH(p65_sbc, A_ABSX(), 2); break;
    case 0xfe: RMW(p65_inc, A_ABSX(), 2); break;
    default:                            /* inst_not_implemented */
        R.pc += 1;
        break;
    }
    m->py65_cycles += py65_cycles[opcode] + extra;
    return opcode;
}

#undef R
#undef A_ZP
#undef A_ZPX
#undef A_ZPY
#undef A_ABS
#undef A_ABSX
#undef A_ABSY
#undef A_INDX
#undef A_INDY
#undef A_ZPI
#undef A_IMM
#undef LOAD
#undef LOGIC
#undef ARITH
#undef COMPARE
#undef BIT
#undef STORE
#undef RMW
#undef BITMOD
#undef TSB_TRB
#undef BRANCH_IF
