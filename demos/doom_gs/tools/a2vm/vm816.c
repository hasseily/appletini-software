/*
 * Runs the SingleStepTests 65816 vectors through the 65816 interpreter of
 * src/vm, on a2vm.
 *
 * usage: vm816 [--vm DIR] [--limit N] [--show N] FILE...
 *        vm816 [--vm DIR] [--limit N] --cost PARAMS OUT FILE...
 *        vm816 [--vm DIR] --lockstep SEED PROGRAMS STEPS BANKS
 *        vm816 [--vm DIR] --selftest
 *
 * DIR (default build/vm) holds the interpreter as src/vm/Makefile builds
 * it: vm.bin.d000, vm.bin.e000 and vm.bin.f000, loaded into the main
 * language card (bank 1 at $D000), and vm.lbl, the addresses of its
 * symbols. Each FILE is a vector file of tools/ref816/fetch_vectors.py;
 * --limit runs the first N cases of each file, --show prints the first N
 * failures of each kind in each file.
 *
 * The interpreter runs on the machine of a2vm.c with the exact W65C02S
 * core: its code in the language card, its state in main zero page, the
 * virtual 65816 memory where its map puts it. The harness only writes
 * the map, memory and the virtual registers, and calls the interpreter's
 * entry points through a stub in main RAM:
 *
 *   $0300  JSR vm_flush, JSR vm_import, JSR vm_step, JSR vm_export
 *   $0310  JSR vm_step, JSR vm_export       (the later steps of MVN, MVP)
 *
 * The map. The vectors' addresses cover the whole 24-bit space, and a
 * case touches a few half-banks of 32 KB. The harness maps the half-banks
 * each case lists (before or after) and leaves the rest unmapped ($FF),
 * so a stray access traps. Four half-banks go through page tables, as the
 * game's special banks will:
 *
 *   $00:0000-$7FFF  table 0: $0900-$0AFF in main $1400-$15FF and
 *                   $3000-$3FFF in main $6000-$6FFF (the game's direct
 *                   page and stack windows, ARCHITECTURE.md 3.3); the
 *                   other pages in RamWorks bank 127
 *   $00:8000-$FFFF  table 1: RamWorks bank 126
 *   $01:0000-$FFFF  tables 2 and 3: $0200-$BFFF in base aux memory,
 *                   identity (the game's SHR bank); the other pages in
 *                   RamWorks bank 125
 *
 * Every other listed half-bank is a flat granule in the next free bank of
 * 1-124.
 *
 * What is compared: the registers after the instruction, every RAM byte
 * the case lists after it, and every write the interpreter made. The
 * write hook of a2vm sees each CPU write: those to the interpreter's zero
 * page, its stack, its RAM and the code cache are its own; one to a
 * virtual location must be a byte the case lists; anything else (a
 * table, other main RAM, the language card, an I/O address but RAMRD,
 * RAMWRT and $C073) fails the case. Unlisted bytes read as zero, as in
 * tools/ref816/vectors.c. Cycles and the bus are not compared.
 *
 * MVN and MVP cases stop after 100 cycles: as tools/ref816/vectors.c
 * does, the interpreter runs the whole byte moves (7 cycles each on the
 * 65816) that fit in the record while the instruction repeats itself, and
 * the rest of the record must be the program fetches of the next step,
 * which advance PC.
 *
 * The known issues of the set are those of tools/ref816/vectors.c, with
 * the same rules: a case a rule picks is counted as known when it
 * differs, never silently skipped.
 *
 * Lockstep. The vectors test one instruction from a cold start; the
 * second form runs PROGRAMS random programs of up to STEPS steps each on
 * the interpreter and on the 65816 core of tools/ref816 (cpu816.c) side
 * by side, and compares the registers and the run state after every
 * step and all of memory at the end of each program. Memory is random
 * bytes, so the programs are random instruction streams: they change the
 * modes, jump across banks and pages, move blocks, write over the code
 * they run (through aliases too) and take BRK, COP, IRQ and NMI, whose
 * lines the harness raises at random steps. Every half-bank is mapped:
 * the four of the page tables as above, the others onto BANKS RamWorks
 * banks (1-124) in turn, so each physical page has several virtual
 * names; the reference core sees exactly the same aliasing. Few banks
 * make writes into cached code pages frequent. The run is a function of
 * SEED alone.
 *
 * Self test (--selftest): what neither reaches, because both run only
 * mapped memory one step at a time: the traps of an unmapped half-bank
 * and of an unmapped page in a page table (the game's I/O space) on a
 * read, a write and an instruction fetch, with the default handlers
 * (the step stops with the status) and with handlers that return (as
 * the platform layer's I/O emulation will); and vm_run, which runs until
 * a trap stops it. A fetch trap must leave the program counter the host
 * sees (vm_export) at the instruction, and a vm_run after it, with no
 * vm_import or vm_flush, must look the page up again: jumps to the middle
 * and to the first byte of an unmapped page, a fall-through into one, an
 * operand that runs into one, each run again, and a page mapped after
 * its trap (vm_flush, then vm_run from where the trap left the PC).
 *
 * Cost (--cost PARAMS OUT): what one interpreted instruction costs, case
 * by case, with the cost model of cost.h (PARAMS is a parameter file of
 * tools/a2vm/costs.py) beside the machine. Each case runs as above but
 * through vm_run instead of vm_step, and the harness watches the 65C02:
 * the instruction starts when the dispatch loop reaches `fetch` (after
 * the service of the page change that vm_import asks for, where the code
 * page is copied into the cache) and ends when it next reaches `fetch`
 * (the loop saw no event: LDA vm_event, BNE not taken) or `service` (the
 * instruction raised an event: a jump to another page, WAI, STP). So the
 * cost is that of the dispatch, the handler and the loop's test, as in a
 * run of many instructions, without the service of an event. The copy
 * of a cold code page stays out too, except in a case whose own fetch
 * enters the next page (its opcode at the first byte of a page, or its
 * operand running into the next one): its fetch then loads that page,
 * cold, since every case starts with vm_flush. The harness sees such a
 * case reach next_page and sets it apart. MVN and MVP are measured for
 * their first byte move. The harness then stops the 65C02 there, calls
 * vm_export and checks the registers and memory as above (not for MVN
 * and MVP, which are measured on one step only). OUT gets, for each
 * opcode, mode (E) and width (M, X), the count, minimum, lower median,
 * maximum and sum of 65C02 cycles (W65C02S bus cycles, one an access)
 * and of fabric clocks of the cost model, over every case and again over
 * the cases not set apart; tools/a2vm/interpreter_report.py reads it.
 * The cost model carries its state (TURBO caches, the RamWorks line
 * cache, the bus phase) from case to case.
 *
 * The exit status is 1 when any case, program or check fails.
 */
#include "a2vm.h"
#include "cost.h"
#include "cpu816.h"

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { PIN_VPA = 0x40, NULL_ADDRESS = 1 };
enum { STUB_FIRST = 0x0300, STUB_FIRST_END = 0x030C, STUB_NEXT = 0x0310,
       STUB_NEXT_END = 0x0316, STUB_INIT = 0x0320, STUB_INIT_END = 0x0323,
       STUB_RUN = 0x0330, STUB_RUN_END = 0x033C, TRAP_READ = 0x0340,
       TRAP_WRITE = 0x0348, TRAP_CELL = 0x0350, STUB_COST = 0x0360,
       STUB_COST_RUN_END = 0x0369, STUB_COST_END = 0x036C,
       STUB_EXPORT = 0x0370, STUB_EXPORT_END = 0x0373,
       STUB_FLUSH_RUN = 0x0380, STUB_RESUME = 0x0383,
       STUB_RESUME_END = 0x0389 };
enum { MAX_STEPS = 2000000, MAX_WRITES = 256, MVN_CYCLES = 7 };
enum { POOL_FIRST = 1, POOL_LAST = 124 };

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
    uint32_t *ram_before, *ram_after;
    cycle *cycles;
} vector;

