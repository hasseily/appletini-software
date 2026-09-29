/*
 * a2vm: run a program on the model of the Appletini target (a2vm.h).
 *
 * usage: a2vm --rom FILE [options]
 *
 * Machine
 *   --rom FILE          the Apple //e enhanced ROM, 16 KB for $C000-$FFFF
 *   --core py65|w65c02s the compatibility core (default) or the exact one
 *   --speed turbo|N     a2sim.py's timing presets: "turbo" (default),
 *                       1,250,000 cycles a 60 Hz frame and 73 extra cycles
 *                       an access to $C000-$CFFF; N, 17,030 * N cycles a
 *                       frame and no extra cycles
 *   --io-cycles N       the extra cycles of an access to $C000-$CFFF
 *   --banks N           RamWorks banks, 1-128 (default 128)
 *   --no-mouse          no mouse card in slot 2
 *   --amem              the memory API in slot 7 (FakeSmartPortMemory)
 *   --amem-unsupported, --amem-unavailable
 *                       its STATUS answers $21, its CONTROL $60
 *
 * Start
 *   --image FILE        memory records (A2VMIMG1, see README.md)
 *   --load ADDR:FILE    a binary into main memory (hex address)
 *   --load-aux BANK:ADDR:FILE
 *                       a binary into a RamWorks bank (decimal bank)
 *   --reg NAME=HEX      pc, a, x, y, s or p
 *   --switch NAME=N     a soft switch (store80 ... hires), lc_read,
 *                       lc_write, lc_prewrite, lc_bank2, bank, newvideo
 *   --prodos FILE       the MLI trap with the files of FILE, one a line:
 *                       NAME TYPE AUX PATH (type and aux in hex)
 *   --volume NAME, --launched NAME
 *                       the volume (DOOM) and the system file's name
 *                       (DOOM.SYSTEM) the trap reports
 *   --idle SPEC         an idle loop to skip: PC:vbl or PC:line0, then
 *                       conditions :main (ALTZP off), :invbl, :eq=A,B
 *                       (main words at A and B equal); hex addresses
 *
 * Run
 *   --boundary ADDR     a frame boundary: the CPU at ADDR after a step,
 *                       with ALTZP off
 *   --boundaries N      stop at the Nth boundary
 *   --cycles N          stop once the clock reaches N
 *   --stop-pc ADDR      stop at ADDR (hex; ALTZP off with a :main suffix)
 *   --input FILE        events, one a line: WHEN ACTION (README.md)
 *   --snapshot-dir DIR  where snapshots, shots and the state go
 *   --snapshot-boundaries
 *                       a snapshot at every boundary
 *   --final-snapshot    a snapshot when the run ends
 *   --state FILE        the final state as JSON (default: stdout)
 *   --bus-script FILE   instead of running the CPU, run the bus commands
 *                       of FILE (README.md) and print their results
 *
 * Cost model (cost.h)
 *   --cost FILE         charge every access with the parameters of FILE
 *                       ("name value" lines; tools/a2vm/costs.py writes
 *                       them from a profile of costs/appletini.json)
 *   --cost-timed        run the machine on the model's clock: the video
 *                       frame, $C019, the mouse interrupt and the idle
 *                       skips follow it (otherwise the model only
 *                       observes, and a compatibility run is unchanged)
 *   --cost-phase ADDR   a main-memory byte whose writes (ALTZP off) mark
 *                       phases: the phase is the value written / 2
 *   --cost-report FILE  a JSON line at every frame boundary: the model's
 *                       clocks, by phase, and its counters
 *
 * A snapshot NAME is NAME.json (the state: registers, time, switches,
 * devices, files) and NAME.ram: main 64 KB, the main language card 16 KB
 * ($C000-$FFFF, a2sim's lc[False]), its bank 1 4 KB, then the 128 aux
 * banks of 64 KB.
 */
#include "a2vm.h"

#include <errno.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum {
    MAX_LIST = 64, MAX_EVENTS = 4096,
    SHOT_BYTES = 0x8000
};

