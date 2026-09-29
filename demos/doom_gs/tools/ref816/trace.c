/*
 * The trace of a run of ref816: see trace.h.
 */
#include "trace.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    /* Kinds of access: the cpu816_space of the cycle, but data in the
       I/O space or the ROM is io. */
    K_PROGRAM, K_DIRECT, K_STACK, K_DATA, K_IO, K_VECTOR, KINDS,

    /* Width records. */
    W_MX = 0, W_D = 1, W_DBR = 2,

    STACK_DEPTH = 64,           /* phases open at once */
    SAMPLE_ACCESSES = 64,       /* accesses a sampled step may have */
    SAMPLE_PREVIOUS = 8,        /* accesses before it that it lists */
    MAX_SMC_FRAME = 0xffff,
    NO_STACK = 0x10000,         /* no S seen */
    SCREEN_START = 0x2000, SCREEN_END = 0x9d00,         /* in bank $E1 */

    /* Bytes that exist: banks $00-$7F, then $E0-$E1. */
    RAM_BYTES = IIGS_RAM_BANKS * IIGS_BANK + 2 * IIGS_BANK,
    ADDRESS_BITS = 24,

    /* Opcodes that the phases follow. */
    OP_JSR = 0x20, OP_JSL = 0x22, OP_JSR_INDEXED = 0xfc,
    OP_RTI = 0x40, OP_RTS = 0x60, OP_RTL = 0x6b
};

static const char *const KIND_NAMES[KINDS] = {
    "program", "direct", "stack", "data", "io", "vector"
};
static const char *const WIDTH_NAMES[] = { "mx", "d", "dbr" };

/* ---- a table of counts by 64-bit key ---- */

#define EMPTY UINT64_MAX

typedef struct {
    uint64_t key;
    uint64_t count;
    uint32_t extra;             /* heat: the instruction's length */
} slot;

typedef struct {
    slot *slots;
    size_t capacity, used;      /* capacity: a power of two */
    int failed;                 /* out of memory: counts are missing */
} table;

static size_t hash(uint64_t key)
{
    key ^= key >> 33;
    key *= 0xff51afd7ed558ccdu;
    key ^= key >> 33;
    return (size_t)key;
}

static int table_grow(table *t)
{
    size_t capacity = t->capacity ? 2 * t->capacity : 4096;
    slot *slots = malloc(capacity * sizeof *slots);
    if (!slots)
        return 0;
    for (size_t i = 0; i < capacity; i++)
        slots[i].key = EMPTY;
    for (size_t i = 0; i < t->capacity; i++) {
        if (t->slots[i].key == EMPTY)
            continue;
        size_t at = hash(t->slots[i].key) & (capacity - 1);
        while (slots[at].key != EMPTY)
            at = (at + 1) & (capacity - 1);
        slots[at] = t->slots[i];
    }
    free(t->slots);
    t->slots = slots;
    t->capacity = capacity;
    return 1;
}

/* The slot of `key`, added with a count of 0 if it is new; NULL when
   memory is short (the table remembers the failure). */
static slot *table_at(table *t, uint64_t key)
{
    if (2 * (t->used + 1) > t->capacity && !table_grow(t)) {
        t->failed = 1;
        return NULL;
    }
    size_t at = hash(key) & (t->capacity - 1);
    while (t->slots[at].key != key) {
        if (t->slots[at].key == EMPTY) {
            t->slots[at].key = key;
            t->slots[at].count = 0;
            t->slots[at].extra = 0;
            t->used++;
            break;
        }
        at = (at + 1) & (t->capacity - 1);
    }
    return &t->slots[at];
}

static void table_clear(table *t)
{
    for (size_t i = 0; i < t->capacity; i++)
        t->slots[i].key = EMPTY;
    t->used = 0;
}

static int by_key(const void *a, const void *b)
{
    uint64_t x = ((const slot *)a)->key, y = ((const slot *)b)->key;
    return (x > y) - (x < y);
}

/* The used slots in the order of their keys, so that a file does not
   depend on the table's layout; NULL when memory is short. */
static slot *table_sorted(table *t)
{
    slot *list = malloc((t->used ? t->used : 1) * sizeof *list);
    if (!list)
        return NULL;
    size_t n = 0;
    for (size_t i = 0; i < t->capacity; i++)
        if (t->slots[i].key != EMPTY)
            list[n++] = t->slots[i];
    qsort(list, n, sizeof *list, by_key);
    return list;
}

/* ---- the trace ---- */

