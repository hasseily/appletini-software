/*
 * mathref: upstream's math routines on ref816's machine (tools/ref816,
 * used as a library and not modified), for the native math of milestone
 * 6 (docs/NATIVE.md sections 3 and 13; src/native/MATH.md).
 *
 *   mathref capture IMAGE DISK INPUT FRAMES SPEC OUTDIR
 *
 *       Runs the release from IMAGE with DISK (read only: the disk's
 *       writes stay in memory) and the input program INPUT (a compiled
 *       coverage script) for at most FRAMES video frames, stopping at
 *       the program's stop. Every call (JSR, JSL, JSR (a,x)) of a
 *       routine of SPEC is logged to OUTDIR/NAME.bin: a record per call
 *       with the values of the routine's declared inputs at its entry,
 *       of its declared outputs at its return (none for a routine
 *       declared "inputs only"), its cycles and flags. The first call of
 *       each routine also writes OUTDIR/NAME.entry (the registers, soft
 *       switches and return address of that call), and the run's end
 *       writes OUTDIR/base.ram (banks $00-$7F then $E0-$E1): with them
 *       `batch` runs the routine again on any inputs.
 *
 *   mathref batch RAM ENTRY SPEC NAME CASES OUT
 *
 *       Loads RAM (a base.ram) and, for each case of CASES (the input
 *       bytes of routine NAME of SPEC, one record after the other), sets
 *       the registers of ENTRY, puts the inputs in place and runs the
 *       routine from its entry to its return, as ref816's --call does
 *       (footprint.h): the call starts at the routine's first
 *       instruction with the return address of ENTRY on the stack and
 *       ends after the RTS or RTL that pops it. OUT gets, per case, the
 *       outputs and the call's cycles (4 bytes). The machine is a fresh
 *       one (the DOC and the ADB quiet: no interrupt comes), as for
 *       --call.
 *
 * SPEC, one line each, # starts a comment:
 *
 *   routine NAME ADDR [inonly]     a routine at ADDR (hex, 24 bits)
 *   in a|x|y                       a 16-bit register input
 *   in ADDR LEN                    LEN bytes of memory (hex address)
 *   out a|x|y                      the same, as outputs
 *   out ADDR LEN
 *   table ADDR LEN                 memory the routine may read that is
 *                                  neither an input nor written first:
 *                                  its tables, its code's constants
 *
 * A record of NAME.bin:
 *
 *   site     3 bytes   the return address on the stack (the call site)
 *   d        2         D at the entry
 *   dbr      1         DBR at the entry
 *   p        1         P at the entry
 *   flags    1         1: an interrupt ran inside the call (its cycles
 *                      are then not the routine's own); 2: the call read
 *                      a byte of data it had not written first that is
 *                      neither an input nor in a table; 4: the call had
 *                      not returned when the run ended (no outputs)
 *   cycles   4         from the routine's first instruction through its
 *                      return, as --call counts them
 *   inputs, then outputs, in the order of SPEC, little-endian
 *
 * Only reads of data through the direct page, DBR, a long address or a
 * pointer count for flag 2; program fetches, stack accesses and vectors
 * do not. A call inside a logged call is logged too, and flag 2 is
 * judged for the outermost call only, and never for an "inonly" routine.
 *
 * Deterministic, like the machine: the same files give the same output.
 */
#include "iigs.h"
#include "program.h"

#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    MAX_ROUTINES = 64,
    MAX_ITEMS = 16,
    MAX_TABLES = 16,
    MAX_ACTIVE = 256,
    HEADER_BYTES = 12,
    MAX_RECORD = 256,
    SPACE = 1 << 24
};

typedef struct {
    int reg;                /* 'a', 'x', 'y', or 0 for memory */
    uint32_t address;
    unsigned length;
} item;

typedef struct {
    char name[64];
    uint32_t address;
    int inputs_only;
    item in[MAX_ITEMS], out[MAX_ITEMS];
    unsigned in_count, out_count;
    uint32_t table_start[MAX_TABLES];
    uint32_t table_length[MAX_TABLES];
    unsigned table_count;
    unsigned in_bytes, out_bytes;
    FILE *log;
    uint64_t calls, logged;
    int entry_written;
    uint64_t undeclared;        /* reads of flag 2, and the first's */
    uint32_t undeclared_at, undeclared_pc;  /*   address and reader */
} routine;

