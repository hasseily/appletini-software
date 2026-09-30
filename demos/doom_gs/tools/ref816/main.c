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
 *   --load ADDR:FILE   put the bytes of FILE in RAM at ADDR (hex) after
 *                      the image, with no I/O or shadowing (repeatable,
 *                      in order)
 *   --load-image FILE  put the records of the memory image FILE in RAM
 *                      after the image, in order with the --load files
 *                      (its registers and switches are not used)
 *   --reg NAME=VALUE   set a register after the image and the loads: a,
 *                      x, y, s, d, pc (16 bits), pbr, dbr, p (8 bits), e
 *                      (0 or 1); VALUE in hex (repeatable)
 *   --save ADDR:LEN:FILE
 *                      write LEN bytes of RAM from ADDR (hex; LEN with
 *                      0x for hex) to FILE at the end (repeatable)
 *
 * Calls (footprint.h):
 *
 *   --call ADDR        run the routine at ADDR (hex, 24 bits: PBR and PC)
 *                      on the state of the image, the loads and --reg,
 *                      until it returns: the RTS, RTL or RTI that leaves
 *                      it at call depth 0. The run ends there (reason
 *                      "return"), or at --frames or --cycles (default
 *                      1000000000 cycles); the state gets a "call" member
 *   --call-reads FILE  write the bytes the call read first, with the
 *                      registers at its start, as a memory image
 *   --call-writes FILE write the bytes the call wrote, with the registers
 *                      at its return, as a memory image
 *   --capture DIR      capture calls of --capture-entry into
 *                      DIR/hit-NNNNNNNN/ (entry.img, reads.img,
 *                      writes.img, exit.img, call.json; DIR must
 *                      exist)
 *   --capture-entry ADDR
 *                      the routine whose calls (JSR, JSL, JSR (a,x)) are
 *                      counted, from 1 (hex)
 *   --capture-hit N    capture its Nth call (repeatable)
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
 * --trace does not go with --call or --capture (they share the hooks).
 *
 * Points, pokes and logs (points.h, inject.h, calllog.h):
 *
 *   --dump-at POINT    dump memory each time POINT fires: pc=ADDR,
 *                      frame=SET or cycle=SET, with hits=, after=, if=
 *                      and ranges= (points.h); repeatable
 *   --dump-stream FILE where the dumps go, one after the other ("-" for
 *                      stdout, with --state): a line of JSON a dump, then
 *                      its bytes (the format is below)
 *   --dump-limit BYTES the largest the stream may grow (default 1 GiB,
 *                      1073741824; 0x for hex)
 *   --dump-max N       the most dumps it may hold (default: no count)
 *                      A dump that would pass either is not written: the
 *                      stream ends with {"end": "dump-limit"} or
 *                      {"end": "dump-max"} and the run fails (status 2)
 *   --poke-file FILE   write memory at points of the run: lines of POINT
 *                      ADDR DATA (inject.h); repeatable
 *   --call-log ROUTINE log every call of ROUTINE: ADDR with name=, in=,
 *                      out=, mem=, jumps=, entry=, hits=, after=, if=
 *                      (calllog.h); repeatable
 *   --call-log-file FILE
 *                      where the call log goes
 *   --call-log-limit BYTES
 *                      the largest the call log may grow (default 1 GiB);
 *                      a line that passes it ends the run with an error
 *                      (status 2)
 *   --wad ADDR        the game's WAD in RAM (hex), for --lump
 *   --lump NAME:DEST:FILE
 *                      put FILE at DEST (hex) and point the WAD's entry
 *                      NAME there, before the run (inject.h); repeatable
 *
 * --call-log does not go with --trace, --call or --capture (the step
 * hook). At a moment where several fire, the pokes come first, in the
 * order given, then the dumps, in the order of the --dump-at options.
 *
 * The dump stream starts with a line
 *   {"format": "ref816-dump-stream 1", "points": ["POINT", ...]}
 * then, for each dump, a line
 *   {"dump": N, "point": I, "hit": H, "note": "...", "frame": F,
 *    "clock": C, "cycles": Y, "instructions": T, "cpu": {...},
 *    "switches": {...}, "peek": {...}, "ranges": [[ADDR, LEN], ...],
 *    "bytes": B}
 * followed by the B bytes of the ranges in order: N counts the dumps
 * from 1, I is the index of the --dump-at (from 0), H the arrival (pc) or
 * the frame or cycle count the point fired for, "note" the last note of
 * the input, and cpu, switches and peek (the --peek ranges now) as in the
 * final state. The last line is {"end": "REASON", "dumps": N}.
 *
 * Every frame or cycle point moves on past the moment it fired for, and
 * each turn of the run's loop makes progress; the machine checks both and
 * fails (status 2) rather than dump or poke again at the same moment.
 *
 * The final state is JSON: why the run ended, time, registers, a hash of
 * all RAM, the soft switches, the text page, and the counts of
 * everything the machine met that it does not model.
 */
