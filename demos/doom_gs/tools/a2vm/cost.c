/*
 * The cost model of a2vm: see cost.h for what it charges, and
 * tools/a2vm/costs/appletini.json for every parameter and its source in
 * the Appletini firmware (appletini-one, F1.2.1). Line numbers in the
 * comments below refer to hdl/apple/vtw_core_top.sv unless another file
 * is named.
 */
#include "cost.h"
#include "a2vm.h"

#include <inttypes.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

/* ---- parameters ---- */

typedef struct {
    const char *name;
    char type;                      /* d double, u unsigned, i int flag */
    size_t offset;
} param_spec;

#define P_D(name) { #name, 'd', offsetof(a2vm_cost_params, name) }
#define P_U(name) { #name, 'u', offsetof(a2vm_cost_params, name) }
#define P_I(name) { #name, 'i', offsetof(a2vm_cost_params, name) }

static const param_spec specs[] = {
    P_D(fabric_mhz), P_D(line_us), P_U(lines), P_U(vbl_line),
    P_U(turbo_hit), P_U(turbo_read_miss), P_U(turbo_write_miss),
    P_U(posted_write), P_D(turbo_extra), P_I(caches_survive),
    P_U(rw_hit), P_U(rw_request), P_U(psram_read), P_U(psram_write),
    P_U(rw_lines), P_U(admit_offset), P_U(admit_window),
    P_I(relaxed_admission), P_U(drain_rmw),
    P_U(io_capture), P_U(io_route), P_U(video_wait), P_U(bus_drive_tap),
    P_U(bus_data_tap), P_U(bus_done), P_U(status_read), P_U(sp_private),
    P_U(rom_read), P_U(quiet_switch), P_I(quiet_switches), P_I(read_bank),
    P_U(flush_steer_cycles), P_I(lazy_shr),
    P_D(axi_us), P_D(axi_write_us), P_D(ps_dispatch_us), P_U(amem_chunk),
    P_U(amem_request_axi), P_U(amem_begin_axi), P_U(amem_poll_axi),
    P_U(amem_end_axi), P_U(amem_dma_axi), P_U(amem_dma_poll_axi),
    P_U(amem_read_word_axi), P_U(amem_read_setup_axi),
    P_U(amem_write_word_axi), P_U(amem_write_setup_axi),
    P_U(amem_write_byte_axi), P_I(keep_lazy),
    P_U(slowdown_cycles), P_I(slowdown_slot4), P_I(slowdown_via_exempt),
    P_U(slow_done)
};
enum { SPEC_COUNT = sizeof specs / sizeof specs[0] };

int a2vm_cost_load(a2vm_cost_params *p, const char *path, char *error,
                   size_t error_size)
{
    uint8_t seen[SPEC_COUNT];
    char line[512];
    unsigned number = 0;
    FILE *file = fopen(path, "r");
    memset(p, 0, sizeof *p);
    memset(seen, 0, sizeof seen);
    if (!file) {
        snprintf(error, error_size, "cannot read %s", path);
        return 0;
    }
    while (fgets(line, sizeof line, file)) {
        char name[128], value[128], extra[8];
        number++;
        char *hash = strchr(line, '#');
        if (hash)
            *hash = 0;
        int n = sscanf(line, "%127s %127s %7s", name, value, extra);
        if (n <= 0)
            continue;
        if (n != 2) {
            snprintf(error, error_size, "%s:%u: NAME VALUE", path, number);
            fclose(file);
            return 0;
        }
        size_t i;
        for (i = 0; i < SPEC_COUNT; i++)
            if (!strcmp(name, specs[i].name))
                break;
        if (i == SPEC_COUNT) {
            snprintf(error, error_size, "%s:%u: unknown parameter %s", path,
                     number, name);
            fclose(file);
            return 0;
        }
        char *end;
        double v = strtod(value, &end);
        if (*end || v < 0 || (specs[i].type != 'd' && v != floor(v))) {
            snprintf(error, error_size, "%s:%u: bad value %s", path, number,
                     value);
            fclose(file);
            return 0;
        }
        char *field = (char *)p + specs[i].offset;
        if (specs[i].type == 'd')
            *(double *)field = v;
        else if (specs[i].type == 'u')
            *(unsigned *)field = (unsigned)v;
        else
            *(int *)field = (int)v;
        seen[i] = 1;
    }
    fclose(file);
    for (size_t i = 0; i < SPEC_COUNT; i++)
        if (!seen[i]) {
            snprintf(error, error_size, "%s: no value for %s", path,
                     specs[i].name);
            return 0;
        }
    if (!p->fabric_mhz || !p->line_us || !p->lines || !p->rw_lines ||
        p->rw_lines > COST_RW_LINES_MAX || !p->amem_chunk) {
        snprintf(error, error_size, "%s: a parameter is out of range", path);
        return 0;
    }
    return 1;
}

/* ---- construction ---- */

enum { MIRROR_BYTES = 0x20000 };

a2vm_cost *a2vm_cost_new(const a2vm_cost_params *p)
{
    a2vm_cost *c = calloc(1, sizeof *c);
    if (!c)
        return NULL;
    c->drain_at = calloc(MIRROR_BYTES, sizeof *c->drain_at);
    c->deferred = calloc(MIRROR_BYTES, 1);
    c->deferred_list = calloc(MIRROR_BYTES, sizeof *c->deferred_list);
    if (!c->drain_at || !c->deferred || !c->deferred_list) {
        a2vm_cost_free(c);
        return NULL;
    }
    c->p = *p;
    c->period = p->fabric_mhz * p->line_us / 65.0;
    c->admit_cycle = -1;
    c->phase_addr = -1;
    c->shr_selected = 0;
    c->instr_turbo = 1;
    return c;
}

void a2vm_cost_free(a2vm_cost *c)
{
    if (!c)
        return;
    free(c->drain_at);
    free(c->deferred);
    free(c->deferred_list);
    free(c);
}

uint64_t a2vm_cost_frame_clocks(const a2vm_cost *c)
{
    return (uint64_t)llround(c->period * 65.0 * c->p.lines);
}