static routine routines[MAX_ROUTINES];
static unsigned routine_count;
static uint8_t *is_entry;       /* a byte per 24-bit address: routine + 1 */

static void fail(const char *format, ...)
{
    va_list args;
    va_start(args, format);
    fputs("mathref: ", stderr);
    vfprintf(stderr, format, args);
    fputc('\n', stderr);
    va_end(args);
    exit(2);
}

static uint8_t *read_file(const char *path, size_t *length)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        fail("cannot open %s", path);
    if (fseek(f, 0, SEEK_END))
        fail("cannot read %s", path);
    long n = ftell(f);
    if (n < 0 || fseek(f, 0, SEEK_SET))
        fail("cannot read %s", path);
    uint8_t *data = malloc(n ? (size_t)n : 1);
    if (!data || fread(data, 1, (size_t)n, f) != (size_t)n)
        fail("cannot read %s", path);
    fclose(f);
    *length = (size_t)n;
    return data;
}

static uint32_t le(const uint8_t *p, unsigned bytes)
{
    uint32_t v = 0;
    for (unsigned i = bytes; i-- > 0;)
        v = v << 8 | p[i];
    return v;
}

/* ---- the spec ---- */

static int parse_item(const char *what, const char *length, item *it,
                      unsigned long most)
{
    if (!strcmp(what, "a") || !strcmp(what, "x") || !strcmp(what, "y")) {
        it->reg = what[0];
        it->address = 0;
        it->length = 2;
        return 1;
    }
    char *end;
    unsigned long address = strtoul(what, &end, 16);
    if (*end || address >= SPACE || !length)
        return 0;
    unsigned long n = strtoul(length, &end, 10);
    if (*end || n == 0 || n > most || address + n > SPACE)
        return 0;
    it->reg = 0;
    it->address = (uint32_t)address;
    it->length = (unsigned)n;
    return 1;
}

static void read_spec(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f)
        fail("cannot open %s", path);
    char line[512];
    unsigned number = 0;
    routine *r = NULL;
    while (fgets(line, sizeof line, f)) {
        number++;
        char *hash = strchr(line, '#');
        if (hash)
            *hash = 0;
        char *words[8];
        unsigned count = 0;
        for (char *w = strtok(line, " \t\r\n"); w && count < 8;
             w = strtok(NULL, " \t\r\n"))
            words[count++] = w;
        if (!count)
            continue;
        if (!strcmp(words[0], "routine")) {
            if (count < 3 || count > 4 || routine_count == MAX_ROUTINES ||
                strlen(words[1]) >= sizeof r->name)
                fail("%s:%u: routine NAME ADDR [inonly]", path, number);
            r = &routines[routine_count++];
            memset(r, 0, sizeof *r);
            strcpy(r->name, words[1]);
            char *end;
            unsigned long address = strtoul(words[2], &end, 16);
            if (*end || address >= SPACE)
                fail("%s:%u: bad address", path, number);
            r->address = (uint32_t)address;
            if (count == 4) {
                if (strcmp(words[3], "inonly"))
                    fail("%s:%u: routine NAME ADDR [inonly]", path, number);
                r->inputs_only = 1;
            }
            continue;
        }
        if (!r)
            fail("%s:%u: no routine yet", path, number);
        if (!strcmp(words[0], "in") || !strcmp(words[0], "out")) {
            int in = words[0][0] == 'i';
            item it = { 0, 0, 0 };
            if (count < 2 || count > 3 ||
                !parse_item(words[1], count == 3 ? words[2] : NULL, &it, 64))
                fail("%s:%u: in|out a|x|y|ADDR LEN", path, number);
            unsigned *n = in ? &r->in_count : &r->out_count;
            if (*n == MAX_ITEMS)
                fail("%s:%u: too many items", path, number);
            (in ? r->in : r->out)[(*n)++] = it;
            if (in)
                r->in_bytes += it.length;
            else
                r->out_bytes += it.length;
        } else if (!strcmp(words[0], "table")) {
            item it = { 0, 0, 0 };
            if (count != 3 || !parse_item(words[1], words[2], &it, SPACE) ||
                it.reg ||
                r->table_count == MAX_TABLES)
                fail("%s:%u: table ADDR LEN", path, number);
            r->table_start[r->table_count] = it.address;
            r->table_length[r->table_count++] = it.length;
        } else if (!strcmp(words[0], "tablerange")) {
            /* tablerange START END: a long range (END exclusive, hex) */
            char *end1, *end2;
            unsigned long a, b;
            if (count != 3 || r->table_count == MAX_TABLES)
                fail("%s:%u: tablerange START END", path, number);
            a = strtoul(words[1], &end1, 16);
            b = strtoul(words[2], &end2, 16);
            if (*end1 || *end2 || a >= b || b > SPACE)
                fail("%s:%u: tablerange START END", path, number);
            r->table_start[r->table_count] = (uint32_t)a;
            r->table_length[r->table_count++] = (uint32_t)(b - a);
        } else
            fail("%s:%u: unknown line %s", path, number, words[0]);
        if (HEADER_BYTES + r->in_bytes + r->out_bytes > MAX_RECORD)
            fail("%s:%u: the record is too long", path, number);
    }
    fclose(f);
    if (!routine_count)
        fail("%s: no routine", path);
}

