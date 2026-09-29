/*
 * ref816: run upstream's DOOM on the minimal IIgs of iigs.c.
 *
 * usage: ref816 [options] IMAGE
 *
 *   IMAGE              a memory image from tools/ref816/make_image.py
 *   --frames N         stop when video frame N starts
 *   --cycles N         stop after N CPU cycles (at least one of the two)
 *   --cpu-hz N         the CPU rate of fast mode (default: 2863636, the
 *                      IIgs's 5 master clocks a cycle); see iigs.h
 *   --stop-pc ADDR     stop before the instruction at ADDR (hex, 24 bits;
 *                      repeatable)
 *   --stop-on-fault    stop after an instruction that jumps to itself,
 *                      and after WDM or STP (iigs_run)
 *   --mark ADDR        log each time the CPU reaches ADDR (hex; repeatable)
 *   --marks FILE       where the log goes, a line a time: "mark", the
 *                      address (hex), the master clock, the CPU cycles
 *                      and the instructions before the one at the
 *                      address; "note", the name, the same counts for
 *                      each note of the input; and last "end -" with
 *                      the counts at the end of the run
 *   --disk FILE        the disk the firmware traps serve (read into memory;
 *                      the file itself is never written)
 *   --disk-out FILE    write the disk, with the game's writes, to FILE at
 *                      the end
 *   --input FILE       the input program (program.h): keys, mouse, shots,
 *                      waits on memory, pokes, stop
 *   --shot-frame N     dump the screen when frame N starts (repeatable)
 *   --shot-cycle N     dump the screen after N cycles (repeatable)
 *   --shot-dir DIR     where the dumps go (default .): frame-NNNNNN.shr,
 *                      cycle-NNNNNNNNNNNN.shr, or NAME.shr for a shot of
 *                      the input, each $E1:2000-$9FFF (32768 bytes) then
 *                      $C034 and $C029
 *   --peek ADDR:LEN    bytes of RAM to put in the final state (hex address)
 *   --state FILE       write the final state there (default: stdout)
 *   --dump-ram FILE    write banks $00-$7F then $E0-$E1 there at the end
 *
 * Tracing (trace.h; without --trace the machine runs untraced):
 *
 *   --trace FILE       write the trace there
 *   --trace-frame ADDR a call to ADDR (hex) starts a frame of the game
 *   --trace-phase NAME=ADDR
 *                      a call to ADDR (hex) enters the phase NAME
 *                      (repeatable; a phase may have several entries)
 *   --trace-from NOTE  record the frames after this note of the input
 *   --trace-to NOTE    and before this one (default: the start, the end)
 *   --trace-near BANK  a bank (hex) whose data is not far (repeatable)
 *   --trace-stack-split ADDR
 *                      S at or below ADDR (hex) is the second stack
 *   --trace-samples FILE
 *                      write samples of the recorded instructions there
 *   --trace-sample-every N
 *                      one instruction in N (default 499)
 *
 * The final state is JSON: why the run ended, time, registers, a hash of
 * all RAM, the soft switches, the text page, and the counts of
 * everything the machine met that it does not model.
 */
#include "iigs.h"
#include "program.h"
#include "trace.h"

#include <errno.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    MAX_LIST = 256,
    SHOT_START = 0x2000, SHOT_LENGTH = 0x8000,
    HEADER = 32,
    TEXT_ROWS = 24, TEXT_COLUMNS = 40
};

static const char MAGIC[] = "REF816I1";     /* 8 bytes, no NUL */

typedef struct {
    uint32_t address;
    uint32_t length;
} peek_range;