/* ---- the interpreter's symbols ---- */

static struct {
    const char *name;
    uint32_t value;
} symbols[] = {
    { "vA", 0 }, { "vX", 0 }, { "vY", 0 }, { "vS", 0 }, { "vD", 0 },
    { "vDBR", 0 }, { "vPBR", 0 }, { "vE", 0 }, { "vm_p", 0 },
    { "vm_pc", 0 }, { "vm_status", 0 }, { "ea", 0 }, { "vm_init", 0 },
    { "vm_flush", 0 }, { "vm_import", 0 }, { "vm_export", 0 },
    { "vm_step", 0 }, { "map0", 0 }, { "map1", 0 }, { "watch", 0 },
    { "vm_trap_ex", 0 }, { "VM_PTAB", 0 }, { "VM_CACHE", 0 },
    { "VM_NSLOT", 0 }, { "VM_NPTAB", 0 }, { "vm_event", 0 },
    { "vm_state", 0 }, { "vm_run", 0 }, { "vm_trap_rd", 0 },
    { "vm_trap_wr", 0 }, { "fetch", 0 }, { "service", 0 },
    { "next_page", 0 },
};

enum { S_A, S_X, S_Y, S_S, S_D, S_DBR, S_PBR, S_E, S_P, S_PC, S_STATUS,
       S_EA, S_INIT, S_FLUSH, S_IMPORT, S_EXPORT, S_STEP, S_MAP0, S_MAP1,
       S_WATCH, S_TRAP_EX, S_PTAB, S_CACHE, S_NSLOT, S_NPTAB, S_EVENT,
       S_STATE, S_RUN, S_TRAP_RD, S_TRAP_WR, S_FETCH, S_SERVICE,
       S_NEXT_PAGE, S_COUNT };

#define SYM(i) (symbols[i].value)

static void load_symbols(const char *path)
{
    char line[256], name[128];
    unsigned value;
    FILE *file = fopen(path, "r");
    if (!file) {
        fprintf(stderr, "vm816: %s: %s\n", path, strerror(errno));
        exit(2);
    }
    while (fgets(line, sizeof line, file))
        if (sscanf(line, "al %x .%127s", &value, name) == 2)
            for (size_t i = 0; i < S_COUNT; i++)
                if (!strcmp(symbols[i].name, name))
                    symbols[i].value = value;
    fclose(file);
    for (size_t i = 0; i < S_COUNT; i++)
        if (!symbols[i].value) {
            fprintf(stderr, "vm816: %s: no symbol %s\n", path,
                    symbols[i].name);
            exit(2);
        }
}

static uint8_t *read_file(const char *path, size_t *size)
{
    FILE *file = fopen(path, "rb");
    uint8_t *data;
    long length;

    if (!file || fseek(file, 0, SEEK_END) || (length = ftell(file)) < 0 ||
        fseek(file, 0, SEEK_SET)) {
        fprintf(stderr, "vm816: %s: %s\n", path, strerror(errno));
        exit(2);
    }
    data = malloc(length ? (size_t)length : 1);
    if (!data || fread(data, 1, (size_t)length, file) != (size_t)length) {
        fprintf(stderr, "vm816: %s: cannot read\n", path);
        exit(2);
    }
    fclose(file);
    *size = (size_t)length;
    return data;
}

/* ---- the machine ---- */

static a2vm *m;
static uint64_t steps_run;

/* The half-bank map as the harness keeps it: the physical bank of each
   flat granule it assigned, and the virtual page of each physical page
   (+1; 0 = none) for the write hook. */
static uint8_t owner_used[128][256];
static uint32_t owner_page[128][256];
static int16_t granule[512];
static uint8_t pool_next;

typedef struct {
    int kind;           /* 0 main, 1 aux bank, -1 unmapped */
    unsigned bank;
    uint16_t address;
} place;

static uint8_t *main_at(uint32_t address)
{
    return a2vm_storage(m, 0, 0, (uint16_t)address);
}

/* Where the interpreter's tables put virtual `address`: read from the
   tables in the machine's memory, independently of the interpreter. */
static place where(uint32_t address)
{
    place p = { -1, 0, 0 };
    unsigned bank = address >> 16 & 0xff, page = address >> 8 & 0xff;
    unsigned half = (bank * 2 + (page >> 7)) & 0xff;
    uint8_t entry = *main_at((bank & 0x80 ? SYM(S_MAP1) : SYM(S_MAP0)) +
                             half);
    uint8_t space, physical;

    if (entry == 0xff)
        return p;
    if (entry < 0x80) {
        space = entry;
        physical = (uint8_t)((page & 0x7f) + 0x40);
    } else {
        uint32_t table = SYM(S_PTAB) + 256u * (entry & 0x7f);
        space = *main_at(table + (page & 0x7f) * 2);
        physical = *main_at(table + (page & 0x7f) * 2 + 1);
        if (space == 0xff)
            return p;
    }
    p.kind = space == 0x80 ? 0 : 1;
    p.bank = space == 0x80 ? 0 : space;
    p.address = (uint16_t)(physical << 8 | (address & 0xff));
    return p;
}

static uint8_t *storage_of(place p)
{
    return a2vm_storage(m, p.kind, p.bank, p.address);
}

static void set_page_table(unsigned table, unsigned vpage, uint8_t space,
                           uint8_t physical)
{
    uint32_t at = SYM(S_PTAB) + 256u * table + (vpage & 0x7f) * 2;
    *main_at(at) = space;
    *main_at(at + 1) = physical;
    if (space != 0x80 && space != 0xff) {
        owner_used[space][physical] = 1;
        owner_page[space][physical] = 0;
    }
}

static void set_owner(place p, uint32_t vpage)
{
    if (p.kind == 1) {
        owner_used[p.bank][p.address >> 8] = 1;
        owner_page[p.bank][p.address >> 8] = vpage + 1;
    }
}

/* The fixed page tables (see the top of this file). */
static void fixed_tables(void)
{
    for (unsigned page = 0; page < 0x80; page++) {
        if (page == 0x09 || page == 0x0a)
            set_page_table(0, page, 0x80, (uint8_t)(page + 0x0b));
        else if (page >= 0x30 && page < 0x40)
            set_page_table(0, page, 0x80, (uint8_t)(page + 0x30));
        else
            set_page_table(0, page, 127, (uint8_t)(page + 0x40));
        set_page_table(1, page, 126, (uint8_t)(page + 0x40));
    }
    for (unsigned page = 0; page < 0x100; page++) {
        unsigned table = 2 + (page >> 7);
        if (page >= 0x02 && page < 0xc0)
            set_page_table(table, page, 0, (uint8_t)page);
        else
            set_page_table(table, page, 125,
                           (uint8_t)((page & 0x7f) + 0x40));
    }
    memset(main_at(SYM(S_MAP0)), 0xff, 256);
    memset(main_at(SYM(S_MAP1)), 0xff, 256);
    for (unsigned i = 0; i < 4; i++)
        *main_at(SYM(S_MAP0) + i) = (uint8_t)(0x80 + i);
    /* the owners of the fixed pages */
    for (uint32_t vpage = 0; vpage < 0x200; vpage++) {
        place p = where(vpage << 8);
        set_owner(p, vpage);
    }
    for (unsigned i = 0; i < 512; i++)
        granule[i] = -1;
    pool_next = POOL_FIRST;
}

static void map_half_bank(unsigned half)
{
    uint32_t base = (uint32_t)half << 15;
    if (half < 4 || granule[half] >= 0)
        return;
    if (pool_next > POOL_LAST) {
        fprintf(stderr, "vm816: more half-banks in a case than banks\n");
        exit(2);
    }
    granule[half] = pool_next;
    *main_at((half < 256 ? SYM(S_MAP0) : SYM(S_MAP1)) + (half & 0xff)) =
        pool_next;
    for (uint32_t vpage = 0; vpage < 0x80; vpage++)
        set_owner(where(base + (vpage << 8)), (base >> 8) + vpage);
    pool_next++;
}