typedef struct {
    uint8_t phase;
    uint32_t pc;                /* where the phase returns to */
    uint16_t s;                 /*   with this S */
} open_phase;

/* What one frame gathers. */
typedef struct {
    uint64_t start_clock, start_cycles, start_instructions;
    uint64_t cost[TRACE_MAX_PHASES][2];
    uint64_t enters[TRACE_MAX_PHASES];          /* calls, interrupts */
    uint64_t firmware[2];       /* firmware traps: calls, cycles */
    uint64_t access[TRACE_MAX_PHASES][KINDS][256][2];
    uint64_t lines[256][6];     /* touched 8, 64, 256; written 8, 64, 256 */
    uint64_t switches[TRACE_MAX_PHASES];
    uint32_t stack[TRACE_MAX_PHASES][2];        /* above, at or below */
    uint64_t screen[TRACE_MAX_PHASES][3];       /* direct, shadowed,
                                                   changed */
    uint64_t unclosed;
    table heat;                 /* phase << 24 | pc: count, length */
    /* instructions by phase, opcode and the widths they ran with
       (E << 2 | M << 1 | X) */
    uint64_t ops[TRACE_MAX_PHASES][256][8];
    uint64_t code[TRACE_MAX_PHASES][2];         /* changes, misses */
} frame;

struct trace {
    iigs *m;
    const trace_config *config;
    FILE *out;
    cpu816_read_fn read;        /* the machine's bus */
    cpu816_write_fn write;
    void *context;

    uint8_t *entry_bits;        /* a bit for each entry address */

    /* The CPU after the last step: the state before this one. */
    uint32_t pc;
    uint16_t s, d, a, x, y;
    uint8_t p, e, dbr;
    uint64_t cycles, instructions;
    uint64_t firmware_cycles;   /* charged by the machine's traps */
    unsigned program_bytes;     /* fetched by the PC in this step */
    int interrupt;              /* this step entered an interrupt */

    open_phase open[STACK_DEPTH];
    unsigned depth;
    uint8_t phase;              /* the innermost open phase */

    int armed;                  /* the next frame is recorded */
    int recording;              /* the frame in progress is recorded */
    uint32_t frames;            /* recorded frames written */
    int last_far_bank;          /* -1: none yet */
    frame *now;
    uint8_t *line_bits[6];      /* 8, 64, 256 touched; then written */

    /* Over the whole run. */
    uint8_t *executed;          /* a bit for each address run as code */
    uint32_t *last_width;       /* by RAM byte: the last packed widths */
    table widths;               /* kind << 40 | pc << 16 | value */
    uint32_t *pending_writer;   /* by RAM byte: writes to it before it */
    uint32_t *pending_frame;    /*   was ever executed: the last one's */
    uint32_t *pending_count;    /*   writer and frame, and how many */
    table smc;                  /* frame << 48 | writer << 24 | target */
    uint64_t smc_mixed;
    uint64_t jumps[TRACE_MAX_PHASES];

    /* Samples: the accesses of this step, and the last accesses before
       it that were not program fetches (a ring, `previous_at` next). */
    FILE *samples;
    uint32_t sample_every;
    uint64_t sample_count, samples_written, samples_skipped;
    struct { uint32_t address; uint8_t value, kind, write; }
        step_access[SAMPLE_ACCESSES];
    unsigned step_accesses;
    int step_overflow;
    uint32_t previous[SAMPLE_PREVIOUS];
    unsigned previous_count, previous_at;

    /* The model of the interpreter's code page cache: the page of the
       last program fetch, and the pages filled, in turn. */
    uint32_t code_page;
    uint32_t code_slot[TRACE_CODE_SLOTS];
    unsigned code_next;
};

static const unsigned LINE_SHIFT[3] = { 3, 6, 8 };

/* In pending_count: the pending writes had more than one writer or
   frame. */
#define MIXED 0x80000000u

/* The index of a byte that exists in the per-byte arrays, or -1. */
static long ram_index(uint32_t address)
{
    unsigned bank = address >> 16;
    if (bank < IIGS_RAM_BANKS)
        return (long)address;
    if (bank == 0xe0 || bank == 0xe1)
        return (long)(IIGS_RAM_BANKS * IIGS_BANK + (address - 0xe00000u));
    return -1;
}

static int bit(const uint8_t *bits, uint32_t index)
{
    return bits[index >> 3] >> (index & 7) & 1;
}

static int set_bit(uint8_t *bits, uint32_t index)
{
    uint8_t mask = (uint8_t)(1u << (index & 7));
    int was = bits[index >> 3] & mask;
    bits[index >> 3] |= mask;
    return !was;
}

