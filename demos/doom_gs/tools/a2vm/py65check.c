/*
 * py65check: the compatibility core of a2vm (py65core.h) on a flat 64 KB
 * memory, for tools/a2vm/py65_diff.py, which runs the same cases on py65
 * itself and compares.
 *
 * Input (stdin), one case a line:
 *
 *   PC A X Y SP P STEPS IRQ SEED ADDR=VALUE...
 *
 * all in hex: the registers, the steps to run (a step with IRQ set to 1
 * first calls MPU.irq, as a2sim.Machine does with I clear, then clears
 * D), the seed of the memory's contents (fill below), then the bytes that
 * differ from them.
 *
 * Output, one line a case: the registers after, the cycles, the waiting
 * flag, then every access in order, "r" or "w", address and value.
 */
#include "a2vm.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    a2vm_py65_regs r;
    uint64_t py65_cycles;
    uint8_t ram[0x10000];
    char *log;
    size_t log_length, log_capacity;
} flat;

static void note(flat *f, char kind, uint16_t address, uint8_t value)
{
    if (f->log_length + 16 > f->log_capacity) {
        f->log_capacity = f->log_capacity ? f->log_capacity * 2 : 4096;
        f->log = realloc(f->log, f->log_capacity);
        if (!f->log) {
            fputs("py65check: out of memory\n", stderr);
            exit(2);
        }
    }
    f->log_length += (size_t)sprintf(f->log + f->log_length, " %c%04X:%02X",
                                     kind, address, value);
}

static uint8_t flat_read(flat *f, uint16_t address)
{
    note(f, 'r', address, f->ram[address]);
    return f->ram[address];
}

static void flat_write(flat *f, uint16_t address, uint8_t value)
{
    note(f, 'w', address, value);
    f->ram[address] = value;
}

/* Memory from a seed: xorshift32, one step a byte (py65_diff.fill). */
static void fill(uint8_t *ram, uint32_t seed)
{
    uint32_t state = seed ? seed : 1;
    for (unsigned i = 0; i < 0x10000; i++) {
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;
        ram[i] = (uint8_t)state;
    }
}

#define P65_M flat
#define P65_RD(address) flat_read(m, (address))
#define P65_WR(address, value) flat_write(m, (address), (uint8_t)(value))
#include "py65core.h"

int main(void)
{
    static flat f;
    static char line[1 << 20];
    while (fgets(line, sizeof line, stdin)) {
        unsigned pc, a, x, y, sp, p, steps, irq, seed;
        static unsigned filled = 0, has_fill = 0;
        static uint8_t base[0x10000];
        int used;
        if (sscanf(line, "%x %x %x %x %x %x %x %x %x%n", &pc, &a, &x, &y,
                   &sp, &p, &steps, &irq, &seed, &used) != 9) {
            fputs("py65check: a malformed case\n", stderr);
            return 2;
        }
        if (!has_fill || filled != seed) {
            fill(base, seed);
            filled = seed;
            has_fill = 1;
        }
        memcpy(f.ram, base, sizeof f.ram);
        f.r.pc = (uint16_t)pc;
        f.r.a = (uint8_t)a;
        f.r.x = (uint8_t)x;
        f.r.y = (uint8_t)y;
        f.r.sp = (uint8_t)sp;
        f.r.p = (uint8_t)p;
        f.r.waiting = 0;
        f.py65_cycles = 0;
        f.log_length = 0;
        char *at = line + used;
        unsigned address, value;
        int n;
        while (sscanf(at, " %x=%x%n", &address, &value, &n) == 2) {
            f.ram[address & 0xffff] = (uint8_t)value;
            at += n;
        }
        for (unsigned i = 0; i < steps; i++) {
            if (irq && !(f.r.p & P65_I)) {
                f.r.waiting = 0;
                p65_irq(&f);
                f.r.p &= (uint8_t)~P65_D;
            }
            p65_step(&f);
        }
        printf("%04X %02X %02X %02X %02X %02X %llu %u%.*s\n", f.r.pc, f.r.a,
               f.r.x, f.r.y, f.r.sp, f.r.p, (unsigned long long)f.py65_cycles,
               f.r.waiting, (int)f.log_length, f.log ? f.log : "");
    }
    free(f.log);
    return 0;
}