#include "calllog.h"
#include "footprint.h"
#include "iigs.h"
#include "inject.h"
#include "points.h"
#include "program.h"
#include "trace.h"

#include <errno.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The cycles a --call may run without --frames or --cycles. */
#define CALL_CYCLES 1000000000u
/* The default bounds of the dump stream and the call log, in bytes. */
#define STREAM_LIMIT ((uint64_t)1 << 30)
/* Bytes kept free under --dump-limit for the stream's last line. */
#define END_RESERVE 128u

enum {
    MAX_LIST = 256,
    MAX_POINTS = 64,
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
    uint32_t address;
    uint32_t length;            /* --save only */
    const char *path;
    int image;                  /* --load-image: the records of an image */
} file_range;

/* A --lump: the entry's name, where the bytes go, the file. */
typedef struct {
    char name[9];
    uint32_t dest;
    const char *path;
} lump_option;

/* A --reg: which register, and its value. */
typedef struct {
    char name[4];
    uint32_t value;
} register_setting;

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
    file_range loads[MAX_LIST], saves[MAX_LIST];
    unsigned load_count, save_count;
    register_setting regs[MAX_LIST];
    unsigned reg_count;
    int call;                   /* --call given */
    uint32_t call_address;
    footprint_config footprint; /* --call and --capture */
    trace_config trace;         /* trace.path is NULL without --trace */
    int trace_options;          /* --trace-* options given */
    point dumps[MAX_POINTS];    /* --dump-at */
    const char *dump_texts[MAX_POINTS];
    unsigned dump_count;
    const char *dump_stream;
    uint64_t dump_limit, dump_max;
    const char *poke_files[MAX_LIST];
    unsigned poke_file_count;
    calllog_routine routines[CALLLOG_ROUTINES];     /* --call-log */
    unsigned routine_count;
    const char *call_log;
    uint64_t call_log_limit;
    int have_wad;
    uint32_t wad;
    lump_option lumps[MAX_LIST];
    unsigned lump_count;
} options;

/* What happens at points of the run: the pokes, the dumps, the call
   log, and the last note of the input. */
typedef struct {
    poke_list pokes;
    FILE *stream;
    uint64_t dumps;
    uint64_t stream_bytes;      /* written to the stream so far */
    calllog *log;
    char note[PROGRAM_NAME];
} extras;