static routine *find_routine(const char *name)
{
    for (unsigned i = 0; i < routine_count; i++)
        if (!strcmp(routines[i].name, name))
            return &routines[i];
    fail("no routine %s in the spec", name);
    return NULL;
}

/* ---- values ---- */

static void get_items(const iigs *m, const item *items, unsigned count,
                      uint8_t *out)
{
    for (unsigned i = 0; i < count; i++) {
        const item *it = &items[i];
        if (it->reg) {
            uint16_t v = it->reg == 'a' ? m->cpu.a : it->reg == 'x' ?
                m->cpu.x : m->cpu.y;
            *out++ = (uint8_t)v;
            *out++ = (uint8_t)(v >> 8);
        } else
            for (unsigned k = 0; k < it->length; k++)
                *out++ = iigs_peek(m, it->address + k);
    }
}

static void put_items(iigs *m, const item *items, unsigned count,
                      const uint8_t *in)
{
    for (unsigned i = 0; i < count; i++) {
        const item *it = &items[i];
        if (it->reg) {
            uint16_t v = (uint16_t)(in[0] | in[1] << 8);
            in += 2;
            if (it->reg == 'a')
                m->cpu.a = v;
            else if (it->reg == 'x')
                m->cpu.x = v;
            else
                m->cpu.y = v;
        } else {
            if (!iigs_load(m, it->address, in, it->length))
                fail("an input outside RAM");
            in += it->length;
        }
    }
}

/* ---- capture ---- */

typedef struct {
    routine *r;
    uint32_t ret;               /* PBR:PC after the return */
    uint16_t s;                 /* S at the entry (after the call's push) */
    unsigned ret_size;          /* 2 for RTS, 3 for RTL */
    uint64_t cycles, interrupts;
    uint8_t record[MAX_RECORD];
    uint8_t flags;
} active_call;

static iigs M;
static active_call active[MAX_ACTIVE];
static unsigned active_count;
static uint64_t lost_calls;
static uint8_t *written;        /* a bit per byte, for the outermost call */
static uint32_t *written_list;
static size_t written_count, written_max;
static cpu816_read_fn real_read;
static cpu816_write_fn real_write;
static const char *out_dir;

static int allowed_read(const routine *r, uint32_t a)
{
    for (unsigned i = 0; i < r->in_count; i++)
        if (!r->in[i].reg && a - r->in[i].address < r->in[i].length)
            return 1;
    for (unsigned i = 0; i < r->table_count; i++)
        if (a - r->table_start[i] < r->table_length[i])
            return 1;
    return 0;
}

static uint8_t watch_read(void *context, uint32_t a)
{
    uint8_t v = real_read(context, a);
    a &= 0xffffff;
    if (active_count && (M.cpu.space == CPU816_DIRECT ||
                         M.cpu.space == CPU816_DATA)) {
        active_call *c = &active[0];
        if (!c->r->inputs_only && c->interrupts == M.counts.interrupts &&
            !(written[a >> 3] >> (a & 7) & 1) && !allowed_read(c->r, a)) {
            c->flags |= 2;
            if (!c->r->undeclared++) {
                c->r->undeclared_at = a;
                c->r->undeclared_pc = M.opcode_pc;
            }
        }
    }
    return v;
}

