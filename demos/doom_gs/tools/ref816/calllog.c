/*
 * The call log: see calllog.h.
 */
#include "calllog.h"

#include <errno.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    OP_JSR = 0x20, OP_JSL = 0x22, OP_JSR_X = 0xfc,
    OP_JMP = 0x4c, OP_JML = 0x5c, OP_JMP_IND = 0x6c, OP_JMP_X = 0x7c,
    OP_JML_IND = 0xdc,
    OP_RTS = 0x60, OP_RTL = 0x6b, OP_RTI = 0x40,
    TEXT = 1024,
    MAX_RANGE = 0x10000,
    BUFFER = 1 << 20
};

typedef struct {
    uint32_t pc;
    uint16_t a, x, y, s, d;
    uint8_t dbr, p, e;
} registers;

typedef struct {
    uint64_t call, hit, parent;
    unsigned routine, depth, irq;
    uint32_t from;
    const char *via;
    uint16_t s;                         /* S at the entry */
    uint64_t frame, cycles, instructions, interrupts;
    registers in;
    uint32_t out_address[CALLLOG_RANGES];
    uint8_t *in_bytes;                  /* the in ranges, one after the other */
} open_call;

struct calllog {
    iigs *m;
    calllog_routine routines[CALLLOG_ROUTINES];
    unsigned count;
    FILE *out;
    char *buffer;
    const char *path;

    uint64_t instructions, firmware_cycles, interrupts;
    uint64_t calls;
    open_call *open;
    size_t open_count, open_capacity;
    uint16_t *irq;                      /* S after each open interrupt entry */
    size_t irq_count, irq_capacity;
    uint64_t limit;                     /* calllog_set_limit */
    int full;                           /* the log passed its limit */
    char error[512];
};

/* ---- parsing ---- */

static int problem(char *error, size_t size, const char *format, ...)
{
    va_list arguments;
    va_start(arguments, format);
    vsnprintf(error, size, format, arguments);
    va_end(arguments);
    return 0;
}

static char *next_part(char **cursor, char separator)
{
    char *part = *cursor;
    if (!part)
        return NULL;
    char *end = strchr(part, separator);
    if (end) {
        *end = 0;
        *cursor = end + 1;
    } else
        *cursor = NULL;
    return part;
}

static int number(const char *text, int base, uint64_t maximum,
                  uint64_t *value)
{
    char *end;
    if (!text[0] || text[0] == '-' || text[0] == '+')
        return 0;
    errno = 0;
    unsigned long long parsed = strtoull(text, &end, base);
    if (errno || end == text || *end || parsed > maximum)
        return 0;
    *value = parsed;
    return 1;
}

static int in_ram(uint64_t address)
{
    unsigned bank = (unsigned)(address >> 16);
    return bank < IIGS_RAM_BANKS || bank == 0xe0 || bank == 0xe1;
}

/* R: ADDR:LEN, d+OFF:LEN or s+OFF:LEN. */
static int parse_range(calllog_range *r, const char *text, char *error,
                       size_t size)
{
    char buffer[TEXT];
    if (strlen(text) >= sizeof buffer)
        return problem(error, size, "a range is too long");
    strcpy(buffer, text);
    char *colon = strrchr(buffer, ':');
    uint64_t offset, length;
    if (!colon || !number(colon + 1, 0, MAX_RANGE, &length) || !length)
        return problem(error, size, "%s is not ADDR:LEN, d+OFF:LEN or "
                       "s+OFF:LEN (LEN 1 to 65536)", text);
    *colon = 0;
    if ((buffer[0] == 'd' || buffer[0] == 's') && buffer[1] == '+') {
        if (!number(buffer + 2, 16, 0xffff, &offset))
            return problem(error, size, "%s: OFF is 0 to FFFF (hex)", text);
        r->base = buffer[0] == 'd' ? CALLLOG_D : CALLLOG_S;
    } else {
        if (!number(buffer, 16, 0xffffff, &offset))
            return problem(error, size, "%s: not a 24-bit hex address",
                           text);
        if (!in_ram(offset) || !in_ram(offset + length - 1) ||
            (offset >> 16) != ((offset + length - 1) >> 16))
            return problem(error, size, "%s is not in RAM within one bank",
                           text);
        r->base = CALLLOG_ABS;
    }
    r->offset = (uint32_t)offset;
    r->length = (uint32_t)length;
    return 1;
}