/* ---- phases ---- */

static int entry_phase(const trace *t, uint32_t pc)
{
    if (!bit(t->entry_bits, pc))
        return -1;
    for (unsigned i = 0; i < t->config->entry_count; i++)
        if (t->config->entries[i] == pc)
            return t->config->entry_phase[i];
    return -1;
}

static void enter(trace *t, uint8_t phase, uint32_t pc, uint16_t s)
{
    if (t->depth == STACK_DEPTH) {
        /* Deeper than any real nesting: forget the oldest. */
        memmove(t->open, t->open + 1, (STACK_DEPTH - 1) * sizeof *t->open);
        t->depth--;
        t->now->unclosed++;
    }
    t->open[t->depth++] = (open_phase){ phase, pc, s };
    t->phase = phase;
    if (t->recording)
        t->now->enters[phase]++;
}

static void leave_returned(trace *t, uint32_t pc, uint16_t s)
{
    while (t->depth && t->open[t->depth - 1].pc == pc &&
           t->open[t->depth - 1].s == s)
        t->depth--;
    t->phase = t->depth ? t->open[t->depth - 1].phase : TRACE_OTHER;
}

/* ---- frames ---- */

static void start_frame(trace *t)
{
    frame *f = t->now;
    table heat = f->heat;
    memset(f, 0, sizeof *f);
    table_clear(&heat);
    f->heat = heat;
    for (unsigned p = 0; p < TRACE_MAX_PHASES; p++)
        f->stack[p][0] = f->stack[p][1] = NO_STACK;
    for (unsigned i = 0; i < 6; i++)
        memset(t->line_bits[i], 0,
               (size_t)1 << (ADDRESS_BITS - LINE_SHIFT[i % 3] - 3));
    f->start_clock = iigs_clock(t->m);
    f->start_cycles = t->m->cpu.cycles;
    f->start_instructions = t->m->instructions;
    t->recording = 1;
}

static void write_stack(FILE *out, uint32_t value)
{
    if (value == NO_STACK)
        fputs(" -", out);
    else
        fprintf(out, " %04" PRIX32, value);
}

static void write_frame(trace *t)
{
    FILE *out = t->out;
    frame *f = t->now;
    unsigned phases = t->config->phase_count;

    fprintf(out, "frame %" PRIu32 " %" PRIu64 " %" PRIu64 " %" PRIu64
            " %" PRIu64 " %" PRIu64 " %" PRIu64 "\n", t->frames,
            f->start_clock, f->start_cycles, f->start_instructions,
            iigs_clock(t->m), t->m->cpu.cycles, t->m->instructions);
    for (unsigned p = 0; p < phases; p++)
        if (f->cost[p][0] || f->cost[p][1])
            fprintf(out, "cost %u %" PRIu64 " %" PRIu64 "\n", p,
                    f->cost[p][0], f->cost[p][1]);
    for (unsigned p = 0; p < phases; p++)
        if (f->enters[p])
            fprintf(out, "enters %u %" PRIu64 "\n", p, f->enters[p]);
    if (f->firmware[0])
        fprintf(out, "firmware %" PRIu64 " %" PRIu64 "\n", f->firmware[0],
                f->firmware[1]);
    for (unsigned p = 0; p < phases; p++)
        for (unsigned k = 0; k < KINDS; k++)
            for (unsigned b = 0; b < 256; b++)
                if (f->access[p][k][b][0] || f->access[p][k][b][1])
                    fprintf(out, "access %u %s %02X %" PRIu64 " %" PRIu64
                            "\n", p, KIND_NAMES[k], b, f->access[p][k][b][0],
                            f->access[p][k][b][1]);
    for (unsigned b = 0; b < 256; b++)
        if (f->lines[b][0])
            fprintf(out, "lines %02X %" PRIu64 " %" PRIu64 " %" PRIu64
                    " %" PRIu64 " %" PRIu64 " %" PRIu64 "\n", b,
                    f->lines[b][0], f->lines[b][1], f->lines[b][2],
                    f->lines[b][3], f->lines[b][4], f->lines[b][5]);
    for (unsigned p = 0; p < phases; p++)
        if (f->switches[p])
            fprintf(out, "switches %u %" PRIu64 "\n", p, f->switches[p]);
    for (unsigned p = 0; p < phases; p++) {
        if (f->stack[p][0] == NO_STACK && f->stack[p][1] == NO_STACK)
            continue;
        fprintf(out, "stack %u", p);
        write_stack(out, f->stack[p][0]);
        write_stack(out, f->stack[p][1]);
        fputc('\n', out);
    }
    for (unsigned p = 0; p < phases; p++)
        if (f->screen[p][0] || f->screen[p][1])
            fprintf(out, "screen %u %" PRIu64 " %" PRIu64 " %" PRIu64 "\n",
                    p, f->screen[p][0], f->screen[p][1], f->screen[p][2]);
    slot *heat = table_sorted(&f->heat);
    if (!heat)
        f->heat.failed = 1;
    for (size_t i = 0; heat && i < f->heat.used; i++)
        fprintf(out, "heat %u %06" PRIX64 " %" PRIu64 " %" PRIu32 "\n",
                (unsigned)(heat[i].key >> 24), heat[i].key & 0xffffff,
                heat[i].count, heat[i].extra);
    free(heat);
    for (unsigned p = 0; p < phases; p++)
        for (unsigned op = 0; op < 256; op++)
            for (unsigned mx = 0; mx < 8; mx++)
                if (f->ops[p][op][mx])
                    fprintf(out, "op %u %02X %u %" PRIu64 "\n", p, op, mx,
                            f->ops[p][op][mx]);
    for (unsigned p = 0; p < phases; p++)
        if (f->code[p][0])
            fprintf(out, "code %u %" PRIu64 " %" PRIu64 "\n", p,
                    f->code[p][0], f->code[p][1]);
    fprintf(out, "unclosed %" PRIu64 "\n", f->unclosed);
    t->frames++;
}