/* ---- the Apple bus clock ---- */

/* The start of Apple cycle k (PHI0 falls; the address phase begins). */
static uint64_t cycle_start(const a2vm_cost *c, int64_t k)
{
    return (uint64_t)floor((double)k * c->period);
}

static int64_t cycle_of(const a2vm_cost *c, uint64_t t)
{
    int64_t k = (int64_t)floor((double)t / c->period);
    while (cycle_start(c, k + 1) <= t)
        k++;
    while (k > 0 && cycle_start(c, k) > t)
        k--;
    return k;
}

static uint64_t data_tap(const a2vm_cost *c)
{
    /* data_en: PHI0 rises half a cycle in, then tap 59
       (apple_bus_wrapper.sv:120) */
    return (uint64_t)llround(c->period / 2.0) + c->p.bus_data_tap;
}

/* The first cycle whose drive_en (tap 8, apple_bus_wrapper.sv:136) comes
   at or after `t`, and not before cycle `after`. */
static int64_t drive_cycle(const a2vm_cost *c, uint64_t t, int64_t after)
{
    int64_t k = cycle_of(c, t);
    if (cycle_start(c, k) + c->p.bus_drive_tap < t)
        k++;
    return k < after ? after : k;
}


/* ---- the video mirror ---- */

static int is_aux_video_range(unsigned a17)
{
    unsigned a = a17 & 0xffff;
    return (a17 & 0x10000) && a >= 0x2000 && a < 0xa000;
}

/* vtw_video_policy.sv: must the byte reach the motherboard promptly? */
static int mirror_active(const a2vm *m, unsigned a17)
{
    unsigned a = a17 & 0xffff;
    int aux = (a17 >> 16) & 1;
    int page2 = m->sw[SW_PAGE2] && !m->sw[SW_STORE80];
    int text_page = page2 ? (a >> 10) == 2 : (a >> 10) == 1;
    int hires_page = page2 ? (a >> 13) == 2 : (a >> 13) == 1;
    int graphics = (a >> 13) >= 1 && (a >> 13) <= 4;
    int extended = aux && graphics;
    int legacy = !aux && ((a >> 3) == (0x0878 >> 3) || (a >> 3) == (0x4078 >> 3));
    return extended || legacy ||
           (text_page && (m->sw[SW_TEXT] || m->sw[SW_MIXED] ||
                          !m->sw[SW_HIRES]) && (!aux || m->sw[SW_COL80])) ||
           (hires_page && !aux && !m->sw[SW_TEXT] && m->sw[SW_HIRES]);
}

static int mirror_pending(const a2vm_cost *c)
{
    return c->active_end > c->t || c->deferred_count > 0;
}

static int any_pending(const a2vm_cost *c)
{
    return mirror_pending(c) || c->lazy_count > 0;
}

/* A byte for the motherboard: drains in the next free bus cycle. */
static void drain_byte(a2vm_cost *c, unsigned a17)
{
    int64_t k = drive_cycle(c, c->t + 2, c->bus_next);
    uint64_t done = cycle_start(c, k) + data_tap(c);
    c->bus_next = k + 1;
    c->drain_at[a17] = cycle_start(c, k) + c->p.bus_drive_tap;
    if (done > c->active_end)
        c->active_end = done;
    if ((a17 & 0x10000) && done > c->aux_drain_end)
        c->aux_drain_end = done;
    c->c.posted++;
}

static void post(a2vm_cost *c, const a2vm *m, unsigned a17)
{
    if (c->p.lazy_shr && c->shr_selected && is_aux_video_range(a17)) {
        if (c->deferred[a17] == 0) {
            c->deferred[a17] = 2;
            c->deferred_list[c->list_used++] = a17;
            c->lazy_count++;
            c->lazy_aux++;
        } else if (c->deferred[a17] == 1) {
            /* a class change flushes first (lazy-mirror-spec.md 1); the
               renderer keeps SHR selected, so this does not arise */
            c->deferred[a17] = 2;
            c->deferred_count--;
            c->lazy_count++;
            if (a17 & 0x10000) {
                c->deferred_aux--;
                c->lazy_aux++;
            }
        }
        return;
    }
    if (mirror_active(m, a17)) {
        if (c->drain_at[a17] > c->t)
            return;                 /* coalesced: still waiting */
        drain_byte(c, a17);
        return;
    }
    if (c->deferred[a17] == 0) {
        c->deferred[a17] = 1;
        c->deferred_list[c->list_used++] = a17;
        c->deferred_count++;
        if (a17 & 0x10000)
            c->deferred_aux++;
    }
}

/* Flush deferred bytes (and lazy ones when `lazy`): the core waits while
   vtw_video_bank_sync steers RAMWRT and the coalescer writes each byte
   (:1408-1413, vtw_video_bank_sync.sv). Returns the clocks waited. */
static uint64_t flush(a2vm_cost *c, int lazy, int aux_only)
{
    uint32_t bytes = 0, kept = 0;
    int banks[2] = { 0, 0 };
    uint64_t start = c->t;
    for (uint32_t i = 0; i < c->list_used; i++) {
        uint32_t a17 = c->deferred_list[i];
        uint8_t kind = c->deferred[a17];
        int take = kind && (kind == 1 || lazy) &&
                   (!aux_only || (a17 & 0x10000));
        if (!take) {
            if (kind)
                c->deferred_list[kept++] = a17;
            continue;
        }
        c->deferred[a17] = 0;
        banks[(a17 >> 16) & 1] = 1;
        bytes++;
        if (kind == 1) {
            c->deferred_count--;
            if (a17 & 0x10000)
                c->deferred_aux--;
        } else {
            c->lazy_count--;
            if (a17 & 0x10000)
                c->lazy_aux--;
        }
    }
    c->list_used = kept;
    if (!bytes)
        return 0;
    unsigned steer = (unsigned)(banks[0] + banks[1]) * c->p.flush_steer_cycles;
    int64_t k = drive_cycle(c, c->t + 1, c->bus_next);
    k += bytes + steer;
    uint64_t done = cycle_start(c, k - 1) + data_tap(c) + 1;
    c->bus_next = k;
    if (banks[1] && done > c->aux_drain_end)
        c->aux_drain_end = done;
    c->c.posted += bytes;
    c->c.flushes++;
    c->c.bus_cycles += steer;
    if (done > c->t)
        c->t = done;
    return c->t - start;
}