static int parse_ranges(calllog_range *list, unsigned *count,
                        const char *text, char *error, size_t size)
{
    char buffer[TEXT];
    if (strlen(text) >= sizeof buffer)
        return problem(error, size, "the ranges are too long");
    strcpy(buffer, text);
    char *cursor = buffer, *part;
    while ((part = next_part(&cursor, '+'))) {
        /* d+OFF and s+OFF have a + of their own. */
        char joined[TEXT];
        if ((!strcmp(part, "d") || !strcmp(part, "s")) && cursor) {
            char *rest = next_part(&cursor, '+');
            snprintf(joined, sizeof joined, "%s+%s", part, rest);
            part = joined;
        }
        if (*count == CALLLOG_RANGES)
            return problem(error, size, "at most %d ranges", CALLLOG_RANGES);
        if (!parse_range(&list[*count], part, error, size))
            return 0;
        ++*count;
    }
    return 1;
}

static int flag(const char *value, int *out)
{
    if (strcmp(value, "0") && strcmp(value, "1"))
        return 0;
    *out = value[0] == '1';
    return 1;
}

int calllog_parse(calllog_routine *r, const char *text, char *error,
                  size_t size)
{
    char buffer[TEXT];
    memset(r, 0, sizeof *r);
    if (!point_parse(&r->select, "", POINT_FOR_CALL, error, size))
        return 0;
    if (strlen(text) >= sizeof buffer)
        return problem(error, size, "--call-log: too long");
    strcpy(buffer, text);
    char *cursor = buffer;
    char *entry = next_part(&cursor, ',');
    uint64_t address;
    if (!number(entry, 16, 0xffffff, &address))
        return problem(error, size, "--call-log %s: it starts with the "
                       "entry, a 24-bit hex address", text);
    r->entry = (uint32_t)address;
    snprintf(r->name, sizeof r->name, "%06" PRIX32, r->entry);
    char *item;
    while ((item = next_part(&cursor, ','))) {
        char *equals = strchr(item, '=');
        if (!equals)
            return problem(error, size, "--call-log %s: %s is not "
                           "KEY=VALUE", text, item);
        *equals = 0;
        const char *key = item, *value = equals + 1;
        if (!strcmp(key, "name")) {
            int printable = 1;
            for (const char *c = value; *c; c++)
                printable &= *c >= 0x20 && *c < 0x7f && *c != '"' &&
                             *c != '\\';
            if (!value[0] || strlen(value) >= CALLLOG_NAME || !printable)
                return problem(error, size, "--call-log: a name of 1 to %d "
                               "printable characters, without quotes or "
                               "backslashes", CALLLOG_NAME - 1);
            strcpy(r->name, value);
        } else if (!strcmp(key, "in") || !strcmp(key, "mem")) {
            if (!parse_ranges(r->in, &r->in_count, value, error, size))
                return 0;
            if (key[0] == 'm' &&
                !parse_ranges(r->out, &r->out_count, value, error, size))
                return 0;
        } else if (!strcmp(key, "out")) {
            if (!parse_ranges(r->out, &r->out_count, value, error, size))
                return 0;
        } else if (!strcmp(key, "jumps")) {
            if (!flag(value, &r->jumps))
                return problem(error, size, "jumps takes 0 or 1");
        } else if (!strcmp(key, "entry")) {
            if (!flag(value, &r->entry_only))
                return problem(error, size, "entry takes 0 or 1");
        } else {
            int known;
            if (!point_item(&r->select, key, value, POINT_FOR_CALL, &known,
                            error, size))
                return 0;
            if (!known)
                return problem(error, size, "--call-log %s: unknown key %s",
                               text, key);
        }
    }
    if (r->entry_only && strstr(text, "out="))
        return problem(error, size, "--call-log %s: entry=1 has no out",
                       text);
    if (r->entry_only)
        r->out_count = 0;
    return 1;
}

/* ---- the log ---- */

static void save_registers(const iigs *m, registers *r)
{
    const cpu816 *c = &m->cpu;
    *r = (registers){ (uint32_t)c->pbr << 16 | c->pc, c->a, c->x, c->y,
                      c->s, c->d, c->dbr, c->p, c->e };
}

static uint32_t range_address(const calllog_range *r, const registers *at)
{
    switch (r->base) {
    case CALLLOG_D: return (uint16_t)(at->d + r->offset);
    case CALLLOG_S: return (uint16_t)(at->s + r->offset);
    default: return r->offset;
    }
}

