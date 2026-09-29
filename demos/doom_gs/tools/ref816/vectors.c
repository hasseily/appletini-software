/*
 * Runs the SingleStepTests 65816 vectors against cpu816.
 *
 * usage: vectors [--limit N] [--show N] FILE...
 *
 * Each FILE is a vector file in the binary form that fetch_vectors.py
 * writes (its docstring describes the layout); the name XX.m.bin gives
 * the opcode and the mode. --limit runs the first N cases of each file,
 * --show prints the first N failures of each kind in each file.
 *
 * Three things are compared and counted separately:
 *   state   registers after the instruction, and every RAM byte the case
 *           lists; a write by the core to an unlisted address fails too
 *   cycles  the number of cycles
 *   bus     the sequence of valid bus cycles (VDA, VPA or VPB high):
 *           address, direction, value and the pins VDA, VPA, VPB, MLB
 *
 * Two conventions of the recording are undone here, for every opcode:
 *   - a cycle with a null address ends the record of an instruction that
 *     stops the clock (WAI, STP); it is not a bus cycle;
 *   - a record may end in the middle of an instruction. MVN and MVP cases
 *     stop after 100 cycles, part way through a later byte move. The core
 *     runs whole steps while the instruction repeats itself and a whole
 *     step fits in the record; the rest of the record must then be the
 *     first program fetches of the next step, and PC is compared as
 *     advanced past them.
 *
 * A few cases of the set are wrong about the chip. known_issues below
 * lists each with a rule that picks out exactly those cases and the
 * evidence; a case the rule picks is still run and its cycle count
 * checked, and its state and bus differences are counted and reported as
 * known instead of failing.
 *
 * The exit status is 1 when any case fails in any of the three ways.
 */
#include "cpu816.h"

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_BUS 512

enum { PIN_VDA = 0x80, PIN_VPA = 0x40, PIN_VPB = 0x20, PIN_READ = 0x10,
       PIN_MLB = 0x01 };
enum { NULL_ADDRESS = 1, NULL_VALUE = 2 };

typedef struct {
    uint16_t pc, s, a, x, y, d;
    uint8_t p, dbr, pbr, e;
} state;

typedef struct {
    uint32_t address;
    uint8_t value, pins, nulls;
} cycle;

typedef struct {
    state before, after;
    uint32_t ram_before_count, ram_after_count, cycle_count;
    uint32_t *ram_before, *ram_after;   /* address | value << 24 */
    cycle *cycles;
} vector;

/* The machine for one case: 16 MB of RAM, a log of the bus, and the
   addresses to clear before the next case. */
static uint8_t memory[1 << 24];
static cycle bus_log[MAX_BUS];
static unsigned bus_count;
static uint32_t written[MAX_BUS];
static unsigned written_count;

static uint8_t pins_of(const cpu816 *cpu, int read)
{
    return (uint8_t)((cpu->bus & CPU816_VDA ? PIN_VDA : 0) |
                     (cpu->bus & CPU816_VPA ? PIN_VPA : 0) |
                     (cpu->bus & CPU816_VPB ? PIN_VPB : 0) |
                     (cpu->bus & CPU816_MLB ? PIN_MLB : 0) |
                     (read ? PIN_READ : 0));
}

static void log_cycle(cpu816 *cpu, uint32_t address, uint8_t value, int read)
{
    if (bus_count < MAX_BUS) {
        bus_log[bus_count].address = address;
        bus_log[bus_count].value = value;
        bus_log[bus_count].pins = pins_of(cpu, read);
        bus_log[bus_count].nulls = 0;
    }
    bus_count++;
}

static uint8_t bus_read(void *context, uint32_t address)
{
    uint8_t value = memory[address];
    log_cycle(context, address, value, 1);
    return value;
}

static void bus_write(void *context, uint32_t address, uint8_t value)
{
    memory[address] = value;
    if (written_count < MAX_BUS)
        written[written_count++] = address;
    log_cycle(context, address, value, 0);
}

/* ---- reading the vector files ---- */