/* A call of the frame entry: the frame in progress ends, and the next
   starts if it is to be recorded. Nothing is open outside the phases at
   that point, so what still is open never returned. */
static void frame_boundary(trace *t)
{
    if (t->recording) {
        t->now->unclosed += t->depth;
        write_frame(t);
        t->recording = 0;
    }
    t->depth = 0;
    t->phase = TRACE_OTHER;
    if (t->armed)
        start_frame(t);
}

/* ---- accesses ---- */

static unsigned kind_of(const trace *t, uint32_t address)
{
    unsigned bank = address >> 16;
    uint16_t offset = (uint16_t)address;

    switch (t->m->cpu.space) {
    case CPU816_PROGRAM: return K_PROGRAM;
    case CPU816_DIRECT: return K_DIRECT;
    case CPU816_STACK: return K_STACK;
    case CPU816_VECTOR: return K_VECTOR;
    default: break;
    }
    if ((bank == 0xe0 || bank == 0xe1) && offset >= 0xc000 &&
        offset < 0xd000)
        return K_IO;
    if (bank < 2 && offset >= 0xc000 && !(t->m->shadow & IIGS_SHADOW_IOLC))
        return K_IO;
    return K_DATA;
}

static void count_lines(trace *t, uint32_t address, unsigned bank,
                        int write)
{
    for (unsigned i = 0; i < 3; i++) {
        uint32_t line = address >> LINE_SHIFT[i];
        if (set_bit(t->line_bits[i], line))
            t->now->lines[bank][i]++;
        if (write && set_bit(t->line_bits[3 + i], line))
            t->now->lines[bank][3 + i]++;
    }
}

static void count_access(trace *t, uint32_t address, int write)
{
    unsigned kind = kind_of(t, address);
    unsigned bank = address >> 16;
    frame *f = t->now;

    f->access[t->phase][kind][bank][write]++;
    if (kind != K_DATA)
        return;
    count_lines(t, address, bank, write);
    if (t->config->near[bank])
        return;
    if (t->last_far_bank >= 0 && (unsigned)t->last_far_bank != bank)
        f->switches[t->phase]++;
    t->last_far_bank = (int)bank;
}

/* ---- self-modification ---- */

static void count_smc(trace *t, uint32_t frame_index, uint32_t writer,
                      uint32_t target, uint64_t count)
{
    slot *s = table_at(&t->smc, (uint64_t)frame_index << 48 |
                                (uint64_t)writer << 24 | target);
    if (s)
        s->count += count;
}

/* A byte runs as code: writes to it that waited for that count now. */
static void executed(trace *t, uint32_t address)
{
    if (!set_bit(t->executed, address))
        return;
    long i = ram_index(address);
    if (i >= 0 && t->pending_count[i]) {
        uint32_t count = t->pending_count[i] & ~MIXED;
        count_smc(t, t->pending_frame[i], t->pending_writer[i], address,
                  count);
        if (t->pending_count[i] & MIXED)
            t->smc_mixed += count;
        t->pending_count[i] = 0;
    }
}