typedef struct {
    const char *image, *disk, *disk_out, *input, *shot_dir, *state, *dump;
    const char *marks;
    uint64_t frames, cycles;
    uint32_t cpu_hz;
    int stop_on_fault;
    uint64_t stop_pcs[MAX_LIST], mark_pcs[MAX_LIST];
    unsigned stop_pc_count, mark_pc_count;
    uint64_t shot_frames[MAX_LIST], shot_cycles[MAX_LIST];
    unsigned shot_frame_count, shot_cycle_count;
    peek_range peeks[MAX_LIST];
    unsigned peek_count;
    trace_config trace;         /* trace.path is NULL without --trace */
    int trace_options;          /* --trace-* options given */
} options;

/* How the run ended. */
typedef struct {
    const char *reason;         /* frames, cycles, stop, stop-pc, spin,
                                   opcode, timeout, late */
    uint32_t pc;                /* stop-pc, spin, opcode: where */
    unsigned line;              /* stop, timeout, late: the input line */
} ending;

static void fail(const char *format, ...)
{
    va_list arguments;
    va_start(arguments, format);
    fputs("ref816: ", stderr);
    vfprintf(stderr, format, arguments);
    fputc('\n', stderr);
    va_end(arguments);
    exit(2);
}

static uint64_t number(const char *text, int base)
{
    char *end;
    errno = 0;
    unsigned long long value = strtoull(text, &end, base);
    if (errno || end == text || *end)
        fail("not a number: %s", text);
    return value;
}

/* ---- files ---- */

static uint8_t *read_file(const char *path, size_t *length)
{
    FILE *file = fopen(path, "rb");
    if (!file)
        fail("cannot open %s: %s", path, strerror(errno));
    size_t capacity = 1 << 20, used = 0;
    uint8_t *data = malloc(capacity);
    for (;;) {
        if (!data)
            fail("out of memory reading %s", path);
        used += fread(data + used, 1, capacity - used, file);
        if (used < capacity)
            break;
        capacity *= 2;
        data = realloc(data, capacity);
    }
    if (ferror(file))
        fail("cannot read %s", path);
    fclose(file);
    *length = used;
    return data;
}

static void write_file(const char *path, const uint8_t *data, size_t length)
{
    FILE *file = fopen(path, "wb");
    if (!file || fwrite(data, 1, length, file) != length || fclose(file))
        fail("cannot write %s", path);
}

static uint32_t le(const uint8_t *p, int bytes)
{
    uint32_t value = 0;
    for (int i = bytes - 1; i >= 0; i--)
        value = value << 8 | p[i];
    return value;
}

/* The image: a header with the registers and the soft switches, then
   records of a 32-bit address, a 32-bit length and the bytes. */
static void load_image(iigs *m, const char *path)
{
    size_t length;
    uint8_t *data = read_file(path, &length);
    if (length < HEADER || memcmp(data, MAGIC, sizeof MAGIC - 1))
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
    size_t at = HEADER;
    while (at < length) {
        if (length - at < 8)
            fail("%s: a record is cut short", path);
        uint32_t address = le(data + at, 4), count = le(data + at + 4, 4);
        at += 8;
        if (count > length - at)
            fail("%s: the record at $%06" PRIX32 " is cut short", path,
                 address);
        if (!iigs_load(m, address, data + at, count))
            fail("%s: the record at $%06" PRIX32 " is outside RAM", path,
                 address);
        at += count;
    }
    free(data);
}

/* ---- screen dumps ---- */

static void shot(const iigs *m, const char *directory, const char *name)
{
    uint8_t data[SHOT_LENGTH + 2];
    char path[1024];
    for (unsigned i = 0; i < SHOT_LENGTH; i++)
        data[i] = iigs_peek(m, 0xe10000u + SHOT_START + i);
    data[SHOT_LENGTH] = m->border;
    data[SHOT_LENGTH + 1] = m->newvideo;
    snprintf(path, sizeof path, "%s/%s.shr", directory, name);
    write_file(path, data, sizeof data);
}

static void numbered_shot(const iigs *m, const char *directory,
                          const char *kind, uint64_t when, int digits)
{
    char name[64];
    snprintf(name, sizeof name, "%s-%0*" PRIu64, kind, digits, when);
    shot(m, directory, name);
}