typedef struct {
    const uint8_t *data;
    size_t size, at;
    int bad;
} reader;

static uint32_t take(reader *r, unsigned bytes)
{
    uint32_t value = 0;
    if (r->at + bytes > r->size) {
        r->bad = 1;
        return 0;
    }
    for (unsigned i = 0; i < bytes; i++)
        value |= (uint32_t)r->data[r->at + i] << (8 * i);
    r->at += bytes;
    return value;
}

static void take_state(reader *r, state *s)
{
    s->pc = (uint16_t)take(r, 2);
    s->s = (uint16_t)take(r, 2);
    s->a = (uint16_t)take(r, 2);
    s->x = (uint16_t)take(r, 2);
    s->y = (uint16_t)take(r, 2);
    s->d = (uint16_t)take(r, 2);
    s->p = (uint8_t)take(r, 1);
    s->dbr = (uint8_t)take(r, 1);
    s->pbr = (uint8_t)take(r, 1);
    s->e = (uint8_t)take(r, 1);
}

static uint32_t *take_ram(reader *r, uint32_t count)
{
    uint32_t *entries = malloc((count ? count : 1) * sizeof *entries);
    if (!entries) {
        perror("vectors");
        exit(2);
    }
    for (uint32_t i = 0; i < count; i++)
        entries[i] = take(r, 4);
    return entries;
}

static int take_vector(reader *r, vector *v)
{
    take_state(r, &v->before);
    take_state(r, &v->after);
    v->ram_before_count = take(r, 2);
    v->ram_after_count = take(r, 2);
    v->cycle_count = take(r, 2);
    v->ram_before = take_ram(r, v->ram_before_count);
    v->ram_after = take_ram(r, v->ram_after_count);
    v->cycles = malloc((v->cycle_count ? v->cycle_count : 1) *
                       sizeof *v->cycles);
    if (!v->cycles) {
        perror("vectors");
        exit(2);
    }
    for (uint32_t i = 0; i < v->cycle_count; i++) {
        uint32_t word = take(r, 4);
        v->cycles[i].address = word & 0xffffff;
        v->cycles[i].value = (uint8_t)(word >> 24);
        v->cycles[i].pins = (uint8_t)take(r, 1);
        v->cycles[i].nulls = (uint8_t)take(r, 1);
    }
    return !r->bad;
}

static void free_vector(vector *v)
{
    free(v->ram_before);
    free(v->ram_after);
    free(v->cycles);
}

static uint8_t *read_file(const char *path, size_t *size)
{
    FILE *file = fopen(path, "rb");
    uint8_t *data;
    long length;

    if (!file || fseek(file, 0, SEEK_END) || (length = ftell(file)) < 0 ||
        fseek(file, 0, SEEK_SET)) {
        fprintf(stderr, "vectors: %s: %s\n", path, strerror(errno));
        exit(2);
    }
    data = malloc(length ? (size_t)length : 1);
    if (!data || fread(data, 1, (size_t)length, file) != (size_t)length) {
        fprintf(stderr, "vectors: %s: cannot read\n", path);
        exit(2);
    }
    fclose(file);
    *size = (size_t)length;
    return data;
}

/* ---- cases the set gets wrong ---- */

/* The byte at `address` before the instruction, or -1 when the case
   does not give it. */
static int initial_byte(const vector *v, uint32_t address)
{
    for (uint32_t i = 0; i < v->ram_before_count; i++)
        if ((v->ram_before[i] & 0xffffff) == address)
            return (int)(v->ram_before[i] >> 24);
    return -1;
}

static int program_byte(const vector *v, unsigned offset)
{
    return initial_byte(v, (uint32_t)v->before.pbr << 16 |
                           (uint16_t)(v->before.pc + offset));
}

/* JSR (a,x) with S = $0100: the second push leaves page 1. */
static int stack_at_page_start(const vector *v)
{
    return (v->before.s & 0xff) == 0;
}