static void unmap_all(void)
{
    for (unsigned half = 4; half < 512; half++)
        if (granule[half] >= 0) {
            unsigned bank = (unsigned)granule[half];
            *main_at((half < 256 ? SYM(S_MAP0) : SYM(S_MAP1)) +
                     (half & 0xff)) = 0xff;
            memset(owner_used[bank], 0, sizeof owner_used[bank]);
            granule[half] = -1;
        }
    pool_next = POOL_FIRST;
}

/* ---- the write hook ---- */

static uint32_t vwrites[MAX_WRITES];
static unsigned vwrite_count;
static char stray[160];
static int everything_mapped;           /* lockstep: all half-banks */

static void on_write(a2vm *machine, uint16_t address, uint8_t *storage,
                     uint8_t value)
{
    (void)value;
    if (!storage) {
        if ((address >= 0xc002 && address <= 0xc005) || address == 0xc073)
            return;
        if (!*stray)
            snprintf(stray, sizeof stray, "write to $%04x (I/O or a "
                     "write-protected page)", address);
        return;
    }
    if (storage >= machine->main && storage < machine->main + 0x10000) {
        uint32_t at = (uint32_t)(storage - machine->main);
        uint32_t ram_end = SYM(S_TRAP_EX) + 2;
        uint32_t cache_end = SYM(S_CACHE) + 256u * SYM(S_NSLOT);
        uint32_t virtual_address;
        if (at < 0x200 || (at >= SYM(S_WATCH) && at < ram_end) ||
            (at >= SYM(S_CACHE) && at < cache_end))
            return;
        if (at >= 0x1400 && at < 0x1600)
            virtual_address = at - 0x1400 + 0x0900;
        else if (at >= 0x6000 && at < 0x7000)
            virtual_address = at - 0x6000 + 0x3000;
        else {
            if (!*stray)
                snprintf(stray, sizeof stray, "write to main $%04" PRIx32
                         ", not virtual memory", at);
            return;
        }
        if (vwrite_count < MAX_WRITES)
            vwrites[vwrite_count++] = virtual_address;
        return;
    }
    if (storage >= machine->aux_banks &&
        storage < machine->aux_banks + (size_t)A2VM_MAX_BANKS *
                                           A2VM_BANK_SIZE) {
        size_t offset = (size_t)(storage - machine->aux_banks);
        unsigned bank = (unsigned)(offset >> 16);
        unsigned page = (unsigned)(offset >> 8 & 0xff);
        if (everything_mapped && owner_used[bank][page])
            return;
        if (owner_used[bank][page] && owner_page[bank][page]) {
            if (vwrite_count < MAX_WRITES)
                vwrites[vwrite_count++] =
                    (owner_page[bank][page] - 1) << 8 | (offset & 0xff);
            return;
        }
        if (!*stray)
            snprintf(stray, sizeof stray, "write to aux bank %u $%04zx, "
                     "which no mapped virtual page owns", bank,
                     offset & 0xffff);
        return;
    }
    if (!*stray)
        snprintf(stray, sizeof stray, "write to $%04x in the language "
                 "card", address);
}

/* Run the stub at `start` until the CPU reaches `end`. */
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
    steps_run += n;
    return 1;
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
    if (!m) {
        fprintf(stderr, "vm816: %s\n", error);
        exit(2);
    }
    for (size_t i = 0; i < sizeof parts / sizeof parts[0]; i++) {
        size_t size;
        uint8_t *data;
        snprintf(path, sizeof path, "%s/%s", dir, parts[i].suffix);
        data = read_file(path, &size);
        if (size > (size_t)(0x10000 - parts[i].at) ||
            (parts[i].kind == 3 && size > 0x1000)) {
            fprintf(stderr, "vm816: %s is too long\n", path);
            exit(2);
        }
        memcpy(a2vm_storage(m, parts[i].kind, 0, parts[i].at), data, size);
        free(data);
    }
    /* the language card: read, write-protected, bank 1 at $D000 */
    m->lc_read = 1;
    m->lc_write = 0;
    m->lc_bank2 = 0;
    a2vm_remap(m);

    put_jsr(STUB_FIRST, SYM(S_FLUSH));
    put_jsr(STUB_FIRST + 3, SYM(S_IMPORT));
    put_jsr(STUB_FIRST + 6, SYM(S_STEP));
    put_jsr(STUB_FIRST + 9, SYM(S_EXPORT));
    put_jsr(STUB_NEXT, SYM(S_STEP));
    put_jsr(STUB_NEXT + 3, SYM(S_EXPORT));
    put_jsr(STUB_INIT, SYM(S_INIT));
    put_jsr(STUB_RUN, SYM(S_FLUSH));
    put_jsr(STUB_RUN + 3, SYM(S_IMPORT));
    put_jsr(STUB_RUN + 6, SYM(S_RUN));
    put_jsr(STUB_RUN + 9, SYM(S_EXPORT));
    put_jsr(STUB_COST, SYM(S_FLUSH));
    put_jsr(STUB_COST + 3, SYM(S_IMPORT));
    put_jsr(STUB_COST + 6, SYM(S_RUN));
    put_jsr(STUB_COST_RUN_END, SYM(S_EXPORT));
    put_jsr(STUB_EXPORT, SYM(S_EXPORT));
    put_jsr(STUB_FLUSH_RUN, SYM(S_FLUSH));      /* no vm_import */
    put_jsr(STUB_RESUME, SYM(S_RUN));
    put_jsr(STUB_RESUME + 3, SYM(S_EXPORT));
    *main_at(STUB_RESUME_END) = 0xdb;
    *main_at(STUB_COST_END) = 0xdb;
    *main_at(STUB_EXPORT_END) = 0xdb;
    *main_at(STUB_RUN_END) = 0xdb;
    *main_at(STUB_FIRST_END) = 0xdb;        /* STP: never reached */
    *main_at(STUB_NEXT_END) = 0xdb;
    *main_at(STUB_INIT_END) = 0xdb;
    if (SYM(S_NPTAB) < 4) {
        fprintf(stderr, "vm816: the interpreter has %u page tables; the "
                "harness needs 4\n", (unsigned)SYM(S_NPTAB));
        exit(2);
    }
    fixed_tables();
    m->cpu.s = 0xff;
    if (!run_stub(STUB_INIT, STUB_INIT_END)) {
        fprintf(stderr, "vm816: vm_init did not return\n");
        exit(2);
    }
    m->write_hook = on_write;
}

/* ---- the vector files (tools/ref816/vectors.c) ---- */

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
        perror("vm816");
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
        perror("vm816");
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

/* ---- the known issues of the set (tools/ref816/vectors.c) ---- */

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

static int stack_at_page_start(const vector *v)
{
    return (v->before.s & 0xff) == 0;
}

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
      "JSR (a,x) in emulation mode with S = $0100: the set wraps the "
      "second push to $01FF, the chip pushes to $00FF (as "
      "tools/ref816/vectors.c explains)", 0, 0 },
    { 0xe1, 1, pointer_at_page_end,
      "SBC (d,x) in emulation mode with DL = 0 and the pointer at the "
      "last byte of the page: the set reads the pointer's high byte from "
      "the next page, the chip wraps (as tools/ref816/vectors.c "
      "explains)", 0, 0 },
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

/* ---- one case ---- */

typedef struct {
    unsigned cases, state, known;
} tally;

static void poke(uint32_t address, uint8_t value)
{
    place p = where(address);
    if (p.kind < 0) {
        fprintf(stderr, "vm816: $%06" PRIx32 " is not mapped\n", address);
        exit(2);
    }
    *storage_of(p) = value;
}

static uint8_t peek(uint32_t address)
{
    place p = where(address);
    return p.kind < 0 ? 0 : *storage_of(p);
}

