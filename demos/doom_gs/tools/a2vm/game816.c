/*
 * The 65816 interpreter of src/vm on upstream's game, on a2vm, against
 * the reference machine of tools/ref816 (docs/MILESTONES.md 3.2, items 2
 * and 3).
 *
 * usage: game816 [--vm DIR] [--cost PARAMS] [--limit N] contact IMAGE
 *        game816 [--vm DIR] [--cost PARAMS] samples FILE
 *        game816 [--vm DIR] [--cost PARAMS] pages
 *
 * DIR (default build/vm) holds the interpreter as src/vm/Makefile builds
 * it. PARAMS is a cost parameter file (tools/a2vm/costs.py): the cost
 * model of cost.h then runs beside the machine and every instruction is
 * also charged in fabric clocks. The report is JSON on the standard
 * output; the exit status is 1 when the run found a difference.
 *
 * The game's map. Unlike the vector harness (vm816.c), which maps what
 * each case lists, this program builds the map of the game, as
 * docs/ARCHITECTURE.md 3.3 lays it out and src/vm/README.md ("The game's
 * map") describes it, in the interpreter's own tables:
 *
 *   $00:0000-$7FFF  page table 0: $0900-$0AFF in main $1400-$15FF (the
 *                   direct page), $3000-$3FFF in main $6000-$6FFF (the
 *                   stack), $4000-$7FFF in RamWorks (the code of bank 0,
 *                   BOOTINFO); the other pages trap
 *   $00:8000-$FFFF  page table 1: RamWorks, but $C000-$CFFF (the IIgs
 *                   I/O space) traps
 *   $01 and $E1     page tables 2 and 3, shared: $0200-$BFFF in base aux
 *                   memory, identity (the screen); the rest traps. $E0
 *                   traps
 *   $02-$12, $1B-$26, $2A-$3F
 *                   flat granules, one RamWorks bank a half-bank
 *   the rest        unmapped: $13-$1A and $27-$29 (quarter squares, DOC
 *                   sound: ARCHITECTURE.md 3.3 leaves them out), $40 and
 *                   up (the level store of an 8 MB IIgs)
 *
 * Two simplifications, until the planner of milestone 5 lays out bank
 * $02 and the fast memory: bank $02 is two flat granules (no near core
 * in main RAM), and the code cache is the interpreter's (vm.s).
 *
 * contact: the first contact with the game. IMAGE is the memory image of
 * tools/ref816/make_image.py (build/ref816/memory.img). Both machines load
 * it: ref816's IIgs (tools/ref816/iigs.c) as ref816 does, and the
 * interpreter's virtual memory through the map above (bytes at unmapped
 * addresses are counted, by bank, and left out). Both start at the entry
 * point with the image's registers. The interpreter runs through vm_run;
 * the harness steps the 65C02 and, each time the dispatch loop comes back
 * to `loop` (one 65816 instruction done), runs one instruction on the
 * reference and compares the registers (A, X, Y, S, D, DBR, PBR, PC, P,
 * E and the run state) and the writes of the instruction: every CPU write
 * of the interpreter (a2vm's write hook) is turned back into its virtual
 * addresses through the map and must match the reference's writes (as
 * multisets of address and value); a write outside virtual memory and
 * the interpreter's own data is a difference. The run stops at the first
 * access of the reference to the IIgs I/O space ($C000-$CFFF of banks
 * $00 and $01 while the shadow register's bit 6 is clear, and of banks
 * $E0 and $E1), to the ROM, or to memory the reference does not have; at
 * the first difference; when the interpreter stops (a trap); or after N
 * instructions (--limit). At an I/O access the interpreter must have
 * trapped at the same address. At the end the whole mapped virtual
 * memory is compared with the reference's.
 *
 * The cost of an instruction is the time from one arrival at `loop` to
 * the next: the loop's test, the service of any event (a new code page,
 * a cold page copied into the cache), the dispatch and the handler.
 *
 * samples: see samples_run below; pages: see pages_run.
 */
#include "a2vm.h"
#include "cost.h"
#include "iigs.h"

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { STUB_INIT = 0x0320, STUB_INIT_END = 0x0323, STUB_RUN = 0x0330,
       STUB_RUN_RETURN = 0x0339, STUB_RUN_END = 0x033C,
       STUB_WARM = 0x0350, STUB_WARM_RETURN = 0x0356, STUB_WARM_END = 0x0359,
       STUB_EXPORT = 0x0340, STUB_EXPORT_END = 0x0343 };
enum { MAX_STEPS = 2000000, MAX_WRITES = 64, HEADER = 32 };
enum { SP_MAIN = 0x80, SP_TRAP = 0xff };

/* ---- the interpreter's symbols ---- */

static struct {
    const char *name;
    uint32_t value;
} symbols[] = {
    { "vA", 0 }, { "vX", 0 }, { "vY", 0 }, { "vS", 0 }, { "vD", 0 },
    { "vDBR", 0 }, { "vPBR", 0 }, { "vE", 0 }, { "vm_p", 0 },
    { "vm_pc", 0 }, { "vm_status", 0 }, { "ea", 0 }, { "vm_init", 0 },
    { "vm_flush", 0 }, { "vm_import", 0 }, { "vm_export", 0 },
    { "vm_run", 0 }, { "map0", 0 }, { "map1", 0 }, { "watch", 0 },
    { "vm_trap_ex", 0 }, { "VM_PTAB", 0 }, { "VM_CACHE", 0 },
    { "VM_NSLOT", 0 }, { "VM_NPTAB", 0 }, { "vm_event", 0 },
    { "vm_state", 0 }, { "loop", 0 }, { "fetch", 0 }, { "service", 0 },
    { "vpcl", 0 }, { "vpch", 0 }, { "vN", 0 }, { "vV", 0 }, { "vZ", 0 },
    { "vC", 0 }, { "vMX", 0 }, { "vP", 0 }, { "curbank", 0 },
    { "imm_m", 0 }, { "next_page", 0 }, { "getp", 0 },
};

enum { S_A, S_X, S_Y, S_S, S_D, S_DBR, S_PBR, S_E, S_P, S_PC, S_STATUS,
       S_EA, S_INIT, S_FLUSH, S_IMPORT, S_EXPORT, S_RUN, S_MAP0, S_MAP1,
       S_WATCH, S_TRAP_EX, S_PTAB, S_CACHE, S_NSLOT, S_NPTAB, S_EVENT,
       S_STATE, S_LOOP, S_FETCH, S_SERVICE, S_VPCL, S_VPCH, S_VN, S_VV,
       S_VZ, S_VC, S_VMX, S_VP, S_CURBANK, S_IMM_M, S_NEXT_PAGE, S_GETP,
       S_COUNT };

static uint32_t first_handler = 0x10000;  /* the lowest of h00-hFF */

#define SYM(i) (symbols[i].value)

static _Noreturn void fail(const char *message, const char *detail)
{
    fprintf(stderr, "game816: %s%s%s\n", message, detail ? ": " : "",
            detail ? detail : "");
    exit(2);
}

static void load_symbols(const char *path)
{
    char line[256], name[128];
    unsigned value;
    FILE *file = fopen(path, "r");
    if (!file)
        fail(path, strerror(errno));
    while (fgets(line, sizeof line, file))
        if (sscanf(line, "al %x .%127s", &value, name) == 2) {
            unsigned opcode;
            char rest;
            for (size_t i = 0; i < S_COUNT; i++)
                if (!strcmp(symbols[i].name, name))
                    symbols[i].value = value;
            if (sscanf(name, "h%2x%c", &opcode, &rest) == 1 &&
                strlen(name) == 3 && value < first_handler)
                first_handler = value;
        }
    fclose(file);
    if (first_handler == 0x10000)
        fail("no handlers in vm.lbl", path);
    for (size_t i = 0; i < S_COUNT; i++)
        if (!symbols[i].value)
            fail("no symbol in vm.lbl", symbols[i].name);
}

static uint8_t *read_file(const char *path, size_t *size)
{
    FILE *file = fopen(path, "rb");
    uint8_t *data;
    long length;

    if (!file || fseek(file, 0, SEEK_END) || (length = ftell(file)) < 0 ||
        fseek(file, 0, SEEK_SET))
        fail(path, strerror(errno));
    data = malloc(length ? (size_t)length : 1);
    if (!data || fread(data, 1, (size_t)length, file) != (size_t)length)
        fail(path, "cannot read");
    fclose(file);
    *size = (size_t)length;
    return data;
}

static uint32_t le(const uint8_t *p, int bytes)
{
    uint32_t value = 0;
    for (int i = bytes - 1; i >= 0; i--)
        value = value << 8 | p[i];
    return value;
}

/* ---- the machine ---- */

static a2vm *m;
static uint64_t host_steps;

static uint8_t *main_at(uint32_t address)
{
    return a2vm_storage(m, 0, 0, (uint16_t)address);
}

static void put_word(uint32_t at, uint16_t value)
{
    *main_at(at) = (uint8_t)value;
    *main_at(at + 1) = (uint8_t)(value >> 8);
}