/* A write of the instruction in progress in the recorded frame. The key
   of the smc table has 16 bits for the frame: later frames are not
   counted (a window of 18 minutes at 60 frames a second). */
static void code_write(trace *t, uint32_t address)
{
    uint32_t writer = t->m->opcode_pc;
    long i = ram_index(address);
    if (i < 0 || t->frames > MAX_SMC_FRAME)
        return;
    if (bit(t->executed, address)) {
        count_smc(t, t->frames, writer, address, 1);
        return;
    }
    if (t->pending_count[i] && (t->pending_writer[i] != writer ||
                                t->pending_frame[i] != t->frames))
        t->pending_count[i] |= MIXED;
    t->pending_writer[i] = writer;
    t->pending_frame[i] = t->frames;
    t->pending_count[i]++;
}

/* ---- the bus ---- */

/* A stack or vector access in a step that fetched no opcode is the entry
   of an IRQ or NMI (its pushes, then its vector): the phase "interrupt"
   starts there, to end with the return to where the CPU was. */
static void check_interrupt(trace *t, uint8_t space)
{
    if ((space == CPU816_STACK || space == CPU816_VECTOR) &&
        !t->interrupt && t->m->instructions == t->instructions) {
        t->interrupt = 1;
        enter(t, TRACE_INTERRUPT, t->pc, t->s);
    }
}

/* An access of this step, for a sample. */
static void sample_access(trace *t, uint32_t address, uint8_t value,
                          int write)
{
    if (!t->samples)
        return;
    if (t->step_accesses == SAMPLE_ACCESSES) {
        t->step_overflow = 1;
        return;
    }
    t->step_access[t->step_accesses].address = address;
    t->step_access[t->step_accesses].value = value;
    t->step_access[t->step_accesses].kind = (uint8_t)kind_of(t, address);
    t->step_access[t->step_accesses++].write = (uint8_t)write;
}

/* A program fetch, in the model of the code page cache. */
static void code_fetch(trace *t, uint32_t address)
{
    uint32_t page = address >> 8;
    unsigned i;
    if (page == t->code_page)
        return;
    t->code_page = page;
    for (i = 0; i < TRACE_CODE_SLOTS && t->code_slot[i] != page; i++)
        ;
    if (i == TRACE_CODE_SLOTS) {
        t->code_slot[t->code_next] = page;
        t->code_next = (t->code_next + 1) % TRACE_CODE_SLOTS;
    }
    if (t->recording) {
        t->now->code[t->phase][0]++;
        if (i == TRACE_CODE_SLOTS)
            t->now->code[t->phase][1]++;
    }
}

static uint8_t traced_read(void *context, uint32_t address)
{
    trace *t = context;
    uint8_t value = t->read(t->context, address);
    uint8_t space = t->m->cpu.space;

    sample_access(t, address, value, 0);
    if (space == CPU816_PROGRAM) {
        code_fetch(t, address);
        t->program_bytes++;
        executed(t, address);
    } else
        check_interrupt(t, space);
    if (t->recording)
        count_access(t, address, 0);
    return value;
}

/* The byte of $E1:2000-$9CFF that a write to `address` reaches, or
   IIGS_NO_SHADOW; `*shadowed` says whether through the shadow. */
static uint32_t screen_byte(const trace *t, uint32_t address, int *shadowed)
{
    uint32_t target = address;
    *shadowed = 0;
    if (address >> 16 != 0xe1) {
        target = iigs_shadow_target(t->m, address);
        *shadowed = 1;
    }
    if (target >> 16 == 0xe1 && (target & 0xffff) >= SCREEN_START &&
        (target & 0xffff) < SCREEN_END)
        return target;
    return IIGS_NO_SHADOW;
}

static void traced_write(void *context, uint32_t address, uint8_t value)
{
    trace *t = context;
    sample_access(t, address, value, 1);
    check_interrupt(t, t->m->cpu.space);
    if (!t->recording) {
        t->write(t->context, address, value);
        return;
    }
    int shadowed;
    uint32_t screen = screen_byte(t, address, &shadowed);
    uint8_t before = iigs_peek(t->m, screen);
    t->write(t->context, address, value);
    count_access(t, address, 1);
    code_write(t, address);
    if (screen != IIGS_NO_SHADOW) {
        uint64_t *counts = t->now->screen[t->phase];
        counts[shadowed]++;
        if (iigs_peek(t->m, screen) != before)
            counts[2]++;
    }
}