/* How the run ended. */
typedef struct {
    const char *reason;         /* frames, cycles, stop, stop-pc, spin,
                                   opcode, timeout, late, return */
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

/* The records of an image into RAM. */
static void load_records(iigs *m, const char *path, const uint8_t *data,
                         size_t length)
{
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
}

static uint8_t *read_image(const char *path, size_t *length)
{
    uint8_t *data = read_file(path, length);
    if (*length < HEADER || memcmp(data, MAGIC, sizeof MAGIC - 1))
        fail("%s is not a ref816 memory image", path);
    return data;
}

/* The image: a header with the registers and the soft switches, then
   records of a 32-bit address, a 32-bit length and the bytes. */
static void load_image(iigs *m, const char *path)
{
    size_t length;
    uint8_t *data = read_image(path, &length);
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
    load_records(m, path, data, length);
    free(data);
}

/* --load, in order, then --reg, then --call's address. */
static void load_files(iigs *m, const options *o)
{
    for (unsigned i = 0; i < o->load_count; i++) {
        size_t length;
        const file_range *r = &o->loads[i];
        if (r->image) {
            uint8_t *data = read_image(r->path, &length);
            load_records(m, r->path, data, length);
            free(data);
            continue;
        }
        uint8_t *data = read_file(r->path, &length);
        if (!iigs_load(m, r->address, data, length))
            fail("--load %s: outside RAM", r->path);
        free(data);
    }
}

/* --lump, after the loads. */
static void place_lumps(iigs *m, const options *o)
{
    char error[512];
    for (unsigned i = 0; i < o->lump_count; i++) {
        const lump_option *l = &o->lumps[i];
        size_t length;
        uint8_t *data = read_file(l->path, &length);
        if (!lump_place(m, o->wad, l->name, l->dest, data, length, error,
                        sizeof error))
            fail("%s", error);
        free(data);
    }
}

static void set_registers(iigs *m, const options *o)
{
    cpu816 *c = &m->cpu;
    for (unsigned i = 0; i < o->reg_count; i++) {
        const char *name = o->regs[i].name;
        uint32_t v = o->regs[i].value;
        uint16_t *wide = !strcmp(name, "a") ? &c->a : !strcmp(name, "x") ?
            &c->x : !strcmp(name, "y") ? &c->y : !strcmp(name, "s") ?
            &c->s : !strcmp(name, "d") ? &c->d : !strcmp(name, "pc") ?
            &c->pc : NULL;
        uint8_t *narrow = !strcmp(name, "pbr") ? &c->pbr :
            !strcmp(name, "dbr") ? &c->dbr : !strcmp(name, "p") ? &c->p :
            !strcmp(name, "e") ? &c->e : NULL;
        if (wide)
            *wide = (uint16_t)v;
        else if (narrow && (v <= 0xff && (narrow != &c->e || v <= 1)))
            *narrow = (uint8_t)v;
        else
            fail("--reg %s=%X: no such register, or too wide", name, v);
    }
    if (o->call) {
        c->pbr = (uint8_t)(o->call_address >> 16);
        c->pc = (uint16_t)o->call_address;
    }
    if (o->reg_count)
        cpu816_normalise(c);
}

static void save_files(const iigs *m, const options *o)
{
    for (unsigned i = 0; i < o->save_count; i++) {
        const file_range *r = &o->saves[i];
        uint8_t *data = malloc(r->length);
        if (!data)
            fail("out of memory");
        for (uint32_t j = 0; j < r->length; j++)
            data[j] = iigs_peek(m, (r->address + j) & 0xffffff);
        write_file(r->path, data, r->length);
        free(data);
    }
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
                        footprint *calls, FILE *out)
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
    fputs("},\n", out);
    if (calls && o->call) {
        footprint_json(calls, out);
        fputs(",\n", out);
    }
    fputs("  \"text_page\": [\n", out);
    for (unsigned row = 0; row < TEXT_ROWS; row++) {
        char text[TEXT_COLUMNS + 1];
        text_row(m, row, text);
        fprintf(out, "    \"%s\"%s\n", text, row + 1 < TEXT_ROWS ? "," : "");
    }
    fputs("  ]\n}\n", out);
}

/* ---- dumps ---- */

/* A line of the stream, made in memory so that its length is known
   before it is written. */
typedef struct {
    char *data;
    size_t length, capacity;
} text;

static void add_text(text *t, const char *format, ...)
{
    for (;;) {
        va_list arguments;
        va_start(arguments, format);
        size_t room = t->capacity - t->length;
        int n = vsnprintf(t->data ? t->data + t->length : NULL, room, format,
                          arguments);
        va_end(arguments);
        if (n < 0)
            fail("cannot format a dump's header");
        if ((size_t)n < room) {
            t->length += (size_t)n;
            return;
        }
        size_t capacity = t->capacity ? 2 * t->capacity : 4096;
        while (capacity - t->length <= (size_t)n)
            capacity *= 2;
        char *grown = realloc(t->data, capacity);
        if (!grown)
            fail("out of memory");
        t->data = grown;
        t->capacity = capacity;
    }
}

static void json_text(text *out, const char *value)
{
    add_text(out, "\"");
    for (; *value; value++)
        if (*value == '"' || *value == '\\' || (unsigned char)*value < 0x20)
            add_text(out, "\\u%04x", (unsigned char)*value);
        else
            add_text(out, "%c", *value);
    add_text(out, "\"");
}