static uint16_t get_word(uint32_t at)
{
    return (uint16_t)(*main_at(at) | *main_at(at + 1) << 8);
}

static void put_jsr(uint16_t at, uint32_t target)
{
    *main_at(at) = 0x20;
    put_word(at + 1u, (uint16_t)target);
}

/* Run from `start` until the CPU reaches `end`. */
static int run_stub(uint16_t start, uint16_t end)
{
    unsigned long n = 0;
    m->cpu.pc = start;
    m->cpu.state = CPU65C02_RUNNING;
    while (m->cpu.pc != end) {
        a2vm_step(m);
        if (++n > MAX_STEPS || m->cpu.state != CPU65C02_RUNNING)
            return 0;
    }
    host_steps += n;
    return 1;
}

static void setup(const char *dir)
{
    char path[1024], error[256];
    static const struct { const char *suffix; int kind; uint16_t at; }
        parts[] = { { "vm.bin.d000", 3, 0xd000 }, { "vm.bin.e000", 2, 0xe000 },
                    { "vm.bin.f000", 2, 0xf000 } };
    a2vm_config config;

    snprintf(path, sizeof path, "%s/vm.lbl", dir);
    load_symbols(path);
    a2vm_default_config(&config);
    config.core = A2VM_CORE_W65C02S;
    config.mouse = 0;
    m = a2vm_new(&config, error, sizeof error);
    if (!m)
        fail(error, NULL);
    for (size_t i = 0; i < sizeof parts / sizeof parts[0]; i++) {
        size_t size;
        uint8_t *data;
        snprintf(path, sizeof path, "%s/%s", dir, parts[i].suffix);
        data = read_file(path, &size);
        if (size > (size_t)(0x10000 - parts[i].at) ||
            (parts[i].kind == 3 && size > 0x1000))
            fail(path, "too long");
        memcpy(a2vm_storage(m, parts[i].kind, 0, parts[i].at), data, size);
        free(data);
    }
    m->lc_read = 1;
    m->lc_write = 0;
    m->lc_bank2 = 0;
    a2vm_remap(m);

    put_jsr(STUB_INIT, SYM(S_INIT));
    *main_at(STUB_INIT_END) = 0xdb;
    put_jsr(STUB_RUN, SYM(S_FLUSH));
    put_jsr(STUB_RUN + 3, SYM(S_IMPORT));
    put_jsr(STUB_RUN + 6, SYM(S_RUN));
    put_jsr(STUB_RUN_RETURN, SYM(S_EXPORT));
    *main_at(STUB_RUN_END) = 0xdb;
    put_jsr(STUB_EXPORT, SYM(S_EXPORT));
    *main_at(STUB_EXPORT_END) = 0xdb;
    put_jsr(STUB_WARM, SYM(S_IMPORT));          /* vm_run without vm_flush */
    put_jsr(STUB_WARM + 3, SYM(S_RUN));
    put_jsr(STUB_WARM_RETURN, SYM(S_EXPORT));
    *main_at(STUB_WARM_END) = 0xdb;
    if (SYM(S_NPTAB) < 4)
        fail("the interpreter has fewer than 4 page tables", NULL);
    m->cpu.s = 0xff;
    if (!run_stub(STUB_INIT, STUB_INIT_END))
        fail("vm_init did not return", NULL);
}

static void attach_cost(const char *params_path)
{
    a2vm_cost_params params;
    char error[256];
    if (!params_path)
        return;
    if (!a2vm_cost_load(&params, params_path, error, sizeof error))
        fail(error, NULL);
    a2vm_attach_cost(m, a2vm_cost_new(&params), 0);
}

static uint64_t clocks_now(void)
{
    return m->cost ? m->cost->t : 0;
}

/* ---- where the time goes ---- */

/* The parts of the interpreter a 65C02 instruction can be in, by address
   (vm.cfg places them: alu.s then handlers.s in LC bank 1 at $D000,
   core.s then modes.s at $E000, far.s at $F000). */
typedef enum { PT_DISPATCH, PT_CORE, PT_PAGE, PT_MODES, PT_FAR,
               PT_OPERATIONS, PT_HANDLERS, PT_OTHER, PARTS } part;

static const char *const PART_NAMES[PARTS] = {
    "dispatch loop", "core: events, P, PC", "code cache: a new page",
    "addressing modes", "far layer", "operations", "handlers",
    "outside the interpreter"
};

static part part_of(uint16_t pc)
{
    if (pc >= SYM(S_LOOP) && pc < SYM(S_SERVICE))
        return PT_DISPATCH;
    if (pc >= SYM(S_NEXT_PAGE) && pc < SYM(S_GETP))
        return PT_PAGE;             /* next_page, ensure_page, load_page */
    if (pc >= 0xf000)
        return PT_FAR;
    if (pc >= SYM(S_IMM_M) && pc < 0xf000)
        return PT_MODES;
    if (pc >= 0xe000)
        return PT_CORE;
    if (pc >= first_handler)
        return PT_HANDLERS;
    if (pc >= 0xd000)
        return PT_OPERATIONS;
    return PT_OTHER;
}

/* Cycles and clocks by part, and the clocks by class of access of the
   cost model, over the measured instructions. */
enum { CL_FAST, CL_RAMWORKS, CL_IO, CL_VIDEO, CL_BUS_CYCLES, CL_QUIET,
       CL_IO_ACCESSES, CL_RW_ACCESSES, CL_RW_MISSES, CL_INVALIDATIONS,
       CLASSES };

static const char *const CLASS_NAMES[CLASSES] = {
    "fast_clocks", "ramworks_clocks", "io_clocks", "video_clocks",
    "bus_cycles", "quiet_switches", "io_accesses", "ramworks_accesses",
    "ramworks_misses", "turbo_invalidations"
};

static uint64_t part_cycles[PARTS], part_clocks[PARTS];
static uint64_t pending_cycles[PARTS], pending_clocks[PARTS];
static uint64_t class_sum[CLASSES], pending_class[CLASSES];

/* The samples leave the loading of a code page out of an instruction's
   cost (the model of the code cache counts it): its time is set apart. */
static int exclude_pages;
static uint64_t pending_page[2], excluded_page[2];      /* cycles, clocks */

static void classes_now(uint64_t out[CLASSES])
{
    const a2vm_cost_counters *c = m->cost ? &m->cost->c : NULL;
    if (!c) {
        memset(out, 0, CLASSES * sizeof *out);
        return;
    }
    out[CL_FAST] = c->fast_clocks;
    out[CL_RAMWORKS] = c->rw_clocks;
    out[CL_IO] = c->io_clocks;
    out[CL_VIDEO] = c->video_clocks;
    out[CL_BUS_CYCLES] = c->bus_cycles;
    out[CL_QUIET] = c->quiet;
    out[CL_IO_ACCESSES] = c->io_accesses;
    out[CL_RW_ACCESSES] = c->rw_accesses;
    out[CL_RW_MISSES] = c->rw_misses;
    out[CL_INVALIDATIONS] = c->invalidations;
}

static uint64_t clocks_now(void);

/* The loading of a code page: from the entry of next_page or ensure_page
   until they return (what they call, resolve, included). */
static int in_page;
static uint8_t page_sp;

/* One 65C02 instruction of a measured instruction, its time to its part. */
static void measured_step(void)
{
    uint64_t cycles = m->cpu.cycles, clocks = clocks_now();
    uint64_t before[CLASSES], after[CLASSES];
    part where_pc = part_of(m->cpu.pc);
    if (in_page && where_pc != PT_PAGE && m->cpu.s >= page_sp)
        in_page = 0;                    /* returned */
    if (!in_page && where_pc == PT_PAGE) {
        in_page = 1;
        page_sp = m->cpu.s;
    }
    if (in_page)
        where_pc = PT_PAGE;
    classes_now(before);
    a2vm_step(m);
    host_steps++;
    if (exclude_pages && where_pc == PT_PAGE) {
        pending_page[0] += m->cpu.cycles - cycles;
        pending_page[1] += clocks_now() - clocks;
        return;
    }
    classes_now(after);
    pending_cycles[where_pc] += m->cpu.cycles - cycles;
    pending_clocks[where_pc] += clocks_now() - clocks;
    for (unsigned i = 0; i < CLASSES; i++)
        pending_class[i] += after[i] - before[i];
}

/* A measured instruction starts: its steps and classes count from here. */
static void measure_start(void)
{
    in_page = 0;
    memset(pending_cycles, 0, sizeof pending_cycles);
    memset(pending_clocks, 0, sizeof pending_clocks);
    memset(pending_class, 0, sizeof pending_class);
    pending_page[0] = pending_page[1] = 0;
}

/* It is done and right: its time goes into the sums. */
static void measure_commit(void)
{
    for (unsigned i = 0; i < CLASSES; i++)
        class_sum[i] += pending_class[i];
    for (unsigned i = 0; i < PARTS; i++) {
        part_cycles[i] += pending_cycles[i];
        part_clocks[i] += pending_clocks[i];
    }
    excluded_page[0] += pending_page[0];
    excluded_page[1] += pending_page[1];
}