static void watch_write(void *context, uint32_t a, uint8_t v)
{
    real_write(context, a, v);
    a &= 0xffffff;
    if (active_count && !(written[a >> 3] >> (a & 7) & 1)) {
        written[a >> 3] |= (uint8_t)(1u << (a & 7));
        if (written_count == written_max) {
            written_max = written_max ? 2 * written_max : 4096;
            written_list = realloc(written_list,
                                   written_max * sizeof *written_list);
            if (!written_list)
                fail("out of memory");
        }
        written_list[written_count++] = a;
    }
}

static void write_entry(const routine *r, const active_call *c)
{
    char path[1024];
    snprintf(path, sizeof path, "%s/%s.entry", out_dir, r->name);
    FILE *f = fopen(path, "w");
    if (!f)
        fail("cannot write %s", path);
    const cpu816 *cpu = &M.cpu;
    fprintf(f, "pc %06" PRIX32 "\ndbr %02X\nd %04X\np %02X\ne %u\n"
            "s %04X\na %04X\nx %04X\ny %04X\nret %u\n",
            r->address, cpu->dbr, cpu->d, cpu->p, cpu->e, cpu->s, cpu->a,
            cpu->x, cpu->y, c->ret_size);
    fprintf(f, "stack");
    for (unsigned k = 1; k <= c->ret_size; k++)
        fprintf(f, " %02X", iigs_peek(&M, (uint16_t)(cpu->s + k)));
    fprintf(f, "\nswitches %02X %02X %02X %02X\n", M.newvideo, M.border,
            M.shadow, M.speed);
    if (fclose(f))
        fail("cannot write %s", path);
}

static void finish(active_call *c, int returned)
{
    routine *r = c->r;
    uint8_t *rec = c->record;
    uint64_t cycles = M.cpu.cycles - c->cycles;
    if (!returned)
        c->flags |= 4;
    if (c->interrupts != M.counts.interrupts)
        c->flags |= 1;
    rec[7] = c->flags;
    uint32_t cyc = cycles > UINT32_MAX ? UINT32_MAX : (uint32_t)cycles;
    rec[8] = (uint8_t)cyc;
    rec[9] = (uint8_t)(cyc >> 8);
    rec[10] = (uint8_t)(cyc >> 16);
    rec[11] = (uint8_t)(cyc >> 24);
    size_t size = HEADER_BYTES + r->in_bytes;
    if (!r->inputs_only) {
        if (returned)
            get_items(&M, r->out, r->out_count, rec + size);
        else
            memset(rec + size, 0, r->out_bytes);
        size += r->out_bytes;
    }
    if (fwrite(rec, 1, size, r->log) != size)
        fail("cannot write the log of %s", r->name);
    r->logged++;
}

static void clear_written(void)
{
    for (size_t i = 0; i < written_count; i++) {
        uint32_t a = written_list[i];
        written[a >> 3] &= (uint8_t)~(1u << (a & 7));
    }
    written_count = 0;
}

static void after_step(void *context)
{
    (void)context;
    cpu816 *cpu = &M.cpu;
    uint32_t pc = (uint32_t)cpu->pbr << 16 | cpu->pc;
    uint8_t op = M.opcode;
    /* a return of the innermost logged call */
    if ((op == 0x60 || op == 0x6b) && active_count) {
        active_call *c = &active[active_count - 1];
        if (cpu->s == (uint16_t)(c->s + c->ret_size) && pc == c->ret) {
            finish(c, 1);
            active_count--;
            if (!active_count)
                clear_written();
        }
    }
    /* a call of a routine of the spec */
    if ((op == 0x20 || op == 0x22 || op == 0xfc) && is_entry[pc]) {
        routine *r = &routines[is_entry[pc] - 1];
        r->calls++;
        if (active_count == MAX_ACTIVE) {
            lost_calls++;
            return;
        }
        active_call *c = &active[active_count++];
        c->r = r;
        c->s = cpu->s;
        c->ret_size = op == 0x22 ? 3 : 2;
        uint32_t ret = (uint32_t)iigs_peek(&M, (uint16_t)(cpu->s + 1)) |
                       (uint32_t)iigs_peek(&M, (uint16_t)(cpu->s + 2)) << 8;
        uint32_t bank = c->ret_size == 3 ?
            iigs_peek(&M, (uint16_t)(cpu->s + 3)) : cpu->pbr;
        c->ret = bank << 16 | ((ret + 1) & 0xffff);
        c->cycles = cpu->cycles;
        c->interrupts = M.counts.interrupts;
        c->flags = 0;
        uint8_t *rec = c->record;
        uint32_t site = bank << 16 | ret;
        rec[0] = (uint8_t)site;
        rec[1] = (uint8_t)(site >> 8);
        rec[2] = (uint8_t)(site >> 16);
        rec[3] = (uint8_t)cpu->d;
        rec[4] = (uint8_t)(cpu->d >> 8);
        rec[5] = cpu->dbr;
        rec[6] = cpu->p;
        get_items(&M, r->in, r->in_count, rec + HEADER_BYTES);
        if (!r->entry_written) {
            write_entry(r, c);
            r->entry_written = 1;
        }
    }
}