static void stream_header(extras *x, const options *o)
{
    text line = { NULL, 0, 0 };
    add_text(&line, "{\"format\": \"ref816-dump-stream 1\", \"points\": [");
    for (unsigned i = 0; i < o->dump_count; i++) {
        if (i)
            add_text(&line, ", ");
        json_text(&line, o->dump_texts[i]);
    }
    add_text(&line, "]}\n");
    if (line.length + END_RESERVE > o->dump_limit)
        fail("--dump-limit %" PRIu64 " is too small for the stream's first "
             "line", o->dump_limit);
    fwrite(line.data, 1, line.length, x->stream);
    x->stream_bytes += line.length;
    free(line.data);
}

/* The stream's last line. */
static void stream_end(extras *x, const char *reason)
{
    int n = fprintf(x->stream, "{\"end\": \"%s\", \"dumps\": %" PRIu64 "}\n",
                    reason, x->dumps);
    if (n > 0)
        x->stream_bytes += (uint64_t)n;
}

/* The bytes of `length` from `address` (all in RAM: points.c checked). */
static void dump_range(FILE *out, const iigs *m, uint32_t address,
                       uint32_t length)
{
    while (length) {
        uint32_t chunk = IIGS_BANK - (address & 0xffff);
        if (chunk > length)
            chunk = length;
        unsigned bank = address >> 16;
        const uint8_t *data = bank < IIGS_RAM_BANKS ? m->ram + address
            : m->mega + (address - 0xe00000u);
        fwrite(data, 1, chunk, out);
        address += chunk;
        length -= chunk;
    }
}

/* Dump for the --dump-at `index`, unless the dump would pass --dump-max
   or --dump-limit: then the stream ends and the run fails. */
static void write_dump(extras *x, const iigs *m, const options *o,
                       unsigned index)
{
    const point *p = &o->dumps[index];
    const cpu816 *c = &m->cpu;
    FILE *out = x->stream;
    text h = { NULL, 0, 0 };
    add_text(&h, "{\"dump\": %" PRIu64 ", \"point\": %u, \"hit\": %" PRIu64
             ", \"note\": ", x->dumps + 1, index, point_hit(p));
    json_text(&h, x->note);
    add_text(&h, ", \"frame\": %" PRIu64 ", \"clock\": %" PRIu64
             ", \"cycles\": %" PRIu64 ", \"instructions\": %" PRIu64,
             m->frame, iigs_clock(m), c->cycles, m->instructions);
    add_text(&h, ", \"cpu\": {\"pc\": %" PRIu32 ", \"a\": %u, \"x\": %u, "
             "\"y\": %u, \"s\": %u, \"d\": %u, \"dbr\": %u, \"p\": %u, "
             "\"e\": %u}", (uint32_t)c->pbr << 16 | c->pc, c->a, c->x, c->y,
             c->s, c->d, c->dbr, c->p, c->e);
    add_text(&h, ", \"switches\": {\"shadow\": %u, \"speed\": %u, "
             "\"newvideo\": %u, \"border\": %u, \"text\": %u, "
             "\"inten\": %u, \"vgc_int\": %u}", m->shadow, m->speed,
             m->newvideo, m->border, m->text, m->inten, m->vgc_int);
    add_text(&h, ", \"peek\": {");
    for (unsigned i = 0; i < o->peek_count; i++) {
        add_text(&h, "%s\"%06" PRIX32 "\": \"", i ? ", " : "",
                 o->peeks[i].address);
        for (uint32_t j = 0; j < o->peeks[i].length; j++)
            add_text(&h, "%02x", iigs_peek(m, o->peeks[i].address + j));
        add_text(&h, "\"");
    }
    add_text(&h, "}, \"ranges\": [");
    if (!p->range_count)
        add_text(&h, "[0, %u], [%u, %u]", IIGS_RAM_BANKS * IIGS_BANK,
                 0xe00000u, 2 * IIGS_BANK);
    for (unsigned i = 0; i < p->range_count; i++)
        add_text(&h, "%s[%" PRIu32 ", %" PRIu32 "]", i ? ", " : "",
                 p->range_address[i], p->range_length[i]);
    add_text(&h, "], \"bytes\": %" PRIu64 "}\n", point_dump_bytes(p));

    uint64_t bytes = h.length + point_dump_bytes(p);
    if (x->dumps >= o->dump_max) {
        stream_end(x, "dump-max");
        fail("--dump-at %s: dump %" PRIu64 " would pass --dump-max %" PRIu64
             " (frame %" PRIu64 ", cycle %" PRIu64 "); the stream ends there",
             o->dump_texts[index], x->dumps + 1, o->dump_max, m->frame,
             c->cycles);
    }
    if (x->stream_bytes + bytes + END_RESERVE > o->dump_limit) {
        stream_end(x, "dump-limit");
        fail("--dump-at %s: dump %" PRIu64 " (%" PRIu64 " bytes) would take "
             "the stream past --dump-limit %" PRIu64 " bytes (frame %" PRIu64
             ", cycle %" PRIu64 "); the stream ends there",
             o->dump_texts[index], x->dumps + 1, bytes, o->dump_limit,
             m->frame, c->cycles);
    }
    x->dumps++;
    x->stream_bytes += bytes;
    fwrite(h.data, 1, h.length, out);
    free(h.data);
    if (!p->range_count) {
        dump_range(out, m, 0, IIGS_RAM_BANKS * IIGS_BANK);
        dump_range(out, m, 0xe00000u, 2 * IIGS_BANK);
    }
    for (unsigned i = 0; i < p->range_count; i++)
        dump_range(out, m, p->range_address[i], p->range_length[i]);
}

