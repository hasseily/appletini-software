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
 *   --via-ora-nh        a write to a Phasor VIA's register 15 (ORA without
 *                       handshake) sets ORA, as the card's 6522 does;
 *                       a2sim.py ignores it (the default)
 *   --via-timers        each Phasor VIA's timer 1 as the card's 6522 runs
 *                       it: latches, one-shot and free-run, IFR, IER and
 *                       its interrupt; a2sim.py has a free-running counter
 *                       only (the default)
 *   --phasor-mb-only    the Phasor locked to Mockingboard mode (the
 *                       card's audio_control bit 26): $C0C0-$C0CF mode
 *                       switches are ignored
 *   --zpbank            arm the zero-page bank pair of the firmware design
 *                       (README.md, "The zero-page bank pair"; needs
 *                       --core w65c02s); the cost profiles f121zp and
 *                       fastzp arm it too
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
 *                       (the words at A and B equal: main, or the main
 *                       language card with lc. before the address),
 *                       :byte=A,V (the main byte at A holds V, at most 4
 *                       a loop); hex addresses and values
 *
 * Run
 *   --boundary ADDR     a frame boundary: the CPU at ADDR after a step,
 *                       with ALTZP off
 *   --boundaries N      stop at the Nth boundary
 *   --cycles N|none     stop once the clock reaches N. Without it a run
 *                       stops at 20,000,000,000 cycles (DEFAULT_CYCLES,
 *                       about two minutes on the host) with end
 *                       "cycle-cap" and exit status 3; "none" runs with no
 *                       limit
 *   --stop-pc ADDR      stop at ADDR (hex; ALTZP off with a :main suffix)
 *   --stop-word ADDR:N  stop once the 32-bit little-endian main word at
 *                       ADDR (hex), after a step where it was below N, is
 *                       at least N (end "stop-word"): a game's tic
 *                       counter, say, whatever the memory held before
 *                       the game set it
 *   --input FILE        events, one a line: WHEN ACTION (README.md)
 *   --snapshot-dir DIR  where snapshots, shots and the state go
 *   --snapshot-boundaries
 *                       a snapshot at every boundary
 *   --final-snapshot    a snapshot when the run ends
 *   --snapshot-ranges RANGES
 *                       snapshots of these ranges only (README.md,
 *                       "Ranges"): NAME.img, an A2VMIMG1 image, in place
 *                       of the whole RAM's NAME.ram
 *   --snapshot-stream FILE
 *                       every snapshot (of --snapshot-ranges, which it
 *                       needs) into one stream instead of files (README.md,
 *                       "The snapshot stream"), "-" for stdout
 *   --snapshot-limit BYTES
 *                       the stream's bound (default 1 GiB): a snapshot
 *                       that would pass it ends the stream and the run
 *                       with exit status 2
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
 *   --cost-pcmap FILE   a PC map of phases (cost.h, a2vm_cost_pcmap): while
 *                       the phase written is --cost-pcmap-when's (default
 *                       18), each instruction's phase is its PC's in the
 *                       map (milestone 10's timing report by subsystem)
 *   --cost-pcmap-when N the phase written under which the map holds
 *
 * Logs
 *   --ay-log FILE       a line for each AY register write that reaches a
 *                       chip, each chip reset, each interrupt taken and
 *                       each RTI, with the machine's time (README.md,
 *                       "The AY log")
 *   --write-log RANGES  a line for each CPU write that reaches the ranges
 *                       (README.md, "The write log"), to the file of
 *                       --write-log-file (default: writes.log in the
 *                       --snapshot-dir)
 *   --write-log-file FILE
 *   --write-log-limit N at most N lines (default 10,000,000, about
 *                       500 MB); the write that would be line N + 1 halts
 *                       the run
 *   --pclog FILE        a line for each instruction run at the PCs of
 *                       --pclog-pcs (README.md, "The PC log"): the clock,
 *                       the registers and the main bytes of --pclog-bytes
 *   --pclog-pcs LIST    hex PCs, commas (at most 64)
 *   --pclog-bytes LIST  hex main addresses, or lc.HEX for the main
 *                       language card's, commas (at most 16)
 *   --pclog-from N      log from the clock N on (default 0)
 *   --pclog-limit N     at most N lines (default 1,000,000, about 50 MB);
 *                       the visit that would be line N + 1 halts the run
 *   --lowest-s          the lowest S the run reaches, in the state
 *   --lowest-s-in RANGES
 *                       also the lowest S reached by the instructions whose
 *                       PC is in each range (hex LO-HI, commas, at most
 *                       16; README.md, "The lowest S")
 *
 *   --every-limit N     at most N snapshots or shots of each pc ADDR@*
 *                       event (default 100); the visit after them ends the
 *                       run with an error (exit status 2)
 *
 * Checks
 *   --irq-bounds RANGES the only addresses an interrupt handler may read
 *                       or write, from its first instruction to its RTI,
 *                       as hex ranges LO-HI separated by commas (at most
 *                       8); any other access halts the run (README.md,
 *                       "Interrupt bounds")
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

/* The cycles a run may make without --cycles (--cycles none: no limit),
   and the default bounds of the write log and of @* events. */
#define DEFAULT_CYCLES 20000000000ull
#define WRITE_LOG_LINES 10000000ull
#define EVERY_LIMIT 100ull
#define PCLOG_LINES 1000000ull