/* ---- steps ---- */

/* The widths an instruction ran with, when they differ from the last
   ones seen at its address. */
static void record_widths(trace *t, uint32_t pc)
{
    uint32_t mx = (uint32_t)t->e << 2 | (t->p >> 4 & 3);
    uint32_t packed = 1u << 31 | mx << 24 | (uint32_t)t->dbr << 16 | t->d;
    long i = ram_index(pc);
    if (i >= 0) {
        if (t->last_width[i] == packed)
            return;
        t->last_width[i] = packed;
    }
    const uint32_t values[] = { mx, t->d, t->dbr };
    for (uint64_t kind = W_MX; kind <= W_DBR; kind++)
        table_at(&t->widths, kind << 40 | (uint64_t)pc << 16 |
                             values[kind]);
}

static int is_call(uint8_t opcode)
{
    return opcode == OP_JSR || opcode == OP_JSL || opcode == OP_JSR_INDEXED;
}

static int is_return(uint8_t opcode)
{
    return opcode == OP_RTS || opcode == OP_RTL || opcode == OP_RTI;
}

static void account(trace *t, uint64_t instructions, uint64_t cycles,
                    uint32_t opcode_pc)
{
    frame *f = t->now;
    uint16_t s = t->m->cpu.s;
    int low = s <= t->config->stack_split;

    f->cost[t->phase][0] += instructions;
    f->cost[t->phase][1] += cycles;
    if (s < f->stack[t->phase][low])
        f->stack[t->phase][low] = s;
    if (instructions) {
        /* the widths before the step are those the instruction ran with */
        unsigned mx = (unsigned)t->e << 2 | (t->p >> 4 & 3);
        f->ops[t->phase][t->m->opcode][mx] += instructions;
        slot *h = table_at(&f->heat, (uint64_t)t->phase << 24 | opcode_pc);
        if (h) {
            h->count += instructions;
            if (t->program_bytes > h->extra)
                h->extra = t->program_bytes;
        }
    }
}

static void snapshot(trace *t)
{
    const cpu816 *c = &t->m->cpu;
    t->pc = (uint32_t)c->pbr << 16 | c->pc;
    t->s = c->s;
    t->d = c->d;
    t->a = c->a;
    t->x = c->x;
    t->y = c->y;
    t->p = c->p;
    t->e = c->e;
    t->dbr = c->dbr;
    t->cycles = c->cycles;
    t->instructions = t->m->instructions;
    t->firmware_cycles = t->m->counts.firmware_cycles;
    t->program_bytes = 0;
    t->interrupt = 0;
    t->step_accesses = 0;
    t->step_overflow = 0;
}

/* Write the instruction of this step as a sample (see trace.h). */
static void write_sample(trace *t)
{
    FILE *out = t->samples;
    const cpu816 *c = &t->m->cpu;
    fprintf(out, "s %u %06" PRIX32 " %04X %04X %04X %04X %04X %02X %02X %u\n",
            t->phase, t->pc, t->a, t->x, t->y, t->s, t->d, t->dbr, t->p,
            t->e);
    fputc('p', out);
    for (unsigned i = 0; i < t->previous_count; i++)
        fprintf(out, " %06" PRIX32, t->previous[(t->previous_at +
                                                  SAMPLE_PREVIOUS - 1 - i) %
                                                 SAMPLE_PREVIOUS]);
    fputc('\n', out);
    for (unsigned i = 0; i < t->step_accesses; i++)
        fprintf(out, "%c %06" PRIX32 " %02X %s\n",
                t->step_access[i].write ? 'w' : 'r',
                t->step_access[i].address, t->step_access[i].value,
                KIND_NAMES[t->step_access[i].kind]);
    fprintf(out, "a %06" PRIX32 " %04X %04X %04X %04X %04X %02X %02X %u %u\n",
            (uint32_t)c->pbr << 16 | c->pc, c->a, c->x, c->y, c->s, c->d,
            c->dbr, c->p, c->e, (unsigned)c->state);
    t->samples_written++;
}

/* The sample of this step, if it is one, then its accesses into the
   ring of previous ones. */
static void sample_step(trace *t, uint64_t instructions)
{
    if (!t->samples)
        return;
    if (t->recording && instructions == 1 &&
        ++t->sample_count % t->sample_every == 0) {
        if (t->step_overflow)
            t->samples_skipped++;
        else
            write_sample(t);
    }
    for (unsigned i = 0; i < t->step_accesses; i++)
        if (t->step_access[i].kind != K_PROGRAM) {
            t->previous[t->previous_at] = t->step_access[i].address;
            t->previous_at = (t->previous_at + 1) % SAMPLE_PREVIOUS;
            if (t->previous_count < SAMPLE_PREVIOUS)
                t->previous_count++;
        }
}