/* The byte `i` of a range at `address`: d and s ranges wrap in bank 0. */
static uint8_t range_byte(const iigs *m, const calllog_range *r,
                          uint32_t address, uint32_t i)
{
    uint32_t a = r->base == CALLLOG_ABS ? address + i
                                        : (uint16_t)(address + i);
    return iigs_peek(m, a & 0xffffff);
}

static void registers_json(FILE *out, const registers *r)
{
    fprintf(out, "\"pc\": %" PRIu32 ", \"a\": %u, \"x\": %u, \"y\": %u, "
            "\"s\": %u, \"d\": %u, \"dbr\": %u, \"p\": %u, \"e\": %u",
            r->pc, r->a, r->x, r->y, r->s, r->d, r->dbr, r->p, r->e);
}

static void hex(FILE *out, const uint8_t *data, uint32_t length)
{
    static const char digits[] = "0123456789abcdef";
    for (uint32_t i = 0; i < length; i++) {
        fputc(digits[data[i] >> 4], out);
        fputc(digits[data[i] & 15], out);
    }
}

/* The start of a call's line, up to "in" included. */
static void call_head(calllog *l, const open_call *c)
{
    const calllog_routine *r = &l->routines[c->routine];
    FILE *out = l->out;
    fprintf(out, "{\"call\": %" PRIu64 ", \"routine\": %u, \"hit\": %" PRIu64
            ", \"from\": %" PRIu32 ", \"via\": \"%s\", \"parent\": %" PRIu64
            ", \"depth\": %u, \"irq\": %u, \"frame\": %" PRIu64
            ", \"cycles\": %" PRIu64 ", \"instructions\": %" PRIu64
            ", \"in\": {", c->call, c->routine, c->hit, c->from, c->via,
            c->parent, c->depth, c->irq, c->frame, c->cycles,
            c->instructions);
    registers_json(out, &c->in);
    fputs(", \"mem\": [", out);
    const uint8_t *bytes = c->in_bytes;
    for (unsigned i = 0; i < r->in_count; i++) {
        fputs(i ? ", \"" : "\"", out);
        hex(out, bytes, r->in[i].length);
        fputc('"', out);
        bytes += r->in[i].length;
    }
    fputs("]}", out);
}

/* The call's line at its return (`exit` NULL: the run ended). */
static void call_line(calllog *l, const open_call *c, const char *exit)
{
    const calllog_routine *r = &l->routines[c->routine];
    iigs *m = l->m;
    FILE *out = l->out;
    registers now;
    save_registers(m, &now);
    call_head(l, c);
    fputs(", \"out\": {\"exit\": ", out);
    if (exit)
        fprintf(out, "\"%s\", ", exit);
    else
        fputs("null, ", out);
    registers_json(out, &now);
    fprintf(out, ", \"cycles\": %" PRIu64 ", \"instructions\": %" PRIu64
            ", \"interrupts\": %" PRIu64 ", \"mem\": [", m->cpu.cycles,
            m->instructions, m->counts.interrupts - c->interrupts);
    for (unsigned i = 0; i < r->out_count; i++) {
        fputs(i ? ", \"" : "\"", out);
        for (uint32_t j = 0; j < r->out[i].length; j++) {
            uint8_t byte = range_byte(m, &r->out[i], c->out_address[i], j);
            hex(out, &byte, 1);
        }
        fputc('"', out);
    }
    fprintf(out, "]}, \"returned\": %s}\n", exit ? "true" : "false");
}

static void set_error(calllog *l, const char *what)
{
    if (!l->error[0])
        snprintf(l->error, sizeof l->error, "%s: %s", what,
                 strerror(errno ? errno : ENOMEM));
}

/* A line was written: past the limit, the log takes no more lines and
   the run is asked to stop (calllog_problem). */
static void line_done(calllog *l)
{
    if (!l->limit)
        return;
    long at = ftell(l->out);
    if (at >= 0 && (uint64_t)at > l->limit) {
        l->full = 1;
        snprintf(l->error, sizeof l->error, "the call log %s passed "
                 "--call-log-limit, %" PRIu64 " bytes, at call %" PRIu64,
                 l->path, l->limit, l->calls);
        l->m->stop_request = 1;
    }
}