static void fail(const char *format, ...)
{
    va_list arguments;
    va_start(arguments, format);
    fputs("a2vm: ", stderr);
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

static int64_t signed_number(const char *text)
{
    char *end;
    errno = 0;
    long long value = strtoll(text, &end, 0);
    if (errno || end == text || *end)
        fail("not a number: %s", text);
    return value;
}

static uint16_t address16(const char *text)
{
    uint64_t value = number(text, 16);
    if (value > 0xffff)
        fail("not a 16-bit address: %s", text);
    return (uint16_t)value;
}

static uint8_t *read_file(const char *path, size_t *length)
{
    FILE *file = fopen(path, "rb");
    if (!file)
        fail("cannot open %s: %s", path, strerror(errno));
    size_t capacity = 1 << 16, used = 0;
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

/* ---- options ---- */

typedef enum {
    ACT_KEY, ACT_HOLD, ACT_RELEASE, ACT_MOUSE, ACT_MOUSE_TO, ACT_BUTTONS,
    ACT_OA, ACT_CA, ACT_SNAPSHOT, ACT_SHOT, ACT_STOP
} action_kind;

typedef enum { WHEN_START, WHEN_BOUNDARY, WHEN_CYCLE, WHEN_PC } when_kind;

typedef struct {
    when_kind when;
    uint64_t value;             /* boundary number, cycle, pc */
    int main_only;              /* WHEN_PC: with ALTZP off */
    action_kind action;
    int64_t a, b;
    char name[64];
    int done;
    unsigned line;
} event;

typedef struct {
    uint16_t pc;
    int main_only;
} stop_pc;

typedef struct {
    a2vm_config config;
    const char *image, *prodos, *input, *snapshot_dir, *state, *bus_script;
    const char *volume, *launched;
    const char *cost, *cost_report;
    int cost_timed, cost_phase;
    const char *loads[MAX_LIST], *aux_loads[MAX_LIST], *regs[MAX_LIST],
        *switches[MAX_LIST], *idles[MAX_LIST];
    unsigned load_count, aux_load_count, reg_count, switch_count, idle_count;
    int amem_supported, amem_available;
    uint16_t boundary;
    int has_boundary;
    uint64_t boundaries, cycles;
    stop_pc stops[MAX_LIST];
    unsigned stop_count;
    int snapshot_boundaries, final_snapshot;
} options;

static void add(const char **list, unsigned *count, const char *value)
{
    if (*count == MAX_LIST)
        fail("at most %d of each option", MAX_LIST);
    list[(*count)++] = value;
}

static void parse(int argc, char **argv, options *o)
{
    memset(o, 0, sizeof *o);
    a2vm_default_config(&o->config);
    o->amem_supported = o->amem_available = 1;
    o->boundaries = o->cycles = UINT64_MAX;
    o->volume = "DOOM";
    o->cost_phase = -1;
    o->launched = "DOOM.SYSTEM";
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!strcmp(arg, "--no-mouse")) {
            o->config.mouse = 0;
            continue;
        }
        if (!strcmp(arg, "--amem")) {
            o->config.amem = 1;
            continue;
        }
        if (!strcmp(arg, "--amem-unsupported")) {
            o->amem_supported = 0;
            continue;
        }
        if (!strcmp(arg, "--amem-unavailable")) {
            o->amem_available = 0;
            continue;
        }
        if (!strcmp(arg, "--snapshot-boundaries")) {
            o->snapshot_boundaries = 1;
            continue;
        }
        if (!strcmp(arg, "--final-snapshot")) {
            o->final_snapshot = 1;
            continue;
        }
        if (!strcmp(arg, "--cost-timed")) {
            o->cost_timed = 1;
            continue;
        }
        if (i + 1 == argc)
            fail("%s needs a value (or is unknown)", arg);
        const char *value = argv[++i];
        if (!strcmp(arg, "--rom"))
            o->config.rom_path = value;
        else if (!strcmp(arg, "--core")) {
            if (!strcmp(value, "py65"))
                o->config.core = A2VM_CORE_PY65;
            else if (!strcmp(value, "w65c02s"))
                o->config.core = A2VM_CORE_W65C02S;
            else
                fail("--core takes py65 or w65c02s");
        } else if (!strcmp(arg, "--speed")) {
            if (!strcmp(value, "turbo"))
                o->config.turbo = 1;
            else {
                o->config.turbo = 0;
                uint64_t speed = number(value, 10);
                if (speed < 1 || speed > 1000)
                    fail("--speed takes turbo or 1 to 1000");
                o->config.speed = (unsigned)speed;
            }
        } else if (!strcmp(arg, "--io-cycles"))
            o->config.io_cycles = (int64_t)number(value, 0);
        else if (!strcmp(arg, "--banks"))
            o->config.ramworks_banks = (unsigned)number(value, 0);
        else if (!strcmp(arg, "--image"))
            o->image = value;
        else if (!strcmp(arg, "--load"))
            add(o->loads, &o->load_count, value);
        else if (!strcmp(arg, "--load-aux"))
            add(o->aux_loads, &o->aux_load_count, value);
        else if (!strcmp(arg, "--reg"))
            add(o->regs, &o->reg_count, value);
        else if (!strcmp(arg, "--switch"))
            add(o->switches, &o->switch_count, value);
        else if (!strcmp(arg, "--idle"))
            add(o->idles, &o->idle_count, value);
        else if (!strcmp(arg, "--prodos"))
            o->prodos = value;
        else if (!strcmp(arg, "--volume"))
            o->volume = value;
        else if (!strcmp(arg, "--launched"))
            o->launched = value;
        else if (!strcmp(arg, "--boundary")) {
            o->boundary = address16(value);
            o->has_boundary = 1;
        } else if (!strcmp(arg, "--boundaries"))
            o->boundaries = number(value, 0);
        else if (!strcmp(arg, "--cycles"))
            o->cycles = number(value, 0);
        else if (!strcmp(arg, "--stop-pc")) {
            if (o->stop_count == MAX_LIST)
                fail("too many --stop-pc");
            char text[32];
            snprintf(text, sizeof text, "%s", value);
            char *colon = strchr(text, ':');
            stop_pc *s = &o->stops[o->stop_count++];
            s->main_only = colon && !strcmp(colon, ":main");
            if (colon)
                *colon = 0;
            s->pc = address16(text);
        } else if (!strcmp(arg, "--input"))
            o->input = value;
        else if (!strcmp(arg, "--snapshot-dir"))
            o->snapshot_dir = value;
        else if (!strcmp(arg, "--state"))
            o->state = value;
        else if (!strcmp(arg, "--bus-script"))
            o->bus_script = value;
        else if (!strcmp(arg, "--cost"))
            o->cost = value;
        else if (!strcmp(arg, "--cost-report"))
            o->cost_report = value;
        else if (!strcmp(arg, "--cost-phase"))
            o->cost_phase = address16(value);
        else
            fail("unknown option %s", arg);
    }
    if (!o->config.rom_path)
        fail("give --rom (the Apple //e enhanced ROM)");
    if ((o->snapshot_boundaries || o->final_snapshot) && !o->snapshot_dir)
        fail("snapshots need --snapshot-dir");
    if ((o->cost_timed || o->cost_report || o->cost_phase >= 0) && !o->cost)
        fail("the cost options need --cost");
}

/* ---- loading ---- */

static uint32_t le(const uint8_t *p, int bytes)
{
    uint32_t value = 0;
    for (int i = bytes - 1; i >= 0; i--)
        value = value << 8 | p[i];
    return value;
}

/* A2VMIMG1: records of kind (1 byte: 0 main, 1 aux bank, 2 main LC
   $C000-$FFFF, 3 main LC bank 1), bank (1), address (2), length (4),
   then the bytes. */