static void after_step(void *context)
{
    trace *t = context;
    iigs *m = t->m;
    const cpu816 *c = &m->cpu;
    uint64_t instructions = m->instructions - t->instructions;
    uint32_t pc = (uint32_t)c->pbr << 16 | c->pc;
    int call = instructions == 1 && is_call(m->opcode);
    /* A firmware trap charges its cycles with no instruction: they are
       the machine's, and go to no phase. */
    uint64_t firmware = m->counts.firmware_cycles - t->firmware_cycles;

    if (instructions)
        record_widths(t, m->opcode_pc);
    sample_step(t, instructions);
    if (t->recording) {
        if (firmware) {
            t->now->firmware[0]++;
            t->now->firmware[1] += firmware;
        }
        account(t, instructions, c->cycles - t->cycles - firmware,
                m->opcode_pc);
    }

    leave_returned(t, pc, c->s);
    if (call && pc == t->config->frame_entry)
        frame_boundary(t);
    int phase = entry_phase(t, pc);
    if (phase >= 0) {
        if (call) {
            /* Back at the instruction after the call, S as before it. */
            uint32_t back = (m->opcode_pc & 0xff0000u) |
                            ((m->opcode_pc + t->program_bytes) & 0xffff);
            enter(t, (uint8_t)phase, back, t->s);
        } else if (instructions && !is_return(m->opcode))
            t->jumps[phase]++;
    }
    snapshot(t);
}

/* ---- the interface ---- */

void trace_config_init(trace_config *c, const char *path)
{
    memset(c, 0, sizeof *c);
    c->path = path;
    c->names[TRACE_OTHER] = "other";
    c->names[TRACE_INTERRUPT] = "interrupt";
    c->phase_count = 2;
}

int trace_config_phase(trace_config *c, const char *name, uint32_t entry)
{
    unsigned phase;
    if (!strcmp(name, c->names[TRACE_OTHER]) ||
        !strcmp(name, c->names[TRACE_INTERRUPT]) ||
        c->entry_count == TRACE_MAX_ENTRIES)
        return 0;
    for (phase = 2; phase < c->phase_count; phase++)
        if (!strcmp(name, c->names[phase]))
            break;
    if (phase == c->phase_count) {
        if (phase == TRACE_MAX_PHASES)
            return 0;
        c->names[c->phase_count++] = name;
    }
    c->entries[c->entry_count] = entry & 0xffffff;
    c->entry_phase[c->entry_count++] = (uint8_t)phase;
    return 1;
}

static void free_trace(trace *t)
{
    if (t->now)
        free(t->now->heat.slots);
    free(t->now);
    for (unsigned i = 0; i < 6; i++)
        free(t->line_bits[i]);
    free(t->entry_bits);
    free(t->executed);
    free(t->last_width);
    free(t->widths.slots);
    free(t->pending_writer);
    free(t->pending_frame);
    free(t->pending_count);
    free(t->smc.slots);
    free(t);
}

static void write_header(trace *t)
{
    const trace_config *c = t->config;
    fputs("ref816-trace 1\n", t->out);
    for (unsigned p = 0; p < c->phase_count; p++)
        fprintf(t->out, "phase %u %s\n", p, c->names[p]);
    for (unsigned i = 0; i < c->entry_count; i++)
        fprintf(t->out, "entry %06" PRIX32 " %u\n", c->entries[i],
                c->entry_phase[i]);
    for (unsigned b = 0; b < 256; b++)
        if (c->near[b])
            fprintf(t->out, "near %02X\n", b);
    fprintf(t->out, "split %04X\n", c->stack_split);
}