/* (d,x) with DL = 0 whose pointer starts at the last byte of the page. */
static int pointer_at_page_end(const vector *v)
{
    int operand = program_byte(v, 1);
    return !(v->before.d & 0xff) && operand >= 0 &&
           ((operand + v->before.x) & 0xff) == 0xff;
}

typedef struct {
    uint8_t opcode, emulation;
    int (*applies)(const vector *v);
    const char *reason;
    unsigned matched, differed;
} known_issue;

static known_issue known_issues[] = {
    { 0xfc, 1, stack_at_page_start,
      "JSR (a,x) in emulation mode with S = $0100. The set wraps the "
      "second push to $01FF; on the chip JSR (a,x) is a new instruction "
      "and, like PEA, PEI, PER, PHD and JSL (whose boundary cases the set "
      "has right), pushes to $00FF and then puts S back in page 1. "
      "Bruce Clark, \"65C816 Opcodes\", appendix; SingleStepTests/65816 "
      "issue 6.", 0, 0 },
    { 0xe1, 1, pointer_at_page_end,
      "SBC (d,x) in emulation mode with DL = 0 and the pointer at the "
      "last byte of the page. The set reads the pointer's high byte from "
      "the next page; the chip wraps to the first byte of the direct "
      "page. Bruce Clark, \"65C816 Opcodes\", section 5.11; "
      "SingleStepTests/65816 issue 3.", 0, 0 },
};

#define KNOWN_ISSUES (sizeof known_issues / sizeof known_issues[0])

static known_issue *known_issue_of(const vector *v)
{
    int opcode = program_byte(v, 0);
    for (size_t i = 0; i < KNOWN_ISSUES; i++)
        if (known_issues[i].opcode == opcode &&
            known_issues[i].emulation == v->before.e &&
            known_issues[i].applies(v))
            return &known_issues[i];
    return NULL;
}

/* ---- running one case ---- */

typedef struct {
    unsigned cases, state, cycles, bus, known;
} tally;

/* Why each comparison failed; empty when it passed. */
typedef struct {
    char state[160], cycles[64], bus[160];
} outcome;

static void load_state(cpu816 *cpu, const state *s)
{
    cpu->pc = s->pc;
    cpu->s = s->s;
    cpu->a = s->a;
    cpu->x = s->x;
    cpu->y = s->y;
    cpu->d = s->d;
    cpu->p = s->p;
    cpu->dbr = s->dbr;
    cpu->pbr = s->pbr;
    cpu->e = s->e;
    cpu->state = CPU816_RUNNING;
    cpu816_normalise(cpu);
}

static int valid(uint8_t pins)
{
    return pins & (PIN_VDA | PIN_VPA | PIN_VPB);
}

static int compare_state(const cpu816 *cpu, const state *want, char *why,
                         size_t size)
{
    const char *field = NULL;
    unsigned have = 0, expect = 0;

#define CHECK(name, member) \
    if (!field && cpu->member != want->member) { \
        field = name; have = cpu->member; expect = want->member; }
    CHECK("pc", pc) CHECK("s", s) CHECK("a", a) CHECK("x", x)
    CHECK("y", y) CHECK("d", d) CHECK("p", p) CHECK("dbr", dbr)
    CHECK("pbr", pbr) CHECK("e", e)
#undef CHECK
    if (field)
        snprintf(why, size, "%s is %04x, expected %04x", field, have, expect);
    return !field;
}

static int compare_memory(const vector *v, char *why, size_t size)
{
    for (uint32_t i = 0; i < v->ram_after_count; i++) {
        uint32_t address = v->ram_after[i] & 0xffffff;
        uint8_t want = (uint8_t)(v->ram_after[i] >> 24);
        if (memory[address] != want) {
            snprintf(why, size, "RAM %06" PRIx32 " is %02x, expected %02x",
                     address, memory[address], want);
            return 0;
        }
    }
    for (unsigned i = 0; i < written_count; i++) {
        uint32_t j;
        for (j = 0; j < v->ram_after_count; j++)
            if ((v->ram_after[j] & 0xffffff) == written[i])
                break;
        if (j == v->ram_after_count) {
            snprintf(why, size, "write to %06" PRIx32 ", which the case does not list",
                     written[i]);
            return 0;
        }
    }
    return 1;
}