static void json_parts(FILE *out)
{
    fprintf(out, "  \"parts\": {");
    for (unsigned i = 0; i < PARTS; i++)
        fprintf(out, "%s\"%s\": [%" PRIu64 ", %" PRIu64 "]", i ? ", " : "",
                PART_NAMES[i], part_cycles[i], part_clocks[i]);
    fprintf(out, "},\n  \"page_loads_set_apart\": [%" PRIu64 ", %" PRIu64
            "],\n  \"classes\": {", excluded_page[0], excluded_page[1]);
    for (unsigned i = 0; i < CLASSES; i++)
        fprintf(out, "%s\"%s\": %" PRIu64, i ? ", " : "", CLASS_NAMES[i],
                class_sum[i]);
    fprintf(out, "},\n");
}

/* ---- the game's map ---- */

typedef struct {
    int kind;           /* 0 main, 1 RamWorks (aux) bank, -1 unmapped */
    unsigned bank;
    uint16_t address;
} place;

static unsigned banks_used;

static void set_page(unsigned table, unsigned vpage, uint8_t space,
                     uint8_t physical)
{
    uint32_t at = SYM(S_PTAB) + 256u * table + (vpage & 0x7f) * 2;
    *main_at(at) = space;
    *main_at(at + 1) = physical;
}

static void set_half(unsigned bank, unsigned half, uint8_t entry)
{
    unsigned index = (bank * 2 + half) & 0xff;
    *main_at((bank & 0x80 ? SYM(S_MAP1) : SYM(S_MAP0)) + index) = entry;
}

/* Is virtual bank `bank` a bank of flat granules? `all` maps the banks
   below $40 that ARCHITECTURE.md 3.3 leaves out too (for the samples). */
static int granule_bank(unsigned bank, int all)
{
    if (bank >= 0x02 && bank <= 0x12)
        return 1;
    if ((bank >= 0x1b && bank <= 0x26) || (bank >= 0x2a && bank <= 0x3f))
        return 1;
    return all && ((bank >= 0x13 && bank <= 0x1a) ||
                   (bank >= 0x27 && bank <= 0x29));
}

static void build_map(int all)
{
    unsigned next = 1;                  /* RamWorks banks from 1 */
    uint8_t low = (uint8_t)next++, high = (uint8_t)next++;

    memset(main_at(SYM(S_MAP0)), SP_TRAP, 256);
    memset(main_at(SYM(S_MAP1)), SP_TRAP, 256);
    for (unsigned page = 0; page < 0x80; page++) {
        if (page == 0x09 || page == 0x0a)
            set_page(0, page, SP_MAIN, (uint8_t)(page + 0x0b));
        else if (page >= 0x30 && page < 0x40)
            set_page(0, page, SP_MAIN, (uint8_t)(page + 0x30));
        else if (page >= 0x40)
            set_page(0, page, low, (uint8_t)(page + 0x40));
        else
            set_page(0, page, SP_TRAP, 0);
    }
    for (unsigned page = 0x80; page < 0x100; page++) {
        if (page >= 0xc0 && page < 0xd0)
            set_page(1, page, SP_TRAP, 0);
        else
            set_page(1, page, high, (uint8_t)((page & 0x7f) + 0x40));
    }
    for (unsigned page = 0; page < 0x100; page++) {
        unsigned table = 2 + (page >> 7);
        if (page >= 0x02 && page < 0xc0)
            set_page(table, page, 0, (uint8_t)page);
        else
            set_page(table, page, SP_TRAP, 0);
    }
    set_half(0x00, 0, 0x80);
    set_half(0x00, 1, 0x81);
    set_half(0x01, 0, 0x82);
    set_half(0x01, 1, 0x83);
    set_half(0xe1, 0, 0x82);
    set_half(0xe1, 1, 0x83);
    for (unsigned bank = 0x02; bank < 0x40; bank++)
        if (granule_bank(bank, all))
            for (unsigned half = 0; half < 2; half++) {
                if (next > 127)
                    fail("the map needs more than 127 RamWorks banks", NULL);
                set_half(bank, half, (uint8_t)next++);
            }
    banks_used = next - 1;
}

/* Where the tables put virtual `address`, read from the tables in the
   machine's memory (independently of the interpreter). */
static place where(uint32_t address)
{
    place p = { -1, 0, 0 };
    unsigned bank = address >> 16 & 0xff, page = address >> 8 & 0xff;
    unsigned half = (bank * 2 + (page >> 7)) & 0xff;
    uint8_t entry = *main_at((bank & 0x80 ? SYM(S_MAP1) : SYM(S_MAP0)) +
                             half);
    uint8_t space, physical;

    if (entry == SP_TRAP)
        return p;
    if (entry < 0x80) {
        space = entry;
        physical = (uint8_t)((page & 0x7f) + 0x40);
    } else {
        uint32_t table = SYM(S_PTAB) + 256u * (entry & 0x7f);
        space = *main_at(table + (page & 0x7f) * 2);
        physical = *main_at(table + (page & 0x7f) * 2 + 1);
        if (space == SP_TRAP)
            return p;
    }
    p.kind = space == SP_MAIN ? 0 : 1;
    p.bank = space == SP_MAIN ? 0 : space;
    p.address = (uint16_t)(physical << 8 | (address & 0xff));
    return p;
}

static uint8_t *storage_of(place p)
{
    return a2vm_storage(m, p.kind, p.bank, p.address);
}

/* Physical pages back to virtual pages: main pages, then the 128
   RamWorks banks. Each physical page has at most two names ($01 and
   $E1 share one). */
enum { NAMES = 2, PHYS_PAGES = 256 + 128 * 256 };
static uint32_t names[PHYS_PAGES][NAMES];      /* virtual page + 1; 0 none */

static unsigned phys_index(place p)
{
    return p.kind == 0 ? (unsigned)(p.address >> 8)
                       : 256 + p.bank * 256 + (unsigned)(p.address >> 8);
}

static void build_names(void)
{
    memset(names, 0, sizeof names);
    for (uint32_t vpage = 0; vpage < 0x10000; vpage++) {
        place p = where(vpage << 8);
        if (p.kind < 0)
            continue;
        uint32_t *slot = names[phys_index(p)];
        unsigned i = 0;
        while (i < NAMES && slot[i])
            i++;
        if (i == NAMES)
            fail("a physical page with more than two virtual names", NULL);
        slot[i] = vpage + 1;
    }
}

/* ---- the interpreter's writes ---- */

typedef struct {
    uint32_t address;       /* virtual; for $01/$E1 the lower name */
    uint32_t other;         /* the other name, or UINT32_MAX */
    uint8_t value;
} vwrite;

static vwrite iwrites[MAX_WRITES];
static unsigned iwrite_count;
static char stray[200];

static void note_stray(const char *text)
{
    if (!*stray)
        snprintf(stray, sizeof stray, "%s", text);
}

static void on_write(a2vm *machine, uint16_t address, uint8_t *storage,
                     uint8_t value)
{
    char text[160];
    place p = { -1, 0, 0 };

    if (!storage) {
        if ((address >= 0xc002 && address <= 0xc005) || address == 0xc073)
            return;
        snprintf(text, sizeof text, "a write to $%04x (I/O or a "
                 "write-protected page)", address);
        note_stray(text);
        return;
    }
    if (storage >= machine->main && storage < machine->main + 0x10000) {
        uint32_t at = (uint32_t)(storage - machine->main);
        uint32_t ram_end = SYM(S_TRAP_EX) + 2;
        uint32_t cache_end = SYM(S_CACHE) + 256u * SYM(S_NSLOT);
        if (at < 0x200 || (at >= SYM(S_WATCH) && at < ram_end) ||
            (at >= SYM(S_CACHE) && at < cache_end))
            return;                     /* the interpreter's own */
        p.kind = 0;
        p.address = (uint16_t)at;
    } else if (storage >= machine->aux_banks &&
               storage < machine->aux_banks + (size_t)A2VM_MAX_BANKS *
                                                  A2VM_BANK_SIZE) {
        size_t offset = (size_t)(storage - machine->aux_banks);
        p.kind = 1;
        p.bank = (unsigned)(offset >> 16);
        p.address = (uint16_t)offset;
    } else {
        snprintf(text, sizeof text, "a write to $%04x in the language "
                 "card", address);
        note_stray(text);
        return;
    }
    const uint32_t *slot = names[phys_index(p)];
    if (!slot[0]) {
        snprintf(text, sizeof text, "a write to %s %u $%04x, which is no "
                 "virtual memory", p.kind ? "aux bank" : "main", p.bank,
                 p.address);
        note_stray(text);
        return;
    }
    if (iwrite_count == MAX_WRITES) {
        note_stray("too many writes in one instruction");
        return;
    }
    vwrite *w = &iwrites[iwrite_count++];
    w->address = (slot[0] - 1) << 8 | (p.address & 0xff);
    w->other = slot[1] ? ((slot[1] - 1) << 8 | (p.address & 0xff))
                       : UINT32_MAX;
    w->value = value;
}