/* ---- the TURBO caches (vtw_turbo_cache.sv) ---- */

static unsigned word_set(uint16_t a)
{
    /* BYTE_INDEX_BITS = 7 (:1174): a[6:2] ^ a[11:7] ^ (a[15:12] << 1) */
    return ((a >> 2) ^ (a >> 7) ^ ((a >> 12) << 1)) & 31;
}

static unsigned page_set(unsigned page)
{
    return (page ^ ((page >> 5) << 2)) & 31;
}

static void invalidate_turbo(a2vm_cost *c)
{
    memset(c->word_valid, 0, sizeof c->word_valid);
    memset(c->map_valid, 0, sizeof c->map_valid);
    c->c.invalidations++;
}

static uint32_t mapping_of(const a2vm *m)
{
    return (uint32_t)m->sw[SW_STORE80] | (uint32_t)m->sw[SW_RAMRD] << 1 |
           (uint32_t)m->sw[SW_RAMWRT] << 2 | (uint32_t)m->sw[SW_ALTZP] << 3 |
           (uint32_t)m->sw[SW_PAGE2] << 4 | (uint32_t)m->sw[SW_HIRES] << 5 |
           (uint32_t)m->sw[SW_INTCXROM] << 6 |
           (uint32_t)m->sw[SW_SLOTC3ROM] << 7 | (uint32_t)m->lc_read << 8 |
           (uint32_t)m->lc_write << 9 | (uint32_t)m->lc_bank2 << 10 |
           (uint32_t)m->bank << 11;
}

/* ---- where an access goes ---- */

enum { WHERE_FAST, WHERE_RAMWORKS };

/* The physical target of a mapped page: fast memory (with a unique
   physical page number) or a RamWorks bank. */
static int where(const a2vm *m, const uint8_t *p, uint32_t *phys,
                 unsigned *bank, uint32_t *offset)
{
    if (p >= m->main && p < m->main + sizeof m->main) {
        *phys = (uint32_t)((p - m->main) >> 8);
        return WHERE_FAST;
    }
    if (p >= m->lc && p < m->lc + sizeof m->lc) {
        *phys = 0x100 + (uint32_t)((p - m->lc) >> 8);
        return WHERE_FAST;
    }
    if (p >= m->lc1 && p < m->lc1 + sizeof m->lc1) {
        *phys = 0x140 + (uint32_t)((p - m->lc1) >> 8);
        return WHERE_FAST;
    }
    if (p >= m->rom && p < m->rom + sizeof m->rom) {
        *phys = 0x150 + (uint32_t)((p - m->rom) >> 8);
        return WHERE_FAST;
    }
    size_t o = (size_t)(p - m->aux_banks);
    *bank = (unsigned)(o >> 16);
    *offset = (uint32_t)(o & 0xffff);
    if (*bank == 0) {
        *phys = 0x200 + (*offset >> 8);
        return WHERE_FAST;
    }
    return WHERE_RAMWORKS;
}

static void charge(a2vm_cost *c, uint64_t clocks, uint64_t *bucket)
{
    c->t += clocks;
    *bucket += clocks;
}

static void fast_extra(a2vm_cost *c)
{
    if (c->p.turbo_extra > 0) {
        c->extra_fraction += c->p.turbo_extra;
        uint64_t whole = (uint64_t)c->extra_fraction;
        c->extra_fraction -= (double)whole;
        charge(c, whole, &c->c.fast_clocks);
    }
}

static void fast_read(a2vm_cost *c, uint16_t a, uint32_t phys)
{
    unsigned i = word_set(a);
    int hit = c->word_valid[i] && c->word_tag[i] == (a >> 7) &&
              (!c->p.caches_survive || c->word_phys[i] == phys);
    if (hit) {
        c->c.read_hits++;
        charge(c, c->p.turbo_hit, &c->c.fast_clocks);
    } else {
        c->c.misses++;
        charge(c, c->p.turbo_read_miss, &c->c.fast_clocks);
        if ((a >> 12) != 0xc) {
            c->word_valid[i] = 1;
            c->word_tag[i] = (uint16_t)(a >> 7);
            c->word_phys[i] = phys;
        }
    }
    fast_extra(c);
}

/* A write: 2 clocks through a fast page-table entry; otherwise TURBO_DONE,
   ROUTE, MEM_CAPTURE, MEM_DONE, with POST_STALL for a video write. */
static int fast_write(a2vm_cost *c, uint16_t a, uint32_t phys, int posted,
                      int aux0)
{
    unsigned page = a >> 8, i = page_set(page);
    int hit = c->map_valid[i] && c->map_fast[i] && c->map_tag[i] == page &&
              (!c->p.caches_survive || c->map_phys[i] == phys);
    if (hit) {
        charge(c, c->p.turbo_hit, &c->c.fast_clocks);
        fast_extra(c);
        return 0;
    }
    c->c.misses++;
    if ((a >> 12) != 0xc) {
        c->map_valid[i] = 1;
        c->map_tag[i] = (uint8_t)page;
        c->map_phys[i] = phys;
        c->map_fast[i] = !posted && !(aux0 && page == 0x9d);
    }
    if (posted) {
        charge(c, c->p.posted_write, &c->c.video_clocks);
        c->c.video_wait++;          /* the POST_STALL clock */
        return 1;
    }
    charge(c, c->p.turbo_write_miss, &c->c.fast_clocks);
    fast_extra(c);
    return 0;
}

/* ---- extended memory: the RamWorks line cache and the PSRAM ---- */