static void load_state(const state *s)
{
    put_word(SYM(S_A), s->a);
    put_word(SYM(S_X), s->x);
    put_word(SYM(S_Y), s->y);
    put_word(SYM(S_S), s->s);
    put_word(SYM(S_D), s->d);
    *main_at(SYM(S_DBR)) = s->dbr;
    *main_at(SYM(S_PBR)) = s->pbr;
    *main_at(SYM(S_E)) = s->e;
    *main_at(SYM(S_P)) = s->p;
    put_word(SYM(S_PC), s->pc);
}

static void read_state(state *s)
{
    s->a = get_word(SYM(S_A));
    s->x = get_word(SYM(S_X));
    s->y = get_word(SYM(S_Y));
    s->s = get_word(SYM(S_S));
    s->d = get_word(SYM(S_D));
    s->dbr = *main_at(SYM(S_DBR));
    s->pbr = *main_at(SYM(S_PBR));
    s->e = *main_at(SYM(S_E));
    s->p = *main_at(SYM(S_P));
    s->pc = get_word(SYM(S_PC));
}

static int listed_after(const vector *v, uint32_t address)
{
    for (uint32_t i = 0; i < v->ram_after_count; i++)
        if ((v->ram_after[i] & 0xffffff) == address)
            return 1;
    return 0;
}

static void prepare_case(const vector *v)
{
    for (uint32_t i = 0; i < v->ram_before_count; i++)
        map_half_bank((v->ram_before[i] & 0xffffff) >> 15);
    for (uint32_t i = 0; i < v->ram_after_count; i++)
        map_half_bank((v->ram_after[i] & 0xffffff) >> 15);
    for (uint32_t i = 0; i < v->ram_before_count; i++)
        poke(v->ram_before[i] & 0xffffff, (uint8_t)(v->ram_before[i] >> 24));
    load_state(&v->before);
    vwrite_count = 0;
    *stray = 0;
}

/* The state `have` and memory against the case's: a reason in `why`, or
   an empty one. */
static void check_case(const vector *v, const state *have, char *why,
                       size_t size)
{
    const char *field = NULL;
    unsigned got = 0, expect = 0;

    if (*main_at(SYM(S_STATUS))) {
        snprintf(why, size, "trap %u at $%06x", *main_at(SYM(S_STATUS)),
                 (unsigned)(get_word(SYM(S_EA)) |
                            *main_at(SYM(S_EA) + 2) << 16));
        return;
    }
    if (*stray) {
        snprintf(why, size, "%s", stray);
        return;
    }

#define CHECK(name, member) \
    if (!field && have->member != v->after.member) { \
        field = name; got = have->member; expect = v->after.member; }
    CHECK("pc", pc) CHECK("s", s) CHECK("a", a) CHECK("x", x)
    CHECK("y", y) CHECK("d", d) CHECK("p", p) CHECK("dbr", dbr)
    CHECK("pbr", pbr) CHECK("e", e)
#undef CHECK
    if (field) {
        snprintf(why, size, "%s is %04x, expected %04x", field, got, expect);
        return;
    }
    for (uint32_t i = 0; i < v->ram_after_count; i++) {
        uint32_t address = v->ram_after[i] & 0xffffff;
        uint8_t want = (uint8_t)(v->ram_after[i] >> 24);
        if (peek(address) != want) {
            snprintf(why, size, "RAM %06" PRIx32 " is %02x, expected %02x",
                     address, peek(address), want);
            return;
        }
    }
    if (vwrite_count >= MAX_WRITES) {
        snprintf(why, size, "too many writes");
        return;
    }
    for (unsigned i = 0; i < vwrite_count; i++)
        if (!listed_after(v, vwrites[i])) {
            snprintf(why, size, "write to %06" PRIx32 ", which the case "
                     "does not list", vwrites[i]);
            return;
        }
}

static void clean_case(const vector *v)
{
    m->write_hook = NULL;
    for (uint32_t i = 0; i < v->ram_before_count; i++)
        poke(v->ram_before[i] & 0xffffff, 0);
    for (uint32_t i = 0; i < v->ram_after_count; i++)
        poke(v->ram_after[i] & 0xffffff, 0);
    for (unsigned i = 0; i < vwrite_count && i < MAX_WRITES; i++)
        if (where(vwrites[i]).kind >= 0)
            poke(vwrites[i], 0);
    unmap_all();
    m->write_hook = on_write;
}

static void run_case(const vector *v, char *why, size_t size)
{
    unsigned recorded = v->cycle_count, steps = 1, tail = 0;
    int opcode = program_byte(v, 0);
    state have;

    *why = 0;
    prepare_case(v);
    if (!run_stub(STUB_FIRST, STUB_FIRST_END)) {
        snprintf(why, size, "the interpreter did not return");
        goto clean;
    }
    while (recorded && (v->cycles[recorded - 1].nulls & NULL_ADDRESS))
        recorded--;
    read_state(&have);
    if (opcode == 0x44 || opcode == 0x54) {
        while (!*main_at(SYM(S_STATUS)) && have.pc == v->before.pc &&
               have.pbr == v->before.pbr &&
               (steps + 1) * MVN_CYCLES <= recorded) {
            if (!run_stub(STUB_NEXT, STUB_NEXT_END)) {
                snprintf(why, size, "the interpreter did not return");
                goto clean;
            }
            steps++;
            read_state(&have);
        }
        if (steps * MVN_CYCLES < recorded && have.pc == v->before.pc &&
            have.pbr == v->before.pbr) {
            unsigned ran = steps * MVN_CYCLES;
            tail = recorded - ran;
            for (unsigned i = 0; i < tail; i++) {
                const cycle *c = &v->cycles[ran + i];
                if (!(c->pins & PIN_VPA) || c->address !=
                    ((uint32_t)v->before.pbr << 16 |
                     (uint16_t)(v->before.pc + i)))
                    tail = 0;
            }
        }
        have.pc = (uint16_t)(have.pc + tail);
    }
    check_case(v, &have, why, size);
clean:
    clean_case(v);
}

/* ---- the cost of one instruction (--cost) ---- */

typedef struct {
    uint32_t *cycles, *clocks;
    uint8_t *paged;                     /* the fetch entered a new page */
    size_t count, capacity;
} cost_bucket;

static cost_bucket buckets[256 * 8];    /* opcode << 3 | E << 2 | M << 1 | X */

static void bucket_add(cost_bucket *b, uint32_t cycles, uint32_t clocks,
                       uint8_t paged)
{
    if (b->count == b->capacity) {
        b->capacity = b->capacity ? 2 * b->capacity : 1024;
        b->cycles = realloc(b->cycles, b->capacity * sizeof *b->cycles);
        b->clocks = realloc(b->clocks, b->capacity * sizeof *b->clocks);
        b->paged = realloc(b->paged, b->capacity * sizeof *b->paged);
        if (!b->cycles || !b->clocks || !b->paged) {
            perror("vm816");
            exit(2);
        }
    }
    b->cycles[b->count] = cycles;
    b->clocks[b->count] = clocks;
    b->paged[b->count++] = paged;
}

static void bucket_free(cost_bucket *b)
{
    free(b->cycles);
    free(b->clocks);
    free(b->paged);
}

/* Set when the 65C02 reaches next_page in run_until: the fetch of the
   instruction entered a new code page. paged_cases counts such cases. */
static int entered_page;
static unsigned paged_cases;

/* Step the 65C02 until it reaches one of `stops` (n of them). Returns the
   address it stopped at, or 0 when it ran away. */
static uint16_t run_until(const uint16_t *stops, unsigned n)
{
    unsigned long count = 0;
    for (;;) {
        for (unsigned i = 0; i < n; i++)
            if (m->cpu.pc == stops[i])
                return stops[i];
        if (m->cpu.pc == SYM(S_NEXT_PAGE))
            entered_page = 1;
        if (++count > MAX_STEPS || m->cpu.state != CPU65C02_RUNNING)
            return 0;
        a2vm_step(m);
        steps_run++;
    }
}