/* ---- the reference ---- */

typedef enum { A_NONE, A_IO, A_ROM, A_NOMEM } special;

static const char *const SPECIAL_NAMES[] = {
    "none", "the IIgs I/O space", "the ROM", "memory the IIgs does not have"
};

static iigs ref;
static cpu816_read_fn ref_read;
static cpu816_write_fn ref_write;
static void *ref_context;
static vwrite rwrites[MAX_WRITES];
static unsigned rwrite_count, rwrite_lost;
static special first_special;
static uint32_t special_address;
static int special_write;

static special classify(uint32_t address)
{
    unsigned bank = address >> 16;
    uint16_t offset = (uint16_t)address;
    if (bank == 0xe0 || bank == 0xe1)
        return offset >= 0xc000 && offset < 0xd000 ? A_IO : A_NONE;
    if (bank < 2 && offset >= 0xc000 && !(ref.shadow & IIGS_SHADOW_IOLC))
        return offset < 0xd000 ? A_IO : A_ROM;
    if (bank >= IIGS_RAM_BANKS)
        return A_NOMEM;
    return A_NONE;
}

static void note_special(uint32_t address, int write)
{
    special kind = classify(address);
    if (kind != A_NONE && first_special == A_NONE) {
        first_special = kind;
        special_address = address;
        special_write = write;
    }
}

static uint8_t observed_read(void *context, uint32_t address)
{
    (void)context;
    note_special(address, 0);
    return ref_read(ref_context, address);
}

static void observed_write(void *context, uint32_t address, uint8_t value)
{
    (void)context;
    note_special(address, 1);
    if (rwrite_count < MAX_WRITES) {
        rwrites[rwrite_count].address = address;
        rwrites[rwrite_count].other = UINT32_MAX;
        rwrites[rwrite_count++].value = value;
    } else
        rwrite_lost++;
    ref_write(ref_context, address, value);
}

/* ---- the image ---- */

typedef struct {
    uint16_t pc, a, x, y, s, d;
    uint8_t pbr, dbr, p, e;
    uint8_t switches[4];
} image_header;

static uint64_t unloaded[256];          /* bytes by bank */
static uint64_t loaded, aliased;

static void load_image(const char *path, image_header *h)
{
    size_t length, at = HEADER;
    uint8_t *data = read_file(path, &length);

    if (length < HEADER || memcmp(data, "REF816I1", 8))
        fail(path, "not a ref816 memory image");
    h->pc = (uint16_t)le(data + 8, 2);
    h->pbr = data[10];
    h->dbr = data[11];
    h->a = (uint16_t)le(data + 12, 2);
    h->x = (uint16_t)le(data + 14, 2);
    h->y = (uint16_t)le(data + 16, 2);
    h->s = (uint16_t)le(data + 18, 2);
    h->d = (uint16_t)le(data + 20, 2);
    h->p = data[22];
    h->e = data[23] & 1;
    memcpy(h->switches, data + 24, 4);

    /* The reference, as tools/ref816/main.c loads an image. */
    if (!iigs_init(&ref))
        fail("out of memory", NULL);
    ref.cpu.pc = h->pc;
    ref.cpu.pbr = h->pbr;
    ref.cpu.dbr = h->dbr;
    ref.cpu.a = h->a;
    ref.cpu.x = h->x;
    ref.cpu.y = h->y;
    ref.cpu.s = h->s;
    ref.cpu.d = h->d;
    ref.cpu.p = h->p;
    ref.cpu.e = h->e;
    cpu816_normalise(&ref.cpu);
    iigs_set_switches(&ref, h->switches[0], h->switches[1], h->switches[2],
                      h->switches[3]);
    while (at < length) {
        if (length - at < 8)
            fail(path, "a record is cut short");
        uint32_t address = le(data + at, 4), count = le(data + at + 4, 4);
        at += 8;
        if (count > length - at)
            fail(path, "a record is cut short");
        if (!iigs_load(&ref, address, data + at, count))
            fail(path, "a record is outside the IIgs's RAM");
        at += count;
    }
    free(data);

    /* The interpreter's memory: every mapped byte from the reference's
       memory once it is loaded (the image's records may overlap; the
       last one wins in both). Bytes the map leaves out are counted. */
    for (uint32_t vpage = 0; vpage < 0x10000; vpage++) {
        uint32_t base = vpage << 8;
        unsigned bank = vpage >> 8;
        int exists = bank < IIGS_RAM_BANKS || bank == 0xe0 || bank == 0xe1;
        place p = where(base);
        if (!exists)
            continue;
        for (unsigned i = 0; i < 256; i++) {
            uint8_t value = iigs_peek(&ref, base + i);
            if (p.kind < 0) {
                if (value)
                    unloaded[bank]++;
                continue;
            }
            place q = p;
            q.address = (uint16_t)(p.address + i);
            const uint32_t *slot = names[phys_index(q)];
            if (slot[1] && slot[1] - 1 == vpage) {
                /* the second name of a shared page ($E1 after $01):
                   the screen of bank $E1 wins where they differ */
                if (*storage_of(q) != value) {
                    aliased++;
                    *storage_of(q) = value;
                }
                continue;
            }
            *storage_of(q) = value;
            loaded += value != 0;
        }
    }
    ref_read = ref.cpu.read;
    ref_write = ref.cpu.write;
    ref_context = ref.cpu.context;
    ref.cpu.read = observed_read;
    ref.cpu.write = observed_write;
    ref.cpu.context = &ref;
}

/* ---- the interpreter's registers ---- */

typedef struct {
    uint16_t pc, s, a, x, y, d;
    uint8_t p, dbr, pbr, e, state;
} regs;

static regs interpreter_regs(void)
{
    regs r;
    uint8_t p = *main_at(SYM(S_VC)) | *main_at(SYM(S_VP));
    uint8_t mx = *main_at(SYM(S_VMX));
    if (!*main_at(SYM(S_VZ)))
        p |= 0x02;
    if (mx & 0x80)
        p |= 0x20;
    if (mx & 0x40)
        p |= 0x10;
    p |= *main_at(SYM(S_VN)) & 0x80;
    p |= *main_at(SYM(S_VV)) & 0x40;
    r.p = p;
    r.pc = (uint16_t)((*main_at(SYM(S_VPCH)) << 8 | *main_at(SYM(S_VPCL))) +
                      1);
    r.a = get_word(SYM(S_A));
    r.x = get_word(SYM(S_X));
    r.y = get_word(SYM(S_Y));
    r.s = get_word(SYM(S_S));
    r.d = get_word(SYM(S_D));
    r.dbr = *main_at(SYM(S_DBR));
    r.pbr = *main_at(SYM(S_PBR));
    r.e = *main_at(SYM(S_E));
    r.state = *main_at(SYM(S_STATE));
    return r;
}

static regs reference_regs(void)
{
    const cpu816 *c = &ref.cpu;
    regs r = { c->pc, c->s, c->a, c->x, c->y, c->d, c->p, c->dbr, c->pbr,
               c->e, (uint8_t)c->state };
    return r;
}

static int compare_regs(const regs *have, const regs *want, char *why,
                        size_t size)
{
#define CHECK(name, member) \
    if (have->member != want->member) { \
        snprintf(why, size, "%s is %04x, the reference has %04x", name, \
                 (unsigned)have->member, (unsigned)want->member); \
        return 0; }
    CHECK("PC", pc) CHECK("PBR", pbr) CHECK("S", s) CHECK("A", a)
    CHECK("X", x) CHECK("Y", y) CHECK("D", d) CHECK("P", p)
    CHECK("DBR", dbr) CHECK("E", e) CHECK("the run state", state)
#undef CHECK
    return 1;
}

static int by_write(const void *a, const void *b)
{
    const vwrite *x = a, *y = b;
    if (x->address != y->address)
        return (x->address > y->address) - (x->address < y->address);
    return (x->value > y->value) - (x->value < y->value);
}

/* The interpreter's writes against the reference's, as multisets. */
static int compare_writes(char *why, size_t size)
{
    vwrite mine[MAX_WRITES], theirs[MAX_WRITES];
    if (*stray) {
        snprintf(why, size, "%s", stray);
        return 0;
    }
    if (rwrite_lost) {
        snprintf(why, size, "more than %d writes in one instruction",
                 MAX_WRITES);
        return 0;
    }
    /* the name the reference used, of the two a shared page has */
    for (unsigned i = 0; i < iwrite_count; i++) {
        mine[i] = iwrites[i];
        for (unsigned j = 0; j < rwrite_count; j++)
            if (mine[i].other == rwrites[j].address) {
                mine[i].address = mine[i].other;
                break;
            }
        mine[i].other = UINT32_MAX;
    }
    memcpy(theirs, rwrites, rwrite_count * sizeof *theirs);
    qsort(mine, iwrite_count, sizeof *mine, by_write);
    qsort(theirs, rwrite_count, sizeof *theirs, by_write);
    for (unsigned i = 0; i < iwrite_count || i < rwrite_count; i++) {
        if (i >= iwrite_count) {
            snprintf(why, size, "the reference wrote $%02x to $%06" PRIx32
                     ", the interpreter did not", theirs[i].value,
                     theirs[i].address);
            return 0;
        }
        if (i >= rwrite_count || mine[i].address != theirs[i].address ||
            mine[i].value != theirs[i].value) {
            snprintf(why, size, "the interpreter wrote $%02x to $%06"
                     PRIx32 ", the reference did not", mine[i].value,
                     mine[i].address);
            return 0;
        }
    }
    return 1;
}