/* ---- the final state ---- */

static void text_row(const iigs *m, unsigned row, char out[TEXT_COLUMNS + 1])
{
    uint32_t base = 0xe00400u + (row % 8) * 0x80 + (row / 8) * 0x28;
    for (unsigned i = 0; i < TEXT_COLUMNS; i++) {
        uint8_t c = iigs_peek(m, base + i) & 0x7f;
        if (c < 0x20)
            c = (uint8_t)(c + 0x40);    /* inverse and flashing letters */
        if (c == '"' || c == '\\' || c == 0x7f)
            c = ' ';
        out[i] = (char)c;
    }
    out[TEXT_COLUMNS] = 0;
}

static void counts_json(FILE *out, const char *name, const uint32_t *counts)
{
    const char *separator = "";
    fprintf(out, "    \"%s\": {", name);
    for (unsigned i = 0; i < 256; i++) {
        if (counts[i]) {
            fprintf(out, "%s\"C0%02X\": %" PRIu32, separator, i, counts[i]);
            separator = ", ";
        }
    }
    fputs("},\n", out);
}

/* Read sites (iigs_read_site) as a list of objects, addresses as numbers. */
static void sites_json(FILE *out, const char *name,
                       const iigs_read_site *sites, unsigned count)
{
    fprintf(out, "    \"%s\": [", name);
    for (unsigned i = 0; i < count; i++)
        fprintf(out, "%s{\"pc\": %" PRIu32 ", \"first\": %" PRIu32
                ", \"last\": %" PRIu32 ", \"count\": %" PRIu64 "}",
                i ? ", " : "", sites[i].pc, sites[i].first, sites[i].last,
                sites[i].count);
    fputs("],\n", out);
}