trace *trace_open(iigs *m, const trace_config *c)
{
    trace *t = calloc(1, sizeof *t);
    if (!t)
        return NULL;
    t->m = m;
    t->config = c;
    t->now = calloc(1, sizeof *t->now);
    for (unsigned i = 0; i < 6; i++)
        t->line_bits[i] =
            malloc((size_t)1 << (ADDRESS_BITS - LINE_SHIFT[i % 3] - 3));
    t->entry_bits = calloc((size_t)1 << (ADDRESS_BITS - 3), 1);
    t->executed = calloc((size_t)1 << (ADDRESS_BITS - 3), 1);
    /* Zeroed by the system as they are touched: only the pages of the
       code and of the data written in the recorded frames get memory. */
    t->last_width = calloc(RAM_BYTES, sizeof *t->last_width);
    t->pending_writer = calloc(RAM_BYTES, sizeof *t->pending_writer);
    t->pending_frame = calloc(RAM_BYTES, sizeof *t->pending_frame);
    t->pending_count = calloc(RAM_BYTES, sizeof *t->pending_count);
    int ready = t->now && t->entry_bits && t->executed && t->last_width &&
                t->pending_writer && t->pending_frame && t->pending_count;
    for (unsigned i = 0; i < 6; i++)
        ready = ready && t->line_bits[i];
    if (!ready || !(t->out = fopen(c->path, "w"))) {
        free_trace(t);
        return NULL;
    }
    if (c->sample_path) {
        if (!(t->samples = fopen(c->sample_path, "w"))) {
            fclose(t->out);
            free_trace(t);
            return NULL;
        }
        fputs("ref816-samples 1\n", t->samples);
        t->sample_every = c->sample_every ? c->sample_every
                                          : TRACE_SAMPLE_EVERY;
    }
    for (unsigned i = 0; i < c->entry_count; i++)
        set_bit(t->entry_bits, c->entries[i]);
    t->armed = c->from == NULL;
    t->last_far_bank = -1;
    t->code_page = UINT32_MAX;
    for (unsigned i = 0; i < TRACE_CODE_SLOTS; i++)
        t->code_slot[i] = UINT32_MAX;
    write_header(t);

    t->read = m->cpu.read;
    t->write = m->cpu.write;
    t->context = m->cpu.context;
    m->cpu.read = traced_read;
    m->cpu.write = traced_write;
    m->cpu.context = t;
    m->after_step = after_step;
    m->step_context = t;
    snapshot(t);
    return t;
}

void trace_note(trace *t, const char *name)
{
    fprintf(t->out, "note %s %" PRIu64 " %" PRIu64 " %" PRIu64 "\n", name,
            iigs_clock(t->m), t->m->cpu.cycles, t->m->instructions);
    if (t->config->from && !strcmp(name, t->config->from)) {
        t->armed = 1;
        t->last_far_bank = -1;
    }
    if (t->config->to && !strcmp(name, t->config->to)) {
        /* The frame in progress is not whole: it is dropped. */
        t->armed = 0;
        t->recording = 0;
    }
}

int trace_close(trace *t)
{
    FILE *out = t->out;
    iigs *m = t->m;

    slot *smc = table_sorted(&t->smc);
    for (size_t i = 0; smc && i < t->smc.used; i++) {
        uint32_t frame_index = (uint32_t)(smc[i].key >> 48);
        if (frame_index < t->frames)        /* not the dropped one */
            fprintf(out, "smc %" PRIu32 " %06" PRIX64 " %06" PRIX64
                    " %" PRIu64 "\n", frame_index,
                    smc[i].key >> 24 & 0xffffff, smc[i].key & 0xffffff,
                    smc[i].count);
    }
    fprintf(out, "smc-mixed %" PRIu64 "\n", t->smc_mixed);
    for (unsigned p = 0; p < t->config->phase_count; p++)
        if (t->jumps[p])
            fprintf(out, "jumps %u %" PRIu64 "\n", p, t->jumps[p]);
    slot *widths = table_sorted(&t->widths);
    for (size_t i = 0; widths && i < t->widths.used; i++) {
        uint64_t key = widths[i].key;
        fprintf(out, "width %06" PRIX64 " %s %" PRIX64 "\n",
                key >> 16 & 0xffffff, WIDTH_NAMES[key >> 40],
                key & 0xffff);
    }
    fprintf(out, "end %" PRIu64 " %" PRIu64 " %" PRIu64 "\n", iigs_clock(m),
            m->cpu.cycles, m->instructions);
    int ok = smc && widths && !t->smc.failed && !t->widths.failed &&
             !t->now->heat.failed && !ferror(out);
    free(smc);
    free(widths);
    ok = !fclose(out) && ok;
    if (t->samples) {
        fprintf(t->samples, "end %" PRIu64 " %" PRIu64 "\n",
                t->samples_written, t->samples_skipped);
        ok = !ferror(t->samples) && ok;
        ok = !fclose(t->samples) && ok;
    }

    m->cpu.read = t->read;
    m->cpu.write = t->write;
    m->cpu.context = t->context;
    m->after_step = NULL;
    m->step_context = NULL;
    free_trace(t);
    return ok;
}