static void load_image(iigs *m, const char *path)
{
    size_t length;
    uint8_t *data = read_file(path, &length);
    if (length < 32 || memcmp(data, "REF816I1", 8))
        fail("%s is not a ref816 memory image", path);
    cpu816 *c = &m->cpu;
    c->pc = (uint16_t)le(data + 8, 2);
    c->pbr = data[10];
    c->dbr = data[11];
    c->a = (uint16_t)le(data + 12, 2);
    c->x = (uint16_t)le(data + 14, 2);
    c->y = (uint16_t)le(data + 16, 2);
    c->s = (uint16_t)le(data + 18, 2);
    c->d = (uint16_t)le(data + 20, 2);
    c->p = data[22];
    c->e = data[23] & 1;
    cpu816_normalise(c);
    iigs_set_switches(m, data[24], data[25], data[26], data[27]);
    size_t at = 32;
    while (at < length) {
        if (length - at < 8)
            fail("%s: a record is cut short", path);
        uint32_t address = le(data + at, 4), count = le(data + at + 4, 4);
        at += 8;
        if (count > length - at || !iigs_load(m, address, data + at, count))
            fail("%s: a bad record", path);
        at += count;
    }
    free(data);
}

static void write_ram(const iigs *m, const char *path)
{
    FILE *f = fopen(path, "wb");
    if (!f ||
        fwrite(m->ram, IIGS_BANK, IIGS_RAM_BANKS, f) != IIGS_RAM_BANKS ||
        fwrite(m->mega, IIGS_BANK, 2, f) != 2 || fclose(f))
        fail("cannot write %s", path);
}