/* When the PSRAM admits an operation requested at `r`. */
static uint64_t admit(a2vm_cost *c, uint64_t r, unsigned busy)
{
    if (c->p.relaxed_admission) {
        uint64_t s = r > c->psram_free ? r : c->psram_free;
        /* a captured aux write (a mirror byte) takes an RMW at the start
           of its cycle's window, before the vTW (psram_simple.sv:439) */
        if (c->aux_drain_end && s < c->aux_drain_end + (uint64_t)c->period) {
            int64_t k = cycle_of(c, s);
            uint64_t rmw = cycle_start(c, k) + c->p.admit_offset;
            if (s >= rmw && s < rmw + c->p.drain_rmw)
                s = rmw + c->p.drain_rmw;
        }
        c->psram_free = s + busy;
        return s;
    }
    int64_t k = cycle_of(c, r);
    for (;;) {
        uint64_t open = cycle_start(c, k) + c->p.admit_offset;
        uint64_t close = open + c->p.admit_window;
        /* a captured aux mirror write takes the cycle after its own
           (psram_simple.sv:439-467, cache-review.md F9) */
        int blocked = k == c->admit_cycle ||
                      (c->aux_drain_end &&
                       cycle_start(c, k) < c->aux_drain_end + (uint64_t)c->period);
        if (!blocked && r < close) {
            c->admit_cycle = k;
            return r > open ? r : open;
        }
        k++;
    }
}

static void ramworks(a2vm_cost *c, unsigned bank, uint32_t offset, int write)
{
    uint32_t line = (uint32_t)bank << 13 | offset >> 3;
    unsigned n = c->p.rw_lines, victim = 0;
    uint64_t start = c->t;
    c->c.rw_accesses++;
    c->c.misses++;                  /* never a TURBO cache hit */
    c->rw_use++;
    for (unsigned i = 0; i < n; i++)
        if (c->rw[i].valid && c->rw[i].line == line) {
            c->rw[i].used = c->rw_use;
            c->rw[i].dirty |= (uint8_t)write;
            c->c.rw_hits++;
            charge(c, c->p.rw_hit, &c->c.rw_clocks);
            return;
        }
    for (unsigned i = 1; i < n; i++) {
        if (!c->rw[victim].valid)
            break;
        if (!c->rw[i].valid || c->rw[i].used < c->rw[victim].used)
            victim = i;
    }
    c->c.rw_misses++;
    /* X_CAPTURE, X_TURBO_DONE, X_ROUTE, then X_RW_LOOKUP issues */
    uint64_t r = c->t + c->p.rw_request;
    if (c->rw[victim].valid && c->rw[victim].dirty) {
        c->c.rw_dirty++;
        uint64_t s = admit(c, r, c->p.psram_write);
        r = s + c->p.psram_write;       /* X_RW_FLUSH (:2072-2079) */
    }
    /* back-to-back reads are 32 clocks apart (cache-review.md F8) */
    uint64_t s = admit(c, r, c->p.psram_read + 1);
    uint64_t done = s + c->p.psram_read;       /* X_RW_FILL, X_RW_DONE */
    c->rw[victim].valid = 1;
    c->rw[victim].dirty = (uint8_t)write;
    c->rw[victim].line = line;
    c->rw[victim].used = c->rw_use;
    uint64_t base = c->t + c->p.rw_hit;
    if (done < base)
        done = base;
    c->c.rw_wait += done - base;
    charge(c, done - start, &c->c.rw_clocks);
}

/* The dirty lines go back (a hold or a flush request): the line cache
   is written back and invalidated (:1804-1828). */
static uint64_t ramworks_flush(a2vm_cost *c)
{
    uint64_t start = c->t;
    for (unsigned i = 0; i < c->p.rw_lines; i++) {
        if (c->rw[i].valid && c->rw[i].dirty) {
            uint64_t s = admit(c, c->t, c->p.psram_write);
            c->t = s + c->p.psram_write;
        }
        c->rw[i].valid = c->rw[i].dirty = 0;
    }
    return c->t - start;
}

/* ---- $Cxxx ---- */

static int exposure(uint16_t a, int write)
{
    /* video_exposure_access (:1390-1401) */
    if ((a >> 12) == 0xc && ((a >> 7) & 0x1f) != 0)
        return 1;
    if ((a >> 4) == 0xc05)
        return 1;
    return write && ((a >> 1) == (0xc000 >> 1) || (a >> 2) == (0xc00c >> 2) ||
                     a == 0xc022 || a == 0xc029 || a == 0xc034 ||
                     a == 0xc035 || a == 0xc071 || a == 0xc073);
}

/* The quiet set of switches-review.md section 4: RAMRD, ALTZP, the
   language card and the RamWorks bank. */
static int quiet(const a2vm_cost *c, uint16_t a, int write)
{
    if (!c->p.quiet_switches || (a >> 8) != 0xc0)
        return 0;
    unsigned low = a & 0xff;
    if ((low >> 4) == 8)
        return 1;
    return write && (low == 0x02 || low == 0x03 || low == 0x08 ||
                     low == 0x09 || low == 0x71 || low == 0x73);
}

/* One real bus cycle, requested at the model's clock; returns when the
   core has the response (X_BUS, X_BUS_DONE). */
static void sync_cycle(a2vm_cost *c)
{
    int64_t k = drive_cycle(c, c->t + 1, c->bus_next);
    c->bus_next = k + 1;
    uint64_t done = cycle_start(c, k) + data_tap(c) + c->p.bus_done;
    c->c.bus_cycles++;
    if (done > c->t) {
        c->c.io_clocks += done - c->t;
        c->t = done;
    }
}

/* The reconciler of switches-review.md section 4: before a non-quiet
   access, replay each switch the motherboard has not seen, the bank first
   (after flushing aux bytes, rule O4). */