static void write_state(const iigs *m, const options *o, const ending *end,
                        FILE *out)
{
    const cpu816 *c = &m->cpu;
    const iigs_counts *n = &m->counts;
    static const char *states[] = { "running", "waiting", "stopped" };
    uint64_t clock = iigs_clock(m);

    fprintf(out, "{\n  \"end\": {\"reason\": \"%s\", \"pc\": %" PRIu32
            ", \"line\": %u},\n", end->reason, end->pc, end->line);
    fprintf(out, "  \"cycles\": %" PRIu64 ",\n", c->cycles);
    fprintf(out, "  \"instructions\": %" PRIu64 ",\n", m->instructions);
    fprintf(out, "  \"master_clocks\": %" PRIu64 ",\n", clock);
    fprintf(out, "  \"seconds\": %.6f,\n", (double)clock / IIGS_MASTER_HZ);
    fprintf(out, "  \"cpu_hz\": %.1f,\n",
            (double)IIGS_MASTER_HZ * m->fast_den / m->fast_num);
    fprintf(out, "  \"frames\": %" PRIu64 ",\n", m->frame);
    fprintf(out, "  \"stopped_at_pc\": %s,\n",
            strcmp(end->reason, "stop-pc") ? "false" : "true");
    fprintf(out, "  \"cpu\": {\"pc\": %" PRIu32 ", \"a\": %u, \"x\": %u, "
            "\"y\": %u, \"s\": %u, \"d\": %u, \"dbr\": %u, \"p\": %u, "
            "\"e\": %u, \"state\": \"%s\"},\n",
            (uint32_t)c->pbr << 16 | c->pc, c->a, c->x, c->y, c->s, c->d,
            c->dbr, c->p, c->e, states[c->state]);
    fprintf(out, "  \"ram_fnv1a64\": \"%016" PRIx64 "\",\n",
            iigs_ram_hash(m));
    fprintf(out, "  \"switches\": {\"shadow\": %u, \"speed\": %u, "
            "\"newvideo\": %u, \"border\": %u, \"text\": %u, "
            "\"inten\": %u, \"vgc_int\": %u},\n", m->shadow, m->speed,
            m->newvideo, m->border, m->text, m->inten, m->vgc_int);
    fprintf(out, "  \"doc\": {\"samples\": %" PRIu64 ", \"enable\": %u},\n",
            m->doc.samples, m->doc.enable);
    fprintf(out, "  \"firmware\": {\"driver_calls\": %" PRIu64
            ", \"smartport_calls\": %" PRIu64 ", \"errors\": %" PRIu64
            ", \"cycles\": %" PRIu64 ", \"disk_written\": %s},\n",
            n->driver_calls, n->smartport_calls, n->firmware_errors,
            n->firmware_cycles, m->disk_written ? "true" : "false");
    fprintf(out, "  \"interrupts\": %" PRIu64 ",\n", n->interrupts);
    fprintf(out, "  \"opcodes\": {\"brk\": %" PRIu64 ", \"cop\": %" PRIu64
            ", \"wdm\": %" PRIu64 ", \"stp\": %" PRIu64
            ", \"first_brk_pc\": %" PRIu32 "},\n", n->brk, n->cop, n->wdm,
            n->stp, n->first_brk_pc);
    fputs("  \"unmodelled\": {\n", out);
    counts_json(out, "io_reads", n->io_reads);
    counts_json(out, "io_writes", n->io_writes);
    fprintf(out, "    \"rom_reads\": %" PRIu64 ", \"rom_writes\": %" PRIu64
            ", \"slot_rom_reads\": %" PRIu64 ",\n", n->rom_reads,
            n->rom_writes, n->slot_rom_reads);
    fprintf(out, "    \"unmapped_reads\": %" PRIu64 ", \"unmapped_writes\": %"
            PRIu64 ",\n", n->unmapped_reads, n->unmapped_writes);
    sites_json(out, "rom_read_sites", n->rom_read_sites,
               n->rom_read_site_count);
    sites_json(out, "unmapped_read_sites", n->unmapped_read_sites,
               n->unmapped_read_site_count);
    fprintf(out, "    \"read_sites_lost\": %" PRIu64 ",\n",
            n->read_sites_lost);
    fprintf(out, "    \"adb_unknown_commands\": %u, \"adb_last_unknown\": %u, "
            "\"adb_system_resets\": %u\n  },\n", m->adb.unknown_commands,
            m->adb.last_unknown, m->adb.system_resets);
    fputs("  \"peek\": {", out);
    for (unsigned i = 0; i < o->peek_count; i++) {
        fprintf(out, "%s\"%06" PRIX32 "\": \"", i ? ", " : "",
                o->peeks[i].address);
        for (uint32_t j = 0; j < o->peeks[i].length; j++)
            fprintf(out, "%02x", iigs_peek(m, o->peeks[i].address + j));
        fputc('"', out);
    }
    fputs("},\n  \"text_page\": [\n", out);
    for (unsigned row = 0; row < TEXT_ROWS; row++) {
        char text[TEXT_COLUMNS + 1];
        text_row(m, row, text);
        fprintf(out, "    \"%s\"%s\n", text, row + 1 < TEXT_ROWS ? "," : "");
    }
    fputs("  ]\n}\n", out);
}

/* ---- the command line ---- */

static void add(uint64_t *list, unsigned *count, uint64_t value)
{
    if (*count == MAX_LIST)
        fail("at most %d of each option", MAX_LIST);
    list[(*count)++] = value;
}

static uint64_t address(const char *text, const char *option)
{
    uint64_t value = number(text, 16);
    if (value > 0xffffff)
        fail("%s takes a 24-bit address", option);
    return value;
}

