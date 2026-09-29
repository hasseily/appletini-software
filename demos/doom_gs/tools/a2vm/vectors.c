/*
 * Runs the SingleStepTests WDC 65C02 vectors against cpu65c02.
 *
 * usage: vectors [--limit N] [--show N] FILE...
 *
 * Each FILE is a vector file in the binary form that fetch_vectors.py
 * writes (its docstring describes the layout); the name XX.bin gives the
 * opcode. --limit runs the first N cases of each file, --show prints the
 * first N failures of each kind in each file.
 *
 * Three things are compared and counted separately:
 *   state   registers after the instruction, and every RAM byte the case
 *           lists; a write by the core to an unlisted address fails too
 *   cycles  the number of cycles
 *   bus     the sequence of bus cycles, every one of which is a read or a
 *           write on the 65C02: address, direction and value
 *
 * A few cases of the set differ from the chip the core models. The table
 * known_issues below lists each with a rule that picks out exactly those
 * cases and the evidence. A case the rule picks is still run and all
 * three comparisons made; its bus differences are counted and reported
 * as known instead of failing, while its state and cycle count must
 * still match. A rule that picks a case the set gets right fails the
 * run, so a rule cannot be wider than the issue it explains.
 *
 * The exit status is 1 when any case fails in any of the three ways.
 */
#include "cpu65c02.h"

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_BUS 64

typedef struct {
    uint16_t pc;
    uint8_t s, a, x, y, p;
} state;

typedef struct {
    uint16_t address;
    uint8_t value, write;
} cycle;

typedef struct {
    state before, after;
    uint32_t ram_before_count, ram_after_count, cycle_count;
    uint32_t *ram_before, *ram_after;   /* address | value << 24 */
    cycle *cycles;
} vector;

/* The machine for one case: 64 KB of RAM, a log of the bus, and the
   addresses to clear before the next case. */
static uint8_t memory[1 << 16];
static cycle bus_log[MAX_BUS];
static unsigned bus_count;
static uint16_t written[MAX_BUS];
static unsigned written_count;

static void log_cycle(uint16_t address, uint8_t value, int write)
{
    if (bus_count < MAX_BUS) {
        bus_log[bus_count].address = address;
        bus_log[bus_count].value = value;
        bus_log[bus_count].write = (uint8_t)write;
    }
    bus_count++;
}

static uint8_t bus_read(void *context, uint16_t address, cpu65c02_kind kind)
{
    uint8_t value = memory[address];
    (void)context;
    (void)kind;
    log_cycle(address, value, 0);
    return value;
}

static void bus_write(void *context, uint16_t address, uint8_t value,
                      cpu65c02_kind kind)
{
    (void)context;
    (void)kind;
    memory[address] = value;
    if (written_count < MAX_BUS)
        written[written_count++] = address;
    log_cycle(address, value, 1);
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
    s->s = (uint8_t)take(r, 1);
    s->a = (uint8_t)take(r, 1);
    s->x = (uint8_t)take(r, 1);
    s->y = (uint8_t)take(r, 1);
    s->p = (uint8_t)take(r, 1);
}

static void *allocate(size_t count, size_t size)
{
    void *block = malloc((count ? count : 1) * size);
    if (!block) {
        perror("vectors");
        exit(2);
    }
    return block;
}