/* Compare the valid cycles of the core with those of the record, in
   order; `recorded` is the part of the record the core ran. */
static int compare_bus(const vector *v, unsigned recorded, char *why,
                       size_t size)
{
    unsigned mine = 0, theirs = 0;
    const uint8_t checked = PIN_VDA | PIN_VPA | PIN_VPB | PIN_READ | PIN_MLB;

    for (;;) {
        while (mine < bus_count && mine < MAX_BUS && !valid(bus_log[mine].pins))
            mine++;
        while (theirs < recorded && !valid(v->cycles[theirs].pins))
            theirs++;
        if (mine >= bus_count || mine >= MAX_BUS || theirs >= recorded)
            break;
        const cycle *a = &bus_log[mine], *b = &v->cycles[theirs];
        if (a->address != b->address || (a->pins & checked) !=
            (b->pins & checked) ||
            (!(b->nulls & NULL_VALUE) && a->value != b->value)) {
            snprintf(why, size, "valid cycle %u: %06" PRIx32 " %02x pins %02x, "
                     "expected %06" PRIx32 " %02x pins %02x", theirs,
                     a->address, a->value, a->pins & checked,
                     b->address, b->value, b->pins & checked);
            return 0;
        }
        mine++;
        theirs++;
    }
    if ((mine < bus_count && mine < MAX_BUS) || theirs < recorded) {
        snprintf(why, size, "the core made %s valid cycles than the record",
                 theirs < recorded ? "fewer" : "more");
        return 0;
    }
    return 1;
}

static void run_case(cpu816 *cpu, const vector *v, outcome *out)
{
    unsigned recorded = v->cycle_count;
    unsigned step, tail = 0;
    uint16_t start_pc = v->before.pc;
    uint8_t start_pbr = v->before.pbr;

    memset(out, 0, sizeof *out);
    for (uint32_t i = 0; i < v->ram_before_count; i++)
        memory[v->ram_before[i] & 0xffffff] = (uint8_t)(v->ram_before[i] >> 24);
    load_state(cpu, &v->before);
    bus_count = 0;
    written_count = 0;
    cpu->cycles = 0;

    while (recorded && (v->cycles[recorded - 1].nulls & NULL_ADDRESS))
        recorded--;
    do
        step = cpu816_step(cpu);
    while (cpu->state == CPU816_RUNNING && cpu->pc == start_pc &&
           cpu->pbr == start_pbr && cpu->cycles + step <= recorded);
    /* The instruction repeats itself and the record ends part way into
       the next step: the rest of the record must be that step's first
       program fetches, which move PC on. */
    if (cpu->cycles < recorded && cpu->pc == start_pc &&
        cpu->pbr == start_pbr) {
        unsigned ran = (unsigned)cpu->cycles;
        tail = recorded - ran;
        for (unsigned i = 0; i < tail; i++) {
            const cycle *c = &v->cycles[ran + i];
            if (!(c->pins & PIN_VPA) || c->address !=
                ((uint32_t)start_pbr << 16 | (uint16_t)(start_pc + i)))
                tail = 0;
        }
        if (tail)
            recorded = ran;
    }
    cpu->pc = (uint16_t)(cpu->pc + tail);

    if (compare_state(cpu, &v->after, out->state, sizeof out->state))
        compare_memory(v, out->state, sizeof out->state);
    if (cpu->cycles != recorded)
        snprintf(out->cycles, sizeof out->cycles, "%" PRIu64
                 " cycles, expected %u", cpu->cycles, recorded);
    compare_bus(v, recorded, out->bus, sizeof out->bus);

    /* Clear what this case touched. */
    for (uint32_t i = 0; i < v->ram_before_count; i++)
        memory[v->ram_before[i] & 0xffffff] = 0;
    for (unsigned i = 0; i < written_count; i++)
        memory[written[i]] = 0;
}