/* A --trace-* option (not --trace itself); 0 when `arg` is none. */
static int trace_option(trace_config *c, const char *arg, char *value)
{
    if (!strcmp(arg, "--trace-frame"))
        c->frame_entry = (uint32_t)address(value, arg);
    else if (!strcmp(arg, "--trace-phase")) {
        char *equals = strchr(value, '=');
        if (!equals || equals == value)
            fail("--trace-phase takes NAME=ADDR");
        *equals = 0;
        if (!trace_config_phase(c, value,
                                (uint32_t)address(equals + 1, arg)))
            fail("--trace-phase: at most %d phases and %d entries, and "
                 "not \"other\" or \"interrupt\"", TRACE_MAX_PHASES - 2,
                 TRACE_MAX_ENTRIES);
    } else if (!strcmp(arg, "--trace-from"))
        c->from = value;
    else if (!strcmp(arg, "--trace-to"))
        c->to = value;
    else if (!strcmp(arg, "--trace-near")) {
        uint64_t bank = number(value, 16);
        if (bank > 0xff)
            fail("--trace-near takes a bank, 00-FF");
        c->near[bank] = 1;
    } else if (!strcmp(arg, "--trace-stack-split")) {
        uint64_t split = number(value, 16);
        if (split > 0xffff)
            fail("--trace-stack-split takes a 16-bit address");
        c->stack_split = (uint16_t)split;
    } else if (!strcmp(arg, "--trace-samples"))
        c->sample_path = value;
    else if (!strcmp(arg, "--trace-sample-every")) {
        uint64_t every = number(value, 10);
        if (!every || every > UINT32_MAX)
            fail("--trace-sample-every takes a count from 1");
        c->sample_every = (uint32_t)every;
    } else
        return 0;
    return 1;
}

static void parse(int argc, char **argv, options *o)
{
    memset(o, 0, sizeof *o);
    o->frames = o->cycles = UINT64_MAX;
    o->shot_dir = ".";
    trace_config_init(&o->trace, NULL);
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (arg[0] != '-') {
            if (o->image)
                fail("one image only");
            o->image = arg;
            continue;
        }
        if (!strcmp(arg, "--stop-on-fault")) {
            o->stop_on_fault = 1;
            continue;
        }
        if (i + 1 == argc)
            fail("%s needs a value", arg);
        const char *value = argv[++i];
        if (!strcmp(arg, "--frames"))
            o->frames = number(value, 0);
        else if (!strcmp(arg, "--cycles"))
            o->cycles = number(value, 0);
        else if (!strcmp(arg, "--cpu-hz")) {
            uint64_t hz = number(value, 0);
            if (hz < 100000 || hz > 1000000000)
                fail("--cpu-hz takes 100000 to 1000000000");
            o->cpu_hz = (uint32_t)hz;
        } else if (!strcmp(arg, "--stop-pc"))
            add(o->stop_pcs, &o->stop_pc_count, address(value, arg));
        else if (!strcmp(arg, "--mark"))
            add(o->mark_pcs, &o->mark_pc_count, address(value, arg));
        else if (!strcmp(arg, "--marks"))
            o->marks = value;
        else if (!strcmp(arg, "--dump-ram"))
            o->dump = value;
        else if (!strcmp(arg, "--disk"))
            o->disk = value;
        else if (!strcmp(arg, "--disk-out"))
            o->disk_out = value;
        else if (!strcmp(arg, "--input"))
            o->input = value;
        else if (!strcmp(arg, "--shot-frame"))
            add(o->shot_frames, &o->shot_frame_count, number(value, 0));
        else if (!strcmp(arg, "--shot-cycle"))
            add(o->shot_cycles, &o->shot_cycle_count, number(value, 0));
        else if (!strcmp(arg, "--shot-dir"))
            o->shot_dir = value;
        else if (!strcmp(arg, "--state"))
            o->state = value;
        else if (!strcmp(arg, "--trace"))
            o->trace.path = value;
        else if (trace_option(&o->trace, arg, argv[i]))
            o->trace_options = 1;
        else if (!strcmp(arg, "--peek")) {
            char *colon = strchr(value, ':');
            if (!colon || o->peek_count == MAX_LIST)
                fail("--peek takes ADDR:LEN");
            *colon = 0;
            peek_range *p = &o->peeks[o->peek_count++];
            p->address = (uint32_t)number(value, 16);
            p->length = (uint32_t)number(colon + 1, 0);
            if (p->address > 0xffffff || p->length > 0x10000)
                fail("--peek: at most 64 KB of a 24-bit address");
        } else
            fail("unknown option %s", arg);
    }
    if (!o->image)
        fail("usage: ref816 [options] IMAGE (see the source for options)");
    if (o->frames == UINT64_MAX && o->cycles == UINT64_MAX)
        fail("give --frames or --cycles");
    if (o->mark_pc_count && !o->marks)
        fail("--mark needs --marks");
    if (o->trace_options && !o->trace.path)
        fail("the --trace-* options need --trace");
}