/* One case through vm_run, measured (see the top of this file). Returns
   0 when the instruction could not be measured, with the reason. */
static int cost_case(const vector *v, char *why, size_t size)
{
    int opcode = program_byte(v, 0);
    uint16_t first[2] = { (uint16_t)SYM(S_FETCH), STUB_COST_RUN_END };
    uint16_t next[3] = { (uint16_t)SYM(S_FETCH), (uint16_t)SYM(S_SERVICE),
                         STUB_COST_RUN_END };
    uint64_t cycles0, clocks0;
    int measured = 0;
    state have;

    *why = 0;
    prepare_case(v);
    m->cpu.s = 0xff;
    m->cpu.pc = STUB_COST;
    m->cpu.state = CPU65C02_RUNNING;
    if (run_until(first, 2) != SYM(S_FETCH)) {
        snprintf(why, size, "the dispatch loop did not reach its fetch");
        goto clean;
    }
    cycles0 = m->cpu.cycles;
    clocks0 = m->cost->t;
    a2vm_step(m);                       /* leave `fetch` */
    steps_run++;
    entered_page = 0;
    switch (run_until(next, 3)) {
    case 0:
        snprintf(why, size, "the interpreter ran away");
        goto clean;
    case STUB_COST_RUN_END:
        snprintf(why, size, "vm_run returned: status %u",
                 *main_at(SYM(S_STATUS)));
        goto clean;
    default:
        break;
    }
    bucket_add(&buckets[(unsigned)opcode << 3 | v->before.e << 2 |
                        (v->before.p >> 4 & 3)],
               (uint32_t)(m->cpu.cycles - cycles0),
               (uint32_t)(m->cost->t - clocks0), (uint8_t)entered_page);
    if (entered_page)
        paged_cases++;
    measured = 1;
    m->cpu.s = 0xff;
    if (!run_stub(STUB_EXPORT, STUB_EXPORT_END)) {
        snprintf(why, size, "vm_export did not return");
        goto clean;
    }
    if (opcode != 0x44 && opcode != 0x54) {
        read_state(&have);
        check_case(v, &have, why, size);
    }
clean:
    clean_case(v);
    return measured;
}

static int by_value(const void *a, const void *b)
{
    uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
    return (x > y) - (x < y);
}

/* Sorts a copy: a bucket's values stay paired with its `paged`. */
static void write_stats(FILE *out, const uint32_t *values, size_t n)
{
    uint64_t sum = 0;
    uint32_t *sorted = malloc(n * sizeof *sorted);
    if (!sorted) {
        perror("vm816");
        exit(2);
    }
    memcpy(sorted, values, n * sizeof *sorted);
    qsort(sorted, n, sizeof *sorted, by_value);
    for (size_t i = 0; i < n; i++)
        sum += sorted[i];
    fprintf(out, " %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu64, sorted[0],
            sorted[(n - 1) / 2], sorted[n - 1], sum);
    free(sorted);
}

/* A bucket's line: every case, then "apart" and the number of cases whose
   fetch entered a new code page, then the cases without them (count,
   cycles and clocks as above, or only the count when there are none). */
static void write_bucket(FILE *out, cost_bucket *b)
{
    cost_bucket rest = { NULL, NULL, NULL, 0, 0 };
    for (size_t i = 0; i < b->count; i++)
        if (!b->paged[i])
            bucket_add(&rest, b->cycles[i], b->clocks[i], 0);
    fprintf(out, " %zu", b->count);
    write_stats(out, b->cycles, b->count);
    write_stats(out, b->clocks, b->count);
    fprintf(out, " apart %zu %zu", b->count - rest.count, rest.count);
    if (rest.count) {
        write_stats(out, rest.cycles, rest.count);
        write_stats(out, rest.clocks, rest.count);
    }
    fputc('\n', out);
    bucket_free(&rest);
}

static void count(unsigned *failures, const char *why, const char *path,
                  unsigned index, const char *kind, unsigned shown)
{
    if (!*why)
        return;
    if ((*failures)++ < shown)
        printf("  %s case %u: %s: %s\n", path, index, kind, why);
}

static int cost_mode;                   /* --cost: measure each case */
static unsigned unmeasured;

static tally run_file(const char *path, unsigned limit, unsigned shown)
{
    size_t size;
    uint8_t *data = read_file(path, &size);
    reader r = { data, size, 0, 0 };
    tally t = { 0, 0, 0 };
    unsigned cases;

    if (size < 12 || memcmp(data, "SST816V1", 8)) {
        fprintf(stderr, "vm816: %s: not a vector file\n", path);
        exit(2);
    }
    r.at = 8;
    cases = take(&r, 4);
    if (limit && cases > limit)
        cases = limit;
    for (unsigned i = 0; i < cases; i++) {
        vector v;
        char why[200];
        known_issue *issue;
        if (!take_vector(&r, &v)) {
            fprintf(stderr, "vm816: %s: truncated at case %u\n", path, i);
            exit(2);
        }
        if (!cost_mode)
            run_case(&v, why, sizeof why);
        else if (!cost_case(&v, why, sizeof why))
            unmeasured++;
        t.cases++;
        issue = known_issue_of(&v);
        if (issue) {
            issue->matched++;
            if (*why) {
                issue->differed++;
                count(&t.known, why, path, i, "known issue", shown);
                *why = 0;
            }
        }
        count(&t.state, why, path, i, "state", shown);
        free_vector(&v);
    }
    free(data);
    return t;
}

/* ---- lockstep with the reference core ---- */

static uint64_t rng_state;

/* xorshift64*: the only source of the random programs. */
static uint32_t rnd(void)
{
    rng_state ^= rng_state >> 12;
    rng_state ^= rng_state << 25;
    rng_state ^= rng_state >> 27;
    return (uint32_t)((rng_state * 0x2545F4914F6CDD1DULL) >> 32);
}

/* The reference's physical memory, laid out as a2vm's: main, then the
   128 aux banks; vmap gives each virtual page its place there. */
static uint8_t *ref_main, *ref_aux;
static uint32_t vmap[0x10000];          /* kind << 24 | bank << 16 | page << 8 */
static uint32_t phys_list[2 * 128 * 256];
static unsigned phys_count;

static uint8_t *ref_at(uint32_t address)
{
    uint32_t e = vmap[address >> 8 & 0xffff];
    size_t offset = (size_t)(e & 0xff00) | (address & 0xff);
    if (!(e >> 24))
        return ref_main + offset;
    return ref_aux + ((size_t)(e >> 16 & 0xff) << 16) + offset;
}

static uint8_t *vm_at(uint32_t e)
{
    return a2vm_storage(m, (int)(e >> 24), e >> 16 & 0xff,
                        (uint16_t)(e & 0xff00));
}

static uint8_t ref_read(void *context, uint32_t address)
{
    (void)context;
    return *ref_at(address);
}

static void ref_write(void *context, uint32_t address, uint8_t value)
{
    (void)context;
    *ref_at(address) = value;
}

/* Map every half-bank: the page tables as for the vectors, the others
   onto `banks` RamWorks banks. */
static void map_everything(unsigned banks)
{
    static uint8_t seen[2][128][256];
    memset(seen, 0, sizeof seen);
    for (unsigned half = 4; half < 512; half++) {
        uint8_t bank = (uint8_t)(POOL_FIRST + (half - 4) % banks);
        *main_at((half < 256 ? SYM(S_MAP0) : SYM(S_MAP1)) + (half & 0xff)) =
            bank;
        for (unsigned page = 0x40; page < 0xc0; page++)
            owner_used[bank][page] = 1;
    }
    phys_count = 0;
    for (uint32_t vpage = 0; vpage < 0x10000; vpage++) {
        place p = where(vpage << 8);
        if (p.kind < 0) {
            fprintf(stderr, "vm816: $%04" PRIx32 "00 is not mapped\n", vpage);
            exit(2);
        }
        vmap[vpage] = (uint32_t)p.kind << 24 | p.bank << 16 |
                      (uint32_t)(p.address & 0xff00);
        if (!seen[p.kind][p.bank][p.address >> 8]) {
            seen[p.kind][p.bank][p.address >> 8] = 1;
            phys_list[phys_count++] = vmap[vpage];
        }
    }
    everything_mapped = 1;
}