/* One step of the reference: returns 1 when it executed an instruction
   (and not an interrupt entry or a firmware call). */
static int reference_step(void)
{
    uint64_t before = ref.instructions;
    rwrite_count = rwrite_lost = 0;
    first_special = A_NONE;
    iigs_run(&ref, ref.cpu.cycles + 1, UINT64_MAX);
    return ref.instructions == before + 1;
}

/* ---- cost accounting ---- */

typedef struct {
    uint32_t *cycles, *clocks;
    size_t count, capacity;
} bucket;

static bucket buckets[256 * 8];         /* opcode << 3 | E << 2 | M << 1 | X */

static void bucket_add(unsigned key, uint32_t cycles, uint32_t clocks)
{
    bucket *b = &buckets[key];
    if (b->count == b->capacity) {
        b->capacity = b->capacity ? 2 * b->capacity : 256;
        b->cycles = realloc(b->cycles, b->capacity * sizeof *b->cycles);
        b->clocks = realloc(b->clocks, b->capacity * sizeof *b->clocks);
        if (!b->cycles || !b->clocks)
            fail("out of memory", NULL);
    }
    b->cycles[b->count] = cycles;
    b->clocks[b->count++] = clocks;
}

static int by_value(const void *a, const void *b)
{
    uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
    return (x > y) - (x < y);
}

static void json_stats(FILE *out, uint32_t *values, size_t n)
{
    uint64_t sum = 0;
    qsort(values, n, sizeof *values, by_value);
    for (size_t i = 0; i < n; i++)
        sum += values[i];
    fprintf(out, "[%" PRIu32 ", %" PRIu32 ", %" PRIu32 ", %" PRIu64 "]",
            values[0], values[(n - 1) / 2], values[n - 1], sum);
}

/* "buckets": [[opcode, e, m, x, count, [cycles: min, median, max, sum],
   [clocks: ...]], ...] */
static void json_buckets(FILE *out)
{
    int first = 1;
    fprintf(out, "  \"buckets\": [");
    for (unsigned key = 0; key < 256 * 8; key++) {
        bucket *b = &buckets[key];
        if (!b->count)
            continue;
        fprintf(out, "%s\n    [%u, %u, %u, %u, %zu, ", first ? "" : ",",
                key >> 3, key >> 2 & 1, key >> 1 & 1, key & 1, b->count);
        json_stats(out, b->cycles, b->count);
        fprintf(out, ", ");
        json_stats(out, b->clocks, b->count);
        fprintf(out, "]");
        first = 0;
        free(b->cycles);
        free(b->clocks);
        b->cycles = b->clocks = NULL;
        b->count = b->capacity = 0;
    }
    fprintf(out, "\n  ]");
}

static void json_cost_header(FILE *out)
{
    fprintf(out, "  \"cost_model\": %s,\n", m->cost ? "true" : "false");
    fprintf(out, "  \"fabric_mhz\": %.6f,\n",
            m->cost ? m->cost->p.fabric_mhz : 0.0);
}

/* ---- first contact ---- */

static void print_regs(FILE *out, const char *name, const regs *r)
{
    fprintf(out, "  \"%s\": {\"pc\": \"%02X:%04X\", \"a\": \"%04X\", "
            "\"x\": \"%04X\", \"y\": \"%04X\", \"s\": \"%04X\", \"d\": "
            "\"%04X\", \"dbr\": \"%02X\", \"p\": \"%02X\", \"e\": %u},\n",
            name, r->pbr, r->pc, r->a, r->x, r->y, r->s, r->d, r->dbr, r->p,
            r->e);
}

/* The whole mapped virtual memory against the reference's: the count of
   differing bytes by bank into `by_bank`. */
static uint64_t compare_memory(uint64_t by_bank[256])
{
    uint64_t total = 0;
    memset(by_bank, 0, 256 * sizeof *by_bank);
    for (uint32_t vpage = 0; vpage < 0x10000; vpage++) {
        place p = where(vpage << 8);
        if (p.kind < 0)
            continue;
        for (unsigned i = 0; i < 256; i++) {
            place q = p;
            q.address = (uint16_t)(p.address + i);
            if (*storage_of(q) != iigs_peek(&ref, vpage << 8 | i)) {
                by_bank[vpage >> 8]++;
                total++;
            }
        }
    }
    return total;
}

static void json_banks(FILE *out, const char *name, const uint64_t *counts,
                       int last)
{
    int first = 1;
    fprintf(out, "  \"%s\": {", name);
    for (unsigned b = 0; b < 256; b++)
        if (counts[b]) {
            fprintf(out, "%s\"%02X\": %" PRIu64, first ? "" : ", ", b,
                    counts[b]);
            first = 0;
        }
    fprintf(out, "}%s\n", last ? "" : ",");
}

static int contact(const char *image, uint64_t limit)
{
    image_header h;
    char why[240] = "";
    const char *reason = NULL;
    uint64_t identical = 0, cycles_prev = 0, clocks_prev = 0;
    uint64_t start_diff[256], end_diff[256], start_total, end_total;
    uint64_t total_cycles = 0, total_clocks = 0;
    uint64_t measured_cycles = 0, measured_clocks = 0;
    unsigned long idle = 0;
    int arrived = 0, trapped = 0;
    regs before_ref, at_stop_ref, at_stop_mine;
    unsigned stop_opcode = 0;

    build_map(0);
    build_names();
    load_image(image, &h);
    start_total = compare_memory(start_diff);

    put_word(SYM(S_A), h.a);
    put_word(SYM(S_X), h.x);
    put_word(SYM(S_Y), h.y);
    put_word(SYM(S_S), h.s);
    put_word(SYM(S_D), h.d);
    *main_at(SYM(S_DBR)) = h.dbr;
    *main_at(SYM(S_PBR)) = h.pbr;
    *main_at(SYM(S_E)) = h.e;
    *main_at(SYM(S_P)) = h.p;
    put_word(SYM(S_PC), h.pc);
    *main_at(SYM(S_EVENT)) = 0;

    m->write_hook = on_write;
    m->cpu.s = 0xff;
    m->cpu.pc = STUB_RUN;
    m->cpu.state = CPU65C02_RUNNING;
    before_ref = reference_regs();
    for (;;) {
        uint16_t pc = m->cpu.pc;
        if (pc == SYM(S_LOOP) || pc == STUB_RUN_RETURN) {
            idle = 0;
            if (pc == STUB_RUN_RETURN)
                trapped = 1;
            if (arrived || trapped) {
                uint32_t at = (uint32_t)ref.cpu.pbr << 16 | ref.cpu.pc;
                unsigned opcode = iigs_peek(&ref, at);
                unsigned key = opcode << 3 | ref.cpu.e << 2 |
                               (ref.cpu.p >> 4 & 3);
                before_ref = reference_regs();
                stop_opcode = opcode;
                if (!reference_step()) {
                    reason = "difference";
                    snprintf(why, sizeof why, "the reference did not run "
                             "an instruction (an interrupt or a firmware "
                             "call)");
                    break;
                }
                if (first_special != A_NONE) {
                    reason = first_special == A_IO ? "io" : "difference";
                    break;
                }
                if (trapped) {
                    reason = "difference";
                    snprintf(why, sizeof why, "the interpreter stopped with "
                             "status %u at $%06x; the reference made no I/O "
                             "access", *main_at(SYM(S_STATUS)),
                             (unsigned)(get_word(SYM(S_EA)) |
                                        *main_at(SYM(S_EA) + 2) << 16));
                    break;
                }
                regs mine = interpreter_regs(), theirs = reference_regs();
                if (!compare_regs(&mine, &theirs, why, sizeof why) ||
                    !compare_writes(why, sizeof why)) {
                    reason = "difference";
                    break;
                }
                bucket_add(key, (uint32_t)(m->cpu.cycles - cycles_prev),
                           (uint32_t)(clocks_now() - clocks_prev));
                measured_cycles += m->cpu.cycles - cycles_prev;
                measured_clocks += clocks_now() - clocks_prev;
                measure_commit();
                identical++;
                if (limit && identical >= limit) {
                    reason = "limit";
                    break;
                }
            }
            arrived = 1;
            cycles_prev = m->cpu.cycles;
            clocks_prev = clocks_now();
            measure_start();
            iwrite_count = 0;
            *stray = 0;
        }
        if (++idle > MAX_STEPS || m->cpu.state != CPU65C02_RUNNING) {
            reason = "difference";
            snprintf(why, sizeof why, "the interpreter ran away (65C02 at "
                     "$%04x)", m->cpu.pc);
            break;
        }
        measured_step();
    }
    total_cycles = m->cpu.cycles;
    total_clocks = clocks_now();
    at_stop_ref = reference_regs();
    at_stop_mine = interpreter_regs();
    m->write_hook = NULL;
    end_total = compare_memory(end_diff);

    FILE *out = stdout;
    fprintf(out, "{\n  \"format\": \"game816-contact 1\",\n");
    fprintf(out, "  \"map_banks\": %u,\n", banks_used);
    fprintf(out, "  \"loaded_nonzero_bytes\": %" PRIu64 ",\n", loaded);
    fprintf(out, "  \"aliased_bytes\": %" PRIu64 ",\n", aliased);
    json_banks(out, "unloaded_nonzero_bytes", unloaded, 0);
    fprintf(out, "  \"identical\": %" PRIu64 ",\n", identical);
    fprintf(out, "  \"stop\": \"%s\",\n", reason);
    fprintf(out, "  \"why\": \"%s\",\n", why);
    print_regs(out, "reference_before", &before_ref);
    fprintf(out, "  \"stop_opcode\": \"%02X\",\n", stop_opcode);
    if (first_special != A_NONE)
        fprintf(out, "  \"reference_access\": {\"kind\": \"%s\", "
                "\"address\": \"%06X\", \"write\": %s},\n",
                SPECIAL_NAMES[first_special], (unsigned)special_address,
                special_write ? "true" : "false");
    fprintf(out, "  \"interpreter_status\": %u,\n",
            trapped ? *main_at(SYM(S_STATUS)) : 0);
    fprintf(out, "  \"interpreter_trap_address\": \"%06X\",\n",
            trapped ? (unsigned)(get_word(SYM(S_EA)) |
                                 *main_at(SYM(S_EA) + 2) << 16) : 0);
    print_regs(out, "reference_at_stop", &at_stop_ref);
    print_regs(out, "interpreter_at_stop", &at_stop_mine);
    fprintf(out, "  \"memory_differences_at_start\": %" PRIu64 ",\n",
            start_total);
    json_banks(out, "memory_differences_at_start_by_bank", start_diff, 0);
    fprintf(out, "  \"memory_differences_at_stop\": %" PRIu64 ",\n",
            end_total);
    json_banks(out, "memory_differences_at_stop_by_bank", end_diff, 0);
    json_cost_header(out);
    json_parts(out);
    fprintf(out, "  \"cycles\": %" PRIu64 ",\n  \"clocks\": %" PRIu64 ",\n",
            total_cycles, total_clocks);
    fprintf(out, "  \"cycles_measured\": %" PRIu64 ",\n  \"clocks_measured\": %"
            PRIu64 ",\n", measured_cycles, measured_clocks);
    json_buckets(out);
    fprintf(out, "\n}\n");

    /* An I/O access where the interpreter trapped at the same address is
       the expected end; anything else but the limit is a difference. */
    if (reason && !strcmp(reason, "io")) {
        int same = trapped && (uint32_t)(get_word(SYM(S_EA)) |
                                         *main_at(SYM(S_EA) + 2) << 16) ==
                              special_address;
        if (!same) {
            fprintf(stderr, "game816: the reference accessed I/O at $%06X, "
                    "but the interpreter %s\n", (unsigned)special_address,
                    trapped ? "trapped elsewhere" : "did not trap");
            return 1;
        }
        return end_total == start_total ? 0 : 1;
    }
    return reason && !strcmp(reason, "limit") && end_total == start_total
               ? 0 : 1;
}