enum {
    MAX_LIST = 64, MAX_EVENTS = 4096,
    SHOT_BYTES = 0x8000,
    MAX_S_RANGES = 16,
    MAX_PCLOG_PCS = 64, MAX_PCLOG_BYTES = 16
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
    uint64_t nth;               /* WHEN_PC: fire at this visit (1 first) */
    int every;                  /* WHEN_PC: fire at every visit */
    uint64_t visits;            /* WHEN_PC: visits so far */
    action_kind action;
    int64_t a, b;
    char name[64];
    int done;
    unsigned line;
} event;

/* --lowest-s: the lowest S, and where it was reached */
typedef struct {
    uint16_t low, high;         /* a PC range; the whole run: 0-FFFF */
    int seen;
    uint8_t s, last;            /* last: S after the last step (lows[0]) */
    uint16_t pc;
    uint64_t cycles, steps;
} lowest_s;

typedef struct {
    uint16_t pc;
    int main_only;
} stop_pc;

typedef struct {
    a2vm_config config;
    const char *image, *prodos, *input, *snapshot_dir, *state, *bus_script;
    const char *volume, *launched;
    const char *cost, *cost_report, *ay_log, *irq_bounds;
    const char *write_log, *write_log_file, *snapshot_ranges, *lowest_s_in;
    const char *snapshot_stream;
    const char *pclog, *pclog_pcs, *pclog_bytes;
    uint64_t pclog_from, pclog_limit;
    uint64_t snapshot_limit;
    int snapshot_limit_given;
    int zpbank, lowest_s;
    int cost_timed, cost_phase;
    const char *cost_pcmap;
    unsigned cost_pcmap_when;
    const char *loads[MAX_LIST], *aux_loads[MAX_LIST], *regs[MAX_LIST],
        *switches[MAX_LIST], *idles[MAX_LIST];
    unsigned load_count, aux_load_count, reg_count, switch_count, idle_count;
    int amem_supported, amem_available;
    uint16_t boundary;
    int has_boundary;
    uint64_t boundaries, cycles;
    int cycles_given;           /* --cycles, a number or none */
    uint64_t write_log_limit, every_limit;
    stop_pc stops[MAX_LIST];
    unsigned stop_count;
    int stop_word;              /* --stop-word given */
    uint16_t stop_word_at;
    uint64_t stop_word_value;
    int snapshot_boundaries, final_snapshot;
    int via_ora_nh, via_timers, phasor_mb_only;
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
    o->write_log_limit = WRITE_LOG_LINES;
    o->pclog_limit = PCLOG_LINES;
    o->every_limit = EVERY_LIMIT;
    o->volume = "DOOM";
    o->cost_phase = -1;
    o->cost_pcmap_when = 18;
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
        if (!strcmp(arg, "--via-ora-nh")) {
            o->via_ora_nh = 1;
            continue;
        }
        if (!strcmp(arg, "--via-timers")) {
            o->via_timers = 1;
            continue;
        }
        if (!strcmp(arg, "--phasor-mb-only")) {
            o->phasor_mb_only = 1;
            continue;
        }
        if (!strcmp(arg, "--zpbank")) {
            o->zpbank = 1;
            continue;
        }
        if (!strcmp(arg, "--lowest-s")) {
            o->lowest_s = 1;
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
        else if (!strcmp(arg, "--cycles")) {
            o->cycles = !strcmp(value, "none") ? UINT64_MAX
                                               : number(value, 0);
            o->cycles_given = 1;
        } else if (!strcmp(arg, "--write-log-limit"))
            o->write_log_limit = number(value, 0);
        else if (!strcmp(arg, "--every-limit"))
            o->every_limit = number(value, 0);
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
        else if (!strcmp(arg, "--cost-pcmap"))
            o->cost_pcmap = value;
        else if (!strcmp(arg, "--cost-pcmap-when"))
            o->cost_pcmap_when = (unsigned)number(value, 0);
        else if (!strcmp(arg, "--ay-log"))
            o->ay_log = value;
        else if (!strcmp(arg, "--irq-bounds"))
            o->irq_bounds = value;
        else if (!strcmp(arg, "--write-log"))
            o->write_log = value;
        else if (!strcmp(arg, "--write-log-file"))
            o->write_log_file = value;
        else if (!strcmp(arg, "--snapshot-ranges"))
            o->snapshot_ranges = value;
        else if (!strcmp(arg, "--snapshot-stream"))
            o->snapshot_stream = value;
        else if (!strcmp(arg, "--snapshot-limit")) {
            o->snapshot_limit = number(value, 0);
            o->snapshot_limit_given = 1;
        }
        else if (!strcmp(arg, "--stop-word")) {
            char text[64];
            snprintf(text, sizeof text, "%s", value);
            char *colon = strchr(text, ':');
            if (!colon)
                fail("--stop-word takes ADDR:N");
            *colon = 0;
            o->stop_word = 1;
            o->stop_word_at = address16(text);
            o->stop_word_value = number(colon + 1, 0);
            if (o->stop_word_at > 0xfffc)
                fail("--stop-word: the word passes $FFFF");
        } else if (!strcmp(arg, "--pclog"))
            o->pclog = value;
        else if (!strcmp(arg, "--pclog-pcs"))
            o->pclog_pcs = value;
        else if (!strcmp(arg, "--pclog-bytes"))
            o->pclog_bytes = value;
        else if (!strcmp(arg, "--pclog-from"))
            o->pclog_from = number(value, 0);
        else if (!strcmp(arg, "--pclog-limit"))
            o->pclog_limit = number(value, 0);
        else if (!strcmp(arg, "--lowest-s-in")) {
            o->lowest_s_in = value;
            o->lowest_s = 1;
        } else
            fail("unknown option %s", arg);
    }
    if (!o->config.rom_path)
        fail("give --rom (the Apple //e enhanced ROM)");
    if ((o->snapshot_boundaries || o->final_snapshot) && !o->snapshot_dir &&
        !o->snapshot_stream)
        fail("snapshots need --snapshot-dir");
    if ((o->cost_timed || o->cost_report || o->cost_phase >= 0 ||
         o->cost_pcmap) && !o->cost)
        fail("the cost options need --cost");
    if (o->cost_pcmap && o->cost_phase < 0)
        fail("--cost-pcmap needs --cost-phase");
    if (o->write_log_file && !o->write_log)
        fail("--write-log-file needs --write-log");
    if (o->write_log && !o->write_log_file && !o->snapshot_dir)
        fail("--write-log needs --write-log-file or --snapshot-dir");
    if (!o->write_log_limit)
        fail("--write-log-limit takes a count from 1");
    if (o->snapshot_stream && !o->snapshot_ranges)
        fail("--snapshot-stream needs --snapshot-ranges");
    if (o->snapshot_limit_given && !o->snapshot_stream)
        fail("--snapshot-limit needs --snapshot-stream");
    if (o->snapshot_limit_given && !o->snapshot_limit)
        fail("--snapshot-limit takes a count of bytes from 1");
    if ((o->pclog_pcs || o->pclog_bytes) && !o->pclog)
        fail("--pclog-pcs and --pclog-bytes need --pclog");
    if (o->pclog && !o->pclog_pcs)
        fail("--pclog needs --pclog-pcs");
    if (!o->pclog_limit)
        fail("--pclog-limit takes a count from 1");
    if (!o->cycles_given)
        o->cycles = DEFAULT_CYCLES;
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

/* An --idle word's address: HEX (main) or lc.HEX (the main language
   card, $C000-$FFFE). */
static uint16_t idle_word(const char *text, uint8_t *store)
{
    *store = 0;
    if (!strncmp(text, "lc.", 3)) {
        *store = 2;
        uint16_t address = address16(text + 3);
        if (address < 0xc000 || address == 0xffff)
            fail("--idle: lc.%s is not in $C000-$FFFE", text + 3);
        return address;
    }
    return address16(text);
}

static void add_idle(a2vm *m, const char *spec)
{
    char text[256];
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
            idle.word_a = idle_word(part + 3, &idle.store_a);
            idle.word_b = idle_word(comma + 1, &idle.store_b);
        } else if (!strncmp(part, "byte=", 5)) {
            char *comma = strchr(part + 5, ',');
            if (!comma)
                fail("--idle: byte=A,V");
            *comma = 0;
            if (idle.byte_count == A2VM_IDLE_BYTES)
                fail("--idle: at most %d byte conditions", A2VM_IDLE_BYTES);
            uint64_t value = number(comma + 1, 16);
            if (value > 0xff)
                fail("--idle: byte=%s,%s: the value is a byte", part + 5,
                     comma + 1);
            idle.byte_addr[idle.byte_count] = address16(part + 5);
            idle.byte_value[idle.byte_count++] = (uint8_t)value;
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
            char *at = strchr(words[1], '@');
            e->nth = 1;
            if (at) {
                *at = 0;
                if (!strcmp(at + 1, "*"))
                    e->every = 1;
                else if ((e->nth = number(at + 1, 10)) == 0)
                    fail("%s:%u: pc ADDR@N counts visits from 1", path,
                         number_of_line);
            }
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

    /* only in runs that ask for them, so every other state is as it was */
    if (m->zpb.armed) {
        const a2vm_zpbank *z = &m->zpb;
        fprintf(out, "  \"zpbank\": {\"address\": %u, \"rd\": %u, \"wr\": %u, "
                "\"enables\": %" PRIu64 ", \"loads\": %" PRIu64 ", "
                "\"reads\": %" PRIu64 ", \"writes\": %" PRIu64 ", "
                "\"firmware\": %" PRIu64 ", \"amem\": %" PRIu64 "},\n",
                z->address, z->rd, z->wr, z->enables, z->loads, z->reads,
                z->writes, z->firmware, z->amem);
    }
    if (m->write_log)
        fprintf(out, "  \"write_logged\": %" PRIu64 ",\n", m->write_logged);
    if (m->via_timers) {
        a2vm_via_timers_update(m);
        fputs("  \"via_timers\": [", out);
        for (unsigned i = 0; i < 2; i++) {
            const a2vm_phasor *f = &m->phasor;
            fprintf(out, "%s{\"latch\": %u, \"acr\": %u, \"ifr\": %u, "
                    "\"ier\": %u, \"armed\": %u, \"load\": %u, "
                    "\"start\": %" PRId64 ", \"flag_bus\": %" PRId64 "}",
                    i ? ", " : "",
                    (unsigned)(f->t1[i].latch_hi << 8 | f->t1[i].latch_lo),
                    f->t1[i].acr, f->t1[i].ifr, f->t1[i].ier, f->t1[i].armed,
                    f->t1[i].load, f->t1_start[i], f->t1[i].flag_bus);
        }
        fputs("],\n", out);
    }

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

/* --snapshot-ranges: an A2VMIMG1 image of the ranges (the records of
   --image: kind, bank, address, length, bytes), which --image loads
   back. */
static a2vm_range snapshot_ranges[A2VM_MAX_RANGES];
static unsigned snapshot_range_count;

static void write_ranges_image(a2vm *m, const char *path)
{
    FILE *file = fopen(path, "wb");
    if (!file || fwrite("A2VMIMG1", 1, 8, file) != 8)
        fail("cannot write %s", path);
    for (unsigned i = 0; i < snapshot_range_count; i++) {
        const a2vm_range *r = &snapshot_ranges[i];
        unsigned first = r->kind == A2VM_RANGE_AUX ? r->bank_low : 0;
        unsigned last = r->kind == A2VM_RANGE_AUX ? r->bank_high : 0;
        for (unsigned bank = first; bank <= last; bank++) {
            uint32_t length = (uint32_t)r->high - r->low + 1;
            uint8_t header[8] = {
                r->kind, (uint8_t)bank, (uint8_t)r->low,
                (uint8_t)(r->low >> 8), (uint8_t)length,
                (uint8_t)(length >> 8), (uint8_t)(length >> 16), 0
            };
            const uint8_t *data = a2vm_storage(m, r->kind, bank, r->low);
            if (fwrite(header, 1, 8, file) != 8 ||
                fwrite(data, 1, length, file) != length)
                fail("cannot write %s", path);
        }
    }
    if (fclose(file))
        fail("cannot write %s", path);
}

/* --snapshot-stream: every snapshot into one stream (milestone 10): a
   JSON line {"format": "a2vm-snapshot-stream 1", "ranges": "..."}; for
   each snapshot a JSON line {"snapshot": N, "name", "cycles", "pc",
   "bytes": L} and its L bytes, an A2VMIMG1 image of the ranges (what
   NAME.img would hold); a last line {"end": REASON, "snapshots": N}. A
   snapshot that would take the stream past its limit is not written: the
   stream ends with {"end": "snapshot-limit", ...} and the run with exit
   status 2. */
static FILE *snap_stream;
static uint64_t snap_stream_limit = 1ull << 30;
static uint64_t snap_stream_bytes, snap_stream_count;

static void stream_end(const char *reason)
{
    if (!snap_stream)
        return;
    fprintf(snap_stream, "{\"end\": \"%s\", \"snapshots\": %" PRIu64 "}\n",
            reason, snap_stream_count);
    if (snap_stream != stdout && fclose(snap_stream))
        fail("cannot write the snapshot stream");
    else if (snap_stream == stdout)
        fflush(stdout);
    snap_stream = NULL;
}

static void stream_snapshot(a2vm *m, const char *name)
{
    uint64_t length = 8;
    for (unsigned i = 0; i < snapshot_range_count; i++) {
        const a2vm_range *r = &snapshot_ranges[i];
        unsigned banks = r->kind == A2VM_RANGE_AUX
                             ? r->bank_high - r->bank_low + 1 : 1;
        length += banks * (8 + ((uint64_t)r->high - r->low + 1));
    }
    char head[512];
    int n = snprintf(head, sizeof head,
                     "{\"snapshot\": %" PRIu64 ", \"name\": \"%s\", "
                     "\"cycles\": %" PRIu64 ", \"pc\": %u, \"bytes\": %"
                     PRIu64 "}\n", snap_stream_count + 1, name, a2vm_now(m),
                     (unsigned)a2vm_pc(m), length);
    if (n < 0 || (size_t)n >= sizeof head)
        fail("a snapshot's name is too long for the stream");
    if (snap_stream_bytes + (uint64_t)n + length > snap_stream_limit) {
        stream_end("snapshot-limit");
        fail("the snapshot %s would take the stream past --snapshot-limit "
             "%" PRIu64 " bytes", name, snap_stream_limit);
    }
    if (fwrite(head, 1, (size_t)n, snap_stream) != (size_t)n ||
        fwrite("A2VMIMG1", 1, 8, snap_stream) != 8)
        fail("cannot write the snapshot stream");
    for (unsigned i = 0; i < snapshot_range_count; i++) {
        const a2vm_range *r = &snapshot_ranges[i];
        unsigned first = r->kind == A2VM_RANGE_AUX ? r->bank_low : 0;
        unsigned last = r->kind == A2VM_RANGE_AUX ? r->bank_high : 0;
        for (unsigned bank = first; bank <= last; bank++) {
            uint32_t size = (uint32_t)r->high - r->low + 1;
            uint8_t header[8] = {
                r->kind, (uint8_t)bank, (uint8_t)r->low,
                (uint8_t)(r->low >> 8), (uint8_t)size,
                (uint8_t)(size >> 8), (uint8_t)(size >> 16), 0
            };
            const uint8_t *data = a2vm_storage(m, r->kind, bank, r->low);
            if (fwrite(header, 1, 8, snap_stream) != 8 ||
                fwrite(data, 1, size, snap_stream) != size)
                fail("cannot write the snapshot stream");
        }
    }
    snap_stream_bytes += (uint64_t)n + length;
    snap_stream_count++;
}

static void snapshot(a2vm *m, const char *directory, const char *name,
                     const char *extra)
{
    char path[1200];
    if (snap_stream) {
        stream_snapshot(m, name);
        return;
    }
    snprintf(path, sizeof path, "%s/%s.json", directory, name);
    write_json(path, m, extra);
    if (snapshot_range_count) {
        snprintf(path, sizeof path, "%s/%s.img", directory, name);
        write_ranges_image(m, path);
        return;
    }
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
        } else if (!strcmp(verb, "read-ea") && n == 2) {
            uint16_t address = address16(words[1]);
            printf("read %04X %02X\n", address, a2vm_read_ea(m, address));
        } else if ((!strcmp(verb, "write") || !strcmp(verb, "write-ea")) &&
                   n == 3) {
            uint16_t address = address16(words[1]);
            uint64_t value = number(words[2], 16);
            if (value > 0xff)
                fail("%s:%u: a byte", path, number_of_line);
            if (verb[5])
                a2vm_write_ea(m, address, (uint8_t)value);
            else
                a2vm_write(m, address, (uint8_t)value);
        } else if (!strcmp(verb, "zpbank") && n == 1) {
            const a2vm_zpbank *z = &m->zpb;
            printf("zpbank armed=%u address=%02X rd=%02X wr=%02X "
                   "enables=%" PRIu64 " loads=%" PRIu64 " reads=%" PRIu64
                   " writes=%" PRIu64 " firmware=%" PRIu64 " amem=%" PRIu64
                   "\n", z->armed, z->address, z->rd, z->wr, z->enables,
                   z->loads, z->reads, z->writes, z->firmware, z->amem);
        } else if (!strcmp(verb, "zpbank-arm") && n == 2) {
            char error[256];
            if (!a2vm_zpbank_arm(m, strcmp(words[1], "0") != 0, error,
                                 sizeof error))
                fail("%s:%u: %s", path, number_of_line, error);
        } else if (!strcmp(verb, "reset") && n == 1) {
            a2vm_cpu_reset(m);
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
            if (c->p.slowdown_slot4) {
                COST_FIELD(slow_hits); COST_FIELD(slow_cycles);
                COST_FIELD(slow_clocks);
                printf(" slow_left=%u", c->slow_left);
            }
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
    char name[96];
    if (e->every && (e->action == ACT_SNAPSHOT || e->action == ACT_SHOT) &&
        e->visits > o->every_limit)
        fail("the event of line %u (pc %04X@*) would take %s number %"
             PRIu64 ", past --every-limit %" PRIu64, e->line,
             (unsigned)e->value, e->action == ACT_SNAPSHOT ? "snapshot"
             : "shot", e->visits, o->every_limit);
    /* an event at every visit names its snapshots and shots NAME-VISIT */
    if (e->every)
        snprintf(name, sizeof name, "%s-%04" PRIu64, e->name, e->visits);
    else
        snprintf(name, sizeof name, "%s", e->name);
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
        if (!o->snapshot_dir && !snap_stream)
            fail("the snapshot action needs --snapshot-dir");
        snapshot(m, o->snapshot_dir, name, NULL);
        break;
    case ACT_SHOT:
        if (!o->snapshot_dir)
            fail("the shot action needs --snapshot-dir");
        shot(m, o->snapshot_dir, name);
        break;
    case ACT_STOP: *stop = 1; break;
    }
    e->done = !e->every;
}

/* --irq-bounds LO-HI[,LO-HI...] (hex) */
static void irq_bounds(a2vm *m, const char *text)
{
    char buffer[256];
    if (strlen(text) >= sizeof buffer)
        fail("--irq-bounds: too long");
    strcpy(buffer, text);
    for (char *item = strtok(buffer, ","); item; item = strtok(NULL, ",")) {
        char *dash = strchr(item, '-');
        if (!dash)
            fail("--irq-bounds: %s is not LO-HI", item);
        *dash = 0;
        uint16_t low = address16(item), high = address16(dash + 1);
        if (low > high)
            fail("--irq-bounds: %s-%s is empty", item, dash + 1);
        if (m->irq_bound_count == A2VM_MAX_IRQ_BOUNDS)
            fail("--irq-bounds: at most %d ranges", A2VM_MAX_IRQ_BOUNDS);
        m->irq_bounds[m->irq_bound_count][0] = low;
        m->irq_bounds[m->irq_bound_count][1] = high;
        m->irq_bound_count++;
    }
    if (!m->irq_bound_count)
        fail("--irq-bounds: no range");
}

/* --lowest-s-in LO-HI[,LO-HI...] (hex): lows[0] is the whole run, the
   ranges follow. Returns the count. */
static unsigned lowest_s_ranges(const char *text, lowest_s *lows)
{
    char buffer[512];
    unsigned count = 1;
    if (strlen(text) >= sizeof buffer)
        fail("--lowest-s-in: too long");
    strcpy(buffer, text);
    for (char *item = strtok(buffer, ","); item; item = strtok(NULL, ",")) {
        char *dash = strchr(item, '-');
        if (!dash)
            fail("--lowest-s-in: %s is not LO-HI", item);
        *dash = 0;
        uint16_t low = address16(item), high = address16(dash + 1);
        if (low > high)
            fail("--lowest-s-in: %s-%s is empty", item, dash + 1);
        if (count == 1 + MAX_S_RANGES)
            fail("--lowest-s-in: at most %d ranges", MAX_S_RANGES);
        memset(&lows[count], 0, sizeof lows[count]);
        lows[count].low = low;
        lows[count].high = high;
        count++;
    }
    if (count == 1)
        fail("--lowest-s-in: no range");
    return count;
}

static void lower(lowest_s *l, uint8_t s, uint16_t pc, uint64_t cycles)
{
    if (!l->seen || s < l->s) {
        l->seen = 1;
        l->s = s;
        l->pc = pc;
        l->cycles = cycles;
    }
}

/* After a step: the instruction (or interrupt entry) that started at
   m->instruction_pc took S from the S of the step before (lows[0].last)
   to its present value. The whole run sees the new S; a range sees both
   when the step started inside it. */
static void note_lowest_s(const a2vm *m, lowest_s *lows, unsigned count)
{
    uint16_t pc0 = m->instruction_pc;
    uint8_t s0 = lows[0].last, s1 = a2vm_register(m, 's');
    uint64_t cycles = a2vm_now(m);
    lows[0].last = s1;
    lower(&lows[0], s1, pc0, cycles);
    lows[0].steps++;
    for (unsigned i = 1; i < count; i++)
        if (pc0 >= lows[i].low && pc0 <= lows[i].high) {
            lower(&lows[i], s0, pc0, cycles);
            lower(&lows[i], s1, pc0, cycles);
            lows[i].steps++;
        }
}

static size_t lowest_s_fields(char *out, size_t size, const lowest_s *l)
{
    char s[8];
    if (l->seen)
        snprintf(s, sizeof s, "%u", l->s);
    else
        snprintf(s, sizeof s, "null");
    int n = snprintf(out, size, "\"s\": %s, \"pc\": %u, \"cycles\": %"
                     PRIu64 ", \"steps\": %" PRIu64, s, l->pc, l->cycles,
                     l->steps);
    return n < 0 ? size : (size_t)n;
}

/* "lowest_s": {the whole run's fields, "ranges": [{"low", "high", then
   the fields}, ...]} */
static void lowest_s_json(char *out, size_t size, const lowest_s *lows,
                          unsigned count)
{
    size_t used = (size_t)snprintf(out, size, "  \"lowest_s\": {");
    if (used < size)
        used += lowest_s_fields(out + used, size - used, &lows[0]);
    if (used < size)
        used += (size_t)snprintf(out + used, size - used, ", \"ranges\": [");
    for (unsigned i = 1; i < count && used < size; i++) {
        used += (size_t)snprintf(out + used, size - used,
                                 "%s{\"low\": %u, \"high\": %u, ",
                                 i > 1 ? ", " : "", lows[i].low, lows[i].high);
        if (used < size)
            used += lowest_s_fields(out + used, size - used, &lows[i]);
        if (used < size)
            used += (size_t)snprintf(out + used, size - used, "}");
    }
    if (used < size)
        used += (size_t)snprintf(out + used, size - used, "]},\n");
    if (used >= size)
        fail("the lowest S does not fit the state");
}

/* ---- the PC log (README.md, "The PC log") ---- */

static struct {
    FILE *file;
    uint8_t map[8192];
    uint16_t bytes[MAX_PCLOG_BYTES];
    uint8_t stores[MAX_PCLOG_BYTES];    /* a2vm_storage's kinds: 0, 2 */
    unsigned byte_count;
    uint64_t from, limit, lines;
} pclog;

/* A list of hex numbers separated by commas, each at most 0xFFFF. */
static unsigned hex_list(const char *option, const char *text,
                         uint16_t *out, unsigned most)
{
    char buffer[2048];
    if (strlen(text) >= sizeof buffer)
        fail("%s: too long", option);
    snprintf(buffer, sizeof buffer, "%s", text);
    unsigned count = 0;
    for (char *item = strtok(buffer, ","); item; item = strtok(NULL, ",")) {
        if (count == most)
            fail("%s: at most %u entries", option, most);
        out[count++] = address16(item);
    }
    if (!count)
        fail("%s: an empty list", option);
    return count;
}

static void pclog_line(a2vm *m, uint16_t pc)
{
    uint64_t now = a2vm_now(m);
    if (now < pclog.from)
        return;
    if (pclog.lines == pclog.limit) {
        snprintf(m->halt, sizeof m->halt, "pclog: past --pclog-limit %"
                 PRIu64 " lines", pclog.limit);
        return;
    }
    pclog.lines++;
    fprintf(pclog.file, "%" PRIu64 " %04X %02X %02X %02X %02X %u", now, pc,
            a2vm_register(m, 'a'), a2vm_register(m, 'x'),
            a2vm_register(m, 'y'), a2vm_register(m, 's'),
            m->sw[SW_ALTZP] ? 1u : 0u);
    for (unsigned i = 0; i < pclog.byte_count; i++)
        fprintf(pclog.file, " %02X",
                *a2vm_storage(m, pclog.stores[i], 0, pclog.bytes[i]));
    fputc('\n', pclog.file);
}

static void pclog_start(a2vm *m, const options *o)
{
    uint16_t pcs[MAX_PCLOG_PCS];
    unsigned count = hex_list("--pclog-pcs", o->pclog_pcs, pcs,
                              MAX_PCLOG_PCS);
    for (unsigned i = 0; i < count; i++)
        pclog.map[pcs[i] >> 3] |= (uint8_t)(1u << (pcs[i] & 7));
    if (o->pclog_bytes) {
        char buffer[1024];
        if (strlen(o->pclog_bytes) >= sizeof buffer)
            fail("--pclog-bytes: too long");
        snprintf(buffer, sizeof buffer, "%s", o->pclog_bytes);
        for (char *item = strtok(buffer, ","); item;
             item = strtok(NULL, ",")) {
            unsigned i = pclog.byte_count;
            if (i == MAX_PCLOG_BYTES)
                fail("--pclog-bytes: at most %d entries", MAX_PCLOG_BYTES);
            pclog.stores[i] = 0;
            if (!strncmp(item, "lc.", 3)) {
                pclog.stores[i] = 2;
                item += 3;
            }
            pclog.bytes[i] = address16(item);
            if (pclog.stores[i] && pclog.bytes[i] < 0xc000)
                fail("--pclog-bytes: lc.%s is not in $C000-$FFFF", item);
            pclog.byte_count++;
        }
    }
    pclog.from = o->pclog_from;
    pclog.limit = o->pclog_limit;
    pclog.file = fopen(o->pclog, "w");
    if (!pclog.file)
        fail("cannot write %s", o->pclog);
    fprintf(pclog.file, "# a2vm pclog 1 (tools/a2vm/README.md, \"The PC "
            "log\")\n# pcs %s\n# bytes %s\n# clock %s\n"
            "# CLOCK PC A X Y S ALTZP BYTE...\n", o->pclog_pcs,
            o->pclog_bytes ? o->pclog_bytes : "-",
            m->cost && m->cost->timed ? "fabric clocks (--cost-timed)"
                                       : "cycles");
    m->pc_hook_map = pclog.map;
    m->pc_hook = pclog_line;
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
    m->via_ora_nh = o.via_ora_nh;
    m->via_timers = o.via_timers;
    m->phasor_mb_only = o.phasor_mb_only;
    if (o.irq_bounds)
        irq_bounds(m, o.irq_bounds);
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
        if (o.cost_pcmap && !a2vm_cost_pcmap(cost, o.cost_pcmap,
                                             o.cost_pcmap_when, error,
                                             sizeof error))
            fail("%s", error);
        if (o.cost_report) {
            cost->report = fopen(o.cost_report, "w");
            if (!cost->report)
                fail("cannot write %s", o.cost_report);
        }
        a2vm_attach_cost(m, cost, o.cost_timed);
        if (o.zpbank && !params.zp_pair)
            fail("--zpbank: the cost profile's firmware has no zero-page "
                 "pair (use f121zp or fastzp)");
    }
    if (o.zpbank || (m->cost && m->cost->p.zp_pair)) {
        if (!a2vm_zpbank_arm(m, 1, error, sizeof error))
            fail("%s", error);
    }
    if (o.write_log) {
        char path[1200];
        if (!a2vm_parse_ranges(o.write_log, m->write_ranges,
                               &m->write_range_count, 1, error, sizeof error))
            fail("--write-log: %s", error);
        if (o.write_log_file)
            snprintf(path, sizeof path, "%s", o.write_log_file);
        else
            snprintf(path, sizeof path, "%s/writes.log", o.snapshot_dir);
        FILE *log = fopen(path, "w");
        if (!log)
            fail("cannot write %s", path);
        a2vm_start_write_log(m, log);
        m->write_log_limit = o.write_log_limit;
        fprintf(m->write_log, "# a2vm write-log 1 (tools/a2vm/README.md, "
                "\"The write log\")\n"
                "# ranges %s\n"
                "# w CLOCK CPU_CYCLES PC ADDRESS STORAGE BANK OFFSET OLD NEW\n",
                o.write_log);
    }
    if (o.snapshot_ranges &&
        !a2vm_parse_ranges(o.snapshot_ranges, snapshot_ranges,
                           &snapshot_range_count, 0, error, sizeof error))
        fail("--snapshot-ranges: %s", error);
    if (o.snapshot_stream) {
        if (!strcmp(o.snapshot_stream, "-") && !o.state)
            fail("--snapshot-stream - needs --state (stdout is the stream)");
        if (o.snapshot_limit_given)
            snap_stream_limit = o.snapshot_limit;
        snap_stream = !strcmp(o.snapshot_stream, "-")
                          ? stdout : fopen(o.snapshot_stream, "wb");
        if (!snap_stream)
            fail("cannot write %s", o.snapshot_stream);
        int n = fprintf(snap_stream, "{\"format\": \"a2vm-snapshot-stream "
                        "1\", \"ranges\": \"%s\"}\n", o.snapshot_ranges);
        if (n < 0)
            fail("cannot write the snapshot stream");
        snap_stream_bytes = (uint64_t)n;
    }
    if (o.pclog)
        pclog_start(m, &o);
    if (o.ay_log) {
        m->ay_log = fopen(o.ay_log, "w");
        if (!m->ay_log)
            fail("cannot write %s", o.ay_log);
        fputs("# a2vm ay-log 1 (tools/a2vm/README.md, \"The AY log\")\n"
              "# w CPU_CYCLES APPLE_CYCLE CLOCK CHIP REG VALUE\n"
              "# reset CPU_CYCLES APPLE_CYCLE CLOCK CHIP\n"
              "# irq N CPU_CYCLES APPLE_CYCLE CLOCK\n"
              "# rti CPU_CYCLES APPLE_CYCLE CLOCK\n", m->ay_log);
        if (m->cost)
            fprintf(m->ay_log, "# clock fabric %.6f MHz, apple cycle %.4f "
                    "clocks\n", m->cost->p.fabric_mhz, m->cost->period);
        else
            fputs("# clock - (no cost model)\n", m->ay_log);
    }

    if (o.bus_script) {
        bus_script(m, o.bus_script);
        if (pclog.file && fclose(pclog.file))
            fail("cannot write %s", o.pclog);
        if (m->ay_log)
            fclose(m->ay_log);
        if (m->write_log && fclose(m->write_log))
            fail("cannot write the write log");
        m->write_log = NULL;
        a2vm_free(m);
        return 0;
    }

    static lowest_s lows[1 + MAX_S_RANGES];
    unsigned low_count = 0;
    if (o.lowest_s) {
        lows[low_count].low = 0;
        lows[low_count++].high = 0xffff;
        if (o.lowest_s_in)
            low_count = lowest_s_ranges(o.lowest_s_in, lows);
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

    int stop = 0, word_below = 0;
    const char *reason = NULL;
    uint64_t boundaries = 0, start_cycles = a2vm_now(m);
    uint64_t start_instructions = m->instructions;
    for (unsigned i = 0; i < event_count && !stop; i++)
        if (events[i].when == WHEN_START)
            act(m, &o, &events[i], &stop);
    if (stop)
        reason = "stop";
    clock_t started = clock();

    if (low_count) {
        lows[0].seen = 1;           /* the whole run starts at the start S */
        lows[0].s = lows[0].last = a2vm_register(m, 's');
        lows[0].pc = a2vm_pc(m);
        lows[0].cycles = a2vm_now(m);
    }
    while (!reason) {
        if (a2vm_now(m) >= o.cycles) {
            reason = o.cycles_given ? "cycles" : "cycle-cap";
            break;
        }
        a2vm_step(m);
        if (low_count)
            note_lowest_s(m, lows, low_count);
        if (m->halt[0]) {
            reason = "halt";
            break;
        }
        uint16_t pc = a2vm_pc(m);
        if (o.cost_pcmap)
            a2vm_cost_pc(m, pc);
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
            for (unsigned i = 0; i < event_count; i++) {
                event *e = &events[i];
                if (e->done || e->when != WHEN_PC || e->value != pc ||
                    (e->main_only && !main_zp))
                    continue;
                e->visits++;
                if (e->every || e->visits == e->nth)
                    act(m, &o, e, &stop);
            }
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
        if (!reason && o.stop_word) {
            if (le(m->main + o.stop_word_at, 4) < o.stop_word_value)
                word_below = 1;
            else if (word_below)
                reason = "stop-word";
        }
        if (!reason && m->prodos && m->prodos->quit)
            reason = "quit";
        if (!reason && boundaries >= o.boundaries)
            reason = "boundaries";
    }
    double seconds = (double)(clock() - started) / CLOCKS_PER_SEC;

    char extra[8192];
    int used = snprintf(extra, sizeof extra,
             "  \"end\": \"%s\",\n  \"halt\": \"%s\",\n"
             "  \"boundaries\": %" PRIu64 ",\n"
             "  \"run_cycles\": %" PRIu64 ",\n"
             "  \"instructions\": %" PRIu64 ",\n"
             "  \"host_seconds\": %.6f,\n", reason, m->halt,
             boundaries, a2vm_now(m) - start_cycles,
             m->instructions - start_instructions, seconds);
    if (low_count)
        lowest_s_json(extra + used, sizeof extra - (size_t)used, lows,
                      low_count);
    if (o.final_snapshot)
        snapshot(m, o.snapshot_dir, "final", extra);
    stream_end(reason);
    if (m->cost && m->cost->report) {
        fputs("{\"final\": true,\n", m->cost->report);
        a2vm_cost_final(m, m->cost->report);
        fprintf(m->cost->report, "  \"host_seconds\": %.6f}\n", seconds);
        fclose(m->cost->report);
        m->cost->report = NULL;
    }
    write_json(o.state, m, extra);
    if (m->ay_log && fclose(m->ay_log))
        fail("cannot write %s", o.ay_log);
    m->ay_log = NULL;
    if (m->write_log && fclose(m->write_log))
        fail("cannot write the write log");
    m->write_log = NULL;
    if (pclog.file && fclose(pclog.file))
        fail("cannot write %s", o.pclog);
    pclog.file = NULL;
    int status = !strcmp(reason, "halt") ? 1 : 0;
    if (!strcmp(reason, "cycle-cap")) {
        fprintf(stderr, "a2vm: the run reached the default limit of %llu "
                "cycles (give --cycles N, or --cycles none for no limit)\n",
                (unsigned long long)DEFAULT_CYCLES);
        status = 3;
    }
    a2vm_free(m);
    return status;
}