typedef struct {
    uint32_t address;
    uint8_t opcode, e, p;
} trace_entry;

static void show_trace(const trace_entry *trace, unsigned step)
{
    unsigned first = step >= 8 ? step - 8 : 0;
    for (unsigned i = first; i <= step; i++) {
        const trace_entry *t = &trace[i % 8];
        printf("    step %u: %02x:%04x opcode %02x, e %u, p %02x\n", i,
               (unsigned)(t->address >> 16), (unsigned)(t->address & 0xffff),
               t->opcode, t->e, t->p);
    }
}

static int lockstep(uint64_t seed, unsigned programs, unsigned steps,
                    unsigned banks)
{
    cpu816 cpu;
    unsigned failures = 0;
    uint64_t total_steps = 0, interrupts = 0, stops = 0;

    rng_state = seed * 0x9E3779B97F4A7C15ULL + 1;
    ref_main = calloc(1, 0x10000);
    ref_aux = calloc(128, 0x10000);
    if (!ref_main || !ref_aux) {
        perror("vm816");
        exit(2);
    }
    map_everything(banks);
    for (unsigned program = 0; program < programs && failures < 3;
         program++) {
        trace_entry trace[8];
        int irq = 0;
        state have;
        char why[200] = "";

        for (unsigned i = 0; i < phys_count; i++) {
            uint8_t *mine = vm_at(phys_list[i]);
            uint8_t *theirs = phys_list[i] >> 24
                ? ref_aux + ((size_t)(phys_list[i] >> 16 & 0xff) << 16) +
                      (phys_list[i] & 0xff00)
                : ref_main + (phys_list[i] & 0xff00);
            for (unsigned j = 0; j < 256; j += 4) {
                uint32_t r = rnd();
                for (unsigned k = 0; k < 4; k++)
                    mine[j + k] = theirs[j + k] = (uint8_t)(r >> 8 * k);
            }
        }
        cpu816_init(&cpu, ref_read, ref_write, NULL);
        cpu.pc = (uint16_t)rnd();
        cpu.s = (uint16_t)rnd();
        cpu.a = (uint16_t)rnd();
        cpu.x = (uint16_t)rnd();
        cpu.y = (uint16_t)rnd();
        cpu.d = (uint16_t)rnd();
        cpu.p = (uint8_t)rnd();
        cpu.dbr = (uint8_t)rnd();
        cpu.pbr = (uint8_t)rnd();
        cpu.e = rnd() & 1;
        cpu.state = CPU816_RUNNING;
        cpu816_normalise(&cpu);
        {
            state s0 = { cpu.pc, cpu.s, cpu.a, cpu.x, cpu.y, cpu.d, cpu.p,
                         cpu.dbr, cpu.pbr, cpu.e };
            load_state(&s0);
        }
        *main_at(SYM(S_EVENT)) = 0;

        for (unsigned step = 0; step < steps; step++) {
            uint32_t r = rnd();
            trace_entry *t = &trace[step % 8];
            const char *field = NULL;
            unsigned got = 0, expect = 0;

            if (r % 61 == 0) {
                irq = !irq;
                cpu816_set_irq(&cpu, 1, irq);
            }
            if (r % 887 == 3) {
                cpu816_nmi(&cpu);
                *main_at(SYM(S_EVENT)) |= 0x02;
            }
            *main_at(SYM(S_EVENT)) = (uint8_t)
                ((*main_at(SYM(S_EVENT)) & ~1u) | (irq ? 1u : 0u));
            t->address = (uint32_t)cpu.pbr << 16 | cpu.pc;
            t->opcode = *ref_at(t->address);
            t->e = cpu.e;
            t->p = cpu.p;
            if (cpu.state == CPU816_RUNNING &&
                (cpu.nmi_pending || (irq && !(cpu.p & CPU816_I))))
                interrupts++;
            cpu816_step(&cpu);
            vwrite_count = 0;
            *stray = 0;
            if (!(step ? run_stub(STUB_NEXT, STUB_NEXT_END)
                       : run_stub(STUB_FIRST, STUB_FIRST_END))) {
                snprintf(why, sizeof why, "the interpreter did not return");
            } else if (*main_at(SYM(S_STATUS))) {
                snprintf(why, sizeof why, "trap %u", *main_at(SYM(S_STATUS)));
            } else if (*stray) {
                snprintf(why, sizeof why, "%s", stray);
            } else {
                read_state(&have);
#define CHECK(name, a, b) \
    if (!field && (unsigned)(a) != (unsigned)(b)) { \
        field = name; got = (unsigned)(a); expect = (unsigned)(b); }
                CHECK("pc", have.pc, cpu.pc) CHECK("s", have.s, cpu.s)
                CHECK("a", have.a, cpu.a) CHECK("x", have.x, cpu.x)
                CHECK("y", have.y, cpu.y) CHECK("d", have.d, cpu.d)
                CHECK("p", have.p, cpu.p) CHECK("dbr", have.dbr, cpu.dbr)
                CHECK("pbr", have.pbr, cpu.pbr) CHECK("e", have.e, cpu.e)
                CHECK("state", *main_at(SYM(S_STATE)), cpu.state)
#undef CHECK
                if (field)
                    snprintf(why, sizeof why, "%s is %04x, expected %04x",
                             field, got, expect);
            }
            total_steps++;
            if (*why) {
                printf("  program %u step %u: %s\n", program, step, why);
                show_trace(trace, step);
                failures++;
                break;
            }
            if (cpu.state == CPU816_STOPPED) {
                stops++;
                break;
            }
        }
        if (*why)
            continue;
        for (unsigned i = 0; i < phys_count; i++) {
            uint32_t e = phys_list[i];
            uint8_t *mine = vm_at(e);
            uint8_t *theirs = e >> 24
                ? ref_aux + ((size_t)(e >> 16 & 0xff) << 16) + (e & 0xff00)
                : ref_main + (e & 0xff00);
            if (memcmp(mine, theirs, 256)) {
                unsigned j = 0;
                while (mine[j] == theirs[j])
                    j++;
                printf("  program %u: %s %u $%04x is %02x, expected %02x\n",
                       program, e >> 24 ? "aux bank" : "main",
                       (unsigned)(e >> 16 & 0xff),
                       (unsigned)((e & 0xff00) | j), mine[j], theirs[j]);
                failures++;
                break;
            }
        }
    }
    printf("lockstep, seed %" PRIu64 ", %u banks: %u programs, %" PRIu64
           " steps (%" PRIu64 " interrupts taken, %" PRIu64 " programs "
           "ended by STP): %u failures\n", seed, banks, programs,
           total_steps, interrupts, stops, failures);
    printf("65C02 instructions: %" PRIu64 " (%.0f a step)\n", steps_run,
           total_steps ? (double)steps_run / total_steps : 0.0);
    free(ref_main);
    free(ref_aux);
    return failures ? 1 : 0;
}

/* ---- self test ---- */

static unsigned selftest_failures;

static void expect(const char *what, unsigned have, unsigned want)
{
    if (have != want) {
        printf("  %s: %x, expected %x\n", what, have, want);
        selftest_failures++;
    }
}

/* A native-mode program at $00:`at` (page table 1 for $8000 and up),
   run from a clean state by `stub`, with bytes `code`. */
static void run_program_at(uint16_t at, const uint8_t *code, size_t length,
                           uint16_t stub, uint16_t end)
{
    state s = { at, 0x01ff, 0, 0, 0, 0, 0x30, 0, 0, 0 };
    for (size_t i = 0; i < length; i++)
        poke((uint16_t)(at + i), code[i]);
    load_state(&s);
    *main_at(SYM(S_EVENT)) = 0;
    if (!run_stub(stub, end)) {
        printf("  the interpreter did not return\n");
        selftest_failures++;
    }
}