static void load_image(a2vm *m, const char *path)
{
    size_t length;
    uint8_t *data = read_file(path, &length);
    if (length < 8 || memcmp(data, "A2VMIMG1", 8))
        fail("%s is not an a2vm image", path);
    size_t at = 8;
    while (at < length) {
        if (length - at < 8)
            fail("%s: a record is cut short", path);
        unsigned kind = data[at], bank = data[at + 1];
        unsigned address = le(data + at + 2, 2);
        uint32_t count = le(data + at + 4, 4);
        at += 8;
        if (count > length - at)
            fail("%s: a record is cut short", path);
        size_t limit = kind == 3 ? 0xe000 : 0x10000;
        uint8_t *target = a2vm_storage(m, (int)kind, bank, (uint16_t)address);
        if (!target || address + (size_t)count > limit)
            fail("%s: a record of kind %u at $%04X is outside its memory",
                 path, kind, address);
        memcpy(target, data + at, count);
        at += count;
    }
    free(data);
}

static void load_binary(a2vm *m, int kind, unsigned bank, const char *spec)
{
    char text[1024];
    snprintf(text, sizeof text, "%s", spec);
    char *colon = strchr(text, ':');
    if (!colon)
        fail("a load takes ADDR:FILE");
    *colon = 0;
    uint16_t address = address16(text);
    size_t length;
    uint8_t *data = read_file(colon + 1, &length);
    if (address + length > 0x10000)
        fail("%s does not fit at $%04X", colon + 1, address);
    memcpy(a2vm_storage(m, kind, bank, address), data, length);
    free(data);
}

static void load_aux(a2vm *m, const char *spec)
{
    char text[1024];
    snprintf(text, sizeof text, "%s", spec);
    char *colon = strchr(text, ':');
    if (!colon)
        fail("--load-aux takes BANK:ADDR:FILE");
    *colon = 0;
    uint64_t bank = number(text, 10);
    if (bank >= A2VM_MAX_BANKS)
        fail("no aux bank %s", text);
    load_binary(m, 1, (unsigned)bank, colon + 1);
}

static void set_register(a2vm *m, const char *spec)
{
    char name[8];
    const char *equals = strchr(spec, '=');
    if (!equals || equals - spec >= (long)sizeof name)
        fail("--reg takes NAME=HEX");
    memcpy(name, spec, (size_t)(equals - spec));
    name[equals - spec] = 0;
    uint64_t value = number(equals + 1, 16);
    if (!strcmp(name, "pc") && value <= 0xffff)
        a2vm_set_register(m, 'c', (unsigned)value);
    else if (strlen(name) == 1 && strchr("axysp", name[0]) && value <= 0xff)
        a2vm_set_register(m, name[0], (unsigned)value);
    else
        fail("--reg: %s", spec);
}

static void set_switch(a2vm *m, const char *spec)
{
    char name[32];
    const char *equals = strchr(spec, '=');
    if (!equals || equals - spec >= (long)sizeof name)
        fail("--switch takes NAME=N");
    memcpy(name, spec, (size_t)(equals - spec));
    name[equals - spec] = 0;
    uint64_t value = number(equals + 1, 0);
    for (int i = 0; i < SW_COUNT; i++)
        if (!strcmp(name, a2vm_switch_names[i])) {
            m->sw[i] = value != 0;
            a2vm_remap(m);
            return;
        }
    if (!strcmp(name, "lc_read"))
        m->lc_read = value != 0;
    else if (!strcmp(name, "lc_write"))
        m->lc_write = value != 0;
    else if (!strcmp(name, "lc_prewrite"))
        m->lc_prewrite = value != 0;
    else if (!strcmp(name, "lc_bank2"))
        m->lc_bank2 = value != 0;
    else if (!strcmp(name, "bank"))
        a2vm_select_bank(m, (unsigned)value);
    else if (!strcmp(name, "newvideo"))
        m->newvideo = (uint8_t)value;
    else
        fail("--switch: unknown switch %s", name);
    a2vm_remap(m);
}

static void add_idle(a2vm *m, const char *spec)
{
    char text[128];
    snprintf(text, sizeof text, "%s", spec);
    a2vm_idle idle;
    memset(&idle, 0, sizeof idle);
    char *part = strtok(text, ":");
    if (!part)
        fail("--idle takes PC:KIND[:CONDITION...]");
    idle.pc = address16(part);
    part = strtok(NULL, ":");
    if (!part)
        fail("--idle takes PC:KIND[:CONDITION...]");
    if (!strcmp(part, "vbl"))
        idle.kind = A2VM_IDLE_VBL;
    else if (!strcmp(part, "line0"))
        idle.kind = A2VM_IDLE_LINE0;
    else
        fail("--idle: the kind is vbl or line0, not %s", part);
    while ((part = strtok(NULL, ":"))) {
        if (!strcmp(part, "main"))
            idle.need_main_zp = 1;
        else if (!strcmp(part, "invbl"))
            idle.need_vbl = 1;
        else if (!strncmp(part, "eq=", 3)) {
            char *comma = strchr(part + 3, ',');
            if (!comma)
                fail("--idle: eq=A,B");
            *comma = 0;
            idle.compare = 1;
            idle.word_a = address16(part + 3);
            idle.word_b = address16(comma + 1);
        } else
            fail("--idle: unknown condition %s", part);
    }
    if (!a2vm_add_idle(m, &idle))
        fail("too many --idle");
}