static void reconcile(a2vm_cost *c, a2vm *m, int bank_only)
{
    if (!c->p.quiet_switches)
        return;
    unsigned cycles = 0;
    if (c->phys_bank != m->bank) {
        if (c->deferred_aux || c->lazy_aux || c->aux_drain_end > c->t) {
            if (c->aux_drain_end > c->t) {
                c->c.flush_wait += c->aux_drain_end - c->t;
                c->t = c->aux_drain_end;
            }
            uint64_t lazy = c->lazy_aux;
            uint64_t waited = flush(c, 1, 1);
            c->c.flush_wait += waited;
            if (lazy) {
                c->c.lazy_flushes++;
                c->c.lazy_wait += waited;
            }
        }
        c->phys_bank = (uint8_t)m->bank;
        cycles++;
    }
    if (!bank_only) {
        if (c->phys_ramrd != m->sw[SW_RAMRD]) {
            c->phys_ramrd = m->sw[SW_RAMRD];
            cycles++;
        }
        if (c->phys_altzp != m->sw[SW_ALTZP]) {
            c->phys_altzp = m->sw[SW_ALTZP];
            cycles++;
        }
        if (c->phys_lc_read != m->lc_read || c->phys_lc_write != m->lc_write ||
            c->phys_lc_bank2 != m->lc_bank2) {
            /* write enable needs two reads (switches-plan.md 3.3) */
            cycles += m->lc_write ? 2 : 1;
            c->phys_lc_read = m->lc_read;
            c->phys_lc_write = m->lc_write;
            c->phys_lc_bank2 = m->lc_bank2;
        }
    }
    for (unsigned i = 0; i < cycles; i++)
        sync_cycle(c);
    c->c.reconcile_cycles += cycles;
}

static void sync_physical(a2vm_cost *c, const a2vm *m)
{
    c->phys_bank = (uint8_t)m->bank;
    c->phys_ramrd = m->sw[SW_RAMRD];
    c->phys_altzp = m->sw[SW_ALTZP];
    c->phys_lc_read = m->lc_read;
    c->phys_lc_write = m->lc_write;
    c->phys_lc_bank2 = m->lc_bank2;
}

static void io_access(a2vm_cost *c, a2vm *m, uint16_t a, int write,
                      uint8_t value)
{
    uint64_t start = c->t;
    c->c.io_accesses++;
    int is_quiet = quiet(c, a, write);
    int bank_write = write && (a == 0xc071 || a == 0xc073);
    int status = !write && (a >> 4) == 0xc01 && (a & 15) != 0;
    int read_bank = c->p.read_bank && write && a == 0xc069;
    int sp = 0, rom = 0;
    if (a >= 0xc100 && !m->sw[SW_INTCXROM] && m->amem_on) {
        /* slot 7: its ROM, and its C8 window once selected, are served
           inside the fabric (sp_hit, :674-702); $CFFF is not */
        if ((a >> 8) == 0xc7)
            sp = 1;
        else if (a >= 0xc800 && a != 0xcfff && m->amem.selected)
            sp = 1;
    }
    if (!write && a >= 0xc100 && m->sw[SW_INTCXROM])
        rom = 1;                    /* internal ROM: the ROM route */
    int bypass = is_quiet || read_bank;

    /* the active-pending barrier holds X_CAPTURE (:1414-1415, :1907) */
    if (!bypass && c->active_end > c->t) {
        uint64_t w = c->active_end - c->t;
        c->c.barrier_wait += w;
        c->c.video_wait += w;
        c->c.video_clocks += w;
        c->t = c->active_end;
    }
    if (!is_quiet && !status && !rom && !read_bank)
        reconcile(c, m, 0);
    charge(c, c->p.io_capture, &c->c.io_clocks);
    if (any_pending(c)) {
        charge(c, c->p.video_wait, &c->c.io_clocks);
        c->c.video_wait += c->p.video_wait;
        if (!bypass && mirror_pending(c) && exposure(a, write)) {
            uint64_t w = flush(c, 0, 0);
            c->c.flush_wait += w;
            c->c.video_wait += w;
        }
        /* a $C029 write that leaves SHR, or a physical bank write, takes
           the lazy bytes out first (lazy-mirror-review.md 3) */
        if (c->lazy_count && write &&
            ((a == 0xc029 && (value & 0xc0) != 0xc0) ||
             (bank_write && !is_quiet))) {
            uint64_t w = flush(c, 1, 0);
            c->c.lazy_flushes++;
            c->c.lazy_wait += w;
            c->c.video_wait += w;
        }
    }
    charge(c, c->p.io_route, &c->c.io_clocks);
    if (is_quiet || read_bank) {
        c->c.quiet++;
        charge(c, c->p.quiet_switch, &c->c.io_clocks);
    } else if (status) {
        c->c.io_private++;
        charge(c, c->p.status_read, &c->c.io_clocks);
    } else if (sp) {
        c->c.io_private++;
        charge(c, c->p.sp_private, &c->c.io_clocks);
    } else if (rom) {
        charge(c, c->p.rom_read, &c->c.io_clocks);
    } else
        sync_cycle(c);
    (void)start;
}

/* ---- the hooks ---- */

static void phase_to(a2vm_cost *c, unsigned phase)
{
    if (phase >= COST_PHASES)
        phase = COST_PHASES - 1;
    c->phase_clocks[c->phase] += c->t - c->phase_start;
    c->phase_start = c->t;
    c->phase = phase;
}

/* One access that is not a dropped dummy read: the path of its kind. */
static void access_read(a2vm_cost *c, a2vm *m, uint16_t address,
                        const uint8_t *page)
{
    c->c.accesses++;
    if (!page) {
        io_access(c, m, address, 0, 0);
        return;
    }
    uint32_t phys = 0, offset = 0;
    unsigned bank = 0;
    if (where(m, page, &phys, &bank, &offset) == WHERE_RAMWORKS)
        ramworks(c, bank, offset + (address & 0xff), 0);
    else
        fast_read(c, address, phys);
}

static void access_write(a2vm_cost *c, a2vm *m, uint16_t address,
                         uint8_t value, const uint8_t *page)
{
    c->c.accesses++;
    if (!page) {
        /* $Cxxx, or $D000-$FFFF with the card write-protected, which is
           a bus cycle too (globals.sv:320-334) */
        if (address >= 0xd000) {
            c->c.io_accesses++;
            charge(c, c->p.io_capture + c->p.io_route, &c->c.io_clocks);
            sync_cycle(c);
        } else
            io_access(c, m, address, 1, value);
        return;
    }
    uint32_t phys = 0, offset = 0;
    unsigned bank = 0;
    if (where(m, page, &phys, &bank, &offset) == WHERE_RAMWORKS) {
        ramworks(c, bank, offset + (address & 0xff), 1);
        return;
    }
    int aux0 = phys >= 0x200;
    if (c->phase_addr >= 0 && address == (unsigned)c->phase_addr &&
        page == m->main + (address & 0xff00))
        phase_to(c, value >> 1);
    /* a video-window write of main or aux bank 0 is posted
       (xl_is_posted, :565-569); a2vm's write flags mark exactly those */
    int posted = address < 0xc000 && m->wflag[address >> 8] != 0;
    if (posted && aux0 && c->p.quiet_switches && c->phys_bank != 0)
        reconcile(c, m, 1);         /* rule O2: the steer must match */
    if (fast_write(c, address, phys, posted, aux0))
        post(c, m, (unsigned)(aux0 ? 0x10000 : 0) | address);
}