static void run_program(const uint8_t *code, size_t length, uint16_t stub,
                        uint16_t end)
{
    run_program_at(0x8000, code, length, stub, end);
}

/* Run `stub` on the interpreter's state as it is (no program, no state
   written). */
static void run_again(uint16_t stub, uint16_t end)
{
    if (!run_stub(stub, end)) {
        printf("  the interpreter did not return\n");
        selftest_failures++;
    }
}

static uint32_t trap_address(void)
{
    return get_word(SYM(S_EA)) | (uint32_t)*main_at(SYM(S_EA) + 2) << 16;
}

static int selftest(void)
{
    static const uint8_t lda_long[] = { 0xaf, 0x56, 0x34, 0x12 };
    static const uint8_t sta_long[] = { 0x8f, 0x56, 0x34, 0x12 };
    static const uint8_t jml[] = { 0x5c, 0x56, 0x34, 0x12 };
    static const uint8_t jml_page[] = { 0x5c, 0x00, 0x34, 0x12 };
    /* LDA #$42, JML $345678 */
    static const uint8_t lda_jml[] = { 0xa9, 0x42, 0x5c, 0x78, 0x56, 0x34 };
    static const uint8_t lda_abs[] = { 0xad, 0x19 };   /* high byte: $C0 */
    static const uint8_t nop[] = { 0xea };
    static const uint8_t lda_io[] = { 0xad, 0x19, 0xc0 };
    /* LDA #5, INC A, INC A, STA $C034, then LDA $C019 */
    static const uint8_t program[] = { 0xa9, 0x05, 0x1a, 0x1a, 0x8d, 0x34,
                                       0xc0, 0xad, 0x19, 0xc0 };
    uint32_t io_entry = SYM(S_PTAB) + 256u * 1 + (0xc0 & 0x7f) * 2;
    uint8_t saved = *main_at(io_entry);
    uint16_t trap_rd = get_word(SYM(S_TRAP_RD));
    uint16_t trap_wr = get_word(SYM(S_TRAP_WR));

    m->write_hook = NULL;

    printf("read, write and fetch in an unmapped half-bank\n");
    run_program(lda_long, sizeof lda_long, STUB_FIRST, STUB_FIRST_END);
    expect("status after LDA $123456", *main_at(SYM(S_STATUS)), 1);
    expect("its address", trap_address(), 0x123456);
    run_program(sta_long, sizeof sta_long, STUB_FIRST, STUB_FIRST_END);
    expect("status after STA $123456", *main_at(SYM(S_STATUS)), 2);
    expect("its address", trap_address(), 0x123456);
    run_program(jml, sizeof jml, STUB_FIRST, STUB_FIRST_END);
    expect("status after JML $123456", *main_at(SYM(S_STATUS)), 0);
    expect("its PC", get_word(SYM(S_PC)), 0x3456);
    expect("its PBR", *main_at(SYM(S_PBR)), 0x12);
    if (!run_stub(STUB_NEXT, STUB_NEXT_END))
        selftest_failures++;
    expect("status of the next fetch", *main_at(SYM(S_STATUS)), 3);
    expect("its address", trap_address(), 0x123400);
    expect("the PC exported", get_word(SYM(S_PC)), 0x3456);
    expect("the PBR exported", *main_at(SYM(S_PBR)), 0x12);
    printf("vm_run again after it, without vm_import or vm_flush\n");
    run_again(STUB_RESUME, STUB_RESUME_END);
    expect("status", *main_at(SYM(S_STATUS)), 3);
    expect("its address", trap_address(), 0x123400);
    expect("the PC exported", get_word(SYM(S_PC)), 0x3456);

    printf("a jump to the first byte of an unmapped page\n");
    run_program(jml_page, sizeof jml_page, STUB_FIRST, STUB_FIRST_END);
    expect("status after JML $123400", *main_at(SYM(S_STATUS)), 0);
    run_again(STUB_NEXT, STUB_NEXT_END);
    expect("status of the next fetch", *main_at(SYM(S_STATUS)), 3);
    expect("its address", trap_address(), 0x123400);
    expect("the PC exported", get_word(SYM(S_PC)), 0x3400);
    expect("the PBR exported", *main_at(SYM(S_PBR)), 0x12);
    printf("vm_run again after it, without vm_import or vm_flush\n");
    run_again(STUB_RESUME, STUB_RESUME_END);
    expect("status", *main_at(SYM(S_STATUS)), 3);
    expect("its address", trap_address(), 0x123400);
    expect("the PC exported", get_word(SYM(S_PC)), 0x3400);
    expect("the PBR exported", *main_at(SYM(S_PBR)), 0x12);
    printf("the page mapped, vm_flush, vm_run: it runs from $12:3400\n");
    map_half_bank(0x12 * 2);
    for (size_t i = 0; i < sizeof lda_jml; i++)
        poke(0x123400 + (uint32_t)i, lda_jml[i]);
    run_again(STUB_FLUSH_RUN, STUB_RESUME_END);
    expect("status", *main_at(SYM(S_STATUS)), 3);
    expect("A after LDA #$42", *main_at(SYM(S_A)), 0x42);
    expect("the trap's address", trap_address(), 0x345600);
    expect("the PC exported", get_word(SYM(S_PC)), 0x5678);
    expect("the PBR exported", *main_at(SYM(S_PBR)), 0x34);
    for (size_t i = 0; i < sizeof lda_jml; i++)
        poke(0x123400 + (uint32_t)i, 0);
    unmap_all();

    printf("an unmapped page of a page table: $00:C000-$C0FF\n");
    *main_at(io_entry) = 0xff;
    run_program(lda_io, sizeof lda_io, STUB_FIRST, STUB_FIRST_END);
    expect("status after LDA $C019", *main_at(SYM(S_STATUS)), 1);
    expect("its address", trap_address(), 0x00c019);

    printf("an operand that runs into it: LDA $xxxx at $00:BFFE\n");
    run_program_at(0xbffe, lda_abs, sizeof lda_abs, STUB_FIRST,
                   STUB_FIRST_END);
    expect("status", *main_at(SYM(S_STATUS)), 3);
    expect("its address", trap_address(), 0x00c000);
    expect("the PC exported", get_word(SYM(S_PC)), 0xbffe);
    expect("the PBR exported", *main_at(SYM(S_PBR)), 0x00);
    printf("vm_run again after it, without vm_import or vm_flush\n");
    run_again(STUB_RESUME, STUB_RESUME_END);
    expect("status", *main_at(SYM(S_STATUS)), 3);
    expect("its address", trap_address(), 0x00c000);
    expect("the PC exported", get_word(SYM(S_PC)), 0xbffe);

    printf("a fall-through into it: NOP at $00:BFFF\n");
    poke(0xbffe, 0);
    run_program_at(0xbfff, nop, sizeof nop, STUB_FIRST, STUB_FIRST_END);
    expect("status after NOP", *main_at(SYM(S_STATUS)), 0);
    expect("the PC exported", get_word(SYM(S_PC)), 0xc000);
    run_again(STUB_NEXT, STUB_NEXT_END);
    expect("status of the next fetch", *main_at(SYM(S_STATUS)), 3);
    expect("its address", trap_address(), 0x00c000);
    expect("the PC exported", get_word(SYM(S_PC)), 0xc000);
    expect("the PBR exported", *main_at(SYM(S_PBR)), 0x00);
    poke(0xbfff, 0);

    printf("vm_run until a trap\n");
    run_program(program, sizeof program, STUB_RUN, STUB_RUN_END);
    expect("status", *main_at(SYM(S_STATUS)), 2);
    expect("address", trap_address(), 0x00c034);
    expect("A", *main_at(SYM(S_A)), 7);

    printf("trap handlers that return\n");
    /* read: LDA #$5A, RTS; write: STA TRAP_CELL, RTS */
    *main_at(TRAP_READ) = 0xa9;
    *main_at(TRAP_READ + 1) = 0x5a;
    *main_at(TRAP_READ + 2) = 0x60;
    *main_at(TRAP_WRITE) = 0x8d;
    put_word(TRAP_WRITE + 1, TRAP_CELL);
    *main_at(TRAP_WRITE + 3) = 0x60;
    put_word(SYM(S_TRAP_RD), TRAP_READ);
    put_word(SYM(S_TRAP_WR), TRAP_WRITE);
    *main_at(TRAP_CELL) = 0;
    run_program(program, sizeof program, STUB_FIRST, STUB_FIRST_END);
    for (int i = 0; i < 4; i++)
        if (!run_stub(STUB_NEXT, STUB_NEXT_END))
            selftest_failures++;
    expect("status", *main_at(SYM(S_STATUS)), 0);
    expect("the byte written to $C034", *main_at(TRAP_CELL), 7);
    expect("A after LDA $C019", *main_at(SYM(S_A)), 0x5a);
    expect("PC", get_word(SYM(S_PC)), 0x800a);
    expect("P", *main_at(SYM(S_P)), 0x30);

    put_word(SYM(S_TRAP_RD), trap_rd);
    put_word(SYM(S_TRAP_WR), trap_wr);
    *main_at(io_entry) = saved;
    for (size_t i = 0; i < sizeof program; i++)
        poke(0x8000 + (uint32_t)i, 0);
    m->write_hook = on_write;
    printf("self test: %u failures\n", selftest_failures);
    return selftest_failures ? 1 : 0;
}