static a2vm_prodos *load_prodos(const char *path, const char *volume,
                                const char *launched)
{
    a2vm_prodos *p = prodos_new(volume, launched);
    char line[2048], error[256];
    FILE *file = fopen(path, "r");
    if (!p || !file)
        fail("cannot read %s", path);
    unsigned number_of_line = 0;
    while (fgets(line, sizeof line, file)) {
        number_of_line++;
        char name[64], type[16], aux[16], file_path[1800];
        if (line[0] == '#' || line[0] == '\n')
            continue;
        if (sscanf(line, "%63s %15s %15s %1799[^\n]", name, type, aux,
                   file_path) != 4)
            fail("%s:%u: NAME TYPE AUX PATH", path, number_of_line);
        size_t length;
        uint8_t *data = read_file(file_path, &length);
        uint64_t t = number(type, 16), a = number(aux, 16);
        if (t > 0xff || a > 0xffff)
            fail("%s:%u: type or aux out of range", path, number_of_line);
        if (!prodos_add(p, name, (uint8_t)t, (uint16_t)a, data, length, error,
                        sizeof error))
            fail("%s:%u: %s", path, number_of_line, error);
        free(data);
    }
    fclose(file);
    return p;
}

/* ---- events ---- */

static unsigned read_events(const char *path, event *events)
{
    char line[512];
    FILE *file = fopen(path, "r");
    if (!file)
        fail("cannot read %s", path);
    unsigned count = 0, number_of_line = 0;
    while (fgets(line, sizeof line, file)) {
        number_of_line++;
        char *words[8];
        unsigned n = 0;
        char *hash = strchr(line, '#');
        if (hash)
            *hash = 0;
        for (char *w = strtok(line, " \t\r\n"); w && n < 8;
             w = strtok(NULL, " \t\r\n"))
            words[n++] = w;
        if (!n)
            continue;
        if (count == MAX_EVENTS)
            fail("%s: too many events", path);
        event *e = &events[count];
        memset(e, 0, sizeof *e);
        e->line = number_of_line;
        unsigned w = 0;
        if (!strcmp(words[0], "start")) {
            e->when = WHEN_START;
            w = 1;
        } else if (n >= 2 && !strcmp(words[0], "boundary")) {
            e->when = WHEN_BOUNDARY;
            e->value = number(words[1], 0);
            w = 2;
        } else if (n >= 2 && !strcmp(words[0], "cycle")) {
            e->when = WHEN_CYCLE;
            e->value = number(words[1], 0);
            w = 2;
        } else if (n >= 2 && !strcmp(words[0], "pc")) {
            char *colon = strchr(words[1], ':');
            e->main_only = colon && !strcmp(colon, ":main");
            if (colon)
                *colon = 0;
            e->when = WHEN_PC;
            e->value = address16(words[1]);
            w = 2;
        } else
            fail("%s:%u: an event starts with start, boundary N, cycle N or "
                 "pc ADDR", path, number_of_line);
        if (w >= n)
            fail("%s:%u: no action", path, number_of_line);
        const char *verb = words[w];
        unsigned args = n - w - 1;
        char **arg = words + w + 1;
        if (!strcmp(verb, "key") || !strcmp(verb, "hold")) {
            if (args != 1)
                fail("%s:%u: %s K", path, number_of_line, verb);
            e->action = verb[0] == 'k' ? ACT_KEY : ACT_HOLD;
            e->a = strlen(arg[0]) == 1 ? (unsigned char)arg[0][0]
                                       : (int64_t)number(arg[0], 0);
        } else if (!strcmp(verb, "release"))
            e->action = ACT_RELEASE;
        else if (!strcmp(verb, "mouse") || !strcmp(verb, "mouse-to") ||
                 !strcmp(verb, "buttons")) {
            if (args != 2)
                fail("%s:%u: %s takes two numbers", path, number_of_line,
                     verb);
            e->action = !strcmp(verb, "mouse") ? ACT_MOUSE
                        : !strcmp(verb, "mouse-to") ? ACT_MOUSE_TO
                                                    : ACT_BUTTONS;
            e->a = signed_number(arg[0]);
            e->b = signed_number(arg[1]);
        } else if (!strcmp(verb, "oa") || !strcmp(verb, "ca")) {
            if (args != 1)
                fail("%s:%u: %s 0|1", path, number_of_line, verb);
            e->action = verb[0] == 'o' ? ACT_OA : ACT_CA;
            e->a = strcmp(arg[0], "0") != 0;
        } else if (!strcmp(verb, "snapshot") || !strcmp(verb, "shot")) {
            if (args != 1 || strlen(arg[0]) >= sizeof e->name ||
                strchr(arg[0], '/'))
                fail("%s:%u: %s NAME", path, number_of_line, verb);
            e->action = verb[1] == 'n' ? ACT_SNAPSHOT : ACT_SHOT;
            snprintf(e->name, sizeof e->name, "%s", arg[0]);
        } else if (!strcmp(verb, "stop"))
            e->action = ACT_STOP;
        else
            fail("%s:%u: unknown action %s", path, number_of_line, verb);
        count++;
    }
    fclose(file);
    return count;
}

/* ---- the state ---- */

static void json_list8(FILE *out, const uint8_t *values, size_t count)
{
    fputc('[', out);
    for (size_t i = 0; i < count; i++)
        fprintf(out, "%s%u", i ? ", " : "", values[i]);
    fputc(']', out);
}