/* ---- the slot-4 slowdown ----

   With the virtual Phasor enabled, the firmware puts slot 4 in the
   slowdown mask whatever the user chose (ps_sources/frontend/
   config_menu.c:4660-4692). An access to $C400-$C4FF (sd_iosel) or
   $C0C0-$C0CF (sd_slot_io) that the core completes, read or write, is a
   hit (:1119-1144): it loads slow_cnt_q with the window, and every other
   completed CPU cycle takes one off it (:1884-1898). While it is not zero
   the effective speed is 1 MHz (:1153-1171): a cycle completes only
   after an Apple data strobe that came after the previous cycle's end
   (pace_tick_pending_q, :1849-1856; pace_ok, :1159-1162), and the core
   runs its instructions without the TURBO shortcuts (w65c02_core.sv:
   instruction_turbo_q is taken at the opcode fetch, :1250, so an
   instruction that started slow keeps all its cycles). The caches are
   still filled on the way (turbo_map_fill and turbo_byte_fill, :1212-1215:
   X_ROUTE and X_MEM_CAPTURE, in any mode). FW-S1 (a proposal, not in
   F1.2.1; docs/firmware/fws1-spec.md as corrected by fws1-review.md)
   exempts writes to the VIA registers ORB and ORA without handshake
   (0 and F) only: exempt writes to IFR, IER or ORA would release the
   card's IRQ in TURBO and cause a second interrupt. */

static int slowdown_hit(const a2vm_cost *c, uint16_t a, int write)
{
    int iosel = (a >> 8) == 0xc4;
    if (!c->p.slowdown_cycles || (!iosel && (a & 0xfff0) != 0xc0c0))
        return 0;
    if (c->p.slowdown_via_exempt && write && iosel && !(a & 0x60)) {
        unsigned reg = a & 15;      /* not an SSI-263 write (addr bits 5-6) */
        if (reg == 0 || reg == 15)
            return 0;
    }
    return 1;
}

/* The end of a cycle at 1 MHz that started at `start` (the end of the
   previous one): the first data strobe after it, then slow_done clocks
   (complete_mem, :1514). */
static void pace(a2vm_cost *c, uint64_t start)
{
    int64_t k = cycle_of(c, start);
    uint64_t strobe = cycle_start(c, k) + data_tap(c);
    if (strobe <= start)
        strobe = cycle_start(c, k + 1) + data_tap(c);
    uint64_t done = strobe + c->p.slow_done;
    if (done > c->t)
        c->t = done;
}

static void slow_fill_word(a2vm_cost *c, uint16_t a, uint32_t phys)
{
    unsigned i = word_set(a);
    c->word_valid[i] = 1;
    c->word_tag[i] = (uint16_t)(a >> 7);
    c->word_phys[i] = phys;
}

/* A cycle while the window is open. */
static void slow_access(a2vm_cost *c, a2vm *m, uint16_t address,
                        uint8_t value, const uint8_t *page, int write)
{
    uint64_t start = c->t;
    c->c.accesses++;
    if (!page) {
        if (write && address >= 0xd000) {
            c->c.io_accesses++;
            charge(c, c->p.io_capture + c->p.io_route, &c->c.io_clocks);
            sync_cycle(c);
        } else
            io_access(c, m, address, write, value);
    } else {
        uint32_t phys = 0, offset = 0;
        unsigned bank = 0;
        if (where(m, page, &phys, &bank, &offset) == WHERE_RAMWORKS)
            ramworks(c, bank, offset + (address & 0xff), write);
        else if (!write) {
            /* X_CAPTURE, X_ROUTE, X_MEM_CAPTURE (the word is filled),
               X_MEM_DONE */
            charge(c, c->p.turbo_read_miss, &c->c.fast_clocks);
            if ((address >> 12) != 0xc)
                slow_fill_word(c, address, phys);
        } else {
            int aux0 = phys >= 0x200;
            if (c->phase_addr >= 0 && address == (unsigned)c->phase_addr &&
                page == m->main + (address & 0xff00))
                phase_to(c, value >> 1);
            int posted = address < 0xc000 && m->wflag[address >> 8] != 0;
            if (posted && aux0 && c->p.quiet_switches && c->phys_bank != 0)
                reconcile(c, m, 1);
            unsigned i = page_set(address >> 8);
            c->map_valid[i] = 1;
            c->map_tag[i] = (uint8_t)(address >> 8);
            c->map_phys[i] = phys;
            c->map_fast[i] = !posted && !(aux0 && (address >> 8) == 0x9d);
            charge(c, posted ? c->p.posted_write : c->p.turbo_write_miss,
                   posted ? &c->c.video_clocks : &c->c.fast_clocks);
            if (posted)
                post(c, m, (unsigned)(aux0 ? 0x10000 : 0) | address);
        }
    }
    pace(c, start);
    c->slow_left--;
    c->c.slow_cycles++;
    c->c.slow_clocks += c->t - start;
}

static void slow_after(a2vm_cost *c, uint16_t address, int write)
{
    if (slowdown_hit(c, address, write)) {
        c->slow_left = c->p.slowdown_cycles;
        c->c.slow_hits++;
    }
}