static int capture(int argc, char **argv)
{
    if (argc != 8)
        fail("usage: mathref capture IMAGE DISK INPUT FRAMES SPEC OUTDIR");
    const char *image = argv[2], *disk_path = argv[3], *input = argv[4];
    uint64_t frames = strtoull(argv[5], NULL, 10);
    read_spec(argv[6]);
    out_dir = argv[7];

    if (!iigs_init(&M))
        fail("out of memory");
    load_image(&M, image);
    size_t disk_length;
    uint8_t *disk = read_file(disk_path, &disk_length);
    if (disk_length % 512)
        fail("%s is not whole blocks", disk_path);
    iigs_attach_disk(&M, disk, disk_length);
    program p;
    char error[512];
    program_init(&p);
    if (!program_read(&p, input, error, sizeof error))
        fail("%s", error);

    is_entry = calloc(SPACE, 1);
    written = calloc(SPACE / 8, 1);
    if (!is_entry || !written)
        fail("out of memory");
    for (unsigned i = 0; i < routine_count; i++) {
        routine *r = &routines[i];
        if (is_entry[r->address])
            fail("two routines at %06" PRIX32, r->address);
        is_entry[r->address] = (uint8_t)(i + 1);
        char path[1024];
        snprintf(path, sizeof path, "%s/%s.bin", out_dir, r->name);
        if (!(r->log = fopen(path, "wb")))
            fail("cannot write %s", path);
    }
    real_read = M.cpu.read;
    real_write = M.cpu.write;
    M.cpu.read = watch_read;
    M.cpu.write = watch_write;
    M.after_step = after_step;
    M.step_context = NULL;

    const char *end = NULL;
    for (;;) {
        const step *s = NULL;
        program_result result;
        while ((result = program_step(&p, &M, &s)) != PROGRAM_IDLE &&
               result != PROGRAM_END) {
            if (result == PROGRAM_STOP)
                end = "stop";
            else if (result == PROGRAM_TIMEOUT)
                end = "timeout";
            else if (result == PROGRAM_LATE)
                end = "late";
            if (end)
                break;
        }
        if (end)
            break;
        if (M.frame >= frames) {
            end = "frames";
            break;
        }
        uint64_t due = program_due(&p);
        iigs_run(&M, UINT64_MAX, due < frames ? due : frames);
    }
    /* calls still open: logged with flag 4 */
    while (active_count)
        finish(&active[--active_count], 0);

    char path[1024];
    snprintf(path, sizeof path, "%s/base.ram", out_dir);
    write_ram(&M, path);
    snprintf(path, sizeof path, "%s/summary.txt", out_dir);
    FILE *f = fopen(path, "w");
    if (!f)
        fail("cannot write %s", path);
    fprintf(f, "end %s\nframes %" PRIu64 "\ncycles %" PRIu64
            "\ninterrupts %" PRIu64 "\nlost %" PRIu64 "\n", end, M.frame,
            M.cpu.cycles, M.counts.interrupts, lost_calls);
    for (unsigned i = 0; i < routine_count; i++) {
        routine *r = &routines[i];
        fprintf(f, "routine %s calls %" PRIu64 " logged %" PRIu64,
                r->name, r->calls, r->logged);
        if (r->undeclared)
            fprintf(f, " undeclared %" PRIu64 " first %06" PRIX32
                    " by %06" PRIX32, r->undeclared, r->undeclared_at,
                    r->undeclared_pc);
        fputc('\n', f);
        if (fclose(r->log))
            fail("cannot write the log of %s", r->name);
    }
    if (fclose(f))
        fail("cannot write %s", path);
    free(disk);
    program_free(&p);
    iigs_free(&M);
    return strcmp(end, "stop") ? 1 : 0;
}

/* ---- batch ---- */

typedef struct {
    uint32_t pc;
    uint8_t dbr, p, e;
    uint16_t d, s, a, x, y;
    unsigned ret_size;
    uint8_t stack[3];
    uint8_t switches[4];
} entry_state;

static void read_entry(const char *path, entry_state *e)
{
    FILE *f = fopen(path, "r");
    if (!f)
        fail("cannot open %s", path);
    char key[32];
    unsigned v[4];
    memset(e, 0, sizeof *e);
    int seen = 0;
    while (fscanf(f, "%31s", key) == 1) {
        if (!strcmp(key, "stack")) {
            for (unsigned k = 0; k < e->ret_size; k++) {
                if (fscanf(f, "%x", &v[0]) != 1)
                    fail("%s: bad stack", path);
                e->stack[k] = (uint8_t)v[0];
            }
            seen |= 1;
            continue;
        }
        if (!strcmp(key, "switches")) {
            if (fscanf(f, "%x %x %x %x", &v[0], &v[1], &v[2], &v[3]) != 4)
                fail("%s: bad switches", path);
            for (unsigned k = 0; k < 4; k++)
                e->switches[k] = (uint8_t)v[k];
            seen |= 2;
            continue;
        }
        if (!strcmp(key, "ret")) {
            if (fscanf(f, "%u", &v[0]) != 1 || (v[0] != 2 && v[0] != 3))
                fail("%s: bad ret", path);
            e->ret_size = v[0];
            continue;
        }
        if (fscanf(f, "%x", &v[0]) != 1)
            fail("%s: bad %s", path, key);
        if (!strcmp(key, "pc"))
            e->pc = v[0];
        else if (!strcmp(key, "dbr"))
            e->dbr = (uint8_t)v[0];
        else if (!strcmp(key, "d"))
            e->d = (uint16_t)v[0];
        else if (!strcmp(key, "p"))
            e->p = (uint8_t)v[0];
        else if (!strcmp(key, "e"))
            e->e = (uint8_t)v[0];
        else if (!strcmp(key, "s"))
            e->s = (uint16_t)v[0];
        else if (!strcmp(key, "a"))
            e->a = (uint16_t)v[0];
        else if (!strcmp(key, "x"))
            e->x = (uint16_t)v[0];
        else if (!strcmp(key, "y"))
            e->y = (uint16_t)v[0];
        else
            fail("%s: unknown %s", path, key);
    }
    fclose(f);
    if (seen != 3 || !e->ret_size)
        fail("%s: incomplete", path);
}

