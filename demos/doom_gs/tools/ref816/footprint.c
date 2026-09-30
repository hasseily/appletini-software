/*
 * The footprint of a call: see footprint.h.
 */
#include "footprint.h"

#include <errno.h>
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

enum {
    OP_BRK = 0x00, OP_COP = 0x02, OP_JSR = 0x20, OP_JSL = 0x22,
    OP_JSR_INDEXED = 0xfc, OP_RTI = 0x40, OP_RTS = 0x60, OP_RTL = 0x6b,
    SPACE = 1 << 24,                    /* 24-bit addresses */
    HEADER = 32,
    CHUNK = 0x1000                      /* entry.img: runs of 4 KB */
};

static const char MAGIC[] = "REF816I1";

/* What an address of the bus is, as the machine maps it now. */
typedef enum { K_RAM, K_IO, K_ROM, K_NONE } kind;

/* Registers and soft switches, as an image header holds them. */
typedef struct {
    uint16_t pc, a, x, y, s, d;
    uint8_t pbr, dbr, p, e;
    uint8_t newvideo, border, shadow, speed;
} registers;

struct footprint {
    iigs *m;
    footprint_config config;
    cpu816_read_fn read;                /* the machine's own callbacks */
    cpu816_write_fn write;
    void *bus_context;

    /* The last step. */
    uint64_t instructions, cycles, firmware_cycles;

    /* The call being recorded. */
    int recording, returned, entering;
    unsigned depth, irq_open;
    uint64_t depth_lost;                /* frames beyond FOOTPRINT_DEPTH */
    uint8_t irq_frame[FOOTPRINT_DEPTH]; /* 1: the frame is an interrupt */
    uint64_t own_instructions, own_cycles;
    uint64_t interrupts, irq_instructions, irq_cycles;
    uint8_t *touched, *written;         /* a bit a 24-bit address */
    uint8_t *own;                       /* the value the call last wrote */
    uint32_t *reads;                    /* address << 8 | value, in order */
    size_t read_count, read_capacity;
    uint64_t io_reads[256], io_writes[256];
    uint64_t rom_reads, rom_writes, none_reads, none_writes;
    registers start, end;

    /* Captures. */
    uint64_t hits;                      /* calls of the entry so far */
    unsigned next_hit;
    char directory[1024];               /* of the capture in progress */
    uint64_t hit, entry_frame, entry_clock, entry_cycles;
    uint64_t entry_instructions;
    char note[64], entry_note[64];
    unsigned captures;

    char error[512];
};

/* ---- helpers ---- */

static void set_error(footprint *f, const char *format, const char *what)
{
    if (!f->error[0])
        snprintf(f->error, sizeof f->error, format, what, strerror(errno));
}

static int bit(const uint8_t *bits, uint32_t a)
{
    return bits[a >> 3] >> (a & 7) & 1;
}

static void set_bit(uint8_t *bits, uint32_t a)
{
    bits[a >> 3] |= (uint8_t)(1u << (a & 7));
}

static kind kind_of(const iigs *m, uint32_t address)
{
    unsigned bank = address >> 16;
    uint16_t offset = (uint16_t)address;
    if (bank < 2 && offset >= 0xc000 && !(m->shadow & IIGS_SHADOW_IOLC))
        return offset < 0xc100 ? K_IO : K_ROM;
    if (bank < IIGS_RAM_BANKS)
        return K_RAM;
    if (bank == 0xe0 || bank == 0xe1) {
        if (offset >= 0xc000 && offset < 0xd000)
            return offset < 0xc100 ? K_IO : K_ROM;
        return K_RAM;
    }
    return K_NONE;
}

static void save_registers(const iigs *m, registers *r)
{
    const cpu816 *c = &m->cpu;
    *r = (registers){ c->pc, c->a, c->x, c->y, c->s, c->d, c->pbr, c->dbr,
                      c->p, c->e, m->newvideo, m->border, m->shadow,
                      m->speed };
}