static void slowdown_read(a2vm *m, uint16_t address, const uint8_t *page,
                          int kind)
{
    a2vm_cost *c = m->cost;
    int io = (address >> 12) == 0xc;
    if (kind == CPU65C02_OPCODE)
        c->instr_turbo = c->slow_left == 0;
    if (c->slow_left)
        slow_access(c, m, address, 0, page, 0);
    else if (kind == CPU65C02_DUMMY && !io && c->instr_turbo) {
        if (m->core == A2VM_CORE_W65C02S &&
            m->cpu.state != CPU65C02_RUNNING)
            charge(c, c->p.turbo_hit, &c->c.fast_clocks);
        else
            c->c.dropped++;
        return;
    } else
        access_read(c, m, address, page);
    slow_after(c, address, 0);
}

void a2vm_cost_read(a2vm *m, uint16_t address, const uint8_t *page, int kind)
{
    a2vm_cost *c = m->cost;
    if (c->p.slowdown_slot4) {
        slowdown_read(m, address, page, kind);
        return;
    }
    int io = (address >> 12) == 0xc;
    if (kind == CPU65C02_DUMMY && !io) {
        /* TURBO omits dummy reads outside I/O (w65c02_core.sv:903-967),
           but a waiting or stopped core still takes time */
        if (m->core == A2VM_CORE_W65C02S &&
            m->cpu.state != CPU65C02_RUNNING)
            charge(c, c->p.turbo_hit, &c->c.fast_clocks);
        else
            c->c.dropped++;
        return;
    }
    access_read(c, m, address, page);
}

void a2vm_cost_write(a2vm *m, uint16_t address, uint8_t value,
                     const uint8_t *page, int kind)
{
    a2vm_cost *c = m->cost;
    (void)kind;
    if (c->p.slowdown_slot4) {
        if (c->slow_left)
            slow_access(c, m, address, value, page, 1);
        else
            access_write(c, m, address, value, page);
        slow_after(c, address, 1);
        return;
    }
    access_write(c, m, address, value, page);
}

void a2vm_cost_skip(a2vm *m, uint64_t clocks)
{
    a2vm_cost *c = m->cost;
    if (!c->slow_left)
        return;
    /* the idle loop's cycles, each at least an Apple cycle */
    uint64_t cycles = (uint64_t)((double)clocks / c->period);
    c->slow_left = cycles >= c->slow_left ? 0
                   : c->slow_left - (unsigned)cycles;
}

void a2vm_cost_after_io(a2vm *m, uint16_t address, int write, uint8_t value)
{
    a2vm_cost *c = m->cost;
    if (write && address == 0xc029)
        c->shr_selected = (value & 0xc0) == 0xc0;
    uint32_t mapping = mapping_of(m);
    if (mapping != c->mapping) {
        c->mapping = mapping;
        /* F1.2.1 clears both caches on any change of the translation
           state (:1206-1211); with the fast path each entry is checked
           against the physical page instead (switches-review.md 4) */
        if (!c->p.caches_survive)
            invalidate_turbo(c);
    }
    /* without quiet switches every switch is a bus cycle, so the
       motherboard has seen it; with them, reconcile() tracks it */
    if (!c->p.quiet_switches)
        sync_physical(c, m);
}

void a2vm_cost_attach(a2vm *m)
{
    a2vm_cost *c = m->cost;
    c->mapping = mapping_of(m);
    sync_physical(c, m);
    c->shr_selected = (m->newvideo & 0xc0) == 0xc0;
}

/* ---- the memory API (memory_api.c, memory_api_hw.c) ---- */

static uint64_t us(const a2vm_cost *c, double microseconds)
{
    return (uint64_t)llround(microseconds * c->p.fabric_mhz);
}

static uint64_t axi(const a2vm_cost *c, unsigned reads, unsigned writes)
{
    return us(c, reads * c->p.axi_us + writes * c->p.axi_write_us);
}

/* A DMA of `total` bytes (whole 8-byte lines) to or from the PSRAM: one
   admission an Apple cycle (psram_simple.sv:232-240), none of the core's
   traffic while it is held. */
static uint64_t dma(const a2vm_cost *c, uint32_t total, int write)
{
    uint32_t lines = total / 8;
    double each = c->p.relaxed_admission
                  ? (write ? c->p.psram_write : c->p.psram_read + 1)
                  : c->period;
    return axi(c, c->p.amem_dma_axi, 3) +
           (uint64_t)llround(lines * each) +
           axi(c, c->p.amem_dma_poll_axi, 0);
}

static uint64_t shadow_read(const a2vm_cost *c, uint32_t phys, uint32_t n)
{
    uint32_t words = ((phys + n + 3) & ~3u) / 4 - (phys & ~3u) / 4;
    return axi(c, c->p.amem_read_setup_axi + words * (c->p.amem_read_word_axi - 1),
               1 + words);
}

static uint64_t shadow_write(a2vm_cost *c, uint32_t phys, uint32_t n)
{
    uint32_t prefix = (4 - (phys & 3)) & 3;
    if (prefix > n)
        prefix = n;
    uint32_t words = (n - prefix) / 4, suffix = n - prefix - words * 4;
    /* each ARM write to the shadow pulses turbo_invalidate (:1207), and
       perf_count[5] counts each pulse (:1638) */
    c->c.invalidations += prefix + suffix + words;
    return axi(c, c->p.amem_write_setup_axi +
                      (prefix + suffix) * (c->p.amem_write_byte_axi - 1) +
                      words * (c->p.amem_write_word_axi - 1),
               2 + prefix + suffix + words);
}

static uint64_t amem_read(const a2vm_cost *c, uint32_t phys, uint32_t n)
{
    if (phys < 0x20000)
        return shadow_read(c, phys, n);
    uint32_t total = ((phys & 7) + n + 7) & ~7u;
    return dma(c, total, 0);
}

static uint64_t amem_write(a2vm_cost *c, uint32_t phys, uint32_t n)
{
    if (phys < 0x20000)
        return shadow_write(c, phys, n);
    uint32_t total = ((phys & 7) + n + 7) & ~7u;
    uint64_t t = 0;
    if ((phys & 7) || total != n)
        t += dma(c, total, 0);      /* keep the rest of partial lines */
    return t + dma(c, total, 1);
}