/* The machine stopped between instructions (at a breakpoint at `pc`
   when `at_break`): the pokes, then the dumps, that fire now. */
static void at_points(iigs *m, options *o, extras *x, int at_break,
                      uint32_t pc)
{
    for (size_t i = 0; i < x->pokes.count; i++) {
        poke *p = &x->pokes.pokes[i];
        if (point_fires(&p->when, m, at_break && p->when.pc == pc))
            poke_apply(m, p);
    }
    for (unsigned i = 0; i < o->dump_count; i++)
        if (point_fires(&o->dumps[i], m, at_break && o->dumps[i].pc == pc))
            write_dump(x, m, o, i);
}

/* The first frame and cycle at which a point of `o` or `x` is due. */
static uint64_t points_due(const options *o, const extras *x, int frames)
{
    uint64_t due = UINT64_MAX, next;
    for (size_t i = 0; i < x->pokes.count; i++) {
        const point *p = &x->pokes.pokes[i].when;
        next = frames ? point_due_frame(p) : point_due_cycle(p);
        due = next < due ? next : due;
    }
    for (unsigned i = 0; i < o->dump_count; i++) {
        next = frames ? point_due_frame(&o->dumps[i])
                      : point_due_cycle(&o->dumps[i]);
        due = next < due ? next : due;
    }
    return due;
}

/* After at_points: every frame and cycle point is next due after now
   (points.h: a point moves on past the moment it fired for). A point
   due now would stop the next iigs_run before any instruction and fire
   again at the same moment, for ever. */
static void check_points_move_on(const options *o, const extras *x,
                                 const iigs *m)
{
    uint64_t frame = points_due(o, x, 1), cycle = points_due(o, x, 0);
    if ((frame != UINT64_MAX && frame <= m->frame) ||
        (cycle != UINT64_MAX && cycle <= m->cpu.cycles))
        fail("a point is due again at frame %" PRIu64 ", cycle %" PRIu64
             " where it fired (internal error: points.c)", m->frame,
             m->cpu.cycles);
}