/* ---- samples ---- */

/* A sample of tools/ref816's trace (trace.h, "Samples"): one instruction
   of the game, with every byte it read and wrote. */
enum { SAMPLE_ACCESSES = 64, SAMPLE_PREVIOUS = 8, PHASES = 16,
       STUB_BANK = 0x0380 };

typedef struct {
    unsigned phase;
    regs before, after;
    uint32_t previous[SAMPLE_PREVIOUS];
    unsigned previous_count;
    struct { uint32_t address; uint8_t value, write; char space[8]; }
        access[SAMPLE_ACCESSES];
    unsigned accesses;
} sample;

typedef enum { SK_IO, SK_UNMAPPED, SK_ALIASED, SK_UNSTABLE, SK_COUNT }
    skip_reason;

static const char *const SKIP_NAMES[SK_COUNT] = {
    "io", "unmapped", "aliased", "unstable"
};

static int parse_regs(const char *text, regs *r, int with_state)
{
    unsigned pc, a, x, y, s, d, dbr, p, e, state = 0;
    int n = sscanf(text, "%x %x %x %x %x %x %x %x %u %u", &pc, &a, &x, &y,
                   &s, &d, &dbr, &p, &e, &state);
    if (n != (with_state ? 10 : 9))
        return 0;
    r->pc = (uint16_t)pc;
    r->pbr = (uint8_t)(pc >> 16);
    r->a = (uint16_t)a;
    r->x = (uint16_t)x;
    r->y = (uint16_t)y;
    r->s = (uint16_t)s;
    r->d = (uint16_t)d;
    r->dbr = (uint8_t)dbr;
    r->p = (uint8_t)p;
    r->e = (uint8_t)e;
    r->state = (uint8_t)state;
    return 1;
}

/* The next sample of `file`: 1, 0 at the end, or fails. */
static int read_sample(FILE *file, const char *path, sample *sm)
{
    char line[256];
    int have = 0;
    while (fgets(line, sizeof line, file)) {
        char kind = line[0];
        if (kind == 's') {
            unsigned phase;
            if (sscanf(line + 2, "%u", &phase) != 1 || phase >= PHASES ||
                !parse_regs(strchr(line + 2, ' ') + 1, &sm->before, 0))
                fail(path, "a bad s line");
            sm->phase = phase;
            sm->accesses = sm->previous_count = 0;
            have = 1;
        } else if (kind == 'p' && have) {
            char *at = line + 1;
            unsigned value;
            int used;
            while (sm->previous_count < SAMPLE_PREVIOUS &&
                   sscanf(at, " %x%n", &value, &used) == 1) {
                sm->previous[sm->previous_count++] = value;
                at += used;
            }
        } else if ((kind == 'r' || kind == 'w') && have) {
            unsigned address, value;
            if (sm->accesses == SAMPLE_ACCESSES)
                fail(path, "a sample with too many accesses");
            if (sscanf(line + 2, "%x %x %7s", &address, &value,
                       sm->access[sm->accesses].space) != 3)
                fail(path, "a bad access line");
            sm->access[sm->accesses].address = address;
            sm->access[sm->accesses].value = (uint8_t)value;
            sm->access[sm->accesses++].write = kind == 'w';
        } else if (kind == 'a' && have) {
            if (!parse_regs(line + 2, &sm->after, 1))
                fail(path, "a bad a line");
            return 1;
        } else if (!strncmp(line, "end", 3) ||
                   !strncmp(line, "ref816-samples", 14))
            continue;
        else
            fail(path, "an unknown line");
    }
    if (have)
        fail(path, "a sample is cut short");
    return 0;
}

/* Put the bytes the sample reads into virtual memory: SK_COUNT when it
   can run, or why it cannot. */
static skip_reason load_sample(const sample *sm)
{
    static struct { uint32_t address; uint8_t value, read_first; }
        set[SAMPLE_ACCESSES];
    unsigned n = 0;

    for (unsigned i = 0; i < sm->accesses; i++) {
        uint32_t address = sm->access[i].address;
        uint8_t value = sm->access[i].value;
        unsigned j;
        if (!strcmp(sm->access[i].space, "io"))
            return SK_IO;
        if (where(address).kind < 0)
            return SK_UNMAPPED;
        for (j = 0; j < n && set[j].address != address; j++)
            ;
        if (j == n) {
            /* the first access: a read gives the byte its value */
            set[n].address = address;
            set[n].value = value;
            set[n++].read_first = !sm->access[i].write;
        } else if (!sm->access[i].write && set[j].value != value)
            return SK_UNSTABLE;     /* a read that does not give back
                                       what the byte holds */
        else
            set[j].value = value;
    }
    for (unsigned i = 0; i < n; i++) {
        uint8_t first = 0;
        if (!set[i].read_first)
            continue;
        for (unsigned k = 0; k < sm->accesses; k++)
            if (sm->access[k].address == set[i].address) {
                first = sm->access[k].value;
                break;
            }
        /* two names of one byte ($01 and $E1) read with two values */
        for (unsigned j = 0; j < i; j++) {
            place a = where(set[i].address), b = where(set[j].address);
            if (set[j].read_first && a.kind == b.kind && a.bank == b.bank &&
                a.address == b.address &&
                *storage_of(b) != first)
                return SK_ALIASED;
        }
        *storage_of(where(set[i].address)) = first;
    }
    return SK_COUNT;
}