void a2vm_cost_amem(a2vm *m, const uint8_t *request, size_t length)
{
    a2vm_cost *c = m->cost;
    if (length < 20 || request[0] != 4)
        return;
    const uint8_t *data = request + 12;
    unsigned count = data[5];
    if (length != 20 + 16u * count)
        return;
    uint64_t start = c->t, bytes = 0;
    int lazy_target = 0;
    /* the PS pops the request and dispatches it */
    c->t += us(c, c->p.ps_dispatch_us) +
            axi(c, c->p.amem_request_axi + (unsigned)(length + 3) / 4, 0);
    for (unsigned i = 0; i < count; i++) {
        const uint8_t *d = data + 8 + 16 * i;
        unsigned space = d[6], bank = d[7];
        unsigned address = d[8] | d[9] << 8, size = d[10] | d[11] << 8;
        if (space == 1 && bank == 0 &&
            address < 0xa000 && address + size > 0x2000)
            lazy_target = 1;
    }
    /* hw_begin: the hold request flushes the mirror and the line cache
       before the core is held (:1408-1413, :1604-1611, :1723-1843) */
    c->t += axi(c, c->p.amem_begin_axi, 1);
    uint64_t hold = c->t;
    if (c->active_end > c->t)
        c->t = c->active_end;
    flush(c, !(c->p.keep_lazy && !lazy_target), 0);
    ramworks_flush(c);
    uint64_t poll = axi(c, c->p.amem_poll_axi, 0);
    c->t += poll;
    if (c->t - hold > poll)
        c->t = hold + ((c->t - hold + poll - 1) / poll) * poll;
    /* the transfers, in chunks of 504 bytes (memory_api.c:166-184) */
    for (unsigned i = 0; i < count; i++) {
        const uint8_t *d = data + 8 + 16 * i;
        unsigned op = d[0];
        uint32_t source = (d[2] == 0 ? 0u : (uint32_t)d[3] + 1) << 16 |
                          (uint32_t)(d[4] | d[5] << 8);
        uint32_t target = (d[6] == 0 ? 0u : (uint32_t)d[7] + 1) << 16 |
                          (uint32_t)(d[8] | d[9] << 8);
        uint32_t size = d[10] | d[11] << 8;
        for (uint32_t offset = 0; offset < size; offset += c->p.amem_chunk) {
            uint32_t n = size - offset;
            if (n > c->p.amem_chunk)
                n = c->p.amem_chunk;
            if (op == 1)
                c->t += amem_read(c, source + offset, n);
            c->t += amem_write(c, target + offset, n);
        }
        bytes += size;
    }
    c->t += axi(c, c->p.amem_end_axi, 2);
    invalidate_turbo(c);            /* arm_rw_flush_req, shadow writes */
    c->c.amem_requests++;
    c->c.amem_bytes += bytes;
    c->c.amem_clocks += c->t - start;
}

/* ---- the report ---- */

static void write_counters(FILE *out, const a2vm_cost_counters *now,
                           const a2vm_cost_counters *before)
{
#define FIELD(name) fprintf(out, ", \"" #name "\": %" PRIu64, \
                            now->name - (before ? before->name : 0))
    FIELD(accesses); FIELD(dropped); FIELD(read_hits); FIELD(misses);
    FIELD(invalidations); FIELD(video_wait); FIELD(bus_cycles);
    FIELD(posted); FIELD(io_accesses); FIELD(io_private); FIELD(quiet);
    FIELD(rw_accesses); FIELD(rw_hits); FIELD(rw_misses); FIELD(rw_dirty);
    FIELD(rw_wait); FIELD(barrier_wait); FIELD(flush_wait); FIELD(flushes);
    FIELD(lazy_flushes); FIELD(lazy_wait); FIELD(reconcile_cycles);
    FIELD(amem_requests); FIELD(amem_bytes); FIELD(amem_clocks);
    FIELD(fast_clocks); FIELD(rw_clocks); FIELD(io_clocks);
    FIELD(video_clocks);
#undef FIELD
}

static void write_slow_counters(FILE *out, const a2vm_cost_counters *now,
                                const a2vm_cost_counters *before)
{
#define FIELD(name) fprintf(out, ", \"" #name "\": %" PRIu64, \
                            now->name - (before ? before->name : 0))
    FIELD(slow_hits); FIELD(slow_cycles); FIELD(slow_clocks);
#undef FIELD
}

void a2vm_cost_boundary(a2vm *m, uint64_t boundary)
{
    a2vm_cost *c = m->cost;
    phase_to(c, c->phase);
    if (c->report) {
        fprintf(c->report, "{\"boundary\": %" PRIu64 ", \"t\": %" PRIu64
                ", \"clocks\": %" PRIu64 ", \"phases\": [", boundary, c->t,
                c->t - c->last_t);
        for (int i = 0; i < COST_PHASES; i++)
            fprintf(c->report, "%s%" PRIu64, i ? ", " : "",
                    c->phase_clocks[i] - c->last_phase[i]);
        fputs("]", c->report);
        write_counters(c->report, &c->c, &c->last_c);
        if (c->p.slowdown_slot4)
            write_slow_counters(c->report, &c->c, &c->last_c);
        fprintf(c->report, ", \"irqs\": %" PRIu64 "}\n", m->irqs);
        fflush(c->report);
    }
    c->last_t = c->t;
    memcpy(c->last_phase, c->phase_clocks, sizeof c->last_phase);
    c->last_c = c->c;
}

void a2vm_cost_final(a2vm *m, FILE *out)
{
    a2vm_cost *c = m->cost;
    phase_to(c, c->phase);
    fprintf(out, "  \"cost\": {\"t\": %" PRIu64 ", \"period\": %.4f, "
            "\"timed\": %d, \"phases\": [", c->t, c->period, c->timed);
    for (int i = 0; i < COST_PHASES; i++)
        fprintf(out, "%s%" PRIu64, i ? ", " : "", c->phase_clocks[i]);
    fputs("]", out);
    write_counters(out, &c->c, NULL);
    if (c->p.slowdown_slot4)
        write_slow_counters(out, &c->c, NULL);
    fputs("},\n", out);
}