static const char *via_of(uint8_t opcode)
{
    switch (opcode) {
    case OP_JSR: return "jsr";
    case OP_JSL: return "jsl";
    case OP_JSR_X: return "jsr_x";
    case OP_JMP: return "jmp";
    case OP_JML: return "jml";
    case OP_JMP_IND: return "jmp_ind";
    case OP_JMP_X: return "jmp_x";
    case OP_JML_IND: return "jml_ind";
    default: return NULL;
    }
}

/* The CPU arrived at routine `index` by `opcode`. */
static void arrive(calllog *l, unsigned index, uint8_t opcode)
{
    iigs *m = l->m;
    calllog_routine *r = &l->routines[index];
    if (!point_passes(&r->select, m))
        return;
    r->select.hits++;
    if (!point_set_has(&r->select.set, r->select.hits))
        return;
    open_call c;
    memset(&c, 0, sizeof c);
    c.call = ++l->calls;
    c.hit = r->select.hits;
    c.parent = l->open_count ? l->open[l->open_count - 1].call : 0;
    c.routine = index;
    c.depth = (unsigned)l->open_count;
    c.irq = (unsigned)l->irq_count;
    c.from = m->opcode_pc;
    c.via = via_of(opcode);
    c.s = m->cpu.s;
    c.frame = m->frame;
    c.cycles = m->cpu.cycles;
    c.instructions = m->instructions;
    c.interrupts = m->counts.interrupts;
    save_registers(m, &c.in);
    size_t total = 0;
    for (unsigned i = 0; i < r->in_count; i++)
        total += r->in[i].length;
    c.in_bytes = malloc(total ? total : 1);
    if (!c.in_bytes) {
        set_error(l, "the call log");
        return;
    }
    uint8_t *at = c.in_bytes;
    for (unsigned i = 0; i < r->in_count; i++) {
        uint32_t address = range_address(&r->in[i], &c.in);
        for (uint32_t j = 0; j < r->in[i].length; j++)
            *at++ = range_byte(m, &r->in[i], address, j);
    }
    for (unsigned i = 0; i < r->out_count; i++)
        c.out_address[i] = range_address(&r->out[i], &c.in);
    if (r->entry_only) {
        if (!l->full) {
            call_head(l, &c);
            fputs(", \"out\": null}\n", l->out);
            line_done(l);
        }
        free(c.in_bytes);
        return;
    }
    if (l->open_count == l->open_capacity) {
        size_t capacity = l->open_capacity ? 2 * l->open_capacity : 64;
        open_call *grown = realloc(l->open, capacity * sizeof *grown);
        if (!grown) {
            free(c.in_bytes);
            set_error(l, "the call log");
            return;
        }
        l->open = grown;
        l->open_capacity = capacity;
    }
    l->open[l->open_count++] = c;
}

/* A return: every open call and interrupt with S at its entry below S
   now has returned. */
static void returned(calllog *l, const char *exit)
{
    uint16_t s = l->m->cpu.s;
    while (l->open_count && s > l->open[l->open_count - 1].s) {
        open_call *c = &l->open[--l->open_count];
        if (!l->full) {
            call_line(l, c, exit);
            line_done(l);
        }
        free(c->in_bytes);
    }
    while (l->irq_count && s > l->irq[l->irq_count - 1])
        l->irq_count--;
}

static void after_step(void *context)
{
    calllog *l = context;
    iigs *m = l->m;
    uint64_t instructions = m->instructions - l->instructions;
    int firmware = m->counts.firmware_cycles != l->firmware_cycles;
    int interrupt = m->counts.interrupts != l->interrupts;
    l->instructions = m->instructions;
    l->firmware_cycles = m->counts.firmware_cycles;
    l->interrupts = m->counts.interrupts;

    if (interrupt && !instructions) {
        if (l->irq_count == l->irq_capacity) {
            size_t capacity = l->irq_capacity ? 2 * l->irq_capacity : 16;
            uint16_t *grown = realloc(l->irq, capacity * sizeof *grown);
            if (!grown) {
                set_error(l, "the call log");
                return;
            }
            l->irq = grown;
            l->irq_capacity = capacity;
        }
        l->irq[l->irq_count++] = m->cpu.s;
        return;
    }
    if (firmware) {
        returned(l, "firmware");
        return;
    }
    if (instructions != 1)
        return;
    switch (m->opcode) {
    case OP_RTS: returned(l, "rts"); return;
    case OP_RTL: returned(l, "rtl"); return;
    case OP_RTI: returned(l, "rti"); return;
    case OP_JSR: case OP_JSL: case OP_JSR_X:
    case OP_JMP: case OP_JML: case OP_JMP_IND: case OP_JMP_X: case OP_JML_IND:
        break;
    default:
        return;
    }
    int call = m->opcode == OP_JSR || m->opcode == OP_JSL ||
               m->opcode == OP_JSR_X;
    uint32_t pc = (uint32_t)m->cpu.pbr << 16 | m->cpu.pc;
    for (unsigned i = 0; i < l->count; i++)
        if (l->routines[i].entry == pc && (call || l->routines[i].jumps))
            arrive(l, i, m->opcode);
}