static int compare_u64(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return (x > y) - (x < y);
}

/* The first of `count` sorted values from `*next` on, or UINT64_MAX. */
static uint64_t upcoming(const uint64_t *list, unsigned count, unsigned next)
{
    return next < count ? list[next] : UINT64_MAX;
}

static uint64_t minimum(uint64_t a, uint64_t b)
{
    return a < b ? a : b;
}

static int listed(const uint64_t *list, unsigned count, uint32_t value)
{
    for (unsigned i = 0; i < count; i++)
        if (list[i] == value)
            return 1;
    return 0;
}

static void log_line(FILE *marks, const char *kind, const char *what,
                     const iigs *m)
{
    if (marks)
        fprintf(marks, "%s %s %" PRIu64 " %" PRIu64 " %" PRIu64 "\n", kind,
                what, iigs_clock(m), m->cpu.cycles, m->instructions);
}

/* Do the steps of the input due now; one that ends the run puts the
   reason in `end`. `tracer` may be NULL. */
static void input(program *p, iigs *m, const options *o, FILE *marks,
                  trace *tracer, ending *end)
{
    for (;;) {
        const step *s = NULL;
        switch (program_step(p, m, &s)) {
        case PROGRAM_IDLE: case PROGRAM_END:
            return;
        case PROGRAM_DONE:
            break;
        case PROGRAM_SHOT:
            shot(m, o->shot_dir, s->name);
            break;
        case PROGRAM_NOTE:
            log_line(marks, "note", s->name, m);
            if (tracer)
                trace_note(tracer, s->name);
            break;
        case PROGRAM_STOP:
            end->reason = "stop";
            end->line = s->line;
            return;
        case PROGRAM_TIMEOUT:
            end->reason = "timeout";
            end->line = s->line;
            return;
        case PROGRAM_LATE:
            end->reason = "late";
            end->line = s->line;
            return;
        }
    }
}