/* The writes of a sample against the interpreter's, as multisets. */
static void sample_writes(const sample *sm)
{
    rwrite_count = rwrite_lost = 0;
    for (unsigned i = 0; i < sm->accesses; i++)
        if (sm->access[i].write && rwrite_count < MAX_WRITES) {
            rwrites[rwrite_count].address = sm->access[i].address;
            rwrites[rwrite_count].other = UINT32_MAX;
            rwrites[rwrite_count++].value = sm->access[i].value;
        }
}

/* The RamWorks bank of the latest of the sample's previous accesses that
   the map puts in RamWorks, or -1: the bank the interpreter's far layer
   would have selected last when it reached this instruction. */
static int previous_bank(const sample *sm)
{
    for (unsigned i = 0; i < sm->previous_count; i++) {
        place p = where(sm->previous[i]);
        if (p.kind == 1)
            return (int)p.bank;
    }
    return -1;
}

static uint16_t run_until(const uint16_t *stops, unsigned n)
{
    unsigned long count = 0;
    for (;;) {
        for (unsigned i = 0; i < n; i++)
            if (m->cpu.pc == stops[i])
                return stops[i];
        if (++count > MAX_STEPS || m->cpu.state != CPU65C02_RUNNING)
            return 0;
        a2vm_step(m);
        host_steps++;
    }
}

/* Does the sample fetch program bytes from two pages? */
static int crosses_pages(const sample *sm)
{
    uint32_t page = UINT32_MAX;
    for (unsigned i = 0; i < sm->accesses; i++)
        if (!sm->access[i].write && !strcmp(sm->access[i].space, "program")) {
            uint32_t this_page = sm->access[i].address >> 8;
            if (page != UINT32_MAX && this_page != page)
                return 1;
            page = this_page;
        }
    return 0;
}

static void set_regs(const regs *r)
{
    put_word(SYM(S_A), r->a);
    put_word(SYM(S_X), r->x);
    put_word(SYM(S_Y), r->y);
    put_word(SYM(S_S), r->s);
    put_word(SYM(S_D), r->d);
    *main_at(SYM(S_DBR)) = r->dbr;
    *main_at(SYM(S_PBR)) = r->pbr;
    *main_at(SYM(S_E)) = r->e;
    *main_at(SYM(S_P)) = r->p;
    put_word(SYM(S_PC), r->pc);
    *main_at(SYM(S_EVENT)) = 0;
}

/* run_until, the steps measured. */
static uint16_t run_measured(const uint16_t *stops, unsigned n)
{
    unsigned long count = 0;
    for (;;) {
        for (unsigned i = 0; i < n; i++)
            if (m->cpu.pc == stops[i])
                return stops[i];
        if (++count > MAX_STEPS || m->cpu.state != CPU65C02_RUNNING)
            return 0;
        measured_step();
    }
}

typedef struct {
    uint64_t count, cycles, clocks;
} phase_sum;

/*
 * samples: each sample of FILE (tools/ref816's --trace-samples) runs as
 * one instruction on the interpreter, with the game's map built with
 * every bank below $40 (the banks ARCHITECTURE.md 3.3 leaves out too, so
 * that the multiply's quarter squares can be read). The bytes the
 * instruction read on the reference are put where the map puts them, the
 * registers are set, and the instruction runs through vm_run as in
 * vm816's --cost: from the arrival of the dispatch loop at `fetch` (the
 * code page is loaded first, cold, since each sample starts with
 * vm_flush) to the next arrival at `fetch` or `service`. Before the
 * measure starts, the far layer's bank ($C073 and curbank) is set, by a
 * stub of the 65C02, to the one the latest RamWorks access among the
 * sample's previous accesses selected, as a run of the game would have
 * left it. Then the registers and the writes are compared with the
 * reference's (the writes as multisets of virtual address and value).
 * A sample is skipped, and counted by reason, when it touches the I/O
 * space ("io"), memory the map leaves out ("unmapped"), both names of a
 * shared byte with two values ("aliased"), or reads one byte twice with
 * two values ("unstable"). Since the samples are every Nth instruction,
 * their mean cost is the cost weighted by the game's own mix, with the
 * addresses it really uses.
 */
static int samples_run(const char *path, unsigned show)
{
    FILE *file = fopen(path, "r");
    static sample sm;
    phase_sum phases[PHASES];
    uint64_t skipped[SK_COUNT] = { 0 }, unmapped_banks[256] = { 0 };
    /* the first unmapped access of each skipped sample, by page, space
       and direction, with the first instruction that made it */
    static struct { uint32_t page, pc; char space[8]; uint8_t write;
                    uint64_t count; } holes[1024];
    unsigned hole_count = 0;
    uint64_t total = 0, measured = 0, failures = 0, warmed = 0;
    uint16_t first[3] = { (uint16_t)SYM(S_FETCH), STUB_RUN_RETURN,
                          STUB_WARM_RETURN };
    uint16_t next[4] = { (uint16_t)SYM(S_FETCH), (uint16_t)SYM(S_SERVICE),
                         STUB_RUN_RETURN, STUB_WARM_RETURN };
    char why[240];

    if (!file)
        fail(path, strerror(errno));
    memset(phases, 0, sizeof phases);
    build_map(1);
    build_names();
    exclude_pages = 1;
    /* The bank stub: LDA #bank, STA curbank, STA $C073, JMP fetch. */
    *main_at(STUB_BANK) = 0xa9;
    *main_at(STUB_BANK + 2) = 0x85;
    *main_at(STUB_BANK + 3) = (uint8_t)SYM(S_CURBANK);
    *main_at(STUB_BANK + 4) = 0x8d;
    put_word(STUB_BANK + 5, 0xc073);
    *main_at(STUB_BANK + 7) = 0x4c;
    put_word(STUB_BANK + 8, (uint16_t)SYM(S_FETCH));
    m->write_hook = on_write;

    printf("{\n  \"format\": \"game816-samples 1\",\n");
    printf("  \"map_banks\": %u,\n  \"failures_shown\": [", banks_used);
    while (read_sample(file, path, &sm)) {
        uint32_t opcode = 0;
        skip_reason reason;
        uint64_t cycles0, clocks0;
        int bank;

        total++;
        m->write_hook = NULL;
        reason = load_sample(&sm);
        m->write_hook = on_write;
        if (reason != SK_COUNT) {
            skipped[reason]++;
            if (reason == SK_UNMAPPED)
                for (unsigned i = 0; i < sm.accesses; i++)
                    if (where(sm.access[i].address).kind < 0) {
                        uint32_t page = sm.access[i].address >> 8;
                        unsigned h;
                        unmapped_banks[page >> 8]++;
                        for (h = 0; h < hole_count; h++)
                            if (holes[h].page == page &&
                                holes[h].write == sm.access[i].write &&
                                !strcmp(holes[h].space,
                                        sm.access[i].space))
                                break;
                        if (h == hole_count && hole_count < 1024) {
                            holes[h].page = page;
                            holes[h].write = sm.access[i].write;
                            holes[h].pc = (uint32_t)sm.before.pbr << 16 |
                                          sm.before.pc;
                            snprintf(holes[h].space, sizeof holes[h].space,
                                     "%s", sm.access[i].space);
                            holes[h].count = 0;
                            hole_count++;
                        }
                        if (h < hole_count)
                            holes[h].count++;
                        break;
                    }
            continue;
        }
        opcode = sm.access[0].value;
        *why = 0;
        if (crosses_pages(&sm) || !(sm.before.pc & 0xff)) {
            /* The instruction's bytes are in two pages, or it starts a
               page (its fetch moves to the page from the one before): a
               first run loads the pages into the cache, unmeasured, so
               that the measured one does not copy a cold page, which it
               would do only because every sample starts cold. */
            set_regs(&sm.before);
            m->cpu.s = 0xff;
            m->cpu.pc = STUB_RUN;
            m->cpu.state = CPU65C02_RUNNING;
            if (run_until(first, 3) != SYM(S_FETCH)) {
                snprintf(why, sizeof why, "the code page did not load");
                goto failed;
            }
            a2vm_step(m);
            host_steps++;
            if (run_until(next, 4) == 0) {
                snprintf(why, sizeof why, "the interpreter ran away");
                goto failed;
            }
            m->write_hook = NULL;
            load_sample(&sm);
            m->write_hook = on_write;
            warmed++;
        }
        set_regs(&sm.before);
        m->cpu.s = 0xff;
        m->cpu.pc = crosses_pages(&sm) || !(sm.before.pc & 0xff)
                        ? STUB_WARM : STUB_RUN;
        m->cpu.state = CPU65C02_RUNNING;
        if (run_until(first, 3) != SYM(S_FETCH)) {
            snprintf(why, sizeof why, "the code page did not load");
            goto failed;
        }
        bank = previous_bank(&sm);
        if (bank >= 0 && bank != *main_at(SYM(S_CURBANK))) {
            *main_at(STUB_BANK + 1) = (uint8_t)bank;
            m->cpu.pc = STUB_BANK;
            if (run_until(first, 1) != SYM(S_FETCH)) {
                snprintf(why, sizeof why, "the bank stub ran away");
                goto failed;
            }
        }
        iwrite_count = 0;
        *stray = 0;
        cycles0 = m->cpu.cycles;
        clocks0 = clocks_now();
        measure_start();
        measured_step();
        switch (run_measured(next, 4)) {
        case 0:
            snprintf(why, sizeof why, "the interpreter ran away");
            goto failed;
        case STUB_RUN_RETURN:
        case STUB_WARM_RETURN:
            snprintf(why, sizeof why, "the interpreter stopped with status "
                     "%u at $%06x", *main_at(SYM(S_STATUS)),
                     (unsigned)(get_word(SYM(S_EA)) |
                                *main_at(SYM(S_EA) + 2) << 16));
            goto failed;
        default:
            break;
        }
        {
            /* less the lookup of a page the fetch entered, which the
               model of the code cache counts */
            uint32_t cycles = (uint32_t)(m->cpu.cycles - cycles0 -
                                         pending_page[0]);
            uint32_t clocks = (uint32_t)(clocks_now() - clocks0 -
                                         pending_page[1]);
            regs mine = interpreter_regs();
            sample_writes(&sm);
            if (!compare_regs(&mine, &sm.after, why, sizeof why) ||
                !compare_writes(why, sizeof why))
                goto failed;
            bucket_add(opcode << 3 | sm.before.e << 2 |
                       (sm.before.p >> 4 & 3), cycles, clocks);
            measure_commit();
            phases[sm.phase].count++;
            phases[sm.phase].cycles += cycles;
            phases[sm.phase].clocks += clocks;
            measured++;
        }
        continue;
failed:
        if (failures < show)
            printf("%s\n    {\"pc\": \"%02X:%04X\", \"opcode\": \"%02X\", "
                   "\"why\": \"%s\"}", failures ? "," : "", sm.before.pbr,
                   sm.before.pc, opcode, why);
        failures++;
    }
    fclose(file);
    m->write_hook = NULL;
    printf("\n  ],\n  \"samples\": %" PRIu64 ",\n  \"measured\": %" PRIu64
           ",\n  \"failures\": %" PRIu64 ",\n  \"warmed\": %" PRIu64
           ",\n  \"skipped\": {", total, measured, failures, warmed);
    for (unsigned k = 0; k < SK_COUNT; k++)
        printf("%s\"%s\": %" PRIu64, k ? ", " : "", SKIP_NAMES[k],
               skipped[k]);
    printf("},\n");
    json_banks(stdout, "unmapped_by_bank", unmapped_banks, 0);
    /* "unmapped": [[page (bank and page), space, write, count, pc], ...] */
    printf("  \"unmapped\": [");
    for (unsigned h = 0; h < hole_count; h++)
        printf("%s\n    [\"%04X\", \"%s\", %u, %" PRIu64 ", \"%06X\"]",
               h ? "," : "", (unsigned)holes[h].page, holes[h].space,
               holes[h].write, holes[h].count, (unsigned)holes[h].pc);
    printf("\n  ],\n");
    printf("  \"phases\": {");
    for (unsigned p = 0, first_phase = 1; p < PHASES; p++)
        if (phases[p].count) {
            printf("%s\"%u\": [%" PRIu64 ", %" PRIu64 ", %" PRIu64 "]",
                   first_phase ? "" : ", ", p, phases[p].count,
                   phases[p].cycles, phases[p].clocks);
            first_phase = 0;
        }
    printf("},\n");
    json_cost_header(stdout);
    json_parts(stdout);
    json_buckets(stdout);
    printf("\n}\n");
    return failures ? 1 : 0;
}