/* ---- images ---- */

static void put16(uint8_t *p, uint16_t value)
{
    p[0] = (uint8_t)value;
    p[1] = (uint8_t)(value >> 8);
}

static void put32(uint8_t *p, uint32_t value)
{
    for (int i = 0; i < 4; i++)
        p[i] = (uint8_t)(value >> (8 * i));
}

static int write_header(FILE *out, const registers *r)
{
    uint8_t h[HEADER] = { 0 };
    memcpy(h, MAGIC, 8);
    put16(h + 8, r->pc);
    h[10] = r->pbr;
    h[11] = r->dbr;
    put16(h + 12, r->a);
    put16(h + 14, r->x);
    put16(h + 16, r->y);
    put16(h + 18, r->s);
    put16(h + 20, r->d);
    h[22] = r->p;
    h[23] = r->e;
    h[24] = r->newvideo;
    h[25] = r->border;
    h[26] = r->shadow;
    h[27] = r->speed;
    return fwrite(h, 1, HEADER, out) == HEADER;
}

static int write_record(FILE *out, uint32_t address, const uint8_t *data,
                        uint32_t length)
{
    uint8_t h[8];
    put32(h, address);
    put32(h + 4, length);
    return fwrite(h, 1, 8, out) == 8 &&
           fwrite(data, 1, length, out) == length;
}

static int all_zero(const uint8_t *data, size_t length)
{
    for (size_t i = 0; i < length; i++)
        if (data[i])
            return 0;
    return 1;
}

/* All RAM: a record for each run of 4 KB chunks with a byte not zero. */
static int write_all(FILE *out, const iigs *m)
{
    static const struct { uint32_t base; uint32_t banks; } areas[] = {
        { 0, IIGS_RAM_BANKS }, { 0xe00000u, 2 } };
    for (unsigned a = 0; a < 2; a++) {
        const uint8_t *data = a ? m->mega : m->ram;
        uint32_t size = areas[a].banks * IIGS_BANK;
        uint32_t at = 0;
        while (at < size) {
            if (all_zero(data + at, CHUNK)) {
                at += CHUNK;
                continue;
            }
            uint32_t end = at + CHUNK;
            while (end < size && !all_zero(data + end, CHUNK))
                end += CHUNK;
            if (!write_record(out, areas[a].base + at, data + at, end - at))
                return 0;
            at = end;
        }
    }
    return 1;
}

static int by_address(const void *a, const void *b)
{
    uint32_t x = *(const uint32_t *)a >> 8, y = *(const uint32_t *)b >> 8;
    return (x > y) - (x < y);
}

/* The first reads, a record for each run of consecutive addresses. */
static int write_reads(FILE *out, footprint *f)
{
    qsort(f->reads, f->read_count, sizeof *f->reads, by_address);
    uint8_t *run = malloc(SPACE / 256);
    if (!run)
        return 0;
    size_t i = 0;
    int ok = 1;
    while (ok && i < f->read_count) {
        uint32_t start = f->reads[i] >> 8, length = 0;
        while (i < f->read_count && f->reads[i] >> 8 == start + length &&
               length < SPACE / 256) {
            run[length++] = (uint8_t)f->reads[i];
            i++;
        }
        ok = write_record(out, start, run, length);
    }
    free(run);
    return ok;
}

/* The bytes written, with the values the call wrote last (or, `now`,
   their values now). */
static int write_writes(FILE *out, const footprint *f, int now)
{
    uint32_t at = 0;
    while (at < SPACE) {
        if (!f->written[at >> 3]) {
            at = (at | 7) + 1;
            continue;
        }
        if (!bit(f->written, at)) {
            at++;
            continue;
        }
        uint32_t end = at + 1;
        while (end < SPACE && bit(f->written, end) &&
               (end & 0xffff) != 0)          /* a record a bank at most */
            end++;
        const uint8_t *data = f->own + at;
        if (now)
            data = at >> 16 < IIGS_RAM_BANKS ? f->m->ram + at
                                             : f->m->mega + (at - 0xe00000u);
        if (!write_record(out, at, data, end - at))
            return 0;
        at = end;
    }
    return 1;
}