static void count(unsigned *failures, const char *why, const char *path,
                  unsigned index, const char *kind, unsigned shown)
{
    if (!*why)
        return;
    if ((*failures)++ < shown)
        printf("  %s case %u: %s: %s\n", path, index, kind, why);
}

static tally run_file(cpu816 *cpu, const char *path, unsigned limit,
                      unsigned shown)
{
    size_t size;
    uint8_t *data = read_file(path, &size);
    reader r = { data, size, 0, 0 };
    tally t = { 0, 0, 0, 0, 0 };
    unsigned cases;

    if (size < 12 || memcmp(data, "SST816V1", 8)) {
        fprintf(stderr, "vectors: %s: not a vector file\n", path);
        exit(2);
    }
    r.at = 8;
    cases = take(&r, 4);
    if (limit && cases > limit)
        cases = limit;
    for (unsigned i = 0; i < cases; i++) {
        vector v;
        outcome out;
        known_issue *issue;
        if (!take_vector(&r, &v)) {
            fprintf(stderr, "vectors: %s: truncated at case %u\n", path, i);
            exit(2);
        }
        run_case(cpu, &v, &out);
        t.cases++;
        issue = known_issue_of(&v);
        if (issue) {
            issue->matched++;
            if (*out.state || *out.bus) {
                issue->differed++;
                count(&t.known, *out.state ? out.state : out.bus, path, i,
                      "known issue", shown);
                *out.state = *out.bus = 0;
            }
        }
        count(&t.state, out.state, path, i, "state", shown);
        count(&t.cycles, out.cycles, path, i, "cycles", shown);
        count(&t.bus, out.bus, path, i, "bus", shown);
        free_vector(&v);
    }
    free(data);
    return t;
}

int main(int argc, char **argv)
{
    unsigned limit = 0, shown = 3;
    tally total = { 0, 0, 0, 0, 0 };
    unsigned files = 0, failed_files = 0;
    cpu816 cpu;
    int i;

    for (i = 1; i < argc && argv[i][0] == '-'; i += 2) {
        if (i + 1 >= argc)
            break;
        if (!strcmp(argv[i], "--limit"))
            limit = (unsigned)strtoul(argv[i + 1], NULL, 10);
        else if (!strcmp(argv[i], "--show"))
            shown = (unsigned)strtoul(argv[i + 1], NULL, 10);
        else
            break;
    }
    if (i >= argc || argv[i][0] == '-') {
        fprintf(stderr, "usage: vectors [--limit N] [--show N] FILE...\n");
        return 2;
    }
    cpu816_init(&cpu, bus_read, bus_write, &cpu);
    for (; i < argc; i++) {
        tally t = run_file(&cpu, argv[i], limit, shown);
        const char *name = strrchr(argv[i], '/');
        name = name ? name + 1 : argv[i];
        files++;
        if (t.state || t.cycles || t.bus) {
            failed_files++;
            printf("%s: %u cases, %u state, %u cycles, %u bus failures\n",
                   name, t.cases, t.state, t.cycles, t.bus);
        }
        total.cases += t.cases;
        total.state += t.state;
        total.cycles += t.cycles;
        total.bus += t.bus;
        total.known += t.known;
    }
    for (size_t k = 0; k < KNOWN_ISSUES; k++)
        if (known_issues[k].matched)
            printf("known issue, opcode %02x %s mode: %u cases match its rule, "
                   "%u differ from the set. %s\n", known_issues[k].opcode,
                   known_issues[k].emulation ? "emulation" : "native",
                   known_issues[k].matched, known_issues[k].differed,
                   known_issues[k].reason);
    printf("%u files, %u cases: %u state failures, %u cycle-count failures, "
           "%u bus failures, %u known issues; %u files with failures\n",
           files, total.cases, total.state, total.cycles, total.bus,
           total.known, failed_files);
    return total.state || total.cycles || total.bus ? 1 : 0;
}