static void write_state_body(FILE *out, a2vm *m)
{
    static const char *cores[] = { "py65", "w65c02s" };
    fprintf(out, "  \"core\": \"%s\",\n", cores[m->core]);
    fprintf(out, "  \"cycles\": %" PRIu64 ",\n", a2vm_now(m));
    fprintf(out, "  \"pc\": %u, \"a\": %u, \"x\": %u, \"y\": %u, "
            "\"sp\": %u, \"p\": %u, \"waiting\": %u,\n", a2vm_pc(m),
            a2vm_register(m, 'a'), a2vm_register(m, 'x'),
            a2vm_register(m, 'y'), a2vm_register(m, 's'),
            a2vm_register(m, 'p'),
            m->core == A2VM_CORE_PY65 ? m->r.waiting
                                      : m->cpu.state == CPU65C02_WAITING);
    fprintf(out, "  \"next_vbl\": %" PRIu64 ", \"idle_cycles\": %" PRIu64
            ", \"irqs\": %" PRIu64 ", \"io_accesses\": %" PRIu64
            ", \"video_writes\": %" PRIu64 ", \"shr_writes\": %" PRIu64
            ", \"speaker_toggles\": %" PRIu64 ",\n", m->next_vbl,
            m->idle_cycles, m->irqs, m->io_accesses, m->video_writes,
            m->shr_writes, m->speaker_toggles);
    fputs("  \"switches\": {", out);
    for (int i = 0; i < SW_COUNT; i++)
        fprintf(out, "\"%s\": %u, ", a2vm_switch_names[i], m->sw[i]);
    fprintf(out, "\"lc_read\": %u, \"lc_write\": %u, \"lc_prewrite\": %u, "
            "\"lc_bank2\": %u, \"bank\": %u, \"newvideo\": %u},\n",
            m->lc_read, m->lc_write, m->lc_prewrite, m->lc_bank2, m->bank,
            m->newvideo);
    fprintf(out, "  \"keyboard\": {\"latch\": %u, \"held\": %u, \"queue\": [",
            m->key_latch, m->key_held);
    for (unsigned i = 0; i < m->key_count; i++)
        fprintf(out, "%s[%" PRIu64 ", %u]", i ? ", " : "", m->keys[i].when,
                m->keys[i].key);
    fputs("]},\n  \"buttons\": ", out);
    json_list8(out, m->buttons, 3);
    fprintf(out, ", \"paddles\": [%" PRId64 ", %" PRId64 ", %" PRId64 ", %"
            PRId64 "], \"paddle_trigger\": %" PRId64 ",\n", m->paddles[0],
            m->paddles[1], m->paddles[2], m->paddles[3], m->paddle_trigger);
    if (m->mli_hi_pending)
        fprintf(out, "  \"mli_hi\": [%u, %u],\n", m->mli_hi_address,
                m->mli_hi_value);
    else
        fputs("  \"mli_hi\": null,\n", out);

    const a2vm_mouse *c = &m->mouse;
    if (m->mouse_on)
        fprintf(out, "  \"mouse\": {\"x\": %d, \"y\": %d, \"buttons\": %u, "
                "\"prev_buttons\": %u, \"moved\": %u, \"move_irq\": %u, "
                "\"button_pending\": %u, \"vbl_pending\": %u, \"irq\": %u, "
                "\"mode\": %u, \"clamp_axis\": %u, \"clamp\": [[%d, %d], "
                "[%d, %d]], \"seq\": %u, \"connected\": %u, \"ps_x\": %d, "
                "\"ps_y\": %d, \"ps_buttons\": %u, \"log_len\": %" PRIu64
                "},\n", c->x, c->y, c->buttons, c->prev_buttons, c->moved,
                c->move_irq, c->button_pending, c->vbl_pending, c->irq,
                c->mode, c->clamp_axis, c->clamp[0][0], c->clamp[0][1],
                c->clamp[1][0], c->clamp[1][1], c->seq, c->connected,
                c->ps_x, c->ps_y, c->ps_buttons,
                c->log_reads + c->log_writes);
    else
        fputs("  \"mouse\": null,\n", out);

    const a2vm_phasor *f = &m->phasor;
    fprintf(out, "  \"phasor\": {\"t1_start\": [%" PRId64 ", %" PRId64
            "], \"mode\": %u, \"via\": [[%u, %u, %u, %u], [%u, %u, %u, %u]], "
            "\"ay\": [", f->t1_start[0], f->t1_start[1], f->mode,
            f->via[0].orb, f->via[0].ora, f->via[0].ddrb, f->via[0].ddra,
            f->via[1].orb, f->via[1].ora, f->via[1].ddrb, f->via[1].ddra);
    for (int i = 0; i < 4; i++) {
        fputs(i ? ", " : "", out);
        json_list8(out, f->ay[i], 16);
    }
    fputs("], \"latched\": ", out);
    json_list8(out, f->latched, 4);
    fprintf(out, ", \"selected\": [[%u, %u], [%u, %u]], \"ssi_dur\": %u, "
            "\"ssi_rate\": %u, ", f->selected[0][0], f->selected[0][1],
            f->selected[1][0], f->selected[1][1], f->ssi_dur, f->ssi_rate);
    if (f->ssi_running)
        fprintf(out, "\"ssi_started\": %" PRId64 ", ", f->ssi_started);
    else
        fputs("\"ssi_started\": null, ", out);
    fprintf(out, "\"ssi_phonemes\": %" PRIu64 ", \"log_len\": %" PRIu64
            "},\n", f->ssi_phonemes, f->ay_writes);

    if (m->amem_on) {
        const a2vm_amem *a = &m->amem;
        fprintf(out, "  \"amem\": {\"selected\": %u, \"ready\": %u, "
                "\"input_len\": %zu, \"input_crc\": %" PRIu32
                ", \"output\": ", a->selected, a->ready, a->input_length,
                a2vm_crc32(0, a->input, a->input_length));
        json_list8(out, a->output, a->output_length);
        fprintf(out, ", \"requests\": %" PRIu64 ", \"completed\": %" PRIu64
                "},\n", a->requests, a->completed);
    } else
        fputs("  \"amem\": null,\n", out);

    const a2vm_prodos *p = m->prodos;
    if (p) {
        fprintf(out, "  \"prodos\": {\"quit\": %d, \"calls\": %" PRIu64
                ", \"calls_crc\": %" PRIu32 ", \"prefix\": \"%s\", "
                "\"open\": {", p->quit, p->calls, p->calls_crc, p->prefix);
        int first = 1;
        for (unsigned ref = 1; ref <= PRODOS_MAX_OPEN; ref++) {
            const prodos_open *o = &p->open[ref];
            if (!o->used)
                continue;
            fprintf(out, "%s\"%u\": [", first ? "" : ", ", ref);
            if (o->file < 0)
                fputs("null", out);
            else
                fprintf(out, "\"%s\"", p->files[o->file].name);
            fprintf(out, ", %" PRIu64 ", %d]", o->pos, o->dirty);
            first = 0;
        }
        fputs("}, \"files\": [", out);
        first = 1;
        for (size_t i = 0; i < p->file_count; i++) {
            const prodos_file *f2 = &p->files[i];
            if (!f2->live)
                continue;
            fprintf(out, "%s[\"%s\", %u, %u, %zu, %" PRIu32 "]",
                    first ? "" : ", ", f2->name, f2->type, f2->aux,
                    f2->buffer.length,
                    a2vm_crc32(0, f2->buffer.data, f2->buffer.length));
            first = 0;
        }
        fputs("]}\n", out);
    } else
        fputs("  \"prodos\": null\n", out);
}