static double seconds(void)
{
    struct timespec now;
    if (!timespec_get(&now, TIME_UTC))
        return 0;
    return (double)now.tv_sec + now.tv_nsec / 1e9;
}

int main(int argc, char **argv)
{
    unsigned limit = 0, shown = 3;
    const char *dir = "build/vm", *cost_params = NULL, *cost_out = NULL;
    tally total = { 0, 0, 0 };
    unsigned files = 0, failed_files = 0;
    double start;
    int i;

    for (i = 1; i < argc && argv[i][0] == '-'; i += 2) {
        if (i + 1 >= argc)
            break;
        if (!strcmp(argv[i], "--limit"))
            limit = (unsigned)strtoul(argv[i + 1], NULL, 10);
        else if (!strcmp(argv[i], "--show"))
            shown = (unsigned)strtoul(argv[i + 1], NULL, 10);
        else if (!strcmp(argv[i], "--vm"))
            dir = argv[i + 1];
        else if (!strcmp(argv[i], "--cost") && i + 2 < argc) {
            cost_params = argv[i + 1];
            cost_out = argv[i + 2];
            i++;
        } else
            break;
    }
    if (i + 4 < argc && !strcmp(argv[i], "--lockstep")) {
        uint64_t seed = strtoull(argv[i + 1], NULL, 10);
        unsigned programs = (unsigned)strtoul(argv[i + 2], NULL, 10);
        unsigned steps = (unsigned)strtoul(argv[i + 3], NULL, 10);
        unsigned banks = (unsigned)strtoul(argv[i + 4], NULL, 10);
        int status;
        if (banks < 1 || banks > POOL_LAST - POOL_FIRST + 1) {
            fprintf(stderr, "vm816: BANKS must be 1-124\n");
            return 2;
        }
        setup(dir);
        start = seconds();
        status = lockstep(seed, programs, steps, banks);
        printf("host time %.1f s\n", seconds() - start);
        return status;
    }
    if (i < argc && !strcmp(argv[i], "--selftest")) {
        setup(dir);
        return selftest();
    }
    if (i >= argc || argv[i][0] == '-') {
        fprintf(stderr, "usage: vm816 [--vm DIR] [--limit N] [--show N] "
                "FILE...\n       vm816 [--vm DIR] --lockstep SEED "
                "PROGRAMS STEPS BANKS\n       vm816 [--vm DIR] "
                "--selftest\n       vm816 [--vm DIR] [--limit N] --cost "
                "PARAMS OUT FILE...\n");
        return 2;
    }
    setup(dir);
    if (cost_params) {
        a2vm_cost_params params;
        char error[256];
        if (!a2vm_cost_load(&params, cost_params, error, sizeof error)) {
            fprintf(stderr, "vm816: %s\n", error);
            return 2;
        }
        a2vm_attach_cost(m, a2vm_cost_new(&params), 0);
        cost_mode = 1;
    }
    start = seconds();
    for (; i < argc; i++) {
        tally t = run_file(argv[i], limit, shown);
        const char *name = strrchr(argv[i], '/');
        name = name ? name + 1 : argv[i];
        files++;
        if (t.state) {
            failed_files++;
            printf("%s: %u cases, %u failures\n", name, t.cases, t.state);
        }
        total.cases += t.cases;
        total.state += t.state;
        total.known += t.known;
    }
    for (size_t k = 0; k < KNOWN_ISSUES; k++)
        if (known_issues[k].matched)
            printf("known issue, opcode %02x %s mode: %u cases match its rule, "
                   "%u differ from the set. %s\n", known_issues[k].opcode,
                   known_issues[k].emulation ? "emulation" : "native",
                   known_issues[k].matched, known_issues[k].differed,
                   known_issues[k].reason);
    printf("%u files, %u cases: %u failures in registers or memory, %u "
           "known issues; %u files with failures\n", files, total.cases,
           total.state, total.known, failed_files);
    printf("65C02 instructions: %" PRIu64 " (%.0f a case); host time "
           "%.1f s\n", steps_run,
           total.cases ? (double)steps_run / total.cases : 0.0,
           seconds() - start);
    if (cost_mode) {
        FILE *out = fopen(cost_out, "w");
        if (!out) {
            fprintf(stderr, "vm816: %s: %s\n", cost_out, strerror(errno));
            return 2;
        }
        /* The format: a header, the totals, then a line a bucket (an
           opcode, a mode and a width) and a line an opcode and mode over
           all widths, each with the count, then the 65C02 cycles, then
           the fabric clocks: minimum, lower median, maximum, sum; then
           the same without the cases whose fetch entered a new code page
           (write_bucket). Those cases copy a cold page into the cache
           while they are measured, since every case starts with vm_flush:
           a cost of the cache, not of the instruction. */
        fprintf(out, "vm816-cost 2\nfabric_mhz %.6f\n",
                m->cost->p.fabric_mhz);
        fprintf(out, "cases %u failures %u known %u unmeasured %u "
                "apart %u\n", total.cases, total.state, total.known,
                unmeasured, paged_cases);
        for (unsigned key = 0; key < 256 * 8; key++) {
            cost_bucket *b = &buckets[key];
            if (!b->count)
                continue;
            fprintf(out, "bucket %02X %u %u %u", key >> 3, key >> 2 & 1,
                    key >> 1 & 1, key & 1);
            write_bucket(out, b);
        }
        /* each opcode and mode over its widths: "mode OP E ..." */
        for (unsigned key = 0; key < 256 * 8; key += 4) {
            cost_bucket all = { NULL, NULL, NULL, 0, 0 };
            for (unsigned w = 0; w < 4; w++) {
                cost_bucket *b = &buckets[key + w];
                for (size_t i = 0; i < b->count; i++)
                    bucket_add(&all, b->cycles[i], b->clocks[i],
                               b->paged[i]);
                bucket_free(b);
            }
            if (!all.count)
                continue;
            fprintf(out, "mode %02X %u", key >> 3, key >> 2 & 1);
            write_bucket(out, &all);
            bucket_free(&all);
        }
        if (fclose(out)) {
            fprintf(stderr, "vm816: cannot write %s\n", cost_out);
            return 2;
        }
        printf("cost: %u cases measured of %u; %u set apart from the "
               "ranges (their fetch entered a new code page)\n",
               total.cases - unmeasured, total.cases, paged_cases);
        if (unmeasured)
            return 1;
    }
    return total.state ? 1 : 0;
}