typedef enum { IMAGE_ALL, IMAGE_READS, IMAGE_WRITES, IMAGE_EXIT } image_kind;

static int write_image(footprint *f, const char *path, image_kind what)
{
    FILE *out = fopen(path, "wb");
    if (!out) {
        set_error(f, "cannot write %s: %s", path);
        return 0;
    }
    int ok = write_header(out, what >= IMAGE_WRITES ? &f->end : &f->start);
    if (ok && what == IMAGE_ALL)
        ok = write_all(out, f->m);
    else if (ok && what == IMAGE_READS)
        ok = write_reads(out, f);
    else if (ok)
        ok = write_writes(out, f, what == IMAGE_EXIT);
    if (fclose(out) || !ok) {
        set_error(f, "cannot write %s: %s", path);
        return 0;
    }
    return 1;
}

/* ---- the bus while recording ---- */

/* A stack or vector access in a step that fetched no opcode is the
   entry of an IRQ or NMI. */
static void check_interrupt(footprint *f, uint8_t space)
{
    if ((space == CPU816_STACK || space == CPU816_VECTOR) && !f->entering &&
        f->m->instructions == f->instructions)
        f->entering = 1;
}

static void first_read(footprint *f, uint32_t address, uint8_t value)
{
    if (bit(f->touched, address))
        return;
    set_bit(f->touched, address);
    if (f->read_count == f->read_capacity) {
        size_t capacity = f->read_capacity ? 2 * f->read_capacity : 65536;
        uint32_t *grown = realloc(f->reads, capacity * sizeof *grown);
        if (!grown) {
            errno = ENOMEM;
            set_error(f, "%s: %s", "the reads of a call");
            return;
        }
        f->reads = grown;
        f->read_capacity = capacity;
    }
    f->reads[f->read_count++] = address << 8 | value;
}

static uint8_t recorded_read(void *context, uint32_t address)
{
    footprint *f = context;
    iigs *m = f->m;
    address &= 0xffffff;
    check_interrupt(f, m->cpu.space);
    kind k = kind_of(m, address);
    uint8_t value = f->read(f->bus_context, address);
    if (f->entering || f->irq_open)
        return value;
    switch (k) {
    case K_RAM: first_read(f, address, value); break;
    case K_IO: f->io_reads[address & 0xff]++; break;
    case K_ROM: f->rom_reads++; break;
    case K_NONE: f->none_reads++; break;
    }
    return value;
}

static void mark_written(footprint *f, uint32_t address, uint8_t value)
{
    set_bit(f->written, address);
    set_bit(f->touched, address);
    f->own[address] = value;
}

static void recorded_write(void *context, uint32_t address, uint8_t value)
{
    footprint *f = context;
    iigs *m = f->m;
    address &= 0xffffff;
    check_interrupt(f, m->cpu.space);
    kind k = kind_of(m, address);
    uint32_t copy = k == K_RAM ? iigs_shadow_target(m, address)
                               : IIGS_NO_SHADOW;
    f->write(f->bus_context, address, value);
    if (f->entering || f->irq_open)
        return;
    switch (k) {
    case K_RAM:
        mark_written(f, address, value);
        if (copy != IIGS_NO_SHADOW)
            mark_written(f, copy, value);
        break;
    case K_IO: f->io_writes[address & 0xff]++; break;
    case K_ROM: f->rom_writes++; break;
    case K_NONE: f->none_writes++; break;
    }
}

/* ---- calls ---- */