static void write_json(const char *path, a2vm *m, const char *extra)
{
    FILE *out = path ? fopen(path, "w") : stdout;
    if (!out)
        fail("cannot write %s", path);
    fputs("{\n", out);
    if (extra)
        fputs(extra, out);
    write_state_body(out, m);
    fputs("}\n", out);
    if (path && fclose(out))
        fail("cannot write %s", path);
}

static void write_ram(a2vm *m, const char *path)
{
    FILE *file = fopen(path, "wb");
    if (!file || fwrite(m->main, 1, sizeof m->main, file) != sizeof m->main ||
        fwrite(m->lc, 1, sizeof m->lc, file) != sizeof m->lc ||
        fwrite(m->lc1, 1, sizeof m->lc1, file) != sizeof m->lc1 ||
        fwrite(m->aux_banks, A2VM_BANK_SIZE, A2VM_MAX_BANKS, file) !=
            A2VM_MAX_BANKS || fclose(file))
        fail("cannot write %s", path);
}

static void snapshot(a2vm *m, const char *directory, const char *name,
                     const char *extra)
{
    char path[1200];
    snprintf(path, sizeof path, "%s/%s.json", directory, name);
    write_json(path, m, extra);
    snprintf(path, sizeof path, "%s/%s.ram", directory, name);
    write_ram(m, path);
}

/* A2VMSHR1, NEWVIDEO, aux bank 0 $2000-$9FFF, main $2000-$9FFF: what
   tools/a2vm/shot.py needs for standard SHR and PAL256. */
static void shot(a2vm *m, const char *directory, const char *name)
{
    static uint8_t data[9 + 2 * SHOT_BYTES];
    char path[1200];
    memcpy(data, "A2VMSHR1", 8);
    data[8] = m->newvideo;
    memcpy(data + 9, m->aux_banks + 0x2000, SHOT_BYTES);
    memcpy(data + 9 + SHOT_BYTES, m->main + 0x2000, SHOT_BYTES);
    snprintf(path, sizeof path, "%s/%s.shr", directory, name);
    write_file(path, data, sizeof data);
}

/* ---- bus scripts ---- */

/* A page table entry: M (main), A<bank> (aux), L (main LC, $C000-based),
   1 (main LC bank 1, $D000-based) or R (ROM, $C000-based), then ":" and
   the page of that storage; "-" for the slow path. */
static void describe(const a2vm *m, const uint8_t *p)
{
    if (!p)
        printf(" -");
    else if (p >= m->main && p < m->main + sizeof m->main)
        printf(" M:%02X", (unsigned)((p - m->main) >> 8));
    else if (p >= m->lc && p < m->lc + sizeof m->lc)
        printf(" L:%02X", (unsigned)((p - m->lc) >> 8) + 0xc0);
    else if (p >= m->lc1 && p < m->lc1 + sizeof m->lc1)
        printf(" 1:%02X", (unsigned)((p - m->lc1) >> 8) + 0xd0);
    else if (p >= m->rom && p < m->rom + sizeof m->rom)
        printf(" R:%02X", (unsigned)((p - m->rom) >> 8) + 0xc0);
    else {
        size_t offset = (size_t)(p - m->aux_banks);
        printf(" A%u:%02X", (unsigned)(offset / A2VM_BANK_SIZE),
               (unsigned)((offset % A2VM_BANK_SIZE) >> 8));
    }
}