static int take_vector(reader *r, vector *v)
{
    take_state(r, &v->before);
    take_state(r, &v->after);
    v->ram_before_count = take(r, 2);
    v->ram_after_count = take(r, 2);
    v->cycle_count = take(r, 2);
    v->ram_before = allocate(v->ram_before_count, sizeof *v->ram_before);
    v->ram_after = allocate(v->ram_after_count, sizeof *v->ram_after);
    v->cycles = allocate(v->cycle_count, sizeof *v->cycles);
    for (uint32_t i = 0; i < v->ram_before_count; i++)
        v->ram_before[i] = take(r, 4);
    for (uint32_t i = 0; i < v->ram_after_count; i++)
        v->ram_after[i] = take(r, 4);
    for (uint32_t i = 0; i < v->cycle_count; i++) {
        uint32_t word = take(r, 4);
        v->cycles[i].address = (uint16_t)word;
        v->cycles[i].value = (uint8_t)(word >> 16);
        v->cycles[i].write = (uint8_t)(word >> 24 & 1);
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
    data = allocate((size_t)length, 1);
    if (fread(data, 1, (size_t)length, file) != (size_t)length) {
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
static int initial_byte(const vector *v, uint16_t address)
{
    for (uint32_t i = 0; i < v->ram_before_count; i++)
        if ((uint16_t)v->ram_before[i] == address)
            return (int)(v->ram_before[i] >> 24);
    return -1;
}

static int program_byte(const vector *v, unsigned offset)
{
    return initial_byte(v, (uint16_t)(v->before.pc + offset));
}

/* STA a,X or STA a,Y whose index does not cross a page. */
static int store_on_same_page(const vector *v)
{
    int low = program_byte(v, 1), opcode = program_byte(v, 0);
    uint8_t index = opcode == 0x9d ? v->before.x : v->before.y;
    return low >= 0 && low + index <= 0xff;
}

typedef struct {
    uint8_t opcode;
    int (*applies)(const vector *v);
    const char *reason;
    unsigned matched, differed;
} known_issue;

static known_issue known_issues[] = {
    { 0x9d, store_on_same_page,
      "STA a,X when the index does not cross a page. The set's fourth "
      "cycle reads the last instruction byte; the Appletini's core "
      "(hdl/apple/w65c02_core.sv, ST_INDEX_DUMMY) reads the target "
      "address, the false read Apple II software depends on for "
      "STA $C08x,X on the disk and other slot soft switches. The "
      "appletini-one harness corrects the same cases "
      "(scripts/test_w65c02_core.py, normalize_known_cycle_quirks). "
      "Only the address of that dummy read differs.", 0, 0 },
    { 0x99, store_on_same_page,
      "STA a,Y when the index does not cross a page: as for STA a,X.",
      0, 0 },
};

#define KNOWN_ISSUES (sizeof known_issues / sizeof known_issues[0])

static known_issue *known_issue_of(const vector *v)
{
    int opcode = program_byte(v, 0);
    for (size_t i = 0; i < KNOWN_ISSUES; i++)
        if (known_issues[i].opcode == opcode && known_issues[i].applies(v))
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

static void load_state(cpu65c02 *cpu, const state *s)
{
    cpu->pc = s->pc;
    cpu->s = s->s;
    cpu->a = s->a;
    cpu->x = s->x;
    cpu->y = s->y;
    /* As given, B included: the chip has no B flip-flop, but the set
       gives P with bit 4 set in some cases and expects it carried through
       every instruction but PLP and RTI, which load P from the stack. The
       core's register keeps any bit it is given. */
    cpu->p = s->p;
    cpu->state = CPU65C02_RUNNING;
    cpu->nmi_pending = 0;
    cpu->irq_sources = 0;
}

static int compare_state(const cpu65c02 *cpu, const state *want, char *why,
                         size_t size)
{
    const char *field = NULL;
    unsigned have = 0, expect = 0;

#define CHECK(name, member) \
    if (!field && cpu->member != want->member) { \
        field = name; have = cpu->member; expect = want->member; }
    CHECK("pc", pc) CHECK("s", s) CHECK("a", a) CHECK("x", x)
    CHECK("y", y) CHECK("p", p)
#undef CHECK
    if (field)
        snprintf(why, size, "%s is %02x, expected %02x", field, have, expect);
    return !field;
}

static int compare_memory(const vector *v, char *why, size_t size)
{
    for (uint32_t i = 0; i < v->ram_after_count; i++) {
        uint16_t address = (uint16_t)v->ram_after[i];
        uint8_t want = (uint8_t)(v->ram_after[i] >> 24);
        if (memory[address] != want) {
            snprintf(why, size, "RAM %04x is %02x, expected %02x",
                     address, memory[address], want);
            return 0;
        }
    }
    for (unsigned i = 0; i < written_count; i++) {
        uint32_t j;
        for (j = 0; j < v->ram_after_count; j++)
            if ((uint16_t)v->ram_after[j] == written[i])
                break;
        if (j == v->ram_after_count) {
            snprintf(why, size, "write to %04x, which the case does not list",
                     written[i]);
            return 0;
        }
    }
    return 1;
}

static int compare_bus(const vector *v, char *why, size_t size)
{
    unsigned count = bus_count < MAX_BUS ? bus_count : MAX_BUS;
    unsigned common = count < v->cycle_count ? count : v->cycle_count;

    for (unsigned i = 0; i < common; i++) {
        const cycle *a = &bus_log[i], *b = &v->cycles[i];
        if (a->address != b->address || a->value != b->value ||
            a->write != b->write) {
            snprintf(why, size, "cycle %u: %04x %02x %s, expected "
                     "%04x %02x %s", i, a->address, a->value,
                     a->write ? "write" : "read", b->address, b->value,
                     b->write ? "write" : "read");
            return 0;
        }
    }
    if (bus_count != v->cycle_count) {
        snprintf(why, size, "the core made %u bus cycles, the record %u",
                 bus_count, (unsigned)v->cycle_count);
        return 0;
    }
    return 1;
}

static void run_case(cpu65c02 *cpu, const vector *v, outcome *out)
{
    memset(out, 0, sizeof *out);
    for (uint32_t i = 0; i < v->ram_before_count; i++)
        memory[(uint16_t)v->ram_before[i]] = (uint8_t)(v->ram_before[i] >> 24);
    load_state(cpu, &v->before);
    bus_count = 0;
    written_count = 0;
    cpu->cycles = 0;

    (void)cpu65c02_step(cpu);

    if (compare_state(cpu, &v->after, out->state, sizeof out->state))
        compare_memory(v, out->state, sizeof out->state);
    if (cpu->cycles != v->cycle_count)
        snprintf(out->cycles, sizeof out->cycles, "%" PRIu64
                 " cycles, expected %u", cpu->cycles,
                 (unsigned)v->cycle_count);
    compare_bus(v, out->bus, sizeof out->bus);

    /* Clear what this case touched. */
    for (uint32_t i = 0; i < v->ram_before_count; i++)
        memory[(uint16_t)v->ram_before[i]] = 0;
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

static tally run_file(cpu65c02 *cpu, const char *path, unsigned limit,
                      unsigned shown)
{
    size_t size;
    uint8_t *data = read_file(path, &size);
    reader r = { data, size, 0, 0 };
    tally t = { 0, 0, 0, 0, 0 };
    unsigned cases;

    if (size < 12 || memcmp(data, "SSTC02V1", 8)) {
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
            /* The issues are all about the address of one dummy read:
               only the bus comparison is excused. */
            if (*out.bus) {
                issue->differed++;
                count(&t.known, out.bus, path, i, "known issue", shown);
                *out.bus = 0;
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
    unsigned files = 0, failed_files = 0, empty_files = 0;
    int unexplained = 0;
    cpu65c02 cpu;
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
    cpu65c02_init(&cpu, bus_read, bus_write, NULL);
    for (; i < argc; i++) {
        tally t = run_file(&cpu, argv[i], limit, shown);
        const char *name = strrchr(argv[i], '/');
        name = name ? name + 1 : argv[i];
        files++;
        if (!t.cases) {
            empty_files++;
            printf("%s: no cases in the set\n", name);
        }
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
    for (size_t k = 0; k < KNOWN_ISSUES; k++) {
        if (!known_issues[k].matched)
            continue;
        printf("known issue, opcode %02x: %u cases match its rule, %u differ "
               "from the set. %s\n", known_issues[k].opcode,
               known_issues[k].matched, known_issues[k].differed,
               known_issues[k].reason);
        if (known_issues[k].differed != known_issues[k].matched) {
            printf("known issue, opcode %02x: %u cases of the rule agree "
                   "with the set, so the rule is wider than the issue\n",
                   known_issues[k].opcode,
                   known_issues[k].matched - known_issues[k].differed);
            unexplained = 1;
        }
    }
    printf("%u files (%u empty), %u cases: %u state failures, "
           "%u cycle-count failures, %u bus failures, %u known issues; "
           "%u files with failures\n", files, empty_files, total.cases,
           total.state, total.cycles, total.bus, total.known, failed_files);
    return total.state || total.cycles || total.bus || unexplained ? 1 : 0;
}