static void begin(footprint *f)
{
    iigs *m = f->m;
    memset(f->touched, 0, SPACE / 8);
    memset(f->written, 0, SPACE / 8);
    f->read_count = 0;
    f->recording = 1;
    f->returned = f->entering = 0;
    f->depth = f->irq_open = 0;
    f->depth_lost = 0;
    f->own_instructions = f->own_cycles = 0;
    f->interrupts = f->irq_instructions = f->irq_cycles = 0;
    memset(f->io_reads, 0, sizeof f->io_reads);
    memset(f->io_writes, 0, sizeof f->io_writes);
    f->rom_reads = f->rom_writes = f->none_reads = f->none_writes = 0;
    save_registers(m, &f->start);
    f->read = m->cpu.read;
    f->write = m->cpu.write;
    f->bus_context = m->cpu.context;
    m->cpu.read = recorded_read;
    m->cpu.write = recorded_write;
    m->cpu.context = f;
}

static void stop_recording(footprint *f)
{
    iigs *m = f->m;
    m->cpu.read = f->read;
    m->cpu.write = f->write;
    m->cpu.context = f->bus_context;
    f->recording = 0;
}

static void push(footprint *f, int interrupt)
{
    if (f->depth < FOOTPRINT_DEPTH)
        f->irq_frame[f->depth] = (uint8_t)interrupt;
    else
        f->depth_lost++;
    f->depth++;
    if (interrupt)
        f->irq_open++;
}

static void pop(footprint *f)
{
    f->depth--;
    if (f->depth < FOOTPRINT_DEPTH && f->irq_frame[f->depth])
        f->irq_open--;
}

static void json_string(FILE *out, const char *text)
{
    fputc('"', out);
    for (; *text; text++)
        if (*text == '"' || *text == '\\' || (unsigned char)*text < 0x20)
            fprintf(out, "\\u%04x", (unsigned char)*text);
        else
            fputc(*text, out);
    fputc('"', out);
}

static void io_json(FILE *out, const char *name, const uint64_t *counts)
{
    const char *separator = "";
    fprintf(out, "\"%s\": {", name);
    for (unsigned i = 0; i < 256; i++)
        if (counts[i]) {
            fprintf(out, "%s\"C0%02X\": %" PRIu64, separator, i, counts[i]);
            separator = ", ";
        }
    fputc('}', out);
}

/* The bytes written, and of those the ones whose value now is not the
   one the call wrote (an interrupt inside it wrote them after). */
static uint64_t count_written(const footprint *f, uint64_t *changed)
{
    uint64_t n = 0;
    *changed = 0;
    for (uint32_t i = 0; i < SPACE / 8; i++)
        for (unsigned j = 0; f->written[i] >> j; j++)
            if (f->written[i] >> j & 1) {
                uint32_t address = i << 3 | j;
                n++;
                *changed += iigs_peek(f->m, address) != f->own[address];
            }
    return n;
}

static void registers_json(FILE *out, const registers *r)
{
    fprintf(out, "{\"pc\": %" PRIu32 ", \"a\": %u, \"x\": %u, \"y\": %u, "
            "\"s\": %u, \"d\": %u, \"dbr\": %u, \"p\": %u, \"e\": %u, "
            "\"shadow\": %u}", (uint32_t)r->pbr << 16 | r->pc, r->a, r->x,
            r->y, r->s, r->d, r->dbr, r->p, r->e, r->shadow);
}