/* ---- the code page cache ---- */

/*
 * pages: what a change of code page costs. A loop of JMP abs in bank $03
 * (a flat granule of the game's map) runs through vm_run, and the time
 * from one arrival of the dispatch loop at `loop` to the next is summed
 * over PAGE_RUNS instructions, after a first pass over the loop: jumps
 * within one page (no change); a ring of PAGE_FEW pages, as many as the
 * cache has slots, which it keeps (every change hits, and the lookup
 * finds the page on average half-way through the slots, as it would
 * with a full cache); a ring of PAGE_MANY, more than its slots (it fills
 * them in turn, so every change misses and copies a page).
 * The jumps go to the middle of each page: a jump to the first byte of a
 * page takes the event service even within one page, since the stored
 * program counter (less one) is then in the page before.
 */
enum { PAGE_RUNS = 4000, PAGE_FEW = 16, PAGE_MANY = 20, PAGE_BASE = 0x1080 };

static void page_ring(unsigned pages, uint64_t out[3])
{
    uint64_t cycles_prev = 0, clocks_prev = 0;
    unsigned long arrivals = 0, warm = 2 * pages + 2, idle = 0;

    for (unsigned k = 0; k < pages; k++) {
        uint32_t at = 0x030000 | (PAGE_BASE + 0x100 * k);
        uint16_t next = (uint16_t)(PAGE_BASE + 0x100 * ((k + 1) % pages));
        place p = where(at);
        if (p.kind != 1)
            fail("bank $03 is not in RamWorks", NULL);
        storage_of(p)[0] = 0x4c;
        storage_of(p)[1] = (uint8_t)next;
        storage_of(p)[2] = (uint8_t)(next >> 8);
    }
    put_word(SYM(S_A), 0);
    put_word(SYM(S_X), 0);
    put_word(SYM(S_Y), 0);
    put_word(SYM(S_S), 0x3fff);
    put_word(SYM(S_D), 0x0900);
    *main_at(SYM(S_DBR)) = 0x02;
    *main_at(SYM(S_PBR)) = 0x03;
    *main_at(SYM(S_E)) = 0;
    *main_at(SYM(S_P)) = 0x04;
    put_word(SYM(S_PC), PAGE_BASE);
    *main_at(SYM(S_EVENT)) = 0;
    m->cpu.s = 0xff;
    m->cpu.pc = STUB_RUN;
    m->cpu.state = CPU65C02_RUNNING;
    out[0] = out[1] = out[2] = 0;
    while (out[0] < PAGE_RUNS) {
        if (m->cpu.pc == SYM(S_LOOP)) {
            if (arrivals > warm) {
                out[0]++;
                out[1] += m->cpu.cycles - cycles_prev;
                out[2] += clocks_now() - clocks_prev;
            }
            arrivals++;
            idle = 0;
            cycles_prev = m->cpu.cycles;
            clocks_prev = clocks_now();
        }
        if (m->cpu.pc == STUB_RUN_RETURN || ++idle > MAX_STEPS)
            fail("the page loop stopped", NULL);
        a2vm_step(m);
        host_steps++;
    }
}

static int pages_run(void)
{
    static const struct { const char *name; unsigned pages; } rings[] = {
        { "same_page", 1 }, { "hit", PAGE_FEW }, { "miss", PAGE_MANY }
    };
    build_map(0);
    build_names();
    printf("{\n  \"format\": \"game816-pages 1\",\n");
    json_cost_header(stdout);
    printf("  \"slots\": %u,\n", (unsigned)SYM(S_NSLOT));
    for (size_t i = 0; i < sizeof rings / sizeof rings[0]; i++) {
        uint64_t out[3];
        page_ring(rings[i].pages, out);
        printf("  \"%s\": {\"pages\": %u, \"instructions\": %" PRIu64
               ", \"cycles\": %" PRIu64 ", \"clocks\": %" PRIu64 "}%s\n",
               rings[i].name, rings[i].pages, out[0], out[1], out[2],
               i + 1 < sizeof rings / sizeof rings[0] ? "," : "");
    }
    printf("}\n");
    return 0;
}

/* ---- the command line ---- */

int main(int argc, char **argv)
{
    const char *dir = "build/vm", *cost = NULL;
    uint64_t limit = 0;
    int i;

    for (i = 1; i + 1 < argc && argv[i][0] == '-'; i += 2) {
        if (!strcmp(argv[i], "--vm"))
            dir = argv[i + 1];
        else if (!strcmp(argv[i], "--cost"))
            cost = argv[i + 1];
        else if (!strcmp(argv[i], "--limit"))
            limit = strtoull(argv[i + 1], NULL, 10);
        else
            break;
    }
    if (i + 1 < argc && !strcmp(argv[i], "contact")) {
        setup(dir);
        attach_cost(cost);
        return contact(argv[i + 1], limit);
    }
    if (i < argc && !strcmp(argv[i], "pages")) {
        setup(dir);
        attach_cost(cost);
        return pages_run();
    }
    if (i + 1 < argc && !strcmp(argv[i], "samples")) {
        setup(dir);
        attach_cost(cost);
        return samples_run(argv[i + 1], 10);
    }
    fprintf(stderr, "usage: game816 [--vm DIR] [--cost PARAMS] [--limit N] "
            "contact IMAGE\n       game816 [--vm DIR] [--cost PARAMS] "
            "samples FILE\n       game816 [--vm DIR] [--cost PARAMS] "
            "pages\n");
    return 2;
}