static void notes(options *o, extras *x, const char *name)
{
    snprintf(x->note, sizeof x->note, "%s", name);
    for (size_t i = 0; i < x->pokes.count; i++)
        point_note(&x->pokes.pokes[i].when, name);
    for (unsigned i = 0; i < o->dump_count; i++)
        point_note(&o->dumps[i], name);
    if (x->log)
        calllog_note(x->log, name);
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

/* --load ADDR:FILE, --save ADDR:LEN:FILE */
static void file_option(options *o, const char *arg, char *value)
{
    int save = !strcmp(arg, "--save");
    file_range *list = save ? o->saves : o->loads;
    unsigned *count = save ? &o->save_count : &o->load_count;
    char *colon = strchr(value, ':');
    char *second = colon && save ? strchr(colon + 1, ':') : colon;
    if (!colon || !second || !second[1] || *count == MAX_LIST)
        fail(save ? "--save takes ADDR:LEN:FILE" : "--load takes ADDR:FILE");
    *colon = 0;
    file_range *r = &list[(*count)++];
    r->address = (uint32_t)address(value, arg);
    r->length = 0;
    r->image = 0;
    if (save) {
        *second = 0;
        uint64_t length = number(colon + 1, 0);
        if (!length || length > 0x1000000)
            fail("--save: 1 to 16 MB");
        r->length = (uint32_t)length;
    }
    r->path = second + 1;
}

static void parse(int argc, char **argv, options *o)
{
    memset(o, 0, sizeof *o);
    o->frames = o->cycles = UINT64_MAX;
    o->dump_limit = o->call_log_limit = STREAM_LIMIT;
    o->dump_max = UINT64_MAX;
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
        } else if (!strcmp(arg, "--load") || !strcmp(arg, "--save"))
            file_option(o, arg, argv[i]);
        else if (!strcmp(arg, "--load-image")) {
            if (o->load_count == MAX_LIST)
                fail("at most %d of each option", MAX_LIST);
            o->loads[o->load_count++] = (file_range){ 0, 0, value, 1 };
        } else if (!strcmp(arg, "--reg")) {
            const char *equals = strchr(value, '=');
            if (!equals || equals == value || equals - value > 3 ||
                o->reg_count == MAX_LIST)
                fail("--reg takes NAME=VALUE");
            register_setting *r = &o->regs[o->reg_count++];
            memset(r->name, 0, sizeof r->name);
            memcpy(r->name, value, (size_t)(equals - value));
            uint64_t v = number(equals + 1, 16);
            if (v > 0xffff)
                fail("--reg %s: at most 16 bits", r->name);
            r->value = (uint32_t)v;
        } else if (!strcmp(arg, "--call")) {
            o->call = 1;
            o->call_address = (uint32_t)address(value, arg);
        } else if (!strcmp(arg, "--call-reads"))
            o->footprint.reads_path = value;
        else if (!strcmp(arg, "--call-writes"))
            o->footprint.writes_path = value;
        else if (!strcmp(arg, "--capture"))
            o->footprint.capture_dir = value;
        else if (!strcmp(arg, "--capture-entry"))
            o->footprint.entry = (uint32_t)address(value, arg);
        else if (!strcmp(arg, "--capture-hit")) {
            uint64_t hit = number(value, 0);
            if (!hit || o->footprint.hit_count == FOOTPRINT_MAX_HITS)
                fail("--capture-hit takes a call from 1, at most %d of them",
                     FOOTPRINT_MAX_HITS);
            o->footprint.hits[o->footprint.hit_count++] = hit;
        } else if (!strcmp(arg, "--dump-at")) {
            char error[512];
            if (o->dump_count == MAX_POINTS)
                fail("at most %d --dump-at", MAX_POINTS);
            if (!point_parse(&o->dumps[o->dump_count], value, POINT_FOR_DUMP,
                             error, sizeof error))
                fail("--dump-at %s", error);
            o->dump_texts[o->dump_count++] = value;
        } else if (!strcmp(arg, "--dump-stream"))
            o->dump_stream = value;
        else if (!strcmp(arg, "--dump-limit"))
            o->dump_limit = number(value, 0);
        else if (!strcmp(arg, "--dump-max"))
            o->dump_max = number(value, 0);
        else if (!strcmp(arg, "--call-log-limit"))
            o->call_log_limit = number(value, 0);
        else if (!strcmp(arg, "--poke-file")) {
            if (o->poke_file_count == MAX_LIST)
                fail("at most %d of each option", MAX_LIST);
            o->poke_files[o->poke_file_count++] = value;
        } else if (!strcmp(arg, "--call-log")) {
            char error[512];
            if (o->routine_count == CALLLOG_ROUTINES)
                fail("at most %d --call-log", CALLLOG_ROUTINES);
            if (!calllog_parse(&o->routines[o->routine_count++], value,
                               error, sizeof error))
                fail("%s", error);
        } else if (!strcmp(arg, "--call-log-file"))
            o->call_log = value;
        else if (!strcmp(arg, "--wad")) {
            o->wad = (uint32_t)address(value, arg);
            o->have_wad = 1;
        } else if (!strcmp(arg, "--lump")) {
            char *first = strchr(argv[i], ':');
            char *second = first ? strchr(first + 1, ':') : NULL;
            if (!first || !second || !second[1] || first == argv[i] ||
                first - argv[i] > 8 || o->lump_count == MAX_LIST)
                fail("--lump takes NAME:DEST:FILE, NAME of 1 to 8 "
                     "characters");
            lump_option *l = &o->lumps[o->lump_count++];
            memset(l->name, 0, sizeof l->name);
            memcpy(l->name, argv[i], (size_t)(first - argv[i]));
            *second = 0;
            l->dest = (uint32_t)address(first + 1, arg);
            l->path = second + 1;
        } else
            fail("unknown option %s", arg);
    }
    if (o->call && o->frames == UINT64_MAX && o->cycles == UINT64_MAX)
        o->cycles = CALL_CYCLES;
    if (!o->call && (o->footprint.reads_path || o->footprint.writes_path))
        fail("--call-reads and --call-writes need --call");
    if (!o->footprint.capture_dir != !o->footprint.hit_count ||
        (o->footprint.capture_dir && !o->footprint.entry))
        fail("--capture needs --capture-entry and --capture-hit");
    if (o->call && o->footprint.capture_dir)
        fail("--call and --capture go in separate runs");
    if (o->trace.path && (o->call || o->footprint.capture_dir))
        fail("--trace does not go with --call or --capture");
    o->footprint.call = o->call;
    if (!o->image)
        fail("usage: ref816 [options] IMAGE (see the source for options)");
    if (o->frames == UINT64_MAX && o->cycles == UINT64_MAX)
        fail("give --frames or --cycles");
    if (o->mark_pc_count && !o->marks)
        fail("--mark needs --marks");
    if (o->trace_options && !o->trace.path)
        fail("the --trace-* options need --trace");
    if (!o->dump_count != !o->dump_stream)
        fail("--dump-at and --dump-stream go together");
    if (o->dump_stream && !strcmp(o->dump_stream, "-") && !o->state)
        fail("--dump-stream - needs --state");
    if (!o->routine_count != !o->call_log)
        fail("--call-log and --call-log-file go together");
    if (!o->call_log_limit)
        fail("--call-log-limit takes a size from 1");
    if (o->routine_count && (o->trace.path || o->call ||
                             o->footprint.capture_dir))
        fail("--call-log does not go with --trace, --call or --capture");
    if (o->lump_count && !o->have_wad)
        fail("--lump needs --wad");
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
static void input(program *p, iigs *m, options *o, extras *x, FILE *marks,
                  trace *tracer, footprint *calls, ending *end)
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
            if (calls)
                footprint_note(calls, s->name);
            notes(o, x, s->name);
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
    load_files(&m, &o);
    place_lumps(&m, &o);
    set_registers(&m, &o);
    m.stop_on_fault = o.stop_on_fault;
    for (unsigned i = 0; i < o.stop_pc_count; i++)
        if (!iigs_set_break(&m, (uint32_t)o.stop_pcs[i]))
            fail("out of memory");
    for (unsigned i = 0; i < o.mark_pc_count; i++)
        if (!iigs_set_break(&m, (uint32_t)o.mark_pcs[i]))
            fail("out of memory");
    extras x;
    memset(&x, 0, sizeof x);
    for (unsigned i = 0; i < o.poke_file_count; i++)
        if (!pokes_read(&x.pokes, o.poke_files[i], error, sizeof error))
            fail("%s", error);
    for (size_t i = 0; i < x.pokes.count; i++)
        if (x.pokes.pokes[i].when.kind == POINT_PC &&
            !iigs_set_break(&m, x.pokes.pokes[i].when.pc))
            fail("out of memory");
    for (unsigned i = 0; i < o.dump_count; i++)
        if (o.dumps[i].kind == POINT_PC &&
            !iigs_set_break(&m, o.dumps[i].pc))
            fail("out of memory");
    if (o.dump_stream) {
        x.stream = strcmp(o.dump_stream, "-") ? fopen(o.dump_stream, "wb")
                                              : stdout;
        if (!x.stream)
            fail("cannot write %s", o.dump_stream);
        stream_header(&x, &o);
    }

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
    footprint *calls = NULL;
    qsort(o.footprint.hits, o.footprint.hit_count, sizeof(uint64_t),
          compare_u64);
    if ((o.call || o.footprint.capture_dir) &&
        !(calls = footprint_open(&m, &o.footprint)))
        fail("out of memory");
    if (o.routine_count &&
        !(x.log = calllog_open(&m, o.routines, o.routine_count, o.call_log,
                               error, sizeof error)))
        fail("%s", error);
    if (x.log)
        calllog_set_limit(x.log, o.call_log_limit);

    qsort(o.shot_frames, o.shot_frame_count, sizeof(uint64_t), compare_u64);
    qsort(o.shot_cycles, o.shot_cycle_count, sizeof(uint64_t), compare_u64);
    unsigned next_frame_shot = 0, next_cycle_shot = 0;
    ending end = { NULL, 0, 0 };

    /* The input's steps at frame 0 come before any instruction, and so
       do the points of frame 0 and cycle 0. */
    input(&p, &m, &o, &x, marks, tracer, calls, &end);
    at_points(&m, &o, &x, 0, 0);
    check_points_move_on(&o, &x, &m);
    while (!end.reason) {
        uint64_t before_cycles = m.cpu.cycles, before_frame = m.frame;
        uint64_t before_instructions = m.instructions;
        uint64_t frame_stop = minimum(minimum(minimum(
            o.frames, upcoming(o.shot_frames, o.shot_frame_count,
                               next_frame_shot)), program_due(&p)),
            points_due(&o, &x, 1));
        uint64_t cycle_stop = minimum(minimum(
            o.cycles, upcoming(o.shot_cycles, o.shot_cycle_count,
                               next_cycle_shot)), points_due(&o, &x, 0));
        iigs_stop why = iigs_run(&m, cycle_stop, frame_stop);
        uint32_t pc = (uint32_t)m.cpu.pbr << 16 | m.cpu.pc;
        if (x.log && calllog_problem(x.log))
            fail("%s", calllog_problem(x.log));

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
        } else if (why == IIGS_REQUEST && calls && footprint_returned(calls))
            end.reason = "return";
        else
            input(&p, &m, &o, &x, marks, tracer, calls, &end);
        at_points(&m, &o, &x, why == IIGS_BREAK, pc);
        check_points_move_on(&o, &x, &m);
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
        /* A turn that ran nothing and stopped at a limit that is not the
           run's own would repeat for ever: something is due now that
           nothing above moved on. */
        if (!end.reason && why == IIGS_LIMIT && m.cpu.cycles == before_cycles &&
            m.frame == before_frame && m.instructions == before_instructions)
            fail("the run makes no progress at frame %" PRIu64 ", cycle %"
                 PRIu64 " (internal error: a stop is due now)", m.frame,
                 m.cpu.cycles);
    }

    if (tracer && !trace_close(tracer))
        fail("cannot write %s", o.trace.path);
    if (x.log) {
        const char *problem = calllog_close(x.log);
        if (problem)
            fail("%s", problem);
    }
    if (x.stream) {
        stream_end(&x, end.reason);
        if (ferror(x.stream) || (x.stream != stdout && fclose(x.stream)) ||
            (x.stream == stdout && fflush(stdout)))
            fail("cannot write %s", o.dump_stream);
    }
    log_line(marks, "end", "-", &m);
    if (marks && fclose(marks))
        fail("cannot write %s", o.marks);
    FILE *out = stdout;
    if (o.state && !(out = fopen(o.state, "w")))
        fail("cannot write %s", o.state);
    write_state(&m, &o, &end, calls, out);
    if (out != stdout && fclose(out))
        fail("cannot write %s", o.state);
    if (calls) {
        const char *error = footprint_close(calls);
        if (error)
            fail("%s", error);
    }
    save_files(&m, &o);
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
    pokes_free(&x.pokes);
    program_free(&p);
    iigs_free(&m);
    return 0;
}