static void bus_script(a2vm *m, const char *path)
{
    char line[512];
    FILE *file = fopen(path, "r");
    if (!file)
        fail("cannot read %s", path);
    unsigned number_of_line = 0;
    while (fgets(line, sizeof line, file)) {
        number_of_line++;
        char *words[8];
        unsigned n = 0;
        char *hash = strchr(line, '#');
        if (hash)
            *hash = 0;
        for (char *w = strtok(line, " \t\r\n"); w && n < 8;
             w = strtok(NULL, " \t\r\n"))
            words[n++] = w;
        if (!n)
            continue;
        const char *verb = words[0];
        if (!strcmp(verb, "read") && n == 2) {
            uint16_t address = address16(words[1]);
            printf("read %04X %02X\n", address, a2vm_read(m, address));
        } else if (!strcmp(verb, "write") && n == 3) {
            uint16_t address = address16(words[1]);
            uint64_t value = number(words[2], 16);
            if (value > 0xff)
                fail("%s:%u: a byte", path, number_of_line);
            a2vm_write(m, address, (uint8_t)value);
        } else if ((!strcmp(verb, "peek") && n == 4) ||
                   (!strcmp(verb, "poke") && n == 5)) {
            static const char *kinds[] = { "main", "aux", "lc", "lc1" };
            int kind = -1;
            for (int k = 0; k < 4; k++)
                if (!strcmp(words[1], kinds[k]))
                    kind = k;
            uint64_t bank = number(words[2], 10);
            uint16_t address = address16(words[3]);
            uint8_t *at = kind < 0 ? NULL
                                   : a2vm_storage(m, kind, (unsigned)bank,
                                                  address);
            if (!at)
                fail("%s:%u: no such storage", path, number_of_line);
            if (verb[1] == 'e')
                printf("peek %s %u %04X %02X\n", words[1], (unsigned)bank,
                       address, *at);
            else
                *at = (uint8_t)number(words[4], 16);
        } else if (!strcmp(verb, "clock") && n == 2) {
            *m->clock = number(words[1], 0);
        } else if (!strcmp(verb, "state") && n == 1) {
            write_json(NULL, m, NULL);
        } else if (!strcmp(verb, "map") && n == 1) {
            /* the page tables, a page a word: what a read and a write of
               the page reach */
            printf("map");
            for (unsigned page = 0; page < 256; page++)
                describe(m, m->rpage[page]);
            printf("\nwmap");
            for (unsigned page = 0; page < 256; page++)
                describe(m, m->wpage[page]);
            printf("\n");
        } else if (!strcmp(verb, "lc") && n == 1) {
            printf("lc %u %u %u %u\n", m->lc_read, m->lc_write,
                   m->lc_prewrite, m->lc_bank2);
        } else if (!strcmp(verb, "cost") && n == 1) {
            if (!m->cost)
                fail("%s:%u: cost needs --cost", path, number_of_line);
            const a2vm_cost *c = m->cost;
            printf("cost t=%" PRIu64, c->t);
#define COST_FIELD(name) printf(" " #name "=%" PRIu64, c->c.name)
            COST_FIELD(accesses); COST_FIELD(read_hits); COST_FIELD(misses);
            COST_FIELD(invalidations); COST_FIELD(bus_cycles);
            COST_FIELD(posted); COST_FIELD(video_wait);
            COST_FIELD(rw_hits); COST_FIELD(rw_misses); COST_FIELD(rw_dirty);
            COST_FIELD(flushes); COST_FIELD(quiet);
            COST_FIELD(reconcile_cycles); COST_FIELD(lazy_flushes);
            COST_FIELD(amem_requests); COST_FIELD(amem_bytes);
            COST_FIELD(amem_clocks);
#undef COST_FIELD
            printf("\n");
        } else if (!strcmp(verb, "counts") && n == 1) {
            printf("counts %" PRIu64 " %" PRIu64 " %" PRIu64 " %" PRIu64
                   "\n", m->io_accesses, m->video_writes, m->shr_writes,
                   a2vm_now(m));
        } else if (!strcmp(verb, "run") && n == 2) {
            uint64_t steps = number(words[1], 0);
            for (uint64_t i = 0; i < steps && !m->halt[0]; i++)
                a2vm_step(m);
        } else if (!strcmp(verb, "reg") && n == 2) {
            set_register(m, words[1]);
        } else if (!strcmp(verb, "press") && n == 3) {
            a2vm_press(m, (uint8_t)number(words[1], 16), number(words[2], 0));
        } else if (!strcmp(verb, "hold") && n == 2) {
            a2vm_hold(m, (uint8_t)number(words[1], 16));
        } else if (!strcmp(verb, "release") && n == 1) {
            a2vm_release(m);
        } else if (!strcmp(verb, "mouse") && n == 3) {
            a2vm_mouse_delta(m, signed_number(words[1]),
                             signed_number(words[2]));
        } else if (!strcmp(verb, "mouse-to") && n == 3) {
            a2vm_mouse_move(m, signed_number(words[1]),
                            signed_number(words[2]));
        } else if (!strcmp(verb, "button") && n == 3) {
            uint64_t which = number(words[1], 0);
            if (which > 2)
                fail("%s:%u: button 0-2", path, number_of_line);
            m->buttons[which] = (uint8_t)number(words[2], 16);
        } else if (!strcmp(verb, "dump") && n == 2) {
            write_ram(m, words[1]);
        } else if (!strcmp(verb, "buttons") && n == 3) {
            a2vm_mouse_buttons(m, strcmp(words[1], "0") != 0,
                               strcmp(words[2], "0") != 0);
        } else
            fail("%s:%u: unknown or malformed command %s", path,
                 number_of_line, verb);
        if (m->halt[0]) {
            printf("halt %s\n", m->halt);
            m->halt[0] = 0;
        }
    }
    fclose(file);
}

/* ---- running ---- */

static void act(a2vm *m, const options *o, event *e, int *stop)
{
    switch (e->action) {
    case ACT_KEY: a2vm_press(m, (uint8_t)e->a, a2vm_now(m)); break;
    case ACT_HOLD: a2vm_hold(m, (uint8_t)e->a); break;
    case ACT_RELEASE: a2vm_release(m); break;
    case ACT_MOUSE: a2vm_mouse_delta(m, e->a, e->b); break;
    case ACT_MOUSE_TO: a2vm_mouse_move(m, e->a, e->b); break;
    case ACT_BUTTONS: a2vm_mouse_buttons(m, e->a != 0, e->b != 0); break;
    case ACT_OA: m->buttons[0] = e->a ? 0x80 : 0; break;
    case ACT_CA: m->buttons[1] = e->a ? 0x80 : 0; break;
    case ACT_SNAPSHOT:
        if (!o->snapshot_dir)
            fail("the snapshot action needs --snapshot-dir");
        snapshot(m, o->snapshot_dir, e->name, NULL);
        break;
    case ACT_SHOT:
        if (!o->snapshot_dir)
            fail("the shot action needs --snapshot-dir");
        shot(m, o->snapshot_dir, e->name);
        break;
    case ACT_STOP: *stop = 1; break;
    }
    e->done = 1;
}