static const entry_state *batch_entry;
static int batch_returned;

static void batch_step(void *context)
{
    (void)context;
    const cpu816 *cpu = &M.cpu;
    if ((M.opcode == 0x60 || M.opcode == 0x6b) &&
        cpu->s == (uint16_t)(batch_entry->s + batch_entry->ret_size)) {
        batch_returned = 1;
        M.stop_request = 1;
    }
}

static int batch(int argc, char **argv)
{
    if (argc != 8)
        fail("usage: mathref batch RAM ENTRY SPEC NAME CASES OUT");
    entry_state e;
    read_entry(argv[3], &e);
    read_spec(argv[4]);
    routine *r = find_routine(argv[5]);
    if (r->inputs_only)
        fail("%s has no outputs", r->name);
    if (e.pc != r->address)
        fail("%s: the entry is not the routine's", argv[3]);
    size_t length;
    uint8_t *ram = read_file(argv[2], &length);
    if (length != (size_t)(IIGS_RAM_BANKS + 2) * IIGS_BANK)
        fail("%s is not a whole RAM", argv[2]);
    size_t case_length;
    uint8_t *cases = read_file(argv[6], &case_length);
    if (!r->in_bytes || case_length % r->in_bytes)
        fail("%s is not whole cases", argv[6]);
    FILE *out = fopen(argv[7], "wb");
    if (!out)
        fail("cannot write %s", argv[7]);

    if (!iigs_init(&M))
        fail("out of memory");
    memcpy(M.ram, ram, (size_t)IIGS_RAM_BANKS * IIGS_BANK);
    memcpy(M.mega, ram + (size_t)IIGS_RAM_BANKS * IIGS_BANK, 2 * IIGS_BANK);
    free(ram);
    iigs_set_switches(&M, e.switches[0], e.switches[1], e.switches[2],
                      e.switches[3]);
    batch_entry = &e;
    M.after_step = batch_step;

    size_t n = case_length / r->in_bytes;
    uint8_t buffer[MAX_RECORD];
    for (size_t i = 0; i < n; i++) {
        cpu816 *c = &M.cpu;
        c->pbr = (uint8_t)(e.pc >> 16);
        c->pc = (uint16_t)e.pc;
        c->dbr = e.dbr;
        c->d = e.d;
        c->p = e.p;
        c->e = e.e;
        c->s = e.s;
        c->a = e.a;
        c->x = e.x;
        c->y = e.y;
        c->state = CPU816_RUNNING;
        cpu816_normalise(c);
        for (unsigned k = 0; k < e.ret_size; k++)
            M.ram[(uint16_t)(e.s + 1 + k)] = e.stack[k];
        put_items(&M, r->in, r->in_count, cases + i * r->in_bytes);
        cpu816_normalise(c);
        uint64_t start = c->cycles, interrupts = M.counts.interrupts;
        batch_returned = 0;
        iigs_run(&M, start + 100000000u, UINT64_MAX);
        if (!batch_returned)
            fail("case %zu of %s did not return", i, r->name);
        if (M.counts.interrupts != interrupts)
            fail("case %zu of %s was interrupted", i, r->name);
        get_items(&M, r->out, r->out_count, buffer);
        uint32_t cycles = (uint32_t)(c->cycles - start);
        buffer[r->out_bytes] = (uint8_t)cycles;
        buffer[r->out_bytes + 1] = (uint8_t)(cycles >> 8);
        buffer[r->out_bytes + 2] = (uint8_t)(cycles >> 16);
        buffer[r->out_bytes + 3] = (uint8_t)(cycles >> 24);
        if (fwrite(buffer, 1, r->out_bytes + 4, out) != r->out_bytes + 4)
            fail("cannot write %s", argv[7]);
    }
    if (fclose(out))
        fail("cannot write %s", argv[7]);
    free(cases);
    iigs_free(&M);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc >= 2 && !strcmp(argv[1], "capture"))
        return capture(argc, argv);
    if (argc >= 2 && !strcmp(argv[1], "batch"))
        return batch(argc, argv);
    fail("usage: mathref capture ... | mathref batch ... (see the source)");
    return 2;
}