int main(int argc, char **argv)
{
    options o;
    static iigs m;
    program p;
    char error[512];
    parse(argc, argv, &o);
    if (!iigs_init(&m))
        fail("out of memory");
    iigs_set_cpu_hz(&m, o.cpu_hz);
    load_image(&m, o.image);
    m.stop_on_fault = o.stop_on_fault;
    for (unsigned i = 0; i < o.stop_pc_count; i++)
        if (!iigs_set_break(&m, (uint32_t)o.stop_pcs[i]))
            fail("out of memory");
    for (unsigned i = 0; i < o.mark_pc_count; i++)
        if (!iigs_set_break(&m, (uint32_t)o.mark_pcs[i]))
            fail("out of memory");

    uint8_t *disk = NULL;
    size_t disk_length = 0;
    if (o.disk) {
        disk = read_file(o.disk, &disk_length);
        if (disk_length % 512)
            fail("%s is not whole 512-byte blocks", o.disk);
        iigs_attach_disk(&m, disk, disk_length);
    }
    program_init(&p);
    if (o.input && !program_read(&p, o.input, error, sizeof error))
        fail("%s", error);
    FILE *marks = NULL;
    if (o.marks && !(marks = fopen(o.marks, "w")))
        fail("cannot write %s", o.marks);
    trace *tracer = NULL;
    if (o.trace.path && !(tracer = trace_open(&m, &o.trace)))
        fail("cannot trace to %s", o.trace.path);

    qsort(o.shot_frames, o.shot_frame_count, sizeof(uint64_t), compare_u64);
    qsort(o.shot_cycles, o.shot_cycle_count, sizeof(uint64_t), compare_u64);
    unsigned next_frame_shot = 0, next_cycle_shot = 0;
    ending end = { NULL, 0, 0 };

    /* The input's steps at frame 0 come before any instruction. */
    input(&p, &m, &o, marks, tracer, &end);
    while (!end.reason) {
        uint64_t frame_stop = minimum(minimum(
            o.frames, upcoming(o.shot_frames, o.shot_frame_count,
                               next_frame_shot)), program_due(&p));
        uint64_t cycle_stop = minimum(
            o.cycles, upcoming(o.shot_cycles, o.shot_cycle_count,
                               next_cycle_shot));
        iigs_stop why = iigs_run(&m, cycle_stop, frame_stop);
        uint32_t pc = (uint32_t)m.cpu.pbr << 16 | m.cpu.pc;

        if (why == IIGS_BREAK && listed(o.mark_pcs, o.mark_pc_count, pc)) {
            char where[8];
            snprintf(where, sizeof where, "%06" PRIX32, pc);
            log_line(marks, "mark", where, &m);
        }
        if (why == IIGS_BREAK && listed(o.stop_pcs, o.stop_pc_count, pc)) {
            end.reason = "stop-pc";
            end.pc = pc;
        } else if (why == IIGS_SPIN) {
            end.reason = "spin";
            end.pc = pc;
        } else if (why == IIGS_ODD_OPCODE) {
            end.reason = "opcode";
            end.pc = m.opcode_pc;
        } else
            input(&p, &m, &o, marks, tracer, &end);
        while (next_frame_shot < o.shot_frame_count &&
               o.shot_frames[next_frame_shot] <= m.frame)
            numbered_shot(&m, o.shot_dir, "frame",
                          o.shot_frames[next_frame_shot++], 6);
        while (next_cycle_shot < o.shot_cycle_count &&
               o.shot_cycles[next_cycle_shot] <= m.cpu.cycles)
            numbered_shot(&m, o.shot_dir, "cycle",
                          o.shot_cycles[next_cycle_shot++], 12);
        if (!end.reason && m.frame >= o.frames)
            end.reason = "frames";
        if (!end.reason && m.cpu.cycles >= o.cycles)
            end.reason = "cycles";
    }

    if (tracer && !trace_close(tracer))
        fail("cannot write %s", o.trace.path);
    log_line(marks, "end", "-", &m);
    if (marks && fclose(marks))
        fail("cannot write %s", o.marks);
    FILE *out = stdout;
    if (o.state && !(out = fopen(o.state, "w")))
        fail("cannot write %s", o.state);
    write_state(&m, &o, &end, out);
    if (out != stdout && fclose(out))
        fail("cannot write %s", o.state);
    if (o.dump) {
        FILE *file = fopen(o.dump, "wb");
        if (!file ||
            fwrite(m.ram, IIGS_BANK, IIGS_RAM_BANKS, file) != IIGS_RAM_BANKS ||
            fwrite(m.mega, IIGS_BANK, 2, file) != 2 || fclose(file))
            fail("cannot write %s", o.dump);
    }
    if (o.disk_out) {
        if (!disk)
            fail("--disk-out needs --disk");
        write_file(o.disk_out, disk, disk_length);
    }
    free(disk);
    program_free(&p);
    iigs_free(&m);
    return 0;
}