static void call_json(const footprint *f, FILE *out, const char *indent)
{
    fprintf(out, "{\n%s  \"returned\": %s,\n", indent,
            f->returned ? "true" : "false");
    fprintf(out, "%s  \"start\": ", indent);
    registers_json(out, &f->start);
    fprintf(out, ",\n%s  \"end\": ", indent);
    registers_json(out, &f->end);
    fprintf(out, ",\n%s  \"depth\": %u, \"depth_lost\": %" PRIu64 ",\n",
            indent, f->depth, f->depth_lost);
    fprintf(out, "%s  \"instructions\": %" PRIu64 ", \"cycles\": %" PRIu64
            ",\n", indent, f->own_instructions, f->own_cycles);
    fprintf(out, "%s  \"interrupts\": {\"count\": %" PRIu64
            ", \"instructions\": %" PRIu64 ", \"cycles\": %" PRIu64 "},\n",
            indent, f->interrupts, f->irq_instructions, f->irq_cycles);
    uint64_t changed, written = count_written(f, &changed);
    fprintf(out, "%s  \"bytes_read\": %zu, \"bytes_written\": %" PRIu64
            ", \"written_then_changed\": %" PRIu64 ",\n", indent,
            f->read_count, written, changed);
    fprintf(out, "%s  \"io\": {", indent);
    io_json(out, "reads", f->io_reads);
    fputs(", ", out);
    io_json(out, "writes", f->io_writes);
    fprintf(out, "},\n%s  \"rom_reads\": %" PRIu64 ", \"rom_writes\": %"
            PRIu64 ", \"unmapped_reads\": %" PRIu64 ", \"unmapped_writes\": %"
            PRIu64 "\n%s}", indent, f->rom_reads, f->rom_writes,
            f->none_reads, f->none_writes, indent);
}

/* ---- captures ---- */

static int wanted(footprint *f)
{
    while (f->next_hit < f->config.hit_count &&
           f->config.hits[f->next_hit] < f->hits)
        f->next_hit++;
    return f->next_hit < f->config.hit_count &&
           f->config.hits[f->next_hit] == f->hits;
}

static void begin_capture(footprint *f)
{
    iigs *m = f->m;
    char path[1100];
    snprintf(f->directory, sizeof f->directory, "%s/hit-%08" PRIu64,
             f->config.capture_dir, f->hits);
    if (mkdir(f->directory, 0777) && errno != EEXIST) {
        set_error(f, "cannot make %s: %s", f->directory);
        return;
    }
    f->hit = f->hits;
    f->entry_frame = m->frame;
    f->entry_clock = iigs_clock(m);
    f->entry_cycles = m->cpu.cycles;
    f->entry_instructions = m->instructions;
    memcpy(f->entry_note, f->note, sizeof f->note);
    begin(f);
    snprintf(path, sizeof path, "%s/entry.img", f->directory);
    write_image(f, path, IMAGE_ALL);
}

static void end_capture(footprint *f)
{
    char path[1100];
    snprintf(path, sizeof path, "%s/reads.img", f->directory);
    write_image(f, path, IMAGE_READS);
    snprintf(path, sizeof path, "%s/writes.img", f->directory);
    write_image(f, path, IMAGE_WRITES);
    snprintf(path, sizeof path, "%s/exit.img", f->directory);
    write_image(f, path, IMAGE_EXIT);
    snprintf(path, sizeof path, "%s/call.json", f->directory);
    FILE *out = fopen(path, "w");
    if (!out) {
        set_error(f, "cannot write %s: %s", path);
        return;
    }
    fprintf(out, "{\n  \"hit\": %" PRIu64 ",\n  \"entry\": %" PRIu32
            ",\n  \"note\": ", f->hit, f->config.entry);
    json_string(out, f->entry_note);
    fprintf(out, ",\n  \"frame\": %" PRIu64 ",\n  \"clock\": %" PRIu64
            ",\n  \"cycles\": %" PRIu64 ",\n  \"instructions\": %" PRIu64
            ",\n  \"call\": ", f->entry_frame, f->entry_clock,
            f->entry_cycles, f->entry_instructions);
    call_json(f, out, "  ");
    fputs("\n}\n", out);
    if (fclose(out))
        set_error(f, "cannot write %s: %s", path);
    f->captures++;
}

/* ---- the step hook ---- */

static int is_call(uint8_t opcode)
{
    return opcode == OP_JSR || opcode == OP_JSL || opcode == OP_JSR_INDEXED;
}

static void returned(footprint *f)
{
    save_registers(f->m, &f->end);
    f->returned = 1;
    stop_recording(f);
    if (f->config.call)
        f->m->stop_request = 1;
    else
        end_capture(f);
}