int main(int argc, char **argv)
{
    options o;
    char error[256];
    parse(argc, argv, &o);
    a2vm *m = a2vm_new(&o.config, error, sizeof error);
    if (!m)
        fail("%s", error);
    a2vm_amem_options(m, o.amem_supported, o.amem_available, 1);
    if (o.prodos)
        a2vm_attach_prodos(m, load_prodos(o.prodos, o.volume, o.launched));
    if (o.image)
        load_image(m, o.image);
    for (unsigned i = 0; i < o.load_count; i++)
        load_binary(m, 0, 0, o.loads[i]);
    for (unsigned i = 0; i < o.aux_load_count; i++)
        load_aux(m, o.aux_loads[i]);
    for (unsigned i = 0; i < o.switch_count; i++)
        set_switch(m, o.switches[i]);
    for (unsigned i = 0; i < o.reg_count; i++)
        set_register(m, o.regs[i]);
    for (unsigned i = 0; i < o.idle_count; i++)
        add_idle(m, o.idles[i]);
    a2vm_remap(m);
    if (o.cost) {
        if (o.cost_timed && o.bus_script)
            fail("--cost-timed runs the CPU, not a bus script");
        a2vm_cost_params params;
        if (!a2vm_cost_load(&params, o.cost, error, sizeof error))
            fail("%s", error);
        a2vm_cost *cost = a2vm_cost_new(&params);
        if (!cost)
            fail("out of memory");
        cost->phase_addr = o.cost_phase;
        if (o.cost_report) {
            cost->report = fopen(o.cost_report, "w");
            if (!cost->report)
                fail("cannot write %s", o.cost_report);
        }
        a2vm_attach_cost(m, cost, o.cost_timed);
    }

    if (o.bus_script) {
        bus_script(m, o.bus_script);
        a2vm_free(m);
        return 0;
    }

    static event events[MAX_EVENTS];
    unsigned event_count = o.input ? read_events(o.input, events) : 0;
    static uint8_t watch[8192];
    if (o.has_boundary)
        watch[o.boundary >> 3] |= (uint8_t)(1u << (o.boundary & 7));
    for (unsigned i = 0; i < o.stop_count; i++)
        watch[o.stops[i].pc >> 3] |= (uint8_t)(1u << (o.stops[i].pc & 7));
    uint64_t next_cycle_event = UINT64_MAX;
    for (unsigned i = 0; i < event_count; i++) {
        if (events[i].when == WHEN_PC)
            watch[events[i].value >> 3] |=
                (uint8_t)(1u << (events[i].value & 7));
        if (events[i].when == WHEN_CYCLE && events[i].value < next_cycle_event)
            next_cycle_event = events[i].value;
    }

    int stop = 0;
    const char *reason = NULL;
    uint64_t boundaries = 0, start_cycles = a2vm_now(m);
    uint64_t start_instructions = m->instructions;
    for (unsigned i = 0; i < event_count && !stop; i++)
        if (events[i].when == WHEN_START)
            act(m, &o, &events[i], &stop);
    if (stop)
        reason = "stop";
    clock_t started = clock();

    while (!reason) {
        if (a2vm_now(m) >= o.cycles) {
            reason = "cycles";
            break;
        }
        a2vm_step(m);
        if (m->halt[0]) {
            reason = "halt";
            break;
        }
        uint16_t pc = a2vm_pc(m);
        if (watch[pc >> 3] & (1u << (pc & 7))) {
            int main_zp = !m->sw[SW_ALTZP];
            if (o.has_boundary && pc == o.boundary && main_zp) {
                boundaries++;
                if (m->cost)
                    a2vm_cost_boundary(m, boundaries);
                if (o.snapshot_boundaries) {
                    char name[32], extra[128];
                    snprintf(name, sizeof name, "boundary-%04" PRIu64,
                             boundaries);
                    snprintf(extra, sizeof extra, "  \"boundary\": %" PRIu64
                             ",\n", boundaries);
                    snapshot(m, o.snapshot_dir, name, extra);
                }
                for (unsigned i = 0; i < event_count; i++)
                    if (!events[i].done && events[i].when == WHEN_BOUNDARY &&
                        events[i].value == boundaries)
                        act(m, &o, &events[i], &stop);
            }
            for (unsigned i = 0; i < event_count; i++)
                if (!events[i].done && events[i].when == WHEN_PC &&
                    events[i].value == pc && (!events[i].main_only || main_zp))
                    act(m, &o, &events[i], &stop);
            for (unsigned i = 0; i < o.stop_count; i++)
                if (o.stops[i].pc == pc && (!o.stops[i].main_only || main_zp))
                    reason = "stop-pc";
        }
        if (a2vm_now(m) >= next_cycle_event) {
            next_cycle_event = UINT64_MAX;
            for (unsigned i = 0; i < event_count; i++) {
                event *e = &events[i];
                if (e->done || e->when != WHEN_CYCLE)
                    continue;
                if (a2vm_now(m) >= e->value)
                    act(m, &o, e, &stop);
                else if (e->value < next_cycle_event)
                    next_cycle_event = e->value;
            }
        }
        if (stop && !reason)
            reason = "stop";
        if (!reason && m->prodos && m->prodos->quit)
            reason = "quit";
        if (!reason && boundaries >= o.boundaries)
            reason = "boundaries";
    }
    double seconds = (double)(clock() - started) / CLOCKS_PER_SEC;

    char extra[1024];
    snprintf(extra, sizeof extra,
             "  \"end\": \"%s\",\n  \"halt\": \"%s\",\n"
             "  \"boundaries\": %" PRIu64 ",\n"
             "  \"run_cycles\": %" PRIu64 ",\n"
             "  \"instructions\": %" PRIu64 ",\n"
             "  \"host_seconds\": %.6f,\n", reason, m->halt,
             boundaries, a2vm_now(m) - start_cycles,
             m->instructions - start_instructions, seconds);
    if (o.final_snapshot)
        snapshot(m, o.snapshot_dir, "final", extra);
    if (m->cost && m->cost->report) {
        fputs("{\"final\": true,\n", m->cost->report);
        a2vm_cost_final(m, m->cost->report);
        fprintf(m->cost->report, "  \"host_seconds\": %.6f}\n", seconds);
        fclose(m->cost->report);
        m->cost->report = NULL;
    }
    write_json(o.state, m, extra);
    int status = !strcmp(reason, "halt") ? 1 : 0;
    a2vm_free(m);
    return status;
}