/* ---- the interface ---- */

static void ranges_json(FILE *out, const calllog_range *list, unsigned count)
{
    static const char *bases[] = { "abs", "d", "s" };
    fputc('[', out);
    for (unsigned i = 0; i < count; i++)
        fprintf(out, "%s{\"base\": \"%s\", \"offset\": %" PRIu32
                ", \"length\": %" PRIu32 "}", i ? ", " : "",
                bases[list[i].base], list[i].offset, list[i].length);
    fputc(']', out);
}

calllog *calllog_open(iigs *m, const calllog_routine *routines,
                      unsigned count, const char *path, char *error,
                      size_t size)
{
    calllog *l = calloc(1, sizeof *l);
    if (!l) {
        problem(error, size, "out of memory");
        return NULL;
    }
    l->m = m;
    l->count = count;
    l->path = path;
    memcpy(l->routines, routines, count * sizeof *routines);
    l->out = fopen(path, "w");
    l->buffer = malloc(BUFFER);
    if (!l->out || !l->buffer) {
        problem(error, size, "cannot write %s: %s", path, strerror(errno));
        if (l->out)
            fclose(l->out);
        free(l->buffer);
        free(l);
        return NULL;
    }
    setvbuf(l->out, l->buffer, _IOFBF, BUFFER);
    fputs("{\"format\": \"ref816-call-log 1\", \"routines\": [", l->out);
    for (unsigned i = 0; i < count; i++) {
        const calllog_routine *r = &routines[i];
        fprintf(l->out, "%s{\"index\": %u, \"name\": \"%s\", \"entry\": %"
                PRIu32 ", \"jumps\": %s, \"entry_only\": %s, \"in\": ",
                i ? ", " : "", i, r->name, r->entry,
                r->jumps ? "true" : "false",
                r->entry_only ? "true" : "false");
        ranges_json(l->out, r->in, r->in_count);
        fputs(", \"out\": ", l->out);
        ranges_json(l->out, r->out, r->out_count);
        fputc('}', l->out);
    }
    fputs("]}\n", l->out);
    l->instructions = m->instructions;
    l->firmware_cycles = m->counts.firmware_cycles;
    l->interrupts = m->counts.interrupts;
    m->after_step = after_step;
    m->step_context = l;
    return l;
}

void calllog_set_limit(calllog *l, uint64_t bytes)
{
    l->limit = bytes;
}

const char *calllog_problem(const calllog *l)
{
    return l->full ? l->error : NULL;
}

void calllog_note(calllog *l, const char *name)
{
    for (unsigned i = 0; i < l->count; i++)
        point_note(&l->routines[i].select, name);
}

const char *calllog_close(calllog *l)
{
    static char message[600];
    while (l->open_count) {
        open_call *c = &l->open[--l->open_count];
        if (!l->full)
            call_line(l, c, NULL);
        free(c->in_bytes);
    }
    fprintf(l->out, "{\"end\": true, \"calls\": %" PRIu64 ", \"arrivals\": [",
            l->calls);
    for (unsigned i = 0; i < l->count; i++)
        fprintf(l->out, "%s%" PRIu64, i ? ", " : "",
                l->routines[i].select.hits);
    fputs("]}\n", l->out);
    if (ferror(l->out) | fclose(l->out))
        snprintf(l->error, sizeof l->error, "cannot write %s", l->path);
    l->m->after_step = NULL;
    l->m->step_context = NULL;
    snprintf(message, sizeof message, "%s", l->error);
    free(l->buffer);
    free(l->open);
    free(l->irq);
    free(l);
    return message[0] ? message : NULL;
}