static void after_step(void *context)
{
    footprint *f = context;
    iigs *m = f->m;
    uint64_t instructions = m->instructions - f->instructions;
    uint64_t cycles = m->cpu.cycles - f->cycles;
    int firmware = m->counts.firmware_cycles != f->firmware_cycles;
    f->instructions = m->instructions;
    f->cycles = m->cpu.cycles;
    f->firmware_cycles = m->counts.firmware_cycles;

    if (!f->recording) {
        uint32_t pc = (uint32_t)m->cpu.pbr << 16 | m->cpu.pc;
        if (f->config.capture_dir && instructions == 1 &&
            is_call(m->opcode) && pc == f->config.entry) {
            f->hits++;
            if (wanted(f))
                begin_capture(f);
        }
        return;
    }
    if (f->entering || f->irq_open) {
        f->irq_instructions += instructions;
        f->irq_cycles += cycles;
    } else {
        f->own_instructions += instructions;
        f->own_cycles += cycles;
    }
    if (f->entering) {
        f->entering = 0;
        f->interrupts++;
        push(f, 1);
        return;
    }
    if (firmware) {
        /* The trap returned for the JSR that reached it. */
        if (!f->depth)
            returned(f);
        else
            pop(f);
        return;
    }
    if (instructions != 1)
        return;
    switch (m->opcode) {
    case OP_JSR: case OP_JSL: case OP_JSR_INDEXED: case OP_BRK: case OP_COP:
        push(f, 0);
        break;
    case OP_RTS: case OP_RTL: case OP_RTI:
        if (!f->depth)
            returned(f);
        else
            pop(f);
        break;
    default:
        break;
    }
}

/* ---- the interface ---- */

footprint *footprint_open(iigs *m, const footprint_config *c)
{
    footprint *f = calloc(1, sizeof *f);
    if (!f)
        return NULL;
    f->m = m;
    f->config = *c;
    f->touched = calloc(SPACE / 8, 1);
    f->written = calloc(SPACE / 8, 1);
    f->own = calloc(SPACE, 1);
    if (!f->touched || !f->written || !f->own) {
        free(f->touched);
        free(f->written);
        free(f->own);
        free(f);
        return NULL;
    }
    f->config.entry &= 0xffffff;
    f->instructions = m->instructions;
    f->cycles = m->cpu.cycles;
    f->firmware_cycles = m->counts.firmware_cycles;
    m->after_step = after_step;
    m->step_context = f;
    if (c->call)
        begin(f);
    return f;
}

void footprint_note(footprint *f, const char *name)
{
    snprintf(f->note, sizeof f->note, "%s", name);
}

int footprint_returned(const footprint *f)
{
    return f->returned;
}

void footprint_json(footprint *f, FILE *out)
{
    if (f->recording)
        save_registers(f->m, &f->end);
    fputs("  \"call\": ", out);
    call_json(f, out, "  ");
}

const char *footprint_close(footprint *f)
{
    static char message[512];
    if (f->recording) {
        if (!f->config.call)
            snprintf(f->error, sizeof f->error, "the capture of call %"
                     PRIu64 " did not return before the run ended", f->hit);
        save_registers(f->m, &f->end);
        stop_recording(f);
    }
    if (f->config.call && f->config.reads_path)
        write_image(f, f->config.reads_path, IMAGE_READS);
    if (f->config.call && f->config.writes_path)
        write_image(f, f->config.writes_path, IMAGE_WRITES);
    if (f->config.capture_dir && !f->error[0] &&
        f->captures < f->config.hit_count)
        snprintf(f->error, sizeof f->error, "%u of the %u calls to capture "
                 "came (the entry was called %" PRIu64 " times)",
                 f->captures, f->config.hit_count, f->hits);
    f->m->after_step = NULL;
    f->m->step_context = NULL;
    snprintf(message, sizeof message, "%s", f->error);
    free(f->touched);
    free(f->written);
    free(f->own);
    free(f->reads);
    free(f);
    return message[0] ? message : NULL;
}
